"""Tests for the stdlib status page (#48)."""

from __future__ import annotations

import urllib.error
import urllib.request

from nhl_scoreboard.status_server import StatusServer, _render_html


def test_render_html_escapes_and_includes_values():
    body = _render_html({"scene": "game", "favourite team": "<script>"}).decode("utf-8")
    assert "game" in body
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_status_server_serves_snapshot_over_http():
    snapshot = {"scene": "preview", "favourite team": "NSH"}
    server = StatusServer(snapshot=lambda: snapshot, port=0, host="127.0.0.1")
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert "preview" in body
        assert "NSH" in body
    finally:
        server.stop()


def test_status_server_404s_on_unknown_paths():
    server = StatusServer(snapshot=dict, port=0, host="127.0.0.1")
    server.start()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/nope", timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("expected a 404")
    finally:
        server.stop()
