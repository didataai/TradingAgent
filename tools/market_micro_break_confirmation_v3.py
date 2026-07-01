#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pesquisa de microconfirmação M5 -> M1 usando arquivos raw sincronizados.

Substitui a base MTF desatualizada por:
- data/{symbol}_M1.parquet
- data/{symbol}_M5.parquet

A execução é abortada quando não há sobreposição temporal real.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import market_micro_break_confirmation as engine
from market_micro_break_confirmation_v2 import comparison
from market_pattern_research_v2 import build_frame_from_fallback, clean

DEFAULT_M1 = "data/{symbol}_M1.parquet"
DEFAULT_M5 = "data/{symbol}_M5.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/micro_confirmation_v3"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Synchronized raw M5 to M1 micro break research")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--m1-input", default=DEFAULT_M1)
    p.add_argument("--m5-input", default=DEFAULT_M5)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--horizons", nargs="+", type=int, default=[3, 5, 10])
    p.add_argument("--false-break-horizon", type=int, default=3)
    p.add_argument("--doji-body-ratio", type=float, default=0.10)
    return p.parse_args()


def main() -> None:
    a = parse_args()
    root = Path.cwd()
    symbol = a.symbol.upper()
    m1_path = root / a.m1_input.format(symbol=symbol)
    m5_path = root / a.m5_input.format(symbol=symbol)
    output = root / a.output.format(symbol=symbol)
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

    # Recorta ambos ao período realmente comparável, preservando um candle anterior.
    m1_sync = m1[(m1["event_time"] >= overlap_start) & (m1["event_time"] <= overlap_end)].copy()
    m5_sync = m5[(m5["event_time"] + pd.Timedelta(minutes=5) >= overlap_start - pd.Timedelta(minutes=5)) &
                 (m5["event_time"] + pd.Timedelta(minutes=5) <= overlap_end)].copy()

    if len(m1_sync) < max(a.horizons) + 3 or len(m5_sync) < 2:
        raise RuntimeError(
            f"Sobreposição insuficiente: M1={len(m1_sync)} linhas, M5={len(m5_sync)} linhas"
        )

    # Reutiliza o motor já testado, agora com datasets temporalmente sincronizados.
    a.horizons = sorted(set(a.horizons))
    events = engine.build_events(m1_sync, m5_sync, a)
    summary = engine.aggregate(events, a.horizons)
    compare = comparison(summary, max(a.horizons))

    events.to_parquet(output / "micro_break_events.parquet", index=False)
    summary.to_csv(output / "micro_break_summary.csv", index=False, encoding="utf-8-sig")
    compare.to_csv(output / "micro_break_same_vs_opposite.csv", index=False, encoding="utf-8-sig")

    metadata = {
        "script": "market_micro_break_confirmation_v3.py",
        "version": "3.0",
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
        "summary_rows": len(summary),
        "comparison_rows": len(compare),
        "horizons": a.horizons,
        "output": str(output),
    }
    (output / "metadata.json").write_text(
        json.dumps(clean(metadata), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(clean(metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
