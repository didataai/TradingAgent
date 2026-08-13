# GOLD Research Decisions

## 2026-08-12 — External AI roadmap review

Purpose: record meta-level decisions about suggested research directions without changing runtime rules.

### Accepted ideas
- Freeze a genuinely unseen forward/shadow period before any promotion.
- Preserve the path-distribution mindset instead of reducing GOLD to raw up/down labels.
- Use nested/walk-forward or prequential validation for future integrated models.
- Treat GBM/boosted trees later as a challenger benchmark to the parsimonious structural kernel, not as an immediate replacement.

### Deferred / revised ideas
- A broad STATE_VECTOR may be useful later as a schema, but current Track D evidence says the first integrated structural core should start from Active Structural Frontier + CorridorPosition + DwellBars. Add D1/Clock/Z/Fib/weekday only through pre-frozen incremental tests.
- PhaseMaturity/EXTREME_FINISH remains a separate Track A context candidate, not a runtime timer or automatic reversal signal.
- Position sizing/Kelly, adaptive stops and horizon rules are downstream decision-layer research and require calibrated probabilities, costs/slippage and fresh forward validation first.

### Rejected as immediate actions
- Do not assign hand-chosen scoring weights such as +0.3/-0.5/+0.4 to existing findings.
- Do not promote shadow/research findings into runtime because they look individually strong.
- Do not re-open the 288-slot directional Market Clock as if it were unfinished: whole-clock FWER correction was already completed and no exact directional slot survived.

### Review of supplied circular-shift Market Clock script
- It tests a different null/target than the completed Track A directional continuation/reversal scan: raw forward return by clock slot rather than current-direction-oriented ATR-normalized response.
- The script calls its method Westfall-Young step-down, but the implementation is single-step maxT.
- Circularly shifting an entire day also shifts the known intraday volatility/coverage pattern; that is not equivalent to the existing whole-day sign-flip null, which preserves every slot's volatility and dependence structure and only removes directional sign.
- The code as supplied detects generic time columns but not `available_at_brt`, defines `broker_day` as calendar date, and applies no chronological TRAIN/VALIDATION/TEST split before permutation. It should therefore not be run unchanged on the current research parquet.
- The script can be retained only as a sensitivity analysis for a distinct hypothesis after being adapted; it should not supersede the completed FWER result.

### Current research priority
Continue the frozen Track D sequence. Exp22 produced only a tiny OOS HMM score gain with a near-degenerate 2-state chain. Exp23 remains the next frozen test: compare the causal HMM against a static stationary-mixture control to determine whether temporal latent-state propagation adds information beyond the mixture/emission correction.

Runtime promotion: NONE.

## 2026-08-12 23:28 BRT — Exp23 execution contract issued

Exp23 remains a strict ablation of the already inspected Exp22 model. No HMM parameter is re-estimated.

Frozen Exp22 parameters used by the runnable Exp23 prompt:

```text
THETA_SEMI_FROZEN:
ADVANCE   [-2.337951, +0.920362, -0.617819]
RECAPTURE [-2.788824, -0.786389, -0.535507]

delta LOW/HIGH = [-1.826423, +0.053321]
A = [[5.27296923e-09, 9.99999995e-01],
     [2.14968253e-02, 9.78503175e-01]]
```

Primary comparison:

```text
CAUSAL_HMM
  pre-day prior propagated from previous filtered posterior
  same-day outcomes update posterior only after same-day scoring

vs

STATIC_MIXTURE
  same frozen latent emissions
  same frozen transition matrix
  same SEMI geometry+dwell backbone
  but every OOS day uses the stationary distribution of A
  no filtering and no prior-day information
```

Primary survival criterion: CAUSAL_HMM must improve STATIC_MIXTURE on BOTH multiclass Brier and LogLoss in BOTH Validation and Test, with positive day-cluster gain. Static mixture vs SEMI is a secondary mechanism audit: if STATIC captures essentially all Exp22 gain while CAUSAL adds nothing, reject useful daily temporal latent memory and interpret Exp22 as a static-mixture/recalibration effect.

The execution also prints the stationary distribution and the non-unit eigenvalue of A. This is a pre-declared diagnostic because the magnitude of the second eigenvalue measures how quickly prior-state deviations from stationarity are forgotten under one HMM transition.

Do not add 3/4 states, alternate initializations, same-day filtering, Clock/D1/Z/Fib/weekday, side-specific shifts, rolling windows, or intraday HMMs after the result.

If Exp23 rejects temporal HMM information, the preferred next structural family is not an immediate GBM pivot. The next isolated candidate is active-corridor scale/width as a common EXIT-hazard modifier beyond CorridorPosition + DwellBars, frozen only after Exp23 is interpreted.

Runtime promotion: NONE.

## 2026-08-12 23:41 BRT — Exp23 result: temporal-state ablation

### Question
Does the temporal propagation/filtering of the frozen Exp22 daily 2-state HMM add OOS probability information beyond using the exact same emissions under the stationary mixture of the same transition matrix?

### Frozen mechanism audit

```text
stationary LOW/HIGH = 0.02104444 / 0.97895556
second eigenvalue = -0.02149682
|lambda2| = 0.02149682
```

Therefore a deviation of a 2-state prior from stationarity contracts to about 2.15% of its previous magnitude after one daily transition. This was pre-declared as a temporal-memory diagnostic, not discovered post hoc.

### Event-weighted primary scores

```text
VALIDATION
SEMI   Brier=.165580887 LogLoss=.301127874
STATIC Brier=.165435852 LogLoss=.300804151
CAUSAL Brier=.165434447 LogLoss=.300803952
CAUSAL-STATIC = -0.000001405 Brier / -0.000000199 LogLoss

TEST
SEMI   Brier=.159127086 LogLoss=.285882713
STATIC Brier=.159054846 LogLoss=.285775157
CAUSAL Brier=.159053900 LogLoss=.285774202
CAUSAL-STATIC = -0.000000946 Brier / -0.000000955 LogLoss
```

At row weighting CAUSAL is microscopically better than STATIC, but the effect is approximately 1e-6 and is not the frozen primary inference because correlated rows within a BRT day are not independent.

### Day-cluster primary inference — CAUSAL over STATIC

Positive means temporal filtering helps.

```text
VALIDATION
Brier   MeanGain=-.000015748 CI95[-.000029231,-.000003995] P>0=.28%
LogLoss MeanGain=-.000034102 CI95[-.000054547,-.000015770] P>0=.00%

TEST
Brier   MeanGain=-.000016335 CI95[-.000032514,-.000001529] P>0=1.45%
LogLoss MeanGain=-.000031976 CI95[-.000055769,-.000010202] P>0=.09%
```

The frozen temporal-memory survival criterion fails cleanly in both OOS periods. Under equal-day cluster weighting, CAUSAL is consistently worse than STATIC.

### Static mixture over SEMI — mechanism audit

```text
VALIDATION
Brier   MeanGain=+.001590230 CI95[+.000902619,+.002379786] P>0=100%
LogLoss MeanGain=+.003480308 CI95[+.002265469,+.004851829] P>0=100%

TEST
Brier   MeanGain=+.001381470 CI95[+.000620420,+.002269838] P>0=100%
LogLoss MeanGain=+.003016538 CI95[+.001662806,+.004575776] P>0=100%
```

Thus the useful part of Exp22 is reproduced without temporal filtering. The HMM gain is a fixed mixture/calibration-map effect, not evidence that the pre-day latent posterior tracks a useful persistent regime.

### Direct temporal diagnostic

```text
VALIDATION prior P(HIGH): mean=.97866356 std=.00034838
TEST       prior P(HIGH): mean=.97867174 std=.00033943
STATIC P(HIGH)=.97895556
mean |row Pexit_causal-Pexit_static| ~3e-5
rho(prior deviation, same-day SEMI exit residual)=-.1009
```

The causal prior has almost no useful day-to-day variation around stationarity.

### Formal status

```text
EXP23_TEMPORAL_MEMORY_SURVIVAL = REJECTED
DAILY_TWO_STATE_HMM_TEMPORAL_INFORMATION = REJECTED_FOR_FROZEN_MODEL
STATIC_STATIONARY_MIXTURE_REPRODUCES_EXP22_GAIN = CONFIRMED
EXP22_HMM_GAIN_MECHANISM = STATIC_MIXTURE / CALIBRATION_MAP, NOT TEMPORAL_FILTERING
TWO_STATE_DAILY_HAZARD_HMM_BRANCH = CLOSED AGAINST POST_HOC_RESCUE
SEMI_MARKOV_ACTIVE_CORRIDOR_BACKBONE = PRESERVED
EXIT_SIDE_GEOMETRY = PRESERVED
RUNTIME_PROMOTION = NONE
```

This rejects the specific frozen daily 2-state hazard HMM, not HMMs as a mathematical family in all possible representations.

### Review of external suggestion: fit one static logit shift on TRAIN

The suggestion is parsimonious in spirit but is not the preferred next experiment. The Exp21 SEMI multinomial logistic model was already fit by maximum likelihood on the same TRAIN rows with separate ADVANCE and RECAPTURE intercepts. In the exact unrounded fit, the intercept score equations already match the TRAIN class totals, so a new common EXIT-vs-STAY intercept fitted on the same TRAIN should be approximately zero. It therefore should not be assumed to reproduce the STATIC_MIXTURE OOS gain.

Also, the stationary mixture is not mathematically identical to one constant Platt-style shift:

```text
p_static(exit | x)
 = w_LOW  * sigmoid(logit(p_semi_exit(x)) + delta_LOW)
 + w_HIGH * sigmoid(logit(p_semi_exit(x)) + delta_HIGH)
```

A mixture of shifted sigmoids is generally not equal to `sigmoid(logit(p)+single_delta)`. Because HIGH has ~97.9% weight the map is close to a small shift over much of the support, but not exactly a one-parameter recalibration.

Do not spend a full experiment fitting a redundant same-TRAIN common intercept merely because the OOS static mixture helped.

## Exp24 frozen — ACTIVE CORRIDOR SCALE / ONE-STEP EXIT HAZARD

### Scientific question
After current CorridorPosition and causal DwellBars are known, does the absolute scale of the ACTIVE corridor add stable information about whether the next M5 state is EXIT vs STAY?

This is distinct from the legacy Exp10 corridor-width diagnostic: Exp10 used the superseded immortal-L2 representation and a 120m first-passage target. Exp24 uses the active frontier of Exp16+ and the one-step M5 semi-Markov kernel of Exp20/21.

### Frozen feature

```text
CorridorWidthATR_t =
    (oriented distance from active back boundary to active forward boundary)
    / ATR_t

Scale_t = log(CorridorWidthATR_t)
```

No buckets or thresholds.

### Frozen models

BASE = exact Exp21 semi-Markov kernel:

```text
ADV vs STAY = a1 + b1*geo_logit + c1*log_dwell
REC vs STAY = a2 + b2*geo_logit + c2*log_dwell
```

SCALE_EXTENDED adds ONE common coefficient `k` to both exit logits:

```text
ADV vs STAY += k*Scale
REC vs STAY += k*Scale
```

Because the same term is added to both exit logits, `P(ADVANCE | EXIT)` is mathematically unchanged. Exp24 tests only EXIT TIMING/HAZARD.

### Fit/evaluation

```text
fit k on TRAIN only while keeping all Exp21 coefficients frozen
Validation/Test evaluation only
primary = multiclass Brier + LogLoss in BOTH Validation and TEST
primary dependence control = BRT-day cluster gain
secondary = EXIT hazard Brier/LogLoss + equal-day calibration residual
```

### Survival criterion

Scale survives only if the common hazard coefficient improves BASE in BOTH Validation and TEST on Brier and LogLoss, with positive day-cluster support. TRAIN coefficient sign alone is not evidence.

### Anti-repeat / prohibited rescue

- no width buckets or thresholds;
- no min-distance / max-distance alternate feature after seeing the result;
- no nonlinear spline/polynomial;
- no interaction with position or dwell;
- no Clock/D1/Z/Fib/weekday;
- no HMM rescue;
- no L4/L5;
- no runtime promotion from this exploratory TEST.

If scale fails, the active one-step structural kernel remains `Position + Dwell`; the next research decision should address whether to move to a genuinely fresh forward validation block before adding additional context families.

Runtime promotion: NONE.

## 2026-08-12 23:49 BRT — Exp24 execution contract finalized

The Exp24 implementation is frozen as a strict added-variable test.

```text
FROZEN BASE PARAMETERS
ADVANCE   [-2.337951, +0.920362, -0.617819]
RECAPTURE [-2.788824, -0.786389, -0.535507]
```

Only one new degree of freedom is allowed:

```text
k = common coefficient on Scale_t
Scale_t = log(CorridorWidthATR_t)
```

All six Exp21 coefficients remain exactly frozen. The model is not jointly refit. This prevents Scale from reallocating explanatory power already assigned to CorridorPosition or DwellBars and makes Exp24 a clean incremental-information test.

The common term is added identically to ADVANCE-vs-STAY and RECAPTURE-vs-STAY, so `P(ADVANCE|EXIT)` remains exactly invariant by algebra. Only EXIT-vs-STAY hazard is tested.

The runnable execution must also print descriptive correlations `Spearman(Scale, log_dwell)` and `Spearman(Scale, geo_logit)` by TRAIN/VALIDATION/TEST. These are diagnostics only: no orthogonalization, thresholds, interactions, feature substitutions or conditional slicing are allowed after inspection.

`k` is fitted by one-dimensional TRAIN-only maximum likelihood with Newton updates on the binary EXIT likelihood induced by the frozen SEMI model. Validation and Test receive the exact fitted `k` without updating.

Primary decision remains unchanged: SCALE_EXTENDED must improve frozen BASE in BOTH Validation and Test on multiclass Brier and LogLoss, with positive BRT-day cluster score gain. EXIT hazard metrics and equal-day calibration are secondary diagnostics. Exit-side probabilities must remain numerically identical up to floating-point error.

Runtime promotion: NONE. Fresh forward/nested validation remains mandatory for any later promotion.

## 2026-08-13 00:10 BRT — Exp24 result + Exp25 estimand audit result

### Exp24 result remains frozen as REJECTED

Exp24 fitted only the common scale coefficient on top of the frozen Exp21 SEMI kernel:

```text
k = -0.217885747
exp(k) = 0.804217
2^k = 0.859825
```

Row/state-weighted OOS scores improved, but the preregistered equal-day primary criterion failed with negative confidence intervals in Validation and Test; equal-episode diagnostics were even more negative. Equal-day class calibration worsened. Exit-side invariance held to floating point (`max_abs diff = 1.11e-16`). Therefore Exp24 is not rescued or reopened.

Formal status remains:

```text
ACTIVE_CORRIDOR_SCALE_INCREMENTAL_INFORMATION = REJECTED_UNDER_FROZEN_EXP24_CONTRACT
SCALE_PHYSICAL_SIGN = NOT_ACCEPTED
POSITION_PLUS_DWELL = PRESERVED
RUNTIME_PROMOTION = NONE
```

### Exp25 question

Does the contradiction between row/state-weighted and equal-day/equal-episode scores come from dependence correction, or from silently changing the estimand by changing cluster weights?

Exp25 fitted nothing and reused the exact frozen Exp24 BASE/SCALE predictions.

### Three estimands — exact observed divergence

```text
VALIDATION
Brier   STATE +0.000367618 | DAY -0.005392613 | EPISODE -0.017539285
LogLoss STATE +0.001344023 | DAY -0.011831980 | EPISODE -0.028850312

TEST
Brier   STATE +0.001246203 | DAY -0.006302204 | EPISODE -0.016177614
LogLoss STATE +0.003743185 | DAY -0.010850953 | EPISODE -0.029253616
```

Positive means SCALE has lower loss than BASE. Therefore the sign reversal is not a numerical accident: the three weighting schemes answer materially different scientific questions.

### State-weighted whole-day bootstrap

Whole BRT days were resampled with replacement, but each replicate preserved the state-level target weight by using `total gain / total sampled states`.

```text
VALIDATION
Brier   +0.000367618 CI[-0.001088114,+0.001750727] P>0=68.38%
LogLoss +0.001344023 CI[-0.001888555,+0.003964425] P>0=80.50%

TEST
Brier   +0.001246203 CI[-0.000699452,+0.003266137] P>0=89.02%
LogLoss +0.003743185 CI[-0.000009998,+0.006918390] P>0=97.43%
```

The state-weighted point gain is positive in both OOS periods, but the dependence-aware confidence intervals still cross zero. Thus Exp25 does NOT provide new confirmatory evidence for Scale; it only clarifies the estimand issue.

### Informative cluster size is strongly present

Cluster size is positively related to mean SCALE-vs-BASE gain in every split and at both day and episode levels. Examples:

```text
VALIDATION rho(day N,meanGain): Brier +0.5737 / LL +0.7324
VALIDATION rho(ep N,meanGain):  Brier +0.6122 / LL +0.6686
TEST rho(day N,meanGain):       Brier +0.4749 / LL +0.5508
TEST rho(ep N,meanGain):        Brier +0.5311 / LL +0.5837
```

The exact weighting identity also holds numerically:

```text
STATE_WEIGHTED - EQUAL_CLUSTER
= Cov(cluster_size, cluster_mean_gain) / E[cluster_size]
```

For example, Validation LogLoss STATE-DAY difference is +0.013176003 and the covariance identity gives exactly +0.013176003; Test LogLoss STATE-EP difference is +0.032996801 and the identity gives exactly +0.032996801.

This demonstrates that the pooled/equal-cluster sign reversal is driven by informative cluster size / weighting, not merely by a generic failure to account for dependence.

### Permanent methodological rule from Exp25

```text
ESTIMAND MUST BE DECLARED BEFORE THE EXPERIMENT.
DEPENDENCE CORRECTION MUST PRESERVE THAT ESTIMAND.
```

For Track D transition-kernel questions of the form `given the current M5 structural state, what is the next-state distribution?`, the natural primary estimand is STATE_WEIGHTED because each runtime prediction corresponds to one current state. The primary uncertainty procedure is therefore whole-day cluster resampling with the replicate statistic `total score gain / total sampled states`.

DAY_WEIGHTED and EPISODE_WEIGHTED remain mandatory heterogeneity diagnostics. They are not silently substituted for the state-level estimand. If a future deployment policy acts once per episode or once per day, that policy must preregister the corresponding estimand separately.

Exp24 remains rejected and Scale cannot be rescued from this audit.

## Exp26 frozen — BACKBONE ESTIMAND RE-AUDIT

Before adding any new Track D feature, re-audit the two surviving structural steps under the corrected inferential contract.

No new feature and no refit beyond deterministic reconstruction of the original frozen baselines.

### Frozen comparisons

```text
A) Exp20 geometry-only one-step kernel vs frozen TRAIN class-frequency constant baseline.

Exp20 geometry kernel:
ADVANCE-vs-STAY   intercept=-3.517028, geo=+0.857591
RECAPTURE-vs-STAY intercept=-3.813144, geo=-0.844111

B) Exp21 semi-Markov kernel vs Exp20 geometry-only kernel.

Exp21 SEMI:
ADVANCE   [-2.337951, +0.920362, -0.617819]
RECAPTURE [-2.788824, -0.786389, -0.535507]
```

### Primary inference

For Validation and Test, use STATE_WEIGHTED Brier and LogLoss with whole-day cluster bootstrap preserving state weights (`sum gain / sum states` per bootstrap replicate).

Also report equal-day and equal-episode estimands as heterogeneity diagnostics and cluster-size correlations. No feature tuning, no coefficient refit, no thresholds, no Clock/D1/Z/Fib/weekday, no Scale, no HMM.

### Interpretation

If Exp20 geometry and Exp21 dwell improvements remain positive under the corrected STATE_WEIGHTED cluster inference, the `Active Frontier + Position + Dwell` backbone is methodologically strengthened before fresh forward validation. If one fails, its previous status must be downgraded for future integration even though no old result is rewritten retroactively.

Repeatedly inspected TEST remains exploratory. No runtime promotion.

## 2026-08-13 09:27 BRT — Exp26 result / Exp27 fresh forward shadow frozen

### Exp26 result — backbone estimand re-audit

The Exp26 sample reproduced the Exp20/21 dynamic universe exactly:

```text
TRAIN      5612 states / 596 episodes / 207 days
VALIDATION 1959 states / 204 episodes / 80 days
TEST       2096 states / 212 episodes / 73 days
```

#### A) Geometry over constant — strongly reaffirmed

STATE_WEIGHTED whole-day bootstrap preserving state weights:

```text
VALIDATION
Brier   +0.013625195 CI95[+0.007886861,+0.020396874] P>0=100.00%
LogLoss +0.071308742 CI95[+0.058585150,+0.086666314] P>0=100.00%

TEST
Brier   +0.011016748 CI95[+0.003736423,+0.019730017] P>0=99.87%
LogLoss +0.066682174 CI95[+0.050761125,+0.086336079] P>0=100.00%
```

Equal-day and equal-episode estimands are also strongly positive in both OOS periods. Therefore active CorridorPosition is reaffirmed as the strongest current Track D state coordinate.

Formal status:

```text
ACTIVE_STRUCTURAL_FRONTIER = PRESERVED
CORRIDOR_POSITION = STRONGLY_REAFFIRMED
ONE_STEP_GEOMETRY_KERNEL = STRONG_EXPLORATORY_BACKBONE
```

#### B) Dwell over geometry — positive but strict reconfirmation not complete

STATE_WEIGHTED whole-day bootstrap preserving state weights:

```text
VALIDATION
Brier   +0.003132413 CI95[-0.000496886,+0.007069943] P>0=95.36%
LogLoss +0.016177007 CI95[+0.007808771,+0.025290279] P>0=100.00%

TEST
Brier   +0.005169096 CI95[+0.000163469,+0.010445175] P>0=97.81%
LogLoss +0.022839282 CI95[+0.011982976,+0.033511957] P>0=100.00%
```

Three of four primary OOS checks have CI95 entirely above zero. Validation Brier is positive but its CI crosses zero slightly; therefore the frozen rule requiring BOTH Brier and LogLoss in BOTH OOS periods is not fully satisfied.

Equal-day and equal-episode gains remain strongly positive in Validation and Test. Cluster-size diagnostics show negative association between cluster size and Dwell gain, especially at episode level, so longer episodes receive more state weight precisely where Dwell adds less incremental score improvement.

Formal status:

```text
DWELL_INCREMENTAL_INFORMATION = POSITIVE_BUT_NOT_FULLY_RECONFIRMED
SEMI_MARKOV_EXTENSION = PRESERVED_AS_FROZEN_CHALLENGER
POSITION_PLUS_DWELL = NOT_YET_FINAL
FRESH_FORWARD_CONFIRMATION = REQUIRED
```

Scale remains rejected under Exp24; the frozen daily 2-state temporal HMM remains rejected under Exp23. No historical result is post-hoc rescued.

### Exp27 frozen — FRESH FORWARD BACKBONE SHADOW

Purpose: obtain genuinely prospective evidence for the frozen backbone without reusing the repeatedly inspected historical TEST.

Frozen start:

```text
SHADOW_START = 2026-08-13 00:00:00 BRT
```

Only data with causal state_time at or after SHADOW_START may enter Exp27.

Frozen models:

```text
MODEL_0 CONST
  TRAIN historical class-frequency baseline from Exp20/26

MODEL_1 GEO
  THETA_GEO_FROZEN
  ADVANCE-vs-STAY   [-3.517028, +0.857591]
  RECAPTURE-vs-STAY [-3.813144, -0.844111]

MODEL_2 SEMI
  THETA_SEMI_FROZEN
  ADVANCE   [-2.337951, +0.920362, -0.617819]
  RECAPTURE [-2.788824, -0.786389, -0.535507]
```

No parameter may be updated after SHADOW_START. No Scale, HMM, Clock, D1, Z, Fib, weekday, new threshold, interaction, new target or new feature may enter Exp27.

Maturity gate — do not inspect model scores before BOTH are true:

```text
eligible BRT days >= 60
AND
dynamic structural states >= 1500
```

The counts needed only to determine maturity may be inspected; Brier, LogLoss, AUC, calibration, class residuals and model-comparison gains must remain unseen until the gate is met.

Final one-shot primary comparisons:

```text
A) GEO vs CONST
B) SEMI vs GEO
```

Primary estimand = STATE_WEIGHTED. Dependence-aware inference = whole-day bootstrap preserving state weights in every replicate (`sum score gain / sum sampled states`). Equal-day and equal-episode estimands remain secondary heterogeneity diagnostics.

Frozen prospective interpretation:

```text
If GEO beats CONST on Brier AND LogLoss with CI95 > 0:
    prospective support for Active Frontier + CorridorPosition is obtained.

If SEMI beats GEO on Brier AND LogLoss with CI95 > 0:
    prospective support for Dwell as an incremental semi-Markov coordinate is obtained.

If either fails:
    downgrade that component for future integration; do not retune on the shadow.
```

Exp27 is validation-only. Runtime promotion remains NONE. Costs/slippage and any later decision-layer research are separate downstream gates.
