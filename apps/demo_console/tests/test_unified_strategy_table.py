"""Unified display contracts over synthetic records; no model, history or API read."""
from collections import Counter
from copy import deepcopy
import json
import sys
from types import ModuleType

import pytest

from apps.demo_console.components.top20_table import (
    applied_comparison_rows, applied_comparison_columns, _focus_applied_ranking,
)
from apps.moomoo_trading_component.moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS as IDS

DAY = "2025-11-03"
DEFAULT_COLUMNS = ["strategy", "ticker", "model_rank", "score", "recorded_action",
    "research_target_weight", "account_target_weight", "record_type"]


def snapshot(count=12):
    result = {"strategies": {}}
    for index, sid in enumerate(IDS):
        research = index >= 2
        rows = [dict(ticker=f"SYN_{number:02}", security_id=f"SEC_{number:02}",
            company="SYNTHETIC_NEEDLE" if number == count - 1 else "Synthetic company",
            action="BUY" if number % 2 == 0 else "HOLD", target_weight=number / 100,
            model_rank=None if research else number + 1, score=None if research else (1000 - index * 2000 + number),
            selected=None if number == 0 else True, original_policy_weight=.5 if research else None,
            hold_units=2. if research else None) for number in range(count)]
        result["strategies"][sid] = dict(status="AVAILABLE", actual_signal_date=DAY, weight_date=DAY,
            source_kind="research" if research else "account", scope="RECORDED_MAIN_RESEARCH" if research else "RAW_TOP40",
            target_kind="RECORDED_RESEARCH_SIGNAL_PLAN" if research else "CURRENT_ACCOUNT_TARGET", rows=rows,
            current_target_status="UNAVAILABLE" if research else "AVAILABLE",
            paper_plan_signal_date="2025-10-31" if research else DAY,
            source_refs={"synthetic": {"path": "/not_opened", "sha256": "ab" * 32}})
    return result


def test_five_sources_each_get_their_limit_and_search_happens_before_limit():
    source = snapshot()
    before = deepcopy(source)
    rows, identities = applied_comparison_rows(source, day=DAY)
    assert len(rows) == len(identities) == 50
    assert Counter(row["strategy_id"] for row in rows) == dict.fromkeys(IDS, 10)
    assert [row["strategy_id"] for row in rows[:5]] == list(IDS)
    matches, _ = applied_comparison_rows(source, day=DAY, query="needle", top_n=1)
    assert len(matches) == 5 and {row["ticker"] for row in matches} == {"SYN_11"}
    selected, _ = applied_comparison_rows(source, day=DAY, selected_only=True, top_n=1)
    assert len(selected) == 5 and {row["ticker"] for row in selected} == {"SYN_01"}
    assert source == before


def test_weights_sources_and_unknown_ranks_remain_distinct():
    source = snapshot(2)
    rows, _ = applied_comparison_rows(source, day=DAY, top_n=None)
    for row in rows:
        if row["strategy_id"] in IDS[:2]:
            assert row["research_target_weight"] is None and row["account_target_weight"] == row["target_weight"]
        else:
            assert row["account_target_weight"] is None and row["research_target_weight"] == row["target_weight"]
            assert row.get("model_rank") is None and row.get("score") is None
            assert row["original_policy_weight"] == .5 and row["hold_units"] == 2.
        assert not (row["research_target_weight"] is not None and row["account_target_weight"] is not None)
    source["strategies"][IDS[0]]["target_kind"] = "RECORDED_EXECUTED_BOOK"
    book, _ = applied_comparison_rows(source, day=DAY, strategy_ids=(IDS[0],), top_n=None)
    assert all(row["research_target_weight"] is None and row["account_target_weight"] is None for row in book)
    assert book[1]["target_weight"] == .01


@pytest.mark.parametrize(("rank", "score", "label", "fields"), [
    (2, 0., "Recorded score · target unverified", ["model_rank", "score"]),
    (2, None, "Recorded rank · target unverified", ["model_rank"]),
    (None, None, "Unavailable", []),
    (None, float("inf"), "Unavailable", []),
])
@pytest.mark.parametrize("kind", (None, "UNAVAILABLE"))
def test_score_only_records_keep_unknown_targets_and_original_identity(rank, score, label, fields, kind):
    import hashlib
    from apps.demo_console.i18n import language_scope, tr

    source = snapshot(1)
    leaf = source["strategies"][IDS[0]]
    leaf.update(target_kind=kind, weight_date=None, current_target_status="UNAVAILABLE")
    leaf["rows"][0].update(model_rank=rank, score=score, target_weight=None, selected=None, action=None)
    before = deepcopy(source)
    original = leaf["rows"][0]
    evidence = {key: leaf.get(key) for key in ("source_kind", "scope", "target_kind",
        "actual_signal_date", "weight_date", "source_refs", "target_source_refs", "source_hashes")}
    fingerprint = hashlib.sha256(json.dumps([evidence, original], sort_keys=True,
        default=str, ensure_ascii=True).encode()).hexdigest()
    identity = (DAY, IDS[0], original["security_id"], original["ticker"], leaf["source_kind"],
        leaf["scope"], kind, DAY, None, fingerprint)
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            rows, identities = applied_comparison_rows(source, day=DAY, strategy_ids=(IDS[0],))
            assert rows[0]["record_type"] == tr(label)
            if language != "en" and label != "Unavailable":
                assert rows[0]["record_type"] != label
        assert identities == (identity,)
        assert rows[0].get("record_type_code") == kind
        assert rows[0]["research_target_weight"] is None and rows[0]["account_target_weight"] is None
        assert rows[0].get("target_weight") is None
        assert applied_comparison_columns(rows) == ["strategy", "ticker", *fields, "record_type"]
        assert rows[0].get("model_rank") == rank
        if "score" in fields:
            assert rows[0]["score"] == score
        else:
            assert rows[0].get("score") is None
    assert source == before


@pytest.mark.parametrize(("raw_score", "native_score", "label", "fields"), [
    (.25, -.5, "Recorded score · target unverified",
        ["native_action_score", "raw_input_rank", "raw_input_score"]),
    (None, None, "Recorded rank · target unverified", ["raw_input_rank"]),
])
def test_frozen_inputs_keep_raw_and_native_fields_separate_from_model_scores(raw_score, native_score, label, fields):
    from apps.demo_console.i18n import language_scope, tr

    source = snapshot(1)
    leaf = source["strategies"][IDS[0]]
    leaf.update(scope="RECORDED_FROZEN_MODEL_INPUTS", target_kind="UNAVAILABLE", weight_date=None)
    leaf["rows"][0].update(raw_rank=4, raw_score=raw_score, source_score=native_score,
        model_rank=99, score=.75, target_weight=None, selected=None, action=None)
    before = deepcopy(source)
    with language_scope("en"):
        rows, _ = applied_comparison_rows(source, day=DAY, strategy_ids=(IDS[0],))
        assert rows[0]["record_type"] == tr(label)
    row = rows[0]
    assert row["raw_input_rank"] == 4
    assert row.get("raw_input_score") == raw_score and row.get("native_action_score") == native_score
    assert "model_rank" not in row and "score" not in row
    assert applied_comparison_columns(rows) == ["strategy", "ticker", *fields, "record_type"]
    assert row["record_type_code"] == "UNAVAILABLE" and row.get("target_weight") is None
    assert source == before


def test_ui_score_records_show_rank_and_score_without_unknown_weights(ui):
    from apps.demo_console.i18n import language_scope, tr

    source = snapshot(1)
    source["strategies"] = {IDS[0]: source["strategies"][IDS[0]]}
    leaf = source["strategies"][IDS[0]]
    leaf.update(target_kind="UNAVAILABLE", weight_date=None, current_target_status="UNAVAILABLE")
    leaf["rows"][0].update(score=0., target_weight=None, selected=None, action=None)
    ui.session_state["synthetic_snapshot"] = source
    ui.run()
    assert not ui.exception and len(ui.dataframe) == 1
    table = ui.dataframe[0]
    assert list(table.proto.column_order) == ["strategy", "ticker", "model_rank", "score", "record_type"]
    assert table.value["model_rank"].tolist() == [1] and table.value["score"].tolist() == [0.]
    assert table.value["record_type_code"].tolist() == ["UNAVAILABLE"]
    assert any("Current PAPER targets unavailable" in item.value for item in ui.warning)
    leaf.update(target_kind="CURRENT_ACCOUNT_TARGET", weight_date=DAY, current_target_status="AVAILABLE")
    leaf["rows"][0].update(target_weight=0., selected=True)
    ui.session_state["synthetic_snapshot"] = source
    ui.run()
    assert not ui.exception
    table = ui.dataframe[0]
    assert list(table.proto.column_order) == ["strategy", "ticker", "model_rank", "score",
        "account_target_weight", "record_type"]
    assert table.value["account_target_weight"].tolist() == [0.]
    with language_scope("en"):
        assert table.value["record_type"].tolist() == [tr("Current account target")]


def test_weight_sort_stays_inside_strategy_and_blocked_records_never_enter_table():
    source = snapshot(3)
    source["strategies"][IDS[1]]["status"] = "BLOCKED"
    rows, _ = applied_comparison_rows(source, day=DAY, order="Portfolio weight", top_n=None)
    assert [row["strategy_id"] for row in rows[:4]] == [IDS[0], *IDS[2:]]
    assert [row["target_weight"] for row in rows if row["strategy_id"] == IDS[0]] == [.02, .01, 0.]
    assert all(row["strategy_id"] != IDS[1] for row in rows)


def test_row_identity_binds_security_source_role_and_dates_without_opening_refs():
    source = snapshot(1)
    _, first = applied_comparison_rows(source, day=DAY)
    assert len(set(first)) == 5  # Same ticker, distinct strategy records.
    for field, value in (("weight_date", "2025-10-31"), ("source_kind", "OTHER_ROLE"),
            ("source_refs", {"synthetic": {"path": "/not_opened", "sha256": "cd" * 32}})):
        changed = deepcopy(source)
        changed["strategies"][IDS[0]][field] = value
        assert applied_comparison_rows(changed, day=DAY)[1][0] != first[0]
    source["strategies"][IDS[0]]["rows"][0]["security_id"] = "OTHER_SECURITY"
    assert applied_comparison_rows(source, day=DAY)[1][0] != first[0]


@pytest.mark.parametrize("failure", ("old_key", "old_date", "unknown_date", "wrong_security", "wrong_source", "wrong_signal", "duplicate", "unknown_sid", "bad_index"))
def test_old_or_mismatched_selection_cannot_change_focus(monkeypatch, failure):
    import streamlit as st
    source = snapshot(1)
    _, identities = applied_comparison_rows(source, day=DAY)
    state = {"decision_date": DAY, "_applied_ranking_date": DAY, "_applied_ranking_keys": ("current",),
        "_applied_ranking_row_ids": identities, "workspace_strategy": IDS[0], "applied_stock_ticker": "KEEP",
        "current": {"selection": {"rows": [3]}}}
    tickers = tuple(identity[3] for identity in identities)
    sent = identities
    key = "current"
    if failure == "old_key": key = "old"
    if failure == "old_date": state["decision_date"] = "2025-10-31"
    if failure == "unknown_date": state["decision_date"] = None
    if failure in ("wrong_security", "wrong_source", "wrong_signal", "unknown_sid"):
        index = {"wrong_security": 2, "wrong_source": 4, "wrong_signal": 7, "unknown_sid": 1}[failure]
        changed = list(identities); row = list(changed[3]); row[index] = "MISMATCH"; changed[3] = tuple(row); sent = tuple(changed)
        if failure == "unknown_sid": state["_applied_ranking_row_ids"] = sent
    if failure == "duplicate":
        sent = (identities[3], identities[3]); tickers = ("SYN_00", "SYN_00")
        state["_applied_ranking_row_ids"] = sent; state["current"]["selection"]["rows"] = [0]
    if failure == "bad_index": state["current"]["selection"]["rows"] = [True]
    calls = []; fake = ModuleType("apps.demo_console.app"); fake._change_strategy = lambda: calls.append("change")
    monkeypatch.setitem(sys.modules, "apps.demo_console.app", fake)
    monkeypatch.setattr(st, "session_state", state)
    _focus_applied_ranking(key, tickers, sent)
    assert state["workspace_strategy"] == IDS[0] and state["applied_stock_ticker"] == "KEEP" and not calls


def test_valid_selection_calls_original_strategy_change_then_retains_source_identity(monkeypatch):
    import streamlit as st
    from apps.demo_console import app
    source = snapshot(1); _, identities = applied_comparison_rows(source, day=DAY)
    state = {"decision_date": DAY, "_applied_ranking_date": DAY, "_applied_ranking_keys": ("current",),
        "_applied_ranking_row_ids": identities, "workspace_strategy": IDS[0], "applied_stock_ticker": "KEEP",
        "_rendered_workspace": "OLD_MODEL", "_research_case_ticker": "OLD_SECURITY", "_history_replay": "old",
        "current": {"selection": {"rows": [3]}}}
    calls = []; original = app._change_strategy
    def change():
        calls.append(state["workspace_strategy"])
        original()
    monkeypatch.setattr(app, "_change_strategy", change); monkeypatch.setattr(st, "session_state", state)
    _focus_applied_ranking("current", tuple(identity[3] for identity in identities), identities)
    assert calls == [IDS[3]] and state["workspace_strategy"] == IDS[3]
    assert state["applied_stock_ticker"] == "SYN_00" and state["_applied_comparison_focus"] == identities[3]
    assert all(key not in state for key in ("_rendered_workspace", "_research_case_ticker", "_history_replay"))
    assert state["decision_date"] == DAY


def _comparison_app():
    import streamlit as st
    from apps.demo_console.components.top20_table import render_applied_rankings
    from apps.demo_console.i18n import language_scope
    st.session_state.setdefault("decision_date", "2025-11-03")
    st.session_state.setdefault("workspace_strategy", "RAW_A2")
    with language_scope(st.session_state.get("synthetic_language", "en")):
        render_applied_rankings(st.session_state["decision_date"], {}, None, snapshot=st.session_state["synthetic_snapshot"])


@pytest.fixture
def ui(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.adapters import workspace_reader
    monkeypatch.setattr(workspace_reader, "load_applied_rankings", lambda *a, **k: pytest.fail("supplied snapshot reread"))
    monkeypatch.setattr(workspace_reader, "load_active_stock_history", lambda *a, **k: pytest.fail("unopened full stock history read"))
    app = AppTest.from_function(_comparison_app, default_timeout=30)
    app.session_state["synthetic_snapshot"] = snapshot()
    app.run()
    assert not app.exception
    return app


def test_ui_one_virtualized_frame_default_all_five_and_optional_raw_fields(ui):
    assert len(ui.dataframe) == 1
    table = ui.dataframe[0]
    assert len(table.value) == 50 and set(table.value.strategy_id) == set(IDS)
    assert list(table.proto.column_order) == DEFAULT_COLUMNS
    assert ui.multiselect(key="applied_rank_strategies").value == list(IDS)
    assert not ui.json and not ui.code  # Both optional detail panels are closed.
    assert list(table.value.strategy_id[:5]) == list(IDS)
    assert list(table.value[table.value.strategy_id == IDS[0]].native_action_code[:2]) == ["BUY", "HOLD"]
    import hashlib
    identities = ui.session_state["_applied_ranking_row_ids"]
    old_grouped = tuple(identity for sid in IDS for identity in identities if identity[1] == sid)
    old_digest = hashlib.sha256(json.dumps([DAY, list(IDS), "", "Score ranking", 10, False,
        old_grouped], ensure_ascii=True).encode()).hexdigest()[:14]
    assert ui.session_state["_applied_ranking_keys"] != ("applied_rank_table_" + old_digest,)


def test_ui_filters_keep_per_strategy_counts_and_selected_sources(ui):
    ui.selectbox(key="applied_rank_count").select(20).run()
    assert len(ui.dataframe[0].value) == 60
    ui.selectbox(key="applied_rank_count").select(40).run()
    assert len(ui.dataframe[0].value) == 60
    ui.selectbox(key="applied_rank_count").select("All").run()
    assert len(ui.dataframe[0].value) == 60
    ui.text_input(key="applied_rank_query").set_value("needle").run()
    assert len(ui.dataframe[0].value) == 5
    ui.multiselect(key="applied_rank_strategies").set_value([IDS[1], IDS[3]]).run()
    assert set(ui.dataframe[0].value.strategy_id) == {IDS[1], IDS[3]}
    assert len(ui.dataframe[0].value) == 2
    assert not ui.exception


def test_ui_actions_translate_and_codes_dates_economics_remain_raw(ui):
    from apps.demo_console.i18n import language_scope, tr
    for language in ("en", "zh", "ja"):
        ui.session_state["synthetic_language"] = language; ui.run()
        assert not ui.exception
        frame = ui.dataframe[0].value
        with language_scope(language):
            first_source = frame[frame.strategy_id == IDS[0]]
            assert first_source.recorded_action.iloc[0] == tr("Buy") and first_source.recorded_action.iloc[1] == tr("Hold")
            assert ui.selectbox(key="applied_rank_count").proto.raw_value == tr("{count} rows per strategy", count=10)
        assert frame.native_action_code.iloc[0] == "BUY" and frame.signal_date.iloc[0] == DAY
        assert frame[frame.strategy_id == IDS[0]].account_target_weight.iloc[1] == .01
        assert ui.multiselect(key="applied_rank_strategies").value == list(IDS)


def test_blocked_and_missing_current_targets_stay_visible_outside_detail_panel(ui):
    source = snapshot(); source["strategies"][IDS[1]].update(status="BLOCKED", error="SYNTHETIC_HASH_CHANGED")
    ui.session_state["synthetic_snapshot"] = source; ui.run()
    assert not ui.exception and len(ui.dataframe) == 1
    assert IDS[1] not in set(ui.dataframe[0].value.strategy_id)
    assert any("Unavailable strategies" in item.value for item in ui.warning)
    assert any("Current PAPER targets unavailable" in item.value for item in ui.warning)
    assert not ui.code
    from apps.demo_console.tests.test_localized_tabs import _open_expander
    _open_expander(ui, "applied_rank_sources")
    assert any("SYNTHETIC_HASH_CHANGED" in item.value for item in ui.code)
    assert any("not a current PAPER account target" in item.value for item in ui.caption)


def test_current_owner_without_target_status_still_reports_missing_account_plan(ui):
    source = snapshot()
    source["strategies"][IDS[3]] = dict(status="UNAVAILABLE", target_kind="UNAVAILABLE", rows=[])
    ui.session_state["synthetic_snapshot"] = source
    ui.run()
    assert not ui.exception and len(ui.dataframe) == 1
    assert IDS[3] not in set(ui.dataframe[0].value.strategy_id)
    from apps.demo_console.pages.selected_strategies import strategy_label
    assert any(strategy_label(IDS[3]) in item.value and "Current PAPER targets unavailable" in item.value for item in ui.warning)


def test_ui_existing_presentation_mode_controls_row_density_without_changing_records(ui):
    before = ui.dataframe[0].value.copy(deep=True)
    assert ui.dataframe[0].proto.row_height == 44
    ui.session_state["presentation_mode"] = False
    ui.run()
    assert not ui.exception and ui.dataframe[0].proto.row_height == 36
    assert ui.dataframe[0].value.equals(before)
    ui.session_state["presentation_mode"] = True
    ui.run()
    assert not ui.exception and ui.dataframe[0].proto.row_height == 44
    assert ui.dataframe[0].value.equals(before)


def test_presentation_settings_are_one_popover_and_research_shows_original_controls(ui):
    popovers = ui.get("popover")
    assert len(popovers) == 1 and popovers[0].key == "applied_rank_controls"
    assert len(popovers[0].multiselect) == 1 and len(popovers[0].selectbox) == 2
    assert len(popovers[0].text_input) == 1 and len(popovers[0].toggle) == 1
    assert not popovers[0].dataframe and not popovers[0].warning
    assert not any("Daily rankings and allocations" in item.value for item in ui.markdown)
    ui.session_state["presentation_mode"] = False
    ui.run()
    assert not ui.exception and not ui.get("popover")
    assert len(ui.multiselect) == 1 and len(ui.selectbox) == 2
    assert len(ui.dataframe) == 1 and ui.dataframe[0].proto.row_height == 36


def test_mode_and_language_roundtrip_keep_all_canonical_filters_and_row_identity(ui):
    from apps.demo_console.i18n import language_scope, tr
    ui.multiselect(key="applied_rank_strategies").set_value([IDS[1], IDS[3]]).run()
    ui.selectbox(key="applied_rank_count").select("All").run()
    ui.selectbox(key="applied_rank_order").select("Portfolio weight").run()
    ui.text_input(key="applied_rank_query").set_value("SYN_0").run()
    ui.toggle(key="applied_rank_selected").set_value(True).run()
    identities = ui.session_state["_applied_ranking_row_ids"]
    table_keys = ui.session_state["_applied_ranking_keys"]
    expected = ui.dataframe[0].value.copy(deep=True)
    for language, presentation in (("zh", False), ("ja", True), ("en", False), ("en", True)):
        ui.session_state["synthetic_language"] = language
        ui.session_state["presentation_mode"] = presentation
        ui.run()
        assert not ui.exception
        assert ui.multiselect(key="applied_rank_strategies").value == [IDS[1], IDS[3]]
        assert ui.selectbox(key="applied_rank_count").value == "All"
        assert ui.selectbox(key="applied_rank_order").value == "Portfolio weight"
        assert ui.text_input(key="applied_rank_query").value == "SYN_0"
        assert ui.toggle(key="applied_rank_selected").value is True
        assert ui.session_state["_applied_ranking_row_ids"] == identities
        assert ui.session_state["_applied_ranking_keys"] == table_keys
        assert ui.dataframe[0].value[["strategy_id", "security_id", "target_weight"]].equals(
            expected[["strategy_id", "security_id", "target_weight"]])
        assert ui.dataframe[0].proto.row_height == (44 if presentation else 36)
        if presentation:
            with language_scope(language):
                assert ui.get("popover")[0].proto.popover.label == tr("Comparison settings")


def test_uniform_current_record_date_moves_to_sources_but_date_gaps_stay_visible(ui):
    from apps.demo_console.tests.test_localized_tabs import _open_expander
    assert not any(item.value.startswith("Record dates:") for item in ui.caption)
    _open_expander(ui, "applied_rank_sources")
    assert any(item.value == f"Record dates: {DAY}." for item in ui.caption)
    source = snapshot()
    source["strategies"][IDS[0]]["weight_date"] = "2025-10-31"
    ui.session_state["synthetic_snapshot"] = source
    ui.run()
    main_dates = [item for item in ui.caption if item.value.startswith("Record dates:")]
    assert len(main_dates) == 2 and "2025-10-31" in main_dates[0].value
    assert any("Current PAPER targets unavailable" in item.value for item in ui.warning)
    assert len(ui.get("popover")) == 1 and not ui.get("popover")[0].warning


def test_round_robin_preserves_every_source_sequence_and_row_identity():
    source = snapshot(4)
    rows, identities = applied_comparison_rows(source, day=DAY, order="Portfolio weight", top_n=3)
    assert [row["strategy_id"] for row in rows[:5]] == list(IDS)
    for sid in IDS:
        separate_rows, separate_ids = applied_comparison_rows(source, day=DAY, strategy_ids=(sid,),
            order="Portfolio weight", top_n=3)
        actual = [row for row in rows if row["strategy_id"] == sid]
        normalize = lambda sequence: [{key: value for key, value in row.items() if value is not None} for row in sequence]
        assert normalize(actual) == normalize(separate_rows)
        assert tuple(identity for identity in identities if identity[1] == sid) == separate_ids
        assert [row["target_weight"] for row in actual] == [.03, .02, .01]
    for row, identity in zip(rows, identities):
        assert (row["strategy_id"], row["security_id"], row["ticker"]) == identity[1:4]


def test_empty_source_is_skipped_without_reordering_other_records_or_identities():
    source = snapshot(3)
    before_rows, before_ids = applied_comparison_rows(source, day=DAY)
    source["strategies"][IDS[2]]["rows"] = []
    rows, identities = applied_comparison_rows(source, day=DAY)
    normalize = lambda sequence: [{key: value for key, value in row.items() if value is not None} for row in sequence]
    assert normalize(rows) == normalize([row for row in before_rows if row["strategy_id"] != IDS[2]])
    assert identities == tuple(identity for identity in before_ids if identity[1] != IDS[2])
    assert [row["strategy_id"] for row in rows[:4]] == [IDS[0], IDS[1], IDS[3], IDS[4]]


def test_interleaved_selection_uses_the_displayed_record_and_rejects_old_group_key(monkeypatch):
    import streamlit as st
    source = snapshot(3)
    rows, identities = applied_comparison_rows(source, day=DAY)
    assert rows[8]["strategy_id"] == IDS[3] and rows[8]["ticker"] == "SYN_01"
    state = {"decision_date": DAY, "_applied_ranking_date": DAY, "_applied_ranking_keys": ("interleaved",),
        "_applied_ranking_row_ids": identities, "workspace_strategy": IDS[0], "applied_stock_ticker": "KEEP",
        "interleaved": {"selection": {"rows": [8]}}, "old-grouped": {"selection": {"rows": [8]}}}
    calls = []
    fake = ModuleType("apps.demo_console.app")
    fake._change_strategy = lambda: calls.append(state["workspace_strategy"])
    monkeypatch.setitem(sys.modules, "apps.demo_console.app", fake)
    monkeypatch.setattr(st, "session_state", state)
    tickers = tuple(row["ticker"] for row in rows)
    _focus_applied_ranking("old-grouped", tickers, identities)
    assert not calls and state["applied_stock_ticker"] == "KEEP"
    _focus_applied_ranking("interleaved", tickers, identities)
    assert calls == [IDS[3]] and state["workspace_strategy"] == IDS[3]
    assert state["applied_stock_ticker"] == "SYN_01" and state["_applied_comparison_focus"] == identities[8]


@pytest.mark.parametrize(("language", "label"), (("en", "Target allocation"), ("zh", "目标仓位"), ("ja", "目標配分")))
def test_target_action_uses_allocation_translation_without_rewriting_native_code(language, label):
    from apps.demo_console.components.top20_table import _applied_action_label
    from apps.demo_console.i18n import language_scope
    source = snapshot(1)
    source["strategies"][IDS[4]]["rows"][0]["action"] = "TARGET"
    with language_scope(language):
        assert _applied_action_label("TARGET") == label
        assert _applied_action_label("UNRECOGNIZED_ACTION") == "UNRECOGNIZED_ACTION"
        assert _applied_action_label(None) is None
        rows, _ = applied_comparison_rows(source, day=DAY, strategy_ids=(IDS[4],))
    assert rows[0]["recorded_action"] == label and rows[0]["native_action_code"] == "TARGET"
    assert rows[0]["target_weight"] == 0.0


@pytest.mark.parametrize(("presentation", "count", "height"), ((True, 5, 260), (True, 50, 420), (False, 5, 220), (False, 50, 420)))
def test_native_dataframe_height_fits_five_rows_and_caps_fifty_in_both_modes(ui, monkeypatch, presentation, count, height):
    import streamlit as st
    original = st.dataframe
    calls = []
    def capture(data, *args, **kwargs):
        calls.append((len(data), kwargs.get("height"), kwargs.get("row_height")))
        return original(data, *args, **kwargs)
    monkeypatch.setattr(st, "dataframe", capture)
    ui.session_state["presentation_mode"] = presentation
    ui.session_state["applied_rank_query"] = "needle" if count == 5 else ""
    ui.run()
    assert not ui.exception and len(ui.dataframe) == 1
    assert len(ui.dataframe[0].value) == count
    assert calls == [(count, height, 44 if presentation else 36)]
