"""Pin existing Parquet fragments without copying data or changing the catalog.

Only lossless timestamp-unit and string-width promotion is permitted. Timezone,
field, numeric-type, overlapping interval and declared identity conflicts fail.
Footer/hash checks do not claim that every bar or exchange session is present.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.storage.storage_r2a import sha256


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode()


def unified_schema(schemas):
    if not schemas:
        raise ValueError("empty fragment list")
    names = schemas[0].names
    if len(names) != len(set(names)) or any(set(s.names) != set(names) or len(s.names) != len(names) for s in schemas):
        raise ValueError("fragment schema field names conflict")
    fields = []
    units = {"s": 0, "ms": 1, "us": 2, "ns": 3}
    for name in names:
        types = [s.field(name).type for s in schemas]
        if all(t == types[0] for t in types):
            dtype = types[0]
        elif all(pa.types.is_string(t) or pa.types.is_large_string(t) for t in types):
            dtype = pa.large_string()
        elif all(pa.types.is_timestamp(t) for t in types):
            if len({t.tz for t in types}) != 1:
                raise ValueError(f"fragment timestamp timezone conflict: {name}")
            dtype = pa.timestamp(max((t.unit for t in types), key=units.get), tz=types[0].tz)
        else:
            raise ValueError(f"incompatible fragment schema: {name}: {types}")
        fields.append(pa.field(name, dtype, nullable=any(s.field(name).nullable for s in schemas)))
    return pa.schema(fields)


def footer_stats(parquet, column):
    index = parquet.schema_arrow.get_field_index(column)
    if index < 0:
        raise ValueError(f"declared fragment column missing: {column}")
    # This contract is intentionally flat; nested Parquet leaf indexes differ.
    if len(parquet.schema) != len(parquet.schema_arrow):
        raise ValueError("nested fragment schemas are unsupported")
    values = []
    for group in range(parquet.metadata.num_row_groups):
        row_group = parquet.metadata.row_group(group)
        if not row_group.num_rows:
            continue
        stat = row_group.column(index).statistics
        if stat is None or not stat.has_min_max or stat.null_count != 0:
            raise ValueError(f"complete non-null footer statistics required: {column}")
        values.append((stat.min, stat.max))
    if not values:
        raise ValueError("empty fragment")
    return min(v[0] for v in values), max(v[1] for v in values)


def inspect_fragment(store, path, date_column, expected_values, expected_hash=None):
    if not Path(path).is_absolute():
        raise ValueError("fragment paths must be absolute")
    path = store._check_data_path(Path(path))
    if not path.is_file() or path.suffix.lower() != ".parquet":
        raise ValueError("fragment must be a regular Parquet file")
    digest = sha256(path)
    if expected_hash is not None and digest != expected_hash:
        raise ValueError(f"manifest fragment metadata/hash mismatch: {path}")
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    dtype = schema.field(date_column).type
    if not (pa.types.is_timestamp(dtype) or pa.types.is_date(dtype)):
        raise ValueError("manifest date column requires an explicit Arrow date/timestamp type")
    lower, upper = footer_stats(parquet, date_column)
    for column, expected in expected_values.items():
        lo, hi = footer_stats(parquet, column)
        if str(lo) != expected or str(hi) != expected:
            raise ValueError(f"fragment identity/source contract mismatch: {column}: {path}")
    if sha256(path) != digest:
        raise ValueError("fragment changed during footer inspection")
    return {"path": str(path), "sha256": digest, "size_bytes": path.stat().st_size,
            "row_count": parquet.metadata.num_rows,
            "min_date": pd.Timestamp(lower).isoformat(), "max_date": pd.Timestamp(upper).isoformat()}, schema


def check_intervals(files):
    ordered = sorted(files, key=lambda f: pd.Timestamp(f["min_date"]))
    for previous, current in zip(ordered, ordered[1:]):
        if pd.Timestamp(current["min_date"]) <= pd.Timestamp(previous["max_date"]):
            raise ValueError("overlapping fragment time ranges; explicit reconciliation required")
    return ordered


def verify_hashes(store, manifest_path, expected_hash, manifest):
    if sha256(store._check_data_path(Path(manifest_path))) != expected_hash:
        raise ValueError("manifest changed or SHA-256 mismatch")
    for item in manifest["files"] + manifest.get("supporting_manifests", []):
        path = store._check_data_path(Path(item["path"]))
        if sha256(path) != item["sha256"]:
            raise ValueError(f"fragment SHA-256 mismatch: {path}")


def load_manifest(store, row):
    path = store._check_data_path(Path(row["path"]))
    if sha256(path) != row.get("source_sha256"):
        raise ValueError("manifest SHA-256 mismatch")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("format") != "parquet_manifest":
        raise ValueError("unsupported Parquet manifest schema/format")
    for field in ("dataset", "ticker", "adjustment", "row_count", "min_date", "max_date"):
        if manifest.get(field) != row.get(field):
            raise ValueError(f"manifest/catalog contract mismatch: {field}")
    expected_values = manifest["expected_values"]
    if not isinstance(expected_values, dict) or manifest["ticker_column"] not in expected_values:
        raise ValueError("manifest requires an explicit ticker column/value contract")
    if expected_values[manifest["ticker_column"]] != manifest["ticker"]:
        raise ValueError("manifest ticker value differs from catalog ticker")
    for evidence in manifest.get("supporting_manifests", []):
        if not Path(evidence["path"]).is_absolute() or sha256(store._check_data_path(Path(evidence["path"]))) != evidence["sha256"]:
            raise ValueError("supporting manifest SHA-256/path mismatch")
    files = manifest["files"]
    if not files or len({str(Path(f["path"]).resolve()) for f in files}) != len(files):
        raise ValueError("empty or duplicate manifest fragments")
    actual, schemas = [], []
    for item in files:
        inspected, schema = inspect_fragment(store, item["path"], manifest["date_column"], expected_values, item["sha256"])
        if inspected != item:
            raise ValueError(f"manifest fragment metadata/hash mismatch: {item['path']}")
        actual.append(inspected); schemas.append(schema)
    check_intervals(actual)
    schema = unified_schema(schemas)
    declared = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(manifest["schema_base64"], validate=True)))
    if schema != declared:
        raise ValueError("manifest unified schema mismatch")
    if sum(f["row_count"] for f in actual) != manifest["row_count"]:
        raise ValueError("manifest total row count mismatch")
    if min(f["min_date"] for f in actual) != manifest["min_date"] or max(f["max_date"] for f in actual) != manifest["max_date"]:
        raise ValueError("manifest aggregate date range mismatch")
    if sha256(path) != row["source_sha256"]:
        raise ValueError("manifest changed during validation")
    return manifest, [Path(item["path"]) for item in files], schema


def prepare(store, files, output_root, *, dataset, ticker, adjustment, date_column,
            ticker_column, source, expected_values, supporting_manifests=()):
    ticker = store._ticker(ticker)
    output_root = store._check_data_path(Path(output_root), must_exist=False)
    if expected_values.get(ticker_column) != ticker:
        raise ValueError("explicit ticker column/value must match ticker")
    resolved = [Path(p).resolve() for p in files]
    if len(set(resolved)) != len(resolved):
        raise ValueError("duplicate fragment path")
    records, schemas = [], []
    for path in sorted(resolved):
        record, schema = inspect_fragment(store, path, date_column, expected_values)
        records.append(record); schemas.append(schema)
    schema = unified_schema(schemas)
    records = check_intervals(records)
    evidence = []
    for item in sorted({Path(p).resolve() for p in supporting_manifests}):
        path = store._check_data_path(item)
        if not path.is_file():
            raise ValueError("supporting manifest must be a regular file")
        evidence.append({"path": str(path), "sha256": sha256(path)})
    contract = {"schema_version": 1, "format": "parquet_manifest", "dataset": dataset,
                "ticker": ticker, "adjustment": adjustment, "source": source,
                "date_column": date_column, "ticker_column": ticker_column,
                "expected_values": expected_values, "files": records, "supporting_manifests": evidence,
                "row_count": sum(f["row_count"] for f in records),
                "min_date": records[0]["min_date"], "max_date": records[-1]["max_date"],
                "schema_base64": base64.b64encode(schema.serialize().to_pybytes()).decode(),
                "schema": {field.name: str(field.type) for field in schema},
                "validation_scope": "FILE_HASH_FOOTER_SCHEMA_IDENTITY_AND_NONOVERLAPPING_RANGES",
                "completeness": "EXISTING_FRAGMENTS_ONLY_NOT_ALL_MINUTES_OR_SESSIONS",
                "source_files_copied": False, "catalog_written": False}
    identity = hashlib.sha256(canonical_bytes(contract)).hexdigest()
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"fragments_{identity[:24]}.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if {key: previous.get(key) for key in contract} != contract:
            raise ValueError("existing manifest content-address conflict")
    else:
        manifest = {**contract, "generated_at_utc": datetime.now(timezone.utc).isoformat()}
        with path.open("xb") as handle:
            handle.write(canonical_bytes(manifest))
    record = {key: contract[key] for key in ("dataset", "ticker", "adjustment", "row_count", "min_date", "max_date", "source")}
    record.update(path=str(path), format="parquet_manifest", lineage={
        "date_column": date_column, "ticker_column": ticker_column,
        "authority": "ORIGINAL_FRAGMENT_CONTRACT_UNCHANGED", "snapshot_id": identity,
        "validation_scope": contract["validation_scope"], "completeness": contract["completeness"]})
    return {"path": str(path), "sha256": sha256(path), "fragment_count": len(records),
            "catalog_record": record, "catalog_written": False}


def main(argv=None):
    from scripts.storage.storage_r2a import DataStore
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--extra-fragment", type=Path, action="append", default=[], help="append a reconciled, non-overlapping fragment")
    parser.add_argument("--supporting-manifest", type=Path, action="append", default=[], help="pin the acquisition/reconciliation evidence")
    for name in ("dataset", "ticker", "adjustment", "date-column", "ticker-column", "source"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--expected-value", action="append", default=[], metavar="COLUMN=VALUE")
    args = parser.parse_args(argv)
    expected = {}
    for pair in args.expected_value:
        key, separator, value = pair.partition("=")
        if not separator or not key or key in expected:
            parser.error("expected-value must give each COLUMN=VALUE exactly once")
        expected[key] = value
    store = DataStore()
    root = store._check_data_path(args.input_root)
    result = prepare(store, list(root.rglob("*.parquet")) + args.extra_fragment, args.output_root,
                     dataset=args.dataset, ticker=args.ticker, adjustment=args.adjustment,
                     date_column=args.date_column, ticker_column=args.ticker_column,
                     source=args.source, expected_values=expected, supporting_manifests=args.supporting_manifest)
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
