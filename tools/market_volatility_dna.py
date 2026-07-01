#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pesquisa independente do DNA de volatilidade em rompimentos de barras M1.

Evento base:
- barra M1 anterior fechada;
- barra M1 atual rompe máxima ou mínima da barra anterior;
- contexto dos últimos candles FECHADOS de M5, M15 e H1;
- anatomia, volatilidade, volume e resultados futuros normalizados em ATR.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_M1 = "data/{symbol}_M1.parquet"
DEFAULT_MTF = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/volatility_dna"
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}


def log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


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
        number = float(value)
        return None if not math.isfinite(number) else round(number, 8)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_time(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "event_time" not in out.columns:
        candidate = next((c for c in ("time", "datetime", "timestamp", "date_time", "date", "open_time") if c in out.columns), None)
        if candidate:
            out = out.rename(columns={candidate: "event_time"})
        elif isinstance(out.index, pd.DatetimeIndex):
            index_name = out.index.name or "index"
            out = out.reset_index().rename(columns={index_name: "event_time"})
        else:
            raise ValueError("coluna temporal não encontrada")
    out["event_time"] = pd.to_datetime(out["event_time"], errors="coerce")
    return out.dropna(subset=["event_time"]).sort_values("event_time").reset_index(drop=True)


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce") if column in frame.columns else pd.Series(np.nan, index=frame.index)


def build_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    raw = normalize_time(frame)
    aliases = {c.lower(): c for c in raw.columns}
    missing = [x for x in ("open", "high", "low", "close") if x not in aliases]
    if missing:
        raise ValueError("OHLC ausente: " + ", ".join(missing))
    out = pd.DataFrame({
        "event_time": raw["event_time"],
        "open": numeric(raw, aliases["open"]),
        "high": numeric(raw, aliases["high"]),
        "low": numeric(raw, aliases["low"]),
        "close": numeric(raw, aliases["close"]),
        "volume": numeric(raw, aliases.get("tick_volume", aliases.get("volume", "_"))),
    }).dropna(subset=["event_time", "open", "high", "low", "close"])
    out = out.sort_values("event_time").drop_duplicates("event_time", keep="last").reset_index(drop=True)
    true_range = pd.concat([
        out["high"] - out["low"],
        (out["high"] - out["close"].shift()).abs(),
        (out["low"] - out["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    out["atr"] = true_range.rolling(14, min_periods=5).mean()
    out["volume_ratio"] = out["volume"] / out["volume"].rolling(20, min_periods=5).mean()
    return add_bar_anatomy(out)


def build_mtf(raw: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    prefix = f"{timeframe}_"
    required = [f"{prefix}{x}" for x in ("open", "high", "low", "close")]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise ValueError("OHLC ausente: " + ", ".join(missing))
    time_column = next((c for c in (f"{prefix}event_time", f"{prefix}time", f"{prefix}datetime", f"{prefix}timestamp", f"{prefix}open_time") if c in raw.columns), None)
    event_time = pd.to_datetime(raw[time_column], errors="coerce") if time_column else raw["event_time"]
    out = pd.DataFrame({
        "event_time": event_time,
        "open": numeric(raw, f"{prefix}open"),
        "high": numeric(raw, f"{prefix}high"),
        "low": numeric(raw, f"{prefix}low"),
        "close": numeric(raw, f"{prefix}close"),
        "volume": numeric(raw, f"{prefix}tick_volume") if f"{prefix}tick_volume" in raw.columns else numeric(raw, f"{prefix}volume"),
    }).dropna(subset=["event_time", "open", "high", "low", "close"])
    if time_column:
        out = out.sort_values("event_time").drop_duplicates("event_time", keep="last")
    else:
        changed = out[["open", "high", "low", "close"]].ne(out[["open", "high", "low", "close"]].shift()).any(axis=1)
        out = out.loc[changed]
    out = out.reset_index(drop=True)
    true_range = pd.concat([
        out["high"] - out["low"],
        (out["high"] - out["close"].shift()).abs(),
        (out["low"] - out["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    out["atr"] = true_range.rolling(14, min_periods=5).mean()
    out["volume_ratio"] = out["volume"] / out["volume"].rolling(20, min_periods=5).mean()
    return add_bar_anatomy(out)


def add_bar_anatomy(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    bar_range = (out["high"] - out["low"]).replace(0, np.nan)
    body = (out["close"] - out["open"]).abs()
    out["color"] = np.where(out["close"] > out["open"], "GREEN", np.where(out["close"] < out["open"], "RED", "DOJI"))
    out["body_ratio"] = body / bar_range
    out["upper_wick_ratio"] = (out["high"] - out[["open", "close"]].max(axis=1)) / bar_range
    out["lower_wick_ratio"] = (out[["open", "close"]].min(axis=1) - out["low"]) / bar_range
    out["close_location"] = (out["close"] - out["low"]) / bar_range
    out["range_atr"] = bar_range / out["atr"]
    return out


def bucket_body(value: float) -> str:
    if not np.isfinite(value): return "UNKNOWN"
    if value < 0.35: return "SMALL_BODY"
    if value < 0.65: return "MEDIUM_BODY"
    return "STRONG_BODY"


def bucket_range(value: float) -> str:
    if not np.isfinite(value): return "UNKNOWN"
    if value < 0.75: return "LOW_RANGE"
    if value < 1.25: return "NORMAL_RANGE"
    return "EXPANSION_RANGE"


def bucket_volume(value: float) -> str:
    if not np.isfinite(value): return "UNKNOWN"
    if value < 0.8: return "LOW_VOLUME"
    if value < 1.5: return "NORMAL_VOLUME"
    return "HIGH_VOLUME"


def last_closed_bar(frame: pd.DataFrame, timeframe: str, event_time: pd.Timestamp) -> pd.Series | None:
    close_delay = pd.Timedelta(minutes=TF_MINUTES[timeframe])
    eligible = frame.loc[frame["event_time"] + close_delay <= event_time]
    return None if eligible.empty else eligible.iloc[-1]


def detect_events(m1: pd.DataFrame, contexts: dict[str, pd.DataFrame], horizons: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for i in range(1, len(m1) - max(horizons) - 1):
        previous = m1.iloc[i - 1]
        current = m1.iloc[i]
        if not np.isfinite(current["atr"]) or current["atr"] <= 0:
            continue
        up_break = current["high"] > previous["high"]
        down_break = current["low"] < previous["low"]
        sides = []
        if up_break: sides.append("UP")
        if down_break: sides.append("DOWN")
        if not sides: continue

        for side in sides:
            event_time = pd.Timestamp(current["event_time"])
            entry = float(previous["high"] if side == "UP" else previous["low"])
            event = {
                "event_id": f"M1_{i}_{side}",
                "event_time": event_time,
                "side": side,
                "entry_price": entry,
                "m1_previous_color": previous["color"],
                "m1_previous_body_bucket": bucket_body(float(previous["body_ratio"])),
                "m1_previous_range_bucket": bucket_range(float(previous["range_atr"])),
                "m1_previous_volume_bucket": bucket_volume(float(previous["volume_ratio"])),
                "m1_previous_body_ratio": previous["body_ratio"],
                "m1_previous_range_atr": previous["range_atr"],
                "m1_previous_volume_ratio": previous["volume_ratio"],
                "m1_current_color": current["color"],
                "m1_current_body_ratio": current["body_ratio"],
                "m1_current_range_atr": current["range_atr"],
                "m1_current_volume_ratio": current["volume_ratio"],
                "m1_break_distance_atr": abs(float(current["close"]) - entry) / float(current["atr"]),
                "m1_double_break": bool(up_break and down_break),
                "atr": float(current["atr"]),
            }
            aligned_count = 0
            for timeframe, frame in contexts.items():
                bar = last_closed_bar(frame, timeframe, event_time)
                if bar is None:
                    event[f"{timeframe.lower()}_color"] = "UNKNOWN"
                    event[f"{timeframe.lower()}_body_bucket"] = "UNKNOWN"
                    event[f"{timeframe.lower()}_range_bucket"] = "UNKNOWN"
                    event[f"{timeframe.lower()}_volume_bucket"] = "UNKNOWN"
                    continue
                prefix = timeframe.lower()
                event[f"{prefix}_color"] = bar["color"]
                event[f"{prefix}_body_bucket"] = bucket_body(float(bar["body_ratio"]))
                event[f"{prefix}_range_bucket"] = bucket_range(float(bar["range_atr"]))
                event[f"{prefix}_volume_bucket"] = bucket_volume(float(bar["volume_ratio"]))
                event[f"{prefix}_body_ratio"] = bar["body_ratio"]
                event[f"{prefix}_range_atr"] = bar["range_atr"]
                event[f"{prefix}_volume_ratio"] = bar["volume_ratio"]
                if (side == "UP" and bar["color"] == "GREEN") or (side == "DOWN" and bar["color"] == "RED"):
                    aligned_count += 1
            event["htf_aligned_count"] = aligned_count
            event["directional_alignment"] = (
                "FULL_ALIGNMENT" if aligned_count == len(contexts)
                else "PARTIAL_ALIGNMENT" if aligned_count > 0
                else "NO_ALIGNMENT"
            )

            for minutes in horizons:
                future = m1.iloc[i + 1:min(len(m1), i + minutes + 1)]
                if future.empty:
                    event[f"success_{minutes}m"] = pd.NA
                    event[f"mfe_{minutes}m_atr"] = np.nan
                    event[f"mae_{minutes}m_atr"] = np.nan
                    event[f"return_{minutes}m_atr"] = np.nan
                    continue
                if side == "UP":
                    mfe = (future["high"].max() - entry) / current["atr"]
                    mae = (entry - future["low"].min()) / current["atr"]
                    result = (future.iloc[-1]["close"] - entry) / current["atr"]
                else:
                    mfe = (entry - future["low"].min()) / current["atr"]
                    mae = (future["high"].max() - entry) / current["atr"]
                    result = (entry - future.iloc[-1]["close"]) / current["atr"]
                event[f"mfe_{minutes}m_atr"] = float(mfe)
                event[f"mae_{minutes}m_atr"] = float(mae)
                event[f"return_{minutes}m_atr"] = float(result)
                event[f"success_{minutes}m"] = bool(mfe >= 0.5 and mfe > mae)
            rows.append(event)
    return pd.DataFrame(rows)


def add_temporal_split(events: pd.DataFrame, train_ratio: float) -> pd.DataFrame:
    out = events.sort_values("event_time").reset_index(drop=True)
    cut = int(math.floor(len(out) * train_ratio))
    cut = min(max(cut, 1), max(1, len(out) - 1))
    out["temporal_split"] = np.where(out.index < cut, "TRAIN", "TEST")
    return out


def aggregate(events: pd.DataFrame, group_columns: list[str], horizons: list[int], min_sample: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for values, group in events.groupby(group_columns, dropna=False):
        if not isinstance(values, tuple): values = (values,)
        base = dict(zip(group_columns, values))
        for minutes in horizons:
            valid = group.loc[group[f"success_{minutes}m"].notna()]
            n = len(valid)
            row = dict(base)
            row.update({
                "horizon_minutes": minutes,
                "sample_size": n,
                "sample_status": "ADEQUATE" if n >= min_sample else "INSUFFICIENT_SAMPLE",
                "success_rate": float(valid[f"success_{minutes}m"].mean()) if n else np.nan,
                "avg_mfe_atr": float(valid[f"mfe_{minutes}m_atr"].mean()) if n else np.nan,
                "avg_mae_atr": float(valid[f"mae_{minutes}m_atr"].mean()) if n else np.nan,
                "avg_return_atr": float(valid[f"return_{minutes}m_atr"].mean()) if n else np.nan,
                "median_return_atr": float(valid[f"return_{minutes}m_atr"].median()) if n else np.nan,
            })
            rows.append(row)
    return pd.DataFrame(rows).sort_values(["horizon_minutes", "sample_size"], ascending=[True, False])


def discover_candidates(train: pd.DataFrame, test: pd.DataFrame, group_columns: list[str], horizons: list[int], min_train: int, min_test: int) -> pd.DataFrame:
    train_stats = aggregate(train, group_columns, horizons, min_train)
    test_stats = aggregate(test, group_columns, horizons, min_test)
    keys = group_columns + ["horizon_minutes"]
    merged = train_stats.merge(test_stats, on=keys, how="outer", suffixes=("_train", "_test"))
    merged["stable_positive"] = (
        (merged["sample_size_train"] >= min_train)
        & (merged["sample_size_test"] >= min_test)
        & (merged["success_rate_train"] >= 0.55)
        & (merged["success_rate_test"] >= 0.55)
        & (merged["avg_return_atr_train"] > 0)
        & (merged["avg_return_atr_test"] > 0)
    )
    merged["stable_negative"] = (
        (merged["sample_size_train"] >= min_train)
        & (merged["sample_size_test"] >= min_test)
        & (merged["success_rate_train"] < 0.45)
        & (merged["success_rate_test"] < 0.45)
        & (merged["avg_return_atr_train"] < 0)
        & (merged["avg_return_atr_test"] < 0)
    )
    merged["candidate_status"] = np.where(merged["stable_positive"], "STABLE_POSITIVE", np.where(merged["stable_negative"], "STABLE_NEGATIVE", "NOT_STABLE"))
    return merged.sort_values(["candidate_status", "sample_size_test", "sample_size_train"], ascending=[True, False, False])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pesquisa do DNA de volatilidade M1")
    parser.add_argument("--symbol", default="GOLD")
    parser.add_argument("--anchor-tf", default="M5")
    parser.add_argument("--m1", default=DEFAULT_M1)
    parser.add_argument("--mtf", default=DEFAULT_MTF)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--horizons-minutes", nargs="+", type=int, default=[5, 15, 30, 60])
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--min-sample", type=int, default=30)
    parser.add_argument("--min-train", type=int, default=20)
    parser.add_argument("--min-test", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    symbol = args.symbol.upper()
    anchor = args.anchor_tf.upper()
    m1_path = root / args.m1.format(symbol=symbol, anchor_tf=anchor)
    mtf_path = root / args.mtf.format(symbol=symbol, anchor_tf=anchor)
    output = root / args.output.format(symbol=symbol, anchor_tf=anchor)
    output.mkdir(parents=True, exist_ok=True)

    log(f"Lendo M1: {m1_path}")
    m1 = build_ohlc(pd.read_parquet(m1_path))
    raw_mtf = normalize_time(pd.read_parquet(mtf_path))
    contexts = {tf: build_mtf(raw_mtf, tf) for tf in ("M5", "M15", "H1")}
    log(f"Candles M1: {len(m1)}")

    horizons = sorted(set(args.horizons_minutes))
    events = detect_events(m1, contexts, horizons)
    events = add_temporal_split(events, args.train_ratio)
    train = events.loc[events["temporal_split"] == "TRAIN"]
    test = events.loc[events["temporal_split"] == "TEST"]

    summary_alignment = aggregate(events, ["side", "directional_alignment"], horizons, args.min_sample)
    summary_colors = aggregate(events, ["side", "m1_previous_color", "m5_color", "m15_color", "h1_color"], horizons, args.min_sample)
    summary_anatomy = aggregate(events, ["side", "m1_previous_body_bucket", "m1_previous_range_bucket", "m1_previous_volume_bucket", "directional_alignment"], horizons, args.min_sample)
    candidates = discover_candidates(
        train,
        test,
        ["side", "m1_previous_color", "m5_color", "m15_color", "h1_color", "m1_previous_body_bucket", "m1_previous_range_bucket", "directional_alignment"],
        horizons,
        args.min_train,
        args.min_test,
    )

    events.to_parquet(output / "volatility_dna_events.parquet", index=False)
    summary_alignment.to_csv(output / "volatility_dna_alignment_summary.csv", index=False, encoding="utf-8-sig")
    summary_colors.to_csv(output / "volatility_dna_color_summary.csv", index=False, encoding="utf-8-sig")
    summary_anatomy.to_csv(output / "volatility_dna_anatomy_summary.csv", index=False, encoding="utf-8-sig")
    candidates.to_csv(output / "volatility_dna_candidates.csv", index=False, encoding="utf-8-sig")

    metadata = {
        "script": "market_volatility_dna.py",
        "version": "1.0-m1-breakout-dna",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "m1_candles": len(m1),
        "events": len(events),
        "train_events": len(train),
        "test_events": len(test),
        "horizons_minutes": horizons,
        "stable_positive_candidates": int((candidates["candidate_status"] == "STABLE_POSITIVE").sum()) if not candidates.empty else 0,
        "stable_negative_candidates": int((candidates["candidate_status"] == "STABLE_NEGATIVE").sum()) if not candidates.empty else 0,
        "output": str(output),
    }
    save_json(output / "metadata.json", metadata)
    log("OK")
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
