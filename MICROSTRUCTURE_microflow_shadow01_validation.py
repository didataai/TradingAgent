#!/usr/bin/env python3
"""Sealed prospective validator for the frozen MicroFlow Shadow01 score.

Freeze:
    docs/MICROFLOW_SHADOW01_PROSPECTIVE_VALIDATION.md

This script intentionally does NOT compute Shadow01 probabilities or any
predictive statistic before frozen maturity. Until then it reports coverage
only.

No runtime promotion.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

import MICROSTRUCTURE_flow_mark_map as fm

FRESH_START = pd.Timestamp("2026-08-19")
MATURITY_DAYS = 20
MATURITY_EVENTS = 200_000
BOOT_N = 5000
BOOT_SEED = 2026081805

DEFAULT_INPUT = fm.OUT_DIR / "FLOWMARK_map04_prospective_passes.csv.gz"
DAILY_OUT = fm.OUT_DIR / "FLOWMARK_shadow01_prospective_daily_auc.csv"

REQUIRED = [
    "mark_id",
    "birth_day",
    "direction",
    "pass_no",
    "outcome_complete_before_retest_60s",
    "hit_200_before_retest",
    "signed_mid_impulse_1s_points",
    "opposing_mid_path_1s_points",
]

COEFS = {
    "PASS1": (-3.9428766403356286, 0.41954426272480366, 0.16817135923298430),
    "PASS2": (-4.3910705931584700, 0.28449971217439424, 0.26039027817580020),
    "PASS3+": (-4.8730026409947770, 0.47301521137832470, 0.37804446547486326),
}

CONF_CUTS = {
    "PASS1": (0.04202876, 0.06016286),
    "PASS2": (0.02636092, 0.03833246),
    "PASS3+": (0.02074484, 0.03190625),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Frozen MicroFlow Shadow01 prospective validator")
    p.add_argument("--input", default=str(DEFAULT_INPUT))
    return p.parse_args()


def pass_group(pass_no: pd.Series) -> pd.Series:
    return pd.Series(
        np.where(pass_no.eq(1), "PASS1", np.where(pass_no.eq(2), "PASS2", "PASS3+")),
        index=pass_no.index,
    )


def load_eligible(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=REQUIRED + ["pass_group"])

    z = pd.read_csv(path, low_memory=False)
    missing = [c for c in REQUIRED if c not in z.columns]
    if missing:
        raise RuntimeError(f"SHADOW01 ledger missing frozen columns: {missing}")

    z["birth_day"] = pd.to_datetime(z["birth_day"], errors="coerce").dt.normalize()
    if z["birth_day"].isna().any():
        raise RuntimeError("GUARD FAIL: invalid birth_day")
    if (z["birth_day"] < FRESH_START).any():
        raise RuntimeError("GUARD FAIL: pre-fresh row in Shadow01 prospective source")

    dup = z[["mark_id", "pass_no"]].duplicated(keep=False)
    if dup.any():
        raise RuntimeError(f"GUARD FAIL: duplicate (mark_id, pass_no) rows = {int(dup.sum())}")

    for c in (
        "direction",
        "pass_no",
        "outcome_complete_before_retest_60s",
        "hit_200_before_retest",
        "signed_mid_impulse_1s_points",
        "opposing_mid_path_1s_points",
    ):
        z[c] = pd.to_numeric(z[c], errors="coerce")

    z = z.loc[
        z["outcome_complete_before_retest_60s"].eq(1)
        & z["hit_200_before_retest"].isin([0, 1])
        & np.isfinite(z["signed_mid_impulse_1s_points"])
        & np.isfinite(z["opposing_mid_path_1s_points"])
    ].copy()
    z["pass_group"] = pass_group(z["pass_no"])
    return z


def frozen_probability(group: str, x: np.ndarray, c: np.ndarray) -> np.ndarray:
    intercept, bx, bc = COEFS[group]
    tx = np.arcsinh(np.asarray(x, dtype=float) / 20.0)
    tc = np.log1p(np.maximum(np.asarray(c, dtype=float), 0.0))
    eta = np.clip(intercept + bx * tx + bc * tc, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-eta))


def auc_rank(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    good = np.isfinite(x) & np.isfinite(y)
    x, y = x[good], y[good]
    pos = y == 1.0
    neg = y == 0.0
    n1, n0 = int(pos.sum()), int(neg.sum())
    if n1 == 0 or n0 == 0:
        return np.nan
    ranks = pd.Series(x).rank(method="average").to_numpy(float)
    u = float(ranks[pos].sum() - n1 * (n1 + 1) / 2.0)
    return u / (n1 * n0)


def daily_auc(z: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (day, group), g in z.groupby(["birth_day", "pass_group"], sort=True):
        y = g["hit_200_before_retest"].to_numpy(float)
        if np.unique(y).size != 2:
            continue
        p = g["shadow01_probability"].to_numpy(float)
        rows.append(
            {
                "birth_day": day,
                "pass_group": group,
                "n": int(len(g)),
                "n_pos": int(np.sum(y == 1.0)),
                "n_neg": int(np.sum(y == 0.0)),
                "auc": auc_rank(p, y),
            }
        )
    return pd.DataFrame(rows)


def bootstrap_mean(v: np.ndarray) -> tuple[float, float, float]:
    a = np.asarray(v, dtype=float)
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


def confidence_label(group: str, p: pd.Series) -> pd.Series:
    med, high = CONF_CUTS[group]
    return pd.Series(np.where(p >= high, "HIGH", np.where(p >= med, "MEDIUM", "LOW")), index=p.index)


def print_secondary(z: pd.DataFrame) -> None:
    print()
    print("SECONDARY DIAGNOSTICS — DESCRIPTIVE ONLY")
    for group in ("PASS1", "PASS2", "PASS3+"):
        g = z.loc[z["pass_group"].eq(group)].copy()
        if g.empty:
            print(f"{group:<6} no events")
            continue
        y = g["hit_200_before_retest"].to_numpy(float)
        p = g["shadow01_probability"].to_numpy(float)
        brier = float(np.mean((p - y) ** 2))
        pooled = auc_rank(p, y)
        print(
            f"{group:<6} pooled_AUC={pooled:.5f} brier={brier:.6f} "
            f"mean_pred={float(np.mean(p)):.5f} observed={float(np.mean(y)):.5f}"
        )

        g["confidence"] = confidence_label(group, g["shadow01_probability"])
        for label in ("LOW", "MEDIUM", "HIGH"):
            q = g.loc[g["confidence"].eq(label)]
            if q.empty:
                continue
            print(
                f"  {label:<6} n={len(q):>8} mean_pred={q['shadow01_probability'].mean():.5f} "
                f"observed={q['hit_200_before_retest'].mean():.5f}"
            )


def main() -> int:
    args = parse_args()
    path = Path(args.input)

    print("=" * 120)
    print("MICROFLOW SHADOW01 — SEALED PROSPECTIVE VALIDATION")
    print("=" * 120)
    print(f"fresh_start       = {FRESH_START.date()} 00:00 BRT")
    print(f"source            = {path}")
    print("target            = +200 before next retest / frozen 60s horizon")
    print("model             = frozen SHADOW01 probability")
    print("primary statistic = equal-BRT-day mean ROC AUC by PASS1/PASS2/PASS3+")
    print(f"bootstrap         = N={BOOT_N} seed={BOOT_SEED}")
    print(f"maturity          = {MATURITY_DAYS} days + {MATURITY_EVENTS} complete eligible PASS events")
    print("runtime promotion = NONE")

    z = load_eligible(path)
    days = int(z["birth_day"].nunique()) if not z.empty else 0
    events = int(len(z))

    print()
    print("PROSPECTIVE PROGRESS")
    print(f"days_progress   = {days}/{MATURITY_DAYS}")
    print(f"event_progress  = {events}/{MATURITY_EVENTS}")

    if days < MATURITY_DAYS or events < MATURITY_EVENTS:
        print("SHADOW01_PROSPECTIVE_STATUS = ACCUMULATING")
        print("PRIMARY_SCORES = SEALED")
        print("NO PROBABILITY / AUC / CI / BRIER / CALIBRATION WAS COMPUTED")
        return 0

    # IMPORTANT: probability computation begins only after frozen maturity.
    z = z.copy()
    z["shadow01_probability"] = np.nan
    for group in ("PASS1", "PASS2", "PASS3+"):
        ix = z["pass_group"].eq(group)
        z.loc[ix, "shadow01_probability"] = frozen_probability(
            group,
            z.loc[ix, "signed_mid_impulse_1s_points"].to_numpy(float),
            z.loc[ix, "opposing_mid_path_1s_points"].to_numpy(float),
        )

    dm = daily_auc(z)
    fm.OUT_DIR.mkdir(parents=True, exist_ok=True)
    dm.to_csv(DAILY_OUT, index=False)

    print()
    print("=" * 120)
    print("SHADOW01 PRIMARY — FRESH DAILY DISCRIMINATION")
    print("=" * 120)

    full = True
    for group in ("PASS1", "PASS2", "PASS3+"):
        g = dm.loc[dm["pass_group"].eq(group)] if not dm.empty else pd.DataFrame()
        if g.empty:
            est = lo = hi = np.nan
            passed = False
            ndays = 0
        else:
            est, lo, hi = bootstrap_mean(g["auc"].to_numpy(float))
            passed = bool(np.isfinite(lo) and est > 0.50 and lo > 0.50)
            ndays = len(g)
        full = full and passed
        print(
            f"{group:<6} eligible_days={ndays:>3} mean_daily_AUC={est:.5f} "
            f"CI95=[{lo:.5f},{hi:.5f}] support={'YES' if passed else 'NO'}"
        )

    print()
    print("SHADOW01_PROSPECTIVE_STATUS = MATURE")
    print("SHADOW01_PRIMARY_FULL_PASS = " + ("YES" if full else "NO"))
    print("NO THRESHOLD / CONFIDENCE-BUCKET / DIRECTION / PASS-STAGE RESCUE AUTHORIZED")

    print_secondary(z)

    print()
    print("FORMAL_RUNTIME_PROMOTION = NONE")
    print("MAP02_PROSPECTIVE = UNTOUCHED / ITS OWN MATURITY")
    print("MAP04_PROSPECTIVE = UNTOUCHED / ITS OWN MATURITY")
    print("MAP03_PRIMARY = FAILED / NOT SIGN-INVERTED")
    print(f"daily_auc = {DAILY_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
