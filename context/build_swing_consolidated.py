#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

DEFAULT_TFS = ("W1", "D1", "H4", "H1", "M15")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monta o consolidado swing a partir dos Parquets por timeframe."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TFS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.project_root.resolve()
    symbol = args.symbol.upper().strip()
    data_dir = root / "data"

    parts: list[pd.DataFrame] = []
    missing: list[str] = []

    for tf in args.timeframes:
        path = data_dir / f"{symbol}_{tf}.parquet"
        if not path.exists():
            missing.append(str(path))
            continue

        df = pd.read_parquet(path)
        if df.empty:
            missing.append(f"{path} (vazio)")
            continue

        df = df.copy()
        df["timeframe"] = tf
        if "symbol" not in df.columns:
            df["symbol"] = symbol
        parts.append(df)

    if missing:
        raise FileNotFoundError(
            "Arquivos necessários ausentes:\n- " + "\n- ".join(missing)
        )

    consolidated = pd.concat(parts, ignore_index=True, sort=False)
    out = data_dir / "consolidated" / f"{symbol}_swing.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)

    temp = out.with_suffix(".parquet.tmp")
    consolidated.to_parquet(temp, index=False, compression="zstd")
    temp.replace(out)

    print(
        f"Consolidado swing salvo: {out} | "
        f"timeframes={list(args.timeframes)} | rows={len(consolidated)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
