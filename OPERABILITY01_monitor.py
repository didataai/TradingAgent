#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
SHADOW_PATH = ROOT / "data" / "market_chronos" / "operability" / "GOLD_operability_shadow.csv"

REQUIRED = {
    "available_at_brt",
    "IN_OPERATIONAL_WINDOW",
    "OPERABILITY",
    "OPERABILITY_REASONS",
}


def _bool_series(s: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(s):
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "sim"})


def _print_counts(title: str, df: pd.DataFrame) -> None:
    print(title)
    counts = df["OPERABILITY"].value_counts(dropna=False)
    for label in ("TRADEABLE", "CAUTION", "NO_TRADE"):
        print(f"  {label:<10} = {int(counts.get(label, 0))}")
    print(f"  TOTAL      = {len(df)}")


def main() -> int:
    print("=" * 132)
    print("OPERABILITY01 — SHADOW DESCRIPTIVE MONITOR (NO OUTCOME SCORE)")
    print("=" * 132)
    print("Exp27 scores      = PROHIBITED / UNTOUCHED")
    print("Outcome metrics   = PROHIBITED")
    print("Runtime promotion = NONE")

    if not SHADOW_PATH.exists():
        print()
        print("OPERABILITY01_MONITOR_STATUS = WAITING_FOR_SHADOW_LOG")
        return 0

    df = pd.read_csv(SHADOW_PATH)
    missing = sorted(REQUIRED - set(df.columns))
    if missing:
        raise RuntimeError(f"Shadow log missing required columns: {missing}")

    df = df.copy()
    df["available_at_brt"] = pd.to_datetime(df["available_at_brt"], errors="coerce")
    if df["available_at_brt"].isna().any():
        raise RuntimeError("Shadow log has invalid available_at_brt values")

    df = df.sort_values("available_at_brt").drop_duplicates("available_at_brt", keep="first").reset_index(drop=True)
    df["IN_OPERATIONAL_WINDOW"] = _bool_series(df["IN_OPERATIONAL_WINDOW"])
    df["brt_date"] = df["available_at_brt"].dt.date

    inw = df.loc[df["IN_OPERATIONAL_WINDOW"]].copy()
    weekday_inw = inw.loc[inw["available_at_brt"].dt.weekday.lt(5)].copy()

    print()
    _print_counts("All persistent fresh-forward rows:", df)
    print()
    _print_counts("Inside configured operational window only:", inw)

    print()
    print("Fresh-forward accumulation (DESCRIPTIVE ONLY):")
    print(f"  first_timestamp            = {df['available_at_brt'].min()}")
    print(f"  last_timestamp             = {df['available_at_brt'].max()}")
    print(f"  unique_BRT_dates_all       = {df['brt_date'].nunique()}")
    print(f"  eligible_weekday_BRT_days  = {weekday_inw['brt_date'].nunique()}")
    print("  EXP27_maturity_days_gate   = 60 (frozen)")
    print("  EXP27_state_count          = NOT_COMPUTED_BY_THIS_MONITOR")
    print("  EXP27_scores               = SEALED")

    reasons = Counter()
    for raw in inw["OPERABILITY_REASONS"].fillna("NONE").astype(str):
        for token in raw.split(";"):
            token = token.strip()
            if token and token != "NONE":
                reasons[token] += 1

    print()
    print("In-window reason counts (descriptive, overlapping):")
    if not reasons:
        print("  NONE")
    else:
        for reason, n in reasons.most_common():
            print(f"  {reason:<36} = {n}")

    latest = df.iloc[-1]
    print()
    print("Latest shadow classification:")
    print(f"  time_brt      = {latest['available_at_brt']}")
    print(f"  operability   = {latest['OPERABILITY']}")
    print(f"  in_window     = {bool(latest['IN_OPERATIONAL_WINDOW'])}")
    print(f"  reasons       = {latest['OPERABILITY_REASONS']}")

    print()
    print("OPERABILITY01_MONITOR_STATUS = PASS")
    print("OPERABILITY01_MODE = SHADOW_ONLY")
    print("EXP27 = UNTOUCHED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
