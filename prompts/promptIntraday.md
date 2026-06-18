# FINALIDADE
Executar o prompt intraday original do usuário utilizando os dados atuais fornecidos
pelo TradingAgent para H4, H1, M15, M5 e M1.

# ENTRADAS
- Prompt intraday original.
- MARKET_DATA atualizado pelo pipeline.
- Ativo, data, horário BRT e preço atual presentes no payload.

# PROCESSAMENTO / ETAPAS
- A LLM interpreta livremente o prompt e os dados recebidos.
- Não há memória anterior no prompt quick.
- Não há regra direcional, comparação obrigatória, guard de direção ou indução BUY/SELL.
- H4 deve ser incluído na análise, além de H1, M15 e M5.
- M1 pode ser utilizado como apoio de timing.

# SAÍDAS
Mostrar apenas:
- Pontos-chave
- Pontos de atenção
- Resumo por timeframe
- Ação Imediata
- Ação Mais Recomendada Agora

# DEPENDÊNCIAS
- Payload factual gerado pelo TradingAgent.
- Modelo LLM configurado no tradingagent.json.

# EXEMPLOS
- Ação Mais Recomendada Agora: COMPRAR, VENDER ou ESPERAR.
- A recomendação pode sugerir entrada imediata, pullback, rompimento ou espera,
  conforme a interpretação livre da LLM.

# TRATAMENTO DE ERROS
- Caso a resposta não possa ser convertida para o formato interno, o agente retorna WAIT
  e registra que a resposta foi inválida.

# LIMITAÇÕES / OBSERVAÇÕES
- O modelo local não possui web_search ou x_keyword_search nativos.
- Notícias, DXY, yields, sentimento externo e dados macro só estarão disponíveis
  quando forem adicionados ao payload ou por uma ferramenta externa.
- A parte técnica utiliza os dados H4 até M1 fornecidos pelo pipeline.

---

As a trading expert specializing in intraday and scalping strategies, provide a concise intraday analysis for GOLD on [Dia Atual] at [HORÁRIO ATUAL] BRT, with the current price at [PREÇO ATUAL]. Focus on actionable setups across H1, M15, and M5 timeframes (priorize esses para foco em intraday, evitando H4 em baixa vol), covering:

Análise Técnica Multi-Timeframe (MTF):
H1 (1 Hora): Tactical entries, key levels, candlestick patterns, indicators, and order flow with emphasis on stop hunts e Smart Money Concepts (SMC, ex.: liquidity sweeps, FVGs como alvos).
M15 (15 Minutos): Scalping opportunities, precise levels, quick patterns, indicators, and order flow.
M5 (5 Minutos): Ultra-short-term scalping, precise levels, micro-patterns, indicators, and order flow.
For each timeframe, provide:
Active chart patterns (e.g., triangles, channels, harmonics like Gartley/Bat, incluindo flags como padrões de continuação). If no clear continuation patterns are present, ask: "Is there a continuation pattern I should consider here?"
Support/resistance levels and Fibonacci (retracement/extension), com ênfase em confluências (ex.: rompimento com volume >1.5x + RSI <70 + suporte Fib 61.8%).
Technical indicators (e.g., RSI, MACD, CCI, EMA/SMA, ADX, Bollinger Bands), priorizando fluxo de ordens, candles e padrões técnicos sobre RSI (secundário, ex.: RSI sobrecomprado >70 como filtro para sells).
Order flow (e.g., liquidity zones, FVGs, stop hunts, volume spikes), expandindo para SMC: liquidity sweeps (ex.: hunt stops abaixo suporte antes de alta) e FVGs como alvos precisos.
Identify specific liquidity zones (e.g., accumulation of stop-losses above resistances or below supports) and their relevance to setups.
Avalie o sentimento de força direcional dos candles nos últimos 5-10 períodos (7 para H1, 5 para M15/M5), calculando a proporção de candles bullish (verdes) vs. bearish (vermelhos) e comparando o volume médio com a média de 20 períodos, com ênfase em picos de volume (>1,5x média) como indicador de força ou exaustão. Identifique padrões como Doji, Hammer, ou Shooting Star e sua relação com o volume para antecipar reversões ou continuidades. Dar maior peso a padrões de continuação (ex.: fundo duplo) e rompimentos com volume >1,5x média, especialmente em M15/H1.
Ao identificar padrões gráficos, harmônicos ou níveis de Fibonacci, forneça um backtesting resumido incluindo win rate, R:R médio, e retorno médio (ex.: para fundo duplo em ouro 2023-2025, win rate 70%, R:R 1:3, retorno +10% com volume spike). Use exemplos reais (se disponíveis) e alinhe com a análise atual, considerando RSI, volume (>1,5x média), e contexto macro (DXY, geopolítica).

Previsão de Preço:
Primary Scenario: Expected movement (bullish/bearish), entry levels, TP, SL, probability (e.g., 70%, ajustada com confluências para >70%), and timeframe (e.g., until the day's close). Apenas recomende trades com prob >70% baseado em confluências (volume + padrão + indicador).
Alternative Scenario: Opposite movement, with triggers, levels, TP, SL, and probability.
R:R: Risk-to-reward ratio for each scenario (e.g., 1:3 mínimo, com SL apertado em ATR/2 e TP em extensão Fib 161.8%).
Triggers: Events or technical conditions validating each scenario (e.g., level breakout, reversal candle, volume spike). Inclua o sentimento dos candles (ex.: proporção 80% venda/20% compra com volume do Doji < média) como um trigger adicional para validar entradas, especialmente para reversões rápidas. Inclua probabilidade de breakout com interpretação (ex.: 65% se volume >1.5x, baseado em histórico).
Considerar confluência com Fibonacci, exemplo "Preço esta em confluência com Fibonacci 61.8%, assim aumenta probabilidade" , caso apoie o vies da previsão.

Gestão de Risco:
Recommend risk per trade (e.g., 1–2% of capital, ajustado para 0.5% em baixa vol).
Suggest position size based on SL (e.g., for $100 risk, SL $50 → 2 lots), com sizing dinâmico (risco max <1% e simule drawdown em vol alta).
Include strategies like trailing stops ($2–$3 on M5 for scalping, dinâmicos após +ATR), partial exits (50% em TP1), and protection against stop hunts (ex.: evite entradas em níveis psicológicos sem volume; implemente "no-trade zones" durante hunts).

Integração com Minha Estratégia:
My strategy: Scalping on M5 with RSI/MACD (RSI > 70 to sell, < 30 to buy, MACD to confirm trend), focusing on order flow and stop hunts.
Filters: Avoid entries during stop hunts (e.g., breakout of a level with high volume followed by reversal); require volume spike (volume > 20-period average on M5); use a trailing stop of $2–$3 on M5. Priorize fluxo de ordens sobre RSI (secundário); filtre entradas com 70% candles bearish + volume >1.5x para sells, e Doji com vol <média para reversões buy. Adicione filtro SMC (FVGs) e backtest win rate no prompt.
Incorpore a análise de força dos candles (ex.: 70%+ candles bearish with volume 1,5x above the average for sells, or Doji/Hammer with volume < average for buys) as a filter in the M5 strategy, maximizing the identification of reversals.
Suggest how to integrate my strategy with the analysis, maximizing profitability (ex.: adicione confluência Fib para entradas, priorize setups pós-Londres em picos vol para R:R >1:3).

Instruções Adicionais:
Use the most recent price ([PREÇO ATUAL]) and market data (e.g., X posts, news). Use web_search para cotação atual e news; x_keyword_search para sentiment no X sobre 'gold trading 2025' (com filter:news, min_faves:5) e ajuste probabilidade com sentiment 70%+ bullish.
Align the analysis with Brasília time (BRT, [HORÁRIO ATUAL]).
Provide precise levels (entries, TPs, SLs) and clear justifications.
Inclua uma análise da volatilidade atual (ex.: ATR) e sugira as melhores sessões de mercado (ex.: Londres, NY) para os setups propostos, correlacionando os horários com picos de volatilidade (ex.: NY 13:00-18:00 BRT, vol 1.5x maior em news como tarifas, prob 70% spikes).
Inclua níveis psicológicos (ex.: $3.340, $3.350) como suportes/resistências adicionais e sua influência no fluxo de ordens.
Avalie a correlação com o DXY ou outros ativos (ex.: prata) e seu impacto nos movimentos esperados (ex.: se DXY >98, priorize shorts; integre news geopolíticas como triggers, elevando ouro em 8-10% históricos).
Reavalie o sentimento de força direcional dos candles (proporção bullish/bearish e volume) a cada pedido, usando os 5 candles mais recentes fechados no M5, e ajuste os percentuais com base em dados em tempo real, validando com picos de volume (>1,5x média) e padrões confirmatórios.
Inclua um resumo final com as seções: 1. Interpretação, resumindo o sentimento do mercado com base em padrões e indicadores; 2. Pontos Chave, listando níveis de entrada, TP e SL; 3. Pontos de Atenção, destacando ações imediatas baseadas nos níveis atuais; 4. Resumo por Timeframe, fornecendo 2 linhas por timeframe (H1, M15, M5) com tendência, padrão principal, nível chave e sentimento; 5. Pontos de Atenção para Padrões Futuros, alertando sobre padrões em formação nos timeframes H1, M15 e M5; 6. Lucratividade Projetada, baseado em backtest (ex.: setup primário tem retorno médio +12% com R:R 1:4).
Inclua interpretação para os próximos passos utlizando as informações geradas como variaveis.
Adicionar analise sobre o volume e volatilidade conforme o horario baseando-se em historicos e probabilides na interpretacao. 
Dar maior peso a padrões de continuação (ex.: fundo duplo) e rompimentos com volume >1,5x média, especialmente em M15/H1. Reavaliar RSI sobrecomprado como filtro secundário, priorizando fluxo de ordens, candles e padrões técnicos.
Quando possivel e valido, sugestoes como: "Alternativamente, esperar fechamento H1 (10:00 BRT) para reduzir risco."; foi feita faltando 10min para o fechamento, por exemplo. Apenas quando valida.
Por favor, forneça a análise para [ATIVO] em [DATA ESPECÍFICA], incluindo todos os pontos acima. Se possível, valide com dados recentes (ex.: última cotação, sentiment no X) e sugira próximos passos (ex.: monitorar eventos, ajustar script).
Concise: Focuses on key timeframes and actionable insights.
Comprehensive: Covers macro context, technical patterns (including flags), breakout probabilities, and trade setups.
Flexible: Works for repeated intraday analyses, adaptable to any asset.
Volume Distortion: Accounts for potential distortions at key candle closes (e.g., 13:00 BRT H1 close), as you noted.
Breakout Probabilities: Includes probability metrics for breakouts, which you found helpful for trading decisions.
Next Steps
Save the Prompt: Use this prompt for future intraday analyses on GOLD or other assets.
Strategy Details: Share your M5 scalping strategy to integrate with the prompt.


Qual ação mais recomendada agora? comprar, vender ou esperar ?

Adicionar H4 na análise, usando os dados fornecidos em MARKET_DATA.
Mostrar apenas Pontos-chave, Pontos de atenção, Resumo por timeframe,
Ação Imediata e Ação Mais Recomendada Agora.

## MARKET_DATA
{{MARKET_DATA}}
