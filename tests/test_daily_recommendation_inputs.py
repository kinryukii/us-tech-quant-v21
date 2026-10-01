from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

SOURCE = Path(__file__).parents[1] / "scripts/daily_recommendation_inputs.py"
SPEC = importlib.util.spec_from_file_location("daily_recommendation_inputs_test", SOURCE)
inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inputs)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": inputs.sha256_file(path)}


def universe(tmp_path):
    manifest = tmp_path / "universe.parquet"
    members = tmp_path / "members.parquet"
    pd.DataFrame([{"quarter": "2026Q1", "institution_count": 24, "effective_date": "2026-05-22",
        "post_cap_universe_count": 2, "universe_fingerprint": "universe-id"}]).to_parquet(manifest)
    pd.DataFrame([{"quarter": "2026Q1", "cusip": str(i), "ticker": ticker,
        "moomoo_transport_code": f"US.{ticker}", "effective_date": "2026-05-22", "expiry_date": None,
        "quarter_universe_fingerprint": "universe-id"} for i, ticker in enumerate(["AAPL", "MSFT"])]).to_parquet(members)
    return {"readiness_sources": {"universe_manifest": {"path": str(manifest), "sha256": inputs.sha256_file(manifest)},
        "universe_members": {"path": str(members), "sha256": inputs.sha256_file(members)}}}


def replay(tmp_path, mutate=None):
    root, history = tmp_path / "replay", tmp_path / "history"
    root.mkdir(); history.mkdir()
    write_json(root / "source_resolution.json", {"model_identity": "synthetic"})
    write_json(root / "input_coverage.json", {"coverage": "synthetic"})
    contract = {"model_sha256": inputs.MODEL_SHA256, "top_n": 20, "model_fit_count": 0,
        "model_selection_count": 0, "parameter_search_count": 0,
        "role": "ALREADY_EXPOSED_DESCRIPTIVE_COVERAGE_LIMITED", "start_date": "2026-08-12", "end_date": "2026-08-13",
        "source_resolution_sha256": inputs.sha256_file(root / "source_resolution.json"),
        "input_coverage_sha256": inputs.sha256_file(root / "input_coverage.json")}
    write_json(root / "contract.json", contract)
    rows = [{"signal_date": pd.Timestamp(day), "ticker": f"T{rank:02}", "a2_rank": rank,
             "a2_prediction": 999, "never_read_outcome": "not authorized"}
            for day in ["2026-08-12", "2026-08-13"] for rank in range(1, 46)]
    if mutate:
        mutate(rows)
    pd.DataFrame(rows).to_parquet(root / "predictions.parquet")
    hashes = {name: inputs.sha256_file(root / name) for name in inputs.REPLAY_HASHES}
    return root, history, hashes


def test_stale_universe_available_for_acquisition_but_never_inference(tmp_path):
    binding = universe(tmp_path)
    result = inputs.load_bound_universe(binding, "2026-09-22")
    assert result["current"] is False
    assert result["required_quarter"] == "2026Q2"
    assert result["members"][0]["moomoo_symbol"] == "US.AAPL"
    with pytest.raises(inputs.InputError, match="CURRENT_13F_QUARTER_MISSING:2026Q2"):
        inputs.load_target_universe(binding, "2026-09-22")
    assert inputs.load_target_universe(binding, "2026-06-01")["current"]


def test_universe_hash_drift_is_rejected_before_decode(tmp_path, monkeypatch):
    binding = universe(tmp_path)
    Path(binding["readiness_sources"]["universe_members"]["path"]).write_bytes(b"changed")
    monkeypatch.setattr(inputs.pq, "read_table", lambda *a, **kw: pytest.fail("decoded unverified source"))
    with pytest.raises(inputs.InputError, match="SOURCE_HASH_MISMATCH"):
        inputs.load_bound_universe(binding, "2026-09-22")


def test_current_freshness_does_not_invent_activation_dates(tmp_path):
    assert inputs.required_reporting_quarter("2026-08-14") == "2026Q1"
    assert inputs.required_reporting_quarter("2026-08-15") == "2026Q2"
    binding = universe(tmp_path)
    with pytest.raises(inputs.InputError, match="NO_EFFECTIVE_UNIVERSE"):
        inputs.load_target_universe(binding, "2026-05-01")


def test_priority_reader_projects_only_three_columns_and_preserves_bootstrap(tmp_path, monkeypatch):
    root, history, hashes = replay(tmp_path)
    read = inputs.pq.read_table
    calls = []
    def guarded(path, **kwargs):
        calls.append(kwargs["columns"])
        assert kwargs["columns"] == ["signal_date", "ticker", "a2_rank"]
        return read(path, **kwargs)
    monkeypatch.setattr(inputs.pq, "read_table", guarded)
    result = inputs.load_priority_history(root, history, expected_replay_hashes=hashes)
    assert calls and not result["records"]
    assert len(result["bootstrap_records"]) == 80
    assert {row["record_kind"] for row in result["bootstrap_records"]} == {"historical_replay"}
    assert set(result["bootstrap_records"][0]) == {"date", "ticker", "rank", "record_kind", "model_id", "source_id"}


def test_replay_byte_changes_cannot_be_accepted_from_stale_manifest(tmp_path):
    root, history, hashes = replay(tmp_path)
    (root / "predictions.parquet").write_bytes(b"changed")
    with pytest.raises(inputs.InputError, match="SOURCE_HASH_MISMATCH"):
        inputs.load_priority_history(root, history, expected_replay_hashes=hashes)


@pytest.mark.parametrize("mutation", [
    lambda rows: rows.pop(0),
    lambda rows: rows[0].update(a2_rank=2),
    lambda rows: rows[0].update(ticker="T02"),
])
def test_partial_or_duplicate_top40_is_not_counted(tmp_path, mutation):
    root, history, hashes = replay(tmp_path, mutation)
    with pytest.raises(inputs.InputError, match="TOP40_INCOMPLETE_OR_DUPLICATED"):
        inputs.load_priority_history(root, history, expected_replay_hashes=hashes)


def test_new_history_uses_same_model_and_latest_complete_run_for_date(tmp_path):
    root, history, hashes = replay(tmp_path)
    payload = {"status": "READY", "model_id": inputs.MODEL_ID, "model_sha256": inputs.MODEL_SHA256,
        "data_date": "2026-08-13", "generated_at": "2026-08-14T00:00:00+00:00",
        "input_manifest_sha256": "a" * 64, "run_id": "first",
        "ranked_rows": [{"ticker": f"D{i:02}", "rank": i, "score": 1, "security_id": str(i)} for i in range(1, 41)]}
    write_json(history / "one.json", payload)
    payload = {**payload, "generated_at": "2026-08-14T01:00:00+00:00", "run_id": "second",
               "ranked_rows": [{**row, "ticker": f"E{row['rank']:02}"} for row in payload["ranked_rows"]]}
    write_json(history / "two.json", payload)
    result = inputs.load_priority_history(root, history, expected_replay_hashes=hashes)
    assert len(result["records"]) == 40 and result["records"][0]["ticker"] == "E01"
    assert len(result["bootstrap_records"]) == 80
    assert result["records"][0]["record_kind"] == "daily_recommendation"
    payload["model_sha256"] = "b" * 64
    write_json(history / "three.json", payload)
    with pytest.raises(inputs.InputError, match="DAILY_HISTORY_MODEL_MISMATCH"):
        inputs.load_priority_history(root, history, expected_replay_hashes=hashes)


def test_latest_session_requires_timezone_before_calendar_access():
    with pytest.raises(inputs.InputError, match="ASOF_TIMEZONE_REQUIRED"):
        inputs.latest_completed_session({}, datetime(2026, 9, 23))


def test_valid_top20_without_full_top40_does_not_advance_priority_window(tmp_path):
    root, history, hashes = replay(tmp_path)
    payload = {"status": "READY", "model_id": inputs.MODEL_ID, "model_sha256": inputs.MODEL_SHA256,
        "data_date": "2026-08-14", "generated_at": "2026-08-14T23:00:00+00:00", "run_id": "partial-ranking",
        "input_manifest_sha256": "a" * 64,
        "ranked_rows": [{"rank": rank, "ticker": f"D{rank:02}"} for rank in range(1, 21)]}
    write_json(history / "twenty.json", payload)
    result = inputs.load_priority_history(root, history, expected_replay_hashes=hashes)
    assert not result["records"] and result["available_dates"][-1] == "2026-08-13"
    assert result["provenance"]["excluded_priority_files"][0]["data_date"] == "2026-08-14"


def recomputed(tmp_path, monkeypatch, *, days=None, eligible=40):
    days = days or ["2026-08-12", "2026-08-13"]
    root = tmp_path / "A2_historical_top40"
    work = root / "runs" / "synthetic"
    work.mkdir(parents=True)
    model = work / "model.bin"
    model.write_bytes(b"synthetic fixed 2026 model")
    monkeypatch.setattr(inputs, "MODEL_SHA256", inputs.sha256_file(model))
    monkeypatch.setattr(inputs.load_priority_history, "__defaults__", (inputs.MODEL_SHA256,))
    rows = [{"target_date": day, "ticker": f"R{rank:02}", "rank": rank, "model_year": 2026,
        "model_sha256": inputs.MODEL_SHA256, "universe_id": "pool", "universe_quarter": "2026Q1",
        "universe_effective_date": "2026-05-26", "institution_count": 25,
        "score": 987.654, "future_return_do_not_project": 123}
        for day in days for rank in range(1, min(eligible, 40)+1)]
    frames = {
        "top40": pd.DataFrame(rows),
        "coverage": pd.DataFrame([{"target_date": day, "status": "PARTIAL", "eligible_count": eligible,
            "universe_member_count": 100, "mapped_count": 80, "quarter": "2026Q1",
            "effective_date": "2026-05-26", "institution_count": 25} for day in days]),
        "schedule": pd.DataFrame([{"snapshot_id": "snapshot", "universe_id": "pool", "quarter": "2026Q1",
            "effective_date": "2026-05-26", "snapshot_effective_date": "2026-05-26", "institution_count": 25,
            "universe_member_count": 100, "mapped_count": 80}]),
        "ledger": pd.DataFrame([{"target_date": day, "snapshot_id": "snapshot"} for day in days]),
        "members": pd.DataFrame([{"snapshot_id": "snapshot", "ticker": "R01", "security_id": "synthetic"}]),
    }
    refs = {}
    for name, frame in frames.items():
        path = work / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        refs[name] = {"path": str(path), "sha256": inputs.sha256_file(path), "rows": len(frame)}
    price = write_json(work / "price_inputs.json", {"role": "synthetic"})
    manifest = {"schema_version": 1, "status": "PARTIAL", "feature_selection_count": 0,
        "model_selection_count": 0, "calculate_returns": False, "training_cutoff_exclusive": "2026-01-01",
        "start_date": days[0], "end_date": days[-1], "report_path": str(work / "manifest.json"),
        "models": {"artifacts": {"2026": {"path": str(model), "sha256": inputs.MODEL_SHA256,
            "model_role": "FROZEN_FULL_PRE2026_FOR_2026_INFERENCE_ONLY", "labelmax": "2025-12-30", "train_end": "2025-12-01"}}},
        "outputs": {name: refs[name] for name in ("top40", "coverage")},
        "universe_outputs": {name: refs[name] for name in ("schedule", "ledger", "members")}, "price_manifest": price}
    write_json(work / "manifest.json", manifest)
    write_json(root / "latest.json", manifest)
    return root, manifest


def update_recomputed(root, manifest, key, change):
    refs = manifest["outputs"] if key in manifest["outputs"] else manifest["universe_outputs"]
    path = Path(refs[key]["path"])
    frame = pd.read_parquet(path)
    change(frame)
    frame.to_parquet(path, index=False)
    refs[key]["sha256"] = inputs.sha256_file(path)
    refs[key]["rows"] = len(frame)
    write_json(Path(manifest["report_path"]), manifest)
    write_json(root / "latest.json", manifest)


def test_recomputed_bootstrap_replaces_legacy_and_never_projects_scores(tmp_path, monkeypatch):
    recompute, _ = recomputed(tmp_path, monkeypatch)
    root, history, hashes = replay(tmp_path)
    original = inputs.pq.read_table
    def guarded(path, **kwargs):
        assert "score" not in kwargs.get("columns", [])
        assert not any("return" in key for key in kwargs.get("columns", []))
        assert Path(path).name != "predictions.parquet"
        return original(path, **kwargs)
    monkeypatch.setattr(inputs.pq, "read_table", guarded)
    result = inputs.load_priority_history(root, history, expected_replay_hashes=hashes, recomputed_root=recompute)
    assert len(result["bootstrap_records"]) == 80
    assert result["bootstrap_records"][0]["ticker"] == "R01"
    assert {row["record_kind"] for row in result["bootstrap_records"]} == {"historical_replay"}
    assert not result["records"]
    assert result["provenance"]["recomputed_coverage"][0]["status"] == "PARTIAL"


def test_incomplete_recomputed_top40_excluded_without_silent_legacy_fallback(tmp_path, monkeypatch):
    recompute, _ = recomputed(tmp_path, monkeypatch, eligible=39)
    root, history, hashes = replay(tmp_path)
    result = inputs.load_priority_history(root, history, expected_replay_hashes=hashes, recomputed_root=recompute)
    assert not result["bootstrap_records"]
    assert len(result["provenance"]["excluded_priority_files"]) == 2


def test_recomputed_keeps_latest_60_reliable_result_dates(tmp_path, monkeypatch):
    days = pd.bdate_range("2026-05-27", periods=65).strftime("%Y-%m-%d").tolist()
    recompute, _ = recomputed(tmp_path, monkeypatch, days=days)
    root, history, hashes = replay(tmp_path)
    result = inputs.load_priority_history(root, history, expected_replay_hashes=hashes, recomputed_root=recompute)
    assert len(result["bootstrap_records"]) == 60 * 40
    assert result["available_dates"] == days[-60:]


@pytest.mark.parametrize("key,change,reason", [
    ("top40", lambda frame: frame.__setitem__("model_sha256", "0" * 64), "ROW_MODEL_OR_DATE"),
    ("top40", lambda frame: frame.__setitem__("rank", 1), "DUPLICATE_RANK_OR_TICKER"),
    ("coverage", lambda frame: frame.__setitem__("eligible_count", 41.5), "COUNTS_INVALID"),
    ("coverage", lambda frame: frame.__setitem__("status", "READY"), "FALSE_COMPLETE_COVERAGE"),
    ("schedule", lambda frame: frame.__setitem__("snapshot_effective_date", "2026-08-13"), "POOL_OR_PIT"),
    ("schedule", lambda frame: frame.__setitem__("snapshot_effective_date", None), "POOL_OR_PIT"),
])
def test_recomputed_rejects_model_rank_coverage_and_future_identity(tmp_path, monkeypatch, key, change, reason):
    recompute, manifest = recomputed(tmp_path, monkeypatch)
    update_recomputed(recompute, manifest, key, change)
    root, history, hashes = replay(tmp_path)
    with pytest.raises(inputs.InputError, match=reason):
        inputs.load_priority_history(root, history, expected_replay_hashes=hashes, recomputed_root=recompute)


def test_recomputed_output_tampering_is_rejected_before_projection(tmp_path, monkeypatch):
    recompute, manifest = recomputed(tmp_path, monkeypatch)
    Path(manifest["outputs"]["top40"]["path"]).write_bytes(b"tampered")
    root, history, hashes = replay(tmp_path)
    monkeypatch.setattr(inputs.pq, "read_table", lambda *a, **kw: pytest.fail("unverified bytes projected"))
    with pytest.raises(inputs.InputError, match="HASH_MISMATCH"):
        inputs.load_priority_history(root, history, expected_replay_hashes=hashes, recomputed_root=recompute)


def test_recomputed_pointer_must_match_immutable_run_manifest(tmp_path, monkeypatch):
    recompute, manifest = recomputed(tmp_path, monkeypatch)
    write_json(recompute / "latest.json", {**manifest, "status": "READY"})
    root, history, hashes = replay(tmp_path)
    with pytest.raises(inputs.InputError, match="MANIFEST_IDENTITY"):
        inputs.load_priority_history(root, history, expected_replay_hashes=hashes, recomputed_root=recompute)


def test_real_daily_recommendation_stays_separate_and_overrides_recomputed_date(tmp_path, monkeypatch):
    recompute, _ = recomputed(tmp_path, monkeypatch)
    root, history, hashes = replay(tmp_path)
    write_json(history / "today.json", {"status": "READY", "model_id": inputs.MODEL_ID,
        "model_sha256": inputs.MODEL_SHA256, "data_date": "2026-08-13", "generated_at": "2026-08-14T00:00:00+00:00",
        "input_manifest_sha256": "a" * 64, "run_id": "real-daily",
        "ranked_rows": [{"rank": rank, "ticker": f"D{rank:02}"} for rank in range(1, 41)]})
    result = inputs.load_priority_history(root, history, expected_replay_hashes=hashes, recomputed_root=recompute)
    assert len(result["records"]) == 40
    assert result["records"][0]["ticker"] == "D01"
    assert result["records"][0]["record_kind"] == "daily_recommendation"
    assert result["bootstrap_records"][-40]["ticker"] == "R01"


def test_default_recomputed_discovery_does_not_require_obsolete_legacy_files(tmp_path, monkeypatch):
    recompute, _ = recomputed(tmp_path, monkeypatch)
    history = tmp_path / "A2_today_recommendation" / "history"
    history.mkdir(parents=True)
    result = inputs.load_priority_history(tmp_path / "nonexistent_legacy", history)
    assert result["provenance"]["recomputed_root"] == str(recompute.resolve())
    assert result["bootstrap_records"][0]["ticker"] == "R01"



def quarterly_registry(tmp_path, core_count=23):
    rows = [{"manager_id": f"core{i:02}", "manager_name": f"Core {i}", "cik": str(i+1),
             "enabled": "True", "active_from_quarter": "2020Q1", "active_to_quarter": "",
             "top_n": "100", "protected_top_n": "20", "manager_weight": "1", "required_for_gate": "True"}
            for i in range(core_count)]
    rows.append({**rows[0], "manager_id": "situational_awareness", "manager_name": "Synthetic late filer",
                 "cik": "99999", "active_from_quarter": "2024Q4"})
    registry = tmp_path / "manager_registry.csv"
    pd.DataFrame(rows).to_csv(registry, index=False)
    return registry


def quarterly_universe(tmp_path, quarter):
    from scripts.storage.refresh_13f_quarter import manager_roster_identity
    binding = universe(tmp_path)
    registry = quarterly_registry(tmp_path)
    roster = manager_roster_identity(pd.read_csv(registry, dtype=str, keep_default_na=False), quarter)
    manifest = Path(binding["readiness_sources"]["universe_manifest"]["path"])
    schedule = pd.read_parquet(manifest)
    schedule["quarter"] = quarter
    schedule["institution_count"] = roster["applicable_manager_count"]
    schedule["manager_roster_sha256"] = roster["roster_sha256"]
    schedule.to_parquet(manifest)
    binding["readiness_sources"]["universe_manifest"]["sha256"] = inputs.sha256_file(manifest)
    members = Path(binding["readiness_sources"]["universe_members"]["path"])
    frame = pd.read_parquet(members)
    frame["quarter"] = quarter
    frame.to_parquet(members)
    binding["readiness_sources"]["universe_members"]["sha256"] = inputs.sha256_file(members)
    binding["readiness_sources"]["manager_registry"] = {"path": str(registry), "sha256": inputs.sha256_file(registry)}
    return binding


@pytest.mark.parametrize("quarter,count", [("2024Q3", 23), ("2024Q4", 24), ("2025Q3", 24)])
def test_bound_quarter_roster_excludes_not_yet_filing_and_keeps_later_sa(tmp_path, quarter, count):
    binding = quarterly_universe(tmp_path, quarter)
    result = inputs.load_bound_universe(binding, "2026-06-01", required_quarter=quarter)
    assert result["current"]
    assert result["applicable_manager_count"] == count
    ids = result["quarter_manager_roster"]["applicable_manager_ids"]
    assert ("situational_awareness" in ids) == (quarter >= "2024Q4")


@pytest.mark.parametrize("mutation,reason", [
    (lambda frame: frame.__setitem__("institution_count", 22), "ROSTER_COUNT_MISMATCH"),
    (lambda frame: frame.__setitem__("manager_roster_sha256", "0" * 64), "ROSTER_IDENTITY_MISMATCH"),
    (lambda frame: frame.drop(columns=["manager_roster_sha256"], inplace=True), "ROSTER_IDENTITY_MISSING"),
])
def test_bound_quarter_rejects_incomplete_or_wrong_roster(tmp_path, mutation, reason):
    binding = quarterly_universe(tmp_path, "2024Q3")
    reference = binding["readiness_sources"]["universe_manifest"]
    frame = pd.read_parquet(reference["path"])
    mutation(frame)
    frame.to_parquet(reference["path"])
    reference["sha256"] = inputs.sha256_file(reference["path"])
    with pytest.raises(inputs.InputError, match=reason):
        inputs.load_bound_universe(binding, "2026-06-01", required_quarter="2024Q3")


def test_legacy_frozen_binding_cannot_silently_change_cohort(tmp_path):
    binding = universe(tmp_path)
    reference = binding["readiness_sources"]["universe_manifest"]
    frame = pd.read_parquet(reference["path"])
    frame["institution_count"] = 23
    frame.to_parquet(reference["path"])
    reference["sha256"] = inputs.sha256_file(reference["path"])
    with pytest.raises(inputs.InputError, match="ROSTER_COUNT_MISMATCH"):
        inputs.load_bound_universe(binding, "2026-06-01")


@pytest.mark.parametrize("reference", [None, {}, {"path": "missing"}])
def test_explicit_invalid_manager_registry_cannot_fall_back_to_legacy(tmp_path, monkeypatch, reference):
    binding = universe(tmp_path)
    binding["readiness_sources"]["manager_registry"] = reference
    monkeypatch.setattr(inputs.pq, "read_table", lambda *a, **k: pytest.fail("invalid roster decoded"))
    with pytest.raises(inputs.InputError, match="MANAGER_REGISTRY_REFERENCE_INVALID"):
        inputs.load_bound_universe(binding, "2026-06-01")
