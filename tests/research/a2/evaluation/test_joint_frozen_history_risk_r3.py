"""Generated metadata/value fixtures only; no registered numeric source or fit."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.common.storage_paths import StoragePaths
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as r
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, StateCache
from scripts.research.a2.data.shared_risk_inputs_r3 import STORED_LABEL_COORDINATE


@pytest.fixture
def storage(tmp_path, monkeypatch):
    roots = {name: tmp_path / name for name in
             ("data", "cache", "daily", "backtest", "results", "envs")}
    for path in roots.values():
        path.mkdir()
    paths = StoragePaths(r.REPO, *(roots[n] for n in
                         ("data", "cache", "daily", "backtest", "results", "envs")))
    monkeypatch.setattr(r, "resolve", lambda *a, **k: paths)
    run = paths.backtest_root / "V24" / "GENERATED_RUN"
    run.mkdir(parents=True)
    return paths, run


def pin_frame(root, name, frame, datecols):
    target = root / (name + ".parquet")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), target)
    footer = pq.ParquetFile(target)
    guards = {}
    for c in datecols:
        ci = footer.schema.names.index(c)
        guards[c] = []
        for i in range(footer.metadata.num_row_groups):
            stat = footer.metadata.row_group(i).column(ci).statistics
            guards[c].append(dict(min=str(stat.min), max=str(stat.max)))
    return dict(path=str(target), sha256=r.sha(target), schema=list(frame.columns),
                physical_pre2026_guard=guards)


@pytest.fixture
def generated(storage):
    paths, run = storage
    days = pd.bdate_range("2021-07-01", "2023-03-10")
    features = pd.DataFrame([dict(ticker=a, signal_date=d, security_id="UID:"+a,
        feature_available=True, all_features_finite=True, feature_source=r.FEATURE_TAGS[0],
        raw_a2_prediction="FORBIDDEN_PREDICTION", raw_a2_rank="FORBIDDEN_RANK")
        for a in ("A", "B") for d in days])
    rows = [dict(ticker=a, signal_date=days[i], execution_date=days[i+1],
        label_end_date=days[i+6], label_mature_date=days[i+6], endpoint_pair_available=True,
        label_available=True, label_unsupported_common_event=False,
        label_coordinate=STORED_LABEL_COORDINATE, y_open5="FORBIDDEN_NUMERIC")
        for a in ("A", "B") for i in range(len(days)-6)]
    extended = pd.DataFrame(rows)
    base = extended[["ticker", "signal_date"]].copy()
    base["security_id"] = ["UID:"+v for v in base.ticker]
    raw = features[["ticker", "signal_date"]].rename(columns={"signal_date":"trade_date"})
    raw["open"] = "FORBIDDEN_RAW_OPEN"
    raw["close"] = "FORBIDDEN_RAW_CLOSE"
    calendar = pd.DataFrame(dict(trade_date=days))
    sources = dict(
        prediction_features=pin_frame(paths.results_root, "features", features, ["signal_date"]),
        raw_open_close=pin_frame(paths.results_root, "raw", raw, ["trade_date"]),
        shareholder_y5=pin_frame(paths.results_root, "base", base, ["signal_date"]),
        extended_shareholder_y5=pin_frame(paths.results_root, "extended", extended,
            ["signal_date", "execution_date", "label_end_date", "label_mature_date"]),
        calendar=pin_frame(paths.results_root, "calendar", calendar, ["trade_date"]))
    ff = pd.DataFrame([dict(decision_date=pd.Timestamp("2023-01-03"), canonical_security_id="UID:A",
        ticker_at_date="A", sic_available_at=pd.Timestamp("2022-12-01T00:00Z"), ff48_code=1,
        identity_status="AUTHORITATIVE", taxonomy_status="STRICT_PIT_SIC_FF12_FF48_MAPPED",
        sic_source_sha256="e"*64, source_fingerprints='{"source":"GENERATED"}')])
    sources["ff48_surface"] = pin_frame(paths.results_root, "ff48", ff, ["decision_date"])
    for name in r.SOURCE_NAMES:
        sources.setdefault(name, sources["calendar"])
    q = pd.DataFrame(dict(ticker="QQQ", trade_date=days, open="FORBIDDEN_QQQ_OPEN", close="FORBIDDEN_QQQ_CLOSE"))
    sources["qqq_qfq_years"] = [dict(year=year, **pin_frame(paths.data_root, "qqq_"+str(year),
                                q.loc[q.trade_date.dt.year.eq(year)], ["trade_date"]))
                                for year in sorted(set(days.year))]
    def small(name, data):
        p = run/name
        p.write_text(json.dumps(data)+"\n", encoding="utf-8")
        return r.sha(p)
    fsha = small("FAMILY_DESIGN_FREEZE.json", dict(schema="GENERATED", actual_snapshot_timestamp="2026-10-03T00:00:00+00:00"))
    asha = small("SOURCE_AUTHORITY.json", dict(authority="UNKNOWN"))
    csha = small("CONTROL_QUALIFICATION_ANALYSIS_R2.json", dict(conditional_mechanism_eligible=True))
    source = dict(schema="GENERATED", research_id="GENERATED_R3",
        scientific_mode="FROZEN_HISTORY_MECHANISM_ONLY", sources=sources,
        family_design_freeze_sha256=fsha, source_authority_sha256=asha, control_gate_sha256=csha,
        strict_PIT_promotion_eligible=False, quote_qualified=False,
        training_exclusive_boundary="2026-01-01")
    small("FAMILY_SOURCE_INPUTS.json", source)
    science = dict(actual_snapshot_timestamp="2026-10-03T00:00:00+00:00")
    small("SCIENCE_FREEZE.json", science)
    small("BUDGET_SCOPE_FREEZE.json", dict(prior_ledger=dict(reserved=968),
        effective_new_cap=2048, stage1_learned_cap=1024, branch_cumulative_cap=4096))
    return dict(paths=paths, run=run, days=days, source=source, science=science,
                features=features, raw=raw, extended=extended)


def test_support_actual_parquet_projection_never_reads_y_scores_or_prices(generated, monkeypatch):
    monkeypatch.setattr(r.SharedRiskEngine, "fit", lambda *a, **k: pytest.fail("SUPPORT_FIT_FORBIDDEN"))
    result = r.support(generated["run"])
    output = r.read_json(generated["run"] / "RISK_SUPPORT.json")
    assert result["fit_units"] == output["numeric_reads"] == output["fit_units"] == 0
    assert len(output["nodes"]) > 9
    assert all(not r.FORBIDDEN.intersection(p["columns"]) for p in output["projections"])
    assert all(n["assets"] == ["A", "B"] for n in output["nodes"])
    assert all(n["asset_uids"] == {"A":"UID:A", "B":"UID:B"} for n in output["nodes"])
    assert not (generated["run"] / "work/FIT_STATUS.json").exists()
    assert all("BLOCK_UNBOUND_STOCK_HORIZONS_3_10_20" in n["metadata_block_reasons"]
               for n in output["nodes"] if n["method"] == "RM")
    assert all("BLOCK_MISSING_OR_UID_UNBOUND_FF48" in n["metadata_block_reasons"]
               for n in output["nodes"] if n["method"] == "RH")


def test_support_projection_guard_rejects_numeric_columns_before_body(generated):
    reader = r.ProjectedReader(generated["source"], phase="support")
    for source, col, date in [("extended_shareholder_y5", "y_open5", "signal_date"),
                             ("prediction_features", "raw_a2_prediction", "signal_date"),
                             ("qqq_qfq_years", "open", "trade_date")]:
        with pytest.raises(ValueError, match="PROJECTION_FORBIDDEN"):
            reader.read(source, (col,), date_field=date, start="2022-01-01", stop="2023-01-01")
    assert reader.audit == []


def test_numeric_read_has_signal_and_maturity_predicates_before_projection(generated):
    reader = r.ProjectedReader(generated["source"], phase="fit")
    frame = reader.read("extended_shareholder_y5", (*r.LABEL_META, "y_open5"),
        date_field="signal_date", start="2022-12-01", stop="2023-01-03",
        mature_before="2023-01-03", tickers=("A",))
    assert set(frame.ticker) == {"A"}
    assert frame.signal_date.ge(pd.Timestamp("2022-12-01")).all()
    assert all(frame[c].lt(pd.Timestamp("2023-01-03")).all() for c in
               ("signal_date", "execution_date", "label_end_date", "label_mature_date"))
    assert reader.audit[0]["maturity_predicate"] == "2023-01-03"


def test_schedule_first_sessions_prior_ny_close_and_no2026():
    days = pd.bdate_range("2022-12-01", "2026-01-02")
    with pytest.raises(ValueError, match="PRE2026"):
        r.schedule(days)
    nodes = r.schedule(days[days.year < 2026])
    assert len(nodes) == 171
    assert sum(n["method"] == "R0" for n in nodes) == 3
    assert sum(n["method"] == "RD" for n in nodes) == 36
    assert sum(n["method"] == "RR" for n in nodes) == 12
    for n in nodes:
        asof, cutoff = pd.Timestamp(n["as_of"]), pd.Timestamp(n["cutoff"])
        assert cutoff < asof
        assert asof.tz_convert("America/New_York").hour == 16
        assert cutoff.tz_convert("America/New_York").hour == 16
        assert asof < pd.Timestamp("2026-01-01T00:00Z")


def test_pool_keeps_short_uid_epoch_and_never_uses_label_completeness(generated):
    days = generated["days"]
    features = generated["features"].copy()
    cutoff = r._clock("2023-03-01")
    tail = features.ticker.eq("B") & features.signal_date.ge(pd.Timestamp("2023-02-23"))
    features.loc[tail, "security_id"] = "UID:B_NEW"
    features["label_complete"] = False
    features["y_open5"] = -999
    features["raw_a2_prediction"] = -999
    pool = r.current_pool(features, generated["raw"], days, cutoff)
    assert pool["assets"] == ("A", "B") and not pool["blocked_assets"]
    assert pool["segment_starts"]["B"] == "2023-02-23"
    assert pool["asset_uids"]["B"] == "UID:B_NEW"
    # A missing membership session truncates continuity; same UID is never stitched.
    features = features.loc[~(features.ticker.eq("B") & features.signal_date.eq(pd.Timestamp("2023-02-27")))]
    gap = r.current_pool(features, generated["raw"], days, cutoff)
    assert gap["segment_starts"]["B"] == "2023-02-28"


def test_pool_uid_conflict_is_blocked_without_asset_removal(generated):
    features = generated["features"].copy()
    features.loc[features.ticker.eq("B"), "security_id"] = "UID:A"
    pool = r.current_pool(features, generated["raw"], generated["days"], r._clock("2023-03-01"))
    assert pool["assets"] == ("A", "B")
    assert set(pool["blocked_assets"]) == {"A", "B"}


def test_metadata_epoch_short_history_blocked_for_all_nodes(generated):
    source = generated["source"]
    features = generated["features"].copy()
    features.loc[features.ticker.eq("B") & features.signal_date.ge(pd.Timestamp("2023-02-20")), "security_id"] = "UID:B_NEW"
    source["sources"]["prediction_features"] = pin_frame(generated["paths"].results_root, "new_features", features, ["signal_date"])
    reader = r.ProjectedReader(source, phase="support")
    pool, assembly, declaration = r.load_period(reader, source, generated["science"],
        generated["days"], r._clock("2023-03-01"), numeric=False)
    assert pool["assets"] == ("A", "B")
    assert declaration["metadata_supported_labels_by_asset"]["B"] == 0
    assert all("BLOCK_METADATA_252_OR_ASSET30_SUPPORT" in declaration["method_block_reasons"][m] for m in r.METHODS)


def test_source_changed_hash_and_mixed_footer_fail_before_body(generated):
    changed = dict(generated["source"])
    changed["sources"] = dict(changed["sources"])
    changed["sources"]["calendar"] = {**changed["sources"]["calendar"], "sha256":"0"*64}
    with pytest.raises(ValueError, match="PIN_CHANGED"):
        r.ProjectedReader(changed, phase="support")
    bad = pin_frame(generated["paths"].results_root, "mixed_calendar",
                    pd.DataFrame(dict(trade_date=pd.to_datetime(["2025-12-31","2026-01-02"]))), ["trade_date"])
    changed["sources"]["calendar"] = bad
    with pytest.raises(ValueError, match="MIXED_OR_UNKNOWN"):
        r.ProjectedReader(changed, phase="support")


def event(key="a", kind="covariance"):
    return dict(key=key, kind=kind, name="GENERATED", status="RESERVED",
        context=dict(synthetic=False, mechanism=True), inputs_sha256="c"*64, parameters={},
        synthetic=False, mechanism=True)


def test_durable_reservation_precedes_compute_and_failed_state_is_not_refunded(generated):
    ledger = r.DurableFitLedger(generated["run"])
    budget = StateBudget(limit=2, reserve_callback=ledger.reserve)
    cache = StateCache(budget, source_identity=dict(id="G", version="V1", sha256="a"*64),
        cutoff="2023-01-01T00:00:00+00:00", assets=("A",), return_coordinate="G", horizon=5,
        identity_epoch="G", synthetic=False, mechanism=True)
    def fail():
        durable = r.read_json(generated["run"] / "work/FIT_STATUS.json")
        assert durable["fit_attempts"] == 969 and durable["new_fit_units"] == 1
        assert durable["physical_events"][0]["status"] == "STARTED"
        raise RuntimeError("GENERATED_FAILURE")
    with pytest.raises(RuntimeError, match="GENERATED_FAILURE"):
        cache.learn("covariance", "failure", {"x":1}, fail)
    ledger.sync(budget.events)
    disk = r.read_json(generated["run"] / "work/FIT_STATUS.json")
    assert disk["fit_attempts"] == 969 and disk["risk_fit_units"] == 1
    assert disk["physical_events"][0]["status"] == "FIT_FAILURE"
    with pytest.raises(ValueError, match="NO_AUTOMATIC_RETRY"):
        r.DurableFitLedger(generated["run"]).reserve(budget.events[0])
    assert len(disk["failures"]) == 1


def test_successful_cache_exact_reuse_zero_new_cost_and_transform_zero_cost(generated):
    ledger = r.DurableFitLedger(generated["run"])
    budget = StateBudget(limit=2, reserve_callback=ledger.reserve)
    cache = StateCache(budget, source_identity=dict(id="G", version="V1", sha256="a"*64),
        cutoff="2023-01-01T00:00:00+00:00", assets=("A",), return_coordinate="G", horizon=5,
        identity_epoch="G", synthetic=False, mechanism=True)
    assert cache.learn("covariance", "same", {"x":1}, lambda: 3) == 3
    assert cache.learn("covariance", "same", {"x":1}, lambda: pytest.fail("EXACT_REUSE")) == 3
    cache.learn("deterministic_transform", "identity", {"x":1}, lambda: 1)
    ledger.sync(budget.events)
    assert ledger.status["fit_attempts"] == 969 and ledger.status["risk_fit_units"] == 1
    assert len(ledger.status["physical_events"]) == 2
    assert all(e["status"] == "FIT_COMPLETE" for e in ledger.status["physical_events"])


def test_inherited_count_cannot_reset_and_stage_cap_precedes_reservation(generated):
    ledger = r.DurableFitLedger(generated["run"])
    ledger.status.update(risk_fit_units=1024, new_fit_units=1024, fit_attempts=1992)
    ledger.checkpoint()
    with pytest.raises(ValueError, match="RISK_STAGE_CAP"):
        ledger.reserve(event())
    assert ledger.status["fit_attempts"] == 1992 and not ledger.status["physical_events"]
    ledger.status["fit_attempts"] = 0
    ledger.checkpoint()
    with pytest.raises(ValueError, match="INHERITED"):
        r.DurableFitLedger(generated["run"])


def test_fit_missing_freeze_fails_without_numeric_reader(generated, monkeypatch):
    monkeypatch.setattr(r, "ProjectedReader", lambda *a, **k: pytest.fail("NO_NUMERIC_READER_BEFORE_FREEZE"))
    with pytest.raises(FileNotFoundError):
        r.fit(generated["run"])


def test_mechanism_receipt_snapshot_is_provenance_not_historical_availability(generated):
    cutoff = r._clock("2023-01-03")
    receipt = r._receipt(generated["source"], generated["science"], cutoff, "G")
    receipt.validate(cutoff)
    assert receipt.available_at == cutoff
    assert pd.Timestamp(receipt.actual_snapshot_timestamp).year == 2026
    assert receipt.observation_time_assumed and not receipt.strict_PIT_promotion_eligible
    q = r._receipt(generated["source"], generated["science"], cutoff, "Q", benchmark=True)
    q.validate(cutoff, role="benchmark", primary=receipt)
    assert q.return_coordinate == r.BENCHMARK_PROXY_COORDINATE and q.benchmark_proxy_allowed


def test_ff48_exact_current_uid_available_asof_and_no_ticker_alias(generated):
    reader = r.ProjectedReader(generated["source"], phase="support")
    pool = dict(assets=("A",), asset_uids={"A":"UID:A"})
    mapping, receipt, reason = r.asof_ff48(reader, generated["source"], generated["science"],
        pool, r._clock("2023-02-01"), "G")
    assert reason is None and mapping.group.tolist() == [1]
    assert mapping.uid.tolist() == ["UID:A"]
    assert receipt.source_sha256 == generated["source"]["sources"]["ff48_surface"]["sha256"]
    mapping, _, reason = r.asof_ff48(reader, generated["source"], generated["science"],
        dict(assets=("A",), asset_uids={"A":"UID:NEW"}), r._clock("2023-02-01"), "G")
    assert mapping.empty and reason == "BLOCK_MISSING_OR_UID_UNBOUND_FF48"
    mapping, _, reason = r.asof_ff48(reader, generated["source"], generated["science"],
        pool, r._clock("2022-12-30"), "G")
    assert mapping.empty and reason == "BLOCK_MISSING_OR_UID_UNBOUND_FF48"


def test_frozen_full_dependency_pins_are_required_before_numeric(generated, monkeypatch):
    r.support(generated["run"])
    run = generated["run"]
    files = [Path(r.__file__), r.REPO/"scripts/research/a2/data/shared_risk_inputs_r3.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_engine_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_budget_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_extensions_r2.py",
        r.REPO/"scripts/research/a2/risk/joint_risk_estimators.py"]
    freeze = dict(source_inputs_sha256=r.sha(run/"FAMILY_SOURCE_INPUTS.json"),
        family_design_freeze_sha256=r.sha(run/"FAMILY_DESIGN_FREEZE.json"),
        risk_support_sha256="0"*64, budget_scope_sha256=r.sha(run/"BUDGET_SCOPE_FREEZE.json"),
        control_qualification_sha256=r.sha(run/"CONTROL_QUALIFICATION_ANALYSIS_R2.json"),
        code_pins=[dict(path=str(p), sha256=r.sha(p)) for p in files],
        risk_stage_fit_cap=1024, inherited_prior_reserved=968)
    (run/"FAMILY_EXECUTION_FREEZE.json").write_text(json.dumps(freeze), encoding="utf-8")
    monkeypatch.setattr(r, "ProjectedReader", lambda *a, **k: pytest.fail("NO_READER_ON_BAD_FREEZE"))
    with pytest.raises(ValueError, match="PIN_CHANGED:risk_support"):
        r.fit(run)

def test_full_cli_fit_generated_only_durable_units_and_pinned_resume(generated, monkeypatch):
    source = generated["source"]
    frame = generated["extended"].copy()
    frame["y_open5"] = np.sin(np.arange(len(frame))) / 100
    source["sources"]["extended_shareholder_y5"] = pin_frame(generated["paths"].results_root,
        "generated_numeric_labels", frame, ["signal_date", "execution_date", "label_end_date", "label_mature_date"])
    for pin in source["sources"]["qqq_qfq_years"]:
        q = pq.read_table(pin["path"]).to_pandas()
        q["open"] = 100 + np.arange(len(q))/100
        pin.update(pin_frame(generated["paths"].data_root, "generated_open_"+str(pin["year"]), q, ["trade_date"]))
    run = generated["run"]
    (run/"FAMILY_SOURCE_INPUTS.json").write_text(json.dumps(source), encoding="utf-8")
    node = next(n for n in r.schedule(generated["days"]) if n["method"] == "R0")
    monkeypatch.setattr(r, "schedule", lambda days: [node])
    assert r.support(run)["metadata_numeric_check_eligible"] == 1
    files = [Path(r.__file__), r.REPO/"scripts/research/a2/data/shared_risk_inputs_r3.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_engine_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_budget_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_extensions_r2.py",
        r.REPO/"scripts/research/a2/risk/joint_risk_estimators.py"]
    freeze = dict(source_inputs_sha256=r.sha(run/"FAMILY_SOURCE_INPUTS.json"),
        family_design_freeze_sha256=r.sha(run/"FAMILY_DESIGN_FREEZE.json"),
        risk_support_sha256=r.sha(run/"RISK_SUPPORT.json"),
        budget_scope_sha256=r.sha(run/"BUDGET_SCOPE_FREEZE.json"),
        control_qualification_sha256=r.sha(run/"CONTROL_QUALIFICATION_ANALYSIS_R2.json"),
        code_pins=[dict(path=str(p), sha256=r.sha(p)) for p in files],
        risk_stage_fit_cap=1024, inherited_prior_reserved=968)
    (run/"FAMILY_EXECUTION_FREEZE.json").write_text(json.dumps(freeze), encoding="utf-8")
    result = r.fit(run)
    assert result["risk_fit_units"] == 2 and result["cumulative_B_fit_units"] == 970
    ledger = r.read_json(run/"work/FIT_STATUS.json")
    row = ledger["records"][0]
    assert row["status"] == "PASS_FROZEN_HISTORY_MECHANISM"
    assert row["assets"] == ["A","B"] and row["learned_states"] == 2
    assert all(e["status"] == "FIT_COMPLETE" for e in ledger["physical_events"])
    assert r.fit(run)["risk_fit_units"] == 2  # Retained successful state; no new fit.
    Path(row["artifact"]).write_bytes(b"GENERATED_MUTATION")
    with pytest.raises(ValueError, match="PIN_CHANGED:retained_risk_state"):
        r.fit(run)


@pytest.fixture
def component_case(generated):
    g = generated
    source, paths = g["source"], g["paths"]
    # C has independent UID metadata UNKNOWN; D has no exact FF48 group.
    c = g["features"].loc[g["features"].ticker.eq("A")].copy()
    c["ticker"], c["security_id"] = "C", None
    d = g["features"].loc[g["features"].ticker.eq("A")].copy()
    d["ticker"], d["security_id"] = "D", "UID:D"
    features = pd.concat([g["features"], c, d], ignore_index=True)
    raw = features[["ticker","signal_date"]].rename(columns={"signal_date":"trade_date"})
    raw["open"], raw["close"] = "FORBIDDEN_RAW_OPEN", "FORBIDDEN_RAW_CLOSE"
    labels = g["extended"].copy()
    extra = labels.loc[labels.ticker.eq("A")].copy()
    extra["ticker"] = "D"
    labels = pd.concat([labels, extra], ignore_index=True)
    base = labels[["ticker","signal_date"]].copy()
    base["security_id"] = base.ticker.map({"A":"UID:A","B":"UID:B","D":"UID:D"})
    ff = pd.DataFrame([dict(decision_date=pd.Timestamp("2023-01-03"),
        canonical_security_id="UID:"+a, ticker_at_date=a,
        sic_available_at=pd.Timestamp("2022-12-01T00:00Z"), ff48_code=i+1,
        identity_status="AUTHORITATIVE", taxonomy_status="STRICT_PIT_SIC_FF12_FF48_MAPPED",
        sic_source_sha256="e"*64, source_fingerprints='{"source":"GENERATED"}')
        for i,a in enumerate(("A","B"))])
    for name, frame, dates in (
        ("prediction_features",features,["signal_date"]),
        ("raw_open_close",raw,["trade_date"]), ("shareholder_y5",base,["signal_date"]),
        ("extended_shareholder_y5",labels,["signal_date","execution_date","label_end_date","label_mature_date"]),
        ("ff48_surface",ff,["decision_date"])):
        source["sources"][name] = pin_frame(paths.results_root,"component_"+name,frame,dates)
    run = g["run"]
    (run/"FAMILY_SOURCE_INPUTS.json").write_text(json.dumps(source),encoding="utf-8")
    r.support(run)
    contract = dict(research_id="V24_B_SOURCE_QUALIFIED_H5_FF48_RISK_COMPONENT_R1",
        source_inputs_sha256=r.sha(run/"FAMILY_SOURCE_INPUTS.json"),
        family_design_freeze_sha256=r.sha(run/"FAMILY_DESIGN_FREEZE.json"),
        control_qualification_sha256=r.sha(run/"CONTROL_QUALIFICATION_ANALYSIS_R2.json"),
        strict_PIT_promotion_eligible=False, account_attempts=0,forecast_fits=0,
        minimum_supported_h5=30,fixed_parent_origins=252,minimum_component_assets=2)
    (run/"RISK_COMPONENT_SCIENCE_FREEZE.json").write_text(json.dumps(contract),encoding="utf-8")
    return {**g, "labels":labels, "component_contract":contract}


def test_component_support_keeps_parent_blocked_but_valid_metadata_subdomain(component_case):
    g = component_case
    _, source, science, _ = r.guard_run(g["run"],"component-support")
    reader = r.ProjectedReader(source, phase="support")
    pool, assembly, declaration = r.load_component_period(reader,source,science,g["days"],
        r._clock("2023-01-31"),numeric=False)
    assert pool["assets"] == ("A","B")
    assert pool["parent_requested"]["assets"] == ("A","B","C","D")
    assert pool["parent_requested"]["blocked_assets"] == {"C":"AMBIGUOUS_OR_MISSING_CURRENT_UID"}
    assert declaration["excluded_reasons"]["C"] == ["AMBIGUOUS_OR_MISSING_CURRENT_UID"]
    assert declaration["excluded_reasons"]["D"] == ["BLOCK_COMPONENT_EXACT_ASOF_FF48_MISSING"]
    assert len(pool["parent_origin_window"]) == 252 and assembly is not None
    assert declaration["component_supported_h5_by_asset"]["A"] == 252
    assert all(not r.FORBIDDEN.intersection(a["columns"]) for a in reader.audit)
    assert not declaration["method_block_reasons"]["RD"]
    assert declaration["method_block_reasons"]["RM"] == ["BLOCK_UNBOUND_STOCK_HORIZONS_3_10_20"]
    assert assembly.risk_input.source_receipt.scientific_contract_sha256 == r.sha(g["run"]/"RISK_COMPONENT_SCIENCE_FREEZE.json")


def test_component_first_prior2022_ff48_not_backfilled(component_case):
    g = component_case
    _, source, science, _ = r.guard_run(g["run"],"component-support")
    pool, assembly, declaration = r.load_component_period(r.ProjectedReader(source,phase="support"),
        source,science,g["days"],r._clock("2022-12-30"),numeric=False)
    assert pool["assets"] == () and assembly is None
    assert all("BLOCK_COMPONENT_EXACT_ASOF_FF48_MISSING" in reasons
               for a,reasons in declaration["excluded_reasons"].items() if a in ("A","B","D"))
    assert len(declaration["parent_origin_window"]) == 252


def test_component_finite_change_blocks_node_without_removing_asset_or_reading_excluded_y(component_case):
    g = component_case
    _, source, science, _ = r.guard_run(g["run"],"component-support")
    pool, _, _ = r.load_component_period(r.ProjectedReader(source,phase="support"),
        source,science,g["days"],r._clock("2023-01-31"),numeric=False)
    expected = {k:r._json(pool[k]) for k in ("assets","asset_uids","asset_epochs","parent_origin_window")}
    reader = r.ProjectedReader(source,phase="fit")
    fitted_pool, assembly, declaration = r.load_component_period(reader,source,science,g["days"],
        r._clock("2023-01-31"),numeric=True,expected=expected)
    assert fitted_pool["assets"] == ("A","B") and assembly is None
    assert declaration["reason"] == "BLOCK_COMPONENT_NUMERIC_FINITE_SUPPORT_CHANGED"
    numeric = [a for a in reader.audit if "y_open5" in a["columns"]]
    assert len(numeric) == 1 and numeric[0]["exact_tickers"] == ["A","B"]
    assert not any("open" in a["columns"] for a in reader.audit)
    changed = {**expected,"assets":["A"]}
    reader = r.ProjectedReader(source,phase="fit")
    with pytest.raises(ValueError,match="FROZEN_COMPONENT_DOMAIN"):
        r.load_component_period(reader,source,science,g["days"],
            r._clock("2023-01-31"),numeric=True,expected=changed)
    assert not any("y_open5" in a["columns"] for a in reader.audit)


def test_component_equal_parent_domain_requests_original_reuse_no_forced_drop(component_case):
    g = component_case
    source = json.loads(json.dumps(g["source"]))
    f = pq.read_table(source["sources"]["prediction_features"]["path"]).to_pandas()
    f = f.loc[f.ticker.isin(["A","B"])]
    source["sources"]["prediction_features"] = pin_frame(g["paths"].results_root,"component_full_domain",f,["signal_date"])
    science = {**g["science"],"scientific_contract_identity":"GENERATED_COMPONENT","scientific_contract_sha256":"c"*64}
    pool, assembly, declaration = r.load_component_period(r.ProjectedReader(source,phase="support"),
        source,science,g["days"],r._clock("2023-01-31"),numeric=False)
    assert pool["assets"] == ("A","B") and assembly is None
    assert declaration["reason"] == "REUSE_ORIGINAL_FULL_DOMAIN_NOT_COMPONENT"
    assert declaration["excluded_reasons"] == {}


def component_execution_freeze(run):
    files = [Path(r.__file__), r.REPO/"scripts/research/a2/data/shared_risk_inputs_r3.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_engine_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_budget_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_extensions_r2.py",
        r.REPO/"scripts/research/a2/risk/joint_risk_estimators.py"]
    (run/"RISK_COMPONENT_REGISTRATION_RECEIPT.json").write_text('{"registered":"GENERATED"}',encoding="utf-8")
    freeze = dict(source_inputs_sha256=r.sha(run/"FAMILY_SOURCE_INPUTS.json"),
        family_design_freeze_sha256=r.sha(run/"FAMILY_DESIGN_FREEZE.json"),
        risk_component_support_sha256=r.sha(run/"RISK_COMPONENT_SUPPORT.json"),
        risk_component_science_sha256=r.sha(run/"RISK_COMPONENT_SCIENCE_FREEZE.json"),
        registration_receipt_sha256=r.sha(run/"RISK_COMPONENT_REGISTRATION_RECEIPT.json"),
        budget_scope_sha256=r.sha(run/"BUDGET_SCOPE_FREEZE.json"),
        control_qualification_sha256=r.sha(run/"CONTROL_QUALIFICATION_ANALYSIS_R2.json"),
        code_pins=[dict(path=str(p),sha256=r.sha(p)) for p in files],
        risk_stage_fit_cap=1024,inherited_prior_reserved=968)
    (run/"RISK_COMPONENT_EXECUTION_FREEZE.json").write_text(json.dumps(freeze),encoding="utf-8")


def test_component_cli_fit_independent_record_prefix_same_cumulative_ledger(component_case,monkeypatch):
    g = component_case
    source = g["source"]
    labels = g["labels"].copy()
    labels["y_open5"] = np.sin(np.arange(len(labels)))/100
    source["sources"]["extended_shareholder_y5"] = pin_frame(g["paths"].results_root,
        "component_numeric",labels,["signal_date","execution_date","label_end_date","label_mature_date"])
    run = g["run"]
    (run/"FAMILY_SOURCE_INPUTS.json").write_text(json.dumps(source),encoding="utf-8")
    contract = g["component_contract"].copy()
    contract["source_inputs_sha256"] = r.sha(run/"FAMILY_SOURCE_INPUTS.json")
    (run/"RISK_COMPONENT_SCIENCE_FREEZE.json").write_text(json.dumps(contract),encoding="utf-8")
    node = next(n for n in r.schedule(g["days"]) if n["method"] == "RD" and n["as_of"].startswith("2023-02"))
    monkeypatch.setattr(r,"schedule",lambda days:[node])
    parent_bytes = (run/"RISK_SUPPORT.json").read_bytes()
    assert r.support(run,component=True)["metadata_numeric_check_eligible"] == 1
    assert (run/"RISK_SUPPORT.json").read_bytes() == parent_bytes
    component_execution_freeze(run)
    result = r.fit(run,component=True)
    assert result["risk_fit_units"] == 2 and result["cumulative_B_fit_units"] == 970
    ledger = r.read_json(run/"work/FIT_STATUS.json")
    row = ledger["records"][0]
    assert row["risk_node"].startswith("component:RD@")
    assert row["assets"] == ["A","B"] and row["parent_requested"]["assets"] == ["A","B","C","D"]
    assert row["status"] == "PASS_FROZEN_HISTORY_MECHANISM"
    assert ledger["account_paths"] == 2 and ledger["test2026_rows_read"] == 0
    assert r.fit(run,component=True)["risk_fit_units"] == 2
    assert (run/"RISK_SUPPORT.json").read_bytes() == parent_bytes



@pytest.mark.parametrize("name,size,allowed", [
    ("RISK_SUPPORT.json", 37660482, True),
    ("RISK_COMPONENT_SUPPORT.json", 128*1024*1024, True),
    ("RISK_SUPPORT.json", 128*1024*1024+1, False),
    ("ordinary_contract.json", 32*1024*1024+1, False),
])
def test_only_fixed_support_metadata_has_larger_bounded_limit(tmp_path,monkeypatch,name,size,allowed):
    path = tmp_path/name
    path.write_text('{"schema":"GENERATED_METADATA_ONLY"}',encoding="utf-8")
    old_stat = Path.stat
    def size_stat(self,*args,**kwargs):
        if self == path:
            return SimpleNamespace(st_size=size)
        return old_stat(self,*args,**kwargs)
    monkeypatch.setattr(Path,"stat",size_stat)
    if allowed:
        assert r.read_json(path)["schema"] == "GENERATED_METADATA_ONLY"
    else:
        with pytest.raises(ValueError,match="COMPACT_METADATA_LIMIT"):
            r.read_json(path)


def amendment_case(generated):
    run = generated["run"]
    r.support(run)
    frozen_code = generated["paths"].results_root/"generated_frozen_code.py"
    frozen_code.write_text("GENERATED_OLD_BYTES",encoding="utf-8")
    files = [Path(r.__file__), r.REPO/"scripts/research/a2/data/shared_risk_inputs_r3.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_engine_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_budget_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_extensions_r2.py",
        r.REPO/"scripts/research/a2/risk/joint_risk_estimators.py", frozen_code]
    freeze = dict(source_inputs_sha256=r.sha(run/"FAMILY_SOURCE_INPUTS.json"),
        family_design_freeze_sha256=r.sha(run/"FAMILY_DESIGN_FREEZE.json"),
        risk_support_sha256=r.sha(run/"RISK_SUPPORT.json"),
        budget_scope_sha256=r.sha(run/"BUDGET_SCOPE_FREEZE.json"),
        control_qualification_sha256=r.sha(run/"CONTROL_QUALIFICATION_ANALYSIS_R2.json"),
        code_pins=[dict(path=str(p),sha256=r.sha(p)) for p in files],
        risk_stage_fit_cap=1024,inherited_prior_reserved=968)
    base = run/"FAMILY_EXECUTION_FREEZE.json"
    base.write_text(json.dumps(freeze),encoding="utf-8")
    prior = r.sha(frozen_code)
    frozen_code.write_text("GENERATED_PATCHED_BYTES",encoding="utf-8")
    patch = dict(base_execution_freeze_sha256=r.sha(base),
        support_sha256=freeze["risk_support_sha256"],source_inputs_sha256=freeze["source_inputs_sha256"],
        semantic_change=False,no_numeric_read_before_patch=True,
        code_pin_changes=[dict(path=str(frozen_code),prior_sha256=prior,sha256=r.sha(frozen_code))])
    return run,freeze,patch


def test_exact_implementation_amendment_replaces_pin_without_rewriting_freeze_or_support(generated,monkeypatch):
    run,freeze,patch = amendment_case(generated)
    base_bytes = (run/"FAMILY_EXECUTION_FREEZE.json").read_bytes()
    support_bytes = (run/"RISK_SUPPORT.json").read_bytes()
    with pytest.raises(ValueError,match="PIN_CHANGED:code"):
        r.guard_run(run,"fit")
    path = run/"EXECUTION_IMPLEMENTATION_AMENDMENT_R1.json"
    path.write_text(json.dumps(patch),encoding="utf-8")
    _,_,science,returned = r.guard_run(run,"fit")
    assert returned == freeze
    lineage = science["implementation_lineage"]
    assert lineage["base_execution_freeze_sha256"] == r.sha(run/"FAMILY_EXECUTION_FREEZE.json")
    assert lineage["execution_implementation_amendment_sha256"] == r.sha(path)
    assert lineage["execution_implementation_amendments"][0]["status"] == "APPLIED"
    assert (run/"FAMILY_EXECUTION_FREEZE.json").read_bytes() == base_bytes
    assert (run/"RISK_SUPPORT.json").read_bytes() == support_bytes
    assert not (run/"work/FIT_STATUS.json").exists()


@pytest.mark.parametrize("tamper,error", [
    ("prior","AMENDMENT_PRIOR_CODE_PIN"),
    ("new","PIN_CHANGED:code"),
    ("path","DEPENDENCIES_CANNOT_CHANGE"),
    ("duplicate","DEPENDENCIES_CANNOT_CHANGE"),
    ("support","SUPPORT_OR_SOURCE_BINDING"),
    ("base","PIN_CHANGED:amendment_base_execution"),
    ("semantic","IMPLEMENTATION_ONLY_PRE_NUMERIC"),
])
def test_amendment_wrong_prior_binding_or_dependency_change_rejected_before_numeric(generated,monkeypatch,tamper,error):
    run,freeze,patch = amendment_case(generated)
    if tamper == "prior":
        patch["code_pin_changes"][0]["prior_sha256"] = "0"*64
    elif tamper == "new":
        patch["code_pin_changes"][0]["sha256"] = "0"*64
    elif tamper == "path":
        patch["code_pin_changes"][0]["path"] = str(run/"unregistered_new_dependency.py")
    elif tamper == "duplicate":
        patch["code_pin_changes"].append(dict(patch["code_pin_changes"][0]))
    elif tamper == "support":
        patch["support_sha256"] = "0"*64
    elif tamper == "base":
        patch["base_execution_freeze_sha256"] = "0"*64
    else:
        patch["semantic_change"] = True
    (run/"EXECUTION_IMPLEMENTATION_AMENDMENT_R1.json").write_text(json.dumps(patch),encoding="utf-8")
    monkeypatch.setattr(r,"ProjectedReader",lambda *a,**k:pytest.fail("NO_READER_BEFORE_AMENDMENT_VALIDATED"))
    with pytest.raises(ValueError,match=error):
        r.fit(run)
    assert not (run/"work/FIT_STATUS.json").exists()


def test_old_amendment_is_not_applied_to_new_base_with_all_current_pins(generated):
    run,freeze,patch = amendment_case(generated)
    amendment = run/"EXECUTION_IMPLEMENTATION_AMENDMENT_R1.json"
    amendment.write_text(json.dumps(patch),encoding="utf-8")
    current = {**freeze, "code_pins":[{**p,"sha256":r.sha(p["path"])} for p in freeze["code_pins"]]}
    component_base = run/"RISK_COMPONENT_EXECUTION_FREEZE.json"
    component_base.write_text(json.dumps(current),encoding="utf-8")
    before = component_base.read_bytes()
    pins,lineage = r.execution_code_pins(run,current,
        freeze_name="RISK_COMPONENT_EXECUTION_FREEZE.json", support_key="risk_component_support_sha256")
    assert pins == current["code_pins"]
    assert lineage["amendment_status"] == "NOT_APPLICABLE_TO_THIS_BASE"
    assert lineage["base_execution_freeze_sha256"] == r.sha(component_base)
    assert lineage["execution_implementation_amendment_sha256"] == r.sha(amendment)
    assert component_base.read_bytes() == before

@pytest.mark.parametrize("winerror",[5,32,33])
def test_atomic_metadata_replace_retries_only_transient_windows_errors(storage,monkeypatch,winerror):
    _,run = storage
    target = run/"work/FIT_STATUS.json"
    target.parent.mkdir()
    target.write_text('{"old":true}',encoding="utf-8")
    temporary = target.with_suffix(".json.tmp")
    old_replace = Path.replace
    calls,waits = [],[]
    def replace_retry(self,destination):
        if self == temporary:
            calls.append(1)
            if len(calls)<3:
                error=OSError("GENERATED_SHARING_CONFLICT")
                error.winerror=winerror
                raise error
        return old_replace(self,destination)
    monkeypatch.setattr(Path,"replace",replace_retry)
    monkeypatch.setattr(r.time,"sleep",lambda delay:waits.append(delay))
    r.write(run,"work/FIT_STATUS.json",{"new":True})
    assert len(calls)==3 and waits==[.05,.1]
    assert r.read_json(target)=={"new":True} and not temporary.exists()


@pytest.mark.parametrize("winerror,attempts",[ (5,6), (87,1) ])
def test_terminal_metadata_failure_keeps_fsynced_tmp_and_old_target(storage,monkeypatch,winerror,attempts):
    _,run=storage
    target=run/"work/FIT_STATUS.json"
    target.parent.mkdir()
    target.write_text('{"old":true}',encoding="utf-8")
    temporary=target.with_suffix(".json.tmp")
    old_replace=Path.replace
    calls=[]
    def fail(self,destination):
        if self==temporary:
            calls.append(1)
            error=OSError("GENERATED_TERMINAL_REPLACE_FAILURE")
            error.winerror=winerror
            raise error
        return old_replace(self,destination)
    monkeypatch.setattr(Path,"replace",fail)
    monkeypatch.setattr(r.time,"sleep",lambda delay:None)
    with pytest.raises(OSError,match="GENERATED_TERMINAL"):
        r.write(run,"work/FIT_STATUS.json",{"journal":"PRESERVED"})
    assert len(calls)==attempts
    assert r.read_json(target)=={"old":True}
    assert r.read_json(temporary)=={"journal":"PRESERVED"}


def test_r1_unrelated_does_not_block_matching_post_execution_r2(generated):
    run,freeze,r1=amendment_case(generated)
    r1["base_execution_freeze_sha256"]="f"*64
    (run/"EXECUTION_IMPLEMENTATION_AMENDMENT_R1.json").write_text(json.dumps(r1),encoding="utf-8")
    r2={**r1,"base_execution_freeze_sha256":r.sha(run/"FAMILY_EXECUTION_FREEZE.json"),
        "no_new_numeric_read_during_patch":True,"prior_execution_preserved":True,"fit_retry_allowed":False}
    r2.pop("no_numeric_read_before_patch")
    (run/"EXECUTION_IMPLEMENTATION_AMENDMENT_R2.json").write_text(json.dumps(r2),encoding="utf-8")
    _,_,science,_=r.guard_run(run,"fit")
    lineage=science["implementation_lineage"]
    assert [a["status"] for a in lineage["execution_implementation_amendments"]]==[
        "NOT_APPLICABLE_TO_THIS_BASE","APPLIED"]
    assert lineage["execution_implementation_amendment_sha256"]==r.sha(run/"EXECUTION_IMPLEMENTATION_AMENDMENT_R2.json")


def test_matching_r1_then_r2_uses_effective_prior_pin_and_validates_final_bytes(generated):
    run,freeze,r1=amendment_case(generated)
    old_change=r1["code_pin_changes"][0]
    code=Path(old_change["path"])
    (run/"EXECUTION_IMPLEMENTATION_AMENDMENT_R1.json").write_text(json.dumps(r1),encoding="utf-8")
    intermediate=r.sha(code)
    code.write_text("GENERATED_SECOND_ENGINEERING_PATCH",encoding="utf-8")
    r2={k:v for k,v in r1.items() if k!="no_numeric_read_before_patch"}
    r2.update(no_new_numeric_read_during_patch=True,prior_execution_preserved=True,fit_retry_allowed=False,
        code_pin_changes=[dict(path=str(code),prior_sha256=intermediate,sha256=r.sha(code))])
    path=run/"EXECUTION_IMPLEMENTATION_AMENDMENT_R2.json"
    path.write_text(json.dumps(r2),encoding="utf-8")
    _,_,science,_=r.guard_run(run,"fit")
    assert [a["status"] for a in science["implementation_lineage"]["execution_implementation_amendments"]]==["APPLIED","APPLIED"]
    r2["code_pin_changes"][0]["prior_sha256"]=old_change["prior_sha256"]
    path.write_text(json.dumps(r2),encoding="utf-8")
    with pytest.raises(ValueError,match="AMENDMENT_PRIOR_CODE_PIN"):
        r.guard_run(run,"fit")


def test_unique_work_fit_status_has_256mib_bound_other_contract_stays32(tmp_path,monkeypatch):
    work=tmp_path/"work"
    work.mkdir()
    path=work/"FIT_STATUS.json"
    path.write_text('{"metadata":"GENERATED_LEDGER"}',encoding="utf-8")
    old_stat=Path.stat
    size=[200*1024*1024]
    def metadata_stat(self,*args,**kwargs):
        return SimpleNamespace(st_size=size[0]) if self==path else old_stat(self,*args,**kwargs)
    monkeypatch.setattr(Path,"stat",metadata_stat)
    assert r.read_json(path)["metadata"]=="GENERATED_LEDGER"
    size[0]=256*1024*1024+1
    with pytest.raises(ValueError,match="COMPACT_METADATA_LIMIT"):
        r.read_json(path)


def test_explicit_abandoned_recovery_is_pinned_no_refund_no_retry_and_never_edits_journal(storage):
    _,run=storage
    status=dict(fit_attempts=1093,inherited_fit_units=968,new_fit_units=125,risk_fit_units=125,
        records=[dict(risk_node="component:RR@GENERATED",status="FIT_FAILURE",learned_states=0)])
    with pytest.raises(ValueError,match="EXPLICIT_REPAIR"):
        r.validate_risk_recovery(run,status,component=True)
    status["records"][0]["status"]="ABANDONED_CHECKPOINT_FAILURE"
    with pytest.raises(ValueError,match="RECOVERY_AUDIT_REQUIRED"):
        r.validate_risk_recovery(run,status,component=True)
    audit=run/"work/GENERATED_RECOVERY_AUDIT.json"
    audit.parent.mkdir()
    audit.write_text(json.dumps(dict(semantic_change=False,fit_retry_allowed=False,fit_unit_refund=False)),encoding="utf-8")
    digest=r.sha(audit)
    status["engineering_recovery_audits"]=[dict(path=str(audit),sha256=digest)]
    status["records"][0]["recovery_audit_sha256"]=digest
    for method in ("RU","RE"):
        status["records"].append(dict(risk_node="component:"+method+"@GENERATED",
            status="BLOCKED_INTERRUPTED_SHARED_DAG",learned_states=0,recovery_audit_sha256=digest))
    before=json.dumps(status,sort_keys=True)
    r.validate_risk_recovery(run,status,component=True)
    assert json.dumps(status,sort_keys=True)==before
    assert status["new_fit_units"]==125 and status["fit_attempts"]==1093
    audit.write_text('{"semantic_change":true}',encoding="utf-8")
    with pytest.raises(ValueError,match="PIN_CHANGED:engineering_recovery"):
        r.validate_risk_recovery(run,status,component=True)


@pytest.fixture
def correction_case(storage):
    """Tiny generated metadata authority and paused ledger; no existing run is read."""
    _, run = storage
    def put(name, body):
        path = run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body)+"\n", encoding="utf-8")
        return r.sha(path)
    put("FAMILY_SOURCE_INPUTS.json", {"generated": True})
    put("FAMILY_DESIGN_FREEZE.json", {"generated": True})
    put("SOURCE_AUTHORITY.json", {"authority": "UNKNOWN"})
    science = {"scientific_contract_identity": "GENERATED_PARENT",
               "scientific_contract_sha256": put("RISK_COMPONENT_SCIENCE_FREEZE.json",
                                                 {"research_id": "GENERATED_PARENT"})}
    put("BUDGET_SCOPE_FREEZE.json", dict(prior_ledger=dict(reserved=968),
        effective_new_cap=2048, stage1_learned_cap=1024, branch_cumulative_cap=4096))
    nodes = []
    days = pd.bdate_range("2021-01-01", "2025-12-31")
    for asof in r.RR_CORRECTION_ASOFS:
        date = pd.Timestamp(asof).tz_convert("America/New_York").tz_localize(None).normalize()
        cutoff = r._clock(days[days.get_loc(date)-1]).isoformat()
        nodes.append(dict(method="RR", as_of=asof, cutoff=cutoff, assets=["A","B","C"],
            asset_uids={a:"UID:"+a for a in ("A","B","C")},
            asset_epochs={a:"EPOCH" for a in ("A","B","C")},
            numeric_check_eligible=False, metadata_block_reasons=["GENERATED_OTHER_QUARTER"],
            parent_requested={"assets":["A","B","C"]}, parent_origin_window=[],
            excluded_reasons={}))
    nodes[0]["numeric_check_eligible"] = True
    nodes[0]["metadata_block_reasons"] = []
    nodes = [dict(nodes[0], method="RD"), dict(nodes[0], method="RB"), *nodes]
    support_sha = put("RISK_COMPONENT_SUPPORT.json", {"nodes": nodes})
    files = [Path(r.__file__), r.REPO/"scripts/research/a2/data/shared_risk_inputs_r3.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_engine_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_budget_r2.py",
        r.REPO/"scripts/research/a2/risk/shared_risk_extensions_r2.py",
        r.REPO/"scripts/research/a2/risk/joint_risk_estimators.py"]
    freeze = dict(code_pins=[dict(path=str(f), sha256=r.sha(f)) for f in files],
        risk_component_support_sha256=support_sha,
        source_inputs_sha256=r.sha(run/"FAMILY_SOURCE_INPUTS.json"))
    put("RISK_COMPONENT_EXECUTION_FREEZE.json", freeze)
    spec_sha = put("RR_INPUT_BINDING_CORRECTION_SPEC.json", {"research_id":r.RR_CORRECTION_ID})
    registration_sha = put("RR_INPUT_BINDING_CORRECTION_REGISTRATION_RECEIPT.json",
        dict(research_id=r.RR_CORRECTION_ID, correction_spec_sha256=spec_sha,
             entity_id="GENERATED_PARENT", registration_kind="REGISTERED_CORRECTION_UNDER_EXISTING_PARENT"))
    pause_sha = put("RR_INPUT_BINDING_PAUSE_RECEIPT.json", {"generated_pause":True})
    ledger = dict(status="PAUSED", fit_attempts=1249, inherited_fit_units=968,
        new_fit_units=281, risk_fit_units=281, records=[], failures=[], physical_events=[],
        account_paths=2, test2026_rows_read=0)
    checkpoint_sha = put("work/rr_binding_pause/FIT_STATUS.json", ledger)
    put("work/FIT_STATUS.json", ledger)
    correction = dict(schema=r.RR_CORRECTION_SCHEMA, research_id=r.RR_CORRECTION_ID,
        status="FROZEN_BEFORE_CORRECTED_RR_NUMERIC_READ_OR_FIT",
        correction_spec_sha256=spec_sha,
        parent_component_science_sha256=r.sha(run/"RISK_COMPONENT_SCIENCE_FREEZE.json"),
        parent_component_execution_sha256=r.sha(run/"RISK_COMPONENT_EXECUTION_FREEZE.json"),
        parent_component_support_sha256=support_sha,
        source_inputs_sha256=r.sha(run/"FAMILY_SOURCE_INPUTS.json"),
        family_design_freeze_sha256=r.sha(run/"FAMILY_DESIGN_FREEZE.json"),
        source_authority_sha256=r.sha(run/"SOURCE_AUTHORITY.json"),
        registration_receipt_sha256=registration_sha, pause_receipt_sha256=pause_sha,
        checkpoint_ledger_sha256=checkpoint_sha, checkpoint_new_fit_units=281,
        start_as_of=r.RR_CORRECTION_ASOFS[0], allowed_as_of=list(r.RR_CORRECTION_ASOFS),
        qqq_open_lookback_sessions=360, max_additional_units_per_quarter=7, max_quarters=6,
        code_pins=freeze["code_pins"], primary_stock_frame_unchanged=True,
        primary_source_receipt_unchanged=True, qqq_source_receipt_unchanged=True,
        industry_receipt_unchanged=True, other_methods_input_binding_unchanged=True,
        rr_input_binding_changed=True, prior_completed_rr_reexecution=False,
        strict_PIT_promotion_eligible=False, quote_qualified=False,
        certified_nav=False, account_equivalence=False, account_attempts=0,
        forecast_fits=0, test2026_rows_read=0)
    put("RR_INPUT_BINDING_CORRECTION_FREEZE.json", correction)
    return dict(run=run, science=science, freeze=freeze, correction=correction,
                ledger=ledger, nodes=nodes, days=days, put=put)


def _guard_correction(case):
    return r.guard_rr_correction(case["run"], case["science"], case["freeze"])


def test_correction_absent_default_path_and_parent_registry_receipt_supported(correction_case):
    c=correction_case
    accepted=_guard_correction(c)
    assert accepted["research_id"]==r.RR_CORRECTION_ID
    assert accepted["freeze_sha256"]==r.sha(c["run"]/"RR_INPUT_BINDING_CORRECTION_FREEZE.json")
    (c["run"]/"RR_INPUT_BINDING_CORRECTION_FREEZE.json").unlink()
    assert _guard_correction(c) is None


@pytest.mark.parametrize("field,value", [
    ("schema","UNKNOWN"), ("research_id","OLD_RR"), ("rr_input_binding_changed",False),
    ("primary_stock_frame_unchanged",False), ("primary_source_receipt_unchanged",False),
    ("qqq_source_receipt_unchanged",False), ("industry_receipt_unchanged",False),
    ("other_methods_input_binding_unchanged",False), ("prior_completed_rr_reexecution",True),
    ("strict_PIT_promotion_eligible",True), ("quote_qualified",True), ("certified_nav",True),
    ("account_equivalence",True), ("account_attempts",1), ("forecast_fits",1),
    ("test2026_rows_read",1), ("checkpoint_new_fit_units",280),
    ("start_as_of","2024-04-01T20:00:00+00:00"), ("max_quarters",7),
    ("max_additional_units_per_quarter",8), ("qqq_open_lookback_sessions",359),
    ("source_inputs_sha256","0"*64), ("parent_component_support_sha256","0"*64),
    ("checkpoint_ledger_sha256","0"*64), ("correction_spec_sha256","0"*64),
])
def test_correction_guard_rejects_scope_or_pin_before_any_reader(correction_case,monkeypatch,field,value):
    c=correction_case
    changed=dict(c["correction"], **{field:value})
    c["put"]("RR_INPUT_BINDING_CORRECTION_FREEZE.json",changed)
    monkeypatch.setattr(r,"guard_run",lambda *a:(c["run"],{},c["science"],c["freeze"]))
    monkeypatch.setattr(r,"ProjectedReader",lambda *a,**k:pytest.fail("READER_BEFORE_CORRECTION_GUARD"))
    before=(c["run"]/"work/FIT_STATUS.json").read_bytes()
    with pytest.raises(ValueError):
        r.fit(c["run"],component=True)
    assert (c["run"]/"work/FIT_STATUS.json").read_bytes()==before


@pytest.mark.parametrize("field,value", [
    ("research_id","PARENT_IS_NOT_CORRECTION"),
    ("correction_spec_sha256","0"*64)])
def test_actual_registry_receipt_fields_must_bind_independent_spec(correction_case,field,value):
    c=correction_case
    receipt=dict(research_id=r.RR_CORRECTION_ID,
                 correction_spec_sha256=c["correction"]["correction_spec_sha256"])
    receipt[field]=value
    newsha=c["put"]("RR_INPUT_BINDING_CORRECTION_REGISTRATION_RECEIPT.json",receipt)
    c["put"]("RR_INPUT_BINDING_CORRECTION_FREEZE.json",
             dict(c["correction"],registration_receipt_sha256=newsha))
    with pytest.raises(ValueError,match="REGISTRY_SPEC_IDENTITY_MISMATCH"):
        _guard_correction(c)


def test_correction_code_closure_and_six_registered_quarters_cannot_shrink(correction_case):
    c=correction_case
    c["put"]("RR_INPUT_BINDING_CORRECTION_FREEZE.json",
             dict(c["correction"],code_pins=c["correction"]["code_pins"][:-1]))
    with pytest.raises(ValueError,match="EXACT_EFFECTIVE_CODE_CLOSURE"):
        _guard_correction(c)
    c["put"]("RR_INPUT_BINDING_CORRECTION_FREEZE.json",c["correction"])
    changed=c["put"]("RISK_COMPONENT_SUPPORT.json",{"nodes":c["nodes"][:-1]})
    c["freeze"]["risk_component_support_sha256"]=changed
    c["put"]("RISK_COMPONENT_EXECUTION_FREEZE.json",c["freeze"])
    c["put"]("RR_INPUT_BINDING_CORRECTION_FREEZE.json",dict(c["correction"],
        parent_component_support_sha256=changed,
        parent_component_execution_sha256=r.sha(c["run"]/"RISK_COMPONENT_EXECUTION_FREEZE.json")))
    with pytest.raises(ValueError,match="SIX_ORIGINAL_QUARTERS"):
        _guard_correction(c)


def test_r3_amendment_pins_correction_without_relabeling_original_semantics(correction_case):
    c=correction_case
    patch=dict(base_execution_freeze_sha256=r.sha(c["run"]/"RISK_COMPONENT_EXECUTION_FREEZE.json"),
        support_sha256=c["freeze"]["risk_component_support_sha256"],
        source_inputs_sha256=c["freeze"]["source_inputs_sha256"],
        semantic_change=False,no_new_numeric_read_during_patch=True,
        prior_execution_preserved=True,fit_retry_allowed=False,code_pin_changes=[],
        rr_correction_freeze_sha256=r.sha(c["run"]/"RR_INPUT_BINDING_CORRECTION_FREEZE.json"))
    c["put"]("EXECUTION_IMPLEMENTATION_AMENDMENT_R3.json",patch)
    _,lineage=r.execution_code_pins(c["run"],c["freeze"],
        freeze_name="RISK_COMPONENT_EXECUTION_FREEZE.json",support_key="risk_component_support_sha256")
    assert lineage["execution_implementation_amendments"][-1]["status"]=="APPLIED"
    patch["rr_correction_freeze_sha256"]="0"*64
    c["put"]("EXECUTION_IMPLEMENTATION_AMENDMENT_R3.json",patch)
    with pytest.raises(ValueError,match="rr_correction_amendment"):
        _guard_correction(c)


def test_activation_binds_initial_checkpoint_once_and_resume_pins_immutable_receipt(correction_case):
    c=correction_case
    correction=_guard_correction(c)
    ledger=r.DurableFitLedger(c["run"])
    pin=r.activate_rr_correction(c["run"],ledger,correction,c["nodes"])
    assert ledger.status["new_fit_units"]==281
    assert r.sha(c["run"]/"work/FIT_STATUS.json")!=correction["checkpoint_ledger_sha256"]
    ledger.status["new_fit_units"]+=1
    ledger.status["fit_attempts"]+=1
    ledger.checkpoint()
    assert r.activate_rr_correction(c["run"],r.DurableFitLedger(c["run"]),correction,c["nodes"])==pin
    c["put"](pin["path"],dict(research_id="MUTATED"))
    with pytest.raises(ValueError,match="rr_correction_activation"):
        r.activate_rr_correction(c["run"],ledger,correction,c["nodes"])


@pytest.mark.parametrize("mutation,match", [
    ("live_sha","initial_live_checkpoint"),("inflight","ZERO_INFLIGHT"),
    ("first_unexecuted","FIRST_UNEXECUTED")])
def test_initial_activation_requires_checkpoint_zero_inflight_and_first_rr(correction_case,mutation,match):
    c=correction_case
    ledger=r.DurableFitLedger(c["run"])
    correction=_guard_correction(c)
    if mutation=="live_sha":
        ledger.status["status"]="DRIFTED"
        ledger.checkpoint()
    elif mutation=="inflight":
        ledger.status["physical_events"]=[dict(key="X",status="STARTED")]
    else:
        ledger.status["records"]=[dict(risk_node="component:RR@"+r.RR_CORRECTION_ASOFS[0],status="BLOCKED")]
    with pytest.raises(ValueError,match=match):
        r.activate_rr_correction(c["run"],ledger,correction,c["nodes"])
    assert not (c["run"]/"RR_INPUT_BINDING_CORRECTION_ACTIVATION_RECEIPT.json").exists()


def test_corrected_interruption_is_component_scope_not_full_scope(correction_case):
    c=correction_case
    status={"records":[dict(risk_node="corrected_rr:RR@"+r.RR_CORRECTION_ASOFS[0],status="FIT_FAILURE")]}
    r.validate_risk_recovery(c["run"],status,component=False)
    with pytest.raises(ValueError,match="EXPLICIT_REPAIR"):
        r.validate_risk_recovery(c["run"],status,component=True)


def test_correction_preflight_caps_seven_without_fit_refund_or_mean_refit(correction_case):
    c=correction_case
    ledger=r.DurableFitLedger(c["run"])
    budget=r._bind_rr_budget_guard(StateBudget(limit=1024,reserve_callback=ledger.reserve),ledger)
    scope=dict(risk_node="corrected_rr:RR@"+r.RR_CORRECTION_ASOFS[0],
               freeze_sha256="c"*64,start_new_fit_units=281)
    ledger.active_rr_correction=scope
    context=dict(synthetic=True,mechanism=False)
    for i in range(7):
        event=budget.reserve("K"+str(i),"covariance","GENERATED_SUBFIT",context,"a"*64,{})
        event["status"]="SUCCEEDED"
    assert budget.learned_total==7 and ledger.status["new_fit_units"]==288
    with pytest.raises(ValueError,match="QUARTER_CAP_EXCEEDED_NO_REFUND"):
        budget.reserve("K8","covariance","UNAUTHORIZED_EIGHTH",context,"a"*64,{})
    assert budget.learned_total==7 and len(ledger.status["physical_events"])==7
    assert all(e["corrected_rr_node"]==scope["risk_node"] for e in ledger.status["physical_events"])
    ledger.active_rr_correction=dict(scope,start_new_fit_units=288)
    for name in ("stock_preprocessing","stock_observed_mean"):
        with pytest.raises(ValueError,match="GLOBAL_STOCK_PREPROCESSING_MUST_REUSE"):
            budget.reserve("FORBIDDEN:"+name,"scaler",name,context,"a"*64,{})
    assert budget.learned_total==7 and ledger.status["fit_attempts"]==1256


def _generated_rr_assembly(case, cutoff):
    """Fabricated mechanism-mode input exercises the real shared engine, no reader."""
    days=case["days"]
    closes=pd.DatetimeIndex([r._clock(d) for d in days])
    cutoff=pd.Timestamp(cutoff)
    position=closes.get_loc(cutoff)
    epoch="EPOCH"
    receipt=r.SourceReceipt("GENERATED_STOCK","V1","a"*64,closes[0],
        synthetic=False,mechanism=True,identity_epoch=epoch,
        status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",
        scientific_contract_identity="GENERATED_PARENT",
        scientific_contract_sha256=case["science"]["scientific_contract_sha256"],
        actual_snapshot_timestamp=pd.Timestamp("2026-10-03T00:00Z"),observation_time_assumed=True)
    qreceipt=replace(receipt,source_identity="GENERATED_QQQ",source_sha256="b"*64,
        identity_epoch="QQQ_EPOCH",return_coordinate=r.BENCHMARK_PROXY_COORDINATE,benchmark_proxy_allowed=True)
    assets=("A","B","C")
    uids={a:"UID:"+a for a in assets}
    origins=range(position-410,position-6)
    labels=pd.DataFrame([dict(ticker=a,signal_date=days[i],security_id=uids[a],
        execution_date=days[i+1],label_end_date=days[i+6],label_mature_date=days[i+6],
        label_coordinate=STORED_LABEL_COORDINATE,label_available=True,
        label_unsupported_common_event=False,endpoint_pair_available=True,
        y_open5=.01*np.sin(i*.13+j)+.003*np.cos(i*.073*(j+1)))
        for j,a in enumerate(assets) for i in origins])
    history=pd.DataFrame([dict(ticker=a,signal_date=d,security_id=uids[a],available_at=r._clock(d))
        for a in assets for d in days[:position+1]])
    rng=np.random.default_rng(20241003)
    market=100*np.exp(np.cumsum(rng.normal(0,.008,360)))
    qqq=pd.DataFrame(dict(ticker="QQQ",trade_date=days[position-360:position],open=market))
    return r.assemble_risk_inputs(labels,days,assets=assets,asset_uids=uids,
        identity_epoch=epoch,source_receipt=receipt,cutoff=cutoff,
        identity_history=history,qqq_opens=qqq,qqq_receipt=qreceipt)


def _install_generated_fit(case,monkeypatch,*,active_asof=None,helper_error=False):
    nodes=case["nodes"]
    if active_asof is not None and active_asof!=r.RR_CORRECTION_ASOFS[0]:
        nodes=[n for n in nodes if n["method"]=="RR"]
        for n in nodes:
            n["numeric_check_eligible"]=n["as_of"]==active_asof
            n["metadata_block_reasons"]=[] if n["numeric_check_eligible"] else ["GENERATED_OTHER_QUARTER"]
        active=next(n for n in nodes if n["as_of"]==active_asof)
        nodes += [dict(active,method="RD"),dict(active,method="RB")]
        nodes.sort(key=lambda n:(n["as_of"],r.METHODS.index(n["method"])))
        newsha=case["put"]("RISK_COMPONENT_SUPPORT.json",{"nodes":nodes})
        case["freeze"]["risk_component_support_sha256"]=newsha
        exsha=case["put"]("RISK_COMPONENT_EXECUTION_FREEZE.json",case["freeze"])
        case["correction"].update(parent_component_support_sha256=newsha,parent_component_execution_sha256=exsha)
        case["put"]("RR_INPUT_BINDING_CORRECTION_FREEZE.json",case["correction"])
        case["nodes"]=nodes
    monkeypatch.setattr(r,"guard_run",lambda *a:(case["run"],{},case["science"],case["freeze"]))
    monkeypatch.setattr(r,"schedule",lambda days:case["nodes"])
    class Reader:
        def __init__(self,*a,**k): self.audit=[]
        def read(self,name,columns,**kwargs):
            assert name=="calendar" and columns==("trade_date",)
            self.audit.append({"columns":list(columns),"generated":True})
            return pd.DataFrame({"trade_date":case["days"]})
    monkeypatch.setattr(r,"ProjectedReader",Reader)
    def loader(reader,source,science,days,cutoff,**kwargs):
        assembly=_generated_rr_assembly(case,cutoff)
        node=kwargs["expected"]
        pool={k:node[k] for k in ("assets","asset_uids","asset_epochs")}
        return pool,assembly,assembly.support_declarations
    monkeypatch.setattr(r,"load_component_period",loader)
    calls=[]
    original=r.SharedRiskEngine.fit
    def fit(engine,method,inputs,**kwargs):
        calls.append((method,inputs))
        return original(engine,method,inputs,**kwargs)
    monkeypatch.setattr(r.SharedRiskEngine,"fit",fit)
    if helper_error:
        monkeypatch.setattr(r,"correct_rr_qqq_source_range",lambda *a,**k:
            (_ for _ in ()).throw(ValueError("GENERATED_RANGE_METADATA_MISMATCH")))
    return calls


@pytest.mark.parametrize("asof",r.RR_CORRECTION_ASOFS[:2])
def test_remaining_quarter_corrected_rr_shares_stock_mean_and_separate_identity(correction_case,monkeypatch,asof):
    c=correction_case
    calls=_install_generated_fit(c,monkeypatch,active_asof=asof)
    r.fit(c["run"],component=True)
    ledger=r.read_json(c["run"]/"work/FIT_STATUS.json")
    audit=r.read_json(c["run"]/"derived/RISK_COMPONENT_STAGE_AUDIT.json")
    assert [m for m,_ in calls]==["RD","RB","RR"]
    corrected=next(x for x in audit["corrected_rr_nodes"] if x["as_of"]==asof)
    assert corrected["status"]=="PASS_FROZEN_HISTORY_MECHANISM",corrected.get("notes")
    assert corrected["learned_states"]<=7
    state=__import__("joblib").load(corrected["artifact"])  # Generated artifact only.
    assert state.risk_state_id!=state.notes["parent_engine_state_id"]
    assert state.notes["correction_envelope"]["research_id"]==r.RR_CORRECTION_ID
    assert state.source_receipt["scientific_contract_identity"]=="GENERATED_PARENT"
    assert state.notes["dependent_source_receipts"]["QQQ"]["scientific_contract_identity"]=="GENERATED_PARENT"
    assert calls[-1][1].observations is calls[0][1].observations
    assert calls[-1][1].source_receipt is calls[0][1].source_receipt
    assert calls[-1][1].qqq_receipt is calls[0][1].qqq_receipt
    assert len(calls[-1][1].qqq_observations)==714
    assert all(x["status"]=="CORRECTION_NOT_EXECUTED" and x["learned_states"]==0
               for x in audit["nodes"] if x["method"]=="RR")
    assert len(audit["corrected_rr_nodes"])==6 and len(audit["nodes"])==8
    new_events=[e for e in ledger["physical_events"] if e.get("corrected_rr_node")]
    assert not any(e["name"] in {"stock_preprocessing","stock_observed_mean"} for e in new_events)
    assert audit["rr_correction"]["learned_fit_units"]==sum(e["learned_states"] for e in new_events)<=7
    assert ledger["new_fit_units"]==281+sum(e["learned_states"] for e in ledger["physical_events"])
    before=ledger["new_fit_units"]
    r.fit(c["run"],component=True)
    assert len(calls)==3 and r.read_json(c["run"]/"work/FIT_STATUS.json")["new_fit_units"]==before


def test_helper_metadata_error_is_only_corrected_zero_fit_block_and_stage_continues(correction_case,monkeypatch):
    c=correction_case
    calls=_install_generated_fit(c,monkeypatch,helper_error=True)
    result=r.fit(c["run"],component=True)
    audit=r.read_json(c["run"]/"derived/RISK_COMPONENT_STAGE_AUDIT.json")
    assert [m for m,_ in calls]==["RD","RB"]
    first=audit["corrected_rr_nodes"][0]
    assert first["status"]=="BLOCKED_INPUT_SOURCE_RANGE" and first["learned_states"]==0
    assert first["block_reasons"]==["GENERATED_RANGE_METADATA_MISMATCH"]
    assert audit["rr_correction"]["learned_fit_units"]==0
    assert result["status"]=="FROZEN_HISTORY_RISK_COMPONENT_STAGE_COMPLETE"
    assert all(x["status"]=="CORRECTION_NOT_EXECUTED" for x in audit["nodes"] if x["method"]=="RR")


def test_retained_corrected_envelope_or_original_rr_promotion_rejected(correction_case):
    c=correction_case
    correction=_guard_correction(c)
    ledger=r.DurableFitLedger(c["run"])
    r.activate_rr_correction(c["run"],ledger,correction,c["nodes"])
    node=next(n for n in c["nodes"] if n["method"]=="RR")
    row=dict(risk_node="corrected_rr:RR@"+node["as_of"],as_of=node["as_of"],learned_states=0,
             correction_envelope=r.rr_correction_envelope(correction,node),status="BLOCKED_METADATA")
    ledger.status["records"].append(row)
    r.activate_rr_correction(c["run"],ledger,correction,c["nodes"])
    row["correction_envelope"]["source_inputs_sha256"]="0"*64
    with pytest.raises(ValueError,match="RETAINED_NODE_ENVELOPE_CHANGED"):
        r.activate_rr_correction(c["run"],ledger,correction,c["nodes"])
    row["correction_envelope"]=r.rr_correction_envelope(correction,node)
    ledger.status["records"].append(dict(risk_node="component:RR@"+node["as_of"],status="PASS",learned_states=0))
    with pytest.raises(ValueError,match="ORIGINAL_RECORD_CANNOT_BE_RECOMPUTED"):
        r.activate_rr_correction(c["run"],ledger,correction,c["nodes"])


def test_complete_schedule_preserves_core_annual_and_old_schedule():
    days=pd.bdate_range("2021-01-01","2025-12-31")
    original=r.schedule(days)
    nodes=r.complete_schedule(days)
    assert len(original)==171 and len(nodes)==99
    assert sum(n["method"]=="R0" for n in nodes)==3
    assert sum(n["method"]=="RM" for n in nodes)==12
    assert sum(n["method"] in {"RD","RB","RH","RT","RR","RU","RE"} for n in nodes)==84
    assert all(pd.Timestamp(n["as_of"]).tz_convert("America/New_York").month==1
               for n in nodes if n["method"]=="R0")
    assert all(pd.Timestamp(n["as_of"]).tz_convert("America/New_York").month in (1,4,7,10)
               for n in nodes if n["method"]!="R0")
    assert r.schedule(days)==original


def _complete_generated_case(g, *, gap=True):
    source=g["source"]
    # Add an independently supported third asset; B has exactly one metadata gap.
    for name,datecols in (
        ("prediction_features",["signal_date"]),("raw_open_close",["trade_date"]),
        ("shareholder_y5",["signal_date"]),
        ("extended_shareholder_y5",["signal_date","execution_date","label_end_date","label_mature_date"])):
        frame=pq.read_table(source["sources"][name]["path"]).to_pandas()
        extra=frame.loc[frame.ticker.eq("A")].copy()
        extra["ticker"]="E"
        if "security_id" in extra:extra["security_id"]="UID:E"
        frame=pd.concat([frame,extra],ignore_index=True)
        if name=="extended_shareholder_y5":
            frame.loc[frame.ticker.eq("B") & frame.signal_date.eq(pd.Timestamp("2023-01-03")),
                      "label_available"]=not gap
        source["sources"][name]=pin_frame(g["paths"].results_root,
            "complete_"+name+("_gap" if gap else "_equal"),frame,datecols)
    ff=pq.read_table(source["sources"]["ff48_surface"]["path"]).to_pandas()
    extra=ff.loc[ff.ticker_at_date.eq("A")].copy()
    extra["ticker_at_date"]="E"
    extra["canonical_security_id"]="UID:E"
    ff=pd.concat([ff,extra],ignore_index=True)
    source["sources"]["ff48_surface"]=pin_frame(g["paths"].results_root,
        "complete_ff"+("_gap" if gap else "_equal"),ff,["decision_date"])
    science=dict(g["science"],scientific_contract_identity="GENERATED_PRIOR_COMPONENT",
                 scientific_contract_sha256="c"*64)
    cutoff=r._clock("2023-01-31")
    partial,_,declaration=r.load_component_period(r.ProjectedReader(source,phase="support"),
        source,science,g["days"],cutoff,numeric=False)
    prior=dict(cutoff=cutoff.isoformat(),method="RD",
        **{k:r._json(partial[k]) for k in
           ("assets","asset_uids","asset_epochs","segment_starts","parent_origin_window")},
        declarations=declaration)
    science.update(scientific_contract_identity=r.COMPLETE_ID,scientific_contract_sha256="d"*64,
        parent_component_support_sha256="e"*64,parent_component_support_nodes=[prior])
    return source,science,cutoff,partial


def test_complete_window_first_exact252_only_metadata_no_outcomes(component_case):
    g=component_case
    source,science,cutoff,partial=_complete_generated_case(g)
    reader=r.ProjectedReader(source,phase="support")
    pool,assembly,declaration=r.load_component_period(reader,source,science,g["days"],
        cutoff,numeric=False,complete=True)
    assert partial["assets"]==("A","B","E") and pool["assets"]==("A","E")
    assert pool["parent_origin_window"]==partial["parent_origin_window"]
    assert len(pool["parent_origin_window"])==252 and assembly is not None
    assert declaration["component_supported_h5_by_asset"]["B"]==251
    assert declaration["component_supported_h5_by_asset"]["A"]==252
    assert all(not r.FORBIDDEN.intersection(p["columns"]) for p in reader.audit)
    proof=pool["domain_comparison"]
    assert proof["relation"]=="STRICT_SUBSET"
    assert proof["counts_sha256"]==r.content_hash(proof["prior_partial_domain"]["supported_h5_by_asset"])
    assert proof["complete_domain_sha256"]==r.content_hash(proof["complete_domain"])
    assert proof["prior_partial_domain_sha256"]==r.content_hash(proof["prior_partial_domain"])
    assert proof["complete_domain"]["assets"]==["A","E"]
    assert all(proof["complete_domain"]["supported_h5_by_asset"][a]==252 for a in pool["assets"])
    assert assembly.risk_input.source_receipt.scientific_contract_identity==r.COMPLETE_ID
    # The existing min30 path has identical metadata output after complete support.
    again,_,_=r.load_component_period(r.ProjectedReader(source,phase="support"),
        source,science,g["days"],cutoff,numeric=False)
    assert again["assets"]==partial["assets"] and "domain_comparison" not in again


def test_complete_numeric_gap_blocks_whole_selected_domain_and_never_reads_excluded_values(component_case):
    g=component_case
    source,science,cutoff,_=_complete_generated_case(g)
    pool,_,_=r.load_component_period(r.ProjectedReader(source,phase="support"),
        source,science,g["days"],cutoff,numeric=False,complete=True)
    expected={k:r._json(pool[k]) for k in
              ("assets","asset_uids","asset_epochs","parent_origin_window","domain_comparison")}
    reader=r.ProjectedReader(source,phase="fit")
    checked,assembly,declaration=r.load_component_period(reader,source,science,g["days"],
        cutoff,numeric=True,expected=expected,complete=True)
    assert checked["assets"]==("A","E") and assembly is None
    assert declaration["reason"]=="BLOCK_COMPONENT_NUMERIC_FINITE_SUPPORT_CHANGED"
    numeric=[p for p in reader.audit if "y_open5" in p["columns"]]
    assert len(numeric)==1 and numeric[0]["exact_tickers"]==["A","E"]
    assert not any("open" in p["columns"] for p in reader.audit)
    changed=dict(expected,domain_comparison={**expected["domain_comparison"],"complete_domain_sha256":"0"*64})
    reader=r.ProjectedReader(source,phase="fit")
    with pytest.raises(ValueError,match="DOMAIN_PROOF_CHANGED"):
        r.load_component_period(reader,source,science,g["days"],cutoff,
            numeric=True,expected=changed,complete=True)
    assert not any("y_open5" in p["columns"] for p in reader.audit)


def test_complete_equal_partial_domain_requires_exact_prior_reuse_not_new_science_id(component_case,monkeypatch):
    g=component_case
    source,science,cutoff,_=_complete_generated_case(g,gap=False)
    monkeypatch.setattr(r.SharedRiskEngine,"fit",lambda *a,**k:pytest.fail("DUPLICATE_FIT_FORBIDDEN"))
    reader=r.ProjectedReader(source,phase="support")
    pool,assembly,declaration=r.load_component_period(reader,source,science,g["days"],
        cutoff,numeric=False,complete=True)
    assert pool["assets"]==("A","B","E") and assembly is None
    assert pool["domain_comparison"]["relation"]=="REUSE_REQUIRED"
    assert declaration["reason"]=="REUSE_REQUIRED_EXACT_PRIOR_SCIENTIFIC_STATE_NOT_NEW_FIT"
    assert all(not r.FORBIDDEN.intersection(p["columns"]) for p in reader.audit)


def test_complete_prior_partial_metadata_pin_must_match_before_numeric(component_case):
    g=component_case
    source,science,cutoff,_=_complete_generated_case(g)
    science["parent_component_support_nodes"][0]["assets"]=["A"]
    reader=r.ProjectedReader(source,phase="fit")
    with pytest.raises(ValueError,match="PRIOR_PARTIAL_DOMAIN_CHANGED"):
        r.load_component_period(reader,source,science,g["days"],cutoff,
            numeric=True,expected={},complete=True)
    assert not any("y_open5" in p["columns"] for p in reader.audit)


@pytest.mark.parametrize("parent_risk,allowed",[(683,True),(684,False)])
def test_complete_activation_waits_for_original_terminal_and_upper341_budget(correction_case,parent_risk,allowed):
    c=correction_case
    status=dict(c["ledger"],status="FROZEN_HISTORY_RISK_COMPONENT_STAGE_COMPLETE",
                new_fit_units=parent_risk,risk_fit_units=parent_risk,fit_attempts=968+parent_risk)
    checkpoint=c["put"]("work/FIT_STATUS.json",status)
    c["put"]("work/complete_common_parent_completion/FIT_STATUS.json",status)
    exe=dict(risk_complete_common_science_sha256="a"*64,risk_complete_common_support_sha256="b"*64,
        checkpoint_ledger_sha256=checkpoint,checkpoint_new_fit_units=parent_risk,
        checkpoint_risk_fit_units=parent_risk)
    c["put"]("RISK_COMPLETE_COMMON_EXECUTION_FREEZE.json",exe)
    ledger=r.DurableFitLedger(c["run"])
    if not allowed:
        with pytest.raises(ValueError,match="UPPER341_MUST_FIT_EXISTING_CAP_BEFORE_NUMERIC"):
            r.activate_complete(c["run"],ledger,exe)
        assert not (c["run"]/"RISK_COMPLETE_COMMON_ACTIVATION_RECEIPT.json").exists()
        return
    pin=r.activate_complete(c["run"],ledger,exe)
    ledger.status["new_fit_units"]+=1
    ledger.status["risk_fit_units"]+=1
    ledger.status["fit_attempts"]+=1
    ledger.checkpoint()
    assert r.activate_complete(c["run"],r.DurableFitLedger(c["run"]),exe)==pin


def test_complete_reservations_group31_stage341_admin_tags_do_not_change_hashed_context(correction_case):
    c=correction_case
    ledger=r.DurableFitLedger(c["run"])
    budget=r._bind_rr_budget_guard(StateBudget(limit=1024,reserve_callback=ledger.reserve),ledger)
    scope=dict(as_of="GENERATED",risk_node="complete:RD@GENERATED",execution_freeze_sha256="c"*64,
               start_new_fit_units=281,stage_start_new_fit_units=281)
    ledger.active_complete_group=scope
    context=dict(synthetic=True,mechanism=False)
    for i in range(31):
        event=budget.reserve("CK"+str(i),"covariance","GENERATED",context,"a"*64,{})
        event["status"]="SUCCEEDED"
    with pytest.raises(ValueError,match="GROUP_CAP_EXCEEDED"):
        budget.reserve("FORBIDDEN32","covariance","GENERATED",context,"a"*64,{})
    assert budget.learned_total==31 and len(ledger.status["physical_events"])==31
    assert all(e["context"]==context and e["complete_common_node"]==scope["risk_node"]
               and e["complete_group_as_of"]=="GENERATED" for e in ledger.status["physical_events"])
    ledger.status.update(new_fit_units=622,risk_fit_units=622,fit_attempts=1590)
    scope["start_new_fit_units"]=622
    with pytest.raises(ValueError,match="STAGE_CAP_EXCEEDED"):
        budget.reserve("FORBIDDEN342","covariance","GENERATED",context,"a"*64,{})
    assert budget.learned_total==31 and len(ledger.status["physical_events"])==31


def test_complete_recovery_and_stage_filters_never_mix_original_identities(correction_case):
    c=correction_case
    status={"records":[dict(risk_node="complete:RU@GENERATED",status="FIT_FAILURE")]}
    r.validate_risk_recovery(c["run"],status,component=False)
    r.validate_risk_recovery(c["run"],status,component=True)
    with pytest.raises(ValueError,match="EXPLICIT_REPAIR"):
        r.validate_risk_recovery(c["run"],status,component=True,complete=True)
    assert r._stage_node("complete:RD@X",component=True,complete=True)
    assert not r._stage_node("component:RD@X",component=True,complete=True)
    assert not r._stage_node("corrected_rr:RR@X",component=True,complete=True)


@pytest.mark.parametrize("size,allowed",[(58533323,True),(128*1024*1024,True),(128*1024*1024+1,False)])
def test_complete_fixed_support_metadata_limit_only(tmp_path,monkeypatch,size,allowed):
    path=tmp_path/"RISK_COMPLETE_COMMON_SUPPORT.json"
    path.write_text('{"generated_metadata":true}',encoding="utf-8")
    old_stat=Path.stat
    def size_stat(self,*args,**kwargs):
        return SimpleNamespace(st_size=size) if self==path else old_stat(self,*args,**kwargs)
    monkeypatch.setattr(Path,"stat",size_stat)
    if allowed:
        assert r.read_json(path)=={"generated_metadata":True}
    else:
        with pytest.raises(ValueError,match="COMPACT_METADATA_LIMIT"):
            r.read_json(path)
