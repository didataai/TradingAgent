#!/usr/bin/env python3
"""Compact a large Flow-Mark passes CSV without recomputing outcomes.

Reads the raw CSV in chunks and keeps only columns needed for the frozen
Map01R continuation, matched PASS1/PASS2 bootstrap, and descriptive feature maps.
Output is gzip-compressed CSV so multi-GB raw files become practical to archive/upload.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = (
    ROOT
    / "data"
    / "market_chronos"
    / "microstructure"
    / "FLOWMARK_map01r_passes_PARTIAL_20260201_20260420.csv"
)
CHUNK_ROWS = 100_000

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
    p = argparse.ArgumentParser(description="Chunked Flow-Mark passes compactor")
    p.add_argument("--input", default=str(DEFAULT_INPUT))
    p.add_argument("--output", default=None)
    p.add_argument("--chunk-rows", type=int, default=CHUNK_ROWS)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"input not found: {src}")

    dst = (
        Path(args.output)
        if args.output
        else src.with_name(src.stem + "_COMPACT.csv.gz")
    )
    if dst.exists():
        raise SystemExit(f"refusing to overwrite existing output: {dst}")

    header = pd.read_csv(src, nrows=0).columns.tolist()
    missing = [c for c in KEEP if c not in header]
    if missing:
        raise SystemExit(f"raw passes file missing expected columns: {missing}")

    print("=" * 110)
    print("MICROSTRUCTURE FLOW-MARK PASSES COMPACTOR")
    print("=" * 110)
    print(f"input       = {src}")
    print(f"output      = {dst}")
    print(f"columns     = {len(KEEP)} / {len(header)}")
    print(f"chunk_rows  = {max(1, int(args.chunk_rows))}")
    print("recompute   = NONE")
    print("outcomes    = COPIED UNCHANGED")
    print()

    first = True
    total = 0
    for chunk_no, df in enumerate(
        pd.read_csv(src, usecols=KEEP, chunksize=max(1, int(args.chunk_rows))), start=1
    ):
        df.to_csv(
            dst,
            mode="wt" if first else "at",
            header=first,
            index=False,
            compression="gzip",
        )
        first = False
        total += len(df)
        print(f"chunk={chunk_no:>4} rows={len(df):>8} total={total:>10}", flush=True)

    raw_mb = src.stat().st_size / (1024 * 1024)
    compact_mb = dst.stat().st_size / (1024 * 1024)
    reduction = 100.0 * (1.0 - compact_mb / raw_mb) if raw_mb else 0.0
    print()
    print(f"raw_MB      = {raw_mb:.2f}")
    print(f"compact_MB  = {compact_mb:.2f}")
    print(f"reduction   = {reduction:.2f}%")
    print("COMPACTION_COMPLETE = YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
