"""Synthetic same-day MAIN research display; no research models, SDK or HTTP."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.demo_console.adapters import new_strategy_stock_history_reader as native
from apps.demo_console.components.top20_table import applied_ranking_display, applied_ranking_rows

SID = "R10_DIRECT_MEAN4_ELASTICNET_MID"
DAY = "2026-01-02"


def _ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _sources(tmp_path, actions=None, orders=None):
    common = dict(path_id=SID, signal_date=datetime(2026, 1, 2))
    action = dict(**common, ticker="ALPHA", policy_explicit=True, policy_weight=.25,
        policy_action="BUY_OR_ADD", actual_weight=.1, planned_execution_date=datetime(2026, 1, 5))
    order = dict(**common, ticker="ALPHA", target_weight=.25, adapted_target_weight=.2,
        hold_units=0., decision_semantic="MODEL_TARGET_WEIGHT", execution_date=datetime(2026, 1, 5),
        status="LATER_STATUS_MUST_NOT_BE_DECODED")
    if actions is None:
        actions = [action, {**action, "ticker": "BETA", "policy_action": "HOLD", "policy_weight": None},
            {**action, "ticker": "FUTURE", "signal_date": datetime(2027, 1, 2)},
            {**action, "ticker": "OTHER_DAY", "signal_date": datetime(2026, 1, 6)},
            {**action, "ticker": "OTHER_SID", "path_id": "OTHER"}]
    if orders is None:
        orders = [order, {**order, "ticker": "BETA", "target_weight": None, "adapted_target_weight": None,
            "hold_units": 2., "decision_semantic": "EXACT_UNIT_HOLD"},
            {**order, "ticker": "FUTURE", "signal_date": datetime(2027, 1, 2)}]
    refs = {}
    for name, rows in (("actions", actions), ("orders", orders)):
        path = tmp_path / (name + ".parquet")
        pq.write_table(pa.Table.from_pylist(rows), path)
        refs[name] = _ref(path)
    # These remain opaque: this endpoint must not decode positions/fills.
    for name in ("positions", "fills"):
        path = tmp_path / (name + ".parquet"); path.write_bytes(b"not-a-parquet-table")
        refs[name] = _ref(path)
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps({"candidate_ids": [SID]}), encoding="utf8")
    refs["receipt"] = _ref(path)
    return {SID: refs}


@pytest.fixture(autouse=True)
def _clear_day_cache():
    native._cached_rankings.cache_clear()
    yield
    native._cached_rankings.cache_clear()


def test_day_projection_preserves_action_order_weights_hold_and_unknown_rank(tmp_path):
    sources = _sources(tmp_path)
    leaf = native.rankings(DAY, cutoff=DAY, sources=sources)["strategies"][SID]
    assert leaf["status"] == "AVAILABLE" and leaf["source_kind"] == "research"
    assert leaf["actual_signal_date"] == leaf["weight_date"] == DAY
    rows = {r["ticker"]: r for r in leaf["rows"]}
    assert list(rows) == ["ALPHA", "BETA"]
    assert rows["ALPHA"]["original_policy_weight"] == .25
    assert rows["ALPHA"]["research_order_target_weight"] == .25
    assert rows["ALPHA"]["adapted_target_weight"] == rows["ALPHA"]["target_weight"] == .2
    assert rows["BETA"]["target_weight"] is rows["BETA"]["selected"] is None
    assert rows["BETA"]["hold_units"] == 2 and rows["BETA"]["decision_semantic"] == "EXACT_UNIT_HOLD"
    assert all(r[k] is None for r in rows.values() for k in ("model_rank", "score", "raw_rank", "raw_score", "source_score", "security_id"))
    assert "LATER_STATUS" not in str(leaf) and "execution_date" not in rows["ALPHA"]["research_orders"][0]
    assert all(r["target_kind"] == "RECORDED_RESEARCH_SIGNAL_PLAN" for r in rows.values())
    rows["ALPHA"]["target_weight"] = 9.
    assert native.rankings(DAY, cutoff=DAY, sources=sources)["strategies"][SID]["rows"][0]["target_weight"] == .2
    assert native._cached_rankings.cache_info().maxsize == 1


def test_scanner_uses_exact_day_sid_and_only_approved_columns(tmp_path, monkeypatch):
    import pyarrow.dataset as ds
    sources = _sources(tmp_path); real = ds.dataset; seen = []
    class Guard:
        def __init__(self, value, name): self.value, self.name, self.schema = value, name, value.schema
        def scanner(self, **kwargs):
            columns = kwargs["columns"]
            assert kwargs["batch_size"] == 256 and kwargs["use_threads"] is False
            assert kwargs["batch_readahead"] == kwargs["fragment_readahead"] == 1
            assert "path_id" in str(kwargs["filter"]) and "signal_date" in str(kwargs["filter"])
            assert "positions" not in self.name and "fills" not in self.name
            if self.name.endswith("orders.parquet"):
                assert set(columns) == {"path_id", "signal_date", "ticker", "target_weight", "adapted_target_weight", "hold_units", "decision_semantic"}
                assert not {"execution_date", "status"} & set(columns)
            else:
                assert set(columns) == {"path_id", "signal_date", "ticker", "policy_explicit", "policy_weight", "policy_action", "actual_weight"}
                assert "planned_execution_date" not in columns
            seen.append(self.name)
            return self.value.scanner(**kwargs)
    monkeypatch.setattr(ds, "dataset", lambda path, **kw: Guard(real(path, **kw), str(path)))
    assert native.rankings(DAY, cutoff=DAY, sources=sources)["strategies"][SID]["status"] == "AVAILABLE"
    assert len(seen) == 2


@pytest.mark.parametrize("changed", ("target_weight", "adapted_target_weight", "hold_units", "decision_semantic"))
def test_inconsistent_same_ticker_orders_block_instead_of_averaging(tmp_path, changed):
    sources = _sources(tmp_path)
    path = sources[SID]["orders"]["path"]
    rows = pq.read_table(path).to_pylist(); row = dict(rows[0])
    row[changed] = "CONFLICT" if changed == "decision_semantic" else .91
    pq.write_table(pa.Table.from_pylist(rows + [row]), path); sources[SID]["orders"] = _ref(__import__("pathlib").Path(path))
    leaf = native.rankings(DAY, cutoff=DAY, sources=sources)["strategies"][SID]
    assert leaf["status"] == "BLOCKED" and leaf["rows"] == [] and "CONFLICTING_ORDERS" in leaf["error"]


def test_duplicate_actions_and_row_limit_fail_closed(tmp_path):
    sources = _sources(tmp_path)
    path = __import__("pathlib").Path(sources[SID]["actions"]["path"])
    first = pq.read_table(path).to_pylist()[0]
    pq.write_table(pa.Table.from_pylist([first, first]), path); sources[SID]["actions"] = _ref(path)
    assert "DUPLICATE_ACTION" in native.rankings(DAY, cutoff=DAY, sources=sources)["strategies"][SID]["error"]
    pq.write_table(pa.Table.from_pylist([{**first, "ticker": "S" + str(i)} for i in range(4097)]), path)
    sources[SID]["actions"] = _ref(path)
    assert "DAY_ROW_LIMIT" in native.rankings(DAY, cutoff=DAY, sources=sources)["strategies"][SID]["error"]


def test_source_bytes_are_reverified_on_cache_hit_and_during_read(tmp_path, monkeypatch):
    from pathlib import Path
    sources = _sources(tmp_path)
    assert native.rankings(DAY, sources=sources)["strategies"][SID]["status"] == "AVAILABLE"
    Path(sources[SID]["receipt"]["path"]).write_bytes(b"changed")
    assert "CHANGED" in native.rankings(DAY, sources=sources)["strategies"][SID]["error"]
    sources = _sources(tmp_path); real = native._rows
    def changed(*args, **kwargs):
        rows = real(*args, **kwargs)
        if args[2] == "orders": Path(sources[SID]["receipt"]["path"]).write_bytes(b"changed-again")
        return rows
    monkeypatch.setattr(native, "_rows", changed)
    assert "CHANGED" in native.rankings(DAY, sources=sources)["strategies"][SID]["error"]


@pytest.mark.parametrize("day,cutoff", (("2025-12-31", "2025-12-31"), ("2027-01-01", "2027-01-01"), ("2026-1-2", DAY), ("2026-01-05", DAY)))
def test_invalid_or_out_of_selected_dates_never_query_source(day, cutoff, monkeypatch):
    monkeypatch.setattr(native, "qualified_sources", lambda: pytest.fail("queried real publication"))
    with pytest.raises(ValueError): native.rankings(day, cutoff=cutoff)


def test_invalid_publication_reason_and_after_end_are_blocked_not_clamped(tmp_path, monkeypatch):
    sources = _sources(tmp_path)
    monkeypatch.setattr(native, "qualified_sources", lambda: {"status": "FALLBACK_ACCEPTED_PREFIX", "reason": "SYNTHETIC_PUBLICATION_HASH_CHANGED"})
    monkeypatch.setattr(native, "source_refs", lambda **kwargs: sources)
    monkeypatch.setattr(native, "_rows", lambda *a, **k: pytest.fail("invalid publication scanned rows"))
    leaf = native.rankings("2026-10-13", cutoff="2026-10-13", strategy_ids=(SID,))["strategies"][SID]
    assert leaf["status"] == "BLOCKED" and leaf["error"] == "SYNTHETIC_PUBLICATION_HASH_CHANGED"
    leaf = native.rankings("2026-10-13", cutoff="2026-10-13", sources=sources)["strategies"][SID]
    assert leaf["status"] == "BLOCKED" and "EXCEEDS_ACCEPTED_END" in leaf["error"]


def test_new_and_original_routes_share_old_pending_baseline_source_gate(tmp_path, monkeypatch):
    sources = _sources(tmp_path); chosen = {}
    for sid in native._HASHES:
        refs = deepcopy(sources[SID]); refs.update(extension_manifest={"path": "synthetic", "sha256": "a" * 64}, qualified_end="2026-10-13", baseline_refs=deepcopy(sources[SID]))
        chosen[sid] = refs
    monkeypatch.setattr(native, "qualified_manifest", lambda ref: {"stock_sources": chosen, "end": "2026-10-13", "publication_ref": ref})
    old, end = native._bound_sources(chosen, DAY)
    assert end == "2026-10-08" and all(v["actions"] == sources[SID]["actions"] for v in old.values())
    future, end = native._bound_sources(chosen, "2026-10-13")
    assert future == chosen and end == "2026-10-13"


def _workspace_fixture(monkeypatch, statuses):
    from apps.demo_console.adapters import workspace_reader as workspace, applied_account_reader as accounts
    from apps.moomoo_trading_component.moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS
    current = {sid: {"status": statuses.get(sid, "AVAILABLE"), "rows": [{"ticker": sid}], "target_kind": "CURRENT_ACCOUNT_TARGET"} for sid in ACTIVE_PAPER_STRATEGY_IDS}
    monkeypatch.setattr(workspace, "load_applied_rankings", lambda *a, **k: {"status": "READY", "strategies": {}})
    monkeypatch.setattr(accounts, "rankings", lambda *a, **k: deepcopy(current))
    monkeypatch.setattr(accounts, "load_state", lambda: pytest.fail("HTTP called"))
    state = {"books": {SID: {"strategy_id": SID, "plan": {"strategy_id": SID, "signal_date": "2026-01-01"}}}}
    leaf = dict(status="AVAILABLE", actual_signal_date=DAY, weight_date=DAY, source_kind="research",
        target_kind="RECORDED_RESEARCH_SIGNAL_PLAN", scope="RECORDED_MAIN_RESEARCH", rows=[dict(ticker="ALPHA", target_weight=.2)])
    return workspace, state, current, leaf


def test_workspace_only_fills_unavailable_and_preserves_paper_date_without_mutating_state(monkeypatch):
    workspace, state, current, leaf = _workspace_fixture(monkeypatch, {SID: "UNAVAILABLE", "R7_GROSS_LINEAR": "BLOCKED"})
    before = deepcopy(state)
    monkeypatch.setattr(native, "rankings", lambda *a, **k: pytest.fail("injected test read publication"))
    result = workspace.load_active_rankings(DAY, package={}, account_state=state, research_rankings={"strategies": {SID: leaf}})
    assert result["strategies"][SID]["source_kind"] == "research"
    assert result["strategies"][SID]["paper_plan_signal_date"] == "2026-01-01"
    assert result["strategies"][SID]["current_target_status"] == "UNAVAILABLE"
    assert result["strategies"]["R7_GROSS_LINEAR"] == current["R7_GROSS_LINEAR"]
    assert result["strategies"]["R10_DIRECT_H5_RIDGE_MID"] == current["R10_DIRECT_H5_RIDGE_MID"]
    assert state == before


@pytest.mark.parametrize("failure", ("SYNTHETIC_HASH_CHANGED", "wrong-date"))
def test_workspace_research_failure_is_visible_and_local(monkeypatch, failure):
    workspace, state, current, leaf = _workspace_fixture(monkeypatch, {SID: "UNAVAILABLE"})
    if failure == "wrong-date": leaf["actual_signal_date"] = "2026-01-01"
    else: leaf.update(status="BLOCKED", rows=[], error=failure)
    result = workspace.load_active_rankings(DAY, package={}, account_state=state, research_rankings={"strategies": {SID: leaf}})
    assert result["strategies"][SID]["status"] == "BLOCKED" and result["strategies"][SID]["error"]
    assert result["strategies"]["RAW_A2"] == current["RAW_A2"]


def test_non_2026_workspace_and_already_current_leaves_never_query_research(monkeypatch):
    workspace, state, current, leaf = _workspace_fixture(monkeypatch, {SID: "UNAVAILABLE"})
    monkeypatch.setattr(native, "rankings", lambda *a, **k: pytest.fail("queried research outside fallback scope"))
    assert workspace.load_active_rankings("2025-01-02", package={}, account_state=state)["strategies"][SID]["status"] == "UNAVAILABLE"
    workspace, state, current, leaf = _workspace_fixture(monkeypatch, {})
    assert workspace.load_active_rankings(DAY, package={}, account_state=state)["strategies"][SID] == current[SID]


def test_display_hides_unknown_columns_without_filling_weights_or_generating_rank():
    rows = [dict(ticker="BETA", model_rank=None, raw_rank=None, score=None, action="HOLD", target_weight=None, selected=None, hold_units=2.)]
    display = applied_ranking_display({"source_kind": "research"}, rows)
    assert display[0]["hold_units"] == 2 and "target_weight" not in display[0]
    assert not {"model_rank", "score", "raw_input_rank", "raw_input_score", "native_action_score"} & set(display[0])
    assert rows[0]["target_weight"] is None
    stable = applied_ranking_rows([{"ticker": "BETA"}, {"ticker": "ALPHA"}], top_n=None)
    assert [r["ticker"] for r in stable] == ["ALPHA", "BETA"] and all("model_rank" not in r for r in stable)
    current = applied_ranking_display({"scope": "RECORDED_FROZEN_MODEL_INPUTS"}, [{"ticker": "A", "raw_rank": 1, "raw_score": .3, "source_score": None}])
    assert current[0]["raw_input_rank"] == 1 and "native_action_score" not in current[0]


def _research_app():
    import streamlit as st
    from apps.demo_console.components.top20_table import render_applied_rankings
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview
    with language_scope("en"):
        render_applied_rankings("2026-01-02", {}, DecisionOverview(), snapshot=st.session_state["synthetic_snapshot"])


@pytest.mark.parametrize("blocked", (False, True))
def test_ui_identifies_research_and_old_paper_or_specific_validation_failure(blocked):
    from streamlit.testing.v1 import AppTest
    leaf = dict(status="BLOCKED" if blocked else "AVAILABLE", source_kind="research", scope="RECORDED_MAIN_RESEARCH",
        target_kind="RECORDED_RESEARCH_SIGNAL_PLAN", actual_signal_date=DAY, weight_date=DAY,
        paper_plan_signal_date="2026-01-01", rows=[] if blocked else [dict(ticker="ALPHA", action="BUY", original_policy_weight=.25, target_weight=.2, selected=True)])
    if blocked: leaf["error"] = "SYNTHETIC_RESEARCH_HASH_CHANGED"
    app = AppTest.from_function(_research_app, default_timeout=30)
    app.session_state["synthetic_snapshot"] = {"strategies": {SID: leaf}}
    app.run()
    assert not app.exception
    from apps.demo_console.tests.test_localized_tabs import _open_expander
    _open_expander(app, "applied_rank_sources")
    captions = " ".join(item.value for item in app.caption)
    assert "Latest PAPER target signal: 2026-01-01" in captions and "not a current PAPER account target" in captions
    if blocked:
        assert any("Unavailable strategies" in item.value for item in app.warning)
        assert any("SYNTHETIC_RESEARCH_HASH_CHANGED" in item.value for item in app.code)
        assert not app.dataframe and not app.info
    else:
        assert "No stock ranking or model score" in captions
        assert app.dataframe[0].value["target_weight"].tolist() == [.2]
        assert "model_rank" not in app.dataframe[0].value.columns


def test_ui_current_blocked_is_explicit_without_claiming_no_ranking():
    from streamlit.testing.v1 import AppTest
    leaf = dict(status="BLOCKED", scope="RECORDED_FROZEN_MODEL_INPUTS", rows=[],
        target_kind="CURRENT_ACCOUNT_TARGET", actual_signal_date=None, weight_date=None)
    app = AppTest.from_function(_research_app, default_timeout=30)
    app.session_state["synthetic_snapshot"] = {"strategies": {SID: leaf}}
    app.run()
    assert not app.exception and not app.dataframe and not app.info
    assert any("Unavailable strategies" in item.value for item in app.warning)


@pytest.mark.parametrize("target_weight", (.2, 0., None))
def test_research_default_columns_keep_auxiliary_data_available(target_weight):
    from streamlit.testing.v1 import AppTest
    leaf = dict(status="AVAILABLE", source_kind="research", scope="RECORDED_MAIN_RESEARCH",
        target_kind="RECORDED_RESEARCH_SIGNAL_PLAN", actual_signal_date=DAY, weight_date=DAY,
        paper_plan_signal_date="2026-01-01", rows=[dict(ticker="ALPHA", action="HOLD",
            original_policy_weight=.25, target_weight=target_weight,
            hold_units=2., decision_semantic="MODEL_NO_DECISION", selected=True if target_weight is not None else None)])
    app = AppTest.from_function(_research_app, default_timeout=30)
    app.session_state["synthetic_snapshot"] = {"strategies": {SID: leaf}}
    app.run()
    assert not app.exception and len(app.dataframe) == 1
    table = app.dataframe[0]
    expected = ["strategy", "ticker", "recorded_action"]
    if target_weight is not None:
        expected.append("research_target_weight")
    expected.append("record_type")
    assert list(table.proto.column_order) == expected
    assert not {"model_rank", "score", "native_action_score", "raw_input_rank", "raw_input_score",
        "account_target_weight"} & set(table.proto.column_order)
    assert table.value["original_policy_weight"].tolist() == [.25]
    assert table.value["hold_units"].tolist() == [2.]
    assert table.value["decision_semantic"].tolist() == ["MODEL_NO_DECISION"]
    assert all(field in table.value.columns for field in ("original_policy_weight", "hold_units", "decision_semantic"))
    if target_weight is not None:
        assert table.value["target_weight"].tolist() == [target_weight]
        assert table.value["research_target_weight"].tolist() == [target_weight]
    else:
        assert "target_weight" not in table.value.columns
        assert leaf["rows"][0]["target_weight"] is None
