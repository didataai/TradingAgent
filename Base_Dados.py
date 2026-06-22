# -*- coding: utf-8 -*-
"""
TradingAgent — MT5 Multi-Timeframe Feature Builder

Objetivos principais
-------------------
- Ler toda a configuração do arquivo ``tradingagent.json``.
- Executar modos diferentes: full_rebuild, intraday_refresh,
  daily_refresh e contexts_only.
- Coletar candles fechados e, opcionalmente, a barra atual em formação.
- Calcular indicadores, padrões, volume, volatilidade, estrutura causal,
  sweeps, FVG, Fibonacci direcional, sessões e contexto da barra live.
- Salvar um Parquet por ativo/timeframe e consolidado por ativo.
- Manter labels futuros separados e desabilitados no modo intraday.

Requisitos
----------
pip install MetaTrader5 pandas numpy ta pyarrow

Execução
--------
python Base_Dados.py --mode full_rebuild
python Base_Dados.py --mode intraday_refresh
python Base_Dados.py --mode daily_refresh
python Base_Dados.py --mode contexts_only

Observações
-----------
- O arquivo ``tradingagent.json`` deve estar na raiz do projeto ou ser
  informado com ``--config``.
- O modo contexts_only não conecta ao MT5; ele apenas valida os Parquets
  existentes e prepara a estrutura para os módulos de contexto.
- A coluna ``is_live_bar`` diferencia a barra em formação das barras fechadas.
- Features de confirmação usam, por padrão, somente barras fechadas.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError as exc:  # pragma: no cover - depende do ambiente Windows/MT5
    raise SystemExit(
        "MetaTrader5 não instalado. Execute: pip install MetaTrader5"
    ) from exc

try:
    import ta
except ImportError as exc:
    raise SystemExit("Pacote 'ta' não instalado. Execute: pip install ta") from exc


# =============================================================================
# Logging
# =============================================================================

LOGGER = logging.getLogger("TradingAgent.BaseDados")


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, str(level).upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


# =============================================================================
# Constantes
# =============================================================================

SUPPORTED_TIMEFRAMES: Tuple[str, ...] = (
    "M1",
    "M5",
    "M15",
    "H1",
    "H4",
    "D1",
    "W1",
    "MN1",
)

TIMEFRAME_SECONDS: Dict[str, int] = {
    "M1": 60,
    "M5": 5 * 60,
    "M15": 15 * 60,
    "H1": 60 * 60,
    "H4": 4 * 60 * 60,
    "D1": 24 * 60 * 60,
    "W1": 7 * 24 * 60 * 60,
    "MN1": 30 * 24 * 60 * 60,
}

MT5_TIMEFRAMES: Dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}

LABEL_COLUMNS: Tuple[str, ...] = (
    "dir_signal",
    "tb_y",
    "tb_exit_type",
    "tb_exit_idx",
    "tb_r_atr",
    "meta_label",
)

FLAG_COLUMNS: Tuple[str, ...] = (
    "Hammer",
    "Inverted_Hammer",
    "Bullish_Engulfing",
    "Bearish_Engulfing",
    "Doji",
    "Bullish_Marubozu",
    "Bearish_Marubozu",
    "Shooting_Star",
    "Hanging_Man",
    "Morning_Star",
    "Evening_Star",
    "Three_White_Soldiers",
    "Three_Black_Crows",
    "Piercing_Line",
    "Dark_Cloud_Cover",
    "Tweezer_Tops",
    "Tweezer_Bottoms",
    "Gap_Up",
    "Gap_Down",
    "Volume_Spike",
    "close_above_prev_close",
    "close_below_prev_close",
    "high_above_prev_high",
    "low_below_prev_low",
    "inside_previous_range",
    "outside_previous_range",
    "breakout_up",
    "breakout_down",
    "false_breakout_up",
    "false_breakout_down",
    "range_expansion_vs_prev",
    "sweep_high",
    "sweep_low",
    "swing_sweep_high",
    "swing_sweep_low",
    "fvg_up",
    "fvg_dn",
    "compression_flag",
    "expansion_flag",
    "swing_high_confirmed",
    "swing_low_confirmed",
    "bos_up",
    "bos_dn",
    "choch_up",
    "choch_dn",
    "ema20_above_ema50",
    "ema_cross_up",
    "ema_cross_dn",
    "zigzag_high_confirmed",
    "zigzag_low_confirmed",
    "in_bull_ob_candidate",
    "in_bear_ob_candidate",
    "mitigated_bull_ob_candidate",
    "mitigated_bear_ob_candidate",
    "in_asia_session",
    "in_london_session",
    "in_ny_session",
    "london_killzone",
    "ny_killzone",
    "is_london_open_bar",
    "is_ny_open_bar",
    "is_live_bar",
    "is_warmup",
    "ready_for_train",
    "ready_for_realtime",
    "vol_spike_1p5",
    "vol_spike_2p0",
)


# =============================================================================
# Configuração
# =============================================================================


def load_tradingagent_config(path: str | Path = "tradingagent.json") -> Dict[str, Any]:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {cfg_path}")

    try:
        with cfg_path.open("r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido em {cfg_path}: {exc}") from exc

    if not isinstance(config, dict):
        raise ValueError("tradingagent.json precisa conter um objeto JSON na raiz.")

    config["_config_path"] = str(cfg_path)
    config["_project_root"] = str(cfg_path.parent)
    validate_config(config)
    LOGGER.info("Config TradingAgent carregada: %s", cfg_path)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    required_sections = ("mt5", "data", "universe", "pipeline_modes")
    missing = [section for section in required_sections if section not in config]
    if missing:
        raise ValueError(f"Seções obrigatórias ausentes no tradingagent.json: {missing}")

    mt5_cfg = config.get("mt5", {})
    for key in ("path", "account", "server"):
        if key not in mt5_cfg:
            raise ValueError(f"Configuração MT5 ausente: mt5.{key}")


def resolve_project_path(config: Mapping[str, Any], value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(str(config.get("_project_root", "."))) / path


def get_mode_config(config: Mapping[str, Any], mode: str) -> Dict[str, Any]:
    modes = config.get("pipeline_modes", {})
    if mode not in modes:
        valid = ", ".join(sorted(modes.keys()))
        raise ValueError(f"Modo inválido '{mode}'. Modos disponíveis: {valid}")
    result = dict(modes[mode])
    result["name"] = mode
    return result


def normalize_symbols(symbols: Sequence[str]) -> List[str]:
    output: List[str] = []
    seen = set()
    for symbol in symbols:
        normalized = str(symbol).strip().upper()
        if normalized and normalized not in seen:
            output.append(normalized)
            seen.add(normalized)
    return output


def normalize_timeframes(timeframes: Sequence[str]) -> List[str]:
    requested = {str(tf).strip().upper() for tf in timeframes if str(tf).strip()}
    unknown = sorted(requested - set(SUPPORTED_TIMEFRAMES))
    if unknown:
        LOGGER.warning("Timeframes ignorados por não serem suportados: %s", unknown)
    return [tf for tf in SUPPORTED_TIMEFRAMES if tf in requested]


# =============================================================================
# Helpers numéricos e temporais
# =============================================================================


def safe_div(a: Any, b: Any, eps: float = 1e-9) -> Any:
    return a / (b + eps)


def rolling_zscore(series: pd.Series, window: int = 200) -> pd.Series:
    mean = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std(ddof=0)
    return (series - mean) / (std + 1e-9)


def nanify_initial_window(series: pd.Series, window: int) -> pd.Series:
    if series is None or len(series) == 0:
        return series
    output = series.copy()
    output.iloc[: min(window - 1, len(output))] = np.nan
    return output


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    if "tick_volume" not in output.columns:
        output["tick_volume"] = np.nan
    if "spread" not in output.columns:
        output["spread"] = 0.0
    if "real_volume" not in output.columns:
        output["real_volume"] = np.nan
    return output


def coerce_numeric_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    numeric_columns = (
        "open",
        "high",
        "low",
        "close",
        "tick_volume",
        "real_volume",
        "spread",
    )
    for column in numeric_columns:
        if column in output.columns:
            output[column] = pd.to_numeric(output[column], errors="coerce")
    return output


def tz_convert_naive_from_utc(series_utc_naive: pd.Series, tz_name: str) -> pd.Series:
    series = pd.to_datetime(series_utc_naive, errors="coerce")
    aware = series.dt.tz_localize("UTC")
    return aware.dt.tz_convert(tz_name).dt.tz_localize(None)


def broker_wall_clock_to_utc_naive(
    series_broker_naive: pd.Series,
    broker_timezone: str,
) -> pd.Series:
    """
    Interpreta timestamps naive como horário de parede do servidor/broker
    e converte para UTC naive.

    Exemplo: 21:44 no broker UTC+2 -> 19:44 UTC.
    """
    series = pd.to_datetime(series_broker_naive, errors="coerce")
    aware = series.dt.tz_localize(
        broker_timezone,
        ambiguous="infer",
        nonexistent="shift_forward",
    )
    return aware.dt.tz_convert("UTC").dt.tz_localize(None)


def add_time_columns(
    base: pd.DataFrame,
    broker_timezone: str,
    brt_timezone: str,
    london_timezone: str,
    ny_timezone: str,
) -> pd.DataFrame:
    output = base.copy()

    output["time_broker"] = tz_convert_naive_from_utc(output["time"], broker_timezone)
    output["time_brt"] = tz_convert_naive_from_utc(output["time"], brt_timezone)
    output["time_london"] = tz_convert_naive_from_utc(output["time"], london_timezone)
    output["time_ny"] = tz_convert_naive_from_utc(output["time"], ny_timezone)

    for suffix in ("broker", "brt", "london", "ny"):
        column = f"time_{suffix}"
        output[f"hour_{suffix}"] = output[column].dt.hour.astype("Int64")
        output[f"minute_{suffix}"] = output[column].dt.minute.astype("Int64")

    output["day_of_week"] = output["time_brt"].dt.dayofweek.astype("Int64")
    output["date_brt"] = output["time_brt"].dt.date
    return output


def infer_live_bar_mask(df: pd.DataFrame, include_live_bar: bool) -> pd.Series:
    mask = pd.Series(0, index=df.index, dtype="int8")
    if include_live_bar and not df.empty:
        mask.iloc[-1] = 1
    return mask


def get_closed_view(df: pd.DataFrame) -> pd.DataFrame:
    if "is_live_bar" not in df.columns:
        return df.copy()
    return df.loc[df["is_live_bar"].fillna(0).astype(int) == 0].copy()


# =============================================================================
# MT5
# =============================================================================


def initialize_mt5(config: Mapping[str, Any]) -> bool:
    mt5_cfg = config["mt5"]
    path = str(mt5_cfg["path"])
    account = int(mt5_cfg["account"])
    server = str(mt5_cfg["server"])
    password = str(mt5_cfg.get("password", ""))

    kwargs: Dict[str, Any] = {
        "path": path,
        "login": account,
        "server": server,
    }
    if password:
        kwargs["password"] = password

    if not mt5.initialize(**kwargs):
        LOGGER.error("Falha ao conectar à conta #%s: %s", account, mt5.last_error())
        return False

    LOGGER.info("Conectado ao MT5 | conta=%s server=%s", account, server)
    return True


def detect_server_name(fallback_server: str) -> str:
    try:
        info = mt5.account_info()
        if info is not None and getattr(info, "server", None):
            return str(info.server)
    except Exception:
        pass
    return fallback_server


def resolve_broker_timezone(config: Mapping[str, Any], server_name: str) -> str:
    mt5_cfg = config.get("mt5", {})
    direct_tz = str(mt5_cfg.get("broker_timezone", "UTC"))

    map_path_value = mt5_cfg.get("broker_timezone_map")
    if not map_path_value:
        return direct_tz

    map_path = resolve_project_path(config, str(map_path_value))
    if not map_path.exists():
        LOGGER.warning("Mapa de timezone não encontrado: %s. Usando %s", map_path, direct_tz)
        return direct_tz

    try:
        with map_path.open("r", encoding="utf-8") as handle:
            mapping = json.load(handle)
        if isinstance(mapping, dict):
            return str(mapping.get(server_name, direct_tz))
    except Exception as exc:
        LOGGER.warning("Falha ao ler mapa de timezone: %s", exc)

    return direct_tz


def resolve_mt5_symbol(symbol: str) -> Optional[str]:
    """
    Resolve o nome real do símbolo no MT5 sem alterar a chave interna usada
    pelo TradingAgent.

    Primeiro tenta correspondência exata. Se não encontrar, procura uma
    correspondência case-insensitive (por exemplo, BRENT -> Brent e
    USAIND -> UsaInd). Isso preserva o comportamento atual do intraday,
    que usa chaves/arquivos em maiúsculas, e apenas corrige o nome enviado
    à API do MT5.
    """
    requested = str(symbol).strip()
    if not requested:
        return None

    info = mt5.symbol_info(requested)
    if info is not None:
        resolved = requested
    else:
        available = mt5.symbols_get()
        if available is None:
            LOGGER.error(
                "Não foi possível listar símbolos do MT5: %s",
                mt5.last_error(),
            )
            return None

        requested_key = requested.casefold()
        resolved = next(
            (item.name for item in available if item.name.casefold() == requested_key),
            None,
        )
        if resolved is None:
            LOGGER.error("Símbolo não encontrado no MT5: %s", requested)
            return None

        LOGGER.warning(
            "Símbolo resolvido pelo MT5 | solicitado=%s | real=%s",
            requested,
            resolved,
        )
        info = mt5.symbol_info(resolved)

    if info is None:
        LOGGER.error("Falha ao obter informações do símbolo: %s", resolved)
        return None

    if not info.visible and not mt5.symbol_select(resolved, True):
        LOGGER.error("Não foi possível habilitar o símbolo: %s", resolved)
        return None

    return resolved


def ensure_symbol_available(symbol: str) -> bool:
    """Compatibilidade com chamadas existentes."""
    return resolve_mt5_symbol(symbol) is not None


def collect_mt5_rates(
    symbol: str,
    timeframe_name: str,
    count: int,
    include_live_bar: bool,
    broker_timezone: str,
    timestamp_source: str = "utc_epoch",
) -> pd.DataFrame:
    mt5_symbol = resolve_mt5_symbol(symbol)
    if mt5_symbol is None:
        return pd.DataFrame()

    timeframe = MT5_TIMEFRAMES[timeframe_name]
    start_pos = 0 if include_live_bar else 1
    rates = mt5.copy_rates_from_pos(mt5_symbol, timeframe, start_pos, int(count))

    if rates is None or len(rates) == 0:
        LOGGER.warning("Sem dados para %s (MT5=%s) %s", symbol, mt5_symbol, timeframe_name)
        return pd.DataFrame()

    base = pd.DataFrame(rates)

    raw_time = pd.to_datetime(base["time"], unit="s", errors="coerce")
    timestamp_source = str(timestamp_source).strip().lower()

    if timestamp_source == "broker_wall_clock":
        # Alguns terminais/brokers expõem o epoch como se fosse o relógio
        # local do servidor. Preservamos o valor bruto como time_broker_raw
        # e convertemos corretamente para UTC.
        base["time_broker_raw"] = raw_time
        base["time"] = broker_wall_clock_to_utc_naive(
            raw_time,
            broker_timezone,
        )
    elif timestamp_source == "utc_epoch":
        base["time"] = pd.to_datetime(
            base["time"],
            unit="s",
            utc=True,
            errors="coerce",
        ).dt.tz_convert(None)
    else:
        raise ValueError(
            "mt5.timestamp_source inválido. Use 'utc_epoch' ou "
            "'broker_wall_clock'."
        )

    base = base.sort_values("time").reset_index(drop=True)
    base = ensure_columns(base)
    base = coerce_numeric_ohlc(base)
    base["symbol"] = symbol
    base["timeframe"] = timeframe_name
    base["is_live_bar"] = infer_live_bar_mask(base, include_live_bar)
    return base


# =============================================================================
# Features básicas e indicadores
# =============================================================================


def calculate_indicators_block(
    df: pd.DataFrame,
    atr_window: int = 14,
) -> pd.DataFrame:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["tick_volume"]

    sma10 = ta.trend.sma_indicator(close, window=10)
    sma50 = ta.trend.sma_indicator(close, window=50)
    sma200 = ta.trend.sma_indicator(close, window=200)
    ema20 = ta.trend.ema_indicator(close, window=20)
    ema50 = ta.trend.ema_indicator(close, window=50)
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi()

    macd_obj = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    bb_obj = ta.volatility.BollingerBands(close, window=20, window_dev=2)

    atr_raw = ta.volatility.AverageTrueRange(
        high,
        low,
        close,
        window=atr_window,
    ).average_true_range()
    atr = nanify_initial_window(atr_raw, atr_window)

    adx_obj = ta.trend.ADXIndicator(high, low, close, window=14)
    stoch_obj = ta.momentum.StochasticOscillator(
        high,
        low,
        close,
        window=14,
        smooth_window=3,
    )
    ichi = ta.trend.IchimokuIndicator(high, low, window1=9, window2=26, window3=52)
    vortex = ta.trend.VortexIndicator(high, low, close, window=14)

    return pd.DataFrame(
        {
            "Volume_MA_10": volume.rolling(10, min_periods=10).mean(),
            "Volume_MA_20": volume.rolling(20, min_periods=20).mean(),
            "SMA_10": sma10,
            "SMA_50": sma50,
            "SMA_200": sma200,
            "EMA_20": ema20,
            "EMA_50": ema50,
            "RSI": rsi,
            "MACD": macd_obj.macd(),
            "MACD_signal": macd_obj.macd_signal(),
            "MACD_hist": macd_obj.macd_diff(),
            "Bollinger_High": bb_obj.bollinger_hband(),
            "Bollinger_Mid": bb_obj.bollinger_mavg(),
            "Bollinger_Low": bb_obj.bollinger_lband(),
            "ATR": atr,
            "ADX": adx_obj.adx(),
            "ADX_Positive": adx_obj.adx_pos(),
            "ADX_Negative": adx_obj.adx_neg(),
            "Stoch_K": stoch_obj.stoch(),
            "Stoch_D": stoch_obj.stoch_signal(),
            "Ichimoku_Base": ichi.ichimoku_base_line(),
            "Ichimoku_Conversion": ichi.ichimoku_conversion_line(),
            "Ichimoku_A": ichi.ichimoku_a(),
            "Ichimoku_B": ichi.ichimoku_b(),
            "OBV": ta.volume.OnBalanceVolumeIndicator(close, volume).on_balance_volume(),
            "MFI": ta.volume.MFIIndicator(high, low, close, volume, window=14).money_flow_index(),
            "Williams_%R": ta.momentum.WilliamsRIndicator(high, low, close, lbp=14).williams_r(),
            "ROC": ta.momentum.ROCIndicator(close, window=12).roc(),
            "Parabolic_SAR": ta.trend.PSARIndicator(high, low, close).psar(),
            "Vortex_Positive": vortex.vortex_indicator_pos(),
            "Vortex_Negative": vortex.vortex_indicator_neg(),
        },
        index=df.index,
    )


def basic_price_block(df: pd.DataFrame) -> pd.DataFrame:
    range_ = (df["high"] - df["low"]).replace(0, np.nan)
    body_signed = df["close"] - df["open"]
    upper_wick = df["high"] - np.maximum(df["open"], df["close"])
    lower_wick = np.minimum(df["open"], df["close"]) - df["low"]

    return pd.DataFrame(
        {
            "ret_1": np.log(df["close"] / df["close"].shift(1)).replace([np.inf, -np.inf], np.nan),
            "ret_3": np.log(df["close"] / df["close"].shift(3)).replace([np.inf, -np.inf], np.nan),
            "ret_5": np.log(df["close"] / df["close"].shift(5)).replace([np.inf, -np.inf], np.nan),
            "range_pct": safe_div(range_, df["close"].replace(0, np.nan)),
            "body_pct": safe_div(body_signed.abs(), range_),
            "body_signed_pct": safe_div(body_signed, range_),
            "close_pos": safe_div(df["close"] - df["low"], range_),
            "upper_wick_pct": safe_div(upper_wick, range_),
            "lower_wick_pct": safe_div(lower_wick, range_),
            "body_direction": np.sign(body_signed).fillna(0).astype("int8"),
        },
        index=df.index,
    )


def previous_bar_relation_block(df: pd.DataFrame, atr: pd.Series) -> pd.DataFrame:
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)
    prev_close = df["close"].shift(1)
    current_range = (df["high"] - df["low"]).replace(0, np.nan)
    previous_range = (prev_high - prev_low).replace(0, np.nan)
    atrn = atr.replace(0, np.nan)

    inside = (df["high"] <= prev_high) & (df["low"] >= prev_low)
    outside = (df["high"] > prev_high) & (df["low"] < prev_low)
    breakout_up = df["close"] > prev_high
    breakout_down = df["close"] < prev_low
    false_breakout_up = (df["high"] > prev_high) & (df["close"] <= prev_high)
    false_breakout_down = (df["low"] < prev_low) & (df["close"] >= prev_low)

    return pd.DataFrame(
        {
            "close_above_prev_close": (df["close"] > prev_close).astype("int8"),
            "close_below_prev_close": (df["close"] < prev_close).astype("int8"),
            "high_above_prev_high": (df["high"] > prev_high).astype("int8"),
            "low_below_prev_low": (df["low"] < prev_low).astype("int8"),
            "inside_previous_range": inside.astype("int8"),
            "outside_previous_range": outside.astype("int8"),
            "breakout_up": breakout_up.astype("int8"),
            "breakout_down": breakout_down.astype("int8"),
            "false_breakout_up": false_breakout_up.astype("int8"),
            "false_breakout_down": false_breakout_down.astype("int8"),
            "range_expansion_vs_prev": (current_range > previous_range).astype("int8"),
            "range_expansion_ratio": safe_div(current_range, previous_range),
            "dist_prev_high_atr": safe_div(df["close"] - prev_high, atrn),
            "dist_prev_low_atr": safe_div(df["close"] - prev_low, atrn),
            "breakout_up_distance_atr": np.where(
                df["high"] > prev_high,
                safe_div(df["high"] - prev_high, atrn),
                0.0,
            ),
            "breakout_down_distance_atr": np.where(
                df["low"] < prev_low,
                safe_div(prev_low - df["low"], atrn),
                0.0,
            ),
        },
        index=df.index,
    )


def candle_patterns_block(df: pd.DataFrame) -> pd.DataFrame:
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]
    body = (c - o).abs()
    total_range = (h - l).replace(0, np.nan)
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - l

    bullish_engulf = (
        (c > o)
        & (c.shift(1) < o.shift(1))
        & (c >= o.shift(1))
        & (o <= c.shift(1))
    )
    bearish_engulf = (
        (c < o)
        & (c.shift(1) > o.shift(1))
        & (c <= o.shift(1))
        & (o >= c.shift(1))
    )

    body_prev2 = (c.shift(2) - o.shift(2)).abs()
    body_mid = (c.shift(1) - o.shift(1)).abs()
    body_prev = (c.shift(1) - o.shift(1)).abs()

    tolerance = total_range.rolling(20, min_periods=5).median() * 0.05

    return pd.DataFrame(
        {
            "Hammer": ((lower_shadow > 2 * body) & (upper_shadow < body)).astype("int8"),
            "Inverted_Hammer": ((upper_shadow > 2 * body) & (lower_shadow < body)).astype("int8"),
            "Bullish_Engulfing": bullish_engulf.astype("int8"),
            "Bearish_Engulfing": bearish_engulf.astype("int8"),
            "Doji": ((body / total_range) < 0.1).astype("int8"),
            "Bullish_Marubozu": (
                (c > o)
                & (safe_div(upper_shadow, total_range) < 0.05)
                & (safe_div(lower_shadow, total_range) < 0.05)
            ).astype("int8"),
            "Bearish_Marubozu": (
                (c < o)
                & (safe_div(upper_shadow, total_range) < 0.05)
                & (safe_div(lower_shadow, total_range) < 0.05)
            ).astype("int8"),
            "Shooting_Star": ((upper_shadow > 2 * body) & (lower_shadow < body)).astype("int8"),
            "Hanging_Man": ((lower_shadow > 2 * body) & (upper_shadow < body)).astype("int8"),
            "Morning_Star": (
                (c.shift(2) < o.shift(2))
                & (body_mid < 0.35 * body_prev2)
                & (c > o)
                & (c > (o.shift(2) + c.shift(2)) / 2)
            ).astype("int8"),
            "Evening_Star": (
                (c.shift(2) > o.shift(2))
                & (body_mid < 0.35 * body_prev2)
                & (c < o)
                & (c < (o.shift(2) + c.shift(2)) / 2)
            ).astype("int8"),
            "Three_White_Soldiers": (
                (c > o)
                & (c.shift(1) > o.shift(1))
                & (c.shift(2) > o.shift(2))
                & (c > c.shift(1))
                & (c.shift(1) > c.shift(2))
            ).astype("int8"),
            "Three_Black_Crows": (
                (c < o)
                & (c.shift(1) < o.shift(1))
                & (c.shift(2) < o.shift(2))
                & (c < c.shift(1))
                & (c.shift(1) < c.shift(2))
            ).astype("int8"),
            "Piercing_Line": (
                (c.shift(1) < o.shift(1))
                & (c > o)
                & (c > (o.shift(1) + c.shift(1)) / 2)
            ).astype("int8"),
            "Dark_Cloud_Cover": (
                (c.shift(1) > o.shift(1))
                & (c < o)
                & (c < (o.shift(1) + c.shift(1)) / 2)
            ).astype("int8"),
            "Tweezer_Tops": (
                ((h - h.shift(1)).abs() <= tolerance)
                & (c < o)
                & (c.shift(1) > o.shift(1))
            ).astype("int8"),
            "Tweezer_Bottoms": (
                ((l - l.shift(1)).abs() <= tolerance)
                & (c > o)
                & (c.shift(1) < o.shift(1))
            ).astype("int8"),
            "Gap_Up": (o > h.shift(1)).astype("int8"),
            "Gap_Down": (o < l.shift(1)).astype("int8"),
            "Volume_Spike": (
                df["tick_volume"] > 2 * df["tick_volume"].rolling(10, min_periods=10).mean()
            ).astype("int8"),
        },
        index=df.index,
    )


def candle_sentiment_volume_block(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    bull = (df["close"] > df["open"]).astype(int)
    bear = (df["close"] < df["open"]).astype(int)
    volume_ma20 = df["tick_volume"].rolling(20, min_periods=20).mean()
    volume_ratio = safe_div(df["tick_volume"], volume_ma20)

    return pd.DataFrame(
        {
            f"bull_ratio_{lookback}": bull.rolling(lookback, min_periods=lookback).mean(),
            f"bear_ratio_{lookback}": bear.rolling(lookback, min_periods=lookback).mean(),
            "vol_ratio": volume_ratio,
            "vol_spike_1p5": (volume_ratio >= 1.5).astype("int8"),
            "vol_spike_2p0": (volume_ratio >= 2.0).astype("int8"),
        },
        index=df.index,
    )


def regime_block(df: pd.DataFrame, indicators: pd.DataFrame, window: int) -> pd.DataFrame:
    bb_width = safe_div(
        indicators["Bollinger_High"] - indicators["Bollinger_Low"],
        df["close"].replace(0, np.nan),
    )
    return pd.DataFrame(
        {
            "BB_Width": bb_width,
            "ATR_Z": rolling_zscore(indicators["ATR"], window),
            "BB_Width_Z": rolling_zscore(bb_width, window),
        },
        index=df.index,
    )


def compression_expansion_block(
    regime: pd.DataFrame,
    compression_threshold: float,
    expansion_threshold: float,
) -> pd.DataFrame:
    compression = (
        (regime["ATR_Z"] < compression_threshold)
        & (regime["BB_Width_Z"] < compression_threshold)
    )
    expansion = (
        (regime["ATR_Z"] > expansion_threshold)
        | (regime["BB_Width_Z"] > expansion_threshold)
    )
    return pd.DataFrame(
        {
            "compression_flag": compression.astype("int8"),
            "expansion_flag": expansion.astype("int8"),
        },
        index=regime.index,
    )


def spread_block(df: pd.DataFrame, window: int = 200) -> pd.DataFrame:
    spread_pct = safe_div(df["spread"], df["close"].replace(0, np.nan))
    return pd.DataFrame(
        {
            "spread_pct": spread_pct,
            "spread_z": rolling_zscore(spread_pct, window),
        },
        index=df.index,
    )


def ema_trend_block(indicators: pd.DataFrame) -> pd.DataFrame:
    ema20 = indicators["EMA_20"]
    ema50 = indicators["EMA_50"]
    return pd.DataFrame(
        {
            "ema20_slope_5": np.log(ema20 / ema20.shift(5)).replace([np.inf, -np.inf], np.nan),
            "ema50_slope_5": np.log(ema50 / ema50.shift(5)).replace([np.inf, -np.inf], np.nan),
            "ema20_above_ema50": (ema20 > ema50).astype("int8"),
            "ema_cross_up": ((ema20 > ema50) & (ema20.shift(1) <= ema50.shift(1))).astype("int8"),
            "ema_cross_dn": ((ema20 < ema50) & (ema20.shift(1) >= ema50.shift(1))).astype("int8"),
        },
        index=indicators.index,
    )


def atr_bar_proxies_block(df: pd.DataFrame, atr: pd.Series) -> pd.DataFrame:
    atrn = atr.replace(0, np.nan)
    return pd.DataFrame(
        {
            "range_atr": safe_div(df["high"] - df["low"], atrn),
            "body_atr": safe_div((df["close"] - df["open"]).abs(), atrn),
        },
        index=df.index,
    )


def atr_distance_block(df: pd.DataFrame, indicators: pd.DataFrame) -> pd.DataFrame:
    atr = indicators["ATR"].replace(0, np.nan)
    close = df["close"]
    donchian_high = df["high"].rolling(20, min_periods=20).max()
    donchian_low = df["low"].rolling(20, min_periods=20).min()

    return pd.DataFrame(
        {
            "dist_sma10_atr": safe_div(close - indicators["SMA_10"], atr),
            "dist_sma50_atr": safe_div(close - indicators["SMA_50"], atr),
            "dist_sma200_atr": safe_div(close - indicators["SMA_200"], atr),
            "dist_ema20_atr": safe_div(close - indicators["EMA_20"], atr),
            "dist_ema50_atr": safe_div(close - indicators["EMA_50"], atr),
            "dist_bb_high_atr": safe_div(close - indicators["Bollinger_High"], atr),
            "dist_bb_low_atr": safe_div(close - indicators["Bollinger_Low"], atr),
            "dist_donchian_high20_atr": safe_div(close - donchian_high, atr),
            "dist_donchian_low20_atr": safe_div(close - donchian_low, atr),
        },
        index=df.index,
    )


# =============================================================================
# Estrutura causal, liquidez, FVG, OB candidato e Fibonacci
# =============================================================================


def confirmed_pivots_block(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """
    Pivot causal confirmado com atraso explícito de ``window`` barras.

    A barra candidata em t-window é comparada apenas quando as barras à direita
    já existem. O evento de confirmação é gravado na barra atual t; os preços do
    pivot confirmado são carregados para frente sem usar informação futura na
    linha original do pivot.
    """
    n = len(df)
    confirmed_high = np.zeros(n, dtype=np.int8)
    confirmed_low = np.zeros(n, dtype=np.int8)
    pivot_high_price = np.full(n, np.nan)
    pivot_low_price = np.full(n, np.nan)
    pivot_high_source_idx = np.full(n, -1, dtype=np.int32)
    pivot_low_source_idx = np.full(n, -1, dtype=np.int32)

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)

    for confirm_idx in range(2 * window, n):
        source_idx = confirm_idx - window
        start = source_idx - window
        end = source_idx + window + 1
        if start < 0 or end > n:
            continue

        high_window = highs[start:end]
        low_window = lows[start:end]
        source_high = highs[source_idx]
        source_low = lows[source_idx]

        if np.isfinite(source_high) and source_high >= np.nanmax(high_window):
            confirmed_high[confirm_idx] = 1
            pivot_high_price[confirm_idx] = source_high
            pivot_high_source_idx[confirm_idx] = source_idx

        if np.isfinite(source_low) and source_low <= np.nanmin(low_window):
            confirmed_low[confirm_idx] = 1
            pivot_low_price[confirm_idx] = source_low
            pivot_low_source_idx[confirm_idx] = source_idx

    pivot_high_series = pd.Series(pivot_high_price, index=df.index)
    pivot_low_series = pd.Series(pivot_low_price, index=df.index)

    return pd.DataFrame(
        {
            "swing_high_confirmed": confirmed_high,
            "swing_low_confirmed": confirmed_low,
            "confirmed_swing_high_price": pivot_high_series,
            "confirmed_swing_low_price": pivot_low_series,
            "confirmed_swing_high_source_idx": pivot_high_source_idx,
            "confirmed_swing_low_source_idx": pivot_low_source_idx,
            "last_swing_high": pivot_high_series.ffill(),
            "last_swing_low": pivot_low_series.ffill(),
        },
        index=df.index,
    )


def structure_bos_choch_block(df: pd.DataFrame, pivots: pd.DataFrame) -> pd.DataFrame:
    close = df["close"]
    last_high_before = pivots["last_swing_high"].shift(1)
    last_low_before = pivots["last_swing_low"].shift(1)

    bos_up = ((close > last_high_before) & (close.shift(1) <= last_high_before)).astype("int8")
    bos_dn = ((close < last_low_before) & (close.shift(1) >= last_low_before)).astype("int8")

    state = np.zeros(len(df), dtype=np.int8)
    choch_up = np.zeros(len(df), dtype=np.int8)
    choch_dn = np.zeros(len(df), dtype=np.int8)

    for idx in range(1, len(df)):
        previous_state = int(state[idx - 1])
        state[idx] = previous_state

        if int(bos_up.iloc[idx]) == 1:
            if previous_state == -1:
                choch_up[idx] = 1
            state[idx] = 1
        elif int(bos_dn.iloc[idx]) == 1:
            if previous_state == 1:
                choch_dn[idx] = 1
            state[idx] = -1

    return pd.DataFrame(
        {
            "bos_up": bos_up,
            "bos_dn": bos_dn,
            "structure_state": state,
            "choch_up": choch_up,
            "choch_dn": choch_dn,
        },
        index=df.index,
    )


def zigzag_causal_block(
    df: pd.DataFrame,
    pivots: pd.DataFrame,
    deviation_pct: float,
) -> pd.DataFrame:
    high_price = pivots["confirmed_swing_high_price"]
    low_price = pivots["confirmed_swing_low_price"]

    last_low_before = pivots["last_swing_low"].shift(1)
    last_high_before = pivots["last_swing_high"].shift(1)

    high_deviation = safe_div((high_price - last_low_before).abs(), last_low_before.abs())
    low_deviation = safe_div((last_high_before - low_price).abs(), low_price.abs())

    high_ok = pivots["swing_high_confirmed"].eq(1) & (high_deviation >= deviation_pct / 100.0)
    low_ok = pivots["swing_low_confirmed"].eq(1) & (low_deviation >= deviation_pct / 100.0)

    zigzag_high = high_price.where(high_ok)
    zigzag_low = low_price.where(low_ok)

    high_source_idx = pivots["confirmed_swing_high_source_idx"].where(high_ok, -1)
    low_source_idx = pivots["confirmed_swing_low_source_idx"].where(low_ok, -1)

    return pd.DataFrame(
        {
            "zigzag_high_confirmed": high_ok.astype("int8"),
            "zigzag_low_confirmed": low_ok.astype("int8"),
            "zigzag_high": zigzag_high,
            "zigzag_low": zigzag_low,
            "zigzag_high_source_idx": high_source_idx.astype("int32"),
            "zigzag_low_source_idx": low_source_idx.astype("int32"),
            "last_zigzag_high": zigzag_high.ffill(),
            "last_zigzag_low": zigzag_low.ffill(),
            "last_zigzag_high_idx": high_source_idx.replace(-1, np.nan).ffill(),
            "last_zigzag_low_idx": low_source_idx.replace(-1, np.nan).ffill(),
        },
        index=df.index,
    )


def sweep_block(df: pd.DataFrame, pivots: pd.DataFrame) -> pd.DataFrame:
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)
    last_swing_high = pivots["last_swing_high"].shift(1)
    last_swing_low = pivots["last_swing_low"].shift(1)

    return pd.DataFrame(
        {
            "sweep_high": ((df["high"] > prev_high) & (df["close"] < prev_high)).astype("int8"),
            "sweep_low": ((df["low"] < prev_low) & (df["close"] > prev_low)).astype("int8"),
            "swing_sweep_high": (
                (df["high"] > last_swing_high) & (df["close"] < last_swing_high)
            ).astype("int8"),
            "swing_sweep_low": (
                (df["low"] < last_swing_low) & (df["close"] > last_swing_low)
            ).astype("int8"),
        },
        index=df.index,
    )


def fvg_block(df: pd.DataFrame, atr: pd.Series, minimum_size_atr: float) -> pd.DataFrame:
    high_two_back = df["high"].shift(2)
    low_two_back = df["low"].shift(2)

    up_low = high_two_back
    up_high = df["low"]
    down_low = df["high"]
    down_high = low_two_back

    atrn = atr.replace(0, np.nan)
    up_size = (up_high - up_low).clip(lower=0)
    down_size = (down_high - down_low).clip(lower=0)
    up_size_atr = safe_div(up_size, atrn)
    down_size_atr = safe_div(down_size, atrn)

    fvg_up = (up_size_atr >= minimum_size_atr).astype("int8")
    fvg_dn = (down_size_atr >= minimum_size_atr).astype("int8")

    return pd.DataFrame(
        {
            "fvg_up": fvg_up,
            "fvg_dn": fvg_dn,
            "fvg_up_low": up_low.where(fvg_up.eq(1)),
            "fvg_up_high": up_high.where(fvg_up.eq(1)),
            "fvg_dn_low": down_low.where(fvg_dn.eq(1)),
            "fvg_dn_high": down_high.where(fvg_dn.eq(1)),
            "fvg_up_size": up_size.where(fvg_up.eq(1), 0.0),
            "fvg_dn_size": down_size.where(fvg_dn.eq(1), 0.0),
            "fvg_up_size_atr": up_size_atr.where(fvg_up.eq(1), 0.0),
            "fvg_dn_size_atr": down_size_atr.where(fvg_dn.eq(1), 0.0),
        },
        index=df.index,
    )


def order_block_candidate_block(
    df: pd.DataFrame,
    structure: pd.DataFrame,
    atr: pd.Series,
    minimum_displacement_atr: float,
) -> pd.DataFrame:
    atrn = atr.replace(0, np.nan)
    displacement = safe_div((df["close"] - df["open"]).abs(), atrn)

    bullish_candidate_event = (
        structure["bos_up"].eq(1)
        & (df["close"] > df["open"])
        & (displacement >= minimum_displacement_atr)
    )
    bearish_candidate_event = (
        structure["bos_dn"].eq(1)
        & (df["close"] < df["open"])
        & (displacement >= minimum_displacement_atr)
    )

    bull_low_event = df["low"].shift(1).where(bullish_candidate_event)
    bull_high_event = df["high"].shift(1).where(bullish_candidate_event)
    bear_low_event = df["low"].shift(1).where(bearish_candidate_event)
    bear_high_event = df["high"].shift(1).where(bearish_candidate_event)

    bull_low = bull_low_event.ffill()
    bull_high = bull_high_event.ffill()
    bear_low = bear_low_event.ffill()
    bear_high = bear_high_event.ffill()

    in_bull = (df["low"] <= bull_high) & (df["high"] >= bull_low)
    in_bear = (df["high"] >= bear_low) & (df["low"] <= bear_high)

    mitigated_bull = in_bull & (df["close"] < bull_low)
    mitigated_bear = in_bear & (df["close"] > bear_high)

    return pd.DataFrame(
        {
            "bull_ob_candidate_event": bullish_candidate_event.astype("int8"),
            "bear_ob_candidate_event": bearish_candidate_event.astype("int8"),
            "bull_ob_candidate_low": bull_low,
            "bull_ob_candidate_high": bull_high,
            "bear_ob_candidate_low": bear_low,
            "bear_ob_candidate_high": bear_high,
            "in_bull_ob_candidate": in_bull.astype("int8"),
            "in_bear_ob_candidate": in_bear.astype("int8"),
            "mitigated_bull_ob_candidate": mitigated_bull.astype("int8"),
            "mitigated_bear_ob_candidate": mitigated_bear.astype("int8"),
        },
        index=df.index,
    )


def fibonacci_directional_block(df: pd.DataFrame, zigzag: pd.DataFrame, atr: pd.Series) -> pd.DataFrame:
    last_high = zigzag["last_zigzag_high"]
    last_low = zigzag["last_zigzag_low"]
    last_high_idx = zigzag["last_zigzag_high_idx"]
    last_low_idx = zigzag["last_zigzag_low_idx"]

    direction = np.where(last_low_idx < last_high_idx, 1, np.where(last_high_idx < last_low_idx, -1, 0))
    range_ = (last_high - last_low).abs().replace(0, np.nan)

    bullish = pd.Series(direction == 1, index=df.index)
    bearish = pd.Series(direction == -1, index=df.index)

    fib_382 = pd.Series(np.nan, index=df.index, dtype=float)
    fib_500 = pd.Series(np.nan, index=df.index, dtype=float)
    fib_618 = pd.Series(np.nan, index=df.index, dtype=float)
    fib_786 = pd.Series(np.nan, index=df.index, dtype=float)
    fib_1272 = pd.Series(np.nan, index=df.index, dtype=float)
    fib_1618 = pd.Series(np.nan, index=df.index, dtype=float)

    fib_382.loc[bullish] = last_high.loc[bullish] - 0.382 * range_.loc[bullish]
    fib_500.loc[bullish] = last_high.loc[bullish] - 0.500 * range_.loc[bullish]
    fib_618.loc[bullish] = last_high.loc[bullish] - 0.618 * range_.loc[bullish]
    fib_786.loc[bullish] = last_high.loc[bullish] - 0.786 * range_.loc[bullish]
    fib_1272.loc[bullish] = last_high.loc[bullish] + 0.272 * range_.loc[bullish]
    fib_1618.loc[bullish] = last_high.loc[bullish] + 0.618 * range_.loc[bullish]

    fib_382.loc[bearish] = last_low.loc[bearish] + 0.382 * range_.loc[bearish]
    fib_500.loc[bearish] = last_low.loc[bearish] + 0.500 * range_.loc[bearish]
    fib_618.loc[bearish] = last_low.loc[bearish] + 0.618 * range_.loc[bearish]
    fib_786.loc[bearish] = last_low.loc[bearish] + 0.786 * range_.loc[bearish]
    fib_1272.loc[bearish] = last_low.loc[bearish] - 0.272 * range_.loc[bearish]
    fib_1618.loc[bearish] = last_low.loc[bearish] - 0.618 * range_.loc[bearish]

    atrn = atr.replace(0, np.nan)
    return pd.DataFrame(
        {
            "fib_direction": direction.astype("int8"),
            "fib_382_retr": fib_382,
            "fib_500_retr": fib_500,
            "fib_618_retr": fib_618,
            "fib_786_retr": fib_786,
            "fib_1272_ext": fib_1272,
            "fib_1618_ext": fib_1618,
            "dist_fib382_atr": safe_div(df["close"] - fib_382, atrn),
            "dist_fib500_atr": safe_div(df["close"] - fib_500, atrn),
            "dist_fib618_atr": safe_div(df["close"] - fib_618, atrn),
            "dist_fib786_atr": safe_div(df["close"] - fib_786, atrn),
        },
        index=df.index,
    )


# =============================================================================
# Sessões e barra live
# =============================================================================


def session_block(df: pd.DataFrame) -> pd.DataFrame:
    hour_london = df["hour_london"].astype("Int64")
    minute_london = df["minute_london"].astype("Int64")
    hour_ny = df["hour_ny"].astype("Int64")
    minute_ny = df["minute_ny"].astype("Int64")
    date_brt = df["time_brt"].dt.date

    in_asia = ((hour_london >= 0) & (hour_london < 8)).astype("int8")
    in_london = ((hour_london >= 8) & (hour_london < 12)).astype("int8")
    london_kz = ((hour_london >= 7) & (hour_london < 10)).astype("int8")
    london_open = ((hour_london == 8) & (minute_london == 0)).astype("int8")

    in_ny = ((hour_ny >= 8) & (hour_ny < 17)).astype("int8")
    ny_kz = ((hour_ny >= 8) & (hour_ny < 11)).astype("int8")
    ny_open = ((hour_ny == 8) & (minute_ny == 0)).astype("int8")

    session_label = np.select(
        [in_ny.eq(1), in_london.eq(1), in_asia.eq(1)],
        ["NEW_YORK", "LONDON", "ASIA"],
        default="OFF_SESSION",
    )

    return pd.DataFrame(
        {
            "in_asia_session": in_asia,
            "in_london_session": in_london,
            "in_ny_session": in_ny,
            "london_killzone": london_kz,
            "ny_killzone": ny_kz,
            "is_london_open_bar": london_open,
            "is_ny_open_bar": ny_open,
            "session_name": session_label,
            "session_high": df.groupby(date_brt)["high"].cummax(),
            "session_low": df.groupby(date_brt)["low"].cummin(),
        },
        index=df.index,
    )


def live_bar_context_block(df: pd.DataFrame, timeframe_name: str) -> pd.DataFrame:
    output = pd.DataFrame(index=df.index)
    for column in (
        "elapsed_bar_ratio",
        "expected_volume_at_elapsed",
        "volume_pace_ratio",
        "projected_final_volume",
        "projected_volume_ratio_20",
        "live_price_position",
        "live_range_atr",
        "live_body_atr",
    ):
        output[column] = np.nan
    output["live_bar_classification"] = "NOT_LIVE"

    if df.empty or int(df["is_live_bar"].iloc[-1]) != 1:
        return output

    idx = df.index[-1]
    timeframe_seconds = TIMEFRAME_SECONDS[timeframe_name]
    bar_start_utc = pd.Timestamp(df.loc[idx, "time"], tz="UTC")
    now_utc = pd.Timestamp.now(tz="UTC")
    elapsed_seconds = max(0.0, min(float(timeframe_seconds), (now_utc - bar_start_utc).total_seconds()))
    elapsed_ratio = max(0.01, min(1.0, elapsed_seconds / timeframe_seconds))

    closed = df.iloc[:-1].copy()
    avg_volume_20 = closed["tick_volume"].tail(20).mean()
    current_volume = float(df.loc[idx, "tick_volume"])
    expected_volume_at_elapsed = avg_volume_20 * elapsed_ratio if np.isfinite(avg_volume_20) else np.nan
    volume_pace_ratio = (
        current_volume / expected_volume_at_elapsed
        if expected_volume_at_elapsed and expected_volume_at_elapsed > 0
        else np.nan
    )
    projected_final_volume = current_volume / elapsed_ratio
    projected_volume_ratio_20 = (
        projected_final_volume / avg_volume_20
        if np.isfinite(avg_volume_20) and avg_volume_20 > 0
        else np.nan
    )

    current_range = float(df.loc[idx, "high"] - df.loc[idx, "low"])
    current_body = abs(float(df.loc[idx, "close"] - df.loc[idx, "open"]))
    live_price_position = (
        float((df.loc[idx, "close"] - df.loc[idx, "low"]) / current_range)
        if current_range > 0
        else np.nan
    )
    atr_value = float(df.loc[idx, "ATR"]) if "ATR" in df.columns else np.nan
    live_range_atr = current_range / atr_value if np.isfinite(atr_value) and atr_value > 0 else np.nan
    live_body_atr = current_body / atr_value if np.isfinite(atr_value) and atr_value > 0 else np.nan

    inside = int(df.loc[idx, "inside_previous_range"]) == 1
    breakout_up = int(df.loc[idx, "high_above_prev_high"]) == 1
    breakout_down = int(df.loc[idx, "low_below_prev_low"]) == 1
    false_up = int(df.loc[idx, "false_breakout_up"]) == 1
    false_down = int(df.loc[idx, "false_breakout_down"]) == 1

    if false_up:
        classification = "FALSE_BREAKOUT_UP"
    elif false_down:
        classification = "FALSE_BREAKOUT_DOWN"
    elif breakout_up and breakout_down:
        classification = "OUTSIDE_RANGE"
    elif breakout_up:
        classification = "BREAKOUT_UP_LIVE"
    elif breakout_down:
        classification = "BREAKOUT_DOWN_LIVE"
    elif inside and np.isfinite(projected_volume_ratio_20) and projected_volume_ratio_20 < 0.8:
        classification = "INSIDE_RANGE_LOW_PARTICIPATION"
    elif inside:
        classification = "INSIDE_RANGE"
    else:
        classification = "LIVE_RANGE_DEVELOPING"

    output.loc[idx, "elapsed_bar_ratio"] = elapsed_ratio
    output.loc[idx, "expected_volume_at_elapsed"] = expected_volume_at_elapsed
    output.loc[idx, "volume_pace_ratio"] = volume_pace_ratio
    output.loc[idx, "projected_final_volume"] = projected_final_volume
    output.loc[idx, "projected_volume_ratio_20"] = projected_volume_ratio_20
    output.loc[idx, "live_price_position"] = live_price_position
    output.loc[idx, "live_range_atr"] = live_range_atr
    output.loc[idx, "live_body_atr"] = live_body_atr
    output.loc[idx, "live_bar_classification"] = classification
    return output


# =============================================================================
# Readiness e labels
# =============================================================================


def readiness_block(df: pd.DataFrame, warmup_min: int = 250) -> pd.DataFrame:
    row_idx = np.arange(len(df))
    is_warmup = (row_idx < warmup_min).astype("int8")

    train_columns = ("ATR_Z", "BB_Width_Z", "dist_sma200_atr", "vol_ratio")
    train_ok = np.ones(len(df), dtype=bool)
    for column in train_columns:
        if column in df.columns:
            train_ok &= df[column].notna().to_numpy()
    train_ok &= is_warmup == 0

    realtime_columns = ("ATR", "EMA_20", "EMA_50", "vol_ratio")
    realtime_ok = np.ones(len(df), dtype=bool)
    for column in realtime_columns:
        if column in df.columns:
            realtime_ok &= df[column].notna().to_numpy()

    return pd.DataFrame(
        {
            "row_idx": row_idx,
            "is_warmup": is_warmup,
            "ready_for_train": train_ok.astype("int8"),
            "ready_for_realtime": realtime_ok.astype("int8"),
        },
        index=df.index,
    )


def build_dir_signal(df: pd.DataFrame) -> pd.Series:
    signal = pd.Series(0, index=df.index, dtype="int8")
    if "structure_state" in df.columns:
        signal = np.sign(pd.to_numeric(df["structure_state"], errors="coerce").fillna(0)).astype("int8")

    if "ema20_above_ema50" in df.columns:
        zero_mask = signal.eq(0)
        ema_above = df["ema20_above_ema50"].fillna(0).astype(int)
        signal.loc[zero_mask] = np.where(ema_above.loc[zero_mask].eq(1), 1, -1).astype("int8")

    if "ready_for_train" in df.columns:
        signal = signal.where(df["ready_for_train"].fillna(0).astype(int).eq(1), 0).astype("int8")
    if "is_live_bar" in df.columns:
        signal = signal.where(df["is_live_bar"].fillna(0).astype(int).eq(0), 0).astype("int8")
    return signal


def select_tb_params(row: pd.Series, labels_cfg: Mapping[str, Any]) -> Dict[str, float]:
    tb_cfg = labels_cfg.get("triple_barrier", {})
    selected = dict(tb_cfg.get("default", {"tp_atr": 0.9, "sl_atr": 0.7, "timeout_bars": 8}))

    if int(row.get("compression_flag", 0) or 0) == 1:
        selected = dict(tb_cfg.get("compression", selected))

    if (
        int(row.get("expansion_flag", 0) or 0) == 1
        and (int(row.get("london_killzone", 0) or 0) == 1 or int(row.get("ny_killzone", 0) or 0) == 1)
    ):
        selected = dict(tb_cfg.get("expansion_killzone", selected))

    if int(row.get("expansion_flag", 0) or 0) == 1 and int(row.get("ny_killzone", 0) or 0) == 1:
        selected = dict(tb_cfg.get("new_york_expansion", selected))

    return {
        "tp_atr": float(selected.get("tp_atr", 0.9)),
        "sl_atr": float(selected.get("sl_atr", 0.7)),
        "timeout_bars": int(selected.get("timeout_bars", 8)),
    }


def triple_barrier_and_meta_label(df: pd.DataFrame, labels_cfg: Mapping[str, Any]) -> pd.DataFrame:
    output = pd.DataFrame(index=df.index)
    if df.empty:
        return output

    entry_mode = str(labels_cfg.get("triple_barrier", {}).get("entry_mode", "close_t1"))
    same_bar_policy = str(
        labels_cfg.get("triple_barrier", {}).get("same_bar_policy", "stop_first_conservative")
    )

    direction = build_dir_signal(df)
    entry = df["close"].shift(-1) if entry_mode == "close_t1" else df["close"]
    entry_offset = 1 if entry_mode == "close_t1" else 0

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    atr = df["ATR"].to_numpy(dtype=float)
    direction_np = direction.to_numpy(dtype=np.int8)

    n = len(df)
    tb_y = np.zeros(n, dtype=np.int8)
    tb_exit_idx = np.full(n, -1, dtype=np.int32)
    tb_r_atr = np.full(n, np.nan)
    tb_exit_type = np.array(["NO_TRADE"] * n, dtype=object)

    last_valid = n - 2 if entry_offset == 1 else n - 1
    for idx in range(last_valid + 1):
        if int(df["is_live_bar"].iloc[idx]) == 1:
            continue
        trade_direction = int(direction_np[idx])
        if trade_direction == 0:
            continue

        entry_idx = idx + entry_offset
        entry_price = float(entry.iloc[idx])
        atr_value = float(atr[idx])
        if not np.isfinite(entry_price) or not np.isfinite(atr_value) or atr_value <= 0:
            continue

        params = select_tb_params(df.iloc[idx], labels_cfg)
        tp_atr = params["tp_atr"]
        sl_atr = params["sl_atr"]
        timeout = params["timeout_bars"]

        if trade_direction == 1:
            tp = entry_price + tp_atr * atr_value
            sl = entry_price - sl_atr * atr_value
        else:
            tp = entry_price - tp_atr * atr_value
            sl = entry_price + sl_atr * atr_value

        end_idx = min(n - 1, entry_idx + timeout)
        hit: Optional[str] = None
        hit_idx = -1

        for future_idx in range(entry_idx, end_idx + 1):
            if int(df["is_live_bar"].iloc[future_idx]) == 1:
                break
            high = highs[future_idx]
            low = lows[future_idx]
            if not np.isfinite(high) or not np.isfinite(low):
                continue

            if trade_direction == 1:
                tp_hit = high >= tp
                sl_hit = low <= sl
            else:
                tp_hit = low <= tp
                sl_hit = high >= sl

            if tp_hit and sl_hit:
                hit = "SL" if same_bar_policy == "stop_first_conservative" else "TP"
                hit_idx = future_idx
                break
            if tp_hit:
                hit = "TP"
                hit_idx = future_idx
                break
            if sl_hit:
                hit = "SL"
                hit_idx = future_idx
                break

        if hit is None:
            timeout_idx = min(end_idx, n - 1)
            exit_price = closes[timeout_idx]
            if np.isfinite(exit_price):
                r_atr = (exit_price - entry_price) / atr_value
                if trade_direction == -1:
                    r_atr = -r_atr
                tb_exit_type[idx] = "TIMEOUT"
                tb_exit_idx[idx] = timeout_idx
                tb_r_atr[idx] = r_atr
            continue

        tb_exit_idx[idx] = hit_idx
        if hit == "TP":
            tb_y[idx] = 1
            tb_r_atr[idx] = tp_atr
            tb_exit_type[idx] = "TP"
        else:
            tb_y[idx] = -1
            tb_r_atr[idx] = -sl_atr
            tb_exit_type[idx] = "SL"

    meta_label = np.where(
        tb_exit_type == "NO_TRADE",
        np.nan,
        (tb_r_atr > 0).astype(float),
    )

    output["dir_signal"] = direction
    output["tb_y"] = tb_y
    output["tb_exit_type"] = tb_exit_type
    output["tb_exit_idx"] = tb_exit_idx
    output["tb_r_atr"] = tb_r_atr
    output["meta_label"] = meta_label
    return output


# =============================================================================
# Construção do dataset
# =============================================================================


def build_feature_dataset(
    base: pd.DataFrame,
    timeframe_name: str,
    config: Mapping[str, Any],
    broker_timezone: str,
    enable_labels: bool,
) -> pd.DataFrame:
    features_cfg = config.get("features", {})
    sessions_cfg = features_cfg.get("sessions", {})

    df = add_time_columns(
        base,
        broker_timezone=broker_timezone,
        brt_timezone=str(sessions_cfg.get("timezone_brt", "America/Sao_Paulo")),
        london_timezone=str(sessions_cfg.get("timezone_london", "Europe/London")),
        ny_timezone=str(sessions_cfg.get("timezone_new_york", "America/New_York")),
    )

    atr_window = int(features_cfg.get("atr_window", 14))
    regime_window = int(features_cfg.get("regime_window", 200))
    sentiment_map = features_cfg.get("sentiment_candles", {})
    sentiment_lookback = int(sentiment_map.get(timeframe_name, 5))

    indicators = calculate_indicators_block(df, atr_window=atr_window)
    basic = basic_price_block(df)
    previous = previous_bar_relation_block(df, indicators["ATR"])
    patterns = candle_patterns_block(df)
    sentiment = candle_sentiment_volume_block(df, sentiment_lookback)
    regime = regime_block(df, indicators, window=regime_window)

    volatility_cfg = features_cfg.get("volatility", {})
    regime_flags = compression_expansion_block(
        regime,
        compression_threshold=float(volatility_cfg.get("compression_threshold", -1.0)),
        expansion_threshold=float(volatility_cfg.get("expansion_threshold", 1.0)),
    )

    spread = spread_block(df, window=regime_window)
    ema_trend = ema_trend_block(indicators)
    bar_atr = atr_bar_proxies_block(df, indicators["ATR"])
    distances = atr_distance_block(df, indicators)

    structure_cfg = features_cfg.get("structure", {})
    swing_window = int(structure_cfg.get("swing_window", 3))
    pivots = confirmed_pivots_block(df, window=swing_window)
    structure = structure_bos_choch_block(df, pivots)

    zigzag_cfg = features_cfg.get("zigzag", {})
    zigzag = zigzag_causal_block(
        df,
        pivots,
        deviation_pct=float(zigzag_cfg.get("deviation_pct", 0.5)),
    )

    sweeps = sweep_block(df, pivots)

    fvg_cfg = features_cfg.get("fvg", {})
    fvg = fvg_block(
        df,
        indicators["ATR"],
        minimum_size_atr=float(fvg_cfg.get("minimum_size_atr", 0.1)),
    )

    ob_cfg = features_cfg.get("order_blocks", {})
    order_blocks = order_block_candidate_block(
        df,
        structure,
        indicators["ATR"],
        minimum_displacement_atr=float(ob_cfg.get("minimum_displacement_atr", 0.8)),
    )

    fibonacci = fibonacci_directional_block(df, zigzag, indicators["ATR"])
    sessions = session_block(df)

    dataset = pd.concat(
        [
            df,
            indicators,
            basic,
            previous,
            patterns,
            sentiment,
            regime,
            regime_flags,
            spread,
            ema_trend,
            bar_atr,
            distances,
            pivots,
            structure,
            zigzag,
            sweeps,
            fvg,
            order_blocks,
            fibonacci,
            sessions,
        ],
        axis=1,
    )

    dataset = dataset.loc[:, ~dataset.columns.duplicated()].copy()
    dataset = dataset.replace([np.inf, -np.inf], np.nan)

    # Forward-fill somente séries contínuas; flags não são carregadas para frente.
    continuous_prefixes = (
        "SMA_",
        "EMA_",
        "Bollinger_",
        "Ichimoku_",
        "last_",
        "fib_",
        "bull_ob_candidate_",
        "bear_ob_candidate_",
    )
    continuous_columns = [
        column
        for column in dataset.columns
        if column.startswith(continuous_prefixes)
        and not column.endswith("_event")
        and not column.startswith("fib_direction")
    ]
    if continuous_columns:
        dataset[continuous_columns] = dataset[continuous_columns].ffill()

    for column in FLAG_COLUMNS:
        if column in dataset.columns:
            dataset[column] = dataset[column].fillna(0)

    readiness = readiness_block(dataset, warmup_min=max(250, regime_window))
    dataset = pd.concat([dataset, readiness], axis=1)

    live_context = live_bar_context_block(dataset, timeframe_name)
    dataset = pd.concat([dataset, live_context], axis=1)

    if enable_labels:
        labels = triple_barrier_and_meta_label(dataset, config.get("labels", {}))
        dataset = pd.concat([dataset, labels], axis=1)
    else:
        dataset = dataset.drop(columns=[c for c in LABEL_COLUMNS if c in dataset.columns], errors="ignore")

    return dataset


# =============================================================================
# Storage
# =============================================================================


def pyarrow_available() -> bool:
    try:
        import pyarrow  # noqa: F401

        return True
    except ImportError:
        return False


def atomic_write_parquet(df: pd.DataFrame, path: Path, compression: str = "zstd") -> None:
    if not pyarrow_available():
        raise RuntimeError("pyarrow não instalado. Execute: pip install pyarrow")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(temp_path, index=False, engine="pyarrow", compression=compression)
    temp_path.replace(path)


def atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(temp_path, index=False)
    temp_path.replace(path)


def save_timeframe_dataset(
    dataset: pd.DataFrame,
    symbol: str,
    timeframe: str,
    config: Mapping[str, Any],
) -> Dict[str, str]:
    data_cfg = config.get("data", {})
    data_dir = resolve_project_path(config, str(data_cfg.get("data_dir", "data")))
    compression = str(data_cfg.get("compression", "zstd"))
    saved: Dict[str, str] = {}

    if bool(data_cfg.get("write_parquet", True)):
        parquet_path = data_dir / f"{symbol}_{timeframe}.parquet"
        atomic_write_parquet(dataset, parquet_path, compression=compression)
        saved["parquet"] = str(parquet_path)
        LOGGER.info("Parquet salvo: %s", parquet_path)

    if bool(data_cfg.get("write_csv", False)):
        csv_path = data_dir / f"{symbol}_{timeframe}.csv"
        atomic_write_csv(dataset, csv_path)
        saved["csv"] = str(csv_path)
        LOGGER.info("CSV salvo: %s", csv_path)

    return saved


def sanitize_filename_component(value: str, fallback: str = "data") -> str:
    """Normaliza um componente de nome de arquivo para Windows e Linux."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def save_consolidated_datasets(
    all_data: Mapping[str, Mapping[str, pd.DataFrame]],
    config: Mapping[str, Any],
    mode: str,
    mode_cfg: Mapping[str, Any],
) -> List[str]:
    data_cfg = config.get("data", {})

    configured_suffix = mode_cfg.get("consolidated_suffix", mode)
    consolidated_suffix = sanitize_filename_component(str(configured_suffix), fallback="data")

    write_parquet = bool(data_cfg.get("write_consolidated_parquet", True))
    write_csv = bool(data_cfg.get("write_consolidated_csv", False))

    if not write_parquet and not write_csv:
        LOGGER.info("Salvamento consolidado desabilitado no tradingagent.json")
        return []

    consolidated_dir = resolve_project_path(
        config,
        str(data_cfg.get("consolidated_dir", "data/consolidated")),
    )
    compression = str(data_cfg.get("compression", "zstd"))

    saved_paths: List[str] = []
    symbols = sorted({symbol for tf_data in all_data.values() for symbol in tf_data.keys()})
    LOGGER.info(
        "Consolidado habilitado | modo=%s sufixo=%s parquet=%s csv=%s diretório=%s símbolos=%s",
        mode,
        consolidated_suffix,
        write_parquet,
        write_csv,
        consolidated_dir,
        symbols,
    )
    for symbol in symbols:
        parts: List[pd.DataFrame] = []
        for timeframe, tf_data in all_data.items():
            if symbol not in tf_data:
                continue
            part = tf_data[symbol].copy()
            if "timeframe" not in part.columns:
                part["timeframe"] = timeframe
            parts.append(part)

        if not parts:
            continue

        consolidated = pd.concat(parts, ignore_index=True, sort=False)

        if write_parquet:
            parquet_path = consolidated_dir / f"{symbol}_{consolidated_suffix}.parquet"
            atomic_write_parquet(consolidated, parquet_path, compression=compression)
            saved_paths.append(str(parquet_path))
            LOGGER.info("Consolidado Parquet salvo: %s", parquet_path)

        if write_csv:
            csv_path = consolidated_dir / f"{symbol}_{consolidated_suffix}.csv"
            atomic_write_csv(consolidated, csv_path)
            if not csv_path.exists():
                raise RuntimeError(f"CSV consolidado não foi criado: {csv_path}")
            saved_paths.append(str(csv_path))
            LOGGER.info(
                "Consolidado CSV salvo: %s | rows=%s cols=%s bytes=%s",
                csv_path,
                len(consolidated),
                len(consolidated.columns),
                csv_path.stat().st_size,
            )

    return saved_paths


def write_manifest(
    config: Mapping[str, Any],
    mode: str,
    outputs: Mapping[str, Any],
    status: str,
) -> Path:
    data_cfg = config.get("data", {})
    manifest_dir = resolve_project_path(
        config,
        str(data_cfg.get("manifest_dir", "data/manifests")),
    )
    manifest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = pd.Timestamp.now(tz="UTC")
    manifest = {
        "project": config.get("project", {}).get("name", "TradingAgent"),
        "mode": mode,
        "status": status,
        "created_at_utc": timestamp.isoformat(),
        "config_path": config.get("_config_path"),
        "outputs": outputs,
    }

    path = manifest_dir / f"base_dados_{mode}_{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False, default=str)
    LOGGER.info("Manifest salvo: %s", path)
    return path


# =============================================================================
# Pipelines
# =============================================================================


def collect_and_build(
    config: Mapping[str, Any],
    mode: str,
    mode_cfg: Mapping[str, Any],
    broker_timezone: str,
) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], Dict[str, Any]]:
    symbols = normalize_symbols(config.get("universe", {}).get("symbols", []))
    timeframes = normalize_timeframes(mode_cfg.get("timeframes", []))
    include_live_bar = bool(mode_cfg.get("include_live_bar", True))
    enable_labels = bool(mode_cfg.get("enable_labels", False))
    q_candles = int(config.get("data", {}).get("q_candles", 5000))
    timestamp_source = str(
        config.get("mt5", {}).get("timestamp_source", "utc_epoch")
    )
    continue_on_error = bool(config.get("pipeline", {}).get("continue_on_error", False))

    all_data: Dict[str, Dict[str, pd.DataFrame]] = {tf: {} for tf in timeframes}
    outputs: Dict[str, Any] = {
        "symbols": symbols,
        "timeframes": timeframes,
        "include_live_bar": include_live_bar,
        "enable_labels": enable_labels,
        "files": [],
        "errors": [],
    }

    for timeframe in timeframes:
        for symbol in symbols:
            try:
                LOGGER.info("Coletando %s TF=%s", symbol, timeframe)
                base = collect_mt5_rates(
                    symbol=symbol,
                    timeframe_name=timeframe,
                    count=q_candles,
                    include_live_bar=include_live_bar,
                    broker_timezone=broker_timezone,
                    timestamp_source=timestamp_source,
                )
                if base.empty:
                    raise RuntimeError("Nenhum candle retornado pelo MT5")

                dataset = build_feature_dataset(
                    base=base,
                    timeframe_name=timeframe,
                    config=config,
                    broker_timezone=broker_timezone,
                    enable_labels=enable_labels,
                )
                all_data[timeframe][symbol] = dataset

                saved = save_timeframe_dataset(dataset, symbol, timeframe, config)
                outputs["files"].append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "rows": len(dataset),
                        "columns": len(dataset.columns),
                        "saved": saved,
                    }
                )
                LOGGER.info(
                    "OK %s %s | rows=%s cols=%s live=%s",
                    symbol,
                    timeframe,
                    len(dataset),
                    len(dataset.columns),
                    include_live_bar,
                )
            except Exception as exc:
                message = f"{symbol} {timeframe}: {exc}"
                LOGGER.exception("Erro em %s", message)
                outputs["errors"].append(message)
                if not continue_on_error:
                    raise

    outputs["consolidated_suffix"] = str(mode_cfg.get("consolidated_suffix", mode))
    outputs["consolidated_files"] = save_consolidated_datasets(
        all_data, config, mode=mode, mode_cfg=mode_cfg
    )
    return all_data, outputs


def run_contexts_only(config: Mapping[str, Any], mode_cfg: Mapping[str, Any]) -> Dict[str, Any]:
    data_dir = resolve_project_path(config, str(config.get("data", {}).get("data_dir", "data")))
    symbols = normalize_symbols(config.get("universe", {}).get("symbols", []))
    timeframes = normalize_timeframes(mode_cfg.get("timeframes", []))

    found: List[str] = []
    missing: List[str] = []
    for symbol in symbols:
        for timeframe in timeframes:
            path = data_dir / f"{symbol}_{timeframe}.parquet"
            if path.exists():
                found.append(str(path))
            else:
                missing.append(str(path))

    LOGGER.info("contexts_only: %s arquivos encontrados, %s ausentes", len(found), len(missing))
    return {
        "symbols": symbols,
        "timeframes": timeframes,
        "found_parquets": found,
        "missing_parquets": missing,
        "note": "A geração dos contexts será executada pelos módulos em context/.",
    }


def run_pipeline(config: Mapping[str, Any], mode: str) -> Dict[str, Any]:
    mode_cfg = get_mode_config(config, mode)
    collect_from_mt5 = bool(mode_cfg.get("collect_from_mt5", True))

    if not collect_from_mt5:
        outputs = run_contexts_only(config, mode_cfg)
        write_manifest(config, mode, outputs, status="success")
        return outputs

    if not initialize_mt5(config):
        raise RuntimeError("Não foi possível inicializar o MetaTrader 5")

    try:
        server_name = detect_server_name(str(config["mt5"]["server"]))
        broker_timezone = resolve_broker_timezone(config, server_name)
        LOGGER.info(
            "Server detectado=%s | timezone broker=%s | timestamp_source=%s",
            server_name,
            broker_timezone,
            config.get("mt5", {}).get("timestamp_source", "utc_epoch"),
        )

        _, outputs = collect_and_build(config, mode, mode_cfg, broker_timezone)
        write_manifest(config, mode, outputs, status="success")
        return outputs
    except Exception as exc:
        outputs = {"error": str(exc)}
        write_manifest(config, mode, outputs, status="failed")
        raise
    finally:
        mt5.shutdown()
        LOGGER.info("Conexão MT5 encerrada")


# =============================================================================
# CLI
# =============================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TradingAgent - coleta MT5 e construção de features multi-timeframe"
    )
    parser.add_argument(
        "--config",
        default="tradingagent.json",
        help="Caminho para o tradingagent.json",
    )
    parser.add_argument(
        "--mode",
        default=None,
        help="Modo do pipeline. Se omitido, usa pipeline.default_mode do JSON.",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=None,
        help=(
            "Filtra um símbolo. Pode ser repetido, por exemplo: "
            "--symbol GOLD --symbol EURUSD."
        ),
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help=(
            "Filtra vários símbolos em uma única opção, por exemplo: "
            "--symbols GOLD EURUSD GBPUSD."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Nível de log",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    try:
        config = load_tradingagent_config(args.config)

        requested_symbols: List[str] = []
        if args.symbol:
            requested_symbols.extend(args.symbol)
        if args.symbols:
            requested_symbols.extend(args.symbols)

        if requested_symbols:
            filtered_symbols = normalize_symbols(requested_symbols)
            if not filtered_symbols:
                raise ValueError("Nenhum símbolo válido foi informado no filtro CLI.")

            universe = config.setdefault("universe", {})
            if not isinstance(universe, MutableMapping):
                raise ValueError("A seção universe do tradingagent.json precisa ser um objeto.")
            universe["symbols"] = filtered_symbols
            LOGGER.info("Filtro de símbolos aplicado via CLI: %s", filtered_symbols)

        default_mode = str(config.get("pipeline", {}).get("default_mode", "full_rebuild"))
        mode = str(args.mode or default_mode)

        LOGGER.info(
            "Projeto=%s | modo=%s | símbolos=%s",
            config.get("project", {}).get("name", "TradingAgent"),
            mode,
            normalize_symbols(config.get("universe", {}).get("symbols", [])),
        )
        outputs = run_pipeline(config, mode)

        LOGGER.info(
            "Pipeline finalizado | modo=%s arquivos=%s erros=%s",
            mode,
            len(outputs.get("files", [])),
            len(outputs.get("errors", [])),
        )
        print("done")
        return 0
    except KeyboardInterrupt:
        LOGGER.warning("Execução interrompida pelo usuário")
        return 130
    except Exception as exc:
        LOGGER.exception("Falha no Base_Dados.py: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
