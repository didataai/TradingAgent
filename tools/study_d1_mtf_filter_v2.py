#!/usr/bin/env python3
"""RESUMO — estudo D1 point-in-time + H1/M15/M5.

O que faz
---------
- Mede o filtro direcional D1 sem look-ahead.
- Usa o dia do broker/MT5 para Open/HighSoFar/LowSoFar.
- Alinha H1 e M15 ao M5 somente depois do fechamento do candle pai.
- Compara baseline MTF, zonas D1, BUY bullish, SELL bearish e no-chase.
- Faz split cronológico 60/20/20, contagem de dias independentes e bootstrap por dia.

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


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    tmp.replace(path)


def metrics_with_days(sample: pd.DataFrame, minutes: int) -> dict[str, Any]:
    out = v1.metrics(sample, minutes)
    usable = sample.dropna(subset=[f"future_delta_{minutes}"])
    out["unique_broker_days"] = (
        int(usable["broker_date"].nunique()) if not usable.empty else 0
    )
    return out


def first_event_per_day_and_side(sample: pd.DataFrame) -> pd.DataFrame:
    if sample.empty:
        return sample
    return (
        sample.sort_values("available_at_brt")
        .drop_duplicates(["broker_date", "side"], keep="first")
    )


def cluster_bootstrap_120(
    sample: pd.DataFrame,
    reps: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
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
    grouped = {
        day: s.loc[s["broker_date"].eq(day)].copy()
        for day in days
    }

    for _ in range(reps):
        sampled_days = rng.choice(days, size=len(days), replace=True)
        boot = pd.concat(
            [grouped[day] for day in sampled_days],
            ignore_index=True,
        )
        m = v1.metrics(boot, 120)
        if m.get("win_rate") is not None:
            wr.append(float(m["win_rate"]))
        if m.get("mean_return") is not None:
            mean_ret.append(float(m["mean_return"]))
        if (
            m.get("profit_factor") is not None
            and np.isfinite(float(m["profit_factor"]))
        ):
            pf.append(float(m["profit_factor"]))

    def ci(values: list[float]) -> list[float] | None:
        if not values:
            return None
        q = np.quantile(
            np.asarray(values, dtype=float),
            [0.025, 0.5, 0.975],
        )
        return [float(x) for x in q]

    return {
        "status": "OK",
        "unique_broker_days": int(len(days)),
        "reps": int(reps),
        "win_rate_ci95_median": ci(wr),
        "mean_return_ci95_median": ci(mean_ret),
        "profit_factor_ci95_median": ci(pf),
    }


def strategy_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    masks = v1.strategy_masks(df)
    baseline = masks["BASELINE_MTF"]

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

    masks.update(
        {
            "D1_BULLISH_BUY_ONLY": baseline & bullish_buy,
            "D1_BEARISH_SELL_ONLY": baseline & bearish_sell,
            "D1_EXTREME_HIGH_BUY_CHASE": (
                baseline
                & df["zone"].eq("EXTREME_HIGH")
                & df["side"].eq("BUY")
            ),
            "D1_EXTREME_LOW_SELL_CHASE": (
                baseline
                & df["zone"].eq("EXTREME_LOW")
                & df["side"].eq("SELL")
            ),
        }
    )
    return masks


def summarize_strategy(
    df: pd.DataFrame,
    mask: pd.Series,
    split_a: pd.Timestamp,
    split_b: pd.Timestamp,
) -> dict[str, Any]:
    selected = df.loc[mask].copy()
    parts = {
        "all": selected,
        "train": selected[selected["available_at_brt"] < split_a],
        "validation": selected[
            (selected["available_at_brt"] >= split_a)
            & (selected["available_at_brt"] < split_b)
        ],
        "test": selected[selected["available_at_brt"] >= split_b],
    }

    out: dict[str, Any] = {}
    for name, part in parts.items():
        out[name] = {
            str(m): metrics_with_days(part, m)
            for m in HORIZONS_MIN
        }
        out[name]["first_event_per_broker_day"] = {
            str(m): metrics_with_days(
                v1.first_event_per_broker_day(part),
                m,
            )
            for m in HORIZONS_MIN
        }
        out[name]["first_event_per_broker_day_and_side"] = {
            str(m): metrics_with_days(
                first_event_per_day_and_side(part),
                m,
            )
            for m in HORIZONS_MIN
        }
        if name == "test":
            out[name]["day_cluster_bootstrap_120"] = (
                cluster_bootstrap_120(part)
            )
    return out


def assess_candidate(
    report: dict[str, Any],
    name: str,
) -> dict[str, Any]:
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
        return (
            a is not None
            and b is not None
            and float(a) > float(b)
        )

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
    for period_name, period in (
        ("TRAIN", train),
        ("VALIDATION", validation),
        ("TEST", cand),
    ):
        mean_ret = period.get("mean_return")
        pf = period.get("profit_factor")
        if mean_ret is None or float(mean_ret) <= 0:
            stable_periods = False
            reasons.append(
                f"{period_name}_EXPECTANCY_NOT_POSITIVE"
            )
        if pf is None or float(pf) <= 1.0:
            stable_periods = False
            reasons.append(f"{period_name}_PF_NOT_ABOVE_1")

    if stable_periods:
        positives.append(
            "TRAIN_VALIDATION_TEST_POSITIVE_AT_120M"
        )

    sample_ok = test_n >= 50
    days_ok = test_days >= 10
    if not sample_ok:
        reasons.append("INSUFFICIENT_TEST_EVENTS_LT_50")
    if not days_ok:
        reasons.append(
            "INSUFFICIENT_INDEPENDENT_TEST_DAYS_LT_10"
        )

    research_candidate = bool(
        exp_ok and pf_ok and wr_ok and stable_periods
    )
    hard_candidate = bool(
        research_candidate and sample_ok and days_ok
    )

    if hard_candidate:
        mode = "HARD_FILTER_CANDIDATE"
    elif research_candidate:
        mode = "SHADOW_ONLY_CANDIDATE"
    else:
        mode = "WARNING_ONLY"

    return {
        "candidate": name,
        "hard_filter_candidate": hard_candidate,
        "research_candidate": research_candidate,
        "recommended_enforcement_mode": mode,
        "basis": (
            "120-minute chronological OOS; fixed D1 zones; "
            "independent broker-day guard"
        ),
        "test_events": test_n,
        "test_unique_broker_days": test_days,
        "test_coverage_vs_baseline": coverage_ratio,
        "positives": positives,
        "reasons": sorted(set(reasons)),
    }


def resolve_input_paths(
    input_dir: Path,
    research_dir: Path,
    symbol: str,
    source: str,
) -> dict[str, Path]:
    if source == "research":
        paths = {
            tf: research_dir
            / f"{symbol}_{tf}_candle_research.parquet"
            for tf in ("M5", "M15", "H1")
        }
    else:
        paths = {
            tf: input_dir / f"{symbol}_{tf}.parquet"
            for tf in ("M5", "M15", "H1")
        }

    missing = [
        str(path)
        for path in paths.values()
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Arquivos de entrada ausentes: " + ", ".join(missing)
        )
    return paths


def build_anchor(
    paths: dict[str, Path],
    rules: dict[str, Any],
) -> tuple[
    pd.DataFrame,
    pd.Timestamp,
    pd.Timestamp,
    dict[str, int],
]:
    m5 = v1.add_future_outcomes(
        v1.add_d1_point_in_time(
            v1.prepare(paths["M5"], "M5", rules)
        )
    )
    m15 = v1.prepare(paths["M15"], "M15", rules)
    h1 = v1.prepare(paths["H1"], "H1", rules)

    anchor = m5.loc[
        v1.in_window(m5["available_at_brt"], rules)
    ].copy()
    anchor = v1.merge_parent(anchor, m15, "M15")
    anchor = v1.merge_parent(anchor, h1, "H1")
    anchor["M5_direction"] = anchor["direction"]

    anchor["side"] = np.where(
        (
            (anchor["H1_direction"] == "UP")
            & (anchor["M15_direction"] == "UP")
            & (anchor["M5_direction"] == "UP")
        ),
        "BUY",
        np.where(
            (
                (anchor["H1_direction"] == "DOWN")
                & (anchor["M15_direction"] == "DOWN")
                & (anchor["M5_direction"] == "DOWN")
            ),
            "SELL",
            "NONE",
        ),
    )

    zones = [
        v1.zone_name(float(p), str(d), rules)
        for p, d in zip(
            anchor["d1_position"],
            anchor["daily_direction"],
        )
    ]
    anchor["zone"] = [z[0] for z in zones]
    anchor["zone_qualified"] = [z[1] for z in zones]

    baseline_events = anchor[
        anchor["side"].isin(["BUY", "SELL"])
    ].copy()
    split_a, split_b = v1.split_edges(baseline_events)

    coverage = {
        "m5_rows": int(len(m5)),
        "m15_rows": int(len(m15)),
        "h1_rows": int(len(h1)),
        "anchor_operational_rows": int(len(anchor)),
        "baseline_aligned_events": int(len(baseline_events)),
        "baseline_broker_days": int(
            baseline_events["broker_date"].nunique()
        ),
    }
    return anchor, split_a, split_b, coverage


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "D1 broker-day + H1/M15/M5 study v2 "
            "with live/research source, side split "
            "and day-cluster validation."
        )
    )
    ap.add_argument(
        "--source",
        choices=("live", "research"),
        default="live",
        help=(
            "live usa data/<symbol>_<TF>.parquet; "
            "research usa candle_base/timeframes."
        ),
    )
    ap.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data"),
    )
    ap.add_argument(
        "--research-dir",
        type=Path,
        default=Path(
            "data/market_chronos/candle_base/timeframes"
        ),
    )
    ap.add_argument("--symbol", default="GOLD")
    ap.add_argument(
        "--rules",
        type=Path,
        default=Path(
            "config/market_intelligence/"
            "GOLD_d1_intraday_rules.json"
        ),
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/research/"
            "GOLD_d1_mtf_filter_report_v2.json"
        ),
    )
    args = ap.parse_args()

    symbol = args.symbol.upper()
    rules = v1.load_json(args.rules)
    paths = resolve_input_paths(
        args.input_dir,
        args.research_dir,
        symbol,
        args.source,
    )

    anchor, split_a, split_b, coverage = build_anchor(
        paths,
        rules,
    )
    masks = strategy_masks(anchor)

    report: dict[str, Any] = {
        "schema_version": "1.2",
        "symbol": symbol,
        "source": args.source,
        "input_paths": {
            tf: str(path)
            for tf, path in paths.items()
        },
        "methodology": {
            "daily_boundary": "MT5 broker day",
            "broker_timezone": (
                rules.get("daily_session_clock", {}) or {}
            ).get("timezone"),
            "operational_window_brt": rules.get(
                "operational_window_brt"
            ),
            "lookahead_safe_d1": True,
            "higher_tf_availability": (
                "H1/M15 direction becomes eligible "
                "only after parent candle closes"
            ),
            "mtf_baseline": (
                "H1 == M15 == M5 direction"
            ),
            "split": (
                "chronological 60/20/20 "
                "on baseline aligned events"
            ),
            "thresholds_frozen_before_test": [
                0.10,
                0.30,
                0.70,
                0.90,
            ],
            "promotion_guard": (
                "hard candidate requires >=50 test events "
                "and >=10 independent broker days"
            ),
            "intermediate_parquet_created": False,
        },
        "coverage": {
            **coverage,
            "split_validation_start": (
                split_a.isoformat()
                if split_a is not pd.Timestamp.min
                else None
            ),
            "split_test_start": (
                split_b.isoformat()
                if split_b is not pd.Timestamp.min
                else None
            ),
        },
        "zone_counts": {
            str(k): int(v)
            for k, v in anchor.groupby(
                ["zone", "daily_direction"],
                dropna=False,
            ).size().to_dict().items()
        },
        "strategies": {},
    }

    for name, mask in masks.items():
        report["strategies"][name] = summarize_strategy(
            anchor,
            mask,
            split_a,
            split_b,
        )

    candidates = [
        "D1_SOFT_DIRECTIONAL",
        "D1_STRICT_ZONE_ONLY",
        "D1_BULLISH_BUY_ONLY",
        "D1_BEARISH_SELL_ONLY",
        "D1_NO_CHASE",
    ]
    report["promotion_assessment"] = {
        name: assess_candidate(report, name)
        for name in candidates
    }

    save_json(args.output, report)
    print(
        json.dumps(
            {
                "status": "ok",
                "source": args.source,
                "output": str(args.output),
                "input_rows": {
                    "M5": coverage["m5_rows"],
                    "M15": coverage["m15_rows"],
                    "H1": coverage["h1_rows"],
                },
                "baseline_events": (
                    coverage["baseline_aligned_events"]
                ),
                "baseline_broker_days": (
                    coverage["baseline_broker_days"]
                ),
                "promotion_assessment": (
                    report["promotion_assessment"]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
