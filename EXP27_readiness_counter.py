#!/usr/bin/env python3
"""EXP27 prospective maturity counter — NO SCORE.

Reuses the exact frozen structural construction embedded in EXP49 and executes
only the source prefix through `dyn` creation. Any score-bearing top-level call
is blocked. The counter first requires exact historical reproduction, then
builds fresh-forward states from historical research + rolling live parquets.

Nothing here computes or prints Brier, LogLoss, AUC, calibration, class
residuals, model gains, PnL or any Exp27 model score.
"""
from __future__ import annotations

import ast
import base64
import hashlib
from pathlib import Path
import zlib

import pandas as pd

HERE = Path(__file__).resolve().parent
LAUNCHER = HERE / "EXP49_symmetric_boundary_timing.py"
LIVE_DIR = HERE / "data"
OUT_DIR = HERE / "data" / "market_chronos" / "exp27"
LEDGER_PATH = OUT_DIR / "EXP27_fresh_state_readiness.csv"

SHADOW_START = pd.Timestamp("2026-08-13 00:00:00")
MATURITY_DAYS = 60
MATURITY_STATES = 1500

EXPECTED_RAW_DYNAMIC = 9826
EXPECTED_DYN = 9667
EXPECTED_SPLITS = {"TRAIN": 5612, "VALIDATION": 1959, "TEST": 2096}
STRUCTURAL_END_LINE = 600

FORBIDDEN_CALLS = {
    "fit_multinomial_baseline",
    "multiclass_score",
    "multiclass_row_loss",
    "binary_row_loss",
    "auc_score",
    "whole_day_bootstrap",
    "fit_binary_logit",
    "predict_exit_cumulative",
    "cell_prediction_from_state",
    "holm_adjust",
}


def extract_payload(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_PAYLOAD":
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, str):
                        raise TypeError("_PAYLOAD is not a string literal")
                    return value
    raise RuntimeError("Could not locate _PAYLOAD")


def decode_source(path: Path) -> str:
    payload = extract_payload(path)
    raw = base64.b64decode(payload.encode("ascii"), validate=True)
    return zlib.decompress(raw).decode("utf-8")


def call_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        fn = child.func
        if isinstance(fn, ast.Name):
            out.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            out.add(fn.attr)
    return out


def compile_node(node: ast.AST, filename: str):
    mod = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(mod)
    return compile(mod, filename, "exec")


def is_load_node(node: ast.AST) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False
    return "load_tf" in call_names(node)


def execute_structural_prefix(source: str, custom_load_tf=None, relax_counts: bool = False) -> dict:
    tree = ast.parse(source, filename="<EXP49_DECODED_STRUCTURAL_ONLY>")
    nodes = [
        n for n in tree.body
        if getattr(n, "end_lineno", getattr(n, "lineno", 0)) <= STRUCTURAL_END_LINE
    ]
    first_load = next((i for i, n in enumerate(nodes) if is_load_node(n)), None)
    if first_load is None:
        raise RuntimeError("Could not locate structural load_tf call")

    ns = {"__name__": "__exp27_structural_only__", "__file__": str(LAUNCHER)}

    for node in nodes[:first_load]:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bad = call_names(node) & FORBIDDEN_CALLS
            if bad:
                raise RuntimeError(f"Blocked score call before structural load: {sorted(bad)}")
        exec(compile_node(node, "<EXP49_STRUCTURAL_PRELUDE>"), ns, ns)

    if custom_load_tf is not None:
        ns["load_tf"] = lambda tf: custom_load_tf(tf, ns)
    if relax_counts:
        ns["assert_count"] = lambda *args, **kwargs: None

    for node in nodes[first_load:]:
        bad = call_names(node) & FORBIDDEN_CALLS
        if bad:
            line = getattr(node, "lineno", -1)
            raise RuntimeError(f"Blocked score-bearing call at line {line}: {sorted(bad)}")
        exec(compile_node(node, "<EXP49_STRUCTURAL_BUILD>"), ns, ns)

    if "dyn" not in ns or "dyn_raw" not in ns:
        raise RuntimeError("Structural prefix did not produce dyn/dyn_raw")
    return ns


def historical_guard(source: str) -> None:
    ns = execute_structural_prefix(source)
    dyn_raw = ns["dyn_raw"]
    dyn = ns["dyn"]
    got_splits = {k: int(dyn["period"].eq(k).sum()) for k in EXPECTED_SPLITS}

    if len(dyn_raw) != EXPECTED_RAW_DYNAMIC:
        raise RuntimeError(f"raw_dynamic mismatch: got {len(dyn_raw)}, expected {EXPECTED_RAW_DYNAMIC}")
    if len(dyn) != EXPECTED_DYN:
        raise RuntimeError(f"dyn mismatch: got {len(dyn)}, expected {EXPECTED_DYN}")
    if got_splits != EXPECTED_SPLITS:
        raise RuntimeError(f"split mismatch: got {got_splits}, expected {EXPECTED_SPLITS}")

    print("EXP27_HISTORICAL_STATE_GUARD = PASS")
    print(f"  raw_dynamic = {len(dyn_raw)}")
    print(f"  dyn          = {len(dyn)}")
    print("  splits       = " + " ".join(f"{k}={got_splits[k]}" for k in ("TRAIN", "VALIDATION", "TEST")))


def prepared(path: Path, tf: str, ns: dict) -> pd.DataFrame:
    q = ns["v1"].prepare(path, tf, ns["rules"]).copy()
    if "available_at_brt" not in q.columns:
        raise RuntimeError(f"{path} missing available_at_brt")
    q["available_at_brt"] = pd.to_datetime(q["available_at_brt"], errors="coerce")
    if q["available_at_brt"].isna().any():
        raise RuntimeError(f"{path} has invalid available_at_brt")
    return q.sort_values("available_at_brt").reset_index(drop=True)


def combined_loader(tf: str, ns: dict) -> pd.DataFrame:
    hist_root = Path(ns["ROOT"])
    hist_path = hist_root / f"GOLD_{tf}_candle_research.parquet"
    live_path = LIVE_DIR / f"GOLD_{tf}.parquet"

    if not hist_path.exists():
        raise FileNotFoundError(hist_path)
    if not live_path.exists():
        raise FileNotFoundError(
            f"Missing live {tf}: {live_path}. Run Base_Dados.py --mode intraday_refresh --symbol GOLD first."
        )

    hist = prepared(hist_path, tf, ns)
    live = prepared(live_path, tf, ns)

    hist_pre = hist.loc[hist["available_at_brt"].lt(SHADOW_START)].copy()
    if hist_pre.empty:
        raise RuntimeError(f"No historical {tf} data before shadow start")

    hist_last = hist_pre["available_at_brt"].max()
    bridge = live.loc[
        live["available_at_brt"].gt(hist_last)
        & live["available_at_brt"].lt(SHADOW_START)
    ].copy()
    fresh = live.loc[live["available_at_brt"].ge(SHADOW_START)].copy()

    q = pd.concat([hist_pre, bridge, fresh], ignore_index=True, sort=False)
    q = q.sort_values("available_at_brt").drop_duplicates("available_at_brt", keep="first").reset_index(drop=True)
    return q


def fresh_identity(dyn: pd.DataFrame) -> pd.DataFrame:
    state_time = pd.to_datetime(dyn["state_time"], errors="coerce")
    if state_time.isna().any():
        raise RuntimeError("dyn has invalid state_time")
    fresh = dyn.loc[state_time.ge(SHADOW_START)].copy()

    cols = [
        "state_key", "state_time", "episode_id", "bias_sign",
        "back", "forward", "position", "dwell_bars",
    ]
    missing = sorted(set(cols) - set(fresh.columns))
    if missing:
        raise RuntimeError(f"Fresh dyn missing identity columns: {missing}")

    out = fresh[cols].copy()
    out["state_time"] = pd.to_datetime(out["state_time"])
    out["brt_date"] = out["state_time"].dt.date.astype(str)
    out["first_counted_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    return out.sort_values(["state_time", "episode_id"]).reset_index(drop=True)


def append_ledger(new_states: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if LEDGER_PATH.exists():
        old = pd.read_csv(LEDGER_PATH)
    else:
        old = pd.DataFrame(columns=new_states.columns)

    if not old.empty and "state_key" not in old.columns:
        raise RuntimeError("Existing readiness ledger missing state_key")

    before = len(old)
    q = pd.concat([old, new_states], ignore_index=True, sort=False)
    q = q.drop_duplicates("state_key", keep="first")
    q["state_time"] = pd.to_datetime(q["state_time"], errors="coerce")
    if q["state_time"].isna().any():
        raise RuntimeError("Readiness ledger has invalid state_time")
    q = q.sort_values(["state_time", "episode_id"]).reset_index(drop=True)
    q.to_csv(LEDGER_PATH, index=False)
    return q, int(len(q) - before)


def main() -> int:
    print("=" * 132)
    print("EXP27 — PROSPECTIVE MATURITY COUNTER (NO SCORE)")
    print("=" * 132)
    print("Exp27 score metrics = SEALED")
    print("Outcome reporting   = PROHIBITED")
    print("Runtime promotion   = NONE")
    print()

    if not LAUNCHER.exists():
        raise FileNotFoundError(LAUNCHER)

    source = decode_source(LAUNCHER)
    print(f"Frozen EXP49 decoded sha256 = {hashlib.sha256(source.encode('utf-8')).hexdigest()}")
    historical_guard(source)

    ns = execute_structural_prefix(source, custom_load_tf=combined_loader, relax_counts=True)
    states = fresh_identity(ns["dyn"])
    ledger, appended = append_ledger(states)

    state_count = int(len(ledger))
    eligible_days = int(pd.to_datetime(ledger["state_time"]).dt.date.nunique()) if state_count else 0
    ready = eligible_days >= MATURITY_DAYS and state_count >= MATURITY_STATES

    print()
    print("Fresh-forward readiness ledger:")
    print(f"  path                = {LEDGER_PATH}")
    print(f"  new_states_appended = {appended}")
    print(f"  dynamic_states      = {state_count} / {MATURITY_STATES}")
    print(f"  eligible_BRT_days   = {eligible_days} / {MATURITY_DAYS}")
    if state_count:
        st = pd.to_datetime(ledger["state_time"])
        print(f"  first_state_time    = {st.min()}")
        print(f"  last_state_time     = {st.max()}")

    print()
    print(f"EXP27_MATURITY_STATUS = {'READY_FOR_ONE_SHOT_SCORE' if ready else 'ACCUMULATING'}")
    print("EXP27_SCORES = SEALED" if not ready else "EXP27_SCORES = MAY_BE_OPENED ONCE UNDER FROZEN CONTRACT")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
