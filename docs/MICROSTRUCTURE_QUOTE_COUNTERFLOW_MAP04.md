# MICROSTRUCTURE QUOTE COUNTERFLOW MAP04 — incremental opposing-path law

## Status / lineage

Map04 is a new, separately frozen prospective microstructure experiment.

It is motivated by a post-unseal diagnostic from Map03. Map03 itself remains a failed primary hypothesis and is never sign-inverted or relabeled as success.

Map03 asked whether a cleaner directional path added continuation information after controlling signed MID impulse. The frozen Map03 holdout returned negative `beta_path` in all three PASS strata. Post-hoc diagnostics then showed that, at comparable signed MID impulse, larger gross MID path tended to associate with continuation. This diagnostic is discovery only.

Map04 freezes a direct, threshold-free test of the specific counterflow mechanism before any fresh Map04 event is scored.

Map02 prospective, Exp27 and Decision Calibration Shadow remain untouched / sealed. Runtime promotion = NONE.

## Scientific question

Within the same PASS stage and after controlling the continuous signed MID impulse over the prior one second, does a larger amount of MID movement *against* the PASS direction during that same second rank subsequent continuation probability upward?

Conceptually:

```text
same PASS stage
+ same net directional MID impulse
+ more opposing quote-path movement inside the prior 1s
        ->
higher probability of +200 points before next retest?
```

This is a quote-path / counterflow hypothesis. With BID/ASK only, it must not be described as confirmed trade absorption or tape aggression.

## Frozen source event

Source events are unchanged Map01R PASS events using:

- debounced Flow Episode definition;
- PEAK-SPREAD mark geometry;
- activation at episode close;
- unchanged PASS / RETEST / FAILURE lifecycle;
- full BRT-day reset;
- `point = 0.01` exact guard.

Map04 does not alter event identity or outcome semantics.

## Primary control

```text
X = signed_mid_impulse_1s_points
```

At PASS tick `i`, with PASS direction `d` in `{+1,-1}` and `j` the last valid tick at-or-before `t_i - 1 second`:

```text
X = d * (MID_i - MID_j) / point
```

No threshold, clipping, quantile or fitted standardization is allowed.

## Primary predictor — opposing MID path

Over the exact same tick path from `j` to `i`, let:

```text
TOTAL_PATH = sum(abs(delta MID)) / point
```

Define directional supporting and opposing path components:

```text
SUPPORTING_PATH = (TOTAL_PATH + X) / 2
OPPOSING_PATH   = (TOTAL_PATH - X) / 2
```

Frozen primary predictor:

```text
C = opposing_mid_path_1s_points = max(0, OPPOSING_PATH)
```

The `max(0, ...)` guard is numerical only for floating-point roundoff; triangle inequality makes the theoretical value non-negative.

Interpretation: `C` measures how much MID path traveled against the eventual PASS direction inside the prior one second. It does not count trades and does not infer buyer/seller identity.

## Primary outcome

Inherited unchanged from Map01R / Map02 / Map03:

```text
Y = hit_200_before_retest
```

`Y=1` only when the directional MID reaches +200 MT5 points within 60 seconds and before the next retest of the same frozen peak-spread mark.

## PASS-stage stratification

Frozen groups:

```text
PASS1  : pass_no == 1
PASS2  : pass_no == 2
PASS3+ : pass_no >= 3
```

No regrouping after scoring.

## Primary model

For each eligible BRT day and PASS group independently, transform continuous `X` and `C` to within-cell fractional ranks and fit the same ridge-stabilized rank-logit family used by Map03:

```text
logit P(Y=1) = alpha + beta_X * rank(X) + beta_C * rank(C)
```

Frozen ridge:

```text
1e-8
```

Primary effect:

```text
beta_C
```

The model asks whether opposing path adds information beyond the already-known continuous net MID impulse.

## Equal-day aggregation / uncertainty

For each PASS group:

```text
PRIMARY_ESTIMATE = arithmetic mean of eligible daily beta_C values
```

Whole BRT days receive equal weight.

Frozen bootstrap:

```text
cluster = whole BRT day
N       = 5000
seed    = 2026081804
CI      = percentile 95%
```

## Fresh-forward gate

Frozen start:

```text
2026-08-19 00:00:00 BRT
```

No date before the fresh start can contribute to Map04 formal scoring.

Maturity requires both:

```text
>= 20 eligible BRT days
>= 200000 complete eligible PASS events total
```

Before maturity:

```text
MAP04_PROSPECTIVE_STATUS = ACCUMULATING
PRIMARY_SCORES = SEALED
```

No beta, CI, sign, AUC or subgroup directional score may be printed before maturity.

## Formal FULL PASS

At maturity, all three frozen PASS groups must satisfy:

```text
mean_daily_beta_C > 0
AND
CI95_lower > 0
```

If any group fails, Map04 PRIMARY FULL PASS = NO.

No sign inversion, PASS-stage dropping, threshold rescue or target substitution is authorized.

## Secondary diagnostics — no promotion authority

After maturity only, the following may be reported descriptively:

- supporting MID path;
- total MID path;
- raw AUC of opposing path;
- UP vs DOWN subgroup behavior;
- directional MID update fraction;
- both-quote-change fraction;
- +50 / +100 / +300 outcomes if already available unchanged.

None can rescue the frozen primary gate.

## Anti-rescue

After Map04 scoring, do not promote or substitute:

- a favorable counterflow threshold;
- quantile/top bucket;
- total path instead of opposing path;
- supporting path instead of opposing path;
- ratio/efficiency redefinition;
- 250 ms / 5 s instead of 1 s;
- PASS1-only / PASS2-only / PASS3+-only rule;
- direction-only rule;
- another target;
- sign inversion;
- different maturity gate.

Any such idea requires a separately frozen experiment.

## Frozen status

```text
MAP04_STATUS = FROZEN_RESEARCH_ONLY
PRIMARY_CONTROL = SIGNED_MID_IMPULSE_1S_POINTS
PRIMARY_PREDICTOR = OPPOSING_MID_PATH_1S_POINTS
PRIMARY_OUTCOME = HIT_200_BEFORE_RETEST
PASS_STRATA = PASS1 / PASS2 / PASS3+
PRIMARY_MODEL = DAILY_RANK_LOGIT_X_PLUS_COUNTERFLOW
PRIMARY_EFFECT = BETA_COUNTERFLOW
BOOTSTRAP_CLUSTER = WHOLE_BRT_DAY
BOOT_N = 5000
BOOT_SEED = 2026081804
FRESH_START = 2026-08-19_00:00_BRT
MATURITY = 20_ELIGIBLE_DAYS_AND_200000_COMPLETE_PASSES
MAP03_PRIMARY = FAILED / NOT_SIGN_INVERTED
MAP02_PROSPECTIVE = UNTOUCHED / SCORES_SEALED
EXP27 = UNTOUCHED / SCORES_SEALED
CALIBRATION_SHADOW = UNTOUCHED / SCORES_SEALED
RUNTIME_PROMOTION = NONE
```
