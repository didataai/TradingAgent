# TradingAgent

> **FINALIDADE**  
> Documentar de forma completa a arquitetura, configuração, execução, pesquisa quantitativa, Market Intelligence, Market Chronos, Breakout Quality, integração com LLM, auditoria, segurança, limitações e roadmap do TradingAgent.
>
> **ENTRADAS**  
> Configuração em `tradingagent.json`, candles do MetaTrader 5, prompts Markdown, arquivos Parquet e artefatos JSON/CSV produzidos pelos pipelines.
>
> **PROCESSAMENTO PRINCIPAL**  
> MT5 → engenharia de features → contexto multi-timeframe → payload factual → Market Chronos → Breakout Quality → Market Intelligence → prompt final → LLM → validação → persistência e auditoria.
>
> **SAÍDAS**  
> Parquets, consolidados, contexto, payload factual, estado Chronos, inteligência Chronos, score de qualidade de rompimento, input exato da LLM, resposta bruta, resultado estruturado, logs, manifestos e relatórios estatísticos.
>
> **ESTADO DO PROJETO**  
> Pesquisa e apoio à decisão. Não executa ordens automaticamente e não deve ser tratado como garantia de resultado.

---

## 1. Visão geral

O **TradingAgent** é uma plataforma quantitativa e orientada a agentes para análise de mercado, inicialmente focada em:

- intraday e scalping;
- swing trade;
- múltiplos ativos;
- múltiplos timeframes;
- integração com MetaTrader 5;
- engenharia de features técnicas e estruturais;
- inteligência histórica baseada em dados;
- classificação de contexto de mercado;
- avaliação da qualidade de rompimentos;
- execução local com Ollama;
- execução via API externa;
- auditoria completa do que foi enviado e recebido da LLM.

Princípio central:

```text
Python coleta, calcula, classifica e organiza fatos
→ componentes quantitativos geram contexto e restrições
→ o prompt define como a LLM deve interpretar os dados
→ a LLM produz BUY, SELL ou WAIT
→ toda decisão permanece auditável
```

O projeto separa três camadas:

```text
1. Dados e features
2. Inteligência quantitativa e guards
3. Interpretação final pela LLM
```

A LLM não deve inventar dados, probabilidades, backtests, notícias, DXY, sentimento ou estatísticas que não estejam presentes no payload.

---

## 2. Estado atual validado

O fluxo intraday atual está funcional de ponta a ponta:

```text
MetaTrader 5
→ Base_Dados.py
→ Parquets por timeframe
→ consolidado intraday
→ timeframe_context.py
→ prompt_payload.py
→ market_chronos_runtime.py
→ chronos_payload_bridge.py
→ market_intelligence.py enrich
→ web_input_agent.py ou intraday_agent.py
→ LLM
→ resultado estruturado
→ persistência e auditoria
```

Componentes atualmente disponíveis:

- coleta MT5 de M1, M5, M15, H1, H4, D1, W1 e MN1;
- aproximadamente 212 colunas por timeframe;
- consolidação em Parquet com compressão Zstandard;
- contexto multi-timeframe;
- payload factual schema `2.1`;
- fluxo intraday e swing independentes;
- Market Intelligence;
- Market Chronos Runtime;
- Market Laws Registry;
- Chronos Payload Bridge;
- Breakout Quality Score de `-5` a `+5`;
- faixas operacionais `LOW`, `VALID`, `PREMIUM` e `UNAVAILABLE`;
- proteção contra dados desatualizados;
- validação estatística por score, lado, horizonte e bloco temporal;
- integração do score ao payload da LLM;
- prompt com regras explícitas para Breakout Quality;
- execução local ou via input Web;
- auditoria do prompt final;
- auditoria da resposta bruta;
- locks, timeouts, manifestos e logs.

---

## 3. Princípios de arquitetura

### 3.1 Separação entre fatos, inteligência e decisão

O payload factual contém dados observáveis e derivados:

- OHLC;
- volume;
- indicadores;
- eventos;
- níveis;
- estrutura;
- volatilidade;
- padrões candidatos;
- estado de barra;
- regiões e referências.

A camada quantitativa adiciona:

- guards;
- bloqueios;
- contexto histórico;
- qualidade de rompimento;
- freshness;
- leis correspondentes;
- classificação operacional.

A LLM recebe esses blocos como restrições e contexto, mas continua responsável pela redação e decisão final dentro das regras do prompt.

### 3.2 Intraday e swing independentes

Intraday:

```text
H4, H1, M15, M5, M1
```

Prioridade:

```text
H1 = viés tático
M15 = setup
M5 = gatilho
H4 = regime superior
M1 = refinamento de timing
```

Swing:

```text
H4, D1, W1, MN1
```

O swing não deve contaminar automaticamente o intraday. Quando usado, entra apenas como contexto superior explicitamente identificado.

### 3.3 Barra live versus barra fechada

Estados relevantes:

- `LIVE`: barra em formação;
- `CLOSED`: barra encerrada;
- `STALE_LAST_BAR`: última barra não atualizada recentemente;
- `is_live_bar=true`: valores ainda podem mudar.

A barra live serve para:

- timing;
- ritmo;
- volume pace;
- projeção de volume;
- posição dentro do range;
- antecipação controlada.

A barra fechada tem maior peso para confirmação.

### 3.4 Candidatos algorítmicos são hipóteses

Exemplos:

```text
BULL_FLAG
BEAR_FLAG
DOUBLE_TOP
DOUBLE_BOTTOM
ASCENDING_TRIANGLE
DESCENDING_TRIANGLE
SYMMETRICAL_TRIANGLE
ASCENDING_CHANNEL
DESCENDING_CHANNEL
```

Regras:

```text
algorithmic_score != probabilidade
candidate != confirmação
candidate != recomendação
```

A LLM deve cruzar o candidato com:

- estrutura;
- candles recentes;
- volume;
- volatilidade;
- pivôs;
- rompimento;
- aceitação;
- fechamento;
- invalidação;
- alinhamento multi-timeframe.

### 3.5 Freshness é obrigatório

O Chronos calcula a idade do último candle utilizado.

Exemplo:

```json
{
  "status": "FRESH",
  "age_minutes": 4.2,
  "max_age_minutes": 30
}
```

Quando o estado estiver desatualizado:

```json
{
  "available": false,
  "chronos_action": "UNAVAILABLE_STALE",
  "operational_band": "UNAVAILABLE",
  "reason": "STALE_DATA"
}
```

O score observado pode ser mantido apenas para diagnóstico:

```json
{
  "observed_score": 1,
  "observed_band": "LOW"
}
```

Esses campos não podem confirmar, bloquear ou inverter uma ação.

---

## 4. Estrutura do projeto

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
│   └── outros utilitários quantitativos
│
└── data/
    ├── <SYMBOL>_M1.parquet
    ├── <SYMBOL>_M5.parquet
    ├── <SYMBOL>_M15.parquet
    ├── <SYMBOL>_H1.parquet
    ├── <SYMBOL>_H4.parquet
    ├── <SYMBOL>_D1.parquet
    ├── <SYMBOL>_W1.parquet
    ├── <SYMBOL>_MN1.parquet
    ├── consolidated/
    ├── context/
    ├── payload/
    ├── intelligence/
    ├── market_chronos/
    ├── agent_results/
    ├── agent_runs/
    ├── pipeline_results/
    ├── pipeline_runs/
    ├── debug_llm/
    ├── state/
    ├── locks/
    ├── logs/
    └── manifests/
```

---

## 5. Responsabilidade dos componentes

### 5.1 `Base_Dados.py`

Responsável por:

- carregar a configuração;
- conectar ao MT5;
- coletar candles;
- normalizar timestamps;
- detectar timezone do broker;
- marcar barra live;
- calcular indicadores;
- calcular estrutura causal;
- calcular volume e ritmo;
- detectar eventos;
- gerar Parquets individuais;
- gerar consolidado;
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
- sessões e kill zones;
- volume relativo;
- volume pace;
- volume projetado;
- compressão e expansão;
- corpo, pavios e posição do fechamento;
- geometria de padrões.

### 5.2 `context/timeframe_context.py`

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
- organizar níveis;
- organizar candles recentes;
- organizar candidatos de padrões;
- produzir trace multi-timeframe;
- manter dados para auditoria.

### 5.3 `context/prompt_payload.py`

Entrada:

- consolidado intraday;
- contexto intraday;
- valores exatos mais recentes.

Saída:

```text
data/payload/<SYMBOL>_intraday_payload.json
```

Schema atual:

```text
2.1
```

Tipo:

```text
FACTUAL_INTRADAY_MARKET_DATA
```

Conteúdo principal:

- preço atual;
- estado do mercado;
- H4, H1, M15, M5 e M1;
- candle atual e anterior;
- indicadores;
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

### 5.4 `tools/market_chronos_runtime.py`

Responsável por:

- ler dados live ou base de laboratório;
- fundir timeframes por `merge_asof`;
- reconstruir features do Chronos;
- extrair o estado mais recente;
- avaliar freshness;
- aplicar Market Laws Registry;
- produzir estado e inteligência Chronos.

Saídas padrão:

```text
data/context/<SYMBOL>_chronos_state.json
data/context/<SYMBOL>_chronos_intelligence.json
```

Campos importantes:

- `chronos_action`;
- `supporting_side`;
- `blocked_actions`;
- `matched_laws`;
- `matched_count`;
- `confidence`;
- `current_segments`;
- `freshness`.

### 5.5 `tools/chronos_payload_bridge.py`

Responsável por:

- ler o payload intraday;
- ler a inteligência Chronos;
- localizar automaticamente o estado Chronos;
- calcular Breakout Quality no runtime;
- compactar a inteligência;
- anexar tudo ao payload final;
- invalidar operacionalmente o score quando o dado estiver stale.

Bloco gerado:

```json
{
  "chronos_intelligence": {
    "available": true,
    "freshness": {"status": "FRESH"},
    "chronos_action": "NO_MATCH",
    "breakout_quality_score": 4,
    "operational_band": "PREMIUM",
    "score_displacement": 1,
    "score_participation": 1,
    "score_momentum": 1,
    "score_location": 1,
    "score_trend": 0
  }
}
```

### 5.6 `market_intelligence.py`

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

O guard formal da Historical Intelligence permanece a restrição principal da ação imediata.

### 5.7 `agent/web_input_agent.py`

Responsável por:

- ler o prompt oficial;
- ler o payload enriquecido;
- montar o input completo;
- salvar o input exato para uso via Web;
- não chamar a LLM automaticamente.

Saída:

```text
data/debug_llm/<SYMBOL>_<ANALYST>_latest_input.txt
```

### 5.8 `agent/intraday_agent.py`

Responsável por:

- selecionar perfil e analista;
- montar prompt final;
- chamar provedor configurado;
- salvar resposta bruta;
- extrair JSON;
- validar schema;
- aplicar fallback seguro;
- persistir resultado e histórico.

### 5.9 `pipeline/intraday_pipeline_web.py`

Pipeline principal do fluxo via Web.

Etapas:

```text
base_dados
→ timeframe_context
→ prompt_payload
→ chronos_runtime
→ chronos_payload_bridge
→ market_intelligence_enrich
→ web_input_agent
```

Também controla:

- lock;
- timeout por etapa;
- logs;
- falha por símbolo;
- resultado consolidado;
- execução opcional sem Chronos;
- execução opcional sem Market Intelligence.

---

## 6. Market Chronos

O **Market Chronos** representa a camada de memória e contexto histórico do mercado.

Objetivos:

- detectar estados recorrentes;
- identificar tentativas em níveis;
- acompanhar falhas e memória recente;
- reconhecer regimes de sequência;
- aplicar leis de mercado validadas;
- produzir apoio, neutralidade ou bloqueio.

Exemplos de estado:

- energia;
- alinhamento multi-timeframe;
- viés HTF;
- proximidade de nível;
- direção do rompimento;
- quantidade de tentativas;
- falhas recentes;
- tempo desde sweep;
- tempo desde falso rompimento;
- regime de sequência.

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

### 7.1 Objetivo

Classificar a qualidade contextual de um rompimento antes de tratá-lo como oportunidade operacional.

A hipótese central é:

> O edge não está apenas no desenho do rompimento, mas na combinação de deslocamento, participação, momentum, localização e tendência.

### 7.2 Escala

```text
-5 a +5
```

Cada família contribui com:

```text
-1 = conflitante
 0 = neutra ou inconclusiva
+1 = alinhada
```

### 7.3 Famílias

#### Displacement

Mede a força física do candle:

- `body_atr`;
- `range_atr`.

#### Participation

Mede participação relativa:

- `vol_ratio`;
- `vol_spike_1p5`;
- bucket de volume.

#### Momentum

Mede continuidade e estrutura direcional:

- RSI contextual;
- direção;
- BOS/CHOCH;
- evento de rompimento.

#### Location

Mede a posição do preço:

- distância da EMA20;
- distância dos extremos Donchian;
- alinhamento de localização;
- viés HTF.

#### Trend

Mede alinhamento tendencial:

- inclinação EMA20;
- inclinação EMA50;
- viés MTF;
- alinhamento MTF.

### 7.4 Magnitude simétrica

Magnitude é simétrica para rompimentos UP e DOWN:

```text
body_atr alto favorece força
range_atr alto favorece força
vol_ratio alto favorece participação
```

A direção é tratada apenas nas famílias contextuais.

### 7.5 Faixas operacionais

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

### 7.6 Exemplo de payload

```json
{
  "breakout_quality": {
    "available": true,
    "applicable": true,
    "side": "DOWN",
    "breakout_quality_score": 4,
    "score_max": 5,
    "operational_band": "PREMIUM",
    "known_families": 5,
    "families": {
      "displacement": {"score": 1, "status": "ALIGNED"},
      "participation": {"score": 1, "status": "ALIGNED"},
      "momentum": {"score": 1, "status": "ALIGNED"},
      "location": {"score": 1, "status": "ALIGNED"},
      "trend": {"score": 0, "status": "NEUTRAL"}
    }
  }
}
```

---

## 8. Pesquisa e validação do Breakout Quality

Script canônico:

```text
tools/chronos_breakout_quality_score.py
```

Versão atual:

```text
2.1-operational-bands
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

Arquivos:

```text
breakout_quality_events.parquet
breakout_quality_summary.csv
breakout_quality_blocks.csv
breakout_quality_stability.csv
breakout_operational_summary.csv
breakout_operational_stability.csv
metadata.json
```

Métricas calculadas:

- quantidade de eventos;
- success rate;
- retorno médio em ATR;
- retorno mediano em ATR;
- MFE médio;
- MAE médio;
- ganho médio;
- perda média;
- payoff ratio;
- profit factor;
- estabilidade em cinco blocos cronológicos.

Resultado observado no GOLD, M5 PREMIUM:

```text
aproximadamente 71% de sucesso
aproximadamente 0,64 a 0,71 ATR de retorno médio
profit factor aproximado de 2,55 a 2,65
5 de 5 blocos temporais positivos
```

Esses números representam pesquisa histórica e não garantem desempenho futuro.

Interpretação prática:

- 71% de sucesso: aproximadamente 71 eventos favoráveis em 100 conforme a definição usada;
- 0,64 a 0,71 ATR: movimento médio proporcional à volatilidade;
- PF 2,55 a 2,65: cerca de 2,55 a 2,65 unidades de ganho bruto por unidade de perda bruta;
- 5/5 blocos positivos: resultado distribuído no tempo, não concentrado em um único período.

Antes de qualquer execução automática ainda são necessários:

- custos;
- spread;
- slippage;
- regras reais de entrada e saída;
- stop e take profit;
- drawdown;
- sequência de perdas;
- holdout estrito;
- teste fora da amostra;
- conta demo.

---

## 9. Hierarquia decisória da LLM

A ordem correta é:

```text
1. Historical Intelligence formal guard
2. Freshness e disponibilidade
3. blocked_reasons e blocked_actions
4. Chronos Laws
5. Breakout Quality
6. Confirmação H1/M15/M5
7. Entrada, stop, alvo e invalidação
```

Regras principais:

- `WAIT` do guard principal permanece `WAIT`;
- `PREMIUM` não libera uma ação bloqueada;
- `LOW` não cria sinal oposto;
- `UNAVAILABLE` é ignorado operacionalmente;
- divergência entre lado do score e ação permitida reduz confiança;
- na dúvida, escolher `WAIT`.

---

## 10. Prompt oficial

Arquivo:

```text
prompts/promptIntraday.md
```

O prompt atual:

- define as cinco seções de saída;
- prioriza H1, M15 e M5;
- usa H4 como regime;
- usa M1 como timing;
- contém regras da Historical Intelligence;
- contém regras do Market Chronos;
- contém regras do Breakout Quality;
- trata `LOW`, `VALID`, `PREMIUM` e `UNAVAILABLE`;
- impede exposição da fórmula proprietária;
- impede probabilidades inventadas;
- usa `WAIT` como fallback seguro.

Saída esperada:

1. Pontos-chave;
2. Pontos de atenção;
3. Resumo por timeframe;
4. Ação Imediata;
5. Ação Mais Recomendada Agora.

---

## 11. Execução

### 11.1 Pipeline Web completo

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1
```

### 11.2 Pipeline padrão com chamada de LLM

```powershell
python pipeline/intraday_pipeline.py `
  --symbol GOLD `
  --agent-mode single `
  --analyst analyst_1
```

### 11.3 Apenas coleta intraday

```powershell
python Base_Dados.py `
  --mode intraday_refresh `
  --symbol GOLD
```

### 11.4 Apenas contexto

```powershell
python context/timeframe_context.py `
  --symbol GOLD
```

### 11.5 Apenas payload

```powershell
python context/prompt_payload.py `
  --symbol GOLD
```

### 11.6 Apenas Chronos Runtime

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

### 11.7 Apenas bridge

```powershell
python tools/chronos_payload_bridge.py `
  --payload data/payload/GOLD_intraday_payload.json `
  --chronos data/context/GOLD_chronos_intelligence.json `
  --output data/payload/GOLD_intraday_payload.json
```

### 11.8 Gerar input Web

```powershell
python agent/web_input_agent.py `
  --symbol GOLD `
  --analyst analyst_1
```

---

## 12. Fluxo completo de arquivos

```text
MT5
  ↓
data/GOLD_M1.parquet
data/GOLD_M5.parquet
data/GOLD_M15.parquet
data/GOLD_H1.parquet
data/GOLD_H4.parquet
  ↓
data/consolidated/GOLD_intraday.parquet
  ↓
data/context/GOLD_intraday_context.json
  ↓
data/payload/GOLD_intraday_payload.json
  ↓
data/context/GOLD_chronos_state.json
data/context/GOLD_chronos_intelligence.json
  ↓
chronos_payload_bridge.py
  ↓
market_intelligence.py enrich
  ↓
data/payload/GOLD_intraday_payload.json
  ↓
prompts/promptIntraday.md + MARKET_DATA
  ↓
data/debug_llm/GOLD_analyst_1_latest_input.txt
  ↓
LLM ou análise via Web
```

---

## 13. Tamanho atual do input da LLM

Medição observada no fluxo completo:

```text
aproximadamente 119.000 caracteres
aproximadamente 3.500 valores finais
aproximadamente 29.000 a 33.000 tokens
```

Principais responsáveis pelo volume:

```text
timeframes completos
historical_intelligence
candles recentes
níveis e geometria
indicadores e métricas derivadas
```

O Breakout Quality representa uma parcela pequena do payload.

A compactação não é obrigatória no fluxo Web atual, mas poderá ser implementada futuramente para:

- reduzir custo de API;
- reduzir latência;
- executar vários símbolos;
- suportar modelos com contexto menor.

---

## 14. Configuração

Arquivo:

```text
tradingagent.json
```

Principais seções:

- `project`;
- `mt5`;
- `data`;
- `universe`;
- `features`;
- `labels`;
- `pipeline_modes`;
- `llm`;
- `agent`;
- `memory`;
- `observability`;
- `pipeline_intraday`.

Universo padrão:

```text
GOLD
EURUSD
GBPUSD
Brent
UsaInd
```

Modos de dados:

### `full_rebuild`

```text
M1, M5, M15, H1, H4, D1, W1, MN1
labels habilitados
```

### `intraday_refresh`

```text
M1, M5, M15, H1, H4
sem labels futuros
```

### `daily_refresh`

```text
H4, D1, W1, MN1
```

### `contexts_only`

Recria contextos sem nova coleta MT5.

---

## 15. Volume e volatilidade

O volume disponível é:

```text
MT5_TICK_VOLUME
```

Ele permite inferir:

- participação relativa;
- aumento ou redução de atividade;
- confirmação aproximada;
- exaustão;
- ritmo da barra;
- distorção em fechamento;
- expansão e compressão.

Ele não representa:

- delta real;
- footprint;
- agressão bid/ask de bolsa;
- livro de ofertas completo;
- fluxo institucional confirmado.

Campos principais:

```text
tick_volume
volume_ratio
volume_pace_ratio
projected_final_volume
projected_volume_ratio_20
expected_volume_at_elapsed
Volume_Spike
vol_spike_1p5
vol_spike_2p0
```

A interpretação deve cruzar volume com:

- direção;
- corpo;
- pavios;
- posição de fechamento;
- estrutura;
- rompimento;
- sequência de candles;
- horário e sessão.

---

## 16. Auditoria e observabilidade

Arquivos `latest`:

```text
data/debug_llm/<SYMBOL>_<ANALYST>_latest_input.txt
data/debug_llm/<SYMBOL>_<ANALYST>_latest_raw_response.txt
```

Eles permitem auditar:

- prompt exato;
- payload exato;
- regras aplicadas;
- resposta bruta;
- divergência entre ação e justificativa.

Outros artefatos:

```text
data/pipeline_results/
data/pipeline_runs/
data/agent_results/
data/agent_runs/
data/logs/
data/manifests/
data/state/
```

O pipeline registra:

- `run_id`;
- duração;
- return code;
- sucesso/falha;
- timeout;
- símbolo;
- etapa;
- caminho de saída.

---

## 17. Validação e inspeção

### Validar configuração JSON

```powershell
python -c "import json; json.load(open('tradingagent.json', encoding='utf-8')); print('JSON OK')"
```

### Abrir input da LLM

```powershell
notepad .\data\debug_llm\GOLD_analyst_1_latest_input.txt
```

### Inspecionar Breakout Quality

```powershell
$payload = Get-Content `
  .\data\payload\GOLD_intraday_payload.json `
  -Raw | ConvertFrom-Json

$payload.chronos_intelligence.breakout_quality |
  ConvertTo-Json -Depth 10
```

### Resumo compacto

```powershell
$q = $payload.chronos_intelligence.breakout_quality

[PSCustomObject]@{
  Available      = $q.available
  Side           = $q.side
  Score          = "$($q.breakout_quality_score)/$($q.score_max)"
  Classification = $q.operational_band
  Displacement   = $q.families.displacement.status
  Participation  = $q.families.participation.status
  Momentum       = $q.families.momentum.status
  Location       = $q.families.location.status
  Trend          = $q.families.trend.status
} | Format-List
```

### Resumo operacional histórico

```powershell
Import-Csv `
  .\data\market_chronos\GOLD\breakout_quality_score\breakout_operational_summary.csv |
  Format-Table -AutoSize
```

### Estabilidade

```powershell
Import-Csv `
  .\data\market_chronos\GOLD\breakout_quality_score\breakout_operational_stability.csv |
  Format-Table -AutoSize
```

---

## 18. Segurança

Nunca versionar:

- senha do MT5;
- conta real;
- token;
- chave de API;
- credencial de broker;
- payload operacional real;
- input real da LLM;
- resposta bruta;
- Parquets;
- logs;
- estado operacional.

Use:

```text
.env
variáveis de ambiente
tradingagent.local.json
.gitignore
```

Configuração recomendada:

```json
{
  "mt5": {
    "account_env": "MT5_ACCOUNT",
    "password_env": "MT5_PASSWORD",
    "server_env": "MT5_SERVER"
  }
}
```

Atenção: qualquer credencial já exposta no histórico do Git deve ser considerada comprometida e deve ser rotacionada.

`.gitignore` recomendado:

```gitignore
.venv/
__pycache__/
*.pyc
.env
tradingagent.local.json

data/*.parquet
data/consolidated/
data/context/
data/payload/
data/intelligence/
data/market_chronos/
data/agent_results/
data/agent_runs/
data/pipeline_results/
data/pipeline_runs/
data/state/
data/debug_llm/
data/locks/
data/logs/
data/manifests/
```

---

## 19. Troubleshooting

### `STALE_DATA`

Sintomas:

```text
available=false
chronos_action=UNAVAILABLE_STALE
operational_band=UNAVAILABLE
```

Verifique:

- se o mercado está aberto;
- se o MT5 está conectado;
- se o símbolo está atualizando;
- se o timezone está correto;
- se o último candle M5 é recente;
- se `max_age_minutes` é adequado.

Não aumente o limite apenas para esconder um feed parado.

### `Unexpected UTF-8 BOM`

```powershell
$content = Get-Content .\tradingagent.json -Raw -Encoding UTF8

[System.IO.File]::WriteAllText(
  (Resolve-Path .\tradingagent.json),
  $content,
  (New-Object System.Text.UTF8Encoding($false))
)
```

### Prompt não encontrado

```powershell
Test-Path .\prompts\promptIntraday.md
```

### Lock preso

Verifique:

```text
data/locks/intraday_pipeline.lock
```

Só remova manualmente após confirmar que não existe execução ativa.

### Resposta contraditória

Compare:

```text
data/debug_llm/<SYMBOL>_<ANALYST>_latest_input.txt
data/debug_llm/<SYMBOL>_<ANALYST>_latest_raw_response.txt
```

E revise:

- guard formal;
- freshness;
- blocked reasons;
- blocked actions;
- Chronos;
- Breakout Quality;
- M15 e M5;
- níveis e invalidação.

---

## 20. Roadmap

Próximos passos recomendados:

1. validar Breakout Quality em holdout estrito 60/20/20;
2. congelar thresholds aprendidos apenas no treino;
3. adicionar spread, slippage e custo;
4. testar regras reais de stop e take profit;
5. medir drawdown e sequência de perdas;
6. validar por sessão e horário;
7. comparar GOLD, EURUSD, GBPUSD, Brent e UsaInd;
8. adicionar alertas para entrada em região preferencial;
9. criar observabilidade em Grafana/Elasticsearch;
10. comparar modelos locais e APIs;
11. criar modo compacto de payload;
12. criar dataset versionado de input, resposta e resultado futuro;
13. implementar agente crítico;
14. implementar agente de risco;
15. integrar calendário econômico e contexto macro;
16. manter execução automática desabilitada até validação robusta.

---

## 21. Limitações

O projeto ainda não garante:

- execução perfeita;
- ausência de slippage;
- robustez em todos os regimes;
- generalização para todos os ativos;
- qualidade idêntica entre modelos;
- interpretação perfeita de payload extenso;
- retorno futuro semelhante ao histórico.

A pesquisa atual mede comportamento histórico e qualidade contextual. Ela não substitui:

- gerenciamento de risco;
- supervisão humana;
- conta demo;
- validação fora da amostra;
- controle de exposição;
- kill switch;
- observabilidade;
- governança.

---

## 22. Aviso

Este projeto é destinado a pesquisa, automação e apoio à análise de mercado.

Não habilitar execução automática antes de:

- validação histórica;
- holdout;
- teste fora da amostra;
- custos e slippage;
- teste em conta demo;
- limites de risco;
- tratamento de falhas;
- kill switch;
- observabilidade;
- supervisão humana.

---

## 23. Licença

Definir antes de distribuição pública.

Possibilidades:

- MIT;
- Apache-2.0;
- licença privada durante o desenvolvimento.
