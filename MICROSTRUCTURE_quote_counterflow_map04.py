#!/usr/bin/env python3
"""MICROSTRUCTURE QUOTE COUNTERFLOW MAP04.

Frozen contract:
    docs/MICROSTRUCTURE_QUOTE_COUNTERFLOW_MAP04.md

Modes:
- collect: append one completed fresh BRT day to the Map04 prospective ledger;
- score: report progress only until frozen maturity, then unseal the frozen test once.

No runtime promotion.
"""
from __future__ import annotations

import argparse
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import MICROSTRUCTURE_flow_mark_map as fm
import MICROSTRUCTURE_quote_path_efficiency_map03 as m3

FRESH_START = date(2026, 8, 19)
MATURITY_DAYS = 20
MATURITY_EVENTS = 200_000
BOOT_N = 5000
BOOT_SEED = 2026081804

OUT_DIR = fm.OUT_DIR
LEDGER = OUT_DIR / "FLOWMARK_map04_prospective_passes.csv.gz"
COVERAGE = OUT_DIR / "FLOWMARK_map04_prospective_coverage.csv"
DAILY_MODELS = OUT_DIR / "FLOWMARK_map04_prospective_daily_models.csv"

KEEP = [
    "mark_id",
    "birth_day",
    "direction",
    "pass_no",
    "pass_time",
    "outcome_complete_before_retest_60s",
    "hit_200_before_retest",
    "signed_mid_impulse_1s_points",
    "total_mid_path_1s_points",
    "opposing_mid_path_1s_points",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Frozen Quote Counterflow Map04")
    p.add_argument("--mode", choices=("collect", "score"), required=True)
    p.add_argument("--symbol", default=fm.SYMBOL_DEFAULT)
    p.add_argument(
        "--day",
        default=None,
        help="Completed BRT day YYYY-MM-DD. collect default = previous BRT calendar day.",
    )
    p.add_argument("--retries", type=int, default=m3.RETRIES)
    return p.parse_args()


def previous_brt_day() -> date:
    return datetime.now(fm.BRT).date() - timedelta(days=1)


def append_coverage(row: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exists = COVERAGE.exists() and COVERAGE.stat().st_size > 0
    pd.DataFrame([row]).to_csv(
        COVERAGE, mode="a" if exists else "w", header=not exists, index=False
    )


def collected_days() -> set[date]:
    if not COVERAGE.exists() or COVERAGE.stat().st_size == 0:
        return set()
    c = pd.read_csv(COVERAGE)
    c["day"] = pd.to_datetime(c["day"], errors="coerce").dt.date
    ok = c["status"].isin(["COMPLETE", "SATURDAY_NO_TICKS"])
    return set(c.loc[ok, "day"].dropna())


def append_gzip(df: pd.DataFrame) -> None:
    if df.empty:
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exists = LEDGER.exists() and LEDGER.stat().st_size > 0
    df.to_csv(
        LEDGER,
        mode="a" if exists else "w",
        header=not exists,
        index=False,
        compression="gzip",
    )


def collect_day(symbol: str, day: date, retries: int) -> int:
    today = datetime.now(fm.BRT).date()
    print("=" * 120)
    print("MICROSTRUCTURE QUOTE COUNTERFLOW MAP04 — PROSPECTIVE COLLECTOR")
    print("=" * 120)
    print(f"symbol            = {symbol}")
    print(f"requested_day     = {day} BRT")
    print(f"fresh_start       = {FRESH_START} 00:00 BRT")
    print("scientific logic  = MAP01R events + MAP03 lean reproduction path")
    print("Map04 scoring     = DISABLED / SEALED")
    print("runtime promotion = NONE")

    if day < FRESH_START:
        raise SystemExit(f"GUARD FAIL: {day} is before frozen fresh start {FRESH_START}")
    if day >= today:
        raise SystemExit(
            f"GUARD FAIL: {day} is not a completed BRT day; latest allowed is {today - timedelta(days=1)}"
        )
    if day in collected_days():
        print("COLLECTION_STATUS = ALREADY_PRESENT / NO WRITE")
        print("PRIMARY_SCORES = SEALED")
        return 0

    ticks, point, last_err = m3.fetch_day(symbol, day, max(1, retries))
    if len(ticks) < 2:
        if day.weekday() == 5:
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
        raise RuntimeError(f"persistent zero-tick non-Saturday {day}; last_error={last_err}")

    ms = ticks["time_msc"].astype(np.int64)
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)

    print(f"BASELINE ticks={len(ticks)}", flush=True)
    baseline = fm.spread_baseline_by_tick(ms, ask - bid)
    print("EPISODES 01R", flush=True)
    marks = fm.episodes_for_day(ms, bid, ask, baseline, point, day)
    print(f"LEAN LIFECYCLE episodes={len(marks)}", flush=True)
    passes = m3.lean_lifecycle(marks, ms, bid, ask)
    print(f"PATH + OUTCOME passes={len(passes)}", flush=True)
    pdf = m3.add_path_and_outcome(passes, ms, bid, ask, point)

    if pdf.empty:
        compact = pd.DataFrame(columns=KEEP)
    else:
        x = pd.to_numeric(pdf["signed_mid_impulse_1s_points"], errors="coerce")
        total = pd.to_numeric(pdf["total_mid_path_1s_points"], errors="coerce")
        opposing = (total - x) / 2.0
        # Numerical roundoff only; theoretical opposing path is non-negative.
        opposing = opposing.where(~np.isfinite(opposing), np.maximum(opposing, 0.0))
        pdf = pdf.copy()
        pdf["opposing_mid_path_1s_points"] = opposing
        compact = pdf[KEEP].copy()

    if not compact.empty:
        dup = compact[["mark_id", "pass_no"]].duplicated(keep=False)
        if dup.any():
            raise RuntimeError(
                f"GUARD FAIL: duplicate (mark_id, pass_no) within day = {int(dup.sum())}"
            )
        append_gzip(compact)

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

    print()
    print(f"valid_ticks     = {len(ticks)}")
    print(f"episodes        = {len(marks)}")
    print(f"passes          = {len(compact)}")
    print(f"complete_passes = {complete}")
    print(f"ledger          = {LEDGER}")
    print(f"coverage        = {COVERAGE}")
    print("COLLECTION_STATUS = COMPLETE")
    print("PRIMARY_SCORES = SEALED")
    print("NO BETA / CI / AUC WAS COMPUTED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


def bootstrap_mean(v: np.ndarray) -> tuple[float, float, float]:
    a = np.asarray(v, dtype=float)
    a = a[np.isfinite(a)]
    if not len(a):
        return np.nan, np.nan, np.nan
    est = float(a.mean())
    if len(a) < 2:
        return est, np.nan, np.nan
    rng = np.random.default_rng(BOOT_SEED)
    picks = rng.integers(0, len(a), size=(BOOT_N, len(a)))
    boot = a[picks].mean(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return est, float(lo), float(hi)


def load_eligible() -> pd.DataFrame:
    if not LEDGER.exists() or LEDGER.stat().st_size == 0:
        return pd.DataFrame(columns=KEEP + ["pass_group"])
    z = pd.read_csv(LEDGER, low_memory=False)
    missing = [c for c in KEEP if c not in z.columns]
    if missing:
        raise RuntimeError(f"MAP04 ledger missing frozen columns: {missing}")

    z["birth_day"] = pd.to_datetime(z["birth_day"], errors="coerce").dt.normalize()
    if z["birth_day"].isna().any():
        raise RuntimeError("GUARD FAIL: invalid birth_day")
    if (z["birth_day"].dt.date < FRESH_START).any():
        raise RuntimeError("GUARD FAIL: pre-fresh row in Map04 prospective ledger")
    dup = z[["mark_id", "pass_no"]].duplicated(keep=False)
    if dup.any():
        raise RuntimeError(f"GUARD FAIL: duplicate (mark_id, pass_no) rows = {int(dup.sum())}")

    for c in (
        "pass_no",
        "outcome_complete_before_retest_60s",
        "hit_200_before_retest",
        "signed_mid_impulse_1s_points",
        "opposing_mid_path_1s_points",
    ):
        z[c] = pd.to_numeric(z[c], errors="coerce")

    z = z.loc[
        z["outcome_complete_before_retest_60s"].eq(1)
        & z["hit_200_before_retest"].isin([0, 1])
        & np.isfinite(z["signed_mid_impulse_1s_points"])
        & np.isfinite(z["opposing_mid_path_1s_points"])
    ].copy()
    z["pass_group"] = np.where(
        z["pass_no"].eq(1), "PASS1", np.where(z["pass_no"].eq(2), "PASS2", "PASS3+")
    )
    return z


def daily_models(z: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (day, group), g in z.groupby(["birth_day", "pass_group"], sort=True):
        y = g["hit_200_before_retest"].to_numpy(float)
        beta, converged = m3.fit_rank_logit(
            g["signed_mid_impulse_1s_points"].to_numpy(float),
            g["opposing_mid_path_1s_points"].to_numpy(float),
            y,
        )
        if not converged:
            continue
        rows.append(
            {
                "birth_day": day,
                "pass_group": group,
                "n": int(len(g)),
                "n_pos": int(np.sum(y == 1.0)),
                "n_neg": int(np.sum(y == 0.0)),
                "beta_x": float(beta[1]),
                "beta_counterflow": float(beta[2]),
            }
        )
    return pd.DataFrame(rows)


def score() -> int:
    print("=" * 120)
    print("MICROSTRUCTURE QUOTE COUNTERFLOW MAP04 — PROSPECTIVE SCORER")
    print("=" * 120)
    print(f"fresh_start       = {FRESH_START} 00:00 BRT")
    print(f"maturity          = {MATURITY_DAYS} eligible days + {MATURITY_EVENTS} complete PASS events")
    print("primary model     = daily rank-logit MID impulse + opposing path")
    print("primary effect    = beta_counterflow")
    print("runtime promotion = NONE")

    z = load_eligible()
    days = int(z["birth_day"].nunique()) if not z.empty else 0
    events = int(len(z))
    print()
    print("PROSPECTIVE PROGRESS")
    print(f"days_progress   = {days}/{MATURITY_DAYS}")
    print(f"event_progress  = {events}/{MATURITY_EVENTS}")

    if days < MATURITY_DAYS or events < MATURITY_EVENTS:
        print("MAP04_PROSPECTIVE_STATUS = ACCUMULATING")
        print("PRIMARY_SCORES = SEALED")
        print("NO BETA / CI / SIGN / AUC WAS COMPUTED")
        return 0

    dm = daily_models(z)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dm.to_csv(DAILY_MODELS, index=False)

    print()
    print("=" * 120)
    print("MAP04 PRIMARY — INCREMENTAL OPPOSING QUOTE PATH AFTER MID-IMPULSE CONTROL")
    print("=" * 120)
    full = True
    for group in ("PASS1", "PASS2", "PASS3+"):
        g = dm.loc[dm["pass_group"].eq(group)]
        est, lo, hi = bootstrap_mean(g["beta_counterflow"].to_numpy(float))
        q = z.loc[z["pass_group"].eq(group)]
        passed = bool(np.isfinite(lo) and est > 0.0 and lo > 0.0)
        full = full and passed
        print(
            f"{group:<6} days={len(g):>3} events={len(q):>9} "
            f"mean_beta_COUNTERFLOW={est:+.6f} CI95=[{lo:+.6f},{hi:+.6f}] "
            f"support={'YES' if passed else 'NO'}"
        )

    print()
    print("MAP04_PROSPECTIVE_STATUS = MATURE")
    print("MAP04_PRIMARY_FULL_PASS = " + ("YES" if full else "NO"))
    print("NO SIGN INVERSION / THRESHOLD / PASS-STAGE RESCUE AUTHORIZED")
    print("MAP03_PRIMARY = FAILED / NOT_SIGN_INVERTED")
    print("MAP02_PROSPECTIVE = UNTOUCHED / SCORES SEALED UNTIL ITS OWN MATURITY")
    print("EXP27 = UNTOUCHED / SCORES SEALED")
    print("CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED")
    print("RUNTIME_PROMOTION = NONE")
    print(f"daily_models = {DAILY_MODELS}")
    return 0


def main() -> int:
    args = parse_args()
    if args.mode == "collect":
        day = pd.Timestamp(args.day).date() if args.day else previous_brt_day()
        return collect_day(str(args.symbol).strip(), day, max(1, int(args.retries)))
    return score()


if __name__ == "__main__":
    raise SystemExit(main())
