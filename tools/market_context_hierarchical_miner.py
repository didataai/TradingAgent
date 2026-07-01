#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mineração hierárquica de contexto para eventos do Volatility DNA.

Combina eventos de rompimento com features M1 da base consolidada, cria buckets
sem lookahead e procura lift sobre o baseline por lado/horizonte. Primeiro testa
features isoladas; depois testa pares somente entre features promissoras.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_EVENTS = "data/market_chronos/{symbol}/volatility_dna/volatility_dna_events.parquet"
DEFAULT_SOURCE = "data/market_chronos/candle_base/consolidated/{symbol}_candle_research.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/context_hierarchical_miner"

CATEGORICAL_FEATURES = [
    "body_direction",
    "structure_state",
    "session_name",
    "in_asia_session",
    "in_london_session",
    "in_ny_session",
    "london_killzone",
    "ny_killzone",
    "compression_flag",
    "expansion_flag",
    "bos_up",
    "bos_dn",
    "choch_up",
    "choch_dn",
    "sweep_high",
    "sweep_low",
    "fvg_up",
    "fvg_dn",
    "ema20_above_ema50",
    "vol_spike_1p5",
    "vol_spike_2p0",
]

NUMERIC_FEATURES = [
    "vol_ratio",
    "ATR_Z",
    "BB_Width_Z",
    "ADX",
    "RSI",
    "range_atr",
    "body_atr",
    "spread_z",
    "ema20_slope_5",
    "ema50_slope_5",
    "dist_ema20_atr",
    "dist_ema50_atr",
    "dist_donchian_high20_atr",
    "dist_donchian_low20_atr",
    "fvg_up_size_atr",
    "fvg_dn_size_atr",
]


def clean(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return None if not math.isfinite(x) else round(x, 8)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def independent(group: pd.DataFrame, horizon: int) -> pd.DataFrame:
    keep: list[int] = []
    last: pd.Timestamp | None = None
    for idx, row in group.sort_values("event_time").iterrows():
        current = pd.Timestamp(row.event_time)
        if last is None or current >= last + pd.Timedelta(minutes=horizon):
            keep.append(idx)
            last = current
    return group.loc[keep].copy()


def bucket_numeric(series: pd.Series, train_mask: pd.Series) -> pd.Series:
    train = pd.to_numeric(series.loc[train_mask], errors="coerce").dropna()
    if train.nunique() < 4:
        return pd.Series("UNKNOWN", index=series.index)
    q = train.quantile([0.25, 0.50, 0.75]).to_numpy(float)
    if len(np.unique(q)) < 3:
        return pd.Series("UNKNOWN", index=series.index)
    values = pd.to_numeric(series, errors="coerce")
    return pd.cut(
        values,
        bins=[-np.inf, q[0], q[1], q[2], np.inf],
        labels=["Q1_LOW", "Q2", "Q3", "Q4_HIGH"],
        include_lowest=True,
    ).astype("object").fillna("UNKNOWN")


def metrics(group: pd.DataFrame, horizon: int) -> dict[str, float | int]:
    n = len(group)
    return {
        "sample_size": n,
        "success_rate": float(group[f"success_{horizon}m"].mean()) if n else np.nan,
        "avg_return_atr": float(group[f"return_{horizon}m_atr"].mean()) if n else np.nan,
        "median_return_atr": float(group[f"return_{horizon}m_atr"].median()) if n else np.nan,
        "avg_mfe_atr": float(group[f"mfe_{horizon}m_atr"].mean()) if n else np.nan,
        "avg_mae_atr": float(group[f"mae_{horizon}m_atr"].mean()) if n else np.nan,
    }


def evaluate_groups(
    data: pd.DataFrame,
    features: list[str],
    horizon: int,
    train_ratio: float,
    min_train: int,
    min_test: int,
    min_success_lift: float,
    min_return_lift: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for side, side_group in data.groupby("side"):
        independent_side = independent(side_group, horizon).sort_values("event_time").reset_index(drop=True)
        if len(independent_side) < 2:
            continue
        cut = min(max(int(len(independent_side) * train_ratio), 1), len(independent_side) - 1)
        baseline_train = metrics(independent_side.iloc[:cut], horizon)
        baseline_test = metrics(independent_side.iloc[cut:], horizon)

        for values, group in independent_side.groupby(features, dropna=False):
            if not isinstance(values, tuple):
                values = (values,)
            group = group.sort_values("event_time").reset_index(drop=True)
            split = min(max(int(len(group) * train_ratio), 1), len(group) - 1)
            train = metrics(group.iloc[:split], horizon)
            test = metrics(group.iloc[split:], horizon)
            row = {"side": side, "horizon_minutes": horizon, "feature_count": len(features)}
            row.update(dict(zip(features, values)))
            row.update({f"train_{k}": v for k, v in train.items()})
            row.update({f"test_{k}": v for k, v in test.items()})
            row["baseline_train_success_rate"] = baseline_train["success_rate"]
            row["baseline_test_success_rate"] = baseline_test["success_rate"]
            row["baseline_train_avg_return_atr"] = baseline_train["avg_return_atr"]
            row["baseline_test_avg_return_atr"] = baseline_test["avg_return_atr"]
            row["train_success_lift"] = train["success_rate"] - baseline_train["success_rate"]
            row["test_success_lift"] = test["success_rate"] - baseline_test["success_rate"]
            row["train_return_lift"] = train["avg_return_atr"] - baseline_train["avg_return_atr"]
            row["test_return_lift"] = test["avg_return_atr"] - baseline_test["avg_return_atr"]
            enough = train["sample_size"] >= min_train and test["sample_size"] >= min_test
            positive = (
                enough
                and row["train_success_lift"] >= min_success_lift
                and row["test_success_lift"] >= min_success_lift
                and row["train_return_lift"] >= min_return_lift
                and row["test_return_lift"] >= min_return_lift
                and train["avg_return_atr"] > 0
                and test["avg_return_atr"] > 0
            )
            negative = (
                enough
                and row["train_success_lift"] <= -min_success_lift
                and row["test_success_lift"] <= -min_success_lift
                and row["train_return_lift"] <= -min_return_lift
                and row["test_return_lift"] <= -min_return_lift
                and train["avg_return_atr"] < 0
                and test["avg_return_atr"] < 0
            )
            row["candidate_status"] = "ROBUST_POSITIVE" if positive else "ROBUST_NEGATIVE" if negative else "NOT_ROBUST"
            rows.append(row)
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="GOLD")
    parser.add_argument("--events", default=DEFAULT_EVENTS)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--horizons-minutes", nargs="+", type=int, default=[5, 15, 30, 60])
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--min-train-single", type=int, default=120)
    parser.add_argument("--min-test-single", type=int, default=50)
    parser.add_argument("--min-train-pair", type=int, default=80)
    parser.add_argument("--min-test-pair", type=int, default=30)
    parser.add_argument("--min-success-lift", type=float, default=0.03)
    parser.add_argument("--min-return-lift", type=float, default=0.05)
    parser.add_argument("--max-promising-features", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    symbol = args.symbol.upper()
    events_path = root / args.events.format(symbol=symbol)
    source_path = root / args.source.format(symbol=symbol)
    output = root / args.output.format(symbol=symbol)
    output.mkdir(parents=True, exist_ok=True)

    events = pd.read_parquet(events_path)
    events["event_time"] = pd.to_datetime(events.event_time, errors="coerce")
    events = events.dropna(subset=["event_time"]).sort_values("event_time").reset_index(drop=True)

    requested = ["time", "symbol", "timeframe", "is_live_bar", *CATEGORICAL_FEATURES, *NUMERIC_FEATURES]
    candles = pd.read_parquet(source_path, columns=requested)
    candles = candles.loc[
        candles.symbol.astype(str).str.upper().eq(symbol)
        & candles.timeframe.astype(str).str.upper().eq("M1")
    ].copy()
    if "is_live_bar" in candles.columns:
        candles = candles.loc[pd.to_numeric(candles.is_live_bar, errors="coerce").fillna(0).eq(0)]
    candles["event_time"] = pd.to_datetime(candles.time, errors="coerce")
    candles = candles.dropna(subset=["event_time"]).sort_values("event_time").drop_duplicates("event_time", keep="last")

    data = events.merge(candles.drop(columns=["time", "symbol", "timeframe", "is_live_bar"], errors="ignore"), on="event_time", how="left")
    chronological_cut = int(len(data) * args.train_ratio)
    train_mask = pd.Series(np.arange(len(data)) < chronological_cut, index=data.index)

    available_categorical = [f for f in CATEGORICAL_FEATURES if f in data.columns]
    available_numeric = [f for f in NUMERIC_FEATURES if f in data.columns]
    mining_features: list[str] = []
    for feature in available_categorical:
        name = f"ctx_{feature}"
        data[name] = data[feature].astype("object").fillna("UNKNOWN").astype(str)
        mining_features.append(name)
    for feature in available_numeric:
        name = f"ctx_{feature}_bucket"
        data[name] = bucket_numeric(data[feature], train_mask)
        mining_features.append(name)

    single_results: list[pd.DataFrame] = []
    for horizon in sorted(set(args.horizons_minutes)):
        for feature in mining_features:
            result = evaluate_groups(
                data,
                [feature],
                horizon,
                args.train_ratio,
                args.min_train_single,
                args.min_test_single,
                args.min_success_lift,
                args.min_return_lift,
            )
            if not result.empty:
                result["feature_1"] = feature
                single_results.append(result)
    singles = pd.concat(single_results, ignore_index=True) if single_results else pd.DataFrame()

    robust_singles = singles.loc[singles.candidate_status.ne("NOT_ROBUST")].copy() if not singles.empty else pd.DataFrame()
    if robust_singles.empty:
        promising: list[str] = []
    else:
        scores = (
            robust_singles.groupby("feature_1")
            .agg(
                robust_count=("candidate_status", "size"),
                mean_abs_test_success_lift=("test_success_lift", lambda x: float(np.mean(np.abs(x)))),
                mean_abs_test_return_lift=("test_return_lift", lambda x: float(np.mean(np.abs(x)))),
            )
            .reset_index()
        )
        scores["score"] = scores.robust_count + scores.mean_abs_test_success_lift + scores.mean_abs_test_return_lift
        promising = scores.sort_values("score", ascending=False).head(args.max_promising_features).feature_1.tolist()
        scores.to_csv(output / "feature_priority.csv", index=False, encoding="utf-8-sig")

    pair_results: list[pd.DataFrame] = []
    for horizon in sorted(set(args.horizons_minutes)):
        for first, second in itertools.combinations(promising, 2):
            result = evaluate_groups(
                data,
                [first, second],
                horizon,
                args.train_ratio,
                args.min_train_pair,
                args.min_test_pair,
                args.min_success_lift,
                args.min_return_lift,
            )
            if not result.empty:
                result["feature_1"] = first
                result["feature_2"] = second
                pair_results.append(result)
    pairs = pd.concat(pair_results, ignore_index=True) if pair_results else pd.DataFrame()

    singles.to_csv(output / "single_feature_results.csv", index=False, encoding="utf-8-sig")
    robust_singles.to_csv(output / "single_feature_robust.csv", index=False, encoding="utf-8-sig")
    pairs.to_csv(output / "pair_feature_results.csv", index=False, encoding="utf-8-sig")
    robust_pairs = pairs.loc[pairs.candidate_status.ne("NOT_ROBUST")].copy() if not pairs.empty else pd.DataFrame()
    robust_pairs.to_csv(output / "pair_feature_robust.csv", index=False, encoding="utf-8-sig")

    metadata = {
        "script": "market_context_hierarchical_miner.py",
        "version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "events": len(events),
        "merged_events": len(data),
        "features_tested": len(mining_features),
        "promising_features": promising,
        "single_robust": len(robust_singles),
        "pair_robust": len(robust_pairs),
        "horizons_minutes": sorted(set(args.horizons_minutes)),
        "output": str(output),
    }
    save_json(output / "metadata.json", metadata)
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
