#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - Technical Patterns Payload Enricher
==================================================

Enriquece o payload intraday com uma leitura grafica estruturada:
triangulos, bandeiras, flamulas, canais, ranges, topo/fundo duplo,
falso rompimento, sweeps, BOS/CHOCH, FVG e candles relevantes.

A camada e CONTEXT_ONLY: nao decide BUY/SELL/WAIT, nao cria hard block
e nao sobrescreve Historical Intelligence. Padroes em formacao servem
para leitura de possivel consolidacao, compressao ou preparacao de setup.
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

FORMATION_STATUSES = {
    "FORMING",
    "FORMING_OR_TESTING",
    "INFERRED_FORMING",
    "CANDIDATE",
    "CANDIDATE_NOT_CONFIRMED",
    "ACTIVE_CANDIDATE",
}

CONFIRMED_STATUSES = {
    "CONFIRMED",
    "BREAKOUT_CONFIRMED",
    "DETECTED_CONFIRMED",
}


PATTERN_RULES: dict[str, dict[str, Any]] = {
    "BULL_FLAG": {
        "family": "CONTINUATION",
        "directional_intent": "BUY",
        "trigger": "break_and_accept_above_flag_resistance",
        "invalidation": "loss_of_flag_base",
        "formation_read": "Bull flag em formacao: pullback/canal curto contra impulso de alta; aguardar rompimento ou reteste.",
    },
    "BEAR_FLAG": {
        "family": "CONTINUATION",
        "directional_intent": "SELL",
        "trigger": "break_and_accept_below_flag_support",
        "invalidation": "reclaim_above_flag_top",
        "formation_read": "Bear flag em formacao: pullback/canal curto contra impulso de queda; aguardar perda da base ou rejeicao.",
    },
    "BULLISH_PENNANT": {
        "family": "CONTINUATION",
        "directional_intent": "BUY",
        "trigger": "break_and_accept_above_pennant_resistance",
        "invalidation": "loss_of_pennant_base",
        "formation_read": "Flamula altista em formacao: triangulo curto apos impulso de alta; aguardar rompimento.",
    },
    "BEARISH_PENNANT": {
        "family": "CONTINUATION",
        "directional_intent": "SELL",
        "trigger": "break_and_accept_below_pennant_support",
        "invalidation": "reclaim_above_pennant_top",
        "formation_read": "Flamula baixista em formacao: triangulo curto apos impulso de queda; aguardar rompimento.",
    },
    "ASCENDING_TRIANGLE": {
        "family": "CONTINUATION_OR_BREAKOUT",
        "directional_intent": "BUY",
        "trigger": "break_and_accept_above_horizontal_resistance",
        "invalidation": "loss_of_ascending_lows",
        "formation_read": "Triangulo ascendente em formacao: fundos ascendentes pressionam resistencia; ainda e compressao ate romper.",
    },
    "DESCENDING_TRIANGLE": {
        "family": "CONTINUATION_OR_BREAKOUT",
        "directional_intent": "SELL",
        "trigger": "break_and_accept_below_horizontal_support",
        "invalidation": "reclaim_above_descending_highs",
        "formation_read": "Triangulo descendente em formacao: topos descendentes pressionam suporte; ainda e compressao ate romper.",
    },
    "SYMMETRICAL_TRIANGLE": {
        "family": "COMPRESSION",
        "directional_intent": "NEUTRAL",
        "trigger": "wait_for_breakout_and_acceptance",
        "invalidation": "opposite_side_breakout_after_acceptance",
        "formation_read": "Triangulo simetrico: compressao sem lado definido; aguardar rompimento e aceitacao.",
    },
    "ASCENDING_CHANNEL": {
        "family": "TREND_CHANNEL",
        "directional_intent": "BUY",
        "trigger": "buy_rejection_at_channel_base_or_break_channel_top",
        "invalidation": "acceptance_below_channel_base",
        "formation_read": "Canal ascendente: estrutura de alta, mas entrada depende de base/topo e candle fechado.",
    },
    "DESCENDING_CHANNEL": {
        "family": "TREND_CHANNEL",
        "directional_intent": "SELL",
        "trigger": "sell_rejection_at_channel_top_or_break_channel_low",
        "invalidation": "acceptance_above_channel_top",
        "formation_read": "Canal descendente: estrutura de queda, mas entrada depende de topo/base e candle fechado.",
    },
    "DOUBLE_TOP": {
        "family": "REVERSAL",
        "directional_intent": "SELL",
        "trigger": "break_below_neckline",
        "invalidation": "acceptance_above_second_top",
        "formation_read": "Topo duplo candidato: possivel reversao vendedora, mas so confirma abaixo da neckline.",
    },
    "DOUBLE_BOTTOM": {
        "family": "REVERSAL",
        "directional_intent": "BUY",
        "trigger": "break_above_neckline",
        "invalidation": "loss_of_second_bottom",
        "formation_read": "Fundo duplo candidato: possivel reversao compradora, mas so confirma acima da neckline.",
    },
    "RANGE_RECTANGLE": {
        "family": "CONSOLIDATION",
        "directional_intent": "NEUTRAL",
        "trigger": "wait_for_range_breakout_or_rejection_at_extremes",
        "invalidation": "none_until_breakout_acceptance",
        "formation_read": "Range/retangulo: consolidacao; operar extremos ou aguardar rompimento aceito.",
    },
    "COMPRESSION": {
        "family": "CONSOLIDATION",
        "directional_intent": "NEUTRAL",
        "trigger": "wait_for_expansion_breakout",
        "invalidation": "false_breakout_return_to_range",
        "formation_read": "Compressao: mercado preparando expansao; lado ainda indefinido.",
    },
}

EVENT_RULES = [
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
    ("compression_flag", "COMPRESSION", "CONSOLIDATION", "NEUTRAL"),
    ("inside_previous_range", "INSIDE_RANGE", "CONSOLIDATION", "NEUTRAL"),
]


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


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


def normalize_name(name: Any) -> str:
    return str(name or "").strip().upper().replace(" ", "_").replace("-", "_")


def compact_level(value: Any) -> float | None:
    number = safe_float(value)
    return round(number, 5) if number is not None else None


def quality_from_score(score: float) -> str:
    if score >= 0.80:
        return "HIGH"
    if score >= 0.60:
        return "MEDIUM"
    return "LOW"


def stage_from_status(status: str) -> str:
    normalized = normalize_name(status)
    if normalized in CONFIRMED_STATUSES:
        return "CONFIRMED"
    if normalized in FORMATION_STATUSES or "FORM" in normalized or "CANDIDATE" in normalized:
        return "FORMING"
    if "TEST" in normalized:
        return "FORMING"
    return "DETECTED"


def operational_bias_from_stage(name: str, directional_intent: str, stage: str) -> str:
    """Bias usado no resumo operacional. Candidato/formacao fica mais conservador."""
    if directional_intent == "NEUTRAL":
        return "NEUTRAL"
    if stage == "CONFIRMED":
        return directional_intent
    if name in {"DOUBLE_TOP", "DOUBLE_BOTTOM", "HEAD_AND_SHOULDERS", "INVERTED_HEAD_AND_SHOULDERS"}:
        return "MIXED"
    if name in {"ASCENDING_TRIANGLE", "DESCENDING_TRIANGLE", "SYMMETRICAL_TRIANGLE", "BULLISH_PENNANT", "BEARISH_PENNANT"}:
        return "MIXED"
    return directional_intent


def formation_label(name: str, family: str, stage: str) -> str:
    if stage == "CONFIRMED":
        return "CONFIRMED_PATTERN"
    if family in {"COMPRESSION", "CONSOLIDATION"} or "TRIANGLE" in name or "PENNANT" in name:
        return "FORMATION_OR_CONSOLIDATION"
    if family == "REVERSAL":
        return "REVERSAL_CANDIDATE"
    if family == "CONTINUATION":
        return "CONTINUATION_CANDIDATE"
    return "CONTEXT_CANDIDATE"


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
    for key, name, family, bias in EVENT_RULES:
        if event_flags.get(key) is True:
            patterns.append(
                {
                    "name": name,
                    "family": family,
                    "directional_intent": bias,
                    "bias": bias,
                    "stage": "DETECTED",
                    "status": "DETECTED",
                    "formation_label": "EVENT_DETECTED",
                    "trigger": None,
                    "invalidation": None,
                    "formation_read": "Evento detectado no candle atual/recente; usar apenas como contexto.",
                }
            )
    return patterns


def classify_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    raw_name = str(candidate.get("name") or "UNKNOWN")
    name = normalize_name(raw_name)
    score = safe_float(candidate.get("algorithmic_score"), 0.0) or 0.0
    status = str(candidate.get("status") or "CANDIDATE").upper()
    stage = stage_from_status(status)

    rule = PATTERN_RULES.get(name, {})
    family = rule.get("family", "UNKNOWN")
    directional_intent = rule.get("directional_intent", "NEUTRAL")
    trigger = rule.get("trigger")
    invalidation = rule.get("invalidation")
    formation_read = rule.get("formation_read", "Candidato grafico detectado; usar apenas como contexto ate confirmacao.")
    bias = operational_bias_from_stage(name, directional_intent, stage)

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
        "directional_intent": directional_intent,
        "bias": bias,
        "stage": stage,
        "status": status,
        "formation_label": formation_label(name, family, stage),
        "quality": quality_from_score(score),
        "score": round(score, 3),
        "trigger": trigger,
        "invalidation": invalidation,
        "levels": levels,
        "confirmation_required": stage != "CONFIRMED",
        "formation_read": formation_read,
        "semantics": "CONTEXT_ONLY",
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

    if impulse_atr < 0.80 or consolidation_bars < 3:
        return []
    if width_atr is not None and width_atr > 2.50:
        return []
    if compression_ratio is not None and compression_ratio > 1.15:
        return []

    name = "BULLISH_PENNANT" if impulse_dir == "UP" else "BEARISH_PENNANT" if impulse_dir == "DOWN" else None
    if not name:
        return []

    rule = PATTERN_RULES[name]
    score = round(min(1.0, impulse_atr / 2.0), 3)
    return [
        {
            "name": name,
            "family": rule["family"],
            "directional_intent": rule["directional_intent"],
            "bias": "MIXED",
            "stage": "FORMING",
            "status": "INFERRED_FORMING",
            "formation_label": "FORMATION_OR_CONSOLIDATION",
            "quality": "MEDIUM" if impulse_atr >= 1.20 else "LOW",
            "score": score,
            "trigger": rule["trigger"],
            "invalidation": rule["invalidation"],
            "levels": {
                "upper_breakout_reference": compact_level(impulse.get("upper_breakout_reference")),
                "lower_breakout_reference": compact_level(impulse.get("lower_breakout_reference")),
            },
            "confirmation_required": True,
            "formation_read": rule["formation_read"],
            "semantics": "CONTEXT_ONLY",
        }
    ]


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
    directional = [item.get("bias") for item in items if item.get("bias") in {"BUY", "SELL", "MIXED"}]
    if any(bias == "MIXED" for bias in directional):
        return "MIXED"
    buy = sum(1 for bias in directional if bias == "BUY")
    sell = sum(1 for bias in directional if bias == "SELL")
    if buy and sell:
        return "MIXED"
    if buy:
        return "BUY"
    if sell:
        return "SELL"
    return "NEUTRAL"


def choose_main_pattern(candidates: list[dict[str, Any]], events: list[dict[str, Any]], candles: list[str], candle_bias: str) -> dict[str, Any] | None:
    if candidates:
        priority = {"CONFIRMED": 3, "FORMING": 2, "DETECTED": 1}
        return sorted(
            candidates,
            key=lambda item: (
                priority.get(str(item.get("stage")), 0),
                item.get("quality") == "HIGH",
                item.get("score") or 0,
            ),
            reverse=True,
        )[0]
    if events:
        return events[0]
    if candles:
        return {
            "name": candles[0],
            "family": "CANDLE",
            "directional_intent": candle_bias,
            "bias": candle_bias,
            "stage": "DETECTED",
            "status": "DETECTED",
            "formation_label": "CANDLE_CONTEXT",
            "confirmation_required": True,
            "semantics": "CONTEXT_ONLY",
        }
    return None


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

    main = choose_main_pattern(candidates, events, candles, candle_bias)
    main_stage = str((main or {}).get("stage") or "NONE")

    entry_relevance = "LOW"
    if tf in {"M15", "M5"} and main:
        entry_relevance = "HIGH"
    elif tf in {"H1", "M1"} and main:
        entry_relevance = "MEDIUM"

    formation_status = "NONE"
    if main:
        if main_stage == "CONFIRMED":
            formation_status = "CONFIRMED"
        elif str(main.get("formation_label")) in {"FORMATION_OR_CONSOLIDATION", "CONTINUATION_CANDIDATE", "REVERSAL_CANDIDATE"}:
            formation_status = str(main.get("formation_label"))
        else:
            formation_status = "CONTEXT_DETECTED"

    operational_read = "Sem padrao grafico relevante; usar suporte/resistencia e candle fechado."
    if main:
        name = main.get("name")
        trigger = main.get("trigger")
        invalidation = main.get("invalidation")
        formation_read = main.get("formation_read") or "Padrao detectado como contexto."
        operational_read = f"{name}: {formation_read}"
        if trigger:
            operational_read += f" Trigger: {trigger}."
        if invalidation:
            operational_read += f" Invalidacao: {invalidation}."

    return {
        "timeframe": tf,
        "main_pattern": main,
        "pattern_bias": pattern_bias,
        "formation_status": formation_status,
        "entry_relevance": entry_relevance,
        "chart_patterns": candidates[:6],
        "event_patterns": events[:8],
        "candlestick_patterns": candles[:8],
        "recent_event_bias": recent_bias,
        "recent_events": recent_events,
        "operational_read": operational_read,
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
        formation = item.get("formation_status")
        if name:
            parts.append(f"{tf}: {name} ({formation}/{bias})")
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
        "priority_rule": "Patterns explain setup, consolidation, trigger and invalidation; they do not override Historical Intelligence or hard blocks.",
        "formation_rule": "Patterns in FORMING/CANDIDATE_NOT_CONFIRMED stage indicate possible consolidation or setup preparation; do not treat them as confirmed direction.",
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
