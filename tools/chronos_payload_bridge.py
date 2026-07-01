#!/usr/bin/env python3
"""Anexa a inteligência Chronos e a qualidade do rompimento ao payload intraday."""
from __future__ import annotations

import argparse
import json
import math
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


def as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalized(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def semantic_vote(value: Any) -> int:
    text = normalized(value)
    negative = (
        "VERY_LOW", "LOW", "WEAK", "COMPRESSION", "MISALIGNED",
        "CONFLICT", "UNFAVORABLE", "OPPOSITE",
    )
    positive = (
        "VERY_HIGH", "HIGH", "STRONG", "EXPANSION", "ALIGNED",
        "FAVORABLE", "CONFIRMED", "ABOVE", "BULLISH", "BEARISH",
    )
    if any(token in text for token in negative):
        return -1
    if any(token in text for token in positive):
        return 1
    return 0


def combine_votes(*votes: int) -> int:
    total = sum(votes)
    return 1 if total > 0 else -1 if total < 0 else 0


def family_label(value: int, known: bool = True) -> str:
    if not known:
        return "UNKNOWN"
    return "ALIGNED" if value > 0 else "CONFLICTING" if value < 0 else "NEUTRAL"


def infer_breakout_side(state: dict[str, Any], chronos: dict[str, Any]) -> str:
    if bool(state.get("event_breakout_up")):
        return "UP"
    if bool(state.get("event_breakout_down")):
        return "DOWN"
    side = normalized(state.get("level_attempt_side"))
    if side in {"UP", "BUY", "LONG"}:
        return "UP"
    if side in {"DOWN", "SELL", "SHORT"}:
        return "DOWN"
    supporting = normalized(chronos.get("supporting_side"))
    return "UP" if supporting == "BUY" else "DOWN" if supporting == "SELL" else "NONE"


def directional_vote(value: Any, side: str) -> tuple[int, bool]:
    text = normalized(value)
    if not text or text in {"NONE", "UNKNOWN", "NEUTRAL", "NO_BREAKOUT"}:
        return 0, False
    bullish = any(token in text for token in ("UP", "BUY", "LONG", "BULL"))
    bearish = any(token in text for token in ("DOWN", "SELL", "SHORT", "BEAR"))
    if side == "UP":
        return (1 if bullish else -1 if bearish else semantic_vote(text)), True
    if side == "DOWN":
        return (1 if bearish else -1 if bullish else semantic_vote(text)), True
    return 0, False


def build_breakout_quality(state_payload: dict[str, Any], chronos: dict[str, Any]) -> dict[str, Any]:
    state = state_payload.get("chronos_state") or {}
    side = infer_breakout_side(state, chronos)
    applicable = side in {"UP", "DOWN"}

    displacement = combine_votes(
        semantic_vote(state.get("anchor_body_bucket")),
        semantic_vote(state.get("anchor_range_bucket")),
    )
    displacement_known = any(
        state.get(key) is not None for key in ("anchor_body_bucket", "anchor_range_bucket")
    )

    vol_ratio = as_float(state.get("anchor_vol_ratio"))
    ratio_vote = (
        1 if vol_ratio is not None and vol_ratio >= 1.5
        else -1 if vol_ratio is not None and vol_ratio < 0.8
        else 0
    )
    participation = combine_votes(ratio_vote, semantic_vote(state.get("anchor_vol_bucket")))
    participation_known = vol_ratio is not None or state.get("anchor_vol_bucket") is not None

    direction_vote, direction_known = directional_vote(state.get("anchor_direction"), side)
    breakout_vote = int(
        applicable and (
            (side == "UP" and bool(state.get("event_breakout_up")))
            or (side == "DOWN" and bool(state.get("event_breakout_down")))
        )
    )
    momentum = combine_votes(direction_vote, breakout_vote)
    momentum_known = direction_known or breakout_vote != 0

    alignment_vote, alignment_known = directional_vote(
        state.get("breakout_location_alignment"), side
    )
    htf_vote, htf_known = directional_vote(state.get("htf_location_bias"), side)
    location = combine_votes(alignment_vote, htf_vote)
    location_known = alignment_known or htf_known

    mtf_vote, mtf_known = directional_vote(state.get("mtf_bias"), side)
    trend = combine_votes(mtf_vote, semantic_vote(state.get("mtf_alignment_bucket")))
    trend_known = mtf_known or state.get("mtf_alignment_bucket") is not None

    families = {
        "displacement": {
            "score": displacement,
            "status": family_label(displacement, displacement_known),
        },
        "participation": {
            "score": participation,
            "status": family_label(participation, participation_known),
        },
        "momentum": {
            "score": momentum,
            "status": family_label(momentum, momentum_known),
        },
        "location": {
            "score": location,
            "status": family_label(location, location_known),
        },
        "trend": {
            "score": trend,
            "status": family_label(trend, trend_known),
        },
    }
    score = sum(item["score"] for item in families.values()) if applicable else 0
    band = "PREMIUM" if score >= 4 else "VALID" if score >= 2 else "LOW"
    known_families = sum(item["status"] != "UNKNOWN" for item in families.values())

    return {
        "available": applicable and known_families >= 3,
        "applicable": applicable,
        "side": side,
        "breakout_quality_score": score,
        "score_max": 5,
        "operational_band": band,
        "known_families": known_families,
        "families": families,
        "score_displacement": displacement,
        "score_participation": participation,
        "score_momentum": momentum,
        "score_location": location,
        "score_trend": trend,
        "method": "chronos_runtime_state_mapping_v1",
        "note": (
            f"Breakout Quality: {score}/5 | Classification: {band}"
            if applicable
            else "Breakout Quality: not applicable; no active breakout side."
        ),
    }


def compact_chronos(
    data: dict[str, Any],
    include_diagnostics: bool,
    state_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    freshness = data.get("freshness") or {}
    stale = normalized(freshness.get("status")) == "STALE"

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

    if state_payload is not None:
        quality = build_breakout_quality(state_payload, data)
        result["breakout_quality"] = quality
        result.update({
            "breakout_quality_score": quality["breakout_quality_score"],
            "operational_band": quality["operational_band"],
            "score_displacement": quality["score_displacement"],
            "score_participation": quality["score_participation"],
            "score_momentum": quality["score_momentum"],
            "score_location": quality["score_location"],
            "score_trend": quality["score_trend"],
        })

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
            "operational_band": "UNAVAILABLE",
        })
        quality = result.get("breakout_quality")
        if quality:
            quality.update({
                "available": False,
                "reason": "STALE_DATA",
                "observed_score": quality.get("breakout_quality_score"),
                "observed_band": quality.get("operational_band"),
                "operational_band": "UNAVAILABLE",
                "note": "Breakout Quality unavailable: stale market data.",
            })

    if include_diagnostics:
        result["law_diagnostics"] = data.get("law_diagnostics", [])
        result["diagnostic_summary"] = data.get("diagnostic_summary", {})
    return result


def infer_state_path(chronos_path: Path) -> Path:
    return chronos_path.with_name(
        chronos_path.name.replace("_chronos_intelligence.json", "_chronos_state.json")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Anexa Chronos ao payload intraday.")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--chronos", required=True)
    parser.add_argument("--state")
    parser.add_argument("--output")
    parser.add_argument("--include-diagnostics", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload_path = Path(args.payload)
    chronos_path = Path(args.chronos)
    state_path = Path(args.state) if args.state else infer_state_path(chronos_path)
    output_path = Path(args.output) if args.output else payload_path

    payload = read_json(payload_path)
    chronos = read_json(chronos_path)
    state_payload = read_json(state_path) if state_path.exists() else None
    payload["chronos_intelligence"] = compact_chronos(
        chronos,
        include_diagnostics=args.include_diagnostics,
        state_payload=state_payload,
    )
    write_json_atomic(output_path, payload)

    summary = payload["chronos_intelligence"]
    quality = summary.get("breakout_quality") or {}
    print(json.dumps({
        "output": str(output_path),
        "available": summary["available"],
        "freshness": summary.get("freshness", {}).get("status"),
        "matched_count": summary["matched_count"],
        "chronos_action": summary["chronos_action"],
        "breakout_quality_score": quality.get("breakout_quality_score"),
        "operational_band": quality.get("operational_band"),
        "observed_score": quality.get("observed_score"),
        "observed_band": quality.get("observed_band"),
        "breakout_side": quality.get("side"),
        "known_families": quality.get("known_families"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
