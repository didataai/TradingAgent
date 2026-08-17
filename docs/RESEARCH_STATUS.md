# TradingAgent — Research Status

## Linha principal atual

1. **Active Structural Frontier / CorridorPosition** — núcleo estrutural Track-D.
2. **Shared competing-risk survival law** — `P(NO_EXIT / ADVANCE / RECAPTURE)` em 15/30/60/120m.
3. **Market Operability** — gate prospectivo `TRADEABLE / CAUTION / NO_TRADE`; não reescreve falhas históricas.
4. **Fresh-forward Exp27** — validação prospectiva congelada; scores permanecem selados até `>=60` dias BRT E `>=1500` dynamic structural states.
5. **Decision Layer** — camada separada entre previsão probabilística e ação econômica.

## Resultados estruturais preservados

- Exp40 `FULL_MULTI_HORIZON_CORRIDOR_DNA = PASS`.
- Exp41 shared competing-risk survival = FULL PASS histórico exploratório.
- Exp44 `ROBUST_POSITION_CORE = PASS`.
- Exp45 `ROBUST_WHICH_SIDE_LAW = PASS`.
- Exp47 `ROBUST_MINIMAL_CORRIDOR_EQUATION = PASS`.
- `CorridorPosition` permanece o coordenador robusto de **WHICH SIDE** dentro do universo histórico inspecionado.
- Nenhum componente universal adicional de `WHEN / WHETHER EXIT` sobreviveu aos Exp48–53; `HISTORICAL_TIMING_FEATURE_DISCOVERY_STOP = YES` permanece ativo.

## Decision Layer 01 — resultado congelado

Hipótese testada, sem feature nova e sem threshold:

```text
EDGE_PROB(H) = q_ADV(H) - CorridorPosition
STRUCTURAL_EDGE_ATR(H)
  = P(EXIT by H) * CorridorWidthATR * EDGE_PROB(H)
```

A geometria foi validada numericamente antes do score:

```text
CorridorPosition = d_back / (d_back + d_forward)
ADVANCE payoff   = +d_forward_ATR
RECAPTURE payoff = -d_back_ATR
```

Resultado formal histórico:

```text
DL01_FORMAL_METRIC_CELLS_PASS = 0/16
DL01_ENVIRONMENTS_FULL_PASS   = 0/8
ROBUST_STRUCTURAL_DECISION_EDGE = FAIL
DECISION_LAYER_01_FORMAL_STATUS = FAIL
```

Interpretação preservada:

- Exp47 continua válido como lei probabilística histórica; DL01 não o apaga.
- Melhor discriminação/proper score não implica automaticamente probabilidade econômica calibrada para comparar diretamente com o break-even geométrico.
- A correlação diagnóstico `StructuralEdge -> payoff` ficou negativa nos oito ambientes históricos; isso **não autoriza inverter o sinal** após ver o resultado.
- Não procurar `EDGE>x`, top-decile/quartile, horizonte favorito, direção, horário, sexta, notícia ou exclusão de ambiente para resgatar DL01.
- Custos/slippage não são adicionados para tentar salvar uma edge bruta que já falhou.

## Decision Calibration Shadow — hard-freeze antes do score prospectivo

Objetivo: testar se o `q_ADV` preservado do `POSITION_SURV` é um bom **ranking** mas necessita calibração absoluta antes de entrar numa equação econômica.

Calibrador único e congelado:

```text
q_raw = q_ADV_POSITION_SURV
q_cal = sigmoid(alpha + beta * logit(q_raw))

alpha = +0.012014589920
beta  = +1.094032434562
```

O freeze foi produzido em 2026-08-17 sem imprimir qualquer score histórico OOS ou fresh-forward.

Fingerprint TRAIN-only do calibrador:

```text
resolved EXIT state-horizon cells = 10152
ADVANCE / RECAPTURE               = 4179 / 5973
H15 / H30 / H60 / H120            = 1342 / 2085 / 2970 / 3755
optimizer iterations              = 7
fingerprint_sha256                = 940acfb845707487f6de889aa0cf77ec6a2b58d4e1f78761eef17fc4fffa8824
```

Contrato de fit preservado:

- `alpha` e `beta` foram ajustados **somente em TRAIN histórico**.
- Amostra de fit = realized EXIT `state x horizon` cells, pooled em `15/30/60/120m`, mesmo estimand `SIDE_STATE_HORIZON_WEIGHTED` do Exp45.
- Target = `ADVANCE=1`, `RECAPTURE=0`; `NO_EXIT` é excluído por definição da calibração condicional de lado.
- Sem horizon-specific coefficient, direção, era, interação, spline, isotonic, threshold ou nova feature.
- Validation/Test históricos não podem escolher calibrador, coeficientes, threshold ou interpretação formal futura.
- O fingerprint e os coeficientes devem ser reproduzidos exatamente antes de qualquer append prospectivo; mismatch => ABORT.

Prospective shadow:

```text
CALIBRATION_SHADOW_START = 2026-08-18 00:00:00 BRT
MATURITY = eligible BRT days >= 60
           AND resolved EXIT state-horizon cells >= 1000
```

Definição operacional congelada de `eligible BRT day`: data BRT pós-start que já contribuiu com pelo menos uma resolved EXIT state-horizon cell para o ledger prospectivo. É uma regra conservadora e verificável pelo próprio ledger.

O ledger é append-only, local e não versionado:

```text
data/market_chronos/decision/DECISION_calibration_shadow.csv
```

Ele preserva identidade da célula, previsão congelada e outcome necessário para o one-shot futuro. Antes da maturidade, seu conteúdo é tratado como **SEALED EVIDENCE**: não usar para inspeção de classe, score, payoff, edge, threshold, subset ou diagnóstico. O console pode mostrar somente contadores de readiness, primeira/última data e status de maturidade.

### Audit de implementação do combined build — 2026-08-17

A primeira execução manual do shadow passou integralmente os guards históricos e o fingerprint do calibrador, mas abortou ao iniciar o build `historical + live`: o runner embedded do EXP49 ainda continha um guard top-level de reprodução histórica que exigia `TEST=2096`, enquanto o universo combined já possuía `2187` rows no bucket TEST por incluir candles posteriores ao cutoff histórico.

Nenhum score de calibração foi aberto, nenhum resultado fresh-forward foi inspecionado e o start prospectivo permaneceu `2026-08-18 00:00 BRT`.

A correção preserva duas execuções separadas:

```text
HISTORICAL-ONLY
  -> todos os guards exatos continuam obrigatórios
  -> 9667 / 5612 / 1959 / 2096

HISTORICAL + LIVE
  -> mesma state/cell machine causal
  -> fixed historical count guards não podem exigir TEST=2096 após append fresh
```

No combined build são ignorados **somente** top-level guards que contêm explicitamente `REPRODUCTION ... FAILED`. Construção estrutural, mapping, denominadores, timestamps, campos, coeficientes e fingerprint continuam protegidos. A correção não altera feature, modelo, `alpha`, `beta`, fingerprint, start, maturidade ou contrato do one-shot.

One-shot após maturidade, sem retuning:

1. `q_cal` vs `q_raw` em fresh-forward EXIT cells: Brier + LogLoss, STATE_HORIZON_WEIGHTED, whole-BRT-day bootstrap.
2. Reavaliar a edge econômica gross usando `q_cal - CorridorPosition`, sem threshold e sem inversão pós-hoc.
3. Custos, slippage, sizing e política de execução permanecem downstream e só entram se a calibração/edge prospectiva sobreviver.

A falha do calibration shadow não pode ser resgatada com outro calibrador no mesmo shadow. Um modelo alternativo exigirá novo freeze e novo bloco prospectivo.

## Decision Replay 01 — política de execução histórica congelada antes do primeiro backtest

Objetivo: desenvolver a tradução prática `estrutura -> BUY / SELL / WAIT` por replay causal M5, sem esperar o fresh-forward para aprender mecânica de execução. Este replay é **engenharia histórica exploratória**: não substitui Exp27, não substitui o Calibration Shadow, não promove runtime e não transforma Historical Validation/Test repetidamente inspecionado em novo OOS formal.

### Universo e modelos

- Usar somente estados históricos `VALIDATION + TEST`; `TRAIN` não entra em métricas de trade porque foi usado para ajustar os modelos/calibrador.
- Reproduzir antes do replay todos os guards históricos Track-D e Exp41.
- Reproduzir exatamente o calibrador TRAIN-only congelado (`alpha`, `beta`, fingerprint) antes de simular trades.
- Usar o Operability v1 congelado com os mesmos thresholds TRAIN-only e regras de janela/Friday/shock; scheduled-event feed histórico fica **inativo**, pois eventos não podem ser retroativamente adicionados.
- O Operability histórico aqui é apenas uma regra fixa de participação para engenharia; não pode ser usado para reescrever falhas anteriores.

### Horizonte e sinal primário

A primeira política testa **somente H=60m**. Não executar 15/30/120 e depois escolher o melhor como rescue.

```text
q_raw_60 = P(ADVANCE | EXIT by 60m, POSITION_SURV)
q_cal_60 = frozen Platt(q_raw_60)

if OPERABILITY != TRADEABLE:
    WAIT
elif q_cal_60 > 0.50:
    STRUCTURAL_SIDE = ADVANCE
elif q_cal_60 < 0.50:
    STRUCTURAL_SIDE = RECAPTURE
else:
    WAIT
```

O limiar `0.50` é maioria condicional de lado, **não** o break-even geométrico rejeitado pelo DL01. Não procurar threshold alternativo após o resultado desta rodada.

Mapeamento estrutural para direção de trade:

```text
             FULL_UP     FULL_DOWN
ADVANCE      BUY         SELL
RECAPTURE    SELL        BUY
```

### Política de entrada e sobreposição

- No máximo **1 trade por episódio estrutural**.
- Dentro de cada episódio, considerar o primeiro estado causal que seja `TRADEABLE`, possua previsão válida e encontre entrada válida.
- Se já houver trade aberto, candidatos até o fechamento são ignorados; não há stacking/portfolio overlap.
- Entrada = `open` do próximo M5 estritamente contíguo após `state_time`; diferença obrigatória de 5 minutos.
- Se o próximo open já estiver fora do corredor fixo `[back, forward]`, não entrar (`ENTRY_OUTSIDE_CORRIDOR`).
- Boundaries são congeladas no estado que gerou o sinal e não trailing/recalculadas durante o trade.

### Target, stop e saída

Para `ADVANCE`, target = `forward` e stop = `back`. Para `RECAPTURE`, target = `back` e stop = `forward`. BUY/SELL apenas traduz a orientação do bias.

O replay de execução usa OHLC M5 para detectar toque intrabar:

- BUY: target se `high >= target`, stop se `low <= stop`.
- SELL: target se `low <= target`, stop se `high >= stop`.
- Se target e stop forem tocados no mesmo candle M5, assumir **STOP primeiro** (regra conservadora; sem dados intrabar não há ordem observável).
- Timeout = 60 minutos após a entrada; se nenhum boundary for tocado, fechar no `close` do último M5 disponível até o deadline.
- Gap/data discontinuity durante a janela do trade encerra a simulação como `DATA_GAP` e o trade não entra nas métricas primárias.

### Métricas congeladas

Primeiro replay = gross, sem spread/slippage/commission/swap. Custos serão camada separada se a política gross mostrar valor; não serão escolhidos para salvar resultado.

Reportar por `VALIDATION`, `TEST` e pooled `VALIDATION+TEST`:

- trades, BUY/SELL;
- TP / STOP / TIMEOUT / ambiguous-stop count;
- win rate (`PnL_R > 0`);
- gross profit factor em R;
- expectancy média/mediana em R;
- average win / average loss em R;
- cumulative R e max drawdown em R;
- payoff também em pontos e ATR quando disponível;
- contagem de episódios bloqueados por Operability, overlap, invalid entry e data gap.

`PnL_R` usa risco de entrada até stop como 1R. TP pode valer mais ou menos de 1R conforme a geometria real na entrada. TIMEOUT é marcado a mercado no close de timeout e normalizado pelo risco inicial.

### Anti-rescue

Depois do primeiro resultado não:

- trocar H=60 por outro horizonte para declarar sucesso;
- procurar `q_cal > x`;
- inverter sinal;
- remover direção, era, sexta, volatilidade ou ambiente ruim;
- escolher somente TP/STOP e apagar timeouts;
- permitir múltiplas entradas do mesmo episódio;
- alterar same-bar ambiguity depois de ver PnL;
- adicionar custos favoráveis ou stop/target alternativo para resgatar.

Se falhar, registrar FAIL da política específica; o resultado não apaga Exp47 nem o Calibration Shadow. Se mostrar valor, o próximo passo é um contrato separado para custos e depois uma implementação live/shadow do mesmo execution engine.

### Decision Replay 01 — resultado do primeiro backtest congelado

Todos os guards históricos, Exp41, calibrador TRAIN-only e Operability replay passaram antes das métricas de trade.

Universo:

```text
VALIDATION states = 1959
TEST states       = 2096
Episodes          = 416
Horizon           = 60m only
```

Resultado gross:

```text
VALIDATION
trades=84 | BUY=36 SELL=48 | TP=59 STOP=15 TIMEOUT=10 | AMBIG=2
win=73.81% | PF=1.0395 | E[R]=+0.00804 | medianR=+0.12556
avgWin=+0.28661R | avgLoss=-0.77700R
CumR=+0.67558 | MaxDD=6.52059R | sumPoints=+144.160 | meanPnL_ATR=+0.13414
GATE=PASS

TEST
trades=86 | BUY=54 SELL=32 | TP=60 STOP=20 TIMEOUT=6 | AMBIG=1
win=72.09% | PF=0.8141 | E[R]=-0.04719 | medianR=+0.13304
avgWin=+0.28666R | avgLoss=-0.90966R
CumR=-4.05868 | MaxDD=8.46487R | sumPoints=-57.630 | meanPnL_ATR=-0.03107
GATE=FAIL

VAL+TEST POOLED
trades=170 | BUY=90 SELL=80 | TP=119 STOP=35 TIMEOUT=16 | AMBIG=3
win=72.94% | PF=0.9131 | E[R]=-0.01990 | medianR=+0.13022
avgWin=+0.28663R | avgLoss=-0.84621R
CumR=-3.38310 | MaxDD=8.46487R | sumPoints=+86.530 | meanPnL_ATR=+0.05056
```

Execution audit:

```text
ENTRY_OUTSIDE_CORRIDOR = 1 episode / 1 state occurrence
INCOMPLETE_END         = 2 episodes / 13 state occurrences
INCOMPLETE_SPLIT       = 1 episode / 1 state occurrence
OPERABILITY_CAUTION    = 4 episodes / 8 state occurrences
OPERABILITY_NO_TRADE   = 260 episodes / 2343 state occurrences
OVERLAP                = 11 episodes / 45 state occurrences
TRADED_EPISODES        = 170
```

Formal result of the frozen execution policy:

```text
DECISION_REPLAY_01_VALIDATION_GATE = PASS
DECISION_REPLAY_01_TEST_GATE       = FAIL
DECISION_REPLAY_01_GROSS_STATUS    = FAIL
```

Interpretation preserved:

- The structural side signal produced a high hit rate, but the trade payoff distribution was unfavorable enough to remove the edge.
- Pooled average win was only `+0.28663R` versus average loss `-0.84621R`; the observed payoff therefore requires roughly a `74.7%` win rate to break even, above the realized `72.94%`.
- Validation was only marginally positive (`PF=1.0395`, `E[R]=+0.00804`) and Test reversed negative (`PF=0.8141`, `E[R]=-0.04719`).
- This is consistent with the distinction already exposed by DL01: **which-side discrimination is not the same thing as economic edge**.
- `q_cal vs 0.50` is therefore rejected as a universal execution decision rule for this target/stop geometry.
- The failure does not erase Exp47, does not open Exp27/Calibration scores, and does not authorize threshold, horizon, sign, subset or cost rescue.

Status after first replay:

```text
DECISION_REPLAY_01 = COMPLETE_FAIL
PRIMARY_HORIZON = 60m
SIGNAL_THRESHOLD = q_cal_60 vs 0.50
NO_HORIZON_THRESHOLD_SIGN_RESCUE = YES
EXP27 = UNTOUCHED / SCORES_SEALED
CALIBRATION_SHADOW = UNTOUCHED / SCORES_SEALED
RUNTIME_PROMOTION = NONE
```

## Governança permanente

```text
Exp27 = UNTOUCHED / SCORES SEALED
Historical timing feature discovery = CLOSED
Historical Validation/Test = repeatedly inspected / exploratory only
Runtime promotion = NONE
```

## Higiene do repositório

Preferir alterar arquivos existentes. Criar arquivo novo somente quando houver responsabilidade realmente nova.

Não versionar:

- `__pycache__` e `*.pyc`;
- logs e manifests de execução;
- parquets e planilhas regeneráveis;
- resultados locais de pesquisas exploratórias;
- snapshots de `research_staging`.

O `.gitignore` da raiz contém as regras canônicas.
