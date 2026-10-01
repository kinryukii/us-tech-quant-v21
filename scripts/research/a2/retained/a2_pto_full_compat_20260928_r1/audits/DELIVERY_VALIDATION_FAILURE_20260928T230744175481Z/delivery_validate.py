"""Read-only verification of the completed, real local delivery.

Run only after full analysis, all-17 visual QA, completion verification and report
construction. This file imports no experiment module and calls no learning,
optimization, replay, strategy creation or model-selection code. Its only write
is ROOT/DELIVERY_VALIDATION.json, including on failure.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.dont_write_bytecode = True

YEARS = [2025, 2026]
METRICS = ["indicative_return", "indicative_max_drawdown", "mean_gross_exposure", "mean_cash", "fees", "half_turnover", "uncertified_days"]
INTERACTION_METRICS = ["indicative_return", "indicative_max_drawdown", "mean_gross_exposure", "fees"]
STATUS = "COMPLETE_REGISTERED_DIAGNOSTICS_FORMAL_FULL_POOL_BLOCKED_DATA"
ZERO = 1e-12


class DeliveryFailure(RuntimeError):
    pass


def require(condition, reason):
    if not bool(condition):
        raise DeliveryFailure(reason)


def digest(path):
    with Path(path).open("rb") as handle:
        result = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
        return result.hexdigest()


def finite(series):
    def valid(value):
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False
    return series.map(valid)


def number(value, percent=False):
    if value is None or not math.isfinite(float(value)):
        return "缺失"
    return f"{100 * float(value):.2f}%" if percent else f"{float(value):.3f}"


def scalar(value):
    return value.item() if hasattr(value, "item") else value


def safe_constant(node, definitions):
    """Read the frozen enum declarations without importing their module."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return definitions[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [safe_constant(value, definitions) for value in node.elts]
        return values if isinstance(node, ast.List) else tuple(values)
    if isinstance(node, ast.Dict):
        return {safe_constant(key, definitions): safe_constant(value, definitions) for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return safe_constant(node.left, definitions) + safe_constant(node.right, definitions)
    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Slice):
            component = lambda value: None if value is None else safe_constant(value, definitions)
            index = slice(component(node.slice.lower), component(node.slice.upper), component(node.slice.step))
        else:
            index = safe_constant(node.slice, definitions)
        return safe_constant(node.value, definitions)[index]
    raise ValueError("Non-literal enum expression")


def same_value(actual, expected, location="value"):
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), "SUMMARY_SCHEMA_CHANGED:" + location)
        for key in expected:
            same_value(actual[key], expected[key], location + "/" + str(key))
    elif expected is None:
        require(actual is None, "SUMMARY_MISSINGNESS_CHANGED:" + location)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        require(isinstance(actual, (int, float)) and not isinstance(actual, bool), "SUMMARY_NUMBER_MISSING:" + location)
        if math.isnan(float(expected)):
            require(math.isnan(float(actual)), "SUMMARY_MISSINGNESS_CHANGED:" + location)
        else:
            require(math.isclose(float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-12), "SUMMARY_NUMBER_CHANGED:" + location)
    else:
        require(actual == expected, "SUMMARY_VALUE_CHANGED:" + location)


def records_by_keys(records, keys):
    output = {}
    for record in records:
        key = tuple(str(record[column]) for column in keys)
        require(key not in output, "DUPLICATE_SUMMARY_KEY:" + str(key))
        output[key] = record
    return output


def stats(series, pd):
    values = series.loc[finite(series)].astype(float)
    result = {"total_pairs": len(series), "finite_pairs": len(values), "missing_pairs": len(series) - len(values)}
    names = ["median_delta", "mean_delta", "q25_delta", "q75_delta", "positive_fraction", "negative_fraction", "tie_fraction"]
    if len(values):
        result.update(median_delta=float(values.median()), mean_delta=float(values.mean()),
                      q25_delta=float(values.quantile(.25)), q75_delta=float(values.quantile(.75)),
                      positive_fraction=float(values.gt(ZERO).mean()), negative_fraction=float(values.lt(-ZERO).mean()),
                      tie_fraction=float(values.abs().le(ZERO).mean()))
    else:
        result.update({name: None for name in names})
    return result


def summaries(frame, groups, pd, prefix="delta_", metrics=METRICS):
    output = []
    for key, group in frame.groupby(groups, sort=False, dropna=False):
        values = key if isinstance(key, tuple) else (key,)
        row = {column: scalar(value) for column, value in zip(groups, values)}
        row["metrics"] = {metric: stats(group[prefix + metric], pd) for metric in metrics}
        row["return_win_fraction"] = row["metrics"]["indicative_return"]["positive_fraction"]
        row["return_negative_fraction"] = row["metrics"]["indicative_return"]["negative_fraction"]
        output.append(row)
    return output


def markdown_tables(text):
    lines = text.splitlines()
    output = []
    for index, line in enumerate(lines[:-1]):
        if not line.strip().startswith("|") or not re.fullmatch(r"[\s|:\-]+", lines[index + 1]):
            continue
        cells = lambda row: [cell.strip() for cell in row.strip().strip("|").split("|")]
        headers = cells(line)
        rows = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            values = cells(lines[cursor])
            require(len(values) == len(headers), "MALFORMED_MARKDOWN_TABLE")
            rows.append(dict(zip(headers, values)))
            cursor += 1
        output.append((headers, rows))
    return output


def expected_display(frame):
    return [{column: str(scalar(value)).replace("|", " / ").replace("\n", " ") for column, value in zip(frame.columns, row)}
            for row in frame.itertuples(index=False, name=None)]


def compare_markdown(text, expected, reason):
    matching = [rows for headers, rows in markdown_tables(text) if headers == list(expected.columns)]
    require(len(matching) == 1, "REPORT_TABLE_MISSING_OR_DUPLICATE:" + reason)
    require(matching[0] == expected_display(expected), "REPORT_TABLE_SOURCE_MISMATCH:" + reason)
    return len(matching[0])


def markdown_destinations(text):
    """Handle image/inline/reference links, including parentheses and titles."""
    text = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1\s*$", "", text)
    destinations = []
    for match in re.finditer(r"!?\[[^\]\n]*\]\(", text):
        start = match.end()
        depth, cursor = 1, start
        while cursor < len(text) and depth:
            char = text[cursor]
            if char == "\\" and cursor + 1 < len(text) and text[cursor + 1] in "()":
                cursor += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            cursor += 1
        require(depth == 0, "UNTERMINATED_MARKDOWN_LINK")
        destinations.append(text[start:cursor - 1].strip())
    for match in re.finditer(r"(?m)^\s*\[[^\]]+\]:\s*(.+)$", text):
        destinations.append(match.group(1).strip())
    output = []
    for value in destinations:
        if value.startswith("<"):
            close = value.find(">")
            require(close >= 0, "UNTERMINATED_MARKDOWN_DESTINATION")
            value = value[1:close]
        else:
            value = re.sub(r"\s+[\"'].*[\"']\s*$", "", value)
        output.append(value.replace("\\(", "(").replace("\\)", ")"))
    return output


class Validator:
    def __init__(self, root):
        self.root = root.resolve()
        self.out = self.root / "analysis"
        self.sources = {}
        self.producers = {}
        self.outputs = {}
        self.checks = []
        self.gates = {}
        self.schema = {}
        self.arithmetic_checks = []
        self.arithmetic_negative_cases = {}
        self.validator_failures = []
        self.pd = None

    def relative(self, path):
        path = Path(path).resolve()
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def path(self, value, base=None):
        path = Path(value)
        return path if path.is_absolute() else (base or self.root) / path

    def bind(self, path, expected=None, category="source"):
        path = self.path(path)
        require(path.is_file(), "REQUIRED_REAL_FILE_MISSING:" + self.relative(path))
        actual = digest(path)
        if expected is not None:
            require(isinstance(expected, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected), "INVALID_SHA256:" + self.relative(path))
            require(actual == expected.lower(), "SHA256_BINDING_FAILED:" + self.relative(path))
        key = self.relative(path)
        require(key not in self.sources or self.sources[key] == actual, "INPUT_CHANGED_DURING_VALIDATION:" + key)
        self.sources[key] = actual
        if category == "producer":
            self.producers[key] = actual
        if category == "output":
            self.outputs[key] = actual
        return path

    def read_json(self, name, gate=False):
        path = self.bind(name)
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        require(isinstance(value, dict), "RECEIPT_NOT_OBJECT:" + name)
        if gate:
            self.gates[name] = {key: value[key] for key in ["status", "complete", "rows", "expected_rows", "figure_count", "inspected_png_count"] if key in value}
        return value

    def read_csv(self, name):
        path = self.bind(self.out / name)
        table = self.pd.read_csv(path, low_memory=False)
        self.schema[name] = {"rows": len(table), "columns": list(table.columns)}
        return table

    def bind_map(self, receipt, field, base=None):
        mapping = receipt.get(field)
        if mapping is None:
            return
        require(isinstance(mapping, dict), "SHA_MANIFEST_NOT_OBJECT:" + field)
        for name, expected in mapping.items():
            self.bind(self.path(name, base), expected)

    def check(self, name, function):
        details = function()
        result = {"name": name, "status": "PASS"}
        if details is not None:
            result["details"] = details
        self.checks.append(result)
        print(json.dumps({"delivery_check": name, "status": "PASS"}, ensure_ascii=False), flush=True)

    def enums(self):
        path = self.bind("common.py", category="producer")
        definitions = {}
        for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
            if isinstance(node, ast.Assign):
                try:
                    value = safe_constant(node.value, definitions)
                except (KeyError, ValueError, TypeError):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        definitions[target.id] = value
        needed = ["POINT", "MEMBERS", "BUNDLES", "FUSIONS", "RISKS", "OPTIMIZERS", "AXES"]
        require(all(name in definitions for name in needed), "FROZEN_METHOD_ENUM_SCHEMA_UNSUPPORTED")
        self.constants = {name: definitions[name] for name in needed}
        self.axes = self.constants["AXES"]
        require(len(self.constants["MEMBERS"]) == 31 and len(self.constants["POINT"]) == 13 and len(self.constants["BUNDLES"]) == 4,
                "FIXED_PREDICTION_METHOD_COUNTS_CHANGED")
        require(len(self.constants["FUSIONS"]) == 11 and len(self.constants["RISKS"]) == 12 and len(self.constants["OPTIMIZERS"]) == 3 and len(self.axes) == 4,
                "FIXED_LAYER_METHOD_COUNTS_CHANGED")
        for name in ["build_report.py", "verify_completion.py", "figures.py", "analyze.py", "target_expert_analysis.py", "solver_quality_analysis.py"]:
            self.bind(name, category="producer")
        candidates = [self.root / "analyze_dimensions.py", self.root / "dimension_reports.py"]
        candidates = [path for path in candidates if path.is_file()]
        require(len(candidates) >= 1, "DIMENSION_REPORT_PRODUCER_MISSING")
        chosen = next((path for path in candidates if "COMPARISON_" in path.read_text(encoding="utf-8-sig")), None)
        require(chosen is not None, "DIMENSION_REPORT_PRODUCER_SCHEMA_UNSUPPORTED")
        self.dimension_producer = chosen
        self.bind(chosen, category="producer")

    def prerequisites(self):
        self.completion = self.read_json("COMPLETION.json", gate=True)
        self.delivery = self.read_json("DELIVERY_RECEIPT.json", gate=True)
        self.analysis = self.read_json("analysis/ANALYSIS_RECEIPT.json", gate=True)
        self.effects = self.read_json("analysis/EFFECTS_SUMMARY.json", gate=True)
        self.visual = self.read_json("analysis/FIGURE_VISUAL_QA.json", gate=True)
        self.quality = self.read_json("analysis/SOLVER_QUALITY_RECEIPT.json", gate=True)
        self.target = self.read_json("analysis/TARGET_FUSION_DECISION_RECEIPT.json", gate=True)
        self.independent = self.read_json("INDEPENDENT_VERIFICATION.json", gate=True)
        self.rl_verification = self.read_json("audits/RL_EVALUATION_VERIFICATION.json", gate=True)
        require(self.completion.get("status") == self.delivery.get("status") == STATUS, "COMPLETION_OR_REPORT_GATE_NOT_COMPLETE")
        require(self.analysis.get("complete") is True and self.analysis.get("rows") == self.analysis.get("expected_rows") == 22176,
                "FULL_ANALYSIS_GATE_NOT_COMPLETE")
        require(self.independent.get("status") == "PASS_COMPLETE" and self.independent.get("coverage_complete") is True,
                "INDEPENDENT_GATE_NOT_COMPLETE")
        require(all(self.independent.get("years", {}).get(str(year), {}).get("verified_accounts") == 11088 for year in YEARS), "INDEPENDENT_ACCOUNT_COUNTS")
        require(self.rl_verification.get("status") == "PASS", "RL_GATE_NOT_COMPLETE")
        require(self.effects.get("status") == "COMPLETE_REGISTERED_DESCRIPTIVE_EFFECTS" and self.effects.get("analysis_rows") == self.effects.get("registered_year_strategy_keys") == 22176,
                "EFFECTS_GATE_NOT_COMPLETE")
        require(self.effects.get("figure_count") == 17 and self.effects.get("all_registered_methods_included") is True and self.effects.get("all_figure_text_bounds_checked") is True,
                "ALL_METHOD_FIGURES_GATE_NOT_COMPLETE")
        require(self.visual.get("status") == "PASS_INSPECTED_ALL17" and self.visual.get("inspected_png_count") == 17, "REAL_ALL17_VISUAL_QA_GATE_NOT_COMPLETE")
        require(self.quality.get("complete") is True and self.quality.get("status") == "PASS_ALL22176_STRATEGIES_7488_EXPERTS", "SOLVER_QUALITY_GATE_NOT_COMPLETE")
        require(self.target.get("complete") is True and self.target.get("status") == "COMPLETE_SAME_ACCOUNT_TARGET_CONTRIBUTIONS", "TARGET_EXPERT_GATE_NOT_COMPLETE")
        require(self.completion.get("descriptive_figures") == self.completion.get("production_figures_visually_inspected") == 17, "COMPLETION_VISUAL_QA_COUNT_CHANGED")
        for receipt, producer in [(self.effects, "figures.py"), (self.visual, "figures.py"), (self.quality, "solver_quality_analysis.py"), (self.target, "target_expert_analysis.py")]:
            self.bind(producer, receipt.get("producer_sha256"), category="producer")
        delivery_producer = self.delivery.get("producer_sha256")
        if isinstance(delivery_producer, str):
            self.bind("build_report.py", delivery_producer, category="producer")
        elif isinstance(delivery_producer, dict):
            for name, expected in delivery_producer.items():
                self.bind(name, expected, category="producer")
        self.bind("REGISTRY.json", self.target.get("registry_sha256"))
        self.bind("FREEZE.json", self.target.get("freeze_sha256"))
        for receipt in [self.delivery, self.analysis, self.effects, self.visual, self.quality, self.target]:
            self.bind_map(receipt, "source_sha256")
        self.bind_map(self.quality, "output_sha256", self.out)
        self.bind_map(self.target, "output_sha256", self.out)
        self.bind_map(self.delivery, "output_sha256")
        self.bind_map(self.analysis, "output_sha256", self.out)
        self.bind_map(self.completion, "sealed_summary_sha256")
        self.bind_map(self.completion, "old_source_sha256")
        for name, count in [("actual_pto_accounts", 22176), ("rl_accounts", 8), ("registered_pto_paths_per_window", 11088), ("sealed_pto_batches", 72)]:
            require(self.completion.get(name) == count, "COMPLETION_EXACT_COUNT_CHANGED:" + name)
        require(self.quality.get("all_scanned_batch_policy_counts_close") is True and self.quality.get("all_independent_batch_counts_close") is True,
                "SOLVER_INDEPENDENT_COUNTS_NOT_CLOSED")
        freeze = self.read_json("FREEZE.json")
        self.bind_map(freeze, "artifact_sha256")
        require(self.completion.get("frozen_files_verified") == len(freeze.get("artifact_sha256", {})), "FROZEN_ARTIFACT_COUNT_CHANGED")
        self.freeze = freeze
        self.completion_schema_proof()
        self.validator_failure_evidence()

    def completion_schema_proof(self):
        qa_name = "analysis/COMPLETION_GATE_SCHEMA_QA.json"
        qa = self.read_json(qa_name, gate=True)
        require(qa.get("status") == "PASS_EXACT_DIAGNOSTIC_SCHEMA_WITH_FORMAL_BLOCK_RETAINED"
                and qa.get("actual_frozen_receipt_passed") is True and qa.get("syntax_check_passed") is True
                and qa.get("first_failure_preserved") is True and qa.get("formal_full_pool_status") == "BLOCKED_DATA",
                "CORRECTED_COMPLETION_GATE_SCHEMA_QA_NOT_PASS")
        require(qa.get("producer_sha256") == self.sources["verify_completion.py"], "CORRECTED_COMPLETION_GATE_SCHEMA_QA_PRODUCER_CHANGED")
        self.bind("predictions/base/final/VERIFICATION.json", qa.get("frozen_prediction_receipt_sha256"))
        negatives = qa.get("negative_cases", {})
        expected = {"generic_PASS_rejected", "arbitrary_PASS_prefix_rejected", "formal_full_pool_allowed_rejected",
                    "2026_fit_call_rejected", "2026_learning_update_rejected", "unknown_promotion_rejected",
                    "missing_member_rejected", "wrong_blocked_count_rejected", "fabricated_typed_mu_rejected",
                    "missing_prediction_file_rejected", "wrong_freeze_count_rejected"}
        require(qa.get("negative_case_count") == 11 and set(negatives) == expected
                and all(case.get("rejected") is True and bool(case.get("reason")) for case in negatives.values()),
                "COMPLETION_GATE_ALL11_NEGATIVE_CASES_NOT_REJECTED")
        base = "audits/COMPLETION_SCHEMA_FAILURE_BASE_20260928T2251"
        preserved = self.read_json(base + "/PRESERVATION_RECEIPT.json", gate=True)
        require(preserved.get("status") == "PRESERVED_FIRST_COMPLETION_SCHEMA_FAILURE"
                and preserved.get("failing_check") == "BASE_FINAL_PREDICTION_PROOF"
                and preserved.get("expected_by_old_gate") == "PASS"
                and preserved.get("actual_frozen_status") == "PASS_DIAGNOSTIC_FORMAL_FULL_POOL_BLOCKED"
                and preserved.get("failure_is_gate_schema_mismatch") is True and preserved.get("freeze_or_prediction_outputs_modified") is False,
                "ORIGINAL_COMPLETION_GATE_SCHEMA_FAILURE_NOT_PRESERVED")
        snapshots = preserved.get("snapshot_sha256", {})
        require(set(snapshots) == {"verify_completion.py", "predictions/base/final/VERIFICATION.json"}, "ORIGINAL_COMPLETION_GATE_SCHEMA_SNAPSHOTS_CHANGED")
        for name, expected_sha in snapshots.items():
            self.bind(base + "/" + name, expected_sha)
        require(snapshots["predictions/base/final/VERIFICATION.json"] == self.sources["predictions/base/final/VERIFICATION.json"],
                "FROZEN_PREDICTION_RECEIPT_CHANGED_TO_SATISFY_COMPLETION_GATE")
        require(snapshots["verify_completion.py"] != self.sources["verify_completion.py"], "COMPLETION_GATE_SCHEMA_CORRECTION_NOT_DISTINCT_FROM_FAILED_SOURCE")
        self.gates[qa_name].update({"negative_case_count": 11, "negative_cases": negatives,
                                   "actual_frozen_receipt_passed": True, "producer_sha256": qa["producer_sha256"],
                                   "frozen_prediction_receipt_sha256": qa["frozen_prediction_receipt_sha256"]})

    def validator_failure_evidence(self):
        for folder in sorted((self.root / "audits").glob("DELIVERY_VALIDATION_FAILURE_*")):
            receipt_path = folder / "PRESERVATION_RECEIPT.json"
            if not receipt_path.is_file():
                continue
            receipt = self.read_json(self.relative(receipt_path), gate=True)
            require(receipt.get("production_files_modified") is False, "VALIDATOR_FAILURE_PRESERVATION_CHANGED_PRODUCTION_FILES")
            snapshots = receipt.get("snapshot_sha256", {})
            require(set(snapshots) == {"delivery_validate.py", "DELIVERY_VALIDATION.json"}, "VALIDATOR_FAILURE_SNAPSHOT_SCHEMA_CHANGED")
            for name, expected_sha in snapshots.items():
                self.bind(folder / name, expected_sha)
            old = self.read_json(self.relative(folder / "DELIVERY_VALIDATION.json"))
            require(old.get("status") == "FAIL" and old.get("validator_sha256") == snapshots["delivery_validate.py"],
                    "VALIDATOR_FIRST_FAILURE_NOT_BOUND_TO_ITS_ORIGINAL_SOURCE")
            self.validator_failures.append({"directory": self.relative(folder), "preservation_receipt_sha256": self.sources[self.relative(receipt_path)],
                                            "original_validator_sha256": snapshots["delivery_validate.py"],
                                            "original_validation_sha256": snapshots["DELIVERY_VALIDATION.json"],
                                            "original_failure": old.get("failure")})

    def compatibility_receipts(self):
        """Bind the actual recovery runs, without running their entry point."""
        entry = self.bind("run_pandas_compat.py", category="producer")
        entry_sha = self.sources[self.relative(entry)]
        reviewed_sha = "db78d107425d19ebc8602522385a9b6c30f1afff901a7844b0fc743b0d88b4f1"
        require(entry_sha == reviewed_sha, "COMPAT_INDEPENDENT_REVIEW_SOURCE_BINDING_STALE")
        qa_name = "analysis/PANDAS_COMPAT_QA.json"
        qa = self.read_json(qa_name, gate=True)
        require(qa.get("status") == "PASS_REPRODUCED_ORIGINAL_AXIS_FAILURE_AND_INDEPENDENT_AGGREGATIONS",
                "COMPAT_SMALL_SAMPLE_QA_NOT_PASS")
        require(qa.get("producer_sha256") == entry_sha and qa.get("pandas_version") == "3.0.2", "COMPAT_QA_PRODUCER_OR_RUNTIME_CHANGED")
        require(qa.get("sample_is_synthetic_qa_only_not_production_results") is True and qa.get("independent_checked_group_metric_aggregates") == 60,
                "COMPAT_QA_SCOPE_OR_AGGREGATE_SUPPORT_CHANGED")
        require(qa.get("original_axis_attribute_restored_on_success_and_exception") is True and qa.get("source_frame_and_group_keys_unchanged") is True
                and qa.get("single_metric_median_unchanged") is True and qa.get("unauthorized_script_guard_verified") is True,
                "COMPAT_QA_RESTORATION_OR_SEMANTICS_FAILED")
        require("IndexError" in str(qa.get("baseline_error", "")) and "already selected" in str(qa.get("baseline_error", "")),
                "COMPAT_ORIGINAL_ERROR_NOT_REPRODUCED")
        call_fields = ["fit_calls", "learning_update_calls", "optimization_calls", "replay_dispatches", "selection_or_tuning_calls"]
        require(all(qa.get(field) == 0 for field in call_fields), "COMPAT_QA_FORBIDDEN_CALLS")
        cache_name = "analysis/STREAM_PREDICTION_DIAGNOSTICS_RECEIPT.json"
        cache = self.read_json(cache_name, gate=True)
        require(cache.get("status") == "PASS_ALL150_FROZEN_STREAM_DIAGNOSTICS" and cache.get("analysis_rows") == 150,
                "COMPAT_STREAM_CACHE_NOT_PASS")
        require(len(self.freeze.get("artifact_sha256", {})) == 663 and len(cache.get("source_sha256", {})) == 162
                and len(cache.get("output_sha256", {})) == 2, "COMPAT_EXPECTED663_FROZEN162_CACHE_SOURCES2_OUTPUTS_CHANGED")
        self.bind_map(cache, "source_sha256")
        self.bind_map(cache, "output_sha256", self.out)
        freeze_sha = self.sources["FREEZE.json"]
        cache_sha = self.sources[cache_name]
        qa_sha = self.sources[qa_name]
        first_failure = "audits/PRODUCTION_HANDOFF_ANALYZE_FAILURE_20260928T2130"
        preservation = self.read_json(first_failure + "/PRESERVATION_RECEIPT.json", gate=True)
        require(preservation.get("status") == "PRESERVED_PANDAS_GROUPBY_AXIS_ATTRIBUTE_FAILURE_NO_FROZEN_EDITS",
                "ORIGINAL_STATISTICAL_FAILURE_PRESERVATION_STATUS_CHANGED")
        self.bind_map(preservation, "snapshot_sha256")
        self.bind(first_failure + "/analyze.py", self.sources["analyze.py"])
        primary_outputs = {
            "analyze.py": {"analysis/ANALYSIS_RECEIPT.json"},
            "dimension_reports.py": {f"analysis/COMPARISON_{axis.upper()}.md" for axis in self.axes},
            "figures.py": {"analysis/EFFECTS_SUMMARY.json"},
            "build_report.py": {"REPORT.md", "DELIVERY_RECEIPT.json", "analysis/ALL_STRATEGY_RESULTS.csv",
                                "analysis/LAYER_EFFECT_RANGES.csv", "analysis/SOLVER_QUALITY_SUMMARY.csv"},
        }
        receipt_names = []
        for script, expected_outputs in primary_outputs.items():
            name = "analysis/PANDAS_COMPAT_" + Path(script).stem + "_RECEIPT.json"
            receipt = self.read_json(name, gate=True)
            require(receipt.get("status") == "PASS_PANDAS_ROW_AXIS_COMPAT_STATISTICAL_DELIVERY" and receipt.get("script") == script,
                    "COMPAT_RUN_NOT_PASS_FOR_SCRIPT:" + script)
            require(receipt.get("producer_sha256") == entry_sha and receipt.get("script_sha256") == self.sources[script]
                    and receipt.get("qa_sha256") == qa_sha, "COMPAT_RUN_SOURCE_OR_QA_BINDING_CHANGED:" + script)
            require(receipt.get("pandas_version") == "3.0.2" and receipt.get("compatibility") == "process-local GroupBy.axis integer row axis=0",
                    "COMPAT_RUN_RUNTIME_OR_SEMANTICS_CHANGED:" + script)
            require(receipt.get("original_axis_attribute_restored") is True and receipt.get("original_script_bytes_unchanged") is True,
                    "COMPAT_RUN_RESTORATION_OR_SOURCE_CHANGE:" + script)
            require(all(receipt.get(field) == 0 for field in call_fields), "COMPAT_RUN_FORBIDDEN_CALLS:" + script)
            require(receipt.get("installation", {}).get("installed_axis") == 0, "COMPAT_RUN_INSTALLED_AXIS_NOT_ZERO:" + script)
            before, after = receipt.get("before"), receipt.get("after")
            require(isinstance(before, dict) and before == after, "COMPAT_RUN_BEFORE_AFTER_PROVENANCE_CHANGED:" + script)
            require(before.get("freeze_sha256") == freeze_sha and before.get("frozen_artifacts_verified") == 663
                    and before.get("stream_cache_receipt_sha256") == cache_sha and before.get("stream_cache_sources_verified") == 162
                    and before.get("stream_cache_output_sha256") == cache["output_sha256"], "COMPAT_RUN_FROZEN_OR_CACHE_BINDING_CHANGED:" + script)
            required_sources = {"run_pandas_compat.py", script, qa_name, "FREEZE.json", cache_name,
                                first_failure + "/PRESERVATION_RECEIPT.json", first_failure + "/analyze.py",
                                first_failure + "/FINALIZATION_STATE.json", first_failure + "/finalization.log"}
            require(required_sources.issubset(receipt.get("source_sha256", {})), "COMPAT_RUN_SOURCE_MANIFEST_INCOMPLETE:" + script)
            self.bind_map(receipt, "source_sha256")
            require(set(receipt.get("output_sha256", {})) == expected_outputs, "COMPAT_RUN_PRIMARY_OUTPUT_MANIFEST_CHANGED:" + script)
            for output, expected in receipt["output_sha256"].items():
                self.bind(output, expected, category="output")
            self.bind(name, category="output")
            self.gates[name].update({field: receipt[field] for field in ["script", "producer_sha256", "script_sha256", "qa_sha256", "before", "after",
                                                                         "original_axis_attribute_restored", "original_script_bytes_unchanged"] + call_fields})
            receipt_names.append(name)
        self.compatibility_review = {"status": "PASS_INDEPENDENT_READONLY_COMPAT_REVIEW", "reviewed_source_sha256": reviewed_sha,
                                     "current_source_sha256": entry_sha, "source_binding_current": True,
                                     "reviewed_qa_sha256": "64a6779b38e048f4c1bda8c4c860c710545803b83ab00dbb4526f32592542362",
                                     "independent_sample_rows": 8, "independently_checked_aggregates": 60,
                                     "original_error_reproduced": True, "source_frame_group_keys_and_column_order_unchanged": True,
                                     "successful_exception_and_existing_descriptor_restore_checked": True,
                                     "exact_allowlist_and_path_rejection_checked": True,
                                     "production_results_substituted_with_sample": False, "full_analysis_calls_in_independent_review": 0,
                                     "production_files_written_in_independent_review": 0}
        return {"actual_compatibility_receipts": receipt_names, "independent_review": self.compatibility_review}

    def account_tables(self):
        pd = self.pd
        self.registered = self.read_json("REGISTRY.json")
        strategies = self.registered.get("strategies")
        require(isinstance(strategies, list) and len(strategies) == 11088, "REGISTERED_LIST_NOT_EXACT11088")
        registered = pd.DataFrame(strategies)
        require(not registered.strategy.duplicated().any(), "DUPLICATE_REGISTERED_STRATEGY")
        registered["members"] = registered.members.map(lambda value: "|".join(value))
        self.registered_frame = registered
        self.table = self.read_csv("ALL_POSITIVE_NEGATIVE_RESULTS.csv")
        self.rl = self.read_csv("RL_RESULTS.csv")
        self.all_results = self.read_csv("ALL_STRATEGY_RESULTS.csv")
        self.coverage = self.read_csv("COMBINATION_COVERAGE.csv")
        self.formal = self.read_csv("FORMAL_FULL_POOL_COVERAGE.csv")
        expected = {(year, strategy) for year in YEARS for strategy in registered.strategy}
        for label, frame in [("all PTO", self.table), ("coverage", self.coverage)]:
            require(len(frame) == 22176 and not frame.duplicated(["year", "strategy"]).any(), "PTO_TABLE_COUNT_OR_DUPLICATE:" + label)
            require(set(zip(frame.year, frame.strategy)) == expected, "REGISTERED_YEAR_STRATEGY_KEYS_CHANGED:" + label)
        dimensions = ["stream", "bundle", "fusion", "risk", "optimizer", "axis", "target_fusion", "members"]
        merged = self.table.merge(registered[["strategy"] + dimensions], on="strategy", validate="many_to_one", suffixes=("", "_fixed"))
        for column in dimensions:
            require(merged[column].astype(str).eq(merged[column + "_fixed"].astype(str)).all(), "REGISTERED_DIMENSION_CHANGED:" + column)
        require(all(finite(self.table[metric]).all() for metric in METRICS), "PTO_PRIMARY_METRIC_NOT_FINITE")
        require(not self.coverage.status.isin(["NOT_EXECUTED", "FAILED"]).any(), "REGISTERED_PATH_UNFINISHED")
        self.core = self.table.loc[self.table.target_fusion.eq("none")]
        self.targets = self.table.loc[self.table.target_fusion.ne("none")]
        require(len(self.core) == 21600 and len(self.targets) == 576, "REGISTERED_CORE_TARGET_SPLIT_CHANGED")
        for year in YEARS:
            for axis in self.axes:
                group = self.table.loc[self.table.year.eq(year) & self.table.axis.eq(axis)]
                require(len(group) == 2772, "YEAR_AXIS_SUPPORT_CHANGED")
                require(set(group.loc[group.target_fusion.eq("none"), "stream"]) == {row["stream"] for row in self.registered["streams"]}, "PREDICTION_STREAM_COVERAGE_CHANGED")
                for name, column in [("RISKS", "risk"), ("OPTIMIZERS", "optimizer")]:
                    require(set(group[column]) == set(self.constants[name]), "FIXED_METHOD_COVERAGE_CHANGED:" + column)
        policies = {"reinforce_updated", "reinforce_zero", "ppo_updated", "ppo_zero"}
        require(len(self.rl) == 8 and not self.rl.duplicated(["year", "policy"]).any() and set(zip(self.rl.year, self.rl.policy)) == {(year, policy) for year in YEARS for policy in policies}, "RL_FIXED_ALL8_COVERAGE_CHANGED")
        rl_registry = self.read_json("RL_REGISTRY.json")
        rl_fixed = pd.DataFrame(rl_registry.get("policies", []))
        require(len(rl_fixed) == 4 and set(rl_fixed.policy) == policies and not rl_fixed.policy.duplicated().any(), "RL_REGISTERED_FIXED_LIST_CHANGED")
        common_columns = [name for name in ["strategy", "policy", "updated", "axis"] if name in rl_fixed.columns]
        rl_joined = self.rl.merge(rl_fixed[common_columns], on="policy", validate="many_to_one", suffixes=("", "_fixed"))
        for name in common_columns:
            if name != "policy":
                require(rl_joined[name].astype(str).eq(rl_joined[name + "_fixed"].astype(str)).all(), "RL_FIXED_METADATA_CHANGED:" + name)
        require(all(finite(self.rl[metric]).all() for metric in METRICS if metric in self.rl), "RL_PRIMARY_METRIC_NOT_FINITE")
        expected_total = pd.concat([self.table.assign(route="PTO"), self.rl.assign(route="RL")], ignore_index=True)
        require(len(self.all_results) == 22184 and set(self.all_results.columns) == set(expected_total.columns), "COMBINED_REAL22184_SCHEMA_CHANGED")
        sort_keys = ["route", "year", "strategy", "policy"]
        actual = self.all_results.sort_values(sort_keys, na_position="last").reset_index(drop=True)[expected_total.columns]
        expected_total = expected_total.sort_values(sort_keys, na_position="last").reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected_total, check_dtype=False, check_exact=False, rtol=1e-12, atol=1e-12)
        for field, value in [("all_strategy_results_rows", 22184), ("layer_effect_ranges_rows", 40), ("solver_quality_summary_rows", 12)]:
            require(self.delivery.get(field) == value, "DELIVERY_RECEIPT_COUNT_CHANGED:" + field)
        for name, field in [("REPORT.md", "report_sha256"), ("analysis/ALL_STRATEGY_RESULTS.csv", "all_strategy_results_sha256"),
                            ("analysis/LAYER_EFFECT_RANGES.csv", "layer_effect_ranges_sha256"), ("analysis/SOLVER_QUALITY_SUMMARY.csv", "solver_quality_summary_sha256")]:
            self.bind(name, self.delivery.get(field), category="output")

    def contrasts_and_effects(self):
        pd = self.pd
        specifications = {
            "prediction_stream": ("PREDICTOR_PAIRED_CONTRASTS.csv", self.core, ["year", "axis", "stream"], "ridge"),
            "fusion": ("FUSION_PAIRED_CONTRASTS.csv", self.core.loc[self.core.bundle.ne("singleton")], ["year", "axis", "bundle", "fusion"], "equal within identical bundle"),
            "risk": ("RISK_PAIRED_CONTRASTS.csv", self.table, ["year", "axis", "risk"], "diagonal"),
            "optimizer": ("OPTIMIZER_PAIRED_CONTRASTS.csv", self.table, ["year", "axis", "optimizer"], "mean_variance"),
            "target_fusion": ("TARGET_FUSION_PAIRED_CONTRASTS.csv", self.targets, ["year", "axis", "target_fusion"], "target_equal"),
            "component_axis": ("BUY_SELL_CASH_PAIRED_CONTRASTS.csv", self.table, ["year", "axis"], "joint"),
        }
        self.contrasts = {}
        coordinate = ["year", "stream", "risk", "optimizer", "axis", "target_fusion"]
        reference_source = self.table[coordinate + METRICS].rename(columns={metric: "source_reference_" + metric for metric in METRICS})
        require(not reference_source.duplicated(coordinate).any(), "ACCOUNT_COORDINATES_NOT_UNIQUE")
        require(set(self.effects.get("paired_effects", {})) == set(specifications) | {"prediction_singleton"}, "EFFECT_LAYER_KEYS_CHANGED")
        for layer, (name, expected, groups, reference_label) in specifications.items():
            frame = self.read_csv(name)
            require(len(frame) == len(expected) and not frame.duplicated(["year", "strategy"]).any() and set(zip(frame.year, frame.strategy)) == set(zip(expected.year, expected.strategy)), "PAIRED_EXACT_ACCOUNT_KEYS_CHANGED:" + layer)
            require(set(coordinate + ["bundle", "fusion"] + METRICS + ["reference_" + metric for metric in METRICS] + ["delta_" + metric for metric in METRICS]).issubset(frame.columns), "PAIRED_SCHEMA_CHANGED:" + layer)
            joined = frame.merge(expected[["year", "strategy"] + METRICS], on=["year", "strategy"], validate="one_to_one", suffixes=("", "_source"))
            for metric in METRICS:
                self.close_series(joined[metric], joined[metric + "_source"], "PAIRED_TEST_METRIC:" + layer + ":" + metric)
            reference = frame[coordinate].copy()
            if layer == "prediction_stream":
                reference["stream"] = "ridge"
            elif layer == "fusion":
                reference["stream"] = frame.bundle.astype(str) + "__equal"
            elif layer == "risk":
                reference["risk"] = "diagonal"
            elif layer == "optimizer":
                reference["optimizer"] = "mean_variance"
            elif layer == "target_fusion":
                reference["target_fusion"] = "target_equal"
            elif layer == "component_axis":
                reference["axis"] = "joint"
            reference["_source_row"] = range(len(reference))
            reference = reference.merge(reference_source, on=coordinate, how="left", validate="many_to_one").sort_values("_source_row")
            for metric in METRICS:
                self.close_series(frame["reference_" + metric].reset_index(drop=True), reference["source_reference_" + metric].reset_index(drop=True), "PAIRED_REFERENCE_METRIC:" + layer + ":" + metric)
                self.close_delta(frame, metric, "PAIRED_DELTA_ARITHMETIC:" + layer + ":" + metric)
            source_summary = self.effects["paired_effects"][layer]
            require(source_summary.get("reference") == reference_label, "EFFECT_REFERENCE_CHANGED:" + layer)
            actual = records_by_keys(source_summary["records"], groups)
            computed = records_by_keys(summaries(frame, groups, pd), groups)
            same_value(actual, computed, "paired_effects/" + layer)
            self.contrasts[layer] = frame
        single = self.contrasts["prediction_stream"].loc[self.contrasts["prediction_stream"].bundle.eq("singleton")]
        require(set(single.stream) == set(self.constants["MEMBERS"]), "ALL31_SINGLETONS_NOT_RETAINED")
        summary = self.effects["paired_effects"]["prediction_singleton"]
        require(summary.get("reference") == "ridge", "SINGLETON_REFERENCE_CHANGED")
        keys = ["year", "axis", "stream"]
        same_value(records_by_keys(summary["records"], keys), records_by_keys(summaries(single, keys, pd), keys), "paired_effects/prediction_singleton")
        interactions = self.read_csv("LAYER_INTERACTIONS.csv")
        keys = ["year", "axis", "stream", "risk", "optimizer"]
        require(len(interactions) == 21600 and not interactions.duplicated(keys).any() and set(map(tuple, interactions[keys].to_numpy())) == set(map(tuple, self.core[keys].to_numpy())), "ALL21600_INTERACTION_KEYS_CHANGED")
        expected_interactions = {}
        for name in ["prediction_x_risk", "prediction_x_optimizer", "risk_x_optimizer", "prediction_x_risk_x_optimizer"]:
            groups = ["year", "axis", "risk", "optimizer"] if name == "risk_x_optimizer" else ["year", "axis", "stream"]
            expected_interactions[name] = (groups, summaries(interactions, groups, pd, prefix=name + "__", metrics=INTERACTION_METRICS))
        cooperation = self.read_csv("FUSION_LAYER_INTERACTIONS.csv")
        cooperation_keys = ["year", "axis", "bundle", "layer", "method", "risk", "optimizer"]
        forecast = self.contrasts["fusion"].assign(layer="prediction_fusion", method=self.contrasts["fusion"].fusion)
        targets = self.contrasts["target_fusion"].assign(layer="target_fusion", method=self.contrasts["target_fusion"].target_fusion)
        expected_keys = pd.concat([forecast[cooperation_keys], targets[cooperation_keys]], ignore_index=True)
        require(len(cooperation) == 13248 and not cooperation.duplicated(cooperation_keys).any() and set(map(tuple, cooperation[cooperation_keys].to_numpy())) == set(map(tuple, expected_keys.to_numpy())), "ALL_COOPERATION_INTERACTION_KEYS_CHANGED")
        forecast_main = cooperation.loc[cooperation.layer.eq("prediction_fusion")].rename(columns={"method": "fusion"})
        conditional_fusion = self.fusion_interactions_from_pairs(self.contrasts["fusion"], forecast_main)
        for name in ["fusion_x_risk", "fusion_x_optimizer", "fusion_x_risk_x_optimizer"]:
            frame = conditional_fusion
            groups = ["year", "axis", "bundle", "fusion"]
            expected_interactions[name] = (groups, summaries(frame, groups, pd, prefix=name + "__", metrics=INTERACTION_METRICS))
            frame = cooperation.loc[cooperation.layer.eq("target_fusion")]
            groups = ["year", "axis", "method"]
            expected_interactions["target_" + name] = (groups, summaries(frame, groups, pd, prefix=name + "__", metrics=INTERACTION_METRICS))
        require(set(self.effects.get("interaction_effects", {})) == set(expected_interactions), "INTERACTION_SUMMARY_KEYS_CHANGED")
        for name, (groups, records) in expected_interactions.items():
            same_value(records_by_keys(self.effects["interaction_effects"][name], groups), records_by_keys(records, groups), "interaction_effects/" + name)
        self.check_arithmetic_negative_cases()

    def fusion_interactions_from_pairs(self, fusion, main):
        """Rebuild the figure summary's declared order of subtraction.

        Conditional fusion contrasts subtract already paired deltas. The main
        cooperation table uses direct signed account sums; its floating residue
        must not replace the conditional values used for sign fractions.
        """
        columns = [prefix + metric for metric in INTERACTION_METRICS for prefix in ["", "reference_", "delta_"]]
        risk_keys = ["year", "axis", "bundle", "fusion", "optimizer"]
        optimizer_keys = ["year", "axis", "bundle", "fusion", "risk"]
        corner_keys = ["year", "axis", "bundle", "fusion"]
        risk_reference = fusion.loc[fusion.risk.eq("diagonal"), risk_keys + columns]
        optimizer_reference = fusion.loc[fusion.optimizer.eq("mean_variance"), optimizer_keys + columns]
        corner = fusion.loc[fusion.risk.eq("diagonal") & fusion.optimizer.eq("mean_variance"), corner_keys + columns]
        corner = corner.rename(columns={column: column + "_corner" for column in columns})
        result = fusion.merge(risk_reference, on=risk_keys, validate="many_to_one", suffixes=("", "_diag"))
        result = result.merge(optimizer_reference, on=optimizer_keys, validate="many_to_one", suffixes=("", "_mv"))
        result = result.merge(corner, on=corner_keys, validate="many_to_one")
        specs = {"fusion_x_risk": [("", 1), ("_diag", -1)],
                 "fusion_x_optimizer": [("", 1), ("_mv", -1)],
                 "fusion_x_risk_x_optimizer": [("", 1), ("_diag", -1), ("_mv", -1), ("_corner", 1)]}
        bounds = {}
        for name, terms in specs.items():
            for metric in INTERACTION_METRICS:
                column = name + "__" + metric
                result[column] = sum(sign * result["delta_" + metric + suffix] for suffix, sign in terms)
                scale = sum(result[metric + suffix].abs() + result["reference_" + metric + suffix].abs() for suffix, _ in terms)
                bounds[column] = 8 * sys.float_info.epsilon * (scale + 1) + 1e-12
        keys = ["year", "axis", "bundle", "fusion", "risk", "optimizer"]
        main_columns = [name + "__" + metric for name in specs for metric in INTERACTION_METRICS]
        require(len(main) == len(result) == 12672 and not main.duplicated(keys).any(), "CONDITIONAL_FUSION_MAIN_REGISTERED_KEYS_CHANGED")
        result["_row_for_bound"] = range(len(result))
        comparison = result.merge(main[keys + main_columns], on=keys, validate="one_to_one", suffixes=("", "_main"))
        comparison = comparison.sort_values("_row_for_bound").reset_index(drop=True)
        for column in main_columns:
            require(finite(comparison[column]).all() and finite(comparison[column + "_main"]).all(), "CONDITIONAL_FUSION_NONFINITE_SUPPORT:" + column)
            error = (comparison[column] - comparison[column + "_main"]).abs()
            bound = bounds[column].reset_index(drop=True)
            require(error.le(bound).all(), "CONDITIONAL_VS_DIRECT_ACCOUNT_FORMULA_OUTSIDE_FP_BOUND:" + column)
            self.record_arithmetic_error(error, bound, "CONDITIONAL_VS_DIRECT_ACCOUNT_FORMULA:" + column,
                                         column.split("__", 1)[1], "matched source account sums")
        return result

    def close_series(self, actual, expected, location):
        self.pd.testing.assert_series_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False, check_names=False,
                                            check_exact=False, rtol=1e-10, atol=1e-12, obj=location)

    def close_delta(self, frame, metric, location, reference_prefix="reference_", record=True):
        left, reference, recorded = frame[metric], frame[reference_prefix + metric], frame["delta_" + metric]
        require(finite(left).all() and finite(reference).all(), "PAIRED_DELTA_SOURCE_NONFINITE:" + location)
        require(finite(recorded).all(), "PAIRED_DELTA_RECORDED_NONFINITE:" + location)
        recomputed = left - reference
        bound = 8 * sys.float_info.epsilon * (left.abs() + reference.abs() + 1) + 1e-12
        error = (recorded - recomputed).abs()
        require(error.le(bound).all(), "PAIRED_DELTA_ARITHMETIC_OUTSIDE_FP_BOUND:" + location)
        if record:
            self.record_arithmetic_error(error, bound, location, metric, reference_prefix)

    def record_arithmetic_error(self, error, bound, location, metric, reference_prefix):
        maximum_index = error.idxmax()
        self.arithmetic_checks.append({"location": location, "metric": metric, "rows": len(error), "finite_rows": len(error),
                                       "reference_prefix": reference_prefix, "maximum_absolute_error": float(error.max()),
                                       "bound_at_maximum_error": float(bound.loc[maximum_index]), "maximum_row_bound": float(bound.max()),
                                       "maximum_error_to_bound_ratio": float((error / bound).max()), "zero_error_rows": int(error.eq(0).sum()),
                                       "outside_bound_rows": int(error.gt(bound).sum())})

    def check_arithmetic_negative_cases(self):
        source = self.contrasts["risk"]
        sample = source.loc[source.delta_fees.ne(0), ["fees", "reference_fees", "delta_fees"]].iloc[[0]].reset_index(drop=True)
        reference_difference = float(sample.fees.iloc[0] - sample.reference_fees.iloc[0])
        bound = 8 * sys.float_info.epsilon * (abs(float(sample.fees.iloc[0])) + abs(float(sample.reference_fees.iloc[0])) + 1) + 1e-12
        cases = [("delta_outside_source_scaled_bound", "delta_fees", reference_difference + 4 * bound, "PAIRED_DELTA_ARITHMETIC_OUTSIDE_FP_BOUND:"),
                 ("reversed_nonzero_delta_sign", "delta_fees", -reference_difference, "PAIRED_DELTA_ARITHMETIC_OUTSIDE_FP_BOUND:"),
                 ("missing_delta", "delta_fees", math.nan, "PAIRED_DELTA_RECORDED_NONFINITE:"),
                 ("infinite_delta", "delta_fees", math.inf, "PAIRED_DELTA_RECORDED_NONFINITE:"),
                 ("missing_reference_source", "reference_fees", math.nan, "PAIRED_DELTA_SOURCE_NONFINITE:")]
        for name, column, value, expected_reason in cases:
            changed = sample.copy(deep=True)
            changed.loc[0, column] = value
            try:
                self.close_delta(changed, "fees", "NEGATIVE_QA:" + name, record=False)
            except DeliveryFailure as error:
                require(str(error).startswith(expected_reason), "ARITHMETIC_NEGATIVE_CASE_FAILED_FOR_WRONG_REASON:" + name)
                self.arithmetic_negative_cases[name] = {"rejected": True, "reason": str(error)}
            else:
                raise DeliveryFailure("ARITHMETIC_NEGATIVE_CASE_NOT_REJECTED:" + name)

    def ranges(self):
        pd = self.pd
        metrics = ["delta_" + metric for metric in INTERACTION_METRICS]
        specs = [("单成员预测", "prediction_stream", ["stream"], lambda t: t.bundle.eq("singleton") & t.stream.ne("ridge"), 30, 1080),
                 ("同集合预测融合", "fusion", ["bundle", "fusion"], lambda t: t.fusion.ne("equal"), 40, 1440),
                 ("风险", "risk", ["risk"], lambda t: t.risk.ne("diagonal"), 11, 2541),
                 ("优化", "optimizer", ["optimizer"], lambda t: t.optimizer.ne("mean_variance"), 2, 1848),
                 ("目标融合", "target_fusion", ["target_fusion"], lambda t: t.target_fusion.ne("target_equal"), 1, 36)]
        records = []
        for label, layer, dimensions, mask, method_count, support in specs:
            data = self.contrasts[layer]
            for (year, axis), part in data.loc[mask(data)].groupby(["year", "axis"]):
                require(all(finite(part[metric]).all() for metric in metrics), "LAYER_RANGE_FINITE_SUPPORT_CHANGED:" + label)
                medians = part.groupby(dimensions, dropna=False)[metrics].median()
                switching = sum(int(group.delta_indicative_return.gt(ZERO).any() and group.delta_indicative_return.lt(-ZERO).any())
                                for _, group in part.groupby(dimensions, dropna=False))
                require(len(medians) == method_count and len(part) == support, "LAYER_RANGE_FIXED_SUPPORT_CHANGED:" + label)
                interval = lambda metric, percent=True: number(medians[metric].min(), percent) + " 至 " + number(medians[metric].max(), percent)
                records.append({"年份": int(year), "轴": axis, "层": label, "非参照方法数": len(medians), "配对格数": len(part),
                                "各方法收益差中位数范围": interval(metrics[0]), "回撤差中位数范围": interval(metrics[1]),
                                "敞口差中位数范围": interval(metrics[2]), "费用差中位数范围USD": interval(metrics[3], False),
                                "收益符号随搭配变化的方法数": switching})
        expected = pd.DataFrame(records)
        actual = self.read_csv("LAYER_EFFECT_RANGES.csv")
        keys = ["年份", "轴", "层"]
        require(len(actual) == 40 and not actual.duplicated(keys).any() and set(map(tuple, actual[keys].to_numpy())) == {(year, axis, label) for year in YEARS for axis in self.axes for label, *_ in specs}, "EXACT40_LAYER_RANGE_KEYS_CHANGED")
        pd.testing.assert_frame_equal(actual.sort_values(keys).reset_index(drop=True)[expected.columns], expected.sort_values(keys).reset_index(drop=True), check_dtype=False)
        self.layer_ranges = expected

    def solver_summary(self):
        pd = self.pd
        quality = self.read_csv("SOLVER_QUALITY_BY_STRATEGY.csv")
        experts = self.read_csv("SOLVER_QUALITY_BY_TARGET_EXPERT.csv")
        require(len(quality) == 22176 and not quality.duplicated(["year", "strategy"]).any() and set(zip(quality.year, quality.strategy)) == set(zip(self.table.year, self.table.strategy)), "SOLVER_QUALITY_EXACT_PTO_KEYS_CHANGED")
        target_names = set(self.targets.strategy)
        require(len(experts) == 7488 and not experts.duplicated(["year", "target_strategy", "expert_member"]).any() and set(zip(experts.year, experts.target_strategy, experts.expert_member)) == {(year, name, member) for year in YEARS for name in target_names for member in self.constants["POINT"]}, "SOLVER_QUALITY_EXACT_EXPERT_KEYS_CHANGED")
        for frame in [quality, experts]:
            require(frame.observation_status.eq("OBSERVED_COMPLETE_BATCH").all() and frame.counts_are_observed.eq(True).all(), "SOLVER_QUALITY_HAS_UNOBSERVED_ROWS")
        records = []
        ordinary = quality.loc[quality.target_fusion.eq("none")]
        for label, data, prefix in [("普通预测账户", ordinary, "outer"), ("同账户目标专家", experts, "expert")]:
            for (year, optimizer), group in data.groupby(["year", "optimizer"]):
                denominator = int(group[prefix + "_certificate_denominator_records"].sum())
                certified = int(group[prefix + "_certified_status_records"].sum())
                approximate = int(group[prefix + "_approximate_budget_records"].sum())
                counts = group[prefix + "_approximate_residual_finite_records"]
                means = group[prefix + "_approximate_residual_mean"]
                valid = counts.gt(0) & finite(means)
                n = int(counts.loc[valid].sum())
                weighted_mean = float((counts.loc[valid] * means.loc[valid]).sum() / n) if n else math.nan
                maximum = group[prefix + "_approximate_residual_max"].max()
                missing = int(group[[prefix + "_approximate_residual_" + tag + "_records" for tag in ["missing", "nonfinite", "nonnumeric"]]].sum().sum())
                require(denominator > 0 and 0 <= certified + approximate <= denominator, "SOLVER_CERTIFICATE_DENOMINATOR_INVALID")
                records.append({"年份": int(year), "优化": optimizer, "范围": label, "全部源调用分母": denominator,
                                "容差或现金状态比例": certified / denominator, "固定预算近似比例": approximate / denominator,
                                "近似有限残差数": n, "近似残差均值": weighted_mean, "近似残差最大": maximum, "近似缺失或无效残差数": missing})
        expected = pd.DataFrame(records)
        actual = self.read_csv("SOLVER_QUALITY_SUMMARY.csv")
        keys = ["年份", "优化", "范围"]
        require(len(actual) == 12 and not actual.duplicated(keys).any() and set(map(tuple, actual[keys].to_numpy())) == {(year, opt, label) for year in YEARS for opt in self.constants["OPTIMIZERS"] for label in ["普通预测账户", "同账户目标专家"]}, "EXACT12_SOLVER_SUMMARY_KEYS_CHANGED")
        pd.testing.assert_frame_equal(actual.sort_values(keys).reset_index(drop=True)[expected.columns], expected.sort_values(keys).reset_index(drop=True), check_dtype=False, check_exact=False, rtol=1e-12, atol=1e-12)
        self.solver_summary_table = expected

    def boundary_and_scope(self):
        require(self.completion.get("formal_full_pool_status") == self.delivery.get("formal_full_pool_status") == self.effects.get("formal_2026_full_pool_status") == self.analysis.get("formal_2026_full_pool_status") == "BLOCKED_DATA", "FORMAL_FULLPOOL_BOUNDARY_CHANGED")
        require(self.completion.get("blind_test_claim") is False and self.completion.get("shareholder_total_return_certified") is False, "BLIND_OR_TOTAL_RETURN_CERTIFICATION_CLAIM")
        require(self.completion.get("previous_2026_exposure_preserved") is True and self.completion.get("whole_batch_frozen_before_2026_inference") is True, "FROZEN_OBSERVED_HISTORY_BOUNDARY_CHANGED")
        require(self.delivery.get("registered_list_stopped") is True, "FIXED_LIST_STOP_RULE_CHANGED")
        for field in ["fit_calls_on_2026", "added_models_seeds_horizons_weight_searches", "post_evaluation_retraining"]:
            require(self.completion.get(field) == 0, "COMPLETION_SCOPE_CHANGED:" + field)
        require(self.analysis.get("selection_or_retraining_calls") == 0, "ANALYSIS_SCOPE_CHANGED")
        for field in ["training_calls", "new_strategy_calls", "selection_or_tuning_calls"]:
            require(self.effects.get(field) == 0, "EFFECTS_SCOPE_CHANGED:" + field)
        for field in ["fit_calls", "learning_update_calls", "tuning_calls", "optimization_calls", "selection_calls", "performance_ranking_files_read"]:
            require(self.quality.get(field) == 0, "SOLVER_QUALITY_SCOPE_CHANGED:" + field)
        require(self.quality.get("source_policy_or_engine_imported") is False, "SOLVER_QUALITY_ACCOUNT_CODE_IMPORTED")
        for field in ["fit_calls", "new_candidates", "hypothetical_expert_accounts_created"]:
            require(self.target.get(field) == 0, "TARGET_ANALYSIS_SCOPE_CHANGED:" + field)
        streams = self.read_json("analysis/STREAM_PREDICTION_DIAGNOSTICS_RECEIPT.json", gate=True)
        require(streams.get("status") == "PASS_ALL150_FROZEN_STREAM_DIAGNOSTICS" and streams.get("analysis_rows") == 150, "STREAM_DIAGNOSTIC_GATE_NOT_COMPLETE")
        for field in ["fit_calls", "learning_update_calls", "selection_or_tuning_calls", "account_result_files_read"]:
            require(streams.get(field) == 0, "STREAM_DIAGNOSTIC_SCOPE_CHANGED:" + field)
        self.bind_map(streams, "source_sha256")
        self.bind_map(streams, "output_sha256", self.out)
        base_name = "predictions/base/final/VERIFICATION.json"
        base = self.read_json(base_name, gate=True)
        base_status = "PASS_DIAGNOSTIC_FORMAL_FULL_POOL_BLOCKED"
        require(base.get("status") == base_status and base.get("evaluation_scope") == "QUALIFIED_CONTEXT_DIAGNOSTIC",
                "BASE_FINAL_PREDICTION_DIAGNOSTIC_SCOPE_NOT_VERIFIED")
        counts = {"members_verified": 31, "prediction_files_verified": 62, "context_keys_per_member": 62475,
                  "full_candidate_keys_per_member": 111868, "original_unknown_keys_per_member": 47271,
                  "unknown_promoted": 0, "fit_calls": 0, "learning_update_calls": 0,
                  "freeze_hashes_verified_before": 663, "freeze_hashes_verified_after": 663}
        require(all(base.get(field) == expected for field, expected in counts.items()), "BASE_FINAL_PREDICTION_COUNTS_OR_ZERO_UPDATE_BOUNDARY_CHANGED")
        require(base.get("formal_full_pool_selection_allowed") is False and base.get("typed_interfaces_verified") is True
                and base.get("rank_or_quantiles_have_fabricated_mu") is False and base.get("probability_train_amplitude_mapping_verified") is True
                and base.get("raw_quantiles_reordered") is False, "BASE_FINAL_TYPED_INTERFACE_OR_BLOCKED_FULLPOOL_BOUNDARY_CHANGED")
        members = base.get("member_diagnostics", [])
        require(len(members) == 31 and {member.get("member") for member in members} == set(self.constants["MEMBERS"]),
                "BASE_FINAL_ALL31_TYPED_MEMBER_KEYS_CHANGED")
        member_counts = {"context_keys": 62475, "full_keys": 111868, "original_unknown_keys": 47271,
                         "blocked_current_unknown_keys": 47272, "proven_ineligible_keys": 2204,
                         "qualified_full_prediction_keys": 62392, "holding_only_context_keys": 83}
        for member in members:
            name = member["member"]
            require(member.get("status") == base_status and all(member.get(field) == expected for field, expected in member_counts.items()),
                    "BASE_FINAL_MEMBER_DIAGNOSTIC_COVERAGE_CHANGED:" + name)
            if name.startswith("prob_"):
                require(member.get("probability_train_amplitude_mapping_exact") is True, "BASE_FINAL_PROBABILITY_MAPPING_CHANGED:" + name)
            if name.startswith("quant_"):
                require(member.get("raw_quantile_crossing_left_unchanged") is True, "BASE_FINAL_RAW_QUANTILE_OBJECT_CHANGED:" + name)
        outputs = {str(name).replace("\\", "/") for name in base.get("prediction_output_sha256", {})}
        expected_outputs = {"predictions/base/final/" + prefix + member + ".parquet" for member in self.constants["MEMBERS"] for prefix in ["", "fullkeys/"]}
        require(outputs == expected_outputs, "BASE_FINAL_REAL62_PREDICTION_OUTPUT_MANIFEST_CHANGED")
        self.bind_map(base, "prediction_output_sha256")
        self.bind("predictions/base/final/FINAL_PREDICTION_COVERAGE.csv", base.get("coverage_sha256"))
        self.bind("predictions/base/verify_frozen_final.py", base.get("verifier_sha256"), category="producer")
        self.gates[base_name].update({**counts, "evaluation_scope": base["evaluation_scope"],
                                     "formal_full_pool_selection_allowed": False, "typed_interfaces_verified": True})
        stream_name = "predictions/streams/final/FROZEN_FULLKEY_RECEIPT.json"
        stream_gate = self.read_json(stream_name, gate=True)
        require(stream_gate.get("status") == "PASS_ALL75_FROZEN_STREAMS", "FROZEN_PREDICTION_GATE_CHANGED:" + stream_name)
        data_gate = self.read_json("data/TEST_DATA_VERIFICATION.json", gate=True)
        require(str(data_gate.get("status", "")).startswith("PASS"), "FINAL_DATA_VERIFICATION_GATE_CHANGED")
        rl_gate = self.read_json("analysis/RL_ANALYSIS_RECEIPT.json", gate=True)
        require(rl_gate.get("status") == "COMPLETE_ALL8" and rl_gate.get("accounts") == 8 and rl_gate.get("matched_updated_zero_pairs") == 4,
                "RL_ALL8_AND_ALL4_CONTROL_GATE_CHANGED")
        require(all(rl_gate.get(field) == 0 for field in ["fit_calls", "parameter_updates", "new_seeds_or_epochs"]) and rl_gate.get("formal_full_pool_status") == "BLOCKED_DATA", "RL_ANALYSIS_SCOPE_CHANGED")
        paired = self.read_csv("RL_UPDATED_VS_ZERO.csv")
        controls = self.rl.loc[self.rl.updated.eq(False), ["year", "algorithm"] + METRICS].rename(columns={metric: "source_zero_" + metric for metric in METRICS})
        expected_updated = self.rl.loc[self.rl.updated.eq(True)]
        require(len(paired) == 4 and not paired.duplicated(["year", "algorithm"]).any() and set(zip(paired.year, paired.policy)) == set(zip(expected_updated.year, expected_updated.policy)), "RL_ALL4_MATCHED_CONTROL_KEYS_CHANGED")
        joined = paired.merge(controls, on=["year", "algorithm"], validate="one_to_one")
        updated = joined.merge(expected_updated[["year", "policy"] + METRICS], on=["year", "policy"], validate="one_to_one", suffixes=("", "_source"))
        for metric in METRICS:
            self.close_series(updated[metric], updated[metric + "_source"], "RL_UPDATED_SOURCE:" + metric)
            self.close_series(updated["zero_" + metric], updated["source_zero_" + metric], "RL_ZERO_SOURCE:" + metric)
            self.close_delta(updated, metric, "RL_CONTROL_DELTA:" + metric, reference_prefix="zero_")
        formal = self.formal
        require(len(formal) == 11088 and set(formal.strategy) == set(self.registered_frame.strategy) and formal.year.eq(2026).all(), "FORMAL_FULLPOOL_REGISTERED_KEYS_CHANGED")
        require(formal.status.eq("BLOCKED_DATA").all() and formal.current_unknown_security_days.eq(47272).all(), "FORMAL_FULLPOOL_NOT_ALL_BLOCKED_DATA")
        require(self.completion.get("full_2026_candidate_keys") == 111868 and self.completion.get("current_qualified_keys") == 62392 and self.completion.get("current_unknown_keys") == 47272 and self.completion.get("proven_ineligible_keys") == 2204 and self.completion.get("certified_full_pool_signal_days") == 0, "FORMAL_DATA_COUNTS_CHANGED")
        require(self.table.loc[self.table.year.eq(2026), "research_status"].eq("OBSERVED_HISTORY_QUALIFIED_SUBPOOL_DIAGNOSTIC").all(), "2026_OBSERVED_DIAGNOSTIC_LABEL_CHANGED")
        for frame in [self.table, self.rl, self.all_results]:
            for field in ["certified_shareholder_total_return", "selected_for_deployment"]:
                require(field in frame and frame[field].eq(False).all(), "ACCOUNT_BOUNDARY_FLAG_CHANGED:" + field)
        require(self.effects.get("sign_tolerance") == ZERO, "PAIRED_SIGN_TOLERANCE_CHANGED")

    def figures(self):
        # Titles excluded from constrained layout must still be exported on the
        # full canvas. Read the current source declarations; never import it.
        tree = ast.parse((self.root / "figures.py").read_text(encoding="utf-8-sig"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        save_function = functions.get("save_figure")
        require(save_function is not None, "CURRENT_FIGURE_SAVE_PRODUCER_SCHEMA_UNSUPPORTED")
        save_calls = [node for node in ast.walk(save_function) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute) and node.func.attr == "savefig"]
        require(len(save_calls) == 1, "CURRENT_FIGURE_SAVE_CALL_SCHEMA_UNSUPPORTED")
        bbox = [keyword.value for keyword in save_calls[0].keywords if keyword.arg == "bbox_inches"]
        require(not bbox or (len(bbox) == 1 and isinstance(bbox[0], ast.Constant) and bbox[0].value is None),
                "FINAL_FIGURES_STILL_USE_TIGHT_CROP_THAT_CAN_OMIT_GLOBAL_TITLES")
        dpi = None
        for node in ast.walk(functions.get("configure", ast.Module(body=[], type_ignores=[]))):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "savefig.dpi":
                        dpi = ast.literal_eval(value)
                    if isinstance(key, ast.Constant) and key.value == "savefig.bbox":
                        require(isinstance(value, ast.Constant) and value.value is None, "FINAL_FIGURE_GLOBAL_RC_STILL_USES_TIGHT_CROP")
        require(isinstance(dpi, (int, float)) and dpi > 0, "CURRENT_FIGURE_EXPORT_DPI_SCHEMA_UNSUPPORTED")
        canvas_sizes = {}
        for function in ["scatter_accounts", "fusion_heatmaps", "risk_optimizer_heatmaps"]:
            sizes = [keyword.value for node in ast.walk(functions[function]) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute) and node.func.attr == "subplots"
                     for keyword in node.keywords if keyword.arg == "figsize"]
            require(len(sizes) == 1, "CURRENT_FIGURE_CANVAS_SIZE_SCHEMA_UNSUPPORTED:" + function)
            size = ast.literal_eval(sizes[0])
            canvas_sizes[function] = tuple(int(float(inches) * float(dpi)) for inches in size)
        stems = {"all_axes_return_actual_exposure"} | {f"{prefix}_{year}_{axis}" for prefix in ["fusion_effects", "risk_optimizer_effects_interactions"] for year in YEARS for axis in self.axes}
        expected = {f"analysis/figures/{stem}.{suffix}" for stem in stems for suffix in ["png", "pdf"]}
        names = {str(name).replace("\\", "/") for name in self.effects.get("figures", {})}
        require(names == expected, "EFFECTS_EXACT17_PNG_PDF_FILES_CHANGED")
        directory = self.out / "figures"
        require(directory.is_dir(), "REAL_FIGURE_DIRECTORY_MISSING")
        existing = {self.relative(path) for path in directory.iterdir() if path.suffix.lower() in [".png", ".pdf"]}
        require(existing == expected, "FIGURE_DIRECTORY_EXACT_FILES_CHANGED")
        png_names = {f"analysis/figures/{stem}.png" for stem in stems}
        require({str(name).replace("\\", "/") for name in self.visual.get("inspected_png_sha256", {})} == png_names, "VISUAL_QA_EXACT17_PNGS_CHANGED")
        for name, sha256 in self.effects["figures"].items():
            path = self.bind(name, sha256, category="output")
            with path.open("rb") as handle:
                header = handle.read(24)
            if path.suffix == ".png":
                require(header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR", "PRODUCTION_PNG_INVALID:" + name)
                width, height = struct.unpack(">II", header[16:24])
                require(width >= 500 and height >= 400 and path.stat().st_size >= 10000, "PRODUCTION_PNG_PLACEHOLDER_OR_TRUNCATED:" + name)
                function = "scatter_accounts" if path.stem == "all_axes_return_actual_exposure" else "fusion_heatmaps" if path.stem.startswith("fusion_effects_") else "risk_optimizer_heatmaps"
                require((width, height) == canvas_sizes[function], "FINAL_PNG_NOT_EXPORTED_ON_DECLARED_FULL_CANVAS:" + name)
            else:
                require(header.startswith(b"%PDF-") and path.stat().st_size >= 1000, "PRODUCTION_PDF_INVALID:" + name)
        for name, sha256 in self.visual["inspected_png_sha256"].items():
            self.bind(name, sha256, category="output")
        self.expected_pngs = png_names
        self.figure_export = {"bbox_inches_tight_crop_disabled": True, "savefig_dpi": dpi,
                              "actual_png_sizes_match_current_declared_full_canvases": True,
                              "full_canvas_pixel_sizes": {name: list(size) for name, size in canvas_sizes.items()}}
        return self.figure_export

    def visual_failure_preservation(self):
        """Bind both real failed exports and unchanged statistics independently."""
        rounds = [
            ("audits/FIGURE_VISUAL_FAILURE_INITIAL_20260928T2230",
             "FAIL_ACTUAL_VISUAL_TITLE_OVERLAP_AND_FEE_CELL_LABEL_OVERLAP",
             "PRESERVED_FAILED_VISUALS_CLEARED_FOR_LAYOUT_ONLY_RERENDER"),
            ("audits/FIGURE_VISUAL_FAILURE_TIGHT_EXPORT_20260928T2242",
             "FAIL_ACTUAL_VISUAL_GLOBAL_TITLE_EXCLUDED_BY_TIGHT_EXPORT",
             "PRESERVED_FAILED_VISUALS_CLEARED_FOR_FULL_CANVAS_EXPORT"),
        ]
        results = [self.visual_failure_snapshot(base, failure_status, preparation_status)
                   for base, failure_status, preparation_status in rounds]
        require(len({result["unchanged_statistics_sha256"] for result in results}) == 1,
                "TWO_VISUAL_FAILURE_ROUNDS_OR_FINAL_STATS_NOT_IDENTICAL")
        self.visual_rerender = {"status": "PASS_BOTH_VISUAL_FAILURE_ROUNDS_PRESERVED_AND_STATISTICS_UNCHANGED",
                               "failure_rounds_verified": 2, "original_snapshots_verified": 74,
                               "current_producer_sha256": self.sources["figures.py"],
                               "actual_current_all17_visual_QA_receipt": "analysis/FIGURE_VISUAL_QA.json",
                               "unchanged_statistics_sha256": results[0]["unchanged_statistics_sha256"],
                               "failed_originals_used_as_final_figures": False, "rounds": results}
        return self.visual_rerender

    def visual_failure_snapshot(self, base, failure_status, preparation_status):
        failure = self.read_json(base + "/FAILURE_RECEIPT.json", gate=True)
        preparation = self.read_json(base + "/RERENDER_PREPARATION_RECEIPT.json", gate=True)
        require(failure.get("status") == failure_status
                and failure.get("png_count") == failure.get("pdf_count") == 17 and failure.get("all_original_png_pdf_preserved") is True,
                "ORIGINAL_VISUAL_FAILURE_NOT_PRESERVED")
        require(all(failure.get(field) == 0 for field in ["fit_calls", "optimization_calls", "selection_or_tuning_calls", "new_account_replays"]),
                "VISUAL_FAILURE_PRESERVATION_SCOPE_CHANGED")
        require(preparation.get("status") == preparation_status
                and preparation.get("count") == 35 and preparation.get("snapshot_verified") == 37,
                "LAYOUT_RERENDER_PREPARATION_NOT_EXACT35_OUTPUTS37_SNAPSHOTS")
        require(all(preparation.get(field) == 0 for field in ["fit_calls", "optimization_calls", "selection_or_tuning_calls", "account_replays"]),
                "LAYOUT_RERENDER_PREPARATION_SCOPE_CHANGED")
        current_figures = set(self.effects["figures"])
        original_sources = {"figures.py", "analysis/EFFECTS_SUMMARY.json", "analysis/PANDAS_COMPAT_figures_RECEIPT.json"} | current_figures
        require(set(failure.get("source_sha256", {})) == original_sources, "ORIGINAL_VISUAL_FAILURE_SOURCE_MANIFEST_NOT_EXACT37")
        snapshot_paths = {}
        for source in original_sources:
            if source.startswith("analysis/figures/"):
                archived = base + "/figures/" + Path(source).name
            else:
                archived = base + "/" + Path(source).name
            snapshot_paths[source] = archived
        require(set(failure.get("snapshot_sha256", {})) == set(snapshot_paths.values()), "ORIGINAL_VISUAL_FAILURE_SNAPSHOT_MANIFEST_NOT_EXACT37")
        for source, archived in snapshot_paths.items():
            old_sha = failure["source_sha256"][source]
            require(failure["snapshot_sha256"][archived] == old_sha, "ORIGINAL_VISUAL_FAILURE_SOURCE_SNAPSHOT_SHA_MISMATCH:" + source)
            self.bind(archived, old_sha)
        require(set(preparation.get("deleted_outputs", [])) == current_figures | {"analysis/EFFECTS_SUMMARY.json"},
                "LAYOUT_RERENDER_CLEAR_SCOPE_NOT_ONLY_ORIGINAL_STATS_AND_FIGURES")
        old_effects = self.read_json(base + "/EFFECTS_SUMMARY.json")
        old_compat = self.read_json(base + "/PANDAS_COMPAT_figures_RECEIPT.json")
        old_producer = failure["producer_sha256"]
        require(old_effects.get("producer_sha256") == old_producer == failure["source_sha256"]["figures.py"],
                "ORIGINAL_VISUAL_FAILURE_PRODUCER_BINDING_CHANGED")
        require(old_compat.get("status") == "PASS_PANDAS_ROW_AXIS_COMPAT_STATISTICAL_DELIVERY"
                and old_compat.get("script") == "figures.py" and old_compat.get("script_sha256") == old_producer
                and old_compat.get("producer_sha256") == self.sources["run_pandas_compat.py"]
                and old_compat.get("output_sha256", {}).get("analysis/EFFECTS_SUMMARY.json") == failure["source_sha256"]["analysis/EFFECTS_SUMMARY.json"],
                "ORIGINAL_VISUAL_FAILURE_STATISTICAL_RUN_BINDING_CHANGED")
        for source, expected in old_compat.get("source_sha256", {}).items():
            if source == "figures.py":
                self.bind(base + "/figures.py", expected)
            else:
                self.bind(source, expected)
        require(old_effects.get("figures") == {name: failure["source_sha256"][name] for name in current_figures},
                "ORIGINAL_VISUAL_FAILURE_ALL34_FIGURE_BYTES_NOT_BOUND_TO_SUMMARY")
        unchanged = ["analysis_rows", "registered_year_strategy_keys", "expected_rows", "strategy_count_per_year", "years", "axes",
                     "source_sha256", "figure_count", "all_registered_methods_included", "training_calls", "new_strategy_calls",
                     "selection_or_tuning_calls", "formal_2026_full_pool_status", "year_labels", "sign_tolerance", "metric_units",
                     "interpretation", "coverage_status_counts", "paired_effects", "interaction_effects"]
        for field in unchanged:
            require(field in old_effects and old_effects[field] == self.effects.get(field), "LAYOUT_RERENDER_CHANGED_STATISTICS_OR_ANALYSIS_SUPPORT:" + base + ":" + field)
        self.bind_map(old_effects, "source_sha256")
        require(self.effects["producer_sha256"] == self.visual["producer_sha256"] == self.sources["figures.py"]
                and self.sources["figures.py"] != old_producer, "LATEST_VISUAL_QA_NOT_BOUND_TO_LAYOUT_REPAIR_PRODUCER")
        require(self.effects.get("fee_annotation_format") == "USD, three significant digits; k = 1000 USD; CSV and all underlying statistics unchanged",
                "RERENDER_FEE_LABEL_UNITS_OR_FORMAT_NOT_DECLARED")
        statistics_bytes = json.dumps({field: old_effects[field] for field in unchanged}, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False).encode("utf-8")
        return {"status": "PASS_PRESERVED_VISUAL_FAILURE_AND_UNCHANGED_STATISTICS", "preservation_directory": base,
                "preserved_failure_status": failure_status, "preserved_rerender_preparation_status": preparation_status,
                "original_snapshots_verified": 37, "original_png_count": 17, "original_pdf_count": 17,
                "old_producer_sha256": old_producer, "current_producer_sha256": self.sources["figures.py"],
                "unchanged_summary_fields": unchanged, "unchanged_statistics_sha256": hashlib.sha256(statistics_bytes).hexdigest(),
                "actual_current_all17_visual_QA_receipt": "analysis/FIGURE_VISUAL_QA.json", "failed_originals_used_as_final_figures": False}

    def reports(self):
        pd = self.pd
        report_path = self.bind("REPORT.md", category="output")
        self.report_text = report_path.read_text(encoding="utf-8-sig")
        text = self.report_text
        for statement in ["正式完整13F池仍为 BLOCKED_DATA", "不能称盲测", "未认证为股东总收益", "没有新增成员、种子、期限、权重或训练预算", "没有从诊断结果回流训练", "收益最高不代表"]:
            require(statement in text, "REPORT_INTERPRETATION_BOUNDARY_MISSING:" + statement)
        require("22176" in text and "22184" in text and "47272" in text, "REPORT_EXACT_SCOPE_COUNTS_MISSING")
        summary = []
        for (year, axis), group in self.table.groupby(["year", "axis"]):
            values = group.loc[finite(group.indicative_return)]
            record = {"年份": year, "轴": axis, "账户": len(group), "正收益": int(values.indicative_return.gt(0).sum()),
                      "负收益": int(values.indicative_return.lt(0).sum()), "零收益": int(values.indicative_return.eq(0).sum()), "非有限收益": len(group) - len(values),
                      "收益中位数": number(values.indicative_return.median(), True), "平均敞口中位数": number(group.mean_gross_exposure.median(), True), "费用中位数USD": number(group.fees.median())}
            require(record["正收益"] + record["负收益"] + record["零收益"] + record["非有限收益"] == len(group), "ALL_SIGN_RESULTS_DO_NOT_CLOSE")
            summary.append(record)
        compare_markdown(text, pd.DataFrame(summary), "all_positive_negative_zero_accounts")
        # Check the report's existing descriptive maximum claims against source
        # accounts; do not assemble, train, replay or deploy any chosen method.
        winner_headers = ["年份", "轴", "完整组合", "指示收益", "指示最大回撤", "平均敞口", "费用USD", "未认证估值日"]
        matching = [rows for headers, rows in markdown_tables(text) if headers == winner_headers]
        require(len(matching) == 1 and len(matching[0]) == 8, "REPORTED_DESCRIPTIVE_MAXIMUM_TABLE_NOT_EXACT8")
        seen = set()
        for row in matching[0]:
            year, axis, strategy = int(row["年份"]), row["轴"], row["完整组合"]
            require((year, axis) not in seen, "DUPLICATE_REPORTED_YEAR_AXIS")
            seen.add((year, axis))
            group = self.table.loc[self.table.year.eq(year) & self.table.axis.eq(axis)]
            source = group.loc[group.strategy.eq(strategy)]
            require(len(source) == 1, "REPORTED_ACCOUNT_NOT_IN_FIXED_SOURCE")
            source = source.iloc[0]
            require(math.isclose(float(source.indicative_return), float(group.indicative_return.max()), rel_tol=1e-12, abs_tol=1e-12), "REPORTED_DESCRIPTIVE_MAXIMUM_NOT_SOURCE_MAXIMUM")
            expected = {"年份": str(year), "轴": axis, "完整组合": strategy, "指示收益": number(source.indicative_return, True),
                        "指示最大回撤": number(source.indicative_max_drawdown, True), "平均敞口": number(source.mean_gross_exposure, True),
                        "费用USD": number(source.fees), "未认证估值日": str(int(source.uncertified_days))}
            require(row == expected, "REPORTED_DESCRIPTIVE_ACCOUNT_NUMBERS_CHANGED")
        require(seen == {(year, axis) for year in YEARS for axis in self.axes}, "REPORTED_YEAR_AXIS_COVERAGE_CHANGED")
        compare_markdown(text, self.layer_ranges, "all40_layer_ranges")
        solver = self.read_csv("SOLVER_STATUS.csv")
        compare_markdown(text, solver.groupby(["year", "status"], as_index=False).decisions.sum(), "solver_source_status_counts")
        solver_display = self.solver_summary_table.copy()
        for column in ["容差或现金状态比例", "固定预算近似比例"]:
            solver_display[column] = solver_display[column].map(lambda value: number(value, True))
        for column in ["近似残差均值", "近似残差最大"]:
            solver_display[column] = solver_display[column].map(lambda value: "无近似调用" if pd.isna(value) else f"{value:.3g}")
        compare_markdown(text, solver_display, "all12_solver_quality_summary")
        rl_display = self.rl[["year", "policy", "indicative_return", "indicative_max_drawdown", "mean_gross_exposure", "fees"]].copy()
        for metric in ["indicative_return", "indicative_max_drawdown", "mean_gross_exposure"]:
            rl_display[metric] = rl_display[metric].map(lambda value: number(value, True))
        rl_display["fees"] = rl_display.fees.map(number)
        compare_markdown(text, rl_display, "all8_RL_positive_negative_accounts")
        fallbacks = self.read_csv("RISK_FIT_FAILURES_AND_FALLBACKS.csv")
        require(f"失败/基线回退共{len(fallbacks)}条" in text, "REPORT_RISK_FALLBACK_SOURCE_COUNT_CHANGED")
        require(f"冻结{self.completion['frozen_files_verified']}个工件" in text and f"PTO共{self.completion['actual_pto_account_days']}个实际账户日" in text,
                "REPORT_COMPLETION_SOURCE_COUNTS_CHANGED")
        specs = [("prediction_stream", ["stream"], True), ("fusion", ["bundle", "fusion"], False), ("risk", ["risk"], False),
                 ("optimizer", ["optimizer"], False), ("target_fusion", ["target_fusion"], False)]
        self.markdown_starts = [report_path]
        for axis in self.axes:
            path = self.bind(f"analysis/COMPARISON_{axis.upper()}.md", category="output")
            self.markdown_starts.append(path)
            dimension_text = path.read_text(encoding="utf-8-sig")
            parsed = markdown_tables(dimension_text)
            require(len(parsed) == 10, "DIMENSION_REPORT_ALL10_TABLES_MISSING:" + axis)
            position = 0
            for year in YEARS:
                for layer, dimensions, only_members in specs:
                    part = self.contrasts[layer]
                    part = part.loc[part.year.eq(year) & part.axis.eq(axis)]
                    if only_members:
                        part = part.loc[part.stream.isin(self.constants["MEMBERS"])]
                    rows = []
                    metrics = ["delta_" + metric for metric in INTERACTION_METRICS]
                    for key, group in part.groupby(dimensions, sort=True, dropna=False):
                        values = key if isinstance(key, tuple) else (key,)
                        valid = group.loc[finite(group.delta_indicative_return)]
                        supports = [int(finite(group[metric]).sum()) for metric in metrics]
                        rows.append({"方法": " / ".join(str(value) for value in values), "配对格数": len(valid),
                                     "有限支持收益/回撤/敞口/费用": " / ".join(str(n) for n in supports),
                                     "缺失收益/回撤/敞口/费用": " / ".join(str(len(group) - n) for n in supports),
                                     "收益差中位数": number(valid.delta_indicative_return.median(), True),
                                     "收益正/负比例": number(valid.delta_indicative_return.gt(ZERO).mean(), True) + " / " + number(valid.delta_indicative_return.lt(-ZERO).mean(), True),
                                     "回撤差中位数": number(group.loc[finite(group.delta_indicative_max_drawdown), "delta_indicative_max_drawdown"].median(), True),
                                     "敞口差中位数": number(group.loc[finite(group.delta_mean_gross_exposure), "delta_mean_gross_exposure"].median(), True),
                                     "费用差中位数USD": number(group.loc[finite(group.delta_fees), "delta_fees"].median())})
                    expected_frame = pd.DataFrame(rows)
                    require(parsed[position][0] == list(expected_frame.columns) and parsed[position][1] == expected_display(expected_frame), "DIMENSION_REPORT_SOURCE_OR_METHOD_COVERAGE_CHANGED:" + axis + ":" + str(year) + ":" + layer)
                    position += 1
        embedded = set()
        report_local_targets = set()
        for raw in markdown_destinations(text):
            local = self.resolve_markdown_target(raw, report_path)
            if local is not None:
                report_local_targets.add(self.relative(local[0]))
                if local[0].suffix.lower() == ".png":
                    embedded.add(self.relative(local[0]))
        require(embedded == self.expected_pngs, "REPORT_NOT_EMBEDDING_ALL17_REAL_QA_PNGS")
        compatibility_links = {"run_pandas_compat.py", "analysis/PANDAS_COMPAT_QA.json",
                               "audits/PRODUCTION_HANDOFF_ANALYZE_FAILURE_20260928T2130/PRESERVATION_RECEIPT.json"}
        compatibility_links.update("analysis/PANDAS_COMPAT_" + name + "_RECEIPT.json" for name in ["analyze", "dimension_reports", "figures", "build_report"])
        require(compatibility_links.issubset(report_local_targets), "REPORT_ACTUAL_COMPAT_RUN_QA_OR_ORIGINAL_FAILURE_LINKS_MISSING")

    def resolve_markdown_target(self, destination, document):
        destination = unquote(destination.strip())
        if not destination or destination.startswith("#"):
            return None
        windows_drive = bool(re.match(r"^[A-Za-z]:[\\/]", destination))
        if not windows_drive:
            parsed = urlsplit(destination)
            if parsed.scheme and parsed.scheme.lower() != "file":
                return None
            if parsed.scheme.lower() == "file":
                destination = parsed.path
                if re.match(r"^/[A-Za-z]:/", destination):
                    destination = destination[1:]
            else:
                destination = destination.split("#", 1)[0].split("?", 1)[0]
        else:
            destination = destination.split("#", 1)[0]
        # Strip a final editor line suffix only; preserve the Windows drive colon.
        line = None
        match = re.search(r":(\d+)(?::\d+)?$", destination)
        if match:
            line = int(match.group(1))
            destination = destination[:match.start()]
        path = Path(destination)
        if not path.is_absolute():
            path = document.parent / path
        return path.resolve(), line

    def local_links(self):
        starts = list(self.markdown_starts)
        for path in [self.root / "README.md", self.root / "analysis/INTERPRETATION_AND_COMPARISON_AUDIT.md"]:
            if path.is_file():
                starts.append(path)
        workspace_readme = self.root.parent / "README.md"
        if workspace_readme.is_file() and self.root.name in workspace_readme.read_text(encoding="utf-8-sig"):
            starts.append(workspace_readme)
        queue, seen, checked = starts, set(), []
        while queue:
            document = queue.pop()
            document_key = self.relative(document)
            if document_key in seen:
                continue
            seen.add(document_key)
            self.bind(document, category="output")
            content = document.read_text(encoding="utf-8-sig")
            for raw in markdown_destinations(content):
                target = self.resolve_markdown_target(raw, document)
                if target is None:
                    continue
                path, line = target
                require(path.exists(), "UNREADABLE_LOCAL_MARKDOWN_LINK:" + document_key + " -> " + raw)
                if path.is_file():
                    with path.open("rb") as handle:
                        handle.read(1)
                    if line is not None:
                        require(line >= 1, "INVALID_MARKDOWN_LINE_SUFFIX:" + raw)
                        count = len(path.read_text(encoding="utf-8-sig").splitlines())
                        require(line <= count, "MARKDOWN_LINE_SUFFIX_OUT_OF_RANGE:" + raw)
                    if path.suffix.lower() == ".md":
                        queue.append(path)
                else:
                    next(path.iterdir(), None)
                    require(line is None, "DIRECTORY_LINK_HAS_LINE_SUFFIX:" + raw)
                checked.append({"document": document_key, "destination": raw, "resolved": self.relative(path), "line": line})
        self.links = {"documents_checked": sorted(seen), "local_link_count": len(checked), "links": checked}

    def stable_inputs(self):
        for name, expected in self.sources.items():
            require(digest(self.path(name)) == expected, "DELIVERY_INPUT_CHANGED_DURING_VALIDATION:" + name)

    def run(self):
        # Only the pre-existing dataframe dependency is imported. Producer code
        # and frozen artifacts are read and hashed, never imported or executed.
        vendor = self.root / "vendor"
        if vendor.is_dir():
            sys.path.insert(0, str(vendor))
        import pandas as pd
        self.pd = pd
        for name, function in [("producer_and_fixed_method_schema", self.enums), ("completed_full_analysis_and_QA_gates", self.prerequisites),
                               ("all4_actual_statistical_compat_runs_and_independent_review", self.compatibility_receipts),
                               ("exact_actual_PTO22176_RL8_total22184", self.account_tables), ("all_fixed_paired_effect_and_interaction_summaries", self.contrasts_and_effects),
                               ("exact40_layer_effect_ranges", self.ranges), ("exact12_solver_quality_summary", self.solver_summary),
                               ("blocked_fullpool_observed2026_uncertified_return_and_zero_calls", self.boundary_and_scope),
                               ("all17_real_figures_SHA_bound_to_actual_visual_QA", self.figures),
                               ("original_visual_failure_preserved_and_layout_rerender_statistics_unchanged", self.visual_failure_preservation),
                               ("report_and_all4_dimension_numbers_match_sources", self.reports),
                               ("all_local_markdown_links_readable", self.local_links), ("all_delivery_sources_stable_during_validation", self.stable_inputs)]:
            self.check(name, function)

    def receipt(self, status, error=None):
        return {"status": status, "created_utc": datetime.now(timezone.utc).isoformat(), "root": self.root.as_posix(),
                "validator_sha256": digest(Path(__file__)), "validator_only_output": "DELIVERY_VALIDATION.json",
                "read_only_validation": True, "fit_calls": 0, "learning_update_calls": 0, "optimization_calls": 0,
                "selection_calls": 0, "new_account_calls": 0, "new_candidates": 0, "production_modules_imported": False,
                "expected": {"pto_rows": 22176, "rl_rows": 8, "total_rows": 22184, "layer_range_rows": 40, "solver_summary_rows": 12, "png_count": 17},
                "formal_full_pool_status": "BLOCKED_DATA", "blind_test_claim": False, "shareholder_total_return_certified": False,
                "actual_visual_QA_performed_by_this_validator": False, "visual_QA_evidence": "analysis/FIGURE_VISUAL_QA.json",
                "independent_compatibility_review": getattr(self, "compatibility_review", None),
                "visual_failure_and_layout_rerender": getattr(self, "visual_rerender", None),
                "paired_arithmetic_validation": {"tolerance_formula": "8 * binary64 epsilon * (abs(source) + abs(reference) + 1) + 1e-12",
                                                  "binary64_epsilon": sys.float_info.epsilon, "source_scaled_error_checks": self.arithmetic_checks,
                                                  "negative_case_count": len(self.arithmetic_negative_cases), "negative_cases": self.arithmetic_negative_cases},
                "preserved_validator_failures": self.validator_failures,
                "checks": self.checks, "failure": error, "gates": self.gates, "table_schema": self.schema,
                "producer_sha256": self.producers, "source_sha256": self.sources, "output_sha256": self.outputs,
                "markdown_links": getattr(self, "links", {"documents_checked": [], "local_link_count": 0, "links": []})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    validator = Validator(args.root)
    destination = validator.root / "DELIVERY_VALIDATION.json"
    status, error = "PASS", None
    try:
        validator.run()
    except Exception as exc:
        status = "FAIL"
        error = {"type": type(exc).__name__, "reason": str(exc), "next_check_index": len(validator.checks)}
    record = validator.receipt(status, error)
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "passed_checks": len(validator.checks), "failure": error,
                      "receipt": destination.as_posix(), "receipt_sha256": digest(destination)}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
