"""The admin page's Cache tab: what is cached, and clearing it (cache_view, app, football mode)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime

import pytest

from scoreboard import admin_server
from scoreboard.cache_view import item, jsonable, matches, valid_scope


@dataclass(frozen=True, slots=True)
class Inner:
    when: datetime
    names: tuple[str, ...]


def test_jsonable_flattens_slotted_dataclasses_dates_and_mappings():
    out = jsonable({"a": Inner(datetime(2026, 11, 16, 20, 0), ("x", "y")), 7: {1, 2}.__class__})
    assert out["a"] == {"when": "2026-11-16T20:00:00", "names": ["x", "y"]}
    assert isinstance(out["7"], str)


def test_an_item_is_cut_to_the_cap_and_says_so():
    big = item("hockey:x", "hockey", "X", 12.34, "big", ["x" * 100] * 500)
    assert big["truncated"] and len(big["data"]) <= 8000 and big["age_seconds"] == 12.3
    small = item("hockey:y", "hockey", "Y", None, "small", [1], clear=False)
    assert not small["truncated"] and small["age_seconds"] is None and not small["clearable"]


def test_scopes_match_all_a_sport_or_one_item():
    assert matches("all", "hockey:standings") and matches("hockey", "hockey:standings")
    assert matches("hockey:standings", "hockey:standings")
    assert not matches("football", "hockey:standings") and not matches(
        "hockey:leaders", "hockey:standings"
    )
    keys = ["hockey:standings", "football:week"]
    assert (
        valid_scope("all", keys)
        and valid_scope("football", keys)
        and valid_scope("football:week", keys)
    )
    assert (
        not valid_scope("football:nope", keys)
        and not valid_scope(None, keys)
        and not valid_scope(3, keys)
    )


# -- the app -----------------------------------------------------------------------------------

from test_admin_server import app_dir, config_path  # noqa: E402,F401  (fixtures)
from test_app_priority import NSH, TEN, Rig, backend, nsh_far, ten_far  # noqa: E402,F401


def test_the_app_lists_hockeys_and_footballs_caches_and_clears_by_scope(backend):  # noqa: F811
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_far()]
    rig.poll(1)
    app = rig.app
    app._leaders = ("NSH", app.monotonic() - 30, None)
    app._season_series = {5: (app.monotonic() - 5, None)}
    keys = {i["key"] for i in app.cache_items()}
    assert {"hockey:leaders", "hockey:season_series:5"} <= keys
    leaders = next(i for i in app.cache_items() if i["key"] == "hockey:leaders")
    assert 29 < leaders["age_seconds"] < 32

    assert app.request_cache_clear("hockey:leaders") is True
    assert app._leaders is not None, "only a note is left; the render loop clears it"
    app._apply_cache_clears()
    assert app._leaders is None and app._season_series != {}
    assert app.request_cache_clear("hockey") and (app._apply_cache_clears() or True)
    assert app._season_series == {}
    assert app.request_cache_clear("nonsense") is False


def test_clearing_all_asks_footballs_worker_to_forget_its_idle_data(backend):  # noqa: F811
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_far()]
    rig.poll(1)
    football = rig.app._football
    assert football is not None
    football.request_clear("football:schedule:TEN")
    assert football._clear_requests == {"football:schedule"}, "a team's item clears its kind"
    rig.app.request_cache_clear("football")
    rig.app._apply_cache_clears()
    assert "football" in football._clear_requests
    football.worker.poll_once()
    assert football._clear_requests == set()
    assert (
        football.snapshot.idle.schedules == {} and football.snapshot.idle.standings_cached is None
    )


# -- the admin page ----------------------------------------------------------------------------


@pytest.fixture
def hooks(monkeypatch):
    cleared = []
    monkeypatch.setattr(
        admin_server, "CACHE_ITEMS", lambda: [item("hockey:a", "hockey", "A", 1.0, "s", [1])]
    )
    monkeypatch.setattr(
        admin_server, "CACHE_CLEARER", lambda scope: cleared.append(scope) or scope != "bad"
    )
    return cleared


def test_the_cache_payload_is_the_items(hooks):
    payload = admin_server._cache_payload()
    assert payload["type"] == "cache" and payload["items"][0]["key"] == "hockey:a"


def test_the_cache_payload_survives_a_dict_changing_size_mid_copy(monkeypatch):
    def boom():
        raise RuntimeError("dictionary changed size during iteration")

    monkeypatch.setattr(admin_server, "CACHE_ITEMS", boom)
    assert admin_server._cache_payload() == {"type": "cache", "items": []}


def test_cache_messages_over_the_websocket(app_dir, config_path, hooks):  # noqa: F811
    from test_admin_server import _serve_and_run, _skip_initial

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "cache_get"}))
        got = json.loads(await client.recv())
        await client.send(json.dumps({"type": "cache_clear", "scope": "hockey"}))
        cleared = json.loads(await client.recv())
        await client.send(json.dumps({"type": "cache_clear", "scope": "bad"}))
        bad = json.loads(await client.recv())
        return got, cleared, bad

    got, cleared, bad = asyncio.run(_serve_and_run(scenario))
    assert got["type"] == "cache" and got["items"][0]["key"] == "hockey:a"
    assert cleared == {"type": "cache_cleared", "scope": "hockey"}
    assert bad["type"] == "error" and bad["section"] == "cache"
    assert hooks == ["hockey", "bad"]
