# MICROFLOW SHADOW01 — PROSPECTIVE VALIDATION FREEZE

Status: FROZEN BEFORE FRESH DATA

Fresh start: 2026-08-19 00:00:00 BRT

Runtime promotion: NONE

## Purpose

Validate the already-frozen MicroFlow Shadow01 historical-development score on fresh FlowMark PASS events. This document does not modify Map01R, Map02, Map03, or Map04 logic and does not authorize BUY/SELL decisions.

## Population

Source ledger:

`data/market_chronos/microstructure/FLOWMARK_map04_prospective_passes.csv.gz`

Eligibility is identical to the Map04 fresh population:

- birth_day >= 2026-08-19 BRT
- outcome_complete_before_retest_60s == 1
- hit_200_before_retest is binary
- finite signed_mid_impulse_1s_points
- finite opposing_mid_path_1s_points
- unique (mark_id, pass_no)

Frozen pass strata:

- PASS1: pass_no == 1
- PASS2: pass_no == 2
- PASS3+: pass_no >= 3

## Frozen Shadow01 probability

For each event, let:

- X = signed_mid_impulse_1s_points
- C = opposing_mid_path_1s_points
- TX = asinh(X / 20)
- TC = log(1 + max(C, 0))

Probability is logistic(intercept + beta_x * TX + beta_c * TC).

Frozen coefficients:

### PASS1

- intercept = -3.9428766403356286
- beta_x = 0.41954426272480366
- beta_c = 0.16817135923298430

### PASS2

- intercept = -4.3910705931584700
- beta_x = 0.28449971217439424
- beta_c = 0.26039027817580020

### PASS3+

- intercept = -4.8730026409947770
- beta_x = 0.47301521137832470
- beta_c = 0.37804446547486326

No coefficient, transform, sign, pass grouping, target, or feature may be changed after fresh data begins.

## Primary prospective question

Does the frozen Shadow01 probability rank fresh +200-before-retest outcomes above chance within each PASS stratum?

Primary statistic:

- daily ROC AUC per BRT day and PASS group
- a day is eligible only if it contains at least one positive and one negative event
- primary estimate is the equal-weight arithmetic mean of eligible daily AUCs
- whole-BRT-day bootstrap, N = 5000
- seed = 2026081805

## Frozen maturity

Scores remain sealed until BOTH are true:

- >= 20 eligible BRT days overall in the fresh ledger
- >= 200000 complete eligible PASS events overall

Before maturity the scorer may report only coverage/progress counts. It MUST NOT compute or print AUC, CI, sign, Brier score, calibration, confidence-bucket outcomes, or directional performance.

## Formal primary pass criterion

All three pass strata must satisfy:

- mean_daily_AUC > 0.50
- CI95 lower bound > 0.50

No sign inversion is allowed.

If any stratum fails, the frozen full-pass criterion fails. No PASS1-only, PASS2-only, PASS3+-only, direction-only, threshold, confidence-bucket, or probability cutoff rescue is authorized.

## Secondary diagnostics after maturity only

Descriptive only:

- pooled AUC
- Brier score
- observed event rate
- mean predicted probability
- calibration by fixed probability bins
- UP/DOWN splits
- LOW/MEDIUM/HIGH historical-display buckets

These secondary diagnostics cannot rescue a failed primary result.

## Anti-rescue / governance

The following are forbidden inside this frozen experiment:

- changing +200 target
- changing 60s/retest outcome definition
- changing 1s feature horizon
- replacing opposing path with total path or path efficiency
- clipping/winsorizing X or C
- selecting favorable thresholds
- selecting only HIGH confidence events
- selecting only one direction or one PASS stage
- refitting coefficients on fresh data
- recalibrating probabilities before formal maturity
- inspecting intermediate predictive scores before maturity

Any new hypothesis requires a separately named future freeze.

## Relationship to other lines

- Map02 prospective remains independent and sealed under its own maturity.
- Map04 prospective remains independent and sealed under its own maturity.
- Map03 primary remains failed and is not sign-inverted.
- Exp27 remains untouched/sealed.
- Decision Calibration Shadow remains untouched/sealed.
- Runtime promotion remains NONE.

## Interpretation boundary

Shadow01 `Continuation` is specifically the frozen historical-development estimate for:

`hit +200 points in PASS direction before next retest within the frozen 60s horizon`.

It is NOT a generic probability that GOLD will rise/fall and is NOT a BUY/SELL probability.
