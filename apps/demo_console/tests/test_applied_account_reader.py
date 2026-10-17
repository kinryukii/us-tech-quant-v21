"""Five-strategy presentation contracts using synthetic state only."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from apps.demo_console.adapters import applied_account_reader as reader
from apps.demo_console.pages.research import _active_comparison
from apps.moomoo_trading_component.moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS


def state():
    return {"books": {sid: {"strategy_id": sid, "account_id": "synthetic-" + sid,
        "plan": {"strategy_id": sid, "status": "READY", "signal_date": "2026-01-07",
            "execution_date": "2026-01-08", "model_fit_calls": 0, "broker_action_allowed": False,
            "target_cash_weight": .4, "rows": [{"ticker": "SYN_A", "security_id": "synthetic-cusip",
                "target_weight": .6, "weight_before": .3, "action": "BUY", "raw_rank": 1}]},
        "nav_history": [{"asof": "2026-01-08T14:31:00+00:00", "nav": 1.01}],
        "equity": 10100, "cash": 4040, "positions": []} for sid in ACTIVE_PAPER_STRATEGY_IDS}}


def test_current_plans_never_acquire_executed_or_research_return_status():
    payload = state()
    before = deepcopy(payload)
    views = reader.views(payload, "2026-01-07")
    assert tuple(views) == ACTIVE_PAPER_STRATEGY_IDS[2:]
    for view in views.values():
        assert view["target"]["execution_status"] == "TARGET_ONLY"
        assert view["target"]["kind"] == "CURRENT_ACCOUNT_TARGET"
        assert view["history"]["daily"] == [] and view["history"]["summary"] is None
        assert view["current_account"]["nav_history"][0]["nav"] == 1.01
    assert payload == before
    assert all(not view["target"]["rows"] for view in reader.views(payload, "2026-01-08").values())
    assert reader.observation_dates(payload) == ("2026-01-07",)


@pytest.mark.parametrize("change", [{"model_fit_calls": 1}, {"broker_action_allowed": True},
    {"target_cash_weight": .9}, {"rows": [{"ticker": "SYN_A", "target_weight": float("nan")}]}])
def test_bad_plan_blanks_only_its_strategy(change):
    payload = state();sid = ACTIVE_PAPER_STRATEGY_IDS[2]
    payload["books"][sid]["plan"].update(change)
    views = reader.views(payload, "2026-01-07")
    assert views[sid]["status"] == "BLOCKED" and not views[sid]["target"]["rows"]
    assert all(view["status"] == "AVAILABLE" for other, view in views.items() if other != sid)


def test_raw_input_rank_is_not_misrepresented_as_native_model_rank():
    ranks = reader.rankings(state(), "2026-01-07")
    assert all(leaf["rows"][0]["model_rank"] is None and leaf["rows"][0]["score"] is None
        and leaf["rows"][0]["raw_rank"] == 1 for leaf in ranks.values())


def test_http_is_fixed_get_bounded_and_closes_connection(monkeypatch):
    reader.load_state.clear()
    connection = Mock();response = connection.getresponse.return_value
    response.status = 200;response.read1.side_effect = [json.dumps({"ok": True, "data": state()}).encode(), b""]
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(reader.http.client, "HTTPConnection", constructor)
    assert reader.load_state()["books"]
    constructor.assert_called_once_with("127.0.0.1", 8766, timeout=10)
    connection.request.assert_called_once_with("GET", "/api/applied/view", headers={"Accept": "application/json"})
    assert all(call.args[0] <= reader._READ_CHUNK_BYTES for call in response.read1.call_args_list)
    connection.close.assert_called_once()
    reader.load_state.clear()


def test_response_deadline_is_finite_and_closes_before_overdue_body(monkeypatch):
    reader.load_state.clear()
    connection=Mock();response=connection.getresponse.return_value;response.status=200
    clock=iter((0.,1.,15.))
    monkeypatch.setattr(reader,"monotonic",lambda:next(clock))
    monkeypatch.setattr(reader.http.client,"HTTPConnection",lambda *args,**kwargs:connection)
    assert reader.load_state()=={"books":{},"error":"APPLIED_ACCOUNT_TOTAL_TIMEOUT"}
    response.read1.assert_not_called()
    connection.close.assert_called_once()
    reader.load_state.clear()


def test_connected_first_response_and_body_share_remaining_total_budget(monkeypatch):
    reader.load_state.clear()
    connection=Mock();response=connection.getresponse.return_value;response.status=200
    response.read1.side_effect=[json.dumps({"ok":True,"data":state()}).encode(),b""]
    clock=iter((0.,.5,12.,12.1))
    monkeypatch.setattr(reader,"monotonic",lambda:next(clock))
    constructor=Mock(return_value=connection)
    monkeypatch.setattr(reader.http.client,"HTTPConnection",constructor)
    assert reader.load_state()["books"]
    constructor.assert_called_once_with("127.0.0.1",8766,timeout=10)
    assert connection.sock.settimeout.call_args_list[0].args==(14.5,)
    assert connection.sock.settimeout.call_args_list[1].args==(3.,)
    assert connection.sock.settimeout.call_args_list[2].args[0]==pytest.approx(2.9)
    connection.close.assert_called_once()
    reader.load_state.clear()


def test_response_limit_still_rejects_more_than_four_mib(monkeypatch):
    reader.load_state.clear()
    connection=Mock();response=connection.getresponse.return_value;response.status=200
    response.read1.side_effect=[b"x"*reader._READ_CHUNK_BYTES]*64+[b"x"]
    monkeypatch.setattr(reader.http.client,"HTTPConnection",lambda *args,**kwargs:connection)
    result=reader.load_state()
    assert result=={"books":{},"error":"APPLIED_ACCOUNT_RESPONSE_LIMIT"}
    assert response.read1.call_args_list[-1].args==(1,)
    connection.close.assert_called_once()
    reader.load_state.clear()


def test_future_planned_execution_remains_available_on_signal_date_without_replay_extension():
    payload=state();cutoff="2026-10-12"
    for book in payload["books"].values():
        book["plan"].update(signal_date=cutoff,execution_date="2026-10-13")
    ranks=reader.rankings(payload,cutoff)
    for sid in ACTIVE_PAPER_STRATEGY_IDS:
        view=reader.current_view(payload,sid,cutoff)
        assert view["status"]=="AVAILABLE"
        assert view["target"]["signal_date"]==cutoff
        assert view["target"]["execution_date"]=="2026-10-13"
        assert view["history"]["daily"]==[] and view["history"]["end"] is None
        assert ranks[sid]["weight_date"]==ranks[sid]["actual_signal_date"]==cutoff
    assert all(reader.current_view(payload,sid,"2026-10-11")["status"]=="UNAVAILABLE"
        for sid in ACTIVE_PAPER_STRATEGY_IDS)


def test_shared_window_preserves_earlier_baseline_and_rejects_internal_missing_dates():
    dates = ("2026-01-05", "2026-01-06", "2026-01-07")
    contexts = {sid: {"label": sid, "history": {"daily": [{"date": day, "nav": nav, "cash_weight": .5}
        for day, nav in zip(dates, (1.1, 1.21, 1.331))]}} for sid in ACTIVE_PAPER_STRATEGY_IDS}
    comparison = _active_comparison(contexts, dates[1], dates[-1])
    assert len(comparison["windows"]) == 5
    assert all(window["cumulative_return"] == pytest.approx(.21) for window in comparison["windows"].values())
    contexts[ACTIVE_PAPER_STRATEGY_IDS[-1]]["history"]["daily"].pop(1)
    assert _active_comparison(contexts, dates[0], dates[-1]) is None


def test_main_entry_shows_all_five_and_switches_new_focus_without_raw_substitution(tmp_path, monkeypatch):
    from apps.demo_console import app as console
    from apps.demo_console.tests.test_hgb_main_workspace import _package, _new_app, _summary
    from apps.demo_console.models import DecisionOverview, PerformanceHistory
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory
    from apps.demo_console.pages import research
    package = _package()
    path = tmp_path / "legacy-package.json"
    path.write_text(json.dumps(package), encoding="utf-8")
    monkeypatch.setenv("USTQ_SELECTED_HGB_PACKAGE", str(path))
    current = state()
    for index, book in enumerate(current["books"].values()):
        book["plan"].update(signal_date="2026-09-24", execution_date="2026-09-25",
                            model_id=f"synthetic-native-model-{index}")
        book["plan"]["rows"][0].update(ticker=f"SYN_NATIVE_{index}", security_id=f"synthetic-cusip-{index}")
    before = deepcopy(current)
    from apps.demo_console.adapters import new_strategy_replay_reader
    monkeypatch.setattr(new_strategy_replay_reader, "load_views", lambda *args, **kwargs: {})
    monkeypatch.setattr(reader, "load_state", lambda: current)
    monkeypatch.setattr(research, "read_updated_benchmarks", lambda *args, **kwargs: BenchmarkHistory())
    model = DecisionOverview(decision_date="2026-09-24", available_dates=("2026-09-23", "2026-09-24"),
        source_id=console.workspace_reader.LATEST, performance_cutoff_date="2026-09-24")
    monkeypatch.setattr(console, "_load_workspace_model", lambda: model)
    monkeypatch.setattr(console, "_refresh_published_data", lambda **kwargs: None)
    monkeypatch.setattr(console.workspace_reader, "load_overview", lambda *args, **kwargs: model)
    monkeypatch.setattr(console.workspace_reader, "read_performance", lambda *args: PerformanceHistory(error="SYNTHETIC_UNAVAILABLE"))
    monkeypatch.setattr(console.workspace_reader, "latest_executed_overview", lambda *args: None)
    original_rankings = console.workspace_reader.load_active_rankings
    captures = []
    def rankings(day, **kwargs):
        assert kwargs["raw_model"] is None and kwargs["account_state"] is current
        result = original_rankings(day, **kwargs)
        captures.append(result)
        return result
    monkeypatch.setattr(console.workspace_reader, "load_active_rankings", rankings)
    from apps.demo_console.adapters import selected_strategies_reader as selected
    selected.clear_cache()
    app = _new_app(strategy=ACTIVE_PAPER_STRATEGY_IDS[2], view="Machine learning", date="2026-09-24")
    assert not app.exception and not app.error
    assert tuple(app.selectbox(key="workspace_strategy").options) == tuple(console._STRATEGIES.values())
    # The unified entry selects one native workbench. It no longer builds the
    # retired sidebar or fetches every strategy's history for an ML visit.
    for index, sid in enumerate(ACTIVE_PAPER_STRATEGY_IDS[2:], start=2):
        app.selectbox(key="workspace_strategy").select(sid).run()
        assert not app.exception and not app.error
        assert app.selectbox(key="workspace_strategy").value == sid
        assert app.selectbox(key="decision_date").value == "2026-09-24"
        snapshot = captures[-1]["strategies"]
        assert tuple(snapshot) == (sid,)
        rows = snapshot[sid]["rows"]
        assert [row["ticker"] for row in rows] == [f"SYN_NATIVE_{index}"]
        assert rows[0]["security_id"] == f"synthetic-cusip-{index}"
        assert rows[0]["model_rank"] is None and rows[0]["score"] is None
        assert app.selectbox(key="ml_engine_ticker").value == f"SYN_NATIVE_{index}"
        assert rows[0]["ticker"] != current["books"]["RAW_A2"]["plan"]["rows"][0]["ticker"]
    from apps.demo_console.adapters import new_strategy_stock_history_reader as native_history
    monkeypatch.setattr(native_history, "rankings", lambda day, **kwargs: {
        "strategies": {sid: {"status": "UNAVAILABLE", "rows": [], "weight_date": None,
            "actual_signal_date": None, "target_kind": "UNAVAILABLE"} for sid in kwargs["strategy_ids"]}})
    # Querying a registered addition with no current plan cannot fall back to
    # Raw or inherit an older book's ticker, score or target.
    app.selectbox(key="workspace_strategy").select("R6_DURATION_TREE").run()
    assert not app.exception and not app.error
    assert captures[-1]["strategies"]["R6_DURATION_TREE"]["rows"] == []
    assert app.session_state["ml_engine_ticker"] is None
    assert current == before
    selected.clear_cache()


def test_all_active_targets_use_owned_books_and_default_replay_hook_keeps_research_separate(monkeypatch):
    from apps.demo_console.adapters import workspace_reader as workspace, new_strategy_replay_reader as replay
    original = {sid: {"strategy_id": sid, "requested_cutoff": "2026-01-07", "target": {
        "kind": "HISTORICAL_SIGNAL_TARGET", "signal_date": "2026-01-07", "rows": [],
        "target_cash_weight": 1.}, "history": {"daily": []}} for sid in ("RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5")}
    original["RAW_A2"]["signal_target"] = {"kind": "RAW_RULE_TARGET", "target_cash_weight": 1.}
    monkeypatch.setattr(workspace, "load_applied_strategies", lambda *args, **kwargs: deepcopy(original))
    frozen = {sid: {"history": {"daily": [{"date": "2026-01-07", "nav": 1.2, "cash_weight": .3}],
        "start": "2026-01-07", "end": "2026-01-07"}, "model_identity": {"candidate_id": sid},
        "provenance": {"scope": "SYNTHETIC_ACCEPTED_REPLAY"}} for sid in ACTIVE_PAPER_STRATEGY_IDS[2:]}
    load = Mock(return_value=frozen);monkeypatch.setattr(replay, "load_views", load)
    views = workspace.load_active_strategies("2026-01-07", package={}, account_state=state())
    assert tuple(views) == ACTIVE_PAPER_STRATEGY_IDS
    assert all(view["target"]["target_cash_weight"] == .4 for view in views.values())
    assert all(view["target"]["execution_status"] == "TARGET_ONLY" for view in views.values())
    for sid in ACTIVE_PAPER_STRATEGY_IDS[:2]:
        assert views[sid]["research_target"]["target_cash_weight"] == 1.
    assert views["RAW_A2"]["signal_target"] == views["RAW_A2"]["target"]
    for sid in ACTIVE_PAPER_STRATEGY_IDS[2:]:
        assert views[sid]["history"]["daily"][0]["nav"] == 1.2
        assert views[sid]["current_account"]["nav_history"][0]["nav"] == 1.01
    load.assert_called_once_with("2026-01-07", history_cutoff=None, sample="test_2026")


def test_action_model_row_limit_follows_input_ranks_without_inventing_native_ranks():
    from apps.demo_console.components.top20_table import applied_ranking_rows
    rows = [{"ticker": "SYN_A", "model_rank": None, "raw_rank": 3},
            {"ticker": "SYN_Z", "model_rank": None, "raw_rank": 1}]
    shown = applied_ranking_rows(rows, top_n=1)
    assert shown[0]["ticker"] == "SYN_Z" and shown[0]["model_rank"] is None
