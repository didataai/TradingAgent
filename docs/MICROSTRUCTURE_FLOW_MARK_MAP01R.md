# MICROSTRUCTURE FLOW-MARK MAP 01R — debounced episode revision hard-freeze

## Why this revision exists

The first 2026-08-11 smoke run of Map01 reached only the pre-outcome lifecycle stage and exposed a measurement-density problem before any PASS/FAIL/target result was observed:

```text
valid ticks = 563991
raw FLOW MARK births = 84660
```

The run was interrupted at `LIFECYCLE marks=84660`. No PASS1/PASS2 continuation rate, failure-destination result, feature bucket result, MFE/MAE result, target hit rate or bootstrap result from Flow-Mark Map01 was inspected.

Therefore Map01R is a **pre-outcome measurement revision**, not a post-hoc rescue of a failed predictive result.

## Scientific scope preserved

Map01R remains a separate historical exploratory microstructure line.

- Symbol: `GOLD` on the connected MT5 / ActivTrades feed.
- Primary historical window after density validation: `2026-02-01` through `2026-08-12` BRT inclusive.
- Tick fields: `time_msc`, `bid`, `ask`, `flags` only.
- `point = 0.01` exact guard.
- Full BRT-day path; state resets at BRT day boundary.
- No M5/M15 level, support/resistance, candle color, OHLC direction, indicator, structural model or fitted trading threshold creates a mark.
- Exp27 and Decision Calibration Shadow remain untouched and sealed.
- Runtime promotion remains NONE.

## Quote coordinates and causal baseline

```text
mid    = (bid + ask) / 2
spread = ask - bid
```

The causal spread baseline is unchanged:

1. completed one-second buckets;
2. median spread per completed second;
3. baseline at second `s` = median of the 30 completed seconds immediately before `s`;
4. all 30 seconds must contain a valid quote;
5. current second excluded.

```text
spread_ratio = spread_now / spread_baseline_30s
```

No quantile or spread multiplier is fitted.

## Qualifying widening tick

A tick is a qualifying widening tick when:

```text
baseline_available = finite(baseline_now) and baseline_now > 0
expanded_now       = spread_now > baseline_now
actual_widening    = spread_now > spread_previous_valid_tick

QUALIFY = baseline_available
          AND expanded_now
          AND actual_widening
```

This is the same mechanical widening concept used by the original Map01 birth rule. The revision changes only how adjacent qualifying ticks are grouped into one episode.

## Debounced expansion episode — frozen Map01R definition

Map01R groups nearby qualifying widening ticks into a single FLOW EPISODE.

- Episode birth = first `QUALIFY` tick while no episode is active.
- Once active, additional qualifying widening ticks do **not** create new marks.
- An episode remains active until a **full completed clock second contains zero qualifying widening ticks**.
- The first later qualifying widening tick after that completed quiet second starts a new episode.
- A BRT-day boundary always terminates the episode.

No magnitude threshold and no minimum spread ratio is introduced.

## FLOW MARK coordinates per episode

Each episode preserves two zones without choosing a winner:

### Birth zone

```text
birth_low  = bid at episode birth
birth_mid  = mid at episode birth
birth_high = ask at episode birth
```

### Peak-spread zone

Within the episode, among qualifying widening ticks, choose the tick with maximum spread; ties use the earliest tick.

```text
peak_low   = bid at peak-spread tick
peak_mid   = mid at peak-spread tick
peak_high  = ask at peak-spread tick
```

Also preserve:

- birth time;
- peak time;
- last qualifying-widening time;
- episode close time / close reason;
- duration from birth to last qualifying widening;
- count of qualifying widening ticks;
- peak spread and peak spread ratio;
- birth and peak quote signatures.

No lifecycle result may choose retrospectively between BIRTH and PEAK geometry inside Map01R. Density validation reports both only as descriptive episode data.

## Direction

Direction remains defined at episode birth from causal one-second MID migration:

```text
delta_mid_1s = mid_birth - last mid at-or-before (birth_time - 1 second)

UP      if delta_mid_1s > 0
DOWN    if delta_mid_1s < 0
NEUTRAL otherwise
```

No minimum directional impulse is imposed.

## Mandatory density-only smoke gate before lifecycle

Before any lifecycle or future outcome is computed, run only:

```text
2026-08-11 BRT
```

Density-only mode may print only measurement/coverage diagnostics:

- valid ticks;
- qualifying widening ticks;
- debounced episodes;
- episodes/hour for full day and 09:00–18:00;
- UP/DOWN/NEUTRAL births;
- qualifying ticks per episode distribution;
- birth-to-last-qualifying duration distribution;
- peak spread / spread-ratio distribution;
- quiet-second close count and day-end close count.

Density-only mode MUST NOT construct or print:

- PASS1/PASS2/PASS3;
- departure/retest/failure outcomes;
- +50/+100/+200/+300 target outcomes;
- MFE/MAE;
- failure destinations;
- feature/outcome quintiles;
- bootstrap results.

The density smoke exists only to verify that the event representation is computationally and conceptually usable before outcome inspection.

If the debounced representation is still obviously tick-flicker dense, revise measurement again **before outcomes**. Do not use future outcomes to choose the debounce rule.

## Lifecycle after density acceptance

Only after density representation is accepted, the original directional lifecycle questions may resume in a separately executed full mode:

```text
BIRTH/PEAK FLOW MARK
-> PASS1
-> RETEST
-> PASS2+
-> FAILURE
-> nearest earlier same-day mark / reclaim / new mark
```

The exact geometry to use for the first lifecycle replay must be frozen before that replay; Map01R density smoke does not choose birth-vs-peak from outcomes.

## Permanent status

```text
FLOW_MARK_MAP01_FIRST_SMOKE = INTERRUPTED_PRE_OUTCOME_DUE_EVENT_DENSITY
RAW_BIRTHS_2026_08_11 = 84660
FLOW_MARK_MAP01_OUTCOMES_INSPECTED = NO
FLOW_MARK_MAP01R = FROZEN_BEFORE_DENSITY_SMOKE
PRIMARY_NEXT_RUN = 2026_08_11_DENSITY_ONLY
THRESHOLD_OPTIMIZATION = NONE
CANDLE_COLOR = NOT_USED
M5_M15_LEVELS = NOT_USED
EXP27 = UNTOUCHED / SCORES SEALED
CALIBRATION_SHADOW = UNTOUCHED / SCORES SEALED
RUNTIME_PROMOTION = NONE
```