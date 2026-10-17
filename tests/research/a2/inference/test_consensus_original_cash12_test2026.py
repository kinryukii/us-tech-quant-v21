"""Synthetic only: frozen cash-head inference, support domain and resume."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import consensus_original_cash12_test2026 as a

FEATURES = ["ret_20d", "realized_vol_20d", "price_vs_ma20", *("f%d" % i for i in range(29))]
PINS = {"synthetic": {"path": "synthetic", "sha256": "1" * 64}}


def frame():
    result = pd.DataFrame({
        "signal_date": pd.to_datetime(["2026-01-02"] * 3), "ticker": ["A", "B", "C"],
        "security_id": ["ID_A", "ID_B", "ID_C"], "feature_available": [True, True, False],
        "input_present": [True, True, False], "feature_source": ["ALLOWED"] * 3})
    for name in FEATURES:
        result[name] = [1., 3., 99.]
    return result


def freeze(tmp_path):
    r = {"path": str(tmp_path / "input.bin"), "sha256": "2" * 64}
    return {"schema": a.SCHEMA, "status": "AUTHORIZED_FROZEN_INFERENCE_ONLY",
            "research_id": "SYNTHETIC_CASH12", "run_dir": str(tmp_path),
            "start": a.START, "end": a.END, "feature_binding": {"features": FEATURES},
            "input_read_columns": [*a.KEYS, *a.FLAGS, *FEATURES], "source_pins": PINS,
            "input_ref": r, "original_input_ref": r, "new_fit": 0,
            "strict_PIT_certified": False, "dependency_paths": []}


def support(f):
    proof = {"domain_policy": a.DOMAIN, "role": "OFFPOOL_HOLDING_VALUE_CONTINUITY_ONLY",
             "no_future_first_membership": True, "no_new_buy_eligibility": True,
             "first_membership_by_ticker": {t: "2025-12-01" for t in f.ticker},
             "sessions": {str(pd.Timestamp(day).date()): a.pool_commitment(rows, FEATURES)
                          for day, rows in f.groupby("signal_date", sort=False)}}
    return {"value_holding_support": proof, "source_has_no_new_buy_flags": True}


def owners():
    values = SimpleNamespace(
        EXTENSIONS=(), SOURCES={"ALLOWED"},
        feature_binding=lambda: {"features": FEATURES},
        _bool=lambda s, n: s.astype(bool),
        diagnostic_columns=lambda m: ("native_mu",),
        raw_fields=lambda m, raw: {"native_mu": raw})
    raw_calls, state_calls = [], []
    def raw_predict(bundle, model_id, rows, reader):
        assert reader is None
        raw_calls.append((model_id, len(rows)))
        return rows.ret_20d.to_numpy(float)
    predictors = SimpleNamespace(raw_predict=raw_predict)
    owner_path = a.HERE.parent / "training/stateful_fusion.py"
    native_path = a.HERE.parent / "retained/a2_predict_then_optimize_20260928_r1/fusion_models.py"
    native_state = a._owned_function(native_path, "state_features", {"np": np})
    def state_fn(rows, x):
        state_calls.append((len(rows), rows.ticker.tolist()))
        return native_state(rows, x)
    namespace = {"np": np, "values": values, "_state": state_fn}
    fusion = SimpleNamespace(
        packet_for=lambda m: a.PACKET, ALLOWED_SOURCES={"ALLOWED"},
        join_packet=a._owned_function(owner_path, "join_packet", {"np": np}),
        state_surface=a._owned_function(owner_path, "state_surface", namespace),
        join_state=a._owned_function(owner_path, "join_state", {"np": np}),
        state_required=lambda m: m == "gate_linear")
    return (predictors, values, fusion), raw_calls, state_calls


def point_model():
    def forbidden(*args):
        raise AssertionError("old annual guard or fitting must never be invoked")
    return SimpleNamespace(native=object(), calibration={"sigma": .25},
                           mapped=lambda raw: (raw + 10., np.full(len(raw), .25)),
                           predict_frame=forbidden, fit=forbidden)


def test_import_and_cli_are_lazy():
    code = ("import sys; from scripts.research.a2.inference import consensus_original_cash12_test2026; "
            "assert 'scripts.research.a2.training.stateful_values' not in sys.modules; "
            "assert 'torch' not in sys.modules; print('LAZY')")
    assert subprocess.check_output([sys.executable, "-B", "-c", code], cwd=a.REPO, text=True).strip() == "LAZY"
    result = subprocess.run([sys.executable, "-B", "-m",
                             "scripts.research.a2.inference.consensus_original_cash12_test2026", "--help"],
                            cwd=a.REPO, text=True, capture_output=True, check=True)
    assert "--freeze" in result.stdout


def test_source_pins_are_existing_owner_sources():
    pins = a.source_pins()
    assert len(pins) == 10 and pins["consumer"] == a.ref(a.__file__)
    assert all(Path(item["path"]).is_file() and len(item["sha256"]) == 64 for item in pins.values())


@pytest.mark.parametrize("change,message", [
    (lambda f: f.update(start="2025-12-31"), "EXACT_EXPOSED"),
    (lambda f: f.update(end="2026-10-09"), "EXACT_EXPOSED"),
    (lambda f: f.update(status="FROZEN"), "EXPLICIT_TEST"),
    (lambda f: f.update(new_fit=1), "INFERENCE_ONLY"),
    (lambda f: f.update(strict_PIT_certified=True), "INFERENCE_ONLY"),
    (lambda f: f["input_read_columns"].append("y_open5"), "FEATURE_ONLY"),
    (lambda f: f.update(input_ref={"path": "different", "sha256": "2" * 64}), "EXACT_ACCEPTED"),
    (lambda f: f.update(source_pins={}), "SOURCE_CHANGED")])
def test_freeze_rejects_boundary_or_identity_change(tmp_path, monkeypatch, change, message):
    monkeypatch.setattr(a, "source_pins", lambda: PINS)
    f = freeze(tmp_path)
    a.validate_freeze(f)
    change(f)
    with pytest.raises(ValueError, match=message):
        a.validate_freeze(f)


def test_support_preserves_all_keys_including_unqualified_held_support(tmp_path):
    f = frame()
    a.validate_frame(f, freeze(tmp_path), support(f))
    assert f.ticker.tolist() == ["A", "B", "C"]


@pytest.mark.parametrize("case,message", [
    ("value", "VALUES_CHANGED"), ("duplicate", "DUPLICATE"), ("label", "NO_LABELS"),
    ("future", "FUTURE_FIRST"), ("calendar", "CALENDAR"), ("buy", "CAUSAL_HOLDING")])
def test_support_rejects_mutation(tmp_path, case, message):
    f = frame()
    proof = support(f)
    if case == "value":
        f.loc[0, FEATURES[0]] += 1
    elif case == "duplicate":
        f.loc[1, list(a.KEYS)] = f.loc[0, list(a.KEYS)]
    elif case == "label":
        f["y_open5"] = 1.
    elif case == "future":
        proof["value_holding_support"]["first_membership_by_ticker"]["A"] = "2026-01-03"
    elif case == "calendar":
        proof["value_holding_support"]["sessions"]["2026-01-05"] = {}
    else:
        proof["source_has_no_new_buy_flags"] = False
    with pytest.raises(ValueError, match=message):
        a.validate_frame(f, freeze(tmp_path), proof)


def test_physical_date_guard_precedes_hash_and_numeric_projection(tmp_path, monkeypatch):
    f = frame()
    f["signal_date"] = pd.Timestamp("2025-12-31")
    path = tmp_path / "outside.parquet"
    f.to_parquet(path, index=False)
    frozen = freeze(tmp_path)
    frozen["input_ref"] = {"path": str(path), "sha256": "wrong"}
    def forbidden(*args, **kwargs):
        raise AssertionError("numeric read/hash must follow physical date gate")
    monkeypatch.setattr(a, "sha", forbidden)
    import pyarrow.parquet as pq
    monkeypatch.setattr(pq, "read_table", forbidden)
    with pytest.raises(ValueError, match="PHYSICAL_INPUT_DATE"):
        a._load_frame(frozen, {})


def test_point_calls_frozen_raw_then_mapping_preserving_nan_and_sigma():
    own, raw_calls, _ = owners()
    f = frame()
    result = a.point_prediction(point_model(), {"native_model_id": "ridge"}, f, FEATURES, own)
    assert raw_calls == [("ridge", 2)]
    assert result[list(a.KEYS)].equals(f[list(a.KEYS)])
    assert result.prediction.tolist()[:2] == [11., 13.]
    assert result.value_sigma.tolist()[:2] == [.25, .25]
    assert result.prediction_qualified.tolist() == [True, True, False]
    assert np.isnan(result.prediction.iloc[2])


def test_point_rejects_nonfinite_qualified_features_before_predict():
    own, raw_calls, _ = owners()
    f = frame()
    f.loc[0, FEATURES[0]] = np.nan
    with pytest.raises(ValueError, match="NONFINITE_QUALIFIED"):
        a.point_prediction(point_model(), {"native_model_id": "ridge"}, f, FEATURES, own)
    assert not raw_calls


@pytest.mark.parametrize("method", a.FUSIONS)
def test_fusion_reuses_original_packet_math_and_full_domain_state(method):
    own, _, state_calls = owners()
    f = frame()
    experts = {name: f[list(a.KEYS)].assign(prediction=[1. + i, 3. + i, np.nan])
               for i, name in enumerate(a.PACKET)}
    calls = []
    def predict(x, state):
        calls.append((x.copy(), state.copy()))
        return x.mean(axis=1) + state[:, 0]
    model = SimpleNamespace(native=SimpleNamespace(predict=predict), sigma=.375)
    result = a.fusion_prediction(model, method, f, experts, own)
    x, state = calls[0]
    np.testing.assert_array_equal(x, [[1., 2., 3.], [3., 4., 5.]])
    if method == "gate_linear":
        assert state_calls == [(2, ["A", "B"])]
        np.testing.assert_allclose(state[:, 0], [2., 2.])
        assert result.prediction.tolist()[:2] == [4., 6.]
    else:
        assert not state_calls
        np.testing.assert_array_equal(state, np.zeros((2, 4)))
        assert result.prediction.tolist()[:2] == [2., 4.]
    assert result.prediction_qualified.tolist() == [True, True, False]
    assert np.isnan(result.prediction.iloc[2])
    np.testing.assert_array_equal(result.value_sigma.iloc[:2], [.375, .375])
    with pytest.raises(ValueError, match="EXACT_ORIGINAL_PACKET3"):
        a.fusion_prediction(model, method, f, {"ridge": experts["ridge"]}, own)


def test_resume_validates_saved_output_hash_and_preserves_stray(tmp_path):
    output, receipt = tmp_path / "out.bin", tmp_path / "receipt.json"
    identity = {"head": "synthetic"}
    assert a.resume_output(receipt, output, identity) is None
    output.write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="UNRECEIPTED"):
        a.resume_output(receipt, output, identity)
    saved = {"status": "COMPLETE", "identity": identity, "output": {"frame_ref": a.ref(output)}}
    receipt.write_text(json.dumps(saved), encoding="utf-8")
    assert a.resume_output(receipt, output, identity) == saved["output"]
    output.write_bytes(b"changed")
    with pytest.raises(ValueError, match="IDENTITY_OR_BYTES_CHANGED"):
        a.resume_output(receipt, output, identity)


def test_synthetic_all13_publication_and_second_run_has_zero_prediction(tmp_path, monkeypatch):
    from scripts.common import storage_paths
    frozen = freeze(tmp_path)
    frozen["head_binding_ref"] = {"synthetic": "binding"}
    frozen["training_acceptance_ref"] = {"synthetic": "acceptance"}
    frozen["support_manifest_ref"] = {"synthetic": "support"}
    frozen["original_value_outputs_ref"] = {"synthetic": "old_outputs"}
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(frozen), encoding="utf-8")
    monkeypatch.setattr(a, "source_pins", lambda: PINS)
    monkeypatch.setattr(storage_paths, "assert_safe_output_path", lambda path, **kwargs: None)
    own, raw_calls, state_calls = owners()
    metadata_by_path, heads, loaded = {}, {}, []
    for head in a.HEADS:
        model_path, receipt_path = tmp_path / (head.replace("::", "_") + ".bin"), tmp_path / (head.replace("::", "_") + ".json")
        model_path.write_bytes(("synthetic " + head).encode())
        token = a.sha(model_path)
        receipt = {"status": "TRAINED", "year": 2025, "model_id": head.split("::")[-1],
                   "native_model_id": head, "reuse_tuple_sha256": token}
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        heads[head] = {"model_ref": a.ref(model_path), "receipt_ref": a.ref(receipt_path), "reuse_tuple_sha256": token}
        metadata_by_path[str(receipt_path)] = receipt
    original = {"source_ref": {"synthetic": "source"}, "authority_ref": {"synthetic": "authority"}}
    monkeypatch.setattr(a, "_bindings", lambda f: (heads, original, {}))
    monkeypatch.setattr(a, "metadata", lambda r: metadata_by_path[r["path"]])
    monkeypatch.setattr(a, "_load_frame", lambda *args: frame())
    monkeypatch.setattr(a, "_owners", lambda: own)
    def load_model(head, *args):
        loaded.append(head)
        return (SimpleNamespace(native=SimpleNamespace(predict=lambda x, s: x.mean(axis=1)), sigma=.375)
                if head.startswith("fusion::") else point_model())
    monkeypatch.setattr(a, "_load_model", load_model)
    result = a.run(freeze_path)
    assert result["computed_heads"] == list(a.HEADS) and not result["reused_heads"]
    assert loaded == list(a.HEADS) and len(raw_calls) == 9
    doc = json.loads(Path(result["value_outputs_ref"]["path"]).read_text(encoding="utf-8"))
    assert len(doc["outputs"]) == 13 and doc["requested_heads"] == 12 and doc["support_heads"] == ["lgb"]
    assert doc["new_fit"] == doc["account"] == 0 and doc["primary_metrics"] is None
    for head, entry in doc["outputs"].items():
        assert entry["rows"] == 3 and entry["qualified_rows"] == 2
        data = pd.read_parquet(entry["frame_ref"]["path"])
        assert data.ticker.tolist() == ["A", "B", "C"]
        assert set(data.prediction_role) == {"FROZEN_FORWARD_INFERENCE"}
        assert set(data.evaluation_year) == {2026} and set(data.year) == {2025}
        assert set(data.model_sha256) == {heads[head]["model_ref"]["sha256"]}
    def forbidden(*args, **kwargs):
        raise AssertionError("resume cannot re-read numeric inputs, load models or predict")
    monkeypatch.setattr(a, "_load_frame", forbidden)
    monkeypatch.setattr(a, "_owners", forbidden)
    monkeypatch.setattr(a, "_load_model", forbidden)
    resumed = a.run(freeze_path)
    assert resumed["reused_heads"] == list(a.HEADS) and not resumed["computed_heads"]
    assert resumed["value_outputs_ref"] == result["value_outputs_ref"]
