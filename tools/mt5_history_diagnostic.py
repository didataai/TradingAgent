#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MT5 History Diagnostic
======================

Diagnostica por que o historico do MetaTrader 5 pode estar retornando zero deals.

Checa:
- login na conta;
- dados da conta logada;
- intervalo UTC consultado;
- quantidade bruta de deals sem filtro de simbolo;
- quantidade de deals por simbolo;
- ultimas deals encontradas;
- posicoes abertas atuais;
- ordens historicas.

Uso:
    python tools/mt5_history_diagnostic.py ^
      --from-date 2026-07-01 ^
      --to-date 2026-07-01 ^
      --mt5-config config/personal_mt5.local.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

BRT_TZ = "America/Sao_Paulo"


def _load_json(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {p}")
    with p.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _nested_get(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _parse_dt(value: str, end_of_day: bool = False) -> datetime:
    if "T" in value or " " in value:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(value)
        if end_of_day:
            dt = dt + timedelta(days=1)
    if dt.tzinfo is None:
        if ZoneInfo is not None:
            dt = dt.replace(tzinfo=ZoneInfo(BRT_TZ))
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnostica history_deals_get do MT5.")
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True)
    parser.add_argument("--mt5-config", default=None)
    parser.add_argument("--mt5-path", default=None)
    parser.add_argument("--mt5-account", type=int, default=None)
    parser.add_argument("--mt5-password", default=None)
    parser.add_argument("--mt5-password-env", default=None)
    parser.add_argument("--mt5-server", default=None)
    parser.add_argument("--symbol", default=None, help="Opcional: filtrar simbolo no diagnostico")
    return parser.parse_args()


def _resolve_credentials(args: argparse.Namespace) -> Dict[str, Any]:
    config = _load_json(args.mt5_config)
    password_env = args.mt5_password_env or _nested_get(config, "mt5", "password_env")
    password = args.mt5_password or (os.environ.get(str(password_env)) if password_env else None)
    if not password:
        password = _nested_get(config, "mt5", "password")
    return {
        "path": args.mt5_path or _nested_get(config, "mt5", "path"),
        "account": args.mt5_account or _nested_get(config, "mt5", "account"),
        "password": password,
        "server": args.mt5_server or _nested_get(config, "mt5", "server"),
        "password_env": password_env,
    }


def _connect(creds: Dict[str, Any]):
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:
        raise RuntimeError("Instale a lib: pip install MetaTrader5") from exc

    init_kwargs: Dict[str, Any] = {}
    if creds.get("path"):
        init_kwargs["path"] = creds["path"]

    print(f"[INFO] MT5 path: {creds.get('path')}")
    if not mt5.initialize(**init_kwargs):
        print(f"[ERRO] initialize: {mt5.last_error()}")
        return None

    if creds.get("account") and creds.get("password") and creds.get("server"):
        ok = mt5.login(int(creds["account"]), password=str(creds["password"]), server=str(creds["server"]))
        print(f"[INFO] login solicitado: account={creds.get('account')} server={creds.get('server')} ok={ok}")
        if not ok:
            print(f"[ERRO] login: {mt5.last_error()}")
            mt5.shutdown()
            return None
    else:
        print("[WARN] Credenciais incompletas. Usando sessao atual do terminal, se existir.")

    info = mt5.account_info()
    if info:
        d = info._asdict()
        print(f"[INFO] Conta logada: login={d.get('login')} server={d.get('server')} name={d.get('name')} balance={d.get('balance')}")
    else:
        print(f"[WARN] account_info vazio: {mt5.last_error()}")
    return mt5


def _to_df(items: Any, time_col: str = "time") -> pd.DataFrame:
    if items is None:
        return pd.DataFrame()
    rows = [x._asdict() for x in items]
    df = pd.DataFrame(rows)
    if not df.empty and time_col in df.columns:
        df["time_utc"] = pd.to_datetime(df[time_col], unit="s", utc=True, errors="coerce")
    return df


def main() -> int:
    args = _args()
    creds = _resolve_credentials(args)
    start_utc = _parse_dt(args.from_date, end_of_day=False)
    end_utc = _parse_dt(args.to_date, end_of_day=True)

    print(f"[INFO] Intervalo BRT informado: {args.from_date} -> {args.to_date}")
    print(f"[INFO] Intervalo UTC consultado: {start_utc.isoformat()} -> {end_utc.isoformat()}")
    print(f"[INFO] password_env usado: {creds.get('password_env')}")
    print(f"[INFO] senha presente: {bool(creds.get('password'))}")

    mt5 = _connect(creds)
    if mt5 is None:
        return 2

    try:
        deals = mt5.history_deals_get(start_utc, end_utc)
        if deals is None:
            print(f"[ERRO] history_deals_get None: {mt5.last_error()}")
            deals_df = pd.DataFrame()
        else:
            deals_df = _to_df(deals)

        orders = mt5.history_orders_get(start_utc, end_utc)
        if orders is None:
            print(f"[WARN] history_orders_get None: {mt5.last_error()}")
            orders_df = pd.DataFrame()
        else:
            orders_df = _to_df(orders)

        positions = mt5.positions_get()
        positions_df = _to_df(positions) if positions is not None else pd.DataFrame()
    finally:
        mt5.shutdown()

    print(f"[INFO] Deals brutas no periodo: {len(deals_df)}")
    if not deals_df.empty:
        if "symbol" in deals_df.columns:
            print("[INFO] Deals por simbolo:")
            print(deals_df["symbol"].fillna("").value_counts().head(30).to_string())
        if args.symbol and "symbol" in deals_df.columns:
            sym_df = deals_df[deals_df["symbol"].astype(str).str.upper() == args.symbol.upper()]
            print(f"[INFO] Deals para symbol exato {args.symbol}: {len(sym_df)}")
        cols = [c for c in ["time_utc", "ticket", "order", "position_id", "symbol", "type", "entry", "volume", "price", "profit", "comment"] if c in deals_df.columns]
        print("[INFO] Ultimas deals:")
        print(deals_df[cols].tail(20).to_string(index=False))

    print(f"[INFO] Orders historicas no periodo: {len(orders_df)}")
    if not orders_df.empty:
        if "symbol" in orders_df.columns:
            print("[INFO] Orders por simbolo:")
            print(orders_df["symbol"].fillna("").value_counts().head(30).to_string())
        cols = [c for c in ["time_utc", "ticket", "position_id", "symbol", "type", "state", "volume_initial", "volume_current", "price_open", "comment"] if c in orders_df.columns]
        print("[INFO] Ultimas orders:")
        print(orders_df[cols].tail(20).to_string(index=False))

    print(f"[INFO] Posicoes abertas agora: {len(positions_df)}")
    if not positions_df.empty:
        cols = [c for c in ["ticket", "time", "symbol", "type", "volume", "price_open", "price_current", "profit", "comment"] if c in positions_df.columns]
        print(positions_df[cols].to_string(index=False))

    if deals_df.empty and orders_df.empty:
        print("[DIAGNOSTICO] O MT5 retornou zero deals e zero orders para o periodo. Possiveis causas:")
        print("  1. A conta logada nao e a conta que operou nesse dia.")
        print("  2. O historico desse periodo nao esta carregado no terminal.")
        print("  3. A data precisa ser ampliada, ex.: --from-date 2026-06-30 --to-date 2026-07-02.")
        print("  4. O terminal/path esta abrindo outra instalacao/servidor.")
    elif not deals_df.empty and args.symbol:
        print("[DIAGNOSTICO] Se deals brutas existem mas o auditor retorna zero, provavelmente o nome do simbolo nao e exatamente o usado no comando.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
