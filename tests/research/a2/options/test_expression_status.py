"""Summary-only counterexamples; all rows and wealth values are invented."""
from copy import deepcopy
from math import isnan

import pytest

from scripts.research.a2.options import expression
from scripts.research.a2.options.contracts import clock


def invented_result(values=(.01,), *, grade="REAL_HISTORICAL_QUOTES"):
    result = {"opportunities": [], "outcomes": [], "acquisition_status": "COMPLETE"}
    for i, value in enumerate(values):
        stamp = str(clock("2025-03-03", i))
        uid = f"INVENTED:{i}"
        result["opportunities"].append(dict(decision_id=str(i), underlying_uid=uid,
            decision_at=stamp, eligible=True, valid_opportunity=True, evidence_grade=grade))
        common = dict(decision_id=str(i), underlying_uid=uid, decision_at=stamp,
            initial_cash=10000., cash=10000., quantity=0., unresolved=False,
            status="CLOSED", reason="FIXED_EXIT", entry_at=stamp, evidence_grade=grade)
        result["outcomes"].extend([
            common | dict(arm="LONG_CALL", net_wealth=10000. * (1 + value)),
            common | dict(arm="STOCK", net_wealth=10000.),
            common | dict(arm="DECISION_DELTA_MATCHED_FUNDED_STOCK", net_wealth=10000.,
                          status="NOT_OPENED", reason="ZERO_QUANTITY", entry_at=None,
                          delta_identifiable=False),
        ])
    return result


def primary(summary):
    return next(r for r in summary["comparisons"]
                if r["arm"] == "STOCK" and r["population"] == "ALL_VALID_OPPORTUNITIES")


def unavailable_call(result, index=0, reason="NO_DECISION_QUOTE"):
    row = next(r for r in result["outcomes"] if r["decision_id"] == str(index) and r["arm"] == "LONG_CALL")
    row.update(status="NOT_OPENED", reason=reason, net_wealth=10000., entry_at=None)


def test_real_complete_main_comparison_does_not_require_delta_or_result_sign():
    for value in (-.01, 0., .01):
        summary = expression.paired_summary(invented_result((value,)))
        assert primary(summary)["paired_rows"] == 1
        assert primary(summary)["mean_date_increment"] == pytest.approx(value)
        assert summary["main_comparison_status"] == "DESCRIPTIVE_COMPLETE"
        assert summary["economic_verdict"] == "DESCRIPTIVE_COMPLETE"
        assert summary["delta_comparison_status"] == "NOT_IDENTIFIABLE"
        assert summary["production_acceptance"] == "NOT_ASSESSED"
    synthetic = expression.paired_summary(invented_result(grade="SYNTHETIC"))
    assert synthetic["economic_verdict"] == "NOT_IDENTIFIABLE"


def test_partial_acquisition_preserves_nominal_population_without_dummy_outcomes():
    result = invented_result()
    result["nominal_opportunities"] = 15000
    summary = expression.paired_summary(result)
    assert summary["main_comparison_status"] == "CONDITIONAL_COMPUTABLE"
    assert summary["economic_verdict"] == "NOT_IDENTIFIABLE"
    assert summary["nominal_opportunities"] == 15000
    assert summary["evaluated_opportunities"] == 1
    assert summary["data_unidentifiable_opportunities"] == 14999
    assert primary(summary)["paired_rows"] == 1
    assert len(summary["pairs"]) == 3  # Same pair in the three original populations.


def test_closed_subset_does_not_self_certify_acquisition_completeness():
    result = invented_result()
    del result["acquisition_status"]
    summary = expression.paired_summary(result)
    assert summary["main_comparison_status"] == "CONDITIONAL_COMPUTABLE"
    assert summary["full_population_status"] == "LIMITED"
    assert summary["economic_verdict"] == "NOT_IDENTIFIABLE"


@pytest.mark.parametrize("reason", ["NO_DECISION_QUOTE", "QUOTE_IDENTITY", "QUOTE_UNITS",
    "STALE_OR_DELAYED_QUOTE", "NON_EXECUTABLE_EVIDENCE", "ENTRY_NOT_YET_AVAILABLE"])
def test_missing_or_invalid_inputs_are_not_cash_even_with_complete_window(reason):
    result = invented_result()
    unavailable_call(result, reason=reason)
    result["opportunities"][0]["entry_window_complete_by_arm"] = {"LONG_CALL": True}
    result["opportunities"][0]["entry_window_qualified_by_arm"] = {"LONG_CALL": True}
    summary = expression.paired_summary(result)
    assert primary(summary)["paired_rows"] == 0
    assert primary(summary)["mean_date_increment"] is None
    assert summary["data_unidentifiable_opportunities"] == 1
    assert summary["active_no_trade_calls"] == 0


def test_no_contract_is_known_no_trade_only_with_complete_qualified_historical_universe():
    result = invented_result()
    unavailable_call(result, reason="NO_ELIGIBLE_CONTRACT")
    result["opportunities"][0]["eligible"] = False
    assert primary(expression.paired_summary(result))["paired_rows"] == 0
    result["opportunities"][0]["contract_universe_complete"] = True
    assert primary(expression.paired_summary(result))["paired_rows"] == 0
    result["opportunities"][0]["contract_universe_qualified"] = True
    summary = expression.paired_summary(result)
    assert primary(summary)["paired_rows"] == 1
    assert primary(summary)["known_no_trade_pairs"] == 1
    assert summary["active_no_trade_calls"] == 1


def test_missing_data_and_unresolved_position_are_counted_separately_without_mutation():
    result = invented_result((.01, .02, .03))
    unavailable_call(result, index=1)
    row = next(r for r in result["outcomes"] if r["decision_id"] == "2" and r["arm"] == "LONG_CALL")
    row.update(status="UNRESOLVED", reason="LIFECYCLE_UNRESOLVED", unresolved=True,
               net_wealth=None, cash=9399., quantity=1.)
    before = deepcopy(result)
    summary = expression.paired_summary(result)
    assert result == before
    assert summary["data_unidentifiable_opportunities"] == 1
    assert summary["unresolved_call_positions"] == 1
    assert summary["opened_calls"] == 2 and summary["closed_calls"] == 1
    assert primary(summary)["exclusions"] == {"DATA_NOT_IDENTIFIABLE": 1, "UNRESOLVED": 1}
    assert summary["main_comparison_status"] == "CONDITIONAL_COMPUTABLE"
    assert summary["economic_verdict"] == "NOT_IDENTIFIABLE"


def test_date_weighting_and_missing_date_counts_keep_original_estimator():
    result = invented_result((.01, .03, .10, .90))
    stamp = result["opportunities"][0]["decision_at"]
    result["opportunities"][1]["decision_at"] = stamp
    for row in result["outcomes"]:
        if row["decision_id"] == "1":
            row["decision_at"] = stamp
    unavailable_call(result, index=3)
    comparison = primary(expression.paired_summary(result))
    assert comparison["mean_date_increment"] == pytest.approx(.06)
    assert comparison["paired_rows"] == 3
    assert comparison["decision_dates"] == 2
    assert comparison["population_decision_dates"] == 3
    assert comparison["missing_decision_dates"] == 1


def test_bootstrap_axis_keeps_missing_boundary_dates_and_40_observed_minimum(monkeypatch):
    received = []
    def interval(daily):
        received.append(daily)
        return [.001, .002]
    monkeypatch.setattr(expression, "date_interval", interval)
    result = invented_result((.01,) * 42)
    unavailable_call(result, index=0)
    unavailable_call(result, index=41)
    comparison = primary(expression.paired_summary(result))
    assert comparison["decision_dates"] == 40
    assert comparison["population_decision_dates"] == 42
    assert received and all(len(daily) == 42 for daily in received)
    assert all(sum(isnan(value) for value in daily.values()) == 2 for daily in received)
    received.clear()
    unavailable_call(result, index=1)
    comparison = primary(expression.paired_summary(result))
    assert comparison["decision_dates"] == 39 and comparison["exploratory_95_interval"] is None
    assert received == []


def test_no_acquired_inputs_do_not_invent_cash_or_economic_run():
    result = {"opportunities": [], "outcomes": [], "nominal_opportunities": 15000}
    summary = expression.paired_summary(result)
    assert summary["nominal_opportunities"] == summary["data_unidentifiable_opportunities"] == 15000
    assert summary["evaluated_opportunities"] == summary["opened_calls"] == 0
    assert summary["pairs"] == [] and summary["economic_verdict"] == "NOT_IDENTIFIABLE"
