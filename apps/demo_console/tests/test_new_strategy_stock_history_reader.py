"""Fixed MAIN stock-history projection and isolation over synthetic artifacts."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.demo_console.adapters import new_strategy_stock_history_reader as reader

SID = "R7_GROSS_LINEAR"


def ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def sources(tmp_path):
    reader._cached.cache_clear()
    common = {"path_id": SID, "ticker": "ALPHA"}
    action = {**common, "signal_date": datetime(2026, 1, 2), "policy_explicit": True,
        "policy_weight": .25, "policy_action": "BUY_OR_ADD", "actual_weight": 0.,
        "planned_execution_date": datetime(2026, 1, 5)}
    order = {**common, "signal_date": datetime(2026, 1, 2), "execution_date": datetime(2026, 1, 5),
        "target_weight": .25, "adapted_target_weight": .2, "hold_units": 0.,
        "decision_semantic": "MODEL_TARGET_WEIGHT", "status": "submitted"}
    position = {**common, "date": datetime(2026, 1, 5), "weight": .21, "fractional_shares": 2.,
        "mark_date": datetime(2026, 1, 5), "stale": False, "unknown": False, "accounting_qualified": True}
    fill = {**common, "execution_date": datetime(2026, 1, 5), "signal_date": datetime(2026, 1, 2),
        "side": "BUY", "actual_fill_price": 101., "fractional_shares": 2.,
        "actual_fill_notional": 202., "transaction_fee": .2}
    references = {}
    for kind, row in (("actions", action), ("orders", order), ("positions", position), ("fills", fill)):
        clock = "date" if kind == "positions" else "execution_date" if kind == "fills" else "signal_date"
        forbidden = {**row, "path_id": "OTHER_CANDIDATE", "ticker": "ALPHA"}
        future = {**row, clock: datetime(2026, 10, 9)}
        outside = {**row, "ticker": "BETA"}
        path = tmp_path / (kind + ".parquet")
        pq.write_table(pa.Table.from_pylist([row, forbidden, future, outside]), path)
        references[kind] = ref(path)
    receipt = tmp_path / "receipt.json";receipt.write_text(json.dumps({"candidate_ids": [SID]}), encoding="utf-8")
    references["receipt"] = ref(receipt)
    yield {SID: references}
    reader._cached.cache_clear()


def test_exact_candidate_ticker_dates_and_columns_preserve_distinct_original_records(sources):
    result = reader.query("ALPHA", "2026-01-01", "2026-10-13", sources=sources)
    leaf = result["strategies"][SID]
    assert leaf["status"] == "READY"
    assert set(leaf["daily"]) == {"2026-01-02", "2026-01-05"}
    signal, executed = leaf["daily"]["2026-01-02"], leaf["daily"]["2026-01-05"]
    assert signal["native_action"] == "BUY_OR_ADD" and signal["target_weight"] == .2
    assert signal["research_orders"][0]["target_weight"] == .25
    assert executed["research_weight"] == .21 and executed["research_units"] == 2.
    assert executed["research_fills"][0]["actual_fill_price"] == 101.
    assert signal["model_rank"] is None and signal["score"] is None and signal["security_id"] is None
    assert signal["security_identity_status"] == "TICKER_ONLY_NO_RECORDED_CUSIP"
    assert "OTHER_CANDIDATE" not in str(result) and "BETA" not in str(result) and "2026-10-09" not in str(result)
    before = deepcopy(reader.query("ALPHA", "2026-01-01", "2026-10-13", sources=sources))
    result["strategies"][SID]["daily"].clear()
    assert reader.query("ALPHA", "2026-01-01", "2026-10-13", sources=sources) == before
    assert reader._cached.cache_info().maxsize == 1


def test_hash_failure_is_local_and_never_relabels_as_empty_history(sources):
    payload = deepcopy(sources)
    payload[SID]["positions"]["sha256"] = "ab" * 32
    leaf = reader.query("ALPHA", "2026-01-02", "2026-10-08", sources=payload)["strategies"][SID]
    assert leaf["status"] == "UNAVAILABLE" and leaf["daily"] == {}
    assert "CHANGED" in leaf["error"]


def test_future_or_other_candidate_requests_never_scan(sources, monkeypatch):
    monkeypatch.setattr(reader, "_project", lambda *args: pytest.fail("out-of-scope query scanned source"))
    assert reader.query("ALPHA", "2026-10-09", "2026-10-13", sources=sources)["strategies"] == {}
    with pytest.raises(ValueError, match="CANDIDATE_SCOPE"):
        reader.query("ALPHA", "2026-01-02", "2026-10-08", sources={"OTHER": sources[SID]})


def test_native_history_joins_original_dates_without_assigning_raw_cusip_or_rank(sources, monkeypatch):
    from apps.demo_console.adapters import workspace_reader as workspace
    from apps.demo_console.components.stock_history_search import applied_stock_records, applied_stock_chart
    from apps.demo_console.tests.test_stock_history_search import fixture_applied_query, fixture_applied_history
    history = {**fixture_applied_history(), "as_of": "2026-01-07", "start_date": "2026-01-02",
        "_active_account_state": {}, "_native_stock_sources": sources}
    monkeypatch.setattr(workspace, "query_applied_stock_history", fixture_applied_query)
    result = workspace.query_active_stock_history(history, "ALPHA", "2026-01-02", "2026-01-07")
    assert result["status"] == "READY" and result["daily"][0]["date"] == "2026-01-02"
    native = [row for row in applied_stock_records(result["daily"]) if row["strategy_id"] == SID]
    assert all(row["security_id"] is None for row in native if row.get("security_identity_status"))
    assert all(row["rank"] is None for row in native)
    assert next(row for row in native if row["date"] == "2026-01-05")["research_weight"] == .21
    spec = applied_stock_chart(applied_stock_records(result["daily"]), "research_weight").to_dict(validate=True)
    assert spec["encoding"]["color"]["scale"]["domain"] == ["R7 LINEAR"]
    assert spec["encoding"]["detail"]["field"] == "research_weight_segment"


def _native_stock_page():
    import streamlit as st
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.components.stock_history_search import render_applied_stock_history
    from apps.demo_console.i18n import language_scope
    st.session_state["decision_date"] = "2026-01-07"
    with language_scope("en"):
        render_applied_stock_history(DecisionOverview(), {}, "2026-01-07")


def test_stock_history_ui_renders_original_actions_and_separate_research_holding_chart(sources, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.adapters import workspace_reader as workspace
    from apps.demo_console.tests.test_stock_history_search import fixture_applied_query, fixture_applied_history
    history = {**fixture_applied_history(), "as_of": "2026-01-07", "start_date": "2026-01-02",
        "_active_account_state": {}, "_native_stock_sources": sources}
    monkeypatch.setattr(workspace, "load_applied_stock_history", lambda **kwargs: history)
    monkeypatch.setattr(workspace, "load_applied_stock_catalog", lambda **kwargs: history)
    monkeypatch.setattr(workspace, "query_applied_stock_history", fixture_applied_query)
    app = AppTest.from_function(_native_stock_page, default_timeout=30)
    app.session_state["applied_stock_ticker"] = "ALPHA"
    app.session_state["applied_stock_native_records"] = True
    app.run()
    assert not app.exception and not app.error
    assert any(item.label == "Original MAIN stock actions, holdings and research fills" for item in app.expander)
    table = next(item.value for item in app.dataframe if "research_units" in item.value.columns)
    assert table["strategy"].unique().tolist() == ["R7 LINEAR"]
    assert table["native_action"].dropna().tolist() == ["BUY_OR_ADD"]
    assert any(item.value == "**Recorded research holding history**" for item in app.markdown)
    assert app.session_state["decision_date"] == "2026-01-07"


def test_presentation_metadata_loader_never_imports_research_math(sources, monkeypatch):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.startswith("scripts.research") or name in {"joblib", "torch", "sklearn"}:
            raise AssertionError("Presentation reader attempted a research/math dependency: " + name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    assert reader.query("ALPHA", "2026-01-02", "2026-10-08", sources=sources)["strategies"][SID]["status"] == "READY"


def test_cached_native_projection_rechecks_frozen_file_identity(sources):
    assert reader.query("ALPHA", "2026-01-02", "2026-10-08", sources=sources)["strategies"][SID]["status"] == "READY"
    from pathlib import Path
    Path(sources[SID]["receipt"]["path"]).write_text('{"candidate_ids":[]}', encoding="utf8")
    leaf = reader.query("ALPHA", "2026-01-02", "2026-10-08", sources=sources)["strategies"][SID]
    assert leaf["status"] == "UNAVAILABLE" and leaf["daily"] == {}
    assert "CHANGED" in leaf["error"]


@pytest.mark.parametrize("sid", ["R6_BUY_NEURAL", "R6_DURATION_TREE", "RAW_s10"])
def test_catalog_native_queries_reuse_exact_rows_and_keep_rank_unknown(sources, tmp_path, monkeypatch, sid):
    from apps.demo_console.adapters import new_strategy_replay_reader as replay
    references = deepcopy(sources[SID])
    for kind in reader._COLUMNS:
        path = Path(references[kind]["path"])
        rows = pq.read_table(path).to_pylist()
        for row in rows:
            if row["path_id"] == SID: row["path_id"] = sid
        pq.write_table(pa.Table.from_pylist(rows), path)
        references[kind] = ref(path)
    receipt = Path(references["receipt"]["path"])
    receipt.write_text(json.dumps({"candidate_ids": [sid]}))
    references["receipt"] = ref(receipt)
    if sid == "RAW_s10":
        scope = tmp_path / "scope.json"
        scope.write_text(json.dumps({"schema": "ALL_A_CONSENSUS100_FROZEN_RAW_SELECTOR_APPLICATION_SCOPE_R2",
            "task_id": "A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1",
            "application_pool_origin": "CONSENSUS_TOP100_FULL_PIT32_APPLICATION_POOL",
            "new_model_or_fit": False, "pre2026_training_identity_unchanged": True}))
        monkeypatch.setattr(replay, "_RAW_SELECTOR_REF", ref(scope))
        references.update(universe_variant="CONSENSUS100", pool_variant_id="TOP100", selector_scope=ref(scope))
    result = reader.query("ALPHA", "2026-01-02", "2026-01-05", sources={sid: references}, strategy_ids=(sid,))
    assert tuple(result["strategies"]) == (sid,)
    assert result["strategies"][sid]["status"] == "READY"
    assert result["strategies"][sid]["daily"]["2026-01-05"]["research_weight"] == .21
    rankings = reader.rankings("2026-01-02", sources={sid: references}, strategy_ids=(sid,))
    assert rankings["strategies"][sid]["status"] == "AVAILABLE"
    row = rankings["strategies"][sid]["rows"][0]
    assert row["score"] is row["model_rank"] is row["raw_rank"] is None
    assert row["action"] == "BUY_OR_ADD" and row["target_weight"] == .2
    assert reader.query("ALPHA", "2026-10-09", "2026-10-15", sources={sid: references})["strategies"] == {}
    if sid == "RAW_s10":
        references["pool_variant_id"] = "OTHER_POOL"
        result = reader.query("ALPHA", "2026-01-02", "2026-01-05", sources={sid: references})
        assert result["strategies"][sid]["status"] == "UNAVAILABLE"


def test_catalog_source_refs_remain_frozen_and_do_not_read_original_extension(monkeypatch):
    monkeypatch.setattr(reader, "qualified_sources", lambda: pytest.fail("extra query must not read v1 extension"))
    refs = reader.source_refs(strategy_ids=("R6_BUY_NEURAL", "R6_DURATION_TREE", "RAW_s10"))
    assert set(refs) == {"R6_BUY_NEURAL", "R6_DURATION_TREE", "RAW_s10"}
    assert refs["R6_BUY_NEURAL"]["actions"] == refs["R6_DURATION_TREE"]["actions"]
    assert refs["R6_BUY_NEURAL"]["actions"]["sha256"] == reader._HASHES["R10_DIRECT_H5_RIDGE_MID"]["actions"]
    assert refs["RAW_s10"]["actions"]["sha256"] == "121e062777bad8ee76ed6ceeed43c299bce3d138d0b12056dd3c51cd73b2cf71"
    assert refs["RAW_s10"]["universe_variant"] == "CONSENSUS100"
    assert len(reader._HASHES) == 3


def test_older_partial_capture_keeps_known_paths_and_marks_missing_catalog_records(sources):
    ids = (SID, "R6_DURATION_TREE")
    result = reader.query("ALPHA", "2026-01-02", "2026-01-05", sources=sources, strategy_ids=ids)
    assert result["strategies"][SID]["status"] == "READY"
    assert result["strategies"]["R6_DURATION_TREE"]["status"] == "UNAVAILABLE"
    assert result["strategies"]["R6_DURATION_TREE"]["daily"] == {}
    result = reader.rankings("2026-01-02", sources=sources, strategy_ids=ids)
    assert result["strategies"][SID]["status"] == "AVAILABLE"
    assert result["strategies"]["R6_DURATION_TREE"]["status"] == "BLOCKED"
    assert result["strategies"]["R6_DURATION_TREE"]["rows"] == []
