#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validação temporal canônica dos rompimentos de figuras clássicas.

Consome pattern_events.parquet, recalcula MFE/MAE/retorno em horizontes reais
(minutos), separa treino/teste cronologicamente e sinaliza amostras pequenas.
Não detecta novas figuras e não publica leis operacionais.
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

DEFAULT_INPUT = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_EVENTS = "data/market_chronos/{symbol}/patterns/research_v2/pattern_events.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/patterns/research_v2/validation"
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


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
        candidate = next(
            (column for column in ("time", "datetime", "timestamp", "date_time", "date", "open_time") if column in out.columns),
            None,
        )
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
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def build_timeframe(raw: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    prefix = f"{timeframe}_"
    required = [f"{prefix}{name}" for name in ("open", "high", "low", "close")]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise ValueError("OHLC ausente: " + ", ".join(missing))

    time_column = next(
        (
            column
            for column in (
                f"{prefix}event_time",
                f"{prefix}time",
                f"{prefix}datetime",
                f"{prefix}timestamp",
                f"{prefix}open_time",
            )
            if column in raw.columns
        ),
        None,
    )
    event_time = pd.to_datetime(raw[time_column], errors="coerce") if time_column else raw["event_time"]
    out = pd.DataFrame(
        {
            "event_time": event_time,
            "open": numeric(raw, f"{prefix}open"),
            "high": numeric(raw, f"{prefix}high"),
            "low": numeric(raw, f"{prefix}low"),
            "close": numeric(raw, f"{prefix}close"),
        }
    ).dropna(subset=["event_time", "open", "high", "low", "close"])

    if time_column:
        out = out.sort_values("event_time").drop_duplicates("event_time", keep="last")
    else:
        changed = out[["open", "high", "low", "close"]].ne(
            out[["open", "high", "low", "close"]].shift()
        ).any(axis=1)
        out = out.loc[changed]
    return out.sort_values("event_time").reset_index(drop=True)


def add_real_time_outcomes(
    events: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    horizons_minutes: list[int],
) -> pd.DataFrame:
    out = events.copy()
    out["breakout_time"] = pd.to_datetime(out["breakout_time"], errors="coerce")

    for minutes in horizons_minutes:
        mfe_values: list[float] = []
        mae_values: list[float] = []
        return_values: list[float] = []
        success_values: list[Any] = []
        observed_values: list[int] = []

        for row in out.itertuples():
            timeframe = str(row.timeframe)
            frame = frames.get(timeframe)
            atr = float(row.atr)
            breakout_time = pd.Timestamp(row.breakout_time)
            end_time = breakout_time + pd.Timedelta(minutes=minutes)

            if frame is None or not np.isfinite(atr) or atr <= 0:
                mfe_values.append(np.nan)
                mae_values.append(np.nan)
                return_values.append(np.nan)
                success_values.append(pd.NA)
                observed_values.append(0)
                continue

            future = frame.loc[
                (frame["event_time"] > breakout_time)
                & (frame["event_time"] <= end_time)
            ]
            if future.empty:
                mfe_values.append(np.nan)
                mae_values.append(np.nan)
                return_values.append(np.nan)
                success_values.append(pd.NA)
                observed_values.append(0)
                continue

            entry = float(row.breakout_price)
            highest = float(future["high"].max())
            lowest = float(future["low"].min())
            last_close = float(future.iloc[-1]["close"])

            if row.breakout_side == "UP":
                mfe = (highest - entry) / atr
                mae = (entry - lowest) / atr
                result = (last_close - entry) / atr
            else:
                mfe = (entry - lowest) / atr
                mae = (highest - entry) / atr
                result = (entry - last_close) / atr

            mfe_values.append(mfe)
            mae_values.append(mae)
            return_values.append(result)
            success_values.append(bool(mfe >= 0.5 and mfe > mae))
            observed_values.append(len(future))

        out[f"mfe_{minutes}m_atr"] = mfe_values
        out[f"mae_{minutes}m_atr"] = mae_values
        out[f"return_{minutes}m_atr"] = return_values
        out[f"success_{minutes}m"] = pd.Series(success_values, dtype="boolean")
        out[f"observed_bars_{minutes}m"] = observed_values

    return out


def add_temporal_split(events: pd.DataFrame, train_ratio: float) -> pd.DataFrame:
    out = events.copy()
    out["temporal_split"] = "UNASSIGNED"
    out["timeframe_event_order"] = 0

    for timeframe, group in out.groupby("timeframe", sort=False):
        ordered = group.sort_values("breakout_time")
        count = len(ordered)
        train_count = int(math.floor(count * train_ratio))
        if count >= 2:
            train_count = min(max(train_count, 1), count - 1)
        else:
            train_count = count

        for order, index in enumerate(ordered.index, start=1):
            out.at[index, "timeframe_event_order"] = order
            out.at[index, "temporal_split"] = "TRAIN" if order <= train_count else "TEST"

    return out


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return np.nan, np.nan
    proportion = successes / total
    denominator = 1 + (z * z / total)
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) / total) + z * z / (4 * total * total)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def aggregate_long(
    events: pd.DataFrame,
    group_columns: list[str],
    horizons_minutes: list[int],
    min_sample: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    grouped = events.groupby(group_columns, dropna=False) if group_columns else [((), events)]

    for values, group in grouped:
        if not isinstance(values, tuple):
            values = (values,)
        base = dict(zip(group_columns, values))

        for minutes in horizons_minutes:
            success_column = f"success_{minutes}m"
            valid = group.loc[group[success_column].notna()].copy()
            sample_size = len(valid)
            successes = int(valid[success_column].astype(bool).sum()) if sample_size else 0
            success_rate = successes / sample_size if sample_size else np.nan
            ci_low, ci_high = wilson_interval(successes, sample_size)

            row = dict(base)
            row.update(
                {
                    "horizon_minutes": minutes,
                    "sample_size": sample_size,
                    "sample_status": "ADEQUATE" if sample_size >= min_sample else "INSUFFICIENT_SAMPLE",
                    "false_breakout_rate": float(valid["false_breakout"].mean()) if sample_size else np.nan,
                    "retest_rate": float(valid["retest"].mean()) if sample_size else np.nan,
                    "success_rate": success_rate,
                    "success_ci95_low": ci_low,
                    "success_ci95_high": ci_high,
                    "avg_mfe_atr": float(valid[f"mfe_{minutes}m_atr"].mean()) if sample_size else np.nan,
                    "median_mfe_atr": float(valid[f"mfe_{minutes}m_atr"].median()) if sample_size else np.nan,
                    "avg_mae_atr": float(valid[f"mae_{minutes}m_atr"].mean()) if sample_size else np.nan,
                    "median_mae_atr": float(valid[f"mae_{minutes}m_atr"].median()) if sample_size else np.nan,
                    "avg_return_atr": float(valid[f"return_{minutes}m_atr"].mean()) if sample_size else np.nan,
                    "median_return_atr": float(valid[f"return_{minutes}m_atr"].median()) if sample_size else np.nan,
                    "avg_available_space_atr": float(valid["available_space_atr"].mean()) if sample_size and valid["available_space_atr"].notna().any() else np.nan,
                }
            )
            rows.append(row)

    return pd.DataFrame(rows)


def stability_table(train_test: pd.DataFrame, min_sample: int) -> pd.DataFrame:
    if train_test.empty:
        return pd.DataFrame()

    keys = ["timeframe", "higher_tf_context", "horizon_minutes"]
    rows: list[dict[str, Any]] = []
    for values, group in train_test.groupby(keys, dropna=False):
        train = group.loc[group["temporal_split"] == "TRAIN"]
        test = group.loc[group["temporal_split"] == "TEST"]
        train_row = train.iloc[0] if not train.empty else None
        test_row = test.iloc[0] if not test.empty else None

        train_n = int(train_row["sample_size"]) if train_row is not None else 0
        test_n = int(test_row["sample_size"]) if test_row is not None else 0
        train_success = float(train_row["success_rate"]) if train_row is not None else np.nan
        test_success = float(test_row["success_rate"]) if test_row is not None else np.nan
        train_return = float(train_row["avg_return_atr"]) if train_row is not None else np.nan
        test_return = float(test_row["avg_return_atr"]) if test_row is not None else np.nan

        same_success_direction = (
            np.isfinite(train_success)
            and np.isfinite(test_success)
            and ((train_success >= 0.5) == (test_success >= 0.5))
        )
        same_return_direction = (
            np.isfinite(train_return)
            and np.isfinite(test_return)
            and ((train_return >= 0) == (test_return >= 0))
        )
        enough = train_n >= min_sample and test_n >= min_sample

        if enough and same_success_direction and same_return_direction:
            status = "STABLE_CANDIDATE"
        elif train_n == 0 or test_n == 0:
            status = "MISSING_SPLIT"
        elif not enough:
            status = "INSUFFICIENT_SAMPLE"
        else:
            status = "UNSTABLE"

        row = dict(zip(keys, values))
        row.update(
            {
                "train_sample_size": train_n,
                "test_sample_size": test_n,
                "train_success_rate": train_success,
                "test_success_rate": test_success,
                "success_rate_delta_test_minus_train": test_success - train_success if np.isfinite(train_success) and np.isfinite(test_success) else np.nan,
                "train_avg_return_atr": train_return,
                "test_avg_return_atr": test_return,
                "return_delta_test_minus_train": test_return - train_return if np.isfinite(train_return) and np.isfinite(test_return) else np.nan,
                "same_success_direction": same_success_direction,
                "same_return_direction": same_return_direction,
                "stability_status": status,
            }
        )
        rows.append(row)

    return pd.DataFrame(rows).sort_values(
        ["stability_status", "timeframe", "horizon_minutes", "higher_tf_context"]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validação temporal de rompimentos de figuras")
    parser.add_argument("--symbol", default="GOLD")
    parser.add_argument("--anchor-tf", default="M5")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--events", default=DEFAULT_EVENTS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--timeframes", nargs="+", default=["M1", "M5", "M15", "H1"])
    parser.add_argument("--horizons-minutes", nargs="+", type=int, default=[15, 30, 60, 180])
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--min-sample", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0 < args.train_ratio < 1:
        raise ValueError("--train-ratio deve estar entre 0 e 1")
    if args.min_sample < 1:
        raise ValueError("--min-sample deve ser maior que zero")

    root = Path.cwd()
    symbol = args.symbol.upper()
    anchor_tf = args.anchor_tf.upper()
    input_path = root / args.input.format(symbol=symbol, anchor_tf=anchor_tf)
    events_path = root / args.events.format(symbol=symbol, anchor_tf=anchor_tf)
    output_path = root / args.output.format(symbol=symbol, anchor_tf=anchor_tf)
    output_path.mkdir(parents=True, exist_ok=True)

    log(f"Lendo MTF: {input_path}")
    raw = normalize_time(pd.read_parquet(input_path))
    events = pd.read_parquet(events_path)
    if events.empty:
        raise ValueError(f"nenhum evento em {events_path}")

    requested_timeframes = [str(value).upper() for value in args.timeframes]
    frames: dict[str, pd.DataFrame] = {}
    skipped: dict[str, str] = {}
    for timeframe in requested_timeframes:
        try:
            frames[timeframe] = build_timeframe(raw, timeframe)
            log(f"{timeframe}: candles={len(frames[timeframe])}")
        except ValueError as exc:
            skipped[timeframe] = str(exc)
            log(f"{timeframe}: ignorado — {exc}")

    events = events.loc[events["timeframe"].isin(frames)].copy()
    events = add_real_time_outcomes(events, frames, sorted(set(args.horizons_minutes)))
    events = add_temporal_split(events, args.train_ratio)

    by_timeframe = aggregate_long(
        events,
        ["timeframe", "higher_tf_context"],
        sorted(set(args.horizons_minutes)),
        args.min_sample,
    )
    train_test = aggregate_long(
        events,
        ["temporal_split", "timeframe", "higher_tf_context"],
        sorted(set(args.horizons_minutes)),
        args.min_sample,
    )
    stability = stability_table(train_test, args.min_sample)
    overall_timeframe = aggregate_long(
        events,
        ["timeframe"],
        sorted(set(args.horizons_minutes)),
        args.min_sample,
    )

    events.to_parquet(output_path / "pattern_validation_events.parquet", index=False)
    by_timeframe.to_csv(output_path / "pattern_validation_by_timeframe.csv", index=False, encoding="utf-8-sig")
    train_test.to_csv(output_path / "pattern_validation_train_test.csv", index=False, encoding="utf-8-sig")
    stability.to_csv(output_path / "pattern_validation_stability.csv", index=False, encoding="utf-8-sig")
    overall_timeframe.to_csv(output_path / "pattern_validation_timeframe_baseline.csv", index=False, encoding="utf-8-sig")

    split_counts = (
        events.groupby(["timeframe", "temporal_split"]).size().rename("events").reset_index().to_dict("records")
    )
    metadata = {
        "script": "market_pattern_validation.py",
        "version": "1.0-time-normalized-temporal-validation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "anchor_tf": anchor_tf,
        "events_input": str(events_path),
        "events_validated": len(events),
        "horizons_minutes": sorted(set(args.horizons_minutes)),
        "train_ratio": args.train_ratio,
        "min_sample": args.min_sample,
        "split_counts": split_counts,
        "skipped_timeframes": skipped,
        "by_timeframe_rows": len(by_timeframe),
        "train_test_rows": len(train_test),
        "stability_rows": len(stability),
        "stable_candidates": int((stability["stability_status"] == "STABLE_CANDIDATE").sum()) if not stability.empty else 0,
        "output": str(output_path),
    }
    save_json(output_path / "metadata.json", metadata)
    log("OK")
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
