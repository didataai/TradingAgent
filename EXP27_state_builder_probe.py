#!/usr/bin/env python3
"""Frozen EXP49 source probe — AST-only / NO PAYLOAD EXECUTION.

The default mode inventories the exact structural-state construction used by
EXP49. `--decision` inventories the exact BASE/POSITION survival-model and
prediction blocks needed to build Decision Layer 01 without reconstructing the
frozen Exp47 law from memory.

Neither mode executes the decoded runner or computes any score.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
from pathlib import Path
import zlib

ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "EXP49_symmetric_boundary_timing.py"

STATE_TERMS = {
    "state_time", "episode_id", "bias_sign", "back", "forward", "corridor",
    "swing", "l1", "l2", "outside_15", "dynamic", "advance", "recapture",
    "stay", "dedup", "active", "frontier",
}

STRUCTURAL_FUNCTIONS = {
    "load_tf", "build_structure", "choose_l1", "first_above", "first_below",
    "select_nearest_active",
}

STRUCTURAL_ASSIGNMENTS = {
    "events", "n_events", "m5q", "touch_rows", "touches", "raw_touches",
    "unique_touches", "dyn_raw", "raw_dynamic", "dyn", "train_states",
}

DECISION_FUNCTIONS = {
    "sigmoid", "fit_binary_logit", "binary_design", "predict_exit_cumulative",
    "cell_prediction_from_state", "softmax_baseline", "fit_multinomial_baseline",
}

DECISION_TERMS = {
    "base_surv", "position_surv", "position", "geo", "geo0", "cif_adv",
    "cif_rec", "cif_advance", "cif_recapture", "p_no_exit", "p_exit",
    "state_exit_predictions", "cell_prediction", "hazard", "hazard_rows",
    "cell_rows", "theta", "coef", "beta", "intercept", "step", "horizon",
    "base_exit", "position_exit", "predict_exit_cumulative",
}

# Result/statistic-bearing blocks are never source-dumped in decision-probe mode.
# Model definitions/fits and deterministic predictions are allowed to be printed,
# because nothing is executed by this probe.
RESULT_TERMS = {
    "brier", "logloss", "log_loss", "auc_score", "whole_day_bootstrap",
    "holm_adjust", "mean_gain", "ci95", "p_gt_zero", "formal_cells",
}


def extract_payload_literal(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_PAYLOAD":
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, str):
                        raise TypeError("_PAYLOAD is not a string literal")
                    return value
    raise RuntimeError("Could not locate literal _PAYLOAD in EXP49 launcher")


def decode_payload(payload: str) -> str:
    raw = base64.b64decode(payload.encode("ascii"), validate=True)
    return zlib.decompress(raw).decode("utf-8")


def node_source(source_lines: list[str], node: ast.AST) -> str:
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if start is None or end is None:
        return ""
    return "\n".join(source_lines[start - 1 : end])


def names_in(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            out.add(child.id.lower())
        elif isinstance(child, ast.Attribute):
            out.add(child.attr.lower())
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            val = child.value.strip().lower()
            if val and len(val) <= 120:
                out.add(val)
    return out


def function_calls(node: ast.AST) -> set[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        fn = child.func
        if isinstance(fn, ast.Name):
            calls.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            calls.add(fn.attr)
    return calls


def assigned_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            out.add(child.id)
    return out


def print_source_block(title: str, source_lines: list[str], node: ast.AST) -> None:
    start = getattr(node, "lineno", -1)
    end = getattr(node, "end_lineno", start)
    print()
    print("-" * 132)
    print(f"{title} | lines={start}-{end}")
    print("-" * 132)
    src = node_source(source_lines, node)
    for lineno, text in enumerate(src.splitlines(), start=start):
        print(f"{lineno:04d}: {text}")


def is_result_block(node: ast.AST) -> bool:
    ids = names_in(node)
    calls = {x.lower() for x in function_calls(node)}
    return bool((ids | calls) & RESULT_TERMS)


def structural_mode(tree: ast.Module, lines: list[str]) -> None:
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    print("Frozen structural helper inventory:")
    for fn in funcs:
        if fn.name in STRUCTURAL_FUNCTIONS:
            print(
                f"  {fn.name:<42} lines={fn.lineno}-{getattr(fn, 'end_lineno', fn.lineno)} "
                f"calls={','.join(sorted(function_calls(fn))) or 'NONE'}"
            )

    print()
    print("Top-level structural block map (AST-only; nothing executed):")
    structural_nodes: list[tuple[int, ast.AST, set[str], set[str]]] = []
    for idx, node in enumerate(tree.body):
        stores = assigned_names(node)
        relevant_stores = stores & STRUCTURAL_ASSIGNMENTS
        ids = names_in(node)
        relevant_terms = {t for t in STATE_TERMS if t in ids}
        if relevant_stores or len(relevant_terms) >= 3:
            print(
                f"  node={idx:03d} type={type(node).__name__:<12} "
                f"lines={getattr(node,'lineno',-1)}-{getattr(node,'end_lineno',-1)} "
                f"stores={','.join(sorted(relevant_stores)) or '-'} "
                f"terms={','.join(sorted(relevant_terms)) or '-'}"
            )
            structural_nodes.append((idx, node, relevant_stores, relevant_terms))

    print()
    print("Exact structural helper source (review only; not executed):")
    for fn in funcs:
        if fn.name in STRUCTURAL_FUNCTIONS:
            print_source_block(f"FUNCTION {fn.name}", lines, fn)

    print()
    print("Exact top-level construction source for frozen state objects:")
    printed = 0
    for idx, node, stores, terms in structural_nodes:
        if stores or len(terms) >= 5:
            print_source_block(
                f"TOPLEVEL node={idx:03d} stores={','.join(sorted(stores)) or '-'}",
                lines,
                node,
            )
            printed += 1

    print()
    print(f"STRUCTURAL_BLOCKS_PRINTED = {printed}")
    print("EXP27_STATE_BUILDER_PROBE_STATUS = PASS_NOEXEC")


def decision_mode(tree: ast.Module, lines: list[str]) -> None:
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    print("Decision01 frozen-model helper inventory (AST-only):")
    for fn in funcs:
        if fn.name in DECISION_FUNCTIONS:
            print(
                f"  {fn.name:<42} lines={fn.lineno}-{getattr(fn, 'end_lineno', fn.lineno)} "
                f"calls={','.join(sorted(function_calls(fn))) or 'NONE'}"
            )

    print()
    print("Decision-relevant top-level assignment map:")
    candidates: list[tuple[int, ast.AST, set[str], set[str], set[str]]] = []
    for idx, node in enumerate(tree.body):
        if getattr(node, "lineno", 0) < 600:
            continue
        stores = assigned_names(node)
        ids = names_in(node)
        calls = {x.lower() for x in function_calls(node)}
        matched = {
            term for term in DECISION_TERMS
            if term in ids or term in calls or any(term in s.lower() for s in stores)
        }
        if matched:
            blocked = is_result_block(node)
            print(
                f"  node={idx:03d} type={type(node).__name__:<12} "
                f"lines={getattr(node,'lineno',-1)}-{getattr(node,'end_lineno',-1)} "
                f"stores={','.join(sorted(stores)) or '-'} "
                f"matched={','.join(sorted(matched))} "
                f"result_guard={'BLOCK' if blocked else 'CLEAR'}"
            )
            if not blocked:
                candidates.append((idx, node, stores, matched, calls))

    print()
    print("Exact frozen model/prediction helper source (review only; not executed):")
    for fn in funcs:
        if fn.name in DECISION_FUNCTIONS:
            print_source_block(f"FUNCTION {fn.name}", lines, fn)

    print()
    print("Exact non-result top-level model/prediction blocks:")
    printed = 0
    for idx, node, stores, matched, calls in candidates:
        # Keep the dump focused on model construction and deterministic prediction.
        if not stores:
            continue
        if not (
            any(k in s.lower() for s in stores for k in ("base", "position", "pred", "cif", "hazard", "cell", "theta", "coef", "beta"))
            or "predict_exit_cumulative" in calls
            or "cell_prediction_from_state" in calls
        ):
            continue
        print_source_block(
            f"TOPLEVEL node={idx:03d} stores={','.join(sorted(stores))}",
            lines,
            node,
        )
        printed += 1

    print()
    print(f"DECISION_MODEL_BLOCKS_PRINTED = {printed}")
    print("RESULT_BEARING_BLOCKS          = BLOCKED_FROM_SOURCE_DUMP")
    print("DECISION01_MODEL_SOURCE_PROBE_STATUS = PASS_NOEXEC")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--decision",
        action="store_true",
        help="Inspect frozen BASE/POSITION survival-model source needed by Decision01.",
    )
    args = parser.parse_args()

    print("=" * 132)
    print("FROZEN EXP49 SOURCE PROBE — NO EXECUTION / NO SCORE")
    print("=" * 132)
    print("Decoded runner execution = PROHIBITED")
    print("Exp27 outcomes/scores     = PROHIBITED / UNTOUCHED")
    print(f"Mode                      = {'DECISION01_MODEL_SOURCE' if args.decision else 'STRUCTURAL_STATE_SOURCE'}")
    print()

    if not LAUNCHER.exists():
        raise FileNotFoundError(f"Missing launcher: {LAUNCHER}")

    payload = extract_payload_literal(LAUNCHER)
    source = decode_payload(payload)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    tree = ast.parse(source, filename="<EXP49_DECODED_NOEXEC>")
    lines = source.splitlines()

    print(f"EXP49 decoded sha256       = {source_hash}")
    print(f"EXP49 decoded lines        = {len(lines)}")
    print()

    if args.decision:
        decision_mode(tree, lines)
    else:
        structural_mode(tree, lines)

    print()
    print("EXP27_SCORES = SEALED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
