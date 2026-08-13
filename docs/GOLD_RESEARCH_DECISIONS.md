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
