#!/usr/bin/env python3
"""MICROSTRUCTURE FLOW-MARK MAP 01R — debounced PEAK-zone lifecycle replay.

Scientific contract:
    docs/MICROSTRUCTURE_FLOW_MARK_MAP01R.md

Key guards:
- FLOW EPISODE grouping is the accepted 01R one-quiet-second debounce.
- Primary mark geometry is PEAK-SPREAD [bid, ask].
- Peak mark becomes causal only at episode_close_time.
- BIRTH geometry is descriptive only in this replay.
- No M5/M15 level, candle color, fitted threshold, Exp27/Calibration score, or runtime promotion.
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
BRT = ZoneInfo("America/Sao_Paulo")

SYMBOL_DEFAULT = "GOLD"
DEFAULT_START = "2026-02-01"
DEFAULT_END = "2026-08-12"
EXPECTED_POINT = 0.01
BASELINE_SECONDS = 30
PASS_HORIZONS_S = (1, 2, 5, 10, 15, 30, 60)
TARGET_POINTS = (50, 100, 200, 300)
BOOT_N = 5000
BOOT_SEED = 2026081705
EPS = 1e-12


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Frozen Microstructure Flow-Mark Map 01R")
    p.add_argument("--symbol", default=SYMBOL_DEFAULT)
    p.add_argument("--start", default=DEFAULT_START, help="BRT YYYY-MM-DD inclusive")
    p.add_argument("--end", default=DEFAULT_END, help="BRT YYYY-MM-DD inclusive")
    return p.parse_args()


def phase(day_no: int, total: int, day: date, text: str) -> None:
    print(f"DAY {day_no:>3}/{total} {day} | {text}", flush=True)


def brt_local(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=BRT)


def to_utc(d: datetime) -> datetime:
    return d.astimezone(timezone.utc)


def ms_to_brt(ms: int) -> pd.Timestamp:
    return pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert(BRT).tz_localize(None)


def valid_ticks(raw: np.ndarray | None) -> np.ndarray:
    if raw is None or len(raw) == 0:
        return np.empty(
            0,
            dtype=[("time_msc", "<i8"), ("bid", "<f8"), ("ask", "<f8"), ("flags", "<u4")],
        )
    names = set(raw.dtype.names or ())
    missing = sorted({"time_msc", "bid", "ask", "flags"} - names)
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
    sec = (ms // 1000).astype(np.int64)
    s = pd.DataFrame({"sec": sec, "spread": spread}).groupby(
        "sec", sort=True, observed=True
    )["spread"].median()
    first_sec = int(s.index.min())
    last_sec = int(s.index.max())
    full = s.reindex(np.arange(first_sec, last_sec + 1, dtype=np.int64))
    base = (
        full.rolling(BASELINE_SECONDS, min_periods=BASELINE_SECONDS)
        .median()
        .shift(1)
    )
    vals = base.to_numpy(float)
    return vals[(sec - first_sec).astype(np.int64)]


def ref_idx(ms: np.ndarray, target_ms: int) -> int:
    return int(np.searchsorted(ms, target_ms, side="right") - 1)


def event_signature(
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
    out = {
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
        j = ref_idx(ms, t0 - window_ms)
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
    return out


class RangeFinder:
    """Segment-tree first-cross search in O(log N) typical per event."""

    def __init__(self, arr: np.ndarray):
        self.arr = np.asarray(arr, dtype=float)
        self.n = len(self.arr)
        size = 1
        while size < self.n:
            size <<= 1
        self.size = size
        self.max_tree = np.full(2 * size, -np.inf, dtype=float)
        self.min_tree = np.full(2 * size, np.inf, dtype=float)
        self.max_tree[size : size + self.n] = self.arr
        self.min_tree[size : size + self.n] = self.arr
        for node in range(size - 1, 0, -1):
            self.max_tree[node] = max(self.max_tree[node * 2], self.max_tree[node * 2 + 1])
            self.min_tree[node] = min(self.min_tree[node * 2], self.min_tree[node * 2 + 1])

    def _possible(self, node: int, threshold: float, mode: str) -> bool:
        if mode == "gt":
            return self.max_tree[node] > threshold
        if mode == "ge":
            return self.max_tree[node] >= threshold
        if mode == "lt":
            return self.min_tree[node] < threshold
        if mode == "le":
            return self.min_tree[node] <= threshold
        raise ValueError(mode)

    def _first_rec(
        self, node: int, left: int, right: int, start: int, threshold: float, mode: str
    ) -> int:
        if right <= start or not self._possible(node, threshold, mode):
            return -1
        if right - left == 1:
            return left if left < self.n else -1
        mid = (left + right) // 2
        hit = self._first_rec(node * 2, left, mid, start, threshold, mode)
        if hit >= 0:
            return hit
        return self._first_rec(node * 2 + 1, mid, right, start, threshold, mode)

    def first(self, start: int, threshold: float, mode: str) -> int:
        if start >= self.n:
            return -1
        return self._first_rec(1, 0, self.size, max(0, int(start)), float(threshold), mode)

    def first_gt(self, start: int, threshold: float) -> int:
        return self.first(start, threshold, "gt")

    def first_ge(self, start: int, threshold: float) -> int:
        return self.first(start, threshold, "ge")

    def first_lt(self, start: int, threshold: float) -> int:
        return self.first(start, threshold, "lt")

    def first_le(self, start: int, threshold: float) -> int:
        return self.first(start, threshold, "le")


class OverlapFinder:
    """First quote overlap with zone [low, high], using segment pruning."""

    def __init__(self, bid: np.ndarray, ask: np.ndarray):
        self.bid = np.asarray(bid, dtype=float)
        self.ask = np.asarray(ask, dtype=float)
        self.n = len(self.bid)
        size = 1
        while size < self.n:
            size <<= 1
        self.size = size
        self.min_bid = np.full(2 * size, np.inf, dtype=float)
        self.max_ask = np.full(2 * size, -np.inf, dtype=float)
        self.min_bid[size : size + self.n] = self.bid
        self.max_ask[size : size + self.n] = self.ask
        for node in range(size - 1, 0, -1):
            self.min_bid[node] = min(self.min_bid[node * 2], self.min_bid[node * 2 + 1])
            self.max_ask[node] = max(self.max_ask[node * 2], self.max_ask[node * 2 + 1])

    def _first_rec(
        self, node: int, left: int, right: int, start: int, low: float, high: float
    ) -> int:
        if right <= start:
            return -1
        if self.max_ask[node] < low or self.min_bid[node] > high:
            return -1
        if right - left == 1:
            if left >= self.n:
                return -1
            return left if (self.ask[left] >= low and self.bid[left] <= high) else -1
        mid = (left + right) // 2
        hit = self._first_rec(node * 2, left, mid, start, low, high)
        if hit >= 0:
            return hit
        return self._first_rec(node * 2 + 1, mid, right, start, low, high)

    def first_overlap(self, start: int, low: float, high: float) -> int:
        return self._first_rec(1, 0, self.size, max(0, int(start)), float(low), float(high))


class FenwickActive:
    def __init__(self, n: int):
        self.n = int(n)
        self.bit = np.zeros(self.n + 1, dtype=np.int64)

    def add(self, index: int) -> None:
        i = int(index) + 1
        while i <= self.n:
            self.bit[i] += 1
            i += i & -i

    def prefix(self, end_exclusive: int) -> int:
        i = min(self.n, max(0, int(end_exclusive)))
        total = 0
        while i > 0:
            total += int(self.bit[i])
            i -= i & -i
        return total

    def kth(self, k: int) -> int:
        total = self.prefix(self.n)
        if k <= 0 or k > total:
            return -1
        idx = 0
        bitmask = 1 << (self.n.bit_length() - 1)
        target = int(k)
        while bitmask:
            nxt = idx + bitmask
            if nxt <= self.n and int(self.bit[nxt]) < target:
                idx = nxt
                target -= int(self.bit[nxt])
            bitmask >>= 1
        return idx

    def predecessor(self, max_index: int) -> int:
        if max_index < 0:
            return -1
        cnt = self.prefix(min(self.n, int(max_index) + 1))
        return self.kth(cnt) if cnt > 0 else -1

    def successor(self, min_index: int) -> int:
        if min_index >= self.n:
            return -1
        before = self.prefix(max(0, int(min_index)))
        total = self.prefix(self.n)
        return self.kth(before + 1) if total > before else -1


def episodes_for_day(
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    baseline: np.ndarray,
    point: float,
    day: date,
) -> list[dict]:
    mid = (bid + ask) / 2.0
    spread = ask - bid
    available = np.isfinite(baseline) & (baseline > 0)
    expanded = available & (spread > baseline)
    widening = np.r_[False, spread[1:] > spread[:-1] + EPS]
    qualify = expanded & widening
    qi = np.flatnonzero(qualify)
    if not len(qi):
        return []

    qsec = (ms[qi] // 1000).astype(np.int64)
    starts = np.r_[0, np.flatnonzero(np.diff(qsec) > 1) + 1]
    ends = np.r_[starts[1:], len(qi)]
    day_end_ms = int(
        (brt_local(day + timedelta(days=1), time(0, 0)) - timedelta(milliseconds=1)).timestamp()
        * 1000
    )

    out: list[dict] = []
    for seq, (a, b) in enumerate(zip(starts, ends)):
        members = qi[int(a) : int(b)]
        birth_i = int(members[0])
        last_i = int(members[-1])
        peak_i = int(members[int(np.argmax(spread[members]))])
        last_sec = int(ms[last_i] // 1000)
        quiet_close_ms = (last_sec + 2) * 1000 - 1
        close_reason = "QUIET_SECOND" if quiet_close_ms <= day_end_ms else "DAY_END"
        close_ms = min(quiet_close_ms, day_end_ms)
        activation_idx = (
            int(np.searchsorted(ms, close_ms, side="right"))
            if close_reason == "QUIET_SECOND"
            else -1
        )
        if activation_idx >= len(ms):
            activation_idx = -1

        j = ref_idx(ms, int(ms[birth_i]) - 1000)
        delta_mid = float(mid[birth_i] - mid[j]) if j >= 0 else np.nan
        if np.isfinite(delta_mid) and delta_mid > EPS:
            direction, direction_name = 1, "UP"
        elif np.isfinite(delta_mid) and delta_mid < -EPS:
            direction, direction_name = -1, "DOWN"
        else:
            direction, direction_name = 0, "NEUTRAL"

        birth_sig = event_signature(ms, bid, ask, baseline, birth_i, direction, point)
        peak_sig = event_signature(ms, bid, ask, baseline, peak_i, direction, point)

        out.append(
            {
                "mark_id": f"{day.isoformat()}:{seq:06d}:{int(ms[birth_i])}",
                "birth_day": day,
                "birth_idx": birth_i,
                "peak_idx": peak_i,
                "last_qualifying_idx": last_i,
                "activation_idx": activation_idx,
                "birth_time": ms_to_brt(int(ms[birth_i])),
                "peak_time": ms_to_brt(int(ms[peak_i])),
                "last_qualifying_time": ms_to_brt(int(ms[last_i])),
                "episode_close_time": ms_to_brt(int(close_ms)),
                "close_reason": close_reason,
                "direction": direction,
                "direction_name": direction_name,
                "qualifying_ticks": int(len(members)),
                "duration_birth_to_last_ms": int(ms[last_i] - ms[birth_i]),
                "birth_bid": float(bid[birth_i]),
                "birth_mid": float(mid[birth_i]),
                "birth_ask": float(ask[birth_i]),
                "peak_bid": float(bid[peak_i]),
                "peak_mid": float(mid[peak_i]),
                "peak_ask": float(ask[peak_i]),
                "peak_spread": float(spread[peak_i]),
                "peak_spread_ratio": (
                    float(spread[peak_i] / baseline[peak_i])
                    if np.isfinite(baseline[peak_i]) and baseline[peak_i] > 0
                    else np.nan
                ),
                "mark_bid": float(bid[peak_i]),
                "mark_mid": float(mid[peak_i]),
                "mark_ask": float(ask[peak_i]),
                **{f"birth_{k}": v for k, v in birth_sig.items()},
                **{f"peak_{k}": v for k, v in peak_sig.items()},
                "departure_idx": -1,
                "first_retest_idx": -1,
                "failure_idx": -1,
                "max_passes": 0,
                "lifecycle_status": (
                    "NEUTRAL"
                    if direction == 0
                    else "DAY_END_NO_ACTIVATION"
                    if activation_idx < 0
                    else "ACTIVE"
                ),
            }
        )
    return out


def append_pass(
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
    sig = event_signature(ms, bid, ask, baseline, pass_idx, int(mark["direction"]), point)
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
        "pass_time": ms_to_brt(int(ms[pass_idx])),
        "next_retest_idx": -1,
        **{f"pass_{k}": v for k, v in sig.items()},
    }
    passes.append(row)
    return len(passes) - 1


def lifecycle_for_day(
    marks: list[dict],
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    baseline: np.ndarray,
    point: float,
) -> list[dict]:
    bid_find = RangeFinder(bid)
    ask_find = RangeFinder(ask)
    passes: list[dict] = []

    for mark in marks:
        direction = int(mark["direction"])
        activation = int(mark["activation_idx"])
        if direction == 0 or activation < 0:
            continue
        low = float(mark["mark_bid"])
        high = float(mark["mark_ask"])
        dep = (
            bid_find.first_gt(activation, high)
            if direction > 0
            else ask_find.first_lt(activation, low)
        )
        if dep < 0:
            mark["lifecycle_status"] = "DAY_END_NO_DEPARTURE"
            continue

        mark["departure_idx"] = dep
        mark["lifecycle_status"] = "DEPARTED"
        pass_no = 1
        mark["max_passes"] = 1
        pass_row_idx = append_pass(
            passes, mark, pass_no, dep, ms, bid, ask, baseline, point
        )
        current_pass_idx = dep

        while True:
            ret = (
                bid_find.first_le(current_pass_idx + 1, high)
                if direction > 0
                else ask_find.first_ge(current_pass_idx + 1, low)
            )
            if ret < 0:
                mark["lifecycle_status"] = "DAY_END_AFTER_DEPARTURE"
                break

            passes[pass_row_idx]["next_retest_idx"] = ret
            if int(mark["first_retest_idx"]) < 0:
                mark["first_retest_idx"] = ret

            if direction > 0 and ask[ret] < low:
                mark["failure_idx"] = ret
                mark["lifecycle_status"] = "FAILED"
                break
            if direction < 0 and bid[ret] > high:
                mark["failure_idx"] = ret
                mark["lifecycle_status"] = "FAILED"
                break

            if direction > 0:
                recross = bid_find.first_gt(ret + 1, high)
                failure = ask_find.first_lt(ret + 1, low)
            else:
                recross = ask_find.first_lt(ret + 1, low)
                failure = bid_find.first_gt(ret + 1, high)

            if failure >= 0 and (recross < 0 or failure < recross):
                mark["failure_idx"] = failure
                mark["lifecycle_status"] = "FAILED"
                break
            if recross < 0:
                mark["lifecycle_status"] = "DAY_END_IN_RETEST"
                break

            pass_no += 1
            mark["max_passes"] = pass_no
            pass_row_idx = append_pass(
                passes, mark, pass_no, recross, ms, bid, ask, baseline, point
            )
            current_pass_idx = recross

        mark["departure_time"] = (
            ms_to_brt(int(ms[int(mark["departure_idx"])]))
            if int(mark["departure_idx"]) >= 0
            else pd.NaT
        )
        mark["first_retest_time"] = (
            ms_to_brt(int(ms[int(mark["first_retest_idx"])]))
            if int(mark["first_retest_idx"]) >= 0
            else pd.NaT
        )
        mark["failure_time"] = (
            ms_to_brt(int(ms[int(mark["failure_idx"])]))
            if int(mark["failure_idx"]) >= 0
            else pd.NaT
        )
    return passes


def label_passes(
    passes: list[dict],
    ms: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    point: float,
) -> None:
    mid = (bid + ask) / 2.0
    for p in passes:
        i = int(p["pass_idx"])
        direction = int(p["direction"])
        t0 = int(ms[i])
        ret = int(p.get("next_retest_idx", -1))
        h_end = int(np.searchsorted(ms, t0 + 60_000, side="right"))
        if ret >= 0:
            end = min(h_end, ret)
            complete = True
        else:
            end = h_end
            complete = bool(int(ms[-1]) >= t0 + 60_000)
        signed = direction * (mid[i:end] - mid[i]) / point
        p["outcome_complete_before_retest_60s"] = int(complete)
        p["mfe_60_points"] = float(np.max(signed)) if complete and len(signed) else (0.0 if complete else np.nan)
        p["mae_60_points"] = (
            float(max(0.0, -np.min(signed))) if complete and len(signed) else (0.0 if complete else np.nan)
        )
        for target in TARGET_POINTS:
            p[f"hit_{target}_before_retest"] = (
                int(len(signed) > 0 and np.any(signed >= target)) if complete else np.nan
            )
        for h in PASS_HORIZONS_S:
            target_ms = t0 + h * 1000
            j = int(np.searchsorted(ms, target_ms, side="right") - 1)
            if j < i or (ret >= 0 and j >= ret) or int(ms[-1]) < target_ms:
                p[f"return_{h}s_points"] = np.nan
            else:
                p[f"return_{h}s_points"] = float(direction * (mid[j] - mid[i]) / point)


def add_activation60(mark: dict, ms: np.ndarray) -> None:
    activation = int(mark["activation_idx"])
    dep = int(mark["departure_idx"])
    if activation < 0:
        mark["pass1_within_60s_from_activation"] = np.nan
        return
    deadline = int(ms[activation]) + 60_000
    if dep >= 0 and int(ms[dep]) <= deadline:
        mark["pass1_within_60s_from_activation"] = 1.0
    elif int(ms[-1]) >= deadline:
        mark["pass1_within_60s_from_activation"] = 0.0
    else:
        mark["pass1_within_60s_from_activation"] = np.nan


def failure_candidate_indexed(failed: np.ndarray, marks: list[dict]) -> dict[int, int]:
    if not len(failed):
        return {}
    activation = np.array([int(m["activation_idx"]) for m in marks], dtype=np.int64)
    lows = np.array([float(m["mark_bid"]) for m in marks], dtype=float)
    highs = np.array([float(m["mark_ask"]) for m in marks], dtype=float)
    directions = np.array([int(m["direction"]) for m in marks], dtype=np.int8)
    failures = np.array([int(marks[k]["failure_idx"]) for k in failed], dtype=np.int64)

    eligible = np.flatnonzero(activation >= 0)
    order_act = eligible[np.argsort(activation[eligible], kind="stable")]
    order_fail = failed[np.argsort(failures, kind="stable")]

    high_values = np.unique(highs[eligible]) if len(eligible) else np.array([], dtype=float)
    low_values = np.unique(lows[eligible]) if len(eligible) else np.array([], dtype=float)
    if not len(high_values) or not len(low_values):
        return {int(k): -1 for k in failed}

    high_tree = FenwickActive(len(high_values))
    low_tree = FenwickActive(len(low_values))
    latest_high = np.full(len(high_values), -1, dtype=np.int64)
    latest_low = np.full(len(low_values), -1, dtype=np.int64)
    active_high = np.zeros(len(high_values), dtype=bool)
    active_low = np.zeros(len(low_values), dtype=bool)

    result: dict[int, int] = {}
    p = 0
    for k_raw in order_fail:
        k = int(k_raw)
        fail = int(marks[k]["failure_idx"])
        while p < len(order_act) and int(activation[order_act[p]]) < fail:
            idx = int(order_act[p])
            hc = int(np.searchsorted(high_values, highs[idx]))
            lc = int(np.searchsorted(low_values, lows[idx]))
            if not active_high[hc]:
                high_tree.add(hc)
                active_high[hc] = True
            if not active_low[lc]:
                low_tree.add(lc)
                active_low[lc] = True
            latest_high[hc] = idx
            latest_low[lc] = idx
            p += 1

        if directions[k] > 0:
            pos = int(np.searchsorted(high_values, lows[k], side="left") - 1)
            coord = high_tree.predecessor(pos)
            result[k] = int(latest_high[coord]) if coord >= 0 else -1
        else:
            pos = int(np.searchsorted(low_values, highs[k], side="right"))
            coord = low_tree.successor(pos)
            result[k] = int(latest_low[coord]) if coord >= 0 else -1
    return result


def failure_paths_for_day(
    marks: list[dict], ms: np.ndarray, bid: np.ndarray, ask: np.ndarray
) -> list[dict]:
    failed = np.array(
        [
            i
            for i, m in enumerate(marks)
            if int(m.get("failure_idx", -1)) >= 0 and int(m["direction"]) != 0
        ],
        dtype=int,
    )
    if not len(failed):
        return []

    birth_idx = np.array([int(m["birth_idx"]) for m in marks], dtype=np.int64)
    lows = np.array([float(m["mark_bid"]) for m in marks], dtype=float)
    highs = np.array([float(m["mark_ask"]) for m in marks], dtype=float)
    directions = np.array([int(m["direction"]) for m in marks], dtype=int)
    ids = np.array([str(m["mark_id"]) for m in marks], dtype=object)

    candidate = failure_candidate_indexed(failed, marks)
    bid_find = RangeFinder(bid)
    ask_find = RangeFinder(ask)
    overlap = OverlapFinder(bid, ask)
    out: list[dict] = []

    for k_raw in failed:
        k = int(k_raw)
        mark = marks[k]
        fail = int(mark["failure_idx"])
        direction = int(mark["direction"])
        low = float(mark["mark_bid"])
        high = float(mark["mark_ask"])
        cand = int(candidate.get(k, -1))

        if direction > 0:
            reclaim = bid_find.first_gt(fail + 1, high)
            travel_direction = -1
        else:
            reclaim = ask_find.first_lt(fail + 1, low)
            travel_direction = 1

        next_birth_pos = int(np.searchsorted(birth_idx, fail, side="right"))
        next_birth = (
            int(birth_idx[next_birth_pos]) if next_birth_pos < len(birth_idx) else -1
        )
        next_birth_mark = next_birth_pos if next_birth_pos < len(birth_idx) else -1
        target_hit = (
            overlap.first_overlap(fail + 1, float(lows[cand]), float(highs[cand]))
            if cand >= 0
            else -1
        )

        events: list[tuple[int, str]] = []
        if target_hit >= 0:
            events.append((target_hit, "NEXT_PRIOR_MARK_HIT"))
        if reclaim >= 0:
            events.append((reclaim, "FAILED_MARK_RECLAIM"))
        if next_birth >= 0:
            events.append((next_birth, "NEW_FLOW_EPISODE_BIRTH"))

        if events:
            first_idx = min(x[0] for x in events)
            first_event = "+".join(sorted(x[1] for x in events if x[0] == first_idx))
            first_time = ms_to_brt(int(ms[first_idx]))
        else:
            first_idx = -1
            first_event = "DAY_END"
            first_time = pd.NaT

        new_dir = int(directions[next_birth_mark]) if next_birth_mark >= 0 else 0
        out.append(
            {
                "mark_id": mark["mark_id"],
                "birth_day": mark["birth_day"],
                "failed_direction": direction,
                "travel_direction_after_failure": travel_direction,
                "failure_idx": fail,
                "failure_time": ms_to_brt(int(ms[fail])),
                "candidate_prior_mark_id": ids[cand] if cand >= 0 else None,
                "candidate_prior_mark_bid": float(lows[cand]) if cand >= 0 else np.nan,
                "candidate_prior_mark_ask": float(highs[cand]) if cand >= 0 else np.nan,
                "candidate_distance_points": (
                    float((low - highs[cand]) / EXPECTED_POINT)
                    if cand >= 0 and direction > 0
                    else float((lows[cand] - high) / EXPECTED_POINT)
                    if cand >= 0
                    else np.nan
                ),
                "prior_mark_hit_idx": target_hit,
                "prior_mark_hit_time": ms_to_brt(int(ms[target_hit])) if target_hit >= 0 else pd.NaT,
                "failed_mark_reclaim_idx": reclaim,
                "failed_mark_reclaim_time": ms_to_brt(int(ms[reclaim])) if reclaim >= 0 else pd.NaT,
                "next_flow_episode_birth_idx": next_birth,
                "next_flow_episode_id": ids[next_birth_mark] if next_birth_mark >= 0 else None,
                "next_flow_episode_direction": new_dir,
                "new_episode_matches_travel_direction": (
                    int(new_dir == travel_direction)
                    if next_birth_mark >= 0 and new_dir != 0
                    else np.nan
                ),
                "first_competing_event": first_event,
                "first_competing_event_idx": first_idx,
                "first_competing_event_time": first_time,
                "prior_mark_eventually_hit_before_reclaim": int(
                    cand >= 0 and target_hit >= 0 and (reclaim < 0 or target_hit < reclaim)
                ),
            }
        )
    return out


def paired_bootstrap(passes: pd.DataFrame, outcome: str) -> dict:
    p1 = passes.loc[
        passes["pass_no"].eq(1), ["mark_id", "birth_day", outcome]
    ].rename(columns={outcome: "p1"})
    p2 = passes.loc[
        passes["pass_no"].eq(2), ["mark_id", outcome]
    ].rename(columns={outcome: "p2"})
    q = p1.merge(p2, on="mark_id", how="inner").dropna(subset=["p1", "p2"])
    if q.empty:
        return dict(n=0, days=0, p1=np.nan, p2=np.nan, diff=np.nan, lo=np.nan, hi=np.nan)
    q["diff"] = q["p2"].astype(float) - q["p1"].astype(float)
    arrays = [g["diff"].to_numpy(float) for _, g in q.groupby("birth_day", sort=True)]
    days = len(arrays)
    if days < 2:
        lo = hi = np.nan
    else:
        rng = np.random.default_rng(BOOT_SEED)
        boot = np.empty(BOOT_N, dtype=float)
        for b in range(BOOT_N):
            picks = rng.integers(0, days, size=days)
            total = 0.0
            nn = 0
            for j in picks:
                a = arrays[int(j)]
                total += float(a.sum())
                nn += int(len(a))
            boot[b] = total / nn
        lo, hi = np.quantile(boot, [0.025, 0.975])
    return dict(
        n=int(len(q)),
        days=days,
        p1=float(q["p1"].mean()),
        p2=float(q["p2"].mean()),
        diff=float(q["diff"].mean()),
        lo=float(lo) if np.isfinite(lo) else np.nan,
        hi=float(hi) if np.isfinite(hi) else np.nan,
    )


def quintile_map(df: pd.DataFrame, feature: str, outcome: str, stage: str) -> pd.DataFrame:
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
        ["stage", "feature", "outcome", "bucket", "n", "rate", "feature_mean", "feature_median"]
    ]


def append_csv(df: pd.DataFrame, path: Path, first: bool) -> bool:
    if df.empty:
        return first
    df.to_csv(path, mode="w" if first else "a", header=first, index=False)
    return False


def main() -> int:
    args = parse_args()
    symbol = str(args.symbol).strip()
    start_day = pd.Timestamp(args.start).date()
    end_day = pd.Timestamp(args.end).date()
    if end_day < start_day:
        raise SystemExit("--end must be >= --start")

    print("=" * 132)
    print("MICROSTRUCTURE FLOW-MARK MAP 01R — DEBOUNCED PEAK-ZONE LIFECYCLE")
    print("=" * 132)
    print("Status             = HISTORICAL EXPLORATORY MAP / NO FORMAL PASS-FAIL")
    print(f"Symbol             = {symbol}")
    print(f"Historical window  = {start_day} through {end_day} BRT inclusive")
    print("Episode debounce   = one full completed clock second with zero qualifying widening")
    print("Primary mark       = PEAK-SPREAD BID/ASK zone")
    print("Mark activation    = EPISODE CLOSE; no peak look-ahead")
    print("Birth geometry     = DESCRIPTIVE ONLY / NO competing replay")
    print("Lifecycle          = PASS1 -> RETEST -> PASS2+ / FAILURE")
    print("M5/M15 levels      = NOT USED")
    print("Candle color       = NOT USED")
    print("Threshold fitting  = NONE")
    print("Exp27/Calibration  = UNTOUCHED / SCORES SEALED")
    print("Runtime promotion  = NONE")
    print()

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    marks_path = OUT_DIR / "FLOWMARK_map01r_marks.csv"
    passes_path = OUT_DIR / "FLOWMARK_map01r_passes.csv"
    failures_path = OUT_DIR / "FLOWMARK_map01r_failures.csv"
    quintiles_path = OUT_DIR / "FLOWMARK_map01r_feature_quintiles.csv"
    for p in (marks_path, passes_path, failures_path, quintiles_path):
        if p.exists():
            p.unlink()

    first_marks = first_passes = first_failures = True
    marks_summaries: list[pd.DataFrame] = []
    pass_summaries: list[pd.DataFrame] = []
    failure_summaries: list[pd.DataFrame] = []
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
            raise RuntimeError(f"FLOWMARK01R point guard failed: expected {EXPECTED_POINT}, got {point}")

        days = pd.date_range(start_day, end_day, freq="D")
        total_days = len(days)

        for day_no, dts in enumerate(days, start=1):
            d = dts.date()
            q_start = brt_local(d, time(0, 0))
            q_end = brt_local(d + timedelta(days=1), time(0, 0)) - timedelta(milliseconds=1)

            phase(day_no, total_days, d, "FETCH ticks")
            raw = mt5.copy_ticks_range(symbol, to_utc(q_start), to_utc(q_end), mt5.COPY_TICKS_ALL)
            ticks = valid_ticks(raw)
            if len(ticks) < 2:
                coverage["NO_TICK_DAY"] += 1
                phase(day_no, total_days, d, f"DONE no ticks ({len(ticks)})")
                continue

            coverage["DAYS_WITH_TICKS"] += 1
            coverage["VALID_TICKS"] += int(len(ticks))
            ms = ticks["time_msc"].astype(np.int64)
            bid = ticks["bid"].astype(float)
            ask = ticks["ask"].astype(float)

            phase(day_no, total_days, d, f"BASELINE ticks={len(ticks)}")
            baseline = spread_baseline_by_tick(ms, ask - bid)

            phase(day_no, total_days, d, "EPISODES 01R")
            marks = episodes_for_day(ms, bid, ask, baseline, point, d)
            phase(day_no, total_days, d, f"LIFECYCLE episodes={len(marks)} [PEAK zone]")
            passes = lifecycle_for_day(marks, ms, bid, ask, baseline, point)
            phase(day_no, total_days, d, f"PASS LABELS passes={len(passes)}")
            label_passes(passes, ms, bid, ask, point)
            for m in marks:
                add_activation60(m, ms)

            failed_n = sum(int(m.get("failure_idx", -1)) >= 0 for m in marks)
            phase(day_no, total_days, d, f"FAILURE PATHS failures={failed_n}")
            failures = failure_paths_for_day(marks, ms, bid, ask)

            mdf = pd.DataFrame(marks)
            pdf = pd.DataFrame(passes)
            fdf = pd.DataFrame(failures)

            first_marks = append_csv(mdf, marks_path, first_marks)
            first_passes = append_csv(pdf, passes_path, first_passes)
            first_failures = append_csv(fdf, failures_path, first_failures)

            if not mdf.empty:
                keep = [
                    "mark_id", "birth_day", "direction", "direction_name", "close_reason",
                    "activation_idx", "lifecycle_status", "departure_idx", "first_retest_idx",
                    "failure_idx", "max_passes", "pass1_within_60s_from_activation",
                    "qualifying_ticks", "duration_birth_to_last_ms", "peak_spread",
                    "peak_spread_ratio", "birth_spread_ratio",
                    "birth_tick_rate_ratio_1s", "birth_tick_accel_1s_vs_prev4s",
                    "birth_signed_mid_impulse_1s_points",
                ]
                marks_summaries.append(mdf[[c for c in keep if c in mdf.columns]].copy())
            if not pdf.empty:
                keep = [
                    "mark_id", "birth_day", "pass_no", "outcome_complete_before_retest_60s",
                    "mfe_60_points", "mae_60_points",
                    "hit_50_before_retest", "hit_100_before_retest",
                    "hit_200_before_retest", "hit_300_before_retest",
                    "pass_spread_ratio", "pass_tick_rate_ratio_1s",
                    "pass_tick_accel_1s_vs_prev4s", "pass_signed_mid_impulse_1s_points",
                ]
                pass_summaries.append(pdf[[c for c in keep if c in pdf.columns]].copy())
            if not fdf.empty:
                keep = [
                    "mark_id", "birth_day", "first_competing_event",
                    "candidate_prior_mark_id", "prior_mark_eventually_hit_before_reclaim",
                    "next_flow_episode_id", "new_episode_matches_travel_direction",
                ]
                failure_summaries.append(fdf[[c for c in keep if c in fdf.columns]].copy())

            coverage["EPISODES"] += len(marks)
            coverage["PASSES"] += len(passes)
            coverage["FAILURES"] += len(failures)
            phase(
                day_no,
                total_days,
                d,
                f"DONE episodes={len(marks)} passes={len(passes)} failures={len(failures)}",
            )
    finally:
        mt5.shutdown()

    marks = pd.concat(marks_summaries, ignore_index=True) if marks_summaries else pd.DataFrame()
    passes = pd.concat(pass_summaries, ignore_index=True) if pass_summaries else pd.DataFrame()
    failures = pd.concat(failure_summaries, ignore_index=True) if failure_summaries else pd.DataFrame()

    print()
    print("=" * 132)
    print("FLOW-MARK MAP01R UNIVERSE")
    print("=" * 132)
    print(f"days_with_ticks = {coverage['DAYS_WITH_TICKS']}")
    print(f"days_no_ticks   = {coverage['NO_TICK_DAY']}")
    print(f"valid_ticks     = {coverage['VALID_TICKS']}")
    print(f"episodes        = {coverage['EPISODES']}")
    print(f"passes          = {coverage['PASSES']}")
    print(f"failures        = {coverage['FAILURES']}")

    if not marks.empty:
        print()
        print("BIRTH DIRECTION")
        print(marks["direction_name"].value_counts(dropna=False).to_string())
        directional = marks.loc[marks["direction"].ne(0)].copy()
        activated = directional["activation_idx"].ge(0)
        dep = directional["departure_idx"].ge(0)
        ret = directional["first_retest_idx"].ge(0)
        fail = directional["failure_idx"].ge(0)
        print()
        print("LIFECYCLE")
        print(f"  directional episodes = {len(directional)}")
        print(f"  activated            = {int(activated.sum())} ({100*activated.mean():.2f}%)")
        print(f"  departed             = {int(dep.sum())} ({100*dep.mean():.2f}%)")
        print(f"  retested             = {int(ret.sum())} ({100*ret.mean():.2f}%)")
        print(f"  failed               = {int(fail.sum())} ({100*fail.mean():.2f}%)")
        d60 = directional["pass1_within_60s_from_activation"].dropna()
        print(f"  PASS1 <=60s activation = {100*d60.mean():.2f}% (n_complete={len(d60)})")

    if not passes.empty:
        print()
        print("PASS COUNTS")
        print(f"  PASS1  = {int(passes['pass_no'].eq(1).sum())}")
        print(f"  PASS2  = {int(passes['pass_no'].eq(2).sum())}")
        print(f"  PASS3  = {int(passes['pass_no'].eq(3).sum())}")
        print(f"  PASS4+ = {int(passes['pass_no'].ge(4).sum())}")
        print()
        print("PASS CONTINUATION — BEFORE NEXT RETEST")
        for name, z0 in (
            ("PASS1", passes.loc[passes["pass_no"].eq(1)]),
            ("PASS2", passes.loc[passes["pass_no"].eq(2)]),
            ("PASS3+", passes.loc[passes["pass_no"].ge(3)]),
        ):
            z = z0.loc[z0["outcome_complete_before_retest_60s"].eq(1)]
            rates = " ".join(
                f"+{t}={100*z[f'hit_{t}_before_retest'].mean():6.2f}%"
                if len(z)
                else f"+{t}=NA"
                for t in TARGET_POINTS
            )
            mfe = float(z["mfe_60_points"].mean()) if len(z) else np.nan
            print(f"  {name:<6} n={len(z):>6} | {rates} | meanMFE60={mfe:.2f}")

        print()
        print("MATCHED SAME-MARK PASS2 - PASS1 — WHOLE-BRT-DAY BOOTSTRAP")
        for target in TARGET_POINTS:
            r = paired_bootstrap(passes, f"hit_{target}_before_retest")
            print(
                f"  +{target:<3} n={r['n']:>5} days={r['days']:>3} "
                f"PASS1={100*r['p1']:6.2f}% PASS2={100*r['p2']:6.2f}% "
                f"diff={100*r['diff']:+6.2f}pp "
                f"CI95=[{100*r['lo']:+6.2f},{100*r['hi']:+6.2f}]pp"
            )
        r = paired_bootstrap(passes, "mfe_60_points")
        print(
            f"  MFE60 n={r['n']:>5} days={r['days']:>3} "
            f"PASS1={r['p1']:.2f} PASS2={r['p2']:.2f} "
            f"diff={r['diff']:+.2f} points CI95=[{r['lo']:+.2f},{r['hi']:+.2f}]"
        )

    if not failures.empty:
        print()
        print("FAILURE -> NEXT DESTINATION")
        print(failures["first_competing_event"].value_counts(dropna=False).to_string())
        cand = failures["candidate_prior_mark_id"].notna()
        if cand.any():
            z = failures.loc[cand]
            print(f"  has activated prior mark candidate = {int(cand.sum())}/{len(failures)}")
            print(
                "  prior mark eventually hit before failed-mark reclaim = "
                f"{100*z['prior_mark_eventually_hit_before_reclaim'].mean():.2f}%"
            )
        nm = failures["next_flow_episode_id"].notna()
        if nm.any():
            x = failures.loc[nm, "new_episode_matches_travel_direction"].dropna()
            if len(x):
                print(
                    "  next new episode birth matches failure travel direction = "
                    f"{100*x.mean():.2f}% (n={len(x)})"
                )

    maps: list[pd.DataFrame] = []
    if not marks.empty:
        directional = marks.loc[marks["direction"].ne(0)]
        for feat in (
            "peak_spread_ratio",
            "qualifying_ticks",
            "duration_birth_to_last_ms",
            "birth_signed_mid_impulse_1s_points",
        ):
            if feat in directional.columns:
                q = quintile_map(
                    directional,
                    feat,
                    "pass1_within_60s_from_activation",
                    "EPISODE_TO_PASS1_60S",
                )
                if not q.empty:
                    maps.append(q)
    if not passes.empty:
        eligible_passes = passes.loc[passes["outcome_complete_before_retest_60s"].eq(1)]
        for feat in (
            "pass_spread_ratio",
            "pass_tick_rate_ratio_1s",
            "pass_tick_accel_1s_vs_prev4s",
            "pass_signed_mid_impulse_1s_points",
        ):
            if feat in eligible_passes.columns:
                q = quintile_map(
                    eligible_passes,
                    feat,
                    "hit_200_before_retest",
                    "PASS_TO_HIT200_BEFORE_RETEST",
                )
                if not q.empty:
                    maps.append(q)

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
    print("OUTPUTS")
    print(f"  marks     = {marks_path}")
    print(f"  passes    = {passes_path}")
    print(f"  failures  = {failures_path}")
    if maps:
        print(f"  quintiles = {quintiles_path}")
    print()
    print("MICROSTRUCTURE_FLOW_MARK_MAP01R = COMPLETE_EXPLORATORY_MAP")
    print("PRIMARY_GEOMETRY = PEAK_SPREAD_ZONE / ACTIVATION = EPISODE_CLOSE")
    print("BIRTH_GEOMETRY_OUTCOME_REPLAY = DISABLED")
    print("NO THRESHOLD / BEST-BUCKET / PASS-NUMBER PROMOTION IS AUTHORIZED")
    print("EXP27 = UNTOUCHED / SCORES SEALED")
    print("CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
