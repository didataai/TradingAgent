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
- prints function inventory and candidate state-machine builders/dependencies;
- computes NO Brier, LogLoss, AUC, calibration, class residual or model gain;
- never reads Exp27 outcomes and never executes the decoded runner.
"""
from __future__ import annotations

import ast
import base64
import hashlib
from pathlib import Path
import sys
import zlib

ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "EXP49_symmetric_boundary_timing.py"

# Terms chosen only to locate the already-existing state construction.
# They are NOT new features, thresholds, targets or model parameters.
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
    decoded = zlib.decompress(raw).decode("utf-8")
    return decoded


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
            # Include identifier-like string literals used as dataframe columns.
            val = child.value.strip().lower()
            if val and len(val) <= 80:
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


def main() -> int:
    print("=" * 132)
    print("EXP27 — FROZEN STRUCTURAL STATE BUILDER PROBE")
    print("=" * 132)
    print("Decoded runner execution = PROHIBITED")
    print("Exp27 outcomes/scores     = PROHIBITED / UNTOUCHED")
    print("Purpose                   = locate exact historical state construction only")
    print()

    if not LAUNCHER.exists():
        raise FileNotFoundError(f"Missing launcher: {LAUNCHER}")

    payload = extract_payload_literal(LAUNCHER)
    source = decode_payload(payload)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    tree = ast.parse(source, filename="<EXP49_DECODED_NOEXEC>")
    lines = source.splitlines()

    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]

    print(f"EXP49 decoded sha256       = {source_hash}")
    print(f"EXP49 decoded lines        = {len(lines)}")
    print(f"Top-level functions        = {len(funcs)}")
    print(f"Top-level classes          = {len(classes)}")
    print()

    print("Top-level function inventory:")
    for fn in funcs:
        print(f"  {fn.name:<42} lines={fn.lineno}-{getattr(fn, 'end_lineno', fn.lineno)}")

    candidates: list[tuple[int, ast.FunctionDef | ast.AsyncFunctionDef, list[str]]] = []
    for fn in funcs:
        identifiers = names_in(fn)
        matched = sorted(term for term in STATE_TERMS if term in identifiers)
        # State-machine candidates should reference several frozen structural terms.
        if len(matched) >= 3:
            candidates.append((len(matched), fn, matched))

    candidates.sort(key=lambda x: (-x[0], x[1].lineno))

    print()
    print("Candidate state-machine functions (AST-only):")
    if not candidates:
        print("  NONE FOUND — inspect inventory manually; do not execute runner.")
    else:
        for score, fn, matched in candidates[:20]:
            calls = sorted(function_calls(fn))
            print(
                f"  {fn.name:<42} lines={fn.lineno}-{getattr(fn, 'end_lineno', fn.lineno)} "
                f"matched={score} terms={','.join(matched)}"
            )
            print(f"    calls={','.join(calls[:40]) if calls else 'NONE'}")

    # Show only signatures and literal column-like tokens for the strongest few.
    # Do not dump executable bodies or scoring code.
    print()
    print("Strongest candidate signatures / structural tokens:")
    for _, fn, matched in candidates[:8]:
        args = [a.arg for a in fn.args.args]
        print(
            f"  {fn.name}({', '.join(args)}) | lines={fn.lineno}-{getattr(fn, 'end_lineno', fn.lineno)}"
        )
        print(f"    structural_terms={','.join(matched)}")

    # Top-level assignments help identify names such as dyn/state frames without
    # evaluating their RHS expressions.
    assigned: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    low = name.lower()
                    if any(t in low for t in ("dyn", "state", "event", "swing", "touch", "split", "m5")):
                        assigned.append(name)

    print()
    print("Relevant top-level assigned names (not evaluated):")
    print("  " + (", ".join(dict.fromkeys(assigned)) if assigned else "NONE"))

    print()
    print("EXP27_STATE_BUILDER_PROBE_STATUS = PASS_NOEXEC")
    print("EXP27_SCORES = SEALED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
