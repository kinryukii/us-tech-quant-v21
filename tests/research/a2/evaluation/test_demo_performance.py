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


def synthetic_price_input(kwargs, prices, events, refs):
    # Match the original reader's qualified rows and complete provenance shape.
    qualified = prices.loc[np.isfinite(prices.open.to_numpy(float)) & prices.open.gt(0)].copy()
    return {"prices": qualified, "events": events, "gaps": [], "refs": refs,
        "price_basis": module.EVALUATION["price_basis"], "start_date": kwargs["start"], "end_date": kwargs["end"],
        "vintage_semantics": "LATER_VENDOR_REHAB_SNAPSHOT_NOT_HISTORICAL_PUBLICATION_VINTAGE"}


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
    helper.load_execution_prices = lambda *args, **kwargs: synthetic_price_input(kwargs, prices, events,
        [module.reference(current_path)])
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
    case.helper.load_execution_prices = lambda *args, **kwargs: synthetic_price_input(kwargs, case.prices,
        pd.DataFrame([{"event_date": case.days[2], "ticker": "T00", "audit_kind": "LARGE_RAW_MOVE_NO_VENDOR_EVENT"}]),
        [module.reference(case.current_path)])
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
    case.helper.load_execution_prices = lambda *args, **kwargs: {
        **synthetic_price_input(kwargs, case.prices, events, [ref]), "event_review": ref}
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
        return synthetic_price_input(kwargs, case.prices, case.events, [module.reference(case.current_path)])
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


def inherited_close_chain(state, monkeypatch, days=None, tickers=None):
    """Existing synthetic prior prices with independently bound V1 origins."""
    case = state.case
    folder = case.current_path.parent / "inherited-close-proofs"
    folder.mkdir()
    days = days or [case.days[-3], case.days[-2]]
    tickers = tickers or [f"T{index:02}" for index in range(len(days))]
    original = pd.read_parquet(state.prior["outputs"]["price_paths"]["path"])
    current = case.prices.copy()
    for index, day in enumerate(days):
        current.loc[current.trade_date.eq(day) & current.ticker.eq(tickers[index]), "close"] += .04 + index / 100
    captured = folder / "captured.parquet"
    current.to_parquet(captured, index=False)
    anchor, rehab = folder / "anchor.bin", folder / "rehab.bin"
    anchor.write_bytes(b"same qualified raw anchor")
    rehab.write_bytes(b"same frozen price-coordinate factors")
    anchor_ref, rehab_ref = module.reference(anchor), module.reference(rehab)
    sources, audits, refs, raw_refs = {}, [], [], []
    previous = None
    for index, day in enumerate(days):
        ticker = tickers[index]
        old = original.loc[original.date.eq(day) & original.ticker.eq(ticker)].iloc[0]
        new = current.loc[current.trade_date.eq(day) & current.ticker.eq(ticker)].iloc[0]
        quotes = []
        for role, value, stamp in (("old", old.close, day + pd.Timedelta(hours=20, minutes=10)),
                                    ("new", new.close, day + pd.Timedelta(days=1, hours=20, minutes=10))):
            path = folder / f"{index}-{role}.csv"
            pd.DataFrame([{"date": str(day.date()), "ticker": ticker, "moomoo_symbol": "US." + ticker,
                "open": old.open, "high": 1000., "low": 1., "close": value, "source": "MOOMOO_OPEND",
                "adjustment": "raw", "fetched_at_utc": stamp.tz_localize("UTC").isoformat()}]).to_csv(path, index=False)
            quote = module.reference(path)
            quotes.append(quote)
            report = folder / f"{index}-{role}-report.json"
            report.write_text(json.dumps({"fixture": "qualified synthetic source"}))
            sources[str(report)] = [{"ticker": ticker, "raw_sources": [quote, anchor_ref], "rehab": rehab_ref}]
        old_report, new_report = (folder / f"{index}-{role}-report.json" for role in ("old", "new"))
        owner = {"current_report": module.reference(old_report)}
        if previous is not None:
            owner["retained_close_vintage_review"] = previous
        contract = folder / f"{index}-contract.json"
        contract.write_text(json.dumps(owner))
        origin = folder / f"{index}-origin.json"
        origin.write_text(json.dumps({"performance_end_date": str(day.date()),
            "ranking_manifest": state.prior["ranking_manifest"], "evaluation_contract": module.reference(contract),
            "outputs": {"price_paths": state.prior["outputs"]["price_paths"]}}))
        audit = {"schema": "A2_RETAINED_CLOSE_VINTAGE_REVIEW_V1",
            "policy": "RETAIN_OLD_EXACT_MARKS_APPEND_NEW_DATES", "allowed_fields": ["close"],
            "prior_manifest": module.reference(origin), "current_report": module.reference(new_report),
            "captured_current_prices": module.reference(captured),
            "source_refs": [*quotes, anchor_ref, rehab_ref],
            "reviews": [{"date": str(day.date()), "ticker": ticker, "old_raw": quotes[0], "new_raw": quotes[1],
                         "shared_anchor": anchor_ref, "shared_rehab": rehab_ref}]}
        if previous is not None:
            audit.update(inherited_review=previous)
            audit["source_refs"].append(previous)
        path = folder / f"{index}-review.json"
        path.write_text(json.dumps(audit))
        previous = module.reference(path)
        audits.append(path)
        refs.append(audit)
        raw_refs.append(quotes)
    monkeypatch.setattr(case.helper, "_current_entries",
        lambda path, *args: (sources[str(Path(path))], {}), raising=False)
    prior = {"ref": refs[-1]["prior_manifest"], "contract": owner,
             "frames": {"price_paths": original}, "cutoff": state.prior["performance_end_date"]}
    return SimpleNamespace(prior=prior, current=current, audits=audits, values=refs,
                           raw_refs=raw_refs, captured=captured)


def test_inherited_close_proofs_keep_each_origin_date_and_every_prior_mark(retained_replay, monkeypatch):
    chain = inherited_close_chain(retained_replay, monkeypatch)
    prices = module._retain_prior_execution_marks(chain.current, chain.prior, module.reference(chain.audits[-1]))
    old = chain.prior["frames"]["price_paths"][["date", "ticker", "open", "close"]].rename(columns={"date": "trade_date"})
    prefix = prices.loc[prices.trade_date.le(pd.Timestamp(chain.prior["cutoff"]))]
    pd.testing.assert_frame_equal(old.sort_values(["trade_date", "ticker"]).reset_index(drop=True),
                                  prefix.reset_index(drop=True), check_exact=True)
    pd.testing.assert_frame_equal(prices.loc[prices.trade_date.gt(pd.Timestamp(chain.prior["cutoff"]))].reset_index(drop=True),
                                  chain.current.loc[chain.current.trade_date.gt(pd.Timestamp(chain.prior["cutoff"]))].reset_index(drop=True), check_exact=True)
    # Already accepted top-level proof can be reused at a later cutoff without
    # rebinding its inherited link to itself rather than its original owner.
    accepted = {**chain.prior, "contract": {"retained_close_vintage_review": module.reference(chain.audits[-1])}}
    reused = module._retain_prior_execution_marks(chain.current, accepted, module.reference(chain.audits[-1]))
    pd.testing.assert_frame_equal(prices, reused, check_exact=True)


@pytest.mark.parametrize("fault", ["unbound_inherited", "missing_source_ref", "wrong_origin", "missing_key", "extra_key",
    "duplicate_key", "capture_tuple", "raw_hash", "raw_ohl", "bad_asof", "naive_asof"])
def test_inherited_proof_cannot_exempt_unbound_or_extra_changes(retained_replay, monkeypatch, fault):
    chain = inherited_close_chain(retained_replay, monkeypatch)
    audit = chain.values[-1]
    if fault == "unbound_inherited":
        copy = chain.audits[0].with_name("unknown-copy.json")
        copy.write_bytes(chain.audits[0].read_bytes())
        audit["inherited_review"] = module.reference(copy)
        audit["source_refs"][-1] = audit["inherited_review"]
    elif fault == "missing_source_ref":
        audit["source_refs"].pop()
    elif fault == "wrong_origin":
        audit["prior_manifest"] = chain.values[0]["prior_manifest"]
    elif fault == "missing_key":
        audit.pop("inherited_review")
    elif fault == "extra_key":
        # A valid inherited proof becomes extra when there is no corresponding
        # current close change. Its raw/source/date proof remains unchanged.
        day = pd.Timestamp(chain.values[0]["reviews"][0]["date"])
        ticker = chain.values[0]["reviews"][0]["ticker"]
        old = chain.prior["frames"]["price_paths"]
        value = old.loc[old.date.eq(day) & old.ticker.eq(ticker), "close"].iloc[0]
        chain.current.loc[chain.current.trade_date.eq(day) & chain.current.ticker.eq(ticker), "close"] = value
    elif fault == "duplicate_key":
        audit["reviews"].append(dict(audit["reviews"][0]))
    elif fault == "capture_tuple":
        frame = pd.read_parquet(chain.captured)
        record = audit["reviews"][0]
        frame.loc[frame.trade_date.eq(pd.Timestamp(record["date"])) & frame.ticker.eq(record["ticker"]), "close"] += .01
        frame.to_parquet(chain.captured, index=False)
        audit["captured_current_prices"] = module.reference(chain.captured)
    else:
        quote = chain.raw_refs[-1][1]
        path = Path(quote["path"])
        if fault == "raw_hash":
            path.write_bytes(b"changed raw source")
        else:
            frame = pd.read_csv(path)
            if fault == "raw_ohl":
                frame.loc[0, "high"] += .01
            else:
                frame.loc[0, "fetched_at_utc"] = "" if fault == "bad_asof" else "2026-09-23T20:10:00"
            frame.to_csv(path, index=False)
            quote.update(module.reference(path))
    chain.audits[-1].write_text(json.dumps(audit))
    with pytest.raises(ValueError):
        module._retain_prior_execution_marks(chain.current, chain.prior, module.reference(chain.audits[-1]))


@pytest.mark.parametrize("length", [8, 9])
def test_inherited_proof_chain_has_a_bounded_fully_verified_depth(retained_replay, monkeypatch, length):
    chain = inherited_close_chain(retained_replay, monkeypatch, days=[retained_replay.case.days[-2]] * length)
    if length == 9:
        with pytest.raises(ValueError, match="CHAIN_TOO_DEEP"):
            module._retain_prior_execution_marks(chain.current, chain.prior, module.reference(chain.audits[-1]))
    else:
        prices = module._retain_prior_execution_marks(chain.current, chain.prior, module.reference(chain.audits[-1]))
        assert len(prices) == len(chain.current)


def test_inherited_proof_cycle_is_rejected_before_reusing_any_authority(retained_replay, monkeypatch):
    chain = inherited_close_chain(retained_replay, monkeypatch)
    top_ref = module.reference(chain.audits[-1])
    child = chain.values[0]
    child["inherited_review"] = top_ref
    child["source_refs"].append(top_ref)
    owner_path = Path(module.read(child["prior_manifest"]["path"])["evaluation_contract"]["path"])
    owner = module.read(owner_path)
    owner["retained_close_vintage_review"] = top_ref
    owner_path.write_text(json.dumps(owner))
    chain.audits[0].write_text(json.dumps(child))
    # A cryptographic reference cycle cannot have mutually stable file hashes.
    # Isolate the structural guard; all raw/date/native proof checks still run.
    monkeypatch.setattr(module, "verified", lambda ref: Path(ref["path"]))
    with pytest.raises(ValueError, match="CHAIN_CYCLE"):
        module._retain_prior_execution_marks(chain.current, chain.prior, top_ref)


def test_inherited_proofs_cannot_repeat_one_key_across_origins(retained_replay, monkeypatch):
    day = retained_replay.case.days[-2]
    chain = inherited_close_chain(retained_replay, monkeypatch, days=[day, day], tickers=["T00", "T00"])
    with pytest.raises(ValueError, match="DUPLICATE_INHERITED_KEY"):
        module._retain_prior_execution_marks(chain.current, chain.prior, module.reference(chain.audits[-1]))


def test_additional_execution_supplement_is_forwarded_and_bound_without_new_inference(case, tmp_path):
    seen = []
    original = case.helper.load_execution_prices
    def reader(*args, **kwargs):
        seen.append(kwargs.get("additional_price_manifest_path"))
        return original(*args, **kwargs)
    case.helper.load_execution_prices = reader
    supplement = tmp_path / "execution_supplement.json"
    supplement.write_text('{"synthetic_execution_only": true}')
    result = module.refresh_demo_performance(case.paths, case.historical, case.current_path,
                                             additional_price_manifest_path=supplement)
    assert result["status"] == "READY", result.get("error")
    assert seen == [supplement]
    ref = module.reference(supplement)
    contract = module.read(module.verified(result["evaluation_contract"]))
    inputs = module.read(module.verified(result["price_inputs"]))
    assert contract["additional_price_manifest"] == inputs["additional_price_manifest"] == ref
    assert result["model_fit_count"] == result["parameter_search_count"] == 0
    assert contract["execution_price_extension"]["model_feature_eligibility_granted"] is False

def pending_revision_fixture(case, tmp_path):
    feature = tmp_path / "old_features.synthetic"
    feature.write_text("old frozen inference")
    case.current["selected_hgb_features"] = module.reference(feature)
    case.current_path.write_text(json.dumps(case.current))
    price_proof = tmp_path / "pending_execution_source.parquet"
    case.prices.to_parquet(price_proof, index=False)
    price_ref = module.reference(price_proof)
    reader = case.helper.load_execution_prices
    def bound_reader(*args, **kwargs):
        return {**reader(*args, **kwargs), "refs": [price_ref],
            "price_basis": module.EVALUATION["price_basis"],
            "start_date": kwargs["start"], "end_date": kwargs["end"],
            "vintage_semantics": "LATER_VENDOR_REHAB_SNAPSHOT_NOT_HISTORICAL_PUBLICATION_VINTAGE"}
    case.helper.load_execution_prices = bound_reader
    result = run(case)
    assert result["status"] == "READY", result.get("error")
    prior = {"cutoff": "2026-09-22", "manifest": result,
        "contract": module.read(module.verified(result["evaluation_contract"])),
        "frames": {"rankings": pd.read_parquet(result["outputs"]["rankings"]["path"])}}
    newer = tmp_path / "new_features.synthetic"
    newer.write_text("new verified observations")
    replacement = tmp_path / "new_recommendation_source.json"
    audit = tmp_path / "repair_lineage.json"
    repair = {"schema": "A2_OFFLINE_INPUT_REPAIR_V1", "network_requests_this_run": 0,
        "status": "INPUTS_VERIFIED", "target_date": "2026-09-22", "run_id": "pending_repair",
        "model_fit_count": 0, "parameter_search_count": 0,
        "old_date_keys_retained": True, "old_rows_unchanged": True,
        "unrelated_current_keys_unchanged": True, "reason": "synthetic pending input completion",
        "parent_inputs": [prior["contract"]["current_report"]]}
    audit.write_text(json.dumps(repair))
    current = {**case.current, "run_id": "pending_repair", "report_path": str(replacement),
        "selected_hgb_features": module.reference(newer), "repair_lineage": module.reference(audit)}
    current["ranked_rows"] = [{**row} for row in current["ranked_rows"]]
    current["ranked_rows"][0]["score"] += .125
    replacement.write_text(json.dumps(current))
    return SimpleNamespace(prior=prior, result=result, current=current, replacement=replacement,
        audit=audit, repair=repair)


def test_only_bound_latest_pending_signal_can_change_rankings_without_rewriting_ledger(case, tmp_path):
    chain = pending_revision_fixture(case, tmp_path)
    result = module.refresh_demo_performance(case.paths, case.historical, chain.replacement,
        prior_verified_performance_manifest_path=chain.result["report_path"],
        pending_signal_revision_path=chain.audit)
    assert result["status"] == "READY", result.get("error")
    proof = module.read(module.verified(result["evaluation_contract"]))["pending_signal_revision"]
    assert proof["allowed_changed_outputs"] == ["rankings", "coverage"]
    assert proof["signal_date"] == "2026-09-22"
    assert proof["scheduled_execution_date"] == "2026-09-23"
    for name in ("portfolio_daily", "positions", "trades", "price_paths"):
        pd.testing.assert_frame_equal(pd.read_parquet(chain.result["outputs"][name]["path"]),
            pd.read_parquet(result["outputs"][name]["path"]), check_exact=True)


@pytest.mark.parametrize("fault", ["executed", "wrong_date", "unbound", "fit", "network"])
def test_pending_revision_rejects_executed_unbound_or_nonfrozen_receipts(case, tmp_path, fault):
    chain = pending_revision_fixture(case, tmp_path)
    if fault == "executed":
        path = Path(chain.result["outputs"]["decision_calendar"]["path"])
        table = pd.read_parquet(path)
        table.loc[table.signal_date.eq("2026-09-22"), "execution_status"] = "EXECUTED"
        table.to_parquet(path, index=False)
        chain.prior["manifest"]["outputs"]["decision_calendar"] = module.reference(path)
    elif fault == "wrong_date":
        chain.current["data_date"] = "2026-09-21"
    elif fault == "unbound":
        chain.current["repair_lineage"] = {"path": str(chain.audit), "sha256": "0" * 64}
    else:
        chain.repair["model_fit_count" if fault == "fit" else "network_requests_this_run"] = 1
        chain.audit.write_text(json.dumps(chain.repair))
        chain.current["repair_lineage"] = module.reference(chain.audit)
    chain.replacement.write_text(json.dumps(chain.current))
    from scripts.research.a2.portfolio.selected_hgb import SelectedStrategyError
    with pytest.raises((ValueError, SelectedStrategyError)):
        module._pending_signal_revision(chain.prior, chain.replacement, chain.audit, case.days)


def test_pending_revision_keeps_all_executed_fields_and_earlier_rankings_strict():
    dates = pd.to_datetime(["2026-09-21", "2026-09-22"])
    old = pd.DataFrame({"date": dates, "value": [1., 2.]})
    prior = {"cutoff": "2026-09-22", "frames": {"rankings": old, "portfolio_daily": old}}
    repair = {"signal_date": "2026-09-22"}
    latest_changed = old.copy()
    latest_changed.loc[1, "value"] = 3.
    module._assert_prior_prefix("rankings", latest_changed, prior, "date", ["date"], repair)
    with pytest.raises(ValueError, match="PREFIX_CHANGED"):
        module._assert_prior_prefix("rankings", latest_changed, prior, "date", ["date"])
    with pytest.raises(ValueError, match="PREFIX_CHANGED"):
        module._assert_prior_prefix("portfolio_daily", latest_changed, prior, "date", ["date"], repair)
    older_changed = old.copy()
    older_changed.loc[0, "value"] = 3.
    with pytest.raises(ValueError, match="PREFIX_CHANGED"):
        module._assert_prior_prefix("rankings", older_changed, prior, "date", ["date"], repair)


@pytest.fixture
def open_replay(case, tmp_path, monkeypatch):
    price_spec = importlib.util.spec_from_file_location("synthetic_real_open_clock",
        case.paths.repo_root / "scripts/research/a2/evaluation/demo_performance_prices.py")
    prices_owner = importlib.util.module_from_spec(price_spec); price_spec.loader.exec_module(prices_owner)
    case.helper.execution_open_clock = prices_owner.execution_open_clock
    original = case.helper.load_execution_prices
    closed_path = tmp_path / "closed_synthetic.parquet"; case.prices.to_parquet(closed_path, index=False)
    closed_ref = module.reference(closed_path)
    phase_path = tmp_path / "synthetic_open_manifest.json"
    phase = {"schema": "A2_EXECUTION_OPEN_INPUTS_V1", "signal_end_date": "2026-09-22",
        "execution_end_date": "2026-09-23", "as_of_utc": "2026-09-23T17:00:00+00:00",
        "current_report": module.reference(case.current_path)}
    captures, factors, extra_refs, identities = [], [], [], []
    for index in range(40):
        ticker, code = f"T{index:02}", f"US.T{index:02}"
        sdk_path = tmp_path / (ticker + "_synthetic_sdk.parquet")
        pd.DataFrame([{"code": code, "time_key": "2026-09-23", "open": 120.}]).to_parquet(sdk_path, index=False)
        sdk_ref = module.reference(sdk_path)
        factor_path = tmp_path / (ticker + "_synthetic_rehab.parquet")
        pd.DataFrame(columns=["code", "ex_div_date"]).to_parquet(factor_path, index=False)
        factor_ref = module.reference(factor_path)
        captures.append({"item": {"ticker": ticker}, "current_kline_provenance": {"code": code,
            "api": "get_cur_kline", "autype": "NONE", "session": "RTH", "observed_at_utc": phase["as_of_utc"], "sdk_response": sdk_ref}})
        factors.append({"code": code, "status": "PASS", **factor_ref})
        extra_refs.extend([sdk_ref, factor_ref])
        identities.append({"ticker": ticker, "code": code, "security_id": "ID" + ticker})
    acquisition_path = tmp_path / "synthetic_native_acquisition.json"
    acquisition_path.write_text(json.dumps({"acquisition_mode": "current-kline", "trade_context_opened": False, "results": captures}))
    rehab_path = tmp_path / "synthetic_native_rehab.json"
    rehab_path.write_text(json.dumps({"source": "MOOMOO_OPEND_GET_REHAB", "target_date": "2026-09-23", "results": factors}))
    phase.update(records=identities, acquisition_manifest=module.reference(acquisition_path), rehab_receipt=module.reference(rehab_path))
    extra_refs.extend([phase["acquisition_manifest"], phase["rehab_receipt"]])
    phase_path.write_text(json.dumps(phase))
    metadata = {"manifest": module.reference(phase_path), "signal_end_date": phase["signal_end_date"],
        "execution_end_date": phase["execution_end_date"], "as_of_utc": phase["as_of_utc"],
        "qualified_tickers": [f"T{index:02}" for index in range(40)],
        "consumer_fields": ["open"], "terminal_close_available": False,
        "model_feature_eligibility_granted": False}
    def bound_reader(*args, **kwargs):
        value = {**original(*args, **kwargs), "refs": [closed_ref],
            "price_basis": module.EVALUATION["price_basis"], "start_date": kwargs["start"],
            "end_date": kwargs["end"],
            "vintage_semantics": "LATER_VENDOR_REHAB_SNAPSHOT_NOT_HISTORICAL_PUBLICATION_VINTAGE"}
        if kwargs.get("execution_open_manifest") is not None:
            value["execution_open"] = metadata
            value["refs"] = [closed_ref, metadata["manifest"], *extra_refs]
        return value
    case.helper.load_execution_prices = bound_reader
    baseline = run(case); assert baseline["status"] == "READY", baseline.get("error")
    terminal = pd.DataFrame([{"trade_date": case.days[-1], "ticker": f"T{index:02}",
        "open": 120., "close": np.nan} for index in range(40)])
    case.prices = pd.concat([case.prices, terminal], ignore_index=True)
    # Original fixture reader captures its original frame; expose the extended input.
    original = lambda *args, **kwargs: {"prices": case.prices, "events": case.events, "gaps": [], "refs": []}
    opened = module.refresh_demo_performance(case.paths, case.historical, case.current_path,
        execution_open_manifest=phase_path, execution_end="2026-09-23",
        prior_verified_performance_manifest_path=baseline["report_path"])
    assert opened["status"] == "READY", opened.get("error")
    assert opened["ranking_end_date"] == "2026-09-22" and opened["performance_end_date"] == "2026-09-23"
    return SimpleNamespace(case=case, baseline=baseline, opened=opened, phase_path=phase_path)


def test_original_raw_engine_extends_next_open_and_completes_only_unknown_close(open_replay, tmp_path, monkeypatch):
    state = open_replay
    case, baseline, opened, phase_path = state.case, state.baseline, state.opened, state.phase_path
    before = pd.read_parquet(baseline["outputs"]["portfolio_daily"]["path"])
    after = pd.read_parquet(opened["outputs"]["portfolio_daily"]["path"])
    pd.testing.assert_frame_equal(before, after.iloc[:-1].reset_index(drop=True), check_exact=True)
    assert after.iloc[-1].reconstructed_nav > before.iloc[-1].reconstructed_nav
    repeat = module.refresh_demo_performance(case.paths, case.historical, case.current_path,
        execution_open_manifest=phase_path, execution_end="2026-09-23",
        prior_verified_performance_manifest_path=opened["report_path"])
    assert repeat["status"] == "READY", repeat.get("error")
    pd.testing.assert_frame_equal(after, pd.read_parquet(repeat["outputs"]["portfolio_daily"]["path"]), check_exact=True)
    history = case.paths.daily_root / "A2_today_recommendation/history"
    history.mkdir(parents=True, exist_ok=True)
    (history / "retained_signal_22.json").write_bytes(case.current_path.read_bytes())
    next_report = tmp_path / "completed_recommendation_source.json"
    case.current = {**case.current, "data_date": "2026-09-23", "report_path": str(next_report),
                    "generated_at": "2026-09-24T09:00:00Z"}
    next_report.write_text(json.dumps(case.current))
    case.current_path = next_report
    case.prices.loc[case.prices.trade_date.eq(case.days[-1]), "close"] = 121.
    from scripts.research.a2.inference import historical_top40
    monkeypatch.setattr(historical_top40, "load_sessions", lambda _: (list(case.days.strftime("%Y-%m-%d")),
        {"current": {"target_date": "2026-09-23"}, "lineage": {"synthetic": True}}))
    completed = module.refresh_demo_performance(case.paths, case.historical, case.current_path,
        prior_verified_performance_manifest_path=opened["report_path"])
    assert completed["status"] == "READY", completed.get("error")
    pd.testing.assert_frame_equal(after, pd.read_parquet(completed["outputs"]["portfolio_daily"]["path"]), check_exact=True)
    marks = pd.read_parquet(completed["outputs"]["price_paths"]["path"])
    assert marks.loc[marks.date.eq(case.days[-1]), "close"].eq(121.).all()


@pytest.fixture
def same_end_reuse(open_replay, tmp_path, monkeypatch):
    state, case = open_replay, open_replay.case
    history = case.paths.daily_root / "A2_today_recommendation/history"
    history.mkdir(parents=True, exist_ok=True)
    (history / "accepted_22.json").write_bytes(case.current_path.read_bytes())
    current = tmp_path / "mature_signal_23.json"
    case.current = {**case.current, "data_date": "2026-09-23", "report_path": str(current),
                    "generated_at": "2026-09-24T09:00:00Z"}
    current.write_text(json.dumps(case.current));case.current_path = current
    state.original_engine_replay = case.engine.reconstruct_open_ended
    case.helper.load_execution_prices = lambda *args, **kwargs: pytest.fail("reuse must not read/revise price vintages")
    case.engine.reconstruct_open_ended = lambda *args, **kwargs: pytest.fail("reuse must not replay accepted economics")
    from scripts.research.a2.inference import historical_top40
    monkeypatch.setattr(historical_top40, "load_sessions", lambda _: (
        [*case.days.strftime("%Y-%m-%d"), "2026-09-24"],
        {"current": {"target_date": "2026-09-23"}, "lineage": {"synthetic": True}}))
    state.prior_path = Path(state.opened["report_path"])
    return state


def same_end_run(state, prior=None):
    return module.refresh_demo_performance(state.case.paths, state.case.historical, state.case.current_path,
        prior_verified_performance_manifest_path=prior or state.prior_path, reuse_same_end_performance=True)


def test_same_end_adds_pending_signal_without_loading_prices_or_replaying_economics(same_end_reuse):
    state = same_end_reuse
    result = same_end_run(state)
    assert result["status"] == "READY", result.get("error")
    assert result["ranking_end_date"] == result["performance_end_date"] == "2026-09-23"
    assert result["action"] == "REUSE_VERIFIED_EXECUTED_LEDGER_SAME_END"
    for name in module.PERFORMANCE_OUTPUTS:
        assert result["outputs"][name] == state.opened["outputs"][name]
    assert result["price_inputs"] == state.opened["price_inputs"]
    assert result["execution_open"] == state.opened["execution_open"]
    decisions = pd.read_parquet(result["outputs"]["decision_calendar"]["path"])
    assert decisions.iloc[-1].signal_date == "2026-09-23"
    assert decisions.iloc[-1].execution_status == "PENDING_NEXT_OPEN"
    assert decisions.iloc[-1].scheduled_execution_date == "2026-09-24"
    assert pd.isna(decisions.iloc[-1].execution_date)
    assert pd.isna(pd.read_parquet(result["outputs"]["price_paths"]["path"]).iloc[-1]["close"])
    second = same_end_run(state, Path(result["report_path"]))
    assert second["status"] == "READY", second.get("error")
    assert second["performance_origin"] == result["performance_origin"]
    assert second["performance_origin"]["manifest"] == module.reference(state.prior_path)


@pytest.mark.parametrize("fault", ["source", "marks", "contract", "model", "calendar", "past_score"])
def test_same_end_reuse_never_masks_original_source_economic_or_rank_changes(same_end_reuse, monkeypatch, fault):
    state, case = same_end_reuse, same_end_reuse.case
    pointer = case.paths.daily_root / "A2_updated_research/latest.json";before = pointer.read_bytes()
    if fault == "source":
        contract=module.read(module.verified(state.opened["evaluation_contract"]))
        module.verified(contract["price_refs"][0]).write_bytes(b"changed original source")
    elif fault == "marks":module.verified(state.opened["outputs"]["price_paths"]).write_bytes(b"changed original economic mark")
    elif fault == "contract":module.verified(state.opened["evaluation_contract"]).write_bytes(b"changed contract")
    elif fault == "model":
        case.current["model_sha256"]="0"*64;case.current_path.write_text(json.dumps(case.current))
    elif fault == "calendar":
        from scripts.research.a2.inference import historical_top40
        monkeypatch.setattr(historical_top40,"load_sessions",lambda _: ([*case.days.strftime("%Y-%m-%d"),"2026-09-24"],{"current":{"target_date":"2026-09-23"},"lineage":{"synthetic":False}}))
    else:
        old=module.read(module.verified(module.read(module.verified(state.opened["evaluation_contract"]))["current_report"]))
        old["ranked_rows"][0]["score"]+=1;path=case.paths.daily_root/"A2_today_recommendation/history/conflicting_22.json"
        old.update(generated_at="2026-09-24T12:00:00Z",report_path=str(path));path.write_text(json.dumps(old))
    result=same_end_run(state)
    assert result["status"]=="BLOCKED"
    assert pointer.read_bytes()==before


def test_same_end_origin_references_cannot_be_rebound_after_first_reuse(same_end_reuse):
    state=same_end_reuse;first=same_end_run(state);assert first["status"]=="READY"
    path=Path(first["report_path"]);changed=module.read(path)
    changed["outputs"]["positions"]={**changed["outputs"]["positions"],"rows":999}
    path.write_text(json.dumps(changed))
    result=same_end_run(state,path)
    assert result["status"]=="BLOCKED" and "ORIGIN_OUTPUTS_CHANGED" in result["error"]


@pytest.fixture
def next_session_reuse(same_end_reuse, tmp_path, monkeypatch):
    state, case = same_end_reuse, same_end_reuse.case
    reused = same_end_run(state);assert reused["status"] == "READY", reused.get("error")
    state.reused = reused
    history=case.paths.daily_root/"A2_today_recommendation/history"
    (history/"accepted_signal_23.json").write_bytes(case.current_path.read_bytes())
    current=tmp_path/"next_session_source.json"
    identity_root=tmp_path/"next_identity";identity_root.mkdir()
    members=pd.DataFrame([{"ticker":f"T{i:02}","security_id":f"IDT{i:02}","moomoo_symbol":f"US.T{i:02}"} for i in range(40)])
    members.to_parquet(identity_root/"mapped_members.parquet",index=False)
    case.current={**case.current,"data_date":"2026-09-24","report_path":str(current),"generated_at":"2026-09-25T09:00:00Z",
        "universe":{**case.current["universe"],"report_path":str(identity_root/"universe_report.json"),
                    "universe_members_sha256":module.digest(identity_root/"mapped_members.parquet")}}
    current.write_text(json.dumps(case.current));case.current_path=current
    case.prices.loc[case.prices.trade_date.eq(case.days[-1]),"open"]=120.5
    case.prices.loc[case.prices.trade_date.eq(case.days[-1]),"close"]=121.
    case.prices=pd.concat([case.prices,pd.DataFrame([{"ticker":f"T{i:02}","trade_date":pd.Timestamp("2026-09-24"),"open":125.,"close":126.} for i in range(40)])],ignore_index=True)
    new_raw=tmp_path/"new_mature_prices.parquet";case.prices.to_parquet(new_raw,index=False)
    def reader(*args,**kwargs):
        return {"prices":case.prices,"events":case.events,"gaps":[],"refs":[module.reference(new_raw),module.reference(current)],
            "price_basis":module.EVALUATION["price_basis"],"start_date":kwargs["start"],"end_date":kwargs["end"],
            "vintage_semantics":"LATER_VENDOR_REHAB_SNAPSHOT_NOT_HISTORICAL_PUBLICATION_VINTAGE"}
    case.helper.load_execution_prices=reader;case.engine.reconstruct_open_ended=state.original_engine_replay
    from scripts.research.a2.inference import historical_top40
    monkeypatch.setattr(historical_top40,"load_sessions",lambda _: ([*case.days.strftime("%Y-%m-%d"),"2026-09-24","2026-09-25"],
        {"current":{"target_date":"2026-09-24"},"lineage":{"synthetic":True}}))
    return state


def next_session_run(state, **kwargs):
    return module.refresh_demo_performance(state.case.paths,state.case.historical,state.case.current_path,
        prior_verified_performance_manifest_path=state.reused["report_path"],reuse_same_end_performance=True,**kwargs)


def test_next_session_preserves_original_qualified_opens_and_every_economic_prefix_field(next_session_reuse):
    state=next_session_reuse
    strict=next_session_run(state)
    assert strict["status"]=="BLOCKED" and "PREFIX_CHANGED:price_paths" in strict["error"]
    result=next_session_run(state,retain_qualified_prior_open=True)
    assert result["status"]=="READY",result.get("error")
    assert result["performance_end_date"]=="2026-09-24"
    for name,column in (("portfolio_daily","execution_date"),("positions","date"),("trades","date")):
        before=pd.read_parquet(state.reused["outputs"][name]["path"])
        after=pd.read_parquet(result["outputs"][name]["path"])
        prefix=after.loc[pd.to_datetime(after[column]).le(pd.Timestamp("2026-09-23"))].reset_index(drop=True)
        pd.testing.assert_frame_equal(before,prefix,check_exact=True,check_dtype=False)
    marks=pd.read_parquet(result["outputs"]["price_paths"]["path"])
    terminal=marks.loc[marks.date.eq(pd.Timestamp("2026-09-23"))]
    assert terminal.open.eq(120.).all() and terminal.close.eq(121.).all()
    audit=module.read(module.verified(result["evaluation_contract"]))["retained_qualified_execution_opens"]
    assert len(audit["records"])==40 and audit["prior_ledger_changed"] is False
    assert audit["records"][0]["completed_vendor_open"]==120.5


@pytest.mark.parametrize("fault",["old_open","old_close","phase_bytes","sdk_bytes","identity","unknown_close","not_mature"])
def test_qualified_terminal_reuse_rejects_closed_history_capture_identity_and_maturity_changes(next_session_reuse,fault):
    state,case=next_session_reuse,next_session_reuse.case
    pointer=case.paths.daily_root/"A2_updated_research/latest.json";before=pointer.read_bytes()
    if fault=="old_open":case.prices.loc[case.prices.trade_date.eq(case.days[1]),"open"]+=.5
    elif fault=="old_close":case.prices.loc[case.prices.trade_date.eq(case.days[1]),"close"]+=.5
    elif fault=="phase_bytes":Path(state.opened["execution_open"]["manifest"]["path"]).write_bytes(b"tampered original phase")
    elif fault=="sdk_bytes":
        phase=module.read(module.verified(state.opened["execution_open"]["manifest"]));acq=module.read(module.verified(phase["acquisition_manifest"]))
        module.verified(acq["results"][0]["current_kline_provenance"]["sdk_response"]).write_bytes(b"tampered native source")
    elif fault=="identity":
        path=Path(case.current["universe"]["report_path"]).parent/"mapped_members.parquet";members=pd.read_parquet(path)
        members.loc[0,"security_id"]="DIFFERENT_SID";members.to_parquet(path,index=False)
        case.current["universe"]["universe_members_sha256"]=module.digest(path);case.current_path.write_text(json.dumps(case.current))
    elif fault=="unknown_close":case.prices.loc[case.prices.trade_date.eq(case.days[-1]),"close"]=np.nan
    else:
        case.current["generated_at"]="2026-09-23T15:00:00Z";case.current_path.write_text(json.dumps(case.current))
    result=next_session_run(state,retain_qualified_prior_open=True)
    assert result["status"]=="BLOCKED",result
    assert pointer.read_bytes()==before


def test_qualified_terminal_source_cannot_promote_an_unqualified_ticker(next_session_reuse):
    state,case=next_session_reuse,next_session_reuse.case
    engine,authority=module._authority(case.paths)
    models=module.read(case.historical)["models"]["artifacts"]
    prior=module._prior_verified_performance(case.paths,Path(state.reused["report_path"]),case.historical,
        models,authority,{"synthetic":True},"2026-09-24")
    # Simulate a malformed internal adapter without changing any real/frozen file.
    prior["manifest"]["execution_open"]["qualified_tickers"].remove("T00")
    prices=case.helper.load_execution_prices(start="2026-09-17",end="2026-09-24")
    with pytest.raises(ValueError,match="VERIFIED_TERMINAL_CLOSE"):
        module._retain_qualified_execution_opens(prices["prices"],prior,prices,case.current_path)


@pytest.fixture
def legacy_partial_open(next_session_reuse, monkeypatch, tmp_path):
    """Reproduce the accepted pre-fix mixed terminal-close publication."""
    state, case = next_session_reuse, next_session_reuse.case
    last = case.prices.trade_date.eq(pd.Timestamp("2026-09-23")) & case.prices.ticker.isin(["T00", "T01"])
    case.prices.loc[last, "open"] = 120.
    case.prices.loc[last, "close"] = np.nan
    case.prices = case.prices.loc[~(case.prices.trade_date.eq(pd.Timestamp("2026-09-24"))
                                   & case.prices.ticker.eq("T00"))].copy()
    raw = tmp_path / "legacy_bound_raw.parquet"
    case.prices.to_parquet(raw, index=False)
    source = case.current_path
    def reader(*args, **kwargs):
        return synthetic_price_input(kwargs, case.prices, case.events,
                                     [module.reference(raw), module.reference(source)])
    case.helper.load_execution_prices = reader
    existing = set((case.paths.daily_root / "A2_updated_research/runs").glob("*/manifest.json"))
    validate = module._prior_verified_performance
    def emulate_previous_publication(paths, path, *args, **kwargs):
        # Only the new post-write self-check is bypassed to create the historical
        # defect fixture. Existing ancestors still traverse the full validator.
        if Path(path) not in existing:
            return None
        return validate(paths, path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(module, "_prior_verified_performance", emulate_previous_publication)
        partial = next_session_run(state, retain_qualified_prior_open=True)
    assert partial["status"] == "PARTIAL", partial.get("error")
    assert partial["performance_end_date"] == "2026-09-23" and "execution_open" not in partial
    state.legacy = partial
    state.legacy_raw = raw
    state.legacy_source = source
    state.legacy_bytes = Path(partial["report_path"]).read_bytes()
    return state


def validate_legacy_partial(state):
    case = state.case
    _, authority = module._authority(case.paths)
    return module._prior_verified_performance(case.paths, Path(state.legacy["report_path"]), case.historical,
        module.read(case.historical)["models"]["artifacts"], authority, {"synthetic": True}, "2026-09-24")


def fresh_after_legacy(state, tmp_path):
    case = state.case
    current = tmp_path / "fresh_requalified_source.json"
    case.current = {**case.current, "report_path": str(current), "generated_at": "2026-09-25T10:00:00Z"}
    current.write_text(json.dumps(case.current)); case.current_path = current
    case.prices.loc[case.prices.trade_date.eq(pd.Timestamp("2026-09-23")), "close"] = 121.
    case.prices = pd.concat([case.prices, pd.DataFrame([{"trade_date": pd.Timestamp("2026-09-24"),
        "ticker": "T00", "open": 125., "close": 126.}])], ignore_index=True)
    raw = tmp_path / "fresh_after_legacy_raw.parquet"; case.prices.to_parquet(raw, index=False)
    case.helper.load_execution_prices = lambda *a, **kw: synthetic_price_input(
        kw, case.prices, case.events, [module.reference(raw), module.reference(current)])
    return raw


def test_bound_legacy_partial_recovers_phase_and_completes_only_unknown_prices(legacy_partial_open, tmp_path):
    state = legacy_partial_open
    prior = validate_legacy_partial(state)
    assert prior["retained_execution_open"] == state.opened["execution_open"]
    old = prior["frames"]["price_paths"]
    assert old.close.isna().sum() == 2
    fresh_after_legacy(state, tmp_path)
    result = module.refresh_demo_performance(state.case.paths, state.case.historical, state.case.current_path,
        prior_verified_performance_manifest_path=state.legacy["report_path"], retain_qualified_prior_open=True)
    assert result["status"] == "READY", result.get("error")
    assert result["performance_end_date"] == "2026-09-24"
    new = pd.read_parquet(result["outputs"]["price_paths"]["path"])
    for name, column in (("portfolio_daily", "execution_date"), ("positions", "date"), ("trades", "date")):
        before = prior["frames"][name]
        after = pd.read_parquet(result["outputs"][name]["path"])
        pd.testing.assert_frame_equal(before, after.loc[pd.to_datetime(after[column]).le(
            pd.Timestamp("2026-09-23"))].reset_index(drop=True), check_exact=True, check_dtype=False)
    known = old.loc[old.date.le(pd.Timestamp("2026-09-23"))].copy()
    overlap = new.loc[new.date.le(pd.Timestamp("2026-09-23"))].reset_index(drop=True)
    pd.testing.assert_series_equal(known.open.reset_index(drop=True), overlap.open, check_exact=True)
    assert overlap.loc[known.close.notna().to_numpy(), "close"].equals(
        known.loc[known.close.notna(), "close"].reset_index(drop=True).set_axis(
            overlap.index[known.close.notna().to_numpy()]))
    assert overlap.close.notna().all()
    assert Path(state.legacy["report_path"]).read_bytes() == state.legacy_bytes
    # New publication must pass the same validator without the compatibility branch.
    _, authority = module._authority(state.case.paths)
    module._prior_verified_performance(state.case.paths, Path(result["report_path"]), state.case.historical,
        module.read(state.case.historical)["models"]["artifacts"], authority, {"synthetic": True},
        "2026-09-24", _allow_retained_partial=False)


@pytest.mark.parametrize("fault", ["unbound_ancestor", "missing_audit", "old_closed_nan", "old_open",
                                   "old_close", "audit_close", "original_phase_hash"])
def test_legacy_partial_recovery_never_broadens_original_proof(legacy_partial_open, fault):
    state = legacy_partial_open
    path = Path(state.legacy["report_path"]); manifest = module.read(path)
    contract_path = Path(manifest["evaluation_contract"]["path"]); contract = module.read(contract_path)
    inputs_path = Path(manifest["price_inputs"]["path"]); inputs = module.read(inputs_path)
    if fault == "original_phase_hash":
        Path(state.opened["execution_open"]["manifest"]["path"]).write_bytes(b"modified original phase")
    elif fault in {"old_closed_nan", "old_open", "old_close"}:
        prices_path = Path(manifest["outputs"]["price_paths"]["path"]); prices = pd.read_parquet(prices_path)
        row = prices.date.eq(pd.Timestamp("2026-09-18")) & prices.ticker.eq("T00")
        field = "open" if fault == "old_open" else "close"
        prices.loc[row, field] = np.nan if fault == "old_closed_nan" else prices.loc[row, field] + .5
        prices.to_parquet(prices_path, index=False)
        manifest["outputs"]["price_paths"] = {**module.reference(prices_path), "rows": len(prices)}
    else:
        if fault == "unbound_ancestor":
            manifest["prior_verified_performance"]["manifest"] = module.reference(Path(state.baseline["report_path"]))
        elif fault == "missing_audit":
            contract.pop("retained_qualified_execution_opens")
            inputs.pop("retained_qualified_execution_opens")
        else:
            contract["retained_qualified_execution_opens"]["records"][0]["mature_close"] += .5
            inputs["retained_qualified_execution_opens"] = contract["retained_qualified_execution_opens"]
        inputs_path.write_text(json.dumps(inputs)); manifest["price_inputs"] = module.reference(inputs_path)
        contract["price_inputs"] = manifest["price_inputs"]
        contract_path.write_text(json.dumps(contract)); manifest["evaluation_contract"] = module.reference(contract_path)
    path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, AssertionError)):
        validate_legacy_partial(state)


@pytest.mark.parametrize("fault", ["known_close_revision", "unknown_identity_change", "not_mature"])
def test_recovered_partial_extension_keeps_known_prices_and_unknown_maturity_strict(legacy_partial_open, tmp_path, fault):
    state = legacy_partial_open; case = state.case
    fresh_after_legacy(state, tmp_path)
    if fault == "known_close_revision":
        case.prices.loc[case.prices.trade_date.eq(pd.Timestamp("2026-09-23")) & case.prices.ticker.eq("T02"), "close"] += .5
    elif fault == "unknown_identity_change":
        path = Path(case.current["universe"]["report_path"]).parent / "mapped_members.parquet"
        members = pd.read_parquet(path); members.loc[members.ticker.eq("T00"), "security_id"] = "WRONG_SID"
        changed = tmp_path / "new_identity"; changed.mkdir(); path = changed / "mapped_members.parquet"
        members.to_parquet(path, index=False)
        case.current["universe"] = {**case.current["universe"], "report_path": str(changed / "report.json"),
            "universe_members_sha256": module.digest(path)}
        case.current_path.write_text(json.dumps(case.current))
    else:
        case.current["generated_at"] = "2026-09-23T15:00:00Z"
        case.current_path.write_text(json.dumps(case.current))
    pointer = case.paths.daily_root / "A2_updated_research/latest.json"; before = pointer.read_bytes()
    result = module.refresh_demo_performance(case.paths, case.historical, case.current_path,
        prior_verified_performance_manifest_path=state.legacy["report_path"], retain_qualified_prior_open=True)
    assert result["status"] == "BLOCKED"
    assert pointer.read_bytes() == before


def test_publication_self_validation_rejects_partial_without_sufficient_phase_proof(next_session_reuse):
    state, case = next_session_reuse, next_session_reuse.case
    terminal = case.prices.trade_date.eq(pd.Timestamp("2026-09-23")) & case.prices.ticker.eq("T00")
    case.prices.loc[terminal, "open"] = 120.; case.prices.loc[terminal, "close"] = np.nan
    case.prices = case.prices.loc[~(case.prices.trade_date.eq(pd.Timestamp("2026-09-24"))
                                   & case.prices.ticker.eq("T00"))].copy()
    pointer = case.paths.daily_root / "A2_updated_research/latest.json"; before = pointer.read_bytes()
    result = next_session_run(state, retain_qualified_prior_open=True)
    assert result["status"] == "BLOCKED" and "EXECUTION_MARKS_INVALID" in result["error"]
    assert pointer.read_bytes() == before


@pytest.fixture
def fully_matured_open_origin(legacy_partial_open, tmp_path):
    state = legacy_partial_open
    fresh_after_legacy(state, tmp_path)
    result = module.refresh_demo_performance(state.case.paths, state.case.historical, state.case.current_path,
        prior_verified_performance_manifest_path=state.legacy["report_path"], retain_qualified_prior_open=True)
    assert result["status"] == "READY", result.get("error")
    assert result["performance_end_date"] == "2026-09-24" and not result.get("execution_open")
    state.matured = result
    state.matured_bytes = Path(result["report_path"]).read_bytes()
    return state


def validate_matured_origin(state, manifest=None, end="2026-09-25"):
    case = state.case
    _, authority = module._authority(case.paths)
    return module._prior_verified_performance(case.paths, Path((manifest or state.matured)["report_path"]),
        case.historical, module.read(case.historical)["models"]["artifacts"], authority,
        {"synthetic": True}, end, _allow_retained_partial=False)


def synthetic_next_closed_source(state, tmp_path, monkeypatch, day="2026-09-25", open_price=130.):
    case = state.case
    history = case.paths.daily_root / "A2_today_recommendation/history"
    (history / (case.current["data_date"] + "_lifecycle.json")).write_bytes(case.current_path.read_bytes())
    current = tmp_path / (day + "_lifecycle_source.json")
    case.current = {**case.current, "data_date": day, "report_path": str(current),
        "generated_at": day + "T23:00:00Z"}
    current.write_text(json.dumps(case.current)); case.current_path = current
    new = pd.DataFrame([{"trade_date": pd.Timestamp(day), "ticker": f"T{i:02}",
        "open": open_price, "close": open_price + 1.} for i in range(40)])
    case.prices = pd.concat([case.prices.loc[~case.prices.trade_date.eq(pd.Timestamp(day))], new], ignore_index=True)
    raw = tmp_path / (day + "_lifecycle_raw.parquet"); case.prices.to_parquet(raw, index=False)
    case.helper.load_execution_prices = lambda *a, **kw: synthetic_price_input(
        kw, case.prices, case.events, [module.reference(raw), module.reference(current)])
    from scripts.research.a2.inference import historical_top40
    days = [*case.days.strftime("%Y-%m-%d"), "2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]
    monkeypatch.setattr(historical_top40, "load_sessions", lambda _: (days,
        {"current": {"target_date": day}, "lineage": {"synthetic": True}}))
    return raw


def extend_matured_origin(state, prior=None):
    return module.refresh_demo_performance(state.case.paths, state.case.historical, state.case.current_path,
        prior_verified_performance_manifest_path=(prior or state.matured)["report_path"],
        retain_qualified_prior_open=True)


def test_fully_matured_phase_keeps_original_open_qualification(fully_matured_open_origin):
    state = fully_matured_open_origin
    prior = validate_matured_origin(state)
    assert prior["retained_execution_open"] == state.opened["execution_open"]
    assert prior["frames"]["price_paths"].close.notna().all()
    assert Path(state.matured["report_path"]).read_bytes() == state.matured_bytes


def test_fully_matured_next_day_and_repeat_preserve_original_marks(fully_matured_open_origin, tmp_path, monkeypatch):
    state = fully_matured_open_origin
    synthetic_next_closed_source(state, tmp_path, monkeypatch)
    result = extend_matured_origin(state)
    assert result["status"] == "READY", result.get("error")
    assert result["performance_end_date"] == "2026-09-25"
    for name, column in (("portfolio_daily","execution_date"),("positions","date"),("trades","date"),("price_paths","date")):
        before = pd.read_parquet(state.matured["outputs"][name]["path"])
        after = pd.read_parquet(result["outputs"][name]["path"])
        after = after.loc[pd.to_datetime(after[column]).le(pd.Timestamp("2026-09-24"))].reset_index(drop=True)
        pd.testing.assert_frame_equal(before, after, check_exact=True, check_dtype=False)
    contract = module.read(module.verified(result["evaluation_contract"]))
    assert contract["retained_qualified_execution_open_origins"] == [module.reference(state.matured["report_path"])]
    repeated = extend_matured_origin(state, result)
    assert repeated["status"] == "READY", repeated.get("error")
    assert module.read(module.verified(repeated["evaluation_contract"]))["retained_qualified_execution_open_origins"] == contract["retained_qualified_execution_open_origins"]
    assert Path(state.matured["report_path"]).read_bytes() == state.matured_bytes


@pytest.mark.parametrize("fault", ["close", "vendor_open", "unrecorded_open", "identity", "phase_hash", "origin_hash"])
def test_matured_open_reuse_never_approves_new_old_changes(fully_matured_open_origin, tmp_path, monkeypatch, fault):
    state, case = fully_matured_open_origin, fully_matured_open_origin.case
    synthetic_next_closed_source(state, tmp_path, monkeypatch)
    chosen = case.prices.trade_date.eq(pd.Timestamp("2026-09-23")) & case.prices.ticker.eq("T02")
    if fault == "close": case.prices.loc[chosen, "close"] += .25
    elif fault == "vendor_open": case.prices.loc[chosen, "open"] += .25
    elif fault == "unrecorded_open":
        case.prices.loc[case.prices.trade_date.eq(pd.Timestamp("2026-09-23")) & case.prices.ticker.eq("T00"), "open"] += .25
    elif fault == "identity":
        path = Path(case.current["universe"]["report_path"]).parent / "mapped_members.parquet"
        frame = pd.read_parquet(path); frame.loc[frame.ticker.eq("T02"), "security_id"] = "SWAPPED"
        frame.to_parquet(path, index=False); case.current["universe"]["universe_members_sha256"] = module.digest(path)
        case.current_path.write_text(json.dumps(case.current))
    elif fault == "phase_hash": state.phase_path.write_bytes(b"changed original synthetic phase")
    else: Path(state.matured["report_path"]).write_bytes(b"changed immutable origin")
    pointer = case.paths.daily_root / "A2_updated_research/latest.json"; before = pointer.read_bytes()
    result = extend_matured_origin(state)
    assert result["status"] == "BLOCKED"
    assert pointer.read_bytes() == before


def synthetic_second_open(state, prior, tmp_path):
    case = state.case
    phase = {"schema":"A2_EXECUTION_OPEN_INPUTS_V1", "signal_end_date":"2026-09-25",
        "execution_end_date":"2026-09-28", "as_of_utc":"2026-09-28T17:00:00+00:00",
        "current_report":module.reference(case.current_path)}
    captures, factors, refs, identities = [], [], [], []
    for i in range(40):
        ticker, code = f"T{i:02}", f"US.T{i:02}"
        sdk = tmp_path / (ticker + "_second_sdk.parquet")
        pd.DataFrame([{"code":code,"time_key":"2026-09-28","open":135.}]).to_parquet(sdk,index=False)
        factor = tmp_path / (ticker + "_second_rehab.parquet")
        pd.DataFrame(columns=["code","ex_div_date"]).to_parquet(factor,index=False)
        sdk_ref, factor_ref = module.reference(sdk), module.reference(factor)
        captures.append({"item":{"ticker":ticker},"current_kline_provenance":{"code":code,"api":"get_cur_kline",
            "autype":"NONE","session":"RTH","observed_at_utc":phase["as_of_utc"],"sdk_response":sdk_ref}})
        factors.append({"code":code,"status":"PASS",**factor_ref}); refs += [sdk_ref,factor_ref]
        identities.append({"ticker":ticker,"code":code,"security_id":"ID"+ticker})
    acq, rehab = tmp_path/"second_acquisition.json", tmp_path/"second_rehab.json"
    acq.write_text(json.dumps({"acquisition_mode":"current-kline","trade_context_opened":False,"results":captures}))
    rehab.write_text(json.dumps({"source":"MOOMOO_OPEND_GET_REHAB","target_date":"2026-09-28","results":factors}))
    phase.update(records=identities, acquisition_manifest=module.reference(acq),rehab_receipt=module.reference(rehab))
    path = tmp_path/"second_open_phase.json"; path.write_text(json.dumps(phase))
    metadata = {"manifest":module.reference(path),"signal_end_date":phase["signal_end_date"],
        "execution_end_date":phase["execution_end_date"],"as_of_utc":phase["as_of_utc"],
        "qualified_tickers":[f"T{i:02}" for i in range(40)], "consumer_fields":["open"],
        "terminal_close_available":False,"model_feature_eligibility_granted":False}
    case.prices = pd.concat([case.prices,pd.DataFrame([{"trade_date":pd.Timestamp("2026-09-28"),
        "ticker":f"T{i:02}","open":135.,"close":np.nan} for i in range(40)])],ignore_index=True)
    raw = tmp_path/"second_open_raw.parquet"; case.prices.to_parquet(raw,index=False)
    def reader(*a,**kw):
        result = synthetic_price_input(kw,case.prices,case.events,[module.reference(raw),module.reference(case.current_path),
            metadata["manifest"],module.reference(acq),module.reference(rehab),*refs])
        if kw.get("execution_open_manifest") is not None: result["execution_open"] = metadata
        return result
    case.helper.load_execution_prices = reader
    opened = module.refresh_demo_performance(case.paths,case.historical,case.current_path,
        prior_verified_performance_manifest_path=prior["report_path"],retain_qualified_prior_open=True,
        execution_open_manifest=path,execution_end="2026-09-28")
    assert opened["status"] == "READY",opened.get("error")
    return opened


@pytest.fixture
def two_phase_matured(fully_matured_open_origin,tmp_path,monkeypatch):
    state = fully_matured_open_origin
    synthetic_next_closed_source(state,tmp_path,monkeypatch)
    closed = extend_matured_origin(state); assert closed["status"] == "READY",closed.get("error")
    opened = synthetic_second_open(state,closed,tmp_path)
    synthetic_next_closed_source(state,tmp_path,monkeypatch,day="2026-09-28",open_price=135.5)
    mature = extend_matured_origin(state,opened); assert mature["status"] == "READY",mature.get("error")
    state.second_matured = mature
    synthetic_next_closed_source(state,tmp_path,monkeypatch,day="2026-09-29",open_price=140.)
    final = extend_matured_origin(state,mature); assert final["status"] == "READY",final.get("error")
    state.two_phase_final = final
    return state


def test_multiple_native_phases_keep_all_accepted_origins(two_phase_matured):
    state = two_phase_matured
    result = state.two_phase_final
    contract = module.read(module.verified(result["evaluation_contract"]))
    assert contract["retained_qualified_execution_open_origins"] == [
        module.reference(state.matured["report_path"]),module.reference(state.second_matured["report_path"])]
    prices = pd.read_parquet(result["outputs"]["price_paths"]["path"])
    assert prices.loc[prices.date.eq(pd.Timestamp("2026-09-23")), "open"].eq(120.).all()
    assert prices.loc[prices.date.eq(pd.Timestamp("2026-09-28")), "open"].eq(135.).all()
    assert prices.loc[prices.date.eq(pd.Timestamp("2026-09-28")), "close"].eq(136.5).all()
    validate_matured_origin(state,result,end="2026-09-29")


@pytest.mark.parametrize("fault",["omit_old","omit_new","mismatch_input","swap_hash"])
def test_multiphase_origin_closure_cannot_be_omitted_or_swapped(two_phase_matured,fault):
    state = two_phase_matured; result = state.two_phase_final
    path = Path(result["report_path"]); report = module.read(path)
    contract_path = module.verified(report["evaluation_contract"]); contract = module.read(contract_path)
    input_path = module.verified(report["price_inputs"]); inputs = module.read(input_path)
    origins = contract["retained_qualified_execution_open_origins"]
    if fault == "omit_old": origins.pop(0)
    elif fault == "omit_new": origins.pop()
    elif fault == "mismatch_input": inputs["retained_qualified_execution_open_origins"] = []
    else: origins[0] = {**origins[0], "sha256":"0"*64}
    if fault != "mismatch_input": inputs["retained_qualified_execution_open_origins"] = origins
    input_path.write_text(json.dumps(inputs)); report["price_inputs"] = module.reference(input_path)
    contract["price_inputs"] = report["price_inputs"]
    contract_path.write_text(json.dumps(contract)); report["evaluation_contract"] = module.reference(contract_path)
    path.write_text(json.dumps(report))
    with pytest.raises((ValueError,AssertionError)):
        validate_matured_origin(state,report,end="2026-09-29")

def test_matured_same_end_wrapper_then_next_day_uses_original_origin(fully_matured_open_origin,tmp_path,monkeypatch):
    state, case = fully_matured_open_origin, fully_matured_open_origin.case
    wrapper = module.refresh_demo_performance(case.paths,case.historical,case.current_path,
        prior_verified_performance_manifest_path=state.matured["report_path"],
        reuse_same_end_performance=True)
    assert wrapper["status"] == "READY",wrapper.get("error")
    assert wrapper["performance_origin"]["manifest"] == module.reference(state.matured["report_path"])
    wrapper_bytes = Path(wrapper["report_path"]).read_bytes()
    synthetic_next_closed_source(state,tmp_path,monkeypatch)
    result = extend_matured_origin(state,wrapper)
    assert result["status"] == "READY",result.get("error")
    assert module.read(module.verified(result["evaluation_contract"]))["retained_qualified_execution_open_origins"] == [
        module.reference(state.matured["report_path"])]
    assert Path(wrapper["report_path"]).read_bytes() == wrapper_bytes
    assert Path(state.matured["report_path"]).read_bytes() == state.matured_bytes
