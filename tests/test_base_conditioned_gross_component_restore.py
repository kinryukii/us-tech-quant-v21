"""Synthetic deleted-component restoration: no real model/data loading."""
import ast
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import base_conditioned_gross_oof as base
from scripts.research.a2.training import stateful_mechanism_models as models


class IdentityScaler:
    def __init__(self, offset=0.):
        self.offset = offset
    def transform(self, x):
        return np.asarray(x) + self.offset


def digest_array(x):
    return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def identity(x, dates, weights, target):
    return dict(x_sha256=digest_array(x), dates_sha256=digest_array(dates),
        weights_sha256=digest_array(weights), target_sha256=digest_array(np.asarray(target, float)),
        x_shape=list(x.shape), target_shape=list(target.shape), features=["a", "missing_a"])


@pytest.fixture
def recovery():
    # Compile the unchanged commitment owner without executing its source I/O.
    p = Path("D:/us-tech-quant-cache/_maintenance/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/missing_nodes/prepare_r10_recovery_inputs.py")
    tree = ast.parse(p.read_text(encoding="utf-8"))
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("check_commitments", "save_array")]
    scope = dict(np=np, array_hash=digest_array, reference=base.reference)
    exec(compile(ast.Module(body=fns, type_ignores=[]), str(p), "exec"), scope)
    return SimpleNamespace(check_commitments=scope["check_commitments"], array_hash=digest_array, save_array=scope["save_array"])


@pytest.fixture
def restore_case(tmp_path, monkeypatch, recovery):
    out = tmp_path / "restore"
    out.mkdir()
    release_ref = dict(path="synthetic_release", sha256="synthetic")
    def put(path, value, roots):
        assert path.resolve().is_relative_to(tmp_path.resolve())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(base, "put", put)
    @contextmanager
    def helpers(_):
        yield None, recovery, SimpleNamespace(memory=lambda:dict(physical_gib=4., page_gib=32.))
    monkeypatch.setattr(base, "helpers", helpers)
    records, inputs = {}, {}
    nodes = {g:{"elasticnet_model_ref":dict(path="synthetic_en_"+g, sha256="unchanged")} for g in base.GROUPS}
    for group in base.GROUPS:
        for horizon, n in (("HMEAN", 2), ("H5", 3)):
            slot = f"ACTION_VALUE_{group}_{horizon}_2024_SCALER"
            raw = np.arange(n*2, dtype=float).reshape(n, 2)
            raw[0, 0] = np.nan
            dates = np.array(["2023-11-01"]*n, dtype="datetime64[ns]")
            weights = np.ones(n)
            target = np.arange(n, dtype=float) + 1
            scaler_id = identity(raw, dates, weights, np.zeros(n))
            model_id = identity(np.nan_to_num(raw, nan=0.), dates, weights, target)
            arrays = {}
            for key, value in dict(x=raw, dates=dates, weights=weights, target=target).items():
                path = out / (slot+"_"+key+".npy")
                np.save(path, value, allow_pickle=False)
                arrays[key] = dict(base.reference(path), shape=list(value.shape))
            inputs[slot] = dict(arrays=arrays, features=scaler_id["features"],
                signal_max="2023-11-01", maturity_max="2023-11-30",
                scaler_identity=scaler_id, model_identity=model_id)
            role = "elasticnet_scaler_ref" if horizon == "HMEAN" else "ridge_scaler_ref"
            records[slot] = dict(group=group, horizon=horizon, kind="scalers", role=role,
                receipt_ref=dict(path="synthetic_receipt_"+slot, sha256="original"),
                identity=scaler_id, original_model_ref=dict(path="deleted_"+slot, sha256="original"),
                en_identity=model_id)
            if horizon == "H5":
                ridge = f"ACTION_VALUE_{group}_H5_2024_ridge_MID_20260928"
                records[ridge] = dict(group=group, horizon=horizon, kind="ridge", role="ridge_model_ref",
                    receipt_ref=dict(path="synthetic_receipt_"+ridge, sha256="original"),
                    identity=model_id, original_model_ref=dict(path="deleted_"+ridge, sha256="original"),
                    receipt=dict(slot_id=ridge, family="ridge", capacity="MID", seed=20260928,
                        group=group, horizon=5, year=2024, bucket="ACTION_VALUE", objective="advantage",
                        cutoff_exclusive=base.FIT_CUTOFF))
    put(out/"PREPARATION.json", dict(status="PREPARED", release_ref=release_ref, inputs=inputs), None)
    bundle_path, design_path = tmp_path/"bundle.json", tmp_path/"design.json"
    put(bundle_path, dict(status="MODELS_READY_PENDING_CONSENSUS_APPLICATION", nodes=nodes), None)
    put(design_path, dict(dependency_paths=[]), None)
    release = dict(permits=dict(prepare=True, fit=True), original_model_bundle_ref=base.reference(bundle_path))
    old_release = dict(original_design_ref=base.reference(design_path), current_execution_source_pins={})
    calls = []
    def fit_scaler(x, payload, on_fit_started):
        on_fit_started("synthetic_scaler")
        calls.append(("scaler", len(x)))
        return IdentityScaler(), dict(actual_fit_count=1)
    def fit_ridge(slot, x, payload, dependencies, on_fit_started):
        on_fit_started("synthetic_ridge")
        calls.append(("ridge", len(x)))
        return dict(synthetic_model=slot), dict(actual_fit_count=1, parameters=dict(alpha=10, solver="auto"))
    monkeypatch.setattr(models, "fit_weighted_scaler", fit_scaler)
    monkeypatch.setattr(models, "fit", fit_ridge)
    monkeypatch.setattr(models, "parameters", lambda *args:dict(alpha=10, solver="auto"))
    return SimpleNamespace(out=out, release=release, old_release=old_release, records=records,
        release_ref=release_ref, calls=calls, inputs=inputs, put=put)


def run_fit(c):
    return base.component_fit(c.release, c.old_release, None, c.out, c.records, c.release_ref)


def test_distinct_original_cohort_dispatch_and_strict_maturity(recovery):
    def frame(n, mature="2023-12-29"):
        return pd.DataFrame(dict(signal_date=pd.to_datetime(["2023-11-29"]*n),
            label_mature_date=pd.to_datetime([mature]*n), target=np.arange(n, dtype=float)))
    mean, h5 = {g:frame(2) for g in base.GROUPS}, {g:frame(3) for g in base.GROUPS}
    calls = []
    original = SimpleNamespace(SINGLE=("a",), PAIR=("e_a",),
        structured_action_frame=lambda frames, h:(calls.append(h) or h5),
        mature_train=lambda f, cutoff:f, role_weights=lambda f:np.ones(len(f)),
        encode=lambda f, columns:(np.ones((len(f), 2)), ("a", "missing_a")))
    recovery.frame_for_recovery = lambda bundle:mean
    bundle = SimpleNamespace(frames=object())
    a = base.component_training_input(bundle, "ENTRY", "HMEAN", original, recovery)
    b = base.component_training_input(bundle, "ENTRY", "H5", original, recovery)
    assert len(a["target"]) == 2 and len(b["target"]) == 3 and calls == [5]
    h5["ENTRY"] = frame(3, "2024-01-01")
    with pytest.raises(ValueError, match="COMPONENT_MATURE_PRE2024"):
        base.component_training_input(bundle, "ENTRY", "H5", original, recovery)


def test_four_scalers_then_two_ridge_and_resume_no_new_fit(restore_case):
    c = restore_case
    result = run_fit(c)
    assert c.calls == [("scaler", 2), ("scaler", 3), ("scaler", 2), ("scaler", 3), ("ridge", 3), ("ridge", 3)]
    assert result["physical_restoration_fits"] == dict(scalers=4, ridge=2, elasticnet=0)
    assert all(result["nodes"][g]["elasticnet_model_ref"]["sha256"] == "unchanged" for g in base.GROUPS)
    run_fit(c)
    assert len(c.calls) == 6


def test_all_raw_targets_checked_before_first_fit(restore_case):
    c = restore_case
    slot = "ACTION_VALUE_INCUMBENT_H5_2024_SCALER"
    data = c.inputs[slot]
    p = Path(data["arrays"]["target"]["path"])
    np.save(p, np.array([1., 2., 999.]), allow_pickle=False)
    data["arrays"]["target"].update(base.reference(p))
    c.put(c.out/"PREPARATION.json", dict(status="PREPARED", release_ref=c.release_ref, inputs=c.inputs), None)
    with pytest.raises(ValueError, match="COMPONENT_MODEL_TARGET"):
        run_fit(c)
    assert c.calls == []


def test_prepared_identity_cannot_replace_original(restore_case):
    c = restore_case
    c.inputs["ACTION_VALUE_ENTRY_HMEAN_2024_SCALER"]["model_identity"] = dict(tampered=True)
    c.put(c.out/"PREPARATION.json", dict(status="PREPARED", release_ref=c.release_ref, inputs=c.inputs), None)
    with pytest.raises(ValueError, match="COMPONENT_PREPARED_IDENTITY"):
        run_fit(c)
    assert c.calls == []


def test_transform_mismatch_preserves_four_actual_fits_and_blocks_ridge(restore_case, monkeypatch):
    c = restore_case
    def bad_scaler(x, payload, on_fit_started):
        on_fit_started("synthetic_scaler")
        c.calls.append(("scaler", len(x)))
        return IdentityScaler(1.), dict(actual_fit_count=1)
    monkeypatch.setattr(models, "fit_weighted_scaler", bad_scaler)
    with pytest.raises(ValueError, match="ORIGINAL_COMMITMENT_MISMATCH:x_sha256"):
        run_fit(c)
    assert len(c.calls) == 4 and all(k == "scaler" for k, _ in c.calls)
    assert sum(json.loads(p.read_text())["fit_units"] for p in (c.out/"objects").glob("*/fit_receipt.json")) == 4
    with pytest.raises(ValueError, match="ORIGINAL_COMMITMENT_MISMATCH:x_sha256"):
        run_fit(c)
    assert len(c.calls) == 4


def test_failed_ridge_attempt_is_counted_and_not_refitted(restore_case, monkeypatch):
    c = restore_case
    def fail(slot, x, payload, dependencies, on_fit_started):
        on_fit_started("synthetic_ridge")
        c.calls.append(("ridge", len(x)))
        raise RuntimeError("synthetic_failure_after_start")
    monkeypatch.setattr(models, "fit", fail)
    with pytest.raises(RuntimeError, match="synthetic_failure_after_start"):
        run_fit(c)
    assert len(c.calls) == 5
    with pytest.raises(ValueError, match="FAILED_OR_INTERRUPTED_COMPONENT_PRESERVED"):
        run_fit(c)
    assert len(c.calls) == 5


def test_missing_execution_permit_rejects_before_input_or_fit(restore_case):
    c = restore_case
    c.release["permits"]["fit"] = False
    with pytest.raises(ValueError, match="COMPONENT_FIT_RELEASE_REQUIRED"):
        run_fit(c)
    c.release["permits"]["prepare"] = False
    with pytest.raises(ValueError, match="COMPONENT_PREPARE_RELEASE_REQUIRED"):
        base.component_prepare(c.release, c.old_release, None, c.out, c.records, c.release_ref)
    assert c.calls == []


def test_wrong_delta_cap_rejects_before_financial_input(monkeypatch):
    contract_ref, release_ref, delta_ref = {"id":"contract"}, {"id":"release"}, {"id":"delta"}
    driver_ref = {"id":"driver"}
    bundle_ref = {"id":"bundle"}
    contract = dict(research_id=base.TASK, historical_base_2024_fit_cutoff_exclusive=base.FIT_CUTOFF,
        controller_signal_and_label_maturity_cutoff_exclusive=base.CONTROL_CUTOFF,
        fit_budget=dict(base_scaler_refits=0, historical_EN_components=2))
    release = dict(task_id=base.TASK, schema="BASE_HISTORICAL_2024_COMPONENT_RESTORE_RELEASE_R1",
        status="ROOT_AUTHORIZED_COMPONENT_RESTORATION", contract_ref=contract_ref,
        driver_ref=driver_ref, recovery_delta_ref=delta_ref, original_model_bundle_ref=bundle_ref)
    delta = dict(schema="BASE_HISTORICAL_2024_COMPONENT_RESTORE_DELTA_R1", task_id=base.TASK,
        status="ROOT_AUTHORIZED_COMPONENT_RESTORATION", contract_ref=contract_ref,
        original_model_bundle_ref=bundle_ref, physical_fit_cap=dict(scalers=3, ridge=2, elasticnet=0),
        deleted_slots=list(base.COMPONENT_SLOTS))
    docs = {"contract":contract, "release":release, "delta":delta}
    monkeypatch.setattr(base, "document", lambda ref:docs[ref["id"]])
    monkeypatch.setattr(base, "reference", lambda path:driver_ref)
    monkeypatch.setattr(base, "physical", lambda ref:pytest.fail("physical access before cap"))
    with pytest.raises(ValueError, match="EXACT_COMPONENT_DELTA"):
        base.validate_component_restore(contract_ref, release_ref, "synthetic_run")



def test_zero_fit_engineering_failure_resumes_with_history(restore_case, monkeypatch):
    c = restore_case
    good = models.fit_weighted_scaler
    monkeypatch.setattr(models, "fit_weighted_scaler", lambda *args, **kwargs:(_ for _ in ()).throw(RuntimeError("before_fit_start")))
    with pytest.raises(RuntimeError, match="before_fit_start"):
        run_fit(c)
    rp = c.out/"objects/ACTION_VALUE_ENTRY_HMEAN_2024_SCALER/fit_receipt.json"
    assert json.loads(rp.read_text())["fit_units"] == 0 and c.calls == []
    monkeypatch.setattr(models, "fit_weighted_scaler", good)
    run_fit(c)
    row = json.loads(rp.read_text())
    assert row["fit_units"] == 1 and len(c.calls) == 6
    assert row["pre_fit_recovery_history"] == [dict(status="FAILED", error="RuntimeError:before_fit_start", fit_units=0)]


def test_zero_fit_preparation_failure_preserves_attempt_and_partial_arrays(restore_case, monkeypatch, recovery):
    from scripts.research.a2.training import stateful_mechanism_inputs as inputs
    c = restore_case
    old_path = c.out/"PREPARATION.json"
    saved = dict(status="FAILED", release_ref=c.release_ref, inputs=c.inputs, physical_fits=0,
        fit_cutoff=base.FIT_CUTOFF, source_read_cutoff=base.CONTROL_CUTOFF, error="synthetic_before_fit")
    c.put(old_path, saved, None)
    old_ref = base.reference(old_path)
    @contextmanager
    def narrowed(*args):
        yield []
    @contextmanager
    def helpers(_):
        yield SimpleNamespace(narrowed_reads=narrowed), recovery, SimpleNamespace(memory=lambda:dict(physical_gib=4., page_gib=32.))
    @contextmanager
    def events(*args):
        yield
    monkeypatch.setattr(base, "helpers", helpers)
    monkeypatch.setattr(base, "bounded_events", events)
    monkeypatch.setattr(base, "project_events", lambda *args:{})
    monkeypatch.setattr(inputs.ReadPermit, "from_files", lambda *args:object())
    monkeypatch.setattr(inputs, "r10_source_manifest", lambda:dict(metadata_pins=dict(event_binding={}), parquet_sources={}))
    monkeypatch.setattr(inputs, "build_real_frames", lambda *args:SimpleNamespace(frames=object()))
    monkeypatch.setattr(recovery, "frame_for_recovery", lambda bundle:object(), raising=False)
    from scripts.research.a2.training import stateful_mechanism as original
    monkeypatch.setattr(original, "structured_action_frame", lambda *args:object())
    def training(bundle, group, horizon, *args, **kwargs):
        slot = f"ACTION_VALUE_{group}_{horizon}_2024_SCALER"
        return dict(c.inputs[slot], **base._component_arrays(c.inputs[slot]))
    monkeypatch.setattr(base, "component_training_input", training)
    def save_array(path, value):
        np.save(path, value, allow_pickle=False)
        return dict(base.reference(path), shape=list(value.shape))
    monkeypatch.setattr(recovery, "save_array", save_array, raising=False)
    c.old_release["original_read_authorization_ref"] = dict(path="synthetic", sha256="synthetic")
    c.old_release["original_design_ref"] = base.reference(Path(c.old_release["original_design_ref"]["path"]))
    result = base.component_prepare(c.release, c.old_release, None, c.out, c.records, c.release_ref)
    assert result["status"] == "PREPARED" and result["attempt"] == 2 and c.calls == []
    snapshot = c.out/"PREPARATION_ATTEMPT_001.json"
    assert base.reference(snapshot)["sha256"] == old_ref["sha256"]
    assert all("attempt_002" in d["arrays"]["x"]["path"] for d in result["inputs"].values())
    assert all(Path(d["arrays"]["x"]["path"]).is_file() for d in c.inputs.values())


def test_interrupted_fit_unit_one_cannot_resume(restore_case):
    c = restore_case
    slot = "ACTION_VALUE_ENTRY_HMEAN_2024_SCALER"
    record = c.records[slot]
    c.put(c.out/"objects"/slot/"fit_receipt.json", dict(status="FITTING", fit_units=1,
        release_ref=c.release_ref, parent_receipt_ref=record["receipt_ref"], original_identity=record["identity"]), None)
    with pytest.raises(ValueError, match="FAILED_OR_INTERRUPTED_COMPONENT_PRESERVED"):
        run_fit(c)
    assert c.calls == []



@pytest.fixture
def correction_case(restore_case, monkeypatch):
    import joblib
    from scripts.research.a2.training import stateful_values as values
    c = restore_case
    parent = dict(c.release, task_id=base.TASK,
        schema="BASE_HISTORICAL_2024_COMPONENT_RESTORE_RELEASE_R1", status="ROOT_AUTHORIZED_COMPONENT_RESTORATION",
        contract_ref=dict(synthetic="contract"), original_oof_release_ref=dict(synthetic="oof"),
        recovery_delta_ref=dict(synthetic="delta"), receipt_refs={}, run_root=str(c.out.parent))
    parent_path = c.out.parent/"parent_release.json"
    c.put(parent_path, parent, None)
    parent_ref = base.reference(parent_path)
    prep = json.loads((c.out/"PREPARATION.json").read_text())
    prep["release_ref"] = parent_ref
    for data in prep["inputs"].values():
        path = Path(data["arrays"]["x"]["path"])
        np.save(path, np.asfortranarray(np.load(path, allow_pickle=False)), allow_pickle=False)
        data["arrays"]["x"].update(base.reference(path))
    c.put(c.out/"PREPARATION.json", prep, None)
    target = c.out.parent/"original_scaler.joblib"
    joblib.dump(IdentityScaler(), target)
    original_sha = base.reference(target)["sha256"]
    for slot, r in c.records.items():
        if r["kind"] != "scalers":
            continue
        r["original_model_ref"]["sha256"] = original_sha
        folder = c.out/"objects"/slot
        folder.mkdir(parents=True)
        mp = folder/"model.joblib"
        joblib.dump(IdentityScaler(1. if r["group"]=="INCUMBENT" else 0.), mp)
        c.put(folder/"fit_receipt.json", dict(status="TRAINED", fit_units=1, kind="scalers", slot_id=slot,
            release_ref=parent_ref, parent_receipt_ref=r["receipt_ref"], original_identity=r["identity"], model_ref=base.reference(mp)), None)
        if r["kind"] == "scalers":
            r["receipt"] = dict(scientific_tuple_sha256="synthetic_tuple")
    baseline = c.out.parent/"baseline_failure.json"
    c.put(baseline, dict(scaler_fits=4,ridge_fits=0), None)
    delta = dict(schema="BASE_HISTORICAL_2024_INC_SCALER_NUMERIC_EXECUTION_CORRECTION_R1",
        status="ROOT_AUTHORIZED_NUMERIC_EXECUTION_CORRECTION", task_id=base.TASK,
        base_component_restore_release_ref=parent_ref, correction_slots=list(base.CORRECTION_SLOTS),
        physical_fit_cap=dict(scalers=2,ridge=0,elasticnet=0), actual_total_scaler_fits_cap=6,
        original_signal_and_label_maturity_cutoff_exclusive=base.FIT_CUTOFF,
        native_execution="original values._fit_job spawn with host default thread environment",
        no_thread_search=True, exact_original_model_sha_required=True, original_transformed_x_sha_required=True,
        baseline_attempt_ref=base.reference(baseline))
    delta_path = c.out.parent/"correction_delta.json"
    c.put(delta_path, delta, None)
    release = dict(parent, base_component_restore_release_ref=parent_ref,
                   correction_delta_ref=base.reference(delta_path), permits=dict(numeric_correction=True, fit=True, prepare=False))
    release_path = c.out.parent/"correction_release.json"
    c.put(release_path, release, None)
    c.release, c.release_ref = release, base.reference(release_path)
    c.native_calls = []
    def native(operation, slot, x, payload, dates, quantile, dependencies, features, observed,
               log, auth, prior, year, tuple_sha, receipt, worker_target):
        assert operation=="mechanism_scaler" and slot in base.CORRECTION_SLOTS
        assert type(x) is np.ndarray and x.flags.f_contiguous and not x.flags.c_contiguous
        assert observed is None and worker_target is models.fit_worker and auth['max_fit_units']==2
        receipt['fit_units']+=1
        c.native_calls.append(slot)
        receipt['physical_fit_metadata']=[dict(metadata=dict(actual_fit_count=1))]
        return IdentityScaler()
    monkeypatch.setattr(values, "_fit_job", native)
    monkeypatch.setattr(models, "fit_weighted_scaler", lambda *args, **kwargs:pytest.fail("correction must use original spawn owner"))
    for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):
        monkeypatch.delenv(key, raising=False)
    c.parent_ref, c.delta = parent_ref, delta
    c.native = native
    return c


def run_correction(c):
    return base.component_numeric_correction(c.release,c.old_release,None,c.out,c.records,c.release_ref)


def test_correction_only_two_inc_then_ridge_and_total_six_scalers(correction_case):
    c=correction_case
    before={str(p):base.reference(p)['sha256'] for p in (c.out/'objects').glob('*/*')}
    result=run_correction(c)
    assert result['actual_total_scaler_fits']==6 and c.native_calls==list(base.CORRECTION_SLOTS)
    assert all(base.reference(p)['sha256']==sha for p,sha in before.items())
    bundle=run_fit(c)
    assert c.calls==[('ridge',3),('ridge',3)]
    assert bundle['physical_restoration_fits']==dict(scalers=6,ridge=2,elasticnet=0)
    assert bundle['physical_restoration_fit_breakdown']['initial_scalers']==4
    assert 'native_execution_correction' in bundle['nodes']['INCUMBENT']['elasticnet_scaler_ref']['path']
    assert 'native_execution_correction' not in bundle['nodes']['ENTRY']['elasticnet_scaler_ref']['path']
    run_correction(c)
    run_fit(c)
    assert len(c.native_calls)==2 and len(c.calls)==2


def test_correction_exact_model_mismatch_stops_one_attempt(correction_case, monkeypatch):
    from scripts.research.a2.training import stateful_values as values
    c=correction_case
    def bad(*args,**kwargs):
        c.native(*args,**kwargs)
        return IdentityScaler(1.)
    monkeypatch.setattr(values,'_fit_job',bad)
    with pytest.raises(ValueError,match='EXACT_ORIGINAL_SCALER_SHA'):
        run_correction(c)
    assert len(c.native_calls)==1
    with pytest.raises(ValueError,match='FAILED_NUMERIC_CORRECTION_PRESERVED'):
        run_correction(c)
    assert len(c.native_calls)==1
    with pytest.raises(ValueError,match='VERIFIED_NUMERIC_CORRECTION_REQUIRED'):
        run_fit(c)
    assert c.calls==[]


def test_correction_host_override_rejects_before_fit(correction_case,monkeypatch):
    c=correction_case
    monkeypatch.setenv('OPENBLAS_NUM_THREADS','2')
    with pytest.raises(ValueError,match='HOST_DEFAULT_ENVIRONMENT'):
        run_correction(c)
    assert c.native_calls==[] and c.calls==[]


def test_correction_wrong_parent_and_cap_reject(correction_case):
    c=correction_case
    c.release['contract_ref']={'changed':'parent'}
    with pytest.raises(ValueError,match='NUMERIC_CORRECTION_PARENT:contract_ref'):
        run_correction(c)
    assert c.native_calls==[]


def test_correction_bad_transformed_commitment_blocks_second_inc(correction_case):
    c=correction_case
    # Keep scalar raw tuple and labels fixed, replace the supplied transformed-X
    # commitment in both record/prepare fixture to exercise the final hash gate.
    slot=base.CORRECTION_SLOTS[0]
    c.records[slot]['en_identity']=dict(c.records[slot]['en_identity'],x_sha256='not_the_actual_transform')
    p=c.out/'PREPARATION.json'
    prep=json.loads(p.read_text())
    prep['inputs'][slot]['model_identity']=c.records[slot]['en_identity']
    c.put(p,prep,None)
    with pytest.raises(ValueError,match='ORIGINAL_COMMITMENT_MISMATCH:x_sha256'):
        run_correction(c)
    assert len(c.native_calls)==1
    with pytest.raises(ValueError,match='FAILED_NUMERIC_CORRECTION_PRESERVED'):
        run_correction(c)
    assert len(c.native_calls)==1 and c.calls==[]


def test_r2_cannot_reprepare_or_fit_before_correction(correction_case):
    c=correction_case
    c.release['permits']['prepare']=True
    with pytest.raises(ValueError,match='REUSES_PARENT_PREPARATION'):
        base.component_prepare(c.release,c.old_release,None,c.out,c.records,c.release_ref)
    with pytest.raises(FileNotFoundError):
        run_fit(c)
    assert c.native_calls==[] and c.calls==[]



def test_correction_wrong_extra_fit_cap_rejects(correction_case):
    c=correction_case
    p=Path(c.release['correction_delta_ref']['path'])
    delta=json.loads(p.read_text())
    delta['physical_fit_cap']['scalers']=3
    c.put(p,delta,None)
    c.release['correction_delta_ref']=base.reference(p)
    with pytest.raises(ValueError,match='EXACT_NUMERIC_EXECUTION_CORRECTION'):
        run_correction(c)
    assert c.native_calls==[] and c.calls==[]



def test_correction_initial_wrong_parent_receipt_rejects_before_fit(correction_case):
    c=correction_case
    p=c.out/'objects/ACTION_VALUE_INCUMBENT_H5_2024_SCALER/fit_receipt.json'
    row=json.loads(p.read_text());row['parent_receipt_ref']={'wrong':'parent'}
    c.put(p,row,None)
    with pytest.raises(ValueError,match='EXACT_INITIAL_SCALER_ATTEMPTS'):
        run_correction(c)
    assert c.native_calls==[]


def test_correction_nonexact_entry_cannot_be_reused(correction_case):
    c=correction_case
    slot='ACTION_VALUE_ENTRY_HMEAN_2024_SCALER'
    c.records[slot]['original_model_ref']['sha256']='not_entry_bytes'
    with pytest.raises(ValueError,match='EXACT_ENTRY_SCALER_REUSE'):
        run_correction(c)
    assert c.native_calls==[]


def test_corrected_result_requires_current_parent_preparation_ref(correction_case):
    c=correction_case
    run_correction(c)
    p=c.out/'PREPARATION.json'
    data=json.loads(p.read_text());data['unapproved_metadata_change']=True
    c.put(p,data,None)
    with pytest.raises(ValueError,match='VERIFIED_NUMERIC_CORRECTION_REQUIRED'):
        run_fit(c)
    assert c.calls==[] and len(c.native_calls)==2



def test_component_workspace_budget_is_shape_based_with_measured_margin():
    solver = SimpleNamespace(memory=lambda:dict(physical_gib=.831, page_gib=22.793))
    big = base.component_memory_admission(solver, [35670, 242], "fit")
    small = base.component_memory_admission(solver, [560, 80], "fit")
    assert big["matrix_bytes"] == 69057120
    # Actual default-owner incremental RSS was 203.016 MiB, commit 264.926 MiB.
    assert big["estimated_incremental_working_bytes"] > 203.016 * 1024**2
    assert big["required_available_page_bytes"] > 264.926 * 1024**2
    assert small["required_available_physical_bytes"] < big["required_available_physical_bytes"] < .831 * 1024**3
    resident = base.component_memory_admission(solver, [35670, 242], "fit", resident_bytes=big["matrix_bytes"])
    assert big["required_available_physical_bytes"] - resident["required_available_physical_bytes"] == big["matrix_bytes"]
    with pytest.raises(ValueError, match="COMPONENT_STAGE_RESOURCE_ADMISSION"):
        base.component_memory_admission(SimpleNamespace(memory=lambda:dict(physical_gib=.1, page_gib=32.)), [35670,242], "fit")
    with pytest.raises(ValueError, match="WORKSPACE_BUDGET_BYTES"):
        base.additional_workspace_budget(1, resident_bytes=-1)



def test_inplace_nan_cleanup_preserves_f_order_and_raw_bits(tmp_path):
    raw = np.asfortranarray([[np.nan, -0., np.inf], [1., 2., -np.inf]])
    p = tmp_path / "raw.npy"
    np.save(p, raw, allow_pickle=False)
    before = base.reference(p)
    mapped = np.load(p, mmap_mode="r", allow_pickle=False)
    tx = IdentityScaler().transform(mapped)
    assert tx.dtype == np.float64 and tx.flags.f_contiguous and not np.shares_memory(tx, mapped)
    expected = np.nan_to_num(tx, nan=0., copy=True)
    pointer = tx.ctypes.data
    np.nan_to_num(tx, nan=0., copy=False)
    assert tx.ctypes.data == pointer and tx.flags.f_contiguous
    assert digest_array(tx) == digest_array(expected)
    assert np.isnan(mapped[0,0]) and not mapped.flags.writeable and base.reference(p) == before
    base.close_component_arrays({"x":mapped})
    assert mapped._mmap.closed



def test_component_cache_single_role_mmaps_f_order_and_no_extra_transform(correction_case, monkeypatch):
    c = correction_case
    run_correction(c)
    original_load, original_transform, original_fit = base._component_arrays, IdentityScaler.transform, models.fit
    mappings, transforms = [], []
    def load(data, keys=None):
        arrays = original_load(data, keys)
        mappings.extend(arrays.values())
        return arrays
    def transform(self, x):
        transforms.append(str(x.filename))
        return original_transform(self, x)
    def fit(slot, x, payload, **kwargs):
        alive = [a for a in mappings if not a._mmap.closed]
        assert len(alive) == 4 and sum(a.ndim == 2 for a in alive) == 1
        assert x.dtype == np.float64 and x.flags.f_contiguous and not x.flags.writeable
        receipt = c.out / "verified_h5_inputs" / c.release_ref["sha256"][:16] / "SCALED_INPUTS.json"
        cache = json.loads(receipt.read_text())
        assert cache["status"] == "VERIFIED_ALL_FOUR_TRANSFORMS" and len(transforms) == 4
        assert all(a._mmap.closed for a in mappings if a.ndim == 2 and "verified_h5_inputs" not in str(a.filename))
        return original_fit(slot, x, payload, **kwargs)
    monkeypatch.setattr(base, "_component_arrays", load)
    monkeypatch.setattr(IdentityScaler, "transform", transform)
    monkeypatch.setattr(models, "fit", fit)
    run_fit(c)
    assert len(transforms) == 4 and all(a._mmap.closed for a in mappings)
    run_fit(c)
    assert len(transforms) == 4 and len(c.calls) == 2 and all(a._mmap.closed for a in mappings)



def test_partial_transform_cache_preserved_and_zero_fit_continues(restore_case, monkeypatch, recovery):
    c = restore_case
    original = recovery.check_commitments
    count = 0
    def check(x, dates, weights, target, features, expected):
        nonlocal count
        original(x, dates, weights, target, features, expected)
        if np.any(target):
            count += 1
            if count == 3:
                raise RuntimeError("synthetic_io_failure_before_ridge")
    monkeypatch.setattr(recovery, "check_commitments", check)
    with pytest.raises(RuntimeError, match="synthetic_io_failure_before_ridge"):
        run_fit(c)
    assert c.calls == [("scaler",2),("scaler",3),("scaler",2),("scaler",3)]
    namespace = c.out / "verified_h5_inputs" / c.release_ref["sha256"][:16]
    failed = json.loads((namespace/"attempt_001/FAILED.json").read_text())
    old_x = base.reference(namespace/"attempt_001/ENTRY/x.npy")
    assert failed["status"] == "FAILED_BEFORE_RIDGE" and not (namespace/"SCALED_INPUTS.json").exists()
    monkeypatch.setattr(recovery, "check_commitments", original)
    run_fit(c)
    assert len(c.calls) == 6 and base.reference(old_x["path"]) == old_x
    assert json.loads((namespace/"SCALED_INPUTS.json").read_text())["attempt"] == 2



def test_alias_transform_rejects_without_mutating_raw_or_starting_ridge(restore_case, monkeypatch):
    c = restore_case
    refs = {s:base.reference(d["arrays"]["x"]["path"]) for s,d in c.inputs.items()}
    monkeypatch.setattr(IdentityScaler, "transform", lambda self, x:x)
    with pytest.raises(ValueError, match="OWNED_FLOAT64_TRANSFORM_REQUIRED"):
        run_fit(c)
    assert len(c.calls) == 4 and all(k == "scaler" for k,n in c.calls)
    assert all(base.reference(c.inputs[s]["arrays"]["x"]["path"]) == ref for s,ref in refs.items())



def test_mmap_load_failure_closes_previously_opened_handles(restore_case, monkeypatch):
    c = restore_case
    data = c.inputs["ACTION_VALUE_ENTRY_H5_2024_SCALER"]
    load = np.load
    opened = []
    def fail(path, **kwargs):
        if opened:
            raise OSError("synthetic_second_array_failure")
        array = load(path, **kwargs)
        opened.append(array)
        return array
    monkeypatch.setattr(np, "load", fail)
    with pytest.raises(OSError, match="synthetic_second_array_failure"):
        base._component_arrays(data)
    assert len(opened) == 1 and opened[0]._mmap.closed



def test_sealed_cache_cannot_replace_original_model_cohort(restore_case):
    c = restore_case
    run_fit(c)
    p = c.out/"verified_h5_inputs"/c.release_ref["sha256"][:16]/"SCALED_INPUTS.json"
    saved = json.loads(p.read_text())
    saved["groups"]["INCUMBENT"]["model_identity"]["features"] = ["substituted"]
    c.put(p, saved, None)
    with pytest.raises(ValueError, match="VERIFIED_SCALED_INPUT_COHORT"):
        run_fit(c)
    assert len(c.calls) == 6



def test_r3_uses_immutable_r2_correction_producer(correction_case):
    c = correction_case
    result = run_correction(c)
    producer = c.release_ref
    c.release = dict(c.release, verified_numeric_correction_release_ref=producer,
        numeric_correction_ref=base.reference(c.out/"native_execution_correction/CORRECTED_SCALERS.json"),
        driver_ref=dict(path="synthetic_new_source", sha256="new_source"), permits=dict(fit=True, prepare=False, numeric_correction=False))
    path = c.out.parent/"memory_release.json"
    c.put(path, c.release, None)
    c.release_ref = base.reference(path)
    bundle = run_fit(c)
    assert bundle["physical_restoration_fits"] == dict(scalers=6,ridge=2,elasticnet=0)
    assert len(c.native_calls) == 2 and c.calls == [("ridge",3),("ridge",3)]
    assert base.reference(producer["path"]) == producer
    assert json.loads((c.out/"native_execution_correction/CORRECTED_SCALERS.json").read_text()) == result



def test_r3_wrong_correction_producer_rejects_before_ridge(correction_case):
    c = correction_case
    run_correction(c)
    producer = dict(c.release, correction_delta_ref={"wrong":"delta"})
    p = c.out.parent/"wrong_producer.json"
    c.put(p, producer, None)
    c.release = dict(c.release, verified_numeric_correction_release_ref=base.reference(p),
        numeric_correction_ref=base.reference(c.out/"native_execution_correction/CORRECTED_SCALERS.json"))
    p = c.out.parent/"new_release.json"
    c.put(p, c.release, None)
    c.release_ref = base.reference(p)
    with pytest.raises(ValueError, match="CORRECTION_PRODUCER:correction_delta_ref"):
        run_fit(c)
    assert c.calls == [] and len(c.native_calls) == 2



def test_same_values_c_order_cache_cannot_replace_original_f_before_any_ridge(correction_case, monkeypatch):
    c = correction_case
    run_correction(c)
    admission = base.component_memory_admission
    def stop(solver, shape, phase, **kwargs):
        if phase == "fit":
            raise RuntimeError("synthetic_stop_after_verified_cache_before_ridge")
        return admission(solver, shape, phase, **kwargs)
    monkeypatch.setattr(base, "component_memory_admission", stop)
    with pytest.raises(RuntimeError, match="synthetic_stop_after_verified_cache_before_ridge"):
        run_fit(c)
    assert c.calls == []
    receipt = c.out/"verified_h5_inputs"/c.release_ref["sha256"][:16]/"SCALED_INPUTS.json"
    cache = json.loads(receipt.read_text())
    xref = cache["groups"]["INCUMBENT"]["arrays"]["x"]
    path = Path(xref["path"])
    x = np.load(path, allow_pickle=False)
    assert x.flags.f_contiguous and not x.flags.c_contiguous
    expected = digest_array(x)
    np.save(path, np.ascontiguousarray(x), allow_pickle=False)
    assert digest_array(np.load(path, allow_pickle=False)) == expected
    xref.update(base.reference(path))
    c.put(receipt, cache, None)
    monkeypatch.setattr(base, "component_memory_admission", admission)
    with pytest.raises(ValueError, match="VERIFIED_SCALED_INPUT_LAYOUT"):
        run_fit(c)
    assert c.calls == [] and len(c.native_calls) == 2
