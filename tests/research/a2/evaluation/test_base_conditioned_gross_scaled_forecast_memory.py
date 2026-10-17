"""Synthetic caller equality for existing owned scaler-output reuse."""
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import base_conditioned_gross_history as history
from scripts.research.a2.evaluation import base_conditioned_gross_eval as evaluation


@pytest.mark.parametrize("entrypoint", ["history", "evaluation"])
@pytest.mark.parametrize("empty_group", [None, "ENTRY", "INCUMBENT"])
def test_scaled_forecast_matches_original_bytes_and_preserves_inputs(monkeypatch, entrypoint, empty_group):
    import joblib
    from sklearn.preprocessing import StandardScaler
    from scripts.research.a2.inference import consensus_paper as paper, frozen_a94_actions as actions
    from scripts.research.a2.training import stateful_mechanism as mechanism, stateful_final_action_packets as packets
    day = pd.Timestamp("2023-01-04")
    frames, originals, artifacts, roles, model_refs = {}, {}, {}, {}, {}
    bundle = dict(nodes={})
    for group in ("ENTRY", "INCUMBENT"):
        role = "R10:" + group
        features = actions.role_features(role)
        rows = [{**dict.fromkeys(features, float(i+1)), "signal_date":day,
                 "sample_id":"synthetic-"+group+str(i), "ticker":"TOY"+str(i),
                 "security_id":"SYNTHETIC"+str(i)} for i in range(2)]
        rows[0][features[0]] = float("nan")
        if group == "INCUMBENT":
            rows[1]["e_friction"] = float("nan")
        frame = pd.DataFrame(rows)
        if empty_group == group:
            frame = frame.iloc[:0].copy()
        frames[group] = frame
        originals[group] = frame.copy(deep=True)
        supported = ((frame.e_friction.notna() & frame.i_friction.notna()).to_numpy()
                     if group == "INCUMBENT" else np.ones(len(frame), bool))
        roles[role] = dict(frame_ref=dict(path=role), read_columns=list(frame.columns),
            commitment=actions.input_commitment(frame, features, supported=supported),
            full_frame_scope=dict(start=str(day.date()), end=str(day.date())))
        bundle["nodes"][group] = {}
        width = len(features)*2
        for base, family in zip(history.BASES, ("elasticnet", "ridge")):
            key = family + group
            model = dict(coefficients=np.linspace(-.5,.5,width,dtype=np.float64), intercept=.125)
            scaler = StandardScaler(copy=True)
            scaler.mean_, scaler.scale_, scaler.var_ = np.linspace(-.25,.25,width), np.full(width,1.5), np.full(width,2.25)
            scaler.n_features_in_, scaler.n_samples_seen_ = width, 2
            artifacts[key+"model"], artifacts[key+"scaler"] = model, scaler
            refs = dict(model_ref=dict(path=key+"model"), scaler_ref=dict(path=key+"scaler"))
            model_refs.setdefault(base,{})[group] = refs
            bundle["nodes"][group][family+"_model_ref"] = refs["model_ref"]
            bundle["nodes"][group][family+"_scaler_ref"] = refs["scaler_ref"]
    def predict(model, x):
        assert x.dtype == np.float64 and np.isfinite(x).all()
        return dict(mean=x @ model["coefficients"] + model["intercept"])
    def decode(row, index, *, group):
        return dict(group=group, sample_id=row["sample_id"], index=index, forecast=float(row["mean"]))
    encoded_inputs = []
    original_encode = mechanism.encode
    def encode(frame, features):
        x, names = original_encode(frame, features)
        assert x.dtype == np.float64
        encoded_inputs.append((x, hashlib.sha256(x.tobytes(order="C")).hexdigest()))
        return x, names
    monkeypatch.setattr(mechanism, "encode", encode)
    monkeypatch.setattr(paper, "predict_r10", predict)
    monkeypatch.setattr(packets, "decode_r10_row", decode)
    monkeypatch.setattr(joblib, "load", lambda key:artifacts[key])
    monkeypatch.setattr(history, "START", str(day.date()))
    monkeypatch.setattr(history, "verify", lambda ref:ref["path"])
    monkeypatch.setattr(paper, "original_frames", lambda *args:frames)
    monkeypatch.setattr(evaluation, "verify", lambda ref:ref["path"])
    monkeypatch.setattr(evaluation, "_resource", lambda *args:None)
    flags = pd.DataFrame([dict(signal_date=day, is_raw_top20=True)])
    manifest = dict(direct_roles=roles, base_model_refs=model_refs)
    bridge = SimpleNamespace(bounded_frame=lambda ref, *args:frames[ref["path"].split(":")[1]].copy())
    optimized = paper.r10_scaled_input
    def execute(helper):
        monkeypatch.setattr(paper, "r10_scaled_input", helper)
        if entrypoint == "history":
            return history.action_predictions(flags, pd.DatetimeIndex([day]), bundle)
        return evaluation._base_predictions(manifest, bridge, str(day.date()), str(day.date()))
    expected = execute(lambda scaler,x:np.nan_to_num(scaler.transform(x), nan=0.))
    actual = execute(optimized)
    def fingerprint(result):
        ordered = [(base,str(date),rows) for base,by_day in result.items() for date,rows in by_day.items()]
        return hashlib.sha256(json.dumps(ordered, sort_keys=True, separators=(",",":"), allow_nan=True).encode()).hexdigest()
    assert fingerprint(actual) == fingerprint(expected)
    assert all(hashlib.sha256(x.tobytes(order="C")).hexdigest() == before for x,before in encoded_inputs)
    for group in frames:
        pd.testing.assert_frame_equal(frames[group], originals[group])
