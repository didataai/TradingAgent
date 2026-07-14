#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - Pattern Attempt Edge Payload Enricher
====================================================

FINALIDADE
----------
Transformar o estudo `pattern_attempt_research.py` em uma camada de inteligencia
filtrada para o payload operacional.

Esta ferramenta NAO decide trade. Ela le os CSVs gerados em:

    data/research/pattern_attempt/<SYMBOL>/

cruza essas estatisticas com o `technical_patterns_context` atual do payload e
injeta um bloco:

    pattern_attempt_edge_context

Esse bloco responde, de forma resumida e operacional:

- o padrao atual costuma aceitar rompimento ou gerar fakeout?
- a tentativa atual parece ser primeira/segunda/terceira tentativa?
- horario, sessao, dia da semana e semana do mes ajudam ou pioram?
- vale perseguir rompimento ou e melhor esperar reteste/confirmacao?

REGRAS DE SEGURANCA OPERACIONAL
-------------------------------
- A camada e CONTEXT_ONLY / WARNING_ONLY.
- Nao sobrescreve Historical Intelligence.
- Nao transforma BUY/SELL/LIMIT em WAIT.
- Nao cria hard block sozinha.
- Nao autoriza operar contra guard formal.
- Dados estatisticos fracos ou sem amostra suficiente viram contexto fraco.

COMPATIBILIDADE
---------------
- Windows/Linux: usa pathlib, csv/json da stdlib e escrita atomica.
- Sem dependencia obrigatoria de pandas.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TFS = ("H1", "M15", "M5", "M1")
MIN_SAMPLE_STRONG = 20
MIN_SAMPLE_WEAK = 8
GOOD_ACCEPTED_RATE = 0.32
BAD_FAKEOUT_RATE = 0.75
VERY_BAD_FAKEOUT_RATE = 0.85

CSV_FILES = {
    "by_pattern_tf": "pattern_attempt_by_pattern_tf.csv",
    "by_hour": "pattern_attempt_by_hour.csv",
    "by_day_of_week": "pattern_attempt_by_day_of_week.csv",
    "by_week_of_month": "pattern_attempt_by_week_of_month.csv",
    "by_session": "pattern_attempt_by_session.csv",
    "by_attempt_number": "pattern_attempt_by_attempt_number.csv",
    "by_pattern_attempt_number": "pattern_attempt_by_pattern_attempt_number.csv",
    "by_pattern_hour": "pattern_attempt_by_pattern_hour.csv",
    "by_pattern_week_of_month": "pattern_attempt_by_pattern_week_of_month.csv",
}


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "_").replace("-", "_")


def payload_path(symbol: str) -> Path:
    return ROOT / "data" / "payload" / f"{symbol}_intraday_payload.json"


def research_dir(symbol: str) -> Path:
    return ROOT / "data" / "research" / "pattern_attempt" / symbol.upper()


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


def load_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_research_tables(base_dir: Path) -> dict[str, list[dict[str, Any]]]:
    return {name: load_csv(base_dir / filename) for name, filename in CSV_FILES.items()}


def row_metric(row: dict[str, Any]) -> dict[str, Any]:
    events = safe_int(row.get("events"), 0)
    accepted_rate = safe_float(row.get("accepted_rate"), None)
    fakeout_rate = safe_float(row.get("fakeout_rate"), None)
    return {
        "events": events,
        "accepted_rate": round(accepted_rate, 5) if accepted_rate is not None else None,
        "fakeout_rate": round(fakeout_rate, 5) if fakeout_rate is not None else None,
        "accepted": safe_int(row.get("accepted"), 0),
        "fakeouts": safe_int(row.get("fakeouts"), 0),
    }


def sample_quality(events: int) -> str:
    if events >= MIN_SAMPLE_STRONG:
        return "STRONG_SAMPLE"
    if events >= MIN_SAMPLE_WEAK:
        return "WEAK_SAMPLE"
    if events > 0:
        return "VERY_SMALL_SAMPLE"
    return "NO_SAMPLE"


def score_from_metric(metric: dict[str, Any]) -> tuple[int, list[str]]:
    """Retorna score simples: positivo favorece aceitacao; negativo alerta fakeout."""
    events = int(metric.get("events") or 0)
    accepted_rate = safe_float(metric.get("accepted_rate"), None)
    fakeout_rate = safe_float(metric.get("fakeout_rate"), None)
    score = 0
    reasons: list[str] = []

    if events <= 0:
        return 0, ["sem amostra"]

    if events < MIN_SAMPLE_WEAK:
        reasons.append("amostra pequena")
        score -= 1

    if accepted_rate is not None:
        if accepted_rate >= GOOD_ACCEPTED_RATE:
            score += 2 if events >= MIN_SAMPLE_STRONG else 1
            reasons.append(f"accepted_rate favoravel={accepted_rate:.2%}")
        elif accepted_rate < 0.20:
            score -= 1
            reasons.append(f"accepted_rate baixo={accepted_rate:.2%}")

    if fakeout_rate is not None:
        if fakeout_rate >= VERY_BAD_FAKEOUT_RATE:
            score -= 3
            reasons.append(f"fakeout_rate muito alto={fakeout_rate:.2%}")
        elif fakeout_rate >= BAD_FAKEOUT_RATE:
            score -= 2
            reasons.append(f"fakeout_rate alto={fakeout_rate:.2%}")
        elif fakeout_rate <= 0.60:
            score += 1
            reasons.append(f"fakeout_rate menor={fakeout_rate:.2%}")

    return score, reasons


def find_first(rows: list[dict[str, Any]], **filters: Any) -> dict[str, Any] | None:
    for row in rows:
        ok = True
        for key, expected in filters.items():
            if normalize(row.get(key)) != normalize(expected):
                ok = False
                break
        if ok:
            return row
    return None


def parse_time_brt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def week_of_month(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    return ((dt.day - 1) // 7) + 1


def day_of_week_name(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][dt.weekday()]


def infer_attempt_number(attempt_ctx: dict[str, Any]) -> int:
    explicit = safe_int(attempt_ctx.get("attempt_number") or attempt_ctx.get("current_attempt_number"), 0)
    if explicit > 0:
        return min(explicit, 3)
    up = safe_int(attempt_ctx.get("breakout_attempts_up"), 0)
    down = safe_int(attempt_ctx.get("breakout_attempts_down"), 0)
    total = max(up, down, up + down)
    if total <= 0:
        return 1
    return min(total, 3)


def classify_decision(total_score: int, fakeout_rate_hint: float | None) -> tuple[str, str]:
    if fakeout_rate_hint is not None and fakeout_rate_hint >= VERY_BAD_FAKEOUT_RATE:
        return "AVOID_CHASE", "VERY_HIGH_FAKEOUT_RISK"
    if total_score <= -4:
        return "AVOID_CHASE", "HIGH_FAKEOUT_RISK"
    if total_score <= -2:
        return "WAIT_RETEST_OR_CONFIRMATION", "ELEVATED_FAKEOUT_RISK"
    if total_score >= 4:
        return "BREAKOUT_CAN_BE_CONSIDERED_WITH_CONFIRMATION", "FAVORABLE_CONTEXT"
    if total_score >= 2:
        return "WATCH_ACCEPTANCE", "SLIGHTLY_FAVORABLE_CONTEXT"
    return "WAIT_CONFIRMATION", "MIXED_OR_NEUTRAL_CONTEXT"


def build_tf_edge(
    symbol: str,
    tf: str,
    payload: dict[str, Any],
    tech_tf: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    main = tech_tf.get("main_pattern") or {}
    attempt_ctx = tech_tf.get("breakout_attempt_context") or {}
    pattern_name = normalize(main.get("name")) or "UNKNOWN"
    attempt_number = infer_attempt_number(attempt_ctx)

    tf_payload = (payload.get("timeframes", {}) or {}).get(tf, {}) or {}
    current_bar = tf_payload.get("current_bar", {}) or {}
    dt = parse_time_brt(current_bar.get("time_brt"))
    hour = dt.hour if dt else None
    dow = day_of_week_name(dt)
    wom = week_of_month(dt)
    session = current_bar.get("session_name") or "UNKNOWN"

    evidence: list[dict[str, Any]] = []
    total_score = 0
    fakeout_hint: float | None = None

    lookups = [
        ("pattern_tf", find_first(tables.get("by_pattern_tf", []), timeframe=tf, pattern_name=pattern_name)),
        ("attempt_number", find_first(tables.get("by_attempt_number", []), attempt_number=attempt_number)),
        ("pattern_attempt", find_first(tables.get("by_pattern_attempt_number", []), pattern_name=pattern_name, attempt_number=attempt_number)),
        ("hour", find_first(tables.get("by_hour", []), formation_hour=hour) if hour is not None else None),
        ("pattern_hour", find_first(tables.get("by_pattern_hour", []), pattern_name=pattern_name, formation_hour=hour) if hour is not None else None),
        ("day_of_week", find_first(tables.get("by_day_of_week", []), day_of_week=dow) if dow else None),
        ("week_of_month", find_first(tables.get("by_week_of_month", []), week_of_month=wom) if wom is not None else None),
        ("pattern_week_of_month", find_first(tables.get("by_pattern_week_of_month", []), pattern_name=pattern_name, week_of_month=wom) if wom is not None else None),
        ("session", find_first(tables.get("by_session", []), session_name=session)),
    ]

    for source, row in lookups:
        if not row:
            continue
        metric = row_metric(row)
        score, reasons = score_from_metric(metric)
        total_score += score
        if metric.get("fakeout_rate") is not None:
            fakeout_hint = max(fakeout_hint or 0.0, float(metric["fakeout_rate"]))
        evidence.append({
            "source": source,
            "sample_quality": sample_quality(int(metric.get("events") or 0)),
            "score": score,
            "reasons": reasons[:4],
            **metric,
        })

    preferred, risk = classify_decision(total_score, fakeout_hint)
    inside_now = attempt_ctx.get("inside_formation_now")
    fakeout_current = attempt_ctx.get("fakeout_risk")
    last_result = attempt_ctx.get("last_attempt_result")

    if normalize(fakeout_current) in {"HIGH", "VERY_HIGH"} or normalize(last_result) == "FAILED_BREAKOUT":
        if preferred not in {"AVOID_CHASE", "WAIT_RETEST_OR_CONFIRMATION"}:
            preferred = "WAIT_RETEST_OR_CONFIRMATION"
            risk = "CURRENT_FAKEOUT_WARNING"

    read = (
        f"{tf} {pattern_name}: contexto estatistico={risk}; "
        f"tentativa={attempt_number}; interpretacao={preferred}."
    )
    if inside_now is True:
        read += " Preco voltou/esta dentro da formacao; evitar chase e priorizar reteste/gatilho."

    return {
        "available": bool(evidence),
        "symbol": symbol,
        "timeframe": tf,
        "pattern_name": pattern_name,
        "attempt_number": attempt_number,
        "current_hour_brt": hour,
        "day_of_week": dow,
        "week_of_month": wom,
        "session_name": session,
        "total_edge_score": total_score,
        "edge_classification": risk,
        "preferred_interpretation": preferred,
        "current_attempt_context": {
            "last_attempt_side": attempt_ctx.get("last_attempt_side"),
            "last_attempt_result": last_result,
            "inside_formation_now": inside_now,
            "fakeout_risk": fakeout_current,
            "third_attempt_watch": attempt_ctx.get("third_attempt_watch"),
        },
        "evidence": evidence[:12],
        "read": read,
        "decision_semantics": "CONTEXT_ONLY_WARNING_ONLY",
    }


def build_summary(tf_edges: dict[str, Any]) -> str:
    parts: list[str] = []
    for tf in ("M15", "M5", "M1", "H1"):
        edge = tf_edges.get(tf)
        if not edge or not edge.get("available"):
            continue
        parts.append(
            f"{tf}: {edge.get('pattern_name')} attempt={edge.get('attempt_number')} "
            f"{edge.get('preferred_interpretation')}/{edge.get('edge_classification')}"
        )
    if not parts:
        return "Pattern Attempt Edge indisponivel ou sem amostra relevante; usar apenas Technical Patterns como contexto."
    return " | ".join(parts)


def enrich_payload(payload: dict[str, Any], symbol: str, base_dir: Path) -> dict[str, Any]:
    tables = load_research_tables(base_dir)
    tech = payload.get("technical_patterns_context", {}) or {}
    tech_tfs = tech.get("timeframes", {}) or {}

    tf_edges: dict[str, Any] = {}
    for tf in DEFAULT_TFS:
        item = tech_tfs.get(tf)
        if isinstance(item, dict):
            tf_edges[tf] = build_tf_edge(symbol, tf, payload, item, tables)

    available = any(edge.get("available") for edge in tf_edges.values())
    context = {
        "available": available,
        "source_dir": str(base_dir),
        "decision_semantics": "CONTEXT_ONLY_WARNING_ONLY",
        "priority_rule": "Pattern Attempt Edge filters whether breakout chase is worth considering; it does not override Historical, Chronos hard blocks, Personal Guard or M5 rule.",
        "usage_rule": "Use as statistical context: high fakeout risk means avoid chase and prefer retest/acceptance; favorable context still requires candle close, volume, M5 permission and M1 trigger.",
        "timeframes": tf_edges,
        "summary": build_summary(tf_edges),
    }
    out = dict(payload)
    out["pattern_attempt_edge_context"] = context
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enriquece payload com pattern_attempt_edge_context.")
    parser.add_argument("--symbol", default="GOLD", help="Simbolo. Padrao: GOLD.")
    parser.add_argument("--payload", help="Payload de entrada/saida. Padrao: data/payload/<SYMBOL>_intraday_payload.json.")
    parser.add_argument("--output", help="Arquivo de saida. Padrao: sobrescreve --payload.")
    parser.add_argument("--research-dir", help="Diretorio pattern_attempt. Padrao: data/research/pattern_attempt/<SYMBOL>.")
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
    base_dir = Path(args.research_dir) if args.research_dir else research_dir(symbol)
    if not base_dir.is_absolute():
        base_dir = ROOT / base_dir

    try:
        payload = read_json(source)
        if not base_dir.exists():
            raise FileNotFoundError(f"Diretorio de pesquisa nao encontrado: {base_dir}")
        enriched = enrich_payload(payload, symbol, base_dir)
        write_json_atomic(output, enriched)
        ctx = enriched.get("pattern_attempt_edge_context", {}) or {}
        print(
            f"[OK] Pattern Attempt Edge aplicado como CONTEXT_ONLY/WARNING_ONLY | "
            f"symbol={symbol} | available={ctx.get('available')} | summary={ctx.get('summary')}"
        )
        return 0
    except Exception as exc:
        print(f"[ERRO] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
