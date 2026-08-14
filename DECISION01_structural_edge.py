#!/usr/bin/env python3
"""Decision Layer 01 — frozen structural edge / geometry break-even.

Historical OOS exploratory only. No runtime promotion. Exp27 untouched.

This runner adds no market feature and fits no decision threshold. It:
1) reproduces the exact frozen Track-D structural universe;
2) deterministically refits the frozen Exp41 TRAIN BASE_SURV and POSITION_SURV
   parameterization and ABORTS before score unless documented Exp41 guards match;
3) reuses the exact Exp47 factorization:
       e(H) = P(EXIT by H) from BASE_SURV
       q(H) = P(ADVANCE | EXIT by H, Position) from POSITION_SURV
4) tests the preregistered gross structural expectancy identity:
       EDGE_PROB = q - CorridorPosition
       STRUCTURAL_EDGE_ATR = e * CorridorWidthATR * EDGE_PROB
5) tests zero-threshold policy payoff with whole-BRT-day bootstrap.

Explicitly excluded: Exp27 fresh-forward rows, Operability historical filtering,
spread/slippage/commission, edge threshold search, horizon/environment deletion,
recalibration, new features and OOS refit.
"""
from __future__ import annotations

import ast
import contextlib
import io
from pathlib import Path

import numpy as np
import pandas as pd

import EXP27_readiness_counter as e27

ROOT = Path(__file__).resolve().parent
HORIZONS = (15, 30, 60, 120)
MAX_STEP = 24
STRUCTURAL_DATA_END_LINE = 766
N_BOOT = 10_000
BOOT_SEED = 2026081401

EXPECTED_DYN = 9667
EXPECTED_SPLITS = {"TRAIN": 5612, "VALIDATION": 1959, "TEST": 2096}
EXPECTED_CELLS = {"TRAIN": 21681, "VALIDATION": 7577, "TEST": 8008}
EXPECTED_CELLS_H = {
    "TRAIN": {15: 5565, 30: 5501, 60: 5395, 120: 5220},
    "VALIDATION": {15: 1942, 30: 1919, 60: 1885, 120: 1831},
    "TEST": {15: 2076, 30: 2046, 60: 1988, 120: 1898},
}
EXPECTED_TRAIN_HAZARD = 67550
EXPECTED_TRAIN_HAZARD_CLASSES = {"STAY": 63795, "ADVANCE": 1559, "RECAPTURE": 2196}
EXPECTED_POSITION_GEO = {"ADVANCE": 0.48459159, "RECAPTURE": -0.46233758}
EXPECTED_BASE_HAZARD = {
    1: (0.899679, 0.038667, 0.061654),
    6: (0.942085, 0.024545, 0.033370),
    12: (0.957741, 0.016588, 0.025671),
    24: (0.970199, 0.013907, 0.015894),
}
VAL_TIME_CUT = pd.Timestamp("2026-03-05 00:00:00")
TEST_TIME_CUT = pd.Timestamp("2026-06-21 00:00:00")
ENVIRONMENTS = (
    "VAL_EARLY_UP", "VAL_EARLY_DOWN", "VAL_LATE_UP", "VAL_LATE_DOWN",
    "TEST_EARLY_UP", "TEST_EARLY_DOWN", "TEST_LATE_UP", "TEST_LATE_DOWN",
)


def _compile_node(node: ast.AST, filename: str):
    mod = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(mod)
    return compile(mod, filename, "exec")


def _execute_historical_dataset(source: str) -> dict:
    """Execute only frozen historical construction through cells/features.

    The source's own load_tf hard-cuts every timeframe before Exp27 SHADOW_START.
    No model fit/result-bearing top-level block is executed here.
    """
    tree = ast.parse(source, filename="<EXP49_DL01_HISTORICAL_ONLY>")
    nodes = [
        n for n in tree.body
        if getattr(n, "end_lineno", getattr(n, "lineno", 0)) <= STRUCTURAL_DATA_END_LINE
    ]
    ns = {"__name__": "__decision01_historical__", "__file__": str(e27.LAUNCHER)}

    # Suppress verbose embedded reproduction prints; all critical guards are
    # explicitly reprinted below by this runner.
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        for node in nodes:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bad = e27.call_names(node) & e27.FORBIDDEN_CALLS
                if bad:
                    line = getattr(node, "lineno", -1)
                    raise RuntimeError(f"ABORT BEFORE SCORE: forbidden call at line {line}: {sorted(bad)}")
            exec(_compile_node(node, "<EXP49_DL01_BUILD>"), ns, ns)

    for name in ("dyn", "hazard", "cells", "softmax_baseline", "fit_multinomial_baseline"):
        if name not in ns:
            raise RuntimeError(f"ABORT BEFORE SCORE: frozen source did not produce {name}")
    return ns


def _guard_exact_universe(ns: dict) -> None:
    dyn = ns["dyn"]
    cells = ns["cells"]
    hazard = ns["hazard"]

    if len(dyn) != EXPECTED_DYN:
        raise RuntimeError(f"ABORT BEFORE SCORE: dyn={len(dyn)} expected={EXPECTED_DYN}")
    got_splits = {k: int(dyn["period"].eq(k).sum()) for k in EXPECTED_SPLITS}
    if got_splits != EXPECTED_SPLITS:
        raise RuntimeError(f"ABORT BEFORE SCORE: dyn splits={got_splits} expected={EXPECTED_SPLITS}")

    got_cells = {k: int(cells["period"].eq(k).sum()) for k in EXPECTED_CELLS}
    if got_cells != EXPECTED_CELLS:
        raise RuntimeError(f"ABORT BEFORE SCORE: cells={got_cells} expected={EXPECTED_CELLS}")
    for period, expected in EXPECTED_CELLS_H.items():
        q = cells.loc[cells["period"].eq(period)]
        got = {h: int(q["horizon"].eq(h).sum()) for h in HORIZONS}
        if got != expected:
            raise RuntimeError(f"ABORT BEFORE SCORE: {period} horizon cells={got} expected={expected}")

    train_hazard = hazard.loc[hazard["period"].eq("TRAIN")].copy()
    if len(train_hazard) != EXPECTED_TRAIN_HAZARD:
        raise RuntimeError(
            f"ABORT BEFORE SCORE: TRAIN hazard={len(train_hazard)} expected={EXPECTED_TRAIN_HAZARD}"
        )
    cls = {
        "STAY": int(train_hazard["label"].eq(ns["STAY"]).sum()),
        "ADVANCE": int(train_hazard["label"].eq(ns["ADVANCE"]).sum()),
        "RECAPTURE": int(train_hazard["label"].eq(ns["RECAPTURE"]).sum()),
    }
    if cls != EXPECTED_TRAIN_HAZARD_CLASSES:
        raise RuntimeError(f"ABORT BEFORE SCORE: TRAIN hazard classes={cls} expected={EXPECTED_TRAIN_HAZARD_CLASSES}")

    print("DL01_EXACT_UNIVERSE_GUARD = PASS")
    print(f"  dyn          = {len(dyn)} | TRAIN={got_splits['TRAIN']} VALIDATION={got_splits['VALIDATION']} TEST={got_splits['TEST']}")
    print(f"  cells        = TRAIN={got_cells['TRAIN']} VALIDATION={got_cells['VALIDATION']} TEST={got_cells['TEST']}")
    print(f"  train_hazard = {len(train_hazard)} | STAY={cls['STAY']} ADV={cls['ADVANCE']} REC={cls['RECAPTURE']}")


def _fit_exp41_models(ns: dict) -> tuple[np.ndarray, np.ndarray]:
    hazard = ns["hazard"]
    train = hazard.loc[hazard["period"].eq("TRAIN")].copy().reset_index(drop=True)
    step = train["step"].to_numpy(int)
    if np.any((step < 1) | (step > MAX_STEP)):
        raise RuntimeError("ABORT BEFORE SCORE: invalid TRAIN hazard step")
    dummies = np.eye(MAX_STEP, dtype=float)[step - 1]
    y = train["label"].to_numpy(int)

    B_base, it_base, conv_base = ns["fit_multinomial_baseline"](dummies, y)
    X_pos = np.column_stack([dummies, train["geo0"].to_numpy(float)])
    B_pos, it_pos, conv_pos = ns["fit_multinomial_baseline"](X_pos, y)

    if not conv_base or not conv_pos or not np.isfinite(B_base).all() or not np.isfinite(B_pos).all():
        raise RuntimeError("ABORT BEFORE SCORE: Exp41 deterministic TRAIN refit did not converge finitely")

    got_adv = float(B_pos[0, -1])
    got_rec = float(B_pos[1, -1])
    if not np.isclose(got_adv, EXPECTED_POSITION_GEO["ADVANCE"], atol=5e-7, rtol=0.0):
        raise RuntimeError(
            f"ABORT BEFORE SCORE: POSITION beta_ADV_geo={got_adv:.9f} expected~{EXPECTED_POSITION_GEO['ADVANCE']:.8f}"
        )
    if not np.isclose(got_rec, EXPECTED_POSITION_GEO["RECAPTURE"], atol=5e-7, rtol=0.0):
        raise RuntimeError(
            f"ABORT BEFORE SCORE: POSITION beta_REC_geo={got_rec:.9f} expected~{EXPECTED_POSITION_GEO['RECAPTURE']:.8f}"
        )

    base_h = ns["softmax_baseline"](np.eye(MAX_STEP, dtype=float), B_base)
    for step_i, exp in EXPECTED_BASE_HAZARD.items():
        got = tuple(float(x) for x in base_h[step_i - 1])
        if tuple(round(x, 6) for x in got) != exp:
            raise RuntimeError(
                f"ABORT BEFORE SCORE: BASE hazard step={step_i} got={tuple(round(x,6) for x in got)} expected={exp}"
            )

    print("DL01_EXP41_MODEL_REPRODUCTION_GUARD = PASS")
    print(f"  BASE fit iterations     = {it_base}")
    print(f"  POSITION fit iterations = {it_pos}")
    print(f"  beta_ADV_geo            = {got_adv:+.8f}")
    print(f"  beta_REC_geo            = {got_rec:+.8f}")
    for step_i in (1, 6, 12, 24):
        p = base_h[step_i - 1]
        print(f"  BASE {step_i*5:>3}m hazard        = STAY {p[ns['STAY']]:.6f} ADV {p[ns['ADVANCE']]:.6f} REC {p[ns['RECAPTURE']]:.6f}")
    return B_base, B_pos


def _predict_cif(ns: dict, dyn: pd.DataFrame, B: np.ndarray, use_geo: bool) -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    n = len(dyn)
    surv = np.ones(n, dtype=float)
    cif_adv = np.zeros(n, dtype=float)
    cif_rec = np.zeros(n, dtype=float)
    geo = dyn["geo_logit"].to_numpy(float)
    out: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    for step in range(1, MAX_STEP + 1):
        d = np.zeros((n, MAX_STEP), dtype=float)
        d[:, step - 1] = 1.0
        X = np.column_stack([d, geo]) if use_geo else d
        p = ns["softmax_baseline"](X, B)
        pa = p[:, ns["ADVANCE"]]
        pr = p[:, ns["RECAPTURE"]]
        ps = p[:, ns["STAY"]]
        cif_adv += surv * pa
        cif_rec += surv * pr
        surv *= ps
        h = step * 5
        if h in HORIZONS:
            out[h] = (surv.copy(), cif_adv.copy(), cif_rec.copy())

    if set(out) != set(HORIZONS):
        raise RuntimeError("Missing cumulative horizon prediction")
    return out


def _environment(period: str, state_time: pd.Timestamp, bias: float) -> str | None:
    if period == "VALIDATION":
        era = "VAL_EARLY" if state_time < VAL_TIME_CUT else "VAL_LATE"
    elif period == "TEST":
        era = "TEST_EARLY" if state_time < TEST_TIME_CUT else "TEST_LATE"
    else:
        return None
    side = "UP" if bias > 0 else "DOWN"
    return f"{era}_{side}"


def _build_score_frame(ns: dict, base_pred, pos_pred) -> pd.DataFrame:
    dyn = ns["dyn"].copy().reset_index(drop=True)
    cells = ns["cells"].copy().reset_index(drop=True)
    dyn["state_id"] = np.arange(len(dyn), dtype=int)

    needed = ["state_id", "position", "geo_logit", "d_back_atr", "d_forward_atr"]
    if any(c not in dyn.columns for c in needed):
        raise RuntimeError(f"ABORT BEFORE SCORE: dyn missing {[c for c in needed if c not in dyn.columns]}")

    q = cells.merge(dyn[needed], on="state_id", how="left", validate="many_to_one")
    if len(q) != len(cells) or q[needed[1:]].isna().any().any():
        raise RuntimeError("ABORT BEFORE SCORE: cell/state mapping failed")

    q["state_time"] = pd.to_datetime(q["state_time"], errors="coerce")
    if q["state_time"].isna().any():
        raise RuntimeError("ABORT BEFORE SCORE: invalid state_time")

    n = len(q)
    p_exit = np.empty(n, dtype=float)
    q_adv = np.empty(n, dtype=float)
    p_sum_err = np.empty(n, dtype=float)

    for h in HORIZONS:
        mask = q["horizon"].eq(h).to_numpy(bool)
        ids = q.loc[mask, "state_id"].to_numpy(int)
        s0, a0, r0 = base_pred[h]
        sp, ap, rp = pos_pred[h]
        e = a0[ids] + r0[ids]
        den = ap[ids] + rp[ids]
        if np.any(den <= 0) or np.any(~np.isfinite(den)):
            raise RuntimeError("ABORT BEFORE SCORE: invalid POSITION CIF denominator")
        qa = ap[ids] / den
        p_exit[mask] = e
        q_adv[mask] = qa
        p_sum_err[mask] = np.abs((1.0 - e) + e * qa + e * (1.0 - qa) - 1.0)

    q["p_exit_base"] = p_exit
    q["q_adv_pos"] = q_adv
    q["edge_prob"] = q["q_adv_pos"] - q["position"]
    q["width_atr"] = q["d_back_atr"] + q["d_forward_atr"]
    q["structural_edge_atr"] = q["p_exit_base"] * q["width_atr"] * q["edge_prob"]

    adv, rec = ns["ADVANCE"], ns["RECAPTURE"]
    lab = q["label"].to_numpy(int)
    q["y_adv_atr"] = np.where(
        lab == adv,
        q["d_forward_atr"].to_numpy(float),
        np.where(lab == rec, -q["d_back_atr"].to_numpy(float), 0.0),
    )
    sign = np.sign(q["edge_prob"].to_numpy(float))
    q["policy_side"] = np.where(sign > 0, "ADVANCE", np.where(sign < 0, "RECAPTURE", "WAIT"))
    q["y_policy_atr"] = sign * q["y_adv_atr"].to_numpy(float)
    q["pred_policy_ev_atr"] = np.abs(q["structural_edge_atr"].to_numpy(float))
    y = q["y_adv_atr"].to_numpy(float)
    pred = q["structural_edge_atr"].to_numpy(float)
    q["mse_gain_row"] = y * y - (y - pred) ** 2
    q["prob_sum_error"] = p_sum_err

    p = q["position"].to_numpy(float)
    geom_p = q["d_back_atr"].to_numpy(float) / q["width_atr"].to_numpy(float)
    q["geometry_identity_error"] = np.abs(p - geom_p)
    direct = q["p_exit_base"].to_numpy(float) * (
        q["q_adv_pos"].to_numpy(float) * q["d_forward_atr"].to_numpy(float)
        - (1.0 - q["q_adv_pos"].to_numpy(float)) * q["d_back_atr"].to_numpy(float)
    )
    q["ev_identity_error"] = np.abs(direct - pred)

    q["environment"] = [
        _environment(str(per), pd.Timestamp(t), float(b))
        for per, t, b in zip(q["period"], q["state_time"], q["bias_sign"])
    ]
    return q


def _bootstrap_two(q: pd.DataFrame, seed: int) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    g = q.groupby("brt_date", sort=True).agg(
        n=("mse_gain_row", "size"),
        mse_sum=("mse_gain_row", "sum"),
        policy_sum=("y_policy_atr", "sum"),
    )
    if len(g) < 2:
        raise RuntimeError("UNDERPOWERED: fewer than two contributing BRT days")
    n = g["n"].to_numpy(float)
    ms = g["mse_sum"].to_numpy(float)
    ps = g["policy_sum"].to_numpy(float)
    m = len(g)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, m, size=(N_BOOT, m))
    denom = n[idx].sum(axis=1)
    bm = ms[idx].sum(axis=1) / denom
    bp = ps[idx].sum(axis=1) / denom

    point_m = float(q["mse_gain_row"].mean())
    point_p = float(q["y_policy_atr"].mean())
    ci_m = np.quantile(bm, [0.025, 0.975])
    ci_p = np.quantile(bp, [0.025, 0.975])
    return (point_m, float(ci_m[0]), float(ci_m[1])), (point_p, float(ci_p[0]), float(ci_p[1]))


def _corrs(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    a = pd.to_numeric(x, errors="coerce")
    b = pd.to_numeric(y, errors="coerce")
    ok = a.notna() & b.notna()
    a, b = a[ok], b[ok]
    if len(a) < 3 or a.nunique() < 2 or b.nunique() < 2:
        return float("nan"), float("nan")
    pearson = float(a.corr(b, method="pearson"))
    spearman = float(a.rank(method="average").corr(b.rank(method="average"), method="pearson"))
    return pearson, spearman


def main() -> int:
    print("=" * 132)
    print("DECISION LAYER 01 — STRUCTURAL EDGE / GEOMETRY BREAK-EVEN")
    print("=" * 132)
    print("Historical OOS          = REPEATEDLY INSPECTED / EXPLORATORY ONLY")
    print("Exp27                   = UNTOUCHED / SCORES SEALED")
    print("Operability filtering   = PROHIBITED IN DL01")
    print("Costs/slippage           = NOT PART OF DL01")
    print("Threshold optimization  = PROHIBITED")
    print("Runtime promotion        = NONE")
    print(f"Bootstrap                = whole-BRT-day, state-horizon weighted, N={N_BOOT}, seed={BOOT_SEED}")
    print()

    source = e27.decode_source(e27.LAUNCHER)
    # First exact backbone guard uses the already-hardened Exp27 no-score helper.
    e27.historical_guard(source)
    ns = _execute_historical_dataset(source)
    _guard_exact_universe(ns)
    B_base, B_pos = _fit_exp41_models(ns)

    base_pred = _predict_cif(ns, ns["dyn"], B_base, use_geo=False)
    pos_pred = _predict_cif(ns, ns["dyn"], B_pos, use_geo=True)
    q = _build_score_frame(ns, base_pred, pos_pred)

    # Only historical OOS environments enter formal score.
    formal = q.loc[q["environment"].isin(ENVIRONMENTS)].copy().reset_index(drop=True)
    missing_env = [e for e in ENVIRONMENTS if e not in set(formal["environment"].dropna())]
    if missing_env:
        raise RuntimeError(f"ABORT BEFORE SCORE: missing formal environments {missing_env}")

    print()
    print("DL01 ALGEBRA / MAPPING GUARDS")
    print(f"  max probability-sum error = {formal['prob_sum_error'].max():.3e}")
    print(f"  max geometry identity err = {formal['geometry_identity_error'].max():.3e}")
    print(f"  max EV identity error     = {formal['ev_identity_error'].max():.3e}")
    if formal["prob_sum_error"].max() > 1e-12 or formal["geometry_identity_error"].max() > 1e-10 or formal["ev_identity_error"].max() > 1e-10:
        raise RuntimeError("ABORT BEFORE SCORE: algebra/mapping identity guard failed")

    print()
    print("PRIMARY FORMAL RESULTS — pooled H=15/30/60/120 within each frozen environment")
    print("positive gain/payoff and CI95 lower > 0 required for BOTH metrics in ALL 8 environments")
    metric_passes = 0
    env_passes = 0
    rows = []
    for i, env in enumerate(ENVIRONMENTS):
        z = formal.loc[formal["environment"].eq(env)].copy()
        classes = z["label_name"].value_counts().to_dict()
        if len(classes) < 3:
            raise RuntimeError(f"UNDERPOWERED {env}: not all three classes present: {classes}")
        mse, pol = _bootstrap_two(z, BOOT_SEED + i)
        pm = mse[0] > 0 and mse[1] > 0
        pp = pol[0] > 0 and pol[1] > 0
        metric_passes += int(pm) + int(pp)
        env_pass = pm and pp
        env_passes += int(env_pass)
        rows.append((env, z, mse, pol, pm, pp))
        print(
            f"{env:<18} n={len(z):>5} days={z['brt_date'].nunique():>3} | "
            f"MSE_GAIN {mse[0]:+.9f} CI[{mse[1]:+.9f},{mse[2]:+.9f}] {'PASS' if pm else 'FAIL'} | "
            f"POLICY {pol[0]:+.9f} CI[{pol[1]:+.9f},{pol[2]:+.9f}] {'PASS' if pp else 'FAIL'}"
        )

    print()
    print("DIAGNOSTICS ONLY — cannot rescue formal result")
    for env, z, *_ in rows:
        pear, spear = _corrs(z["structural_edge_atr"], z["y_adv_atr"])
        side = z["policy_side"].value_counts(normalize=True)
        print(
            f"{env:<18} EDGE mean={z['edge_prob'].mean():+.5f} med={z['edge_prob'].median():+.5f} "
            f"|abs|={z['edge_prob'].abs().mean():.5f} predEVabs={z['pred_policy_ev_atr'].mean():.5f} "
            f"ADV={side.get('ADVANCE',0):.3f} REC={side.get('RECAPTURE',0):.3f} WAIT={side.get('WAIT',0):.3f} "
            f"Pearson={pear:+.4f} Spearman={spear:+.4f}"
        )

    print()
    print("HORIZON DIAGNOSTICS ONLY")
    for h in HORIZONS:
        z = formal.loc[formal["horizon"].eq(h)]
        print(
            f"H={h:>3}m n={len(z):>5} MSE_GAIN={z['mse_gain_row'].mean():+.9f} "
            f"POLICY={z['y_policy_atr'].mean():+.9f} |EDGE|={z['edge_prob'].abs().mean():.5f} "
            f"predEVabs={z['pred_policy_ev_atr'].mean():.5f}"
        )

    robust = metric_passes == 16 and env_passes == 8
    print()
    print(f"DL01_FORMAL_METRIC_CELLS_PASS = {metric_passes}/16")
    print(f"DL01_ENVIRONMENTS_FULL_PASS   = {env_passes}/8")
    print(f"ROBUST_STRUCTURAL_DECISION_EDGE = {'PASS' if robust else 'FAIL'}")
    print(f"DECISION_LAYER_01_FORMAL_STATUS = {'PASS' if robust else 'FAIL'}")
    print("HISTORICAL_TIMING_FEATURE_DISCOVERY_STOP = PRESERVED_YES")
    print("EXP27 = UNTOUCHED / SCORES_SEALED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
