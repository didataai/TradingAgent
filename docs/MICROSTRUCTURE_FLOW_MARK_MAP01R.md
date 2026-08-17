# MICROSTRUCTURE FLOW-MARK MAP 01R — debounced episode revision

## Status / chronology

This is a separate historical exploratory microstructure line. It does not rescue, modify or score Decision Replay, Exp27, Decision Calibration Shadow, Operability or Microstructure Breakout Map 01.

The first Flow-Mark Map01 smoke on `2026-08-11` was interrupted at the pre-outcome lifecycle stage because the tick-level episode boundary was too dense:

```text
valid ticks     = 563991
raw FLOW births = 84660
```

No PASS1/PASS2 continuation rate, failure destination, MFE/MAE, target hit, feature/outcome bucket or bootstrap result from Flow-Mark Map01 was inspected before the revision.

Map01R therefore changes measurement discretization before outcomes; it is not a post-hoc predictive rescue.

## Data / scope

- Symbol: `GOLD` on connected MT5 / ActivTrades.
- Primary historical window after smoke validation: `2026-02-01` through `2026-08-12` BRT inclusive.
- Tick fields used: `time_msc`, `bid`, `ask`, `flags` only.
- `point = 0.01` exact guard.
- Full BRT-day path; state resets at BRT day boundary.
- No M5/M15 level, support/resistance, candle color, OHLC direction, indicator, structural model or fitted trading threshold creates a mark.
- Exp27 and Decision Calibration Shadow remain untouched / sealed.
- Runtime promotion = NONE.

## Quote coordinates / causal spread baseline

```text
mid    = (bid + ask) / 2
spread = ask - bid
```

Baseline is unchanged:

1. completed one-second buckets;
2. median spread per completed second;
3. baseline at second `s` = median of the 30 completed seconds immediately before `s`;
4. all 30 prior seconds must contain at least one valid quote;
5. current second excluded.

```text
spread_ratio = spread_now / spread_baseline_30s
```

No quantile, multiplier or fixed spread threshold is fitted.

## Qualifying widening tick

```text
baseline_available = finite(baseline_now) and baseline_now > 0
expanded_now       = spread_now > baseline_now
actual_widening    = spread_now > spread_previous_valid_tick

QUALIFY = baseline_available
          AND expanded_now
          AND actual_widening
```

## Debounced FLOW EPISODE — frozen definition

- Episode birth = first `QUALIFY` tick while no episode is active.
- Additional qualifying ticks do not create new marks.
- Qualifying ticks in the same or immediately next clock second remain the same episode.
- A gap of at least two qualifying-second indices means one full completed clock second contained zero qualifying widening ticks, which closes the episode.
- BRT-day boundary always closes the episode.
- No magnitude threshold or minimum spread ratio is introduced.

Equivalent close rule:

```text
last qualifying widening occurs in clock second s
quiet second = s+1
normal close = end of completed quiet second s+1
```

## FLOW EPISODE coordinates

Each episode preserves both geometries, but outcomes may not choose between them retrospectively.

### Birth zone — descriptive only in first lifecycle replay

```text
birth_low  = bid at episode birth
birth_mid  = mid at episode birth
birth_high = ask at episode birth
```

### Peak-spread zone — PRIMARY lifecycle geometry

Among qualifying widening ticks in the episode, choose maximum spread; ties use earliest tick.

```text
peak_low   = bid at peak-spread tick
peak_mid   = mid at peak-spread tick
peak_high  = ask at peak-spread tick
```

Also preserve birth/peak/last-qualifying/close times, qualifying tick count, duration, peak spread, peak spread ratio and causal signatures.

## Direction

Direction is frozen at episode birth:

```text
delta_mid_1s = mid_birth - last mid at-or-before (birth_time - 1 second)

UP      if delta_mid_1s > 0
DOWN    if delta_mid_1s < 0
NEUTRAL otherwise
```

No minimum directional impulse is imposed.

## Density-only smoke — completed before outcomes

The mandatory density-only probe on `2026-08-11 BRT` completed with lifecycle/outcomes disabled by design:

```text
valid_ticks               = 563991
baseline_available_ticks  = 373147
expanded_ticks            = 175746
qualifying_widening_ticks = 114460
old_raw_births            = 84660
debounced_episodes        = 4066
reduction_vs_raw          = 95.20%

episodes_09_18            = 1757
episodes_per_hour_09_18   = 195.22
```

Important reporting correction: the probe label `episodes_per_24h = 169.42` was a naming bug. The calculation `4066 / 24 = 169.42` is **episodes per hour across the full 24h day**, not episodes per 24h. Total episodes for the day are 4066. This is reporting-only; episode membership is unchanged.

Birth direction:

```text
UP      = 1967
DOWN    = 1940
NEUTRAL = 159
```

Episode diagnostics:

```text
qualifying ticks / episode:
P10=2 P25=4 P50=12 P75=31 P90=67 P95=105 P99=231.7 max=800

birth -> last qualifying duration ms:
P10=300 P25=1560 P50=4525.5 P75=10990.5
P90=22168 P95=32600.8 P99=63368.1 max=191947

peak spread ratio:
P10=1.0309 P25=1.0426 P50=1.0625 P75=1.0833
P90=1.1299 P95=1.2054 P99=1.4283 max=4.5294
```

All 4066 episodes closed via `QUIET_SECOND` in this smoke day.

Interpretation allowed at this stage: the debounced representation is accepted as computationally and conceptually usable. No further debounce duration or spread threshold is selected before outcomes.

## First lifecycle replay — hard freeze before outcomes

### Primary mark geometry

```text
PRIMARY_MARK = PEAK_SPREAD_ZONE
ZONE         = [peak_bid, peak_ask]
```

The birth zone is retained as descriptive episode metadata only. It is **not** run as a competing lifecycle geometry inside Map01R.

### Causal activation

The peak-spread tick may occur before episode close, therefore the peak zone must not be used until the episode is complete.

```text
MARK_ACTIVATION_TIME = episode_close_time
```

- `PASS1`, retest, recross and failure searches begin strictly after activation.
- A `DAY_END`-closed episode never activates within that BRT day and cannot enter lifecycle outcomes for that day.
- No price movement between peak time and activation time may count as PASS1 or any future outcome.

This makes the peak geometry causal: the zone is known only after the quiet-second closure confirms which qualifying tick was the episode maximum spread.

## Directional lifecycle — unchanged state semantics, peak geometry

### UP episode

```text
PASS1 after activation : bid > peak_ask
RETEST after PASS      : bid <= peak_ask
PASS2+ after retest    : bid > peak_ask
FAILURE after retest   : ask < peak_bid
```

### DOWN episode

```text
PASS1 after activation : ask < peak_bid
RETEST after PASS      : ask >= peak_bid
PASS2+ after retest    : ask < peak_bid
FAILURE after retest   : bid > peak_ask
```

Failure is terminal for that mark within the BRT day.

## PASS-strength outcomes

Every PASS receives a causal quote signature at pass time. From pass `t0`, within the next 60 seconds and before the next retest of the same peak zone, measure:

```text
signed return at 1/2/5/10/15/30/60s
MFE_60_points
MAE_60_points
hit +50 before retest
hit +100 before retest
hit +200 before retest
hit +300 before retest
```

UP positive = upward; DOWN positive = downward.

### Matched same-mark diagnostic

For marks with both PASS1 and PASS2, compare PASS2 vs PASS1 within the same mark.

Primary paired binary contrast remains:

```text
PASS2 - PASS1 for hit_200_before_retest
bootstrap cluster = whole BRT birth day
N = 5000
seed = 2026081705
```

Direct PASS1/PASS2 population averages are descriptive; matched same-mark is preferred.

## Failure -> next destination

At terminal failure, prior candidate marks must be **already activated** before the failure; merely having been born is not sufficient because peak geometry is not causal until episode close.

For failed UP / downward travel:

```text
candidate prior peak zone fully below:
prior.peak_ask < failed.peak_bid
choose nearest = maximum prior.peak_ask
```

For failed DOWN / upward travel:

```text
candidate prior peak zone fully above:
prior.peak_bid > failed.peak_ask
choose nearest = minimum prior.peak_bid
```

From failure until BRT day end record competing path events. A later expansion episode birth may be recorded as `NEW_FLOW_EPISODE_BIRTH` because the onset itself is causally observable; its eventual peak geometry is not used until its own activation.

Also record whether the nearest already-activated prior peak zone is eventually hit before failed-mark reclaim.

## First observed lifecycle smoke — 2026-08-11 BRT

This is the first outcome-bearing Flow-Mark 01R run. The geometry, debounce, activation time and lifecycle rules above were frozen before these results were observed. This one-day smoke is descriptive / mechanical validation only; its bootstrap CI is undefined because there is only one BRT cluster day.

Universe:

```text
valid_ticks            = 563991
episodes               = 4066
directional episodes   = 3907
activated              = 3906 (99.97%)
departed               = 3853 (98.62%)
retested               = 3837 (98.21%)
failed                 = 3750 (95.98%)
PASS1 <=60s activation = 66.65%
passes                  = 38287
```

Pass counts:

```text
PASS1  = 3853
PASS2  = 3365
PASS3  = 2986
PASS4+ = 28083
```

Continuation before next retest:

```text
PASS1 n=3853  +50=20.79% +100=12.77% +200=4.83% +300=2.02% meanMFE60=38.92
PASS2 n=3365  +50=15.81% +100= 8.71% +200=3.57% +300=1.63% meanMFE60=30.43
PASS3+ n=31067 +50=13.92% +100= 7.64% +200=2.98% +300=1.12% meanMFE60=26.14
```

Matched same-mark PASS2 minus PASS1 on this single day:

```text
+50  = -4.31 pp
+100 = -3.63 pp
+200 = -1.13 pp
+300 = -0.27 pp
MFE60 = -7.25 points
```

Allowed one-day interpretation: the specific hypothesis `PASS2 > PASS1` was not supported on this smoke day; the observed direction was the opposite. This does not become a cross-day conclusion until the unchanged historical replay is run across multiple BRT days.

Failure destination:

```text
failures = 3750
has activated prior-mark candidate = 3713
prior mark eventually hit before failed-mark reclaim = 98.68%

first competing event:
NEXT_PRIOR_MARK_HIT                           3630
NEW_FLOW_EPISODE_BIRTH                         66
FAILED_MARK_RECLAIM                            34
NEW_FLOW_EPISODE_BIRTH+NEXT_PRIOR_MARK_HIT     19
FAILED_MARK_RECLAIM+NEW_FLOW_EPISODE_BIRTH      1
```

This high prior-mark hit rate is not yet interpreted as predictive evidence because mark density / candidate distance may make the destination mechanically easy to hit. Candidate-distance distribution must be audited before claiming a useful navigation law; the frozen destination result itself is preserved.

One-day descriptive feature observations, not thresholds:

```text
PASS -> hit200 by pass_spread_ratio quintile:
Q1=2.16% -> Q5=4.50%

PASS -> hit200 by signed_mid_impulse_1s quintile:
Q1=2.71%
Q2=2.24%
Q3=2.88%
Q4=2.94%
Q5=5.34%
```

Tick-rate / tick-acceleration top quintiles did not show corresponding improvement on this day. No threshold or best bucket is promoted from these observations.

Status after first lifecycle smoke:

```text
FLOW_MARK_MAP01R_FIRST_LIFECYCLE_SMOKE = COMPLETE
SMOKE_DAY = 2026-08-11_BRT
PASS2_GT_PASS1_ON_SMOKE_DAY = NO
FAILURE_PRIOR_MARK_HIT_RATE_SMOKE = 98.68_PERCENT
FULL_HISTORICAL_CROSS_DAY_REPLAY = NOT_YET_RUN
RUNNER_LOGIC_AFTER_SMOKE = UNCHANGED
EXP27 = UNTOUCHED / SCORES SEALED
CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED
RUNTIME_PROMOTION = NONE
```

## Governance / anti-rescue

Map01R is a map, not a live strategy.

After outcomes, do not declare a live rule by selecting a favorable:

- spread ratio or peak spread threshold;
- episode duration;
- qualifying-tick count;
- time of day;
- direction;
- PASS number;
- target among 50/100/200/300;
- feature quintile / 2D cell;
- BIRTH geometry as rescue if PEAK geometry is weak;
- M5/M15 context added retrospectively.

Any predictive fingerprint selected after Map01R requires a separately frozen Map02.

Permanent status:

```text
FLOW_MARK_MAP01_FIRST_SMOKE = INTERRUPTED_PRE_OUTCOME_DUE_EVENT_DENSITY
RAW_BIRTHS_2026_08_11 = 84660
FLOW_MARK_MAP01_OUTCOMES_INSPECTED_BEFORE_01R = NO
FLOW_MARK_MAP01R_DENSITY_SMOKE = ACCEPTED_PRE_OUTCOME
DEBOUNCED_EPISODES_2026_08_11 = 4066
PRIMARY_MARK_GEOMETRY = PEAK_SPREAD_ZONE
MARK_ACTIVATION = EPISODE_CLOSE_TIME
BIRTH_GEOMETRY_OUTCOME_REPLAY = DISABLED
FIRST_01R_LIFECYCLE_SMOKE = COMPLETE_2026_08_11
THRESHOLD_OPTIMIZATION = NONE
CANDLE_COLOR = NOT_USED
M5_M15_LEVELS = NOT_USED
EXP27 = UNTOUCHED / SCORES SEALED
CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED
RUNTIME_PROMOTION = NONE
```