# GOLD D1 Point-in-Time Intraday Filter

## Goal

Add a daily-position context to the existing Market Intelligence flow without using the final D1 high/low of the day, and maintain a single research record of the D1, z-score, post-09 stress-cycle and intraday-clock findings.

The runtime reconstructs the current D1 candle from `GOLD_M5.parquet` using the **MT5 broker day**. BRT is used for the operational window and for intraday phase research.

## Runtime flow

```text
GOLD_M5.parquet
    ↓
Broker-day open / high-so-far / low-so-far
    ↓
d1_position = (price - low_so_far) / (high_so_far - low_so_far)
    ↓
D1 zone + daily direction
    ↓
market_intelligence.py enrich
    ↓
formal_mtf_decision.d1_position_filter
```

The existing hierarchy remains intact:

```text
H4 = regime
H1 = tactical bias
M15 = setup
M5 = confirmed trigger
M1 = execution/intrabar resolution
```

The D1 filter remains an additional runtime guard. New z-score, stress-cycle and Market Clock findings are still research/shadow context and do not replace the confirmed M5 trigger.

---

# Research checkpoint — 2026-08-11

## Methodology

The consolidated study uses:

- MT5 broker-day D1 boundaries;
- point-in-time `Open / HighSoFar / LowSoFar` only;
- no final-day D1 lookahead;
- completed H1 and M15 bars only at each M5 decision timestamp;
- chronological `60/20/20` train/validation/test;
- M5 research history of about 100k candles;
- independent broker-day checks;
- 30/60/120 minute horizons, with 120 minutes currently the principal research horizon;
- expectancy and profit factor before win rate;
- MFE/MAE and sample size as supporting metrics;
- day-cluster bootstrap for Market Clock phase validation.

Important statistical note: the exploratory TEST segment has now been inspected repeatedly while developing the z-score, episode and clock hypotheses. It is no longer a pristine untouched holdout for final promotion. Any future hard promotion must use frozen forward shadow data or nested/walk-forward confirmation.

---

# 1. D1 directional structure

## 1.1 Bullish continuation: D1 0.70-0.90

This is the strongest directional D1 continuation finding so far.

```text
D1 Position 0.70-0.90
+ daily candle BULLISH
+ H1/M15/M5 aligned BUY
```

OOS 120m:

| n | independent days | WR | mean | PF |
|---:|---:|---:|---:|---:|
| 358 | 44 | 56.70% | +4.14 | 1.66 |

Status: **STRONG_RESEARCH_EDGE**.

The current soft BUY preference remains in the runtime rules.

## 1.2 Bearish continuation: D1 0.10-0.30

The lower side is **not** a mirror image of the bullish side.

OOS 120m:

| n | independent days | WR | mean | PF |
|---:|---:|---:|---:|---:|
| 208 | 41 | 49.52% | -0.96 | 0.87 |

Status: **SELL_CONTINUATION_NOT_CONFIRMED**.

The former SELL bonus was removed from runtime scoring. The zone is retained for research compatibility, but it no longer has a directional preference.

---

# 2. D1 extremes and anti-edge

## 2.1 Extreme high: avoid BUY chase

At `D1 Position >= 0.90`, BUY continuation deteriorated strongly.

```text
D1 EXTREME_HIGH
+ aligned BUY chase
```

OOS 120m:

| n | independent days | WR | mean | PF |
|---:|---:|---:|---:|---:|
| 355 | 35 | 41.69% | -3.95 | 0.64 |

Status: **STRONG_ANTI_EDGE_BUY_CHASE_RULE_CANDIDATE**.

This is the important high-side rule discovery:

```text
D1 >= 0.90
→ do not chase BUY simply because price remains at the high
```

The exact inverse SELL on those timestamps looked strong in the recent TEST, but historical train/validation did not confirm a stable SELL edge. Therefore the research conclusion is **avoid BUY chase**, not automatically SELL.

## 2.2 Extreme low: avoid SELL chase

At `D1 Position <= 0.10`, SELL continuation is also an anti-edge.

OOS 120m:

| n | independent days | WR | mean | PF |
|---:|---:|---:|---:|---:|
| 256 | 32 | 41.41% | -2.24 | 0.73 |

Status: **ANTI_EDGE_SELL_CHASE_CONFIRMED**.

This supports a separate lower-extreme mean-reversion family rather than continued SELL chasing.

---

# 3. Lower-extreme z-score mean reversion

The strongest mean-reversion family found so far is:

```text
D1 EXTREME_LOW
+ H1 DOWN
+ M15 DOWN
+ M5 rolling z-score <= -2.0
→ BUY mean-reversion research candidate
```

Z-score definition:

```text
window = 20 M5 candles
z = (close - rolling_mean) / rolling_std_population
```

## 3.1 Train / validation / test at Z <= -2.0

120m:

| Period | n | WR | mean | PF |
|---|---:|---:|---:|---:|
| TRAIN | 195 | 65.64% | +4.05 | 2.02 |
| VALIDATION | 69 | 62.32% | +9.31 | 2.21 |
| TEST | 100 | 72.00% | +7.07 | 2.87 |

TEST contains 29 independent broker days.

Status: **STRONG_SHADOW_CANDIDATE**.

## 3.2 Threshold robustness

PF at 120m:

| Z threshold | TRAIN | VALIDATION | TEST |
|---:|---:|---:|---:|
| 1.5 | 1.82 | 1.17 | 1.78 |
| 2.0 | 2.02 | 2.21 | 2.87 |
| 2.5 | 2.93 | 1.49 | 7.25 |

The lower-side effect survives all three tested thresholds. `Z=-2.0` is retained as the current research balance because it combines quality with materially more sample than `-2.5`.

The pattern is therefore better interpreted as an **overextension family**, not a threshold trick at exactly `-2.0`.

## 3.3 Horizon profile

Across the broader lower-extreme sample, the response was much weaker at 30/60 minutes and materially stronger around 120 minutes.

Interpretation:

```text
extreme stress
    ↓
possible additional overshoot
    ↓
mean reversion develops over a longer horizon
    ↓
~120m is the principal research horizon
```

This is not currently treated as an immediate scalp-reversal rule.

## 3.4 Rejection variants

Adding candle rejection produced very high headline PF in some subsets, but sample collapsed sharply. These variants remain **experimental only** and are not promoted.

---

# 4. Post-09 stress-cycle sequence

Repeated M5 extreme candles initially looked stronger as persistence increased, but consecutive candles can belong to the same episode. The research therefore introduced z-score episode hysteresis:

```text
episode enters: z <= -2.0
episode only resets: z > -1.5
```

The important finding is explicitly session-relative:

```text
09:00 BRT reset
    ↓
post-09 z episode #1
    ↓
recovery above -1.5
    ↓
post-09 z episode #2
    ↓
at episode #2:
D1 EXTREME_LOW + H1 DOWN + M15 DOWN
```

120m:

| Period | n | independent days | WR | mean | PF |
|---|---:|---:|---:|---:|---:|
| TRAIN | 14 | 14 | 71.43% | +4.76 | 2.14 |
| VALIDATION | 4 | 4 | 75.00% | +2.85 | 1.48 |
| TEST | 13 | 13 | 69.23% | +6.17 | 3.32 |

Status: **PROMISING_SMALL_SAMPLE_SHADOW**.

## 4.1 Important boundary result

The same episode definition was tested with different reset clocks:

```text
09:00 reset      = 31 qualifying events
08:00 reset      = 4 qualifying events
broker-day reset = 0 qualifying events
```

Overlap between 09:00 and 08:00 definitions was only about 3%.

Conclusion: this is **not** the second extreme episode of the whole day. It is specifically a **post-09 session stress-cycle feature**.

This suggests `Post09StressCycle` as a future Market Chronos feature rather than a generic `ExtremePersistenceCount`.

## 4.2 Episode ordinal information

The second post-09 episode remained better than the first in the large TRAIN and TEST blocks even when D1 depth and Z intensity were similar or stronger on EP1. This indicates episode order may contain sequence information rather than merely proxying a deeper D1 or more extreme z-score.

Sample remains too small for runtime promotion.

---

# 5. Data-driven Market Clock

Instead of imposing session boundaries manually, the research scanned the M5 clock and let TRAIN discover intraday structural zones. Validation and Test were used only to confirm/reject discovered phases.

## 5.1 Robust high-volatility phase

The strongest Market Clock discovery is:

```text
09:05-12:30 BRT
HIGH VOLATILITY PHASE
```

Day-cluster bootstrap, one observation per broker day, 10,000 repetitions:

| Period | days | mean relative vol | median | CI95 | P(vol > 1) |
|---|---:|---:|---:|---|---:|
| TRAIN | 212 | 1.587 | 1.530 | [1.542, 1.634] | 100% |
| VALIDATION | 77 | 1.513 | 1.426 | [1.425, 1.606] | 100% |
| TEST | 76 | 1.546 | 1.508 | [1.481, 1.613] | 100% |

Status: **ROBUST_DESCRIPTIVE_PHASE**.

This is currently the strongest clock finding because the confidence interval stays entirely above baseline in all three periods.

Core volatility peaks discovered inside the larger phase include approximately:

```text
09:30
10:05
10:35-10:45   strongest core
11:05-11:10
11:20-11:40
```

This is descriptive market state, **not a directional BUY/SELL rule**.

## 5.2 Night continuation candidates

The night clock produced several continuation-looking slots, but bootstrap did not establish a stable directional phase.

### NIGHT_20

```text
20:10-20:20
TRAIN P(mean>0) 91.10%
VALIDATION       58.81%
TEST             89.55%
```

Mixed confidence. Not promoted.

### NIGHT_22

TRAIN is clearly negative while later periods are mixed. Rejected as a stable continuation rule.

### NIGHT_2335

```text
23:35-00:10 region
```

Validation and Test are promising, but TRAIN CI crosses zero. Keep exploratory.

## 5.3 Pre-morning reversal candidate

The discovered region around `06:20-08:00` looked reversal-biased in TRAIN/VALIDATION but did not survive TEST bootstrap:

```text
TRAIN       P(mean<0) 99.82%
VALIDATION              95.88%
TEST                    49.63%
```

Status: **UNSTABLE_OOS**.

## 5.4 Post-volatility reversal candidate

The region around `12:55-13:45` had a negative median in all periods, but mean bootstrap confidence was weak:

```text
TRAIN       P(mean<0) 65.70%
VALIDATION              62.68%
TEST                    52.40%
```

Status: **DESCRIPTIVE_ONLY_NOT_BOOTSTRAP_CONFIRMED**.

It should not become a directional rule yet.

---

# 6. Opening-flow / echo hypotheses

The working hypothesis that `20:00-01:00` direction is repeated by `08:00-09:00` was tested.

Direction agreement:

```text
TRAIN       54.72%
VALIDATION  61.84%
TEST        48.68%
```

The binary direction match is therefore not structurally confirmed.

However, the signed magnitude remained positive across the three periods, and the later `08-09` phase showed useful interactions with directional efficiency and volatility. These are retained as state-feature hypotheses, not rules.

The data also suggested that a strong/efficient `08-09` move can behave differently from a noisy high-range move. Therefore future phase modeling should separate:

```text
volatility
+
directional efficiency
+
flow direction
```

rather than treating high range alone as momentum.

Weekday effects (Tuesday/Wednesday/Thursday) were not stable enough to become standalone rules.

---

# 7. Current rule/status matrix

| Finding | Current status | Runtime effect now? |
|---|---|---|
| D1 0.70-0.90 bullish aligned BUY | Strong research edge | Soft BUY score retained |
| D1 0.10-0.30 bearish aligned SELL | Not confirmed | SELL bonus removed |
| D1 >= 0.90 BUY chase | Strong anti-edge | Avoid-chase BUY warning/penalty retained |
| D1 <= 0.10 SELL chase | Strong anti-edge | Avoid-chase SELL warning/penalty retained |
| D1 extreme-low + Z<=-2 BUY | Strong shadow candidate | Research only |
| Post-09 EP2 + extreme-low BUY | Promising, small sample | Research only |
| 09:05-12:30 high-vol phase | Robust descriptive phase | Research context only |
| Night directional phases | Mixed | No rule |
| 06:20-08:00 reversal | OOS unstable | No rule |
| 12:55-13:45 reversal | Bootstrap not confirmed | No rule |
| Tue/Wed/Thu standalone effect | Unstable | No rule |

---

# 8. What we will join later

The next architecture should associate the statistically discovered features rather than stack arbitrary filters.

Candidate state vector:

```text
D1Position
DailyDirection
H1Direction
M15Direction
M5ZScore20
Post09StressCycle
IntradayVolatilityPhase
MinutesFromPhaseChange
OpeningFlowState
DirectionalEfficiency
```

Then, only after these statistical phases are frozen, map them to real-world market-session events:

```text
market open
market close
session overlap
maintenance/reopen
fixing windows
DST-aware session shifts
```

The economic/session labels should explain a phase **after** the phase is discovered statistically, not define it beforehand.

---

# Runtime policy

The runtime remains:

```text
WARNING_ONLY_RESEARCH
```

No new hard filter is promoted from this checkpoint.

A future promotion requires:

- a frozen hypothesis;
- untouched forward/shadow or nested walk-forward data;
- independent-day validation;
- costs/slippage review;
- no material sample collapse;
- stable direction across relevant temporal segments.

## Rules file

```text
config/market_intelligence/GOLD_d1_intraday_rules.json
```

The research-only z-score, post-09 episode and Market Clock findings are also recorded there so the evidence checkpoint remains machine-readable without activating them in runtime.

## Research script

```powershell
python .\tools\study_d1_mtf_filter_v2.py `
  --source research `
  --symbol GOLD `
  --rules .\config\market_intelligence\GOLD_d1_intraday_rules.json `
  --output .\data\research\GOLD_d1_mtf_filter_report_v2.json
```

`tools/study_d1_mtf_filter_v2.py` remains the main evolving D1/z-score research script. The next code evolution should integrate the frozen post-09 stress-cycle and Market Clock phase analyses into that same file rather than creating additional versioned study scripts.
