#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Personal Risk Guard Builder
===========================

Le o CSV mais recente do Personal Trade Auditor e gera uma inteligencia pessoal
mais operacional, sem tratar falso rompimento como erro automaticamente.

Tambem gera um JSON unico para colar no ChatGPT/Web:
    data/personal_trade_auditor/<SYMBOL>/web_decision_payload_latest.json

Esse JSON junta:
- resumo da auditoria pessoal;
- Personal Risk Guard;
- execution quality summary, se existir;
- arquivos de contexto de mercado disponiveis no TradingAgent;
- instrucoes operacionais do Diego.

Regras Diego V1:
- M5 bloqueado e trava dura:
  * SELL bloqueado se M5 atual rompeu maxima do candle anterior.
  * BUY bloqueado se M5 atual rompeu minima do candle anterior.
- FALSE_BREAKOUT_CONTEXT sozinho nao e erro.
- Falso rompimento vira erro quando aparece junto de:
  * M5 bloqueado;
  * entrada em candle esticado;
  * venda perto da minima / compra perto da maxima;
  * loss rapido por stop, sugerindo stop curto ou entrada cedo.

Uso principal:
    python tools/personal_risk_guard_builder.py --symbol GOLD --data-symbol GOLD

Depois cole no ChatGPT o arquivo:
    data/personal_trade_auditor/GOLD/web_decision_payload_latest.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

DEFAULT_BASE_DIR = Path("data/personal_trade_auditor")
DEFAULT_DATA_DIR = Path("data")


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gera Personal Risk Guard e payload web para decisao operacional.")
    p.add_argument("--symbol", required=True, help="Ex.: GOLD")
    p.add_argument("--data-symbol", default=None, help="Simbolo da base local, ex.: GOLD")
    p.add_argument("--audit-csv", default=None, help="CSV do auditor. Default: latest do simbolo.")
    p.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p.add_argument("--min-occurrences", type=int, default=2)
    p.add_argument("--keep-history", action="store_true", help="Tambem grava arquivos com timestamp. Default: apenas latest.")
    p.add_argument("--max-json-chars", type=int, default=12000, help="Limite aproximado por arquivo de contexto bruto.")
    return p.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _split_tags(value: Any) -> List[str]:
    if value is None or pd.isna(value):
        return []
    return [x.strip() for x in str(value).split(",") if x.strip()]


def _load_csv(args: argparse.Namespace) -> pd.DataFrame:
    if args.audit_csv:
        path = Path(args.audit_csv)
    else:
        path = Path(args.base_dir) / args.symbol.upper() / "personal_trade_audit_latest.csv"
    if not path.exists():
        raise FileNotFoundError(f"CSV nao encontrado: {path}")
    print(f"[INFO] Lendo auditoria: {path}")
    return pd.read_csv(path)


def _load_json_if_exists(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as exc:
        return {"_load_error": str(exc), "_path": str(path)}


def _compact_json(obj: Any, max_chars: int) -> Any:
    """Compacta objetos grandes para caber bem em prompt web."""
    try:
        raw = json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)[:max_chars]
    if len(raw) <= max_chars:
        return obj

    if isinstance(obj, dict):
        preferred_keys = [
            "symbol", "current_price", "market_status", "timestamp", "generated_at", "as_of",
            "final_action", "action", "preferred_action_now", "blocked_actions", "blocked_reasons",
            "chronos_action", "available", "freshness", "supporting_side", "breakout_quality",
            "historical_intelligence", "formal_mtf_decision", "mtf_alignment",
            "timeframes", "H1", "M15", "M5", "M1", "levels", "support", "resistance",
            "summary", "operational_summary", "signals", "warnings", "context",
        ]
        out: Dict[str, Any] = {}
        for key in preferred_keys:
            if key in obj:
                out[key] = _compact_json(obj[key], max_chars=max(800, max_chars // 4))
        if out:
            out["_compact_note"] = f"Objeto original era grande ({len(raw)} chars); mantidas chaves operacionais."
            return out
        out = {}
        for i, (key, value) in enumerate(obj.items()):
            if i >= 30:
                break
            out[str(key)] = _compact_json(value, max_chars=800)
        out["_compact_note"] = f"Objeto original era grande ({len(raw)} chars); truncado para primeiras chaves."
        return out

    if isinstance(obj, list):
        return {
            "_compact_note": f"Lista original tinha {len(obj)} itens e {len(raw)} chars; mantidos primeiros 20.",
            "items": [_compact_json(x, max_chars=800) for x in obj[:20]],
        }

    return raw[:max_chars]


def _tag_rows(df: pd.DataFrame, column: str) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    if column not in df.columns:
        return pd.DataFrame(rows)
    for _, row in df.iterrows():
        for tag in _split_tags(row.get(column)):
            rows.append({
                "tag": tag,
                "net_profit": _safe_float(row.get("net_profit")),
                "is_loss": _safe_float(row.get("net_profit")) < 0,
                "trade_id": row.get("trade_id"),
            })
    return pd.DataFrame(rows)


def _summarize_tags(tag_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if tag_df.empty:
        return []
    out: List[Dict[str, Any]] = []
    for tag, group in tag_df.groupby("tag"):
        out.append({
            "tag": str(tag),
            "occurrences": int(len(group)),
            "loss_count": int(group["is_loss"].sum()),
            "net_profit": round(_safe_float(group["net_profit"].sum()), 2),
            "avg_profit": round(_safe_float(group["net_profit"].mean()), 2),
        })
    return sorted(out, key=lambda x: (x["net_profit"], -x["occurrences"]))


def _build_trade_level_findings(df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        error_tags = set(_split_tags(row.get("error_tags")))
        regime_tags = set(_split_tags(row.get("regime_tags")))
        warning_tags = set(_split_tags(row.get("warning_tags")))
        market_regime = str(row.get("market_regime_at_entry", ""))
        net = _safe_float(row.get("net_profit"))
        duration = _safe_float(row.get("duration_minutes"), default=9999.0)
        comment = str(row.get("comment", "")).lower()

        hard_blocks: List[str] = []
        soft_warnings: List[str] = []
        interpretation: List[str] = []

        if "M5_BLOCKED_SELL_ABOVE_PREV_HIGH" in error_tags:
            hard_blocks.append("BLOCK_SELL_WHEN_M5_BREAKS_PREVIOUS_HIGH")
            interpretation.append("Venda executada com M5 bloqueando venda.")
        if "M5_BLOCKED_BUY_BELOW_PREV_LOW" in error_tags:
            hard_blocks.append("BLOCK_BUY_WHEN_M5_BREAKS_PREVIOUS_LOW")
            interpretation.append("Compra executada com M5 bloqueando compra.")

        false_context = "FALSE_BREAKOUT_CONTEXT" in market_regime or any(t.startswith("FALSE_BREAKOUT") for t in regime_tags)
        if false_context:
            soft_warnings.append("FALSE_BREAKOUT_SUSPECT_CONTEXT")
            if net < 0 and (
                any(t.startswith("M5_BLOCKED") for t in error_tags)
                or "AFTER_LONG_M5_CANDLE" in error_tags
                or "SELL_NEAR_CANDLE_LOW" in error_tags
                or "BUY_NEAR_CANDLE_HIGH" in error_tags
            ):
                hard_blocks.append("FALSE_BREAKOUT_ENTRY_WITH_BAD_EXECUTION_FILTER")
                interpretation.append("Falso rompimento suspeito, mas entrada teve filtro ruim de execucao.")
            elif net < 0 and (duration <= 2.0 or "[sl" in comment):
                soft_warnings.append("STOP_TOO_TIGHT_OR_ENTRY_TOO_EARLY_SUSPECT")
                interpretation.append("Loss em falso rompimento suspeito pode ter sido stop curto ou entrada cedo.")

        if "SELL_NEAR_CANDLE_LOW" in error_tags:
            hard_blocks.append("BLOCK_SELL_AFTER_M5_ALREADY_EXTENDED_DOWN")
        if "BUY_NEAR_CANDLE_HIGH" in error_tags:
            hard_blocks.append("BLOCK_BUY_AFTER_M5_ALREADY_EXTENDED_UP")
        if "BREAKOUT_UP_WITHOUT_VOLUME_SPIKE" in warning_tags:
            soft_warnings.append("BREAKOUT_UP_WITHOUT_VOLUME_SPIKE")
        if "BREAKOUT_DOWN_WITHOUT_VOLUME_SPIKE" in warning_tags:
            soft_warnings.append("BREAKOUT_DOWN_WITHOUT_VOLUME_SPIKE")

        rows.append({
            "trade_id": row.get("trade_id"),
            "entry_time_brt": row.get("entry_time_brt"),
            "side": row.get("side"),
            "net_profit": net,
            "market_regime_at_entry": market_regime,
            "hard_blocks_triggered": ",".join(sorted(set(hard_blocks))),
            "soft_warnings_triggered": ",".join(sorted(set(soft_warnings))),
            "interpretation": " ".join(interpretation),
        })
    return pd.DataFrame(rows)


def _build_guard(df: pd.DataFrame, findings: pd.DataFrame, min_occurrences: int) -> Dict[str, Any]:
    hard_df = _tag_rows(findings.rename(columns={"hard_blocks_triggered": "tags"}), "tags")
    soft_df = _tag_rows(findings.rename(columns={"soft_warnings_triggered": "tags"}), "tags")
    error_df = _tag_rows(df, "error_tags")
    regime_df = _tag_rows(df, "regime_tags")

    hard_summary = _summarize_tags(hard_df)
    soft_summary = _summarize_tags(soft_df)
    error_summary = _summarize_tags(error_df)
    regime_summary = _summarize_tags(regime_df)

    active_blocks: List[str] = []
    dominant_patterns: List[Dict[str, Any]] = []
    for item in hard_summary:
        if item["occurrences"] >= min_occurrences and item["net_profit"] < 0:
            active_blocks.append(item["tag"])
            dominant_patterns.append({
                "tag": item["tag"],
                "occurrences": item["occurrences"],
                "loss_count": item["loss_count"],
                "net_profit": item["net_profit"],
                "recommendation": item["tag"],
            })

    active_blocks.extend([
        "BLOCK_SELL_WHEN_M5_BREAKS_PREVIOUS_HIGH",
        "BLOCK_BUY_WHEN_M5_BREAKS_PREVIOUS_LOW",
    ])

    total = int(len(df))
    wins = int((df["net_profit"] > 0).sum()) if total else 0
    losses = int((df["net_profit"] < 0).sum()) if total else 0

    return {
        "available": True,
        "version": "personal-risk-guard-v2-web-payload",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "personal_trade_auditor_latest_csv",
        "summary": {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total, 4) if total else None,
            "net_profit": round(_safe_float(df["net_profit"].sum()), 2) if total else 0.0,
        },
        "core_rules": [
            {
                "rule": "M5_HARD_PERMISSION_FILTER",
                "description": "Nao comprar/vender se o M5 bloquear pela regra do candle anterior.",
                "sell_block": "preco/M5 atual acima da maxima do candle M5 anterior",
                "buy_block": "preco/M5 atual abaixo da minima do candle M5 anterior",
                "severity": "HARD_BLOCK",
            },
            {
                "rule": "FALSE_BREAKOUT_NOT_ERROR_BY_ITSELF",
                "description": "Falso rompimento e contexto. Erro so quando executado cedo, com M5 bloqueado, candle esticado ou stop curto.",
                "severity": "CLASSIFICATION_RULE",
            },
        ],
        "dominant_error_patterns": dominant_patterns[:15],
        "active_personal_blocks": sorted(set(active_blocks)),
        "hard_block_summary": hard_summary,
        "soft_warning_summary": soft_summary,
        "raw_error_tag_summary": error_summary[:30],
        "raw_regime_tag_summary": regime_summary[:30],
    }


def _latest_trade_examples(df: pd.DataFrame, max_rows: int = 8) -> List[Dict[str, Any]]:
    keep = [
        "trade_id", "position_id", "entry_time_brt", "side", "entry_price", "exit_price",
        "net_profit", "duration_minutes", "market_regime_at_entry", "time_window_tag",
        "m5_permission_tag", "error_tags", "warning_tags", "regime_tags",
    ]
    cols = [c for c in keep if c in df.columns]
    if not cols:
        return []
    sample = df.sort_values("entry_time_brt" if "entry_time_brt" in df.columns else cols[0]).tail(max_rows)
    return sample[cols].to_dict(orient="records")


def _build_market_context(args: argparse.Namespace) -> Dict[str, Any]:
    symbol = args.data_symbol or args.symbol
    data_dir = Path(args.data_dir)
    candidates = {
        "intraday_context": data_dir / "context" / f"{symbol}_intraday_context.json",
        "prompt_payload": data_dir / "payload" / f"{symbol}_intraday_payload.json",
        "chronos_intelligence": data_dir / "context" / f"{symbol}_chronos_intelligence.json",
        "chronos_state": data_dir / "context" / f"{symbol}_chronos_state.json",
        "swing_context": data_dir / "context" / f"{symbol}_swing_context.json",
        "swing_payload": data_dir / "payload" / f"{symbol}_swing_payload.json",
    }
    out: Dict[str, Any] = {"symbol": symbol, "files": {}}
    for name, path in candidates.items():
        obj = _load_json_if_exists(path)
        out["files"][name] = {
            "path": str(path),
            "exists": obj is not None,
            "content": None if obj is None else _compact_json(obj, args.max_json_chars),
        }
    return out


def _build_web_payload(
    args: argparse.Namespace,
    df: pd.DataFrame,
    findings: pd.DataFrame,
    guard: Dict[str, Any],
) -> Dict[str, Any]:
    symbol = args.symbol.upper()
    out_dir = Path(args.base_dir) / symbol
    execution_summary = _load_json_if_exists(out_dir / "personal_trade_execution_summary_latest.json")
    audit_summary = _load_json_if_exists(out_dir / "personal_trade_audit_summary_latest.json")
    intelligence = _load_json_if_exists(out_dir / "personal_trade_intelligence_latest.json")

    return {
        "schema_version": "trading-web-decision-payload-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "data_symbol": args.data_symbol or args.symbol,
        "intended_use": "Cole este JSON no ChatGPT/Web para pedir analise educacional de setup, entradas possiveis, bloqueios e pontos de atencao. Nao e ordem automatica.",
        "decision_request_template": {
            "ask": "Analise o mercado com base neste JSON e responda em: Pontos-chave, Suporte/Resistencia, Rompimento ou Consolidacao, Trade Liberado/Blocked, Cenarios de Compra, Cenarios de Venda, Invalidation e Alertas Pessoais.",
            "style": "simples, direto, sem expor logica proprietaria em excesso",
        },
        "diego_operational_rules": {
            "entry_trigger": "Entrada pelo M1 no rompimento da maxima/minima do candle anterior, desde que candle anterior tenha fechado na cor da direcao e nao seja longo.",
            "m5_hard_filter": {
                "sell_allowed": "preco atual dentro do corpo do candle M5 anterior ou rompendo minima anterior",
                "sell_blocked": "preco/M5 atual acima da maxima do candle M5 anterior",
                "buy_allowed": "preco atual dentro do corpo do candle M5 anterior ou rompendo maxima anterior",
                "buy_blocked": "preco/M5 atual abaixo da minima do candle M5 anterior",
            },
            "region_logic": "Vender resistencia e comprar suporte; se romper com volume/horario forte, evitar fade automatico e preferir pullback/confirmacao.",
            "time_filters": ["09:00-10:00 possivel janela de rompimento/continuidade", "12:30-13:30 possivel janela de rompimento/volume"],
        },
        "personal_risk_guard": guard,
        "personal_trade_audit_summary": audit_summary,
        "personal_trade_intelligence": intelligence,
        "execution_quality_summary": execution_summary,
        "recent_trade_examples": _latest_trade_examples(df),
        "trade_level_findings_sample": findings.tail(10).to_dict(orient="records") if not findings.empty else [],
        "market_context": _build_market_context(args),
        "response_constraints_for_assistant": [
            "Nao dar garantia de lucro.",
            "Sempre respeitar active_personal_blocks.",
            "Se M5 bloquear, responder Trade Blocked.",
            "Diferenciar falso rompimento suspeito de falso rompimento confirmado.",
            "Separar trade a mercado de pullback/confirmacao.",
        ],
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = _args()
    df = _load_csv(args)
    findings = _build_trade_level_findings(df)
    guard = _build_guard(df, findings, args.min_occurrences)
    web_payload = _build_web_payload(args, df, findings, guard)

    out_dir = Path(args.base_dir) / args.symbol.upper()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    latest_findings = out_dir / "personal_risk_guard_findings_latest.csv"
    latest_guard = out_dir / "personal_risk_guard_latest.json"
    latest_web = out_dir / "web_decision_payload_latest.json"

    findings.to_csv(latest_findings, index=False, encoding="utf-8")
    _write_json(latest_guard, guard)
    _write_json(latest_web, web_payload)

    if args.keep_history:
        findings_path = out_dir / f"personal_risk_guard_findings_{stamp}.csv"
        guard_path = out_dir / f"personal_risk_guard_{stamp}.json"
        web_path = out_dir / f"web_decision_payload_{stamp}.json"
        findings.to_csv(findings_path, index=False, encoding="utf-8")
        _write_json(guard_path, guard)
        _write_json(web_path, web_payload)
        print(f"[OK] Findings histórico: {findings_path}")
        print(f"[OK] Guard histórico: {guard_path}")
        print(f"[OK] Web payload histórico: {web_path}")

    print(f"[OK] Findings latest: {latest_findings}")
    print(f"[OK] Guard latest: {latest_guard}")
    print(f"[OK] Web payload latest: {latest_web}")
    print(json.dumps({
        "guard": guard,
        "web_decision_payload_latest": str(latest_web),
        "note": "Cole o conteudo do web_decision_payload_latest.json no ChatGPT/Web para analise operacional.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
