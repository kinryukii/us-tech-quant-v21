"""Refresh report presentation from a preserved complete ledger audit.

This caller is outside the learning/execution freeze. It never calls fit,
forecast, replay, or audit_account/audit_all, and never opens account ledgers.
Archive the original complete delivery before editing reporting templates.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import build_delivery as delivery
from common import ROOT, clean, read, sha, strategies, write


ARCHIVE = ROOT / "diagnostics/DELIVERY_INITIAL_FULL_AUDIT"


def need(condition, reason):
    delivery._need(condition, "REPORT_REFRESH:" + reason)


def relative(path):
    return str(path.relative_to(ROOT))


def audit_grid(verification):
    rows = verification["path_audits"]
    expected = {(year, spec["strategy_id"], False) for year in delivery.YEARS for spec in strategies()}
    expected |= {(year, sid, True) for year in delivery.YEARS for sid in delivery.CONTROLS}
    actual = {(int(row["year"]), row["strategy_id"], bool(row["control"])) for row in rows}
    need(verification["verification_status"] == "PASS"
         and verification["diagnostic_execution"] == "COMPLETE"
         and len(rows) == len(expected) == 10116 and actual == expected
         and all(row["status"] == "PASS" for row in rows), "ORIGINAL_COMPLETE_AUDIT_REQUIRED")
    need(verification["delivered_pto_path_windows"] == 10106
         and verification["formal_full_pool"] == "BLOCKED"
         and not verification["blind_test"] and not verification["fitting_performed"], "ORIGINAL_SCOPE_CHANGED")


def training_boundary_tables(source_hashes):
    native_path, fusion_path = ROOT / "FIT_LOG.csv", ROOT / "FUSION_FIT_LOG.csv"
    native, fusion = delivery._csv(native_path), delivery._csv(fusion_path)
    need(len(native) == 93 and not native.duplicated(["stage", "model_id"]).any()
         and native.status.value_counts().to_dict() == {"PASS": 84, "FAILED": 9},
         "NATIVE_ORIGINAL_FIT_HISTORY_CHANGED")
    rows = []
    for stage in ["early", "validation", "final"]:
        group = native.loc[native.stage.eq(stage)]
        need(len(group) == 31 and set(group.model_id) == set(delivery.PROVIDERS)
             and group.sample_count.eq(30000).all() and group.feature_count.eq(32).all(),
             "NATIVE_FIT_SAMPLE_CONTRACT_CHANGED")
        row = dict(stage=stage, models=31, sample_rows_each=30000, features=32,
                   original_log_pass=int(group.status.eq("PASS").sum()),
                   original_restore_failures=int(group.status.eq("FAILED").sum()))
        for column in ["cutoff_exclusive", "train_signal_min", "train_signal_max", "train_label_end_max"]:
            values = group[column].astype(str).unique()
            need(len(values) == 1, "NATIVE_SAMPLE_DATE_BOUNDARIES_DISAGREE:" + stage)
            row[column] = values[0]
        need(row["train_signal_min"] == "2023-01-03"
             and row["train_label_end_max"] < row["cutoff_exclusive"] <= "2026-01-01",
             "NATIVE_SAMPLE_DATE_BOUNDARIES_ILLEGAL")
        rows.append(row)
    fusion_rows = []
    for stage in ["validation", "final"]:
        group = fusion.loc[fusion.stage.eq(stage)]
        need(len(group) == 121 and not group.duplicated(["group", "method"]).any()
             and set(group.group) == set(delivery.COALITIONS)
             and set(group.method) == set(delivery.FUSIONS)
             and group.rows.le(20000).all(), "FUSION_OOF_TRAINING_GRID_CHANGED")
        cutoffs = {tuple(ast.literal_eval(text)) for text in group.base_prediction_cutoffs}
        need(len(cutoffs) == 1, "FUSION_OOF_BASE_CUTOFFS_DISAGREE")
        base_cutoffs = list(next(iter(cutoffs)))
        fusion_rows.append(dict(stage=stage, objects=121, base_oof_signal_years="2024" if stage == "validation" else "2024,2025",
            rows_min=int(group.rows.min()), rows_max=int(group.rows.max()),
            dates_min=int(group.dates.min()), dates_max=int(group.dates.max()),
            signal_max=str(group.signal_max.max())[:10], label_end_max=str(group.label_end_max.max())[:10],
            cutoff=str(group.cutoff.iloc[0]), base_prediction_cutoffs=base_cutoffs,
            residual_scale_semantics="fusion fitting residual on the same time-legal base OOF training table; no second-level fusion cross-fit"))
        need(fusion_rows[-1]["label_end_max"] < fusion_rows[-1]["cutoff"] <= "2026-01-01",
             "FUSION_SAMPLE_DATE_BOUNDARIES_ILLEGAL")
    risk_rows = []
    for stage in ["validation", "final"]:
        path = ROOT / f"risk_artifacts/{stage}/TRAIN_RECEIPT.json"
        receipt = read(path)
        need(receipt["fit_2026_rows"] == 0, "RISK_BOUNDARY_REFIT_2026")
        risk_rows.append(dict(stage=stage, fixed_risk_return_first=receipt["risk_return_first"],
            fixed_risk_return_last=receipt["risk_return_last"], fixed_history_sessions=252,
            feature_conditional_second_moment_rows_each=30000,
            feature_conditional_second_moment_signal_min="2023-01-03",
            feature_conditional_second_moment_signal_max=next(row["train_signal_max"] for row in rows if row["stage"] == stage),
            fit_2026_rows=0, inference_after_cutoff_is_refit=False))
        source_hashes[relative(path)] = sha(path)
    source_hashes[relative(native_path)], source_hashes[relative(fusion_path)] = sha(native_path), sha(fusion_path)
    return dict(native=rows, fusion=fusion_rows, risk=risk_rows,
        dates_describe_actual_training_samples_not_wall_clock=True,
        original_fit_log_status_counts={"PASS": 84, "FAILED": 9},
        final_completion_source="models/TRAIN_RECEIPT.json and 93 structured FIT receipts; 9 saved restoration audits performed no new fit")


def archive_initial_delivery():
    source = ROOT / "report/FINAL_VERIFICATION.json"
    verification = read(source)
    audit_grid(verification)
    manifest_path = ARCHIVE / "MANIFEST.json"
    if manifest_path.exists():
        manifest = read(manifest_path)
        for key, digest in manifest["archive_sha256"].items():
            need(sha(delivery._local(ROOT, key)) == digest, "ARCHIVE_CHANGED:" + key)
        return manifest
    reporting_source = ROOT / "build_delivery.py"
    recorded_source = {key.replace("\\", "/"): value for key, value in verification["source_sha256"].items()}
    need(recorded_source["build_delivery.py"] == sha(reporting_source), "ARCHIVE_MUST_PRECEDE_TEMPLATE_EDIT")
    files = [source, reporting_source]
    for name, digest in verification["output_sha256"].items():
        path = ROOT / "report" / name
        need(sha(path) == digest, "ORIGINAL_OUTPUT_CHANGED:" + name)
        if name in {"EXPERIMENT_REPORT.md", "RESULTS.html"}:
            files.append(path)
    for key, digest in verification["scientific_plot_sha256"].items():
        path = delivery._local(ROOT, key)
        need(sha(path) == digest, "ORIGINAL_PLOT_CHANGED:" + key)
        files.append(path)
    archive_hashes = {}
    for path in files:
        target = ARCHIVE / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        need(not target.exists(), "UNEXPECTED_EXISTING_ARCHIVE_FILE:" + relative(target))
        shutil.copyfile(path, target)
        archive_hashes[relative(target)] = sha(target)
        need(archive_hashes[relative(target)] == sha(path), "ARCHIVE_COPY_CHANGED:" + relative(path))
    manifest = dict(status="PASS_PRESERVED_COMPLETE_INITIAL_AUDIT", created_utc=datetime.now(timezone.utc).isoformat(),
        original_verification_sha256=sha(source), original_reporting_source_sha256=sha(reporting_source),
        preserved_complete_accounts=10116, ledger_files_read=0, fit_calls=0, replay_calls=0,
        archive_sha256=archive_hashes,
        unchanged_original_data_outputs={name: digest for name, digest in verification["output_sha256"].items()
                                         if name not in {"EXPERIMENT_REPORT.md", "RESULTS.html"}})
    write(manifest_path, manifest)
    return manifest


def refresh_rendering():
    manifest = read(ARCHIVE / "MANIFEST.json")
    for key, digest in manifest["archive_sha256"].items():
        need(sha(delivery._local(ROOT, key)) == digest, "ARCHIVE_CHANGED:" + key)
    baseline_path = ARCHIVE / "report/FINAL_VERIFICATION.json"
    baseline = read(baseline_path)
    audit_grid(baseline)
    need(sha(baseline_path) == manifest["original_verification_sha256"], "INITIAL_AUDIT_RECEIPT_CHANGED")
    old_tree = ast.parse((ARCHIVE / "build_delivery.py").read_text(encoding="utf-8"))
    new_tree = ast.parse((ROOT / "build_delivery.py").read_text(encoding="utf-8"))
    old_functions = {node.name: ast.dump(node, include_attributes=False) for node in old_tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    new_functions = {node.name: ast.dump(node, include_attributes=False) for node in new_tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    protected = set(old_functions) - {"write_markdown", "write_html", "write_plots", "run"}
    need(all(new_functions.get(name) == old_functions[name] for name in protected),
         "AUDIT_OR_NONRENDER_FUNCTION_CHANGED")
    protected_ast_sha256 = hashlib.sha256(json.dumps({name: old_functions[name] for name in sorted(protected)},
                                                   sort_keys=True).encode("utf-8")).hexdigest()
    for key, digest in baseline["source_sha256"].items():
        if key.replace("\\", "/") != "build_delivery.py":
            need(sha(delivery._local(ROOT, key)) == digest, "VERIFIED_UPSTREAM_CHANGED:" + key)
    for name, digest in manifest["unchanged_original_data_outputs"].items():
        need(sha(ROOT / "report" / name) == digest, "AUDITED_COVERAGE_OR_FAILURE_TABLE_CHANGED:" + name)
    coverage = delivery._csv(ROOT / "report/COMBINATION_COVERAGE_FINAL.csv")
    need(len(coverage) == 10106 and not coverage.duplicated(["year", "strategy_id"]).any()
         and coverage.independent_audit_status.eq("PASS").all(), "CACHED_AUDIT_GRID_CHANGED")
    verification = copy.deepcopy(baseline)
    source_hashes = dict(verification["source_sha256"])
    source_hashes["build_delivery.py"] = sha(ROOT / "build_delivery.py")
    source_hashes[Path(__file__).name] = sha(Path(__file__))
    source_hashes[relative(ARCHIVE / "MANIFEST.json")] = sha(ARCHIVE / "MANIFEST.json")
    source_hashes[relative(baseline_path)] = sha(baseline_path)

    controls = {}
    audits = {(row["year"], row["strategy_id"]): row for row in baseline["path_audits"] if row["control"]}
    for year in delivery.YEARS:
        path = ROOT / f"evaluation_controls_{year}/COMPARISON.csv"
        frame = delivery._csv(path)
        need(len(frame) == 5 and set(frame.strategy_id) == set(delivery.CONTROLS), "CONTROL_GRID_CHANGED")
        frame["year"] = year
        for row in frame.to_dict("records"):
            done_path = path.parent / row["strategy_id"] / "DONE.json"
            need(sha(done_path) == audits[(year, row["strategy_id"])]["source_done_sha256"], "CONTROL_DONE_CHANGED")
            done = read(done_path)
            for key in ["net_return", "max_drawdown", "mean_gross_exposure", "total_fees", "trades", "terminal_nav"]:
                need(delivery._max_error(row.get(key, np.nan), done.get(key, np.nan)) <= 1e-8, "CONTROL_COMPARISON_CHANGED:" + key)
        controls[year] = frame
        source_hashes[relative(path)] = sha(path)
    forecast_info = {}
    for year in delivery.YEARS:
        folder = ROOT / f"diagnostics/forecast_metrics/{year}"
        receipt_path = folder / "RECEIPT.json"
        receipt = read(receipt_path)
        need(receipt["no_parameter_fitting"] and receipt["no_model_selection"]
             and receipt["forecasts_reported"] == 152, "FORECAST_REPORT_RECEIPT_CHANGED")
        source_hashes[relative(receipt_path)] = sha(receipt_path)
        expected_outputs = {key.replace("\\", "/"): value for key, value in receipt["output_sha256"].items()}
        for name in ["FORECAST_METRICS.csv", "NATIVE_PROBABILITY_METRICS.csv", "LABEL_AVAILABILITY.csv"]:
            path = folder / name
            need(sha(path) == expected_outputs[relative(path).replace("\\", "/")], "FORECAST_DIAGNOSTIC_CHANGED:" + name)
            source_hashes[relative(path)] = sha(path)
        forecast_info[year] = dict(metrics=delivery._csv(folder / "FORECAST_METRICS.csv"), receipt=receipt)

    findings_path = ROOT / "diagnostics/COMPARISON_FINDINGS_RECEIPT.json"
    findings = read(findings_path)
    need(findings["status"] == "PASS_COMPLETE_TWO_YEAR_DESCRIPTIVE_INTERPRETATION"
         and findings["fit_calls"] == findings["replay_calls"] == 0
         and findings["model_selection_performed"] is False
         and findings["learning_artifacts_modified"] is False, "INDEPENDENT_FINDINGS_SCOPE_FAILURE")
    for key, digest in {**findings["source_sha256"], **findings["output_sha256"]}.items():
        need(sha(delivery._local(ROOT, key)) == digest, "INDEPENDENT_FINDINGS_SOURCE_CHANGED:" + key)
    for name in ["COMPARISON_FINDINGS.md", "COMPARISON_FINDINGS.json", "COMPARISON_FINDINGS_RECEIPT.json"]:
        path = ROOT / "diagnostics" / name
        source_hashes[relative(path)] = sha(path)
    verification["independent_findings"] = dict(status=findings["status"], receipt=relative(findings_path),
        receipt_sha256=sha(findings_path), source_files_verified=len(findings["source_sha256"]),
        outputs_verified=len(findings["output_sha256"]), fit_calls=0, replay_calls=0)
    table_check_path = ROOT / "diagnostics/FINAL_COMPARISON_TABLE_VERIFICATION.json"
    table_check = read(table_check_path)
    need(table_check["status"] == "PASS_COMPLETE_ANALYSIS_TABLE_COVERAGE"
         and table_check["all_pto_rows"] == 10106 and table_check["all_unique"] is True
         and table_check["model_fit_attempts"] == table_check["replays_rerun"] == 0
         and table_check["independent_full_ledger_audit"] is False
         and table_check["formal_full_pool_certification"] is False, "COMPARISON_TABLE_CHECK_SCOPE_FAILURE")
    for key, digest in table_check["source_sha256"].items():
        need(sha(delivery._local(ROOT, key)) == digest, "COMPARISON_TABLE_SOURCE_CHANGED:" + key)
    for year in delivery.YEARS:
        row = table_check["years"][str(year)]
        need(row["pto_rows"] == 5053 and row["matched_comparison_rows"] == 634
             and row["conditional_fusion_risk_rows"] == 1100
             and row["optimization_vs_budget_rows"] == 4890
             and row["complete_pair_grid"] is True, "COMPARISON_TABLE_GRID_CHANGED")
        need(len(row["factor_metrics"]) == 4 and all(value["rows"] == 4560
             and value["balanced_152x10x3"] is True for value in row["factor_metrics"].values()),
             "COMPARISON_FACTOR_GRID_CHANGED")
    source_hashes[relative(table_check_path)] = sha(table_check_path)
    verification["comparison_table_coverage"] = dict(status=table_check["status"],
        receipt=relative(table_check_path), receipt_sha256=sha(table_check_path),
        source_files_verified=len(table_check["source_sha256"]), years=table_check["years"],
        initial_checker_schema_error_retained=table_check["read_only_check_initial_schema_error_retained"],
        added_after_initial_full_audit_source_capture=True,
        independent_full_ledger_audit=False, formal_full_pool_certification=False)
    matrix_path = ROOT / "INPUT_OUTPUT_COMPATIBILITY.csv"
    matrix = delivery._csv(matrix_path)
    need(len(matrix) == 16368 and int(matrix.legal.eq(True).sum()) == 11532
         and len(set(matrix.provider)) == 31
         and set(matrix.fusion) == set(delivery.FUSIONS) | {"identity"},
         "COMPATIBILITY_TYPE_INTERFACE_COUNTS_CHANGED")
    source_hashes[relative(matrix_path)] = sha(matrix_path)
    verification["compatibility_interface_matrix"] = dict(source=relative(matrix_path),
        source_sha256=sha(matrix_path), type_interface_rows=16368, legal_type_interface_cells=11532,
        provider_labels=31, fusion_labels_including_single_identity=12,
        independent_experiment_roster=False, experiment_roster_routes_per_window=5053,
        fixed_member_coalitions=11, forecast_interfaces=152,
        identity_used_for_singletons_only=True, equal_top20_canonical_risk="none")
    learning_path = ROOT / "diagnostics/NO_2026_LEARNING_BOUNDARY_RECHECK.json"
    learning = read(learning_path)
    need(sha(learning_path) == "ae709edc5dbe41b7d8987bf753fa4980bb742fefa1898b5a2f48b2e7139a8fbf"
         and learning["status"] == "PASS_RECORDED_DATE_AND_CALL_BOUNDARIES"
         and not learning["checks_failed"]
         and learning["conclusion"]["recorded_fit_2026_rows"] == 0
         and learning["conclusion"]["both_account_windows_recorded_fit_attempts"] == 0
         and learning["native"]["original_FIT_LOG_status_counts"] == {"PASS": 84, "FAILED": 9}
         and learning["native"]["final_per_bundle_status_counts"] == {"PASS": 93}
         and learning["recheck_actions"]["fit_calls"] == learning["recheck_actions"]["replay_calls"] == 0
         and learning["freeze_evidence"]["GLOBAL_sha256"] == baseline["global_freeze_sha256"],
         "NO_2026_DATE_CALL_BOUNDARY_RECEIPT_CHANGED")
    source_hashes[relative(learning_path)] = sha(learning_path)
    verification["no_2026_learning_boundary_recheck"] = dict(status=learning["status"],
        receipt=relative(learning_path), receipt_sha256=sha(learning_path),
        conclusion=learning["conclusion"], original_fit_log_status_counts={"PASS": 84, "FAILED": 9},
        targeted_receipt_only=True, full_freeze_hash_scan_rerun=False,
        added_after_initial_full_audit_source_capture=True)
    for path in [ROOT / "diagnostics/DELIVERY_THREAD_AUDIT_HISTORY.json",
                 ROOT / "diagnostics/DELIVERY_THREAD_AUDIT_STDOUT.jsonl",
                 ROOT / "DIMENSION_ANALYSIS_INTERPRETATION.md"]:
        source_hashes[relative(path)] = sha(path)
    doc_revision_path = ROOT / "diagnostics/DELIVERY_DOC_PRESENTATION_REVISION.json"
    doc_revision = read(doc_revision_path)
    need(doc_revision["status"] == "PRESENTATION_SCOPE_CLARIFICATION_ONLY"
         and doc_revision["learning_or_execution_source_changed"] is False
         and doc_revision["fit_calls"] == doc_revision["replay_calls"] == doc_revision["ledger_files_read"] == 0
         and sha(delivery._local(ROOT, doc_revision["original_document"])) == doc_revision["original_sha256"]
         and sha(delivery._local(ROOT, doc_revision["current_document"])) == doc_revision["current_sha256"],
         "INTERPRETATION_DOC_PRESENTATION_HISTORY_CHANGED")
    source_hashes[relative(doc_revision_path)] = sha(doc_revision_path)
    source_hashes[doc_revision["original_document"]] = doc_revision["original_sha256"]
    verification["interpretation_document_presentation_revision"] = doc_revision
    history = read(ROOT / "diagnostics/DELIVERY_THREAD_AUDIT_HISTORY.json")
    need(history["status"] == "PASS_COMPLETE_FULL_AUDIT" and history["exit_code"] == 0
         and history["completed_account_audits"] == 10116
         and history["audit_source_sha256"] == manifest["original_reporting_source_sha256"]
         and history["original_final_verification_sha256"] == manifest["original_verification_sha256"]
         and history["observed_stdout_sha256"] == sha(ROOT / "diagnostics/DELIVERY_THREAD_AUDIT_STDOUT.jsonl")
         and history["parallel_executor_switch_performed"] is False, "ORIGINAL_RUN_TERMINAL_HISTORY_CHANGED")
    verification["original_full_audit_run_history"] = dict(status=history["status"],
        receipt="diagnostics/DELIVERY_THREAD_AUDIT_HISTORY.json", session_id=44136, exit_code=0,
        elapsed_seconds=history["elapsed_seconds"], original_source_sha256=history["audit_source_sha256"],
        switched_executor=False, complete_accounts=10116)
    verification["evaluation_windows"] = delivery.evaluation_window_metadata()
    verification["descriptive_complete_route_extrema"] = delivery.descriptive_route_extrema(coverage)
    freeze = read(ROOT / "GLOBAL_FREEZE.json")
    for year in delivery.YEARS:
        for name in ["calendar.parquet", "features.parquet"]:
            path = ROOT / f"input/eval_{year}/{name}"
            key = relative(path).replace("\\", "/")
            need(sha(path) == freeze["artifact_sha256"][key], "WINDOW_METADATA_INPUT_CHANGED")
            source_hashes[relative(path)] = sha(path)
    verification["source_sha256"] = source_hashes
    verification["training_sample_boundaries"] = training_boundary_tables(source_hashes)
    verification["report_refreshed_utc"] = datetime.now(timezone.utc).isoformat()
    verification["rendering_revision"] = dict(status="PRESENTATION_ONLY_FROM_PRESERVED_FULL_AUDIT",
        initial_audit_archive=relative(baseline_path), initial_audit_sha256=sha(baseline_path),
        initial_reporting_source_sha256=manifest["original_reporting_source_sha256"],
        current_reporting_source_sha256=sha(ROOT / "build_delivery.py"), renderer=Path(__file__).name,
        renderer_sha256=sha(Path(__file__)), reused_account_audits=10116, ledger_files_read=0,
        protected_original_functions_ast_identical=True,
        protected_original_function_count=len(protected), protected_original_functions_ast_sha256=protected_ast_sha256,
        control_done_records_rechecked=10, fit_calls=0, replay_calls=0, combinations_added=0,
        changes=["explicit shared-quarter 13F eligibility and legacy mapping denominator",
                 "actual NAV date windows and unequal window lengths",
                 "descriptive full-route extrema with stable ID tie rule",
                 "independent findings receipt and source links",
                 "total-dataset control count wording in filtered HTML",
                 "actual date windows in scientific plot titles"])
    plot_paths = delivery.write_plots(coverage, windows=verification["evaluation_windows"])
    verification["scientific_plot_sha256"] = {relative(path): sha(path) for path in plot_paths}
    delivery.write_markdown(coverage, controls, verification["actual_training"],
        delivery._csv(ROOT / "report/FAILURE_AND_INCOMPATIBILITY.csv"), verification,
        forecast_info, read(ROOT / "INPUT_AUDIT.json"), read(ROOT / "EXPOSURE_HISTORY.json"))
    delivery.write_html(coverage, controls, verification)
    for key, digest in source_hashes.items():
        need(sha(delivery._local(ROOT, key)) == digest, "SOURCE_CHANGED_DURING_RENDER:" + key)
    verification["output_sha256"] = {name: sha(ROOT / "report" / name) for name in baseline["output_sha256"]}
    write(ROOT / "report/FINAL_VERIFICATION.json", verification)
    receipt = dict(status="PASS_PRESENTATION_REFRESH_FROM_COMPLETE_AUDIT", created_utc=datetime.now(timezone.utc).isoformat(),
        original_verification_sha256=sha(baseline_path), final_verification_sha256=sha(ROOT / "report/FINAL_VERIFICATION.json"),
        ledger_files_read=0, fit_calls=0, replay_calls=0, reused_account_audits=10116,
        source_sha256=source_hashes, output_sha256=verification["output_sha256"],
        scientific_plot_sha256=verification["scientific_plot_sha256"], rendering_revision=verification["rendering_revision"])
    write(ROOT / "diagnostics/DELIVERY_REPORT_REFRESH_RECEIPT.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="store_true")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    need(args.archive != args.render, "CHOOSE_ARCHIVE_OR_RENDER")
    result = archive_initial_delivery() if args.archive else refresh_rendering()
    print(json.dumps(clean({key: result[key] for key in ["status", "ledger_files_read", "fit_calls", "replay_calls"]}), ensure_ascii=False))
