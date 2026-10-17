"""Published cash-start snapshots survive a later READY or BLOCKED update."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.research.a2.portfolio import selected_hgb as backend
from apps.demo_console.adapters import selected_strategies_reader as selected
from apps.demo_console.adapters import stock_history_reader as stocks
from apps.demo_console.tests.test_stock_history_reader import applied_fixture


def bound_package(tmp_path, monkeypatch, day="2026-09-24", *, mutable=False):
    raw, package = applied_fixture()
    frozen = {}
    for relative in ("models/hgb_2026092501.joblib", "optimize_route.py"):
        path = tmp_path / "frozen" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
        frozen[relative] = backend.digest(path)
    monkeypatch.setattr(backend, "FROZEN_HASHES", frozen)
    refs = {"frozen/" + relative: {"path": str(tmp_path / "frozen" / relative), "sha256": sha}
            for relative, sha in frozen.items()}
    feature = tmp_path / (day + "_features.parquet")
    feature.write_bytes((day + " real frozen inference inputs").encode())
    refs["current/selected_hgb_features.parquet"] = {"path": str(feature), "sha256": backend.digest(feature)}
    report = tmp_path / ("latest.json" if mutable else day + "_recommendation.json")
    rows = package["shared_scores"]["current"]["rows"]
    report.write_text(json.dumps({"status": "READY", "data_date": day, "model_id": "A2_HGB",
        "model_sha256": backend.A2_MODEL_SHA256,
        "selected_hgb_features": {**refs["current/selected_hgb_features.parquet"], "signal_date": day},
        "ranked_rows": [{"ticker": row["ticker"], "security_id": row["security_id"],
                         "rank": row["raw_rank"], "score": row["raw_score"]} for row in rows]}), encoding="utf-8")
    refs["current/report.json"] = {"path": str(report), "sha256": backend.digest(report)}
    package.update(source_refs=refs, source_hashes={key: ref["sha256"] for key, ref in refs.items()},
                   model_fit_calls=0, broker_action_allowed=False, source_root=str(tmp_path / "frozen"))
    package["shared_scores"]["model_sha256"] = frozen["models/hgb_2026092501.joblib"]
    package["shared_scores"]["current"].update(signal_date=day, requested_signal_date=day)
    for app in (strategy["application"] for strategy in package["strategies"].values()):
        app.update(signal_date=day, requested_signal_date=day, cash_weight_before=1.,
            decision_clock="SIGNAL_CLOSE_NEXT_SESSION_OPEN", model_fit_calls=0, broker_action_allowed=False)
    return raw, selected.validate_package(package)


def block_for(package, day):
    result = deepcopy(package)
    result["shared_scores"]["current"] = {"status": "BLOCKED", "signal_date": None,
        "requested_signal_date": day, "rows": [], "reason": "CURRENT_FEATURES_HASH_FAILED"}
    for sid in backend.STRATEGY_IDS:
        result["strategies"][sid]["application"] = backend._blocked("CURRENT_FEATURES_HASH_FAILED", day)
    return result


@pytest.mark.parametrize("change", ["prediction", "target"])
def test_date_archive_is_lightweight_idempotent_and_rejects_conflicting_decision(tmp_path, monkeypatch, change):
    _, package = bound_package(tmp_path, monkeypatch)
    folder = tmp_path / "published/history"
    first = backend.archive_current_snapshot(package, folder)
    package["generated_at"] = "2026-09-26T02:00:00+00:00"
    assert backend.archive_current_snapshot(package, folder) == first
    snapshot = json.loads((folder / "2026-09-24.json").read_text(encoding="utf-8"))
    assert "daily" not in snapshot and "strategies" not in snapshot and "historical" not in snapshot["shared_scores"]
    assert len(snapshot["shared_scores"]["rows"]) == 40
    assert all(app["account_basis"] == "CASH_START" and app["execution_status"] == "TARGET_ONLY"
               for app in snapshot["applications"].values())
    if change == "prediction":
        package["shared_scores"]["current"]["rows"][0]["pred_hgb"] += .000001
    else:
        app = package["strategies"][backend.STRATEGY_IDS[0]]["application"]
        app["rows"][0]["target_weight"] -= .001
        app["target_cash_weight"] += .001
    with pytest.raises(backend.SelectedStrategyError, match="SAME_DATE_CONFLICT"):
        backend.archive_current_snapshot(package, folder)
    assert not list(folder.glob("*.tmp"))


def test_external_package_requires_recorded_hash_and_frozen_source_bytes(tmp_path, monkeypatch):
    _, package = bound_package(tmp_path, monkeypatch)
    origin = tmp_path / "origin.json"
    origin.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(backend.SelectedStrategyError, match="SOURCE_HASH_REQUIRED"):
        backend.archive_current_snapshot(origin, tmp_path / "history")
    with pytest.raises(backend.SelectedStrategyError, match="SOURCE_HASH_MISMATCH"):
        backend.archive_current_snapshot(origin, tmp_path / "history", "0" * 64)
    package["shared_scores"]["model_sha256"] = "0" * 64
    with pytest.raises(backend.SelectedStrategyError, match="FROZEN_MODEL"):
        backend.archive_current_snapshot(package, tmp_path / "history")
    package["shared_scores"]["model_sha256"] = backend.FROZEN_HASHES["models/hgb_2026092501.joblib"]
    (tmp_path / "frozen/optimize_route.py").write_bytes(b"changed code")
    with pytest.raises(backend.SelectedStrategyError, match="SOURCE_HASH_MISMATCH"):
        backend.archive_current_snapshot(package, tmp_path / "history")


@pytest.mark.parametrize("blocked", [False, True])
def test_publish_rotation_keeps_scores_cash_start_targets_and_original_nav(tmp_path, monkeypatch, blocked):
    raw, old = bound_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    _, next_package = bound_package(tmp_path, monkeypatch, "2026-09-25")
    if blocked:
        next_package = block_for(next_package, "2026-09-25")
    before = deepcopy(next_package)
    backend.publish(next_package, output)
    persisted = selected.load_package(output)
    snapshot = selected.score_snapshot("2026-09-24", package=persisted)
    assert snapshot["rows"] == old["shared_scores"]["current"]["rows"]
    assert len(selected.score_history(package=persisted, start_date="2026-09-24", end_date="2026-09-24")) == 40
    for sid in backend.STRATEGY_IDS:
        actual = selected.workspace_view(sid, "2026-09-24", package=persisted)
        assert actual["target"]["rows"] == old["strategies"][sid]["application"]["rows"]
        assert actual["target"]["account_basis"] == "CASH_START"
        assert actual["target"]["execution_status"] == "TARGET_ONLY"
        assert actual["target"]["kind"] == "ARCHIVED_CASH_START_TARGET"
        assert persisted["strategies"][sid]["targets"] == before["strategies"][sid]["targets"]
        assert persisted["strategies"][sid]["daily"] == before["strategies"][sid]["daily"]
        assert selected.workspace_view(sid, "2026-09-25", package=persisted)["target"]["status"] == (
            "BLOCKED" if blocked else "READY")
    history = stocks.prepare_applied_history(raw, persisted, "2026-09-25")
    ranking = stocks.load_applied_rankings("2026-09-24", history=history)
    for sid in backend.STRATEGY_IDS:
        assert len(ranking["strategies"][sid]["rows"]) == 40
        assert ranking["strategies"][sid]["target_kind"] == "ARCHIVED_CASH_START_TARGET"
        assert ranking["strategies"][sid]["execution_status"] == "TARGET_ONLY"
    row = stocks.query_applied_history(history, "T01", "2026-09-24", "2026-09-24")["daily"][0]
    assert row["strategies"]["HGB_DIAG_5"]["target_weight"] == .1
    assert row["strategies"]["HGB_FACTOR_5"]["target_weight"] == 0
    assert row["strategies"]["HGB_DIAG_5"]["account_basis"] == "CASH_START"
    cutoff = stocks.prepare_applied_history(raw, persisted, "2026-09-23")
    assert "2026-09-24" not in cutoff["_scores"]
    assert all("2026-09-24" not in targets for targets in cutoff["_targets"].values())
    assert persisted["model_fit_calls"] == 0 and persisted["broker_action_allowed"] is False


def test_mutable_report_pointer_can_rotate_after_snapshot_is_verified(tmp_path, monkeypatch):
    _, package = bound_package(tmp_path, monkeypatch, mutable=True)
    folder = tmp_path / "published/history"
    first = backend.archive_current_snapshot(package, folder)
    (tmp_path / "latest.json").write_text('{"data_date":"2026-09-25"}', encoding="utf-8")
    assert backend.archive_current_snapshot(package, folder) == first
    result = block_for(package, "2026-09-25")
    backend.publish(result, tmp_path / "published/latest.json")
    assert selected.score_snapshot("2026-09-24", package=result)["status"] == "READY"
    assert result["strategies"][backend.STRATEGY_IDS[0]]["application_history"][0]["signal_date"] == "2026-09-24"


def test_normal_publication_archives_before_rotating_a_mutable_daily_pointer(tmp_path, monkeypatch):
    _, package = bound_package(tmp_path, monkeypatch, mutable=True)
    output = tmp_path / "published/latest.json"
    backend.publish(package, output)
    _, newer = bound_package(tmp_path, monkeypatch, "2026-09-25", mutable=True)
    backend.publish(newer, output)
    loaded = selected.load_package(output)
    assert selected.score_snapshot("2026-09-24", package=loaded)["rows"] == package["shared_scores"]["current"]["rows"]
    assert sorted(path.name for path in output.parent.joinpath("history").glob("*.json")) == ["2026-09-24.json", "2026-09-25.json"]


def test_three_date_rotation_preserves_first_snapshot_despite_merged_history_and_new_timestamp(tmp_path, monkeypatch):
    _, day0 = bound_package(tmp_path, monkeypatch, "2026-09-23", mutable=True)
    folder = tmp_path / "published/history"
    backend.archive_current_snapshot(day0, folder)
    _, day1 = bound_package(tmp_path, monkeypatch, "2026-09-24", mutable=True)
    output = folder.parent / "latest.json"
    backend.publish(day1, output)
    assert day1["strategies"][backend.STRATEGY_IDS[0]]["application_history"][0]["signal_date"] == "2026-09-23"
    first = (folder / "2026-09-24.json").read_bytes()
    # Re-archive the enriched persisted package, with changed observation time.
    persisted = selected.load_package(output)
    persisted["generated_at"] = "2026-09-25T03:00:00+00:00"
    backend.archive_current_snapshot(persisted, folder)
    assert first == (folder / "2026-09-24.json").read_bytes()
    _, day2 = bound_package(tmp_path, monkeypatch, "2026-09-25", mutable=True)
    backend.publish(day2, output)
    assert first == (folder / "2026-09-24.json").read_bytes()
    assert [app["signal_date"] for app in day2["strategies"][backend.STRATEGY_IDS[0]]["application_history"]] == [
        "2026-09-23", "2026-09-24"]
    assert len(selected.score_history(package=day2, start_date="2026-09-23", end_date="2026-09-24")) == 80


def test_cash_start_archive_rejects_targets_outside_raw_top20(tmp_path, monkeypatch):
    _, package = bound_package(tmp_path, monkeypatch)
    package["strategies"][backend.STRATEGY_IDS[0]]["application"]["rows"][0]["ticker"] = "T40"
    with pytest.raises(backend.SelectedStrategyError, match="CASH_START_WEIGHT_INVALID"):
        backend.archive_current_snapshot(package, tmp_path / "history")


def test_tampered_snapshot_is_rejected_before_publication(tmp_path, monkeypatch):
    _, package = bound_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(package, output)
    original = output.read_bytes()
    path = output.parent / "history/2026-09-24.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["applications"][backend.STRATEGY_IDS[0]]["rows"][0]["target_weight"] = .09
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(backend.SelectedStrategyError, match="SNAPSHOT_HASH"):
        backend.publish(block_for(package, "2026-09-25"), output)
    assert output.read_bytes() == original


@pytest.mark.parametrize("field,value", [("execution_status", "EXECUTED"), ("account_basis", "REAL_ACCOUNT"),
                                        ("future_open", 100), ("source_ref", "history/2026-09-23.json")])
def test_reader_rejects_invalid_archive_semantics_and_unknown_fields(tmp_path, monkeypatch, field, value):
    _, package = bound_package(tmp_path, monkeypatch)
    backend.archive_current_snapshot(package, tmp_path / "history")
    result = block_for(package, "2026-09-25")
    backend._merge_archived_snapshots(result, tmp_path / "history")
    result["strategies"][backend.STRATEGY_IDS[0]]["application_history"][0][field] = value
    with pytest.raises(ValueError, match="application_history"):
        selected.validate_package(result)


def test_history_never_archives_a_blocked_or_backtest_fallback_as_current(tmp_path, monkeypatch):
    _, package = bound_package(tmp_path, monkeypatch)
    for sid in backend.STRATEGY_IDS:
        package["strategies"][sid]["application"]["status"] = "LATEST_AVAILABLE_SIGNAL"
    with pytest.raises(backend.SelectedStrategyError, match="CASH_START_TARGET_REQUIRED"):
        backend.archive_current_snapshot(package, tmp_path / "history")
    result = block_for(package, "2026-09-25")
    backend.publish(result, tmp_path / "published/latest.json")
    assert not list((tmp_path / "published/history").glob("*.json"))


def repair_package(tmp_path, monkeypatch):
    _, old = bound_package(tmp_path, monkeypatch)
    new = deepcopy(old)
    current = new["shared_scores"]["current"]
    # Preserve frozen model ranks while changing a real source-bound score.
    current["rows"][0]["raw_score"] += .001
    feature = tmp_path / "repaired_features.parquet"
    feature.write_bytes(b"same frozen transformations; repaired native input")
    feature_ref = {"path": str(feature), "sha256": backend.digest(feature)}
    old_ref = old["source_refs"]["current/report.json"]
    report = json.loads(Path(old_ref["path"]).read_text(encoding="utf-8"))
    audit_path = tmp_path / "repair_lineage.json"
    audit = {"schema": "A2_OFFLINE_INPUT_REPAIR_V1", "network_requests_this_run": 0,
        "status": "INPUTS_VERIFIED", "target_date": "2026-09-24", "run_id": "synthetic_repair",
        "parent_inputs": [old_ref], "model_fit_count": 0, "parameter_search_count": 0,
        "old_date_keys_retained": True, "old_rows_unchanged": True, "unrelated_current_keys_unchanged": True,
        "reason": "native required input repaired without selection"}
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    repair_ref = {"path": str(audit_path), "sha256": backend.digest(audit_path)}
    report.update(run_id=audit["run_id"], repair_lineage=repair_ref,
        selected_hgb_features={**feature_ref, "signal_date": "2026-09-24"})
    report["ranked_rows"] = [{"ticker": row["ticker"], "security_id": row["security_id"],
        "rank": row["raw_rank"], "score": row["raw_score"]} for row in current["rows"]]
    report_path = tmp_path / "repaired_recommendation.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    new["source_refs"]["current/report.json"] = {"path": str(report_path), "sha256": backend.digest(report_path)}
    new["source_refs"]["current/selected_hgb_features.parquet"] = feature_ref
    new["source_hashes"] = {key: ref["sha256"] for key, ref in new["source_refs"].items()}
    return old, new, repair_ref


def test_input_repair_revision_preserves_base_and_normal_repeat_is_idempotent(tmp_path, monkeypatch):
    old, new, repair = repair_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    base = output.parent / "history/2026-09-24.json"
    original = base.read_bytes()
    with pytest.raises(backend.SelectedStrategyError):
        backend.publish(deepcopy(new), output)
    backend.publish(new, output, snapshot_repair=repair)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    ref = persisted["source_refs"]["history/2026-09-24.json"]
    revision = Path(ref["path"])
    assert revision.parent == base.parent / "revisions/2026-09-24"
    assert backend.digest(revision) == ref["sha256"]
    assert base.read_bytes() == original
    receipt_ref = persisted["source_refs"]["history_revision/2026-09-24.json"]
    receipt = json.loads(Path(receipt_ref["path"]).read_text(encoding="utf-8"))
    assert receipt["supersedes"] == {"path": str(base.resolve()), "sha256": backend.digest(base)}
    assert receipt["replacement"] == ref
    revision_bytes, receipt_bytes = revision.read_bytes(), Path(receipt_ref["path"]).read_bytes()
    persisted["generated_at"] = "2026-09-25T01:00:00+00:00"
    backend.publish(persisted, output)
    backend.publish(persisted, output, snapshot_repair=repair)
    assert revision.read_bytes() == revision_bytes
    assert Path(receipt_ref["path"]).read_bytes() == receipt_bytes
    assert base.read_bytes() == original
    # A stale package carrying the older current input cannot silently revert.
    with pytest.raises(backend.SelectedStrategyError):
        backend.publish(deepcopy(old), output)


@pytest.mark.parametrize("blocked", [False, True])
def test_next_day_uses_published_revision_for_implicit_and_explicit_previous(tmp_path, monkeypatch, blocked):
    old, new, repair = repair_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    backend.publish(new, output, snapshot_repair=repair)
    previous = json.loads(output.read_text(encoding="utf-8"))
    # A syntactically plausible unpublished file must never win by mtime/name.
    orphan = output.parent / "history/revisions/2026-09-24/zzz_orphan.json"
    orphan.write_text("{}", encoding="utf-8")
    _, following = bound_package(tmp_path, monkeypatch, "2026-09-25")
    if blocked: following = block_for(following, "2026-09-25")
    implicit, explicit_path, explicit_mapping = deepcopy(following), deepcopy(following), deepcopy(following)
    backend._merge_archived_snapshots(implicit, output.parent / "history")
    backend._merge_archived_snapshots(explicit_path, output.parent / "history", previous=output)
    backend._merge_archived_snapshots(explicit_mapping, output.parent / "history", previous=previous)
    assert implicit["shared_scores"]["historical"] == explicit_path["shared_scores"]["historical"] == explicit_mapping["shared_scores"]["historical"]
    assert implicit["source_refs"]["history/2026-09-24.json"] == previous["source_refs"]["history/2026-09-24.json"]
    backend.publish(implicit, output)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert selected.score_snapshot("2026-09-24", package=saved)["rows"] == new["shared_scores"]["current"]["rows"]


@pytest.mark.parametrize("change", ["revision_bytes", "receipt_bytes", "selected_sha", "receipt_sha", "missing_revision"])
def test_selected_revision_tamper_rejects_and_keeps_latest(tmp_path, monkeypatch, change):
    old, new, repair = repair_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    backend.publish(new, output, snapshot_repair=repair)
    before = output.read_bytes()
    current = json.loads(before)
    selected_ref = current["source_refs"]["history/2026-09-24.json"]
    receipt_ref = current["source_refs"]["history_revision/2026-09-24.json"]
    if change == "revision_bytes": Path(selected_ref["path"]).write_bytes(b"tampered")
    elif change == "receipt_bytes": Path(receipt_ref["path"]).write_bytes(b"tampered")
    elif change == "missing_revision": Path(selected_ref["path"]).unlink()
    elif change == "selected_sha": current["source_hashes"]["history/2026-09-24.json"] = "0" * 64
    elif change == "receipt_sha": current["source_hashes"]["history_revision/2026-09-24.json"] = "0" * 64
    with pytest.raises((backend.SelectedStrategyError, OSError)):
        backend._merge_archived_snapshots(block_for(new, "2026-09-25"), output.parent / "history", previous=current)
    assert output.read_bytes() == before


@pytest.mark.parametrize("change", ["target_date", "parent_ref", "fit", "preservation", "audit_hash", "loose_mapping", "schema", "network"])
def test_revision_repair_authorization_must_be_exact_bound_audit(tmp_path, monkeypatch, change):
    old, new, repair = repair_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    before = output.read_bytes()
    audit_path = Path(repair["path"])
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if change == "audit_hash": repair["sha256"] = "0" * 64
    elif change == "loose_mapping": repair["allow"] = True
    else:
        if change == "target_date": audit["target_date"] = "2026-09-23"
        elif change == "parent_ref": audit["parent_inputs"] = []
        elif change == "fit": audit["model_fit_count"] = 1
        elif change == "preservation": audit["old_rows_unchanged"] = False
        elif change == "schema": audit["schema"] = "LOOSE_OVERRIDE"
        elif change == "network": audit["network_requests_this_run"] = 1
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        repair["sha256"] = backend.digest(audit_path)
        report_path = Path(new["source_refs"]["current/report.json"]["path"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["repair_lineage"] = repair
        report_path.write_text(json.dumps(report), encoding="utf-8")
        sha = backend.digest(report_path)
        new["source_refs"]["current/report.json"]["sha256"] = sha
        new["source_hashes"]["current/report.json"] = sha
    with pytest.raises(backend.SelectedStrategyError):
        backend.publish(new, output, snapshot_repair=repair)
    assert output.read_bytes() == before
    assert not list((output.parent / "history/revisions").glob("**/*.json"))


@pytest.mark.parametrize("change", ["snapshot_outside", "snapshot_nested", "receipt_outside", "supersedes_outside"])
def test_revision_paths_are_rejected_before_hashing_or_reading_outside(tmp_path, monkeypatch, change):
    old, new, repair = repair_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    backend.publish(new, output, snapshot_repair=repair)
    current = json.loads(output.read_text(encoding="utf-8"))
    before = output.read_bytes()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"must never be read")
    selected_ref = current["source_refs"]["history/2026-09-24.json"]
    receipt_ref = current["source_refs"]["history_revision/2026-09-24.json"]
    if change.startswith("snapshot"):
        selected_ref["path"] = str(outside) if change == "snapshot_outside" else str(Path(selected_ref["path"]).parent / "nested" / Path(selected_ref["path"]).name)
    elif change == "receipt_outside": receipt_ref["path"] = str(outside)
    else:
        receipt_path = Path(receipt_ref["path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["supersedes"] = {"path": str(outside), "sha256": "a" * 64}
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        receipt_ref["sha256"] = backend.digest(receipt_path)
        current["source_hashes"]["history_revision/2026-09-24.json"] = receipt_ref["sha256"]
    digest, read = backend.digest, backend._json
    def guarded_digest(path):
        assert Path(path).resolve() != outside.resolve(), "outside digest was called"
        return digest(path)
    def guarded_read(path):
        assert Path(path).resolve() != outside.resolve(), "outside read was called"
        return read(path)
    monkeypatch.setattr(backend, "digest", guarded_digest)
    monkeypatch.setattr(backend, "_json", guarded_read)
    with pytest.raises(backend.SelectedStrategyError, match="PATH_INVALID"):
        backend._merge_archived_snapshots(block_for(new, "2026-09-25"), output.parent / "history", previous=current)
    assert output.read_bytes() == before


def rerun_same_decision(tmp_path, package):
    """Synthetic fresh report/run plus a byte-identical copy of the frozen input."""
    result = deepcopy(package)
    refs = result["source_refs"]
    feature = tmp_path / "new_run" / "selected_hgb_features.parquet"
    feature.parent.mkdir()
    feature.write_bytes(Path(refs["current/selected_hgb_features.parquet"]["path"]).read_bytes())
    feature_ref = {"path": str(feature.resolve()), "sha256": backend.digest(feature)}
    report = json.loads(Path(refs["current/report.json"]["path"]).read_text(encoding="utf-8"))
    report.update(run_id="synthetic_reobserved", generated_at="2026-09-25T01:00:00+00:00",
                  selected_hgb_features={**feature_ref, "signal_date": report["data_date"]})
    report_path = feature.parent / "recommendation_source.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    refs["current/report.json"] = {"path": str(report_path.resolve()), "sha256": backend.digest(report_path)}
    refs["current/selected_hgb_features.parquet"] = feature_ref
    result["source_hashes"] = {key: ref["sha256"] for key, ref in refs.items()}
    return result


def test_new_run_same_decision_reuses_immutable_snapshot_and_remains_next_day_idempotent(tmp_path, monkeypatch):
    _, old = bound_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    archive = output.parent / "history/2026-09-24.json"
    before = archive.read_bytes()
    original_ref = old["source_refs"]["history/2026-09-24.json"]
    new = rerun_same_decision(tmp_path, old)
    backend.publish(new, output)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["source_refs"]["history/2026-09-24.json"] == original_ref
    assert saved["source_refs"]["current/report.json"] == new["source_refs"]["current/report.json"]
    assert saved["source_refs"]["current/selected_hgb_features.parquet"] == new["source_refs"]["current/selected_hgb_features.parquet"]
    assert archive.read_bytes() == before
    assert not (archive.parent / "revisions").exists()
    _, following = bound_package(tmp_path, monkeypatch, "2026-09-25")
    backend.publish(following, output)
    assert archive.read_bytes() == before
    assert following["source_refs"]["history/2026-09-24.json"] == original_ref
    assert selected.score_snapshot("2026-09-24", package=following)["rows"] == old["shared_scores"]["current"]["rows"]


def test_same_decision_reobservation_preserves_accepted_input_repair_receipt(tmp_path, monkeypatch):
    old, repaired, repair = repair_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    backend.publish(repaired, output, snapshot_repair=repair)
    accepted = json.loads(output.read_text(encoding="utf-8"))
    selected_ref = accepted["source_refs"]["history/2026-09-24.json"]
    receipt_ref = accepted["source_refs"]["history_revision/2026-09-24.json"]
    original = {ref["path"]: Path(ref["path"]).read_bytes() for ref in (selected_ref, receipt_ref)}
    new = rerun_same_decision(tmp_path, accepted)
    backend.publish(new, output)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["source_refs"]["history/2026-09-24.json"] == selected_ref
    assert saved["source_refs"]["history_revision/2026-09-24.json"] == receipt_ref
    assert all(Path(path).read_bytes() == value for path, value in original.items())
    _, following = bound_package(tmp_path, monkeypatch, "2026-09-25")
    backend._merge_archived_snapshots(following, output.parent / "history")
    assert following["source_refs"]["history/2026-09-24.json"] == selected_ref
    backend.publish(following, output)
    assert all(Path(path).read_bytes() == value for path, value in original.items())


@pytest.mark.parametrize("change", ["raw_score", "prediction", "target", "feature_bytes", "other_source", "frozen_path", "application_scalar_type", "report_provenance"])
def test_reobserved_run_cannot_hide_changed_frozen_decision(tmp_path, monkeypatch, change):
    _, old = bound_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    archive = output.parent / "history/2026-09-24.json"
    original_latest, original_archive = output.read_bytes(), archive.read_bytes()
    new = rerun_same_decision(tmp_path, old)
    if change == "raw_score":
        new["shared_scores"]["current"]["rows"][0]["raw_score"] += .001
        report_path = Path(new["source_refs"]["current/report.json"]["path"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["ranked_rows"][0]["score"] += .001
        report_path.write_text(json.dumps(report), encoding="utf-8")
        new["source_refs"]["current/report.json"]["sha256"] = backend.digest(report_path)
    elif change == "prediction": new["shared_scores"]["current"]["rows"][0]["pred_hgb"] += .000001
    elif change == "target":
        app = new["strategies"][backend.STRATEGY_IDS[0]]["application"]
        app["rows"][0]["target_weight"] -= .001
        app["target_cash_weight"] += .001
    elif change == "feature_bytes":
        ref = new["source_refs"]["current/selected_hgb_features.parquet"]
        Path(ref["path"]).write_bytes(b"different qualified input, not identical")
        ref["sha256"] = backend.digest(ref["path"])
        report_path = Path(new["source_refs"]["current/report.json"]["path"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["selected_hgb_features"]["sha256"] = ref["sha256"]
        report_path.write_text(json.dumps(report), encoding="utf-8")
        new["source_refs"]["current/report.json"]["sha256"] = backend.digest(report_path)
    elif change == "frozen_path":
        ref = new["source_refs"]["frozen/optimize_route.py"]
        other = tmp_path / "copied_frozen_source.py"
        other.write_bytes(Path(ref["path"]).read_bytes())
        ref["path"] = str(other)
    elif change == "application_scalar_type":
        new["strategies"][backend.STRATEGY_IDS[0]]["application"]["model_fit_calls"] = False
    elif change == "report_provenance":
        new["source_refs"]["current/report.json"]["provider_identity"] = "changed_provenance"
    else:
        other = tmp_path / "different_original_report.json"
        other.write_text("{}", encoding="utf-8")
        new["source_refs"]["current/original_report.json"] = {"path": str(other), "sha256": backend.digest(other)}
    new["source_hashes"] = {key: ref["sha256"] for key, ref in new["source_refs"].items()}
    with pytest.raises(backend.SelectedStrategyError, match="SAME_DATE_CONFLICT"):
        backend.publish(new, output)
    assert output.read_bytes() == original_latest
    assert archive.read_bytes() == original_archive


@pytest.mark.parametrize("change", ["report_status", "report_date", "report_model", "report_feature_sha", "new_report_hash", "new_feature_hash"])
def test_same_decision_reobservation_requires_new_report_and_feature_integrity(tmp_path, monkeypatch, change):
    _, old = bound_package(tmp_path, monkeypatch)
    output = tmp_path / "published/latest.json"
    backend.publish(old, output)
    before = output.read_bytes()
    new = rerun_same_decision(tmp_path, old)
    report_path = Path(new["source_refs"]["current/report.json"]["path"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if change == "report_status": report["status"] = "BLOCKED"
    elif change == "report_date": report["data_date"] = "2026-09-25"
    elif change == "report_model": report["model_sha256"] = "a" * 64
    elif change == "report_feature_sha": report["selected_hgb_features"]["sha256"] = "a" * 64
    elif change == "new_feature_hash": Path(new["source_refs"]["current/selected_hgb_features.parquet"]["path"]).write_bytes(b"tampered")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    if change != "new_report_hash": new["source_refs"]["current/report.json"]["sha256"] = backend.digest(report_path)
    else: report_path.write_bytes(b"tampered")
    new["source_hashes"] = {key: ref["sha256"] for key, ref in new["source_refs"].items()}
    with pytest.raises(backend.SelectedStrategyError):
        backend.publish(new, output)
    assert output.read_bytes() == before



def direct_bound_package(tmp_path, monkeypatch):
    _, package = bound_package(tmp_path, monkeypatch)
    package["policy_id"] = backend.DIRECT_POLICY
    for sid, ticker in zip(backend.STRATEGY_IDS, ("T40", "T39")):
        app = package["strategies"][sid]["application"]
        app["policy_id"] = backend.DIRECT_POLICY
        app["rows"][0]["ticker"] = ticker
    return package


def test_direct_snapshot_accepts_hgb_top20_outside_raw_top20(tmp_path, monkeypatch):
    package = direct_bound_package(tmp_path, monkeypatch)
    folder = tmp_path / "direct_hgb_r1/history"
    ref = backend.archive_current_snapshot(package, folder)
    snapshot = backend._validate_snapshot(json.loads(Path(ref["path"]).read_text(encoding="utf-8")))
    assert snapshot["policy_id"] == backend.DIRECT_POLICY
    score_by_ticker = {row["ticker"]: row for row in snapshot["shared_scores"]["rows"]}
    for app in snapshot["applications"].values():
        assert app["policy_id"] == backend.DIRECT_POLICY
        for row in app["rows"]:
            score = score_by_ticker[row["ticker"]]
            assert score["raw_rank"] > 20 and score["hgb_rank"] <= 20
    assert backend.archive_current_snapshot(package, folder) == ref


@pytest.mark.parametrize("policy", [None, backend.LEGACY_POLICY, "UNKNOWN_POLICY"])
def test_direct_snapshot_cannot_be_downgraded_or_relabelled(tmp_path, monkeypatch, policy):
    package = direct_bound_package(tmp_path, monkeypatch)
    snapshot = backend._capture_snapshot(package, "ab" * 32)
    if policy is None:
        snapshot.pop("policy_id")
    else:
        snapshot["policy_id"] = policy
    snapshot["snapshot_sha256"] = backend._snapshot_hash(snapshot)
    with pytest.raises(backend.SelectedStrategyError, match="POLICY_IDENTITY_INVALID"):
        backend._validate_snapshot(snapshot)


@pytest.mark.parametrize("change", ["outside_hgb", "missing_application_policy", "unknown_package_policy"])
def test_direct_snapshot_rejects_noneligible_or_unbound_policy(tmp_path, monkeypatch, change):
    package = direct_bound_package(tmp_path, monkeypatch)
    app = package["strategies"][backend.STRATEGY_IDS[0]]["application"]
    if change == "outside_hgb":
        app["rows"][0]["ticker"] = "T01"
        message = "CASH_START_WEIGHT_INVALID"
    elif change == "missing_application_policy":
        app.pop("policy_id")
        message = "POLICY_IDENTITY_INVALID"
    else:
        package["policy_id"] = "UNKNOWN_POLICY"
        message = "POLICY_IDENTITY_INVALID"
    with pytest.raises(backend.SelectedStrategyError, match=message):
        backend._capture_snapshot(package, "ab" * 32)


def test_legacy_snapshot_keys_and_identity_ignore_explicit_legacy_package_metadata(tmp_path, monkeypatch):
    _, package = bound_package(tmp_path, monkeypatch)
    original = backend._capture_snapshot(package, "ab" * 32)
    labelled = deepcopy(package)
    labelled["policy_id"] = backend.LEGACY_POLICY
    for strategy in labelled["strategies"].values():
        strategy["application"]["policy_id"] = backend.LEGACY_POLICY
    repeated = backend._capture_snapshot(labelled, "ab" * 32)
    assert "policy_id" not in original and all("policy_id" not in app for app in original["applications"].values())
    assert repeated == original
    assert repeated["snapshot_sha256"] == original["snapshot_sha256"]
    assert json.dumps(repeated, sort_keys=True) == json.dumps(original, sort_keys=True)
    assert backend._same_snapshot_decision(repeated, original)


def test_identical_cash_start_snapshot_cannot_share_decision_identity_across_policies(tmp_path, monkeypatch):
    _, package = bound_package(tmp_path, monkeypatch)
    for strategy in package["strategies"].values():
        strategy["application"].update(rows=[], target_cash_weight=1.)
    legacy = backend._capture_snapshot(package, "ab" * 32)
    package["policy_id"] = backend.DIRECT_POLICY
    for strategy in package["strategies"].values():
        strategy["application"]["policy_id"] = backend.DIRECT_POLICY
    direct = backend._capture_snapshot(package, "ab" * 32)
    assert direct["snapshot_sha256"] != legacy["snapshot_sha256"]
    assert not backend._same_snapshot_decision(direct, legacy)


def direct_repaired_research_fixture(tmp_path, monkeypatch):
    """Two accepted cash vintages and one unchanged synthetic research ledger."""
    import pandas as pd
    from scripts.research.a2.evaluation import selected_performance_update as update
    from scripts.research.a2.evaluation import three_strategy_extension as producer
    old, repaired, receipt = repair_package(tmp_path, monkeypatch)
    for package in (old, repaired):
        package['policy_id'] = backend.DIRECT_POLICY
        for sid, ticker in zip(backend.STRATEGY_IDS, ('T40', 'T39')):
            package['strategies'][sid]['application']['policy_id'] = backend.DIRECT_POLICY
            package['strategies'][sid]['application']['rows'][0]['ticker'] = ticker
    period = {**old['performance_period'], 'end': '2026-09-25', 'days': 3,
              'price_basis': 'PIT_FORWARD_REHAB_INDEX'}
    strategies = {sid: deepcopy(old['strategies'].get(sid, old['raw_reference']))
                  for sid in ('RAW_A2', *backend.STRATEGY_IDS)}
    for sid, strategy in strategies.items():
        strategy['daily'][-1]['date'] = period['end']
        strategy['targets'][-1]['signal_date'] = '2026-09-24'
        strategy['outputs'] = {}
        for kind in ('daily', 'targets'):
            path = tmp_path / (sid + '_' + kind + '.parquet')
            pd.DataFrame(strategy[kind]).to_parquet(path, index=False)
            strategy['outputs'][kind] = producer.reference(path)
    scores = deepcopy(old['shared_scores']['historical']) + [
        {**row, 'signal_date': '2026-09-24'} for row in old['shared_scores']['current']['rows']]
    manifest = {'source_id': 'NEW_PIT_COMPARISON', 'policy_id': backend.DIRECT_POLICY,
        'model_fit_calls': 0, 'broker_action_allowed': False, 'status': 'READY', 'blocked_next': None,
        'performance_period': period, 'requested_end_date': period['end'], 'strategies': strategies,
        'shared_scores_historical': scores, 'source_refs': list(old['source_refs'].values()),
        'cost_one_way': .0005, 'initial_cash_coordinate': 1., 'limitations': []}
    path = tmp_path / 'research_manifest.json'; path.write_text(json.dumps(manifest), encoding='utf8')
    contract = tmp_path / 'frozen_contract.json'; contract.write_text('synthetic frozen contract', encoding='utf8')
    for package in (old, repaired):
        package['performance_period'] = deepcopy(period)
        for sid in backend.STRATEGY_IDS:
            for key in ('daily', 'targets', 'summary'):
                package['strategies'][sid][key] = deepcopy(strategies[sid][key])
        package['raw_reference'] = {**deepcopy(strategies['RAW_A2']), 'strategy_id': 'RAW_A2',
                                    'performance_period': deepcopy(period)}
        package['shared_scores']['historical'] = deepcopy(scores)
        package['performance_extension'] = {key: deepcopy(manifest[key]) for key in (
            'source_id', 'model_fit_calls', 'broker_action_allowed', 'status', 'blocked_next',
            'performance_period', 'requested_end_date', 'cost_one_way', 'initial_cash_coordinate')}
        package['performance_extension']['manifest'] = producer.reference(path)
        for key, ref in [('performance_extension/manifest', producer.reference(path)),
                         ('policy/frozen_contract', producer.reference(contract))]:
            package['source_refs'][key] = ref
            package['source_hashes'][key] = ref['sha256']
    output = tmp_path / 'daily/direct_hgb_r1/latest.json'
    backend.publish(old, output)
    backend.publish(repaired, output, snapshot_repair=receipt)
    accepted = json.loads(output.read_text(encoding='utf8'))
    update.verified_direct_research(accepted)
    return old, accepted, manifest, path, output, producer.reference(contract)


def test_direct_accepted_cash_revision_projects_ui_without_rewriting_executed_research(tmp_path, monkeypatch):
    old, accepted, manifest, path, output, _ = direct_repaired_research_fixture(tmp_path, monkeypatch)
    originals = {p: p.read_bytes() for p in [path, *[Path(r['path']) for k,r in accepted['source_refs'].items()
        if k.startswith(('history/', 'history_revision/'))]]}
    following = block_for(accepted, '2026-09-25')
    backend._merge_archived_snapshots(following, output.parent/'history', previous=accepted)
    cash = [{**r, 'signal_date': '2026-09-24'} for r in accepted['shared_scores']['current']['rows']]
    assert [r for r in following['shared_scores']['historical'] if r['signal_date']=='2026-09-24'] == cash
    assert cash != [r for r in manifest['shared_scores_historical'] if r['signal_date']=='2026-09-24']
    assert following['strategies']['HGB_DIAG_5']['application_history'][-1]['rows'][0]['ticker']=='T40'
    selected.validate_package(following)
    backend.publish(following, output)
    assert all(p.read_bytes()==b for p,b in originals.items())
    for sid in backend.STRATEGY_IDS:
        assert following['strategies'][sid]['daily']==manifest['strategies'][sid]['daily']
        assert following['strategies'][sid]['targets']==manifest['strategies'][sid]['targets']


@pytest.mark.parametrize('change', ['unbound_revision','fake_receipt','bad_manifest_hash','wrong_research_group',
                                   'unbound_manifest','wrong_model','ordinary_base'])
def test_direct_cash_projection_rejects_unbound_forged_or_nonresearch_difference(tmp_path, monkeypatch, change):
    old, accepted, manifest, path, output, _ = direct_repaired_research_fixture(tmp_path, monkeypatch)
    following = block_for(accepted, '2026-09-25')
    owner = deepcopy(accepted)
    if change=='unbound_revision': owner['source_hashes'].pop('history_revision/2026-09-24.json')
    elif change=='fake_receipt':
        ref=owner['source_refs']['history_revision/2026-09-24.json']
        receipt=json.loads(Path(ref['path']).read_text()); receipt['kind']='INVENTED'
        Path(ref['path']).write_text(json.dumps(receipt)); ref['sha256']=backend.digest(ref['path'])
        owner['source_hashes']['history_revision/2026-09-24.json']=ref['sha256']
    elif change=='bad_manifest_hash': following['performance_extension']['manifest']['sha256']='0'*64
    elif change=='unbound_manifest': following['source_hashes'].pop('performance_extension/manifest')
    elif change=='wrong_model': following['shared_scores']['model_sha256']='0'*64
    elif change=='wrong_research_group':
        following['shared_scores']['historical'][-1]['raw_score']+=.05
    else:
        owner=old
        following['shared_scores']['historical'][-1]['raw_score']+=.05
    with pytest.raises(backend.SelectedStrategyError, match='HISTORY_'):
        backend._merge_archived_snapshots(following, output.parent/'history', previous=owner)
