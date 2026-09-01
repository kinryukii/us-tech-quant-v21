import json
from pathlib import Path

import numpy as np
import pandas as pd

import raw_a2_strict_counterfactual_stock_selection_identification_r1 as mod


def test_calendar_is_next_open_to_following_open_and_stops_pre2026():
    calendar = pd.to_datetime(["2025-12-26", "2025-12-29", "2025-12-30", "2025-12-31"])
    result = mod.calendar_map(pd.to_datetime(["2025-12-26", "2025-12-29", "2025-12-30"]), calendar)
    assert result[pd.Timestamp("2025-12-26")] == (pd.Timestamp("2025-12-29"), pd.Timestamp("2025-12-30"))
    assert result[pd.Timestamp("2025-12-29")] == (pd.Timestamp("2025-12-30"), pd.Timestamp("2025-12-31"))
    assert pd.Timestamp("2025-12-30") not in result


def test_hac_is_deterministic_and_uses_fixed_lag():
    values = np.linspace(-0.01, 0.02, 40) + np.sin(np.arange(40)) * 0.001
    first = mod.ols_hac(values)
    second = mod.ols_hac(values)
    assert first["alpha_t_hac"] == second["alpha_t_hac"]
    assert first["k"] == 1 and first["n"] == 40


def test_outcome_blind_match_is_same_ff48_and_never_selected_control():
    rows = []
    date = pd.Timestamp("2025-01-02")
    for security, selected, beta in [("A", True, 0.1), ("B", False, 0.11), ("C", False, 2.0)]:
        rows.append({
            "decision_date": date, "canonical_security_id": security, "ticker_at_date": security,
            "ff48_code": 1.0, "ff48_name": "Test", "is_selected": selected,
            "entry_date": pd.Timestamp("2025-01-03"), "exit_date": pd.Timestamp("2025-01-06"),
            "return_key_available": True, "beta_spy": beta, "beta_qqq_orth": beta,
            "beta_soxx_orth": beta, "realized_vol_60": beta, "adv60": beta,
        })
    pairs, audit = mod.match_outcome_blind(pd.DataFrame(rows))
    assert len(pairs) == 1 and pairs.iloc[0].control_security_id == "B"
    assert pairs.iloc[0].control_security_id != pairs.iloc[0].treatment_security_id
    assert pairs.iloc[0].ff48_code == 1.0
    assert audit.status.eq("MATCHED").all()


def test_contract_freezes_counts_covariates_and_zero_counters():
    frozen = mod.contract({"safe": True}, "abc")
    assert frozen["primary_return"]["horizon_legal_sessions"] == 1
    assert frozen["q2"]["covariates"] == mod.MATCH_COVARIATES
    assert frozen["q6"]["placebo_repetitions"] == 1000
    assert frozen["q6"]["rank_shuffle_repetitions"] == 1000
    assert all(value == 0 for value in frozen["temporal_counters"].values())
    assert frozen["anti_bloat"]["new_horizon_search_count"] == 0
    assert frozen["anti_bloat"]["new_matching_method_search_count"] == 0


def test_code_has_no_moomoo_request_or_rv_execution_entrypoint():
    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "get_history_kline" not in source
    assert "get_history_kl_quota" not in source
    assert "A2_SECTOR_NEUTRAL_CONTINUOUS_RANK_RV_V1" not in source
    assert "risk_registry.json" not in source


def test_evidence_verdict_no_optimization():
    q1 = {"within_industry_ic": 0.01, "d10_minus_d1": 0.001, "within_industry_ic_hac_t": 2.1, "d10_minus_d1_hac_t": 1.2}
    q2 = {"match_rate": 0.9, "post_match_max_abs_smd": 0.1, "matched_selection_return": 0.001, "matched_selection_hac_t": 2.0}
    q3 = {"tradable_stack_residual_alpha": 0.05, "tradable_stack_alpha_hac_t": 2.0}
    q4 = {"within_industry_selection_mean": 0.001, "within_industry_selection_hac_t": 2.0, "attribution_closure_error": 0.0, "complete_sessions": 500}
    q5 = {"evaluable_years": 3, "positive_years": 2, "top10_date_contribution": 0.2, "top5_security_contribution": 0.2, "top1_ff48_contribution": 0.2, "leave_one_year_out_sign_consistency": 1.0, "remove_top5_security_result": 0.001, "remove_top10_date_result": 0.001}
    q6 = {"empirical_one_sided_p": 0.01}
    statuses, verdict, _ = mod.evidence_statuses(q1, q2, q3, q4, q5, q6)
    assert set(statuses.values()) == {"SUPPORTED"}
    assert verdict == "PASS_GENUINE_STOCK_SELECTION_ALPHA_SUPPORTED"
