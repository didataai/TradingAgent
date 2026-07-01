#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chronos Breakout Quality Score.

Score explicável de -5 a +5, composto por cinco famílias sem dupla contagem:
displacement, participation, momentum, location e trend.

Magnitude é simétrica: body_atr, range_atr e vol_ratio altos favorecem tanto UP
quanto DOWN. Momentum, localização e tendência permanecem direcionais.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import market_context_hierarchical_miner as miner

DEFAULT_OUTPUT = "data/market_chronos/{symbol}/breakout_quality_score"
MAGNITUDE_BUCKETS = {"body_atr_bucket", "range_atr_bucket", "vol_ratio_bucket"}


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return None if not math.isfinite(x) else round(x, 8)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def qscore(series: pd.Series, side: pd.Series) -> pd.Series:
    """Pontua magnitude simetricamente e contexto direcionalmente."""
    result = pd.Series(0, index=series.index, dtype="int8")
    high = series.astype(str).eq("Q4_HIGH")
    low = series.astype(str).eq("Q1_LOW")

    if str(series.name or "") in MAGNITUDE_BUCKETS:
        result.loc[high] = 1
        result.loc[low] = -1
        return result

    up = side.astype(str).eq("UP")
    down = side.astype(str).eq("DOWN")
    result.loc[up & high] = 1
    result.loc[up & low] = -1
    result.loc[down & low] = 1
    result.loc[down & high] = -1
    return result


def family_vote(votes: list[pd.Series]) -> pd.Series:
    matrix = pd.concat(votes, axis=1)
    total = matrix.sum(axis=1)
    result = pd.Series(0, index=matrix.index, dtype="int8")
    result.loc[total > 0] = 1
    result.loc[total < 0] = -1
    return result


def bucket_label(score: pd.Series) -> pd.Series:
    return pd.cut(
        score,
        bins=[-np.inf, -3, -1, 1, 3, np.inf],
        labels=["VERY_WEAK", "WEAK", "NEUTRAL", "STRONG", "VERY_STRONG"],
        include_lowest=True,
    ).astype(str)


def metrics(group: pd.DataFrame, horizon: int) -> dict[str, Any]:
    n = len(group)
    if not n:
        return {"sample_size": 0, "success_rate": np.nan, "avg_return_atr": np.nan,
                "median_return_atr": np.nan, "avg_mfe_atr": np.nan, "avg_mae_atr": np.nan}
    return {
        "sample_size": n,
        "success_rate": float(group[f"success_{horizon}m"].mean()),
        "avg_return_atr": float(group[f"return_{horizon}m_atr"].mean()),
        "median_return_atr": float(group[f"return_{horizon}m_atr"].median()),
        "avg_mfe_atr": float(group[f"mfe_{horizon}m_atr"].mean()),
        "avg_mae_atr": float(group[f"mae_{horizon}m_atr"].mean()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="GOLD")
    parser.add_argument("--events", default=miner.DEFAULT_EVENTS)
    parser.add_argument("--source", default=miner.DEFAULT_SOURCE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--horizons-minutes", nargs="+", type=int, default=[5, 15, 30, 60])
    parser.add_argument("--min-block-size", type=int, default=30)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    symbol = args.symbol.upper()
    output = root / args.output.format(symbol=symbol)
    output.mkdir(parents=True, exist_ok=True)

    events = pd.read_parquet(root / args.events.format(symbol=symbol))
    events["event_time"] = pd.to_datetime(events.event_time, errors="coerce")
    events = events.dropna(subset=["event_time"]).sort_values("event_time").reset_index(drop=True)

    columns = [
        "time", "symbol", "timeframe", "is_live_bar", "body_atr", "range_atr",
        "vol_ratio", "vol_spike_1p5", "RSI", "bos_up", "bos_dn", "choch_up",
        "choch_dn", "dist_ema20_atr", "dist_donchian_high20_atr",
        "dist_donchian_low20_atr", "ema20_slope_5", "ema50_slope_5",
    ]
    candles = pd.read_parquet(root / args.source.format(symbol=symbol), columns=columns)
    candles = candles.loc[
        candles.symbol.astype(str).str.upper().eq(symbol)
        & candles.timeframe.astype(str).str.upper().eq("M1")
    ].copy()
    candles = candles.loc[pd.to_numeric(candles.is_live_bar, errors="coerce").fillna(0).eq(0)]
    candles["event_time"] = pd.to_datetime(candles.time, errors="coerce")
    candles = candles.dropna(subset=["event_time"]).sort_values("event_time").drop_duplicates("event_time", keep="last")

    data = events.merge(
        candles.drop(columns=["time", "symbol", "timeframe", "is_live_bar"], errors="ignore"),
        on="event_time", how="left",
    )

    train_mask = pd.Series(np.arange(len(data)) < int(len(data) * 0.60), index=data.index)
    numeric = [
        "body_atr", "range_atr", "vol_ratio", "RSI", "dist_ema20_atr",
        "dist_donchian_high20_atr", "dist_donchian_low20_atr",
        "ema20_slope_5", "ema50_slope_5",
    ]
    for feature in numeric:
        data[f"{feature}_bucket"] = miner.bucket_numeric(data[feature], train_mask)

    displacement = family_vote([
        qscore(data["body_atr_bucket"], data.side),
        qscore(data["range_atr_bucket"], data.side),
    ])
    participation = family_vote([
        qscore(data["vol_ratio_bucket"], data.side),
        pd.Series(
            np.where(pd.to_numeric(data.vol_spike_1p5, errors="coerce").fillna(0).eq(1), 1, 0),
            index=data.index, dtype="int8",
        ),
    ])

    structural = pd.Series(0, index=data.index, dtype="int8")
    structural.loc[
        data.side.astype(str).eq("UP")
        & (pd.to_numeric(data.bos_up, errors="coerce").fillna(0).eq(1)
           | pd.to_numeric(data.choch_up, errors="coerce").fillna(0).eq(1))
    ] = 1
    structural.loc[
        data.side.astype(str).eq("DOWN")
        & (pd.to_numeric(data.bos_dn, errors="coerce").fillna(0).eq(1)
           | pd.to_numeric(data.choch_dn, errors="coerce").fillna(0).eq(1))
    ] = 1

    data["score_displacement"] = displacement
    data["score_participation"] = participation
    data["score_momentum"] = family_vote([qscore(data["RSI_bucket"], data.side), structural])
    data["score_location"] = family_vote([
        qscore(data["dist_ema20_atr_bucket"], data.side),
        qscore(data["dist_donchian_high20_atr_bucket"], data.side),
        qscore(data["dist_donchian_low20_atr_bucket"], data.side),
    ])
    data["score_trend"] = family_vote([
        qscore(data["ema20_slope_5_bucket"], data.side),
        qscore(data["ema50_slope_5_bucket"], data.side),
    ])

    family_columns = ["score_displacement", "score_participation", "score_momentum",
                      "score_location", "score_trend"]
    data["breakout_quality_score"] = data[family_columns].sum(axis=1).astype("int8")
    data["breakout_quality_class"] = bucket_label(data.breakout_quality_score)

    summaries: list[dict[str, Any]] = []
    block_rows: list[dict[str, Any]] = []
    horizons = sorted(set(args.horizons_minutes))
    for horizon in horizons:
        independent = pd.concat(
            [miner.independent(group, horizon) for _, group in data.groupby("side")],
            ignore_index=True,
        ).sort_values("event_time")
        keys = ["side", "breakout_quality_score", "breakout_quality_class"]
        for (side, score, quality_class), group in independent.groupby(keys, dropna=False):
            row = {"side": side, "horizon_minutes": horizon, "score": int(score),
                   "quality_class": quality_class, **metrics(group, horizon)}
            summaries.append(row)
            ordered = group.sort_values("event_time").copy()
            ordered["block"] = pd.qcut(ordered.event_time.rank(method="first"), 5,
                                         labels=False, duplicates="drop")
            for block, block_group in ordered.groupby("block"):
                if len(block_group) < args.min_block_size:
                    continue
                block_rows.append({"side": side, "horizon_minutes": horizon,
                                   "score": int(score), "quality_class": quality_class,
                                   "block": int(block), **metrics(block_group, horizon)})

    summary = pd.DataFrame(summaries).sort_values(["horizon_minutes", "side", "score"])
    blocks = pd.DataFrame(block_rows)
    stability_rows: list[dict[str, Any]] = []
    if not blocks.empty:
        for (side, horizon, score, quality_class), group in blocks.groupby(
            ["side", "horizon_minutes", "score", "quality_class"]
        ):
            stability_rows.append({
                "side": side, "horizon_minutes": int(horizon), "score": int(score),
                "quality_class": quality_class, "valid_blocks": len(group),
                "positive_return_blocks": int((group.avg_return_atr > 0).sum()),
                "negative_return_blocks": int((group.avg_return_atr < 0).sum()),
                "avg_block_return_atr": float(group.avg_return_atr.mean()),
                "min_block_return_atr": float(group.avg_return_atr.min()),
                "max_block_return_atr": float(group.avg_return_atr.max()),
                "avg_block_success_rate": float(group.success_rate.mean()),
            })
    stability = pd.DataFrame(stability_rows)

    outcomes = [c for c in data.columns if c.startswith(("success_", "return_", "mfe_", "mae_"))]
    keep = ["event_time", "side", "breakout_quality_score", "breakout_quality_class",
            *family_columns, *outcomes]
    data[keep].to_parquet(output / "breakout_quality_events.parquet", index=False)
    summary.to_csv(output / "breakout_quality_summary.csv", index=False, encoding="utf-8-sig")
    blocks.to_csv(output / "breakout_quality_blocks.csv", index=False, encoding="utf-8-sig")
    stability.to_csv(output / "breakout_quality_stability.csv", index=False, encoding="utf-8-sig")

    metadata = {
        "script": "chronos_breakout_quality_score.py",
        "version": "2.0-symmetric-strength",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "events": len(data),
        "score_min": int(data.breakout_quality_score.min()),
        "score_max": int(data.breakout_quality_score.max()),
        "score_distribution": data.breakout_quality_score.value_counts().sort_index().to_dict(),
        "families": {
            "displacement": ["body_atr", "range_atr"],
            "participation": ["vol_ratio", "vol_spike_1p5"],
            "momentum": ["RSI", "BOS/CHOCH aligned"],
            "location": ["dist_ema20_atr", "dist_donchian_high20_atr", "dist_donchian_low20_atr"],
            "trend": ["ema20_slope_5", "ema50_slope_5"],
        },
        "magnitude_features_are_symmetric": True,
        "horizons_minutes": horizons,
        "output": str(output),
    }
    save_json(output / "metadata.json", metadata)
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
