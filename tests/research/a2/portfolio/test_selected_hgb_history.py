"""Published cash-start snapshots survive a later READY or BLOCKED update."""
from copy import deepcopy
import json

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
