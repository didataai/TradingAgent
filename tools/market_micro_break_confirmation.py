#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pesquisa canônica de microconfirmação M5 -> M1.

Usa arquivos raw sincronizados:
- data/{symbol}_M1.parquet
- data/{symbol}_M5.parquet

Hipótese:
- SELL: último M5 fechado é RED; o M1 anterior também deve ser RED e o
  candle atual deve romper sua mínima;
- BUY: último M5 fechado é GREEN; o M1 anterior também deve ser GREEN e o
  candle atual deve romper sua máxima.

Classificação semântica:
- WICK_ONLY  -> LEVEL_SWEEP / WAIT_FOR_CONFIRMATION
- CLOSE_BREAK + SAME_COLOR -> BREAK_ACCEPTED / CONFIRMATION_CANDIDATE
- CLOSE_BREAK + OPPOSITE_COLOR -> DIRECTION_MISMATCH

A execução é abortada quando M1 e M5 não possuem sobreposição temporal real.
Não altera leis, registries ou bases originais.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from market_pattern_research_v2 import build_frame_from_fallback, clean

DEFAULT_M1 = "data/{symbol}_M1.parquet"
DEFAULT_M5 = "data/{symbol}_M5.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/micro_confirmation"


def candle_color(open_: float, close: float, doji_ratio: float, high: float, low: float) -> str:
    rng = max(float(high - low), 1e-12)
    body = float(close - open_)
    if abs(body) / rng <= doji_ratio:
        return "DOJI"
    return "GREEN" if body > 0 else "RED"


def measure(frame: pd.DataFrame, idx: int, entry: float, side: str, atr: float, horizon: int) -> tuple[float, float, float, bool]:
    end = min(len(frame), idx + horizon + 1)
    if idx + 1 >= end or not np.isfinite(atr) or atr <= 0:
        return np.nan, np.nan, np.nan, False
    future = frame.iloc[idx + 1:end]
    hi = float(future["high"].max())
    lo = float(future["low"].min())
    last = float(future["close"].iloc[-1])
    if side == "BUY":
        mfe, mae, ret = (hi-entry)/atr, (entry-lo)/atr, (last-entry)/atr
    else:
        mfe, mae, ret = (entry-lo)/atr, (hi-entry)/atr, (entry-last)/atr
    return mfe, mae, ret, bool(mfe >= 0.50 and mfe > mae)


def prepare_context(m5: pd.DataFrame) -> pd.DataFrame:
    out = m5[["event_time", "open", "high", "low", "close", "atr"]].copy()
    out = out.sort_values("event_time").reset_index(drop=True)
    out["m5_close_time"] = out["event_time"] + pd.Timedelta(minutes=5)
    out["m5_color"] = np.where(out["close"] > out["open"], "GREEN", np.where(out["close"] < out["open"], "RED", "DOJI"))
    out["m5_side"] = np.where(out["m5_color"].eq("GREEN"), "BUY", np.where(out["m5_color"].eq("RED"), "SELL", "NONE"))
    return out


def build_events(m1: pd.DataFrame, m5: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    m1 = m1.sort_values("event_time").reset_index(drop=True).copy()
    m5_ctx = prepare_context(m5)
    aligned = pd.merge_asof(
        m1,
        m5_ctx[["m5_close_time", "m5_color", "m5_side"]],
        left_on="event_time",
        right_on="m5_close_time",
        direction="backward",
        tolerance=pd.Timedelta(minutes=5),
        allow_exact_matches=True,
    )

    rows: list[dict[str, Any]] = []
    for i in range(1, len(aligned) - max(args.horizons) - 1):
        cur = aligned.iloc[i]
        prev = aligned.iloc[i - 1]
        side = str(cur.get("m5_side", "NONE"))
        if side not in {"BUY", "SELL"} or pd.isna(cur.get("m5_close_time")):
            continue

        prev_color = candle_color(prev["open"], prev["close"], args.doji_body_ratio, prev["high"], prev["low"])
        expected_color = "GREEN" if side == "BUY" else "RED"
        color_relation = "SAME_COLOR" if prev_color == expected_color else "OPPOSITE_COLOR" if prev_color in {"GREEN", "RED"} else "DOJI"

        if side == "BUY":
            wick_break = float(cur["high"]) > float(prev["high"])
            close_break = float(cur["close"]) > float(prev["high"])
            level = float(prev["high"])
        else:
            wick_break = float(cur["low"]) < float(prev["low"])
            close_break = float(cur["close"]) < float(prev["low"])
            level = float(prev["low"])

        if not wick_break:
            continue

        atr = float(cur["atr"]) if np.isfinite(cur["atr"]) and cur["atr"] > 0 else float(prev["atr"])
        if not np.isfinite(atr) or atr <= 0:
            continue

        break_mode = "CLOSE_BREAK" if close_break else "WICK_ONLY"
        micro_state = "BREAK_ACCEPTED" if close_break else "LEVEL_SWEEP"
        runtime_action = (
            "WAIT_FOR_CONFIRMATION" if micro_state == "LEVEL_SWEEP"
            else "CONFIRMATION_CANDIDATE" if color_relation == "SAME_COLOR"
            else "DIRECTION_MISMATCH"
        )
        entry = float(cur["close"])
        fail_end = min(len(aligned), i + args.false_break_horizon + 1)
        future_close = aligned.iloc[i + 1:fail_end]["close"]
        false_breakout = False
        if len(future_close):
            false_breakout = bool((future_close < level).any()) if side == "BUY" else bool((future_close > level).any())

        row: dict[str, Any] = {
            "symbol": args.symbol.upper(),
            "event_time": cur["event_time"],
            "m5_close_time": cur["m5_close_time"],
            "m5_color": cur["m5_color"],
            "side": side,
            "m1_previous_color": prev_color,
            "color_relation": color_relation,
            "break_mode": break_mode,
            "micro_state": micro_state,
            "runtime_action": runtime_action,
            "level": level,
            "entry_price": entry,
            "atr": atr,
            "break_distance_atr": abs(entry-level)/atr,
            "false_breakout": false_breakout,
            "m1_prev_open": float(prev["open"]),
            "m1_prev_high": float(prev["high"]),
            "m1_prev_low": float(prev["low"]),
            "m1_prev_close": float(prev["close"]),
            "m1_open": float(cur["open"]),
            "m1_high": float(cur["high"]),
            "m1_low": float(cur["low"]),
            "m1_close": float(cur["close"]),
        }
        for h in sorted(set(args.horizons)):
            mfe, mae, ret, success = measure(aligned, i, entry, side, atr, h)
            row[f"mfe_{h}_atr"] = mfe
            row[f"mae_{h}_atr"] = mae
            row[f"return_{h}_atr"] = ret
            row[f"success_{h}"] = success
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate(events: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    rows = []
    keys = ["side", "color_relation", "break_mode", "micro_state", "runtime_action"]
    for values, group in events.groupby(keys, dropna=False):
        row = dict(zip(keys, values))
        row.update({
            "sample_size": len(group),
            "false_breakout_rate": float(group["false_breakout"].mean()),
            "avg_break_distance_atr": float(group["break_distance_atr"].mean()),
        })
        for h in horizons:
            row[f"success_rate_{h}"] = float(group[f"success_{h}"].mean())
            row[f"avg_mfe_{h}_atr"] = float(group[f"mfe_{h}_atr"].mean())
            row[f"avg_mae_{h}_atr"] = float(group[f"mae_{h}_atr"].mean())
            row[f"avg_return_{h}_atr"] = float(group[f"return_{h}_atr"].mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["side", "sample_size"], ascending=[True, False])


def comparison(summary: pd.DataFrame, horizon: int) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    rows = []
    for (side, mode), group in summary.groupby(["side", "break_mode"]):
        same = group[group["color_relation"].eq("SAME_COLOR")]
        opposite = group[group["color_relation"].eq("OPPOSITE_COLOR")]
        if same.empty or opposite.empty:
            continue
        s, o = same.iloc[0], opposite.iloc[0]
        rows.append({
            "side": side,
            "break_mode": mode,
            "same_color_sample": int(s["sample_size"]),
            "opposite_color_sample": int(o["sample_size"]),
            f"success_lift_{horizon}": float(s[f"success_rate_{horizon}"] - o[f"success_rate_{horizon}"]),
            f"return_lift_{horizon}_atr": float(s[f"avg_return_{horizon}_atr"] - o[f"avg_return_{horizon}_atr"]),
            f"mae_reduction_{horizon}_atr": float(o[f"avg_mae_{horizon}_atr"] - s[f"avg_mae_{horizon}_atr"]),
            "false_break_reduction": float(o["false_breakout_rate"] - s["false_breakout_rate"]),
            "same_color_preferred": bool(
                s[f"success_rate_{horizon}"] > o[f"success_rate_{horizon}"]
                and s[f"avg_return_{horizon}_atr"] > o[f"avg_return_{horizon}_atr"]
            ),
        })
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Synchronized M5 to M1 micro break confirmation research")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--m1-input", default=DEFAULT_M1)
    p.add_argument("--m5-input", default=DEFAULT_M5)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--horizons", nargs="+", type=int, default=[3, 5, 10])
    p.add_argument("--false-break-horizon", type=int, default=3)
    p.add_argument("--doji-body-ratio", type=float, default=0.10)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd(); symbol = args.symbol.upper()
    m1_path = root / args.m1_input.format(symbol=symbol)
    m5_path = root / args.m5_input.format(symbol=symbol)
    output = root / args.output.format(symbol=symbol)
    output.mkdir(parents=True, exist_ok=True)

    if not m1_path.exists():
        raise FileNotFoundError(f"M1 não encontrado: {m1_path}")
    if not m5_path.exists():
        raise FileNotFoundError(f"M5 não encontrado: {m5_path}")

    m1 = build_frame_from_fallback(m1_path).sort_values("event_time").reset_index(drop=True)
    m5 = build_frame_from_fallback(m5_path).sort_values("event_time").reset_index(drop=True)

    m1_min, m1_max = m1["event_time"].min(), m1["event_time"].max()
    m5_close_min = m5["event_time"].min() + pd.Timedelta(minutes=5)
    m5_close_max = m5["event_time"].max() + pd.Timedelta(minutes=5)
    overlap_start = max(m1_min, m5_close_min)
    overlap_end = min(m1_max, m5_close_max)
    if overlap_start > overlap_end:
        raise RuntimeError(
            "Sem sobreposição temporal entre M1 e M5 raw. "
            f"M1={m1_min}..{m1_max} | M5 close={m5_close_min}..{m5_close_max}"
        )

    m1_sync = m1[(m1["event_time"] >= overlap_start) & (m1["event_time"] <= overlap_end)].copy()
    m5_sync = m5[
        ((m5["event_time"] + pd.Timedelta(minutes=5)) >= overlap_start - pd.Timedelta(minutes=5))
        & ((m5["event_time"] + pd.Timedelta(minutes=5)) <= overlap_end)
    ].copy()
    if len(m1_sync) < max(args.horizons) + 3 or len(m5_sync) < 2:
        raise RuntimeError(f"Sobreposição insuficiente: M1={len(m1_sync)}, M5={len(m5_sync)}")

    horizons = sorted(set(args.horizons))
    events = build_events(m1_sync, m5_sync, args)
    summary = aggregate(events, horizons)
    compare = comparison(summary, max(horizons))

    events.to_parquet(output / "micro_break_events.parquet", index=False)
    summary.to_csv(output / "micro_break_summary.csv", index=False, encoding="utf-8-sig")
    compare.to_csv(output / "micro_break_same_vs_opposite.csv", index=False, encoding="utf-8-sig")

    metadata = {
        "script": "market_micro_break_confirmation.py",
        "version": "3.0-consolidated",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "m1_input": str(m1_path),
        "m5_input": str(m5_path),
        "m1_rows_total": len(m1),
        "m5_rows_total": len(m5),
        "m1_rows_synchronized": len(m1_sync),
        "m5_rows_synchronized": len(m5_sync),
        "m1_min": m1_min,
        "m1_max": m1_max,
        "m5_close_min": m5_close_min,
        "m5_close_max": m5_close_max,
        "overlap_start": overlap_start,
        "overlap_end": overlap_end,
        "events": len(events),
        "buy_events": int((events["side"] == "BUY").sum()) if len(events) else 0,
        "sell_events": int((events["side"] == "SELL").sum()) if len(events) else 0,
        "level_sweeps": int((events["micro_state"] == "LEVEL_SWEEP").sum()) if len(events) else 0,
        "accepted_breaks": int((events["micro_state"] == "BREAK_ACCEPTED").sum()) if len(events) else 0,
        "summary_rows": len(summary),
        "comparison_rows": len(compare),
        "horizons": horizons,
        "output": str(output),
    }
    (output / "metadata.json").write_text(json.dumps(clean(metadata), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
