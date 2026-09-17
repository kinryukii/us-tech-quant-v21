"""Synthetic SEC source unions; no research, credentials or network calls."""
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from scripts.storage.materialize_sec_2026 import materialize
from scripts.storage.storage_r2a import DataStore, StoragePaths, sha256


@pytest.fixture
def store(tmp_path):
    return DataStore(StoragePaths(**{name: tmp_path / name for name in (
        "repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")}))


def row(number=1):
    return {"cik": 123, "accession": f"0000000123-26-{number:06d}", "form": "10-Q",
            "filed_date": "2026-09-11", "accepted_at": pd.Timestamp("2026-09-11T12:00:00Z"),
            "acceptance_status": "KNOWN"}


def fact(number=1, **updates):
    return {**row(number), "taxonomy": "us-gaap", "concept": "Revenue", "unit": "USD",
            "start_date": "2026-01-01", "end_date": "2026-06-30", "raw_value": 100.,
            "frame": "CY2026Q2", "fiscal_year": 2026., "fiscal_period": "Q2", **updates}


def inputs(store, *, facts=None, submissions=None, exception=False):
    manifests = []
    for name, number, prefix in [("baseline", 1, "current/"), ("incremental", 2, "")]:
        root = store.paths.data_root / name
        root.mkdir(parents=True)
        file_records = {}
        frames = {"companyfacts": pd.DataFrame((facts or {}).get(name, [fact(number)])),
                  "submissions": pd.DataFrame((submissions or {}).get(name, [row(number)]))}
        for kind, frame in frames.items():
            frame["source_archive" if name == "baseline" else "source_url"] = name + ":source"
            path = root / f"{kind}.parquet"
            frame.to_parquet(path, index=False)
            file_records[prefix + kind] = {"path": str(path), "sha256": sha256(path), "rows": len(frame)}
        manifest = root / "source_manifest.json"
        manifest.write_text(json.dumps({"files": file_records}), encoding="utf-8")
        manifests.append(manifest)
    if exception:
        root = store.paths.data_root / "exceptions"; root.mkdir()
        path = root / "submissions.parquet"
        pd.DataFrame([{**row(3), "exception_reason": "ACCEPTED_BEFORE_WINDOW"}]).to_parquet(path, index=False)
        manifest = root / "source_manifest.json"
        manifest.write_text(json.dumps({"dataset_id": "sec_submissions_acceptance_exceptions", "files": {
            "submissions": {"path": str(path), "sha256": sha256(path), "rows": 1}}}), encoding="utf-8")
        manifests.append(manifest)
    return manifests


def run(store, manifests):
    return materialize(store, manifests[0], manifests[1], store.paths.data_root / "unified", "2026-09-11",
                       manifests[2] if len(manifests) == 3 else None)


def test_preserves_units_revisions_all_columns_and_input_lineage(store):
    manifests = inputs(store, facts={"baseline": [fact(1), fact(1, unit="shares", raw_value=8), fact(1, frame=None)]}, exception=True)
    original = {path: sha256(path) for path in store.paths.data_root.rglob("*") if path.is_file()}
    result = run(store, manifests)
    assert not store.catalog_path.exists()
    assert all(sha256(path) == digest for path, digest in original.items())
    facts = pq.ParquetFile(result["files"]["companyfacts"]["path"]).read().to_pandas()
    submissions = pq.ParquetFile(result["files"]["submissions"]["path"]).read().to_pandas()
    assert len(facts) == 4 and len(submissions) == 3
    assert facts.unit.tolist().count("shares") == 1 and facts.frame.isna().sum() == 1
    assert {"source_archive", "source_url", "input_file_sha256", "input_manifest_sha256"} <= set(facts)
    assert not submissions.duplicated(["cik", "accession"]).any()
    assert submissions.input_dataset_role.tolist() == ["baseline", "incremental", "acceptance_exception"]
    input_hashes = {record["sha256"] for record in result["contract"]["inputs"] if record["kind"] == "companyfacts"}
    assert set(facts.input_file_sha256) == input_hashes
    assert set(facts.input_manifest_sha256) == {sha256(manifests[0]), sha256(manifests[1])}
    assert run(store, manifests) == result


@pytest.mark.parametrize("kind", ["facts", "submissions"])
def test_cross_source_accession_overlap_requires_reconciliation(store, kind):
    changes = {kind: {"incremental": [fact(1, raw_value=999)] if kind == "facts" else [row(1)]}}
    manifests = inputs(store, **changes)
    with pytest.raises(ValueError, match="accession overlap"):
        run(store, manifests)
    assert not list((store.paths.data_root / "unified").rglob("sec_2026_manifest.json"))


def test_duplicate_submissions_inside_source_rejected(store):
    manifests = inputs(store, submissions={"baseline": [row(1), row(1)]})
    with pytest.raises(ValueError, match="duplicate submission key"):
        run(store, manifests)


def test_original_duplicate_fact_rows_are_preserved(store):
    manifests = inputs(store, facts={"baseline": [fact(1), fact(1)]})
    result = run(store, manifests)
    assert result["files"]["companyfacts"]["rows"] == 3


def test_input_hash_and_current_snapshot_changes_fail_closed(store):
    manifests = inputs(store)
    result = run(store, manifests)
    path = Path(result["files"]["companyfacts"]["path"])
    with path.open("ab") as handle:
        handle.write(b"synthetic corruption")
    with pytest.raises(ValueError, match="snapshot bytes changed"):
        run(store, manifests)
    source = store.paths.data_root / "baseline/companyfacts.parquet"
    with source.open("ab") as handle:
        handle.write(b"synthetic source corruption")
    with pytest.raises(ValueError, match="source Parquet hash mismatch"):
        run(store, manifests)


def test_dates_outside_2026_or_snapshot_are_not_silently_filtered(store):
    manifests = inputs(store, facts={"baseline": [fact(1, filed_date="2025-12-31")]})
    with pytest.raises(ValueError, match="escape the explicit 2026"):
        run(store, manifests)


def test_incompatible_value_types_are_not_silently_coerced(store):
    manifests = inputs(store, facts={"incremental": [fact(2, raw_value="reported-as-text")]})
    with pytest.raises(ValueError, match="incompatible fragment schema"):
        run(store, manifests)


def test_prior_year_filed_submission_accepted_in_2026_is_preserved(store):
    prior_year = {**row(1), "filed_date": "2025-12-31", "accepted_at": pd.Timestamp("2026-01-02T05:15:27Z")}
    manifests = inputs(store, submissions={"baseline": [prior_year]})
    result = run(store, manifests)
    submission = result["files"]["submissions"]
    data = pq.ParquetFile(submission["path"]).read().to_pandas()
    assert data.iloc[0].filed_date == "2025-12-31"
    assert submission["date_column"] == "accepted_at"
    assert submission["min_date"] == "2026-01-02T05:15:27+00:00"
    catalog = next(row for row in result["catalog_records"] if row["dataset"] == "sec_submissions_2026")
    assert catalog["lineage"]["date_column"] == "accepted_at"


def test_submission_window_uses_new_york_day(store):
    # 2026 in UTC is still 2025 in New York; filed_date cannot override a known timestamp.
    prior_year = {**row(1), "accepted_at": pd.Timestamp("2026-01-01T01:00:00Z")}
    manifests = inputs(store, submissions={"baseline": [prior_year]})
    with pytest.raises(ValueError, match="2026 ET window"):
        run(store, manifests)


def test_unknown_acceptance_is_retained_without_fabricating_timestamp(store):
    unknown = {**row(3), "accepted_at": pd.NaT, "acceptance_status": "MISSING"}
    manifests = inputs(store, submissions={"baseline": [row(1), unknown]})
    result = run(store, manifests)
    item = result["files"]["submissions"]
    data = pq.ParquetFile(item["path"]).read().to_pandas()
    assert item["accepted_at_missing_rows"] == 1
    assert data.loc[data.acceptance_status.eq("MISSING"), "accepted_at"].isna().all()
