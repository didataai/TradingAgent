#!/usr/bin/env python3
"""Decision Replay — causal historical execution backtest.

Two frozen exploratory execution policies share the same causal engine.

Replay01 (already completed):
- H=60m only.
- Signal: TRADEABLE and q_cal_60 > 0.50 => ADVANCE; <0.50 => RECAPTURE.

Replay02 (frozen before first run):
- H=60m only.
- Entry is still the next contiguous M5 open.
- At that executable entry price:
      d_back_entry    = abs(entry - back)
      d_forward_entry = abs(forward - entry)
      q_BE_entry      = d_back_entry / (d_back_entry + d_forward_entry)
- Signal: TRADEABLE and q_cal_60 > q_BE_entry => ADVANCE;
          q_cal_60 < q_BE_entry => RECAPTURE; equality => WAIT.
- No fitted margin, threshold search, horizon search or sign inversion.

Shared frozen engine:
- Historical engineering only; VALIDATION + TEST are repeatedly inspected and exploratory.
- Exact Track-D / Exp41 / calibration guards must pass first.
- Mapping: UP ADV=BUY, UP REC=SELL, DOWN ADV=SELL, DOWN REC=BUY.
- Maximum one trade per structural episode; no overlapping positions.
- Entry = next contiguous M5 open after state_time.
- Target/stop = frozen corridor boundaries for chosen structural side.
- Intrabar OHLC execution; same-bar target+stop => STOP first.
- Timeout = 60 minutes after entry, marked at last contiguous M5 close <= deadline.
- Validation trades may not cross Split B; TEST trades require complete data to deadline.
- Gross replay only: no spread/slippage/commission/swap.
- Gross PASS gate: expectancy_R > 0 and profit_factor_R > 1 in BOTH VALIDATION and TEST.

This runner does not touch or score Exp27/Decision Calibration fresh-forward ledgers.
Runtime promotion is NONE.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import math

import numpy as np
import pandas as pd

import DECISION01_structural_edge as d
import DECISION_calibration_shadow as cal
import EXP27_readiness_counter as e27
import OPERABILITY01_shadow_gate as gate

ROOT = Path(__file__).resolve().parent
PRIMARY_H = 60
SIGNAL_THRESHOLD = 0.50
SPLIT_B = pd.Timestamp("2026-04-29 10:40:00")
PERIODS = ("VALIDATION", "TEST")
POLICIES = ("replay01", "replay02")


def _historical_operability(m: pd.DataFrame, rules: dict, thresholds: dict) -> pd.DataFrame:
    """Apply frozen Operability v1 causally to historical M5.

    Scheduled events are intentionally inactive: the frozen governance forbids
    retroactively supplied event calendars from changing historical decisions.
    """
    q = m.copy().reset_index(drop=True)
    cfg = rules.get("operational_window_brt", {}) or {}
    start_s = str(cfg.get("start") or "09:00")
    end_s = str(cfg.get("end") or "18:00")
    start_min = gate.parse_hhmm(start_s)
    end_min = gate.parse_hhmm(end_s)
    if start_min > end_min:
        raise RuntimeError("ABORT BEFORE BACKTEST: unsupported cross-midnight operational window")

    ts = q["available_at_brt"]
    minute = (ts.dt.hour * 60 + ts.dt.minute).to_numpy(int)
    weekday = ts.dt.weekday.to_numpy(int)
    in_win = gate.in_window(ts, rules).to_numpy(bool)

    severity = np.zeros(len(q), dtype=np.int8)
    invalid = (
        ~np.isfinite(q[["open", "high", "low", "close", "ATR"]].to_numpy(float)).all(axis=1)
        | (q["ATR"].to_numpy(float) <= 0)
    )
    data_gap = q["M5_DELTA_MIN"].notna().to_numpy(bool) & ~np.isclose(
        q["M5_DELTA_MIN"].fillna(5.0).to_numpy(float), 5.0, atol=1e-9
    )
    outside = ~in_win
    weekend = weekday >= 5
    severity[invalid | data_gap | outside | weekend] = 2

    friday = (weekday == 4) & in_win
    mins_to_end = end_min - minute
    friday_no = (
        friday
        & (mins_to_end >= 0)
        & (mins_to_end <= gate.FRIDAY_NO_TRADE_MINUTES_TO_END)
    )
    friday_caution = (
        friday
        & (mins_to_end > gate.FRIDAY_NO_TRADE_MINUTES_TO_END)
        & (mins_to_end <= gate.FRIDAY_CAUTION_MINUTES_TO_END)
    )
    severity[friday_caution] = np.maximum(severity[friday_caution], 1)
    severity[friday_no] = 2

    caution_hits = np.zeros(len(q), dtype=np.int16)
    no_trade_shock = np.zeros(len(q), dtype=bool)
    for metric in gate.METRICS:
        x = q[metric].to_numpy(float)
        t = thresholds[metric]
        nt = np.isfinite(x) & (x >= t["q_no_trade"])
        ca = np.isfinite(x) & (x >= t["q_caution"]) & ~nt
        no_trade_shock |= nt
        caution_hits += ca.astype(np.int16)

    severity[caution_hits == 1] = np.maximum(severity[caution_hits == 1], 1)
    severity[no_trade_shock | (caution_hits >= 2)] = 2
    q["OPERABILITY_BT"] = np.where(
        severity == 2, "NO_TRADE", np.where(severity == 1, "CAUTION", "TRADEABLE")
    )
    return q


def _prepare_candidates(ns: dict, B_pos: np.ndarray, m5: pd.DataFrame) -> pd.DataFrame:
    dyn = ns["dyn"].copy().reset_index(drop=True)
    dyn["state_id"] = np.arange(len(dyn), dtype=int)

    needed = {"state_time", "episode_id", "bias_sign", "back", "forward", "period", "state_key"}
    missing = sorted(needed - set(dyn.columns))
    if missing:
        raise RuntimeError(f"ABORT BEFORE BACKTEST: dyn missing {missing}")

    pred = d._predict_cif(ns, dyn, B_pos, use_geo=True)
    _, a, r = pred[PRIMARY_H]
    den = a + r
    if np.any(~np.isfinite(den)) or np.any(den <= 0):
        raise RuntimeError("ABORT BEFORE BACKTEST: invalid H60 conditional-side denominator")
    q_raw = a / den
    q_cal = cal._calibrate(q_raw)
    if np.any(~np.isfinite(q_cal)) or np.any((q_cal <= 0) | (q_cal >= 1)):
        raise RuntimeError("ABORT BEFORE BACKTEST: invalid calibrated side probability")

    dyn["q_raw_60"] = q_raw
    dyn["q_cal_60"] = q_cal
    dyn["state_time"] = pd.to_datetime(dyn["state_time"], errors="coerce")
    if dyn["state_time"].isna().any():
        raise RuntimeError("ABORT BEFORE BACKTEST: invalid state_time")

    op = m5[["available_at_brt", "OPERABILITY_BT", "ATR"]].copy()
    q = dyn.loc[dyn["period"].isin(PERIODS)].merge(
        op,
        left_on="state_time",
        right_on="available_at_brt",
        how="left",
        validate="many_to_one",
    )
    if q["OPERABILITY_BT"].isna().any():
        bad = q.loc[q["OPERABILITY_BT"].isna(), "state_time"].head(5).tolist()
        raise RuntimeError(f"ABORT BEFORE BACKTEST: state/M5 operability mapping failed examples={bad}")
    return q.sort_values(["state_time", "episode_id"]).reset_index(drop=True)


def _trade_direction(bias_sign: float, structural_side: str) -> str:
    if bias_sign > 0:
        return "BUY" if structural_side == "ADVANCE" else "SELL"
    if bias_sign < 0:
        return "SELL" if structural_side == "ADVANCE" else "BUY"
    raise RuntimeError("ABORT BEFORE BACKTEST: zero structural bias")


def _planned_deadline(entry_time: pd.Timestamp) -> pd.Timestamp:
    return entry_time + pd.Timedelta(minutes=PRIMARY_H)


def _entry_break_even(entry: float, back: float, forward: float) -> tuple[float, float, float]:
    d_back = abs(entry - back)
    d_forward = abs(forward - entry)
    width = d_back + d_forward
    corridor_width = abs(forward - back)
    if not np.isfinite(width) or width <= 0:
        raise RuntimeError("ABORT BEFORE BACKTEST: invalid entry break-even width")
    if not np.isclose(width, corridor_width, atol=1e-8, rtol=1e-10):
        raise RuntimeError(
            "ABORT BEFORE BACKTEST: entry break-even geometry identity failed "
            f"width={width} corridor={corridor_width}"
        )
    q_be = d_back / width
    if not (0.0 < q_be < 1.0):
        raise RuntimeError(f"ABORT BEFORE BACKTEST: invalid q_BE_entry={q_be}")
    return float(q_be), float(d_back), float(d_forward)


def _simulate_trade(
    m5: pd.DataFrame,
    entry_idx: int,
    period: str,
    direction: str,
    target: float,
    stop: float,
    state_atr: float,
) -> dict:
    entry_row = m5.iloc[entry_idx]
    entry_time = pd.Timestamp(entry_row["available_at_brt"])
    entry = float(entry_row["open"])
    deadline = _planned_deadline(entry_time)

    if period == "VALIDATION" and deadline >= SPLIT_B:
        return {"status": "INCOMPLETE_SPLIT"}
    if period == "TEST" and deadline > pd.Timestamp(m5["available_at_brt"].max()):
        return {"status": "INCOMPLETE_END"}

    risk = abs(entry - stop)
    if not np.isfinite(risk) or risk <= 0:
        return {"status": "INVALID_RISK"}

    if direction == "BUY":
        if not (stop < entry < target):
            return {"status": "INVALID_ENTRY_GEOMETRY"}
    else:
        if not (target < entry < stop):
            return {"status": "INVALID_ENTRY_GEOMETRY"}

    prev_t = pd.Timestamp(m5.iloc[entry_idx - 1]["available_at_brt"])
    last_row = None
    ambiguous = False

    i = entry_idx
    while i < len(m5):
        row = m5.iloc[i]
        t = pd.Timestamp(row["available_at_brt"])
        if t > deadline:
            break
        if (t - prev_t) != pd.Timedelta(minutes=5):
            return {"status": "DATA_GAP", "exit_time": prev_t, "deadline": deadline}
        prev_t = t
        last_row = row

        hi = float(row["high"])
        lo = float(row["low"])
        if direction == "BUY":
            hit_target = hi >= target
            hit_stop = lo <= stop
        else:
            hit_target = lo <= target
            hit_stop = hi >= stop

        if hit_target and hit_stop:
            ambiguous = True
            exit_price = stop
            outcome = "STOP"
        elif hit_stop:
            exit_price = stop
            outcome = "STOP"
        elif hit_target:
            exit_price = target
            outcome = "TP"
        else:
            i += 1
            continue

        pnl_points = (exit_price - entry) if direction == "BUY" else (entry - exit_price)
        pnl_r = pnl_points / risk
        pnl_atr = pnl_points / state_atr if np.isfinite(state_atr) and state_atr > 0 else np.nan
        return {
            "status": "OK",
            "outcome": outcome,
            "exit_time": t,
            "exit_price": exit_price,
            "entry_time": entry_time,
            "entry_price": entry,
            "risk_points": risk,
            "pnl_points": pnl_points,
            "pnl_R": pnl_r,
            "pnl_ATR": pnl_atr,
            "ambiguous_stop": int(ambiguous),
            "deadline": deadline,
        }

    if last_row is None or pd.Timestamp(last_row["available_at_brt"]) < deadline:
        return {"status": "INCOMPLETE_END"}

    exit_time = pd.Timestamp(last_row["available_at_brt"])
    exit_price = float(last_row["close"])
    pnl_points = (exit_price - entry) if direction == "BUY" else (entry - exit_price)
    pnl_r = pnl_points / risk
    pnl_atr = pnl_points / state_atr if np.isfinite(state_atr) and state_atr > 0 else np.nan
    return {
        "status": "OK",
        "outcome": "TIMEOUT",
        "exit_time": exit_time,
        "exit_price": exit_price,
        "entry_time": entry_time,
        "entry_price": entry,
        "risk_points": risk,
        "pnl_points": pnl_points,
        "pnl_R": pnl_r,
        "pnl_ATR": pnl_atr,
        "ambiguous_stop": 0,
        "deadline": deadline,
    }


def _replay(candidates: pd.DataFrame, m5: pd.DataFrame, policy: str) -> tuple[pd.DataFrame, dict]:
    if policy not in POLICIES:
        raise ValueError(policy)

    time_to_idx = {
        pd.Timestamp(t): int(i)
        for i, t in enumerate(m5["available_at_brt"])
    }
    used_episodes: set[tuple[str, str]] = set()
    busy_until = pd.Timestamp.min
    trades: list[dict] = []
    blocked_sets: dict[str, set[tuple[str, str]]] = defaultdict(set)
    state_counts = Counter()

    for _, s in candidates.iterrows():
        period = str(s["period"])
        episode_key = (period, str(s["episode_id"]))
        if episode_key in used_episodes:
            continue

        state_time = pd.Timestamp(s["state_time"])
        if state_time < busy_until:
            blocked_sets["OVERLAP"].add(episode_key)
            state_counts["OVERLAP"] += 1
            continue

        if str(s["OPERABILITY_BT"]) != "TRADEABLE":
            blocked_sets[f"OPERABILITY_{s['OPERABILITY_BT']}"] .add(episode_key)
            state_counts[f"OPERABILITY_{s['OPERABILITY_BT']}"] += 1
            continue

        idx = time_to_idx.get(state_time)
        if idx is None or idx + 1 >= len(m5):
            blocked_sets["NO_NEXT_M5"].add(episode_key)
            state_counts["NO_NEXT_M5"] += 1
            continue
        entry_idx = idx + 1
        entry_time = pd.Timestamp(m5.iloc[entry_idx]["available_at_brt"])
        if (entry_time - state_time) != pd.Timedelta(minutes=5):
            blocked_sets["NONCONTIGUOUS_ENTRY"].add(episode_key)
            state_counts["NONCONTIGUOUS_ENTRY"] += 1
            continue

        if period == "VALIDATION" and entry_time >= SPLIT_B:
            blocked_sets["SPLIT_ENTRY"].add(episode_key)
            state_counts["SPLIT_ENTRY"] += 1
            continue

        back = float(s["back"])
        forward = float(s["forward"])
        entry = float(m5.iloc[entry_idx]["open"])
        lo_b, hi_b = min(back, forward), max(back, forward)
        if not (lo_b < entry < hi_b):
            blocked_sets["ENTRY_OUTSIDE_CORRIDOR"].add(episode_key)
            state_counts["ENTRY_OUTSIDE_CORRIDOR"] += 1
            continue

        qc = float(s["q_cal_60"])
        if policy == "replay01":
            decision_threshold = SIGNAL_THRESHOLD
            q_be_entry, d_back_entry, d_forward_entry = _entry_break_even(entry, back, forward)
            equal_key = "Q_EQUAL_050"
        else:
            q_be_entry, d_back_entry, d_forward_entry = _entry_break_even(entry, back, forward)
            decision_threshold = q_be_entry
            equal_key = "Q_EQUAL_ENTRY_BE"

        if math.isclose(qc, decision_threshold, rel_tol=0.0, abs_tol=1e-15):
            blocked_sets[equal_key].add(episode_key)
            state_counts[equal_key] += 1
            continue

        structural_side = "ADVANCE" if qc > decision_threshold else "RECAPTURE"
        direction = _trade_direction(float(s["bias_sign"]), structural_side)
        target = forward if structural_side == "ADVANCE" else back
        stop = back if structural_side == "ADVANCE" else forward

        sim = _simulate_trade(
            m5=m5,
            entry_idx=entry_idx,
            period=period,
            direction=direction,
            target=float(target),
            stop=float(stop),
            state_atr=float(s["ATR"]),
        )
        status = str(sim["status"])
        if status != "OK":
            blocked_sets[status].add(episode_key)
            state_counts[status] += 1
            if status == "DATA_GAP":
                used_episodes.add(episode_key)
                busy_until = pd.Timestamp(sim.get("deadline", entry_time + pd.Timedelta(minutes=PRIMARY_H)))
            continue

        used_episodes.add(episode_key)
        busy_until = pd.Timestamp(sim["exit_time"])
        trades.append({
            "policy": policy,
            "period": period,
            "episode_id": s["episode_id"],
            "state_key": s["state_key"],
            "state_time": state_time,
            "bias_sign": float(s["bias_sign"]),
            "q_raw_60": float(s["q_raw_60"]),
            "q_cal_60": qc,
            "q_be_entry": q_be_entry,
            "decision_threshold": float(decision_threshold),
            "q_minus_threshold": float(qc - decision_threshold),
            "d_back_entry": d_back_entry,
            "d_forward_entry": d_forward_entry,
            "structural_side": structural_side,
            "direction": direction,
            "back": back,
            "forward": forward,
            "target": float(target),
            "stop": float(stop),
            **sim,
        })

    return pd.DataFrame(trades), {
        "blocked_episode_sets": blocked_sets,
        "blocked_state_counts": state_counts,
        "used_episodes": len(used_episodes),
    }


def _metrics(z: pd.DataFrame) -> dict:
    if z.empty:
        return {
            "trades": 0, "expectancy": np.nan, "pf": np.nan, "win_rate": np.nan,
            "max_dd": np.nan, "cum_r": np.nan,
        }
    r = z["pnl_R"].to_numpy(float)
    pos = r[r > 0]
    neg = r[r < 0]
    gp = float(pos.sum()) if len(pos) else 0.0
    gl = float(-neg.sum()) if len(neg) else 0.0
    pf = gp / gl if gl > 0 else (float("inf") if gp > 0 else np.nan)
    equity = np.cumsum(r)
    running_peak = np.maximum.accumulate(np.r_[0.0, equity])
    dd = np.r_[0.0, equity] - running_peak
    return {
        "trades": int(len(z)),
        "buy": int(z["direction"].eq("BUY").sum()),
        "sell": int(z["direction"].eq("SELL").sum()),
        "tp": int(z["outcome"].eq("TP").sum()),
        "stop": int(z["outcome"].eq("STOP").sum()),
        "timeout": int(z["outcome"].eq("TIMEOUT").sum()),
        "ambiguous": int(z["ambiguous_stop"].sum()),
        "win_rate": float((r > 0).mean()),
        "pf": pf,
        "expectancy": float(np.mean(r)),
        "median": float(np.median(r)),
        "avg_win": float(np.mean(pos)) if len(pos) else np.nan,
        "avg_loss": float(np.mean(neg)) if len(neg) else np.nan,
        "cum_r": float(equity[-1]),
        "max_dd": float(-np.min(dd)),
        "pnl_points": float(z["pnl_points"].sum()),
        "mean_atr": float(z["pnl_ATR"].mean()),
    }


def _print_metrics(name: str, m: dict) -> None:
    if m["trades"] == 0:
        print(f"{name:<18} trades=0")
        return
    pf_text = "inf" if math.isinf(m["pf"]) else f"{m['pf']:.4f}"
    print(
        f"{name:<18} trades={m['trades']:>4} BUY={m['buy']:>4} SELL={m['sell']:>4} | "
        f"TP={m['tp']:>4} STOP={m['stop']:>4} TIMEOUT={m['timeout']:>4} AMBIG={m['ambiguous']:>3}"
    )
    print(
        f"{'':18} win={100*m['win_rate']:6.2f}% PF={pf_text:>8} "
        f"E[R]={m['expectancy']:+.5f} medianR={m['median']:+.5f} "
        f"avgWin={m['avg_win']:+.5f} avgLoss={m['avg_loss']:+.5f}"
    )
    print(
        f"{'':18} CumR={m['cum_r']:+.5f} MaxDD_R={m['max_dd']:.5f} "
        f"sumPoints={m['pnl_points']:+.3f} meanPnL_ATR={m['mean_atr']:+.5f}"
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Frozen Decision Replay execution backtest")
    p.add_argument(
        "--policy",
        choices=POLICIES,
        default="replay01",
        help="replay01 reproduces q_cal vs 0.50; replay02 uses entry-price economic break-even",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    policy = str(args.policy)
    replay_no = "01" if policy == "replay01" else "02"
    signal_text = (
        "TRADEABLE + q_cal_60 vs 0.50"
        if policy == "replay01"
        else "TRADEABLE + q_cal_60 vs q_BE_entry(next M5 open)"
    )

    print("=" * 132)
    print(f"DECISION REPLAY {replay_no} — CAUSAL BUY / SELL / WAIT EXECUTION BACKTEST")
    print("=" * 132)
    print("Historical status     = REPEATEDLY INSPECTED / EXPLORATORY ENGINEERING")
    print("Primary horizon       = 60m ONLY")
    print(f"Signal                = {signal_text}")
    print("Entry                 = next contiguous M5 open")
    print("Overlap               = none; max one trade per structural episode")
    print("Same-bar ambiguity    = STOP FIRST")
    print("Costs                 = excluded; GROSS replay")
    print("Formal fresh-forward  = NOT REPLACED")
    print("Exp27/Calibration     = UNTOUCHED / SCORES SEALED")
    print("Runtime promotion     = NONE")
    print()

    source = e27.decode_source(e27.LAUNCHER)
    e27.historical_guard(source)
    ns = d._execute_historical_dataset(source)
    d._guard_exact_universe(ns)
    _, B_pos = d._fit_exp41_models(ns)
    cal._guard_calibrator(ns, B_pos)

    rules = gate.load_json(gate.RULES_PATH)
    ref_path = gate.find_reference_m5_parquet()
    m5 = gate.prepare_operability_m5(ref_path, rules)
    thresholds = gate.compute_thresholds(m5, rules)
    print()
    print("OPERABILITY HISTORICAL REPLAY GUARD = PASS")
    print(f"  reference = {ref_path}")
    for metric in gate.METRICS:
        t = thresholds[metric]
        print(
            f"  {metric:<12} caution={t['q_caution']:.6f} "
            f"no_trade={t['q_no_trade']:.6f} n={t['n_train']}"
        )

    m5 = _historical_operability(m5, rules, thresholds)
    candidates = _prepare_candidates(ns, B_pos, m5)
    print()
    print("CANDIDATE UNIVERSE")
    print(f"  states VALIDATION = {int(candidates['period'].eq('VALIDATION').sum())}")
    print(f"  states TEST       = {int(candidates['period'].eq('TEST').sum())}")
    print(f"  episodes          = {candidates[['period','episode_id']].drop_duplicates().shape[0]}")
    if policy == "replay01":
        print(f"  H60 threshold     = q_cal_60 vs {SIGNAL_THRESHOLD:.2f}")
    else:
        print("  H60 threshold     = q_cal_60 vs q_BE_entry at actual next-M5 open")
        print("  edge margin       = NONE")

    trades, audit = _replay(candidates, m5, policy)
    gate_prefix = f"DECISION_REPLAY_{replay_no}"
    if trades.empty:
        print()
        print("No valid trades were produced under the frozen policy.")
        print(f"{gate_prefix}_GROSS_STATUS = FAIL")
        print("EXP27 = UNTOUCHED / SCORES SEALED")
        print("CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED")
        print("RUNTIME_PROMOTION = NONE")
        return 0

    trades = trades.sort_values("entry_time").reset_index(drop=True)

    print()
    print("PRIMARY GROSS TRADE RESULTS")
    res = {}
    for period in PERIODS:
        res[period] = _metrics(trades.loc[trades["period"].eq(period)])
        _print_metrics(period, res[period])
    res["POOLED"] = _metrics(trades)
    _print_metrics("VAL+TEST POOLED", res["POOLED"])

    if policy == "replay02":
        print()
        print("ENTRY BREAK-EVEN DIAGNOSTICS — descriptive only")
        print(
            f"  q_BE_entry mean={trades['q_be_entry'].mean():.5f} "
            f"median={trades['q_be_entry'].median():.5f} "
            f"min={trades['q_be_entry'].min():.5f} max={trades['q_be_entry'].max():.5f}"
        )
        print(
            f"  |q_cal-q_BE| mean={trades['q_minus_threshold'].abs().mean():.5f} "
            f"median={trades['q_minus_threshold'].abs().median():.5f}"
        )

    print()
    print("EXECUTION AUDIT — episode flags may overlap before a trade is eventually taken")
    blocked_sets = audit["blocked_episode_sets"]
    for key in sorted(blocked_sets):
        print(
            f"  {key:<28} episodes={len(blocked_sets[key]):>4} "
            f"state_occurrences={audit['blocked_state_counts'][key]:>5}"
        )
    print(f"  {'TRADED_EPISODES':<28} episodes={audit['used_episodes']:>4}")

    print()
    print("LAST 15 TRADES — descriptive")
    cols = [
        "period", "state_time", "entry_time", "exit_time", "direction",
        "structural_side", "q_cal_60", "decision_threshold", "q_minus_threshold",
        "outcome", "pnl_R", "pnl_points",
    ]
    print(trades[cols].tail(15).to_string(index=False, float_format=lambda x: f"{x:.5f}"))

    val_pass = (
        res["VALIDATION"]["trades"] > 0
        and res["VALIDATION"]["expectancy"] > 0
        and res["VALIDATION"]["pf"] > 1
    )
    test_pass = (
        res["TEST"]["trades"] > 0
        and res["TEST"]["expectancy"] > 0
        and res["TEST"]["pf"] > 1
    )
    gross_pass = bool(val_pass and test_pass)

    print()
    print(f"{gate_prefix}_VALIDATION_GATE = {'PASS' if val_pass else 'FAIL'}")
    print(f"{gate_prefix}_TEST_GATE       = {'PASS' if test_pass else 'FAIL'}")
    print(f"{gate_prefix}_GROSS_STATUS    = {'PASS' if gross_pass else 'FAIL'}")
    if policy == "replay01":
        print("NO HORIZON/THRESHOLD/SIGN RESCUE IS AUTHORIZED BY THIS RUN")
    else:
        print("NO EDGE-MARGIN/HORIZON/TARGET-STOP/SIGN RESCUE IS AUTHORIZED BY THIS RUN")
    print("EXP27 = UNTOUCHED / SCORES SEALED")
    print("CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED")
    print("RUNTIME_PROMOTION = NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
