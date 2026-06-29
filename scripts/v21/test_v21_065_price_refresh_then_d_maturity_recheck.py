#!/usr/bin/env python
"""Contract test for V21.065 approved price refresh and D maturity recheck."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_065_price_refresh_then_d_maturity_recheck.py"
WRAPPER = ROOT / "scripts/v21/run_v21_065_price_refresh_then_d_maturity_recheck.ps1"
spec = importlib.util.spec_from_file_location("v21_065", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.SUMMARY_NAME, module.DETAIL_NAME, module.AUDIT_NAME,
    module.VALIDATION_NAME,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_wrapper() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]", source)
    assert not re.search(r"20\d{2}-\d{2}-\d{2}", source)
    v64_summary, _, _ = module.discover_v21_064(ROOT)
    v63_summary, _, _ = module.discover_v21_063(ROOT)
    protected = module.protected_paths(ROOT, v63_summary.parent, v64_summary.parent)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    completed = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(WRAPPER),
        ],
        cwd=ROOT, text=True, capture_output=True, timeout=960,
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
        int(summary["post_refresh_pending_count"])
        + int(summary["post_refresh_matured_count"])
        + int(summary["post_refresh_price_missing_count"])
        == total
    )
    for row in details:
        has_return = bool(row["realized_forward_return"].strip())
        assert has_return == (row["post_refresh_maturity_status"] == "MATURED")
        if row["post_refresh_maturity_status"] != "MATURED":
            assert row["realized_forward_return"].strip() not in {"0", "0.0"}
        assert row["research_only"] == "True"
    assert validation["observation_ids_preserved"] is True
    assert validation["missing_return_zero_fill_count"] == 0
    assert validation["warning_reconciled"] is True
    assert validation["v21_062_outputs_modified"] is False
    assert validation["v21_063_outputs_modified"] is False
    assert validation["v21_064_outputs_modified"] is False
    assert validation["a0_a1_b_c_d_source_outputs_modified"] is False
    assert validation["protected_outputs_modified"] == []
    for field in (
        "abcd_comparison_allowed", "preferred_policy_selected",
        "recommendation_allowed", "trade_action_created",
        "broker_execution_supported", "official_mutation",
    ):
        assert summary[field] == "False"
    assert summary["research_only"] == "True"
    assert summary["post_refresh_maturity_state"] in module.STATES
    expected_status, expected_decision, expected_next = module.STATUS_MAP[
        summary["post_refresh_maturity_state"]
    ]
    assert summary["final_status"] == expected_status
    assert summary["decision"] == expected_decision
    assert summary["recommended_next_stage"] == expected_next
    assert summary["provider_refresh_status"] in {
        "EXECUTED", "SKIPPED_VALIDATED_LATEST", "UNAVAILABLE"
    }
    assert before == {path: sha(ROOT / path) for path in before}
    assert {
        path.parent.resolve()
        for path in out.glob("V21_065_*")
        if path.is_file()
    } == {out.resolve()}


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_065_price_refresh_then_d_maturity_recheck")
