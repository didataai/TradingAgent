#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{stamp()}] {message}", flush=True)


def run_step(name: str, script: Path, args: list[str], timeout: float) -> None:
    command = [sys.executable, str(script), *args]
    log(f"Etapa iniciada | step={name} | timeout={timeout}s")
    log("Comando | " + subprocess.list2cmdline(command))
    started = time.perf_counter()

    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )

    if process.stdout:
        for line in process.stdout.splitlines():
            print(f"    {line}")
    if process.stderr:
        for line in process.stderr.splitlines():
            print(f"    {line}", file=sys.stderr)

    duration = time.perf_counter() - started
    if process.returncode != 0:
        raise RuntimeError(
            f"Etapa {name} falhou | return_code={process.returncode}"
        )
    log(f"Etapa finalizada | step={name} | duration={duration:.3f}s")


class Lock:
    def __init__(self, path: Path):
        self.path = path
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"Pipeline já está em execução: {self.path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                f"pid={os.getpid()}\nhost={socket.gethostname()}\nstarted={stamp()}\n"
            )
        self.acquired = True
        log(f"Lock adquirido | path={self.path}")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.acquired:
            self.path.unlink(missing_ok=True)
            log(f"Lock removido | path={self.path}")


def normalize_symbol(value: str) -> str:
    return str(value).strip().upper()


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Configuração não encontrada: {path}")
    with path.open("r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("tradingagent.json precisa conter um objeto JSON.")
    return config


def load_symbols_from_config(config: dict[str, Any]) -> list[str]:
    raw_symbols = config.get("universe", {}).get("symbols", [])
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raise ValueError(
            "Nenhum símbolo encontrado em universe.symbols no tradingagent.json."
        )

    result: list[str] = []
    seen: set[str] = set()
    for raw_symbol in raw_symbols:
        symbol = normalize_symbol(raw_symbol)
        if symbol and symbol not in seen:
            result.append(symbol)
            seen.add(symbol)

    if not result:
        raise ValueError("A lista universe.symbols não possui símbolos válidos.")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Atualiza dados swing e gera arquivos para ChatGPT Web."
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help=(
            "Processa apenas um símbolo. Quando omitido, processa todos os "
            "símbolos configurados em universe.symbols."
        ),
    )
    parser.add_argument(
        "--config",
        default="tradingagent.json",
        help="Caminho para o tradingagent.json.",
    )
    parser.add_argument(
        "--skip-daily-refresh",
        action="store_true",
        help="Não atualiza H4/D1/W1/MN1; usa os Parquets existentes.",
    )
    parser.add_argument(
        "--skip-intraday-refresh",
        action="store_true",
        help="Não atualiza H1/M15; usa os Parquets existentes.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Interrompe no primeiro ativo com erro.",
    )
    return parser.parse_args()


def run_symbol_pipeline(symbol: str) -> Path:
    run_step(
        f"build_swing_consolidated_{symbol}",
        ROOT / "context" / "build_swing_consolidated.py",
        ["--symbol", symbol],
        120,
    )

    run_step(
        f"swing_timeframe_context_{symbol}",
        ROOT / "context" / "swing_timeframe_context.py",
        ["--symbol", symbol],
        120,
    )

    run_step(
        f"swing_prompt_payload_{symbol}",
        ROOT / "context" / "swing_prompt_payload.py",
        ["--symbol", symbol],
        120,
    )

    run_step(
        f"web_swing_input_agent_{symbol}",
        ROOT / "agent" / "web_swing_input_agent.py",
        ["--symbol", symbol],
        60,
    )

    output = ROOT / "data" / "debug_llm" / f"{symbol}_swing_latest_input.txt"
    if not output.exists():
        raise FileNotFoundError(f"Arquivo final não foi gerado: {output}")
    return output


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    config = load_config(config_path)

    if args.symbol:
        symbols = [normalize_symbol(args.symbol)]
        execution_mode = "single_symbol"
    else:
        symbols = load_symbols_from_config(config)
        execution_mode = "multi_symbol"

    started = time.perf_counter()
    lock_path = ROOT / "data" / "locks" / "swing_pipeline_web.lock"

    log(
        "Pipeline swing web iniciado | "
        f"mode={execution_mode} | symbols={symbols} | llm_called=False"
    )

    successful: list[str] = []
    failed: list[dict[str, str]] = []
    outputs: list[str] = []

    with Lock(lock_path):
        common_config_args = ["--config", str(config_path)]

        # Em modo single_symbol, o Base_Dados.py recebe o mesmo filtro e
        # atualiza somente o ativo solicitado. Em modo multi_symbol, o filtro
        # é omitido e a lista completa continua vindo do tradingagent.json.
        refresh_symbol_args = (
            ["--symbol", symbols[0]]
            if execution_mode == "single_symbol"
            else []
        )

        if not args.skip_intraday_refresh:
            run_step(
                "base_dados_intraday",
                ROOT / "Base_Dados.py",
                [
                    "--mode",
                    "intraday_refresh",
                    *common_config_args,
                    *refresh_symbol_args,
                ],
                600,
            )

        if not args.skip_daily_refresh:
            run_step(
                "base_dados_daily",
                ROOT / "Base_Dados.py",
                [
                    "--mode",
                    "daily_refresh",
                    *common_config_args,
                    *refresh_symbol_args,
                ],
                600,
            )

        for symbol in symbols:
            symbol_started = time.perf_counter()
            log(f"Ativo iniciado | symbol={symbol}")
            try:
                output = run_symbol_pipeline(symbol)
                outputs.append(str(output))
                successful.append(symbol)
                log(
                    f"Ativo finalizado | symbol={symbol} | success=True | "
                    f"duration={time.perf_counter() - symbol_started:.3f}s | "
                    f"output={output}"
                )
            except Exception as exc:
                failed.append(
                    {
                        "symbol": symbol,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                log(
                    f"Ativo falhou | symbol={symbol} | "
                    f"error={type(exc).__name__}: {exc}"
                )
                if args.fail_fast:
                    raise

    duration = time.perf_counter() - started
    log(
        "Pipeline swing web finalizado | "
        f"success={len(successful)} | failed={len(failed)} | "
        f"duration={duration:.3f}s"
    )
    log(f"Ativos com sucesso | symbols={successful}")
    if failed:
        log(f"Ativos com falha | details={failed}")
    log(f"Arquivos gerados | outputs={outputs}")

    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired as exc:
        log(f"ERRO: timeout no comando {exc.cmd}")
        raise SystemExit(1)
    except Exception as exc:
        log(f"ERRO: {type(exc).__name__}: {exc}")
        raise SystemExit(1)