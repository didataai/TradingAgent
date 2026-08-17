#!/usr/bin/env python3
"""MICROSTRUCTURE BREAKOUT MAP 01 — causal GOLD quote/tick breakout mapping.

Scientific contract: docs/MICROSTRUCTURE_BREAKOUT_MAP01.md

This is a separate historical exploratory research line. It does not touch,
score, filter or inspect Exp27 / Decision Calibration fresh-forward ledgers.
No candle color, fitted spread threshold, Last/Volume tape or runtime signal is
used.
"""
from __future__ import annotations

import argparse
import heapq
import math
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError as exc:
    raise SystemExit("MetaTrader5 not installed. Run: pip install MetaTrader5") from exc

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.study_d1_mtf_filter import bseries, load_json, prepare

SYMBOL_DEFAULT = "GOLD"
BRT = ZoneInfo("America/Sao_Paulo")
RULES_PATH = ROOT / "config" / "market_intelligence" / "GOLD_d1_intraday_rules.json"
TF_DIR = ROOT / "data" / "market_chronos" / "candle_base" / "timeframes"
OUT_DIR = ROOT / "data" / "market_chronos" / "microstructure"

DEFAULT_START = "2026-02-01"
DEFAULT_END = "2026-08-12"
EXPECTED_POINT = 0.01

EVENT_START = time(9, 0, 0)
EVENT_END = time(18, 0, 0)  # exclusive
QUERY_START = time(8, 59, 0)
QUERY_END = time(18, 2, 0)
PRE_BASELINE_MS = 30_000
BREAK_HORIZONS_S = (1, 2, 5, 15, 30, 60)
RETURN_HORIZONS_S = (1, 2, 5, 10, 15, 30, 60)
TARGET_POINTS = (50, 100, 200, 300)
BOOT_N = 5000
BOOT_SEED = 2026081704
MIN_PRE_TICKS = 20
MAP_FEATURES = (
    "spread_ratio",
    "tick_rate_ratio_1s",
    "tick_accel_1s_vs_prev4s",
    "signed_mid_impulse_1s_points",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Frozen Microstructure Breakout Map 01")
    p.add_argument("--symbol", default=SYMBOL_DEFAULT)
    p.add_argument("--start", default=DEFAULT_START, help="BRT YYYY-MM-DD inclusive")
    p.add_argument("--end", default=DEFAULT_END, help="BRT YYYY-MM-DD inclusive")
    return p.parse_args()


def _resolve_tf_path(tf: str) -> Path:
    preferred = [
        TF_DIR / f"GOLD_{tf}_candle_research.parquet",
        TF_DIR / f"GOLD_{tf}.parquet",
        TF_DIR / f"gold_{tf.lower()}_candle_research.parquet",
        TF_DIR / f"gold_{tf.lower()}.parquet",
    ]
    for p in preferred:
        if p.exists():
            return p
    if not TF_DIR.exists():
        raise FileNotFoundError(f"Timeframe directory not found: {TF_DIR}")
    cands = sorted(
        p for p in TF_DIR.glob("*.parquet")
        if "GOLD" in p.name.upper() and tf.upper() in p.name.upper()
    )
    research = [p for p in cands if "RESEARCH" in p.name.upper()]
    if len(research) == 1:
        return research[0]
    if len(cands) == 1:
        return cands[0]
    raise RuntimeError(f"Could not resolve unique GOLD {tf} parquet: {[p.name for p in cands]}")


def _build_levels(start_ts: pd.Timestamp, end_exclusive: pd.Timestamp) -> pd.DataFrame:
    rules = load_json(RULES_PATH)
    rows: list[dict] = []
    for tf in ("M5", "M15"):
        path = _resolve_tf_path(tf)
        q = prepare(path, tf, rules)
        required = {
            "available_at_brt",
            "swing_high_confirmed",
            "swing_low_confirmed",
            "confirmed_swing_high_price",
            "confirmed_swing_low_price",
        }
        missing = sorted(required - set(q.columns))
        if missing:
            raise RuntimeError(
                f"{path}: missing frozen causal swing fields {missing}. "
                "Rebuild candle research data; Map01 will not create a second swing definition."
            )
        q["available_at_brt"] = pd.to_datetime(q["available_at_brt"], errors="coerce")
        q = q.loc[
            q["available_at_brt"].ge(start_ts)
            & q["available_at_brt"].lt(end_exclusive)
        ].copy()
        for side, flag_col, price_col, direction in (
            ("RESISTANCE", "swing_high_confirmed", "confirmed_swing_high_price", 1),
            ("SUPPORT", "swing_low_confirmed", "confirmed_swing_low_price", -1),
        ):
            z = q.loc[bseries(q[flag_col])].copy()
            z[price_col] = pd.to_numeric(z[price_col], errors="coerce")
            z = z.dropna(subset=["available_at_brt", price_col])
            for idx, r in z.iterrows():
                price = float(r[price_col])
                if not np.isfinite(price) or price <= 0:
                    continue
                confirm = pd.Timestamp(r["available_at_brt"])
                rows.append({
                    "level_id": f"{tf}:{side[0]}:{idx}:{confirm.isoformat()}:{price:.2f}",
                    "tf": tf,
                    "level_type": side,
                    "direction": direction,
                    "level_price": price,
                    "confirm_time": confirm,
                })
        print(f"LEVEL SOURCE {tf:<3} = {path}")
    levels = pd.DataFrame(rows)
    if levels.empty:
        raise RuntimeError("No confirmed M5/M15 swing levels in frozen Map01 window")
    levels = (
        levels.sort_values(["confirm_time", "tf", "level_type", "level_price", "level_id"])
        .drop_duplicates(["tf", "level_type", "confirm_time", "level_price"], keep="first")
        .reset_index(drop=True)
    )
    levels["confirm_ms"] = (
        levels["confirm_time"].astype("int64") // 1_000_000
    ).astype(np.int64)
    return levels


def _brt_local(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=BRT)


def _to_utc(d: datetime) -> datetime:
    return d.astimezone(timezone.utc)


def _ms_to_brt_naive(ms: int) -> pd.Timestamp:
    return pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert(BRT).tz_localize(None)


def _valid_ticks(raw: np.ndarray | None) -> np.ndarray:
    if raw is None or len(raw) == 0:
        return np.empty(0, dtype=[("time_msc", "<i8"), ("bid", "<f8"), ("ask", "<f8"), ("flags", "<u4")])
    names = set(raw.dtype.names or ())
    need = {"time_msc", "bid", "ask", "flags"}
    missing = sorted(need - names)
    if missing:
        raise RuntimeError(f"MT5 ticks missing fields: {missing}")
    good = (
        np.isfinite(raw["bid"].astype(float))
        & np.isfinite(raw["ask"].astype(float))
        & (raw["bid"].astype(float) > 0)
        & (raw["ask"].astype(float) > 0)
        & (raw["ask"].astype(float) >= raw["bid"].astype(float))
    )
    return raw[good]


def _ref_value(ms: np.ndarray, x: np.ndarray, target_ms: int) -> float:
    j = int(np.searchsorted(ms, target_ms, side="right") - 1)
    return float(x[j]) if j >= 0 else np.nan


def _rate(ms: np.ndarray, i: int, window_ms: int) -> float:
    t0 = int(ms[i])
    lo = int(np.searchsorted(ms, t0 - window_ms, side="left"))
    n = i - lo + 1
    return float(n) / (window_ms / 1000.0)


def _pre_features(ticks: np.ndarray, i: int, direction: int, point: float) -> dict | None:
    ms = ticks["time_msc"].astype(np.int64)
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)
    mid = (bid + ask) / 2.0
    spread = ask - bid
    t0 = int(ms[i])

    base_lo = int(np.searchsorted(ms, t0 - PRE_BASELINE_MS, side="left"))
    base = spread[base_lo:i]
    if len(base) < MIN_PRE_TICKS:
        return None
    base = base[np.isfinite(base) & (base > 0)]
    if len(base) < MIN_PRE_TICKS:
        return None
    spread_base = float(np.median(base))
    if not np.isfinite(spread_base) or spread_base <= 0:
        return None

    baseline_rate = float(i - base_lo) / (PRE_BASELINE_MS / 1000.0)
    if baseline_rate <= 0:
        return None

    out: dict[str, float] = {
        "attack_bid": float(bid[i]),
        "attack_ask": float(ask[i]),
        "attack_mid": float(mid[i]),
        "attack_spread": float(spread[i]),
        "spread_baseline_30s": spread_base,
        "spread_ratio": float(spread[i] / spread_base),
        "tick_rate_baseline_30s": baseline_rate,
    }

    for name, w in (("250ms", 250), ("1s", 1000), ("5s", 5000)):
        rate = _rate(ms, i, w)
        out[f"tick_rate_{name}"] = rate
        out[f"tick_rate_ratio_{name}"] = rate / baseline_rate
        spread_ref = _ref_value(ms, spread, t0 - w)
        out[f"spread_delta_{name}"] = float(spread[i] - spread_ref) if np.isfinite(spread_ref) else np.nan
        for qname, arr in (("mid", mid), ("bid", bid), ("ask", ask)):
            ref = _ref_value(ms, arr, t0 - w)
            out[f"signed_{qname}_impulse_{name}_points"] = (
                float(direction * (arr[i] - ref) / point) if np.isfinite(ref) else np.nan
            )

    prev4_lo = int(np.searchsorted(ms, t0 - 5000, side="left"))
    prev4_hi = int(np.searchsorted(ms, t0 - 1000, side="left"))
    prev4_rate = float(max(0, prev4_hi - prev4_lo)) / 4.0
    out["tick_accel_1s_vs_prev4s"] = (
        out["tick_rate_1s"] / prev4_rate if prev4_rate > 0 else np.nan
    )

    one_lo = int(np.searchsorted(ms, t0 - 1000, side="left"))
    if i - one_lo >= 1:
        dmid = np.diff(mid[one_lo:i + 1])
        dbid = np.diff(bid[one_lo:i + 1])
        dask = np.diff(ask[one_lo:i + 1])
        changed = np.abs(dmid) > 1e-12
        out["directional_mid_update_fraction_1s"] = (
            float(np.mean(direction * dmid[changed] > 0)) if np.any(changed) else np.nan
        )
        out["both_quote_change_fraction_1s"] = float(
            np.mean((np.abs(dbid) > 1e-12) & (np.abs(dask) > 1e-12))
        )
    else:
        out["directional_mid_update_fraction_1s"] = np.nan
        out["both_quote_change_fraction_1s"] = np.nan
    return out


def _future_labels(ticks: np.ndarray, attack_i: int, direction: int, level: float, point: float) -> dict:
    ms = ticks["time_msc"].astype(np.int64)
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)
    mid = (bid + ask) / 2.0
    t0 = int(ms[attack_i])
    end_i = int(np.searchsorted(ms, t0 + 60_000, side="right"))
    sl = slice(attack_i, end_i)

    if direction > 0:
        cond = bid[sl] > level
    else:
        cond = ask[sl] < level
    hit = np.flatnonzero(cond)
    out: dict[str, float | int] = {}
    if len(hit):
        break_i = attack_i + int(hit[0])
        break_delay = int(ms[break_i] - t0)
    else:
        break_i = -1
        break_delay = -1

    for h in BREAK_HORIZONS_S:
        out[f"break_{h}s"] = int(break_i >= 0 and break_delay <= h * 1000)
    out["time_to_break_ms"] = break_delay if break_i >= 0 else np.nan

    if break_i < 0:
        out.update({
            "break_time": pd.NaT,
            "break_bid": np.nan,
            "break_ask": np.nan,
            "break_mid": np.nan,
            "time_to_recapture_ms": np.nan,
            "mfe_60_points": np.nan,
            "mae_60_points": np.nan,
        })
        for h in RETURN_HORIZONS_S:
            out[f"return_{h}s_points"] = np.nan
        for target in TARGET_POINTS:
            out[f"hit_{target}_before_recapture"] = np.nan
            out[f"time_to_{target}_ms"] = np.nan
        return out

    break_ms = int(ms[break_i])
    break_mid = float(mid[break_i])
    post_end = int(np.searchsorted(ms, break_ms + 60_000, side="right"))
    signed = direction * (mid[break_i:post_end] - break_mid) / point
    out["break_time"] = _ms_to_brt_naive(break_ms)
    out["break_bid"] = float(bid[break_i])
    out["break_ask"] = float(ask[break_i])
    out["break_mid"] = break_mid
    out["mfe_60_points"] = float(np.max(signed)) if len(signed) else 0.0
    out["mae_60_points"] = float(max(0.0, -np.min(signed))) if len(signed) else 0.0

    post_idx = np.arange(break_i, post_end)
    if direction > 0:
        rec_cond = ask[break_i:post_end] < level
    else:
        rec_cond = bid[break_i:post_end] > level
    rec_hits = np.flatnonzero(rec_cond)
    rec_i = break_i + int(rec_hits[0]) if len(rec_hits) else -1
    out["time_to_recapture_ms"] = (
        int(ms[rec_i] - break_ms) if rec_i >= 0 else np.nan
    )

    for h in RETURN_HORIZONS_S:
        j = int(np.searchsorted(ms, break_ms + h * 1000, side="right") - 1)
        if j < break_i:
            out[f"return_{h}s_points"] = np.nan
        else:
            out[f"return_{h}s_points"] = float(direction * (mid[j] - break_mid) / point)

    for target in TARGET_POINTS:
        target_hits = np.flatnonzero(signed >= target)
        if len(target_hits):
            ti = break_i + int(target_hits[0])
            before_rec = rec_i < 0 or ti < rec_i
            out[f"hit_{target}_before_recapture"] = int(before_rec)
            out[f"time_to_{target}_ms"] = int(ms[ti] - break_ms) if before_rec else np.nan
        else:
            out[f"hit_{target}_before_recapture"] = 0
            out[f"time_to_{target}_ms"] = np.nan
    return out


def _bootstrap_day_diff(df: pd.DataFrame, outcome: str) -> dict:
    q = df.dropna(subset=[outcome, "spread_expanded", "attack_day"]).copy()
    if q.empty or q["spread_expanded"].nunique() < 2:
        return {"point": np.nan, "lo": np.nan, "hi": np.nan, "days": 0}
    daily = (
        q.groupby(["attack_day", "spread_expanded"], observed=True)[outcome]
        .agg(["sum", "count"])
        .reset_index()
    )
    days = sorted(q["attack_day"].unique())
    pos_sum = {d: 0.0 for d in days}
    pos_n = {d: 0.0 for d in days}
    neg_sum = {d: 0.0 for d in days}
    neg_n = {d: 0.0 for d in days}
    for _, r in daily.iterrows():
        d = r["attack_day"]
        if bool(r["spread_expanded"]):
            pos_sum[d], pos_n[d] = float(r["sum"]), float(r["count"])
        else:
            neg_sum[d], neg_n[d] = float(r["sum"]), float(r["count"])
    ps = np.array([pos_sum[d] for d in days])
    pn = np.array([pos_n[d] for d in days])
    ns = np.array([neg_sum[d] for d in days])
    nn = np.array([neg_n[d] for d in days])
    point = float(q.loc[q["spread_expanded"], outcome].mean() - q.loc[~q["spread_expanded"], outcome].mean())
    rng = np.random.default_rng(BOOT_SEED)
    boot: list[float] = []
    for _ in range(BOOT_N):
        idx = rng.integers(0, len(days), size=len(days))
        pnn, nnn = float(pn[idx].sum()), float(nn[idx].sum())
        if pnn <= 0 or nnn <= 0:
            continue
        boot.append(float(ps[idx].sum() / pnn - ns[idx].sum() / nnn))
    if not boot:
        return {"point": point, "lo": np.nan, "hi": np.nan, "days": len(days)}
    lo, hi = np.quantile(np.asarray(boot), [0.025, 0.975])
    return {"point": point, "lo": float(lo), "hi": float(hi), "days": len(days)}


def _quintile_map(df: pd.DataFrame, feature: str, outcome: str, stage: str) -> pd.DataFrame:
    q = df.dropna(subset=[feature, outcome]).copy()
    if len(q) < 10 or q[feature].nunique() < 5:
        return pd.DataFrame()
    try:
        q["bucket"] = pd.qcut(q[feature], 5, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    out = (
        q.groupby("bucket", observed=True)
        .agg(n=(outcome, "size"), rate=(outcome, "mean"), feature_mean=(feature, "mean"), feature_median=(feature, "median"))
        .reset_index()
    )
    out["stage"] = stage
    out["feature"] = feature
    out["outcome"] = outcome
    out["bucket"] = out["bucket"].astype(str)
    return out[["stage", "feature", "outcome", "bucket", "n", "rate", "feature_mean", "feature_median"]]


def _two_dim_map(df: pd.DataFrame, outcome: str, stage: str) -> pd.DataFrame:
    q = df.dropna(subset=["spread_ratio", "tick_rate_ratio_1s", outcome]).copy()
    if len(q) < 25 or q["spread_ratio"].nunique() < 5 or q["tick_rate_ratio_1s"].nunique() < 5:
        return pd.DataFrame()
    try:
        q["spread_q"] = pd.qcut(q["spread_ratio"], 5, duplicates="drop")
        q["tick_q"] = pd.qcut(q["tick_rate_ratio_1s"], 5, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    out = (
        q.groupby(["spread_q", "tick_q"], observed=True)
        .agg(n=(outcome, "size"), rate=(outcome, "mean"))
        .reset_index()
    )
    out["stage"] = stage
    out["outcome"] = outcome
    out["spread_q"] = out["spread_q"].astype(str)
    out["tick_q"] = out["tick_q"].astype(str)
    return out[["stage", "outcome", "spread_q", "tick_q", "n", "rate"]]


def _print_rate_table(df: pd.DataFrame, outcomes: tuple[str, ...], title: str) -> None:
    print()
    print(title)
    for expanded in (False, True):
        z = df.loc[df["spread_expanded"].eq(expanded)]
        label = "SPREAD<=BASE" if not expanded else "SPREAD>BASE"
        vals = " ".join(
            f"{c}={100*z[c].mean():6.2f}%" if len(z) and z[c].notna().any() else f"{c}=NA"
            for c in outcomes
        )
        print(f"  {label:<13} n={len(z):>5} | {vals}")


def main() -> int:
    args = _parse_args()
    symbol = str(args.symbol).strip()
    start_ts = pd.Timestamp(f"{args.start} 00:00:00")
    end_day = pd.Timestamp(f"{args.end} 00:00:00")
    end_exclusive = end_day + pd.Timedelta(days=1)
    if end_exclusive <= start_ts:
        raise SystemExit("--end must be >= --start")

    print("=" * 132)
    print("MICROSTRUCTURE BREAKOUT MAP 01 — GOLD BID/ASK QUOTE MICROSTRUCTURE")
    print("=" * 132)
    print("Status             = HISTORICAL EXPLORATORY MAP / NO FORMAL PASS-FAIL")
    print(f"Symbol             = {symbol}")
    print(f"Historical window  = {start_ts} <= BRT < {end_exclusive}")
    print("Event window       = 09:00 <= attack BRT < 18:00")
    print("Levels             = M5/M15 existing causal 2-left/2-right confirmed swings")
    print("Level usage        = FIRST OBSERVED ATTACK ONLY")
    print("Candle color       = NOT USED")
    print("Tick tape          = BID/ASK + time_msc; Last/Volume/BUY/SELL NOT USED")
    print("Question A         = ATTACK -> FULL-QUOTE BREAK 1/2/5/15/30/60s")
    print("Question B         = BREAK -> +50/+100/+200/+300 points before recapture within 60s")
    print("Threshold search   = NONE; spread_ratio > 1 is pre-frozen coarse contrast only")
    print("Exp27/Calibration  = UNTOUCHED / SCORES SEALED")
    print("Runtime promotion  = NONE")
    print()

    levels = _build_levels(start_ts, end_exclusive)
    print(f"CONFIRMED LEVELS = {len(levels)}")
    print(levels.groupby(["tf", "level_type"]).size().to_string())

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol_info({symbol}) returned None")
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")
        point = float(info.point)
        print()
        print(f"MT5 SYMBOL GUARD digits={info.digits} point={point:.8f}")
        if not math.isclose(point, EXPECTED_POINT, rel_tol=0.0, abs_tol=1e-12):
            raise RuntimeError(
                f"MAP01 frozen point guard failed: expected {EXPECTED_POINT}, got {point}"
            )

        pending = levels.to_dict("records")
        pending_i = 0
        res_heap: list[tuple[float, int, dict]] = []
        sup_heap: list[tuple[float, int, dict]] = []
        seq = 0
        events: list[dict] = []
        status = Counter()
        total_valid_ticks = 0
        days_with_ticks = 0
        days_no_ticks = 0

        days = pd.date_range(start_ts.normalize(), end_day.normalize(), freq="D")
        for dts in days:
            d = dts.date()
            if d.weekday() >= 5:
                continue
            q_start = _brt_local(d, QUERY_START)
            q_end = _brt_local(d, QUERY_END)
            raw = mt5.copy_ticks_range(symbol, _to_utc(q_start), _to_utc(q_end), mt5.COPY_TICKS_ALL)
            ticks = _valid_ticks(raw)
            if len(ticks) == 0:
                days_no_ticks += 1
                status["NO_TICK_DAY"] += 1
                continue
            days_with_ticks += 1
            total_valid_ticks += len(ticks)
            ms = ticks["time_msc"].astype(np.int64)
            bid = ticks["bid"].astype(float)
            ask = ticks["ask"].astype(float)
            first_ms = int(ms[0])

            # Levels already known before today's first quote are activated only if
            # the market is still on the causal side of the level. Otherwise the
            # first attack may have happened outside the observed 09-18 window.
            while pending_i < len(pending) and int(pending[pending_i]["confirm_ms"]) <= first_ms:
                lv = pending[pending_i]
                pending_i += 1
                if int(lv["direction"]) > 0:
                    if ask[0] >= float(lv["level_price"]):
                        status["STALE_AT_DAY_START"] += 1
                    else:
                        heapq.heappush(res_heap, (float(lv["level_price"]), seq, lv)); seq += 1
                else:
                    if bid[0] <= float(lv["level_price"]):
                        status["STALE_AT_DAY_START"] += 1
                    else:
                        heapq.heappush(sup_heap, (-float(lv["level_price"]), seq, lv)); seq += 1

            # Active levels carried from a prior day may also have been crossed
            # outside the observed session. Remove them before today's events.
            while res_heap and res_heap[0][0] <= ask[0]:
                heapq.heappop(res_heap); status["STALE_AT_DAY_START"] += 1
            while sup_heap and -sup_heap[0][0] >= bid[0]:
                heapq.heappop(sup_heap); status["STALE_AT_DAY_START"] += 1

            event_start_ms = int(_brt_local(d, EVENT_START).timestamp() * 1000)
            event_end_ms = int(_brt_local(d, EVENT_END).timestamp() * 1000)

            for i in range(len(ticks)):
                tms = int(ms[i])

                # Levels becoming known during the continuously observed day can
                # be attacked on the first quote after their confirmation time.
                while pending_i < len(pending) and int(pending[pending_i]["confirm_ms"]) <= tms:
                    lv = pending[pending_i]
                    pending_i += 1
                    if int(lv["direction"]) > 0:
                        heapq.heappush(res_heap, (float(lv["level_price"]), seq, lv)); seq += 1
                    else:
                        heapq.heappush(sup_heap, (-float(lv["level_price"]), seq, lv)); seq += 1

                attacked: list[dict] = []
                while res_heap and res_heap[0][0] <= ask[i]:
                    _, _, lv = heapq.heappop(res_heap)
                    attacked.append(lv)
                while sup_heap and -sup_heap[0][0] >= bid[i]:
                    _, _, lv = heapq.heappop(sup_heap)
                    attacked.append(lv)

                if not attacked:
                    continue
                in_event_window = event_start_ms <= tms < event_end_ms
                for lv in attacked:
                    if not in_event_window:
                        status["ATTACK_OUTSIDE_EVENT_WINDOW"] += 1
                        continue
                    feat = _pre_features(ticks, i, int(lv["direction"]), point)
                    if feat is None:
                        status["INSUFFICIENT_PRE_TICKS"] += 1
                        continue
                    future = _future_labels(
                        ticks=ticks,
                        attack_i=i,
                        direction=int(lv["direction"]),
                        level=float(lv["level_price"]),
                        point=point,
                    )
                    attack_time = _ms_to_brt_naive(tms)
                    events.append({
                        "level_id": lv["level_id"],
                        "tf": lv["tf"],
                        "level_type": lv["level_type"],
                        "direction": int(lv["direction"]),
                        "level_price": float(lv["level_price"]),
                        "confirm_time": pd.Timestamp(lv["confirm_time"]),
                        "attack_time": attack_time,
                        "attack_day": attack_time.date(),
                        **feat,
                        **future,
                    })
                    status["RECORDED_ATTACK"] += 1

        if not events:
            print()
            print("No Map01 events produced.")
            print(f"days_with_ticks={days_with_ticks} days_no_ticks={days_no_ticks} valid_ticks={total_valid_ticks}")
            print("LEVEL STATUS")
            for k, v in sorted(status.items()):
                print(f"  {k:<30} {v}")
            print("MICROSTRUCTURE_BREAKOUT_MAP01 = COMPLETE_EXPLORATORY_MAP_EMPTY")
            return 0

        e = pd.DataFrame(events).sort_values(["attack_time", "tf", "level_price"]).reset_index(drop=True)
        e["spread_expanded"] = e["spread_ratio"] > 1.0
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        events_path = OUT_DIR / "MICROSTRUCTURE_breakout_map01_events.csv"
        e.to_csv(events_path, index=False)

        print()
        print("=" * 132)
        print("MAP01 EVENT UNIVERSE")
        print("=" * 132)
        print(f"days_with_ticks = {days_with_ticks}")
        print(f"days_no_ticks   = {days_no_ticks}")
        print(f"valid_ticks     = {total_valid_ticks}")
        print(f"recorded_attacks= {len(e)}")
        print(e.groupby(["tf", "level_type"]).size().to_string())
        print()
        print("LEVEL / COVERAGE AUDIT")
        for k, v in sorted(status.items()):
            print(f"  {k:<30} {v}")

        _print_rate_table(
            e,
            tuple(f"break_{h}s" for h in BREAK_HORIZONS_S),
            "QUESTION A — ATTACK -> FULL-QUOTE BREAK",
        )
        broken = e.loc[e["break_60s"].eq(1)].copy()
        _print_rate_table(
            broken,
            tuple(f"hit_{t}_before_recapture" for t in TARGET_POINTS),
            "QUESTION B — BREAK -> CONTINUATION BEFORE FULL-QUOTE RECAPTURE",
        )

        print()
        print("PRIMARY COARSE CONTRASTS — DIAGNOSTIC, NOT PROMOTION GATES")
        a = _bootstrap_day_diff(e, "break_60s")
        b = _bootstrap_day_diff(broken, "hit_200_before_recapture")
        print(
            f"Attack->Break60 spread>base minus <=base = {a['point']:+.5f} "
            f"CI95=[{a['lo']:+.5f},{a['hi']:+.5f}] days={a['days']}"
        )
        print(
            f"Break->Hit200 spread>base minus <=base    = {b['point']:+.5f} "
            f"CI95=[{b['lo']:+.5f},{b['hi']:+.5f}] days={b['days']}"
        )

        maps: list[pd.DataFrame] = []
        for feat_name in MAP_FEATURES:
            m = _quintile_map(e, feat_name, "break_60s", "ATTACK_TO_BREAK60")
            if not m.empty:
                maps.append(m)
            m2 = _quintile_map(broken, feat_name, "hit_200_before_recapture", "BREAK_TO_HIT200")
            if not m2.empty:
                maps.append(m2)
        map_path = OUT_DIR / "MICROSTRUCTURE_breakout_map01_quintiles.csv"
        if maps:
            pd.concat(maps, ignore_index=True).to_csv(map_path, index=False)

        grid_a = _two_dim_map(e, "break_60s", "ATTACK_TO_BREAK60")
        grid_b = _two_dim_map(broken, "hit_200_before_recapture", "BREAK_TO_HIT200")
        grid = pd.concat([x for x in (grid_a, grid_b) if not x.empty], ignore_index=True) if (not grid_a.empty or not grid_b.empty) else pd.DataFrame()
        grid_path = OUT_DIR / "MICROSTRUCTURE_breakout_map01_spread_tick_grid.csv"
        if not grid.empty:
            grid.to_csv(grid_path, index=False)

        print()
        print("DESCRIPTIVE FEATURE QUINTILES — BREAK<=60s")
        for feat_name in MAP_FEATURES:
            m = _quintile_map(e, feat_name, "break_60s", "ATTACK_TO_BREAK60")
            if m.empty:
                continue
            print()
            print(feat_name)
            print(m[["bucket", "n", "rate", "feature_mean"]].to_string(index=False, float_format=lambda x: f"{x:.5f}"))

        print()
        print("DESCRIPTIVE 2D MAP — spread_ratio x tick_rate_ratio_1s")
        if not grid_a.empty:
            p = grid_a.pivot(index="spread_q", columns="tick_q", values="rate")
            print("ATTACK -> BREAK60 rate")
            print(p.to_string(float_format=lambda x: f"{x:.3f}"))
        if not grid_b.empty:
            p = grid_b.pivot(index="spread_q", columns="tick_q", values="rate")
            print()
            print("BREAK -> HIT200 before recapture rate")
            print(p.to_string(float_format=lambda x: f"{x:.3f}"))

        print()
        print("OUTPUTS")
        print(f"  events   = {events_path}")
        if maps:
            print(f"  quintiles= {map_path}")
        if not grid.empty:
            print(f"  2d_grid  = {grid_path}")
        print()
        print("MICROSTRUCTURE_BREAKOUT_MAP01 = COMPLETE_EXPLORATORY_MAP")
        print("NO THRESHOLD / BEST-BUCKET PROMOTION IS AUTHORIZED BY MAP01")
        print("NEXT STEP = FREEZE ONE CANDIDATE FINGERPRINT AS MAP02 ONLY AFTER MAP01 INSPECTION")
        print("EXP27 = UNTOUCHED / SCORES SEALED")
        print("CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED")
        print("RUNTIME_PROMOTION = NONE")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
