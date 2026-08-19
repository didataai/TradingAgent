#!/usr/bin/env python3
"""MAP05 Counterflow Sequence — historical discovery only.

Frozen discovery protocol:
    docs/MICROSTRUCTURE_COUNTERFLOW_SEQUENCE_MAP05_DISCOVERY.md

This script reuses Map01R / Map03 lifecycle semantics and asks whether the
temporal location of opposing MID path inside the causal 1-second PASS window
adds historical discovery information after continuous control for signed MID
impulse and total opposing path.

NOT formal validation. No runtime promotion.
"""
from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import MICROSTRUCTURE_flow_mark_map as fm
import MICROSTRUCTURE_quote_path_efficiency_map03 as m3

DISCOVERY_START = date(2026, 7, 2)
DISCOVERY_END = date(2026, 8, 12)
BOOT_N = 5000
BOOT_SEED = 2026081901
RIDGE = 1e-8
IRLS_MAX_ITER = 60
IRLS_TOL = 1e-9

OUT_DIR = fm.OUT_DIR
LEDGER = OUT_DIR / "FLOWMARK_map05_discovery_passes.csv.gz"
COVERAGE = OUT_DIR / "FLOWMARK_map05_discovery_coverage.csv"
DAILY_MODELS = OUT_DIR / "FLOWMARK_map05_discovery_daily_models.csv"

KEEP = [
    "mark_id",
    "birth_day",
    "direction",
    "pass_no",
    "pass_time",
    "outcome_complete_before_retest_60s",
    "hit_200_before_retest",
    "signed_mid_impulse_1s_points",
    "opposing_mid_path_1s_points",
    "opposing_early_500ms_points",
    "opposing_late_500ms_points",
    "supporting_early_500ms_points",
    "supporting_late_500ms_points",
    "counterflow_sequence_contrast",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Map05 counterflow sequence historical discovery")
    p.add_argument("--mode", choices=("collect", "score", "run"), default="run")
    p.add_argument("--symbol", default=fm.SYMBOL_DEFAULT)
    p.add_argument("--start", default=DISCOVERY_START.isoformat())
    p.add_argument("--end", default=DISCOVERY_END.isoformat())
    p.add_argument("--retries", type=int, default=m3.RETRIES)
    p.add_argument("--reset", action="store_true")
    return p.parse_args()


def append_gzip(df: pd.DataFrame) -> None:
    if df.empty:
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exists = LEDGER.exists() and LEDGER.stat().st_size > 0
    df.to_csv(
        LEDGER,
        mode="a" if exists else "w",
        header=not exists,
        index=False,
        compression="gzip",
    )


def append_coverage(row: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exists = COVERAGE.exists() and COVERAGE.stat().st_size > 0
    pd.DataFrame([row]).to_csv(
        COVERAGE, mode="a" if exists else "w", header=not exists, index=False
    )


def collected_days() -> set[date]:
    if not COVERAGE.exists() or COVERAGE.stat().st_size == 0:
        return set()
    c = pd.read_csv(COVERAGE)
    c["day"] = pd.to_datetime(c["day"], errors="coerce").dt.date
    ok = c["status"].isin(["COMPLETE", "SATURDAY_NO_TICKS"])
    return set(c.loc[ok, "day"].dropna())


def map03_guard_counts() -> dict[date, tuple[int, int, int]]:
    path = m3.COVERAGE
    if not path.exists() or path.stat().st_size == 0:
        return {}
    c = pd.read_csv(path)
    needed = {"day", "valid_ticks", "episodes", "passes"}
    if not needed.issubset(c.columns):
        return {}
    c["day"] = pd.to_datetime(c["day"], errors="coerce").dt.date
    out: dict[date, tuple[int, int, int]] = {}
    for _, r in c.dropna(subset=["day"]).iterrows():
        try:
            out[r["day"]] = (int(r["valid_ticks"]), int(r["episodes"]), int(r["passes"]))
        except Exception:
            continue
    return out


def prefix(v: np.ndarray) -> np.ndarray:
    return np.r_[0.0, np.cumsum(np.asarray(v, dtype=float), dtype=float)]


def sequence_features(
    passes: list[dict],
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    point: float,
) -> pd.DataFrame:
    mid = (bid + ask) / 2.0
    dmid_points = np.diff(mid) / point
    pos = prefix(np.maximum(dmid_points, 0.0))
    neg = prefix(np.maximum(-dmid_points, 0.0))

    rows: list[dict] = []
    for p in passes:
        i = int(p["pass_idx"])
        t0 = int(ms[i])
        j = fm.ref_idx(ms, t0 - 1000)
        k = int(np.searchsorted(ms, t0 - 500, side="right") - 1)
        direction = int(p["direction"])

        if j < 0 or j >= i:
            vals = (np.nan,) * 6
        else:
            k = max(j, min(i, k))
            if direction > 0:
                sup_early = float(pos[k] - pos[j])
                opp_early = float(neg[k] - neg[j])
                sup_late = float(pos[i] - pos[k])
                opp_late = float(neg[i] - neg[k])
            else:
                sup_early = float(neg[k] - neg[j])
                opp_early = float(pos[k] - pos[j])
                sup_late = float(neg[i] - neg[k])
                opp_late = float(pos[i] - pos[k])

            opp_total = opp_early + opp_late
            contrast = (
                float((opp_early - opp_late) / opp_total)
                if opp_total > fm.EPS
                else np.nan
            )
            vals = (opp_total, opp_early, opp_late, sup_early, sup_late, contrast)

        rows.append(
            {
                "opposing_mid_path_1s_points": vals[0],
                "opposing_early_500ms_points": vals[1],
                "opposing_late_500ms_points": vals[2],
                "supporting_early_500ms_points": vals[3],
                "supporting_late_500ms_points": vals[4],
                "counterflow_sequence_contrast": vals[5],
            }
        )
    return pd.DataFrame(rows)


def collect_day(symbol: str, day: date, retries: int, guards: dict[date, tuple[int, int, int]]) -> None:
    ticks, point, last_err = m3.fetch_day(symbol, day, max(1, retries))
    if len(ticks) < 2:
        if day.weekday() == 5:
            append_coverage(
                {
                    "day": day,
                    "status": "SATURDAY_NO_TICKS",
                    "valid_ticks": 0,
                    "episodes": 0,
                    "passes": 0,
                    "eligible_sequence_passes": 0,
                }
            )
            print(f"{day} SATURDAY_NO_TICKS")
            return
        raise RuntimeError(f"persistent zero-tick non-Saturday {day}; last_error={last_err}")

    ms = ticks["time_msc"].astype(np.int64)
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)

    print(f"{day} BASELINE ticks={len(ticks)}", flush=True)
    baseline = fm.spread_baseline_by_tick(ms, ask - bid)
    marks = fm.episodes_for_day(ms, bid, ask, baseline, point, day)
    passes = m3.lean_lifecycle(marks, ms, bid, ask)

    if day in guards:
        expected = guards[day]
        actual = (int(len(ticks)), int(len(marks)), int(len(passes)))
        if actual != expected:
            raise RuntimeError(
                f"MAP05 REPRODUCTION GUARD FAIL {day}: expected ticks/episodes/passes={expected}, got={actual}"
            )
        print(f"{day} MAP03_REPRODUCTION_GUARD=PASS", flush=True)

    base = m3.add_path_and_outcome(passes, ms, bid, ask, point)
    seq = sequence_features(passes, ms, bid, ask, point)
    if len(base) != len(seq):
        raise RuntimeError(f"MAP05 alignment failure {day}: base={len(base)} seq={len(seq)}")

    if base.empty:
        compact = pd.DataFrame(columns=KEEP)
    else:
        compact = pd.DataFrame(
            {
                "mark_id": base["mark_id"],
                "birth_day": base["birth_day"],
                "direction": base["direction"],
                "pass_no": base["pass_no"],
                "pass_time": base["pass_time"],
                "outcome_complete_before_retest_60s": base["outcome_complete_before_retest_60s"],
                "hit_200_before_retest": base["hit_200_before_retest"],
                "signed_mid_impulse_1s_points": base["signed_mid_impulse_1s_points"],
                "opposing_mid_path_1s_points": seq["opposing_mid_path_1s_points"],
                "opposing_early_500ms_points": seq["opposing_early_500ms_points"],
                "opposing_late_500ms_points": seq["opposing_late_500ms_points"],
                "supporting_early_500ms_points": seq["supporting_early_500ms_points"],
                "supporting_late_500ms_points": seq["supporting_late_500ms_points"],
                "counterflow_sequence_contrast": seq["counterflow_sequence_contrast"],
            }
        )[KEEP]

    if not compact.empty:
        dup = compact[["mark_id", "pass_no"]].duplicated(keep=False)
        if dup.any():
            raise RuntimeError(f"MAP05 duplicate (mark_id,pass_no) rows on {day}: {int(dup.sum())}")
        append_gzip(compact)

    eligible = 0
    if not compact.empty:
        eligible = int(
            compact["outcome_complete_before_retest_60s"].eq(1)
            & compact["hit_200_before_retest"].isin([0, 1])
            & np.isfinite(compact["signed_mid_impulse_1s_points"])
            & np.isfinite(compact["opposing_mid_path_1s_points"])
            & compact["opposing_mid_path_1s_points"].gt(0)
            & np.isfinite(compact["counterflow_sequence_contrast"])
        ).sum()

    append_coverage(
        {
            "day": day,
            "status": "COMPLETE",
            "valid_ticks": int(len(ticks)),
            "episodes": int(len(marks)),
            "passes": int(len(compact)),
            "eligible_sequence_passes": eligible,
        }
    )
    print(
        f"{day} COMPLETE ticks={len(ticks)} episodes={len(marks)} passes={len(compact)} sequence_eligible={eligible}",
        flush=True,
    )


def frac_rank(v: np.ndarray) -> np.ndarray:
    s = pd.Series(np.asarray(v, dtype=float))
    return (s.rank(method="average").to_numpy(float) - 0.5) / float(len(s))


def fit_rank_logit3(x: np.ndarray, c: np.ndarray, s: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, bool]:
    x = np.asarray(x, dtype=float)
    c = np.asarray(c, dtype=float)
    s = np.asarray(s, dtype=float)
    y = np.asarray(y, dtype=float)
    good = np.isfinite(x) & np.isfinite(c) & np.isfinite(s) & np.isfinite(y)
    x, c, s, y = x[good], c[good], s[good], y[good]
    if len(y) < 4 or np.unique(y).size != 2:
        return np.full(4, np.nan), False
    if np.unique(x).size < 2 or np.unique(c).size < 2 or np.unique(s).size < 2:
        return np.full(4, np.nan), False

    a = np.column_stack(
        [
            np.ones(len(y)),
            frac_rank(x) - 0.5,
            frac_rank(c) - 0.5,
            frac_rank(s) - 0.5,
        ]
    )
    py = float(np.clip(y.mean(), 1e-9, 1.0 - 1e-9))
    beta = np.array([math.log(py / (1.0 - py)), 0.0, 0.0, 0.0], dtype=float)
    ridge = np.diag([0.0, RIDGE, RIDGE, RIDGE])

    converged = False
    for _ in range(IRLS_MAX_ITER):
        eta = np.clip(a @ beta, -30.0, 30.0)
        prob = 1.0 / (1.0 + np.exp(-eta))
        w = np.maximum(prob * (1.0 - prob), 1e-9)
        h = a.T @ (w[:, None] * a) + ridge
        grad = a.T @ (y - prob)
        try:
            delta = np.linalg.solve(h, grad)
        except np.linalg.LinAlgError:
            return np.full(4, np.nan), False
        beta += delta
        if float(np.max(np.abs(delta))) < IRLS_TOL:
            converged = True
            break
    return beta, converged


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
    return u / float(n1 * n0)


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


def load_eligible() -> pd.DataFrame:
    if not LEDGER.exists() or LEDGER.stat().st_size == 0:
        return pd.DataFrame(columns=KEEP + ["pass_group"])
    z = pd.read_csv(LEDGER, low_memory=False)
    missing = [c for c in KEEP if c not in z.columns]
    if missing:
        raise RuntimeError(f"MAP05 ledger missing columns: {missing}")
    z["birth_day"] = pd.to_datetime(z["birth_day"], errors="coerce").dt.normalize()
    if z["birth_day"].isna().any():
        raise RuntimeError("MAP05 invalid birth_day")
    dup = z[["mark_id", "pass_no"]].duplicated(keep=False)
    if dup.any():
        raise RuntimeError(f"MAP05 duplicate ledger identities: {int(dup.sum())}")

    numeric = [
        "pass_no",
        "outcome_complete_before_retest_60s",
        "hit_200_before_retest",
        "signed_mid_impulse_1s_points",
        "opposing_mid_path_1s_points",
        "counterflow_sequence_contrast",
    ]
    for c in numeric:
        z[c] = pd.to_numeric(z[c], errors="coerce")

    z = z.loc[
        z["outcome_complete_before_retest_60s"].eq(1)
        & z["hit_200_before_retest"].isin([0, 1])
        & np.isfinite(z["signed_mid_impulse_1s_points"])
        & np.isfinite(z["opposing_mid_path_1s_points"])
        & z["opposing_mid_path_1s_points"].gt(0)
        & np.isfinite(z["counterflow_sequence_contrast"])
    ].copy()
    z["pass_group"] = np.where(
        z["pass_no"].eq(1), "PASS1", np.where(z["pass_no"].eq(2), "PASS2", "PASS3+")
    )
    return z


def score() -> int:
    z = load_eligible()
    print("=" * 120)
    print("MAP05 COUNTERFLOW SEQUENCE — HISTORICAL DISCOVERY SCORE")
    print("=" * 120)
    print("status            = HISTORICAL DISCOVERY ONLY")
    print("model             = daily rank-logit NET + OPP_TOTAL + SEQUENCE_CONTRAST")
    print("primary discovery = beta_SEQUENCE > 0")
    print(f"bootstrap         = N={BOOT_N} seed={BOOT_SEED}")
    print("runtime promotion = NONE")
    print(f"eligible_events   = {len(z)}")
    print(f"eligible_days     = {z['birth_day'].nunique() if not z.empty else 0}")

    rows: list[dict] = []
    for (day, group), g in z.groupby(["birth_day", "pass_group"], sort=True):
        y = g["hit_200_before_retest"].to_numpy(float)
        beta, converged = fit_rank_logit3(
            g["signed_mid_impulse_1s_points"].to_numpy(float),
            g["opposing_mid_path_1s_points"].to_numpy(float),
            g["counterflow_sequence_contrast"].to_numpy(float),
            y,
        )
        if not converged:
            continue
        rows.append(
            {
                "birth_day": day,
                "pass_group": group,
                "n": int(len(g)),
                "n_pos": int(np.sum(y == 1.0)),
                "n_neg": int(np.sum(y == 0.0)),
                "beta_mid": float(beta[1]),
                "beta_counterflow": float(beta[2]),
                "beta_sequence": float(beta[3]),
                "raw_sequence_auc": auc_rank(g["counterflow_sequence_contrast"].to_numpy(float), y),
            }
        )

    dm = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dm.to_csv(DAILY_MODELS, index=False)

    print()
    print("PRIMARY DISCOVERY — TEMPORAL LOCATION OF COUNTERFLOW")
    support_all = True
    for group in ("PASS1", "PASS2", "PASS3+"):
        g = dm.loc[dm["pass_group"].eq(group)] if not dm.empty else pd.DataFrame()
        q = z.loc[z["pass_group"].eq(group)]
        if g.empty:
            est = lo = hi = raw_auc = np.nan
            pos_days = 0
            support = False
        else:
            est, lo, hi = bootstrap_mean(g["beta_sequence"].to_numpy(float))
            pos_days = int(g["beta_sequence"].gt(0).sum())
            raw_auc = auc_rank(q["counterflow_sequence_contrast"].to_numpy(float), q["hit_200_before_retest"].to_numpy(float))
            support = bool(np.isfinite(lo) and est > 0.0 and lo > 0.0)
        support_all = support_all and support
        print(
            f"{group:<6} days={len(g):>3} events={len(q):>9} "
            f"mean_beta_SEQUENCE={est:+.6f} CI95=[{lo:+.6f},{hi:+.6f}] "
            f"positive_days={pos_days}/{len(g)} raw_sequence_AUC={raw_auc:.5f} "
            f"support={'YES' if support else 'NO'}"
        )

    print()
    print("MAP05_HISTORICAL_DISCOVERY_SUPPORT = " + ("YES" if support_all else "NO"))
    print("FORMAL_VALIDATION = NO")
    print("NO THRESHOLD / SIGN INVERSION / DIRECTION / PASS-STAGE RESCUE AUTHORIZED")
    print("MAP02_PROSPECTIVE = UNTOUCHED")
    print("MAP04_PROSPECTIVE = UNTOUCHED")
    print("SHADOW01_PROSPECTIVE = UNTOUCHED")
    print("MAP03_PRIMARY = FAILED / NOT SIGN-INVERTED")
    print("RUNTIME_PROMOTION = NONE")
    print(f"daily_models = {DAILY_MODELS}")
    return 0


def collect(symbol: str, start: date, end: date, retries: int) -> int:
    if end < start:
        raise SystemExit("end before start")
    guards = map03_guard_counts()
    done = collected_days()
    days = [d.date() for d in pd.date_range(start, end, freq="D")]
    print("=" * 120)
    print("MAP05 COUNTERFLOW SEQUENCE — HISTORICAL DISCOVERY COLLECTOR")
    print("=" * 120)
    print(f"symbol            = {symbol}")
    print(f"block             = {start} .. {end}")
    print("status            = HISTORICAL DISCOVERY ONLY")
    print("runtime promotion = NONE")
    for d in days:
        if d in done:
            print(f"{d} ALREADY_PRESENT / SKIP")
            continue
        collect_day(symbol, d, retries, guards)
    return 0


def main() -> int:
    args = parse_args()
    start = pd.Timestamp(args.start).date()
    end = pd.Timestamp(args.end).date()

    if args.reset:
        for p in (LEDGER, COVERAGE, DAILY_MODELS):
            if p.exists():
                p.unlink()
        print("MAP05 outputs reset")

    if args.mode in ("collect", "run"):
        collect(str(args.symbol).strip(), start, end, max(1, int(args.retries)))
    if args.mode in ("score", "run"):
        return score()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
