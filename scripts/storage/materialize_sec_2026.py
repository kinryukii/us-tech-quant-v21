"""Prepare one versioned SEC 2026 query snapshot from explicit source manifests.

No source is overwritten and no catalog is modified. Submissions are unique by
(CIK, accession). Facts retain every original unit, frame, period and revision
row. Cross-input accession overlap is rejected until explicitly reconciled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from scripts.storage.build_parquet_manifest import canonical_bytes, unified_schema
from scripts.storage.storage_r2a import DataStore, sha256


ANNOTATIONS = ("input_file_sha256", "input_manifest_sha256", "input_dataset_role")
COMMON = {"cik", "accession", "form", "filed_date", "accepted_at", "acceptance_status"}
FACTS = {"taxonomy", "concept", "unit", "start_date", "end_date", "raw_value", "frame", "fiscal_year", "fiscal_period"}


def read_manifest(store, path):
    path = store._check_data_path(Path(path))
    digest = sha256(path)
    content = json.loads(path.read_text(encoding="utf-8"))
    if sha256(path) != digest:
        raise ValueError("source manifest changed during read")
    return content, {"path": str(path), "sha256": digest}


def source_record(store, manifest, identity, key, role, kind):
    record = manifest["files"][key]
    path = Path(record["path"])
    if not path.is_absolute():
        raise ValueError("source data paths must be absolute")
    path = store._check_data_path(path)
    if not path.is_file() or sha256(path) != record["sha256"]:
        raise ValueError("source Parquet hash mismatch")
    return {"path": str(path), "sha256": record["sha256"], "rows": record["rows"],
            "manifest": identity, "role": role, "kind": kind}


def validate_table(table, record, as_of):
    required = COMMON | (FACTS if record["kind"] == "companyfacts" else set())
    if not required <= set(table.column_names):
        raise ValueError("SEC source schema missing columns: " + ",".join(sorted(required - set(table.column_names))))
    if set(ANNOTATIONS) & set(table.column_names):
        raise ValueError("input already contains unified-snapshot annotations")
    if table.num_rows != record["rows"]:
        raise ValueError("source manifest row count mismatch")
    keys = table.select(["cik", "accession"]).to_pandas()
    if keys.isna().any().any() or not keys.accession.astype(str).str.fullmatch(r"\d{10}-\d{2}-\d{6}").all():
        raise ValueError("invalid CIK/accession source key")
    if not pa.types.is_integer(table.schema.field("cik").type) or keys.cik.le(0).any():
        raise ValueError("CIK must be a positive integer")
    if record["kind"] == "submissions" and keys.duplicated().any():
        raise ValueError("duplicate submission key inside one source")
    filed = table.column("filed_date").to_pandas()
    parsed = pd.to_datetime(filed, format="%Y-%m-%d", errors="coerce")
    if parsed.isna().any() or not parsed.dt.strftime("%Y-%m-%d").eq(filed).all():
        raise ValueError("filed_date must contain finite ISO daily dates")
    accepted_type = table.schema.field("accepted_at").type
    if not pa.types.is_timestamp(accepted_type) or accepted_type.tz is None:
        raise ValueError("accepted_at must retain an explicit timestamp timezone")
    if record["kind"] == "companyfacts":
        if len(filed) and (filed.min() < "2026-01-01" or filed.max() > as_of):
            raise ValueError("source filed dates escape the explicit 2026 snapshot interval")
    else:
        accepted = table.column("accepted_at").to_pandas()
        known = table.column("acceptance_status").to_pandas().eq("KNOWN")
        if accepted[known].isna().any():
            raise ValueError("KNOWN submission acceptance is missing its timestamp")
        availability_days = filed.copy()
        availability_days.loc[known] = accepted.loc[known].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
        if len(availability_days) and (availability_days.min() < "2026-01-01" or availability_days.max() > as_of):
            raise ValueError("submission availability dates escape the explicit 2026 ET window")
    return set(keys.drop_duplicates().itertuples(index=False, name=None))


def union_tables(tables):
    names = list(dict.fromkeys(name for table in tables for name in table.column_names))
    fields = []
    for name in names:
        present = [pa.schema([table.schema.field(name)]) for table in tables if name in table.column_names]
        field = unified_schema(present).field(name)
        fields.append(pa.field(name, field.type, nullable=True))
    schema = pa.schema(fields)
    aligned = []
    for table in tables:
        columns = [table.column(field.name).cast(field.type, safe=True) if field.name in table.column_names
                   else pa.nulls(table.num_rows, type=field.type) for field in schema]
        aligned.append(pa.Table.from_arrays(columns, schema=schema))
    return pa.concat_tables(aligned)


def atomic_parquet(path, table):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        pq.write_table(table, temporary, compression="zstd")
        digest = sha256(temporary)
        if path.exists():
            if sha256(path) != digest:
                raise ValueError("existing immutable SEC snapshot file differs")
        else:
            # rename fails if another writer already published this version.
            os.rename(temporary, path)
        return digest
    finally:
        if temporary.exists():
            temporary.unlink()


def materialize(store, baseline_manifest, incremental_manifest, output_root, as_of, exception_manifest=None):
    if date.fromisoformat(as_of).isoformat() != as_of or not as_of.startswith("2026-"):
        raise ValueError("as_of must be an explicit YYYY-MM-DD date in 2026")
    output_root = store._check_data_path(Path(output_root), must_exist=False)
    records = []
    for path, role, prefix in ((baseline_manifest, "baseline", "current/"), (incremental_manifest, "incremental", "")):
        manifest, identity = read_manifest(store, path)
        for kind in ("companyfacts", "submissions"):
            records.append(source_record(store, manifest, identity, prefix + kind, role, kind))
    if exception_manifest is not None:
        manifest, identity = read_manifest(store, exception_manifest)
        if manifest.get("dataset_id") != "sec_submissions_acceptance_exceptions":
            raise ValueError("unsupported exception manifest dataset")
        records.append(source_record(store, manifest, identity, "submissions", "acceptance_exception", "submissions"))
    contract = {"schema_version": 1, "as_of": as_of, "start_date": "2026-01-01", "inputs": records,
                "cross_input_accession_policy": "REJECT_OVERLAP_REQUIRES_EXPLICIT_RECONCILIATION",
                "fact_policy": "PRESERVE_EVERY_SOURCE_ROW_UNIT_FRAME_PERIOD_REVISION",
                "submission_key": ["cik", "accession"],
                "date_columns": {"companyfacts": "filed_date", "submissions": "accepted_at"},
                "submission_window_policy": "KNOWN_ACCEPTED_AT_NEW_YORK_DAY_ELSE_FILED_DATE_WITH_UNKNOWN_AVAILABILITY",
                "availability_column": "accepted_at", "catalog_written": False}
    snapshot_id = hashlib.sha256(canonical_bytes(contract)).hexdigest()
    directory = output_root / "versions" / snapshot_id[:24]
    manifest_path = directory / "sec_2026_manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("contract") != contract:
            raise ValueError("existing SEC snapshot contract mismatch")
        for item in previous["files"].values():
            if sha256(store._check_data_path(Path(item["path"]))) != item["sha256"]:
                raise ValueError("existing SEC snapshot bytes changed")
        return previous
    outputs, catalog_records = {}, []
    for kind in ("companyfacts", "submissions"):
        tables, seen = [], set()
        for record in [item for item in records if item["kind"] == kind]:
            path = Path(record["path"])
            if sha256(path) != record["sha256"]:
                raise ValueError("source changed before materialization")
            table = pq.ParquetFile(path).read()
            keys = validate_table(table, record, as_of)
            overlap = seen & keys
            if overlap:
                raise ValueError(f"cross-input {kind} accession overlap; reconcile explicitly: {sorted(overlap)[:3]}")
            seen |= keys
            for name, value in zip(ANNOTATIONS, (record["sha256"], record["manifest"]["sha256"], record["role"])):
                table = table.append_column(name, pa.array([value] * table.num_rows, type=pa.string()))
            if sha256(path) != record["sha256"]:
                raise ValueError("source changed during materialization")
            tables.append(table)
        combined = union_tables(tables)
        sort_keys = [(name, "ascending") for name in ["cik", "accession"] + (["taxonomy", "concept", "unit", "start_date", "end_date", "frame"] if kind == "companyfacts" else [])]
        combined = combined.take(pc.sort_indices(combined, sort_keys=sort_keys))
        path = directory / f"{kind}.parquet"
        digest = atomic_parquet(path, combined)
        date_column = contract["date_columns"][kind]
        bounds = pc.min_max(combined.column(date_column)).as_py()
        bounds = {key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in bounds.items()}
        record = {"path": str(path), "sha256": digest, "rows": combined.num_rows,
                  "min_date": bounds["min"], "max_date": bounds["max"],
                  "date_column": date_column,
                  "columns": combined.column_names,
                  "accepted_at_missing_rows": combined.column("accepted_at").null_count}
        outputs[kind] = record
        catalog_records.append({"dataset": f"sec_{kind}_2026", "ticker": "", "adjustment": "", "path": str(path),
                                "row_count": combined.num_rows, "min_date": bounds["min"], "max_date": bounds["max"],
                                "source": "SEC_OFFICIAL_SOURCES", "lineage": {
                                    "date_column": date_column, "availability_column": "accepted_at", "snapshot_id": snapshot_id,
                                    "submission_window_policy": contract["submission_window_policy"],
                                    "manifest_path": str(manifest_path), "inputs": [r for r in records if r["kind"] == kind],
                                    "fact_policy": contract["fact_policy"],
                                    "authority": "QUERY_UNION_NOT_NEW_IDENTITY_OR_RESEARCH_AUTHORITY"}})
    for record in records:
        if sha256(Path(record["path"])) != record["sha256"] or sha256(Path(record["manifest"]["path"])) != record["manifest"]["sha256"]:
            raise ValueError("input data or source manifest changed before snapshot completion")
    result = {"schema_version": 1, "dataset_id": "sec_2026_query_snapshot", "snapshot_id": snapshot_id,
              "generated_at_utc": datetime.now(timezone.utc).isoformat(), "contract": contract,
              "files": outputs, "catalog_records": catalog_records, "catalog_written": False,
              "original_sources_modified": False,
              "limitations": ["Union of these explicit source snapshots; not all SEC companies or all concepts guaranteed.",
                              "All fact rows and original provenance columns retained; absent source-specific columns are null.",
                              "Submissions use known accepted_at in the New York 2026 window; earlier filed dates are preserved. Unknown acceptance uses filed_date only for intake and stays unknown.",
                              "Filing dates do not replace accepted_at availability; current vintages do not establish historical PIT eligibility.",
                              "Cross-input accession overlaps require explicit reconciliation before this tool can include them."]}
    with manifest_path.open("xb") as handle:
        handle.write(canonical_bytes(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--incremental-manifest", type=Path, required=True)
    parser.add_argument("--exception-manifest", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args(argv)
    result = materialize(DataStore(), args.baseline_manifest, args.incremental_manifest, args.output_root,
                         args.as_of, args.exception_manifest)
    print(json.dumps({"snapshot_id": result["snapshot_id"], "files": result["files"],
                      "catalog_records": result["catalog_records"], "catalog_written": False}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
