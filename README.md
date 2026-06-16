# TradingAgent

Base quantitativa e pipeline de contexto para agentes de análise **intraday** e **swing**, com coleta de dados do MetaTrader 5, engenharia de features multi-timeframe, consolidação em Parquet, geração de contexto e montagem de payload factual para LLM.

> Estado atual: a coleta, os consolidados, o contexto intraday e o payload factual estão funcionais. A etapa de chamada da LLM e persistência da decisão ainda será implementada.

---

## 1. Objetivo

O TradingAgent foi projetado para separar claramente três responsabilidades:

1. **Python coleta e calcula fatos**
   - candles;
   - indicadores;
   - volume;
   - volatilidade;
   - estrutura;
   - eventos;
   - níveis;
   - geometria de padrões.

2. **O prompt define o método de análise**
   - prioridade entre timeframes;
   - regras de confirmação;
   - critérios para BUY, SELL ou WAIT;
   - prevenção de alucinações;
   - formato obrigatório da resposta.

3. **A LLM interpreta e decide**
   - não recebe viés pré-calculado;
   - não recebe ação determinística;
   - cruza H1, M15, M5 e M1;
   - decide BUY, SELL ou WAIT conforme os dados.

O projeto evita colocar uma recomendação pronta dentro do payload. A intenção é permitir que a LLM faça a leitura técnica a partir dos valores exatos.

---

## 2. Princípios de arquitetura

### 2.1 Separação entre intraday e swing

Os fluxos são independentes.

- **Intraday:** M1, M5, M15 e H1.
- **Swing:** H4, D1, W1 e MN1.
- **Full:** todos os timeframes.

O viés do swing não deve ser injetado automaticamente no agente intraday.

### 2.2 Fonte oficial de dados

Os arquivos Parquet são a fonte principal.

- arquivos individuais por ativo/timeframe funcionam como cache operacional;
- consolidados são os produtos oficiais de cada fluxo;
- CSV é opcional e voltado para inspeção humana.

### 2.3 Barra atual e barras fechadas

- `is_live_bar = true`: barra atual em formação;
- `bar_status = LIVE`: barra recebendo atualizações;
- `bar_status = CLOSED`: barra encerrada;
- `bar_status = STALE_LAST_BAR`: última barra marcada como atual pelo MT5, mas sem atualização recente.

Barras fechadas têm maior peso para confirmação. A barra live serve para antecipação, leitura de ritmo e timing.

### 2.4 Sem vazamento de futuro

Labels e resultados futuros não entram no payload da LLM.

O payload factual declara:

```json
{
  "future_labels_included": false,
  "decision_or_bias_included": false
}
```

### 2.5 Multiativo e multiplataforma

A lista de ativos é definida uma única vez em:

```json
"universe": {
  "symbols": ["GOLD", "EURUSD", "GBPUSD"]
}
```

Os caminhos são construídos com `pathlib.Path`, funcionando em Windows e Linux.

Observação importante:

- a camada de contexto e payload funciona nativamente em Windows e Linux;
- a coleta direta pelo pacote Python `MetaTrader5` depende de um ambiente compatível com o terminal MT5;
- em Linux, os módulos de contexto podem consumir Parquet/CSV produzidos por outro coletor, por uma máquina Windows, por Wine ou por integração remota.

---

## 3. Estrutura do projeto

```text
TradingAgent/
├── Base_Dados.py
├── tradingagent.json
├── README.md
│
├── context/
│   ├── timeframe_context.py
│   └── prompt_payload.py
│
├── prompts/
│   ├── promptIntraday.md
│   ├── prompRapido.txt
│   ├── PromptPrevIntra-2.txt
│   └── PromptPrevisao.txt
│
├── data/
│   ├── GOLD_M1.parquet
│   ├── GOLD_M5.parquet
│   ├── GOLD_M15.parquet
│   ├── GOLD_H1.parquet
│   ├── GOLD_H4.parquet
│   ├── GOLD_D1.parquet
│   ├── GOLD_W1.parquet
│   ├── GOLD_MN1.parquet
│   │
│   ├── consolidated/
│   │   ├── GOLD_full.parquet
│   │   ├── GOLD_intraday.parquet
│   │   └── GOLD_swing.parquet
│   │
│   ├── context/
│   │   └── GOLD_intraday_context.json
│   │
│   ├── payload/
│   │   └── GOLD_intraday_payload.json
│   │
│   └── manifests/
│       └── base_dados_<modo>_<timestamp>.json
│
└── logs/                         # futuro
```

Os prompts antigos permanecem apenas como referência. O prompt intraday ativo é:

```text
prompts/promptIntraday.md
```

---

## 4. Componentes

## 4.1 `Base_Dados.py`

Responsável por:

- ler `tradingagent.json`;
- conectar ao MT5;
- coletar candles;
- converter horários;
- marcar a barra live;
- calcular indicadores;
- calcular estrutura causal;
- calcular volume, ritmo e projeção;
- detectar eventos;
- gerar Parquets individuais;
- gerar consolidados por modo;
- gerar manifestos.

### Timeframes suportados

```text
M1, M5, M15, H1, H4, D1, W1, MN1
```

### Principais grupos de features

- OHLC;
- tick volume;
- spread;
- retornos;
- ATR;
- RSI;
- MACD;
- médias móveis;
- ADX e DI;
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
- candidatos a Order Block;
- Fibonacci;
- sessões;
- kill zones;
- volume relativo;
- volume pace;
- volume final projetado;
- compressão e expansão;
- contexto da barra live.

---

## 4.2 `context/timeframe_context.py`

Lê o consolidado intraday e cria um contexto resumido por timeframe.

Entrada padrão:

```text
data/consolidated/<ATIVO>_intraday.parquet
```

Fallback:

```text
data/consolidated/<ATIVO>_full.parquet
```

Saída:

```text
data/context/<ATIVO>_intraday_context.json
```

### Conteúdo

- status do mercado;
- status da barra;
- OHLC atual;
- estado estrutural;
- métricas principais;
- eventos;
- níveis próximos;
- últimas barras;
- corpo e pavios;
- volume;
- trace multi-timeframe;
- dados para diagnóstico.

O contexto pode conter classificações determinísticas para auditoria, mas essas classificações não são usadas como decisão final no payload factual.

---

## 4.3 `context/prompt_payload.py`

Lê:

- o contexto;
- o consolidado intraday;
- os valores exatos do mercado.

Gera:

```text
data/payload/<ATIVO>_intraday_payload.json
```

### Objetivo

Entregar à LLM um pacote factual, sem:

- BUY;
- SELL;
- WAIT;
- viés;
- setup recomendado;
- qualidade de entrada;
- probabilidade inventada;
- narrativa decisória pronta.

### Schema atual

```text
2.1
```

### Conteúdo principal

- preço atual;
- status de mercado;
- candle atual por timeframe;
- últimos candles;
- indicadores exatos;
- métricas derivadas;
- flags de eventos;
- níveis exatos;
- zonas próximas;
- geometria de padrões;
- candidatos algorítmicos;
- limitações dos dados.

---

## 4.4 `prompts/promptIntraday.md`

Prompt oficial do agente intraday.

Ele orienta a LLM a:

- priorizar H1, M15 e M5;
- usar M1 somente para timing;
- analisar sequência de candles;
- interpretar volume e volatilidade;
- validar BOS, CHOCH, sweeps e FVG;
- validar padrões de candles;
- analisar bull flag, bear flag, canais e triângulos;
- usar Fibonacci apenas com âncoras presentes;
- separar direção de qualidade da entrada;
- escolher BUY, SELL ou WAIT;
- não inventar probabilidades, notícias ou backtests;
- não aceitar `pattern_candidates` automaticamente.

O placeholder esperado é:

```text
{{MARKET_DATA}}
```

Na etapa de execução da LLM, esse placeholder será substituído pelo JSON do payload.

---

## 5. Modos do pipeline de dados

## 5.1 `full_rebuild`

Executa todos os timeframes e labels configurados.

```powershell
python Base_Dados.py --mode full_rebuild
```

Gera:

```text
data/consolidated/GOLD_full.parquet
```

Timeframes:

```text
M1, M5, M15, H1, H4, D1, W1, MN1
```

Uso recomendado:

- reconstrução da base;
- backtest;
- treino;
- pesquisa;
- auditoria;
- atualização completa.

---

## 5.2 `intraday_refresh`

Atualiza apenas os timeframes intraday.

```powershell
python Base_Dados.py --mode intraday_refresh
```

Gera:

```text
data/consolidated/GOLD_intraday.parquet
```

Timeframes:

```text
M1, M5, M15, H1
```

Labels futuros ficam desabilitados.

Uso recomendado:

- execução recorrente;
- análise a cada poucos minutos;
- alimentação do contexto;
- alimentação do payload;
- agente intraday.

---

## 5.3 `daily_refresh`

Atualiza o bloco de swing.

```powershell
python Base_Dados.py --mode daily_refresh
```

Gera:

```text
data/consolidated/GOLD_swing.parquet
```

Timeframes:

```text
H4, D1, W1, MN1
```

Uso recomendado:

- análise swing;
- atualização diária;
- contexto de longo prazo independente.

---

## 5.4 `contexts_only`

Valida os arquivos existentes sem coletar do MT5.

```powershell
python Base_Dados.py --mode contexts_only
```

Uso planejado:

- ambientes sem MT5;
- Linux;
- pipelines que recebem Parquet de outro coletor;
- processamento offline.

> Observação: a versão atual de `Base_Dados.py` importa o pacote `MetaTrader5` no carregamento do arquivo. Para uso nativo em Linux sem o pacote, essa importação deverá ser tornada opcional em uma melhoria futura.

---

## 6. Instalação

## 6.1 Windows

### Pré-requisitos

- Python 3.10 ou superior;
- MetaTrader 5 instalado;
- terminal configurado;
- conta com acesso ao ativo;
- Git opcional.

### Ambiente virtual

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Dependências

```powershell
pip install --upgrade pip
pip install MetaTrader5 pandas numpy ta pyarrow
```

---

## 6.2 Linux

Para processar Parquet, contexto e payload:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install pandas numpy ta pyarrow
```

A coleta MT5 deve ser feita por uma das estratégias:

- coletor em Windows;
- MT5 via Wine;
- serviço remoto;
- exportação de Parquet/CSV;
- API alternativa.

---

## 7. Configuração

Arquivo:

```text
tradingagent.json
```

## 7.1 Projeto

```json
{
  "project": {
    "name": "TradingAgent",
    "environment": "dev"
  }
}
```

## 7.2 MT5

```json
{
  "mt5": {
    "path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
    "account": 123456,
    "server": "Broker-Server",
    "password": "",
    "broker_timezone": "Etc/GMT-2",
    "timestamp_source": "broker_wall_clock"
  }
}
```

### Segurança

Não publique credenciais no GitHub.

Recomendado:

- manter senha fora do JSON;
- usar variável de ambiente;
- usar arquivo local ignorado pelo Git;
- adicionar `tradingagent.local.json` ao `.gitignore`;
- nunca versionar conta, senha ou token real.

---

## 7.3 Universo de ativos

```json
{
  "universe": {
    "symbols": ["GOLD", "EURUSD", "GBPUSD"]
  }
}
```

Para cada ativo serão gerados arquivos independentes:

```text
GOLD_intraday.parquet
EURUSD_intraday.parquet
GBPUSD_intraday.parquet
```

---

## 7.4 Saída de arquivos

```json
{
  "data": {
    "data_dir": "data",
    "consolidated_dir": "data/consolidated",
    "manifest_dir": "data/manifests",
    "q_candles": 5000,
    "write_parquet": true,
    "write_csv": false,
    "write_consolidated_parquet": true,
    "write_consolidated_csv": false,
    "compression": "zstd"
  }
}
```

Parquet é recomendado para operação. CSV pode ser ativado para inspeção.

---

## 8. Execução intraday completa

### Windows

```powershell
python Base_Dados.py --mode intraday_refresh
python context/timeframe_context.py --symbol GOLD
python context/prompt_payload.py --symbol GOLD
```

### Linux

```bash
python3 context/timeframe_context.py --symbol GOLD
python3 context/prompt_payload.py --symbol GOLD
```

No Linux, o consolidado deve existir previamente.

---

## 9. Validação dos resultados

## 9.1 Contexto

```powershell
$context = Get-Content `
  .\data\context\GOLD_intraday_context.json `
  -Raw -Encoding UTF8 |
  ConvertFrom-Json

$context.schema_version
$context.market_summary.market_status
$context.timeframes.M5.recent_bars[-1] | ConvertTo-Json -Depth 10
```

## 9.2 Payload

```powershell
$payload = Get-Content `
  .\data\payload\GOLD_intraday_payload.json `
  -Raw -Encoding UTF8 |
  ConvertFrom-Json

$payload.payload_schema_version
$payload.payload_type
$payload.data_limitations.decision_or_bias_included
$payload.timeframes.M5.pattern_geometry | ConvertTo-Json -Depth 15
```

Esperado:

```text
payload_schema_version = 2.1
payload_type = FACTUAL_INTRADAY_MARKET_DATA
decision_or_bias_included = False
```

---

## 10. Interpretação dos dados

## 10.1 Volume

O volume do MT5 é tick volume.

Ele permite inferir:

- participação relativa;
- aumento de atividade;
- enfraquecimento;
- ritmo da barra;
- confirmação aproximada;
- possíveis distorções.

Ele não representa:

- delta real;
- footprint;
- agressão bid/ask de bolsa;
- fluxo institucional confirmado.

---

## 10.2 `volume_pace_ratio`

Compara o volume atual da barra com o volume historicamente esperado para o percentual já transcorrido.

Exemplo:

```text
volume_pace_ratio = 1.30
```

Interpretação factual:

```text
o volume está 30% acima do ritmo histórico esperado naquele instante da barra
```

Isso não significa automaticamente compra ou venda.

---

## 10.3 Geometria de padrões

O payload pode gerar candidatos como:

- BULL_FLAG;
- BEAR_FLAG;
- ASCENDING_CHANNEL;
- DESCENDING_CHANNEL;
- ASCENDING_TRIANGLE;
- DESCENDING_TRIANGLE;
- DOUBLE_TOP;
- DOUBLE_BOTTOM.

Esses candidatos são hipóteses.

```text
algorithmic_score != probabilidade
```

A LLM deve validar:

- impulso;
- consolidação;
- slopes;
- compressão;
- volume;
- pivôs;
- breakout;
- fechamento;
- aceitação;
- invalidação.

---

## 10.4 Fibonacci

O payload inclui:

- direção;
- swing high;
- swing low;
- ZigZag;
- retrações;
- extensões.

A LLM não deve criar âncoras novas. Deve utilizar somente as fornecidas.

---

## 11. Fluxo de dados

```text
MetaTrader 5
    ↓
Base_Dados.py
    ↓
Parquets individuais
    ↓
Consolidado intraday
    ↓
timeframe_context.py
    ↓
Contexto por timeframe
    ↓
prompt_payload.py
    ↓
Payload factual
    ↓
promptIntraday.md
    ↓
LLM
    ↓
BUY / SELL / WAIT
```

---

## 12. O que já está implementado

- [x] Configuração por JSON;
- [x] coleta multiativo;
- [x] coleta multi-timeframe;
- [x] barra live;
- [x] timestamps broker/UTC/BRT;
- [x] indicadores técnicos;
- [x] padrões de candles;
- [x] estrutura causal;
- [x] BOS e CHOCH;
- [x] sweeps;
- [x] FVG;
- [x] candidatos a Order Block;
- [x] Fibonacci;
- [x] sessões;
- [x] volume pace;
- [x] projeção de volume;
- [x] consolidados separados;
- [x] contexto intraday;
- [x] últimos candles;
- [x] níveis;
- [x] geometria de padrões;
- [x] payload factual sem viés;
- [x] prompt intraday.

---

## 13. Próximas etapas

### Curto prazo

- [ ] criar `run_intraday_agent.py`;
- [ ] carregar `prompts/promptIntraday.md`;
- [ ] substituir `{{MARKET_DATA}}`;
- [ ] chamar a LLM;
- [ ] salvar a resposta;
- [ ] extrair BUY, SELL ou WAIT;
- [ ] registrar horário, preço e decisão;
- [ ] implementar logs estruturados;
- [ ] validar saída obrigatória.

### Médio prazo

- [ ] criar prompt e payload swing;
- [ ] auditoria de decisões;
- [ ] comparar decisão com movimentos futuros;
- [ ] registrar MFE e MAE após a decisão;
- [ ] backtest real de setups;
- [ ] estatísticas por ativo, sessão e timeframe;
- [ ] GARCH;
- [ ] regimes de volatilidade;
- [ ] HMM;
- [ ] DXY e ativos correlacionados;
- [ ] notícias e calendário econômico;
- [ ] execução agendada.

### Longo prazo

- [ ] orquestração multiagente;
- [ ] agente técnico;
- [ ] agente de risco;
- [ ] agente de macro;
- [ ] agente crítico;
- [ ] agregador final;
- [ ] backtesting e replay;
- [ ] integração com execução;
- [ ] monitoramento em Grafana;
- [ ] avaliação contínua da qualidade das decisões.

---

## 14. Troubleshooting

## Erro: `GOLD_intraday.parquet` não encontrado

Execute:

```powershell
python Base_Dados.py --mode intraday_refresh
```

Depois:

```powershell
python context/timeframe_context.py --symbol GOLD
```

---

## Erro: acentos aparecem como `PressÃ£o`

Use:

```powershell
Get-Content arquivo.json -Raw -Encoding UTF8
```

---

## Erro: `truth value of an empty array is ambiguous`

Confirme que está usando a versão corrigida de `prompt_payload.py`.

```powershell
Select-String `
  -Path .\context\prompt_payload.py `
  -Pattern 'item == \{\}|item == \[\]'
```

O comando não deve retornar resultado.

---

## Mercado fechado, mas `is_live_bar = true`

Consulte:

```json
"bar_status": "STALE_LAST_BAR"
```

e:

```json
"market_status": "CLOSED_OR_STALE"
```

O MT5 pode manter a última barra como corrente mesmo após parar de receber ticks.

---

## 15. Recomendações de Git

`.gitignore` sugerido:

```gitignore
.venv/
__pycache__/
*.pyc
.env
tradingagent.local.json

data/*.csv
data/*.parquet
data/consolidated/
data/context/
data/payload/
data/manifests/
logs/
```

Evite versionar:

- credenciais;
- dados de corretora;
- arquivos grandes;
- Parquets;
- CSVs;
- logs;
- payloads reais;
- respostas com dados sensíveis.

---

## 16. Aviso

Este projeto é voltado a pesquisa, automação e apoio à análise.

Ele não garante lucro e não substitui:

- validação;
- gerenciamento de risco;
- supervisão humana;
- testes históricos;
- testes em conta demo;
- avaliação das condições de mercado.

Decisões automatizadas devem ser validadas antes de qualquer uso em ambiente real.

---

## 17. Licença

Definir a licença do projeto antes de distribuição pública.

Sugestões:

- MIT para uso aberto e simples;
- Apache-2.0 para proteção adicional de patentes;
- licença privada enquanto o projeto estiver em desenvolvimento.
