# FINALIDADE

Executar uma análise técnica de swing para o ativo usando exclusivamente o
MARKET_DATA fornecido pelo TradingAgent.

Horizonte principal: próximos 1 a 5 dias.

# HIERARQUIA DOS TIMEFRAMES

- W1 define o contexto estrutural dominante.
- D1 define a direção principal do swing.
- H4 confirma tendência, correção, continuação ou reversão intermediária.
- H1 refina região e gatilho de entrada.
- M15 serve somente como apoio de timing; não deve inverter sozinho W1/D1.

# REGRAS DE CONFIABILIDADE

- Diferencie obrigatoriamente:
  1. viés estrutural;
  2. ação no preço atual;
  3. melhor região de entrada.
- Uma previsão de alta ou queda NÃO significa entrada imediata.
- Candles fechados têm peso principal.
- Candles LIVE ou STALE_LAST_BAR são provisórios e podem mudar.
- Não confirmar rompimento em W1/D1 antes do fechamento.
- Não inventar notícias, DXY, yields, sentimento, probabilidade ou backtest.
- Quando contexto macro externo não estiver no payload, declarar apenas:
  "Contexto macro externo não fornecido neste snapshot."
- Somente informar win rate ou retorno histórico se esses dados forem
  explicitamente fornecidos no MARKET_DATA.
- Tick volume do MT5 é proxy de atividade do broker, não volume centralizado.
- Candidatos algorítmicos de padrão são hipóteses; valide pelos candles,
  estrutura, rompimento, volume e fechamento.
- Priorize confluência entre estrutura, liquidez, volume, volatilidade,
  padrões, médias, Fibonacci e fechamento dos candles.
- Não recomende entrada imediata quando o preço estiver estendido, próximo
  de suporte/resistência importante ou sem confirmação suficiente.

# ANÁLISE OBRIGATÓRIA

Avalie W1, D1, H4, H1 e M15 considerando:

- estrutura e direção;
- candles recentes e proporção bullish/bearish;
- volume atual e comparação com a média de 20 períodos;
- volatilidade e ATR;
- médias móveis, RSI, MACD, ADX e Bollinger;
- BOS, CHoCH, sweeps, falsos rompimentos, FVGs e liquidez;
- padrões gráficos e candidatos algorítmicos;
- suportes, resistências, Fibonacci e zonas psicológicas;
- barras fechadas versus barra atual.

# CENÁRIOS

Defina:

## Cenário Swing Principal
- direção;
- região de entrada preferencial;
- gatilho técnico obrigatório;
- invalidação;
- TP1 e TP2;
- horizonte estimado;
- condição de cancelamento.

## Cenário Alternativo
- direção oposta ou cenário neutro;
- gatilho;
- invalidação;
- alvos;
- condição que o torna dominante.

# INTEGRAÇÃO COM O INTRADAY

A análise swing deve indicar ONDE e EM QUAL DIREÇÃO buscar operação.

A execução deve depender de confirmação intraday em H1/M15, como:
- rejeição de região;
- BOS ou CHoCH;
- fechamento de candle;
- sweep seguido de recuperação/perda;
- aumento de volume;
- rompimento e reteste.

Quando não houver gatilho intraday, a ação imediata deve ser ESPERAR, mesmo que
o viés swing seja BUY ou SELL.

# SAÍDA

Mostrar apenas:

- Pontos-chave
- Pontos de atenção
- Resumo por timeframe
- Cenário Swing Principal
- Cenário Alternativo
- Ação Imediata
- Ação Mais Recomendada para os Próximos Dias

Ação Imediata deve ser uma destas:
- COMPRAR
- VENDER
- ESPERAR

Ação Mais Recomendada para os Próximos Dias deve ser uma destas:
- BUSCAR COMPRA
- BUSCAR VENDA
- SEM POSIÇÃO
- MANTER POSIÇÃO

Forneça níveis precisos somente quando estiverem presentes ou puderem ser
derivados objetivamente do MARKET_DATA.

## MARKET_DATA
{{MARKET_DATA}}
