#!/usr/bin/env python3
"""Prospective shadow collector for frozen MICROSTRUCTURE QUOTE-MIGRATION MAP 02.

This file must collect only fresh Map01R PASS rows and must never score Map02.
Scientific contract: docs/MICROSTRUCTURE_QUOTE_MIGRATION_MAP02.md

Frozen prospective start: 2026-08-19 00:00 BRT.
The collector processes completed BRT days only, reuses Map01R episode/lifecycle/
outcome semantics unchanged, and appends compact PASS rows to a prospective ledger.
AUC/CI remain sealed until the separate Map02 scorer reaches frozen maturity.
"""
from __future__ import annotations

import argparse
import math
import time as walltime
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import MetaTrader5 as mt5

import MICROSTRUCTURE_flow_mark_map as fm

FRESH_START = date(2026, 8, 19)
RETRIES = 3
RETRY_SLEEP_S = 0.75

OUT_DIR = fm.OUT_DIR
LEDGER = OUT_DIR / "FLOWMARK_map02_prospective_passes.csv.gz"
COVERAGE = OUT_DIR / "FLOWMARK_map02_prospective_coverage.csv"

KEEP = [
    "mark_id",
    "birth_day",
    "direction",
    "pass_no",
    "pass_time",
    "outcome_complete_before_retest_60s",
    "mfe_60_points",
    "mae_60_points",
    "hit_50_before_retest",
    "hit_100_before_retest",
    "hit_200_before_retest",
    "hit_300_before_retest",
    "pass_spread_ratio",
    "pass_tick_rate_ratio_1s",
    "pass_tick_accel_1s_vs_prev4s",
    "pass_signed_mid_impulse_1s_points",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Frozen Map02 prospective shadow collector")
    p.add_argument("--symbol", default=fm.SYMBOL_DEFAULT)
    p.add_argument(
        "--day",
        default=None,
        help="Completed BRT day YYYY-MM-DD. Default = previous BRT calendar day.",
    )
    return p.parse_args()


def previous_brt_day() -> date:
    return datetime.now(fm.BRT).date() - timedelta(days=1)


def append_coverage(row: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    exists = COVERAGE.exists() and COVERAGE.stat().st_size > 0
    df.to_csv(COVERAGE, mode="a", header=not exists, index=False)


def already_collected(day: date) -> bool:
    if COVERAGE.exists() and COVERAGE.stat().st_size > 0:
        c = pd.read_csv(COVERAGE, usecols=["day", "status"])
        c["day"] = pd.to_datetime(c["day"], errors="coerce").dt.date
        if c.loc[c["day"].eq(day), "status"].isin(["COMPLETE", "SATURDAY_NO_TICKS"]).any():
            return True
    if LEDGER.exists() and LEDGER.stat().st_size > 0:
        # Defensive recovery if the coverage manifest were deleted or interrupted.
        for chunk in pd.read_csv(LEDGER, usecols=["birth_day"], chunksize=250_000):
            d = pd.to_datetime(chunk["birth_day"], errors="coerce").dt.date
            if d.eq(day).any():
                return True
    return False


def fetch_day(symbol: str, day: date):
    q_start = fm.brt_local(day, time(0, 0))
    q_end = fm.brt_local(day + timedelta(days=1), time(0, 0)) - timedelta(milliseconds=1)

    last_error = None
    for attempt in range(1, RETRIES + 1):
        mt5.shutdown()
        if not mt5.initialize():
            last_error = mt5.last_error()
            print(f"FETCH attempt={attempt}/{RETRIES} initialize_failed last_error={last_error}", flush=True)
            walltime.sleep(RETRY_SLEEP_S)
            continue

        info = mt5.symbol_info(symbol)
        if info is None:
            last_error = mt5.last_error()
            mt5.shutdown()
            print(f"FETCH attempt={attempt}/{RETRIES} symbol_info=None last_error={last_error}", flush=True)
            walltime.sleep(RETRY_SLEEP_S)
            continue
        if not info.visible and not mt5.symbol_select(symbol, True):
            last_error = mt5.last_error()
            mt5.shutdown()
            print(f"FETCH attempt={attempt}/{RETRIES} symbol_select_failed last_error={last_error}", flush=True)
            walltime.sleep(RETRY_SLEEP_S)
            continue

        point = float(info.point)
        if not math.isclose(point, fm.EXPECTED_POINT, rel_tol=0.0, abs_tol=1e-12):
            mt5.shutdown()
            raise RuntimeError(
                f"MAP02 point guard failed: expected {fm.EXPECTED_POINT}, got {point}"
            )

        raw = mt5.copy_ticks_range(
            symbol, fm.to_utc(q_start), fm.to_utc(q_end), mt5.COPY_TICKS_ALL
        )
        last_error = mt5.last_error()
        ticks = fm.valid_ticks(raw)
        print(
            f"FETCH attempt={attempt}/{RETRIES} ticks={len(ticks):>8} last_error={last_error}",
            flush=True,
        )
        if len(ticks) >= 2:
            return ticks, point

        mt5.shutdown()
        walltime.sleep(RETRY_SLEEP_S)

    mt5.shutdown()
    if day.weekday() == 5:  # Saturday BRT
        return None, fm.EXPECTED_POINT
    raise RuntimeError(
        f"persistent zero-tick day {day} after {RETRIES} fresh MT5 sessions; "
        f"last_error={last_error}"
    )


def append_ledger(df: pd.DataFrame) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exists = LEDGER.exists() and LEDGER.stat().st_size > 0
    # Python gzip readers support concatenated gzip members; append therefore keeps
    # each completed day atomic without rewriting the entire historical ledger.
    df.to_csv(
        LEDGER,
        mode="a" if exists else "w",
        header=not exists,
        index=False,
        compression="gzip",
    )


def main() -> int:
    args = parse_args()
    symbol = str(args.symbol).strip()
    day = pd.Timestamp(args.day).date() if args.day else previous_brt_day()
    today_brt = datetime.now(fm.BRT).date()

    print("=" * 120)
    print("MICROSTRUCTURE QUOTE-MIGRATION MAP02 — PROSPECTIVE SHADOW COLLECTOR")
    print("=" * 120)
    print(f"symbol            = {symbol}")
    print(f"requested_day     = {day} BRT")
    print(f"fresh_start       = {FRESH_START} 00:00 BRT")
    print("scientific logic  = IMPORTED UNCHANGED FROM MAP01R")
    print("Map02 scoring     = DISABLED / SEALED")
    print("runtime promotion = NONE")

    if day < FRESH_START:
        raise SystemExit(f"GUARD FAIL: {day} is before frozen fresh start {FRESH_START}")
    if day >= today_brt:
        raise SystemExit(
            f"GUARD FAIL: {day} is not a completed BRT day; latest allowed is {today_brt - timedelta(days=1)}"
        )
    if already_collected(day):
        print("COLLECTION_STATUS = ALREADY_PRESENT / NO WRITE")
        print("PRIMARY_SCORES = SEALED")
        return 0

    ticks, point = fetch_day(symbol, day)
    if ticks is None:
        append_coverage(
            {
                "day": day,
                "status": "SATURDAY_NO_TICKS",
                "valid_ticks": 0,
                "episodes": 0,
                "passes": 0,
                "complete_passes": 0,
            }
        )
        print("COLLECTION_STATUS = SATURDAY_NO_TICKS")
        print("PRIMARY_SCORES = SEALED")
        return 0

    ms = ticks["time_msc"].astype("int64")
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)

    print(f"BASELINE ticks={len(ticks)}", flush=True)
    baseline = fm.spread_baseline_by_tick(ms, ask - bid)

    print("EPISODES 01R", flush=True)
    marks = fm.episodes_for_day(ms, bid, ask, baseline, point, day)
    print(f"LIFECYCLE episodes={len(marks)} [PEAK zone]", flush=True)
    passes = fm.lifecycle_for_day(marks, ms, bid, ask, baseline, point)
    print(f"PASS LABELS passes={len(passes)}", flush=True)
    fm.label_passes(passes, ms, bid, ask, point)

    pdf = pd.DataFrame(passes)
    if pdf.empty:
        compact = pd.DataFrame(columns=KEEP)
    else:
        missing = [c for c in KEEP if c not in pdf.columns]
        if missing:
            raise RuntimeError(f"MAP02 collector missing frozen PASS columns: {missing}")
        compact = pdf[KEEP].copy()

    if not compact.empty:
        ident = compact[["mark_id", "pass_no"]]
        if ident.duplicated().any():
            raise RuntimeError("GUARD FAIL: duplicate (mark_id, pass_no) within collected day")
        append_ledger(compact)

    complete = int(
        pd.to_numeric(compact.get("outcome_complete_before_retest_60s"), errors="coerce")
        .eq(1)
        .sum()
    ) if not compact.empty else 0

    append_coverage(
        {
            "day": day,
            "status": "COMPLETE",
            "valid_ticks": int(len(ticks)),
            "episodes": int(len(marks)),
            "passes": int(len(compact)),
            "complete_passes": complete,
        }
    )

    mt5.shutdown()
    print()
    print(f"valid_ticks     = {len(ticks)}")
    print(f"episodes        = {len(marks)}")
    print(f"passes          = {len(compact)}")
    print(f"complete_passes = {complete}")
    print(f"ledger          = {LEDGER}")
    print(f"coverage        = {COVERAGE}")
    print("COLLECTION_STATUS = COMPLETE")
    print("PRIMARY_SCORES = SEALED")
    print("NO AUC / CI / DIRECTIONAL SCORE WAS COMPUTED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
