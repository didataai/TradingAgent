# GOLD Discovery History — TradingAgent

> Documento vivo de pesquisa. Objetivo: registrar **o que já foi testado, por que foi testado, como foi testado, o que funcionou, o que falhou e o que não deve ser repetido sem uma nova justificativa**.
>
> Este arquivo deve ser atualizado nas próximas rodadas de pesquisa, preservando o histórico. Achados superados não devem ser apagados; devem ser marcados como `REJECTED`, `SUPERSEDED`, `REGIME_DEPENDENT`, `SHADOW_ONLY`, `PROMISING_STATE` ou `CONFIRMED_RESEARCH`.

---

# 0. Regras de manutenção

1. Não apagar histórico.
2. Hipóteses refutadas permanecem registradas.
3. Quando uma hipótese evoluir, preservar a definição anterior e registrar a nova.
4. Thresholds inspecionados em TEST são exploratórios; o TEST atual não é mais holdout puro.
5. Promoções futuras exigem forward shadow congelado, nested/walk-forward ou novo período temporal.
6. Custos, spread e slippage ainda não foram incorporados à maior parte dos estudos.
7. O objetivo é construir um **Market State Model**, não empilhar filtros.
8. O estudo principal continua em `tools/study_d1_mtf_filter_v2.py`; evitar v3/v4 sem necessidade.
9. Pesquisas rápidas podem continuar em memória/PowerShell; o raciocínio e resultados relevantes entram neste arquivo.

---

# 1. Base de dados e metodologia

Símbolo: `GOLD`.

Research dataset aproximado:

```text
M5  ~100.000 candles
M15 ~50.000 candles
H1  ~20.000 candles
```

Arquivos principais:

```text
data/market_chronos/candle_base/timeframes/GOLD_M5_candle_research.parquet
data/market_chronos/candle_base/timeframes/GOLD_M15_candle_research.parquet
data/market_chronos/candle_base/timeframes/GOLD_H1_candle_research.parquet
```

Metodologia:

- D1 reconstruído point-in-time pelo broker-day MT5;
- `D1Position = (Price - LowSoFar)/(HighSoFar - LowSoFar)`;
- sem High/Low final do dia;
- H1/M15 somente disponíveis após fechamento do candle pai;
- split cronológico 60/20/20;
- prioridade: expectancy, PF, dias independentes, WR, sample, MFE/MAE;
- horizonte principal emergente para mean reversion: 120m.

---

# 2. Baseline MTF

```text
H1 == M15 == M5
```

OOS TEST 120m:

```text
n=2267
dias=77
WR=48.43%
Mean=-0.4116
PF=0.945
```

Status: `REFERENCE_BASELINE`.

---

# 3. D1 directional structure

## 3.1 D1 0.70-0.90 bullish + BUY alinhado

```text
D1Position 0.70-0.90
+ daily_direction BULLISH
+ H1/M15/M5 BUY alinhados
```

TEST 120m:

```text
n=358
dias=44
WR=56.70%
Mean=+4.1437
PF=1.6578
```

Conclusão: upper D1 antes do extremo >=0.90 preserva continuation BUY.

Status: `CONFIRMED_RESEARCH / STRONG_DIRECTIONAL_CONTEXT`.

## 3.2 D1 0.10-0.30 bearish + SELL alinhado

TEST 120m:

```text
n=208
dias=41
WR=49.52%
Mean=-0.9630
PF=0.8664
```

Conclusão: não existe simetria com o lado bullish. A antiga preferência SELL foi removida do scoring.

Status: `REJECTED_AS_DIRECTIONAL_SELL_EDGE`.

---

# 4. D1 extremes / anti-edge

## 4.1 EXTREME HIGH >=0.90 — BUY chase

TEST 120m:

```text
n=355
dias=35
WR=41.69%
Mean=-3.9499
PF=0.6393
```

Conclusão correta:

```text
D1 >= 0.90
-> AVOID BUY CHASE
```

Evitar BUY não implica SELL automático. O inverse SELL recente não foi estável em Train/Validation.

Status BUY chase: `STRONG_ANTI_EDGE_RULE_CANDIDATE`.

## 4.2 EXTREME LOW <=0.10 — SELL chase

TEST 120m:

```text
n=256
dias=32
WR=41.41%
Mean=-2.2447
PF=0.7268
```

Conclusão:

```text
D1 <= 0.10
-> AVOID SELL CHASE
```

Status: `STRONG_ANTI_EDGE_RESEARCH`.

---

# 5. Anti-edge -> inverse-edge

Inverter BUY/SELL nos mesmos timestamps é ferramenta de descoberta, não prova automática de edge.

Sem custos em horizonte fixo:

```text
mean_inverse ~= -mean_original
PF_inverse ~= 1/PF_original
WR_inverse ~= 1-WR_original
```

Resultado:

- extreme-high inverse SELL: positivo no TEST recente, instável historicamente;
- extreme-low inverse BUY: mais consistente, levando ao estudo Z-score.

Status: `USEFUL_DISCOVERY_TOOL`.

---

# 6. Lower-extreme M5 Z-score mean reversion

Definição:

```text
window=20 candles M5 (~100m)
z=(close-rolling_mean)/rolling_std_population
```

Hipótese:

```text
D1 EXTREME_LOW
+ H1 DOWN
+ M15 DOWN
+ Z20 <= -2
-> BUY mean reversion
```

120m:

```text
TRAIN      n=195 WR=65.64% Mean=+4.05 PF=2.02
VALIDATION n=69  WR=62.32% Mean=+9.31 PF=2.21
TEST       n=100 WR=72.00% Mean=+7.07 PF=2.87, 29 dias
```

Status: `STRONG_SHADOW_CANDIDATE`.

---

# 7. Z-score sensitivity

```text
Z=-1.5 PF train/val/test = 1.82 / 1.17 / 1.78
Z=-2.0 PF train/val/test = 2.02 / 2.21 / 2.87
Z=-2.5 PF train/val/test = 2.93 / 1.49 / 7.25
```

Z=-3 teve sample pequeno.

Conclusão: existe uma família de overextension/mean reversion; `-2.0` é o melhor equilíbrio atual de qualidade/amostra, não um threshold mágico.

Não continuar otimizando Z no mesmo TEST.

---

# 8. High-side Z-score SELL

```text
D1 EXTREME_HIGH + H1 UP + M15 UP + z alto -> SELL
```

PF 120m aproximado:

```text
Z=1.5 train .84 / val .33 / test 1.97
Z=2.0 train .95 / val .27 / test 1.79
Z=2.5 train .83 / val .20 / test 1.34
```

Conclusão: provável regime flip recente, não edge estrutural.

Status: `NOT_PROMOTED / REGIME_FLIP_EVIDENCE`.

---

# 9. Candle rejection variants

Rejection high/low produziu alguns PFs enormes com sample muito pequeno.

Conclusão: não usar como filtro obrigatório.

Status: `EXPERIMENTAL_SMALL_SAMPLE`.

---

# 10. First event per day

LOW Z=-2, 120m:

```text
TRAIN first/day PF=1.29
VALIDATION first/day PF=0.82
TEST first/day PF=2.40
```

Conclusão: primeiro toque não explica o edge completo. Eventos repetidos no dia carregam informação.

Status: `FIRST_TOUCH_ONLY_REJECTED`.

---

# 11. Event order / persistence

Persistência parecia melhorar, porém candles consecutivos podiam ser o mesmo evento.

Exemplos 120m:

```text
TRAIN 1st 1.29 / 2nd 1.30 / 3rd 1.72 / 4th+ 7.16
VAL   1st .82  / 2nd 1.01 / 3rd 1.03 / 4th+ 10.66
TEST  1st 2.40 / 2nd 5.06 / 3rd 6.66 / 4th+ 2.19
```

Status: `SUPERSEDED_BY_HYSTERESIS_EPISODES`.

---

# 12. Episode model sem histerese

False->true simples sofria threshold chatter e reentrada por mudança de filtros.

Status: `SUPERSEDED`.

---

# 13. Hysteresis episode model

Definição congelada:

```text
ENTER: z <= -2.0
RESET only: z > -1.5
```

Objetivo: separar episódios reais de stress de múltiplos candles consecutivos.

---

# 14. Second hysteresis episode + lower extreme

Com contagem pós-09:

```text
TRAIN      n=14 WR=71.43% Mean=+4.76 PF=2.14
VALIDATION n=4  WR=75.00% Mean=+2.85 PF=1.48
TEST       n=13 WR=69.23% Mean=+6.17 PF=3.32
```

Status: `PROMISING_SMALL_SAMPLE_SHADOW`.

---

# 15. Horizon do second episode

```text
TRAIN 30=.97 / 60=1.14 / 90=1.82 / 120=2.14 / 150=3.12 / 180=5.04
TEST  90=1.81 / 120=3.32 / 150=2.32 / 180=2.24
```

120m mantido porque Train/Validation/Test permanecem positivos e Test não confirma crescimento monotônico até 180m.

---

# 16. Episode reset boundary

```text
OP_09       31 eventos
OPEN_08      4 eventos
BROKER_DAY   0 eventos
Jaccard OP09 vs OPEN08 ~2.94%
```

Conclusão: não é o segundo episódio do dia; é um **POST-09 STRESS CYCLE**.

Status: `IMPORTANT_SESSION_RELATIVE_DISCOVERY`.

Feature: `Post09StressCycle`.

---

# 17. EP1/EP2/EP3/EP4+

TRAIN 120m:

```text
EP1 n=6  PF=.88 Mean=-1.09 D1med=.012 Zmed=-2.45
EP2 n=14 PF=2.14 Mean=+4.76 D1med=.043 Zmed=-2.22
EP3 n=12 PF=.86 Mean=-.61
EP4+ n=15 PF=5.72 Mean=+6.56
```

TEST:

```text
EP1 PF=.49
EP2 PF=3.32
EP3 PF=28.89 n=5 frágil
EP4+ PF=1.50
```

EP1 foi mais profundo em D1/Z no Train, mas pior que EP2. Logo ordinal/sequência carrega informação além da profundidade.

Status EP2: `PROMISING_SEQUENCE_INFORMATION`.

---

# 18. Time-of-day around EP2

10:00-11:30 apareceu interessante em Train/Test, mas Validation não tinha sample suficiente.

Status: `FEATURE_CANDIDATE_ONLY`.

---

# 19. Opening-flow 08-09 -> 10-11:30

Primeira hipótese simples usando HIGH/NOT_HIGH por range e weekdays não foi estável.

Exemplo Tue-Thu NOT_HIGH SignedMean:

```text
TRAIN -0.34
VAL   -2.68
TEST  +3.34
```

Status: `SIMPLE_RULE_REJECTED`.

---

# 20. Weekday

Tue/Wed/Thu não foi estável como regra standalone.

Status: `NOT_A_STANDALONE_RULE`.

---

# 21. 20:00-01:00 -> 08:00-09:00 opening echo

Direction SAME:

```text
TRAIN 54.72%
VAL   61.84%
TEST  48.68%
```

Signed magnitude:

```text
TRAIN +0.41
VAL   +2.72
TEST  +0.46
```

Conclusão: binary echo não confirmado; força/eficiência pode carregar informação.

Status: `FEATURE_CANDIDATE`.

---

# 22. Directional impulse 08-09

`STRONG IMPULSE = high range percentile + high directional efficiency percentile`.

ECHO+STRONG para 10-11:30:

```text
TRAIN CONT 57.14%, median +0.54
VAL   CONT 58.33%, median +5.95, mean negativa por tails
TEST  CONT 66.67%, median +7.05
```

Interessante, mas sample pequeno.

Status: `PROMISING_STATE_FEATURE / SMALL_SAMPLE`.

---

# 23. 09-10 transition/rest

ECHO+STRONG mediana 09-10:

```text
TRAIN -0.35
VAL   -0.04
TEST  -0.20
```

10-11:30 mediana:

```text
TRAIN +0.03
VAL   +0.19
TEST  +0.22
```

Possível estrutura: pullback/rest -> later continuation. Não promovido porque horários ainda eram manuais.

Status: `DESCRIPTIVE_TRANSITION_HYPOTHESIS`.

---

# 24. Mudança metodológica — relógio descoberto pelos dados

Foram varridos 288 slots M5 das 24h usando volatilidade relativa, efficiency, continuation 60/120m e probability continuation.

Primeiro detector revelou gaps/feed como falsos change points e warnings `Mean of empty slice`.

Status inicial: `SUPERSEDED_BY_COVERAGE_AWARE_ZONE_DISCOVERY`.

---

# 25. Data-driven Market Clock

Volatility peaks:

```text
09:30
10:05
10:35-10:45
11:05-11:10
11:20-11:40
```

Núcleo mais forte: ~10:35-10:45.

Candidatos pontuais iniciais:

- ~20:50 continuation;
- ~13:30 reversal.

Posteriormente avaliados como zonas + bootstrap por dia.

---

# 26. Stable intraday zones

High-volatility zones:

```text
04:05-04:15
09:05-12:30
21:05-21:15
22:05-22:25
22:35-22:45
```

Principal:

```text
09:05-12:30 BRT
TRAIN ~1.47 / VAL ~1.42 / TEST ~1.41
```

Continuation candidates 120m:

```text
00:00-00:10
20:10-20:20
22:00-22:10
23:35-24:00
```

Reversal candidates 120m:

```text
06:20-07:15
07:25-08:00
12:55-13:45
```

---

# 27. Day-cluster bootstrap das zonas

Cada broker-day = uma observação; 10.000 reps.

## NIGHT_20

```text
TRAIN Mean +.110 Med -.031 CI[-.053,.272] P>0 91.10%
VAL   Mean +.025 Med +.043 CI[-.196,.238] P>0 58.81%
TEST  Mean +.252 Med +.118 CI[-.140,.649] P>0 89.55%
```

Status: `MIXED / NOT_PROMOTED`.

## NIGHT_22

Train mean=-.145, CI inteiro negativo, P(>0)=2.04%.

Status: `REJECTED_AS_STABLE_CONTINUATION`.

## NIGHT_2335

Train CI cruza zero; Validation positiva; Test quase positivo.

Status: `PROMISING_LATER_REGIME / EXPLORATORY`.

## PRE_MORNING_REV 06:20-08:00

```text
TRAIN P(<0)=99.82%
VAL   P(<0)=95.88%
TEST  P(<0)=49.63%
```

Status: `FAILED_OOS_STABILITY`.

## HIGH_VOL_MAIN 09:05-12:30

```text
TRAIN days=212 Mean=1.587 Med=1.530 CI[1.542,1.634] P(>1)=100%
VAL   days=77  Mean=1.513 Med=1.426 CI[1.425,1.606] P(>1)=100%
TEST  days=76  Mean=1.546 Med=1.508 CI[1.481,1.613] P(>1)=100%
```

Conclusão:

```text
09:05-12:30 = STRUCTURAL HIGH-VOLATILITY PHASE
```

Status: `ROBUST_DESCRIPTIVE_PHASE`.

## POST_VOL_REV 12:55-13:45

```text
TRAIN Mean=-.017 Med=-.113 P<0=65.70%
VAL   Mean=-.024 Med=-.106 P<0=62.68%
TEST  Mean=-.007 Med=-.085 P<0=52.40%
```

Status: `DESCRIPTIVE_HYPOTHESIS_ONLY`.

---

# 28. Decomposição da HIGH_VOL_MAIN

Objetivo: entender por que 09:05-12:30 produz continuation em alguns dias e reversal em outros.

Train-only thresholds:

```text
impulse          Q33=.326 Q67=.783
efficiency       Q33=.338 Q67=.614
terminal_extreme Q33=.669 Q67=.850
```

## Baseline da fase 120m

```text
TRAIN n=210 CONT=50.0% Mean=.028 Med~0
VAL   n=77  CONT=50.6% Mean~0 Med=.003
TEST  n=73  CONT=42.5% REV=57.5% Mean=-.073 Med=-.041
```

Status: `POSSIBLE_REGIME_DRIFT`.

## IMPULSE HIGH

```text
TRAIN n=64 REV=56.2% Mean=-.004 Med=-.040
VAL   n=24 REV=45.8% Mean=+.071 Med=+.009
TEST  n=14 REV=71.4% Mean=-.093 Med=-.143
```

Status: `NOT_STRUCTURAL_ALONE`.

## EFFICIENCY HIGH

```text
TRAIN REV=47.9% Mean=+.049 Med=+.020
VAL   REV=66.7% Mean=-.156 Med=-.033
TEST  REV=64.7% Mean=-.083 Med=-.077
```

Status: `REGIME_DEPENDENT`.

## TERMINAL HIGH / EXTREME_FINISH

```text
TRAIN n=71 REV=54.9% Mean=+.015 Med=-.026
VAL   n=22 REV=59.1% Mean=-.025 Med=-.023
TEST  n=21 REV=66.7% Mean=-.090 Med=-.089
```

Status antes do bootstrap dedicado: `PROMISING_EXHAUSTION_STATE`.

## STRONG_DIRECTIONAL

`impulse>=.783 AND efficiency>=.614`

```text
TRAIN n=48 REV=52.1% Mean=.001 Med=-.005
VAL   n=15 REV=60.0% Mean=-.059 Med=-.014
TEST  n=10 REV=70.0% Mean=-.096 Med=-.135
```

Status: `PROMISING_RECENT_EXHAUSTION / NOT_STRUCTURAL_YET`.

---

# 29. Interpretação da HIGH_VOL_MAIN

A hipótese inicial `high volatility + efficiency -> continuation` não foi confirmada estruturalmente.

Nova hipótese:

```text
HIGH_VOL_MAIN 09:05-12:30
        |
        +-- finish muito perto do extremo
        |      -> exhaustion/reversal propensity
        |
        +-- strong directional
               -> reversal crescente no regime recente
```

---

# 30. Achados por confiança

## Fortes

- D1 0.70-0.90 bullish aligned BUY continuation context.
- D1 EXTREME_HIGH -> avoid BUY chase.
- D1 EXTREME_LOW -> avoid SELL chase.
- D1 EXTREME_LOW + H1/M15 down + Z20<=-2 -> BUY mean-reversion shadow.
- HIGH_VOL_MAIN 09:05-12:30 -> structural high-volatility state.

## Promissores / shadow

- Post09StressCycle #2.
- HIGH_VOL terminal-extreme exhaustion propensity.
- StrongDirectional exhaustion no regime recente.

## Features sem regra

- OpeningFlowState
- DirectionalEfficiency
- ImpulseState
- TerminalExtreme
- MinutesFromPhaseChange
- weekday
- Post09StressCycle
- IntradayVolatilityPhase

## Rejeitados / não repetir sem nova hipótese

- bearish D1 0.10-0.30 como espelho SELL;
- high-side zscore SELL estrutural;
- rejection obrigatório;
- first-event/day como explicação suficiente;
- episódio sem histerese;
- second episode desde 08:00 ou broker-day;
- Tue/Wed/Thu standalone;
- binary opening echo standalone;
- NIGHT_22 continuation;
- PRE_MORNING_REV como regra estrutural;
- POST_VOL_REV standalone;
- high impulse = continuation;
- high efficiency = continuation.

---

# 31. Anti-repeat checklist

```text
[ ] D1 upper bullish continuation?
[ ] D1 lower bearish continuation?
[ ] EXTREME_HIGH BUY chase?
[ ] EXTREME_LOW SELL chase?
[ ] exact inverse?
[ ] Z sensitivity 1.5/2.0/2.5?
[ ] candle rejection?
[ ] first event/day?
[ ] event ordinal?
[ ] raw episodes?
[ ] hysteresis episodes?
[ ] 09:00 vs 08:00 vs broker-day reset?
[ ] EP1/EP2/EP3/EP4+?
[ ] 08-09 opening flow?
[ ] Tue/Wed/Thu?
[ ] 20-01 -> 08-09 echo?
[ ] range + directional efficiency?
[ ] 09-10 transition?
[ ] automatic 24h clock discovery?
[ ] stable volatility/continuation/reversal zones?
[ ] broker-day bootstrap of clock zones?
[ ] HIGH_VOL phase impulse/efficiency/terminal decomposition?
[ ] EXTREME_FINISH dedicated bootstrap?
[ ] STRONG_DIRECTIONAL dedicated bootstrap?
```

---

# 32. Statistical caveat

O TEST atual foi consultado repetidamente durante z sensitivity, event order, episodes, reset boundary, opening-flow, Market Clock e high-vol decomposition.

```text
TEST atual = exploratory OOS
NOT pristine final holdout
```

Promoções futuras requerem forward shadow/nested walk-forward/novo período + custos/slippage.

---

# 33. Arquitetura emergente

```text
D1Position
    |
DailyDirection
    |
H1 / M15 context
    |
M5 Z-score / stretch
    |
Post09StressCycle
    |
IntradayVolatilityPhase
    |
Impulse / Efficiency / TerminalExtreme
    |
OpeningFlowState
    |
MinutesFromPhaseChange
    v
MARKET STATE
```

Somente depois congelar estado estatístico, associar aberturas/fechamentos/overlaps/maintenance/reopen e DST-aware sessions.

---

# 34. Perguntas congeladas

1. Bootstrap EXTREME_FINISH com threshold `.850`.
2. Bootstrap STRONG_DIRECTIONAL com `.783/.614`.
3. Se sobreviverem, cruzar HIGH_VOL state x D1Position.
4. Depois cruzar com Post09StressCycle.
5. Corrigir directional Market Clock para multiple testing/data snooping.
6. Só depois associar sessões econômicas reais.

---

# 35. Decisões do projeto

Mantido:

- `tools/study_d1_mtf_filter_v2.py` como estudo principal;
- runtime `WARNING_ONLY_RESEARCH`;
- upper bullish BUY soft score;
- EXTREME_HIGH BUY chase penalizado;
- EXTREME_LOW SELL chase penalizado.

Corrigido:

- bearish SELL 0.10-0.30 removido.

---

# 36. Formato das próximas atualizações

Cada rodada deve registrar:

```text
DATE / RUN
QUESTION
WHY
FROZEN DEFINITION
DATA / SPLIT
RESULTS
INTERPRETATION
STATUS
WHAT CHANGED
WHAT NOT TO REPEAT
NEXT QUESTION
```

---

# 37. Checkpoint anterior — 2026-08-11

Resumo:

> GOLD apresenta assimetria D1, anti-edge claro nos extremos, família consistente de lower-extreme Z-score mean reversion, informação sequencial no second post-09 stress cycle e fase estrutural HIGH_VOL_MAIN 09:05-12:30. A decomposição sugeriu que terminar essa fase perto do extremo pode carregar exhaustion/reversal propensity.

---

# 38. 2026-08-11 — Dedicated bootstrap: EXTREME_FINISH e STRONG_DIRECTIONAL

## QUESTION

A tendência de reversão após a HIGH_VOL_MAIN é realmente condicionada pelo estado interno da fase, principalmente `EXTREME_FINISH`, ou é apenas ruído da amostra?

## WHY

O agregado `POST_VOL_REV` tinha medianas negativas, mas mean/bootstrap fracos. A hipótese evoluiu para: o pós-fase mistura dias diferentes. Precisávamos testar se `terminal_extreme` separa uma distribuição mais reversiva.

## FROZEN DEFINITIONS

```text
HIGH_VOL_MAIN = 09:05-12:30 BRT
horizon = 120m
EXTREME_FINISH = terminal_extreme >= 0.850
STRONG_DIRECTIONAL = impulse >= 0.783 AND efficiency >= 0.614
bootstrap = 10.000 reps
1 day = 1 phase observation
```

Thresholds não foram recalibrados.

## RESULTS — EXTREME_FINISH

### TRAIN

```text
n=71
REV=54.93%
Mean=+0.015
Median=-0.026
Trimmed=+0.008
Mean CI95 [-0.046,+0.078], P(mean<0)=31.30%
Median CI95 [-0.092,+0.077], P(median<0)=79.67%
REV CI95 [43.66%,66.20%], P(REV>50)=79.67%
```

Contrast vs complement:

```text
P(state mean lower)=65.93%
P(state median lower)=81.77%
P(state more REV)=85.03%
```

### VALIDATION

```text
n=22
REV=59.09%
Mean=-0.025
Median=-0.023
Trimmed=-0.079
Mean CI95 [-0.228,+0.224], P(mean<0)=61.29%
Median CI95 [-0.218,+0.037], P(median<0)=76.16%
REV CI95 [40.91%,77.27%], P(REV>50)=74.36%
```

Contrast vs complement:

```text
P(state mean lower)=63.16%
P(state median lower)=82.55%
P(state more REV)=85.34%
```

### TEST

```text
n=21
REV=66.67%
Mean=-0.090
Median=-0.089
Trimmed=-0.074
Mean CI95 [-0.202,+0.016], P(mean<0)=95.02%
Median CI95 [-0.236,+0.071], P(median<0)=94.51%
REV CI95 [47.62%,85.71%], P(REV>50)=94.51%
```

Contrast vs complement:

```text
P(state mean lower)=62.26%
P(state median lower)=83.17%
P(state more REV)=84.67%
```

## INTERPRETATION — EXTREME_FINISH

O resultado **não confirma um expectancy edge estrutural** porque os CIs da média cruzam zero e o contraste de mean é fraco.

Porém existe um padrão distribucional muito consistente:

```text
P(state more reversal vs complement)
TRAIN 85.03%
VAL   85.34%
TEST  84.67%
```

Também:

```text
REV rate 54.9% -> 59.1% -> 66.7%
median < 0 nos 3 splits
```

Isto sugere que `EXTREME_FINISH` é melhor interpretado como **reversal propensity / exhaustion state**, não como regra SELL/BUY ou expectancy edge isolado.

Status atualizado:

`PROMISING_DISTRIBUTIONAL_EXHAUSTION_STATE`.

Não promover como directional rule.

## EXTREME_FINISH — UP vs DOWN descriptive

```text
TRAIN: UP n=53 REV=54.72%, DOWN n=18 REV=55.56%
VAL:   UP n=12 REV=50.00%, DOWN n=10 REV=70.00%
TEST:  UP n=12 REV=66.67%, DOWN n=9 REV=66.67%
```

A condição não parece depender exclusivamente do lado. TEST apresentou exatamente 66.67% reversal em ambos os lados, mas samples ainda são pequenos.

Isto fortalece a interpretação de `terminal_extreme` como propriedade do **estado da fase**, e não simplesmente direção UP/DOWN.

## RESULTS — STRONG_DIRECTIONAL

### TRAIN

```text
n=48 REV=52.08%
Mean=+0.001 Median=-0.005 Trimmed=+0.002
P(mean<0)=48.70%
P(median<0)=57.53%
P(REV>50)=56.32%
P(state more REV)=62.42%
```

### VALIDATION

```text
n=15 REV=60.00%
Mean=-0.059 Median=-0.014 Trimmed=-0.057
P(mean<0)=83.96%
P(median<0)=78.62%
P(REV>50)=78.62%
P(state more REV)=82.17%
```

### TEST

```text
n=10 REV=70.00%
Mean=-0.096 Median=-0.135 Trimmed=-0.092
P(mean<0)=89.71%
P(median<0)=86.28%
P(REV>50)=84.83%
P(state more REV)=80.98%
```

## INTERPRETATION — STRONG_DIRECTIONAL

Train continua praticamente neutro. Validation/Test ficam mais reversivos, mas sample cai para 15/10.

Status permanece:

`REGIME_DEPENDENT_RECENT_EXHAUSTION_SIGNAL`.

Não utilizar como regra estrutural.

## WHAT CHANGED

Antes do bootstrap:

```text
EXTREME_FINISH -> possible exhaustion
```

Depois do bootstrap:

```text
EXTREME_FINISH -> consistent distributional reversal propensity
                  but NOT confirmed negative-expectancy edge
```

A nuance é importante: a feature parece deslocar a probabilidade/mediana para reversão, mas tails de continuation ainda impedem tratar isso como regra direcional simples.

## WHAT NOT TO REPEAT

- não recalibrar `terminal_extreme=0.850` no mesmo TEST;
- não transformar `EXTREME_FINISH` diretamente em SELL/BUY;
- não usar STRONG_DIRECTIONAL como regra estrutural com n=10 no TEST;
- não concluir pelo headline reversal rate sem olhar mean/median/contrast.

## NEXT QUESTION — FROZEN

Agora faz sentido cruzar o estado mais promissor com D1Position, porque já existe uma hipótese independente e prévia no D1:

```text
HIGH_VOL_MAIN + EXTREME_FINISH
x
D1 0.70-0.90 bullish continuation
versus
D1 >=0.90 anti-BUY-chase
versus
D1 <=0.10 anti-SELL-chase / lower mean-reversion family
```

Pergunta central:

> `terminal_extreme` é apenas uma propensão genérica de reversão, ou se torna muito mais informativo quando o D1 também está em um extremo?

Depois disso, cruzar com `Post09StressCycle` e só então voltar ao Market Clock directional com correção de multiple testing.

---

# END OF CURRENT CHECKPOINT

Próximas rodadas devem ser adicionadas abaixo deste ponto, mantendo o histórico acima.