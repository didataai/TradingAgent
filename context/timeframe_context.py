#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - Context Builder por Timeframe

Lê um consolidado intraday Parquet/CSV e gera um JSON compacto para o agente, incluindo uma janela curta de candles.
Compatível com Windows/Linux, multiativo e sem dependência do MT5.

Exemplos:
  python context/timeframe_context.py --symbol GOLD
  python context/timeframe_context.py --input data/consolidated/GOLD_intraday.parquet
  python context/timeframe_context.py --input data/consolidated/GOLD_intraday.csv --output data/context/GOLD_context.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

DEFAULT_TFS = ("H4", "H1", "M15", "M5", "M1")
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}
RECENT_BAR_COUNTS = {"H4": 5, "H1": 5, "M15": 8, "M5": 10, "M1": 6}


def finite(value: Any, default: Any = None) -> Any:
    """Converte tipos numpy e remove NaN/inf para JSON válido."""
    if value is None:
        return default
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else default
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return default
    return value


def num(row: pd.Series, name: str, default: float | None = None) -> float | None:
    return finite(row.get(name), default)


def flag(row: pd.Series, name: str) -> bool:
    value = row.get(name, 0)
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return bool(value) if not pd.isna(value) else False


def text(row: pd.Series, name: str, default: str = "UNKNOWN") -> str:
    value = row.get(name)
    if value is None or pd.isna(value) or str(value).strip() == "":
        return default
    return str(value)


def round_or_none(value: Any, digits: int = 5) -> float | None:
    value = finite(value)
    return round(float(value), digits) if value is not None else None


def load_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path, low_memory=False)
    raise ValueError(f"Formato não suportado: {suffix}. Use Parquet ou CSV.")


def latest_row(tf_df: pd.DataFrame) -> pd.Series:
    work = tf_df.copy()
    time_col = "time_brt" if "time_brt" in work.columns else "time"
    work["__sort_time"] = pd.to_datetime(work[time_col], errors="coerce", utc=True)
    if "is_live_bar" in work.columns:
        live = work[pd.to_numeric(work["is_live_bar"], errors="coerce").fillna(0).astype(int) == 1]
        if not live.empty:
            return live.sort_values("__sort_time").iloc[-1]
    return work.sort_values("__sort_time").iloc[-1]


def recent_closed(tf_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    work = tf_df.copy()
    if "is_live_bar" in work.columns:
        work = work[pd.to_numeric(work["is_live_bar"], errors="coerce").fillna(0).astype(int) == 0]
    time_col = "time_brt" if "time_brt" in work.columns else "time"
    work["__sort_time"] = pd.to_datetime(work[time_col], errors="coerce", utc=True)
    return work.sort_values("__sort_time").tail(n)


def classify_structure(row: pd.Series) -> str:
    state = num(row, "structure_state", 0) or 0
    ema20 = num(row, "EMA_20")
    ema50 = num(row, "EMA_50")
    slope20 = num(row, "ema20_slope_5", 0) or 0
    if state > 0:
        return "BULLISH"
    if state < 0:
        return "BEARISH"
    if ema20 is not None and ema50 is not None:
        if ema20 > ema50 and slope20 > 0:
            return "BULLISH_WEAK"
        if ema20 < ema50 and slope20 < 0:
            return "BEARISH_WEAK"
    return "NEUTRAL"


def classify_momentum(row: pd.Series, structure: str, live_state: str) -> str:
    rsi = num(row, "RSI", 50) or 50
    macd_hist = num(row, "MACD_hist", 0) or 0
    adx = num(row, "ADX", 0) or 0
    pos = num(row, "ADX_Positive", 0) or 0
    neg = num(row, "ADX_Negative", 0) or 0

    direction = "NEUTRAL"
    if macd_hist > 0 and pos > neg:
        direction = "BULLISH"
    elif macd_hist < 0 and neg > pos:
        direction = "BEARISH"
    elif rsi >= 55:
        direction = "BULLISH"
    elif rsi <= 45:
        direction = "BEARISH"

    strength = "STRONG" if adx >= 25 else "MODERATE" if adx >= 18 else "WEAK"
    extension = "_OVERBOUGHT" if rsi >= 70 else "_OVERSOLD" if rsi <= 30 else ""

    if structure.startswith("BEARISH") and direction != "BEARISH":
        return f"BEARISH_STRUCTURE_MOMENTUM_MIXED_{strength}{extension}"
    if structure.startswith("BULLISH") and direction != "BULLISH":
        return f"BULLISH_STRUCTURE_MOMENTUM_MIXED_{strength}{extension}"
    return f"{direction}_{strength}{extension}"


def classify_bar_status(tf: str, row: pd.Series) -> str:
    raw = row.get("time_brt", row.get("time"))
    ts = pd.to_datetime(raw, errors="coerce")
    if pd.isna(ts):
        return "UNKNOWN"
    if ts.tzinfo is None:
        ts = ts.tz_localize("America/Sao_Paulo")
    else:
        ts = ts.tz_convert("America/Sao_Paulo")
    now = pd.Timestamp.now(tz="America/Sao_Paulo")
    duration = pd.Timedelta(minutes=TF_MINUTES.get(tf, 1))
    age = now - ts
    if not flag(row, "is_live_bar"):
        return "CLOSED"
    if age <= duration * 1.5:
        return "LIVE"
    return "STALE_LAST_BAR"


def classify_volume(row: pd.Series) -> str:
    pace = num(row, "volume_pace_ratio")
    projected = num(row, "projected_volume_ratio_20")
    ratio = pace if pace is not None else projected
    if ratio is None:
        ratio = num(row, "vol_ratio")
    if ratio is None:
        return "UNKNOWN"
    if ratio >= 1.5:
        return "VERY_HIGH"
    if ratio >= 1.1:
        return "ABOVE_EXPECTED"
    if ratio >= 0.85:
        return "NEAR_EXPECTED"
    if ratio >= 0.6:
        return "BELOW_EXPECTED"
    return "VERY_LOW"


def classify_volatility(row: pd.Series) -> str:
    compression = flag(row, "compression_flag")
    expansion = flag(row, "expansion_flag")
    atr_z = num(row, "ATR_Z", 0) or 0
    range_atr = num(row, "range_atr", 0) or 0
    if compression:
        return "COMPRESSION"
    if expansion or atr_z >= 1.0 or range_atr >= 1.5:
        return "EXPANSION"
    if atr_z <= -1.0:
        return "LOW_VOLATILITY"
    return "NORMAL"


def classify_location(row: pd.Series) -> str:
    pos = num(row, "live_price_position")
    if pos is None:
        pos = num(row, "close_pos")
    if pos is None:
        return "UNKNOWN"
    if pos <= 0.15:
        return "NEAR_BAR_LOW"
    if pos <= 0.35:
        return "LOWER_THIRD"
    if pos < 0.65:
        return "MID_RANGE"
    if pos < 0.85:
        return "UPPER_THIRD"
    return "NEAR_BAR_HIGH"


def detect_events(row: pd.Series) -> list[str]:
    event_map = {
        "bos_up": "BOS_UP",
        "bos_dn": "BOS_DOWN",
        "choch_up": "CHOCH_UP",
        "choch_dn": "CHOCH_DOWN",
        "breakout_up": "BREAKOUT_UP",
        "breakout_down": "BREAKOUT_DOWN",
        "false_breakout_up": "FALSE_BREAKOUT_UP",
        "false_breakout_down": "FALSE_BREAKOUT_DOWN",
        "sweep_high": "SWEEP_HIGH",
        "sweep_low": "SWEEP_LOW",
        "swing_sweep_high": "SWING_SWEEP_HIGH",
        "swing_sweep_low": "SWING_SWEEP_LOW",
        "fvg_up": "FVG_UP",
        "fvg_dn": "FVG_DOWN",
        "Volume_Spike": "VOLUME_SPIKE",
        "compression_flag": "COMPRESSION",
        "expansion_flag": "EXPANSION",
    }
    events = [label for col, label in event_map.items() if flag(row, col)]
    live_class = text(row, "live_bar_classification", "")
    if live_class and live_class not in {"UNKNOWN", "NOT_LIVE"} and live_class not in events:
        events.insert(0, live_class)
    return events


def candle_direction(row: pd.Series) -> str:
    open_ = num(row, "open")
    close = num(row, "close")
    if open_ is None or close is None:
        return "UNKNOWN"
    if close > open_:
        return "BULLISH"
    if close < open_:
        return "BEARISH"
    return "DOJI"


def candle_shape(row: pd.Series) -> dict[str, float | None]:
    """Mede corpo e pavios sem depender de colunas pré-calculadas."""
    open_ = num(row, "open")
    high = num(row, "high")
    low = num(row, "low")
    close = num(row, "close")
    atr = num(row, "ATR")
    if None in {open_, high, low, close}:
        return {
            "body_atr": None,
            "body_to_range": None,
            "upper_wick_ratio": None,
            "lower_wick_ratio": None,
        }

    candle_range = max(float(high) - float(low), 0.0)
    body = abs(float(close) - float(open_))
    upper_wick = max(float(high) - max(float(open_), float(close)), 0.0)
    lower_wick = max(min(float(open_), float(close)) - float(low), 0.0)

    return {
        "body_atr": round_or_none(body / atr, 3) if atr and atr > 0 else None,
        "body_to_range": round_or_none(body / candle_range, 3) if candle_range > 0 else 0.0,
        "upper_wick_ratio": round_or_none(upper_wick / candle_range, 3) if candle_range > 0 else 0.0,
        "lower_wick_ratio": round_or_none(lower_wick / candle_range, 3) if candle_range > 0 else 0.0,
    }


def summarize_recent_bars(tf: str, tf_df: pd.DataFrame, count: int | None = None) -> list[dict[str, Any]]:
    """Retorna uma janela curta de candles, sem labels/futuro, para interpretação da LLM."""
    count = count or RECENT_BAR_COUNTS.get(tf, 6)
    work = tf_df.copy()
    time_col = "time_brt" if "time_brt" in work.columns else "time"
    work["__sort_time"] = pd.to_datetime(work[time_col], errors="coerce", utc=True)
    work = work.sort_values("__sort_time").tail(count)

    bars: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        live_state = text(row, "live_bar_classification", "UNKNOWN")
        events = detect_events(row)
        bars.append({
            "time_brt": text(row, "time_brt", text(row, "time", "UNKNOWN")),
            "is_live_bar": flag(row, "is_live_bar"),
            "bar_status": classify_bar_status(tf, row),
            "ohlc": {
                "open": round_or_none(num(row, "open")),
                "high": round_or_none(num(row, "high")),
                "low": round_or_none(num(row, "low")),
                "close": round_or_none(num(row, "close")),
            },
            "direction": candle_direction(row),
            "range_atr": round_or_none(num(row, "range_atr"), 3),
            **candle_shape(row),
            "close_position": round_or_none(num(row, "close_pos", num(row, "live_price_position")), 3),
            "volume_ratio": round_or_none(num(row, "vol_ratio"), 3),
            "volume_pace_ratio": round_or_none(num(row, "volume_pace_ratio"), 3),
            "structure_state": classify_structure(row),
            "live_state": live_state,
            "events": events[:6],
        })
    return bars


def candidate_levels(row: pd.Series, current_price: float) -> list[dict[str, Any]]:
    fields = {
        "last_swing_high": "SWING_HIGH",
        "last_swing_low": "SWING_LOW",
        "last_zigzag_high": "ZIGZAG_HIGH",
        "last_zigzag_low": "ZIGZAG_LOW",
        "session_high": "SESSION_HIGH",
        "session_low": "SESSION_LOW",
        "Bollinger_High": "BB_HIGH",
        "Bollinger_Low": "BB_LOW",
        "EMA_20": "EMA20",
        "EMA_50": "EMA50",
        "SMA_200": "SMA200",
        "fib_382_retr": "FIB_382",
        "fib_500_retr": "FIB_500",
        "fib_618_retr": "FIB_618",
        "fib_1272_ext": "FIB_1272",
        "fib_1618_ext": "FIB_1618",
        "fvg_up_low": "FVG_UP_LOW",
        "fvg_up_high": "FVG_UP_HIGH",
        "fvg_dn_low": "FVG_DOWN_LOW",
        "fvg_dn_high": "FVG_DOWN_HIGH",
        "bull_ob_candidate_low": "BULL_OB_LOW",
        "bull_ob_candidate_high": "BULL_OB_HIGH",
        "bear_ob_candidate_low": "BEAR_OB_LOW",
        "bear_ob_candidate_high": "BEAR_OB_HIGH",
    }
    levels: list[dict[str, Any]] = []
    for col, reason in fields.items():
        value = num(row, col)
        if value is None or value <= 0:
            continue
        levels.append({
            "price": float(value),
            "side": "RESISTANCE" if value > current_price else "SUPPORT",
            "reason": reason,
            "distance": abs(value - current_price),
        })
    return levels


def cluster_levels(levels: Iterable[dict[str, Any]], atr: float | None, tf: str, max_each_side: int = 4) -> dict[str, list[dict[str, Any]]]:
    tolerance = max((atr or 0) * 0.15, 0.01)
    max_atr_distance = {"M1": 4.0, "M5": 4.0, "M15": 5.0, "H1": 6.0}.get(tf, 5.0)
    result: dict[str, list[dict[str, Any]]] = {"supports": [], "resistances": []}

    for side, key in (("SUPPORT", "supports"), ("RESISTANCE", "resistances")):
        items = sorted((x for x in levels if x["side"] == side and ((atr is None) or (x["distance"] <= atr * max_atr_distance))), key=lambda x: x["price"])
        clusters: list[list[dict[str, Any]]] = []
        for item in items:
            if not clusters or abs(item["price"] - np.mean([x["price"] for x in clusters[-1]])) > tolerance:
                clusters.append([item])
            else:
                clusters[-1].append(item)

        summarized = []
        for cluster in clusters:
            prices = [x["price"] for x in cluster]
            reasons = sorted(set(x["reason"] for x in cluster))
            summarized.append({
                "zone_low": round(min(prices), 5),
                "zone_high": round(max(prices), 5),
                "center": round(float(np.mean(prices)), 5),
                "strength": "HIGH" if len(reasons) >= 3 else "MEDIUM" if len(reasons) == 2 else "LOW",
                "reasons": reasons,
                "distance": min(x["distance"] for x in cluster),
                "distance_atr": round(min(x["distance"] for x in cluster) / atr, 3) if atr else None,
            })

        summarized.sort(key=lambda x: x["distance"])
        for item in summarized[:max_each_side]:
            item.pop("distance", None)
        result[key] = summarized[:max_each_side]
    return result


def entry_quality(structure: str, momentum: str, volume_state: str, location: str, live_state: str) -> dict[str, str]:
    direction = "WAIT"
    quality = "LOW"
    reason = "SEM_CONFLUENCIA_SUFFICIENTE"

    bearish = structure.startswith("BEARISH") and momentum.startswith("BEARISH")
    bullish = structure.startswith("BULLISH") and momentum.startswith("BULLISH")
    volume_ok = volume_state in {"NEAR_EXPECTED", "ABOVE_EXPECTED", "VERY_HIGH"}

    if bearish:
        direction = "SELL"
        if location in {"NEAR_BAR_LOW", "LOWER_THIRD"}:
            reason = "DIRECAO_BAIXISTA_MAS_ENTRADA_ESTICADA"
        elif "FALSE_BREAKOUT_DOWN" in live_state:
            reason = "ROMPIMENTO_BAIXISTA_REJEITADO"
        elif volume_ok:
            quality, reason = "HIGH", "CONFLUENCIA_BAIXISTA_COM_VOLUME"
        else:
            quality, reason = "MEDIUM", "CONFLUENCIA_BAIXISTA_SEM_CONFIRMACAO_DE_VOLUME"
    elif bullish:
        direction = "BUY"
        if location in {"NEAR_BAR_HIGH", "UPPER_THIRD"}:
            reason = "DIRECAO_ALTISTA_MAS_ENTRADA_ESTICADA"
        elif "FALSE_BREAKOUT_UP" in live_state:
            reason = "ROMPIMENTO_ALTISTA_REJEITADO"
        elif volume_ok:
            quality, reason = "HIGH", "CONFLUENCIA_ALTISTA_COM_VOLUME"
        else:
            quality, reason = "MEDIUM", "CONFLUENCIA_ALTISTA_SEM_CONFIRMACAO_DE_VOLUME"

    return {"directional_setup": direction, "quality": quality, "reason": reason}


def build_tf_context(tf: str, tf_df: pd.DataFrame) -> dict[str, Any]:
    row = latest_row(tf_df)
    closed = recent_closed(tf_df, 20)
    current_price = float(num(row, "close", 0) or 0)
    atr = num(row, "ATR")

    structure = classify_structure(row)
    live_state = text(row, "live_bar_classification", "UNKNOWN")
    momentum = classify_momentum(row, structure, live_state)
    volume_state = classify_volume(row)
    volatility = classify_volatility(row)
    location = classify_location(row)
    bar_status = classify_bar_status(tf, row)
    levels = cluster_levels(candidate_levels(row, current_price), atr, tf)

    recent_high = round_or_none(pd.to_numeric(closed.get("high"), errors="coerce").max()) if not closed.empty else None
    recent_low = round_or_none(pd.to_numeric(closed.get("low"), errors="coerce").min()) if not closed.empty else None

    return {
        "timeframe": tf,
        "bar_time_brt": text(row, "time_brt", text(row, "time", "UNKNOWN")),
        "is_live_bar": flag(row, "is_live_bar"),
        "bar_status": bar_status,
        "ohlc": {
            "open": round_or_none(num(row, "open")),
            "high": round_or_none(num(row, "high")),
            "low": round_or_none(num(row, "low")),
            "close": round_or_none(current_price),
        },
        "state": {
            "structure": structure,
            "momentum": momentum,
            "live_bar": live_state,
            "volume": volume_state,
            "volatility": volatility,
            "location": location,
            "session": text(row, "session_name", "UNKNOWN"),
        },
        "metrics": {
            "rsi": round_or_none(num(row, "RSI"), 2),
            "adx": round_or_none(num(row, "ADX"), 2),
            "adx_positive": round_or_none(num(row, "ADX_Positive"), 2),
            "adx_negative": round_or_none(num(row, "ADX_Negative"), 2),
            "atr": round_or_none(atr),
            "range_atr": round_or_none(num(row, "range_atr"), 3),
            "elapsed_bar_ratio": round_or_none(num(row, "elapsed_bar_ratio"), 4),
            "volume_pace_ratio": round_or_none(num(row, "volume_pace_ratio"), 3),
            "projected_volume_ratio_20": round_or_none(num(row, "projected_volume_ratio_20"), 3),
            "bull_ratio_5": round_or_none(num(row, "bull_ratio_5"), 3),
            "bear_ratio_5": round_or_none(num(row, "bear_ratio_5"), 3),
        },
        "events": detect_events(row),
        "recent_closed_range_20": {"high": recent_high, "low": recent_low},
        "levels": levels,
        "entry_assessment": entry_quality(structure, momentum, volume_state, location, live_state),
        "recent_bars": summarize_recent_bars(tf, tf_df),
    }


def aggregate_market(timeframes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    weights = {"H4": 5, "H1": 4, "M15": 3, "M5": 2, "M1": 1}
    score = 0
    total = 0
    conflicts: list[str] = []
    traces: list[str] = []

    for tf, ctx in timeframes.items():
        structure = ctx["state"]["structure"]
        weight = weights.get(tf, 1)
        total += weight
        if structure.startswith("BULLISH"):
            score += weight
        elif structure.startswith("BEARISH"):
            score -= weight

    if score >= total * 0.45:
        direction = "BULLISH"
    elif score <= -total * 0.45:
        direction = "BEARISH"
    else:
        direction = "MIXED"

    ordered = [tf for tf in DEFAULT_TFS if tf in timeframes]
    for tf in ordered:
        ctx = timeframes[tf]
        traces.append(
            f"{tf}:{ctx['state']['structure']}/{ctx['state']['live_bar']}/{ctx['state']['volume']}"
        )

    if "H1" in timeframes and "M5" in timeframes:
        h1 = timeframes["H1"]["state"]["structure"]
        m5 = timeframes["M5"]["state"]["structure"]
        if h1.startswith("BEARISH") and m5.startswith("BULLISH"):
            conflicts.append("M5_REACAO_ALTISTA_CONTRA_H1_BAIXISTA")
        if h1.startswith("BULLISH") and m5.startswith("BEARISH"):
            conflicts.append("M5_REACAO_BAIXISTA_CONTRA_H1_ALTISTA")

    active_volume_tfs = [
        (tf, ctx) for tf, ctx in timeframes.items()
        if ctx["state"]["volume"] in {"NEAR_EXPECTED", "ABOVE_EXPECTED", "VERY_HIGH"}
    ]
    volume_confirmations = len(active_volume_tfs)
    participation_strength = (
        "STRONG" if volume_confirmations >= 3 else
        "MODERATE" if volume_confirmations >= 2 else
        "WEAK"
    )

    directional_votes: list[str] = []
    for tf, ctx in active_volume_tfs:
        structure = ctx["state"]["structure"]
        live_state = ctx["state"]["live_bar"]
        if "BREAKOUT_UP" in live_state or structure.startswith("BULLISH"):
            directional_votes.append("BULLISH")
        if "BREAKOUT_DOWN" in live_state or structure.startswith("BEARISH"):
            directional_votes.append("BEARISH")
    if directional_votes and all(v == "BULLISH" for v in directional_votes):
        directional_volume_confirmation = "BULLISH"
    elif directional_votes and all(v == "BEARISH" for v in directional_votes):
        directional_volume_confirmation = "BEARISH"
    elif directional_votes:
        directional_volume_confirmation = "MIXED"
    else:
        directional_volume_confirmation = "WEAK_OR_UNKNOWN"

    # Compatibilidade com consumidores anteriores.
    volume_confirmation = participation_strength

    immediate_action = "WAIT"
    preferred_setup = "AGUARDAR_MELHOR_CONFLUENCIA"
    if direction == "BEARISH":
        immediate_action = "WAIT" if volume_confirmation == "WEAK" else "SELL_ON_CONFIRMATION"
        preferred_setup = "SELL_PULLBACK_OR_CONFIRMED_BREAKDOWN"
    elif direction == "BULLISH":
        immediate_action = "WAIT" if volume_confirmation == "WEAK" else "BUY_ON_CONFIRMATION"
        preferred_setup = "BUY_PULLBACK_OR_CONFIRMED_BREAKOUT"

    stale = [tf for tf, ctx in timeframes.items() if ctx.get("bar_status") == "STALE_LAST_BAR"]
    live = [tf for tf, ctx in timeframes.items() if ctx.get("bar_status") == "LIVE"]
    market_status = "LIVE" if live else "CLOSED_OR_STALE" if stale else "UNKNOWN"

    narrative: list[str] = []
    if "H1" in timeframes:
        h = timeframes["H1"]
        narrative.append(f"H1 mantém estrutura {h['state']['structure']} com estado {h['state']['live_bar']} e volume {h['state']['volume']}.")
    if "M15" in timeframes:
        h = timeframes["M15"]
        narrative.append(f"M15 confirma/contesta a direção principal com momentum {h['state']['momentum']} e volume {h['state']['volume']}.")
    if "M5" in timeframes:
        h = timeframes["M5"]
        if "FALSE_BREAKOUT" in h['state']['live_bar']:
            narrative.append(f"M5 mostra rejeição do rompimento ({h['state']['live_bar']}), reduzindo a qualidade de entrada imediata.")
        else:
            narrative.append(f"M5 está em {h['state']['live_bar']} com estrutura {h['state']['structure']} e volume {h['state']['volume']}.")
    if "M1" in timeframes:
        h = timeframes["M1"]
        narrative.append(f"M1 representa o microfluxo: {h['state']['structure']}, {h['state']['live_bar']}, volume {h['state']['volume']}.")
    if stale:
        narrative.append("Últimas barras paradas/defasadas em " + ", ".join(stale) + "; interpretar como fechamento de sessão, não como fluxo ao vivo.")

    return {
        "market_status": market_status,
        "directional_state": direction,
        "weighted_structure_score": score,
        "volume_confirmation": volume_confirmation,
        "participation_strength": participation_strength,
        "directional_volume_confirmation": directional_volume_confirmation,
        "conflicts": conflicts,
        "trace_compact": traces,
        "trace_narrative": narrative,
        "immediate_action": immediate_action,
        "preferred_setup": preferred_setup,
    }


def find_default_input(project_root: Path, symbol: str) -> Path:
    base = project_root / "data" / "consolidated"
    # Prioridade operacional: intraday. O full é fallback seguro porque este
    # builder seleciona apenas campos presentes/pasados e ignora labels futuros.
    for product in ("intraday", "full"):
        for suffix in (".parquet", ".csv"):
            candidate = base / f"{symbol}_{product}{suffix}"
            if candidate.exists():
                if product == "full":
                    print(
                        f"AVISO: {symbol}_intraday não encontrado; usando {candidate.name} como fallback.",
                        file=sys.stderr,
                    )
                return candidate
    raise FileNotFoundError(
        f"Não encontrei {symbol}_intraday ou {symbol}_full em {base}. Use --input."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera contexto intraday compacto por timeframe.")
    parser.add_argument("--input", type=Path, help="Consolidado intraday Parquet/CSV")
    parser.add_argument("--symbol", default="GOLD", help="Símbolo desejado")
    parser.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TFS))
    parser.add_argument("--output", type=Path, help="Arquivo JSON de saída")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--stdout", action="store_true", help="Também imprime o JSON")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    input_path = args.input or find_default_input(args.project_root, symbol)
    df = load_table(input_path)

    if "symbol" in df.columns:
        df = df[df["symbol"].astype(str).str.upper() == symbol]
    if df.empty:
        raise ValueError(f"Nenhuma linha encontrada para o símbolo {symbol}.")

    contexts: dict[str, dict[str, Any]] = {}
    available_tfs = set(df["timeframe"].astype(str)) if "timeframe" in df.columns else set()
    for tf in args.timeframes:
        if tf not in available_tfs:
            continue
        contexts[tf] = build_tf_context(tf, df[df["timeframe"].astype(str) == tf])

    if not contexts:
        raise ValueError(f"Nenhum timeframe solicitado foi encontrado. Disponíveis: {sorted(available_tfs)}")

    latest_price_ctx = contexts.get("M1") or contexts.get("M5") or next(iter(contexts.values()))
    payload = {
        "schema_version": "1.3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "source_file": str(input_path.resolve()),
        "current_price": latest_price_ctx["ohlc"]["close"],
        "market_summary": aggregate_market(contexts),
        "timeframes": contexts,
        "data_scope_note": (
            "Pressão e order flow são inferidos por OHLC, tick volume, spread e estrutura; "
            "não representam delta/footprint de bolsa."
        ),
    }

    output_path = args.output or (args.project_root / "data" / "context" / f"{symbol}_intraday_context.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Contexto salvo: {output_path}")
    print(f"Símbolo={symbol} | timeframes={list(contexts)} | ação={payload['market_summary']['immediate_action']}")
    if args.stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)
