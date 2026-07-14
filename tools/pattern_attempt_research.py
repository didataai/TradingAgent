#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingAgent - Pattern Attempt Research
=======================================

Objetivo
--------
Estudar, de forma separada do operacional, como padroes/formacoes graficas
se comportam apos tentativas de rompimento.

Motivacao operacional
---------------------
A leitura pratica observada no projeto e que formacoes nem sempre rompem
limpo na primeira tentativa. Muitas vezes o preco testa uma borda, volta
para dentro da formacao e so depois decide. Por isso, este estudo mede:

- primeira, segunda e terceira tentativa de rompimento;
- tentativas aceitas vs. falso rompimento / retorno para dentro;
- comportamento por timeframe;
- comportamento por dia da semana;
- comportamento por horario;
- comportamento por sessao;
- comportamento por semana do mes;
- comportamento por tipo de padrao.

Importante
----------
Este script e somente pesquisa. Ele nao altera o payload operacional, nao
cria BUY/SELL/WAIT, nao executa ordens e nao substitui Historical
Intelligence, Chronos, Execution Quality ou Technical Patterns Context.

Compatibilidade
---------------
Desenvolvido com pathlib e caminhos relativos ao projeto para funcionar em
Windows, Linux e macOS.

Entradas esperadas
------------------
Por padrao, le os Parquets gerados pelo Base_Dados.py:

    data/<SYMBOL>_M1.parquet
    data/<SYMBOL>_M5.parquet
    data/<SYMBOL>_M15.parquet
    data/<SYMBOL>_H1.parquet

Saidas
------
Por padrao, grava em:

    data/research/pattern_attempt/<SYMBOL>/

Arquivos principais:

    pattern_attempt_events.csv
    pattern_attempt_summary.json
    pattern_attempt_by_pattern_tf.csv
    pattern_attempt_by_hour.csv
    pattern_attempt_by_day_of_week.csv
    pattern_attempt_by_week_of_month.csv
    pattern_attempt_by_session.csv
    pattern_attempt_by_attempt_number.csv

Uso Windows PowerShell
----------------------
    python .\tools\pattern_attempt_research.py `
      --symbol GOLD

Uso Linux/macOS
---------------
    python tools/pattern_attempt_research.py \
      --symbol GOLD
"""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEFRAMES = ("M1", "M5", "M15", "H1")
DEFAULT_OUTPUT_DIR = ROOT / "data" / "research" / "pattern_attempt"


@dataclass(frozen=True)
class ResearchConfig:
    symbol: str
    timeframes: tuple[str, ...]
    window_bars: int
    lookahead_bars: int
    boundary_buffer_atr: float
    acceptance_bars: int
    min_range_atr: float
    max_range_atr: float
    min_impulse_atr: float
    output_dir: Path


@dataclass(frozen=True)
class AttemptEvent:
    symbol: str
    timeframe: str
    pattern_name: str
    pattern_family: str
    formation_time: str
    formation_date: str
    formation_hour: int
    day_of_week: str
    day_of_week_num: int
    week_of_month: int
    session_name: str
    upper_boundary: float
    lower_boundary: float
    formation_width: float
    formation_width_atr: float
    impulse_direction: str
    impulse_atr: float
    attempt_number: int
    attempt_side: str
    attempt_time: str
    attempt_result: str
    bars_after_formation: int
    close_after_attempt: float
    max_excursion_after_attempt: float
    adverse_excursion_after_attempt: float
    returned_inside: bool
    accepted: bool
    fakeout: bool


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def safe_json_dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def normalize_time_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    candidates = ["time", "datetime", "timestamp", "time_brt", "time_utc"]
    found = next((col for col in candidates if col in out.columns), None)
    if found is None:
        if isinstance(out.index, pd.DatetimeIndex):
            out = out.reset_index().rename(columns={out.index.name or "index": "time"})
            found = "time"
        else:
            raise ValueError("Nenhuma coluna de tempo encontrada no Parquet.")

    out["_time"] = pd.to_datetime(out[found], errors="coerce")
    out = out.dropna(subset=["_time"]).sort_values("_time").drop_duplicates("_time")
    return out.reset_index(drop=True)


def drop_live_bars(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "is_live_bar" in out.columns:
        out = out[out["is_live_bar"] != True]  # noqa: E712
    elif "bar_status" in out.columns:
        out = out[out["bar_status"].astype(str).str.upper() != "LIVE"]
    else:
        # Se nao houver marcador de live bar, remove o ultimo candle por seguranca.
        if len(out) > 1:
            out = out.iloc[:-1]
    return out.reset_index(drop=True)


def ensure_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    required = ["open", "high", "low", "close"]
    missing = [col for col in required if col not in out.columns]
    if missing:
        raise ValueError(f"Colunas OHLC ausentes: {missing}")
    for col in required:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=required)
    out = out[(out["high"] >= out[["open", "close", "low"]].max(axis=1)) & (out["low"] <= out[["open", "close", "high"]].min(axis=1))]
    return out.reset_index(drop=True)


def true_range_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=max(3, period // 2)).mean()
    return atr.bfill().ffill()


def session_from_hour(hour: int) -> str:
    # Sessao simples em BRT, alinhada ao uso pratico do projeto.
    if 3 <= hour < 6:
        return "PRE_LONDON"
    if 6 <= hour < 10:
        return "LONDON"
    if 10 <= hour < 13:
        return "NY_OPEN"
    if 13 <= hour < 18:
        return "NEW_YORK"
    if 18 <= hour < 21:
        return "POST_NY"
    return "ASIA_OR_OFF"


def week_of_month(ts: pd.Timestamp) -> int:
    return int(((ts.day - 1) // 7) + 1)


def slope(values: Iterable[float]) -> float:
    arr = np.asarray(list(values), dtype=float)
    if len(arr) < 2 or np.isnan(arr).any():
        return 0.0
    x = np.arange(len(arr), dtype=float)
    return float(np.polyfit(x, arr, 1)[0])


def classify_formation(window: pd.DataFrame, atr: float, cfg: ResearchConfig) -> list[dict[str, Any]]:
    high = window["high"].astype(float)
    low = window["low"].astype(float)
    close = window["close"].astype(float)
    open_ = window["open"].astype(float)

    upper = float(high.max())
    lower = float(low.min())
    width = upper - lower
    width_atr = width / max(atr, 1e-9)
    if width_atr < cfg.min_range_atr or width_atr > cfg.max_range_atr:
        return []

    half = max(3, len(window) // 2)
    first_width = float(high.iloc[:half].max() - low.iloc[:half].min())
    second_width = float(high.iloc[-half:].max() - low.iloc[-half:].min())
    compression_ratio = second_width / max(first_width, 1e-9)

    high_slope_atr = slope(high.tail(half)) / max(atr, 1e-9)
    low_slope_atr = slope(low.tail(half)) / max(atr, 1e-9)
    close_slope_atr = slope(close.tail(half)) / max(atr, 1e-9)

    impulse_slice = window.iloc[: max(3, len(window) // 3)]
    impulse_move = float(impulse_slice["close"].iloc[-1] - impulse_slice["open"].iloc[0])
    impulse_atr = impulse_move / max(atr, 1e-9)
    impulse_direction = "UP" if impulse_atr > 0 else "DOWN" if impulse_atr < 0 else "FLAT"

    patterns: list[dict[str, Any]] = []

    # Range/compressao generica.
    if compression_ratio <= 0.85:
        patterns.append({
            "pattern_name": "COMPRESSION_RANGE",
            "pattern_family": "CONSOLIDATION",
            "upper_boundary": upper,
            "lower_boundary": lower,
            "width": width,
            "width_atr": width_atr,
            "impulse_direction": impulse_direction,
            "impulse_atr": impulse_atr,
        })

    # Triangulos por inclinacao relativa das bordas.
    flat_threshold = 0.035
    trend_threshold = 0.045
    if abs(high_slope_atr) <= flat_threshold and low_slope_atr > trend_threshold:
        patterns.append({
            "pattern_name": "ASCENDING_TRIANGLE",
            "pattern_family": "FORMATION_OR_CONSOLIDATION",
            "upper_boundary": upper,
            "lower_boundary": lower,
            "width": width,
            "width_atr": width_atr,
            "impulse_direction": impulse_direction,
            "impulse_atr": impulse_atr,
        })
    if high_slope_atr < -trend_threshold and abs(low_slope_atr) <= flat_threshold:
        patterns.append({
            "pattern_name": "DESCENDING_TRIANGLE",
            "pattern_family": "FORMATION_OR_CONSOLIDATION",
            "upper_boundary": upper,
            "lower_boundary": lower,
            "width": width,
            "width_atr": width_atr,
            "impulse_direction": impulse_direction,
            "impulse_atr": impulse_atr,
        })
    if high_slope_atr < -trend_threshold and low_slope_atr > trend_threshold:
        patterns.append({
            "pattern_name": "SYMMETRICAL_TRIANGLE",
            "pattern_family": "FORMATION_OR_CONSOLIDATION",
            "upper_boundary": upper,
            "lower_boundary": lower,
            "width": width,
            "width_atr": width_atr,
            "impulse_direction": impulse_direction,
            "impulse_atr": impulse_atr,
        })

    # Bandeiras: impulso relevante seguido por canal/pullback curto contra o impulso.
    if abs(impulse_atr) >= cfg.min_impulse_atr:
        if impulse_direction == "UP" and close_slope_atr < -0.035:
            patterns.append({
                "pattern_name": "BULL_FLAG",
                "pattern_family": "CONTINUATION_CANDIDATE",
                "upper_boundary": upper,
                "lower_boundary": lower,
                "width": width,
                "width_atr": width_atr,
                "impulse_direction": impulse_direction,
                "impulse_atr": impulse_atr,
            })
        elif impulse_direction == "DOWN" and close_slope_atr > 0.035:
            patterns.append({
                "pattern_name": "BEAR_FLAG",
                "pattern_family": "CONTINUATION_CANDIDATE",
                "upper_boundary": upper,
                "lower_boundary": lower,
                "width": width,
                "width_atr": width_atr,
                "impulse_direction": impulse_direction,
                "impulse_atr": impulse_atr,
            })

    # Evita duplicidade excessiva quando nada especifico foi detectado.
    if not patterns and width_atr <= 2.0:
        patterns.append({
            "pattern_name": "RANGE_RECTANGLE",
            "pattern_family": "CONSOLIDATION",
            "upper_boundary": upper,
            "lower_boundary": lower,
            "width": width,
            "width_atr": width_atr,
            "impulse_direction": impulse_direction,
            "impulse_atr": impulse_atr,
        })

    return patterns


def attempt_result(
    df: pd.DataFrame,
    attempt_idx: int,
    side: str,
    upper: float,
    lower: float,
    buffer: float,
    cfg: ResearchConfig,
) -> dict[str, Any]:
    end_idx = min(len(df) - 1, attempt_idx + cfg.acceptance_bars)
    future = df.iloc[attempt_idx : end_idx + 1]
    close_after = float(future["close"].iloc[-1])

    if side == "UP":
        accepted = bool((future["close"] > upper + buffer).all())
        returned_inside = bool((future["close"] <= upper).any())
        max_excursion = float(future["high"].max() - upper)
        adverse = float(upper - future["low"].min())
    else:
        accepted = bool((future["close"] < lower - buffer).all())
        returned_inside = bool((future["close"] >= lower).any())
        max_excursion = float(lower - future["low"].min())
        adverse = float(future["high"].max() - lower)

    fakeout = bool(returned_inside and not accepted)
    if accepted:
        result = "ACCEPTED_BREAKOUT"
    elif fakeout:
        result = "FAILED_BREAKOUT"
    else:
        result = "UNRESOLVED_ATTEMPT"

    return {
        "attempt_result": result,
        "close_after_attempt": close_after,
        "max_excursion_after_attempt": max_excursion,
        "adverse_excursion_after_attempt": adverse,
        "returned_inside": returned_inside,
        "accepted": accepted,
        "fakeout": fakeout,
    }


def extract_attempts_for_pattern(
    df: pd.DataFrame,
    start_idx: int,
    pattern: dict[str, Any],
    atr: float,
    cfg: ResearchConfig,
) -> list[dict[str, Any]]:
    upper = float(pattern["upper_boundary"])
    lower = float(pattern["lower_boundary"])
    buffer = cfg.boundary_buffer_atr * max(atr, 1e-9)
    end_idx = min(len(df) - 1, start_idx + cfg.lookahead_bars)
    attempts: list[dict[str, Any]] = []
    last_side: str | None = None
    attempt_count = 0

    for idx in range(start_idx + 1, end_idx + 1):
        row = df.iloc[idx]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        side = None
        if high > upper + buffer:
            side = "UP"
        elif low < lower - buffer:
            side = "DOWN"

        if side is None:
            continue

        # Conta nova tentativa quando o lado muda ou quando houve volta para dentro depois da tentativa anterior.
        if side != last_side:
            attempt_count += 1
        else:
            previous = attempts[-1] if attempts else {}
            if previous.get("returned_inside") is True:
                attempt_count += 1
            else:
                continue

        result = attempt_result(df, idx, side, upper, lower, buffer, cfg)
        attempts.append({
            "attempt_number": attempt_count,
            "attempt_side": side,
            "attempt_idx": idx,
            "attempt_time": row["_time"],
            "bars_after_formation": idx - start_idx,
            "close_at_attempt": close,
            **result,
        })
        last_side = side

        if attempt_count >= 3:
            # O foco atual do estudo e primeira/segunda/terceira tentativa.
            break

    return attempts


def event_from_attempt(
    symbol: str,
    timeframe: str,
    formation_idx: int,
    df: pd.DataFrame,
    pattern: dict[str, Any],
    attempt: dict[str, Any],
) -> AttemptEvent:
    ts = pd.Timestamp(df.iloc[formation_idx]["_time"])
    attempt_ts = pd.Timestamp(attempt["attempt_time"])
    day_name = ts.day_name()
    hour = int(ts.hour)

    return AttemptEvent(
        symbol=symbol,
        timeframe=timeframe,
        pattern_name=str(pattern["pattern_name"]),
        pattern_family=str(pattern["pattern_family"]),
        formation_time=ts.isoformat(),
        formation_date=ts.date().isoformat(),
        formation_hour=hour,
        day_of_week=day_name,
        day_of_week_num=int(ts.dayofweek),
        week_of_month=week_of_month(ts),
        session_name=session_from_hour(hour),
        upper_boundary=round(float(pattern["upper_boundary"]), 5),
        lower_boundary=round(float(pattern["lower_boundary"]), 5),
        formation_width=round(float(pattern["width"]), 5),
        formation_width_atr=round(float(pattern["width_atr"]), 5),
        impulse_direction=str(pattern["impulse_direction"]),
        impulse_atr=round(float(pattern["impulse_atr"]), 5),
        attempt_number=int(attempt["attempt_number"]),
        attempt_side=str(attempt["attempt_side"]),
        attempt_time=attempt_ts.isoformat(),
        attempt_result=str(attempt["attempt_result"]),
        bars_after_formation=int(attempt["bars_after_formation"]),
        close_after_attempt=round(float(attempt["close_after_attempt"]), 5),
        max_excursion_after_attempt=round(float(attempt["max_excursion_after_attempt"]), 5),
        adverse_excursion_after_attempt=round(float(attempt["adverse_excursion_after_attempt"]), 5),
        returned_inside=bool(attempt["returned_inside"]),
        accepted=bool(attempt["accepted"]),
        fakeout=bool(attempt["fakeout"]),
    )


def read_timeframe(symbol: str, timeframe: str) -> pd.DataFrame:
    path = ROOT / "data" / f"{symbol}_{timeframe}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Parquet nao encontrado: {path}")
    df = pd.read_parquet(path)
    df = normalize_time_column(df)
    df = drop_live_bars(df)
    df = ensure_ohlc(df)
    df["_atr"] = true_range_atr(df)
    return df


def run_timeframe(symbol: str, timeframe: str, cfg: ResearchConfig) -> list[AttemptEvent]:
    df = read_timeframe(symbol, timeframe)
    events: list[AttemptEvent] = []
    if len(df) < cfg.window_bars + cfg.lookahead_bars + 5:
        return events

    step = max(1, cfg.window_bars // 3)
    for formation_idx in range(cfg.window_bars, len(df) - cfg.lookahead_bars - 1, step):
        window = df.iloc[formation_idx - cfg.window_bars : formation_idx]
        atr = safe_float(df.iloc[formation_idx]["_atr"], None)
        if atr is None or atr <= 0:
            continue

        patterns = classify_formation(window, atr, cfg)
        for pattern in patterns:
            attempts = extract_attempts_for_pattern(df, formation_idx, pattern, atr, cfg)
            for attempt in attempts:
                events.append(event_from_attempt(symbol, timeframe, formation_idx, df, pattern, attempt))
    return events


def rate_table(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=group_cols + ["events", "accepted", "fakeouts", "accepted_rate", "fakeout_rate", "avg_bars_after_formation"])

    grouped = df.groupby(group_cols, dropna=False).agg(
        events=("attempt_result", "size"),
        accepted=("accepted", "sum"),
        fakeouts=("fakeout", "sum"),
        avg_bars_after_formation=("bars_after_formation", "mean"),
        avg_max_excursion=("max_excursion_after_attempt", "mean"),
        avg_adverse_excursion=("adverse_excursion_after_attempt", "mean"),
    ).reset_index()
    grouped["accepted_rate"] = grouped["accepted"] / grouped["events"]
    grouped["fakeout_rate"] = grouped["fakeouts"] / grouped["events"]
    grouped["avg_bars_after_formation"] = grouped["avg_bars_after_formation"].round(3)
    grouped["avg_max_excursion"] = grouped["avg_max_excursion"].round(5)
    grouped["avg_adverse_excursion"] = grouped["avg_adverse_excursion"].round(5)
    grouped["accepted_rate"] = grouped["accepted_rate"].round(5)
    grouped["fakeout_rate"] = grouped["fakeout_rate"].round(5)
    return grouped.sort_values(["events", "fakeout_rate", "accepted_rate"], ascending=[False, False, False])


def save_reports(events: list[AttemptEvent], cfg: ResearchConfig) -> dict[str, Any]:
    output = cfg.output_dir / cfg.symbol
    output.mkdir(parents=True, exist_ok=True)

    event_rows = [asdict(event) for event in events]
    df = pd.DataFrame(event_rows)
    events_path = output / "pattern_attempt_events.csv"
    df.to_csv(events_path, index=False, encoding="utf-8-sig")

    reports = {
        "by_pattern_tf": rate_table(df, ["timeframe", "pattern_name"]),
        "by_hour": rate_table(df, ["timeframe", "formation_hour"]),
        "by_day_of_week": rate_table(df, ["timeframe", "day_of_week_num", "day_of_week"]),
        "by_week_of_month": rate_table(df, ["timeframe", "week_of_month"]),
        "by_session": rate_table(df, ["timeframe", "session_name"]),
        "by_attempt_number": rate_table(df, ["timeframe", "attempt_number"]),
        "by_pattern_attempt_number": rate_table(df, ["timeframe", "pattern_name", "attempt_number"]),
        "by_pattern_hour": rate_table(df, ["timeframe", "pattern_name", "formation_hour"]),
        "by_pattern_week_of_month": rate_table(df, ["timeframe", "pattern_name", "week_of_month"]),
    }

    for name, table in reports.items():
        table.to_csv(output / f"pattern_attempt_{name}.csv", index=False, encoding="utf-8-sig")

    summary: dict[str, Any] = {
        "symbol": cfg.symbol,
        "timeframes": list(cfg.timeframes),
        "config": {
            "window_bars": cfg.window_bars,
            "lookahead_bars": cfg.lookahead_bars,
            "boundary_buffer_atr": cfg.boundary_buffer_atr,
            "acceptance_bars": cfg.acceptance_bars,
            "min_range_atr": cfg.min_range_atr,
            "max_range_atr": cfg.max_range_atr,
            "min_impulse_atr": cfg.min_impulse_atr,
        },
        "total_events": int(len(df)),
        "outputs": {
            "events": str(events_path),
            **{name: str(output / f"pattern_attempt_{name}.csv") for name in reports},
        },
        "interpretation_rule": "Research only. High fakeout_rate suggests avoiding chase; third attempt watch still requires candle close, acceptance, volume and operational permission.",
    }

    if not df.empty:
        summary["overall"] = {
            "accepted_rate": round(float(df["accepted"].mean()), 5),
            "fakeout_rate": round(float(df["fakeout"].mean()), 5),
            "attempts_by_number": {str(k): int(v) for k, v in df["attempt_number"].value_counts().sort_index().items()},
            "events_by_timeframe": {str(k): int(v) for k, v in df["timeframe"].value_counts().items()},
            "events_by_pattern": {str(k): int(v) for k, v in df["pattern_name"].value_counts().items()},
        }
        top_fakeouts = reports["by_pattern_attempt_number"].head(20).to_dict(orient="records")
        summary["top_pattern_attempt_rows"] = top_fakeouts
    else:
        summary["overall"] = {
            "accepted_rate": None,
            "fakeout_rate": None,
            "attempts_by_number": {},
            "events_by_timeframe": {},
            "events_by_pattern": {},
        }
        summary["top_pattern_attempt_rows"] = []

    safe_json_dump(output / "pattern_attempt_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pesquisa tentativas de rompimento por padrao, horario, dia e semana do mes.")
    parser.add_argument("--symbol", default="GOLD", help="Simbolo. Padrao: GOLD.")
    parser.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES), help="Timeframes a estudar.")
    parser.add_argument("--window-bars", type=int, default=24, help="Janela de formacao em candles. Padrao: 24.")
    parser.add_argument("--lookahead-bars", type=int, default=24, help="Janela futura para procurar tentativas. Padrao: 24.")
    parser.add_argument("--boundary-buffer-atr", type=float, default=0.05, help="Buffer de rompimento em ATR. Padrao: 0.05.")
    parser.add_argument("--acceptance-bars", type=int, default=2, help="Candles necessarios para aceitar rompimento. Padrao: 2.")
    parser.add_argument("--min-range-atr", type=float, default=0.25, help="Largura minima da formacao em ATR. Padrao: 0.25.")
    parser.add_argument("--max-range-atr", type=float, default=4.0, help="Largura maxima da formacao em ATR. Padrao: 4.0.")
    parser.add_argument("--min-impulse-atr", type=float, default=0.80, help="Impulso minimo para flags em ATR. Padrao: 0.80.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Diretorio base de saida.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbol = args.symbol.upper().strip()
    timeframes = tuple(tf.upper().strip() for tf in args.timeframes if str(tf).strip())
    cfg = ResearchConfig(
        symbol=symbol,
        timeframes=timeframes,
        window_bars=max(8, int(args.window_bars)),
        lookahead_bars=max(3, int(args.lookahead_bars)),
        boundary_buffer_atr=max(0.0, float(args.boundary_buffer_atr)),
        acceptance_bars=max(1, int(args.acceptance_bars)),
        min_range_atr=max(0.01, float(args.min_range_atr)),
        max_range_atr=max(0.05, float(args.max_range_atr)),
        min_impulse_atr=max(0.01, float(args.min_impulse_atr)),
        output_dir=Path(args.output_dir) if Path(args.output_dir).is_absolute() else ROOT / args.output_dir,
    )

    all_events: list[AttemptEvent] = []
    errors: dict[str, str] = {}
    for tf in cfg.timeframes:
        try:
            tf_events = run_timeframe(symbol, tf, cfg)
            all_events.extend(tf_events)
            print(f"[OK] {symbol} {tf} | events={len(tf_events)}")
        except Exception as exc:
            errors[tf] = f"{type(exc).__name__}: {exc}"
            print(f"[WARN] {symbol} {tf} ignorado | {errors[tf]}")

    summary = save_reports(all_events, cfg)
    if errors:
        summary["errors"] = errors
        safe_json_dump(cfg.output_dir / cfg.symbol / "pattern_attempt_summary.json", summary)

    print(
        f"[OK] Pattern Attempt Research | symbol={symbol} | "
        f"events={summary.get('total_events')} | output={cfg.output_dir / cfg.symbol}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
