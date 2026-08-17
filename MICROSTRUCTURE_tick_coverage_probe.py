#!/usr/bin/env python3
"""Non-destructive MT5 historical tick coverage diagnostic.

This probe writes no research outputs and computes no Flow-Mark lifecycle/outcomes.
It exists only to diagnose historical copy_ticks_range coverage after the Map01R
full run returned a long zero-tick streak despite known isolated availability.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    import MetaTrader5 as mt5
except ImportError as exc:
    raise SystemExit("MetaTrader5 not installed. Run: pip install MetaTrader5") from exc

BRT = ZoneInfo("America/Sao_Paulo")
DEFAULT_DATES = (
    "2026-04-20",
    "2026-04-21",
    "2026-05-15",
    "2026-06-15",
    "2026-07-15",
    "2026-08-11",
    "2026-08-12",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MT5 tick coverage diagnostic; no outputs modified")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--dates", nargs="*", default=list(DEFAULT_DATES), help="BRT YYYY-MM-DD dates")
    p.add_argument("--retries", type=int, default=2, help="extra retries after an empty result")
    return p.parse_args()


def brt_day_range(text: str) -> tuple[datetime, datetime]:
    d = date.fromisoformat(text)
    start = datetime.combine(d, time(0, 0), tzinfo=BRT)
    end = datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=BRT) - timedelta(milliseconds=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def init(symbol: str) -> None:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"symbol_info({symbol}) returned None: {mt5.last_error()}")
    if not info.visible and not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")


def main() -> int:
    args = parse_args()
    symbol = str(args.symbol).strip()
    retries = max(0, int(args.retries))

    print("=" * 108)
    print("MICROSTRUCTURE MT5 TICK COVERAGE PROBE — NON-DESTRUCTIVE")
    print("=" * 108)
    print(f"symbol      = {symbol}")
    print("writes      = NONE")
    print("lifecycle   = NONE")
    print("outcomes    = NONE")
    print("purpose     = diagnose copy_ticks_range zero-tick streak only")
    print()

    init(symbol)
    try:
        for text in args.dates:
            start_utc, end_utc = brt_day_range(text)
            count = 0
            for attempt in range(retries + 1):
                raw = mt5.copy_ticks_range(symbol, start_utc, end_utc, mt5.COPY_TICKS_ALL)
                err = mt5.last_error()
                count = 0 if raw is None else len(raw)
                print(
                    f"{text} attempt={attempt+1}/{retries+1} ticks={count:<9} "
                    f"last_error={err}",
                    flush=True,
                )
                if count > 0:
                    break
                if attempt < retries:
                    mt5.shutdown()
                    init(symbol)
    finally:
        mt5.shutdown()

    print()
    print("PROBE_COMPLETE = YES")
    print("RESEARCH_OUTPUTS_MODIFIED = NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
