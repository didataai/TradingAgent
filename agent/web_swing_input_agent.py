#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera input swing para análise manual via ChatGPT Web."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--prompt",
        type=Path,
        default=ROOT / "prompts" / "PromptPrevisaoSwing.md",
    )
    parser.add_argument("--payload", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbol = args.symbol.upper().strip()
    prompt_path = args.prompt
    payload_path = args.payload or (
        ROOT / "data" / "payload" / f"{symbol}_swing_payload.json"
    )

    prompt_template = prompt_path.read_text(encoding="utf-8")
    payload = read_json(payload_path)
    market_data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    if "{{MARKET_DATA}}" not in prompt_template:
        raise ValueError(
            f"O prompt precisa conter o marcador {{MARKET_DATA}}: {prompt_path}"
        )

    rendered = prompt_template.replace("{{MARKET_DATA}}", market_data)
    output = ROOT / "data" / "debug_llm" / f"{symbol}_swing_latest_input.txt"
    write_text_atomic(output, rendered)

    print(
        "Web swing input gerado | "
        f"symbol={symbol} | chars={len(rendered)} | llm_called=False"
    )
    print(f"Arquivo gerado: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
