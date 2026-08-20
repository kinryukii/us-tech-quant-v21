from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.v22 import fast_a2_r0g1_dynamic_pit_13f_universe_reconstruction_and_exact_r4_rerun as run
from scripts.v22 import pit_13f_reconstruction_r1 as pit


def _filings() -> pd.DataFrame:
    return pd.DataFrame([
        {"manager":"M","cik":"1","accession":"A","form_type":"13F-HR","report_period":"2023-03-31","accepted_timestamp":"2023-05-15T19:00:00Z","sha256":"a"*64,"parse_status":"PASS","amendment_type":""},
    ])


def _holding(**overrides) -> dict:
    row = {"manager":"M1","cik":"0000000001","accession":"A","accepted_timestamp":"2023-05-15T19:00:00Z","reported_value":20.0,"manager_total_reported_value":100.0,"security_id":"S1","cusip":"CUSIP1","ticker":"AAA","class":"COM","put_call":""}
    row.update(overrides)
    return row


def test_report_period_is_not_availability_date_and_acceptance_controls_use():
    filing = _filings().iloc[0]
    assert filing.report_period == "2023-03-31"
    assert not pit.filing_is_public_for_signal(filing.accepted_timestamp, "2023-05-12")
    assert pit.filing_is_public_for_signal(filing.accepted_timestamp, "2023-05-15")


def test_after_close_filing_moves_to_next_session():
    sessions = ["2023-05-15", "2023-05-16"]
    assert pit.first_legal_signal_session("2023-05-15T20:30:00Z", sessions) == pd.Timestamp("2023-05-16")


def test_missing_or_naive_accepted_timestamp_fails_closed():
    with pytest.raises(pit.Pit13FContractError, match="TIMEZONE"):
        pit.accepted_utc("2023-05-15 15:00:00")


def test_manager_first_filing_is_not_backfilled():
    assert pit.latest_legal_filings(_filings(), "2023-05-12").empty


def test_amendment_restatement_replaces_and_does_not_double_count():
    filings = pd.DataFrame([
        {"accession":"A","form_type":"13F-HR","accepted_timestamp":"2023-05-15T19:00:00Z","amendment_type":""},
        {"accession":"B","form_type":"13F-HR/A","accepted_timestamp":"2023-05-16T19:00:00Z","amendment_type":"RESTATEMENT"},
    ])
    holdings = pd.DataFrame([_holding(accession="A",security_id="OLD"), _holding(accession="B",security_id="NEW")])
    got = pit.apply_amendment_semantics(filings, holdings)
    assert got.security_id.tolist() == ["NEW"]


def test_additional_and_confidentially_delayed_holding_appears_only_at_amendment():
    filings = pd.DataFrame([
        {"accession":"A","form_type":"13F-HR","accepted_timestamp":"2023-05-15T19:00:00Z","amendment_type":""},
        {"accession":"B","form_type":"13F-HR/A","accepted_timestamp":"2023-06-20T19:00:00Z","amendment_type":"ADD_NEW_HOLDINGS"},
    ])
    holdings = pd.DataFrame([_holding(accession="A",security_id="S1"), _holding(accession="B",security_id="S2",cusip="CUSIP2")])
    assert pit.apply_amendment_semantics(filings.iloc[:1], holdings).security_id.tolist() == ["S1"]
    assert set(pit.apply_amendment_semantics(filings, holdings).security_id) == {"S1","S2"}


def test_ambiguous_amendment_fails_closed():
    filings = pd.DataFrame([{"accession":"B","form_type":"13F-HR/A","accepted_timestamp":"2023-06-20T19:00:00Z","amendment_type":"UNKNOWN"}])
    with pytest.raises(pit.Pit13FContractError, match="AMBIGUOUS"):
        pit.apply_amendment_semantics(filings, pd.DataFrame([_holding(accession="B")]))


def test_same_cusip_multi_manager_union_is_deduplicated_and_counts_managers():
    holdings = pd.DataFrame([_holding(), _holding(manager="M2",cik="0000000002",accession="B",reported_value=30.0)])
    got = pit.build_raw_union(holdings)
    assert len(got) == 1 and got.iloc[0].manager_count == 2
    assert got.iloc[0].aggregate_reported_value == 50.0
    assert got.iloc[0].max_manager_portfolio_weight == pytest.approx(0.3)


def test_ticker_only_identity_collision_guard():
    with pytest.raises(pit.Pit13FContractError, match="TICKER_ONLY"):
        pit.canonical_security_key({"ticker":"AAA"})


def test_put_and_call_do_not_create_stock_candidate():
    assert pit.classify_instrument(_holding(put_call="PUT")) == "OPTION"
    assert not pit.eligible_holding(_holding(put_call="CALL"))


def test_unsupported_instrument_is_ineligible():
    assert not pit.eligible_holding(_holding(**{"class":"NOTE"}))


def test_raw_union_at_or_below_cap_is_not_capped():
    raw = pd.DataFrame([{"canonical_security_id":"A","manager_count":1,"max_manager_portfolio_weight":.1,"aggregate_reported_value":1}])
    final, excluded = pit.apply_universe_cap(raw, 900)
    assert not final.cap_applied.any() and excluded.empty


def test_raw_union_above_cap_is_strict_top900_with_deterministic_tie_break():
    raw = pd.DataFrame([{"canonical_security_id":f"S{i:04d}","manager_count":1,"max_manager_portfolio_weight":.1,"aggregate_reported_value":1} for i in range(905,0,-1)])
    final, excluded = pit.apply_universe_cap(raw, 900)
    assert len(final) == 900 and len(excluded) == 5
    assert final.canonical_security_id.iloc[0] == "S0001" and excluded.canonical_security_id.iloc[0] == "S0901"


@pytest.mark.parametrize("column", ["a1_score","a2_prediction","target","future_return","pnl"])
def test_cap_rule_rejects_model_or_outcome_columns(column):
    raw = pd.DataFrame([{"canonical_security_id":"A","manager_count":1,"max_manager_portfolio_weight":.1,"aggregate_reported_value":1,column:0}])
    with pytest.raises(pit.Pit13FContractError, match="CAP_MODEL_OR_OUTCOME"):
        pit.apply_universe_cap(raw)


def test_dynamic_ranking_is_within_current_pit_universe():
    scores = pd.DataFrame({"signal_date":["2023-01-03"]*3,"canonical_security_id":["A","B","C"],"score":[3.,2.,9.]})
    universe = pd.DataFrame({"signal_date":["2023-01-03"]*2,"canonical_security_id":["A","B"]})
    got = pit.rank_scores_within_universe(scores, universe, "score")
    assert got.canonical_security_id.tolist() == ["A","B"] and got.dynamic_rank.tolist() == [1,2]


def test_missing_dynamic_score_fails_closed():
    scores = pd.DataFrame({"signal_date":["2023-01-03"],"canonical_security_id":["A"],"score":[3.]})
    universe = pd.DataFrame({"signal_date":["2023-01-03"]*2,"canonical_security_id":["A","B"]})
    with pytest.raises(pit.Pit13FContractError, match="COVERAGE"):
        pit.rank_scores_within_universe(scores, universe, "score")


def test_same_ticker_date_raw_score_is_not_mutated_by_ranker():
    scores = pd.DataFrame({"signal_date":["2023-01-03"],"canonical_security_id":["A"],"score":[3.14159]})
    universe = scores[["signal_date","canonical_security_id"]]
    got = pit.rank_scores_within_universe(scores, universe, "score")
    assert got.score.iloc[0] == scores.score.iloc[0]


def test_target_maturity_overlap_detection():
    assert pit.audit_target_maturity("2023-01-03","2022-12-01","2022-12-30") == "PASS"
    assert pit.audit_target_maturity("2023-01-03","2022-12-01","2023-01-03") == "FAIL_TARGET_MATURITY_OVERLAP"


def test_duplicate_accession_cache_rejected():
    frame = pd.concat([_filings(), _filings()], ignore_index=True)
    with pytest.raises(pit.Pit13FContractError, match="DUPLICATED"):
        pit.validate_filing_manifest(frame)


def test_legacy_non_authoritative_manager_config_is_30_unique_and_preserved():
    config = run.load_legacy_config()
    assert config["classification"] == "LEGACY_RESEARCH_ONLY"
    assert config["active_authoritative"] is False
    assert config["authoritative_for_holdings_ingestion"] is False
    assert len(config["managers"]) == 30
    assert len({row["cik"] for row in config["managers"]}) == 30


def test_authoritative_manager_config_is_exactly_24_and_excludes_situational():
    path = Path(__file__).parents[2] / "config/v22/authoritative_24_manager_master_r1.json"
    config = pit.load_authoritative_manager_config(path)
    ciks = {pit.normalized_cik(row["cik"]) for row in config["managers"]}
    assert len(ciks) == config["manager_count"] == 24
    assert pit.SITUATIONAL_AWARENESS_CIK not in ciks


def test_top100_per_manager_is_qualifying_and_deterministic():
    rows = [_holding(security_id=f"S{i:03d}", cusip=f"C{i:03d}", reported_value=float(200-i)) for i in range(105)]
    rows.append(_holding(security_id="OPTION", cusip="OPTION", put_call="CALL", reported_value=999.0))
    selected = pit.select_top100_qualifying_holdings(pd.DataFrame(rows))
    assert len(selected) == 100
    assert selected.manager_rank.max() == 100
    assert "OPTION" not in set(selected.security_id)


def test_authoritative_merged_universe_cap_is_900_and_deterministic():
    raw = pd.DataFrame([{"canonical_security_id":f"S{i:04d}","manager_count":1,"max_manager_portfolio_weight":.1,"aggregate_reported_value":1} for i in range(905,0,-1)])
    first, excluded = pit.apply_universe_cap(raw, pit.AUTHORITATIVE_UNIVERSE_CAP)
    second, _ = pit.apply_universe_cap(raw.sample(frac=1, random_state=7), pit.AUTHORITATIVE_UNIVERSE_CAP)
    assert len(first) == 900 and len(excluded) == 5
    assert first.canonical_security_id.tolist() == second.canonical_security_id.tolist()


def _authoritative_filings_and_ciks():
    config = pit.load_authoritative_manager_config(Path(__file__).parents[2] / "config/v22/authoritative_24_manager_master_r1.json")
    ciks = [row["cik"] for row in config["managers"]]
    filings = pd.DataFrame({"quarter":["2025Q4"]*24,"cik":ciks,"accepted_timestamp":["2026-02-13T21:00:00Z"]*23+["2026-02-17T21:00:00Z"]})
    return filings, ciks


def test_latest_filing_plus_five_us_trading_sessions_controls_activation():
    filings, ciks = _authoritative_filings_and_ciks()
    sessions = pd.bdate_range("2026-02-17", "2026-03-03")
    got = pit.authoritative_quarter_activations(filings, ciks, sessions)
    assert got.iloc[0].effective_date == pd.Timestamp("2026-02-24")


def test_prior_quarter_remains_active_before_authoritative_switch():
    activations = pd.DataFrame({"quarter":["2025Q3","2025Q4"],"effective_date":["2025-11-24","2026-02-24"]})
    got = pit.active_quarter_ledger(["2026-02-23","2026-02-24"], activations)
    assert got.active_quarter.tolist() == ["2025Q3", "2025Q4"]


def test_incomplete_authoritative_quarter_fails_and_situational_cannot_substitute():
    filings, ciks = _authoritative_filings_and_ciks()
    replacement = filings.iloc[:-1].copy()
    replacement.loc[len(replacement)] = ["2025Q4", pit.SITUATIONAL_AWARENESS_CIK, "2026-02-17T21:00:00Z"]
    with pytest.raises(pit.Pit13FContractError, match="INCOMPLETE"):
        pit.authoritative_quarter_activations(replacement, ciks, pd.bdate_range("2026-02-17", "2026-03-03"))


def test_missing_historical_price_coverage_excludes_candidate_without_future_fill():
    history = pd.DataFrame({"canonical_security_id":["A","A","B"],"date":["2025-01-01","2025-01-02","2025-01-02"]})
    eligible, excluded = pit.eligible_candidates_asof(["A","B"], history, "2025-01-02", 2)
    assert eligible == ["A"] and excluded == ["B"]


def test_future_price_availability_cannot_change_past_candidate_eligibility():
    history = pd.DataFrame({"canonical_security_id":["B","B"],"date":["2025-01-02","2025-02-01"]})
    before = pit.eligible_candidates_asof(["B"], history.iloc[:1], "2025-01-02", 2)
    after = pit.eligible_candidates_asof(["B"], history, "2025-01-02", 2)
    assert before == after == ([], ["B"])


def test_no_per_manager_branching_or_network_model_fit_calls_in_sources():
    for path in (run.MODULE_PATH, run.SCRIPT_PATH):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert 'if manager ==' not in source.lower()
        calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        assert "fit" not in calls
        assert not any(name in source for name in ("requests.get", "urllib.request", "selenium", "playwright"))


def test_frozen_corporate_action_and_execution_policy_hashes_are_unchanged():
    assert run.sha256_file(run.R0F1_POLICY) == run.EXPECTED_CA_POLICY_SHA256
    assert run.EXECUTION_POLICY.is_file()


def test_stop_preflight_has_zero_model_fit_predict_and_post2025_reads():
    result = run.build_stop_result()["summary"]
    assert result["MODEL_FIT_COUNT"] == result["MODEL_PREDICT_CALL_COUNT"] == 0
    assert result["POST2025_TARGET_READ_COUNT"] == result["POST2025_OUTCOME_READ_COUNT"] == 0
    assert result["PROSPECTIVE_SHADOW_CHANGED"] is False


def test_stop_does_not_fabricate_dynamic_economic_result():
    summary = run.build_stop_result()["summary"]
    assert summary["FAST_A2_R0G1_STATUS"] == "STOP"
    assert summary["DYNAMIC_PIT_A2_CAGR"] is None
    assert summary["HISTORICAL_RESULT_MATERIALIZED"] is False


def test_deterministic_stop_audit_fingerprint():
    a = run.build_stop_result()["summary"]
    b = run.build_stop_result()["summary"]
    assert a["RUN1_FINGERPRINT"] == b["RUN2_FINGERPRINT"]


def test_anti_bloat_contract():
    summary = run.build_stop_result()["summary"]
    assert summary["NEW_REPOSITORY_FILE_COUNT"] <= 4
    assert summary["NEW_DATABASE_COUNT"] == summary["NEW_FRAMEWORK_COUNT"] == 0
    assert summary["PER_MANAGER_SCRIPT_COUNT"] == summary["PER_MANAGER_PARSER_COUNT"] == 0
    assert summary["RAW_SEC_FILE_IN_REPOSITORY_COUNT"] == 0
