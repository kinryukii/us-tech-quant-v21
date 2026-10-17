"""New evaluation scope only; no actual 2026 inputs, models or accounts."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import base_conditioned_gross_eval as evaluation
from scripts.research.a2.training import base_conditioned_gross as gross
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision


def trained_bundle():
    return dict(status="SIX_GROSS_MODELS_TRAINED", models=[dict(base=base, learner=learner,
        status="TRAINED", model_ref=dict(path=base + learner, sha256="a" * 64))
        for base in evaluation.BASES for learner in ("linear", "tree", "neural")])


def test_only_complete_six_ordered_states_release():
    assert tuple(evaluation.gross_model_refs(trained_bundle())) == evaluation.LEARNED_IDS
    bundle = trained_bundle()
    bundle["models"][0]["status"] = "FAILED"
    with pytest.raises(ValueError, match="EXACT_SIX_TRAINED"):
        evaluation.gross_model_refs(bundle)
    bundle["status"] = "SIX_FIXED_ARMS_ATTEMPTED_WITH_PRESERVED_FAILURES"
    with pytest.raises(ValueError, match="ALL_SIX_MODELS"):
        evaluation.gross_model_refs(bundle)


def test_draft_release_rejected_before_bootstrap_or_numeric(monkeypatch):
    from scripts.research.a2.evaluation import base_conditioned_gross_runtime as runtime
    monkeypatch.setattr(evaluation, "document", lambda ref: {"status": "DRAFT"})
    monkeypatch.setattr(runtime, "bootstrap", lambda *a, **k: pytest.fail("bootstrap must not run"))
    with pytest.raises(ValueError, match="ROOT_STAGE_RELEASE"):
        evaluation.startup({}, {}, "prepare")


def context(cid, day="2026-01-02"):
    return SimpleNamespace(path_ids=(cid,), signal_date=pd.Timestamp(day),
        tickers=np.array(["A", "B", "C"], dtype=object), current_units=np.array([[2., 0., 5.]]),
        decision_mask=np.array([[True, True, True]]), reserved_mask=np.array([[False, False, True]]),
        sell_restricted=np.array([[False, False, False]]))


def test_fixed_decoder_uses_same_code_and_preserves_hold_cash_and_state_isolation(monkeypatch):
    calls = []
    def learned(model, reference, previous):
        calls.append((model, previous))
        return .25
    monkeypatch.setattr(gross, "predict_gross", learned)
    owner_fn = gross.predict_gross
    base_calls = []
    def base(di, ctx):
        base_calls.append(ctx.path_ids)
        return TargetDecision(np.array([[0., .8, 0.]]), explicit_mask=np.array([[False, True, True]]))
    inputs = lambda *args: (np.ones((3, 32)), np.ones(3))
    fixed_id, learned_id = evaluation.IDS[-1], evaluation.LEARNED_IDS[0]
    fixed = evaluation.make_gross_overlay({"candidate_id": fixed_id}, base, evaluation._FIXED_HALF, inputs)
    trained = evaluation.make_gross_overlay({"candidate_id": learned_id}, base, object(), inputs)
    assert fixed.__call__.__code__ is gross.BaseConditionedGrossOverlay.__call__.__code__
    half = fixed(0, context(fixed_id))
    quarter = trained(0, context(learned_id))
    assert np.array_equal(half.explicit_mask, [[False, True, False]])
    assert half.weights[0, 1] == .4
    assert quarter.weights[0, 1] == .2
    assert calls[0][1] == 1.
    assert gross.predict_gross is owner_fn
    assert fixed.previous == {fixed_id: .5}
    assert trained.previous == {learned_id: .25}
    new_window = evaluation.make_gross_overlay({"candidate_id": fixed_id}, base, evaluation._FIXED_HALF, inputs)
    assert new_window.previous == {fixed_id: 1.}
    assert base_calls == [(fixed_id,), (learned_id,)]


def test_missing_learned_model_cannot_fall_back_to_fixed():
    with pytest.raises(ValueError, match="EXACT_FIXED_OR_LEARNED"):
        evaluation.make_gross_overlay({"candidate_id": evaluation.IDS[0]}, None, evaluation._FIXED_HALF, None)


def schedule_fixture(monkeypatch, *, source_ready=True):
    from scripts.research.a2.evaluation import stateful_frozen_six_path as owner
    from scripts.research.a2.evaluation import frozen_test_authority as authority
    windows = [dict(window_id="MAIN" if i == 0 else f"RANDOM_{i:03d}",
        start="2026-01-02", end="2026-01-05", first_execution_date="2026-01-05") for i in range(101)]
    candidates = [dict(candidate_id=cid) for cid in evaluation.IDS]
    release = dict(windows=windows, candidate_bindings=[dict(specification=c) for c in candidates],
                   native_descriptive_metrics_allowed=source_ready)
    calls, metrics = [], []
    def executor(candidate, data, admitted):
        calls.append((admitted.window_id, candidate["candidate_id"]))
        if admitted.window_id == "RANDOM_002" and candidate["candidate_id"] == evaluation.IDS[3]:
            raise RuntimeError("synthetic account failure")
        return {"synthetic": True}
    monkeypatch.setattr(authority, "load_descriptive_authority", lambda value: value)
    monkeypatch.setattr(owner, "_qualification", lambda frames: dict(groups={"accounting": True}, all_passed=True))
    def original_metrics(candidate, frames):
        metrics.append(candidate["candidate_id"])
        return {"owner_metric": True}
    monkeypatch.setattr(owner, "descriptive_metrics", original_metrics)
    durable = evaluation.durable_runner(release, path_executor=executor)
    assert durable.__code__ is owner.execute_durable.__code__
    assert durable.__globals__["MAX_PATHS"] == 808
    schedule = dict(task_id=evaluation.TASK, path_ids=list(evaluation.IDS), windows=windows, account_paths=808)
    def admission(window):
        return SimpleNamespace(task_id=evaluation.TASK, window_id=window["window_id"],
                               start=pd.Timestamp(window["start"]), end=pd.Timestamp(window["end"]))
    inputs_called = []
    def inputs(window, admitted):
        inputs_called.append(window["window_id"])
        data = {"market": SimpleNamespace(dates=pd.DatetimeIndex([admitted.start, admitted.end]),
                                           signal_mask=np.array([True, True]))}
        return {"stocks": data, **{cid: data for cid in evaluation.IDS}}
    return durable.__globals__["execute_schedule"], schedule, candidates, admission, inputs, calls, metrics, inputs_called


def test_all_808_slots_keep_failure_and_resume_without_reexecution(monkeypatch):
    runner, schedule, candidates, admission, inputs, calls, metrics, input_calls = schedule_fixture(monkeypatch)
    events, stored = [], []
    reports = runner(schedule, candidates, authority_for_window=admission, inputs_for_window=inputs,
        record_event=lambda event: events.append(dict(event)),
        consume_result=lambda w, c, frames, report: stored.append(dict(report)))
    assert len(reports) == len(calls) == 808
    assert len(set(calls)) == 808
    assert len(stored) == len(metrics) == 807
    assert sum(r["status"] == "FAILED_ENGINEERING" for r in reports) == 1
    assert all(r["formal_primary_metrics"] is None for r in reports)
    assert all(r["matched_baselines_replayed"] is False for r in reports)
    assert len(input_calls) == 101
    assert calls[:8] == [("MAIN", cid) for cid in evaluation.IDS]
    resumed = runner(schedule, candidates, authority_for_window=admission, inputs_for_window=inputs,
        record_event=lambda event: pytest.fail("no new attempts"),
        consume_result=lambda *args: pytest.fail("no repeated result"), prior_events=events)
    assert resumed == [] and len(calls) == 808


def test_source_unqualified_never_computes_native_metrics_and_keeps_denominator(monkeypatch):
    runner, schedule, candidates, admission, inputs, calls, metrics, _ = schedule_fixture(monkeypatch, source_ready=False)
    reports = runner(schedule, candidates, authority_for_window=admission, inputs_for_window=inputs,
        record_event=lambda event: None, consume_result=lambda *args: None)
    assert len(reports) == 808 and metrics == []
    assert sum(r["status"] == "NOT_TESTABLE" for r in reports) == 807
    assert all(r["metrics"] is None for r in reports)


def test_partial_attempt_is_not_silently_retried_or_window_removed(monkeypatch):
    runner, schedule, candidates, admission, inputs, calls, _, _ = schedule_fixture(monkeypatch)
    pending = [dict(event="STARTED", window_id="MAIN", candidate_id=evaluation.IDS[0])]
    with pytest.raises(ValueError, match="OUTSTANDING_ATTEMPT_NO_RETRY"):
        runner(schedule, candidates, authority_for_window=admission, inputs_for_window=inputs,
            record_event=lambda event: None, consume_result=lambda *args: None, prior_events=pending)
    assert calls == []

def test_business_owners_require_exact_release_pins_before_inputs(monkeypatch):
    monkeypatch.setattr(evaluation, "OWNER_FILES", ("training/base_conditioned_gross_history.py",))
    ref = dict(path="source.py", sha256="a" * 64)
    monkeypatch.setattr(evaluation, "reference", lambda path: ref)
    manifest = dict(source_owner_refs={evaluation.OWNER_FILES[0]: ref}, feature_provider_owner_ref=ref)
    evaluation.validate_source_owners(manifest, dict(owner_refs={"history": ref}))
    with pytest.raises(ValueError, match="SOURCE_OWNER_NOT_RELEASED"):
        evaluation.validate_source_owners(manifest, dict(owner_refs={}))
    manifest["source_owner_refs"] = {}
    with pytest.raises(ValueError, match="SOURCE_OWNER_CHANGED"):
        evaluation.validate_source_owners(manifest, dict(owner_refs={"history": ref}))


def test_large_direct_metadata_streams_only_committed_roles(tmp_path, monkeypatch):
    import json
    from copy import deepcopy
    dates = ["2026-01-02", "2026-10-08"]
    roles = {role: dict(frame_ref=dict(path=role, sha256="a" * 64),
                       read_columns=["signal_date", "sample_id"], commitment=dict(rows=2),
                       computed_signal_dates=dates,
                       daily_sources=[dict(SENTINEL_FORBIDDEN_ECONOMIC_PAYLOAD="x" * 400_000)])
             for role in ("R10:ENTRY", "R10:INCUMBENT")}
    path = tmp_path / "DIRECT_ROLE_INPUTS.json"
    path.write_text(json.dumps(dict(task_id="A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1",
                                   new_fit=0, model_predict=0, account=0, roles=roles)), encoding="utf-8")
    ref = evaluation.reference(path)
    assert path.stat().st_size > 250_000
    real_loads = json.loads
    def metadata_only(raw, *args, **kwargs):
        assert "SENTINEL_FORBIDDEN_ECONOMIC_PAYLOAD" not in str(raw)
        return real_loads(raw, *args, **kwargs)
    monkeypatch.setattr(json, "loads", metadata_only)
    projected = evaluation.original_direct_roles(ref)
    assert set(projected) == set(roles)
    for role, item in projected.items():
        assert set(item) == {"frame_ref", "read_columns", "commitment", "full_frame_scope"}
        assert item["commitment"] == roles[role]["commitment"]
        assert item["full_frame_scope"] == dict(date_column="signal_date", start=dates[0], end=dates[-1],
                                                computed_signal_date_count=2)
    closure = dict(reused_direct_role_metadata_ref=ref, new_fit_count=0, account_replay=0,
                   outcome_columns_in_model_features=0, label_columns_decoded=0,
                   feature_frame_refs={role: item["frame_ref"] for role, item in projected.items()},
                   action_feature_inputs={role: dict(commitment=item["commitment"]) for role, item in projected.items()})
    monkeypatch.setattr(evaluation, "document", lambda ref: closure)
    manifest = dict(direct_role_metadata_ref=ref, original_input_closure_ref={}, direct_roles=projected)
    evaluation.validate_direct_roles(manifest)
    bad = deepcopy(manifest)
    bad["direct_roles"]["R10:ENTRY"]["commitment"]["rows"] = 1
    with pytest.raises(ValueError, match="COMPLETE_ROLE_METADATA_CHANGED"):
        evaluation.validate_direct_roles(bad)
    closure["action_feature_inputs"]["R10:INCUMBENT"]["commitment"] = dict(rows=1)
    with pytest.raises(ValueError, match="FULL_FRAME_COMMITMENT_BINDING"):
        evaluation.validate_direct_roles(manifest)


def test_account_catalog_bound_to_this_run_before_any_event_decode(tmp_path, monkeypatch):
    calls = []
    expected = tmp_path / "derived/gross_evaluation_sources/ACCOUNT_CATALOG.json"
    catalog = dict(task_id=evaluation.TASK, phase=evaluation.PHASE)
    def read(ref, *, limit):
        calls.append((ref, limit))
        return catalog
    monkeypatch.setattr(evaluation, "document", read)
    ref = dict(path=str(expected), sha256="a" * 64)
    assert evaluation.load_account_catalog(dict(account_catalog_ref=ref), tmp_path) is catalog
    assert calls == [(ref, 2_000_000)]
    with pytest.raises(ValueError, match="NEW_TASK_TYPED_ACCOUNT_CATALOG_REQUIRED"):
        evaluation.load_account_catalog(dict(account_catalog_ref=dict(path=str(tmp_path / "old2024.json"))), tmp_path)
    assert len(calls) == 1
    catalog["task_id"] = "OLD_TASK"
    with pytest.raises(ValueError, match="NEW_TASK_TYPED_ACCOUNT_CATALOG_SCOPE"):
        evaluation.load_account_catalog(dict(account_catalog_ref=ref), tmp_path)


@pytest.mark.parametrize("row_count", [1, 513])
def test_original_mechanism_sklearn_state_without_features_uses_native_width_gate(monkeypatch, row_count):
    import joblib
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from scripts.research.a2.inference import frozen_a94_actions as actions
    from scripts.research.a2.training import stateful_mechanism_models as native
    frames, roles, artifacts, model_refs = {}, {}, {}, {}
    source_pins = native.source_pins()
    for group in ("ENTRY", "INCUMBENT"):
        role = "R10:" + group
        features = actions.role_features(role)
        frame = pd.DataFrame([{**dict.fromkeys(features, 0.), features[0]: float(i), "signal_date": "2026-01-02",
                               "sample_id": "synthetic-" + group + str(i), "ticker": "SYNTH", "security_id": "SYNTH"}
                              for i in range(row_count)])
        frames[role] = frame
        roles[role] = dict(frame_ref=dict(path=role), read_columns=list(frame.columns),
            commitment=actions.input_commitment(frame, features, supported=np.ones(row_count, bool)),
            full_frame_scope=dict(start="2026-01-02", end="2026-10-08"))
        width = 2 * len(features)
        for base in evaluation.BASES:
            estimator = Ridge(alpha=10.)
            estimator.coef_, estimator.intercept_, estimator.n_features_in_ = np.zeros(width), .01, width
            estimator.coef_[0] = .0001
            model = native.MechanismModel(dict(family="Ridge"), estimator,
                dict(feature_shape=[width], classifier=False, source_pins=source_pins))
            scaler = StandardScaler()
            scaler.n_features_in_, scaler.mean_, scaler.scale_ = width, np.zeros(width), np.ones(width)
            mkey, skey = base + group + "-model", base + group + "-scaler"
            artifacts[mkey], artifacts[skey] = model, scaler
            model_refs.setdefault(base, {})[group] = dict(model_ref=dict(path=mkey), scaler_ref=dict(path=skey))
            assert not hasattr(model, "features") and not hasattr(estimator, "features")
    manifest = dict(direct_roles=roles, base_model_refs=model_refs)
    monkeypatch.setattr(evaluation, "_resource", lambda manifest: None)
    monkeypatch.setattr(evaluation, "verify", lambda ref: ref["path"])
    monkeypatch.setattr(joblib, "load", lambda key: artifacts[key])
    monkeypatch.setattr(native.values, "_native", lambda deps: None)
    bridge = SimpleNamespace(bounded_frame=lambda ref, *args: frames[ref["path"]].copy())
    from scripts.research.a2.inference import consensus_paper
    original_predict = consensus_paper.predict_r10
    predictions, record_batch_sizes = [], []
    def capture_predict(model, matrix):
        prediction = original_predict(model, matrix)
        predictions.append(prediction["mean"].copy())
        return prediction
    original_records = pd.DataFrame.to_dict
    def capture_records(frame, *args, **kwargs):
        if args == ("records",):
            record_batch_sizes.append(len(frame))
        return original_records(frame, *args, **kwargs)
    monkeypatch.setattr(consensus_paper, "predict_r10", capture_predict)
    monkeypatch.setattr(pd.DataFrame, "to_dict", capture_records)
    result = evaluation._base_predictions(manifest, bridge, "2026-01-02", "2026-10-08")
    assert max(record_batch_sizes) <= 256
    for index, base in enumerate(evaluation.BASES):
        rows = result[base][pd.Timestamp("2026-01-02")]
        assert len(rows) == 2 * row_count
        np.testing.assert_array_equal([row["source_score"] for row in rows],
                                      np.r_[predictions[index], predictions[index + 2]])
    first_scaler = artifacts[model_refs[evaluation.BASES[0]]["ENTRY"]["scaler_ref"]["path"]]
    first_scaler.n_features_in_ += 1
    with pytest.raises(ValueError, match="ORIGINAL_ROLE_ENCODER_AND_SCALER_WIDTH"):
        evaluation._base_predictions(manifest, bridge, "2026-01-02", "2026-10-08")


def test_reference_accepts_same_physical_path_representation_and_rejects_changed_identity(tmp_path):
    path = tmp_path / "synthetic_metadata.json"
    path.write_text("{}", encoding="utf-8")
    ref = evaluation.reference(path)
    alternate = {**ref, "path": path.resolve().as_posix()}
    assert evaluation.verify(alternate).resolve() == path.resolve()
    with pytest.raises(ValueError, match="REFERENCE_CHANGED"):
        evaluation.verify({**alternate, "sha256": "0" * 64})
    with pytest.raises(ValueError, match="REFERENCE_CHANGED"):
        evaluation.verify({**alternate, "unexpected": True})


def test_prepare_budget_accounts_for_already_resident_memory_and_keeps_commit_floor():
    mib = 2**20
    budget = dict(peak_rss_ceiling_bytes=600*mib, peak_private_ceiling_bytes=2100*mib, max_stage_increment_bytes=130*mib)
    cold = evaluation._prepare_resource_requirements(budget, dict(rss=100*mib, private=1100*mib))
    warm = evaluation._prepare_resource_requirements(budget, dict(rss=400*mib, private=1500*mib))
    assert cold["physical_bytes"] == 756*mib
    assert warm["physical_bytes"] == 456*mib
    assert cold["commit_bytes"] == warm["commit_bytes"] == 8*2**30
    near_peak = evaluation._prepare_resource_requirements(budget, dict(rss=599*mib, private=1500*mib))
    assert near_peak["physical_bytes"] == 386*mib
    with pytest.raises(ValueError, match="CALIBRATION_EXCEEDED"):
        evaluation._prepare_resource_requirements(budget, dict(rss=601*mib, private=1500*mib))
    with pytest.raises(ValueError, match="CALIBRATION_EXCEEDED"):
        evaluation._prepare_resource_requirements(budget, dict(rss=400*mib, private=2101*mib))


def test_account_keeps_original_resource_gate_even_when_prepare_budget_exists(monkeypatch):
    from scripts.research.a2.training import base_conditioned_gross_run
    calls = []
    monkeypatch.setattr(base_conditioned_gross_run, "resource_gate", lambda ref: calls.append(ref) or "ORIGINAL")
    monkeypatch.setattr(evaluation, "document", lambda ref: pytest.fail("account must not decode prepare budget"))
    manifest = dict(resource_owner_ref={"path": "synthetic-owner"}, prepare_memory_budget_ref={"path": "unused"})
    assert evaluation._resource(manifest, prepare=False) == "ORIGINAL"
    assert calls == [manifest["resource_owner_ref"]]
