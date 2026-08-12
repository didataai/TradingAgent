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
10. A partir de 2026-08-12, toda rodada relevante deve ser registrada no mesmo dia, incluindo pergunta, hipótese, definição congelada, resultado, interpretação, status, falhas e próxima pergunta.

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

# 34. Perguntas congeladas — histórico da fila anterior

1. Bootstrap EXTREME_FINISH com threshold `.850`.
2. Bootstrap STRONG_DIRECTIONAL com `.783/.614`.
3. Se sobreviverem, cruzar HIGH_VOL state x D1Position.
4. Depois cruzar com Post09StressCycle.
5. Corrigir directional Market Clock para multiple testing/data snooping.
6. Só depois associar sessões econômicas reais.

Esta fila é preservada como histórico; várias perguntas já foram executadas nas seções posteriores.

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

---

# 39. 2026-08-12 — EXTREME_FINISH x D1Position

## QUESTION

`EXTREME_FINISH` se torna mais informativo quando a fase também termina em uma região estrutural do D1?

## FROZEN DEFINITIONS

```text
HIGH_VOL_MAIN = [09:05,12:30) BRT
EXTREME_FINISH >= .850
UP EF + D1 0.70-.90 bullish
UP EF + D1 >= .90
DOWN EF + D1 <= .10
horizon = 120m
```

## RESULTS PRINCIPAIS

```text
UP EF + D1 >=.90
TRAIN n=39 REV=56.41% Mean=+.004 Med=-.026
VAL   n=10 REV=50.00% Mean=-.127 Med=-.054
TEST  n=6  REV=83.33% Mean=-.128 Med=-.215
```

Controle `UP EF + D1 .70-.90` colapsou em sample:

```text
TRAIN n=4
VAL   n=0
TEST  n=6
```

No TEST, o contraste D1>=.90 vs .70-.90 foi promissor, mas não pode ser confirmado historicamente por falta de Validation e sample.

Lado inferior:

```text
DOWN EF + D1 <=.10
TRAIN n=6 REV=66.67%
VAL   n=4 REV=50.00%
TEST  n=6 REV=50.00%
```

## INTERPRETATION

- `EXTREME_FINISH` não parece ser apenas D1>=.90 disfarçado; o D1 mediano do conjunto EF caiu ao longo dos splits enquanto a reversão subiu.
- D1>=.90 pode amplificar exaustão no lado UP, porém o cruzamento categórico destrói a amostra.
- Lado LOW não confirma espelho.

Status: `PROMISING_D1_HIGH_EXHAUSTION_AMPLIFIER / UNDERPOWERED_INTERACTION`.

WHAT NOT TO REPEAT: não empilhar D1 + EF + Z + EP2 em categorias pequenas neste dataset.

---

# 40. 2026-08-12 — Continuous exhaustion model

## QUESTION

Existe relação contínua/generalizável entre `TerminalExtreme`, pressão D1 e exaustão pós-HIGH_VOL_MAIN?

Modelos TRAIN-only:

```text
TERMINAL
D1
ADDITIVE
INTERACTION
```

Target: `reversal_strength = -response_120`.

## RESULTS

Lado UP, correlação score x reversal strength:

```text
                 TRAIN    VAL      TEST
TERMINAL         +.078   -.029    -.159
D1               +.058   -.000    -.446
ADDITIVE         +.078   -.026    -.211
INTERACTION      +.148   +.059    -.379
```

Lado DOWN também não apresentou correlação estável.

## INTERPRETATION

Não existe evidência de relação linear/monotônica generalizável `mais terminal + mais D1 -> mais exaustão`.

Isso não elimina o threshold-state `EXTREME_FINISH>=.850`: sugere efeito possivelmente **não linear / mudança de estado na cauda**, e não uma régua contínua.

Status:

```text
CONTINUOUS_MODEL = REJECTED_AS_GENERALIZABLE_LINEAR_MODEL
EXTREME_FINISH_THRESHOLD_STATE = PRESERVED
D1_CONTINUOUS_INTERACTION = NOT_CONFIRMED
```

---

# 41. 2026-08-12 — Phase Transition Curve

## QUESTION

Quando a propensão de reversão associada ao `EXTREME_FINISH` amadurece após o fim da HIGH_VOL_MAIN?

Horizontes pré-definidos: 15,30,45,60,90,120,150,180m.

## RESULTADO CENTRAL

Contraste `EXTREME_FINISH` vs OTHER em probabilidade de ser mais reversivo:

```text
              90m    120m    150m
TRAIN        80.5%   84.7%   91.8%
VAL          66.0%   85.1%   96.2%
TEST         82.1%   84.8%   69.1%
```

Mediana acumulada em 120m:

```text
TRAIN -.026
VAL   -.023
TEST  -.089
```

Em 180m o TEST perde/inverte a assinatura (`median +.023`, REV 42.9%).

## INTERPRETATION

- 90m: efeito começa a aparecer.
- 120m: anchor mais estável entre os três splits.
- 150m: forte em Train/Val, menos estável no Test.
- 180m: previsibilidade degrada.

Status: `PROMISING_PHASE_MATURITY_WINDOW_90_150 / 120M_ANCHOR`.

Não interpretar os acumulados como minuto exato de início da reversão.

---

# 42. 2026-08-12 — Incremental Transition Anatomy

## QUESTION

Qual bloco incremental de 30m constrói o efeito acumulado?

Blocos: 0-30, 30-60, 60-90, 90-120, 120-150, 150-180.

## RESULTS

O bloco com melhor repetição relativa foi 60-90m:

```text
               EF median   OTHER median   P(EF med lower)
TRAIN            -.015        -.001            76.2%
VAL              ~.000        +.016            69.3%
TEST             -.062        -.008            76.6%
```

P(mean lower): 94.9% / 64.3% / 85.5%.

Outros blocos mudam fortemente por regime. 120-150 é forte em Train/Val, mas não Test. 90-120 chega a inverter comportamento entre períodos.

## TIMING DISTRIBUTION

Primeiro acumulado negativo em 30m:

```text
TRAIN 49.3%
VAL   54.5%
TEST  54.5%
```

O timing de máximo reversal é heterogêneo; não existe um único bloco universal.

## CLOCK SEMANTICS

O código usa intervalo half-open:

```text
HIGH_VOL_MAIN = [09:05,12:30) BRT
```

Logo o último candle M5 incluído é sempre `12:25`, observado nos 364 dias.

Status: `60_90_CANDIDATE_TRANSITION_BLOCK / HETEROGENEOUS_TIMING`.

---

# 43. 2026-08-12 — Eventual reversal / depth / persistence

## QUESTION

`EXTREME_FINISH` aumenta a chance de entrar em reversão, a profundidade, ou principalmente o tempo permanecido do lado reversivo?

Path M5: 5..180m.

## EVENTUAL REVERSAL

A variável `EVER_NEGATIVE` ficou permissiva demais. No TEST, EF cruzou negativo menos vezes que OTHER:

```text
até 180m
EF    77.27%
OTHER 92.59%
```

Portanto `EXTREME_FINISH -> maior chance de tocar qualquer reversal` foi rejeitado.

## NEGATIVE FRACTION

Mediana da fração do path no lado reversivo:

```text
                 EF       OTHER
TRAIN           .611      .417
VAL             .833      .528
TEST            .792      .528
```

Bootstrap P(EF mean > OTHER):

```text
TRAIN 89.90%
VAL   90.25%
TEST  65.70%
```

## MAX REVERSAL DEPTH — MEDIANA

```text
                 EF       OTHER
TRAIN          -.203      -.165
VAL            -.261      -.200
TEST           -.313      -.191
```

Means são contaminadas por tails, especialmente no Test.

## INTERPRETATION

O melhor nome conceitual não é `PostHighVolReversalHazard`, mas algo como:

```text
PostHighVolExhaustionPersistence
```

`EXTREME_FINISH` não necessariamente faz o preço entrar mais vezes em reversão; ele parece associado ao dia típico permanecer mais tempo e/ou aprofundar mais no lado reversivo.

Status: `PROMISING_REVERSAL_PERSISTENCE_STATE`, ainda não regra direcional.

---

# 44. 2026-08-12 — MIDWEEK hypothesis x EXTREME_FINISH

## QUESTION

A hipótese pré-definida `Tue/Wed/Thu` melhora o padrão por maior volatilidade, maior ocorrência de EF ou maior persistência reversiva?

Grupos congelados:

```text
MIDWEEK = Tue/Wed/Thu
MON_FRI = Monday/Friday
```

## VOLATILITY

P(MIDWEEK phase-vol higher):

```text
TRAIN 45.88%
VAL   60.24%
TEST  66.62%
```

Não confirmado.

## EXTREME_FINISH OCCURRENCE

```text
                 MIDWEEK   MON_FRI
TRAIN             28.57%    41.18%
VAL               28.26%    29.03%
TEST              26.09%    33.33%
```

No TRAIN, P(MIDWEEK EF rate higher)=3.14%. Logo a hipótese de EF ocorrer mais no meio da semana foi rejeitada.

## EXTREME_FINISH OUTCOME

REV120:

```text
                 MIDWEEK   MON_FRI
TRAIN             44.44%    65.71%
VAL               46.15%    77.78%
TEST              58.33%    70.00%
```

NegativeFraction median:

```text
                 MIDWEEK   MON_FRI
TRAIN               .500      .722
VAL                 .417      .917
TEST                 .597      .861
```

## WITHIN-GROUP CONTROL

MON_FRI EF vs OTHER REV120:

```text
TRAIN 65.71% vs 36.00%
VAL   77.78% vs 45.45%
TEST  70.00% vs 50.00%
```

MIDWEEK EF vs OTHER é inconsistente.

## DID

A hipótese original era `MIDWEEK amplifies EF`. O DID não confirma; em negative_fraction o sinal é oposto:

```text
TRAIN DID -.160, P(midweek amplifies)=6.48%
VAL   DID -.345, CI95 [-.664,-.002], P=2.40%
TEST  DID -.049, P=40.44%
```

## INTERPRETATION

```text
MIDWEEK higher volatility -> NOT CONFIRMED
MIDWEEK more EF -> REJECTED
MIDWEEK amplifies EF reversal -> REJECTED
MON_FRI + EF exhaustion -> NEW EXPLORATORY CANDIDATE
```

Importante: `MON_FRI + EF` surgiu após inspeção dos resultados, portanto não é hipótese confirmatória.

---

# 45. 2026-08-12 — Week Cycle: direct trend quality

## QUESTION

Talvez Tue/Wed/Thu não sejam mais voláteis, mas sejam mais **tendenciais/direcionalmente persistentes** que Mon/Fri?

Medidas:

```text
PhaseEfficiency = abs(close-open)/range
PathEfficiency = abs(net move)/sum(abs(M5 moves))
AlignedFraction = fração de moves M5 alinhada à direção final
ImpulseRelative
TerminalExtreme
PostResponse120
```

## RESULTS — DIRECT TREND QUALITY

### TRAIN

MIDWEEK teve MENOR qualidade direcional:

```text
PhaseEfficiency diff -0.069, CI95 [-.137,-.000], P(mid higher)=2.42%
PathEfficiency  diff -0.035, CI95 [-.069,-.001], P=2.19%
AlignedFraction diff -0.019, CI95 [-.036,-.002], P=1.44%
TerminalExtreme diff -0.050, P=3.31%
```

### VALIDATION

Mesmo sentido, embora CIs mais largos:

```text
PhaseEfficiency diff -.072, P(mid higher)=9.21%
PathEfficiency  diff -.033, P=8.29%
AlignedFraction diff -.021, P=6.54%
TerminalExtreme diff -.059, P=8.83%
```

### TEST

Diferenças diminuem/mudam:

```text
PhaseEfficiency diff ~0
PathEfficiency diff -.009
AlignedFraction diff +.021, P(mid higher)=95.56%
ImpulseRelative diff +.019
TerminalExtreme diff -.017
```

PostResponse120 não apresenta diferença robusta:

```text
TRAIN diff +.023 CI crosses 0
VAL   diff +.033 CI crosses 0
TEST  diff +.015 CI crosses 0
```

## TERMINAL STATE x WEEK GROUP

A assinatura mais consistente permanece em `MON_FRI + EXTREME_FINISH`:

```text
MON_FRI EXTREME CONT120
TRAIN 34.29%
VAL   22.22%
TEST  30.00%

MON_FRI OTHER CONT120
TRAIN 63.27%
VAL   54.55%
TEST  44.44%
```

Diferença EF vs OTHER em continuation:

```text
TRAIN -28.98 pp
VAL   -32.33 pp
TEST  -14.44 pp
```

MIDWEEK EXTREME vs OTHER:

```text
TRAIN 55.56% vs 46.67%
VAL   53.85% vs 54.55%
TEST  36.36% vs 47.06%
```

inconsistente.

## INTERPRETATION

A teoria `Tue/Wed/Thu são mais tendenciais que Mon/Fri` **não é suportada de forma geral** pela HIGH_VOL_MAIN. Train e Validation apontam inclusive maior eficiência direcional em Mon/Fri; Test é misto.

O achado novo mais interessante é condicional:

```text
MON_FRI + EXTREME_FINISH
-> muito menor continuidade pós-fase
-> possível EDGE_WEEK_EXHAUSTION_STATE
```

Isso não autoriza excluir segunda/sexta. Pelo contrário: removê-las apagaria atualmente o subset mais reversivo associado ao `EXTREME_FINISH`.

Status:

```text
MIDWEEK_GENERAL_TREND_PERSISTENCE = REJECTED
MON_FRI_EXTREME_FINISH_EXHAUSTION = PROMISING_POST_HOC_CANDIDATE
```

---

# 46. Current checkpoint — 2026-08-12

## O que está forte

```text
D1 0.70-.90 bullish aligned -> continuation context
D1 >=.90 -> avoid BUY chase
D1 <=.10 -> avoid SELL chase
D1 low + H1/M15 down + Z20<=-2 -> mean-reversion shadow family
Post09StressCycle #2 -> promising small-sample sequence
HIGH_VOL_MAIN [09:05,12:30) -> robust structural volatility phase
```

## O que está promissor no Market Clock

```text
EXTREME_FINISH >=.850 -> nonlinear exhaustion/persistence state candidate
120m -> most stable cumulative comparison anchor
60-90m -> candidate transition block, not rule
MON_FRI + EXTREME_FINISH -> new post-hoc exhaustion candidate
```

## O que foi rejeitado nesta árvore

```text
continuous TerminalExtreme exhaustion model
continuous D1 exhaustion model
Terminal x D1 linear interaction
MIDWEEK higher volatility
MIDWEEK more EXTREME_FINISH
MIDWEEK amplifies EF reversal
MIDWEEK generally more directional/trending
EVER_NEGATIVE as useful discriminator
```

## NEXT QUESTION — FROZEN

Não otimizar weekdays individualmente agora.

Próximo teste recomendado:

1. congelar `EDGE_WEEK = MON_FRI` como hipótese exploratória derivada;
2. medir estabilidade temporal de `MON_FRI + EXTREME_FINISH` sem novos thresholds: chronological subperiods / rolling blocks + day bootstrap;
3. testar explicitamente o efeito EF vs OTHER dentro de MON_FRI para `response120`, `negative_fraction`, `reversal_auc` e distribuição/tails;
4. somente se sobreviver, investigar Monday vs Friday separadamente como diagnóstico, marcado como post-hoc;
5. manter correção de multiple testing do Market Clock directional na fila;
6. depois associar fases a sessões/aberturas/fechamentos reais e DST.

---

# 47. 2026-08-12 — Temporal stability of MON_FRI + EXTREME_FINISH

## QUESTION

O candidato pós-hoc `MON_FRI + EXTREME_FINISH` é estável ao longo do tempo ou sua aparente força está concentrada em um regime específico?

## WHY

Os testes anteriores mostraram forte separação entre `EXTREME_FINISH` e `OTHER` dentro de Monday/Friday. Como essa hipótese nasceu após inspeção dos resultados, era necessário verificar estabilidade temporal antes de qualquer tentativa de detalhar Monday e Friday separadamente.

## FROZEN DEFINITION

```text
HIGH_VOL_MAIN = [09:05,12:30) BRT
phase_end observed = 12:25
EDGE_WEEK = Monday + Friday
EXTREME_FINISH = terminal_extreme >= .850
primary anchor = response120
path = M5 endpoints 5..180m
metrics = REV120, response120, negative_fraction, reversal_auc, min_response
```

Nenhum threshold foi recalibrado. Monday e Friday permaneceram agrupados.

## DATA

Base M5 atualizada até 2026-08-12.

```text
HIGH_VOL_MAIN phase days = 364
MON_FRI phase days = 145
MON_FRI EXTREME_FINISH = 46
MON_FRI OTHER = 99
```

Os 145 dias MON_FRI foram ordenados cronologicamente e divididos em quatro blocos aproximadamente iguais, sem escolher datas por resultado.

## RESULTS — CHRONOLOGICAL QUARTERS

### Q1 — 2025-03-17 a 2025-07-25

```text
Days=37 | EF=10 | OTHER=27
REV120       EF 50.0%   OTHER 48.15%
Resp120 med  EF -.009   OTHER +.005
NegFrac med  EF .403    OTHER .417
AUC med      EF .049    OTHER .027
MinResp med  EF -.200   OTHER -.177
```

Bootstrap expected contrast:

```text
P(EF more REV120)      53.75%
P(EF higher NegFrac)   52.01%
P(EF higher AUC)       64.09%
P(EF deeper min)       62.88%
```

Conclusão: assinatura praticamente ausente no primeiro quarto.

### Q2 — 2025-07-28 a 2025-11-28

```text
Days=36 | EF=17 | OTHER=19
REV120       EF 64.71%  OTHER 36.84%
Resp120 med  EF -.041   OTHER +.090
NegFrac med  EF .556    OTHER .333
AUC med      EF .049    OTHER .025
MinResp med  EF -.158   OTHER -.115
```

Bootstrap:

```text
P(EF more REV120)      95.56%
P(EF higher NegFrac)   93.69%
P(EF higher AUC)       52.82%
P(EF deeper min)       44.46%
```

Conclusão: aparece forte assinatura binária/persistência, porém depth/AUC ainda fracos.

### Q3 — 2025-12-01 a 2026-04-06

```text
Days=36 | EF=12 | OTHER=24
REV120       EF 75.00%  OTHER 33.33%
Resp120 med  EF -.113   OTHER +.046
NegFrac med  EF .861    OTHER .306
AUC med      EF .099    OTHER .016
MinResp med  EF -.292   OTHER -.122
```

Bootstrap:

```text
P(EF more REV120)      99.08%
P(EF higher NegFrac)   99.60%
P(EF higher AUC)       99.77%
P(EF deeper min)       97.82%
```

Conclusão: este é o regime em que a assinatura aparece de forma mais completa e forte.

### Q4 — 2026-04-10 a 2026-08-10

```text
Days=36 | EF=7 | OTHER=29
REV120       EF 57.14%  OTHER 65.52%
Resp120 med  EF -.089   OTHER -.084
NegFrac med  EF .861    OTHER .528
AUC med      EF .156    OTHER .076
MinResp med  EF -.404   OTHER -.263
```

Bootstrap:

```text
P(EF more REV120)      33.79%
P(EF higher NegFrac)   58.21%
P(EF higher AUC)       86.80%
P(EF deeper min)       75.40%
```

Q4 tem apenas 7 observações EF; portanto não é apropriado concluir por frequência binária. O ponto importante é que a assinatura de **persistência/profundidade** continua visível nas medianas mesmo quando a taxa REV120 não separa.

## INTERPRETATION

O teste rejeita a interpretação simples:

```text
MON_FRI + EXTREME_FINISH
-> universal binary reversal rule
```

A força é claramente regime-dependent. Q1 não mostra efeito; Q2/Q3 mostram forte separação; Q4 perde a vantagem binária de REV120.

Entretanto Q4 preserva a anatomia que já vinha aparecendo:

```text
NegativeFraction median: .861 vs .528
ReversalAUC median:       .156 vs .076
Max reversal depth:      -.404 vs -.263
```

Isso reforça que `EXTREME_FINISH` deve ser tratado como **modificador da distribuição do path**, principalmente persistência/profundidade, e não como trigger automático de reversal.

## STATUS

```text
MON_FRI_EF_BINARY_REVERSAL = REGIME_DEPENDENT / NOT_STRUCTURAL
MON_FRI_EF_PERSISTENCE = PROMISING_REGIME_DEPENDENT_STATE
EXTREME_FINISH = STATE_MODIFIER_NOT_ENTRY_TRIGGER
```

## WHAT NOT TO REPEAT

- não separar Monday e Friday ainda para escolher o melhor;
- não otimizar `.850` por subperíodo;
- não escolher o quarter Q3 como regime operacional após vê-lo;
- não transformar mediana de persistence em directional entry rule;
- não tratar overlapping rolling windows como amostras independentes.

## NEXT QUESTION

A pendência metodológica mais importante do Track A passa a ser corrigir a descoberta direcional do Market Clock pelos 288 slots M5 para multiple testing/data snooping, usando um teste que preserve dependência intraday e controle family-wise error.

---

# 48. 2026-08-12 — Research Program Consolidation / DNA Tracks

## WHY

A pesquisa começou a produzir várias hipóteses plausíveis ao mesmo tempo: Market Clock, sequências multi-day, confluência gráfica de Fibonacci em D1/W1/MN1 e estrutura em H4/H1/M15. Misturar essas ideias prematuramente aumentaria risco de overfit e destruiria a capacidade de identificar qual família realmente adiciona informação.

Por isso a investigação passa a ser organizada em trilhas isoladas.

## TRACK A — MARKET CLOCK / PHASE DNA — ACTIVE

```text
HIGH_VOL_MAIN [09:05,12:30)
EXTREME_FINISH
PhaseMaturity 90-150m
60-90m candidate transition block
PostHighVolExhaustionPersistence
Week-cycle interaction
Multiple-testing correction of 288 M5 slots
```

Objetivo: fechar a anatomia temporal antes de misturar nova estrutura técnica.

## TRACK B — MULTI-DAY DNA — PARKED

Perguntas futuras:

```text
DailySequenceLength
D1ExtremePersistence
RangeExpansionSequence
MultiDayEfficiency
state t-1 / t-2 / t-3 -> state t
next-session / next-day state distribution
```

A motivação é testar sequências de dias, e não weekdays isolados.

## TRACK C — MTF_GRAPHIC_FIB_CONFLUENCE — PARKED

Hipótese originada da leitura gráfica manual:

```text
D1 / W1 / MN1 active impulse
Fib targets / retracements
multiple timeframe target cluster
DistanceToFibCluster
FibClusterReached
FibClusterRejected
FibClusterBroken
```

A seleção dos swings deve primeiro ser formalizada para reproduzir causalmente o método gráfico; não assumir que o ZigZag automático atual escolhe os mesmos pontos.

## TRACK D — LOWER_TF_STRUCTURAL_CONFLUENCE — PARKED

Timeframes principais:

```text
H4
H1
M15
```

Hipótese: timeframes menores podem fornecer estado estrutural mais frequente e antecipado que D1/W1/MN1.

Features candidatas futuras:

```text
SwingDirection_H4/H1/M15
DistanceToNearestFib_H4/H1/M15
MTFStructuralAgreement
MTFTargetDispersion
expansion/compression
structure/breakout/sweep
phase efficiency
```

O Market Chronos atual já possui infraestrutura parcial de `mtf_alignment_score`, `mtf_bias` e alinhamento H4/H1/M15; isso é apenas ponto de partida, não validação desta nova hipótese.

## TRACK E — INTEGRATION — FUTURE

Somente depois de cada família ser estudada isoladamente:

```text
Clock
+ Z-score/stretch
+ MTF structure
+ Fib confluence
+ Week cycle
+ Multi-day sequence
```

A pergunta da integração não será “qual combinação fica mais bonita?”, mas:

```text
qual informação incremental cada família adiciona OOS?
```

Comparações futuras devem incluir baseline de cada família e ganho incremental, evitando simplesmente empilhar filtros.

## RESEARCH GOVERNANCE

Fluxo obrigatório para nova ideia:

```text
IDEA
 -> isolated question
 -> frozen definition on Train
 -> Validation
 -> exploratory Test
 -> temporal/regime stability
 -> incremental information
 -> frozen shadow
 -> integration
```

Uma variável não entra no Super Agent apenas por apresentar um resultado bonito em uma rodada.

## CURRENT PRIORITY

```text
1. Finish Track A methodological cleanup.
2. Multiple-testing correction for 288 M5 directional clock slots.
3. Consolidate Track A.
4. Open one parked DNA track at a time.
5. Preserve all failed hypotheses and regime-dependent findings in this document.
```

Status: `RESEARCH_PROGRAM_CONSOLIDATED`.

---

# 49. Current checkpoint — 2026-08-12 15:35 BRT

A descoberta mais importante até aqui não é um único horário ou indicador. É que o GOLD apresenta **mudanças de significado condicionadas ao estado**.

Exemplos já observados na pesquisa:

```text
D1 upper continuation != D1 extreme chase
EXTREME_FINISH != automatic reversal
EXTREME_FINISH effect changes by regime/week context
same terminal state can lead to continuation or exhaustion
path persistence may contain more information than binary reversal
```

Portanto o objetivo permanece construir um **Market State / DNA Model**, não uma coleção de regras IF/THEN.

Próxima execução congelada: `288-slot Market Clock multiple-testing correction`.

---

# 50. 2026-08-12 — 288-slot Market Clock multiple-testing correction

## QUESTION

Depois de procurar direção futura em praticamente todos os 288 slots M5 do relógio, algum horário pontual continua estatisticamente anormal quando corrigimos a seleção múltipla?

## WHY

Candidatos como `20:50 continuation` e `13:30 reversal` surgiram durante varredura ampla do relógio. Sem correção, algum slot pode parecer forte apenas porque muitas alternativas foram observadas.

## FROZEN DEFINITION

```text
primary horizon = 120m
response = current M5 direction * future 120m displacement / ATR
TRAIN discovers only
cluster = BRT day
wild bootstrap = one +/-1 sign for the entire intraday curve of each day
max-|t| statistic across all eligible clock slots
bootstrap reps = 10,000
minimum TRAIN coverage = 100 days
FWER alpha = .05
```

## RESULTS

```text
Theoretical slots = 288
Coverage eligible = 264
TRAIN clustered days = 257
FWER 5% critical |t| = 3.738
FWER 1% critical |t| = 4.156
```

Best TRAIN slot:

```text
06:50
n=211
Mean120ATR=-.7230
Median=-.5387
CONT=38.39%
t=-3.552
p_FWER=.0993
```

Nenhum slot sobreviveu `p_FWER <= .05`.

Legacy `20:50`:

```text
TRAIN Mean=+.8268 CONT=58.02% t=+2.351 p_FWER=.9940
VALIDATION Mean=-.1608 CONT=48.05%
TEST Mean=+.5257 CONT=50.67%
```

Legacy `13:30`:

```text
TRAIN Mean=-.1135 CONT=49.28% t=-.767 p_FWER=1.0000
VALIDATION Mean=+.1247 CONT=54.55%
TEST Mean=+.0916 CONT=48.61%
```

## INTERPRETATION

A ideia de `hora exata -> direção futura` não sobrevive ao controle da família inteira de slots. Os antigos candidatos pontuais devem ser tratados como resultados de descoberta exploratória sem evidência estrutural.

Isso **não invalida** `HIGH_VOL_MAIN [09:05,12:30)`, pois HIGH_VOL_MAIN é uma fase robusta de atividade/volatilidade, não um slot direcional exato.

## STATUS

```text
POINT_CLOCK_DIRECTIONAL_EDGE = REJECTED_AFTER_FWER
20_50_CONTINUATION = REJECTED_AS_STRUCTURAL_CLOCK_EDGE
13_30_REVERSAL = REJECTED_AS_STRUCTURAL_CLOCK_EDGE
HIGH_VOL_MAIN = UNAFFECTED / ROBUST_DESCRIPTIVE_PHASE
TRACK_A_METHOD_CLEANUP = CONSOLIDATED_CHECKPOINT
```

## WHAT NOT TO REPEAT

- não selecionar horários pontuais sem corrigir a família pesquisada;
- não ressuscitar 20:50/13:30 por memória visual;
- não confundir fase de volatilidade com direção determinística.

---

# 51. 2026-08-12 — Track D Experiment 1: simple H4/H1/M15 directional agreement

## QUESTION

H4, H1 e M15 totalmente alinhados (`FULL`) produzem maior persistência direcional que alinhamento parcial (`PARTIAL`)?

## FROZEN DEFINITION

```text
anchor = M5
parent directions = sign(close-open) do último candle fechado
H4/H1/M15 available only after parent close
FULL_UP = +1/+1/+1
FULL_DOWN = -1/-1/-1
PARTIAL = 2 of 3 in the same direction
response = consensus sign * future displacement / M5 ATR
horizons = 15/30/60/120m
no Clock, D1, Z, weekday, Fib or EXTREME_FINISH
```

Infraestrutura foi ampliada para `H4=240m` em `TF_MINUTES`.

## DATA

```text
M5  rows 99,999
M15 rows 50,000
H1  rows 20,000
H4  rows 10,000
```

## RESULTS — EVENT LEVEL 120m

```text
                 TRAIN    VALIDATION   TEST
FULL CONT        50.3%      48.1%      48.4%
PARTIAL CONT     50.2%      48.2%      49.9%
```

Logo `FULL > PARTIAL continuation` não aparece.

## RESULTS — DAY LEVEL 120m

```text
FULL median
TRAIN      -.125
VALIDATION -.214
TEST       -.347

FULL positive-day rate
TRAIN      47.47%
VALIDATION 45.74%
TEST       38.89%

PARTIAL median
TRAIN      +.039
VALIDATION -.093
TEST       +.025
```

A diferença entre event-level e day-level mostra forte dependência/correlação entre múltiplos M5 do mesmo estado no mesmo dia.

## UP/DOWN ASYMMETRY — EVENT LEVEL 120m

```text
FULL_UP CONT
TRAIN 53.37%
VAL   50.65%
TEST  44.44%

FULL_DOWN CONT
TRAIN 46.42%
VAL   44.84%
TEST  51.59%
```

## INTERPRETATION

`FULL` não significa automaticamente mais força de continuação. A assinatura day-level mais negativa é interessante, mas não pode ser tratada como edge sem entender persistência do estado, episódios e regime. UP/DOWN também não formam espelho estável.

## STATUS

```text
SIMPLE_FULL_ALIGNMENT_CONTINUATION = REJECTED
FULL_GREATER_THAN_PARTIAL = REJECTED
FULL_DAY_LEVEL_ANTI_CONTINUATION = PROMISING_STATE_DIAGNOSTIC_ONLY
UP_DOWN_SYMMETRY = REJECTED
```

## NEXT QUESTION

Transformar `FULL` em episódios e estudar o nascimento do estado, evitando contar dezenas de M5 correlacionados como eventos independentes.

---

# 52. 2026-08-12 — Track D Experiment 2: FULL alignment episode onset

## QUESTION

O primeiro M5 de um episódio `FULL_UP/FULL_DOWN` contém informação diferente dos candles posteriores do mesmo estado?

## INITIAL DEFINITION

O experimento agrupou sequências FULL e criou `FULL_ENTRY`; porém a primeira implementação resetava a definição na mudança de `brt_date`.

Portanto esse resultado é válido como **day-relative transition diagnostic**, mas não como nascimento estrutural puro de um episódio que pode atravessar meia-noite.

## RESULTS — COMBINED FULL 120m

```text
TRAIN      n=2962 Mean=+.0804 Med=+.0457 CONT=50.61%
VALIDATION n=1092 Mean=+.1237 Med=-.0913 CONT=47.99%
TEST       n=1069 Mean=-.0876 Med=-.0975 CONT=48.36%
```

O onset combinado não apresenta sinal estável.

## UP/DOWN 120m

```text
FULL_UP
TRAIN Med=+.2499 CONT=54.24%
VAL   Med=+.0597 CONT=51.28%
TEST  Med=-.5200 CONT=42.11%

FULL_DOWN
TRAIN Med=-.2978 CONT=46.32%
VAL   Med=-.3318 CONT=44.16%
TEST  Med=+.1776 CONT=53.37%
```

Há forte flip de regime entre lados.

## FIRST FULL EPISODE PER BRT DAY — DIAGNOSTIC

30m reversal rate:

```text
TRAIN      57.03%
VALIDATION 57.45%
TEST       55.56%
```

Esse padrão foi percebido após inspeção de 15/30/60/120m, portanto é apenas exploratório e não deve ser promovido.

## EPISODE DURATION — DESCRIPTIVE

```text
median = 3 M5 bars
Q75    = 6 bars
Q90    = 9-12 bars dependendo do split/lado
```

## INTERPRETATION

O nascimento `FULL` não é exhaustion/continuation geral. O resultado reforça que direção e regime importam e que precisamos de uma definição estrutural contínua sem reset diário.

## STATUS

```text
FULL_ENTRY_GENERAL_EDGE = REJECTED
EXP2_DAY_RESET_FULL_ENTRY = DAY_RELATIVE_DIAGNOSTIC_ONLY
FIRST_DAILY_FULL_15_30_PULLBACK = EXPLORATORY_POST_HOC
TRUE_STRUCTURAL_ONSET = REQUIRES_CORRECTED_EPISODE_DEFINITION
```

## NEXT QUESTION

Construir episódio FULL contínuo por M5 contíguo, sem reset de calendário, e testar idade causal do estado.

---

# 53. 2026-08-12 — Track D Experiment 3: true continuous FULL state age

## QUESTION

Depois de corrigir o reset diário, a idade causal de um estado FULL (`state_age_bars`) altera progressivamente sua distribuição futura?

## WHY

Se alinhamento completo representa maturidade do movimento, poderíamos observar uma transição aproximadamente monotônica entre FULL recém-nascido e FULL antigo. A variável precisa ser causal: apenas idade conhecida até o instante atual, nunca duração final do episódio.

## FROZEN DEFINITION

```text
true FULL episode continues only when consecutive M5 timestamps differ by exactly 5m and state remains identical
no midnight reset
AGE landmarks = 1,3,6,12 bars
primary horizon = 120m
15/30/60 = diagnostic only
no D1, Clock, Z, weekday, Fib or EXTREME_FINISH
```

## EPISODE DISTRIBUTION

```text
true episodes = 5,372
mean duration = 5.41 bars
median = 3 bars
Q75 = 6 bars
Q90 = 9 bars
max = 30 bars
```

A distribuição de duração é relativamente estável; episódios muito longos são uma minoria.

## COMBINED FULL — EVENT LEVEL 120m

```text
             AGE1       AGE3       AGE6       AGE12
TRAIN Med    +.0416     +.0108     +.0390     +.0622
TRAIN CONT   50.56%     50.10%     50.82%     51.38%

VAL Med      -.0856     +.0039     -.1300     -.3780
VAL CONT     48.12%     50.14%     48.42%     42.53%

TEST Med     -.1062     -.2337     -.1514     -.1757
TEST CONT    48.31%     47.00%     47.00%     47.13%
```

Não existe progressão monotônica comum aos três splits.

## DAY-LEVEL 120m

```text
             AGE1       AGE3       AGE6       AGE12
TRAIN Med    -.0027     +.0341     +.0360     +.1364
VAL Med      +.1816     +.0278     -.1244     -.2064
TEST Med     -.1896     -.2802     -.2510     -.1766
```

Novamente, a forma muda por regime.

## DAY BOOTSTRAP — OLDER AGE vs AGE1

Todos os principais CIs cruzam zero.

```text
TRAIN AGE12-AGE1 MeanDiff +.2694 CI95 [-.2470,+.7808]
VAL   AGE12-AGE1 MeanDiff -.1695 CI95 [-.8499,+.5380]
TEST  AGE12-AGE1 MeanDiff +.3915 CI95 [-.6223,+1.4468]
```

AGE6 também muda de sinal entre splits e não apresenta CI estável.

## TRUE ONSET UP/DOWN ASYMMETRY — AGE1 120m

```text
FULL_UP CONT
TRAIN 54.31%
VAL   51.20%
TEST  41.98%

FULL_DOWN CONT
TRAIN 46.15%
VAL   44.55%
TEST  53.39%
```

O flip é forte: a direção do FULL parece depender de contexto/regime maior, não possuir significado estrutural fixo sozinha.

## INTERPRETATION

A hipótese `FULL mais velho -> exhaustion progressivamente maior` é rejeitada como regra generalizável. `state_age_bars` é uma feature causal válida, mas nesta definição simples não carrega efeito monotônico estável.

A descoberta útil é negativa: não procurar AGE7/AGE9/AGE14 até achar um número bonito. O próximo passo deve mudar a representação e perguntar **como o FULL foi formado**, não por quanto tempo ele já existe.

## STATUS

```text
FULL_STATE_AGE_MONOTONIC_EXHAUSTION = REJECTED
STATE_AGE_BARS = VALID_CAUSAL_FEATURE_BUT_NO_GENERAL_EDGE
TRUE_ONSET_GENERAL_EDGE = NOT_CONFIRMED
FULL_UP_DOWN_MEANING = STRONGLY_REGIME_DEPENDENT
FINAL_EPISODE_DURATION = DESCRIPTIVE_ONLY / NEVER REALTIME FEATURE
```

## WHAT NOT TO REPEAT

- não otimizar idade depois de ver AGE1/3/6/12;
- não usar duração final do episódio como feature causal;
- não tratar milhares de episódios/M5 como dias independentes;
- não espelhar FULL_UP e FULL_DOWN;
- não combinar Clock/D1/Z/Fib antes de entender a formação estrutural isolada.

## NEXT QUESTION — FROZEN

`TRACK D — EXPERIMENT 4: FULL FORMATION PATH`.

Perguntar qual timeframe foi o último a entrar em acordo no nascimento verdadeiro do FULL:

```text
H4 + H1 já alinhados -> M15 joins
H4 + M15 já alinhados -> H1 joins
H1 + M15 já alinhados -> H4 joins
MULTI_PARENT_CHANGE -> vários pais mudam juntos
```

Usar true AGE1, apenas transições com M5 anterior contíguo para as quais a formação seja observável. `120m` continua horizonte primário. Last-aligner será primeiro estudado isoladamente; Clock/D1/Z/Fib continuam fora.

---

# 54. Parked hypothesis — D1 extreme activity x Market Clock

## ORIGIN

Observação visual a investigar depois: em dias que estão estabelecendo máxima/mínima diária durante a região de maior atividade, a volatilidade parece maior, possivelmente com menos fakeouts e comportamento de exhaustion diferente perto do fim da HIGH_VOL_MAIN.

## CAUSAL DEFINITION REQUIREMENT

Nunca usar `final D1 high/low` intraday. Estados futuros devem ser reconstruídos point-in-time:

```text
NewD1HighSoFar
NewD1LowSoFar
D1PositionSoFar
DailyRangeSoFar
DailyRangeExpansion
```

## FUTURE QUESTIONS

```text
D1 extreme activity -> HIGH_VOL_MAIN relative volatility?
D1 extreme activity -> directional efficiency/follow-through?
D1 extreme activity -> lower false-breakout/fakeout rate?
D1 extreme activity -> different terminal condition near 12:30?
D1 extreme activity -> different post-phase persistence/depth?
```

Status: `PARKED_UNTESTED_HYPOTHESIS`.

Não misturar com Track D antes de fechar a formação estrutural H4/H1/M15.

---

# 55. Current checkpoint — 2026-08-12 16:52 BRT

Track A teve a principal dívida metodológica de horários pontuais encerrada: nenhum directional slot sobreviveu ao whole-clock FWER, enquanto HIGH_VOL_MAIN permanece uma fase estrutural de volatilidade.

Track D começou isolado e já eliminou três simplificações:

```text
FULL H4/H1/M15 != continuation automática
FULL onset != exhaustion/continuation geral
FULL age != monotonic maturity/exhaustion edge
```

O indício central passa a ser que **a história de formação do estado e o regime em que ele ocorre** podem importar mais que o alinhamento estático ou sua idade.

Próxima execução congelada:

```text
TRACK D — EXPERIMENT 4
TRUE FULL FORMATION PATH / LAST ALIGNER
primary horizon = 120m
```

---

# 56. 2026-08-12 — Track D Experiment 4: true FULL formation path / last aligner

## QUESTION

Quando nasce um verdadeiro FULL H4/H1/M15, importa qual timeframe foi o último a entrar em acordo?

## FROZEN DEFINITION

```text
true FULL onset
M15_LAST
H1_LAST
H4_LAST
MULTI_PARENT
primary horizon = 120m
no Clock, D1, Z, Fib, weekday or EXTREME_FINISH
```

## DATA

```text
true formation events = 5,209
M15_LAST    = 3,687
H1_LAST     =   705
MULTI_PARENT=   675
H4_LAST     =   142
```

## RESULTS — 120m

```text
                 TRAIN Med/CONT      VAL Med/CONT        TEST Med/CONT
M15_LAST         +.0896 / 51.02%    -.1758 / 46.10%    -.0897 / 48.68%
H1_LAST          +.0557 / 51.00%    -.1376 / 49.21%    -.0461 / 48.53%
H4_LAST          -.3049 / 49.40%    -.1453 / 50.00%    +.1576 / 55.88%
MULTI_PARENT     -.0545 / 49.06%    +.1926 / 53.28%    -.2859 / 45.07%
```

A decomposição UP/DOWN reforçou forte regime flip. Exemplo `M15_LAST`:

```text
FULL_UP CONT:   TRAIN 54.80% / VAL 49.39% / TEST 40.91%
FULL_DOWN CONT: TRAIN 46.41% / VAL 42.34% / TEST 54.50%
```

A estrutura imediatamente anterior também não foi estável:

```text
PRE_MAJORITY_SAME Med120:
TRAIN +.0698 / VAL -.1758 / TEST -.0758

PRE_MAJORITY_OPPOSITE Med120:
TRAIN -.1704 / VAL +.2057 / TEST -.2619
```

## INTERPRETATION

A hierarquia de formação baseada apenas em qual parent mudou por último não carrega uma assinatura direcional generalizável. `M15_LAST` domina naturalmente a frequência de eventos; `H4_LAST` é raro e não deve receber peso especial por resultados isolados.

## STATUS

```text
LAST_ALIGNER_GENERAL_EDGE = REJECTED
PREVIOUS_MAJORITY_PATH = NOT_STABLE
UP_DOWN_ASYMMETRY = STRONGLY_REGIME_DEPENDENT
```

## WHAT NOT TO REPEAT

- não otimizar combinações last-aligner x horário/Z/Fib;
- não escolher H4_LAST por sample pequeno;
- não espelhar FULL_UP/FULL_DOWN.

## NEXT QUESTION

Trocar direção binária por qualidade estrutural dos candles pais, ainda isoladamente.

---

# 57. 2026-08-12 — Track D Experiment 5: MTF structural quality

## QUESTION

A qualidade dos candles H4/H1/M15 que formam o FULL contém informação que a direção close-open não contém?

## FROZEN DEFINITION

```text
BodyEfficiency = abs(close-open)/(high-low)
DirectionalClosePosition = close dentro do range orientado à direção do FULL
ParentQuality = BodyEfficiency * DirectionalClosePosition
MTFStructuralQuality = mean(H4,H1,M15)
TRAIN-only Q33/Q67
primary horizon = 120m
```

Thresholds congelados do TRAIN:

```text
Q33 = .285715
Q67 = .434484
```

## RESULTS — QUALITY BUCKETS 120m

```text
TRAIN
LOW  Med +.0439 CONT 50.85%
MID  Med +.0784 CONT 51.35%
HIGH Med -.0020 CONT 49.95%

VALIDATION
LOW  Med +.0608 CONT 51.79%
MID  Med -.4425 CONT 42.94%
HIGH Med -.1709 CONT 47.39%

TEST
LOW  Med -.0085 CONT 49.69%
MID  Med -.0856 CONT 48.20%
HIGH Med -.2652 CONT 47.45%
```

## CONTINUOUS RELATION

```text
Spearman MTFStructuralQuality x Response120
TRAIN      -.0163
VALIDATION -.0379
TEST       -.0212
```

Range expansion e quality dispersion também ficaram próximos de zero.

Matched-day HIGH-LOW:

```text
TRAIN      Mean -.0742 CI95 [-.5243,+.3922]
VALIDATION Mean -.0369 CI95 [-.6937,+.6540]
TEST       Mean +.0112 CI95 [-.7000,+.7216]
```

## INTERPRETATION

A aparência/qualidade do candle não adiciona informação geral estável. A mediana HIGH ficou pior que LOW nos três splits, mas o contraste same-day desaparece e não sustenta uma hipótese de exhaustion estrutural.

## STATUS

```text
MTF_STRUCTURAL_QUALITY_CONTINUATION = REJECTED
MTF_STRUCTURAL_QUALITY_EXHAUSTION = WEAK_DESCRIPTIVE_HINT_NOT_CONFIRMED
MTF_RANGE_EXPANSION_ALONE = NO_EDGE
MTF_QUALITY_DISPERSION_ALONE = NO_EDGE
CANDLE_DIRECTION_CONFLUENCE_BRANCH = CLOSED_AS_GENERAL_PREDICTOR
```

## NEXT QUESTION

Migrar de aparência dos candles para localização/topologia estrutural usando swings confirmados causalmente.

---

# 58. 2026-08-12 — Track D Experiment 6: confirmed swing target topology

## QUESTION

No nascimento verdadeiro do FULL, quantos dos últimos swing targets confirmados H4/H1/M15 ainda estão à frente do preço e isso altera a distribuição futura?

## FROZEN DEFINITION

```text
fractal = 2-left / 2-right
swing só existe após fechamento dos 2 candles à direita
FULL_UP target = último swing high confirmado
FULL_DOWN target = último swing low confirmado
TargetsAheadCount = 0/1/2/3
primary horizon = 120m
```

## DATA

```text
true FULL events = 5,209
all-3-target coverage = 100%
M15 confirmed highs/lows = 6,670 / 6,677
H1  confirmed highs/lows = 2,639 / 2,687
H4  confirmed highs/lows = 1,364 / 1,403
```

## RESULTS — 120m MEDIAN / CONT

```text
TRAIN
AHEAD0 +.4459 / 53.41%
AHEAD1 +.1658 / 52.47%
AHEAD2 -.1976 / 46.77%
AHEAD3 +.1473 / 52.03%

VALIDATION
AHEAD0 +.6153 / 57.32%
AHEAD1 -.0917 / 46.60%
AHEAD2 -.1215 / 47.27%
AHEAD3 -.3050 / 46.30%

TEST
AHEAD0 -.1913 / 44.12%
AHEAD1 -.0732 / 48.91%
AHEAD2 -.1358 / 48.25%
AHEAD3 -.0524 / 48.93%
```

Ordinal Spearman:

```text
TRAIN +.0055
VAL   -.0605
TEST  -.0040
```

Matched-day AHEAD3-AHEAD0:

```text
TRAIN      Mean +.4425 CI95 [-.4718,+1.3569]
VALIDATION Mean -.4069 CI95 [-1.7496,+.8250]
TEST       Mean +.5208 CI95 [-1.4357,+2.6037]
```

## INTERPRETATION

Não existe progressão 0->1->2->3 e nem relação contínua de distância aos targets. O nível estático/quantidade de targets não descreve o DNA isoladamente.

## STATUS

```text
STATIC_SWING_TARGET_TOPOLOGY = REJECTED
TARGETS_AHEAD_COUNT = NO_GENERAL_EDGE
STATIC_DISTANCE_TO_SWING_TARGET = NO_GENERAL_EDGE
```

## WHAT NOT TO REPEAT

- não procurar fractal 3/3,4/4,5/5 depois do resultado;
- não selecionar AHEAD bucket por split;
- não selecionar timeframe isolado após inspeção.

## NEXT QUESTION

Testar a dinâmica da primeira interação com o target, e não apenas sua presença/localização.

---

# 59. 2026-08-12 — Track D Experiment 7: first structural target interaction

## QUESTION

O primeiro contato com o target estrutural mais próximo diferencia `BREAK_CLOSE` de `SWEEP_REJECT` de forma generalizável?

## FROZEN DEFINITION

```text
nearest confirmed target ahead frozen at true FULL onset
contact window = 120m
onset candle excluded
BREAK_CLOSE = touch + close além do target na direção do FULL
SWEEP_REJECT = touch/overshoot + close de volta do lado anterior
outcome = 120m após interaction close
```

## DATA

```text
true FULL events = 5,209
target ahead eligible = 4,786 (91.88%)
touched within 120m = 2,588 (54.07%)
interaction rows = 2,588
unique interaction keys = 2,326
duplicate fraction = 10.12%
```

## RESULTS — EVENT LEVEL

```text
TRAIN
BREAK Med -.0295 CONT 49.37%
SWEEP Med -.0730 CONT 49.22%

VALIDATION
BREAK Med -.0744 CONT 48.91%
SWEEP Med -.4356 CONT 41.56%

TEST
BREAK Med -.5128 CONT 43.18%
SWEEP Med +.3551 CONT 52.40%
```

## MATCHED-DAY BREAK-SWEEP

```text
TRAIN      Mean -.1522 CI95 [-.6888,+.3932] P(BREAK>SWEEP)=29.36%
VALIDATION Mean +.7433 CI95 [-.0491,+1.5894] P(BREAK>SWEEP)=96.72%
TEST       Mean -.7981 CI95 [-1.6233,+.1133] P(BREAK>SWEEP)=4.10%
```

## INTERPRETATION

A assinatura troca de lado entre splits. Primeiro toque sozinho não é edge: `breakout=continuation` e `sweep=reversal` não são regras válidas. Cerca de 10% das linhas convergiram para a mesma interação estrutural; isso motivou deduplicação explícita no experimento seguinte.

## STATUS

```text
FIRST_TOUCH_BREAK_VS_SWEEP = REJECTED_AS_GENERAL_EDGE
BREAK_CLOSE = NOT_STANDALONE_CONTINUATION_STATE
SWEEP_REJECT = NOT_STANDALONE_REVERSAL_STATE
```

## NEXT QUESTION

Deduplicar interações reais e testar aceitação/recaptura 15m depois do primeiro contato.

---

# 60. 2026-08-12 — Track D Experiment 8: structural interaction acceptance / failure

## QUESTION

A sequência `first touch -> estado 15m depois` carrega informação que o primeiro toque sozinho não carregava?

## FROZEN DEFINITION

```text
T0 = primeiro contato deduplicado
confirmation = exatamente T0 + 15m
OUTSIDE_15 = close confirmado além do target na direção original do FULL
INSIDE_15 = close confirmado de volta do lado anterior
sequence states = BREAK_HOLD / FAILED_BREAK / SWEEP_HOLD / REBREAK
primary outcome = 120m após confirmation close
15m congelado antes do resultado
```

## DATA / COVERAGE

```text
true FULL events = 5,209
target-ahead eligible = 4,786 (91.88%)
raw interactions = 2,588
unique interactions = 2,310
removed duplicates = 278 (10.74%)
exact 15m confirmation = 2,281 / 2,310 (98.74%)
```

## PRIMARY — OUTSIDE_15 vs INSIDE_15

```text
TRAIN
OUTSIDE n=606 Mean +.2423 Med +.1534 CONT 52.48%
INSIDE  n=647 Mean +.2700 Med +.0646 CONT 50.23%

VALIDATION
OUTSIDE n=206 Mean +.2331 Med +.0844 CONT 50.49%
INSIDE  n=250 Mean -.3861 Med -.4978 CONT 44.80%

TEST
OUTSIDE n=199 Mean +.3955 Med +.1342 CONT 51.26%
INSIDE  n=248 Mean -.3511 Med -.6346 CONT 44.76%
```

A nível bruto, Validation/Test sugerem que permanecer fora do nível é melhor que retornar para dentro. Porém o contraste day-level não confirma estabilidade temporal.

## DAY-LEVEL

```text
TRAIN
OUTSIDE days=210 Mean +.0118 Med +.0151 POS 50.48%
INSIDE  days=215 Mean +.3330 Med -.0556 POS 49.77%

VALIDATION
OUTSIDE days=80 Mean +.0967 Med +.0646 POS 50.00%
INSIDE  days=78 Mean -.3411 Med -.1911 POS 39.74%

TEST
OUTSIDE days=71 Mean +.0732 Med -.2324 POS 46.48%
INSIDE  days=76 Mean -.5560 Med -.4745 POS 44.74%
```

## MATCHED-DAY OUTSIDE - INSIDE

```text
TRAIN
matched_days=187
Mean=-.4084
Median=-.4272
CI95 [-.8623,+.0416]
P(OUTSIDE>INSIDE)=3.92%

VALIDATION
matched_days=71
Mean=+.4000
Median=+.2113
CI95 [-.3434,+1.1853]
P(OUTSIDE>INSIDE)=85.09%

TEST
matched_days=62
Mean=+.7950
Median=+.4694
CI95 [-.1349,+1.8129]
P(OUTSIDE>INSIDE)=95.14%
```

O sinal do matched-day muda: TRAIN favorece INSIDE, enquanto Validation/Test favorecem OUTSIDE. Todos os CIs ainda cruzam zero.

## SEQUENCE STATES

```text
TRAIN
BREAK_HOLD   Med +.1079 CONT 52.17%
FAILED_BREAK Med +.3972 CONT 56.67%
SWEEP_HOLD   Med -.2383 CONT 47.14%
REBREAK      Med +.2507 CONT 53.12%

VALIDATION
BREAK_HOLD   Med +.1259 CONT 53.10%
FAILED_BREAK Med +.1779 CONT 54.95%
SWEEP_HOLD   Med -.7935 CONT 38.99%
REBREAK      Med -.4753 CONT 44.26%

TEST
BREAK_HOLD   Med -.1196 CONT 48.12%
FAILED_BREAK Med -.8185 CONT 39.36%
SWEEP_HOLD   Med -.1064 CONT 48.05%
REBREAK      Med +.9140 CONT 57.58%
```

Frozen contrasts:

```text
BREAK_HOLD > FAILED_BREAK
not supported in TRAIN/VAL; only TEST separates in expected direction.

REBREAK > SWEEP_HOLD
median ordering appears in all three splits, but Validation both are negative and event dependence/regime sensitivity remain material.
```

Transition frequencies were relatively stable:

```text
BREAK_CLOSE -> OUTSIDE_15: TRAIN 67.12% / VAL 62.25% / TEST 59.75%
SWEEP_REJECT -> INSIDE_15: TRAIN 68.42% / VAL 71.74% / TEST 69.40%
```

Continuous acceptance depth remained near zero correlation:

```text
Spearman acceptance_distance_atr x response120
TRAIN +.0224
VAL   +.0635
TEST  +.0342
```

## INTERPRETATION

O primeiro resultado realmente interessante desta subárvore é que **a dinâmica da transição contém mais estrutura que o primeiro toque**, mas ainda não existe um edge geral confirmado. Validation/Test apontam para `OUTSIDE_15 > INSIDE_15`, porém TRAIN apresenta o contraste day-level oposto; portanto não promover.

`REBREAK > SWEEP_HOLD` é o único contraste ordinal que aparece na mesma direção nas medianas dos três splits, mas nasceu dentro de uma família de quatro estados já inspecionada e ainda é exploratório/regime-sensitive. Deve ser tratado apenas como pista para a próxima representação sequencial, não como regra.

## STATUS

```text
OUTSIDE15_GENERAL_CONTINUATION = NOT_CONFIRMED / REGIME_DEPENDENT
INSIDE15_GENERAL_FAILURE = NOT_CONFIRMED / REGIME_DEPENDENT
BREAK_HOLD_VS_FAILED_BREAK = REJECTED_AS_GENERAL_RULE
REBREAK_VS_SWEEP_HOLD = PROMISING_SEQUENCE_HINT / EXPLORATORY_ONLY
CONTINUOUS_ACCEPTANCE_DEPTH = NO_GENERAL_EDGE
SINGLE_LEVEL_INTERACTION_BRANCH = NOT_PROMOTED
```

## WHAT NOT TO REPEAT

- não mudar 15m para 5/10/20/30m neste TEST;
- não selecionar target timeframe após inspeção;
- não transformar REBREAK em regra direcional;
- não ignorar day-level/matched-day em favor de event-level;
- manter deduplicação de interação real em todos os próximos testes.

## NEXT QUESTION — FROZEN

Encerrar a tentativa de extrair regra de um único nível e migrar para **sequência estrutural multi-step**:

```text
TRACK D — EXPERIMENT 9
SEQUENTIAL SWING CONSUMPTION / BOS / RECAPTURE STATE
```

Pergunta: o estado muda quando o preço consome um swing, aceita além dele e então enfrenta/consome o próximo swing? A unidade passa a ser uma sequência de eventos estruturais, não um único candle/nível.

---

# 61. Current checkpoint — 2026-08-12 18:25 BRT

Track D eliminou progressivamente explicações estáticas/simples:

```text
FULL agreement                  -> rejected as continuation edge
FULL onset                      -> rejected as general edge
FULL age                        -> rejected as monotonic maturity edge
last aligner                    -> rejected as general edge
parent candle quality           -> rejected
static swing-target topology    -> rejected
first break vs sweep            -> rejected
15m acceptance alone            -> regime dependent / not promoted
```

A evidência acumulada aponta para um DNA mais próximo de uma **máquina de estados e transições** do que de uma combinação fixa de indicadores:

```text
STATE
 -> STRUCTURAL LOCATION
 -> LEVEL INTERACTION
 -> ACCEPTANCE / RECAPTURE
 -> NEXT STRUCTURAL EVENT
 -> NEW STATE
```

Nenhuma descoberta desta árvore altera o runtime hard rules. `WARNING_ONLY_RESEARCH` permanece. O próximo experimento deve preservar H4/H1/M15 e swings causais, mas abandonar single-level slicing e estudar consumo sequencial/BOS/recapture.

---

# 62. 2026-08-12 — Track D Experiment 9: sequential swing consumption / BOS / recapture

## QUESTION

Depois de um `OUTSIDE_15` deduplicado, consumir o próximo swing estrutural (`ADVANCE_BOS`) ou recapturar o primeiro nível aceito (`RECAPTURE_L1`) produz estados futuros diferentes?

## WHY

Os Experimentos 7-8 mostraram que primeiro toque e aceitação de um único nível não eram suficientes. A hipótese evoluiu para uma sequência multi-step: nível aceito -> próximo nível ou recaptura.

## FROZEN DEFINITION

```text
origin = deduplicated OUTSIDE_15
L1 = first accepted structural target
L2 = nearest causally confirmed H4/H1/M15 swing still ahead at state_time
transition window = 120m
ADVANCE_BOS = close beyond L2 in original FULL direction
RECAPTURE_L1 = close back through L1
first competing event wins
primary outcome = response120 after transition close
fractal = 2-left / 2-right
no D1, Clock, Z, weekday, Fib or EXTREME_FINISH
```

## DATA / COVERAGE

```text
true FULL events = 5,209
L1 ahead eligible = 4,786 (91.88%)
raw first interactions = 2,588
unique first interactions = 2,310
exact +15m confirmations = 2,281
OUTSIDE_15 states = 1,091
L2 known and ahead = 1,014 / 1,091 (92.94%)
L2 distance median = .1239 M5 ATR
```

Important structural caveat:

```text
L2 source TF = M15 for all 1,014 states
```

Portanto o experimento não testou uma hierarquia real H4/H1/M15 no segundo target; ele testou progressão sequencial de swings locais M15 dentro do contexto FULL H4/H1/M15.

## TRANSITION INCIDENCE

```text
                 TRAIN      VALIDATION    TEST
ADVANCE_BOS      60.37%       59.80%      63.68%
RECAPTURE_L1     38.63%       37.25%      34.91%
CENSORED          1.00%        2.94%       1.42%
```

A incidência ~60/40 foi surpreendentemente estável entre períodos.

## EVENT-LEVEL RESPONSE120

```text
TRAIN
ADVANCE   n=316 Med +.2668 Mean +.4043 CONT 51.58%
RECAPTURE n=210 Med -.0186 Mean -.0001 CONT 49.05%

VALIDATION
ADVANCE   n=109 Med +.1367 Mean +.0388 CONT 51.38%
RECAPTURE n=70  Med -.4347 Mean -.4495 CONT 40.00%

TEST
ADVANCE   n=122 Med +.3867 Mean +.3008 CONT 52.46%
RECAPTURE n=73  Med +.1542 Mean +.5057 CONT 52.05%
```

As medianas favorecem ADVANCE nos três splits, mas no TEST a média é maior para RECAPTURE por tails.

## DAY-LEVEL / MATCHED-DAY

```text
TRAIN      ADV Med -.0800 / RECAP Med -.0086
VALIDATION ADV Med -.0221 / RECAP Med -.2822
TEST       ADV Med +.2712 / RECAP Med +.5895
```

Matched-day `ADVANCE - RECAPTURE`:

```text
TRAIN      n=103 Mean +.5267 Med +.5203 CI95 [-.3831,+1.4372]
VALIDATION n=32  Mean -.0042 Med +.0185 CI95 [-1.0910,+1.0899]
TEST       n=36  Mean +.1181 Med +.5519 CI95 [-1.2854,+1.4692]
```

Nenhum CI exclui zero; Validation é essencialmente neutra.

## LATENCY / DISTANCE

```text
ADVANCE_BOS median latency = 5m nos 3 splits
RECAPTURE_L1 median latency = 10m nos 3 splits
Spearman L2 distance x response120 = -.0448 / -.0984 / +.0881
```

## INTERPRETATION

A sequência estrutural apresenta uma anatomia mais estável que as regras de primeiro toque, principalmente na **incidência da próxima transição**, porém `ADVANCE_BOS > RECAPTURE_L1` não se sustenta como edge futuro day-level. A descoberta mais importante foi deslocar a pergunta de retorno futuro para probabilidade do próximo estado.

O colapso de L2 para M15 também muda a interpretação: a partir daqui esta subárvore deve ser tratada explicitamente como **local M15 structural transition process inside FULL context**, até que uma definição hierárquica diferente seja congelada.

## STATUS

```text
ADVANCE_BOS_GT_RECAPTURE_GENERAL_EDGE = NOT_CONFIRMED
EVENT_LEVEL_MEDIAN_ORDERING = PROMISING_DESCRIPTIVE_SEQUENCE_HINT
DAY_LEVEL_MATCHED_EFFECT = NOT_CONFIRMED
TRANSITION_INCIDENCE_60_40 = ROBUST_DESCRIPTIVE_PATTERN_BUT_GEOMETRY_CONFOUNDED
EXP9_MTF_NEXT_TARGET_HIERARCHY = NOT_TESTED_AS_INTENDED
L2_SOURCE = M15_ONLY
```

No runtime promotion.

## WHAT NOT TO REPEAT

- não otimizar a janela de 120m após ver o resultado;
- não escolher source path BREAK_HOLD/REBREAK para salvar o edge;
- não escolher lado FULL_UP/FULL_DOWN após inspeção;
- não chamar L2 de hierarquia MTF enquanto o nearest target colapsa para M15;
- não interpretar a incidência ~60/40 como drift antes de corrigir geometria das duas barreiras.

## NEXT QUESTION — FROZEN

`TRACK D — EXPERIMENT 10: STRUCTURAL CORRIDOR / COMPETING-RISK GEOMETRY`.

Perguntar se a incidência ~60/40 é simplesmente consequência da posição relativa do preço entre L1 e L2.

---

# 63. 2026-08-12 — Track D Experiment 10: structural corridor / competing-risk geometry

## QUESTION

A probabilidade de `ADVANCE_BOS` versus `RECAPTURE_L1` é explicada pela geometria causal do corredor entre L1 e L2, ou existe informação residual além da posição relativa entre as barreiras?

## WHY

Exp9 encontrou incidência de ADVANCE extremamente estável (~60-64%), mas L2 estava muito próximo e sempre em M15. Antes de interpretar isso como tendência estrutural, era necessário comparar com um null de first-passage baseado apenas nas distâncias às duas barreiras.

## FROZEN DEFINITION

No estado `OUTSIDE_15`:

```text
d_back = oriented ATR distance from state_close back to L1
d_forward = oriented ATR distance from state_close to L2
corridor_width = d_back + d_forward
corridor_position = d_back / corridor_width
p_geometry = corridor_position
```

`p_geometry` é um null geométrico simples de first-passage, não uma hipótese de que o GOLD seja um Brownian motion perfeito.

Target:

```text
ADVANCE_BOS = 1
RECAPTURE_L1 = 0
```

TRAIN-only calibration:

```text
logit P(ADVANCE) = b0 + b1 * logit(p_geometry)
```

Avaliação OOS por AUC, Brier, LogLoss, fixed bins e bootstrap por BRT day. Nenhum threshold foi recalibrado.

## DATA / CORRIDOR GEOMETRY

```text
valid corridors = 1,014 / 1,091 (92.94%)
L2 source = M15 em 1,014 / 1,014

d_back mean 1.1143 ATR / median .8778
d_forward mean .3646 ATR / median .1239
corridor_width mean 1.4789 / median 1.1651
corridor_position mean .7568 / median .8702
```

A geometria explica por que ADVANCE seria naturalmente mais provável: o estado normalmente já está muito mais distante de L1 do que de L2.

## PRIMARY — OBSERVED vs RAW GEOMETRY NULL

```text
TRAIN      n=592 days=207 Observed=60.98% Geometry=72.70% Residual=-11.72 pp
VALIDATION n=198 days=79  Observed=61.62% Geometry=73.81% Residual=-12.19 pp
TEST       n=209 days=72  Observed=64.59% Geometry=85.76% Residual=-21.17 pp
```

O null `P=CorridorPosition` sobrestima sistematicamente ADVANCE.

Day-cluster bootstrap do residual bruto:

```text
TRAIN MeanResidual=-10.11 pp CI95 [-14.98,-5.35] P(<0)=100.00%
VAL   MeanResidual=-10.53 pp CI95 [-18.15,-2.98] P(<0)=99.70%
TEST  MeanResidual=-24.56 pp CI95 [-32.43,-17.03] P(<0)=100.00%
```

Portanto a diferença não é ruído event-level: a propensão real de recapture é maior que o null geométrico simples em todos os splits.

## TRAIN-ONLY CALIBRATION

```text
intercept = -.112307
slope     = +.388604
ideal raw-geometry null = intercept 0 / slope 1
```

A slope muito abaixo de 1 comprime probabilidades extremas: a posição relativa importa, porém o processo real responde muito menos agressivamente à proximidade da fronteira do que o null linear de first-passage sugeriria.

## DISCRIMINATION

```text
AUC corridor_position
TRAIN      .6970
VALIDATION .6652
TEST       .6459
```

Como a calibração logística é transformação monotônica, AUC calibrado é idêntico. O ponto importante é a estabilidade OOS positiva da ordenação.

Spearman `corridor_position x ADVANCE`:

```text
TRAIN      +.3328
VALIDATION +.2784
TEST       +.2418
```

Isto é a primeira feature estrutural do Track D que mantém **discriminação probabilística clara da próxima transição** nos três períodos.

## PROBABILITY QUALITY

Brier score:

```text
                 TRAIN      VALIDATION    TEST
constant          .237945     .236547     .230009
raw geometry      .233511     .242524     .273146
TRAIN calibrated  .209354     .217867     .219689
```

Brier skill aproximado do modelo calibrado vs constant TRAIN-rate baseline:

```text
TRAIN      +12.0%
VALIDATION  +7.9%
TEST        +4.5%
```

O ganho diminui temporalmente, mas permanece positivo em Validation e Test. Raw geometry sem calibração fica pior que o constant baseline em Validation/Test.

LogLoss:

```text
                 TRAIN      VALIDATION    TEST
raw geometry      .753247     .771901     .916504
TRAIN calibrated  .607483     .627491     .631903
```

## FIXED CORRIDOR BINS

TRAIN apresenta progressão clara:

```text
0-.20    Obs 21.43% / Geom 10.34%
.20-.40  Obs 35.29% / Geom 30.06%
.40-.60  Obs 47.89% / Geom 49.93%
.60-.80  Obs 62.00% / Geom 70.10%
.80-1    Obs 72.56% / Geom 93.04%
```

Validation mantém a ordenação ampla, embora o bucket .40-.60 seja fraco:

```text
0-.20    30.77% n=13
.20-.40  41.67% n=12
.40-.60  33.33% n=27
.60-.80  68.89% n=45
+.80-1   72.28% n=101
```

TEST está fortemente concentrado no topo; buckets baixos são pequenos. Nos buckets com amostra útil:

```text
.40-.60  Obs 40.00% n=15
.60-.80  Obs 48.48% n=33
.80-1    Obs 70.51% n=156
```

Um padrão descritivo marcante é que o bucket `.80-1` fica em ~70-73% observed nos três splits, apesar do null geométrico esperar ~93-94%. Não transformar esse nível em threshold/regra após inspeção.

## AFTER TRAIN CALIBRATION — DAY CLUSTER

```text
TRAIN MeanResidual +.88 pp CI95 [-3.73,+5.46]
VAL   MeanResidual +2.18 pp CI95 [-5.36,+9.60]
TEST  MeanResidual -8.00 pp CI95 [-15.76,-.48]
```

A calibração TRAIN neutraliza bem Train/Validation, mas deixa residual negativo significativo no TEST. Portanto a mapping `geometry -> transition probability` não é perfeitamente estacionária.

## DIRECTION / WIDTH DIAGNOSTICS

O residual bruto é negativo nos dois lados em todos os splits:

```text
FULL_UP residual:   -7.87 / -9.11 / -18.20 pp
FULL_DOWN residual: -16.62 / -16.72 / -23.46 pp
```

Logo a falha do null não é apenas um lado do FULL.

`corridor_width` não mostra relação incremental consistente com residual:

```text
Spearman width x residual
TRAIN +.0311 / VAL -.0079 / TEST -.0810
```

## INTERPRETATION

O Exp10 muda materialmente o Track D.

1. A incidência ~60/40 do Exp9 é **parcialmente explicada pela geometria**: L2 geralmente está muito mais próximo que L1.
2. Entretanto o null simples `P(ADVANCE)=corridor_position` é fortemente sobreconfiante e é rejeitado em todos os splits; o mercado recaptura L1 mais frequentemente do que esse null preveria.
3. `CorridorPosition` ainda é uma feature probabilística real: AUC .697/.665/.646 e Spearman positivo nos três splits.
4. Uma calibração TRAIN-only comprime a geometria e melhora Brier sobre o baseline constante em Train/Validation/Test, embora o ganho caia de ~12% para ~4.5% e o TEST apresente residual negativo remanescente.
5. Portanto encontramos algo diferente de um directional edge: uma **state-transition probability feature**. O preço dentro de um corredor estrutural carrega informação sobre qual fronteira tende a ser atingida primeiro.
6. A calibração ainda sofre drift/regime change; não está pronta para runtime e muito menos para inferência de retorno financeiro.

## STATUS

```text
CORRIDOR_POSITION_TRANSITION_DISCRIMINATION = STRONG_OOS_RESEARCH_FEATURE
RAW_IDENTITY_GEOMETRY_NULL = REJECTED_AS_CALIBRATED_PROBABILITY_MODEL
RAW_GEOMETRY_RESIDUAL = CONSISTENT_NEGATIVE / RECAPTURE_PROPENSITY_VS_NULL
TRAIN_LOGISTIC_GEOMETRY_CALIBRATION = OOS_USEFUL_BUT_NOT_STATIONARY
POST_CALIBRATION_TEST_DRIFT = PRESENT
CORRIDOR_WIDTH_INCREMENTAL_SIGNAL = NOT_OBSERVED
FULL_SIDE_EXPLAINS_RAW_RESIDUAL = NO
L2_SOURCE = M15_ONLY
RUNTIME_PROMOTION = NONE
```

## WHAT CHANGED

Antes:

```text
STATE -> next swing or recapture looked ~60/40
```

Agora:

```text
STATE + STRUCTURAL CORRIDOR POSITION
    -> non-trivial probability of next boundary
    -> calibrated relationship is compressed vs neutral geometry
    -> mapping drifts over time
```

Esta é a primeira evidência forte no Track D de um componente do DNA que faz sentido como **probabilidade de transição de estado**, não como BUY/SELL.

## WHAT NOT TO REPEAT

- não usar `p_geometry` cru como probabilidade operacional;
- não criar threshold `.80` porque o top bucket parece bom;
- não refitar calibração em Validation/Test;
- não otimizar corridor bins;
- não usar corridor width como filtro depois do Spearman quase zero;
- não separar FULL_UP/FULL_DOWN para escolher o lado melhor;
- não adicionar Clock/D1/Z/Fib ainda para explicar o residual;
- não confundir AUC de transição com edge de retorno financeiro.

## NEXT QUESTION — FROZEN

`TRACK D — EXPERIMENT 11: CORRIDOR GEOMETRY + LOCAL ACCEPTANCE PRESSURE`.

Pergunta: a forma causal como o preço percorreu os 15 minutos entre o primeiro contato e `OUTSIDE_15` explica informação de transição incremental além de `CorridorPosition` e reduz o residual de calibração?

Feature primária congelada:

```text
AcceptancePressure15 =
    oriented net close displacement from contact close to state_close
    /
    sum(abs(M5 close-to-close moves)) over the fixed 15m acceptance path
```

Range natural aproximado `[-1,+1]`; nenhum threshold será criado.

Comparação congelada:

```text
BASE:
logit P(ADVANCE) = b0 + b1*logit(CorridorPosition)

EXTENDED:
logit P(ADVANCE) = b0 + b1*logit(CorridorPosition)
                 + b2*AcceptancePressure15
```

Fit somente TRAIN. Validation/Test avaliam incremento por AUC, Brier, LogLoss e day-cluster residual. `BREAK_HOLD` vs `REBREAK` permanece diagnóstico secundário, sem seleção.

---

# 64. Current checkpoint — 2026-08-12 19:13 BRT

Track D finalmente produziu uma feature probabilística estrutural que preserva sinal OOS:

```text
CorridorPosition -> P(next boundary = ADVANCE_BOS)
AUC .697 / .665 / .646
```

Mas a probabilidade não é a geometria crua; `P=position` é excessivamente extrema e sobrestima ADVANCE. A calibração TRAIN-only ajuda em Validation/Test, porém o TEST ainda mostra drift residual.

A investigação passa, portanto, de regras de direção para uma state machine probabilística:

```text
CURRENT STRUCTURAL STATE
    + CORRIDOR GEOMETRY
    + LOCAL PATH PRESSURE ?
        -> P(ADVANCE)
        -> P(RECAPTURE)
        -> NEXT STATE
```

Próxima execução congelada:

```text
TRACK D — EXPERIMENT 11
CORRIDOR GEOMETRY + LOCAL ACCEPTANCE PRESSURE
```

No runtime promotion. Fresh forward / nested validation continua obrigatório antes de qualquer uso operacional.

---

# 65. 2026-08-12 — Track D Experiment 11: corridor geometry + local acceptance pressure

## QUESTION

Depois de controlar `CorridorPosition`, a eficiência/direção do caminho causal nos 15 minutos entre o primeiro contato com L1 e o estado `OUTSIDE_15` adiciona informação sobre a próxima transição estrutural?

## WHY

O Exp10 encontrou discriminação probabilística robusta de `CorridorPosition`, mas deixou drift negativo de calibração no TEST. Antes de introduzir estados de outras trilhas, foi congelada uma única feature local de path para verificar se a forma como o preço chegou ao corredor explicava parte desse residual.

## FROZEN DEFINITION

```text
AcceptancePressure15 =
    oriented net close displacement from contact_close to state_close
    /
    sum(abs(M5 close-to-close moves)) over exactly 15m

BASE:
logit P(ADVANCE) = b0 + b1*logit(CorridorPosition)

EXTENDED:
logit P(ADVANCE) = b0 + b1*logit(CorridorPosition)
                 + b2*AcceptancePressure15

fit = TRAIN only
Validation/Test = evaluation only
```

Target e estrutura permanecem os mesmos do Exp10:

```text
ADVANCE_BOS = 1
RECAPTURE_L1 = 0
fractal = 2-left / 2-right
first-contact window = 120m
acceptance confirmation = exactly +15m
transition window = 120m
no D1, Clock, Z, Fib, weekday or EXTREME_FINISH
```

## DATA / COVERAGE

```text
true FULL events = 5,209
L1 eligible = 4,786
raw first interactions = 2,588
unique first interactions = 2,310
OUTSIDE_15 = 1,091
valid corridor states = 1,014
L2 source = M15 in 1,014 / 1,014
```

AcceptancePressure15 distribution:

```text
mean = +.4675
median = +.5023
Q25 = +.1627
Q75 = +.9240
```

The transition incidence is unchanged from Exp10:

```text
                 TRAIN      VALIDATION    TEST
ADVANCE_BOS      60.37%       59.80%      63.68%
RECAPTURE_L1     38.63%       37.25%      34.91%
CENSORED          1.00%        2.94%       1.42%
```

## TRAIN-ONLY COEFFICIENTS

```text
BASE
intercept = -.112307
geometry  = +.388604

EXTENDED
intercept = -.191876
geometry  = +.373503
pressure  = +.218588
```

O coeficiente TRAIN de pressure é positivo, porém seu tamanho isolado não é evidência de generalização.

## PRIMARY MODEL COMPARISON

```text
TRAIN
AUC      .6970 -> .6991   Delta +.0021
Brier    .209354 -> .208891   Delta -.000464
LogLoss  .607483 -> .606512   Delta -.000970

VALIDATION
AUC      .6652 -> .6746   Delta +.0094
Brier    .217867 -> .216961   Delta -.000907
LogLoss  .627491 -> .626138   Delta -.001353

TEST
AUC      .6459 -> .6450   Delta -.0009
Brier    .219689 -> .220326   Delta +.000638
LogLoss  .631903 -> .633555   Delta +.001652
```

A feature melhora levemente o event-weighted TRAIN/Validation, mas piora todas as métricas primárias de probabilidade no TEST.

## DAY-CLUSTER BRIER GAIN

Positive means EXTENDED better than BASE.

```text
TRAIN
MeanGain +.000560
CI95 [-.001420,+.002480]
P(extended better)=72.43%

VALIDATION
MeanGain -.000638
CI95 [-.003871,+.002614]
P(extended better)=34.82%

TEST
MeanGain -.000214
CI95 [-.003670,+.003079]
P(extended better)=45.19%
```

A diferença entre o pequeno ganho event-weighted em Validation e o ganho day-weighted negativo mostra que o aparente incremento é dependente da multiplicidade de eventos por dia e não é robusto como informação independente.

## PRESSURE x BASE RESIDUAL

```text
Spearman AcceptancePressure15 x base residual
TRAIN      -.0091
VALIDATION -.0096
TEST       -.1406
```

Não há relação incremental estável que corresponda ao coeficiente positivo estimado no TRAIN. Train/Validation são essencialmente zero e o TEST fica mais negativo.

## EXTENDED MODEL RESIDUAL

Day-cluster residual after extended model:

```text
TRAIN MeanResidual +.86 pp CI95 [-3.74,+5.44]
VAL   MeanResidual +2.46 pp CI95 [-5.16,+9.92]
TEST  MeanResidual -7.39 pp CI95 [-15.17,+.14]
```

O novo predictor não resolve materialmente o drift. No TEST o residual continua grande e negativo; o CI apenas toca zero pela borda superior.

## SOURCE PATH DIAGNOSTIC

```text
TRAIN
BREAK_HOLD Obs61.94% Base62.38%
REBREAK    Obs58.95% Base58.02%

VALIDATION
BREAK_HOLD Obs64.49% Base61.61%
REBREAK    Obs55.00% Base59.39%

TEST
BREAK_HOLD Obs65.22% Base69.92%
REBREAK    Obs63.38% Base67.84%
```

Não existe justificativa para selecionar BREAK_HOLD ou REBREAK após inspeção.

## INTERPRETATION

`AcceptancePressure15` é uma feature causal bem definida, mas **não adiciona informação probabilística generalizável além da geometria do corredor** nesta definição congelada.

A leve melhora no TRAIN e no event-level Validation não sobrevive ao TEST nem ao day-cluster Validation/Test. Portanto não há justificativa para alterar o path window ou procurar thresholds de pressure.

O achado reforça que:

```text
WHERE AM I? = CorridorPosition
```

continua mais informativo que a métrica simples de:

```text
HOW STRAIGHT DID I GET HERE? = AcceptancePressure15
```

O residual recente do modelo geométrico parece ser principalmente um problema de **calibration/concept drift** ou de um estado causal de ordem superior ainda não representado, e não de eficiência local dos 15 minutos pós-contato.

## STATUS

```text
ACCEPTANCE_PRESSURE15_INCREMENTAL_INFORMATION = REJECTED
GEOMETRY_BASE_TRANSITION_MODEL = PRESERVED_STRONG_RESEARCH_FEATURE
LOCAL_15M_PATH_EFFICIENCY = NO_GENERAL_INCREMENTAL_SIGNAL
EXTENDED_GEOMETRY_PRESSURE_MODEL = NOT_PROMOTED
TEST_CALIBRATION_DRIFT = PERSISTS
BREAK_HOLD_REBREAK_SOURCE_PATH = DIAGNOSTIC_ONLY
L2_SOURCE = M15_ONLY
RUNTIME_PROMOTION = NONE
```

## WHAT NOT TO REPEAT

- não criar thresholds de AcceptancePressure15;
- não mudar o path para 5/10/20/30m para tentar salvar a feature;
- não testar transformações polinomiais/nonlinear de pressure neste mesmo TEST;
- não selecionar BREAK_HOLD ou REBREAK;
- não adicionar D1/Clock/Z/Fib para resgatar o Exp11;
- não confundir pequena melhora event-weighted de Validation com ganho independente day-level.

## NEXT QUESTION — FROZEN

`TRACK D — EXPERIMENT 12: PREQUENTIAL CALIBRATION DRIFT / ADAPTIVE CORRIDOR MODEL`.

Pergunta: o drift observado no TEST é um processo de calibração temporal lenta que pode ser acompanhado causalmente usando somente resultados anteriores, sem introduzir novas features?

Modelos congelados:

```text
STATIC_TRAIN
    intercept + geometry slope congelados no TRAIN original

ADAPTIVE_INTERCEPT
    geometry slope congelada no TRAIN original
    intercept reestimado com todos os estados realizados até o BRT day anterior

ADAPTIVE_FULL
    intercept e geometry slope reestimados com todos os estados realizados até o BRT day anterior
```

Regras:

```text
prediction for a BRT day may use outcomes only through previous BRT day
same-day outcomes never enter model for that day
expanding history only; no rolling-window optimization
minimum historical sample = original TRAIN already available before Validation
primary evaluation = Validation and TEST
metrics = Brier, LogLoss, AUC, day-cluster scoring gain and residual
```

Interpretação congelada:

```text
if adaptive models improve STATIC in both VAL and TEST:
    calibration drift is at least partly slow/learnable

if intercept-only is enough:
    drift is mainly calibration-in-the-large/base-rate

if full adaptive is materially better than intercept-only:
    geometry sensitivity itself drifts

if neither improves reliably:
    remaining error points to omitted structural state rather than simple online recalibration
```

Nenhuma janela temporal será escolhida depois do resultado.

---

# 66. Current checkpoint — 2026-08-12 19:25 BRT

Track D status after Exp11:

```text
Static alignment/direction features      -> rejected
Static swing target topology             -> rejected
Single-touch behavior                    -> rejected
15m acceptance alone                     -> regime-dependent
Sequential next-boundary incidence       -> stable descriptive process
CorridorPosition                         -> strong OOS transition discrimination
Raw geometry probability                 -> overconfident / rejected
TRAIN logistic calibration               -> useful OOS but drifting
AcceptancePressure15 incremental          -> rejected
```

The research problem is now explicit:

```text
STRUCTURAL STATE
    + CORRIDOR POSITION
        -> stable ranking of next transition
        -> imperfect and drifting probability calibration
```

The next test will not add indicators. It will ask whether the calibration drift itself is causally trackable with expanding prequential recalibration.

No runtime promotion. Current TEST remains repeatedly inspected exploratory OOS; fresh forward/nested validation remains mandatory before operational use.

# END OF CURRENT CHECKPOINT
