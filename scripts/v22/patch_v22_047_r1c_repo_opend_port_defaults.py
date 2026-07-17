#!/usr/bin/env python
"""Audit and safely replace legacy Moomoo OpenD port literals in repo source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {".py", ".ps1", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg"}
MOOMOO_MARKERS = (
    "OpenQuoteContext",
    "OpenSecTradeContext",
    "OpenUSTradeContext",
    "OpenHKTradeContext",
    "moomoo",
    "futu",
    "opend",
    "OpenD",
)
EXCLUDED_PARTS = {".git", ".venv", "outputs", "backups", ".tmp", "__pycache__"}
MIGRATION_TOOL_FILENAMES = {
    "patch_v22_047_r1c_repo_opend_port_defaults.py",
    "run_v22_047_r1c_patch_repo_opend_port_defaults.ps1",
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_profile_port(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    port = int(payload["port"])
    if not 1 <= port <= 65535:
        raise ValueError("profile port out of range")
    return port


def eligible(path: Path, repo_root: Path) -> bool:
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    if path.name.startswith("test_") or path.name in MIGRATION_TOOL_FILENAMES:
        return False
    return relative.parts and relative.parts[0] in {"scripts", "config"}


def scan(repo_root: Path, old_port: int, new_port: int) -> list[dict[str, Any]]:
    pattern = re.compile(rf"(?<!\d){re.escape(str(old_port))}(?!\d)")
    rows: list[dict[str, Any]] = []
    for base_name in ("scripts", "config"):
        base = repo_root / base_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or not eligible(path, repo_root):
                continue
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                try:
                    text = path.read_text(encoding="utf-8-sig")
                except Exception:
                    continue
            if not any(marker in text for marker in MOOMOO_MARKERS):
                continue
            count = len(pattern.findall(text))
            if count:
                rows.append(
                    {
                        "path": path.relative_to(repo_root).as_posix(),
                        "replacement_count": count,
                        "old_port": old_port,
                        "new_port": new_port,
                    }
                )
    return sorted(rows, key=lambda row: row["path"].lower())


def apply_patch(
    repo_root: Path,
    rows: list[dict[str, Any]],
    old_port: int,
    new_port: int,
    backup_root: Path,
) -> list[dict[str, Any]]:
    pattern = re.compile(rf"(?<!\d){re.escape(str(old_port))}(?!\d)")
    applied: list[dict[str, Any]] = []
    for row in rows:
        relative = Path(row["path"])
        source = repo_root / relative
        raw_before = source.read_bytes()
        try:
            text_before = raw_before.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text_before = raw_before.decode("utf-8-sig")
            encoding = "utf-8-sig"
        text_after, count = pattern.subn(str(new_port), text_before)
        if count <= 0:
            continue
        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup)
        source.write_text(text_after, encoding=encoding, newline="\n")
        raw_after = source.read_bytes()
        applied.append(
            {
                **row,
                "replacement_count": count,
                "backup_path": str(backup),
                "sha256_before": sha256_bytes(raw_before),
                "sha256_after": sha256_bytes(raw_after),
            }
        )
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--old-port", type=int, default=11111)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    profile_path = Path(args.profile).resolve()
    new_port = load_profile_port(profile_path)
    rows = scan(repo_root, args.old_port, new_port)
    backup_root = repo_root / "backups" / f"v22_047_r1c_opend_port_{utc_stamp()}"
    applied: list[dict[str, Any]] = []
    if args.apply and rows:
        applied = apply_patch(repo_root, rows, args.old_port, new_port, backup_root)

    payload = {
        "schema_version": 1,
        "repo_root": str(repo_root),
        "profile_path": str(profile_path),
        "old_port": args.old_port,
        "new_port": new_port,
        "apply_requested": bool(args.apply),
        "candidate_file_count": len(rows),
        "candidate_replacement_count": sum(int(x["replacement_count"]) for x in rows),
        "applied_file_count": len(applied),
        "applied_replacement_count": sum(int(x["replacement_count"]) for x in applied),
        "backup_root": str(backup_root) if applied else "",
        "candidates": rows,
        "applied": applied,
        "final_status": (
            "PASS_V22_047_R1C_OPEND_PORT_PATCH_APPLIED"
            if args.apply
            else "PASS_V22_047_R1C_OPEND_PORT_AUDIT_COMPLETE"
        ),
    }
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"final_status={payload['final_status']}")
    print(f"old_port={args.old_port}")
    print(f"new_port={new_port}")
    print(f"candidate_file_count={payload['candidate_file_count']}")
    print(f"candidate_replacement_count={payload['candidate_replacement_count']}")
    print(f"applied_file_count={payload['applied_file_count']}")
    print(f"applied_replacement_count={payload['applied_replacement_count']}")
    print(f"report_path={report}")
    if applied:
        print(f"backup_root={backup_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
