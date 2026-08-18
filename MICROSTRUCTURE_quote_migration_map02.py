#!/usr/bin/env python3
"""MICROSTRUCTURE QUOTE-MIGRATION MAP 02.

Threshold-free test of causal signed MID migration at Map01R PASS time.
Scientific contract: docs/MICROSTRUCTURE_QUOTE_MIGRATION_MAP02.md

Historical mode is diagnostic only. Prospective mode seals AUC scores until
frozen maturity is reached.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

FRESH_START = pd.Timestamp("2026-08-19")
MATURITY_DAYS = 20
MATURITY_EVENTS = 200_000
BOOT_N = 5000
BOOT_SEED = 2026081801

PRIMARY_X = "pass_signed_mid_impulse_1s_points"
PRIMARY_Y = "hit_200_before_retest"
COMPLETE = "outcome_complete_before_retest_60s"

SECONDARY_FEATURES = (
    "pass_spread_ratio",
    "pass_tick_rate_ratio_1s",
    "pass_tick_accel_1s_vs_prev4s",
)

REQUIRED = {
    "mark_id",
    "birth_day",
    "pass_no",
    COMPLETE,
    PRIMARY_X,
    PRIMARY_Y,
}

OPTIONAL = {
    "direction",
    "mfe_60_points",
    "hit_50_before_retest",
    "hit_100_before_retest",
    "hit_300_before_retest",
    *SECONDARY_FEATURES,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Frozen Quote Migration Map02 scorer")
    p.add_argument(
        "--input",
        action="append",
        required=True,
        help="Compact Map01R passes CSV or CSV.GZ. Repeat for multiple chronological blocks.",
    )
    p.add_argument(
        "--mode", choices=("historical", "prospective"), default="historical"
    )
    return p.parse_args()


def pass_group(s: pd.Series) -> pd.Series:
    n = pd.to_numeric(s, errors="coerce")
    return pd.Series(
        np.where(n.eq(1), "PASS1", np.where(n.eq(2), "PASS2", "PASS3+")),
        index=s.index,
    )


def auc_rank(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    good = np.isfinite(x) & np.isfinite(y)
    x = x[good]
    y = y[good]
    if len(x) == 0:
        return np.nan
    pos = y == 1.0
    neg = y == 0.0
    n1 = int(pos.sum())
    n0 = int(neg.sum())
    if n1 == 0 or n0 == 0:
        return np.nan
    ranks = pd.Series(x).rank(method="average").to_numpy(float)
    u = float(ranks[pos].sum() - n1 * (n1 + 1) / 2.0)
    return u / (n1 * n0)


def bootstrap_equal_day_mean(a: np.ndarray) -> tuple[float, float, float]:
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) == 0:
        return np.nan, np.nan, np.nan
    est = float(a.mean())
    if len(a) < 2:
        return est, np.nan, np.nan
    rng = np.random.default_rng(BOOT_SEED)
    picks = rng.integers(0, len(a), size=(BOOT_N, len(a)))
    boot = a[picks].mean(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return est, float(lo), float(hi)


def load_inputs(paths: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            raise SystemExit(f"input not found: {path}")
        header = pd.read_csv(path, nrows=0)
        cols = list(header.columns)
        missing = sorted(REQUIRED - set(cols))
        if missing:
            raise SystemExit(f"{path.name}: missing required columns: {missing}")
        use = [c for c in cols if c in REQUIRED or c in OPTIONAL]
        print(f"LOAD {path} | columns={len(use)}/{len(cols)}", flush=True)
        frame = pd.read_csv(path, usecols=use, low_memory=False)
        frame["source_file"] = path.name
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["birth_day"] = pd.to_datetime(df["birth_day"], errors="coerce").dt.normalize()
    for c in ["pass_no", COMPLETE, PRIMARY_X, PRIMARY_Y, *SECONDARY_FEATURES]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def reproduction_guards(df: pd.DataFrame) -> None:
    if df.empty:
        raise SystemExit("no rows loaded")
    if df["birth_day"].isna().any():
        raise SystemExit("GUARD FAIL: invalid birth_day")
    ident = df[["mark_id", "pass_no"]]
    dup = ident.duplicated(keep=False)
    if dup.any():
        sample = df.loc[dup, ["mark_id", "pass_no", "source_file"]].head(10)
        print(sample.to_string(index=False))
        raise SystemExit(
            f"GUARD FAIL: duplicate (mark_id, pass_no) rows = {int(dup.sum())}"
        )
    bad_complete = ~df[COMPLETE].dropna().isin([0, 1])
    bad_y = ~df[PRIMARY_Y].dropna().isin([0, 1])
    if bad_complete.any() or bad_y.any():
        raise SystemExit("GUARD FAIL: binary columns contain values outside {0,1}")
    print("REPRODUCTION_GUARDS = PASS")


def eligible(df: pd.DataFrame) -> pd.DataFrame:
    z = df.loc[
        df[COMPLETE].eq(1)
        & np.isfinite(df[PRIMARY_X])
        & df[PRIMARY_Y].isin([0, 1])
    ].copy()
    z["pass_group"] = pass_group(z["pass_no"])
    return z


def daily_auc_table(z: pd.DataFrame, feature: str) -> pd.DataFrame:
    rows: list[dict] = []
    for (day, group), g in z.groupby(["birth_day", "pass_group"], sort=True):
        q = g.loc[np.isfinite(g[feature]) & g[PRIMARY_Y].isin([0, 1])]
        if q.empty:
            continue
        n_pos = int(q[PRIMARY_Y].eq(1).sum())
        n_neg = int(q[PRIMARY_Y].eq(0).sum())
        if n_pos == 0 or n_neg == 0:
            continue
        rows.append(
            {
                "birth_day": day,
                "pass_group": group,
                "feature": feature,
                "n": int(len(q)),
                "n_pos": n_pos,
                "n_neg": n_neg,
                "auc": auc_rank(q[feature].to_numpy(), q[PRIMARY_Y].to_numpy()),
            }
        )
    return pd.DataFrame(rows)


def score_primary(z: pd.DataFrame) -> list[dict]:
    d = daily_auc_table(z, PRIMARY_X)
    results: list[dict] = []
    for group in ("PASS1", "PASS2", "PASS3+"):
        g = d.loc[d["pass_group"].eq(group)] if not d.empty else pd.DataFrame()
        vals = g["auc"].to_numpy(float) if not g.empty else np.array([])
        est, lo, hi = bootstrap_equal_day_mean(vals)
        q = z.loc[z["pass_group"].eq(group)]
        pooled = auc_rank(q[PRIMARY_X].to_numpy(), q[PRIMARY_Y].to_numpy()) if len(q) else np.nan
        results.append(
            {
                "pass_group": group,
                "eligible_days": int(len(vals)),
                "events": int(len(q)),
                "mean_daily_auc": est,
                "ci95_lo": lo,
                "ci95_hi": hi,
                "pooled_auc_descriptive": pooled,
                "full_pass": bool(np.isfinite(lo) and est > 0.5 and lo > 0.5),
            }
        )
    return results


def print_primary(results: list[dict]) -> None:
    print()
    print("PRIMARY — SIGNED MID IMPULSE 1s -> HIT +200 BEFORE RETEST")
    for r in results:
        print(
            f"{r['pass_group']:<6} days={r['eligible_days']:>3} events={r['events']:>9} "
            f"mean_daily_AUC={r['mean_daily_auc']:.5f} "
            f"CI95=[{r['ci95_lo']:.5f},{r['ci95_hi']:.5f}] "
            f"pooled_AUC={r['pooled_auc_descriptive']:.5f}"
        )


def print_secondary(z: pd.DataFrame) -> None:
    print()
    print("SECONDARY MECHANISTIC CONTROLS — DESCRIPTIVE ONLY")
    for feature in SECONDARY_FEATURES:
        if feature not in z.columns:
            continue
        print(f"\n{feature}")
        for group in ("PASS1", "PASS2", "PASS3+"):
            q = z.loc[
                z["pass_group"].eq(group)
                & np.isfinite(z[feature])
                & z[PRIMARY_Y].isin([0, 1])
            ]
            a = auc_rank(q[feature].to_numpy(), q[PRIMARY_Y].to_numpy()) if len(q) else np.nan
            print(f"  {group:<6} n={len(q):>9} pooled_AUC={a:.5f}")


def main() -> int:
    args = parse_args()
    print("=" * 120)
    print("MICROSTRUCTURE QUOTE-MIGRATION MAP 02 — THRESHOLD-FREE PASSAGE-EFFICIENCY LAW")
    print("=" * 120)
    print(f"mode              = {args.mode.upper()}")
    print(f"primary X         = {PRIMARY_X}")
    print(f"primary Y         = {PRIMARY_Y}")
    print("pass strata       = PASS1 / PASS2 / PASS3+")
    print("primary statistic = equal-BRT-day mean AUC")
    print(f"bootstrap         = N={BOOT_N} seed={BOOT_SEED}")
    print(f"fresh start       = {FRESH_START.date()} 00:00 BRT")
    print(f"maturity          = {MATURITY_DAYS} eligible days + {MATURITY_EVENTS} complete PASS events")
    print("runtime promotion = NONE")

    df = load_inputs(args.input)
    reproduction_guards(df)

    if args.mode == "prospective":
        df = df.loc[df["birth_day"].ge(FRESH_START)].copy()
        print(f"PROSPECTIVE_DATE_FILTER = >= {FRESH_START.date()}")

    z = eligible(df)
    days = int(z["birth_day"].nunique()) if not z.empty else 0
    print()
    print("ELIGIBLE UNIVERSE")
    print(f"rows_loaded        = {len(df)}")
    print(f"complete_events    = {len(z)}")
    print(f"BRT_days           = {days}")
    if not z.empty:
        print(f"first_day          = {z['birth_day'].min().date()}")
        print(f"last_day           = {z['birth_day'].max().date()}")
        print("pass_groups:")
        print(z["pass_group"].value_counts().reindex(["PASS1", "PASS2", "PASS3+"]).fillna(0).astype(int).to_string())

    if args.mode == "prospective" and (days < MATURITY_DAYS or len(z) < MATURITY_EVENTS):
        print()
        print("MAP02_PROSPECTIVE_STATUS = ACCUMULATING")
        print("PRIMARY_SCORES = SEALED")
        print(f"days_progress   = {days}/{MATURITY_DAYS}")
        print(f"event_progress  = {len(z)}/{MATURITY_EVENTS}")
        print("NO AUC / CI / DIRECTIONAL SCORE WAS COMPUTED")
        return 0

    results = score_primary(z)
    print_primary(results)
    print_secondary(z)

    if args.mode == "historical":
        print()
        print("MAP02_RESULT_STATUS = HISTORICAL_DIAGNOSTIC_ONLY")
        print("FORMAL_VALIDATION = NO")
        print("The predictor was selected after Map01R inspection; these rows are not fresh OOS.")
    else:
        full = all(r["full_pass"] for r in results)
        print()
        print("MAP02_PROSPECTIVE_STATUS = MATURE")
        print(f"MAP02_PRIMARY_FULL_PASS = {'YES' if full else 'NO'}")
        print("NO SIGN INVERSION / THRESHOLD RESCUE AUTHORIZED")

    print("RUNTIME_PROMOTION = NONE")
    print("EXP27 = UNTOUCHED / SCORES SEALED")
    print("CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
