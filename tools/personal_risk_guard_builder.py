#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Personal Risk Guard Builder
===========================

Le o CSV mais recente do Personal Trade Auditor e gera uma inteligencia pessoal
mais operacional, sem tratar falso rompimento como erro automaticamente.

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

Uso:
    python tools/personal_risk_guard_builder.py --symbol GOLD

Ou apontando um CSV especifico:
    python tools/personal_risk_guard_builder.py ^
      --symbol GOLD ^
      --audit-csv data/personal_trade_auditor/GOLD/personal_trade_audit_latest.csv
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

DEFAULT_BASE_DIR = Path("data/personal_trade_auditor")


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gera Personal Risk Guard a partir do CSV auditado.")
    p.add_argument("--symbol", required=True, help="Ex.: GOLD")
    p.add_argument("--audit-csv", default=None, help="CSV do auditor. Default: latest do simbolo.")
    p.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    p.add_argument("--min-occurrences", type=int, default=2)
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

    # Regra fixa do Diego: M5 bloqueado e trava operacional dura.
    active_blocks.extend([
        "BLOCK_SELL_WHEN_M5_BREAKS_PREVIOUS_HIGH",
        "BLOCK_BUY_WHEN_M5_BREAKS_PREVIOUS_LOW",
    ])

    total = int(len(df))
    wins = int((df["net_profit"] > 0).sum()) if total else 0
    losses = int((df["net_profit"] < 0).sum()) if total else 0

    return {
        "available": True,
        "version": "personal-risk-guard-v1-m5-hard-block",
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


def main() -> int:
    args = _args()
    df = _load_csv(args)
    findings = _build_trade_level_findings(df)
    guard = _build_guard(df, findings, args.min_occurrences)

    out_dir = Path(args.base_dir) / args.symbol.upper()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    findings_path = out_dir / f"personal_risk_guard_findings_{stamp}.csv"
    latest_findings = out_dir / "personal_risk_guard_findings_latest.csv"
    guard_path = out_dir / f"personal_risk_guard_{stamp}.json"
    latest_guard = out_dir / "personal_risk_guard_latest.json"

    findings.to_csv(findings_path, index=False, encoding="utf-8")
    findings.to_csv(latest_findings, index=False, encoding="utf-8")
    guard_path.write_text(json.dumps(guard, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_guard.write_text(json.dumps(guard, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] Findings: {findings_path}")
    print(f"[OK] Guard: {guard_path}")
    print(json.dumps(guard, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
