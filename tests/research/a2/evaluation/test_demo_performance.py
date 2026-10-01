"""Synthetic integration with the exact frozen open-ended engine; no outcomes."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

SOURCE = Path(__file__).parents[4] / "scripts/research/a2/evaluation/demo_performance.py"
spec = importlib.util.spec_from_file_location("updated_demo_performance_test_subject", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def case(tmp_path, monkeypatch):
    paths = SimpleNamespace(repo_root=Path("D:/us-tech-quant"), daily_root=tmp_path / "daily",
                            backtest_root=tmp_path / "backtests")
    work = paths.daily_root / "A2_historical_top40/runs/synthetic"
    work.mkdir(parents=True)
    days = pd.DatetimeIndex(["2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23"])
    tickers = [f"T{index:02}" for index in range(40)]
    records = [{"target_date": str(day.date()), "ticker": ticker, "security_id": "ID" + ticker,
        "rank": index + 1, "score": float(40 - index), "model_year": 2026,
        "model_sha256": module.MODEL_2026_SHA, "universe_id": "TEST_POOL",
        "universe_quarter": "2026Q2", "universe_effective_date": "2026-09-01",
        "institution_count": 25, "source": "SYNTHETIC"}
        for day in days[:-1] for index, ticker in enumerate(tickers)]
    rankings = pd.DataFrame(records)
    coverage = pd.DataFrame([{"target_date": str(day.date()), "status": "READY", "eligible_count": 40,
        "universe_member_count": 40, "mapped_count": 40, "excluded_count": 0, "quarter": "2026Q2",
        "effective_date": "2026-09-01", "institution_count": 25, "model_year": 2026} for day in days[:-1]])
    rankings.to_parquet(work / "top40.parquet", index=False)
    coverage.to_parquet(work / "coverage.parquet", index=False)
    hist = {"status": "READY", "generated_at": "2026-09-23T08:00:00Z",
        "report_path": str(work / "manifest.json"), "outputs": {"top40": module.reference(work / "top40.parquet"),
        "coverage": module.reference(work / "coverage.parquet")}, "models": {"artifacts": {"2026": {"sha256": module.MODEL_2026_SHA}}}}
    historical = work / "manifest.json"
    historical.write_text(json.dumps(hist))
    current = {"status": "READY", "model_id": "A2_HGB", "model_sha256": module.MODEL_2026_SHA,
        "data_date": "2026-09-22", "generated_at": "2026-09-23T09:00:00Z", "run_id": "synthetic_current",
        "ranked_rows": rankings.loc[rankings.target_date.eq("2026-09-22")].to_dict("records"),
        "universe": {"universe_id": "TEST_POOL", "quarter": "2026Q2", "effective_date": "2026-09-01",
                     "universe_member_count": 40, "institution_count": 25},
        "coverage": {"eligible_count": 40, "mapped_count": 40, "excluded_count": 0}}
    current_path = tmp_path / "recommendation_source.json"
    current["report_path"] = str(current_path)
    current_path.write_text(json.dumps(current))
    prices = pd.DataFrame([{"trade_date": day, "ticker": ticker, "open": 100. + index,
                            "close": 101. + index} for index, day in enumerate(days[:-1]) for ticker in tickers])
    events = pd.DataFrame(columns=["ticker", "event_date", "audit_kind"])
    helper = ModuleType("scripts.research.a2.evaluation.demo_performance_prices")
    helper.load_execution_prices = lambda *args, **kwargs: {"prices": prices, "events": events, "gaps": [], "refs": []}
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    engine_path = paths.repo_root / "scripts/v22/a_a2_2026_pre_risk_holdout_r1.py"
    assert module.digest(engine_path) == module.ENGINE_SHA
    engine_spec = importlib.util.spec_from_file_location("synthetic_bound_open_ledger", engine_path)
    engine = importlib.util.module_from_spec(engine_spec)
    monkeypatch.setitem(sys.modules, engine_spec.name, engine)
    engine_spec.loader.exec_module(engine)
    monkeypatch.setattr(module, "_authority", lambda _: (engine, [module.reference(engine_path)]))
    from scripts.research.a2.inference import historical_top40
    monkeypatch.setattr(historical_top40, "load_sessions", lambda _: (
        list(days.strftime("%Y-%m-%d")), {"current": {"target_date": "2026-09-22"}, "lineage": {"synthetic": True}}))
    return SimpleNamespace(paths=paths, days=days, rankings=rankings, prices=prices, events=events, helper=helper, engine=engine,
        current=current, current_path=current_path, historical=historical, hist=hist, work=work)


def run(case):
    return module.refresh_demo_performance(case.paths, case.historical, case.current_path)


def test_original_engine_keeps_terminal_holdings_and_pending_last_signal(case):
    result = run(case)
    assert result["status"] == "READY", result.get("error")
    assert result["performance_end_date"] == result["ranking_end_date"] == "2026-09-22"
    assert result["performance_points"] == 4 and result["return_observations"] == 3
    daily = pd.read_parquet(result["outputs"]["portfolio_daily"]["path"])
    book = pd.read_parquet(result["outputs"]["positions"]["path"])
    orders = pd.read_parquet(result["outputs"]["trades"]["path"])
    decisions = pd.read_parquet(result["outputs"]["decision_calendar"]["path"])
    assert daily.iloc[0].reconstructed_nav == 1 and daily.iloc[0].actual_risky_name_count == 0
    assert daily.iloc[-1].actual_risky_name_count == 20
    assert book.loc[book.date.eq(case.days[-2]), "shares_after"].gt(0).sum() == 20
    assert orders.date.min() == case.days[1]
    np.testing.assert_allclose(orders.allocated_transaction_cost, orders.notional * 0.0005, rtol=0, atol=1e-15)
    assert decisions.iloc[0].performance_cutoff_date == "2026-09-18"
    assert decisions.iloc[-1].execution_status == "PENDING_NEXT_OPEN"
    assert decisions.iloc[-1].scheduled_execution_date == "2026-09-23"
    assert pd.isna(decisions.iloc[-1].execution_date) and pd.isna(decisions.iloc[-1].portfolio_snapshot_date)
    for ref in result["outputs"].values():
        module.verified(ref)
    assert (case.paths.daily_root / "A2_updated_research/latest.json").is_file()
    contract = module.read(module.verified(result["evaluation_contract"]))
    assert contract["evaluation"] == module.EVALUATION
    assert contract["rankings"] == {key: result["outputs"]["rankings"][key] for key in ("path", "sha256")}


def test_explicit_execution_record_manifest_is_forwarded_to_original_price_reader(case):
    seen = []
    original = case.helper.load_execution_prices
    def reader(*args, **kwargs):
        seen.append(kwargs.get("current_execution_manifest_path"))
        return original(*args, **kwargs)
    case.helper.load_execution_prices = reader
    path = case.paths.daily_root / "execution_recovery/current_records.json"
    result = module.refresh_demo_performance(case.paths, case.historical, case.current_path,
                                             current_execution_manifest_path=path)
    assert result["status"] == "READY", result.get("error")
    assert seen == [path]


def test_last_day_new_ranking_is_not_executed_at_same_open(case):
    old = run(case)
    for row in case.current["ranked_rows"]:
        row["rank"] = 41 - row["rank"]
    case.current_path.write_text(json.dumps(case.current))
    new = run(case)
    assert new["status"] == "READY"
    pd.testing.assert_frame_equal(pd.read_parquet(old["outputs"]["portfolio_daily"]["path"]),
                                  pd.read_parquet(new["outputs"]["portfolio_daily"]["path"]))
    rank = pd.read_parquet(new["outputs"]["rankings"]["path"])
    assert rank.loc[rank.target_date.eq("2026-09-22")].iloc[0].ticker == "T39"


def test_missing_execution_open_retains_safe_prefix_without_liquidating(case):
    case.prices.loc[case.prices.trade_date.eq(case.days[2]) & case.prices.ticker.eq("T00"), "open"] = np.nan
    result = run(case)
    assert result["status"] == "PARTIAL" and result["performance_end_date"] == "2026-09-18"
    assert result["blocking_input"]["date"] == "2026-09-21"
    assert result["blocking_input"]["missing_open_tickers"] == ["T00"]
    daily = pd.read_parquet(result["outputs"]["portfolio_daily"]["path"])
    assert daily.iloc[-1].actual_risky_name_count == 20
    decisions = pd.read_parquet(result["outputs"]["decision_calendar"]["path"])
    assert decisions.iloc[1].execution_status == "BLOCKED_PRICE_INPUT"
    assert decisions.iloc[1].performance_cutoff_date == "2026-09-18"


def test_held_corporate_action_exception_stops_the_same_safe_prefix(case):
    case.helper.load_execution_prices = lambda *args, **kwargs: {"prices": case.prices,
        "events": pd.DataFrame([{"event_date": case.days[2], "ticker": "T00", "audit_kind": "LARGE_RAW_MOVE_NO_VENDOR_EVENT"}]),
        "gaps": [], "refs": []}
    result = run(case)
    assert result["status"] == "PARTIAL" and result["performance_end_date"] == "2026-09-18"
    assert result["blocking_input"]["reason"] == "HELD_CORPORATE_ACTION_EXCEPTION"


@pytest.mark.parametrize("fault", ["model", "source_hash", "missing_rank"])
def test_failed_refresh_preserves_prior_display_pointer(case, fault):
    good = run(case)
    pointer = case.paths.daily_root / "A2_updated_research/latest.json"
    previous = pointer.read_bytes()
    if fault == "model":
        case.current["model_sha256"] = "0" * 64
        case.current_path.write_text(json.dumps(case.current))
    elif fault == "source_hash":
        (case.work / "top40.parquet").write_bytes(b"changed immutable input")
    else:
        case.current["ranked_rows"].pop()
        case.current_path.write_text(json.dumps(case.current))
    result = run(case)
    assert result["status"] == "BLOCKED" and result["error"]
    assert pointer.read_bytes() == previous
    assert good["run_id"] != result["run_id"]


def test_missing_signal_session_blocks(case):
    # A later signal without the intervening observation cannot be bridged.
    rankings = case.rankings.loc[~case.rankings.target_date.eq("2026-09-21")]
    rankings.to_parquet(case.work / "top40.parquet", index=False)
    case.hist["outputs"]["top40"] = module.reference(case.work / "top40.parquet")
    case.historical.write_text(json.dumps(case.hist))
    result = run(case)
    assert result["status"] == "BLOCKED" and "SESSION_COVERAGE" in result["error"]


@pytest.mark.parametrize("stamp,expected", [
    ("2026-09-23T07:59:59Z", "T00"), ("2026-09-23T08:00:00Z", "T00"),
    ("2026-09-23T08:00:01Z", "T39")])
def test_same_day_daily_only_replaces_strictly_older_historical_run(case, stamp, expected):
    case.current["generated_at"] = stamp
    for row in case.current["ranked_rows"]:
        row["rank"] = 41 - row["rank"]
    case.current_path.write_text(json.dumps(case.current))
    result = run(case)
    assert result["status"] == "READY", result.get("error")
    frame = pd.read_parquet(result["outputs"]["rankings"]["path"])
    assert frame.loc[frame.target_date.eq("2026-09-22")].iloc[0].ticker == expected


def test_evaluation_contract_exists_before_original_engine_is_called(case, monkeypatch):
    original = case.engine.reconstruct_open_ended
    seen = []
    def checked(*args, **kwargs):
        files = list((case.paths.daily_root / "A2_updated_research/runs").glob("*/evaluation_contract.json"))
        assert len(files) == 1
        contract = module.read(files[0])
        assert not (files[0].parent / "portfolio_daily.parquet").exists()
        for ref in contract["authorities"] + contract["input_refs"] + [contract["rankings"], contract["price_inputs"]]:
            module.verified(ref)
        seen.append(contract)
        return original(*args, **kwargs)
    monkeypatch.setattr(case.engine, "reconstruct_open_ended", checked)
    result = run(case)
    assert result["status"] == "READY", result.get("error")
    assert len(seen) == 1


def test_daily_history_fills_intervening_new_signal_without_future_history(case):
    # Historical replay ends on the first date; daily history supplies the next
    # two observations. A future saved report must not advance this request.
    case.rankings.loc[case.rankings.target_date.eq("2026-09-17")].to_parquet(case.work / "top40.parquet", index=False)
    coverage = pd.read_parquet(case.work / "coverage.parquet")
    coverage.loc[coverage.target_date.eq("2026-09-17")].to_parquet(case.work / "coverage.parquet", index=False)
    case.hist["outputs"] = {key: module.reference(case.work / (key + ".parquet")) for key in ("top40", "coverage")}
    case.historical.write_text(json.dumps(case.hist))
    history = case.paths.daily_root / "A2_today_recommendation/history"
    history.mkdir(parents=True)
    for day in ("2026-09-18", "2026-09-21", "2026-09-23"):
        report = dict(case.current, data_date=day, report_path=str(history / (day + ".json")))
        (history / (day + ".json")).write_text(json.dumps(report))
    result = run(case)
    assert result["status"] == "READY", result.get("error")
    assert result["ranking_days"] == 4 and result["ranking_end_date"] == "2026-09-22"
    assert len(result["recommendation_reports"]) == 3


def test_latest_manifest_is_resolved_and_bound_to_immutable_copy(case):
    pointer = case.paths.daily_root / "A2_historical_top40/latest.json"
    pointer.write_bytes(case.historical.read_bytes())
    result = module.refresh_demo_performance(case.paths, pointer, case.current_path)
    assert result["status"] == "READY", result.get("error")
    assert result["ranking_manifest"] == module.reference(case.historical)
    assert module.reference(pointer) not in result["input_refs"]
    pointer.write_text(json.dumps(dict(case.hist, generated_at="2026-09-23T10:00:00Z")))
    failed = module.refresh_demo_performance(case.paths, pointer, case.current_path)
    assert failed["status"] == "BLOCKED" and "CANONICAL_HASH_MISMATCH" in failed["error"]


def reviewed_case(case):
    events = pd.DataFrame([{"event_date": case.days[2], "ticker": "T00", "code": "US.T00",
        "audit_kind": "LARGE_RAW_MOVE_NO_VENDOR_EVENT", "raw_jump": 0.91}])
    review = {"schema": "A2_EXECUTION_EVENT_REVIEW_V1", "policy": module.EVENT_REVIEW_POLICY,
        "records": [{"event_date": "2026-09-21", "ticker": "T00", "code": "US.T00",
            "audit_kind": "LARGE_RAW_MOVE_NO_VENDOR_EVENT", "raw_jump": 0.91,
            "status": "RESOLVED_NON_CORPORATE_ACTION"}]}
    path = case.paths.daily_root / "synthetic_event_review.json"
    path.write_text(json.dumps(review))
    ref = module.reference(path)
    case.helper.load_execution_prices = lambda *args, **kwargs: {"prices": case.prices,
        "events": events, "gaps": [], "refs": [ref], "event_review": ref}
    return events, review, path, ref


def test_factual_event_review_resolves_only_exact_flag_and_retains_original_audit(case):
    _, _, _, ref = reviewed_case(case)
    result = run(case)
    assert result["status"] == "READY", result.get("error")
    assert result["performance_end_date"] == "2026-09-22"
    assert result["resolved_non_corporate_action_count"] == 1
    event = pd.read_parquet(result["outputs"]["corporate_action_events"]["path"]).iloc[0]
    assert event.audit_kind == "LARGE_RAW_MOVE_NO_VENDOR_EVENT" and event.raw_jump == 0.91
    assert event.resolution_status == "RESOLVED_NON_CORPORATE_ACTION"
    contract = module.read(module.verified(result["evaluation_contract"]))
    assert contract["event_review"] == ref
    assert contract["resolved_non_corporate_action_events"] == [{"ticker": "T00", "event_date": "2026-09-21"}]


def test_resolving_one_event_never_disables_other_held_event_stop(case):
    events, _, _, _ = reviewed_case(case)
    events.loc[len(events)] = {"event_date": case.days[3], "ticker": "T01", "code": "US.T01",
        "audit_kind": "LARGE_RAW_MOVE_NO_VENDOR_EVENT", "raw_jump": 0.95}
    result = run(case)
    assert result["status"] == "PARTIAL" and result["performance_end_date"] == "2026-09-21"
    assert result["blocking_input"]["corporate_action_tickers"] == ["T01"]


@pytest.mark.parametrize("fault", ["identity", "jump", "hash", "unbound"])
def test_event_review_cannot_resolve_different_or_unbound_source_fact(case, fault):
    events, review, path, ref = reviewed_case(case)
    if fault == "identity":
        review["records"][0]["code"] = "US.OTHER"
    elif fault == "jump":
        review["records"][0]["raw_jump"] = 0.90
    if fault in {"identity", "jump", "hash"}:
        path.write_text(json.dumps(review) + "\n")
        if fault != "hash":
            ref.update(module.reference(path))
    else:
        case.helper.load_execution_prices = lambda *args, **kwargs: {"prices": case.prices,
            "events": events, "gaps": [], "refs": [], "event_review": ref}
    result = run(case)
    assert result["status"] == "BLOCKED"
    assert "EVENT_REVIEW" in result["error"] or "SOURCE_HASH_CHANGED" in result["error"]
    assert not (Path(result["report_path"]).parent / "evaluation_contract.json").exists()


@pytest.fixture
def missed(case, monkeypatch):
    from scripts.research.a2.inference import historical_top40 as runner
    from scripts.research.a2.inference import historical_top40_universe as universe
    from scripts.research.a2.inference import historical_top40_models as models
    from scripts.research.a2.inference import historical_top40_prices as prices
    columns = [f"f{index}" for index in range(32)]
    case.rankings.loc[case.rankings.target_date.eq("2026-09-17")].to_parquet(case.work / "top40.parquet", index=False)
    count = pd.read_parquet(case.work / "coverage.parquet")
    count.loc[count.target_date.eq("2026-09-17")].to_parquet(case.work / "coverage.parquet", index=False)
    case.hist["outputs"] = {key: module.reference(case.work / (key + ".parquet")) for key in ("top40", "coverage")}
    case.hist["models"]["feature_columns"] = columns
    case.historical.write_text(json.dumps(case.hist))
    universe_path = case.current_path.parent / "synthetic_universe.json"
    universe_path.write_text("{}")
    case.current["universe"]["report_path"] = str(universe_path)
    case.current["acquisitions"] = {"synthetic": True}
    case.current_path.write_text(json.dumps(case.current))
    (case.current_path.parent / "rehab_receipt.json").write_text('{"results": []}')
    schedule = pd.DataFrame([{"snapshot_id": label, "universe_id": label, "quarter": "2026Q2",
        "effective_date": date, "snapshot_effective_date": date, "institution_count": 25,
        "universe_member_count": 40, "mapped_count": 40}
        for label, date in (("OLD", "2026-09-01"), ("NEW", "2026-09-21"))])
    members = pd.DataFrame([{"snapshot_id": label, "security_id": f"IDT{index:02}", "ticker": f"T{index:02}",
        "moomoo_symbol": f"US.T{index:02}"} for label, offset in (("OLD", 0), ("NEW", 1)) for index in range(offset, offset + 40)])
    ledger = pd.DataFrame([{"target_date": day, "snapshot_id": "OLD" if day < "2026-09-21" else "NEW"}
        for day in ("2026-09-18", "2026-09-21", "2026-09-22")])
    state = SimpleNamespace(case=case, calls=[], feature_calls=[], reader_calls=[],
        features=pd.DataFrame([{"trade_date": day, "ticker": f"T{index:02}",
            **{name: 100.0 - index for name in columns}}
            for day in pd.to_datetime(ledger.target_date) for index in range(41)]))
    def pool(*args, **kwargs):
        state.calls.append(("universe", args[1:3], kwargs))
        assert args[4] == str(universe_path) and kwargs["mode"] == "registry25"
        return {"schedule": schedule, "members": members, "ledger": ledger, "lineage": {}, "gaps": []}
    model = {"status": "FROZEN_REFERENCE", "sha256": module.MODEL_2026_SHA,
        "path": "D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/final_full_pre2026_hgb.joblib",
        "model_role": "FROZEN_FULL_PRE2026_FOR_2026_INFERENCE_ONLY", "labelmax": "2025-12-31"}
    state.models = {"status": "READY", "model_fit_count": 0, "artifacts": {"2026": model}, "feature_columns": columns}
    def frozen(*args, **kwargs):
        state.calls.append(("models", kwargs))
        assert kwargs == {"years": (2026,), "execute": False}
        return state.models
    def features(*args):
        state.feature_calls.append(args)
        price_work = Path(args[-1]) / "prices"
        price_work.mkdir(parents=True)
        (price_work / "manifest.json").write_text('{"synthetic_features": true}')
        return state.features, [{"synthetic_accepted_lineage": True}], []
    class Fixed:
        def predict(self, x):
            return x[:, 0]
        def fit(self, *args, **kwargs):
            raise AssertionError("GAP_INFERENCE_MUST_NEVER_FIT")
    real_ranked = runner.ranked_predictions
    monkeypatch.setattr(universe, "build_universe_schedule", pool)
    monkeypatch.setattr(models, "build_models", frozen)
    monkeypatch.setattr(prices, "build_price_features", features)
    monkeypatch.setattr(runner, "ranked_predictions", lambda *args: real_ranked(*args, model_loader=lambda _: Fixed()))
    def reader(*args, **kwargs):
        state.reader_calls.append(kwargs)
        return {"prices": case.prices, "events": case.events, "gaps": [], "refs": []}
    case.helper.load_execution_prices = reader
    return state


def test_missed_sessions_use_each_pit_pool_frozen_prediction_and_separate_audit(missed):
    case = missed.case
    before = case.historical.read_bytes()
    result = run(case)
    assert result["status"] == "READY", result.get("error")
    ranks = pd.read_parquet(result["outputs"]["rankings"]["path"])
    assert ranks.loc[ranks.target_date.eq("2026-09-18")].iloc[0].ticker == "T00"
    assert ranks.loc[ranks.target_date.eq("2026-09-21")].iloc[0].ticker == "T01"
    assert ranks.loc[ranks.target_date.isin(["2026-09-18", "2026-09-21"]), "source"].eq("MISSED_SESSION_DESCRIPTIVE_REPLAY").all()
    assert ranks.loc[ranks.target_date.eq("2026-09-17"), "source"].eq("SYNTHETIC").all()
    assert case.historical.read_bytes() == before
    assert not (case.paths.daily_root / "A2_today_recommendation/history").exists()
    assert not (case.paths.daily_root / "A2_historical_top40/latest.json").exists()
    inference = module.read(module.verified(result["missing_signal_inference"]))
    assert inference["missing_dates"] == ["2026-09-18", "2026-09-21"]
    assert inference["model_fit_count"] == 0 and inference["forward_history_created"] is False
    assert missed.reader_calls[0]["inference_manifest_path"] == result["missing_signal_inference"]["path"]
    assert missed.feature_calls[0][2:4] == ("2026-09-18", "2026-09-22")
    assert {row["snapshot_id"] for row in missed.feature_calls[0][1]} == {"OLD", "NEW"}


def test_missed_session_with_fewer_than_40_verified_inputs_blocks_before_performance(missed, monkeypatch):
    missed.features = missed.features.loc[~(missed.features.trade_date.eq(pd.Timestamp("2026-09-18")) & missed.features.ticker.eq("T00"))]
    monkeypatch.setattr(missed.case.engine, "reconstruct_open_ended", lambda *args: pytest.fail("must not compute incomplete signals"))
    result = run(missed.case)
    assert result["status"] == "BLOCKED" and "MISSING_SIGNAL_TOP40_INPUTS_INCOMPLETE" in result["error"]
    path = Path(result["report_path"]).parent / "missing_signals/manifest.json"
    assert module.read(path)["status"] == "BLOCKED"
    assert not (missed.case.paths.daily_root / "A2_updated_research/latest.json").exists()


def test_gap_model_identity_failure_never_reaches_features_or_fit(missed):
    missed.models["artifacts"]["2026"]["sha256"] = "0" * 64
    result = run(missed.case)
    assert result["status"] == "BLOCKED" and "FROZEN_2026_REFERENCE_ONLY" in result["error"]
    assert not missed.feature_calls


def test_complete_signal_sequence_does_not_call_gap_components(case, monkeypatch):
    from scripts.research.a2.inference import historical_top40_models, historical_top40_universe, historical_top40_prices
    for component, name in ((historical_top40_models, "build_models"), (historical_top40_universe, "build_universe_schedule"),
                            (historical_top40_prices, "build_price_features")):
        monkeypatch.setattr(component, name, lambda *args, **kwargs: pytest.fail("complete sequence must not rebuild"))
    result = run(case)
    assert result["status"] == "READY", result.get("error")
    assert result["missing_signal_inference"] is None
    assert not (Path(result["report_path"]).parent / "missing_signals").exists()


@pytest.fixture
def retained_replay(missed, monkeypatch):
    case = missed.case
    raw_proof = case.current_path.parent / "verified_execution_source.parquet"
    case.prices.to_parquet(raw_proof, index=False)
    raw_ref = module.reference(raw_proof)
    reader = case.helper.load_execution_prices
    def bound_reader(*args, **kwargs):
        return {**reader(*args, **kwargs), "refs": [raw_ref],
                "price_basis": module.EVALUATION["price_basis"],
                "start_date": kwargs["start"], "end_date": kwargs["end"],
                "vintage_semantics": "LATER_VENDOR_REHAB_SNAPSHOT_NOT_HISTORICAL_PUBLICATION_VINTAGE"}
    case.helper.load_execution_prices = bound_reader
    prior = run(case)
    assert prior["status"] == "READY", prior.get("error")
    pointer = case.paths.daily_root / "A2_updated_research/latest.json"
    old_pointer = pointer.read_bytes()
    history = case.paths.daily_root / "A2_today_recommendation/history"
    history.mkdir(parents=True)
    (history / "saved_22.json").write_bytes(case.current_path.read_bytes())
    next_path = case.current_path.parent / "next" / "recommendation_source.json"
    next_path.parent.mkdir()
    case.current = {**case.current, "data_date": "2026-09-23", "generated_at": "2026-09-24T09:00:00Z",
                    "run_id": "synthetic_next", "report_path": str(next_path)}
    next_path.write_text(json.dumps(case.current))
    case.current_path = next_path
    case.prices = pd.concat([case.prices, pd.DataFrame([
        {"trade_date": case.days[-1], "ticker": f"T{index:02}", "open": 104., "close": 105.}
        for index in range(40)])], ignore_index=True)
    from scripts.research.a2.inference import historical_top40
    monkeypatch.setattr(historical_top40, "load_sessions", lambda _: (
        list(case.days.strftime("%Y-%m-%d")), {"current": {"target_date": "2026-09-23"}, "lineage": {"synthetic": True}}))
    return SimpleNamespace(case=case, missed=missed, prior=prior, prior_path=Path(prior["report_path"]),
                           pointer=pointer, old_pointer=old_pointer, raw_proof=raw_proof, raw_ref=raw_ref)


def retained_run(state):
    return module.refresh_demo_performance(state.case.paths, state.case.historical, state.case.current_path,
                                          prior_verified_performance_manifest_path=state.prior_path)


@pytest.mark.parametrize("future_complete", [True, False])
def test_verified_prior_missing_signals_and_execution_prefix_are_retained(retained_replay, future_complete):
    state, case = retained_replay, retained_replay.case
    before = (len(state.missed.calls), len(state.missed.feature_calls))
    # The current price snapshot lost earlier qualified tails. It must not lose
    # either previously accepted rankings or marks in the completed replay.
    case.prices = case.prices.loc[case.prices.trade_date.isin([case.days[0], case.days[-1]])].copy()
    if not future_complete:
        case.prices = case.prices.loc[~(case.prices.trade_date.eq(case.days[-1]) & case.prices.ticker.eq("T00"))]
    result = retained_run(state)
    assert result["status"] == ("READY" if future_complete else "PARTIAL"), result.get("error")
    assert result["performance_end_date"] == ("2026-09-23" if future_complete else "2026-09-22")
    assert result["ranking_end_date"] == "2026-09-23"
    assert result["prior_verified_performance"]["reused_signal_dates"] == ["2026-09-18", "2026-09-21"]
    assert result["prior_verified_performance"]["prefix_verification"] == "PASSED"
    assert before == (len(state.missed.calls), len(state.missed.feature_calls))
    assert result["missing_signal_inference"] is None
    prior = {"frames": {name: pd.read_parquet(ref["path"]) for name, ref in state.prior["outputs"].items()},
             "cutoff": "2026-09-22"}
    for name, column, keys in (
        ("rankings", "target_date", ["target_date", "rank"]), ("coverage", "target_date", ["target_date"]),
        ("portfolio_daily", "execution_date", ["execution_date"]), ("positions", "date", ["date", "ticker"]),
        ("trades", "date", ["date", "ticker", "side"]), ("price_paths", "date", ["date", "ticker"])):
        module._assert_prior_prefix(name, pd.read_parquet(result["outputs"][name]["path"]), prior, column, keys)
    contract = module.read(module.verified(result["evaluation_contract"]))
    assert contract["prior_verified_performance"]["manifest"] == module.reference(state.prior_path)
    assert state.raw_ref in contract["price_refs"]
    for ref in contract["input_refs"] + contract["price_refs"]:
        module.verified(ref)


def test_prior_marks_do_not_invent_raw_ohlcv_or_apply_to_future(retained_replay, monkeypatch):
    state, case = retained_replay, retained_replay.case
    case.prices = case.prices.loc[case.prices.trade_date.eq(case.days[-1])].copy()
    case.prices["high"], case.prices["low"], case.prices["volume"] = 106., 103., 1000.
    seen = []
    original = case.engine.reconstruct_open_ended
    def checked(model, targets, prices, calendar, cutoff):
        prefix = prices.loc[prices.trade_date.le(case.days[-2])]
        assert prefix[["high", "low", "volume"]].isna().all().all()
        assert len(prefix) == 160  # Includes every old key, not only new Top20.
        assert prices.loc[prices.trade_date.eq(case.days[-1]), "volume"].eq(1000.).all()
        seen.append(True)
        return original(model, targets, prices, calendar, cutoff)
    monkeypatch.setattr(case.engine, "reconstruct_open_ended", checked)
    result = retained_run(state)
    assert result["status"] == "READY", result.get("error")
    assert seen == [True]


def test_saved_ready_conflict_is_not_overwritten_by_prior_replay(retained_replay):
    state, case = retained_replay, retained_replay.case
    history = case.paths.daily_root / "A2_today_recommendation/history/changed_21.json"
    conflict = {**case.current, "data_date": "2026-09-21", "report_path": str(history)}
    history.write_text(json.dumps(conflict))
    before = history.read_bytes()
    result = retained_run(state)
    assert result["status"] == "BLOCKED" and "PREFIX_CHANGED:rankings" in result["error"]
    assert state.pointer.read_bytes() == state.old_pointer
    assert history.read_bytes() == before


def test_saved_ready_coverage_conflict_is_not_silently_replaced(retained_replay):
    state, case = retained_replay, retained_replay.case
    contract = module.read(module.verified(state.prior["evaluation_contract"]))
    saved = module.read(module.verified(contract["current_report"]))
    history = case.paths.daily_root / "A2_today_recommendation/history/changed_22.json"
    saved.update(report_path=str(history), generated_at="2026-09-24T10:00:00Z")
    saved["coverage"].update(eligible_count=41, excluded_count=1)
    history.write_text(json.dumps(saved))
    result = retained_run(state)
    assert result["status"] == "BLOCKED" and "PREFIX_CHANGED:coverage" in result["error"]
    assert state.pointer.read_bytes() == state.old_pointer


def test_hash_valid_prior_scores_still_require_the_same_frozen_model(retained_replay):
    state = retained_replay
    prior = module.read(state.prior_path)
    rank_path = Path(prior["outputs"]["rankings"]["path"])
    ranks = pd.read_parquet(rank_path)
    ranks["model_sha256"] = "0" * 64
    ranks.to_parquet(rank_path, index=False)
    prior["outputs"]["rankings"] = {**module.reference(rank_path), "rows": len(ranks)}
    contract_path = Path(prior["evaluation_contract"]["path"])
    contract = module.read(contract_path)
    contract["rankings"] = module.reference(rank_path)
    contract_path.write_text(json.dumps(contract))
    prior["evaluation_contract"] = module.reference(contract_path)
    state.prior_path.write_text(json.dumps(prior))
    result = retained_run(state)
    assert result["status"] == "BLOCKED" and "RANKING_MODEL_IDENTITY" in result["error"]
    assert state.pointer.read_bytes() == state.old_pointer


@pytest.mark.parametrize("fault", ["historical", "evaluation", "calendar", "source_hash", "price_hash", "contract", "pointer"])
def test_prior_replay_requires_immutable_identity_and_complete_price_proof(retained_replay, fault):
    state = retained_replay
    prior = module.read(state.prior_path)
    if fault == "historical":
        prior["ranking_manifest"]["sha256"] = "0" * 64
    elif fault == "evaluation":
        prior["evaluation"]["cost_bps_round_trip"] = 0
    elif fault == "calendar":
        prior["calendar_lineage"] = {"synthetic": False}
    elif fault == "source_hash":
        state.raw_proof.write_bytes(b"changed raw provenance")
    elif fault == "price_hash":
        Path(prior["outputs"]["price_paths"]["path"]).write_bytes(b"changed prior marks")
    elif fault == "contract":
        path = Path(prior["evaluation_contract"]["path"])
        contract = module.read(path)
        contract["execution_price_extension"]["model_feature_eligibility_granted"] = True
        path.write_text(json.dumps(contract))
        prior["evaluation_contract"] = module.reference(path)
    else:
        state.prior_path = state.pointer
    if fault not in {"source_hash", "price_hash", "pointer"}:
        state.prior_path.write_text(json.dumps(prior))
    result = retained_run(state)
    assert result["status"] == "BLOCKED", result
    assert "PRIOR_PERFORMANCE" in result["error"] or "SOURCE_HASH_CHANGED" in result["error"]
    assert state.pointer.read_bytes() == state.old_pointer


def test_changed_current_overlap_never_replaces_a_verified_price(retained_replay):
    state, case = retained_replay, retained_replay.case
    case.prices.loc[0, "open"] += 1e-10
    result = retained_run(state)
    assert result["status"] == "BLOCKED" and "PREFIX_CHANGED:price_paths" in result["error"]
    assert state.pointer.read_bytes() == state.old_pointer


def make_close_review(state, monkeypatch):
    case = state.case
    folder = case.current_path.parent
    day = pd.Timestamp(state.prior["performance_end_date"])
    target = case.prices.trade_date.eq(day) & case.prices.ticker.eq("T00")
    before = case.prices.loc[target].iloc[0].copy()
    case.prices.loc[target, "close"] += .04
    captured = folder / "reviewed_prices.parquet"
    case.prices.to_parquet(captured, index=False)
    quotes = []
    for name, closing, observed in (("old", before.close, "2026-09-22T20:10:00Z"),
                                     ("new", before.close + .04, "2026-09-23T20:10:00Z")):
        path = folder / (name + "_raw.csv")
        pd.DataFrame([{"date": str(day.date()), "ticker": "T00", "moomoo_symbol": "US.T00",
            "open": before.open, "close": closing, "high": 1000., "low": 1., "source": "MOOMOO_OPEND",
            "adjustment": "raw", "fetched_at_utc": observed}]).to_csv(path, index=False)
        quotes.append(module.reference(path))
    anchor, rehab = folder / "anchor.bin", folder / "rehab.bin"
    anchor.write_bytes(b"unchanged native anchor")
    rehab.write_bytes(b"unchanged corporate-action factors")
    anchor_ref, rehab_ref = module.reference(anchor), module.reference(rehab)
    def source_entries(path, *args):
        quote = quotes[1] if Path(path) == case.current_path else quotes[0]
        return [{"ticker": "T00", "raw_sources": [quote, anchor_ref], "rehab": rehab_ref}], {}
    monkeypatch.setattr(case.helper, "_current_entries", source_entries, raising=False)
    audit = {"schema": "A2_RETAINED_CLOSE_VINTAGE_REVIEW_V1",
        "policy": "RETAIN_OLD_EXACT_MARKS_APPEND_NEW_DATES", "allowed_fields": ["close"],
        "prior_manifest": module.reference(state.prior_path), "current_report": module.reference(case.current_path),
        "captured_current_prices": module.reference(captured), "source_refs": [*quotes, anchor_ref, rehab_ref],
        "reviews": [{"date": str(day.date()), "ticker": "T00", "old_raw": quotes[0], "new_raw": quotes[1],
                     "shared_anchor": anchor_ref, "shared_rehab": rehab_ref}]}
    path = folder / "close_review.json"
    path.write_text(json.dumps(audit))
    return path


def test_reviewed_native_close_revision_retains_every_prior_economic_field(retained_replay, monkeypatch):
    state = retained_replay
    audit = make_close_review(state, monkeypatch)
    result = module.refresh_demo_performance(state.case.paths, state.case.historical, state.case.current_path,
        prior_verified_performance_manifest_path=state.prior_path, close_vintage_review_path=audit)
    assert result["status"] == "READY", result.get("error")
    for name in ("price_paths", "portfolio_daily", "positions", "trades"):
        old = pd.read_parquet(state.prior["outputs"][name]["path"])
        new = pd.read_parquet(result["outputs"][name]["path"])
        date = "execution_date" if name == "portfolio_daily" else "date"
        prefix = new.loc[new[date].le(pd.Timestamp(state.prior["performance_end_date"]))]
        pd.testing.assert_frame_equal(old.reset_index(drop=True), prefix.reset_index(drop=True), check_exact=True)
    assert module.read(result["evaluation_contract"]["path"])["retained_close_vintage_review"] == module.reference(audit)


@pytest.mark.parametrize("fault", ["open", "unreviewed_close", "source_hash"])
def test_close_review_cannot_approve_other_prices_or_changed_sources(retained_replay, monkeypatch, fault):
    state = retained_replay
    audit = make_close_review(state, monkeypatch)
    if fault == "open":
        state.case.prices.loc[0, "open"] += .01
    elif fault == "unreviewed_close":
        state.case.prices.loc[0, "close"] += .01
    else:
        (audit.parent / "new_raw.csv").write_bytes(b"changed source")
    result = module.refresh_demo_performance(state.case.paths, state.case.historical, state.case.current_path,
        prior_verified_performance_manifest_path=state.prior_path, close_vintage_review_path=audit)
    assert result["status"] == "BLOCKED"
    assert state.pointer.read_bytes() == state.old_pointer


@pytest.mark.parametrize("field", ["nav", "positions", "trades"])
def test_prior_economic_prefix_is_checked_before_publication(retained_replay, monkeypatch, field):
    state = retained_replay
    original = module.normalize_ledger
    def changed(*args):
        daily, book, orders = original(*args)
        if field == "nav":
            daily.loc[0, "reconstructed_nav"] += 1e-10
        elif field == "positions":
            book.loc[0, "shares_after"] += 1e-10
        else:
            orders.loc[0, "allocated_transaction_cost"] += 1e-10
        return daily, book, orders
    monkeypatch.setattr(module, "normalize_ledger", changed)
    result = retained_run(state)
    expected = "portfolio_daily" if field == "nav" else field
    assert result["status"] == "BLOCKED" and "PREFIX_CHANGED:" + expected in result["error"]
    assert state.pointer.read_bytes() == state.old_pointer
