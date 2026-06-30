#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Chronos Runtime — State Builder + Laws Matcher

Objetivo
--------
Construir automaticamente o estado Chronos atual a partir da base MTF e
avaliá-lo contra o Market Laws Registry da V10.1, sem recalcular relatórios,
Excel, validações históricas ou segmentações.

Uso padrão
----------
python tools/market_chronos_runtime.py --symbol GOLD --anchor-tf M5

Saídas padrão
-------------
data/context/GOLD_chronos_state.json
data/context/GOLD_chronos_intelligence.json

O script importa as mesmas funções do market_chronos_engine_v10_1.py para
manter paridade entre pesquisa e runtime.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

DEFAULT_INPUT = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_REGISTRY = "data/market_chronos/{symbol}/laws/market_laws_registry.json"
DEFAULT_STATE_OUTPUT = "data/context/{symbol}_chronos_state.json"
DEFAULT_INTELLIGENCE_OUTPUT = "data/context/{symbol}_chronos_intelligence.json"
DEFAULT_ENGINE = "tools/market_chronos_engine_v10_1.py"

DEFAULT_LIVE_TEMPLATE = "data/{symbol}_{tf}.parquet"


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{stamp()}] {message}", flush=True)


def clean_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if not math.isfinite(number) else round(number, 6)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value) if not isinstance(value, (str, bytes)) else False:
        return None
    return value


def save_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean_json(dict(payload)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON inválido: {path}")
    return payload


def load_engine_module(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Engine V10.1 não encontrado: {path}")
    spec = importlib.util.spec_from_file_location("market_chronos_engine_runtime", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Não foi possível importar o engine: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    required = (
        "add_core_features",
        "add_state_dna_features",
        "add_setup_genome_features",
        "add_htf_location_features",
        "add_sequence_dna_features",
        "add_memory_engine_features",
        "add_law_segmentation_features",
        "match_market_laws",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise AttributeError(f"Engine incompatível; funções ausentes: {', '.join(missing)}")
    return module


def normalize_event_time(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza a coluna temporal dos Parquets de laboratório e live.

    Aceita event_time, time, datetime, timestamp, date_time, date e também
    índices temporais (DatetimeIndex ou índice nomeado).
    """
    out = df.copy()

    if "event_time" not in out.columns:
        candidates = (
            "time",
            "datetime",
            "timestamp",
            "date_time",
            "date",
            "open_time",
            "candle_time",
        )
        source_col = next((name for name in candidates if name in out.columns), None)

        if source_col is not None:
            out = out.rename(columns={source_col: "event_time"})
        elif isinstance(out.index, pd.DatetimeIndex):
            out = out.reset_index()
            index_col = out.columns[0]
            out = out.rename(columns={index_col: "event_time"})
        elif out.index.name in candidates or out.index.name == "event_time":
            out = out.reset_index().rename(columns={out.index.name or "index": "event_time"})
        else:
            available = ", ".join(map(str, out.columns[:30]))
            raise ValueError(
                "A base não contém coluna temporal reconhecida. "
                "Esperado um de: event_time, time, datetime, timestamp, "
                "date_time, date, open_time, candle_time; "
                f"colunas disponíveis: {available}"
            )

    raw_time = out["event_time"]
    if pd.api.types.is_numeric_dtype(raw_time):
        numeric = pd.to_numeric(raw_time, errors="coerce")
        valid = numeric.dropna()
        if not valid.empty:
            magnitude = float(valid.abs().median())
            if magnitude >= 1e17:
                unit = "ns"
            elif magnitude >= 1e14:
                unit = "us"
            elif magnitude >= 1e11:
                unit = "ms"
            else:
                unit = "s"
            parsed = pd.to_datetime(numeric, unit=unit, errors="coerce")
        else:
            parsed = pd.to_datetime(raw_time, errors="coerce")
    else:
        parsed = pd.to_datetime(raw_time, errors="coerce")

    out["event_time"] = parsed
    out = (
        out.dropna(subset=["event_time"])
        .sort_values("event_time")
        .drop_duplicates("event_time", keep="last")
    )
    if out.empty:
        raise ValueError("Nenhuma linha válida após normalizar event_time.")
    return out.reset_index(drop=True)


def read_runtime_window(path: Path, warmup_bars: int) -> tuple[pd.DataFrame, int]:
    if not path.exists():
        raise FileNotFoundError(f"Base MTF não encontrada: {path}")
    raw = pd.read_parquet(path)
    total = len(raw)
    raw = normalize_event_time(raw)
    if warmup_bars > 0 and len(raw) > warmup_bars:
        raw = raw.tail(warmup_bars).reset_index(drop=True)
    return raw, total


def _prefix_timeframe_columns(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    out = normalize_event_time(df)
    prefix = f"{tf}_"
    rename = {}
    for col in out.columns:
        if col == "event_time":
            continue
        name = str(col)
        if name.startswith(prefix):
            continue
        rename[col] = f"{prefix}{name}"
    return out.rename(columns=rename)


def read_live_mtf_window(
    root: Path,
    symbol: str,
    anchor_tf: str,
    timeframes: list[str],
    warmup_bars: int,
    template: str = DEFAULT_LIVE_TEMPLATE,
) -> tuple[pd.DataFrame, int, list[str]]:
    ordered = []
    for tf in [anchor_tf, *timeframes]:
        tf = str(tf).upper()
        if tf not in ordered:
            ordered.append(tf)
    if anchor_tf not in ordered:
        ordered.insert(0, anchor_tf)

    loaded: dict[str, pd.DataFrame] = {}
    source_paths: list[str] = []
    for tf in ordered:
        path = root / template.format(symbol=symbol, tf=tf, anchor_tf=anchor_tf)
        if not path.exists():
            raise FileNotFoundError(f"Parquet live não encontrado para {tf}: {path}")
        frame = pd.read_parquet(path)
        loaded[tf] = _prefix_timeframe_columns(frame, tf)
        source_paths.append(str(path))

    anchor = loaded[anchor_tf].copy().sort_values("event_time")
    total_rows = len(anchor)
    if warmup_bars > 0 and len(anchor) > warmup_bars:
        anchor = anchor.tail(warmup_bars).reset_index(drop=True)

    merged = anchor
    for tf in ordered:
        if tf == anchor_tf:
            continue
        higher = loaded[tf].sort_values("event_time")
        merged = pd.merge_asof(
            merged.sort_values("event_time"),
            higher,
            on="event_time",
            direction="backward",
            allow_exact_matches=True,
        )

    merged = normalize_event_time(merged)
    return merged, total_rows, source_paths


def build_features(df: pd.DataFrame, engine: Any, anchor_tf: str) -> pd.DataFrame:
    out = engine.add_core_features(df, anchor_tf)
    out = engine.add_state_dna_features(out)
    out = engine.add_setup_genome_features(out)
    out = engine.add_htf_location_features(out, anchor_tf)
    out = engine.add_sequence_dna_features(out, anchor_tf)
    out = engine.add_memory_engine_features(out, anchor_tf)
    out = engine.add_law_segmentation_features(out)
    return out


STATE_FIELDS = (
    "event_time",
    "hour",
    "time_slot",
    "session_brt",
    "weekday",
    "anchor_direction",
    "anchor_market_state",
    "anchor_vol_bucket",
    "anchor_range_bucket",
    "anchor_body_bucket",
    "anchor_close_position_bucket",
    "anchor_range_atr",
    "anchor_body_atr",
    "anchor_vol_ratio",
    "energy_score",
    "energy_bucket",
    "mtf_alignment_score",
    "mtf_alignment_count",
    "mtf_alignment_bucket",
    "mtf_bias",
    "htf_location_bias",
    "breakout_location_alignment",
    "level_proximity",
    "nearest_resistance_atr",
    "nearest_support_atr",
    "resistance_bucket",
    "support_bucket",
    "event_name",
    "event_breakout",
    "event_breakout_up",
    "event_breakout_down",
    "event_false_breakout",
    "event_sweep",
    "event_compression",
    "event_expansion",
    "level_attempt_start",
    "level_attempt_side",
    "level_cycle_id",
    "level_price",
    "level_attempt_number",
    "level_attempt_cluster_length",
    "level_reset_reason",
    "level_age_bars",
    "distance_from_level_atr",
    "accepted_breakout",
    "attempt_bucket",
    "attempt_quality",
    "attempt_energy_delta",
    "attempt_range_delta",
    "failure_episode_start",
    "failure_episode_side",
    "failure_episode_id",
    "failures_on_current_level",
    "bars_since_level_failure",
    "failure_memory_bucket",
    "bars_since_breakout_episode",
    "bars_since_false_break",
    "bars_since_sweep",
    "attempts_since_false_break",
    "attempts_since_sweep",
    "attempts_since_level_failure",
    "recent_failure_count_24",
    "memory_condition",
    "sequence_regime",
)


def extract_state(row: Mapping[str, Any]) -> dict[str, Any]:
    state = {field: row.get(field) for field in STATE_FIELDS if field in row}
    # Aliases explícitos usados pelos moduladores do registry.
    if "energy_bucket" in state:
        state.setdefault("energy", state["energy_bucket"])
    if "htf_location_bias" in state:
        state.setdefault("htf_location", state["htf_location_bias"])
    if "breakout_location_alignment" in state:
        state.setdefault("breakout_alignment", state["breakout_location_alignment"])
    return clean_json(state)


def parse_timestamp(value: Any, event_timezone: str = "UTC") -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        try:
            ts = ts.tz_localize(event_timezone)
        except Exception as exc:
            raise ValueError(f"Timezone inválido para event_time: {event_timezone}") from exc
    return ts.tz_convert("UTC")


def freshness_info(event_time: Any, max_age_minutes: int, event_timezone: str = "UTC") -> dict[str, Any]:
    event_ts = parse_timestamp(event_time, event_timezone)
    now = pd.Timestamp.now(tz="UTC")
    if event_ts is None:
        return {"status": "UNKNOWN", "age_minutes": None, "max_age_minutes": max_age_minutes}
    age = max(0.0, (now - event_ts).total_seconds() / 60.0)
    return {
        "status": "FRESH" if age <= max_age_minutes else "STALE",
        "age_minutes": round(age, 2),
        "max_age_minutes": max_age_minutes,
    }


def build_state_payload(
    state: Mapping[str, Any],
    symbol: str,
    anchor_tf: str,
    input_path: Path | None,
    total_rows: int,
    processed_rows: int,
    warmup_bars: int,
    freshness: Mapping[str, Any],
    source_mode: str = "lab",
    source_paths: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "builder_version": "CHRONOS_STATE_BUILDER_V1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "anchor_tf": anchor_tf,
        "source": {
            "mode": source_mode,
            "input": str(input_path) if input_path is not None else None,
            "inputs": source_paths or ([str(input_path)] if input_path is not None else []),
            "total_rows": total_rows,
            "processed_rows": processed_rows,
            "warmup_bars": warmup_bars,
        },
        "freshness": dict(freshness),
        "chronos_state": dict(state),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market Chronos Runtime — State Builder + Matcher")
    parser.add_argument("--symbol", default="GOLD")
    parser.add_argument("--anchor-tf", default="M5")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument(
        "--source-mode",
        choices=["lab", "live"],
        default="lab",
        help="Fonte dos dados: lab usa a base MTF histórica; live funde os Parquets atuais por timeframe.",
    )
    parser.add_argument(
        "--live-timeframes",
        nargs="+",
        default=["M5", "M15", "H1", "H4"],
        help="Timeframes live a fundir usando o anchor como base.",
    )
    parser.add_argument(
        "--live-template",
        default=DEFAULT_LIVE_TEMPLATE,
        help="Template dos Parquets live (default: data/{symbol}_{tf}.parquet).",
    )
    parser.add_argument(
        "--event-timezone",
        default="Etc/GMT-2",
        help="Timezone dos timestamps sem offset nos Parquets live.",
    )
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--engine", default=DEFAULT_ENGINE)
    parser.add_argument("--state-output", default=DEFAULT_STATE_OUTPUT)
    parser.add_argument("--intelligence-output", default=DEFAULT_INTELLIGENCE_OUTPUT)
    parser.add_argument(
        "--warmup-bars",
        type=int,
        default=5000,
        help="Quantidade de candles recentes usada para reconstruir memória/tentativas (default: 5000).",
    )
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=30,
        help="Idade máxima para considerar o estado atual (default: 30 minutos).",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Retorna erro quando o último candle estiver mais antigo que --max-age-minutes.",
    )
    parser.add_argument("--no-diagnostics", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    symbol = args.symbol.upper()
    anchor_tf = args.anchor_tf.upper()

    input_path = root / args.input.format(symbol=symbol, anchor_tf=anchor_tf)
    registry_path = root / args.registry.format(symbol=symbol, anchor_tf=anchor_tf)
    engine_path = root / args.engine.format(symbol=symbol, anchor_tf=anchor_tf)
    state_output = root / args.state_output.format(symbol=symbol, anchor_tf=anchor_tf)
    intelligence_output = root / args.intelligence_output.format(symbol=symbol, anchor_tf=anchor_tf)

    log(f"Engine: {engine_path}")
    engine = load_engine_module(engine_path)
    registry = load_json(registry_path)

    if str(registry.get("symbol", symbol)).upper() != symbol:
        raise ValueError(f"Registry pertence a {registry.get('symbol')}, mas o runtime recebeu {symbol}.")
    if str(registry.get("anchor_tf", anchor_tf)).upper() != anchor_tf:
        raise ValueError(f"Registry pertence a {registry.get('anchor_tf')}, mas o runtime recebeu {anchor_tf}.")

    source_paths: list[str] = []
    if args.source_mode == "live":
        live_tfs = [str(tf).upper() for tf in args.live_timeframes]
        log(f"Lendo e fundindo Parquets live: {', '.join(live_tfs)}")
        window, total_rows, source_paths = read_live_mtf_window(
            root=root,
            symbol=symbol,
            anchor_tf=anchor_tf,
            timeframes=live_tfs,
            warmup_bars=max(200, args.warmup_bars),
            template=args.live_template,
        )
        effective_input_path = None
    else:
        log(f"Lendo janela runtime: {input_path}")
        window, total_rows = read_runtime_window(input_path, max(200, args.warmup_bars))
        source_paths = [str(input_path)]
        effective_input_path = input_path
    log(f"Processando {len(window)} de {total_rows} linhas | source_mode={args.source_mode}")
    features = build_features(window, engine, anchor_tf)
    if features.empty:
        raise RuntimeError("O State Builder não produziu linhas.")

    latest = features.sort_values("event_time").iloc[-1].to_dict()
    state = extract_state(latest)
    freshness = freshness_info(state.get("event_time"), args.max_age_minutes, args.event_timezone)
    state_payload = build_state_payload(
        state=state,
        symbol=symbol,
        anchor_tf=anchor_tf,
        input_path=effective_input_path,
        total_rows=total_rows,
        processed_rows=len(features),
        warmup_bars=max(200, args.warmup_bars),
        freshness=freshness,
        source_mode=args.source_mode,
        source_paths=source_paths,
    )
    save_json(state_output, state_payload)

    intelligence = engine.match_market_laws(
        state,
        registry,
        include_diagnostics=not args.no_diagnostics,
    )
    intelligence["state_builder_version"] = "CHRONOS_STATE_BUILDER_V1"
    intelligence["state_file"] = str(state_output)
    intelligence["registry_file"] = str(registry_path)
    intelligence["freshness"] = freshness
    intelligence["source_mode"] = args.source_mode
    intelligence["source_paths"] = source_paths
    save_json(intelligence_output, intelligence)

    summary = {
        "mode": "runtime_builder",
        "symbol": symbol,
        "anchor_tf": anchor_tf,
        "source_mode": args.source_mode,
        "event_time": state.get("event_time"),
        "freshness": freshness,
        "processed_rows": len(features),
        "state_output": str(state_output),
        "intelligence_output": str(intelligence_output),
        "matched_laws": intelligence.get("matched_count", 0),
        "runtime_action": intelligence.get("chronos_action"),
        "supporting_side": intelligence.get("supporting_side"),
        "blocked_actions": intelligence.get("blocked_actions", []),
    }
    log("OK")
    print(json.dumps(clean_json(summary), ensure_ascii=False, indent=2))

    if args.fail_on_stale and freshness.get("status") == "STALE":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
