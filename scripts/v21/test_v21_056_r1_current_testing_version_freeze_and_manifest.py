#!/usr/bin/env python
"""Contract tests for the V21.056-R1 current-testing version freeze."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_056_r1_current_testing_version_freeze_and_manifest.py"
WRAPPER = ROOT / "scripts/v21/run_v21_056_r1_current_testing_version_freeze_and_manifest.ps1"
spec = importlib.util.spec_from_file_location("v21_056_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


ALLOWED_STATUSES = {
    module.PASS_STATUS, module.PARTIAL_STATUS, module.BLOCKED_STATUS, module.FAIL_STATUS,
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path, complete: bool = True) -> tuple[Path, list[Path]]:
    ledger = root / "outputs/v21/shadow/V21_CURRENT_DAILY_OBSERVATION_LEDGER.csv"
    base = {
        "observation_id": "OBS-1", "as_of_date": "2026-06-18", "ticker": "MSFT",
        "forward_window": "10D", "maturity_status": "PENDING",
        "realized_forward_return": "", "research_only": "TRUE",
    }
    if complete:
        base.update({
            "rank": "1", "scheduled_maturity_date": "2026-07-02",
            "version_id": "V21_CURRENT", "variant_id": "A0",
        })
    second = {**base, "observation_id": "OBS-2", "ticker": "NVDA"}
    if complete:
        second["rank"] = "2"
    write_csv(ledger, [base, second])
    protected = [
        root / "outputs/v21/official/V21_OFFICIAL_RANKING.csv",
        root / "outputs/v21/official/V21_OFFICIAL_WEIGHTS.csv",
        root / "outputs/v21/real_book/V21_REAL_BOOK_LEDGER.csv",
        root / "outputs/v21/broker/V21_BROKER_ORDERS.csv",
    ]
    for index, path in enumerate(protected):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"id,value\n{index},unchanged\n", encoding="utf-8")
    return ledger, protected


def assert_contract(root: Path, summary: dict[str, object], protected_before: dict[str, str]) -> None:
    out = root / module.OUTPUT_DIR_REL
    required = [
        module.MANIFEST_NAME, module.HASH_AUDIT_NAME,
        module.IMMUTABILITY_AUDIT_NAME, module.SUMMARY_NAME,
    ]
    assert all((out / name).is_file() for name in required)
    assert summary["FINAL_STATUS"] in ALLOWED_STATUSES
    assert summary["research_only"] is True
    assert summary["official_use_allowed"] is False
    assert summary["production_adoption_allowed"] is False
    assert summary["real_book_mutation_allowed"] is False
    assert summary["broker_execution_allowed"] is False
    assert summary["official_mutation_detected"] is False
    assert summary["real_book_mutation_detected"] is False
    assert summary["broker_mutation_detected"] is False
    assert protected_before == {path: sha(root / path) for path in protected_before}
    manifest = json.loads((out / module.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["frozen_version_id"] == module.FROZEN_VERSION_ID
    assert manifest["research_only"] is True
    assert manifest["official_use_allowed"] is False
    assert manifest["production_adoption_allowed"] is False
    assert manifest["real_book_mutation_allowed"] is False
    assert manifest["broker_execution_allowed"] is False
    if summary["source_ledger_found"]:
        snapshot = out / module.SNAPSHOT_NAME
        assert snapshot.is_file()
        assert summary["source_row_count"] == summary["snapshot_row_count"]
    actual_outputs = {path.parent.resolve() for path in out.rglob("*") if path.is_file()}
    assert actual_outputs == {out.resolve()}


def test_complete_and_idempotent_lock() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        ledger, protected = fixture(root, complete=True)
        before = {path.relative_to(root).as_posix(): sha(path) for path in protected}
        first = module.run_stage(root)
        assert first["FINAL_STATUS"] == module.PASS_STATUS
        assert sha(ledger) == sha(root / module.OUTPUT_DIR_REL / module.SNAPSHOT_NAME)
        manifest_path = root / module.OUTPUT_DIR_REL / module.MANIFEST_NAME
        locked_hash = sha(manifest_path)
        snapshot_hash = sha(root / module.OUTPUT_DIR_REL / module.SNAPSHOT_NAME)
        second = module.run_stage(root)
        assert second["FINAL_STATUS"] == module.PASS_STATUS
        assert sha(manifest_path) == locked_hash
        assert sha(root / module.OUTPUT_DIR_REL / module.SNAPSHOT_NAME) == snapshot_hash
        assert_contract(root, second, before)


def test_partial_schema_and_duplicate_reporting() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        ledger, protected = fixture(root, complete=False)
        rows = list(csv.DictReader(ledger.open("r", encoding="utf-8")))
        rows[1]["observation_id"] = rows[0]["observation_id"]
        write_csv(ledger, rows)
        before = {path.relative_to(root).as_posix(): sha(path) for path in protected}
        summary = module.run_stage(root)
        assert summary["FINAL_STATUS"] == module.PARTIAL_STATUS
        assert summary["duplicate_observation_id_count"] == 1
        assert_contract(root, summary, before)


def test_blocked_outputs_still_exist() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        summary = module.run_stage(root)
        assert summary["FINAL_STATUS"] == module.BLOCKED_STATUS
        out = root / module.OUTPUT_DIR_REL
        for name in (module.MANIFEST_NAME, module.HASH_AUDIT_NAME, module.IMMUTABILITY_AUDIT_NAME, module.SUMMARY_NAME):
            assert (out / name).is_file()
        fixture(root, complete=True)
        recovered = module.run_stage(root)
        assert recovered["FINAL_STATUS"] == module.PASS_STATUS


def test_repository_wrapper_and_contract() -> None:
    protected_paths: list[Path] = []
    for base in (ROOT / "outputs", ROOT / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                text = path.as_posix().lower()
                if (
                    ("official" in text and ("rank" in text or "weight" in text))
                    or "real_book" in text or "realbook" in text or "broker" in text
                ):
                    protected_paths.append(path)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected_paths}
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT, text=True, capture_output=True,
    )
    summary_path = ROOT / module.OUTPUT_DIR_REL / module.SUMMARY_NAME
    assert summary_path.is_file(), completed.stdout + completed.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary["FINAL_STATUS"] in {module.FAIL_STATUS, module.BLOCKED_STATUS}:
        assert completed.returncode != 0
    else:
        assert completed.returncode == 0, completed.stdout + completed.stderr
    assert_contract(ROOT, summary, before)


if __name__ == "__main__":
    test_complete_and_idempotent_lock()
    test_partial_schema_and_duplicate_reporting()
    test_blocked_outputs_still_exist()
    test_repository_wrapper_and_contract()
    print("PASS test_v21_056_r1_current_testing_version_freeze_and_manifest")
