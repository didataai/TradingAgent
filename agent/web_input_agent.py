#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - Web Input Agent
==============================

Gera o arquivo de entrada completo para análise manual via ChatGPT Web,
usando o mesmo prompt e o mesmo MARKET_DATA que seriam enviados à LLM local,
sem chamar Ollama, API externa, crítico ou árbitro.

Antes de montar o input Web, este agente tenta enriquecer automaticamente o
payload com a camada EMA Exhaustion / Execution Quality, quando o script
`tools/ema_exhaustion_payload_enricher.py` estiver disponível.

Também tenta atualizar e anexar o contexto Synthetic Dollar/DXY quando o script
`tools/synthetic_dollar_context.py` estiver disponível. Essa camada é apenas
contextual e nunca deve gerar trade sozinha.

Saída:
    data/debug_llm/{SYMBOL}_{ANALYST}_latest_input.txt

Exemplos:
    python agent/web_input_agent.py --symbol GOLD
    python agent/web_input_agent.py --symbol GOLD --analyst analyst_1
    python agent/web_input_agent.py --symbol GOLD --profile quick
    python agent/web_input_agent.py --symbol GOLD --skip-ema-enrichment
    python agent/web_input_agent.py --symbol GOLD --skip-synthetic-dollar
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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
A análise técnica é produzida pela LLM, mas a ação imediata deve respeitar
historical_intelligence.formal_mtf_decision quando esse bloco existir.

Regras de preenchimento:
- immediate_action é obrigatório e não pode ser vazio.
- immediate_action deve ser uma instrução objetiva, por exemplo:
  "Esperar confirmação", "Comprar após rompimento" ou "Vender após rejeição".
- recommended_action_now.description deve explicar resumidamente a decisão.
'''


def safe_text(value: Any) -> str:
    """Converte texto para algo imprimível no console atual do Windows/Linux."""
    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def safe_print(*values: Any, sep: str = " ", end: str = "\n") -> None:
    try:
        print(sep.join(safe_text(v) for v in values), end=end)
    except UnicodeEncodeError:
        fallback = sep.join(str(v).encode("ascii", errors="replace").decode("ascii") for v in values)
        print(fallback, end=end)


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
    enabled = [profile for profile in ("quick", "detailed") if profiles.get(profile) is True]
    if len(enabled) != 1:
        raise ValueError("Exatamente um perfil deve estar True em agent.analysis_profiles: quick ou detailed.")
    return enabled[0]


def analyst_role(config: dict[str, Any], analyst_id: str) -> dict[str, Any]:
    analysts = config.get("llm", {}).get("roles", {}).get("analysts", [])
    for role in analysts:
        if role.get("id") == analyst_id and role.get("enabled", True):
            return role
    raise ValueError(f"Analista inválido ou desabilitado: {analyst_id}")


def prompt_path_for_profile(config: dict[str, Any], role: dict[str, Any], profile: str) -> Path:
    if profile == "quick":
        relative = config.get("agent", {}).get("quick_profile", {}).get("prompt_path", "prompts/promptIntradayQuick.md")
    else:
        relative = role.get("prompt_path")
    if not relative:
        raise ValueError(f"Prompt não configurado para analista={role.get('id')} profile={profile}.")
    path = ROOT / str(relative)
    if not path.exists():
        raise FileNotFoundError(f"Prompt não encontrado: {path}")
    return path


def payload_path(config: dict[str, Any], symbol: str) -> Path:
    template = config.get("agent", {}).get("paths", {}).get("payload_template", "data/payload/{symbol}_intraday_payload.json")
    return ROOT / str(template).format(symbol=symbol)


def synthetic_context_paths(symbol: str) -> tuple[Path, Path]:
    base_dir = ROOT / "data" / "market_context" / "synthetic_dollar"
    return (
        base_dir / f"{symbol}_synthetic_dollar_context.json",
        base_dir / f"{symbol}_synthetic_dollar_block.txt",
    )


def run_ema_enrichment(symbol: str, payload: Path, update_timeframe_parquets: bool) -> None:
    enricher = ROOT / "tools" / "ema_exhaustion_payload_enricher.py"
    if not enricher.exists():
        safe_print("[WARN] EMA enrichment ignorado: script não encontrado |", f"path={enricher}")
        return

    command = [sys.executable, str(enricher), "--symbol", symbol, "--payload", str(payload)]
    if update_timeframe_parquets:
        command.append("--write-timeframe-parquets")

    safe_print("[INFO] Executando EMA/Execution Quality enrichment antes do Web input |", f"symbol={symbol}")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.stdout:
        for line in completed.stdout.splitlines():
            safe_print("   ", line)
    if completed.returncode != 0:
        raise RuntimeError(f"EMA enrichment falhou antes do Web input. return_code={completed.returncode}")


def run_synthetic_dollar(symbol: str) -> None:
    builder = ROOT / "tools" / "synthetic_dollar_context.py"
    if not builder.exists():
        safe_print("[WARN] Synthetic Dollar ignorado: script não encontrado |", f"path={builder}")
        return

    command = [sys.executable, str(builder), "--symbol", symbol]
    safe_print("[INFO] Executando Synthetic Dollar context antes do Web input |", f"symbol={symbol}")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.stdout:
        for line in completed.stdout.splitlines():
            safe_print("   ", line)
    if completed.returncode != 0:
        # Contexto DXY nunca deve derrubar o fluxo Web. O payload seguirá sem essa camada.
        safe_print("[WARN] Synthetic Dollar indisponível antes do Web input |", f"return_code={completed.returncode}")


def attach_synthetic_dollar(payload: dict[str, Any], symbol: str) -> tuple[dict[str, Any], str | None]:
    context_path, block_path = synthetic_context_paths(symbol)
    if context_path.exists():
        try:
            context = read_json(context_path)
            synthetic = context.get("synthetic_dollar")
            if isinstance(synthetic, dict):
                payload = dict(payload)
                payload["synthetic_dollar"] = synthetic
        except Exception as exc:
            safe_print("[WARN] Falha ao anexar synthetic_dollar ao payload |", f"erro={type(exc).__name__}: {exc}")
    block = None
    if block_path.exists():
        try:
            block = block_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            safe_print("[WARN] Falha ao ler bloco Synthetic Dollar |", f"erro={type(exc).__name__}: {exc}")
    return payload, block


def build_prompt(
    *,
    config: dict[str, Any],
    role: dict[str, Any],
    profile: str,
    payload: dict[str, Any],
    synthetic_block: str | None = None,
) -> tuple[str, Path]:
    source_path = prompt_path_for_profile(config, role, profile)
    source = source_path.read_text(encoding="utf-8")
    market_data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    prompt = source.replace("{{MARKET_DATA}}", market_data)
    if synthetic_block:
        prompt += "\n\n" + synthetic_block + "\n"
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
    parser = argparse.ArgumentParser(description="Gera o input completo para análise manual via ChatGPT Web, sem chamar LLM.")
    parser.add_argument("--symbol", required=True, help="Símbolo, por exemplo GOLD.")
    parser.add_argument("--analyst", default="analyst_1", help="Analista usado para resolver prompt/modelo. Padrão: analyst_1.")
    parser.add_argument("--profile", choices=["quick", "detailed"], help="Sobrescreve temporariamente o perfil configurado.")
    parser.add_argument("--skip-ema-enrichment", action="store_true", help="Não enriquece o payload com execution_quality antes do input Web.")
    parser.add_argument("--skip-synthetic-dollar", action="store_true", help="Não atualiza/anexa o contexto Synthetic Dollar/DXY ao input Web.")
    parser.add_argument("--write-timeframe-parquets", action="store_true", help="Atualiza também os parquets data/<SYMBOL>_<TF>.parquet durante o enrichment.")
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

        if not args.skip_ema_enrichment:
            run_ema_enrichment(symbol=symbol, payload=current_payload_path, update_timeframe_parquets=args.write_timeframe_parquets)

        if not args.skip_synthetic_dollar:
            run_synthetic_dollar(symbol=symbol)

        payload = read_json(current_payload_path)
        synthetic_block = None
        if not args.skip_synthetic_dollar:
            payload, synthetic_block = attach_synthetic_dollar(payload, symbol)

        prompt, _source_prompt_path = build_prompt(
            config=config,
            role=role,
            profile=profile,
            payload=payload,
            synthetic_block=synthetic_block,
        )

        debug_dir = ROOT / "data" / "debug_llm"
        latest_path = debug_dir / f"{symbol}_{analyst_id}_latest_input.txt"
        write_text_atomic(latest_path, prompt)

        safe_print(
            "Web input gerado |",
            f"symbol={symbol} | analyst={analyst_id} | profile={profile}",
            f"| synthetic_dollar={not args.skip_synthetic_dollar}",
            f"| chars={len(prompt)} | llm_called=False",
        )
        safe_print(f"Arquivo gerado: {latest_path}")
        return 0
    except Exception as exc:
        safe_print(f"ERRO: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
