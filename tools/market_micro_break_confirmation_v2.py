#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hotfix da pesquisa de microconfirmação M5 -> M1.

Corrige o NameError da função comparison() da versão 1 sem duplicar o motor.
"""
from __future__ import annotations

import pandas as pd

import market_micro_break_confirmation as engine


def comparison(summary: pd.DataFrame, horizon: int) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()

    rows = []
    for (side, mode), group in summary.groupby(["side", "break_mode"]):
        same = group[group["color_relation"].eq("SAME_COLOR")]
        opposite = group[group["color_relation"].eq("OPPOSITE_COLOR")]
        if same.empty or opposite.empty:
            continue

        s = same.iloc[0]
        o = opposite.iloc[0]
        rows.append({
            "side": side,
            "break_mode": mode,
            "same_color_sample": int(s["sample_size"]),
            "opposite_color_sample": int(o["sample_size"]),
            f"success_lift_{horizon}": float(
                s[f"success_rate_{horizon}"] - o[f"success_rate_{horizon}"]
            ),
            f"return_lift_{horizon}_atr": float(
                s[f"avg_return_{horizon}_atr"] - o[f"avg_return_{horizon}_atr"]
            ),
            f"mae_reduction_{horizon}_atr": float(
                o[f"avg_mae_{horizon}_atr"] - s[f"avg_mae_{horizon}_atr"]
            ),
            "false_break_reduction": float(
                o["false_breakout_rate"] - s["false_breakout_rate"]
            ),
            "same_color_preferred": bool(
                s[f"success_rate_{horizon}"] > o[f"success_rate_{horizon}"]
                and s[f"avg_return_{horizon}_atr"] > o[f"avg_return_{horizon}_atr"]
            ),
        })

    return pd.DataFrame(rows)


engine.comparison = comparison


if __name__ == "__main__":
    engine.main()
