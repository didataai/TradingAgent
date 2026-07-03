# TradingAgent

> **FINALIDADE**  
> Plataforma de pesquisa quantitativa, análise multi-timeframe, geração de payload factual para LLM e auditoria pessoal de execução no MetaTrader 5.
>
> **ESTADO DO PROJETO**  
> Apoio à decisão e pesquisa. O projeto não executa ordens automaticamente, não promete resultado e não deve ser tratado como recomendação financeira.
>
> **PRINCÍPIO CENTRAL**  
> Python coleta, calcula e organiza fatos; os módulos quantitativos produzem contexto, restrições e guards; a LLM interpreta apenas o que está no payload; toda decisão deve permanecer auditável.

---

## 1. Visão geral

O **TradingAgent** foi criado para estudar e apoiar operações em mercados como `GOLD`, `EURUSD`, `GBPUSD`, `Brent` e `UsaInd`, usando dados do MetaTrader 5, engenharia de features, contexto multi-timeframe, Market Intelligence, Market Chronos, Breakout Quality e auditoria pessoal de execução.

O projeto possui dois grandes fluxos:

```text
1. Fluxo de mercado
   MT5 → dados → features → contexto → payload → Chronos → Intelligence → LLM/Web

2. Fluxo de auditoria pessoal
   histórico real MT5 → reconstrução de trades → contexto da entrada → MFE/MAE → Risk Guard diário → JSON para análise Web
```

A ideia é separar claramente:

```text
Fatos de mercado
Inteligência quantitativa
Regras pessoais
Interpretação final
Execução real
Auditoria pós-trade
```

A LLM não deve inventar dados, probabilidades, notícias, backtests, DXY, sentimento ou estatísticas que não estejam presentes no payload.

---

## 2. Arquitetura do fluxo de mercado

Fluxo intraday principal:

```text
MetaTrader 5
→ Base_Dados.py
→ Parquets por timeframe
→ data/consolidated/<SYMBOL>_intraday.parquet
→ context/timeframe_context.py
→ data/context/<SYMBOL>_intraday_context.json
→ context/prompt_payload.py
→ data/payload/<SYMBOL>_intraday_payload.json
→ tools/market_chronos_runtime.py
→ data/context/<SYMBOL>_chronos_state.json
→ data/context/<SYMBOL>_chronos_intelligence.json
→ tools/chronos_payload_bridge.py
→ market_intelligence.py enrich
→ agent/web_input_agent.py ou agent/intraday_agent.py
→ LLM/Web
```

Componentes principais:

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
│   ├── promptSwing.md
│   ├── promptCritic.md
│   └── promptArbiter.md
│
├── tools/
│   ├── market_chronos_engine_v10_1.py
│   ├── market_chronos_runtime.py
│   ├── chronos_payload_bridge.py
│   ├── market_context_hierarchical_miner.py
│   ├── chronos_breakout_quality_score.py
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
    ├── personal_trade_auditor/
    ├── logs/
    ├── locks/
    └── manifests/
```

---

## 3. Timeframes e hierarquia operacional

Fluxo intraday:

```text
H4  = regime superior
H1  = viés tático
M15 = setup / estrutura intermediária
M5  = gatilho macro / permissão operacional
M1  = refinamento e timing fino
```

Fluxo swing:

```text
H4, D1, W1, MN1
```

Regra importante:

```text
Swing pode entrar como contexto superior,
mas não deve contaminar automaticamente o intraday.
```

No operacional pessoal do Diego, a leitura ficou:

```text
M1 = gatilho fino de entrada
M5 = trava obrigatória
S/R = região de decisão
Horário + volume = leitura de rompimento real/falso
```

---

## 4. `Base_Dados.py`

Responsável por:

- conectar ao MetaTrader 5;
- carregar configuração;
- coletar candles;
- normalizar timestamps;
- detectar timezone do broker;
- marcar barra live;
- calcular indicadores técnicos;
- calcular features estruturais;
- calcular volume relativo;
- detectar eventos;
- gerar Parquets individuais;
- gerar consolidado intraday;
- gerar manifestos.

Timeframes suportados:

```text
M1, M5, M15, H1, H4, D1, W1, MN1
```

Principais grupos de features:

- OHLC;
- tick volume;
- spread;
- retornos;
- ATR;
- RSI;
- MACD;
- SMA e EMA;
- ADX, DI+ e DI−;
- Bollinger Bands;
- Stochastic;
- Ichimoku;
- OBV;
- MFI;
- Williams %R;
- ROC;
- Parabolic SAR;
- Vortex;
- padrões de candle;
- pivôs;
- ZigZag causal;
- BOS e CHOCH;
- sweeps;
- FVG;
- Order Blocks candidatos;
- Fibonacci;
- sessões;
- volume relativo;
- volume pace;
- corpo, pavios e posição do fechamento;
- compressão e expansão.

---

## 5. Contexto e payload

### 5.1 Contexto multi-timeframe

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

- resumir cada timeframe;
- classificar barra atual;
- organizar indicadores e métricas;
- organizar níveis próximos;
- organizar candles recentes;
- organizar candidatos de padrões;
- produzir trace multi-timeframe;
- manter dados auditáveis.

### 5.2 Payload factual

Script:

```text
context/prompt_payload.py
```

Saída:

```text
data/payload/<SYMBOL>_intraday_payload.json
```

Conteúdo:

- preço atual;
- estado do mercado;
- H4, H1, M15, M5 e M1;
- candle atual e anterior;
- indicadores exatos;
- métricas derivadas;
- eventos;
- padrões;
- níveis exatos;
- zonas próximas;
- Fibonacci;
- geometria;
- candles recentes;
- semântica dos campos;
- limitações.

---

## 6. Market Chronos

O **Market Chronos** representa a camada de memória/contexto histórico do mercado.

Objetivos:

- detectar estados recorrentes;
- identificar tentativas em níveis;
- acompanhar falhas e memória recente;
- reconhecer regimes de sequência;
- aplicar leis de mercado validadas;
- produzir apoio, neutralidade ou bloqueio.

Script principal:

```text
tools/market_chronos_runtime.py
```

Saídas:

```text
data/context/<SYMBOL>_chronos_state.json
data/context/<SYMBOL>_chronos_intelligence.json
```

Campos importantes:

- `chronos_action`;
- `supporting_side`;
- `blocked_actions`;
- `matched_laws`;
- `confidence`;
- `freshness`;
- `current_segments`.

O Chronos pode:

```text
confirmar
neutralizar
reduzir confiança
bloquear um lado
```

O Chronos não pode:

```text
liberar uma ação proibida pelo guard principal
inventar probabilidade
substituir confirmação técnica
transformar ausência de lei em sinal contrário
```

---

## 7. Breakout Quality Score

Script:

```text
tools/chronos_breakout_quality_score.py
```

Objetivo:

```text
Classificar a qualidade contextual de um rompimento antes de tratá-lo como oportunidade operacional.
```

Escala:

```text
-5 a +5
```

Famílias avaliadas:

- displacement;
- participation;
- momentum;
- location;
- trend.

Faixas operacionais:

```text
LOW     = score <= 1
VALID   = score 2 ou 3
PREMIUM = score 4 ou 5
```

Interpretação:

```text
LOW
→ rompimento de baixa qualidade
→ não perseguir
→ preferir WAIT ou nova confirmação

VALID
→ rompimento aceitável
→ exige gatilho, região e confirmação M15/M5

PREMIUM
→ rompimento de alta qualidade
→ prioridade maior
→ nunca entrada automática

UNAVAILABLE
→ dado stale ou indisponível
→ ignorar operacionalmente
```

Execução:

```powershell
python .\tools\chronos_breakout_quality_score.py `
  --symbol GOLD
```

Saída:

```text
data/market_chronos/GOLD/breakout_quality_score/
```

---

## 8. Market Intelligence

Script:

```text
market_intelligence.py
```

Responsável por enriquecer o payload com inteligência histórica e decisão formal multi-timeframe.

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

Regra:

```text
O guard formal da Historical Intelligence permanece a restrição principal da ação imediata.
```

---

## 9. Hierarquia decisória da LLM

Ordem correta:

```text
1. Historical Intelligence formal guard
2. Freshness e disponibilidade
3. blocked_reasons e blocked_actions
4. Chronos Laws
5. Breakout Quality
6. Confirmação H1/M15/M5
7. Entrada, stop, alvo e invalidação
8. Personal Risk Guard, quando existir
```

Regras principais:

- `WAIT` do guard principal permanece `WAIT`;
- `PREMIUM` não libera ação bloqueada;
- `LOW` não cria sinal oposto;
- `UNAVAILABLE` é ignorado operacionalmente;
- divergência entre lado do score e ação permitida reduz confiança;
- Personal Risk Guard deve bloquear operações que violam regras pessoais;
- na dúvida, escolher `WAIT`.

---

## 10. Execução do fluxo de mercado

### 10.1 Pipeline Web completo

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1
```

### 10.2 Pipeline com chamada de LLM

```powershell
python pipeline/intraday_pipeline.py `
  --symbol GOLD `
  --agent-mode single `
  --analyst analyst_1
```

### 10.3 Apenas coleta intraday

```powershell
python Base_Dados.py `
  --mode intraday_refresh `
  --symbol GOLD
```

### 10.4 Apenas contexto

```powershell
python context/timeframe_context.py `
  --symbol GOLD
```

### 10.5 Apenas payload

```powershell
python context/prompt_payload.py `
  --symbol GOLD
```

### 10.6 Apenas Chronos Runtime

```powershell
python tools/market_chronos_runtime.py `
  --symbol GOLD `
  --anchor-tf M5 `
  --source-mode live `
  --live-timeframes M5 M15 H1 H4 `
  --warmup-bars 5000 `
  --max-age-minutes 30 `
  --event-timezone UTC
```

### 10.7 Apenas bridge

```powershell
python tools/chronos_payload_bridge.py `
  --payload data/payload/GOLD_intraday_payload.json `
  --chronos data/context/GOLD_chronos_intelligence.json `
  --output data/payload/GOLD_intraday_payload.json
```

### 10.8 Gerar input Web

```powershell
python agent/web_input_agent.py `
  --symbol GOLD `
  --analyst analyst_1
```

Saída:

```text
data/debug_llm/GOLD_analyst_1_latest_input.txt
```

---

# 11. Personal Trade Auditor diário

Esta é a camada de auditoria pessoal do Diego. Ela cruza trades reais do MetaTrader 5 com o contexto intraday do TradingAgent e gera um **Risk Guard pessoal** para melhorar execução e evitar erros repetidos.

O fluxo possui três scripts:

```text
1. tools/personal_trade_auditor.py
2. tools/personal_trade_execution_audit.py
3. tools/personal_risk_guard_builder.py
```

A lógica final é:

```text
histórico real MT5
→ reconstrução de trades
→ contexto H1/M15/M5/M1 na entrada
→ tags operacionais
→ MFE/MAE
→ summary diário
→ web_decision_payload.json
→ análise via ChatGPT/Web
```

---

## 11.1 Regras pessoais do Diego

### M1 = gatilho de entrada

Compra:

```text
candle M1 anterior fechou verde
candle anterior não é longo
entrada no rompimento da máxima do candle M1 anterior
```

Venda:

```text
candle M1 anterior fechou vermelho
candle anterior não é longo
entrada no rompimento da mínima do candle M1 anterior
```

### M5 = trava obrigatória

Venda permitida:

```text
preço atual dentro do corpo do candle M5 anterior
ou rompendo a mínima do candle M5 anterior
```

Venda bloqueada:

```text
preço/M5 atual acima da máxima do candle M5 anterior
```

Compra permitida:

```text
preço atual dentro do corpo do candle M5 anterior
ou rompendo a máxima do candle M5 anterior
```

Compra bloqueada:

```text
preço/M5 atual abaixo da mínima do candle M5 anterior
```

Regra final:

```text
Se M5 bloqueia, não opera.
```

### Região de decisão

```text
Comprar suporte
Vender resistência
Evitar comprar resistência
Evitar vender suporte
```

Quando houver rompimento com volume e janela forte:

```text
não fazer fade automático
esperar confirmação, aceitação ou pullback
```

Janelas observadas:

```text
09:00–10:00     possível rompimento/continuidade
12:30–13:30     possível rompimento/volume
```

---

## 11.2 Auditor principal: `personal_trade_auditor.py`

Objetivo:

```text
Buscar trades reais no MT5, reconstruir operações e marcar contexto da entrada.
```

Comando base:

```powershell
python .\tools\personal_trade_auditor.py `
  --symbol GOLD `
  --mt5-symbol XAUUSD `
  --data-symbol GOLD `
  --from-date 2026-07-01 `
  --to-date 2026-07-01 `
  --mt5-config .\config\personal_mt5.local.json
```

Parâmetros:

- `--symbol`: alias lógico do relatório, exemplo `GOLD`;
- `--mt5-symbol`: nome do ativo no broker, exemplo `XAUUSD`;
- `--data-symbol`: nome da base local, exemplo `GOLD`;
- `--from-date`: data inicial;
- `--to-date`: data final;
- `--mt5-config`: arquivo local de configuração MT5;
- `--no-symbol-filter`: não filtra por símbolo MT5;
- `--zone-window-bars`: janela para suporte/resistência local;
- `--zone-tolerance-atr`: tolerância ATR para zona.

Arquivo de configuração local:

```text
config/personal_mt5.local.json
```

Esse arquivo deve ficar fora do Git e não deve ser versionado.

Exemplo de formato:

```json
{
  "mt5": {
    "path": "C:/CAMINHO/PARA/terminal64.exe",
    "account": 123456,
    "password_env": "MT5_PASSWORD",
    "server": "BROKER-SERVER",
    "symbol": "XAUUSD"
  },
  "data": {
    "symbol": "GOLD"
  }
}
```

Recomendação:

```powershell
$env:MT5_PASSWORD="sua_senha"
```

Nunca commitar senha, login real, servidor real ou arquivo local de credenciais.

### Tags geradas pelo auditor

Exemplos:

```text
COUNTER_H1
COUNTER_M15
M5_BLOCKED_SELL_ABOVE_PREV_HIGH
M5_BLOCKED_BUY_BELOW_PREV_LOW
SELL_NEAR_CANDLE_LOW
BUY_NEAR_CANDLE_HIGH
TIME_BREAKOUT_WINDOW_09_10
TIME_BREAKOUT_WINDOW_1230_1330
FALSE_BREAKOUT_UP_CONTEXT
FALSE_BREAKOUT_DOWN_CONTEXT
REAL_BREAKOUT_UP_CONTEXT
REAL_BREAKOUT_DOWN_CONTEXT
BUY_AT_SUPPORT
SELL_AT_RESISTANCE
BUY_AT_RESISTANCE
SELL_AT_SUPPORT
```

Interpretação importante:

```text
FALSE_BREAKOUT_CONTEXT sozinho não é erro.
Erro ocorre quando o falso rompimento é operado cedo demais,
com M5 bloqueado, candle esticado, stop curto ou execução ruim.
```

---

## 11.3 Execution Audit: `personal_trade_execution_audit.py`

Objetivo:

```text
Calcular MFE/MAE e separar leitura ruim de stop/saída/execução ruim.
```

Comando:

```powershell
python .\tools\personal_trade_execution_audit.py `
  --symbol GOLD `
  --data-symbol GOLD
```

Métricas:

```text
MFE = máximo que o trade andou a favor
MAE = máximo que o trade andou contra
post_exit_MFE = quanto andou a favor depois que saiu
```

Regras:

```text
MFE nunca deve ser negativo
MAE nunca deve ser negativo
post_exit_MFE nunca deve ser negativo
```

Tags principais:

```text
TRADE_LOSS
TRADE_WIN
M5_HARD_BLOCK_VIOLATED
ENTRY_AFTER_EXTENSION
LOSS_BUT_HAD_GOOD_MFE
MOVE_CAME_AFTER_EXIT
GOOD_IDEA_BAD_STOP_OR_EXIT
EXIT_TOO_EARLY_LOW_MFE_CAPTURE
EXECUTION_ACCEPTABLE
```

Leitura prática:

```text
M5_HARD_BLOCK_VIOLATED
→ operação violou trava obrigatória

ENTRY_AFTER_EXTENSION
→ entrada depois do movimento já esticado

LOSS_BUT_HAD_GOOD_MFE
→ deu loss, mas houve movimento a favor

MOVE_CAME_AFTER_EXIT
→ movimento veio depois da saída

GOOD_IDEA_BAD_STOP_OR_EXIT
→ ideia pode ter sido boa, mas stop/saída prejudicou

EXIT_TOO_EARLY_LOW_MFE_CAPTURE
→ trade vencedor, mas capturou pouco do movimento disponível
```

---

## 11.4 Builder diário: `personal_risk_guard_builder.py`

Objetivo:

```text
Consolidar auditoria + execution quality + regras pessoais em dois arquivos por dia.
```

Comando:

```powershell
python .\tools\personal_risk_guard_builder.py `
  --symbol GOLD `
  --data-symbol GOLD
```

Saída oficial por dia:

```text
data/personal_trade_auditor/GOLD/daily/YYYY-MM-DD/summary.json
data/personal_trade_auditor/GOLD/daily/YYYY-MM-DD/web_decision_payload.json
```

Atalho latest:

```text
data/personal_trade_auditor/GOLD/latest/summary.json
data/personal_trade_auditor/GOLD/latest/web_decision_payload.json
```

O arquivo para colar no ChatGPT/Web é:

```text
data/personal_trade_auditor/GOLD/latest/web_decision_payload.json
```

Forçar data do relatório:

```powershell
python .\tools\personal_risk_guard_builder.py `
  --symbol GOLD `
  --data-symbol GOLD `
  --report-date 2026-07-01
```

Manter nomes antigos na raiz, caso necessário:

```powershell
python .\tools\personal_risk_guard_builder.py `
  --symbol GOLD `
  --data-symbol GOLD `
  --keep-legacy-latest
```

---

## 11.5 Estrutura final desejada

Após o fluxo diário e limpeza, a pasta deve ficar assim:

```text
data/personal_trade_auditor/GOLD/
├── daily/
│   └── 2026-07-01/
│       ├── summary.json
│       └── web_decision_payload.json
└── latest/
    ├── summary.json
    └── web_decision_payload.json
```

A pasta `daily` guarda evolução histórica.

A pasta `latest` é usada para o fluxo rápido de análise com ChatGPT/Web.

---

## 11.6 Fluxo diário recomendado

### Passo 1 — Rodar auditor principal

```powershell
python .\tools\personal_trade_auditor.py `
  --symbol GOLD `
  --mt5-symbol XAUUSD `
  --data-symbol GOLD `
  --from-date 2026-07-01 `
  --to-date 2026-07-01 `
  --mt5-config .\config\personal_mt5.local.json
```

### Passo 2 — Rodar execution audit

```powershell
python .\tools\personal_trade_execution_audit.py `
  --symbol GOLD `
  --data-symbol GOLD
```

### Passo 3 — Rodar builder diário

```powershell
python .\tools\personal_risk_guard_builder.py `
  --symbol GOLD `
  --data-symbol GOLD
```

### Passo 4 — Limpar arquivos temporários da raiz

Em alguns PowerShell, `Remove-Item -File` pode não existir. Use o comando compatível:

```powershell
Get-ChildItem .\data\personal_trade_auditor\GOLD\personal_trade_* | Remove-Item -Force
```

Conferir resultado:

```powershell
Get-ChildItem .\data\personal_trade_auditor\GOLD
```

Ou:

```powershell
tree .\data\personal_trade_auditor\GOLD /F
```

O esperado é sobrar somente:

```text
daily
latest
```

---

## 11.7 Como usar o JSON no ChatGPT/Web

Arquivo para colar:

```text
data/personal_trade_auditor/GOLD/latest/web_decision_payload.json
```

Pedido sugerido:

```text
Mestre, analisa esse JSON e responda:
- Pontos-chave
- Suporte e resistência
- Rompimento ou consolidação
- Compra liberada ou blocked
- Venda liberada ou blocked
- Cenários de compra
- Cenários de venda
- Invalidação
- Alertas pessoais
```

O JSON inclui:

- contexto de mercado;
- payload intraday, se existir;
- contexto Chronos, se existir;
- regras pessoais;
- Personal Risk Guard;
- auditoria do dia;
- MFE/MAE;
- exemplos recentes de trades;
- restrições para a resposta.

Regra de resposta esperada:

```text
Se M5 bloquear, responder Trade Blocked.
Não perseguir rompimento sem confirmação.
Não tratar falso rompimento como erro sozinho.
Separar entrada a mercado de pullback/confirmação.
Não dar garantia de lucro.
```

---

## 11.8 Comparação dia a dia

Cada dia fica em:

```text
data/personal_trade_auditor/GOLD/daily/YYYY-MM-DD/summary.json
```

Exemplo:

```text
data/personal_trade_auditor/GOLD/daily/2026-07-01/summary.json
data/personal_trade_auditor/GOLD/daily/2026-07-02/summary.json
data/personal_trade_auditor/GOLD/daily/2026-07-03/summary.json
```

Esses arquivos permitem acompanhar:

- total de trades;
- wins;
- losses;
- win rate;
- net profit;
- profit factor;
- erros dominantes;
- hard blocks violados;
- MFE médio;
- MAE médio;
- saída cedo;
- stop/saída ruim;
- evolução do Personal Risk Guard.

Objetivo:

```text
Não apenas saber se ganhou ou perdeu,
mas entender se a execução está ficando mais disciplinada.
```

---

## 12. Diagnóstico MT5

Script:

```text
tools/mt5_history_diagnostic.py
```

Uso quando o auditor não encontra trades, ou quando é necessário verificar datas, símbolos e deals.

Exemplo:

```powershell
python .\tools\mt5_history_diagnostic.py `
  --from-date 2026-07-01 `
  --to-date 2026-07-01 `
  --mt5-config .\config\personal_mt5.local.json
```

Cuidados:

- nunca publicar login real;
- nunca publicar senha;
- nunca versionar configuração local;
- revisar nomes reais de servidor antes de compartilhar logs.

---

## 13. Segurança e privacidade

Arquivos que não devem ser versionados:

```text
config/personal_mt5.local.json
*.local.json
.env
```

Não compartilhar:

- login MT5;
- senha;
- servidor real;
- token de API;
- path local com informações sensíveis;
- prints com dados de conta.

Preferir:

```text
password_env
variáveis de ambiente
arquivos .local.json ignorados pelo Git
```

Exemplo:

```powershell
$env:MT5_PASSWORD="sua_senha"
```

---

## 14. Prompt oficial

Arquivo:

```text
prompts/promptIntraday.md
```

O prompt deve:

- priorizar H1, M15 e M5;
- usar H4 como regime;
- usar M1 como timing;
- respeitar Historical Intelligence;
- respeitar Market Chronos;
- respeitar Breakout Quality;
- respeitar Personal Risk Guard;
- não expor fórmula proprietária em excesso;
- não inventar probabilidades;
- usar `WAIT` como fallback seguro.

Formato preferido de resposta:

```text
1. Pontos-chave
2. Pontos de atenção
3. Resumo por timeframe
4. Ação Imediata
5. Ação Mais Recomendada Agora
```

Para análise operacional via JSON Web:

```text
Pontos-chave
Suporte/Resistência
Rompimento ou Consolidação
Trade Liberado/Blocked
Cenários de Compra
Cenários de Venda
Invalidation
Alertas Pessoais
```

---

## 15. Limitações

O TradingAgent:

- não garante resultado;
- não executa ordens automaticamente;
- não substitui gerenciamento de risco;
- não elimina slippage, spread ou erro humano;
- não transforma backtest em garantia futura;
- não deve liberar trades que violem hard blocks;
- depende da qualidade dos dados do MT5;
- depende da atualização correta dos Parquets e payloads;
- depende da interpretação correta de barra live versus barra fechada.

Pontos críticos:

```text
barra live pode mudar
rompimento pode falhar
falso rompimento pode exigir stop mais amplo
M5 pode liberar, mas não é gatilho automático
M1 pode dar gatilho, mas sem região não há edge claro
```

---

## 16. Roadmap prático

Prioridades próximas:

```text
1. Fundir MFE/MAE no personal_trade_auditor.py
2. Criar modo único de auditoria diária
3. Adicionar limpeza automática dos temporários
4. Criar comparador de evolução diária
5. Gerar dashboard simples de disciplina
6. Criar bloco de Personal Risk Guard dentro do payload intraday
7. Criar alerta visual de Trade Liberado/Blocked
```

Ideia futura de comando único:

```powershell
python .\tools\personal_trade_auditor.py `
  --symbol GOLD `
  --mt5-symbol XAUUSD `
  --data-symbol GOLD `
  --from-date 2026-07-01 `
  --to-date 2026-07-01 `
  --mt5-config .\config\personal_mt5.local.json `
  --daily-report `
  --cleanup-root
```

Objetivo final:

```text
um auditor forte
poucos arquivos
comparação dia a dia
JSON pronto para análise Web
bloqueios pessoais claros
menos repetição de erro
mais disciplina operacional
```
