#!/usr/bin/env python
"""Contract tests for the V21.056-R2 A0 canonical schema bridge."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_056_r2_a0_schema_bridge_and_canonical_control_view.py"
WRAPPER = ROOT / "scripts/v21/run_v21_056_r2_a0_schema_bridge_and_canonical_control_view.ps1"
spec = importlib.util.spec_from_file_location("v21_056_r2", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)

ALLOWED = {module.PASS_STATUS, module.PARTIAL_STATUS, module.BLOCKED_STATUS, module.FAIL_STATUS}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path, with_rank: bool = True) -> tuple[Path, list[Path]]:
    out = root / module.OUTPUT_DIR_REL
    snapshot = out / module.INPUT_SNAPSHOT_NAME
    rows = [
        {"observation_id": "O1", "as_of_date": "2026-06-18", "ticker": "AAA", "context_key": "UP", "lane_id": "BASE", "forward_return_window": "5D", "maturity_status": "PENDING", "realized_forward_return": "", "research_only": "TRUE"},
        {"observation_id": "O2", "as_of_date": "2026-06-18", "ticker": "BBB", "context_key": "UP", "lane_id": "BASE", "forward_return_window": "10D", "maturity_status": "PENDING", "realized_forward_return": "", "research_only": "TRUE"},
    ]
    write_csv(snapshot, rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / module.INPUT_MANIFEST_NAME).write_text(json.dumps({
        "frozen_version_id": module.FROZEN_VERSION_ID,
        "snapshot_ledger_sha256": sha(snapshot),
    }), encoding="utf-8")
    if with_rank:
        write_csv(root / "outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv", [
            {"rank": "1", "ticker": "AAA", "composite_candidate_score": "9.5", "latest_price_date": "2026-06-18"},
            {"rank": "2", "ticker": "BBB", "composite_candidate_score": "8.5", "latest_price_date": "2026-06-18"},
        ])
    protected = [
        root / "outputs/v21/official/OFFICIAL_RANKING.csv",
        root / "outputs/v21/official/OFFICIAL_WEIGHTS.csv",
        root / "outputs/v21/real_book/REAL_BOOK.csv",
        root / "outputs/v21/broker/BROKER.csv",
    ]
    for index, path in enumerate(protected):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"id,value\n{index},same\n", encoding="utf-8")
    return snapshot, protected


def assert_contract(root: Path, summary: dict[str, object], before: dict[str, str]) -> None:
    out = root / module.OUTPUT_DIR_REL
    for name in (module.VIEW_NAME, module.GAP_AUDIT_NAME, module.JOIN_AUDIT_NAME, module.MANIFEST_NAME, module.SUMMARY_NAME):
        assert (out / name).is_file()
    assert summary["FINAL_STATUS"] in ALLOWED
    rows = list(csv.DictReader((out / module.VIEW_NAME).open("r", encoding="utf-8")))
    source_rows = list(csv.DictReader((out / module.INPUT_SNAPSHOT_NAME).open("r", encoding="utf-8")))
    assert len(rows) == len(source_rows) == summary["canonical_row_count"] == summary["input_row_count"]
    assert [row["observation_id"] for row in rows] == [row["observation_id"] for row in source_rows]
    assert all(row["version_id"] == module.FROZEN_VERSION_ID for row in rows)
    assert all(row["variant_id"] == module.FROZEN_VERSION_ID for row in rows)
    assert summary["research_only"] is True
    assert summary["official_mutation_detected"] is False
    assert summary["real_book_mutation_detected"] is False
    assert summary["broker_mutation_detected"] is False
    assert summary["ready_for_abcd_experiment"] is (summary["blocked_bridge_count"] == 0)
    assert before == {path: sha(root / path) for path in before}
    assert {path.parent.resolve() for path in out.glob("V21_056_R2*") if path.is_file()} == {out.resolve()}


def test_complete_bridge() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        snapshot, protected = fixture(root, with_rank=True)
        protected.append(snapshot)
        before = {path.relative_to(root).as_posix(): sha(path) for path in protected}
        summary = module.run_stage(root)
        assert summary["FINAL_STATUS"] == module.PASS_STATUS
        assert summary["complete_bridge_count"] == 2
        assert summary["rank_available_count"] == 2
        assert summary["scheduled_maturity_date_available_count"] == 2
        assert_contract(root, summary, before)


def test_partial_rank_without_fabrication() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        snapshot, protected = fixture(root, with_rank=False)
        protected.append(snapshot)
        before = {path.relative_to(root).as_posix(): sha(path) for path in protected}
        summary = module.run_stage(root)
        assert summary["FINAL_STATUS"] == module.PARTIAL_STATUS
        assert summary["rank_missing_count"] == 2
        assert summary["blocked_bridge_count"] == 0
        assert_contract(root, summary, before)


def test_repository_wrapper() -> None:
    r1_paths = [
        ROOT / module.OUTPUT_DIR_REL / module.INPUT_SNAPSHOT_NAME,
        ROOT / module.OUTPUT_DIR_REL / module.INPUT_MANIFEST_NAME,
    ]
    protected: list[Path] = [path for path in r1_paths if path.is_file()]
    for base in (ROOT / "outputs", ROOT / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            text = path.as_posix().lower()
            if (
                ("official" in text and ("rank" in text or "weight" in text))
                or "real_book" in text or "realbook" in text or "broker" in text
            ):
                protected.append(path)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT, text=True, capture_output=True,
    )
    summary_path = ROOT / module.OUTPUT_DIR_REL / module.SUMMARY_NAME
    assert summary_path.is_file(), completed.stdout + completed.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary["FINAL_STATUS"] in {module.BLOCKED_STATUS, module.FAIL_STATUS}:
        assert completed.returncode != 0
    else:
        assert completed.returncode == 0, completed.stdout + completed.stderr
    assert_contract(ROOT, summary, before)


if __name__ == "__main__":
    test_complete_bridge()
    test_partial_rank_without_fabrication()
    test_repository_wrapper()
    print("PASS test_v21_056_r2_a0_schema_bridge_and_canonical_control_view")
