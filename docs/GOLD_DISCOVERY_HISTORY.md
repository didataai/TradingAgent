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
TEST                .597      .861
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

# END OF CURRENT CHECKPOINT

Próximas rodadas devem ser adicionadas abaixo deste ponto, preservando tudo acima.