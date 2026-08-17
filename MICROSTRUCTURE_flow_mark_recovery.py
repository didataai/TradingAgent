#!/usr/bin/env python3
"""Recover the missing Flow-Mark Map01R historical coverage without changing semantics.

This runner reuses the frozen implementation in MICROSTRUCTURE_flow_mark_map.py.
It exists only because the first long MT5 session returned a false zero-tick streak
from 2026-04-21 onward, while isolated probes proved those ticks are available.

Guards:
- reinitialize MT5 before every BRT day;
- retry an empty day up to 3 times;
- abort on persistent zero for every non-Saturday day instead of silently accepting it;
- write recovery files under a separate prefix; never overwrite the preserved partial run;
- scientific mark/lifecycle/outcome definitions are imported unchanged from Map01R.
"""
from __future__ import annotations

import argparse
import math
import time as walltime
from collections import Counter
from datetime import date, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

import MICROSTRUCTURE_flow_mark_map as fm

DEFAULT_START = "2026-04-21"
DEFAULT_END = "2026-08-12"
DEFAULT_TAG = "RECOVERY_20260421_20260812"
RETRIES = 3
RETRY_SLEEP_S = 0.75


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Guarded recovery for frozen Flow-Mark Map01R")
    p.add_argument("--symbol", default=fm.SYMBOL_DEFAULT)
    p.add_argument("--start", default=DEFAULT_START, help="BRT YYYY-MM-DD inclusive")
    p.add_argument("--end", default=DEFAULT_END, help="BRT YYYY-MM-DD inclusive")
    p.add_argument("--tag", default=DEFAULT_TAG, help="output tag; preserved partial files are never touched")
    p.add_argument("--retries", type=int, default=RETRIES)
    return p.parse_args()


def init_symbol(symbol: str) -> float:
    mt5.shutdown()
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"symbol_info({symbol}) returned None")
    if not info.visible and not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")
    point = float(info.point)
    if not math.isclose(point, fm.EXPECTED_POINT, rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError(
            f"FLOWMARK01R point guard failed: expected {fm.EXPECTED_POINT}, got {point}"
        )
    return point


def fetch_day(symbol: str, d: date, retries: int) -> tuple[np.ndarray, tuple]:
    q_start = fm.brt_local(d, time(0, 0))
    q_end = fm.brt_local(d + timedelta(days=1), time(0, 0)) - timedelta(milliseconds=1)
    last_err: tuple = (0, "not-called")

    for attempt in range(1, retries + 1):
        # Critical engineering guard: a fresh MT5 session per day prevents the
        # false long-session zero-tick streak observed in the first full run.
        init_symbol(symbol)
        raw = mt5.copy_ticks_range(
            symbol, fm.to_utc(q_start), fm.to_utc(q_end), mt5.COPY_TICKS_ALL
        )
        last_err = mt5.last_error()
        ticks = fm.valid_ticks(raw)
        print(
            f"    FETCH attempt={attempt}/{retries} ticks={len(ticks):>8} last_error={last_err}",
            flush=True,
        )
        if len(ticks) >= 2:
            return ticks, last_err
        if attempt < retries:
            mt5.shutdown()
            walltime.sleep(RETRY_SLEEP_S)

    return ticks, last_err


def append_csv(df: pd.DataFrame, path: Path, first: bool) -> bool:
    if df.empty:
        return first
    df.to_csv(path, mode="w" if first else "a", header=first, index=False)
    return False


def compact_passes(pdf: pd.DataFrame) -> pd.DataFrame:
    keep = [
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
    return pdf[[c for c in keep if c in pdf.columns]].copy()


def main() -> int:
    args = parse_args()
    symbol = str(args.symbol).strip()
    start_day = pd.Timestamp(args.start).date()
    end_day = pd.Timestamp(args.end).date()
    if end_day < start_day:
        raise SystemExit("--end must be >= --start")
    retries = max(1, int(args.retries))
    tag = str(args.tag).strip().replace(" ", "_")

    print("=" * 132)
    print("MICROSTRUCTURE FLOW-MARK MAP 01R — COVERAGE RECOVERY")
    print("=" * 132)
    print(f"Symbol             = {symbol}")
    print(f"Recovery window    = {start_day} through {end_day} BRT inclusive")
    print("MT5 fetch guard    = REINITIALIZE BEFORE EVERY DAY + RETRY")
    print("Persistent zero    = ABORT on every non-Saturday day")
    print("Scientific logic   = IMPORTED UNCHANGED FROM MICROSTRUCTURE_flow_mark_map.py")
    print("Partial outputs    = NEVER OVERWRITTEN")
    print("Exp27/Calibration  = UNTOUCHED / SCORES SEALED")
    print("Runtime promotion  = NONE")
    print()

    fm.OUT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = fm.OUT_DIR / f"FLOWMARK_map01r_{tag}"
    marks_path = Path(str(prefix) + "_marks.csv")
    passes_path = Path(str(prefix) + "_passes.csv")
    compact_path = Path(str(prefix) + "_passes_compact.csv.gz")
    failures_path = Path(str(prefix) + "_failures.csv")
    manifest_path = Path(str(prefix) + "_coverage.csv")

    for p in (marks_path, passes_path, compact_path, failures_path, manifest_path):
        if p.exists():
            raise RuntimeError(
                f"Refusing to overwrite existing recovery output: {p}. "
                "Use a different --tag if this is intentional."
            )

    first_marks = first_passes = first_compact = first_failures = True
    manifest_rows: list[dict] = []
    coverage = Counter()

    days = pd.date_range(start_day, end_day, freq="D")
    total = len(days)
    point = init_symbol(symbol)
    info = mt5.symbol_info(symbol)
    print(f"MT5 SYMBOL GUARD digits={info.digits if info else '?'} point={point:.8f}")

    try:
        for day_no, dts in enumerate(days, start=1):
            d = dts.date()
            fm.phase(day_no, total, d, "FETCH ticks [fresh MT5 session]")
            ticks, last_err = fetch_day(symbol, d, retries)

            if len(ticks) < 2:
                # Saturday is structurally closed. For every other BRT day we fail
                # closed so that another false missing-history streak cannot pass silently.
                if d.weekday() != 5:
                    raise RuntimeError(
                        f"COVERAGE_GUARD_FAIL day={d} ticks={len(ticks)} "
                        f"after {retries} attempts last_error={last_err}"
                    )
                coverage["NO_TICK_SATURDAY"] += 1
                manifest_rows.append(
                    {
                        "day": d,
                        "status": "NO_TICK_SATURDAY",
                        "ticks": 0,
                        "episodes": 0,
                        "passes": 0,
                        "failures": 0,
                        "last_error": repr(last_err),
                    }
                )
                fm.phase(day_no, total, d, "DONE no ticks [Saturday accepted]")
                continue

            coverage["DAYS_WITH_TICKS"] += 1
            coverage["VALID_TICKS"] += int(len(ticks))
            ms = ticks["time_msc"].astype(np.int64)
            bid = ticks["bid"].astype(float)
            ask = ticks["ask"].astype(float)

            fm.phase(day_no, total, d, f"BASELINE ticks={len(ticks)}")
            baseline = fm.spread_baseline_by_tick(ms, ask - bid)

            fm.phase(day_no, total, d, "EPISODES 01R")
            marks = fm.episodes_for_day(ms, bid, ask, baseline, point, d)

            fm.phase(day_no, total, d, f"LIFECYCLE episodes={len(marks)} [PEAK zone]")
            passes = fm.lifecycle_for_day(marks, ms, bid, ask, baseline, point)

            fm.phase(day_no, total, d, f"PASS LABELS passes={len(passes)}")
            fm.label_passes(passes, ms, bid, ask, point)
            for m in marks:
                fm.add_activation60(m, ms)

            failed_n = sum(int(m.get("failure_idx", -1)) >= 0 for m in marks)
            fm.phase(day_no, total, d, f"FAILURE PATHS failures={failed_n}")
            failures = fm.failure_paths_for_day(marks, ms, bid, ask)

            mdf = pd.DataFrame(marks)
            pdf = pd.DataFrame(passes)
            fdf = pd.DataFrame(failures)
            cpdf = compact_passes(pdf) if not pdf.empty else pd.DataFrame()

            first_marks = append_csv(mdf, marks_path, first_marks)
            first_passes = append_csv(pdf, passes_path, first_passes)
            first_failures = append_csv(fdf, failures_path, first_failures)
            if not cpdf.empty:
                cpdf.to_csv(
                    compact_path,
                    mode="wt" if first_compact else "at",
                    header=first_compact,
                    index=False,
                    compression="gzip",
                )
                first_compact = False

            coverage["EPISODES"] += len(marks)
            coverage["PASSES"] += len(passes)
            coverage["FAILURES"] += len(failures)
            manifest_rows.append(
                {
                    "day": d,
                    "status": "OK",
                    "ticks": len(ticks),
                    "episodes": len(marks),
                    "passes": len(passes),
                    "failures": len(failures),
                    "last_error": repr(last_err),
                }
            )
            pd.DataFrame(manifest_rows).to_csv(manifest_path, index=False)
            fm.phase(
                day_no,
                total,
                d,
                f"DONE episodes={len(marks)} passes={len(passes)} failures={len(failures)}",
            )
    finally:
        mt5.shutdown()

    pd.DataFrame(manifest_rows).to_csv(manifest_path, index=False)

    print()
    print("=" * 132)
    print("RECOVERY COVERAGE SUMMARY")
    print("=" * 132)
    print(f"days_with_ticks     = {coverage['DAYS_WITH_TICKS']}")
    print(f"no_tick_saturdays   = {coverage['NO_TICK_SATURDAY']}")
    print(f"valid_ticks         = {coverage['VALID_TICKS']}")
    print(f"episodes            = {coverage['EPISODES']}")
    print(f"passes              = {coverage['PASSES']}")
    print(f"failures            = {coverage['FAILURES']}")
    print()
    print("OUTPUTS")
    print(f"  marks          = {marks_path}")
    print(f"  passes raw     = {passes_path}")
    print(f"  passes compact = {compact_path}")
    print(f"  failures       = {failures_path}")
    print(f"  coverage       = {manifest_path}")
    print()
    print("FLOW_MARK_MAP01R_RECOVERY = COMPLETE")
    print("SCIENTIFIC_DEFINITIONS = UNCHANGED")
    print("EXP27 = UNTOUCHED / SCORES SEALED")
    print("CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
