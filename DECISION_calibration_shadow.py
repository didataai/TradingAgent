#!/usr/bin/env python3
"""Prospective Decision Calibration shadow — readiness only before maturity.

Uses the TRAIN-only Platt calibrator frozen on 2026-08-17. Historical
Validation/Test scores are not computed. Exp27 is untouched. The local ledger
is append-only evidence; console output exposes readiness counts only.

Important separation:
- the historical-only execution MUST reproduce every frozen historical guard;
- the combined historical+live execution reuses the same state/cell machine but
  MUST NOT re-assert fixed historical split counts after fresh rows are appended.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

import DECISION01_structural_edge as d
import EXP27_readiness_counter as e27

ROOT = Path(__file__).resolve().parent
START = pd.Timestamp("2026-08-18 00:00:00")
MATURITY_DAYS = 60
MATURITY_EXIT_CELLS = 1000
ALPHA = 0.012014589920
BETA = 1.094032434562
TRAIN_EXIT_CELLS = 10152
TRAIN_ADV = 4179
TRAIN_REC = 5973
TRAIN_H = {15: 1342, 30: 2085, 60: 2970, 120: 3755}
FINGERPRINT = "940acfb845707487f6de889aa0cf77ec6a2b58d4e1f78761eef17fc4fffa8824"
LEDGER_DIR = ROOT / "data" / "market_chronos" / "decision"
LEDGER = LEDGER_DIR / "DECISION_calibration_shadow.csv"
LEDGER_COLUMNS = [
    "cell_key", "state_key", "state_time", "brt_date", "horizon", "bias_sign",
    "position", "d_back_atr", "d_forward_atr", "p_exit_base", "q_raw", "q_cal",
    "label", "first_counted_at_utc",
]


def _compile(node: ast.AST, filename: str):
    mod = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(mod)
    return compile(mod, filename, "exec")


def _is_fixed_historical_reproduction_guard(node: ast.AST) -> bool:
    """Identify only frozen-count guards that cannot hold after fresh append.

    The embedded historical runner contains top-level RuntimeError checks whose
    messages explicitly say REPRODUCTION ... FAILED. Those are correct in the
    historical-only guard and are executed there before this function is ever
    used. In the combined hist+live build their fixed TEST counts are expected
    to grow, so only these explicit reproduction guards are skipped.

    Structural construction, mapping, causal denominator checks and all other
    RuntimeErrors remain active.
    """
    has_runtime_raise = False
    messages: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Raise) and isinstance(child.exc, ast.Call):
            fn = child.exc.func
            if isinstance(fn, ast.Name) and fn.id == "RuntimeError":
                has_runtime_raise = True
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            messages.append(child.value.upper())
    return has_runtime_raise and any(
        "REPRODUCTION" in msg and "FAILED" in msg for msg in messages
    )


def _execute_combined(source: str) -> dict:
    """Execute frozen EXP49 through cells with hist+live data.

    Fixed historical reproduction-count guards are intentionally skipped here
    because fresh rows extend the historical TEST bucket. The exact historical
    universe is reproduced separately before this function is called.
    """
    tree = ast.parse(source, filename="<DECISION_CAL_SHADOW>")
    nodes = [
        n for n in tree.body
        if getattr(n, "end_lineno", getattr(n, "lineno", 0)) <= d.STRUCTURAL_DATA_END_LINE
    ]
    first_load = next((i for i, n in enumerate(nodes) if e27.is_load_node(n)), None)
    if first_load is None:
        raise RuntimeError("ABORT: structural load_tf call not found")

    ns = {"__name__": "__decision_cal_shadow__", "__file__": str(e27.LAUNCHER)}
    skipped_reproduction_guards = 0
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        for node in nodes[:first_load]:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bad = e27.call_names(node) & e27.FORBIDDEN_CALLS
                if bad:
                    raise RuntimeError(f"ABORT: forbidden pre-load call {sorted(bad)}")
            exec(_compile(node, "<DECISION_CAL_PRELUDE>"), ns, ns)

        ns["load_tf"] = lambda tf: e27.combined_loader(tf, ns)
        ns["assert_count"] = lambda *args, **kwargs: None
        if "assert_close" in ns:
            ns["assert_close"] = lambda *args, **kwargs: None

        for node in nodes[first_load:]:
            if _is_fixed_historical_reproduction_guard(node):
                skipped_reproduction_guards += 1
                continue
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bad = e27.call_names(node) & e27.FORBIDDEN_CALLS
                if bad:
                    raise RuntimeError(
                        f"ABORT: forbidden top-level call line={getattr(node,'lineno',-1)} {sorted(bad)}"
                    )
            exec(_compile(node, "<DECISION_CAL_BUILD>"), ns, ns)

    for name in ("dyn", "cells", "softmax_baseline"):
        if name not in ns:
            raise RuntimeError(f"ABORT: combined source did not produce {name}")
    ns["_combined_reproduction_guards_skipped"] = skipped_reproduction_guards
    return ns


def _fit_platt(q_raw: np.ndarray, y_adv: np.ndarray) -> tuple[float, float, int]:
    p0 = np.clip(np.asarray(q_raw, float), 1e-12, 1.0 - 1e-12)
    z = np.log(p0 / (1.0 - p0))
    X = np.column_stack([np.ones(len(z), dtype=float), z])
    y = np.asarray(y_adv, float)
    coef = np.zeros(2, dtype=float)
    for it in range(1, 101):
        eta = np.clip(X @ coef, -35.0, 35.0)
        p = np.empty_like(eta)
        pos = eta >= 0
        p[pos] = 1.0 / (1.0 + np.exp(-eta[pos]))
        ez = np.exp(eta[~pos])
        p[~pos] = ez / (1.0 + ez)
        w = np.clip(p * (1.0 - p), 1e-10, None)
        grad = X.T @ (y - p)
        info = X.T @ (X * w[:, None]) + np.eye(2) * 1e-10
        try:
            step = np.linalg.solve(info, grad)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(info) @ grad
        coef += step
        if not np.isfinite(coef).all():
            raise RuntimeError("ABORT: non-finite calibration coefficients")
        if np.max(np.abs(step)) < 1e-10:
            return float(coef[0]), float(coef[1]), it
    raise RuntimeError("ABORT: calibrator did not converge")


def _spec(alpha: float, beta: float) -> dict:
    return {
        "form": "q_cal=sigmoid(alpha+beta*logit(q_raw))",
        "alpha": round(alpha, 12),
        "beta": round(beta, 12),
        "train_exit_cells": TRAIN_EXIT_CELLS,
        "train_adv": TRAIN_ADV,
        "train_rec": TRAIN_REC,
        "horizon_counts": TRAIN_H,
        "shadow_start_brt": "2026-08-18 00:00:00",
        "maturity_days": MATURITY_DAYS,
        "maturity_exit_cells": MATURITY_EXIT_CELLS,
    }


def _fingerprint(alpha: float, beta: float) -> str:
    payload = json.dumps(_spec(alpha, beta), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _guard_calibrator(ns: dict, B_pos: np.ndarray) -> None:
    pred = d._predict_cif(ns, ns["dyn"], B_pos, use_geo=True)
    cells = ns["cells"].loc[
        ns["cells"]["period"].eq("TRAIN"), ["state_id", "horizon", "label"]
    ].copy().reset_index(drop=True)
    q_raw = np.empty(len(cells), dtype=float)
    for h in d.HORIZONS:
        mask = cells["horizon"].eq(h).to_numpy(bool)
        ids = cells.loc[mask, "state_id"].to_numpy(int)
        _, a, r = pred[h]
        den = a[ids] + r[ids]
        if np.any(den <= 0) or np.any(~np.isfinite(den)):
            raise RuntimeError("ABORT: invalid TRAIN conditional-side denominator")
        q_raw[mask] = a[ids] / den
    cells["q_raw"] = q_raw
    fit = cells.loc[cells["label"].isin([ns["ADVANCE"], ns["RECAPTURE"]])].copy()
    fit["y_adv"] = fit["label"].eq(ns["ADVANCE"]).astype(int)
    counts_h = {h: int(fit["horizon"].eq(h).sum()) for h in d.HORIZONS}
    n_adv = int(fit["y_adv"].sum())
    n_rec = int(len(fit) - n_adv)
    if len(fit) != TRAIN_EXIT_CELLS or n_adv != TRAIN_ADV or n_rec != TRAIN_REC or counts_h != TRAIN_H:
        raise RuntimeError("ABORT: TRAIN calibration sample fingerprint changed")
    alpha, beta, it = _fit_platt(fit["q_raw"].to_numpy(float), fit["y_adv"].to_numpy(int))
    if not np.isclose(alpha, ALPHA, atol=5e-12, rtol=0.0):
        raise RuntimeError(f"ABORT: alpha mismatch {alpha:.12f}")
    if not np.isclose(beta, BETA, atol=5e-12, rtol=0.0):
        raise RuntimeError(f"ABORT: beta mismatch {beta:.12f}")
    fp = _fingerprint(alpha, beta)
    if fp != FINGERPRINT:
        raise RuntimeError(f"ABORT: calibration fingerprint mismatch {fp}")
    print("DECISION_CALIBRATION_FROZEN_GUARD = PASS")
    print(f"  TRAIN exit cells = {len(fit)}")
    print(f"  alpha            = {alpha:+.12f}")
    print(f"  beta             = {beta:+.12f}")
    print(f"  fit iterations   = {it}")
    print(f"  fingerprint      = {fp}")


def _calibrate(q_raw: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(q_raw, float), 1e-12, 1.0 - 1e-12)
    z = np.log(p / (1.0 - p))
    eta = np.clip(ALPHA + BETA * z, -35.0, 35.0)
    out = np.empty_like(eta)
    pos = eta >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-eta[pos]))
    ez = np.exp(eta[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


def _fresh_rows(source: str, B_base: np.ndarray, B_pos: np.ndarray) -> pd.DataFrame:
    ns = _execute_combined(source)
    dyn = ns["dyn"].copy().reset_index(drop=True)
    cells = ns["cells"].copy().reset_index(drop=True)
    dyn["state_id"] = np.arange(len(dyn), dtype=int)
    state_cols = ["state_id", "state_key", "position", "d_back_atr", "d_forward_atr"]
    missing = [c for c in state_cols if c not in dyn.columns]
    if missing:
        raise RuntimeError(f"ABORT: fresh dyn missing {missing}")
    q = cells.merge(dyn[state_cols], on="state_id", how="left", validate="many_to_one")
    q["state_time"] = pd.to_datetime(q["state_time"], errors="coerce")
    if q["state_time"].isna().any():
        raise RuntimeError("ABORT: invalid fresh state_time")
    q = q.loc[q["state_time"].ge(START)].copy().reset_index(drop=True)
    if q.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    base_pred = d._predict_cif(ns, dyn, B_base, use_geo=False)
    pos_pred = d._predict_cif(ns, dyn, B_pos, use_geo=True)
    p_exit = np.empty(len(q), dtype=float)
    q_raw = np.empty(len(q), dtype=float)
    for h in d.HORIZONS:
        mask = q["horizon"].eq(h).to_numpy(bool)
        if not mask.any():
            continue
        ids = q.loc[mask, "state_id"].to_numpy(int)
        _, a0, r0 = base_pred[h]
        _, ap, rp = pos_pred[h]
        den = ap[ids] + rp[ids]
        if np.any(den <= 0) or np.any(~np.isfinite(den)):
            raise RuntimeError("ABORT: invalid fresh conditional-side denominator")
        p_exit[mask] = a0[ids] + r0[ids]
        q_raw[mask] = ap[ids] / den
    q["p_exit_base"] = p_exit
    q["q_raw"] = q_raw
    q["q_cal"] = _calibrate(q_raw)

    q = q.loc[q["label"].isin([ns["ADVANCE"], ns["RECAPTURE"]])].copy()
    if q.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    q["cell_key"] = q["state_key"].astype(str) + "|H" + q["horizon"].astype(int).astype(str)
    q["brt_date"] = q["state_time"].dt.date.astype(str)
    q["first_counted_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    missing = [c for c in LEDGER_COLUMNS if c not in q.columns]
    if missing:
        raise RuntimeError(f"ABORT: ledger fields missing {missing}")
    return q[LEDGER_COLUMNS].sort_values(["state_time", "horizon"]).reset_index(drop=True)


def _append(new_rows: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(LEDGER) if LEDGER.exists() else pd.DataFrame(columns=LEDGER_COLUMNS)
    if not old.empty and "cell_key" not in old.columns:
        raise RuntimeError("ABORT: existing calibration ledger missing cell_key")
    before = len(old)
    if old.empty:
        ledger = new_rows.copy()
    elif new_rows.empty:
        ledger = old.copy()
    else:
        ledger = pd.concat([old, new_rows], ignore_index=True, sort=False)
    if not ledger.empty:
        ledger = ledger.drop_duplicates("cell_key", keep="first")
        ledger["state_time"] = pd.to_datetime(ledger["state_time"], errors="coerce")
        if ledger["state_time"].isna().any():
            raise RuntimeError("ABORT: calibration ledger has invalid state_time")
        ledger = ledger.sort_values(["state_time", "horizon"]).reset_index(drop=True)
        ledger.to_csv(LEDGER, index=False)
    return ledger, int(len(ledger) - before)


def main() -> int:
    print("=" * 132)
    print("DECISION CALIBRATION SHADOW — READINESS ONLY / SCORES SEALED")
    print("=" * 132)
    print(f"Shadow start      = {START} BRT")
    print(f"Maturity          = {MATURITY_DAYS} eligible BRT days AND {MATURITY_EXIT_CELLS} resolved EXIT state-horizon cells")
    print("Ledger evidence   = SEALED until maturity")
    print("Exp27             = UNTOUCHED / SCORES SEALED")
    print("Runtime promotion = NONE")
    print()

    source = e27.decode_source(e27.LAUNCHER)
    e27.historical_guard(source)
    ns_hist = d._execute_historical_dataset(source)
    d._guard_exact_universe(ns_hist)
    B_base, B_pos = d._fit_exp41_models(ns_hist)
    _guard_calibrator(ns_hist, B_pos)

    fresh = _fresh_rows(source, B_base, B_pos)
    ledger, appended = _append(fresh)
    n_cells = int(len(ledger))
    days = int(pd.to_datetime(ledger["state_time"]).dt.date.nunique()) if n_cells else 0
    ready = days >= MATURITY_DAYS and n_cells >= MATURITY_EXIT_CELLS

    print()
    print("Calibration shadow readiness:")
    print(f"  ledger_path         = {LEDGER}")
    print(f"  new_cells_appended  = {appended}")
    print(f"  eligible_BRT_days   = {days} / {MATURITY_DAYS}")
    print(f"  resolved_EXIT_cells = {n_cells} / {MATURITY_EXIT_CELLS}")
    if n_cells:
        st = pd.to_datetime(ledger["state_time"])
        print(f"  first_state_time    = {st.min()}")
        print(f"  last_state_time     = {st.max()}")
    print()
    print(f"DECISION_CALIBRATION_MATURITY_STATUS = {'READY_FOR_ONE_SHOT_SCORE' if ready else 'ACCUMULATING'}")
    print("DECISION_CALIBRATION_SCORES = SEALED" if not ready else "DECISION_CALIBRATION_SCORES = MAY_BE OPENED ONCE UNDER FROZEN CONTRACT")
    print("EXP27 = UNTOUCHED / SCORES SEALED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())