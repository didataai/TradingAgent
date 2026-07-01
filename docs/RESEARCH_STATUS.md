# TradingAgent — Research Status

## Linha principal

1. **Chronos / rompimentos** — motor principal de eventos.
2. **Market Intelligence** — contexto, regime, pressão, volatilidade e estrutura.
3. **Volatility DNA** — anatomia e comportamento do rompimento.
4. **Figuras clássicas** — feature secundária; não devem comandar uma entrada isoladamente.

## Conclusão da pesquisa de figuras

A pesquisa consolidada avaliou triângulos e ranges em M5, M15 e H1, com contexto H1/H4.
Os resultados foram frágeis e muito específicos. Houve mais utilidade como filtro negativo do que como fonte principal de edge.

Os scripts permanecem no repositório para reprodutibilidade:

- `tools/market_pattern_research_consolidated.py`
- `tools/market_pattern_research_consolidated_exploratory.py`

As saídas desses scripts são regeneráveis e não devem ser versionadas.

## Pesquisa ativa

A próxima etapa é a mineração hierárquica de contexto:

- baseline por lado e horizonte;
- teste de uma feature por vez;
- combinações de duas features somente quando a feature individual mostra lift;
- eventos temporalmente independentes;
- treino/teste cronológico;
- comparação contra baseline, não apenas taxa absoluta;
- resultados positivos e negativos como regras candidatas ou filtros.

## Higiene do repositório

Não versionar:

- `__pycache__` e `*.pyc`;
- logs e manifests de execução;
- parquets e planilhas regeneráveis;
- resultados locais de pesquisas exploratórias;
- snapshots de `research_staging`.

O `.gitignore` da raiz contém as regras canônicas.
