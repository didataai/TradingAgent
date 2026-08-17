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

## Decision Calibration Shadow — congelado antes de score prospectivo

Objetivo: testar se o `q_ADV` preservado do `POSITION_SURV` é um bom **ranking** mas necessita calibração absoluta antes de entrar numa equação econômica.

Calibrador pré-declarado e único:

```text
q_raw = q_ADV_POSITION_SURV
q_cal = sigmoid(alpha + beta * logit(q_raw))
```

Contrato de fit:

- `alpha` e `beta` são ajustados **somente em TRAIN histórico**.
- Amostra de fit = realized EXIT `state x horizon` cells, pooled em `15/30/60/120m`, mesmo estimand `SIDE_STATE_HORIZON_WEIGHTED` do Exp45.
- Target = `ADVANCE=1`, `RECAPTURE=0`; `NO_EXIT` é excluído por definição da calibração condicional de lado.
- Sem horizon-specific coefficient, direção, era, interação, spline, isotonic, threshold ou nova feature.
- Validation/Test históricos não podem escolher calibrador, coeficientes, threshold ou interpretação formal futura.
- A execução de freeze dos coeficientes não imprime Brier, LogLoss, AUC, PnL ou payoff.

Prospective shadow:

```text
CALIBRATION_SHADOW_START = 2026-08-18 00:00:00 BRT
MATURITY = eligible BRT days >= 60
           AND resolved EXIT state-horizon cells >= 1000
```

Até a maturidade podem ser vistos somente contadores de readiness. Scores permanecem selados.

One-shot após maturidade, sem retuning:

1. `q_cal` vs `q_raw` em fresh-forward EXIT cells: Brier + LogLoss, STATE_HORIZON_WEIGHTED, whole-BRT-day bootstrap.
2. Reavaliar a edge econômica gross usando `q_cal - CorridorPosition`, sem threshold e sem inversão pós-hoc.
3. Custos, slippage, sizing e política de execução permanecem downstream e só entram se a calibração/edge prospectiva sobreviver.

A falha do calibration shadow não pode ser resgatada com outro calibrador no mesmo shadow. Um modelo alternativo exigirá novo freeze e novo bloco prospectivo.

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
