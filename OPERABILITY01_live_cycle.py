#!/usr/bin/env python3
"""
OPERABILITY01 live cycle.

1) Refresh GOLD intraday data from MT5 using the existing Base_Dados.py.
2) Run the frozen OPERABILITY01 shadow classifier.

This wrapper does not score outcomes, does not touch Exp27 and does not promote
the operability gate to runtime enforcement.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def run(cmd: list[str]) -> int:
    print("$ " + subprocess.list2cmdline(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=ROOT)
    return int(proc.returncode)


def main() -> int:
    refresh = [
        sys.executable,
        str(ROOT / "Base_Dados.py"),
        "--mode",
        "intraday_refresh",
        "--symbol",
        "GOLD",
    ]
    rc = run(refresh)
    if rc != 0:
        print("OPERABILITY01_LIVE_CYCLE = ABORTED_BASE_DADOS_FAILED")
        return rc

    shadow = [
        sys.executable,
        str(ROOT / "OPERABILITY01_shadow_gate.py"),
    ]
    rc = run(shadow)
    if rc != 0:
        print("OPERABILITY01_LIVE_CYCLE = ABORTED_SHADOW_FAILED")
        return rc

    print("OPERABILITY01_LIVE_CYCLE = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
