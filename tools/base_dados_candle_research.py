# -*- coding: utf-8 -*-
"""
TradingAgent — Candle Research Collector

Script seguro para aumentar a amostra de candles do estudo Market Chronos sem
sobrescrever os Parquets oficiais do TradingAgent.

Salva em:
  data/market_chronos/candle_base/timeframes/
  data/market_chronos/candle_base/consolidated/
  data/market_chronos/candle_base/manifests/

Uso:
  python tools/base_dados_candle_research.py --symbol GOLD --timeframes M1 M5 M15 H1 H4
  python tools/base_dados_candle_research.py --symbol GOLD --counts M1=150000 M5=100000 M15=50000 H1=20000 H4=10000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError as exc:
    raise SystemExit("MetaTrader5 não instalado. Execute: pip install MetaTrader5") from exc

# -----------------------------------------------------------------------------
# Importa o motor validado do Base_Dados.py, mas NÃO usa os paths oficiais dele.
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import Base_Dados as bd  # type: ignore
except Exception as exc:
    raise SystemExit(
        "Não consegui importar Base_Dados.py da raiz do projeto. "
        "Confirme que este arquivo está em TradingAgent/tools/."
    ) from exc


DEFAULT_COUNTS: Dict[str, int] = {
    "M1": 150_000,
    "M5": 100_000,
    "M15": 50_000,
    "H1": 20_000,
    "H4": 10_000,
    "D1": 5_000,
    "W1": 2_000,
    "MN1": 1_000,
}

DEFAULT_TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4")


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def parse_count_overrides(items: Iterable[str] | None) -> Dict[str, int]:
    counts = dict(DEFAULT_COUNTS)
    if not items:
        return counts
    for item in items:
        if "=" not in item:
            raise ValueError(f"Formato inválido em --counts: {item}. Use TF=NUM, ex.: M1=150000")
        tf, raw = item.split("=", 1)
        tf = tf.strip().upper()
        if tf not in bd.SUPPORTED_TIMEFRAMES:
            raise ValueError(f"Timeframe inválido em --counts: {tf}")
        value = int(raw)
        if value <= 0:
            raise ValueError(f"Count precisa ser positivo para {tf}: {value}")
        counts[tf] = value
    return counts


def adaptive_copy_rates(mt5_symbol: str, timeframe: int, start_pos: int, count: int, chunk_size: int) -> pd.DataFrame:
    """Coleta por posição em blocos, reduzindo o lote se o terminal recusar.

    Motivo: alguns terminais MT5 retornam None/vazio quando o count é grande.
    """
    frames: List[pd.DataFrame] = []
    remaining = int(count)
    pos = int(start_pos)
    preferred_chunk = max(100, int(chunk_size))

    while remaining > 0:
        request = min(preferred_chunk, remaining)
        rates = None
        used_request = request

        # fallback progressivo: 5000 -> 2500 -> 1000 -> 500 -> 100 -> 10 -> 1
        attempts = []
        x = request
        while x >= 100:
            attempts.append(x)
            x //= 2
        attempts.extend([50, 10, 1])
        seen = set()
        attempts = [a for a in attempts if not (a in seen or seen.add(a))]

        for attempt in attempts:
            attempt = min(attempt, remaining)
            if attempt <= 0:
                continue
            rates = mt5.copy_rates_from_pos(mt5_symbol, timeframe, pos, int(attempt))
            if rates is not None and len(rates) > 0:
                used_request = attempt
                break
            last_error = mt5.last_error()
            log(f"Sem retorno | pos={pos} count={attempt} mt5_error={last_error}")
            time.sleep(0.05)

        if rates is None or len(rates) == 0:
            if frames:
                log(f"Histórico acabou ou terminal recusou além de pos={pos}. Salvando parcial.")
                break
            raise RuntimeError(
                f"MT5 não retornou candles nem com fallback mínimo | symbol={mt5_symbol} pos={pos}"
            )

        part = pd.DataFrame(rates)
        frames.append(part)
        got = len(part)
        log(f"Chunk coletado | pos={pos} request={used_request} rows={got} acumulado={sum(len(f) for f in frames)}/{count}")

        pos += got
        remaining -= got

        # Se pediu mais do que o terminal tinha disponível neste ponto, provavelmente acabou o histórico.
        if got < used_request:
            log(f"Retorno menor que pedido ({got}<{used_request}); provável fim do histórico disponível.")
            break

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def collect_rates_research(
    symbol: str,
    timeframe_name: str,
    count: int,
    include_live_bar: bool,
    broker_timezone: str,
    timestamp_source: str,
    chunk_size: int,
) -> pd.DataFrame:
    mt5_symbol = bd.resolve_mt5_symbol(symbol)
    if mt5_symbol is None:
        return pd.DataFrame()

    timeframe = bd.MT5_TIMEFRAMES[timeframe_name]
    start_pos = 0 if include_live_bar else 1

    raw = adaptive_copy_rates(
        mt5_symbol=mt5_symbol,
        timeframe=timeframe,
        start_pos=start_pos,
        count=count,
        chunk_size=chunk_size,
    )
    if raw.empty:
        return raw

    base = raw.copy()
    raw_time = pd.to_datetime(base["time"], unit="s", errors="coerce")
    timestamp_source = str(timestamp_source).strip().lower()

    if timestamp_source == "broker_wall_clock":
        base["time_broker_raw"] = raw_time
        base["time"] = bd.broker_wall_clock_to_utc_naive(raw_time, broker_timezone)
    elif timestamp_source == "utc_epoch":
        base["time"] = pd.to_datetime(base["time"], unit="s", utc=True, errors="coerce").dt.tz_convert(None)
    else:
        raise ValueError("mt5.timestamp_source inválido. Use 'utc_epoch' ou 'broker_wall_clock'.")

    base = base.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)
    base = bd.ensure_columns(base)
    base = bd.coerce_numeric_ohlc(base)
    base["symbol"] = symbol
    base["timeframe"] = timeframe_name
    base["is_live_bar"] = bd.infer_live_bar_mask(base, include_live_bar)
    return base


def atomic_write_parquet(df: pd.DataFrame, path: Path, compression: str = "zstd") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(temp_path, index=False, engine="pyarrow", compression=compression)
    temp_path.replace(path)


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp_path.replace(path)


def build_symbol(
    config: Mapping[str, Any],
    symbol: str,
    timeframes: List[str],
    counts: Mapping[str, int],
    output_root: Path,
    chunk_size: int,
    include_live_bar: bool,
    enable_labels: bool,
) -> Dict[str, Any]:
    if not bd.initialize_mt5(config):
        raise RuntimeError("Não foi possível inicializar o MetaTrader 5")

    manifest: Dict[str, Any] = {
        "script": "base_dados_candle_research.py",
        "symbol": symbol,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_root": str(output_root),
        "timeframes": {},
        "errors": [],
    }

    datasets: List[pd.DataFrame] = []

    try:
        server_name = bd.detect_server_name(str(config["mt5"]["server"]))
        broker_timezone = bd.resolve_broker_timezone(config, server_name)
        timestamp_source = str(config.get("mt5", {}).get("timestamp_source", "utc_epoch"))
        log(f"Server={server_name} | broker_timezone={broker_timezone} | timestamp_source={timestamp_source}")

        for tf in timeframes:
            requested = int(counts[tf])
            log(f"Coletando {symbol} {tf} | alvo={requested}")
            try:
                base = collect_rates_research(
                    symbol=symbol,
                    timeframe_name=tf,
                    count=requested,
                    include_live_bar=include_live_bar,
                    broker_timezone=broker_timezone,
                    timestamp_source=timestamp_source,
                    chunk_size=chunk_size,
                )
                if base.empty:
                    raise RuntimeError("Nenhum candle retornado pelo MT5")

                log(f"Features {symbol} {tf} | rows_base={len(base)}")
                dataset = bd.build_feature_dataset(
                    base=base,
                    timeframe_name=tf,
                    config=config,
                    broker_timezone=broker_timezone,
                    enable_labels=enable_labels,
                )

                tf_path = output_root / "timeframes" / f"{symbol}_{tf}_candle_research.parquet"
                atomic_write_parquet(dataset, tf_path)
                datasets.append(dataset)

                times = pd.to_datetime(dataset.get("time_brt", dataset.get("time")), errors="coerce")
                manifest["timeframes"][tf] = {
                    "requested": requested,
                    "rows": int(len(dataset)),
                    "columns": int(len(dataset.columns)),
                    "start_brt": str(times.min()) if not times.dropna().empty else None,
                    "end_brt": str(times.max()) if not times.dropna().empty else None,
                    "path": str(tf_path),
                }
                log(f"OK {symbol} {tf} | rows={len(dataset)} | path={tf_path}")
            except Exception as exc:
                msg = f"{symbol} {tf}: {exc}"
                log(f"ERRO {msg}")
                manifest["errors"].append(msg)
                # Continua para os próximos TFs: pesquisa não deve morrer no primeiro erro.
                continue

        if datasets:
            consolidated = pd.concat(datasets, ignore_index=True, sort=False)
            consolidated_path = output_root / "consolidated" / f"{symbol}_candle_research.parquet"
            atomic_write_parquet(consolidated, consolidated_path)
            manifest["consolidated"] = {
                "rows": int(len(consolidated)),
                "columns": int(len(consolidated.columns)),
                "path": str(consolidated_path),
            }
            log(f"Consolidado salvo | rows={len(consolidated)} | path={consolidated_path}")
        else:
            raise RuntimeError("Nenhum timeframe foi salvo.")

        manifest["status"] = "success" if not manifest["errors"] else "partial_success"
        return manifest
    finally:
        mt5.shutdown()
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        log("Conexão MT5 encerrada")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coleta ampliada para estudo Market Chronos/Candle Intelligence.")
    parser.add_argument("--config", default="tradingagent.json", help="Caminho do tradingagent.json")
    parser.add_argument("--symbol", default="GOLD", help="Símbolo a coletar")
    parser.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES), help="Timeframes: M1 M5 M15 H1 H4")
    parser.add_argument("--counts", nargs="*", default=None, help="Overrides: M1=150000 M5=100000 ...")
    parser.add_argument("--chunk-size", type=int, default=5000, help="Tamanho inicial do lote MT5")
    parser.add_argument("--include-live-bar", action="store_true", help="Inclui barra atual em formação")
    parser.add_argument("--enable-labels", action="store_true", help="Calcula labels futuros se configurados")
    parser.add_argument(
        "--output-root",
        default="data/market_chronos/candle_base",
        help="Pasta raiz de saída da base de pesquisa",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bd.configure_logging("INFO")

    config = bd.load_tradingagent_config(args.config)
    symbol = str(args.symbol).strip().upper()
    timeframes = bd.normalize_timeframes(args.timeframes)
    counts = parse_count_overrides(args.counts)
    output_root = bd.resolve_project_path(config, args.output_root)

    log(f"Candle research seguro | symbol={symbol} | timeframes={timeframes}")
    log(f"Saída={output_root}")
    log("Counts=" + json.dumps({tf: counts[tf] for tf in timeframes}, ensure_ascii=False))

    manifest = build_symbol(
        config=config,
        symbol=symbol,
        timeframes=timeframes,
        counts=counts,
        output_root=output_root,
        chunk_size=args.chunk_size,
        include_live_bar=bool(args.include_live_bar),
        enable_labels=bool(args.enable_labels),
    )

    manifest_path = output_root / "manifests" / f"base_dados_candle_research_{symbol}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    write_json(manifest_path, manifest)
    log(f"Manifest salvo: {manifest_path}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return 0 if manifest.get("status") in {"success", "partial_success"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
