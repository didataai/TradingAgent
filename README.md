# TradingAgent

> **FINALIDADE**  
> Plataforma de pesquisa quantitativa, geração de dados intraday/swing, análise multi-timeframe, construção de payload factual para LLM e apoio operacional no MetaTrader 5.
>
> **ESTADO DO PROJETO**  
> Projeto de pesquisa e apoio à decisão. O TradingAgent **não executa ordens automaticamente**, não promete resultado, não substitui gestão de risco e não deve ser tratado como recomendação financeira.
>
> **PRINCÍPIO CENTRAL**  
> Python coleta, calcula, organiza e audita fatos. As camadas quantitativas produzem contexto, restrições, warnings e guards. A LLM interpreta apenas o que existe no payload. A decisão deve permanecer rastreável, explicável e auditável.

---

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Arquitetura atual](#2-arquitetura-atual)
3. [Fluxo intraday operacional](#3-fluxo-intraday-operacional)
4. [Hierarquia por timeframe](#4-hierarquia-por-timeframe)
5. [Coleta e base de dados](#5-coleta-e-base-de-dados)
6. [Contexto e payload factual](#6-contexto-e-payload-factual)
7. [Historical / Market Intelligence](#7-historical--market-intelligence)
8. [Market Chronos](#8-market-chronos)
9. [Breakout Quality](#9-breakout-quality)
10. [Execution Quality / EMA Exhaustion](#10-execution-quality--ema-exhaustion)
11. [Technical Patterns Context](#11-technical-patterns-context)
12. [Breakout Attempt Context](#12-breakout-attempt-context)
13. [Web Input Agent](#13-web-input-agent)
14. [Prompts e regras da LLM](#14-prompts-e-regras-da-llm)
15. [Comandos principais](#15-comandos-principais)
16. [Estrutura de diretórios](#16-estrutura-de-diretórios)
17. [Arquivos gerados](#17-arquivos-gerados)
18. [Regras pessoais operacionais](#18-regras-pessoais-operacionais)
19. [DXY / Synthetic Dollar](#19-dxy--synthetic-dollar)
20. [Pesquisa e backtests auxiliares](#20-pesquisa-e-backtests-auxiliares)
21. [Compatibilidade Windows/Linux](#21-compatibilidade-windowslinux)
22. [Troubleshooting](#22-troubleshooting)
23. [Roadmap](#23-roadmap)
24. [Avisos importantes](#24-avisos-importantes)

---

## 1. Visão geral

O **TradingAgent** é um ambiente de pesquisa e apoio operacional para análise de mercado, com foco atual em `GOLD`/XAUUSD, mas estruturado para múltiplos símbolos e múltiplos timeframes.

O projeto nasceu para responder a uma pergunta prática:

```text
O que o mercado está fazendo agora, onde está a região de decisão, qual é o lado permitido pelo histórico/estrutura, qual é o risco de entrada e qual gatilho objetivo ainda falta?
```

O TradingAgent não tenta fazer a LLM “adivinhar” o mercado. O objetivo é entregar para a LLM um payload factual, com campos estruturados, e obrigá-la a respeitar a hierarquia de decisão.

Separação mental do projeto:

```text
1. Dados de mercado
2. Features técnicas
3. Estrutura multi-timeframe
4. Memória histórica / Market Intelligence
5. Chronos / leis e contexto recorrente
6. Qualidade de rompimento
7. Qualidade de execução
8. Padrões gráficos e tentativas de rompimento
9. Prompt factual
10. Resposta operacional simples
```

A LLM não deve inventar:

```text
notícias
DXY
yields
sentimento
Twitter/X
probabilidades
win rate
backtest
estatísticas externas
níveis ausentes no payload
```

---

## 2. Arquitetura atual

Fluxo principal:

```text
MetaTrader 5
  ↓
Base_Dados.py
  ↓
data/<SYMBOL>_<TF>.parquet
  ↓
data/consolidated/<SYMBOL>_intraday.parquet
  ↓
context/timeframe_context.py
  ↓
data/context/<SYMBOL>_intraday_context.json
  ↓
context/prompt_payload.py
  ↓
data/payload/<SYMBOL>_intraday_payload.json
  ↓
tools/market_chronos_runtime.py
  ↓
data/context/<SYMBOL>_chronos_state.json
data/context/<SYMBOL>_chronos_intelligence.json
  ↓
tools/chronos_payload_bridge.py
  ↓
market_intelligence.py enrich
  ↓
agent/web_input_agent.py
  ↓
tools/ema_exhaustion_payload_enricher.py
  ↓
tools/technical_patterns_payload_enricher.py
  ↓
data/debug_llm/<SYMBOL>_<ANALYST>_latest_input.txt
  ↓
ChatGPT Web / LLM local
```

A arquitetura foi organizada para que cada camada faça uma coisa clara:

| Camada | Responsabilidade | Decide trade? |
|---|---|---|
| `Base_Dados.py` | coleta e features | não |
| `timeframe_context.py` | contexto multi-timeframe | não |
| `prompt_payload.py` | payload factual | não |
| `market_intelligence.py` | decisão histórica/formal | sim, quando houver final_action |
| `market_chronos_runtime.py` | memória/leis/contexto | pode apoiar ou bloquear |
| `chronos_payload_bridge.py` | injeta Chronos no payload | não |
| `ema_exhaustion_payload_enricher.py` | qualidade da entrada | não, warning-only |
| `technical_patterns_payload_enricher.py` | padrões gráficos/tentativas | não, context-only |
| `web_input_agent.py` | monta prompt final para Web | não |

---

## 3. Fluxo intraday operacional

Comando principal em PowerShell:

```powershell
python .\pipeline\intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1
```

Comando equivalente em Linux/macOS:

```bash
python pipeline/intraday_pipeline_web.py \
  --symbol GOLD \
  --web-agent \
  --analyst analyst_1
```

O pipeline faz:

```text
1. Cria lock em data/locks/
2. Roda Base_Dados.py em modo intraday_refresh
3. Atualiza Parquets M1/M5/M15/H1/H4
4. Gera consolidado intraday
5. Gera contexto multi-timeframe
6. Gera payload factual
7. Roda Chronos Runtime
8. Injeta Chronos no payload
9. Enriquece com Market Intelligence
10. Enriquece com Execution Quality
11. Enriquece com Technical Patterns
12. Gera input Web final
13. Remove lock
14. Atualiza data/pipeline_results/intraday_pipeline_latest.json
```

Exemplo de resultado esperado:

```text
Pipeline finalizado | success=True
Web input gerado | symbol=GOLD | analyst=analyst_1 | profile=quick | technical_patterns=True | llm_called=False
```

---

## 4. Hierarquia por timeframe

Intraday:

```text
H4  = regime superior / contexto macro do intraday
H1  = viés tático / estrutura principal / níveis maiores
M15 = setup / formação / região de decisão
M5  = confirmação operacional / trava / qualidade de gatilho
M1  = timing fino / gatilho de entrada
```

Swing:

```text
H4, D1, W1, MN1
```

Regra importante:

```text
Swing pode contextualizar,
mas não deve contaminar automaticamente o intraday.
```

No uso operacional atual:

```text
M15 mostra o desenho/setup.
M5 confirma ou bloqueia.
M1 dá o gatilho fino.
```

---

## 5. Coleta e base de dados

Script:

```text
Base_Dados.py
```

Responsabilidades:

```text
conectar ao MetaTrader 5
ler tradingagent.json
filtrar símbolos via CLI
coletar candles por timeframe
normalizar timestamps
identificar timezone do broker
marcar candle live
calcular indicadores
calcular métricas derivadas
calcular eventos técnicos
gerar Parquets individuais
gerar consolidado
gerar manifest
encerrar conexão MT5
```

Timeframes usados no intraday:

```text
M1, M5, M15, H1, H4
```

Timeframes usados no swing:

```text
H4, D1, W1, MN1
```

Principais features calculadas:

```text
OHLC
spread
tick_volume
retornos
range_pct
body_pct
body_signed_pct
close_pos
upper/lower wick
volume ratio
volume pace
ATR
RSI
MACD
SMA/EMA
ADX/DI+/DI-
Bollinger Bands
Stochastic
Ichimoku
OBV
MFI
Williams %R
ROC
Parabolic SAR
Vortex
Fibonacci
ZigZag
swings
BOS
CHOCH
sweeps
FVG
Order Block candidates
session flags
killzones
candlestick patterns
pattern geometry
nearby level zones
recent bars
```

Saídas comuns:

```text
data/GOLD_M1.parquet
data/GOLD_M5.parquet
data/GOLD_M15.parquet
data/GOLD_H1.parquet
data/GOLD_H4.parquet
data/consolidated/GOLD_intraday.parquet
data/manifests/base_dados_intraday_refresh_<timestamp>.json
```

---

## 6. Contexto e payload factual

### 6.1 Contexto multi-timeframe

Script:

```text
context/timeframe_context.py
```

Entrada:

```text
data/consolidated/<SYMBOL>_intraday.parquet
```

Saída:

```text
data/context/<SYMBOL>_intraday_context.json
```

Responsabilidades:

```text
organizar H4/H1/M15/M5/M1
classificar candle atual
organizar candle anterior
listar indicadores exatos
listar métricas derivadas
listar eventos técnicos
listar padrões de candle
listar geometria de padrões
listar níveis próximos
listar candles recentes
produzir ação contextual inicial
```

### 6.2 Payload factual

Script:

```text
context/prompt_payload.py
```

Saída:

```text
data/payload/<SYMBOL>_intraday_payload.json
```

O payload é a fonte única de verdade para a LLM.

Conteúdo principal:

```text
payload_schema_version
payload_type
generated_at_utc
context_generated_at_utc
symbol
current_price
market_status
source
timeframes
chronos_intelligence
historical_intelligence
breakout_quality
execution_quality
technical_patterns_context
semantics
data limitations
```

Regra:

```text
A LLM só pode usar o que está no MARKET_DATA.
```

---

## 7. Historical / Market Intelligence

Script:

```text
market_intelligence.py
```

Uso no pipeline:

```text
market_intelligence.py enrich
```

Entradas:

```text
data/intelligence/<SYMBOL>.json
data/payload/<SYMBOL>_intraday_payload.json
```

Saída:

```text
data/payload/<SYMBOL>_intraday_payload.json
```

A Historical Intelligence é a camada que pode produzir decisão formal:

```text
BUY
SELL
BUY_LIMIT_0.50
SELL_LIMIT_0.50
WAIT
WAIT_M5_CONFIRMATION
WAIT_...
```

Regra-mestra:

```text
Historical Intelligence decide a ação.
As demais camadas qualificam, apoiam, explicam ou bloqueiam apenas quando são hard blocks formais.
```

Se `final_action` for `SELL_LIMIT_0.50`, a LLM deve preservar essa ação, exceto se houver hard block formal.

`BUY_LIMIT_*` e `SELL_LIMIT_*` são ações condicionais/limitadas. Não significam perseguir preço a mercado.

---

## 8. Market Chronos

Scripts:

```text
tools/market_chronos_engine_v10_1.py
tools/market_chronos_runtime.py
tools/chronos_payload_bridge.py
```

Objetivo:

```text
Dar memória de mercado, estado atual, leis recorrentes, segmentos e bloqueios contextuais.
```

Saídas:

```text
data/context/<SYMBOL>_chronos_state.json
data/context/<SYMBOL>_chronos_intelligence.json
```

Campos importantes:

```text
available
freshness.status
chronos_action
supporting_side
blocked_actions
matched_laws
current_segments
breakout_quality_score
operational_band
observed_score
known_families
```

Interpretação:

```text
NO_MATCH = neutro
supporting_side = apoio, não ordem
blocked_actions = hard block apenas para o lado explicitamente bloqueado
freshness != FRESH = ignorar operacionalmente
```

Chronos pode:

```text
apoiar um lado
bloquear explicitamente um lado
indicar ausência de match
trazer memória de regimes e leis
```

Chronos não pode:

```text
inventar trade
liberar lado bloqueado
operar lado oposto só porque bloqueou um lado
substituir Historical
```

---

## 9. Breakout Quality

Script:

```text
tools/chronos_breakout_quality_score.py
```

Objetivo:

```text
Classificar qualidade contextual do rompimento.
```

Faixas:

```text
LOW     = rompimento fraco / cuidado com chase
VALID   = rompimento aceitável, ainda exige gatilho
PREMIUM = rompimento forte, mas não é entrada automática
UNAVAILABLE = ignorar
```

Regra:

```text
Breakout Quality qualifica o rompimento.
Breakout Quality não substitui Historical.
Breakout Quality LOW não cria sinal contrário automático.
```

---

## 10. Execution Quality / EMA Exhaustion

Script:

```text
tools/ema_exhaustion_payload_enricher.py
```

Executado pelo:

```text
agent/web_input_agent.py
```

Objetivo:

```text
Qualificar risco de entrada agora.
```

Campos importantes:

```text
execution_quality.state
execution_quality.buy_allowed
execution_quality.sell_allowed
execution_quality.buy_warning_reason
execution_quality.sell_warning_reason
execution_quality.warnings
execution_quality.next_buy_trigger
execution_quality.next_sell_trigger
execution_quality.summary
execution_quality.decision_semantics
ema_exhaustion_context.entry_quality
ema_exhaustion_context.pullback_state
ema_exhaustion_context.exhaustion_risk
ema_exhaustion_context.preferred_action
```

Regra crítica:

```text
Execution Quality é WARNING_ONLY.
```

Isso significa:

```text
buy_allowed=false  → warning, não hard block
sell_allowed=false → warning, não hard block
EXTENDED_MOVE      → warning de chase
EXHAUSTION_RISK    → warning de exaustão
WAIT_PULLBACK      → contexto de qualidade, não veto
```

Exemplo correto:

```text
Historical final_action=SELL_LIMIT_0.50
Execution Quality sell_allowed=false
→ Ação Imediata: SELL_LIMIT_0.50
→ Venda: liberada com warning.
```

---

## 11. Technical Patterns Context

Script:

```text
tools/technical_patterns_payload_enricher.py
```

Executado pelo:

```text
agent/web_input_agent.py
```

Objetivo:

```text
Adicionar leitura gráfica estruturada ao payload.
```

A camada é:

```text
CONTEXT_ONLY
```

Ou seja:

```text
não decide BUY/SELL/WAIT
não cria hard block
não sobrescreve Historical
não cancela ação por conta própria
```

Padrões reconhecidos:

```text
BULL_FLAG
BEAR_FLAG
BULLISH_PENNANT
BEARISH_PENNANT
ASCENDING_TRIANGLE
DESCENDING_TRIANGLE
SYMMETRICAL_TRIANGLE
ASCENDING_CHANNEL
DESCENDING_CHANNEL
RANGE_RECTANGLE
COMPRESSION
DOUBLE_TOP
DOUBLE_BOTTOM
FALSE_BREAKOUT_UP
FALSE_BREAKOUT_DOWN
SWEEP_HIGH
SWEEP_LOW
BOS_UP
BOS_DOWN
CHOCH_UP
CHOCH_DOWN
FVG_UP
FVG_DOWN
candles relevantes
```

Conceitos importantes:

```text
directional_intent = intenção teórica do padrão
bias = leitura operacional atual conservadora
stage = CONFIRMED / FORMING / DETECTED
formation_status = formação, consolidação, candidato ou confirmado
confirmation_required = se precisa confirmação
```

Exemplos:

```text
DOUBLE_TOP candidato:
  directional_intent = SELL
  bias = MIXED
  formation_status = REVERSAL_CANDIDATE
  confirmation_required = true
  trigger = break_below_neckline

ASCENDING_TRIANGLE formando:
  directional_intent = BUY
  bias = MIXED
  formation_status = FORMATION_OR_CONSOLIDATION
  confirmation_required = true
  trigger = break_and_accept_above_horizontal_resistance

BEAR_FLAG formando:
  directional_intent = SELL
  bias = MIXED ou SELL contextual
  formation_status = CONTINUATION_CANDIDATE
  confirmation_required = true
```

Exemplo de resumo:

```text
M15: BEAR_FLAG (CONTINUATION_CANDIDATE/MIXED)
M5: ASCENDING_TRIANGLE (FORMATION_OR_CONSOLIDATION/MIXED)
M1: DESCENDING_CHANNEL (CONTEXT_DETECTED/MIXED)
H1: DOUBLE_TOP (REVERSAL_CANDIDATE/MIXED)
```

---

## 12. Breakout Attempt Context

O `technical_patterns_payload_enricher.py` também adiciona a leitura de tentativas de rompimento.

Motivação operacional:

```text
Formações raramente rompem limpo na primeira tentativa.
Primeira tentativa tem risco maior de fakeout/chase.
Retorno para dentro da formação pode ser mais informativo que perseguir rompimento.
Terceira tentativa pode ganhar relevância, desde que exista candle fechado, aceitação, volume e permissão operacional.
```

Campos adicionados por timeframe:

```text
breakout_attempt_context.available
upper_boundary
lower_boundary
breakout_attempts_up
breakout_attempts_down
failed_breakouts_up
failed_breakouts_down
accepted_breakouts_up
accepted_breakouts_down
last_attempt_side
last_attempt_result
inside_formation_now
third_attempt_watch
fakeout_risk
fade_breakout_context
preferred_interpretation
read
decision_semantics
```

Interpretações típicas:

```text
FADE_FIRST_BREAKOUT_OR_WAIT_RETEST
WAIT_CONFIRMATION
WATCH_THIRD_ATTEMPT
WAIT_ACCEPTANCE
```

Exemplo:

```json
"breakout_attempt_context": {
  "available": true,
  "upper_boundary": 4064.91,
  "lower_boundary": 4054.26,
  "breakout_attempts_up": 1,
  "failed_breakouts_up": 1,
  "last_attempt_side": "UP",
  "last_attempt_result": "FAILED_BREAKOUT",
  "inside_formation_now": true,
  "fakeout_risk": "HIGH",
  "preferred_interpretation": "FADE_FIRST_BREAKOUT_OR_WAIT_RETEST",
  "decision_semantics": "CONTEXT_ONLY"
}
```

Uso correto pela LLM:

```text
M15 tem bear flag em formação.
Primeira tentativa falhou.
Risco de fakeout alto.
Evitar chase.
Preferir reteste, retorno para dentro ou nova tentativa com candle fechado.
```

Uso incorreto:

```text
Fakeout risk HIGH → vender automaticamente.
```

---

## 13. Web Input Agent

Script:

```text
agent/web_input_agent.py
```

Função:

```text
Gerar arquivo completo para análise manual via ChatGPT Web,
sem chamar API externa e sem chamar LLM local.
```

Fluxo atual dentro dele:

```text
1. Lê tradingagent.json
2. Resolve profile quick/detailed
3. Resolve analista
4. Roda EMA/Execution Quality enrichment
5. Roda Technical Patterns enrichment
6. Lê payload atualizado
7. Monta prompt com MARKET_DATA
8. Adiciona schema de resposta JSON
9. Salva latest_input
```

Saída:

```text
data/debug_llm/GOLD_analyst_1_latest_input.txt
```

Comando Windows:

```powershell
python .\agent\web_input_agent.py `
  --symbol GOLD `
  --analyst analyst_1
```

Comando Linux/macOS:

```bash
python agent/web_input_agent.py \
  --symbol GOLD \
  --analyst analyst_1
```

Flags úteis:

```text
--skip-ema-enrichment
--skip-technical-patterns
--write-timeframe-parquets
--profile quick
--profile detailed
```

---

## 14. Prompts e regras da LLM

Prompts principais:

```text
prompts/promptIntraday.md
prompts/promptIntradayQuick.md
prompts/promptSwing.md
```

A resposta Web deve ser simples e operacional, normalmente com:

```text
1. Pontos-chave
2. Pontos de atenção
3. Resumo por timeframe
4. Ação Imediata
5. Ação Mais Recomendada Agora
```

Regra-mestra do prompt:

```text
Historical Intelligence decide a ação.
Execution Quality apenas qualifica a entrada.
Technical Patterns apenas explicam setup, consolidação, tentativa e fakeout.
```

Hard blocks formais:

```text
dados stale/ausentes/inválidos
final_action WAIT
final_action começando com WAIT_
blocked_reasons formais
chronos blocked_actions para o lado da ação
personal_risk_guard ativo para o lado da ação
regra M5 pessoal quando ativa
conflito formal definido pelo Historical
```

Não são hard blocks:

```text
execution_quality.buy_allowed=false
execution_quality.sell_allowed=false
execution_quality.state=EXTENDED_MOVE
execution_quality.state=EXHAUSTION_RISK
ema_exhaustion_context.entry_quality=LATE_BUY_RISK
ema_exhaustion_context.entry_quality=LATE_SELL_RISK
ema_exhaustion_context.preferred_action=WAIT_PULLBACK
technical_patterns_context.pattern_bias=MIXED
breakout_attempt_context.fakeout_risk=HIGH
```

Esses itens viram warning ou contexto.

---

## 15. Comandos principais

### Atualizar repositório

Windows:

```powershell
git pull origin main
```

Linux/macOS:

```bash
git pull origin main
```

### Rodar pipeline intraday Web

Windows:

```powershell
python .\pipeline\intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1
```

Linux/macOS:

```bash
python pipeline/intraday_pipeline_web.py \
  --symbol GOLD \
  --web-agent \
  --analyst analyst_1
```

### Rodar somente Base_Dados intraday

Windows:

```powershell
python .\Base_Dados.py `
  --mode intraday_refresh `
  --symbol GOLD
```

Linux/macOS:

```bash
python Base_Dados.py \
  --mode intraday_refresh \
  --symbol GOLD
```

### Gerar apenas Web Input

Windows:

```powershell
python .\agent\web_input_agent.py `
  --symbol GOLD `
  --analyst analyst_1
```

Linux/macOS:

```bash
python agent/web_input_agent.py \
  --symbol GOLD \
  --analyst analyst_1
```

### Testar Technical Patterns diretamente

Windows:

```powershell
python .\tools\technical_patterns_payload_enricher.py `
  --symbol GOLD
```

Linux/macOS:

```bash
python tools/technical_patterns_payload_enricher.py \
  --symbol GOLD
```

### Procurar campos no payload

Windows:

```powershell
Select-String -Path .\data\payload\GOLD_intraday_payload.json -Pattern "technical_patterns_context"
Select-String -Path .\data\payload\GOLD_intraday_payload.json -Pattern "breakout_attempt_context","fakeout_risk","third_attempt_watch"
```

Linux/macOS:

```bash
grep -E "technical_patterns_context|breakout_attempt_context|fakeout_risk|third_attempt_watch" data/payload/GOLD_intraday_payload.json
```

---

## 16. Estrutura de diretórios

```text
TradingAgent/
├── Base_Dados.py
├── market_intelligence.py
├── tradingagent.json
├── README.md
│
├── agent/
│   ├── intraday_agent.py
│   └── web_input_agent.py
│
├── context/
│   ├── timeframe_context.py
│   └── prompt_payload.py
│
├── pipeline/
│   ├── intraday_pipeline.py
│   ├── intraday_pipeline_web.py
│   └── swing_pipeline_web.py
│
├── prompts/
│   ├── promptIntraday.md
│   ├── promptIntradayQuick.md
│   ├── promptSwing.md
│   ├── promptCritic.md
│   └── promptArbiter.md
│
├── tools/
│   ├── ema_exhaustion_payload_enricher.py
│   ├── technical_patterns_payload_enricher.py
│   ├── market_chronos_engine_v10_1.py
│   ├── market_chronos_runtime.py
│   ├── chronos_payload_bridge.py
│   ├── chronos_breakout_quality_score.py
│   ├── market_context_hierarchical_miner.py
│   ├── ma_confluence_optimizer.py
│   ├── dxy_gold_research.py
│   ├── synthetic_dollar_context.py
│   ├── personal_trade_auditor.py
│   ├── personal_trade_execution_audit.py
│   ├── personal_risk_guard_builder.py
│   └── mt5_history_diagnostic.py
│
└── data/
    ├── consolidated/
    ├── context/
    ├── payload/
    ├── intelligence/
    ├── market_chronos/
    ├── debug_llm/
    ├── research/
    ├── personal_trade_auditor/
    ├── logs/
    ├── locks/
    ├── manifests/
    └── pipeline_results/
```

---

## 17. Arquivos gerados

Intraday principal:

```text
data/GOLD_M1.parquet
data/GOLD_M5.parquet
data/GOLD_M15.parquet
data/GOLD_H1.parquet
data/GOLD_H4.parquet
data/consolidated/GOLD_intraday.parquet
```

Contexto:

```text
data/context/GOLD_intraday_context.json
data/context/GOLD_chronos_state.json
data/context/GOLD_chronos_intelligence.json
```

Payload:

```text
data/payload/GOLD_intraday_payload.json
```

Web:

```text
data/debug_llm/GOLD_analyst_1_latest_input.txt
```

Pipeline:

```text
data/pipeline_results/intraday_pipeline_latest.json
data/locks/intraday_pipeline.lock
```

Pesquisa:

```text
data/research/dxy_gold/GOLD/
data/research/ma_confluence/
```

---

## 18. Regras pessoais operacionais

Regras operacionais atuais do Diego:

```text
M1 é gatilho fino.
M5 é trava obrigatória.
Suporte/resistência são regiões de decisão.
Candle fechado importa.
Volume e horário ajudam a diferenciar rompimento real/falso.
```

Regra M5:

```text
Venda bloqueada se preço/M5 atual rompeu a máxima do candle M5 anterior.
Compra bloqueada se preço/M5 atual rompeu a mínima do candle M5 anterior.
```

Regra de entrada M1:

```text
Compra:
  candle M1 anterior fechado verde
  entrada no rompimento da máxima do candle anterior
  candle não pode estar longo demais

Venda:
  candle M1 anterior fechado vermelho
  entrada no rompimento da mínima do candle anterior
  candle não pode estar longo demais
```

Falso rompimento:

```text
Falso rompimento é contexto, não reversão automática.
Só vira entrada depois de retorno, confirmação e permissão M5/M1.
```

Padrões em formação:

```text
Formação detectada não significa rompimento confirmado.
Primeira tentativa de rompimento pode falhar.
Terceira tentativa pode ter mais relevância se houver aceitação.
```

---

## 19. DXY / Synthetic Dollar

O projeto possui scripts de pesquisa para DXY sintético:

```text
tools/synthetic_dollar_context.py
tools/dxy_gold_research.py
```

Decisão operacional atual:

```text
DXY foi removido do Web Input operacional.
DXY não entra mais no MARKET_DATA operacional.
DXY não aparece no prompt final.
DXY fica apenas para pesquisa separada.
```

Motivo:

```text
Os testes mostraram que DXY x GOLD não teve influência suficientemente estável para virar filtro operacional.
```

Regra:

```text
Não usar DXY para BUY/SELL/WAIT no operacional atual.
```

---

## 20. Pesquisa e backtests auxiliares

### 20.1 MA Confluence Optimizer

Script:

```text
tools/ma_confluence_optimizer.py
```

Objetivo:

```text
Pesquisar combinações de médias, alinhamento M1/M5/M15, stop/target/hold e robustez.
```

Saídas típicas:

```text
top_configs.csv
top_configs.json
summary.json
trades_sample.csv
top_config_trades.csv
top_config_by_day.csv
top_config_by_hour.csv
top_config_walk_forward.csv
neighborhood_report.csv
```

### 20.2 DXY Gold Research

Script:

```text
tools/dxy_gold_research.py
```

Objetivo:

```text
Pesquisar relação DXY sintético x GOLD, correlação, lag, volatilidade, setups condicionais.
```

Uso:

```powershell
python .\tools\dxy_gold_research.py `
  --symbol GOLD `
  --dxy-mode DXY_FULL
```

Saídas:

```text
data/research/dxy_gold/GOLD/dxy_gold_summary.json
data/research/dxy_gold/GOLD/dxy_gold_lag_matrix.csv
data/research/dxy_gold/GOLD/dxy_gold_by_hour.csv
data/research/dxy_gold/GOLD/dxy_gold_conditional_setups.csv
```

Uso atual:

```text
Pesquisa apenas. Não entra no operacional.
```

---

## 21. Compatibilidade Windows/Linux

Princípios usados no projeto:

```text
usar pathlib
não hardcodar separador de caminho
aceitar caminhos relativos e absolutos
manter comandos Windows e Linux documentados
não depender de shell específico dentro dos scripts
usar UTF-8 quando possível
usar escrita atômica para JSON/texto
```

Windows PowerShell usa crase para quebra de linha:

```powershell
python .\pipeline\intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1
```

Linux/macOS usa barra invertida:

```bash
python pipeline/intraday_pipeline_web.py \
  --symbol GOLD \
  --web-agent \
  --analyst analyst_1
```

---

## 22. Troubleshooting

### Pipeline travou com lock

Verificar:

```text
data/locks/intraday_pipeline.lock
```

Se não houver processo rodando, remover o lock manualmente.

### MT5 não conecta

Verificar:

```text
MetaTrader 5 aberto
login ativo
símbolo habilitado no Market Watch
tradingagent.json
permissões do terminal
```

### Web input não atualizou

Rodar:

```powershell
python .\agent\web_input_agent.py `
  --symbol GOLD `
  --analyst analyst_1
```

Verificar:

```text
data/debug_llm/GOLD_analyst_1_latest_input.txt
```

### Technical Patterns não aparece

Verificar:

```powershell
Select-String -Path .\data\payload\GOLD_intraday_payload.json -Pattern "technical_patterns_context"
```

Rodar direto:

```powershell
python .\tools\technical_patterns_payload_enricher.py `
  --symbol GOLD
```

### Execution Quality não aparece

Rodar:

```powershell
python .\tools\ema_exhaustion_payload_enricher.py `
  --symbol GOLD `
  --payload .\data\payload\GOLD_intraday_payload.json
```

### DXY apareceu no prompt operacional

Isso não deveria ocorrer no estado atual. DXY deve ficar fora do Web Input operacional.

Procurar:

```powershell
Select-String -Path .\data\debug_llm\GOLD_analyst_1_latest_input.txt -Pattern "DXY","Synthetic Dollar","synthetic_dollar"
```

---

## 23. Roadmap

Próximos pontos naturais:

```text
1. Transformar pattern_breakout_attempt_context em fator de qualidade pesquisável.
2. Medir estatisticamente 1ª, 2ª e 3ª tentativa por tipo de padrão.
3. Integrar MA Confluence como camada warning/context-only no payload.
4. Criar relatório de padrões por sessão/hora.
5. Evoluir Personal Risk Guard com base em auditoria real de trades.
6. Criar comparação de performance com e sem Technical Patterns.
7. Melhorar priorização de padrões conflitantes no mesmo timeframe.
8. Separar padrão confirmado, padrão candidato e padrão em consolidação no prompt final.
```

---

## 24. Avisos importantes

```text
Este projeto é para pesquisa, estudo e apoio à decisão.
Não é robô de execução automática.
Não é recomendação financeira.
Não promete win rate.
Não garante resultado.
Não substitui gestão de risco.
```

Regra final:

```text
Trade bom não é o que parece bonito.
Trade bom é o que respeita contexto, região, candle fechado, gatilho, risco e processo.
```
