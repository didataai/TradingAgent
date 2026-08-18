# MICROSTRUCTURE QUOTE-MIGRATION MAP 02 — continuous passage-efficiency law

## Status / lineage

Map02 is a new, separately frozen microstructure research line derived from the descriptive observations of Flow-Mark Map01R. It does **not** modify or rescue Map01R, Decision Replay, Exp27, Decision Calibration Shadow, Operability, or Breakout Map01.

Map01R historical exploration observed two repeatable patterns over separate chronological blocks:

1. PASS2 was weaker than matched PASS1, so pass number is a structural confound and must be controlled rather than ignored.
2. `pass_signed_mid_impulse_1s_points` showed the clearest positive ordering with `hit_200_before_retest`, whereas raw tick-rate / tick-acceleration did not show the same stable top-end behavior. Spread-ratio behavior was not stable enough across periods to be promoted as the primary signal.

Those observations are discovery only. Map02 therefore freezes a threshold-free continuous test before any new prospective score is inspected.

## Scientific question

Within the **same recross stage**, does stronger causal directional migration of the quotes at the instant of a PASS rank events by subsequent continuation probability?

In compact form:

```text
same PASS stage
+
larger signed MID migration over prior 1 second
        ->
higher probability of +200 points before next retest?
```

## Population

Source events are the unchanged Map01R PASS rows.

Eligibility:

```text
outcome_complete_before_retest_60s == 1
finite(pass_signed_mid_impulse_1s_points)
finite(hit_200_before_retest)
```

No event is created, removed or relabeled by Map02 beyond this pre-existing completeness requirement.

Map02 does not change:

- Flow episode definition;
- PEAK-SPREAD mark geometry;
- episode-close activation;
- PASS / RETEST / FAILURE semantics;
- +200 target definition;
- 60 second horizon;
- BRT day boundary.

## Primary predictor

```text
X = pass_signed_mid_impulse_1s_points
```

This is already causal in Map01R:

```text
mid = (bid + ask) / 2
raw_mid_impulse_1s_points = (mid_now - mid_at_or_before_t_minus_1s) / point
X = pass_direction * raw_mid_impulse_1s_points
```

No clipping, winsorization, quantile threshold, optimized multiplier, standardization fitted from outcomes, or best-bucket selection is allowed in the primary test.

## Primary outcome

```text
Y = hit_200_before_retest
```

`Y=1` only if the directional mid-price excursion reaches +200 MT5 points within 60 seconds and before the next retest of the same Map01R mark. The definition is inherited unchanged from Map01R.

The +200 outcome was already the primary matched binary contrast in Map01R; it is not selected post-hoc inside Map02.

## Mandatory PASS-stage stratification

Because Map01R established that continuation decays with recross number, Map02 must not pool stages naively.

Frozen groups:

```text
PASS1  : pass_no == 1
PASS2  : pass_no == 2
PASS3+ : pass_no >= 3
```

The primary law is evaluated independently in all three groups.

No alternate pass grouping may replace this grouping after scoring.

## Primary statistic — threshold-free daily AUC

For each BRT birth day and each PASS group, compute the ROC AUC of continuous `X` for binary `Y` using rank statistics.

Interpretation:

```text
AUC = 0.50  -> no ranking information
AUC > 0.50  -> larger X tends to occur on +200 continuations
AUC < 0.50  -> larger X tends to rank continuation in the wrong direction
```

A day/group is eligible for AUC only if it contains at least one `Y=1` and one `Y=0`; no arbitrary minimum event-count threshold is added.

For each PASS group:

```text
PRIMARY_ESTIMATE = arithmetic mean of eligible BRT-day AUCs
```

Every eligible BRT day receives equal weight. This prevents very high-tick / high-PASS days from dominating the law merely through event count.

## Uncertainty — whole-day bootstrap

Cluster unit:

```text
whole BRT birth day
```

Frozen bootstrap:

```text
N    = 5000
seed = 2026081801
```

Resample eligible daily AUC values with replacement and compute the arithmetic mean.

Report percentile 95% CI.

## Prospective gate

Historical Map02 analysis is diagnostic only because the feature was selected after Map01R inspection.

Fresh-forward start:

```text
2026-08-19 00:00:00 BRT
```

Scores from prospective events must not be used to alter predictor, target, pass grouping, bootstrap or gate.

Maturity requires both:

```text
>= 20 eligible BRT days
>= 200000 complete eligible PASS events total
```

Formal prospective FULL PASS requires, for **all three** frozen pass groups:

```text
mean_daily_AUC > 0.50
AND
CI95_lower > 0.50
```

If any one of PASS1, PASS2 or PASS3+ fails that rule at maturity, the primary Map02 law is not FULL PASS.

No sign inversion is allowed after failure.

## Secondary diagnostics — no promotion authority

The following are reported descriptively and cannot rescue the primary gate:

- pooled event-level AUC for `X`;
- +50 / +100 / +300 continuation outcomes;
- `mfe_60_points` relationship with `X`;
- UP vs DOWN subgroup results;
- `pass_spread_ratio`;
- `pass_tick_rate_ratio_1s`;
- `pass_tick_accel_1s_vs_prev4s`.

These variables may characterize the mechanism but cannot become a runtime rule from Map02 without a new separately frozen experiment.

## Negative-control interpretation

Tick rate and tick acceleration are retained specifically as descriptive controls for the alternative explanation that the observed effect is only generic quote activity.

Map02 does not require these controls to equal 0.50 and does not fit a threshold from them. Their purpose is mechanistic comparison only.

## Historical discovery blocks already inspected before this freeze

Map01R / pre-Map02 exploration inspected historical results through approximately `2026-07-01 BRT`, plus the original one-day `2026-08-11` mechanical smoke. These dates are **not fresh OOS for Map02**.

Any historical Map02 score on those rows is therefore explicitly labeled:

```text
HISTORICAL_DIAGNOSTIC_ONLY
```

It may be used for understanding and reproduction, not formal validation.

## Anti-rescue / governance

After Map02 scores are observed, do not promote or substitute:

- a favorable X threshold;
- Q4/Q5 or another quantile;
- absolute-value MID impulse;
- 250 ms or 5 s impulse instead of 1 s;
- BID-only or ASK-only impulse;
- spread-ratio interaction;
- tick-rate / tick-acceleration threshold;
- PASS1-only rule;
- direction-only rule;
- another target among +50/+100/+300;
- another maturity requirement;
- sign inversion.

Any such idea requires a new freeze and a separate experiment.

## Runtime status

```text
MAP02_STATUS = FROZEN_RESEARCH_ONLY
PRIMARY_X = PASS_SIGNED_MID_IMPULSE_1S_POINTS
PRIMARY_Y = HIT_200_BEFORE_RETEST
PASS_STRATA = PASS1 / PASS2 / PASS3+
PRIMARY_METRIC = EQUAL_DAY_MEAN_AUC
BOOTSTRAP_CLUSTER = WHOLE_BRT_DAY
BOOT_N = 5000
BOOT_SEED = 2026081801
FRESH_START = 2026-08-19_00:00_BRT
MATURITY = 20_ELIGIBLE_DAYS_AND_200000_COMPLETE_PASSES
RUNTIME_PROMOTION = NONE
EXP27 = UNTOUCHED / SCORES_SEALED
CALIBRATION_SHADOW = UNTOUCHED / SCORES_SEALED
```
