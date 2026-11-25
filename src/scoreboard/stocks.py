"""The stock ticker idle screen: the rules, the quotes and the feed behind it.

``[stocks]`` lists up to ``STOCKS_MAX`` symbols; the opt-in ``stocks`` rotation screen draws them
as a strip that starts fully painted and scrolls left to show the rest. Everything here is pure
except ``YahooClient`` (one HTTP GET per symbol) and ``StockFeed`` (the thread that calls it), so
the config loader, the admin save, both sports' rotations and the renderer share one rule set.

**Source.** Yahoo Finance's public chart endpoint
(``query1.finance.yahoo.com/v8/finance/chart``): no account or key, one small request per symbol,
US quotes up to 15 minutes delayed. It is unofficial, so the client is the one place to change if
Yahoo moves or blocks it (a keyed provider such as Finnhub would replace ``YahooClient`` and
nothing else). A failed symbol keeps its last quote and is retried on the next refresh; a symbol
Yahoo does not know shows ``NO DATA`` in grey.

**Symbols** are Yahoo's: ``AAPL``, ``BRK-B``, ``^GSPC`` (an index), ``BTC-USD``, ``EURUSD=X``.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)

STOCKS_MAX = 5

REFRESH_DEFAULT = 300.0
REFRESH_MIN = 60.0
REFRESH_MAX = 3600.0

#: Scroll speed in pixels per second: slow enough to read a price, fast enough to cross in a slot.
SPEED_DEFAULT = 20.0
SPEED_MIN = 8.0
SPEED_MAX = 60.0

SYMBOL_MAX_LENGTH = 12
_SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]*$")

#: The renderer's fonts are fixed-width: the symbol is 6x10, the change 5x7 and the price 7x13. Kept
#: here so the strip's width (and so the slot's length) is known without a renderer, as football's
#: idle screens need.
SYMBOL_CHAR_WIDTH = 6
DETAIL_CHAR_WIDTH = 5
PRICE_CHAR_WIDTH = 7
#: Blank pixels after each stock, with a thin divider in the middle of them.
GAP = 14
NO_DATA_TEXT = "NO DATA"

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
USER_AGENT = "scoreboard/0.1 (+https://github.com/diggforbeer/scoreboard)"
REQUEST_TIMEOUT = 8.0


# -- symbols and settings ---------------------------------------------------------------------


def clean_symbol(value: object) -> str:
    """A symbol as the feed spells it: trimmed, capitals. Not checked (see ``symbol_problem``)."""
    return str(value).strip().upper() if isinstance(value, str) else ""


def symbol_problem(symbol: str) -> str:
    """Why ``symbol`` cannot be asked of the feed, or ``""`` when it can."""
    if not symbol:
        return "enter a symbol"
    if len(symbol) > SYMBOL_MAX_LENGTH:
        return f"at most {SYMBOL_MAX_LENGTH} characters"
    if not _SYMBOL.match(symbol):
        return "letters, numbers and . - = ^ only"
    return ""


def parse_symbols(raw: object) -> list[str]:
    """The config loader's forgiving read: capitals, bad and repeated symbols dropped, at most
    ``STOCKS_MAX`` kept (and logged, never fatal)."""
    if not isinstance(raw, (list, tuple)):
        if raw not in (None, ""):
            log.warning("stocks.symbols must be a list of symbols; ignoring %r", raw)
        return []
    out: list[str] = []
    for item in raw:
        symbol = clean_symbol(item)
        if symbol_problem(symbol):
            log.warning("Ignoring stocks symbol %r: %s", item, symbol_problem(symbol) or "invalid")
            continue
        if symbol in out:
            continue
        if len(out) >= STOCKS_MAX:
            log.warning("Ignoring stocks symbol %s: at most %d are shown", symbol, STOCKS_MAX)
            continue
        out.append(symbol)
    return out


def clamp(value: object, low: float, high: float, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return min(max(float(value), low), high)


# -- quotes and what is drawn -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Quote:
    """One symbol's last answer from the feed."""

    symbol: str
    price: float
    #: Change since the previous close, in price units and per cent.
    change: float
    percent: float
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class StockView:
    """A stock as drawn: all text, plus which way it moved (``None`` for flat or unknown)."""

    symbol: str
    price: str
    change: str
    up: bool | None


def price_text(price: float) -> str:
    """``354.07``, ``1,234.5`` is too wide for the panel, so thousands drop their cents."""
    if price >= 10000:
        return f"{price:.0f}"
    if price >= 1000:
        return f"{price:.1f}"
    if price >= 1:
        return f"{price:.2f}"
    return f"{price:.4f}".rstrip("0").rstrip(".") if price else "0"


def change_text(percent: float) -> str:
    """``+1.43%`` / ``-0.20%`` (an exact zero is ``0.00%``)."""
    return f"{percent:+.2f}%" if abs(percent) >= 0.005 else "0.00%"


def view_for(symbol: str, quote: Quote | None) -> StockView:
    if quote is None:
        return StockView(symbol, NO_DATA_TEXT, "", None)
    up = None if abs(quote.percent) < 0.005 else quote.percent > 0
    return StockView(symbol, price_text(quote.price), change_text(quote.percent), up)


def views(symbols: Sequence[str], quotes: dict[str, Quote]) -> tuple[StockView, ...]:
    """The configured symbols in order, each with its quote or the no-data card."""
    return tuple(view_for(symbol, quotes.get(symbol)) for symbol in symbols)


# -- the strip and its scroll ------------------------------------------------------------------


def block_width(view: StockView) -> int:
    """Pixels one stock takes, gap included: the wider of its top line (symbol, then the change)
    and its price."""
    top = len(view.symbol) * SYMBOL_CHAR_WIDTH
    if view.change:
        top += DETAIL_CHAR_WIDTH + len(view.change) * DETAIL_CHAR_WIDTH
    return max(top, len(view.price) * PRICE_CHAR_WIDTH) + GAP


def strip_width(shown: Iterable[StockView]) -> int:
    return sum(block_width(v) for v in shown)


#: Seconds the strip rests at each end of its scroll: long enough to read the first stocks as the
#: screen paints, and the last ones as it settles. (Hockey's standings tables use the same rule.)
HOLD_SECONDS = 2.0
#: Blank pixels kept beside the first and last stock, so neither sits against the panel's edge.
EDGE = 2


def overflow(shown: Iterable[StockView], panel_width: int) -> int:
    """Pixels the strip is wider than the panel: how far it has to move to show its last stock.
    0 when every stock fits, and then the strip never moves."""
    return max(0, strip_width(shown) - GAP + 2 * EDGE - panel_width)


def slot_seconds(
    shown: Sequence[StockView], minimum: float, speed: float, panel_width: int
) -> float:
    """The slot's length: ``minimum`` (the rotation row's seconds), or longer if resting at both
    ends and moving the overflow at ``speed`` px/s takes more, so every price is seen."""
    extra = overflow(shown, panel_width)
    if not shown or extra <= 0:
        return minimum
    return max(minimum, 2 * HOLD_SECONDS + extra / max(speed, SPEED_MIN))


def scroll_px(shown: Sequence[StockView], offset: float, seconds: float, panel_width: int) -> int:
    """How far left the strip has moved ``offset`` seconds into a ``seconds`` slot. The slot starts
    fully painted (0: the first stocks fill the panel), rests, moves evenly, and rests again on the
    last stocks (``overflow``)."""
    extra = overflow(shown, panel_width)
    hold = min(HOLD_SECONDS, seconds / 4)
    moving_seconds = seconds - 2 * hold
    if not shown or extra <= 0 or moving_seconds <= 0:
        return 0
    progress = min(1.0, max(0.0, (offset - hold) / moving_seconds))
    return round(progress * extra)


def is_moving(shown: Sequence[StockView], offset: float, seconds: float, panel_width: int) -> bool:
    """Whether the strip is between its two rests (the board runs its fast loop then)."""
    hold = min(HOLD_SECONDS, seconds / 4)
    return overflow(shown, panel_width) > 0 and hold <= offset < seconds - hold


# -- the feed ----------------------------------------------------------------------------------


class YahooClient:
    """Quotes from Yahoo's chart endpoint. One request per symbol; ``None`` when it has none."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def close(self) -> None:
        self._session.close()

    def quote(self, symbol: str) -> Quote | None:
        response = self._session.get(
            f"{YAHOO_URL}/{requests.utils.quote(symbol, safe='')}",
            params={"interval": "1d", "range": "5d"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return quote_from_chart(symbol, response.json())


def quote_from_chart(symbol: str, payload: Any) -> Quote | None:
    """A ``Quote`` from a chart payload, or ``None`` if it carries no usable price.

    The change is against the **previous close**: the chart's own ``chartPreviousClose`` is the
    close before the whole 5-day window, so it is read off the daily closes instead (the last
    two), with ``regularMarketChangePercent`` as the fallback when there are fewer than two.
    """
    try:
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            return None
        closes = [
            c
            for c in ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close")
            or []
            if isinstance(c, (int, float))
        ]
        previous: float | None = None
        if len(closes) >= 2 and closes[-2]:
            previous = closes[-2]
        if previous:
            change = price - previous
            percent = change / previous * 100
        else:
            percent = float(meta.get("regularMarketChangePercent") or 0.0)
            change = price * percent / (100 + percent) if percent > -100 else 0.0
        return Quote(symbol, float(price), change, percent, str(meta.get("currency") or "USD"))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        log.warning("Unusable chart payload for %s", symbol, exc_info=True)
        return None


@dataclass(frozen=True, slots=True)
class StockSnapshot:
    """What the render loop reads: the latest quote per symbol and when the last pass ended."""

    quotes: dict[str, Quote]
    fetched_at: float | None = None


class StockFeed:
    """Refreshes the configured symbols on its own thread; the render loop only reads ``snapshot``.

    ``symbols`` and ``refresh`` are read each pass, so an admin-page change applies without a
    restart. With no symbols it idles. A symbol whose request fails (or that Yahoo does not know)
    keeps its previous quote, so a blip never blanks the screen.
    """

    def __init__(
        self,
        symbols: Callable[[], Sequence[str]],
        refresh: Callable[[], float],
        client_factory: Callable[[], Any] = YahooClient,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._symbols = symbols
        self._refresh = refresh
        self._client_factory = client_factory
        self._monotonic = monotonic
        self._snapshot = StockSnapshot({})
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> StockSnapshot:
        with self._lock:
            return self._snapshot

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="stocks-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        client = None
        try:
            while not self._stop.is_set():
                symbols = list(self._symbols())
                if symbols:
                    client = client or self._client_factory()
                    self.poll_once(client, symbols)
                    wait = clamp(self._refresh(), REFRESH_MIN, REFRESH_MAX, REFRESH_DEFAULT)
                else:
                    wait = 5.0  # nothing to fetch: look again soon, in case symbols were added
                if self._stop.wait(wait):
                    break
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    log.debug("closing the stocks client failed", exc_info=True)

    def poll_once(self, client: Any, symbols: Sequence[str]) -> None:
        """One pass over ``symbols``; public so tests drive it without the thread."""
        with self._lock:
            quotes = {s: q for s, q in self._snapshot.quotes.items() if s in symbols}
        got_any = False
        for symbol in symbols:
            try:
                quote = client.quote(symbol)
            except Exception as exc:
                log.warning("Stock quote for %s failed: %s", symbol, exc)
                continue
            if quote is None:
                log.info("No quote for stock symbol %s", symbol)
                quotes.pop(symbol, None)
                continue
            quotes[symbol] = quote
            got_any = True
        with self._lock:
            self._snapshot = StockSnapshot(
                quotes, self._monotonic() if got_any else self._snapshot.fetched_at
            )
