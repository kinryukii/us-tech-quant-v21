"""Synthetic C R3 kernel checks; no real source receipt, fit or covariance estimate.

The C acceptance fixture exercises unfrozen consumer interface requirements; it
is never evidence that the absent actual shared source schema is integrated.
"""
import copy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import selector_monthly_risk as kernel

CAPS = dict(all_backend_plus_statistic_estimation_nodes_excluding_derived_fallback=868,
    all_model_year_attempt_slots=278, annual_head_year_slots=18, backend_fit_calls=192,
    base_fit_calls=0, calibration_fit_calls=0, candidate_head_year_slots=12,
    cholesky_ops=208, configs_per_role=1, derived_fallback_scalars=260, fusion_fit_calls=0,
    hgb_fit_calls=9, hgb_internal_trees=576, monthly_risk_state_slots=240,
    possible_matched_annual_reference_risk_slots=20, psd_validation_ops=260,
    reference_head_year_slots=6, retries_per_scientific_slot=0, ridge_fit_calls=9,
    risk_backend_fit_calls=156,
    risk_backend_plus_statistic_estimation_nodes_excluding_derived_fallback=832,
    risk_extra_analytical_statistics=156,
    risk_numpy_statistic_estimates_excluding_derived_fallback=676,
    risk_prepare_statistics=520, risk_state_slots=260, scaler_fit_calls=18,
    seeds_per_role=1, threads=2, workers=1)


def dag_fixture():
    roles = list(kernel.preflight.ROLES)
    refs = list(kernel.REFERENCES)
    cutoffs = [dict(cutoff_ref=f"FIRST_ACCEPTED_SESSION:{y}-{m:02d}",
        purpose="FOUR_CANDIDATES_SHARED_RISK_STATE")
        for y in (2022, 2023, 2024, 2025) for m in range(1, 13)]
    cutoffs += [dict(cutoff_ref=f"{y}-01-01T00:00:00",
        purpose="OPTIONAL_FIXED_REFERENCE_SHARED_RISK_STATE") for y in (2022, 2023, 2024, 2025)]
    method_entries = []
    for method, backend, extra, cholesky in (("DIAG", 0, 0, 0), ("LW", 1, 0, 1),
            ("OAS", 1, 0, 1), ("PCA", 1, 1, 1), ("EWMA", 0, 2, 1)):
        method_entries.append(dict(method=method, backend_fit_reservation=backend,
            prepare_statistic_reservation=2, extra_statistic_reservation=extra,
            derived_fallback_scalar_reservation=1, psd_validation_reservation=1,
            cholesky_reservation_upper=cholesky, attempt_limit=1, retry_limit=0))
    heads = [dict(slot_id=f"ANNUAL_HEAD:{role}:{year}", role=role, year=year,
        head_backend="HistGradientBoostingRegressor" if "HGB" in role else "Ridge",
        candidate=role in roles, reference_only=role in refs, scaler_fit_reservation=1,
        head_model_fit_reservation=1, attempt_limit=1, retry_limit=0)
        for role in roles + refs for year in (2023, 2024, 2025)]
    return dict(scientific_contract=dict(candidate_roles=roles, fixed_reference_roles=refs,
        core_methods=["DIAG", "LW", "OAS", "PCA", "EWMA"], risk_years=[2022, 2023, 2024, 2025],
        head_years=[2023, 2024, 2025], risk_refresh_cadence="MONTHLY_FIRST_ACCEPTED_SESSION",
        head_cadence="ANNUAL", head_hyperparameter_search=False, target_changed=False,
        seed=20260928, target="MEAN_ER_3D_5D_10D_20D", window_sessions=63,
        min_observations=30, candidate_count=4, reference_candidate_count=0, monthly_cutoff_max=48),
        risk_slot_reservation_plan=dict(encoding="CUT_OFF_METHOD_CARTESIAN_GRID", cutoffs=cutoffs,
            per_method=method_entries, expanded_slot_count=260, monthly_expanded_slot_count=240),
        annual_head_reservation_plan=heads, proposed_caps=copy.deepcopy(CAPS),
        reservation_contract=dict(all_new_one_pass_reservation_totals=copy.deepcopy(CAPS),
            reservation_before_first_operation=True, failed_or_timeout_reservation_released=False,
            same_scientific_slot_second_attempt_allowed=False), budget_frozen=True,
        official_freeze=True, source_gate="QUALIFIED", source_pins=[])


def metadata_fields(kind):
    return dict(metadata_only=True, artifact_kind=kind,
                observation_scope_end_exclusive="2026-01-01")


def descriptor(path, kind):
    return dict(path=str(path), sha256=kernel.prior.sha(path), metadata_only=True,
                artifact_kind=kind, content_scope="STRICT_PRE2026_SOURCE_METADATA")


def reseal(run, design):
    kernel.prior.putj(run / "DESIGN_FREEZE.json", design)
    sha = kernel.prior.sha(run / "DESIGN_FREEZE.json")
    kernel.prior.putj(run / "DESIGN_FREEZE_SHA.json", {"sha256": sha})
    kernel.prior.putj(run / "run_config.json", {"design_freeze_sha256": sha})


@pytest.fixture(autouse=True)
def forbid_real_estimation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("REAL_FIT_OR_ESTIMATION_FORBIDDEN_IN_SYNTHETIC_KERNEL_TESTS")
    monkeypatch.setattr(kernel.old, "bounded_risk_fit", forbidden)
    monkeypatch.setattr(kernel.risk, "fit_risk_estimator", forbidden)
    monkeypatch.setattr(kernel.risk, "_prepare", forbidden)
    monkeypatch.setattr(kernel.risk, "_estimate", forbidden)
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import HistGradientBoostingRegressor
    for model in (kernel.risk.LedoitWolf, kernel.risk.OAS, PCA, StandardScaler,
                  Ridge, HistGradientBoostingRegressor):
        monkeypatch.setattr(model, "fit", forbidden)


@pytest.fixture
def ready_run(tmp_path):
    # tmp_path is externally routed by the reviewed pytest invocation.
    run = tmp_path / "synthetic_run"
    run.mkdir()
    sessions = [pd.Timestamp(f"{y}-{m:02d}-03").isoformat()
                for y in (2022, 2023, 2024, 2025) for m in range(1, 13)]
    proof = dict(path=str(tmp_path / "SYNTHETIC_UNREAD_PROOF.parquet"), sha256="a" * 64)
    binding = dict(field="Cret1d", coordinate=kernel.COORDINATE, source_id="SYNTHETIC_SOURCE", return_unit=kernel.features.UNIT,
        return_horizon_sessions=1, identity_policy="NO_CROSS_IDENTITY_STITCHING",
        provider="SYNTHETIC", provider_version="fixture1", source_version="fixture1",
        session_timezone="America/New_York", scope_end_exclusive="2026-01-01")
    shared_path = run / "SYNTHETIC_SHARED_CONTRACT.json"
    kernel.prior.putj(shared_path, dict(**metadata_fields("SHARED_SOURCE_CONTRACT_METADATA"),
        status="QUALIFIED_ACCEPTED", schema="SHARED_C_SOURCE_CONTRACT_METADATA_V1",
        Cret1d_binding=binding, source_proof=proof, accepted_sessions=sessions))
    acceptance_path = run / "SYNTHETIC_C_ACCEPTANCE.json"
    kernel.prior.putj(acceptance_path, dict(**metadata_fields("C_SOURCE_ACCEPTANCE_METADATA"),
        status="QUALIFIED_ACCEPTED", schema="C_R3_SOURCE_ACCEPTANCE_METADATA_V1",
        consumer_binding_version=1, consumer="C_SELECTOR_R3",
        shared_contract=descriptor(shared_path, "SHARED_SOURCE_CONTRACT_METADATA"),
        Cret1d_binding=binding, source_proof=proof,
        qualification_checks={key: True for key in kernel.SOURCE_CHECKS}))
    dag = dag_fixture()
    dag.update(metadata_fields("PHYSICAL_DAG_BUDGET_FREEZE"))
    dag["source_pins"] = [dict(path=str(path), sha256=kernel.prior.sha(path))
                          for path in kernel.REQUIRED_SOURCES]
    dag_path = run / "PHYSICAL_DAG.json"
    kernel.prior.putj(dag_path, dag)
    design = dict(official_freeze=True, synthetic_only=True,
        execution_gates={key: True for key in kernel.GATES}, accepted_sessions=sessions,
        physical_dag=descriptor(dag_path, "PHYSICAL_DAG_BUDGET_FREEZE"),
        c_source_acceptance=descriptor(acceptance_path, "C_SOURCE_ACCEPTANCE_METADATA"),
        source_proof_sha256=proof["sha256"])
    reseal(run, design)
    return run, design


def update_dag(run, design, mutate):
    path = Path(design["physical_dag"]["path"])
    dag = kernel.prior.readj(path)
    mutate(dag)
    kernel.prior.putj(path, dag)
    design["physical_dag"]["sha256"] = kernel.prior.sha(path)
    reseal(run, design)


def test_expansion_has_exact_typed_caps_and_no_extra_candidate():
    slots = kernel.expanded_slots(dag_fixture())
    assert len(slots) == len({slot["slot_id"] for slot in slots}) == 278
    assert sum(s["kind"] == "RISK" and s["cadence"] == "MONTHLY" for s in slots) == 240
    assert sum(s["kind"] == "RISK" and s["cadence"] == "ANNUAL" for s in slots) == 20
    for name in ("backend_fit_calls", "risk_numpy_statistic_estimates_excluding_derived_fallback",
                 "derived_fallback_scalars", "scaler_fit_calls"):
        assert sum(s["reservation"].get(name, 0) for s in slots) == CAPS[name]
    assert all(s["reference_only"] and not s["candidate"] for s in slots
               if s["kind"] == "ANNUAL_HEAD" and s["role"] in kernel.REFERENCES)


def test_january_monthly_is_distinct_from_exact_annual(ready_run):
    context = kernel.checked(ready_run[0])
    jan = [s for s in context["slots"] if s["kind"] == "RISK" and s["method"] == "DIAG"
           and ("2023-01" in s["cutoff_ref"])]
    assert len(jan) == 2
    assert {s["cutoff"] for s in jan} == {"2023-01-01T00:00:00", "2023-01-03T00:00:00"}
    assert len({s["slot_id"] for s in jan}) == 2


@pytest.mark.parametrize("mode", ["missing", "unfrozen", "source_blocked", "gate_false"])
def test_gate_denies_before_input_reader(ready_run, mode):
    run, design = ready_run
    if mode == "missing":
        (run / "DESIGN_FREEZE.json").unlink()
    elif mode == "unfrozen":
        update_dag(run, design, lambda dag: dag.update(budget_frozen=False))
    elif mode == "source_blocked":
        design["execution_gates"]["source_qualified"] = False
        reseal(run, design)
    else:
        design["execution_gates"]["source_qualified"] = False
        reseal(run, design)
    calls = []
    with pytest.raises((kernel.ExecutionBlocked, KeyError, ValueError)):
        kernel.fit_risk_slot(run, "ANY", lambda slot: calls.append(slot))
    assert calls == [] and not (run / "FIT_LEDGER.json").exists()


@pytest.mark.parametrize("tamper", ["role", "seed", "cap", "method", "retry", "pin"])
def test_tampered_frozen_identity_denies_callback(ready_run, tamper):
    run, design = ready_run
    def mutation(dag):
        if tamper == "role":
            dag["scientific_contract"]["candidate_roles"][0] = "FIFTH_ROLE"
        elif tamper == "seed":
            dag["scientific_contract"]["seed"] = 20260929
        elif tamper == "cap":
            dag["proposed_caps"]["backend_fit_calls"] = 193
        elif tamper == "method":
            dag["risk_slot_reservation_plan"]["per_method"][0]["backend_fit_reservation"] = 1
        elif tamper == "retry":
            dag["annual_head_reservation_plan"][0]["retry_limit"] = 1
        else:
            dag["source_pins"][0]["sha256"] = "0" * 64
    update_dag(run, design, mutation)
    calls = []
    with pytest.raises(ValueError):
        kernel.execute(run, "ANY", lambda slot: calls.append(slot))
    assert not calls and not (run / "FIT_LEDGER.json").exists()


def test_status_only_source_and_semantic_failure_are_not_acceptance(ready_run):
    run, design = ready_run
    path = Path(design["c_source_acceptance"]["path"])
    receipt = kernel.prior.readj(path)
    receipt["status"] = "QUALIFIED"
    receipt["qualification_checks"]["endpoint_predecessor_uid_unit_verified"] = False
    kernel.prior.putj(path, receipt)
    design["c_source_acceptance"]["sha256"] = kernel.prior.sha(path)
    reseal(run, design)
    with pytest.raises(kernel.ExecutionBlocked, match="SEMANTICS"):
        kernel.checked(run)


@pytest.mark.parametrize("error,status", [(RuntimeError("synthetic failure"), "FAILED"),
                                           (TimeoutError("synthetic timeout"), "TIMED_OUT")])
def test_failure_keeps_full_durable_reservation_and_no_retry(ready_run, error, status):
    run, _ = ready_run
    slot = next(s for s in kernel.checked(run)["slots"] if s["kind"] == "ANNUAL_HEAD")
    def fail(reserved):
        ledger = kernel.prior.readj(run / "FIT_LEDGER.json")
        assert ledger["events"][0]["status"] == "RESERVED"
        assert ledger["reserved"]["backend_fit_calls"] == 2
        raise error
    with pytest.raises(type(error)):
        kernel.execute(run, slot["slot_id"], fail)
    ledger = kernel.prior.readj(run / "FIT_LEDGER.json")
    assert ledger["reserved"] == slot["reservation"] and ledger["events"][0]["status"] == status
    calls = []
    with pytest.raises(kernel.ExecutionBlocked, match="NO_RETRY"):
        kernel.execute(run, slot["slot_id"], lambda s: calls.append(s))
    assert calls == []


def test_resumed_unfinished_is_consumed_and_single_worker_enforced(ready_run):
    run, _ = ready_run
    slot = kernel.checked(run)["slots"][0]
    kernel.reserve(run, slot["slot_id"])
    calls = []
    with pytest.raises(kernel.ExecutionBlocked, match="NO_RETRY"):
        kernel.execute(run, slot["slot_id"], lambda s: calls.append(s))
    with kernel._one_worker(run):
        with pytest.raises(kernel.ExecutionBlocked, match="SINGLE_WORKER"):
            kernel.reserve(run, kernel.checked(run)["slots"][1]["slot_id"])
    assert calls == []
    kernel.finish(run, slot["slot_id"], "FAILED")
    assert kernel.prior.readj(run / "FIT_LEDGER.json")["reserved"] == slot["reservation"]


def test_fit_adapter_delegates_one_qualified_uid_panel_to_existing_owner(ready_run, monkeypatch):
    run, _ = ready_run
    calls = []
    panel = pd.DataFrame({"UID_X": [.01]}, index=pd.DatetimeIndex(["2022-12-30"]))
    coverage = pd.DataFrame({"asset": ["UID_X"]})
    def input_reader(slot):
        calls.append("input")
        return dict(history="SYNTHETIC_HISTORY", accepted_sessions=ready_run[1]["accepted_sessions"],
            universe="SYNTHETIC_ROSTER", decision_at="2023-01-03T09:30:00-05:00",
            source_authority=lambda row, **clock: True, source_id="SYNTHETIC_SOURCE",
            source_proof_sha256="a" * 64)
    def adapt(history, sessions, cutoff, universe, **kwargs):
        calls.append(("panel", cutoff, kwargs["cadence"], kwargs["decision_at"]))
        return panel, coverage, dict(status="UID_PANEL_QUALIFIED", qualification_sha256="b" * 64)
    def fit(method, table, market, params, timeout):
        calls.append(("fit", method, timeout, params))
        assert table is panel and market is None
        return SimpleNamespace(status="FITTED", method_id=method)
    monkeypatch.setattr(kernel.preflight, "canonical_uid_return_panel", adapt)
    monkeypatch.setattr(kernel.old, "bounded_risk_fit", fit)
    slot = next(s for s in kernel.checked(run)["slots"] if s.get("cutoff_ref") ==
                "FIRST_ACCEPTED_SESSION:2023-01" and s.get("method") == "LW")
    result = kernel.fit_risk_slot(run, slot["slot_id"], input_reader)
    assert result[1] is coverage and [c[0] if isinstance(c, tuple) else c for c in calls] == ["input", "panel", "fit"]
    assert calls[1][1:3] == ("2023-01-03T00:00:00", "MONTHLY")
    assert calls[2][3]["fit_cutoff"] == "2023-01-03T00:00:00"
    assert kernel.prior.readj(run / "FIT_LEDGER.json")["events"][0]["status"] == "SUCCEEDED"


def test_full_u_projection_uses_existing_owner_with_synthetic_bundle(monkeypatch):
    bundle = SimpleNamespace(status="FITTED", estimated_assets=("A", "B"),
        covariance=np.array([[.04, -.015], [-.015, .01]]), fallback_variance=.09)
    requested = ["A", "B", "NEW_UID"]
    original = kernel.features.project
    calls = []
    def project(value, full_pool):
        calls.append((value, tuple(full_pool)))
        return original(value, full_pool)
    monkeypatch.setattr(kernel.features, "project", project)
    result = kernel.project_full_pool(bundle, requested)
    assert calls == [(bundle, tuple(requested))]
    assert result.shape == (3, 3) and result[:, 2].tolist() == [0., 0., 1.]
    assert result[1, 1] < 0 and result[2, 0] == pytest.approx(.3)

@pytest.mark.parametrize("status", ["FAIL_CLOSED", "UNKNOWN", "BLOCKED", "QUALIFIED"])
def test_shared_status_cannot_override_c_acceptance_semantics(ready_run, status):
    run, design = ready_run
    path = Path(design["c_source_acceptance"]["path"])
    receipt = kernel.prior.readj(path)
    shared_path = Path(receipt["shared_contract"]["path"])
    shared = kernel.prior.readj(shared_path)
    shared["status"] = status
    kernel.prior.putj(shared_path, shared)
    receipt["shared_contract"]["sha256"] = kernel.prior.sha(shared_path)
    kernel.prior.putj(path, receipt)
    design["c_source_acceptance"]["sha256"] = kernel.prior.sha(path)
    reseal(run, design)
    with pytest.raises(kernel.ExecutionBlocked, match="SHARED_SOURCE"):
        kernel.execute(run, "ANY", lambda slot: pytest.fail("callback invoked"))


def test_unknown_metadata_descriptor_rejected_before_json_read(ready_run, monkeypatch):
    run, design = ready_run
    design["c_source_acceptance"]["metadata_only"] = False
    reseal(run, design)
    original = kernel.prior.readj
    def readj(path):
        assert Path(path).name != "SYNTHETIC_C_ACCEPTANCE.json"
        return original(path)
    monkeypatch.setattr(kernel.prior, "readj", readj)
    with pytest.raises(kernel.ExecutionBlocked, match="CLASSIFIED_METADATA"):
        kernel.checked(run)


@pytest.mark.parametrize("changed", ["calendar", "source", "proof", "universe"])
def test_reader_identity_mismatch_denies_before_panel_or_fit(ready_run, monkeypatch, changed):
    run, design = ready_run
    supplied = dict(history="SYNTHETIC_HISTORY", accepted_sessions=design["accepted_sessions"],
        universe="SYNTHETIC_ROSTER", decision_at="2023-01-03T09:30:00-05:00",
        source_authority=lambda row, **clock: changed != "universe",
        source_id="SYNTHETIC_SOURCE", source_proof_sha256="a" * 64)
    if changed == "calendar":
        supplied["accepted_sessions"] = ["2023-01-04"]
    elif changed == "source":
        supplied["source_id"] = "OTHER"
    elif changed == "proof":
        supplied["source_proof_sha256"] = "b" * 64
    monkeypatch.setattr(kernel.preflight, "canonical_uid_return_panel",
                        lambda *a, **k: pytest.fail("panel invoked"))
    slot = kernel.checked(run)["slots"][0]
    with pytest.raises(kernel.ExecutionBlocked):
        kernel.fit_risk_slot(run, slot["slot_id"], lambda s: supplied)
    assert kernel.prior.readj(run / "FIT_LEDGER.json")["events"][0]["status"] == "FAILED"


def test_frozen_budget_source_snapshot_is_not_a_second_source_authority(ready_run):
    run, design = ready_run
    update_dag(run, design, lambda dag: dag.update(source_gate="BLOCKED", official_freeze=False))
    assert len(kernel.checked(run)["slots"]) == 278
    # The same frozen bytes stay fixed when current source qualification fails.
    frozen_sha = design["physical_dag"]["sha256"]
    design["execution_gates"]["source_qualified"] = False
    reseal(run, design)
    with pytest.raises(kernel.ExecutionBlocked, match="EXECUTION_GATE"):
        kernel.execute(run, "ANY", lambda slot: pytest.fail("callback invoked"))
    assert kernel.prior.sha(Path(design["physical_dag"]["path"])) == frozen_sha


@pytest.mark.parametrize("field", ["design_sha256", "dag_sha256", "source_proof_sha256",
                                   "source_id", "accepted_sessions", "slots", "caps"])
def test_second_gate_context_drift_preserves_reservation_without_callback(ready_run, monkeypatch, field):
    run, _ = ready_run
    original = kernel.checked(run)
    slot = next(s for s in original["slots"] if s.get("method") == "LW")
    calls = []
    number = 0
    def checked(path):
        nonlocal number
        number += 1
        context = copy.deepcopy(original)
        if number > 1:
            if field == "accepted_sessions":
                context[field][0] = "2022-01-04T00:00:00"
            elif field == "slots":
                context[field][0]["method"] = "GARCH"
            elif field == "caps":
                context[field]["backend_fit_calls"] += 1
            else:
                context[field] = "DRIFTED"
        return context
    monkeypatch.setattr(kernel, "checked", checked)
    with pytest.raises(kernel.ExecutionBlocked, match="RESERVED_CONTEXT_CHANGED"):
        kernel.execute(run, slot["slot_id"], lambda s: calls.append(s))
    ledger = kernel.prior.readj(run / "FIT_LEDGER.json")
    assert calls == [] and ledger["events"][0]["status"] == "FAILED"
    assert ledger["reserved"] == slot["reservation"]


@pytest.mark.parametrize("field,value", [("method", "GARCH"),
                                           ("cutoff", "2024-01-01T00:00:00")])
def test_input_reader_cannot_change_reserved_risk_method_or_cutoff(ready_run, monkeypatch, field, value):
    run, _ = ready_run
    slot = next(s for s in kernel.checked(run)["slots"] if s.get("method") == "LW")
    monkeypatch.setattr(kernel.preflight, "canonical_uid_return_panel",
                        lambda *a, **k: pytest.fail("panel invoked"))
    def reader(view):
        view[field] = value
        return {}
    with pytest.raises(kernel.ExecutionBlocked, match="INPUT_READER_CHANGED_SLOT"):
        kernel.fit_risk_slot(run, slot["slot_id"], reader)
    ledger = kernel.prior.readj(run / "FIT_LEDGER.json")
    assert ledger["events"][0]["status"] == "FAILED"
    assert ledger["reserved"] == slot["reservation"]
    assert next(s for s in kernel.checked(run)["slots"] if s["slot_id"] == slot["slot_id"]) == slot


def synthetic_source_correction(ready_run):
    """No actual correction receipt is created; the original bytes are a fixture."""
    run, design = ready_run
    current = Path(kernel.__file__).resolve()
    original = run / "SYNTHETIC_ORIGINAL_SOURCE.txt"
    original.write_text("SYNTHETIC ORIGINAL ENTRY SOURCE\n", encoding="utf-8")
    original_sha = kernel.prior.sha(original)
    actual = kernel.prior.sha(current)
    def mutate(dag):
        dag["research_id"] = "SYNTHETIC_C_R3"
        next(pin for pin in dag["source_pins"] if Path(pin["path"]).resolve() == current)["sha256"] = original_sha
    update_dag(run, design, mutate)
    design["research_id"] = "SYNTHETIC_C_R3"
    design["sources"] = {str(current): actual}
    review_path = run / "SYNTHETIC_INDEPENDENT_REVIEW.json"
    review = dict(**metadata_fields("ENGINEERING_INDEPENDENT_REVIEW_METADATA"),
        status="PASS", classification="ENGINEERING_ONLY", source_path=str(current),
        original_source_sha256=original_sha, corrected_source_sha256=actual,
        physical_dag_sha256=design["physical_dag"]["sha256"], research_id=design["research_id"])
    kernel.prior.putj(review_path, review)
    correction_path = run / "SYNTHETIC_SOURCE_CORRECTION.json"
    correction = dict(**metadata_fields("BUDGET_SOURCE_CORRECTION_METADATA"),
        schema="C_R3_BUDGET_SOURCE_CORRECTION_METADATA_V1", classification="ENGINEERING_ONLY",
        original_source=dict(path=str(current), sha256=original_sha),
        corrected_source=dict(path=str(current), sha256=actual),
        original_snapshot=dict(path=str(original), sha256=original_sha),
        physical_dag_sha256=design["physical_dag"]["sha256"], research_id=design["research_id"],
        budget_and_scientific_parameters_changed=False,
        actual_execution=dict(fit_calls=0, covariance_estimates=0, outcome_rows_read=0),
        independent_review=descriptor(review_path, "ENGINEERING_INDEPENDENT_REVIEW_METADATA"))
    kernel.prior.putj(correction_path, correction)
    design["budget_source_correction"] = descriptor(correction_path, "BUDGET_SOURCE_CORRECTION_METADATA")
    reseal(run, design)
    return run, design, correction_path, correction, review_path, review


def test_reviewed_self_only_correction_preserves_frozen_dag_bytes(ready_run):
    run, design, *_ = synthetic_source_correction(ready_run)
    frozen = design["physical_dag"]["sha256"]
    assert len(kernel.checked(run)["slots"]) == 278
    assert kernel.prior.sha(Path(design["physical_dag"]["path"])) == frozen
    slot = kernel.checked(run)["slots"][0]
    assert kernel.execute(run, slot["slot_id"], lambda s: "SYNTHETIC_STUB") == "SYNTHETIC_STUB"
    assert kernel.prior.readj(run / "FIT_LEDGER.json")["reserved"] == slot["reservation"]


@pytest.mark.parametrize("tamper", ["missing", "original", "corrected", "other_source", "snapshot",
    "dag", "research", "fit", "covariance", "outcome", "science", "review", "review_hash", "design_source"])
def test_invalid_source_correction_never_invokes_callback(ready_run, tamper):
    run, design, path, correction, review_path, review = synthetic_source_correction(ready_run)
    if tamper == "missing":
        del design["budget_source_correction"]
    elif tamper == "original":
        correction["original_source"]["sha256"] = "0" * 64
    elif tamper == "corrected":
        correction["corrected_source"]["sha256"] = "0" * 64
    elif tamper == "other_source":
        correction["corrected_source"]["path"] = kernel.old.__file__
    elif tamper == "snapshot":
        correction["original_snapshot"]["sha256"] = "0" * 64
    elif tamper == "dag":
        correction["physical_dag_sha256"] = "0" * 64
    elif tamper == "research":
        correction["research_id"] = "OTHER"
    elif tamper in ("fit", "covariance", "outcome"):
        correction["actual_execution"][dict(fit="fit_calls", covariance="covariance_estimates",
                                             outcome="outcome_rows_read")[tamper]] = 1
    elif tamper == "science":
        correction["budget_and_scientific_parameters_changed"] = True
    elif tamper == "review":
        review["status"] = "UNKNOWN"
        kernel.prior.putj(review_path, review)
        correction["independent_review"]["sha256"] = kernel.prior.sha(review_path)
    elif tamper == "review_hash":
        correction["independent_review"]["sha256"] = "0" * 64
    else:
        design["sources"][str(Path(kernel.__file__).resolve())] = "0" * 64
    kernel.prior.putj(path, correction)
    if "budget_source_correction" in design:
        design["budget_source_correction"]["sha256"] = kernel.prior.sha(path)
    reseal(run, design)
    calls = []
    with pytest.raises(kernel.ExecutionBlocked):
        kernel.execute(run, "ANY", lambda slot: calls.append(slot))
    assert calls == [] and not (run / "FIT_LEDGER.json").exists()


def test_third_gate_new_identity_is_rejected_against_durable_reservation(ready_run, monkeypatch):
    run, _ = ready_run
    original = kernel.checked(run)
    slot = next(s for s in original["slots"] if s.get("method") == "LW")
    calls = []
    number = 0
    def checked(path):
        nonlocal number
        number += 1
        context = copy.deepcopy(original)
        if number >= 3:
            # Newly sealed B remains valid on both third and fourth checks;
            # it must not execute under A's already-persisted reservation.
            context["design_sha256"] = "b" * 64
            context["source_proof_sha256"] = "c" * 64
            context["source_id"] = "SYNTHETIC_SOURCE_B"
        return context
    monkeypatch.setattr(kernel, "checked", checked)
    monkeypatch.setattr(kernel.old, "bounded_risk_fit", lambda *a, **k: calls.append("fit"))
    with pytest.raises(kernel.ExecutionBlocked, match="LEDGER_IDENTITY_CHANGED"):
        kernel.fit_risk_slot(run, slot["slot_id"], lambda s: calls.append("reader"))
    ledger = kernel.prior.readj(run / "FIT_LEDGER.json")
    assert calls == [] and number == 3
    assert ledger["events"][0]["status"] == "FAILED"
    assert ledger["reserved"] == slot["reservation"]
    with pytest.raises(kernel.ExecutionBlocked, match="NO_RETRY"):
        kernel._reserve(original, slot["slot_id"])

def _synthetic_calendar_source(ready):
    """A test-only legal reader fixture, never a claim about actual shared data."""
    run, design = ready
    sessions = pd.bdate_range("2021-10-01", "2025-12-31").map(pd.Timestamp.isoformat).tolist()
    acceptance_path = Path(design["c_source_acceptance"]["path"])
    acceptance = kernel.prior.readj(acceptance_path)
    shared_path = Path(acceptance["shared_contract"]["path"])
    shared = kernel.prior.readj(shared_path)
    shared["accepted_sessions"] = sessions
    kernel.prior.putj(shared_path, shared)
    acceptance["shared_contract"]["sha256"] = kernel.prior.sha(shared_path)
    kernel.prior.putj(acceptance_path, acceptance)
    design["accepted_sessions"] = sessions
    design["c_source_acceptance"]["sha256"] = kernel.prior.sha(acceptance_path)
    reseal(run, design)
    return run, design


def _complete_synthetic_orchestration(ready, monkeypatch):
    """Drive existing kernel APIs. Head/evidence callbacks remain test-only.

    The real UID adapter and full-U projection run; every actual estimator fit
    is replaced explicitly with a counting stub, not a learned synthetic model.
    This cannot activate a real source, fill the missing production reader,
    or demonstrate that the absent production R3 head/evidence runner exists.
    """
    import hashlib
    import json
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import HistGradientBoostingRegressor

    run, design = _synthetic_calendar_source(ready)
    context = kernel.checked(run)
    calendar = pd.DatetimeIndex(design["accepted_sessions"])
    counts = dict(reader=0, risk=0, risk_backend=0, scaler=0, ridge=0, hgb=0)
    trace, states, projections, head_outputs = [], {}, {}, {}
    active_head = {}

    def reserved(slot_id):
        ledger = kernel.prior.readj(run / "FIT_LEDGER.json")
        event = next(item for item in ledger["events"] if item["id"] == slot_id)
        assert event["status"] == "RESERVED" and event["attempt"] == 1
        assert not (run / "SYNTHETIC_EVIDENCE.json").exists()

    def authority(row, *, cutoff, decision_at, **clock):
        if clock.get("proof_kind") == "CUTOFF_KNOWN_UNIVERSE":
            return isinstance(row, pd.DataFrame) and row.security_uid.tolist() == ["UID:A", "UID:B", "UID:NEW"]
        return (row["source_hash"] == "a" * 64 and row["return_unit"] == kernel.features.UNIT
                and row["signal_date"] < cutoff and row["available_at"] < decision_at)

    def reader(slot):
        reserved(slot["slot_id"])
        counts["reader"] += 1
        cutoff = pd.Timestamp(slot["cutoff"])
        past = calendar[calendar < cutoff][-64:]
        rows = []
        for uid, selected in (("UID:A", past), ("UID:B", past[-20:])):
            for i, day in enumerate(selected):
                rows.append(dict(signal_date=day, security_uid=uid, ticker=uid.removeprefix("UID:"),
                    identity_epoch="SYNTHETIC_E0", source_hash="a" * 64,
                    available_at=day.tz_localize("America/New_York") + pd.Timedelta(hours=16),
                    return_unit=kernel.features.UNIT, ret_1d=(i % 7 - 3) * .001,
                    predecessor_uid=uid, predecessor_date=selected[i-1] if i else pd.NaT))
        universe = pd.DataFrame(dict(security_uid=["UID:A", "UID:B", "UID:NEW"],
                                     ticker=["A", "B", "NEW"]))
        decision = cutoff.tz_localize("America/New_York")
        if slot["cadence"] == "MONTHLY":
            decision += pd.Timedelta(hours=9, minutes=30)
        return dict(history=pd.DataFrame(rows), universe=universe,
            accepted_sessions=design["accepted_sessions"], decision_at=decision,
            source_authority=authority, source_id="SYNTHETIC_SOURCE", source_proof_sha256="a" * 64)

    def fit_stub(method, table, market, params, timeout):
        counts["risk"] += 1
        counts["risk_backend"] += kernel.METHOD_CHARGES[method][0]
        assert market is None and timeout == 1800 and table.columns.tolist() == ["UID:A", "UID:B", "UID:NEW"]
        assert table.shape[0] == 63 and table["UID:A"].notna().sum() == 63
        assert table["UID:B"].notna().sum() < 30 and table["UID:NEW"].isna().all()
        assert table.index.max() < pd.Timestamp(params["fit_cutoff"]) < pd.Timestamp("2026-01-01")
        # Constant fixture covariance: no sample moments/covariance are computed.
        return SimpleNamespace(status="FITTED", method_id=method,
            estimated_assets=("UID:A",), covariance=np.array([[.0001]]),
            fallback_variance=.0004, specification=params)

    def scaler_fit(self, x, y=None, sample_weight=None):
        reserved(active_head["id"])
        counts["scaler"] += 1
        assert np.isfinite(x).all() and len(x) == len(sample_weight)
        self.synthetic_features = x.shape[1]
        return self

    def scaler_transform(self, x):
        assert x.shape[1] == self.synthetic_features
        return np.asarray(x, dtype=float)

    def model_fit(self, x, y, sample_weight=None):
        reserved(active_head["id"])
        name = "hgb" if isinstance(self, HistGradientBoostingRegressor) else "ridge"
        counts[name] += 1
        assert np.isfinite(x).all() and np.isfinite(y).all()
        self.synthetic_features = x.shape[1]
        return self

    def model_predict(self, x):
        assert x.shape[1] == self.synthetic_features
        # Fixed output independent of synthetic targets; no learned parameters.
        return np.full(len(x), .0125)

    monkeypatch.setattr(kernel.old, "bounded_risk_fit", fit_stub)
    monkeypatch.setattr(StandardScaler, "fit", scaler_fit)
    monkeypatch.setattr(StandardScaler, "transform", scaler_transform)
    for cls in (Ridge, HistGradientBoostingRegressor):
        monkeypatch.setattr(cls, "fit", model_fit)
        monkeypatch.setattr(cls, "predict", model_predict)

    # All 260 risk calls use the actual thin input adapter, identity qualifier,
    # durable reservation owner and established full-U projection.
    for slot in context["slots"]:
        if slot["kind"] != "RISK":
            continue
        bundle, coverage, metadata = kernel.fit_risk_slot(run, slot["slot_id"], reader)
        assert metadata["status"] == "UID_PANEL_QUALIFIED" and metadata["source_accepted"] is False
        assert metadata["full_U_t_preserved"] and coverage.security_uid.tolist() == ["UID:A", "UID:B", "UID:NEW"]
        projected = kernel.project_full_pool(bundle, ["UID:A", "UID:B", "UID:NEW"])
        assert projected.shape == (3, 3) and projected[:, 2].tolist() == [0., 1., 1.]
        states[slot["slot_id"]] = metadata["returns_sha256"]
        projections[slot["slot_id"]] = projected
        trace.append((slot["slot_id"], metadata["returns_sha256"]))

    def head_callback(slot):
        reserved(slot["slot_id"])
        active_head["id"] = slot["slot_id"]
        reference = slot["role"] in kernel.REFERENCES
        assert slot["reference_only"] is reference and slot["candidate"] is (not reference)
        # The test-only head bank uses only an earlier year's fixed risk states.
        cadence = "ANNUAL" if reference else "MONTHLY"
        dependencies = [item for item in context["slots"] if item["kind"] == "RISK"
            and item["cadence"] == cadence and pd.Timestamp(item["cutoff"]).year == slot["year"]-1]
        assert len(dependencies) == (5 if reference else 60)
        assert all(item["slot_id"] in states and pd.Timestamp(item["cutoff"]) < pd.Timestamp(f"{slot['year']}-01-01")
                   for item in dependencies)
        projected = np.concatenate([projections[item["slot_id"]] for item in dependencies[:5]], axis=1)
        risk_values = projected[:, 2::3] if "FLAG_ONLY" in slot["role"] else projected
        # Five fixed calibrated-member placeholders: no base/calibration loads or fits.
        x = np.column_stack((np.full((3, 5), .01), risk_values))
        y, weights = np.full(3, .015), np.ones(3)
        scaler = StandardScaler().fit(x, sample_weight=weights)
        model = (Ridge(alpha=100.) if slot["head_backend"] == "Ridge"
                 else HistGradientBoostingRegressor(max_iter=64, max_depth=3, max_leaf_nodes=15,
                     min_samples_leaf=100, learning_rate=.05, l2_regularization=1.,
                     early_stopping=False, random_state=20260928))
        model.fit(scaler.transform(x), y, sample_weight=weights)
        score = model.predict(scaler.transform(x))
        head_outputs[slot["slot_id"]] = score.tolist()
        trace.append((slot["slot_id"], score.tolist()))
        return score

    for slot in context["slots"]:
        if slot["kind"] == "ANNUAL_HEAD":
            kernel.execute(run, slot["slot_id"], head_callback)
    ledger = kernel.prior.readj(run / "FIT_LEDGER.json")
    controls = set(kernel.CONTROLS)
    assert ledger["reserved"] == {name: value for name, value in CAPS.items() if name not in controls}
    assert len(ledger["events"]) == 278 and all(event["status"] == "SUCCEEDED" for event in ledger["events"])
    assert counts == dict(reader=260, risk=260, risk_backend=156, scaler=18, ridge=9, hgb=9)
    assert counts["risk_backend"] + counts["scaler"] + counts["ridge"] + counts["hgb"] == 192
    assert len(head_outputs) == 18 and len(states) == 260
    evidence = dict(synthetic_only=True, interpretation="MECHANICAL_ORCHESTRATION_NOT_ECONOMIC_EVIDENCE",
        candidate_roles=list(kernel.preflight.ROLES), fixed_references=list(kernel.REFERENCES),
        scientific_candidate_count=4, head_outputs=head_outputs, counts=counts,
        attempt_slots=278, backend_stub_calls=192, monthly_state_slots=240, annual_state_slots=20,
        reserved_caps=ledger["reserved"], candidate_head_year_slots=12, reference_head_year_slots=6,
        fixed_seed=20260928, configs_per_role=1, retries_per_scientific_slot=0,
        synthetic_base_member_ids=["ridge", "hgb", "xgb_rank", "logistic", "cat_uncertainty"],
        actual_real_fit_calls=0, actual_real_covariance_estimates=0, actual_outcome_rows_read=0,
        actual_real_account_replays=0, actual_provider_fetches=0, actual_E_F_reads=0,
        actual_real2026_market_economic_reads=0, actual_model_loads=0,
        deterministic_trace_sha256=hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest(),
        production_source_reader_integrated=False, production_r3_head_runner_integrated=False,
        production_evidence_runner_integrated=False)
    kernel.prior.putj(run / "SYNTHETIC_EVIDENCE.json", evidence)
    denied = []
    with pytest.raises(kernel.ExecutionBlocked, match="NO_RETRY"):
        kernel.execute(run, context["slots"][-1]["slot_id"], lambda slot: denied.append(slot))
    assert denied == [] and kernel.prior.readj(run / "FIT_LEDGER.json")["reserved"] == ledger["reserved"]
    return evidence


def test_full_278_slot_synthetic_orchestration_twice_is_deterministic(ready_run, tmp_path, monkeypatch):
    first = _complete_synthetic_orchestration(ready_run, monkeypatch)
    second_root = tmp_path / "second"
    second_root.mkdir()
    second = _complete_synthetic_orchestration(globals()["ready_run"].__wrapped__(second_root), monkeypatch)
    assert first == second
    kernel.prior.putj(tmp_path / "C_RUNNER_DRYRUN_OBSERVED.json", dict(
        status="PASS_SYNTHETIC_COMPLETE_ORCHESTRATION", repeat_count=2,
        first=first, second=second, actual_real_fit_calls=0, actual_real_covariance_estimates=0))


def _synthetic_reviewed_dependencies(ready, dependencies):
    """Produce only cache-owned synthetic correction/review fixtures."""
    run, design = ready
    sources = [Path(dependency).resolve() for dependency in dependencies]
    snapshots = {}
    for number, current in enumerate(sources):
        snapshot = run / f"SYNTHETIC_ORIGINAL_DEPENDENCY_{number}.txt"
        snapshot.write_text(f"SYNTHETIC ORIGINAL DEPENDENCY {number}\n", encoding="utf-8")
        snapshots[current] = snapshot
    def mutate(dag):
        dag["research_id"] = "SYNTHETIC_C_R3"
        for pin in dag["source_pins"]:
            current = Path(pin["path"]).resolve()
            if current in snapshots:
                pin["sha256"] = kernel.prior.sha(snapshots[current])
    update_dag(run, design, mutate)
    design["research_id"] = "SYNTHETIC_C_R3"
    design["sources"] = {str(current): kernel.prior.sha(current) for current in sources}
    records = {}
    for number, current in enumerate(sources):
        snapshot = snapshots[current]
        original, actual = kernel.prior.sha(snapshot), kernel.prior.sha(current)
        review_path = run / f"SYNTHETIC_DEPENDENCY_REVIEW_{number}.json"
        review = dict(**metadata_fields("ENGINEERING_INDEPENDENT_REVIEW_METADATA"),
            status="PASS", classification="ENGINEERING_ONLY", source_path=str(current),
            original_source_sha256=original, corrected_source_sha256=actual,
            physical_dag_sha256=design["physical_dag"]["sha256"], research_id=design["research_id"])
        kernel.prior.putj(review_path, review)
        correction_path = run / f"SYNTHETIC_DEPENDENCY_CORRECTION_{number}.json"
        correction = dict(**metadata_fields("BUDGET_SOURCE_CORRECTION_METADATA"),
            schema="C_R3_BUDGET_SOURCE_CORRECTION_METADATA_V1", classification="ENGINEERING_ONLY",
            original_source=dict(path=str(current), sha256=original),
            corrected_source=dict(path=str(current), sha256=actual),
            original_snapshot=dict(path=str(snapshot), sha256=original),
            physical_dag_sha256=design["physical_dag"]["sha256"], research_id=design["research_id"],
            budget_and_scientific_parameters_changed=False,
            actual_execution=dict(fit_calls=0, covariance_estimates=0, outcome_rows_read=0),
            independent_review=descriptor(review_path, "ENGINEERING_INDEPENDENT_REVIEW_METADATA"))
        kernel.prior.putj(correction_path, correction)
        binding = descriptor(correction_path, "BUDGET_SOURCE_CORRECTION_METADATA")
        if current == Path(kernel.__file__).resolve():
            design["budget_source_correction"] = binding
        else:
            design.setdefault("budget_dependency_corrections", {})[str(current)] = binding
        records[current] = (correction_path, correction, review_path, review)
    reseal(run, design)
    return run, design, records


@pytest.mark.parametrize("dependencies", [
    ("preflight",), ("entry", "preflight")])
def test_reviewed_uid_dependency_and_entry_repairs_preserve_immutable_budget(ready_run, dependencies):
    paths = {"preflight": Path(kernel.preflight.__file__), "entry": Path(kernel.__file__)}
    run, design, _ = _synthetic_reviewed_dependencies(ready_run, [paths[key] for key in dependencies])
    frozen = design["physical_dag"]["sha256"]
    context = kernel.checked(run)
    assert len(context["slots"]) == 278 and context["caps"] == CAPS
    assert kernel.prior.sha(Path(design["physical_dag"]["path"])) == frozen
    slot = context["slots"][0]
    assert kernel.execute(run, slot["slot_id"], lambda reserved: "SYNTHETIC_STUB") == "SYNTHETIC_STUB"
    assert kernel.prior.readj(run / "FIT_LEDGER.json")["reserved"] == slot["reservation"]


@pytest.mark.parametrize("fault", ["missing", "missing_review", "unreviewed", "wrong_review_source",
    "design_source", "snapshot", "fit", "covariance", "science", "proof_scope"])
def test_uid_dependency_repair_cannot_bypass_review_or_fit_authority(ready_run, fault):
    current = Path(kernel.preflight.__file__).resolve()
    run, design, records = _synthetic_reviewed_dependencies(ready_run, [current])
    path, correction, review_path, review = records[current]
    if fault == "missing":
        del design["budget_dependency_corrections"]
    elif fault == "missing_review":
        del correction["independent_review"]
    elif fault == "unreviewed":
        review["status"] = "UNKNOWN"
    elif fault == "wrong_review_source":
        review["source_path"] = kernel.risk.__file__
    elif fault == "design_source":
        design["sources"][str(current)] = "f" * 64
    elif fault == "snapshot":
        correction["original_snapshot"]["sha256"] = "f" * 64
    elif fault == "fit":
        correction["actual_execution"]["fit_calls"] = 1
    elif fault == "covariance":
        correction["actual_execution"]["covariance_estimates"] = 1
    elif fault == "science":
        correction["budget_and_scientific_parameters_changed"] = True
    else:
        correction["observation_scope_end_exclusive"] = "2027-01-01"
    kernel.prior.putj(review_path, review)
    if "independent_review" in correction:
        correction["independent_review"]["sha256"] = kernel.prior.sha(review_path)
    kernel.prior.putj(path, correction)
    if "budget_dependency_corrections" in design:
        design["budget_dependency_corrections"][str(current)]["sha256"] = kernel.prior.sha(path)
    reseal(run, design)
    calls = []
    with pytest.raises((kernel.ExecutionBlocked, KeyError)):
        kernel.execute(run, "ANY", lambda slot: calls.append(slot))
    assert calls == [] and not (run / "FIT_LEDGER.json").exists()


@pytest.mark.parametrize("owner", ["risk", "features", "old"])
def test_other_dependencies_never_gain_source_correction_override(ready_run, owner):
    current = Path(getattr(kernel, owner).__file__).resolve()
    run, design, _ = _synthetic_reviewed_dependencies(ready_run, [current])
    calls = []
    with pytest.raises(kernel.ExecutionBlocked, match="CURRENT_SOURCE_PIN_CHANGED"):
        kernel.execute(run, "ANY", lambda slot: calls.append(slot))
    assert calls == [] and not (run / "FIT_LEDGER.json").exists()
    dag = kernel.prior.readj(Path(design["physical_dag"]["path"]))
    pins = {Path(item["path"]).resolve(): item["sha256"] for item in dag["source_pins"]}
    with pytest.raises(kernel.ExecutionBlocked, match="UNAPPROVED_SOURCE_CORRECTION_DEPENDENCY"):
        kernel._budget_source_correction(design, dag, pins, kernel.storage_paths.resolve(kernel.prior.REPO),
                                       run, dependency=current)



def frozen_history_ready(run, design):
    source_path=run/"SYNTHETIC_FROZEN_HISTORY_CONTRACT.json"
    authorization_path=run/"SYNTHETIC_HUMAN_AUTHORIZATION.json"
    kernel.prior.putj(authorization_path,{"synthetic":True})
    kernel.prior.putj(source_path,dict(**metadata_fields("C_FROZEN_HISTORY_SOURCE_AUTHORITY_METADATA"),
        schema_id="C_FROZEN_HISTORY_SOURCE_AUTHORITY_V1",source_policy=kernel.FH_MODE,
        research_id="SYNTHETIC_NEW_FROZEN_HISTORY_ID",source_id="SYNTHETIC_FROZEN_HISTORY",
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,
        historical_available_at_proved=False,historical_revision_vintage_proved=False,
        test2026_locked=True,base_calibration_refits_authorized=False,
        identity_policy=kernel.preflight.NO_CROSS_IDENTITY_STITCHING,
        return_coordinate=kernel.COORDINATE,return_unit=kernel.features.UNIT,
        return_horizon_sessions=1,accepted_sessions=design["accepted_sessions"],
        human_authorization_ref={"path":str(authorization_path),"sha256":kernel.prior.sha(authorization_path)}))
    design.update(research_id="SYNTHETIC_NEW_FROZEN_HISTORY_ID",source_contract_mode=kernel.FH_MODE,
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True,
        frozen_history_source=descriptor(source_path,"C_FROZEN_HISTORY_SOURCE_AUTHORITY_METADATA"),
        source_proof_sha256=kernel.prior.sha(source_path),
        execution_gates={key:True for key in kernel.FH_GATES})
    update_dag(run,design,lambda dag:dag.update(research_id=design["research_id"]))
    return source_path


def test_frozen_history_has_explicit_mechanism_qualification_not_strict(ready_run,monkeypatch):
    run,design=ready_run
    # Synthetic authorization is classified explicitly, wholly in external cache.
    frozen_history_ready(run,design)
    context=kernel.checked(run)
    assert context["authority_mode"]==kernel.FH_MODE
    assert "availability_qualified" not in design["execution_gates"]


@pytest.mark.parametrize("field,value",[("mechanism_research_eligible",False),
    ("strict_PIT_promotion_eligible",True),("test2026_locked",False)])
def test_frozen_history_eligibility_is_hard_gate(ready_run,field,value):
    run,design=ready_run
    frozen_history_ready(run,design)
    design[field]=value
    reseal(run,design)
    with pytest.raises(kernel.ExecutionBlocked,match="FROZEN_HISTORY_ELIGIBILITY_CHANGED"):
        kernel.checked(run)


def test_production_reader_bank_projection_and_head_recipe_integrate_without_real_fits(ready_run,monkeypatch):
    """Actual reader/qualifier/persistence/projection; estimator fits are spies."""
    from scripts.research.a2.data import selector_frozen_history as source
    from scripts.research.a2.training import selector_frozen_history_risk as production
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    run,design=ready_run
    sessions=pd.bdate_range("2021-10-01","2025-12-31")
    records=[{"signal_date":day,"ticker":ticker,"ret_1d":.001,
              "cusip":("333333333" if ticker=="A" and day>=pd.Timestamp("2023-01-03")
                       else "111111111" if ticker=="A" else "222222222")}
             for day in sessions for ticker in ("A","B")]
    frame=pd.DataFrame(records)
    inputs={}
    for kind,columns in source.PROJECTIONS.items():
        path=run/f"SYNTHETIC_{kind}.parquet"
        frame[columns].to_parquet(path,index=False)
        inputs[kind]={"path":str(path),"sha256":kernel.prior.sha(path)}
    authorization=run/"SYNTHETIC_AUTHORIZATION.json"
    kernel.prior.putj(authorization,{"synthetic":True})
    contract=source.build_source_contract(inputs,research_id=source.RESEARCH_ID,
        human_authorization_ref={"path":str(authorization),"sha256":kernel.prior.sha(authorization)})
    contract_path=run/"SYNTHETIC_FROZEN_HISTORY.json"
    kernel.prior.putj(contract_path,contract)
    design.update(research_id=source.RESEARCH_ID,source_contract_mode=kernel.FH_MODE,
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True,
        frozen_history_source=descriptor(contract_path,"C_FROZEN_HISTORY_SOURCE_AUTHORITY_METADATA"),
        source_proof_sha256=kernel.prior.sha(contract_path),accepted_sessions=contract["accepted_sessions"],
        execution_gates={key:True for key in kernel.FH_GATES},
        sources={str(Path(production.__file__).resolve()):kernel.prior.sha(production.__file__)})
    update_dag(run,design,lambda dag:dag.update(research_id=source.RESEARCH_ID))
    def synthetic_output(run,relative):
        path=Path(run)/relative
        kernel.storage_paths.assert_safe_output_path(path,kind="cache")
        path.parent.mkdir(parents=True,exist_ok=True)
        return path
    monkeypatch.setattr(production,"output",synthetic_output)
    context=kernel.checked(run)
    selected=[slot for slot in context["slots"] if slot["kind"]=="RISK" and
              slot["cutoff_ref"] in ("FIRST_ACCEPTED_SESSION:2023-01","2023-01-01T00:00:00")]
    monkeypatch.setattr(production,"checked",lambda run:({**context,"slots":selected},design))
    calls=[]
    def synthetic_fit(method,panel,market,params,timeout):
        calls.append((method,params["fit_cutoff"]))
        known=tuple(panel.columns[panel.notna().sum()>=30])
        assert len(known)==2 and panel.shape[0]==63
        return SimpleNamespace(status="FITTED",method_id=method,estimated_assets=known,
            covariance=np.eye(len(known))*.0004,fallback_variance=.0004,budget={"synthetic":True})
    monkeypatch.setattr(kernel.old,"bounded_risk_fit",synthetic_fit)
    reader=source.FrozenHistoryReader(contract_path,kernel.prior.sha(contract_path))
    production.risk_bank(run,reader)
    ledger=kernel.prior.readj(run/"FIT_LEDGER.json")
    assert len(calls)==len(ledger["events"])==10
    assert all(event["status"]=="SUCCEEDED" for event in ledger["events"])
    for slot in selected:
        receipt_path,model_path=production.paths_for_risk(run,slot)
        receipt=kernel.prior.readj(receipt_path)
        assert receipt["model_sha256"]==kernel.prior.sha(model_path)
        assert receipt["strict_PIT_promotion_eligible"] is False
        assert receipt["universe_epochs"]
    current=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]*2),
        "security_uid":["CUSIP:333333333","CUSIP:222222222"],"ticker":["A","B"],
        "U_t_fingerprint":["U","U"],"target":[.1,.2],
        "label_end_date":pd.to_datetime(["2023-01-31"]*2),
        "source_kind":["CALIBRATED_OOF"]*2,"source_cutoff":pd.to_datetime(["2023-01-01"]*2)})
    current=current.sort_values(production.KEY).reset_index(drop=True)
    for member in production.old.MEMBERS:
        current[member+"__mu"]=.01
    production.projections(run,reader,{2023:current})
    joined=production.join_risk(run,current,2023,"MONTHLY")
    assert len(joined)==2 and joined.loc[joined.ticker.eq("A"),"DIAG__unknown_flag"].iloc[0]==1
    assert joined.loc[joined.ticker.eq("B"),"DIAG__unknown_flag"].iloc[0]==0
    history=current.copy()
    history["signal_date"]=pd.Timestamp("2022-12-01")
    history["label_end_date"]=pd.Timestamp("2022-12-28")
    history["source_cutoff"]=pd.Timestamp("2022-01-01")
    for column in production.head_columns("MONTHLY_FIXED_CORE_RIDGE"):
        history[column]=.02
    order=[]
    monkeypatch.setattr(StandardScaler,"fit",lambda self,x,**kw:order.append("scaler_fit") or self)
    monkeypatch.setattr(StandardScaler,"transform",lambda self,x:x)
    monkeypatch.setattr(Ridge,"fit",lambda self,x,y,**kw:order.append("ridge_fit") or self)
    monkeypatch.setattr(Ridge,"predict",lambda self,x:np.zeros(len(x)))
    cal=SimpleNamespace(sample=lambda h:order.append("sample") or h,
        date_weights=lambda d:np.ones(len(d)))
    values,model,receipt=production.fit_head_arrays("MONTHLY_FIXED_CORE_RIDGE",history,joined,
        pd.Timestamp("2023-01-01"),cal)
    assert order==["sample","scaler_fit","ridge_fit"]
    assert values.shape==(2,) and receipt["max_train_label_end"]<"2023-01-01"
    assert receipt["actual_backend_fit_calls"]==2 # two mocked, zero real fits
