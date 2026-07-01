#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Valida entrada no breakout versus entrada no reteste para padrões V2."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from market_pattern_research_v2 import (
    build_frame_from_fallback,
    build_frame_from_mtf,
    clean,
    normalize_time,
)

DEFAULT_EVENTS = "data/market_chronos/{symbol}/patterns/research_v2/pattern_events.parquet"
DEFAULT_MTF = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_FALLBACK = "data/{symbol}_{tf}.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/patterns/retest_validation"


def measure(frame: pd.DataFrame, start_idx: int, entry: float, side: str, atr: float, horizon: int) -> tuple[float, float, float, bool]:
    end = min(len(frame), start_idx + horizon + 1)
    if start_idx + 1 >= end or not np.isfinite(atr) or atr <= 0:
        return np.nan, np.nan, np.nan, False
    future = frame.iloc[start_idx + 1:end]
    hi = float(future["high"].max())
    lo = float(future["low"].min())
    last = float(future["close"].iloc[-1])
    if side == "UP":
        mfe, mae, ret = (hi-entry)/atr, (entry-lo)/atr, (last-entry)/atr
    else:
        mfe, mae, ret = (entry-lo)/atr, (hi-entry)/atr, (entry-last)/atr
    return mfe, mae, ret, bool(mfe >= 0.50 and mfe > mae)


def analyze_event(row: pd.Series, frame: pd.DataFrame, horizons: list[int], retest_horizon: int, tolerance_atr: float) -> dict:
    i = int(row["bar_index"])
    side = str(row["breakout_side"])
    boundary = float(row["breakout_boundary"])
    atr = float(row["atr"])
    tol = tolerance_atr * atr
    result = row.to_dict()

    retest_idx = None
    failed_before_retest = False
    end = min(len(frame), i + retest_horizon + 1)
    for j in range(i + 1, end):
        candle = frame.iloc[j]
        if side == "UP":
            failed = float(candle["close"]) < boundary - tol
            touched = float(candle["low"]) <= boundary + tol
            confirmed = touched and float(candle["close"]) > boundary
        else:
            failed = float(candle["close"]) > boundary + tol
            touched = float(candle["high"]) >= boundary - tol
            confirmed = touched and float(candle["close"]) < boundary
        if failed:
            failed_before_retest = True
            break
        if confirmed:
            retest_idx = j
            break

    result["retest_confirmed"] = retest_idx is not None
    result["failed_before_retest"] = failed_before_retest
    result["bars_to_retest"] = (retest_idx - i) if retest_idx is not None else np.nan
    result["retest_time"] = frame.iloc[retest_idx]["event_time"] if retest_idx is not None else pd.NaT
    result["retest_entry_price"] = float(frame.iloc[retest_idx]["close"]) if retest_idx is not None else np.nan

    for h in horizons:
        b = measure(frame, i, float(row["breakout_price"]), side, atr, h)
        result[f"breakout_mfe_{h}_atr"], result[f"breakout_mae_{h}_atr"], result[f"breakout_return_{h}_atr"], result[f"breakout_success_{h}"] = b
        if retest_idx is not None:
            r = measure(frame, retest_idx, float(frame.iloc[retest_idx]["close"]), side, atr, h)
        else:
            r = (np.nan, np.nan, np.nan, False)
        result[f"retest_mfe_{h}_atr"], result[f"retest_mae_{h}_atr"], result[f"retest_return_{h}_atr"], result[f"retest_success_{h}"] = r
    return result


def aggregate(detail: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows = []
    for keys, g in detail.groupby(["timeframe", "pattern_type", "breakout_side"], dropna=False):
        confirmed = g[g["retest_confirmed"]]
        row = {
            "timeframe": keys[0], "pattern_type": keys[1], "breakout_side": keys[2],
            "sample_size": len(g), "retest_confirmed_count": len(confirmed),
            "retest_confirmation_rate": float(g["retest_confirmed"].mean()),
            "failed_before_retest_rate": float(g["failed_before_retest"].mean()),
            "avg_bars_to_retest": float(confirmed["bars_to_retest"].mean()) if len(confirmed) else np.nan,
        }
        for h in horizons:
            row[f"breakout_success_rate_{h}"] = float(g[f"breakout_success_{h}"].mean())
            row[f"breakout_avg_mfe_{h}_atr"] = float(g[f"breakout_mfe_{h}_atr"].mean())
            row[f"breakout_avg_mae_{h}_atr"] = float(g[f"breakout_mae_{h}_atr"].mean())
            row[f"breakout_avg_return_{h}_atr"] = float(g[f"breakout_return_{h}_atr"].mean())
            row[f"retest_success_rate_{h}"] = float(confirmed[f"retest_success_{h}"].mean()) if len(confirmed) else np.nan
            row[f"retest_avg_mfe_{h}_atr"] = float(confirmed[f"retest_mfe_{h}_atr"].mean()) if len(confirmed) else np.nan
            row[f"retest_avg_mae_{h}_atr"] = float(confirmed[f"retest_mae_{h}_atr"].mean()) if len(confirmed) else np.nan
            row[f"retest_avg_return_{h}_atr"] = float(confirmed[f"retest_return_{h}_atr"].mean()) if len(confirmed) else np.nan
            row[f"retest_success_lift_{h}"] = row[f"retest_success_rate_{h}"] - row[f"breakout_success_rate_{h}"] if len(confirmed) else np.nan
            row[f"retest_mae_reduction_{h}_atr"] = row[f"breakout_avg_mae_{h}_atr"] - row[f"retest_avg_mae_{h}_atr"] if len(confirmed) else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["timeframe", "sample_size"], ascending=[True, False])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pattern breakout versus retest validation")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.add_argument("--events", default=DEFAULT_EVENTS)
    p.add_argument("--mtf-input", default=DEFAULT_MTF)
    p.add_argument("--fallback-template", default=DEFAULT_FALLBACK)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--horizons", nargs="+", type=int, default=[3, 6, 12])
    p.add_argument("--retest-horizon", type=int, default=8)
    p.add_argument("--retest-tolerance-atr", type=float, default=0.18)
    return p.parse_args()


def main() -> None:
    a = parse_args(); root = Path.cwd(); symbol = a.symbol.upper(); anchor = a.anchor_tf.upper()
    events_path = root / a.events.format(symbol=symbol, anchor_tf=anchor)
    mtf_path = root / a.mtf_input.format(symbol=symbol, anchor_tf=anchor)
    output = root / a.output.format(symbol=symbol, anchor_tf=anchor); output.mkdir(parents=True, exist_ok=True)
    events = pd.read_parquet(events_path)
    raw = normalize_time(pd.read_parquet(mtf_path))

    frames = {}
    for tf in sorted(events["timeframe"].astype(str).unique()):
        try:
            frames[tf] = build_frame_from_mtf(raw, tf)
        except ValueError:
            fallback = root / a.fallback_template.format(symbol=symbol, tf=tf, anchor_tf=anchor)
            frames[tf] = build_frame_from_fallback(fallback)

    rows = []
    for _, row in events.iterrows():
        rows.append(analyze_event(row, frames[str(row["timeframe"])], sorted(set(a.horizons)), a.retest_horizon, a.retest_tolerance_atr))
    detail = pd.DataFrame(rows)
    summary = aggregate(detail, sorted(set(a.horizons)))
    detail.to_parquet(output / "pattern_retest_detail.parquet", index=False)
    summary.to_csv(output / "pattern_retest_summary.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "script": "market_pattern_retest_validation.py", "version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol, "events": len(detail), "summary_rows": len(summary),
        "retest_horizon": a.retest_horizon, "retest_tolerance_atr": a.retest_tolerance_atr,
        "output": str(output),
    }
    (output / "metadata.json").write_text(json.dumps(clean(metadata), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
