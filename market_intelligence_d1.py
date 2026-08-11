#!/usr/bin/env python3
"""D1 point-in-time runtime extension for the existing Market Intelligence engine.

The historical profile/build stays in market_intelligence.py. This wrapper is used
only by the intraday `enrich` step and adds a lookahead-safe D1 broker-day filter.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import market_intelligence as core

RUNTIME_VERSION = "1.0.0"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"JSON inválido: {path}")
    return data


def project_root() -> Path:
    return Path(__file__).resolve().parent


def default_rules_path(symbol: str) -> Path:
    return project_root() / "config" / "market_intelligence" / f"{symbol.upper()}_d1_intraday_rules.json"


def default_m5_path(symbol: str) -> Path:
    return project_root() / "data" / f"{symbol.upper()}_M5.parquet"


def time_in_window(value: pd.Timestamp, start: str, end: str) -> bool:
    if pd.isna(value):
        return False
    try:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
    except Exception:
        return True
    cur = value.hour * 60 + value.minute
    a = sh * 60 + sm
    b = eh * 60 + em
    return (a <= cur <= b) if a <= b else (cur >= a or cur <= b)


def broker_to_operational_time(ts: pd.Timestamp, broker_tz: str, operational_tz: str) -> pd.Timestamp:
    if pd.isna(ts):
        return pd.NaT
    value = pd.Timestamp(ts)
    try:
        if value.tzinfo is None:
            value = value.tz_localize(ZoneInfo(broker_tz))
        else:
            value = value.tz_convert(ZoneInfo(broker_tz))
        return value.tz_convert(ZoneInfo(operational_tz)).tz_localize(None)
    except Exception:
        return pd.NaT


def zone_for(position: float, daily_direction: str, rules: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    cfg = rules.get("daily_position_filter", {}) or {}
    for zone in cfg.get("zones", []):
        try:
            lo = float(zone.get("min"))
            hi = float(zone.get("max"))
        except (TypeError, ValueError):
            continue
        if not (lo <= position < hi):
            continue
        required = str(zone.get("required_daily_direction") or "").upper()
        return zone, (not required or required == daily_direction)
    return None, False


def build_daily_position_context(m5_path: Path, rules: dict[str, Any]) -> dict[str, Any]:
    base = {
        "available": False,
        "runtime_version": RUNTIME_VERSION,
        "source": "M5_POINT_IN_TIME_BROKER_DAY",
        "lookahead_safe": True,
        "reason": None,
    }
    if not m5_path.exists():
        return {**base, "reason": "M5_FILE_NOT_FOUND", "m5_path": str(m5_path)}

    try:
        df = pd.read_parquet(m5_path).copy()
    except Exception as exc:
        return {**base, "reason": f"M5_READ_FAILED:{type(exc).__name__}", "m5_path": str(m5_path)}

    if not {"open", "high", "low", "close"}.issubset(df.columns):
        return {**base, "reason": "M5_OHLC_MISSING", "m5_path": str(m5_path)}

    clock = rules.get("daily_session_clock", {}) or {}
    broker_col = next((c for c in clock.get("preferred_columns", ["time_broker", "time"]) if c in df.columns), None)
    if broker_col is None:
        return {**base, "reason": "BROKER_TIME_COLUMN_MISSING", "m5_path": str(m5_path)}

    broker_tz = str(clock.get("timezone") or "Etc/GMT-2")
    op = rules.get("operational_window_brt", {}) or {}
    op_tz = str(op.get("timezone") or "America/Sao_Paulo")

    df["_broker_time"] = pd.to_datetime(df[broker_col], errors="coerce")
    if "time_brt" in df.columns:
        df["_operational_time"] = pd.to_datetime(df["time_brt"], errors="coerce")
        op_source = "time_brt"
    else:
        df["_operational_time"] = df["_broker_time"].map(lambda x: broker_to_operational_time(x, broker_tz, op_tz))
        op_source = f"converted_from_{broker_col}"

    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["_broker_time", "open", "high", "low", "close"])
    df = df.sort_values("_broker_time").drop_duplicates("_broker_time", keep="last")
    if df.empty:
        return {**base, "reason": "M5_EMPTY_AFTER_CLEAN", "m5_path": str(m5_path)}

    latest = df.iloc[-1]
    broker_date = pd.Timestamp(latest["_broker_time"]).date()
    day = df.loc[df["_broker_time"].dt.date == broker_date]
    if day.empty:
        return {**base, "reason": "BROKER_DAY_EMPTY", "m5_path": str(m5_path)}

    daily_open = float(day.iloc[0]["open"])
    high_so_far = float(day["high"].max())
    low_so_far = float(day["low"].min())
    price = float(day.iloc[-1]["close"])
    daily_range = high_so_far - low_so_far
    position = (price - low_so_far) / daily_range if daily_range > 0 else 0.5
    position = float(max(0.0, min(1.0, position)))
    daily_direction = "BULLISH" if price > daily_open else "BEARISH" if price < daily_open else "NEUTRAL"

    operational_time = pd.Timestamp(latest["_operational_time"]) if not pd.isna(latest["_operational_time"]) else pd.NaT
    start = str(op.get("start") or "09:00")
    end = str(op.get("end") or "18:00")
    in_window = time_in_window(operational_time, start, end)
    zone, qualified = zone_for(position, daily_direction, rules)

    return {
        **base,
        "available": True,
        "reason": None,
        "m5_path": str(m5_path),
        "daily_session_clock": "BROKER",
        "broker_time_column": broker_col,
        "broker_timezone": broker_tz,
        "broker_date": str(broker_date),
        "event_time_broker": pd.Timestamp(latest["_broker_time"]).isoformat(),
        "operational_time_source": op_source,
        "event_time_brt": operational_time.isoformat() if not pd.isna(operational_time) else None,
        "operational_timezone": op_tz,
        "operational_window": {"start": start, "end": end},
        "in_operational_window": bool(in_window),
        "daily_open": daily_open,
        "high_so_far": high_so_far,
        "low_so_far": low_so_far,
        "price": price,
        "daily_range": daily_range,
        "d1_position": round(position, 6),
        "daily_direction": daily_direction,
        "raw_zone": zone.get("name") if zone else None,
        "zone": zone.get("name") if zone and qualified else None,
        "zone_qualified": bool(zone and qualified),
        "preferred_side": zone.get("preferred_side") if zone and qualified else None,
        "zone_action": zone.get("action") if zone and qualified else None,
        "enforcement_mode": (rules.get("daily_position_filter", {}) or {}).get("enforcement_mode"),
        "score_mode": (rules.get("daily_position_filter", {}) or {}).get("score_mode"),
    }


def evaluate_filter(context: dict[str, Any], rules: dict[str, Any] | None, side: str | None) -> dict[str, Any]:
    cfg = (rules or {}).get("daily_position_filter", {}) or {}
    result = {
        "available": False,
        "runtime_version": RUNTIME_VERSION,
        "side": side,
        "zone": context.get("zone"),
        "raw_zone": context.get("raw_zone"),
        "preferred_side": context.get("preferred_side"),
        "score_adjustment": 0,
        "hard_block": False,
        "warning": None,
        "enforcement_mode": cfg.get("enforcement_mode", "DISABLED"),
    }
    if not rules or not cfg.get("enabled"):
        result["reason"] = "RULES_DISABLED_OR_MISSING"
        return result
    if not context.get("available"):
        result["reason"] = context.get("reason") or "D1_CONTEXT_UNAVAILABLE"
        return result
    if cfg.get("apply_only_in_operational_window", True) and not context.get("in_operational_window"):
        result["reason"] = "OUTSIDE_OPERATIONAL_WINDOW"
        return result
    if side not in {"BUY", "SELL"}:
        result["reason"] = "NO_CANDIDATE_SIDE"
        return result

    try:
        position = float(context.get("d1_position"))
    except (TypeError, ValueError):
        result["reason"] = "INVALID_D1_POSITION"
        return result
    daily_direction = str(context.get("daily_direction") or "NEUTRAL").upper()
    zone, qualified = zone_for(position, daily_direction, rules)
    if zone is None:
        result["reason"] = "NO_ZONE"
        return result
    if not qualified:
        result.update({"available": True, "reason": "ZONE_DIRECTION_NOT_QUALIFIED", "d1_position": position, "daily_direction": daily_direction, "raw_zone": zone.get("name")})
        return result

    adjustments = zone.get("score_adjustment", {}) or {}
    result.update({
        "available": True,
        "reason": None,
        "d1_position": position,
        "daily_direction": daily_direction,
        "zone": zone.get("name"),
        "raw_zone": zone.get("name"),
        "preferred_side": zone.get("preferred_side"),
        "zone_action": zone.get("action"),
        "score_adjustment": int(adjustments.get(side, 0) or 0),
        "lookahead_safe": context.get("lookahead_safe"),
        "broker_date": context.get("broker_date"),
    })

    preferred = str(zone.get("preferred_side") or "NONE").upper()
    chase_side = str(zone.get("same_direction_chase_side") or "NONE").upper()
    conflict = preferred in {"BUY", "SELL"} and side != preferred
    chase = chase_side in {"BUY", "SELL"} and side == chase_side
    if conflict:
        result["warning"] = f"D1_{zone.get('name')}_COUNTER_{side}"
    elif chase:
        result["warning"] = f"D1_{zone.get('name')}_AVOID_CHASE_{side}"

    if str(cfg.get("enforcement_mode") or "WARNING_ONLY").upper() == "HARD_FILTER":
        if conflict and bool(zone.get("hard_block_opposite_side_when_promoted")):
            result["hard_block"] = True
        if chase and bool(zone.get("hard_block_same_direction_chase_when_promoted")):
            result["hard_block"] = True
    return result


def apply_d1_extension(out: dict[str, Any], rules: dict[str, Any] | None) -> dict[str, Any]:
    hi = out.get("historical_intelligence", {}) or {}
    formal = hi.get("formal_mtf_decision", {}) or {}
    m15d = formal.get("m15_setup_direction")
    side = "BUY" if m15d == "UP" else "SELL" if m15d == "DOWN" else None
    context = out.get("daily_position_context", {}) or {}
    d1f = evaluate_filter(context, rules, side)

    score = int(formal.get("alignment_score") or 0)
    score = int(max(0, min(100, score + int(d1f.get("score_adjustment") or 0))))
    formal["alignment_score"] = score
    formal["d1_position_filter"] = d1f

    warnings = list(formal.get("warning_reasons") or [])
    blocked = list(formal.get("blocked_reasons") or [])
    if d1f.get("warning") and d1f["warning"] not in warnings:
        warnings.append(d1f["warning"])
    if d1f.get("hard_block"):
        reason = str(d1f.get("warning") or "D1_POSITION_HARD_FILTER")
        if reason not in blocked:
            blocked.append(reason)
        formal["final_action"] = "WAIT"
        hi["preferred_action_now"] = "WAIT"

    formal["warning_reasons"] = warnings
    formal["blocked_reasons"] = blocked
    hi["formal_mtf_decision"] = formal

    brief = hi.get("llm_quantitative_brief", {}) or {}
    priority = list(brief.get("priority") or [])
    if "D1_POSITION_FILTER" not in priority:
        priority.insert(0, "D1_POSITION_FILTER")
    brief["priority"] = priority
    brief["daily_position_context"] = context
    brief["d1_filter_runtime_version"] = RUNTIME_VERSION
    brief["instruction"] = "Use como restrição quantitativa; D1 é point-in-time no dia do broker, permanece WARNING_ONLY até validação OOS e não substitui gatilho técnico."
    brief["formal_decision"] = formal
    brief["final_action"] = formal.get("final_action")
    hi["llm_quantitative_brief"] = brief
    out["historical_intelligence"] = hi
    return out


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Market Intelligence enrich + D1 point-in-time extension")
    p.add_argument("command", choices=["enrich"])
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--payload", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--d1-rules", type=Path, default=None)
    p.add_argument("--d1-m5", type=Path, default=None)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        profile = core.load_json(args.profile)
        payload = core.load_json(args.payload)
        symbol = str(profile.get("symbol") or "GOLD").upper()
        rules_path = args.d1_rules or default_rules_path(symbol)
        m5_path = args.d1_m5 or default_m5_path(symbol)
        rules = load_json(rules_path) if rules_path.exists() else None

        if rules:
            payload["daily_position_context"] = build_daily_position_context(m5_path, rules)
        else:
            payload["daily_position_context"] = {
                "available": False,
                "runtime_version": RUNTIME_VERSION,
                "reason": "D1_RULES_NOT_FOUND",
                "rules_path": str(rules_path),
            }

        out = core.evaluate(payload, profile)
        out = apply_d1_extension(out, rules)
        core.save_json(args.output, out)
        ctx = out.get("daily_position_context", {}) or {}
        print(json.dumps({
            "status": "ok",
            "output": str(args.output),
            "preferred_action_now": out.get("historical_intelligence", {}).get("preferred_action_now"),
            "d1_filter": {
                "available": ctx.get("available"),
                "position": ctx.get("d1_position"),
                "zone": ctx.get("zone"),
                "raw_zone": ctx.get("raw_zone"),
                "daily_direction": ctx.get("daily_direction"),
                "broker_date": ctx.get("broker_date"),
                "in_operational_window": ctx.get("in_operational_window"),
            },
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
