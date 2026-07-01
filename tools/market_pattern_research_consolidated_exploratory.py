#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Perfil exploratório para a pesquisa consolidada de figuras.

Usa o mesmo detector canônico, mas com filtros menos restritivos para descobrir
onde existem populações suficientes antes da validação estrita.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import market_pattern_research_consolidated as base


def main() -> None:
    original_argv = sys.argv[:]
    try:
        user_args = sys.argv[1:]
        defaults = [
            "--windows", "8", "12", "20", "30", "40", "60",
            "--min-r2", "0.30",
            "--min-compression", "0.08",
            "--slope-flat", "0.06",
            "--slope-directional", "0.008",
            "--max-range-width-atr", "6.0",
            "--touch-tolerance-atr", "0.35",
            "--min-touches", "1",
            "--breakout-buffer-atr", "0.03",
            "--min-sample", "10",
            "--min-block", "3",
            "--output", "data/market_chronos/{symbol}/patterns/consolidated_research_exploratory",
        ]
        sys.argv = [sys.argv[0], *defaults, *user_args]
        base.main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
