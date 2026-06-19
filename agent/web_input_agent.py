#!/usr/bin/env python3
"""
TradingAgent - Web Input Agent

FINALIDADE
    Gerar o arquivo de entrada completo para análise manual via ChatGPT Web,
    usando o mesmo prompt e o mesmo MARKET_DATA que seriam enviados à LLM local,
    sem chamar Ollama, API externa, crítico ou árbitro.

ENTRADAS
    - tradingagent.json na raiz do projeto.
    - data/payload/{symbol}_intraday_payload.json.
    - prompt configurado para o perfil quick/detailed.
    - analista configurado em llm.roles.analysts.

PROCESSAMENTO / ETAPAS
    1. Carrega a configuração e seleciona o analista.
    2. Resolve o perfil de análise efetivo.
    3. Carrega o payload factual atualizado.
    4. Monta exatamente o texto do prompt com MARKET_DATA e schema de saída.
    5. Salva somente o arquivo latest, sobrescrevendo a rodada anterior.

SAÍDAS
    - data/debug_llm/{SYMBOL}_{ANALYST}_latest_input.txt

DEPENDÊNCIAS
    - Python 3.10+.
    - tradingagent.json válido.
    - payload factual já gerado pelo pipeline.
    - prompt configurado existente.

EXEMPLOS
    python agent/web_input_agent.py --symbol GOLD
    python agent/web_input_agent.py --symbol GOLD --analyst analyst_1
    python agent/web_input_agent.py --symbol GOLD --profile quick

TRATAMENTO DE ERROS
    - Falha com mensagem objetiva quando configuração, payload ou prompt não existem.
    - Valida o analista e o perfil antes de gerar os arquivos.
    - Usa gravação atômica para o arquivo latest e para os metadados.

LIMITAÇÕES / OBSERVAÇÕES
    - Não executa análise e não retorna BUY/SELL/WAIT.
    - Não chama LLM local nem API.
    - O arquivo latest é sobrescrito a cada rodada.
    - Não cria histórico nem arquivo adicional de metadados.
    - O conteúdo gerado pode ser enviado manualmente ao ChatGPT Web.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "tradingagent.json"


ANALYST_SCHEMA = '''
Responda SOMENTE com JSON válido, sem Markdown:
{
  "action": "BUY|SELL|WAIT",
  "confidence": "LOW|MODERATE|HIGH",
  "summary": "interpretação da ação imediata",
  "previous_thesis_evaluation": {
    "status": "CONFIRMED|PARTIALLY_CONFIRMED|STILL_DEVELOPING|INVALIDATED|EXPIRED|REPLACED|NO_PREVIOUS_THESIS",
    "reason": "explique objetivamente o que aconteceu com a tese anterior"
  },
  "timeframes": {"H1":"...","M15":"...","M5":"...","M1":"somente timing"},
  "patterns": [],
  "trade_plan": {
    "action_now": "BUY|SELL|WAIT",
    "conditional_bias": "BUY|SELL|NEUTRAL",
    "trigger": null,
    "entry_min": null,
    "entry_max": null,
    "stop": null,
    "target_1": null,
    "target_2": null
  },
  "confirmation_conditions": [],
  "invalidation_conditions": [],
  "risk_flags": [],
  "current_thesis": {
    "scenario": "identificador curto",
    "action_now": "BUY|SELL|WAIT",
    "conditional_bias": "BUY|SELL|NEUTRAL",
    "summary": "nova tese da rodada atual",
    "trigger": null,
    "invalidation": null,
    "expiry_minutes": 15
  }
}
Regras adicionais:
- previous_thesis_evaluation descreve somente a tese recebida na memória.
- current_thesis descreve somente a nova tese criada nesta rodada.
- action é a ação imediata e deve ser igual a trade_plan.action_now.
- Se action=WAIT, conditional_bias pode ser BUY, SELL ou NEUTRAL.
- Não use o termo invalidation sem deixar claro se é invalidação da nova tese.
- Não reutilize a tese anterior como nova tese sem explicar por que ela continua válida.
- Não invente níveis, probabilidades ou fatos ausentes.
- A memória serve para testar a tese anterior, não para defendê-la.
'''


QUICK_ANALYST_SCHEMA = '''

Retorne SOMENTE JSON válido, sem Markdown e sem texto fora do JSON:
{
  "action": "BUY|SELL|WAIT",
  "confidence": "LOW|MODERATE|HIGH",
  "key_points": [],
  "attention_points": [],
  "timeframe_summary": {
    "H4": "",
    "H1": "",
    "M15": "",
    "M5": ""
  },
  "immediate_action": "",
  "recommended_action_now": {
    "action": "BUY|SELL|WAIT",
    "description": ""
  }
}

O JSON é apenas o formato de transporte.
A análise, direção e recomendação devem ser definidas livremente pela LLM
a partir do prompt original e do MARKET_DATA.

Regras de preenchimento:
- immediate_action é obrigatório e não pode ser vazio.
- immediate_action deve ser uma instrução objetiva, por exemplo:
  "Esperar confirmação", "Comprar após rompimento" ou "Vender após rejeição".
- recommended_action_now.description deve explicar resumidamente a decisão.
'''




def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON deve conter um objeto: {path}")
    return data


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)




def effective_profile(config: dict[str, Any], cli_profile: str | None) -> str:
    if cli_profile:
        return cli_profile

    profiles = config.get("agent", {}).get("analysis_profiles", {})
    enabled = [
        profile
        for profile in ("quick", "detailed")
        if profiles.get(profile) is True
    ]
    if len(enabled) != 1:
        raise ValueError(
            "Exatamente um perfil deve estar True em "
            "agent.analysis_profiles: quick ou detailed."
        )
    return enabled[0]


def analyst_role(config: dict[str, Any], analyst_id: str) -> dict[str, Any]:
    analysts = config.get("llm", {}).get("roles", {}).get("analysts", [])
    for role in analysts:
        if role.get("id") == analyst_id and role.get("enabled", True):
            return role
    raise ValueError(f"Analista inválido ou desabilitado: {analyst_id}")


def prompt_path_for_profile(
    config: dict[str, Any],
    role: dict[str, Any],
    profile: str,
) -> Path:
    if profile == "quick":
        relative = (
            config.get("agent", {})
            .get("quick_profile", {})
            .get("prompt_path", "prompts/promptIntradayQuick.md")
        )
    else:
        relative = role.get("prompt_path")

    if not relative:
        raise ValueError(
            f"Prompt não configurado para analista={role.get('id')} "
            f"profile={profile}."
        )

    path = ROOT / str(relative)
    if not path.exists():
        raise FileNotFoundError(f"Prompt não encontrado: {path}")
    return path


def payload_path(config: dict[str, Any], symbol: str) -> Path:
    template = (
        config.get("agent", {})
        .get("paths", {})
        .get("payload_template", "data/payload/{symbol}_intraday_payload.json")
    )
    return ROOT / str(template).format(symbol=symbol)


def build_prompt(
    *,
    config: dict[str, Any],
    role: dict[str, Any],
    profile: str,
    payload: dict[str, Any],
) -> tuple[str, Path]:
    source_path = prompt_path_for_profile(config, role, profile)
    source = source_path.read_text(encoding="utf-8")
    market_data = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    prompt = source.replace("{{MARKET_DATA}}", market_data)

    if profile == "quick":
        prompt += QUICK_ANALYST_SCHEMA
    else:
        model_ref = role.get("model_ref")
        model_cfg = config.get("llm", {}).get("models", {}).get(model_ref, {})
        prompt += (
            f"\n\nVocê é {role.get('id')}. "
            f"Propósito: {model_cfg.get('purpose', '')}. "
            f"Foco: {model_cfg.get('focus', [])}."
            + ANALYST_SCHEMA
        )

    return prompt, source_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Gera o input completo para análise manual via ChatGPT Web, "
            "sem chamar LLM."
        )
    )
    parser.add_argument("--symbol", required=True, help="Símbolo, por exemplo GOLD.")
    parser.add_argument(
        "--analyst",
        default="analyst_1",
        help="Analista usado para resolver prompt/modelo. Padrão: analyst_1.",
    )
    parser.add_argument(
        "--profile",
        choices=["quick", "detailed"],
        help="Sobrescreve temporariamente o perfil configurado.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbol = args.symbol.upper().strip()
    analyst_id = args.analyst.strip()

    try:
        config = read_json(CONFIG_PATH)
        profile = effective_profile(config, args.profile)
        role = analyst_role(config, analyst_id)
        current_payload_path = payload_path(config, symbol)
        payload = read_json(current_payload_path)

        prompt, _source_prompt_path = build_prompt(
            config=config,
            role=role,
            profile=profile,
            payload=payload,
        )

        debug_dir = ROOT / "data" / "debug_llm"
        latest_path = debug_dir / f"{symbol}_{analyst_id}_latest_input.txt"
        write_text_atomic(latest_path, prompt)

        print(
            "Web input gerado | "
            f"symbol={symbol} | analyst={analyst_id} | profile={profile} "
            f"| chars={len(prompt)} | llm_called=False"
        )
        print(f"Arquivo gerado: {latest_path}")
        return 0

    except Exception as exc:
        print(f"ERRO: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
