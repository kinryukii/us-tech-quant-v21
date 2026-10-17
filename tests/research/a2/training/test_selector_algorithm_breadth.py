"""Synthetic production spies; no real inputs, outcomes or estimator backend fits."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import selector_algorithm_breadth as sut
from scripts.research.a2.evaluation import selector_algorithm_breadth_evidence as adapter

FEATURES = [f"f{i:02d}" for i in range(32)]
BACKENDS = {name: dict(status="AVAILABLE", version="SYNTHETIC", origin="synthetic-source")
            for name in sut.BACKEND_MODULES}
BUDGET = dict(model_year_slots=54, estimator_fit_calls=54, scaler_fit_calls=54,
    backend_fit_calls=108, scientific_retries=0, risk_fit_calls=0,
    calibration_fit_calls=0, configs_per_role=1, seeds_per_role=1, workers=1, threads=2)


def pin(path):
    return dict(path=str(path), sha256=sut.sha(path))


def freeze(run, design):
    sut.putj(run / "DESIGN_FREEZE.json", design)
    digest = sut.sha(run / "DESIGN_FREEZE.json")
    sut.putj(run / "DESIGN_FREEZE_SHA.json", dict(sha256=digest))
    cfg = sut.readj(run / "run_config.json")
    cfg["design_freeze_sha256"] = digest
    sut.putj(run / "run_config.json", cfg)
    sut.putj(run / "FREEZE_ACTIVATION.json", dict(design_freeze_sha256=digest, status="PASS"))


@pytest.fixture
def contract(tmp_path, monkeypatch):
    run = tmp_path / "backtest/run"
    results, cache = tmp_path / "results/run", tmp_path / "cache/run"
    for path in (run, results, cache):
        path.mkdir(parents=True)
    source, dag, premise = run / "source.py", run / "dag.json", run / "source_contract.json"
    source.write_text("# synthetic source", encoding="utf-8")
    sut.putj(dag, {"synthetic": True})
    sut.putj(premise, dict(mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
                         source_contract_mode="FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY"))
    cfg = dict(results_directory=str(results), cache_directory=str(cache),
               research_id=sut.ID, research_line="C_SELECTOR")
    sut.putj(run / "run_config.json", cfg)
    design = dict(research_id=sut.ID, official_freeze=True, formal_freeze_applied=True,
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        test2026_locked=True, new2026_estimation_authorized=False,
        roles=list(sut.objectives.role_specs()), role_specs=sut.objectives.role_specs(),
        new_fitting_years=list(sut.YEARS), seed=20260928, features=FEATURES.copy(),
        fixed_features=FEATURES.copy(), target="MEAN_ER_3D_5D_10D_20D",
        fitting_weights="fixed day-balanced sampled keys; each input row weight one, no explicit equal-total-date sample_weight",
        budget=BUDGET.copy(), sources={str(source): sut.sha(source)}, source_contract=pin(premise),
        physical_dag=pin(dag), evaluation={"legacy": {}})
    if hasattr(sut, "required_source_paths"):
        design["sources"].update({str(p): sut.sha(p) for p in sut.required_source_paths()})
    design["backend_versions"] = copy.deepcopy(BACKENDS)
    freeze(run, design)
    paths = SimpleNamespace(backtest_root=tmp_path / "backtest", results_root=tmp_path / "results",
                            cache_root=tmp_path / "cache")
    monkeypatch.setattr(sut, "resolve", lambda repo: paths)
    def safe(path, kind, paths):
        assert Path(path).resolve().is_relative_to(getattr(paths, kind + "_root").resolve())
    monkeypatch.setattr(sut, "assert_safe_output_path", safe)
    return run, results, design


def test_checked_schema_agrees_with_objectives_and_adapter(contract):
    run, _, _ = contract
    _, d = sut.checked(run)
    assert tuple(d["roles"]) == adapter.ROLES
    assert d["budget"]["model_year_slots"] == 54 and d["budget"]["backend_fit_calls"] == 108
    assert d["budget"]["scientific_retries"] == 0


@pytest.mark.parametrize("field,value", [
    ("official_freeze", False), ("formal_freeze_applied", False),
    ("strict_PIT_promotion_eligible", True), ("test2026_locked", False),
    ("new2026_estimation_authorized", True), ("features", FEATURES + ["risk_state"]),
    ("seed", 1), ("new_fitting_years", [2023, 2024, 2025, 2026]),
    ("target", "EXECUTABLE_NET_PROFIT"),
])
def test_checked_boundary_changes_stop_before_runtime(contract, monkeypatch, field, value):
    run, _, d = contract
    d[field] = value
    freeze(run, d)
    monkeypatch.setattr(sut.prior, "runtime", lambda *a: pytest.fail("runtime before valid freeze"))
    with pytest.raises(ValueError):
        sut.train(run)


def test_source_hash_and_strict_premise_are_gates(contract):
    run, _, d = contract
    Path(next(iter(d["sources"]))).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        sut.checked(run)
    d["sources"] = {p: sut.sha(p) for p in d["sources"]}
    premise = Path(d["source_contract"]["path"])
    sut.putj(premise, dict(mechanism_research_eligible=True, strict_PIT_promotion_eligible=True,
                         source_contract_mode="STRICT_PIT"))
    d["source_contract"] = pin(premise)
    freeze(run, d)
    with pytest.raises(ValueError, match="SOURCE_AUTHORITY_PREMISE"):
        sut.checked(run)


def test_full_pool_boundary_uid_ties_and_future_append_do_not_change_past():
    frame = pd.DataFrame(dict(signal_date=pd.to_datetime(["2022-01-03"] * 25),
        security_uid=[f"UID{i:02d}" for i in range(24, -1, -1)], target=np.zeros(25)))
    labels = sut.boundary_labels(frame)
    assert labels.sum() == 20
    assert set(frame.loc[labels.astype(bool), "security_uid"]) == {f"UID{i:02d}" for i in range(20)}
    appended = pd.concat([frame, frame.assign(signal_date=pd.Timestamp("2025-01-03"), target=100.)], ignore_index=True)
    np.testing.assert_array_equal(sut.boundary_labels(appended)[:25], labels)
    with pytest.raises(ValueError, match="DUPLICATE"):
        sut.boundary_labels(pd.concat([frame, frame.iloc[:1]], ignore_index=True))


def inputs_fixture(run, d, monkeypatch, mixed=False):
    parent = run.parent / "parent"
    parent.mkdir(exist_ok=True)
    path = run / "inputs.parquet"
    dates = pd.to_datetime(["2022-01-03", "2026-01-02"] if mixed else ["2022-01-03", "2025-01-03"])
    pd.DataFrame(dict(signal_date=dates, target_end_date=dates + pd.Timedelta(days=1))).to_parquet(path, index=False)
    d["inputs"] = {"training": pin(path)}
    sut.putj(parent / "DESIGN_FREEZE.json", {"inputs": copy.deepcopy(d["inputs"]), "features": FEATURES.copy()})
    d["parent_run"], d["parent_design_sha256"] = str(parent), sut.sha(parent / "DESIGN_FREEZE.json")
    shared = SimpleNamespace(FEATURES=FEATURES.copy())
    rt = (None, None, None, None, None, None, None, shared)
    return rt, parent


def test_parent_data_body_unreachable_until_actual_footers_proven(contract, monkeypatch):
    run, _, d = contract
    rt, _ = inputs_fixture(run, d, monkeypatch, mixed=True)
    monkeypatch.setattr(sut.prior, "data", lambda *a: pytest.fail("mixed body projection"))
    with pytest.raises(ValueError, match="PHYSICAL_BOUNDARY"):
        sut.read_inputs(run, rt, d)


def test_guarded_input_pins_must_be_the_parent_actual_reader_inputs(contract, monkeypatch):
    run, _, d = contract
    rt, parent = inputs_fixture(run, d, monkeypatch)
    unsafe = run / "different.parquet"
    pd.DataFrame(dict(signal_date=pd.to_datetime(["2026-01-02"]),
        target_end_date=pd.to_datetime(["2026-01-03"]))).to_parquet(unsafe, index=False)
    sut.putj(parent / "DESIGN_FREEZE.json", {"inputs": {"training": pin(unsafe)}, "features": FEATURES.copy()})
    d["parent_design_sha256"] = sut.sha(parent / "DESIGN_FREEZE.json")
    monkeypatch.setattr(sut.prior, "data", lambda *a: pytest.fail("unguarded parent body projection"))
    with pytest.raises(ValueError, match="PARENT.*INPUT|INPUT.*PARENT"):
        sut.read_inputs(run, rt, d)


def test_exact_features_gate_precedes_parent_body(contract, monkeypatch):
    run, _, d = contract
    rt, _ = inputs_fixture(run, d, monkeypatch)
    d["features"] = ["risk_state", *FEATURES[1:]]
    monkeypatch.setattr(sut.prior, "data", lambda *a: pytest.fail("body before exact information gate"))
    with pytest.raises(ValueError, match="FEATURE"):
        sut.read_inputs(run, rt, d)


def training_fixture(contract, monkeypatch, failure=None, sample_last=False, bad_prediction=False):
    run, results, d = contract
    dates = pd.to_datetime(["2022-01-03"] * 25)
    train = pd.DataFrame(dict(signal_date=dates, target_end_date=dates + pd.Timedelta(days=20),
        ticker=[f"S{i:02d}" for i in range(25)], security_uid=[f"UID{i:02d}" for i in range(25)],
        target=np.arange(25., 0., -1)))
    for i, feature in enumerate(FEATURES):
        train[feature] = np.arange(25.) + i
    frame = pd.DataFrame([dict(signal_date=pd.Timestamp(f"{year}-01-03"), ticker=f"S{i:02d}",
        security_uid=f"UID{i:02d}", U_t_fingerprint="SYNTHETIC_FULL_U_T", **{f:float(i) for f in FEATURES})
        for year in sut.YEARS for i in range(3)])
    samples = []
    sampler = (lambda f, pd, np: f.iloc[-5:].reset_index(drop=True)) if sample_last else sut.prior.sampled
    monkeypatch.setattr(sut.prior, "sampled", sampler)
    for year in sut.YEARS:
        path = run / f"sample_{year}.parquet"
        sampler(train, pd, np)[["signal_date", "ticker", "security_uid", "target_end_date"]].to_parquet(path, index=False)
        samples.append(dict(year=year, **pin(path)))
    manifest_path = run / "reuse.json"
    sut.putj(manifest_path, {"training_samples": samples})
    d["native_reuse_manifest"] = pin(manifest_path)
    raw_path = run / "raw.parquet"
    frame[sut.KEYS].to_parquet(raw_path, index=False)
    d["score_reuse"] = {sut.RAW: pin(raw_path)}
    evidence_sources = (Path(adapter.__file__), Path(sut.evidence.__file__),
        sut.REPO / "scripts/research/a2/evaluation/selector_account_compare.py")
    d["sources"].update({str(p): sut.sha(p) for p in evidence_sources})
    freeze(run, d)
    captured = []
    def dump(value, path, compress):
        Path(path).write_bytes(b"synthetic model")
    rt = (None, np, pd, None, SimpleNamespace(dump=dump), SimpleNamespace(RUNTIME={"modules": copy.deepcopy(BACKENDS)}), None,
          SimpleNamespace(FEATURES=FEATURES), None, None)
    monkeypatch.setattr(sut.prior, "runtime", lambda run: rt)
    monkeypatch.setattr(sut, "read_inputs", lambda *a: (train.copy(), frame.copy()))
    class Scaler:
        def fit(self, x):
            ledger = sut.readj(run / "FIT_LEDGER.json")
            event = ledger["events"][-1]
            assert event["status"] == "RESERVED"
            assert event["actual_fit_calls_entered"]["scaler"] == 1
            assert ledger["charged_backend_ceiling"] >= 2
            return self
        def transform(self, x):
            return x
    import sklearn.preprocessing
    monkeypatch.setattr(sklearn.preprocessing, "StandardScaler", Scaler)
    def fit(role, x, y, date, boundary, runtime, on_fit_call):
        captured.append(dict(role=role, x=x.copy(), y=y.copy(), dates=date.copy(), boundary=boundary.copy()))
        if role == failure:
            raise ModuleNotFoundError("synthetic missing optional backend")
        on_fit_call(dict(operation="estimator_fit", role=role))
        ledger = sut.readj(run / "FIT_LEDGER.json")
        assert ledger["events"][-1]["actual_fit_calls_entered"]["estimator"] == 1
        return SimpleNamespace(metadata={"synthetic": True,
            "backend": {"module": "sklearn", **{k: BACKENDS["sklearn"][k] for k in ("version", "origin")}}})
    monkeypatch.setattr(sut.objectives, "fit", fit)
    monkeypatch.setattr(sut.objectives, "predict", lambda obj, x: np.zeros((len(x), 1))
        if bad_prediction else np.arange(len(x), dtype=float))
    return run, results, d, train, frame, captured


def test_all_54_slots_reserve_before_call_and_actual_callbacks_persist(contract, monkeypatch):
    run, _, d, _, frame, calls = training_fixture(contract, monkeypatch)
    sut.train(run)
    ledger = sut.readj(run / "FIT_LEDGER.json")
    assert len(calls) == len(ledger["events"]) == 54
    assert ledger["charged_backend_ceiling"] == ledger["actual_backend_fit_calls_entered"] == 108
    assert ledger["backend_fit_calls_completed"] == 108 and ledger["scientific_retries"] == 0
    for event in ledger["events"]:
        receipt = sut.qualify_existing_success(run, d, event)
        assert receipt["rows_prediction"] == int(frame.signal_date.dt.year.eq(event["year"]).sum())
    monkeypatch.setattr(sut.objectives, "fit", lambda *a, **k: pytest.fail("success scientific retry"))
    sut.train(run)
    assert sut.readj(run / "FIT_LEDGER.json") == ledger


def test_full_boundary_precedes_common_sampling_and_label_maturity(contract, monkeypatch):
    run, _, _, _, _, calls = training_fixture(contract, monkeypatch, sample_last=True)
    sut.train(run)
    assert len(calls) == 54
    assert all(len(c["x"]) == 5 and not c["boundary"].any() for c in calls)
    assert all(pd.to_datetime(c["dates"]).max() == pd.Timestamp("2022-01-03") for c in calls)


def test_failed_dependency_slots_retain_reservation_and_never_retry(contract, monkeypatch):
    role = adapter.ROLES[0]
    run, _, _, _, _, calls = training_fixture(contract, monkeypatch, failure=role)
    sut.train(run)
    ledger = sut.readj(run / "FIT_LEDGER.json")
    failures = [e for e in ledger["events"] if e["status"] == "FAILED"]
    assert len(failures) == 3 and ledger["charged_backend_ceiling"] == 108
    assert ledger["actual_backend_fit_calls_entered"] == 105
    assert all(e["actual_fit_calls_entered"] == {"scaler": 1, "estimator": 0} for e in failures)
    # Failed leftovers must not become readable candidates during assembly.
    for year in sut.YEARS:
        path = run / f"predictions/native_{role}_{year}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"FAILED_LEFTOVER_MUST_NOT_BE_READ")
    count = len(calls)
    sut.train(run)
    assert len(calls) == count and sut.readj(run / "FIT_LEDGER.json") == ledger
    original = sut.pre2026
    def safe(path, *args, **kwargs):
        assert f"native_{role}_" not in str(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(sut, "pre2026", safe)
    sut.assemble(run)
    assembly = sut.readj(run / "SCORE_ASSEMBLY.json")
    assert role not in assembly["complete_candidates"] and role in assembly["failed_or_untestable"]
    assert len(assembly["complete_candidates"]) == 17


def test_bad_native_prediction_shape_is_failed_never_replaced_or_shrunk(contract, monkeypatch):
    run, _, _, _, _, _ = training_fixture(contract, monkeypatch, bad_prediction=True)
    sut.train(run)
    ledger = sut.readj(run / "FIT_LEDGER.json")
    assert len(ledger["events"]) == 54 and all(e["status"] == "FAILED" for e in ledger["events"])
    assert ledger["actual_backend_fit_calls_entered"] == 108
    sut.assemble(run)
    assembly = sut.readj(run / "SCORE_ASSEMBLY.json")
    assert assembly["complete_candidates"] == [] and len(assembly["failed_or_untestable"]) == 18
    assert assembly["common_rows"] == 9 and assembly["common_dates"] == 3


def test_changed_common_sample_keys_stop_before_reservation(contract, monkeypatch):
    run, _, d, _, _, calls = training_fixture(contract, monkeypatch)
    path = Path(sut.readj(d["native_reuse_manifest"]["path"])["training_samples"][0]["path"])
    sample = pd.read_parquet(path)
    sample.loc[0, "security_uid"] = "CHANGED_UID"
    sample.to_parquet(path, index=False)
    manifest = sut.readj(d["native_reuse_manifest"]["path"])
    manifest["training_samples"][0].update(pin(path))
    sut.putj(d["native_reuse_manifest"]["path"], manifest)
    d["native_reuse_manifest"] = pin(Path(d["native_reuse_manifest"]["path"]))
    freeze(run, d)
    with pytest.raises(ValueError, match="EXACT_SAMPLED_KEYS"):
        sut.train(run)
    assert calls == [] and not sut.readj(run / "FIT_LEDGER.json")["events"]


def test_reserved_interruption_and_receipt_tamper_cannot_trigger_scientific_retry(contract, monkeypatch):
    run, _, d, _, _, calls = training_fixture(contract, monkeypatch)
    ledger = sut.new_ledger(run, d)
    sut.reserve(run, ledger, adapter.ROLES[0], 2023)
    with pytest.raises(ValueError, match="UNFINISHED"):
        sut.train(run)
    assert calls == []
    event = ledger["events"][0]
    event["status"] = "TRAINED"
    sut.putj(run / "FIT_LEDGER.json", ledger)
    receipt = run / f"models/{adapter.ROLES[0]}/2023.json"
    sut.putj(receipt, {"status": "FAILED"})
    with pytest.raises((ValueError, KeyError)):
        sut.qualify_existing_success(run, d, event)


def test_assembly_requires_exact_three_years_and_design_bound_ledger(contract, monkeypatch):
    run, _, _, _, _, _ = training_fixture(contract, monkeypatch)
    sut.train(run)
    ledger = sut.readj(run / "FIT_LEDGER.json")
    ledger["design_freeze_sha256"] = "0" * 64
    sut.putj(run / "FIT_LEDGER.json", ledger)
    with pytest.raises(ValueError, match="LEDGER_DESIGN"):
        sut.assemble(run)


def test_success_receipt_requires_actual_two_backend_calls(contract, monkeypatch):
    run, _, d, _, _, _ = training_fixture(contract, monkeypatch)
    sut.train(run)
    event = sut.readj(run / "FIT_LEDGER.json")["events"][0]
    event["actual_fit_calls_entered"]["estimator"] = 0
    with pytest.raises(ValueError, match="SUCCESS.*CALL|CALL.*SUCCESS|TELEMETRY"):
        sut.qualify_existing_success(run, d, event)


def report_evidence(run, results):
    sut.putj(run / "SCORE_ASSEMBLY.json", {"synthetic": True})
    receipt = dict(schema="C_ALGORITHM_BREADTH_SELECTION_EVIDENCE_V1", status="MECHANISM_EVIDENCE_COMPLETE",
        research_id=sut.ID, design_freeze_sha256=sut.sha(run / "DESIGN_FREEZE.json"),
        score_assembly_sha256=sut.sha(run / "SCORE_ASSEMBLY.json"),
        evaluation_source_sha256=sut.sha(adapter.__file__), strict_PIT_promotion_eligible=False,
        financial_verified=False, economic_promotion_allowed=False, finalists=[],
        test2026_locked=True, new2026_estimation_authorized=False,
        test2026_rows_read=0, test2026_rows_read_by_this_runner=0,
        candidates=[dict(candidate_id=role, test_id=role, status="COMPLETE",
            year_edges={str(y): .001 for y in sut.YEARS}, pooled_edge=.001,
            simultaneous_lower_95=-.002, mechanism_supported=False) for role in adapter.ROLES],
        research_supported_roles=[], failed_or_untestable={})
    sut.putj(results / "SELECTION_EVIDENCE.json", receipt)
    return receipt


def test_report_consumes_evidence_status_and_public_budget_audit(contract, monkeypatch):
    run, results, d, _, _, _ = training_fixture(contract, monkeypatch)
    sut.train(run)
    report_evidence(run, results)
    from scripts.maintenance import audit_repo_size_r1
    monkeypatch.setattr(audit_repo_size_r1, "audit", lambda repo: dict(violations=[],
        accounting_complete=True, hard_limit_passed=True))
    sut.report(run)
    delivery = sut.readj(run / "DELIVERY_COMPLETE.json")
    assert delivery["successful_roles"] == 18 and delivery["finalists"] == []
    assert delivery["strict_PIT_promotion_eligible"] is False
    assert (results / "FINAL_REPORT.md").is_file()


@pytest.mark.parametrize("field,value", [("design_freeze_sha256", "0" * 64),
    ("financial_verified", True), ("strict_PIT_promotion_eligible", True), ("test2026_rows_read", 1)])
def test_report_rejects_stale_or_promoted_evidence_before_writing_report(contract, field, value):
    run, results, d = contract
    sut.new_ledger(run, d)
    receipt = report_evidence(run, results)
    receipt[field] = value
    sut.putj(results / "SELECTION_EVIDENCE.json", receipt)
    with pytest.raises(ValueError, match="DELIVERY_EVIDENCE_LINEAGE_OR_AUTHORITY"):
        sut.report(run)
    assert not (results / "FINAL_REPORT.md").exists()


@pytest.mark.parametrize("field,value", [("charged_backend_ceiling", 0),
    ("actual_backend_fit_calls_entered", 1), ("backend_fit_calls_completed", 1), ("scientific_retries", 1)])
def test_resume_rejects_counter_drift_and_refunded_reservations(contract, field, value):
    run, _, d = contract
    ledger = sut.new_ledger(run, d)
    sut.reserve(run, ledger, adapter.ROLES[0], 2023)
    ledger[field] = value
    with pytest.raises(ValueError, match="LEDGER_COUNTER_OR_BUDGET"):
        sut.validate_ledger(run, d, ledger)


def test_resume_rejects_duplicate_or_noncanonical_year_slots(contract):
    run, _, d = contract
    ledger = sut.new_ledger(run, d)
    event = sut.reserve(run, ledger, adapter.ROLES[0], 2023)
    ledger["events"].append(copy.deepcopy(event))
    with pytest.raises(ValueError, match="LEDGER_SLOT"):
        sut.validate_ledger(run, d, ledger)
    ledger["events"].pop()
    ledger["events"][0]["year"] = 2026
    with pytest.raises(ValueError, match="LEDGER_SLOT"):
        sut.validate_ledger(run, d, ledger)


def test_missing_source_closure_and_run_identity_stop_before_runtime(contract, monkeypatch):
    run, _, d = contract
    d["sources"].pop(str(sut.required_source_paths()[0]))
    freeze(run, d)
    with pytest.raises(ValueError, match="SOURCE_CLOSURE"):
        sut.checked(run)
    d["sources"].update({str(p): sut.sha(p) for p in sut.required_source_paths()})
    freeze(run, d)
    cfg = sut.readj(run / "run_config.json")
    cfg["research_id"] = "OTHER_STUDY"
    sut.putj(run / "run_config.json", cfg)
    with pytest.raises(ValueError, match="RUN_CONFIG_RESEARCH_IDENTITY"):
        sut.checked(run)


def test_backend_origin_status_version_drift_precedes_input_body(contract, monkeypatch):
    run, _, d = contract
    actual = copy.deepcopy(BACKENDS)
    actual["sklearn"]["origin"] = "unfrozen-backend"
    rt = (None, None, None, None, None, SimpleNamespace(RUNTIME={"modules": actual}))
    monkeypatch.setattr(sut.prior, "runtime", lambda *a: rt)
    monkeypatch.setattr(sut, "read_inputs", lambda *a: pytest.fail("body before backend gate"))
    with pytest.raises(ValueError, match="FROZEN_BACKEND_VERSION_OR_ORIGIN"):
        sut.train(run)
    metadata = {"backend": dict(module="sklearn", version="UNFROZEN", origin=BACKENDS["sklearn"]["origin"])}
    rt = (None, None, None, None, None, SimpleNamespace(RUNTIME={"modules": copy.deepcopy(BACKENDS)}))
    with pytest.raises(ValueError, match="FITTED_BACKEND_VERSION_OR_ORIGIN"):
        sut.guard_backend(rt, d, metadata)
