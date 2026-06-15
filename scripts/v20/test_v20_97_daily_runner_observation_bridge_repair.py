from __future__ import annotations

import csv
import importlib.util
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_97_daily_runner_observation_bridge_repair.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_97_daily_runner_observation_bridge_repair.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_97_daily_runner_observation_bridge_repair.ps1"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"

DETAIL = EVIDENCE / "V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_DETAIL.csv"
SUMMARY = EVIDENCE / "V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_SUMMARY.md"
DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_DETAIL.csv"
SUMMARY_ALIAS = EVIDENCE / "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_SUMMARY.md"


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
    spec = importlib.util.spec_from_file_location("v20_97", SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "could not load V20.97 module")
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
    assert_true(row["promotion_allowed"] == "FALSE", f"promotion_allowed invariant failed: {row}")
    for field in ["official_recommendation_created", "official_weight_mutated", "trade_action_created"]:
        assert_true(row[field] == "FALSE", f"{field} invariant failed: {row}")


def markdown(path: Path, run_id: str = "V20_55_TEST_RUN", status: str = "PASS", extra: str = "") -> None:
    path.write_text(
        "\n".join(
            [
                "# Daily Runner",
                f"- run_id: {run_id}",
                "- created_at_utc: 2026-06-09T00:00:00Z",
                f"- {status}",
                "- research_only: TRUE",
                "- promotion_allowed: FALSE",
                "- official_recommendation_created: FALSE",
                "- official_weight_mutated: FALSE",
                "- trade_action_created: FALSE",
                extra,
                "",
            ]
        ),
        encoding="utf-8",
    )


def markdown_with_timestamp(path: Path, run_id: str, timestamp: str, status: str) -> None:
    path.write_text(
        "\n".join(
            [
                "# Daily Runner",
                f"- run_id: {run_id}",
                f"- created_at_utc: {timestamp}",
                f"- {status}",
                "- research_only: TRUE",
                "- promotion_allowed: FALSE",
                "- official_recommendation_created: FALSE",
                "- official_weight_mutated: FALSE",
                "- trade_action_created: FALSE",
                "",
            ]
        ),
        encoding="utf-8",
    )


def csv_row(run_id: str = "CSV_RUN", status: str = "PASS", **overrides: str) -> dict[str, str]:
    row = {
        "run_id": run_id,
        "created_at_utc": "2026-06-09T00:00:00Z",
        "status": status,
        "research_only": "TRUE",
        "promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
    }
    row.update(overrides)
    return row


def test_outputs_aliases_and_summary() -> None:
    for path in [DETAIL, SUMMARY, DETAIL_ALIAS, SUMMARY_ALIAS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")
    assert_true(DETAIL.read_bytes() == DETAIL_ALIAS.read_bytes(), "detail alias differs")
    assert_true(SUMMARY.read_bytes() == SUMMARY_ALIAS.read_bytes(), "summary alias differs")
    rows = read_csv(DETAIL)
    for row in rows:
        assert_safety(row)
    summary = SUMMARY.read_text(encoding="utf-8")
    for token in [
        "## Source Scan",
        "source_files_scanned:",
        "source_files_found:",
        "source_files_missing_warn:",
        "## Normalized Observation Counts",
        "valid_observation_row_count:",
        "invalid_observation_row_count:",
        "duplicate_count:",
        "eligible_for_v20_96_count:",
        "## Rejection Reasons",
        "## Safety Confirmation",
        "promotion_allowed: FALSE",
        "official_recommendation_created: FALSE",
        "official_weight_mutated: FALSE",
        "trade_action_created: FALSE",
    ]:
        assert_true(token in summary, f"summary missing {token}")


def test_missing_optional_files_warn_not_crash() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "missing.md"
        rows, metrics, status = module.build_bridge_rows([missing], require_context=False, expand_versioned=False)
    assert_true(status == module.WARN_STATUS, f"missing optional files should WARN: {status}")
    assert_true(metrics["source_files_scanned"] == 1, f"bad scanned count: {metrics}")
    assert_true(metrics["source_files_found"] == 0, f"bad found count: {metrics}")
    assert_true(metrics["source_files_missing"] == 1, f"bad missing count: {metrics}")
    assert_true(metrics["valid_observation_row_count"] == 0, f"missing sources yielded valid rows: {metrics}")


def test_markdown_and_export_brief_create_observations_and_dedupe() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md"
        brief = Path(tmp) / "V20_CURRENT_DAILY_OPERATION_EXPORT_BRIEF.md"
        markdown(report, run_id="SAME_RUN", status="Final wrapper status:\nPASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_CREATED")
        markdown(brief, run_id="SAME_RUN", status="Wrapper status: PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_CREATED")
        rows, metrics, status = module.build_bridge_rows([report, brief], require_context=False, expand_versioned=False)
    assert_true(status == module.PASS_STATUS, f"valid markdown sources did not pass: {status}")
    assert_true(metrics["normalized_observation_row_count"] == 2, f"normalized row count should include duplicate source rows: {metrics}")
    assert_true(metrics["canonical_observation_row_count"] == 1, f"duplicate run not deduped canonically: {metrics}")
    assert_true(metrics["duplicate_count"] == 1, f"duplicate count missing: {metrics}")
    assert_true(metrics["valid_observation_row_count"] == 1, f"valid count wrong: {metrics}")
    assert_true(rows[0]["eligible_for_v20_96"] == "TRUE", f"valid bridge row not eligible: {rows[0]}")
    assert_true(rows[0]["source_status_normalized"].startswith("PASS"), f"status not normalized to PASS: {rows[0]}")
    assert_safety(rows[0])


def test_versioned_pass_beats_current_blocked_and_inventory_records_rejection() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        current = Path(tmp) / "V20_CURRENT_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md"
        versioned = Path(tmp) / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT_20260609.md"
        markdown(current, run_id="CURRENT_BLOCKED", status="wrapper status: BLOCKED_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER")
        markdown(versioned, run_id="VERSIONED_PASS", status="wrapper status: PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_CREATED")
        rows, metrics, status = module.build_bridge_rows([current, versioned], require_context=False, expand_versioned=False)
    by_id = {row["observation_run_id"]: row for row in rows}
    assert_true(status == module.PASS_STATUS, f"versioned PASS did not recover bridge: {status}")
    assert_true(metrics["eligible_for_v20_96_count"] == 1, f"eligible count wrong: {metrics}")
    assert_true(metrics["pass_candidate_count"] == 1, f"PASS candidate count wrong: {metrics}")
    assert_true(metrics["blocked_na_candidate_count"] == 1, f"blocked/NA candidate count wrong: {metrics}")
    assert_true(by_id["VERSIONED_PASS"]["candidate_selected"] == "TRUE", f"PASS artifact not selected: {by_id['VERSIONED_PASS']}")
    assert_true(by_id["VERSIONED_PASS"]["eligible_for_v20_96"] == "TRUE", f"PASS artifact not eligible: {by_id['VERSIONED_PASS']}")
    assert_true(by_id["CURRENT_BLOCKED"]["eligible_for_v20_96"] == "FALSE", f"BLOCKED current alias eligible: {by_id['CURRENT_BLOCKED']}")
    assert_true("SOURCE_STATUS_NOT_PASS_OR_ACCEPTABLE_WARN" in by_id["CURRENT_BLOCKED"]["observation_rejection_reason"], f"BLOCKED rejection missing: {by_id['CURRENT_BLOCKED']}")


def test_newest_valid_pass_selected_before_older_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        older = Path(tmp) / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT_OLD.md"
        newer = Path(tmp) / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT_NEW.md"
        markdown_with_timestamp(older, "RUN_OLD", "2026-06-01T00:00:00Z", "wrapper status: PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_CREATED")
        markdown_with_timestamp(newer, "RUN_NEW", "2026-06-09T00:00:00Z", "wrapper status: PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_CREATED")
        rows, metrics, status = module.build_bridge_rows([older, newer], require_context=False, expand_versioned=False)
    by_id = {row["observation_run_id"]: row for row in rows}
    assert_true(status == module.PASS_STATUS, f"multiple PASS reports did not pass: {status}")
    assert_true(metrics["eligible_for_v20_96_count"] == 2, f"both unique PASS runs should be eligible: {metrics}")
    assert_true(int(by_id["RUN_NEW"]["candidate_rank"]) < int(by_id["RUN_OLD"]["candidate_rank"]), f"newer PASS not ranked before older: {by_id}")
    assert_true(by_id["RUN_NEW"]["source_timestamp_utc"] >= by_id["RUN_OLD"]["source_timestamp_utc"], f"timestamps not preserved: {by_id}")


def test_no_valid_source_requires_fresh_v20_55_rerun() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        blocked = Path(tmp) / "blocked.md"
        na = Path(tmp) / "na.md"
        markdown(blocked, run_id="BLOCKED_ONLY", status="wrapper status: BLOCKED_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER")
        na.write_text(
            "\n".join(
                [
                    "- run_id: NA_ONLY",
                    "- created_at_utc: 2026-06-09T00:00:00Z",
                    "- research_only: TRUE",
                    "- promotion_allowed: FALSE",
                    "- official_recommendation_created: FALSE",
                    "- official_weight_mutated: FALSE",
                    "- trade_action_created: FALSE",
                ]
            ),
            encoding="utf-8",
        )
        rows, metrics, status = module.build_bridge_rows([blocked, na], require_context=False, expand_versioned=False)
        summary = Path(tmp) / "summary.md"
        module.write_summary(summary, status, metrics)
        assert_true(status == module.WARN_STATUS, f"blocked/NA-only sources should WARN: {status}")
        assert_true(metrics["valid_observation_row_count"] == 0, f"blocked/NA-only valid count wrong: {metrics}")
        assert_true(metrics["eligible_for_v20_96_count"] == 0, f"blocked/NA-only eligible count wrong: {metrics}")
        assert_true(metrics["fresh_daily_runner_rerun_required"] is True, f"fresh rerun flag missing: {metrics}")
        text = summary.read_text(encoding="utf-8")
        assert_true("FRESH_DAILY_RUNNER_RERUN_REQUIRED: TRUE" in text, "summary missing fresh rerun requirement")
        assert_true("rerun V20.55 daily one-click research runner" in text, "summary missing V20.55 rerun recommendation")
        for row in rows:
            assert_safety(row)


def test_markdown_status_extraction_variants() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        final_wrapper = tmpdir / "final_wrapper.md"
        mixed_case = tmpdir / "mixed_case.md"
        acceptable_warn = tmpdir / "warn.md"
        blocked = tmpdir / "blocked.md"
        ambiguous = tmpdir / "ambiguous.md"
        markdown(final_wrapper, run_id="FINAL_WRAPPER", status="Final wrapper status:\nPASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_CREATED")
        markdown(mixed_case, run_id="MIXED_CASE", status="wrapper status: PASS_EVIDENCE_CHAIN_CLOSED_PROMOTION_STILL_BLOCKED")
        markdown(acceptable_warn, run_id="WARN_RUN", status="wrapper status: WARN_V20_96_INSUFFICIENT_VALID_OBSERVATION_RUNS")
        markdown(blocked, run_id="BLOCKED_RUN", status="wrapper status: BLOCKED_V20_96_MISSING_V20_95_PREFLIGHT")
        markdown(ambiguous, run_id="AMBIGUOUS_RUN", status="status: NOT_PROMOTED")
        rows, metrics, status = module.build_bridge_rows([final_wrapper, mixed_case, acceptable_warn, blocked, ambiguous], require_context=False, expand_versioned=False)
    by_id = {row["observation_run_id"]: row for row in rows}
    assert_true(status == module.PASS_STATUS, f"valid PASS/WARN rows should yield pass: {status}")
    for run_id in ["FINAL_WRAPPER", "MIXED_CASE"]:
        assert_true(by_id[run_id]["source_status_normalized"].startswith("PASS"), f"PASS status not extracted: {by_id[run_id]}")
        assert_true(by_id[run_id]["eligible_for_v20_96"] == "TRUE", f"PASS row not eligible: {by_id[run_id]}")
    assert_true(by_id["WARN_RUN"]["source_status_normalized"].startswith("WARN"), f"WARN status not extracted: {by_id['WARN_RUN']}")
    assert_true(by_id["WARN_RUN"]["eligible_for_v20_96"] == "TRUE", f"acceptable WARN row not eligible: {by_id['WARN_RUN']}")
    assert_true(by_id["BLOCKED_RUN"]["eligible_for_v20_96"] == "FALSE", f"BLOCKED row eligible: {by_id['BLOCKED_RUN']}")
    assert_true("SOURCE_STATUS_NOT_PASS_OR_ACCEPTABLE_WARN" in by_id["BLOCKED_RUN"]["observation_rejection_reason"], f"BLOCKED rejection reason missing: {by_id['BLOCKED_RUN']}")
    assert_true(by_id["AMBIGUOUS_RUN"]["eligible_for_v20_96"] == "FALSE", f"ambiguous row eligible: {by_id['AMBIGUOUS_RUN']}")
    assert_true("SOURCE_STATUS_NOT_PASS_OR_ACCEPTABLE_WARN" in by_id["AMBIGUOUS_RUN"]["observation_rejection_reason"], f"ambiguous rejection missing: {by_id['AMBIGUOUS_RUN']}")
    assert_true("PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_CREATED" in metrics["normalized_statuses"], f"raw normalized statuses missing PASS token: {metrics}")


def test_missing_run_id_uses_safe_fallback() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "V20_CURRENT_DAILY_OPERATION_EXPORT_BRIEF.md"
        report.write_text(
            "\n".join(
                [
                    "- created_at_utc: 2026-06-09T00:00:00Z",
                    "- status: PASS",
                    "- research_only: TRUE",
                    "- promotion_allowed: FALSE",
                    "- official_recommendation_created: FALSE",
                    "- official_weight_mutated: FALSE",
                    "- trade_action_created: FALSE",
                ]
            ),
            encoding="utf-8",
        )
        rows, metrics, status = module.build_bridge_rows([report], require_context=False, expand_versioned=False)
    assert_true(status == module.PASS_STATUS, f"fallback row should be valid: {status}")
    assert_true(metrics["valid_observation_row_count"] == 1, f"fallback row not valid: {metrics}")
    assert_true("RUN_ID_DERIVED_FROM_TIMESTAMP_AND_SOURCE_STAGE" in rows[0]["notes"] or "RUN_ID_FALLBACK" in rows[0]["notes"], f"fallback note missing: {rows[0]}")
    assert_true(rows[0]["observation_run_id"], f"fallback run id missing: {rows[0]}")


def test_malformed_and_unsafe_sources_rejected() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        csv_file = Path(tmp) / "V20_CURRENT_OBSERVATION_INTAKE.csv"
        rows_in = [
            csv_row("NO_STATUS", status=""),
            csv_row("BAD_REC", official_recommendation_created="TRUE"),
            csv_row("BAD_WEIGHT", official_weight_mutated="TRUE"),
            csv_row("BAD_TRADE", trade_action_created="TRUE"),
            csv_row("BAD_PROMO", promotion_allowed="TRUE"),
        ]
        fields = list(rows_in[0].keys())
        write_csv(csv_file, rows_in, fields)
        rows, metrics, status = module.build_bridge_rows([csv_file], require_context=False, expand_versioned=False)
    assert_true(status == module.WARN_STATUS, f"unsafe-only sources should WARN: {status}")
    assert_true(metrics["invalid_observation_row_count"] == 5, f"invalid count wrong: {metrics}")
    for reason in [
        "SOURCE_STATUS_NOT_PASS_OR_ACCEPTABLE_WARN",
        "OFFICIAL_RECOMMENDATION_CREATED_NOT_FALSE",
        "OFFICIAL_WEIGHT_MUTATED_NOT_FALSE",
        "TRADE_ACTION_CREATED_NOT_FALSE",
        "PROMOTION_ALLOWED_NOT_FALSE",
    ]:
        assert_true(reason in metrics["rejected_reasons"], f"missing rejection reason {reason}: {metrics}")
    for row in rows:
        assert_true(row["eligible_for_v20_96"] == "FALSE", f"unsafe row eligible: {row}")
        assert_safety(row)


def test_three_duplicate_sources_count_two_duplicates() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        files = [Path(tmp) / f"source_{index}.md" for index in range(3)]
        for file in files:
            markdown(file, run_id="SHARED_RUN", status="Final status: PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_CREATED")
        rows, metrics, status = module.build_bridge_rows(files, require_context=False, expand_versioned=False)
    assert_true(status == module.PASS_STATUS, f"duplicate valid run should produce PASS: {status}")
    assert_true(metrics["normalized_observation_row_count"] == 3, f"normalized count should be 3: {metrics}")
    assert_true(metrics["canonical_observation_row_count"] == 1, f"canonical count should be 1: {metrics}")
    assert_true(metrics["duplicate_count"] == 2, f"duplicate count should be 2: {metrics}")
    assert_true(metrics["eligible_for_v20_96_count"] == 1, f"eligible canonical count should be 1: {metrics}")
    assert_true(len(rows) == 1, f"detail should keep one canonical row: {rows}")
    assert_safety(rows[0])


def test_pass_status_with_failed_safety_flags_rejected() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        csv_file = Path(tmp) / "unsafe_pass.csv"
        rows_in = [
            csv_row("BAD_REC", status="PASS_V20_55_OK", official_recommendation_created="TRUE"),
            csv_row("BAD_WEIGHT", status="PASS_V20_55_OK", official_weight_mutated="TRUE"),
            csv_row("BAD_TRADE", status="PASS_V20_55_OK", trade_action_created="TRUE"),
        ]
        write_csv(csv_file, rows_in, list(rows_in[0].keys()))
        rows, metrics, status = module.build_bridge_rows([csv_file], require_context=False, expand_versioned=False)
    assert_true(status == module.WARN_STATUS, f"unsafe PASS rows should not produce pass: {status}")
    assert_true(metrics["eligible_for_v20_96_count"] == 0, f"unsafe PASS rows became eligible: {metrics}")
    for reason in ["OFFICIAL_RECOMMENDATION_CREATED_NOT_FALSE", "OFFICIAL_WEIGHT_MUTATED_NOT_FALSE", "TRADE_ACTION_CREATED_NOT_FALSE"]:
        assert_true(reason in metrics["rejected_reasons"], f"missing safety rejection {reason}: {metrics}")
    for row in rows:
        assert_true(row["source_status_normalized"].startswith("PASS"), f"test fixture did not normalize PASS: {row}")
        assert_true(row["eligible_for_v20_96"] == "FALSE", f"unsafe row eligible: {row}")
        assert_safety(row)


def test_v20_55_research_only_warn_bridges_for_research_only_not_promotion() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md"
        markdown(
            report,
            run_id="WARN_RESEARCH_ONLY",
            status="Status: WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED",
        )
        rows, metrics, status = module.build_bridge_rows([report], require_context=False, expand_versioned=False)
    assert_true(status == module.PASS_STATUS, f"research-only WARN should bridge as valid research observation: {status}")
    assert_true(metrics["valid_research_observation_rows"] == 1, f"research observation count wrong: {metrics}")
    assert_true(metrics["eligible_for_v20_96_research_only"] == 1, f"V20.96 research-only eligibility missing: {metrics}")
    assert_true(metrics["eligible_for_official_promotion"] == 0, f"research-only WARN became official eligible: {metrics}")
    row = rows[0]
    assert_true(row["observation_class"] == "RESEARCH_ONLY_READY_PROMOTION_BLOCKED", f"wrong class: {row}")
    assert_true(row["research_observation_valid"] == "TRUE", f"research valid flag missing: {row}")
    assert_true(row["official_promotion_eligible"] == "FALSE", f"official promotion not blocked: {row}")
    assert_true(row["official_recommendation_created"] == "FALSE", f"official recommendation created: {row}")
    assert_true(row["official_weight_mutated"] == "FALSE" and row["weight_mutated"] == "FALSE", f"weight mutation allowed: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action created: {row}")


def test_current_bridge_preserves_v20_27_and_lineage_promotion_blockers() -> None:
    rows = read_csv(DETAIL)
    summary = SUMMARY.read_text(encoding="utf-8")
    valid_rows = [row for row in rows if row.get("research_observation_valid") == "TRUE"]
    assert_true(valid_rows, "current bridge has no valid research observation rows")
    assert_true(all(row["official_promotion_eligible"] == "FALSE" for row in valid_rows), f"current rows became promotion eligible: {valid_rows}")
    assert_true(any(row["v20_27_forward_pending"] == "TRUE" for row in valid_rows), f"V20.27 pending flag missing: {valid_rows}")
    assert_true("V20.27" in summary, "summary missing V20.27 promotion blocker")
    assert_true("missing promotion lineage" in summary.lower(), "summary missing promotion lineage blocker")


def test_current_rerun_exposes_status_provenance_when_zero_valid() -> None:
    rows = read_csv(DETAIL)
    summary = SUMMARY.read_text(encoding="utf-8")
    assert_true("extracted_raw_statuses:" in summary, "summary missing raw status provenance")
    assert_true("normalized_statuses:" in summary, "summary missing normalized status provenance")
    valid = sum(row["eligible_for_v20_96"] == "TRUE" for row in rows)
    if valid == 0:
        assert_true(any(row["source_status_raw"] for row in rows), f"zero-valid run lacks raw statuses: {rows}")
        assert_true(any(row["source_status_normalized"] for row in rows), f"zero-valid run lacks normalized statuses: {rows}")
        assert_true(any(row["observation_rejection_reason"] != "NA" for row in rows), f"zero-valid run lacks rejection reasons: {rows}")


def test_source_inventory_fields_present() -> None:
    rows = read_csv(DETAIL)
    assert_true(rows, "current detail rows empty")
    for row in rows:
        for field in ["source_status_raw", "source_status_normalized", "source_run_id", "source_timestamp_utc", "candidate_rank", "candidate_selected", "observation_rejection_reason", "source_file_exists"]:
            assert_true(field in row, f"inventory field missing {field}: {row}")
        assert_true(row["candidate_rank"], f"candidate rank missing: {row}")
        assert_true(row["candidate_selected"] in {"TRUE", "FALSE"}, f"candidate selected invalid: {row}")


def test_context_missing_blocks() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        assert_true(not module.context_ok(Path(tmp) / "missing.csv"), "missing V20.96 context accepted")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(
        "PASS_V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIRED" in result.stdout
        or "WARN_V20_97_NO_VALID_DAILY_RUNNER_OBSERVATIONS_FOUND" in result.stdout,
        f"unexpected wrapper status: {result.stdout}",
    )
    test_outputs_aliases_and_summary()
    test_missing_optional_files_warn_not_crash()
    test_markdown_and_export_brief_create_observations_and_dedupe()
    test_versioned_pass_beats_current_blocked_and_inventory_records_rejection()
    test_newest_valid_pass_selected_before_older_pass()
    test_no_valid_source_requires_fresh_v20_55_rerun()
    test_markdown_status_extraction_variants()
    test_missing_run_id_uses_safe_fallback()
    test_malformed_and_unsafe_sources_rejected()
    test_three_duplicate_sources_count_two_duplicates()
    test_pass_status_with_failed_safety_flags_rejected()
    test_v20_55_research_only_warn_bridges_for_research_only_not_promotion()
    test_current_rerun_exposes_status_provenance_when_zero_valid()
    test_current_bridge_preserves_v20_27_and_lineage_promotion_blockers()
    test_source_inventory_fields_present()
    test_context_missing_blocks()
    print("PASS_V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
