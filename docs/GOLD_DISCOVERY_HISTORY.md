# GOLD Discovery History — TradingAgent

> Documento vivo de pesquisa. Objetivo: registrar **o que já foi testado, por que foi testado, como foi testado, o que funcionou, o que falhou e o que não deve ser repetido sem uma nova justificativa**.
>
> Este arquivo deve ser atualizado nas próximas rodadas de pesquisa, preservando o histórico antigo. Achados superados **não devem ser apagados**; devem ser marcados como `REJECTED`, `SUPERSEDED`, `REGIME_DEPENDENT`, `SHADOW_ONLY` ou `CONFIRMED_RESEARCH`.

---

# 0. Por que este arquivo existe

Ao longo da pesquisa do GOLD foram criados diversos testes rápidos em memória, muitos executados diretamente no PowerShell e colados no chat. Eles foram úteis porque permitiram testar hipóteses em segundos sem transformar cada hipótese em um novo script permanente.

O risco desse método é perder o raciocínio histórico: repetir testes, esquecer por que determinada hipótese foi rejeitada, reintroduzir thresholds antigos ou confundir uma descoberta exploratória com uma regra validada.

Este documento resolve esse problema.

## Regras de manutenção deste histórico

1. **Não apagar histórico.**
2. Quando uma hipótese for refutada, manter os números e marcar como rejeitada.
3. Quando uma hipótese evoluir, manter a definição antiga e registrar a nova.
4. Thresholds já inspecionados em TEST devem ser tratados como exploratórios, não como novo holdout puro.
5. Novas promoções exigem forward shadow congelado ou nested/walk-forward.
6. Custos, spread e slippage ainda não foram incorporados à maior parte destes estudos.
7. O objetivo é construir **estado de mercado**, não empilhar filtros sem entender causalidade ou dependência.
8. O arquivo de pesquisa principal continua sendo `tools/study_d1_mtf_filter_v2.py`; evitar criar versões v3/v4 sem necessidade.

---

# 1. Ambiente e base de dados

## Símbolo

`GOLD`

## Timeframes utilizados

- M5
- M15
- H1

## Research dataset ampliado

Coleta realizada com:

```text
M5  ~100.000 candles
M15 ~50.000 candles
H1  ~20.000 candles
```

Arquivos:

```text
data/market_chronos/candle_base/timeframes/GOLD_M5_candle_research.parquet
data/market_chronos/candle_base/timeframes/GOLD_M15_candle_research.parquet
data/market_chronos/candle_base/timeframes/GOLD_H1_candle_research.parquet
```

Cobertura M5 aproximada:

```text
2025-03-13 -> 2026-08-11
```

## Metodologia base

- D1 reconstruído **point-in-time**.
- D1 usa **broker-day MT5**.
- `D1Position = (Price - LowSoFar) / (HighSoFar - LowSoFar)`.
- Não usa High/Low final do dia.
- H1 e M15 somente ficam disponíveis após o fechamento do candle pai.
- Split cronológico 60/20/20.
- Métricas principais:
  - expectancy / mean return;
  - profit factor;
  - independent broker days;
  - win rate;
  - sample size;
  - MFE/MAE.
- Horizonte principal que emergiu nos estudos de mean reversion: **120 minutos**.

---

# 2. Baseline MTF

Baseline original:

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

Conclusão:

`BASELINE_MTF` sozinho não apresentava edge positivo no período de teste. Isto abriu espaço para estudar contexto D1, anti-edge, extremos, z-score e estado intradiário.

Status: `REFERENCE_BASELINE`.

---

# 3. D1 directional structure

## 3.1 D1 0.70-0.90 bullish + BUY alinhado

Hipótese:

```text
D1Position 0.70-0.90
+ daily_direction BULLISH
+ H1/M15/M5 BUY alinhados
```

OOS TEST 120m:

```text
n=358
dias=44
WR=56.70%
Mean=+4.1437
PF=1.6578
```

Interpretação:

A parte superior do candle diário, **antes do extremo >=0.90**, preserva continuation BUY quando o contexto diário e MTF estão alinhados.

Status: `CONFIRMED_RESEARCH / STRONG_DIRECTIONAL_CONTEXT`.

Uso atual:

- manter soft preference BUY;
- ainda não transformar em hard filter sem novo forward holdout.

---

## 3.2 D1 0.10-0.30 bearish + SELL alinhado

Hipótese inicial: seria o espelho inferior da zona bullish.

OOS TEST 120m:

```text
n=208
dias=41
WR=49.52%
Mean=-0.9630
PF=0.8664
```

Conclusão:

A simetria não existe.

```text
Bullish upper continuation != bearish lower continuation
```

A antiga preferência SELL nessa zona foi removida do runtime scoring.

Status: `REJECTED_AS_DIRECTIONAL_SELL_EDGE`.

Não repetir:

- não assumir que D1 0.10-0.30 é espelho de 0.70-0.90;
- não reintroduzir bônus SELL sem uma nova amostra independente.

---

# 4. D1 extremes: anti-edge e inversão

## 4.1 EXTREME HIGH >= 0.90 — BUY chase

Hipótese testada:

```text
D1 EXTREME_HIGH
+ BUY continuation/chase
```

OOS TEST 120m:

```text
n=355
dias=35
WR=41.69%
Mean=-3.9499
PF=0.6393
```

Este foi um dos achados mais claros da pesquisa.

Conclusão correta:

```text
D1 >= 0.90
-> AVOID BUY CHASE
```

Importante:

**Evitar BUY não significa automaticamente abrir SELL.**

A inversão exata dos timestamps para SELL ficou forte no TEST recente, porém não apresentou estabilidade histórica suficiente em TRAIN/VALIDATION.

Status:

- BUY chase: `STRONG_ANTI_EDGE_RULE_CANDIDATE`.
- inverse SELL: `REGIME_DEPENDENT / NOT_STRUCTURAL`.

Não repetir:

- não transformar `EXTREME_HIGH` automaticamente em SELL;
- manter a interpretação como anti-edge do BUY até nova confirmação.

---

## 4.2 EXTREME LOW <= 0.10 — SELL chase

Hipótese:

```text
D1 EXTREME_LOW
+ SELL continuation/chase
```

OOS TEST 120m:

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

Esta descoberta motivou o estudo separado de mean reversion no extremo inferior.

Status: `STRONG_ANTI_EDGE_RESEARCH`.

---

# 5. Anti-edge -> inverse-edge

Foi levantada a pergunta:

> Se uma condição é consistentemente ruim para BUY, o SELL nos mesmos timestamps seria bom?

Matematicamente, sem custos e em horizonte fixo:

```text
mean_inverse ~= -mean_original
PF_inverse ~= 1/PF_original
WR_inverse ~= 1-WR_original
```

Mas isto **não prova** edge estrutural porque:

- custos quebram a simetria;
- regime pode mudar;
- TEST positivo pode ser recente e não histórico.

Resultado prático:

- extreme high inverse SELL: bom no TEST, falhou estabilidade histórica;
- extreme low inverse BUY: mostrou comportamento mais consistente e levou ao estudo do z-score.

Status do conceito: `USEFUL_DISCOVERY_TOOL`, não regra por si só.

---

# 6. M5 Z-score no extremo inferior

## Definição

```text
window = 20 candles M5
z = (close - rolling_mean) / rolling_std_population
```

20 candles M5 ~= 100 minutos.

Hipótese:

```text
D1 EXTREME_LOW
+ H1 DOWN
+ M15 DOWN
+ M5 z <= -2
-> BUY mean reversion
```

## Resultado Z=-2.0

120m:

```text
TRAIN
n=195
WR=65.64%
Mean=+4.05
PF=2.02

VALIDATION
n=69
WR=62.32%
Mean=+9.31
PF=2.21

TEST
n=100
dias=29
WR=72.00%
Mean=+7.07
PF=2.87
```

Status: `STRONG_SHADOW_CANDIDATE`.

---

# 7. Z-score sensitivity

Foram testados vários thresholds para verificar se o resultado era apenas otimização em `-2.0`.

## Z=1.5

```text
LOW BUY
TRAIN PF=1.82
VALIDATION PF=1.17
TEST PF=1.78
```

## Z=2.0

```text
LOW BUY
TRAIN PF=2.02
VALIDATION PF=2.21
TEST PF=2.87
```

## Z=2.5

```text
LOW BUY
TRAIN PF=2.93
VALIDATION PF=1.49
TEST PF=7.25
```

## Z=3.0

Amostra muito pequena; não usar para conclusão.

Conclusão:

O fenômeno é melhor interpretado como uma **família de overextension / mean reversion**, não um threshold mágico em -2.0.

`-2.0` foi congelado como melhor equilíbrio atual entre qualidade e tamanho da amostra.

Não repetir:

- não continuar otimizando Z depois de inspecionar o mesmo TEST;
- próximos thresholds só devem ser explorados em nested/walk-forward ou forward shadow.

---

# 8. High-side Z-score SELL

Foi testado o espelho superior:

```text
D1 EXTREME_HIGH
+ H1 UP
+ M15 UP
+ z >= threshold
-> SELL mean reversion
```

Apesar do TEST recente parecer forte, a estabilidade histórica falhou.

Resumo de PF 120m:

```text
Z=1.5 HIGH SELL  train~0.84 / val~0.33 / test~1.97
Z=2.0 HIGH SELL  train~0.95 / val~0.27 / test~1.79
Z=2.5 HIGH SELL  train~0.83 / val~0.20 / test~1.34
```

Conclusão:

É provável que exista **regime flip recente**, não uma regra estrutural.

Status: `NOT_PROMOTED / REGIME_FLIP_EVIDENCE`.

---

# 9. Rejection variants

Foram adicionadas rejeições de candle:

```text
high rejection:
false_breakout_up OR bearish candle with upper_wick >= body

low rejection:
false_breakout_down OR bullish candle with lower_wick >= body
```

Alguns resultados apresentaram PFs gigantes, por exemplo lower rejection em determinados subsets, porém com `n` muito pequeno.

Conclusão:

- headline PF não é confiável com sample collapse;
- rejeição deve permanecer como feature experimental, não filtro obrigatório.

Status: `EXPERIMENTAL_SMALL_SAMPLE`.

---

# 10. First event per day

Pergunta:

> O edge acontece apenas no primeiro toque extremo do dia?

Resultado para LOW Z=-2, 120m:

```text
TRAIN first/day PF=1.29
VALIDATION first/day PF=0.82
TEST first/day PF=2.40
```

Conclusão:

Primeiro toque por dia **não explica** o edge completo.

Isso mostrou que eventos repetidos no mesmo dia carregam informação.

Status: `FIRST_TOUCH_ONLY_REJECTED`.

---

# 11. Event order / persistence

Foi contado o número ordinal de eventos extremos no mesmo dia.

Exemplos 120m:

```text
TRAIN
1st  PF~1.29
2nd  PF~1.30
3rd  PF~1.72
4th+ PF~7.16

VALIDATION
1st  PF~0.82
2nd  PF~1.01
3rd  PF~1.03
4th+ PF~10.66

TEST
1st  PF~2.40
2nd  PF~5.06
3rd  PF~6.66
4th+ PF~2.19
```

A persistência parecia melhorar o resultado, mas havia um problema metodológico:

**candles consecutivos podiam pertencer ao mesmo evento/episódio**, causando pseudo-repetição.

Status: `SUPERSEDED_BY_HYSTERESIS_EPISODES`.

---

# 12. Episode model sem histerese

Foi criada definição de episódio usando condição false -> true.

Resultados sugeriram que episódio #2 poderia ser interessante, porém threshold chatter e mudanças de filtros poderiam criar falsas reentradas.

Conclusão:

A definição simples de episódio era insuficiente.

Status: `SUPERSEDED`.

---

# 13. Hysteresis episode model

Definição congelada:

```text
ENTER episode: z <= -2.0
STAY inside: enquanto z <= -1.5
RESET only: z > -1.5
```

Objetivo:

Separar **episódios reais de stress** de múltiplos candles consecutivos na mesma extensão.

---

# 14. Second hysteresis episode + D1 extreme low

Hipótese:

```text
pure Z episode #2
+ D1 EXTREME_LOW
+ H1 DOWN
+ M15 DOWN
-> BUY mean reversion
```

Resultados 120m com contagem pós-09:

```text
TRAIN
n=14
dias=14
WR=71.43%
Mean=+4.76
PF=2.14

VALIDATION
n=4
dias=4
WR=75.00%
Mean=+2.85
PF=1.48

TEST
n=13
dias=13
WR=69.23%
Mean=+6.17
PF=3.32
```

Status: `PROMISING_SMALL_SAMPLE_SHADOW`.

---

# 15. Horizon study of second episode

For second hysteresis episode:

```text
TRAIN
30m  PF~0.97
60m  PF~1.14
90m  PF~1.82
120m PF~2.14
150m PF~3.12
180m PF~5.04

VALIDATION
120m PF~1.48

TEST
90m  PF~1.81
120m PF~3.32
150m PF~2.32
180m PF~2.24
```

Conclusão:

120m foi mantido como melhor horizonte de pesquisa porque:

- Train positivo;
- Validation positivo;
- Test positivo;
- Test não confirma crescimento monotônico até 180m.

Não selecionar 150/180 somente porque TRAIN apresentou PF maior.

---

# 16. Episode reset boundary test

Pergunta crítica:

> O episódio #2 é o segundo episódio do dia inteiro ou de uma fase específica?

Comparação:

```text
OP_09       31 eventos
OPEN_08      4 eventos
BROKER_DAY   0 eventos
```

Overlap:

```text
OP_09 vs OPEN_08
Jaccard ~2.94%
```

Conclusão:

O fenômeno **não é** o segundo episódio do broker-day.

Ele é explicitamente:

```text
POST-09 STRESS CYCLE
```

Status: `IMPORTANT_SESSION_RELATIVE_DISCOVERY`.

Feature futura sugerida:

`Post09StressCycle`.

---

# 17. Ordinal episode validation

Comparação EP1/EP2/EP3/EP4+ no contexto D1 extreme low + H1/M15 down.

## TRAIN 120m

```text
EP1   n=6   PF=0.88   Mean=-1.09   D1med=.012   Zmed=-2.45
EP2   n=14  PF=2.14   Mean=+4.76   D1med=.043   Zmed=-2.22
EP3   n=12  PF=0.86   Mean=-0.61
EP4+  n=15  PF=5.72   Mean=+6.56
```

## VALIDATION

```text
EP1  PF=1.98
EP2  PF=1.48
EP3  PF=2.66
EP4+ PF=3.49
```

## TEST

```text
EP1  PF=0.49
EP2  PF=3.32
EP3  PF=28.89 (n=5, frágil)
EP4+ PF=1.50
```

Ponto importante:

No TRAIN, EP1 era **mais profundo em D1 e mais extremo em Z** que EP2 e mesmo assim teve resultado pior.

Isso sugere que o ordinal do ciclo carrega informação além de D1 depth e Z magnitude.

Status EP2: `PROMISING_SEQUENCE_INFORMATION`.

---

# 18. Time-of-day exploration around EP2

EP2 mostrou concentração interessante em horários da manhã, especialmente 10:00-11:30 em alguns splits.

Porém validation não tinha amostra suficiente para transformar o horário em filtro.

Conclusão:

- horário pode ser feature;
- não usar `10:00-11:30` como regra obrigatória.

Status: `FEATURE_CANDIDATE_ONLY`.

---

# 19. Opening-flow hypothesis 08:00-09:00 -> 10:00-11:30

Hipótese observacional inicial:

- 08-09 tende a seguir fluxo anterior / abertura;
- 10-11:30 poderia devolver quando volatilidade não fosse forte;
- com volatilidade forte poderia continuar;
- possível efeito maior Tue/Wed/Thu.

Primeiro teste usando `HIGH / NOT_HIGH` por range da abertura mostrou comportamento instável entre splits.

Exemplo TUE_THU | NOT_HIGH:

```text
TRAIN SignedMean  -0.34
VAL   SignedMean  -2.68
TEST  SignedMean  +3.34
```

Conclusão:

Dia da semana + range bruto não explica sozinho o fenômeno.

Status: `SIMPLE_RULE_REJECTED`.

---

# 20. Weekday hypothesis

Tuesday / Wednesday / Thursday foram testados separadamente.

O comportamento mudou de split para split e entre os próprios dias.

Conclusão:

`weekday` pode permanecer como feature futura, porém:

```text
Tue/Wed/Thu standalone rule
```

não foi confirmado.

Status: `NOT_A_STANDALONE_RULE`.

---

# 21. 20:00-01:00 -> 08:00-09:00 opening echo

Hipótese:

```text
20:00-01:00 flow
-> 08:00-09:00 repeats direction
```

Direction SAME:

```text
TRAIN       54.72%
VALIDATION  61.84%
TEST        48.68%
```

Signed echo magnitude:

```text
TRAIN       +0.41
VALIDATION  +2.72
TEST        +0.46
```

Conclusão:

A direção binária não é estruturalmente estável acima de 50%, mas a magnitude assinada ficou positiva.

Possível interpretação:

A informação pode estar em **força/eficiência do fluxo**, não apenas em direção igual/diferente.

Status:

- binary echo rule: `NOT_CONFIRMED`;
- opening flow state: `FEATURE_CANDIDATE`.

---

# 22. Directional impulse 08:00-09:00

Foi criado conceito:

```text
STRONG IMPULSE
= high range percentile
+ high directional efficiency percentile
```

Thresholds exploratórios inicialmente 67% / 67%, point-in-time.

Resultado ECHO + STRONG para resposta 10-11:30:

```text
TRAIN       CONT 57.14%, median +0.54
VALIDATION  CONT 58.33%, median +5.95, mean negativa por tails
TEST        CONT 66.67%, median +7.05
```

Interessante, porém amostra pequena.

ECHO + NON_STRONG mostrou reversão em Validation/Test, mas não Train.

Conclusão:

- range sozinho é insuficiente;
- `DirectionalEfficiency` é feature importante;
- potencial tail risk em dias de reversão violenta;
- ainda não promover.

Status: `PROMISING_STATE_FEATURE / SMALL_SAMPLE`.

---

# 23. 09:00-10:00 transition/rest phase

Foi testada a ideia de que após 08-09 ocorre descanso antes da resolução 10-11:30.

Movimentos foram normalizados pelo range 08-09.

ECHO + STRONG, mediana 09-10:

```text
TRAIN       -0.35
VALIDATION  -0.04
TEST        -0.20
```

Depois 10-11:30 mediana:

```text
TRAIN       +0.03
VALIDATION  +0.19
TEST        +0.22
```

Interpretação possível:

```text
strong opening echo
-> partial rest/pullback 09-10
-> later continuation/resolution
```

Porém não foi transformado em regra, pois horários ainda eram escolhidos manualmente.

Status: `DESCRIPTIVE_TRANSITION_HYPOTHESIS`.

---

# 24. Mudança metodológica: descobrir horários pelos dados

A pesquisa deixou de impor janelas como 08-09, 09-10 e 10-11:30 e passou a varrer as 288 posições M5 das 24h.

Medidas por horário:

- volatilidade relativa;
- directional efficiency;
- continuation 60m;
- continuation 120m;
- probability of continuation.

Change points foram descobertos **somente no TRAIN**; Validation e Test serviram para alignment.

Primeiro detector também revelou um problema:

- gaps de feed / fechamento-reabertura podem gerar change points artificiais;
- warnings `Mean of empty slice` ocorreram em horários sem cobertura.

Por isso a etapa seguinte incluiu filtro de cobertura e zonas contínuas.

Status do detector inicial: `SUPERSEDED_BY_COVERAGE_AWARE_ZONE_DISCOVERY`.

---

# 25. Data-driven Market Clock — primeiras descobertas

## Volatility clock

Picos estáveis encontrados:

```text
09:30
10:05
10:35-10:45
11:05-11:10
11:20-11:40
```

O núcleo mais forte apareceu em torno de 10:35-10:45.

## Continuation candidate

~20:50 apresentou sinal positivo nos três splits no estudo pontual inicial.

## Reversal candidate

~13:30 apresentou cont120 negativo nos três splits no estudo pontual inicial.

Estes horários foram posteriormente avaliados como zonas e por bootstrap de broker-day.

---

# 26. Stable intraday zones

Após filtro de cobertura e agrupamento de slots M5 consecutivos:

## High-volatility zones

```text
04:05-04:15
09:05-12:30
21:05-21:15
22:05-22:25
22:35-22:45
```

A zona principal foi claramente:

```text
09:05-12:30 BRT
```

Perfil mediano:

```text
TRAIN ~1.47
VAL   ~1.42
TEST  ~1.41
```

## Continuation zones 120m

```text
00:00-00:10
20:10-20:20
22:00-22:10
23:35-24:00
```

## Reversal zones 120m

Entre outras:

```text
06:20-07:15
07:25-08:00
12:55-13:45
```

Essas zonas foram então levadas ao bootstrap de dia independente.

---

# 27. Day-cluster bootstrap das zonas

Cada broker-day contribuiu com **uma observação por zona**.

10.000 bootstrap reps.

## NIGHT_20

```text
TRAIN days=212 Mean=+0.110 Med=-0.031 CI95[-0.053,+0.272] P(>0)=91.10%
VAL   days=76  Mean=+0.025 Med=+0.043 CI95[-0.196,+0.238] P(>0)=58.81%
TEST  days=76  Mean=+0.252 Med=+0.118 CI95[-0.140,+0.649] P(>0)=89.55%
```

Status: `MIXED / NOT_PROMOTED`.

## NIGHT_22

```text
TRAIN Mean=-0.145 CI95[-0.293,-0.006] P(>0)=2.04%
VAL   mixed
TEST  mixed
```

Status: `REJECTED_AS_STABLE_CONTINUATION`.

## NIGHT_2335

```text
TRAIN CI crosses zero
VAL   CI positive
TEST  near-positive but CI crosses zero slightly
```

Status: `PROMISING_LATER_REGIME / EXPLORATORY`.

## PRE_MORNING_REV 06:20-08:00

```text
TRAIN P(<0)=99.82%
VAL   P(<0)=95.88%
TEST  P(<0)=49.63%
```

Status: `FAILED_OOS_STABILITY`.

Important lesson: do not trust a visually strong Train/Validation pattern when TEST becomes neutral.

## HIGH_VOL_MAIN 09:05-12:30

```text
TRAIN
days=212
Mean=1.587
Med=1.530
CI95[1.542,1.634]
P(>1)=100%

VALIDATION
days=77
Mean=1.513
Med=1.426
CI95[1.425,1.606]
P(>1)=100%

TEST
days=76
Mean=1.546
Med=1.508
CI95[1.481,1.613]
P(>1)=100%
```

Este é o achado de relógio mais robusto até agora.

Conclusão:

```text
09:05-12:30 BRT = STRUCTURAL HIGH-VOLATILITY PHASE
```

Não é directional edge. É um **estado de mercado**.

Status: `ROBUST_DESCRIPTIVE_PHASE`.

## POST_VOL_REV 12:55-13:45

```text
TRAIN Mean=-0.017 Med=-0.113 P(<0)=65.70%
VAL   Mean=-0.024 Med=-0.106 P(<0)=62.68%
TEST  Mean=-0.007 Med=-0.085 P(<0)=52.40%
```

A mediana negativa é curiosa, mas a média/bootstrap não confirma edge.

Status: `DESCRIPTIVE_HYPOTHESIS_ONLY`.

---

# 28. Decomposição da HIGH_VOL_MAIN — latest study

Objetivo:

Descobrir por que `09:05-12:30` produz continuação em alguns dias e reversão em outros.

A fase foi caracterizada por:

- `impulse`;
- `efficiency`;
- `terminal_extreme`;
- composites `STRONG_DIRECTIONAL` e `EXTREME_FINISH`.

Thresholds foram definidos **somente no TRAIN**.

## Train-only thresholds

```text
impulse          Q33=0.326  Q67=0.783
efficiency       Q33=0.338  Q67=0.614
terminal_extreme Q33=0.669  Q67=0.850
```

---

## 28.1 Baseline da fase

### TRAIN

```text
n=210
120m continuation=50.0%
Mean=+0.028
Median~0
```

### VALIDATION

```text
n=77
120m continuation=50.6%
Mean~0
Median=+0.003
```

### TEST

```text
n=73
120m continuation=42.5%
reversal=57.5%
Mean=-0.073
Median=-0.041
```

Interpretação:

A fase como um todo está ficando mais reversiva no período recente, mas não é uma regra estrutural de reversão em todo histórico.

Status: `POSSIBLE_REGIME_DRIFT`.

---

## 28.2 IMPULSE HIGH

120m:

```text
TRAIN
n=64
CONT=43.8%
REV=56.2%
Mean=-0.004
Med=-0.040

VALIDATION
n=24
CONT=54.2%
REV=45.8%
Mean=+0.071
Med=+0.009

TEST
n=14
CONT=28.6%
REV=71.4%
Mean=-0.093
Med=-0.143
```

Conclusão:

High impulse sozinho **não é estável**. Validation contradiz Train/Test.

Status: `NOT_STRUCTURAL_ALONE`.

---

## 28.3 EFFICIENCY HIGH

120m:

```text
TRAIN
CONT=52.1%
REV=47.9%
Mean=+0.049
Med=+0.020

VALIDATION
CONT=33.3%
REV=66.7%
Mean=-0.156
Med=-0.033

TEST
CONT=35.3%
REV=64.7%
Mean=-0.083
Med=-0.077
```

Interpretação:

Há uma mudança de regime: movimentos eficientes passaram a apresentar mais reversão depois da fase em Validation/Test, mas Train não confirma.

Status: `REGIME_DEPENDENT`.

---

## 28.4 TERMINAL HIGH / EXTREME_FINISH

Esta é a decomposição mais interessante do estudo atual.

`terminal_extreme >= Q67`, ou seja, a fase termina muito perto do extremo de sua própria direção.

120m:

```text
TRAIN
n=71
CONT=45.1%
REV=54.9%
Mean=+0.015
Med=-0.026

VALIDATION
n=22
CONT=40.9%
REV=59.1%
Mean=-0.025
Med=-0.023

TEST
n=21
CONT=33.3%
REV=66.7%
Mean=-0.090
Med=-0.089
```

Pontos importantes:

1. reversal rate >50% nos três splits;
2. mediana negativa nos três splits;
3. intensidade de reversão aumenta no período recente;
4. TRAIN mean ainda levemente positiva, indicando tails de continuação grandes.

Hipótese emergente:

```text
HIGH_VOL_MAIN
+ finish near directional extreme
-> exhaustion risk in following 120m
```

Status atual: `PROMISING_EXHAUSTION_STATE / NEEDS_DAY_BOOTSTRAP`.

Não promover ainda.

---

## 28.5 STRONG_DIRECTIONAL

Definição:

```text
impulse HIGH
AND efficiency HIGH
```

120m:

```text
TRAIN
n=48
CONT=47.9%
REV=52.1%
Mean=+0.001
Med=-0.005

VALIDATION
n=15
CONT=40.0%
REV=60.0%
Mean=-0.059
Med=-0.014

TEST
n=10
CONT=30.0%
REV=70.0%
Mean=-0.096
Med=-0.135
```

A hipótese original era que movimento forte + eficiente pudesse continuar.

O resultado atual sugere o oposto no regime recente:

```text
strong directional high-vol phase
-> possible exhaustion / later reversal
```

Mas TRAIN é praticamente neutro.

Status: `PROMISING_RECENT_EXHAUSTION / NOT_STRUCTURAL_YET`.

---

## 28.6 STRONG_DIRECTIONAL UP vs DOWN

### TRAIN

```text
UP   n=31 REV=51.61% Mean~0
DOWN n=17 REV=52.94% Mean~0
```

### VALIDATION

```text
UP   n=9 REV=55.56%
DOWN n=6 REV=66.67%
```

### TEST

```text
UP   n=7 REV=85.71% Mean=-0.112 Med=-0.181
DOWN n=3 CONT=66.67% Mean=-0.060 Med=+0.105
```

Conclusão:

O subset UP no TEST chama atenção, mas `n=7` é pequeno e houve inspeção repetida do TEST.

Não usar como regra.

Status: `SMALL_SAMPLE_REGIME_SIGNAL`.

---

# 29. O que o latest study mudou na interpretação

A hipótese inicial era:

```text
high volatility + directional efficiency
-> continuation
```

O resultado **não confirmou isso estruturalmente**.

A nova hipótese mais plausível é:

```text
HIGH_VOL_MAIN 09:05-12:30
        |
        +-- se termina muito próximo do extremo da própria direção
        |      -> possível exhaustion / reversal risk
        |
        +-- strong directional
               -> também apresenta reversal crescente no regime recente
```

Portanto o próximo passo não é criar regra de continuação.

O candidato mais interessante do estudo atual é `TERMINAL_HIGH / EXTREME_FINISH`, seguido por `STRONG_DIRECTIONAL` como hipótese de exaustão recente.

---

# 30. Achados atuais por nível de confiança

## A. Fortes / usar como contexto de pesquisa

### A1. D1 bullish continuation 0.70-0.90

```text
BULLISH D1 + aligned BUY
-> continuation context
```

### A2. D1 EXTREME_HIGH

```text
avoid BUY chase
```

### A3. D1 EXTREME_LOW

```text
avoid SELL chase
```

### A4. LOW extreme Z-score family

```text
D1 EXTREME_LOW
+ H1 DOWN
+ M15 DOWN
+ Z20 <= -2
-> BUY mean-reversion shadow candidate
```

### A5. HIGH_VOL_MAIN

```text
09:05-12:30 BRT
-> structurally elevated volatility
```

---

## B. Promissores, mas ainda shadow/small sample

### B1. Post09StressCycle #2

```text
09:00 reset
EP1 z<=-2
recover >-1.5
EP2 z<=-2
+ D1 low/H1 down/M15 down
```

### B2. HIGH_VOL terminal extreme exhaustion

```text
09:05-12:30 phase
+ terminal_extreme HIGH
-> reversal risk after phase
```

### B3. Strong directional exhaustion

Mais forte no período recente, não estável em Train.

---

## C. Features úteis, ainda sem regra

- `OpeningFlowState`
- `DirectionalEfficiency`
- `ImpulseState`
- `TerminalExtreme`
- `MinutesFromPhaseChange`
- `weekday`
- `Post09StressCycle`
- `IntradayVolatilityPhase`

---

## D. Rejeitados / não repetir sem nova hipótese

- bearish D1 0.10-0.30 como espelho SELL;
- high-side z-score SELL como regra estrutural;
- rejection candle como filtro obrigatório;
- first extreme event/day como explicação suficiente;
- episódio sem histerese;
- segundo episódio contado desde 08:00 ou broker-day;
- Tue/Wed/Thu como regra standalone;
- opening echo binário 20-01 -> 08-09 como regra;
- NIGHT_22 continuation;
- PRE_MORNING_REV 06:20-08:00 como regra estrutural;
- POST_VOL_REV 12:55-13:45 como regra standalone;
- `high impulse = continuation` como regra simples;
- `high efficiency = continuation` como regra simples.

---

# 31. Anti-repeat checklist

Antes de criar um novo teste, conferir se ele já foi realizado:

```text
[ ] D1 upper bullish continuation?
[ ] D1 lower bearish continuation?
[ ] EXTREME_HIGH BUY chase?
[ ] EXTREME_LOW SELL chase?
[ ] exact side inversion?
[ ] Z sensitivity 1.5 / 2.0 / 2.5?
[ ] candle rejection?
[ ] first event per day?
[ ] event ordinal?
[ ] raw episodes?
[ ] hysteresis episodes?
[ ] 09:00 vs 08:00 vs broker-day reset?
[ ] EP1 / EP2 / EP3 / EP4+?
[ ] 08-09 opening flow?
[ ] Tue/Wed/Thu?
[ ] 20-01 -> 08-09 echo?
[ ] range + directional efficiency?
[ ] 09-10 transition?
[ ] automatic 24h clock discovery?
[ ] stable volatility/continuation/reversal zones?
[ ] broker-day bootstrap of clock zones?
[ ] HIGH_VOL phase impulse/efficiency/terminal decomposition?
```

---

# 32. Statistical caveat — very important

O antigo TEST foi consultado repetidamente durante:

- z-score threshold sensitivity;
- event order;
- episode definitions;
- session reset boundary;
- opening-flow hypotheses;
- Market Clock;
- high-vol phase decomposition.

Portanto:

```text
TEST atual = exploratory OOS
NOT pristine final holdout
```

Qualquer futura promoção deve usar pelo menos um dos seguintes:

1. forward shadow congelado;
2. nested walk-forward;
3. novo período temporal ainda não usado;
4. bootstrap/cluster robusto em broker-day;
5. custos/slippage antes de qualquer conclusão operacional.

---

# 33. Arquitetura conceitual que está emergindo

A pesquisa está deixando de ser uma coleção de filtros e começando a formar um **Market State Model**.

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

Depois desse estado estatístico estar congelado, associar externamente:

```text
market open
market close
overlap
maintenance/reopen
London / New York / futures sessions
DST-aware clocks
```

A associação econômica deve vir **depois** da descoberta estatística para evitar impor horários ao modelo.

---

# 34. Próximas perguntas congeladas

## Próxima pergunta 1 — terminal extreme bootstrap

Validar `TERMINAL_HIGH / EXTREME_FINISH` por broker-day, com thresholds já definidos no TRAIN:

```text
terminal_extreme Q67 = 0.850
```

Perguntas:

- mediana negativa é estrutural?
- média negativa aparece após controle de outliers?
- bootstrap P(response<0) é alto nos três splits?
- qual diferença versus baseline HIGH_VOL_MAIN?

## Próxima pergunta 2 — strong directional exhaustion

Bootstrap independente para:

```text
impulse >= 0.783
AND efficiency >= 0.614
```

Sem recalibrar thresholds.

## Próxima pergunta 3 — associação com D1

Somente se os estados acima sobreviverem:

```text
HIGH_VOL terminal extreme
x D1Position
```

Pergunta:

- extremo de fase + D1 extremo gera exaustão maior?
- terminal high em D1 0.70-0.90 comporta-se diferente de D1 >=0.90?

## Próxima pergunta 4 — associação com Post09StressCycle

Pergunta:

```text
HIGH_VOL phase state
+ Post09StressCycle #2
```

A sequência EP2 pode ser o marcador técnico de amadurecimento da fase intradiária?

## Próxima pergunta 5 — market-session association

Somente após congelar as fases estatísticas:

- mapear aberturas/fechamentos reais;
- timezone-aware;
- DST-aware;
- verificar coincidência temporal sem redefinir as fases.

---

# 35. Histórico de decisões do projeto

## Mantido

- `tools/study_d1_mtf_filter_v2.py` como estudo principal.
- Runtime permanece `WARNING_ONLY_RESEARCH`.
- D1 upper bullish BUY soft score permanece.
- EXTREME_HIGH BUY chase permanece penalizado.
- EXTREME_LOW SELL chase permanece penalizado.

## Corrigido

- antiga preferência bearish SELL 0.10-0.30 removida.

## Não promovido

- high-side inverse SELL;
- lower rejection high-PF small sample;
- weekdays;
- clock directional zones fracas;
- second episode como hard rule;
- high-vol terminal exhaustion até bootstrap dedicado.

---

# 36. Guideline para futuras atualizações deste arquivo

Cada nova rodada deve adicionar uma seção no final com:

```text
DATE / RUN
QUESTION
WHY WE ASKED IT
FROZEN DEFINITION
DATA / SPLIT
RESULTS
INTERPRETATION
STATUS
WHAT CHANGED
WHAT NOT TO REPEAT
NEXT QUESTION
```

Não editar números históricos antigos para fazê-los combinar com hipóteses novas.

Se houver erro metodológico, registrar:

```text
METHODOLOGY BUG
old result
why invalid
corrected result
impact on conclusion
```

---

# 37. Current research snapshot

Data do checkpoint:

```text
2026-08-11
```

Resumo em uma linha:

> GOLD apresenta forte assimetria D1, anti-edge claro nos extremos, uma família consistente de mean reversion no extremo inferior com Z-score, informação sequencial no segundo stress pós-09, e uma fase estrutural de alta volatilidade entre 09:05-12:30; a decomposição mais recente sugere que terminar essa fase muito próximo do extremo pode carregar risco de exaustão/reversão, mas ainda requer bootstrap específico antes de qualquer promoção.

---

# END OF CURRENT CHECKPOINT

Próximas rodadas devem ser adicionadas **abaixo deste ponto**, mantendo todo o histórico acima.
