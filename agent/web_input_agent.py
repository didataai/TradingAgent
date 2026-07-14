#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - Web Input Agent
==============================

Gera o arquivo de entrada completo para analise manual via ChatGPT Web,
usando o mesmo prompt e o mesmo MARKET_DATA que seriam enviados a LLM local,
sem chamar Ollama, API externa, critico ou arbitro.

Antes de montar o input Web, este agente tenta enriquecer automaticamente o
payload com camadas auxiliares, quando os scripts estiverem disponiveis:

1. EMA Exhaustion / Execution Quality
   - script: tools/ema_exhaustion_payload_enricher.py
   - semantica: WARNING_ONLY

2. Technical Patterns Context
   - script: tools/technical_patterns_payload_enricher.py
   - semantica: CONTEXT_ONLY

3. Pattern Attempt Edge Context
   - script: tools/pattern_attempt_edge_payload_enricher.py
   - semantica: CONTEXT_ONLY / WARNING_ONLY
   - le os CSVs de data/research/pattern_attempt/<SYMBOL>/ quando existirem
   - filtra estatisticas de fakeout/aceitacao por padrao, tentativa, horario,
     sessao, dia da semana e semana do mes.

4. Fakeout Return Setup Context
   - script: tools/fakeout_return_setup_payload_enricher.py
   - semantica: CONTEXT_ONLY / WARNING_ONLY
   - transforma alto risco de fakeout em leitura de setup de retorno/fade,
     sem virar ordem automatica.

5. Console summary
   - apenas imprime um resumo curto no PowerShell/Linux apos o enrichment.
   - exibe patterns/edge/fakeout em linhas por timeframe.
   - nao altera payload, prompt, MARKET_DATA ou decisao.

Nenhuma dessas camadas sobrescreve Historical Intelligence, Chronos hard blocks,
Personal Guard ou regra M5 pessoal.

Saida:
    data/debug_llm/{SYMBOL}_{ANALYST}_latest_input.txt

Exemplos:
    python agent/web_input_agent.py --symbol GOLD
    python agent/web_input_agent.py --symbol GOLD --analyst analyst_1
    python agent/web_input_agent.py --symbol GOLD --profile quick
    python agent/web_input_agent.py --symbol GOLD --skip-ema-enrichment
    python agent/web_input_agent.py --symbol GOLD --skip-technical-patterns
    python agent/web_input_agent.py --symbol GOLD --skip-pattern-attempt-edge
    python agent/web_input_agent.py --symbol GOLD --skip-fakeout-return-setup
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
CONSOLE_TF_ORDER = ("M15", "M5", "M1", "H1")

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
        fallback = sep.join(
            str(v).encode("ascii", errors="replace").decode("ascii")
            for v in values
        )
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
        raise ValueError(
            "Exatamente um perfil deve estar True em agent.analysis_profiles: quick ou detailed."
        )
    return enabled[0]


def analyst_role(config: dict[str, Any], analyst_id: str) -> dict[str, Any]:
    analysts = config.get("llm", {}).get("roles", {}).get("analysts", [])
    for role in analysts:
        if role.get("id") == analyst_id and role.get("enabled", True):
            return role
    raise ValueError(f"Analista inválido ou desabilitado: {analyst_id}")


def prompt_path_for_profile(config: dict[str, Any], role: dict[str, Any], profile: str) -> Path:
    if profile == "quick":
        relative = config.get("agent", {}).get("quick_profile", {}).get(
            "prompt_path", "prompts/promptIntradayQuick.md"
        )
    else:
        relative = role.get("prompt_path")
    if not relative:
        raise ValueError(
            f"Prompt não configurado para analista={role.get('id')} profile={profile}."
        )
    path = ROOT / str(relative)
    if not path.exists():
        raise FileNotFoundError(f"Prompt não encontrado: {path}")
    return path


def payload_path(config: dict[str, Any], symbol: str) -> Path:
    template = config.get("agent", {}).get(
        "paths", {}
    ).get("payload_template", "data/payload/{symbol}_intraday_payload.json")
    return ROOT / str(template).format(symbol=symbol)


def run_helper_script(*, label: str, script: Path, command_args: list[str], required: bool) -> bool:
    if not script.exists():
        safe_print(f"[WARN] {label} ignorado: script não encontrado |", f"path={script}")
        return False

    command = [sys.executable, str(script), *command_args]
    safe_print(f"[INFO] Executando {label} antes do Web input")
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
        message = f"{label} falhou antes do Web input. return_code={completed.returncode}"
        if required:
            raise RuntimeError(message)
        safe_print("[WARN]", message)
        return False
    return True


def run_ema_enrichment(symbol: str, payload: Path, update_timeframe_parquets: bool) -> bool:
    args = ["--symbol", symbol, "--payload", str(payload)]
    if update_timeframe_parquets:
        args.append("--write-timeframe-parquets")
    return run_helper_script(
        label=f"EMA/Execution Quality enrichment | symbol={symbol}",
        script=ROOT / "tools" / "ema_exhaustion_payload_enricher.py",
        command_args=args,
        required=True,
    )


def run_technical_patterns(symbol: str, payload: Path) -> bool:
    return run_helper_script(
        label=f"Technical Patterns enrichment | symbol={symbol}",
        script=ROOT / "tools" / "technical_patterns_payload_enricher.py",
        command_args=["--symbol", symbol, "--payload", str(payload)],
        required=False,
    )


def run_pattern_attempt_edge(symbol: str, payload: Path) -> bool:
    return run_helper_script(
        label=f"Pattern Attempt Edge enrichment | symbol={symbol}",
        script=ROOT / "tools" / "pattern_attempt_edge_payload_enricher.py",
        command_args=["--symbol", symbol, "--payload", str(payload)],
        required=False,
    )


def run_fakeout_return_setup(symbol: str, payload: Path) -> bool:
    return run_helper_script(
        label=f"Fakeout Return Setup enrichment | symbol={symbol}",
        script=ROOT / "tools" / "fakeout_return_setup_payload_enricher.py",
        command_args=["--symbol", symbol, "--payload", str(payload)],
        required=False,
    )


def first_present(*values: Any, default: str = "NA") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def deep_find_first(obj: Any, keys: tuple[str, ...]) -> Any:
    """Busca curta e defensiva para campos decisórios em payloads com schemas variáveis."""
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                return obj[key]
        for value in obj.values():
            found = deep_find_first(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = deep_find_first(value, keys)
            if found not in (None, ""):
                return found
    return None


def tf_items(data: dict[str, Any], order: tuple[str, ...] = CONSOLE_TF_ORDER) -> list[tuple[str, dict[str, Any]]]:
    tfs = data.get("timeframes", {}) if isinstance(data, dict) else {}
    if not isinstance(tfs, dict):
        return []
    items: list[tuple[str, dict[str, Any]]] = []
    for tf in order:
        item = tfs.get(tf)
        if isinstance(item, dict) and item.get("available", True):
            items.append((tf, item))
    for tf, item in tfs.items():
        if tf not in order and isinstance(item, dict) and item.get("available", True):
            items.append((str(tf), item))
    return items


def split_summary_by_tf(summary: Any) -> dict[str, str]:
    text = str(summary or "").strip()
    rows: dict[str, str] = {}
    if not text:
        return rows
    for raw_part in text.split(" | "):
        part = raw_part.strip()
        if ":" not in part:
            continue
        tf, rest = part.split(":", 1)
        tf = tf.strip().upper()
        if tf:
            rows[tf] = rest.strip()
    return rows


def format_pattern_row(tf: str, item: dict[str, Any], summary_rows: dict[str, str]) -> str:
    summary_text = summary_rows.get(tf)
    if summary_text:
        return f"    {tf}: {summary_text}"

    main = item.get("main_pattern") or item.get("pattern") or {}
    pattern = first_present(main.get("name"), item.get("pattern_name"))
    status = first_present(
        main.get("formation_status"),
        main.get("stage"),
        main.get("status"),
        item.get("formation_status"),
        item.get("stage"),
    )
    bias = first_present(main.get("bias"), item.get("bias"))
    read = first_present(
        main.get("operational_read"),
        main.get("preferred_interpretation"),
        item.get("operational_read"),
        item.get("preferred_interpretation"),
    )
    risk = first_present(
        main.get("fakeout_risk"),
        item.get("fakeout_risk"),
        (item.get("breakout_attempt_context") or {}).get("fakeout_risk") if isinstance(item.get("breakout_attempt_context"), dict) else None,
    )
    return f"    {tf}: {pattern} ({status}/{bias}; {read}/{risk})"


def format_edge_row(tf: str, edge: dict[str, Any]) -> str:
    return (
        f"    {tf}: {first_present(edge.get('pattern_name'))} | "
        f"att={first_present(edge.get('attempt_number'))} | "
        f"h={first_present(edge.get('current_hour_brt'))} | "
        f"sess={first_present(edge.get('session_name'))} | "
        f"day={first_present(edge.get('day_of_week'))} | "
        f"wom={first_present(edge.get('week_of_month'))} | "
        f"{first_present(edge.get('preferred_interpretation'))}/{first_present(edge.get('edge_classification'))}"
    )


def format_fakeout_row(tf: str, fake: dict[str, Any]) -> str:
    return (
        f"    {tf}: {first_present(fake.get('pattern_name'))} | "
        f"{first_present(fake.get('setup_state'))} | "
        f"side={first_present(fake.get('side_if_confirmed'))}"
    )


def build_console_operational_summary(payload: dict[str, Any]) -> str:
    """Resumo multilinha apenas para console; nao altera prompt, JSON ou MARKET_DATA."""
    med = first_present(
        deep_find_first(payload.get("historical_intelligence", {}), ("preferred_action_now", "formal_mtf_decision", "action_now")),
        deep_find_first(payload.get("market_intelligence", {}), ("preferred_action_now", "formal_mtf_decision", "action_now")),
        deep_find_first(payload, ("preferred_action_now",)),
        default="NA",
    )

    tech_ctx = payload.get("technical_patterns_context", {}) or {}
    edge_ctx = payload.get("pattern_attempt_edge_context", {}) or {}
    fakeout_ctx = payload.get("fakeout_return_setup_context", {}) or {}

    lines = [
        "Resumo operacional",
        f"  med: {med}",
        "",
        "  patterns:",
    ]

    tech_items = tf_items(tech_ctx)
    tech_summary_rows = split_summary_by_tf(tech_ctx.get("summary"))
    if tech_items:
        for tf, item in tech_items:
            lines.append(format_pattern_row(tf, item, tech_summary_rows))
    elif tech_summary_rows:
        for tf in CONSOLE_TF_ORDER:
            if tf in tech_summary_rows:
                lines.append(f"    {tf}: {tech_summary_rows[tf]}")
    else:
        lines.append("    status: NA")

    lines.extend(["", "  edge:"])
    edge_items = tf_items(edge_ctx)
    if edge_items:
        for tf, edge in edge_items:
            lines.append(format_edge_row(tf, edge))
    else:
        lines.append("    status: NA")

    lines.extend(["", "  fakeout:"])
    fake_items = tf_items(fakeout_ctx)
    if fake_items:
        for tf, fake in fake_items:
            lines.append(format_fakeout_row(tf, fake))
    else:
        lines.append("    status: NA")

    return "\n".join(lines)


def build_prompt(*, config: dict[str, Any], role: dict[str, Any], profile: str, payload: dict[str, Any]) -> tuple[str, Path]:
    source_path = prompt_path_for_profile(config, role, profile)
    source = source_path.read_text(encoding="utf-8")
    market_data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
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
        description="Gera o input completo para análise manual via ChatGPT Web, sem chamar LLM."
    )
    parser.add_argument("--symbol", required=True, help="Símbolo, por exemplo GOLD.")
    parser.add_argument("--analyst", default="analyst_1", help="Analista usado para resolver prompt/modelo. Padrão: analyst_1.")
    parser.add_argument("--profile", choices=["quick", "detailed"], help="Sobrescreve temporariamente o perfil configurado.")
    parser.add_argument("--skip-ema-enrichment", action="store_true", help="Não enriquece o payload com execution_quality antes do Web input.")
    parser.add_argument("--skip-technical-patterns", action="store_true", help="Não enriquece o payload com technical_patterns_context antes do Web input.")
    parser.add_argument("--skip-pattern-attempt-edge", action="store_true", help="Não enriquece o payload com pattern_attempt_edge_context antes do Web input.")
    parser.add_argument("--skip-fakeout-return-setup", action="store_true", help="Não enriquece o payload com fakeout_return_setup_context antes do Web input.")
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

        ema_used = False
        technical_patterns_used = False
        pattern_attempt_edge_used = False
        fakeout_return_setup_used = False

        if not args.skip_ema_enrichment:
            ema_used = run_ema_enrichment(
                symbol=symbol,
                payload=current_payload_path,
                update_timeframe_parquets=args.write_timeframe_parquets,
            )

        if not args.skip_technical_patterns:
            technical_patterns_used = run_technical_patterns(symbol=symbol, payload=current_payload_path)

        if not args.skip_pattern_attempt_edge:
            pattern_attempt_edge_used = run_pattern_attempt_edge(symbol=symbol, payload=current_payload_path)

        if not args.skip_fakeout_return_setup:
            fakeout_return_setup_used = run_fakeout_return_setup(symbol=symbol, payload=current_payload_path)

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

        safe_print(build_console_operational_summary(payload))
        safe_print(
            "Web input gerado |",
            f"symbol={symbol} | analyst={analyst_id} | profile={profile}",
            f"| ema={ema_used}",
            f"| technical_patterns={technical_patterns_used}",
            f"| pattern_attempt_edge={pattern_attempt_edge_used}",
            f"| fakeout_return_setup={fakeout_return_setup_used}",
            f"| chars={len(prompt)} | llm_called=False",
        )
        safe_print(f"Arquivo gerado: {latest_path}")
        return 0
    except Exception as exc:
        safe_print(f"ERRO: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
