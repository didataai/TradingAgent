#!/usr/bin/env python3
"""FLOW-MARK MAP 01R density-only probe.

Scientific contract:
    docs/MICROSTRUCTURE_FLOW_MARK_MAP01R.md

This temporary measurement probe intentionally computes NO lifecycle or future
outcome. It exists only to validate the debounced FLOW EPISODE representation
before PASS/FAIL/target inspection.
"""
from __future__ import annotations

import argparse
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError as exc:
    raise SystemExit("MetaTrader5 not installed. Run: pip install MetaTrader5") from exc

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "market_chronos" / "microstructure"
SYMBOL_DEFAULT = "GOLD"
BRT = ZoneInfo("America/Sao_Paulo")
EXPECTED_POINT = 0.01
BASELINE_SECONDS = 30
EPS = 1e-12


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Flow-Mark Map01R density-only smoke")
    p.add_argument("--symbol", default=SYMBOL_DEFAULT)
    p.add_argument("--start", default="2026-08-11", help="BRT YYYY-MM-DD inclusive")
    p.add_argument("--end", default="2026-08-11", help="BRT YYYY-MM-DD inclusive")
    return p.parse_args()


def brt_local(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=BRT)


def to_utc(d: datetime) -> datetime:
    return d.astimezone(timezone.utc)


def ms_to_brt(ms: int) -> pd.Timestamp:
    return pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert(BRT).tz_localize(None)


def valid_ticks(raw: np.ndarray | None) -> np.ndarray:
    if raw is None or len(raw) == 0:
        return np.empty(0, dtype=[("time_msc", "<i8"), ("bid", "<f8"), ("ask", "<f8")])
    names = set(raw.dtype.names or ())
    missing = sorted({"time_msc", "bid", "ask"} - names)
    if missing:
        raise RuntimeError(f"MT5 ticks missing fields: {missing}")
    bid = raw["bid"].astype(float)
    ask = raw["ask"].astype(float)
    good = (
        np.isfinite(bid)
        & np.isfinite(ask)
        & (bid > 0)
        & (ask > 0)
        & (ask >= bid)
    )
    q = raw[good]
    if len(q) <= 1:
        return q
    return q[np.argsort(q["time_msc"], kind="stable")]


def spread_baseline_by_tick(ms: np.ndarray, spread: np.ndarray) -> np.ndarray:
    """Median of prior 30 completed clock-second median spreads."""
    sec = (ms // 1000).astype(np.int64)
    s = pd.DataFrame({"sec": sec, "spread": spread}).groupby(
        "sec", sort=True, observed=True
    )["spread"].median()
    first_sec = int(s.index.min())
    last_sec = int(s.index.max())
    full_idx = np.arange(first_sec, last_sec + 1, dtype=np.int64)
    full = s.reindex(full_idx)
    baseline_full = (
        full.rolling(BASELINE_SECONDS, min_periods=BASELINE_SECONDS)
        .median()
        .shift(1)
    )
    vals = baseline_full.to_numpy(float)
    return vals[(sec - first_sec).astype(np.int64)]


def ref_idx(ms: np.ndarray, target_ms: int) -> int:
    return int(np.searchsorted(ms, target_ms, side="right") - 1)


def qfmt(x: np.ndarray, digits: int = 3) -> str:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return "NA"
    qs = np.quantile(x, [0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99])
    f = f"{{:.{digits}f}}"
    return (
        f"P10={f.format(qs[0])} P25={f.format(qs[1])} "
        f"P50={f.format(qs[2])} P75={f.format(qs[3])} "
        f"P90={f.format(qs[4])} P95={f.format(qs[5])} "
        f"P99={f.format(qs[6])} max={f.format(np.max(x))}"
    )


def episodes_for_day(
    ticks: np.ndarray,
    point: float,
    day: date,
) -> tuple[pd.DataFrame, dict]:
    ms = ticks["time_msc"].astype(np.int64)
    bid = ticks["bid"].astype(float)
    ask = ticks["ask"].astype(float)
    mid = (bid + ask) / 2.0
    spread = ask - bid
    baseline = spread_baseline_by_tick(ms, spread)

    available = np.isfinite(baseline) & (baseline > 0)
    expanded = available & (spread > baseline)
    actual_widening = np.r_[False, spread[1:] > spread[:-1] + EPS]
    qualify = expanded & actual_widening

    # Original Map01 tick-flicker birth count, for reproduction/diagnostic only.
    prev_expanded = np.r_[False, expanded[:-1]]
    old_raw_birth = expanded & ~prev_expanded & actual_widening

    qi = np.flatnonzero(qualify)
    rows: list[dict] = []
    if len(qi):
        qsec = (ms[qi] // 1000).astype(np.int64)
        # Same episode while qualifying widening ticks occur in the same or the
        # immediately next clock second. A gap >=2 means one full quiet second
        # has completed with zero qualifying widening ticks.
        starts = np.r_[0, np.flatnonzero(np.diff(qsec) > 1) + 1]
        ends = np.r_[starts[1:], len(qi)]

        day_end_ms = int((brt_local(day + timedelta(days=1), time(0, 0)) - timedelta(milliseconds=1)).timestamp() * 1000)
        for seq, (a, b) in enumerate(zip(starts, ends)):
            members = qi[int(a):int(b)]
            birth_i = int(members[0])
            last_i = int(members[-1])
            local_spread = spread[members]
            peak_off = int(np.argmax(local_spread))  # earliest max tie
            peak_i = int(members[peak_off])
            j = ref_idx(ms, int(ms[birth_i]) - 1000)
            delta_mid = float(mid[birth_i] - mid[j]) if j >= 0 else np.nan
            if np.isfinite(delta_mid) and delta_mid > EPS:
                direction = "UP"
            elif np.isfinite(delta_mid) and delta_mid < -EPS:
                direction = "DOWN"
            else:
                direction = "NEUTRAL"

            last_sec = int(ms[last_i] // 1000)
            quiet_sec_end_ms = (last_sec + 2) * 1000 - 1
            close_reason = "QUIET_SECOND" if quiet_sec_end_ms <= day_end_ms else "DAY_END"
            close_ms = min(quiet_sec_end_ms, day_end_ms)
            birth_time = ms_to_brt(int(ms[birth_i]))
            peak_time = ms_to_brt(int(ms[peak_i]))
            last_time = ms_to_brt(int(ms[last_i]))
            minute = birth_time.hour * 60 + birth_time.minute

            rows.append(
                {
                    "episode_id": f"{day.isoformat()}:{seq:06d}:{int(ms[birth_i])}",
                    "birth_day": day,
                    "birth_time": birth_time,
                    "direction": direction,
                    "birth_bid": float(bid[birth_i]),
                    "birth_mid": float(mid[birth_i]),
                    "birth_ask": float(ask[birth_i]),
                    "birth_spread": float(spread[birth_i]),
                    "birth_baseline": float(baseline[birth_i]),
                    "birth_spread_ratio": float(spread[birth_i] / baseline[birth_i]),
                    "birth_delta_mid_1s_points": float(delta_mid / point) if np.isfinite(delta_mid) else np.nan,
                    "peak_time": peak_time,
                    "peak_bid": float(bid[peak_i]),
                    "peak_mid": float(mid[peak_i]),
                    "peak_ask": float(ask[peak_i]),
                    "peak_spread": float(spread[peak_i]),
                    "peak_spread_ratio": float(spread[peak_i] / baseline[peak_i]) if np.isfinite(baseline[peak_i]) and baseline[peak_i] > 0 else np.nan,
                    "last_qualifying_time": last_time,
                    "qualifying_ticks": int(len(members)),
                    "duration_birth_to_last_ms": int(ms[last_i] - ms[birth_i]),
                    "episode_close_time": ms_to_brt(int(close_ms)),
                    "close_reason": close_reason,
                    "in_09_18_birth": bool(9 * 60 <= minute < 18 * 60),
                }
            )

    diag = {
        "valid_ticks": int(len(ticks)),
        "baseline_available_ticks": int(available.sum()),
        "expanded_ticks": int(expanded.sum()),
        "qualifying_widening_ticks": int(qualify.sum()),
        "old_raw_births": int(old_raw_birth.sum()),
    }
    return pd.DataFrame(rows), diag


def print_day(day: date, eps: pd.DataFrame, diag: dict) -> None:
    print()
    print("=" * 116)
    print(f"FLOW-MARK 01R DENSITY ONLY — {day}")
    print("=" * 116)
    for k in (
        "valid_ticks",
        "baseline_available_ticks",
        "expanded_ticks",
        "qualifying_widening_ticks",
        "old_raw_births",
    ):
        print(f"{k:<28} = {diag[k]}")
    print(f"debounced_episodes           = {len(eps)}")
    if diag["old_raw_births"]:
        reduction = 1.0 - len(eps) / diag["old_raw_births"]
        print(f"reduction_vs_old_raw_births  = {100*reduction:.2f}%")
    print(f"episodes_per_24h             = {len(eps)/24.0:.2f}")
    if len(eps):
        n0918 = int(eps["in_09_18_birth"].sum())
        print(f"episodes_09_18               = {n0918}")
        print(f"episodes_per_hour_09_18      = {n0918/9.0:.2f}")
        print()
        print("BIRTH DIRECTION")
        print(eps["direction"].value_counts(dropna=False).to_string())
        print()
        print("QUALIFYING TICKS / EPISODE")
        print(qfmt(eps["qualifying_ticks"].to_numpy(float), digits=1))
        print()
        print("BIRTH -> LAST QUALIFYING DURATION (ms)")
        print(qfmt(eps["duration_birth_to_last_ms"].to_numpy(float), digits=1))
        print()
        print("PEAK SPREAD (price units)")
        print(qfmt(eps["peak_spread"].to_numpy(float), digits=5))
        print()
        print("PEAK SPREAD RATIO")
        print(qfmt(eps["peak_spread_ratio"].to_numpy(float), digits=4))
        print()
        print("CLOSE REASON")
        print(eps["close_reason"].value_counts(dropna=False).to_string())


def main() -> int:
    args = parse_args()
    symbol = str(args.symbol).strip()
    start = pd.Timestamp(args.start).date()
    end = pd.Timestamp(args.end).date()
    if end < start:
        raise SystemExit("--end must be >= --start")

    print("=" * 116)
    print("MICROSTRUCTURE FLOW-MARK MAP 01R — DENSITY-ONLY PRE-OUTCOME PROBE")
    print("=" * 116)
    print("Lifecycle/outcomes  = DISABLED BY DESIGN")
    print("PASS/FAIL/targets   = NOT COMPUTED")
    print("Debounce            = one full completed clock second with zero qualifying widening ticks")
    print("Contract            = docs/MICROSTRUCTURE_FLOW_MARK_MAP01R.md")
    print("Exp27/Calibration   = UNTOUCHED / SCORES SEALED")
    print("Runtime promotion   = NONE")

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    all_eps: list[pd.DataFrame] = []
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol_info({symbol}) returned None")
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")
        point = float(info.point)
        print(f"MT5 SYMBOL GUARD     digits={info.digits} point={point:.8f}")
        if not math.isclose(point, EXPECTED_POINT, rel_tol=0.0, abs_tol=1e-12):
            raise RuntimeError(f"FLOWMARK01R point guard failed: expected {EXPECTED_POINT}, got {point}")

        days = pd.date_range(start, end, freq="D")
        for n, ts in enumerate(days, start=1):
            d = ts.date()
            print(f"DAY {n:>3}/{len(days)} {d} | FETCH", flush=True)
            q_start = brt_local(d, time(0, 0))
            q_end = brt_local(d + timedelta(days=1), time(0, 0)) - timedelta(milliseconds=1)
            raw = mt5.copy_ticks_range(symbol, to_utc(q_start), to_utc(q_end), mt5.COPY_TICKS_ALL)
            ticks = valid_ticks(raw)
            if len(ticks) < 2:
                print(f"DAY {n:>3}/{len(days)} {d} | NO TICKS ({len(ticks)})", flush=True)
                continue
            print(f"DAY {n:>3}/{len(days)} {d} | BASELINE + EPISODES ticks={len(ticks)}", flush=True)
            eps, diag = episodes_for_day(ticks, point, d)
            print_day(d, eps, diag)
            if len(eps):
                all_eps.append(eps)
    finally:
        mt5.shutdown()

    if all_eps:
        out = pd.concat(all_eps, ignore_index=True)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / "FLOWMARK_map01r_density_episodes.csv"
        out.to_csv(path, index=False)
        print()
        print(f"DENSITY OUTPUT = {path}")

    print()
    print("FLOW_MARK_MAP01R_DENSITY_SMOKE = COMPLETE_PRE_OUTCOME")
    print("NO LIFECYCLE / PASS / FAILURE / TARGET OUTCOME WAS COMPUTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
