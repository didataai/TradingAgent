# MICROSTRUCTURE QUOTE PATH EFFICIENCY MAP 03 — incremental quote-coherence law

## Status / lineage

Map03 is a new, separately frozen microstructure experiment derived from the already-observed Map01R / Map02 discovery line.

It does **not** modify or rescue Map01R, Map02, Decision Replay, Exp27, Decision Calibration Shadow, Operability, or Breakout Map01.

Already-observed discovery before this freeze:

- repeated PASSes are weaker on average than PASS1;
- `pass_signed_mid_impulse_1s_points` is a threshold-free positive ranking feature for +200 continuation inside PASS1, PASS2 and PASS3+;
- raw tick-rate and tick-acceleration do not show the same stable positive ordering;
- spread-ratio is not stable enough to replace signed MID migration as the primary directional feature.

Map03 asks a different mechanistic question: **holding net directional MID strength continuously under control, does the coherence / efficiency of the quote path add information?**

No Map03 outcome has been inspected before this freeze.

## Scientific question

Two PASS events can have the same net signed MID displacement over one second but very different paths.

Example:

```text
A: 100 -> 102 -> 104 -> 106 -> 108
B: 100 -> 108 ->  99 -> 110 -> 108
```

Both may finish with the same net move, but A is a cleaner directional migration while B contains much more backtracking.

Frozen question:

```text
within the same BRT day and PASS stage,
after continuously controlling signed MID impulse 1s,
does a more directionally efficient 1-second MID path
increase the probability of +200 points before the next retest?
```

## Uninspected historical holdout

The historical discovery analyzed Map02 PASS outcomes through `2026-07-01 BRT`, plus the separately observed mechanical/outcome smoke on `2026-08-11 BRT`.

Map03 freezes the following historical holdout before scoring it:

```text
2026-07-02 through 2026-08-10 BRT inclusive
PLUS 2026-08-12 BRT
EXCLUDE 2026-08-11 BRT
```

`2026-08-11` is excluded because its Map01R lifecycle and descriptive outcomes were already observed.

`2026-07-02` may be used: an earlier recovery process was manually interrupted during lifecycle computation before that day produced PASS labels/outcome output or a completed day append.

This block is an **uninspected historical holdout**, not formal prospective OOS. A successful result may be called historical holdout support, not formal validation.

## Mechanical reproduction gate — no Map03 scoring

Before holdout scoring, the lean Map03 lifecycle implementation must reproduce the frozen Map01R smoke day `2026-08-11 BRT` using the unchanged PEAK-zone episode definitions.

Hard counts:

```text
episodes = 4066
passes   = 38287
PASS1    = 3853
PASS2    = 3365
PASS3+   = 31069
```

The smoke gate computes event counts only. It must not score Map03 on `2026-08-11`.

Any mismatch aborts the holdout before Map03 outcome scoring.

## Source event semantics — unchanged Map01R

Map03 uses the same causal Flow-Mark lifecycle:

- debounced qualifying widening episode;
- PEAK-SPREAD `[peak_bid, peak_ask]` primary mark;
- mark activation only at episode close;
- UP/DOWN direction frozen at birth;
- PASS1 / RETEST / PASS2+ semantics unchanged;
- FAILURE semantics unchanged;
- full BRT-day path;
- `point = 0.01` exact guard.

Map03 may implement a lean lifecycle representation for computational efficiency, but event identity and crossing inequalities must remain exactly equivalent to Map01R.

## Primary net-strength control

Inherited Map02 predictor:

```text
X = signed_mid_impulse_1s_points
```

At PASS tick index `i`, let:

```text
t0 = time_msc[i]
j  = last tick index at-or-before (t0 - 1000 ms)
mid = (bid + ask) / 2

X = pass_direction * (mid[i] - mid[j]) / point
```

`X` is a nuisance/control variable in Map03, not the new primary mechanism.

## Primary path-coherence predictor

Using the **same endpoint `j` used by X**, define the total traveled MID path:

```text
TOTAL_MID_PATH_1S_POINTS
    = sum(abs(mid[k] - mid[k-1]), k=j+1..i) / point
```

Then freeze:

```text
E = DIRECTIONAL_PATH_EFFICIENCY_1S
  = X / TOTAL_MID_PATH_1S_POINTS
```

Eligibility requires:

```text
j >= 0
TOTAL_MID_PATH_1S_POINTS > 0
finite(X)
finite(E)
```

Properties:

```text
E near +1 -> nearly all traveled MID path was efficiently in PASS direction
E near  0 -> substantial backtracking / churn relative to net move
E < 0     -> one-second net migration finished against PASS direction
E near -1 -> coherent movement against PASS direction
```

No threshold, clipping, winsorization, quantile cutoff or optimized transform is allowed for E.

## Primary outcome

Inherited unchanged:

```text
Y = hit_200_before_retest
```

Eligibility also requires:

```text
outcome_complete_before_retest_60s == 1
Y in {0,1}
```

The +200 target and 60-second/retest horizon are inherited from the pre-existing Map01R/Map02 primary outcome and are not selected inside Map03.

## Mandatory PASS-stage stratification

Frozen groups:

```text
PASS1  : pass_no == 1
PASS2  : pass_no == 2
PASS3+ : pass_no >= 3
```

No pooling or alternate grouping may replace this after scoring.

## Rank transform — frozen and threshold-free

Inside each `BRT birth day × PASS group`, separately transform X and E to average fractional ranks:

```text
R(v) = (average_rank(v) - 0.5) / n
```

Then center each rank at 0.5 for numerical stability.

Ranks are used to test monotonic incremental information without imposing a fitted threshold and to reduce sensitivity to extreme raw-point values.

No outcome-dependent transformation is allowed.

## Primary daily model

For every eligible `BRT day × PASS group`, fit the two-predictor logistic model:

```text
logit P(Y=1)
    = alpha
    + beta_X    * (R(X) - 0.5)
    + beta_PATH * (R(E) - 0.5)
```

`beta_X` controls continuously for the already-known MID migration ranking.

The **Map03 primary statistic is `beta_PATH`**.

Interpretation:

```text
beta_PATH > 0
    -> for comparable ranked MID impulse,
       greater directional path efficiency adds positive continuation information

beta_PATH = 0
    -> path coherence adds no incremental monotonic information beyond MID strength

beta_PATH < 0
    -> cleaner directional path is associated with lower continuation after MID control
```

Daily model eligibility requires:

- both Y classes present;
- finite X and E;
- nonzero variation in both rank predictors;
- numerical convergence of the frozen logistic fit.

A tiny fixed numerical ridge may be used only to stabilize matrix inversion; it may not be tuned from outcomes and does not change the estimand.

## Primary cross-day estimate

For each PASS group independently:

```text
PRIMARY_ESTIMATE = arithmetic mean of eligible daily beta_PATH values
```

Every eligible BRT day receives equal weight.

## Uncertainty — whole-day bootstrap

Frozen bootstrap:

```text
cluster = whole BRT birth day
N       = 5000
seed    = 2026081803
```

Resample daily `beta_PATH` values with replacement and report the percentile 95% CI of their arithmetic mean.

## Historical holdout support criterion

Historical holdout support requires, for **all three** frozen PASS groups:

```text
mean(beta_PATH) > 0
AND
CI95_lower(beta_PATH) > 0
```

If any one of PASS1, PASS2 or PASS3+ fails, then:

```text
MAP03_HISTORICAL_HOLDOUT_SUPPORT = NO
```

No subgroup may rescue another.

Even if all three pass:

```text
FORMAL_VALIDATION = NO
RUNTIME_PROMOTION = NONE
```

because the test block is historical rather than prospectively collected after freeze.

## Secondary mechanistic diagnostics — descriptive only

Map03 may report, but may not promote from this experiment:

- raw AUC of E -> Y;
- `beta_X` from the primary two-predictor model;
- `directional_mid_update_fraction_1s`;
- `both_quote_change_fraction_1s`;
- total MID path 1s;
- UP vs DOWN breakdown;
- pooled-event statistics.

These cannot rescue the primary `beta_PATH` criterion.

## Prospective continuation

Map03 prospective start is frozen before any Map03 holdout outcome is inspected:

```text
2026-08-19 00:00:00 BRT
```

Prospective maturity requires both:

```text
>= 20 eligible BRT days
>= 200000 complete eligible PASS events total
```

Formal prospective FULL PASS uses the same all-three-strata rule:

```text
mean(beta_PATH) > 0
AND
CI95_lower(beta_PATH) > 0
```

for PASS1, PASS2 and PASS3+ independently.

The historical holdout result may not change predictor, model, rank transform, target, PASS groups, bootstrap or prospective criterion.

## Anti-rescue / governance

After Map03 results are observed, do not replace or rescue the primary law by selecting:

- a favorable path-efficiency threshold;
- Q4/Q5 or any best quantile;
- a different lookback such as 250 ms, 2 s or 5 s;
- absolute path efficiency instead of directional efficiency;
- BID-only or ASK-only efficiency;
- another target (+50/+100/+300);
- PASS1-only or PASS3+-only deployment;
- UP-only or DOWN-only deployment;
- spread interaction;
- tick-rate interaction;
- alternate MID-impulse bins;
- best time-of-day subset;
- sign inversion;
- a different maturity requirement.

Any such idea requires a separately frozen later experiment.

## Runtime / frozen status

```text
MAP03_STATUS = FROZEN_RESEARCH_ONLY
PRIMARY_CONTROL_X = SIGNED_MID_IMPULSE_1S_POINTS
PRIMARY_PATH_E = DIRECTIONAL_PATH_EFFICIENCY_1S
PRIMARY_Y = HIT_200_BEFORE_RETEST
PASS_STRATA = PASS1 / PASS2 / PASS3+
PRIMARY_MODEL = DAILY_RANK_LOGISTIC_X_PLUS_E
PRIMARY_STATISTIC = BETA_PATH
PRIMARY_AGGREGATION = EQUAL_BRT_DAY_MEAN
BOOTSTRAP_CLUSTER = WHOLE_BRT_DAY
BOOT_N = 5000
BOOT_SEED = 2026081803
HISTORICAL_HOLDOUT = 2026-07-02..2026-08-10_PLUS_2026-08-12_EXCLUDE_2026-08-11
FRESH_START = 2026-08-19_00:00_BRT
PROSPECTIVE_MATURITY = 20_ELIGIBLE_DAYS_AND_200000_COMPLETE_PASSES
RUNTIME_PROMOTION = NONE
EXP27 = UNTOUCHED / SCORES_SEALED
CALIBRATION_SHADOW = UNTOUCHED / SCORES_SEALED
MAP02_PROSPECTIVE = UNTOUCHED / SCORES_SEALED
```
