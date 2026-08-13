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
TWO_STATE_DAILY_HAZARD_HMM_BRANCH = CLOSED AGAINST POST_HOC RESCUE
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
