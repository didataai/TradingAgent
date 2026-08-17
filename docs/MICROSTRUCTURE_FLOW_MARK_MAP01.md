# MICROSTRUCTURE FLOW-MARK MAP 01 — hard freeze before first run

## Status

This is a new, separate **historical exploratory microstructure** line. It does not rescue, modify or score Decision Replay, Exp27, Decision Calibration Shadow, Operability or the earlier Microstructure Breakout Map 01.

The purpose is to test whether quote-spread expansion leaves reusable intraday price zones ("FLOW MARKS") that organize subsequent price travel, retests, recrosses and failures.

No runtime promotion is authorized by this map.

## Data and scope

- Symbol: `GOLD` on the user's connected MT5 / ActivTrades feed.
- Primary historical window: `2026-02-01` through `2026-08-12` BRT inclusive.
- Tick fields used: `time_msc`, `bid`, `ask`, `flags` only.
- `last`, `volume`, `volume_real`, BUY/SELL tape flags are not used because this feed does not populate them.
- `point` guard: `0.01`.
- Primary discovery uses the **full BRT day**, not only 09:00–18:00.
- Each BRT day is an independent continuous path. Marks do **not** carry across the BRT-day boundary in Map01; unresolved states become `DAY_END`.
- Time-of-day / 09:00–18:00 membership is retained only as descriptive context, not as an event filter.

This first map does **not** use M5/M15 support/resistance, candle color, OHLC candle direction, swing level, indicator or structural model to create a mark.

## Quote coordinates

For every valid quote:

```text
mid    = (bid + ask) / 2
spread = ask - bid
```

A FLOW MARK is a zone, not a single price:

```text
mark_low  = birth_bid
mark_mid  = birth_mid
mark_high = birth_ask
```

## Causal spread baseline

To avoid fitting a historical spread threshold, Map01 defines a local baseline mechanically.

1. Aggregate ticks into **completed one-second buckets**.
2. For each completed second, compute the median spread in that second.
3. At a tick in second `s`, the baseline is the median of the per-second median spreads from the **30 completed clock seconds immediately before `s`**.
4. All 30 completed seconds must contain at least one valid quote; otherwise no mark may be born at that tick.
5. The current second is excluded from the baseline.

```text
spread_ratio = spread_now / spread_baseline_30s
```

No quantile, optimized multiplier or fixed spread value is selected.

## FLOW MARK birth — frozen definition

An expansion episode is active while:

```text
spread_now > spread_baseline_30s
```

A new FLOW MARK is created only at the **onset** of an expansion episode and only if the spread itself increased on that tick:

```text
expanded_now     = spread_now > baseline_now
expanded_prev    = previous valid tick was in expansion
actual_widening  = spread_now > spread_previous_tick

BIRTH = expanded_now
        AND NOT expanded_prev
        AND actual_widening
```

The episode ends when `spread_now <= baseline_now`. While an episode remains expanded, additional ticks do not create additional marks.

This `baseline crossing + actual widening` rule is a mechanical event definition, not a fitted prediction threshold.

## Direction — no candle color

Direction is defined from quote migration over the immediately preceding second:

```text
delta_mid_1s = mid_now - last mid at-or-before (t - 1 second)

UP      if delta_mid_1s > 0
DOWN    if delta_mid_1s < 0
NEUTRAL if delta_mid_1s = 0 or no causal 1-second reference exists
```

NEUTRAL births are retained descriptively but do not enter the directional lifecycle tests below.

No minimum directional impulse is imposed in Map01.

## Birth signature — continuous features only

At each birth preserve, without fitted cutoffs:

- spread and 30s spread baseline;
- `spread_ratio`;
- spread change over 250ms / 1s / 5s;
- signed BID / ASK / MID impulse over 250ms / 1s / 5s;
- tick rate over 250ms / 1s / 5s;
- tick-rate ratio versus prior 30s;
- tick acceleration = last 1s rate / previous 4s rate;
- directional MID update fraction over 1s;
- fraction of quote updates where BID and ASK both changed over 1s;
- BRT timestamp and time-of-day context.

These features are mapped as continuous distributions/quintiles. Map01 does not select a best bucket for live use.

## Directional lifecycle state machine

### UP mark

Birth zone:

```text
[mark_bid, mark_ask]
```

First directional departure / PASS #1:

```text
bid > mark_ask
```

After a departure, first retest begins when:

```text
bid <= mark_ask
```

After retest:

```text
RECROSS / PASS #2+ : bid > mark_ask
FAILURE            : ask < mark_bid
```

Every later retest/recross increments the pass number (`PASS #3`, `PASS #4`, ...). A failure is terminal for that mark in Map01.

### DOWN mark

First directional departure / PASS #1:

```text
ask < mark_bid
```

After a departure, first retest begins when:

```text
ask >= mark_bid
```

After retest:

```text
RECROSS / PASS #2+ : ask < mark_bid
FAILURE            : bid > mark_ask
```

Failure is terminal.

## PASS-strength question — primary replay map

Every PASS event (`PASS #1`, `PASS #2`, `PASS #3`, ...) receives a causal quote signature at the pass timestamp and future outcomes.

From pass time `t0`, within the next 60 seconds and **before the next retest of the same mark**, measure:

```text
signed return at 1s / 2s / 5s / 10s / 15s / 30s / 60s
MFE_60_points
MAE_60_points
hit +50 points before retest
hit +100 points before retest
hit +200 points before retest
hit +300 points before retest
```

For UP marks, positive movement is upward; for DOWN marks, positive movement is downward.

If the next retest occurs before a target, that target is recorded as not reached before retest.

### Frozen matched diagnostic

The user's specific hypothesis "when price comes back and passes the mark again, movement gains strength" is tested descriptively with marks that have both PASS #1 and PASS #2.

For the **same mark**, compare PASS #2 versus PASS #1 for:

- `hit_50_before_retest`;
- `hit_100_before_retest`;
- `hit_200_before_retest`;
- `hit_300_before_retest`;
- MFE_60.

Primary paired binary contrast: `PASS2 - PASS1` for `hit_200_before_retest`, with whole-BRT-day cluster bootstrap.

Bootstrap:

```text
N = 5000
seed = 2026081705
cluster = BRT birth day
```

This is still historical exploratory evidence; it is not a promotion gate.

Direct PASS #1 vs PASS #2 population averages must also be printed, but the matched same-mark comparison is preferred because PASS #2 exists only after a retest.

## Mark failure -> next destination map

At terminal FAILURE, Map01 asks whether price travels toward another previously created mark or creates a new mark first.

At failure time, identify the nearest **earlier FLOW MARK zone born on the same BRT day** in the direction of travel, regardless of that earlier mark's original UP/DOWN direction.

For a failed UP mark (price now traveling downward):

```text
candidate prior mark must lie fully below:
prior.mark_ask < failed.mark_bid

choose nearest = maximum prior.mark_ask
```

For a failed DOWN mark (price traveling upward):

```text
candidate prior mark must lie fully above:
prior.mark_bid > failed.mark_ask

choose nearest = minimum prior.mark_bid
```

From failure until BRT day end, record the first of:

```text
NEXT_PRIOR_MARK_HIT
FAILED_MARK_RECLAIM
NEW_FLOW_MARK_BIRTH
DAY_END
```

Definitions:

- prior-mark hit = current quote overlaps the nearest prior mark zone;
- failed UP reclaim = `bid > failed.mark_ask`;
- failed DOWN reclaim = `ask < failed.mark_bid`;
- new mark = next FLOW MARK birth after failure; also record whether its direction matches the failure travel direction.

Map01 reports both the raw competing first event and whether the nearest prior mark is eventually hit before failed-mark reclaim.

## Mark-chain map

For each BRT day, preserve the chronological sequence of directional FLOW MARK births:

```text
UP / DOWN / UP / ...
```

Report descriptively:

- same-direction run lengths;
- distance in points between consecutive mark mids;
- time between births;
- whether a new same-direction mark was born before the prior mark failed/reclaimed.

No chain pattern is promoted from Map01.

## Primary Map01 outputs

Generated local data, not source-code artifacts:

```text
data/market_chronos/microstructure/FLOWMARK_map01_marks.csv
data/market_chronos/microstructure/FLOWMARK_map01_passes.csv
data/market_chronos/microstructure/FLOWMARK_map01_failures.csv
data/market_chronos/microstructure/FLOWMARK_map01_feature_quintiles.csv
```

Console must print:

1. tick/day coverage;
2. births UP/DOWN/NEUTRAL;
3. PASS #1 / #2 / #3+ counts;
4. departure/retest/failure counts;
5. continuation rates by pass number;
6. matched PASS2-minus-PASS1 diagnostics;
7. failure destination frequencies;
8. descriptive feature quintiles for `birth -> PASS1<=60s` and `PASS -> hit200 before retest`.

## Governance / anti-rescue

Map01 is a map, not a strategy.

After inspecting Map01, do not claim a live rule by selecting:

- a favorable spread ratio;
- a favorable tick-rate threshold;
- a favorable time of day;
- only UP or DOWN marks;
- only PASS #2 if PASS #1 is bad without freezing a new hypothesis;
- only a favorable target among 50/100/200/300;
- a favorable feature quintile or 2D cell;
- M5/M15 structural context added retrospectively to rescue a weak result.

Any predictive fingerprint selected after Map01 requires a separate pre-frozen `FLOW-MARK MAP 02` contract.

Permanent status during Map01:

```text
FLOW_MARK_MAP01 = FROZEN_BEFORE_FIRST_RUN
HISTORICAL_STATUS = EXPLORATORY
CANDLE_COLOR = NOT_USED
M5_M15_LEVELS = NOT_USED_IN_PRIMARY_EVENT_DEFINITION
THRESHOLD_OPTIMIZATION = NONE
EXP27 = UNTOUCHED / SCORES SEALED
CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED
RUNTIME_PROMOTION = NONE
```
