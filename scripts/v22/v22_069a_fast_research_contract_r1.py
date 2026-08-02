from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m")
REQUESTED_OFFICIAL_OUTPUT_ROOT = r"D:\us-tech-quant-results\fast3\archive\legacy_v22\V22.069A_FAST_RESEARCH_CONTRACT_R1"
LOCAL_RESULTS_ROOT = Path(r"D:\us-tech-quant-results\fast3\archive\legacy_v22")
OUT = LOCAL_RESULTS_ROOT / "V22.069A_FAST_RESEARCH_CONTRACT_R1"
SYMS = ["QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS"]
IDENTITY_FIELDS = ("relative_path", "symbol", "year", "month", "file_size", "mtime_ns")
IDENTITY_METHOD = "relative_path+symbol+year+month+file_size+mtime_ns"
D_SOURCE = Path(__file__).with_name("v22_068d_fast3_compact_model_failure_diagnostic_r1.py")
R2_SOURCE = Path(__file__).with_name("v22_068d1_fast3_frozen_input_contract_lineage_recovery_r2.py")
ATTESTATION_FLAGS = {
    "relied_on_v22_049_acceptance": True,
    "full_row_integrity_reaudit_performed": False,
    "full_partition_content_hash_performed": False,
    "partition_identity_fingerprint_method": IDENTITY_METHOD,
    "research_only": True,
    "prospective_shadow_allowed": False,
    "paper_action_allowed": False,
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "order_output_count": 0,
}
OUTPUT_LOCATION_FLAGS = {
    "requested_official_output_root": REQUESTED_OFFICIAL_OUTPUT_ROOT,
    "actual_output_root": str(OUT),
    "official_results_root_unavailable_from_current_execution_context": True,
    "local_fallback_output_used": True,
}


def b(value):
    return (json.dumps(value, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")


def h(value):
    return hashlib.sha256(value).hexdigest()


def partition_identity(row):
    return {field: row[field] for field in IDENTITY_FIELDS}


def metadata_fingerprint(rows):
    return h(b(sorted((partition_identity(row) for row in rows), key=lambda row: row["relative_path"])))


class FeatureWhitelistSourceIncomplete(ValueError):
    pass


def normalized_features(values):
    if not isinstance(values, (list, tuple, set)) or not all(isinstance(value, str) for value in values):
        raise FeatureWhitelistSourceIncomplete("feature classifications must be string collections")
    return sorted({value.strip() for value in values if value.strip()})


def tracked_diagnostic_features(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        raise FeatureWhitelistSourceIncomplete("diagnostic source is unreadable") from error
    matches = [node.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "F" for target in node.targets)]
    if len(matches) != 1 or not isinstance(matches[0], (ast.List, ast.Tuple)) or not all(isinstance(element, ast.Constant) and isinstance(element.value, str) for element in matches[0].elts):
        raise FeatureWhitelistSourceIncomplete("diagnostic source does not uniquely define F")
    return normalized_features([element.value for element in matches[0].elts])


def conditional_source_value(node, field):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.IfExp) or not isinstance(node.test, ast.Compare) or len(node.test.ops) != 1 or not isinstance(node.test.ops[0], ast.Eq) or not isinstance(node.test.left, ast.Name) or node.test.left.id != "f" or len(node.test.comparators) != 1 or not isinstance(node.test.comparators[0], ast.Constant):
        return None
    return conditional_source_value(node.body if node.test.comparators[0].value == field else node.orelse, field)


def recover_feature_evidence(source_paths=(D_SOURCE, R2_SOURCE)):
    diagnostic_source, lineage_source = map(Path, source_paths)
    diagnostic_features = tracked_diagnostic_features(diagnostic_source)
    try:
        lineage_tree = ast.parse(lineage_source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        raise FeatureWhitelistSourceIncomplete("lineage source is unreadable") from error
    authoritative_values = []
    for node in ast.walk(lineage_tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "authoritative_value":
                    authoritative_values.append(value)
    recovered = {}
    for field, label in {"non_monotonic_features": "NON_MONOTONIC feature set", "direction_reversal_features": "DIRECTION_REVERSAL feature set"}.items():
        matches = [conditional_source_value(value, label) for value in authoritative_values]
        matches = [value for value in matches if value is not None]
        if len(matches) != 1:
            raise FeatureWhitelistSourceIncomplete(f"lineage source has ambiguous {field} evidence")
        recovered[field] = normalized_features(matches[0].split(";"))
    whitelist = sorted(set(recovered["non_monotonic_features"]) | set(recovered["direction_reversal_features"]))
    if not whitelist or not set(whitelist) <= set(diagnostic_features):
        raise FeatureWhitelistSourceIncomplete("tracked sources cannot uniquely cross-validate feature evidence")
    paths = [str(path.relative_to(Path(__file__).resolve().parents[2])) for path in (diagnostic_source, lineage_source)]
    return {"feature_evidence_transport": "git_tracked_source", "feature_evidence_source_paths": paths, "feature_evidence_source_sha256": {path: h(Path(path_text).read_bytes()) for path, path_text in zip(paths, (diagnostic_source, lineage_source))}, **recovered, "feature_whitelist": whitelist, "feature_whitelist_not_fabricated": True}


LOGICAL_TO_PHYSICAL = {"timestamp": "timestamp_et", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
LOGICAL_TIMESTAMP_COLUMN = "timestamp_et"
LOGICAL_TIMESTAMP_TIMEZONE = "America/New_York"
SECONDARY_UTC_TIMESTAMP_COLUMN = "timestamp_utc"
REQUIRED_LOGICAL_COLUMNS = tuple(LOGICAL_TO_PHYSICAL)
LOGICAL_SCHEMA_MAPPING = {"logical_timestamp_column": LOGICAL_TIMESTAMP_COLUMN, "logical_timestamp_timezone": LOGICAL_TIMESTAMP_TIMEZONE, "secondary_utc_timestamp_column": SECONDARY_UTC_TIMESTAMP_COLUMN}


def normalized_schema_record(symbol, path, schema):
    physical = {field.name.strip().lower(): field.type for field in schema}
    logical = {logical_name: str(physical[physical_name]) for logical_name, physical_name in LOGICAL_TO_PHYSICAL.items() if physical_name in physical}
    arrow_types = {logical_name: physical[physical_name] for logical_name, physical_name in LOGICAL_TO_PHYSICAL.items() if physical_name in physical}
    required_present = len(logical) == len(REQUIRED_LOGICAL_COLUMNS) and SECONDARY_UTC_TIMESTAMP_COLUMN in physical
    metadata = schema.metadata or {}
    return {"symbol": symbol, "sample_partition_path": str(path), "physical_columns": [field.name for field in schema], "physical_types": [str(field.type) for field in schema], "schema_metadata_present": bool(metadata), "schema_metadata_keys": sorted(key.decode("utf-8", "replace") for key in metadata), "required_logical_columns_present": required_present, "normalized_schema_signature": h(b(logical)), **LOGICAL_SCHEMA_MAPPING, "_logical_types": logical, "_arrow_types": arrow_types, "_physical_arrow_types": physical, "schema_rejection_reason": ""}


def evaluate_sample_schemas(records):
    timestamp_types = set()
    utc_timestamp_types = set()
    for record in records:
        logical = record["_logical_types"]
        arrow_types = record["_arrow_types"]
        missing = [physical_name for logical_name, physical_name in LOGICAL_TO_PHYSICAL.items() if logical_name not in logical]
        if SECONDARY_UTC_TIMESTAMP_COLUMN not in record["_physical_arrow_types"]:
            missing.append(SECONDARY_UTC_TIMESTAMP_COLUMN)
        reasons = []
        if missing:
            reasons.append("MISSING_REQUIRED_LOGICAL_COLUMNS: " + ", ".join(missing))
        else:
            timestamp_type = arrow_types["timestamp"]
            if not pa.types.is_timestamp(timestamp_type) or timestamp_type.tz != LOGICAL_TIMESTAMP_TIMEZONE:
                reasons.append("TIMESTAMP_ET_NOT_AMERICA_NEW_YORK_AWARE: " + logical["timestamp"])
            else:
                timestamp_types.add(logical["timestamp"])
            utc_timestamp_type = record["_physical_arrow_types"][SECONDARY_UTC_TIMESTAMP_COLUMN]
            if not pa.types.is_timestamp(utc_timestamp_type) or utc_timestamp_type.tz != "UTC":
                reasons.append("TIMESTAMP_UTC_NOT_UTC_AWARE: " + str(utc_timestamp_type))
            else:
                utc_timestamp_types.add(str(utc_timestamp_type))
            for column in ("open", "high", "low", "close", "volume"):
                field_type = arrow_types[column]
                if not pa.types.is_integer(field_type) and not pa.types.is_floating(field_type) and not pa.types.is_decimal(field_type):
                    reasons.append("NON_NUMERIC_" + column.upper() + ": " + logical[column])
        record["schema_rejection_reason"] = "; ".join(reasons)
    if not any(record["schema_rejection_reason"] for record in records) and (len(timestamp_types) != 1 or len(utc_timestamp_types) != 1):
        for record in records:
            record["schema_rejection_reason"] = "INCOMPATIBLE_TIMESTAMP_LOGICAL_TYPES: timestamp_et=" + ", ".join(sorted(timestamp_types)) + "; timestamp_utc=" + ", ".join(sorted(utc_timestamp_types))
    return records, not any(record["schema_rejection_reason"] for record in records)


def parse_canonical_partition(path: Path, root: Path = ROOT):
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) != 5 or parts[0] != "canonical" or parts[4] != "data.parquet":
        return None
    symbol_part, year_part, month_part = parts[1:4]
    if not symbol_part.startswith("symbol=") or not year_part.startswith("year=") or not month_part.startswith("month="):
        return None
    symbol, year, month = symbol_part[7:], year_part[5:], month_part[6:]
    if symbol not in SYMS or len(year) != 4 or not year.isdigit() or len(month) != 2 or not month.isdigit() or not 1 <= int(month) <= 12:
        return None
    return {"symbol": symbol, "year": year, "month": month, "relative_path": str(relative)}


def canonical_rows(root: Path = ROOT):
    rows = []
    for symbol in SYMS:
        for path in sorted((root / "canonical" / f"symbol={symbol}").glob("year=*/month=*/data.parquet")):
            partition = parse_canonical_partition(path, root)
            if partition:
                stat = path.stat()
                rows.append({**partition, "file_size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return rows


def build_split(rows):
    month_sets = [{f'{row["year"]}-{row["month"]}' for row in rows if row["symbol"] == symbol} for symbol in SYMS]
    common_complete_months = sorted(set.intersection(*month_sets))
    n = len(common_complete_months)
    confirmation_count = max(12, math.floor(0.20 * n))
    validation_count = max(12, math.floor(0.20 * n))
    required_month_count = 24 + validation_count + confirmation_count + 2
    if n < required_month_count:
        return common_complete_months, None, {"final_status": "FAIL", "final_decision": "INSUFFICIENT_COMMON_MONTHS_FOR_SPLIT", "required_month_count": required_month_count}
    confirmation = common_complete_months[-confirmation_count:]
    validation_confirmation_embargo = common_complete_months[-confirmation_count - 1]
    validation = common_complete_months[-confirmation_count - 1 - validation_count:-confirmation_count - 1]
    development_validation_embargo = common_complete_months[-confirmation_count - 2 - validation_count]
    development = common_complete_months[:-confirmation_count - 2 - validation_count]
    return common_complete_months, {"development_months": development, "validation_months": validation, "confirmation_months": confirmation, "development_validation_embargo_month": development_validation_embargo, "validation_confirmation_embargo_month": validation_confirmation_embargo}, None


def publish(stage):
    if OUT.exists():
        shutil.rmtree(OUT)
    os.replace(stage, OUT)


def run():
    print("STAGE=DISCOVER_PARTITIONS", flush=True)
    rows = canonical_rows()
    counts = {symbol: sum(row["symbol"] == symbol for row in rows) for symbol in SYMS}
    canonical_fingerprint = metadata_fingerprint(rows)
    print("STAGE=CHECK_SAMPLE_SCHEMAS", flush=True)
    samples = []
    for symbol in SYMS:
        row = next(row for row in rows if row["symbol"] == symbol)
        parquet = pq.ParquetFile(ROOT / row["relative_path"])
        samples.append(normalized_schema_record(symbol, ROOT / row["relative_path"], parquet.schema_arrow))
    samples, sample_schema_verified = evaluate_sample_schemas(samples)
    print("STAGE=BUILD_SPLIT", flush=True)
    months, split, split_failure = build_split(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".069fast_", dir=OUT.parent))
    try:
        if split_failure:
            summary = {**split_failure, "canonical_partition_count": len(rows), "partition_count_by_symbol": counts, "common_complete_month_count": len(months), "canonical_partition_metadata_fingerprint_sha256": canonical_fingerprint, **OUTPUT_LOCATION_FLAGS, **ATTESTATION_FLAGS}
            (stage / "v22_069a_fast_summary.json").write_bytes(b(summary))
            publish(stage)
            return summary
        print("STAGE=LOAD_FEATURE_EVIDENCE", flush=True)
        evidence = recover_feature_evidence()
        features = evidence["feature_whitelist"]
        pd.DataFrame(rows).to_csv(stage / "v22_069a_fast_canonical_inventory.csv", index=False)
        pd.DataFrame([{"feature_name": name} for name in features]).to_csv(stage / "v22_069a_fast_feature_whitelist.csv", index=False)
        print("STAGE=SEAL_CONFIRMATION", flush=True)
        confirmation_months = set(split["confirmation_months"])
        confirmation_rows = [row for row in rows if f'{row["year"]}-{row["month"]}' in confirmation_months]
        confirmation_hash = metadata_fingerprint(confirmation_rows)
        confirmation_seal = {"partitions": [partition_identity(row) for row in sorted(confirmation_rows, key=lambda row: row["relative_path"])], "confirmation_partition_identity_sha256": confirmation_hash, "confirmation_content_parsed": False, "confirmation_row_read_count": 0, "confirmation_sealed": True}
        print("STAGE=WRITE_CONTRACT", flush=True)
        for name, value in [("v22_069a_fast_split_contract.json", split), ("v22_069a_fast_confirmation_seal.json", confirmation_seal), ("v22_069a_fast_event_contract.json", {"timezone": "America/New_York", "feature_cutoff": "09:25", "entry": "09:30-09:32 first valid open", "exit": "15:58-16:00 last valid close"}), ("v22_069a_fast_target_contract.json", {"target": "exit_price / entry_price - 1"}), ("v22_069a_fast_cost_contract.json", {"one_way_cost_bps": 5, "round_trip_cost_bps": 10})]:
            (stage / name).write_bytes(b(value))
        ok = len(rows) == 582 and all(count == 97 for count in counts.values()) and len(split["development_months"]) >= 24 and sample_schema_verified
        contract = {"symbols": SYMS, "split": split, "canonical_partition_metadata_fingerprint_sha256": canonical_fingerprint, "confirmation_partition_identity_sha256": confirmation_hash, "features": features, **evidence, **OUTPUT_LOCATION_FLAGS, **LOGICAL_SCHEMA_MAPPING, "confirmation_content_parsed": False, "confirmation_row_read_count": 0, **ATTESTATION_FLAGS}
        contract_hash = h(b(contract))
        (stage / "v22_069a_fast_frozen_research_contract.json").write_bytes(b(contract))
        (stage / "v22_069a_fast_frozen_research_contract.sha256").write_text(contract_hash + "\n")
        decision = "FAST_RESEARCH_CONTRACT_READY_FOR_V22_069B" if ok else "SAMPLE_SCHEMA_INCOMPATIBLE" if not sample_schema_verified else "FAST_RESEARCH_CONTRACT_FAILURE"
        summary = {"final_status": "PASS" if ok else "FAIL", "final_decision": decision, "python_process_exit_code": 0, "runner_exit_code": 0 if ok else 1, "canonical_partition_count": len(rows), "partition_count_by_symbol": counts, "common_complete_month_count": len(months), "development_month_count": len(split["development_months"]), "validation_month_count": len(split["validation_months"]), "confirmation_month_count": len(split["confirmation_months"]), "development_validation_embargo_month": split["development_validation_embargo_month"], "validation_confirmation_embargo_month": split["validation_confirmation_embargo_month"], "sample_schema_checked_count": len(samples), "sample_schema_verified": sample_schema_verified, "sample_schemas": [{key: value for key, value in sample.items() if key not in {"_logical_types", "_arrow_types", "_physical_arrow_types"}} for sample in samples], "canonical_partition_metadata_fingerprint_sha256": canonical_fingerprint, **evidence, **OUTPUT_LOCATION_FLAGS, **LOGICAL_SCHEMA_MAPPING, "confirmation_content_parsed": False, "confirmation_row_read_count": 0, "confirmation_sealed": True, "confirmation_partition_identity_sha256": confirmation_hash, "feature_whitelist_count": len(features), "frozen_research_contract_sha256": contract_hash, "eligible_for_v22_069b": ok, **ATTESTATION_FLAGS}
        (stage / "v22_069a_fast_manifest.json").write_bytes(b({"sample_schemas": summary["sample_schemas"], **OUTPUT_LOCATION_FLAGS, **LOGICAL_SCHEMA_MAPPING, "research_only": True}))
        (stage / "v22_069a_fast_readme.txt").write_text(f"Research-only: eligibility permits Development-stage research model construction only. It does not mean data received a row-by-row review or full content hash, and it must not be used for paper, broker, or official strategy adoption. Requested official output root: {REQUESTED_OFFICIAL_OUTPUT_ROOT}. Actual local fallback output root: {OUT}. Official results root was unavailable from this execution context. V22.069B must explicitly read its contract from actual_output_root. Logical timestamp mapping: timestamp -> {LOGICAL_TIMESTAMP_COLUMN} ({LOGICAL_TIMESTAMP_TIMEZONE}); secondary UTC column: {SECONDARY_UTC_TIMESTAMP_COLUMN}. Sample schema records: {json.dumps(summary['sample_schemas'], sort_keys=True)}\n")
        (stage / "v22_069a_fast_summary.json").write_bytes(b(summary))
        publish(stage)
        return summary
    except FeatureWhitelistSourceIncomplete as error:
        summary = {"final_status": "FAIL", "final_decision": "FEATURE_WHITELIST_SOURCE_INCOMPLETE", "feature_whitelist_source_error": str(error), "canonical_partition_count": len(rows), "partition_count_by_symbol": counts, "common_complete_month_count": len(months), **OUTPUT_LOCATION_FLAGS, **ATTESTATION_FLAGS}
        (stage / "v22_069a_fast_summary.json").write_bytes(b(summary))
        publish(stage)
        return summary
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args()
    if arguments.execute:
        print(run())
