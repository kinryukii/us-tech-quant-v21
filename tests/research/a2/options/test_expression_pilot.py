"""Independent arithmetic and adversarial checks for the one frozen R1 template.

All observations below are invented. No provider, research cache or economic
file is read; CLI outputs must be directed to pytest's external temp root.
"""
from dataclasses import FrozenInstanceError, replace
from math import log, sqrt

import pandas as pd
import pytest

from scripts.research.a2.options.contracts import (
    Contract, Fees, Invalid, LifecycleEvent, Mark, Opportunity, Quote,
    clock, in_session, validate_opportunity, validate_quote,
)
from scripts.research.a2.options.expression import (
    decision_delta, evaluate, paired_summary, payoff_at_expiry, quote_at,
    select_contract, stock_path,
)
from scripts.common.storage_paths import resolve


D = "2025-03-03T14:45:00Z"
EXIT = "2025-03-10T13:45:00Z"


@pytest.fixture
def external_tmp_path():
    """Normal inherited directory permissions; preserve denied pytest residue."""
    import shutil
    import uuid
    root = resolve().cache_root.resolve()
    target = root / ("options-expression-b-test-" + uuid.uuid4().hex)
    target.mkdir()
    try:
        yield target
    finally:
        assert target.resolve().parent == root
        assert target.name.startswith("options-expression-b-test-")
        shutil.rmtree(target)


def opportunity(**changes):
    base = Opportunity("case", "UID", D, D, D, "SYNTHETIC_RAW_A2", 1, .5,
                       "2024-12-31T23:00:00Z", "synthetic-fold", 100., D)
    return replace(base, **changes)


def contract(**changes):
    base = Contract("CALL", "UID", 100., "2025-04-17",
                    "2025-04-17T20:00:00Z", D)
    return replace(base, **changes)


def quote(at=D, *, option=True, **changes):
    base = Quote("CALL" if option else "UID", "UID", at, at,
                 "2026-09-13T00:00:00Z", 5.9 if option else 99.9,
                 6. if option else 100., 1000., 1000., 100., at,
                 size_unit="CONTRACTS" if option else "SHARES")
    return replace(base, **changes)


def inputs():
    return dict(opportunities=(opportunity(),), contracts=(contract(),), quotes=(
        quote(delta=.5, delta_at=D, delta_source="SYNTHETIC",
              delta_kind="PROVIDER_HISTORICAL", delta_unit="PER_UNDERLYING_SHARE",
              delta_style="AMERICAN"),
        quote("2025-03-03T14:45:01Z"),
        quote("2025-03-10T13:45:01Z", bid=8., ask=8.1),
        quote(option=False), quote("2025-03-03T14:45:01Z", option=False),
        quote("2025-03-10T13:45:01Z", option=False, bid=103., ask=103.1),
    ))


def arm(result, name="LONG_CALL"):
    return next(r for r in result["outcomes"] if r["arm"] == name)


def test_hand_calculated_cash_ledger_and_funded_delta():
    result = evaluate(**inputs())
    call, stock, delta, cash = [arm(result, x) for x in
        ("LONG_CALL", "STOCK", "DECISION_DELTA_MATCHED_FUNDED_STOCK", "CASH")]
    # Independent arithmetic: 10000 - (100*6+1) + (100*8-1).
    assert call["net_wealth"] == 10198.
    assert call["net_pnl"] == 198.
    assert call["entry_fee"] == call["exit_fee"] == 1.
    assert call["status"] == "CLOSED" and call["quantity"] == 0
    # 99 shares: 10000 - 9900 - 1 + 10197 - 1.
    assert stock["net_wealth"] == 10295.
    assert delta["net_wealth"] == 10148.  # 50 shares and two minimum fees.
    assert delta["usage"] == "ANALYTICAL_ONLY"
    assert cash["net_wealth"] == 10000. and cash["action"] == "CASH"
    buy = next(r for r in result["ledger"] if r["arm"] == "LONG_CALL" and r["side"] == "BUY")
    assert buy["post_trade_cash"] == 9399.
    assert buy["contracts"] == 1 and buy["multiplier"] == 100
    for row in result["ledger"]:
        direction = -1 if row["side"] == "BUY" else 1
        assert row["post_trade_cash"] == pytest.approx(row["pre_trade_cash"] + direction * row["notional"] - row["fee"])


def test_terminal_payoff_is_arithmetic_only():
    # S0=K=100, premium=6, terminal S=103: (3-6)*100 = -300.
    assert payoff_at_expiry(103, 100, 6) == -300
    assert payoff_at_expiry(90, 100, 6) == -600
    assert payoff_at_expiry(110, 100, 6) == 400
    with pytest.raises(Invalid, match="PAYOFF_UNITS"):
        payoff_at_expiry(103, 100, 6, 1)


def test_stock_up_iv_down_is_model_scenario_only():
    from scripts.research.a2.options.cli import model_scenario
    row, = model_scenario()
    assert row["evidence_grade"] == "MODEL_SCENARIO"
    assert row["stock_pnl_per_share"] == 3
    assert row["call_pnl_per_share"] < 0 and row["iv_after"] < row["iv_before"]
    assert row["ordered_spot_effect"] + row["ordered_time_effect"] + row["ordered_iv_effect"] == pytest.approx(row["call_pnl_per_share"])
    assert "NOT_AMERICAN" in row["limitation"]


def test_unmatured_exit_cannot_be_realized():
    result = evaluate(**inputs(), evaluated_at="2025-03-05T15:00:00Z")
    call = arm(result)
    assert call["status"] == "UNRESOLVED" and call["action"] == "HOLD"
    assert call["reason"] == "LABEL_NOT_MATURE"
    assert call["net_wealth"] is None and call["cash"] == 9399 and call["quantity"] == 1
    assert not [r for r in result["ledger"] if r["side"] == "SELL"]


@pytest.mark.parametrize("changes,reason", [
    ({"signal_available_at": "2025-03-03T14:45:01Z"}, "FUTURE_SIGNAL"),
    ({"feature_available_at": "2025-03-03T14:45:01Z"}, "FUTURE_FEATURE"),
    ({"train_cutoff": D}, "TRAIN_CUTOFF"),
    ({"decision_at": "2026-01-02T14:45:00Z"}, "ECONOMIC_TIME_NOT_PRE2026"),
    ({"rank": 21}, "NOT_RAW_TOP20"),
    ({"spot_at": "2025-03-03T14:44:58Z"}, "DECISION_SPOT_CLOCK"),
    ({"capital": float("nan")}, "INVALID_BUDGET_OR_SPOT"),
    ({"score": True}, "INVALID_SCORE"),
])
def test_opportunity_rejections_are_localized(changes, reason):
    with pytest.raises(Invalid, match=reason):
        validate_opportunity(opportunity(**changes))
    result = evaluate(**(inputs() | {"opportunities": (opportunity(**changes),)}))
    assert len(result["opportunities"]) == 1
    assert reason in result["opportunities"][0]["reason"]
    assert result["ledger"] == []


def test_immutable_decision_input_has_no_label_fields():
    o = opportunity()
    with pytest.raises(FrozenInstanceError):
        o.spot = 200
    assert not {"label_end", "absolute_return", "mfe", "mae"} & set(o.__dataclass_fields__)


def test_calendar_dst_holiday_and_early_close():
    assert str(clock("2025-03-07")) == "2025-03-07 14:45:00+00:00"
    assert str(clock("2025-03-07", 1)) == "2025-03-10 13:45:00+00:00"
    assert in_session("2025-11-28T12:59:00-05:00")
    assert not in_session("2025-11-28T13:01:00-05:00")
    assert not in_session("2025-07-04T09:45:00-04:00")
    with pytest.raises(Invalid, match="ECONOMIC_TIME_NOT_PRE2026"):
        clock("2025-12-30", 5)


def test_expiry_then_atm_ties_and_input_order_invariance():
    cs = (contract(contract_id="later-atm", expiry="2025-04-18"),
          contract(contract_id="b", strike=101), contract(contract_id="a", strike=99))
    assert select_contract(opportunity(), cs).contract_id == "a"
    assert select_contract(opportunity(), tuple(reversed(cs))).contract_id == "a"
    # Equal distance to target 45 days: 44 beats 46, even with worse moneyness.
    cs = (contract(contract_id="46-atm", expiry="2025-04-18"),
          contract(contract_id="44-otm", expiry="2025-04-16",
                   last_trade_at="2025-04-16T20:00:00Z", strike=110))
    assert select_contract(opportunity(), cs).contract_id == "44-otm"


@pytest.mark.parametrize("changes", [
    {"right": "PUT"}, {"multiplier": 10}, {"multiplier": 100.0},
    {"currency": "HKD"}, {"deliverable": "ADJUSTED_BASKET"},
    {"adjustment_status": "ADJUSTED"}, {"exercise_style": "EUROPEAN"},
    {"settlement_type": "CASH"}, {"underlying_uid": "OTHER"},
    {"available_at": "2025-03-03T14:45:01Z"},
    {"last_trade_at": "2025-03-12T19:59:59Z"},
])
def test_ineligible_contract_does_not_relax_template(changes):
    assert select_contract(opportunity(), (contract(**changes),)) is None


def test_two_full_session_buffer_and_duplicate_contract():
    assert select_contract(opportunity(), (contract(last_trade_at="2025-03-12T20:00:00Z"),))
    with pytest.raises(Invalid, match="DUPLICATE_CONTRACT"):
        select_contract(opportunity(), (contract(), contract()))


@pytest.mark.parametrize("changes,reason", [
    ({"bid": 7.}, "CROSSED_OR_EMPTY_QUOTE"),
    ({"ask": None}, "INVALID_BIDASK"),
    ({"bid": float("nan")}, "INVALID_BIDASK"),
    ({"bid_size": -1.}, "INVALID_BIDASK"),
    ({"available_at": "2025-03-03T14:45:03Z"}, "STALE_OR_DELAYED_QUOTE"),
    ({"underlying_at": "2025-03-03T14:44:58Z"}, "UNDERLYING_CLOCK"),
    ({"underlying_at": "2025-03-03T14:45:01Z"}, "FUTURE_UNDERLYING_PRICE"),
    ({"size_unit": "SHARES"}, "QUOTE_UNITS"),
    ({"currency": "HKD"}, "QUOTE_UNITS"),
    ({"underlying_uid": "OTHER"}, "QUOTE_IDENTITY"),
    ({"quote_kind": "LAST"}, "NON_EXECUTABLE_QUOTE"),
    ({"evidence_grade": "INDICATIVE_OR_AGGREGATE"}, "NON_EXECUTABLE_EVIDENCE"),
])
def test_quote_fault_families(changes, reason):
    with pytest.raises(Invalid, match=reason):
        validate_quote(quote(**changes), "UID", "CALL", option=True, grade="SYNTHETIC")


def test_late_download_is_audit_time_not_historical_availability():
    validate_quote(quote(), "UID", "CALL", option=True, grade="SYNTHETIC")
    historical = quote(evidence_grade="REAL_HISTORICAL_QUOTES", feed_kind="HISTORICAL_BBO", source="TEST_PROVIDER")
    validate_quote(historical, "UID", "CALL", option=True, grade="REAL_HISTORICAL_QUOTES")
    with pytest.raises(Invalid, match="NON_EXECUTABLE"):
        validate_quote(replace(historical, feed_kind="INDICATIVE"), "UID", "CALL", option=True, grade="REAL_HISTORICAL_QUOTES")


def test_same_snapshot_cannot_both_select_and_fill():
    fixture = inputs()
    fixture["quotes"] = tuple(q for q in fixture["quotes"] if q.event_at != "2025-03-03T14:45:01Z")
    result = evaluate(**fixture)
    assert result["opportunities"][0]["eligible"]
    assert arm(result)["status"] == "NOT_OPENED"
    assert arm(result)["reason"] == "NO_EXECUTION_QUOTE"
    assert result["ledger"] == []


@pytest.mark.parametrize("changes,reason", [
    ({"ask_size": .5}, "ENTRY_SIZE_OR_BID"),
    ({"bid": 0}, "ENTRY_SIZE_OR_BID"),
    ({"available_at": "2025-03-03T14:45:04Z"}, "STALE_OR_DELAYED_QUOTE"),
])
def test_entry_whole_order_rejection(changes, reason):
    qs = (quote("2025-03-03T14:45:01Z", **changes),)
    selected, why = quote_at(qs, opportunity(), "CALL", pd.Timestamp(D), option=True, quantity=1)
    assert selected is None and why == reason


def test_first_valid_quote_and_permutation_determinism():
    fixture = inputs()
    result = evaluate(**fixture)
    shuffled = evaluate(**(fixture | {"quotes": tuple(reversed(fixture["quotes"]))}))
    assert shuffled == result
    early_bad = quote("2025-03-03T14:45:01Z", ask_size=0)
    good = quote("2025-03-03T14:45:02Z", ask=6.1)
    late = quote("2025-03-03T14:45:03Z", ask=5.95)
    chosen, reason = quote_at((late, early_bad, good), opportunity(), "CALL", pd.Timestamp(D), option=True, quantity=1)
    assert chosen == good and reason == "OK"
    with pytest.raises(Invalid, match="DUPLICATE_QUOTE"):
        quote_at((good, good), opportunity(), "CALL", pd.Timestamp(D), option=True, quantity=1)


def test_integer_budget_and_fill_cap_no_ex_post_capital():
    fixture = inputs()
    result = evaluate(**(fixture | {"opportunities": (opportunity(capital=600),)}))
    assert result["opportunities"][0]["minimum_one_contract_cash"] == 601
    assert arm(result)["reason"] == "ONE_CALL_OVER_BUDGET"
    assert arm(result)["action"] == "CASH" and arm(result)["quantity"] == 0
    fixture["opportunities"] = (opportunity(capital=601),)
    fixture["quotes"] = tuple(replace(q, ask=6.01) if q.instrument_id == "CALL" and q.event_at == "2025-03-03T14:45:01Z" else q for q in fixture["quotes"])
    result = evaluate(**fixture)
    assert result["opportunities"][0]["eligible"]
    assert arm(result)["reason"] == "FILL_OVER_BUDGET"
    assert arm(result)["cash"] == 601
    assert not [r for r in result["ledger"] if r["arm"] == "LONG_CALL"]


def test_more_cost_cannot_improve_wealth_and_minimum_fee_is_per_order():
    assert Fees().order(1, True) == 1.
    assert Fees().order(3, True) == pytest.approx(1.95)
    base = evaluate(**inputs())
    dearer = evaluate(**inputs(), fees=Fees(minimum=2, option_slippage=.1, stock_slippage=.01))
    for name in ("LONG_CALL", "STOCK", "DECISION_DELTA_MATCHED_FUNDED_STOCK"):
        assert arm(dearer, name)["net_wealth"] <= arm(base, name)["net_wealth"]
    assert arm(dearer)["net_wealth"] == pytest.approx(10176)


@pytest.mark.parametrize("failure", ["missing", "zero_bid", "zero_size", "adjustment", "expiration"])
def test_open_position_never_disappears_when_exit_fails(failure):
    fixture = inputs()
    if failure == "missing":
        fixture["quotes"] = tuple(q for q in fixture["quotes"] if not (q.instrument_id == "CALL" and q.event_at.startswith("2025-03-10")))
    elif failure in {"zero_bid", "zero_size"}:
        changes = {"bid": 0} if failure == "zero_bid" else {"bid_size": 0}
        fixture["quotes"] = tuple(replace(q, **changes) if q.instrument_id == "CALL" and q.event_at.startswith("2025-03-10") else q for q in fixture["quotes"])
    else:
        fixture["events"] = (LifecycleEvent("CALL", "2025-03-05T15:00:00Z", failure.upper()),)
    result = evaluate(**fixture)
    call = arm(result)
    assert len(result["opportunities"]) == 1 and len(result["outcomes"]) == 4
    assert call["action"] == "HOLD" and call["status"] == "UNRESOLVED"
    assert call["quantity"] == 1 and call["cash"] == 9399
    assert call["net_wealth"] is None and call["net_pnl"] is None
    entries = [r for r in result["ledger"] if r["arm"] == "LONG_CALL"]
    assert len(entries) == 1 and entries[0]["side"] == "BUY"
    assert paired_summary(result)["economic_verdict"] == "NOT_IDENTIFIABLE"
    assert paired_summary(result)["unresolved"] >= 1


def test_future_outcomes_do_not_select_a_different_contract():
    fixture = inputs()
    first = evaluate(**fixture)["opportunities"]
    fixture["quotes"] = tuple(replace(q, bid=200., ask=201.) if q.event_at.startswith("2025-03-10") else q for q in fixture["quotes"])
    fixture["events"] = (LifecycleEvent("CALL", "2025-03-05T15:00:00Z", "ADJUSTMENT"),)
    assert evaluate(**fixture)["opportunities"] == first


def test_delta_requires_historical_units_style_and_timestamp():
    q = inputs()["quotes"][0]
    assert decision_delta(q, D) == .5
    for changes in ({"delta_at": "2025-03-03T14:45:01Z"}, {"delta_kind": "MODEL"},
                    {"delta_style": "EUROPEAN"}, {"delta_unit": "PER_CONTRACT"},
                    {"delta_source": None}, {"delta": 1.1}):
        assert decision_delta(replace(q, **changes), D) is None
    fixture = inputs()
    fixture["quotes"] = tuple(replace(q, delta=None) for q in fixture["quotes"])
    result = evaluate(**fixture)
    assert arm(result)["status"] == arm(result, "STOCK")["status"] == "CLOSED"
    assert not arm(result, "DECISION_DELTA_MATCHED_FUNDED_STOCK")["delta_identifiable"]


def marks(prices=(100, 98, 101, 99, 104, 103)):
    return tuple(Mark("UID", str(clock("2025-03-03", i)), str(clock("2025-03-03", i)), p)
                 for i, p in enumerate(prices))


def test_stock_path_hand_calculation_is_label_not_prediction_or_fill():
    row = stock_path(opportunity(), marks(), 5, "2025-03-11T00:00:00Z")
    assert row["status"] == "COMPLETE"
    assert row["absolute_return"] == pytest.approx(.03)
    assert row["mfe"] == pytest.approx(.04) and row["mae"] == pytest.approx(-.02)
    assert row["first_positive_session"] == 2
    assert row["realized_volatility"] == pytest.approx(sqrt(sum(log(b/a)**2 for a, b in zip((100,98,101,99,104), (98,101,99,104,103)))))
    assert row["role"] == "POSTHOC_PATH_LABEL" and "NOT_EXECUTION" in row["clock"]
    assert stock_path(opportunity(), tuple(reversed(marks())), 5, "2025-03-11T00:00:00Z") == row


@pytest.mark.parametrize("failure,reason", [
    ("missing", "MISSING_PATH"), ("duplicate", "DUPLICATE_MARK"),
    ("action", "PATH_IDENTITY_OR_ACTION"), ("identity", "PATH_IDENTITY_OR_ACTION"),
    ("immature", "LABEL_NOT_MATURE"), ("future", "ECONOMIC_TIME_NOT_PRE2026"),
])
def test_path_maturity_and_identity_faults(failure, reason):
    data = list(marks())
    if failure == "missing":
        data.pop()
    elif failure == "duplicate":
        data.append(data[-1])
    else:
        changes = {"action_status": "ADJUSTED"} if failure == "action" else {"identity_status": "UNKNOWN"} if failure == "identity" else {"available_at": "2025-03-12T00:00:00Z"} if failure == "immature" else {"available_at": "2026-01-01T05:00:00Z"}
        data[-1] = replace(data[-1], **changes)
    row = stock_path(opportunity(), tuple(data), 5, "2025-03-11T00:00:00Z")
    assert row["status"] != "COMPLETE" and row["reason"] == reason
    assert "absolute_return" not in row


def test_duplicate_opportunities_rejected_and_same_date_not_independent():
    fixture = inputs()
    with pytest.raises(Invalid, match="DUPLICATE_OPPORTUNITY"):
        evaluate(**(fixture | {"opportunities": (opportunity(), opportunity())}))
    with pytest.raises(Invalid, match="DUPLICATE_UID_DATE"):
        evaluate(**(fixture | {"opportunities": (opportunity(), opportunity(decision_id="other"))}))
    result = evaluate(**fixture)
    extra = []
    for row in result["outcomes"]:
        extra.append(row | {"decision_id": "second", "underlying_uid": "UID2",
                           "net_wealth": row["net_wealth"] + (200 if row["arm"] == "LONG_CALL" else 0)})
    result["outcomes"] += extra
    result["opportunities"].append(result["opportunities"][0] | {"decision_id": "second", "underlying_uid": "UID2"})
    summary = paired_summary(result)
    comparison = next(r for r in summary["comparisons"] if r["arm"] == "STOCK")
    assert comparison["paired_rows"] == 2 and comparison["decision_dates"] == 1
    assert comparison["mean_date_increment"] == pytest.approx(.0003)
    assert comparison["exploratory_95_interval"] is None
    assert summary["effective_sample_size"] == "UNKNOWN"
    assert summary["nav"] == "NOT_RUN_NO_ACCOUNT_POLICY"


def test_bootstrap_fixed_seed_and_date_aggregation():
    result = evaluate(**inputs())
    template_rows = result["outcomes"]
    result["outcomes"] = []
    result["opportunities"] = []
    for i in range(45):
        at = str(clock("2025-03-03", i))
        result["opportunities"].append({"decision_id": str(i), "underlying_uid": "UID",
                                       "eligible": True, "valid_opportunity": True, "decision_at": at})
        result["outcomes"].extend(row | {"decision_id": str(i), "decision_at": at} for row in template_rows)
    first = paired_summary(result)
    result["outcomes"].reverse()
    second = paired_summary(result)
    assert second["comparisons"] == first["comparisons"]
    pair_key = lambda row: (row["decision_id"], row["arm"])
    assert sorted(second["pairs"], key=pair_key) == sorted(first["pairs"], key=pair_key)
    stock = next(r for r in first["comparisons"] if r["arm"] == "STOCK")
    assert stock["decision_dates"] == 45
    assert stock["exploratory_95_interval"] == pytest.approx([-.0097, -.0097])


def test_cli_consumes_adapter_and_rerun_deterministic(external_tmp_path, monkeypatch):
    from scripts.research.a2.options import cli
    tmp_path = external_tmp_path
    called = []
    original = cli.evaluate
    def record(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(cli, "evaluate", record)
    cli.run(mode="all", output=tmp_path)
    assert called, "User entrypoint must actually consume the new evaluator"
    tables = {p.name: p.read_bytes() for p in tmp_path.glob("*.csv")}
    assert tables, "End to end requires written evidence tables"
    cli.run(mode="all", output=tmp_path)
    assert tables == {p.name: p.read_bytes() for p in tmp_path.glob("*.csv")}


def test_unbound_real_input_is_rejected_before_open(external_tmp_path, monkeypatch):
    from pathlib import Path
    from scripts.research.a2.options import cli
    tmp_path = external_tmp_path
    forbidden = tmp_path / "unbound-2026-real.csv"
    opened = []
    original = Path.open
    def guarded(self, *args, **kwargs):
        if self == forbidden:
            opened.append(self)
            raise AssertionError("Forbidden input must never be opened")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded)
    assert cli.main(["--mode", "local", "--input", str(forbidden), "--output", str(tmp_path / "output")]) == 2
    assert opened == []


def test_review_f1_future_lifecycle_does_not_erase_completed_trade():
    fixture = inputs()
    expected = evaluate(**fixture)
    fixture["events"] = (LifecycleEvent("CALL", "2026-01-02T15:00:00Z", "EXPIRY"),)
    actual = evaluate(**fixture)
    assert actual["opportunities"] == expected["opportunities"]
    assert actual["outcomes"] == expected["outcomes"]
    assert actual["ledger"] == expected["ledger"]


@pytest.mark.parametrize("event", [
    LifecycleEvent("CALL", "UNKNOWN", "ADJUSTMENT"),
    LifecycleEvent("CALL", "2025-03-05T15:00:00Z", "UNKNOWN_EVENT_KIND"),
])
def test_review_f1_unknown_lifecycle_retains_funded_position(event):
    result = evaluate(**inputs(), events=(event,))
    call = arm(result)
    assert call["action"] == "HOLD" and call["unresolved"]
    assert call["cash"] == 9399 and call["quantity"] == 1
    assert call["net_wealth"] is None
    ledger = [r for r in result["ledger"] if r["arm"] == "LONG_CALL"]
    assert len(ledger) == 1 and ledger[0]["side"] == "BUY"
    assert arm(result, "STOCK")["net_wealth"] == 10295


def test_review_f2_option_identity_failure_keeps_stock_domain():
    fixture = inputs()
    fixture["contracts"] = (contract(), contract())
    result = evaluate(**fixture, marks=marks())
    assert arm(result, "STOCK")["net_wealth"] == 10295
    call = arm(result)
    assert call["action"] == "CASH" and call["status"] == "NOT_OPENED"
    assert "DUPLICATE_CONTRACT" in call["reason"]
    label = next(r for r in result["labels"] if r["horizon"] == 5)
    assert label["status"] == "COMPLETE" and label["absolute_return"] == pytest.approx(.03)
    assert any(r["arm"] == "STOCK" for r in result["ledger"])


def test_review_f3_uid_date_aliases_cannot_duplicate_opportunity():
    fixture = inputs()
    fixture["opportunities"] = (opportunity(), opportunity(
        decision_id="alias", decision_at="2025-03-03T09:45:00-05:00"))
    with pytest.raises(Invalid, match="DUPLICATE_UID_DATE"):
        evaluate(**fixture)


def test_review_f3_path_alias_cannot_replace_missing_session():
    data = list(marks())
    data.pop(1)
    data.append(replace(data[0], event_at="2025-03-03T09:45:00-05:00"))
    row = stock_path(opportunity(), tuple(data), 5, "2025-03-11T00:00:00Z")
    assert row["status"] != "COMPLETE"
    assert row["reason"] in {"DUPLICATE_MARK", "MISSING_PATH"}
    assert "absolute_return" not in row


def test_review_f3_label_availability_uses_instants_not_string_order():
    data = list(marks())
    data[0] = replace(data[0], available_at="2025-03-11T12:00:00-05:00")
    data[-1] = replace(data[-1], available_at="2025-03-11T16:00:00Z")
    row = stock_path(opportunity(), tuple(data), 5, "2025-03-12T00:00:00Z")
    assert row["status"] == "COMPLETE"
    assert pd.Timestamp(row["label_available_at"]) == pd.Timestamp("2025-03-11T17:00:00Z")


def comparison_for(result, population):
    return next(row for row in paired_summary(result)["comparisons"]
                if row["arm"] == "STOCK" and row["population"] == population)


def test_review_f4_budget_cash_belongs_to_all_valid_population():
    result = evaluate(**(inputs() | {"opportunities": (opportunity(capital=600),)}))
    all_valid = comparison_for(result, "ALL_VALID_OPPORTUNITIES")
    # Budget rejects Call; five stock shares earn 15 less two minimum fees.
    assert all_valid["opportunity_rows"] == all_valid["paired_rows"] == 1
    assert all_valid["mean_date_increment"] == pytest.approx(-13/600)
    assert all_valid["unresolved_rows"] == all_valid["excluded_rows"] == 0
    assert comparison_for(result, "DECISION_OPTION_ELIGIBLE")["opportunity_rows"] == 0
    assert comparison_for(result, "RESOLVED_FILLED_ONLY")["paired_rows"] == 0


def test_review_f4_missing_entry_data_is_not_known_cash_without_window_evidence():
    fixture = inputs()
    fixture["quotes"] = tuple(q for q in fixture["quotes"] if not (
        q.instrument_id == "CALL" and q.event_at == "2025-03-03T14:45:01Z"))
    result = evaluate(**fixture)
    assert result["opportunities"][0]["eligible"]
    assert arm(result)["status"] == "NOT_OPENED"
    for population in ("ALL_VALID_OPPORTUNITIES", "DECISION_OPTION_ELIGIBLE"):
        row = comparison_for(result, population)
        assert row["opportunity_rows"] == 1 and row["paired_rows"] == 0
        assert row["mean_date_increment"] is None
        assert row["exclusions"] == {"DATA_NOT_IDENTIFIABLE": 1}
    # Complete and qualified source coverage can establish a no-fill outcome.
    result["opportunities"][0]["entry_window_complete_by_arm"] = {"LONG_CALL": True}
    assert comparison_for(result, "ALL_VALID_OPPORTUNITIES")["paired_rows"] == 0
    result["opportunities"][0]["entry_window_qualified_by_arm"] = {"LONG_CALL": True}
    for population in ("ALL_VALID_OPPORTUNITIES", "DECISION_OPTION_ELIGIBLE"):
        row = comparison_for(result, population)
        assert row["paired_rows"] == 1 and row["excluded_rows"] == 0
        assert row["mean_date_increment"] == pytest.approx(-.0295)
        assert row["known_no_trade_pairs"] == 1
    assert comparison_for(result, "RESOLVED_FILLED_ONLY")["paired_rows"] == 0


def test_review_complete_entry_window_cannot_hide_earlier_unqualified_quote():
    fixture = inputs()
    fixture["quotes"] = tuple(q for q in fixture["quotes"] if not (
        q.instrument_id == "CALL" and q.event_at == "2025-03-03T14:45:01Z")) + (
            quote("2025-03-03T14:45:01Z", size_unit="UNKNOWN"),
            quote("2025-03-03T14:45:02Z", ask_size=0),
        )
    result = evaluate(**fixture)
    assert result["opportunities"][0]["eligible"]
    # quote_at reports its last rejection, which must not certify earlier rows.
    assert arm(result)["reason"] == "ENTRY_SIZE_OR_BID"
    assert arm(result)["status"] == "NOT_OPENED" and arm(result)["cash"] == 10000
    result["opportunities"][0]["entry_window_complete_by_arm"] = {"LONG_CALL": True}
    assert comparison_for(result, "ALL_VALID_OPPORTUNITIES")["paired_rows"] == 0
    for qualified in (None, False, "UNKNOWN"):
        result["opportunities"][0]["entry_window_qualified_by_arm"] = {"LONG_CALL": qualified}
        summary = paired_summary(result)
        assert comparison_for(result, "ALL_VALID_OPPORTUNITIES")["exclusions"] == {"DATA_NOT_IDENTIFIABLE": 1}
        assert summary["active_no_trade_calls"] == 0
        assert summary["data_unidentifiable_opportunities"] == 1


def test_review_complete_contract_universe_cannot_make_unknown_adjustment_no_trade():
    fixture = inputs() | {"contracts": (contract(adjustment_status="UNKNOWN"),)}
    result = evaluate(**fixture)
    assert arm(result)["reason"] == "NO_ELIGIBLE_CONTRACT"
    assert arm(result, "STOCK")["status"] == "CLOSED"
    result["opportunities"][0]["contract_universe_complete"] = True
    assert comparison_for(result, "ALL_VALID_OPPORTUNITIES")["paired_rows"] == 0
    for qualified in (None, False, "UNKNOWN"):
        result["opportunities"][0]["contract_universe_qualified"] = qualified
        summary = paired_summary(result)
        assert comparison_for(result, "ALL_VALID_OPPORTUNITIES")["exclusions"] == {"DATA_NOT_IDENTIFIABLE": 1}
        assert summary["active_no_trade_calls"] == 0
        assert summary["data_unidentifiable_opportunities"] == 1


def test_review_f4_unresolved_position_is_visible_in_population_counts():
    fixture = inputs()
    fixture["quotes"] = tuple(q for q in fixture["quotes"] if not (
        q.instrument_id == "CALL" and q.event_at == "2025-03-10T13:45:01Z"))
    result = evaluate(**fixture)
    for population in ("ALL_VALID_OPPORTUNITIES", "DECISION_OPTION_ELIGIBLE"):
        row = comparison_for(result, population)
        assert row["opportunity_rows"] == 1 and row["paired_rows"] == 0
        assert row["unresolved_rows"] == 1
        assert row["excluded_rows"] == 1 and sum(row["exclusions"].values()) == 1
        assert row["mean_date_increment"] is None
    assert paired_summary(result)["economic_verdict"] == "NOT_IDENTIFIABLE"


def test_review_f5_delta_drift_requires_qualified_fill_metadata():
    fixture = inputs()
    fill_at = "2025-03-03T14:45:01Z"
    fixture["quotes"] = tuple(replace(q, delta=.6, delta_at=fill_at,
        delta_source="SYNTHETIC", delta_kind="PROVIDER_HISTORICAL",
        delta_unit="PER_UNDERLYING_SHARE", delta_style="AMERICAN")
        if q.instrument_id == "CALL" and q.event_at == fill_at else q
        for q in fixture["quotes"])
    result = evaluate(**fixture)
    call = arm(result)
    assert call["entry_delta_raw"] == call["entry_delta_qualified"] == .6
    assert call["decision_to_entry_delta_drift"] == pytest.approx(.1)
    assert call["delta_drift_status"] != "NOT_IDENTIFIABLE"
    fixture["quotes"] = tuple(replace(q, delta_unit="PER_CONTRACT")
        if q.instrument_id == "CALL" and q.event_at == fill_at else q
        for q in fixture["quotes"])
    call = arm(evaluate(**fixture))
    assert call["entry_delta_raw"] == .6
    assert call["entry_delta_qualified"] is None
    assert call["decision_to_entry_delta_drift"] is None
    assert call["delta_drift_status"] == "NOT_IDENTIFIABLE"
    assert call["net_wealth"] == 10198
