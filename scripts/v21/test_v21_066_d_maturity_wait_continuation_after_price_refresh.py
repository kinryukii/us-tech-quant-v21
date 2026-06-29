#!/usr/bin/env python
"""Contract test for V21.066 D maturity wait continuation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / (
    "scripts/v21/v21_066_d_maturity_wait_continuation_after_price_refresh.py"
)
WRAPPER = ROOT / (
    "scripts/v21/run_v21_066_d_maturity_wait_continuation_after_price_refresh.ps1"
)
spec = importlib.util.spec_from_file_location("v21_066", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.SUMMARY_NAME, module.DETAIL_NAME,
    module.AUDIT_NAME, module.VALIDATION_NAME,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_wrapper() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]", source)
    assert not re.search(r"20\d{2}-\d{2}-\d{2}", source)
    source_summary, _, _ = module.discover_v21_065(ROOT)
    protected = module.protected_paths(ROOT, source_summary.parent)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    completed = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(WRAPPER),
        ],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    out = ROOT / module.OUT_REL
    assert all((out / name).is_file() for name in REQUIRED)
    summary = next(csv.DictReader(
        (out / module.SUMMARY_NAME).open("r", encoding="utf-8")
    ))
    details = list(csv.DictReader(
        (out / module.DETAIL_NAME).open("r", encoding="utf-8")
    ))
    validation = json.loads(
        (out / module.VALIDATION_NAME).read_text(encoding="utf-8")
    )
    ids = [row["observation_id"] for row in details]
    assert ids and len(ids) == len(set(ids))
    total = int(summary["total_rows"])
    assert len(details) == total
    assert (
        int(summary["pending_count"])
        + int(summary["matured_count"])
        + int(summary["price_missing_count"])
        == total
    )
    before_target = (
        summary["next_target_maturity_date"]
        and summary["latest_available_price_date"]
        < summary["next_target_maturity_date"]
    )
    if before_target:
        assert summary["maturity_compute_allowed"] == "False"
        assert summary["repeated_price_refresh_suppressed"] == "True"
    if int(summary["matured_count"]) == 0:
        assert summary["abcd_comparison_allowed"] == "False"
    for field in (
        "preferred_policy_selected", "recommendation_allowed",
        "trade_action_created", "broker_execution_supported",
        "official_mutation",
    ):
        assert summary[field] == "False"
    assert summary["research_only"] == "True"
    assert summary["wait_continuation_state"] in module.STATES
    expected_status, expected_decision, expected_next = module.STATUS_MAP[
        summary["wait_continuation_state"]
    ]
    assert summary["final_status"] == expected_status
    assert summary["decision"] == expected_decision
    assert summary["recommended_next_stage"] == expected_next
    assert validation["observation_ids_preserved"] is True
    assert validation["v21_062_outputs_modified"] is False
    assert validation["v21_063_outputs_modified"] is False
    assert validation["v21_064_outputs_modified"] is False
    assert validation["v21_065_outputs_modified"] is False
    assert validation["a0_a1_b_c_d_source_outputs_modified"] is False
    assert validation["protected_outputs_modified"] == []
    assert before == {path: sha(ROOT / path) for path in before}
    assert {
        path.parent.resolve()
        for path in out.glob("V21_066_*") if path.is_file()
    } == {out.resolve()}


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_066_d_maturity_wait_continuation_after_price_refresh")
