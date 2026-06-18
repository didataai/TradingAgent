#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Atualiza dados swing e gera arquivo para ChatGPT Web."
    )
    parser.add_argument("--symbol", default="GOLD")
    parser.add_argument(
        "--skip-intraday-refresh",
        action="store_true",
        help="Não atualiza H1/M15; usa os Parquets existentes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbol = args.symbol.upper().strip()
    started = time.perf_counter()
    lock_path = ROOT / "data" / "locks" / "swing_pipeline_web.lock"

    log(
        f"Pipeline swing web iniciado | symbol={symbol} | "
        f"llm_called=False"
    )

    with Lock(lock_path):
        if not args.skip_intraday_refresh:
            run_step(
                "base_dados_intraday",
                ROOT / "Base_Dados.py",
                ["--mode", "intraday_refresh"],
                240,
            )

        run_step(
            "base_dados_daily",
            ROOT / "Base_Dados.py",
            ["--mode", "daily_refresh"],
            240,
        )

        run_step(
            "build_swing_consolidated",
            ROOT / "context" / "build_swing_consolidated.py",
            ["--symbol", symbol],
            120,
        )

        run_step(
            "swing_timeframe_context",
            ROOT / "context" / "swing_timeframe_context.py",
            ["--symbol", symbol],
            120,
        )

        run_step(
            "swing_prompt_payload",
            ROOT / "context" / "swing_prompt_payload.py",
            ["--symbol", symbol],
            120,
        )

        run_step(
            "web_swing_input_agent",
            ROOT / "agent" / "web_swing_input_agent.py",
            ["--symbol", symbol],
            60,
        )

    duration = time.perf_counter() - started
    output = ROOT / "data" / "debug_llm" / f"{symbol}_swing_latest_input.txt"
    log(
        f"Pipeline swing web finalizado | success=True | "
        f"duration={duration:.3f}s | output={output}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired as exc:
        log(f"ERRO: timeout no comando {exc.cmd}")
        raise SystemExit(1)
    except Exception as exc:
        log(f"ERRO: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
