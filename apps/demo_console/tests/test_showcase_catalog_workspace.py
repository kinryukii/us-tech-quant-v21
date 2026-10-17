"""Cross-owner catalog projections stay read-only and retain native units."""
from copy import deepcopy
import pytest
from apps.demo_console.adapters import workspace_reader as workspace
from apps.demo_console.adapters import applied_account_reader as accounts
from apps.moomoo_trading_component.moomoo_component.strategy import (
    ACTIVE_PAPER_STRATEGY_IDS, QUERYABLE_STRATEGY_IDS,
)


def test_catalog_extension_does_not_change_the_accepted_v1_execution_membership():
    assert len(ACTIVE_PAPER_STRATEGY_IDS) == 5
    assert len(QUERYABLE_STRATEGY_IDS) == len(set(QUERYABLE_STRATEGY_IDS)) == 8
    assert QUERYABLE_STRATEGY_IDS[:5] == ACTIVE_PAPER_STRATEGY_IDS
    assert "R10_DIRECT_H5_RIDGE_MID" in QUERYABLE_STRATEGY_IDS
    assert "H5_RIDGE_MID" not in QUERYABLE_STRATEGY_IDS
    assert "RAW_A2" in QUERYABLE_STRATEGY_IDS and "RAW_s10" in QUERYABLE_STRATEGY_IDS


def test_all_catalog_identities_and_mechanisms_are_source_free(monkeypatch):
    from apps.demo_console.adapters import new_strategy_replay_reader as native
    monkeypatch.setattr(native, "_history", lambda *a, **k: pytest.fail("mechanism must not read outcomes"))
    for sid in QUERYABLE_STRATEGY_IDS:
        model = workspace.load_ml_overview(sid, "2026-10-08", observation_dates=("2026-10-08",))
        assert model.source_id == sid and model.decision_date == "2026-10-08"
        assert not model.ranking
    with pytest.raises(ValueError):
        workspace.load_ml_overview("UNREGISTERED_MODEL")


def test_queryable_books_keep_hidden_history_without_manufacturing_a_current_target():
    original = {"books": {"duration": {"strategy_id": "R6_DURATION_TREE", "positions": [{"ticker": "SYNTH"}],
        "plan": {"strategy_id": "R6_DURATION_TREE", "signal_date": "2026-10-08"}},
        "raw": {"strategy_id": "RAW_s10", "plan": None},
        "unknown": {"strategy_id": "UNREGISTERED_MODEL"}}}
    before = deepcopy(original)
    assert set(accounts.books(original)) == {"R6_DURATION_TREE", "RAW_s10"}
    view = accounts.current_view(original, "R6_DURATION_TREE", "2026-10-15")
    assert view["status"] == "UNAVAILABLE" and view["target"]["target_cash_weight"] is None
    assert original == before


def test_native_units_and_score_roles_are_not_interchanged_for_the_new_catalog():
    day = "2026-10-08"
    leaf = {"status": "AVAILABLE", "actual_signal_date": day, "weight_date": day,
        "target_kind": "RECORDED_RESEARCH_SIGNAL_PLAN", "source_kind": "research",
        "rows": [{"ticker": "SYNTH", "model_rank": 2, "score": .03,
                  "source_score": .7, "raw_rank": 3, "raw_score": .01,
                  "action": "SELL", "target_weight": 0.}]}
    for sid in ("R6_BUY_NEURAL", "R6_DURATION_TREE", "RAW_s10"):
        result = workspace.ml_workspace(sid, day, snapshot={"strategies": {sid: leaf}}, context={"strategy_id": sid})
        row = result["rows"][0]
        if sid == "RAW_s10":
            assert result["output_kind"] == "RANK_SCORE" and row["score"] == .03
            assert row["native_action_score"] is None
        else:
            assert result["output_kind"] == "ACTION_VALUE" and row["score"] is None and row["rank"] is None
            assert row["native_action_score"] == .7
        assert row["target_weight"] == 0. and row["raw_score"] == .01


@pytest.mark.parametrize("history_sid,plan_sid,exists,expected", [
    (None, None, True, None), (None, "KNOWN_SID", True, None),
    ("OLD_SID", "NEW_SID", True, None), ("KNOWN_SID", "KNOWN_SID", True, .2),
    (None, None, False, 0.),
])
def test_stock_target_unknown_identity_is_not_interpreted_as_absence(monkeypatch, history_sid, plan_sid, exists, expected):
    from apps.demo_console.adapters import new_strategy_stock_history_reader as native
    day, sid = "2026-10-08", "R6_DURATION_TREE"
    monkeypatch.setattr(workspace, "query_applied_stock_history", lambda *a, **k: {
        "status": "READY", "ticker": "SYNTH", "daily": [{"date": day, "security_id": history_sid}],
    })
    monkeypatch.setattr(native, "query", lambda *a, **k: {"strategies": {}, "note": "SYNTHETIC"})
    leaves = {item: {"status": "UNAVAILABLE", "rows": [], "weight_date": None} for item in QUERYABLE_STRATEGY_IDS}
    leaves[sid] = {"status": "AVAILABLE", "weight_date": day, "target_kind": "CURRENT_ACCOUNT_TARGET",
        "rows": [{"ticker": "SYNTH", "security_id": plan_sid, "target_weight": .2, "selected": True}] if exists else []}
    monkeypatch.setattr(accounts, "rankings", lambda *a, **k: leaves)
    result = workspace.query_active_stock_history({"start_date": day, "as_of": day}, "SYNTH")
    target = result["daily"][0]["strategies"][sid]
    assert target["target_weight"] == expected
    if expected is None:
        assert target["selected"] is None and target["target_status"] == "SECURITY_IDENTITY_UNVERIFIED"



def test_retired_book_remains_queryable_and_never_overrides_the_active_capture():
    sid = "R10_DIRECT_MEAN4_ELASTICNET_MID"
    retired = {"strategy_id": sid, "status": "PAUSED", "nav_history": [{"nav": 1.1}], "plan": None}
    state = {"books": {}, "legacy_history": {"books": {sid: retired}}}
    assert accounts.books(state)[sid] == retired
    state["books"][sid] = {**retired, "status": "TARGET_ONLY", "nav_history": [{"nav": 1.2}]}
    assert accounts.books(state)[sid]["status"] == "TARGET_ONLY"
    assert retired["status"] == "PAUSED"



def test_mechanism_roster_uses_only_the_small_fixed_metadata_endpoint(monkeypatch):
    from unittest.mock import Mock
    import json
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read1.side_effect = [json.dumps({"ok": True, "data": {"books": {}, "metadata_only": True}}).encode(), b""]
    monkeypatch.setattr(accounts.http.client, "HTTPConnection", lambda *a, **k: connection)
    accounts.load_roster.clear()
    result = accounts.load_roster()
    assert result["metadata_only"] is True and result["books"] == {}
    connection.request.assert_called_once_with("GET", "/api/applied/showcase-roster", headers={"Accept": "application/json"})
    connection.close.assert_called_once()
    accounts.load_roster.clear()
    with pytest.raises(ValueError):
        accounts._read_projection("https://arbitrary.example/", 100)


def test_an_existing_account_capture_does_not_make_a_second_roster_request(monkeypatch):
    monkeypatch.setattr(accounts, "load_roster", lambda: pytest.fail("capture already supplied"))
    result = accounts.showcase_projection({"books": {}})
    assert tuple(result["showcase_ids"]) == ACTIVE_PAPER_STRATEGY_IDS



def test_empty_new_method_offers_an_explicit_shared_date_query_without_reading_data(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(accounts, "load_state", lambda: pytest.fail("no account capture for mechanism illustration"))
    source = """
import streamlit as st
from apps.demo_console.models import DecisionOverview
from apps.demo_console.adapters.workspace_reader import ml_workspace
from apps.demo_console.pages.machine_learning import render_machine_learning
sid = "R6_DURATION_TREE"
day = st.session_state.get("decision_date", "2026-10-15")
workspace = ml_workspace(sid, day, snapshot={"strategies": {}}, context={
    "strategy_id": sid, "model_identity": {"frozen_main_end": "2026-10-08"}})
render_machine_learning(DecisionOverview(decision_date=day), workspace=workspace)
"""
    app = AppTest.from_string(source, default_timeout=30)
    app.session_state["language"] = "en"
    app.session_state["workspace_sample"] = "test_2026"
    app.session_state["_workbench_dates:test_2026"] = ("2026-10-08", "2026-10-15")
    app.run()
    assert not app.exception
    assert app.session_state["ml_engine_ticker"] is None
    app.button(key="ml_frozen_records").click().run()
    assert not app.exception
    assert app.session_state["decision_date"] == "2026-10-08"
    assert not any(button.key == "ml_frozen_records" for button in app.button)
