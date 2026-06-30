#!/usr/bin/env python3
"""
Market Chronos Law Manager

Governança segura das leis:
- Research e validation nunca publicam leis.
- Apenas o comando approve altera o registry operacional.
- Toda mutação gera backup e auditoria append-only.
- O runtime deve consumir apenas status=APPROVED e enabled=true.

Uso:
  python tools/market_chronos_law_manager.py list-candidates --symbol GOLD
  python tools/market_chronos_law_manager.py review --symbol GOLD --candidate-id CAND_...
  python tools/market_chronos_law_manager.py approve --symbol GOLD --candidate-id CAND_... --by Diego --reason "..."
  python tools/market_chronos_law_manager.py reject --symbol GOLD --candidate-id CAND_... --by Diego --reason "..."
  python tools/market_chronos_law_manager.py list-laws --symbol GOLD
  python tools/market_chronos_law_manager.py disable --symbol GOLD --law-id LAW_0001 --by Diego --reason "..."
  python tools/market_chronos_law_manager.py enable --symbol GOLD --law-id LAW_0001 --by Diego --reason "..."
  python tools/market_chronos_law_manager.py validate --symbol GOLD
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:
    jsonschema = None


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "schemas"


class GovernanceError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def paths(symbol: str) -> dict[str, Path]:
    base = ROOT / "data" / "market_chronos" / symbol
    return {
        "base": base,
        "candidates": base / "discovery" / "law_candidates.json",
        "validation": base / "validation" / "validation_report.json",
        "registry": base / "laws" / "market_laws_registry.json",
        "audit": base / "laws" / "approval_audit.jsonl",
        "backups": base / "laws" / "backups",
    }


def ensure_layout(symbol: str) -> dict[str, Path]:
    p = paths(symbol)
    for key in ("candidates", "validation", "registry", "audit"):
        p[key].parent.mkdir(parents=True, exist_ok=True)
    p["backups"].mkdir(parents=True, exist_ok=True)

    if not p["candidates"].exists():
        atomic_write_json(p["candidates"], {
            "candidate_schema_version": "1.0",
            "symbol": symbol,
            "generated_at_utc": None,
            "candidates": [],
        })
    if not p["validation"].exists():
        atomic_write_json(p["validation"], {
            "validation_schema_version": "1.0",
            "symbol": symbol,
            "generated_at_utc": None,
            "results": [],
        })
    if not p["registry"].exists():
        atomic_write_json(p["registry"], {
            "registry_schema_version": "1.0",
            "registry_version": 1,
            "symbol": symbol,
            "updated_at_utc": utc_now(),
            "laws": [],
        })
    p["audit"].touch(exist_ok=True)
    return p


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise GovernanceError(f"Arquivo não encontrado: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GovernanceError(f"JSON inválido em {path}: {exc}") from exc


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_audit(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def backup_registry(registry_path: Path, backups_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backups_dir / f"market_laws_registry_{stamp}.json"
    shutil.copy2(registry_path, destination)
    return destination


def payload_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def find_candidate(data: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    for candidate in data.get("candidates", []):
        if candidate.get("candidate_id") == candidate_id:
            return candidate
    raise GovernanceError(f"Candidato não encontrado: {candidate_id}")


def find_law(data: dict[str, Any], law_id: str) -> dict[str, Any]:
    for law in data.get("laws", []):
        if law.get("law_id") == law_id:
            return law
    raise GovernanceError(f"Lei não encontrada: {law_id}")


def next_law_id(registry: dict[str, Any]) -> str:
    highest = 0
    for law in registry.get("laws", []):
        raw = str(law.get("law_id", ""))
        if raw.startswith("LAW_"):
            try:
                highest = max(highest, int(raw.split("_", 1)[1]))
            except ValueError:
                continue
    return f"LAW_{highest + 1:04d}"


def approval_checks(candidate: dict[str, Any]) -> list[str]:
    validation = candidate.get("validation", {})
    failures: list[str] = []
    if candidate.get("status") not in {"VALIDATED", "PENDING_APPROVAL"}:
        failures.append("status deve ser VALIDATED ou PENDING_APPROVAL")
    if int(validation.get("sample_size", 0)) < 100:
        failures.append("sample_size deve ser >= 100")
    if validation.get("oos_pass") is not True:
        failures.append("oos_pass deve ser true")
    if validation.get("walk_forward_pass") is not True:
        failures.append("walk_forward_pass deve ser true")
    if validation.get("recent_window_pass") is not True:
        failures.append("recent_window_pass deve ser true")
    if validation.get("confidence_grade") not in {"A", "B"}:
        failures.append("confidence_grade deve ser A ou B")
    return failures


def validate_with_schema(instance: dict[str, Any], schema_name: str) -> None:
    if jsonschema is None:
        raise GovernanceError(
            "Pacote jsonschema não instalado. Execute: pip install jsonschema"
        )
    schema = read_json(SCHEMAS_DIR / schema_name)
    resolver = jsonschema.RefResolver(
        base_uri=(SCHEMAS_DIR.resolve().as_uri() + "/"),
        referrer=schema,
    )
    jsonschema.validate(instance=instance, schema=schema, resolver=resolver)


def command_list_candidates(args: argparse.Namespace) -> None:
    p = ensure_layout(args.symbol)
    data = read_json(p["candidates"])
    rows = data.get("candidates", [])
    if args.status:
        rows = [row for row in rows if row.get("status") == args.status]
    print(json.dumps(rows, indent=2, ensure_ascii=False))


def command_review(args: argparse.Namespace) -> None:
    p = ensure_layout(args.symbol)
    candidate = find_candidate(read_json(p["candidates"]), args.candidate_id)
    result = copy.deepcopy(candidate)
    result["approval_check_failures"] = approval_checks(candidate)
    result["eligible_for_approval"] = not result["approval_check_failures"]
    print(json.dumps(result, indent=2, ensure_ascii=False))


def command_approve(args: argparse.Namespace) -> None:
    p = ensure_layout(args.symbol)
    candidates = read_json(p["candidates"])
    registry = read_json(p["registry"])
    candidate = find_candidate(candidates, args.candidate_id)

    failures = approval_checks(candidate)
    if failures and not args.force:
        raise GovernanceError(
            "Candidato não elegível:\n- " + "\n- ".join(failures) +
            "\nUse --force apenas após revisão consciente."
        )

    for law in registry.get("laws", []):
        if law.get("source_candidate_id") == args.candidate_id:
            raise GovernanceError(
                f"Candidato já publicado como {law.get('law_id')}."
            )

    backup = backup_registry(p["registry"], p["backups"])
    now = utc_now()
    law_id = next_law_id(registry)

    law = {
        "law_id": law_id,
        "source_candidate_id": candidate["candidate_id"],
        "symbol": candidate.get("symbol", args.symbol),
        "name": candidate["name"],
        "description": candidate.get("description", ""),
        "status": "APPROVED",
        "enabled": True,
        "version": 1,
        "conditions": copy.deepcopy(candidate.get("conditions", {})),
        "effect": copy.deepcopy(candidate.get("effect", {
            "supporting_side": "NONE",
            "blocked_actions": [],
        })),
        "validation_snapshot": copy.deepcopy(candidate.get("validation", {})),
        "health": {
            "status": "UNKNOWN",
            "checked_at_utc": None,
            "notes": [],
        },
        "governance": {
            "approved_at_utc": now,
            "approved_by": args.by,
            "approval_reason": args.reason,
            "disabled_at_utc": None,
            "disabled_by": None,
            "disable_reason": None,
        },
    }

    registry.setdefault("laws", []).append(law)
    registry["registry_version"] = int(registry.get("registry_version", 0)) + 1
    registry["updated_at_utc"] = now

    candidate["status"] = "APPROVED"
    candidate["updated_at_utc"] = now
    candidate["review"] = {
        "reviewed_by": args.by,
        "reviewed_at_utc": now,
        "decision_reason": args.reason,
    }

    validate_with_schema(registry, "law_registry.schema.json")
    atomic_write_json(p["registry"], registry)
    atomic_write_json(p["candidates"], candidates)

    append_audit(p["audit"], {
        "timestamp_utc": now,
        "action": "APPROVE",
        "symbol": args.symbol,
        "candidate_id": args.candidate_id,
        "law_id": law_id,
        "actor": args.by,
        "reason": args.reason,
        "forced": bool(args.force),
        "registry_version": registry["registry_version"],
        "registry_hash": payload_hash(registry),
        "backup": str(backup.relative_to(ROOT)),
    })
    print(json.dumps({"status": "ok", "law_id": law_id, "backup": str(backup)}, indent=2))


def command_reject(args: argparse.Namespace) -> None:
    p = ensure_layout(args.symbol)
    candidates = read_json(p["candidates"])
    candidate = find_candidate(candidates, args.candidate_id)
    now = utc_now()
    candidate["status"] = "REJECTED"
    candidate["updated_at_utc"] = now
    candidate["review"] = {
        "reviewed_by": args.by,
        "reviewed_at_utc": now,
        "decision_reason": args.reason,
    }
    atomic_write_json(p["candidates"], candidates)
    append_audit(p["audit"], {
        "timestamp_utc": now,
        "action": "REJECT",
        "symbol": args.symbol,
        "candidate_id": args.candidate_id,
        "actor": args.by,
        "reason": args.reason,
    })
    print(json.dumps({"status": "ok", "candidate_id": args.candidate_id}, indent=2))


def command_list_laws(args: argparse.Namespace) -> None:
    p = ensure_layout(args.symbol)
    registry = read_json(p["registry"])
    rows = registry.get("laws", [])
    if args.enabled_only:
        rows = [row for row in rows if row.get("enabled") is True and row.get("status") == "APPROVED"]
    print(json.dumps(rows, indent=2, ensure_ascii=False))


def mutate_law(args: argparse.Namespace, enabled: bool) -> None:
    p = ensure_layout(args.symbol)
    registry = read_json(p["registry"])
    law = find_law(registry, args.law_id)
    backup = backup_registry(p["registry"], p["backups"])
    now = utc_now()

    law["enabled"] = enabled
    law["status"] = "APPROVED" if enabled else "DISABLED"
    law["version"] = int(law.get("version", 0)) + 1
    governance = law.setdefault("governance", {})
    if enabled:
        governance["disabled_at_utc"] = None
        governance["disabled_by"] = None
        governance["disable_reason"] = None
    else:
        governance["disabled_at_utc"] = now
        governance["disabled_by"] = args.by
        governance["disable_reason"] = args.reason

    registry["registry_version"] = int(registry.get("registry_version", 0)) + 1
    registry["updated_at_utc"] = now
    validate_with_schema(registry, "law_registry.schema.json")
    atomic_write_json(p["registry"], registry)
    append_audit(p["audit"], {
        "timestamp_utc": now,
        "action": "ENABLE" if enabled else "DISABLE",
        "symbol": args.symbol,
        "law_id": args.law_id,
        "actor": args.by,
        "reason": args.reason,
        "registry_version": registry["registry_version"],
        "registry_hash": payload_hash(registry),
        "backup": str(backup.relative_to(ROOT)),
    })
    print(json.dumps({"status": "ok", "law_id": args.law_id, "enabled": enabled}, indent=2))


def command_validate(args: argparse.Namespace) -> None:
    p = ensure_layout(args.symbol)
    candidates = read_json(p["candidates"])
    registry = read_json(p["registry"])
    for candidate in candidates.get("candidates", []):
        validate_with_schema(candidate, "law_candidate.schema.json")
    validate_with_schema(registry, "law_registry.schema.json")
    print(json.dumps({
        "status": "ok",
        "candidate_count": len(candidates.get("candidates", [])),
        "law_count": len(registry.get("laws", [])),
        "registry_version": registry.get("registry_version"),
    }, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Governança segura das leis do Market Chronos.")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--symbol", required=True)

    p = sub.add_parser("list-candidates", parents=[common])
    p.add_argument("--status")
    p.set_defaults(func=command_list_candidates)

    p = sub.add_parser("review", parents=[common])
    p.add_argument("--candidate-id", required=True)
    p.set_defaults(func=command_review)

    p = sub.add_parser("approve", parents=[common])
    p.add_argument("--candidate-id", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=command_approve)

    p = sub.add_parser("reject", parents=[common])
    p.add_argument("--candidate-id", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=command_reject)

    p = sub.add_parser("list-laws", parents=[common])
    p.add_argument("--enabled-only", action="store_true")
    p.set_defaults(func=command_list_laws)

    for name, enabled in (("disable", False), ("enable", True)):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("--law-id", required=True)
        p.add_argument("--by", required=True)
        p.add_argument("--reason", required=True)
        p.set_defaults(func=lambda args, state=enabled: mutate_law(args, state))

    p = sub.add_parser("validate", parents=[common])
    p.set_defaults(func=command_validate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except GovernanceError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERRO INESPERADO: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
