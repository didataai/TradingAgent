#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pesquisa canônica de microconfirmação M5 -> M1.

Estuda:
- LEVEL_SWEEP versus BREAK_ACCEPTED;
- reteste após fechamento além do nível;
- episódios de múltiplas tentativas sobre o mesmo nível;
- profundidade do recuo entre tentativas e compressão.

Usa data/{symbol}_M1.parquet e data/{symbol}_M5.parquet sincronizados.
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


def candle_color(o: float, c: float, ratio: float, h: float, l: float) -> str:
    rng = max(float(h - l), 1e-12)
    if abs(float(c - o)) / rng <= ratio:
        return "DOJI"
    return "GREEN" if c > o else "RED"


def measure(frame: pd.DataFrame, idx: int, entry: float, side: str, atr: float, horizon: int):
    end = min(len(frame), idx + horizon + 1)
    if idx + 1 >= end or not np.isfinite(atr) or atr <= 0:
        return np.nan, np.nan, np.nan, False
    future = frame.iloc[idx + 1:end]
    hi, lo, last = float(future.high.max()), float(future.low.min()), float(future.close.iloc[-1])
    if side == "BUY":
        mfe, mae, ret = (hi-entry)/atr, (entry-lo)/atr, (last-entry)/atr
    else:
        mfe, mae, ret = (entry-lo)/atr, (hi-entry)/atr, (entry-last)/atr
    return mfe, mae, ret, bool(mfe >= 0.50 and mfe > mae)


def prepare_context(m5: pd.DataFrame) -> pd.DataFrame:
    out = m5[["event_time", "open", "high", "low", "close", "atr"]].copy().sort_values("event_time")
    out["m5_close_time"] = out.event_time + pd.Timedelta(minutes=5)
    out["m5_color"] = np.where(out.close > out.open, "GREEN", np.where(out.close < out.open, "RED", "DOJI"))
    out["m5_side"] = np.where(out.m5_color.eq("GREEN"), "BUY", np.where(out.m5_color.eq("RED"), "SELL", "NONE"))
    return out.reset_index(drop=True)


def classify_retest(frame, idx, side, level, atr, args):
    result = {
        "retest_state": "NO_RETEST", "retest_event_time": pd.NaT,
        "retest_entry_price": np.nan, "retest_delay_candles": np.nan,
    }
    tol = args.retest_tolerance_atr * atr
    for j in range(idx + 1, min(len(frame), idx + args.retest_horizon + 1)):
        c = frame.iloc[j]
        if side == "BUY":
            touched = float(c.low) <= level + tol
            invalid = float(c.close) < level - tol
            held = touched and not invalid and float(c.close) >= level
        else:
            touched = float(c.high) >= level - tol
            invalid = float(c.close) > level + tol
            held = touched and not invalid and float(c.close) <= level
        if not touched:
            continue
        result.update({
            "retest_event_time": c.event_time,
            "retest_entry_price": float(c.close),
            "retest_delay_candles": j - idx,
            "retest_state": "RETEST_FAILED" if invalid else "RETEST_HELD" if held else "RETEST_AMBIGUOUS",
        })
        return result
    return result


def align_frames(m1, m5):
    return pd.merge_asof(
        m1.sort_values("event_time").reset_index(drop=True),
        prepare_context(m5)[["m5_close_time", "m5_color", "m5_side"]],
        left_on="event_time", right_on="m5_close_time", direction="backward",
        tolerance=pd.Timedelta(minutes=5), allow_exact_matches=True,
    )


def build_events(m1, m5, args):
    aligned = align_frames(m1, m5)
    rows = []
    max_future = max(args.horizons) + args.retest_horizon + 2
    for i in range(1, len(aligned) - max_future):
        cur, prev = aligned.iloc[i], aligned.iloc[i-1]
        side = str(cur.get("m5_side", "NONE"))
        if side not in {"BUY", "SELL"} or pd.isna(cur.get("m5_close_time")):
            continue
        prev_color = candle_color(prev.open, prev.close, args.doji_body_ratio, prev.high, prev.low)
        expected = "GREEN" if side == "BUY" else "RED"
        relation = "SAME_COLOR" if prev_color == expected else "OPPOSITE_COLOR" if prev_color in {"GREEN", "RED"} else "DOJI"
        if side == "BUY":
            wick, close_break, level = cur.high > prev.high, cur.close > prev.high, float(prev.high)
        else:
            wick, close_break, level = cur.low < prev.low, cur.close < prev.low, float(prev.low)
        if not wick:
            continue
        atr = float(cur.atr) if np.isfinite(cur.atr) and cur.atr > 0 else float(prev.atr)
        if not np.isfinite(atr) or atr <= 0:
            continue

        break_mode = "CLOSE_BREAK" if close_break else "WICK_ONLY"
        micro_state = "BREAK_ACCEPTED" if close_break else "LEVEL_SWEEP"
        entry = float(cur.close)
        future_close = aligned.iloc[i+1:min(len(aligned), i+args.false_break_horizon+1)].close
        false_break = bool((future_close < level).any()) if side == "BUY" and len(future_close) else bool((future_close > level).any()) if len(future_close) else False
        retest = classify_retest(aligned, i, side, level, atr, args) if close_break else {
            "retest_state": "NOT_APPLICABLE", "retest_event_time": pd.NaT,
            "retest_entry_price": np.nan, "retest_delay_candles": np.nan,
        }
        row = {
            "symbol": args.symbol.upper(), "event_time": cur.event_time, "event_index": i,
            "m5_close_time": cur.m5_close_time, "m5_color": cur.m5_color, "side": side,
            "m1_previous_color": prev_color, "color_relation": relation,
            "break_mode": break_mode, "micro_state": micro_state,
            "runtime_action": "CONFIRMATION_CANDIDATE" if close_break else "WAIT_FOR_CONFIRMATION",
            "level": level, "entry_price": entry, "atr": atr,
            "break_distance_atr": abs(entry-level)/atr, "false_breakout": false_break,
            **retest,
        }
        for h in args.horizons:
            mfe, mae, ret, success = measure(aligned, i, entry, side, atr, h)
            row.update({f"breakout_mfe_{h}_atr": mfe, f"breakout_mae_{h}_atr": mae,
                        f"breakout_return_{h}_atr": ret, f"breakout_success_{h}": success})
            if retest["retest_state"] == "RETEST_HELD":
                ri = i + int(retest["retest_delay_candles"])
                rmfe, rmae, rret, rs = measure(aligned, ri, float(retest["retest_entry_price"]), side, atr, h)
            else:
                rmfe, rmae, rret, rs = np.nan, np.nan, np.nan, False
            row.update({f"retest_mfe_{h}_atr": rmfe, f"retest_mae_{h}_atr": rmae,
                        f"retest_return_{h}_atr": rret, f"retest_success_{h}": rs})
        rows.append(row)
    return pd.DataFrame(rows), aligned


def build_attempt_episodes(events: pd.DataFrame, aligned: pd.DataFrame, args):
    if events.empty:
        return pd.DataFrame(), pd.DataFrame()
    attempts, episodes = [], []
    episode_id = 0

    for side, side_events in events.sort_values("event_index").groupby("side", sort=False):
        active = None
        for _, ev in side_events.iterrows():
            idx, level, atr = int(ev.event_index), float(ev.level), float(ev.atr)
            same_episode = False
            if active is not None:
                gap = idx - active["last_index"]
                distance = abs(level - active["level"]) / max(atr, 1e-12)
                same_episode = gap <= args.episode_max_gap_candles and distance <= args.episode_level_tolerance_atr
            if not same_episode:
                if active is not None:
                    episodes.append(active)
                episode_id += 1
                active = {
                    "episode_id": episode_id, "side": side, "start_time": ev.event_time,
                    "end_time": ev.event_time, "level": level, "atr": atr,
                    "attempts": 0, "failed_attempts": 0, "accepted": False,
                    "accepted_on_attempt": np.nan, "last_index": idx,
                    "last_failed_index": None, "last_recoil_atr": np.nan,
                    "recoil_decreasing_count": 0,
                }

            attempt_no = active["attempts"] + 1
            recoil = np.nan
            recoil_ratio = np.nan
            compression = False
            if active["last_failed_index"] is not None:
                start = active["last_failed_index"] + 1
                segment = aligned.iloc[start:idx+1]
                if len(segment):
                    recoil = ((active["level"] - float(segment.low.min())) / atr) if side == "BUY" else ((float(segment.high.max()) - active["level"]) / atr)
                    if np.isfinite(active["last_recoil_atr"]) and active["last_recoil_atr"] > 0:
                        recoil_ratio = recoil / active["last_recoil_atr"]
                        compression = recoil < active["last_recoil_atr"]
                        if compression:
                            active["recoil_decreasing_count"] += 1

            accepted = ev.break_mode == "CLOSE_BREAK"
            attempts.append({
                "episode_id": episode_id, "side": side, "attempt_number": attempt_no,
                "event_time": ev.event_time, "event_index": idx, "level": active["level"],
                "event_level": level, "atr": atr, "break_mode": ev.break_mode,
                "accepted": accepted, "recoil_before_attempt_atr": recoil,
                "recoil_ratio_vs_previous": recoil_ratio, "compression_before_attempt": compression,
                "color_relation": ev.color_relation,
            })
            active["attempts"] = attempt_no
            active["end_time"] = ev.event_time
            active["last_index"] = idx
            if accepted:
                active["accepted"] = True
                active["accepted_on_attempt"] = attempt_no
                episodes.append(active)
                active = None
            else:
                active["failed_attempts"] += 1
                active["last_failed_index"] = idx
                if np.isfinite(recoil):
                    active["last_recoil_atr"] = recoil
        if active is not None:
            episodes.append(active)

    ep = pd.DataFrame(episodes)
    if not ep.empty:
        ep["episode_state"] = np.where(ep.accepted, "LEVEL_BROKEN", "UNRESOLVED_OR_REJECTED")
        ep["pressure_state"] = np.where(
            ep.recoil_decreasing_count >= 2, "PRESSURE_BUILDING",
            np.where(ep.recoil_decreasing_count == 1, "POSSIBLE_COMPRESSION", "NO_COMPRESSION_EVIDENCE")
        )
    return pd.DataFrame(attempts), ep


def aggregate_breaks(events, horizons):
    if events.empty: return pd.DataFrame()
    rows = []
    keys = ["side", "color_relation", "break_mode", "micro_state", "runtime_action"]
    for vals, g in events.groupby(keys, dropna=False):
        r = dict(zip(keys, vals)); r.update(sample_size=len(g), false_breakout_rate=float(g.false_breakout.mean()))
        for h in horizons:
            r.update({f"success_rate_{h}": float(g[f"breakout_success_{h}"].mean()),
                      f"avg_mfe_{h}_atr": float(g[f"breakout_mfe_{h}_atr"].mean()),
                      f"avg_mae_{h}_atr": float(g[f"breakout_mae_{h}_atr"].mean()),
                      f"avg_return_{h}_atr": float(g[f"breakout_return_{h}_atr"].mean())})
        rows.append(r)
    return pd.DataFrame(rows).sort_values(["side", "sample_size"], ascending=[True, False])


def compare_color(summary, h):
    rows = []
    if summary.empty: return pd.DataFrame()
    for (side, mode), g in summary.groupby(["side", "break_mode"]):
        s, o = g[g.color_relation.eq("SAME_COLOR")], g[g.color_relation.eq("OPPOSITE_COLOR")]
        if s.empty or o.empty: continue
        s, o = s.iloc[0], o.iloc[0]
        rows.append({"side": side, "break_mode": mode, "same_color_sample": int(s.sample_size),
                     "opposite_color_sample": int(o.sample_size),
                     f"success_lift_{h}": float(s[f"success_rate_{h}"]-o[f"success_rate_{h}"]),
                     f"return_lift_{h}_atr": float(s[f"avg_return_{h}_atr"]-o[f"avg_return_{h}_atr"]),
                     f"mae_reduction_{h}_atr": float(o[f"avg_mae_{h}_atr"]-s[f"avg_mae_{h}_atr"]),
                     "false_break_reduction": float(o.false_breakout_rate-s.false_breakout_rate)})
    return pd.DataFrame(rows)


def aggregate_retests(events, horizons):
    accepted = events[events.break_mode.eq("CLOSE_BREAK")]
    rows = []
    for (side, state), g in accepted.groupby(["side", "retest_state"]):
        r = {"side": side, "retest_state": state, "sample_size": len(g),
             "share_of_accepted": len(g)/len(accepted[accepted.side.eq(side)]),
             "avg_retest_delay_candles": float(g.retest_delay_candles.mean()) if g.retest_delay_candles.notna().any() else np.nan}
        for h in horizons:
            r[f"breakout_success_rate_{h}"] = float(g[f"breakout_success_{h}"].mean())
            r[f"breakout_avg_return_{h}_atr"] = float(g[f"breakout_return_{h}_atr"].mean())
            held = g[g.retest_state.eq("RETEST_HELD")]
            r[f"retest_success_rate_{h}"] = float(held[f"retest_success_{h}"].mean()) if len(held) else np.nan
            r[f"retest_avg_return_{h}_atr"] = float(held[f"retest_return_{h}_atr"].mean()) if len(held) else np.nan
        rows.append(r)
    return pd.DataFrame(rows)


def fair_retest(events, h):
    held = events[(events.break_mode.eq("CLOSE_BREAK")) & events.retest_state.eq("RETEST_HELD")]
    rows = []
    for side, g in held.groupby("side"):
        rows.append({"side": side, "sample_size": len(g),
                     f"breakout_success_rate_{h}": float(g[f"breakout_success_{h}"].mean()),
                     f"retest_success_rate_{h}": float(g[f"retest_success_{h}"].mean()),
                     f"success_lift_{h}": float(g[f"retest_success_{h}"].mean()-g[f"breakout_success_{h}"].mean()),
                     f"breakout_avg_return_{h}_atr": float(g[f"breakout_return_{h}_atr"].mean()),
                     f"retest_avg_return_{h}_atr": float(g[f"retest_return_{h}_atr"].mean()),
                     f"return_lift_{h}_atr": float(g[f"retest_return_{h}_atr"].mean()-g[f"breakout_return_{h}_atr"].mean())})
    return pd.DataFrame(rows)


def episode_summary(episodes):
    if episodes.empty: return pd.DataFrame()
    accepted = episodes[episodes.accepted].copy()
    rows = []
    for (side, attempt), g in accepted.groupby(["side", "accepted_on_attempt"]):
        rows.append({"side": side, "accepted_on_attempt": int(attempt), "episodes": len(g),
                     "share_of_accepted": len(g)/len(accepted[accepted.side.eq(side)]),
                     "avg_failed_attempts_before_break": float(g.failed_attempts.mean()),
                     "pressure_building_rate": float(g.pressure_state.eq("PRESSURE_BUILDING").mean()),
                     "possible_compression_rate": float(g.pressure_state.isin(["PRESSURE_BUILDING", "POSSIBLE_COMPRESSION"]).mean())})
    return pd.DataFrame(rows).sort_values(["side", "accepted_on_attempt"])


def parse_args():
    p = argparse.ArgumentParser(description="M5/M1 micro break, retest and repeated-attempt research")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--m1-input", default=DEFAULT_M1); p.add_argument("--m5-input", default=DEFAULT_M5)
    p.add_argument("--output", default=DEFAULT_OUTPUT); p.add_argument("--horizons", nargs="+", type=int, default=[3,5,10])
    p.add_argument("--false-break-horizon", type=int, default=3); p.add_argument("--retest-horizon", type=int, default=8)
    p.add_argument("--retest-tolerance-atr", type=float, default=0.10); p.add_argument("--doji-body-ratio", type=float, default=0.10)
    p.add_argument("--episode-level-tolerance-atr", type=float, default=0.15)
    p.add_argument("--episode-max-gap-candles", type=int, default=20)
    return p.parse_args()


def main():
    args = parse_args(); args.horizons = sorted(set(args.horizons))
    root, symbol = Path.cwd(), args.symbol.upper()
    m1_path, m5_path = root/args.m1_input.format(symbol=symbol), root/args.m5_input.format(symbol=symbol)
    output = root/args.output.format(symbol=symbol); output.mkdir(parents=True, exist_ok=True)
    if not m1_path.exists() or not m5_path.exists(): raise FileNotFoundError("Arquivos M1/M5 raw não encontrados")
    m1, m5 = build_frame_from_fallback(m1_path), build_frame_from_fallback(m5_path)
    m1, m5 = m1.sort_values("event_time").reset_index(drop=True), m5.sort_values("event_time").reset_index(drop=True)
    overlap_start = max(m1.event_time.min(), m5.event_time.min()+pd.Timedelta(minutes=5))
    overlap_end = min(m1.event_time.max(), m5.event_time.max()+pd.Timedelta(minutes=5))
    if overlap_start > overlap_end: raise RuntimeError("Sem sobreposição temporal entre M1 e M5")
    m1s = m1[(m1.event_time>=overlap_start)&(m1.event_time<=overlap_end)].copy()
    m5s = m5[((m5.event_time+pd.Timedelta(minutes=5))>=overlap_start-pd.Timedelta(minutes=5))&((m5.event_time+pd.Timedelta(minutes=5))<=overlap_end)].copy()

    events, aligned = build_events(m1s, m5s, args)
    summary = aggregate_breaks(events, args.horizons)
    color = compare_color(summary, max(args.horizons))
    retest_summary = aggregate_retests(events, args.horizons)
    retest_cmp = fair_retest(events, max(args.horizons))
    attempts, episodes = build_attempt_episodes(events, aligned, args)
    ep_summary = episode_summary(episodes)

    events.to_parquet(output/"micro_break_events.parquet", index=False)
    summary.to_csv(output/"micro_break_summary.csv", index=False, encoding="utf-8-sig")
    color.to_csv(output/"micro_break_same_vs_opposite.csv", index=False, encoding="utf-8-sig")
    retest_summary.to_csv(output/"micro_break_retest_summary.csv", index=False, encoding="utf-8-sig")
    retest_cmp.to_csv(output/"micro_break_retest_fair_comparison.csv", index=False, encoding="utf-8-sig")
    attempts.to_parquet(output/"breakout_attempts.parquet", index=False)
    episodes.to_csv(output/"breakout_attempt_episodes.csv", index=False, encoding="utf-8-sig")
    ep_summary.to_csv(output/"breakout_attempt_number_summary.csv", index=False, encoding="utf-8-sig")

    meta = {"script":"market_micro_break_confirmation.py","version":"5.0-attempt-episodes",
            "generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":symbol,
            "m1_rows_synchronized":len(m1s),"m5_rows_synchronized":len(m5s),
            "overlap_start":overlap_start,"overlap_end":overlap_end,"events":len(events),
            "level_sweeps":int(events.micro_state.eq("LEVEL_SWEEP").sum()),
            "accepted_breaks":int(events.micro_state.eq("BREAK_ACCEPTED").sum()),
            "attempts":len(attempts),"episodes":len(episodes),
            "episodes_broken":int(episodes.accepted.sum()) if len(episodes) else 0,
            "episodes_pressure_building":int(episodes.pressure_state.eq("PRESSURE_BUILDING").sum()) if len(episodes) else 0,
            "episode_level_tolerance_atr":args.episode_level_tolerance_atr,
            "episode_max_gap_candles":args.episode_max_gap_candles,"output":str(output)}
    (output/"metadata.json").write_text(json.dumps(clean(meta),ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(clean(meta),ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
