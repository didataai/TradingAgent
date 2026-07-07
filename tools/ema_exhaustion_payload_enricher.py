#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EMA Exhaustion Payload Enricher
===============================

Adiciona uma camada operacional de qualidade de entrada ao payload intraday:

- garante EMA_5 no consolidado/parquets quando estiver ausente;
- calcula dist_ema5_atr;
- recalcula OBV como série assinada para evitar overflow uint64;
- injeta `ema_exhaustion_context` por timeframe no MARKET_DATA;
- injeta `execution_quality` consolidado no payload.

Objetivo conceitual:

Trend forte não significa entrada boa agora.
Pullback normal não significa reversão.
Exaustão bloqueia perseguição, mas não libera reversão automática.

Uso:
    python tools/ema_exhaustion_payload_enricher.py --symbol GOLD

Uso com paths explícitos:
    python tools/ema_exhaustion_payload_enricher.py ^
      --symbol GOLD ^
      --market-data data/consolidated/GOLD_intraday.parquet ^
      --payload data/payload/GOLD_intraday_payload.json
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


TF_ORDER = ("H4", "H1", "M15", "M5", "M1")
FAST_EMA = 5
SLOW_EMA = 20
EXTENDED_ATR_THRESHOLD = 0.8
ADX_HEALTHY_MIN = 18.0
ADX_STRONG_MIN = 22.0


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enriquece payload intraday com EMA exhaustion/execution quality.")
    p.add_argument("--symbol", default="GOLD", help="Símbolo lógico, ex.: GOLD")
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--market-data", type=Path, default=None, help="Consolidado intraday parquet/csv")
    p.add_argument("--payload", type=Path, default=None, help="Payload intraday JSON")
    p.add_argument("--output", type=Path, default=None, help="Arquivo de saída. Default: sobrescreve payload")
    p.add_argument("--write-market-data", action="store_true", default=True, help="Atualiza o consolidado com EMA_5/dist_ema5_atr/OBV corrigido")
    p.add_argument("--no-write-market-data", dest="write_market_data", action="store_false")
    p.add_argument("--write-timeframe-parquets", action="store_true", help="Também atualiza data/<SYMBOL>_<TF>.parquet se existirem")
    return p.parse_args()


def _finite(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else default
    return value


def _rounded(value: Any, digits: int = 6, default: Any = None) -> Any:
    value = _finite(value, default)
    if isinstance(value, float):
        return round(value, digits)
    return value


def _safe_float(value: Any, default: float = float("nan")) -> float:
    value = _finite(value)
    try:
        return float(value)
    except Exception:
        return default


def _safe_bool(row: pd.Series, field: str) -> bool:
    try:
        return bool(int(_finite(row.get(field), 0)))
    except Exception:
        return False


def _safe_div(n: Any, d: Any) -> Optional[float]:
    try:
        n = float(n)
        d = float(d)
        if not math.isfinite(n) or not math.isfinite(d) or d == 0:
            return None
        return n / d
    except Exception:
        return None


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Payload não encontrado: {path}")
    with path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Payload inválido: {path}")
    return data


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_market_path(root: Path, symbol: str) -> Path:
    candidates = [
        root / "data" / "consolidated" / f"{symbol}_intraday.parquet",
        root / "data" / "consolidated" / f"{symbol.upper()}_intraday.parquet",
        root / "data" / "consolidated" / f"{symbol.capitalize()}_intraday.parquet",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"Consolidado intraday não encontrado para {symbol}: {candidates}")


def _default_payload_path(root: Path, symbol: str) -> Path:
    return root / "data" / "payload" / f"{symbol}_intraday_payload.json"


def _load_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Market data não encontrado: {path}")
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, low_memory=False)
    raise ValueError(f"Formato não suportado: {path.suffix}")


def _save_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".parquet", ".pq"}:
        df.to_parquet(path, index=False)
    elif path.suffix.lower() == ".csv":
        df.to_csv(path, index=False, encoding="utf-8")
    else:
        raise ValueError(f"Formato não suportado: {path.suffix}")


def _sort_frame(df: pd.DataFrame) -> pd.DataFrame:
    time_col = "time_brt" if "time_brt" in df.columns else "time"
    if time_col in df.columns:
        work = df.copy()
        work["__sort_time"] = pd.to_datetime(work[time_col], errors="coerce")
        work = work.sort_values(["timeframe", "__sort_time"] if "timeframe" in work.columns else ["__sort_time"])
        return work.drop(columns=["__sort_time"], errors="ignore")
    return df


def _signed_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """OBV assinado em float64 para evitar underflow/overflow uint64.

    O bug observado vinha de OBV negativo armazenado como inteiro sem sinal,
    aparecendo no payload como 1844674407... Recalculamos por timeframe com
    float64, mantendo compatibilidade com parquet e JSON.
    """
    close_num = pd.to_numeric(close, errors="coerce")
    vol_num = pd.to_numeric(volume, errors="coerce").fillna(0.0).astype("float64")
    delta = close_num.diff()
    direction = np.where(delta > 0, 1.0, np.where(delta < 0, -1.0, 0.0))
    contribution = pd.Series(direction, index=close.index, dtype="float64") * vol_num
    if len(contribution) > 0:
        contribution.iloc[0] = vol_num.iloc[0]
    return contribution.cumsum().astype("float64")


def ensure_ema5_features(df: pd.DataFrame) -> pd.DataFrame:
    """Garante EMA_5, dist_ema5_atr e OBV assinado no dataframe consolidado."""
    if df.empty:
        return df
    work = df.copy()
    if "timeframe" not in work.columns:
        work["timeframe"] = "UNKNOWN"
    work = _sort_frame(work)

    if "EMA_5" not in work.columns:
        work["EMA_5"] = np.nan
    if "dist_ema5_atr" not in work.columns:
        work["dist_ema5_atr"] = np.nan
    if "OBV" not in work.columns:
        work["OBV"] = np.nan

    for _tf, idx in work.groupby(work["timeframe"].astype(str).str.upper()).groups.items():
        group = work.loc[idx].copy()
        close = pd.to_numeric(group["close"], errors="coerce")
        volume = pd.to_numeric(group.get("tick_volume", 0.0), errors="coerce").fillna(0.0)

        ema5 = close.ewm(span=FAST_EMA, adjust=False, min_periods=FAST_EMA).mean()
        work.loc[group.index, "EMA_5"] = ema5
        work.loc[group.index, "OBV"] = _signed_obv(close, volume)

        if "ATR" in group.columns:
            atr = pd.to_numeric(group["ATR"], errors="coerce").replace(0, np.nan)
            work.loc[group.index, "dist_ema5_atr"] = (close - ema5) / atr

    # Garante dtype final estável e assinado.
    work["OBV"] = pd.to_numeric(work["OBV"], errors="coerce").astype("float64")
    return work


def _latest_row_for_tf(df: pd.DataFrame, tf: str) -> Optional[pd.Series]:
    if "timeframe" not in df.columns:
        return None
    frame = df[df["timeframe"].astype(str).str.upper() == tf.upper()].copy()
    if frame.empty:
        return None
    time_col = "time_brt" if "time_brt" in frame.columns else "time"
    if time_col in frame.columns:
        frame["__sort_time"] = pd.to_datetime(frame[time_col], errors="coerce")
        if "is_live_bar" in frame.columns:
            live = frame[pd.to_numeric(frame["is_live_bar"], errors="coerce").fillna(0).astype(int) == 1]
            if not live.empty:
                return live.sort_values("__sort_time").iloc[-1]
        return frame.sort_values("__sort_time").iloc[-1]
    return frame.iloc[-1]


def _recent_rows_for_tf(df: pd.DataFrame, tf: str, limit: int = 8) -> pd.DataFrame:
    if "timeframe" not in df.columns:
        return pd.DataFrame()
    frame = df[df["timeframe"].astype(str).str.upper() == tf.upper()].copy()
    if frame.empty:
        return frame
    time_col = "time_brt" if "time_brt" in frame.columns else "time"
    if time_col in frame.columns:
        frame["__sort_time"] = pd.to_datetime(frame[time_col], errors="coerce")
        frame = frame.sort_values("__sort_time")
    return frame.tail(limit)


def _side_from_row(row: pd.Series) -> str:
    ema5 = _safe_float(row.get("EMA_5"))
    ema20 = _safe_float(row.get("EMA_20"))
    close = _safe_float(row.get("close"))
    slope20 = _safe_float(row.get("ema20_slope_5"), 0.0)
    adx_pos = _safe_float(row.get("ADX_Positive"), 0.0)
    adx_neg = _safe_float(row.get("ADX_Negative"), 0.0)
    if all(math.isfinite(x) for x in (ema5, ema20, close)):
        if ema5 > ema20 and close >= ema5 and slope20 >= 0 and adx_pos >= adx_neg:
            return "BUY"
        if ema5 < ema20 and close <= ema5 and slope20 <= 0 and adx_neg >= adx_pos:
            return "SELL"
    return "NEUTRAL"


def _ema_relation(row: pd.Series) -> str:
    ema5 = _safe_float(row.get("EMA_5"))
    ema20 = _safe_float(row.get("EMA_20"))
    if not math.isfinite(ema5) or not math.isfinite(ema20):
        return "FLAT"
    if ema5 > ema20:
        return "ABOVE"
    if ema5 < ema20:
        return "BELOW"
    return "FLAT"


def _price_position(row: pd.Series) -> str:
    close = _safe_float(row.get("close"))
    ema5 = _safe_float(row.get("EMA_5"))
    ema20 = _safe_float(row.get("EMA_20"))
    if not all(math.isfinite(x) for x in (close, ema5, ema20)):
        return "UNKNOWN"
    upper = max(ema5, ema20)
    lower = min(ema5, ema20)
    if close > upper:
        return "ABOVE_FAST" if ema5 >= ema20 else "ABOVE_SLOW"
    if close < lower:
        return "BELOW_SLOW" if ema5 >= ema20 else "BELOW_FAST"
    return "BETWEEN_FAST_SLOW"


def _small_pullback(recent: pd.DataFrame, row: pd.Series) -> bool:
    if recent.empty:
        return False
    if "range_atr" in recent.columns:
        ranges = pd.to_numeric(recent["range_atr"], errors="coerce").dropna()
        current = _safe_float(row.get("range_atr"))
        if not ranges.empty and math.isfinite(current):
            return current <= max(1.0, float(ranges.tail(6).median()) * 1.15)
    return False


def build_ema_exhaustion_context(row: pd.Series, recent: pd.DataFrame, tf: str) -> Dict[str, Any]:
    close = _safe_float(row.get("close"))
    ema5 = _safe_float(row.get("EMA_5"))
    ema20 = _safe_float(row.get("EMA_20"))
    atr = _safe_float(row.get("ATR"))
    adx = _safe_float(row.get("ADX"), 0.0)
    adx_pos = _safe_float(row.get("ADX_Positive"), 0.0)
    adx_neg = _safe_float(row.get("ADX_Negative"), 0.0)
    slope20 = _safe_float(row.get("ema20_slope_5"), 0.0)
    slope50 = _safe_float(row.get("ema50_slope_5"), 0.0)
    close_pos = _safe_float(row.get("close_pos"), 0.5)
    range_atr = _safe_float(row.get("range_atr"), 0.0)
    body_atr = _safe_float(row.get("body_atr"), 0.0)
    vol_ratio = _safe_float(row.get("vol_ratio"), float("nan"))
    volume_pace = _safe_float(row.get("volume_pace_ratio"), float("nan"))

    dist_fast = _safe_div(close - ema5, atr) if all(math.isfinite(x) for x in (close, ema5, atr)) else None
    dist_slow = _safe_div(close - ema20, atr) if all(math.isfinite(x) for x in (close, ema20, atr)) else None

    ema_side = _ema_relation(row)
    price_pos = _price_position(row)
    trend_side = _side_from_row(row)

    sweep_high = _safe_bool(row, "sweep_high") or _safe_bool(row, "swing_sweep_high")
    sweep_low = _safe_bool(row, "sweep_low") or _safe_bool(row, "swing_sweep_low")
    false_up = _safe_bool(row, "false_breakout_up")
    false_down = _safe_bool(row, "false_breakout_down")
    breakout_up = _safe_bool(row, "breakout_up")
    breakout_down = _safe_bool(row, "breakout_down")

    volume_confirming = False
    volume_diverging = False
    if math.isfinite(vol_ratio):
        volume_confirming = vol_ratio >= 1.0
        volume_diverging = vol_ratio < 0.75
    if math.isfinite(volume_pace):
        volume_confirming = volume_confirming or volume_pace >= 1.0
        volume_diverging = volume_diverging and volume_pace < 0.75

    trend_up = ema_side == "ABOVE" and slope20 >= 0 and adx_pos >= adx_neg
    trend_down = ema_side == "BELOW" and slope20 <= 0 and adx_neg >= adx_pos
    healthy_adx = adx >= ADX_HEALTHY_MIN
    extended_above = dist_slow is not None and dist_slow > EXTENDED_ATR_THRESHOLD
    extended_below = dist_slow is not None and dist_slow < -EXTENDED_ATR_THRESHOLD
    extended = bool(extended_above or extended_below or range_atr >= 1.35 or body_atr >= 0.85)

    pullback_state = "NONE"
    if trend_up and close < ema5 and close >= ema20 and _small_pullback(recent, row):
        pullback_state = "HEALTHY_PULLBACK"
    elif trend_down and close > ema5 and close <= ema20 and _small_pullback(recent, row):
        pullback_state = "HEALTHY_PULLBACK"
    elif extended_above:
        pullback_state = "EXTENDED_ABOVE_EMA20"
    elif extended_below:
        pullback_state = "EXTENDED_BELOW_EMA20"

    exhaustion_event_up = (breakout_up or sweep_high or false_up) and (close_pos <= 0.65 or false_up or sweep_high)
    exhaustion_event_down = (breakout_down or sweep_low or false_down) and (close_pos >= 0.35 or false_down or sweep_low)
    exhaustion_risk = "LOW"
    if (exhaustion_event_up and extended_above) or (exhaustion_event_down and extended_below):
        exhaustion_risk = "HIGH"
    elif exhaustion_event_up or exhaustion_event_down or extended:
        exhaustion_risk = "MEDIUM"

    consolidation = (
        price_pos == "BETWEEN_FAST_SLOW"
        and adx < ADX_STRONG_MIN
        and range_atr <= 0.85
        and not breakout_up
        and not breakout_down
    )

    trend_continuation_buy = (
        trend_up
        and close >= ema5
        and healthy_adx
        and close_pos >= 0.65
        and not volume_diverging
        and not exhaustion_event_up
    )
    trend_continuation_sell = (
        trend_down
        and close <= ema5
        and healthy_adx
        and close_pos <= 0.35
        and not volume_diverging
        and not exhaustion_event_down
    )

    if consolidation:
        entry_quality = "CONSOLIDATION"
        preferred_action = "WAIT"
    elif exhaustion_risk == "HIGH":
        entry_quality = "WAIT_CONFIRMATION"
        preferred_action = "WAIT"
    elif extended_above:
        entry_quality = "LATE_BUY_RISK"
        preferred_action = "WAIT_PULLBACK"
    elif extended_below:
        entry_quality = "LATE_SELL_RISK"
        preferred_action = "WAIT_PULLBACK"
    elif pullback_state == "HEALTHY_PULLBACK":
        entry_quality = "WAIT_CONFIRMATION"
        preferred_action = "WAIT_RECLAIM"
    elif trend_continuation_buy:
        entry_quality = "GOOD"
        preferred_action = "BUY_CONTINUATION"
    elif trend_continuation_sell:
        entry_quality = "GOOD"
        preferred_action = "SELL_CONTINUATION"
    else:
        entry_quality = "WAIT_CONFIRMATION"
        preferred_action = "WAIT"

    return {
        "ema_fast_period": FAST_EMA,
        "ema_slow_period": SLOW_EMA,
        "ema_fast": _rounded(ema5),
        "ema_slow": _rounded(ema20),
        "price_vs_ema_fast_atr": _rounded(dist_fast),
        "price_vs_ema_slow_atr": _rounded(dist_slow),
        "ema_fast_vs_slow": ema_side,
        "price_position": price_pos,
        "pullback_state": pullback_state,
        "exhaustion_risk": exhaustion_risk,
        "entry_quality": entry_quality,
        "preferred_action": preferred_action,
        "trend_side": trend_side,
        "diagnostics": {
            "adx": _rounded(adx),
            "adx_positive": _rounded(adx_pos),
            "adx_negative": _rounded(adx_neg),
            "ema20_slope_5": _rounded(slope20, 8),
            "ema50_slope_5": _rounded(slope50, 8),
            "range_atr": _rounded(range_atr),
            "body_atr": _rounded(body_atr),
            "close_pos": _rounded(close_pos),
            "volume_ratio": _rounded(vol_ratio),
            "volume_pace_ratio": _rounded(volume_pace),
            "breakout_up": breakout_up,
            "breakout_down": breakout_down,
            "sweep_high": sweep_high,
            "sweep_low": sweep_low,
            "false_breakout_up": false_up,
            "false_breakout_down": false_down,
            "volume_confirming_or_neutral": volume_confirming or not volume_diverging,
        },
        "semantics": "Entrada boa exige timing e gatilho; exaustão bloqueia perseguição, mas não libera reversão automática.",
    }


def _tf_side(context: Optional[Dict[str, Any]]) -> str:
    if not context:
        return "NEUTRAL"
    preferred = str(context.get("preferred_action", "")).upper()
    trend = str(context.get("trend_side", "NEUTRAL")).upper()
    if preferred.startswith("BUY") or trend == "BUY":
        return "BUY"
    if preferred.startswith("SELL") or trend == "SELL":
        return "SELL"
    return "NEUTRAL"


def _state_from_contexts(contexts: Dict[str, Dict[str, Any]]) -> str:
    ordered = [contexts.get(tf, {}) for tf in ("H1", "M15", "M5", "M1")]
    qualities = [str(c.get("entry_quality", "")).upper() for c in ordered if c]
    pullbacks = [str(c.get("pullback_state", "")).upper() for c in ordered if c]
    exhaustions = [str(c.get("exhaustion_risk", "LOW")).upper() for c in ordered if c]
    if "HIGH" in exhaustions:
        return "EXHAUSTION_RISK"
    if any(q in {"LATE_BUY_RISK", "LATE_SELL_RISK"} for q in qualities):
        return "EXTENDED_MOVE"
    if "HEALTHY_PULLBACK" in pullbacks:
        return "HEALTHY_PULLBACK"
    if "CONSOLIDATION" in qualities:
        return "CONSOLIDATION"
    if any(q == "GOOD" for q in qualities):
        return "TREND_CONTINUATION"
    return "CONSOLIDATION"


def build_execution_quality(contexts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    h1 = contexts.get("H1", {})
    m15 = contexts.get("M15", {})
    m5 = contexts.get("M5", {})
    m1 = contexts.get("M1", {})

    htf_side = _tf_side(h1)
    setup_side = _tf_side(m15)
    trigger_side = _tf_side(m5)
    micro_side = _tf_side(m1)
    state = _state_from_contexts(contexts)

    buy_allowed = True
    sell_allowed = True
    buy_reasons: list[str] = []
    sell_reasons: list[str] = []

    m5_quality = str(m5.get("entry_quality", "")).upper()
    m5_pref = str(m5.get("preferred_action", "")).upper()
    m5_price_pos = str(m5.get("price_position", "")).upper()
    m5_diag = m5.get("diagnostics", {}) if isinstance(m5.get("diagnostics"), dict) else {}
    m5_exhaustion = str(m5.get("exhaustion_risk", "LOW")).upper()

    if m5_quality == "LATE_BUY_RISK" or (m5_exhaustion == "HIGH" and m5_diag.get("false_breakout_up")):
        buy_allowed = False
        buy_reasons.append("M5_LATE_BUY_OR_EXHAUSTION_RISK")
    if m5_quality == "LATE_SELL_RISK" or (m5_exhaustion == "HIGH" and m5_diag.get("false_breakout_down")):
        sell_allowed = False
        sell_reasons.append("M5_LATE_SELL_OR_EXHAUSTION_RISK")

    if htf_side == "BUY" and m5_price_pos in {"BELOW_SLOW", "BELOW_FAST"}:
        buy_allowed = False
        buy_reasons.append("HTF_BUY_BUT_M5_BELOW_EMA_FAST_SLOW_WAIT_RECLAIM")
    if htf_side == "SELL" and m5_price_pos in {"ABOVE_FAST", "ABOVE_SLOW"}:
        sell_allowed = False
        sell_reasons.append("HTF_SELL_BUT_M5_ABOVE_EMA_FAST_SLOW_WAIT_RECLAIM")

    if state == "CONSOLIDATION":
        buy_allowed = False
        sell_allowed = False
        buy_reasons.append("CONSOLIDATION_WAIT_BREAKOUT_OR_REJECTION")
        sell_reasons.append("CONSOLIDATION_WAIT_BREAKOUT_OR_REJECTION")

    if state == "EXHAUSTION_RISK":
        if trigger_side == "BUY" or m5_diag.get("false_breakout_up") or m5_diag.get("sweep_high"):
            buy_allowed = False
            buy_reasons.append("EXHAUSTION_BLOCKS_BUY_CHASE")
        if trigger_side == "SELL" or m5_diag.get("false_breakout_down") or m5_diag.get("sweep_low"):
            sell_allowed = False
            sell_reasons.append("EXHAUSTION_BLOCKS_SELL_CHASE")

    if not buy_allowed:
        next_buy_trigger = "Aguardar reclaim/fechamento acima da EMA5/EMA20 no M5 e gatilho M1 a favor."
    elif m5_pref in {"BUY_CONTINUATION", "WAIT_RECLAIM"}:
        next_buy_trigger = "Compra só com candle M5/M1 confirmando retomada, sem entrada atrasada."
    else:
        next_buy_trigger = "Aguardar pullback, reclaim ou rompimento limpo."

    if not sell_allowed:
        next_sell_trigger = "Aguardar perda/reclaim inverso da EMA5/EMA20 no M5 e gatilho M1 a favor."
    elif m5_pref in {"SELL_CONTINUATION", "WAIT_RECLAIM"}:
        next_sell_trigger = "Venda só com candle M5/M1 confirmando retomada, sem entrada atrasada."
    else:
        next_sell_trigger = "Aguardar pullback, rejeição ou rompimento limpo."

    if not buy_allowed and not sell_allowed:
        summary = "Ambos os lados exigem espera: contexto atual não oferece entrada limpa pelo bloco de qualidade de execução."
    elif buy_allowed and not sell_allowed:
        summary = "Compra pode ser considerada apenas com gatilho M5/M1; venda está bloqueada pelo contexto de execução."
    elif sell_allowed and not buy_allowed:
        summary = "Venda pode ser considerada apenas com gatilho M5/M1; compra está bloqueada pelo contexto de execução."
    else:
        summary = "Nenhum hard block de EMA/exaustão, mas ainda exige região, candle fechado e gatilho operacional."

    return {
        "htf_trend_side": htf_side,
        "setup_side_m15": setup_side,
        "trigger_side_m5": trigger_side,
        "micro_side_m1": micro_side,
        "state": state,
        "buy_allowed": bool(buy_allowed),
        "sell_allowed": bool(sell_allowed),
        "buy_block_reason": "; ".join(dict.fromkeys(buy_reasons)),
        "sell_block_reason": "; ".join(dict.fromkeys(sell_reasons)),
        "next_buy_trigger": next_buy_trigger,
        "next_sell_trigger": next_sell_trigger,
        "summary": summary,
        "guard_rule": "Nunca transformar exaustão em sinal contrário automático; exaustão bloqueia perseguição e exige confirmação.",
    }


def update_timeframe_parquets(root: Path, symbol: str, market_df: pd.DataFrame) -> None:
    if "timeframe" not in market_df.columns:
        return
    for tf in TF_ORDER:
        path = root / "data" / f"{symbol}_{tf}.parquet"
        if not path.exists():
            continue
        tf_df = market_df[market_df["timeframe"].astype(str).str.upper() == tf].copy()
        if tf_df.empty:
            continue
        _save_table(tf_df, path)
        print(f"[OK] Timeframe parquet atualizado: {path}")


def enrich_payload(symbol: str, market_path: Path, payload_path: Path, output_path: Path, write_market: bool, write_tfs: bool, root: Path) -> None:
    market_df = ensure_ema5_features(_load_table(market_path))
    payload = _load_json(payload_path)

    contexts: Dict[str, Dict[str, Any]] = {}
    for tf in TF_ORDER:
        row = _latest_row_for_tf(market_df, tf)
        if row is None:
            continue
        recent = _recent_rows_for_tf(market_df, tf, limit=10)
        ctx = build_ema_exhaustion_context(row, recent, tf)
        contexts[tf] = ctx

        tf_payload = payload.setdefault("timeframes", {}).setdefault(tf, {})
        tf_payload["ema_exhaustion_context"] = ctx
        tf_payload.setdefault("indicators_exact", {})["EMA_5"] = _rounded(row.get("EMA_5"))
        tf_payload.setdefault("indicators_exact", {})["OBV"] = _rounded(row.get("OBV"), 2)
        tf_payload.setdefault("derived_metrics_exact", {})["dist_ema5_atr"] = _rounded(row.get("dist_ema5_atr"))

    payload["execution_quality"] = build_execution_quality(contexts)
    payload.setdefault("data_semantics", {})["ema_exhaustion_context"] = (
        "Camada de qualidade de entrada baseada em EMA5/EMA20, ATR, ADX, slopes, volume, candles e eventos. "
        "Bloqueia perseguição e entradas atrasadas; não libera reversão automática."
    )
    payload.setdefault("data_semantics", {})["execution_quality"] = (
        "Bloco consolidado de leitura operacional. buy_allowed/sell_allowed são filtros de qualidade, "
        "não ordens automáticas. Ainda exigem região, candle fechado e gatilho M5/M1."
    )
    payload.setdefault("data_limitations", {})["ema_exhaustion_decision_rule"] = (
        "Exaustão bloqueia chase, mas não autoriza operar contra sem confirmação independente."
    )
    payload.setdefault("data_quality_fixes", {})["OBV"] = (
        "OBV recalculado como float64 assinado no enrichment para evitar overflow uint64 em valores negativos."
    )
    payload["ema_exhaustion_enriched_at_utc"] = datetime.now(timezone.utc).isoformat()

    _write_json(output_path, payload)
    print(f"[OK] Payload enriquecido: {output_path}")
    print("[OK] OBV recalculado como série assinada no payload/consolidado")

    if write_market:
        _save_table(market_df, market_path)
        print(f"[OK] Market data atualizado com EMA_5/dist_ema5_atr/OBV assinado: {market_path}")
    if write_tfs:
        update_timeframe_parquets(root, symbol, market_df)


def main() -> int:
    args = _args()
    root = args.project_root.resolve()
    symbol = args.symbol.upper()
    market_path = args.market_data or _default_market_path(root, symbol)
    payload_path = args.payload or _default_payload_path(root, symbol)
    output_path = args.output or payload_path

    enrich_payload(
        symbol=symbol,
        market_path=market_path,
        payload_path=payload_path,
        output_path=output_path,
        write_market=args.write_market_data,
        write_tfs=args.write_timeframe_parquets,
        root=root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
