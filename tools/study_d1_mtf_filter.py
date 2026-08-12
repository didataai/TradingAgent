#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TF_MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}
HORIZONS_MIN = (30, 60, 120)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"JSON inválido: {path}")
    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    tmp.replace(path)


def bseries(s: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(s):
        return s.fillna(False)
    if pd.api.types.is_numeric_dtype(s):
        return s.fillna(0).astype(int).astype(bool)
    return s.astype(str).str.lower().isin({"1", "true", "yes", "sim"})


def _broker_col(df: pd.DataFrame, rules: dict[str, Any]) -> str:
    clock = rules.get("daily_session_clock", {}) or {}
    for col in clock.get("preferred_columns", ["time_broker", "time"]):
        if col in df.columns:
            return col
    if "time_brt" in df.columns:
        return "time_brt"
    raise ValueError("Nenhuma coluna temporal encontrada para o dia do broker.")


def _to_brt(series: pd.Series, source_col: str, rules: dict[str, Any]) -> pd.Series:
    if source_col == "time_brt":
        return pd.to_datetime(series, errors="coerce")
    broker_tz = str((rules.get("daily_session_clock", {}) or {}).get("timezone") or "Etc/GMT-2")
    brt_tz = str((rules.get("operational_window_brt", {}) or {}).get("timezone") or "America/Sao_Paulo")
    ts = pd.to_datetime(series, errors="coerce")

    def convert(v: pd.Timestamp) -> pd.Timestamp:
        if pd.isna(v):
            return pd.NaT
        x = pd.Timestamp(v)
        try:
            if x.tzinfo is None:
                x = x.tz_localize(ZoneInfo(broker_tz))
            else:
                x = x.tz_convert(ZoneInfo(broker_tz))
            return x.tz_convert(ZoneInfo(brt_tz)).tz_localize(None)
        except Exception:
            return pd.NaT

    return ts.map(convert)


def _direction(df: pd.DataFrame) -> pd.Series:
    up = pd.Series(False, index=df.index)
    down = pd.Series(False, index=df.index)
    if "breakout_up" in df.columns:
        up |= bseries(df["breakout_up"])
    if "false_breakout_up" in df.columns:
        up |= bseries(df["false_breakout_up"])
    if "breakout_down" in df.columns:
        down |= bseries(df["breakout_down"])
    if "false_breakout_down" in df.columns:
        down |= bseries(df["false_breakout_down"])

    body = pd.Series(0, index=df.index, dtype="int64")
    if "body_direction" in df.columns:
        body = pd.to_numeric(df["body_direction"], errors="coerce").fillna(0).astype(int)
    else:
        body = np.select([df["close"] > df["open"], df["close"] < df["open"]], [1, -1], default=0)
        body = pd.Series(body, index=df.index)

    out = pd.Series("NONE", index=df.index, dtype="object")
    out.loc[body == 1] = "UP"
    out.loc[body == -1] = "DOWN"
    out.loc[down] = "DOWN"
    out.loc[up] = "UP"
    return out


def prepare(path: Path, tf: str, rules: dict[str, Any]) -> pd.DataFrame:
    df = pd.read_parquet(path).copy()
    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            raise ValueError(f"{path.name}: coluna {c} ausente")
        df[c] = pd.to_numeric(df[c], errors="coerce")

    bc = _broker_col(df, rules)
    df["broker_time"] = pd.to_datetime(df[bc], errors="coerce")
    if "time_brt" in df.columns:
        df["time_brt_norm"] = pd.to_datetime(df["time_brt"], errors="coerce")
    else:
        df["time_brt_norm"] = _to_brt(df[bc], bc, rules)

    if "is_live_bar" in df.columns:
        df = df.loc[~bseries(df["is_live_bar"])].copy()

    df = df.dropna(subset=["broker_time", "time_brt_norm", "open", "high", "low", "close"])
    df = df.sort_values("broker_time").drop_duplicates("broker_time", keep="last").reset_index(drop=True)
    df["direction"] = _direction(df)
    df["available_at_brt"] = df["time_brt_norm"] + pd.to_timedelta(TF_MINUTES[tf], unit="m")
    df["broker_date"] = df["broker_time"].dt.date
    return df


def add_d1_point_in_time(m5: pd.DataFrame) -> pd.DataFrame:
    x = m5.copy()
    g = x.groupby("broker_date", sort=False)
    x["d1_open"] = g["open"].transform("first")
    x["d1_high_so_far"] = g["high"].cummax()
    x["d1_low_so_far"] = g["low"].cummin()
    rng = (x["d1_high_so_far"] - x["d1_low_so_far"]).replace(0, np.nan)
    x["d1_position"] = ((x["close"] - x["d1_low_so_far"]) / rng).fillna(0.5).clip(0, 1)
    x["daily_direction"] = np.select(
        [x["close"] > x["d1_open"], x["close"] < x["d1_open"]],
        ["BULLISH", "BEARISH"],
        default="NEUTRAL",
    )
    return x


def in_window(ts: pd.Series, rules: dict[str, Any]) -> pd.Series:
    cfg = rules.get("operational_window_brt", {}) or {}
    start = str(cfg.get("start") or "09:00")
    end = str(cfg.get("end") or "18:00")
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    cur = ts.dt.hour * 60 + ts.dt.minute
    a = sh * 60 + sm
    b = eh * 60 + em
    return ((cur >= a) & (cur <= b)) if a <= b else ((cur >= a) | (cur <= b))


def zone_name(position: float, daily_direction: str, rules: dict[str, Any]) -> tuple[str | None, bool]:
    cfg = rules.get("daily_position_filter", {}) or {}
    for z in cfg.get("zones", []):
        lo = float(z["min"])
        hi = float(z["max"])
        if lo <= position < hi:
            req = str(z.get("required_daily_direction") or "").upper()
            return str(z.get("name")), (not req or req == daily_direction)
    return None, False


def merge_parent(anchor: pd.DataFrame, parent: pd.DataFrame, name: str) -> pd.DataFrame:
    right = parent[["available_at_brt", "direction"]].rename(columns={"direction": f"{name}_direction"}).sort_values("available_at_brt")
    return pd.merge_asof(
        anchor.sort_values("available_at_brt"),
        right,
        on="available_at_brt",
        direction="backward",
        allow_exact_matches=True,
    )


def add_future_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    for minutes in HORIZONS_MIN:
        bars = minutes // 5
        future_close = x["close"].shift(-bars)
        raw = future_close - x["close"]
        x[f"future_delta_{minutes}"] = raw
        highs = pd.concat([x["high"].shift(-i) for i in range(1, bars + 1)], axis=1).max(axis=1)
        lows = pd.concat([x["low"].shift(-i) for i in range(1, bars + 1)], axis=1).min(axis=1)
        x[f"mfe_buy_{minutes}"] = highs - x["close"]
        x[f"mae_buy_{minutes}"] = x["close"] - lows
        x[f"mfe_sell_{minutes}"] = x["close"] - lows
        x[f"mae_sell_{minutes}"] = highs - x["close"]
    return x


def directional_return(sample: pd.DataFrame, minutes: int) -> pd.Series:
    raw = sample[f"future_delta_{minutes}"]
    sign = sample["side"].map({"BUY": 1.0, "SELL": -1.0})
    return raw * sign


def metrics(sample: pd.DataFrame, minutes: int) -> dict[str, Any]:
    s = sample.dropna(subset=[f"future_delta_{minutes}"]).copy()
    if s.empty:
        return {"n": 0, "win_rate": None, "mean_return": None, "median_return": None, "profit_factor": None, "mean_mfe": None, "mean_mae": None}
    r = directional_return(s, minutes)
    wins = r[r > 0]
    losses = r[r < 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and abs(losses.sum()) > 0 else None
    mfe = np.where(s["side"].eq("BUY"), s[f"mfe_buy_{minutes}"], s[f"mfe_sell_{minutes}"])
    mae = np.where(s["side"].eq("BUY"), s[f"mae_buy_{minutes}"], s[f"mae_sell_{minutes}"])
    return {
        "n": int(len(s)),
        "win_rate": float((r > 0).mean()),
        "mean_return": float(r.mean()),
        "median_return": float(r.median()),
        "profit_factor": pf,
        "mean_mfe": float(np.nanmean(mfe)),
        "mean_mae": float(np.nanmean(mae)),
    }


def first_event_per_broker_day(sample: pd.DataFrame) -> pd.DataFrame:
    if sample.empty:
        return sample
    return sample.sort_values("available_at_brt").drop_duplicates(["broker_date"], keep="first")


def strategy_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    baseline = df["side"].isin(["BUY", "SELL"])
    bullish = df["zone"].eq("BULLISH_CONTINUATION") & df["zone_qualified"] & df["side"].eq("BUY")
    bearish = df["zone"].eq("BEARISH_CONTINUATION") & df["zone_qualified"] & df["side"].eq("SELL")
    neutral = df["zone"].eq("NEUTRAL")
    extreme_high_ok = df["zone"].eq("EXTREME_HIGH") & ~df["side"].eq("BUY")
    extreme_low_ok = df["zone"].eq("EXTREME_LOW") & ~df["side"].eq("SELL")
    unqualified = ~df["zone_qualified"] & df["zone"].isin(["BULLISH_CONTINUATION", "BEARISH_CONTINUATION"])

    return {
        "BASELINE_MTF": baseline,
        "D1_SOFT_DIRECTIONAL": baseline & (bullish | bearish | neutral | extreme_high_ok | extreme_low_ok | unqualified),
        "D1_STRICT_ZONE_ONLY": baseline & (bullish | bearish),
        "D1_NO_CHASE": baseline & ~(
            (df["zone"].eq("EXTREME_HIGH") & df["side"].eq("BUY"))
            | (df["zone"].eq("EXTREME_LOW") & df["side"].eq("SELL"))
        ),
    }


def split_edges(events: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    ordered = events.sort_values("available_at_brt")
    if len(ordered) < 5:
        t = ordered["available_at_brt"].iloc[-1] if len(ordered) else pd.Timestamp.min
        return t, t
    a = ordered["available_at_brt"].iloc[int(len(ordered) * 0.60)]
    b = ordered["available_at_brt"].iloc[int(len(ordered) * 0.80)]
    return pd.Timestamp(a), pd.Timestamp(b)


def summarize_strategy(df: pd.DataFrame, mask: pd.Series, split_a: pd.Timestamp, split_b: pd.Timestamp) -> dict[str, Any]:
    selected = df.loc[mask].copy()
    parts = {
        "all": selected,
        "train": selected[selected["available_at_brt"] < split_a],
        "validation": selected[(selected["available_at_brt"] >= split_a) & (selected["available_at_brt"] < split_b)],
        "test": selected[selected["available_at_brt"] >= split_b],
    }
    out: dict[str, Any] = {}
    for name, part in parts.items():
        out[name] = {str(m): metrics(part, m) for m in HORIZONS_MIN}
        out[name]["first_event_per_broker_day"] = {str(m): metrics(first_event_per_broker_day(part), m) for m in HORIZONS_MIN}
    return out


def promotion_assessment(report: dict[str, Any]) -> dict[str, Any]:
    base = report["strategies"]["BASELINE_MTF"]["test"]["120"]
    filt = report["strategies"]["D1_SOFT_DIRECTIONAL"]["test"]["120"]
    reasons = []
    passed = True
    if not base.get("n") or not filt.get("n"):
        passed = False; reasons.append("INSUFFICIENT_TEST_SAMPLE")
    else:
        sample_ratio = filt["n"] / base["n"] if base["n"] else 0
        if sample_ratio < 0.35:
            passed = False; reasons.append("SAMPLE_COLLAPSE_GT_65PCT")
        if filt.get("mean_return") is None or base.get("mean_return") is None or filt["mean_return"] <= base["mean_return"]:
            passed = False; reasons.append("TEST_EXPECTANCY_NOT_IMPROVED")
        if filt.get("profit_factor") is None or base.get("profit_factor") is None or filt["profit_factor"] <= base["profit_factor"]:
            passed = False; reasons.append("TEST_PROFIT_FACTOR_NOT_IMPROVED")
        if filt.get("win_rate") is None or base.get("win_rate") is None or filt["win_rate"] < base["win_rate"]:
            passed = False; reasons.append("TEST_WIN_RATE_NOT_MAINTAINED")
    return {
        "hard_filter_candidate": bool(passed),
        "recommended_enforcement_mode": "HARD_FILTER_CANDIDATE" if passed else "WARNING_ONLY",
        "basis": "120-minute OOS test, fixed 0.10/0.30/0.70/0.90 zones",
        "reasons": reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Estudo D1 broker-day + H1/M15/M5 para GOLD intraday.")
    ap.add_argument("--input-dir", type=Path, default=Path("data"))
    ap.add_argument("--symbol", default="GOLD")
    ap.add_argument("--rules", type=Path, default=Path("config/market_intelligence/GOLD_d1_intraday_rules.json"))
    ap.add_argument("--output", type=Path, default=Path("data/research/GOLD_d1_mtf_filter_report.json"))
    args = ap.parse_args()

    symbol = args.symbol.upper()
    rules = load_json(args.rules)
    m5 = add_future_outcomes(add_d1_point_in_time(prepare(args.input_dir / f"{symbol}_M5.parquet", "M5", rules)))
    m15 = prepare(args.input_dir / f"{symbol}_M15.parquet", "M15", rules)
    h1 = prepare(args.input_dir / f"{symbol}_H1.parquet", "H1", rules)

    anchor = m5.loc[in_window(m5["available_at_brt"], rules)].copy()
    anchor = merge_parent(anchor, m15, "M15")
    anchor = merge_parent(anchor, h1, "H1")
    anchor["M5_direction"] = anchor["direction"]
    anchor["side"] = np.where(
        (anchor["H1_direction"] == "UP") & (anchor["M15_direction"] == "UP") & (anchor["M5_direction"] == "UP"),
        "BUY",
        np.where(
            (anchor["H1_direction"] == "DOWN") & (anchor["M15_direction"] == "DOWN") & (anchor["M5_direction"] == "DOWN"),
            "SELL",
            "NONE",
        ),
    )

    zones = [zone_name(float(p), str(d), rules) for p, d in zip(anchor["d1_position"], anchor["daily_direction"])]
    anchor["zone"] = [z[0] for z in zones]
    anchor["zone_qualified"] = [z[1] for z in zones]
    baseline_events = anchor[anchor["side"].isin(["BUY", "SELL"])].copy()
    split_a, split_b = split_edges(baseline_events)
    masks = strategy_masks(anchor)

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "symbol": symbol,
        "methodology": {
            "daily_boundary": "MT5 broker day",
            "broker_timezone": (rules.get("daily_session_clock", {}) or {}).get("timezone"),
            "operational_window_brt": rules.get("operational_window_brt"),
            "lookahead_safe_d1": True,
            "higher_tf_availability": "H1/M15 direction becomes eligible only after the parent candle closes",
            "mtf_baseline": "H1 == M15 == M5 direction",
            "split": "chronological 60/20/20 on baseline aligned events",
            "thresholds_frozen_before_test": [0.10, 0.30, 0.70, 0.90],
        },
        "coverage": {
            "m5_rows": int(len(m5)),
            "m15_rows": int(len(m15)),
            "h1_rows": int(len(h1)),
            "anchor_operational_rows": int(len(anchor)),
            "baseline_aligned_events": int(len(baseline_events)),
            "split_validation_start": split_a.isoformat() if split_a is not pd.Timestamp.min else None,
            "split_test_start": split_b.isoformat() if split_b is not pd.Timestamp.min else None,
        },
        "zone_counts": anchor.groupby(["zone", "daily_direction"], dropna=False).size().astype(int).to_dict(),
        "strategies": {},
    }
    report["zone_counts"] = {str(k): v for k, v in report["zone_counts"].items()}

    for name, mask in masks.items():
        report["strategies"][name] = summarize_strategy(anchor, mask, split_a, split_b)

    report["promotion_assessment"] = promotion_assessment(report)
    save_json(args.output, report)
    print(json.dumps({
        "status": "ok",
        "output": str(args.output),
        "baseline_events": report["coverage"]["baseline_aligned_events"],
        "promotion_assessment": report["promotion_assessment"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
