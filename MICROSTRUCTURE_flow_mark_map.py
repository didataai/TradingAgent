#!/usr/bin/env python3
"""MICROSTRUCTURE FLOW-MARK MAP 01 — causal quote-path mapping.

Scientific contract:
    docs/MICROSTRUCTURE_FLOW_MARK_MAP01.md

Separate historical exploratory line:
- no candle color;
- no M5/M15 level in mark birth;
- no fitted spread/tick threshold;
- BID/ASK + time_msc only;
- full BRT-day path, reset at BRT day boundary;
- no Exp27 / Decision Calibration inspection or runtime promotion.
"""
from __future__ import annotations

import argparse
import math
from collections import Counter
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
DEFAULT_START = "2026-02-01"
DEFAULT_END = "2026-08-12"
EXPECTED_POINT = 0.01

BASELINE_SECONDS = 30
PASS_HORIZONS_S = (1, 2, 5, 10, 15, 30, 60)
TARGET_POINTS = (50, 100, 200, 300)
BOOT_N = 5000
BOOT_SEED = 2026081705
BLOCK = 2048
EPS = 1e-12

MAP_FEATURES = (
    "spread_ratio",
    "tick_rate_ratio_1s",
    "tick_accel_1s_vs_prev4s",
    "signed_mid_impulse_1s_points",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Frozen Microstructure Flow-Mark Map 01")
    p.add_argument("--symbol", default=SYMBOL_DEFAULT)
    p.add_argument("--start", default=DEFAULT_START, help="BRT YYYY-MM-DD inclusive")
    p.add_argument("--end", default=DEFAULT_END, help="BRT YYYY-MM-DD inclusive")
    return p.parse_args()


def _brt_local(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=BRT)


def _to_utc(d: datetime) -> datetime:
    return d.astimezone(timezone.utc)


def _ms_to_brt_naive(ms: int) -> pd.Timestamp:
    return pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert(BRT).tz_localize(None)


def _valid_ticks(raw: np.ndarray | None) -> np.ndarray:
    if raw is None or len(raw) == 0:
        return np.empty(
            0,
            dtype=[
                ("time_msc", "<i8"),
                ("bid", "<f8"),
                ("ask", "<f8"),
                ("flags", "<u4"),
            ],
        )
    names = set(raw.dtype.names or ())
    need = {"time_msc", "bid", "ask", "flags"}
    missing = sorted(need - names)
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

    order = np.argsort(q["time_msc"], kind="stable")
    return q[order]


def _spread_baseline_by_tick(ms: np.ndarray, spread: np.ndarray) -> np.ndarray:
    """Median spread of the 30 completed clock seconds before current second."""
    sec = (ms // 1000).astype(np.int64)
    s = pd.DataFrame({"sec": sec, "spread": spread}).groupby(
        "sec", sort=True, observed=True
    )["spread"].median()

    first_sec = int(s.index.min())
    last_sec = int(s.index.max())
    full_idx = np.arange(first_sec, last_sec + 1, dtype=np.int64)
    full = s.reindex(full_idx)

    # Exact 30 completed clock seconds. Any missing second => baseline unavailable.
    baseline_full = (
        full.rolling(BASELINE_SECONDS, min_periods=BASELINE_SECONDS)
        .median()
        .shift(1)
    )
    values = baseline_full.to_numpy(float)
    return values[(sec - first_sec).astype(np.int64)]


def _ref_idx(ms: np.ndarray, target_ms: int) -> int:
    return int(np.searchsorted(ms, target_ms, side="right") - 1)


def _event_signature(
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    baseline: np.ndarray,
    i: int,
    direction: int,
    point: float,
) -> dict:
    mid = (bid + ask) / 2.0
    spread = ask - bid
    t0 = int(ms[i])

    out: dict[str, float | int | bool] = {
        "event_bid": float(bid[i]),
        "event_ask": float(ask[i]),
        "event_mid": float(mid[i]),
        "event_spread": float(spread[i]),
        "spread_baseline_30s": float(baseline[i]) if np.isfinite(baseline[i]) else np.nan,
        "spread_ratio": (
            float(spread[i] / baseline[i])
            if np.isfinite(baseline[i]) and baseline[i] > 0
            else np.nan
        ),
    }

    lo30 = int(np.searchsorted(ms, t0 - 30_000, side="left"))
    baseline_rate = float(max(0, i - lo30)) / 30.0
    out["tick_rate_baseline_30s"] = baseline_rate

    for label, window_ms in (("250ms", 250), ("1s", 1000), ("5s", 5000)):
        lo = int(np.searchsorted(ms, t0 - window_ms, side="left"))
        rate = float(i - lo + 1) / (window_ms / 1000.0)
        out[f"tick_rate_{label}"] = rate
        out[f"tick_rate_ratio_{label}"] = (
            rate / baseline_rate if baseline_rate > 0 else np.nan
        )

        j = _ref_idx(ms, t0 - window_ms)
        if j >= 0:
            out[f"spread_delta_{label}_points"] = float(
                (spread[i] - spread[j]) / point
            )
            for name, arr in (("bid", bid), ("ask", ask), ("mid", mid)):
                raw_points = float((arr[i] - arr[j]) / point)
                out[f"{name}_impulse_{label}_points"] = raw_points
                out[f"signed_{name}_impulse_{label}_points"] = (
                    float(direction * raw_points) if direction else np.nan
                )
        else:
            out[f"spread_delta_{label}_points"] = np.nan
            for name in ("bid", "ask", "mid"):
                out[f"{name}_impulse_{label}_points"] = np.nan
                out[f"signed_{name}_impulse_{label}_points"] = np.nan

    prev4_lo = int(np.searchsorted(ms, t0 - 5000, side="left"))
    prev4_hi = int(np.searchsorted(ms, t0 - 1000, side="left"))
    prev4_rate = float(max(0, prev4_hi - prev4_lo)) / 4.0
    out["tick_accel_1s_vs_prev4s"] = (
        float(out["tick_rate_1s"]) / prev4_rate if prev4_rate > 0 else np.nan
    )

    one_lo = int(np.searchsorted(ms, t0 - 1000, side="left"))
    if i - one_lo >= 1:
        dbid = np.diff(bid[one_lo : i + 1])
        dask = np.diff(ask[one_lo : i + 1])
        dmid = (dbid + dask) / 2.0
        changed_mid = np.abs(dmid) > EPS
        out["directional_mid_update_fraction_1s"] = (
            float(np.mean(direction * dmid[changed_mid] > 0))
            if direction and np.any(changed_mid)
            else np.nan
        )
        out["both_quote_change_fraction_1s"] = float(
            np.mean((np.abs(dbid) > EPS) & (np.abs(dask) > EPS))
        )
    else:
        out["directional_mid_update_fraction_1s"] = np.nan
        out["both_quote_change_fraction_1s"] = np.nan

    t = _ms_to_brt_naive(t0)
    minute = t.hour * 60 + t.minute
    out["hour_brt"] = int(t.hour)
    out["minute_brt"] = int(t.minute)
    out["in_09_18"] = bool(9 * 60 <= minute < 18 * 60)
    return out


class CrossFinder:
    def __init__(self, arr: np.ndarray, block: int = BLOCK):
        self.arr = np.asarray(arr, dtype=float)
        self.n = len(self.arr)
        self.block = int(block)
        nb = (self.n + self.block - 1) // self.block
        self.block_max = np.empty(nb, dtype=float)
        self.block_min = np.empty(nb, dtype=float)
        for b in range(nb):
            lo = b * self.block
            hi = min(self.n, lo + self.block)
            x = self.arr[lo:hi]
            self.block_max[b] = float(np.max(x))
            self.block_min[b] = float(np.min(x))

    def _first(self, start: int, end: int, threshold: float, mode: str) -> int:
        start = max(0, int(start))
        end = min(self.n, int(end))
        if start >= end:
            return -1

        def local(lo: int, hi: int) -> int:
            x = self.arr[lo:hi]
            if mode == "gt":
                hit = np.flatnonzero(x > threshold)
            elif mode == "ge":
                hit = np.flatnonzero(x >= threshold)
            elif mode == "lt":
                hit = np.flatnonzero(x < threshold)
            elif mode == "le":
                hit = np.flatnonzero(x <= threshold)
            else:
                raise ValueError(mode)
            return lo + int(hit[0]) if len(hit) else -1

        first_block_end = min(end, ((start // self.block) + 1) * self.block)
        hit = local(start, first_block_end)
        if hit >= 0:
            return hit
        pos = first_block_end

        full_end = (end // self.block) * self.block
        if pos < full_end:
            b0 = pos // self.block
            b1 = full_end // self.block
            if mode == "gt":
                candidates = np.flatnonzero(self.block_max[b0:b1] > threshold)
            elif mode == "ge":
                candidates = np.flatnonzero(self.block_max[b0:b1] >= threshold)
            elif mode == "lt":
                candidates = np.flatnonzero(self.block_min[b0:b1] < threshold)
            else:
                candidates = np.flatnonzero(self.block_min[b0:b1] <= threshold)

            for off in candidates:
                b = b0 + int(off)
                lo = b * self.block
                hi = min(end, lo + self.block)
                hit = local(lo, hi)
                if hit >= 0:
                    return hit
            pos = full_end

        if pos < end:
            return local(pos, end)
        return -1

    def first_gt(self, start: int, threshold: float, end: int) -> int:
        return self._first(start, end, threshold, "gt")

    def first_ge(self, start: int, threshold: float, end: int) -> int:
        return self._first(start, end, threshold, "ge")

    def first_lt(self, start: int, threshold: float, end: int) -> int:
        return self._first(start, end, threshold, "lt")

    def first_le(self, start: int, threshold: float, end: int) -> int:
        return self._first(start, end, threshold, "le")


class OverlapFinder:
    def __init__(self, bid: np.ndarray, ask: np.ndarray, block: int = BLOCK):
        self.bid = np.asarray(bid, dtype=float)
        self.ask = np.asarray(ask, dtype=float)
        self.n = len(self.bid)
        self.block = int(block)
        nb = (self.n + self.block - 1) // self.block
        self.block_min_bid = np.empty(nb, dtype=float)
        self.block_max_ask = np.empty(nb, dtype=float)
        for b in range(nb):
            lo = b * self.block
            hi = min(self.n, lo + self.block)
            self.block_min_bid[b] = float(np.min(self.bid[lo:hi]))
            self.block_max_ask[b] = float(np.max(self.ask[lo:hi]))

    def first_overlap(self, start: int, end: int, low: float, high: float) -> int:
        start = max(0, int(start))
        end = min(self.n, int(end))
        if start >= end:
            return -1

        def local(lo: int, hi: int) -> int:
            x = (self.ask[lo:hi] >= low) & (self.bid[lo:hi] <= high)
            hit = np.flatnonzero(x)
            return lo + int(hit[0]) if len(hit) else -1

        first_block_end = min(end, ((start // self.block) + 1) * self.block)
        hit = local(start, first_block_end)
        if hit >= 0:
            return hit
        pos = first_block_end

        full_end = (end // self.block) * self.block
        if pos < full_end:
            b0 = pos // self.block
            b1 = full_end // self.block
            possible = (
                (self.block_max_ask[b0:b1] >= low)
                & (self.block_min_bid[b0:b1] <= high)
            )
            candidates = np.flatnonzero(possible)
            for off in candidates:
                b = b0 + int(off)
                lo = b * self.block
                hi = min(end, lo + self.block)
                hit = local(lo, hi)
                if hit >= 0:
                    return hit
            pos = full_end

        if pos < end:
            return local(pos, end)
        return -1


def _births_for_day(
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    baseline: np.ndarray,
    point: float,
    day: date,
) -> list[dict]:
    mid = (bid + ask) / 2.0
    spread = ask - bid

    expanded = np.isfinite(baseline) & (baseline > 0) & (spread > baseline)
    prev_expanded = np.r_[False, expanded[:-1]]
    actual_widening = np.r_[False, spread[1:] > spread[:-1] + EPS]
    starts = np.flatnonzero(expanded & ~prev_expanded & actual_widening)

    marks: list[dict] = []
    for seq, i_raw in enumerate(starts):
        i = int(i_raw)
        j = _ref_idx(ms, int(ms[i]) - 1000)
        delta_mid = float(mid[i] - mid[j]) if j >= 0 else np.nan
        if np.isfinite(delta_mid) and delta_mid > EPS:
            direction = 1
            direction_name = "UP"
        elif np.isfinite(delta_mid) and delta_mid < -EPS:
            direction = -1
            direction_name = "DOWN"
        else:
            direction = 0
            direction_name = "NEUTRAL"

        sig = _event_signature(ms, bid, ask, baseline, i, direction, point)
        birth_time = _ms_to_brt_naive(int(ms[i]))
        marks.append(
            {
                "mark_id": f"{day.isoformat()}:{seq:06d}:{int(ms[i])}",
                "birth_idx": i,
                "birth_time": birth_time,
                "birth_day": day,
                "direction": direction,
                "direction_name": direction_name,
                "mark_bid": float(bid[i]),
                "mark_mid": float(mid[i]),
                "mark_ask": float(ask[i]),
                "mark_width_points": float((ask[i] - bid[i]) / point),
                "birth_delta_mid_1s_points": (
                    float(delta_mid / point) if np.isfinite(delta_mid) else np.nan
                ),
                **{f"birth_{k}": v for k, v in sig.items()},
                "departure_idx": -1,
                "first_retest_idx": -1,
                "failure_idx": -1,
                "max_passes": 0,
                "lifecycle_status": "NEUTRAL" if direction == 0 else "BORN",
            }
        )
    return marks


def _append_pass(
    passes: list[dict],
    mark: dict,
    pass_no: int,
    pass_idx: int,
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    baseline: np.ndarray,
    point: float,
) -> int:
    sig = _event_signature(
        ms, bid, ask, baseline, pass_idx, int(mark["direction"]), point
    )
    row = {
        "mark_id": mark["mark_id"],
        "birth_day": mark["birth_day"],
        "direction": int(mark["direction"]),
        "direction_name": mark["direction_name"],
        "mark_bid": float(mark["mark_bid"]),
        "mark_mid": float(mark["mark_mid"]),
        "mark_ask": float(mark["mark_ask"]),
        "pass_no": int(pass_no),
        "pass_idx": int(pass_idx),
        "pass_time": _ms_to_brt_naive(int(ms[pass_idx])),
        "next_retest_idx": -1,
        **{f"pass_{k}": v for k, v in sig.items()},
    }
    passes.append(row)
    return len(passes) - 1


def _lifecycle_for_day(
    marks: list[dict],
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    baseline: np.ndarray,
    point: float,
) -> list[dict]:
    n = len(ms)
    bid_find = CrossFinder(bid)
    ask_find = CrossFinder(ask)
    passes: list[dict] = []

    for mark in marks:
        direction = int(mark["direction"])
        if direction == 0:
            continue

        birth = int(mark["birth_idx"])
        low = float(mark["mark_bid"])
        high = float(mark["mark_ask"])

        if direction > 0:
            dep = bid_find.first_gt(birth + 1, high, n)
        else:
            dep = ask_find.first_lt(birth + 1, low, n)

        if dep < 0:
            mark["lifecycle_status"] = "DAY_END_NO_DEPARTURE"
            continue

        mark["departure_idx"] = dep
        mark["lifecycle_status"] = "DEPARTED"
        pass_no = 1
        mark["max_passes"] = 1
        pass_row_idx = _append_pass(
            passes, mark, pass_no, dep, ms, bid, ask, baseline, point
        )
        current_pass_idx = dep

        while True:
            if direction > 0:
                ret = bid_find.first_le(current_pass_idx + 1, high, n)
            else:
                ret = ask_find.first_ge(current_pass_idx + 1, low, n)

            if ret < 0:
                mark["lifecycle_status"] = "DAY_END_AFTER_DEPARTURE"
                break

            passes[pass_row_idx]["next_retest_idx"] = ret
            if int(mark["first_retest_idx"]) < 0:
                mark["first_retest_idx"] = ret

            # A full loss can occur on the exact tick that first re-enters.
            if direction > 0 and ask[ret] < low:
                mark["failure_idx"] = ret
                mark["lifecycle_status"] = "FAILED"
                break
            if direction < 0 and bid[ret] > high:
                mark["failure_idx"] = ret
                mark["lifecycle_status"] = "FAILED"
                break

            if direction > 0:
                recross = bid_find.first_gt(ret + 1, high, n)
                failure = ask_find.first_lt(ret + 1, low, n)
            else:
                recross = ask_find.first_lt(ret + 1, low, n)
                failure = bid_find.first_gt(ret + 1, high, n)

            if failure >= 0 and (recross < 0 or failure < recross):
                mark["failure_idx"] = failure
                mark["lifecycle_status"] = "FAILED"
                break

            if recross < 0:
                mark["lifecycle_status"] = "DAY_END_IN_RETEST"
                break

            pass_no += 1
            mark["max_passes"] = pass_no
            pass_row_idx = _append_pass(
                passes, mark, pass_no, recross, ms, bid, ask, baseline, point
            )
            current_pass_idx = recross

        if int(mark["failure_idx"]) >= 0:
            fi = int(mark["failure_idx"])
            mark["failure_time"] = _ms_to_brt_naive(int(ms[fi]))
        else:
            mark["failure_time"] = pd.NaT

        if int(mark["departure_idx"]) >= 0:
            di = int(mark["departure_idx"])
            mark["departure_time"] = _ms_to_brt_naive(int(ms[di]))
            mark["departure_delay_ms"] = int(ms[di] - ms[birth])
        else:
            mark["departure_time"] = pd.NaT
            mark["departure_delay_ms"] = np.nan

        if int(mark["first_retest_idx"]) >= 0:
            ri = int(mark["first_retest_idx"])
            mark["first_retest_time"] = _ms_to_brt_naive(int(ms[ri]))
        else:
            mark["first_retest_time"] = pd.NaT

    return passes


def _label_passes(
    passes: list[dict],
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    point: float,
) -> None:
    mid = (bid + ask) / 2.0
    n = len(ms)

    for p in passes:
        i = int(p["pass_idx"])
        direction = int(p["direction"])
        t0 = int(ms[i])
        ret = int(p.get("next_retest_idx", -1))
        h_end = int(np.searchsorted(ms, t0 + 60_000, side="right"))

        if ret >= 0:
            end = min(h_end, ret)
            outcome_complete = True
        else:
            end = h_end
            outcome_complete = bool(h_end <= n and int(ms[-1]) >= t0 + 60_000)

        signed = direction * (mid[i:end] - mid[i]) / point
        p["outcome_complete_before_retest_60s"] = int(outcome_complete)
        if outcome_complete:
            p["mfe_60_points"] = float(np.max(signed)) if len(signed) else 0.0
            p["mae_60_points"] = (
                float(max(0.0, -np.min(signed))) if len(signed) else 0.0
            )
        else:
            p["mfe_60_points"] = np.nan
            p["mae_60_points"] = np.nan

        for target in TARGET_POINTS:
            if outcome_complete:
                p[f"hit_{target}_before_retest"] = int(
                    len(signed) > 0 and np.any(signed >= target)
                )
            else:
                p[f"hit_{target}_before_retest"] = np.nan

        for h in PASS_HORIZONS_S:
            target_ms = t0 + h * 1000
            j = int(np.searchsorted(ms, target_ms, side="right") - 1)
            if j < i:
                p[f"return_{h}s_points"] = np.nan
                continue
            if ret >= 0 and j >= ret:
                p[f"return_{h}s_points"] = np.nan
                continue
            if j >= n or int(ms[-1]) < target_ms:
                p[f"return_{h}s_points"] = np.nan
                continue
            p[f"return_{h}s_points"] = float(
                direction * (mid[j] - mid[i]) / point
            )


def _departure60_label(mark: dict, ms: np.ndarray) -> float:
    birth = int(mark["birth_idx"])
    dep = int(mark["departure_idx"])
    deadline = int(ms[birth]) + 60_000
    if dep >= 0 and int(ms[dep]) <= deadline:
        return 1.0
    if int(ms[-1]) >= deadline:
        return 0.0
    return np.nan


def _failure_paths_for_day(
    marks: list[dict],
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
) -> list[dict]:
    if not marks:
        return []

    birth_idx = np.array([int(m["birth_idx"]) for m in marks], dtype=int)
    lows = np.array([float(m["mark_bid"]) for m in marks], dtype=float)
    highs = np.array([float(m["mark_ask"]) for m in marks], dtype=float)
    directions = np.array([int(m["direction"]) for m in marks], dtype=int)
    ids = np.array([str(m["mark_id"]) for m in marks], dtype=object)
    n = len(ms)

    bid_find = CrossFinder(bid)
    ask_find = CrossFinder(ask)
    overlap_find = OverlapFinder(bid, ask)
    out: list[dict] = []

    for k, mark in enumerate(marks):
        fail = int(mark.get("failure_idx", -1))
        direction = int(mark["direction"])
        if fail < 0 or direction == 0:
            continue

        low = float(mark["mark_bid"])
        high = float(mark["mark_ask"])
        prior = birth_idx < fail
        prior[k] = False
        candidate_idx = -1

        if direction > 0:
            # UP mark failed; travel direction is DOWN.
            mask = prior & (highs < low)
            cand = np.flatnonzero(mask)
            if len(cand):
                best_price = np.max(highs[cand])
                tied = cand[np.isclose(highs[cand], best_price, atol=EPS, rtol=0.0)]
                candidate_idx = int(tied[np.argmax(birth_idx[tied])])
            reclaim = bid_find.first_gt(fail + 1, high, n)
            travel_direction = -1
        else:
            # DOWN mark failed; travel direction is UP.
            mask = prior & (lows > high)
            cand = np.flatnonzero(mask)
            if len(cand):
                best_price = np.min(lows[cand])
                tied = cand[np.isclose(lows[cand], best_price, atol=EPS, rtol=0.0)]
                candidate_idx = int(tied[np.argmax(birth_idx[tied])])
            reclaim = ask_find.first_lt(fail + 1, low, n)
            travel_direction = 1

        next_birth_pos = int(np.searchsorted(birth_idx, fail, side="right"))
        next_birth = (
            int(birth_idx[next_birth_pos]) if next_birth_pos < len(birth_idx) else -1
        )
        next_birth_mark = (
            int(next_birth_pos) if next_birth_pos < len(birth_idx) else -1
        )

        if candidate_idx >= 0:
            target_hit = overlap_find.first_overlap(
                fail + 1,
                n,
                float(lows[candidate_idx]),
                float(highs[candidate_idx]),
            )
        else:
            target_hit = -1

        events: list[tuple[int, str]] = []
        if target_hit >= 0:
            events.append((target_hit, "NEXT_PRIOR_MARK_HIT"))
        if reclaim >= 0:
            events.append((reclaim, "FAILED_MARK_RECLAIM"))
        if next_birth >= 0:
            events.append((next_birth, "NEW_FLOW_MARK_BIRTH"))

        if events:
            first_idx = min(x[0] for x in events)
            names = sorted(x[1] for x in events if x[0] == first_idx)
            first_event = "+".join(names)
            first_time = _ms_to_brt_naive(int(ms[first_idx]))
        else:
            first_idx = -1
            first_event = "DAY_END"
            first_time = pd.NaT

        eventually_prior_before_reclaim = (
            candidate_idx >= 0
            and target_hit >= 0
            and (reclaim < 0 or target_hit < reclaim)
        )

        new_dir = int(directions[next_birth_mark]) if next_birth_mark >= 0 else 0
        out.append(
            {
                "mark_id": mark["mark_id"],
                "birth_day": mark["birth_day"],
                "failed_direction": direction,
                "travel_direction_after_failure": travel_direction,
                "failure_idx": fail,
                "failure_time": _ms_to_brt_naive(int(ms[fail])),
                "candidate_prior_mark_id": (
                    ids[candidate_idx] if candidate_idx >= 0 else None
                ),
                "candidate_prior_mark_bid": (
                    float(lows[candidate_idx]) if candidate_idx >= 0 else np.nan
                ),
                "candidate_prior_mark_ask": (
                    float(highs[candidate_idx]) if candidate_idx >= 0 else np.nan
                ),
                "candidate_distance_points": (
                    float(
                        (low - highs[candidate_idx]) / EXPECTED_POINT
                        if direction > 0
                        else (lows[candidate_idx] - high) / EXPECTED_POINT
                    )
                    if candidate_idx >= 0
                    else np.nan
                ),
                "prior_mark_hit_idx": target_hit,
                "prior_mark_hit_time": (
                    _ms_to_brt_naive(int(ms[target_hit]))
                    if target_hit >= 0
                    else pd.NaT
                ),
                "failed_mark_reclaim_idx": reclaim,
                "failed_mark_reclaim_time": (
                    _ms_to_brt_naive(int(ms[reclaim])) if reclaim >= 0 else pd.NaT
                ),
                "next_flow_mark_idx": next_birth,
                "next_flow_mark_id": (
                    ids[next_birth_mark] if next_birth_mark >= 0 else None
                ),
                "next_flow_mark_direction": new_dir,
                "new_mark_matches_travel_direction": (
                    int(new_dir == travel_direction)
                    if next_birth_mark >= 0 and new_dir != 0
                    else np.nan
                ),
                "first_competing_event": first_event,
                "first_competing_event_idx": first_idx,
                "first_competing_event_time": first_time,
                "prior_mark_eventually_hit_before_reclaim": int(
                    eventually_prior_before_reclaim
                ),
            }
        )
    return out


def _add_chain_fields(marks: list[dict], point: float) -> None:
    directional = [m for m in marks if int(m["direction"]) != 0]
    run = 0
    prev: dict | None = None
    for m in directional:
        if prev is None:
            run = 1
            m["same_direction_run_length_at_birth"] = 1
            m["prev_directional_mark_id"] = None
            m["prev_mark_mid_distance_points"] = np.nan
            m["prev_mark_birth_delta_s"] = np.nan
        else:
            run = run + 1 if int(m["direction"]) == int(prev["direction"]) else 1
            m["same_direction_run_length_at_birth"] = run
            m["prev_directional_mark_id"] = prev["mark_id"]
            m["prev_mark_mid_distance_points"] = float(
                (float(m["mark_mid"]) - float(prev["mark_mid"])) / point
            )
            m["prev_mark_birth_delta_s"] = float(
                (
                    pd.Timestamp(m["birth_time"])
                    - pd.Timestamp(prev["birth_time"])
                ).total_seconds()
            )
        prev = m


def _paired_bootstrap(
    passes_df: pd.DataFrame,
    outcome: str,
) -> dict:
    p1 = passes_df.loc[
        passes_df["pass_no"].eq(1), ["mark_id", "birth_day", outcome]
    ].rename(columns={outcome: "p1"})
    p2 = passes_df.loc[
        passes_df["pass_no"].eq(2), ["mark_id", outcome]
    ].rename(columns={outcome: "p2"})
    q = p1.merge(p2, on="mark_id", how="inner").dropna(subset=["p1", "p2"])
    if q.empty:
        return {"n": 0, "days": 0, "p1": np.nan, "p2": np.nan, "diff": np.nan, "lo": np.nan, "hi": np.nan}

    q["diff"] = q["p2"].astype(float) - q["p1"].astype(float)
    day_arrays = [
        g["diff"].to_numpy(float) for _, g in q.groupby("birth_day", sort=True)
    ]
    days = len(day_arrays)
    if days < 2:
        lo = hi = np.nan
    else:
        rng = np.random.default_rng(BOOT_SEED)
        boot = np.empty(BOOT_N, dtype=float)
        for b in range(BOOT_N):
            idx = rng.integers(0, days, size=days)
            total = 0.0
            n = 0
            for j in idx:
                a = day_arrays[int(j)]
                total += float(a.sum())
                n += int(len(a))
            boot[b] = total / n
        lo, hi = np.quantile(boot, [0.025, 0.975])

    return {
        "n": int(len(q)),
        "days": int(days),
        "p1": float(q["p1"].mean()),
        "p2": float(q["p2"].mean()),
        "diff": float(q["diff"].mean()),
        "lo": float(lo) if np.isfinite(lo) else np.nan,
        "hi": float(hi) if np.isfinite(hi) else np.nan,
    }


def _quintile_map(
    df: pd.DataFrame,
    feature: str,
    outcome: str,
    stage: str,
) -> pd.DataFrame:
    q = df.dropna(subset=[feature, outcome]).copy()
    if len(q) < 10 or q[feature].nunique() < 5:
        return pd.DataFrame()
    try:
        q["bucket"] = pd.qcut(q[feature], 5, duplicates="drop")
    except ValueError:
        return pd.DataFrame()

    out = (
        q.groupby("bucket", observed=True)
        .agg(
            n=(outcome, "size"),
            rate=(outcome, "mean"),
            feature_mean=(feature, "mean"),
            feature_median=(feature, "median"),
        )
        .reset_index()
    )
    out["stage"] = stage
    out["feature"] = feature
    out["outcome"] = outcome
    out["bucket"] = out["bucket"].astype(str)
    return out[
        [
            "stage",
            "feature",
            "outcome",
            "bucket",
            "n",
            "rate",
            "feature_mean",
            "feature_median",
        ]
    ]


def _print_pass_rates(passes: pd.DataFrame) -> None:
    print()
    print("PASS CONTINUATION — BEFORE NEXT RETEST, COMPLETE 60s/RETEST WINDOWS ONLY")
    groups = [
        ("PASS1", passes.loc[passes["pass_no"].eq(1)]),
        ("PASS2", passes.loc[passes["pass_no"].eq(2)]),
        ("PASS3+", passes.loc[passes["pass_no"].ge(3)]),
    ]
    for name, z0 in groups:
        z = z0.loc[z0["outcome_complete_before_retest_60s"].eq(1)].copy()
        rates = " ".join(
            f"+{t}={100*z[f'hit_{t}_before_retest'].mean():6.2f}%"
            if len(z)
            else f"+{t}=NA"
            for t in TARGET_POINTS
        )
        mfe = float(z["mfe_60_points"].mean()) if len(z) else np.nan
        print(f"  {name:<6} n={len(z):>6} | {rates} | meanMFE60={mfe:.2f}")


def main() -> int:
    args = _parse_args()
    symbol = str(args.symbol).strip()
    start_day = pd.Timestamp(args.start).date()
    end_day = pd.Timestamp(args.end).date()
    if end_day < start_day:
        raise SystemExit("--end must be >= --start")

    print("=" * 132)
    print("MICROSTRUCTURE FLOW-MARK MAP 01 — CONTINUOUS GOLD BID/ASK PATH")
    print("=" * 132)
    print("Status             = HISTORICAL EXPLORATORY MAP / NO FORMAL PASS-FAIL")
    print(f"Symbol             = {symbol}")
    print(f"Historical window  = {start_day} through {end_day} BRT inclusive")
    print("Path scope         = FULL BRT DAY; state resets at BRT day boundary")
    print("Mark birth         = spread-baseline expansion episode onset + actual widening")
    print("Spread baseline    = median of prior 30 completed 1-second median spreads")
    print("Direction          = sign of causal 1-second MID migration")
    print("Mark geometry      = BID/ASK birth zone")
    print("Primary lifecycle  = BIRTH -> PASS1 -> RETEST -> PASS2+ / FAILURE")
    print("Failure path       = nearest earlier same-day mark vs reclaim vs new mark")
    print("M5/M15 levels      = NOT USED")
    print("Candle color       = NOT USED")
    print("Threshold fitting  = NONE")
    print("Exp27/Calibration  = UNTOUCHED / SCORES SEALED")
    print("Runtime promotion  = NONE")
    print()

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    all_marks: list[dict] = []
    all_passes: list[dict] = []
    all_failures: list[dict] = []
    coverage = Counter()

    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol_info({symbol}) returned None")
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")
        point = float(info.point)
        print(f"MT5 SYMBOL GUARD digits={info.digits} point={point:.8f}")
        if not math.isclose(point, EXPECTED_POINT, rel_tol=0.0, abs_tol=1e-12):
            raise RuntimeError(
                f"FLOWMARK01 point guard failed: expected {EXPECTED_POINT}, got {point}"
            )

        days = pd.date_range(start_day, end_day, freq="D")
        total_days = len(days)

        for day_no, dts in enumerate(days, start=1):
            d = dts.date()
            q_start = _brt_local(d, time(0, 0, 0))
            q_end = _brt_local(d + timedelta(days=1), time(0, 0, 0)) - timedelta(
                milliseconds=1
            )
            raw = mt5.copy_ticks_range(
                symbol, _to_utc(q_start), _to_utc(q_end), mt5.COPY_TICKS_ALL
            )
            ticks = _valid_ticks(raw)
            if len(ticks) < 2:
                coverage["NO_TICK_DAY"] += 1
                if day_no == 1 or day_no % 10 == 0 or day_no == total_days:
                    print(
                        f"SCAN {day_no:>3}/{total_days} {d} ticks={len(ticks):>7} "
                        f"marks={len(all_marks):>7} passes={len(all_passes):>7}"
                    )
                continue

            coverage["DAYS_WITH_TICKS"] += 1
            coverage["VALID_TICKS"] += int(len(ticks))
            ms = ticks["time_msc"].astype(np.int64)
            bid = ticks["bid"].astype(float)
            ask = ticks["ask"].astype(float)
            baseline = _spread_baseline_by_tick(ms, ask - bid)

            marks = _births_for_day(ms, bid, ask, baseline, point, d)
            _add_chain_fields(marks, point)
            passes = _lifecycle_for_day(marks, ms, bid, ask, baseline, point)
            _label_passes(passes, ms, bid, ask, point)

            for m in marks:
                m["departure_within_60s"] = _departure60_label(m, ms)

            failures = _failure_paths_for_day(marks, ms, bid, ask)

            all_marks.extend(marks)
            all_passes.extend(passes)
            all_failures.extend(failures)

            coverage["BIRTHS"] += len(marks)
            coverage["PASSES"] += len(passes)
            coverage["FAILURES"] += len(failures)

            if day_no == 1 or day_no % 10 == 0 or day_no == total_days:
                print(
                    f"SCAN {day_no:>3}/{total_days} {d} ticks={len(ticks):>7} "
                    f"day_marks={len(marks):>6} day_passes={len(passes):>6} "
                    f"total_marks={len(all_marks):>7}"
                )
    finally:
        mt5.shutdown()

    if not all_marks:
        print()
        print("No FLOW MARK births produced.")
        print(dict(coverage))
        print("MICROSTRUCTURE_FLOW_MARK_MAP01 = COMPLETE_EXPLORATORY_MAP_EMPTY")
        return 0

    marks = pd.DataFrame(all_marks).sort_values("birth_time").reset_index(drop=True)
    passes = (
        pd.DataFrame(all_passes).sort_values("pass_time").reset_index(drop=True)
        if all_passes
        else pd.DataFrame()
    )
    failures = (
        pd.DataFrame(all_failures).sort_values("failure_time").reset_index(drop=True)
        if all_failures
        else pd.DataFrame()
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    marks_path = OUT_DIR / "FLOWMARK_map01_marks.csv"
    passes_path = OUT_DIR / "FLOWMARK_map01_passes.csv"
    failures_path = OUT_DIR / "FLOWMARK_map01_failures.csv"
    quintiles_path = OUT_DIR / "FLOWMARK_map01_feature_quintiles.csv"

    marks.to_csv(marks_path, index=False)
    passes.to_csv(passes_path, index=False)
    failures.to_csv(failures_path, index=False)

    print()
    print("=" * 132)
    print("FLOW-MARK MAP01 UNIVERSE")
    print("=" * 132)
    print(f"days_with_ticks = {coverage['DAYS_WITH_TICKS']}")
    print(f"days_no_ticks   = {coverage['NO_TICK_DAY']}")
    print(f"valid_ticks     = {coverage['VALID_TICKS']}")
    print(f"marks           = {len(marks)}")
    print(f"passes          = {len(passes)}")
    print(f"failures        = {len(failures)}")
    print()
    print("BIRTH DIRECTION")
    print(marks["direction_name"].value_counts(dropna=False).to_string())

    directional = marks.loc[marks["direction"].ne(0)].copy()
    dep = directional["departure_idx"].ge(0)
    ret = directional["first_retest_idx"].ge(0)
    fail = directional["failure_idx"].ge(0)
    print()
    print("LIFECYCLE")
    print(f"  directional marks = {len(directional)}")
    print(f"  departed          = {int(dep.sum())} ({100*dep.mean():.2f}%)")
    print(f"  retested          = {int(ret.sum())} ({100*ret.mean():.2f}%)")
    print(f"  failed            = {int(fail.sum())} ({100*fail.mean():.2f}%)")
    d60 = directional["departure_within_60s"].dropna()
    print(
        f"  PASS1 <=60s      = {100*d60.mean():.2f}% "
        f"(n_complete={len(d60)})"
    )

    if not passes.empty:
        print()
        print("PASS COUNTS")
        print(f"  PASS1 = {int(passes['pass_no'].eq(1).sum())}")
        print(f"  PASS2 = {int(passes['pass_no'].eq(2).sum())}")
        print(f"  PASS3 = {int(passes['pass_no'].eq(3).sum())}")
        print(f"  PASS4+ = {int(passes['pass_no'].ge(4).sum())}")
        _print_pass_rates(passes)

        print()
        print("MATCHED SAME-MARK PASS2 - PASS1 — WHOLE-BRT-DAY BOOTSTRAP")
        for target in TARGET_POINTS:
            outcome = f"hit_{target}_before_retest"
            r = _paired_bootstrap(passes, outcome)
            print(
                f"  +{target:<3} n={r['n']:>5} days={r['days']:>3} "
                f"PASS1={100*r['p1']:6.2f}% PASS2={100*r['p2']:6.2f}% "
                f"diff={100*r['diff']:+6.2f}pp "
                f"CI95=[{100*r['lo']:+6.2f},{100*r['hi']:+6.2f}]pp"
            )

        r = _paired_bootstrap(passes, "mfe_60_points")
        print(
            f"  MFE60 n={r['n']:>5} days={r['days']:>3} "
            f"PASS1={r['p1']:.2f} PASS2={r['p2']:.2f} "
            f"diff={r['diff']:+.2f} points "
            f"CI95=[{r['lo']:+.2f},{r['hi']:+.2f}]"
        )

    if not failures.empty:
        print()
        print("FAILURE -> NEXT DESTINATION")
        print("  first competing event:")
        print(failures["first_competing_event"].value_counts(dropna=False).to_string())
        cand = failures["candidate_prior_mark_id"].notna()
        if cand.any():
            z = failures.loc[cand]
            print(
                f"  has prior mark candidate = {int(cand.sum())}/{len(failures)}"
            )
            print(
                "  prior mark eventually hit before failed-mark reclaim = "
                f"{100*z['prior_mark_eventually_hit_before_reclaim'].mean():.2f}%"
            )
        nm = failures["next_flow_mark_id"].notna()
        if nm.any():
            x = failures.loc[nm, "new_mark_matches_travel_direction"].dropna()
            if len(x):
                print(
                    "  next new mark matches failure travel direction = "
                    f"{100*x.mean():.2f}% (n={len(x)})"
                )

    maps: list[pd.DataFrame] = []
    for feat in MAP_FEATURES:
        birth_col = f"birth_{feat}"
        if birth_col in marks.columns:
            m = _quintile_map(
                directional,
                birth_col,
                "departure_within_60s",
                "BIRTH_TO_PASS1_60S",
            )
            if not m.empty:
                maps.append(m)
        pass_col = f"pass_{feat}"
        if not passes.empty and pass_col in passes.columns:
            m = _quintile_map(
                passes.loc[passes["outcome_complete_before_retest_60s"].eq(1)],
                pass_col,
                "hit_200_before_retest",
                "PASS_TO_HIT200_BEFORE_RETEST",
            )
            if not m.empty:
                maps.append(m)

    if maps:
        qmap = pd.concat(maps, ignore_index=True)
        qmap.to_csv(quintiles_path, index=False)
        print()
        print("DESCRIPTIVE FEATURE QUINTILES")
        for (stage, feature), g in qmap.groupby(["stage", "feature"], sort=False):
            print()
            print(f"{stage} | {feature}")
            print(
                g[["bucket", "n", "rate", "feature_mean"]].to_string(
                    index=False, float_format=lambda x: f"{x:.5f}"
                )
            )

    print()
    print("CHAIN DESCRIPTIVES")
    dr = directional["same_direction_run_length_at_birth"].dropna()
    print(
        f"  same-direction run length mean={dr.mean():.3f} "
        f"median={dr.median():.3f} max={dr.max():.0f}"
    )
    dist = directional["prev_mark_mid_distance_points"].dropna()
    if len(dist):
        print(
            f"  consecutive directional mark distance points "
            f"mean={dist.mean():+.2f} median={dist.median():+.2f}"
        )

    print()
    print("OUTPUTS")
    print(f"  marks    = {marks_path}")
    print(f"  passes   = {passes_path}")
    print(f"  failures = {failures_path}")
    if maps:
        print(f"  quintiles= {quintiles_path}")

    print()
    print("MICROSTRUCTURE_FLOW_MARK_MAP01 = COMPLETE_EXPLORATORY_MAP")
    print("NO THRESHOLD / BEST-BUCKET / PASS-NUMBER PROMOTION IS AUTHORIZED BY MAP01")
    print("NEXT STEP = FREEZE ONE FLOW-MARK FINGERPRINT AS MAP02 ONLY AFTER MAP01 INSPECTION")
    print("EXP27 = UNTOUCHED / SCORES SEALED")
    print("CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
