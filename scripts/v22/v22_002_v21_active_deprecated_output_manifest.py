#!/usr/bin/env python
"""V22.002 V21 active/deprecated output manifest.

This module is a read-only classifier for existing V21 output directories. It
scans paths, records classifications, and writes only V22.002 artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODULE_ID = "V22.002"
MODULE_NAME = "V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST"
STAGE = "V22.002_V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST"
OUT_REL = Path("outputs") / "v22" / STAGE
OUTPUT_ROOT_REL = Path("outputs") / "v21"

PASS_STATUS = "PASS_V22_002_V21_OUTPUT_MANIFEST_READY"
WARN_STATUS = "WARN_V22_002_V21_OUTPUT_MANIFEST_READY_WITH_MISSING_OUTPUT_ROOT"
FINAL_DECISION = "V21_OUTPUTS_CLASSIFIED_FOR_V22_CONSOLIDATION_RESEARCH_ONLY"

NEXT_RECOMMENDED_MODULES = [
    "V22.003_SYSTEM_MAP_AND_README_REFRESH",
    "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY",
    "V22.020_DRAM_DAILY_DECISION_PANEL_R2",
    "V22.030_ETF_OPTION_UNIVERSE_REGISTRY",
]

NO_ACTION_GATES = {
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "market_data_fetch_allowed": False,
    "moomoo_connection_allowed": False,
    "option_chain_fetch_allowed": False,
    "daily_chain_execution_allowed": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
    "delete_allowed": False,
    "move_allowed": False,
    "rename_allowed": False,
    "clean_allowed": False,
    "research_only": True,
}

KNOWN_REFERENCES: dict[str, tuple[str, str]] = {
    "V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1": (
        "ACTIVE_DAILY_CHAIN",
        "Canonical V21 daily research chain output frozen by V22.001.",
    ),
    "V21.259_DAILY_RESEARCH_ENTRYPOINT_REGISTRY_R1": (
        "ACTIVE_REPO_GOVERNANCE",
        "Entrypoint registry retained for V22 consolidation governance.",
    ),
    "V21.264_KNOWN_FAILURE_GROUPS_REPAIRED": (
        "ACTIVE_REPO_GOVERNANCE",
        "Known failure group repair evidence retained for V22 consolidation governance.",
    ),
    "V21.241_DAILY_CHAIN_WITH_RETENTION_GUARD": (
        "ACTIVE_RISK_GOVERNANCE",
        "Retention guard daily chain output retained for risk governance context.",
    ),
    "V21.240_RETENTION_GUARD": (
        "ACTIVE_RISK_GOVERNANCE",
        "Retention guard output retained for risk governance context.",
    ),
    "V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN": (
        "ACTIVE_RESEARCH_INPUT",
        "Prior daily research chain output retained as research input.",
    ),
    "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON": (
        "ACTIVE_FACTOR_VALIDITY_RESEARCH",
        "Factor weight comparison output retained for factor validity research.",
    ),
    "V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT": (
        "ACTIVE_FACTOR_VALIDITY_RESEARCH",
        "Technical subfactor audit retained for factor validity research.",
    ),
    "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1": (
        "ACTIVE_FACTOR_VALIDITY_RESEARCH",
        "Technical and forward panel output retained for factor validity research.",
    ),
    "V21.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER": (
        "ACTIVE_CACHE_GOVERNANCE",
        "Local cache architecture output retained for cache governance.",
    ),
    "V21.235_REPO_CLEAN_DELETE_AFTER_VERIFICATION": (
        "ACTIVE_REPO_GOVERNANCE",
        "Repo clean/delete verification output retained as governance evidence only.",
    ),
    "V21.233_MOOMOO_ONLY_ABCDE_RERUN": (
        "HISTORICAL_ARCHIVE_KEEP",
        "Historical ABCDE rerun retained as archive.",
    ),
    "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT": (
        "HISTORICAL_ARCHIVE_KEEP",
        "Historical broad-date ABCDE rerun retained as archive.",
    ),
    "V21.201_DRAM_MOOMOO_R4_PLAN": (
        "ACTIVE_DRAM_RESEARCH",
        "DRAM research output retained for active DRAM research.",
    ),
    "V21.232_DRAM": (
        "ACTIVE_DRAM_RESEARCH",
        "DRAM output retained for active DRAM research.",
    ),
}

FIELDNAMES = [
    "output_name",
    "output_path",
    "exists",
    "classification",
    "v22_role",
    "active_allowed",
    "read_allowed",
    "write_allowed",
    "delete_allowed",
    "mutation_allowed",
    "reason",
    "detected_by",
    "last_modified_utc",
    "file_count_shallow",
    "total_size_bytes_shallow",
]

DEPRECATED_OR_REVIEW_CLASSIFICATIONS = {
    "DEPRECATED_DO_NOT_USE",
    "UNKNOWN_REVIEW_REQUIRED",
    "MISSING_REFERENCE",
}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    observed = output_dir.resolve()
    if observed != expected:
        raise ValueError(f"V22.002 output directory must be {expected}, got {observed}")


def rel_output_path(output_name: str) -> str:
    return (OUTPUT_ROOT_REL / output_name).as_posix()


def v22_role_for_classification(classification: str) -> str:
    roles = {
        "ACTIVE_DAILY_CHAIN": "ACTIVE_CANONICAL_DAILY_RESEARCH_OUTPUT",
        "ACTIVE_RESEARCH_INPUT": "ACTIVE_RESEARCH_INPUT",
        "ACTIVE_RISK_GOVERNANCE": "ACTIVE_RISK_GOVERNANCE",
        "ACTIVE_CACHE_GOVERNANCE": "ACTIVE_CACHE_GOVERNANCE",
        "ACTIVE_REPO_GOVERNANCE": "ACTIVE_REPO_GOVERNANCE",
        "ACTIVE_FACTOR_VALIDITY_RESEARCH": "ACTIVE_FACTOR_VALIDITY_RESEARCH",
        "ACTIVE_DRAM_RESEARCH": "ACTIVE_DRAM_RESEARCH",
        "HISTORICAL_ARCHIVE_KEEP": "HISTORICAL_ARCHIVE_READ_ONLY",
        "DIAGNOSTIC_ONLY_KEEP": "DIAGNOSTIC_READ_ONLY",
        "DEPRECATED_DO_NOT_USE": "DEPRECATED_READ_ONLY_DO_NOT_USE",
        "UNKNOWN_REVIEW_REQUIRED": "REVIEW_REQUIRED_BEFORE_USE",
        "MISSING_REFERENCE": "MISSING_REFERENCE_REVIEW",
    }
    return roles[classification]


def classify_unknown(output_name: str) -> tuple[str, str]:
    upper_name = output_name.upper()
    if "DRAM" in upper_name:
        return "DIAGNOSTIC_ONLY_KEEP", "Name contains DRAM; kept as diagnostic unless listed as active DRAM research."
    if "ABCDE" in upper_name or "ABCD" in upper_name:
        return "HISTORICAL_ARCHIVE_KEEP", "Name contains ABCDE/ABCD; kept as historical archive unless listed as active."
    if any(token in upper_name for token in ["TEST", "REPAIR", "AUDIT", "TRIAGE", "FORENSIC", "DIAGNOSTIC"]):
        return "DIAGNOSTIC_ONLY_KEEP", "Name contains diagnostic/audit/repair token; kept for read-only diagnostics."
    if "CACHE" in upper_name:
        return "ACTIVE_CACHE_GOVERNANCE", "Name contains CACHE; retained for cache governance classification."
    if any(token in upper_name for token in ["DELETE", "CLEAN", "RETENTION", "REGISTRY"]):
        return "ACTIVE_REPO_GOVERNANCE", "Name contains repo governance token; retained for read-only governance classification."
    return "UNKNOWN_REVIEW_REQUIRED", "No known reference or deterministic name rule matched; review required before use."


def shallow_stats(path: Path) -> tuple[str, int, int]:
    if not path.exists():
        return "", 0, 0
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds").removesuffix("+00:00") + "Z"
    file_count = 0
    total_size = 0
    for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        if child.is_file():
            file_count += 1
            total_size += child.stat().st_size
    return modified, file_count, total_size


def manifest_row(repo_root: Path, output_name: str, classification: str, reason: str, detected_by: str) -> dict[str, Any]:
    rel_path = rel_output_path(output_name)
    path = repo_root / rel_path
    exists = path.exists()
    if not exists:
        classification = "MISSING_REFERENCE"
        reason = "Known reference is not present under outputs/v21."
    last_modified_utc, file_count_shallow, total_size_bytes_shallow = shallow_stats(path)
    active_allowed = classification.startswith("ACTIVE_")
    return {
        "output_name": output_name,
        "output_path": rel_path,
        "exists": exists,
        "classification": classification,
        "v22_role": v22_role_for_classification(classification),
        "active_allowed": active_allowed,
        "read_allowed": exists,
        "write_allowed": False,
        "delete_allowed": False,
        "mutation_allowed": False,
        "reason": reason,
        "detected_by": detected_by,
        "last_modified_utc": last_modified_utc,
        "file_count_shallow": file_count_shallow,
        "total_size_bytes_shallow": total_size_bytes_shallow,
    }


def classification_rows(repo_root: Path) -> list[dict[str, Any]]:
    output_root = repo_root / OUTPUT_ROOT_REL
    names: set[str] = set(KNOWN_REFERENCES)
    if output_root.exists():
        names.update(child.name for child in output_root.iterdir() if child.is_dir() and child.name.startswith("V21."))

    rows: list[dict[str, Any]] = []
    for name in sorted(names, key=str.lower):
        if name in KNOWN_REFERENCES:
            classification, reason = KNOWN_REFERENCES[name]
            detected_by = "KNOWN_REFERENCE"
        else:
            classification, reason = classify_unknown(name)
            detected_by = "OUTPUT_ROOT_SCAN"
        rows.append(manifest_row(repo_root, name, classification, reason, detected_by))
    return rows


def classification_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        classification = str(row["classification"])
        counts[classification] = counts.get(classification, 0) + 1
    return dict(sorted(counts.items()))


def summary_payload(repo_root: Path, output_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    output_root = repo_root / OUTPUT_ROOT_REL
    output_root_exists = output_root.exists()
    scanned_count = sum(1 for row in rows if row["exists"] is True and str(row["output_name"]).startswith("V21."))
    active_count = sum(1 for row in rows if row["active_allowed"] is True)
    deprecated_count = sum(1 for row in rows if row["classification"] in DEPRECATED_OR_REVIEW_CLASSIFICATIONS)
    missing_count = sum(1 for row in rows if row["classification"] == "MISSING_REFERENCE")
    known_present_count = sum(1 for row in rows if row["detected_by"] == "KNOWN_REFERENCE" and row["exists"] is True)
    final_status = PASS_STATUS if output_root_exists and rows else WARN_STATUS
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": FINAL_DECISION,
        "output_root_scanned": OUTPUT_ROOT_REL.as_posix(),
        "output_root_exists": output_root_exists,
        "known_reference_count": len(KNOWN_REFERENCES),
        "known_reference_present_count": known_present_count,
        "scanned_v21_output_count": scanned_count,
        "classified_output_count": len(rows),
        "active_output_count": active_count,
        "deprecated_or_review_required_count": deprecated_count,
        "missing_reference_count": missing_count,
        "classification_counts": classification_counts(rows),
        "protected_outputs_modified": False,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        "output_dir": str(output_dir),
        **NO_ACTION_GATES,
    }


def risk_gate_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "allowed_side_effects": ["create_outputs_v22_002_only"],
        "forbidden_side_effects": [
            "delete_v21_outputs",
            "move_v21_outputs",
            "rename_v21_outputs",
            "mutate_v21_outputs",
            "execute_daily_chain",
            "connect_moomoo",
            "fetch_market_data",
            "fetch_option_chain",
            "mutate_cache",
            "create_trade_order",
            "modify_broker_state",
        ],
        **{key: value for key, value in NO_ACTION_GATES.items() if key != "research_only"},
    }


def report_text(summary: dict[str, Any]) -> str:
    lines = [
        "V22.002 V21 Active Deprecated Output Manifest",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"output_root_scanned={summary['output_root_scanned']}",
        f"output_root_exists={summary['output_root_exists']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        "classification_counts="
        + ";".join(f"{name}:{count}" for name, count in summary["classification_counts"].items()),
        f"active_output_count={summary['active_output_count']}",
        f"deprecated_or_review_required_count={summary['deprecated_or_review_required_count']}",
        f"missing_reference_count={summary['missing_reference_count']}",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
        "market_data_fetch_allowed=False",
        "moomoo_connection_allowed=False",
        "option_chain_fetch_allowed=False",
        "daily_chain_execution_allowed=False",
        "historical_outputs_mutation_allowed=False",
        "cache_mutation_allowed=False",
        "delete_allowed=False",
        "move_allowed=False",
        "rename_allowed=False",
        "clean_allowed=False",
        "protected_outputs_modified=False",
        "next_recommended_modules=" + ";".join(summary["next_recommended_modules"]),
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = classification_rows(repo_root)
    active_rows = [row for row in rows if row["active_allowed"] is True]
    deprecated_rows = [row for row in rows if row["classification"] in DEPRECATED_OR_REVIEW_CLASSIFICATIONS]
    summary = summary_payload(repo_root, output_dir, rows)

    write_csv(output_dir / "v21_output_classification_manifest.csv", FIELDNAMES, rows)
    write_csv(output_dir / "v21_active_output_manifest.csv", FIELDNAMES, active_rows)
    write_csv(output_dir / "v21_deprecated_output_manifest.csv", FIELDNAMES, deprecated_rows)
    write_json(output_dir / "v21_output_manifest_summary.json", summary)
    write_json(output_dir / "v21_output_manifest_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.002_v21_active_deprecated_output_manifest_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v21_output_manifest_summary.json'}")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_allowed=False")
    print("delete_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
