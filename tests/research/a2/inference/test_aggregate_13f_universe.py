"""Synthetic full-holdings ranking and information-boundary contracts only."""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from scripts.research.a2.inference.aggregate_13f_universe import (
    Aggregate13FContractError, aggregate_snapshot_top100,
)


def classifier(issuer, title, shares_type, put_call):
    # The caller supplies the frozen owner in production. This deliberately small
    # stub isolates aggregation from the separately owned instrument policy.
    return (title == "COM" and shares_type == "SH" and not put_call, "SYNTHETIC")


def inputs():
    registry = pd.DataFrame([{"manager_id": manager, "cik": str(index + 1), "enabled": True,
        "active_from_quarter": "2020Q1", "active_to_quarter": "", "top_n": 100,
        "protected_top_n": 20, "manager_weight": 1.0, "required_for_gate": True}
        for index, manager in enumerate(("m1", "m2"))])
    rows = []
    for index, manager in enumerate(("m1", "m2")):
        for number in range(100):
            rows.append({"snapshot_id": "initial", "quarter": "2025Q3", "manager_id": manager,
                "source_row_id": str(number), "source_sha256": ("a" if index == 0 else "b") * 64,
                "cusip": f"{index * 100 + number:09d}", "issuer_name": "Synthetic Corp",
                "title_of_class": "COM", "ssh_prnamt_type": "SH", "put_call": "", "value_usd": "100"})
        rows.append({**rows[-1], "source_row_id": "shared", "cusip": "999999999", "value_usd": "60"})
    holdings = pd.DataFrame(rows)
    evidence = pd.DataFrame([{"snapshot_id": "initial", "quarter": "2025Q3", "manager_id": manager,
        "holdings_scope": "FULL_AS_FILED_HOLDINGS", "full_report_complete": True,
        "amendment_resolved": True, "full_row_count": 101, "full_value_usd": "10060",
        "source_sha256": ("a" if index == 0 else "b") * 64,
        "qualification_sha256": "c" * 64, "unit_evidence_sha256": "d" * 64,
        "accepted_at": "2025-11-14T21:10:00Z", "qualification_available_at": "2025-11-14T21:10:00Z",
        "effective_at": "2025-11-21T14:30:00Z"}
        for index, manager in enumerate(("m1", "m2"))])
    return holdings, evidence, registry


def run(holdings=None, evidence=None, registry=None, **options):
    original = inputs()
    return aggregate_snapshot_top100(
        original[0] if holdings is None else holdings,
        original[1] if evidence is None else evidence,
        original[2] if registry is None else registry,
        quarter="2025Q3", snapshot_id=options.pop("snapshot_id", "initial"),
        decision_at="2025-11-24T21:00:00Z", classify_equity=options.pop("classify_equity", classifier), **options)


def test_full_holdings_find_stock_missing_from_every_manager_top100():
    holdings, evidence, registry = inputs()
    result = run(holdings, evidence, registry)
    assert result["members"].iloc[0].cusip == "999999999"
    assert result["members"].iloc[0].aggregate_value_usd == Decimal("120")
    assert len(result["ranking"]) == 201 and len(result["members"]) == 100
    truncated = holdings.loc[holdings.source_row_id.ne("shared")]
    with pytest.raises(Aggregate13FContractError, match="ROW_COUNT"):
        run(truncated, evidence, registry)


def test_amount_ties_use_historical_cusip_and_input_order_is_irrelevant():
    holdings, evidence, registry = inputs()
    first = run(holdings, evidence, registry)["members"]
    second = run(holdings.sample(frac=1, random_state=4), evidence.iloc[::-1], registry.iloc[::-1])["members"]
    pd.testing.assert_frame_equal(first, second)
    assert first.iloc[1:].cusip.tolist() == [f"{number:09d}" for number in range(99)]


def test_future_snapshot_append_cannot_revise_selected_vintage():
    holdings, evidence, registry = inputs()
    before = run(holdings, evidence, registry)
    future_rows = holdings.assign(snapshot_id="restatement", value_usd="500")
    future_evidence = evidence.assign(snapshot_id="restatement", full_value_usd="50500",
        accepted_at="2025-12-01T21:10:00Z", qualification_available_at="2025-12-01T21:10:00Z",
        effective_at="2025-12-08T14:30:00Z")
    joined_holdings = pd.concat([holdings, future_rows], ignore_index=True)
    joined_evidence = pd.concat([evidence, future_evidence], ignore_index=True)
    after = run(joined_holdings, joined_evidence, registry)
    pd.testing.assert_frame_equal(before["members"], after["members"])
    assert before["audit"] == after["audit"]
    with pytest.raises(Aggregate13FContractError, match="FUTURE"):
        run(joined_holdings, joined_evidence, registry, snapshot_id="restatement")


def test_missing_and_unregistered_managers_are_rejected():
    holdings, evidence, registry = inputs()
    with pytest.raises(Aggregate13FContractError, match="COHORT"):
        run(holdings.loc[holdings.manager_id.eq("m1")], evidence.iloc[:1], registry)
    with pytest.raises(Aggregate13FContractError, match="COHORT"):
        run(holdings.assign(manager_id="unknown"), evidence, registry)


@pytest.mark.parametrize("field,value,reason", [
    ("holdings_scope", "PER_MANAGER_TOP100", "TRUNCATED"),
    ("full_report_complete", False, "UNQUALIFIED"),
    ("amendment_resolved", False, "UNQUALIFIED"),
    ("unit_evidence_sha256", "", "EVIDENCE_MISSING"),
    ("source_sha256", "bad", "EVIDENCE_MISSING"),
    ("qualification_sha256", "bad", "EVIDENCE_MISSING"),
    ("full_value_usd", "10061", "TOTAL_MISMATCH"),
    ("full_value_usd", "NaN", "INVALID_USD"),
    ("accepted_at", "2025-11-14", "TIMEZONE"),
    ("qualification_available_at", "2025-12-01T00:00:00Z", "FUTURE"),
    ("effective_at", "2025-12-01T00:00:00Z", "FUTURE"),
])
def test_evidence_must_reconcile_and_be_legally_available(field, value, reason):
    holdings, evidence, registry = inputs()
    evidence.loc[0, field] = value
    with pytest.raises(Aggregate13FContractError, match=reason):
        run(holdings, evidence, registry)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "-1", True])
def test_nonfinite_negative_or_boolean_holdings_values_fail(value):
    holdings, evidence, registry = inputs()
    holdings["value_usd"] = holdings["value_usd"].astype(object)
    holdings.loc[0, "value_usd"] = value
    with pytest.raises(Aggregate13FContractError, match="INVALID_USD"):
        run(holdings, evidence, registry)


def test_duplicate_source_rows_and_manager_snapshots_fail():
    holdings, evidence, registry = inputs()
    with pytest.raises(Aggregate13FContractError, match="DUPLICATE_SOURCE_ROW"):
        run(pd.concat([holdings, holdings.iloc[:1]], ignore_index=True), evidence, registry)
    with pytest.raises(Aggregate13FContractError, match="DUPLICATE_MANAGER_SNAPSHOT"):
        run(holdings, pd.concat([evidence, evidence.iloc[:1]], ignore_index=True), registry)


def test_repeated_cusip_lines_aggregate_and_classifier_rejects_options_before_ranking():
    holdings, evidence, registry = inputs()
    duplicate = holdings.iloc[:1].copy().assign(source_row_id="split", value_usd="5")
    option = holdings.iloc[:1].copy().assign(source_row_id="option", cusip="888888888", value_usd="1000000", put_call="CALL")
    holdings = pd.concat([holdings, duplicate, option], ignore_index=True)
    evidence.loc[0, ["full_row_count", "full_value_usd"]] = [103, "1010065"]
    result = run(holdings, evidence, registry)
    assert "888888888" not in set(result["ranking"].cusip)
    assert result["members"].iloc[1].aggregate_value_usd == Decimal("105")
    assert result["audit"]["full_source_rows"] == 204
    assert result["audit"]["eligible_source_rows"] == 203


def test_coverage_and_manager_weight_cannot_change_top100_or_backfill_101():
    holdings, evidence, registry = inputs()
    expected = run(holdings, evidence, registry)["members"]
    holdings["mapping_verified"] = False
    holdings["price_available"] = False
    holdings["ticker"] = None
    holdings["manager_rank"] = 999
    registry["manager_weight"] = [99.0, 0.1]
    actual = run(holdings, evidence, registry)["members"]
    pd.testing.assert_frame_equal(expected, actual)
    assert "000000099" not in set(actual.cusip)


def test_declared_zero_holdings_manager_and_small_pool_do_not_invent_members():
    holdings, evidence, registry = inputs()
    holdings = holdings.iloc[:1].copy()
    evidence.loc[0, ["full_row_count", "full_value_usd"]] = [1, "100"]
    evidence.loc[1, ["full_row_count", "full_value_usd"]] = [0, "0"]
    result = run(holdings, evidence, registry)
    assert len(result["members"]) == 1
    assert result["audit"]["roster"]["applicable_manager_count"] == 2


def test_quarter_effective_registry_does_not_require_future_manager():
    holdings, evidence, registry = inputs()
    future = registry.iloc[:1].copy().assign(manager_id="later", cik="3", active_from_quarter="2025Q4")
    result = run(holdings, evidence, pd.concat([registry, future], ignore_index=True))
    assert result["audit"]["roster"]["applicable_manager_ids"] == ["m1", "m2"]


# Consensus is a separate declared selection rule on the same qualified source.
# These fixtures and checks are synthetic; no source acquisition or research I/O.
def consensus_inputs(positions):
    from fractions import Fraction
    holdings, evidence, registry = inputs()
    row, proof = holdings.iloc[0].to_dict(), evidence.iloc[0].to_dict()
    rows, proofs, managers = [], [], []
    for index, (manager, entries) in enumerate(positions.items()):
        source_sha = str(index + 1) * 64
        for ordinal, entry in enumerate(entries):
            cusip, amount, *title = entry
            rows.append({**row, "manager_id": manager, "source_sha256": source_sha,
                "source_row_id": str(ordinal), "cusip": cusip, "value_usd": str(amount),
                "title_of_class": title[0] if title else "COM"})
        total = sum((Fraction(str(entry[1])) for entry in entries), Fraction(0))
        # Synthetic fixtures use integer values, exactly represented by Decimal.
        assert total.denominator == 1
        proofs.append({**proof, "manager_id": manager, "source_sha256": source_sha,
                       "full_row_count": len(entries), "full_value_usd": str(total.numerator)})
        managers.append({**registry.iloc[0].to_dict(), "manager_id": manager, "cik": str(index + 1)})
    return pd.DataFrame(rows, columns=holdings.columns), pd.DataFrame(proofs), pd.DataFrame(managers)


def consensus(holdings=None, evidence=None, registry=None):
    return run(holdings, evidence, registry, selection_rule="MANAGER_COUNT_WEIGHT_SUM")


def test_consensus_votes_outrank_absolute_dollars_and_use_all_holdings():
    result = consensus()
    # Shared security is rank 101 inside BOTH managers: truncation loses its votes.
    assert result["members"].iloc[0].cusip == "999999999"
    assert result["members"].iloc[0].manager_count == 2
    assert result["members"].iloc[0].holding_weight_sum_exact == "6/503"
    assert "amount_rank" not in result["members"]
    assert result["members"].consensus_rank.tolist() == list(range(1, 101))
    h, e, r = consensus_inputs({"m1": [("000000001", 1), ("000000002", 10**12)],
                               "m2": [("000000001", 1)]})
    assert consensus(h, e, r)["members"].iloc[0].cusip == "000000001"


def test_consensus_tie_uses_sum_of_full_eligible_manager_weights_not_dollars():
    h, e, r = consensus_inputs({"m1": [("000000001", 900), ("000000003", 1100)],
                               "m2": [("000000002", 50), ("000000004", 10)]})
    result = consensus(h, e, r)["ranking"]
    assert result.iloc[0].cusip == "000000002"
    assert result.iloc[0].holding_weight_sum_exact == "5/6"
    assert result.set_index("cusip").loc["000000001", "holding_weight_sum_exact"] == "9/20"


def test_consensus_denominator_excludes_rejected_instruments_without_changing_source_reconciliation():
    h, e, r = consensus_inputs({"m1": [("000000001", 9), ("000000002", 1),
                                       ("000000003", 99990, "FUND")],
                               "m2": [("000000001", 1)]})
    result = consensus(h, e, r)
    assert result["members"].iloc[0].holding_weight_sum_exact == "19/10"
    assert "000000003" not in set(result["ranking"].cusip)
    assert result["audit"]["full_source_rows"] == 4
    assert result["audit"]["eligible_source_rows"] == 3


def test_consensus_same_manager_cusip_is_one_vote_and_amounts_are_added():
    h, e, r = consensus_inputs({"m1": [("000000001", 20), ("000000001", 30), ("000000002", 50)],
                               "m2": [("000000001", 10), ("000000002", 90)]})
    result = consensus(h, e, r)["ranking"].set_index("cusip")
    assert result.loc["000000001", "manager_count"] == 2
    assert result.loc["000000001", "aggregate_value_usd"] == Decimal("60")
    assert result.loc["000000001", "holding_weight_sum_exact"] == "3/5"
    assert result.loc["000000002", "consensus_rank"] == 1


def test_consensus_rescaling_one_managers_entire_book_preserves_order_and_exact_weights():
    h, e, r = consensus_inputs({"m1": [("000000001", 90), ("000000002", 10)],
                               "m2": [("000000001", 5), ("000000002", 10)]})
    before = consensus(h, e, r)["ranking"]
    mask = h.manager_id.eq("m1")
    h.loc[mask, "value_usd"] = h.loc[mask, "value_usd"].map(lambda value: str(Decimal(value) * 1000000))
    e.loc[e.manager_id.eq("m1"), "full_value_usd"] = "100000000"
    r["manager_weight"] = [99.0, 0.1]
    after = consensus(h, e, r)["ranking"]
    columns = ["cusip", "manager_count", "consensus_rank", "holding_weight_sum", "holding_weight_sum_exact"]
    pd.testing.assert_frame_equal(before[columns], after[columns])
    assert not before.aggregate_value_usd.equals(after.aggregate_value_usd)


def test_consensus_fraction_order_is_not_changed_by_rounded_display():
    magnitude = 10**26
    h, e, r = consensus_inputs({"m1": [("000000001", magnitude), ("000000002", magnitude + 1)]})
    result = consensus(h, e, r)["ranking"]
    assert result.cusip.tolist() == ["000000002", "000000001"]
    assert result.holding_weight_sum.nunique() == 1
    assert result.holding_weight_sum_exact.nunique() == 2


def test_consensus_equal_votes_and_weights_use_cusip_independent_of_input_order():
    h, e, r = consensus_inputs({"m1": [("000000002", 50), ("000000001", 50)],
                               "m2": [("000000001", 50), ("000000002", 50)]})
    before = consensus(h, e, r)
    after = consensus(h.iloc[::-1], e.iloc[::-1], r.iloc[::-1])
    pd.testing.assert_frame_equal(before["ranking"], after["ranking"])
    assert before["ranking"].cusip.tolist() == ["000000001", "000000002"]


def test_consensus_keeps_zero_disclosed_votes_but_rejects_undefined_denominators():
    h, e, r = consensus_inputs({"m1": [("000000001", 0), ("000000002", 100)],
                               "m2": [("000000001", 1)]})
    result = consensus(h, e, r)
    assert result["members"].iloc[0].cusip == "000000001"
    assert result["members"].iloc[0].manager_count == 2
    assert result["members"].iloc[0].holding_weight_sum_exact == "1/1"
    h, e, r = consensus_inputs({"m1": [("000000001", 0)]})
    with pytest.raises(Aggregate13FContractError, match="ZERO_ELIGIBLE"):
        consensus(h, e, r)
    # Existing amount mode continues to accept a disclosed zero-valued row.
    assert len(run(h, e, r)["members"]) == 1
    h, e, r = consensus_inputs({"m1": [("000000001", 100)], "m2": []})
    result = consensus(h, e, r)
    assert result["audit"]["roster"]["applicable_manager_count"] == 2
    assert result["members"].iloc[0].manager_count == 1


def test_consensus_coverage_fields_cannot_replace_rank100_with_rank101():
    h, e, r = inputs()
    expected = consensus(h, e, r)["members"]
    h["mapping_verified"], h["price_available"], h["ticker"] = False, False, None
    actual = consensus(h, e, r)["members"]
    pd.testing.assert_frame_equal(expected, actual)
    assert "000000099" not in set(actual.cusip)
    assert len(actual) == 100


def test_consensus_preserves_future_snapshot_boundary_and_full_cohort_requirement():
    h, e, r = inputs()
    before = consensus(h, e, r)
    future_rows = h.assign(snapshot_id="future", value_usd="500")
    future_evidence = e.assign(snapshot_id="future", full_value_usd="50500",
        accepted_at="2025-12-01T21:10:00Z", qualification_available_at="2025-12-01T21:10:00Z",
        effective_at="2025-12-08T14:30:00Z")
    after = consensus(pd.concat([h, future_rows]), pd.concat([e, future_evidence]), r)
    pd.testing.assert_frame_equal(before["members"], after["members"])
    assert before["audit"] == after["audit"]
    with pytest.raises(Aggregate13FContractError, match="COHORT"):
        consensus(h.loc[h.manager_id.eq("m1")], e.iloc[:1], r)
    with pytest.raises(Aggregate13FContractError, match="TRUNCATED"):
        consensus(h, e.assign(holdings_scope="PER_MANAGER_TOP100"), r)


def test_selection_rule_is_explicit_and_legacy_default_schema_is_preserved():
    result = run()
    explicit = run(selection_rule="AGGREGATE_USD")
    pd.testing.assert_frame_equal(result["members"], explicit["members"])
    assert result["audit"] == explicit["audit"]
    assert result["members"].columns.tolist() == ["snapshot_id", "quarter", "cusip",
        "aggregate_value_usd", "manager_count", "manager_ids", "amount_rank"]
    assert "selection_rule" not in result["audit"]
    with pytest.raises(Aggregate13FContractError, match="UNKNOWN_SELECTION"):
        run(selection_rule="UNDECLARED")



def initial_public_inputs():
    holdings,evidence,registry=inputs()
    evidence=evidence.drop(columns=['full_report_complete','amendment_resolved','accepted_at'])
    evidence['holdings_scope']='FULL_INITIAL_PUBLIC_AS_FILED_HOLDINGS'
    evidence['full_public_filing_complete']=True
    evidence['amendments_handled']=False
    evidence['filing_form']='13F-HR'
    evidence['initial_public_filing']=True
    evidence['filing_date']='2025-11-14'
    evidence['disclosure_available_by']='2025-11-15T05:00:00Z'
    evidence['qualification_available_at']='2025-11-15T05:00:00Z'
    return holdings,evidence,registry


def test_initial_public_policy_is_explicit_and_reuses_consensus_ranking():
    h,e,r=initial_public_inputs()
    result=run(h,e,r,selection_rule='MANAGER_COUNT_WEIGHT_SUM',
               filing_policy='INITIAL_PUBLIC_AS_FILED_NO_AMENDMENT_BACKFILL')
    assert result['members'].iloc[0].cusip=='999999999'
    assert result['audit']['amendments_handled'] is False
    assert result['audit']['institution_total_assets_complete'] is False
    with pytest.raises(Aggregate13FContractError,match='REQUIRED_COLUMNS_MISSING'):
        run(h,e,r,selection_rule='MANAGER_COUNT_WEIGHT_SUM')


@pytest.mark.parametrize('field,value',[
    ('amendments_handled',True),('filing_form','13F-HR/A'),
    ('initial_public_filing',False),('full_public_filing_complete',False),
    ('amendment_resolved',True),
])
def test_initial_public_policy_rejects_fabricated_or_amendment_claims(field,value):
    h,e,r=initial_public_inputs()
    with pytest.raises(Aggregate13FContractError,match='INITIAL_PUBLIC_FILING_POLICY_UNQUALIFIED'):
        run(h,e.assign(**{field:value}),r,selection_rule='MANAGER_COUNT_WEIGHT_SUM',
            filing_policy='INITIAL_PUBLIC_AS_FILED_NO_AMENDMENT_BACKFILL')


def test_initial_public_policy_requires_conservative_publication_bound():
    h,e,r=initial_public_inputs()
    with pytest.raises(Aggregate13FContractError,match='CONSERVATIVE_DISCLOSURE_BOUND'):
        run(h,e.assign(disclosure_available_by='2025-11-14T21:00:00Z'),r,
            filing_policy='INITIAL_PUBLIC_AS_FILED_NO_AMENDMENT_BACKFILL')
