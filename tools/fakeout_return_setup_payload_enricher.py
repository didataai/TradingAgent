#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - Fakeout Return Setup Payload Enricher
=====================================================

Objetivo
--------
Adicionar ao payload uma leitura operacional conservadora para o setup de
retorno apos falso rompimento de formacao/padrao grafico.

Motivacao
---------
O estudo `pattern_attempt_research.py` mostrou alta taxa de fakeout em
rompimentos de formacoes. Portanto, em vez de perseguir o primeiro rompimento,
o sistema deve observar quando o preco rompe, falha, volta para dentro da
formacao e oferece uma oportunidade de retorno/fade.

Semantica
---------
Esta camada e CONTEXT_ONLY / WARNING_ONLY:
- nao decide BUY/SELL/WAIT;
- nao sobrescreve Historical Intelligence;
- nao cria hard block;
- nao autoriza trade contra Chronos, Personal Guard ou regra M5;
- nao transforma qualquer falso rompimento em entrada automatica.

Estados do setup
----------------
NO_SETUP
    Nao existe contexto suficiente de fakeout/retorno.

WATCHING_FAKEOUT
    Ha padrao/formacao e risco estatistico alto de fakeout. O sistema deve
    evitar chase e observar uma possivel falha do rompimento.

RETURN_INSIDE_PENDING
    Ha falso rompimento/sweep ou leitura de retorno, mas ainda falta evidencia
    clara de aceitacao de volta para dentro da formacao.

FAKEOUT_RETURN_CONFIRMATION_PENDING
    O setup de retorno esta em observacao avancada: ha risco alto de fakeout,
    tentativa inicial e eventos de falso rompimento/retorno. Ainda exige candle
    fechado, M5 permitindo e gatilho M1.

Uso operacional
---------------
Quando este contexto estiver ativo, a LLM deve preferir frases como:
- "Nao perseguir rompimento; observar retorno para dentro da formacao."
- "Setup de retorno do fakeout em observacao; aguardar M5/M1 confirmar."
- "Stop tecnico ficaria alem da maxima/minima do falso rompimento."

Compatibilidade
---------------
- Python padrao + pathlib/json/os/argparse.
- Compatível com Windows e Linux.
- Escrita atomica de JSON.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TFS = ("M15", "M5", "M1", "H1")

HIGH_FAKEOUT_CLASSES = {"HIGH_FAKEOUT_RISK", "VERY_HIGH_FAKEOUT_RISK", "ELEVATED_FAKEOUT_RISK"}
AVOID_CHASE_INTERPRETATIONS = {
    "AVOID_CHASE",
    "WAIT_RETEST_OR_CONFIRMATION",
    "FADE_FIRST_BREAKOUT_OR_WAIT_RETEST",
    "WAIT_CONFIRMATION",
}


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


def normalize(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "_").replace("-", "_")


def compact_level(value: Any) -> float | None:
    number = safe_float(value)
    return round(number, 5) if number is not None else None


def get_tf_data(payload: dict[str, Any], tf: str) -> dict[str, Any]:
    data = payload.get("timeframes", {}).get(tf, {})
    return data if isinstance(data, dict) else {}


def get_event_flags(tf_data: dict[str, Any]) -> dict[str, Any]:
    annotations = tf_data.get("algorithmic_annotations", {}) or {}
    flags = annotations.get("event_flags", {}) or {}
    return flags if isinstance(flags, dict) else {}


def get_recent_events(tf_data: dict[str, Any], lookback: int = 4) -> list[str]:
    events: list[str] = []
    for bar in (tf_data.get("recent_bars", []) or [])[-lookback:]:
        for event in bar.get("algorithmic_events", []) or []:
            events.append(normalize(event))
    return events[-12:]


def current_price(tf_data: dict[str, Any], payload: dict[str, Any]) -> float | None:
    bar = tf_data.get("current_bar", {}) or {}
    for key in ("close", "last", "price"):
        value = safe_float(bar.get(key))
        if value is not None:
            return value
    return safe_float(payload.get("current_price"))


def formation_bounds(tf_patterns: dict[str, Any]) -> tuple[float | None, float | None]:
    attempt = tf_patterns.get("breakout_attempt_context", {}) or {}
    upper = compact_level(attempt.get("upper_boundary"))
    lower = compact_level(attempt.get("lower_boundary"))
    if upper is not None or lower is not None:
        return upper, lower

    main = tf_patterns.get("main_pattern", {}) or {}
    levels = main.get("levels", {}) or {}
    upper = compact_level(
        levels.get("upper_breakout_reference")
        or levels.get("upper_reference")
        or levels.get("breakout_level")
    )
    lower = compact_level(
        levels.get("lower_breakout_reference")
        or levels.get("lower_reference")
        or levels.get("invalidation_level")
        or levels.get("neckline_reference")
    )
    return upper, lower


def infer_fakeout_side(event_flags: dict[str, Any], recent_events: list[str]) -> str | None:
    if event_flags.get("false_breakout_up") is True or "FALSE_BREAKOUT_UP" in recent_events or "SWEEP_HIGH" in recent_events:
        return "UP"
    if event_flags.get("false_breakout_down") is True or "FALSE_BREAKOUT_DOWN" in recent_events or "SWEEP_LOW" in recent_events:
        return "DOWN"
    return None


def side_if_confirmed(fakeout_side: str | None) -> str:
    if fakeout_side == "UP":
        return "SELL"
    if fakeout_side == "DOWN":
        return "BUY"
    return "NONE"


def stop_reference(fakeout_side: str | None, tf_data: dict[str, Any], upper: float | None, lower: float | None) -> float | None:
    bar = tf_data.get("current_bar", {}) or {}
    if fakeout_side == "UP":
        return compact_level(bar.get("high") or upper)
    if fakeout_side == "DOWN":
        return compact_level(bar.get("low") or lower)
    return None


def target_references(fakeout_side: str | None, upper: float | None, lower: float | None) -> dict[str, float | None]:
    middle = None
    if upper is not None and lower is not None:
        middle = round((upper + lower) / 2.0, 5)
    if fakeout_side == "UP":
        return {"target_1_mid_formation": middle, "target_2_opposite_boundary": lower}
    if fakeout_side == "DOWN":
        return {"target_1_mid_formation": middle, "target_2_opposite_boundary": upper}
    return {"target_1_mid_formation": middle, "target_2_opposite_boundary": None}


def is_inside_formation(price: float | None, upper: float | None, lower: float | None) -> bool | None:
    if price is None or upper is None or lower is None:
        return None
    hi = max(upper, lower)
    lo = min(upper, lower)
    return lo <= price <= hi


def classify_state(
    *,
    has_pattern: bool,
    high_fakeout: bool,
    attempt_number: int | None,
    fakeout_side: str | None,
    inside: bool | None,
    current_flags: dict[str, Any],
    recent_events: list[str],
) -> str:
    if not has_pattern or not high_fakeout:
        return "NO_SETUP"

    early_attempt = attempt_number in {1, 2, None}
    has_return_event = (
        current_flags.get("inside_previous_range") is True
        or "INSIDE_RANGE" in recent_events
        or "INSIDE_RANGE_LOW_PARTICIPATION" in recent_events
    )

    if fakeout_side and inside is True and early_attempt:
        return "FAKEOUT_RETURN_CONFIRMATION_PENDING"
    if fakeout_side and (inside is None or inside is False or has_return_event):
        return "RETURN_INSIDE_PENDING"
    return "WATCHING_FAKEOUT"


def build_requirements(state: str, side: str) -> list[str]:
    base = [
        "M5_close_back_inside_or_reject_breakout_boundary",
        "M1_closed_candle_trigger_in_return_direction",
        "avoid_market_chase",
        "respect_Historical_Chronos_Personal_Guard_and_Diego_M5_rule",
    ]
    if side == "BUY":
        base.append("M1_green_close_and_break_previous_high")
    elif side == "SELL":
        base.append("M1_red_close_and_break_previous_low")
    if state == "WATCHING_FAKEOUT":
        return ["wait_for_failed_breakout_or_return_inside", *base]
    if state == "RETURN_INSIDE_PENDING":
        return ["wait_for_price_to_return_and_accept_inside_formation", *base]
    if state == "FAKEOUT_RETURN_CONFIRMATION_PENDING":
        return ["confirm_return_inside_with_closed_candle", *base]
    return []


def build_read(state: str, tf: str, pattern: str, fakeout_side: str | None, side: str) -> str:
    if state == "NO_SETUP":
        return f"{tf}: sem setup de retorno do fakeout suficiente."
    if state == "WATCHING_FAKEOUT":
        return f"{tf}: {pattern} com risco alto de fakeout; nao perseguir rompimento, observar falha e retorno para dentro."
    if state == "RETURN_INSIDE_PENDING":
        return f"{tf}: falso rompimento {fakeout_side or 'indefinido'} em observacao; aguardar retorno aceito para dentro da formacao."
    if state == "FAKEOUT_RETURN_CONFIRMATION_PENDING":
        return f"{tf}: setup de retorno do fakeout em observacao avancada; lado se confirmar={side}, ainda exige M5/M1 e candle fechado."
    return f"{tf}: contexto de fakeout indefinido."


def summarize_tf(tf: str, payload: dict[str, Any]) -> dict[str, Any]:
    tech_ctx = payload.get("technical_patterns_context", {}) or {}
    edge_ctx = payload.get("pattern_attempt_edge_context", {}) or {}
    tf_patterns = (tech_ctx.get("timeframes", {}) or {}).get(tf, {}) or {}
    tf_edge = (edge_ctx.get("timeframes", {}) or {}).get(tf, {}) or {}
    tf_data = get_tf_data(payload, tf)

    main = tf_patterns.get("main_pattern", {}) or {}
    pattern_name = normalize(main.get("name") or tf_edge.get("pattern_name") or "UNKNOWN")
    has_pattern = pattern_name not in {"", "UNKNOWN", "NONE"}
    attempt_number = tf_edge.get("attempt_number")
    try:
        attempt_number_int = int(attempt_number) if attempt_number is not None else None
    except (TypeError, ValueError):
        attempt_number_int = None

    edge_class = normalize(tf_edge.get("edge_classification"))
    preferred = normalize(tf_edge.get("preferred_interpretation"))
    high_fakeout = edge_class in HIGH_FAKEOUT_CLASSES or preferred in AVOID_CHASE_INTERPRETATIONS

    upper, lower = formation_bounds(tf_patterns)
    price = current_price(tf_data, payload)
    inside = is_inside_formation(price, upper, lower)
    event_flags = get_event_flags(tf_data)
    recent_events = get_recent_events(tf_data)
    fakeout_side = infer_fakeout_side(event_flags, recent_events)
    side = side_if_confirmed(fakeout_side)

    state = classify_state(
        has_pattern=has_pattern,
        high_fakeout=high_fakeout,
        attempt_number=attempt_number_int,
        fakeout_side=fakeout_side,
        inside=inside,
        current_flags=event_flags,
        recent_events=recent_events,
    )

    stop = stop_reference(fakeout_side, tf_data, upper, lower)
    targets = target_references(fakeout_side, upper, lower)
    requirements = build_requirements(state, side)
    read = build_read(state, tf, pattern_name, fakeout_side, side)

    return {
        "timeframe": tf,
        "available": state != "NO_SETUP",
        "setup_name": "FAKEOUT_RETURN_SETUP",
        "setup_state": state,
        "pattern_name": pattern_name,
        "attempt_number": attempt_number_int,
        "edge_classification": edge_class or None,
        "edge_preferred_interpretation": preferred or None,
        "fakeout_side": fakeout_side,
        "side_if_confirmed": side,
        "current_price": compact_level(price),
        "upper_boundary": upper,
        "lower_boundary": lower,
        "inside_formation_now": inside,
        "stop_reference_if_confirmed": stop,
        "target_references_if_confirmed": targets,
        "requirements": requirements,
        "recent_events": recent_events,
        "read": read,
        "decision_semantics": "CONTEXT_ONLY_WARNING_ONLY",
    }


def build_summary(items: dict[str, Any]) -> str:
    parts = []
    for tf in DEFAULT_TFS:
        item = items.get(tf)
        if not item:
            continue
        state = item.get("setup_state")
        if state and state != "NO_SETUP":
            parts.append(
                f"{tf}: {item.get('pattern_name')} {state} side_if_confirmed={item.get('side_if_confirmed')}"
            )
    if not parts:
        return "Nenhum setup de retorno do fakeout ativo; manter leitura de contexto, evitar chase quando pattern_attempt_edge indicar risco alto."
    return " | ".join(parts)


def enrich_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tf_items = {tf: summarize_tf(tf, payload) for tf in DEFAULT_TFS}
    active = [item for item in tf_items.values() if item.get("setup_state") != "NO_SETUP"]
    context = {
        "available": bool(active),
        "version": "1.0",
        "decision_semantics": "CONTEXT_ONLY_WARNING_ONLY",
        "priority_rule": "Fakeout return setup can suggest watching return/fade opportunities, but it must not override Historical Intelligence, hard blocks, Chronos, Personal Guard or Diego M5 rule.",
        "core_rule": "High fakeout rate favors avoiding breakout chase and observing return inside formation; entry still requires closed candle, M5 permission and M1 trigger.",
        "states": [
            "NO_SETUP",
            "WATCHING_FAKEOUT",
            "RETURN_INSIDE_PENDING",
            "FAKEOUT_RETURN_CONFIRMATION_PENDING",
        ],
        "timeframes": tf_items,
        "summary": build_summary(tf_items),
    }
    out = dict(payload)
    out["fakeout_return_setup_context"] = context
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enriquece payload com fakeout_return_setup_context.")
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
        ctx = enriched.get("fakeout_return_setup_context", {})
        print(
            f"[OK] Fakeout Return Setup aplicado como CONTEXT_ONLY/WARNING_ONLY | "
            f"symbol={symbol} | available={ctx.get('available')} | summary={ctx.get('summary')}"
        )
        return 0
    except Exception as exc:
        print(f"[ERRO] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
