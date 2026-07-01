#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Market Pattern Research MVP.

Detecta, sem alterar o parquet original:
- TRIANGLE_SYMMETRIC
- TRIANGLE_ASCENDING
- TRIANGLE_DESCENDING
- RANGE_BOX

Também mede breakout, falso rompimento, reteste, MFE, MAE e retorno por
horizonte. As saídas ficam isoladas em ``patterns/research`` e não publicam leis.
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
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/patterns/research"
DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "H1"]


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{stamp()}] {message}", flush=True)


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if not math.isfinite(number) else round(number, 8)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean_json(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_event_time(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "event_time" not in out.columns:
        candidates = ("time", "datetime", "timestamp", "date_time", "date", "open_time", "candle_time")
        source = next((name for name in candidates if name in out.columns), None)
        if source:
            out = out.rename(columns={source: "event_time"})
        elif isinstance(out.index, pd.DatetimeIndex):
            index_name = out.index.name or "index"
            out = out.reset_index().rename(columns={index_name: "event_time"})
        else:
            raise ValueError("Coluna temporal não encontrada na base.")
    out["event_time"] = pd.to_datetime(out["event_time"], errors="coerce")
    return out.dropna(subset=["event_time"]).sort_values("event_time").drop_duplicates("event_time", keep="last").reset_index(drop=True)


def num(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[name], errors="coerce")


def first_num(df: pd.DataFrame, names: list[str]) -> pd.Series:
    for name in names:
        if name in df.columns:
            return num(df, name)
    return pd.Series(np.nan, index=df.index, dtype=float)


def tf_frame(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    p = f"{tf}_"
    required = [f"{p}open", f"{p}high", f"{p}low", f"{p}close"]
    missing = [name for name in required if name not in df.columns]
    if missing:
        raise ValueError(f"OHLC ausente: {', '.join(missing)}")

    out = pd.DataFrame({
        "event_time": df["event_time"],
        "open": num(df, f"{p}open"),
        "high": num(df, f"{p}high"),
        "low": num(df, f"{p}low"),
        "close": num(df, f"{p}close"),
        "atr": first_num(df, [f"{p}ATR", f"{p}atr"]),
        "vol_ratio": first_num(df, [f"{p}vol_ratio", f"{p}volume_ratio"]),
        "breakout_up_existing": df.get(f"{p}breakout_up", False),
        "breakout_down_existing": df.get(f"{p}breakout_down", False),
        "false_breakout_up_existing": df.get(f"{p}false_breakout_up", False),
        "false_breakout_down_existing": df.get(f"{p}false_breakout_down", False),
        "sweep_high_existing": df.get(f"{p}sweep_high", False),
        "sweep_low_existing": df.get(f"{p}sweep_low", False),
        "compression_existing": df.get(f"{p}compression_flag", False),
        "expansion_existing": df.get(f"{p}expansion_flag", False),
    })

    if out["atr"].isna().all():
        tr = pd.concat([
            out["high"] - out["low"],
            (out["high"] - out["close"].shift()).abs(),
            (out["low"] - out["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        out["atr"] = tr.rolling(14, min_periods=5).mean()

    bool_cols = [c for c in out.columns if c.endswith("_existing")]
    for col in bool_cols:
        out[col] = out[col].fillna(False).astype(bool)
    return out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def fit_line(values: np.ndarray) -> tuple[float, float, float]:
    x = np.arange(len(values), dtype=float)
    valid = np.isfinite(values)
    if valid.sum() < max(5, len(values) // 2):
        return np.nan, np.nan, np.nan
    slope, intercept = np.polyfit(x[valid], values[valid], 1)
    fitted = slope * x[valid] + intercept
    ss_res = float(np.sum((values[valid] - fitted) ** 2))
    ss_tot = float(np.sum((values[valid] - np.mean(values[valid])) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return float(slope), float(intercept), float(r2)


def classify(us: float, ls: float, compression: float, width_end_atr: float, ur2: float, lr2: float,
             slope_flat: float, slope_dir: float, min_compression: float, max_range_width_atr: float) -> str | None:
    if not all(np.isfinite(v) for v in (us, ls, compression, width_end_atr, ur2, lr2)):
        return None
    if ur2 < 0.15 or lr2 < 0.15:
        return None
    upper_down = us <= -slope_dir
    lower_up = ls >= slope_dir
    upper_flat = abs(us) <= slope_flat
    lower_flat = abs(ls) <= slope_flat
    if compression >= min_compression:
        if upper_down and lower_up:
            return "TRIANGLE_SYMMETRIC"
        if upper_flat and lower_up:
            return "TRIANGLE_ASCENDING"
        if upper_down and lower_flat:
            return "TRIANGLE_DESCENDING"
    if upper_flat and lower_flat and width_end_atr <= max_range_width_atr and compression >= -0.20:
        return "RANGE_BOX"
    return None


def add_outcomes(events: pd.DataFrame, frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    if events.empty:
        return events
    out = events.copy()
    highs, lows, closes = (frame[c].to_numpy(float) for c in ("high", "low", "close"))
    for h in horizons:
        mfe, mae, ret, success = [], [], [], []
        for row in out.itertuples():
            idx = int(row.bar_index)
            end = min(len(frame), idx + h + 1)
            atr = float(row.atr)
            if idx + 1 >= end or not np.isfinite(atr) or atr <= 0:
                mfe.append(np.nan); mae.append(np.nan); ret.append(np.nan); success.append(False); continue
            future_high = float(np.nanmax(highs[idx + 1:end]))
            future_low = float(np.nanmin(lows[idx + 1:end]))
            future_close = float(closes[end - 1])
            entry = float(row.breakout_price)
            if row.breakout_side == "UP":
                m = (future_high - entry) / atr; a = (entry - future_low) / atr; r = (future_close - entry) / atr
            else:
                m = (entry - future_low) / atr; a = (future_high - entry) / atr; r = (entry - future_close) / atr
            mfe.append(m); mae.append(a); ret.append(r); success.append(bool(m >= 0.50 and m > a))
        out[f"mfe_{h}_atr"] = mfe
        out[f"mae_{h}_atr"] = mae
        out[f"close_return_{h}_atr"] = ret
        out[f"success_{h}"] = success
    return out


def detect(frame: pd.DataFrame, symbol: str, tf: str, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    events: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    high, low, close = (frame[c].to_numpy(float) for c in ("high", "low", "close"))
    atr = frame["atr"].to_numpy(float)
    vol = frame["vol_ratio"].to_numpy(float)
    last_break = -999999

    for window in sorted(set(args.windows)):
        if len(frame) <= window + max(args.horizons) + 2:
            continue
        x = np.arange(window, dtype=float)
        for idx in range(window - 1, len(frame) - max(args.horizons) - 1):
            start = idx - window + 1
            highs, lows = high[start:idx + 1], low[start:idx + 1]
            atr_ref = float(np.nanmedian(atr[start:idx + 1]))
            if not np.isfinite(atr_ref) or atr_ref <= 0:
                continue
            us, ui, ur2 = fit_line(highs)
            ls, li, lr2 = fit_line(lows)
            if not all(np.isfinite(v) for v in (us, ui, ls, li)):
                continue
            upper_start, upper_end = ui, us * (window - 1) + ui
            lower_start, lower_end = li, ls * (window - 1) + li
            width_start, width_end = upper_start - lower_start, upper_end - lower_end
            if width_start <= 0 or width_end <= 0:
                continue
            compression = 1.0 - width_end / width_start
            pattern = classify(us / atr_ref, ls / atr_ref, compression, width_end / atr_ref, ur2, lr2,
                               args.slope_flat, args.slope_directional, args.min_compression, args.max_range_width_atr)
            if not pattern:
                continue
            upper_line, lower_line = us * x + ui, ls * x + li
            upper_touches = int(np.sum(np.abs(highs - upper_line) <= args.touch_tolerance_atr * atr_ref))
            lower_touches = int(np.sum(np.abs(lows - lower_line) <= args.touch_tolerance_atr * atr_ref))
            if upper_touches < args.min_touches or lower_touches < args.min_touches:
                continue

            next_idx = idx + 1
            upper_next, lower_next = us * window + ui, ls * window + li
            next_atr = atr[next_idx] if np.isfinite(atr[next_idx]) and atr[next_idx] > 0 else atr_ref
            buffer = args.breakout_buffer_atr * next_atr
            side = "UP" if close[next_idx] > upper_next + buffer else "DOWN" if close[next_idx] < lower_next - buffer else None
            quality = float(np.clip(25 * max(0, compression) + 20 * ur2 + 20 * lr2 + 10 * min(1, upper_touches / 4) + 10 * min(1, lower_touches / 4), 0, 100))

            if side is None:
                states.append({
                    "symbol": symbol, "timeframe": tf, "bar_index": idx,
                    "event_time": frame.at[idx, "event_time"], "pattern_type": pattern,
                    "state": "ACTIVE", "window_bars": window,
                    "upper_boundary": upper_end, "lower_boundary": lower_end,
                    "width_end_atr": width_end / atr_ref, "compression_ratio": compression,
                    "upper_touches": upper_touches, "lower_touches": lower_touches,
                    "upper_slope_atr": us / atr_ref, "lower_slope_atr": ls / atr_ref,
                    "quality_score": quality,
                })
                continue

            if next_idx <= last_break + max(2, window // 5):
                continue
            last_break = next_idx
            boundary = upper_next if side == "UP" else lower_next
            false_end = min(len(frame), next_idx + args.false_break_horizon + 1)
            future_closes = close[next_idx + 1:false_end]
            false_break = bool(np.any(future_closes < upper_next)) if side == "UP" and len(future_closes) else bool(np.any(future_closes > lower_next)) if len(future_closes) else False
            retest_end = min(len(frame), next_idx + args.retest_horizon + 1)
            tolerance = args.touch_tolerance_atr * next_atr
            retest = bool(np.any(np.abs(low[next_idx + 1:retest_end] - upper_next) <= tolerance)) if side == "UP" else bool(np.any(np.abs(high[next_idx + 1:retest_end] - lower_next) <= tolerance))
            dist_atr = abs(close[next_idx] - boundary) / next_atr
            volume = vol[next_idx]
            quality = float(np.clip(quality + 10 * min(1, dist_atr) + 5 * min(1, (volume if np.isfinite(volume) else 0) / 2), 0, 100))

            events.append({
                "pattern_id": f"{symbol}_{tf}_{pattern}_{next_idx}", "symbol": symbol, "timeframe": tf,
                "bar_index": next_idx, "formation_start_time": frame.at[start, "event_time"],
                "formation_end_time": frame.at[idx, "event_time"], "breakout_time": frame.at[next_idx, "event_time"],
                "pattern_type": pattern, "window_bars": window, "breakout_side": side,
                "breakout_price": close[next_idx], "breakout_boundary": boundary,
                "breakout_distance_atr": dist_atr, "breakout_volume_ratio": volume, "atr": next_atr,
                "width_start_atr": width_start / atr_ref, "width_end_atr": width_end / atr_ref,
                "compression_ratio": compression, "upper_slope_atr": us / atr_ref,
                "lower_slope_atr": ls / atr_ref, "upper_r2": ur2, "lower_r2": lr2,
                "upper_touches": upper_touches, "lower_touches": lower_touches,
                "false_breakout": false_break, "retest": retest, "quality_score": quality,
                "existing_breakout_flag": bool(frame.at[next_idx, "breakout_up_existing"] if side == "UP" else frame.at[next_idx, "breakout_down_existing"]),
                "existing_false_breakout_flag": bool(frame.at[next_idx, "false_breakout_up_existing"] if side == "UP" else frame.at[next_idx, "false_breakout_down_existing"]),
                "existing_sweep_flag": bool(frame.at[next_idx, "sweep_high_existing"] if side == "UP" else frame.at[next_idx, "sweep_low_existing"]),
                "existing_compression_flag": bool(frame.at[idx, "compression_existing"]),
                "existing_expansion_flag": bool(frame.at[next_idx, "expansion_existing"]),
            })

    event_df = pd.DataFrame(events)
    if not event_df.empty:
        event_df = event_df.sort_values(["breakout_time", "quality_score"], ascending=[True, False]).drop_duplicates(["timeframe", "breakout_time", "breakout_side"], keep="first").reset_index(drop=True)
        event_df = add_outcomes(event_df, frame, sorted(set(args.horizons)))
    state_df = pd.DataFrame(states)
    if not state_df.empty:
        state_df = state_df.sort_values(["event_time", "quality_score"], ascending=[True, False]).drop_duplicates(["timeframe", "event_time", "pattern_type"], keep="first").reset_index(drop=True)
    return event_df, state_df


def aggregate(events: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    rows = []
    keys = ["timeframe", "pattern_type", "breakout_side"]
    for values, group in events.groupby(keys, dropna=False):
        row = dict(zip(keys, values))
        row.update({
            "sample_size": len(group),
            "false_breakout_rate": float(group["false_breakout"].mean()),
            "retest_rate": float(group["retest"].mean()),
            "avg_quality_score": float(group["quality_score"].mean()),
            "avg_compression_ratio": float(group["compression_ratio"].mean()),
            "avg_breakout_distance_atr": float(group["breakout_distance_atr"].mean()),
            "avg_breakout_volume_ratio": float(group["breakout_volume_ratio"].mean()),
            "existing_breakout_agreement_rate": float(group["existing_breakout_flag"].mean()),
        })
        for h in horizons:
            row[f"success_rate_{h}"] = float(group[f"success_{h}"].mean())
            row[f"avg_mfe_{h}_atr"] = float(group[f"mfe_{h}_atr"].mean())
            row[f"avg_mae_{h}_atr"] = float(group[f"mae_{h}_atr"].mean())
            row[f"avg_close_return_{h}_atr"] = float(group[f"close_return_{h}_atr"].mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["timeframe", "sample_size", "pattern_type"], ascending=[True, False, True])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Market Pattern Research MVP")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.add_argument("--input", default=DEFAULT_INPUT)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--timeframes", nargs="+", default=DEFAULT_TIMEFRAMES)
    p.add_argument("--windows", nargs="+", type=int, default=[12, 20, 30])
    p.add_argument("--horizons", nargs="+", type=int, default=[3, 6, 12])
    p.add_argument("--min-touches", type=int, default=2)
    p.add_argument("--touch-tolerance-atr", type=float, default=0.18)
    p.add_argument("--breakout-buffer-atr", type=float, default=0.08)
    p.add_argument("--false-break-horizon", type=int, default=3)
    p.add_argument("--retest-horizon", type=int, default=6)
    p.add_argument("--slope-flat", type=float, default=0.025)
    p.add_argument("--slope-directional", type=float, default=0.025)
    p.add_argument("--min-compression", type=float, default=0.25)
    p.add_argument("--max-range-width-atr", type=float, default=2.50)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    symbol, anchor_tf = args.symbol.upper(), args.anchor_tf.upper()
    input_path = root / args.input.format(symbol=symbol, anchor_tf=anchor_tf)
    output_root = root / args.output.format(symbol=symbol, anchor_tf=anchor_tf)
    output_root.mkdir(parents=True, exist_ok=True)

    log(f"Lendo: {input_path}")
    raw = normalize_event_time(pd.read_parquet(input_path))
    log(f"Linhas: {len(raw)}")
    all_events, all_states, skipped = [], [], {}

    for tf in [str(v).upper() for v in args.timeframes]:
        try:
            frame = tf_frame(raw, tf)
        except ValueError as exc:
            skipped[tf] = str(exc)
            log(f"{tf}: ignorado — {exc}")
            continue
        log(f"{tf}: detectando em {len(frame)} linhas")
        events, states = detect(frame, symbol, tf, args)
        log(f"{tf}: eventos={len(events)} | ativos={len(states)}")
        if not events.empty:
            all_events.append(events)
        if not states.empty:
            all_states.append(states)

    events = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
    states = pd.concat(all_states, ignore_index=True) if all_states else pd.DataFrame()
    stats = aggregate(events, sorted(set(args.horizons)))

    events_path = output_root / "pattern_events.parquet"
    states_path = output_root / "pattern_active_states.parquet"
    stats_path = output_root / "pattern_statistics.csv"
    current_path = output_root / "pattern_current_state.json"
    events.to_parquet(events_path, index=False)
    states.to_parquet(states_path, index=False)
    stats.to_csv(stats_path, index=False, encoding="utf-8-sig")

    current = []
    if not states.empty:
        for tf, group in states.groupby("timeframe"):
            latest = group[group["event_time"].eq(group["event_time"].max())].sort_values("quality_score", ascending=False).head(3)
            current.extend(latest.to_dict(orient="records"))
    save_json(current_path, {
        "schema_version": "1.0", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol, "anchor_tf": anchor_tf, "patterns": current,
    })

    metadata = {
        "script": "market_pattern_research.py", "version": "MVP_1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol, "anchor_tf": anchor_tf, "input": str(input_path),
        "rows": len(raw), "timeframes": [str(v).upper() for v in args.timeframes],
        "windows": sorted(set(args.windows)), "horizons": sorted(set(args.horizons)),
        "events": len(events), "active_states": len(states), "statistics_rows": len(stats),
        "skipped_timeframes": skipped,
        "outputs": {"events": str(events_path), "statistics": str(stats_path), "active_states": str(states_path), "current_state": str(current_path)},
    }
    save_json(output_root / "metadata.json", metadata)
    log("OK")
    print(json.dumps(clean_json(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
