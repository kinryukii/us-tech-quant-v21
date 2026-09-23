#!/usr/bin/env python
"""Tests for V20.170-R1 DATA_TRUST ticker-level PIT safety emitter repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r1_data_trust_ticker_level_pit_safety_emitter_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_DISCOVERY = FACTORS / "V20_170_R1_DATA_TRUST_PIT_SOURCE_DISCOVERY.csv"
OUT_STATUS = FACTORS / "V20_170_R1_TICKER_LEVEL_PIT_SAFETY_STATUS.csv"
OUT_LINEAGE = FACTORS / "V20_170_R1_PIT_SAFETY_EVIDENCE_LINEAGE.csv"
OUT_BACKLOG = FACTORS / "V20_170_R1_PIT_SAFETY_REPAIR_BACKLOG.csv"
OUT_RETEST = FACTORS / "V20_170_R1_DATA_TRUST_DIRECT_STATUS_RETEST_INPUT.csv"
OUT_COVERAGE = FACTORS / "V20_170_R1_PIT_SAFETY_COVERAGE_AUDIT.csv"
OUT_GATE = FACTORS / "V20_170_R1_PIT_SAFETY_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_170_R1_PIT_SAFETY_SAFETY_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_170_R1_DATA_TRUST_TICKER_LEVEL_PIT_SAFETY_EMITTER_REPAIR_REPORT.md"
OUTPUTS = [OUT_DISCOVERY, OUT_STATUS, OUT_LINEAGE, OUT_BACKLOG, OUT_RETEST, OUT_COVERAGE, OUT_GATE, OUT_SAFETY, OUT_REPORT]

PASS_STATUS = "PASS_V20_170_R1_TICKER_LEVEL_PIT_SAFETY_REPAIR_READY_FOR_V20_170_R2"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R1_PIT_SAFETY_REPAIR_WITH_REMAINING_UNKNOWN_READY_FOR_V20_170_R2"
WARN_STATUS = "WARN_V20_170_R1_NO_TICKER_LEVEL_PIT_SAFETY_EVIDENCE_RECOVERED"
BLOCKED_STATUS = "BLOCKED_V20_170_R1_DATA_TRUST_TICKER_LEVEL_PIT_SAFETY_EMITTER_REPAIR"
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed", "promotion_ready", "official_recommendation_created",
    "official_ranking_mutated", "official_weight_change_created",
    "official_weight_registry_mutated", "weight_mutated", "real_book_action_created",
    "trade_action_created", "broker_execution_supported", "performance_claim_created",
    "shadow_weight_expansion_allowed",
]
STATUS_COLUMNS = {
    "ticker", "baseline_rank", "ticker_identity_match", "pit_direct_status",
    "pit_direct_pass", "pit_direct_fail", "pit_direct_unknown",
    "as_of_date_available", "factor_input_lineage_available",
    "source_timestamp_available", "non_pit_blocker_present", "leakage_flag_present",
    "pit_validation_status", "pit_source_artifact", "pit_source_field",
    "pit_status_confidence", "pit_failure_or_unknown_reason", "repair_required",
    "recommended_repair_action",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    assert rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[Path, str]:
    paths = [
        FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT.csv",
        FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_SOURCE_DISCOVERY.csv",
        FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER.csv",
        FACTORS / "V20_170_DATA_TRUST_DIRECT_PASS_FAIL_UNKNOWN.csv",
        FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_REPAIR_BACKLOG.csv",
        FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_COVERAGE_AUDIT.csv",
        FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_NEXT_GATE.csv",
        FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_SAFETY_AUDIT.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    ]
    return {p: digest(p) for p in paths if p.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_170_r1_pit_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.CONSOLIDATION = temp / "consolidation"
    module.FACTORS = temp / "factors"
    module.BACKTEST = temp / "backtest"
    module.READ_CENTER = temp / "read_center"
    for name in ["V170_CONTRACT", "V170_DISCOVERY", "V170_EMITTER", "V170_STATUS", "V170_BACKLOG", "V170_COVERAGE", "V170_GATE", "V170_SAFETY"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.BASELINE = module.CONSOLIDATION / module.BASELINE.name
    module.NAMED_PIT_SOURCES = [module.FACTORS / "DIRECT_PIT.csv"]
    for name in ["OUT_DISCOVERY", "OUT_STATUS", "OUT_LINEAGE", "OUT_BACKLOG", "OUT_RETEST", "OUT_COVERAGE", "OUT_GATE", "OUT_SAFETY"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_common_inputs(module, status_ok: bool = True) -> None:
    status = "WARN_V20_170_DIRECT_STATUS_EMITTER_CREATED_BUT_NO_DIRECT_PASS_ROWS" if status_ok else "PASS"
    for path in [module.V170_CONTRACT, module.V170_DISCOVERY, module.V170_STATUS, module.V170_BACKLOG, module.V170_COVERAGE, module.V170_SAFETY]:
        write_csv(path, [{"id": "X"}])
    write_csv(module.V170_GATE, [{
        "final_status": status,
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": "GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "direct_ticker_mapping_required_before_official_use": "TRUE",
        "ready_for_direct_status_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
    }])
    write_csv(module.BASELINE, [{"ticker": "AAA", "official_current_rank": "1"}, {"ticker": "BBB", "official_current_rank": "2"}])
    write_csv(module.V170_EMITTER, [
        {"ticker": "AAA", "direct_data_trust_status": "UNKNOWN", "pit_safety_status": "UNKNOWN"},
        {"ticker": "BBB", "direct_data_trust_status": "UNKNOWN", "pit_safety_status": "UNKNOWN"},
    ])


def write_pit_source(module, include_bbb: bool = False) -> None:
    rows = [{"ticker": "AAA", "as_of_date": "2026-06-05", "pit_status": "PASS", "factor_lineage": "rank_inputs", "source_timestamp": "2026-06-05T00:00:00Z", "leakage_flag": "FALSE", "non_pit_blocker": "FALSE"}]
    if include_bbb:
        rows.append({"ticker": "BBB", "as_of_date": "2026-06-05", "pit_status": "PASS", "factor_lineage": "rank_inputs", "source_timestamp": "2026-06-05T00:00:00Z", "leakage_flag": "FALSE", "non_pit_blocker": "FALSE"})
    write_csv(module.NAMED_PIT_SOURCES[0], rows)


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == BLOCKED_STATUS


def test_blocked_wrong_v170_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == BLOCKED_STATUS


def test_temp_partial_and_full_cases() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module)
        write_pit_source(module, include_bbb=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == PARTIAL_STATUS
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module)
        write_pit_source(module, include_bbb=True)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == PASS_STATUS


def test_data_trust_ticker_level_pit_safety_emitter_repair() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.170/base outputs were mutated"
    stdout = result.stdout
    for expected in [
        WARN_STATUS,
        "V20_170_GATE_CONSUMED=TRUE",
        "DATA_TRUST_SCORING_WEIGHT=0.0000000000",
        "DATA_TRUST_ROLE=GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "BASELINE_CANDIDATE_COUNT=40",
        "PIT_DIRECT_PASS_COUNT=0",
        "PIT_DIRECT_UNKNOWN_COUNT=40",
        "READY_FOR_DIRECT_STATUS_RETEST=FALSE",
        "READY_FOR_DIRECT_STATUS_GATE_ONLY_RANKING_SIMULATION=FALSE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "RANKING_SIMULATION_CREATED=FALSE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    status = read_csv(OUT_STATUS)
    retest = read_csv(OUT_RETEST)
    coverage = read_csv(OUT_COVERAGE)
    gate = read_csv(OUT_GATE)
    safety = read_csv(OUT_SAFETY)
    assert len(status) == 40
    assert len(retest) == 40
    assert STATUS_COLUMNS.issubset(status[0].keys()), STATUS_COLUMNS - set(status[0].keys())
    assert coverage[0]["ready_for_official_use"] == "FALSE"
    assert gate[0]["final_status"] == WARN_STATUS
    assert gate[0]["ranking_simulation_created"] == "FALSE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [status, gate, safety]:
        assert_safety(rows)
    assert "Aggregate PIT evidence is not treated as ticker-level" in OUT_REPORT.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v170_status_case()
    test_temp_partial_and_full_cases()
    test_data_trust_ticker_level_pit_safety_emitter_repair()
    print("PASS_V20_170_R1_DATA_TRUST_TICKER_LEVEL_PIT_SAFETY_EMITTER_REPAIR_TESTS")
