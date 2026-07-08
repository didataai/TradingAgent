#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MA Confluence Optimizer
=======================

Pesquisa offline de combinações de médias para entrada intraday no GOLD.

Ideia operacional inicial:
- M1 dá o gatilho fino: candle fechado na direção e fechamento acima/abaixo das médias.
- Entrada ocorre no rompimento da máxima/mínima do candle M1 anterior.
- M5 atua como filtro/permissão: candle fechado alinhado com as médias.
- M15 atua como filtro de regime: quando alinha, movimento tende a ter mais força;
  quando está contra, o movimento tende a ser menor ou falhar.

Este script NÃO altera payload e NÃO gera ordem. Ele é pesquisa/backtest.

Exemplo rápido:
    python tools/ma_confluence_optimizer.py --symbol GOLD --max-combos 5000

Exemplo mais amplo:
    python tools/ma_confluence_optimizer.py ^
      --symbol GOLD ^
      --fast-range 3 15 ^
      --mid-range 6 40 ^
      --slow-range 10 100 ^
      --stop-atrs 0.7 1.0 1.3 ^
      --target-atrs 0.8 1.0 1.5 2.0 ^
      --max-hold-minutes 5 10 15 30 ^
      --m15-modes required warning_only disabled ^
      --max-combos 100000

Saídas:
    data/research/ma_confluence/<SYMBOL>/top_configs.csv
    data/research/ma_confluence/<SYMBOL>/top_configs.json
    data/research/ma_confluence/<SYMBOL>/summary.json
    data/research/ma_confluence/<SYMBOL>/trades_sample.csv
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


TF_M1 = "M1"
TF_M5 = "M5"
TF_M15 = "M15"
DEFAULT_SYMBOL = "GOLD"


@dataclass(frozen=True)
class StrategyConfig:
    ma_type: str
    fast: int
    mid: int
    slow: int
    stop_atr: float
    target_atr: float
    max_hold_minutes: int
    m15_mode: str
    m5_mode: str
    max_entry_candle_atr: float
    max_distance_slow_atr: float


@dataclass
class Metrics:
    symbol: str
    ma_type: str
    fast: int
    mid: int
    slow: int
    stop_atr: float
    target_atr: float
    max_hold_minutes: int
    m15_mode: str
    m5_mode: str
    max_entry_candle_atr: float
    max_distance_slow_atr: float
    trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    gross_profit_points: float
    gross_loss_points: float
    net_points: float
    avg_points: float
    profit_factor: float
    expectancy_r: float
    avg_mfe_points: float
    avg_mae_points: float
    mfe_mae_ratio: float
    max_drawdown_points: float
    max_loss_streak: int
    buy_trades: int
    sell_trades: int
    buy_win_rate: float
    sell_win_rate: float
    trades_per_day: float
    active_days: int
    robustness_score: float
    score: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Otimiza confluência de médias M1/M5/M15 para entrada intraday.")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--output-dir", type=Path, default=None)
    p.add_argument("--ma-type", choices=["ema", "sma"], default="ema")
    p.add_argument("--fast-range", nargs=2, type=int, default=[3, 15], metavar=("MIN", "MAX"))
    p.add_argument("--mid-range", nargs=2, type=int, default=[6, 40], metavar=("MIN", "MAX"))
    p.add_argument("--slow-range", nargs=2, type=int, default=[10, 100], metavar=("MIN", "MAX"))
    p.add_argument("--fast-step", type=int, default=1)
    p.add_argument("--mid-step", type=int, default=1)
    p.add_argument("--slow-step", type=int, default=1)
    p.add_argument("--stop-atrs", nargs="+", type=float, default=[0.7, 1.0, 1.3])
    p.add_argument("--target-atrs", nargs="+", type=float, default=[0.8, 1.0, 1.5, 2.0])
    p.add_argument("--max-hold-minutes", nargs="+", type=int, default=[5, 10, 15, 30])
    p.add_argument("--m15-modes", nargs="+", choices=["required", "warning_only", "disabled"], default=["required", "warning_only"])
    p.add_argument("--m5-modes", nargs="+", choices=["closed_all", "stack_only", "price_position_only"], default=["closed_all"])
    p.add_argument("--max-entry-candle-atrs", nargs="+", type=float, default=[0.8, 1.2, 1.8])
    p.add_argument("--max-distance-slow-atrs", nargs="+", type=float, default=[0.8, 1.2, 2.0])
    p.add_argument("--min-trades", type=int, default=30)
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--max-combos", type=int, default=25000, help="Limite de combinações avaliadas. Use 0 para avaliar todas.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--tie-break", choices=["stop", "target", "skip"], default="stop", help="Quando stop e alvo batem no mesmo candle futuro.")
    p.add_argument("--side", choices=["both", "buy", "sell"], default="both")
    p.add_argument("--write-trades-sample", type=int, default=5000)
    return p.parse_args()


def log(msg: str) -> None:
    print(msg, flush=True)


def normalize_time(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    time_col = "time_brt" if "time_brt" in df.columns else "time"
    if time_col not in df.columns:
        raise ValueError("DataFrame não possui coluna time/time_brt.")
    df["time"] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return df


def load_tf(data_dir: Path, symbol: str, tf: str) -> pd.DataFrame:
    path = data_dir / f"{symbol}_{tf}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Parquet não encontrado: {path}")
    df = pd.read_parquet(path)
    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{path} sem colunas obrigatórias: {missing}")
    if "ATR" not in df.columns:
        raise ValueError(f"{path} sem coluna ATR. Rode Base_Dados.py antes.")
    df = normalize_time(df)
    for col in ["open", "high", "low", "close", "ATR"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "ATR"])
    if "is_live_bar" in df.columns:
        df = df[pd.to_numeric(df["is_live_bar"], errors="coerce").fillna(0).astype(int) == 0]
    return df.reset_index(drop=True)


def add_ma_columns(df: pd.DataFrame, ma_type: str, fast: int, mid: int, slow: int) -> pd.DataFrame:
    out = df.copy()
    close = pd.to_numeric(out["close"], errors="coerce")
    for period, name in [(fast, "ma_fast"), (mid, "ma_mid"), (slow, "ma_slow")]:
        if ma_type == "ema":
            out[name] = close.ewm(span=period, adjust=False, min_periods=period).mean()
        else:
            out[name] = close.rolling(period, min_periods=period).mean()
    return out


def build_grid(args: argparse.Namespace) -> List[StrategyConfig]:
    fast_values = range(args.fast_range[0], args.fast_range[1] + 1, args.fast_step)
    mid_values = range(args.mid_range[0], args.mid_range[1] + 1, args.mid_step)
    slow_values = range(args.slow_range[0], args.slow_range[1] + 1, args.slow_step)
    configs: List[StrategyConfig] = []
    for fast, mid, slow in itertools.product(fast_values, mid_values, slow_values):
        if not (fast < mid < slow):
            continue
        for stop_atr, target_atr, hold, m15_mode, m5_mode, max_entry, max_dist in itertools.product(
            args.stop_atrs,
            args.target_atrs,
            args.max_hold_minutes,
            args.m15_modes,
            args.m5_modes,
            args.max_entry_candle_atrs,
            args.max_distance_slow_atrs,
        ):
            configs.append(
                StrategyConfig(
                    ma_type=args.ma_type,
                    fast=int(fast),
                    mid=int(mid),
                    slow=int(slow),
                    stop_atr=float(stop_atr),
                    target_atr=float(target_atr),
                    max_hold_minutes=int(hold),
                    m15_mode=str(m15_mode),
                    m5_mode=str(m5_mode),
                    max_entry_candle_atr=float(max_entry),
                    max_distance_slow_atr=float(max_dist),
                )
            )
    if args.max_combos and args.max_combos > 0 and len(configs) > args.max_combos:
        rng = random.Random(args.seed)
        configs = rng.sample(configs, args.max_combos)
    return configs


def align_context(m1: pd.DataFrame, m5: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    m1_ctx = m1.copy()
    m5_ctx = m5[["time", "close", "ma_fast", "ma_mid", "ma_slow"]].rename(
        columns={
            "close": "m5_close",
            "ma_fast": "m5_fast",
            "ma_mid": "m5_mid",
            "ma_slow": "m5_slow",
        }
    )
    m15_ctx = m15[["time", "close", "ma_fast", "ma_mid", "ma_slow"]].rename(
        columns={
            "close": "m15_close",
            "ma_fast": "m15_fast",
            "ma_mid": "m15_mid",
            "ma_slow": "m15_slow",
        }
    )
    m1_ctx = pd.merge_asof(m1_ctx.sort_values("time"), m5_ctx.sort_values("time"), on="time", direction="backward")
    m1_ctx = pd.merge_asof(m1_ctx.sort_values("time"), m15_ctx.sort_values("time"), on="time", direction="backward")
    return m1_ctx.dropna(subset=["ma_fast", "ma_mid", "ma_slow", "m5_fast", "m5_mid", "m5_slow"])


def side_alignment(close: pd.Series, fast: pd.Series, mid: pd.Series, slow: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    above_all = (close > fast) & (close > mid) & (close > slow)
    below_all = (close < fast) & (close < mid) & (close < slow)
    bull_stack = (fast > mid) & (mid > slow)
    bear_stack = (fast < mid) & (mid < slow)
    return above_all & bull_stack, below_all & bear_stack, above_all | below_all


def compute_signals(df: pd.DataFrame, cfg: StrategyConfig, side: str) -> pd.DataFrame:
    work = df.copy()
    prev = work.shift(1)

    m1_bull, m1_bear, _ = side_alignment(prev["close"], prev["ma_fast"], prev["ma_mid"], prev["ma_slow"])
    m5_bull_stack = (prev["m5_fast"] > prev["m5_mid"]) & (prev["m5_mid"] > prev["m5_slow"])
    m5_bear_stack = (prev["m5_fast"] < prev["m5_mid"]) & (prev["m5_mid"] < prev["m5_slow"])
    m5_above_all = (prev["m5_close"] > prev["m5_fast"]) & (prev["m5_close"] > prev["m5_mid"]) & (prev["m5_close"] > prev["m5_slow"])
    m5_below_all = (prev["m5_close"] < prev["m5_fast"]) & (prev["m5_close"] < prev["m5_mid"]) & (prev["m5_close"] < prev["m5_slow"])

    if cfg.m5_mode == "closed_all":
        m5_buy_ok = m5_above_all
        m5_sell_ok = m5_below_all
    elif cfg.m5_mode == "stack_only":
        m5_buy_ok = m5_bull_stack
        m5_sell_ok = m5_bear_stack
    else:
        m5_buy_ok = m5_above_all
        m5_sell_ok = m5_below_all

    m15_bull_stack = (prev["m15_fast"] > prev["m15_mid"]) & (prev["m15_mid"] > prev["m15_slow"])
    m15_bear_stack = (prev["m15_fast"] < prev["m15_mid"]) & (prev["m15_mid"] < prev["m15_slow"])
    m15_above_all = (prev["m15_close"] > prev["m15_fast"]) & (prev["m15_close"] > prev["m15_mid"]) & (prev["m15_close"] > prev["m15_slow"])
    m15_below_all = (prev["m15_close"] < prev["m15_fast"]) & (prev["m15_close"] < prev["m15_mid"]) & (prev["m15_close"] < prev["m15_slow"])
    m15_buy_aligned = m15_above_all | m15_bull_stack
    m15_sell_aligned = m15_below_all | m15_bear_stack
    m15_buy_against = m15_below_all & m15_bear_stack
    m15_sell_against = m15_above_all & m15_bull_stack

    if cfg.m15_mode == "required":
        m15_buy_ok = m15_buy_aligned
        m15_sell_ok = m15_sell_aligned
    elif cfg.m15_mode == "warning_only":
        m15_buy_ok = ~m15_buy_against
        m15_sell_ok = ~m15_sell_against
    else:
        m15_buy_ok = pd.Series(True, index=work.index)
        m15_sell_ok = pd.Series(True, index=work.index)

    prev_range_atr = (prev["high"] - prev["low"]) / prev["ATR"].replace(0, np.nan)
    prev_dist_slow_atr = ((prev["close"] - prev["ma_slow"]).abs() / prev["ATR"].replace(0, np.nan))
    candle_size_ok = prev_range_atr <= cfg.max_entry_candle_atr
    distance_ok = prev_dist_slow_atr <= cfg.max_distance_slow_atr

    prev_red = prev["close"] < prev["open"]
    prev_green = prev["close"] > prev["open"]
    buy_break = work["high"] >= prev["high"]
    sell_break = work["low"] <= prev["low"]

    buy_signal = m1_bull & prev_green & m5_buy_ok & m15_buy_ok & candle_size_ok & distance_ok & buy_break
    sell_signal = m1_bear & prev_red & m5_sell_ok & m15_sell_ok & candle_size_ok & distance_ok & sell_break

    if side == "buy":
        sell_signal[:] = False
    elif side == "sell":
        buy_signal[:] = False

    out = work.copy()
    out["buy_signal"] = buy_signal.fillna(False)
    out["sell_signal"] = sell_signal.fillna(False)
    out["entry_buy"] = prev["high"]
    out["entry_sell"] = prev["low"]
    out["signal_atr"] = prev["ATR"]
    out["signal_time"] = prev["time"]
    out["signal_high"] = prev["high"]
    out["signal_low"] = prev["low"]
    out["signal_close"] = prev["close"]
    return out


def simulate_trade(
    rows: pd.DataFrame,
    start_pos: int,
    side: str,
    entry: float,
    atr: float,
    cfg: StrategyConfig,
    tie_break: str,
) -> Optional[Dict[str, Any]]:
    if not math.isfinite(entry) or not math.isfinite(atr) or atr <= 0:
        return None

    hold_bars = max(1, int(cfg.max_hold_minutes))
    end_pos = min(len(rows) - 1, start_pos + hold_bars - 1)
    future = rows.iloc[start_pos : end_pos + 1]
    if future.empty:
        return None

    if side == "BUY":
        stop = entry - cfg.stop_atr * atr
        target = entry + cfg.target_atr * atr
    else:
        stop = entry + cfg.stop_atr * atr
        target = entry - cfg.target_atr * atr

    mfe = 0.0
    mae = 0.0
    exit_price = float(future.iloc[-1]["close"])
    exit_reason = "TIME_EXIT"
    exit_time = future.iloc[-1]["time"]

    for _, bar in future.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        if side == "BUY":
            mfe = max(mfe, high - entry)
            mae = min(mae, low - entry)
            hit_stop = low <= stop
            hit_target = high >= target
            if hit_stop and hit_target:
                if tie_break == "skip":
                    return None
                exit_price = stop if tie_break == "stop" else target
                exit_reason = "AMBIGUOUS_STOP_FIRST" if tie_break == "stop" else "AMBIGUOUS_TARGET_FIRST"
                exit_time = bar["time"]
                break
            if hit_stop:
                exit_price = stop
                exit_reason = "STOP"
                exit_time = bar["time"]
                break
            if hit_target:
                exit_price = target
                exit_reason = "TARGET"
                exit_time = bar["time"]
                break
        else:
            mfe = max(mfe, entry - low)
            mae = min(mae, entry - high)
            hit_stop = high >= stop
            hit_target = low <= target
            if hit_stop and hit_target:
                if tie_break == "skip":
                    return None
                exit_price = stop if tie_break == "stop" else target
                exit_reason = "AMBIGUOUS_STOP_FIRST" if tie_break == "stop" else "AMBIGUOUS_TARGET_FIRST"
                exit_time = bar["time"]
                break
            if hit_stop:
                exit_price = stop
                exit_reason = "STOP"
                exit_time = bar["time"]
                break
            if hit_target:
                exit_price = target
                exit_reason = "TARGET"
                exit_time = bar["time"]
                break

    pnl = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    return {
        "side": side,
        "entry": round(entry, 5),
        "stop": round(stop, 5),
        "target": round(target, 5),
        "exit_price": round(float(exit_price), 5),
        "pnl_points": round(float(pnl), 5),
        "pnl_r": round(float(pnl / (cfg.stop_atr * atr)), 5) if cfg.stop_atr * atr else None,
        "mfe_points": round(float(mfe), 5),
        "mae_points": round(float(abs(mae)), 5),
        "exit_reason": exit_reason,
        "exit_time": str(exit_time),
    }


def backtest_config(
    symbol: str,
    base_m1: pd.DataFrame,
    base_m5: pd.DataFrame,
    base_m15: pd.DataFrame,
    cfg: StrategyConfig,
    args: argparse.Namespace,
    keep_trades: bool = False,
) -> Tuple[Metrics, List[Dict[str, Any]]]:
    m1 = add_ma_columns(base_m1, cfg.ma_type, cfg.fast, cfg.mid, cfg.slow)
    m5 = add_ma_columns(base_m5, cfg.ma_type, cfg.fast, cfg.mid, cfg.slow)
    m15 = add_ma_columns(base_m15, cfg.ma_type, cfg.fast, cfg.mid, cfg.slow)
    aligned = align_context(m1, m5, m15).reset_index(drop=True)
    signals = compute_signals(aligned, cfg, args.side).reset_index(drop=True)

    trades: List[Dict[str, Any]] = []
    signal_idx = signals.index[signals["buy_signal"] | signals["sell_signal"]].tolist()
    for idx in signal_idx:
        row = signals.iloc[idx]
        if bool(row["buy_signal"]):
            trade = simulate_trade(signals, idx, "BUY", float(row["entry_buy"]), float(row["signal_atr"]), cfg, args.tie_break)
        else:
            trade = simulate_trade(signals, idx, "SELL", float(row["entry_sell"]), float(row["signal_atr"]), cfg, args.tie_break)
        if trade is None:
            continue
        if keep_trades:
            trade.update(
                {
                    "signal_time": str(row["signal_time"]),
                    "entry_time": str(row["time"]),
                    "fast": cfg.fast,
                    "mid": cfg.mid,
                    "slow": cfg.slow,
                    "stop_atr": cfg.stop_atr,
                    "target_atr": cfg.target_atr,
                    "m15_mode": cfg.m15_mode,
                    "m5_mode": cfg.m5_mode,
                }
            )
        trades.append(trade)

    metrics = compute_metrics(symbol, cfg, trades)
    return metrics, trades if keep_trades else []


def compute_metrics(symbol: str, cfg: StrategyConfig, trades: List[Dict[str, Any]]) -> Metrics:
    pnl = np.array([float(t["pnl_points"]) for t in trades], dtype=float) if trades else np.array([], dtype=float)
    wins = int(np.sum(pnl > 0)) if len(pnl) else 0
    losses = int(np.sum(pnl < 0)) if len(pnl) else 0
    breakeven = int(np.sum(pnl == 0)) if len(pnl) else 0
    gross_profit = float(np.sum(pnl[pnl > 0])) if len(pnl) else 0.0
    gross_loss = float(abs(np.sum(pnl[pnl < 0]))) if len(pnl) else 0.0
    net = float(np.sum(pnl)) if len(pnl) else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    avg = float(np.mean(pnl)) if len(pnl) else 0.0

    mfe = np.array([float(t.get("mfe_points", 0.0)) for t in trades], dtype=float) if trades else np.array([], dtype=float)
    mae = np.array([float(t.get("mae_points", 0.0)) for t in trades], dtype=float) if trades else np.array([], dtype=float)
    avg_mfe = float(np.mean(mfe)) if len(mfe) else 0.0
    avg_mae = float(np.mean(mae)) if len(mae) else 0.0
    mfe_mae = avg_mfe / avg_mae if avg_mae > 0 else 0.0

    equity = np.cumsum(pnl) if len(pnl) else np.array([], dtype=float)
    if len(equity):
        peak = np.maximum.accumulate(equity)
        dd = peak - equity
        max_dd = float(np.max(dd))
    else:
        max_dd = 0.0

    max_loss_streak = 0
    current = 0
    for value in pnl:
        if value < 0:
            current += 1
            max_loss_streak = max(max_loss_streak, current)
        else:
            current = 0

    buy_pnl = np.array([float(t["pnl_points"]) for t in trades if t["side"] == "BUY"], dtype=float)
    sell_pnl = np.array([float(t["pnl_points"]) for t in trades if t["side"] == "SELL"], dtype=float)
    buy_trades = int(len(buy_pnl))
    sell_trades = int(len(sell_pnl))
    buy_wr = float(np.mean(buy_pnl > 0)) if buy_trades else 0.0
    sell_wr = float(np.mean(sell_pnl > 0)) if sell_trades else 0.0

    days = set()
    for t in trades:
        entry_time = t.get("entry_time") or t.get("signal_time") or ""
        if entry_time:
            days.add(str(entry_time)[:10])
    active_days = len(days)
    trades_per_day = len(trades) / active_days if active_days else 0.0

    win_rate = wins / len(trades) if trades else 0.0
    expectancy_r_values = [float(t.get("pnl_r", 0.0) or 0.0) for t in trades]
    expectancy_r = float(np.mean(expectancy_r_values)) if expectancy_r_values else 0.0

    # Score robusto e conservador: premia PF, expectancy, win rate e MFE/MAE; penaliza DD e pouca amostra.
    sample_penalty = min(1.0, len(trades) / 100.0)
    dd_penalty = 1.0 / (1.0 + max_dd / 100.0)
    robustness = sample_penalty * dd_penalty * min(2.0, pf) * max(0.0, expectancy_r + 0.5) * max(0.1, mfe_mae)
    score = (win_rate * 100.0) + (min(pf, 5.0) * 20.0) + (expectancy_r * 25.0) + (mfe_mae * 10.0) - (max_loss_streak * 2.0)

    return Metrics(
        symbol=symbol,
        ma_type=cfg.ma_type,
        fast=cfg.fast,
        mid=cfg.mid,
        slow=cfg.slow,
        stop_atr=cfg.stop_atr,
        target_atr=cfg.target_atr,
        max_hold_minutes=cfg.max_hold_minutes,
        m15_mode=cfg.m15_mode,
        m5_mode=cfg.m5_mode,
        max_entry_candle_atr=cfg.max_entry_candle_atr,
        max_distance_slow_atr=cfg.max_distance_slow_atr,
        trades=int(len(trades)),
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=round(win_rate, 6),
        gross_profit_points=round(gross_profit, 5),
        gross_loss_points=round(gross_loss, 5),
        net_points=round(net, 5),
        avg_points=round(avg, 5),
        profit_factor=round(pf, 6),
        expectancy_r=round(expectancy_r, 6),
        avg_mfe_points=round(avg_mfe, 5),
        avg_mae_points=round(avg_mae, 5),
        mfe_mae_ratio=round(mfe_mae, 6),
        max_drawdown_points=round(max_dd, 5),
        max_loss_streak=max_loss_streak,
        buy_trades=buy_trades,
        sell_trades=sell_trades,
        buy_win_rate=round(buy_wr, 6),
        sell_win_rate=round(sell_wr, 6),
        trades_per_day=round(trades_per_day, 4),
        active_days=active_days,
        robustness_score=round(float(robustness), 6),
        score=round(float(score), 6),
    )


def metrics_to_frame(metrics: Iterable[Metrics]) -> pd.DataFrame:
    rows = [asdict(m) for m in metrics]
    return pd.DataFrame(rows)


def write_outputs(out_dir: Path, metrics_df: pd.DataFrame, sample_trades: List[Dict[str, Any]], args: argparse.Namespace) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if metrics_df.empty:
        raise RuntimeError("Nenhuma métrica gerada.")

    filtered = metrics_df[metrics_df["trades"] >= args.min_trades].copy()
    if filtered.empty:
        filtered = metrics_df.copy()

    top = filtered.sort_values(
        ["score", "profit_factor", "expectancy_r", "win_rate", "trades"],
        ascending=[False, False, False, False, False],
    ).head(args.top_n)

    top.to_csv(out_dir / "top_configs.csv", index=False, encoding="utf-8")
    (out_dir / "top_configs.json").write_text(top.to_json(orient="records", indent=2, force_ascii=False), encoding="utf-8")

    if sample_trades:
        pd.DataFrame(sample_trades).head(args.write_trades_sample).to_csv(out_dir / "trades_sample.csv", index=False, encoding="utf-8")

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol.upper(),
        "ma_type": args.ma_type,
        "configs_evaluated": int(len(metrics_df)),
        "configs_after_min_trades": int(len(filtered)),
        "min_trades": args.min_trades,
        "top_n": args.top_n,
        "best_config": top.iloc[0].to_dict() if not top.empty else None,
        "ranking_semantics": {
            "score": "Ranking composto; não deve ser usado sozinho.",
            "profit_factor": "Lucro bruto / perda bruta em pontos.",
            "expectancy_r": "Expectativa média por trade em R.",
            "robustness_score": "Penaliza pouca amostra e drawdown; ajuda a evitar overfit.",
        },
        "acceptance_hint": "Preferir zonas de parâmetros robustas, não um único melhor número isolado.",
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    symbol = args.symbol.upper().strip()
    root = args.project_root.resolve()
    data_dir = args.data_dir or (root / "data")
    out_dir = args.output_dir or (root / "data" / "research" / "ma_confluence" / symbol)

    log(f"[INFO] Carregando parquets | symbol={symbol} data_dir={data_dir}")
    base_m1 = load_tf(data_dir, symbol, TF_M1)
    base_m5 = load_tf(data_dir, symbol, TF_M5)
    base_m15 = load_tf(data_dir, symbol, TF_M15)
    log(f"[INFO] Linhas fechadas | M1={len(base_m1)} M5={len(base_m5)} M15={len(base_m15)}")

    configs = build_grid(args)
    log(f"[INFO] Combinações a avaliar: {len(configs)}")
    if not configs:
        raise RuntimeError("Nenhuma combinação gerada. Ajuste ranges/steps.")

    all_metrics: List[Metrics] = []
    sample_trades: List[Dict[str, Any]] = []
    best_score = -1e18
    best_cfg: Optional[StrategyConfig] = None

    for i, cfg in enumerate(configs, start=1):
        keep = args.write_trades_sample > 0 and len(sample_trades) < args.write_trades_sample
        metrics, trades = backtest_config(symbol, base_m1, base_m5, base_m15, cfg, args, keep_trades=keep)
        all_metrics.append(metrics)
        if trades and len(sample_trades) < args.write_trades_sample:
            sample_trades.extend(trades[: max(0, args.write_trades_sample - len(sample_trades))])
        if metrics.score > best_score and metrics.trades >= args.min_trades:
            best_score = metrics.score
            best_cfg = cfg
        if i == 1 or i % 500 == 0 or i == len(configs):
            best_text = f" best={best_cfg.fast}/{best_cfg.mid}/{best_cfg.slow}" if best_cfg else ""
            log(f"[INFO] Progresso {i}/{len(configs)}{best_text}")

    df = metrics_to_frame(all_metrics)
    write_outputs(out_dir, df, sample_trades, args)

    filtered = df[df["trades"] >= args.min_trades].copy()
    if filtered.empty:
        filtered = df.copy()
    top = filtered.sort_values(["score", "profit_factor", "expectancy_r"], ascending=[False, False, False]).head(10)

    log("[OK] Otimização concluída")
    log(f"[OK] Output: {out_dir}")
    log("\nTOP 10:")
    cols = [
        "fast",
        "mid",
        "slow",
        "stop_atr",
        "target_atr",
        "max_hold_minutes",
        "m15_mode",
        "trades",
        "win_rate",
        "profit_factor",
        "expectancy_r",
        "net_points",
        "max_drawdown_points",
        "score",
    ]
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print(top[cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
