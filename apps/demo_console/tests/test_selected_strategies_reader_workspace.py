"""Synthetic cutoff/target checks for the main workspace selected-policy reader."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from apps.demo_console.adapters import selected_strategies_reader as reader


def package():
    strategies = {}
    for sid in reader.STRATEGY_IDS:
        rows = [{"ticker": "AAPL", "target_weight": .6, "weight_before": .2, "action": "BUY"}]
        strategies[sid] = {
            "label": reader.STRATEGY_LABELS[sid],
            "daily": [{"date": day, "nav": nav, "cash_weight": cash}
                      for day, nav, cash in (("2026-01-05", 1.01, .4),
                                            ("2026-01-06", .98, .5),
                                            ("2026-01-07", 1.03, .6))],
            "summary": {"end_nav": 1.03, "cumulative_return": .03, "max_drawdown": .98 / 1.01 - 1,
                        "mean_cash": .5, "days": 3, "turnover": 2.4},
            "targets": [{"signal_date": day, "rows": deepcopy(rows)}
                        for day in ("2026-01-02", "2026-01-05", "2026-01-06")],
            "application": {"status": "READY", "signal_date": "2026-09-24", "account_basis": "CASH_START",
                "rows": [{"ticker": "MSFT", "target_weight": .5, "weight_before": 0, "action": "BUY"}],
                "target_cash_weight": .5, "reason": ""},
        }
    return {"schema_version": 1, "generated_at": "2026-09-25T01:00:00+00:00",
        "selection_basis": reader.SELECTION_BASIS,
        "performance_period": {"start": "2026-01-05", "end": "2026-01-07",
            "price_basis": "QFQ_PRICE_COORDINATE_PROXY", "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN"},
        "source_hashes": {"model": "ab" * 32},
        "source_refs": {"model": {"path": "C:/synthetic/model.joblib", "sha256": "ab" * 32}},
        "strategies": strategies, "limitations": ["Recorded replay and current cash-start targets."]}


def test_workspace_dates_are_only_real_records_and_never_extend_the_curve():
    payload = package()
    assert reader.workspace_dates(payload) == (
        "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-09-24")
    view = reader.workspace_view(reader.STRATEGY_IDS[0], package=payload)
    assert view["requested_cutoff"] == "2026-09-24"
    assert [row["date"] for row in view["history"]["daily"]] == ["2026-01-05", "2026-01-06", "2026-01-07"]
    assert view["history"]["end"] == "2026-01-07"
    assert view["target"]["signal_date"] == "2026-09-24"
    assert view["target"]["kind"] == "CURRENT_CASH_START_TARGET"
    assert view["target"]["account_basis"] == "CASH_START"
    assert view["target"]["execution_status"] == "TARGET_ONLY"


def test_cutoff_hides_later_nav_current_target_and_full_period_metrics():
    payload = package()
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-01-05", package=payload)
    history, target = view["history"], view["target"]
    assert history["end"] == "2026-01-05"
    assert len(history["daily"]) == 1
    assert history["summary"]["end_nav"] == 1.01
    assert history["summary"]["cumulative_return"] == pytest.approx(.01)
    assert history["summary"]["min_daily_return"] == pytest.approx(.01)
    assert history["summary"]["net_returns"] == pytest.approx([.01])
    assert history["summary"]["mean_cash"] == .4
    assert history["summary"]["days"] == 1
    assert history["summary"]["turnover"] is None
    assert target["signal_date"] == "2026-01-05"
    assert target["kind"] == "HISTORICAL_SIGNAL_TARGET"
    assert target["rows"][0]["ticker"] == "AAPL"
    assert target["target_cash_weight"] == pytest.approx(.4)
    assert target["execution_status"] == "TARGET_ONLY"


def test_missing_history_and_target_remain_empty_instead_of_fabricating_nav_or_cash():
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-01-01", package=package())
    assert view["history"]["status"] == "UNAVAILABLE"
    assert view["history"]["daily"] == []
    assert view["history"]["summary"] is None
    assert view["history"]["last_cash_weight"] is None
    assert view["target"]["status"] == "UNAVAILABLE"
    assert view["target"]["rows"] == []
    assert view["target"]["target_cash_weight"] is None


def test_gap_after_history_preserves_real_dates_and_hides_future_application():
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-08-18", package=package())
    assert view["history"]["end"] == "2026-01-07"
    assert view["target"]["signal_date"] == "2026-01-06"
    assert view["target"]["status"] == "LATEST_AVAILABLE_SIGNAL"
    assert view["target"]["kind"] == "HISTORICAL_SIGNAL_TARGET"
    assert all(row["ticker"] != "MSFT" for row in view["target"]["rows"])


def test_future_requested_cutoff_uses_latest_target_date_without_renaming_it():
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-09-28", package=package())
    assert view["target"]["status"] == "LATEST_AVAILABLE_SIGNAL"
    assert view["target"]["signal_date"] == "2026-09-24"
    assert view["history"]["end"] == "2026-01-07"


def test_blocked_current_application_does_not_fall_back_to_historical_as_current():
    payload = package()
    payload["strategies"][reader.STRATEGY_IDS[0]]["application"] = {
        "status": "BLOCKED", "signal_date": None, "requested_signal_date": "2026-09-24",
        "rows": [], "reason": "CURRENT_FEATURES_MISSING"}
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-09-24", package=payload)
    assert "2026-09-24" in view["available_dates"]
    assert view["target"]["status"] == "BLOCKED"
    assert view["target"]["rows"] == []
    assert view["target"]["reason"] == "CURRENT_FEATURES_MISSING"
    assert view["history"]["status"] == "AVAILABLE"


def test_blocked_requested_date_is_default_observation_without_extending_history():
    payload = package()
    payload["performance_period"]["end"] = "2026-08-18"
    for strategy in payload["strategies"].values():
        strategy["daily"][-1]["date"] = "2026-08-18"
        strategy["application"] = {"status": "BLOCKED", "signal_date": None,
            "requested_signal_date": "2026-09-24", "rows": [], "reason": "CURRENT_FEATURES_MISSING"}
    assert reader.workspace_dates(payload)[-1] == "2026-09-24"
    for cutoff in (None, "2026-09-24"):
        view = reader.workspace_view(reader.STRATEGY_IDS[0], cutoff, package=payload)
        assert view["requested_cutoff"] == view["latest_requested_signal_date"] == "2026-09-24"
        assert view["latest_application_date"] is None
        assert view["target"]["status"] == "BLOCKED"
        assert view["target"]["rows"] == []
        assert view["target"]["target_cash_weight"] is None
        assert view["target"]["reason"] == "CURRENT_FEATURES_MISSING"
        assert view["history"]["end"] == "2026-08-18"
        assert len(view["history"]["daily"]) == 3
        assert all(point["date"] <= "2026-08-18" for point in view["history"]["daily"])


def test_reader_returns_blocked_empty_states_for_missing_or_invalid_package(tmp_path):
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-09-24", path=tmp_path / "absent.json")
    assert view["status"] == "BLOCKED"
    assert view["history"]["daily"] == view["target"]["rows"] == []
    payload = package()
    payload["strategies"][reader.STRATEGY_IDS[0]]["daily"][0]["nav"] = float("nan")
    invalid = reader.workspace_view(reader.STRATEGY_IDS[0], package=payload)
    assert invalid["status"] == "BLOCKED"
    assert invalid["history"]["summary"] is None


def test_summary_returns_use_initial_nav_and_keep_unknown_costs_out_of_history():
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-01-06", package=package())
    summary = view["history"]["summary"]
    assert summary["net_returns"] == pytest.approx([.01, .98 / 1.01 - 1])
    assert summary["min_daily_return"] == pytest.approx(.98 / 1.01 - 1)
    assert summary["max_drawdown"] == pytest.approx(.98 / 1.01 - 1)
    assert all("cost" not in point and "gross_return" not in point for point in view["history"]["daily"])
    full = reader.workspace_view(reader.STRATEGY_IDS[0], package=package())
    assert full["history"]["summary"]["turnover"] == 2.4


def test_same_package_snapshot_supports_both_strategies_without_loading_again():
    payload = package()
    with patch.object(reader, "load_package", side_effect=AssertionError("unexpected file read")):
        first = reader.workspace_view(reader.STRATEGY_IDS[0], package=payload)
        second = reader.workspace_view(reader.STRATEGY_IDS[1], package=payload)
    first["target"]["rows"][0]["ticker"] = "MODIFIED"
    first["history"]["daily"][0]["nav"] = 10
    first["source_refs"]["model"]["path"] = "MODIFIED"
    assert payload["strategies"][reader.STRATEGY_IDS[0]]["application"]["rows"][0]["ticker"] == "MSFT"
    assert second["target"]["rows"][0]["ticker"] == "MSFT"
    assert payload["source_refs"]["model"]["path"] == "C:/synthetic/model.joblib"
    assert second["model_identity"]["feature_count"] == 21
    assert second["model_identity"]["prediction_scores_available"] is False


def test_file_view_keeps_exact_package_hash_and_validates_cutoff_and_strategy(tmp_path):
    path = tmp_path / "package.json"
    path.write_text(json.dumps(package()), encoding="utf-8")
    view = reader.workspace_view(reader.STRATEGY_IDS[0], path=path)
    assert view["package_sha256"] == reader.load_package(path)["package_sha256"]
    assert view["source_path"] == str(path.resolve())
    with pytest.raises(ValueError):
        reader.workspace_view("RAW_A2", package=package())
    with pytest.raises(ValueError):
        reader.workspace_view(reader.STRATEGY_IDS[0], "2026-02-30", package=package())


def test_latest_real_target_is_selected_when_current_pointer_has_an_older_signal():
    payload = package()
    payload["strategies"][reader.STRATEGY_IDS[0]]["application"]["signal_date"] = "2026-01-03"
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-01-07", package=payload)
    assert view["target"]["signal_date"] == "2026-01-06"
    assert view["target"]["kind"] == "HISTORICAL_SIGNAL_TARGET"


def test_blocked_application_invalid_date_fails_closed_without_hiding_an_exception():
    payload = package()
    payload["strategies"][reader.STRATEGY_IDS[0]]["application"] = {
        "status": "BLOCKED", "rows": [], "reason": "missing", "requested_signal_date": "2026-02-30"}
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-09-24", package=payload)
    assert view["status"] == "BLOCKED"
    assert view["history"]["daily"] == view["target"]["rows"] == []


def extended_package():
    payload = package()
    model_key = "frozen/models/hgb_2026092501.joblib"
    payload["source_hashes"][model_key] = "cd" * 32
    payload["source_refs"][model_key] = {"path": "C:/synthetic/hgb.joblib", "sha256": "cd" * 32}
    for strategy in payload["strategies"].values():
        prior = 1.
        for point in strategy["daily"]:
            pre = point["nav"] / (1 - .8 * .001)
            point.update(net_return=point["nav"] / prior - 1, gross_return=pre / prior - 1,
                pretrade_nav=pre, turnover=.8, transaction_cost_amount=pre - point["nav"],
                transaction_cost_fraction=.0008, gross_exposure=1 - point["cash_weight"],
                holding_count=4, buy_cash_scale=1., skipped_buy_count=0, blocked_sell_count=0,
                stale_mark_count=None, blocked_rebalance_count=None)
            prior = point["nav"]
    reference = deepcopy(payload["strategies"][reader.STRATEGY_IDS[0]])
    reference.pop("application")
    reference.update(strategy_id="RAW_A2", label="Raw A2", performance_period=deepcopy(payload["performance_period"]))
    payload["raw_reference"] = reference
    rows = [{"ticker": f"T{rank:02d}", "security_id": f"SEC-{rank}", "raw_rank": rank,
             "raw_score": .05 - rank * .001, "pred_hgb": (rank // 2) * .001}
            for rank in range(1, 41)]
    rows.sort(key=lambda row: (-row["pred_hgb"], row["ticker"]))
    for rank, row in enumerate(rows, 1):
        row["hgb_rank"] = rank
    payload["shared_scores"] = {"model_id": "HGB_2026092501", "model_sha256": "cd" * 32,
        "scoring_scope": "RAW_TOP40", "ranking_basis": "PRED_HGB_DESC_TICKER_ASC",
        "historical": [{"signal_date": day, **deepcopy(row)}
            for day in ("2026-01-02", "2026-01-05", "2026-09-22") for row in rows],
        "current": {"status": "READY", "signal_date": "2026-09-24", "requested_signal_date": "2026-09-24",
            "rows": deepcopy(rows), "reason": ""}}
    return payload


def test_new_optional_records_keep_legacy_packets_compatible_without_fabricating_scores():
    payload = package()
    assert reader.validate_package(payload) is payload
    assert reader.raw_reference_view(package=payload)["status"] == "UNAVAILABLE"
    assert reader.score_snapshot("2026-09-24", package=payload)["rows"] == []
    assert reader.score_history(package=payload) == []


def test_same_batch_raw_reference_is_separate_and_uses_only_the_requested_history():
    payload = extended_package()
    view = reader.raw_reference_view("2026-01-05", package=payload)
    assert set(payload["strategies"]) == set(reader.STRATEGY_IDS)
    assert view["strategy_id"] == "RAW_A2" and view["source_id"] == "SAME_BATCH_QFQ_PROXY"
    assert view["history"]["summary"]["end_nav"] == 1.01
    assert view["history"]["summary"]["turnover"] == .8
    assert len(view["history"]["daily"]) == 1
    assert view["target"]["signal_date"] == "2026-01-05"
    assert view["target"]["execution_status"] == "TARGET_ONLY"
    assert view["target"]["account_basis"] == "RECORDED_REPLAY_SIGNAL"
    later = reader.raw_reference_view("2026-09-24", package=payload)
    assert later["history"]["end"] == "2026-01-07"
    assert later["target"]["signal_date"] == "2026-01-06"
    assert later["target"]["status"] == "LATEST_AVAILABLE_SIGNAL"
    view["target"]["rows"][0]["ticker"] = "MUTATED"
    assert payload["raw_reference"]["targets"][1]["rows"][0]["ticker"] == "AAPL"


def test_daily_fields_are_actual_records_and_cutoff_turnover_uses_actual_daily_sum():
    view = reader.workspace_view(reader.STRATEGY_IDS[0], "2026-01-06", package=extended_package())
    daily = view["history"]["daily"]
    assert view["history"]["summary"]["turnover"] == pytest.approx(1.6)
    assert daily[0]["transaction_cost_amount"] == pytest.approx(daily[0]["pretrade_nav"] - daily[0]["nav"])
    assert daily[0]["holding_count"] == 4
    assert daily[0]["stale_mark_count"] is daily[0]["blocked_rebalance_count"] is None
    assert daily[0]["blocked_sell_count"] == 0


def test_scores_use_shared_model_order_and_exact_dates_without_weight_ranking():
    payload = extended_package()
    current = reader.score_snapshot("2026-09-24", package=payload)
    assert current["status"] == "READY" and current["actual_signal_date"] == "2026-09-24"
    assert current["scoring_scope"] == "RAW_TOP40" and len(current["rows"]) == 40
    assert current["rows"][0]["raw_rank"] == 40 and current["rows"][0]["hgb_rank"] == 1
    assert all("target_weight" not in row and "future_return_label" not in row for row in current["rows"])
    for day in ("2026-09-23", "2026-09-25", "2026-01-03"):
        missing = reader.score_snapshot(day, package=payload)
        assert missing["status"] == "UNAVAILABLE" and missing["rows"] == []
        assert missing["requested_signal_date"] == day and missing["actual_signal_date"] is None
    historical = reader.score_snapshot("2026-01-05", package=payload)
    assert historical["rows"] == current["rows"]
    assert historical["actual_signal_date"] == "2026-01-05"
    current["rows"][0]["ticker"] = "MUTATED"
    assert payload["shared_scores"]["current"]["rows"][0]["ticker"] == "T40"


def test_stock_score_history_filters_stored_security_identity_and_dates_without_future_rows():
    payload = extended_package()
    history = reader.score_history(package=payload, ticker=" t20 ", security_id="SEC-20", end_date="2026-01-05")
    assert [row["signal_date"] for row in history] == ["2026-01-02", "2026-01-05"]
    assert all(row["ticker"] == "T20" and row["security_id"] == "SEC-20" for row in history)
    assert reader.score_history(package=payload, ticker="NEVER_SCORED") == []
    assert reader.score_history(package=payload, start_date="2026-09-23") == []
    history[0]["pred_hgb"] = 999
    assert reader.score_history(package=payload, ticker="T20")[0]["pred_hgb"] != 999
    with pytest.raises(ValueError, match="shared_scores.range"):
        reader.score_history(package=payload, start_date="2026-09-24", end_date="2026-01-01")


def test_blocked_current_scores_keep_the_requested_date_and_do_not_borrow_history():
    payload = extended_package()
    payload["shared_scores"]["current"] = {"status": "BLOCKED", "signal_date": None,
        "requested_signal_date": "2026-09-24", "rows": [], "reason": "CURRENT_FEATURE_HASH_FAILED"}
    snapshot = reader.score_snapshot(package=payload)
    assert snapshot["status"] == "BLOCKED" and snapshot["actual_signal_date"] is None
    assert snapshot["requested_signal_date"] == "2026-09-24" and snapshot["rows"] == []
    assert reader.score_snapshot("2026-09-22", package=payload)["status"] == "READY"


@pytest.mark.parametrize("corruption", ["cost", "net", "count", "sum", "gross", "fraction"])
def test_invalid_new_accounting_fields_fail_closed(corruption):
    payload = extended_package()
    point = payload["strategies"][reader.STRATEGY_IDS[0]]["daily"][0]
    if corruption == "cost":
        point["transaction_cost_amount"] *= 2
    elif corruption == "net":
        point["net_return"] = .5
    elif corruption == "count":
        point["holding_count"] = True
    elif corruption == "sum":
        point["turnover"] = .7
    elif corruption == "gross":
        point["gross_return"] = float("nan")
    else:
        point["transaction_cost_fraction"] = .8
    with pytest.raises(ValueError, match="SELECTED_HGB_PACKAGE_INVALID"):
        reader.validate_package(payload)


@pytest.mark.parametrize("corruption", ["rank", "order", "identity", "nonfinite", "label", "model", "future", "reason"])
def test_invalid_or_outcome_contaminated_shared_scores_fail_closed(corruption):
    payload = extended_package()
    current = payload["shared_scores"]["current"]
    if corruption == "rank":
        current["rows"][0]["raw_rank"] = current["rows"][1]["raw_rank"]
    elif corruption == "order":
        current["rows"][0]["hgb_rank"], current["rows"][1]["hgb_rank"] = 2, 1
    elif corruption == "identity":
        current["rows"][0]["security_id"] = current["rows"][1]["security_id"]
    elif corruption == "nonfinite":
        current["rows"][0]["pred_hgb"] = float("nan")
    elif corruption == "label":
        payload["shared_scores"]["historical"][0]["future_return_label"] = 1
    elif corruption == "model":
        payload["shared_scores"]["model_sha256"] = "ef" * 32
    elif corruption == "future":
        current["signal_date"] = "2026-09-25"
    else:
        current["reason"] = {"unexpected": "object"}
    with pytest.raises(ValueError, match="shared_scores"):
        reader.validate_package(payload)


@pytest.mark.parametrize("corruption", ["identity", "period", "calendar"])
def test_raw_reference_requires_same_batch_identity_period_and_calendar(corruption):
    payload = extended_package()
    raw = payload["raw_reference"]
    if corruption == "identity":
        raw["strategy_id"] = "RAW_FROM_OTHER_LEDGER"
    elif corruption == "period":
        raw["performance_period"]["price_basis"] = "PIT_MARKED_EXECUTED_LEDGER"
    else:
        raw["daily"][1]["date"] = "2026-01-03"
    with pytest.raises(ValueError, match="SELECTED_HGB_PACKAGE_INVALID"):
        reader.validate_package(payload)
