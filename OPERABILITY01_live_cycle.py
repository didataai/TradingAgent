#!/usr/bin/env python3
"""
OPERABILITY01 live cycle.

1) Verify the frozen historical threshold reference.
2) Refresh GOLD intraday data from MT5 using the existing Base_Dados.py.
3) Run the frozen OPERABILITY01 shadow classifier.
4) Run the descriptive shadow monitor (no outcomes, no Exp27 scores).
5) Update the sealed Exp27 maturity ledger after exact historical state guards.
6) Update the sealed Decision Calibration shadow readiness ledger.

This wrapper never computes Exp27 or Decision Calibration scores and never
promotes the operability gate or Track-D models to runtime enforcement.
Exp27 work here is maturity counting only; score opening remains governed by
the frozen 60-day AND 1500-state gate. Decision Calibration work is also
readiness-only; score opening remains governed by the frozen 60-day AND
1000-resolved-EXIT-cell gate starting 2026-08-18 00:00 BRT.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import OPERABILITY01_shadow_gate as gate

EXPECTED_THRESHOLD_6DP = {
    "RANGE_ATR": (2.431744, 2.824153),
    "ABS_RET_ATR": (1.851113, 2.154342),
    "GAP_ATR": (0.086353, 0.109370),
}


def run(cmd: list[str]) -> int:
    print("$ " + subprocess.list2cmdline(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=ROOT)
    return int(proc.returncode)


def verify_frozen_reference() -> None:
    rules = gate.load_json(gate.RULES_PATH)
    reference_path = gate.find_reference_m5_parquet()
    reference = gate.prepare_operability_m5(reference_path, rules)
    thresholds = gate.compute_thresholds(reference, rules)

    for metric, (exp_ca, exp_nt) in EXPECTED_THRESHOLD_6DP.items():
        got_ca = float(thresholds[metric]["q_caution"])
        got_nt = float(thresholds[metric]["q_no_trade"])
        if round(got_ca, 6) != exp_ca or round(got_nt, 6) != exp_nt:
            raise RuntimeError(
                f"Frozen threshold guard failed for {metric}: "
                f"got ({got_ca:.6f}, {got_nt:.6f}), "
                f"expected ({exp_ca:.6f}, {exp_nt:.6f})."
            )

    print("OPERABILITY01_FROZEN_REFERENCE_GUARD = PASS")


def main() -> int:
    try:
        verify_frozen_reference()
    except Exception as exc:
        print(f"OPERABILITY01_LIVE_CYCLE = ABORTED_REFERENCE_GUARD | {type(exc).__name__}: {exc}")
        return 2

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

    shadow = [sys.executable, str(ROOT / "OPERABILITY01_shadow_gate.py")]
    rc = run(shadow)
    if rc != 0:
        print("OPERABILITY01_LIVE_CYCLE = ABORTED_SHADOW_FAILED")
        return rc

    monitor = [sys.executable, str(ROOT / "OPERABILITY01_monitor.py")]
    rc = run(monitor)
    if rc != 0:
        print("OPERABILITY01_LIVE_CYCLE = ABORTED_MONITOR_FAILED")
        return rc

    readiness = [sys.executable, str(ROOT / "EXP27_readiness_counter.py")]
    rc = run(readiness)
    if rc != 0:
        print("OPERABILITY01_LIVE_CYCLE = ABORTED_EXP27_READINESS_FAILED")
        return rc

    calibration = [sys.executable, str(ROOT / "DECISION_calibration_shadow.py")]
    rc = run(calibration)
    if rc != 0:
        print("OPERABILITY01_LIVE_CYCLE = ABORTED_DECISION_CALIBRATION_FAILED")
        return rc

    print("OPERABILITY01_LIVE_CYCLE = PASS")
    print("EXP27_SCORE_OPENING = GOVERNED_BY_FROZEN_MATURITY_GATE")
    print("DECISION_CALIBRATION_SCORE_OPENING = GOVERNED_BY_FROZEN_MATURITY_GATE")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
