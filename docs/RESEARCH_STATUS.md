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
