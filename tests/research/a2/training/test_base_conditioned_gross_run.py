"""Synthetic runner boundaries; no market data, real estimator or account replay."""
from types import SimpleNamespace
import json

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import base_conditioned_gross_run as run


def context(day="2024-01-02"):
    return SimpleNamespace(signal_date=pd.Timestamp(day), path_ids=run.BASES,
        current_units=np.array([[0., 1., 1., 0.]] * 2),
        decision_mask=np.array([[True, True, True, False]] * 2),
        reserved_mask=np.array([[False, True, False, False]] * 2),
        sell_restricted=np.array([[False, False, True, False]] * 2))


def signal_inputs(di, ctx, row):
    x = np.ones((4, 32))
    return ("a", "b", "c", "d"), x, np.array([1., 2., 3., 4.])


def decision():
    return run.gross.TargetDecision(np.array([[.2, .2, .2, .2]] * 2),
                                   explicit_mask=np.ones((2, 4), bool))


def samples():
    parts = []
    for day in pd.bdate_range("2024-01-02", periods=100):
        parts.append(run.gross.training_rows([.5], np.ones((1, 32)), [1.], [.01],
            signal_date=day, label_mature_dates=[day + pd.Timedelta(days=7)], cutoff=run.CUTOFF))
    return pd.concat(parts, ignore_index=True)


def test_signal_capture_matches_inference_mask_and_returns_original(monkeypatch):
    ctx, original = context(), decision()
    recorder = run.SignalTargetRecorder(run.BASES, lambda *a: original, signal_inputs)
    assert recorder(0, ctx) is original
    monkeypatch.setattr(run.gross, "predict_gross", lambda *a: 1.)
    overlay = run.gross.BaseConditionedGrossOverlay(run.BASES, lambda *a: original,
        dict.fromkeys(run.BASES, object()), lambda di, ctx, row: signal_inputs(di, ctx, row)[1:])
    output = overlay(0, ctx)
    for row, record in enumerate(recorder.records):
        np.testing.assert_array_equal(record["weights"], output.weights[row, output.weights[row] > 0])
        assert record["keys"] == ("a",)
    np.testing.assert_array_equal(original.weights, np.array([[.2] * 4] * 2))


def test_cash_never_reads_features_or_labels():
    ctx, original = context(), decision()
    original.weights[:] = 0
    def forbidden(*a, **k): raise AssertionError("unexpected read")
    recorder = run.SignalTargetRecorder(run.BASES, lambda *a: original, forbidden)
    recorder(0, ctx)
    frames, excluded = run.build_samples(recorder.records, forbidden, forbidden)
    assert all(f.empty for f in frames.values()) and len(excluded) == 2


def test_future_label_clock_prevents_numeric_read():
    recorder = run.SignalTargetRecorder(run.BASES, lambda *a: decision(), signal_inputs)
    recorder(0, context())
    def forbidden(*a, **k): raise AssertionError("future numeric label read")
    frames, excluded = run.build_samples(recorder.records, lambda r: [run.CUTOFF], forbidden)
    assert all(f.empty for f in frames.values())
    assert {r["reason"] for r in excluded} == {"WHOLE_TARGET_LABEL_NOT_MATURE"}


def test_label_missing_keeps_whole_target_and_no_weight_renormalization():
    ctx = context()
    ctx.reserved_mask[:] = False
    ctx.sell_restricted[:] = False
    recorder = run.SignalTargetRecorder(run.BASES, lambda *a: decision(), signal_inputs)
    recorder(0, ctx)
    frames, _ = run.build_samples(recorder.records, lambda r: ["2024-01-10"] * 3,
                                  lambda *a, **k: [.1, .1, .1])
    assert all(len(f) == 5 and np.allclose(f.base_tradable_gross, .6) for f in frames.values())
    assert all(np.allclose(f.basket_y, .06) for f in frames.values())
    frames, excluded = run.build_samples(recorder.records, lambda r: ["2024-01-10"] * 3,
                                          lambda *a, **k: [.1, np.nan, .1])
    assert all(f.empty for f in frames.values()) and len(excluded) == 2


def test_calibration_last60_and_train_label_purge():
    frame = samples()
    train, cal, split = run.split_samples(frame)
    assert cal.signal_date.nunique() == 60
    assert (train.label_mature_date < pd.Timestamp(split["calibration_start"])).all()
    assert split["purged_rows"] > 0 and split["calibration_driven_selection"] is False
    with pytest.raises(ValueError, match="EXACT_FIVE_PRIOR_REQUESTS"):
        run.split_samples(frame.iloc[1:])


def test_cutoff_rejected_and_unreleased_has_no_reads(monkeypatch):
    recorder = run.SignalTargetRecorder(run.BASES, lambda *a: decision(), signal_inputs)
    with pytest.raises(ValueError, match="BOUNDED_CAUSAL"):
        recorder(0, context(str(run.CUTOFF.date())))
    monkeypatch.setattr(run, "document", lambda *a: dict(task_id=run.TASK, permits={"train": False}))
    monkeypatch.setattr(run, "verify", lambda *a: pytest.fail("input read before release"))
    with pytest.raises(ValueError, match="SOURCE_RELEASE"):
        run.run_training({})


def test_sample_footer_boundary_precedes_numeric_columns(tmp_path):
    frame = samples()
    frame.loc[0, "label_mature_date"] = run.CUTOFF
    p = tmp_path / "bad.parquet"
    frame.to_parquet(p)
    with pytest.raises(ValueError, match="NUMERIC_SAMPLE_READ_BOUNDARY"):
        run.read_samples(run.reference(p), tmp_path)


def test_completed_fit_checkpoint_reuses_and_started_failure_is_preserved(tmp_path, monkeypatch):
    train, cal, split = run.split_samples(samples())
    monkeypatch.setattr(run, "write_json_atomic", lambda p, j: p.write_text(json.dumps(j, default=str)))
    monkeypatch.setattr(run, "diagnostics", lambda *a: {"synthetic": True})
    monkeypatch.setattr(run.values, "_events", lambda p: [])
    calls = []
    def fake_fit(*args, **kw):
        calls.append(1)
        kw["receipt"]["fit_units"] = 1
        return SimpleNamespace(metadata={"synthetic": True})
    monkeypatch.setattr(run.values, "_fit_job", fake_fit)
    first = run.fit_slot(tmp_path, run.BASES[0], "tree", train, cal, split, {"id": 1}, ())
    again = run.fit_slot(tmp_path, run.BASES[0], "tree", train, cal, split, {"id": 1}, ())
    assert first == again and len(calls) == 1
    p = tmp_path / "gross_models" / (run.BASES[0] + "__tree") / "fit_receipt.json"
    failed = json.loads(p.read_text()); failed["status"] = "FAILED"
    p.write_text(json.dumps(failed))
    with pytest.raises(ValueError, match="FAILED_STARTED_FIT"):
        run.fit_slot(tmp_path, run.BASES[0], "tree", train, cal, split, {"id": 1}, ())
    assert len(calls) == 1


def test_diagnostic_failure_keeps_trained_model_and_resumes_without_fit(tmp_path, monkeypatch):
    train, cal, split = run.split_samples(samples())
    monkeypatch.setattr(run, "write_json_atomic", lambda p, j: p.write_text(json.dumps(j, default=str)))
    monkeypatch.setattr(run.values, "_events", lambda p: [])
    calls = []
    def fake_fit(*args, **kw):
        calls.append(1); kw["receipt"]["fit_units"] = 1
        return SimpleNamespace(metadata={"synthetic": True})
    monkeypatch.setattr(run.values, "_fit_job", fake_fit)
    monkeypatch.setattr(run, "diagnostics", lambda *a: (_ for _ in ()).throw(ValueError("diagnostic-only")))
    with pytest.raises(ValueError, match="diagnostic-only"):
        run.fit_slot(tmp_path, run.BASES[0], "tree", train, cal, split, {}, ())
    p = tmp_path / "gross_models" / (run.BASES[0] + "__tree") / "fit_receipt.json"
    assert json.loads(p.read_text())["status"] == "TRAINED"
    monkeypatch.setattr(run, "diagnostics", lambda *a: {"resumed": True})
    result = run.fit_slot(tmp_path, run.BASES[0], "tree", train, cal, split, {}, ())
    assert result["diagnostic"] == {"resumed": True} and len(calls) == 1


def test_resource_failure_has_no_numeric_reads_or_trial_then_resume(tmp_path, monkeypatch):
    from contextlib import nullcontext
    (tmp_path / "run_config.json").write_text("{}")
    driver = run.reference(run.__file__)
    manifest = dict(task_id=run.TASK, permits={"train": True}, driver_ref=driver,
        history=run.history_config(), runtime_source_refs={}, run_root=str(tmp_path),
        sample_receipt_ref="samples", raw_model_manifest_refs={}, resource_owner_ref={})
    sample = dict(status="SAMPLES_READY", history=run.history_config(),
        source_refs={k:k for k in run.SOURCE_KEYS}, samples=dict.fromkeys(run.BASES, {}),
        splits={b:run.split_samples(samples())[2] for b in run.BASES})
    contract = dict(research_id=run.TASK, bases=run.BASES, learners=run.models.LEARNERS,
        controller_signal_and_label_maturity_cutoff_exclusive="2024-10-07",
        fit_budget={"gross_physical_fit_cap":10}, ordered_features=run.gross.FEATURES)
    monkeypatch.setattr(run, "document", lambda ref: {"manifest":manifest,"samples":sample,"contract":contract}[ref])
    monkeypatch.setattr(run, "verify", lambda ref: None)
    monkeypatch.setattr(run, "runtime_source_refs", lambda: {})
    monkeypatch.setattr(run, "assert_safe_output_path", lambda *a, **k: None)
    monkeypatch.setattr(run, "verify_raw_models", lambda *a: True)
    monkeypatch.setattr(run, "continuation_lock", lambda *a, **k: nullcontext())
    monkeypatch.setattr(run, "resource_gate", lambda *a: (_ for _ in ()).throw(ValueError("ORIGINAL_RESOURCE_ADMISSION")))
    monkeypatch.setattr(run, "read_samples", lambda *a: pytest.fail("numeric read before memory admission"))
    with pytest.raises(ValueError, match="ORIGINAL_RESOURCE_ADMISSION"):
        run.run_training("manifest")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run_config.json"]
    monkeypatch.setattr(run, "resource_gate", lambda *a: {"synthetic":True})
    monkeypatch.setattr(run, "read_samples", lambda *a: samples())
    calls=[]
    def fitted(*args):
        calls.append((args[1], args[2])); return {"status":"TRAINED"}
    monkeypatch.setattr(run, "fit_slot", fitted)
    monkeypatch.setattr(run, "write_json_atomic", lambda p,j: p.write_text(json.dumps(j)))
    assert run.run_training("manifest")["status"] == "SIX_GROSS_MODELS_TRAINED"
    assert len(calls) == 6


def test_target_tamper_cannot_reach_fit():
    frame=samples()
    frame.loc[0,"target"]=(frame.loc[0,"target"]+1)%len(run.gross.GRID)
    with pytest.raises(ValueError,match="ORIGINAL_GROSS_TARGET_REQUIRED"):
        run.split_samples(frame)


@pytest.mark.parametrize("failed_learner", [None, "tree"])
def test_two_base_training_releases_previous_frames_and_preserves_failed_arms(tmp_path, monkeypatch, failed_learner):
    """At the second source read the previous base's frame/splits must be gone."""
    import weakref
    from contextlib import nullcontext
    (tmp_path / "run_config.json").write_text("{}")
    toy = samples()
    for key in ("signal_date", "label_mature_date"):
        toy[key] = pd.to_datetime(toy[key]) - pd.Timedelta(days=365)
    assert toy.signal_date.max() < pd.Timestamp("2024-01-01")
    monkeypatch.setattr(run, "START", toy.signal_date.min())
    expected_split = run.split_samples(toy)[2]
    manifest = dict(task_id=run.TASK, permits=dict(train=True), driver_ref=run.reference(run.__file__),
        history=run.history_config(), runtime_source_refs={}, run_root=str(tmp_path),
        sample_receipt_ref="sample", raw_model_manifest_refs={}, resource_owner_ref={})
    sample = dict(status="SAMPLES_READY", history=run.history_config(),
        source_refs={k:k for k in run.SOURCE_KEYS},
        samples={b:dict(base=b) for b in run.BASES}, splits=dict.fromkeys(run.BASES, expected_split))
    contract = dict(research_id=run.TASK, bases=run.BASES, learners=run.models.LEARNERS,
        controller_signal_and_label_maturity_cutoff_exclusive="2024-10-07",
        fit_budget=dict(gross_physical_fit_cap=10), ordered_features=run.gross.FEATURES)
    monkeypatch.setattr(run, "document", lambda ref:{"manifest":manifest,"sample":sample,"contract":contract}[ref])
    monkeypatch.setattr(run, "verify", lambda *args:None)
    monkeypatch.setattr(run, "runtime_source_refs", lambda:{})
    monkeypatch.setattr(run, "assert_safe_output_path", lambda path, **kwargs:None)
    monkeypatch.setattr(run, "verify_raw_models", lambda *args:None)
    monkeypatch.setattr(run, "continuation_lock", lambda *args, **kwargs:nullcontext())
    monkeypatch.setattr(run, "resource_gate", lambda *args:dict(synthetic=True))
    reads, frame_refs, calls = [], [], []
    original_split = run.split_samples
    def read(reference, root):
        assert all(ref() is None for ref in frame_refs)
        reads.append(reference["base"])
        frame = toy.copy(); frame_refs.append(weakref.ref(frame)); return frame
    def split(frame):
        train, cal, split = original_split(frame)
        frame_refs.extend((weakref.ref(train), weakref.ref(cal)))
        return train, cal, split
    def fit(root, base, learner, train, cal, split, identity, dependencies):
        calls.append((base, learner))
        assert split == expected_split and train.signal_date.max() < pd.Timestamp("2024-01-01")
        if base == run.BASES[0] and learner == failed_learner:
            raise RuntimeError("synthetic_failed_fixed_arm")
        return dict(status="TRAINED", base=base, learner=learner)
    monkeypatch.setattr(run, "read_samples", read)
    monkeypatch.setattr(run, "split_samples", split)
    monkeypatch.setattr(run, "fit_slot", fit)
    def put(path, value):
        assert path.resolve().is_relative_to(tmp_path.resolve())
        path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(run, "write_json_atomic", put)
    result = run.run_training("manifest")
    assert reads == list(run.BASES)
    assert calls == [(b, learner) for b in run.BASES for learner in run.models.LEARNERS]
    assert all(ref() is None for ref in frame_refs)
    assert len(result["models"]) == 6 and result["test_rows_read"] == 0
    if failed_learner is None:
        assert result["status"] == "SIX_GROSS_MODELS_TRAINED"
    else:
        assert result["status"] == "SIX_FIXED_ARMS_ATTEMPTED_WITH_PRESERVED_FAILURES"
        failed = [r for r in result["models"] if r["status"] != "TRAINED"]
        assert len(failed) == 1 and "synthetic_failed_fixed_arm" in failed[0]["error"]
