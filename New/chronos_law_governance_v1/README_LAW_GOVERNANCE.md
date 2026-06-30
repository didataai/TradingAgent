# Market Chronos — Law Governance v1

## Segurança principal

```text
Research não publica.
Validation não publica.
Somente approve altera o registry operacional.
```

## Instalação

Copie para a raiz do TradingAgent:

```text
tools/market_chronos_law_manager.py
schemas/law_candidate.schema.json
schemas/market_law.schema.json
schemas/law_registry.schema.json
data/market_chronos/GOLD/discovery/law_candidates.json
data/market_chronos/GOLD/validation/validation_report.json
data/market_chronos/GOLD/laws/market_laws_registry.json
data/market_chronos/GOLD/laws/approval_audit.jsonl
```

Dependência:

```powershell
pip install jsonschema
```

## Validação inicial

```powershell
python tools/market_chronos_law_manager.py validate --symbol GOLD
```

## Listar candidatos

```powershell
python tools/market_chronos_law_manager.py list-candidates --symbol GOLD
```

## Revisar candidato

```powershell
python tools/market_chronos_law_manager.py review `
  --symbol GOLD `
  --candidate-id CAND_20260715_001
```

## Aprovar

```powershell
python tools/market_chronos_law_manager.py approve `
  --symbol GOLD `
  --candidate-id CAND_20260715_001 `
  --by Diego `
  --reason "Amostra, OOS, walk-forward e janela recente aprovados"
```

Critérios padrão:

- status `VALIDATED` ou `PENDING_APPROVAL`;
- amostra >= 100;
- OOS aprovado;
- walk-forward aprovado;
- janela recente aprovada;
- confidence grade A ou B.

`--force` existe para exceções conscientes e fica registrado na auditoria.

## Rejeitar

```powershell
python tools/market_chronos_law_manager.py reject `
  --symbol GOLD `
  --candidate-id CAND_20260715_001 `
  --by Diego `
  --reason "Instável na janela recente"
```

## Leis operacionais

```powershell
python tools/market_chronos_law_manager.py list-laws `
  --symbol GOLD `
  --enabled-only
```

## Desabilitar

```powershell
python tools/market_chronos_law_manager.py disable `
  --symbol GOLD `
  --law-id LAW_0001 `
  --by Diego `
  --reason "Expectancy recente degradada"
```

## Reabilitar

```powershell
python tools/market_chronos_law_manager.py enable `
  --symbol GOLD `
  --law-id LAW_0001 `
  --by Diego `
  --reason "Lei recuperou estabilidade após nova validação"
```

## Arquivos de controle

```text
laws/market_laws_registry.json  → runtime deve ler somente este
laws/backups/                   → backup antes de cada alteração
laws/approval_audit.jsonl       → trilha append-only
discovery/law_candidates.json   → nunca lido pelo runtime
validation/validation_report.json
```

## Integração pendente

O runtime deve filtrar estritamente:

```python
law["status"] == "APPROVED" and law["enabled"] is True
```

e nunca ler arquivos de `discovery/` ou `validation/`.
