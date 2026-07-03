#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Personal Trade Auditor
======================

Audita o historico real de operacoes do MetaTrader 5 e cruza cada entrada com a
base intraday do TradingAgent.

Ponto importante:
- `--mt5-symbol` e o nome do ativo na conta/broker, ex.: XAUUSD.
- `--data-symbol` e o nome da base local do TradingAgent, ex.: GOLD.

Assim e possivel auditar uma conta onde o ouro aparece como XAUUSD usando a base
local `data/consolidated/GOLD_intraday.parquet`.

Uso recomendado:
    python tools/personal_trade_auditor.py ^
      --symbol GOLD ^
      --mt5-symbol XAUUSD ^
      --data-symbol GOLD ^
      --from-date 2026-07-01 ^
      --to-date 2026-07-01 ^
      --mt5-config config/personal_mt5.local.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


BRT_TZ = "America/Sao_Paulo"
DEFAULT_DATA_DIR = Path("data")
DEFAULT_OUTPUT_DIR = Path("data/personal_trade_auditor")


@dataclass
class AuditConfig:
    symbol: str
    mt5_symbol: str
    data_symbol: str
    from_date: str
    to_date: str
    mt5_path: Optional[str]
    mt5_account: Optional[int]
    mt5_password: Optional[str]
    mt5_server: Optional[str]
    data_dir: Path
    output_dir: Path
    lookback_minutes: int
    no_symbol_filter: bool


@dataclass
class TradeRecord:
    trade_id: str
    position_id: int
    mt5_symbol: str
    data_symbol: str
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


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audita trades reais do MT5 contra a base intraday do TradingAgent.")
    p.add_argument("--symbol", required=True, help="Alias operacional/logico, ex.: GOLD")
    p.add_argument("--mt5-symbol", default=None, help="Simbolo real no broker, ex.: XAUUSD")
    p.add_argument("--data-symbol", default=None, help="Simbolo da base local, ex.: GOLD")
    p.add_argument("--from-date", required=True, help="Data inicial YYYY-MM-DD ou datetime ISO")
    p.add_argument("--to-date", required=True, help="Data final YYYY-MM-DD ou datetime ISO")
    p.add_argument("--mt5-config", default=None, help="Arquivo local com credenciais MT5. Nao versionar.")
    p.add_argument("--mt5-path", default=None)
    p.add_argument("--mt5-account", type=int, default=None)
    p.add_argument("--mt5-password", default=None)
    p.add_argument("--mt5-password-env", default=None)
    p.add_argument("--mt5-server", default=None)
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    p.add_argument("--lookback-minutes", type=int, default=240)
    p.add_argument("--no-symbol-filter", action="store_true", help="Nao filtra deals por simbolo MT5")
    return p.parse_args()


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
    account = args.mt5_account or _nested_get(config, "mt5", "account")
    return AuditConfig(
        symbol=args.symbol,
        mt5_symbol=(args.mt5_symbol or _nested_get(config, "mt5", "symbol") or args.symbol),
        data_symbol=(args.data_symbol or _nested_get(config, "data", "symbol") or args.symbol),
        from_date=args.from_date,
        to_date=args.to_date,
        mt5_path=args.mt5_path or _nested_get(config, "mt5", "path"),
        mt5_account=int(account) if account is not None else None,
        mt5_password=_resolve_password(args, config),
        mt5_server=args.mt5_server or _nested_get(config, "mt5", "server"),
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        lookback_minutes=args.lookback_minutes,
        no_symbol_filter=bool(args.no_symbol_filter),
    )


def _parse_dt(value: str, end_of_day: bool = False) -> datetime:
    if "T" in value or " " in value:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(value)
        if end_of_day:
            dt = dt + timedelta(days=1)
    if dt.tzinfo is None:
        if ZoneInfo is not None:
            dt = dt.replace(tzinfo=ZoneInfo(BRT_TZ))
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    return None if dt is None else dt.astimezone(timezone.utc).isoformat()


def _dt_to_brt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if ZoneInfo is None:
        return dt.isoformat()
    return dt.astimezone(ZoneInfo(BRT_TZ)).strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _connect_mt5(cfg: AuditConfig):
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:
        raise RuntimeError("Biblioteca MetaTrader5 nao instalada. Instale com: pip install MetaTrader5") from exc

    kwargs: Dict[str, Any] = {}
    if cfg.mt5_path:
        kwargs["path"] = cfg.mt5_path

    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"Falha ao inicializar MT5: {mt5.last_error()}")

    if cfg.mt5_account and cfg.mt5_password and cfg.mt5_server:
        if not mt5.login(cfg.mt5_account, password=cfg.mt5_password, server=cfg.mt5_server):
            err = mt5.last_error()
            mt5.shutdown()
            raise RuntimeError(f"Falha ao logar no MT5: {err}")

    info = mt5.account_info()
    if info:
        d = info._asdict()
        print(f"[INFO] Conta logada: login={d.get('login')} server={d.get('server')} balance={d.get('balance')}")
    return mt5


def _fetch_deals(cfg: AuditConfig) -> pd.DataFrame:
    start_utc = _parse_dt(cfg.from_date, end_of_day=False)
    end_utc = _parse_dt(cfg.to_date, end_of_day=True)
    print(f"[INFO] Intervalo UTC: {start_utc.isoformat()} -> {end_utc.isoformat()}")

    mt5 = _connect_mt5(cfg)
    try:
        raw = mt5.history_deals_get(start_utc, end_utc)
        if raw is None:
            raise RuntimeError(f"history_deals_get retornou None: {mt5.last_error()}")
        rows = [x._asdict() for x in raw]
    finally:
        mt5.shutdown()

    df = pd.DataFrame(rows)
    print(f"[INFO] Deals brutas no periodo: {len(df)}")
    if df.empty:
        return df

    if "time" in df.columns:
        df["time_utc"] = pd.to_datetime(df["time"], unit="s", utc=True, errors="coerce")
    elif "time_msc" in df.columns:
        df["time_utc"] = pd.to_datetime(df["time_msc"], unit="ms", utc=True, errors="coerce")

    if "symbol" in df.columns:
        counts = df["symbol"].fillna("").astype(str).value_counts().head(20)
        print("[INFO] Deals por simbolo:")
        print(counts.to_string())
        if not cfg.no_symbol_filter:
            before = len(df)
            df = df[df["symbol"].astype(str).str.upper() == cfg.mt5_symbol.upper()].copy()
            print(f"[INFO] Filtro mt5_symbol={cfg.mt5_symbol}: {before} -> {len(df)} deals")

    return df.sort_values("time_utc") if "time_utc" in df.columns else df


def _deal_side(row: pd.Series) -> str:
    # MT5 comum: DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1.
    try:
        value = int(row.get("type", -1))
        if value == 0:
            return "BUY"
        if value == 1:
            return "SELL"
    except Exception:
        pass
    text = str(row.get("type", "")).upper()
    if "BUY" in text:
        return "BUY"
    if "SELL" in text:
        return "SELL"
    return "UNKNOWN"


def _is_entry_in(row: pd.Series) -> bool:
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
    deals = deals.copy()
    if "position_id" not in deals.columns:
        deals["position_id"] = deals.get("position", deals.index)

    records: List[TradeRecord] = []
    for position_id, group in deals.groupby("position_id", dropna=False):
        group = group.sort_values("time_utc")
        if int(position_id) == 0 if pd.notna(position_id) else False:
            # Transferencias/balanco geralmente usam position_id zero.
            continue

        entries = group[group.apply(_is_entry_in, axis=1)]
        exits = group[group.apply(_is_entry_out, axis=1)]
        if entries.empty:
            entries = group[group.apply(lambda r: _deal_side(r) in ("BUY", "SELL"), axis=1)]
        if entries.empty:
            continue

        entry = entries.iloc[0]
        exit_row = exits.iloc[-1] if len(exits) else (group.iloc[-1] if len(group) > 1 else None)
        entry_dt = pd.Timestamp(entry.get("time_utc")).to_pydatetime()
        exit_dt = None
        if exit_row is not None and pd.notna(exit_row.get("time_utc")):
            exit_dt = pd.Timestamp(exit_row.get("time_utc")).to_pydatetime()

        profit = _safe_float(group.get("profit", pd.Series(dtype=float)).sum())
        commission = _safe_float(group.get("commission", pd.Series(dtype=float)).sum())
        swap = _safe_float(group.get("swap", pd.Series(dtype=float)).sum())
        duration = None if exit_dt is None else (exit_dt - entry_dt).total_seconds() / 60.0

        mt5_symbol = str(entry.get("symbol", cfg.mt5_symbol) or cfg.mt5_symbol)
        record = TradeRecord(
            trade_id=f"{cfg.symbol}-{int(position_id) if pd.notna(position_id) else len(records)}",
            position_id=int(position_id) if pd.notna(position_id) else -1,
            mt5_symbol=mt5_symbol,
            data_symbol=cfg.data_symbol,
            side=_deal_side(entry),
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
            net_profit=profit + commission + swap,
            duration_minutes=duration,
            comment=str(entry.get("comment", "") or ""),
            magic=int(_safe_float(entry.get("magic"), 0)),
        )
        records.append(record)

    if not records:
        return pd.DataFrame()
    return pd.DataFrame([asdict(x) for x in records]).sort_values("entry_time_utc")


def _find_context_file(cfg: AuditConfig) -> Optional[Path]:
    candidates = [
        cfg.data_dir / "consolidated" / f"{cfg.data_symbol}_intraday.parquet",
        cfg.data_dir / "consolidated" / f"{cfg.data_symbol.upper()}_intraday.parquet",
        cfg.data_dir / "consolidated" / f"{cfg.data_symbol.capitalize()}_intraday.parquet",
    ]
    return next((p for p in candidates if p.exists()), None)


def _load_context(cfg: AuditConfig) -> Optional[pd.DataFrame]:
    path = _find_context_file(cfg)
    if path is None:
        print(f"[WARN] Consolidado intraday nao encontrado para data_symbol={cfg.data_symbol}")
        return None
    print(f"[INFO] Contexto usado: {path}")
    df = pd.read_parquet(path)
    df.columns = [str(c) for c in df.columns]

    time_col = next((c for c in ("time_utc", "datetime_utc", "timestamp_utc", "time", "datetime", "timestamp", "time_brt") if c in df.columns), None)
    if time_col is None:
        print("[WARN] Contexto sem coluna de tempo reconhecida.")
        return None

    if time_col == "time_brt" and ZoneInfo is not None:
        df["context_time_utc"] = pd.to_datetime(df[time_col], errors="coerce").dt.tz_localize(
            BRT_TZ, nonexistent="shift_forward", ambiguous="NaT"
        ).dt.tz_convert("UTC")
    else:
        df["context_time_utc"] = pd.to_datetime(df[time_col], errors="coerce", utc=True)

    tf_col = next((c for c in ("timeframe", "tf", "period") if c in df.columns), None)
    df["context_timeframe"] = df[tf_col].astype(str).str.upper() if tf_col else "UNKNOWN"
    return df.dropna(subset=["context_time_utc"]).sort_values("context_time_utc")


def _context_before(df: pd.DataFrame, entry_time_utc: str, tf: str, lookback_minutes: int) -> Dict[str, Any]:
    if df is None or df.empty:
        return {}
    entry_ts = pd.to_datetime(entry_time_utc, utc=True)
    frame = df
    if "context_timeframe" in frame.columns and (frame["context_timeframe"] != "UNKNOWN").any():
        frame = frame[frame["context_timeframe"] == tf]
    if frame.empty:
        return {}
    min_ts = entry_ts - pd.Timedelta(minutes=lookback_minutes)
    frame = frame[(frame["context_time_utc"] <= entry_ts) & (frame["context_time_utc"] >= min_ts)]
    if frame.empty:
        return {}
    row = frame.iloc[-1]
    keep = [
        "context_time_utc", "context_timeframe", "open", "high", "low", "close", "tick_volume", "spread", "spread_z",
        "RSI", "MACD", "MACD_signal", "MACD_hist", "ATR", "ADX", "EMA_20", "EMA_50", "SMA_10", "SMA_50",
        "body_direction", "structure_state", "volume_ratio", "volume_pace_ratio", "range_atr", "body_atr", "close_pos",
        "ema20_slope_5", "ema50_slope_5", "dist_ema20_atr", "dist_ema50_atr",
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


def _bias(value: Any) -> Optional[str]:
    try:
        v = float(value)
        if v > 0:
            return "UP"
        if v < 0:
            return "DOWN"
    except Exception:
        t = str(value).upper()
        if "BULL" in t or t == "UP":
            return "UP"
        if "BEAR" in t or t == "DOWN":
            return "DOWN"
    return None


def _side_dir(side: str) -> Optional[str]:
    side = side.upper()
    if side == "BUY":
        return "UP"
    if side == "SELL":
        return "DOWN"
    return None


def _classify(row: Dict[str, Any]) -> Dict[str, Any]:
    tags: List[str] = []
    warnings: List[str] = []
    side_dir = _side_dir(str(row.get("side", "")))

    for tf in ("H1", "M15"):
        b = _bias(row.get(f"{tf}_structure_state"))
        if side_dir and b and side_dir != b:
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

    net = _safe_float(row.get("net_profit"))
    return {
        "result_quality": "WIN" if net > 0 else ("LOSS" if net < 0 else "FLAT"),
        "error_tags": ",".join(sorted(set(tags))),
        "warning_tags": ",".join(sorted(set(warnings))),
        "error_tag_count": len(set(tags)),
    }


def _enrich(trades: pd.DataFrame, context: Optional[pd.DataFrame], cfg: AuditConfig) -> pd.DataFrame:
    if trades.empty:
        return trades
    rows: List[Dict[str, Any]] = []
    for _, trade in trades.iterrows():
        item = trade.to_dict()
        if context is not None:
            for tf in ("H1", "M15", "M5", "M1"):
                item.update(_context_before(context, trade["entry_time_utc"], tf, cfg.lookback_minutes))
        item.update(_classify(item))
        rows.append(item)
    return pd.DataFrame(rows)


def _summarize(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"total_trades": 0, "message": "Nenhum trade encontrado."}

    total = int(len(df))
    wins = int((df["net_profit"] > 0).sum())
    losses = int((df["net_profit"] < 0).sum())
    flats = total - wins - losses
    gross_profit = _safe_float(df.loc[df["net_profit"] > 0, "net_profit"].sum())
    gross_loss = abs(_safe_float(df.loc[df["net_profit"] < 0, "net_profit"].sum()))
    pf = None if gross_loss == 0 else gross_profit / gross_loss

    tag_rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        for tag in [x for x in str(row.get("error_tags", "")).split(",") if x]:
            tag_rows.append({"tag": tag, "net_profit": row.get("net_profit", 0.0), "is_loss": row.get("net_profit", 0.0) < 0})

    top_tags: List[Dict[str, Any]] = []
    if tag_rows:
        tag_df = pd.DataFrame(tag_rows)
        for tag, group in tag_df.groupby("tag"):
            top_tags.append({
                "tag": tag,
                "occurrences": int(len(group)),
                "loss_count": int(group["is_loss"].sum()),
                "net_profit": round(_safe_float(group["net_profit"].sum()), 2),
                "avg_profit": round(_safe_float(group["net_profit"].mean()), 2),
            })
        top_tags = sorted(top_tags, key=lambda x: (x["net_profit"], -x["occurrences"]))[:20]

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": round(wins / total, 4),
        "net_profit": round(_safe_float(df["net_profit"].sum()), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": None if pf is None else round(pf, 4),
        "top_error_tags": top_tags,
    }


def _write(df: pd.DataFrame, summary: Dict[str, Any], cfg: AuditConfig) -> None:
    out_dir = cfg.output_dir / cfg.symbol.upper()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"personal_trade_audit_{stamp}.csv"
    json_path = out_dir / f"personal_trade_audit_summary_{stamp}.json"
    latest_csv = out_dir / "personal_trade_audit_latest.csv"
    latest_json = out_dir / "personal_trade_audit_summary_latest.json"

    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_csv(latest_csv, index=False, encoding="utf-8")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] Trades auditados: {len(df)}")
    print(f"[OK] CSV: {csv_path}")
    print(f"[OK] Summary: {json_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    args = _args()
    cfg = _build_config(args)

    if not cfg.mt5_account:
        print("[ERRO] Conta MT5 nao informada.", file=sys.stderr)
        return 2
    if not cfg.mt5_password:
        print("[ERRO] Senha MT5 nao informada. Use --mt5-password-env ou mt5.password_env.", file=sys.stderr)
        return 2
    if not cfg.mt5_server:
        print("[ERRO] Servidor MT5 nao informado.", file=sys.stderr)
        return 2

    print(
        f"[INFO] Auditor iniciado | symbol={cfg.symbol} | mt5_symbol={cfg.mt5_symbol} | "
        f"data_symbol={cfg.data_symbol} | from={cfg.from_date} | to={cfg.to_date}"
    )
    deals = _fetch_deals(cfg)
    trades = _reconstruct_trades(deals, cfg)
    print(f"[INFO] Trades reconstruidos: {len(trades)}")

    context = _load_context(cfg)
    if context is not None:
        print(f"[INFO] Contexto intraday carregado: {len(context)} linhas")

    audited = _enrich(trades, context, cfg)
    summary = _summarize(audited)
    _write(audited, summary, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
