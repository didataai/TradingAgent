#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Executa o Market Chronos Research sem sobrescrever o registry operacional.

O engine V10.1 grava o registry em ``<output>.parent/laws``. Este runner cria uma
pasta de staging exclusiva por execução e direciona ``--output`` para dentro
dela. Assim, o arquivo operacional
``data/market_chronos/<SYMBOL>/laws/market_laws_registry.json`` permanece intacto.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ENGINE = "tools/market_chronos_engine_v10_1.py"
DEFAULT_INPUT = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_STAGING_ROOT = "data/market_chronos/{symbol}/research_staging"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Market Chronos safe research runner")
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.add_argument("--engine", default=DEFAULT_ENGINE)
    p.add_argument("--input", default=DEFAULT_INPUT)
    p.add_argument("--staging-root", default=DEFAULT_STAGING_ROOT)
    p.add_argument("--run-id", default=None)
    p.add_argument("--min-bars", type=int, default=120)
    p.add_argument("--min-segment", type=int, default=120)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    symbol = args.symbol.upper()
    anchor_tf = args.anchor_tf.upper()
    run_id = args.run_id or utc_stamp()

    engine = root / args.engine
    input_path = root / args.input.format(symbol=symbol, anchor_tf=anchor_tf)
    staging_root = root / args.staging_root.format(symbol=symbol, anchor_tf=anchor_tf)
    run_root = staging_root / run_id
    engine_output = run_root / "engine"
    candidate_registry = run_root / "laws" / "market_laws_registry.json"
    manifest_path = run_root / "research_manifest.json"

    if not engine.exists():
        raise FileNotFoundError(f"Engine não encontrado: {engine}")
    if not input_path.exists():
        raise FileNotFoundError(f"Dataset MTF não encontrado: {input_path}")
    if run_root.exists():
        raise FileExistsError(f"Run já existe: {run_root}")

    engine_output.mkdir(parents=True, exist_ok=False)

    command = [
        sys.executable,
        str(engine),
        "--symbol", symbol,
        "--anchor-tf", anchor_tf,
        "--input", str(input_path),
        "--output", str(engine_output),
        "--min-bars", str(args.min_bars),
        "--min-segment", str(args.min_segment),
    ]

    started_at = datetime.now(timezone.utc).isoformat()
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True)
    finished_at = datetime.now(timezone.utc).isoformat()

    manifest = {
        "schema_version": "1.0",
        "mode": "RESEARCH_STAGING_ONLY",
        "run_id": run_id,
        "symbol": symbol,
        "anchor_tf": anchor_tf,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "command": command,
        "return_code": completed.returncode,
        "engine_output": str(engine_output),
        "candidate_registry": str(candidate_registry),
        "operational_registry_touched": False,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")

    if completed.returncode != 0:
        print(f"Research falhou. Manifest: {manifest_path}", file=sys.stderr)
        return completed.returncode
    if not candidate_registry.exists():
        print(f"Engine terminou, mas o registry candidato não foi encontrado: {candidate_registry}", file=sys.stderr)
        return 3

    print(json.dumps({
        "status": "ok",
        "mode": "RESEARCH_STAGING_ONLY",
        "run_id": run_id,
        "candidate_registry": str(candidate_registry),
        "manifest": str(manifest_path),
        "next_step": (
            f"python tools/market_chronos_registry_manager.py review "
            f"--symbol {symbol} --candidate '{candidate_registry}'"
        ),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
