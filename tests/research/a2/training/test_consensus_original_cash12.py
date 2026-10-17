"""Synthetic provenance, clocks and original packet3 transport; never fit models."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import numpy as np
import pytest
from scripts.research.a2.training import consensus_original_cash12 as a


def frozen(tmp_path):
    day = date(2024, 10, 7)
    dates = []
    while day <= date(2024, 12, 31):
        if day.weekday() < 5 and day.isoformat() not in ("2024-11-28", "2024-12-25"):
            dates.append(day.isoformat())
        day += timedelta(days=1)
    columns = [*a.META, "y_open5", *a.EXPERTS, *a.STATE]
    inputs = {stage: {"path": str(tmp_path / (stage + ".parquet")), "sha256": "1" * 64,
                      "rows": 2, "columns": columns} for stage in ("train", "calibration")}
    return {"schema": a.SCHEMA, "status": "AUTHORIZED_PRE2025_TRAINING_ONLY",
            "research_id": "SYNTHETIC_PACKET3", "parent_research_id": "SYNTHETIC_PARENT",
            "run_dir": str(tmp_path), "year": 2025, "methods": list(a.METHODS),
            "packet": list(a.PACKET), "seed": a._literal("SEED"),
            "label_definition": a._literal("LABEL"),
            "feature_binding": {"features": ["SYN_%02d" % i for i in range(32)]},
            "train_maturity_exclusive": a.TRAIN_END, "calibration_maturity_exclusive": a.CAL_END,
            "calibration_sessions": dates, "inputs": inputs, "membership_sha256": "2" * 64,
            "input_binding_sha256": "3" * 64, "state_basis": a.STATE_BASIS,
            "state_source_ref": {"path": str(tmp_path / "state.json"), "sha256": "4" * 64},
            "expert_oof_pins": [{"model_id": m, "year": y, "prediction_role": "MODEL_OOF",
                                 "membership_sha256": "2" * 64, "input_binding_sha256": "3" * 64,
                                 "publication_ref": {"path": str(tmp_path / (m + str(y) + ".json")),
                                                     "sha256": "5" * 64}}
                                for m in a.PACKET for y in range(2021, 2025)],
            "source_pins": a.source_pins(), "allowed_feature_sources": ["SYNTHETIC"],
            "dependency_paths": [], "prior_fit_units": 7, "max_fit_units": 30, "max_new_fit_units": 15}


def rows(f, stage="train"):
    signal = "2024-03-01" if stage == "train" else f["calibration_sessions"][0]
    mature = "2024-03-08" if stage == "train" else f["calibration_sessions"][5]
    return [{"signal_date": signal, "ticker": ticker, "label_mature_date": mature,
             "feature_available": True, "label_available": True, "account_event_unhandled": False,
             "feature_source": "SYNTHETIC", "label_coordinate": f["label_definition"]}
            for ticker in ("SYN_A", "SYN_B")]


def test_exact_frozen_packet_and_past_metadata(tmp_path):
    f = frozen(tmp_path)
    assert len(a.validate_freeze(f)) == 60
    a.validate_metadata(rows(f), f, "train")
    a.validate_metadata(rows(f, "calibration"), f, "calibration")


@pytest.mark.parametrize("field,value", [
    ("year", 2026), ("packet", ["ridge", "hgb", "xgb", "lgb", "cat"]),
    ("methods", ["equal"]), ("seed", 42), ("train_maturity_exclusive", "2024-10-08"),
    ("calibration_maturity_exclusive", "2026-01-01"),
    ("state_basis", "LABEL_FILTERED_SUBSET"), ("prior_fit_units", -1)])
def test_reject_scientific_or_clock_drift(tmp_path, field, value):
    f = frozen(tmp_path)
    f[field] = value
    with pytest.raises(ValueError):
        a.validate_freeze(f)


def test_reject_old_pool_and_calibration_as_expert_oof(tmp_path):
    f = frozen(tmp_path)
    f["expert_oof_pins"][0]["membership_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="OLD_POOL"):
        a.validate_freeze(f)
    f = frozen(tmp_path)
    f["expert_oof_pins"][0]["prediction_role"] = "PAST_HELDOUT_CALIBRATION_USED_FOR_FIT_NOT_OOF_EVALUATION"
    with pytest.raises(ValueError, match="CALIBRATION_AS_OOF"):
        a.validate_freeze(f)


@pytest.mark.parametrize("change", [
    {"label_mature_date": "2024-10-07"}, {"signal_date": "2025-01-01"},
    {"feature_available": False}, {"account_event_unhandled": True},
    {"label_coordinate": "WRONG_TARGET"}, {"feature_source": "UNAPPROVED"}])
def test_reject_metadata_before_value_decoding(tmp_path, change):
    f = frozen(tmp_path)
    r = rows(f)
    r[0].update(change)
    with pytest.raises(ValueError):
        a.validate_metadata(r, f, "train")


def test_duplicate_and_noncalibration_keys_rejected(tmp_path):
    f = frozen(tmp_path)
    r = rows(f)
    r[1] = deepcopy(r[0])
    with pytest.raises(ValueError, match="DUPLICATE"):
        a.validate_metadata(r, f, "train")
    r = rows(f, "calibration")
    r[0]["signal_date"] = "2024-10-06"
    with pytest.raises(ValueError, match="NONCALIBRATION"):
        a.validate_metadata(r, f, "calibration")


def test_original_three_expert_worker_transport_only(tmp_path):
    f = frozen(tmp_path)
    calls = []
    sentinel = object()
    values = SimpleNamespace(_fit_job=lambda *args, **kw: calls.append((args, kw)) or sentinel)
    worker = object()
    owner = SimpleNamespace(_fusion_worker=worker,
                            _fit_arrays=lambda *args, **kw: calls.append((args, kw)) or sentinel)
    x, y, state = np.ones((3, 3)), np.ones(3), np.zeros((3, 4))
    for method in ("convex", "stack_ridge", "gate_linear"):
        assert a._fit_native(method, x, y, state, f, tmp_path / "FIT_LOG.jsonl",
                             {}, "SYN", (values, owner, None)) is sentinel
        args, kw = calls[-1]
        assert args[4] is state and np.equal(args[5], 1).all()
        assert args[8] is None and args[7] == list(a.EXPERTS)
        assert kw["worker_target"] is worker and kw["year"] == 2025 and kw["prior"] == 7
    assert a._fit_native("equal", x, y, state, f, tmp_path / "FIT_LOG.jsonl",
                         {}, "SYN", (values, owner, None)) is sentinel
    args, kw = calls[-1]
    assert kw["packet_width"] == 3 and args[0] == "equal"
    assert not (tmp_path / "FIT_LOG.jsonl").exists()


def test_physical_future_clock_rejected_before_hash_or_numeric_read(tmp_path, monkeypatch):
    f = frozen(tmp_path)
    path = Path(f["inputs"]["train"]["path"])
    path.write_bytes(b"SYNTHETIC_PLACEHOLDER_NOT_A_REAL_DATASET")
    stat = SimpleNamespace(has_min_max=True, null_count=0, min=date(2025, 1, 1), max=date(2025, 1, 1))
    meta = SimpleNamespace(num_rows=2, row_group=lambda i: SimpleNamespace(column=lambda j: SimpleNamespace(statistics=stat)))
    pf = SimpleNamespace(metadata=meta, schema_arrow=SimpleNamespace(names=f["inputs"]["train"]["columns"]), num_row_groups=1)
    package = ModuleType("pyarrow")
    package.__path__ = []
    parquet = ModuleType("pyarrow.parquet")
    parquet.ParquetFile = lambda p: pf
    parquet.read_table = lambda *args, **kw: pytest.fail("Numerical decoding happened before clock rejection")
    package.parquet = parquet
    monkeypatch.setitem(sys.modules, "pyarrow", package)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", parquet)
    monkeypatch.setattr(a, "sha", lambda p: pytest.fail("Whole input hash happened before clock rejection"))
    with pytest.raises(ValueError, match="PHYSICAL_META_CLOCK"):
        a._inputs(f)



def test_saved_calibration_rows_and_reuse_hash(tmp_path):
    from datetime import datetime
    import pyarrow.parquet as pq
    keys = [{"signal_date": datetime(2024, 10, 7), "ticker": "SYN_A",
             "label_mature_date": datetime(2024, 10, 14)},
            {"signal_date": datetime(2024, 10, 8), "ticker": "SYN_B",
             "label_mature_date": datetime(2024, 10, 15)}]
    path = tmp_path / "calibration_predictions.parquet"
    reference = a.save_calibration_predictions(path, keys, [.1, .2], [.03, .11], .07)
    actual = pq.read_table(path).to_pylist()
    assert reference["rows"] == 2 and reference["prediction_role"] == "CALIBRATION_NOT_OOF"
    assert [{k: r[k] for k in keys[0]} for r in actual] == keys
    assert [r["y_open5"] for r in actual] == [.1, .2]
    assert [r["prediction"] for r in actual] == [.03, .11]
    assert np.allclose([r["residual"] for r in actual], [.07, .09])
    assert [r["value_sigma"] for r in actual] == [.07, .07]
    assert all(r["prediction_role"] == "CALIBRATION_NOT_OOF" for r in actual)
    receipt = {"calibration_predictions_ref": reference}
    a.verify_calibration_predictions(receipt, path, 2)
    with path.open("ab") as stream:
        stream.write(b"SYNTHETIC_CORRUPTION")
    with pytest.raises(ValueError, match="BYTES_CHANGED"):
        a.verify_calibration_predictions(receipt, path, 2)


def test_completed_slot_requires_non_oof_calibration_receipt(tmp_path):
    path = tmp_path / "calibration_predictions.parquet"
    with pytest.raises(ValueError, match="CALIBRATION_RECEIPT"):
        a.verify_calibration_predictions({}, path, 2)
    with pytest.raises(ValueError, match="CALIBRATION_RECEIPT"):
        a.verify_calibration_predictions(
            {"calibration_predictions_ref": {"path": str(path), "rows": 2,
                                             "prediction_role": "MODEL_OOF"}}, path, 2)


@pytest.mark.parametrize("target,prediction,sigma", [
    ([.1, .2], [.1], .1), ([.1, .2], [.1, float("nan")], .1),
    ([.1, .2], [.1, .2], 0.)])
def test_invalid_calibration_cannot_create_artifact(tmp_path, target, prediction, sigma):
    path = tmp_path / "calibration_predictions.parquet"
    keys = [{"signal_date": "2024-10-07", "ticker": "SYN_A", "label_mature_date": "2024-10-14"}] * 2
    with pytest.raises(ValueError, match="INVALID_SAVED_CALIBRATION"):
        a.save_calibration_predictions(path, keys, target, prediction, sigma)
    assert not path.exists()


def test_cli_main_dispatches_to_canonical_module_without_fit(monkeypatch):
    import importlib
    called = []
    canonical = "scripts.research.a2.training.consensus_original_cash12"
    argv = ["--freeze", "SYNTHETIC_NOT_OPENED.json", "--method", "equal"]
    target = SimpleNamespace(main=lambda passed: called.append(("main", passed)) or 37)
    monkeypatch.setattr(a, "__name__", "__main__")
    monkeypatch.setattr(importlib, "import_module",
                        lambda name: called.append(("import", name)) or target)
    monkeypatch.setattr(a, "fit_one", lambda *args: pytest.fail("Entry module must not train"))
    assert a.main(argv) == 37
    assert called == [("import", canonical), ("main", argv)]
    assert a.OriginalCashFusionFit.__module__ == canonical
