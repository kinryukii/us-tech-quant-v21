"""Verify selected-policy bindings and prohibit accidental Raw reader fallback."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
import json
from unittest.mock import Mock

import pytest

from apps.demo_console.adapters import selected_strategies_reader as selected
from apps.demo_console.adapters import workspace_reader as workspace
from apps.demo_console.models import DecisionOverview, HoldingRow, PerformanceHistory, PerformancePoint, Provenance
from apps.demo_console.tests.test_selected_strategies_reader_workspace import package as synthetic_package


@pytest.fixture
def bound_package(tmp_path):
    path = tmp_path / "selected_hgb.json"
    path.write_text(json.dumps(synthetic_package()), encoding="utf-8")
    return selected.load_package(path)


@pytest.fixture
def reject_raw(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A selected/unknown source reached a Raw reader")

    for module, names in (
        (workspace.decision_reader, ("load_overview", "load_history")),
        (workspace.performance_reader, ("read_performance",)),
        (workspace.updated, ("load_overview", "read_performance", "bundle")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


def test_selected_model_binds_identity_source_and_replay_end_without_fake_positions(bound_package, reject_raw):
    model = workspace.load_selected_overview("HGB_FACTOR_5", package=bound_package)
    assert model.source_id == workspace.SELECTED_HGB
    assert model.provenance.strategy_identity == "HGB_FACTOR_5"
    assert model.decision_date == model.provenance.information_as_of == "2026-09-24"
    assert model.performance_cutoff_date == "2026-01-07"
    assert model.source_manifest_path == bound_package["package_path"]
    assert model.source_manifest_sha256 == bound_package["package_sha256"]
    assert model.provenance.artifact_sources == ("C:/synthetic/model.joblib",)
    assert model.provenance.artifact_hashes == (("C:/synthetic/model.joblib", "ab" * 32),)
    assert model.execution_status == "TARGET_ONLY"
    assert model.provenance.execution_date is model.scheduled_execution_date is None
    assert model.ranking == model.holdings == model.learning.feature_columns == ()
    assert model.error is None


def test_both_policies_share_explicit_observation_dates_without_renaming_each_signal(bound_package, reject_raw):
    payload = deepcopy(bound_package)
    payload["strategies"]["HGB_FACTOR_5"]["application"]["signal_date"] = "2026-09-25"
    model = workspace.load_selected_overview("HGB_DIAG_5", package=payload)
    assert model.decision_date == "2026-09-25"
    assert model.available_dates[-2:] == ("2026-09-24", "2026-09-25")
    assert model.provenance.strategy_identity == "HGB_DIAG_5"
    view = selected.workspace_view("HGB_DIAG_5", model.decision_date, package=payload)
    assert view["target"]["signal_date"] == "2026-09-24"
    assert view["target"]["status"] == "LATEST_AVAILABLE_SIGNAL"
    assert view["history"]["end"] == model.performance_cutoff_date == "2026-01-07"


@pytest.mark.parametrize("day,end", [("2026-01-02", None), (date(2026, 1, 5), "2026-01-05")])
def test_observation_cutoff_keeps_performance_separate_from_signal_clock(bound_package, reject_raw, day, end):
    model = workspace.load_selected_overview("HGB_DIAG_5", day, package=bound_package)
    assert model.decision_date == (day.isoformat() if isinstance(day, date) else day)
    assert model.performance_cutoff_date == end
    assert model.execution_status == "TARGET_ONLY"
    assert model.provenance.execution_date is None
    assert not model.holdings


@pytest.mark.parametrize("requested,observed", [("2026-01-04", "2026-01-02"), ("2026-01-01", None)])
def test_missing_observation_never_moves_selected_policy_into_future(bound_package, reject_raw, requested, observed):
    model = workspace.load_selected_overview("HGB_FACTOR_5", requested, package=bound_package)
    assert model.decision_date == model.provenance.information_as_of == observed
    assert model.performance_cutoff_date is None
    assert model.ranking == model.holdings == ()


def test_unavailable_training_sample_does_not_expose_2026_history_or_raw(bound_package, reject_raw):
    model = workspace.load_selected_overview("HGB_DIAG_5", package=bound_package, sample="historical")
    assert model.available_dates == ()
    assert model.decision_date is model.performance_cutoff_date is None
    assert model.provenance.information_as_of is None
    assert model.provenance.strategy_identity == "HGB_DIAG_5"
    assert model.sample_end_date == "2025-12-31"
    assert not model.holdings and not model.ranking


def test_blocked_requested_date_is_current_while_verified_replay_remains_available(bound_package, reject_raw):
    payload = deepcopy(bound_package)
    payload["strategies"]["HGB_FACTOR_5"]["application"] = {
        "status": "BLOCKED", "signal_date": None, "requested_signal_date": "2026-09-28",
        "rows": [], "reason": "CURRENT_FEATURE_HASH_MISMATCH"}
    model = workspace.load_selected_overview("HGB_FACTOR_5", package=payload)
    assert model.decision_date == "2026-09-28"
    assert model.provenance.strategy_identity == "HGB_FACTOR_5"
    assert model.performance_cutoff_date == "2026-01-07"
    assert model.error is None
    assert not model.holdings
    target = selected.workspace_view("HGB_FACTOR_5", model.decision_date, package=payload)["target"]
    assert target["status"] == "BLOCKED" and target["rows"] == []
    assert target["reason"] == "CURRENT_FEATURE_HASH_MISMATCH"


def test_default_loading_reads_one_bound_package(monkeypatch, bound_package, reject_raw):
    loader = Mock(return_value=bound_package)
    monkeypatch.setattr(selected, "load_package", loader)
    model = workspace.load_selected_overview("HGB_DIAG_5")
    loader.assert_called_once_with()
    assert model.source_manifest_sha256 == bound_package["package_sha256"]


def test_bad_package_and_unknown_selected_id_fail_before_any_raw_read(bound_package, reject_raw):
    payload = deepcopy(bound_package)
    payload["strategies"]["HGB_DIAG_5"]["application"]["target_cash_weight"] = .9
    with pytest.raises(ValueError, match="application.cash_identity"):
        workspace.load_selected_overview("HGB_DIAG_5", package=payload)
    with pytest.raises(ValueError, match="UNKNOWN_SELECTED_WORKSPACE_STRATEGY"):
        workspace.load_selected_overview("RAW_A2", package=bound_package)


@pytest.mark.parametrize("day", ["invalid", "20260924", 123, True, datetime(2026, 9, 24, 16)])
def test_invalid_observation_input_is_not_silently_relabelled(bound_package, reject_raw, day):
    with pytest.raises(ValueError, match="INVALID_SELECTED_WORKSPACE_DATE"):
        workspace.load_selected_overview("HGB_DIAG_5", day, package=bound_package)


@pytest.mark.parametrize("source", [workspace.SELECTED_HGB, "UNKNOWN_OTHER", ""])
def test_nonraw_history_and_performance_cannot_fall_back_to_frozen_raw(source, reject_raw):
    identity = "HGB_DIAG_5" if source == workspace.SELECTED_HGB else source
    model = DecisionOverview(decision_date="2026-09-24", source_id=source,
        performance_cutoff_date="2026-08-18", provenance=Provenance(strategy_identity=identity))
    with pytest.raises(ValueError, match="UNSUPPORTED_WORKSPACE_HISTORY_SOURCE"):
        workspace.load_history(model)
    history = workspace.read_performance(model)
    assert history.error and history.points == ()
    assert history.model_identity == identity
    assert history.requested_end_date == "2026-08-18"
    assert "UNSUPPORTED_WORKSPACE_PERFORMANCE_SOURCE" in history.debug_error
    assert workspace.latest_executed_overview(model) is None


def test_frozen_raw_history_and_performance_keep_original_call_contract(monkeypatch):
    history_reader = Mock(return_value=("FROZEN_RAW_HISTORY",))
    performance_reader = Mock(return_value=PerformanceHistory(model_identity="FROZEN_RAW"))
    monkeypatch.setattr(workspace.decision_reader, "load_history", history_reader)
    monkeypatch.setattr(workspace.performance_reader, "read_performance", performance_reader)
    model = DecisionOverview(decision_date="2025-12-02", source_id=workspace.FROZEN,
        provenance=Provenance(execution_date="2025-12-03"))
    assert workspace.load_history(model, window=17) == ("FROZEN_RAW_HISTORY",)
    assert workspace.read_performance(model).model_identity == "FROZEN_RAW"
    history_reader.assert_called_once_with("2025-12-02", window=17)
    performance_reader.assert_called_once_with("2025-12-03")


def _point(day):
    return PerformancePoint(execution_date=day, nav=1., net_return=0., gross_return=0.,
        transaction_cost=0., turnover=0., cash=1., position_value=0., holding_count=0,
        stale_mark_count=0, skipped_buy_count=0, blocked_rebalance_count=0, buy_cash_scale=1.)


def test_updated_raw_keeps_bound_history_and_sample_scoped_performance(monkeypatch):
    reference = {"path": "C:/synthetic/raw_manifest.json", "sha256": "cd" * 32}
    model = DecisionOverview(decision_date="2026-01-05", source_id=workspace.LATEST,
        available_dates=("2026-01-02", "2026-01-05", "2026-01-06"),
        source_manifest_path=reference["path"], source_manifest_sha256=reference["sha256"],
        sample_start_date="2026-01-01", sample_end_date="2026-12-31",
        performance_cutoff_date="2026-01-05")
    overview_reader = Mock(side_effect=lambda day, reference: DecisionOverview(
        decision_date=day, source_id=workspace.LATEST))
    points = tuple(_point(day) for day in ("2025-12-31", "2026-01-02", "2026-01-05"))
    performance_reader = Mock(return_value=PerformanceHistory(points=points,
        available_dates=tuple(point.execution_date for point in points), model_identity="UPDATED_RAW"))
    monkeypatch.setattr(workspace.updated, "load_overview", overview_reader)
    monkeypatch.setattr(workspace.updated, "read_performance", performance_reader)
    history = workspace.load_history(model, window=1)
    overview_reader.assert_called_once_with("2026-01-05", reference=reference)
    assert len(history) == 1 and history[0].decision_date == "2026-01-05"
    assert history[0].sample_start_date == "2026-01-01"
    performance = workspace.read_performance(model)
    performance_reader.assert_called_once_with("2026-01-05", reference=reference)
    assert performance.model_identity == "UPDATED_RAW"
    assert tuple(point.execution_date for point in performance.points) == ("2026-01-02", "2026-01-05")
    assert performance.baseline_date == "2025-12-31"
    assert performance.effective_end_date == "2026-01-05"


@pytest.fixture
def recorded_raw(monkeypatch):
    latest = DecisionOverview(decision_date="2026-09-24", source_id=workspace.LATEST,
        available_dates=("2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-09-23", "2026-09-24"),
        source_manifest_path="C:/synthetic/raw_manifest.json", source_manifest_sha256="ef" * 32,
        performance_cutoff_date="2026-09-24", execution_status="PENDING_NEXT_OPEN",
        ranking=(HoldingRow(1, "RANKING_ONLY", score=99.),), holdings=())
    points = tuple(replace(_point(day), nav=nav, net_return=net, gross_return=net,
        cash=nav * .2, position_value=nav * .8, holding_count=2)
        for day, nav, net in (("2026-01-05", 5.5, .1), ("2026-01-06", 5.28, -.04),
                              ("2026-01-07", 5.544, .05), ("2026-09-24", 6., 6. / 5.544 - 1.)))
    history = PerformanceHistory(points=points, available_dates=tuple(point.execution_date for point in points),
        archive_start="2026-01-05", archive_end="2026-09-24", baseline_date="2025-12-31")
    last_book = replace(latest, decision_date="2026-09-23", execution_status="EXECUTED",
        holdings=(HoldingRow(None, "RAW_EXEC_ALPHA", weight=.45), HoldingRow(None, "RAW_EXEC_BETA", weight=.35)),
        provenance=Provenance(decision_date="2026-09-23", execution_date="2026-09-24"))
    early_book = replace(last_book, decision_date="2026-01-02",
        holdings=(HoldingRow(None, "RAW_EXEC_ALPHA", weight=.5), HoldingRow(None, "RAW_EXEC_BETA", weight=.3)),
        provenance=Provenance(decision_date="2026-01-02", execution_date="2026-01-05"))

    def overview(day=None, **kwargs):
        return latest if day is None else replace(latest, decision_date=day,
            performance_cutoff_date="2026-01-07" if day < "2026-09-24" else "2026-09-24")

    def performance(model):
        scoped = tuple(point for point in history.points if point.execution_date <= model.performance_cutoff_date)
        return replace(history, points=scoped)

    overview_reader = Mock(side_effect=overview)
    performance_reader = Mock(side_effect=performance)
    book_reader = Mock(side_effect=lambda model: last_book if model.performance_cutoff_date >= "2026-09-24" else early_book)
    monkeypatch.setattr(workspace, "load_overview", overview_reader)
    monkeypatch.setattr(workspace, "read_performance", performance_reader)
    monkeypatch.setattr(workspace, "latest_executed_overview", book_reader)
    return {"latest": latest, "history": history, "last_book": last_book,
            "overview": overview_reader, "performance": performance_reader, "book": book_reader}


def test_applied_three_views_retain_raw_first_return_and_use_actual_executed_book(bound_package, recorded_raw):
    views = workspace.load_applied_strategies("2026-09-24", package=bound_package)
    assert tuple(views) == ("RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5")
    raw = views["RAW_A2"]
    assert raw["status"] == "AVAILABLE"
    assert raw["history"]["summary"] is None
    assert raw["history"]["baseline_source_nav"] == pytest.approx(5.)
    assert [row["nav"] for row in raw["history"]["daily"]] == pytest.approx([1.1, 1.056, 1.1088, 1.2])
    assert all(row["cash_weight"] == pytest.approx(.2) for row in raw["history"]["daily"])
    target = raw["target"]
    assert target["kind"] == target["account_basis"] == "RECORDED_EXECUTED_BOOK"
    assert target["execution_status"] == "EXECUTED"
    assert target["signal_date"] == "2026-09-23" and target["execution_date"] == "2026-09-24"
    assert target["rows"] == [{"ticker": "RAW_EXEC_ALPHA", "target_weight": .45},
                              {"ticker": "RAW_EXEC_BETA", "target_weight": .35}]
    assert target["target_cash_weight"] == pytest.approx(.2)
    assert "RANKING_ONLY" not in {row["ticker"] for row in target["rows"]}
    assert recorded_raw["latest"].holdings == ()
    assert recorded_raw["performance"].call_args.args[0].source_manifest_sha256 == "ef" * 32
    for sid in selected.STRATEGY_IDS:
        assert views[sid] == selected.workspace_view(sid, "2026-09-24", package=bound_package)


def test_applied_raw_signal_and_execution_never_cross_observation_cutoff(bound_package, recorded_raw):
    views = workspace.load_applied_strategies("2026-01-06", package=bound_package)
    raw = views["RAW_A2"]
    assert raw["status"] == "AVAILABLE"
    assert [row["date"] for row in raw["history"]["daily"]] == ["2026-01-05", "2026-01-06"]
    assert raw["target"]["execution_date"] == "2026-01-05"
    recorded_raw["overview"].assert_called_with("2026-01-06", source=workspace.LATEST,
        reference={"path": "C:/synthetic/raw_manifest.json", "sha256": "ef" * 32})
    assert recorded_raw["performance"].call_args.args[0].performance_cutoff_date == "2026-01-06"
    assert views["HGB_DIAG_5"]["history"]["end"] == "2026-01-06"


@pytest.mark.parametrize("failure", ["missing_weight", "pending_book", "cash_identity", "performance", "wrong_source"])
def test_incomplete_raw_proof_blanks_entire_raw_column_without_using_rankings(bound_package, recorded_raw, failure):
    if failure == "missing_weight":
        recorded_raw["book"].side_effect = None
        recorded_raw["book"].return_value = replace(recorded_raw["last_book"],
            holdings=(HoldingRow(None, "RAW_EXEC_ALPHA", weight=None),))
    elif failure == "pending_book":
        recorded_raw["book"].side_effect = None
        recorded_raw["book"].return_value = recorded_raw["latest"]
    elif failure == "cash_identity":
        recorded_raw["book"].side_effect = None
        recorded_raw["book"].return_value = replace(recorded_raw["last_book"],
            holdings=(HoldingRow(None, "RAW_EXEC_ALPHA", weight=.5), HoldingRow(None, "RAW_EXEC_BETA", weight=.35)))
    elif failure == "performance":
        recorded_raw["performance"].side_effect = None
        recorded_raw["performance"].return_value = PerformanceHistory(error="RAW_SOURCE_HASH_FAILED")
    else:
        recorded_raw["overview"].side_effect = None
        recorded_raw["overview"].return_value = replace(recorded_raw["latest"], source_id=workspace.FROZEN)
    views = workspace.load_applied_strategies("2026-09-24", package=bound_package)
    raw = views["RAW_A2"]
    assert raw["status"] == "UNAVAILABLE" and raw["error"]
    assert raw["history"]["daily"] == [] and raw["history"]["summary"] is None
    assert raw["target"]["kind"] == "UNAVAILABLE" and raw["target"]["rows"] == []
    assert raw["target"]["target_cash_weight"] is None
    for sid in selected.STRATEGY_IDS:
        assert views[sid]["target"]["kind"] == "CURRENT_CASH_START_TARGET"


def test_early_unavailable_raw_and_late_performance_both_keep_three_ids(bound_package, recorded_raw):
    views = workspace.load_applied_strategies("2026-01-01", package=bound_package)
    assert tuple(views) == ("RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5")
    assert views["RAW_A2"]["status"] == "UNAVAILABLE"
    assert all(not view["history"]["daily"] for view in views.values())
    recorded_raw["performance"].side_effect = None
    recorded_raw["performance"].return_value = recorded_raw["history"]
    raw = workspace.load_applied_strategies("2026-01-06", package=bound_package)["RAW_A2"]
    assert raw["status"] == "UNAVAILABLE"
    assert "EXCEEDS_CUTOFF" in raw["error"]


def test_bad_hgb_package_blocks_its_two_views_without_disabling_valid_raw(bound_package, recorded_raw):
    payload = deepcopy(bound_package)
    payload["strategies"]["HGB_DIAG_5"]["application"]["target_cash_weight"] = .9
    views = workspace.load_applied_strategies("2026-09-24", package=payload)
    assert views["RAW_A2"]["status"] == "AVAILABLE"
    for sid in selected.STRATEGY_IDS:
        assert views[sid]["status"] == "BLOCKED" and not views[sid]["history"]["daily"]


def test_default_applied_cutoff_and_empty_sample_do_not_fabricate_dates(bound_package, recorded_raw):
    views = workspace.load_applied_strategies(None, package=bound_package)
    assert all(view["requested_cutoff"] == "2026-09-24" for view in views.values())
    empty = workspace.load_applied_strategies(None, package=bound_package, sample="historical")
    assert all(view["requested_cutoff"] is None for view in empty.values())
    assert all(not view["history"]["daily"] for view in empty.values())
    assert all(not view["target"]["rows"] for view in empty.values())


def test_common_calendar_preserves_raw_date_when_detail_focus_changes_to_hgb(bound_package, recorded_raw):
    dates = workspace.applied_observation_dates(bound_package)
    assert "2026-09-23" in dates and "2026-09-24" in dates
    model = workspace.load_selected_overview("HGB_FACTOR_5", "2026-09-23",
        package=bound_package, observation_dates=dates)
    assert model.decision_date == model.provenance.information_as_of == "2026-09-23"
    assert model.available_dates == dates
    assert model.performance_cutoff_date == "2026-01-07"
    view = selected.workspace_view("HGB_FACTOR_5", model.decision_date, package=bound_package)
    assert view["target"]["kind"] == "HISTORICAL_SIGNAL_TARGET"
    assert view["target"]["signal_date"] == "2026-01-06"
    assert all(row["ticker"] != "MSFT" for row in view["target"]["rows"])
    assert all(row["date"] <= "2026-09-23" for row in view["history"]["daily"])


def test_calendar_is_sample_bounded_and_reuses_given_canonical_raw_snapshot(bound_package, recorded_raw):
    raw = replace(recorded_raw["latest"], available_dates=("2025-12-31", "2026-09-23", "2027-01-01"))
    test_dates = workspace.applied_observation_dates(bound_package, raw_model=raw)
    assert "2026-09-23" in test_dates
    assert "2025-12-31" not in test_dates and "2027-01-01" not in test_dates
    assert workspace.applied_observation_dates(bound_package, "historical", raw_model=raw) == ("2025-12-31",)
    recorded_raw["overview"].assert_not_called()


def test_unavailable_raw_calendar_keeps_package_dates_and_never_uses_frozen_dates(bound_package, recorded_raw):
    failed = replace(recorded_raw["latest"], error="RAW_BINDING_FAILED")
    assert workspace.applied_observation_dates(bound_package, raw_model=failed) == selected.workspace_dates(bound_package)
    frozen = replace(recorded_raw["latest"], source_id=workspace.FROZEN)
    assert workspace.applied_observation_dates(bound_package, raw_model=frozen) == selected.workspace_dates(bound_package)


def _with_same_batch_raw(payload):
    payload = deepcopy(payload)
    reference = payload['strategies']['HGB_DIAG_5']
    payload['raw_reference'] = {'strategy_id': 'RAW_A2', 'label': 'Raw A2',
        'performance_period': deepcopy(payload['performance_period']),
        **{key: deepcopy(reference[key]) for key in ('daily', 'summary', 'targets')}}
    return payload


def test_same_batch_raw_history_is_independent_of_the_pit_latest_book(bound_package, recorded_raw):
    payload = _with_same_batch_raw(bound_package)
    raw = workspace.load_applied_strategies('2026-09-24', package=payload)['RAW_A2']
    assert raw['status'] == 'AVAILABLE' and raw['source_id'] == 'SAME_BATCH_QFQ_PROXY'
    assert [row['nav'] for row in raw['history']['daily']] == [1.01, .98, 1.03]
    assert raw['history']['end'] == '2026-01-07'
    assert raw['latest_book']['source_id'] == workspace.LATEST
    assert raw['latest_book']['history']['daily'][-1]['nav'] == pytest.approx(1.2)
    assert raw['target']['kind'] == 'RECORDED_EXECUTED_BOOK'
    assert raw['target']['execution_date'] == '2026-09-24'
    assert raw['research_target']['signal_date'] == '2026-01-06'


def test_current_raw_rule_target_uses_signal_top20_instead_of_executed_book(bound_package, recorded_raw):
    latest = replace(recorded_raw['latest'],
        scheduled_execution_date='2026-09-25',
        ranking=tuple(HoldingRow(i, f'SIG{i:02d}', score=1-i/100) for i in range(1, 41)))
    views = workspace.load_applied_strategies('2026-09-24', package=_with_same_batch_raw(bound_package),
                                            raw_model=latest)
    raw = views['RAW_A2']
    target = raw['signal_target']
    assert target['status'] == 'READY' and target['kind'] == 'RAW_RULE_TARGET'
    assert target['signal_date'] == '2026-09-24' and target['execution_date'] == '2026-09-25'
    assert target['execution_status'] == 'TARGET_ONLY'
    assert [r['ticker'] for r in target['rows']] == [f'SIG{i:02d}' for i in range(1, 21)]
    assert all(r['target_weight'] == .05 for r in target['rows'])
    assert target['target_cash_weight'] == 0
    assert raw['target']['signal_date'] == '2026-09-23'
    assert not any(r['ticker'].startswith('RAW_EXEC') for r in target['rows'])
    for sid in selected.STRATEGY_IDS:
        assert views[sid]['target']['execution_date'] == '2026-09-25'
        assert views[sid]['target']['execution_status'] == 'TARGET_ONLY'


def test_raw_rule_plan_date_is_unknown_when_bound_calendar_has_no_next_session(bound_package, recorded_raw):
    latest = replace(recorded_raw['latest'], scheduled_execution_date=None,
        ranking=tuple(HoldingRow(i, f'SIG{i:02d}', score=1-i/100) for i in range(1, 21)))
    views = workspace.load_applied_strategies('2026-09-24', package=_with_same_batch_raw(bound_package),
                                            raw_model=latest)
    assert views['RAW_A2']['signal_target']['execution_date'] is None
    assert all(view['target'].get('execution_date') is None for sid, view in views.items() if sid != 'RAW_A2')


def test_raw_book_failure_cannot_remove_verified_same_batch_history(bound_package, recorded_raw):
    recorded_raw['book'].side_effect = None
    recorded_raw['book'].return_value = None
    raw = workspace.load_applied_strategies('2026-09-24', package=_with_same_batch_raw(bound_package))['RAW_A2']
    assert raw['status'] == 'AVAILABLE' and raw['history']['daily']
    assert raw['latest_book']['status'] == 'UNAVAILABLE'
    assert raw['target']['rows'] == []
    assert raw['research_target']['rows']


def test_raw_rule_target_missing_exact_signal_never_falls_back_to_previous_book(bound_package, recorded_raw):
    raw = workspace.load_applied_strategies('2026-09-22', package=_with_same_batch_raw(bound_package))['RAW_A2']
    assert raw['signal_target']['status'] == 'UNAVAILABLE'
    assert raw['signal_target']['signal_date'] is None and raw['signal_target']['rows'] == []
