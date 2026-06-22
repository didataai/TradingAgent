#!/usr/bin/env python3
"""Motor único de inteligência histórica e runtime para o TradingAgent.

Dependências: pandas, numpy, pyarrow

BUILD:
  python market_intelligence.py build --symbol GOLD \
    --input-dir data/consolidated --output data/intelligence/GOLD.json

ENRICH:
  python market_intelligence.py enrich --profile data/intelligence/GOLD.json \
    --payload data/context/GOLD_intraday.json \
    --output data/context/GOLD_intraday_enriched.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCHEMA_VERSION = "1.5.1"
DEFAULT_TFS = ("M1", "M5", "M15", "H1", "H4")
HORIZON_WINDOWS = {
    "M1": {"fast": 5, "base": 10, "extended": 15},
    "M5": {"fast": 3, "base": 6, "extended": 12},
    "M15": {"fast": 2, "base": 4, "extended": 8},
    "H1": {"fast": 1, "base": 3, "extended": 6},
    "H4": {"fast": 1, "base": 3, "extended": 6},
}
LOWER_TF = {"H4": "H1", "H1": "M15", "M15": "M5", "M5": "M1"}
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}



def jclean(v: Any) -> Any:
    """Converte tipos numpy/pandas e arredonda métricas."""
    if isinstance(v, dict):
        return {str(k): jclean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jclean(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        value = float(v)
        return None if not math.isfinite(value) else round(value, 6)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"JSON inválido: {path}")
    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    """Grava atomicamente em UTF-8 usando JSON compacto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(
            jclean(data),
            f,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        f.write("\n")
    tmp.replace(path)


def bseries(s: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(s):
        return s.fillna(False)
    if pd.api.types.is_numeric_dtype(s):
        return s.fillna(0).astype(int).astype(bool)
    return s.astype(str).str.lower().isin({"1", "true", "yes", "sim"})


def discover(input_dir: Path, symbol: str, tf: str) -> Path | None:
    exact = [
        input_dir / f"{symbol}_{tf}.parquet",
        input_dir / f"{symbol}_intraday_{tf}.parquet",
        input_dir / f"{symbol}_swing_{tf}.parquet",
    ]
    for p in exact:
        if p.exists():
            return p
    matches = [
        p for p in input_dir.rglob("*.parquet")
        if symbol.lower() in p.stem.lower() and tf.lower() in p.stem.lower()
    ]
    return max(matches, key=lambda p: p.stat().st_mtime) if matches else None


def prepare(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path).copy()
    required = {"open", "high", "low", "close", "ATR"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{path.name}: faltam colunas {missing}")

    tcol = next((c for c in ("time_brt", "time", "timestamp", "datetime") if c in df.columns), None)
    if not tcol:
        raise ValueError(f"{path.name}: coluna temporal não encontrada")

    df["event_time"] = pd.to_datetime(df[tcol], errors="coerce")
    df = df.dropna(subset=["event_time", "open", "high", "low", "close", "ATR"])
    df = df.sort_values("event_time").drop_duplicates("event_time", keep="last")
    if "is_live_bar" in df.columns:
        df = df.loc[~bseries(df["is_live_bar"])].copy()

    for c in ("open", "high", "low", "close", "ATR"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    if "vol_ratio" not in df.columns:
        vol = pd.to_numeric(df.get("tick_volume"), errors="coerce")
        df["vol_ratio"] = vol / vol.rolling(20, min_periods=5).mean().replace(0, np.nan)
    else:
        df["vol_ratio"] = pd.to_numeric(df["vol_ratio"], errors="coerce")

    if "range_atr" not in df.columns:
        df["range_atr"] = (df["high"] - df["low"]) / df["ATR"].replace(0, np.nan)

    prev_high, prev_low = df["high"].shift(1), df["low"].shift(1)
    for c in ("breakout_up", "breakout_down", "false_breakout_up", "false_breakout_down", "compression_flag"):
        df[c] = bseries(df[c]) if c in df.columns else False

    if not (df["breakout_up"].any() or df["breakout_down"].any()):
        df["breakout_up"] = df["close"] > prev_high
        df["breakout_down"] = df["close"] < prev_low
        df["false_breakout_up"] = (df["high"] > prev_high) & (df["close"] <= prev_high)
        df["false_breakout_down"] = (df["low"] < prev_low) & (df["close"] >= prev_low)

    if not df["compression_flag"].any():
        q = df["range_atr"].rolling(20, min_periods=10).quantile(.30)
        df["compression_flag"] = df["range_atr"] <= q

    if "structure_state" in df.columns:
        df["structure"] = pd.to_numeric(df["structure_state"], errors="coerce").fillna(0).astype(int)
    else:
        e20 = df["close"].ewm(span=20, adjust=False).mean()
        e50 = df["close"].ewm(span=50, adjust=False).mean()
        df["structure"] = np.select([e20 > e50, e20 < e50], [1, -1], default=0)

    df["hour"] = df["event_time"].dt.hour
    df["weekday"] = df["event_time"].dt.day_name().str.upper()
    df["month"] = df["event_time"].dt.month
    df["vol_bucket"] = pd.cut(df["vol_ratio"], [-np.inf,.8,1,1.5,np.inf], labels=["LOW","NORMAL","HIGH","SPIKE"]).astype("object").fillna("UNKNOWN")
    df["atr_bucket"] = pd.cut(df["range_atr"], [-np.inf,.6,1,1.5,np.inf], labels=["LOW","NORMAL","HIGH","EXTREME"]).astype("object").fillna("UNKNOWN")
    return df.reset_index(drop=True)


def _first_touch_metrics(
    df: pd.DataFrame,
    direction: str,
    horizon: int,
    target_atr: float,
    stop_atr: float,
) -> pd.DataFrame:
    """Calcula TP/SL em ordem cronológica usando OHLC de barras futuras.

    Quando TP e SL são tocados na mesma barra, o resultado é AMBIGUOUS, pois
    OHLC não informa a sequência intrabar.
    """
    n = len(df)
    result = np.full(n, "NO_TOUCH", dtype=object)
    bars_to_result = np.full(n, np.nan)
    adverse_before_target = np.full(n, np.nan)
    favorable_before_stop = np.full(n, np.nan)

    close = df["close"].to_numpy(dtype=float)
    atr = df["ATR"].replace(0, np.nan).to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)

    for i in range(n):
        if not np.isfinite(close[i]) or not np.isfinite(atr[i]):
            result[i] = "INVALID"
            continue
        entry = close[i]
        if direction == "UP":
            tp = entry + target_atr * atr[i]
            sl = entry - stop_atr * atr[i]
        else:
            tp = entry - target_atr * atr[i]
            sl = entry + stop_atr * atr[i]

        max_adverse = 0.0
        max_favorable = 0.0
        last = min(n, i + horizon + 1)
        for j in range(i + 1, last):
            if direction == "UP":
                tp_hit = highs[j] >= tp
                sl_hit = lows[j] <= sl
                max_adverse = max(max_adverse, (entry - lows[j]) / atr[i])
                max_favorable = max(max_favorable, (highs[j] - entry) / atr[i])
            else:
                tp_hit = lows[j] <= tp
                sl_hit = highs[j] >= sl
                max_adverse = max(max_adverse, (highs[j] - entry) / atr[i])
                max_favorable = max(max_favorable, (entry - lows[j]) / atr[i])

            if tp_hit and sl_hit:
                result[i] = "AMBIGUOUS"
                bars_to_result[i] = j - i
                adverse_before_target[i] = max_adverse
                favorable_before_stop[i] = max_favorable
                break
            if tp_hit:
                result[i] = "TP_FIRST"
                bars_to_result[i] = j - i
                adverse_before_target[i] = max_adverse
                favorable_before_stop[i] = max_favorable
                break
            if sl_hit:
                result[i] = "SL_FIRST"
                bars_to_result[i] = j - i
                adverse_before_target[i] = max_adverse
                favorable_before_stop[i] = max_favorable
                break

    suf = "up" if direction == "UP" else "down"
    out = pd.DataFrame(index=df.index)
    out[f"first_touch_{suf}_{stop_atr:g}"] = result
    out[f"bars_to_result_{suf}_{stop_atr:g}"] = bars_to_result
    out[f"adverse_before_target_{suf}_{stop_atr:g}"] = adverse_before_target
    out[f"favorable_before_stop_{suf}_{stop_atr:g}"] = favorable_before_stop
    return out


def _pullback_metrics(
    df: pd.DataFrame,
    direction: str,
    horizon: int,
    pullback_atr: float,
    target_atr: float,
    stop_atr: float,
) -> pd.DataFrame:
    """Simula entrada LIMIT após retração, com resultado conservador por barra.

    O alvo e o stop são medidos a partir do preço da LIMIT. Eventos com
    preenchimento e ambas as barreiras na mesma barra são AMBIGUOUS.
    """
    n = len(df)
    filled = np.zeros(n, dtype=bool)
    result = np.full(n, "NOT_FILLED", dtype=object)
    bars_to_fill = np.full(n, np.nan)
    bars_fill_to_result = np.full(n, np.nan)

    close = df["close"].to_numpy(dtype=float)
    atr = df["ATR"].replace(0, np.nan).to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)

    for i in range(n):
        if not np.isfinite(close[i]) or not np.isfinite(atr[i]):
            result[i] = "INVALID"
            continue
        entry = close[i] - pullback_atr * atr[i] if direction == "UP" else close[i] + pullback_atr * atr[i]
        tp = entry + target_atr * atr[i] if direction == "UP" else entry - target_atr * atr[i]
        sl = entry - stop_atr * atr[i] if direction == "UP" else entry + stop_atr * atr[i]
        fill_bar = None
        last = min(n, i + horizon + 1)

        for j in range(i + 1, last):
            touched_entry = lows[j] <= entry if direction == "UP" else highs[j] >= entry
            if fill_bar is None and touched_entry:
                fill_bar = j
                filled[i] = True
                bars_to_fill[i] = j - i

            if fill_bar is None:
                continue

            tp_hit = highs[j] >= tp if direction == "UP" else lows[j] <= tp
            sl_hit = lows[j] <= sl if direction == "UP" else highs[j] >= sl
            if tp_hit and sl_hit:
                result[i] = "AMBIGUOUS"
                bars_fill_to_result[i] = j - fill_bar
                break
            if tp_hit:
                result[i] = "TP_FIRST"
                bars_fill_to_result[i] = j - fill_bar
                break
            if sl_hit:
                result[i] = "SL_FIRST"
                bars_fill_to_result[i] = j - fill_bar
                break
            result[i] = "FILLED_NO_EXIT"

    suf = "up" if direction == "UP" else "down"
    tag = f"{pullback_atr:g}_{stop_atr:g}"
    out = pd.DataFrame(index=df.index)
    out[f"pb_filled_{suf}_{tag}"] = filled
    out[f"pb_result_{suf}_{tag}"] = result
    out[f"pb_bars_to_fill_{suf}_{tag}"] = bars_to_fill
    out[f"pb_bars_fill_to_result_{suf}_{tag}"] = bars_fill_to_result
    return out




def _ambiguous_case_ids(df: pd.DataFrame) -> set[tuple[int, str]]:
    cases: set[tuple[int, str]] = set()
    for col in df.columns:
        if col.startswith("first_touch_") or col.startswith("pb_result_"):
            mask = df[col].astype(str).eq("AMBIGUOUS")
            cases.update((int(i), col) for i in df.index[mask])
    return cases


def _resolve_ambiguous_with_lower_tf(
    parent: pd.DataFrame,
    lower: pd.DataFrame | None,
    parent_tf: str,
    lower_tf_name: str,
    horizon: int,
    target: float,
) -> dict[str, Any]:
    """Resolve casos ainda ambíguos usando uma série temporal inferior."""
    before = _ambiguous_case_ids(parent)
    if lower is None or lower.empty or not before:
        return {"attempted_cases": len(before), "resolved_cases": 0,
                "remaining_cases": len(before), "lower_timeframe": lower_tf_name}

    child = lower.sort_values("event_time").reset_index(drop=True)
    times = child["event_time"].to_numpy(dtype="datetime64[ns]")
    highs = child["high"].to_numpy(float)
    lows = child["low"].to_numpy(float)
    parent_minutes = TF_MINUTES[parent_tf]

    def bounds(ts: pd.Timestamp) -> tuple[int, int]:
        start = np.datetime64(ts + pd.Timedelta(minutes=parent_minutes))
        end = np.datetime64(ts + pd.Timedelta(minutes=parent_minutes * (horizon + 1)))
        return int(np.searchsorted(times, start, side="left")), int(np.searchsorted(times, end, side="left"))

    for direction in ("UP", "DOWN"):
        suf = "up" if direction == "UP" else "down"
        for stop in (0.4, 0.5, 0.6, 0.75, 1.0):
            col = f"first_touch_{suf}_{stop:g}"
            if col not in parent:
                continue
            for i in parent.index[parent[col].astype(str).eq("AMBIGUOUS")]:
                entry = float(parent.at[i, "close"]); atr = float(parent.at[i, "ATR"])
                if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
                    continue
                tp = entry + target*atr if direction == "UP" else entry-target*atr
                sl = entry - stop*atr if direction == "UP" else entry+stop*atr
                a,b = bounds(pd.Timestamp(parent.at[i,"event_time"])); outcome = None
                for j in range(a,b):
                    tph = highs[j] >= tp if direction == "UP" else lows[j] <= tp
                    slh = lows[j] <= sl if direction == "UP" else highs[j] >= sl
                    if tph and slh:
                        break
                    if tph: outcome = "TP_FIRST"; break
                    if slh: outcome = "SL_FIRST"; break
                if outcome:
                    parent.at[i,col] = outcome

        for pullback in (0.25, 0.5):
            tag=f"{pullback:g}_0.75"; rcol=f"pb_result_{suf}_{tag}"; fcol=f"pb_filled_{suf}_{tag}"
            if rcol not in parent:
                continue
            for i in parent.index[parent[rcol].astype(str).eq("AMBIGUOUS")]:
                close=float(parent.at[i,"close"]); atr=float(parent.at[i,"ATR"])
                if not np.isfinite(close) or not np.isfinite(atr) or atr<=0:
                    continue
                entry=close-pullback*atr if direction=="UP" else close+pullback*atr
                tp=entry+target*atr if direction=="UP" else entry-target*atr
                sl=entry-0.75*atr if direction=="UP" else entry+0.75*atr
                a,b=bounds(pd.Timestamp(parent.at[i,"event_time"])); filled=False; outcome=None
                for j in range(a,b):
                    if not filled:
                        filled = lows[j] <= entry if direction=="UP" else highs[j] >= entry
                        if not filled:
                            continue
                    tph = highs[j] >= tp if direction=="UP" else lows[j] <= tp
                    slh = lows[j] <= sl if direction=="UP" else highs[j] >= sl
                    if tph and slh:
                        break
                    if tph: outcome="TP_FIRST"; break
                    if slh: outcome="SL_FIRST"; break
                if outcome:
                    parent.at[i,rcol]=outcome; parent.at[i,fcol]=True

    after = _ambiguous_case_ids(parent)
    return {"attempted_cases": len(before), "resolved_cases": len(before-after),
            "remaining_cases": len(after), "lower_timeframe": lower_tf_name}


def _resolve_ambiguous_cascade(
    parent: pd.DataFrame,
    parent_tf: str,
    lower_chain: list[tuple[str, pd.DataFrame]],
    horizon: int,
    target: float,
) -> dict[str, Any]:
    initial_cases = _ambiguous_case_ids(parent)
    initial_events = {i for i,_ in initial_cases}
    levels=[]
    for lower_name, lower_df in lower_chain:
        if not _ambiguous_case_ids(parent):
            break
        levels.append(_resolve_ambiguous_with_lower_tf(parent, lower_df, parent_tf, lower_name, horizon, target))
    final_cases = _ambiguous_case_ids(parent)
    final_events = {i for i,_ in final_cases}
    resolved_cases = len(initial_cases-final_cases)
    fully_resolved_events = len(initial_events-final_events)
    return {
        "unique_ambiguous_events_before": len(initial_events),
        "unique_events_fully_resolved": fully_resolved_events,
        "event_resolution_rate": fully_resolved_events/len(initial_events) if initial_events else None,
        "ambiguous_execution_cases_before": len(initial_cases),
        "resolved_execution_cases": resolved_cases,
        "remaining_execution_cases": len(final_cases),
        "case_resolution_rate": resolved_cases/len(initial_cases) if initial_cases else None,
        "cascade": levels,
    }


def _expectancy_for_fixed_decision(execution: dict[str, Any], decision: dict[str, Any]) -> float | None:
    mode=decision.get("recommended_entry_mode"); variant=decision.get("recommended_variant")
    if mode == "MARKET":
        return get(execution, "close_entry", variant, "gross_expectancy_atr_all")
    if mode in {"LIMIT_0.25", "LIMIT_0.50"}:
        return get(execution, "pullback_entries", variant, "coverage_adjusted_expectancy_atr")
    return None


def _temporal_validation(g: pd.DataFrame, direction: str, target: float, horizon: int) -> dict[str, Any]:
    """OOS cronológico: a decisão é escolhida no treino e congelada."""
    if len(g) < 120:
        return {"status": "INSUFFICIENT_SAMPLE", "sample_size": int(len(g))}
    ordered=g.sort_values("event_time").copy(); n=len(ordered); a=int(n*.60); b=int(n*.80)
    parts={"train": ordered.iloc[:max(0,a-horizon)],
           "validation": ordered.iloc[a:max(a,b-horizon)],
           "test": ordered.iloc[b:]}
    train_stats=stat(parts["train"],direction,target,include_execution=True)
    frozen=train_stats.get("decision",{})
    out={"status":"OK","split":"60/20/20","embargo_bars":horizon,
         "selection_scope":"TRAIN_ONLY","frozen_decision":frozen,"periods":{}}
    vals=[]
    for name,part in parts.items():
        st=stat(part,direction,target,include_execution=True)
        best=st.get("decision",{})
        fixed_exp=_expectancy_for_fixed_decision(st.get("execution_given_attempt",{}),frozen)
        out["periods"][name]={"sample_size":int(len(part)),
            "frozen_decision_expectancy_atr":fixed_exp,
            "period_best_expectancy_atr":best.get("gross_expectancy_atr"),
            "period_best_entry_mode":best.get("recommended_entry_mode"),
            "confidence_grade":best.get("confidence_grade")}
        if fixed_exp is not None: vals.append(float(fixed_exp))
    out["positive_period_ratio"]=(sum(v>0 for v in vals)/len(vals)) if vals else None
    out["expectancy_stability"]=(1/(1+float(np.std(vals)))) if len(vals)>=2 else None
    tr=out["periods"]["train"].get("frozen_decision_expectancy_atr")
    te=out["periods"]["test"].get("frozen_decision_expectancy_atr")
    out["degradation_ratio"]=(te/tr) if tr not in (None,0) and te is not None else None
    out["oos_pass"] = bool(
        out["periods"]["validation"].get("frozen_decision_expectancy_atr") is not None
        and out["periods"]["validation"]["frozen_decision_expectancy_atr"] > 0
        and out["periods"]["test"].get("frozen_decision_expectancy_atr") is not None
        and out["periods"]["test"]["frozen_decision_expectancy_atr"] > 0
    )
    return out

def outcomes(df: pd.DataFrame, horizon: int, target: float) -> pd.DataFrame:
    x = df.copy()
    highs = pd.concat([x["high"].shift(-i) for i in range(1, horizon+1)], axis=1)
    lows = pd.concat([x["low"].shift(-i) for i in range(1, horizon+1)], axis=1)
    fhi, flo, atr, close = highs.max(axis=1), lows.min(axis=1), x["ATR"].replace(0, np.nan), x["close"]
    x["mfe_up"] = (fhi-close)/atr; x["mae_up"] = (close-flo)/atr
    x["mfe_down"] = (close-flo)/atr; x["mae_down"] = (fhi-close)/atr
    x["ok_up"] = x["mfe_up"] >= target; x["ok_down"] = x["mfe_down"] >= target
    x["clean_up"] = x["ok_up"] & (x["mae_up"] < target)
    x["clean_down"] = x["ok_down"] & (x["mae_down"] < target)

    for direction in ("UP", "DOWN"):
        for stop in (0.4, 0.5, 0.6, 0.75, 1.0):
            x = pd.concat(
                [x, _first_touch_metrics(x, direction, horizon, target, stop)],
                axis=1,
            )
        for pullback in (0.25, 0.5):
            x = pd.concat(
                [
                    x,
                    _pullback_metrics(
                        x,
                        direction,
                        horizon,
                        pullback,
                        target,
                        0.75,
                    ),
                ],
                axis=1,
            )

    # Avoid expensive repeated comparisons on string[pyarrow].
    for col in x.columns:
        if col.startswith("first_touch_") or col.startswith("pb_result_"):
            x[col] = x[col].astype("category")

    return x


def _rate(series: pd.Series, value: str, denominator: pd.Series | None = None) -> float | None:
    if denominator is not None:
        series = series.loc[denominator]
    if len(series) == 0:
        return None
    return float((series == value).mean())



def _execution_view(
    sample: pd.DataFrame,
    suf: str,
    target: float,
) -> dict[str, Any]:
    """Summarize sequential execution for a preselected sample."""
    total = int(len(sample))
    execution: dict[str, Any] = {
        "sample_size": total,
        "close_entry": {},
        "pullback_entries": {},
    }

    for stop in (0.4, 0.5, 0.6, 0.75, 1.0):
        col = f"first_touch_{suf}_{stop:g}"
        values = sample[col]
        counts = values.value_counts(dropna=False)

        tp = int(counts.get("TP_FIRST", 0))
        sl = int(counts.get("SL_FIRST", 0))
        ambiguous = int(counts.get("AMBIGUOUS", 0))
        no_touch = int(counts.get("NO_TOUCH", 0))
        valid_n = tp + sl + ambiguous + no_touch
        resolved_n = tp + sl

        resolved_mask = values.isin(["TP_FIRST", "SL_FIRST"])
        tp_mask = values.eq("TP_FIRST")
        expectancy = (
            (tp * target - sl * stop) / total
            if total
            else None
        )

        execution["close_entry"][f"stop_{stop:g}_atr"] = {
            "reward_atr": target,
            "risk_atr": stop,
            "breakeven_win_rate": stop / (stop + target),
            "tp_first_probability_all": tp / valid_n if valid_n else None,
            "sl_first_probability_all": sl / valid_n if valid_n else None,
            "ambiguous_probability": ambiguous / valid_n if valid_n else None,
            "no_touch_probability": no_touch / valid_n if valid_n else None,
            "tp_first_probability_resolved": tp / resolved_n if resolved_n else None,
            "resolved_sample_size": resolved_n,
            "gross_expectancy_atr_all": expectancy,
            "median_bars_to_result": (
                float(sample.loc[resolved_mask, f"bars_to_result_{suf}_{stop:g}"].median())
                if resolved_n
                else None
            ),
            "median_adverse_before_target_atr": (
                float(sample.loc[tp_mask, f"adverse_before_target_{suf}_{stop:g}"].median())
                if tp
                else None
            ),
        }

    for pullback in (0.25, 0.5):
        tag = f"{pullback:g}_0.75"
        fill_col = f"pb_filled_{suf}_{tag}"
        result_col = f"pb_result_{suf}_{tag}"

        filled = sample[fill_col].fillna(False).astype(bool)
        filled_values = sample.loc[filled, result_col]
        counts = filled_values.value_counts(dropna=False)

        tp = int(counts.get("TP_FIRST", 0))
        sl = int(counts.get("SL_FIRST", 0))
        ambiguous = int(counts.get("AMBIGUOUS", 0))
        no_exit = int(counts.get("FILLED_NO_EXIT", 0))
        filled_n = int(filled.sum())
        resolved_n = tp + sl
        stop = 0.75

        expectancy_filled = (
            (tp * target - sl * stop) / filled_n
            if filled_n
            else None
        )
        expectancy_all = (
            (tp * target - sl * stop) / total
            if total
            else None
        )

        execution["pullback_entries"][f"retrace_{pullback:g}_atr"] = {
            "reward_atr": target,
            "risk_atr": stop,
            "breakeven_win_rate": stop / (stop + target),
            "fill_probability": filled_n / total if total else None,
            "tp_first_probability_all_events": tp / total if total else None,
            "tp_first_probability_when_filled": tp / filled_n if filled_n else None,
            "tp_first_probability_resolved": tp / resolved_n if resolved_n else None,
            "sl_first_probability_when_filled": sl / filled_n if filled_n else None,
            "ambiguous_probability_when_filled": ambiguous / filled_n if filled_n else None,
            "filled_no_exit_probability_when_filled": no_exit / filled_n if filled_n else None,
            "resolved_sample_size": resolved_n,
            "gross_expectancy_atr_when_filled": expectancy_filled,
            "coverage_adjusted_expectancy_atr": expectancy_all,
            "median_bars_to_fill": (
                float(sample.loc[filled, f"pb_bars_to_fill_{suf}_{tag}"].median())
                if filled_n
                else None
            ),
        }

    return execution


def _decision_from_execution(
    execution_attempt: dict[str, Any],
    reliability: float,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    for variant, stats in execution_attempt.get("close_entry", {}).items():
        candidates.append({
            "mode": "MARKET",
            "variant": variant,
            "expectancy": stats.get("gross_expectancy_atr_all"),
            "coverage": 1.0,
            "resolved": int(stats.get("resolved_sample_size") or 0),
            "ambiguity": float(stats.get("ambiguous_probability") or 0.0),
            "risk_atr": stats.get("risk_atr"),
            "reward_atr": stats.get("reward_atr"),
        })

    for variant, stats in execution_attempt.get("pullback_entries", {}).items():
        mode = "LIMIT_0.25" if "0.25" in variant else "LIMIT_0.50"
        candidates.append({
            "mode": mode,
            "variant": variant,
            "expectancy": stats.get("coverage_adjusted_expectancy_atr"),
            "coverage": float(stats.get("fill_probability") or 0.0),
            "resolved": int(stats.get("resolved_sample_size") or 0),
            "ambiguity": float(stats.get("ambiguous_probability_when_filled") or 0.0),
            "risk_atr": stats.get("risk_atr"),
            "reward_atr": stats.get("reward_atr"),
        })

    usable = [c for c in candidates if c["expectancy"] is not None]
    best = max(usable, key=lambda c: float(c["expectancy"])) if usable else None

    if not best or float(best["expectancy"]) <= 0.0:
        return {
            "recommended_entry_mode": "NO_TRADE",
            "recommended_variant": None,
            "confidence_grade": "D",
            "gross_expectancy_atr": float(best["expectancy"]) if best else None,
            "coverage": float(best["coverage"]) if best else 0.0,
            "resolved_sample_size": int(best["resolved"]) if best else 0,
            "ambiguity": float(best["ambiguity"]) if best else None,
        }

    exp = float(best["expectancy"])
    resolved = int(best["resolved"])
    ambiguity = float(best["ambiguity"])

    if reliability >= 0.70 and resolved >= 100 and ambiguity <= 0.10 and exp >= 0.08:
        grade = "A"
    elif reliability >= 0.55 and resolved >= 60 and ambiguity <= 0.15 and exp >= 0.04:
        grade = "B"
    elif reliability >= 0.35 and resolved >= 25 and exp > 0:
        grade = "C"
    else:
        grade = "D"

    return {
        "recommended_entry_mode": best["mode"],
        "recommended_variant": best["variant"],
        "confidence_grade": grade,
        "gross_expectancy_atr": exp,
        "coverage": float(best["coverage"]),
        "resolved_sample_size": resolved,
        "ambiguity": ambiguity,
        "risk_atr": best["risk_atr"],
        "reward_atr": best["reward_atr"],
    }


def stat(
    g: pd.DataFrame,
    direction: str,
    target: float,
    include_execution: bool = True,
) -> dict[str, Any]:
    confirmed_col = "breakout_up" if direction == "UP" else "breakout_down"
    false_col = "false_breakout_up" if direction == "UP" else "false_breakout_down"
    suf = "up" if direction == "UP" else "down"

    confirmed_mask = g[confirmed_col].fillna(False).astype(bool)
    false_mask = g[false_col].fillna(False).astype(bool)
    attempt_mask = confirmed_mask | false_mask

    confirmed = g.loc[confirmed_mask]
    attempts = g.loc[attempt_mask]

    confirmed_count = int(confirmed_mask.sum())
    false_count = int(false_mask.sum())
    attempt_count = int(attempt_mask.sum())
    reliability_weight = attempt_count / (attempt_count + 100.0) if attempt_count else 0.0
    mae = confirmed[f"mae_{suf}"].dropna()

    result: dict[str, Any] = {
        "n": attempt_count,
        "confirmed": confirmed_count,
        "false": false_count,
        "reliability": reliability_weight,
        "confirmation_probability": confirmed_count / attempt_count if attempt_count else None,
        "false_breakout_probability": false_count / attempt_count if attempt_count else None,
        "continuation_probability": float(confirmed[f"ok_{suf}"].mean()) if not confirmed.empty else None,
        "clean_continuation_probability": float(confirmed[f"clean_{suf}"].mean()) if not confirmed.empty else None,
        "median_mfe_atr": float(confirmed[f"mfe_{suf}"].median()) if not confirmed.empty else None,
        "median_mae_atr": float(confirmed[f"mae_{suf}"].median()) if not confirmed.empty else None,
        "mae_quantiles_atr": {
            "p50": float(mae.quantile(.50)) if len(mae) else None,
            "p75": float(mae.quantile(.75)) if len(mae) else None,
            "p90": float(mae.quantile(.90)) if len(mae) else None,
        },
        "mae_exceedance_probability": {
            "gt_0.4": float((mae > .4).mean()) if len(mae) else None,
            "gt_0.5": float((mae > .5).mean()) if len(mae) else None,
            "gt_0.6": float((mae > .6).mean()) if len(mae) else None,
            "gt_0.75": float((mae > .75).mean()) if len(mae) else None,
            "gt_1.0": float((mae > 1.0).mean()) if len(mae) else None,
        },
        "median_volume_ratio": float(confirmed["vol_ratio"].median()) if not confirmed.empty else None,
        "median_range_atr": float(confirmed["range_atr"].median()) if not confirmed.empty else None,
    }

    if not include_execution:
        return result

    execution_attempt = _execution_view(attempts, suf, target)
    execution_confirmed = _execution_view(confirmed, suf, target)
    result["execution_given_attempt"] = execution_attempt
    result["execution_given_confirmed"] = execution_confirmed
    # Compatibility alias for older readers.
    result["execution"] = execution_confirmed
    result["decision"] = _decision_from_execution(execution_attempt, reliability_weight)
    return result


def key(direction: str, hour: Any="*", weekday: Any="*", month: Any="*", structure: Any="*", vol: Any="*", atr: Any="*") -> str:
    return "|".join(map(str, [direction, hour, weekday, month, structure, vol, atr]))


def regime_stat(g: pd.DataFrame) -> dict[str, Any]:
    size = int(len(g))
    return {
        "sample_size": size,
        "probabilities": {
            "breakout_up": float(g["breakout_up"].mean()) if size else None,
            "breakout_down": float(g["breakout_down"].mean()) if size else None,
            "false_breakout_up": float(g["false_breakout_up"].mean()) if size else None,
            "false_breakout_down": float(g["false_breakout_down"].mean()) if size else None,
            "compression": float(g["compression_flag"].mean()) if size else None,
            "no_event": float(
                (~(
                    g["breakout_up"]
                    | g["breakout_down"]
                    | g["false_breakout_up"]
                    | g["false_breakout_down"]
                    | g["compression_flag"]
                )).mean()
            ) if size else None,
        },
        "median_volume_ratio": float(g["vol_ratio"].median()) if size else None,
        "median_range_atr": float(g["range_atr"].median()) if size else None,
    }


def rkey(hour: Any="*", weekday: Any="*", month: Any="*", structure: Any="*", vol: Any="*", atr: Any="*") -> str:
    return "|".join(map(str, [hour, weekday, month, structure, vol, atr]))


def probability_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    fields = (
        "confirmation_probability",
        "false_breakout_probability",
        "continuation_probability",
        "clean_continuation_probability",
    )
    distances = []
    for field in fields:
        av = a.get(field)
        bv = b.get(field)
        if av is not None and bv is not None:
            distances.append(abs(float(av) - float(bv)))
    return max(distances, default=0.0)


def regime_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    ap = a.get("probabilities", {})
    bp = b.get("probabilities", {})
    fields = (
        "breakout_up",
        "breakout_down",
        "false_breakout_up",
        "false_breakout_down",
        "compression",
    )
    return max(
        (
            abs(float(ap.get(field, 0.0)) - float(bp.get(field, 0.0)))
            for field in fields
        ),
        default=0.0,
    )



def build_tf(
    path: Path,
    tf: str,
    target: float,
    min_sample: int,
    lower_chain: list[tuple[str, pd.DataFrame]] | None = None,
) -> dict[str, Any]:
    windows=HORIZON_WINDOWS.get(tf,{"fast":2,"base":3,"extended":6})
    raw=prepare(path)
    views={name:outcomes(raw,bars,target) for name,bars in windows.items()}
    df=views["base"]
    intrabar=_resolve_ambiguous_cascade(df,tf,lower_chain or [],windows["base"],target)

    groups={}; regimes={}
    min_hour=max(min_sample*2,60); min_weekday=max(min_sample*3,90)
    min_hour_weekday=max(min_sample*2,60); min_market_regime=max(min_sample*2,60); min_month=max(min_sample*4,120)
    distinct_months=int(df["event_time"].dt.to_period("M").nunique()); use_month=distinct_months>=6
    calendar_days=max(1,int((df["event_time"].max()-df["event_time"].min()).total_seconds()/86400)+1)
    if calendar_days >= 730: calendar_grade="STRONG_CALENDAR"
    elif calendar_days >= 240: calendar_grade="GOOD_CALENDAR"
    elif calendar_days >= 60: calendar_grade="MODERATE_CALENDAR"
    elif calendar_days >= 21: calendar_grade="SHORT_CALENDAR"
    else: calendar_grade="MICRO_SAMPLE"

    def enrich(profile_key, group, direction, base_stats):
        idx=group.index
        hv={}
        for name,vdf in views.items():
            hgroup=vdf.loc[vdf.index.intersection(idx)]
            hv[name]=stat(hgroup,direction,target,include_execution=True)
        base_stats["horizon_views"]={k:{
            "horizon_bars":windows[k],
            "decision":v.get("decision"),
            "continuation_probability":v.get("continuation_probability"),
            "clean_continuation_probability":v.get("clean_continuation_probability"),
            "execution_given_attempt":v.get("execution_given_attempt")
        } for k,v in hv.items()}
        base_stats["validation"]=_temporal_validation(group,direction,target,windows["base"])
        return base_stats

    for direction in ("UP","DOWN"):
        general=stat(df,direction,target); groups[key(direction)]=enrich(key(direction),df,direction,general)
        ordered_all=df.sort_values("event_time"); split_idx=int(len(ordered_all)*.60)
        train_all=ordered_all.iloc[:max(0,split_idx-windows["base"])]
        general_train=stat(train_all,direction,target,include_execution=False)
        def maybe_store(profile_key,group,minimum_attempts,minimum_confirmed,min_effect):
            ordered_group=group.sort_values("event_time"); gi=int(len(ordered_group)*.60)
            train_group=ordered_group.iloc[:max(0,gi-windows["base"])]
            basic=stat(train_group,direction,target,include_execution=False)
            train_min_attempts=max(20,int(minimum_attempts*.55)); train_min_confirmed=max(12,int(minimum_confirmed*.55))
            if int(basic.get("n") or 0)<train_min_attempts or int(basic.get("confirmed") or 0)<train_min_confirmed: return
            if probability_distance(basic,general_train)<min_effect: return
            groups[profile_key]=enrich(profile_key,group,direction,stat(group,direction,target,True))
        for hour,g in df.groupby("hour"): maybe_store(key(direction,int(hour)),g,min_hour,25,.02)
        for wd,g in df.groupby("weekday"): maybe_store(key(direction,weekday=wd),g,min_weekday,35,.02)
        if use_month:
            for mo,g in df.groupby("month"): maybe_store(key(direction,month=int(mo)),g,min_month,45,.03)
        for (hour,wd),g in df.groupby(["hour","weekday"]): maybe_store(key(direction,int(hour),wd),g,min_hour_weekday,25,.04)
        for (st,vol,atr),g in df.groupby(["structure","vol_bucket","atr_bucket"]):
            maybe_store(key(direction,structure=int(st),vol=vol,atr=atr),g,min_market_regime,25,.03)

    general_regime=regime_stat(df); regimes[rkey()]=general_regime
    def maybe_reg(k,g,n,effect):
        if len(g)<n:return
        c=regime_stat(g)
        if regime_distance(c,general_regime)>=effect: regimes[k]=c
    for hour,g in df.groupby("hour"): maybe_reg(rkey(int(hour)),g,150,.025)
    for wd,g in df.groupby("weekday"): maybe_reg(rkey(weekday=wd),g,300,.02)
    if use_month:
        for mo,g in df.groupby("month"): maybe_reg(rkey(month=int(mo)),g,500,.025)
    for (hour,wd),g in df.groupby(["hour","weekday"]): maybe_reg(rkey(int(hour),wd),g,150,.04)
    for (st,vol,atr),g in df.groupby(["structure","vol_bucket","atr_bucket"]): maybe_reg(rkey(structure=int(st),vol=vol,atr=atr),g,150,.03)

    mask=df["breakout_up"]|df["breakout_down"]; fmask=df["false_breakout_up"]|df["false_breakout_down"]
    return {"source_file":path.name,"start_time":df["event_time"].min(),"end_time":df["event_time"].max(),
            "bar_count":int(len(df)),"distinct_months":distinct_months,"calendar_days":calendar_days,"calendar_coverage_grade":calendar_grade,"horizon_windows":windows,
            "intrabar_resolution":intrabar,"breakout_rate":float(mask.mean()),"false_breakout_rate":float(fmask.mean()),
            "compression_rate":float(df["compression_flag"].mean()),"profile_counts":{"directional":len(groups),"regime":len(regimes)},
            "groups":groups,"regimes":regimes}


def build(symbol: str, input_dir: Path, output: Path, tfs: tuple[str,...], horizon: int, target: float, min_sample: int) -> dict[str, Any]:
    symbol=symbol.upper(); paths={tf:discover(input_dir,symbol,tf) for tf in tfs}; missing=[tf for tf,p in paths.items() if p is None]
    prepared={tf:prepare(p) for tf,p in paths.items() if p is not None}
    profiles={}
    for tf,p in paths.items():
        if p is None: continue
        order=list(DEFAULT_TFS); lower_chain=[]
        if tf in order:
            for lower_name in reversed(order[:order.index(tf)]):
                if lower_name in prepared: lower_chain.append((lower_name,prepared[lower_name]))
        profiles[tf]=build_tf(p,tf,target,min_sample,lower_chain)
    if not profiles: raise FileNotFoundError(f"Nenhum parquet de {symbol} encontrado em {input_dir}")
    profile={"profile_schema_version":SCHEMA_VERSION,"profile_type":"HISTORICAL_MARKET_INTELLIGENCE",
             "generated_at_utc":datetime.now(timezone.utc),"symbol":symbol,
             "settings":{"horizon_bars_by_timeframe":HORIZON_WINDOWS,"target_atr":target,"minimum_sample":min_sample,
                         "compact_profile":True,"multi_horizon":True,"intrabar_resolution_enabled":True,
                         "temporal_validation":"TRAIN_SELECTED_60_20_20_WITH_EMBARGO","formal_mtf_hierarchy":["H4","H1","M15","M5","M1"],
                         "h4_role":"REGIME_FILTER","m1_role":"INTRABAR_EXECUTION",
                         "execution_stops_atr":[.4,.5,.6,.75,1.0],"pullback_entries_atr":[.25,.5],"pullback_stop_atr":.75,
                         "same_bar_policy":"CASCADE_TO_M1_ELSE_AMBIGUOUS","prospective_execution_uses_all_attempts":True,
                         "decision_uses_coverage_adjusted_expectancy":True},
             "missing_timeframes":missing,"timeframes":profiles}
    save_json(output,profile); return profile

def get(d: dict[str, Any], *path: str, default: Any=None) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def current_context(tf: dict[str, Any]) -> dict[str, Any]:
    flags = get(tf, "algorithmic_annotations", "event_flags", default={}) or {}
    direction = "UP" if flags.get("breakout_up") or flags.get("false_breakout_up") else "DOWN" if flags.get("breakout_down") or flags.get("false_breakout_down") else None
    if direction is None:
        bd = get(tf, "algorithmic_annotations", "body_direction", default=0)
        direction = "UP" if bd == 1 else "DOWN" if bd == -1 else None
    t = pd.to_datetime(get(tf, "current_bar", "time_brt"), errors="coerce")
    vr = get(tf, "derived_metrics_exact", "volume_pace_ratio", default=get(tf, "derived_metrics_exact", "vol_ratio"))
    ra = get(tf, "derived_metrics_exact", "live_range_atr", default=get(tf, "derived_metrics_exact", "range_atr"))
    def vb(v: Any) -> str:
        try: v=float(v)
        except: return "UNKNOWN"
        return "LOW" if v<.8 else "NORMAL" if v<1 else "HIGH" if v<1.5 else "SPIKE"
    def ab(v: Any) -> str:
        try: v=float(v)
        except: return "UNKNOWN"
        return "LOW" if v<.6 else "NORMAL" if v<1 else "HIGH" if v<1.5 else "EXTREME"
    return {
        "direction": direction,
        "hour": "*" if pd.isna(t) else int(t.hour),
        "weekday": "*" if pd.isna(t) else t.day_name().upper(),
        "month": "*" if pd.isna(t) else int(t.month),
        "structure": get(tf, "algorithmic_annotations", "structure_state", default="*"),
        "vol_bucket": vb(vr), "atr_bucket": ab(ra), "volume_ratio": vr, "range_atr": ra,
    }


def candidates(c: dict[str, Any]) -> list[tuple[str, str]]:
    d,h,w,m,s,v,a = c["direction"],c["hour"],c["weekday"],c["month"],c["structure"],c["vol_bucket"],c["atr_bucket"]
    return [
        ("HOUR_WEEKDAY", key(d,h,w)),
        ("STRUCTURE_VOLUME_VOLATILITY", key(d,structure=s,vol=v,atr=a)),
        ("HOUR", key(d,h)),
        ("WEEKDAY", key(d,weekday=w)),
        ("MONTH", key(d,month=m)),
        ("GENERAL", key(d)),
    ]


def regime_candidates(c: dict[str, Any]) -> list[tuple[str, str]]:
    h,w,m,s,v,a = c["hour"],c["weekday"],c["month"],c["structure"],c["vol_bucket"],c["atr_bucket"]
    return [
        ("HOUR_WEEKDAY", rkey(h,w)),
        ("STRUCTURE_VOLUME_VOLATILITY", rkey(structure=s,vol=v,atr=a)),
        ("HOUR", rkey(h)),
        ("WEEKDAY", rkey(weekday=w)),
        ("MONTH", rkey(month=m)),
        ("GENERAL", rkey()),
    ]


def score(st: dict[str, Any], c: dict[str, Any]) -> int:
    p=float(st.get("continuation_probability") or 0)
    cp=float(st.get("clean_continuation_probability") or 0)
    fp=float(st.get("false_breakout_probability") or 0)
    conf=float(st.get("confirmation_probability") or 0)
    mfe=float(st.get("median_mfe_atr") or 0)
    mae=float(st.get("median_mae_atr") or 0)

    value = (
        p*35
        + cp*20
        + conf*15
        + max(0,1-fp)*10
        + min(max(mfe,0),2)*7.5
        + max(0,1-min(mae,1))*7.5
    )
    value += 5 if c["vol_bucket"]=="SPIKE" else -5 if c["vol_bucket"]=="LOW" else 0
    value -= 3 if c["atr_bucket"]=="EXTREME" else 0

    reliability = float(st.get("reliability") or 0)
    value = 50.0 + (value - 50.0) * reliability

    return int(round(max(0,min(100,value))))


def _evaluate_individual(payload: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    min_sample = int(get(profile, "settings", "minimum_sample", default=30))
    results = {}

    for tf, prof in profile.get("timeframes", {}).items():
        tfp = payload.get("timeframes", {}).get(tf)
        if not isinstance(tfp, dict):
            continue

        c = current_context(tfp)

        regime = None
        regime_key_used = None
        regime_level = None
        for level, rk in regime_candidates(c):
            candidate = prof.get("regimes", {}).get(rk)
            if isinstance(candidate, dict) and int(candidate.get("sample_size") or 0) >= min_sample:
                regime = candidate
                regime_key_used = rk
                regime_level = level
                break

        base = {
            "temporal_context": {
                "hour_brt": c["hour"],
                "weekday": c["weekday"],
                "month": c["month"],
            },
            "context": c,
            "regime_profile_level": regime_level,
            "regime_profile_key": regime_key_used,
            "regime_probabilities": regime.get("probabilities") if regime else None,
        }

        if c["direction"] not in {"UP","DOWN"}:
            base.update({
                "status":"NO_DIRECTIONAL_EVENT",
                "preferred_action":"WAIT",
            })
            results[tf] = base
            continue

        selected = None
        selected_key = None
        selected_level = None

        for level, k in candidates(c):
            st = prof.get("groups", {}).get(k)
            if isinstance(st, dict) and int(st.get("n") or 0) >= min_sample:
                selected = st
                selected_key = k
                selected_level = level
                break

        if selected is None:
            base.update({
                "status":"INSUFFICIENT_SAMPLE",
                "preferred_action":"WAIT",
            })
            results[tf] = base
            continue

        sc = score(selected,c)
        p = float(selected.get("continuation_probability") or 0)
        conf = float(selected.get("confirmation_probability") or 0)

        current_event = "BREAKOUT" if (
            get(tfp, "algorithmic_annotations", "event_flags", default={}).get("breakout_up")
            or get(tfp, "algorithmic_annotations", "event_flags", default={}).get("breakout_down")
        ) else "NO_CONFIRMED_BREAKOUT"

        action = (
            ("BUY_AFTER_CONFIRMATION" if c["direction"]=="UP" else "SELL_AFTER_CONFIRMATION")
            if current_event == "BREAKOUT" and sc>=70 and p>=.65 and conf>=.55
            else "WAIT"
        )

        base.update({
            "status":"OK",
            "matched_profile_level":selected_level,
            "matched_profile_key":selected_key,
            "score":sc,
            "attempt_sample_size":selected.get("n"),
            "confirmed_breakout_count":selected.get("confirmed"),
            "false_breakout_count":selected.get("false"),
            "confirmation_probability":selected.get("confirmation_probability"),
            "false_breakout_probability":selected.get("false_breakout_probability"),
            "continuation_probability":p,
            "clean_continuation_probability":selected.get("clean_continuation_probability"),
            "median_mfe_atr":selected.get("median_mfe_atr"),
            "median_mae_atr":selected.get("median_mae_atr"),
            "reliability":selected.get("reliability"),
            "validation":selected.get("validation"),
            "current_event":current_event,
            "execution_given_attempt":selected.get("execution_given_attempt"),
            "execution_given_confirmed":selected.get("execution_given_confirmed"),
            "quantitative_decision":selected.get("decision"),
            "preferred_action": (
                (
                    "BUY_" if c["direction"] == "UP" else "SELL_"
                ) + str(selected.get("decision", {}).get("recommended_entry_mode"))
                if selected.get("decision", {}).get("recommended_entry_mode") not in {None, "NO_TRADE"}
                else "WAIT"
            ),
        })
        results[tf] = base

    usable=[r for r in results.values() if r.get("status")=="OK"]
    dirs=[r["context"]["direction"] for r in usable]
    dominant = "UP" if dirs.count("UP")>dirs.count("DOWN") else "DOWN" if dirs else None
    aligned=[tf for tf,r in results.items() if r.get("status")=="OK" and r["context"]["direction"]==dominant]
    alignment = int(round(100*len(aligned)/len(usable))) if usable else 0
    actionable=[(tf,r) for tf,r in results.items() if r.get("preferred_action")!="WAIT"]
    best=max(actionable,key=lambda x:x[1].get("score",0)) if actionable else None

    out=dict(payload)
    out["historical_intelligence"]={
        "profile_schema_version": profile.get("profile_schema_version"),
        "profile_generated_at_utc": profile.get("generated_at_utc"),
        "evaluated_at_utc": datetime.now(timezone.utc),
        "preferred_action_now": best[1]["preferred_action"] if best else "WAIT",
        "best_timeframe": best[0] if best else None,
        "mtf_alignment": {
            "dominant_direction":dominant,
            "alignment_score":alignment,
            "aligned_timeframes":aligned
        },
        "timeframes":results,
        "limitations":[
            "Score não substitui fechamento, aceitação e reteste.",
            "Amostra insuficiente retorna WAIT.",
            "Horário, dia e mês usam fallback para o recorte com amostra suficiente."
        ],
    }
    return out


def evaluate(payload: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    out=_evaluate_individual(payload,profile)
    hi=out.get("historical_intelligence",{}); tfres=hi.get("timeframes",{})
    h4=tfres.get("H4",{}); h1=tfres.get("H1",{}); m15=tfres.get("M15",{}); m5=tfres.get("M5",{}); m1=tfres.get("M1",{})
    def direction(r): return get(r,"context","direction")
    h4d,h1d,m15d,m5d=map(direction,(h4,h1,m15,m5))
    setup=m15.get("quantitative_decision",{}) if m15.get("status")=="OK" else {}
    mode=setup.get("recommended_entry_mode","NO_TRADE")
    blocked=[]
    if mode=="NO_TRADE": blocked.append("M15_NO_POSITIVE_EXPECTANCY")
    if m15d and h1d and m15d!=h1d: blocked.append("H1_M15_DIRECTION_CONFLICT")
    trigger_confirmed=(
        m5.get("status")=="OK"
        and m5.get("current_event")=="BREAKOUT"
        and m5d is not None
        and m5d==m15d
    )
    h4_relation="NEUTRAL"
    if h4d and m15d: h4_relation="ALIGNED" if h4d==m15d else "COUNTERTREND_ALLOWED"
    score=0
    if h4_relation=="ALIGNED": score+=20
    elif h4_relation=="COUNTERTREND_ALLOWED": score+=8
    if h1d and m15d and h1d==m15d: score+=30
    if m15.get("status")=="OK": score+=35
    if trigger_confirmed: score+=15
    action="WAIT"
    if not blocked and trigger_confirmed and mode not in (None,"NO_TRADE"):
        action=("BUY_" if m15d=="UP" else "SELL_")+mode
    elif not blocked and mode not in (None,"NO_TRADE"):
        action="WAIT_M5_CONFIRMATION"
    hi["formal_mtf_decision"]={
        "h4_regime_role":"REGIME_FILTER","h4_direction":h4d,"h4_relation":h4_relation,
        "h1_tactical_bias":h1d,"m15_setup_direction":m15d,"m15_entry_mode":mode,
        "m5_trigger":"CONFIRMED" if trigger_confirmed else "NOT_CONFIRMED",
        "m1_role":"INTRABAR_RESOLUTION_ONLY","alignment_score":score,
        "trade_class":"TREND_ALIGNED" if h4_relation=="ALIGNED" else "H4_COUNTERTREND" if h4_relation=="COUNTERTREND_ALLOWED" else "UNCLASSIFIED",
        "blocked_reasons":blocked,"final_action":action,
    }
    hi["preferred_action_now"]=action
    def compact_tf(name: str, r: dict[str, Any]) -> dict[str, Any]:
        q=r.get("quantitative_decision",{}) or {}; v=r.get("validation",{}) or {}
        return {"role":{"H4":"REGIME","H1":"TACTICAL_BIAS","M15":"SETUP","M5":"TRIGGER","M1":"EXECUTION"}.get(name),
                "status":r.get("status"),"direction":get(r,"context","direction"),
                "profile_level":r.get("matched_profile_level"),"reliability":r.get("reliability"),
                "entry_mode":q.get("recommended_entry_mode"),"expectancy_atr":q.get("gross_expectancy_atr"),
                "confidence_grade":q.get("confidence_grade"),"coverage":q.get("coverage"),
                "ambiguity":q.get("ambiguity"),"calendar_coverage":get(profile,"timeframes",name,"calendar_coverage_grade"),
                "oos_pass":v.get("oos_pass")}
    hi["llm_quantitative_brief"]={
        "instruction":"Use como restrição quantitativa; não trate como garantia e não substitua gatilho técnico.",
        "priority":["M15_SETUP","H1_TACTICAL_BIAS","M5_TRIGGER","H4_REGIME","M1_EXECUTION"],
        "timeframes":{name:compact_tf(name,tfres.get(name,{})) for name in ("H4","H1","M15","M5","M1")},
        "formal_decision":hi["formal_mtf_decision"],
        "final_action":action,
    }
    out["historical_intelligence"]=hi
    return out

def parse_tfs(value: str) -> tuple[str,...]:
    return tuple(x.strip().upper() for x in value.split(",") if x.strip())


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Market Intelligence Engine")
    sub=p.add_subparsers(dest="cmd",required=True)
    b=sub.add_parser("build"); b.add_argument("--symbol",required=True); b.add_argument("--input-dir",type=Path,required=True); b.add_argument("--output",type=Path,required=True); b.add_argument("--timeframes",type=parse_tfs,default=DEFAULT_TFS); b.add_argument("--horizon-bars",type=int,default=3); b.add_argument("--target-atr",type=float,default=.5); b.add_argument("--minimum-sample",type=int,default=30)
    e=sub.add_parser("enrich"); e.add_argument("--profile",type=Path,required=True); e.add_argument("--payload",type=Path,required=True); e.add_argument("--output",type=Path,required=True)
    return p


def main() -> int:
    args=parser().parse_args()
    try:
        if args.cmd=="build":
            prof=build(args.symbol,args.input_dir,args.output,args.timeframes,args.horizon_bars,args.target_atr,args.minimum_sample)
            summary = {}
            for tf, tfp in prof["timeframes"].items():
                up = tfp["groups"].get(key("UP"), {})
                down = tfp["groups"].get(key("DOWN"), {})
                summary[tf] = {
                    "bars": tfp.get("bar_count"),
                    "breakout_rate": tfp.get("breakout_rate"),
                    "false_breakout_rate": tfp.get("false_breakout_rate"),
                    "compression_rate": tfp.get("compression_rate"),
                    "up_attempts": up.get("n"),
                    "up_confirmation_probability": up.get("confirmation_probability"),
                    "down_attempts": down.get("n"),
                    "down_confirmation_probability": down.get("confirmation_probability"),
                }
            print(json.dumps({
                "status":"ok",
                "schema_version":SCHEMA_VERSION,
                "symbol":prof["symbol"],
                "output":str(args.output),
                "timeframes":list(prof["timeframes"]),
                "summary":summary
            },ensure_ascii=False,indent=2))
        else:
            out=evaluate(load_json(args.payload),load_json(args.profile)); save_json(args.output,out)
            print(json.dumps({"status":"ok","output":str(args.output),"preferred_action_now":out["historical_intelligence"]["preferred_action_now"]},ensure_ascii=False,indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status":"error","error":str(exc)},ensure_ascii=False,indent=2),file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
