#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Chronos Engine — motor único de pesquisa estatística do GOLD.

Versão inicial consolidada:
- Lê a base MTF já criada pelo market_chronos_lab.py
- Calcula Behavior Map por horário
- Calcula DNA Rank
- Calcula Event Edges
- Calcula Context Scores por camadas
- Gera relatório, Excel e CSVs em uma pasta única

Uso:
  python tools/market_chronos_engine.py --symbol GOLD --anchor-tf M5

Entrada padrão:
  data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet

Saída:
  data/market_chronos/{symbol}/engine/

VALIDATION_MARKER: MARKET_CHRONOS_ENGINE_V2_LEVEL_PLAYBOOK
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

DEFAULT_INPUT = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/engine"


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{stamp()}] {msg}", flush=True)


def jclean(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): jclean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jclean(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return None if not math.isfinite(x) else round(x, 6)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(jclean(data), ensure_ascii=False, indent=2), encoding="utf-8")


def fcol(df: pd.DataFrame, col: str, default=np.nan) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    if isinstance(default, pd.Series):
        return pd.to_numeric(default, errors="coerce")
    return pd.Series(default, index=df.index, dtype=float)


def scol(df: pd.DataFrame, col: str, default="UNKNOWN") -> pd.Series:
    if col in df.columns:
        return df[col].astype("object").fillna(default).astype(str)
    return pd.Series(default, index=df.index, dtype=str)


def bcol(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    s = df[col]
    if pd.api.types.is_bool_dtype(s):
        return s.fillna(False)
    if pd.api.types.is_numeric_dtype(s):
        return s.fillna(0).astype(int).astype(bool)
    return s.astype(str).str.lower().isin({"1", "true", "yes", "sim"})


def pct_rank(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    if s.notna().sum() < 50:
        return pd.Series(0.5, index=s.index)
    return s.rank(pct=True).fillna(0.5)


def add_core_features(df: pd.DataFrame, anchor_tf: str) -> pd.DataFrame:
    out = df.copy()
    p = f"{anchor_tf}_"

    if "event_time" in out.columns:
        out["event_time"] = pd.to_datetime(out["event_time"], errors="coerce")
    else:
        raise ValueError("Coluna event_time ausente na base MTF.")

    if f"{p}hour_brt" not in out.columns:
        out[f"{p}hour_brt"] = out["event_time"].dt.hour
    if f"{p}time_slot" not in out.columns:
        out[f"{p}time_slot"] = out["event_time"].dt.strftime("%H:%M")

    close = fcol(out, f"{p}close")
    open_ = fcol(out, f"{p}open")
    high = fcol(out, f"{p}high")
    low = fcol(out, f"{p}low")
    atr = fcol(out, f"{p}ATR").replace(0, np.nan)

    out["hour"] = fcol(out, f"{p}hour_brt").fillna(-1).astype(int)
    out["time_slot"] = scol(out, f"{p}time_slot")
    out["anchor_direction"] = scol(out, f"{p}direction")
    out["anchor_range_usd"] = fcol(out, f"{p}range_usd", high - low)
    out["anchor_net_usd"] = fcol(out, f"{p}net_usd", close - open_)
    out["anchor_abs_net_usd"] = out["anchor_net_usd"].abs()
    out["anchor_atr"] = atr
    out["anchor_range_atr"] = fcol(out, f"{p}range_atr", out["anchor_range_usd"] / atr)
    out["anchor_body_atr"] = fcol(out, f"{p}body_atr", out["anchor_abs_net_usd"] / atr)
    out["anchor_vol_ratio"] = fcol(out, f"{p}vol_ratio")
    out["anchor_market_state"] = scol(out, f"{p}market_state")
    out["anchor_vol_bucket"] = scol(out, f"{p}vol_bucket")
    out["anchor_range_bucket"] = scol(out, f"{p}range_bucket")
    out["anchor_body_bucket"] = scol(out, f"{p}body_bucket")
    out["anchor_close_position_bucket"] = scol(out, f"{p}close_position_bucket")

    out["event_breakout_up"] = bcol(out, f"{p}breakout_up")
    out["event_breakout_down"] = bcol(out, f"{p}breakout_down")
    out["event_breakout"] = out["event_breakout_up"] | out["event_breakout_down"]
    out["event_false_breakout"] = bcol(out, f"{p}false_breakout_up") | bcol(out, f"{p}false_breakout_down")
    out["event_sweep"] = bcol(out, f"{p}sweep_high") | bcol(out, f"{p}sweep_low")
    out["event_compression"] = bcol(out, f"{p}compression_flag")
    out["event_expansion"] = bcol(out, f"{p}expansion_flag")

    score = np.zeros(len(out), dtype=float)
    count = np.zeros(len(out), dtype=float)
    for col in [f"{p}direction", "M15_direction", "H1_direction", "H4_direction"]:
        if col in out.columns:
            d = scol(out, col)
            val = np.select([d.eq("UP"), d.eq("DOWN")], [1, -1], default=0)
            score += val
            count += (val != 0).astype(float)

    out["mtf_alignment_score"] = score
    out["mtf_alignment_count"] = count
    out["mtf_alignment_abs"] = np.abs(score)
    out["mtf_bias"] = np.select([score > 0, score < 0], ["UP", "DOWN"], default="MIXED")
    out["mtf_alignment_bucket"] = pd.cut(
        out["mtf_alignment_abs"],
        [-np.inf, 0, 1, 2, 3, 4],
        labels=["NONE", "WEAK", "MIXED", "STRONG", "FULL"],
    ).astype("object").fillna("UNKNOWN").astype(str)

    adx = fcol(out, "H1_ADX", fcol(out, "M15_ADX", np.nan))
    out["energy_score"] = (
        100 * (
            0.30 * pct_rank(out["anchor_vol_ratio"].clip(0, 5))
            + 0.30 * pct_rank(out["anchor_range_atr"].clip(0, 5))
            + 0.20 * pct_rank(out["anchor_body_atr"].clip(0, 3))
            + 0.15 * pct_rank(adx.clip(0, 80))
            + 0.10 * out["event_expansion"].astype(float)
            + 0.05 * out["event_compression"].astype(float)
        )
    ).clip(0, 100)

    out["energy_bucket"] = pd.cut(
        out["energy_score"],
        [-np.inf, 20, 40, 60, 80, np.inf],
        labels=["VERY_LOW", "LOW", "MEDIUM", "HIGH", "EXTREME"],
    ).astype("object").fillna("UNKNOWN").astype(str)

    high_dists = []
    low_dists = []
    for c in (f"{p}dist_prev_high_atr", f"{p}dist_donchian_high20_atr", f"{p}dist_bb_high_atr"):
        if c in out.columns:
            high_dists.append(fcol(out, c).abs())
    for c in (f"{p}dist_prev_low_atr", f"{p}dist_donchian_low20_atr", f"{p}dist_bb_low_atr"):
        if c in out.columns:
            low_dists.append(fcol(out, c).abs())

    out["nearest_resistance_atr"] = pd.concat(high_dists, axis=1).min(axis=1) if high_dists else ((high - close).abs() / atr)
    out["nearest_support_atr"] = pd.concat(low_dists, axis=1).min(axis=1) if low_dists else ((close - low).abs() / atr)

    def dist_bucket(s: pd.Series) -> pd.Series:
        return pd.cut(
            s,
            [-np.inf, 0.15, 0.35, 0.75, 1.5, np.inf],
            labels=["TOUCHING", "VERY_NEAR", "NEAR", "FAR", "VERY_FAR"],
        ).astype("object").fillna("UNKNOWN").astype(str)

    out["resistance_bucket"] = dist_bucket(out["nearest_resistance_atr"])
    out["support_bucket"] = dist_bucket(out["nearest_support_atr"])

    out["event_name"] = np.select(
        [
            out["event_breakout"],
            out["event_false_breakout"],
            out["event_sweep"],
            out["event_compression"],
            out["event_expansion"],
        ],
        ["BREAKOUT", "FALSE_BREAK", "SWEEP", "COMPRESSION", "EXPANSION"],
        default="NONE",
    )

    return out


def future_matrix(values: np.ndarray, horizon: int) -> np.ndarray:
    n = len(values)
    arr = np.full((horizon, n), np.nan)
    for i in range(1, horizon + 1):
        arr[i - 1, : n - i] = values[i:]
    return arr


def add_future_outcomes(df: pd.DataFrame, anchor_tf: str, horizons: list[int]) -> pd.DataFrame:
    out = df.copy()
    p = f"{anchor_tf}_"

    close = fcol(out, f"{p}close").to_numpy(float)
    high = fcol(out, f"{p}high").to_numpy(float)
    low = fcol(out, f"{p}low").to_numpy(float)
    atr = out["anchor_atr"].replace(0, np.nan).to_numpy(float)
    direction = out["anchor_direction"].to_numpy(object)

    n = len(out)
    for h in horizons:
        f_close = np.full(n, np.nan)
        f_close[: n - h] = close[h:]
        ret = f_close - close

        highs = future_matrix(high, h)
        lows = future_matrix(low, h)

        with np.errstate(all="ignore"):
            max_high = np.nanmax(highs, axis=0)
            min_low = np.nanmin(lows, axis=0)

        fav_up = max_high - close
        adv_up = close - min_low
        fav_down = close - min_low
        adv_down = max_high - close

        fav = np.where(direction == "UP", fav_up, np.where(direction == "DOWN", fav_down, np.nan))
        adv = np.where(direction == "UP", adv_up, np.where(direction == "DOWN", adv_down, np.nan))

        out[f"h{h}_continues"] = np.where(direction == "UP", ret > 0, np.where(direction == "DOWN", ret < 0, False))
        out[f"h{h}_reverses"] = np.where(direction == "UP", ret < 0, np.where(direction == "DOWN", ret > 0, False))
        out[f"h{h}_fav_atr"] = fav / atr
        out[f"h{h}_adv_atr"] = adv / atr
        out[f"h{h}_pullback_0p25"] = (adv / atr) >= 0.25
        out[f"h{h}_pullback_0p50"] = (adv / atr) >= 0.50
        out[f"h{h}_reaches_0p50"] = (fav / atr) >= 0.50
        out[f"h{h}_reaches_1p00"] = (fav / atr) >= 1.00
        out[f"h{h}_reaches_1p50"] = (fav / atr) >= 1.50

    return out


def first_touch_rr(df: pd.DataFrame, anchor_tf: str, target_atr: float, stop_atr: float, horizon: int) -> pd.Series:
    p = f"{anchor_tf}_"
    close = fcol(df, f"{p}close").to_numpy(float)
    high = fcol(df, f"{p}high").to_numpy(float)
    low = fcol(df, f"{p}low").to_numpy(float)
    atr = df["anchor_atr"].replace(0, np.nan).to_numpy(float)
    direction = df["anchor_direction"].to_numpy(object)

    n = len(df)
    result = np.full(n, "INVALID", dtype=object)

    for i in range(n):
        if not np.isfinite(close[i]) or not np.isfinite(atr[i]) or direction[i] not in ("UP", "DOWN"):
            continue

        if direction[i] == "UP":
            tp = close[i] + target_atr * atr[i]
            sl = close[i] - stop_atr * atr[i]
        else:
            tp = close[i] - target_atr * atr[i]
            sl = close[i] + stop_atr * atr[i]

        result[i] = "NO_TOUCH"
        last = min(n, i + horizon + 1)

        for j in range(i + 1, last):
            if direction[i] == "UP":
                tp_hit = high[j] >= tp
                sl_hit = low[j] <= sl
            else:
                tp_hit = low[j] <= tp
                sl_hit = high[j] >= sl

            if tp_hit and sl_hit:
                result[i] = "AMBIGUOUS"
                break
            if tp_hit:
                result[i] = "TP_FIRST"
                break
            if sl_hit:
                result[i] = "SL_FIRST"
                break

    return pd.Series(result, index=df.index)


def add_rr_outcomes(df: pd.DataFrame, anchor_tf: str) -> pd.DataFrame:
    out = df.copy()
    combos = [(0.5, 0.25, 6), (1.0, 0.5, 12), (1.5, 0.75, 24), (2.0, 1.0, 24)]
    for target, stop, horizon in combos:
        suffix = f"t{str(target).replace('.', 'p')}_s{str(stop).replace('.', 'p')}_h{horizon}"
        out[f"rr_{suffix}"] = first_touch_rr(out, anchor_tf, target, stop, horizon)
    return out


def rr_stats(g: pd.DataFrame, col: str = "rr_t1p0_s0p5_h12") -> tuple[float, float, float, float]:
    if col not in g.columns:
        return np.nan, np.nan, np.nan, np.nan
    s = g[col].dropna()
    if s.empty:
        return np.nan, np.nan, np.nan, np.nan
    return s.eq("TP_FIRST").mean(), s.eq("SL_FIRST").mean(), s.eq("AMBIGUOUS").mean(), s.eq("NO_TOUCH").mean()


def make_behavior_guidance(row: dict[str, Any]) -> tuple[str, str]:
    notes, guidance = [], []

    if row["avg_energy"] >= 70 or row["avg_range_atr"] >= 1.15:
        notes.append("janela de expansão/movimento")
    if row["avg_vol_ratio"] >= 1.15:
        notes.append("volume acima da média")
    if row["pullback_0p50_h6"] >= 0.60:
        notes.append("alta devolução após impulso")
        guidance += ["evitar stop apertado", "evitar perseguir candle"]
    if row["breakout_pct"] >= 0.30:
        notes.append("rompimentos frequentes")
    if row["false_break_pct"] >= 0.25 or row["sweep_pct"] >= 0.25:
        notes.append("sweeps/falsos rompimentos relevantes")
        guidance.append("esperar aceitação")
    if row["reach_1atr_h12"] >= 0.75:
        notes.append("boa chance de deslocamento >=1 ATR")
    if row["continuation_h6"] >= 0.65:
        notes.append("continuação acima da média")
        guidance.append("preferir pullback a favor")
    if row["continuation_h6"] < 0.52 and row["pullback_0p50_h6"] >= 0.55:
        notes.append("continuação fraca com devolução")
        guidance.append("cuidado com entrada curta na direção do candle")

    return (
        "; ".join(dict.fromkeys(notes)) if notes else "comportamento misto/neutro",
        "; ".join(dict.fromkeys(guidance)) if guidance else "sem viés operacional forte",
    )


def summarize_behavior_map(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    rows = []
    for hour, g in df.groupby("hour", dropna=False):
        if hour < 0 or len(g) < min_bars:
            continue

        tp, sl, amb, nt = rr_stats(g)
        row = {
            "hour": int(hour),
            "bars": len(g),
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "avg_vol_ratio": g["anchor_vol_ratio"].mean(),
            "expansion_pct": g["event_expansion"].mean(),
            "breakout_pct": g["event_breakout"].mean(),
            "false_break_pct": g["event_false_breakout"].mean(),
            "sweep_pct": g["event_sweep"].mean(),
            "continuation_h3": g["h3_continues"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "continuation_h12": g["h12_continues"].mean(),
            "pullback_0p25_h6": g["h6_pullback_0p25"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_0p50_h12": g["h12_reaches_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
            "rr_tp": tp,
            "rr_sl": sl,
            "rr_edge": tp - sl if pd.notna(tp) and pd.notna(sl) else np.nan,
        }
        row["behavior_summary"], row["operational_guidance"] = make_behavior_guidance(row)
        rows.append(row)

    return pd.DataFrame(rows).sort_values(["avg_energy", "avg_range_atr"], ascending=[False, False])


def context_key(df: pd.DataFrame, level: int) -> pd.Series:
    key = "hour=" + df["hour"].astype(str)
    if level >= 2:
        key += "|state=" + df["anchor_market_state"]
    if level >= 3:
        key += "|energy=" + df["energy_bucket"]
    if level >= 4:
        key += "|vol=" + df["anchor_vol_bucket"]
    if level >= 5:
        key += "|align=" + df["mtf_alignment_bucket"] + "/" + df["mtf_bias"]
    if level >= 6:
        key += "|event=" + df["event_name"].astype(str)
    if level >= 7:
        key += "|res=" + df["resistance_bucket"] + "|sup=" + df["support_bucket"]
    return key


def summarize_context_scores(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    rows = []
    for level in range(1, 8):
        tmp = df.copy()
        tmp["context_key"] = context_key(tmp, level)

        for ctx, g in tmp.groupby("context_key", dropna=False):
            if len(g) < min_bars:
                continue

            tp, sl, amb, nt = rr_stats(g)
            rr_edge = tp - sl if pd.notna(tp) and pd.notna(sl) else 0.0
            row = {
                "layer": level,
                "context_key": ctx,
                "bars": len(g),
                "avg_energy": g["energy_score"].mean(),
                "avg_range_atr": g["anchor_range_atr"].mean(),
                "avg_vol_ratio": g["anchor_vol_ratio"].mean(),
                "continuation_h3": g["h3_continues"].mean(),
                "continuation_h6": g["h6_continues"].mean(),
                "continuation_h12": g["h12_continues"].mean(),
                "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
                "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
                "rr_tp": tp,
                "rr_sl": sl,
                "rr_ambiguous": amb,
                "rr_no_touch": nt,
                "rr_edge": rr_edge,
            }
            row["fusion_edge_score"] = (
                0.35 * rr_edge
                + 0.25 * row["reach_1atr_h12"]
                + 0.20 * row["continuation_h6"]
                - 0.20 * row["pullback_0p50_h6"]
            )
            rows.append(row)

    return pd.DataFrame(rows).sort_values(["fusion_edge_score", "bars"], ascending=[False, False])


def summarize_event_edges(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    rows = []
    group_cols = ["event_name", "hour", "anchor_market_state", "energy_bucket", "mtf_alignment_bucket", "mtf_bias"]

    for keys, g in df.groupby(group_cols, dropna=False):
        if len(g) < min_bars:
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)

        tp, sl, amb, nt = rr_stats(g)
        row = dict(zip(group_cols, keys))
        row.update({
            "bars": len(g),
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "continuation_h3": g["h3_continues"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
            "rr_tp": tp,
            "rr_sl": sl,
            "rr_edge": tp - sl if pd.notna(tp) and pd.notna(sl) else np.nan,
        })
        rows.append(row)

    return pd.DataFrame(rows).sort_values(["rr_edge", "reach_1atr_h12", "bars"], ascending=[False, False, False])


def summarize_dna_rank(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    tmp = df.copy()
    tmp["dna_key"] = (
        "hour=" + tmp["hour"].astype(str)
        + "|state=" + tmp["anchor_market_state"]
        + "|energy=" + tmp["energy_bucket"]
        + "|vol=" + tmp["anchor_vol_bucket"]
        + "|align=" + tmp["mtf_alignment_bucket"] + "/" + tmp["mtf_bias"]
        + "|event=" + tmp["event_name"].astype(str)
    )

    rows = []
    for dna, g in tmp.groupby("dna_key", dropna=False):
        if len(g) < min_bars:
            continue

        tp, sl, amb, nt = rr_stats(g)
        edge = tp - sl if pd.notna(tp) and pd.notna(sl) else 0.0
        row = {
            "dna_key": dna,
            "bars": len(g),
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "avg_vol_ratio": g["anchor_vol_ratio"].mean(),
            "continuation_h3": g["h3_continues"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
            "rr_tp": tp,
            "rr_sl": sl,
            "rr_edge": edge,
        }
        row["dna_score"] = (
            0.30 * edge
            + 0.25 * row["reach_1atr_h12"]
            + 0.20 * row["continuation_h6"]
            - 0.15 * row["pullback_0p50_h6"]
            + 0.10 * min(len(g) / 500, 1.0)
        )
        rows.append(row)

    return pd.DataFrame(rows).sort_values(["dna_score", "bars"], ascending=[False, False])



def first_touch_fixed_side(
    df: pd.DataFrame,
    anchor_tf: str,
    side: str,
    target_atr: float = 1.0,
    stop_atr: float = 0.5,
    horizon: int = 12,
) -> pd.Series:
    """
    Mede BUY ou SELL independente da cor do candle.
    Isso permite responder:
      - Na resistência, comprar rompimento ou vender rejeição?
      - No suporte, comprar defesa ou vender rompimento?
    """
    p = f"{anchor_tf}_"
    close = fcol(df, f"{p}close").to_numpy(float)
    high = fcol(df, f"{p}high").to_numpy(float)
    low = fcol(df, f"{p}low").to_numpy(float)
    atr = df["anchor_atr"].replace(0, np.nan).to_numpy(float)

    n = len(df)
    result = np.full(n, "INVALID", dtype=object)
    side = side.upper()

    for i in range(n):
        if not np.isfinite(close[i]) or not np.isfinite(atr[i]):
            continue

        if side == "BUY":
            tp = close[i] + target_atr * atr[i]
            sl = close[i] - stop_atr * atr[i]
        elif side == "SELL":
            tp = close[i] - target_atr * atr[i]
            sl = close[i] + stop_atr * atr[i]
        else:
            raise ValueError("side precisa ser BUY ou SELL")

        result[i] = "NO_TOUCH"
        last = min(n, i + horizon + 1)

        for j in range(i + 1, last):
            if side == "BUY":
                tp_hit = high[j] >= tp
                sl_hit = low[j] <= sl
            else:
                tp_hit = low[j] <= tp
                sl_hit = high[j] >= sl

            if tp_hit and sl_hit:
                result[i] = "AMBIGUOUS"
                break
            if tp_hit:
                result[i] = "TP_FIRST"
                break
            if sl_hit:
                result[i] = "SL_FIRST"
                break

    return pd.Series(result, index=df.index)


def add_level_side_outcomes(df: pd.DataFrame, anchor_tf: str) -> pd.DataFrame:
    out = df.copy()
    out["buy_t1p0_s0p5_h12"] = first_touch_fixed_side(out, anchor_tf, "BUY", 1.0, 0.5, 12)
    out["sell_t1p0_s0p5_h12"] = first_touch_fixed_side(out, anchor_tf, "SELL", 1.0, 0.5, 12)
    out["buy_t0p5_s0p25_h6"] = first_touch_fixed_side(out, anchor_tf, "BUY", 0.5, 0.25, 6)
    out["sell_t0p5_s0p25_h6"] = first_touch_fixed_side(out, anchor_tf, "SELL", 0.5, 0.25, 6)
    return out


def side_stats(g: pd.DataFrame, col: str) -> tuple[float, float, float, float, float]:
    if col not in g.columns:
        return np.nan, np.nan, np.nan, np.nan, np.nan
    s = g[col].dropna()
    if s.empty:
        return np.nan, np.nan, np.nan, np.nan, np.nan
    tp = s.eq("TP_FIRST").mean()
    sl = s.eq("SL_FIRST").mean()
    amb = s.eq("AMBIGUOUS").mean()
    nt = s.eq("NO_TOUCH").mean()
    edge = tp - sl
    return tp, sl, amb, nt, edge


def classify_level_question(zone: str, buy_edge: float, sell_edge: float, min_delta: float = 0.05) -> str:
    """
    Gera uma orientação descritiva.
    Não é sinal; é leitura estatística do contexto.
    """
    if pd.isna(buy_edge) or pd.isna(sell_edge):
        return "amostra insuficiente"

    delta = buy_edge - sell_edge

    if abs(delta) < min_delta:
        return "sem vantagem clara; esperar confirmação"

    if zone == "RESISTANCE":
        if delta > 0:
            return "rompimento favorece compra; esperar aceitação/reteste"
        return "rejeição favorece venda; evitar comprar topo esticado"

    if zone == "SUPPORT":
        if delta > 0:
            return "defesa do suporte favorece compra; evitar vender fundo esticado"
        return "rompimento favorece venda; esperar aceitação abaixo"

    return "sem leitura"


def summarize_level_playbook(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    """
    Responde perguntas:
      - Na resistência, estatisticamente é melhor comprar rompimento ou vender rejeição?
      - No suporte, estatisticamente é melhor comprar defesa ou vender rompimento?
    """
    rows = []

    level_defs = [
        ("RESISTANCE", df["resistance_bucket"].isin(["TOUCHING", "VERY_NEAR", "NEAR"])),
        ("SUPPORT", df["support_bucket"].isin(["TOUCHING", "VERY_NEAR", "NEAR"])),
    ]

    group_cols = ["hour", "anchor_market_state", "energy_bucket", "mtf_alignment_bucket", "mtf_bias", "event_name"]

    for zone, mask in level_defs:
        tmp = df.loc[mask].copy()
        if tmp.empty:
            continue

        for keys, g in tmp.groupby(group_cols, dropna=False):
            if len(g) < min_bars:
                continue

            if not isinstance(keys, tuple):
                keys = (keys,)

            buy_tp, buy_sl, buy_amb, buy_nt, buy_edge = side_stats(g, "buy_t1p0_s0p5_h12")
            sell_tp, sell_sl, sell_amb, sell_nt, sell_edge = side_stats(g, "sell_t1p0_s0p5_h12")
            buy_fast_tp, buy_fast_sl, _, _, buy_fast_edge = side_stats(g, "buy_t0p5_s0p25_h6")
            sell_fast_tp, sell_fast_sl, _, _, sell_fast_edge = side_stats(g, "sell_t0p5_s0p25_h6")

            row = dict(zip(group_cols, keys))
            row.update({
                "zone": zone,
                "bars": len(g),
                "avg_energy": g["energy_score"].mean(),
                "avg_range_atr": g["anchor_range_atr"].mean(),
                "avg_vol_ratio": g["anchor_vol_ratio"].mean(),
                "breakout_pct": g["event_breakout"].mean(),
                "false_break_pct": g["event_false_breakout"].mean(),
                "sweep_pct": g["event_sweep"].mean(),
                "buy_tp": buy_tp,
                "buy_sl": buy_sl,
                "buy_edge": buy_edge,
                "sell_tp": sell_tp,
                "sell_sl": sell_sl,
                "sell_edge": sell_edge,
                "buy_fast_tp": buy_fast_tp,
                "buy_fast_sl": buy_fast_sl,
                "buy_fast_edge": buy_fast_edge,
                "sell_fast_tp": sell_fast_tp,
                "sell_fast_sl": sell_fast_sl,
                "sell_fast_edge": sell_fast_edge,
            })

            row["best_side"] = "BUY" if buy_edge > sell_edge else "SELL"
            row["edge_delta_buy_minus_sell"] = buy_edge - sell_edge
            row["level_guidance"] = classify_level_question(zone, buy_edge, sell_edge)
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(
        ["edge_delta_buy_minus_sell", "bars"],
        ascending=[False, False],
    )


def summarize_level_playbook_best(levels: pd.DataFrame) -> pd.DataFrame:
    """
    Ordenação mais amigável: melhores compras e melhores vendas separados dentro da mesma tabela.
    """
    if levels.empty:
        return levels

    out = levels.copy()
    out["abs_edge_delta"] = out["edge_delta_buy_minus_sell"].abs()
    out["max_side_edge"] = out[["buy_edge", "sell_edge"]].max(axis=1)
    return out.sort_values(["max_side_edge", "abs_edge_delta", "bars"], ascending=[False, False, False])


def write_report(
    path: Path,
    symbol: str,
    anchor_tf: str,
    metadata: dict[str, Any],
    behavior: pd.DataFrame,
    dna: pd.DataFrame,
    contexts: pd.DataFrame,
    events: pd.DataFrame,
    level_playbook: pd.DataFrame,
) -> None:
    lines = [
        f"# Market Chronos Engine — {symbol}\n",
        "## Base\n",
        f"- Anchor TF: **{anchor_tf}**",
        f"- Linhas: **{metadata['rows']}**",
        f"- Input: `{metadata['input']}`\n",
        "## Leitura\n",
        "Este relatório organiza a pesquisa em: comportamento por horário → DNA → contexto → eventos.",
        "A ideia é mapear comportamento mesmo quando ainda não existe setup claro.\n",
    ]

    if not behavior.empty:
        lines += ["## Behavior Map — leitura por horário\n", behavior.to_markdown(index=False), ""]
    if not dna.empty:
        lines += ["## DNA Rank — padrões candidatos\n", dna.head(30).to_markdown(index=False), ""]
    if not contexts.empty:
        lines += ["## Context Scores — camadas\n", contexts.head(30).to_markdown(index=False), ""]
    if not events.empty:
        lines += ["## Event Edges\n", events.head(30).to_markdown(index=False), ""]

    if not level_playbook.empty:
        lines += ["## Level Playbook — suporte/resistência\n", level_playbook.head(30).to_markdown(index=False), ""]

    lines += [
        "## Como interpretar\n",
        "- `behavior_summary`: descreve o comportamento típico do horário.",
        "- `operational_guidance`: ajuda a evitar decisões ruins, como stop curto ou perseguir candle.",
        "- `dna_score`: ranking inicial de padrões para validação visual.",
        "- `rr_tp`: bateu +1 ATR antes de -0,5 ATR em até 12 candles M5.",
        "- `rr_edge`: diferença entre TP e SL; ainda não é lucro real.",
        "- `level_guidance`: leitura estatística para resistência/suporte: romper, rejeitar ou esperar confirmação.",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    root = Path.cwd()
    symbol = args.symbol.upper()
    anchor_tf = args.anchor_tf.upper()
    input_path = root / args.input.format(symbol=symbol, anchor_tf=anchor_tf)
    out_root = root / args.output.format(symbol=symbol)
    out_root.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"Base MTF não encontrada: {input_path}")

    log(f"Lendo: {input_path}")
    df = pd.read_parquet(input_path)
    log(f"Linhas: {len(df)}")

    df = add_core_features(df, anchor_tf)
    df = add_future_outcomes(df, anchor_tf, horizons=[1, 2, 3, 6, 12, 24])
    df = add_rr_outcomes(df, anchor_tf)
    df = add_level_side_outcomes(df, anchor_tf)

    behavior = summarize_behavior_map(df, min_bars=args.min_bars)
    dna = summarize_dna_rank(df, min_bars=args.min_bars)
    contexts = summarize_context_scores(df, min_bars=args.min_bars)
    events = summarize_event_edges(df, min_bars=args.min_bars)
    level_playbook = summarize_level_playbook(df, min_bars=args.min_bars)
    level_playbook_best = summarize_level_playbook_best(level_playbook)

    behavior.to_csv(out_root / "engine_behavior_map.csv", index=False, encoding="utf-8-sig")
    dna.to_csv(out_root / "engine_dna_rank.csv", index=False, encoding="utf-8-sig")
    contexts.to_csv(out_root / "engine_context_scores.csv", index=False, encoding="utf-8-sig")
    events.to_csv(out_root / "engine_event_edges.csv", index=False, encoding="utf-8-sig")
    level_playbook.to_csv(out_root / "engine_level_playbook.csv", index=False, encoding="utf-8-sig")
    level_playbook_best.to_csv(out_root / "engine_level_playbook_best.csv", index=False, encoding="utf-8-sig")

    detail_cols = [
        "event_time", "hour", "time_slot", "anchor_direction", "anchor_market_state", "anchor_vol_bucket",
        "energy_score", "energy_bucket", "mtf_alignment_score", "mtf_alignment_bucket", "mtf_bias",
        "event_name", "nearest_resistance_atr", "nearest_support_atr", "resistance_bucket", "support_bucket",
        "h3_continues", "h6_continues", "h12_continues", "h6_pullback_0p50", "h12_reaches_1p00",
        "rr_t1p0_s0p5_h12", "buy_t1p0_s0p5_h12", "sell_t1p0_s0p5_h12",
    ]
    detail_cols = [c for c in detail_cols if c in df.columns]
    detail_path = out_root / f"{symbol}_{anchor_tf}_engine_detail.parquet"
    df[detail_cols].to_parquet(detail_path, index=False)

    xlsx_path = out_root / f"{symbol}_market_chronos_engine.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        behavior.to_excel(writer, sheet_name="behavior_map", index=False)
        dna.to_excel(writer, sheet_name="dna_rank", index=False)
        contexts.to_excel(writer, sheet_name="context_scores", index=False)
        events.to_excel(writer, sheet_name="event_edges", index=False)
        level_playbook_best.to_excel(writer, sheet_name="level_playbook", index=False)

    metadata = {
        "script": "market_chronos_engine.py",
        "validation_marker": "MARKET_CHRONOS_ENGINE_V2_LEVEL_PLAYBOOK",
        "symbol": symbol,
        "anchor_tf": anchor_tf,
        "rows": len(df),
        "input": str(input_path),
        "output": str(out_root),
        "min_bars": args.min_bars,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    save_json(out_root / "metadata.json", metadata)
    write_report(out_root / "chronos_engine_report.md", symbol, anchor_tf, metadata, behavior, dna, contexts, events, level_playbook_best)

    log("OK")
    print(json.dumps(jclean({
        "output": str(out_root),
        "report": str(out_root / "chronos_engine_report.md"),
        "xlsx": str(xlsx_path),
        "detail": str(detail_path),
        "rows": len(df),
        "behavior_hours": len(behavior),
        "dna_patterns": len(dna),
        "contexts": len(contexts),
        "events": len(events),
        "level_playbook": len(level_playbook),
    }), ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Market Chronos Engine")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.add_argument("--input", default=DEFAULT_INPUT)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--min-bars", type=int, default=120)
    return p.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
