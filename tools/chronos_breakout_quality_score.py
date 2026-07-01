#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chronos Breakout Quality Score.

Consolida evidências de rompimento em cinco famílias explicáveis, evitando dupla
contagem entre features correlacionadas:

1. displacement
2. participation
3. momentum
4. location
5. trend

Cada família recebe -1, 0 ou +1 na direção do evento. O score final varia de
-5 a +5 e é avaliado contra os resultados futuros já calculados no Volatility DNA.
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


def qscore(series: pd.Series, side: pd.Series, up_high: bool = True) -> pd.Series:
    result = pd.Series(0, index=series.index, dtype="int8")
    up = side.astype(str).eq("UP")
    down = side.astype(str).eq("DOWN")
    high = series.astype(str).eq("Q4_HIGH")
    low = series.astype(str).eq("Q1_LOW")
    if up_high:
        result.loc[up & high] = 1
        result.loc[up & low] = -1
        result.loc[down & low] = 1
        result.loc[down & high] = -1
    else:
        result.loc[up & low] = 1
        result.loc[up & high] = -1
        result.loc[down & high] = 1
        result.loc[down & low] = -1
    return result


def family_vote(votes: list[pd.Series]) -> pd.Series:
    if not votes:
        return pd.Series(dtype="int8")
    matrix = pd.concat(votes, axis=1)
    summed = matrix.sum(axis=1)
    out = pd.Series(0, index=matrix.index, dtype="int8")
    out.loc[summed > 0] = 1
    out.loc[summed < 0] = -1
    return out


def bucket_label(score: pd.Series) -> pd.Series:
    return pd.cut(
        score,
        bins=[-np.inf, -3, -1, 1, 3, np.inf],
        labels=["VERY_WEAK", "WEAK", "NEUTRAL", "STRONG", "VERY_STRONG"],
        include_lowest=True,
    ).astype(str)


def metrics(group: pd.DataFrame, horizon: int) -> dict[str, Any]:
    n = len(group)
    if n == 0:
        return {
            "sample_size": 0,
            "success_rate": np.nan,
            "avg_return_atr": np.nan,
            "median_return_atr": np.nan,
            "avg_mfe_atr": np.nan,
            "avg_mae_atr": np.nan,
        }
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

    feature_columns = [
        "time", "symbol", "timeframe", "is_live_bar",
        "body_atr", "range_atr", "vol_ratio", "vol_spike_1p5",
        "RSI", "bos_up", "bos_dn", "choch_up", "choch_dn",
        "dist_ema20_atr", "dist_donchian_high20_atr", "dist_donchian_low20_atr",
        "ema20_slope_5", "ema50_slope_5",
    ]
    candles = pd.read_parquet(root / args.source.format(symbol=symbol), columns=feature_columns)
    candles = candles.loc[
        candles.symbol.astype(str).str.upper().eq(symbol)
        & candles.timeframe.astype(str).str.upper().eq("M1")
    ].copy()
    candles = candles.loc[pd.to_numeric(candles.is_live_bar, errors="coerce").fillna(0).eq(0)]
    candles["event_time"] = pd.to_datetime(candles.time, errors="coerce")
    candles = candles.dropna(subset=["event_time"]).sort_values("event_time").drop_duplicates("event_time", keep="last")

    data = events.merge(
        candles.drop(columns=["time", "symbol", "timeframe", "is_live_bar"], errors="ignore"),
        on="event_time",
        how="left",
    )

    train_mask = pd.Series(np.arange(len(data)) < int(len(data) * 0.60), index=data.index)
    numeric = [
        "body_atr", "range_atr", "vol_ratio", "RSI", "dist_ema20_atr",
        "dist_donchian_high20_atr", "dist_donchian_low20_atr",
        "ema20_slope_5", "ema50_slope_5",
    ]
    for feature in numeric:
        data[f"{feature}_bucket"] = miner.bucket_numeric(data[feature], train_mask)

    displacement_votes = [
        qscore(data["body_atr_bucket"], data.side),
        qscore(data["range_atr_bucket"], data.side),
    ]
    participation_votes = [
        qscore(data["vol_ratio_bucket"], data.side),
    ]
    participation_votes.append(
        pd.Series(
            np.where(pd.to_numeric(data.vol_spike_1p5, errors="coerce").fillna(0).eq(1), 1, 0),
            index=data.index,
            dtype="int8",
        )
    )
    momentum_votes = [qscore(data["RSI_bucket"], data.side)]
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
    momentum_votes.append(structural)

    location_votes = [
        qscore(data["dist_ema20_atr_bucket"], data.side),
        qscore(data["dist_donchian_high20_atr_bucket"], data.side),
        qscore(data["dist_donchian_low20_atr_bucket"], data.side),
    ]
    trend_votes = [
        qscore(data["ema20_slope_5_bucket"], data.side),
        qscore(data["ema50_slope_5_bucket"], data.side),
    ]

    data["score_displacement"] = family_vote(displacement_votes)
    data["score_participation"] = family_vote(participation_votes)
    data["score_momentum"] = family_vote(momentum_votes)
    data["score_location"] = family_vote(location_votes)
    data["score_trend"] = family_vote(trend_votes)
    family_columns = [
        "score_displacement", "score_participation", "score_momentum",
        "score_location", "score_trend",
    ]
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
        for keys, group in independent.groupby(["side", "breakout_quality_score", "breakout_quality_class"], dropna=False):
            side, score, quality_class = keys
            row = {"side": side, "horizon_minutes": horizon, "score": int(score), "quality_class": quality_class}
            row.update(metrics(group, horizon))
            summaries.append(row)

            ordered = group.sort_values("event_time").copy()
            ordered["block"] = pd.qcut(ordered.event_time.rank(method="first"), 5, labels=False, duplicates="drop")
            for block, block_group in ordered.groupby("block"):
                if len(block_group) < args.min_block_size:
                    continue
                block_row = {
                    "side": side,
                    "horizon_minutes": horizon,
                    "score": int(score),
                    "quality_class": quality_class,
                    "block": int(block),
                }
                block_row.update(metrics(block_group, horizon))
                block_rows.append(block_row)

    summary = pd.DataFrame(summaries).sort_values(["horizon_minutes", "side", "score"])
    blocks = pd.DataFrame(block_rows)

    stability_rows: list[dict[str, Any]] = []
    if not blocks.empty:
        for keys, group in blocks.groupby(["side", "horizon_minutes", "score", "quality_class"]):
            side, horizon, score, quality_class = keys
            stability_rows.append({
                "side": side,
                "horizon_minutes": int(horizon),
                "score": int(score),
                "quality_class": quality_class,
                "valid_blocks": len(group),
                "positive_return_blocks": int((group.avg_return_atr > 0).sum()),
                "negative_return_blocks": int((group.avg_return_atr < 0).sum()),
                "avg_block_return_atr": float(group.avg_return_atr.mean()),
                "min_block_return_atr": float(group.avg_return_atr.min()),
                "max_block_return_atr": float(group.avg_return_atr.max()),
                "avg_block_success_rate": float(group.success_rate.mean()),
            })
    stability = pd.DataFrame(stability_rows)

    keep_columns = [
        "event_time", "side", "breakout_quality_score", "breakout_quality_class",
        *family_columns,
        *[c for c in data.columns if c.startswith("success_") or c.startswith("return_") or c.startswith("mfe_") or c.startswith("mae_")],
    ]
    data[keep_columns].to_parquet(output / "breakout_quality_events.parquet", index=False)
    summary.to_csv(output / "breakout_quality_summary.csv", index=False, encoding="utf-8-sig")
    blocks.to_csv(output / "breakout_quality_blocks.csv", index=False, encoding="utf-8-sig")
    stability.to_csv(output / "breakout_quality_stability.csv", index=False, encoding="utf-8-sig")

    metadata = {
        "script": "chronos_breakout_quality_score.py",
        "version": "1.0-five-family-score",
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
        "horizons_minutes": horizons,
        "output": str(output),
    }
    save_json(output / "metadata.json", metadata)
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
