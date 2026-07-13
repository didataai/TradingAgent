#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - DXY x GOLD Research

Pesquisa offline, separada do pipeline operacional, para medir se o DXY
sintetico gerado pelo MT5 acrescenta informacao ao GOLD.

Leituras principais:
- retorno do DXY vs retorno futuro do GOLD;
- volatilidade do DXY vs amplitude futura do GOLD;
- lags do DXY em M1/M5/M15/H1;
- estabilidade por horario e por timeframe;
- comparacao simples contra baseline ingenua.

Nao gera sinal operacional. Nao usa shuffle. Nao usa candle aberto.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEFRAMES = ("M1", "M5", "M15", "H1")
DEFAULT_LAGS = (0, 1, 2, 3, 5, 10)
DEFAULT_HORIZONS = (1, 3, 5, 10)


@dataclass(frozen=True)
class ResearchConfig:
    symbol: str
    dxy_mode: str
    timeframes: tuple[str, ...]
    lags: tuple[int, ...]
    horizons: tuple[int, ...]
    min_rows: int
    rolling_window: int
    data_dir: Path
    dxy_dir: Path
    output_dir: Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def safe_round(value: Any, digits: int = 6) -> Any:
    value = finite_float(value)
    if value is None:
        return None
    return round(value, digits)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
    df = pd.read_parquet(path)
    if df.empty:
        raise ValueError(f"Arquivo vazio: {path}")
    return df


def find_time_column(df: pd.DataFrame) -> str:
    for col in ("time", "timestamp", "time_brt", "datetime", "date"):
        if col in df.columns:
            return col
    raise ValueError(f"Nenhuma coluna de tempo encontrada. Colunas={list(df.columns)[:20]}")


def find_close_column(df: pd.DataFrame, preferred: tuple[str, ...]) -> str:
    for col in preferred:
        if col in df.columns:
            return col
    raise ValueError(f"Nenhuma coluna de close/valor encontrada. Colunas={list(df.columns)[:30]}")


def normalize_market_frame(df: pd.DataFrame, *, value_names: tuple[str, ...], prefix: str) -> pd.DataFrame:
    work = df.copy()
    time_col = find_time_column(work)
    close_col = find_close_column(work, value_names)

    out = pd.DataFrame()
    out["time"] = pd.to_datetime(work[time_col], errors="coerce", utc=True)
    out[f"{prefix}_close"] = pd.to_numeric(work[close_col], errors="coerce")

    if "open" in work.columns:
        out[f"{prefix}_open"] = pd.to_numeric(work["open"], errors="coerce")
    if "high" in work.columns:
        out[f"{prefix}_high"] = pd.to_numeric(work["high"], errors="coerce")
    if "low" in work.columns:
        out[f"{prefix}_low"] = pd.to_numeric(work["low"], errors="coerce")
    if "ATR" in work.columns:
        out[f"{prefix}_atr"] = pd.to_numeric(work["ATR"], errors="coerce")
    if "is_live_bar" in work.columns:
        live = pd.to_numeric(work["is_live_bar"], errors="coerce").fillna(0).astype(int)
        out["is_live_bar"] = live.values
    else:
        out["is_live_bar"] = 0

    out = out.dropna(subset=["time", f"{prefix}_close"])
    out = out[out[f"{prefix}_close"] > 0]
    out = out[out["is_live_bar"] != 1]
    out = out.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)
    return out


def load_pair(config: ResearchConfig, tf: str) -> pd.DataFrame:
    gold_path = config.data_dir / f"{config.symbol}_{tf}.parquet"
    dxy_path = config.dxy_dir / f"{config.dxy_mode}_{tf}.parquet"

    gold = normalize_market_frame(
        load_parquet(gold_path),
        value_names=("close", "Close", "value", "dxy_value"),
        prefix="gold",
    )
    dxy = normalize_market_frame(
        load_parquet(dxy_path),
        value_names=("dxy_value", "value", "close", "Close"),
        prefix="dxy",
    )

    merged = pd.merge(gold.drop(columns=["is_live_bar"], errors="ignore"), dxy.drop(columns=["is_live_bar"], errors="ignore"), on="time", how="inner")
    merged = merged.dropna(subset=["gold_close", "dxy_close"]).sort_values("time").reset_index(drop=True)
    if len(merged) < config.min_rows:
        raise ValueError(f"Poucas linhas alinhadas para {tf}: {len(merged)} < {config.min_rows}")
    return merged


def add_base_features(df: pd.DataFrame, rolling_window: int) -> pd.DataFrame:
    work = df.copy()
    work["gold_ret_1"] = np.log(work["gold_close"]).diff()
    work["dxy_ret_1"] = np.log(work["dxy_close"]).diff()
    work["dxy_abs_ret_1"] = work["dxy_ret_1"].abs()
    work["gold_abs_ret_1"] = work["gold_ret_1"].abs()

    if {"gold_high", "gold_low"}.issubset(work.columns):
        work["gold_range"] = (work["gold_high"] - work["gold_low"]).abs()
        if "gold_atr" in work.columns:
            atr = work["gold_atr"].replace(0, np.nan)
            work["gold_range_atr"] = work["gold_range"] / atr
    else:
        work["gold_range"] = np.nan
        work["gold_range_atr"] = np.nan

    work["rolling_corr_now"] = work["gold_ret_1"].rolling(rolling_window).corr(work["dxy_ret_1"])
    work["hour_utc"] = work["time"].dt.hour
    work["date"] = work["time"].dt.date.astype(str)
    return work


def corr_safe(a: pd.Series, b: pd.Series) -> float | None:
    pair = pd.concat([a, b], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pair) < 20:
        return None
    if pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return None
    return finite_float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))


def direction_stats(dxy_signal: pd.Series, gold_future: pd.Series) -> dict[str, Any]:
    pair = pd.concat([dxy_signal, gold_future], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pair) < 20:
        return {"rows": int(len(pair))}

    dxy_sign = np.sign(pair.iloc[:, 0])
    gold_sign = np.sign(pair.iloc[:, 1])
    active = (dxy_sign != 0) & (gold_sign != 0)
    dxy_sign = dxy_sign[active]
    gold_sign = gold_sign[active]
    if len(dxy_sign) < 20:
        return {"rows": int(len(dxy_sign))}

    inverse_hits = (dxy_sign * gold_sign < 0).mean()
    positive_hits = (dxy_sign * gold_sign > 0).mean()
    majority_baseline = max((gold_sign > 0).mean(), (gold_sign < 0).mean())

    return {
        "rows": int(len(dxy_sign)),
        "inverse_hit_rate": round(float(inverse_hits), 6),
        "positive_hit_rate": round(float(positive_hits), 6),
        "gold_direction_baseline": round(float(majority_baseline), 6),
        "inverse_edge_vs_baseline": round(float(inverse_hits - majority_baseline), 6),
        "positive_edge_vs_baseline": round(float(positive_hits - majority_baseline), 6),
    }


def build_lag_matrix(df: pd.DataFrame, tf: str, lags: tuple[int, ...], horizons: tuple[int, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for lag in lags:
        dxy_signal = df["dxy_ret_1"].shift(lag)
        dxy_abs_signal = df["dxy_abs_ret_1"].shift(lag)
        for horizon in horizons:
            gold_future = np.log(df["gold_close"].shift(-horizon) / df["gold_close"])
            gold_future_abs = gold_future.abs()

            stats = direction_stats(dxy_signal, gold_future)
            rows.append({
                "timeframe": tf,
                "lag_bars": lag,
                "future_horizon_bars": horizon,
                "rows": stats.get("rows", 0),
                "corr_dxy_ret_vs_gold_future_ret": safe_round(corr_safe(dxy_signal, gold_future)),
                "corr_abs_dxy_ret_vs_abs_gold_future_ret": safe_round(corr_safe(dxy_abs_signal, gold_future_abs)),
                "inverse_hit_rate": stats.get("inverse_hit_rate"),
                "positive_hit_rate": stats.get("positive_hit_rate"),
                "gold_direction_baseline": stats.get("gold_direction_baseline"),
                "inverse_edge_vs_baseline": stats.get("inverse_edge_vs_baseline"),
                "positive_edge_vs_baseline": stats.get("positive_edge_vs_baseline"),
            })
    return pd.DataFrame(rows)


def build_hour_matrix(df: pd.DataFrame, tf: str, best_lag: int, best_horizon: int) -> pd.DataFrame:
    work = df.copy()
    work["dxy_signal"] = work["dxy_ret_1"].shift(best_lag)
    work["gold_future"] = np.log(work["gold_close"].shift(-best_horizon) / work["gold_close"])
    rows: list[dict[str, Any]] = []
    for hour, group in work.groupby("hour_utc"):
        stats = direction_stats(group["dxy_signal"], group["gold_future"])
        rows.append({
            "timeframe": tf,
            "hour_utc": int(hour),
            "lag_bars": best_lag,
            "future_horizon_bars": best_horizon,
            "rows": stats.get("rows", 0),
            "corr": safe_round(corr_safe(group["dxy_signal"], group["gold_future"])),
            "inverse_hit_rate": stats.get("inverse_hit_rate"),
            "positive_hit_rate": stats.get("positive_hit_rate"),
            "inverse_edge_vs_baseline": stats.get("inverse_edge_vs_baseline"),
            "positive_edge_vs_baseline": stats.get("positive_edge_vs_baseline"),
        })
    return pd.DataFrame(rows)


def select_best_rows(lag_matrix: pd.DataFrame) -> dict[str, Any]:
    work = lag_matrix.copy()
    work["abs_corr"] = pd.to_numeric(work["corr_dxy_ret_vs_gold_future_ret"], errors="coerce").abs()
    work["abs_vol_corr"] = pd.to_numeric(work["corr_abs_dxy_ret_vs_abs_gold_future_ret"], errors="coerce").abs()
    work["inverse_edge"] = pd.to_numeric(work["inverse_edge_vs_baseline"], errors="coerce")
    work["positive_edge"] = pd.to_numeric(work["positive_edge_vs_baseline"], errors="coerce")

    best_corr = work.sort_values("abs_corr", ascending=False).head(1)
    best_vol = work.sort_values("abs_vol_corr", ascending=False).head(1)
    best_inverse = work.sort_values("inverse_edge", ascending=False).head(1)
    best_positive = work.sort_values("positive_edge", ascending=False).head(1)

    def as_dict(frame: pd.DataFrame) -> dict[str, Any] | None:
        if frame.empty:
            return None
        return {k: (None if pd.isna(v) else v) for k, v in frame.iloc[0].drop(labels=["abs_corr", "abs_vol_corr", "inverse_edge", "positive_edge"], errors="ignore").to_dict().items()}

    return {
        "best_direction_correlation": as_dict(best_corr),
        "best_volatility_correlation": as_dict(best_vol),
        "best_inverse_direction_edge": as_dict(best_inverse),
        "best_positive_direction_edge": as_dict(best_positive),
    }


def interpret(best: dict[str, Any]) -> dict[str, str]:
    corr_row = best.get("best_direction_correlation") or {}
    vol_row = best.get("best_volatility_correlation") or {}
    inv_row = best.get("best_inverse_direction_edge") or {}
    pos_row = best.get("best_positive_direction_edge") or {}

    corr = abs(finite_float(corr_row.get("corr_dxy_ret_vs_gold_future_ret"), 0.0) or 0.0)
    vol_corr = abs(finite_float(vol_row.get("corr_abs_dxy_ret_vs_abs_gold_future_ret"), 0.0) or 0.0)
    inv_edge = finite_float(inv_row.get("inverse_edge_vs_baseline"), 0.0) or 0.0
    pos_edge = finite_float(pos_row.get("positive_edge_vs_baseline"), 0.0) or 0.0

    if corr >= 0.20 or max(inv_edge, pos_edge) >= 0.08:
        direction = "POTENTIAL_DIRECTIONAL_SIGNAL"
    elif corr >= 0.10 or max(inv_edge, pos_edge) >= 0.03:
        direction = "WEAK_DIRECTIONAL_CONTEXT"
    else:
        direction = "NO_CLEAR_DIRECTIONAL_EDGE"

    if vol_corr >= 0.20:
        volatility = "POTENTIAL_VOLATILITY_SIGNAL"
    elif vol_corr >= 0.10:
        volatility = "WEAK_VOLATILITY_CONTEXT"
    else:
        volatility = "NO_CLEAR_VOLATILITY_EDGE"

    relation = "UNSTABLE"
    if inv_edge > pos_edge and inv_edge > 0.03:
        relation = "INVERSE_BIAS_CANDIDATE"
    elif pos_edge > inv_edge and pos_edge > 0.03:
        relation = "POSITIVE_BIAS_CANDIDATE"

    return {
        "directional_read": direction,
        "volatility_read": volatility,
        "relationship_read": relation,
        "warning": "Pesquisa exploratoria. Nao usar como regra operacional sem split temporal/walk-forward fora da amostra.",
    }


def run_research(config: ResearchConfig) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    all_lag: list[pd.DataFrame] = []
    all_hour: list[pd.DataFrame] = []
    tf_summaries: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for tf in config.timeframes:
        try:
            merged = add_base_features(load_pair(config, tf), config.rolling_window)
            lag_matrix = build_lag_matrix(merged, tf, config.lags, config.horizons)
            best = select_best_rows(lag_matrix)

            best_for_hour = best.get("best_direction_correlation") or {}
            best_lag = int(best_for_hour.get("lag_bars", 0) or 0)
            best_horizon = int(best_for_hour.get("future_horizon_bars", 1) or 1)
            hour_matrix = build_hour_matrix(merged, tf, best_lag, best_horizon)

            tf_summaries[tf] = {
                "rows_aligned": int(len(merged)),
                "first_time": str(merged["time"].min()),
                "last_time": str(merged["time"].max()),
                "latest_rolling_corr": safe_round(merged["rolling_corr_now"].dropna().iloc[-1] if merged["rolling_corr_now"].dropna().size else None),
                "mean_rolling_corr": safe_round(merged["rolling_corr_now"].mean()),
                "best": best,
                "interpretation": interpret(best),
            }
            all_lag.append(lag_matrix)
            all_hour.append(hour_matrix)
        except Exception as exc:
            errors[tf] = f"{type(exc).__name__}: {exc}"

    lag_out = pd.concat(all_lag, ignore_index=True) if all_lag else pd.DataFrame()
    hour_out = pd.concat(all_hour, ignore_index=True) if all_hour else pd.DataFrame()

    if not lag_out.empty:
        lag_out.to_csv(config.output_dir / "dxy_gold_lag_matrix.csv", index=False)
    if not hour_out.empty:
        hour_out.to_csv(config.output_dir / "dxy_gold_by_hour.csv", index=False)

    summary = {
        "generated_at_utc": utc_now_iso(),
        "symbol": config.symbol,
        "dxy_mode": config.dxy_mode,
        "timeframes": list(config.timeframes),
        "lags": list(config.lags),
        "horizons": list(config.horizons),
        "min_rows": config.min_rows,
        "rolling_window": config.rolling_window,
        "outputs": {
            "lag_matrix": str(config.output_dir / "dxy_gold_lag_matrix.csv"),
            "by_hour": str(config.output_dir / "dxy_gold_by_hour.csv"),
            "summary": str(config.output_dir / "dxy_gold_summary.json"),
        },
        "timeframe_summaries": tf_summaries,
        "errors": errors,
        "usage_rule": "Research only. Do not create BUY/SELL from DXY alone.",
    }
    write_json(config.output_dir / "dxy_gold_summary.json", summary)
    return summary


def parse_int_list(values: list[str] | None, default: tuple[int, ...]) -> tuple[int, ...]:
    if not values:
        return default
    return tuple(int(v) for v in values)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pesquisa DXY sintetico x GOLD por Parquet.")
    parser.add_argument("--symbol", default="GOLD", help="Ativo alvo. Padrao: GOLD.")
    parser.add_argument("--dxy-mode", default="DXY_FULL", choices=["DXY_FULL", "USD_PROXY_3"], help="Indice sintetico a analisar.")
    parser.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES), help="Timeframes. Padrao: M1 M5 M15 H1.")
    parser.add_argument("--lags", nargs="+", help="Lags do DXY em barras. Padrao: 0 1 2 3 5 10.")
    parser.add_argument("--horizons", nargs="+", help="Horizontes futuros do GOLD em barras. Padrao: 1 3 5 10.")
    parser.add_argument("--min-rows", type=int, default=300, help="Minimo de linhas alinhadas por timeframe.")
    parser.add_argument("--rolling-window", type=int, default=100, help="Janela da correlacao rolling.")
    parser.add_argument("--data-dir", default="data", help="Diretorio dos parquets do GOLD.")
    parser.add_argument("--dxy-dir", default="data/market_context/synthetic_dollar", help="Diretorio dos parquets do DXY sintetico.")
    parser.add_argument("--output-dir", help="Diretorio de saida. Padrao: data/research/dxy_gold/<SYMBOL>.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbol = args.symbol.upper().strip()
    output_dir = Path(args.output_dir) if args.output_dir else Path("data") / "research" / "dxy_gold" / symbol
    config = ResearchConfig(
        symbol=symbol,
        dxy_mode=args.dxy_mode,
        timeframes=tuple(str(tf).upper().strip() for tf in args.timeframes),
        lags=parse_int_list(args.lags, DEFAULT_LAGS),
        horizons=parse_int_list(args.horizons, DEFAULT_HORIZONS),
        min_rows=int(args.min_rows),
        rolling_window=int(args.rolling_window),
        data_dir=(ROOT / args.data_dir).resolve(),
        dxy_dir=(ROOT / args.dxy_dir).resolve(),
        output_dir=(ROOT / output_dir).resolve(),
    )

    try:
        summary = run_research(config)
        ok_tfs = sorted(summary.get("timeframe_summaries", {}).keys())
        print(f"[OK] DXY x {symbol} research | dxy_mode={config.dxy_mode} | timeframes={ok_tfs}")
        print(f"[OK] Output: {config.output_dir}")
        for tf, item in summary.get("timeframe_summaries", {}).items():
            interp = item.get("interpretation", {})
            print(
                f"  {tf}: rows={item.get('rows_aligned')} "
                f"latest_corr={item.get('latest_rolling_corr')} "
                f"direction={interp.get('directional_read')} "
                f"vol={interp.get('volatility_read')} "
                f"relation={interp.get('relationship_read')}"
            )
        if summary.get("errors"):
            print(f"[WARN] Erros: {summary['errors']}")
        return 0
    except Exception as exc:
        print(f"[ERRO] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
