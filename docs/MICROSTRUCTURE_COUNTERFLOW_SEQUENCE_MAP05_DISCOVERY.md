# MICROSTRUCTURE COUNTERFLOW SEQUENCE MAP05 — HISTORICAL DISCOVERY PROTOCOL

Status: HISTORICAL DISCOVERY ONLY  
Formal validation: NO  
Runtime promotion: NONE  
Map02 / Map04 / Shadow01 prospective lines: UNTOUCHED

## Motivation

Map03 rejected the hypothesis that cleaner directional quote-path efficiency adds positive continuation information after controlling for signed MID impulse. A post-hoc diagnostic suggested that greater gross/opposing quote path may instead contain information. Map04 prospectively tests the amount of opposing path.

Map05 Discovery asks a distinct mechanistic question:

> Conditional on signed MID impulse and total opposing path in the causal 1-second PASS window, does the temporal location of opposing path matter?

Specifically, does opposing path concentrated earlier in the 1-second window, followed by recovery into the PASS, rank higher +200 continuation than opposing path concentrated late?

This line is discovery only because the hypothesis was motivated by already-inspected historical behavior. Historical results cannot become formal validation.

## Reused event semantics

All event geometry and lifecycle semantics are imported unchanged from Map01R / Map03 lean reproduction:

- 30 completed 1-second spread buckets baseline;
- qualifying tick = baseline available AND spread expanded AND actual spread widening;
- debounced Flow Episode;
- PEAK_SPREAD_ZONE mark;
- activation after episode close;
- PASS1 / RETEST / PASS2+ / FAILURE lifecycle;
- target = hit +200 points in frozen PASS direction before next retest, within the existing 60-second outcome horizon.

No new episode threshold is introduced.

## Causal path window

For each PASS at time `t0`:

- reference = last valid tick at or before `t0 - 1000 ms`;
- split = last valid tick at or before `t0 - 500 ms`;
- end = PASS tick.

For each MID transition `dMID` inside the window and frozen PASS direction `D in {-1,+1}`:

```text
signed_increment = D * dMID / point
supporting_increment = max(signed_increment, 0)
opposing_increment   = max(-signed_increment, 0)
```

Frozen derived quantities:

```text
NET_1S = D * (MID_pass - MID_ref) / point

OPP_EARLY = sum(opposing_increment) over first ~500 ms
OPP_LATE  = sum(opposing_increment) over last  ~500 ms
OPP_TOTAL = OPP_EARLY + OPP_LATE

SUP_EARLY = sum(supporting_increment) over first ~500 ms
SUP_LATE  = sum(supporting_increment) over last  ~500 ms

SEQUENCE_CONTRAST = (OPP_EARLY - OPP_LATE) / OPP_TOTAL
```

`SEQUENCE_CONTRAST` is defined only when `OPP_TOTAL > 0`.

Interpretation:

- `+1` = opposing path almost entirely early;
- `0` = opposing path balanced early/late;
- `-1` = opposing path almost entirely late.

This is quote-path language only. Do not label it tape absorption or aggressor absorption.

## Frozen discovery question

Within each PASS stratum separately (`PASS1`, `PASS2`, `PASS3+`), fit per-BRT-day continuous rank logistic models:

```text
logit P(hit +200 before retest) =
    alpha
  + beta_MID * rank(NET_1S)
  + beta_CF  * rank(OPP_TOTAL)
  + beta_SEQ * rank(SEQUENCE_CONTRAST)
```

Primary discovery coefficient:

```text
beta_SEQ
```

Directional discovery hypothesis:

```text
beta_SEQ > 0
```

Meaning: after controlling continuously for net directional MID migration and total counterflow, earlier rather than later counterflow is associated with stronger subsequent continuation.

## Frozen eligibility

A PASS is eligible when:

```text
outcome_complete_before_retest_60s == 1
hit_200_before_retest in {0,1}
finite NET_1S
finite OPP_TOTAL
OPP_TOTAL > 0
finite SEQUENCE_CONTRAST
```

No clipping, thresholding, sign inversion, direction subset rescue, PASS-stage subset rescue, or outcome-driven redefinition is authorized.

## Historical discovery block

Default discovery block:

```text
2026-07-02 through 2026-08-12 BRT
```

This block is already historically exposed through prior Map03/diagnostic work and is therefore explicitly NOT a holdout.

The runner may use Map03 coverage, when present, only as an engineering reproduction guard for tick / episode / PASS counts. This does not upgrade the scientific status.

## Reporting

For PASS1 / PASS2 / PASS3+ report:

- eligible BRT days;
- eligible events;
- equal-day mean `beta_SEQ`;
- whole-day bootstrap CI95, `N=5000`, seed `2026081901`;
- number of days with positive `beta_SEQ`;
- raw pooled AUC of `SEQUENCE_CONTRAST` as descriptive only.

A positive result is reported as `HISTORICAL_DISCOVERY_SUPPORT=YES`, never as validation.

A negative/null result remains a valid discovery result. No rescue is authorized inside Map05.

## Governance

- Map03 remains failed and is not sign-inverted.
- Map04 prospective definition is unchanged.
- Map02 prospective definition is unchanged.
- Shadow01 prospective validation is unchanged.
- Historical Map05 results cannot change those frozen tests.
- Any formal use of sequence timing requires a separately frozen future experiment after discovery is inspected.
- Runtime promotion remains NONE.
