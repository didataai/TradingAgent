#!/usr/bin/env python3
"""
OPERABILITY01 — Prospective GOLD Market Operability Shadow Gate

This is NOT Exp54 timing-feature research and it never rescues Exp48–Exp53.
It calibrates only causal shock thresholds on the frozen TRAIN reference
and classifies only fresh-forward rows >= 2026-08-13 00:00 BRT.

Outputs:
    TRADEABLE / CAUTION / NO_TRADE
for NEW ENTRIES only. Risk-management actions remain allowed.

No future outcome, no PnL, no EXIT label and no Exp27 score is read.
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.study_d1_mtf_filter import load_json, prepare, in_window

RULES_PATH = ROOT / "config" / "market_intelligence" / "GOLD_d1_intraday_rules.json"
TF_DIR = ROOT / "data" / "market_chronos" / "candle_base" / "timeframes"
EVENTS_PATH = ROOT / "config" / "market_intelligence" / "GOLD_operability_events.csv"
OUT_DIR = ROOT / "data" / "market_chronos" / "operability"
OUT_PATH = OUT_DIR / "GOLD_operability_shadow.csv"

TRAIN_END = pd.Timestamp("2026-01-09 12:50:00")
FRESH_START = pd.Timestamp("2026-08-13 00:00:00")

Q_CAUTION = 0.990
Q_NO_TRADE = 0.995

FRIDAY_CAUTION_MINUTES_TO_END = 60
FRIDAY_NO_TRADE_MINUTES_TO_END = 30

HIGH_EVENT_CAUTION_MINUTES = 30
HIGH_EVENT_NO_TRADE_MINUTES = 15

METRICS = ("RANGE_ATR", "ABS_RET_ATR", "GAP_ATR")


def find_m5_parquet() -> Path:
    preferred = [
        TF_DIR / "GOLD_M5.parquet",
        TF_DIR / "gold_m5.parquet",
    ]
    for p in preferred:
        if p.exists():
            return p
    if not TF_DIR.exists():
        raise FileNotFoundError(f"Timeframe directory not found: {TF_DIR}")
    cands = sorted(
        p for p in TF_DIR.glob("*.parquet")
        if "GOLD" in p.name.upper() and "M5" in p.name.upper()
    )
    if len(cands) == 1:
        return cands[0]
    raise RuntimeError(
        "Could not resolve a unique GOLD M5 parquet. "
        f"Candidates={[p.name for p in cands]}"
    )


def parse_hhmm(s: str) -> int:
    h, m = map(int, s.split(":"))
    return h * 60 + m


def load_scheduled_high_events() -> pd.DataFrame:
    if not EVENTS_PATH.exists():
        return pd.DataFrame(columns=["event_time_brt", "impact", "label"])
    e = pd.read_csv(EVENTS_PATH)
    need = {"event_time_brt", "impact", "label"}
    miss = sorted(need - set(e.columns))
    if miss:
        raise RuntimeError(
            f"{EVENTS_PATH.name}: missing columns {miss}; required={sorted(need)}"
        )
    e = e.copy()
    e["event_time_brt"] = pd.to_datetime(e["event_time_brt"], errors="coerce")
    e["impact"] = e["impact"].astype(str).str.upper().str.strip()
    e["label"] = e["label"].astype(str)
    e = e.dropna(subset=["event_time_brt"])
    e = e.loc[e["impact"].eq("HIGH")].sort_values("event_time_brt").reset_index(drop=True)
    return e


def nearest_event_distance_minutes(ts: pd.Series, events: pd.DataFrame) -> np.ndarray:
    if events.empty:
        return np.full(len(ts), np.inf, dtype=float)
    ev = events["event_time_brt"].to_numpy(dtype="datetime64[ns]")
    out = np.empty(len(ts), dtype=float)
    for i, t in enumerate(ts.to_numpy(dtype="datetime64[ns]")):
        out[i] = float(np.min(np.abs((ev - t) / np.timedelta64(1, "m"))))
    return out


def add_reason(reason_lists: list[list[str]], mask: np.ndarray, reason: str) -> None:
    idx = np.flatnonzero(mask)
    for i in idx:
        reason_lists[i].append(reason)


def main() -> None:
    rules = load_json(RULES_PATH)
    m5_path = find_m5_parquet()
    m = prepare(m5_path, "M5", rules).copy()

    required = {"available_at_brt", "open", "high", "low", "close", "ATR"}
    missing = sorted(required - set(m.columns))
    if missing:
        raise RuntimeError(
            f"OPERABILITY01 requires the frozen M5 causal fields {missing}. "
            "No ATR fallback is allowed because that would change the policy definition."
        )

    for c in ("open", "high", "low", "close", "ATR"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    m["available_at_brt"] = pd.to_datetime(m["available_at_brt"], errors="coerce")
    m = m.sort_values("available_at_brt").drop_duplicates("available_at_brt", keep="last").reset_index(drop=True)

    prev_close = m["close"].shift(1)
    m["M5_DELTA_MIN"] = m["available_at_brt"].diff().dt.total_seconds().div(60.0)
    atr = m["ATR"].to_numpy(float)
    valid_atr = np.isfinite(atr) & (atr > 0)

    m["RANGE_ATR"] = np.nan
    m["ABS_RET_ATR"] = np.nan
    m["GAP_ATR"] = np.nan
    m.loc[valid_atr, "RANGE_ATR"] = (
        (m.loc[valid_atr, "high"] - m.loc[valid_atr, "low"]).to_numpy(float)
        / atr[valid_atr]
    )
    m.loc[valid_atr, "ABS_RET_ATR"] = (
        (m.loc[valid_atr, "close"] - prev_close.loc[valid_atr]).abs().to_numpy(float)
        / atr[valid_atr]
    )
    m.loc[valid_atr, "GAP_ATR"] = (
        (m.loc[valid_atr, "open"] - prev_close.loc[valid_atr]).abs().to_numpy(float)
        / atr[valid_atr]
    )

    op_mask = in_window(m["available_at_brt"], rules)
    train = m.loc[
        m["available_at_brt"].lt(TRAIN_END)
        & op_mask
        & m["available_at_brt"].dt.weekday.lt(5)
    ].copy()

    thresholds: dict[str, dict[str, float]] = {}
    for metric in METRICS:
        vals = train[metric].replace([np.inf, -np.inf], np.nan).dropna()
        if len(vals) < 1000:
            raise RuntimeError(
                f"Insufficient TRAIN reference for {metric}: n={len(vals)}"
            )
        thresholds[metric] = {
            "q_caution": float(vals.quantile(Q_CAUTION)),
            "q_no_trade": float(vals.quantile(Q_NO_TRADE)),
            "n_train": int(len(vals)),
        }

    fresh = m.loc[m["available_at_brt"].ge(FRESH_START)].copy().reset_index(drop=True)

    print("=" * 132)
    print("OPERABILITY01 — PROSPECTIVE GOLD MARKET OPERABILITY SHADOW GATE")
    print("=" * 132)
    print(f"M5 source                 = {m5_path}")
    print(f"TRAIN threshold reference = < {TRAIN_END} BRT | operational window only")
    print(f"Fresh-forward start       = >= {FRESH_START} BRT")
    print("Historical timing rescue  = PROHIBITED")
    print("Exp27 scoring             = PROHIBITED / UNTOUCHED")
    print("Runtime promotion         = NONE / SHADOW ONLY")
    print()
    print("Frozen TRAIN-only shock thresholds:")
    for metric, t in thresholds.items():
        print(
            f"  {metric:<12} CAUTION q{Q_CAUTION:.3f}={t['q_caution']:.6f} "
            f"NO_TRADE q{Q_NO_TRADE:.3f}={t['q_no_trade']:.6f} n={t['n_train']}"
        )

    if fresh.empty:
        print()
        print("OPERABILITY01_STATUS = WAITING_FOR_FRESH_FORWARD_DATA")
        print("No row >= 2026-08-13 00:00 BRT exists in the local M5 parquet.")
        return

    cfg = rules.get("operational_window_brt", {}) or {}
    start_s = str(cfg.get("start") or "09:00")
    end_s = str(cfg.get("end") or "18:00")
    start_min = parse_hhmm(start_s)
    end_min = parse_hhmm(end_s)
    if start_min > end_min:
        raise RuntimeError(
            "OPERABILITY01 v1 freezes a same-day operational window; "
            f"cross-midnight window {start_s}-{end_s} is unsupported."
        )

    ts = fresh["available_at_brt"]
    minute = (ts.dt.hour * 60 + ts.dt.minute).to_numpy(int)
    weekday = ts.dt.weekday.to_numpy(int)

    fresh["IN_OPERATIONAL_WINDOW"] = in_window(ts, rules).to_numpy(bool)
    fresh["MINUTES_TO_WINDOW_END"] = end_min - minute
    fresh["IS_FRIDAY"] = weekday == 4

    events = load_scheduled_high_events()
    fresh["HIGH_EVENT_DISTANCE_MIN"] = nearest_event_distance_minutes(ts, events)

    n = len(fresh)
    reasons: list[list[str]] = [[] for _ in range(n)]
    severity = np.zeros(n, dtype=np.int8)

    invalid_ohlc = ~np.isfinite(
        fresh[["open", "high", "low", "close", "ATR"]].to_numpy(float)
    ).all(axis=1) | (fresh["ATR"].to_numpy(float) <= 0)
    data_gap = fresh["M5_DELTA_MIN"].notna().to_numpy(bool) & ~np.isclose(
        fresh["M5_DELTA_MIN"].fillna(5.0).to_numpy(float), 5.0, atol=1e-9
    )
    outside = ~fresh["IN_OPERATIONAL_WINDOW"].to_numpy(bool)
    weekend = weekday >= 5

    hard = invalid_ohlc | data_gap | outside | weekend
    severity[hard] = 2
    add_reason(reasons, invalid_ohlc, "INVALID_M5_OR_ATR")
    add_reason(reasons, data_gap, "NONCONTIGUOUS_M5_DATA")
    add_reason(reasons, outside, "OUTSIDE_OPERATIONAL_WINDOW")
    add_reason(reasons, weekend, "WEEKEND")

    friday = fresh["IS_FRIDAY"].to_numpy(bool) & fresh["IN_OPERATIONAL_WINDOW"].to_numpy(bool)
    mins_to_end = fresh["MINUTES_TO_WINDOW_END"].to_numpy(int)
    friday_no = friday & (mins_to_end >= 0) & (mins_to_end <= FRIDAY_NO_TRADE_MINUTES_TO_END)
    friday_caution = (
        friday
        & (mins_to_end > FRIDAY_NO_TRADE_MINUTES_TO_END)
        & (mins_to_end <= FRIDAY_CAUTION_MINUTES_TO_END)
    )
    severity[friday_caution] = np.maximum(severity[friday_caution], 1)
    severity[friday_no] = 2
    add_reason(reasons, friday_caution, "FRIDAY_FINAL_60M")
    add_reason(reasons, friday_no, "FRIDAY_FINAL_30M")

    ed = fresh["HIGH_EVENT_DISTANCE_MIN"].to_numpy(float)
    event_no = ed <= HIGH_EVENT_NO_TRADE_MINUTES
    event_caution = (ed > HIGH_EVENT_NO_TRADE_MINUTES) & (ed <= HIGH_EVENT_CAUTION_MINUTES)
    severity[event_caution] = np.maximum(severity[event_caution], 1)
    severity[event_no] = 2
    add_reason(reasons, event_caution, "SCHEDULED_HIGH_EVENT_30M")
    add_reason(reasons, event_no, "SCHEDULED_HIGH_EVENT_15M")

    caution_hits = np.zeros(n, dtype=np.int16)
    no_trade_shock = np.zeros(n, dtype=bool)

    for metric in METRICS:
        x = fresh[metric].to_numpy(float)
        t = thresholds[metric]
        nt = np.isfinite(x) & (x >= t["q_no_trade"])
        ca = np.isfinite(x) & (x >= t["q_caution"]) & ~nt
        no_trade_shock |= nt
        caution_hits += ca.astype(np.int16)
        add_reason(reasons, nt, f"{metric}_EXTREME")
        add_reason(reasons, ca, f"{metric}_ELEVATED")

    multi_caution = caution_hits >= 2
    single_caution = caution_hits == 1
    severity[single_caution] = np.maximum(severity[single_caution], 1)
    severity[no_trade_shock | multi_caution] = 2
    add_reason(reasons, multi_caution, "MULTIPLE_SHOCK_WARNINGS")

    label = np.where(severity == 2, "NO_TRADE", np.where(severity == 1, "CAUTION", "TRADEABLE"))
    fresh["OPERABILITY"] = label
    fresh["NEW_ENTRY_POLICY"] = np.where(
        severity == 2, "BLOCKED",
        np.where(severity == 1, "REVIEW_REQUIRED", "ALLOWED")
    )
    fresh["RISK_MANAGEMENT_POLICY"] = "ALLOWED"
    fresh["OPERABILITY_REASONS"] = [
        ";".join(dict.fromkeys(r)) if r else "NONE"
        for r in reasons
    ]

    print()
    print("Scheduled HIGH-impact event feed:")
    if events.empty:
        print(f"  INACTIVE — no file at {EVENTS_PATH}")
        print("  Expected CSV columns: event_time_brt,impact,label")
        print("  Only events supplied prospectively may affect this gate.")
    else:
        print(f"  ACTIVE — {len(events)} HIGH events loaded from {EVENTS_PATH}")

    print()
    print("Fresh-forward operability counts (NO OUTCOME SCORE):")
    counts = fresh["OPERABILITY"].value_counts(dropna=False)
    for k in ("TRADEABLE", "CAUTION", "NO_TRADE"):
        print(f"  {k:<10} = {int(counts.get(k, 0))}")

    out_cols = [
        "available_at_brt", "open", "high", "low", "close", "ATR",
        "RANGE_ATR", "ABS_RET_ATR", "GAP_ATR", "M5_DELTA_MIN",
        "IN_OPERATIONAL_WINDOW", "IS_FRIDAY", "MINUTES_TO_WINDOW_END",
        "HIGH_EVENT_DISTANCE_MIN", "OPERABILITY", "NEW_ENTRY_POLICY",
        "RISK_MANAGEMENT_POLICY", "OPERABILITY_REASONS",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fresh[out_cols].to_csv(OUT_PATH, index=False)

    print()
    print(f"Shadow log written = {OUT_PATH}")
    print()
    print("Latest fresh-forward rows:")
    print(
        fresh[out_cols].tail(30).to_string(
            index=False,
            float_format=lambda v: f"{v:.5f}"
        )
    )

    print()
    print("OPERABILITY01_POLICY_STATUS = FROZEN")
    print("OPERABILITY01_MODE = SHADOW_ONLY")
    print("HISTORICAL_TIMING_FEATURE_DISCOVERY_STOP = PRESERVED_YES")
    print("EXP27 = UNTOUCHED")
    print("RUNTIME_PROMOTION = NONE")


if __name__ == "__main__":
    main()
