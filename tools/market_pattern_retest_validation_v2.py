#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comparação justa entre entrada no breakout e no reteste.

Usa o detalhe produzido por market_pattern_retest_validation.py e compara:
1) breakout em todos os eventos;
2) breakout apenas nos eventos que confirmaram reteste;
3) entrada no reteste nesses mesmos eventos;
4) coorte sem reteste confirmado.

Assim evitamos comparar universos diferentes.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_DETAIL = "data/market_chronos/{symbol}/patterns/retest_validation/pattern_retest_detail.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/patterns/retest_validation_v2"


def mean_bool(series: pd.Series) -> float:
    return float(series.fillna(False).astype(bool).mean()) if len(series) else np.nan


def mean_num(series: pd.Series) -> float:
    return float(pd.to_numeric(series, errors="coerce").mean()) if len(series) else np.nan


def classify(row: dict, h: int, min_sample: int, min_retest_sample: int) -> str:
    n = int(row["sample_size"])
    rn = int(row["retest_confirmed_count"])
    if n < min_sample or rn < min_retest_sample:
        return "INSUFFICIENT_SAMPLE"
    success_lift = row[f"paired_success_lift_{h}"]
    mae_reduction = row[f"paired_mae_reduction_{h}_atr"]
    return_lift = row[f"paired_return_lift_{h}_atr"]
    breakout_return = row[f"breakout_all_avg_return_{h}_atr"]
    retest_return = row[f"retest_avg_return_{h}_atr"]
    if success_lift >= 0.10 and mae_reduction > 0 and return_lift > 0 and retest_return > 0:
        return "WAIT_FOR_RETEST"
    if success_lift <= -0.10 and return_lift < 0 and breakout_return > 0:
        return "BREAKOUT_ENTRY_PREFERRED"
    if retest_return < 0 and breakout_return < 0:
        return "AVOID_PATTERN"
    return "RETEST_OPTIONAL"


def aggregate(detail: pd.DataFrame, horizons: list[int], min_sample: int, min_retest_sample: int) -> pd.DataFrame:
    rows = []
    keys = ["timeframe", "pattern_type", "breakout_side"]
    for values, group in detail.groupby(keys, dropna=False):
        confirmed = group[group["retest_confirmed"].fillna(False).astype(bool)]
        no_retest = group[~group["retest_confirmed"].fillna(False).astype(bool)]
        row = dict(zip(keys, values))
        row.update({
            "sample_size": len(group),
            "retest_confirmed_count": len(confirmed),
            "no_retest_count": len(no_retest),
            "retest_confirmation_rate": mean_bool(group["retest_confirmed"]),
            "failed_before_retest_rate": mean_bool(group["failed_before_retest"]),
            "avg_bars_to_retest": mean_num(confirmed["bars_to_retest"]),
        })
        for h in horizons:
            # Todos os breakouts
            row[f"breakout_all_success_rate_{h}"] = mean_bool(group[f"breakout_success_{h}"])
            row[f"breakout_all_avg_mfe_{h}_atr"] = mean_num(group[f"breakout_mfe_{h}_atr"])
            row[f"breakout_all_avg_mae_{h}_atr"] = mean_num(group[f"breakout_mae_{h}_atr"])
            row[f"breakout_all_avg_return_{h}_atr"] = mean_num(group[f"breakout_return_{h}_atr"])

            # Comparação pareada: os mesmos eventos com reteste confirmado
            row[f"paired_breakout_success_rate_{h}"] = mean_bool(confirmed[f"breakout_success_{h}"])
            row[f"paired_breakout_avg_mfe_{h}_atr"] = mean_num(confirmed[f"breakout_mfe_{h}_atr"])
            row[f"paired_breakout_avg_mae_{h}_atr"] = mean_num(confirmed[f"breakout_mae_{h}_atr"])
            row[f"paired_breakout_avg_return_{h}_atr"] = mean_num(confirmed[f"breakout_return_{h}_atr"])
            row[f"retest_success_rate_{h}"] = mean_bool(confirmed[f"retest_success_{h}"])
            row[f"retest_avg_mfe_{h}_atr"] = mean_num(confirmed[f"retest_mfe_{h}_atr"])
            row[f"retest_avg_mae_{h}_atr"] = mean_num(confirmed[f"retest_mae_{h}_atr"])
            row[f"retest_avg_return_{h}_atr"] = mean_num(confirmed[f"retest_return_{h}_atr"])
            row[f"paired_success_lift_{h}"] = row[f"retest_success_rate_{h}"] - row[f"paired_breakout_success_rate_{h}"]
            row[f"paired_mae_reduction_{h}_atr"] = row[f"paired_breakout_avg_mae_{h}_atr"] - row[f"retest_avg_mae_{h}_atr"]
            row[f"paired_return_lift_{h}_atr"] = row[f"retest_avg_return_{h}_atr"] - row[f"paired_breakout_avg_return_{h}_atr"]

            # Eventos sem reteste confirmado
            row[f"no_retest_breakout_success_rate_{h}"] = mean_bool(no_retest[f"breakout_success_{h}"])
            row[f"no_retest_breakout_avg_return_{h}_atr"] = mean_num(no_retest[f"breakout_return_{h}_atr"])

        row["recommendation"] = classify(row, max(horizons), min_sample, min_retest_sample)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["recommendation", "timeframe", "sample_size"], ascending=[True, True, False])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fair breakout versus retest cohort comparison")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--detail", default=DEFAULT_DETAIL)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--horizons", nargs="+", type=int, default=[3, 6, 12])
    p.add_argument("--min-sample", type=int, default=5)
    p.add_argument("--min-retest-sample", type=int, default=3)
    return p.parse_args()


def main() -> None:
    a = parse_args()
    root = Path.cwd()
    symbol = a.symbol.upper()
    detail_path = root / a.detail.format(symbol=symbol)
    output = root / a.output.format(symbol=symbol)
    output.mkdir(parents=True, exist_ok=True)

    detail = pd.read_parquet(detail_path)
    horizons = sorted(set(a.horizons))
    summary = aggregate(detail, horizons, a.min_sample, a.min_retest_sample)
    summary.to_csv(output / "pattern_retest_fair_comparison.csv", index=False, encoding="utf-8-sig")
    summary.to_parquet(output / "pattern_retest_fair_comparison.parquet", index=False)

    metadata = {
        "script": "market_pattern_retest_validation_v2.py",
        "version": "2.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "events": len(detail),
        "summary_rows": len(summary),
        "horizons": horizons,
        "min_sample": a.min_sample,
        "min_retest_sample": a.min_retest_sample,
        "output": str(output),
    }
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
