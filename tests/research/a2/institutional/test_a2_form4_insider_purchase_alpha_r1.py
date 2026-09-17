from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = (
    Path(__file__).resolve().parents[4]
    / "scripts"
    / "research"
    / "a2"
    / "institutional"
    / "a2_form4_insider_purchase_alpha_r1.py"
)


def module(name: str = "h22_test"):
    spec = importlib.util.spec_from_file_location(name, SOURCE)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def owners(count: int, relationship: str = "Officer") -> pd.DataFrame:
    return pd.DataFrame({
        "ACCESSION_NUMBER": ["A1"] * count,
        "RPTOWNERCIK": [str(100 + i) for i in range(count)],
        "RPTOWNER_RELATIONSHIP": [relationship] * count,
    })


def joined(**overrides) -> pd.DataFrame:
    base = {
        "DOCUMENT_TYPE": "4", "TRANS_CODE": "P", "TRANS_ACQUIRED_DISP_CD": "A",
        "TRANS_SHARES": "10", "EQUITY_SWAP_INVOLVED": "0", "TRANS_TIMELINESS": "",
        "eligible_owner_count": 1,
    }
    base.update(overrides)
    return pd.DataFrame([base])


def synthetic_panel() -> pd.DataFrame:
    date = pd.Timestamp("2023-01-10")
    return pd.DataFrame({
        "signal_date": [date, date], "ticker": ["AAA", "BBB"], "split": ["DEVELOPMENT"] * 2,
        "a2_rank": [1, 2], "cik": pd.Series([1, 2], dtype="Int64"),
        "identity_status": ["EXACT", "EXACT"],
    })


def synthetic_event() -> pd.DataFrame:
    return pd.DataFrame({
        "ACCESSION_NUMBER": ["A1"], "NONDERIV_TRANS_SK": ["T1"], "issuer_cik": pd.Series([1], dtype="Int64"),
        "filing_date": [pd.Timestamp("2023-01-06")], "buyer_event_id": ["0001"],
        "valid_price": [True], "transaction_value": [1000.0], "owner_conviction_ratio": [0.10],
    })


def test_stage_a_h22_duplicate_resolution_and_exact_stop_statuses() -> None:
    m = module()
    assert m.resolve_duplicate_gate("H22 Clustered insider activity") == "PASS_REUSE_EXISTING_HYPOTHESIS"
    assert m.resolve_duplicate_gate("H22 Clustered insider activity", ["COMPLETED"]) == "STOP_DUPLICATE_RESEARCH_ALREADY_EVALUATED"
    assert m.resolve_duplicate_gate("H22 Clustered insider activity", ["REJECTED"]) == "STOP_EXISTING_HYPOTHESIS_REJECTED"


def test_actual_sec_zip_cache_and_headers_validate() -> None:
    m = module()
    valid, audit = m.validate_cache()
    assert len(valid) == 21
    assert audit["sec_quarters_cache_hit"] == 21
    assert audit["network_used"] is False


@pytest.mark.parametrize("count", [1, 2, 3])
def test_accession_owner_join_cardinality_is_aggregated(count: int) -> None:
    m = module()
    summary = m.build_owner_summary(owners(count))
    assert len(summary) == 1
    assert int(summary.iloc[0].eligible_owner_count) == count
    transactions = pd.DataFrame({"ACCESSION_NUMBER": ["A1"], "value": [100.0]})
    merged = transactions.merge(summary, on="ACCESSION_NUMBER", validate="many_to_one")
    assert len(merged) == 1 and merged.value.sum() == 100.0


@pytest.mark.parametrize(
    "field,value",
    [
        ("DOCUMENT_TYPE", "4/A"), ("TRANS_CODE", "S"), ("TRANS_ACQUIRED_DISP_CD", "D"),
        ("TRANS_SHARES", "0"), ("EQUITY_SWAP_INVOLVED", "1"), ("TRANS_TIMELINESS", "L"),
        ("eligible_owner_count", 0),
    ],
)
def test_fixed_p_purchase_filter_rejects_noncontract_rows(field: str, value: object) -> None:
    m = module()
    assert bool(m.fixed_event_filter(joined(**{field: value})).iloc[0]) is False
    assert bool(m.fixed_event_filter(joined()).iloc[0]) is True


def test_relationship_filter_excludes_pure_ten_percent_and_other() -> None:
    m = module()
    assert int(m.build_owner_summary(owners(1, "TenPercentOwner")).iloc[0].eligible_owner_count) == 0
    assert int(m.build_owner_summary(owners(1, "Other")).iloc[0].eligible_owner_count) == 0
    assert int(m.build_owner_summary(owners(1, "Director,TenPercentOwner")).iloc[0].eligible_owner_count) == 1


def test_joint_filing_breadth_is_one_event_and_value_not_multiplied() -> None:
    m = module()
    frame = pd.DataFrame({
        "ACCESSION_NUMBER": ["A1", "A1"], "eligible_owner_count": [3, 3],
        "eligible_owner_ids": ["1|2|3", "1|2|3"], "transaction_value": [100.0, 200.0],
    })
    result = m.add_buyer_event_ids(frame)
    assert result.buyer_event_id.nunique() == 1
    assert result.transaction_value.sum() == 300.0
    assert result.buyer_event_id.iloc[0] == "JOINT:A1"


def test_filing_date_next_full_session_and_same_day_unavailable() -> None:
    m = module()
    sessions = pd.DatetimeIndex(["2023-01-06", "2023-01-09", "2023-01-10"])
    assert m.next_full_session(pd.Timestamp("2023-01-06"), sessions) == pd.Timestamp("2023-01-09")
    assert m.next_full_session(pd.Timestamp("2023-01-06"), sessions, 1) == pd.Timestamp("2023-01-10")


def test_2026_outcome_firewall() -> None:
    m = module()
    m.validate_outcome_dates(pd.Series([pd.Timestamp("2025-12-31")]))
    with pytest.raises(m.ContractError, match="POST2025_OUTCOME"):
        m.validate_outcome_dates(pd.Series([pd.Timestamp("2026-01-02")]))


def test_known_no_event_is_distinct_from_unmapped_missing_state() -> None:
    m = module()
    panel = synthetic_panel()
    panel.loc[1, "identity_status"] = "ISSUER_UNMAPPED"
    sessions = pd.DatetimeIndex(["2023-01-06", "2023-01-09", "2023-01-10"])
    adv = pd.Series({("AAA", pd.Timestamp("2023-01-10")): 10000.0})
    result = m.materialize_components(panel, synthetic_event(), adv, sessions)
    assert result.loc[result.ticker.eq("AAA"), "state"].iloc[0].startswith("EVENT_PRESENT")
    assert result.loc[result.ticker.eq("BBB"), "state"].iloc[0] == "ISSUER_UNMAPPED"
    assert pd.isna(result.loc[result.ticker.eq("BBB"), "insider_uplift_score"].iloc[0])


def test_four_fixed_components_equal_composite_and_determinism() -> None:
    m = module()
    panel = synthetic_panel()
    sessions = pd.DatetimeIndex(["2023-01-06", "2023-01-09", "2023-01-10"])
    adv = pd.Series({("AAA", pd.Timestamp("2023-01-10")): 10000.0, ("BBB", pd.Timestamp("2023-01-10")): 10000.0})
    first = m.materialize_components(panel, synthetic_event(), adv, sessions)
    second = m.materialize_components(panel, synthetic_event(), adv, sessions)
    pd.testing.assert_frame_equal(first, second)
    row = first.loc[first.ticker.eq("AAA")].iloc[0]
    assert row[m.COMPONENTS[0]] == 1 and row[m.COMPONENTS[1]] == 1
    assert row[m.COMPONENTS[2]] == pytest.approx(0.1) and row[m.COMPONENTS[3]] == pytest.approx(0.1)
    ranks = [row[f"{name}_rank_pct"] for name in m.COMPONENTS]
    assert row.insider_uplift_score == pytest.approx(np.mean(ranks))


def test_preregistered_contract_has_no_extra_windows_or_weights() -> None:
    m = module()
    contract = m.immutable_contract()
    assert contract["windows_calendar_days"] == {"F1": 90, "F2": 30, "F3": 90, "F4": 90}
    assert contract["score_blend"] == [0.80, 0.20]
    assert contract["dual_sleeve"] == [0.80, 0.20]
    assert len(contract["candidates"]) == 4


def test_c1_does_not_fill_and_c3_nets_overlap_at_target_level() -> None:
    m = module()
    date = pd.Timestamp("2023-01-03")
    rows = []
    for rank in range(1, 22):
        rows.append({
            "signal_date": date, "ticker": f"T{rank:02d}", "a2_rank": rank,
            "standalone_rank": 1 if rank == 1 else np.nan,
            "combined_rank": rank if rank <= 20 else np.nan,
        })
    maps = m.target_maps(pd.DataFrame(rows))
    assert len(maps["C1_INSIDER_STANDALONE"][date]) == 1
    assert sum(maps["C1_INSIDER_STANDALONE"][date].values()) == pytest.approx(0.05)
    assert maps["C3_DUAL_SLEEVE_80_20"][date]["T01"] == pytest.approx(0.05)
    assert maps["C3_DUAL_SLEEVE_80_20"][date]["T02"] == pytest.approx(0.04)
    assert sum(maps["C3_DUAL_SLEEVE_80_20"][date].values()) == pytest.approx(0.81)


def test_label_lineage_fail_closed_on_post_boundary_and_no_random_ties() -> None:
    m = module()
    with pytest.raises(m.ContractError):
        m.validate_outcome_dates(pd.Series([pd.NaT]))
    panel = pd.DataFrame({
        "signal_date": [pd.Timestamp("2023-01-03")] * 3,
        "state": ["KNOWN_NO_EVENT"] * 3,
        **{name: [np.nan] * 3 for name in m.COMPONENTS},
    })
    ranked = m.rank_event_components(panel)
    assert ranked.insider_uplift_score.tolist() == [0.0, 0.0, 0.0]


def test_mechanism_contract_is_fixed_signal_only_and_deterministic() -> None:
    m = module()
    first = m.backward_binary_diagnostic_contract("abc")
    second = m.backward_binary_diagnostic_contract("abc")
    assert first == second
    assert m.contract_sha256(first) == m.contract_sha256(second)
    assert first["diagnostic_id"] == "H22_BINARY_RECENT_PURCHASE_PRESENCE_DIAGNOSTIC"
    assert first["economic_candidate_count_added"] == 0
    assert first["feature_search"] is False
    assert first["window_search"] is False
    assert first["weight_search"] is False


def test_existing_c2_score_binary_and_intensity_decomposition_is_exact() -> None:
    m = module()
    panel = pd.DataFrame({
        "state": ["EVENT_PRESENT_VALID", "KNOWN_NO_EVENT", "ISSUER_UNMAPPED"],
        "a2_rank_pct": [0.80, 0.70, 0.60],
        "insider_uplift_score": [0.75, 0.0, np.nan],
        "combined_score": [0.80 * 0.80 + 0.20 * 0.75, 0.80 * 0.70, np.nan],
    })
    result, error = m.decompose_existing_c2_score(panel)
    assert error <= np.finfo(float).eps
    assert result.loc[0, "binary_event_term"] == pytest.approx(0.10)
    assert result.loc[0, "within_event_intensity_term"] == pytest.approx(0.05)
    assert result.loc[1, "binary_event_term"] == 0
    assert pd.isna(result.loc[2, "c2_score_reconstructed"])


def test_displacement_term_attribution_uses_exact_ablation_categories() -> None:
    m = module()
    assert m.displacement_category(-0.08, 0.10, 0.01) == "BINARY_EVENT_TERM_DECISIVE"
    assert m.displacement_category(-0.08, 0.01, 0.10) == "WITHIN_EVENT_INTENSITY_TERM_DECISIVE"
    assert m.displacement_category(-0.15, 0.10, 0.10) == "BOTH_INSIDER_TERMS_REQUIRED"
    assert m.displacement_category(0.01, 0.0, 0.0) == "RAW_A2_TERM_ALREADY_SUFFICIENT"
    assert m.displacement_category(-0.01, 0.02, 0.02) == "OTHER_OR_TIE"


def test_binary_return_stats_keep_missing_state_out_of_known_no_event() -> None:
    m = module()
    frame = pd.DataFrame({
        "state": ["EVENT_PRESENT_VALID", "KNOWN_NO_EVENT", "ISSUER_UNMAPPED"],
        "target": [0.03, 0.01, -0.99],
    })
    result = m.binary_return_stats(frame)
    assert result["event_positive_count"] == 1
    assert result["known_no_event_count"] == 1
    assert result["event_positive_vs_known_no_event_spread"] == pytest.approx(0.02)
    assert result["known_state_coverage"] == pytest.approx(2 / 3)


def test_displacement_keeps_missing_removed_state_in_other_not_zero_event() -> None:
    m = module()
    date = pd.Timestamp("2023-01-03")
    rows = []
    for rank in range(1, 22):
        missing = rank == 20
        added = rank == 21
        a2_pct = (21 - rank + 1) / 21
        score = np.nan if missing else 0.8 * a2_pct + (0.15 if added else 0.0)
        rows.append({
            "signal_date": date, "ticker": f"T{rank:02d}", "split": "DEVELOPMENT",
            "a2_rank": rank, "combined_rank": (rank if rank < 20 else (20 if added else np.nan)),
            "combined_score": score, "raw_a2_term": 0.8 * a2_pct,
            "binary_event_term": (0.1 if added else (np.nan if missing else 0.0)),
            "within_event_intensity_term": (0.05 if added else (np.nan if missing else 0.0)),
            "event_present": bool(added), "state": ("ISSUER_UNMAPPED" if missing else ("EVENT_PRESENT_VALID" if added else "KNOWN_NO_EVENT")),
            "target": rank / 1000, "latest_event_age_days": (5.0 if added else np.nan),
        })
    pairs, _ = m.selection_displacement(pd.DataFrame(rows))
    assert len(pairs) == 1
    assert pairs.iloc[0].attribution_category == "OTHER_OR_TIE"
    assert pairs.iloc[0].removed_state == "ISSUER_UNMAPPED"
    assert pd.isna(pairs.iloc[0].total_score_margin)
