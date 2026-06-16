#!/usr/bin/env python3
"""
TradingAgent - Pipeline Intraday

FINALIDADE
    Executar o ciclo intraday completo do TradingAgent em ordem controlada:
    atualização da base MT5, criação do contexto, geração do payload factual
    e execução do agente intraday.

ENTRADAS
    - tradingagent.json
    - conexão MT5 já utilizada por Base_Dados.py
    - scripts:
        Base_Dados.py
        context/timeframe_context.py
        context/prompt_payload.py
        agent/intraday_agent.py
    - símbolos definidos em universe.symbols ou informados por --symbol

PROCESSAMENTO
    1. Adquire um lock para impedir execuções simultâneas.
    2. Executa Base_Dados.py uma única vez para atualizar todos os símbolos.
    3. Para cada símbolo:
       a. gera o contexto multi-timeframe;
       b. gera o payload factual;
       c. executa o agente no modo definido pelo JSON ou pela CLI.
    4. Registra duração, retorno, erros e decisão final de cada etapa.
    5. Remove o lock ao encerrar, mesmo em caso de erro controlado.

SAÍDAS
    - data/pipeline_results/intraday_pipeline_latest.json
    - data/pipeline_runs/intraday_pipeline_runs.jsonl
    - data/logs/intraday_pipeline.log
    - saídas normais de cada script executado:
        data/consolidated/{symbol}_intraday.parquet
        data/context/{symbol}_intraday_context.json
        data/payload/{symbol}_intraday_payload.json
        data/state/{symbol}_intraday_state.json
        data/agent_results/{symbol}_intraday_latest.json
        data/agent_runs/{symbol}_intraday_runs.jsonl

DEPENDÊNCIAS
    - Python 3.10+
    - dependências já exigidas pelos scripts chamados
    - tradingagent.json válido na raiz do projeto
    - não exige biblioteca adicional para a própria orquestração

EXEMPLOS
    python pipeline/intraday_pipeline.py
    python pipeline/intraday_pipeline.py --symbol GOLD
    python pipeline/intraday_pipeline.py --symbol GOLD --agent-mode single
    python pipeline/intraday_pipeline.py --symbol GOLD --skip-agent
    python pipeline/intraday_pipeline.py --symbol GOLD --agent-only

TRATAMENTO DE ERROS
    - Ctrl+C encerra o subprocesso filho, registra a interrupção e remove o lock;
    - interrompe a cadeia do símbolo quando uma etapa obrigatória falha;
    - registra stdout/stderr e código de retorno;
    - protege contra duas rodadas simultâneas;
    - considera lock antigo como removível após o limite configurado;
    - sempre produz um resumo final quando a inicialização foi possível.

LIMITAÇÕES
    - o lock é local ao host e não coordena múltiplas máquinas;
    - --agent-only pressupõe payload já existente e atual;
    - o tempo total depende principalmente do provider/modelo da LLM;
    - o pipeline não agenda a si próprio; o agendamento é externo.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "tradingagent.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        )


class PipelineLogger:
    """Registra simultaneamente no terminal e no arquivo de log."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str) -> None:
        line = f"[{local_stamp()}] {message}"
        print(line, flush=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class PipelineLock:
    """Lock local baseado em criação exclusiva de arquivo."""

    def __init__(
        self,
        path: Path,
        stale_after_minutes: float,
        logger: PipelineLogger,
    ):
        self.path = path
        self.stale_after_seconds = stale_after_minutes * 60
        self.logger = logger
        self.acquired = False

    def _read_existing(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
            return age > self.stale_after_seconds
        except FileNotFoundError:
            return False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if self.path.exists():
            existing = self._read_existing()
            if self._is_stale():
                self.logger.write(
                    "Lock antigo detectado e removido "
                    f"| conteúdo={existing or 'inválido'}"
                )
                self.path.unlink(missing_ok=True)
            else:
                raise RuntimeError(
                    "Pipeline intraday já está em execução. "
                    f"Lock ativo: {self.path} | conteúdo={existing}"
                )

        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at_utc": utc_now_iso(),
            "project_root": str(ROOT),
        }

        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise RuntimeError(
                f"Outro processo adquiriu o lock: {self.path}"
            ) from exc

        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

        self.acquired = True
        self.logger.write(f"Lock adquirido | path={self.path}")

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False
            self.logger.write(f"Lock removido | path={self.path}")

    def __enter__(self) -> "PipelineLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def resolve_path(path_text: str) -> Path:
    return ROOT / path_text


def expand_arguments(arguments: Iterable[str], symbol: str | None) -> list[str]:
    return [
        str(item).replace("{symbol}", symbol or "")
        for item in arguments
    ]


def run_step(
    *,
    name: str,
    script: Path,
    arguments: list[str],
    timeout_seconds: float,
    logger: PipelineLogger,
    symbol: str | None = None,
) -> dict[str, Any]:
    started_at = utc_now_iso()
    started_perf = time.perf_counter()

    command = [sys.executable, str(script), *arguments]
    display_command = subprocess.list2cmdline(command)

    logger.write(
        f"Etapa iniciada | step={name} | symbol={symbol or '-'} "
        f"| timeout={timeout_seconds}s"
    )
    logger.write(f"Comando | {display_command}")

    if not script.exists():
        error = f"Script não encontrado: {script}"
        logger.write(f"Etapa falhou | step={name} | erro={error}")
        return {
            "name": name,
            "symbol": symbol,
            "success": False,
            "started_at_utc": started_at,
            "finished_at_utc": utc_now_iso(),
            "duration_seconds": round(time.perf_counter() - started_perf, 3),
            "return_code": None,
            "timed_out": False,
            "command": command,
            "output_tail": [],
            "error": error,
        }

    output_lines: list[str] = []
    process: subprocess.Popen[str] | None = None
    timed_out = False
    error: str | None = None

    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None

        deadline = time.monotonic() + timeout_seconds
        while True:
            line = process.stdout.readline()

            if line:
                clean = line.rstrip()
                output_lines.append(clean)
                print(f"    {clean}", flush=True)
                with logger.path.open("a", encoding="utf-8") as handle:
                    handle.write(f"    {clean}\n")

            if process.poll() is not None:
                for remaining in process.stdout:
                    clean = remaining.rstrip()
                    output_lines.append(clean)
                    print(f"    {clean}", flush=True)
                    with logger.path.open("a", encoding="utf-8") as handle:
                        handle.write(f"    {clean}\n")
                break

            if time.monotonic() > deadline:
                timed_out = True
                error = (
                    f"Timeout da etapa após {timeout_seconds} segundos."
                )
                process.kill()
                process.wait(timeout=10)
                break

            if not line:
                time.sleep(0.1)

        return_code = process.returncode

    except KeyboardInterrupt:
        error = "Execução interrompida pelo usuário."
        return_code = process.returncode if process else None
        if process and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=10)
            except Exception:
                pass
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return_code = process.returncode if process else None
        if process and process.poll() is None:
            process.kill()

    success = (
        error is None
        and not timed_out
        and return_code == 0
    )

    result = {
        "name": name,
        "symbol": symbol,
        "success": success,
        "started_at_utc": started_at,
        "finished_at_utc": utc_now_iso(),
        "duration_seconds": round(time.perf_counter() - started_perf, 3),
        "return_code": return_code,
        "timed_out": timed_out,
        "command": command,
        "output_tail": output_lines[-40:],
        "error": error,
    }

    logger.write(
        f"Etapa finalizada | step={name} | symbol={symbol or '-'} "
        f"| success={success} | return_code={return_code} "
        f"| duration={result['duration_seconds']}s"
    )
    return result


def read_agent_summary(
    config: dict[str, Any],
    symbol: str,
) -> dict[str, Any] | None:
    template = config.get("agent", {}).get("paths", {}).get(
        "latest_result_template"
    )
    if not template:
        return None

    path = ROOT / template.format(symbol=symbol)
    if not path.exists():
        return None

    try:
        data = read_json(path)
        final = data.get("final", {})
        execution = data.get("execution", {})
        return {
            "path": str(path),
            "run_id": data.get("run_id"),
            "action": final.get("action"),
            "confidence": final.get("confidence"),
            "source": final.get("source"),
            "summary": final.get("summary"),
            "agent_mode": execution.get("mode"),
            "agent_latency_ms": execution.get("total_latency_ms"),
        }
    except Exception as exc:
        return {
            "path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def build_agent_arguments(
    configured_arguments: list[str],
    symbol: str,
    agent_mode: str | None,
    analyst: str | None,
) -> list[str]:
    arguments = expand_arguments(configured_arguments, symbol)

    if agent_mode:
        arguments.extend(["--mode", agent_mode])

    if analyst:
        arguments.extend(["--analyst", analyst])

    return arguments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa o pipeline intraday completo do TradingAgent."
    )
    parser.add_argument(
        "--symbol",
        action="append",
        help=(
            "Símbolo a processar. Pode ser repetido. "
            "Sem este argumento, usa universe.symbols."
        ),
    )
    parser.add_argument(
        "--agent-mode",
        choices=["single", "ensemble"],
        help="Sobrescreve temporariamente o modo do agente.",
    )
    parser.add_argument(
        "--analyst",
        help="Analista usado quando o modo efetivo for single.",
    )
    parser.add_argument(
        "--skip-agent",
        action="store_true",
        help="Executa dados, contexto e payload, mas não chama a LLM.",
    )
    parser.add_argument(
        "--agent-only",
        action="store_true",
        help="Executa somente o agente usando o payload já existente.",
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="Desabilita o lock somente nesta execução.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.skip_agent and args.agent_only:
        print(
            "ERRO: --skip-agent e --agent-only são incompatíveis.",
            file=sys.stderr,
        )
        return 2

    run_started_at = utc_now_iso()
    run_started_perf = time.perf_counter()
    run_id = (
        "intraday_pipeline_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + "_"
        + uuid.uuid4().hex[:8]
    )

    try:
        config = read_json(CONFIG_PATH)
        pipeline_cfg = config.get("pipeline_intraday", {})
        if not pipeline_cfg.get("enabled", True):
            raise RuntimeError("pipeline_intraday.enabled está false.")

        output_paths = pipeline_cfg["paths"]
        logger = PipelineLogger(resolve_path(output_paths["log_file"]))

        symbols = [
            item.upper()
            for item in (
                args.symbol
                if args.symbol
                else config.get("universe", {}).get("symbols", [])
            )
        ]
        if not symbols:
            raise ValueError("Nenhum símbolo foi informado ou configurado.")

        symbols = list(dict.fromkeys(symbols))

        logger.write(
            f"Pipeline iniciado | run_id={run_id} | symbols={symbols} "
            f"| agent_only={args.agent_only} | skip_agent={args.skip_agent} "
            f"| agent_mode={args.agent_mode or 'json'}"
        )

        lock_cfg = pipeline_cfg.get("lock", {})
        use_lock = lock_cfg.get("enabled", True) and not args.no_lock

        if use_lock:
            lock_context = PipelineLock(
                resolve_path(lock_cfg["path"]),
                float(lock_cfg.get("stale_after_minutes", 60)),
                logger,
            )
        else:
            class NoopLock:
                def __enter__(self): return self
                def __exit__(self, exc_type, exc, traceback): return None
            lock_context = NoopLock()

        record: dict[str, Any] = {
            "@timestamp": run_started_at,
            "run_id": run_id,
            "project": config.get("project", {}).get("name", "TradingAgent"),
            "environment": config.get("project", {}).get("environment", "dev"),
            "pipeline": "intraday",
            "symbols": symbols,
            "options": {
                "agent_only": args.agent_only,
                "skip_agent": args.skip_agent,
                "agent_mode_override": args.agent_mode,
                "analyst_override": args.analyst,
                "lock_enabled": use_lock,
            },
            "base_dados": None,
            "symbol_results": [],
            "success": False,
            "started_at_utc": run_started_at,
            "finished_at_utc": None,
            "duration_seconds": None,
            "error": None,
        }

        with lock_context:
            steps_cfg = pipeline_cfg["steps"]

            if not args.agent_only and steps_cfg["base_dados"].get("enabled", True):
                base_cfg = steps_cfg["base_dados"]
                base_result = run_step(
                    name="base_dados",
                    script=resolve_path(base_cfg["script"]),
                    arguments=expand_arguments(
                        base_cfg.get("arguments", []),
                        None,
                    ),
                    timeout_seconds=float(
                        base_cfg.get("timeout_seconds", 180)
                    ),
                    logger=logger,
                )
                record["base_dados"] = base_result

                if not base_result["success"]:
                    raise RuntimeError(
                        "A atualização da base falhou; etapas seguintes "
                        "não serão executadas."
                    )

            continue_on_symbol_error = bool(
                pipeline_cfg.get("continue_on_symbol_error", False)
            )

            for symbol in symbols:
                symbol_started = time.perf_counter()
                logger.write(f"Símbolo iniciado | symbol={symbol}")

                symbol_record: dict[str, Any] = {
                    "symbol": symbol,
                    "success": False,
                    "steps": {},
                    "agent_summary": None,
                    "duration_seconds": None,
                    "error": None,
                }

                try:
                    if not args.agent_only:
                        for step_name in (
                            "timeframe_context",
                            "prompt_payload",
                        ):
                            step_cfg = steps_cfg[step_name]
                            if not step_cfg.get("enabled", True):
                                continue

                            result = run_step(
                                name=step_name,
                                script=resolve_path(step_cfg["script"]),
                                arguments=expand_arguments(
                                    step_cfg.get("arguments", []),
                                    symbol,
                                ),
                                timeout_seconds=float(
                                    step_cfg.get("timeout_seconds", 120)
                                ),
                                logger=logger,
                                symbol=symbol,
                            )
                            symbol_record["steps"][step_name] = result

                            if not result["success"]:
                                raise RuntimeError(
                                    f"Etapa {step_name} falhou para {symbol}."
                                )

                    if not args.skip_agent:
                        agent_cfg = steps_cfg["intraday_agent"]
                        if agent_cfg.get("enabled", True):
                            result = run_step(
                                name="intraday_agent",
                                script=resolve_path(agent_cfg["script"]),
                                arguments=build_agent_arguments(
                                    agent_cfg.get("arguments", []),
                                    symbol,
                                    args.agent_mode,
                                    args.analyst,
                                ),
                                timeout_seconds=float(
                                    agent_cfg.get("timeout_seconds", 1500)
                                ),
                                logger=logger,
                                symbol=symbol,
                            )
                            symbol_record["steps"]["intraday_agent"] = result

                            if not result["success"]:
                                raise RuntimeError(
                                    f"Agente intraday falhou para {symbol}."
                                )

                            symbol_record["agent_summary"] = read_agent_summary(
                                config,
                                symbol,
                            )

                    symbol_record["success"] = True

                except Exception as exc:
                    symbol_record["error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    logger.write(
                        f"Símbolo falhou | symbol={symbol} "
                        f"| erro={symbol_record['error']}"
                    )

                    if not continue_on_symbol_error:
                        symbol_record["duration_seconds"] = round(
                            time.perf_counter() - symbol_started,
                            3,
                        )
                        record["symbol_results"].append(symbol_record)
                        raise

                symbol_record["duration_seconds"] = round(
                    time.perf_counter() - symbol_started,
                    3,
                )
                record["symbol_results"].append(symbol_record)

                logger.write(
                    f"Símbolo finalizado | symbol={symbol} "
                    f"| success={symbol_record['success']} "
                    f"| duration={symbol_record['duration_seconds']}s"
                )

            record["success"] = all(
                item["success"] for item in record["symbol_results"]
            )

    except KeyboardInterrupt:
        error = "KeyboardInterrupt: execução interrompida pelo usuário."
        if "record" not in locals():
            record = {
                "@timestamp": run_started_at,
                "run_id": run_id,
                "pipeline": "intraday",
                "success": False,
                "started_at_utc": run_started_at,
                "symbol_results": [],
            }
        record["error"] = error
        if "logger" in locals():
            logger.write("Pipeline interrompido pelo usuário.")
        else:
            print("Pipeline interrompido pelo usuário.", file=sys.stderr)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if "record" not in locals():
            record = {
                "@timestamp": run_started_at,
                "run_id": run_id,
                "pipeline": "intraday",
                "success": False,
                "started_at_utc": run_started_at,
                "symbol_results": [],
            }
        record["error"] = error
        if "logger" in locals():
            logger.write(f"Pipeline falhou | erro={error}")
        else:
            print(f"ERRO: {error}", file=sys.stderr)

    record["finished_at_utc"] = utc_now_iso()
    record["duration_seconds"] = round(
        time.perf_counter() - run_started_perf,
        3,
    )

    if "pipeline_cfg" in locals():
        latest_path = resolve_path(
            pipeline_cfg["paths"]["latest_result"]
        )
        runs_path = resolve_path(
            pipeline_cfg["paths"]["runs_jsonl"]
        )
        write_json_atomic(latest_path, record)
        append_jsonl(runs_path, record)

        if "logger" in locals():
            logger.write(
                f"Pipeline finalizado | success={record['success']} "
                f"| duration={record['duration_seconds']}s "
                f"| latest={latest_path}"
            )

    if record.get("success"):
        for item in record.get("symbol_results", []):
            summary = item.get("agent_summary") or {}
            if summary:
                print(
                    f"Resumo | symbol={item['symbol']} "
                    f"| action={summary.get('action')} "
                    f"| confidence={summary.get('confidence')} "
                    f"| mode={summary.get('agent_mode')}",
                    flush=True,
                )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
