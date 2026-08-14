#!/usr/bin/env python3
"""EXP27 state-builder probe — NO SCORE / NO PAYLOAD EXECUTION.

Purpose
-------
Inspect the exact embedded historical runner source used by EXP49 without
executing it, so the prospective EXP27 maturity counter can reuse the validated
structural-state construction rather than reimplementing it approximately.

This script:
- reads EXP49_symmetric_boundary_timing.py as text;
- extracts the literal _PAYLOAD via AST (no import / no exec);
- base64+zlib decodes it;
- parses the decoded Python source with AST only;
- inventories the exact structural helper functions;
- locates top-level blocks that construct events/touches/dynamic states;
- prints those structural source blocks for engineering review only;
- computes NO Brier, LogLoss, AUC, calibration, class residual or model gain;
- never reads Exp27 outcomes and never executes the decoded runner.
"""
from __future__ import annotations

import ast
import base64
import hashlib
from pathlib import Path
import zlib

ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "EXP49_symmetric_boundary_timing.py"

STATE_TERMS = {
    "state_time",
    "episode_id",
    "bias_sign",
    "back",
    "forward",
    "corridor",
    "swing",
    "l1",
    "l2",
    "outside_15",
    "dynamic",
    "advance",
    "recapture",
    "stay",
    "dedup",
    "active",
    "frontier",
}

STRUCTURAL_FUNCTIONS = {
    "load_tf",
    "build_structure",
    "choose_l1",
    "first_above",
    "first_below",
    "select_nearest_active",
}

STRUCTURAL_ASSIGNMENTS = {
    "events",
    "n_events",
    "m5q",
    "touch_rows",
    "touches",
    "raw_touches",
    "unique_touches",
    "dyn_raw",
    "raw_dynamic",
    "dyn",
    "train_states",
}

# Once any of these model/scoring names appear in a top-level node, that node is
# not printed as state-construction source. This is a conservative no-score guard.
SCORE_TERMS = {
    "state_exit_predictions",
    "brier",
    "logloss",
    "log_loss",
    "auc",
    "bootstrap",
    "predict_exit_cumulative",
    "fit_binary_logit",
    "binary_row_loss",
    "multiclass_row_loss",
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
            if val and len(val) <= 100:
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


def has_score_term(node: ast.AST) -> bool:
    ids = names_in(node)
    return any(term in ids for term in SCORE_TERMS)


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


def main() -> int:
    print("=" * 132)
    print("EXP27 — FROZEN STRUCTURAL STATE BUILDER PROBE v2")
    print("=" * 132)
    print("Decoded runner execution = PROHIBITED")
    print("Exp27 outcomes/scores     = PROHIBITED / UNTOUCHED")
    print("Purpose                   = extract exact historical state construction only")
    print()

    if not LAUNCHER.exists():
        raise FileNotFoundError(f"Missing launcher: {LAUNCHER}")

    payload = extract_payload_literal(LAUNCHER)
    source = decode_payload(payload)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    tree = ast.parse(source, filename="<EXP49_DECODED_NOEXEC>")
    lines = source.splitlines()

    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    print(f"EXP49 decoded sha256       = {source_hash}")
    print(f"EXP49 decoded lines        = {len(lines)}")
    print(f"Top-level functions        = {len(funcs)}")
    print()

    print("Frozen structural helper inventory:")
    found_helpers = set()
    for fn in funcs:
        if fn.name in STRUCTURAL_FUNCTIONS:
            found_helpers.add(fn.name)
            print(
                f"  {fn.name:<42} lines={fn.lineno}-{getattr(fn, 'end_lineno', fn.lineno)} "
                f"calls={','.join(sorted(function_calls(fn))) or 'NONE'}"
            )
    missing_helpers = sorted(STRUCTURAL_FUNCTIONS - found_helpers)
    if missing_helpers:
        print(f"  MISSING_EXPECTED_HELPERS = {missing_helpers}")

    print()
    print("Top-level structural block map (AST-only; nothing executed):")
    structural_nodes: list[tuple[int, ast.AST, set[str], set[str]]] = []
    for idx, node in enumerate(tree.body):
        stores = assigned_names(node)
        relevant_stores = stores & STRUCTURAL_ASSIGNMENTS
        ids = names_in(node)
        relevant_terms = {t for t in STATE_TERMS if t in ids}
        if relevant_stores or len(relevant_terms) >= 3:
            score_guard = has_score_term(node)
            print(
                f"  node={idx:03d} type={type(node).__name__:<12} "
                f"lines={getattr(node,'lineno',-1)}-{getattr(node,'end_lineno',-1)} "
                f"stores={','.join(sorted(relevant_stores)) or '-'} "
                f"terms={','.join(sorted(relevant_terms)) or '-'} "
                f"score_guard={'BLOCK' if score_guard else 'CLEAR'}"
            )
            if not score_guard:
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
        # Print nodes that directly create/transform the known state objects or
        # that carry enough structural vocabulary to be necessary context.
        if stores or len(terms) >= 5:
            print_source_block(
                f"TOPLEVEL node={idx:03d} stores={','.join(sorted(stores)) or '-'}",
                lines,
                node,
            )
            printed += 1

    print()
    print(f"STRUCTURAL_BLOCKS_PRINTED = {printed}")
    print("SCORE_BEARING_BLOCKS       = BLOCKED_FROM_SOURCE_DUMP")
    print("EXP27_STATE_BUILDER_PROBE_STATUS = PASS_NOEXEC")
    print("EXP27_SCORES = SEALED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
