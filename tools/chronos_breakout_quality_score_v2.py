#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chronos Breakout Quality Score v2.

Corrige a assimetria da v1: body_atr, range_atr e vol_ratio medem intensidade,
não direção. Portanto Q4_HIGH é favorável e Q1_LOW desfavorável para ambos os
lados. RSI, localização e tendência permanecem direcionais.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import chronos_breakout_quality_score as base

MAGNITUDE_BUCKETS = {
    "body_atr_bucket",
    "range_atr_bucket",
    "vol_ratio_bucket",
}


def corrected_qscore(series: pd.Series, side: pd.Series, up_high: bool = True) -> pd.Series:
    """Pontua magnitude de forma simétrica e contexto de forma direcional."""
    name = str(series.name or "")
    high = series.astype(str).eq("Q4_HIGH")
    low = series.astype(str).eq("Q1_LOW")

    if name in MAGNITUDE_BUCKETS:
        result = pd.Series(0, index=series.index, dtype="int8")
        result.loc[high] = 1
        result.loc[low] = -1
        return result

    result = pd.Series(0, index=series.index, dtype="int8")
    up = side.astype(str).eq("UP")
    down = side.astype(str).eq("DOWN")
    if up_high:
        result.loc[up & high] = 1
        result.loc[up & low] = -1
        result.loc[down & low] = 1
        result.loc[down & high] = -1
    else:
        result.loc[up & low] = 1
        result.loc[up & high] = -1
        result.loc[down & high] = 1
        result.loc[down & low] = -1
    return result


def main() -> None:
    original_output = base.DEFAULT_OUTPUT
    try:
        base.DEFAULT_OUTPUT = "data/market_chronos/{symbol}/breakout_quality_score_v2"
        base.qscore = corrected_qscore
        base.main()
    finally:
        base.DEFAULT_OUTPUT = original_output


if __name__ == "__main__":
    main()
