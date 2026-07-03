#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Personal Trade Execution Audit
==============================

Complementa o `personal_trade_auditor.py` calculando MFE/MAE dos trades ja
auditados. A ideia e separar:

- leitura ruim;
- entrada ruim;
- stop curto demais;
- saida ruim;
- ideia boa com execucao/stop ruim.

Entrada:
- CSV gerado pelo personal_trade_auditor.py;
- base intraday parquet do TradingAgent.

Uso:
    python tools/personal_trade_execution_audit.py ^
      --symbol GOLD ^
      --data-symbol GOLD

Ou informando CSV especifico:
    python tools/personal_trade_execution_audit.py ^
      --symbol GOLD ^
      --data-symbol GOLD ^
      --audit-csv data/personal_trade_auditor/GOLD/personal_trade_audit_latest.csv
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


BRT_TZ = "America/Sao_Paulo"
DEFAULT_DATA_DIR = Path("data")
DEFAULT_AUDIT_DIR = Path("data/personal_trade_auditor")


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Calcula MFE/MAE e qualidade de execucao dos trades auditados.")
    p.add_argument("--symbol", required=True, help="Alias do relatorio, ex.: GOLD")
    p.add_argument("--data-symbol", default=None, help="Simbolo da base local, ex.: GOLD")
    p.add_argument("--audit-csv", default=None, help="CSV gerado pelo personal_trade_auditor.py")
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p.add_argument("--audit-dir", default=str(DEFAULT_AUDIT_DIR))
    p.add_argument("--horizon-minutes", type=int, default=60, help="Janela pos-entrada para medir movimento")
    p.add_argument("--post-exit-minutes", type=int, default=30, help="Janela depois da saida para ver se o movimento veio depois")
    p.add_argument("--mfe-good-points", type=float, default=2.0, help="MFE minimo em preco para considerar ideia com potencial")
    p.add_argument("--stop-tight-ratio", type=float, default=1.25, help="MFE futuro precisa ser X vezes o loss em preco para marcar stop/saida ruim")
    return p.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _safe_time(value: Any) -> Optional[pd.Timestamp]:
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts
    except Exception:
        return None


def _find_audit_csv(symbol: str, audit_dir: Path, explicit: Optional[str]) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise FileNotFoundError(f"CSV de auditoria nao encontrado: {p}")
        return p
    p = audit_dir / symbol.upper() / "personal_trade_audit_latest.csv"
    if not p.exists():
        raise FileNotFoundError(f"CSV latest nao encontrado: {p}")
    return p


def _find_context_file(data_dir: Path, data_symbol: str) -> Path:
    candidates = [
        data_dir / "consolidated" / f"{data_symbol}_intraday.parquet",
        data_dir / "consolidated" / f"{data_symbol.upper()}_intraday.parquet",
        data_dir / "consolidated" / f"{data_symbol.capitalize()}_intraday.parquet",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"Consolidado intraday nao encontrado para {data_symbol}: {candidates}")


def _load_context(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df.columns = [str(c) for c in df.columns]
    time_col = next((c for c in ("time_utc", "datetime_utc", "timestamp_utc", "time", "datetime", "timestamp", "time_brt") if c in df.columns), None)
    if not time_col:
        raise ValueError("Base intraday sem coluna de tempo reconhecida.")

    if time_col == "time_brt" and ZoneInfo is not None:
        df["context_time_utc"] = pd.to_datetime(df[time_col], errors="coerce").dt.tz_localize(
            BRT_TZ, nonexistent="shift_forward", ambiguous="NaT"
        ).dt.tz_convert("UTC")
    else:
        df["context_time_utc"] = pd.to_datetime(df[time_col], utc=True, errors="coerce")

    tf_col = next((c for c in ("timeframe", "tf", "period") if c in df.columns), None)
    df["context_timeframe"] = df[tf_col].astype(str).str.upper() if tf_col else "UNKNOWN"
    df = df.dropna(subset=["context_time_utc"]).sort_values("context_time_utc")
    return df


def _m1_frame(context: pd.DataFrame) -> pd.DataFrame:
    if "context_timeframe" in context.columns and (context["context_timeframe"] != "UNKNOWN").any():
        m1 = context[context["context_timeframe"] == "M1"].copy()
        if not m1.empty:
            return m1
    return context.copy()


def _price_slice(m1: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return m1[(m1["context_time_utc"] >= start) & (m1["context_time_utc"] <= end)].copy()


def _calc_mfe_mae_for_trade(row: pd.Series, m1: pd.DataFrame, horizon_minutes: int, post_exit_minutes: int) -> Dict[str, Any]:
    side = str(row.get("side", "")).upper()
    entry_price = _safe_float(row.get("entry_price"), default=float("nan"))
    exit_price = _safe_float(row.get("exit_price"), default=float("nan"))
    entry_time = _safe_time(row.get("entry_time_utc"))
    exit_time = _safe_time(row.get("exit_time_utc"))
    if entry_time is None or math.isnan(entry_price) or side not in ("BUY", "SELL"):
        return {
            "mfe_points": None,
            "mae_points": None,
            "post_exit_mfe_points": None,
            "execution_quality_tags": "EXECUTION_DATA_UNAVAILABLE",
        }

    horizon_end = entry_time + pd.Timedelta(minutes=horizon_minutes)
    measure_end = min(exit_time, horizon_end) if exit_time is not None else horizon_end
    bars = _price_slice(m1, entry_time, measure_end)
    if bars.empty or "high" not in bars.columns or "low" not in bars.columns:
        return {
            "mfe_points": None,
            "mae_points": None,
            "post_exit_mfe_points": None,
            "execution_quality_tags": "M1_PRICE_DATA_UNAVAILABLE",
        }

    high = pd.to_numeric(bars["high"], errors="coerce").max()
    low = pd.to_numeric(bars["low"], errors="coerce").min()
    if side == "BUY":
        mfe = float(high - entry_price)
        mae = float(entry_price - low)
    else:
        mfe = float(entry_price - low)
        mae = float(high - entry_price)

    post_exit_mfe = None
    if exit_time is not None:
        post_bars = _price_slice(m1, exit_time, exit_time + pd.Timedelta(minutes=post_exit_minutes))
        if not post_bars.empty and "high" in post_bars.columns and "low" in post_bars.columns:
            post_high = pd.to_numeric(post_bars["high"], errors="coerce").max()
            post_low = pd.to_numeric(post_bars["low"], errors="coerce").min()
            if side == "BUY":
                post_exit_mfe = float(post_high - exit_price) if not math.isnan(exit_price) else None
            else:
                post_exit_mfe = float(exit_price - post_low) if not math.isnan(exit_price) else None

    return {
        "mfe_points": round(mfe, 5),
        "mae_points": round(mae, 5),
        "post_exit_mfe_points": None if post_exit_mfe is None else round(post_exit_mfe, 5),
        "execution_quality_tags": "",
    }


def _classify_execution(row: Dict[str, Any], mfe_good_points: float, stop_tight_ratio: float) -> str:
    tags: List[str] = []
    net = _safe_float(row.get("net_profit"))
    side = str(row.get("side", "")).upper()
    entry = _safe_float(row.get("entry_price"), default=float("nan"))
    exit_price = _safe_float(row.get("exit_price"), default=float("nan"))
    mfe = _safe_float(row.get("mfe_points"), default=float("nan"))
    mae = _safe_float(row.get("mae_points"), default=float("nan"))
    post_exit_mfe = _safe_float(row.get("post_exit_mfe_points"), default=float("nan"))

    if side == "BUY" and not math.isnan(entry) and not math.isnan(exit_price):
        realized_points = exit_price - entry
    elif side == "SELL" and not math.isnan(entry) and not math.isnan(exit_price):
        realized_points = entry - exit_price
    else:
        realized_points = float("nan")

    if net < 0:
        tags.append("TRADE_LOSS")
        if not math.isnan(mfe) and mfe >= mfe_good_points:
            tags.append("LOSS_BUT_HAD_GOOD_MFE")
        if not math.isnan(post_exit_mfe) and post_exit_mfe >= mfe_good_points:
            tags.append("MOVE_CAME_AFTER_EXIT")
        if not math.isnan(post_exit_mfe) and not math.isnan(realized_points):
            loss_points = abs(min(realized_points, 0.0))
            if loss_points > 0 and post_exit_mfe >= loss_points * stop_tight_ratio:
                tags.append("GOOD_IDEA_BAD_STOP_OR_EXIT")
        if not math.isnan(mae) and not math.isnan(mfe) and mae > 0 and mfe / mae >= stop_tight_ratio:
            tags.append("ADVERSE_MOVE_SMALL_VS_FAVORABLE_MOVE")
    elif net > 0:
        tags.append("TRADE_WIN")
        if not math.isnan(mfe) and not math.isnan(realized_points) and mfe > 0:
            capture = max(realized_points, 0.0) / mfe
            if capture < 0.35 and mfe >= mfe_good_points:
                tags.append("EXIT_TOO_EARLY_LOW_MFE_CAPTURE")
            else:
                tags.append("EXECUTION_ACCEPTABLE")
    else:
        tags.append("TRADE_FLAT")

    # Erros ja detectados no auditor principal que viram qualidade de execucao.
    existing_errors = str(row.get("error_tags", ""))
    if "M5_BLOCKED" in existing_errors:
        tags.append("M5_HARD_BLOCK_VIOLATED")
    if "SELL_NEAR_CANDLE_LOW" in existing_errors or "BUY_NEAR_CANDLE_HIGH" in existing_errors:
        tags.append("ENTRY_AFTER_EXTENSION")

    return ",".join(sorted(set(tags)))


def _tag_summary(df: pd.DataFrame, column: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if column not in df.columns:
        return []
    for _, row in df.iterrows():
        for tag in [x for x in str(row.get(column, "")).split(",") if x]:
            rows.append({
                "tag": tag,
                "net_profit": row.get("net_profit", 0.0),
                "is_loss": row.get("net_profit", 0.0) < 0,
                "mfe_points": row.get("mfe_points"),
                "mae_points": row.get("mae_points"),
                "post_exit_mfe_points": row.get("post_exit_mfe_points"),
            })
    if not rows:
        return []
    tag_df = pd.DataFrame(rows)
    out: List[Dict[str, Any]] = []
    for tag, group in tag_df.groupby("tag"):
        out.append({
            "tag": tag,
            "occurrences": int(len(group)),
            "loss_count": int(group["is_loss"].sum()),
            "net_profit": round(_safe_float(group["net_profit"].sum()), 2),
            "avg_profit": round(_safe_float(group["net_profit"].mean()), 2),
            "avg_mfe_points": round(_safe_float(group["mfe_points"].mean()), 5),
            "avg_mae_points": round(_safe_float(group["mae_points"].mean()), 5),
            "avg_post_exit_mfe_points": round(_safe_float(group["post_exit_mfe_points"].mean()), 5),
        })
    return sorted(out, key=lambda x: (x["net_profit"], -x["occurrences"]))[:30]


def _summarize(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"total_trades": 0, "message": "Nenhum trade para auditar."}
    total = int(len(df))
    wins = int((df["net_profit"] > 0).sum())
    losses = int((df["net_profit"] < 0).sum())
    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total, 4) if total else None,
        "net_profit": round(_safe_float(df["net_profit"].sum()), 2),
        "avg_mfe_points": round(_safe_float(df["mfe_points"].mean()), 5),
        "avg_mae_points": round(_safe_float(df["mae_points"].mean()), 5),
        "avg_post_exit_mfe_points": round(_safe_float(df["post_exit_mfe_points"].mean()), 5),
        "top_execution_quality_tags": _tag_summary(df, "execution_quality_tags"),
    }


def _write_outputs(df: pd.DataFrame, summary: Dict[str, Any], symbol: str, audit_dir: Path) -> None:
    out_dir = audit_dir / symbol.upper()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"personal_trade_execution_audit_{stamp}.csv"
    json_path = out_dir / f"personal_trade_execution_summary_{stamp}.json"
    latest_csv = out_dir / "personal_trade_execution_audit_latest.csv"
    latest_json = out_dir / "personal_trade_execution_summary_latest.json"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_csv(latest_csv, index=False, encoding="utf-8")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Execution CSV: {csv_path}")
    print(f"[OK] Execution Summary: {json_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    args = _args()
    data_symbol = args.data_symbol or args.symbol
    audit_dir = Path(args.audit_dir)
    data_dir = Path(args.data_dir)
    audit_csv = _find_audit_csv(args.symbol, audit_dir, args.audit_csv)
    context_path = _find_context_file(data_dir, data_symbol)

    print(f"[INFO] Audit CSV: {audit_csv}")
    print(f"[INFO] Contexto: {context_path}")
    trades = pd.read_csv(audit_csv)
    context = _load_context(context_path)
    m1 = _m1_frame(context)
    print(f"[INFO] Trades carregados: {len(trades)}")
    print(f"[INFO] Barras M1/contexto usadas: {len(m1)}")

    rows: List[Dict[str, Any]] = []
    for _, row in trades.iterrows():
        item = row.to_dict()
        metrics = _calc_mfe_mae_for_trade(row, m1, args.horizon_minutes, args.post_exit_minutes)
        item.update(metrics)
        item["execution_quality_tags"] = _classify_execution(item, args.mfe_good_points, args.stop_tight_ratio)
        rows.append(item)

    out = pd.DataFrame(rows)
    summary = _summarize(out)
    _write_outputs(out, summary, args.symbol, audit_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
