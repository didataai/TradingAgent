#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Synthetic Dollar Context Builder
================================

Motor enxuto para calcular DXY_FULL e USD_PROXY_3 a partir dos pares Forex do
MetaTrader 5 ou de Parquets já existentes.

Princípios:
- Não usa Yahoo/Futuro DXY como fonte principal.
- Usa somente candles fechados.
- Não usa lookahead.
- Compatível Windows/Linux.
- Multi-timeframe e sem paths absolutos hardcoded.
- DXY é contexto/filtro, nunca gatilho isolado de trade.

Uso offline, com Parquets existentes:
    python tools/synthetic_dollar_context.py --symbol GOLD --offline

Uso MT5:
    python tools/synthetic_dollar_context.py --symbol GOLD

Saídas:
    data/market_context/synthetic_dollar/<MODE>_<TF>.parquet
    data/market_context/synthetic_dollar/<SYMBOL>_synthetic_dollar_context.json
    data/market_context/synthetic_dollar/<SYMBOL>_synthetic_dollar_block.txt
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

try:  # MT5 é opcional para testes/offline/Linux sem terminal.
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover
    mt5 = None


DXY_FULL_WEIGHTS: Dict[str, float] = {
    "EURUSD": -0.576,
    "USDJPY": 0.136,
    "GBPUSD": -0.119,
    "USDCAD": 0.091,
    "USDSEK": 0.042,
    "USDCHF": 0.036,
}

USD_PROXY_3_WEIGHTS: Dict[str, float] = {
    "EURUSD": -0.576,
    "USDJPY": 0.136,
    "GBPUSD": -0.119,
}

DXY_CONSTANT = 50.14348112
TIMEFRAME_TO_MT5_NAME = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
}
TIMEFRAME_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}
DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "H1"]
DEFAULT_STALE_TOLERANCE_SECONDS = {"M1": 180, "M5": 600, "M15": 1800, "H1": 7200, "H4": 21600}


@dataclass(frozen=True)
class SyntheticDollarConfig:
    enabled: bool = True
    source: str = "mt5"
    preferred_mode: str = "full"
    fallback_mode: str = "proxy_3"
    timeframes: Tuple[str, ...] = tuple(DEFAULT_TIMEFRAMES)
    base_value: float = 100.0
    anchor: str = "first_closed_candle_of_day"
    timezone: str = "America/Sao_Paulo"
    q_candles: int = 5000
    symbol_mapping: Mapping[str, str] | None = None
    stale_tolerance_seconds: Mapping[str, int] | None = None


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"JSON inválido: {path}")
    return data


def write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def normalize_symbol_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def load_config(project_root: Path, config_path: Path) -> Tuple[Dict[str, Any], SyntheticDollarConfig]:
    cfg = read_json(config_path)
    sd = cfg.get("synthetic_dollar", {}) or {}
    data_cfg = cfg.get("data", {}) or {}
    normalization = sd.get("normalization", {}) or {}
    stale = sd.get("stale_tolerance_seconds", {}) or {}
    merged_stale = dict(DEFAULT_STALE_TOLERANCE_SECONDS)
    merged_stale.update({str(k): int(v) for k, v in stale.items()})
    out = SyntheticDollarConfig(
        enabled=bool(sd.get("enabled", True)),
        source=str(sd.get("source", "mt5")),
        preferred_mode=str(sd.get("preferred_mode", "full")),
        fallback_mode=str(sd.get("fallback_mode", "proxy_3")),
        timeframes=tuple(str(x).upper() for x in sd.get("timeframes", DEFAULT_TIMEFRAMES)),
        base_value=float(normalization.get("base", 100.0)),
        anchor=str(normalization.get("anchor", "first_closed_candle_of_day")),
        timezone=str(normalization.get("timezone", "America/Sao_Paulo")),
        q_candles=int(sd.get("q_candles", data_cfg.get("q_candles", 5000))),
        symbol_mapping=sd.get("symbol_mapping", {}) or {},
        stale_tolerance_seconds=merged_stale,
    )
    return cfg, out


def mt5_timeframe(tf: str) -> int:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 não disponível. Use --offline ou instale MetaTrader5.")
    name = TIMEFRAME_TO_MT5_NAME.get(tf.upper())
    if not name or not hasattr(mt5, name):
        raise ValueError(f"Timeframe MT5 não suportado: {tf}")
    return int(getattr(mt5, name))


def mt5_initialize_from_config(config: Mapping[str, Any]) -> None:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 não disponível neste ambiente.")
    mt5_cfg = config.get("mt5", {}) or {}
    path = mt5_cfg.get("path")
    account = mt5_cfg.get("account")
    password = mt5_cfg.get("password")
    server = mt5_cfg.get("server")
    kwargs: Dict[str, Any] = {}
    if path:
        kwargs["path"] = str(path)
    if account:
        kwargs["login"] = int(account)
    if password:
        kwargs["password"] = str(password)
    if server:
        kwargs["server"] = str(server)
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"Falha ao inicializar MT5: {mt5.last_error()}")


def resolve_symbols(required: Iterable[str], manual_mapping: Mapping[str, str] | None = None) -> Dict[str, str]:
    manual_mapping = manual_mapping or {}
    resolved: Dict[str, str] = {}
    if mt5 is None:
        raise RuntimeError("MetaTrader5 não disponível para resolver símbolos.")
    broker_symbols = mt5.symbols_get()
    if broker_symbols is None:
        raise RuntimeError(f"symbols_get falhou: {mt5.last_error()}")
    available = [s.name for s in broker_symbols if getattr(s, "name", None)]
    available_norm = {normalize_symbol_text(name): name for name in available}
    for canonical in required:
        canonical = canonical.upper()
        manual = manual_mapping.get(canonical)
        if manual:
            if not mt5.symbol_select(str(manual), True):
                raise RuntimeError(f"Símbolo manual não habilitado no MT5: {manual}")
            resolved[canonical] = str(manual)
            continue
        if canonical in available:
            candidate = canonical
            if not mt5.symbol_select(candidate, True):
                raise RuntimeError(f"Símbolo não habilitado no MT5: {candidate}")
            resolved[canonical] = candidate
            continue
        norm = normalize_symbol_text(canonical)
        matches = []
        for real_norm, real in available_norm.items():
            if real_norm == norm or real_norm.startswith(norm) or real_norm.endswith(norm) or norm in real_norm:
                matches.append(real)
        matches = sorted(set(matches))
        if len(matches) == 1:
            if not mt5.symbol_select(matches[0], True):
                raise RuntimeError(f"Símbolo não habilitado no MT5: {matches[0]}")
            resolved[canonical] = matches[0]
        elif len(matches) > 1:
            raise RuntimeError(f"Símbolo ambíguo para {canonical}: {matches[:10]}")
    return resolved


def load_mt5_rates(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 não disponível.")
    rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe(timeframe), 0, int(count))
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"Sem candles MT5 para {symbol} {timeframe}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time")
    if not df.empty:
        # copy_rates_from_pos pode trazer candle atual. Remove o último por segurança.
        df = df.iloc[:-1]
    return df.reset_index(drop=True)


def load_offline_rates(data_dir: Path, canonical_symbol: str, timeframe: str) -> pd.DataFrame:
    candidates = [
        data_dir / f"{canonical_symbol}_{timeframe}.parquet",
        data_dir / "consolidated" / f"{canonical_symbol}_intraday.parquet",
        data_dir / "consolidated" / f"{canonical_symbol}_full.parquet",
    ]
    for path in candidates:
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if "timeframe" in df.columns:
            df = df[df["timeframe"].astype(str).str.upper() == timeframe.upper()]
        time_col = "time_brt" if "time_brt" in df.columns else "time"
        if time_col not in df.columns:
            continue
        df = df.copy()
        df["time"] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
        for col in ["open", "high", "low", "close"]:
            if col not in df.columns:
                raise ValueError(f"{path} sem coluna {col}")
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "is_live_bar" in df.columns:
            df = df[pd.to_numeric(df["is_live_bar"], errors="coerce").fillna(0).astype(int) == 0]
        return df.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
    raise FileNotFoundError(f"Não achei Parquet offline para {canonical_symbol} {timeframe} em {data_dir}")


def validate_ohlc(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    work = df.copy()
    mask = (work["open"] > 0) & (work["high"] > 0) & (work["low"] > 0) & (work["close"] > 0)
    mask &= work["high"] >= work[["open", "close", "low"]].max(axis=1)
    mask &= work["low"] <= work[["open", "close", "high"]].min(axis=1)
    invalid = int((~mask).sum())
    if invalid:
        print(f"[WARN] {symbol}: {invalid} candles OHLC inválidos removidos", flush=True)
    return work[mask].drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)


def align_component_closes(component_frames: Mapping[str, pd.DataFrame]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    aligned: Optional[pd.DataFrame] = None
    diagnostics = {"input_rows": {}, "discarded_rows": {}, "components": list(component_frames.keys())}
    for canonical, frame in component_frames.items():
        df = validate_ohlc(frame, canonical)
        diagnostics["input_rows"][canonical] = int(len(df))
        part = df[["time", "close"]].rename(columns={"close": canonical})
        aligned = part if aligned is None else aligned.merge(part, on="time", how="inner")
    if aligned is None or aligned.empty:
        return pd.DataFrame(), diagnostics
    aligned = aligned.sort_values("time").reset_index(drop=True)
    for canonical, rows in diagnostics["input_rows"].items():
        diagnostics["discarded_rows"][canonical] = int(rows - len(aligned))
    return aligned, diagnostics


def calculate_dxy_full(aligned: pd.DataFrame) -> pd.Series:
    missing = [p for p in DXY_FULL_WEIGHTS if p not in aligned.columns]
    if missing:
        raise ValueError(f"Componentes ausentes para DXY_FULL: {missing}")
    value = pd.Series(float(DXY_CONSTANT), index=aligned.index, dtype="float64")
    for pair, weight in DXY_FULL_WEIGHTS.items():
        value = value * np.power(pd.to_numeric(aligned[pair], errors="coerce"), weight)
    return value


def calculate_proxy_3(aligned: pd.DataFrame, base_value: float = 100.0) -> pd.Series:
    missing = [p for p in USD_PROXY_3_WEIGHTS if p not in aligned.columns]
    if missing:
        raise ValueError(f"Componentes ausentes para USD_PROXY_3: {missing}")
    weights_sum = sum(abs(x) for x in USD_PROXY_3_WEIGHTS.values())
    log_acc = pd.Series(0.0, index=aligned.index, dtype="float64")
    for pair, weight in USD_PROXY_3_WEIGHTS.items():
        price = pd.to_numeric(aligned[pair], errors="coerce")
        base = float(price.iloc[0])
        if base <= 0:
            raise ValueError(f"Preço-base inválido para {pair}: {base}")
        log_acc = log_acc + (weight / weights_sum) * (np.log(price) - math.log(base))
    return float(base_value) * np.exp(log_acc)


def component_usd_direction(pair: str, price_return: float) -> int:
    # Retorno positivo em USDXXX fortalece USD; em XXXUSD enfraquece USD.
    if pair.upper().startswith("USD"):
        return 1 if price_return > 0 else (-1 if price_return < 0 else 0)
    if pair.upper().endswith("USD"):
        return -1 if price_return > 0 else (1 if price_return < 0 else 0)
    return 0


def slope(series: pd.Series, window: int) -> pd.Series:
    return (series - series.shift(window)) / float(window)


def realized_vol(ret: pd.Series, window: int = 20) -> pd.Series:
    return ret.rolling(window, min_periods=max(3, window // 3)).std()


def atr_like(value: pd.Series, window: int = 14) -> pd.Series:
    return value.diff().abs().rolling(window, min_periods=max(3, window // 3)).mean()


def classify_direction(ret_3: float, slp_5: float, z: float) -> str:
    score = 0
    if ret_3 > 0:
        score += 1
    elif ret_3 < 0:
        score -= 1
    if slp_5 > 0:
        score += 1
    elif slp_5 < 0:
        score -= 1
    if z > 0.5:
        score += 1
    elif z < -0.5:
        score -= 1
    if score >= 3:
        return "STRONG_UP"
    if score > 0:
        return "UP"
    if score <= -3:
        return "STRONG_DOWN"
    if score < 0:
        return "DOWN"
    return "NEUTRAL"


def classify_regime(atr_ratio: float, z_abs: float) -> str:
    if not math.isfinite(atr_ratio):
        return "UNAVAILABLE"
    if z_abs >= 3.0 or atr_ratio >= 2.0:
        return "SHOCK"
    if atr_ratio >= 1.25:
        return "EXPANSION"
    if atr_ratio <= 0.75:
        return "CONTRACTION"
    return "NORMAL"


def add_features(index_df: pd.DataFrame, component_cols: List[str]) -> pd.DataFrame:
    out = index_df.copy()
    v = pd.to_numeric(out["dxy_value"], errors="coerce")
    out["dxy_return_1"] = v.pct_change(1)
    out["dxy_return_3"] = v.pct_change(3)
    out["dxy_return_5"] = v.pct_change(5)
    out["dxy_slope_3"] = slope(v, 3)
    out["dxy_slope_5"] = slope(v, 5)
    out["dxy_range_pct"] = v.pct_change().abs().rolling(5, min_periods=2).sum()
    out["dxy_realized_vol"] = realized_vol(out["dxy_return_1"])
    out["dxy_atr"] = atr_like(v)
    out["dxy_atr_ratio"] = out["dxy_atr"] / out["dxy_atr"].rolling(50, min_periods=10).mean()
    ma = v.rolling(50, min_periods=10).mean()
    sd = v.rolling(50, min_periods=10).std()
    out["dxy_zscore"] = (v - ma) / sd.replace(0, np.nan)
    out["dxy_momentum"] = out["dxy_return_3"]
    out["dxy_acceleration"] = out["dxy_slope_3"] - out["dxy_slope_3"].shift(3)
    out["component_count"] = len(component_cols)
    agreement_values = []
    dispersion_values = []
    for _, row in out.iterrows():
        dirs = []
        rets = []
        for pair in component_cols:
            ret_col = f"{pair}_ret_1"
            ret = row.get(ret_col)
            if pd.notna(ret):
                rets.append(float(ret))
                dirs.append(component_usd_direction(pair, float(ret)))
        non_zero = [x for x in dirs if x != 0]
        up = sum(1 for x in non_zero if x > 0)
        down = sum(1 for x in non_zero if x < 0)
        agreement_values.append(max(up, down))
        dispersion_values.append(float(np.std(rets)) if rets else np.nan)
    out["component_agreement"] = agreement_values
    out["component_dispersion"] = dispersion_values
    dirs = []
    regimes = []
    for _, row in out.iterrows():
        dirs.append(classify_direction(float(row.get("dxy_return_3", 0) or 0), float(row.get("dxy_slope_5", 0) or 0), float(row.get("dxy_zscore", 0) or 0)))
        regimes.append(classify_regime(float(row.get("dxy_atr_ratio", np.nan)), abs(float(row.get("dxy_zscore", 0) or 0))))
    out["dxy_direction"] = dirs
    out["dxy_regime"] = regimes
    return out


def status_from_freshness(last_time: pd.Timestamp, timeframe: str, tolerance_map: Mapping[str, int]) -> str:
    if pd.isna(last_time):
        return "INVALID"
    now = pd.Timestamp.now(tz="UTC")
    if last_time.tzinfo is None:
        last_time = last_time.tz_localize("UTC")
    age = (now - last_time).total_seconds()
    tol = int(tolerance_map.get(timeframe, DEFAULT_STALE_TOLERANCE_SECONDS.get(timeframe, 3600)))
    if age <= tol:
        return "FRESH"
    if age <= tol * 6:
        return "STALE"
    return "MARKET_CLOSED"


def choose_mode(frames: Mapping[str, pd.DataFrame]) -> str:
    if all(pair in frames and not frames[pair].empty for pair in DXY_FULL_WEIGHTS):
        return "DXY_FULL"
    if all(pair in frames and not frames[pair].empty for pair in USD_PROXY_3_WEIGHTS):
        return "USD_PROXY_3"
    return "INSUFFICIENT_COMPONENTS"


def build_index_for_timeframe(
    component_frames: Mapping[str, pd.DataFrame],
    timeframe: str,
    cfg: SyntheticDollarConfig,
) -> Tuple[str, pd.DataFrame, Dict[str, Any]]:
    mode = choose_mode(component_frames)
    if mode == "INSUFFICIENT_COMPONENTS":
        return mode, pd.DataFrame(), {"status": "INSUFFICIENT_COMPONENTS"}
    required = DXY_FULL_WEIGHTS if mode == "DXY_FULL" else USD_PROXY_3_WEIGHTS
    aligned, diagnostics = align_component_closes({k: component_frames[k] for k in required})
    if aligned.empty:
        return mode, pd.DataFrame(), {"status": "INVALID", "reason": "empty_aligned_frame", "diagnostics": diagnostics}
    for pair in required:
        aligned[f"{pair}_ret_1"] = pd.to_numeric(aligned[pair], errors="coerce").pct_change(1)
    value = calculate_dxy_full(aligned) if mode == "DXY_FULL" else calculate_proxy_3(aligned, cfg.base_value)
    index_df = aligned.copy()
    index_df["mode"] = mode
    index_df["timeframe"] = timeframe
    index_df["dxy_value"] = value
    index_df = add_features(index_df, list(required.keys()))
    status = status_from_freshness(pd.to_datetime(index_df["time"].iloc[-1], utc=True), timeframe, cfg.stale_tolerance_seconds or {})
    index_df["dxy_freshness"] = status
    diagnostics["status"] = status
    diagnostics["mode"] = mode
    diagnostics["rows"] = int(len(index_df))
    return mode, index_df, diagnostics


def gold_relationship(gold_df: Optional[pd.DataFrame], dxy_df: pd.DataFrame) -> Dict[str, Any]:
    if gold_df is None or gold_df.empty or dxy_df.empty:
        return {"relationship": "INSUFFICIENT_HISTORY", "impact": "UNAVAILABLE", "confirmation": "NEUTRAL", "confidence": "LOW"}
    g = validate_ohlc(gold_df, "GOLD")
    merged = g[["time", "close"]].rename(columns={"close": "gold_close"}).merge(dxy_df[["time", "dxy_value", "dxy_direction", "dxy_regime"]], on="time", how="inner")
    if len(merged) < 30:
        return {"relationship": "INSUFFICIENT_HISTORY", "impact": "UNAVAILABLE", "confirmation": "NEUTRAL", "confidence": "LOW"}
    merged["gold_ret"] = merged["gold_close"].pct_change()
    merged["dxy_ret"] = merged["dxy_value"].pct_change()
    corr = float(merged["gold_ret"].rolling(50, min_periods=20).corr(merged["dxy_ret"]).iloc[-1])
    dxy_dir = str(merged["dxy_direction"].iloc[-1])
    relationship = "UNSTABLE"
    impact = "NEUTRAL"
    confirmation = "NEUTRAL"
    confidence = "LOW"
    if math.isfinite(corr):
        if corr <= -0.25:
            relationship = "INVERSE_AND_ALIGNED"
            confidence = "MODERATE"
            if dxy_dir in {"UP", "STRONG_UP"}:
                impact = "BEARISH_PRESSURE"
                confirmation = "ALIGNED"
            elif dxy_dir in {"DOWN", "STRONG_DOWN"}:
                impact = "BULLISH_PRESSURE"
                confirmation = "ALIGNED"
        elif corr >= 0.25:
            relationship = "POSITIVE_AND_ALIGNED"
            confidence = "LOW"
            if dxy_dir in {"UP", "STRONG_UP"}:
                impact = "BULLISH_PRESSURE"
            elif dxy_dir in {"DOWN", "STRONG_DOWN"}:
                impact = "BEARISH_PRESSURE"
        else:
            relationship = "UNSTABLE"
            impact = "VOLATILITY_ONLY"
    return {"rolling_correlation": round(corr, 6) if math.isfinite(corr) else None, "relationship": relationship, "impact": impact, "confirmation": confirmation, "confidence": confidence}


def latest_context(symbol: str, tf_results: Mapping[str, pd.DataFrame], diagnostics: Mapping[str, Any], gold_ctx: Mapping[str, Any]) -> Dict[str, Any]:
    available = {tf: df for tf, df in tf_results.items() if df is not None and not df.empty}
    if not available:
        return {"synthetic_dollar": {"status": "UNAVAILABLE", "mode": "UNAVAILABLE", "gold_context": gold_ctx}}
    primary_tf = "M5" if "M5" in available else list(available.keys())[0]
    row = available[primary_tf].iloc[-1]
    status = str(row.get("dxy_freshness", "INVALID"))
    mode = str(row.get("mode", "UNAVAILABLE"))
    tf_payload: Dict[str, Any] = {}
    for tf, df in available.items():
        r = df.iloc[-1]
        tf_payload[tf] = {
            "timestamp": str(r.get("time")),
            "direction": str(r.get("dxy_direction", "NEUTRAL")),
            "return": safe_float(r.get("dxy_return_1")),
            "slope": safe_float(r.get("dxy_slope_5")),
            "zscore": safe_float(r.get("dxy_zscore")),
            "regime": str(r.get("dxy_regime", "UNAVAILABLE")),
            "freshness": str(r.get("dxy_freshness", "INVALID")),
        }
    total = int(row.get("component_count", 0) or 0)
    agreeing = int(row.get("component_agreement", 0) or 0)
    return {
        "synthetic_dollar": {
            "status": status,
            "mode": mode,
            "source": "MetaTrader5_or_local_parquet",
            "timestamp": str(row.get("time")),
            "value": safe_float(row.get("dxy_value")),
            "direction": str(row.get("dxy_direction", "NEUTRAL")),
            "volatility_regime": str(row.get("dxy_regime", "UNAVAILABLE")),
            "component_agreement": {"agreeing": agreeing, "total": total, "ratio": round(agreeing / total, 4) if total else 0.0},
            "timeframes": tf_payload,
            "gold_context": dict(gold_ctx),
            "diagnostics": dict(diagnostics),
            "usage_rule": "Context only; never open or recommend a trade using synthetic DXY alone.",
        }
    }


def safe_float(value: Any) -> Optional[float]:
    try:
        f = float(value)
        if math.isfinite(f):
            return round(f, 6)
    except Exception:
        return None
    return None


def format_prompt_block(context: Mapping[str, Any]) -> str:
    sd = (context.get("synthetic_dollar") or {}) if isinstance(context, Mapping) else {}
    tf = sd.get("timeframes", {}) or {}
    gold = sd.get("gold_context", {}) or {}
    lines = [
        "=== SYNTHETIC DOLLAR CONTEXT ===",
        "Source: MetaTrader 5 / local MT5-derived parquet",
        f"Mode: {sd.get('mode', 'UNAVAILABLE')}",
        f"Data Status: {sd.get('status', 'UNAVAILABLE')}",
        f"Last Closed Candle: {sd.get('timestamp', '-')}",
        "",
        "USD Direction:",
    ]
    for name in DEFAULT_TIMEFRAMES:
        item = tf.get(name, {}) or {}
        lines.append(f"{name}: {item.get('direction', 'UNAVAILABLE')}")
    ca = sd.get("component_agreement", {}) or {}
    lines.extend([
        "",
        f"USD Volatility Regime: {sd.get('volatility_regime', 'UNAVAILABLE')}",
        f"Component Agreement: {ca.get('agreeing', 0)} of {ca.get('total', 0)}",
        f"Current GOLD/DXY Rolling Correlation: {gold.get('rolling_correlation', 'N/A')}",
        f"Relationship: {gold.get('relationship', 'UNAVAILABLE')}",
        f"Expected GOLD Effect: {gold.get('impact', 'UNAVAILABLE')}",
        f"DXY Confirmation: {gold.get('confirmation', 'NEUTRAL')}",
        "",
        "Important:",
        "The synthetic DXY is contextual information.",
        "Do not open or recommend a trade using the DXY alone.",
        "Prioritize GOLD structure, support/resistance, candle confirmation, relative volume, volatility and existing entry rules.",
    ])
    if sd.get("status") in {"STALE", "MARKET_CLOSED", "INVALID", "UNAVAILABLE"}:
        lines.append("DXY indisponível ou desatualizado — não utilizar como confirmação.")
    return "\n".join(lines)


def build_context(args: argparse.Namespace) -> Dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    config_path = Path(args.config).resolve() if args.config else project_root / "tradingagent.json"
    raw_cfg, cfg = load_config(project_root, config_path)
    data_dir = project_root / str((raw_cfg.get("data", {}) or {}).get("data_dir", "data"))
    out_dir = data_dir / "market_context" / "synthetic_dollar"
    if not cfg.enabled:
        return {"synthetic_dollar": {"status": "UNAVAILABLE", "reason": "disabled"}}

    canonical_all = list(DXY_FULL_WEIGHTS.keys())
    resolved = {x: x for x in canonical_all}
    if not args.offline:
        mt5_initialize_from_config(raw_cfg)
        resolved = resolve_symbols(canonical_all, cfg.symbol_mapping)

    tf_results: Dict[str, pd.DataFrame] = {}
    all_diag: Dict[str, Any] = {"resolved_symbols": resolved, "timeframes": {}}
    for tf in cfg.timeframes:
        component_frames: Dict[str, pd.DataFrame] = {}
        for canonical in canonical_all:
            try:
                if args.offline:
                    component_frames[canonical] = load_offline_rates(data_dir, canonical, tf)
                else:
                    component_frames[canonical] = load_mt5_rates(resolved[canonical], tf, cfg.q_candles)
            except Exception as exc:
                all_diag.setdefault("component_errors", {}).setdefault(tf, {})[canonical] = str(exc)
        mode, df, diag = build_index_for_timeframe(component_frames, tf, cfg)
        all_diag["timeframes"][tf] = diag
        if df.empty:
            continue
        tf_results[tf] = df
        out_path = out_dir / f"{mode}_{tf}.parquet"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False)

    gold_df = None
    try:
        gold_df = load_offline_rates(data_dir, args.symbol.upper(), "M5")
    except Exception:
        gold_df = None
    gold_ctx = gold_relationship(gold_df, tf_results.get("M5", pd.DataFrame()))
    context = latest_context(args.symbol.upper(), tf_results, all_diag, gold_ctx)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out_dir / f"{args.symbol.upper()}_synthetic_dollar_context.json", context)
    (out_dir / f"{args.symbol.upper()}_synthetic_dollar_block.txt").write_text(format_prompt_block(context), encoding="utf-8")
    return context


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Calcula DXY_FULL / USD_PROXY_3 sintético via MT5 ou Parquets locais.")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--config", default=None)
    p.add_argument("--offline", action="store_true", help="Usa Parquets locais em vez de conectar no MT5.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    context = build_context(args)
    sd = context.get("synthetic_dollar", {})
    print(f"[OK] Synthetic Dollar | status={sd.get('status')} mode={sd.get('mode')} direction={sd.get('direction')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
