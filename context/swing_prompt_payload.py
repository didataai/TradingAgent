#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - Factual Prompt Payload Builder (Swing)

Gera um payload neutro para a LLM. O código seleciona e organiza fatos,
valores exatos e flags algorítmicas, mas NÃO fornece viés, ação, setup,
qualidade de entrada ou narrativa decisória.

Compatível com Windows/Linux e multiativo.

Exemplos:
  python context/prompt_payload.py --symbol GOLD
  python context/prompt_payload.py --symbol GOLD --compact
  python context/prompt_payload.py --symbol GBPUSD --market-data data/consolidated/GBPUSD_swing.parquet
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

TF_ORDER = ("W1", "D1", "H4", "H1", "M15")
RECENT_LIMITS = {"W1": 12, "D1": 12, "H4": 10, "H1": 8, "M15": 8}
LEVEL_LIMITS = {"W1": 6, "D1": 6, "H4": 5, "H1": 4, "M15": 4}
PATTERN_LOOKBACK = {"W1": 40, "D1": 40, "H4": 32, "H1": 24, "M15": 24}

# Campos numéricos que ajudam a LLM a fazer a própria leitura.
INDICATOR_FIELDS = (
    "SMA_10", "SMA_50", "SMA_200", "EMA_20", "EMA_50",
    "RSI", "MACD", "MACD_signal", "MACD_hist",
    "Bollinger_High", "Bollinger_Mid", "Bollinger_Low",
    "ATR", "ADX", "ADX_Positive", "ADX_Negative",
    "Stoch_K", "Stoch_D",
    "Ichimoku_Base", "Ichimoku_Conversion", "Ichimoku_A", "Ichimoku_B",
    "OBV", "MFI", "Williams_%R", "ROC", "Parabolic_SAR",
    "Vortex_Positive", "Vortex_Negative",
)

DERIVED_METRIC_FIELDS = (
    "ret_1", "ret_3", "ret_5", "range_pct", "body_pct", "body_signed_pct",
    "close_pos", "upper_wick_pct", "lower_wick_pct",
    "bull_ratio_5", "bear_ratio_5", "bull_ratio_7", "bear_ratio_7",
    "bull_ratio_10", "bear_ratio_10",
    "vol_ratio", "BB_Width", "ATR_Z", "BB_Width_Z",
    "spread_pct", "spread_z", "ema20_slope_5", "ema50_slope_5",
    "range_atr", "body_atr",
    "dist_sma10_atr", "dist_sma50_atr", "dist_sma200_atr",
    "dist_ema20_atr", "dist_ema50_atr",
    "dist_bb_high_atr", "dist_bb_low_atr",
    "dist_donchian_high20_atr", "dist_donchian_low20_atr",
    "elapsed_bar_ratio", "expected_volume_at_elapsed", "volume_pace_ratio",
    "projected_final_volume", "projected_volume_ratio_20",
    "live_price_position", "live_range_atr", "live_body_atr",
)

BOOLEAN_EVENT_FIELDS = (
    "close_above_prev_close", "close_below_prev_close",
    "high_above_prev_high", "low_below_prev_low",
    "inside_previous_range", "outside_previous_range",
    "breakout_up", "breakout_down", "false_breakout_up", "false_breakout_down",
    "range_expansion_vs_prev", "Volume_Spike", "vol_spike_1p5", "vol_spike_2p0",
    "compression_flag", "expansion_flag",
    "ema20_above_ema50", "ema_cross_up", "ema_cross_dn",
    "swing_high_confirmed", "swing_low_confirmed", "bos_up", "bos_dn",
    "choch_up", "choch_dn", "zigzag_high_confirmed", "zigzag_low_confirmed",
    "sweep_high", "sweep_low", "swing_sweep_high", "swing_sweep_low",
    "fvg_up", "fvg_dn", "bull_ob_candidate_event", "bear_ob_candidate_event",
    "in_bull_ob_candidate", "in_bear_ob_candidate",
    "mitigated_bull_ob_candidate", "mitigated_bear_ob_candidate",
    "in_asia_session", "in_london_session", "in_ny_session",
    "london_killzone", "ny_killzone", "is_london_open_bar", "is_ny_open_bar",
)

PATTERN_FIELDS = (
    "Hammer", "Inverted_Hammer", "Bullish_Engulfing", "Bearish_Engulfing",
    "Doji", "Bullish_Marubozu", "Bearish_Marubozu", "Shooting_Star",
    "Hanging_Man", "Morning_Star", "Evening_Star",
    "Three_White_Soldiers", "Three_Black_Crows", "Piercing_Line",
    "Dark_Cloud_Cover", "Tweezer_Tops", "Tweezer_Bottoms", "Gap_Up", "Gap_Down",
)

LEVEL_FIELD_MAP = {
    "moving_averages": ("SMA_10", "SMA_50", "SMA_200", "EMA_20", "EMA_50"),
    "bollinger": ("Bollinger_High", "Bollinger_Mid", "Bollinger_Low"),
    "swings": ("last_swing_high", "last_swing_low", "confirmed_swing_high_price", "confirmed_swing_low_price"),
    "zigzag": ("last_zigzag_high", "last_zigzag_low", "zigzag_high", "zigzag_low"),
    "session": ("session_high", "session_low"),
    "fibonacci": ("fib_382_retr", "fib_500_retr", "fib_618_retr", "fib_786_retr", "fib_1272_ext", "fib_1618_ext"),
    "fvg": ("fvg_up_low", "fvg_up_high", "fvg_dn_low", "fvg_dn_high"),
    "order_block_candidates": ("bull_ob_candidate_low", "bull_ob_candidate_high", "bear_ob_candidate_low", "bear_ob_candidate_high"),
}


def finite(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return finite(value.item(), default)
        except Exception:
            pass
    return value


def _is_empty(value: Any) -> bool:
    """Retorna True apenas para containers vazios ou None, sem comparar arrays."""
    if value is None:
        return True
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) == 0
    return False


def clean(value: Any) -> Any:
    """Normaliza objetos pandas/numpy e remove valores vazios com segurança."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            cleaned = clean(item)
            if _is_empty(cleaned):
                continue
            out[str(key)] = cleaned
        return out

    # Series, Index, ndarray e similares possuem tolist().
    if not isinstance(value, (str, bytes)) and hasattr(value, "tolist"):
        try:
            value = value.tolist()
        except Exception:
            pass

    if isinstance(value, (list, tuple, set)):
        out: list[Any] = []
        for item in value:
            cleaned = clean(item)
            if _is_empty(cleaned):
                continue
            out.append(cleaned)
        return out

    # Timestamps são serializados em ISO para manter o payload JSON-safe.
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()

    return finite(value)


def rounded(value: Any, digits: int = 6) -> Any:
    value = finite(value)
    if isinstance(value, float):
        return round(value, digits)
    return value


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("O contexto deve ser um objeto JSON.")
    return data


def load_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de mercado não encontrado: {path}")
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path, low_memory=False)
    raise ValueError(f"Formato não suportado: {suffix}")


def latest_row(tf_df: pd.DataFrame) -> pd.Series:
    work = tf_df.copy()
    time_col = "time_brt" if "time_brt" in work.columns else "time"
    work["__sort_time"] = pd.to_datetime(work[time_col], errors="coerce")
    if "is_live_bar" in work.columns:
        live = work[pd.to_numeric(work["is_live_bar"], errors="coerce").fillna(0).astype(int) == 1]
        if not live.empty:
            return live.sort_values("__sort_time").iloc[-1]
    return work.sort_values("__sort_time").iloc[-1]


def row_values(row: pd.Series, fields: tuple[str, ...], boolean: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in fields:
        if field not in row.index:
            continue
        value = finite(row.get(field))
        if value is None:
            continue
        if boolean:
            try:
                value = bool(int(value))
            except (TypeError, ValueError):
                value = bool(value)
        else:
            value = rounded(value)
        out[field] = value
    return out


def exact_levels(row: pd.Series) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for group, fields in LEVEL_FIELD_MAP.items():
        values = row_values(row, fields)
        if values:
            groups[group] = values
    return groups


def previous_bar_reference(tf_df: pd.DataFrame, current_row: pd.Series) -> dict[str, Any]:
    work = tf_df.copy()
    time_col = "time_brt" if "time_brt" in work.columns else "time"
    work["__sort_time"] = pd.to_datetime(work[time_col], errors="coerce")
    work = work.sort_values("__sort_time")
    current_time = pd.to_datetime(current_row.get(time_col), errors="coerce")
    prior = work[work["__sort_time"] < current_time]
    if prior.empty:
        return {}
    prev = prior.iloc[-1]
    return clean({
        "time_brt": str(prev.get("time_brt", prev.get("time"))),
        "open": rounded(prev.get("open")),
        "high": rounded(prev.get("high")),
        "low": rounded(prev.get("low")),
        "close": rounded(prev.get("close")),
        "tick_volume": rounded(prev.get("tick_volume")),
        "spread": rounded(prev.get("spread")),
    })


def select_context_levels(ctx: dict[str, Any], side: str, limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in (ctx.get("levels", {}) or {}).get(side, [])[:limit]:
        selected.append(clean({
            "zone_low": item.get("zone_low"),
            "zone_high": item.get("zone_high"),
            "center": item.get("center"),
            "distance_atr": item.get("distance_atr"),
            "sources": item.get("reasons", []),
        }))
    return selected


def factual_recent_bar(bar: dict[str, Any]) -> dict[str, Any]:
    # "direction" é consequência direta de close-open; mantida como conveniência factual.
    return clean({
        "time_brt": bar.get("time_brt"),
        "bar_status": bar.get("bar_status"),
        "is_live_bar": bar.get("is_live_bar"),
        "ohlc": bar.get("ohlc"),
        "direction_from_ohlc": bar.get("direction"),
        "range_atr": bar.get("range_atr"),
        "body_atr": bar.get("body_atr"),
        "body_to_range": bar.get("body_to_range"),
        "upper_wick_ratio": bar.get("upper_wick_ratio"),
        "lower_wick_ratio": bar.get("lower_wick_ratio"),
        "close_position": bar.get("close_position"),
        "volume_ratio": bar.get("volume_ratio"),
        "volume_pace_ratio": bar.get("volume_pace_ratio"),
        "structure_state_numeric_or_label": bar.get("structure_state"),
        "algorithmic_bar_classification": bar.get("live_state"),
        "algorithmic_events": bar.get("events", []),
    })



def _linear_slope(values: pd.Series) -> float | None:
    clean_values = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean_values) < 2:
        return None
    x = np.arange(len(clean_values), dtype=float)
    try:
        return float(np.polyfit(x, clean_values.to_numpy(dtype=float), 1)[0])
    except Exception:
        return None


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    n = finite(numerator)
    d = finite(denominator)
    if n is None or d in (None, 0):
        return None
    try:
        return float(n) / float(d)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _local_pivots(work: pd.DataFrame, side: str, radius: int = 2) -> list[dict[str, Any]]:
    field = "high" if side == "high" else "low"
    values = pd.to_numeric(work[field], errors="coerce").to_numpy(dtype=float)
    times = work["__sort_time"].tolist()
    pivots: list[dict[str, Any]] = []
    for i in range(radius, len(values) - radius):
        center = values[i]
        if not np.isfinite(center):
            continue
        window = values[i - radius:i + radius + 1]
        if side == "high" and center >= np.nanmax(window):
            pivots.append({"index": i, "time_brt": str(times[i]), "price": float(center)})
        elif side == "low" and center <= np.nanmin(window):
            pivots.append({"index": i, "time_brt": str(times[i]), "price": float(center)})
    return pivots


def _candidate_score(conditions: list[bool]) -> float:
    if not conditions:
        return 0.0
    return round(sum(bool(x) for x in conditions) / len(conditions), 3)


def pattern_geometry(tf_df: pd.DataFrame, tf: str) -> dict[str, Any]:
    """Gera geometria factual e candidatos técnicos sem recomendação direcional."""
    work = tf_df.copy()
    time_col = "time_brt" if "time_brt" in work.columns else "time"
    work["__sort_time"] = pd.to_datetime(work[time_col], errors="coerce")
    work = work.sort_values("__sort_time")
    limit = PATTERN_LOOKBACK.get(tf, 30)
    work = work.tail(limit).copy()
    if len(work) < 8:
        return {}

    for col in ("open", "high", "low", "close", "tick_volume", "ATR"):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    atr_series = work.get("ATR", pd.Series(index=work.index, dtype=float)).dropna()
    atr = float(atr_series.iloc[-1]) if not atr_series.empty and float(atr_series.iloc[-1]) > 0 else None
    if atr is None:
        ranges = (work["high"] - work["low"]).dropna()
        atr = float(ranges.tail(14).mean()) if not ranges.empty else None
    if not atr or not math.isfinite(atr):
        return {}

    geom_window = work.tail(min(12, len(work))).copy()
    high_slope = _linear_slope(geom_window["high"])
    low_slope = _linear_slope(geom_window["low"])
    close_slope = _linear_slope(geom_window["close"])
    high_slope_atr = _safe_ratio(high_slope, atr)
    low_slope_atr = _safe_ratio(low_slope, atr)
    close_slope_atr = _safe_ratio(close_slope, atr)

    width = (geom_window["high"] - geom_window["low"]).dropna()
    midpoint = max(2, len(width) // 2)
    first_width = float(width.iloc[:midpoint].mean()) if len(width.iloc[:midpoint]) else None
    second_width = float(width.iloc[midpoint:].mean()) if len(width.iloc[midpoint:]) else None
    compression_ratio = _safe_ratio(second_width, first_width)

    # Impulso anterior + consolidação recente para bandeiras/flâmulas.
    consolidation_bars = min(6, max(4, len(work) // 4))
    impulse_bars = min(5, max(3, len(work) // 5))
    consolidation = work.tail(consolidation_bars)
    before = work.iloc[: -consolidation_bars]
    impulse = before.tail(impulse_bars) if len(before) >= impulse_bars else before

    impulse_open = finite(impulse["open"].iloc[0]) if not impulse.empty else None
    impulse_close = finite(impulse["close"].iloc[-1]) if not impulse.empty else None
    impulse_move = (float(impulse_close) - float(impulse_open)) if impulse_open is not None and impulse_close is not None else None
    impulse_move_atr = _safe_ratio(impulse_move, atr)
    impulse_direction = "UP" if impulse_move_atr is not None and impulse_move_atr > 0 else "DOWN" if impulse_move_atr is not None and impulse_move_atr < 0 else "FLAT"

    cons_high = finite(consolidation["high"].max())
    cons_low = finite(consolidation["low"].min())
    cons_last_close = finite(consolidation["close"].iloc[-1])
    pullback_depth_pct = None
    if impulse_move not in (None, 0) and cons_last_close is not None and impulse_close is not None:
        if impulse_move > 0:
            pullback_depth_pct = abs((float(impulse_close) - float(cons_low)) / float(impulse_move)) * 100
        else:
            pullback_depth_pct = abs((float(cons_high) - float(impulse_close)) / float(impulse_move)) * 100

    cons_high_slope = _safe_ratio(_linear_slope(consolidation["high"]), atr)
    cons_low_slope = _safe_ratio(_linear_slope(consolidation["low"]), atr)
    cons_width_atr = _safe_ratio(float(cons_high) - float(cons_low), atr) if cons_high is not None and cons_low is not None else None

    volume_impulse = finite(impulse["tick_volume"].mean()) if "tick_volume" in impulse.columns and not impulse.empty else None
    volume_consolidation = finite(consolidation["tick_volume"].mean()) if "tick_volume" in consolidation.columns and not consolidation.empty else None
    volume_consolidation_vs_impulse = _safe_ratio(volume_consolidation, volume_impulse)

    candidates: list[dict[str, Any]] = []
    abs_impulse = abs(impulse_move_atr) if impulse_move_atr is not None else 0.0
    pb_ok = pullback_depth_pct is not None and 10 <= pullback_depth_pct <= 70
    vol_contracting = volume_consolidation_vs_impulse is not None and volume_consolidation_vs_impulse <= 1.05

    bull_flag_conditions = [
        impulse_direction == "UP", abs_impulse >= 1.2, pb_ok,
        cons_high_slope is not None and cons_high_slope <= 0.08,
        cons_low_slope is not None and cons_low_slope <= 0.08,
        vol_contracting,
    ]
    bear_flag_conditions = [
        impulse_direction == "DOWN", abs_impulse >= 1.2, pb_ok,
        cons_high_slope is not None and cons_high_slope >= -0.08,
        cons_low_slope is not None and cons_low_slope >= -0.08,
        vol_contracting,
    ]
    for name, conditions, breakout, invalidation in (
        ("BULL_FLAG", bull_flag_conditions, cons_high, cons_low),
        ("BEAR_FLAG", bear_flag_conditions, cons_low, cons_high),
    ):
        score = _candidate_score(conditions)
        if score >= 0.5:
            candidates.append(clean({
                "name": name,
                "algorithmic_score": score,
                "status": "FORMING_OR_TESTING",
                "breakout_level": rounded(breakout),
                "invalidation_level": rounded(invalidation),
                "evidence_count": sum(bool(x) for x in conditions),
                "evidence_total": len(conditions),
            }))

    # Triângulos e canais pela inclinação e compressão.
    hs = high_slope_atr
    ls = low_slope_atr
    comp = compression_ratio
    triangle_defs = []
    if hs is not None and ls is not None:
        triangle_defs = [
            ("SYMMETRICAL_TRIANGLE", [hs < -0.02, ls > 0.02, comp is not None and comp < 0.9]),
            ("ASCENDING_TRIANGLE", [abs(hs) <= 0.04, ls > 0.02, comp is not None and comp < 0.95]),
            ("DESCENDING_TRIANGLE", [hs < -0.02, abs(ls) <= 0.04, comp is not None and comp < 0.95]),
        ]
        for name, conditions in triangle_defs:
            score = _candidate_score(conditions)
            if score >= 0.667:
                candidates.append(clean({
                    "name": name,
                    "algorithmic_score": score,
                    "status": "FORMING",
                    "upper_breakout_reference": rounded(float(geom_window["high"].max())),
                    "lower_breakout_reference": rounded(float(geom_window["low"].min())),
                }))

        parallel = abs(hs - ls) <= 0.05
        if parallel and abs((hs + ls) / 2) >= 0.02:
            candidates.append(clean({
                "name": "ASCENDING_CHANNEL" if (hs + ls) / 2 > 0 else "DESCENDING_CHANNEL",
                "algorithmic_score": _candidate_score([parallel, abs((hs + ls) / 2) >= 0.02, comp is None or comp >= 0.65]),
                "status": "ACTIVE_CANDIDATE",
                "upper_reference": rounded(float(geom_window["high"].max())),
                "lower_reference": rounded(float(geom_window["low"].min())),
            }))

    # Topo/fundo duplo com pivôs locais e tolerância em ATR.
    highs = _local_pivots(work, "high")
    lows = _local_pivots(work, "low")
    tolerance_atr = 0.45
    if len(highs) >= 2:
        p1, p2 = highs[-2], highs[-1]
        sep = p2["index"] - p1["index"]
        diff_atr = abs(p2["price"] - p1["price"]) / atr
        if sep >= 3 and diff_atr <= tolerance_atr:
            between = work.iloc[p1["index"]:p2["index"] + 1]
            neckline = finite(between["low"].min())
            candidates.append(clean({
                "name": "DOUBLE_TOP",
                "algorithmic_score": _candidate_score([sep >= 3, diff_atr <= tolerance_atr, neckline is not None]),
                "status": "CANDIDATE_NOT_CONFIRMED",
                "peak_1": p1,
                "peak_2": p2,
                "peak_difference_atr": rounded(diff_atr, 4),
                "neckline_reference": rounded(neckline),
            }))
    if len(lows) >= 2:
        p1, p2 = lows[-2], lows[-1]
        sep = p2["index"] - p1["index"]
        diff_atr = abs(p2["price"] - p1["price"]) / atr
        if sep >= 3 and diff_atr <= tolerance_atr:
            between = work.iloc[p1["index"]:p2["index"] + 1]
            neckline = finite(between["high"].max())
            candidates.append(clean({
                "name": "DOUBLE_BOTTOM",
                "algorithmic_score": _candidate_score([sep >= 3, diff_atr <= tolerance_atr, neckline is not None]),
                "status": "CANDIDATE_NOT_CONFIRMED",
                "trough_1": p1,
                "trough_2": p2,
                "trough_difference_atr": rounded(diff_atr, 4),
                "neckline_reference": rounded(neckline),
            }))

    last_row = work.iloc[-1]
    fib_anchors = clean({
        "direction": finite(last_row.get("fib_direction")),
        "last_swing_high": rounded(last_row.get("last_swing_high")),
        "last_swing_low": rounded(last_row.get("last_swing_low")),
        "last_zigzag_high": rounded(last_row.get("last_zigzag_high")),
        "last_zigzag_low": rounded(last_row.get("last_zigzag_low")),
        "retracement_382": rounded(last_row.get("fib_382_retr")),
        "retracement_500": rounded(last_row.get("fib_500_retr")),
        "retracement_618": rounded(last_row.get("fib_618_retr")),
        "retracement_786": rounded(last_row.get("fib_786_retr")),
        "extension_1272": rounded(last_row.get("fib_1272_ext")),
        "extension_1618": rounded(last_row.get("fib_1618_ext")),
    })

    return clean({
        "geometry_window_bars": len(geom_window),
        "atr_reference": rounded(atr),
        "trendline_geometry": {
            "high_slope_price_per_bar": rounded(high_slope),
            "low_slope_price_per_bar": rounded(low_slope),
            "close_slope_price_per_bar": rounded(close_slope),
            "high_slope_atr_per_bar": rounded(high_slope_atr, 5),
            "low_slope_atr_per_bar": rounded(low_slope_atr, 5),
            "close_slope_atr_per_bar": rounded(close_slope_atr, 5),
            "range_compression_ratio_second_half_vs_first_half": rounded(compression_ratio, 4),
        },
        "impulse_and_consolidation": {
            "impulse_bars": len(impulse),
            "consolidation_bars": len(consolidation),
            "impulse_direction_from_ohlc": impulse_direction,
            "impulse_move_atr": rounded(impulse_move_atr, 4),
            "pullback_depth_pct": rounded(pullback_depth_pct, 2),
            "consolidation_high_slope_atr_per_bar": rounded(cons_high_slope, 5),
            "consolidation_low_slope_atr_per_bar": rounded(cons_low_slope, 5),
            "consolidation_width_atr": rounded(cons_width_atr, 4),
            "volume_consolidation_vs_impulse": rounded(volume_consolidation_vs_impulse, 4),
            "upper_breakout_reference": rounded(cons_high),
            "lower_breakout_reference": rounded(cons_low),
        },
        "local_pivots": {
            "recent_highs": highs[-4:],
            "recent_lows": lows[-4:],
        },
        "fibonacci_anchors_and_levels": fib_anchors,
        "pattern_candidates": candidates,
        "candidate_semantics": "Candidatos algorítmicos baseados em geometria; não constituem confirmação, viés ou recomendação.",
    })

def build_timeframe_payload(tf: str, tf_df: pd.DataFrame, ctx: dict[str, Any]) -> dict[str, Any]:
    row = latest_row(tf_df)
    bars = ctx.get("recent_bars", [])[-RECENT_LIMITS.get(tf, 6):]

    current_bar = clean({
        "time_brt": str(row.get("time_brt", row.get("time"))),
        "time_broker": str(row.get("time_broker")) if finite(row.get("time_broker")) is not None else None,
        "time_london": str(row.get("time_london")) if finite(row.get("time_london")) is not None else None,
        "time_ny": str(row.get("time_ny")) if finite(row.get("time_ny")) is not None else None,
        "is_live_bar": bool(int(finite(row.get("is_live_bar"), 0))),
        "bar_status": ctx.get("bar_status"),
        "open": rounded(row.get("open")),
        "high": rounded(row.get("high")),
        "low": rounded(row.get("low")),
        "close": rounded(row.get("close")),
        "tick_volume": rounded(row.get("tick_volume")),
        "real_volume": rounded(row.get("real_volume")),
        "spread": rounded(row.get("spread")),
        "session_name": finite(row.get("session_name")),
    })

    annotations = clean({
        "structure_state": rounded(row.get("structure_state")),
        "body_direction": finite(row.get("body_direction")),
        "live_bar_classification": finite(row.get("live_bar_classification")),
        "fib_direction": finite(row.get("fib_direction")),
        "event_flags": row_values(row, BOOLEAN_EVENT_FIELDS, boolean=True),
        "pattern_flags": row_values(row, PATTERN_FIELDS, boolean=True),
    })

    return clean({
        "current_bar": current_bar,
        "previous_closed_bar": previous_bar_reference(tf_df, row),
        "indicators_exact": row_values(row, INDICATOR_FIELDS),
        "derived_metrics_exact": row_values(row, DERIVED_METRIC_FIELDS),
        "algorithmic_annotations": annotations,
        "exact_reference_levels": exact_levels(row),
        "pattern_geometry": pattern_geometry(tf_df, tf),
        "nearby_level_zones": {
            "below_current_price": select_context_levels(ctx, "supports", LEVEL_LIMITS.get(tf, 3)),
            "above_current_price": select_context_levels(ctx, "resistances", LEVEL_LIMITS.get(tf, 3)),
        },
        "recent_bars": [factual_recent_bar(bar) for bar in bars],
    })


def find_default_context(project_root: Path, symbol: str) -> Path:
    path = project_root / "data" / "context" / f"{symbol}_swing_context.json"
    if not path.exists():
        raise FileNotFoundError(f"Não encontrei {path}. Execute timeframe_context.py ou use --context.")
    return path


def find_default_market_data(project_root: Path, symbol: str) -> Path:
    base = project_root / "data" / "consolidated"
    candidates = (
        base / f"{symbol}_swing.parquet",
        base / f"{symbol}_swing.csv",
        base / f"{symbol}_full.parquet",
        base / f"{symbol}_full.csv",
    )
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        f"Não encontrei dados consolidados de {symbol} em {base}. Use --market-data."
    )


def build_payload(context: dict[str, Any], market_df: pd.DataFrame, market_path: Path) -> dict[str, Any]:
    symbol = str(context.get("symbol", "UNKNOWN")).upper()
    raw_tfs = context.get("timeframes", {})

    if "symbol" in market_df.columns:
        market_df = market_df[market_df["symbol"].astype(str).str.upper() == symbol]

    timeframes: dict[str, Any] = {}
    for tf in TF_ORDER:
        if tf not in raw_tfs:
            continue
        if "timeframe" not in market_df.columns:
            raise ValueError("O consolidado não possui a coluna timeframe.")
        tf_df = market_df[market_df["timeframe"].astype(str).str.upper() == tf].copy()
        if tf_df.empty:
            continue
        timeframes[tf] = build_timeframe_payload(tf, tf_df, raw_tfs[tf])

    return clean({
        "payload_schema_version": "2.1",
        "payload_type": "FACTUAL_SWING_MARKET_DATA",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "context_generated_at_utc": context.get("generated_at_utc"),
        "symbol": symbol,
        "current_price": context.get("current_price"),
        "market_status": (context.get("market_summary", {}) or {}).get("market_status"),
        "source": {
            "market_data_file": str(market_path.resolve()),
            "context_file": context.get("source_file"),
            "timeframes_included": list(timeframes.keys()),
        },
        "timeframes": timeframes,
        "data_semantics": {
            "structure_state": "Valor algorítmico: positivo=estrutura de alta, negativo=estrutura de baixa, zero=neutra/indefinida.",
            "algorithmic_events": "Flags calculadas por regras causais. São observações auxiliares, não recomendações.",
            "nearby_level_zones": "Agrupamentos matemáticos de níveis próximos. O campo sources informa a origem; não implica força garantida.",
            "bar_live_rule": "A barra LIVE ainda pode mudar. Para W1/D1, somente barras CLOSED confirmam rompimentos estruturais.",
            "pattern_geometry": "Inclinações, compressão, impulso, pullback, pivôs e candidatos são cálculos geométricos auxiliares. A LLM deve validar o padrão pelos candles e pelo rompimento.",
        },
        "data_limitations": {
            "volume_type": "MT5_TICK_VOLUME",
            "order_flow": "INFERRED_FROM_OHLC_TICK_VOLUME_SPREAD_AND_STRUCTURE_ONLY",
            "exchange_delta_available": False,
            "footprint_available": False,
            "level2_order_book_available": False,
            "future_labels_included": False,
            "decision_or_bias_included": False,
        },
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera payload factual swing, sem viés decisório.")
    parser.add_argument("--context", type=Path, help="JSON de timeframe_context.py")
    parser.add_argument("--market-data", type=Path, help="Parquet/CSV consolidado swing")
    parser.add_argument("--symbol", default="GOLD", help="Símbolo desejado")
    parser.add_argument("--output", type=Path, help="Arquivo JSON de saída")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    context_path = args.context or find_default_context(args.project_root, symbol)
    market_path = args.market_data or find_default_market_data(args.project_root, symbol)

    context = read_json(context_path)
    context_symbol = str(context.get("symbol", symbol)).upper()
    if context_symbol != symbol:
        raise ValueError(f"Símbolo do contexto ({context_symbol}) diferente do solicitado ({symbol}).")

    market_df = load_table(market_path)
    payload = build_payload(context, market_df, market_path)

    output_path = args.output or (
        args.project_root / "data" / "payload" / f"{symbol}_swing_payload.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    indent = None if args.compact else 2
    separators = (",", ":") if args.compact else None
    rendered = json.dumps(payload, ensure_ascii=False, indent=indent, separators=separators)
    output_path.write_text(rendered, encoding="utf-8")

    print(f"Payload factual salvo: {output_path}")
    print(
        f"Símbolo={symbol} | schema={payload.get('payload_schema_version')} | "
        f"timeframes={list(payload.get('timeframes', {}).keys())} | "
        f"viés_decisão_incluído=False | bytes={output_path.stat().st_size}"
    )
    if args.stdout:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
