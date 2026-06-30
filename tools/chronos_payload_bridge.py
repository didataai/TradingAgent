#!/usr/bin/env python3
"""Anexa a inteligência Chronos ao payload intraday sem quebrar o fluxo existente."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def compact_chronos(data: dict[str, Any], include_diagnostics: bool) -> dict[str, Any]:
    freshness = data.get("freshness") or {}
    stale = str(freshness.get("status", "UNKNOWN")).upper() == "STALE"

    result: dict[str, Any] = {
        "available": not stale,
        "freshness": freshness,
        "engine_version": data.get("engine_version"),
        "evaluated_at": data.get("evaluated_at"),
        "matched_count": data.get("matched_count", 0),
        "supporting_side": data.get("supporting_side", "NONE"),
        "buy_score": data.get("buy_score", 0.0),
        "sell_score": data.get("sell_score", 0.0),
        "blocked_actions": data.get("blocked_actions", []),
        "chronos_action": data.get("chronos_action", "NO_MATCH"),
        "confidence": data.get("confidence", "NONE"),
        "matched_laws": data.get("matched_laws", []),
        "current_segments": data.get("current_segments", {}),
        "guard_note": data.get("guard_note"),
    }

    if stale:
        result.update({
            "available": False,
            "reason": "STALE_DATA",
            "matched_count": 0,
            "supporting_side": "NONE",
            "buy_score": 0.0,
            "sell_score": 0.0,
            "blocked_actions": [],
            "chronos_action": "UNAVAILABLE_STALE",
            "confidence": "NONE",
            "matched_laws": [],
        })

    if include_diagnostics:
        result["law_diagnostics"] = data.get("law_diagnostics", [])
        result["diagnostic_summary"] = data.get("diagnostic_summary", {})

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Anexa Chronos ao payload intraday.")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--chronos", required=True)
    parser.add_argument("--output")
    parser.add_argument("--include-diagnostics", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload_path = Path(args.payload)
    chronos_path = Path(args.chronos)
    output_path = Path(args.output) if args.output else payload_path

    payload = read_json(payload_path)
    chronos = read_json(chronos_path)
    payload["chronos_intelligence"] = compact_chronos(
        chronos, include_diagnostics=args.include_diagnostics
    )
    write_json_atomic(output_path, payload)

    summary = payload["chronos_intelligence"]
    print(json.dumps({
        "output": str(output_path),
        "available": summary["available"],
        "freshness": summary.get("freshness", {}).get("status"),
        "matched_count": summary["matched_count"],
        "chronos_action": summary["chronos_action"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
