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



def latest_execution_fixture():
    """Synthetic Friday signal / verified Monday open; no real artifact reads."""
    payload = synthetic_package()
    dates = ("2026-10-01", "2026-10-02", "2026-10-05")
    payload["performance_period"].update(start=dates[0], end=dates[-1])
    for strategy in payload["strategies"].values():
        for row, day in zip(strategy["daily"], dates):
            row["date"] = day
        for row, day in zip(strategy["targets"], ("2026-09-30", "2026-10-01", "2026-10-02")):
            row["signal_date"] = day
        strategy["application"]["signal_date"] = "2026-10-02"
    payload = selected.validate_package(_with_same_batch_raw(payload))
    payload.update(package_path="C:/synthetic/selected_hgb.json", package_sha256="ac" * 32)
    model = DecisionOverview(decision_date="2026-10-02", source_id=workspace.LATEST,
        available_dates=("2026-09-30", "2026-10-01", "2026-10-02"),
        source_manifest_path="C:/synthetic/latest_manifest.json", source_manifest_sha256="de" * 32,
        execution_status="EXECUTED", scheduled_execution_date="2026-10-05",
        performance_cutoff_date="2026-10-05",
        ranking=tuple(HoldingRow(i, f"SIG{i:02d}", score=.1-i/1000) for i in range(1, 21)),
        holdings=(HoldingRow(None, "REAL_BOOK_A", weight=.4), HoldingRow(None, "REAL_BOOK_B", weight=.4)),
        provenance=Provenance(decision_date="2026-10-02", information_as_of="2026-10-02",
                              execution_date="2026-10-05"))
    navs = (1.01, .98, 1.03)
    points = tuple(replace(_point(day), nav=nav, net_return=nav/previous-1,
        gross_return=nav/previous-1, cash=nav*.2, position_value=nav*.8, holding_count=2)
        for day, nav, previous in zip(dates, navs, (1., *navs[:-1])))
    history = PerformanceHistory(points=points, available_dates=dates, archive_start=dates[0],
        archive_end=dates[-1], baseline_date="2026-09-30")

    def overview(day=None, **kwargs):
        if day is None or day == model.decision_date:
            return model
        execution = "2026-10-02" if day == "2026-10-01" else "2026-10-01"
        return replace(model, decision_date=day, scheduled_execution_date=execution,
            performance_cutoff_date=execution, provenance=Provenance(decision_date=day,
                information_as_of=day, execution_date=execution))

    def performance(current):
        return replace(history, points=tuple(point for point in points
            if point.execution_date <= current.performance_cutoff_date))

    def book(current):
        execution = current.performance_cutoff_date
        signal = {"2026-10-05": "2026-10-02", "2026-10-02": "2026-10-01",
                  "2026-10-01": "2026-09-30"}[execution]
        return replace(model, decision_date=signal, scheduled_execution_date=execution,
            performance_cutoff_date=execution, provenance=Provenance(decision_date=signal,
                information_as_of=signal, execution_date=execution))

    return {"package": payload, "model": model, "overview": overview,
            "performance": performance, "book": book, "binding": workspace.source_reference(model)}


@pytest.fixture
def latest_execution(monkeypatch):
    proof = latest_execution_fixture()
    for name in ("overview", "performance", "book"):
        function = {"overview": "load_overview", "performance": "read_performance",
                    "book": "latest_executed_overview"}[name]
        monkeypatch.setattr(workspace, function, Mock(side_effect=proof[name]))
    monkeypatch.setattr(workspace.updated, "binding", Mock(return_value=proof["binding"]))
    return proof


def test_latest_verified_execution_expands_only_history_and_preserves_signal_targets(latest_execution):
    proof = latest_execution
    original = deepcopy(proof["package"])
    assert workspace.applied_history_cutoff("2026-10-02", raw_model=proof["model"]) == "2026-10-05"
    strict = workspace.load_applied_strategies("2026-10-02", package=proof["package"], raw_model=proof["model"])
    expanded = workspace.load_applied_strategies("2026-10-02", package=proof["package"],
        raw_model=proof["model"], history_cutoff="2026-10-05")
    for sid, view in expanded.items():
        assert view["requested_cutoff"] == "2026-10-02"
        assert strict[sid]["history"]["end"] == "2026-10-02"
        assert view["history"]["end"] == "2026-10-05"
        assert [row["date"] for row in view["history"]["daily"]] == ["2026-10-01", "2026-10-02", "2026-10-05"]
        if sid != "RAW_A2":
            assert view["target"] == strict[sid]["target"]
            assert view["target"]["signal_date"] == "2026-10-02"
            assert view["target"]["execution_status"] == "TARGET_ONLY"
    raw = expanded["RAW_A2"]
    assert raw["latest_book"]["history"]["end"] == raw["target"]["execution_date"] == "2026-10-05"
    assert raw["signal_target"] == strict["RAW_A2"]["signal_target"]
    assert raw["signal_target"]["signal_date"] == raw["research_target"]["signal_date"] == "2026-10-02"
    assert len(raw["signal_target"]["rows"]) == 20
    assert all(row["target_weight"] == .05 for row in raw["signal_target"]["rows"])
    assert proof["package"] == original and proof["model"].provenance.information_as_of == "2026-10-02"


@pytest.mark.parametrize("failure", ["earlier_selection", "historical_sample", "pending", "wrong_source",
    "wrong_information_date", "not_latest_signal", "execution_not_scheduled", "performance_not_execution",
    "changed_manifest", "changed_hash", "missing_reference"])
def test_history_expansion_requires_current_verified_identity_and_owner_clock(latest_execution, failure):
    model, day, sample = latest_execution["model"], "2026-10-02", "test_2026"
    if failure == "earlier_selection": day = "2026-10-01"
    elif failure == "historical_sample": sample = "historical"
    elif failure == "pending": model = replace(model, execution_status="PENDING_NEXT_OPEN")
    elif failure == "wrong_source": model = replace(model, source_id=workspace.SELECTED_HGB)
    elif failure == "wrong_information_date": model = replace(model, provenance=replace(model.provenance, information_as_of="2026-10-01"))
    elif failure == "not_latest_signal": model = replace(model, available_dates=(*model.available_dates, "2026-10-05"))
    elif failure == "execution_not_scheduled": model = replace(model, scheduled_execution_date="2026-10-06")
    elif failure == "performance_not_execution": model = replace(model, performance_cutoff_date="2026-10-02")
    elif failure == "changed_manifest": workspace.updated.binding.return_value = {**latest_execution["binding"], "path":"C:/synthetic/archived.json"}
    elif failure == "changed_hash": workspace.updated.binding.return_value = {**latest_execution["binding"], "sha256":"ff"*32}
    else: model = replace(model, source_manifest_sha256=None)
    assert workspace.applied_history_cutoff(day, raw_model=model, sample=sample) == day
    if failure in {"earlier_selection", "historical_sample", "pending", "wrong_source"}:
        workspace.updated.binding.assert_not_called()


@pytest.mark.parametrize("day,execution", [("2026-10-01", "2026-10-05"), ("2026-10-02", "2026-10-06")])
def test_explicit_unverified_history_end_is_rejected(latest_execution, day, execution):
    with pytest.raises(ValueError, match="APPLIED_HISTORY_CUTOFF_NOT_VERIFIED"):
        workspace.load_applied_strategies(day, package=latest_execution["package"],
            raw_model=latest_execution["model"], history_cutoff=execution)


def test_historical_selection_retains_strict_performance_boundary(latest_execution):
    views = workspace.load_applied_strategies("2026-10-01", package=latest_execution["package"],
        raw_model=latest_execution["model"])
    assert all(view["history"]["end"] == "2026-10-01" for view in views.values())
    assert all(row["date"] <= "2026-10-01" for view in views.values() for row in view["history"]["daily"])
    assert views["RAW_A2"]["target"]["execution_date"] == "2026-10-01"
    workspace.updated.binding.assert_not_called()


def test_default_hgb_observation_uses_current_signal_instead_of_later_nav(latest_execution):
    package = latest_execution["package"]
    for sid in selected.STRATEGY_IDS:
        model = workspace.load_selected_overview(sid, package=package)
        assert model.decision_date == model.provenance.information_as_of == "2026-10-02"
        assert model.performance_cutoff_date == "2026-10-02"
        assert model.available_dates[-1] == "2026-10-05"
        explicit = workspace.load_selected_overview(sid, "2026-10-05", package=package)
        assert explicit.decision_date == explicit.performance_cutoff_date == "2026-10-05"



def _ml_capture(sid, *, day="2026-09-24", source="recorded", kind="CURRENT_ACCOUNT_TARGET"):
    leaf = {"status": "AVAILABLE", "actual_signal_date": day, "weight_date": day,
        "scope": "RECORDED_FROZEN_MODEL_INPUTS", "source_kind": source, "target_kind": kind,
        "rows": [{"ticker": "SYNTH", "security_id": "SYNTHETIC_ID", "model_rank": 2,
            "score": .123, "raw_rank": 7, "raw_score": .3, "source_score": -.025,
            "action": "HOLD", "target_weight": .12, "weight_before": .1,
            "exact_hold_units": 4., "hold_units": 4., "explicit_target": False}],
        "source_refs": {"record": {"path": "C:/synthetic/record.json", "sha256": "ad" * 32}}}
    context = {"strategy_id": sid, "model_identity": {"candidate_id": sid},
        "provenance": {"window_id": "MAIN"},
        "target": {"kind": kind, "status": "READY", "signal_date": day,
            "rows": [{"ticker": "SYNTH", "target_weight": .12}], "target_cash_weight": .88}}
    return {"strategies": {sid: leaf}}, context


@pytest.mark.parametrize("sid,kind", [
    ("RAW_A2", "RANK_SCORE"), ("HGB_DIAG_5", "RANK_SCORE"),
    ("R10_DIRECT_MEAN4_ELASTICNET_MID", "ACTION_VALUE"),
    ("R10_DIRECT_H5_RIDGE_MID", "ACTION_VALUE"), ("R7_GROSS_LINEAR", "GROSS_EXPOSURE")])
def test_ml_workspace_projects_all_five_without_any_reader_calls(monkeypatch, sid, kind):
    snapshot, context = _ml_capture(sid)
    original = deepcopy((snapshot, context))
    def forbidden(*args, **kwargs):
        raise AssertionError("A pure ML projection performed an artifact read")
    for name in ("load_overview", "load_active_strategies", "load_active_rankings", "load_history", "read_performance"):
        monkeypatch.setattr(workspace, name, forbidden)
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context)
    assert result["strategy_id"] == sid and result["output_kind"] == kind
    assert result["status"] == "AVAILABLE" and result["error"] is None
    assert result["source"] == "recorded" and result["record_basis"] == "CURRENT_PAPER_ACCOUNT"
    assert result["score_date"] == result["target_date"] == "2026-09-24"
    row = result["rows"][0]
    assert row["ticker"] == "SYNTH" and row["action"] == "HOLD"
    assert row["target_weight"] == .12 and row["weight_before"] == .1 and row["exact_hold_units"] == 4.
    assert row["rank"] == (2 if kind == "RANK_SCORE" else None)
    assert row["score"] == (.123 if kind == "RANK_SCORE" else None)
    assert row["native_action_score"] == (-.025 if kind == "ACTION_VALUE" else None)
    assert row["raw_rank"] == 7 and row["raw_score"] == .3
    assert (snapshot, context) == original
    result["target"]["rows"][0]["target_weight"] = .9
    result["provenance"]["source_refs"]["record"]["sha256"] = "bb" * 32
    assert (snapshot, context) == original


def test_ml_workspace_raw_keeps_only_its_exact_date_learning_profile():
    from apps.demo_console.models import LearningProfile
    sid = "RAW_A2"
    snapshot, context = _ml_capture(sid)
    raw = DecisionOverview(decision_date="2026-09-24", learning=LearningProfile(
        feature_columns=("raw_feature",), target="raw objective"),
        provenance=Provenance(config_identity="raw-frozen-id"))
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context, raw_model=raw)
    assert result["learning"] is raw.learning
    assert result["provenance"]["config_identity"] == "raw-frozen-id"
    wrong_day = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context,
        raw_model=replace(raw, decision_date="2026-09-23"))
    assert not wrong_day["learning"].feature_columns


@pytest.mark.parametrize("sid", ("HGB_DIAG_5", "R10_DIRECT_H5_RIDGE_MID"))
def test_ml_workspace_never_borrows_raw_features_vintages_or_objective(sid):
    from apps.demo_console.models import LearningProfile
    snapshot, context = _ml_capture(sid)
    context["model_identity"].update(feature_count=21, fit_cutoff_exclusive="2025-01-01", target="native objective")
    raw = DecisionOverview(decision_date="2026-09-24", learning=LearningProfile(
        feature_columns=("unrelated_raw_feature",), parameters=(("max_iter", "42"),), target="unrelated objective"))
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context, raw_model=raw,
        package={"feature_columns": ["unverified schema"]})
    assert result["learning"].target == "native objective"
    assert not result["learning"].feature_columns and not result["learning"].vintages and not result["learning"].parameters
    assert result["model_identity"]["fit_cutoff_exclusive"] == "2025-01-01"


def test_ml_workspace_native_main_records_keep_ticker_only_actions_without_fake_scores():
    sid = "R10_DIRECT_H5_RIDGE_MID"
    snapshot, context = _ml_capture(sid, source="research", kind="RECORDED_RESEARCH_SIGNAL_PLAN")
    row = snapshot["strategies"][sid]["rows"][0]
    for field in ("model_rank", "score", "raw_rank", "raw_score", "source_score", "security_id"):
        row[field] = None
    row.update(original_policy_weight=.1, research_weight_before=.11, decision_semantic="EXACT_HOLD")
    context["target"].update(kind="UNAVAILABLE", signal_date=None, rows=[], target_cash_weight=None)
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context)
    assert result["record_basis"] == "RECORDED_MAIN_RESEARCH" and result["source"] == "research"
    assert result["rows"][0]["rank"] is result["rows"][0]["score"] is result["rows"][0]["native_action_score"] is None
    assert result["rows"][0]["original_policy_weight"] == .1
    assert result["target"]["signal_date"] == "2026-09-24"
    assert result["target"]["kind"] == "RECORDED_RESEARCH_SIGNAL_PLAN"
    assert result["target"]["target_cash_weight"] is None


def test_ml_workspace_r7_keeps_recorded_zero_exposure_without_converting_rows_to_scores():
    sid = "R7_GROSS_LINEAR"
    snapshot, context = _ml_capture(sid)
    context["target"].update(requested_gross=0., previous_requested_gross=.5)
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context)
    assert result["model_identity"]["requested_gross"] == 0.
    assert result["model_identity"]["previous_requested_gross"] == .5
    assert result["rows"][0]["native_action_score"] is None


@pytest.mark.parametrize("status,observed", (("BLOCKED", "2026-09-24"), ("AVAILABLE", "2026-09-23"),
                                            ("AVAILABLE", "2026-09-25"), ("UNAVAILABLE", None)))
def test_ml_workspace_rejects_wrong_date_or_unqualified_output(status, observed):
    sid = "R10_DIRECT_H5_RIDGE_MID"
    snapshot, context = _ml_capture(sid)
    snapshot["strategies"][sid].update(status=status, actual_signal_date=observed)
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context)
    assert result["rows"] == [] and result["error"]
    assert result["target"]["kind"] == "UNAVAILABLE"


def test_ml_workspace_does_not_attach_old_target_weight_to_current_score():
    sid = "HGB_DIAG_5"
    snapshot, context = _ml_capture(sid)
    snapshot["strategies"][sid]["weight_date"] = "2026-09-23"
    context["target"]["signal_date"] = "2026-09-23"
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context)
    assert result["score_date"] == "2026-09-24" and result["target_date"] == "2026-09-23"
    assert result["rows"][0]["score"] == .123 and result["rows"][0]["target_weight"] is None
    assert result["target"]["kind"] == "UNAVAILABLE"


def test_ml_workspace_context_identity_and_duplicate_ticker_fail_closed():
    sid = "HGB_DIAG_5"
    snapshot, context = _ml_capture(sid)
    context["strategy_id"] = "RAW_A2"
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context)
    assert result["error"] == "ML_WORKSPACE_CONTEXT_IDENTITY_MISMATCH" and not result["rows"]
    context["strategy_id"] = sid
    snapshot["strategies"][sid]["rows"] *= 2
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context)
    assert result["error"] == "ML_WORKSPACE_INVALID_OUTPUT_ROWS" and not result["rows"]
    with pytest.raises(ValueError, match="UNKNOWN_ML_WORKSPACE_STRATEGY"):
        workspace.ml_workspace("HGB_FACTOR_5", "2026-09-24", snapshot=snapshot, context=context)



def test_ml_workspace_hgb_aliases_and_same_day_target_metadata_are_read_only_projections():
    sid = "HGB_DIAG_5"
    snapshot, context = _ml_capture(sid)
    leaf = snapshot["strategies"][sid]
    snapshot["source_refs"] = leaf.pop("source_refs")
    row = leaf["rows"][0]
    row["raw_input_score"] = row.pop("raw_score")
    for field in ("action", "weight_before", "explicit_target", "exact_hold_units"):
        row.pop(field)
    context["target"]["rows"][0].update(action="BUY", weight_before=.08,
        explicit_target=True, exact_hold_units=2., security_id=row["security_id"])
    original = deepcopy((snapshot, context))
    result = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context)
    assert result["rows"][0]["raw_score"] == .3
    assert result["rows"][0]["action"] == "BUY" and result["rows"][0]["weight_before"] == .08
    assert result["provenance"]["source_refs"] == snapshot["source_refs"]
    assert (snapshot, context) == original
    context["target"]["rows"][0]["security_id"] = "DIFFERENT_SYNTHETIC_ID"
    mismatched = workspace.ml_workspace(sid, "2026-09-24", snapshot=snapshot, context=context)
    assert mismatched["rows"][0].get("action") is None and mismatched["rows"][0]["weight_before"] is None



def test_ml_workspace_r7_real_owner_projection_keeps_exact_day_gross_with_replay_identity(monkeypatch):
    pytest.importorskip("streamlit")
    from apps.demo_console.adapters import applied_account_reader as accounts
    sid, day = "R7_GROSS_LINEAR", "2026-09-24"
    payload = {"books": {sid: {"strategy_id": sid, "plan": {
        "strategy_id": sid, "status": "READY", "signal_date": day, "execution_date": "2026-09-25",
        "model_fit_calls": 0, "broker_action_allowed": False,
        "requested_gross": .5, "previous_requested_gross": .75,
        "target_cash_weight": .5, "rows": [{"ticker": "SYNTH", "target_weight": .5}],
        "model_identity": {"requested_gross": .5, "signal_date": day}}}}}
    before = deepcopy(payload)
    def original(cutoff, **kwargs):
        return {name: {"strategy_id": name, "requested_cutoff": cutoff,
            "target": {"kind": "UNAVAILABLE", "rows": []}} for name in ("RAW_A2", "HGB_DIAG_5")}
    monkeypatch.setattr(workspace, "load_applied_strategies", original)
    replay = {sid: {"model_identity": {"candidate_id": sid,
        "signal_cutoff_exclusive": "2024-10-07", "frozen_state_identity_ref": {
            "path": "C:/synthetic/closure.json", "sha256": "ab" * 32}},
        "history": {"daily": []}, "provenance": {"scope": "FIXED_ACCEPTED_DESCRIPTIVE_REPLAY"}}}
    current = workspace.load_active_strategies(day, package={}, account_state=payload, research_views=replay)[sid]
    assert current["model_identity"] == replay[sid]["model_identity"]
    assert current["target"]["requested_gross"] == .5 and current["target"]["previous_requested_gross"] == .75
    projected = workspace.ml_workspace(sid, day, snapshot={"strategies": accounts.rankings(payload, day)}, context=current)
    assert projected["model_identity"] == {**replay[sid]["model_identity"],
        "requested_gross": .5, "previous_requested_gross": .75}
    next_day = "2026-09-25"
    stale = workspace.load_active_strategies(next_day, package={}, account_state=payload, research_views=replay)[sid]
    old = workspace.ml_workspace(sid, next_day, snapshot={"strategies": accounts.rankings(payload, next_day)}, context=stale)
    assert "requested_gross" not in old["model_identity"] and "previous_requested_gross" not in old["model_identity"]
    assert not old["rows"] and old["target"]["kind"] == "UNAVAILABLE"
    assert payload == before

def _forbid_ml_background_reads(monkeypatch):
    from apps.demo_console.adapters import new_strategy_replay_reader as replay
    def forbidden(*args, **kwargs):
        raise AssertionError("ML must not read Raw overview or performance histories")
    for name in ("load_overview","load_applied_strategies","load_active_strategies","read_performance","load_history"):
        monkeypatch.setattr(workspace,name,forbidden)
    monkeypatch.setattr(replay,"load_views",forbidden)
    return forbidden


def _ml_account_payload(sid, day="2026-09-24"):
    return {"books": {sid: {"strategy_id":sid,"plan":{
        "strategy_id":sid,"status":"READY","signal_date":day,"execution_date":"2026-09-25",
        "model_fit_calls":0,"broker_action_allowed":False,"target_cash_weight":.8,
        "rows":[{"ticker":"SYNTH","target_weight":.2,"weight_before":.1,
                 "action":"HOLD","source_score":0.,"raw_rank":7,"raw_score":.3,"exact_hold_units":0.}],
        "model_identity":{"recorded_current":True},"requested_gross":.2,"previous_requested_gross":.5}}}}


@pytest.mark.parametrize("sid", ("R10_DIRECT_MEAN4_ELASTICNET_MID","R10_DIRECT_H5_RIDGE_MID","R7_GROSS_LINEAR"))
def test_light_ml_native_reads_only_selected_current_output_and_never_raw_or_history(monkeypatch,sid):
    from apps.demo_console.adapters import applied_account_reader as accounts
    from apps.demo_console.adapters import new_strategy_stock_history_reader as native
    forbidden = _forbid_ml_background_reads(monkeypatch)
    monkeypatch.setattr(workspace,"load_applied_rankings",forbidden)
    monkeypatch.setattr(native,"rankings",forbidden)
    payload = _ml_account_payload(sid)
    before = deepcopy(payload)
    calls = []
    monkeypatch.setattr(accounts,"load_state",lambda: calls.append(True) or payload)
    result = workspace.load_ml_workspace(sid,"2026-09-24")
    assert calls == [True] and result["strategy_id"] == sid
    assert result["rows"][0]["ticker"] == "SYNTH"
    assert result["rows"][0]["target_weight"] == .2
    assert result["rows"][0]["native_action_score"] == (None if sid=="R7_GROSS_LINEAR" else 0.)
    assert result["rows"][0]["rank"] is result["rows"][0]["score"] is None
    assert result["model_identity"]["recorded_current"] is True
    assert result["target"]["kind"] == "CURRENT_ACCOUNT_TARGET"
    assert payload == before


def test_light_ml_missing_native_target_queries_only_selected_research_records(monkeypatch):
    from apps.demo_console.adapters import new_strategy_stock_history_reader as native
    sid="R10_DIRECT_H5_RIDGE_MID"
    forbidden = _forbid_ml_background_reads(monkeypatch)
    monkeypatch.setattr(workspace,"load_applied_rankings",forbidden)
    snapshot,_ = _ml_capture(sid,source="research",kind="RECORDED_RESEARCH_SIGNAL_PLAN")
    calls=[]
    def rankings(day,**kwargs):
        calls.append((day,kwargs))
        return snapshot
    monkeypatch.setattr(native,"rankings",rankings)
    result=workspace.load_ml_workspace(sid,"2026-09-24",package={},account_state={"books":{}})
    assert calls == [("2026-09-24",{"cutoff":"2026-09-24","strategy_ids":(sid,)})]
    assert result["record_basis"]=="RECORDED_MAIN_RESEARCH" and result["rows"]
    assert result["target"]["kind"]=="RECORDED_RESEARCH_SIGNAL_PLAN"


def test_light_ml_hgb_reuses_qualified_ranking_owner_without_performance(monkeypatch):
    sid="HGB_DIAG_5"
    _forbid_ml_background_reads(monkeypatch)
    snapshot,_=_ml_capture(sid)
    calls=[]
    monkeypatch.setattr(workspace,"load_applied_rankings",
        lambda day,**kwargs: calls.append((day,kwargs)) or snapshot)
    payload=_ml_account_payload(sid)
    result=workspace.load_ml_workspace(sid,"2026-09-24",package={"synthetic":True},account_state=payload)
    assert len(calls)==1 and calls[0][0]=="2026-09-24"
    assert result["model_identity"]["feature_count"]==21
    assert result["model_identity"]["prediction_scores_available"] is True
    assert result["rows"][0]["rank"]==2 and result["rows"][0]["score"]==.123
    assert result["target"]["kind"]=="CURRENT_ACCOUNT_TARGET"


@pytest.mark.parametrize("sid", ("HGB_DIAG_5","R10_DIRECT_MEAN4_ELASTICNET_MID",
                                  "R10_DIRECT_H5_RIDGE_MID","R7_GROSS_LINEAR"))
def test_historical_ml_keeps_own_mechanism_without_any_account_or_2026_reader(monkeypatch,sid):
    from apps.demo_console.adapters import applied_account_reader as accounts
    forbidden=_forbid_ml_background_reads(monkeypatch)
    for owner,name in ((accounts,"load_state"),(selected,"load_package"),(selected,"workspace_dates"),
                       (workspace,"load_active_rankings"),(workspace,"load_applied_rankings")):
        monkeypatch.setattr(owner,name,forbidden)
    assert workspace.ml_observation_dates({}, "historical")==()
    shell=workspace.load_ml_overview(sid,"2025-12-02",sample="historical",
        observation_dates=("2026-01-02",))
    assert shell.available_dates==() and shell.decision_date=="2025-12-02"
    assert shell.provenance.information_as_of is None
    result=workspace.load_ml_workspace(sid,"2025-12-02",sample="historical",package={})
    assert result["strategy_id"]==sid and result["mechanism_only"] is True
    assert result["rows"]==[] and result["error"]
    assert result["learning"].feature_columns==() and result["learning"].vintages==()
    assert result["target"]["kind"]=="UNAVAILABLE"


def test_ml_calendar_and_shell_use_given_dates_without_raw_or_future_fallback(monkeypatch):
    _forbid_ml_background_reads(monkeypatch)
    monkeypatch.setattr(selected,"workspace_dates",lambda package:("2025-12-31","2026-01-02","2026-01-05"))
    assert workspace.ml_observation_dates({},account_state={"books":{}})==("2026-01-02","2026-01-05")
    sid="R10_DIRECT_H5_RIDGE_MID"
    dates=("2026-01-02","2026-01-05")
    model=workspace.load_ml_overview(sid,"2026-01-04",observation_dates=dates)
    assert model.decision_date=="2026-01-04" and model.available_dates==dates
    assert model.provenance.information_as_of is None
    assert model.provenance.strategy_identity==sid
    assert model.ranking==model.holdings==() and model.performance_cutoff_date is None
    assert workspace.load_ml_overview(sid,"2025-12-31",observation_dates=dates).decision_date is None
    assert workspace.load_ml_overview(sid,"2026-01-04",observation_dates=()).decision_date=="2026-01-04"

def test_light_ml_query_ahead_of_package_calendar_stays_exact_and_does_not_borrow_old_output(monkeypatch):
    from apps.demo_console.adapters import new_strategy_stock_history_reader as native
    sid="R10_DIRECT_H5_RIDGE_MID"
    forbidden=_forbid_ml_background_reads(monkeypatch)
    monkeypatch.setattr(workspace,"load_applied_rankings",forbidden)
    monkeypatch.setattr(selected,"workspace_dates",lambda package:("2026-09-24",))
    dates=workspace.ml_observation_dates({},account_state={"books":{}})
    shell=workspace.load_ml_overview(sid,"2026-09-25",observation_dates=dates)
    assert shell.decision_date=="2026-09-25" and shell.available_dates==("2026-09-24",)
    assert shell.provenance.information_as_of is None
    old,_=_ml_capture(sid,source="research",kind="RECORDED_RESEARCH_SIGNAL_PLAN")
    monkeypatch.setattr(native,"rankings",lambda *args,**kwargs:old)
    result=workspace.load_ml_workspace(sid,shell.decision_date,package={},
        account_state=_ml_account_payload(sid))
    assert not result["rows"] and result["error"]
    assert result["target"]["kind"]=="UNAVAILABLE"

def test_ml_latest_uses_verified_account_signal_dates_without_future_execution_or_mark_dates(monkeypatch):
    from apps.demo_console.adapters import applied_account_reader as accounts
    forbidden=_forbid_ml_background_reads(monkeypatch)
    monkeypatch.setattr(selected,"workspace_dates",lambda package:("2026-09-24",))
    sid="R10_DIRECT_H5_RIDGE_MID"
    state=_ml_account_payload(sid,day="2026-09-25")
    state["books"][sid]["plan"]["execution_date"]="2026-09-28"
    state["books"][sid]["valuation"]={"observed_at_utc":"2026-09-29T16:00:00+00:00"}
    calls=[]
    monkeypatch.setattr(accounts,"load_state",lambda:calls.append(True) or state)
    dates=workspace.ml_observation_dates({})
    assert dates==("2026-09-24","2026-09-25") and calls==[True]
    model=workspace.load_ml_overview(sid,observation_dates=dates)
    assert model.decision_date=="2026-09-25"
    assert model.provenance.information_as_of=="2026-09-25"
    broken=deepcopy(state)
    broken["books"][sid]["plan"]["model_fit_calls"]=1
    assert workspace.ml_observation_dates({},account_state=broken)==("2026-09-24",)
    monkeypatch.setattr(accounts,"load_state",forbidden)
    assert workspace.ml_observation_dates({},sample="historical")==()


def test_light_ml_hgb_default_package_uses_base_reader_without_overlay(monkeypatch):
    _forbid_ml_background_reads(monkeypatch)
    sid="HGB_DIAG_5"
    calls=[]
    monkeypatch.setattr(selected,"load_package",lambda **kwargs:calls.append(kwargs) or {})
    snapshot,_=_ml_capture(sid)
    monkeypatch.setattr(workspace,"load_applied_rankings",lambda *args,**kwargs:snapshot)
    result=workspace.load_ml_workspace(sid,"2026-09-24",account_state=_ml_account_payload(sid))
    assert calls==[{"include_performance":False}]
    assert result["rows"] and result["error"] is None


def test_ml_calendar_projection_and_workspace_share_one_account_capture(monkeypatch, bound_package):
    from apps.demo_console.adapters import applied_account_reader as accounts
    from apps.demo_console.adapters import new_strategy_stock_history_reader as native
    sid = "R10_DIRECT_H5_RIDGE_MID"
    forbidden = _forbid_ml_background_reads(monkeypatch)
    monkeypatch.setattr(workspace, "load_applied_rankings", forbidden)
    monkeypatch.setattr(native, "rankings", forbidden)
    package_dates = selected.workspace_dates(bound_package)
    payload = _ml_account_payload(sid)
    before = deepcopy(payload)
    calls = []
    monkeypatch.setattr(accounts, "load_state", lambda: calls.append(True) or payload)
    state = accounts.load_state()
    expected_dates = workspace.ml_observation_dates(bound_package, account_state=state)
    monkeypatch.setattr(accounts, "load_state", forbidden)
    monkeypatch.setattr(selected, "workspace_dates", forbidden)
    dates = workspace.ml_observation_dates(sample="test_2026", package_dates=package_dates, account_state=state)
    result = workspace.load_ml_workspace(sid, "2026-09-24", package={}, account_state=state)
    assert dates == expected_dates and "2026-09-25" not in dates
    assert calls == [True] and payload == before
    assert result["rows"][0]["ticker"] == "SYNTH"
    assert result["target"]["signal_date"] == "2026-09-24"


def test_ml_calendar_projection_historical_never_reads_source_or_account(monkeypatch):
    from apps.demo_console.adapters import applied_account_reader as accounts
    forbidden = _forbid_ml_background_reads(monkeypatch)
    for owner, name in ((accounts, "load_state"), (selected, "load_package"),
                        (selected, "load_workspace_calendar"), (selected, "workspace_dates")):
        monkeypatch.setattr(owner, name, forbidden)
    assert workspace.ml_observation_dates(sample="historical", package_dates=()) == ()
    result = workspace.load_ml_workspace("R10_DIRECT_H5_RIDGE_MID", "2025-12-02", sample="historical")
    assert result["mechanism_only"] is True and result["rows"] == []


def test_ml_renderer_forwards_ephemeral_account_capture(monkeypatch):
    from types import SimpleNamespace
    from apps.demo_console.adapters import applied_account_reader as accounts
    from apps.demo_console.pages import selected_strategies as page, machine_learning
    state = _ml_account_payload("R10_DIRECT_H5_RIDGE_MID")
    before = deepcopy(state)
    session = {"workspace_strategy": "R10_DIRECT_H5_RIDGE_MID", "decision_date": "2026-09-24",
               "workspace_sample": "test_2026"}
    monkeypatch.setattr(page, "st", SimpleNamespace(session_state=session, html=lambda *_: None))
    monkeypatch.setattr(page, "apply_style", lambda **_: None)
    monkeypatch.setattr(page, "tr", lambda value: value)
    monkeypatch.setattr(accounts, "load_state", lambda: pytest.fail("Renderer recaptured account state"))
    calls = []
    def project(sid, day, **kwargs):
        assert kwargs["account_state"] is state and kwargs["package"] == {}
        calls.append((sid, day))
        return {"synthetic": True}
    monkeypatch.setattr(workspace, "load_ml_workspace", project)
    monkeypatch.setattr(machine_learning, "render_machine_learning", lambda *_, **kwargs:
        calls.append(kwargs["workspace"]))
    page.render_workspace(DecisionOverview(decision_date="2026-09-24"), {},
        view="Machine learning", account_state=state)
    assert calls == [("R10_DIRECT_H5_RIDGE_MID", "2026-09-24"), {"synthetic": True}]
    assert state == before and set(session) == {"workspace_strategy", "decision_date", "workspace_sample"}
