"""Synthetic-only breadth admission and orchestration; no economic data readers."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import stateful_breadth as breadth
from scripts.research.a2.training import stateful_execution as execution
from scripts.research.a2.training import stateful_replay as replay
from scripts.storage import storage_r2a


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": execution.values.sha(path)}


def journal(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def friction():
    return dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE", scenario_id="ADVERSE_OPEN_10BPS_USD3000",
                one_way_bps=10, fee_bps=0, benchmark="NEXT_RAW_OPEN", authority="HYPOTHETICAL_RESEARCH_SCENARIO")


def synthetic_candidates():
    """Fixed family and corner identities; no observed result selects a method."""
    candidates = []
    for model in ("ridge", "huber", "extra", "hgb", "xgb", "xgb_rank", "mlp", "ngboost", "hgb_q"):
        identity = f"A_{model}_aware_s10" if model in ("ridge", "hgb") else f"A_BREADTH_R1_{model}_REF_s10"
        candidates.append(dict(candidate_id=identity, value_model=model, breadth_layer="VALUE_MAIN", breadth_slot="REF"))
    for model in ("equal", "convex", "stack_ridge", "gate_linear"):
        candidates.append(dict(candidate_id=f"A_BREADTH_R1_fusion_{model}_REF_s10", value_model="fusion::" + model,
                               breadth_layer="FUSION_MAIN", breadth_slot="REF"))
    corners = (("xgb_rank", "VOL_OAS", "volatility_targeting", "OAS", "none", "aware"),
               ("ngboost", "DYN_COV", "dynamic", "COV_ENSEMBLE", "none", "aware"),
               ("hgb_q", "BLIND", "fixed", "diag20_reference", "none", "blind"),
               ("fusion::convex", "VOL_OAS", "volatility_targeting", "OAS", "none", "aware"),
               ("fusion::gate_linear", "DYN_COV", "dynamic", "COV_ENSEMBLE", "none", "aware"),
               ("mlp", "PARTIAL", "fixed", "diag20_reference", "partial_rebalancing", "aware"))
    for model, slot, gross, risk, control, cost in corners:
        candidates.append(dict(candidate_id=f"A_BREADTH_R1_{model.replace('::', '_')}_{slot}_s10", value_model=model,
                               breadth_layer="PRESELECTED_INTERACTION", breadth_slot=slot, gross=gross, risk=risk,
                               control=control, action_cost_mode=cost))
    for ordinal, candidate in enumerate(candidates, 1):
        for key, value in dict(action="stateful", action_cost_mode="aware", control="none", gross="fixed",
                               risk="diag20_reference", forecast="none", target_role="shareholder5d").items():
            candidate.setdefault(key, value)
        candidate.update(ordinal=ordinal, execution_friction=friction(), source_method_ids=[f"SYNTHETIC_{ordinal}"])
        candidate["scientific_tuple_sha256"] = hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
    assert len(candidates) == 19
    return candidates


def synthetic_market():
    dates = pd.to_datetime(["2023-12-28", "2023-12-29", "2024-01-02", "2024-12-31", "2025-01-02", "2025-01-03"])
    names = [f"SYNTHETIC_{i:02d}" for i in range(20)]
    top = np.ones((len(dates), 20), dtype=bool)
    prices = np.full(top.shape, 10.)
    market = replay.MarketArrays(dates, names, prices.copy(), prices.copy(), input_present=top.copy(),
        new_buy_eligible=top.copy(), signal_asof=[d.tz_localize("America/New_York") + pd.Timedelta(hours=16) for d in dates])
    candidates = synthetic_candidates()
    packets = {model: dict(mu=np.full(top.shape, .04), sigma=np.full(len(dates), .001),
                           lineage=np.full(len(dates), "SYNTHETIC_ONLY")) for model in {c["value_model"] for c in candidates}}
    account = dict(base_currency="USD", initial_nav=3000., initial_cash=3000., initial_holdings=[],
        fractional_shares=True, integer_share_rounding=False, transaction_cost_bps=0., cash_interest=0.,
        financing=False, borrowed_cash=False, long_only=True, max_weight=1., max_positions=20, max_invested=1., capacity_fraction=None)
    return market, candidates, packets, top, account


def execute_synthetic(market, candidates, packets, top, account):
    def risk_provider(di, selected, tickers, risk):
        assert risk in ("OAS", "COV_ENSEMBLE")
        return np.eye(len(selected)) * .0001
    return replay.execute_market(market, candidates, packets, top, top.copy(), np.full(top.shape, .03), account,
        stock_present=top.copy(), raw_selector_present=top.copy(), execution_friction=friction(), risk_provider=risk_provider)


def test_shared_engine_nineteen_paths_cross_year_cash_cost_and_isolation(monkeypatch):
    market, candidates, packets, top, account = synthetic_market()
    original = replay.run_continuous_account
    calls = []
    def owner(*args, **kwargs):
        calls.append(tuple(args[1]))
        return original(*args, **kwargs)
    monkeypatch.setattr(replay, "run_continuous_account", owner)
    result, frames = execute_synthetic(market, candidates, packets, top, account)
    assert calls == [tuple(c["candidate_id"] for c in candidates)]
    assert frames["daily"].groupby("path_id").size().eq(6).all()
    assert len(frames["daily"]) == 114 and frames["daily"].accounting_qualified.all()
    assert not frames["continuation"].annual_reset.any()
    assert frames["positions"].holding_age.max() >= 4
    assert frames["positions"].entry_date.min() == market.dates[1]
    assert not frames["fills"].execution_date.ge("2026-01-01").any()
    assert frames["costs"].one_way_slippage_bps.eq(10).all()
    assert frames["fills"].transaction_fee.eq(0).all()
    final = frames["daily"].loc[frames["daily"].date.eq(market.dates[-1])].set_index("path_id")
    costs = frames["costs"].groupby("path_id").transaction_cost_amount.sum()
    np.testing.assert_allclose(final.nav + costs.reindex(final.index), 3000., atol=1e-7)
    # A path must have the same own-state ledger when run alone or with 18 peers.
    one = [c for c in candidates if c["breadth_slot"] == "PARTIAL"]
    _, alone = execute_synthetic(market, one, packets, top, account)
    together = frames["daily"].loc[frames["daily"].path_id.eq(one[0]["candidate_id"])].reset_index(drop=True)
    pd.testing.assert_frame_equal(together, alone["daily"].reset_index(drop=True))
    assert calls[-1] == (one[0]["candidate_id"],)


def make_design(parent):
    features = [f"synthetic_feature_{i}" for i in range(32)]
    manifest = write(parent / "input_manifest.json", {"synthetic_only": True})
    config = write(parent / "run_config.json", {"synthetic_only": True, "phase": "FROZEN"})
    candidates = synthetic_candidates()
    source_refs = {
        "scripts/research/a2/training/stateful_values.py": write(parent / "source_stubs/value.py", {"producer": "SYNTHETIC_VALUE"}),
        "scripts/research/a2/training/stateful_fusion.py": write(parent / "source_stubs/fusion.py", {"producer": "SYNTHETIC_FUSION"})}
    specification = dict(research_id=breadth.NAMESPACE, candidates_in_exact_order=candidates,
        fit_policy={"new_fit_hard_limit": 0}, budget={"new_account_attempt_hard_limit": 19},
        breadth_is_not_a_R5_prerequisite=True, account={"capital_usd": 3000, "2026_locked": True})
    design = dict(schema_id="A_BREADTH_FROZEN_DESIGN_R1", specification=specification,
        specification_sha256=execution.values.digest(specification),
        parent_custody={"run_config": config, "input_manifest": manifest},
        implementation_source_pins=source_refs,
        exact_fit_prediction_publication_dependency_refs={}, exact_risk_dependency_refs={})
    for model in dict.fromkeys(c["value_model"] for c in candidates):
        fusion = model.startswith("fusion::")
        short = model.split("::")[-1]
        producer = source_refs["scripts/research/a2/training/stateful_fusion.py" if fusion else "scripts/research/a2/training/stateful_values.py"]["sha256"]
        packet = dict(source_kind="V24_FUSION_OUTPUTS" if fusion else "V24_VALUE_OUTPUTS", annual={})
        for year in (2023, 2024, 2025):
            folder = parent / "models" / short / str(year)
            start = date(year - 1, 9, 1)
            sessions = [(start + timedelta(days=i)).isoformat() + "T00:00:00" for i in range(60)]
            reuse = dict(fold=f"ANNUAL_{year}", label_definition=execution.values.LABEL,
                cutoff_exclusive=f"{year}-01-01", calibration_label_maturity_exclusive=f"{year}-01-01",
                calibration_sessions=sessions, calendar_sha256="f" * 64,
                training_signal_and_label_maturity_exclusive=sessions[0], feature_binding={"features": features},
                source_pins={"module_sha256": producer, "input_manifest_sha256": manifest["sha256"]})
            if fusion:
                experts = ["ridge", "hgb", "lgb"]
                states = ["state_mean_ret20d", "state_mean_realized_vol20d", "state_breadth_price_vs_ma20_positive", "state_expert_disagreement"] if short.startswith("gate_") else []
                reuse.update(feature_binding_role="UNDERLYING_SOURCE32_NOT_FUSION_ESTIMATOR_INPUTS", packet=experts,
                    model_input_columns=["expert_" + e for e in experts] + states,
                    expert_oof_pins=[{"year": y, "model_id": e} for y in range(2021, year) for e in experts])
            model_ref = write(folder / "model.joblib", {"opaque": True})
            prediction = write(folder / "prediction.parquet", {"opaque": True})
            fit = dict(status="TRAINED", model_id=short, year=year, model_sha256=model_ref["sha256"],
                model_path=model_ref["path"], reuse_tuple_sha256=execution.values.digest(reuse), reuse_tuple=reuse,
                scientific_target_qualified=True, scientific_feature_pit_qualified=True,
                train_label_maturity_max=f"{year-1}-08-31", calibration_label_maturity_max=f"{year-1}-12-29")
            receipt = write(folder / "fit_receipt.json", fit)
            publication = write(folder / "prediction.receipt.json", dict(status="PUBLISHED", prediction_role="MODEL_OOF",
                model_id=short, year=year, producer_source_sha256=producer, input_manifest_sha256=manifest["sha256"],
                fit_receipt_sha256=receipt["sha256"], fit_receipt_path=receipt["path"], model_sha256=fit["model_sha256"],
                reuse_tuple_sha256=fit["reuse_tuple_sha256"], sha256=prediction["sha256"], path=prediction["path"], test_2026_rows_read=0))
            packet["annual"][str(year)] = dict(refs={"receipt": receipt, "prediction": prediction,
                "prediction_receipt": publication, "model": model_ref}, fit_identity=deepcopy(fit))
        design["exact_fit_prediction_publication_dependency_refs"][model] = packet
    for method in ("OAS", "COV_ENSEMBLE"):
        packet = dict(annual={})
        for year in (2023, 2024, 2025):
            folder = parent / "risk" / method / str(year)
            bundle = write(folder / "risk.joblib", {"opaque": True})
            receipt = dict(status="FITTED", year=year, method_id=method, model_sha256=bundle["sha256"],
                scientific_feature_pit_qualified=True, scientific_return_proxy_qualified=True,
                reuse_tuple_sha256="e" * 64)
            packet["annual"][str(year)] = dict(refs={"receipt": write(folder / "fit_receipt.json", receipt), "bundle": bundle},
                                             receipt_metadata=deepcopy(receipt))
        design["exact_risk_dependency_refs"][method] = packet
    return design, features


@pytest.fixture
def metadata(tmp_path, monkeypatch):
    parent = tmp_path / "bank"
    design, features = make_design(parent)
    monkeypatch.setattr(execution.values, "feature_binding", lambda: {"features": features})
    original = execution.values.sha
    def opaque_guard(path):
        assert Path(path).suffix not in (".parquet", ".joblib"), "opaque prediction/model was opened or hashed"
        return original(path)
    monkeypatch.setattr(execution.values, "sha", opaque_guard)
    return design


def mutate_fit(design, key, change):
    entry = design["exact_fit_prediction_publication_dependency_refs"][key]["annual"]["2023"]
    fit = json.loads(Path(entry["refs"]["receipt"]["path"]).read_text())
    change(fit)
    fit["reuse_tuple_sha256"] = execution.values.digest(fit["reuse_tuple"])
    entry["fit_identity"] = deepcopy(fit)
    entry["refs"]["receipt"] = write(Path(entry["refs"]["receipt"]["path"]), fit)
    publication = Path(entry["refs"]["prediction_receipt"]["path"])
    pub = json.loads(publication.read_text())
    pub["fit_receipt_sha256"] = entry["refs"]["receipt"]["sha256"]
    pub["reuse_tuple_sha256"] = fit["reuse_tuple_sha256"]
    entry["refs"]["prediction_receipt"] = write(publication, pub)


def test_dependency_metadata_admits_thirteen_packets_without_binary_read(metadata):
    result = breadth.validate_dependencies(metadata)
    assert result == dict(status="PASS_PRODUCER_METADATA_ONLY", value_years=27, fusion_years=12, risk_years=6,
                          model_parquet_read_or_hash=False, new_fit=0)
    value, risk = breadth.packet_specs(metadata)
    assert len(value) == 13 and set(risk) == {"OAS", "COV_ENSEMBLE"}
    assert value["fusion::equal"]["source_kind"] == "V24_FUSION_OUTPUTS"


@pytest.mark.parametrize("kind", ["producer", "type", "target", "maturity", "future_expert", "feature_role"])
def test_typed_dependency_guards_reject_semantic_bypasses(metadata, kind):
    if kind == "type":
        metadata["exact_fit_prediction_publication_dependency_refs"]["fusion::equal"]["source_kind"] = "V24_VALUE_OUTPUTS"
    elif kind == "producer":
        mutate_fit(metadata, "fusion::equal", lambda fit: fit["reuse_tuple"]["source_pins"].update(module_sha256="a" * 64))
    elif kind == "target":
        mutate_fit(metadata, "ridge", lambda fit: fit.update(scientific_target_qualified=1))
    elif kind == "maturity":
        mutate_fit(metadata, "ridge", lambda fit: fit.update(train_label_maturity_max="2022-09-01T00:00:00"))
    elif kind == "future_expert":
        mutate_fit(metadata, "fusion::equal", lambda fit: fit["reuse_tuple"]["expert_oof_pins"][0].update(year=2023))
    else:
        mutate_fit(metadata, "fusion::gate_linear", lambda fit: fit["reuse_tuple"].update(feature_binding_role="FUSION_ESTIMATOR_SOURCE32"))
    with pytest.raises(breadth.Blocked):
        breadth.validate_dependencies(metadata)


def parent_candidates_and_history():
    candidates = [dict(candidate_id="RAW_s10" if i == 0 else f"SYNTHETIC_FROZEN37_{i}", scientific_tuple_sha256=f"{i:064x}") for i in range(38)]
    history = []
    for i, c in enumerate(candidates):
        history.extend([dict(c, event="ACCOUNT_PATH_ATTEMPT_STARTED"),
                        dict(c, event="ACCOUNT_PATH_FAILED" if i == 12 else "ACCOUNT_PATH_COMPLETE")])
    return candidates, history


def literal_gate():
    return {"groups": dict.fromkeys(breadth.GATES, True), "all_passed": True, "eligible_for_selection": True}


def test_handoff_requires_38_terminals_but_not_37_economic_successes():
    candidates, history = parent_candidates_and_history()
    assert breadth.validate_handoff_state({"status": "COMPLETED"}, literal_gate(), candidates, history)
    with pytest.raises(breadth.Blocked, match="EXACT38"):
        breadth.validate_handoff_state({"status": "COMPLETED"}, literal_gate(), candidates, history[:-1])
    with pytest.raises(breadth.Blocked, match="NOT_COMPLETE"):
        breadth.validate_handoff_state({"status": "RUNNING"}, literal_gate(), candidates, history)


@pytest.mark.parametrize("gate_name", breadth.GATES)
@pytest.mark.parametrize("bad", [False, None, "missing", 1, "true"])
def test_literal_gate_never_promotes_combined_eligible(gate_name, bad):
    candidates, history = parent_candidates_and_history()
    gate = literal_gate()
    if bad == "missing":
        del gate["groups"][gate_name]
    else:
        gate["groups"][gate_name] = bad
    with pytest.raises(breadth.Blocked, match="LITERAL_TRUE"):
        breadth.validate_handoff_state({"status": "COMPLETED"}, gate, candidates, history)


def breadth_event(candidate, event):
    return dict(candidate_id=candidate["candidate_id"], scientific_tuple_sha256=candidate["scientific_tuple_sha256"], event=event)


def test_failed_budget_counts_and_completion_requires_all_nineteen_slots():
    candidates = synthetic_candidates()
    history = []
    for i, c in enumerate(candidates):
        history += [breadth_event(c, "ACCOUNT_PATH_ATTEMPT_STARTED"),
                    breadth_event(c, "ACCOUNT_PATH_FAILED" if i == 4 else "ACCOUNT_PATH_COMPLETE")]
    result = breadth.completion(candidates, history)
    assert result["finite_execution_complete"] and result["budget"]["new_account_attempts"] == 19
    assert result["budget"]["failed_attempts"] == 1 and result["budget"]["new_fit"] == 0
    assert not result["winner_selected"] and result["status"] == "PENDING_UNIFIED_ECONOMIC_EVALUATION"
    assert not breadth.completion(candidates, history[:-1])["finite_execution_complete"]
    skipped = breadth.completion(candidates, [], baseline_passed=False)
    assert skipped["status"] == "NOT_TESTABLE" and set(skipped["candidate_states"].values()) == {"NOT_EXECUTED_REQUIRED_BASELINE_UNQUALIFIED"}


@pytest.mark.parametrize("mutation", ["duplicate", "reorder", "substitution", "unstarted", "fit"])
def test_attempt_journal_rejects_retries_order_identity_and_fit(mutation):
    candidates = synthetic_candidates()
    first = candidates[0]
    history = [breadth_event(first, "ACCOUNT_PATH_ATTEMPT_STARTED"), breadth_event(first, "ACCOUNT_PATH_FAILED")]
    if mutation == "duplicate":
        history += history
    elif mutation == "reorder":
        history = [breadth_event(candidates[1], "ACCOUNT_PATH_ATTEMPT_STARTED")]
    elif mutation == "substitution":
        history[0]["scientific_tuple_sha256"] = "f" * 64
    elif mutation == "unstarted":
        history = [breadth_event(first, "ACCOUNT_PATH_COMPLETE")]
    else:
        history += [dict(event="FIT_STARTED", fit_units=1)]
    with pytest.raises(breadth.Blocked):
        breadth.attempt_budget(candidates, history)


def test_exact_reuse_requires_same_account_friction_tuple_and_all_gates():
    candidate = synthetic_candidates()[0]
    evidence = dict(candidate_id=candidate["candidate_id"], scientific_tuple_sha256=candidate["scientific_tuple_sha256"],
        source_account_fingerprint="SOURCE_SYNTHETIC", execution_friction=friction(), candidate=deepcopy(candidate),
        groups=dict.fromkeys(breadth.GATES, True))
    assert breadth.exact_reuse_qualified(evidence, candidate, "SOURCE_SYNTHETIC")
    for key in ("source_account_fingerprint", "scientific_tuple_sha256", "execution_friction"):
        changed = deepcopy(evidence); changed[key] = None
        assert not breadth.exact_reuse_qualified(changed, candidate, "SOURCE_SYNTHETIC")
    evidence["groups"]["terminal"] = 1
    assert not breadth.exact_reuse_qualified(evidence, candidate, "SOURCE_SYNTHETIC")
    history = [breadth_event(candidate, "ACCOUNT_EXACT_REUSED")]
    budget = breadth.attempt_budget(synthetic_candidates(), history)
    assert budget["new_account_attempts"] == 0 and budget["exact_reused"] == 1
    with pytest.raises(breadth.Blocked):
        breadth.attempt_budget(synthetic_candidates(), history + [breadth_event(candidate, "ACCOUNT_PATH_ATTEMPT_STARTED")])


@pytest.fixture
def stage(tmp_path, monkeypatch, metadata):
    """Synthetic stage semantics; physical frozen custody is checked separately below."""
    # The fixture already substitutes owner, source gates and registry admission.
    # A newer engineering descendant must not silently rebind the strict pins.
    monkeypatch.setattr(breadth, "protected_custody", lambda: dict(breadth.PROTECTED))
    design = metadata
    design_path = tmp_path / "design.json"
    write(design_path, design)
    monkeypatch.setattr(breadth, "DESIGN_SHA", execution.values.sha(design_path))
    paths = SimpleNamespace(backtest_root=tmp_path, results_root=tmp_path / "reports")
    monkeypatch.setattr(execution.values, "resolve", lambda *args, **kw: paths)
    monkeypatch.setattr(storage_r2a, "BACKTEST_ROOT", tmp_path)
    def guard(path, *args, **kw):
        assert Path(path).resolve().is_relative_to(tmp_path.resolve())
    monkeypatch.setattr(breadth, "assert_write_path", guard)
    monkeypatch.setattr(execution, "assert_write_path", guard)
    monkeypatch.setattr(replay, "assert_write_path", guard)
    parent = tmp_path / "R5"
    write(parent / "run_config.json", {"phase": "FROZEN", "synthetic_only": True})
    write(parent / "EXECUTION_STATUS.json", {"status": "COMPLETED", "synthetic_only": True})
    candidates, history = parent_candidates_and_history()
    for event in history:
        event.update(namespace=execution.R5_NAMESPACE, continuation=True,
                     module_sha256=breadth.PROTECTED["scripts/research/a2/training/stateful_replay.py"],
                     controller_module_sha256=breadth.PROTECTED["scripts/research/a2/training/stateful_execution.py"])
    journal(parent / "ACCOUNT_PATH_LOG.jsonl", history)
    journal(parent / "FIT_LOG.jsonl", [])
    slots = {name: dict(approved=True, source_qualified=True,
                       ref=write(parent / "source_refs" / (name + ".json"), {"synthetic_only": True, "role": name}))
             for name in execution.R5_SOURCE_SLOTS}
    control = object.__new__(execution.Controller)
    control.run = parent.resolve()
    control.config = {"parent_run_dir": str(tmp_path / "bank")}
    control.auth = dict(namespace=execution.R5_NAMESPACE,
        module_sha256=breadth.PROTECTED["scripts/research/a2/training/stateful_execution.py"],
        source_pins={"replay_module_sha256": breadth.PROTECTED["scripts/research/a2/training/stateful_replay.py"]}, source_account_binding={"synthetic_only": True},
        parent_input_manifest_sha256=design["parent_custody"]["input_manifest"]["sha256"],
        source_decision=dict(branch_id="S", adopted=True, approved=True, source_qualified=True,
                             qualification_claim="STRICT_HISTORICAL_PIT", slots=slots))
    control.candidates = candidates
    control.state = {"status": "COMPLETED"}
    guard_calls = []
    control.guard = lambda: guard_calls.append(True)
    monkeypatch.setattr(execution, "r5_baseline_gate", lambda *args: literal_gate())
    authority = dict(approved=True, namespace=breadth.NAMESPACE, synthetic_only=True)
    identity = breadth.identity_template(design)
    identity.update(status="FROZEN_BOUND_EXECUTION_IDENTITY", source_activated=True, execution_authority=authority,
        parent_R5_run=str(control.run), parent_R5_source_account_fingerprint=breadth.source_fingerprint(control),
        source_slots=slots)
    run = tmp_path / "BREADTH"
    write(run / "run_config.json", {"breadth_identity": identity, "synthetic_only": True})
    admission = dict(entity_id=breadth.NAMESPACE, status="OPEN", metadata_only_admission=True, source_authority_granted=False)
    # Canonical registry admission has separate reviewed tests; this seam proves runtime ownership.
    monkeypatch.setattr(breadth, "_canonical_admission", lambda design, declaration: admission)
    monkeypatch.setattr(breadth, "_parent_reuse", lambda *args: None)
    return dict(control=control, run=run, identity=identity, design_path=design_path,
                admission=admission, authority=authority, design=design, guard_calls=guard_calls)


def call_stage(stage, authority=True):
    return breadth.run_stage(stage["control"], stage["run"], stage["identity"], stage["design_path"], stage["admission"],
                             execution_authority=stage["authority"] if authority else None)


def test_inactive_templates_and_unbound_sources_never_create_account_attempts(stage):
    with pytest.raises(breadth.Blocked, match="NOT_AUTHORIZED"):
        call_stage(stage, authority=False)
    inactive = deepcopy(stage["identity"]); inactive.update(status="INACTIVE_TEMPLATE", source_activated=False)
    with pytest.raises(breadth.Blocked, match="INACTIVE_TEMPLATE"):
        breadth.run_stage(stage["control"], stage["run"], inactive, stage["design_path"], stage["admission"], execution_authority=stage["authority"])
    stage["control"].auth["source_decision"]["slots"]["MKFG_settlement_authority"].update(approved=False, source_qualified=False, ref=None)
    with pytest.raises(breadth.Blocked, match="SOURCE_SLOT_UNKNOWN"):
        call_stage(stage)
    assert not (stage["run"] / "ACCOUNT_PATH_LOG.jsonl").exists()
    assert not (stage["run"] / "ledgers").exists()


def test_sole_controller_stage_preserves_parent_and_attempt_failure_resume(stage, monkeypatch):
    control, run = stage["control"], stage["run"]
    before = {name: execution.values.sha(control.run / name) for name in ("run_config.json", "FIT_LOG.jsonl", "ACCOUNT_PATH_LOG.jsonl", "EXECUTION_STATUS.json")}
    calls = []
    def worker(candidate, owner, design, folder):
        assert owner is control and (control.run / "CONTINUATION_LOCK.json").is_file()
        assert folder.resolve().is_relative_to(run.resolve()) and not folder.resolve().is_relative_to(control.run)
        calls.append(deepcopy(candidate))
        if candidate["ordinal"] == 5:
            raise ValueError("SYNTHETIC_KNOWN_ENGINEERING_FAILURE")
        return dict(status="ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE", synthetic_only=True,
            candidate_id=candidate["candidate_id"], scientific_tuple_sha256=candidate["scientific_tuple_sha256"],
            source_account_fingerprint=breadth.source_fingerprint(control), execution_friction=candidate["execution_friction"],
            annual_reset=False, fit_units=0, test_2026_rows_read=0,
            qualification_checks={"scope": "SYNTHETIC_ONLY", "accounting_qualified": True})
    monkeypatch.setattr(breadth, "_worker", worker)
    result = call_stage(stage)
    assert calls == stage["design"]["specification"]["candidates_in_exact_order"]
    assert result["budget"]["new_account_attempts"] == 19 and result["budget"]["failed_attempts"] == 1
    assert result["finite_execution_complete"] and not result["winner_selected"]
    assert result["new_fit"] == 0 and not (run / "FIT_LOG.jsonl").exists()
    assert before == {name: execution.values.sha(control.run / name) for name in before}
    assert not (control.run / "CONTINUATION_LOCK.json").exists()
    assert len(stage["guard_calls"]) >= 19
    history = execution._continuation_events(run, "ACCOUNT_PATH_LOG.jsonl")
    assert sum(event["event"] == "ACCOUNT_PATH_ATTEMPT_STARTED" for event in history) == 19
    assert sum(event["event"] == "ACCOUNT_PATH_FAILED" for event in history) == 1
    # A completed stage is resumable metadata; failed attempts are never retried.
    assert call_stage(stage)["finite_execution_complete"] and len(calls) == 19


def test_owned_controller_lock_has_no_second_writer_or_takeover(stage, monkeypatch):
    calls = []
    monkeypatch.setattr(breadth, "_worker", lambda *args: calls.append(args))
    with execution.continuation_lock(stage["control"].run, stage["control"].auth["module_sha256"], execution.R5_NAMESPACE):
        with pytest.raises(breadth.Blocked, match="ALREADY_EXISTS"):
            call_stage(stage)
    assert calls == [] and not (stage["run"] / "ACCOUNT_PATH_LOG.jsonl").exists()


@pytest.mark.parametrize("mutation", ["parent_namespace", "wrong_fingerprint", "changed_cost", "reordered", "nested_path", "fit_log"])
def test_stage_scope_bypasses_fail_before_any_worker(stage, monkeypatch, mutation):
    calls = []
    monkeypatch.setattr(breadth, "_worker", lambda *args: calls.append(args))
    if mutation == "parent_namespace":
        stage["control"].auth["namespace"] = "R2"
    elif mutation == "wrong_fingerprint":
        stage["identity"]["parent_R5_source_account_fingerprint"] = "wrong"
    elif mutation in ("changed_cost", "reordered"):
        design = json.loads(stage["design_path"].read_text())
        if mutation == "changed_cost":
            design["specification"]["candidates_in_exact_order"][0]["execution_friction"]["one_way_bps"] = 5
        else:
            design["specification"]["candidates_in_exact_order"].reverse()
        write(stage["design_path"], design)
    elif mutation == "nested_path":
        stage["run"] = stage["control"].run / "BREADTH"
    else:
        journal(stage["run"] / "FIT_LOG.jsonl", [dict(event="FIT_STARTED", fit_units=1)])
    with pytest.raises(breadth.Blocked):
        call_stage(stage)
    assert calls == [] and not (stage["run"] / "ACCOUNT_PATH_LOG.jsonl").exists()


def test_outstanding_breadth_attempt_is_retained_and_not_retried(stage, monkeypatch):
    candidate = stage["design"]["specification"]["candidates_in_exact_order"][0]
    event = breadth_event(candidate, "ACCOUNT_PATH_ATTEMPT_STARTED")
    event.update(namespace=breadth.NAMESPACE, module_sha256=execution.values.sha(Path(breadth.__file__)),
        controller_module_sha256=stage["control"].auth["module_sha256"], path_units=1)
    journal(stage["run"] / "ACCOUNT_PATH_LOG.jsonl", [event])
    before = execution.values.sha(stage["run"] / "ACCOUNT_PATH_LOG.jsonl")
    monkeypatch.setattr(breadth, "_worker", lambda *args: pytest.fail("Outstanding attempt must not be retried"))
    with pytest.raises(breadth.Blocked, match="OUTSTANDING_NO_AUTORETRY"):
        call_stage(stage)
    assert execution.values.sha(stage["run"] / "ACCOUNT_PATH_LOG.jsonl") == before
    assert not (stage["control"].run / "CONTINUATION_LOCK.json").exists()


@pytest.mark.parametrize("mutation", ["qualification", "bundle_identity", "year_grid"])
def test_risk_bank_qualification_and_exact_identity_are_not_upgraded(metadata, mutation):
    packet = metadata["exact_risk_dependency_refs"]["OAS"]
    if mutation == "year_grid":
        del packet["annual"]["2024"]
    elif mutation == "bundle_identity":
        packet["annual"]["2023"]["refs"]["bundle"]["sha256"] = "1" * 64
    else:
        entry = packet["annual"]["2023"]
        receipt = json.loads(Path(entry["refs"]["receipt"]["path"]).read_text())
        receipt["scientific_return_proxy_qualified"] = 1
        entry["receipt_metadata"] = deepcopy(receipt)
        entry["refs"]["receipt"] = write(Path(entry["refs"]["receipt"]["path"]), receipt)
    with pytest.raises(breadth.Blocked):
        breadth.validate_dependencies(metadata)


@pytest.mark.parametrize("field,value", [("candidate_order", []), ("max_new_account_paths", 20),
    ("new_fit_hard_limit", 1), ("2026_locked", False), ("account_contract", {"capital_usd": 4000})])
def test_bound_identity_cannot_expand_frozen_scientific_scope(stage, monkeypatch, field, value):
    stage["identity"][field] = value
    calls = []
    monkeypatch.setattr(breadth, "_worker", lambda *args: calls.append(args))
    with pytest.raises(breadth.Blocked, match="IDENTITY"):
        call_stage(stage)
    assert calls == [] and not (stage["run"] / "ACCOUNT_PATH_LOG.jsonl").exists()


def test_in_memory_complete_cannot_override_persisted_parent_status(stage, monkeypatch):
    write(stage["control"].run / "EXECUTION_STATUS.json", {"status": "RUNNING", "synthetic_only": True})
    monkeypatch.setattr(breadth, "_worker", lambda *args: pytest.fail("Persisted parent is still running"))
    with pytest.raises(breadth.Blocked, match="PERSISTED_STATUS_NOT_COMPLETE"):
        call_stage(stage)
    assert not (stage["run"] / "ACCOUNT_PATH_LOG.jsonl").exists()


@pytest.mark.parametrize("changed", list(breadth.PROTECTED))
def test_frozen_strict_breadth_custody_rejects_each_engineering_descendant(monkeypatch, changed):
    """An isolated stage fixture must not weaken the real strict custody gate."""
    expected = {str((execution.values.REPO / name).resolve()): value
                for name, value in breadth.PROTECTED.items()}
    monkeypatch.setattr(execution.values, "sha", lambda path: expected[str(Path(path).resolve())])
    assert breadth.protected_custody() == breadth.PROTECTED
    expected[str((execution.values.REPO / changed).resolve())] = "0" * 64
    with pytest.raises(breadth.Blocked, match="BREADTH_PROTECTED_SOURCE_CHANGED"):
        breadth.protected_custody()
