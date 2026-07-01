#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnóstico da microconfirmação M5 -> M1 e semântica de sweep/acceptance.

Objetivos:
- verificar cobertura BUY/SELL do contexto M5 alinhado ao M1;
- contar candidatos de rompimento por lado antes dos filtros;
- reclassificar WICK_ONLY como LEVEL_SWEEP;
- reclassificar CLOSE_BREAK como BREAK_ACCEPTED;
- produzir um resumo operacional sem alterar leis ou registries.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from market_pattern_research_v2 import build_frame_from_fallback, build_frame_from_mtf, clean, normalize_time
from market_micro_break_confirmation import candle_color, prepare_context

DEFAULT_MTF = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_M1 = "data/{symbol}_M1.parquet"
DEFAULT_EVENTS = "data/market_chronos/{symbol}/micro_confirmation/micro_break_events.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/micro_confirmation/diagnostics"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diagnose M5 to M1 micro break coverage")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.add_argument("--mtf-input", default=DEFAULT_MTF)
    p.add_argument("--m1-input", default=DEFAULT_M1)
    p.add_argument("--events-input", default=DEFAULT_EVENTS)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--doji-body-ratio", type=float, default=0.10)
    return p.parse_args()


def main() -> None:
    a = parse_args()
    root = Path.cwd()
    symbol = a.symbol.upper()
    anchor = a.anchor_tf.upper()
    output = root / a.output.format(symbol=symbol, anchor_tf=anchor)
    output.mkdir(parents=True, exist_ok=True)

    raw_mtf = normalize_time(pd.read_parquet(root / a.mtf_input.format(symbol=symbol, anchor_tf=anchor)))
    m5 = build_frame_from_mtf(raw_mtf, "M5").sort_values("event_time").reset_index(drop=True)
    m1 = build_frame_from_fallback(root / a.m1_input.format(symbol=symbol, anchor_tf=anchor)).sort_values("event_time").reset_index(drop=True)

    m5_ctx = prepare_context(m5)
    aligned = pd.merge_asof(
        m1,
        m5_ctx[["m5_close_time", "m5_color", "m5_side"]],
        left_on="event_time",
        right_on="m5_close_time",
        direction="backward",
        allow_exact_matches=True,
    )

    context_counts = (
        aligned["m5_side"].fillna("UNALIGNED").value_counts(dropna=False).rename_axis("m5_side").reset_index(name="m1_rows")
    )

    candidate_rows = []
    for i in range(1, len(aligned)):
        cur = aligned.iloc[i]
        prev = aligned.iloc[i - 1]
        side = str(cur.get("m5_side", "NONE"))
        if side not in {"BUY", "SELL"}:
            continue

        prev_color = candle_color(prev["open"], prev["close"], a.doji_body_ratio, prev["high"], prev["low"])
        expected = "GREEN" if side == "BUY" else "RED"
        relation = "SAME_COLOR" if prev_color == expected else "OPPOSITE_COLOR" if prev_color in {"GREEN", "RED"} else "DOJI"

        if side == "BUY":
            wick_break = float(cur["high"]) > float(prev["high"])
            close_break = float(cur["close"]) > float(prev["high"])
        else:
            wick_break = float(cur["low"]) < float(prev["low"])
            close_break = float(cur["close"]) < float(prev["low"])

        candidate_rows.append({
            "event_time": cur["event_time"],
            "side": side,
            "previous_color": prev_color,
            "color_relation": relation,
            "wick_break": bool(wick_break),
            "close_break": bool(close_break),
            "state": "BREAK_ACCEPTED" if close_break else "LEVEL_SWEEP" if wick_break else "NO_BREAK",
        })

    candidates = pd.DataFrame(candidate_rows)
    candidate_summary = (
        candidates.groupby(["side", "color_relation", "state"], dropna=False)
        .size().reset_index(name="sample_size")
        .sort_values(["side", "sample_size"], ascending=[True, False])
    )

    events_path = root / a.events_input.format(symbol=symbol, anchor_tf=anchor)
    events_semantic = pd.DataFrame()
    if events_path.exists():
        events_semantic = pd.read_parquet(events_path).copy()
        events_semantic["micro_state"] = np.where(
            events_semantic["break_mode"].eq("CLOSE_BREAK"),
            "BREAK_ACCEPTED",
            "LEVEL_SWEEP",
        )
        events_semantic["runtime_action"] = np.where(
            events_semantic["micro_state"].eq("LEVEL_SWEEP"),
            "WAIT_FOR_CONFIRMATION",
            np.where(
                events_semantic["color_relation"].eq("SAME_COLOR"),
                "CONFIRMATION_CANDIDATE",
                "DIRECTION_MISMATCH",
            ),
        )
        events_semantic.to_parquet(output / "micro_break_events_semantic.parquet", index=False)

    context_counts.to_csv(output / "context_side_coverage.csv", index=False, encoding="utf-8-sig")
    candidate_summary.to_csv(output / "candidate_state_summary.csv", index=False, encoding="utf-8-sig")
    candidates.to_parquet(output / "candidate_state_detail.parquet", index=False)

    metadata = {
        "script": "market_micro_break_diagnostics.py",
        "version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "m1_rows": len(m1),
        "m5_rows": len(m5),
        "aligned_rows": len(aligned),
        "candidate_rows": len(candidates),
        "buy_context_rows": int((aligned["m5_side"] == "BUY").sum()),
        "sell_context_rows": int((aligned["m5_side"] == "SELL").sum()),
        "buy_break_candidates": int(((candidates["side"] == "BUY") & (candidates["state"] != "NO_BREAK")).sum()),
        "sell_break_candidates": int(((candidates["side"] == "SELL") & (candidates["state"] != "NO_BREAK")).sum()),
        "semantic_events_written": int(len(events_semantic)),
        "output": str(output),
    }
    (output / "metadata.json").write_text(json.dumps(clean(metadata), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
