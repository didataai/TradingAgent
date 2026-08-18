# MICRO FLOW SHADOW01 — Frozen Development Model

Status: **FROZEN DEVELOPMENT / NOT FORMALLY VALIDATED / NO RUNTIME PROMOTION**

Freeze date: 2026-08-18 BRT
Fresh evaluation start: 2026-08-19 00:00 BRT

## Purpose

Provide the live chart layout requested for the Book5 microstructure observer while keeping the predictive layer explicitly separated from validated runtime logic.

Displayed fields:

- Direction
- Continuation
- Confidence
- NET
- COUNTERFLOW
- PASS
- BIAS

`Continuation` is **not** a generic probability that price will rise/fall. It is the development-model estimate of the frozen research target:

> hit +200 GOLD points in the PASS direction before the next retest.

`Confidence` is a relative score bucket within the same PASS stratum, based on the historical distribution of SHADOW01 fitted probabilities. It is **not** statistical certainty and is not an authorization to trade.

## Scientific separation

- Map02 prospective remains unchanged and sealed under its own contract.
- Map04 prospective remains unchanged and sealed under its own contract.
- SHADOW01 is a new development model trained only on already-inspected historical data.
- SHADOW01 may be shown live for observation, but it has no runtime promotion authority.
- No BUY/SELL order, auto-trading, entry threshold, stop, target or position sizing is authorized by this model.

## Training population

Already-inspected Map03 historical holdout ledger:

- 2026-07-02 through 2026-08-10
- plus 2026-08-12
- 2026-08-11 excluded from that holdout because it had already been used for the mechanical smoke

Eligible events use the same frozen PASS outcome definition:

- outcome_complete_before_retest_60s == 1
- hit_200_before_retest in {0,1}
- finite signed MID impulse 1s
- finite opposing MID path 1s

PASS strata:

- PASS1: pass_no == 1
- PASS2: pass_no == 2
- PASS3+: pass_no >= 3

## Predictor definitions

At the PASS event:

```text
X = signed_mid_impulse_1s_points
TOTAL = total_mid_path_1s_points
COUNTERFLOW = max((TOTAL - X) / 2, 0)
```

Transformations used by SHADOW01:

```text
TX = asinh(X / 20)
TC = ln(1 + COUNTERFLOW)
```

Separate logistic model by PASS stratum:

```text
logit(P(hit +200 before retest)) = intercept + beta_x * TX + beta_counterflow * TC
```

## Frozen coefficients

### PASS1

```text
intercept        = -3.9428766403356286
beta_x           =  0.41954426272480366
beta_counterflow =  0.16817135923298430
historical base rate = 0.04157875362501010
```

### PASS2

```text
intercept        = -4.3910705931584700
beta_x           =  0.28449971217439424
beta_counterflow =  0.26039027817580020
historical base rate = 0.02684901201669265
```

### PASS3+

```text
intercept        = -4.8730026409947770
beta_x           =  0.47301521137832470
beta_counterflow =  0.37804446547486326
historical base rate = 0.02102472016945077
```

## Confidence display buckets

Confidence is based only on the historical percentile of the fitted SHADOW01 probability within the same PASS group.

Frozen cutoffs:

### PASS1

```text
MEDIUM >= 0.04202876
HIGH   >= 0.06016286
```

### PASS2

```text
MEDIUM >= 0.02636092
HIGH   >= 0.03833246
```

### PASS3+

```text
MEDIUM >= 0.02074484
HIGH   >= 0.03190625
```

Below MEDIUM is displayed as LOW.

These labels are relative historical ranking only. For example, `HIGH` does not mean a high absolute win probability.

## Live PASS semantics

The MQL5 live implementation must reproduce the frozen Map01R mechanics:

- spread baseline = median spread of the previous 30 completed one-second buckets
- qualifying tick = baseline available AND spread > baseline AND spread > previous valid tick spread
- qualifying ticks in the same or immediately following second belong to one episode
- episode activates only after one complete quiet second
- mark zone = peak spread quote `[peak_bid, peak_ask]`
- direction = sign of causal 1-second MID delta at episode birth

UP lifecycle:

- PASS1: bid > peak_ask after activation
- RETEST: bid <= peak_ask
- PASS2+: bid > peak_ask again
- FAILURE after retest: ask < peak_bid

DOWN lifecycle is symmetric.

The chart displays the newest current/recent PASS event produced by this state machine.

## Live panel contract

```text
MICRO FLOW [SHADOW]

Direction       DOWN
Continuation    4.8%
Confidence      HIGH

NET             -21.0
COUNTERFLOW       8.0
PASS                2

BIAS              ↓

SHADOW / NOT VALIDATED
```

`BIAS` is the frozen PASS direction rendered visually. It is not a BUY/SELL instruction.

## Fresh evaluation

SHADOW01 must not be declared validated from the training ledger.

Fresh evaluation begins 2026-08-19 and can reuse the separately collected Map04 prospective ledger because it contains the required PASS number, MID impulse, counterflow and +200 outcome without changing Map04 itself.

No coefficient, transform, PASS rule, target, confidence cutoff, sign inversion or subgroup rescue may be changed after fresh data begins without creating a separately frozen successor model.

## Runtime status

```text
SHADOW01_LIVE_DISPLAY = ALLOWED FOR OBSERVATION
FORMAL_VALIDATION = NO
BUY_SELL_CLASSIFIER = NO
AUTO_TRADING = NO
RUNTIME_PROMOTION = NONE
```
