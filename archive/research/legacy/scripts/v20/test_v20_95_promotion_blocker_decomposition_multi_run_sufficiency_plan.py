from __future__ import annotations

import csv
import importlib.util
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_95_promotion_blocker_decomposition_multi_run_sufficiency_plan.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_95_promotion_blocker_decomposition_multi_run_sufficiency_plan.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_95_promotion_blocker_decomposition_multi_run_sufficiency_plan.ps1"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"

DETAIL = EVIDENCE / "V20_95_PROMOTION_BLOCKER_DECOMPOSITION_DETAIL.csv"
SUMMARY = EVIDENCE / "V20_95_PROMOTION_BLOCKER_DECOMPOSITION_SUMMARY.md"
DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_PROMOTION_BLOCKER_DECOMPOSITION_DETAIL.csv"
SUMMARY_ALIAS = EVIDENCE / "V20_CURRENT_PROMOTION_BLOCKER_DECOMPOSITION_SUMMARY.md"
EXPECTED_WRAPPER_STATUS = "WARN_V20_95_PROMOTION_BLOCKERS_DECOMPOSED_WITH_MISSING_OPTIONAL_INPUTS"
EXPECTED_BASELINE_COUNTS = {"PASS": 1, "WARN": 5, "BLOCK": 3}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_module():
    spec = importlib.util.spec_from_file_location("v20_95", SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "could not load V20.95 module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_wrapper() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{WRAPPER.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command])
    assert_true(result.returncode == 0, f"PowerShell parser failed: {result.stdout}\n{result.stderr}")


def assert_safety(row: dict[str, str]) -> None:
    assert_true(row["research_only"] == "TRUE", f"research_only invariant failed: {row}")
    for field in ["promotion_allowed", "official_recommendation_created", "official_weight_mutated", "trade_action_created"]:
        assert_true(row[field] == "FALSE", f"{field} invariant failed: {row}")


def assert_all_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        assert_safety(row)


def blocker_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return {state: sum(row["blocker_status"] == state for row in rows) for state in ["PASS", "WARN", "BLOCK"]}


def patch_inputs(module: object, overrides: dict[str, list[Path]]):
    original = module.INPUT_CANDIDATES
    module.INPUT_CANDIDATES = dict(original)
    for key, value in overrides.items():
        module.INPUT_CANDIDATES[key] = value
    return original


def test_outputs_and_blockers() -> None:
    for path in [DETAIL, SUMMARY, DETAIL_ALIAS, SUMMARY_ALIAS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")
    assert_true(DETAIL.read_bytes() == DETAIL_ALIAS.read_bytes(), "detail alias differs")
    assert_true(SUMMARY.read_bytes() == SUMMARY_ALIAS.read_bytes(), "summary alias differs")
    rows = read_csv(DETAIL)
    categories = {row["blocker_category"] for row in rows}
    expected = {
        "research_only_guard",
        "multi_run_history_sufficiency",
        "rolling_evidence_ledger_sufficiency",
        "shadow_feedback_stability",
        "candidate_dynamic_weight_promotion_readiness",
        "official_recommendation_readiness",
        "nasdaq_benchmark_hurdle",
        "operator_acceptance_requirement",
        "safety_state",
    }
    assert_true(expected.issubset(categories), f"missing blocker rows: {sorted(expected - categories)}")
    by_category = {row["blocker_category"]: row for row in rows}
    assert_true(blocker_counts(rows) == EXPECTED_BASELINE_COUNTS, f"unexpected baseline blocker counts: {blocker_counts(rows)}")
    assert_true(by_category["safety_state"]["blocker_status"] == "PASS", f"safety row not PASS: {by_category['safety_state']}")
    assert_true(by_category["nasdaq_benchmark_hurdle"]["nasdaq_hurdle_passed"] == "FALSE", "Nasdaq hurdle inferred true")
    assert_true(by_category["candidate_dynamic_weight_promotion_readiness"]["dynamic_weight_promotion_ready"] == "FALSE", "dynamic weight unexpectedly ready")
    assert_true(by_category["multi_run_history_sufficiency"]["discovered_run_count"] == "0", f"baseline discovered run count changed: {by_category['multi_run_history_sufficiency']}")
    assert_true(by_category["multi_run_history_sufficiency"]["required_run_count"] == "5", f"baseline required run count changed: {by_category['multi_run_history_sufficiency']}")
    assert_true(by_category["multi_run_history_sufficiency"]["remaining_run_count"] == "5", f"baseline remaining run count changed: {by_category['multi_run_history_sufficiency']}")
    assert_true(by_category["multi_run_history_sufficiency"]["sufficiency_met"] == "FALSE", f"baseline sufficiency unexpectedly met: {by_category['multi_run_history_sufficiency']}")
    assert_true(by_category["multi_run_history_sufficiency"]["promotion_blocking"] == "TRUE", f"multi-run row not promotion blocking: {by_category['multi_run_history_sufficiency']}")
    assert_true(by_category["official_recommendation_readiness"]["readiness_blockers"] == "V20_51_OFFICIAL_RECOMMENDATION_READINESS_MISSING", f"baseline V20.51 missing blocker changed: {by_category['official_recommendation_readiness']}")
    assert_all_safety(rows)
    summary = SUMMARY.read_text(encoding="utf-8")
    for token in [
        "## V20.94 Inherited Status",
        "## Blocker Decomposition Table",
        "## Multi-Run Sufficiency Gap",
        "## Dynamic Weight Readiness Gap",
        "## Official Recommendation Readiness Gap",
        "## Benchmark Hurdle State",
        "## Operator Acceptance Requirement",
        "## Safety Confirmation",
        "## Recommended Next Stages",
    ]:
        assert_true(token in summary, f"summary missing {token}")


def test_blocks_when_v20_94_not_closed() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        detail = Path(tmp) / "v20_94_detail.csv"
        summary = Path(tmp) / "summary.md"
        fields = ["evidence_chain_closure_status", "promotion_preflight_status", "promotion_allowed", "official_recommendation_created", "official_weight_mutated", "trade_action_created", "nasdaq_hurdle_passed"]
        write_csv(detail, [{
            "evidence_chain_closure_status": "BLOCKED_REQUIRED_EVIDENCE_CATEGORY_MISSING",
            "promotion_preflight_status": "BLOCKED_REQUIRED_EVIDENCE_CATEGORY_MISSING",
            "promotion_allowed": "FALSE",
            "official_recommendation_created": "FALSE",
            "official_weight_mutated": "FALSE",
            "trade_action_created": "FALSE",
            "nasdaq_hurdle_passed": "FALSE",
        }], fields)
        summary.write_text("blocked", encoding="utf-8")
        rows, status = module.build_rows(detail, summary)
    assert_true(status == module.BLOCKED_STATUS, f"not-closed V20.94 did not block: {status}")
    assert_true(rows[0]["blocker_status"] == "BLOCK", f"blocked row missing: {rows}")
    for row in rows:
        assert_safety(row)


def test_missing_optional_inputs_warn_not_crash() -> None:
    module = load_module()
    original = module.INPUT_CANDIDATES
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "missing.csv"
        try:
            module.INPUT_CANDIDATES = {key: [missing] for key in original}
            rows, status = module.build_rows()
        finally:
            module.INPUT_CANDIDATES = original
    assert_true(status == module.WARN_STATUS, f"missing optional inputs did not WARN: {status}")
    assert_true(any(row["evidence_source_status"] == "MISSING_OPTIONAL_INPUT" for row in rows), "missing optional inputs not reported")
    by_category = {row["blocker_category"]: row for row in rows}
    multi = by_category["multi_run_history_sufficiency"]
    assert_true(multi["blocker_status"] == "WARN", f"missing multi-run input did not WARN: {multi}")
    assert_true(multi["discovered_run_count"] == "0", f"missing input discovered runs not zero: {multi}")
    assert_true(multi["required_run_count"] == "5", f"missing input required runs not five: {multi}")
    assert_true(multi["remaining_run_count"] == "5", f"missing input remaining runs not five: {multi}")
    assert_true(multi["sufficiency_met"] == "FALSE", f"missing input sufficiency incorrectly met: {multi}")
    assert_true(multi["promotion_blocking"] == "TRUE", f"missing multi-run input not promotion blocking: {multi}")
    assert_all_safety(rows)


def test_multi_run_gap_calculation() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        run_file = tmpdir / "runs.csv"
        ledger_file = tmpdir / "ledger.csv"
        obs_file = tmpdir / "obs.csv"
        write_csv(run_file, [{"effective_source_run_count": "2"}], ["effective_source_run_count"])
        write_csv(ledger_file, [{"row_id": str(i)} for i in range(7)], ["row_id"])
        write_csv(obs_file, [{"row_id": str(i)} for i in range(11)], ["row_id"])
        original = module.INPUT_CANDIDATES
        try:
            module.INPUT_CANDIDATES = dict(original)
            module.INPUT_CANDIDATES["multi_run_history_sufficiency"] = [run_file]
            module.INPUT_CANDIDATES["rolling_evidence_ledger_sufficiency"] = [ledger_file]
            module.INPUT_CANDIDATES["shadow_feedback_stability"] = [obs_file]
            metrics, _source, status = module.multi_run_metrics()
        finally:
            module.INPUT_CANDIDATES = original
    assert_true(status == "OK", f"synthetic multi-run inputs not read: {status}")
    assert_true(metrics["discovered_run_count"] == "2", f"bad discovered run count: {metrics}")
    assert_true(metrics["remaining_run_count"] == "3", f"bad remaining run count: {metrics}")
    assert_true(metrics["observation_rows_available"] == "11", f"bad observation rows: {metrics}")
    assert_true(metrics["rolling_ledger_rows_available"] == "7", f"bad ledger rows: {metrics}")
    assert_true(metrics["sufficiency_met"] == "FALSE", f"sufficiency incorrectly met: {metrics}")


def test_multi_run_sufficiency_alone_does_not_enable_promotion() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        run_file = tmpdir / "runs.csv"
        ledger_file = tmpdir / "ledger.csv"
        obs_file = tmpdir / "obs.csv"
        write_csv(run_file, [{"effective_source_run_count": "6"}], ["effective_source_run_count"])
        write_csv(ledger_file, [{"row_id": str(i)} for i in range(25)], ["row_id"])
        write_csv(obs_file, [{"row_id": str(i)} for i in range(60)], ["row_id"])
        original = patch_inputs(module, {
            "multi_run_history_sufficiency": [run_file],
            "rolling_evidence_ledger_sufficiency": [ledger_file],
            "shadow_feedback_stability": [obs_file],
        })
        try:
            rows, status = module.build_rows()
        finally:
            module.INPUT_CANDIDATES = original
    by_category = {row["blocker_category"]: row for row in rows}
    multi = by_category["multi_run_history_sufficiency"]
    assert_true(multi["blocker_status"] == "PASS", f"synthetic sufficient multi-run did not PASS: {multi}")
    assert_true(multi["sufficiency_met"] == "TRUE", f"synthetic multi-run sufficiency not met: {multi}")
    assert_true(status in {module.WARN_STATUS, module.PASS_STATUS}, f"unexpected decomposition status with sufficient multi-run: {status}")
    assert_true(by_category["official_recommendation_readiness"]["official_recommendation_ready"] == "FALSE", "official readiness unexpectedly true")
    assert_true(by_category["nasdaq_benchmark_hurdle"]["nasdaq_hurdle_passed"] == "FALSE", "Nasdaq hurdle unexpectedly true")
    assert_all_safety(rows)


def test_dynamic_weight_zero_promoted_stays_blocked() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        weight_file = Path(tmp) / "weights.csv"
        write_csv(weight_file, [{"promotion_status": "BLOCKED_DRY_RUN", "candidate_weight_delta": "0"}], ["promotion_status", "candidate_weight_delta"])
        original = module.INPUT_CANDIDATES
        try:
            module.INPUT_CANDIDATES = dict(original)
            module.INPUT_CANDIDATES["candidate_dynamic_weight_promotion_readiness"] = [weight_file]
            metrics, _source, status = module.dynamic_weight_metrics()
        finally:
            module.INPUT_CANDIDATES = original
    assert_true(status == "OK", f"synthetic V20.66 not read: {status}")
    assert_true(metrics["candidate_dynamic_weight_rows"] == "1", f"bad candidate rows: {metrics}")
    assert_true(metrics["promoted_dynamic_weight_rows"] == "0", f"promoted rows should be zero: {metrics}")
    assert_true(metrics["blocked_dynamic_weight_rows"] == "1", f"blocked rows should be positive: {metrics}")
    assert_true(metrics["dynamic_weight_promotion_ready"] == "FALSE", f"dynamic weight incorrectly ready: {metrics}")


def test_dynamic_weight_promoted_does_not_override_official_readiness() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        weight_file = tmpdir / "weights.csv"
        rec_file = tmpdir / "recommendation.csv"
        write_csv(weight_file, [{"promotion_status": "PROMOTED", "candidate_weight_delta": "0.01"}], ["promotion_status", "candidate_weight_delta"])
        write_csv(rec_file, [{"official_recommendation_ready": "FALSE", "official_recommendation_created": "FALSE", "readiness_blockers": "OFFICIAL_GATE_NOT_READY"}], ["official_recommendation_ready", "official_recommendation_created", "readiness_blockers"])
        original = patch_inputs(module, {
            "candidate_dynamic_weight_promotion_readiness": [weight_file],
            "official_recommendation_readiness": [rec_file],
        })
        try:
            rows, _status = module.build_rows()
        finally:
            module.INPUT_CANDIDATES = original
    by_category = {row["blocker_category"]: row for row in rows}
    assert_true(by_category["candidate_dynamic_weight_promotion_readiness"]["dynamic_weight_promotion_ready"] == "TRUE", f"promoted dynamic weight not recognized: {by_category['candidate_dynamic_weight_promotion_readiness']}")
    assert_true(by_category["official_recommendation_readiness"]["official_recommendation_gate_attemptable"] == "FALSE", f"official gate became attemptable: {by_category['official_recommendation_readiness']}")
    assert_true(by_category["operator_acceptance_requirement"]["promotion_blocking"] == "TRUE", f"operator acceptance no longer blocks: {by_category['operator_acceptance_requirement']}")
    assert_all_safety(rows)


def test_official_recommendation_not_ready_stays_blocked() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        rec_file = Path(tmp) / "recommendation.csv"
        write_csv(rec_file, [{"official_recommendation_ready": "FALSE", "official_recommendation_created": "FALSE", "readiness_blockers": "NEEDS_OPERATOR_REVIEW"}], ["official_recommendation_ready", "official_recommendation_created", "readiness_blockers"])
        original = module.INPUT_CANDIDATES
        try:
            module.INPUT_CANDIDATES = dict(original)
            module.INPUT_CANDIDATES["official_recommendation_readiness"] = [rec_file]
            metrics, _source, status = module.official_recommendation_metrics()
        finally:
            module.INPUT_CANDIDATES = original
    assert_true(status == "OK", f"synthetic V20.51 not read: {status}")
    assert_true(metrics["official_recommendation_ready"] == "FALSE", f"recommendation incorrectly ready: {metrics}")
    assert_true(metrics["official_recommendation_created"] == "FALSE", f"recommendation created: {metrics}")
    assert_true(metrics["official_recommendation_gate_attemptable"] == "FALSE", f"gate incorrectly attemptable: {metrics}")
    assert_true("NEEDS_OPERATOR_REVIEW" in metrics["readiness_blockers"], f"readiness blocker missing: {metrics}")


def test_official_recommendation_missing_reports_v20_51_blocker() -> None:
    module = load_module()
    original = module.INPUT_CANDIDATES
    with tempfile.TemporaryDirectory() as tmp:
        try:
            module.INPUT_CANDIDATES = dict(original)
            module.INPUT_CANDIDATES["official_recommendation_readiness"] = [Path(tmp) / "missing_v20_51.csv"]
            metrics, _source, status = module.official_recommendation_metrics()
        finally:
            module.INPUT_CANDIDATES = original
    assert_true(status == "MISSING_OPTIONAL_INPUT", f"missing V20.51 status changed: {status}")
    assert_true(metrics["official_recommendation_ready"] == "FALSE", f"missing V20.51 marked ready: {metrics}")
    assert_true("V20_51_OFFICIAL_RECOMMENDATION_READINESS_MISSING" in metrics["readiness_blockers"], f"missing V20.51 blocker absent: {metrics}")


def test_nasdaq_hurdle_not_inferred() -> None:
    module = load_module()
    assert_true(module.nasdaq_hurdle_from_v20_94({"nasdaq_hurdle_passed": "FALSE"}) is False, "false Nasdaq hurdle inferred true")
    assert_true(module.nasdaq_hurdle_from_v20_94({"nasdaq_hurdle_passed": ""}) is False, "empty Nasdaq hurdle inferred true")
    assert_true(module.nasdaq_hurdle_from_v20_94({"nasdaq_hurdle_passed": "PASS"}) is False, "ambiguous Nasdaq PASS inferred true")
    assert_true(module.nasdaq_hurdle_from_v20_94({"benchmark_hurdle": "TRUE"}) is False, "unrecognized benchmark field inferred true")
    assert_true(module.nasdaq_hurdle_from_v20_94({"nasdaq_hurdle_passed": "TRUE"}) is True, "explicit true Nasdaq hurdle not recognized")


def test_operator_acceptance_not_satisfied_by_acceptance_proof_count() -> None:
    rows = read_csv(DETAIL)
    by_category = {row["blocker_category"]: row for row in rows}
    operator = by_category["operator_acceptance_requirement"]
    assert_true(operator["blocker_status"] == "BLOCK", f"operator acceptance not blocked: {operator}")
    assert_true(operator["promotion_blocking"] == "TRUE", f"operator acceptance not promotion blocking: {operator}")
    assert_true("OPERATOR_ACCEPTANCE_REQUIRED" in operator["missing_requirement"], f"operator missing requirement changed: {operator}")
    assert_all_safety(rows)


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(EXPECTED_WRAPPER_STATUS in result.stdout, f"unexpected wrapper status: {result.stdout}")
    test_outputs_and_blockers()
    test_blocks_when_v20_94_not_closed()
    test_missing_optional_inputs_warn_not_crash()
    test_multi_run_gap_calculation()
    test_multi_run_sufficiency_alone_does_not_enable_promotion()
    test_dynamic_weight_zero_promoted_stays_blocked()
    test_dynamic_weight_promoted_does_not_override_official_readiness()
    test_official_recommendation_not_ready_stays_blocked()
    test_official_recommendation_missing_reports_v20_51_blocker()
    test_nasdaq_hurdle_not_inferred()
    test_operator_acceptance_not_satisfied_by_acceptance_proof_count()
    print("PASS_V20_95_PROMOTION_BLOCKER_DECOMPOSITION_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
