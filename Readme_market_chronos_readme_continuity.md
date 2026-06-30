# Market Chronos — README de Continuidade

> **Projeto:** TradingAgent / Market Chronos  
> **Ativo inicial:** GOLD  
> **Anchor timeframe atual:** M5  
> **Objetivo:** transformar dados de mercado em conhecimento estatístico validado, descobrindo o DNA comportamental do ativo e usando esse conhecimento para filtrar, evitar e selecionar trades melhores.

---

## 1. Filosofia do Projeto

O Market Chronos não deve ser tratado como um indicador tradicional.

A ideia principal é:

> **Indicadores medem. Dados ensinam. Leis decidem.**

Os indicadores, timeframes, candles, volume, ATR, sessões, rompimentos, sweeps e contextos não são sinais isolados. Eles são **sensores**. O Chronos usa esses sensores para descobrir padrões recorrentes no comportamento do mercado.

O objetivo final não é criar mais sinais, mas descobrir:

- quando operar;
- quando esperar;
- quando evitar;
- qual tipo de contexto favorece compra;
- qual tipo de contexto favorece venda;
- quando o mercado tende a romper;
- quando tende a devolver;
- quando um falso rompimento tem edge;
- quando um rompimento está esticado demais;
- quando o setup nasceu de uma sequência saudável;
- quando o movimento já está cansado.

A frase que resume o espírito do projeto:

> **Não queremos ensinar o mercado para a IA. Queremos que o mercado ensine a IA.**

---

## 2. Visão Geral da Arquitetura

A estrutura conceitual do Chronos está evoluindo para:

```text
Sensores
    ↓
Research Engine
    ↓
Discovery Engine
    ↓
Validation Engine
    ↓
Market Laws
    ↓
Decision Engine
    ↓
EA / Trading Agent
```

### 2.1 Sensores

Sensores são todas as fontes de observação do mercado:

```text
Preço
Volume
ATR
Range
Body
Wicks
ADX
RSI
MACD
OBV
MFI
Horário
Sessão
M1 / M5 / M15 / H1 / H4 / D1 / W1
Breakout
False Break
Sweep
Compressão
Expansão
Distância de suporte/resistência
Distância de máxima/mínima anterior
Localização HTF
Sequência de eventos
```

### 2.2 Research Engine

Responsável por calcular estatísticas e produzir tabelas de pesquisa.

### 2.3 Discovery Engine

Responsável por encontrar padrões novos automaticamente.

Exemplo futuro:

```text
"Encontrei 14 combinações novas com edge acima de 18%.
Nenhuma delas existe na base de conhecimento atual."
```

### 2.4 Validation Engine

Responsável por validar se uma hipótese continua funcionando em:

```text
amostra maior
out-of-sample
período recente
ativo diferente
broker diferente
janela rolling
```

### 2.5 Market Laws

Biblioteca final de leis estatísticas validadas.

Exemplo:

```text
LAW_0001 — 10h Expansion Retrace
Ativo: GOLD
TF: M5
Status: Validada
Aplicação: evitar perseguir candle; preferir pullback
```

### 2.6 Decision Engine

Consumidor final das leis.

Ele deve responder perguntas como:

```text
Comprar?
Vender?
Esperar?
Evitar?
Qual score?
Qual confiança?
Quais leis apoiam?
Quais leis são contra?
```

---

## 3. Estrutura de Arquivos Atual

### 3.1 Scripts principais

```text
tools/base_dados_candle_research.py
tools/market_chronos_lab.py
tools/market_chronos_engine_v6.py
```

### 3.2 Base principal

```text
data/market_chronos/candle_base/consolidated/GOLD_candle_research.parquet
data/market_chronos/GOLD/lab/GOLD_M5_mtf_research_base.parquet
```

A base MTF atual possui aproximadamente:

```text
M5 anchor: 99.999 candles
GOLD
Base MTF com contexto M15 / H1 / H4
```

### 3.3 Pasta de saída principal

```text
data/market_chronos/GOLD/engine/
```

Essa pasta recebe os relatórios e CSVs do `market_chronos_engine`.

---

## 4. Evolução por Versão

---

# V1 — Behavior Map

## Objetivo

Mapear comportamento por horário.

Perguntas:

```text
Qual horário tem mais energia?
Qual horário tem mais volume?
Qual horário rompe mais?
Qual horário devolve mais?
Qual horário tem maior pullback?
Qual horário é perigoso para stop curto?
```

## Arquivos gerados

```text
engine_behavior_map.csv
chronos_engine_report.md
GOLD_market_chronos_engine.xlsx
metadata.json
```

## Descobertas importantes

### 9h e 10h

O feeling inicial era:

```text
9h anda / expande / tem volume
10h anda, mas devolve
```

Os dados confirmaram:

```text
9h e 10h têm energia alta
range alto
volume acima da média
rompimentos frequentes
muitos sweeps / falsos rompimentos
alta devolução
```

Conclusão operacional:

```text
evitar perseguir candle
evitar stop curto
esperar aceitação
preferir pullback/reteste
```

### 21h

A janela de 21h também apareceu com energia/volume relevantes.

Hipótese:

```text
pode ter relação com abertura diária / reset do broker
```

Ainda precisa de estudo específico.

---

# V2 — Level Playbook

## Objetivo

Responder perguntas em suporte/resistência:

```text
Estou na resistência: compro rompimento ou vendo rejeição?
Estou no suporte: compro defesa ou vendo rompimento?
```

## Arquivos gerados

```text
engine_level_playbook.csv
engine_level_playbook_best.csv
```

## Descobertas importantes

### Falso rompimento em resistência

Quando o contexto favorece venda:

```text
RESISTANCE
FALSE_BREAK
viés vendedor
```

o motor encontrou edge para venda/rejeição.

### Falso rompimento em suporte

Quando o contexto favorece compra:

```text
SUPPORT
FALSE_BREAK
viés comprador
```

o motor encontrou edge para compra/defesa.

## Interpretação

Isso começou a transformar o estudo em um manual operacional:

```text
rompimento favorece compra
rejeição favorece venda
defesa do suporte favorece compra
rompimento do suporte favorece venda
```

---

# V3 — State DNA

## Objetivo

Criar identidade estatística do estado de mercado.

Pergunta central:

```text
O mercado já ficou assim antes?
```

## Arquivos gerados

```text
engine_state_dna_macro.csv
engine_state_dna_operational.csv
engine_state_dna_granular.csv
engine_state_playbook.csv
engine_state_transitions.csv
```

## Resultado do run

```text
state_dna_macro: 204
state_dna_operational: 0
state_dna_granular: 0
state_transitions: 270
```

## Interpretação

O DNA macro funcionou bem.

O DNA operacional e granular ficaram específicos demais para `min_bars=120`, por isso retornaram zero padrões. Isso não é erro. Significa:

```text
quanto mais específico o DNA, maior a chance de faltar amostra
```

## Decisão

Por enquanto:

```text
usar Macro DNA como camada confiável
manter Operational/Granular para versões futuras com mais candles ou min_bars menor
```

---

# V4 — Setup Genome

## Objetivo

Sair de "estado do mercado" e começar a mapear o "genoma do setup".

Pergunta central:

```text
Esse conjunto de contexto + localização + evento + lado provável forma um setup?
```

## Arquivos gerados

```text
engine_setup_genome_macro.csv
engine_setup_genome_time.csv
engine_setup_genome_granular.csv
engine_setup_genome_playbook.csv
```

## Resultado do run

```text
setup_genome_macro: 178
setup_genome_time: 1
setup_genome_granular: 0
```

## Descobertas importantes

### Melhor padrão identificado

```text
RESISTANCE_FALSE_BREAK
SELL_ALIGNED
FULL/DOWN
```

Interpretação:

```text
Falso rompimento em resistência
+
viés MTF vendedor
=
venda de rejeição com edge
```

### Espelho comprador

```text
SUPPORT_FALSE_BREAK
BUY_ALIGNED
FULL/UP
```

Interpretação:

```text
Falso rompimento em suporte
+
viés MTF comprador
=
compra de defesa do suporte com edge
```

### 10h novamente

O único `setup_genome_time` apareceu na região de 10h:

```text
10h
EXPANSION
RESISTANCE_BREAKOUT
BUY_ALIGNED
EXTREME
FULL/UP
```

Mas o resultado mostrou:

```text
movimento ocorre
mas devolução é alta
não perseguir rompimento
preferir aceitação/pullback
```

---

# V5 — HTF Location DNA

## Objetivo

Medir se o setup M5 está a favor ou contra a localização dos timeframes maiores.

Perguntas:

```text
O rompimento M5 está a favor do H1/H4/D1?
Está contra?
Está perto de máxima/min de TF maior?
A localização HTF melhora ou piora o edge?
```

## Arquivos gerados

```text
engine_htf_location_dna.csv
engine_htf_setup_genome.csv
engine_htf_setup_genome_time.csv
engine_htf_breakout_alignment.csv
```

## Resultado do run

```text
htf_location_dna: 149
htf_setup_genome: 200
htf_setup_genome_time: 2
htf_breakout_alignment: 225
```

## Descobertas importantes

A expectativa inicial era:

```text
rompimento com HTF alinhado = sempre melhor
```

Mas os dados mostraram algo mais refinado:

```text
rompimento com HTF pode andar
mas ainda pode devolver muito
```

A leitura prática ficou:

```text
não basta HTF estar alinhado
é preciso avaliar se o rompimento está esticado
se veio de expansão
se há pullback provável
se há aceitação
```

---

# V6 — Sequence DNA / DNA Temporal

## Objetivo

Parar de olhar apenas a "foto" do candle e começar a olhar o "filme".

Pergunta central:

```text
Como o mercado chegou nesse estado?
```

## Arquivos gerados

```text
engine_sequence_dna_macro.csv
engine_sequence_dna_setup.csv
engine_sequence_dna_time.csv
engine_sequence_regimes.csv
```

## Resultado do run

```text
sequence_dna_macro: 194
sequence_dna_setup: 186
sequence_dna_time: 1
sequence_regimes: 179
```

## O que a V6 mede

```text
sequência de direção dos últimos candles
sequência de eventos
compressão recente
expansão recente
sweep recente
falso rompimento recente
tentativas de breakout
cluster de breakout
streak direcional
```

## Descobertas importantes

### Melhor macro temporal

```text
FALSE_BREAK
FULL/UP
NORMAL_SEQUENCE
```

Interpretação:

```text
falso rompimento
+
alinhamento comprador
+
sem sequência esticada antes
=
compra muito forte
```

### Espelho vendedor

```text
FALSE_BREAK
FULL/DOWN
EXPANSION_CHAIN
```

Interpretação:

```text
falso rompimento
+
alinhamento vendedor
+
após cadeia de expansão
=
venda forte
```

### Setup Sequence confirmado

```text
RESISTANCE_FALSE_BREAK
SELL_ALIGNED
FULL/DOWN
BO_CLUSTER
```

Interpretação:

```text
falso rompimento em resistência
+
vendedor alinhado
+
várias tentativas de rompimento
=
venda de rejeição
```

### 10h novamente

O único `sequence_time` reforçou:

```text
10h
EXPANSION
EXTREME
BREAKOUT_AFTER_EXPANSION_CHAIN
```

Conclusão:

```text
anda
mas devolve muito
evitar entrada esticada
preferir pullback
```

---

## 5. Resumo das Descobertas Até Agora

### 5.1 Lei candidata — 10h Expansion Retrace

```text
Janela 10h
expansão alta
volume alto
rompimentos frequentes
mas devolução muito alta
```

Uso:

```text
evitar perseguir candle
evitar stop curto
esperar aceitação
preferir pullback/reteste
```

Status:

```text
Hipótese validada em discovery
ainda não promovida para Market Law
```

---

### 5.2 Lei candidata — False Break Resistance Sell

```text
Falso rompimento em resistência
+
viés MTF vendedor
+
sequência com tentativas/cluster
=
edge para venda
```

Uso:

```text
vender rejeição
não comprar topo
esperar confirmação de falha
```

Status:

```text
muito promissora
precisa validação out-of-sample
```

---

### 5.3 Lei candidata — False Break Support Buy

```text
Falso rompimento em suporte
+
viés MTF comprador
=
edge para compra
```

Uso:

```text
comprar defesa do suporte
não vender fundo
esperar confirmação/reteste
```

Status:

```text
muito promissora
precisa validação out-of-sample
```

---

### 5.4 Lei candidata — Movimento Esticado Devolve

```text
Expansão extrema
+
breakout
+
cadeia de expansão anterior
=
tende a andar, mas devolver
```

Uso:

```text
não perseguir rompimento
usar pullback
stop mais inteligente
alvo parcial
```

---

## 6. Decisão Filosófica Importante

Não vamos transformar descobertas em leis imediatamente.

Fluxo correto:

```text
Discovery
    ↓
Validation
    ↓
Market Laws
```

Agora estamos em:

```text
Fase 1 — Discovery
```

As descobertas ficam como:

```text
hipóteses fortes
candidatas a lei
```

Só entram oficialmente em `Market Laws` após:

```text
mais amostra
out-of-sample
janela recente
robustez com min_bars diferentes
eventual teste em outros ativos
```

---

## 7. Próximas Versões Planejadas

---

# V7 — Memory Engine

## Objetivo

Medir memória recente do mercado.

Perguntas:

```text
primeira tentativa de rompimento funciona melhor?
segunda tentativa é melhor ou pior?
terceira tentativa já está cansada?
após falso rompimento, o próximo breakout melhora?
após sweep, o primeiro pullback tem edge?
após BO_CLUSTER, o movimento continua ou esgota?
```

## Features planejadas

```text
last_breakout_distance
last_false_break_distance
last_sweep_distance
attempt_number_since_last_sweep
attempt_number_since_last_false_break
bars_since_last_breakout
bars_since_last_high_sweep
bars_since_last_low_sweep
breakout_attempt_number_session
breakout_attempt_number_hour
failed_breakout_count_lookback
accepted_breakout_count_lookback
```

## Outputs planejados

```text
engine_memory_dna.csv
engine_memory_setup.csv
engine_memory_attempts.csv
engine_memory_playbook.csv
```

---

# V8 — Liquidity / Daily Range Engine

## Objetivo

Responder a ideia:

```text
Quando o diário está acima/abaixo da máxima/mínima anterior,
isso favorece rompimentos?
```

## Perguntas

```text
D1 acima da máxima do dia anterior favorece continuação?
D1 abaixo da mínima anterior favorece venda?
Dentro do range de ontem favorece falso rompimento?
Perto da máxima do dia atual aumenta rejeição?
Perto da mínima do dia atual aumenta defesa?
Dia já andou 1 ATR: rompimentos perdem força?
Dia ainda andou pouco: rompimentos têm mais espaço?
```

## Features planejadas

```text
above_prev_day_high
below_prev_day_low
inside_prev_day_range
distance_prev_day_high_atr
distance_prev_day_low_atr
current_day_range_atr
current_day_range_pct_of_atr
distance_today_high_atr
distance_today_low_atr
daily_extension_bucket
daily_location_bucket
weekly_location_bucket
```

## Outputs planejados

```text
engine_liquidity_dna.csv
engine_daily_range_dna.csv
engine_daily_breakout_playbook.csv
engine_liquidity_setup_genome.csv
```

---

# V9 — M1 Entry Filter Lab

## Objetivo

Testar entradas finas no M1 usando os contextos validados pelo Chronos.

Hipótese inicial do operador:

```text
BUY:
M1 rompe máxima do candle anterior
candle anterior M1 verde
M5 verde/alinhado

SELL:
M1 rompe mínima do candle anterior
candle anterior M1 vermelho
M5 vermelho/alinhado
```

## Perguntas

```text
Esse gatilho funciona sozinho?
Funciona apenas com DNA favorável?
Funciona melhor após falso rompimento?
Funciona melhor após pullback?
Funciona melhor em 9h/10h/21h?
Funciona pior em expansão extrema?
Qual stop ideal em ATR?
Qual alvo ideal?
```

## Outputs planejados

```text
engine_m1_entry_lab.csv
engine_m1_entry_genome.csv
engine_m1_entry_filters.csv
engine_m1_entry_playbook.csv
```

---

# V10 — Discovery Engine

## Objetivo

Fazer o Chronos propor hipóteses automaticamente.

Exemplos:

```text
"Encontrei um padrão novo com edge acima de 18%."
"Nas últimas 20.000 velas, um comportamento mudou."
"A terceira tentativa de rompimento após sweep tem edge melhor que a primeira."
```

## Outputs planejados

```text
engine_discovery_candidates.csv
engine_discovery_anomalies.csv
engine_discovery_report.md
```

---

# V11 — Validation Engine

## Objetivo

Validar hipóteses candidatas.

Validações:

```text
treino/teste temporal
walk-forward
últimos 30 dias
últimos 90 dias
períodos de alta/baixa volatilidade
min_bars diferentes
alvos/stops diferentes
```

## Outputs planejados

```text
engine_validation_report.md
engine_validated_laws_candidates.csv
engine_failed_hypotheses.csv
```

---

# V12 — Market Laws Library

## Objetivo

Criar biblioteca permanente de conhecimento.

Exemplo de lei:

```text
LAW_0001
Nome: 10h Expansion Retrace
Ativo: GOLD
Status: VALIDADA
Origem: Behavior Engine
Descrição: Após expansão forte às 10h, existe alta chance de pullback relevante.
Aplicação: evitar perseguir candle, preferir pullback/reteste.
```

## Outputs planejados

```text
market_laws_gold.json
market_laws_gold.md
market_laws_registry.csv
```

---

# V13 — Decision Engine

## Objetivo

Receber estado atual do mercado e responder:

```text
comprar
vender
esperar
evitar
```

Com justificativa:

```text
leis favoráveis
leis contra
score
probabilidade
confiança
risco de devolução
melhor forma de entrada
```

## Exemplo futuro

```text
Estado atual parecido com:
LAW_0002 + LAW_0007 + LAW_0018

Score comprador: 82
Score vendedor: 21

Decisão:
Comprar somente após pullback.
Evitar perseguir rompimento.
```

---

## 8. Estrutura Ideal Futura do Projeto

```text
data/
  market_chronos/
    candle_base/
    GOLD/
      lab/
      engine/
      laws/
      validation/
      discovery/

tools/
  base_dados_candle_research.py
  market_chronos_lab.py
  market_chronos_engine.py

docs/
  market_chronos_readme.md
  market_chronos_laws.md
  market_chronos_architecture.md
```

---

## 9. Pipeline Atual

```text
1. Coletar base grande
   ↓
tools/base_dados_candle_research.py

2. Criar base MTF
   ↓
tools/market_chronos_lab.py

3. Rodar engine
   ↓
tools/market_chronos_engine_v6.py --symbol GOLD --anchor-tf M5

4. Analisar outputs
   ↓
engine/*.csv
chronos_engine_report.md
GOLD_market_chronos_engine.xlsx

5. Evoluir próxima versão
```

---

## 10. Comando Atual

```powershell
python tools/market_chronos_engine_v6.py --symbol GOLD --anchor-tf M5
```

---

## 11. Prompt para Continuar em Novo Chat

Copiar e colar o prompt abaixo no novo chat:

```text
Mestre, vamos continuar o projeto Market Chronos / TradingAgent.

Contexto:
Estamos construindo o Market Chronos, um motor estatístico para descobrir o DNA comportamental do GOLD e futuramente de outros ativos. A filosofia é: indicadores são sensores, dados ensinam e leis decidem. Não queremos criar sinais fixos; queremos descobrir padrões estatísticos recorrentes, validar hipóteses e futuramente transformar descobertas robustas em Market Laws.

Base atual:
- Ativo: GOLD
- Anchor TF: M5
- Base MTF: data/market_chronos/GOLD/lab/GOLD_M5_mtf_research_base.parquet
- Aproximadamente 99.999 candles M5
- Contexto M15 / H1 / H4
- Saída principal: data/market_chronos/GOLD/engine/

Scripts atuais:
- tools/base_dados_candle_research.py
- tools/market_chronos_lab.py
- tools/market_chronos_engine_v6.py

Já evoluímos:
V1 Behavior Map
V2 Level Playbook
V3 State DNA
V4 Setup Genome
V5 HTF Location DNA
V6 Sequence DNA

Principais descobertas até agora:
1. 9h e 10h têm expansão, volume e rompimentos, mas devolvem muito.
2. 10h especialmente tende a andar, mas exige pullback/reteste; evitar perseguir candle.
3. Falso rompimento em resistência com viés MTF vendedor mostrou edge forte para venda.
4. Falso rompimento em suporte com viés MTF comprador mostrou edge forte para compra.
5. Rompimento puro funciona menos do que esperado; precisa de contexto, localização e sequência.
6. HTF alinhado ajuda, mas não elimina devolução se o movimento estiver esticado.
7. Sequence DNA mostrou que o caminho até o setup importa: não é só a foto do candle, é o filme.
8. O melhor caminho agora é V7 Memory Engine.

Próxima evolução desejada:
Criar V7 — Memory Engine dentro do market_chronos_engine, gerando um novo arquivo market_chronos_engine_v7.py.

Objetivo da V7:
Medir memória recente do mercado:
- primeira tentativa de rompimento
- segunda tentativa
- terceira tentativa
- cluster de rompimentos
- bars since last breakout
- bars since last false breakout
- bars since last sweep
- tentativas desde último sweep
- tentativas desde último false break
- se o mercado melhora ou piora após falhas recentes

Outputs esperados:
- engine_memory_dna.csv
- engine_memory_setup.csv
- engine_memory_attempts.csv
- engine_memory_playbook.csv

Importante:
Manter o projeto enxuto, evoluindo o engine principal por versões.
Não transformar descobertas em Market Laws ainda; estamos em fase Discovery.
Depois faremos Validation e só então Market Laws.
```

---

## 12. Observações Importantes para o Próximo Chat

1. Não criar muitos scripts paralelos.
2. Continuar usando `market_chronos_engine_vX.py` por versão.
3. Quando uma versão estabilizar, depois renomear para `market_chronos_engine.py`.
4. Tratar descobertas como hipóteses até validação.
5. Sempre separar:
   - comportamento;
   - edge;
   - setup;
   - contexto;
   - sequência;
   - decisão.
6. Foco principal:
   - evitar trades ruins;
   - selecionar menos trades, porém melhores;
   - deixar os dados ensinarem.

---

## 13. Frases-Chave do Projeto

```text
Indicadores medem. Dados ensinam. Leis decidem.

Não buscamos sinais. Descobrimos leis.

Não queremos mais trades. Queremos menos trades, mas melhores.

O mercado nunca é estático. Portanto, o conhecimento também não pode ser estático.

Não queremos ensinar o mercado para a IA. Queremos que o mercado ensine a IA.

O Chronos não é um indicador. É um motor de descoberta estatística.

O objetivo não é prever tudo. É evitar o que historicamente dá errado.
```

---

## 14. Próxima Ação Recomendada

A próxima ação é criar:

```text
tools/market_chronos_engine_v7.py
```

Com o módulo:

```text
Memory Engine
```

A V7 deve responder:

```text
Essa é a primeira tentativa de rompimento?
A segunda?
A terceira?
Já houve sweep antes?
Já houve false break antes?
A sequência está cansada?
O mercado está insistindo ou esgotando?
```

Essa etapa deve aproximar o Chronos do objetivo final:

```text
Decision Engine probabilístico
```

---

## 15. Status Atual

```text
Status: Discovery ativo
Ativo: GOLD
TF principal: M5
Última versão operacional: V6 Sequence DNA
Próxima versão: V7 Memory Engine
Objetivo final: Market Intelligence Platform / Chronos Engine
```

##  Validação científica da lei (Discovery → Robustez → Survival).
### Validação operacional (Decision Engine → Backtest → Walk Forward → Monte Carlo, Drift Detection).

E vou deixar uma frase para colocar no README, se gostar.

O Chronos não procura confirmar crenças. Procura descobrir evidências.

Cada descoberta deve sobreviver aos dados antes de sobreviver ao tempo.

"Não vendemos previsões. Construímos conhecimento sobre o comportamento do mercado."

####
E acho que já consigo enxergar o objetivo final do TradingAgent.

Não será apenas um robô que compra e vende.

Será um sistema composto por especialistas:

Market Intelligence → especialista em execução.
Market Chronos → especialista em comportamento e DNA do ativo.
Market Discovery → cientista que descobre novos padrões.
Market Validation → revisor que tenta derrubar hipóteses.
Market Laws → biblioteca permanente de conhecimento validado.
Decision Engine → gestor que toma a decisão final.
Execution Engine → executor que envia as ordens.

Na minha visão, essa arquitetura é muito sólida porque cada módulo tem uma responsabilidade clara e pode evoluir de forma independente. E o mais importante: cada nova descoberta que vocês fizerem poderá ser incorporada sem precisar reescrever o restante do sistema. É exatamente o tipo de base que permite construir conhecimento acumulativo ao longo do tempo.