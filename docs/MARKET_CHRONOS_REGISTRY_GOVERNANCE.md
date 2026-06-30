# Market Chronos — Governança Segura do Registry

## Problema resolvido

O `market_chronos_engine_v10_1.py` grava o registry em:

```text
data/market_chronos/<SYMBOL>/laws/market_laws_registry.json
```

Executar o research diretamente com o output padrão pode sobrescrever o registry operacional usado pelo runtime live.

A governança agora separa:

```text
Research em staging
→ Review e diff
→ Aprovação explícita
→ Publish atômico
→ Backup e auditoria
```

## 1. Research seguro

Execute:

```powershell
python tools/market_chronos_research_runner.py `
  --symbol GOLD `
  --anchor-tf M5
```

O runner cria uma pasta exclusiva:

```text
data/market_chronos/GOLD/research_staging/<RUN_ID>/
├── engine/
├── laws/
│   └── market_laws_registry.json
└── research_manifest.json
```

O arquivo gerado em `research_staging` é um **registry candidato**. Ele não é lido pelo runtime.

## 2. Review e comparação

Use o caminho mostrado pelo runner:

```powershell
python tools/market_chronos_registry_manager.py review `
  --symbol GOLD `
  --anchor-tf M5 `
  --candidate .\data\market_chronos\GOLD\research_staging\<RUN_ID>\laws\market_laws_registry.json
```

Saída de revisão:

```text
data/market_chronos/GOLD/laws/review/registry_diff_latest.json
```

O relatório mostra:

- leis adicionadas;
- leis removidas;
- leis alteradas;
- campos alterados;
- mudanças de tier;
- mudanças de validation status;
- mudanças de amostra e OOS edge;
- hashes do registry atual e do candidato.

## 3. Publicação aprovada

Depois da revisão:

```powershell
python tools/market_chronos_registry_manager.py publish `
  --symbol GOLD `
  --anchor-tf M5 `
  --candidate .\data\market_chronos\GOLD\research_staging\<RUN_ID>\laws\market_laws_registry.json `
  --approved-by Diego `
  --reason "Research quinzenal revisado e aprovado" `
  --expected-candidate-hash <HASH_MOSTRADO_NO_REVIEW>
```

O hash impede publicar um arquivo que mudou depois da revisão.

Por padrão, a publicação é bloqueada quando o candidato remove leis. Para autorizar conscientemente:

```powershell
--allow-removals
```

## 4. Backups e auditoria

Antes da publicação, o registry atual é salvo em:

```text
data/market_chronos/GOLD/laws/backups/
```

A auditoria append-only fica em:

```text
data/market_chronos/GOLD/laws/registry_approval_audit.jsonl
```

## 5. Rollback

```powershell
python tools/market_chronos_registry_manager.py rollback `
  --symbol GOLD `
  --anchor-tf M5 `
  --backup .\data\market_chronos\GOLD\laws\backups\market_laws_registry_<TIMESTAMP>.json `
  --approved-by Diego `
  --reason "Rollback após comportamento inesperado"
```

O rollback também cria um backup emergencial do registry que estava ativo.

## 6. Rotina quinzenal completa

```powershell
cd C:\Users\diego\Desktop\Python\TradingAgent

python tools/base_dados_candle.py `
  --symbol GOLD `
  --mode full_rebuild `
  --timeframes M1 M5 M15 H1 H4

python tools/market_chronos_dataset.py `
  --symbol GOLD `
  --input data/market_chronos/candle_base/consolidated/GOLD_candle_research.parquet

python tools/market_chronos_research_runner.py `
  --symbol GOLD `
  --anchor-tf M5
```

Depois:

```text
review
→ analisar registry_diff_latest.json
→ publish explícito ou não publicar
```

## Regra definitiva

```text
Rodar research não altera leis operacionais.
Validar não altera leis operacionais.
Somente publish explícito altera o registry live.
```
