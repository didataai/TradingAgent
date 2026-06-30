#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Governança do registry operacional do Market Chronos V10.1.

Fluxo seguro:
    research_staging -> review/diff -> publish explícito -> backup/audit

O formato real do registry V10.1 é preservado integralmente. O manager não
recria leis nem converte schemas; apenas valida identidade, compara registries
e publica atomicamente após aprovação explícita.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

DEFAULT_OPERATIONAL = "data/market_chronos/{symbol}/laws/market_laws_registry.json"
DEFAULT_BACKUPS = "data/market_chronos/{symbol}/laws/backups"
DEFAULT_AUDIT = "data/market_chronos/{symbol}/laws/registry_approval_audit.jsonl"
DEFAULT_REVIEW = "data/market_chronos/{symbol}/laws/review/registry_diff_latest.json"


class RegistryError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RegistryError(f"Arquivo não encontrado: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"JSON inválido em {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegistryError(f"Registry deve ser objeto JSON: {path}")
    return payload


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def sha256_payload(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_registry(payload: Mapping[str, Any], symbol: str, anchor_tf: str | None = None) -> list[str]:
    errors: list[str] = []
    if not str(payload.get("registry_schema_version", "")).strip():
        errors.append("registry_schema_version ausente")
    if str(payload.get("symbol", "")).upper() != symbol.upper():
        errors.append(f"symbol incompatível: {payload.get('symbol')} != {symbol}")
    if anchor_tf and str(payload.get("anchor_tf", "")).upper() != anchor_tf.upper():
        errors.append(f"anchor_tf incompatível: {payload.get('anchor_tf')} != {anchor_tf}")
    laws = payload.get("laws")
    if not isinstance(laws, list):
        errors.append("laws deve ser uma lista")
        return errors

    seen: set[str] = set()
    for idx, law in enumerate(laws):
        prefix = f"laws[{idx}]"
        if not isinstance(law, dict):
            errors.append(f"{prefix} não é objeto")
            continue
        law_id = str(law.get("law_id", "")).strip()
        if not law_id:
            errors.append(f"{prefix}.law_id ausente")
        elif law_id in seen:
            errors.append(f"law_id duplicado: {law_id}")
        seen.add(law_id)
        for required in ("name", "symbol", "anchor_tf", "validation_status", "tier", "side", "conditions", "effect", "metrics"):
            if required not in law:
                errors.append(f"{law_id or prefix}.{required} ausente")
        if str(law.get("symbol", symbol)).upper() != symbol.upper():
            errors.append(f"{law_id}.symbol incompatível")
        if anchor_tf and str(law.get("anchor_tf", anchor_tf)).upper() != anchor_tf.upper():
            errors.append(f"{law_id}.anchor_tf incompatível")
        if not isinstance(law.get("conditions", {}), dict):
            errors.append(f"{law_id}.conditions deve ser objeto")
        if not isinstance(law.get("effect", {}), dict):
            errors.append(f"{law_id}.effect deve ser objeto")
        if not isinstance(law.get("metrics", {}), dict):
            errors.append(f"{law_id}.metrics deve ser objeto")
        if not isinstance(law.get("segment_modulators", []), list):
            errors.append(f"{law_id}.segment_modulators deve ser lista")
    return errors


def index_laws(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(law.get("law_id")): law
        for law in payload.get("laws", [])
        if isinstance(law, dict) and law.get("law_id")
    }


def changed_fields(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    fields = sorted(set(old) | set(new))
    return [field for field in fields if old.get(field) != new.get(field)]


def build_diff(current: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    old = index_laws(current)
    new = index_laws(candidate)
    added_ids = sorted(set(new) - set(old))
    removed_ids = sorted(set(old) - set(new))
    common_ids = sorted(set(old) & set(new))

    changed = []
    unchanged = []
    for law_id in common_ids:
        fields = changed_fields(old[law_id], new[law_id])
        if fields:
            changed.append({
                "law_id": law_id,
                "changed_fields": fields,
                "old_tier": old[law_id].get("tier"),
                "new_tier": new[law_id].get("tier"),
                "old_validation_status": old[law_id].get("validation_status"),
                "new_validation_status": new[law_id].get("validation_status"),
                "old_sample_size": old[law_id].get("metrics", {}).get("sample_size"),
                "new_sample_size": new[law_id].get("metrics", {}).get("sample_size"),
                "old_oos_edge": old[law_id].get("metrics", {}).get("oos_edge"),
                "new_oos_edge": new[law_id].get("metrics", {}).get("oos_edge"),
            })
        else:
            unchanged.append(law_id)

    return {
        "schema_version": "1.0",
        "generated_at_utc": utc_now(),
        "current_registry_hash": sha256_payload(current),
        "candidate_registry_hash": sha256_payload(candidate),
        "current_metadata": {
            "schema": current.get("registry_schema_version"),
            "engine": current.get("engine_version"),
            "generated_at_utc": current.get("generated_at_utc"),
            "law_count": len(old),
        },
        "candidate_metadata": {
            "schema": candidate.get("registry_schema_version"),
            "engine": candidate.get("engine_version"),
            "generated_at_utc": candidate.get("generated_at_utc"),
            "law_count": len(new),
        },
        "summary": {
            "added": len(added_ids),
            "removed": len(removed_ids),
            "changed": len(changed),
            "unchanged": len(unchanged),
        },
        "added_laws": [new[law_id] for law_id in added_ids],
        "removed_laws": [old[law_id] for law_id in removed_ids],
        "changed_laws": changed,
        "unchanged_law_ids": unchanged,
    }


def append_audit(path: Path, event: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(event), ensure_ascii=False) + "\n")


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    root = Path.cwd()
    symbol = args.symbol.upper()
    operational = root / args.operational.format(symbol=symbol, anchor_tf=args.anchor_tf)
    backups = root / args.backups.format(symbol=symbol, anchor_tf=args.anchor_tf)
    audit = root / args.audit.format(symbol=symbol, anchor_tf=args.anchor_tf)
    review_output = root / args.review_output.format(symbol=symbol, anchor_tf=args.anchor_tf)
    return operational, backups, audit, review_output


def command_validate(args: argparse.Namespace) -> int:
    payload = read_json(Path(args.registry))
    errors = validate_registry(payload, args.symbol, args.anchor_tf)
    result = {
        "status": "ok" if not errors else "invalid",
        "registry": args.registry,
        "hash": sha256_payload(payload),
        "law_count": len(payload.get("laws", [])),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def command_review(args: argparse.Namespace) -> int:
    operational, _, _, review_output = resolve_paths(args)
    current = read_json(operational)
    candidate_path = Path(args.candidate)
    candidate = read_json(candidate_path)

    errors = validate_registry(candidate, args.symbol, args.anchor_tf)
    if errors:
        raise RegistryError("Registry candidato inválido:\n- " + "\n- ".join(errors))
    current_errors = validate_registry(current, args.symbol, args.anchor_tf)
    if current_errors:
        raise RegistryError("Registry operacional inválido:\n- " + "\n- ".join(current_errors))

    diff = build_diff(current, candidate)
    diff["operational_registry"] = str(operational)
    diff["candidate_registry"] = str(candidate_path)
    atomic_write_json(review_output, diff)
    print(json.dumps({
        "status": "ok",
        "review_output": str(review_output),
        **diff["summary"],
        "current_hash": diff["current_registry_hash"],
        "candidate_hash": diff["candidate_registry_hash"],
    }, ensure_ascii=False, indent=2))
    return 0


def command_publish(args: argparse.Namespace) -> int:
    operational, backups, audit, review_output = resolve_paths(args)
    current = read_json(operational)
    candidate_path = Path(args.candidate)
    candidate = read_json(candidate_path)

    errors = validate_registry(candidate, args.symbol, args.anchor_tf)
    if errors:
        raise RegistryError("Registry candidato inválido:\n- " + "\n- ".join(errors))
    current_errors = validate_registry(current, args.symbol, args.anchor_tf)
    if current_errors:
        raise RegistryError("Registry operacional inválido:\n- " + "\n- ".join(current_errors))

    diff = build_diff(current, candidate)
    expected = args.expected_candidate_hash
    actual_hash = diff["candidate_registry_hash"]
    if expected and expected != actual_hash:
        raise RegistryError(f"Hash candidato mudou: esperado {expected}, atual {actual_hash}")
    if diff["current_registry_hash"] == actual_hash:
        raise RegistryError("O registry candidato é idêntico ao operacional; nada a publicar.")
    if diff["summary"]["removed"] and not args.allow_removals:
        raise RegistryError(
            f"Candidato remove {diff['summary']['removed']} lei(s). "
            "Use --allow-removals apenas após revisão explícita."
        )

    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f"market_laws_registry_{utc_stamp()}.json"
    shutil.copy2(operational, backup)

    review_output.parent.mkdir(parents=True, exist_ok=True)
    diff["operational_registry"] = str(operational)
    diff["candidate_registry"] = str(candidate_path)
    diff["approved_by"] = args.approved_by
    diff["approval_reason"] = args.reason
    atomic_write_json(review_output, diff)

    atomic_write_json(operational, candidate)
    published = read_json(operational)
    published_hash = sha256_payload(published)
    if published_hash != actual_hash:
        shutil.copy2(backup, operational)
        raise RegistryError("Falha na verificação pós-publicação; backup restaurado.")

    append_audit(audit, {
        "timestamp_utc": utc_now(),
        "action": "PUBLISH_REGISTRY",
        "symbol": args.symbol.upper(),
        "anchor_tf": args.anchor_tf.upper(),
        "approved_by": args.approved_by,
        "reason": args.reason,
        "candidate": str(candidate_path),
        "operational": str(operational),
        "backup": str(backup),
        "previous_hash": diff["current_registry_hash"],
        "published_hash": published_hash,
        "summary": diff["summary"],
        "allow_removals": bool(args.allow_removals),
    })

    print(json.dumps({
        "status": "published",
        "operational_registry": str(operational),
        "backup": str(backup),
        "audit": str(audit),
        "published_hash": published_hash,
        **diff["summary"],
    }, ensure_ascii=False, indent=2))
    return 0


def command_rollback(args: argparse.Namespace) -> int:
    operational, backups, audit, _ = resolve_paths(args)
    backup = Path(args.backup)
    candidate = read_json(backup)
    errors = validate_registry(candidate, args.symbol, args.anchor_tf)
    if errors:
        raise RegistryError("Backup inválido:\n- " + "\n- ".join(errors))

    current = read_json(operational)
    emergency_backup = backups / f"market_laws_registry_before_rollback_{utc_stamp()}.json"
    backups.mkdir(parents=True, exist_ok=True)
    shutil.copy2(operational, emergency_backup)
    atomic_write_json(operational, candidate)

    append_audit(audit, {
        "timestamp_utc": utc_now(),
        "action": "ROLLBACK_REGISTRY",
        "symbol": args.symbol.upper(),
        "anchor_tf": args.anchor_tf.upper(),
        "approved_by": args.approved_by,
        "reason": args.reason,
        "source_backup": str(backup),
        "emergency_backup": str(emergency_backup),
        "previous_hash": sha256_payload(current),
        "restored_hash": sha256_payload(candidate),
    })
    print(json.dumps({
        "status": "rolled_back",
        "operational_registry": str(operational),
        "source_backup": str(backup),
        "emergency_backup": str(emergency_backup),
    }, ensure_ascii=False, indent=2))
    return 0


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.add_argument("--operational", default=DEFAULT_OPERATIONAL)
    p.add_argument("--backups", default=DEFAULT_BACKUPS)
    p.add_argument("--audit", default=DEFAULT_AUDIT)
    p.add_argument("--review-output", default=DEFAULT_REVIEW)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market Chronos Registry Governance")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate")
    p.add_argument("--registry", required=True)
    p.add_argument("--symbol", default="GOLD")
    p.add_argument("--anchor-tf", default="M5")
    p.set_defaults(func=command_validate)

    p = sub.add_parser("review")
    add_common(p)
    p.add_argument("--candidate", required=True)
    p.set_defaults(func=command_review)

    p = sub.add_parser("publish")
    add_common(p)
    p.add_argument("--candidate", required=True)
    p.add_argument("--approved-by", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--expected-candidate-hash")
    p.add_argument("--allow-removals", action="store_true")
    p.set_defaults(func=command_publish)

    p = sub.add_parser("rollback")
    add_common(p)
    p.add_argument("--backup", required=True)
    p.add_argument("--approved-by", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=command_rollback)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return int(args.func(args))
    except RegistryError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERRO INESPERADO: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
