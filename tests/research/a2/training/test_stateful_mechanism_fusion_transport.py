"""Synthetic spawn transport only: no estimator/scaler fit or real data."""
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import sys
import tempfile
import traceback
import types

import pytest

NATIVE = (
    "scripts.research.a2.retained."
    "a2_predict_then_optimize_20260928_r1.fusion_models"
)


def _forbid(*args, **kwargs):
    raise AssertionError("NO_FIT_OR_REDISPATCH_ALLOWED")


def _result_only_worker(
    pipe, operation, model_id, x, payload, dates, quantile,
    dependencies, features, observed,
):
    """Original objects; RESULT then immediate exit, like the real worker."""
    try:
        import numpy as np
        from scripts.research.a2.training import stateful_fusion as owner
        from scripts.research.a2.training import stateful_mechanism_models as models

        assert operation == "fusion"
        native = owner._native(dependencies)
        for name in (
            "Fusion", "StandardScaler", "Ridge", "ElasticNet",
            "HistGradientBoostingRegressor", "MLPRegressor",
        ):
            getattr(native, name).fit = _forbid
        native.minimize = _forbid
        native.torch.optim.Adam = _forbid

        method = payload["method"]
        obj = native.Fusion(method, seed=20260928)
        obj.members_count = 3
        obj.fitted_rows = 0
        if method == "convex":
            obj.fixed = np.array([0.5, 0.25, 0.25])
        else:
            # Synthetic fitted attributes, with no StandardScaler.fit call.
            scale = native.StandardScaler()
            scale.mean_ = np.zeros(4)
            scale.var_ = scale.scale_ = np.ones(4)
            scale.n_features_in_ = 4
            scale.n_samples_seen_ = 2
            obj.scale = scale
            obj.gate = native.Gate(3, hidden=8)
            with native.torch.no_grad():
                for parameter in obj.gate.parameters():
                    parameter.fill_(0.02)
            obj.gate.eval()

        metadata = {
            "source_pins": models.source_pins(),
            "actual_fit_count": 0,
            "scaler_fit_count": 0,
        }
        wrapped = models.FusionModel(
            method, obj, metadata, tuple(dependencies)
        )
        pipe.send(("RESULT", wrapped, metadata))
        # No FIT_START, ACK, sleep, tensor conversion or storage workaround.
    except BaseException as exc:
        pipe.send(("ERROR", type(exc).__name__, str(exc)))
    finally:
        pipe.close()


def _tree(path):
    return {
        str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.rglob("*") if p.is_file()
    }


def _fresh_probe(pipe, run_text, method, alias, mode):
    """Fresh parent: physical_job, not the test, must preload native Fusion."""
    try:
        import numpy as np
        import joblib
        from scripts.research.a2.training import stateful_mechanism as root
        from scripts.research.a2.training import stateful_mechanism_models as models
        from scripts.research.a2.training import stateful_fusion as owner
        from scripts.research.a2.training.stateful_value_extensions import (
            TORCH_SNAPSHOT,
        )

        assert NATIVE not in sys.modules
        dependencies = [str(TORCH_SNAPSHOT)]
        for dependency in dependencies:
            if dependency not in sys.path:
                sys.path.append(dependency)
        before_path = list(sys.path)
        sentinel = types.ModuleType("common")
        if alias == "sentinel":
            sys.modules["common"] = sentinel
        else:
            sys.modules.pop("common", None)

        def alias_restored():
            assert list(sys.path) == before_path
            if alias == "sentinel":
                assert sys.modules["common"] is sentinel
            else:
                assert "common" not in sys.modules

        pins = models.source_pins()
        design = {
            **root.AUTHORITY,
            "scientific_identity": root.IDENTITY,
            "account_authorized": False,
            "source_activated": False,
            "dependency_paths": dependencies,
            "model_specifications": {"source_pins": pins},
        }
        spec = {
            "slot_id": "TRANSPORT_" + method,
            "method": method,
            "family": "fusion_" + method,
            "capacity": "MID",
            "seed": 20260928,
            "objective": "ADVANTAGE",
            "group": "ENTRY",
            "year": 2024,
            "bucket": "FUSION_GATING",
        }
        run = Path(run_text)
        # Production writers require backtest_root. This test uses its approved
        # independent cache; adapt only IO, never worker/recv/model behavior.
        from scripts.common.storage_paths import assert_safe_output_path

        def synthetic_path(path):
            path = Path(path)
            assert path.resolve().is_relative_to(run.resolve())
            assert_safe_output_path(path, kind="cache")
            path.parent.mkdir(parents=True, exist_ok=True)
            return path

        def synthetic_save(path, value):
            synthetic_path(path).write_text(
                json.dumps(root.clean(value), sort_keys=True, allow_nan=False,
                           default=str), encoding="utf-8"
            )

        def synthetic_append(path, value):
            with synthetic_path(path).open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
                stream.flush()

        root.save = synthetic_save
        root.fit_owner._append = synthetic_append
        frozen = run / "FROZEN_DESIGN.json"
        if not frozen.exists():
            frozen.write_text(
                json.dumps(design, sort_keys=True), encoding="utf-8"
            )
        x = np.array([[0.01, 0.0, 0.02], [-0.02, 0.0, 0.01]])
        x[:, 1] = (x[:, 0] + x[:, 2]) / 2
        state = np.zeros((2, 4))
        target = np.zeros(2)
        weights = np.ones(2)
        dates = np.array(["2023-12-27", "2023-12-28"], dtype="datetime64[D]")
        extra = {"method": method, "state": state}
        root.fit_owner._component_start = _forbid
        root.fit_owner.FIT_TIMEOUT = 45

        calls = []
        original_native = owner._native

        def counted_native(*args, **kwargs):
            native = original_native(*args, **kwargs)
            alias_restored()
            calls.append(native)
            return native

        owner._native = counted_native
        if mode == "negative":
            # Only absence is a negative control. An empty sentinel makes
            # "from common import *" legal and must not expect this exception.
            assert alias == "absent"
            receipt = {
                "fit_units": 0,
                "receipt_path": str(run / "negative_receipt.json"),
            }
            payload = {**spec, "target": target, "weights": weights}
            try:
                root.fit_owner._fit_job(
                    "fusion", spec["slot_id"], x, payload, dates, None,
                    dependencies, ["a", "virtual", "b"], None,
                    log=run / "FIT_LOG.jsonl",
                    auth={"max_fit_units": 1200},
                    prior=0, year=2024, tuple_sha="SYNTHETIC",
                    receipt=receipt, worker_target=_result_only_worker,
                )
            except ModuleNotFoundError as exc:
                assert exc.name == "common"
            else:
                raise AssertionError("NEGATIVE_CONTROL_DID_NOT_FAIL")
            assert receipt["fit_units"] == 0 and calls == []
            assert not (run / "FIT_LOG.jsonl").exists()
            alias_restored()
            assert models.source_pins() == pins
            pipe.send({"ok": True})
            return

        if mode in ("trained", "failed"):
            root.fit_owner._fit_job = _forbid
        before = _tree(run)
        model, receipt = root.physical_job(
            run, design, spec, x, target, weights, dates,
            ["a", "virtual", "b"],
            operation="fusion", worker=_result_only_worker,
            payload_extra=extra,
        )
        if mode == "failed":
            assert model is None and receipt["status"] == "FAILED"
            assert receipt["fit_units"] == 1
            assert _tree(run) == before
            assert calls == [] and NATIVE not in sys.modules
        else:
            assert receipt["status"] == "TRAINED", receipt.get("error")
            assert receipt["fit_units"] == 0
            assert len(calls) == 1
            native = calls[0]
            assert type(model.estimator) is native.Fusion
            if method.startswith("gate_"):
                assert type(model.estimator.gate) is native.Gate
                assert all(
                    isinstance(p, native.torch.nn.Parameter)
                    for p in model.estimator.gate.parameters()
                )
            prediction = models.predict_fusion(
                model, {"experts": x, "state": state}
            )["mean"]
            assert np.isfinite(prediction).all()
            loaded = joblib.load(Path(receipt["model_path"]))
            assert type(loaded.estimator) is native.Fusion
            np.testing.assert_array_equal(
                prediction,
                models.predict_fusion(
                    loaded, {"experts": x, "state": state}
                )["mean"],
            )
            if mode == "trained":
                assert _tree(run) == before
            events = root.fit_owner._events(run / "FIT_LOG.jsonl")
            assert not any(e.get("event") == "FIT_STARTED" for e in events)
        alias_restored()
        assert models.source_pins() == pins
        pipe.send({"ok": True})
    except BaseException:
        pipe.send({"ok": False, "error": traceback.format_exc()})
    finally:
        pipe.close()


def _probe(run, method, alias, mode):
    context = mp.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_fresh_probe, args=(child, str(run), method, alias, mode)
    )
    process.start()
    child.close()
    try:
        assert parent.poll(120), "SYNTHETIC_PROBE_TIMEOUT"
        result = parent.recv()  # Small ordinary Python metadata; no model.
        process.join(15)
        assert process.exitcode == 0
        assert result["ok"], result.get("error")
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)
        parent.close()


@pytest.fixture
def cache_run():
    from scripts.common.storage_paths import resolve, assert_safe_output_path
    repo = Path(__file__).resolve().parents[4]
    paths = resolve(repo)
    cache = paths.cache_root / "research" / (
        "V24_A_STATEFUL_ACTION_RISK_FULL_BREADTH_R10"
    ) / "fusion_transport_synthetic"
    assert_safe_output_path(cache, kind="cache", paths=paths)
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        yield Path(directory)


def test_fresh_unpreloaded_negative_control(cache_run):
    _probe(cache_run, "convex", "absent", "negative")


@pytest.mark.parametrize("method", ["convex", "gate_mlp"])
@pytest.mark.parametrize("alias", ["absent", "sentinel"])
def test_physical_job_transport_exact_reuse_and_failed_custody(
    cache_run, method, alias
):
    _probe(cache_run, method, alias, "new")
    _probe(cache_run, method, alias, "trained")

    # Test-owned synthetic fixture; no genuine failed receipt is rewritten.
    receipt_path = (
        cache_run / "models" / "mechanism" /
        ("TRANSPORT_" + method) / "fit_receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    Path(receipt["model_path"]).unlink()
    receipt.update(status="FAILED", fit_units=1, error="SYNTHETIC_OLD_FAILURE")
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True), encoding="utf-8"
    )
    _probe(cache_run, method, alias, "failed")
