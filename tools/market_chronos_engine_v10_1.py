#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Chronos Engine — pesquisa, validação e segmentação temporal/HTF de Market Laws do GOLD.

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

VALIDATION_MARKER: MARKET_CHRONOS_ENGINE_V10_1_RUNTIME_HARDENING
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

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


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"JSON inválido: {path}")
    return data


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



def add_state_dna_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cria IDs de estado para mapear DNA estatístico do mercado.
    Não é sinal. É identificação de contexto repetitivo.
    """
    out = df.copy()

    out["range_dna_bucket"] = pd.cut(
        out["anchor_range_atr"],
        [-np.inf, 0.6, 1.0, 1.5, 2.0, np.inf],
        labels=["R_LOW", "R_NORMAL", "R_HIGH", "R_EXTREME", "R_CHAOS"],
    ).astype("object").fillna("R_UNKNOWN").astype(str)

    out["body_dna_bucket"] = pd.cut(
        out["anchor_body_atr"],
        [-np.inf, 0.25, 0.6, 1.0, 1.5, np.inf],
        labels=["B_TINY", "B_SMALL", "B_MEDIUM", "B_LARGE", "B_EXPLOSIVE"],
    ).astype("object").fillna("B_UNKNOWN").astype(str)

    out["level_zone"] = np.select(
        [
            out["resistance_bucket"].isin(["TOUCHING", "VERY_NEAR"]),
            out["support_bucket"].isin(["TOUCHING", "VERY_NEAR"]),
            out["resistance_bucket"].isin(["NEAR"]),
            out["support_bucket"].isin(["NEAR"]),
        ],
        ["AT_RESISTANCE", "AT_SUPPORT", "NEAR_RESISTANCE", "NEAR_SUPPORT"],
        default="NO_LEVEL_PRESSURE",
    )

    out["event_group"] = np.select(
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

    # DNA mais macro: bom para ter amostra.
    out["state_dna_macro"] = (
        "state=" + out["anchor_market_state"].astype(str)
        + "|energy=" + out["energy_bucket"].astype(str)
        + "|align=" + out["mtf_alignment_bucket"].astype(str) + "/" + out["mtf_bias"].astype(str)
        + "|level=" + out["level_zone"].astype(str)
        + "|event=" + out["event_group"].astype(str)
    )

    # DNA operacional: adiciona hora e volume.
    out["state_dna_operational"] = (
        "hour=" + out["hour"].astype(str)
        + "|state=" + out["anchor_market_state"].astype(str)
        + "|energy=" + out["energy_bucket"].astype(str)
        + "|vol=" + out["anchor_vol_bucket"].astype(str)
        + "|align=" + out["mtf_alignment_bucket"].astype(str) + "/" + out["mtf_bias"].astype(str)
        + "|level=" + out["level_zone"].astype(str)
        + "|event=" + out["event_group"].astype(str)
    )

    # DNA granular: pode ter menos amostra, mas é mais específico.
    out["state_dna_granular"] = (
        out["state_dna_operational"]
        + "|range=" + out["range_dna_bucket"].astype(str)
        + "|body=" + out["body_dna_bucket"].astype(str)
    )

    # IDs estáveis legíveis.
    out["state_id_macro"] = pd.util.hash_pandas_object(out["state_dna_macro"], index=False).astype("uint64").astype(str).str[-8:]
    out["state_id_operational"] = pd.util.hash_pandas_object(out["state_dna_operational"], index=False).astype("uint64").astype(str).str[-8:]
    out["state_id_granular"] = pd.util.hash_pandas_object(out["state_dna_granular"], index=False).astype("uint64").astype(str).str[-8:]

    return out


def summarize_state_dna(df: pd.DataFrame, key_col: str, min_bars: int) -> pd.DataFrame:
    """
    Ranking de DNA:
    - O que acontece quando o mercado fica nesse estado?
    - Continua?
    - Devolve?
    - Atinge 1 ATR?
    - BUY ou SELL tem melhor comportamento?
    """
    rows = []

    for dna, g in df.groupby(key_col, dropna=False):
        if len(g) < min_bars:
            continue

        tp, sl, amb, nt = rr_stats(g)
        buy_tp, buy_sl, buy_amb, buy_nt, buy_edge = side_stats(g, "buy_t1p0_s0p5_h12")
        sell_tp, sell_sl, sell_amb, sell_nt, sell_edge = side_stats(g, "sell_t1p0_s0p5_h12")

        buy_sell_delta = buy_edge - sell_edge if pd.notna(buy_edge) and pd.notna(sell_edge) else np.nan

        row = {
            "dna_type": key_col,
            "state_dna": dna,
            "bars": len(g),
            "first_seen": str(g["event_time"].min()) if "event_time" in g.columns else "",
            "last_seen": str(g["event_time"].max()) if "event_time" in g.columns else "",
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "avg_vol_ratio": g["anchor_vol_ratio"].mean(),
            "continuation_h3": g["h3_continues"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "continuation_h12": g["h12_continues"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_0p50_h12": g["h12_reaches_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
            "rr_tp": tp,
            "rr_sl": sl,
            "rr_edge": tp - sl if pd.notna(tp) and pd.notna(sl) else np.nan,
            "buy_tp": buy_tp,
            "buy_sl": buy_sl,
            "buy_edge": buy_edge,
            "sell_tp": sell_tp,
            "sell_sl": sell_sl,
            "sell_edge": sell_edge,
            "buy_minus_sell_edge": buy_sell_delta,
        }

        row["state_bias"] = np.select(
            [
                pd.notna(buy_sell_delta) and buy_sell_delta > 0.08,
                pd.notna(buy_sell_delta) and buy_sell_delta < -0.08,
            ],
            ["BUY_BIAS", "SELL_BIAS"],
            default="NEUTRAL_OR_CONFIRMATION",
        ).item()

        row["state_quality_score"] = (
            0.25 * max(row["buy_edge"], row["sell_edge"])
            + 0.20 * row["reach_1atr_h12"]
            + 0.15 * row["continuation_h6"]
            - 0.15 * row["pullback_0p50_h6"]
            + 0.15 * min(len(g) / 500.0, 1.0)
            + 0.10 * abs(row["buy_minus_sell_edge"] if pd.notna(row["buy_minus_sell_edge"]) else 0)
        )

        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(["state_quality_score", "bars"], ascending=[False, False])


def summarize_state_transitions_dna(df: pd.DataFrame, key_col: str, min_count: int = 30) -> pd.DataFrame:
    """
    Mede transição entre estados consecutivos.
    Ajuda a descobrir gramática:
      COMPRESSION -> SWEEP -> BREAKOUT -> PULLBACK
    """
    if key_col not in df.columns:
        return pd.DataFrame()

    tmp = df[["event_time", key_col, "anchor_market_state", "event_group", "energy_bucket"]].copy()
    tmp = tmp.sort_values("event_time")
    tmp["next_state"] = tmp[key_col].shift(-1)
    tmp["next_market_state"] = tmp["anchor_market_state"].shift(-1)
    tmp["next_event_group"] = tmp["event_group"].shift(-1)

    trans = (
        tmp.dropna(subset=[key_col, "next_state"])
        .groupby([key_col, "next_state", "anchor_market_state", "next_market_state", "event_group", "next_event_group"])
        .size()
        .reset_index(name="count")
    )

    if trans.empty:
        return trans

    trans["state_total"] = trans.groupby(key_col)["count"].transform("sum")
    trans["transition_pct"] = trans["count"] / trans["state_total"]
    trans = trans.loc[trans["count"] >= min_count].copy()
    return trans.sort_values(["transition_pct", "count"], ascending=[False, False])


def make_state_playbook_text(row: pd.Series) -> str:
    if row.get("state_bias") == "BUY_BIAS":
        return "viés comprador; priorizar compra após confirmação/pullback"
    if row.get("state_bias") == "SELL_BIAS":
        return "viés vendedor; priorizar venda após confirmação/pullback"
    if row.get("pullback_0p50_h6", 0) > 0.70:
        return "alta devolução; evitar perseguir candle e esperar reteste"
    if row.get("reach_1atr_h12", 0) > 0.75:
        return "bom deslocamento, mas exigir leitura de lado/aceitação"
    return "sem viés claro; usar como contexto, não como gatilho"


def summarize_state_playbook(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    macro = summarize_state_dna(df, "state_dna_macro", min_bars=min_bars)
    operational = summarize_state_dna(df, "state_dna_operational", min_bars=min_bars)

    combined = pd.concat([macro, operational], ignore_index=True) if not macro.empty or not operational.empty else pd.DataFrame()
    if combined.empty:
        return combined

    combined["state_playbook"] = combined.apply(make_state_playbook_text, axis=1)
    return combined.sort_values(["state_quality_score", "bars"], ascending=[False, False])



def add_setup_genome_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Setup Genome inicial.
    Contexto + localização + evento + lado provável.
    """
    out = df.copy()

    out["setup_side_context"] = np.select(
        [
            (out["mtf_bias"].eq("UP")) & (out["anchor_direction"].eq("UP")),
            (out["mtf_bias"].eq("DOWN")) & (out["anchor_direction"].eq("DOWN")),
            out["mtf_bias"].eq("UP"),
            out["mtf_bias"].eq("DOWN"),
        ],
        ["BUY_ALIGNED", "SELL_ALIGNED", "BUY_MTF_ONLY", "SELL_MTF_ONLY"],
        default="MIXED",
    )

    out["setup_location_context"] = np.select(
        [
            out["level_zone"].isin(["AT_RESISTANCE", "NEAR_RESISTANCE"]),
            out["level_zone"].isin(["AT_SUPPORT", "NEAR_SUPPORT"]),
        ],
        ["RESISTANCE_ZONE", "SUPPORT_ZONE"],
        default="MID_RANGE",
    )

    out["setup_event_context"] = np.select(
        [
            out["event_group"].eq("BREAKOUT") & out["setup_location_context"].eq("RESISTANCE_ZONE"),
            out["event_group"].eq("BREAKOUT") & out["setup_location_context"].eq("SUPPORT_ZONE"),
            out["event_group"].eq("FALSE_BREAK") & out["setup_location_context"].eq("RESISTANCE_ZONE"),
            out["event_group"].eq("FALSE_BREAK") & out["setup_location_context"].eq("SUPPORT_ZONE"),
            out["event_group"].eq("SWEEP"),
            out["event_group"].eq("COMPRESSION"),
            out["event_group"].eq("EXPANSION"),
        ],
        ["RESISTANCE_BREAKOUT", "SUPPORT_BREAKOUT", "RESISTANCE_FALSE_BREAK", "SUPPORT_FALSE_BREAK", "SWEEP", "COMPRESSION", "EXPANSION"],
        default="NO_EVENT",
    )

    out["setup_genome_macro"] = (
        "state=" + out["anchor_market_state"].astype(str)
        + "|setup=" + out["setup_event_context"].astype(str)
        + "|side=" + out["setup_side_context"].astype(str)
        + "|loc=" + out["setup_location_context"].astype(str)
        + "|energy=" + out["energy_bucket"].astype(str)
        + "|align=" + out["mtf_alignment_bucket"].astype(str) + "/" + out["mtf_bias"].astype(str)
    )

    out["setup_genome_time"] = (
        "hour=" + out["hour"].astype(str)
        + "|" + out["setup_genome_macro"]
        + "|vol=" + out["anchor_vol_bucket"].astype(str)
    )

    out["setup_genome_granular"] = (
        out["setup_genome_time"]
        + "|range=" + out["range_dna_bucket"].astype(str)
        + "|body=" + out["body_dna_bucket"].astype(str)
        + "|res=" + out["resistance_bucket"].astype(str)
        + "|sup=" + out["support_bucket"].astype(str)
    )

    out["setup_id_macro"] = pd.util.hash_pandas_object(out["setup_genome_macro"], index=False).astype("uint64").astype(str).str[-8:]
    out["setup_id_time"] = pd.util.hash_pandas_object(out["setup_genome_time"], index=False).astype("uint64").astype(str).str[-8:]
    out["setup_id_granular"] = pd.util.hash_pandas_object(out["setup_genome_granular"], index=False).astype("uint64").astype(str).str[-8:]

    return out


def make_setup_genome_guidance(row: dict[str, Any]) -> str:
    side = row.get("best_side", "WAIT")
    edge = row.get("best_edge", 0)
    pull = row.get("pullback_0p50_h6", 0)
    reach = row.get("reach_1atr_h12", 0)

    if edge > 0.15 and pull < 0.60:
        return f"{side}: genoma forte; aceitar somente com confirmação"
    if edge > 0.08 and reach > 0.70:
        return f"{side}: genoma promissor; preferir pullback/reteste"
    if reach > 0.80 and pull > 0.65:
        return f"{side}: anda muito, mas devolve; não perseguir candle"
    if edge < 0:
        return "sem edge direto; usar apenas como contexto"
    return "aguardar confirmação; genoma misto"


def summarize_setup_genome(df: pd.DataFrame, key_col: str, min_bars: int) -> pd.DataFrame:
    rows = []

    for setup, g in df.groupby(key_col, dropna=False):
        if len(g) < min_bars:
            continue

        buy_tp, buy_sl, _, _, buy_edge = side_stats(g, "buy_t1p0_s0p5_h12")
        sell_tp, sell_sl, _, _, sell_edge = side_stats(g, "sell_t1p0_s0p5_h12")
        buy_fast_tp, buy_fast_sl, _, _, buy_fast_edge = side_stats(g, "buy_t0p5_s0p25_h6")
        sell_fast_tp, sell_fast_sl, _, _, sell_fast_edge = side_stats(g, "sell_t0p5_s0p25_h6")

        best_side = "BUY" if buy_edge >= sell_edge else "SELL"
        best_edge = max(buy_edge, sell_edge)
        edge_gap = abs(buy_edge - sell_edge)

        row = {
            "genome_type": key_col,
            "setup_genome": setup,
            "bars": len(g),
            "first_seen": str(g["event_time"].min()) if "event_time" in g.columns else "",
            "last_seen": str(g["event_time"].max()) if "event_time" in g.columns else "",
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "avg_vol_ratio": g["anchor_vol_ratio"].mean(),
            "continuation_h3": g["h3_continues"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "continuation_h12": g["h12_continues"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_0p50_h12": g["h12_reaches_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
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
            "best_side": best_side,
            "best_edge": best_edge,
            "edge_gap": edge_gap,
        }

        row["genome_score"] = (
            0.35 * max(best_edge, 0)
            + 0.20 * edge_gap
            + 0.20 * row["reach_1atr_h12"]
            + 0.10 * row["continuation_h6"]
            - 0.15 * row["pullback_0p50_h6"]
            + 0.10 * min(len(g) / 500.0, 1.0)
        )
        row["genome_guidance"] = make_setup_genome_guidance(row)
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(["genome_score", "bars"], ascending=[False, False])


def summarize_setup_genome_playbook(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    macro = summarize_setup_genome(df, "setup_genome_macro", min_bars=min_bars)
    time = summarize_setup_genome(df, "setup_genome_time", min_bars=min_bars)
    granular = summarize_setup_genome(df, "setup_genome_granular", min_bars=max(min_bars, 150))
    parts = [x for x in [macro, time, granular] if not x.empty]
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True).sort_values(["genome_score", "bars"], ascending=[False, False])



def add_htf_location_features(df: pd.DataFrame, anchor_tf: str) -> pd.DataFrame:
    """
    HTF Location DNA.
    Mede onde o candle M5 está em relação a estruturas de TFs maiores:
      - máxima/mínima anterior do próprio anchor
      - high/low/close de H1/H4/D1 quando existirem na base
      - distância normalizada por ATR
      - se o breakout M5 está alinhado com a pressão de localização maior
    """
    out = df.copy()
    p = f"{anchor_tf}_"
    close = fcol(out, f"{p}close")
    atr = out["anchor_atr"].replace(0, np.nan)

    # Fallbacks usando níveis já existentes no anchor.
    anchor_prev_high_dist = fcol(out, f"{p}dist_prev_high_atr")
    anchor_prev_low_dist = fcol(out, f"{p}dist_prev_low_atr")

    out["anchor_prev_high_zone"] = pd.cut(
        anchor_prev_high_dist,
        [-np.inf, -0.05, 0.15, 0.50, 1.50, np.inf],
        labels=["ABOVE_PREV_HIGH", "TESTING_PREV_HIGH", "NEAR_PREV_HIGH", "MID_FROM_PREV_HIGH", "FAR_FROM_PREV_HIGH"],
    ).astype("object").fillna("UNKNOWN").astype(str)

    out["anchor_prev_low_zone"] = pd.cut(
        anchor_prev_low_dist,
        [-np.inf, -0.05, 0.15, 0.50, 1.50, np.inf],
        labels=["BELOW_PREV_LOW", "TESTING_PREV_LOW", "NEAR_PREV_LOW", "MID_FROM_PREV_LOW", "FAR_FROM_PREV_LOW"],
    ).astype("object").fillna("UNKNOWN").astype(str)

    # Cria localização para TFs maiores quando as colunas existirem.
    for tf in ["M15", "H1", "H4", "D1", "W1"]:
        high_col = f"{tf}_high"
        low_col = f"{tf}_low"
        close_col = f"{tf}_close"
        atr_col = f"{tf}_ATR"

        if high_col in out.columns and low_col in out.columns:
            tf_high = fcol(out, high_col)
            tf_low = fcol(out, low_col)
            tf_close = fcol(out, close_col, close)
            tf_atr = fcol(out, atr_col, atr).replace(0, np.nan)

            out[f"dist_{tf}_high_atr"] = (tf_high - close) / atr
            out[f"dist_{tf}_low_atr"] = (close - tf_low) / atr
            out[f"pos_in_{tf}_range"] = ((close - tf_low) / (tf_high - tf_low).replace(0, np.nan)).clip(-2, 3)

            out[f"{tf}_range_location"] = pd.cut(
                out[f"pos_in_{tf}_range"],
                [-np.inf, -0.05, 0.20, 0.45, 0.55, 0.80, 1.05, np.inf],
                labels=[
                    f"BELOW_{tf}_LOW",
                    f"LOWER_{tf}_RANGE",
                    f"LOW_MID_{tf}",
                    f"MID_{tf}",
                    f"HIGH_MID_{tf}",
                    f"UPPER_{tf}_RANGE",
                    f"ABOVE_{tf}_HIGH",
                ],
            ).astype("object").fillna(f"UNKNOWN_{tf}").astype(str)

            out[f"{tf}_near_high"] = out[f"dist_{tf}_high_atr"].between(-0.05, 0.35)
            out[f"{tf}_near_low"] = out[f"dist_{tf}_low_atr"].between(-0.05, 0.35)
            out[f"{tf}_above_high"] = out[f"dist_{tf}_high_atr"] < -0.05
            out[f"{tf}_below_low"] = out[f"dist_{tf}_low_atr"] < -0.05
        else:
            out[f"{tf}_range_location"] = f"NO_{tf}_DATA"
            out[f"{tf}_near_high"] = False
            out[f"{tf}_near_low"] = False
            out[f"{tf}_above_high"] = False
            out[f"{tf}_below_low"] = False

    # Pressão HTF simples baseada em localização H1/H4/D1 disponíveis.
    up_pressure = np.zeros(len(out), dtype=float)
    down_pressure = np.zeros(len(out), dtype=float)

    for tf in ["H1", "H4", "D1", "W1"]:
        if f"{tf}_range_location" in out.columns:
            loc = out[f"{tf}_range_location"].astype(str)
            up_pressure += loc.str.contains("ABOVE|UPPER|HIGH_MID", regex=True).astype(float)
            down_pressure += loc.str.contains("BELOW|LOWER|LOW_MID", regex=True).astype(float)

        if f"{tf}_direction" in out.columns:
            d = scol(out, f"{tf}_direction")
            up_pressure += d.eq("UP").astype(float)
            down_pressure += d.eq("DOWN").astype(float)

    out["htf_location_up_pressure"] = up_pressure
    out["htf_location_down_pressure"] = down_pressure
    out["htf_location_bias_score"] = up_pressure - down_pressure

    out["htf_location_bias"] = np.select(
        [
            out["htf_location_bias_score"] >= 3,
            out["htf_location_bias_score"] <= -3,
            out["htf_location_bias_score"] > 0,
            out["htf_location_bias_score"] < 0,
        ],
        ["STRONG_UP_LOCATION", "STRONG_DOWN_LOCATION", "UP_LOCATION", "DOWN_LOCATION"],
        default="MIXED_LOCATION",
    )

    # Confluência entre evento M5 e localização maior.
    out["breakout_location_alignment"] = np.select(
        [
            out["event_breakout_up"] & out["htf_location_bias"].isin(["UP_LOCATION", "STRONG_UP_LOCATION"]),
            out["event_breakout_down"] & out["htf_location_bias"].isin(["DOWN_LOCATION", "STRONG_DOWN_LOCATION"]),
            out["event_breakout_up"] & out["htf_location_bias"].isin(["DOWN_LOCATION", "STRONG_DOWN_LOCATION"]),
            out["event_breakout_down"] & out["htf_location_bias"].isin(["UP_LOCATION", "STRONG_UP_LOCATION"]),
            out["event_breakout"],
        ],
        ["BREAKOUT_WITH_HTF_UP", "BREAKOUT_WITH_HTF_DOWN", "BREAKOUT_AGAINST_HTF_DOWN", "BREAKOUT_AGAINST_HTF_UP", "BREAKOUT_MIXED_HTF"],
        default="NO_BREAKOUT",
    )

    out["htf_location_dna"] = (
        "htf_bias=" + out["htf_location_bias"].astype(str)
        + "|H1=" + out.get("H1_range_location", pd.Series("NO_H1_DATA", index=out.index)).astype(str)
        + "|H4=" + out.get("H4_range_location", pd.Series("NO_H4_DATA", index=out.index)).astype(str)
        + "|D1=" + out.get("D1_range_location", pd.Series("NO_D1_DATA", index=out.index)).astype(str)
        + "|bo_align=" + out["breakout_location_alignment"].astype(str)
    )

    out["htf_setup_genome"] = (
        out["setup_genome_macro"].astype(str)
        + "|htf=" + out["htf_location_bias"].astype(str)
        + "|bo_htf=" + out["breakout_location_alignment"].astype(str)
    )

    out["htf_setup_genome_time"] = (
        "hour=" + out["hour"].astype(str)
        + "|" + out["htf_setup_genome"].astype(str)
    )

    return out


def summarize_htf_location_dna(df: pd.DataFrame, key_col: str, min_bars: int) -> pd.DataFrame:
    rows = []

    for key, g in df.groupby(key_col, dropna=False):
        if len(g) < min_bars:
            continue

        buy_tp, buy_sl, _, _, buy_edge = side_stats(g, "buy_t1p0_s0p5_h12")
        sell_tp, sell_sl, _, _, sell_edge = side_stats(g, "sell_t1p0_s0p5_h12")
        tp, sl, amb, nt = rr_stats(g)

        best_side = "BUY" if buy_edge >= sell_edge else "SELL"
        best_edge = max(buy_edge, sell_edge)

        row = {
            "dna_type": key_col,
            "htf_dna": key,
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
            "rr_edge": tp - sl if pd.notna(tp) and pd.notna(sl) else np.nan,
            "buy_tp": buy_tp,
            "buy_sl": buy_sl,
            "buy_edge": buy_edge,
            "sell_tp": sell_tp,
            "sell_sl": sell_sl,
            "sell_edge": sell_edge,
            "best_side": best_side,
            "best_edge": best_edge,
            "edge_gap": abs(buy_edge - sell_edge),
        }

        row["htf_score"] = (
            0.35 * max(best_edge, 0)
            + 0.20 * row["edge_gap"]
            + 0.20 * row["reach_1atr_h12"]
            + 0.10 * row["continuation_h6"]
            - 0.15 * row["pullback_0p50_h6"]
            + 0.10 * min(len(g) / 500.0, 1.0)
        )

        row["htf_guidance"] = make_htf_guidance(row)
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(["htf_score", "bars"], ascending=[False, False])


def make_htf_guidance(row: dict[str, Any]) -> str:
    side = row.get("best_side", "WAIT")
    best_edge = row.get("best_edge", 0)
    gap = row.get("edge_gap", 0)
    pull = row.get("pullback_0p50_h6", 0)

    if best_edge > 0.15 and gap > 0.30:
        return f"{side}: localização HTF favorece o lado; buscar confirmação"
    if best_edge > 0.08 and pull < 0.60:
        return f"{side}: confluência HTF moderada; entrada com reteste"
    if pull > 0.70:
        return f"{side}: HTF permite movimento, mas devolução alta; evitar entrada esticada"
    return "sem confluência HTF suficiente; usar como contexto"


def summarize_htf_breakout_alignment(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    group_cols = ["breakout_location_alignment", "htf_location_bias", "anchor_market_state", "energy_bucket", "mtf_alignment_bucket", "mtf_bias"]
    rows = []

    for keys, g in df.groupby(group_cols, dropna=False):
        if len(g) < min_bars:
            continue

        if not isinstance(keys, tuple):
            keys = (keys,)

        buy_tp, buy_sl, _, _, buy_edge = side_stats(g, "buy_t1p0_s0p5_h12")
        sell_tp, sell_sl, _, _, sell_edge = side_stats(g, "sell_t1p0_s0p5_h12")

        row = dict(zip(group_cols, keys))
        row.update({
            "bars": len(g),
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
            "buy_edge": buy_edge,
            "sell_edge": sell_edge,
            "best_side": "BUY" if buy_edge >= sell_edge else "SELL",
            "best_edge": max(buy_edge, sell_edge),
            "edge_gap": abs(buy_edge - sell_edge),
        })
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(["best_edge", "edge_gap", "bars"], ascending=[False, False, False])



def add_sequence_dna_features(df: pd.DataFrame, anchor_tf: str) -> pd.DataFrame:
    """
    Sequence DNA.
    Mede como o mercado chegou no estado atual:
      - sequência de direção dos últimos candles
      - sequência de eventos
      - compressão/expansão recente
      - streak direcional
      - primeira/segunda tentativa de rompimento
    """
    out = df.copy()
    out = out.sort_values("event_time").reset_index(drop=True)

    direction_map = {
        "UP": "U",
        "DOWN": "D",
        "FLAT": "F",
        "MIXED": "M",
        "UNKNOWN": "N",
    }

    event_map = {
        "BREAKOUT": "BO",
        "FALSE_BREAK": "FB",
        "SWEEP": "SW",
        "COMPRESSION": "CP",
        "EXPANSION": "EX",
        "NONE": "NO",
    }

    out["seq_dir_symbol"] = out["anchor_direction"].map(direction_map).fillna("N")
    out["seq_event_symbol"] = out["event_group"].map(event_map).fillna("NO")

    # Sequências curtas, médias e longas.
    for n in [3, 5, 8]:
        out[f"dir_seq_{n}"] = rolling_join(out["seq_dir_symbol"], n)
        out[f"event_seq_{n}"] = rolling_join(out["seq_event_symbol"], n)

        out[f"up_count_{n}"] = out["anchor_direction"].eq("UP").rolling(n, min_periods=n).sum()
        out[f"down_count_{n}"] = out["anchor_direction"].eq("DOWN").rolling(n, min_periods=n).sum()
        out[f"compression_count_{n}"] = out["event_compression"].astype(int).rolling(n, min_periods=n).sum()
        out[f"expansion_count_{n}"] = out["event_expansion"].astype(int).rolling(n, min_periods=n).sum()
        out[f"breakout_count_{n}"] = out["event_breakout"].astype(int).rolling(n, min_periods=n).sum()
        out[f"false_break_count_{n}"] = out["event_false_breakout"].astype(int).rolling(n, min_periods=n).sum()
        out[f"sweep_count_{n}"] = out["event_sweep"].astype(int).rolling(n, min_periods=n).sum()

    out["dir_streak"] = directional_streak(out["anchor_direction"])
    out["range_sum_5_atr"] = out["anchor_range_atr"].rolling(5, min_periods=5).sum()
    out["range_sum_8_atr"] = out["anchor_range_atr"].rolling(8, min_periods=8).sum()
    out["energy_mean_5"] = out["energy_score"].rolling(5, min_periods=5).mean()
    out["energy_mean_8"] = out["energy_score"].rolling(8, min_periods=8).mean()

    out["sequence_regime"] = np.select(
        [
            out["compression_count_5"].ge(3) & out["event_breakout"],
            out["compression_count_8"].ge(5) & out["event_breakout"],
            out["expansion_count_5"].ge(3) & out["event_breakout"],
            out["sweep_count_5"].ge(1) & out["event_breakout"],
            out["false_break_count_5"].ge(1) & out["event_breakout"],
            out["dir_streak"].ge(4),
            out["dir_streak"].le(-4),
            out["compression_count_5"].ge(3),
            out["expansion_count_5"].ge(3),
        ],
        [
            "BREAKOUT_AFTER_COMPRESSION",
            "BREAKOUT_AFTER_LONG_COMPRESSION",
            "BREAKOUT_AFTER_EXPANSION_CHAIN",
            "BREAKOUT_AFTER_SWEEP",
            "BREAKOUT_AFTER_FALSE_BREAK",
            "UP_STREAK_EXTENDED",
            "DOWN_STREAK_EXTENDED",
            "COMPRESSION_BUILDUP",
            "EXPANSION_CHAIN",
        ],
        default="NORMAL_SEQUENCE",
    )

    # Tentativas de rompimento em janela recente.
    out["breakout_attempt_lookback_12"] = out["event_breakout"].astype(int).rolling(12, min_periods=1).sum()
    out["false_break_recent_12"] = out["event_false_breakout"].astype(int).rolling(12, min_periods=1).sum()
    out["sweep_recent_12"] = out["event_sweep"].astype(int).rolling(12, min_periods=1).sum()

    out["breakout_attempt_bucket"] = pd.cut(
        out["breakout_attempt_lookback_12"],
        [-np.inf, 0, 1, 2, 4, np.inf],
        labels=["NO_RECENT_BO", "FIRST_BO", "SECOND_BO", "MULTI_BO", "BO_CLUSTER"],
    ).astype("object").fillna("UNKNOWN").astype(str)

    out["sequence_dna_macro"] = (
        "regime=" + out["sequence_regime"].astype(str)
        + "|event=" + out["event_group"].astype(str)
        + "|state=" + out["anchor_market_state"].astype(str)
        + "|align=" + out["mtf_alignment_bucket"].astype(str) + "/" + out["mtf_bias"].astype(str)
        + "|htf=" + out["htf_location_bias"].astype(str)
    )

    out["sequence_dna_setup"] = (
        out["setup_genome_macro"].astype(str)
        + "|seq=" + out["sequence_regime"].astype(str)
        + "|attempt=" + out["breakout_attempt_bucket"].astype(str)
    )

    out["sequence_dna_time"] = (
        "hour=" + out["hour"].astype(str)
        + "|" + out["sequence_dna_setup"].astype(str)
    )

    out["sequence_id_macro"] = pd.util.hash_pandas_object(out["sequence_dna_macro"], index=False).astype("uint64").astype(str).str[-8:]
    out["sequence_id_setup"] = pd.util.hash_pandas_object(out["sequence_dna_setup"], index=False).astype("uint64").astype(str).str[-8:]
    out["sequence_id_time"] = pd.util.hash_pandas_object(out["sequence_dna_time"], index=False).astype("uint64").astype(str).str[-8:]

    return out


def rolling_join(s: pd.Series, n: int) -> pd.Series:
    vals = s.astype(str).to_numpy()
    out = []
    for i in range(len(vals)):
        if i < n - 1:
            out.append("NA")
        else:
            out.append("-".join(vals[i - n + 1 : i + 1]))
    return pd.Series(out, index=s.index)


def directional_streak(direction: pd.Series) -> pd.Series:
    """
    UP streak positivo, DOWN streak negativo.
    """
    result = []
    current = 0
    last = None

    for x in direction.astype(str):
        if x == "UP":
            if last == "UP":
                current += 1
            else:
                current = 1
            last = "UP"
        elif x == "DOWN":
            if last == "DOWN":
                current -= 1
            else:
                current = -1
            last = "DOWN"
        else:
            current = 0
            last = x
        result.append(current)

    return pd.Series(result, index=direction.index)


def summarize_sequence_dna(df: pd.DataFrame, key_col: str, min_bars: int) -> pd.DataFrame:
    rows = []

    for key, g in df.groupby(key_col, dropna=False):
        if len(g) < min_bars:
            continue

        buy_tp, buy_sl, _, _, buy_edge = side_stats(g, "buy_t1p0_s0p5_h12")
        sell_tp, sell_sl, _, _, sell_edge = side_stats(g, "sell_t1p0_s0p5_h12")
        tp, sl, amb, nt = rr_stats(g)

        best_side = "BUY" if buy_edge >= sell_edge else "SELL"
        best_edge = max(buy_edge, sell_edge)

        row = {
            "dna_type": key_col,
            "sequence_dna": key,
            "bars": len(g),
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "avg_vol_ratio": g["anchor_vol_ratio"].mean(),
            "avg_dir_streak": g["dir_streak"].mean(),
            "avg_range_sum_5_atr": g["range_sum_5_atr"].mean(),
            "avg_energy_mean_5": g["energy_mean_5"].mean(),
            "continuation_h3": g["h3_continues"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
            "rr_tp": tp,
            "rr_sl": sl,
            "rr_edge": tp - sl if pd.notna(tp) and pd.notna(sl) else np.nan,
            "buy_tp": buy_tp,
            "buy_sl": buy_sl,
            "buy_edge": buy_edge,
            "sell_tp": sell_tp,
            "sell_sl": sell_sl,
            "sell_edge": sell_edge,
            "best_side": best_side,
            "best_edge": best_edge,
            "edge_gap": abs(buy_edge - sell_edge),
        }

        row["sequence_score"] = (
            0.35 * max(best_edge, 0)
            + 0.20 * row["edge_gap"]
            + 0.20 * row["reach_1atr_h12"]
            + 0.10 * row["continuation_h6"]
            - 0.15 * row["pullback_0p50_h6"]
            + 0.10 * min(len(g) / 500.0, 1.0)
        )

        row["sequence_guidance"] = make_sequence_guidance(row)
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(["sequence_score", "bars"], ascending=[False, False])


def make_sequence_guidance(row: dict[str, Any]) -> str:
    side = row.get("best_side", "WAIT")
    best_edge = row.get("best_edge", 0)
    gap = row.get("edge_gap", 0)
    pull = row.get("pullback_0p50_h6", 0)
    reach = row.get("reach_1atr_h12", 0)

    if best_edge > 0.18 and gap > 0.35 and pull < 0.65:
        return f"{side}: sequência forte; buscar confirmação de entrada"
    if best_edge > 0.10 and reach > 0.75:
        return f"{side}: sequência promissora; preferir reteste/pullback"
    if reach > 0.80 and pull > 0.70:
        return f"{side}: sequência desloca, mas devolve; evitar perseguir"
    if best_edge < 0:
        return "sem edge sequencial; não usar como gatilho"
    return "sequência mista; usar apenas como contexto"


def summarize_sequence_regimes(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    group_cols = ["sequence_regime", "event_group", "breakout_attempt_bucket", "htf_location_bias", "mtf_alignment_bucket", "mtf_bias"]
    rows = []

    for keys, g in df.groupby(group_cols, dropna=False):
        if len(g) < min_bars:
            continue

        if not isinstance(keys, tuple):
            keys = (keys,)

        buy_tp, buy_sl, _, _, buy_edge = side_stats(g, "buy_t1p0_s0p5_h12")
        sell_tp, sell_sl, _, _, sell_edge = side_stats(g, "sell_t1p0_s0p5_h12")

        row = dict(zip(group_cols, keys))
        row.update({
            "bars": len(g),
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "avg_range_sum_5_atr": g["range_sum_5_atr"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
            "buy_edge": buy_edge,
            "sell_edge": sell_edge,
            "best_side": "BUY" if buy_edge >= sell_edge else "SELL",
            "best_edge": max(buy_edge, sell_edge),
            "edge_gap": abs(buy_edge - sell_edge),
        })
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(["best_edge", "edge_gap", "bars"], ascending=[False, False, False])



def bars_since_event(flag: pd.Series, cap: int = 9999) -> pd.Series:
    """Número de candles desde a ocorrência anterior do evento (0 no candle do evento)."""
    values = flag.fillna(False).astype(bool).to_numpy()
    result = np.full(len(values), cap, dtype=int)
    last = None
    for i, occurred in enumerate(values):
        if occurred:
            last = i
            result[i] = 0
        elif last is not None:
            result[i] = min(i - last, cap)
    return pd.Series(result, index=flag.index, dtype="int64")


def bucket_bars_since(s: pd.Series, prefix: str) -> pd.Series:
    return pd.cut(
        pd.to_numeric(s, errors="coerce").fillna(9999),
        [-np.inf, 0, 3, 6, 12, 24, 48, np.inf],
        labels=[
            f"{prefix}_NOW", f"{prefix}_1_3", f"{prefix}_4_6",
            f"{prefix}_7_12", f"{prefix}_13_24", f"{prefix}_25_48", f"{prefix}_OLD_NONE",
        ],
    ).astype("object").fillna(f"{prefix}_UNKNOWN").astype(str)


def add_memory_engine_features(df: pd.DataFrame, anchor_tf: str) -> pd.DataFrame:
    """V7.2 — memória por nível com episódios unificados de falha.

    Regras principais:
    - resistência e suporte mantêm ciclos independentes;
    - candles consecutivos no mesmo contato formam um único episódio;
    - uma nova tentativa exige afastamento mínimo e retorno ao mesmo nível;
    - mudança material do nível abre um novo ciclo;
    - rompimento aceito encerra o ciclo atual;
    - false break e sweep têm episódios próprios, evitando contar candles repetidos.

    Os parâmetros são expressos em ATR para funcionarem em diferentes regimes:
      LEVEL_TOLERANCE_ATR = 0.30  -> níveis próximos pertencem ao mesmo ciclo
      MIN_AWAY_ATR        = 0.35  -> afastamento exigido antes de nova tentativa
      ACCEPTANCE_ATR      = 0.30  -> fechamento além do nível sugere aceitação
      MIN_REENTRY_BARS    = 2     -> intervalo mínimo entre tentativas
      MAX_LEVEL_AGE       = 96    -> expira memória após 8h no M5
    """
    out = df.copy().sort_values("event_time").reset_index(drop=True)
    p = f"{anchor_tf}_"

    high = fcol(out, f"{p}high")
    low = fcol(out, f"{p}low")
    close = fcol(out, f"{p}close")
    atr = out["anchor_atr"].replace(0, np.nan)

    bo_up = out["event_breakout_up"].fillna(False).astype(bool)
    bo_down = out["event_breakout_down"].fillna(False).astype(bool)
    fb_up = bcol(out, f"{p}false_breakout_up")
    fb_down = bcol(out, f"{p}false_breakout_down")
    sw_high = bcol(out, f"{p}sweep_high")
    sw_low = bcol(out, f"{p}sweep_low")

    # Qualquer teste de resistência/suporte pode iniciar ou renovar uma tentativa.
    resistance_touch = bo_up | fb_up | sw_high
    support_touch = bo_down | fb_down | sw_low
    any_bo = bo_up | bo_down

    # Episódios específicos de evento, sem duplicar candles consecutivos.
    out["false_break_episode_start_up"] = fb_up & ~fb_up.shift(1, fill_value=False)
    out["false_break_episode_start_down"] = fb_down & ~fb_down.shift(1, fill_value=False)
    out["false_break_episode_start"] = out["false_break_episode_start_up"] | out["false_break_episode_start_down"]
    out["sweep_episode_start_high"] = sw_high & ~sw_high.shift(1, fill_value=False)
    out["sweep_episode_start_low"] = sw_low & ~sw_low.shift(1, fill_value=False)
    out["sweep_episode_start"] = out["sweep_episode_start_high"] | out["sweep_episode_start_low"]

    n = len(out)
    LEVEL_TOLERANCE_ATR = 0.30
    MIN_AWAY_ATR = 0.35
    ACCEPTANCE_ATR = 0.30
    MIN_REENTRY_BARS = 2
    MAX_LEVEL_AGE = 96
    ACCEPTANCE_BARS = 2

    # Arrays de saída.
    level_attempt_start = np.zeros(n, dtype=bool)
    attempt_side = np.full(n, "NONE", dtype=object)
    level_cycle_id = np.zeros(n, dtype=np.int64)
    level_price = np.full(n, np.nan)
    level_attempt_number = np.zeros(n, dtype=np.int64)
    attempt_cluster_length = np.zeros(n, dtype=np.int64)
    level_reset_reason = np.full(n, "NONE", dtype=object)
    level_age_bars = np.zeros(n, dtype=np.int64)
    distance_from_level_atr = np.full(n, np.nan)
    accepted_breakout = np.zeros(n, dtype=bool)
    attempt_energy_delta = np.full(n, np.nan)
    attempt_range_delta = np.full(n, np.nan)
    attempt_quality = np.full(n, "NO_NEW_ATTEMPT", dtype=object)

    # Estado independente para resistência e suporte.
    def fresh_state():
        return {
            "active": False,
            "level": np.nan,
            "cycle_id": 0,
            "attempt": 0,
            "last_touch": -10_000,
            "last_attempt": -10_000,
            "in_contact": False,
            "away_reached": False,
            "accepted_count": 0,
            "created_at": -1,
            "prev_attempt_energy": np.nan,
            "prev_attempt_range": np.nan,
            "cluster_len": 0,
        }

    states = {"UP": fresh_state(), "DOWN": fresh_state()}
    cycle_counter = 0

    touch_up = resistance_touch.to_numpy(bool)
    touch_down = support_touch.to_numpy(bool)
    highs = high.to_numpy(float)
    lows = low.to_numpy(float)
    closes = close.to_numpy(float)
    atrs = atr.to_numpy(float)
    energies = out["energy_score"].to_numpy(float)
    ranges = out["anchor_range_atr"].to_numpy(float)

    def process_side(i: int, side: str, is_touch: bool) -> None:
        nonlocal cycle_counter
        st = states[side]
        a = atrs[i]
        if not np.isfinite(a) or a <= 0:
            return

        candidate = highs[i] if side == "UP" else lows[i]
        if not np.isfinite(candidate):
            return

        # Expiração temporal do nível.
        if st["active"] and i - st["last_touch"] > MAX_LEVEL_AGE:
            st.update(fresh_state())
            level_reset_reason[i] = "LEVEL_EXPIRED"

        if st["active"]:
            dist = (closes[i] - st["level"]) / a
            distance_from_level_atr[i] = dist
            level_age_bars[i] = max(0, i - st["created_at"])

            # O preço precisa se afastar para que um retorno possa ser nova tentativa.
            if side == "UP" and lows[i] <= st["level"] - MIN_AWAY_ATR * a:
                st["away_reached"] = True
            if side == "DOWN" and highs[i] >= st["level"] + MIN_AWAY_ATR * a:
                st["away_reached"] = True

            # Aceitação exige dois fechamentos consecutivos além do nível.
            beyond = closes[i] >= st["level"] + ACCEPTANCE_ATR * a if side == "UP" else closes[i] <= st["level"] - ACCEPTANCE_ATR * a
            st["accepted_count"] = st["accepted_count"] + 1 if beyond else 0
            if st["accepted_count"] >= ACCEPTANCE_BARS:
                accepted_breakout[i] = True
                level_reset_reason[i] = "ACCEPTED_BREAKOUT"
                st.update(fresh_state())
                return

        if not is_touch:
            if st["active"]:
                st["in_contact"] = False
                st["cluster_len"] = 0
                level_cycle_id[i] = st["cycle_id"]
                level_price[i] = st["level"]
                level_attempt_number[i] = st["attempt"]
            return

        same_level = (
            st["active"]
            and np.isfinite(st["level"])
            and abs(candidate - st["level"]) <= LEVEL_TOLERANCE_ATR * a
        )

        # Mudança material do preço testado cria novo nível/ciclo.
        if not same_level:
            cycle_counter += 1
            previous_reason = "NEW_LEVEL" if st["active"] else "NEW_CYCLE"
            st.update(fresh_state())
            st.update({
                "active": True,
                "level": candidate,
                "cycle_id": cycle_counter,
                "attempt": 1,
                "last_touch": i,
                "last_attempt": i,
                "in_contact": True,
                "created_at": i,
                "cluster_len": 1,
                "prev_attempt_energy": energies[i],
                "prev_attempt_range": ranges[i],
            })
            level_attempt_start[i] = True
            level_reset_reason[i] = previous_reason
        elif st["in_contact"]:
            # Continuação do mesmo episódio; não incrementa tentativa.
            st["last_touch"] = i
            st["cluster_len"] += 1
        else:
            can_reenter = (
                st["away_reached"]
                and i - st["last_attempt"] >= MIN_REENTRY_BARS
            )
            if can_reenter:
                st["attempt"] += 1
                st["last_attempt"] = i
                st["last_touch"] = i
                st["in_contact"] = True
                st["away_reached"] = False
                st["accepted_count"] = 0
                st["cluster_len"] = 1
                level_attempt_start[i] = True

                prev_e = st["prev_attempt_energy"]
                prev_r = st["prev_attempt_range"]
                if np.isfinite(prev_e):
                    attempt_energy_delta[i] = energies[i] - prev_e
                if np.isfinite(prev_r):
                    attempt_range_delta[i] = ranges[i] - prev_r
                if attempt_energy_delta[i] > 5 and attempt_range_delta[i] > 0.10:
                    attempt_quality[i] = "IMPROVING"
                elif attempt_energy_delta[i] < -5 and attempt_range_delta[i] < -0.10:
                    attempt_quality[i] = "WEAKENING"
                else:
                    attempt_quality[i] = "STABLE"
                st["prev_attempt_energy"] = energies[i]
                st["prev_attempt_range"] = ranges[i]
            else:
                # Retorno precoce sem afastamento suficiente: mesmo episódio lógico.
                st["in_contact"] = True
                st["last_touch"] = i
                st["cluster_len"] = max(1, st["cluster_len"] + 1)

        attempt_side[i] = side
        level_cycle_id[i] = st["cycle_id"]
        level_price[i] = st["level"]
        level_attempt_number[i] = st["attempt"]
        attempt_cluster_length[i] = st["cluster_len"]
        level_age_bars[i] = max(0, i - st["created_at"])
        if np.isfinite(st["level"]):
            distance_from_level_atr[i] = (closes[i] - st["level"]) / a
        if level_attempt_start[i] and attempt_quality[i] == "NO_NEW_ATTEMPT":
            attempt_quality[i] = "FIRST_ATTEMPT" if st["attempt"] == 1 else "STABLE"

    for i in range(n):
        # Processa ambos os lados; eventos raros simultâneos continuam independentes.
        process_side(i, "UP", bool(touch_up[i]))
        up_started = level_attempt_start[i]
        up_snapshot = (
            attempt_side[i], level_cycle_id[i], level_price[i], level_attempt_number[i],
            attempt_cluster_length[i], level_reset_reason[i], level_age_bars[i],
            distance_from_level_atr[i], attempt_energy_delta[i], attempt_range_delta[i], attempt_quality[i]
        )
        process_side(i, "DOWN", bool(touch_down[i]))
        if up_started and not touch_down[i]:
            (attempt_side[i], level_cycle_id[i], level_price[i], level_attempt_number[i],
             attempt_cluster_length[i], level_reset_reason[i], level_age_bars[i],
             distance_from_level_atr[i], attempt_energy_delta[i], attempt_range_delta[i], attempt_quality[i]) = up_snapshot

    out["level_attempt_start"] = level_attempt_start
    out["level_attempt_side"] = attempt_side
    out["level_cycle_id"] = level_cycle_id
    out["level_price"] = level_price
    out["level_attempt_number"] = level_attempt_number
    out["level_attempt_cluster_length"] = attempt_cluster_length
    out["level_reset_reason"] = level_reset_reason
    out["level_age_bars"] = level_age_bars
    out["distance_from_level_atr"] = distance_from_level_atr
    out["accepted_breakout"] = accepted_breakout

    # Compatibilidade com relatórios V7: agora os aliases refletem tentativas por nível.
    out["breakout_episode_start"] = out["level_attempt_start"]
    out["breakout_episode_start_up"] = out["level_attempt_start"] & out["level_attempt_side"].eq("UP")
    out["breakout_episode_start_down"] = out["level_attempt_start"] & out["level_attempt_side"].eq("DOWN")
    out["breakout_episode_side"] = out["level_attempt_side"]
    out["breakout_episode_id"] = out["level_cycle_id"]
    out["breakout_cluster_length"] = out["level_attempt_cluster_length"]
    out["breakout_side"] = np.select([resistance_touch, support_touch], ["UP", "DOWN"], default="NONE")

    out["bars_since_breakout"] = bars_since_event(any_bo)
    out["bars_since_breakout_episode"] = bars_since_event(out["level_attempt_start"])
    out["bars_since_false_break"] = bars_since_event(out["false_break_episode_start"])
    out["bars_since_sweep"] = bars_since_event(out["sweep_episode_start"])
    out["bars_since_expansion"] = bars_since_event(out["event_expansion"])
    out["since_breakout_bucket"] = bucket_bars_since(out["bars_since_breakout_episode"], "BO")
    out["since_false_break_bucket"] = bucket_bars_since(out["bars_since_false_break"], "FB")
    out["since_sweep_bucket"] = bucket_bars_since(out["bars_since_sweep"], "SW")

    starts = out["level_attempt_start"].astype(int)
    for window in (12, 24, 48):
        out[f"breakout_episodes_{window}"] = starts.rolling(window, min_periods=1).sum().astype(int)

    # Número real da tentativa no mesmo nível, não total genérico da janela.
    out["attempt_number_48"] = out["level_attempt_number"]
    out["attempt_bucket"] = pd.cut(
        out["level_attempt_number"],
        [-np.inf, 0, 1, 2, 3, np.inf],
        labels=["NO_ATTEMPT", "FIRST_ATTEMPT", "SECOND_ATTEMPT", "THIRD_ATTEMPT", "FOURTH_PLUS"],
    ).astype("object").fillna("UNKNOWN").astype(str)

    out["attempt_energy_delta"] = attempt_energy_delta
    out["attempt_range_delta"] = attempt_range_delta
    out["attempt_quality"] = attempt_quality

    # V7.2 — episódio unificado de falha por nível.
    # False break e sweep no mesmo contato representam uma única falha estrutural.
    raw_failure_up = fb_up | sw_high
    raw_failure_down = fb_down | sw_low
    raw_failure = raw_failure_up | raw_failure_down
    raw_failure_side = np.select([raw_failure_up, raw_failure_down], ["UP", "DOWN"], default="NONE")

    failure_episode_start = np.zeros(n, dtype=bool)
    failure_episode_side = np.full(n, "NONE", dtype=object)
    failure_episode_id = np.zeros(n, dtype=np.int64)
    failures_on_current_level = np.zeros(n, dtype=np.int64)
    bars_since_level_failure = np.full(n, 9999, dtype=np.int64)

    failure_counter = 0
    cycle_failures: dict[tuple[str, int], int] = {}
    last_failure_bar: dict[tuple[str, int], int] = {}
    previous_active_key: tuple[str, int] | None = None
    previous_raw_failure = False

    raw_failure_values = raw_failure.to_numpy(bool)
    raw_failure_sides = np.asarray(raw_failure_side, dtype=object)
    cycle_values = out["level_cycle_id"].to_numpy(np.int64)
    side_values = out["level_attempt_side"].astype(str).to_numpy(object)

    for i in range(n):
        side_i = str(raw_failure_sides[i]) if raw_failure_values[i] else str(side_values[i])
        cycle_i = int(cycle_values[i])
        key = (side_i, cycle_i) if side_i in ("UP", "DOWN") and cycle_i > 0 else None

        if raw_failure_values[i] and key is not None:
            # Candles consecutivos do mesmo contato/nível formam um único episódio.
            is_new_episode = not (previous_raw_failure and previous_active_key == key)
            if is_new_episode:
                failure_counter += 1
                failure_episode_start[i] = True
                failure_episode_side[i] = side_i
                failure_episode_id[i] = failure_counter
                cycle_failures[key] = cycle_failures.get(key, 0) + 1
                last_failure_bar[key] = i
            else:
                failure_episode_side[i] = side_i
                failure_episode_id[i] = failure_counter

        if key is not None:
            failures_on_current_level[i] = cycle_failures.get(key, 0)
            if key in last_failure_bar:
                bars_since_level_failure[i] = i - last_failure_bar[key]

        previous_raw_failure = bool(raw_failure_values[i])
        previous_active_key = key if raw_failure_values[i] else None

    out["failure_episode_start"] = failure_episode_start
    out["failure_episode_side"] = failure_episode_side
    out["failure_episode_id"] = failure_episode_id
    out["failures_on_current_level"] = failures_on_current_level
    out["bars_since_level_failure"] = bars_since_level_failure
    out["since_level_failure_bucket"] = bucket_bars_since(out["bars_since_level_failure"], "LF")

    # Compatibilidade: a contagem temporal agora usa episódios unificados, não FB + sweep separados.
    recent_failures = out["failure_episode_start"].astype(int).rolling(24, min_periods=1).sum()
    out["recent_failure_count_24"] = recent_failures.astype(int)
    out["failure_memory_bucket"] = pd.cut(
        out["failures_on_current_level"],
        [-np.inf, 0, 1, 2, np.inf],
        labels=["NO_RECENT_FAILURE", "ONE_RECENT_FAILURE", "TWO_RECENT_FAILURES", "THREE_PLUS_FAILURES"],
    ).astype("object").fillna("UNKNOWN").astype(str)

    cumulative_attempts = starts.cumsum()
    last_at_fb = cumulative_attempts.where(out["false_break_episode_start"]).ffill().fillna(0)
    last_at_sw = cumulative_attempts.where(out["sweep_episode_start"]).ffill().fillna(0)
    last_at_failure = cumulative_attempts.where(out["failure_episode_start"]).ffill().fillna(0)
    out["attempts_since_false_break"] = (cumulative_attempts - last_at_fb).clip(lower=0).astype(int)
    out["attempts_since_sweep"] = (cumulative_attempts - last_at_sw).clip(lower=0).astype(int)
    out["attempts_since_level_failure"] = (cumulative_attempts - last_at_failure).clip(lower=0).astype(int)

    out["memory_condition"] = np.select(
        [
            out["level_attempt_start"] & out["attempt_bucket"].eq("FIRST_ATTEMPT") & out["failure_memory_bucket"].eq("NO_RECENT_FAILURE"),
            out["level_attempt_start"] & out["attempt_bucket"].eq("SECOND_ATTEMPT"),
            out["level_attempt_start"] & out["attempt_bucket"].eq("THIRD_ATTEMPT"),
            out["level_attempt_start"] & out["attempt_bucket"].eq("FOURTH_PLUS"),
            out["level_attempt_start"] & out["attempt_quality"].eq("IMPROVING"),
            out["level_attempt_start"] & out["attempt_quality"].eq("WEAKENING"),
            out["accepted_breakout"],
            resistance_touch | support_touch,
            out["bars_since_false_break"].le(6),
            out["bars_since_sweep"].le(6),
        ],
        [
            "CLEAN_FIRST_ATTEMPT", "SECOND_LEVEL_ATTEMPT", "THIRD_LEVEL_ATTEMPT", "FOURTH_PLUS_PRESSURE",
            "IMPROVING_LEVEL_ATTEMPT", "WEAKENING_LEVEL_ATTEMPT", "ACCEPTED_LEVEL_BREAK",
            "ACTIVE_LEVEL_CONTACT", "RECENT_FALSE_BREAK_MEMORY", "RECENT_SWEEP_MEMORY",
        ],
        default="NEUTRAL_MEMORY",
    )

    out["memory_dna"] = (
        "memory=" + out["memory_condition"].astype(str)
        + "|side=" + out["level_attempt_side"].astype(str)
        + "|attempt=" + out["attempt_bucket"].astype(str)
        + "|quality=" + out["attempt_quality"].astype(str)
        + "|fail=" + out["failure_memory_bucket"].astype(str)
        + "|lf_age=" + out["since_level_failure_bucket"].astype(str)
        + "|align=" + out["mtf_alignment_bucket"].astype(str) + "/" + out["mtf_bias"].astype(str)
    )
    out["memory_setup"] = (
        out["setup_genome_macro"].astype(str)
        + "|mem=" + out["memory_condition"].astype(str)
        + "|side=" + out["level_attempt_side"].astype(str)
        + "|attempt=" + out["attempt_bucket"].astype(str)
        + "|fb=" + out["since_false_break_bucket"].astype(str)
        + "|sw=" + out["since_sweep_bucket"].astype(str)
        + "|lf=" + out["failure_memory_bucket"].astype(str)
    )
    out["memory_id"] = pd.util.hash_pandas_object(out["memory_dna"], index=False).astype("uint64").astype(str).str[-8:]
    out["memory_setup_id"] = pd.util.hash_pandas_object(out["memory_setup"], index=False).astype("uint64").astype(str).str[-8:]
    return out

def summarize_memory_groups(df: pd.DataFrame, key_col: str, min_bars: int) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(key_col, dropna=False):
        if len(g) < min_bars:
            continue
        buy_tp, buy_sl, _, _, buy_edge = side_stats(g, "buy_t1p0_s0p5_h12")
        sell_tp, sell_sl, _, _, sell_edge = side_stats(g, "sell_t1p0_s0p5_h12")
        best_side = "BUY" if buy_edge >= sell_edge else "SELL"
        best_edge = max(buy_edge, sell_edge)
        row = {
            "memory_type": key_col,
            "memory_key": key,
            "bars": len(g),
            "episode_starts": int(g["breakout_episode_start"].sum()),
            "avg_attempt_number_48": g["attempt_number_48"].mean(),
            "avg_recent_failures_24": g["recent_failure_count_24"].mean(),
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
            "buy_tp": buy_tp, "buy_sl": buy_sl, "buy_edge": buy_edge,
            "sell_tp": sell_tp, "sell_sl": sell_sl, "sell_edge": sell_edge,
            "best_side": best_side, "best_edge": best_edge,
            "edge_gap": abs(buy_edge - sell_edge),
        }
        row["memory_score"] = (
            0.40 * max(best_edge, 0)
            + 0.20 * row["edge_gap"]
            + 0.20 * row["reach_1atr_h12"]
            + 0.10 * row["continuation_h6"]
            - 0.15 * row["pullback_0p50_h6"]
            + 0.05 * min(len(g) / 500.0, 1.0)
        )
        row["memory_guidance"] = make_memory_guidance(row)
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["memory_score", "bars"], ascending=[False, False])


def make_memory_guidance(row: dict[str, Any]) -> str:
    side = row.get("best_side", "WAIT")
    edge = row.get("best_edge", 0.0)
    gap = row.get("edge_gap", 0.0)
    pull = row.get("pullback_0p50_h6", 0.0)
    if edge >= 0.18 and gap >= 0.30 and pull < 0.65:
        return f"{side}: memória favorável; buscar confirmação/reteste"
    if edge >= 0.10 and pull >= 0.65:
        return f"{side}: há deslocamento, mas a memória indica devolução; não perseguir"
    if edge < 0:
        return "memória desfavorável; evitar usar como gatilho"
    return "memória inconclusiva; usar apenas como filtro contextual"


def summarize_memory_attempts(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    events = df[df["breakout_episode_start"]].copy()
    group_cols = [
        "breakout_episode_side", "attempt_bucket", "attempt_quality",
        "failure_memory_bucket", "memory_condition", "mtf_alignment_bucket", "mtf_bias",
    ]
    rows = []
    for keys, g in events.groupby(group_cols, dropna=False):
        if len(g) < max(20, min_bars // 3):
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)
        buy_tp, buy_sl, _, _, buy_edge = side_stats(g, "buy_t1p0_s0p5_h12")
        sell_tp, sell_sl, _, _, sell_edge = side_stats(g, "sell_t1p0_s0p5_h12")
        row = dict(zip(group_cols, keys))
        row.update({
            "attempts": len(g),
            "avg_energy": g["energy_score"].mean(),
            "avg_range_atr": g["anchor_range_atr"].mean(),
            "avg_energy_delta": g["attempt_energy_delta"].mean(),
            "avg_range_delta": g["attempt_range_delta"].mean(),
            "continuation_h6": g["h6_continues"].mean(),
            "pullback_0p50_h6": g["h6_pullback_0p50"].mean(),
            "reach_1atr_h12": g["h12_reaches_1p00"].mean(),
            "buy_edge": buy_edge, "sell_edge": sell_edge,
            "best_side": "BUY" if buy_edge >= sell_edge else "SELL",
            "best_edge": max(buy_edge, sell_edge),
            "edge_gap": abs(buy_edge - sell_edge),
        })
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["best_edge", "edge_gap", "attempts"], ascending=[False, False, False])


def summarize_memory_playbook(memory_dna: pd.DataFrame, memory_setup: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for source, table in (("MEMORY_DNA", memory_dna), ("MEMORY_SETUP", memory_setup)):
        if table.empty:
            continue
        x = table.copy()
        x.insert(0, "source", source)
        frames.append(x)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    out = out[(out["best_edge"] > 0) & (out["edge_gap"] >= 0.08)].copy()
    return out.sort_values(["memory_score", "best_edge", "bars"], ascending=[False, False, False]).head(500)


def append_memory_report(
    path: Path,
    memory_dna: pd.DataFrame,
    memory_attempts: pd.DataFrame,
    memory_playbook: pd.DataFrame,
) -> None:
    lines = [
        "\n---\n",
        "# V7 — Memory Engine\n",
        f"- Memory DNA: {len(memory_dna)} padrões\n",
        f"- Memory Attempts: {len(memory_attempts)} grupos de tentativas\n",
        f"- Memory Playbook: {len(memory_playbook)} padrões selecionados\n",
        "\n## Leitura\n",
        "A V7 conta episódios de rompimento, não candles isolados. Candles consecutivos do mesmo lado pertencem ao mesmo cluster.\n",
    ]
    if not memory_playbook.empty:
        lines += ["\n## Melhores memórias observadas\n", "```text\n"]
        for _, row in memory_playbook.head(15).iterrows():
            key = str(row.get("memory_key", ""))[:180]
            lines.append(
                f"{row.get('source', 'MEMORY')} | {row.get('best_side', 'WAIT')} | "
                f"edge={row.get('best_edge', float('nan')):.3f} | bars={int(row.get('bars', 0))} | {key}\n"
            )
        lines.append("```\n")
    with path.open("a", encoding="utf-8") as fh:
        fh.writelines(lines)

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
    state_playbook: pd.DataFrame,
    state_transitions: pd.DataFrame,
    setup_genome: pd.DataFrame,
    htf_location: pd.DataFrame,
    htf_breakout: pd.DataFrame,
    sequence_regimes: pd.DataFrame,
    sequence_dna: pd.DataFrame,
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

    if not state_playbook.empty:
        lines += ["## State Intelligence — DNA do mercado\n", state_playbook.head(30).to_markdown(index=False), ""]

    if not state_transitions.empty:
        lines += ["## State Transitions — gramática do mercado\n", state_transitions.head(30).to_markdown(index=False), ""]

    if not setup_genome.empty:
        lines += ["## Setup Genome — genoma do setup\n", setup_genome.head(30).to_markdown(index=False), ""]

    if not htf_location.empty:
        lines += ["## HTF Location DNA — localização multi-timeframe\n", htf_location.head(30).to_markdown(index=False), ""]

    if not htf_breakout.empty:
        lines += ["## HTF Breakout Alignment — rompimento contra/a favor do HTF\n", htf_breakout.head(30).to_markdown(index=False), ""]

    if not sequence_regimes.empty:
        lines += ["## Sequence Regimes — DNA temporal\n", sequence_regimes.head(30).to_markdown(index=False), ""]

    if not sequence_dna.empty:
        lines += ["## Sequence DNA — genoma temporal\n", sequence_dna.head(30).to_markdown(index=False), ""]

    lines += [
        "## Como interpretar\n",
        "- `behavior_summary`: descreve o comportamento típico do horário.",
        "- `operational_guidance`: ajuda a evitar decisões ruins, como stop curto ou perseguir candle.",
        "- `dna_score`: ranking inicial de padrões para validação visual.",
        "- `rr_tp`: bateu +1 ATR antes de -0,5 ATR em até 12 candles M5.",
        "- `rr_edge`: diferença entre TP e SL; ainda não é lucro real.",
        "- `level_guidance`: leitura estatística para resistência/suporte: romper, rejeitar ou esperar confirmação.",
        "- `state_dna_*`: identidade estatística do estado de mercado.",
        "- `state_playbook`: orientação contextual por estado, não gatilho de entrada.",
        "- `setup_genome`: combinação estatística de contexto + localização + evento + lado provável.",
        "- `htf_location_dna`: mede se o setup M5 está alinhado ou contra a localização H1/H4/D1.",
        "- `sequence_dna`: mede como o mercado chegou no setup atual, não apenas a foto do candle.",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")



# -----------------------------------------------------------------------------
# V8 — VALIDATION ENGINE
# -----------------------------------------------------------------------------

def _validation_law_definitions(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Market Laws candidatas descobertas até a V7.2.

    Cada lei define um filtro causal no candle atual e um lado fixo para avaliação.
    A V8 não otimiza os filtros; apenas testa hipóteses previamente declaradas.
    """
    first = df["attempt_bucket"].eq("FIRST_ATTEMPT")
    second = df["attempt_bucket"].eq("SECOND_ATTEMPT")
    no_fail = df["failure_memory_bucket"].eq("NO_RECENT_FAILURE")
    one_fail = df["failure_memory_bucket"].eq("ONE_RECENT_FAILURE")
    res_side = df["level_attempt_side"].eq("UP")
    sup_side = df["level_attempt_side"].eq("DOWN")
    mtf_down = df["mtf_bias"].eq("DOWN") & df["mtf_alignment_bucket"].isin(["MIXED", "STRONG", "FULL"])
    mtf_up = df["mtf_bias"].eq("UP") & df["mtf_alignment_bucket"].isin(["MIXED", "STRONG", "FULL"])
    fb_recent = pd.to_numeric(df["bars_since_false_break"], errors="coerce").between(1, 3)
    sw_recent = pd.to_numeric(df["bars_since_sweep"], errors="coerce").between(1, 3)

    return [
        {
            "law_id": "LAW_0001A",
            "law_name": "First Resistance Attempt Against Bearish MTF",
            "side": "SELL",
            "hypothesis": "Primeira tentativa contra resistência, sem falha no nível atual e contra MTF vendedor favorece devolução.",
            "mask": res_side & first & no_fail & mtf_down,
        },
        {
            "law_id": "LAW_0001B",
            "law_name": "First Support Attempt Against Bullish MTF",
            "side": "BUY",
            "hypothesis": "Primeira tentativa contra suporte, sem falha no nível atual e contra MTF comprador favorece devolução.",
            "mask": sup_side & first & no_fail & mtf_up,
        },
        {
            "law_id": "LAW_0002A",
            "law_name": "Resistance Breakout After External Failure Memory",
            "side": "SELL",
            "hypothesis": "Breakout de resistência contra MTF vendedor após false break e sweep recentes favorece devolução.",
            "mask": res_side & first & no_fail & mtf_down & df["event_breakout_up"] & fb_recent & sw_recent,
        },
        {
            "law_id": "LAW_0002B",
            "law_name": "Support Breakout After External Failure Memory",
            "side": "BUY",
            "hypothesis": "Breakout de suporte contra MTF comprador após false break e sweep recentes favorece devolução.",
            "mask": sup_side & first & no_fail & mtf_up & df["event_breakout_down"] & fb_recent & sw_recent,
        },
        {
            "law_id": "LAW_0003A",
            "law_name": "Second Resistance Attempt After One Failure",
            "side": "SELL",
            "hypothesis": "Segunda tentativa contra resistência após uma falha no nível e contra MTF vendedor favorece rejeição.",
            "mask": res_side & second & one_fail & mtf_down,
        },
        {
            "law_id": "LAW_0003B",
            "law_name": "Second Support Attempt After One Failure",
            "side": "BUY",
            "hypothesis": "Segunda tentativa contra suporte após uma falha no nível e contra MTF comprador favorece defesa.",
            "mask": sup_side & second & one_fail & mtf_up,
        },
    ]


def _law_sample_stats(g: pd.DataFrame, side: str) -> dict[str, Any]:
    col = "buy_t1p0_s0p5_h12" if side == "BUY" else "sell_t1p0_s0p5_h12"
    if g.empty or col not in g.columns:
        return {"bars": 0, "valid": 0, "tp_rate": np.nan, "sl_rate": np.nan, "edge": np.nan,
                "edge_ci_low": np.nan, "edge_ci_high": np.nan, "no_touch_rate": np.nan,
                "ambiguous_rate": np.nan, "reach_1atr": np.nan, "pullback_0p50": np.nan}
    s = g[col].dropna()
    valid = s.isin(["TP_FIRST", "SL_FIRST", "NO_TOUCH", "AMBIGUOUS"])
    s = s.loc[valid]
    n = len(s)
    if n == 0:
        return {"bars": len(g), "valid": 0, "tp_rate": np.nan, "sl_rate": np.nan, "edge": np.nan,
                "edge_ci_low": np.nan, "edge_ci_high": np.nan, "no_touch_rate": np.nan,
                "ambiguous_rate": np.nan, "reach_1atr": np.nan, "pullback_0p50": np.nan}
    x = np.select([s.eq("TP_FIRST"), s.eq("SL_FIRST")], [1.0, -1.0], default=0.0)
    edge = float(np.mean(x))
    se = float(np.std(x, ddof=1) / math.sqrt(n)) if n > 1 else np.nan
    z = 1.96
    return {
        "bars": len(g), "valid": n,
        "tp_rate": s.eq("TP_FIRST").mean(), "sl_rate": s.eq("SL_FIRST").mean(),
        "edge": edge,
        "edge_ci_low": edge - z * se if np.isfinite(se) else np.nan,
        "edge_ci_high": edge + z * se if np.isfinite(se) else np.nan,
        "no_touch_rate": s.eq("NO_TOUCH").mean(), "ambiguous_rate": s.eq("AMBIGUOUS").mean(),
        "reach_1atr": pd.to_numeric(g["h12_reaches_1p00"], errors="coerce").mean(),
        "pullback_0p50": pd.to_numeric(g["h6_pullback_0p50"], errors="coerce").mean(),
    }


def _chronological_segments(df: pd.DataFrame) -> dict[str, pd.Series]:
    order = df["event_time"].sort_values().index
    n = len(order)
    train_end = int(n * 0.70)
    recent_start = int(n * 0.75)
    masks = {}
    for name, idx in {
        "IN_SAMPLE_70": order[:train_end],
        "OUT_OF_SAMPLE_30": order[train_end:],
        "RECENT_25": order[recent_start:],
        "FULL": order,
    }.items():
        m = pd.Series(False, index=df.index)
        m.loc[idx] = True
        masks[name] = m
    return masks


def validate_market_laws(df: pd.DataFrame, min_oos: int = 40) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Valida leis declaradas em splits temporais, anos e janelas cronológicas.

    O edge é TP_FIRST - SL_FIRST para alvo de 1 ATR e stop de 0,5 ATR em 12 candles.
    Intervalo de confiança de 95% usa a média da variável {-1, 0, +1}.
    """
    work = df.sort_values("event_time").copy()
    work["year"] = pd.to_datetime(work["event_time"], errors="coerce").dt.year
    segments = _chronological_segments(work)
    laws = _validation_law_definitions(work)
    split_rows, year_rows, rolling_rows = [], [], []

    for law in laws:
        base_mask = law["mask"].fillna(False)
        for split_name, split_mask in segments.items():
            stats = _law_sample_stats(work.loc[base_mask & split_mask], law["side"])
            split_rows.append({k: law[k] for k in ("law_id", "law_name", "side", "hypothesis")} | {"split": split_name} | stats)

        years = sorted(y for y in work.loc[base_mask, "year"].dropna().unique())
        for year in years:
            stats = _law_sample_stats(work.loc[base_mask & work["year"].eq(year)], law["side"])
            year_rows.append({k: law[k] for k in ("law_id", "law_name", "side")} | {"year": int(year)} | stats)

        positions = np.arange(len(work))
        for window_no, pos_chunk in enumerate(np.array_split(positions, 10), start=1):
            if len(pos_chunk) == 0:
                continue
            idx = work.index[pos_chunk]
            wm = pd.Series(False, index=work.index)
            wm.loc[idx] = True
            stats = _law_sample_stats(work.loc[base_mask & wm], law["side"])
            rolling_rows.append({k: law[k] for k in ("law_id", "law_name", "side")} | {
                "window": window_no,
                "start_time": work.loc[idx, "event_time"].min(),
                "end_time": work.loc[idx, "event_time"].max(),
            } | stats)

    splits = pd.DataFrame(split_rows)
    yearly = pd.DataFrame(year_rows)
    rolling = pd.DataFrame(rolling_rows)
    summary_rows = []
    for law in laws:
        lid = law["law_id"]
        s = splits[splits["law_id"].eq(lid)].set_index("split")
        y = yearly[yearly["law_id"].eq(lid)]
        r = rolling[rolling["law_id"].eq(lid)]
        full = s.loc["FULL"] if "FULL" in s.index else pd.Series(dtype=object)
        oos = s.loc["OUT_OF_SAMPLE_30"] if "OUT_OF_SAMPLE_30" in s.index else pd.Series(dtype=object)
        ins = s.loc["IN_SAMPLE_70"] if "IN_SAMPLE_70" in s.index else pd.Series(dtype=object)
        yearly_valid = y[y["valid"] >= 20]
        rolling_valid = r[r["valid"] >= 15]
        year_pos = yearly_valid["edge"].gt(0).mean() if len(yearly_valid) else np.nan
        roll_pos = rolling_valid["edge"].gt(0).mean() if len(rolling_valid) else np.nan
        degradation = (oos.get("edge", np.nan) / ins.get("edge", np.nan)) if ins.get("edge", 0) > 0 else np.nan
        status = "REJECTED"
        if (full.get("valid", 0) >= 120 and oos.get("valid", 0) >= min_oos and
            full.get("edge", -1) > 0.10 and oos.get("edge", -1) > 0.05 and
            year_pos >= 0.60 and roll_pos >= 0.60):
            status = "VALIDATED" if full.get("edge_ci_low", -1) > 0 and oos.get("edge_ci_low", -1) > 0 else "PROVISIONAL"
        elif full.get("valid", 0) >= 80 and full.get("edge", -1) > 0.05:
            status = "PROVISIONAL"
        summary_rows.append({
            "law_id": lid, "law_name": law["law_name"], "side": law["side"], "hypothesis": law["hypothesis"],
            "status": status,
            "full_bars": full.get("bars", 0), "full_valid": full.get("valid", 0),
            "full_edge": full.get("edge", np.nan), "full_ci_low": full.get("edge_ci_low", np.nan), "full_ci_high": full.get("edge_ci_high", np.nan),
            "is_edge": ins.get("edge", np.nan), "oos_edge": oos.get("edge", np.nan), "recent_edge": s.loc["RECENT_25"].get("edge", np.nan) if "RECENT_25" in s.index else np.nan,
            "oos_valid": oos.get("valid", 0), "oos_degradation_ratio": degradation,
            "positive_year_ratio": year_pos, "years_tested": len(yearly_valid),
            "positive_window_ratio": roll_pos, "windows_tested": len(rolling_valid),
            "full_tp_rate": full.get("tp_rate", np.nan), "full_sl_rate": full.get("sl_rate", np.nan),
            "full_pullback_0p50": full.get("pullback_0p50", np.nan), "full_reach_1atr": full.get("reach_1atr", np.nan),
        })
    summary = pd.DataFrame(summary_rows).sort_values(["status", "full_edge"], ascending=[True, False])
    return summary, splits, yearly, rolling


def append_validation_report(path: Path, summary: pd.DataFrame) -> None:
    if summary.empty:
        return
    lines = ["", "# V8 — Validation Engine", "",
             "Validação temporal das Market Laws candidatas. `edge` = TP_FIRST − SL_FIRST para alvo 1 ATR, stop 0,5 ATR e horizonte 12 candles.", ""]
    cols = ["law_id", "law_name", "side", "status", "full_valid", "full_edge", "full_ci_low", "oos_valid", "oos_edge", "recent_edge", "positive_year_ratio", "positive_window_ratio"]
    lines += [summary[cols].to_markdown(index=False), "",
              "## Critérios", "",
              "- `VALIDATED`: amostra total e OOS suficientes, edge positivo no OOS, estabilidade anual/rolling e IC95% acima de zero.",
              "- `PROVISIONAL`: evidência positiva, mas ainda sem robustez suficiente para virar Market Law definitiva.",
              "- `REJECTED`: hipótese não sustentada com os critérios atuais.", ""]
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# -----------------------------------------------------------------------------
# V9 — LAW SEGMENTATION ENGINE
# -----------------------------------------------------------------------------

def add_law_segmentation_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona dimensões interpretáveis sem alterar as Market Laws originais.

    As sessões são faixas operacionais aproximadas em BRT e não tentam corrigir
    individualmente DST de Londres/Nova York. O objetivo é segmentação robusta,
    não definição de horário oficial de bolsas.
    """
    out = df.copy()
    event_time = pd.to_datetime(out["event_time"], errors="coerce")
    out["weekday"] = event_time.dt.day_name().str.upper().fillna("UNKNOWN")
    out["month"] = event_time.dt.month.fillna(-1).astype(int)
    hour = pd.to_numeric(out["hour"], errors="coerce").fillna(-1).astype(int)
    out["session_brt"] = np.select(
        [
            hour.isin([21,22,23,0,1,2,3]),
            hour.isin([4,5]),
            hour.isin([6,7,8]),
            hour.isin([9,10,11,12]),
            hour.isin([13,14,15,16]),
            hour.isin([17,18,19,20]),
        ],
        ["ASIA","PRE_LONDON","LONDON","NY_OPEN","NY_AFTERNOON","LATE_BRT"],
        default="UNKNOWN",
    )
    # Confluência de localização já calculada na V5.
    out["htf_location_group"] = scol(out, "htf_location_bias")
    out["breakout_alignment_group"] = scol(out, "breakout_location_alignment")
    out["level_proximity_group"] = np.select(
        [
            out["resistance_bucket"].isin(["TOUCHING","VERY_NEAR"]),
            out["support_bucket"].isin(["TOUCHING","VERY_NEAR"]),
        ],
        ["NEAR_RESISTANCE", "NEAR_SUPPORT"],
        default="OTHER_LOCATION",
    )
    return out


def _segment_status(base_edge: float, stats: dict[str, Any], oos_stats: dict[str, Any], min_segment: int) -> str:
    valid = int(stats.get("valid", 0) or 0)
    oos_valid = int(oos_stats.get("valid", 0) or 0)
    edge = stats.get("edge", np.nan)
    oos_edge = oos_stats.get("edge", np.nan)
    ci_low = stats.get("edge_ci_low", np.nan)
    if valid < min_segment or oos_valid < max(12, min_segment // 3):
        return "INSUFFICIENT"
    if not np.isfinite(edge) or not np.isfinite(oos_edge):
        return "INSUFFICIENT"
    delta = edge - base_edge if np.isfinite(base_edge) else np.nan
    if np.isfinite(ci_low) and ci_low > 0 and oos_edge > 0 and delta >= 0.08:
        return "STRONGER"
    if edge > 0 and oos_edge > 0 and (not np.isfinite(delta) or delta >= -0.08):
        return "STABLE"
    if edge <= 0 or oos_edge <= 0 or (np.isfinite(delta) and delta <= -0.15):
        return "WEAKER"
    return "MIXED"


def segment_validated_laws(
    df: pd.DataFrame,
    validation_summary: pd.DataFrame,
    min_segment: int = 40,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Segmenta leis congeladas, uma dimensão por vez.

    Este módulo é diagnóstico/exploratório. Segmentos não viram novas leis sem
    uma validação temporal própria posterior e correção para múltiplos testes.
    """
    work = add_law_segmentation_features(df).sort_values("event_time").copy()
    laws = _validation_law_definitions(work)
    split_masks = _chronological_segments(work)
    oos_mask = split_masks["OUT_OF_SAMPLE_30"]
    base_map = {}
    if not validation_summary.empty:
        base_map = validation_summary.set_index("law_id")["full_edge"].to_dict()

    dimensions = {
        "HOUR_BRT": "hour",
        "SESSION_BRT": "session_brt",
        "WEEKDAY": "weekday",
        "ENERGY": "energy_bucket",
        "HTF_LOCATION": "htf_location_group",
        "BREAKOUT_ALIGNMENT": "breakout_alignment_group",
        "LEVEL_PROXIMITY": "level_proximity_group",
    }
    rows=[]
    for law in laws:
        law_mask = law["mask"].fillna(False)
        base_edge = float(base_map.get(law["law_id"], np.nan))
        for dim_name, col in dimensions.items():
            if col not in work.columns:
                continue
            vals = work.loc[law_mask, col].astype(str).fillna("UNKNOWN")
            for value in sorted(vals.unique()):
                seg_mask = law_mask & work[col].astype(str).eq(value)
                full_stats = _law_sample_stats(work.loc[seg_mask], law["side"])
                oos_stats = _law_sample_stats(work.loc[seg_mask & oos_mask], law["side"])
                delta = full_stats["edge"] - base_edge if np.isfinite(full_stats["edge"]) and np.isfinite(base_edge) else np.nan
                rows.append({
                    "law_id":law["law_id"],
                    "law_name":law["law_name"],
                    "side":law["side"],
                    "dimension":dim_name,
                    "segment":value,
                    "base_edge":base_edge,
                    "segment_edge_delta":delta,
                    "segment_status":_segment_status(base_edge, full_stats, oos_stats, min_segment),
                    **{f"full_{k}":v for k,v in full_stats.items()},
                    **{f"oos_{k}":v for k,v in oos_stats.items()},
                })
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail, detail
    detail = detail.sort_values(["law_id","dimension","segment_status","full_edge"], ascending=[True,True,True,False])
    eligible = detail.loc[detail["segment_status"].isin(["STRONGER","STABLE","WEAKER"])].copy()
    summary_rows=[]
    for (law_id, dimension), g in eligible.groupby(["law_id","dimension"], dropna=False):
        strongest = g.sort_values(["full_edge","full_valid"], ascending=[False,False]).iloc[0]
        weakest = g.sort_values(["full_edge","full_valid"], ascending=[True,False]).iloc[0]
        summary_rows.append({
            "law_id":law_id,
            "law_name":strongest["law_name"],
            "dimension":dimension,
            "strongest_segment":strongest["segment"],
            "strongest_status":strongest["segment_status"],
            "strongest_valid":strongest["full_valid"],
            "strongest_edge":strongest["full_edge"],
            "strongest_oos_edge":strongest["oos_edge"],
            "weakest_segment":weakest["segment"],
            "weakest_status":weakest["segment_status"],
            "weakest_valid":weakest["full_valid"],
            "weakest_edge":weakest["full_edge"],
            "weakest_oos_edge":weakest["oos_edge"],
            "edge_spread":strongest["full_edge"]-weakest["full_edge"],
        })
    summary=pd.DataFrame(summary_rows).sort_values(["law_id","dimension"]) if summary_rows else pd.DataFrame()
    return detail, summary


def append_segmentation_report(path: Path, detail: pd.DataFrame, summary: pd.DataFrame) -> None:
    lines=[
        "",
        "# V9 — Law Segmentation Engine",
        "",
        "Segmentação exploratória das leis congeladas por uma dimensão de cada vez.",
        "Um segmento STRONGER não vira nova Market Law sem validação temporal dedicada.",
        "",
    ]
    if not summary.empty:
        lines += ["## Resumo de melhores e piores segmentos", "", summary.to_markdown(index=False), ""]
    if not detail.empty:
        show=detail.loc[detail["segment_status"].isin(["STRONGER","WEAKER"])].head(80)
        if not show.empty:
            cols=[c for c in ["law_id","dimension","segment","segment_status","full_valid","full_edge","full_edge_ci_low","oos_valid","oos_edge","segment_edge_delta"] if c in show.columns]
            lines += ["## Segmentos que mais alteraram o edge", "", show[cols].to_markdown(index=False), ""]
    with path.open("a",encoding="utf-8") as f:
        f.write("\n".join(lines))


# -----------------------------------------------------------------------------
# V10 — MARKET LAWS REGISTRY + RUNTIME MATCHER
# -----------------------------------------------------------------------------

def _registry_conditions(law_id: str) -> dict[str, Any]:
    common = {
        "LAW_0001A": {"level_attempt_side": "UP", "attempt_bucket": "FIRST_ATTEMPT", "failure_memory_bucket": "NO_RECENT_FAILURE", "mtf_bias": "DOWN", "mtf_alignment_bucket_in": ["MIXED", "STRONG", "FULL"]},
        "LAW_0001B": {"level_attempt_side": "DOWN", "attempt_bucket": "FIRST_ATTEMPT", "failure_memory_bucket": "NO_RECENT_FAILURE", "mtf_bias": "UP", "mtf_alignment_bucket_in": ["MIXED", "STRONG", "FULL"]},
        "LAW_0002A": {"level_attempt_side": "UP", "attempt_bucket": "FIRST_ATTEMPT", "failure_memory_bucket": "NO_RECENT_FAILURE", "mtf_bias": "DOWN", "mtf_alignment_bucket_in": ["MIXED", "STRONG", "FULL"], "event_breakout_up": True, "bars_since_false_break_between": [1, 3], "bars_since_sweep_between": [1, 3]},
        "LAW_0002B": {"level_attempt_side": "DOWN", "attempt_bucket": "FIRST_ATTEMPT", "failure_memory_bucket": "NO_RECENT_FAILURE", "mtf_bias": "UP", "mtf_alignment_bucket_in": ["MIXED", "STRONG", "FULL"], "event_breakout_down": True, "bars_since_false_break_between": [1, 3], "bars_since_sweep_between": [1, 3]},
        "LAW_0003A": {"level_attempt_side": "UP", "attempt_bucket": "SECOND_ATTEMPT", "failure_memory_bucket": "ONE_RECENT_FAILURE", "mtf_bias": "DOWN", "mtf_alignment_bucket_in": ["MIXED", "STRONG", "FULL"]},
        "LAW_0003B": {"level_attempt_side": "DOWN", "attempt_bucket": "SECOND_ATTEMPT", "failure_memory_bucket": "ONE_RECENT_FAILURE", "mtf_bias": "UP", "mtf_alignment_bucket_in": ["MIXED", "STRONG", "FULL"]},
    }
    return common.get(law_id, {})


def _law_tier(law_id: str, status: str) -> str:
    if law_id in {"LAW_0001A", "LAW_0001B", "LAW_0002A", "LAW_0002B"} and status == "VALIDATED":
        return "A"
    if law_id == "LAW_0003A" and status == "VALIDATED":
        return "B"
    return "C"


def _law_effect(side: str, tier: str) -> dict[str, Any]:
    opposite = "SELL_BREAKOUT" if side == "BUY" else "BUY_BREAKOUT"
    preferred = f"WAIT_FOR_{side}_CONFIRMATION"
    if tier == "A":
        return {"block_action": opposite, "preferred_response": preferred, "runtime_role": "GUARD"}
    if tier == "B":
        return {"block_action": None, "preferred_response": preferred, "runtime_role": "CONFIRMATION"}
    return {"block_action": None, "preferred_response": preferred, "runtime_role": "ADVISORY"}


def build_market_laws_registry(
    validation_summary: pd.DataFrame,
    law_segments: pd.DataFrame,
    symbol: str,
    anchor_tf: str,
) -> dict[str, Any]:
    """Cria a fonte oficial, versionada e auditável das Market Laws.

    Segmentos V9 permanecem moduladores. Apenas STRONGER/WEAKER com amostra e
    OOS suficientes são publicados para uso runtime.
    """
    laws=[]
    for _, row in validation_summary.sort_values("law_id").iterrows():
        lid=str(row["law_id"])
        status=str(row.get("status", "REJECTED"))
        tier=_law_tier(lid, status)
        mods=[]
        if not law_segments.empty:
            seg=law_segments.loc[
                law_segments["law_id"].eq(lid)
                & law_segments["segment_status"].isin(["STRONGER", "WEAKER"])
                & (pd.to_numeric(law_segments["full_valid"], errors="coerce") >= 80)
                & (pd.to_numeric(law_segments["oos_valid"], errors="coerce") >= 20)
            ].copy()
            for _, sr in seg.sort_values(["dimension", "segment"]).iterrows():
                delta=float(sr.get("segment_edge_delta", 0.0)) if pd.notna(sr.get("segment_edge_delta")) else 0.0
                adjustment=float(np.clip(delta * 35.0, -18.0, 18.0))
                mods.append({
                    "dimension": str(sr["dimension"]),
                    "segment": str(sr["segment"]),
                    "status": str(sr["segment_status"]),
                    "score_adjustment": round(adjustment, 3),
                    "full_valid": int(sr.get("full_valid", 0)),
                    "full_edge": jclean(sr.get("full_edge")),
                    "oos_valid": int(sr.get("oos_valid", 0)),
                    "oos_edge": jclean(sr.get("oos_edge")),
                })
        side=str(row["side"])
        laws.append({
            "law_id": lid,
            "name": str(row["law_name"]),
            "hypothesis": str(row.get("hypothesis", "")),
            "symbol": symbol,
            "anchor_tf": anchor_tf,
            "status": "VALIDATED_LOCAL" if status == "VALIDATED" else status,
            "validation_status": status,
            "tier": tier,
            "side": side,
            "conditions": _registry_conditions(lid),
            "effect": _law_effect(side, tier),
            "metrics": {
                "sample_size": int(row.get("full_valid", 0)),
                "full_edge": jclean(row.get("full_edge")),
                "full_ci_low": jclean(row.get("full_ci_low")),
                "full_ci_high": jclean(row.get("full_ci_high")),
                "is_edge": jclean(row.get("is_edge")),
                "oos_edge": jclean(row.get("oos_edge")),
                "recent_edge": jclean(row.get("recent_edge")),
                "oos_valid": int(row.get("oos_valid", 0)),
                "positive_year_ratio": jclean(row.get("positive_year_ratio")),
                "positive_window_ratio": jclean(row.get("positive_window_ratio")),
            },
            "segment_modulators": mods,
        })
    return {
        "registry_schema_version": "1.1.0",
        "engine_version": "V10.1",
        "validation_scope": "VALIDATED_LOCAL",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "anchor_tf": anchor_tf,
        "laws": laws,
    }


def _row_bool(row: Mapping[str, Any], key: str) -> bool:
    value=row.get(key, False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "sim"}
    return bool(value) if pd.notna(value) else False


def _row_num(row: Mapping[str, Any], key: str) -> float:
    try:
        return float(row.get(key, np.nan))
    except (TypeError, ValueError):
        return np.nan


def _evaluate_conditions(row: Mapping[str, Any], conditions: Mapping[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    """Avalia todas as condições e devolve diagnóstico auditável por campo."""
    reasons: list[str] = []
    checks: dict[str, Any] = {}
    all_ok = True
    for key, expected in conditions.items():
        if key.endswith("_in"):
            field = key[:-3]
            actual = str(row.get(field, "UNKNOWN"))
            expected_values = [str(x) for x in expected]
            ok = actual in set(expected_values)
            expected_display: Any = expected_values
        elif key.endswith("_between"):
            field = key[:-8]
            actual = _row_num(row, field)
            expected_display = [float(expected[0]), float(expected[1])]
            ok = np.isfinite(actual) and expected_display[0] <= actual <= expected_display[1]
        elif isinstance(expected, bool):
            field = key
            actual = _row_bool(row, key)
            expected_display = expected
            ok = actual is expected
        else:
            field = key
            actual = str(row.get(key, "UNKNOWN"))
            expected_display = str(expected)
            ok = actual == expected_display
        checks[key] = {
            "field": field,
            "expected": expected_display,
            "actual": jclean(actual),
            "passed": bool(ok),
        }
        if ok:
            reasons.append(f"{key}={expected_display}")
        else:
            all_ok = False
    return all_ok, reasons, checks


def _matches_conditions(row: Mapping[str, Any], conditions: Mapping[str, Any]) -> tuple[bool, list[str]]:
    ok, reasons, _ = _evaluate_conditions(row, conditions)
    return ok, reasons


def _row_segment_values(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "HOUR_BRT": str(int(_row_num(row, "hour"))) if np.isfinite(_row_num(row, "hour")) else "UNKNOWN",
        "SESSION_BRT": str(row.get("session_brt", "UNKNOWN")),
        "WEEKDAY": str(row.get("weekday", "UNKNOWN")),
        "ENERGY": str(row.get("energy_bucket", "UNKNOWN")),
        "HTF_LOCATION": str(row.get("htf_location_group", row.get("htf_location_bias", "UNKNOWN"))),
        "BREAKOUT_ALIGNMENT": str(row.get("breakout_alignment_group", row.get("breakout_location_alignment", "UNKNOWN"))),
        "LEVEL_PROXIMITY": str(row.get("level_proximity_group", "UNKNOWN")),
    }


def _modulator_evidence_signature(mod: Mapping[str, Any]) -> tuple[Any, ...]:
    """Assinatura usada para impedir dupla contagem da mesma evidência estatística."""
    def r(v: Any) -> Any:
        try:
            return round(float(v), 9)
        except (TypeError, ValueError):
            return v
    return (
        str(mod.get("status")),
        int(mod.get("full_valid", 0) or 0),
        r(mod.get("full_edge")),
        int(mod.get("oos_valid", 0) or 0),
        r(mod.get("oos_edge")),
    )


def _deduplicate_applied_modulators(applied: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Mantém apenas o ajuste de maior magnitude para evidências idênticas."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in applied:
        groups.setdefault(_modulator_evidence_signature(item), []).append(item)
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for items in groups.values():
        selected = max(items, key=lambda x: abs(float(x.get("score_adjustment", 0.0))))
        kept.append(selected)
        for item in items:
            if item is selected:
                continue
            suppressed.append({**item, "suppression_reason": "DUPLICATE_STATISTICAL_EVIDENCE", "kept_dimension": selected.get("dimension")})
    return kept, suppressed


def match_market_laws(
    row: Mapping[str, Any],
    registry: Mapping[str, Any],
    include_diagnostics: bool = True,
) -> dict[str, Any]:
    """Compara um estado de mercado com o registry sem usar LLM.

    V10.1:
    - avalia todas as condições por lei;
    - explica por que cada lei casou ou falhou;
    - deduplica moduladores com evidência estatística idêntica;
    - mantém o resultado determinístico e auditável.
    """
    segments = _row_segment_values(row)
    matched: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    blocked: set[str] = set()
    buy_score = 0.0
    sell_score = 0.0
    for law in registry.get("laws", []):
        if law.get("validation_status") not in {"VALIDATED", "PROVISIONAL"}:
            continue
        ok, reasons, checks = _evaluate_conditions(row, law.get("conditions", {}))
        failed_conditions = [k for k, v in checks.items() if not v.get("passed")]
        diagnostic = {
            "law_id": law.get("law_id"),
            "name": law.get("name"),
            "side": law.get("side"),
            "tier": law.get("tier"),
            "matched": bool(ok),
            "passed_conditions": len(checks) - len(failed_conditions),
            "total_conditions": len(checks),
            "failed_conditions": failed_conditions,
            "condition_checks": checks,
        }
        diagnostics.append(diagnostic)
        if not ok:
            continue

        metrics = law.get("metrics", {})
        edge = float(metrics.get("full_edge") or 0.0)
        base_score = float(np.clip(45.0 + 55.0 * edge, 0.0, 100.0))
        tier_adjustment = 5.0 if law.get("tier") == "A" else -12.0 if law.get("tier") == "C" else 0.0
        raw_applied: list[dict[str, Any]] = []
        for mod in law.get("segment_modulators", []):
            if segments.get(str(mod.get("dimension"))) == str(mod.get("segment")):
                raw_applied.append({
                    "dimension": mod.get("dimension"),
                    "segment": mod.get("segment"),
                    "status": mod.get("status"),
                    "score_adjustment": float(mod.get("score_adjustment", 0.0)),
                    "full_valid": mod.get("full_valid"),
                    "full_edge": mod.get("full_edge"),
                    "oos_valid": mod.get("oos_valid"),
                    "oos_edge": mod.get("oos_edge"),
                })
        applied, suppressed = _deduplicate_applied_modulators(raw_applied)
        modulator_adjustment = sum(float(x.get("score_adjustment", 0.0)) for x in applied)
        score = float(np.clip(base_score + tier_adjustment + modulator_adjustment, 0.0, 100.0))
        side = str(law.get("side"))
        if side == "BUY":
            buy_score += score
        elif side == "SELL":
            sell_score += score
        effect = law.get("effect", {})
        if law.get("tier") == "A" and effect.get("block_action"):
            blocked.add(str(effect["block_action"]))
        matched.append({
            "law_id": law.get("law_id"),
            "name": law.get("name"),
            "side": side,
            "tier": law.get("tier"),
            "status": law.get("status"),
            "score": round(score, 3),
            "score_components": {
                "base_score": round(base_score, 3),
                "tier_adjustment": round(tier_adjustment, 3),
                "modulator_adjustment": round(modulator_adjustment, 3),
            },
            "runtime_role": effect.get("runtime_role"),
            "preferred_response": effect.get("preferred_response"),
            "block_action": effect.get("block_action"),
            "matched_conditions": reasons,
            "condition_checks": checks,
            "applied_modulators": applied,
            "suppressed_duplicate_modulators": suppressed,
            "metrics": metrics,
        })

    matched.sort(key=lambda x: (x["score"], x["tier"] == "A"), reverse=True)
    if not matched:
        action = "NO_MATCH"
        supporting = "NONE"
        confidence = "NONE"
    elif buy_score > 0 and sell_score > 0:
        diff = buy_score - sell_score
        if abs(diff) < 15:
            action = "WAIT_CONFLICT"
            supporting = "MIXED"
        else:
            supporting = "BUY" if diff > 0 else "SELL"
            action = f"WAIT_FOR_{supporting}_CONFIRMATION"
        confidence = "MEDIUM"
    else:
        supporting = "BUY" if buy_score > sell_score else "SELL"
        top = max((m["score"] for m in matched if m["side"] == supporting), default=0)
        action = f"WAIT_FOR_{supporting}_CONFIRMATION"
        confidence = "HIGH" if top >= 75 else "MEDIUM" if top >= 55 else "LOW"

    result = {
        "schema_version": "1.1.0",
        "engine_version": "V10.1",
        "evaluated_at": jclean(row.get("event_time")),
        "symbol": registry.get("symbol"),
        "anchor_tf": registry.get("anchor_tf"),
        "matched_laws": matched,
        "matched_count": len(matched),
        "supporting_side": supporting,
        "buy_score": round(buy_score, 3),
        "sell_score": round(sell_score, 3),
        "blocked_actions": sorted(blocked),
        "chronos_action": action,
        "confidence": confidence,
        "current_segments": segments,
        "guard_note": "Lei de devolução bloqueia perseguição incompatível; entrada oposta ainda exige confirmação do preço.",
    }
    if include_diagnostics:
        result["law_diagnostics"] = diagnostics
        result["diagnostic_summary"] = {
            "laws_evaluated": len(diagnostics),
            "laws_matched": len(matched),
            "laws_not_matched": len(diagnostics) - len(matched),
        }
    return result


def _find_runtime_state(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Localiza o bloco de estado Chronos em payloads diretos ou aninhados."""
    required_any = {"attempt_bucket", "level_attempt_side", "mtf_bias", "event_breakout_up", "event_breakout_down"}
    preferred_keys = ("chronos_state", "runtime_state", "current_state", "market_state", "chronos_features")
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    if required_any.intersection(payload.keys()):
        return payload
    queue = [v for v in payload.values() if isinstance(v, Mapping)]
    while queue:
        candidate = queue.pop(0)
        if required_any.intersection(candidate.keys()):
            return candidate
        queue.extend(v for v in candidate.values() if isinstance(v, Mapping))
    raise ValueError(
        "Não encontrei estado runtime compatível. Forneça um objeto direto ou um bloco "
        "chronos_state/runtime_state com campos como attempt_bucket, level_attempt_side e mtf_bias."
    )


def run_runtime(args: argparse.Namespace) -> None:
    registry_path = Path(args.registry)
    state_path = Path(args.state_json)
    output_path = Path(args.runtime_output)
    if not registry_path.exists():
        raise FileNotFoundError(f"Registry não encontrado: {registry_path}")
    if not state_path.exists():
        raise FileNotFoundError(f"Estado runtime não encontrado: {state_path}")
    registry = load_json(registry_path)
    payload = load_json(state_path)
    state = dict(_find_runtime_state(payload))
    result = match_market_laws(state, registry, include_diagnostics=not args.no_diagnostics)
    save_json(output_path, result)
    log("OK runtime")
    print(json.dumps(jclean({
        "mode": "runtime",
        "registry": str(registry_path),
        "state_json": str(state_path),
        "output": str(output_path),
        "matched_laws": result.get("matched_count", 0),
        "runtime_action": result.get("chronos_action"),
        "supporting_side": result.get("supporting_side"),
        "blocked_actions": result.get("blocked_actions", []),
    }), ensure_ascii=False, indent=2))


def append_registry_report(path: Path, registry: Mapping[str, Any], runtime: Mapping[str, Any]) -> None:
    lines=["", "# V10.1 — Market Laws Registry + Runtime Hardening", "",
           f"Registry: {len(registry.get('laws', []))} leis publicadas.",
           f"Último estado: {runtime.get('matched_count', 0)} leis correspondentes; ação Chronos: `{runtime.get('chronos_action')}`.", ""]
    rows=[]
    for law in registry.get("laws", []):
        rows.append({"law_id":law.get("law_id"),"tier":law.get("tier"),"status":law.get("status"),"side":law.get("side"),"sample":law.get("metrics",{}).get("sample_size"),"edge":law.get("metrics",{}).get("full_edge"),"oos_edge":law.get("metrics",{}).get("oos_edge"),"modulators":len(law.get("segment_modulators",[]))})
    if rows:
        lines += [pd.DataFrame(rows).to_markdown(index=False), ""]
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


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
    df = add_state_dna_features(df)
    df = add_setup_genome_features(df)
    df = add_htf_location_features(df, anchor_tf)
    df = add_sequence_dna_features(df, anchor_tf)
    df = add_memory_engine_features(df, anchor_tf)

    behavior = summarize_behavior_map(df, min_bars=args.min_bars)
    dna = summarize_dna_rank(df, min_bars=args.min_bars)
    contexts = summarize_context_scores(df, min_bars=args.min_bars)
    events = summarize_event_edges(df, min_bars=args.min_bars)
    level_playbook = summarize_level_playbook(df, min_bars=args.min_bars)
    level_playbook_best = summarize_level_playbook_best(level_playbook)
    state_dna_macro = summarize_state_dna(df, "state_dna_macro", min_bars=args.min_bars)
    state_dna_operational = summarize_state_dna(df, "state_dna_operational", min_bars=args.min_bars)
    state_dna_granular = summarize_state_dna(df, "state_dna_granular", min_bars=max(args.min_bars, 150))
    state_playbook = summarize_state_playbook(df, min_bars=args.min_bars)
    state_transitions = summarize_state_transitions_dna(df, "state_dna_macro", min_count=30)
    setup_genome_macro = summarize_setup_genome(df, "setup_genome_macro", min_bars=args.min_bars)
    setup_genome_time = summarize_setup_genome(df, "setup_genome_time", min_bars=args.min_bars)
    setup_genome_granular = summarize_setup_genome(df, "setup_genome_granular", min_bars=max(args.min_bars, 150))
    setup_genome_playbook = summarize_setup_genome_playbook(df, min_bars=args.min_bars)
    htf_location_dna = summarize_htf_location_dna(df, "htf_location_dna", min_bars=args.min_bars)
    htf_setup_genome = summarize_htf_location_dna(df, "htf_setup_genome", min_bars=args.min_bars)
    htf_setup_genome_time = summarize_htf_location_dna(df, "htf_setup_genome_time", min_bars=max(args.min_bars, 150))
    htf_breakout_alignment = summarize_htf_breakout_alignment(df, min_bars=args.min_bars)
    sequence_dna_macro = summarize_sequence_dna(df, "sequence_dna_macro", min_bars=args.min_bars)
    sequence_dna_setup = summarize_sequence_dna(df, "sequence_dna_setup", min_bars=args.min_bars)
    sequence_dna_time = summarize_sequence_dna(df, "sequence_dna_time", min_bars=max(args.min_bars, 150))
    sequence_regimes = summarize_sequence_regimes(df, min_bars=args.min_bars)
    memory_dna = summarize_memory_groups(df, "memory_dna", min_bars=args.min_bars)
    memory_setup = summarize_memory_groups(df, "memory_setup", min_bars=args.min_bars)
    memory_attempts = summarize_memory_attempts(df, min_bars=args.min_bars)
    memory_playbook = summarize_memory_playbook(memory_dna, memory_setup)
    validation_summary, validation_splits, validation_yearly, validation_rolling = validate_market_laws(df)
    law_segments, law_segment_summary = segment_validated_laws(df, validation_summary, min_segment=max(40, args.min_segment // 3))
    registry = build_market_laws_registry(validation_summary, law_segments, symbol, anchor_tf)
    runtime_df = add_law_segmentation_features(df)
    latest_row = runtime_df.sort_values("event_time").iloc[-1].to_dict()
    chronos_runtime = match_market_laws(latest_row, registry)

    behavior.to_csv(out_root / "engine_behavior_map.csv", index=False, encoding="utf-8-sig")
    dna.to_csv(out_root / "engine_dna_rank.csv", index=False, encoding="utf-8-sig")
    contexts.to_csv(out_root / "engine_context_scores.csv", index=False, encoding="utf-8-sig")
    events.to_csv(out_root / "engine_event_edges.csv", index=False, encoding="utf-8-sig")
    level_playbook.to_csv(out_root / "engine_level_playbook.csv", index=False, encoding="utf-8-sig")
    level_playbook_best.to_csv(out_root / "engine_level_playbook_best.csv", index=False, encoding="utf-8-sig")
    state_dna_macro.to_csv(out_root / "engine_state_dna_macro.csv", index=False, encoding="utf-8-sig")
    state_dna_operational.to_csv(out_root / "engine_state_dna_operational.csv", index=False, encoding="utf-8-sig")
    state_dna_granular.to_csv(out_root / "engine_state_dna_granular.csv", index=False, encoding="utf-8-sig")
    state_playbook.to_csv(out_root / "engine_state_playbook.csv", index=False, encoding="utf-8-sig")
    state_transitions.to_csv(out_root / "engine_state_transitions.csv", index=False, encoding="utf-8-sig")
    setup_genome_macro.to_csv(out_root / "engine_setup_genome_macro.csv", index=False, encoding="utf-8-sig")
    setup_genome_time.to_csv(out_root / "engine_setup_genome_time.csv", index=False, encoding="utf-8-sig")
    setup_genome_granular.to_csv(out_root / "engine_setup_genome_granular.csv", index=False, encoding="utf-8-sig")
    setup_genome_playbook.to_csv(out_root / "engine_setup_genome_playbook.csv", index=False, encoding="utf-8-sig")
    htf_location_dna.to_csv(out_root / "engine_htf_location_dna.csv", index=False, encoding="utf-8-sig")
    htf_setup_genome.to_csv(out_root / "engine_htf_setup_genome.csv", index=False, encoding="utf-8-sig")
    htf_setup_genome_time.to_csv(out_root / "engine_htf_setup_genome_time.csv", index=False, encoding="utf-8-sig")
    htf_breakout_alignment.to_csv(out_root / "engine_htf_breakout_alignment.csv", index=False, encoding="utf-8-sig")
    sequence_dna_macro.to_csv(out_root / "engine_sequence_dna_macro.csv", index=False, encoding="utf-8-sig")
    sequence_dna_setup.to_csv(out_root / "engine_sequence_dna_setup.csv", index=False, encoding="utf-8-sig")
    sequence_dna_time.to_csv(out_root / "engine_sequence_dna_time.csv", index=False, encoding="utf-8-sig")
    sequence_regimes.to_csv(out_root / "engine_sequence_regimes.csv", index=False, encoding="utf-8-sig")
    memory_dna.to_csv(out_root / "engine_memory_dna.csv", index=False, encoding="utf-8-sig")
    memory_setup.to_csv(out_root / "engine_memory_setup.csv", index=False, encoding="utf-8-sig")
    memory_attempts.to_csv(out_root / "engine_memory_attempts.csv", index=False, encoding="utf-8-sig")
    memory_playbook.to_csv(out_root / "engine_memory_playbook.csv", index=False, encoding="utf-8-sig")
    validation_summary.to_csv(out_root / "engine_validation_laws.csv", index=False, encoding="utf-8-sig")
    validation_splits.to_csv(out_root / "engine_validation_splits.csv", index=False, encoding="utf-8-sig")
    validation_yearly.to_csv(out_root / "engine_validation_yearly.csv", index=False, encoding="utf-8-sig")
    validation_rolling.to_csv(out_root / "engine_validation_rolling.csv", index=False, encoding="utf-8-sig")
    law_segments.to_csv(out_root / "engine_law_segments.csv", index=False, encoding="utf-8-sig")
    law_segment_summary.to_csv(out_root / "engine_law_segment_summary.csv", index=False, encoding="utf-8-sig")
    laws_root = out_root.parent / "laws"
    laws_root.mkdir(parents=True, exist_ok=True)
    save_json(laws_root / "market_laws_registry.json", registry)
    save_json(out_root / "chronos_intelligence_latest.json", chronos_runtime)

    detail_cols = [
        "event_time", "hour", "time_slot", "anchor_direction", "anchor_market_state", "anchor_vol_bucket",
        "energy_score", "energy_bucket", "mtf_alignment_score", "mtf_alignment_bucket", "mtf_bias",
        "event_name", "nearest_resistance_atr", "nearest_support_atr", "resistance_bucket", "support_bucket",
        "h3_continues", "h6_continues", "h12_continues", "h6_pullback_0p50", "h12_reaches_1p00",
        "rr_t1p0_s0p5_h12", "buy_t1p0_s0p5_h12", "sell_t1p0_s0p5_h12",
        "state_id_macro", "state_id_operational", "state_id_granular",
        "state_dna_macro", "state_dna_operational", "state_dna_granular",
        "setup_id_macro", "setup_id_time", "setup_id_granular",
        "setup_genome_macro", "setup_genome_time", "setup_genome_granular",
        "htf_location_bias", "breakout_location_alignment", "htf_location_dna",
        "htf_setup_genome", "htf_setup_genome_time",
        "sequence_regime", "breakout_attempt_bucket",
        "sequence_dna_macro", "sequence_dna_setup", "sequence_dna_time",
        "dir_seq_3", "dir_seq_5", "event_seq_3", "event_seq_5",
        "level_attempt_start", "level_attempt_side", "level_cycle_id", "level_price",
        "level_attempt_number", "level_attempt_cluster_length", "level_reset_reason",
        "level_age_bars", "distance_from_level_atr", "accepted_breakout",
        "false_break_episode_start", "sweep_episode_start",
        "failure_episode_start", "failure_episode_side", "failure_episode_id",
        "failures_on_current_level", "bars_since_level_failure", "since_level_failure_bucket",
        "breakout_episode_start", "breakout_episode_side", "breakout_episode_id",
        "breakout_cluster_length", "attempt_number_48", "attempt_bucket",
        "bars_since_breakout_episode", "bars_since_false_break", "bars_since_sweep",
        "attempts_since_false_break", "attempts_since_sweep",
        "attempt_energy_delta", "attempt_range_delta", "attempt_quality",
        "recent_failure_count_24", "failure_memory_bucket", "attempts_since_level_failure", "memory_condition",
        "memory_id", "memory_setup_id", "memory_dna", "memory_setup",
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
        state_playbook.to_excel(writer, sheet_name="state_playbook", index=False)
        state_dna_macro.to_excel(writer, sheet_name="state_dna_macro", index=False)
        state_dna_operational.to_excel(writer, sheet_name="state_dna_operational", index=False)
        state_transitions.to_excel(writer, sheet_name="state_transitions", index=False)
        setup_genome_playbook.to_excel(writer, sheet_name="setup_genome", index=False)
        setup_genome_macro.to_excel(writer, sheet_name="setup_macro", index=False)
        setup_genome_time.to_excel(writer, sheet_name="setup_time", index=False)
        htf_location_dna.to_excel(writer, sheet_name="htf_location", index=False)
        htf_setup_genome.to_excel(writer, sheet_name="htf_setup", index=False)
        htf_breakout_alignment.to_excel(writer, sheet_name="htf_breakout", index=False)
        sequence_dna_macro.to_excel(writer, sheet_name="seq_macro", index=False)
        sequence_dna_setup.to_excel(writer, sheet_name="seq_setup", index=False)
        sequence_regimes.to_excel(writer, sheet_name="seq_regimes", index=False)
        memory_dna.to_excel(writer, sheet_name="memory_dna", index=False)
        memory_setup.to_excel(writer, sheet_name="memory_setup", index=False)
        memory_attempts.to_excel(writer, sheet_name="memory_attempts", index=False)
        memory_playbook.to_excel(writer, sheet_name="memory_playbook", index=False)
        validation_summary.to_excel(writer, sheet_name="validation_laws", index=False)
        validation_splits.to_excel(writer, sheet_name="validation_splits", index=False)
        validation_yearly.to_excel(writer, sheet_name="validation_yearly", index=False)
        validation_rolling.to_excel(writer, sheet_name="validation_rolling", index=False)
        law_segments.to_excel(writer, sheet_name="law_segments", index=False)
        law_segment_summary.to_excel(writer, sheet_name="law_segment_summary", index=False)

    metadata = {
        "script": "market_chronos_engine_v10_1.py",
        "validation_marker": "MARKET_CHRONOS_ENGINE_V10_1_RUNTIME_HARDENING",
        "symbol": symbol,
        "anchor_tf": anchor_tf,
        "rows": len(df),
        "input": str(input_path),
        "output": str(out_root),
        "min_bars": args.min_bars,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    save_json(out_root / "metadata.json", metadata)
    report_path = out_root / "chronos_engine_report.md"
    write_report(report_path, symbol, anchor_tf, metadata, behavior, dna, contexts, events, level_playbook_best, state_playbook, state_transitions, setup_genome_playbook, htf_location_dna, htf_breakout_alignment, sequence_regimes, sequence_dna_setup)
    append_memory_report(report_path, memory_dna, memory_attempts, memory_playbook)
    append_validation_report(report_path, validation_summary)
    append_segmentation_report(report_path, law_segments, law_segment_summary)
    append_registry_report(report_path, registry, chronos_runtime)

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
        "state_dna_macro": len(state_dna_macro),
        "state_dna_operational": len(state_dna_operational),
        "state_dna_granular": len(state_dna_granular),
        "state_transitions": len(state_transitions),
        "setup_genome_macro": len(setup_genome_macro),
        "setup_genome_time": len(setup_genome_time),
        "setup_genome_granular": len(setup_genome_granular),
        "htf_location_dna": len(htf_location_dna),
        "htf_setup_genome": len(htf_setup_genome),
        "htf_setup_genome_time": len(htf_setup_genome_time),
        "htf_breakout_alignment": len(htf_breakout_alignment),
        "sequence_dna_macro": len(sequence_dna_macro),
        "sequence_dna_setup": len(sequence_dna_setup),
        "sequence_dna_time": len(sequence_dna_time),
        "sequence_regimes": len(sequence_regimes),
        "memory_dna": len(memory_dna),
        "memory_setup": len(memory_setup),
        "memory_attempts": len(memory_attempts),
        "memory_playbook": len(memory_playbook),
        "validation_laws": len(validation_summary),
        "validation_validated": int(validation_summary["status"].eq("VALIDATED").sum()) if not validation_summary.empty else 0,
        "validation_provisional": int(validation_summary["status"].eq("PROVISIONAL").sum()) if not validation_summary.empty else 0,
        "law_segments": len(law_segments),
        "law_segments_stronger": int(law_segments["segment_status"].eq("STRONGER").sum()) if not law_segments.empty else 0,
        "law_segments_weaker": int(law_segments["segment_status"].eq("WEAKER").sum()) if not law_segments.empty else 0,
        "registry_laws": len(registry.get("laws", [])),
        "runtime_matched_laws": chronos_runtime.get("matched_count", 0),
        "runtime_action": chronos_runtime.get("chronos_action"),
        "registry": str(laws_root / "market_laws_registry.json"),
        "chronos_intelligence_latest": str(out_root / "chronos_intelligence_latest.json"),
    }), ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Market Chronos Engine V10.1 — Runtime Hardening")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.add_argument("--input", default=DEFAULT_INPUT)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--min-bars", type=int, default=120)
    p.add_argument(
        "--min-segment",
        type=int,
        default=120,
        help=(
            "Amostra-base para segmentacao das leis. O motor usa pelo menos 40 barras "
            "por segmento (default efetivo: max(40, min_segment/3))."
        ),
    )
    p.add_argument("--runtime", action="store_true", help="Executa apenas o matcher leve, sem recalcular a pesquisa.")
    p.add_argument("--registry", default="data/market_chronos/GOLD/laws/market_laws_registry.json", help="Registry JSON usado no modo runtime.")
    p.add_argument("--state-json", default="data/context/GOLD_chronos_state.json", help="JSON contendo o estado atual ou bloco chronos_state.")
    p.add_argument("--runtime-output", default="data/context/GOLD_chronos_intelligence.json", help="Saída JSON do modo runtime.")
    p.add_argument("--no-diagnostics", action="store_true", help="Omite diagnóstico das leis não correspondentes no modo runtime.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.runtime:
        run_runtime(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
