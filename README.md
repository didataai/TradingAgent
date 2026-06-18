# TradingAgent

> **FINALIDADE**  
> Documentar a arquitetura, configuração, execução, auditoria, limitações e próximos passos do TradingAgent.
>
> **ENTRADAS**  
> Configuração em `tradingagent.json`, dados do MetaTrader 5, prompts Markdown e arquivos Parquet/JSON produzidos pelo pipeline.
>
> **PROCESSAMENTO / ETAPAS**  
> Coleta MT5 → engenharia de features → consolidação multi-timeframe → contexto → payload factual → montagem do prompt → execução da LLM → validação → persistência e auditoria.
>
> **SAÍDAS**  
> Parquets, contexto, payload, input exato da LLM, resposta bruta, resultado estruturado do agente, estado, logs e resultados do pipeline.
>
> **DEPENDÊNCIAS**  
> Python 3.10+, MetaTrader 5, pandas, numpy, pyarrow, biblioteca `ta`, Ollama ou provedor de LLM via API.
>
> **EXEMPLOS**  
> `python pipeline/intraday_pipeline.py --symbol GOLD --agent-mode single --analyst analyst_1`
>
> **TRATAMENTO DE ERROS**  
> Lock de execução, timeouts por etapa, fallback seguro para `WAIT`, validação de JSON e persistência de logs.
>
> **LIMITAÇÕES / OBSERVAÇÕES**  
> O volume é tick volume do MT5. O modelo local atual não possui web search nativo. Candidatos algorítmicos não são confirmação nem probabilidade.

---

## 1. Visão geral

O **TradingAgent** é uma base quantitativa e um pipeline de análise de mercado com LLM, inicialmente focado em:

- intraday;
- scalping;
- swing;
- múltiplos ativos;
- múltiplos timeframes;
- MetaTrader 5;
- execução local com Ollama;
- futura execução por APIs externas;
- rastreabilidade completa do que foi enviado e recebido da LLM.

Princípio central:

```text
Python coleta, calcula e organiza fatos
→ o prompt define o método de análise
→ a LLM interpreta os fatos
→ a LLM decide BUY, SELL ou WAIT
```

O Python não deve inserir uma recomendação pronta dentro do payload factual.

---

## 2. Estado atual validado

O fluxo intraday está funcional de ponta a ponta:

```text
MetaTrader 5
→ Base_Dados.py
→ Parquets individuais
→ consolidado intraday
→ timeframe_context.py
→ prompt_payload.py
→ intraday_agent.py
→ LLM
→ resultado estruturado
→ persistência e auditoria
```

Componentes já funcionando:

- coleta MT5 de M1, M5, M15, H1 e H4;
- aproximadamente 212 colunas por timeframe;
- consolidação intraday;
- contexto multi-timeframe;
- payload factual schema `2.1`;
- execução com Ollama;
- modelo local `qwen2.5:7b-instruct`;
- modo `single`;
- perfil `quick`;
- prompt oficial `prompts/promptIntraday.md`;
- saída estruturada;
- decisão `BUY`, `SELL` ou `WAIT`;
- auditoria do input exato enviado à LLM;
- auditoria da resposta bruta;
- resultado final do agente;
- resultado consolidado do pipeline;
- lock de execução;
- logs;
- manifestos.

A arquitetura atual preserva a decisão livre da LLM no perfil quick:

```text
decision_method = free_llm_prompt_executor
send_memory_to_llm = false
```

---

## 3. Princípios de arquitetura

### 3.1 Payload factual sem viés

O payload não deve conter:

- BUY;
- SELL;
- WAIT;
- ação recomendada;
- viés decisório pronto;
- qualidade de entrada pronta;
- probabilidade inventada;
- narrativa interpretativa fechada;
- labels futuros.

O payload deve declarar:

```json
{
  "future_labels_included": false,
  "decision_or_bias_included": false
}
```

O contexto pode calcular classificações auxiliares para inspeção e diagnóstico, mas elas não devem ser tratadas como decisão final da LLM.

### 3.2 Intraday e swing independentes

Fluxo intraday atual:

```text
H4, H1, M15, M5, M1
```

Prioridade analítica:

```text
H1, M15 e M5
```

Uso complementar:

```text
H4 = contexto estrutural
M1 = timing
```

Fluxo swing:

```text
H4, D1, W1, MN1
```

O fluxo swing não deve contaminar automaticamente o intraday.

### 3.3 Barra live versus barra fechada

- `LIVE`: barra em formação;
- `CLOSED`: barra encerrada;
- `STALE_LAST_BAR`: última barra sem atualização recente;
- `is_live_bar = true`: barra ainda pode mudar.

A barra live serve para:

- ritmo;
- antecipação;
- timing;
- volume pace;
- posição dentro do range.

A barra fechada tem maior peso para confirmação.

### 3.4 Candidatos algorítmicos são hipóteses

Campos como:

```text
BULL_FLAG
BEAR_FLAG
DOUBLE_TOP
DOUBLE_BOTTOM
ASCENDING_TRIANGLE
DESCENDING_TRIANGLE
```

são candidatos geométricos.

```text
algorithmic_score != probabilidade
candidate != confirmação
candidate != recomendação
```

A LLM deve validar o candidato usando:

- estrutura;
- sequência de candles;
- volume;
- volatilidade;
- pivôs;
- rompimento;
- aceitação;
- fechamento;
- invalidação.

---

## 4. Estrutura atual do projeto

```text
TradingAgent/
├── Base_Dados.py
├── tradingagent.json
├── README.md
│
├── agent/
│   └── intraday_agent.py
│
├── context/
│   ├── timeframe_context.py
│   └── prompt_payload.py
│
├── pipeline/
│   └── intraday_pipeline.py
│
├── prompts/
│   ├── promptIntraday.md
│   ├── promptCritic.md
│   ├── promptArbiter.md
│   └── prompts antigos de referência
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

Prompt intraday ativo:

```text
prompts/promptIntraday.md
```

---

## 5. Responsabilidade de cada componente

### 5.1 `Base_Dados.py`

Responsável por:

- carregar `tradingagent.json`;
- conectar ao MT5;
- coletar candles;
- converter timestamps;
- marcar barra live;
- calcular indicadores;
- calcular estrutura causal;
- calcular volume;
- calcular ritmo e projeção de volume;
- calcular volatilidade;
- detectar eventos;
- gerar Parquets;
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
- padrões de candles;
- pivôs;
- ZigZag causal;
- BOS;
- CHOCH;
- sweeps;
- FVG;
- Order Blocks candidatos;
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

Responsabilidades:

- resumir dados por timeframe;
- classificar status de mercado e barra;
- organizar níveis;
- organizar eventos;
- organizar candles recentes;
- produzir diagnóstico;
- produzir trace multi-timeframe;
- manter classificações auxiliares para auditoria.

### 5.3 `context/prompt_payload.py`

Entrada:

- consolidado intraday;
- contexto intraday;
- valores exatos mais recentes.

Saída:

```text
data/payload/<ATIVO>_intraday_payload.json
```

Schema atual:

```text
2.1
```

Tipo:

```text
FACTUAL_INTRADAY_MARKET_DATA
```

Conteúdo:

- preço atual;
- status do mercado;
- H4, H1, M15, M5 e M1;
- candle atual;
- candle anterior fechado;
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
- limitações dos dados.

### 5.4 `agent/intraday_agent.py`

Responsável por:

- carregar configuração;
- selecionar perfil;
- selecionar analista;
- ler prompt oficial;
- ler payload factual;
- montar o prompt final;
- salvar o input exato da LLM;
- chamar o provedor;
- salvar a resposta bruta;
- extrair JSON;
- validar estrutura;
- preencher fallback de apresentação para `Ação Imediata`;
- preservar a decisão livre da LLM;
- salvar resultado final;
- atualizar estado e histórico.

No perfil quick atual:

```text
single = true
ensemble = false
quick = true
detailed = false
send_memory_to_llm = false
decision_method = free_llm_prompt_executor
```

### 5.5 `pipeline/intraday_pipeline.py`

Orquestra:

1. `Base_Dados.py`;
2. `timeframe_context.py`;
3. `prompt_payload.py`;
4. `intraday_agent.py`.

Também controla:

- lock;
- timeout;
- logs;
- sucesso/falha;
- resultado mais recente;
- histórico do pipeline.

---

## 6. Fluxo intraday completo

```text
MT5
  ↓
data/<ATIVO>_M1.parquet
data/<ATIVO>_M5.parquet
data/<ATIVO>_M15.parquet
data/<ATIVO>_H1.parquet
data/<ATIVO>_H4.parquet
  ↓
data/consolidated/<ATIVO>_intraday.parquet
  ↓
data/context/<ATIVO>_intraday_context.json
  ↓
data/payload/<ATIVO>_intraday_payload.json
  ↓
prompts/promptIntraday.md + MARKET_DATA + schema de transporte
  ↓
LLM
  ↓
data/debug_llm/<ATIVO>_<ANALISTA>_latest_input.txt
data/debug_llm/<ATIVO>_<ANALISTA>_latest_raw_response.txt
  ↓
data/agent_results/<ATIVO>_intraday_latest.json
  ↓
data/pipeline_results/intraday_pipeline_latest.json
```

---

## 7. Pastas de dados

### Essenciais para o fluxo intraday

```text
consolidated/
context/
payload/
agent_results/
pipeline_results/
locks/
```

### Histórico e auditoria

```text
agent_runs/
pipeline_runs/
logs/
manifests/
state/
debug_llm/
```

### Outros modos

```text
<ATIVO>_D1.parquet
<ATIVO>_W1.parquet
<ATIVO>_MN1.parquet
```

Esses arquivos maiores são usados em `full_rebuild`, `daily_refresh` e futuros fluxos swing.

### Política para `debug_llm`

A configuração atual usa nomes `latest`:

```text
<ATIVO>_<ANALISTA>_latest_input.txt
<ATIVO>_<ANALISTA>_latest_raw_response.txt
```

Esses arquivos são sobrescritos a cada execução. Não acumulam histórico.

Eles permitem auditar exatamente:

- o prompt enviado;
- o payload enviado;
- o schema solicitado;
- a resposta bruta antes do tratamento.

---

## 8. Volume e volatilidade

### 8.1 Natureza do volume

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

### 8.2 Campos de volume

Principais campos:

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

### 8.3 Interpretação correta

`volume_ratio = 3.05`:

```text
o candle teve aproximadamente 3,05 vezes a média de volume de referência
```

`volume_pace_ratio = 0.39`:

```text
o candle live está com cerca de 39% do ritmo historicamente esperado para aquele ponto da barra
```

A LLM deve cruzar volume com:

- direção do candle;
- corpo;
- pavios;
- posição do fechamento;
- estrutura;
- rompimento;
- sequência de candles.

### 8.4 Limitação atual da LLM local

O payload contém os dados de volume, mas o modelo local de 7B pode não sintetizar corretamente:

- volume crescente;
- volume decrescente;
- dominância de volume comprador ou vendedor;
- diferença entre pico anterior e baixa participação atual.

Melhoria futura planejada:

```text
volume_analysis_summary
```

Esse bloco deve ser factual, compacto e sem viés decisório.

---

## 9. Configuração da LLM

Configuração atual:

```text
provider = ollama_local
model = qwen2.5:7b-instruct
temperature = 0.1
num_ctx = 32768
max_output_tokens = 2000
```

O prompt real observado utiliza aproximadamente:

```text
27k a 28k tokens de entrada
```

Tempo observado na máquina local:

```text
aproximadamente 4 a 5 minutos por análise
```

Limitações observadas:

- síntese inconsistente em payload longo;
- dificuldade de priorizar estrutura sobre candidatos;
- leitura incompleta de volume;
- contradições ocasionais entre H4/H1 e resumo final;
- baixa profundidade em níveis, stop, alvo e relação risco-retorno.

Essas limitações parecem estar relacionadas principalmente à capacidade do modelo local, não à falta de dados.

Próximo teste planejado:

- modelo local mais forte; ou
- LLM via API;
- mesmo prompt;
- mesmo payload;
- mesma saída estruturada;
- comparação controlada de qualidade, latência e custo.

---

## 10. Prompt oficial

Arquivo:

```text
prompts/promptIntraday.md
```

O prompt atual:

- preserva o prompt intraday original;
- adiciona H4;
- usa M1 como apoio;
- solicita apenas cinco seções;
- exige JSON válido;
- não envia memória;
- não injeta direção;
- não usa guard de BUY/SELL;
- exige `immediate_action`;
- pede `recommended_action_now`.

Saída exibida:

1. Pontos-chave;
2. Pontos de atenção;
3. Resumo por timeframe;
4. Ação Imediata;
5. Ação Mais Recomendada Agora.

O JSON é formato de transporte, não regra decisória.

---

## 11. Execução

### Pipeline completo

```powershell
python pipeline/intraday_pipeline.py `
  --symbol GOLD `
  --agent-mode single `
  --analyst analyst_1
```

### Apenas coleta intraday

```powershell
python Base_Dados.py --mode intraday_refresh
```

### Apenas contexto

```powershell
python context/timeframe_context.py --symbol GOLD
```

### Apenas payload

```powershell
python context/prompt_payload.py --symbol GOLD
```

---

## 12. Validação

### Validar configuração JSON

```powershell
python -c "import json; json.load(open('tradingagent.json', encoding='utf-8')); print('JSON OK')"
```

### Conferir perfil ativo

```powershell
$config = Get-Content `
  .\tradingagent.json `
  -Raw -Encoding UTF8 |
  ConvertFrom-Json

[PSCustomObject]@{
  QuickPrompt      = $config.agent.quick_profile.prompt_path
  AnalystPrompt    = $config.llm.roles.analysts[0].prompt_path
  ModelMaxOutput   = $config.llm.models.qwen_local_analyst_1.max_output_tokens
  QuickTarget      = $config.agent.quick_profile.target_output_tokens
  SendMemoryToLLM = $config.agent.quick_profile.send_memory_to_llm
  DecisionMethod   = $config.agent.quick_profile.decision_method
}
```

Esperado:

```text
QuickPrompt      : prompts/promptIntraday.md
AnalystPrompt    : prompts/promptIntraday.md
ModelMaxOutput   : 2000
QuickTarget      : 2000
SendMemoryToLLM : False
DecisionMethod   : free_llm_prompt_executor
```

### Abrir o input exato da última execução

```powershell
notepad .\data\debug_llm\GOLD_analyst_1_latest_input.txt
```

### Abrir a resposta bruta

```powershell
notepad .\data\debug_llm\GOLD_analyst_1_latest_raw_response.txt
```

---

## 13. Modos de dados

### `full_rebuild`

```powershell
python Base_Dados.py --mode full_rebuild
```

Timeframes:

```text
M1, M5, M15, H1, H4, D1, W1, MN1
```

### `intraday_refresh`

```powershell
python Base_Dados.py --mode intraday_refresh
```

Timeframes:

```text
M1, M5, M15, H1, H4
```

### `daily_refresh`

```powershell
python Base_Dados.py --mode daily_refresh
```

Timeframes:

```text
H4, D1, W1, MN1
```

### `contexts_only`

Usado para recriação de contexto sem nova coleta.

---

## 14. Segurança

Não versionar:

- senhas;
- tokens;
- chaves de API;
- conta real;
- servidor privado;
- payload real;
- input real da LLM;
- resposta bruta;
- Parquets;
- logs;
- estado operacional.

Recomendação:

```text
.env
variáveis de ambiente
tradingagent.local.json
.gitignore
```

`.gitignore` sugerido:

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

## 15. Próximas etapas

### Próximo passo imediato

Comparar o mesmo fluxo usando outra LLM:

- API externa; ou
- modelo local mais forte.

Objetivo da comparação:

- coerência H4/H1/M15/M5;
- leitura de volume;
- leitura de volatilidade;
- uso correto de níveis;
- capacidade de distinguir direção de qualidade de entrada;
- consistência entre `action` e justificativa;
- latência;
- custo;
- estabilidade do JSON.

### Melhorias futuras

- `volume_analysis_summary` factual;
- resumo de volatilidade;
- substituição automática de placeholders;
- suporte a OpenAI;
- suporte a OpenRouter;
- suporte a Anthropic;
- suporte a xAI;
- comparação entre modelos;
- dataset de inputs e respostas;
- agente crítico especializado;
- avaliação histórica;
- MFE/MAE;
- backtest real;
- métricas por sessão;
- integração DXY;
- calendário econômico;
- notícias;
- monitoramento em Grafana;
- agente de risco;
- agente macro;
- multiagente;
- execução automatizada, somente após validação robusta.

---

## 16. Uso futuro dos arquivos de auditoria

Os arquivos de auditoria podem futuramente apoiar:

- criação de dataset;
- avaliação de modelos;
- prompt optimization;
- classificação de erros;
- fine-tuning;
- RAG de casos históricos;
- agente crítico;
- comparação entre recomendações e resultado futuro.

Para treinamento real, será necessário adicionar rótulos posteriores, por exemplo:

- preço após N minutos;
- preço após N candles;
- MFE;
- MAE;
- direção realizada;
- acerto/erro;
- qualidade da justificativa;
- aderência aos dados;
- erro factual;
- erro de volume;
- erro de estrutura;
- erro de nível;
- ação mais segura retrospectivamente.

Os arquivos `latest` atuais são úteis para auditoria manual, mas não mantêm histórico. Para dataset, deverá existir um modo separado de retenção versionada.

---

## 17. Troubleshooting

### `Unexpected UTF-8 BOM`

Corrigir o JSON para UTF-8 sem BOM:

```powershell
$content = Get-Content `
  .\tradingagent.json `
  -Raw -Encoding UTF8

[System.IO.File]::WriteAllText(
  (Resolve-Path .\tradingagent.json),
  $content,
  (New-Object System.Text.UTF8Encoding($false))
)
```

### Prompt não encontrado

Confirmar:

```powershell
Test-Path .\prompts\promptIntraday.md
```

E verificar:

```text
agent.quick_profile.prompt_path
llm.roles.analysts[0].prompt_path
```

Ambos devem apontar para:

```text
prompts/promptIntraday.md
```

### `Ação Imediata` vazia

A versão atual exige `immediate_action`. Caso a LLM ainda retorne vazio, o agente usa a própria descrição da recomendação como fallback de apresentação, sem alterar `BUY`, `SELL` ou `WAIT`.

### Resposta contraditória

Verificar:

```text
data/debug_llm/<ATIVO>_<ANALISTA>_latest_input.txt
data/debug_llm/<ATIVO>_<ANALISTA>_latest_raw_response.txt
```

Comparar a resposta com:

- `structure_state`;
- eventos;
- volume;
- candles recentes;
- médias;
- MACD;
- ADX;
- Vortex;
- candidatos não confirmados.

---

## 18. Aviso

Este projeto é voltado para pesquisa, automação e apoio à análise.

Ele não garante lucro e não substitui:

- supervisão humana;
- validação;
- gerenciamento de risco;
- testes históricos;
- testes em conta demo;
- controle de exposição;
- avaliação de mercado;
- responsabilidade do operador.

Não habilitar execução automática de ordens antes de:

- validação histórica;
- avaliação estatística;
- testes robustos;
- tratamento de falhas;
- limites de risco;
- kill switch;
- observabilidade;
- supervisão humana.

---

## 19. Licença

Definir antes de distribuição pública.

Possibilidades:

- MIT;
- Apache-2.0;
- licença privada durante o desenvolvimento.
