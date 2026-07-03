#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Personal Trade Auditor
======================

Audita o historico real de operacoes do MetaTrader 5 e cruza cada entrada com
contexto intraday ja existente no TradingAgent.

Objetivos:
- usar outra conta/senha/path do MT5 sem mexer no tradingagent.json principal;
- importar historico de trades diretamente da conta;
- reconstruir operacoes por position_id;
- enriquecer cada trade com contexto H1/M15/M5/M1 mais proximo da entrada;
- classificar erros recorrentes com regras simples;
- gerar relatorios CSV/JSON para evoluir depois em Personal Risk Guard.

Seguranca:
- nao hardcode credenciais neste arquivo;
- prefira variaveis de ambiente ou um arquivo local ignorado pelo Git;
- nunca versione senha, conta real, servidor privado ou historico operacional.

Exemplo:
    python tools/personal_trade_auditor.py ^
      --symbol GOLD ^
      --from-date 2026-07-01 ^
      --to-date 2026-07-02 ^
      --mt5-config config/personal_mt5.local.json

Arquivo local sugerido, nao versionar:
{
  "mt5": {
    "path": "C:/Program Files/MetaTrader 5/terminal64.exe",
    "account": 123456,
    "server": "Broker-Server",
    "password_env": "MT5_PERSONAL_PASSWORD",
    "broker_timezone": "Etc/GMT-2"
  }
}
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


BRT_TZ = "America/Sao_Paulo"
DEFAULT_OUTPUT_DIR = Path("data/personal_trade_auditor")
DEFAULT_DATA_DIR = Path("data")


@dataclass
class AuditConfig:
    symbol: str
    from_date: str
    to_date: str
    mt5_path: Optional[str]
    mt5_account: Optional[int]
    mt5_password: Optional[str]
    mt5_server: Optional[str]
    broker_timezone: str
    data_dir: Path
    output_dir: Path
    lookback_minutes: int
    include_open_positions: bool


@dataclass
class ReconstructedTrade:
    trade_id: str
    position_id: int
    symbol: str
    side: str
    entry_time_utc: str
    entry_time_brt: str
    entry_price: float
    exit_time_utc: Optional[str]
    exit_time_brt: Optional[str]
    exit_price: Optional[float]
    volume: float
    profit: float
    commission: float
    swap: float
    net_profit: float
    duration_minutes: Optional[float]
    comment: str
    magic: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audita trades reais do MT5 e cruza com contexto intraday do TradingAgent."
    )
    parser.add_argument("--symbol", required=True, help="Simbolo do ativo, ex.: GOLD")
    parser.add_argument("--from-date", required=True, help="Data inicial YYYY-MM-DD ou datetime ISO")
    parser.add_argument("--to-date", required=True, help="Data final YYYY-MM-DD ou datetime ISO")
    parser.add_argument("--mt5-config", default=None, help="Arquivo local com credenciais MT5. Nao versionar.")
    parser.add_argument("--mt5-path", default=None, help="Path do terminal64.exe da conta a auditar")
    parser.add_argument("--mt5-account", type=int, default=None, help="Numero da conta MT5")
    parser.add_argument("--mt5-password", default=None, help="Senha MT5. Prefira variavel de ambiente.")
    parser.add_argument("--mt5-password-env", default=None, help="Nome da variavel de ambiente com a senha")
    parser.add_argument("--mt5-server", default=None, help="Servidor MT5")
    parser.add_argument("--broker-timezone", default=None, help="Timezone do broker, ex.: Etc/GMT-2")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Diretorio data do TradingAgent")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Diretorio de saida")
    parser.add_argument("--lookback-minutes", type=int, default=240, help="Janela maxima para contexto anterior")
    parser.add_argument("--include-open-positions", action="store_true", help="Inclui posicoes abertas, quando possivel")
    return parser.parse_args()


def _load_json(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo de configuracao nao encontrado: {p}")
    with p.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _nested_get(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _resolve_password(args: argparse.Namespace, config: Dict[str, Any]) -> Optional[str]:
    if args.mt5_password:
        return args.mt5_password
    env_name = args.mt5_password_env or _nested_get(config, "mt5", "password_env")
    if env_name:
        return os.environ.get(str(env_name))
    return _nested_get(config, "mt5", "password")


def _build_config(args: argparse.Namespace) -> AuditConfig:
    config = _load_json(args.mt5_config)
    mt5_account = args.mt5_account or _nested_get(config, "mt5", "account")
    if mt5_account is not None:
        mt5_account = int(mt5_account)

    return AuditConfig(
        symbol=args.symbol,
        from_date=args.from_date,
        to_date=args.to_date,
        mt5_path=args.mt5_path or _nested_get(config, "mt5", "path"),
        mt5_account=mt5_account,
        mt5_password=_resolve_password(args, config),
        mt5_server=args.mt5_server or _nested_get(config, "mt5", "server"),
        broker_timezone=args.broker_timezone or _nested_get(config, "mt5", "broker_timezone", default="Etc/GMT-2"),
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        lookback_minutes=args.lookback_minutes,
        include_open_positions=bool(args.include_open_positions),
    )


def _parse_dt(value: str, tz_name: str = BRT_TZ, end_of_day: bool = False) -> datetime:
    if "T" in value or " " in value:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(value)
        if end_of_day:
            dt = dt + timedelta(days=1)
    if dt.tzinfo is None:
        if ZoneInfo is not None:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name))
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _dt_to_brt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if ZoneInfo is None:
        return dt.isoformat()
    return dt.astimezone(ZoneInfo(BRT_TZ)).strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return default
        return float(value)
    except Exception:
        return default


def _connect_mt5(cfg: AuditConfig):
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Biblioteca MetaTrader5 nao instalada. Instale com: pip install MetaTrader5"
        ) from exc

    init_kwargs: Dict[str, Any] = {}
    if cfg.mt5_path:
        init_kwargs["path"] = cfg.mt5_path

    if not mt5.initialize(**init_kwargs):
        code, msg = mt5.last_error()
        raise RuntimeError(f"Falha ao inicializar MT5: {code} {msg}")

    if cfg.mt5_account and cfg.mt5_password and cfg.mt5_server:
        if not mt5.login(cfg.mt5_account, password=cfg.mt5_password, server=cfg.mt5_server):
            code, msg = mt5.last_error()
            mt5.shutdown()
            raise RuntimeError(f"Falha ao logar no MT5: {code} {msg}")

    return mt5


def _fetch_deals(cfg: AuditConfig) -> pd.DataFrame:
    start_utc = _parse_dt(cfg.from_date, end_of_day=False)
    end_utc = _parse_dt(cfg.to_date, end_of_day=True)
    mt5 = _connect_mt5(cfg)
    try:
        raw = mt5.history_deals_get(start_utc, end_utc)
        if raw is None:
            code, msg = mt5.last_error()
            raise RuntimeError(f"history_deals_get retornou None: {code} {msg}")
        rows = [deal._asdict() for deal in raw]
    finally:
        mt5.shutdown()

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    if "symbol" in df.columns:
        df = df[df["symbol"].astype(str).str.upper() == cfg.symbol.upper()].copy()

    if "time" in df.columns:
        df["time_utc"] = pd.to_datetime(df["time"], unit="s", utc=True, errors="coerce")
    elif "time_msc" in df.columns:
        df["time_utc"] = pd.to_datetime(df["time_msc"], unit="ms", utc=True, errors="coerce")

    return df.sort_values("time_utc") if "time_utc" in df.columns else df


def _deal_side(row: pd.Series) -> str:
    # MT5: DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1. Mantemos fallback textual.
    value = row.get("type")
    try:
        ivalue = int(value)
        if ivalue == 0:
            return "BUY"
        if ivalue == 1:
            return "SELL"
    except Exception:
        pass
    text = str(value).upper()
    if "BUY" in text:
        return "BUY"
    if "SELL" in text:
        return "SELL"
    return "UNKNOWN"


def _is_entry_in(row: pd.Series) -> bool:
    # MT5: DEAL_ENTRY_IN=0, OUT=1, INOUT=2, OUT_BY=3.
    try:
        return int(row.get("entry", -1)) == 0
    except Exception:
        return False


def _is_entry_out(row: pd.Series) -> bool:
    try:
        return int(row.get("entry", -1)) in (1, 2, 3)
    except Exception:
        return False


def _reconstruct_trades(deals: pd.DataFrame, cfg: AuditConfig) -> pd.DataFrame:
    if deals.empty:
        return pd.DataFrame()

    if "position_id" not in deals.columns:
        deals["position_id"] = deals.get("position", deals.index)

    trades: List[ReconstructedTrade] = []
    for position_id, group in deals.groupby("position_id", dropna=False):
        group = group.sort_values("time_utc")
        entry_rows = group[group.apply(_is_entry_in, axis=1)]
        exit_rows = group[group.apply(_is_entry_out, axis=1)]

        if entry_rows.empty:
            # Fallback: primeira deal BUY/SELL com volume positivo.
            entry_rows = group[group.apply(lambda r: _deal_side(r) in ("BUY", "SELL"), axis=1)]
        if entry_rows.empty:
            continue

        entry = entry_rows.iloc[0]
        exits = exit_rows if not exit_rows.empty else group.iloc[1:]
        exit_row = exits.iloc[-1] if len(exits) else None

        entry_time = entry.get("time_utc")
        exit_time = None if exit_row is None else exit_row.get("time_utc")
        if pd.isna(entry_time):
            continue
        entry_dt = pd.Timestamp(entry_time).to_pydatetime()
        exit_dt = None if exit_time is None or pd.isna(exit_time) else pd.Timestamp(exit_time).to_pydatetime()

        side = _deal_side(entry)
        profit = _safe_float(group.get("profit", pd.Series(dtype=float)).sum())
        commission = _safe_float(group.get("commission", pd.Series(dtype=float)).sum())
        swap = _safe_float(group.get("swap", pd.Series(dtype=float)).sum())
        net_profit = profit + commission + swap
        duration = None
        if exit_dt:
            duration = (exit_dt - entry_dt).total_seconds() / 60.0

        trade = ReconstructedTrade(
            trade_id=f"{cfg.symbol}-{int(position_id) if pd.notna(position_id) else len(trades)}",
            position_id=int(position_id) if pd.notna(position_id) else -1,
            symbol=cfg.symbol,
            side=side,
            entry_time_utc=_dt_to_iso(entry_dt) or "",
            entry_time_brt=_dt_to_brt(entry_dt) or "",
            entry_price=_safe_float(entry.get("price")),
            exit_time_utc=_dt_to_iso(exit_dt),
            exit_time_brt=_dt_to_brt(exit_dt),
            exit_price=None if exit_row is None else _safe_float(exit_row.get("price")),
            volume=_safe_float(entry.get("volume")),
            profit=profit,
            commission=commission,
            swap=swap,
            net_profit=net_profit,
            duration_minutes=duration,
            comment=str(entry.get("comment", "") or ""),
            magic=int(_safe_float(entry.get("magic"), 0)),
        )
        trades.append(trade)

    return pd.DataFrame([asdict(t) for t in trades]).sort_values("entry_time_utc")


def _load_intraday_context(cfg: AuditConfig) -> Optional[pd.DataFrame]:
    candidates = [
        cfg.data_dir / "consolidated" / f"{cfg.symbol}_intraday.parquet",
        cfg.data_dir / "consolidated" / f"{cfg.symbol.upper()}_intraday.parquet",
        cfg.data_dir / "consolidated" / f"{cfg.symbol.capitalize()}_intraday.parquet",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return None

    df = pd.read_parquet(path)
    df.columns = [str(c) for c in df.columns]

    # Normalizacao flexivel de tempo.
    time_col = None
    for candidate in ("time_utc", "datetime_utc", "timestamp_utc", "time", "datetime", "timestamp", "time_brt"):
        if candidate in df.columns:
            time_col = candidate
            break
    if time_col is None:
        return None

    if time_col == "time_brt":
        if ZoneInfo is not None:
            df["context_time_utc"] = pd.to_datetime(df[time_col], errors="coerce").dt.tz_localize(
                BRT_TZ, nonexistent="shift_forward", ambiguous="NaT"
            ).dt.tz_convert("UTC")
        else:
            df["context_time_utc"] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
    else:
        df["context_time_utc"] = pd.to_datetime(df[time_col], errors="coerce", utc=True)

    tf_col = None
    for candidate in ("timeframe", "tf", "period"):
        if candidate in df.columns:
            tf_col = candidate
            break
    if tf_col:
        df["context_timeframe"] = df[tf_col].astype(str).str.upper()
    else:
        df["context_timeframe"] = "UNKNOWN"

    return df.dropna(subset=["context_time_utc"]).sort_values("context_time_utc")


def _latest_context_before(df: pd.DataFrame, entry_time_utc: str, tf: str, lookback_minutes: int) -> Dict[str, Any]:
    if df is None or df.empty:
        return {}
    entry_ts = pd.to_datetime(entry_time_utc, utc=True)
    frame = df
    if "context_timeframe" in frame.columns and (frame["context_timeframe"] != "UNKNOWN").any():
        frame = frame[frame["context_timeframe"] == tf.upper()]
    if frame.empty:
        return {}
    min_ts = entry_ts - pd.Timedelta(minutes=lookback_minutes)
    frame = frame[(frame["context_time_utc"] <= entry_ts) & (frame["context_time_utc"] >= min_ts)]
    if frame.empty:
        return {}
    row = frame.iloc[-1]
    keep = [
        "context_time_utc", "context_timeframe", "open", "high", "low", "close", "tick_volume", "spread",
        "RSI", "MACD", "MACD_signal", "MACD_hist", "ATR", "ADX", "EMA_20", "EMA_50", "SMA_10", "SMA_50",
        "body_direction", "structure_state", "volume_ratio", "volume_pace_ratio", "range_atr", "body_atr",
        "close_pos", "ema20_slope_5", "ema50_slope_5", "dist_ema20_atr", "dist_ema50_atr",
        "breakout_up", "breakout_down", "false_breakout_up", "false_breakout_down", "sweep_high", "sweep_low",
        "bos_up", "bos_dn", "choch_up", "choch_dn", "Volume_Spike", "vol_spike_1p5", "vol_spike_2p0",
        "session_name",
    ]
    out: Dict[str, Any] = {}
    for col in keep:
        if col in row.index:
            value = row[col]
            if isinstance(value, pd.Timestamp):
                value = value.isoformat()
            elif pd.isna(value):
                value = None
            out[f"{tf}_{col}"] = value
    return out


def _enrich_trades(trades: pd.DataFrame, context: Optional[pd.DataFrame], cfg: AuditConfig) -> pd.DataFrame:
    if trades.empty:
        return trades
    rows: List[Dict[str, Any]] = []
    for _, trade in trades.iterrows():
        item = trade.to_dict()
        if context is not None:
            for tf in ("H1", "M15", "M5", "M1"):
                item.update(_latest_context_before(context, trade["entry_time_utc"], tf, cfg.lookback_minutes))
        item.update(_classify_trade_errors(item))
        rows.append(item)
    return pd.DataFrame(rows)


def _bias_from_structure(value: Any) -> Optional[str]:
    try:
        v = float(value)
        if v > 0:
            return "UP"
        if v < 0:
            return "DOWN"
    except Exception:
        text = str(value).upper()
        if "BULL" in text or text == "UP":
            return "UP"
        if "BEAR" in text or text == "DOWN":
            return "DOWN"
    return None


def _side_to_direction(side: str) -> Optional[str]:
    if side == "BUY":
        return "UP"
    if side == "SELL":
        return "DOWN"
    return None


def _classify_trade_errors(row: Dict[str, Any]) -> Dict[str, Any]:
    tags: List[str] = []
    warnings: List[str] = []
    side_dir = _side_to_direction(str(row.get("side", "")).upper())
    net = _safe_float(row.get("net_profit"))

    # Contexto por timeframe.
    for tf in ("H1", "M15"):
        bias = _bias_from_structure(row.get(f"{tf}_structure_state"))
        if side_dir and bias and side_dir != bias:
            tags.append(f"COUNTER_{tf}")

    m5_volume = _safe_float(row.get("M5_volume_ratio"), default=float("nan"))
    if not math.isnan(m5_volume) and m5_volume < 0.70:
        tags.append("LOW_VOLUME_ENTRY")

    m5_range = _safe_float(row.get("M5_range_atr"), default=float("nan"))
    if not math.isnan(m5_range) and m5_range > 1.20:
        tags.append("AFTER_LONG_M5_CANDLE")

    m5_spread_z = _safe_float(row.get("M5_spread_z"), default=float("nan"))
    if not math.isnan(m5_spread_z) and m5_spread_z > 2.0:
        tags.append("HIGH_SPREAD_ENTRY")

    close_pos = _safe_float(row.get("M5_close_pos"), default=float("nan"))
    if side_dir == "UP" and not math.isnan(close_pos) and close_pos > 0.85:
        tags.append("BUY_NEAR_CANDLE_HIGH")
    if side_dir == "DOWN" and not math.isnan(close_pos) and close_pos < 0.15:
        tags.append("SELL_NEAR_CANDLE_LOW")

    if _safe_float(row.get("M5_vol_spike_1p5")) == 0 and _safe_float(row.get("M5_breakout_up")) == 1:
        warnings.append("BREAKOUT_UP_WITHOUT_VOLUME_SPIKE")
    if _safe_float(row.get("M5_vol_spike_1p5")) == 0 and _safe_float(row.get("M5_breakout_down")) == 1:
        warnings.append("BREAKOUT_DOWN_WITHOUT_VOLUME_SPIKE")

    if net < 0:
        quality = "LOSS"
    elif net > 0:
        quality = "WIN"
    else:
        quality = "FLAT"

    return {
        "result_quality": quality,
        "error_tags": ",".join(sorted(set(tags))),
        "warning_tags": ",".join(sorted(set(warnings))),
        "error_tag_count": len(set(tags)),
    }


def _summarize(audited: pd.DataFrame) -> Dict[str, Any]:
    if audited.empty:
        return {"total_trades": 0, "message": "Nenhum trade encontrado."}

    total = int(len(audited))
    wins = int((audited["net_profit"] > 0).sum())
    losses = int((audited["net_profit"] < 0).sum())
    flats = total - wins - losses
    net = _safe_float(audited["net_profit"].sum())
    gross_profit = _safe_float(audited.loc[audited["net_profit"] > 0, "net_profit"].sum())
    gross_loss = abs(_safe_float(audited.loc[audited["net_profit"] < 0, "net_profit"].sum()))
    profit_factor = None if gross_loss == 0 else gross_profit / gross_loss

    tag_rows: List[Dict[str, Any]] = []
    for _, row in audited.iterrows():
        tags = [t for t in str(row.get("error_tags", "")).split(",") if t]
        for tag in tags:
            tag_rows.append({"tag": tag, "net_profit": row.get("net_profit", 0.0), "is_loss": row.get("net_profit", 0.0) < 0})

    if tag_rows:
        tag_df = pd.DataFrame(tag_rows)
        by_tag = []
        for tag, g in tag_df.groupby("tag"):
            by_tag.append(
                {
                    "tag": tag,
                    "occurrences": int(len(g)),
                    "loss_count": int(g["is_loss"].sum()),
                    "net_profit": round(_safe_float(g["net_profit"].sum()), 2),
                    "avg_profit": round(_safe_float(g["net_profit"].mean()), 2),
                }
            )
        top_error_tags = sorted(by_tag, key=lambda x: (x["net_profit"], -x["occurrences"]))[:20]
    else:
        top_error_tags = []

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": round(wins / total, 4) if total else None,
        "net_profit": round(net, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": None if profit_factor is None else round(profit_factor, 4),
        "top_error_tags": top_error_tags,
    }


def _write_outputs(audited: pd.DataFrame, summary: Dict[str, Any], cfg: AuditConfig) -> None:
    out_dir = cfg.output_dir / cfg.symbol.upper()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    audited_path = out_dir / f"personal_trade_audit_{stamp}.csv"
    summary_path = out_dir / f"personal_trade_audit_summary_{stamp}.json"
    latest_audited = out_dir / "personal_trade_audit_latest.csv"
    latest_summary = out_dir / "personal_trade_audit_summary_latest.json"

    audited.to_csv(audited_path, index=False, encoding="utf-8")
    audited.to_csv(latest_audited, index=False, encoding="utf-8")
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with latest_summary.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[OK] Trades auditados: {len(audited)}")
    print(f"[OK] CSV: {audited_path}")
    print(f"[OK] Summary: {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    args = _parse_args()
    cfg = _build_config(args)

    if not cfg.mt5_account:
        print("[ERRO] Conta MT5 nao informada. Use --mt5-account ou mt5.account no arquivo local.", file=sys.stderr)
        return 2
    if not cfg.mt5_password:
        print("[ERRO] Senha MT5 nao informada. Use --mt5-password-env ou mt5.password_env.", file=sys.stderr)
        return 2
    if not cfg.mt5_server:
        print("[ERRO] Servidor MT5 nao informado. Use --mt5-server ou mt5.server.", file=sys.stderr)
        return 2

    print(f"[INFO] Auditor iniciado | symbol={cfg.symbol} | from={cfg.from_date} | to={cfg.to_date}")
    deals = _fetch_deals(cfg)
    print(f"[INFO] Deals carregadas: {len(deals)}")

    trades = _reconstruct_trades(deals, cfg)
    print(f"[INFO] Trades reconstruidos: {len(trades)}")

    context = _load_intraday_context(cfg)
    if context is None:
        print("[WARN] Consolidado intraday nao encontrado ou sem coluna de tempo. Auditoria seguira sem contexto de mercado.")
    else:
        print(f"[INFO] Contexto intraday carregado: {len(context)} linhas")

    audited = _enrich_trades(trades, context, cfg)
    summary = _summarize(audited)
    _write_outputs(audited, summary, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
