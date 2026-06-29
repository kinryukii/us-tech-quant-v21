#!/usr/bin/env python
"""Validate V21.130 D strict-gate evidence ledger outputs."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION"
OUT = ROOT / "outputs/v21/V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION"
V129 = ROOT / "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"

MAIN_SCRIPT = ROOT / "scripts/v21/v21_130_d_strict_gate_evidence_ledger_and_block_reason_decomposition.py"
SUMMARY = OUT / "V21.130_summary.json"
READABLE = OUT / "V21.130_readable_report.txt"
COMPACT = OUT / "V21.130_compact_report.txt"
LEDGER = OUT / "V21.130_d_gate_evidence_ledger.csv"
DECOMP = OUT / "V21.130_d_block_reason_decomposition.csv"
PERSISTENCE = OUT / "V21.130_d_gate_persistence_summary.csv"
REQUIRED_EVIDENCE = OUT / "V21.130_d_required_evidence_for_review.csv"
REGIME_HISTORY = OUT / "V21.130_d_regime_block_history.csv"
DATA_QUALITY = OUT / "V21.130_d_data_quality_block_detail.csv"
V129_GATES = V129 / "V21.129_d_strict_gate_results.csv"

EXPECTED_GATES = {
    "DATA_FRESHNESS",
    "DATA_QUALITY_WARNING",
    "MATURITY",
    "VS_A1_PERFORMANCE",
    "VS_QQQ_PERFORMANCE",
    "CONCENTRATION_RISK",
    "LEFT_TAIL_DRAWDOWN_RISK",
    "REPEATED_LOSER_RISK",
    "REGIME_COMPATIBILITY",
}

EXPECTED_PROTECTED_SHA256 = {
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_summary.json": "9769d42521e1aace56930c2e4d553de4472c77d176d64143cf1751211233a71c",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_readable_report.txt": "bd6e99582cf23f201aaf9d4b340a2cb7139c9d8bd6dd2d6dbac0cc929dba2af3",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_compact_report.txt": "8763446cf2d70e3712ec6a247819e334db0a9b63740151b40b91169be841835a",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv": "014bc942860b969185090998730178177a740b52b1985d8c2134e8299b3c3f01",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv": "60197c9c964b2666258a2d5154ff2b97d9ca667aed964a1585653afe570d59a9",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_summary.json": "ebe5b19cdd98e6865e5d501f9307119628fb81ce28c0cfcc831849dea7fd74ff",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_strict_gate_results.csv": "14c96de363f7c9999a228e7b612724490461822ea4ce255bda03037e53eb74c1",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_tracking_top20.csv": "b0c4e1b1b3176927d696f599fcf9f24581682836919b3b4844579c40be585c44",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_tracking_top50.csv": "6e4d692fdd50db3722282258c4405378aad21ac7656a104793a41f05bdc8ad1a",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def validate_required_files() -> None:
    for path in [
        MAIN_SCRIPT,
        OUT,
        SUMMARY,
        READABLE,
        COMPACT,
        LEDGER,
        DECOMP,
        PERSISTENCE,
        REQUIRED_EVIDENCE,
        REGIME_HISTORY,
        DATA_QUALITY,
    ]:
        require(path.exists(), f"missing required path: {path}")


def validate_ledger(summary: dict[str, Any]) -> None:
    ledger = read_csv(LEDGER)
    require(ledger, "evidence ledger is empty")
    ledger_gates = {row["gate_name"] for row in ledger}
    v129_gates = {row["gate"] for row in read_csv(V129_GATES)}
    require(EXPECTED_GATES.issubset(ledger_gates), "not every expected gate appears in ledger")
    require(v129_gates.issubset(ledger_gates), "not every V21.129 gate appears in ledger")
    statuses = {row["status"] for row in ledger}
    require(statuses.issubset({"PASS", "BLOCK", "UNKNOWN"}), f"invalid ledger statuses: {statuses}")
    for row in ledger:
        if row["status"] == "BLOCK":
            require(row["blocker_reason"].strip(), f"BLOCK gate missing blocker_reason: {row}")
    require(summary.get("primary_D_blocker"), "primary blocker was not computed")
    require(summary.get("primary_D_blocker") == "DATA_QUALITY_WARNING", "unexpected primary blocker")

    decomp = read_csv(DECOMP)
    require(decomp, "block reason decomposition is empty")
    active_categories = {row["blocker_category"] for row in decomp if row["active_blocker"].lower() == "true"}
    for category in ["DATA_BLOCKER", "MATURITY_BLOCKER", "PERFORMANCE_BLOCKER", "CONCENTRATION_BLOCKER", "LEFT_TAIL_BLOCKER", "REPEATED_LOSER_BLOCKER", "REGIME_BLOCKER"]:
        require(category in active_categories, f"missing active blocker category: {category}")

    required_evidence = read_csv(REQUIRED_EVIDENCE)
    require(required_evidence, "required evidence checklist is empty")
    require(any(row["met"].lower() == "false" for row in required_evidence), "required evidence should contain unmet items")
    require(read_csv(REGIME_HISTORY), "regime block history is empty")
    require(read_csv(DATA_QUALITY), "data quality block detail is empty")


def validate_controls(summary: dict[str, Any]) -> None:
    require(summary.get("stage") == STAGE, "summary stage mismatch")
    require(as_bool(summary.get("D_adoption_allowed")) is False, "D_adoption_allowed must be false")
    require(as_bool(summary.get("D_continued_tracking")) is True, "D_continued_tracking must be true")
    require(as_bool(summary.get("official_adoption_allowed")) is False, "official_adoption_allowed must be false")
    require(as_bool(summary.get("broker_action_allowed")) is False, "broker_action_allowed must be false")
    require(as_bool(summary.get("protected_outputs_modified")) is False, "protected_outputs_modified must be false")
    require(as_bool(summary.get("research_only")) is True, "research_only must be true")
    require(as_bool(summary.get("v21_129_baseline_preserved")) is True, "V21.129 baseline must be preserved")
    require(summary.get("role_review_required") is False, "role_review_required must remain false")


def validate_protected_hashes() -> None:
    for rel_path, expected_hash in EXPECTED_PROTECTED_SHA256.items():
        path = ROOT / rel_path
        require(path.is_file(), f"missing protected baseline file: {rel_path}")
        require(sha256(path) == expected_hash, f"protected baseline changed: {rel_path}")


def main() -> None:
    validate_required_files()
    summary = load_json(SUMMARY)
    validate_controls(summary)
    validate_ledger(summary)
    validate_protected_hashes()
    print("V21.130 validation PASS")
    print(f"summary_path={SUMMARY.relative_to(ROOT).as_posix()}")
    print(f"primary_D_blocker={summary.get('primary_D_blocker')}")
    print(f"required_next_evidence={summary.get('required_next_evidence')}")


if __name__ == "__main__":
    main()
