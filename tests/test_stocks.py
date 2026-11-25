"""The stock ticker (``stocks.py``): symbols, quote parsing, the strip and its scroll, the feed."""

from __future__ import annotations

import pytest

from scoreboard import stocks
from scoreboard.config import Settings, screen_sport
from scoreboard.stocks import (
    Quote,
    StockFeed,
    StockView,
    clean_symbol,
    is_moving,
    overflow,
    parse_symbols,
    quote_from_chart,
    scroll_px,
    slot_seconds,
    strip_width,
    symbol_problem,
    view_for,
    views,
)

# -- symbols ---------------------------------------------------------------------------------


@pytest.mark.parametrize("symbol", ["AAPL", "BRK-B", "^GSPC", "BTC-USD", "EURUSD=X", "RDS.A", "X"])
def test_yahoo_style_symbols_are_accepted(symbol):
    assert symbol_problem(symbol) == ""


@pytest.mark.parametrize("symbol", ["", "-AAPL", "A B", "AAPL!", "A" * 13, "$AAPL"])
def test_other_symbols_are_refused(symbol):
    assert symbol_problem(symbol)


def test_clean_symbol_trims_and_capitalises_and_ignores_non_text():
    assert clean_symbol("  aapl ") == "AAPL"
    assert clean_symbol(5) == ""


def test_parse_symbols_is_forgiving_and_caps_the_list():
    raw = ["aapl", "AAPL", "bad sym", "tsla", "msft", "goog", "amzn", "nvda"]
    assert parse_symbols(raw) == ["AAPL", "TSLA", "MSFT", "GOOG", "AMZN"]
    assert parse_symbols("AAPL") == []
    assert parse_symbols(None) == []


# -- the settings ----------------------------------------------------------------------------


def test_stocks_are_a_shared_rotation_screen_and_a_valid_one():
    assert screen_sport("stocks") == "shared"


def test_settings_default_to_no_stocks_and_clamp_the_pacing(tmp_path):
    assert Settings().stocks.symbols == []
    path = tmp_path / "s.toml"
    path.write_text('[stocks]\nsymbols = ["aapl", "tsla"]\nrefresh_seconds = 5\nspeed = 999\n')
    cfg = Settings.load(path).stocks
    assert cfg.symbols == ["AAPL", "TSLA"]
    assert cfg.refresh_seconds == stocks.REFRESH_MIN and cfg.speed == stocks.SPEED_MAX


def test_saving_stocks_keeps_the_rest_of_the_file(tmp_path):
    path = tmp_path / "s.toml"
    path.write_text("# mine\n[scoreboard]\nrotate_seconds = 9\n")
    settings = Settings.load(path)
    settings.save({"stocks": {"symbols": ["AAPL", "^GSPC"], "refresh_seconds": 120, "speed": 25}})
    assert settings.stocks.symbols == ["AAPL", "^GSPC"] and settings.stocks.speed == 25
    text = path.read_text()
    assert "# mine" in text and "rotate_seconds = 9" in text
    assert Settings.load(path).stocks.symbols == ["AAPL", "^GSPC"]


# -- parsing a chart payload -----------------------------------------------------------------


def chart(price, closes, pct=None, currency="USD"):
    meta = {"regularMarketPrice": price, "currency": currency}
    if pct is not None:
        meta["regularMarketChangePercent"] = pct
    return {"chart": {"result": [{"meta": meta, "indicators": {"quote": [{"close": closes}]}}]}}


def test_the_change_is_against_the_previous_close_not_the_start_of_the_window():
    quote = quote_from_chart("AAPL", chart(354.07, [352.45, 349.21, 342.56, 349.08, 354.07]))
    assert quote.price == 354.07
    assert quote.change == pytest.approx(354.07 - 349.08)
    assert quote.percent == pytest.approx((354.07 - 349.08) / 349.08 * 100)


def test_null_closes_are_skipped_and_one_close_falls_back_to_the_reported_percent():
    quote = quote_from_chart("X", chart(110.0, [None, 100.0], pct=10.0))
    assert quote.percent == pytest.approx(10.0) and quote.change == pytest.approx(10.0)


@pytest.mark.parametrize(
    "payload",
    [{}, {"chart": {"result": None}}, {"chart": {"result": []}}, chart(None, [1.0, 2.0]), "junk"],
)
def test_a_payload_without_a_price_is_no_quote(payload):
    assert quote_from_chart("X", payload) is None


# -- what is drawn ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "text"),
    [
        (354.073, "354.07"),
        (1234.56, "1234.6"),
        (59471.31, "59471"),
        (0.5, "0.5"),
        (0.00012, "0.0001"),
    ],
)
def test_price_text_keeps_to_what_the_panel_fits(price, text):
    assert stocks.price_text(price) == text


def test_view_for_marks_the_direction_and_a_missing_quote():
    up = view_for("AAPL", Quote("AAPL", 10.0, 0.1, 1.0))
    down = view_for("TSLA", Quote("TSLA", 10.0, -0.1, -1.0))
    flat = view_for("X", Quote("X", 10.0, 0.0, 0.001))
    assert (up.up, up.change) == (True, "+1.00%")
    assert (down.up, down.change) == (False, "-1.00%")
    assert (flat.up, flat.change) == (None, "0.00%")
    assert view_for("NOPE", None) == StockView("NOPE", "NO DATA", "", None)


def test_views_follow_the_configured_order_with_no_data_for_the_unknown():
    out = views(["B", "A"], {"A": Quote("A", 1.0, 0.0, 0.0)})
    assert [v.symbol for v in out] == ["B", "A"] and out[0].price == "NO DATA"


# -- the strip and its scroll -----------------------------------------------------------------


SHOWN = (
    StockView("AAPL", "354.07", "+1.43%", True),
    StockView("BTC-USD", "59471", "+2.10%", True),
)


def test_a_block_is_as_wide_as_its_wider_line_plus_the_gap():
    wide_price = StockView("X", "12345.6789", "", None)
    assert stocks.block_width(wide_price) == 10 * stocks.PRICE_CHAR_WIDTH + stocks.GAP
    wide_top = StockView("BTC-USD", "1", "+2.10%", True)
    top = 7 * stocks.SYMBOL_CHAR_WIDTH + stocks.DETAIL_CHAR_WIDTH * (1 + 6)
    assert stocks.block_width(wide_top) == top + stocks.GAP
    assert strip_width(SHOWN) == sum(stocks.block_width(v) for v in SHOWN)


FIVE = tuple(
    StockView(sym, "123.45", "+1.00%", True) for sym in ("AAPL", "TSLA", "MSFT", "GOOG", "AMZN")
)
ONE = (StockView("AAPL", "354.07", "+1.43%", True),)


def test_a_strip_wider_than_the_panel_overflows_by_what_hides_its_last_stock():
    assert overflow(FIVE, 128) == strip_width(FIVE) - stocks.GAP + 2 * stocks.EDGE - 128 > 0
    assert overflow(ONE, 128) == 0  # it all fits: the strip never moves
    assert overflow((), 128) == 0


def test_the_slot_starts_fully_painted_rests_scrolls_evenly_and_rests_on_the_last_stocks():
    seconds = slot_seconds(FIVE, 1, 20, 128)
    extra = overflow(FIVE, 128)
    assert scroll_px(FIVE, 0, seconds, 128) == 0  # the first paint: the first stocks, in place
    assert scroll_px(FIVE, stocks.HOLD_SECONDS, seconds, 128) == 0  # still resting
    assert scroll_px(FIVE, seconds / 2, seconds, 128) == round(extra / 2)
    assert scroll_px(FIVE, seconds - stocks.HOLD_SECONDS, seconds, 128) == extra
    assert scroll_px(FIVE, seconds, seconds, 128) == extra  # and stays on the last stocks
    assert scroll_px(FIVE, 99, seconds, 128) == extra  # clamped


def test_a_strip_that_fits_never_moves_and_nothing_is_not_an_error():
    assert [scroll_px(ONE, t, 10, 128) for t in (0, 5, 10)] == [0, 0, 0]
    assert scroll_px((), 5, 10, 128) == 0
    assert not is_moving(ONE, 5, 10, 128)


def test_the_fast_loop_only_runs_between_the_two_rests():
    seconds = slot_seconds(FIVE, 1, 20, 128)
    hold = stocks.HOLD_SECONDS
    assert [
        is_moving(FIVE, t, seconds, 128) for t in (0, hold - 0.1, hold, seconds - hold - 0.1)
    ] == [
        False,
        False,
        True,
        True,
    ]
    assert not is_moving(FIVE, seconds - hold, seconds, 128)


def test_the_slot_lasts_both_rests_and_the_scroll_at_the_speed_but_never_less_than_the_row():
    needed = 2 * stocks.HOLD_SECONDS + overflow(FIVE, 128) / 20
    assert slot_seconds(FIVE, 1, 20, 128) == pytest.approx(needed)
    assert slot_seconds(FIVE, 500, 20, 128) == 500
    assert slot_seconds(ONE, 9, 20, 128) == 9  # nothing to scroll: the row's seconds
    assert slot_seconds((), 9, 20, 128) == 9


# -- the feed --------------------------------------------------------------------------------


class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.asked = []
        self.closed = False

    def quote(self, symbol):
        self.asked.append(symbol)
        answer = self.answers.get(symbol)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self):
        self.closed = True


def feed(symbols=("AAPL", "TSLA")):
    return StockFeed(lambda: list(symbols), lambda: 60.0, monotonic=lambda: 7.0)


def test_a_pass_publishes_every_quote_and_when_it_finished():
    f = feed()
    assert f.snapshot().fetched_at is None
    f.poll_once(
        FakeClient({"AAPL": Quote("AAPL", 1.0, 0.0, 0.0), "TSLA": Quote("TSLA", 2.0, 0.0, 0.0)}),
        ["AAPL", "TSLA"],
    )
    snap = f.snapshot()
    assert set(snap.quotes) == {"AAPL", "TSLA"} and snap.fetched_at == 7.0


def test_a_failed_symbol_keeps_its_last_quote_and_does_not_stop_the_others():
    f = feed()
    first = Quote("AAPL", 1.0, 0.0, 0.0)
    f.poll_once(FakeClient({"AAPL": first, "TSLA": Quote("TSLA", 2.0, 0.0, 0.0)}), ["AAPL", "TSLA"])
    f.poll_once(
        FakeClient({"AAPL": RuntimeError("boom"), "TSLA": Quote("TSLA", 3.0, 0.0, 0.0)}),
        ["AAPL", "TSLA"],
    )
    quotes = f.snapshot().quotes
    assert quotes["AAPL"] == first and quotes["TSLA"].price == 3.0


def test_a_symbol_the_feed_does_not_know_has_no_quote_and_one_removed_is_dropped():
    f = feed()
    f.poll_once(FakeClient({"AAPL": Quote("AAPL", 1.0, 0.0, 0.0)}), ["AAPL", "NOPE"])
    assert set(f.snapshot().quotes) == {"AAPL"}
    f.poll_once(FakeClient({"TSLA": Quote("TSLA", 2.0, 0.0, 0.0)}), ["TSLA"])
    assert set(f.snapshot().quotes) == {"TSLA"}


def test_a_pass_where_every_request_fails_does_not_look_fresh():
    f = feed()
    f.poll_once(FakeClient({"AAPL": RuntimeError("down")}), ["AAPL"])
    assert f.snapshot().fetched_at is None


def test_the_thread_idles_without_symbols_then_fetches_and_stops_cleanly():
    import time

    symbols: list[str] = []
    client = FakeClient({"AAPL": Quote("AAPL", 1.0, 0.0, 0.0)})
    f = StockFeed(lambda: symbols, lambda: 60.0, client_factory=lambda: client)
    f.start()
    time.sleep(0.05)
    assert client.asked == []
    f.stop()
    assert f.snapshot().fetched_at is None
    symbols.append("AAPL")
    f.start()
    for _ in range(100):
        if client.asked:
            break
        time.sleep(0.02)
    f.stop()
    assert client.asked == ["AAPL"] and client.closed


# -- the client ------------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        return self.response

    def close(self):
        pass


def test_the_client_asks_yahoo_for_five_days_of_daily_closes_and_escapes_the_symbol():
    session = FakeSession(FakeResponse(200, chart(354.07, [349.08, 354.07])))
    quote = stocks.YahooClient(session).quote("^GSPC")
    url, params, timeout = session.calls[0]
    assert url == f"{stocks.YAHOO_URL}/%5EGSPC"
    assert params == {"interval": "1d", "range": "5d"} and timeout == stocks.REQUEST_TIMEOUT
    assert quote.symbol == "^GSPC" and quote.price == 354.07
    assert "scoreboard" in session.headers["User-Agent"]


def test_the_client_returns_no_quote_for_an_unknown_symbol_and_raises_on_a_server_error():
    assert stocks.YahooClient(FakeSession(FakeResponse(404))).quote("NOPE") is None
    with pytest.raises(RuntimeError):
        stocks.YahooClient(FakeSession(FakeResponse(503))).quote("AAPL")
