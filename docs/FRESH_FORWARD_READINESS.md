# Fresh-Forward Readiness — Exp27 + OPERABILITY01

Date: 2026-08-14.

This document records the pre-score readiness rules for the fresh-forward phase. It does not change the frozen Exp27 scientific contract and does not promote OPERABILITY01 to runtime enforcement.

## Exp27 — frozen maturity gate

Frozen shadow start:

```text
2026-08-13 00:00:00 BRT
```

No Exp27 model score may be inspected until BOTH conditions are true:

```text
eligible BRT days >= 60
AND
dynamic structural states >= 1500
```

Before maturity, only the counts required to determine readiness may be inspected. The following remain sealed:

- Brier;
- LogLoss;
- AUC;
- calibration;
- class residuals;
- GEO vs CONST gains;
- SEMI vs GEO gains;
- any model-comparison outcome.

The final one-shot Exp27 comparisons remain exactly:

```text
A) GEO vs CONST
B) SEMI vs GEO
```

with STATE_WEIGHTED primary estimand and whole-BRT-day bootstrap preserving state weights.

## Exact state-count requirement

A generic M5 row is NOT an Exp27 dynamic structural state.

The Exp27 readiness state counter must use the same frozen active-frontier / corridor state-machine definition. Before any fresh-forward state count is accepted, the counter must reproduce the historical replay exactly:

```text
unique dynamic states = 9667
TRAIN      = 5612
VALIDATION = 1959
TEST       = 2096
```

Any mismatch aborts the readiness state count. No approximate count may be substituted.

## OPERABILITY01 — separate shadow layer

OPERABILITY01 remains separate from Exp27. It may inspect only its own causal shadow classifications and descriptive counts:

- TRADEABLE / CAUTION / NO_TRADE counts;
- in-window vs outside-window counts;
- reason counts;
- accumulated BRT dates;
- latest shadow classification;
- data continuity / source guards.

No future return, PnL, EXIT label, win rate, Brier, LogLoss or other outcome score may be computed by the descriptive monitor.

OPERABILITY01 rows must never be counted as Exp27 states.

## Governance

- Historical timing discovery remains closed after Exp53.
- Exp27 remains untouched until its frozen maturity gate opens.
- OPERABILITY01 remains SHADOW_ONLY.
- Runtime promotion remains NONE.
- No rule, threshold, event exclusion, state definition or maturity requirement may be changed after observing fresh-forward outcomes.
