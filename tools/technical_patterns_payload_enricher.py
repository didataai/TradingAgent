#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - Technical Patterns Payload Enricher
==================================================

Enriquece o payload intraday com uma leitura grafica estruturada:
triangulos, bandeiras, flamulas, canais, ranges, topo/fundo duplo,
falso rompimento, sweeps e candles relevantes.

A camada e CONTEXT_ONLY: nao decide BUY/SELL/WAIT e nao cria hard block.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TFS = ("H1", "M15", "M5", "M1")

CONTINUATION_PATTERNS = {
    "BULL_FLAG",
    "BEAR_FLAG",
    "BULLISH_PENNANT",
    "BEARISH_PENNANT",
    "ASCENDING_TRIANGLE",
    "DESCENDING_TRIANGLE",
    "SYMMETRICAL_TRIANGLE",
    "ASCENDING_CHANNEL",
    "DESCENDING_CHANNEL",
    "RANGE_RECTANGLE",
    "COMPRESSION",
}

REVERSAL_PATTERNS = {
    "DOUBLE_TOP",
    "DOUBLE_BOTTOM",
    "TRIPLE_TOP",
    "TRIPLE_BOTTOM",
    "HEAD_AND_SHOULDERS",
    "INVERTED_HEAD_AND_SHOULDERS",
    "RISING_WEDGE",
    "FALLING_WEDGE",
    "FALSE_BREAKOUT_UP",
    "FALSE_BREAKOUT_DOWN",
    "SWEEP_HIGH",
    "SWEEP_LOW",
}

BULLISH_CANDLES = {
    "Hammer",
    "Bullish_Engulfing",
    "Morning_Star",
    "Three_White_Soldiers",
    "Piercing_Line",
    "Tweezer_Bottoms",
}

BEARISH_CANDLES = {
    "Shooting_Star",
    "Hanging_Man",
    "Bearish_Engulfing",
    "Evening_Star",
    "Three_Black_Crows",
    "Dark_Cloud_Cover",
    "Tweezer_Tops",
}

NEUTRAL_CANDLES = {"Doji", "Inside_Bar", "Outside_Bar"}


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON deve conter objeto: {path}")
    return data


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def payload_path(symbol: str) -> Path:
    return ROOT / "data" / "payload" / f"{symbol}_intraday_payload.json"


def normalize_name(name: str) -> str:
    return str(name or "").strip().upper().replace(" ", "_").replace("-", "_")


def compact_level(value: Any) -> float | None:
    number = safe_float(value)
    return round(number, 5) if number is not None else None


def candle_direction_from_flags(pattern_flags: dict[str, Any]) -> tuple[str, list[str]]:
    active = [name for name, enabled in pattern_flags.items() if enabled is True]
    bullish = [name for name in active if name in BULLISH_CANDLES]
    bearish = [name for name in active if name in BEARISH_CANDLES]
    neutral = [name for name in active if name in NEUTRAL_CANDLES]

    if bullish and not bearish:
        return "BUY", bullish + neutral
    if bearish and not bullish:
        return "SELL", bearish + neutral
    if bullish and bearish:
        return "MIXED", bullish + bearish + neutral
    return "NEUTRAL", neutral or active


def event_patterns(event_flags: dict[str, Any]) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []

    mapping = [
        ("breakout_up", "BREAKOUT_UP", "CONTINUATION", "BUY"),
        ("breakout_down", "BREAKOUT_DOWN", "CONTINUATION", "SELL"),
        ("false_breakout_up", "FALSE_BREAKOUT_UP", "REVERSAL_OR_TRAP", "SELL"),
        ("false_breakout_down", "FALSE_BREAKOUT_DOWN", "REVERSAL_OR_TRAP", "BUY"),
        ("sweep_high", "SWEEP_HIGH", "LIQUIDITY_SWEEP", "SELL"),
        ("sweep_low", "SWEEP_LOW", "LIQUIDITY_SWEEP", "BUY"),
        ("bos_up", "BOS_UP", "STRUCTURE_BREAK", "BUY"),
        ("bos_dn", "BOS_DOWN", "STRUCTURE_BREAK", "SELL"),
        ("choch_up", "CHOCH_UP", "POTENTIAL_REVERSAL", "BUY"),
        ("choch_dn", "CHOCH_DOWN", "POTENTIAL_REVERSAL", "SELL"),
        ("fvg_up", "FVG_UP", "IMBALANCE", "BUY"),
        ("fvg_dn", "FVG_DOWN", "IMBALANCE", "SELL"),
        ("compression_flag", "COMPRESSION", "CONTINUATION_OR_BREAKOUT", "NEUTRAL"),
        ("inside_previous_range", "INSIDE_RANGE", "CONSOLIDATION", "NEUTRAL"),
    ]
    for key, name, family, bias in mapping:
        if event_flags.get(key) is True:
            patterns.append({"name": name, "family": family, "bias": bias, "status": "DETECTED"})
    return patterns


def classify_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    raw_name = str(candidate.get("name") or "UNKNOWN")
    name = normalize_name(raw_name)
    score = safe_float(candidate.get("algorithmic_score"), 0.0) or 0.0
    status = str(candidate.get("status") or "CANDIDATE").upper()

    family = "UNKNOWN"
    bias = "NEUTRAL"
    trigger = None
    invalidation = None

    if name in {"BULL_FLAG", "BULLISH_PENNANT"}:
        family, bias = "CONTINUATION", "BUY"
        trigger = "break_and_accept_above_flag_or_pennant_resistance"
        invalidation = "loss_of_flag_or_pennant_base"
    elif name in {"BEAR_FLAG", "BEARISH_PENNANT"}:
        family, bias = "CONTINUATION", "SELL"
        trigger = "break_and_accept_below_flag_or_pennant_support"
        invalidation = "reclaim_above_flag_or_pennant_top"
    elif name == "ASCENDING_TRIANGLE":
        family, bias = "CONTINUATION_OR_BREAKOUT", "BUY"
        trigger = "break_and_accept_above_horizontal_resistance"
        invalidation = "loss_of_ascending_lows"
    elif name == "DESCENDING_TRIANGLE":
        family, bias = "CONTINUATION_OR_BREAKOUT", "SELL"
        trigger = "break_and_accept_below_horizontal_support"
        invalidation = "reclaim_above_descending_highs"
    elif name == "SYMMETRICAL_TRIANGLE":
        family, bias = "COMPRESSION", "NEUTRAL"
        trigger = "wait_for_breakout_and_acceptance"
        invalidation = "opposite_side_breakout"
    elif name == "DESCENDING_CHANNEL":
        family, bias = "TREND_CHANNEL", "SELL"
        trigger = "sell_rejection_at_channel_top_or_break_channel_low"
        invalidation = "acceptance_above_channel_top"
    elif name == "ASCENDING_CHANNEL":
        family, bias = "TREND_CHANNEL", "BUY"
        trigger = "buy_rejection_at_channel_base_or_break_channel_top"
        invalidation = "acceptance_below_channel_base"
    elif name == "DOUBLE_TOP":
        family, bias = "REVERSAL", "SELL"
        trigger = "break_below_neckline"
        invalidation = "acceptance_above_second_top"
    elif name == "DOUBLE_BOTTOM":
        family, bias = "REVERSAL", "BUY"
        trigger = "break_above_neckline"
        invalidation = "loss_of_second_bottom"
    elif name in CONTINUATION_PATTERNS:
        family = "CONTINUATION"
    elif name in REVERSAL_PATTERNS:
        family = "REVERSAL"

    quality = "LOW"
    if score >= 0.80:
        quality = "HIGH"
    elif score >= 0.60:
        quality = "MEDIUM"

    levels = {}
    for key in (
        "breakout_level",
        "invalidation_level",
        "upper_breakout_reference",
        "lower_breakout_reference",
        "upper_reference",
        "lower_reference",
        "neckline_reference",
    ):
        if key in candidate:
            levels[key] = compact_level(candidate.get(key))

    return {
        "name": name,
        "family": family,
        "bias": bias,
        "status": status,
        "quality": quality,
        "score": round(score, 3),
        "trigger": trigger,
        "invalidation": invalidation,
        "levels": levels,
    }


def infer_pennant_from_geometry(tf_data: dict[str, Any]) -> list[dict[str, Any]]:
    geometry = tf_data.get("pattern_geometry", {}) or {}
    impulse = geometry.get("impulse_and_consolidation", {}) or {}
    trendline = geometry.get("trendline_geometry", {}) or {}

    impulse_dir = str(impulse.get("impulse_direction_from_ohlc") or "").upper()
    impulse_atr = abs(safe_float(impulse.get("impulse_move_atr"), 0.0) or 0.0)
    consolidation_bars = int(safe_float(impulse.get("consolidation_bars"), 0) or 0)
    width_atr = safe_float(impulse.get("consolidation_width_atr"), None)
    compression_ratio = safe_float(trendline.get("range_compression_ratio_second_half_vs_first_half"), None)

    out: list[dict[str, Any]] = []
    if impulse_atr < 0.80 or consolidation_bars < 3:
        return out
    if width_atr is not None and width_atr > 2.50:
        return out
    if compression_ratio is not None and compression_ratio > 1.15:
        return out

    if impulse_dir == "UP":
        out.append({
            "name": "BULLISH_PENNANT",
            "family": "CONTINUATION",
            "bias": "BUY",
            "status": "INFERRED_FORMING",
            "quality": "MEDIUM" if impulse_atr >= 1.20 else "LOW",
            "score": round(min(1.0, impulse_atr / 2.0), 3),
            "trigger": "break_and_accept_above_pennant_resistance",
            "invalidation": "loss_of_pennant_base",
            "levels": {
                "upper_breakout_reference": compact_level(impulse.get("upper_breakout_reference")),
                "lower_breakout_reference": compact_level(impulse.get("lower_breakout_reference")),
            },
        })
    elif impulse_dir == "DOWN":
        out.append({
            "name": "BEARISH_PENNANT",
            "family": "CONTINUATION",
            "bias": "SELL",
            "status": "INFERRED_FORMING",
            "quality": "MEDIUM" if impulse_atr >= 1.20 else "LOW",
            "score": round(min(1.0, impulse_atr / 2.0), 3),
            "trigger": "break_and_accept_below_pennant_support",
            "invalidation": "reclaim_above_pennant_top",
            "levels": {
                "upper_breakout_reference": compact_level(impulse.get("upper_breakout_reference")),
                "lower_breakout_reference": compact_level(impulse.get("lower_breakout_reference")),
            },
        })
    return out


def recent_event_bias(tf_data: dict[str, Any]) -> tuple[str, list[str]]:
    recent = tf_data.get("recent_bars", []) or []
    events: list[str] = []
    buy_score = 0
    sell_score = 0

    for bar in recent[-3:]:
        for event in bar.get("algorithmic_events", []) or []:
            event_name = normalize_name(event)
            events.append(event_name)
            if event_name in {"FALSE_BREAKOUT_DOWN", "SWEEP_LOW", "CHOCH_UP", "BOS_UP", "BREAKOUT_UP"}:
                buy_score += 1
            elif event_name in {"FALSE_BREAKOUT_UP", "SWEEP_HIGH", "CHOCH_DOWN", "BOS_DOWN", "BREAKOUT_DOWN"}:
                sell_score += 1

    if buy_score > sell_score:
        return "BUY", events[-8:]
    if sell_score > buy_score:
        return "SELL", events[-8:]
    return "NEUTRAL", events[-8:]


def aggregate_bias(items: list[dict[str, Any]]) -> str:
    buy = sum(1 for item in items if item.get("bias") == "BUY")
    sell = sum(1 for item in items if item.get("bias") == "SELL")
    if buy > sell and buy >= 1:
        return "BUY"
    if sell > buy and sell >= 1:
        return "SELL"
    if buy and sell:
        return "MIXED"
    return "NEUTRAL"


def summarize_tf(tf: str, tf_data: dict[str, Any]) -> dict[str, Any]:
    annotations = tf_data.get("algorithmic_annotations", {}) or {}
    event_flags = annotations.get("event_flags", {}) or {}
    pattern_flags = annotations.get("pattern_flags", {}) or {}
    geometry = tf_data.get("pattern_geometry", {}) or {}

    candidates = [classify_candidate(item) for item in geometry.get("pattern_candidates", []) or []]
    candidates.extend(infer_pennant_from_geometry(tf_data))
    events = event_patterns(event_flags)
    candle_bias, candles = candle_direction_from_flags(pattern_flags)
    recent_bias, recent_events = recent_event_bias(tf_data)

    all_items = candidates + events
    pattern_bias = aggregate_bias(all_items)
    if pattern_bias == "NEUTRAL" and candle_bias in {"BUY", "SELL", "MIXED"}:
        pattern_bias = candle_bias
    if pattern_bias == "NEUTRAL" and recent_bias in {"BUY", "SELL"}:
        pattern_bias = recent_bias

    main = None
    if candidates:
        main = sorted(candidates, key=lambda x: (x.get("quality") == "HIGH", x.get("score") or 0), reverse=True)[0]
    elif events:
        main = events[0]
    elif candles:
        main = {"name": candles[0], "family": "CANDLE", "bias": candle_bias, "status": "DETECTED"}

    entry_relevance = "LOW"
    if tf in {"M15", "M5"} and main:
        entry_relevance = "HIGH"
    elif tf in {"H1", "M1"} and main:
        entry_relevance = "MEDIUM"

    return {
        "timeframe": tf,
        "main_pattern": main,
        "pattern_bias": pattern_bias,
        "entry_relevance": entry_relevance,
        "chart_patterns": candidates[:5],
        "event_patterns": events[:8],
        "candlestick_patterns": candles[:8],
        "recent_event_bias": recent_bias,
        "recent_events": recent_events,
        "semantics": "CONTEXT_ONLY",
    }


def build_summary(tf_contexts: dict[str, Any]) -> str:
    parts = []
    for tf in ("M15", "M5", "M1", "H1"):
        item = tf_contexts.get(tf)
        if not item:
            continue
        main = item.get("main_pattern") or {}
        name = main.get("name")
        bias = item.get("pattern_bias")
        if name:
            parts.append(f"{tf}: {name} ({bias})")
    if not parts:
        return "Nenhum padrao grafico relevante detectado; usar suporte/resistencia, candle fechado e gatilho operacional."
    return " | ".join(parts)


def enrich_payload(payload: dict[str, Any]) -> dict[str, Any]:
    timeframes = payload.get("timeframes", {}) or {}
    tf_contexts: dict[str, Any] = {}
    for tf in DEFAULT_TFS:
        tf_data = timeframes.get(tf)
        if isinstance(tf_data, dict):
            tf_contexts[tf] = summarize_tf(tf, tf_data)

    context = {
        "available": bool(tf_contexts),
        "decision_semantics": "CONTEXT_ONLY",
        "priority_rule": "Patterns explain setup, trigger and invalidation; they do not override Historical Intelligence or hard blocks.",
        "timeframe_role": {
            "M15": "setup_pattern",
            "M5": "operational_confirmation",
            "M1": "fine_timing",
            "H1": "tactical_context",
        },
        "timeframes": tf_contexts,
        "summary": build_summary(tf_contexts),
    }
    out = dict(payload)
    out["technical_patterns_context"] = context
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enriquece payload com technical_patterns_context.")
    parser.add_argument("--symbol", default="GOLD", help="Simbolo. Padrao: GOLD.")
    parser.add_argument("--payload", help="Payload de entrada/saida. Padrao: data/payload/<SYMBOL>_intraday_payload.json.")
    parser.add_argument("--output", help="Arquivo de saida. Padrao: sobrescreve --payload.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbol = args.symbol.upper().strip()
    source = Path(args.payload) if args.payload else payload_path(symbol)
    if not source.is_absolute():
        source = ROOT / source
    output = Path(args.output) if args.output else source
    if not output.is_absolute():
        output = ROOT / output

    try:
        payload = read_json(source)
        enriched = enrich_payload(payload)
        write_json_atomic(output, enriched)
        ctx = enriched.get("technical_patterns_context", {})
        print(
            f"[OK] Technical Patterns aplicado como CONTEXT_ONLY | "
            f"symbol={symbol} | summary={ctx.get('summary')}"
        )
        return 0
    except Exception as exc:
        print(f"[ERRO] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
