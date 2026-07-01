#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validação temporal da microconfirmação M5 -> M1.

Evita que todos os candles M1 sejam associados ao último M5 disponível quando
os períodos não se sobrepõem. Mede cobertura, atraso e overlap real.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from market_pattern_research_v2 import build_frame_from_fallback, build_frame_from_mtf, clean, normalize_time
from market_micro_break_confirmation import prepare_context

DEFAULT_MTF = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_M1 = "data/{symbol}_M1.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/micro_confirmation/diagnostics_v2"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate temporal overlap for M5 to M1 micro confirmation")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.add_argument("--mtf-input", default=DEFAULT_MTF)
    p.add_argument("--m1-input", default=DEFAULT_M1)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--max-context-lag-minutes", type=int, default=5)
    return p.parse_args()


def main() -> None:
    a = parse_args()
    root = Path.cwd(); symbol = a.symbol.upper(); anchor = a.anchor_tf.upper()
    output = root / a.output.format(symbol=symbol, anchor_tf=anchor)
    output.mkdir(parents=True, exist_ok=True)

    raw_mtf = normalize_time(pd.read_parquet(root / a.mtf_input.format(symbol=symbol, anchor_tf=anchor)))
    m5 = build_frame_from_mtf(raw_mtf, "M5").sort_values("event_time").reset_index(drop=True)
    m1 = build_frame_from_fallback(root / a.m1_input.format(symbol=symbol, anchor_tf=anchor)).sort_values("event_time").reset_index(drop=True)
    m5_ctx = prepare_context(m5)

    m1_min, m1_max = m1["event_time"].min(), m1["event_time"].max()
    m5_min, m5_max = m5_ctx["m5_close_time"].min(), m5_ctx["m5_close_time"].max()
    overlap_start, overlap_end = max(m1_min, m5_min), min(m1_max, m5_max)
    has_overlap = bool(overlap_start <= overlap_end)

    aligned = pd.merge_asof(
        m1,
        m5_ctx[["m5_close_time", "m5_color", "m5_side"]],
        left_on="event_time",
        right_on="m5_close_time",
        direction="backward",
        tolerance=pd.Timedelta(minutes=a.max_context_lag_minutes),
        allow_exact_matches=True,
    )
    aligned["context_lag_minutes"] = (
        aligned["event_time"] - aligned["m5_close_time"]
    ).dt.total_seconds() / 60.0
    valid = aligned[aligned["m5_side"].isin(["BUY", "SELL"])].copy()

    coverage = valid["m5_side"].value_counts().rename_axis("side").reset_index(name="rows")
    coverage.to_csv(output / "valid_context_coverage.csv", index=False, encoding="utf-8-sig")
    aligned[["event_time", "m5_close_time", "m5_color", "m5_side", "context_lag_minutes"]].to_parquet(
        output / "temporal_alignment_detail.parquet", index=False
    )

    metadata = {
        "script": "market_micro_break_diagnostics_v2.py",
        "version": "2.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "m1_rows": len(m1),
        "m5_rows": len(m5),
        "m1_min": m1_min,
        "m1_max": m1_max,
        "m5_close_min": m5_min,
        "m5_close_max": m5_max,
        "has_temporal_overlap": has_overlap,
        "overlap_start": overlap_start if has_overlap else None,
        "overlap_end": overlap_end if has_overlap else None,
        "max_context_lag_minutes": a.max_context_lag_minutes,
        "valid_aligned_rows": len(valid),
        "unaligned_rows": int(aligned["m5_side"].isna().sum()),
        "buy_context_rows": int((valid["m5_side"] == "BUY").sum()),
        "sell_context_rows": int((valid["m5_side"] == "SELL").sum()),
        "max_observed_lag_minutes": float(valid["context_lag_minutes"].max()) if len(valid) else None,
        "output": str(output),
    }
    (output / "metadata.json").write_text(json.dumps(clean(metadata), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
