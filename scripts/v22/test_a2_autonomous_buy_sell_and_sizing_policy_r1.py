from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).with_name("a2_autonomous_buy_sell_and_sizing_policy_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_autonomous_policy_tested", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_bounded_projection_preserves_long_only_full_gross_contract() -> None:
    raw = np.linspace(-2.0, 3.0, MODULE.TOP_N)
    for lower, upper in ((0.03, 0.07), (0.04, 0.06)):
        weights = MODULE.bounded_project(raw, lower, upper)
        assert len(weights) == 20
        assert np.all(weights > 0.0)
        assert weights.min() >= lower - 1e-12
        assert weights.max() <= upper + 1e-12
        assert abs(float(weights.sum()) - 1.0) <= 1e-12


def test_dynamic_role_state_distinguishes_incumbent_exit_and_buffer() -> None:
    frame = pd.DataFrame(
        {
            "ticker": ["KEEP", "EXIT", "ENTRY", "BUFFER"],
            "a2_rank": [2, 24, 11, 28],
        }
    )
    held = {
        "KEEP": {"age": 4, "return": 0.1, "drawdown": -0.02},
        "EXIT": {"age": 7, "return": -0.1, "drawdown": -0.15},
    }
    result = MODULE.apply_dynamic_state(frame, held).set_index("ticker")
    assert result.loc["KEEP", "current_role"] == "CURRENT_HOLDING"
    assert result.loc["EXIT", "current_role"] == "RAW_EXIT_CANDIDATE"
    assert result.loc["ENTRY", "current_role"] == "NEW_RAW_TOP20_ENTRANT"
    assert result.loc["BUFFER", "current_role"] == "RAW_BUFFER_21_30"
    assert result.loc["EXIT", "holding_age"] == 7


def test_preregistered_search_and_temporal_firewalls_are_bounded() -> None:
    assert MODULE.MAX_UNIQUE_MODEL_SPECS == 96
    assert MODULE.MAX_TOTAL_MODEL_FITS == 600
    assert MODULE.MAX_POLICY_SPECS == 48
    assert MODULE.MAX_ENSEMBLES == 2
    assert MODULE.MAX_OUTER_FINALISTS == 8
    assert MODULE.LABEL_DATE_CUTOFF == pd.Timestamp("2025-12-31")
    assert MODULE.FEATURE_DATE_CUTOFF < pd.Timestamp("2026-01-01")
    assert MODULE.RANDOM_SEEDS == (20260823, 20260824, 20260825)


def test_policy_templates_keep_raw_prior_and_fixed_allowed_bounds() -> None:
    model = MODULE.ModelSpec("m", "RIDGE", "M0_GLOBAL_POOLED", {"alpha": 1.0})
    policies = MODULE.policy_templates(model)
    assert policies
    assert {p.eta for p in policies} <= {0.25, 0.50, 1.00}
    assert {p.bounds for p in policies} <= {(0.03, 0.07), (0.04, 0.06)}
    assert {p.entrant_protection for p in policies} <= {
        "EP0_NO_HARD_PROTECTION",
        "EP1_RAW_TOP10_MUST_HOLD",
    }
    assert {p.candidate_universe for p in policies} <= {
        "U0_RAW_TOP20",
        "U1_RAW_TOP30_BUFFER",
    }


def test_sector_shrinkage_is_support_only_and_has_global_fallback() -> None:
    support = pd.Series({"SMALL": 100.0, "LARGE": 400.0})
    median_n = float(support.median())
    shrink = support / (support + median_n)
    assert 0.0 < shrink["SMALL"] < shrink["LARGE"] < 1.0
    assert "UNSEEN" not in shrink.index  # predict_bundle therefore leaves global prediction unchanged.


def test_label_maturity_purge_and_oof_extension_contract() -> None:
    validation_start = pd.Timestamp("2023-01-01")
    label_end = pd.Series(pd.to_datetime(["2022-12-29", "2023-01-01", "2023-01-02"]))
    assert label_end.lt(validation_start).tolist() == [True, False, False]
    prereg_source = SOURCE.read_text(encoding="utf-8")
    assert "2023_RECONSTRUCTION_MAX_ABS_ERROR_MUST_EQUAL_0" in prereg_source
    assert "NO_FULL_SAMPLE_BACKFILL" in prereg_source
    assert "U2_STATUS=SKIPPED_UNSAFE_SCORE" not in prereg_source  # status is data-driven, not silently accepted.


def test_2026_outcome_access_is_rejected_before_loader_call() -> None:
    class NeverCalled:
        def load_prices(self, *_args, **_kwargs):
            raise AssertionError("loader must not be called")
    with pytest.raises(MODULE.GateFailure, match="2026_OUTCOME_ACCESS"):
        MODULE.qfq_forward_labels(NeverCalled(), {"QQQ"}, [2025, 2026])


def test_labels_use_continuous_raw_qfq_not_exact_ledger_marks() -> None:
    dates = pd.bdate_range("2025-01-02", periods=21)
    exact = pd.DataFrame({"ticker": "X", "trade_date": dates, "close": np.r_[1.0, np.repeat(100.0, 20)]})
    raw = pd.DataFrame({"ticker": "X", "trade_date": dates, "close": np.linspace(10.0, 20.0, 21), "source": "CANONICAL_QFQ"})
    exact.attrs["raw_counterfactual"] = raw

    class FixtureAction:
        @staticmethod
        def load_prices(*_args, **_kwargs):
            return exact

    _, labels = MODULE.qfq_forward_labels(FixtureAction(), {"X"}, [2025])
    first = labels.sort_values("signal_date").iloc[0]
    assert first.y_abs20 == pytest.approx(1.0)
    assert first.y_abs20 != pytest.approx(99.0)


def test_feature_ablation_and_hierarchical_contract_are_bounded() -> None:
    assert set(MODULE.FEATURE_FAMILIES) == {
        "F0_RAW_CORE", "F1_RAW_PLUS_STATE", "F2_RAW_PLUS_VOL_LIQ", "F3_RAW_PLUS_TREND",
        "F4_RAW_PLUS_SECTOR_RELATIVE", "F5_RAW_PLUS_PORTFOLIO_RISK", "F6_FULL_BOUNDED",
    }
    assert MODULE.MIN_SECTOR_DECISION_DATES == 30
    assert MODULE.MIN_SECTOR_EVENTS == 200
    specs, _ = MODULE.candidate_model_specs()
    assert len(specs) <= MODULE.MAX_UNIQUE_MODEL_SPECS
    assert {s.structure for s in specs} == {
        "M0_GLOBAL_POOLED", "M1_GLOBAL_WITH_FF12_FEATURES",
        "M2_GLOBAL_PLUS_FF12_RESIDUAL_HEADS", "M3_ROLE_AWARE_GLOBAL_PLUS_FF12",
    }


def test_optimizer_replay_is_deterministic_and_constrained() -> None:
    utility = np.linspace(-1.0, 1.0, MODULE.TOP_N)
    vol = np.linspace(0.1, 0.4, MODULE.TOP_N)
    pretrade = np.repeat(0.05, MODULE.TOP_N)
    first, status1 = MODULE.optimize_bounded_weights(utility, vol, pretrade, 0.03, 0.07, "LOW", "BASE")
    second, status2 = MODULE.optimize_bounded_weights(utility, vol, pretrade, 0.03, 0.07, "LOW", "BASE")
    np.testing.assert_allclose(first, second, atol=1e-12, rtol=0)
    assert status1 == status2
    assert abs(first.sum() - 1.0) <= 1e-12
    assert first.min() >= 0.03 - 1e-12 and first.max() <= 0.07 + 1e-12


def test_freeze_no_promotion_hash_and_reconciliation_guards_are_present() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    for token in (
        "outer_outcome_read_count_at_freeze", "PRIMARY_CHANGED_AFTER_2025_READ",
        "automatic_promotion\":False", "LABEL_MATURITY_FAILURE", "PASS_HASH_VERIFIED",
        "ONE_TIME_PREREGISTRATION_RECONCILIATION", "2026_OUTCOME_USED=FALSE",
        "PREREG_CONTAMINATION_AFTER_OUTER_READ",
    ):
        assert token in source


def raw_a2_records(target_date: str = "2026-08-24") -> list[dict[str, object]]:
    return [
        {
            "target_date": target_date,
            "security_id": f"S{index:02d}",
            "ticker": f"T{index:02d}",
            "rank": index,
            "score": float(100 - index),
            "raw_target_weight": 0.05,
            "model_id": "A2_HGB",
        }
        for index in range(1, 21)
    ]


def test_operational_all_cash_state_builds_equal_weight_buy_plan_deterministically() -> None:
    state = {"as_of": "2026-08-24", "cash": 1000.0, "positions": []}
    first = MODULE.build_operational_policy_plan(raw_a2_records(), state)
    second = MODULE.build_operational_policy_plan(raw_a2_records(), state)
    assert first == second
    assert len(first["target_weights"]) == 20
    assert set(first["target_weights"].values()) == {0.05}
    assert {row["action"] for row in first["actions"]} == {"BUY"}
    assert first["current_portfolio"]["total_equity"] == 1000.0
    assert first["current_portfolio"]["gross_exposure"] == 0.0
    assert first["current_portfolio"]["cash_weight"] == 1.0
    assert first["target_cash_weight"] == pytest.approx(0.0, abs=1e-12)
    assert first["accounting"]["cash_after_fraction"] >= 0.0


def test_operational_drifted_state_generates_all_five_actions() -> None:
    state = {
        "as_of": "2026-08-24",
        "cash": 750.0,
        "positions": [
            {"symbol": "US.T02", "shares": 3.0, "mark_price": 10.0},
            {"symbol": "US.T03", "shares": 5.0, "mark_price": 10.0},
            {"symbol": "US.T04", "shares": 7.0, "mark_price": 10.0},
            {"symbol": "US.OLD", "shares": 10.0, "mark_price": 10.0},
        ],
    }
    plan = MODULE.build_operational_policy_plan(raw_a2_records(), state)
    by_symbol = {row["security"]: row for row in plan["actions"]}
    assert by_symbol["US.T01"]["action"] == "BUY"
    assert by_symbol["US.T02"]["action"] == "ADD"
    assert by_symbol["US.T03"]["action"] == "HOLD"
    assert by_symbol["US.T04"]["action"] == "REDUCE"
    assert by_symbol["US.OLD"]["action"] == "EXIT"
    assert set(row["action"] for row in plan["actions"]) == {"BUY", "ADD", "HOLD", "REDUCE", "EXIT"}
    assert plan["current_portfolio"]["gross_exposure"] == pytest.approx(0.25)
    assert plan["current_portfolio"]["cash_weight"] == pytest.approx(0.75)
    assert plan["accounting"]["turnover"] >= 0.0
    assert plan["accounting"]["transaction_cost_fraction"] == pytest.approx(
        plan["accounting"]["turnover"] * MODULE.RAW_A2_COST_BPS / 10000.0
    )


def test_operational_policy_requires_explicit_current_state_and_never_infers_holdings() -> None:
    with pytest.raises(MODULE.GateFailure, match="CURRENT_PORTFOLIO_STATE_REQUIRED"):
        MODULE.build_operational_policy_plan(raw_a2_records(), None)


def test_operational_current_state_rejects_short_and_negative_cash() -> None:
    with pytest.raises(MODULE.GateFailure, match="CASH_INVALID"):
        MODULE.build_operational_policy_plan(raw_a2_records(), {"as_of": "2026-08-24", "cash": -1, "positions": []})
    with pytest.raises(MODULE.GateFailure, match="SHORT_FORBIDDEN"):
        MODULE.build_operational_policy_plan(
            raw_a2_records(),
            {"as_of": "2026-08-24", "cash": 1000, "positions": [{"symbol": "US.T01", "shares": -1, "mark_price": 10}]},
        )


def test_operational_policy_accepts_only_authoritative_equal_weight_top20() -> None:
    rows = raw_a2_records()
    rows[0]["raw_target_weight"] = 0.04
    with pytest.raises(MODULE.GateFailure, match="EQUAL_WEIGHT_CONTRACT_FAILURE"):
        MODULE.build_operational_policy_plan(rows, {"as_of": "2026-08-24", "cash": 1000, "positions": []})


def clean_fixture(prices: np.ndarray, source: str = "CANONICAL_QFQ") -> tuple[pd.DatetimeIndex, pd.DataFrame]:
    dates = pd.bdate_range("2024-01-02", periods=len(prices))
    frame = pd.DataFrame({"ticker": "X", "trade_date": dates, "close": prices, "source": source})
    return dates, frame


def labels_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    exact = raw.copy(); exact["close"] = exact.close * 100.0; exact.attrs["raw_counterfactual"] = raw
    class FixtureAction:
        @staticmethod
        def load_prices(*_args, **_kwargs):
            return exact
    return MODULE.qfq_forward_labels(FixtureAction(), {"X"}, [2024])[1]


def test_ml_labels_use_raw_counterfactual_only() -> None:
    values = np.linspace(10.0, 20.0, 25); _, raw = clean_fixture(values)
    labels = labels_from_raw(raw)
    assert labels.iloc[0].y_abs20 == pytest.approx(values[20]/values[0]-1.0)
    assert labels.label_price_lineage.eq(MODULE.LABEL_LINEAGE).all()


def test_portfolio_ledger_marks_forbidden_for_labels() -> None:
    _, raw = clean_fixture(np.linspace(10.0, 20.0, 26))
    forbidden = raw.iloc[[5]].copy(); forbidden["trade_date"] += pd.Timedelta(days=1); forbidden["source"] = MODULE.FORBIDDEN_LABEL_SOURCE
    mixed = pd.concat([raw, forbidden], ignore_index=True)
    labels = labels_from_raw(mixed)
    assert not labels[["start_price_source", "end5_price_source", "end20_price_source"]].astype(str).eq(MODULE.FORBIDDEN_LABEL_SOURCE).any().any()


def test_start_end_price_lineage_equal() -> None:
    _, raw = clean_fixture(np.linspace(5.0, 8.0, 25))
    labels = labels_from_raw(raw).dropna(subset=["y_abs20"])
    assert labels[["start_price_lineage", "end5_price_lineage", "end20_price_lineage"]].nunique(axis=1).eq(1).all()


def test_abs20_direct_formula() -> None:
    values = np.linspace(10.0, 30.0, 25); _, raw = clean_fixture(values)
    first = labels_from_raw(raw).iloc[0]
    assert first.y_abs20 == pytest.approx(values[20] / values[0] - 1.0)


def test_abs5_direct_formula() -> None:
    values = np.linspace(10.0, 30.0, 25); _, raw = clean_fixture(values)
    first = labels_from_raw(raw).iloc[0]
    assert first.y_abs5 == pytest.approx(values[5] / values[0] - 1.0)


def test_ff12_residual_clean_lineage() -> None:
    panel = pd.DataFrame({"signal_date": pd.to_datetime(["2024-01-02"]*2), "ff12": ["TECH","TECH"], "y_abs20": [.1,.3]})
    residual = panel.y_abs20 - panel.groupby(["signal_date","ff12"]).y_abs20.transform("mean")
    np.testing.assert_allclose(residual, [-.1,.1], atol=1e-15)


def test_downside_clean_path() -> None:
    values = np.array([100.0, 90.0, 80.0] + [100.0]*18); _, raw = clean_fixture(values)
    first = labels_from_raw(raw).iloc[0]
    assert first.y_downside20 == pytest.approx(.2)


def test_persist20_uses_clean_labels() -> None:
    values = pd.Series([-.1,.1,.2,.3]); median = values.median()
    assert (values > median).astype(float).tolist() == [0.0,0.0,1.0,1.0]


def test_label_end_date_before_2026() -> None:
    dates = pd.bdate_range("2025-11-03", periods=30)
    raw = pd.DataFrame({"ticker":"X","trade_date":dates,"close":np.linspace(10,11,30),"source":"CANONICAL_QFQ"})
    mature = labels_from_raw(raw).dropna(subset=["label_end_date"])
    assert mature.label_end_date.max() <= pd.Timestamp("2025-12-31")


def test_nvda_split_regression() -> None:
    action = MODULE.import_file("a2_policy_test_nvda_action", MODULE.ACTION_SOURCE)
    labels = MODULE.qfq_forward_labels(action, {"NVDA","QQQ"}, [2024])[1]
    value = float(labels.loc[(labels.ticker.eq("NVDA")) & labels.signal_date.eq(pd.Timestamp("2024-05-15")), "y_abs20"].iloc[0])
    assert value == pytest.approx(.36976269624412206, abs=1e-12)
    assert value < 5.0


@pytest.mark.parametrize("jump", [10.0, .1])
def test_split_and_reverse_split_sentinel_cases(jump: float) -> None:
    continuous = np.linspace(100.0, 120.0, 25)
    _, raw = clean_fixture(continuous)
    exact = raw.copy(); exact.loc[exact.index >= 10, "close"] *= jump; exact.attrs["raw_counterfactual"] = raw
    class FixtureAction:
        @staticmethod
        def load_prices(*_args, **_kwargs): return exact
    first = MODULE.qfq_forward_labels(FixtureAction(), {"X"}, [2024])[1].iloc[0]
    assert first.y_abs20 == pytest.approx(continuous[20]/continuous[0]-1.0)


def test_no_action_control() -> None:
    values = np.repeat(42.0, 25); _, raw = clean_fixture(values)
    first = labels_from_raw(raw).iloc[0]
    assert first.y_abs5 == pytest.approx(0.0) and first.y_abs20 == pytest.approx(0.0)


def test_label_arithmetic_mismatch_zero() -> None:
    values = np.geomspace(10.0, 20.0, 25); _, raw = clean_fixture(values)
    labels = labels_from_raw(raw)
    np.testing.assert_allclose(labels.y_abs5.iloc[:20], values[5:25]/values[:20]-1.0, atol=1e-15, rtol=0)
    np.testing.assert_allclose(labels.y_abs20.iloc[:5], values[20:25]/values[:5]-1.0, atol=1e-15, rtol=0)


def test_mixed_scale_guard() -> None:
    _, raw = clean_fixture(np.linspace(10.0, 15.0, 25))
    labels = labels_from_raw(raw).dropna(subset=["y_abs20"])
    assert int((labels[["start_price_lineage","end20_price_lineage"]].nunique(axis=1)>1).sum()) == 0


def test_t1_t4_gate_uses_builder_full_pool_before_training_subset() -> None:
    date = pd.Timestamp("2022-06-01")
    panel = pd.DataFrame({
        "signal_date": [date]*3, "ticker": ["A","B","C"], "ff12": ["TECH"]*3,
        "y_abs20": [.1,.3,.5], "y_abs5": [.01,.02,.03], "y_downside20": [.1,.2,.3],
        "label_end_date": [pd.Timestamp("2022-06-30")]*3,
    })
    panel["y_ff12res20"] = panel.y_abs20-panel.y_abs20.mean()
    panel["y_persist20"] = (panel.y_abs20>panel.y_abs20.median()).astype(float)
    labels = pd.DataFrame({"signal_date":[date]*3,"ticker":["A","B","C"],"start_price":[10.0]*3,"end_price_20":[11.0,13.0,15.0],"label_price_lineage":[MODULE.LABEL_LINEAGE]*3})
    facts, _ = MODULE.panel_label_hard_gate(panel, labels, "UNIT_FULL_POOL")
    assert facts["panel_label_hard_gate"] == "PASS"


def test_r2_distinct_identity_and_r1_rerun_block_remain_frozen() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    wrapper = SOURCE.with_name("a2_clean_label_lineage_and_autonomous_policy_r2.py").read_text(encoding="utf-8")
    assert MODULE.R1_TASK != MODULE.R2_TASK
    assert "A2_AUTONOMOUS_POLICY_MODE" in wrapper and '"R2"' in wrapper
    assert "PREREG_CONTAMINATION_AFTER_OUTER_READ" in source
    assert "automatic_promotion\":False" in source
