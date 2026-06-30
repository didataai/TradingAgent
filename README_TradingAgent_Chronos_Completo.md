# TradingAgent + Market Chronos

> **Estado documentado:** 30 de junho de 2026  
> **Ativo principal validado:** `GOLD`  
> **Pipeline intraday principal:** `pipeline/intraday_pipeline_web.py`  
> **Anchor timeframe do Chronos runtime:** `M5`  
> **Objetivo:** coletar dados reais do MetaTrader 5, construir contexto técnico multi-timeframe, aplicar inteligência quantitativa e histórica, e produzir uma entrada auditável para análise por LLM local ou via ChatGPT Web.

---

## 1. Visão geral

O TradingAgent é uma plataforma de análise quantitativa e assistida por LLM para:

- intraday;
- scalping;
- swing;
- múltiplos ativos;
- múltiplos timeframes;
- coleta via MetaTrader 5;
- engenharia de features;
- inteligência quantitativa;
- memória histórica por leis de mercado;
- execução com LLM local;
- geração de input para uso via Web;
- auditoria completa do que foi enviado à LLM.

O projeto segue três princípios:

```text
Python coleta, calcula e organiza fatos.
A inteligência quantitativa restringe decisões.
A LLM interpreta e comunica a leitura final.
```

No Market Chronos:

```text
Indicadores medem.
Dados ensinam.
Leis decidem.
```

O objetivo não é gerar mais operações. O objetivo é evitar operações ruins e selecionar menos operações, porém melhores.

---

## 2. Estado atual validado

O fluxo intraday foi validado de ponta a ponta com:

- coleta live do MT5;
- M1, M5, M15, H1 e H4;
- aproximadamente 212 colunas por timeframe;
- consolidado intraday;
- contexto multi-timeframe;
- payload factual schema `2.1`;
- Market Intelligence;
- Market Chronos runtime;
- bridge do Chronos para o payload;
- prompt oficial com regras do Chronos;
- modo Web sem chamada à LLM local;
- modo local com Ollama;
- auditoria do input exato;
- lock, timeout, logs e resultado do pipeline.

Execução validada:

```text
source_mode=live
freshness=FRESH
chronos_payload_bridge.available=true
web_input_agent.llm_called=false
input final ≈ 119 mil caracteres
pipeline success=true
```

`matched_laws=0` e `chronos_action=NO_MATCH` são respostas válidas. Significam que o estado atual não ativou nenhuma lei histórica; não significam erro.

---

## 3. Arquitetura atual

### 3.1 Fluxo intraday completo

```text
MetaTrader 5
  ↓
Base_Dados.py --mode intraday_refresh
  ↓
data/<ATIVO>_M1.parquet
data/<ATIVO>_M5.parquet
data/<ATIVO>_M15.parquet
data/<ATIVO>_H1.parquet
data/<ATIVO>_H4.parquet
  ↓
data/consolidated/<ATIVO>_intraday.parquet
  ↓
context/timeframe_context.py
  ↓
data/context/<ATIVO>_intraday_context.json
  ↓
context/prompt_payload.py
  ↓
data/payload/<ATIVO>_intraday_payload.json
  ↓
tools/market_chronos_runtime.py
  ↓
data/context/<ATIVO>_chronos_state.json
data/context/<ATIVO>_chronos_intelligence.json
  ↓
tools/chronos_payload_bridge.py
  ↓
MARKET_DATA.chronos_intelligence
  ↓
market_intelligence.py enrich
  ↓
MARKET_DATA.historical_intelligence
  ↓
modo local: agent/intraday_agent.py → Ollama
ou
modo web: agent/web_input_agent.py → TXT para ChatGPT Web
```

### 3.2 Ordem real das etapas

A ordem atual do `intraday_pipeline_web.py` é:

1. `base_dados`
2. `timeframe_context`
3. `prompt_payload`
4. `chronos_runtime`
5. `chronos_payload_bridge`
6. `market_intelligence_enrich`
7. `intraday_agent` ou `web_input_agent`

Essa ordem é importante:

- o Chronos lê dados live atualizados;
- o bridge adiciona a inteligência do Chronos ao payload;
- o Market Intelligence adiciona o guard quantitativo;
- a LLM recebe os dois blocos no mesmo `MARKET_DATA`.

---

## 4. Estrutura de diretórios

```text
TradingAgent/
├── Base_Dados.py
├── market_intelligence.py
├── tradingagent.json
├── README.md
│
├── agent/
│   ├── intraday_agent.py
│   ├── web_input_agent.py
│   └── web_swing_input_agent.py
│
├── context/
│   ├── timeframe_context.py
│   ├── prompt_payload.py
│   ├── build_swing_consolidated.py
│   ├── swing_timeframe_context.py
│   └── swing_prompt_payload.py
│
├── pipeline/
│   ├── intraday_pipeline_web.py
│   └── swing_pipeline_web.py
│
├── prompts/
│   ├── promptIntraday.md
│   └── PromptPrevisaoSwing.md
│
├── tools/
│   ├── market_chronos_runtime.py
│   ├── chronos_payload_bridge.py
│   ├── market_chronos_engine_v10_1.py
│   ├── market_chronos_dataset.py
│   └── base_dados_candle.py
│
└── data/
    ├── <ATIVO>_M1.parquet
    ├── <ATIVO>_M5.parquet
    ├── <ATIVO>_M15.parquet
    ├── <ATIVO>_H1.parquet
    ├── <ATIVO>_H4.parquet
    ├── <ATIVO>_D1.parquet
    ├── <ATIVO>_W1.parquet
    ├── <ATIVO>_MN1.parquet
    │
    ├── consolidated/
    ├── context/
    ├── payload/
    ├── intelligence/
    ├── market_intelligence/
    ├── market_chronos/
    ├── agent_results/
    ├── agent_runs/
    ├── pipeline_results/
    ├── pipeline_runs/
    ├── state/
    ├── debug_llm/
    ├── locks/
    ├── logs/
    └── manifests/
```

---

## 5. Responsabilidade dos componentes

### 5.1 `Base_Dados.py`

Responsável por:

- carregar `tradingagent.json`;
- conectar ao MT5;
- detectar o broker;
- coletar candles;
- calcular timestamps;
- marcar barra live;
- calcular indicadores;
- calcular métricas derivadas;
- detectar eventos;
- gerar Parquets;
- gerar consolidado;
- gerar manifesto.

Timeframes intraday:

```text
M1, M5, M15, H1, H4
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
- BOS;
- CHOCH;
- sweeps;
- FVG;
- candidatos de Order Block;
- Fibonacci;
- sessões;
- kill zones;
- volume relativo;
- volume pace;
- volume projetado;
- compressão;
- expansão;
- corpo, pavios e posição do fechamento;
- geometria de padrões.

### 5.2 `context/timeframe_context.py`

Entrada:

```text
data/consolidated/<ATIVO>_intraday.parquet
```

Saída:

```text
data/context/<ATIVO>_intraday_context.json
```

Responsável por:

- organizar H4, H1, M15, M5 e M1;
- separar barra live e barra fechada;
- resumir níveis;
- resumir eventos;
- organizar candles recentes;
- construir contexto factual;
- produzir diagnóstico multi-timeframe.

### 5.3 `context/prompt_payload.py`

Saída:

```text
data/payload/<ATIVO>_intraday_payload.json
```

Schema:

```text
2.1
```

Tipo:

```text
FACTUAL_INTRADAY_MARKET_DATA
```

Inclui:

- preço atual;
- status do mercado;
- fontes;
- timeframes;
- candle atual;
- candle anterior fechado;
- indicadores;
- métricas derivadas;
- eventos;
- padrões;
- níveis;
- zonas próximas;
- Fibonacci;
- FVG;
- candidatos de Order Block;
- geometria;
- candles recentes;
- limitações e semântica.

### 5.4 `tools/market_chronos_runtime.py`

Responsável por:

- ler Parquets live;
- normalizar timestamp;
- fundir M5, M15, H1 e H4;
- limitar o warmup;
- chamar o engine Chronos;
- calcular freshness;
- gerar estado atual;
- consultar o registry de leis;
- gerar inteligência para o payload.

Comando validado:

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

Saídas:

```text
data/context/GOLD_chronos_state.json
data/context/GOLD_chronos_intelligence.json
```

### 5.5 `tools/chronos_payload_bridge.py`

Responsável por adicionar o resultado do Chronos ao payload:

```json
{
  "chronos_intelligence": {
    "available": true,
    "freshness": {
      "status": "FRESH"
    },
    "matched_count": 0,
    "chronos_action": "NO_MATCH"
  }
}
```

O bridge não deve apagar campos existentes do payload.

### 5.6 `market_intelligence.py enrich`

Responsável por adicionar:

```text
MARKET_DATA.historical_intelligence
```

Esse bloco contém o guard quantitativo principal, incluindo:

- direção por timeframe;
- confiabilidade;
- cobertura;
- expectativa em ATR;
- modo de entrada;
- alinhamento;
- razões de bloqueio;
- `formal_decision.final_action`.

Exemplo:

```text
H4: DOWN
H1: DOWN
M15: DOWN
M5: NOT_CONFIRMED
final_action: WAIT_M5_CONFIRMATION
```

### 5.7 `agent/intraday_agent.py`

Usado no modo LLM local.

Responsável por:

- carregar o prompt;
- carregar o payload;
- montar o input;
- salvar o input;
- chamar Ollama;
- salvar a resposta bruta;
- extrair JSON;
- validar schema;
- salvar resultado.

Configuração observada:

```text
provider=ollama_local
model=qwen2.5:7b-instruct
profile=quick
mode=single
```

### 5.8 `agent/web_input_agent.py`

Usado no modo Web.

Responsável por:

- carregar o mesmo prompt;
- carregar o mesmo payload;
- substituir `{{MARKET_DATA}}`;
- anexar schema de saída;
- salvar o TXT final;
- não chamar LLM.

Saída:

```text
data/debug_llm/<ATIVO>_<ANALISTA>_latest_input.txt
```

Log esperado:

```text
llm_called=False
```

---

## 6. Diferença entre modo local e modo Web

### 6.1 Modo Web

Comando:

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1
```

Comportamento:

```text
coleta dados
→ monta contexto
→ monta payload
→ roda Chronos
→ adiciona Market Intelligence
→ gera TXT
→ não chama Ollama
```

Log esperado:

```text
step=web_input_agent
llm_called=False
```

Arquivo:

```text
data\debug_llm\GOLD_analyst_1_latest_input.txt
```

Esse é o arquivo que deve ser enviado ao ChatGPT Web.

### 6.2 Modo LLM local

Comando:

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --analyst analyst_1
```

Comportamento:

```text
coleta dados
→ monta contexto
→ monta payload
→ roda Chronos
→ adiciona Market Intelligence
→ chama intraday_agent
→ chama Qwen via Ollama
```

Log esperado:

```text
step=intraday_agent
provider=ollama_local
model=qwen2.5:7b-instruct
```

### 6.3 Regra operacional

```text
Com --web-agent:
gera arquivo para análise externa.

Sem --web-agent:
chama a LLM local.
```

---

## 7. Prompt intraday oficial

Arquivo:

```text
prompts/promptIntraday.md
```

O prompt deve terminar obrigatoriamente com:

```markdown
## MARKET_DATA
{{MARKET_DATA}}
```

O placeholder `{{MARKET_DATA}}` é substituído pelo payload JSON completo.

Se esse placeholder for removido:

- o input final terá apenas instruções;
- OHLC, volume, indicadores e demais dados não serão enviados;
- o arquivo pode cair de aproximadamente 120 mil para aproximadamente 17 mil caracteres;
- a LLM ficará sem os dados atuais do mercado.

Validação:

```powershell
Select-String `
  -Path .\prompts\promptIntraday.md `
  -Pattern "{{MARKET_DATA}}"
```

Esperado:

```text
uma ocorrência
```

### 7.1 Regras de prioridade

A hierarquia atual é:

```text
1. historical_intelligence.formal_mtf_decision
2. chronos_intelligence
3. leitura técnica H1/M15/M5
4. M1 como refinamento de timing
5. H4 como regime superior
```

### 7.2 Guard quantitativo principal

Se:

```text
final_action=WAIT
ou
final_action=WAIT_*
```

a ação imediata deve ser `WAIT`.

Se houver itens em:

```text
formal_decision.blocked_reasons
```

a ação imediata deve ser `WAIT`.

### 7.3 Regras do Chronos

- `available=false`: Chronos indisponível;
- `freshness.status!=FRESH`: não usar operacionalmente;
- `NO_MATCH`: neutro;
- `supporting_side=BUY`: apoio histórico comprador, não ordem;
- `supporting_side=SELL`: apoio histórico vendedor, não ordem;
- `blocked_actions` bloqueia o lado indicado;
- Chronos não libera operação proibida pelo guard principal;
- Chronos não substitui confirmação técnica;
- nenhuma lei deve ser tratada como garantia.

---

## 8. Market Chronos

### 8.1 Filosofia

O Chronos não é um indicador tradicional.

Ele usa sensores como:

- preço;
- volume;
- ATR;
- range;
- corpo;
- pavios;
- RSI;
- MACD;
- ADX;
- horário;
- sessão;
- timeframes;
- breakout;
- false break;
- sweep;
- compressão;
- expansão;
- localização HTF;
- sequência de eventos.

Objetivo:

```text
Sensores
  ↓
Research
  ↓
Discovery
  ↓
Validation
  ↓
Market Laws
  ↓
Decision Engine
```

### 8.2 Runtime live

O runtime atual trabalha com:

```text
anchor_tf=M5
live_timeframes=M5,M15,H1,H4
warmup_bars=5000
```

Ele não usa a base histórica de research como estado atual. Usa os Parquets live gerados por `Base_Dados.py`.

### 8.3 Freshness

A proteção de freshness evita usar dados antigos.

Exemplo:

```json
{
  "status": "FRESH",
  "age_minutes": 0.94,
  "max_age_minutes": 30
}
```

Se o status for `STALE`:

- o bridge marca o Chronos indisponível;
- a LLM não deve usar suas conclusões;
- `STALE` não vira sinal contrário.

### 8.4 Timezone

O MT5 detecta o broker como:

```text
timezone broker=Etc/GMT-2
```

Porém os timestamps persistidos no Parquet foram validados como UTC para o runtime.

Portanto, o Chronos deve usar:

```text
--event-timezone UTC
```

Usar `Etc/GMT-2` no runtime gerou atraso artificial de aproximadamente duas horas e status `STALE`.

### 8.5 Estado sem lei correspondente

Resposta válida:

```text
matched_laws=0
chronos_action=NO_MATCH
supporting_side=NONE
blocked_actions=[]
```

Interpretação:

```text
Chronos disponível e atualizado,
mas sem lei histórica correspondente.
```

Não é erro e não deve forçar `WAIT` sozinho.

---

## 9. Dados enviados à LLM

O input final Web validado contém:

- prompt;
- regras quantitativas;
- regras Chronos;
- preço atual;
- H4, H1, M15, M5 e M1;
- OHLC;
- volume;
- spread;
- RSI;
- MACD;
- ADX;
- ATR;
- médias;
- Bollinger;
- Stochastic;
- Ichimoku;
- OBV;
- MFI;
- Williams %R;
- ROC;
- Parabolic SAR;
- Vortex;
- padrões de candle;
- BOS;
- CHOCH;
- sweeps;
- FVG;
- Order Blocks candidatos;
- Fibonacci;
- sessões;
- níveis próximos;
- barras recentes;
- geometrias;
- Market Intelligence;
- Chronos Intelligence;
- schema JSON final.

Tamanho observado:

```text
aproximadamente 119.587 caracteres
```

Isso confirma que o payload foi inserido.

---

## 10. Volume e volatilidade

### 10.1 Natureza do volume

O volume utilizado é:

```text
MT5 tick volume
```

Ele ajuda a medir:

- atividade relativa;
- ritmo;
- expansão;
- compressão;
- exaustão;
- confirmação aproximada.

Ele não é:

- delta real;
- footprint;
- agressão bid/ask real;
- livro de ofertas;
- fluxo institucional confirmado.

### 10.2 Campos principais

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

### 10.3 Barra live

A barra live pode mudar.

Campos como:

```text
elapsed_bar_ratio
volume_pace_ratio
projected_final_volume
live_price_position
live_range_atr
live_body_atr
```

devem ser tratados como observação em andamento, não como confirmação fechada.

---

## 11. Problemas conhecidos

### 11.1 OBV com overflow unsigned

Foi observado um OBV semelhante a:

```text
184467440737...
```

Esse valor indica provável underflow/overflow de `uint64`.

Causa provável:

```text
OBV negativo convertido para inteiro unsigned
```

Correção recomendada no cálculo:

```python
df["OBV"] = df["OBV"].astype("int64")
```

Idealmente, converter volume e série acumulada para tipo signed antes do cálculo.

Até a correção, a LLM não deve usar valores gigantes de OBV como sinal real.

### 11.2 Padrões de candle sobrepostos

Flags como:

```text
Bearish Engulfing
Evening Star
Dark Cloud Cover
```

podem coexistir no mesmo trecho.

Essas flags são detectores independentes e não devem ser contadas automaticamente como três evidências independentes.

### 11.3 Instruções de probabilidade

O prompt antigo contém exemplos de:

- 65%;
- 70%;
- +12%;
- R:R ilustrativo;
- DXY ilustrativo;
- movimentos históricos ilustrativos.

Regra recomendada:

```text
Só informar probabilidade numérica quando ela estiver explicitamente presente no MARKET_DATA.
Caso contrário, usar LOW, MODERATE ou HIGH.
```

### 11.4 Modelos locais pequenos

O Qwen 7B pode ter dificuldade com:

- payload longo;
- síntese multi-timeframe;
- priorização de regras;
- leitura de volume;
- distinção entre candidato e confirmação;
- estabilidade do JSON.

O modo Web permite comparar a mesma entrada com uma LLM mais capaz sem mudar os dados.

---

## 12. Comandos principais

### 12.1 Entrar no projeto

```powershell
cd C:\Users\diego\Desktop\Python\TradingAgent
```

### 12.2 GOLD intraday para ChatGPT Web

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1
```

Arquivo:

```text
data\debug_llm\GOLD_analyst_1_latest_input.txt
```

### 12.3 GOLD intraday com LLM local

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --analyst analyst_1
```

### 12.4 Intraday sem Market Intelligence

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1 `
  --skip-market-intelligence
```

### 12.5 Intraday sem Chronos

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1 `
  --skip-chronos
```

### 12.6 Apenas validar o fluxo sem LLM

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --skip-agent
```

### 12.7 Múltiplos símbolos

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --symbol EURUSD `
  --web-agent
```

### 12.8 Swing completo

```powershell
python pipeline/swing_pipeline_web.py --symbol GOLD
```

Saída:

```text
data\debug_llm\GOLD_swing_latest_input.txt
```

### 12.9 Swing rápido

```powershell
python pipeline/swing_pipeline_web.py `
  --symbol GOLD `
  --skip-intraday-refresh
```

### 12.10 Validar JSON de configuração

```powershell
python -m json.tool .\tradingagent.json
```

### 12.11 Abrir input Web

```powershell
notepad .\data\debug_llm\GOLD_analyst_1_latest_input.txt
```

### 12.12 Conferir campos essenciais

```powershell
Select-String `
  -Path .\data\debug_llm\GOLD_analyst_1_latest_input.txt `
  -Pattern `
    "REGRAS OBRIGATÓRIAS DO MARKET CHRONOS", `
    "current_price", `
    "indicators_exact", `
    "fvg_up", `
    "historical_intelligence", `
    "chronos_intelligence"
```

---

## 13. Validação esperada

### 13.1 Pipeline Web correto

```text
step=base_dados success=True
step=timeframe_context success=True
step=prompt_payload success=True
step=chronos_runtime success=True
step=chronos_payload_bridge success=True
step=market_intelligence_enrich success=True
step=web_input_agent success=True
llm_called=False
pipeline success=True
```

### 13.2 Chronos correto

```text
source_mode=live
freshness=FRESH
available=true
```

### 13.3 Input completo

O tamanho deve normalmente ser muito maior que o prompt-base.

Exemplo validado:

```text
prompt-base ≈ 16.887 caracteres
input final ≈ 119.587 caracteres
```

Se o input final ficar próximo do tamanho do prompt-base, verificar imediatamente o placeholder `{{MARKET_DATA}}`.

---

## 14. Arquivos de auditoria

### 14.1 Input mais recente

```text
data/debug_llm/<ATIVO>_<ANALISTA>_latest_input.txt
```

### 14.2 Resposta bruta local

```text
data/debug_llm/<ATIVO>_<ANALISTA>_latest_raw_response.txt
```

### 14.3 Resultado do agente

```text
data/agent_results/<ATIVO>_intraday_latest.json
```

### 14.4 Resultado do pipeline

```text
data/pipeline_results/intraday_pipeline_latest.json
```

Arquivos `latest` são sobrescritos.

Para dataset histórico, criar retenção versionada separada.

---

## 15. Swing Web Agent

Estrutura:

```text
agent/web_swing_input_agent.py
context/build_swing_consolidated.py
context/swing_timeframe_context.py
context/swing_prompt_payload.py
pipeline/swing_pipeline_web.py
prompts/PromptPrevisaoSwing.md
```

Fluxo:

1. atualiza H1/M15 quando necessário;
2. atualiza H4/D1/W1;
3. monta consolidado swing;
4. gera contexto;
5. gera payload;
6. gera TXT;
7. não chama LLM.

Saída:

```text
data\debug_llm\GOLD_swing_latest_input.txt
```

---

## 16. Segurança

Não versionar:

- conta real;
- senha;
- servidor privado;
- token;
- chave de API;
- `.env`;
- Parquets;
- payload real;
- input real da LLM;
- resposta bruta;
- logs;
- estado operacional.

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
data/market_intelligence/
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

## 17. Troubleshooting

### 17.1 Chronos retorna `STALE`

Verificar:

```text
--event-timezone UTC
```

Não usar `Etc/GMT-2` no runtime enquanto os Parquets estiverem persistindo timestamps UTC.

### 17.2 `event_time` ausente

O runtime aceita:

- `event_time`;
- `time`;
- `datetime`;
- `timestamp`;
- `date_time`;
- `date`;
- `open_time`;
- `candle_time`;
- DatetimeIndex;
- epoch numérico.

### 17.3 Input com aproximadamente 17 mil caracteres

Causa provável:

```text
placeholder {{MARKET_DATA}} removido do prompt
```

Validar:

```powershell
Select-String `
  -Path .\prompts\promptIntraday.md `
  -Pattern "{{MARKET_DATA}}"
```

### 17.4 LLM local foi chamada sem querer

Se o log mostrar:

```text
step=intraday_agent
provider=ollama_local
```

o comando foi executado sem `--web-agent`.

Usar:

```powershell
python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1
```

### 17.5 `NO_MATCH`

Não é erro.

Significa:

```text
Chronos atualizado,
mas nenhuma lei ativa.
```

### 17.6 Bridge indisponível

Se:

```text
available=false
```

verificar:

- arquivo `chronos_intelligence.json`;
- freshness;
- timezone;
- caminhos;
- retorno do runtime.

### 17.7 Resposta contraditória

Comparar com:

```text
historical_intelligence.formal_mtf_decision
chronos_intelligence.blocked_actions
chronos_intelligence.supporting_side
M5 trigger
```

O guard principal sempre tem prioridade.

---

## 18. Próximas melhorias

Prioridade imediata:

1. corrigir overflow do OBV;
2. remover exemplos numéricos fictícios do prompt;
3. proibir percentuais quando não existirem no payload;
4. compactar instruções para modelos locais pequenos;
5. adicionar validação automática do placeholder;
6. adicionar validação automática do tamanho mínimo do input;
7. adicionar teste de schema do Chronos;
8. adicionar teste de integração do bridge;
9. versionar outputs para dataset;
10. comparar Qwen local com LLM Web usando o mesmo input.

Melhorias futuras:

- volume analysis summary factual;
- volatility summary factual;
- calendário econômico;
- DXY;
- notícias;
- agente de risco;
- agente macro;
- crítico;
- arbiter;
- avaliação histórica;
- MFE/MAE;
- walk-forward;
- backtest real;
- monitoramento;
- execução automatizada somente após validação robusta.

---

## 19. Checklist operacional

Antes da análise:

```text
[ ] tradingagent.json válido
[ ] MT5 conectado
[ ] símbolo habilitado
[ ] prompt contém {{MARKET_DATA}}
[ ] Chronos usa UTC
[ ] Parquets atualizados
```

Após rodar:

```text
[ ] base_dados success
[ ] context success
[ ] payload success
[ ] Chronos FRESH
[ ] bridge available=true
[ ] Market Intelligence success
[ ] web_input_agent llm_called=false
[ ] input final contém MARKET_DATA
[ ] input final contém historical_intelligence
[ ] input final contém chronos_intelligence
```

---

## 20. Comando recomendado para uso diário

```powershell
cd C:\Users\diego\Desktop\Python\TradingAgent

python pipeline/intraday_pipeline_web.py `
  --symbol GOLD `
  --web-agent `
  --analyst analyst_1

notepad .\data\debug_llm\GOLD_analyst_1_latest_input.txt
```

Esse fluxo:

```text
atualiza o mercado
→ roda a inteligência quantitativa
→ roda o Chronos
→ monta o input completo
→ não chama a LLM local
→ gera o arquivo para análise via Web
```
