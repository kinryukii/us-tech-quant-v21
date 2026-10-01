"""Synthetic records only: no research/data-root or SDK reads."""
from datetime import date, timedelta
import importlib.util
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "scripts/storage/top20_quota_plan.py"
SPEC = importlib.util.spec_from_file_location("top20_quota_plan_test_subject", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
plan = MODULE.build_top20_quota_plan


def record(ticker, day="2026-09-22", rank=1, **extra):
    return {"date": day, "ticker": ticker, "rank": rank,
            "record_kind": "daily_recommendation", **extra}


def rows_by_ticker(result):
    return {row["ticker"]: row for row in result["assignments"]}


def test_frequency_dedup_and_stable_ties_ignore_backtests_and_non_top20():
    records = [record("B", "2026-09-21"), record("B"), record("A"), record("C"),
               record("B", strategy="another"), record("D", "2026-09-21"),
               record("BAD", record_kind="backtest"), record("LOW", rank=41),
               record("MISSING", record_kind=None), record("FUTURE", "2026-09-24")]
    result = plan(records, (0, 300, []), as_of_date="2026-09-23")
    assert result["priority_pool"] == ["B", "A", "C", "D"]
    assert rows_by_ticker(result)["B"]["frequency_days"] == 2
    assert result["counts"]["deduplicated_same_day_records"] == 1
    assert result["counts"]["excluded_record_kind"] == 2
    assert result["counts"]["excluded_future_records"] == 1
    assert result["counts"]["excluded_rank_records"] == 1
    assert result["counts"]["moomoo_symbols"] == 4


def test_window_uses_last_sixty_reliable_result_dates():
    days = []
    day = date(2026, 1, 1)
    while len(days) < 65:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    records = [record("ALWAYS", day) for day in days]
    records += [record("OLD", days[0]), record("EDGE", days[5]), record("NEW", days[-1])]
    result = plan(records, (0, 300, []), as_of_date="2026-09-23", trading_dates=days)
    assert result["priority_pool"] == ["ALWAYS", "NEW", "EDGE"]
    assert result["window_start"] == days[5]
    assert result["counts"]["window_sessions"] == 60
    assert result["window_basis"] == "LATEST_RELIABLE_RESULT_DATES"
    assert result["result_dates_calendar_validated"] is True


def test_observed_history_fallback_is_explicit_and_does_not_pad():
    result = plan([record("A")], (0, 300, []), as_of_date="2026-09-23")
    assert result["window_basis"] == "LATEST_RELIABLE_RESULT_DATES"
    assert result["counts"]["window_sessions"] == 1
    assert result["priority_pool"] == ["A"]
    assert result["counts"]["planned_new_provider_symbols"] == 1


def test_priority_pool_caps_at_300_and_other_requested_symbols_are_alternate():
    records = [record(f"T{i:03}", strategy=f"strategy-{i}") for i in range(305)]
    result = plan(records, (0, 300, []), as_of_date="2026-09-23",
                  universe=[{"ticker": "NOHISTORY"}])
    assert len(result["priority_pool"]) == 300
    assert result["counts"]["moomoo_symbols"] == 300
    assert result["counts"]["alternate_symbols"] == 6
    assert rows_by_ticker(result)["NOHISTORY"]["reason"] == "OUTSIDE_PRIORITY_POOL"
    assert rows_by_ticker(result)["T300"]["provider"] == "ALTERNATE"


def test_existing_slots_outside_pool_reduce_new_slots_but_repeats_are_free():
    details = [{"code": f"US.EXTERNAL{i}"} for i in range(298)] + [{"code": "US.B"}]
    result = plan([record("A"), record("B"), record("C")], (299, 1, details),
                  as_of_date="2026-09-23")
    rows = rows_by_ticker(result)
    assert rows["A"]["consumes_new_slot"] is True
    assert rows["B"]["provider"] == "MOOMOO"
    assert rows["B"]["consumes_new_slot"] is False
    assert rows["C"]["provider"] == "ALTERNATE"
    assert result["counts"]["planned_new_provider_symbols"] == 1
    assert result["counts"]["reused_provider_symbols"] == 1


def test_zero_remaining_still_allows_repeated_reads_of_known_pool_symbols():
    details = [{"code": "US.A"}, {"code": "HK.00700"}]
    result = plan([record("A"), record("B")], (2, 0, details), as_of_date="2026-09-23")
    assert rows_by_ticker(result)["A"]["provider"] == "MOOMOO"
    assert rows_by_ticker(result)["B"]["provider"] == "ALTERNATE"
    assert result["counts"]["planned_new_provider_symbols"] == 0


def test_already_used_symbols_outside_priority_pool_are_reused_without_new_quota():
    result = plan([record("A")], (1, 299, [{"code": "US.OUTSIDE"}]),
                  as_of_date="2026-09-23", universe=[{"ticker": "OUTSIDE"}, {"ticker": "NEWOUTSIDE"}])
    rows = rows_by_ticker(result)
    assert rows["OUTSIDE"]["provider"] == "MOOMOO"
    assert rows["OUTSIDE"]["in_priority_pool"] is False
    assert rows["OUTSIDE"]["consumes_new_slot"] is False
    assert rows["OUTSIDE"]["reason"] == "ALREADY_COUNTED_PROVIDER_SYMBOL_OUTSIDE_PRIORITY_POOL"
    assert rows["NEWOUTSIDE"]["provider"] == "ALTERNATE"
    assert result["counts"]["planned_new_provider_symbols"] == 1
    assert result["counts"]["reused_provider_symbols"] == 1


def test_known_outside_pool_still_occupies_the_total_300_slot_limit():
    records = [record(f"T{i:03}") for i in range(301)]
    result = plan(records, (1, 299, [{"code": "US.T300"}]), as_of_date="2026-09-23")
    rows = rows_by_ticker(result)
    assert rows["T300"]["provider"] == "MOOMOO"
    assert rows["T299"]["provider"] == "ALTERNATE"
    assert result["counts"]["planned_new_provider_symbols"] == 299
    assert result["counts"]["moomoo_symbols"] == 300


def test_provider_remaining_is_not_mistaken_for_total_limit_or_weekly_reset():
    details = [{"code": f"US.U{i}"} for i in range(280)]
    records = [record(f"T{i}") for i in range(30)]
    for as_of in ("2026-09-23", "2026-10-05"):
        result = plan(records, (280, 5, details), as_of_date=as_of)
        assert result["counts"]["planned_new_provider_symbols"] == 5
        assert result["quota"]["provider_total"] == 285


def test_user_cap_limits_new_slots_even_if_provider_has_larger_tier():
    details = [{"code": f"US.EXTERNAL{i}"} for i in range(299)]
    result = plan([record("A"), record("B")], (299, 701, details), as_of_date="2026-09-23")
    assert result["counts"]["planned_new_provider_symbols"] == 1


@pytest.mark.parametrize("quota", [None, {}, (0, 300), (True, 300, []),
    (0, -1, []), (1, 299, []), (0, 300, [{"code": "US.A"}]),
    (2, 298, [{"code": "US.A"}, {"code": "US.A"}]),
    (1, 299, [{"code": "A"}]), (1, 299, ["US.A"]), (0, 300, None)])
def test_unknown_or_contradictory_quota_fails_closed(quota):
    result = plan([record("A")], quota, as_of_date="2026-09-23")
    assert result["quota"]["status"] == "UNKNOWN"
    assert result["counts"]["moomoo_symbols"] == 0
    assert rows_by_ticker(result)["A"]["reason"] == "QUOTA_UNKNOWN_OR_INCONSISTENT"


def test_mapping_and_string_csv_rank_preserve_special_symbol_identity():
    result = plan([record("brk.b", rank="2")],
                  {"used": 1, "remaining": 299, "details": [{"code": "US.BRK.B"}]},
                  as_of_date="2026-09-23", universe=[{"ticker": "BRK.B", "moomoo_code": "US.BRK.B"}])
    row = result["assignments"][0]
    assert row["ticker"] == "BRK.B"
    assert row["reason"] == "ALREADY_COUNTED_PROVIDER_SYMBOL"


def test_special_symbol_without_mapping_is_alternate_without_blocking_others():
    result = plan([record("BRK.B"), record("A")], (0, 300, []), as_of_date="2026-09-23")
    rows = rows_by_ticker(result)
    assert rows["BRK.B"]["provider"] == "ALTERNATE"
    assert rows["BRK.B"]["reason"] == "EXPLICIT_PROVIDER_MAPPING_REQUIRED"
    assert rows["BRK.B"]["moomoo_symbol"] is None
    assert rows["BRK.B"]["consumes_new_slot"] is False
    assert rows["A"]["provider"] == "MOOMOO"
    assert result["counts"]["planned_new_provider_symbols"] == 1


def test_explicit_special_mapping_can_complete_an_earlier_unknown_mapping():
    result = plan([record("BRK.B", moomoo_symbol="US.BRK.B")], (0, 300, []),
                  as_of_date="2026-09-23", universe=[{"ticker": "BRK.B"}])
    assert result["assignments"][0]["moomoo_symbol"] == "US.BRK.B"
    assert result["assignments"][0]["provider"] == "MOOMOO"


def test_conflicting_and_ambiguous_provider_mappings_are_rejected():
    with pytest.raises(ValueError, match="CONFLICTING_TICKER_MAPPING"):
        plan([record("A", moomoo_symbol="US.WRONG")], (0, 300, []), as_of_date="2026-09-23",
             universe=[{"ticker": "A", "moomoo_symbol": "US.A"}])
    with pytest.raises(ValueError, match="AMBIGUOUS_PROVIDER_MAPPING"):
        plan([record("A")], (0, 300, []), as_of_date="2026-09-23",
             universe=[{"ticker": "A"}, {"ticker": "B", "moomoo_symbol": "US.A"}])


def test_non_session_and_empty_inputs_do_not_invent_priorities():
    with pytest.raises(ValueError, match="RESULT_DATE_NOT_IN_SUPPLIED_TRADING_DATES"):
        plan([record("A", "2026-09-20")], (0, 300, []), as_of_date="2026-09-23",
             trading_dates=["2026-09-21", "2026-09-22"])
    empty = plan([], (0, 300, []), as_of_date="2026-09-23")
    assert empty["window_start"] is None
    assert empty["counts"]["moomoo_symbols"] == 0


@pytest.mark.parametrize("changes", [{"lookback_sessions": 0}, {"max_moomoo_symbols": 301},
                                     {"max_moomoo_symbols": True}, {"as_of_date": "2026-9-23"}])
def test_bad_contract_inputs_are_rejected(changes):
    kwargs = {"as_of_date": "2026-09-23", **changes}
    with pytest.raises(ValueError):
        plan([record("A")], (0, 300, []), **kwargs)


def seed(ticker, day="2025-12-30", rank=1, **extra):
    return record(ticker, day, rank, record_kind="historical_replay",
                  model_id="same-frozen-model", source_id="same-replay-source", **extra)


def test_bootstrap_old_reliable_results_are_not_cut_off_relative_to_today():
    replay = [seed("TOP20", "2025-12-29"), seed("TOP40", "2025-12-29", 25),
              seed("TOP40", rank=25), seed("LAST40", rank=40), seed("EXCLUDED", rank=41)]
    result = plan([], (0, 300, []), as_of_date="2026-09-23", bootstrap_records=replay)
    assert result["bootstrap_used"] is True
    assert result["history_date_start"] == "2025-12-29"
    assert result["history_date_end"] == "2025-12-30"
    assert result["priority_pool"] == ["TOP20", "TOP40", "LAST40"]
    assert result["counts"]["top20_unique_symbols"] == 1
    assert result["counts"]["priority_top40_symbols"] == 2
    assert result["counts"]["priority_pool_symbols"] == 3
    assert rows_by_ticker(result)["TOP40"]["priority_tier"] == "TOP40"


def test_replay_in_daily_input_is_never_silently_authorized():
    result = plan([seed("A")], (0, 300, []), as_of_date="2026-09-23")
    assert result["priority_pool"] == []
    assert result["bootstrap_used"] is False


def test_same_day_daily_replaces_whole_bootstrap_day_without_double_counting():
    result = plan([record("REAL", "2025-12-30")], (0, 300, []), as_of_date="2026-09-23",
                  bootstrap_records=[seed("OLD", "2025-12-29"), seed("REAL"), seed("REPLAYONLY")])
    assert result["priority_pool"] == ["REAL", "OLD"]
    assert result["counts"]["bootstrap_sessions"] == 1
    assert result["counts"]["daily_sessions"] == 1
    assert result["counts"]["replaced_bootstrap_records"] == 2
    assert rows_by_ticker(result)["REAL"]["frequency_days"] == 1


def test_top20_frequency_is_separate_from_top40_frequency_and_deduped():
    records = [record("A", "2026-09-21", 20), record("A", rank=30),
               record("A", rank=30, strategy="second"), record("B", rank=20),
               record("C", "2026-09-21", 30), record("C", rank=30)]
    result = plan(records, (0, 300, []), as_of_date="2026-09-23")
    assert result["priority_pool"] == ["B", "A", "C"]
    assert rows_by_ticker(result)["A"]["frequency_days"] == 1
    assert rows_by_ticker(result)["A"]["top40_frequency_days"] == 2
    assert result["counts"]["deduplicated_same_day_records"] == 1


def test_bootstrap_cannot_mix_models_or_sources():
    for key in ("model_id", "source_id"):
        mixed = [seed("A"), {**seed("B", rank=30), key: "different"}]
        with pytest.raises(ValueError, match="MIXED_BOOTSTRAP_MODEL_OR_SOURCE"):
            plan([], (0, 300, []), as_of_date="2026-09-23", bootstrap_records=mixed)
    with pytest.raises(ValueError, match="BOOTSTRAP_MODEL_AND_SOURCE_ID_REQUIRED"):
        plan([], (0, 300, []), as_of_date="2026-09-23",
             bootstrap_records=[record("A", record_kind="historical_replay")])


def test_bootstrap_top40_only_fills_after_all_top20_symbols():
    replay = [seed(f"TOP{i:03}") for i in range(93)]
    replay += [seed(f"FILL{i:03}", rank=30) for i in range(250)]
    result = plan([], (0, 300, []), as_of_date="2026-09-23", bootstrap_records=replay)
    assert result["priority_pool"][:93] == [f"TOP{i:03}" for i in range(93)]
    assert result["counts"]["top20_unique_symbols"] == 93
    assert result["counts"]["priority_top40_symbols"] == 207
    assert result["counts"]["alternate_symbols"] == 43


def test_explicit_pool_fills_142_remaining_slots_after_history_with_631_members():
    top20 = [f"TOP{i:03}" for i in range(93)]
    top40 = [f"FILL{i:03}" for i in range(61)]
    outside_used = [f"USED{i}" for i in range(4)]
    additional = [f"POOL{i:03}" for i in range(473)]
    members = top20 + top40 + outside_used + additional
    assert len(members) == 631
    details = [{"code": "US." + ticker} for ticker in top20 + top40 + outside_used]
    replay = [seed(ticker) for ticker in top20] + [seed(ticker, rank=30) for ticker in top40]
    result = plan([], (158, 142, details), as_of_date="2026-09-22",
                  bootstrap_records=replay,
                  universe=[{"ticker": ticker} for ticker in members + ["OLDCATALOG"]],
                  pool_supplement=[{"ticker": ticker, "last_price_date": None} for ticker in members])
    rows = rows_by_ticker(result)
    assert result["priority_pool"][:154] == top20 + top40
    assert result["counts"]["moomoo_symbols"] == 300
    assert result["counts"]["reused_provider_symbols"] == 158
    assert result["counts"]["planned_new_provider_symbols"] == 142
    assert result["counts"]["new_symbol_budget_after"] == 0
    assert result["counts"]["priority_top40_symbols"] == 61
    assert result["counts"]["pool_refresh_new_provider_symbols"] == 142
    assert rows["POOL141"]["provider"] == "MOOMOO"
    assert rows["POOL142"]["provider"] == "ALTERNATE"
    assert rows["OLDCATALOG"]["reason"] == "OUTSIDE_PRIORITY_POOL"
    assert result["counts"]["alternate_symbols"] == 332


def test_pool_supplement_order_is_missing_then_oldest_then_ticker_after_top40():
    coverage = {"MISSINGB": None, "MISSINGA": None, "OLDB": "2026-01-02",
                "OLDA": "2026-01-02", "RECENT": "2026-09-21",
                "CURRENT": "2026-09-22", "TOP": None, "HISTORY40": None}
    result = plan([record("TOP", "2026-09-21"), record("HISTORY40", "2026-09-21", 30)],
                  (0, 300, []), as_of_date="2026-09-22",
                  universe=[{"ticker": ticker} for ticker in coverage],
                  pool_supplement=[{"ticker": ticker, "last_price_date": latest} for ticker, latest in coverage.items()])
    assert result["priority_pool"] == ["TOP", "HISTORY40", "MISSINGA", "MISSINGB", "OLDA", "OLDB", "RECENT"]
    rows = rows_by_ticker(result)
    assert rows["OLDA"]["priority_tier"] == "POOL_REFRESH"
    assert rows["OLDA"]["pool_last_price_date"] == "2026-01-02"
    assert rows["MISSINGA"]["reason"] == "POOL_REFRESH_NEW_PROVIDER_SYMBOL"
    assert rows["CURRENT"]["reason"] == "POOL_PRICE_COVERAGE_ALREADY_CURRENT"
    assert rows["CURRENT"]["consumes_new_slot"] is False
    assert result["counts"]["pool_refresh_additional_symbols"] == 5
    assert result["counts"]["pool_current_symbols"] == 1
    assert result["counts"]["top20_unique_symbols"] == 1
    assert result["counts"]["priority_top40_symbols"] == 1


def test_pool_only_allocation_respects_provider_remaining_and_reuses_outside_known():
    result = plan([], (2, 1, [{"code": "US.KNOWN"}, {"code": "HK.00700"}]),
                  as_of_date="2026-09-22", universe=[{"ticker": ticker} for ticker in ["A", "B", "KNOWN"]],
                  pool_supplement=[{"ticker": ticker, "last_price_date": None} for ticker in ["B", "A"]])
    rows = rows_by_ticker(result)
    assert rows["A"]["provider"] == "MOOMOO"
    assert rows["B"]["reason"] == "PROVIDER_REMAINING_OR_USER_CAP_EXHAUSTED"
    assert rows["KNOWN"]["provider"] == "MOOMOO"
    assert result["counts"]["planned_new_provider_symbols"] == 1
    assert result["counts"]["reused_provider_symbols"] == 1
    assert result["history_date_start"] is None


def test_pool_unknown_quota_fails_closed_and_unmapped_symbols_do_not_take_positions():
    universe = [{"ticker": ticker} for ticker in ["A.B", "C", "D"]]
    supplement = [{"ticker": ticker, "last_price_date": None} for ticker in ["A.B", "C", "D"]]
    unknown = plan([], None, as_of_date="2026-09-22", universe=universe, pool_supplement=supplement)
    assert unknown["counts"]["moomoo_symbols"] == 0
    assert rows_by_ticker(unknown)["C"]["reason"] == "QUOTA_UNKNOWN_OR_INCONSISTENT"
    result = plan([], (0, 300, []), as_of_date="2026-09-22", universe=universe,
                  pool_supplement=supplement, max_moomoo_symbols=2)
    assert result["priority_pool"] == ["C", "D"]
    assert result["counts"]["planned_new_provider_symbols"] == 2
    assert rows_by_ticker(result)["A.B"]["reason"] == "EXPLICIT_PROVIDER_MAPPING_REQUIRED"


def test_pool_duplicates_deduplicate_without_changing_top20_frequency():
    row = {"ticker": "A", "last_price_date": None}
    result = plan([record("A")], (0, 300, []), as_of_date="2026-09-23",
                  universe=[{"ticker": "A"}], pool_supplement=[row, dict(row)])
    assert result["priority_pool"] == ["A"]
    assert result["counts"]["pool_supplement_symbols"] == 1
    assert result["counts"]["pool_refresh_additional_symbols"] == 0
    assert result["counts"]["planned_new_provider_symbols"] == 1
    assert rows_by_ticker(result)["A"]["frequency_days"] == 1


@pytest.mark.parametrize("supplement,error", [
    ([{"ticker": "OUTSIDE", "last_price_date": None}], "POOL_SUPPLEMENT_NOT_IN_UNIVERSE"),
    ([{"ticker": "A"}], "POOL_LAST_PRICE_DATE_REQUIRED"),
    ([{"ticker": "A", "last_price_date": "2026-9-21"}], "INVALID_POOL_LAST_PRICE_DATE"),
    ([{"ticker": "A", "last_price_date": None}, {"ticker": "A", "last_price_date": "2026-09-21"}], "CONFLICTING_POOL_PRICE_COVERAGE"),
])
def test_pool_contract_rejects_unknown_members_or_ambiguous_coverage(supplement, error):
    with pytest.raises(ValueError, match=error):
        plan([], (0, 300, []), as_of_date="2026-09-22", universe=[{"ticker": "A"}], pool_supplement=supplement)


def test_explicit_empty_supplement_never_uses_arbitrary_catalog_members():
    result = plan([], (0, 300, []), as_of_date="2026-09-22", universe=[{"ticker": "OLDCATALOG"}], pool_supplement=[])
    assert result["pool_supplement_authorized"] is True
    assert result["priority_pool"] == []
    assert result["counts"]["planned_new_provider_symbols"] == 0
    assert rows_by_ticker(result)["OLDCATALOG"]["provider"] == "ALTERNATE"


def test_unavailable_codes_free_priority_positions_without_changing_recommendation_frequency():
    records = [record("UNAVAILABLE", "2026-09-21"), record("UNAVAILABLE"),
               record("TOP20"), record("TOP40", rank=30)]
    result = plan(records, (0, 300, []), as_of_date="2026-09-23", max_moomoo_symbols=3,
                  universe=[{"ticker": "POOL"}], pool_supplement=[{"ticker": "POOL", "last_price_date": None}],
                  provider_unavailable={"US.UNAVAILABLE"})
    rows = rows_by_ticker(result)
    assert result["priority_pool"] == ["TOP20", "TOP40", "POOL"]
    assert rows["UNAVAILABLE"]["frequency_days"] == 2 and rows["UNAVAILABLE"]["priority_rank"] == 1
    assert rows["UNAVAILABLE"]["priority_tier"] == "TOP20"
    assert rows["UNAVAILABLE"]["provider"] == "ALTERNATE"
    assert rows["UNAVAILABLE"]["reason"] == "PROVIDER_UNAVAILABLE_IN_CALLER_EVIDENCE"
    assert rows["UNAVAILABLE"]["consumes_new_slot"] is False
    assert result["counts"]["top20_unique_symbols"] == 2
    assert result["counts"]["planned_new_provider_symbols"] == 3
    assert result["counts"]["priority_excluded_provider_unavailable_symbols"] == 1


def test_thirteen_unavailable_symbols_do_not_repeat_block_remaining_live_quota():
    used = [{"code": f"US.USED{i:03}"} for i in range(286)] + [{"code": "US.EMPTY"}]
    unavailable = [f"A{i:02}" for i in range(13)]
    replacements = [f"B{i:02}" for i in range(20)]
    tickers = unavailable + replacements + ["EMPTY"]
    result = plan([], (287, 13, used), as_of_date="2026-09-23",
                  universe=[{"ticker": ticker} for ticker in tickers],
                  pool_supplement=[{"ticker": ticker, "last_price_date": None} for ticker in tickers],
                  provider_unavailable=["US." + ticker for ticker in unavailable])
    rows = rows_by_ticker(result)
    assert all(rows[ticker]["provider"] == "ALTERNATE" for ticker in unavailable)
    assert all(rows[ticker]["consumes_new_slot"] for ticker in replacements[:13])
    assert all(rows[ticker]["provider"] == "ALTERNATE" for ticker in replacements[13:])
    assert rows["EMPTY"]["provider"] == "MOOMOO" and rows["EMPTY"]["consumes_new_slot"] is False
    assert result["counts"]["planned_new_provider_symbols"] == 13
    assert result["counts"]["provider_unavailable_symbols"] == 13
    assert result["counts"]["reused_provider_symbols"] == 1


def test_charged_unavailable_symbol_is_skipped_but_its_provider_slot_is_not_refunded():
    result = plan([record("A"), record("B"), record("C")], (1, 299, [{"code": "US.A"}]),
                  as_of_date="2026-09-23", max_moomoo_symbols=2, provider_unavailable={"US.A"})
    rows = rows_by_ticker(result)
    assert rows["A"]["reason"] == "PROVIDER_UNAVAILABLE_IN_CALLER_EVIDENCE"
    assert rows["A"]["provider"] == "ALTERNATE" and rows["C"]["provider"] == "ALTERNATE"
    assert rows["B"]["consumes_new_slot"] is True
    assert result["counts"]["new_symbol_budget_before"] == 1
    assert result["counts"]["reused_provider_symbols"] == 0


def test_unavailable_evidence_is_bound_to_provider_code_not_ticker_and_is_opt_in():
    base = {"records": [record("RENAMED")], "quota": (0, 300, []), "as_of_date": "2026-09-23",
            "universe": [{"ticker": "RENAMED", "moomoo_symbol": "US.NEWCODE"}]}
    assert rows_by_ticker(plan(**base, provider_unavailable={"US.RENAMED"}))["RENAMED"]["provider"] == "MOOMOO"
    assert rows_by_ticker(plan(**base, provider_unavailable={"US.NEWCODE"}))["RENAMED"]["provider"] == "ALTERNATE"
    assert rows_by_ticker(plan(**base, provider_unavailable=[]))["RENAMED"]["provider"] == "MOOMOO"


@pytest.mark.parametrize("codes", ["US.A", ["A"], ["HK.00700"], [None], ["US.A;DROP"]])
def test_unavailable_evidence_requires_explicit_us_code_collection(codes):
    with pytest.raises(ValueError, match="PROVIDER_UNAVAILABLE_REQUIRES"):
        plan([record("A")], (0, 300, []), as_of_date="2026-09-23", provider_unavailable=codes)
