#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Chronos Fusion — motor único de pesquisa em camadas.

Lê:
  data/market_chronos/GOLD/lab/GOLD_M5_mtf_research_base.parquet

Gera poucos arquivos:
  data/market_chronos/GOLD/fusion/
    chronos_fusion_report.md
    GOLD_chronos_fusion.xlsx
    fusion_context_scores.csv
    fusion_event_edges.csv
    fusion_detail.parquet
    metadata.json

Camadas:
  1) Time
  2) Energy
  3) Continuation
  4) Pullback
  5) Breakout
  6) Levels
  7) Fusion Score

Uso:
  python tools/market_chronos_fusion.py --symbol GOLD --anchor-tf M5
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_INPUT = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/fusion"


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
        value = float(v)
        return None if not math.isfinite(value) else round(value, 6)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jclean(data), ensure_ascii=False, indent=2), encoding="utf-8")


def fcol(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(default, index=df.index, dtype=float)


def scol(df: pd.DataFrame, col: str, default: str = "UNKNOWN") -> pd.Series:
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
    return s.rank(pct=True).fillna(0.5)


def add_core_features(df: pd.DataFrame, anchor_tf: str) -> pd.DataFrame:
    out = df.copy()
    p = f"{anchor_tf}_"

    # Tempo
    if f"{p}hour_brt" not in out.columns:
        if "event_time" in out.columns:
            out[f"{p}hour_brt"] = pd.to_datetime(out["event_time"]).dt.hour
        else:
            out[f"{p}hour_brt"] = np.nan

    if f"{p}time_slot" not in out.columns and "event_time" in out.columns:
        out[f"{p}time_slot"] = pd.to_datetime(out["event_time"]).dt.strftime("%H:%M")

    # Direção e candle
    out["anchor_direction"] = scol(out, f"{p}direction")
    out["anchor_is_up"] = out["anchor_direction"].eq("UP")
    out["anchor_is_down"] = out["anchor_direction"].eq("DOWN")

    out["anchor_range_usd"] = fcol(out, f"{p}range_usd", fcol(out, f"{p}high") - fcol(out, f"{p}low"))
    out["anchor_net_usd"] = fcol(out, f"{p}net_usd", fcol(out, f"{p}close") - fcol(out, f"{p}open"))
    out["anchor_abs_net_usd"] = out["anchor_net_usd"].abs()
    out["anchor_atr"] = fcol(out, f"{p}ATR")
    out["anchor_range_atr"] = fcol(out, f"{p}range_atr", out["anchor_range_usd"] / out["anchor_atr"].replace(0, np.nan))
    out["anchor_body_atr"] = fcol(out, f"{p}body_atr", out["anchor_abs_net_usd"] / out["anchor_atr"].replace(0, np.nan))
    out["anchor_vol_ratio"] = fcol(out, f"{p}vol_ratio")
    out["anchor_close_pos"] = fcol(out, f"{p}close_pos")
    out["anchor_market_state"] = scol(out, f"{p}market_state")
    out["anchor_vol_bucket"] = scol(out, f"{p}vol_bucket")
    out["anchor_range_bucket"] = scol(out, f"{p}range_bucket")
    out["anchor_body_bucket"] = scol(out, f"{p}body_bucket")

    # Eventos
    out["event_breakout_up"] = bcol(out, f"{p}breakout_up")
    out["event_breakout_down"] = bcol(out, f"{p}breakout_down")
    out["event_breakout"] = out["event_breakout_up"] | out["event_breakout_down"]
    out["event_false_breakout"] = bcol(out, f"{p}false_breakout_up") | bcol(out, f"{p}false_breakout_down")
    out["event_sweep"] = bcol(out, f"{p}sweep_high") | bcol(out, f"{p}sweep_low")
    out["event_compression"] = bcol(out, f"{p}compression_flag")
    out["event_expansion"] = bcol(out, f"{p}expansion_flag")

    # Alinhamento MTF simples
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
    ).astype("object").fillna("UNKNOWN")

    # Energia do mercado: escala 0-100 por percentile interno
    vol_p = pct_rank(out["anchor_vol_ratio"].clip(lower=0, upper=5))
    range_p = pct_rank(out["anchor_range_atr"].clip(lower=0, upper=5))
    body_p = pct_rank(out["anchor_body_atr"].clip(lower=0, upper=3))
    adx_source = fcol(out, "H1_ADX", fcol(out, "M15_ADX", np.nan))
    adx_p = pct_rank(adx_source.clip(lower=0, upper=80)) if adx_source.notna().sum() > 100 else pd.Series(0.5, index=out.index)
    expansion_bonus = out["event_expansion"].astype(float) * 0.10
    compression_bonus = out["event_compression"].astype(float) * 0.05

    out["energy_score"] = (
        100 * (
            0.30 * vol_p
            + 0.30 * range_p
            + 0.20 * body_p
            + 0.15 * adx_p
            + expansion_bonus
            + compression_bonus
        )
    ).clip(0, 100)

    out["energy_bucket"] = pd.cut(
        out["energy_score"],
        [-np.inf, 20, 40, 60, 80, np.inf],
        labels=["VERY_LOW", "LOW", "MEDIUM", "HIGH", "EXTREME"],
    ).astype("object").fillna("UNKNOWN")

    # Proxies de distância de nível
    high_dist_candidates = []
    low_dist_candidates = []
    for c in (f"{p}dist_prev_high_atr", f"{p}dist_donchian_high20_atr", f"{p}dist_bb_high_atr"):
        if c in out.columns:
            high_dist_candidates.append(fcol(out, c).abs())
    for c in (f"{p}dist_prev_low_atr", f"{p}dist_donchian_low20_atr", f"{p}dist_bb_low_atr"):
        if c in out.columns:
            low_dist_candidates.append(fcol(out, c).abs())

    if high_dist_candidates:
        out["nearest_resistance_atr"] = pd.concat(high_dist_candidates, axis=1).min(axis=1)
    else:
        out["nearest_resistance_atr"] = (fcol(out, f"{p}high") - fcol(out, f"{p}close")).abs() / out["anchor_atr"].replace(0, np.nan)

    if low_dist_candidates:
        out["nearest_support_atr"] = pd.concat(low_dist_candidates, axis=1).min(axis=1)
    else:
        out["nearest_support_atr"] = (fcol(out, f"{p}close") - fcol(out, f"{p}low")).abs() / out["anchor_atr"].replace(0, np.nan)

    def dist_bucket(s: pd.Series) -> pd.Series:
        return pd.cut(
            s,
            [-np.inf, 0.15, 0.35, 0.75, 1.5, np.inf],
            labels=["TOUCHING", "VERY_NEAR", "NEAR", "FAR", "VERY_FAR"],
        ).astype("object").fillna("UNKNOWN")

    out["resistance_bucket"] = dist_bucket(out["nearest_resistance_atr"])
    out["support_bucket"] = dist_bucket(out["nearest_support_atr"])

    return out


def add_future_simple_outcomes(df: pd.DataFrame, anchor_tf: str, horizons: list[int]) -> pd.DataFrame:
    out = df.copy()
    p = f"{anchor_tf}_"

    close = fcol(out, f"{p}close").to_numpy(float)
    high = fcol(out, f"{p}high").to_numpy(float)
    low = fcol(out, f"{p}low").to_numpy(float)
    open_ = fcol(out, f"{p}open").to_numpy(float)
    atr = out["anchor_atr"].replace(0, np.nan).to_numpy(float)
    direction = out["anchor_direction"].to_numpy(object)

    n = len(out)
    for h in horizons:
        f_close = np.roll(close, -h)
        f_close[-h:] = np.nan

        ret = f_close - close
        ret_atr = ret / atr

        future_highs = np.vstack([np.roll(high, -i) for i in range(1, h + 1)])
        future_lows = np.vstack([np.roll(low, -i) for i in range(1, h + 1)])
        if h > 0:
            for i in range(1, h + 1):
                future_highs[i - 1, -i:] = np.nan
                future_lows[i - 1, -i:] = np.nan

        max_fav_up = np.nanmax(future_highs, axis=0) - close
        max_adv_up = close - np.nanmin(future_lows, axis=0)
        max_fav_down = close - np.nanmin(future_lows, axis=0)
        max_adv_down = np.nanmax(future_highs, axis=0) - close

        fav = np.where(direction == "UP", max_fav_up, np.where(direction == "DOWN", max_fav_down, np.nan))
        adv = np.where(direction == "UP", max_adv_up, np.where(direction == "DOWN", max_adv_down, np.nan))

        out[f"h{h}_ret_atr"] = ret_atr
        out[f"h{h}_abs_ret_atr"] = np.abs(ret_atr)
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


def first_touch_for_rr(df: pd.DataFrame, anchor_tf: str, target_atr: float, stop_atr: float, horizon: int) -> pd.Series:
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
    combos = [
        (0.5, 0.25, 6),
        (1.0, 0.5, 12),
        (1.5, 0.75, 24),
        (2.0, 1.0, 24),
    ]
    for target, stop, horizon in combos:
        suffix = f"t{str(target).replace('.', 'p')}_s{str(stop).replace('.', 'p')}_h{horizon}"
        out[f"rr_{suffix}"] = first_touch_for_rr(out, anchor_tf, target, stop, horizon)
    return out


def make_context_key(df: pd.DataFrame, level: int) -> pd.Series:
    parts = []
    if level >= 1:
        parts.append("hour=" + fcol(df, "M5_hour_brt", df.get("anchor_hour", np.nan)).fillna(-1).astype(int).astype(str))
    if level >= 2:
        parts.append("state=" + df["anchor_market_state"].astype(str))
    if level >= 3:
        parts.append("energy=" + df["energy_bucket"].astype(str))
    if level >= 4:
        parts.append("vol=" + df["anchor_vol_bucket"].astype(str))
    if level >= 5:
        parts.append("align=" + df["mtf_alignment_bucket"].astype(str) + "/" + df["mtf_bias"].astype(str))
    if level >= 6:
        parts.append("event=" + np.select(
            [df["event_breakout"], df["event_false_breakout"], df["event_sweep"], df["event_compression"], df["event_expansion"]],
            ["BREAKOUT", "FALSE_BREAK", "SWEEP", "COMPRESSION", "EXPANSION"],
            default="NONE",
        ).astype(str))
    if level >= 7:
        parts.append("res=" + df["resistance_bucket"].astype(str) + "|sup=" + df["support_bucket"].astype(str))
    if not parts:
        return pd.Series("ALL", index=df.index)
    key = parts[0]
    for part in parts[1:]:
        key = key + "|" + part
    return key


def summarize_layered_contexts(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    rr_cols = [c for c in df.columns if c.startswith("rr_")]
    rows = []

    for level in range(1, 8):
        key = make_context_key(df, level)
        tmp = df.copy()
        tmp["context_key"] = key

        for ctx, g in tmp.groupby("context_key", dropna=False):
            if len(g) < min_bars:
                continue

            row = {
                "layer": level,
                "context_key": ctx,
                "bars": len(g),
                "avg_energy": g["energy_score"].mean(),
                "avg_range_atr": g["anchor_range_atr"].mean(),
                "avg_vol_ratio": g["anchor_vol_ratio"].mean(),
                "continuation_h3": g["h3_continues"].mean() if "h3_continues" in g.columns else np.nan,
                "continuation_h6": g["h6_continues"].mean() if "h6_continues" in g.columns else np.nan,
                "continuation_h12": g["h12_continues"].mean() if "h12_continues" in g.columns else np.nan,
                "pullback_0p50_h6": g["h6_pullback_0p50"].mean() if "h6_pullback_0p50" in g.columns else np.nan,
                "reach_1atr_h12": g["h12_reaches_1p00"].mean() if "h12_reaches_1p00" in g.columns else np.nan,
            }

            for col in rr_cols:
                valid = g[col].dropna()
                if len(valid):
                    row[f"{col}_tp"] = valid.eq("TP_FIRST").mean()
                    row[f"{col}_sl"] = valid.eq("SL_FIRST").mean()
                    row[f"{col}_amb"] = valid.eq("AMBIGUOUS").mean()
                    row[f"{col}_nt"] = valid.eq("NO_TOUCH").mean()

            # Score inicial: combina continuidade, alcance, pullback menor e RR principal.
            primary = "rr_t1p0_s0p5_h12"
            tp = row.get(f"{primary}_tp", np.nan)
            sl = row.get(f"{primary}_sl", np.nan)
            rr_edge = (tp - sl) if pd.notna(tp) and pd.notna(sl) else 0.0
            row["fusion_edge_score"] = (
                0.35 * rr_edge
                + 0.25 * (row["reach_1atr_h12"] if pd.notna(row["reach_1atr_h12"]) else 0)
                + 0.20 * (row["continuation_h6"] if pd.notna(row["continuation_h6"]) else 0)
                - 0.20 * (row["pullback_0p50_h6"] if pd.notna(row["pullback_0p50_h6"]) else 0)
            )
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(["fusion_edge_score", "bars"], ascending=[False, False])


def summarize_events(df: pd.DataFrame, min_bars: int) -> pd.DataFrame:
    event_name = np.select(
        [df["event_breakout"], df["event_false_breakout"], df["event_sweep"], df["event_compression"], df["event_expansion"]],
        ["BREAKOUT", "FALSE_BREAK", "SWEEP", "COMPRESSION", "EXPANSION"],
        default="NONE",
    )
    tmp = df.copy()
    tmp["event_name"] = event_name
    tmp["hour"] = fcol(tmp, "M5_hour_brt", tmp.get("anchor_hour", np.nan)).fillna(-1).astype(int)
    group_cols = ["event_name", "hour", "anchor_market_state", "energy_bucket", "mtf_alignment_bucket", "mtf_bias"]
    rows = []

    for keys, g in tmp.groupby(group_cols, dropna=False):
        if len(g) < min_bars:
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        row["bars"] = len(g)
        row["avg_energy"] = g["energy_score"].mean()
        row["avg_range_atr"] = g["anchor_range_atr"].mean()
        row["continuation_h3"] = g["h3_continues"].mean()
        row["continuation_h6"] = g["h6_continues"].mean()
        row["pullback_0p50_h6"] = g["h6_pullback_0p50"].mean()
        row["reach_1atr_h12"] = g["h12_reaches_1p00"].mean()
        primary = "rr_t1p0_s0p5_h12"
        if primary in g.columns:
            valid = g[primary].dropna()
            row["rr_tp"] = valid.eq("TP_FIRST").mean()
            row["rr_sl"] = valid.eq("SL_FIRST").mean()
            row["rr_edge"] = row["rr_tp"] - row["rr_sl"]
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["rr_edge", "reach_1atr_h12", "bars"], ascending=[False, False, False])


def write_report(path: Path, symbol: str, anchor_tf: str, metadata: dict[str, Any], contexts: pd.DataFrame, events: pd.DataFrame) -> None:
    lines = []
    lines.append(f"# Market Chronos Fusion — {symbol}\n")
    lines.append("## Base\n")
    lines.append(f"- Anchor TF: **{anchor_tf}**")
    lines.append(f"- Linhas: **{metadata['rows']}**")
    lines.append(f"- Input: `{metadata['input']}`")
    lines.append("")
    lines.append("## Leitura\n")
    lines.append("Este relatório organiza a pesquisa em camadas: horário → estado → energia → volume → MTF → evento → níveis.")
    lines.append("O objetivo é descobrir onde cada filtro melhora ou piora a assimetria, sem forçar uma regra única.\n")

    if not contexts.empty:
        lines.append("## Top contextos por Fusion Edge Score\n")
        lines.append(contexts.head(30).to_markdown(index=False))
        lines.append("")

    if not events.empty:
        lines.append("## Top eventos por edge operacional\n")
        lines.append(events.head(30).to_markdown(index=False))
        lines.append("")

    lines.append("## Como interpretar\n")
    lines.append("- `continuation_h6`: continuação na direção do candle em 6 candles M5.")
    lines.append("- `pullback_0p50_h6`: devolveu pelo menos 0,5 ATR contra o candle em até 6 candles.")
    lines.append("- `reach_1atr_h12`: andou pelo menos 1 ATR a favor em até 12 candles.")
    lines.append("- `rr_t1p0_s0p5_h12_tp`: bateu +1 ATR antes de -0,5 ATR em até 12 candles.")
    lines.append("- `fusion_edge_score`: métrica inicial para ranquear contextos; ainda não é lucro real.\n")
    lines.append("## Próximo passo\n")
    lines.append("Validar os contextos fortes no gráfico e depois criar uma versão realtime que apenas consulta essas estatísticas, sem labels futuros.")
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
    df = add_future_simple_outcomes(df, anchor_tf, horizons=[1, 2, 3, 6, 12, 24])
    df = add_rr_outcomes(df, anchor_tf)

    contexts = summarize_layered_contexts(df, min_bars=args.min_bars)
    events = summarize_events(df, min_bars=args.min_bars)

    keep_cols = [
        "event_time",
        f"{anchor_tf}_open", f"{anchor_tf}_high", f"{anchor_tf}_low", f"{anchor_tf}_close",
        f"{anchor_tf}_hour_brt", f"{anchor_tf}_time_slot",
        "anchor_direction", "anchor_market_state", "anchor_vol_bucket",
        "energy_score", "energy_bucket",
        "mtf_alignment_score", "mtf_alignment_bucket", "mtf_bias",
        "event_breakout", "event_false_breakout", "event_sweep", "event_compression", "event_expansion",
        "nearest_resistance_atr", "nearest_support_atr", "resistance_bucket", "support_bucket",
        "h3_continues", "h6_continues", "h12_continues",
        "h6_pullback_0p50", "h12_reaches_1p00",
        "rr_t1p0_s0p5_h12",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    detail = df[keep_cols].copy()

    detail_path = out_root / f"{symbol}_{anchor_tf}_fusion_detail.parquet"
    detail.to_parquet(detail_path, index=False)
    contexts.to_csv(out_root / "fusion_context_scores.csv", index=False, encoding="utf-8-sig")
    events.to_csv(out_root / "fusion_event_edges.csv", index=False, encoding="utf-8-sig")

    xlsx_path = out_root / f"{symbol}_chronos_fusion.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        contexts.to_excel(writer, sheet_name="context_scores", index=False)
        events.to_excel(writer, sheet_name="event_edges", index=False)

    metadata = {
        "script": "market_chronos_fusion.py",
        "symbol": symbol,
        "anchor_tf": anchor_tf,
        "rows": len(df),
        "input": str(input_path),
        "output": str(out_root),
        "min_bars": args.min_bars,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    save_json(out_root / "metadata.json", metadata)
    write_report(out_root / "chronos_fusion_report.md", symbol, anchor_tf, metadata, contexts, events)

    log("OK")
    print(json.dumps(jclean({
        "output": str(out_root),
        "report": str(out_root / "chronos_fusion_report.md"),
        "xlsx": str(xlsx_path),
        "detail": str(detail_path),
        "rows": len(df),
        "contexts": len(contexts),
        "events": len(events),
    }), ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Market Chronos Fusion")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.add_argument("--input", default=DEFAULT_INPUT)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--min-bars", type=int, default=120)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
