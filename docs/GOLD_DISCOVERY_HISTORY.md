# GOLD Discovery History — TradingAgent

> Documento canônico e vivo da pesquisa GOLD. Objetivo: preservar **o que foi testado, por que foi testado, como foi testado, o que sobreviveu, o que falhou, o que não deve ser repetido e qual pergunta ficou aberta**.
>
> Esta versão consolida o histórico até `2026-08-13 / Exp37`. As versões anteriores, mais verbosas por rodada, permanecem preservadas no histórico Git. O documento atual prioriza uma visão única, coerente e anti-repeat.

---

# 0. Regras permanentes de manutenção

1. Hipóteses refutadas continuam registradas; não são apagadas por terem falhado.
2. Thresholds, subgrupos ou variantes vistos em TEST não podem ser reutilizados como se fossem hipóteses novas confirmatórias.
3. O TEST histórico atual foi repetidamente inspecionado e deve ser tratado como `EXPLORATORY_OOS`, não como holdout pristine.
4. Promoção futura exige fresh forward, nested/walk-forward ou novo período temporal, além de custos/spread/slippage quando o objetivo mudar de state modeling para trading expectancy.
5. Runtime permanece separado de research. Nenhum achado Track D/Track B recente foi promovido a BUY/SELL.
6. O objetivo é construir um **Market State / DNA Model**, não empilhar filtros até algum resultado parecer bom.
7. Causalidade temporal é obrigatória: uma feature só pode usar informação disponível em `state_time`.
8. Dependência deve ser tratada sem alterar o estimand científico. Para Track D, o estimand primário atual é `STATE_WEIGHTED`; a incerteza deve resamplear BRT days inteiros preservando peso por estado.
9. Para targets diários Track B, a unidade científica é o broker-day e a dependência é tratada por blocos de ISO-week.
10. O forward shadow `Exp27` é uma ilha congelada: nenhuma feature descoberta depois do freeze pode ser adicionada retroativamente.
11. Runtime promotion atual: `NONE` para Track D/Track B recente.
12. Sempre registrar: `QUESTION / WHY / FROZEN DEFINITION / DATA-SPLIT / RESULTS / INTERPRETATION / STATUS / WHAT NOT TO REPEAT / NEXT QUESTION`.

---

# 1. Base de dados / causalidade / estado atual

Símbolo: `GOLD`.

Research data mais recente antes do shadow:

```text
M5  ~99,999 candles
M15 ~50,000
H1  ~20,000
H4  ~10,000
D1  ~3,416
W1  ~679
MN1 ~156
```

Hard historical cutoff para as pesquisas posteriores ao freeze:

```text
2026-08-13 00:00:00 BRT
```

Último M5 carregado nos Exp28-37:

```text
2026-08-12 14:05:00 BRT
```

Infraestrutura causal relevante:

```text
D1 point-in-time por broker-day
H4/H1/M15 disponíveis somente após candle pai fechar
swings 2-left / 2-right disponíveis somente após confirmação causal
state_time e next_time auditados contra shadow cutoff
```

---

# 2. Achados anteriores de maior confiança

## 2.1 D1 bullish continuation context

```text
D1Position 0.70-0.90
+ daily_direction BULLISH
+ H1/M15/M5 BUY aligned
```

TEST 120m histórico:

```text
n=358
WR=56.70%
Mean=+4.1437
PF=1.6578
```

Status: `CONFIRMED_RESEARCH / STRONG_DIRECTIONAL_CONTEXT`.

## 2.2 D1 extreme anti-edge

```text
D1 >= .90 -> AVOID BUY CHASE
D1 <= .10 -> AVOID SELL CHASE
```

Histórico TEST 120m:

```text
EXTREME_HIGH BUY: WR 41.69%, Mean -3.9499, PF .6393
EXTREME_LOW SELL: WR 41.41%, Mean -2.2447, PF .7268
```

Evitar chase não implica abrir o lado contrário automaticamente.

## 2.3 Lower-extreme Z20 mean-reversion family

```text
D1 EXTREME_LOW
+ H1 DOWN
+ M15 DOWN
+ M5 Z20 <= -2
-> BUY mean-reversion research family
```

120m histórico:

```text
TRAIN      n=195 WR=65.64% Mean=+4.05 PF=2.02
VALIDATION n=69  WR=62.32% Mean=+9.31 PF=2.21
TEST       n=100 WR=72.00% Mean=+7.07 PF=2.87
```

Status: `STRONG_SHADOW_CANDIDATE`.

Não continuar otimizando Z no mesmo TEST.

## 2.4 Post09StressCycle

A antiga interpretação de “segundo episódio do dia” foi superada. O objeto relevante é sessão-relativo:

```text
ENTER z<=-2
RESET z>-1.5
cycle counted after 09:00 BRT
```

`Cycle #2` permaneceu um candidato pequeno/promissor; sample insuficiente para promoção.

---

# 3. Track A — Market Clock / phase DNA

## 3.1 HIGH_VOL_MAIN

Fase estrutural robusta:

```text
HIGH_VOL_MAIN = [09:05,12:30) BRT
último M5 incluído = 12:25
```

Whole-day bootstrap:

```text
TRAIN days=212 relvol mean=1.587 CI[1.542,1.634]
VAL   days=77  relvol mean=1.513 CI[1.425,1.606]
TEST  days=76  relvol mean=1.546 CI[1.481,1.613]
P(relvol>1)=100% nos três splits
```

Status: `ROBUST_DESCRIPTIVE_PHASE`.

## 3.2 Point clock directional slots — FWER correction

Varredura original: 288 slots M5. Após whole-day cluster wild bootstrap / max-|t|:

```text
theoretical slots = 288
eligible = 264
TRAIN days = 257
FWER 5% critical |t| = 3.738
FWER 1% critical |t| = 4.156
best TRAIN slot 06:50: t=-3.552, p_FWER=.0993
```

Nenhum slot sobreviveu 5%.

Status:

```text
POINT_CLOCK_DIRECTIONAL_EDGE = REJECTED_AFTER_FWER
20:50 continuation = REJECTED_AS_STRUCTURAL_CLOCK_EDGE
13:30 reversal = REJECTED_AS_STRUCTURAL_CLOCK_EDGE
HIGH_VOL_MAIN = UNAFFECTED
```

## 3.3 EXTREME_FINISH

Frozen threshold:

```text
terminal_extreme >= .850
```

Dedicated bootstrap mostrou uma **propensão distribucional à reversão/persistência**, não expectancy direcional robusta.

P(EXTREME_FINISH more reversal than complement):

```text
TRAIN 85.03%
VAL   85.34%
TEST  84.67%
```

REV120:

```text
54.9% -> 59.1% -> 66.7%
```

Mas mean CIs não sustentam regra SELL/BUY.

Status: `PROMISING_DISTRIBUTIONAL_EXHAUSTION_STATE`.

## 3.4 Exhaustion anatomy

Resultados acumulados:

```text
continuous TerminalExtreme model -> rejected
continuous D1 exhaustion -> rejected
Terminal x D1 linear interaction -> rejected
EVER_NEGATIVE -> rejected as useful discriminator
120m -> stable descriptive anchor
60-90m -> candidate transition block only
```

`EXTREME_FINISH` parece carregar mais informação sobre **tempo/profundidade no lado reversivo** do que simplesmente sobre “tocar qualquer reversão”.

## 3.5 Week-cycle interaction

Hipóteses originais:

```text
MIDWEEK higher vol -> not confirmed
MIDWEEK more EXTREME_FINISH -> rejected
MIDWEEK amplifies EF reversal -> rejected
MIDWEEK generally more directional -> rejected
```

`MON_FRI + EXTREME_FINISH` apareceu pós-hoc como candidato, mas estabilidade temporal mostrou forte dependência do período. Não promover.

Status:

```text
MON_FRI_EF_BINARY_REVERSAL = REGIME_DEPENDENT / NOT_STRUCTURAL
MON_FRI_EF_PERSISTENCE = PROMISING_REGIME_DEPENDENT_STATE
EXTREME_FINISH = STATE_MODIFIER_NOT_ENTRY_TRIGGER
```

Track A está metodologicamente consolidado. HIGH_VOL_MAIN continua descritivo; directional point-clock foi fechado por FWER.

---

# 4. Track D — Lower-TF structural state machine

## 4.1 Experiments 1-8 — simplificações fechadas

| Exp | Pergunta | Resultado formal |
|---|---|---|
| 1 | H4/H1/M15 FULL > PARTIAL continuation? | `REJECTED` |
| 2 | FULL onset geral? | `REJECTED`; primeira implementação era day-relative |
| 3 | FULL age monotonic exhaustion? | `REJECTED` |
| 4 | last aligner / formation path? | `REJECTED` |
| 5 | parent candle structural quality? | `REJECTED` |
| 6 | static confirmed target topology/count? | `REJECTED` |
| 7 | BREAK_CLOSE vs SWEEP_REJECT first touch? | `REJECTED` |
| 8 | OUTSIDE_15 vs INSIDE_15 / sequence state? | `NOT_CONFIRMED / REGIME_DEPENDENT` |

A árvore evoluiu de “direção/alinhamento” para máquina de estados:

```text
STATE
 -> ACTIVE STRUCTURE
 -> CURRENT LOCATION
 -> LEVEL INTERACTION
 -> ACCEPTANCE / RECAPTURE
 -> NEXT STRUCTURAL EVENT
 -> NEW STATE
```

## 4.2 Exp9 — sequential swing consumption

Depois de `OUTSIDE_15`, o próximo evento competidor era `ADVANCE_BOS` ou `RECAPTURE_L1`.

Incidência:

```text
ADVANCE ~60-64%
RECAPTURE ~35-39%
```

Muito estável descritivamente, porém geometria confundia o resultado. `L2` colapsava para M15.

Status: `TRANSITION_INCIDENCE_ROBUST_DESCRIPTIVE_BUT_GEOMETRY_CONFOUNDED`.

## 4.3 Exp10 — corridor geometry

Definição:

```text
d_back = oriented distance state -> L1
d_forward = oriented distance state -> L2
CorridorPosition = d_back/(d_back+d_forward)
```

Raw `P(ADVANCE)=CorridorPosition` era excessivamente confiante e foi rejeitado como probability model.

Mesmo assim, ranking transportou:

```text
AUC TRAIN .6970
AUC VAL   .6652
AUC TEST  .6459
Spearman .3328 / .2784 / .2418
```

Primeira descoberta forte de Track D:

```text
CORRIDOR_POSITION_TRANSITION_DISCRIMINATION = STRONG_OOS_RESEARCH_FEATURE
```

## 4.4 Exp11-15 — attempted residual explanations

```text
Exp11 AcceptancePressure15 -> rejected incremental
Exp12 expanding prequential recalibration -> rejected general solution
Exp13 exact MTF L2 provenance -> rejected incremental
Exp14 prior exact L2 touch memory + age control -> rejected
Exp15 current L2 confirmation recency -> rejected
```

Exp14/15 fecharam a família simples de “idade/memória exata do mesmo preço”: touch count e recency não transportaram; havia confounding idade/touch e shift temporal de age.

Status: `EXACT_PRICE_AGE_MEMORY_FAMILY = CLOSED`.

## 4.5 Exp16 — ACTIVE STRUCTURAL FRONTIER

Esta foi uma correção de representação decisiva. O antigo algoritmo mantinha swings “imortais” no histórico; Exp16 passou a consumir níveis quando estruturalmente atravessados, mantendo apenas frontier ativo causal.

Coverage do novo estado:

```text
TRAIN ~91%
VAL   ~93%
TEST  ~100%
```

Ranking da próxima fronteira melhorou materialmente:

```text
AUC ~.765 / .774 / .797
Brier skill ~+20% / +22% / +25%
```

Status:

```text
ACTIVE_STRUCTURAL_FRONTIER = MAJOR_REPRESENTATION_FIX
LEGACY_IMMORTAL_L2 = SUPERSEDED
CURRENT_ACTIVE_CORRIDOR = CORE_STATE_REPRESENTATION
```

## 4.6 Exp17 — recursive frontier Step2

A mesma representação foi propagada para o segundo passo estrutural. Ranking transportou fortemente; parâmetros exatos não foram invariantes.

Status: `DEPTH_TRANSPORTABLE_RANKING / EXACT_CALIBRATION_NOT_INVARIANT`.

## 4.7 Exp18 — pooled Step1+Step2 with step identity

Adicionar identidade explícita do passo não melhorou OOS; piorou a modelagem pooled.

Status:

```text
STEP_IDENTITY_INCREMENT = REJECTED
GEOMETRY_RANKING_ACROSS_DEPTH = STRENGTHENED
```

## 4.8 Exp19 — prior corridor geometry memory

Geometria do corredor anterior não adicionou informação OOS depois de conhecer o corredor atual.

Status:

```text
PRIOR_CORRIDOR_GEOMETRY_MEMORY = REJECTED
CURRENT_ACTIVE_CORRIDOR = MARKOV_SUFFICIENT_RANKING_STATE CANDIDATE
```

---

# 5. Track D — one-step probabilistic kernel

## 5.1 Exp20 — dynamic one-step Markov kernel

Sample:

```text
TRAIN 5612 states / 596 episodes / 207 days
VAL   1959 / 204 / 80
TEST  2096 / 212 / 73
STAY ~90%
```

Frozen geometry-only logits:

```text
ADV vs STAY: intercept -3.517028, geo +0.857591
REC vs STAY: intercept -3.813144, geo -0.844111
```

Scores vs TRAIN class-frequency constant:

```text
Brier skill  TRAIN +10.42% / VAL +7.47% / TEST +6.28%
LogLoss skill TRAIN +19.19% / VAL +18.35% / TEST +17.76%
```

Exit-side ranking:

```text
AUC ADV .8521 / .8160 / .8751
AUC REC .8158 / .8697 / .8120
P(ADV|EXIT) AUC-like side structure ~.958 / .964 / .983
```

Corrected STATE_WEIGHTED whole-day bootstrap:

```text
VAL Brier gain +.013625 CI[+.007887,+.020397]
VAL LL gain    +.071309 CI[+.058585,+.086666]
TEST Brier     +.011017 CI[+.003736,+.019730]
TEST LL        +.066682 CI[+.050761,+.086336]
```

Status:

```text
EXP20_STATE_WEIGHTED_VALIDATION = PASS
EXP20_STATE_WEIGHTED_TEST = PASS
ACTIVE_CORRIDOR_GEOMETRY = STRONGLY_REAFFIRMED
EXIT_SIDE_GEOMETRY = VERY_STRONG_OOS_STRUCTURE
RUNTIME_PROMOTION = NONE
```

## 5.2 Exp21 — semi-Markov Dwell

Frozen coefficients:

```text
ADV [-2.337951,+0.920362,-0.617819]
REC [-2.788824,-0.786389,-0.535507]
```

Longer surviving corridor episodes suppress EXIT hazard; side remains mostly governed by geometry.

SEMI scores:

```text
TRAIN Brier .161492 LL .297183
VAL   Brier .165581 LL .301128
TEST  Brier .159127 LL .285883
```

Corrected primary STATE_WEIGHTED whole-day bootstrap, SEMI over GEO:

```text
VAL Brier +.003132 CI[-.000497,+.007070]  -> borderline
VAL LL    +.016177 CI[+.007809,+.025290] -> pass
TEST Brier+.005169 CI[+.000163,+.010445] -> pass
TEST LL   +.022839 CI[+.011983,+.033512] -> pass
```

Frozen strict rule exigia ambos metrics em ambos OOS splits. Portanto 3/4 passam, mas não 4/4.

Status:

```text
DWELL_INCREMENTAL_INFORMATION = POSITIVE_BUT_NOT_FULLY_RECONFIRMED
DWELL_LOGLOSS = PASS_VAL_AND_TEST
DWELL_BRIER_TEST = PASS
DWELL_BRIER_VALIDATION = BORDERLINE
SEMI_MARKOV_EXTENSION = FROZEN_CHALLENGER
POSITION_PLUS_DWELL = NOT_YET_FINAL
```

## 5.3 Exp22 — two-state latent daily hazard HMM

HMM degenerou para estado HIGH quase default (~97.9%) e LOW raro/transiente. Pequenos ganhos de score foram reproduzíveis, mas estado causal pre-day ficou quase constante.

Status:

```text
TWO_STATE_PERSISTENT_LATENT_HAZARD_REGIME = NOT_CONFIRMED
LATENT_STATE_IDENTIFIABILITY = POOR/DEGENERATE
SEMI_MARKOV_BACKBONE = PRESERVED
```

## 5.4 Exp23 — temporal ablation

Static stationary mixture reproduziu praticamente todo ganho do HMM; causal HMM propagation acrescentou ~zero.

Status:

```text
EXP23_TEMPORAL_MEMORY_SURVIVAL = REJECTED
DAILY_TWO_STATE_HMM_TEMPORAL_INFORMATION = REJECTED
EXP22_GAIN_MECHANISM = STATIC_MIXTURE/CALIBRATION_MAP
HMM_BRANCH = CLOSED AGAINST POST_HOC RESCUE
```

### Static-shift methodological correction

Uma sugestão externa de common Platt intercept shift no mesmo TRAIN foi rejeitada como redundante: o multinomial MLE do Exp21 já possui intercept score equations; mesmo-TRAIN common shift não cria nova evidência.

---

# 6. Exp24-26 — Scale, estimand e backbone re-audit

## 6.1 Exp24 — active corridor Scale

Frozen feature:

```text
CorridorWidthATR
Scale=log(CorridorWidthATR)
common k added to both EXIT logits
P(ADV|EXIT) invariant
```

TRAIN `k=-0.217886`, mas frozen primary equal-day/equal-episode result foi negativo em VAL/TEST.

Formal:

```text
ACTIVE_CORRIDOR_SCALE_INCREMENTAL_INFORMATION = REJECTED_UNDER_FROZEN_EXP24_CONTRACT
SCALE_PHYSICAL_SIGN = NOT_ACCEPTED
POSITION_PLUS_DWELL = PRESERVED
```

Nunca retroativamente resgatar Exp24.

## 6.2 Exp25 — estimand / informative cluster-size audit

Este experimento não testou feature nova; mostrou que **o estimand é parte da pergunta científica**.

Scale gains mudavam radicalmente conforme ponderação:

```text
STATE_WEIGHTED positive point estimate
DAY_WEIGHTED negative
EPISODE_WEIGHTED more negative
```

Identidade exata:

```text
STATE_WEIGHTED - EQUAL_CLUSTER
= Cov(N_cluster, mean_gain_cluster)/E[N_cluster]
```

Conclusão permanente:

```text
ESTIMAND MUST BE DECLARED BEFORE THE EXPERIMENT
DEPENDENCE CORRECTION MUST PRESERVE THAT ESTIMAND
```

Para Track D current-state kernel:

```text
PRIMARY = STATE_WEIGHTED
UNCERTAINTY = whole-BRT-day bootstrap preserving state weights
DAY_WEIGHTED / EPISODE_WEIGHTED = mandatory heterogeneity diagnostics
```

Scale permaneceu rejeitado.

## 6.3 Exp26 — backbone estimand re-audit

Reproduziu exatamente amostra/modelos Exp20/21 e corrigiu a inferência sob o estimand declarado.

Resultado:

```text
Geometry > Constant = very strong PASS in VAL and TEST
SEMI > Geometry = 3/4 strict cells pass
VAL Brier Dwell = only borderline cell
```

Formal:

```text
ACTIVE_CORRIDOR_GEOMETRY = STRONGLY_REAFFIRMED
CORRIDOR_POSITION = CORE_STATE_COORDINATE
EXP20_STATE_WEIGHTED_VAL = PASS
EXP20_STATE_WEIGHTED_TEST = PASS
EXP21_STRICT_RECONFIRMATION = NOT_FULLY_PASSED
SEMI_MARKOV = FROZEN CHALLENGER
ACTIVE_CORRIDOR_SCALE = REMAINS REJECTED
DAILY_HAZARD_HMM = REMAINS REJECTED
```

---

# 7. Exp27 — fresh forward shadow

Frozen prospective start:

```text
SHADOW_START = 2026-08-13 00:00:00 BRT
```

Models congelados:

```text
MODEL0 CONST = [0.89967926,0.03866714,0.06165360]
MODEL1 GEO   = frozen Exp20
MODEL2 SEMI  = frozen Exp21
```

Maturity gate:

```text
>=60 eligible BRT days
AND
>=1500 dynamic structural states
```

Antes dos dois thresholds:

```text
counts-only may be inspected
NO Brier
NO LogLoss
NO AUC
NO calibration
NO gains
```

One-shot primary após maturidade:

```text
A: GEO vs CONST
B: SEMI vs GEO
STATE_WEIGHTED Brier + LogLoss
whole-day bootstrap preserving state weights
```

Nenhuma feature descoberta após freeze pode entrar no Exp27.

Status: `FROZEN / ACCUMULATING / UNTOUCHED`.

---

# 8. Exp28-30 — historical post-freeze discoveries, all isolated from shadow

## 8.1 Exp28 — HIGH_VOL_MAIN common EXIT-hazard modulator

Feature:

```text
HighVol_t = 1 inside [09:05,12:30)
centered by TRAIN prevalence
one common k_phase on ADV and REC logits
P(ADV|EXIT) invariant
```

TRAIN:

```text
k_phase=+.537702
exp(k)=1.712
```

Descriptive EXIT uplift existed in all splits, but magnitude did not transport.

Primary STATE_WEIGHTED:

```text
VAL Brier gain -.000874 CI[-.003030,+.001250]
VAL LL gain    -.001421 CI[-.005127,+.002250]
TEST Brier     +.001052 CI[-.000051,+.002224]
TEST LL        +.002643 CI[+.000779,+.004610]
```

Frozen rule required both metrics >0 in both OOS splits.

Status:

```text
HIGH_VOL_MAIN_COMMON_HAZARD_MODULATOR = REJECTED
HIGH_VOL_MAIN_ACTIVITY_PHENOMENON = STILL PRESENT DESCRIPTIVELY
FIXED_CLOCK_HAZARD_MULTIPLIER = NOT TRANSPORTABLE
```

## 8.2 Exp29 — local M5 range energy

Frozen feature:

```text
RangeATR=(M5_high-M5_low)/M5_ATR
EnergyRaw=log1p(RangeATR)
EnergyCentered=EnergyRaw-TRAIN_mean
one common k_energy on EXIT logits
```

TRAIN:

```text
k_energy=+.275719
exp(k)=1.317
```

Feature distribution was stable and weakly correlated with geo/dwell, but predictive effect failed.

Primary:

```text
VAL Brier StateGain -.000452 CI[-.000883,-.000047]
VAL LL             -.000680 CI[-.001435,+.000046]
TEST Brier          +.000043 CI[-.000423,+.000525]
TEST LL             -.000107 CI[-.000894,+.000655]
```

Status:

```text
LOCAL_M5_RANGE_ENERGY = REJECTED
FIXED_CURRENT_BAR_ENERGY_HAZARD = NOT TRANSPORTABLE
BODY/WICK/ABSRETURN/TRUERANGE/VOLUME RESCUE = PROHIBITED
```

## 8.3 Exp30 — D1 bullish context as EXIT-side prior

Frozen context:

```text
FULL_UP
+ daily_direction BULLISH
+ .70<=D1Position<.90
+ 09:00-18:00 BRT
```

Only `P(ADVANCE|EXIT)` could change; `P(EXIT)` stayed exact.

Sample flagged EXITs:

```text
TRAIN 40
VAL   16
TEST  17
```

TRAIN:

```text
k_side=-.606936
odds multiplier .545
```

Primary EXIT_WEIGHTED whole-day bootstrap:

```text
VAL Brier - .001264 CI[-.004944,+.001215]
VAL LL    - .004871 CI[-.014890,+.002802]
TEST Brier -.000178 CI[-.002656,+.002027]
TEST LL    +.000641 CI[-.004954,+.005795]
```

Status:

```text
D1_BULL_EXIT_SIDE_MODULATOR = REJECTED
D1_CONTEXT_AS_LOCAL_BOUNDARY_PRIOR = NOT SUPPORTED
ALTERNATE_D1_BANDS / BEARISH_MIRROR RESCUE = PROHIBITED
EXIT_SIDE_GEOMETRY = PRESERVED
```

Importante: isso não invalida o antigo D1 `.70-.90 bullish` no target 120m. Exp30 perguntou um estimand diferente: `P(ADVANCE boundary | EXIT)`.

---

# 9. Track B — Multi-day DNA, Exp31-37

Track B foi aberto depois do Exp30 para investigar estrutura diária/multi-day sem contaminar o Track D.

## 9.1 Exp31 — two-day directional streak

Pergunta:

```text
sign_{d-1}=sign_{d-2}
-> muda P(sign_d=sign_{d-1})?
```

Sample:

```text
TRAIN 218 days / 44 weeks
VAL    77 / 15
TEST   72 / 15
```

TRAIN `Streak2` continuation 49.47%; TEST caiu para 29.41%.

Primary TEST:

```text
Brier gain -.009529 CI[-.017070,-.001113]
LL gain    -.019165 CI[-.034231,-.002141]
```

Status: `REJECTED / SIMPLE_MULTI_DAY_SIGN_SEQUENCE_NOT_TRANSPORTABLE`.

## 9.2 Exp32 — previous range compression -> next-day expansion

Frozen:

```text
RangeRef20 = median of previous 20 completed days
RangeRatio = DayRange/RangeRef20
PrevCompress=1 iff previous RangeRatio<1
y_expand=1 iff current RangeRatio>1
```

TRAIN effect and Validation looked strong; TEST collapsed to no difference:

```text
TEST PrevCompress=1 NextExpand 46.15%
TEST PrevCompress=0 NextExpand 45.45%
```

Primary TEST gains ~zero/negative, CIs crossing zero.

Status: `REJECTED / COMPRESSION_TO_NEXT_DAY_EXPANSION_NOT_TRANSPORTABLE`.

## 9.3 Exp33 — previous-day directional efficiency

```text
Efficiency=abs(Close-Open)/(High-Low)
feature=Efficiency_{d-1}
target=next-day directional continuation
```

TRAIN learned positive `k=+.623642`; relation inverted OOS.

TEST:

```text
Brier gain -.009878 CI[-.016083,-.003272]
LL gain    -.020146 CI[-.032914,-.006471]
```

Status: `REJECTED / SIGN_REVERSAL_OOS`.

## 9.4 Exp34 — medium-term structural location

```text
Position20=(Close-Low20)/(High20-Low20)
AlignedPosition20=day_sign*(2*Position20-1)
feature=previous aligned position
target=next-day continuation
```

TRAIN `k=+.393792`; Validation near zero; TEST relation reversed.

TEST:

```text
Brier gain -.011262 CI[-.018108,-.004310]
LL gain    -.022942 CI[-.037240,-.008537]
```

Status: `REJECTED`.

Após Exp34, busca sequencial de feature simples foi pausada por desenho prévio.

## 9.5 Exp35 — temporal-stability audit

Nenhuma feature nova. Reconstruiu Exp31-34 e dividiu 71 ISO weeks em exatamente 6 eras contíguas:

```text
12 / 12 / 12 / 12 / 12 / 11 weeks
```

Sinais por era:

```text
Streak2Diff        [+ + + + - -]
EfficiencySpearman [+ - + - - -]
LocationSpearman   [- + + + + -]
PrevCompressDiff   [- + - - - +]
```

Base-rate spans:

```text
Continuation 33.93% -> 50.82% = 16.89 pp
Expansion    43.64% -> 52.54% = 8.91 pp
```

Descritivamente parecia haver instabilidade temporal, mas Exp35 era somente diagnóstico; nenhuma hipótese de regime foi autorizada.

## 9.6 Exp36 — whole-week temporal exchangeability

Pergunta: a heterogeneidade cronológica do Exp35 é maior do que em realocações aleatórias das mesmas semanas para pseudo-eras do mesmo tamanho?

10k permutations, same whole-week allocation for all diagnostics.

Resultados:

```text
ContinuationBaseRate p_perm 49.08%
Streak2Diff          p_perm  9.68%
EfficiencySpearman   p_perm 13.84%
LocationSpearman     p_perm 37.53%
ExpansionBaseRate    p_perm 97.74%
PrevCompressDiff     p_perm 31.65%
```

Frozen summary:

```text
conditional rejections = 0/4
base-rate rejections = 0/2
```

Portanto:

```text
TEMPORAL_CONDITIONAL_INSTABILITY = NOT STATISTICALLY STRENGTHENED
BASE_RATE_NONSTATIONARITY = NOT SUPPORTED BY THIS FROZEN TEST
REGIME_MODEL_JUSTIFICATION_FROM_EXP35_36 = NOT ESTABLISHED
```

Exp35 sign flips foram rebaixados para comportamento compatível com finite-sample/week-allocation variability sob este teste.

## 9.7 Exp37 — first-order daily-sign Markov dependence

Pre-run correction importante: null `P(continue)=.5` foi retirado antes de execução, porque marginal UP/DOWN pode ser desbalanceada mesmo sob independência.

Frozen NULL:

```text
pi_up=P_TRAIN(UP)
ignora previous sign
```

MARKOV1:

```text
P(UP|prevUP)
P(UP|prevDOWN)
```

TRAIN:

```text
P(UP)=57.08%
P(UP|prevUP)=50.79%
P(UP|prevDOWN)=65.59%
diff=-14.80 pp
```

Descriptive OOS anti-persistence attenuated:

```text
VAL diff=-10.00 pp
TEST diff=-5.64 pp
```

Primary:

```text
VAL Brier gain +.001665 CI[-.014004,+.017362]
VAL LL gain    +.003172 CI[-.029654,+.035724]
TEST Brier     -.003713 CI[-.016664,+.007299]
TEST LL        -.008448 CI[-.035523,+.014685]
```

Status:

```text
FIRST_ORDER_DAILY_SIGN_MARKOV = REJECTED
STATIC_LAG1_DAILY_SIGN_DEPENDENCE = NOT CONFIRMED OOS
DESCRIPTIVE_ANTI_PERSISTENCE = PRESENT_BUT_ATTENUATING
TRACK_B_DAILY_DIRECTION = PAUSED/CLOSED
```

No higher-lag, shrinkage, rolling refit, asymmetric rescue or feature combinations are authorized from this branch.

---

# 10. Current GOLD DNA — consolidated interpretation

A representação de maior valor descoberta até agora é:

```text
STRUCTURAL CONTEXT
    -> ACTIVE FRONTIER
    -> CURRENT ACTIVE CORRIDOR
    -> CorridorPosition
    -> Dwell / survival state
    -> one-step transition kernel
        -> EXIT hazard
        -> ADVANCE vs RECAPTURE side
    -> NEXT ACTIVE FRONTIER
```

Current evidence hierarchy:

```text
CorridorPosition
    -> CORE / strongly reaffirmed
    -> especially strong for WHICH SIDE of EXIT

Dwell
    -> positive incremental evidence
    -> strong LogLoss and TEST Brier
    -> VAL Brier borderline under frozen STATE_WEIGHTED inference
    -> FROZEN CHALLENGER, not final

Scale
    -> rejected

Daily two-state HMM temporal memory
    -> rejected

HIGH_VOL fixed hazard coefficient
    -> rejected, while phase itself remains descriptive

Local M5 Range Energy common hazard
    -> rejected

D1 bullish side modifier inside Track D
    -> rejected

Track B simple daily/multi-day static kernels
    -> paused/closed after Exp31-37
```

Conceptual factorization still under research:

```text
Geometry/Position -> WHICH SIDE
Dwell             -> WHEN EXIT / survival
```

No third stable hazard coordinate has yet been identified.

---

# 11. Scientific anti-repeat ledger

Closed or prohibited without a separately preregistered new design:

```text
FULL alignment continuation
FULL onset general edge
FULL age thresholds
last-aligner selection
parent candle quality
static target-count topology
first break vs sweep rule
acceptance 5/10/20/30m retuning
AcceptancePressure thresholds/nonlinear rescue
rolling/forget-factor calibration rescue
exact-price MTF provenance tolerance search
exact L2 touch-count/age/recency family
prior corridor geometry memory
Step identity rescue
Scale thresholds/buckets/interactions
HMM state-count/multi-start rescue
clock window subdivision after Exp28
body/wick/abs-return/true-range/volume rescue after Exp29
alternate D1 bands/bearish mirror after Exp30
Streak3/Streak4 after Exp31
alternate range lookbacks/quantiles after Exp32
Efficiency thresholds/bins/splines/UP-DOWN split after Exp33
Position20 lookback/threshold variants after Exp34
post-hoc era/regime rules from Exp35
regime/HMM justification from Exp35 without Exp36 support
lag2/lag3/shrinkage/rolling rescue after Exp37
```

---

# 12. Fresh forward vs historical discovery

Permanent separation:

```text
HISTORICAL DISCOVERY LAB
    pre-shadow rows only
    may continue with preregistered families

EXP27 FRESH FORWARD SHADOW
    frozen models only
    no performance peek before maturity
    cannot validate post-freeze discoveries
```

This separation is mandatory.

---

# 13. New research execution policy — larger frozen batches

Decision added `2026-08-13` after Exp37: future research should stop progressing predominantly as “one variable -> one experiment -> inspect -> next variable”.

The default will become a **FROZEN RESEARCH BATCH / FAMILY TEST**.

## 13.1 Why

Item-by-item search is statistically inefficient and increases adaptive-selection risk. A larger frozen batch lets us see, in the same sample and under the same null, which coordinates are redundant, complementary or simply noise.

## 13.2 Batch design

Before any result is viewed, freeze a compact family, normally `4-8` scientifically distinct coordinates or hypotheses.

A batch should contain:

```text
1. SAME scientific target / estimand
2. SAME causal state universe
3. SAME TRAIN / VALIDATION / exploratory TEST boundaries
4. ALL candidate definitions frozen before scoring
5. one univariate screen per coordinate
6. one frozen joint model for incremental information
7. correlation / redundancy matrix
8. cluster-aware inference preserving estimand
9. family-wise multiplicity control when multiple candidate claims are made
10. one final family verdict
```

## 13.3 Multiple testing

If a batch makes multiple feature-level claims, use a predeclared family-level correction, e.g. max-statistic / Westfall-Young style resampling when dependence structure can be preserved, or Holm as a simpler fallback where appropriate.

Do not choose the correction after seeing which p-values are convenient.

## 13.4 Model comparisons

The preferred output of a future batch is not only “feature X passed”. It should answer:

```text
BASE model quality
+ each feature marginal gain
+ joint frozen family gain
+ incremental/drop-one contribution
+ redundancy between coordinates
+ calibration and discrimination
+ STATE/DAY/EPISODE heterogeneity where applicable
+ OOS transportability
```

## 13.5 Anti-adaptive rule

Within one frozen batch:

```text
NO threshold rescue
NO transform rescue
NO direction split rescue
NO window rescue
NO feature replacement after seeing results
```

A failed family closes as a family. A survivor can advance only under the predeclared family criterion.

## 13.6 Future naming

We may continue numbering experiments for history, but one experiment can now contain a **panel/family of hypotheses**, instead of testing a single scalar feature per round.

This is the new default research style.

---

# 14. Current checkpoint — 2026-08-13 12:37 BRT

## Track A

```text
HIGH_VOL_MAIN = robust descriptive activity phase
point-clock direction = rejected after FWER
EXTREME_FINISH = distributional state modifier, not entry trigger
```

## Track D

```text
ACTIVE FRONTIER = core representation
CorridorPosition = strongest structural coordinate
Exp20 geometry kernel = robust historical exploratory backbone
Dwell = frozen challenger, not fully reconfirmed by strict Exp26 rule
Scale / HMM / Clock hazard / Energy / D1 side modifier = rejected
```

## Exp27

```text
FROZEN
starts 2026-08-13
no score peek before >=60 days AND >=1500 states
```

## Track B

```text
Exp31-34 = rejected simple feature families
Exp35 sign instability = descriptive
Exp36 exchangeability rejection = 0/6
Exp37 first-order Markov daily sign = rejected
Track B daily-direction program = PAUSED/CLOSED
```

## Next research posture

Do **not** open an Exp38 as another isolated daily feature rescue.

While Exp27 accumulates:

```text
1. preserve the Track D backbone;
2. use historical-only discovery in larger preregistered batches;
3. choose genuinely new scientific families, not variants of rejected coordinates;
4. evaluate several related coordinates jointly under one frozen family-wise contract;
5. keep runtime promotion = NONE until prospective evidence exists.
```

The next research batch should be defined as a family first, with the full candidate panel and multiplicity/incremental-information plan frozen before execution.

---

# END OF CURRENT CHECKPOINT
