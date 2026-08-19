#!/usr/bin/env python3
"""Daily orchestration for frozen microstructure prospective experiments.

Engineering wrapper only. It does not implement, alter, or inspect any frozen
scientific score. It delegates collection/scoring to the frozen Map02/Map04/
Shadow01 scripts and preserves each experiment's own maturity guards.

Default collection day = previous BRT calendar day.
Before the frozen fresh start (2026-08-19), collection is skipped and only
sealed progress checks are run where possible.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import MICROSTRUCTURE_flow_mark_map as fm

FRESH_START = datetime(2026, 8, 19).date()
ROOT = Path(__file__).resolve().parent
MAP02_LEDGER = fm.OUT_DIR / "FLOWMARK_map02_prospective_passes.csv.gz"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run frozen microstructure prospective daily cycle")
    p.add_argument("--day", default=None, help="Completed BRT day YYYY-MM-DD; default=previous BRT day")
    p.add_argument("--symbol", default=fm.SYMBOL_DEFAULT)
    return p.parse_args()


def run_step(label: str, args: list[str], required: bool = True) -> int:
    print()
    print("=" * 120)
    print(label)
    print("=" * 120)
    print("COMMAND = " + " ".join(args))
    cp = subprocess.run(args, cwd=ROOT)
    if cp.returncode != 0 and required:
        raise SystemExit(f"DAILY CYCLE ABORT: {label} returned {cp.returncode}")
    return cp.returncode


def main() -> int:
    args = parse_args()
    today_brt = datetime.now(fm.BRT).date()
    day = (
        datetime.strptime(args.day, "%Y-%m-%d").date()
        if args.day
        else today_brt - timedelta(days=1)
    )

    print("=" * 120)
    print("MICROSTRUCTURE PROSPECTIVE DAILY — ENGINEERING ORCHESTRATOR")
    print("=" * 120)
    print(f"today_brt         = {today_brt}")
    print(f"requested_day     = {day}")
    print(f"fresh_start       = {FRESH_START}")
    print(f"symbol            = {args.symbol}")
    print("scientific logic  = UNCHANGED / delegated to frozen scripts")
    print("runtime promotion = NONE")

    if day >= today_brt:
        raise SystemExit(
            f"GUARD FAIL: {day} is not a completed BRT day; latest allowed is {today_brt - timedelta(days=1)}"
        )

    py = sys.executable

    if day < FRESH_START:
        print()
        print("COLLECTION = SKIPPED")
        print(f"reason     = requested completed day {day} is before fresh start {FRESH_START}")
    else:
        run_step(
            "MAP02 — COLLECT COMPLETED DAY",
            [py, str(ROOT / "MICROSTRUCTURE_quote_migration_shadow.py"), "--symbol", args.symbol, "--day", day.isoformat()],
        )
        run_step(
            "MAP04 — COLLECT COMPLETED DAY",
            [py, str(ROOT / "MICROSTRUCTURE_quote_counterflow_map04.py"), "--mode", "collect", "--symbol", args.symbol, "--day", day.isoformat()],
        )

    # Map02 scorer requires an input ledger. Until the first fresh day exists,
    # report the absence rather than fabricating an empty input file.
    if MAP02_LEDGER.exists() and MAP02_LEDGER.stat().st_size > 0:
        run_step(
            "MAP02 — SEALED PROSPECTIVE PROGRESS / SCORE WHEN MATURE",
            [py, str(ROOT / "MICROSTRUCTURE_quote_migration_map02.py"), "--mode", "prospective", "--input", str(MAP02_LEDGER)],
        )
    else:
        print()
        print("=" * 120)
        print("MAP02 — SEALED PROSPECTIVE PROGRESS")
        print("=" * 120)
        print("days_progress   = 0/20")
        print("event_progress  = 0/200000")
        print("MAP02_PROSPECTIVE_STATUS = ACCUMULATING")
        print("PRIMARY_SCORES = SEALED")
        print("reason = prospective ledger does not exist yet")

    run_step(
        "MAP04 — SEALED PROSPECTIVE PROGRESS / SCORE WHEN MATURE",
        [py, str(ROOT / "MICROSTRUCTURE_quote_counterflow_map04.py"), "--mode", "score"],
    )
    run_step(
        "SHADOW01 — SEALED PROSPECTIVE VALIDATION PROGRESS / SCORE WHEN MATURE",
        [py, str(ROOT / "MICROSTRUCTURE_microflow_shadow01_validation.py")],
    )

    print()
    print("=" * 120)
    print("DAILY CYCLE COMPLETE")
    print("=" * 120)
    print(f"completed_day = {day}")
    print("frozen scientific contracts = UNCHANGED")
    print("runtime promotion = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
