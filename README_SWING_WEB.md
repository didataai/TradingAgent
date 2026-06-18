# Swing Web Agent

Copie os arquivos respeitando as pastas:

```text
TradingAgent/
├── agent/
│   └── web_swing_input_agent.py
├── context/
│   ├── build_swing_consolidated.py
│   ├── swing_timeframe_context.py
│   └── swing_prompt_payload.py
├── pipeline/
│   └── swing_pipeline_web.py
└── prompts/
    └── PromptPrevisaoSwing.md
```

Execução:

```powershell
python pipeline/swing_pipeline_web.py --symbol GOLD
```

Saída para anexar no ChatGPT Web:

```text
data\debug_llm\GOLD_swing_latest_input.txt
```

O arquivo é sobrescrito a cada execução. Não cria histórico e não chama LLM.

## Observação

O pipeline executa:

1. `intraday_refresh` para atualizar H1/M15;
2. `daily_refresh` para atualizar H4/D1/W1;
3. monta `GOLD_swing.parquet`;
4. gera contexto e payload;
5. gera o TXT para uso via Web.

Quando H1/M15 já estiverem suficientemente recentes:

```powershell
python pipeline/swing_pipeline_web.py --symbol GOLD --skip-intraday-refresh
```
