#!/usr/bin/env python3
"""RESUMO — estudo D1 point-in-time + H1/M15/M5, anti-edge e inversão.

O que faz
---------
- Mede o filtro direcional D1 sem look-ahead.
- Usa o dia do broker/MT5 para Open/HighSoFar/LowSoFar.
- Alinha H1 e M15 ao M5 somente depois do fechamento do candle pai.
- Compara baseline MTF, zonas D1, BUY bullish, SELL bearish e no-chase.
- Procura anti-edge: condições consistentemente ruins na direção original.
- Testa a inversão nos MESMOS timestamps para descobrir inverse-edge candidato.
- Testa mean reversion nos extremos D1 com Z-score M5 e rejeição do candle.
- Faz split cronológico 60/20/20, dias independentes e bootstrap por broker day.

Fontes
------
--source live
    data/<SYMBOL>_M5.parquet
    data/<SYMBOL>_M15.parquet
    data/<SYMBOL>_H1.parquet

--source research
    data/market_chronos/candle_base/timeframes/<SYMBOL>_M5_candle_research.parquet
    data/market_chronos/candle_base/timeframes/<SYMBOL>_M15_candle_research.parquet
    data/market_chronos/candle_base/timeframes/<SYMBOL>_H1_candle_research.parquet

Saída
-----
Um único JSON de relatório. Nenhum Parquet intermediário é criado.

Exemplo portátil (Windows/Linux)
--------------------------------
python tools/study_d1_mtf_filter_v2.py --source research --symbol GOLD \
  --rules config/market_intelligence/GOLD_d1_intraday_rules.json \
  --output data/research/GOLD_d1_mtf_filter_report_v2.json

Notas
-----
- Z-score padrão: janela M5=20 e threshold=2.0. São parâmetros de pesquisa,
  não gatilhos live até validação OOS.
- Inverter uma condição ruim não prova edge por si só: custos, slippage e
  estabilidade temporal precisam ser validados antes de promoção live.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import study_d1_mtf_filter as v1

HORIZONS_MIN = v1.HORIZONS_MIN
MIN_TEST_EVENTS = 50
MIN_TEST_DAYS = 10


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    tmp.replace(path)


def invert_side(sample: pd.DataFrame) -> pd.DataFrame:
    x = sample.copy()
    x["side"] = x["side"].map({"BUY": "SELL", "SELL": "BUY"}).fillna(x["side"])
    return x


def metrics_with_days(sample: pd.DataFrame, minutes: int) -> dict[str, Any]:
    out = v1.metrics(sample, minutes)
    usable = sample.dropna(subset=[f"future_delta_{minutes}"])
    out["unique_broker_days"] = int(usable["broker_date"].nunique()) if not usable.empty else 0
    return out


def first_event_per_day_and_side(sample: pd.DataFrame) -> pd.DataFrame:
    if sample.empty:
        return sample
    return sample.sort_values("available_at_brt").drop_duplicates(["broker_date", "side"], keep="first")


def cluster_bootstrap_120(sample: pd.DataFrame, reps: int = 2000, seed: int = 42) -> dict[str, Any]:
    s = sample.dropna(subset=["future_delta_120"]).copy()
    days = list(pd.unique(s["broker_date"]))
    if len(days) < 3 or s.empty:
        return {
            "status": "INSUFFICIENT_INDEPENDENT_DAYS",
            "unique_broker_days": int(len(days)),
            "reps": 0,
        }

    rng = np.random.default_rng(seed)
    wr: list[float] = []
    mean_ret: list[float] = []
    pf: list[float] = []
    grouped = {day: s.loc[s["broker_date"].eq(day)].copy() for day in days}

    for _ in range(reps):
        sampled_days = rng.choice(days, size=len(days), replace=True)
        boot = pd.concat([grouped[day] for day in sampled_days], ignore_index=True)
        m = v1.metrics(boot, 120)
        if m.get("win_rate") is not None:
            wr.append(float(m["win_rate"]))
        if m.get("mean_return") is not None:
            mean_ret.append(float(m["mean_return"]))
        if m.get("profit_factor") is not None and np.isfinite(float(m["profit_factor"])):
            pf.append(float(m["profit_factor"]))

    def ci(values: list[float]) -> list[float] | None:
        if not values:
            return None
        q = np.quantile(np.asarray(values, dtype=float), [0.025, 0.5, 0.975])
        return [float(x) for x in q]

    return {
        "status": "OK",
        "unique_broker_days": int(len(days)),
        "reps": int(reps),
        "win_rate_ci95_median": ci(wr),
        "mean_return_ci95_median": ci(mean_ret),
        "profit_factor_ci95_median": ci(pf),
    }


def add_stretch_features(m5: pd.DataFrame, zscore_window: int) -> pd.DataFrame:
    x = m5.copy()
    close = pd.to_numeric(x["close"], errors="coerce")
    roll_mean = close.rolling(zscore_window, min_periods=zscore_window).mean()
    roll_std = close.rolling(zscore_window, min_periods=zscore_window).std(ddof=0).replace(0, np.nan)
    x[f"m5_zscore_{zscore_window}"] = (close - roll_mean) / roll_std

    open_ = pd.to_numeric(x["open"], errors="coerce")
    high = pd.to_numeric(x["high"], errors="coerce")
    low = pd.to_numeric(x["low"], errors="coerce")
    body = (close - open_).abs()
    upper_wick = high - pd.concat([open_, close], axis=1).max(axis=1)
    lower_wick = pd.concat([open_, close], axis=1).min(axis=1) - low

    false_up = v1.bseries(x["false_breakout_up"]) if "false_breakout_up" in x.columns else pd.Series(False, index=x.index)
    false_down = v1.bseries(x["false_breakout_down"]) if "false_breakout_down" in x.columns else pd.Series(False, index=x.index)

    x["m5_rejection_high"] = false_up | ((close < open_) & (upper_wick >= body))
    x["m5_rejection_low"] = false_down | ((close > open_) & (lower_wick >= body))
    return x


def strategy_specs(df: pd.DataFrame, zscore_window: int, zscore_threshold: float) -> dict[str, dict[str, Any]]:
    base_masks = v1.strategy_masks(df)
    baseline = base_masks["BASELINE_MTF"]
    bullish_buy = (
        df["zone"].eq("BULLISH_CONTINUATION")
        & df["zone_qualified"]
        & df["side"].eq("BUY")
    )
    bearish_sell = (
        df["zone"].eq("BEARISH_CONTINUATION")
        & df["zone_qualified"]
        & df["side"].eq("SELL")
    )
    bullish_counter_sell = (
        df["zone"].eq("BULLISH_CONTINUATION")
        & df["zone_qualified"]
        & df["side"].eq("SELL")
    )
    bearish_counter_buy = (
        df["zone"].eq("BEARISH_CONTINUATION")
        & df["zone_qualified"]
        & df["side"].eq("BUY")
    )
    extreme_high_buy = baseline & df["zone"].eq("EXTREME_HIGH") & df["side"].eq("BUY")
    extreme_low_sell = baseline & df["zone"].eq("EXTREME_LOW") & df["side"].eq("SELL")
    high_trend_context = (
        df["zone"].eq("EXTREME_HIGH")
        & df["H1_direction"].eq("UP")
        & df["M15_direction"].eq("UP")
    )
    low_trend_context = (
        df["zone"].eq("EXTREME_LOW")
        & df["H1_direction"].eq("DOWN")
        & df["M15_direction"].eq("DOWN")
    )

    zcol = f"m5_zscore_{zscore_window}"
    high_z = pd.to_numeric(df[zcol], errors="coerce").ge(zscore_threshold)
    low_z = pd.to_numeric(df[zcol], errors="coerce").le(-zscore_threshold)

    specs: dict[str, dict[str, Any]] = {
        "BASELINE_MTF": {"mask": base_masks["BASELINE_MTF"], "side_mode": "original"},
        "D1_SOFT_DIRECTIONAL": {"mask": base_masks["D1_SOFT_DIRECTIONAL"], "side_mode": "original"},
        "D1_STRICT_ZONE_ONLY": {"mask": base_masks["D1_STRICT_ZONE_ONLY"], "side_mode": "original"},
        "D1_NO_CHASE": {"mask": base_masks["D1_NO_CHASE"], "side_mode": "original"},
        "D1_BULLISH_BUY_ONLY": {"mask": baseline & bullish_buy, "side_mode": "original"},
        "D1_BEARISH_SELL_ONLY": {"mask": baseline & bearish_sell, "side_mode": "original"},
        "D1_BULLISH_COUNTER_SELL": {"mask": baseline & bullish_counter_sell, "side_mode": "original"},
        "D1_BEARISH_COUNTER_BUY": {"mask": baseline & bearish_counter_buy, "side_mode": "original"},
        "D1_EXTREME_HIGH_BUY_CHASE": {"mask": extreme_high_buy, "side_mode": "original"},
        "D1_EXTREME_LOW_SELL_CHASE": {"mask": extreme_low_sell, "side_mode": "original"},
        "D1_EXTREME_HIGH_SELL_INVERSE": {"mask": extreme_high_buy, "side_mode": "invert"},
        "D1_EXTREME_LOW_BUY_INVERSE": {"mask": extreme_low_sell, "side_mode": "invert"},
        "D1_EXTREME_HIGH_ZSCORE_SELL": {"mask": high_trend_context & high_z, "side_mode": "SELL"},
        "D1_EXTREME_LOW_ZSCORE_BUY": {"mask": low_trend_context & low_z, "side_mode": "BUY"},
        "D1_EXTREME_HIGH_ZSCORE_REJECTION_SELL": {
            "mask": high_trend_context & high_z & df["m5_rejection_high"],
            "side_mode": "SELL",
        },
        "D1_EXTREME_LOW_ZSCORE_REJECTION_BUY": {
            "mask": low_trend_context & low_z & df["m5_rejection_low"],
            "side_mode": "BUY",
        },
    }
    return specs


def summarize_strategy(
    df: pd.DataFrame,
    mask: pd.Series,
    split_a: pd.Timestamp,
    split_b: pd.Timestamp,
    side_mode: str = "original",
) -> dict[str, Any]:
    selected = df.loc[mask].copy()
    if side_mode == "invert":
        selected = invert_side(selected)
    elif side_mode in {"BUY", "SELL"}:
        selected["side"] = side_mode

    parts = {
        "all": selected,
        "train": selected[selected["available_at_brt"] < split_a],
        "validation": selected[(selected["available_at_brt"] >= split_a) & (selected["available_at_brt"] < split_b)],
        "test": selected[selected["available_at_brt"] >= split_b],
    }
    out: dict[str, Any] = {}
    for name, part in parts.items():
        out[name] = {str(m): metrics_with_days(part, m) for m in HORIZONS_MIN}
        out[name]["first_event_per_broker_day"] = {
            str(m): metrics_with_days(v1.first_event_per_broker_day(part), m)
            for m in HORIZONS_MIN
        }
        out[name]["first_event_per_broker_day_and_side"] = {
            str(m): metrics_with_days(first_event_per_day_and_side(part), m)
            for m in HORIZONS_MIN
        }
        if name == "test":
            out[name]["day_cluster_bootstrap_120"] = cluster_bootstrap_120(part)
    return out


def _positive_period(m: dict[str, Any]) -> bool:
    return (
        m.get("mean_return") is not None
        and float(m["mean_return"]) > 0
        and m.get("profit_factor") is not None
        and float(m["profit_factor"]) > 1.0
    )


def _negative_period(m: dict[str, Any]) -> bool:
    return (
        m.get("mean_return") is not None
        and float(m["mean_return"]) < 0
        and m.get("profit_factor") is not None
        and float(m["profit_factor"]) < 1.0
    )


def assess_candidate(report: dict[str, Any], name: str) -> dict[str, Any]:
    base = report["strategies"]["BASELINE_MTF"]["test"]["120"]
    cand = report["strategies"][name]["test"]["120"]
    train = report["strategies"][name]["train"]["120"]
    validation = report["strategies"][name]["validation"]["120"]

    reasons: list[str] = []
    positives: list[str] = []
    test_n = int(cand.get("n") or 0)
    test_days = int(cand.get("unique_broker_days") or 0)
    base_n = int(base.get("n") or 0)
    coverage_ratio = (test_n / base_n) if base_n else 0.0

    def gt(metric: str) -> bool:
        a = cand.get(metric)
        b = base.get(metric)
        return a is not None and b is not None and float(a) > float(b)

    wr_ok = (
        cand.get("win_rate") is not None
        and base.get("win_rate") is not None
        and float(cand["win_rate"]) >= float(base["win_rate"])
    )
    exp_ok = gt("mean_return")
    pf_ok = gt("profit_factor")

    if exp_ok:
        positives.append("TEST_EXPECTANCY_IMPROVED")
    else:
        reasons.append("TEST_EXPECTANCY_NOT_IMPROVED")
    if pf_ok:
        positives.append("TEST_PROFIT_FACTOR_IMPROVED")
    else:
        reasons.append("TEST_PROFIT_FACTOR_NOT_IMPROVED")
    if wr_ok:
        positives.append("TEST_WIN_RATE_MAINTAINED_OR_IMPROVED")
    else:
        reasons.append("TEST_WIN_RATE_NOT_MAINTAINED")

    stable_periods = True
    for period_name, period in (("TRAIN", train), ("VALIDATION", validation), ("TEST", cand)):
        if not _positive_period(period):
            stable_periods = False
            if period.get("mean_return") is None or float(period["mean_return"]) <= 0:
                reasons.append(f"{period_name}_EXPECTANCY_NOT_POSITIVE")
            if period.get("profit_factor") is None or float(period["profit_factor"]) <= 1.0:
                reasons.append(f"{period_name}_PF_NOT_ABOVE_1")
    if stable_periods:
        positives.append("TRAIN_VALIDATION_TEST_POSITIVE_AT_120M")

    sample_ok = test_n >= MIN_TEST_EVENTS
    days_ok = test_days >= MIN_TEST_DAYS
    if not sample_ok:
        reasons.append(f"INSUFFICIENT_TEST_EVENTS_LT_{MIN_TEST_EVENTS}")
    if not days_ok:
        reasons.append(f"INSUFFICIENT_INDEPENDENT_TEST_DAYS_LT_{MIN_TEST_DAYS}")

    research_candidate = bool(exp_ok and pf_ok and wr_ok and stable_periods)
    hard_candidate = bool(research_candidate and sample_ok and days_ok)
    mode = "HARD_FILTER_CANDIDATE" if hard_candidate else ("SHADOW_ONLY_CANDIDATE" if research_candidate else "WARNING_ONLY")

    return {
        "candidate": name,
        "hard_filter_candidate": hard_candidate,
        "research_candidate": research_candidate,
        "recommended_enforcement_mode": mode,
        "basis": "120-minute chronological OOS; fixed D1 zones; independent broker-day guard",
        "test_events": test_n,
        "test_unique_broker_days": test_days,
        "test_coverage_vs_baseline": coverage_ratio,
        "positives": positives,
        "reasons": sorted(set(reasons)),
    }


def classify_inverse_edge(original: dict[str, Any], inverse: dict[str, Any]) -> dict[str, Any]:
    o_train = original["train"]["120"]
    o_val = original["validation"]["120"]
    o_test = original["test"]["120"]
    i_train = inverse["train"]["120"]
    i_val = inverse["validation"]["120"]
    i_test = inverse["test"]["120"]

    n = int(o_test.get("n") or 0)
    days = int(o_test.get("unique_broker_days") or 0)
    sample_ok = n >= MIN_TEST_EVENTS and days >= MIN_TEST_DAYS
    stable_anti = all(_negative_period(x) for x in (o_train, o_val, o_test))
    stable_inverse = all(_positive_period(x) for x in (i_train, i_val, i_test))

    test_pf = o_test.get("profit_factor")
    test_mean = o_test.get("mean_return")
    strong_test_anti = (
        test_pf is not None
        and float(test_pf) < 0.75
        and test_mean is not None
        and float(test_mean) < 0
        and sample_ok
    )

    if stable_anti and stable_inverse and sample_ok:
        classification = "INVERSE_EDGE_CANDIDATE"
    elif strong_test_anti:
        classification = "STRONG_ANTI_EDGE"
    elif _negative_period(o_test):
        classification = "ANTI_EDGE"
    elif _positive_period(o_test):
        classification = "EDGE_OR_POSITIVE"
    else:
        classification = "NEUTRAL_OR_UNRESOLVED"

    return {
        "classification": classification,
        "sample_guard_passed": sample_ok,
        "stable_anti_edge_train_validation_test": stable_anti,
        "stable_inverse_train_validation_test": stable_inverse,
        "test_events": n,
        "test_unique_broker_days": days,
        "original_test_120": o_test,
        "inverse_test_120": i_test,
        "note": "Inverse uses the exact same timestamps with BUY/SELL swapped; transaction costs are not yet deducted.",
    }


def build_anchor(
    input_dir: Path,
    symbol: str,
    rules: dict[str, Any],
    source: str,
    zscore_window: int,
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp, dict[str, int], dict[str, str]]:
    if source == "research":
        root = input_dir / "market_chronos" / "candle_base" / "timeframes"
        paths = {
            "M5": root / f"{symbol}_M5_candle_research.parquet",
            "M15": root / f"{symbol}_M15_candle_research.parquet",
            "H1": root / f"{symbol}_H1_candle_research.parquet",
        }
    else:
        paths = {
            "M5": input_dir / f"{symbol}_M5.parquet",
            "M15": input_dir / f"{symbol}_M15.parquet",
            "H1": input_dir / f"{symbol}_H1.parquet",
        }

    for tf, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"Fonte {source}: arquivo {tf} não encontrado: {path}")

    m5 = v1.prepare(paths["M5"], "M5", rules)
    m5 = v1.add_d1_point_in_time(m5)
    m5 = v1.add_future_outcomes(m5)
    m5 = add_stretch_features(m5, zscore_window)
    m15 = v1.prepare(paths["M15"], "M15", rules)
    h1 = v1.prepare(paths["H1"], "H1", rules)

    anchor = m5.loc[v1.in_window(m5["available_at_brt"], rules)].copy()
    anchor = v1.merge_parent(anchor, m15, "M15")
    anchor = v1.merge_parent(anchor, h1, "H1")
    anchor["M5_direction"] = anchor["direction"]
    anchor["side"] = np.where(
        (anchor["H1_direction"] == "UP") & (anchor["M15_direction"] == "UP") & (anchor["M5_direction"] == "UP"),
        "BUY",
        np.where(
            (anchor["H1_direction"] == "DOWN") & (anchor["M15_direction"] == "DOWN") & (anchor["M5_direction"] == "DOWN"),
            "SELL",
            "NONE",
        ),
    )

    zones = [v1.zone_name(float(p), str(d), rules) for p, d in zip(anchor["d1_position"], anchor["daily_direction"])]
    anchor["zone"] = [z[0] for z in zones]
    anchor["zone_qualified"] = [z[1] for z in zones]

    baseline_events = anchor[anchor["side"].isin(["BUY", "SELL"])].copy()
    split_a, split_b = v1.split_edges(baseline_events)
    coverage = {
        "m5_rows": int(len(m5)),
        "m15_rows": int(len(m15)),
        "h1_rows": int(len(h1)),
        "anchor_operational_rows": int(len(anchor)),
        "baseline_aligned_events": int(len(baseline_events)),
        "baseline_broker_days": int(baseline_events["broker_date"].nunique()),
    }
    return anchor, split_a, split_b, coverage, {k: str(v) for k, v in paths.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description="D1 broker-day + MTF study with anti-edge, inverse-edge and mean reversion research.")
    ap.add_argument("--input-dir", type=Path, default=Path("data"))
    ap.add_argument("--source", choices=("live", "research"), default="live")
    ap.add_argument("--symbol", default="GOLD")
    ap.add_argument("--rules", type=Path, default=Path("config/market_intelligence/GOLD_d1_intraday_rules.json"))
    ap.add_argument("--output", type=Path, default=Path("data/research/GOLD_d1_mtf_filter_report_v2.json"))
    ap.add_argument("--zscore-window", type=int, default=20)
    ap.add_argument("--zscore-threshold", type=float, default=2.0)
    args = ap.parse_args()

    if args.zscore_window < 5:
        raise ValueError("--zscore-window deve ser >= 5")
    if args.zscore_threshold <= 0:
        raise ValueError("--zscore-threshold deve ser > 0")

    symbol = args.symbol.upper()
    rules = v1.load_json(args.rules)
    anchor, split_a, split_b, coverage, source_paths = build_anchor(
        args.input_dir,
        symbol,
        rules,
        args.source,
        args.zscore_window,
    )
    specs = strategy_specs(anchor, args.zscore_window, args.zscore_threshold)

    report: dict[str, Any] = {
        "schema_version": "1.2",
        "symbol": symbol,
        "source": args.source,
        "methodology": {
            "daily_boundary": "MT5 broker day",
            "broker_timezone": (rules.get("daily_session_clock", {}) or {}).get("timezone"),
            "operational_window_brt": rules.get("operational_window_brt"),
            "lookahead_safe_d1": True,
            "higher_tf_availability": "H1/M15 direction becomes eligible only after parent candle closes",
            "mtf_baseline": "H1 == M15 == M5 direction",
            "split": "chronological 60/20/20 on baseline aligned events",
            "thresholds_frozen_before_test": [0.10, 0.30, 0.70, 0.90],
            "zscore": {
                "timeframe": "M5",
                "window": int(args.zscore_window),
                "threshold": float(args.zscore_threshold),
                "formula": "(close - rolling_mean) / rolling_std_population",
                "point_in_time_only": True,
            },
            "rejection": {
                "high": "false_breakout_up OR bearish candle with upper_wick >= body",
                "low": "false_breakout_down OR bullish candle with lower_wick >= body",
                "point_in_time_only": True,
            },
            "inverse_edge": "same timestamps, BUY/SELL swapped; no transaction costs deducted",
            "promotion_guard": f"hard candidate requires >={MIN_TEST_EVENTS} test events and >={MIN_TEST_DAYS} independent broker days",
        },
        "source_paths": source_paths,
        "coverage": {
            **coverage,
            "split_validation_start": split_a.isoformat() if split_a is not pd.Timestamp.min else None,
            "split_test_start": split_b.isoformat() if split_b is not pd.Timestamp.min else None,
        },
        "zone_counts": {
            str(k): int(v)
            for k, v in anchor.groupby(["zone", "daily_direction"], dropna=False).size().to_dict().items()
        },
        "strategies": {},
        "inverse_edge_scan": {},
    }

    for name, spec in specs.items():
        report["strategies"][name] = summarize_strategy(
            anchor,
            spec["mask"],
            split_a,
            split_b,
            side_mode=str(spec["side_mode"]),
        )

    for name, spec in specs.items():
        if str(spec["side_mode"]) != "original":
            continue
        original = report["strategies"][name]
        inverse = summarize_strategy(anchor, spec["mask"], split_a, split_b, side_mode="invert")
        report["inverse_edge_scan"][name] = classify_inverse_edge(original, inverse)

    directional_candidates = [
        "D1_SOFT_DIRECTIONAL",
        "D1_STRICT_ZONE_ONLY",
        "D1_BULLISH_BUY_ONLY",
        "D1_BEARISH_SELL_ONLY",
        "D1_BULLISH_COUNTER_SELL",
        "D1_BEARISH_COUNTER_BUY",
        "D1_NO_CHASE",
    ]
    report["promotion_assessment"] = {
        name: assess_candidate(report, name)
        for name in directional_candidates
    }

    mean_reversion_candidates = [
        "D1_EXTREME_HIGH_SELL_INVERSE",
        "D1_EXTREME_LOW_BUY_INVERSE",
        "D1_EXTREME_HIGH_ZSCORE_SELL",
        "D1_EXTREME_LOW_ZSCORE_BUY",
        "D1_EXTREME_HIGH_ZSCORE_REJECTION_SELL",
        "D1_EXTREME_LOW_ZSCORE_REJECTION_BUY",
    ]
    report["mean_reversion_assessment"] = {
        name: assess_candidate(report, name)
        for name in mean_reversion_candidates
    }

    inverse_candidates = [
        name
        for name, data in report["inverse_edge_scan"].items()
        if data.get("classification") in {"INVERSE_EDGE_CANDIDATE", "STRONG_ANTI_EDGE"}
    ]

    def compact(name: str) -> dict[str, Any]:
        m = report["strategies"][name]["test"]["120"]
        return {
            "n": m.get("n"),
            "days": m.get("unique_broker_days"),
            "win_rate": m.get("win_rate"),
            "mean_return": m.get("mean_return"),
            "profit_factor": m.get("profit_factor"),
        }

    key_names = [
        "BASELINE_MTF",
        "D1_BULLISH_BUY_ONLY",
        "D1_BEARISH_SELL_ONLY",
        "D1_BULLISH_COUNTER_SELL",
        "D1_BEARISH_COUNTER_BUY",
        "D1_EXTREME_HIGH_BUY_CHASE",
        "D1_EXTREME_HIGH_SELL_INVERSE",
        "D1_EXTREME_HIGH_ZSCORE_SELL",
        "D1_EXTREME_HIGH_ZSCORE_REJECTION_SELL",
        "D1_EXTREME_LOW_SELL_CHASE",
        "D1_EXTREME_LOW_BUY_INVERSE",
        "D1_EXTREME_LOW_ZSCORE_BUY",
        "D1_EXTREME_LOW_ZSCORE_REJECTION_BUY",
    ]
    report["key_results_120m_oos"] = {name: compact(name) for name in key_names}

    save_json(args.output, report)
    print(json.dumps({
        "status": "ok",
        "source": args.source,
        "output": str(args.output),
        "input_rows": {"M5": coverage["m5_rows"], "M15": coverage["m15_rows"], "H1": coverage["h1_rows"]},
        "baseline_events": coverage["baseline_aligned_events"],
        "baseline_broker_days": coverage["baseline_broker_days"],
        "zscore": {"window": args.zscore_window, "threshold": args.zscore_threshold},
        "inverse_edge_candidates": inverse_candidates,
        "key_results_120m_oos": report["key_results_120m_oos"],
        "mean_reversion_assessment": report["mean_reversion_assessment"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
