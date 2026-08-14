# OPERABILITY01 — Prospective GOLD Market Operability Policy v1 — FROZEN BEFORE FRESH-FORWARD USE

Date: 2026-08-14.

This phase is separate from historical timing discovery. It is NOT Exp54 timing-feature research and cannot rescue Exp48–Exp53. `HISTORICAL_TIMING_FEATURE_DISCOVERY_STOP=YES` remains active. Exp27 remains untouched and runtime promotion remains NONE.

## Purpose

Classify whether NEW entries are operationally allowed before any directional/timing model is consulted:

- `TRADEABLE`
- `CAUTION`
- `NO_TRADE`

Risk-management actions for already-open positions remain allowed in all three states.

No future outcome, PnL, EXIT label, trade result, or Exp27 score may be used by OPERABILITY01.

## Frozen reference / prospective boundary

- TRAIN reference for endogenous shock thresholds: M5 rows strictly before `2026-01-09 12:50:00 BRT`.
- Reference rows are restricted to the already-defined operational window and weekdays.
- Fresh-forward operability rows: `>= 2026-08-13 00:00:00 BRT`.
- Historical VALIDATION/TEST must NOT be used to optimize, score, or rescue this policy.
- Threshold quantile levels are frozen before fresh-forward evaluation.

## Frozen deterministic governance

Operational window comes from `config/market_intelligence/GOLD_d1_intraday_rules.json` (`09:00–18:00 BRT` at freeze time).

- Outside operational window -> `NO_TRADE`.
- Weekend -> `NO_TRADE`.
- Invalid/nonpositive ATR or invalid M5 OHLC -> `NO_TRADE`.
- Non-contiguous M5 data at current bar (`delta != 5 minutes`) -> `NO_TRADE`.
- Friday final 60 minutes of the configured operating window -> at least `CAUTION`.
- Friday final 30 minutes -> `NO_TRADE`.

The Friday rule is a risk-governance rule relative to the strategy operating-window end; it is not an empirical claim that every broker's XAUUSD weekly close occurs at that exact BRT time.

## Frozen endogenous causal shock metrics

All use only the closed M5 bar available at the decision timestamp and previous closed M5 where needed:

- `RANGE_ATR = (high-low)/ATR`
- `ABS_RET_ATR = abs(close-prev_close)/ATR`
- `GAP_ATR = abs(open-prev_close)/ATR`

For each metric independently, thresholds are estimated once from TRAIN reference only:

- `CAUTION` threshold = TRAIN empirical q=0.990.
- `NO_TRADE` threshold = TRAIN empirical q=0.995.

Decision:
- Any metric >= its q0.995 -> `NO_TRADE`.
- Exactly one metric in [q0.990, q0.995) -> at least `CAUTION`.
- Two or more simultaneous q0.990 warnings -> `NO_TRADE`.

No threshold may be changed after observing fresh-forward outcomes.

## Scheduled macro-event hook

If `config/market_intelligence/GOLD_operability_events.csv` exists, only rows supplied prospectively with columns:

`event_time_brt,impact,label`

are considered. Only `impact=HIGH` is active in v1:

- within ±15 minutes -> `NO_TRADE`
- >15 and <=30 minutes -> at least `CAUTION`

A missing event file leaves this gate inactive. Retrospectively adding events to explain previous failures is prohibited.

## Unscheduled news / geopolitical shocks

OPERABILITY01 v1 has no external real-time news feed. Unscheduled war/news can only be detected indirectly after market microstructure/price shock appears. A future live news connector may be added only under a separately frozen prospective policy; it may not retroactively rewrite historical results.

## Governance / interpretation

- `TRADEABLE` means the operability gate does not block a new entry; it is NOT a BUY/SELL signal.
- `CAUTION` means entry requires additional review / later risk policy; no position-sizing rule is promoted by this phase.
- `NO_TRADE` blocks NEW entries only; risk-reducing actions remain allowed.
- This layer sits BEFORE structural signal/timing logic.
- Exp47 remains the minimal robust historical probability law.
- Exp49/50/51/53 remain non-universal/regime candidates where already recorded.
- OPERABILITY01 does not claim that blocked periods are unprofitable; it tests whether abstention governance improves robustness prospectively.
- No historical event/day exclusion may be used to turn prior FAILs into PASS.

## Shadow runner

`OPERABILITY01_shadow_gate.py`

The runner:
1. loads GOLD M5 causally;
2. calibrates q0.990/q0.995 from TRAIN reference only;
3. classifies only rows >= fresh-forward start;
4. optionally applies prospectively supplied HIGH macro events;
5. writes a shadow log;
6. computes no future-performance score.

If the local M5 parquet contains no fresh-forward rows, status must be `WAITING_FOR_FRESH_FORWARD_DATA`.
