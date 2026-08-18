#!/usr/bin/env python3
"""MICROSTRUCTURE QUOTE PATH EFFICIENCY MAP 03.

Frozen contract:
    docs/MICROSTRUCTURE_QUOTE_PATH_EFFICIENCY_MAP03.md

Purpose:
- reproduce Map01R PASS identities with a lean lifecycle;
- keep Map03 historical holdout scores sealed until all frozen holdout days finish;
- test incremental directional path efficiency after continuous MID-impulse control.

No runtime promotion.
"""
from __future__ import annotations

import argparse
import json
import math
import time as walltime
from datetime import date, time, timedelta

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

import MICROSTRUCTURE_flow_mark_map as fm

SMOKE_DAY = date(2026, 8, 11)
SMOKE_EXPECTED = {
    "episodes": 4066,
    "passes": 38287,
    "PASS1": 3853,
    "PASS2": 3365,
    "PASS3+": 31069,
}

HOLDOUT_START = date(2026, 7, 2)
HOLDOUT_END = date(2026, 8, 10)
HOLDOUT_EXTRA = date(2026, 8, 12)

TARGET_POINTS = 200
BOOT_N = 5000
BOOT_SEED = 2026081803
RIDGE = 1e-8
IRLS_MAX_ITER = 60
IRLS_TOL = 1e-9
RETRIES = 3
RETRY_SLEEP_S = 0.75

OUT_DIR = fm.OUT_DIR
SMOKE_GUARD = OUT_DIR / "FLOWMARK_map03_smoke_guard.json"
LEDGER = OUT_DIR / "FLOWMARK_map03_holdout_passes.csv.gz"
COVERAGE = OUT_DIR / "FLOWMARK_map03_holdout_coverage.csv"
DAILY_MODELS = OUT_DIR / "FLOWMARK_map03_holdout_daily_models.csv"

KEEP = [
    "mark_id",
    "birth_day",
    "direction",
    "pass_no",
    "pass_idx",
    "next_retest_idx",
    "pass_time",
    "outcome_complete_before_retest_60s",
    "hit_200_before_retest",
    "signed_mid_impulse_1s_points",
    "total_mid_path_1s_points",
    "directional_path_efficiency_1s",
    "directional_mid_update_fraction_1s",
    "both_quote_change_fraction_1s",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Frozen Quote Path Efficiency Map03")
    p.add_argument("--mode", choices=("smoke", "holdout"), required=True)
    p.add_argument("--symbol", default=fm.SYMBOL_DEFAULT)
    p.add_argument("--retries", type=int, default=RETRIES)
    p.add_argument(
        "--reset",
        action="store_true",
        help="Delete only Map03 holdout outputs before a new holdout run. Smoke guard is preserved.",
    )
    return p.parse_args()


def init_symbol(symbol: str) -> float:
    mt5.shutdown()
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"symbol_info({symbol}) returned None")
    if not info.visible and not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")
    point = float(info.point)
    if not math.isclose(point, fm.EXPECTED_POINT, rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError(
            f"MAP03 point guard failed: expected {fm.EXPECTED_POINT}, got {point}"
        )
    return point


def fetch_day(symbol: str, d: date, retries: int) -> tuple[np.ndarray, float, tuple]:
    q_start = fm.brt_local(d, time(0, 0))
    q_end = fm.brt_local(d + timedelta(days=1), time(0, 0)) - timedelta(milliseconds=1)
    last_err: tuple = (0, "not-called")
    ticks = fm.valid_ticks(None)
    point = fm.EXPECTED_POINT

    for attempt in range(1, retries + 1):
        point = init_symbol(symbol)
        raw = mt5.copy_ticks_range(
            symbol, fm.to_utc(q_start), fm.to_utc(q_end), mt5.COPY_TICKS_ALL
        )
        last_err = mt5.last_error()
        ticks = fm.valid_ticks(raw)
        print(
            f"    FETCH attempt={attempt}/{retries} ticks={len(ticks):>8} last_error={last_err}",
            flush=True,
        )
        if len(ticks) >= 2:
            return ticks, point, last_err
        mt5.shutdown()
        if attempt < retries:
            walltime.sleep(RETRY_SLEEP_S)

    return ticks, point, last_err


def holdout_days() -> list[date]:
    days = [x.date() for x in pd.date_range(HOLDOUT_START, HOLDOUT_END, freq="D")]
    days.append(HOLDOUT_EXTRA)
    return days


def lean_lifecycle(
    marks: list[dict],
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
) -> list[dict]:
    """Exact Map01R crossing state machine without per-PASS event_signature overhead."""
    bid_find = fm.RangeFinder(bid)
    ask_find = fm.RangeFinder(ask)
    rows: list[dict] = []

    for mark in marks:
        direction = int(mark["direction"])
        activation = int(mark["activation_idx"])
        if direction == 0 or activation < 0:
            continue

        low = float(mark["mark_bid"])
        high = float(mark["mark_ask"])
        current = (
            bid_find.first_gt(activation, high)
            if direction > 0
            else ask_find.first_lt(activation, low)
        )
        if current < 0:
            continue

        pass_no = 1
        while True:
            ret = (
                bid_find.first_le(current + 1, high)
                if direction > 0
                else ask_find.first_ge(current + 1, low)
            )

            rows.append(
                {
                    "mark_id": mark["mark_id"],
                    "birth_day": mark["birth_day"],
                    "direction": direction,
                    "pass_no": int(pass_no),
                    "pass_idx": int(current),
                    "next_retest_idx": int(ret),
                    "pass_time": fm.ms_to_brt(int(ms[current])),
                }
            )

            if ret < 0:
                break

            if direction > 0 and ask[ret] < low:
                break
            if direction < 0 and bid[ret] > high:
                break

            if direction > 0:
                recross = bid_find.first_gt(ret + 1, high)
                failure = ask_find.first_lt(ret + 1, low)
            else:
                recross = ask_find.first_lt(ret + 1, low)
                failure = bid_find.first_gt(ret + 1, high)

            if failure >= 0 and (recross < 0 or failure < recross):
                break
            if recross < 0:
                break

            current = int(recross)
            pass_no += 1

    return rows


def prefix_sums_for_path(
    bid: np.ndarray, ask: np.ndarray, point: float
) -> dict[str, np.ndarray]:
    mid = (bid + ask) / 2.0
    dmid = np.diff(mid)
    dbid = np.diff(bid)
    dask = np.diff(ask)

    def prefix(v: np.ndarray) -> np.ndarray:
        return np.r_[0.0, np.cumsum(v, dtype=float)]

    return {
        "mid": mid,
        "abs_mid_points": prefix(np.abs(dmid) / point),
        "mid_pos": prefix((dmid > fm.EPS).astype(float)),
        "mid_neg": prefix((dmid < -fm.EPS).astype(float)),
        "mid_changed": prefix((np.abs(dmid) > fm.EPS).astype(float)),
        "both_quote_changed": prefix(
            ((np.abs(dbid) > fm.EPS) & (np.abs(dask) > fm.EPS)).astype(float)
        ),
    }


def add_path_and_outcome(
    passes: list[dict],
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    point: float,
) -> pd.DataFrame:
    if not passes:
        return pd.DataFrame(columns=KEEP)

    pref = prefix_sums_for_path(bid, ask, point)
    mid = pref["mid"]
    mid_find = fm.RangeFinder(mid)

    out: list[dict] = []
    for p in passes:
        i = int(p["pass_idx"])
        ret = int(p["next_retest_idx"])
        direction = int(p["direction"])
        t0 = int(ms[i])

        h_end = int(np.searchsorted(ms, t0 + 60_000, side="right"))
        if ret >= 0:
            end = min(h_end, ret)
            complete = True
        else:
            end = h_end
            complete = bool(int(ms[-1]) >= t0 + 60_000)

        if complete:
            if direction > 0:
                hit_idx = mid_find.first_ge(i, float(mid[i] + TARGET_POINTS * point))
            else:
                hit_idx = mid_find.first_le(i, float(mid[i] - TARGET_POINTS * point))
            hit200 = int(hit_idx >= 0 and hit_idx < end)
        else:
            hit200 = np.nan

        j = fm.ref_idx(ms, t0 - 1000)
        if j >= 0 and i > j:
            x = float(direction * (mid[i] - mid[j]) / point)
            total_path = float(pref["abs_mid_points"][i] - pref["abs_mid_points"][j])
            efficiency = float(x / total_path) if total_path > 0 else np.nan
        else:
            x = np.nan
            total_path = np.nan
            efficiency = np.nan

        one_lo = int(np.searchsorted(ms, t0 - 1000, side="left"))
        if i - one_lo >= 1:
            changed = float(pref["mid_changed"][i] - pref["mid_changed"][one_lo])
            favorable = float(
                (pref["mid_pos"][i] - pref["mid_pos"][one_lo])
                if direction > 0
                else (pref["mid_neg"][i] - pref["mid_neg"][one_lo])
            )
            directional_fraction = favorable / changed if changed > 0 else np.nan
            transitions = float(i - one_lo)
            both_fraction = float(
                (pref["both_quote_changed"][i] - pref["both_quote_changed"][one_lo])
                / transitions
            )
        else:
            directional_fraction = np.nan
            both_fraction = np.nan

        q = dict(p)
        q.update(
            {
                "outcome_complete_before_retest_60s": int(complete),
                "hit_200_before_retest": hit200,
                "signed_mid_impulse_1s_points": x,
                "total_mid_path_1s_points": total_path,
                "directional_path_efficiency_1s": efficiency,
                "directional_mid_update_fraction_1s": directional_fraction,
                "both_quote_change_fraction_1s": both_fraction,
            }
        )
        out.append(q)

    return pd.DataFrame(out)[KEEP]


def frac_rank(v: np.ndarray) -> np.ndarray:
    s = pd.Series(np.asarray(v, dtype=float))
    n = len(s)
    return (s.rank(method="average").to_numpy(float) - 0.5) / float(n)


def fit_rank_logit(x: np.ndarray, e: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, bool]:
    x = np.asarray(x, dtype=float)
    e = np.asarray(e, dtype=float)
    y = np.asarray(y, dtype=float)
    good = np.isfinite(x) & np.isfinite(e) & np.isfinite(y)
    x, e, y = x[good], e[good], y[good]

    if len(y) < 3 or np.unique(y).size != 2:
        return np.full(3, np.nan), False
    if np.unique(x).size < 2 or np.unique(e).size < 2:
        return np.full(3, np.nan), False

    rx = frac_rank(x) - 0.5
    re = frac_rank(e) - 0.5
    a = np.column_stack([np.ones(len(y)), rx, re])

    py = float(np.clip(y.mean(), 1e-9, 1.0 - 1e-9))
    beta = np.array([math.log(py / (1.0 - py)), 0.0, 0.0], dtype=float)
    ridge = np.diag([0.0, RIDGE, RIDGE])

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
            return np.full(3, np.nan), False
        beta = beta + delta
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
    return u / (n1 * n0)


def daily_models(z: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (day, group), g in z.groupby(["birth_day", "pass_group"], sort=True):
        q = g.loc[
            g["outcome_complete_before_retest_60s"].eq(1)
            & g["hit_200_before_retest"].isin([0, 1])
            & np.isfinite(g["signed_mid_impulse_1s_points"])
            & np.isfinite(g["directional_path_efficiency_1s"])
        ].copy()
        if q.empty:
            continue

        y = q["hit_200_before_retest"].to_numpy(float)
        beta, converged = fit_rank_logit(
            q["signed_mid_impulse_1s_points"].to_numpy(float),
            q["directional_path_efficiency_1s"].to_numpy(float),
            y,
        )
        if not converged:
            continue

        rows.append(
            {
                "birth_day": day,
                "pass_group": group,
                "n": int(len(q)),
                "n_pos": int(np.sum(y == 1.0)),
                "n_neg": int(np.sum(y == 0.0)),
                "beta_x": float(beta[1]),
                "beta_path": float(beta[2]),
                "path_auc_descriptive": auc_rank(
                    q["directional_path_efficiency_1s"].to_numpy(float), y
                ),
            }
        )
    return pd.DataFrame(rows)


def bootstrap_mean(v: np.ndarray) -> tuple[float, float, float]:
    a = np.asarray(v, dtype=float)
    a = a[np.isfinite(a)]
    if not len(a):
        return np.nan, np.nan, np.nan
    est = float(a.mean())
    if len(a) < 2:
        return est, np.nan, np.nan
    rng = np.random.default_rng(BOOT_SEED)
    picks = rng.integers(0, len(a), size=(BOOT_N, len(a)))
    boot = a[picks].mean(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return est, float(lo), float(hi)


def append_gzip(df: pd.DataFrame, path) -> None:
    if df.empty:
        return
    exists = path.exists() and path.stat().st_size > 0
    df.to_csv(
        path,
        mode="a" if exists else "w",
        header=not exists,
        index=False,
        compression="gzip",
    )


def append_coverage(row: dict) -> None:
    exists = COVERAGE.exists() and COVERAGE.stat().st_size > 0
    pd.DataFrame([row]).to_csv(
        COVERAGE, mode="a" if exists else "w", header=not exists, index=False
    )


def completed_days() -> set[date]:
    if not COVERAGE.exists() or COVERAGE.stat().st_size == 0:
        return set()
    c = pd.read_csv(COVERAGE)
    c["day"] = pd.to_datetime(c["day"], errors="coerce").dt.date
    ok = c["status"].isin(["COMPLETE", "SATURDAY_NO_TICKS"])
    return set(c.loc[ok, "day"].dropna())


def smoke_guard_ok() -> bool:
    if not SMOKE_GUARD.exists():
        return False
    try:
        data = json.loads(SMOKE_GUARD.read_text(encoding="utf-8"))
    except Exception:
        return False
    return all(data.get(k) == v for k, v in SMOKE_EXPECTED.items())


def run_smoke(symbol: str, retries: int) -> int:
    print("=" * 120)
    print("MAP03 MECHANICAL REPRODUCTION SMOKE — NO MAP03 OUTCOME SCORING")
    print("=" * 120)
    print(f"day             = {SMOKE_DAY} BRT")
    print("expected        = Map01R frozen smoke counts")
    print("Map03 scoring   = DISABLED")
    print("runtime         = NONE")

    ticks, point, _ = fetch_day(symbol, SMOKE_DAY, retries)
    if len(ticks) < 2:
        raise RuntimeError("SMOKE GUARD FAIL: no ticks")

    ms = ticks["time_msc"].astype(np.int64)
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)
    baseline = fm.spread_baseline_by_tick(ms, ask - bid)
    marks = fm.episodes_for_day(ms, bid, ask, baseline, point, SMOKE_DAY)
    passes = lean_lifecycle(marks, ms, bid, ask)

    counts = {
        "episodes": int(len(marks)),
        "passes": int(len(passes)),
        "PASS1": int(sum(int(p["pass_no"]) == 1 for p in passes)),
        "PASS2": int(sum(int(p["pass_no"]) == 2 for p in passes)),
        "PASS3+": int(sum(int(p["pass_no"]) >= 3 for p in passes)),
    }

    print()
    for k in ("episodes", "passes", "PASS1", "PASS2", "PASS3+"):
        print(f"{k:<10} observed={counts[k]:>8} expected={SMOKE_EXPECTED[k]:>8}")

    if counts != SMOKE_EXPECTED:
        print("MAP03_REPRODUCTION_GUARD = FAIL")
        raise RuntimeError(f"smoke mismatch: {counts}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "day": SMOKE_DAY.isoformat(),
        **counts,
        "status": "PASS",
        "map03_scoring": "DISABLED",
    }
    SMOKE_GUARD.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print()
    print("MAP03_REPRODUCTION_GUARD = PASS")
    print(f"guard_file = {SMOKE_GUARD}")
    print("NO MAP03 OUTCOME SCORE WAS COMPUTED")
    print("RUNTIME_PROMOTION = NONE")
    mt5.shutdown()
    return 0


def score_complete_holdout() -> int:
    if not LEDGER.exists() or LEDGER.stat().st_size == 0:
        raise RuntimeError("holdout ledger missing at scoring stage")

    z = pd.read_csv(LEDGER, low_memory=False)
    z["birth_day"] = pd.to_datetime(z["birth_day"], errors="coerce").dt.normalize()
    for c in (
        "direction",
        "pass_no",
        "outcome_complete_before_retest_60s",
        "hit_200_before_retest",
        "signed_mid_impulse_1s_points",
        "total_mid_path_1s_points",
        "directional_path_efficiency_1s",
    ):
        z[c] = pd.to_numeric(z[c], errors="coerce")

    if z["birth_day"].isna().any():
        raise RuntimeError("GUARD FAIL: invalid birth_day in Map03 ledger")
    dup = z[["mark_id", "pass_no"]].duplicated(keep=False)
    if dup.any():
        raise RuntimeError(
            f"GUARD FAIL: duplicate (mark_id, pass_no) rows = {int(dup.sum())}"
        )

    allowed = set(holdout_days())
    got = set(z["birth_day"].dt.date.unique())
    bad = sorted(got - allowed)
    if bad:
        raise RuntimeError(f"GUARD FAIL: ledger contains non-holdout days: {bad}")

    z["pass_group"] = np.where(
        z["pass_no"].eq(1),
        "PASS1",
        np.where(z["pass_no"].eq(2), "PASS2", "PASS3+"),
    )

    dm = daily_models(z)
    dm.to_csv(DAILY_MODELS, index=False)

    print()
    print("=" * 120)
    print("MAP03 PRIMARY — INCREMENTAL PATH EFFICIENCY AFTER MID-IMPULSE CONTROL")
    print("=" * 120)

    support = True
    for group in ("PASS1", "PASS2", "PASS3+"):
        g = dm.loc[dm["pass_group"].eq(group)]
        est, lo, hi = bootstrap_mean(g["beta_path"].to_numpy(float))
        q = z.loc[
            z["pass_group"].eq(group)
            & z["outcome_complete_before_retest_60s"].eq(1)
            & z["hit_200_before_retest"].isin([0, 1])
            & np.isfinite(z["signed_mid_impulse_1s_points"])
            & np.isfinite(z["directional_path_efficiency_1s"])
        ]
        pooled_auc = auc_rank(
            q["directional_path_efficiency_1s"].to_numpy(float),
            q["hit_200_before_retest"].to_numpy(float),
        )
        passed = bool(np.isfinite(lo) and est > 0.0 and lo > 0.0)
        support = support and passed
        print(
            f"{group:<6} days={len(g):>3} events={len(q):>9} "
            f"mean_beta_PATH={est:+.6f} CI95=[{lo:+.6f},{hi:+.6f}] "
            f"raw_path_AUC={pooled_auc:.5f} support={'YES' if passed else 'NO'}"
        )

    print()
    print("MAP03_HISTORICAL_HOLDOUT_SUPPORT = " + ("YES" if support else "NO"))
    print("FORMAL_VALIDATION = NO")
    print("Historical holdout only; prospective Map03 remains separate.")
    print("MAP02_PROSPECTIVE = UNTOUCHED / SCORES SEALED")
    print("EXP27 = UNTOUCHED / SCORES SEALED")
    print("CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED")
    print("RUNTIME_PROMOTION = NONE")
    print(f"ledger       = {LEDGER}")
    print(f"daily_models = {DAILY_MODELS}")
    return 0


def run_holdout(symbol: str, retries: int, reset: bool) -> int:
    if not smoke_guard_ok():
        raise SystemExit(
            "MAP03_REPRODUCTION_GUARD missing/not valid. "
            "Run first: python .\\MICROSTRUCTURE_quote_path_efficiency_map03.py --mode smoke"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if reset:
        for p in (LEDGER, COVERAGE, DAILY_MODELS):
            if p.exists():
                p.unlink()
        print("MAP03_RESET = holdout outputs deleted; smoke guard preserved")

    days = holdout_days()
    done = completed_days()

    print("=" * 120)
    print("MICROSTRUCTURE QUOTE PATH EFFICIENCY MAP03 — SEALED HISTORICAL HOLDOUT")
    print("=" * 120)
    print(f"symbol            = {symbol}")
    print(f"holdout           = {HOLDOUT_START}..{HOLDOUT_END} + {HOLDOUT_EXTRA}")
    print(f"excluded          = {SMOKE_DAY} [already observed smoke]")
    print("primary control   = signed MID impulse 1s")
    print("primary path      = directional path efficiency 1s")
    print("primary model     = daily rank-logit X + path")
    print("scores during run = SEALED UNTIL ALL HOLDOUT DAYS COMPLETE")
    print("runtime promotion = NONE")
    if done:
        print(f"resume            = {len(done)}/{len(days)} calendar holdout days already covered")

    try:
        for day_no, d in enumerate(days, start=1):
            if d in done:
                print(f"DAY {day_no:>2}/{len(days)} {d} | SKIP already complete", flush=True)
                continue

            print(f"DAY {day_no:>2}/{len(days)} {d} | FETCH ticks", flush=True)
            ticks, point, last_err = fetch_day(symbol, d, retries)

            if len(ticks) < 2:
                if d.weekday() == 5:
                    append_coverage(
                        {
                            "day": d,
                            "status": "SATURDAY_NO_TICKS",
                            "valid_ticks": 0,
                            "episodes": 0,
                            "passes": 0,
                            "complete_passes": 0,
                        }
                    )
                    print(
                        f"DAY {day_no:>2}/{len(days)} {d} | DONE Saturday no ticks | SCORES SEALED",
                        flush=True,
                    )
                    continue
                raise RuntimeError(
                    f"persistent zero-tick non-Saturday {d}; last_error={last_err}"
                )

            ms = ticks["time_msc"].astype(np.int64)
            bid = ticks["bid"].astype(float)
            ask = ticks["ask"].astype(float)

            print(
                f"DAY {day_no:>2}/{len(days)} {d} | BASELINE ticks={len(ticks)}",
                flush=True,
            )
            baseline = fm.spread_baseline_by_tick(ms, ask - bid)

            print(f"DAY {day_no:>2}/{len(days)} {d} | EPISODES", flush=True)
            marks = fm.episodes_for_day(ms, bid, ask, baseline, point, d)

            print(
                f"DAY {day_no:>2}/{len(days)} {d} | LEAN LIFECYCLE episodes={len(marks)}",
                flush=True,
            )
            passes = lean_lifecycle(marks, ms, bid, ask)

            print(
                f"DAY {day_no:>2}/{len(days)} {d} | PATH + OUTCOME passes={len(passes)}",
                flush=True,
            )
            pdf = add_path_and_outcome(passes, ms, bid, ask, point)

            if not pdf.empty:
                ident = pdf[["mark_id", "pass_no"]]
                if ident.duplicated().any():
                    raise RuntimeError(f"GUARD FAIL: duplicate (mark_id,pass_no) within {d}")
                append_gzip(pdf, LEDGER)

            complete = (
                int(pdf["outcome_complete_before_retest_60s"].eq(1).sum())
                if not pdf.empty
                else 0
            )
            append_coverage(
                {
                    "day": d,
                    "status": "COMPLETE",
                    "valid_ticks": int(len(ticks)),
                    "episodes": int(len(marks)),
                    "passes": int(len(pdf)),
                    "complete_passes": complete,
                }
            )
            print(
                f"DAY {day_no:>2}/{len(days)} {d} | DONE "
                f"episodes={len(marks)} passes={len(pdf)} complete={complete} | SCORES SEALED",
                flush=True,
            )
    finally:
        mt5.shutdown()

    done = completed_days()
    missing = [d for d in days if d not in done]
    if missing:
        print()
        print("MAP03_HOLDOUT_STATUS = INCOMPLETE")
        print(f"covered = {len(done)}/{len(days)}")
        print(f"missing = {missing}")
        print("PRIMARY_SCORES = SEALED")
        return 0

    print()
    print("MAP03_HOLDOUT_COVERAGE = COMPLETE")
    print("PRIMARY_SCORES = UNSEALED ONCE, USING FROZEN MODEL")
    return score_complete_holdout()


def main() -> int:
    args = parse_args()
    symbol = str(args.symbol).strip()
    retries = max(1, int(args.retries))

    if args.mode == "smoke":
        return run_smoke(symbol, retries)
    return run_holdout(symbol, retries, bool(args.reset))


if __name__ == "__main__":
    raise SystemExit(main())
