# GOLD D1 Point-in-Time Intraday Filter

## Goal

Add a daily-position context to the existing Market Intelligence flow without using the final D1 high/low of the day.

The runtime reconstructs the current D1 candle from `GOLD_M5.parquet` using the **MT5 broker day**. BRT is used only for the operational window.

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

The D1 filter is an additional runtime guard and does not replace the M5 trigger.

## Current zones

- `0.00–0.10`: `EXTREME_LOW` → avoid chasing SELL.
- `0.10–0.30` + bearish daily candle: `BEARISH_CONTINUATION` → soft preference for SELL.
- `0.30–0.70`: `NEUTRAL` → D1 does not choose direction.
- `0.70–0.90` + bullish daily candle: `BULLISH_CONTINUATION` → soft preference for BUY.
- `0.90–1.00`: `EXTREME_HIGH` → avoid chasing BUY.

These thresholds remain `WARNING_ONLY` until the broker-day OOS study confirms them.

## Rules file

```text
config/market_intelligence/GOLD_d1_intraday_rules.json
```

Because the rules live outside `data/intelligence/GOLD.json`, rebuilding the historical profile does not overwrite them.

## Build the historical profile

```powershell
py .\market_intelligence.py build `
  --symbol GOLD `
  --input-dir .\data `
  --output .\data\intelligence\GOLD.json
```

## Intraday runtime

No new pipeline command is required. The existing `market_intelligence.py enrich` automatically looks for:

```text
config/market_intelligence/GOLD_d1_intraday_rules.json
data/GOLD_M5.parquet
```

If the rules or M5 file are unavailable, Market Intelligence falls back to its existing behavior and reports the D1 context as unavailable.

## Research

```powershell
py .\tools\study_d1_mtf_filter.py `
  --input-dir .\data `
  --symbol GOLD `
  --rules .\config\market_intelligence\GOLD_d1_intraday_rules.json `
  --output .\data\research\GOLD_d1_mtf_filter_report.json
```

The study uses:

- broker-day D1 boundaries;
- only completed H1 and M15 bars at each M5 decision timestamp;
- MTF baseline `H1 == M15 == M5`;
- fixed D1 thresholds before the test set;
- chronological `60/20/20` train/validation/test;
- 30, 60 and 120 minute horizons;
- win rate, directional expectancy, profit factor, MFE/MAE and sample size.

`HARD_FILTER` should only be considered if the OOS test improves expectancy and profit factor without unacceptable sample collapse.
