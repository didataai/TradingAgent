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

A V2 adiciona leitura operacional do regime no momento da entrada:
- janelas provaveis de rompimento;
- volume/energia no M5;
- fade de rompimento real;
- compra em resistencia / venda em suporte;
- compra em suporte / venda em resistencia;
- M5 liberado/bloqueado conforme regra operacional do Diego.

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
from typing import Any, Dict, List, Optional, Tuple

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
    zone_window_bars: int
    zone_tolerance_atr: float


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
    p.add_argument("--zone-window-bars", type=int, default=48, help="Barras anteriores do M5 para suporte/resistencia local")
    p.add_argument("--zone-tolerance-atr", type=float, default=0.25, help="Tolerancia em ATR para perto de suporte/resistencia")
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
        zone_window_bars=args.zone_window_bars,
        zone_tolerance_atr=args.zone_tolerance_atr,
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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return default
        return int(value)
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
        if pd.notna(position_id) and _safe_int(position_id) == 0:
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
        records.append(
            TradeRecord(
                trade_id=f"{cfg.symbol}-{_safe_int(position_id, len(records))}",
                position_id=_safe_int(position_id, -1),
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
                magic=_safe_int(entry.get("magic"), 0),
            )
        )

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


def _frame_for_tf(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if "context_timeframe" in df.columns and (df["context_timeframe"] != "UNKNOWN").any():
        return df[df["context_timeframe"] == tf.upper()].copy()
    return df.copy()


def _context_slice_before(df: pd.DataFrame, entry_time_utc: str, tf: str, lookback_minutes: int) -> pd.DataFrame:
    frame = _frame_for_tf(df, tf)
    if frame.empty:
        return frame
    entry_ts = pd.to_datetime(entry_time_utc, utc=True)
    min_ts = entry_ts - pd.Timedelta(minutes=lookback_minutes)
    return frame[(frame["context_time_utc"] <= entry_ts) & (frame["context_time_utc"] >= min_ts)].copy()


def _context_before(df: pd.DataFrame, entry_time_utc: str, tf: str, lookback_minutes: int) -> Dict[str, Any]:
    frame = _context_slice_before(df, entry_time_utc, tf, lookback_minutes)
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


def _entry_hour_brt(entry_time_utc: str) -> Tuple[int, int]:
    ts = pd.to_datetime(entry_time_utc, utc=True)
    if ZoneInfo is not None:
        ts = ts.tz_convert(BRT_TZ)
    return int(ts.hour), int(ts.minute)


def _in_minutes(hour: int, minute: int) -> int:
    return hour * 60 + minute


def _time_window_tag(entry_time_utc: str) -> str:
    hour, minute = _entry_hour_brt(entry_time_utc)
    cur = _in_minutes(hour, minute)
    if _in_minutes(9, 0) <= cur <= _in_minutes(10, 0):
        return "TIME_BREAKOUT_WINDOW_09_10"
    if _in_minutes(12, 30) <= cur <= _in_minutes(13, 30):
        return "TIME_BREAKOUT_WINDOW_1230_1330"
    return "TIME_RANGE_OR_LOWER_CONTINUATION_WINDOW"


def _nearest_zone_from_m5(context: Optional[pd.DataFrame], entry_time_utc: str, cfg: AuditConfig) -> Dict[str, Any]:
    if context is None or context.empty:
        return {}
    m5 = _context_slice_before(context, entry_time_utc, "M5", max(cfg.lookback_minutes, cfg.zone_window_bars * 5 + 10))
    if m5.empty:
        return {}
    m5 = m5.tail(cfg.zone_window_bars)
    if "high" not in m5.columns or "low" not in m5.columns:
        return {}
    highs = pd.to_numeric(m5["high"], errors="coerce").dropna()
    lows = pd.to_numeric(m5["low"], errors="coerce").dropna()
    if highs.empty or lows.empty:
        return {}
    support = float(lows.min())
    resistance = float(highs.max())
    last = m5.iloc[-1]
    atr = _safe_float(last.get("ATR"), default=0.0)
    if atr <= 0:
        rng = max(resistance - support, 0.0)
        atr = rng / 5 if rng > 0 else 1.0
    tolerance = max(atr * cfg.zone_tolerance_atr, 0.01)
    return {
        "zone_support_m5": support,
        "zone_resistance_m5": resistance,
        "zone_tolerance": tolerance,
        "zone_distance_to_support": None,
        "zone_distance_to_resistance": None,
    }


def _m5_current_previous(context: Optional[pd.DataFrame], entry_time_utc: str, cfg: AuditConfig) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
    if context is None or context.empty:
        return None, None
    m5 = _context_slice_before(context, entry_time_utc, "M5", max(cfg.lookback_minutes, 40))
    if len(m5) < 2:
        return None, None
    return m5.iloc[-1], m5.iloc[-2]


def _m5_permission(side: str, current: Optional[pd.Series], previous: Optional[pd.Series]) -> str:
    if current is None or previous is None:
        return "M5_PERMISSION_UNKNOWN"
    cur_close = _safe_float(current.get("close"), default=float("nan"))
    cur_low = _safe_float(current.get("low"), default=float("nan"))
    cur_high = _safe_float(current.get("high"), default=float("nan"))
    prev_open = _safe_float(previous.get("open"), default=float("nan"))
    prev_close = _safe_float(previous.get("close"), default=float("nan"))
    prev_high = _safe_float(previous.get("high"), default=float("nan"))
    prev_low = _safe_float(previous.get("low"), default=float("nan"))
    body_top = max(prev_open, prev_close)
    body_bottom = min(prev_open, prev_close)
    inside_prev_body = body_bottom <= cur_close <= body_top

    side = side.upper()
    if side == "SELL":
        if not math.isnan(cur_high) and not math.isnan(prev_high) and cur_high > prev_high:
            return "M5_BLOCKED_SELL_ABOVE_PREV_HIGH"
        if inside_prev_body or (not math.isnan(cur_low) and not math.isnan(prev_low) and cur_low < prev_low):
            return "M5_ALLOWED_SELL"
        return "M5_NEUTRAL_SELL"
    if side == "BUY":
        if not math.isnan(cur_low) and not math.isnan(prev_low) and cur_low < prev_low:
            return "M5_BLOCKED_BUY_BELOW_PREV_LOW"
        if inside_prev_body or (not math.isnan(cur_high) and not math.isnan(prev_high) and cur_high > prev_high):
            return "M5_ALLOWED_BUY"
        return "M5_NEUTRAL_BUY"
    return "M5_PERMISSION_UNKNOWN"


def _classify(row: Dict[str, Any], context: Optional[pd.DataFrame], cfg: AuditConfig) -> Dict[str, Any]:
    tags: List[str] = []
    warnings: List[str] = []
    regime_tags: List[str] = []
    side = str(row.get("side", "")).upper()
    side_dir = _side_dir(side)
    entry_price = _safe_float(row.get("entry_price"), default=float("nan"))

    time_tag = _time_window_tag(str(row.get("entry_time_utc")))
    regime_tags.append(time_tag)
    in_breakout_window = time_tag.startswith("TIME_BREAKOUT_WINDOW")

    for tf in ("H1", "M15"):
        b = _bias(row.get(f"{tf}_structure_state"))
        if side_dir and b and side_dir != b:
            tags.append(f"COUNTER_{tf}")

    m5_volume = _safe_float(row.get("M5_volume_ratio"), default=float("nan"))
    m5_pace = _safe_float(row.get("M5_volume_pace_ratio"), default=float("nan"))
    volume_expansion = False
    if (not math.isnan(m5_volume) and m5_volume >= 1.20) or (not math.isnan(m5_pace) and m5_pace >= 1.20):
        volume_expansion = True
        regime_tags.append("VOLUME_EXPANSION_AT_ENTRY")
    elif not math.isnan(m5_volume) and m5_volume < 0.70:
        tags.append("LOW_VOLUME_ENTRY")
        regime_tags.append("LOW_VOLUME_AT_ENTRY")

    m5_range = _safe_float(row.get("M5_range_atr"), default=float("nan"))
    if not math.isnan(m5_range) and m5_range > 1.20:
        tags.append("AFTER_LONG_M5_CANDLE")
        regime_tags.append("M5_EXTENDED_CANDLE")

    m5_spread_z = _safe_float(row.get("M5_spread_z"), default=float("nan"))
    if not math.isnan(m5_spread_z) and m5_spread_z > 2.0:
        tags.append("HIGH_SPREAD_ENTRY")

    close_pos = _safe_float(row.get("M5_close_pos"), default=float("nan"))
    if side_dir == "UP" and not math.isnan(close_pos) and close_pos > 0.85:
        tags.append("BUY_NEAR_CANDLE_HIGH")
    if side_dir == "DOWN" and not math.isnan(close_pos) and close_pos < 0.15:
        tags.append("SELL_NEAR_CANDLE_LOW")

    breakout_up = _safe_int(row.get("M5_breakout_up"), 0) == 1
    breakout_down = _safe_int(row.get("M5_breakout_down"), 0) == 1
    false_up = _safe_int(row.get("M5_false_breakout_up"), 0) == 1 or _safe_int(row.get("M5_sweep_high"), 0) == 1
    false_down = _safe_int(row.get("M5_false_breakout_down"), 0) == 1 or _safe_int(row.get("M5_sweep_low"), 0) == 1

    if breakout_up and volume_expansion and in_breakout_window:
        regime_tags.append("REAL_BREAKOUT_UP_CONTEXT")
        if side == "SELL":
            tags.append("FADED_REAL_BREAKOUT_UP")
    if breakout_down and volume_expansion and in_breakout_window:
        regime_tags.append("REAL_BREAKOUT_DOWN_CONTEXT")
        if side == "BUY":
            tags.append("FADED_REAL_BREAKOUT_DOWN")
    if (false_up or (breakout_up and not volume_expansion and not in_breakout_window)):
        regime_tags.append("FALSE_BREAKOUT_UP_CONTEXT")
    if (false_down or (breakout_down and not volume_expansion and not in_breakout_window)):
        regime_tags.append("FALSE_BREAKOUT_DOWN_CONTEXT")

    if _safe_float(row.get("M5_vol_spike_1p5")) == 0 and breakout_up:
        warnings.append("BREAKOUT_UP_WITHOUT_VOLUME_SPIKE")
    if _safe_float(row.get("M5_vol_spike_1p5")) == 0 and breakout_down:
        warnings.append("BREAKOUT_DOWN_WITHOUT_VOLUME_SPIKE")

    zone = _nearest_zone_from_m5(context, str(row.get("entry_time_utc")), cfg)
    support = _safe_float(zone.get("zone_support_m5"), default=float("nan"))
    resistance = _safe_float(zone.get("zone_resistance_m5"), default=float("nan"))
    tolerance = _safe_float(zone.get("zone_tolerance"), default=float("nan"))
    near_support = False
    near_resistance = False
    if not math.isnan(entry_price) and not math.isnan(tolerance):
        if not math.isnan(support):
            zone["zone_distance_to_support"] = round(entry_price - support, 5)
            near_support = abs(entry_price - support) <= tolerance
        if not math.isnan(resistance):
            zone["zone_distance_to_resistance"] = round(resistance - entry_price, 5)
            near_resistance = abs(resistance - entry_price) <= tolerance

    if side == "BUY" and near_support:
        regime_tags.append("BUY_AT_SUPPORT")
    if side == "SELL" and near_resistance:
        regime_tags.append("SELL_AT_RESISTANCE")
    if side == "BUY" and near_resistance:
        tags.append("BUY_AT_RESISTANCE")
    if side == "SELL" and near_support:
        tags.append("SELL_AT_SUPPORT")

    current_m5, previous_m5 = _m5_current_previous(context, str(row.get("entry_time_utc")), cfg)
    m5_permission = _m5_permission(side, current_m5, previous_m5)
    if m5_permission.startswith("M5_BLOCKED"):
        tags.append(m5_permission)
    elif m5_permission.startswith("M5_ALLOWED"):
        regime_tags.append(m5_permission)

    if in_breakout_window and volume_expansion:
        market_regime = "BREAKOUT_CONTINUATION_CONTEXT"
    elif "FALSE_BREAKOUT_UP_CONTEXT" in regime_tags or "FALSE_BREAKOUT_DOWN_CONTEXT" in regime_tags:
        market_regime = "FALSE_BREAKOUT_CONTEXT"
    elif near_support or near_resistance:
        market_regime = "RANGE_FADE_ZONE_CONTEXT"
    else:
        market_regime = "CHOP_OR_NO_CLEAR_ZONE_CONTEXT"

    net = _safe_float(row.get("net_profit"))
    out = {
        "result_quality": "WIN" if net > 0 else ("LOSS" if net < 0 else "FLAT"),
        "market_regime_at_entry": market_regime,
        "time_window_tag": time_tag,
        "m5_permission_tag": m5_permission,
        "error_tags": ",".join(sorted(set(tags))),
        "warning_tags": ",".join(sorted(set(warnings))),
        "regime_tags": ",".join(sorted(set(regime_tags))),
        "error_tag_count": len(set(tags)),
    }
    out.update(zone)
    return out


def _enrich(trades: pd.DataFrame, context: Optional[pd.DataFrame], cfg: AuditConfig) -> pd.DataFrame:
    if trades.empty:
        return trades
    rows: List[Dict[str, Any]] = []
    for _, trade in trades.iterrows():
        item = trade.to_dict()
        if context is not None:
            for tf in ("H1", "M15", "M5", "M1"):
                item.update(_context_before(context, trade["entry_time_utc"], tf, cfg.lookback_minutes))
        item.update(_classify(item, context, cfg))
        rows.append(item)
    return pd.DataFrame(rows)


def _tag_summary(df: pd.DataFrame, column: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if df.empty or column not in df.columns:
        return []
    for _, row in df.iterrows():
        for tag in [x for x in str(row.get(column, "")).split(",") if x]:
            rows.append({"tag": tag, "net_profit": row.get("net_profit", 0.0), "is_loss": row.get("net_profit", 0.0) < 0})
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
        })
    return sorted(out, key=lambda x: (x["net_profit"], -x["occurrences"]))[:30]


def _regime_summary(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df.empty or "market_regime_at_entry" not in df.columns:
        return []
    out: List[Dict[str, Any]] = []
    for regime, group in df.groupby("market_regime_at_entry"):
        total = int(len(group))
        wins = int((group["net_profit"] > 0).sum())
        out.append({
            "regime": str(regime),
            "trades": total,
            "wins": wins,
            "losses": int((group["net_profit"] < 0).sum()),
            "win_rate": round(wins / total, 4) if total else None,
            "net_profit": round(_safe_float(group["net_profit"].sum()), 2),
            "avg_profit": round(_safe_float(group["net_profit"].mean()), 2),
        })
    return sorted(out, key=lambda x: x["net_profit"])


def _build_personal_intelligence(summary: Dict[str, Any]) -> Dict[str, Any]:
    active_blocks: List[str] = []
    recommendations: List[Dict[str, Any]] = []
    for item in summary.get("top_error_tags", []):
        tag = item.get("tag")
        if not tag:
            continue
        if item.get("net_profit", 0) < 0 and item.get("occurrences", 0) >= 2:
            if tag == "FADED_REAL_BREAKOUT_UP":
                block = "BLOCK_SELL_AGAINST_REAL_BREAKOUT_UP"
            elif tag == "FADED_REAL_BREAKOUT_DOWN":
                block = "BLOCK_BUY_AGAINST_REAL_BREAKOUT_DOWN"
            elif tag == "BUY_AT_RESISTANCE":
                block = "BLOCK_BUY_DIRECTLY_AT_RESISTANCE"
            elif tag == "SELL_AT_SUPPORT":
                block = "BLOCK_SELL_DIRECTLY_AT_SUPPORT"
            elif str(tag).startswith("M5_BLOCKED"):
                block = "RESPECT_M5_PERMISSION_FILTER"
            else:
                block = f"REVIEW_{tag}"
            active_blocks.append(block)
            recommendations.append({
                "tag": tag,
                "occurrences": item.get("occurrences"),
                "loss_count": item.get("loss_count"),
                "net_profit": item.get("net_profit"),
                "recommendation": block,
            })
    return {
        "available": True,
        "dominant_error_patterns": recommendations[:10],
        "active_personal_blocks": sorted(set(active_blocks)),
    }


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

    summary = {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": round(wins / total, 4),
        "net_profit": round(_safe_float(df["net_profit"].sum()), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": None if pf is None else round(pf, 4),
        "top_error_tags": _tag_summary(df, "error_tags"),
        "top_regime_tags": _tag_summary(df, "regime_tags"),
        "top_warning_tags": _tag_summary(df, "warning_tags"),
        "market_regime_summary": _regime_summary(df),
    }
    summary["personal_trade_intelligence"] = _build_personal_intelligence(summary)
    return summary


def _write(df: pd.DataFrame, summary: Dict[str, Any], cfg: AuditConfig) -> None:
    out_dir = cfg.output_dir / cfg.symbol.upper()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"personal_trade_audit_{stamp}.csv"
    json_path = out_dir / f"personal_trade_audit_summary_{stamp}.json"
    intelligence_path = out_dir / f"personal_trade_intelligence_{stamp}.json"
    latest_csv = out_dir / "personal_trade_audit_latest.csv"
    latest_json = out_dir / "personal_trade_audit_summary_latest.json"
    latest_intelligence = out_dir / "personal_trade_intelligence_latest.json"

    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_csv(latest_csv, index=False, encoding="utf-8")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    intelligence = summary.get("personal_trade_intelligence", {"available": False})
    intelligence_path.write_text(json.dumps(intelligence, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_intelligence.write_text(json.dumps(intelligence, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] Trades auditados: {len(df)}")
    print(f"[OK] CSV: {csv_path}")
    print(f"[OK] Summary: {json_path}")
    print(f"[OK] Intelligence: {intelligence_path}")
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
