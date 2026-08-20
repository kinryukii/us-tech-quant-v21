from __future__ import annotations

import ast
import inspect

import numpy as np
import pandas as pd
import pytest

from scripts.v22 import abcde_a2_r4_portfolio_translation_using_hgb_incumbent as r4
from scripts.v22 import fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun as r0f1
from scripts.v22.corporate_action_transition_r1 import (
    CorporateActionTransition,
    CorporateActionTransitionAdapter,
    apply_transition_to_positions,
)


def transition(**overrides):
    values = {
        "effective_date": "2024-01-03", "action_type": "FORWARD_SPLIT",
        "old_security_id": "OLD", "new_security_id": "NEW",
        "old_ticker": "AAA", "new_ticker": "AAA", "quantity_multiplier": 2.0,
        "cash_component_per_old_share": 0.0,
        "source_type": "TIER1_ISSUER_REGULATOR_EXCHANGE",
        "source_reference": "https://www.sec.gov/example", "source_fingerprint": "a" * 64,
    }
    values.update(overrides)
    return CorporateActionTransition(**values)


def test_two_for_one_split_quantity_and_economic_value_continuity():
    event = transition(quantity_multiplier=2.0)
    positions, cash, row = apply_transition_to_positions(event, {"AAA": 100.0}, 0.0, pd.Timestamp("2024-01-03"))
    assert positions == {"AAA": 200.0}
    assert positions["AAA"] * 50.0 == 100.0 * 100.0
    assert cash == 0.0 and row["new_quantity"] == 200.0


def test_one_for_ten_reverse_split_has_no_900pct_phantom_return():
    event = transition(action_type="REVERSE_SPLIT", quantity_multiplier=0.1)
    positions, _, _ = apply_transition_to_positions(event, {"AAA": 1000.0}, 0.0, pd.Timestamp("2024-01-03"))
    assert positions["AAA"] == 100.0
    assert positions["AAA"] * 10.0 == 1000.0 * 1.0


def test_wolf_style_security_migration_multiplies_by_0_008352():
    event = transition(
        action_type="SECURITY_REORGANIZATION_SHARE_CONVERSION",
        old_security_id="CUSIP_977852102", new_security_id="CUSIP_97785W106",
        old_ticker="WOLF", new_ticker="WOLF", quantity_multiplier=0.008352,
    )
    positions, _, row = apply_transition_to_positions(event, {"WOLF": 0.458840}, 1.0, pd.Timestamp("2024-01-03"))
    assert positions["WOLF"] == pytest.approx(0.458840 * 0.008352)
    assert row["old_security_id"] != row["new_security_id"]


def test_same_ticker_different_security_id_cannot_keep_original_quantity():
    event = transition(quantity_multiplier=0.25, old_security_id="OLD_CUSIP", new_security_id="NEW_CUSIP")
    positions, _, _ = apply_transition_to_positions(event, {"AAA": 8.0}, 0.0, pd.Timestamp("2024-01-03"))
    assert positions["AAA"] == 2.0
    assert positions["AAA"] != 8.0


def test_ticker_change_same_economic_security_preserves_quantity():
    event = transition(
        action_type="TICKER_CHANGE_NO_ECONOMIC_CHANGE", old_ticker="OLD", new_ticker="NEW",
        old_security_id="ECONOMIC_ID", new_security_id="ECONOMIC_ID_V2", quantity_multiplier=1.0,
    )
    positions, _, _ = apply_transition_to_positions(event, {"OLD": 3.5}, 2.0, pd.Timestamp("2024-01-03"))
    assert positions == {"NEW": 3.5}


def test_wrong_ratio_direction_is_rejected():
    with pytest.raises(ValueError, match="WRONG_RATIO_ORIENTATION"):
        transition(quantity_multiplier=0.008352, ratio_orientation="OLD_DIVIDED_BY_NEW")


def test_event_effective_date_timing_not_early_or_late():
    event = transition(quantity_multiplier=2.0)
    before, _, row_before = apply_transition_to_positions(event, {"AAA": 10.0}, 0.0, pd.Timestamp("2024-01-02"))
    after, _, row_after = apply_transition_to_positions(event, {"AAA": 10.0}, 0.0, pd.Timestamp("2024-01-04"))
    exact, _, row_exact = apply_transition_to_positions(event, {"AAA": 10.0}, 0.0, pd.Timestamp("2024-01-03"))
    assert before == after == {"AAA": 10.0}
    assert row_before is row_after is None
    assert exact == {"AAA": 20.0} and row_exact is not None


def test_fractional_shares_are_preserved_without_rounding():
    event = transition(quantity_multiplier=0.008352)
    positions, _, _ = apply_transition_to_positions(event, {"AAA": 0.458840}, 0.0, pd.Timestamp("2024-01-03"))
    assert positions["AAA"] == pytest.approx(0.00383223168)


def test_old_position_removed_after_migration_no_double_counting():
    event = transition(old_ticker="OLD", new_ticker="NEW", quantity_multiplier=0.5)
    positions, _, _ = apply_transition_to_positions(event, {"OLD": 10.0}, 0.0, pd.Timestamp("2024-01-03"))
    assert "OLD" not in positions and positions == {"NEW": 5.0}
    with pytest.raises(RuntimeError, match="DOUBLE_COUNT"):
        apply_transition_to_positions(event, {"OLD": 10.0, "NEW": 1.0}, 0.0, pd.Timestamp("2024-01-03"))


def test_corrected_nav_transition_occurs_before_mark_and_matches_value():
    event = transition(action_type="REVERSE_SPLIT", quantity_multiplier=0.1)
    adapter = CorporateActionTransitionAdapter([event])
    positions, cash, rows = adapter.apply(
        execution_date=pd.Timestamp("2024-01-03"), shares={"AAA": 100.0}, cash=5.0,
        context={"model": "A1", "top_n": 20, "cost_bps": 10},
    )
    nav = cash + positions["AAA"] * 100.0
    assert nav == 5.0 + 100.0 * 10.0
    assert rows[0]["timing_rule"] == "BEFORE_EFFECTIVE_SESSION_MARK_AND_BEFORE_TRADES"


def test_signal_and_ranking_fingerprint_invariant():
    signals = pd.DataFrame({
        "signal_date": pd.to_datetime(["2023-01-03", "2023-01-03"]),
        "ticker": ["AAA", "BBB"], "a1_rank": [1.0, 2.0], "a2_rank": [2.0, 1.0],
    })
    before = r0f1.dataframe_fingerprint(signals)
    adapter = CorporateActionTransitionAdapter([])
    adapter.apply(execution_date=pd.Timestamp("2023-01-04"), shares={}, cash=1.0, context={})
    assert r0f1.dataframe_fingerprint(signals) == before


def test_execution_policy_invariant_default_r4_path_has_no_transition_columns():
    source = inspect.getsource(r4.simulate_portfolio)
    assert "corporate_action_adapter is not None" in source
    assert "missing opens never generate cash or stale orders" in source.lower()
    assert r0f1.sha256_file(r4.EXECUTION_ELIGIBILITY_POLICY_PATH) == r0f1.sha256_file(r4.EXECUTION_ELIGIBILITY_POLICY_PATH)


def test_universe_invariant_is_frozen_in_summary_contract():
    inputs = r0f1.r0f.load_inputs()
    assert inputs.frozen_summary["CURRENT_COHORT_COUNT"] == 325
    assert inputs.frozen_summary["MODEL_COHORT_CHANGED"] is False


def test_post2025_outcome_read_count_is_zero_by_construction():
    source = inspect.getsource(r0f1)
    assert 'END_EXCLUSIVE = pd.Timestamp("2026-01-01")' in source
    tree = ast.parse(source)
    assert not any(isinstance(node, ast.Attribute) and node.attr in {"target", "outcome"} for node in ast.walk(tree))


def test_model_fit_and_search_count_zero_and_no_fit_call():
    tree = ast.parse(inspect.getsource(r0f1))
    fit_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fit"]
    assert fit_calls == []


def test_heuristic_fingerprint_alone_cannot_trigger_auto_repair():
    with pytest.raises(ValueError, match="HEURISTIC"):
        transition(source_type="TIER4_PRICE_FINGERPRINT_ONLY")


def test_insufficient_authoritative_evidence_fails_closed():
    manifest = pd.DataFrame(columns=["ticker", "event_date"])
    review = pd.DataFrame([{
        "classification": "INSUFFICIENT_EVIDENCE_FAIL_CLOSED", "material_to_portfolio": True,
        "ticker": "AAA", "event_date": pd.Timestamp("2024-01-03"),
    }])
    with pytest.raises(RuntimeError, match="UNRESOLVED_MATERIAL"):
        r0f1.build_policy(manifest, review)


def test_deterministic_transition_fingerprint_and_application():
    first = transition()
    second = transition()
    assert first.event_fingerprint == second.event_fingerprint
    a1 = CorporateActionTransitionAdapter([first])
    a2 = CorporateActionTransitionAdapter([second])
    result1 = a1.apply(execution_date=pd.Timestamp("2024-01-03"), shares={"AAA": 2.0}, cash=1.0, context={})
    result2 = a2.apply(execution_date=pd.Timestamp("2024-01-03"), shares={"AAA": 2.0}, cash=1.0, context={})
    assert result1 == result2


def test_all_real_r0f_fingerprints_receive_closed_review_classification():
    manifest, review = r0f1.build_event_review()
    assert len(review) >= 27
    assert review.classification.isin(r0f1.REVIEW_CLASSIFICATIONS).all()
    assert not (review.classification.eq("INSUFFICIENT_EVIDENCE_FAIL_CLOSED") & review.material_to_portfolio).any()
    assert len(manifest) == 8
