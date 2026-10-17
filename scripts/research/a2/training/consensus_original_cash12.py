"""Original three-expert cash-head fusion over frozen, pre-2025 projections.

Import is stdlib-only. This adapter owns provenance/transport, while the retained
fusion owner owns every combination, estimator, state formula and calibration.
"""
from __future__ import annotations
import argparse
import ast
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path

SCHEMA = "CONSENSUS_ORIGINAL_CASH12_FUSION_FREEZE_R1"
METHODS = ("equal", "convex", "stack_ridge", "gate_linear")
PACKET = ("ridge", "hgb", "lgb")
STATE = tuple("state_" + str(i) for i in range(4))
EXPERTS = tuple("expert_" + m for m in PACKET)
META = ("signal_date", "ticker", "label_mature_date", "feature_available",
        "label_available", "account_event_unhandled", "feature_source", "label_coordinate")
TRAIN_END = "2024-10-07"
CAL_END = "2025-01-01"
STATE_BASIS = "FULL_CAUSAL_INFERENCE_POOL_BEFORE_LABEL_SUBSET"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path)}


def source_pins():
    retained = REPO / "scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1"
    paths = {"adapter": Path(__file__), "fusion_owner": HERE / "stateful_fusion.py",
             "value_owner": HERE / "stateful_values.py", "fit_lock_owner": HERE / "consensus_predictors.py",
             "input_constants": HERE / "stateful_inputs.py",
             "native_fusion": retained / "fusion_models.py", "native_common": retained / "common.py"}
    return {name: ref(path) for name, path in paths.items()}


def _literal(name):
    tree = ast.parse((HERE / "stateful_values.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("OWNER_CONSTANT_MISSING:" + name)


def _day(value):
    return date.fromisoformat(str(value)[:10]).isoformat()


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def pinned_metadata(reference):
    path = Path(reference["path"])
    need(path.is_absolute() and path.resolve(strict=True) == path.absolute(), "UNSAFE_METADATA_PATH")
    need(path.stat().st_size <= 1024 * 1024 and sha(path) == reference["sha256"], "METADATA_PIN_CHANGED")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_freeze(frozen):
    need(frozen["schema"] == SCHEMA and frozen["status"] == "AUTHORIZED_PRE2025_TRAINING_ONLY",
         "AUTHORIZED_ORIGINAL_PACKET3_FREEZE_REQUIRED")
    need(frozen["research_id"] and frozen["research_id"] != frozen["parent_research_id"], "NEW_BRANCH_IDENTITY_REQUIRED")
    need(frozen["year"] == 2025 and tuple(frozen["packet"]) == PACKET
         and len(frozen["methods"]) == 4 and set(frozen["methods"]) == set(METHODS), "EXACT_ORIGINAL_FOUR_PACKET3")
    need(frozen["seed"] == _literal("SEED") and frozen["label_definition"] == _literal("LABEL"),
         "ORIGINAL_SEED_OR_TARGET_CHANGED")
    need(_day(frozen["train_maturity_exclusive"]) == TRAIN_END
         and _day(frozen["calibration_maturity_exclusive"]) == CAL_END, "ORIGINAL_2025_BOUNDARIES_REQUIRED")
    sessions = [_day(v) for v in frozen["calibration_sessions"]]
    need(len(sessions) == len(set(sessions)) == 60 and sessions == sorted(sessions)
         and sessions[0] == TRAIN_END and sessions[-1] == "2024-12-31", "EXACT_FROZEN_60_CALIBRATION_SESSIONS")
    features = frozen["feature_binding"]["features"]
    need(len(features) == len(set(features)) == 32, "SOURCE_FEATURE32_BINDING_REQUIRED")
    need(frozen["source_pins"] == source_pins(), "FROZEN_ADAPTER_OR_OWNER_SOURCE_CHANGED")
    need(frozen["state_basis"] == STATE_BASIS, "STATE_MUST_PRECEDE_LABEL_SUBSET")
    need(_hash(frozen["membership_sha256"]) and _hash(frozen["input_binding_sha256"]), "POOL_BINDINGS_REQUIRED")
    for key in ("train", "calibration"):
        r = frozen["inputs"][key]
        need(Path(r["path"]).is_absolute() and _hash(r["sha256"]) and type(r["rows"]) is int and r["rows"] >= 2,
             "FROZEN_INPUT_REFERENCE_REQUIRED")
        need(len(r["columns"]) == len(set(r["columns"]))
             and set((*META, "y_open5", *EXPERTS, *STATE)) <= set(r["columns"]), "PREPARED_INPUT_SCHEMA")
    pins = frozen["expert_oof_pins"]
    need(len(pins) == 12 and {(p["model_id"], p["year"]) for p in pins}
         == {(m, y) for m in PACKET for y in range(2021, 2025)}, "EXACT_2021_2024_PACKET3_OOF_PINS")
    for p in pins:
        need(p["prediction_role"] == "MODEL_OOF" and p["membership_sha256"] == frozen["membership_sha256"]
             and p["input_binding_sha256"] == frozen["input_binding_sha256"], "NO_OLD_POOL_OR_CALIBRATION_AS_OOF")
    need(type(frozen["prior_fit_units"]) is int and frozen["prior_fit_units"] >= 0
         and type(frozen["max_fit_units"]) is int and frozen["max_fit_units"] > frozen["prior_fit_units"]
         and type(frozen["max_new_fit_units"]) is int and frozen["max_new_fit_units"] > 0, "FINITE_FIT_BUDGET_REQUIRED")
    need(frozen.get("strict_PIT_certified", False) is False, "NO_PIT_PROMOTION")
    return sessions


def validate_metadata(rows, frozen, stage):
    """Check only keys, clocks and qualifications before numerical decoding."""
    sessions = set(_day(v) for v in frozen["calibration_sessions"])
    keys = set()
    allowed = set(frozen["allowed_feature_sources"])
    need(allowed, "ALLOWED_FEATURE_SOURCES_REQUIRED")
    for row in rows:
        signal, mature = _day(row["signal_date"]), _day(row["label_mature_date"])
        key = (signal, str(row["ticker"]))
        need(key not in keys, "DUPLICATE_META_KEYS")
        keys.add(key)
        need("2021-01-01" <= signal < CAL_END and signal <= mature, "PRIOR_ANNUAL_OOF_ROWS_ONLY")
        if stage == "train":
            need(signal < TRAIN_END and mature < TRAIN_END, "LATE_TRAIN_SIGNAL_OR_LABEL")
        else:
            need(stage == "calibration" and signal in sessions and mature < CAL_END, "LATE_OR_NONCALIBRATION_ROW")
        need(row["feature_available"] is True and row["label_available"] is True
             and row["account_event_unhandled"] is False, "UNQUALIFIED_META_ROW")
        need(row["feature_source"] in allowed and row["label_coordinate"] == frozen["label_definition"],
             "META_SOURCE_OR_LABEL_CHANGED")
    need(len(keys) >= 2, "INSUFFICIENT_PAST_OOF_ROWS")


def _publication_pins(frozen):
    for pin in frozen["expert_oof_pins"]:
        pub = pinned_metadata(pin["publication_ref"])
        year, model = pin["year"], pin["model_id"]
        need(pub["status"] == "PUBLISHED" and pub["year"] == year and pub["model_id"] == model
             and pub["horizon"] == pub["joint_horizon"] == 5
             and pub.get("prediction_role", "MODEL_OOF") == "MODEL_OOF"
             and pub["test_2026_rows_read"] == 0, "UNQUALIFIED_EXPERT_PUBLICATION")
        fit = pinned_metadata({"path": pub["fit_receipt_path"], "sha256": pub["fit_receipt_sha256"]})
        reuse = fit["reuse_tuple"]
        need(fit["status"] == "TRAINED" and fit["year"] == year and fit["model_id"] == model
             and fit["reuse_tuple_sha256"] == pub["reuse_tuple_sha256"]
             and fit["model_sha256"] == pub["model_sha256"], "EXPERT_FIT_IDENTITY_CHANGED")
        need(reuse["membership_sha256"] == frozen["membership_sha256"]
             and reuse["input_binding_sha256"] == frozen["input_binding_sha256"]
             and _day(reuse["calibration_maturity_exclusive"]) == f"{year}-01-01"
             and _day(reuse["train_maturity_exclusive"]) < f"{year}-01-01", "EXPERT_NOT_SAME_POOL_PAST_OOF")


def _inputs(frozen):
    import pyarrow.parquet as pq
    import numpy as np
    arrays = {}
    for stage in ("train", "calibration"):
        r = frozen["inputs"][stage]
        path = Path(r["path"])
        need(path.is_absolute() and path.resolve(strict=True) == path.absolute(), "UNSAFE_PREPARED_INPUT")
        pf = pq.ParquetFile(path)
        need(pf.metadata.num_rows == r["rows"] and pf.schema_arrow.names == r["columns"], "INPUT_SCHEMA_OR_ROWS_CHANGED")
        boundary = TRAIN_END if stage == "train" else CAL_END
        # Footer date statistics are inspected before hashing/decoding the value columns.
        for clock in ("signal_date", "label_mature_date"):
            col = pf.schema_arrow.names.index(clock)
            for i in range(pf.num_row_groups):
                st = pf.metadata.row_group(i).column(col).statistics
                need(st is not None and st.has_min_max and st.null_count == 0
                     and "2021-01-01" <= _day(st.min) <= _day(st.max) < boundary,
                     "PHYSICAL_META_CLOCK_OUTSIDE_STAGE")
        need(sha(path) == r["sha256"], "FROZEN_PREPARED_INPUT_CHANGED")
        meta = pq.read_table(path, columns=list(META)).to_pylist()
        validate_metadata(meta, frozen, stage)
        if stage == "calibration":
            arrays["calibration_keys"] = [{k: row[k] for k in ("signal_date", "ticker", "label_mature_date")} for row in meta]
        numeric = pq.read_table(path, columns=["y_open5", *EXPERTS, *STATE]).to_pandas()
        values = numeric.to_numpy(float)
        need(np.isfinite(values).all(), "MISSING_EXPERT_LABEL_OR_STATE_NO_ROW_DROP")
        arrays[stage] = (values[:, 1:4].copy(), values[:, 0].copy(), values[:, 4:8].copy())
    return arrays


def save_calibration_predictions(path, keys, target, prediction, sigma):
    """Persist the already evaluated heldout rows; never invoke a predictor."""
    import math
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    path = Path(path)
    y, raw = np.asarray(target, float), np.asarray(prediction, float)
    need(y.ndim == raw.ndim == 1 and len(keys) == len(y) == len(raw) >= 2
         and np.isfinite(y).all() and np.isfinite(raw).all()
         and math.isfinite(sigma) and sigma > 0, "INVALID_SAVED_CALIBRATION_ROWS")
    need(not path.exists(), "EXISTING_CALIBRATION_ARTIFACT_PRESERVE")
    rows = [{**{column: key[column] for column in ("signal_date", "ticker", "label_mature_date")},
             "y_open5": float(actual), "prediction": float(predicted),
             "value_sigma": float(sigma), "residual": float(actual - predicted),
             "prediction_role": "CALIBRATION_NOT_OOF"}
            for key, actual, predicted in zip(keys, y, raw)]
    pq.write_table(pa.Table.from_pylist(rows), path)
    return {"path": str(path.resolve()), "sha256": sha(path), "rows": len(rows),
            "prediction_role": "CALIBRATION_NOT_OOF"}


def verify_calibration_predictions(receipt, path, expected_rows):
    reference = receipt.get("calibration_predictions_ref")
    path = Path(path).resolve()
    need(isinstance(reference, dict)
         and reference.get("path") == str(path)
         and reference.get("rows") == expected_rows
         and reference.get("prediction_role") == "CALIBRATION_NOT_OOF",
         "CALIBRATION_RECEIPT_REQUIRED_NOT_OOF")
    need(path.is_file() and sha(path) == reference.get("sha256"),
         "CALIBRATION_PREDICTIONS_BYTES_CHANGED")


def _owners():
    from scripts.research.a2.training import stateful_values, stateful_fusion, consensus_predictors
    return stateful_values, stateful_fusion, consensus_predictors


def _fit_native(method, x, y, state, frozen, log, receipt, tuple_sha, owners):
    """Use the original packet3 ACK channel, never the wide-packet options branch."""
    import numpy as np
    values, owner, _ = owners
    if method == "equal":
        return owner._fit_arrays(method, x, y, state, np.ones(len(y)), lambda _: None,
                                 frozen["dependency_paths"], packet_width=3)
    return values._fit_job("fusion", method, x, y, state, np.ones(len(y)),
                           frozen["dependency_paths"], list(EXPERTS), None,
                           log=log, auth={"max_fit_units": frozen["max_fit_units"],
                                          "max_new_bucket_fit_units": frozen["max_new_fit_units"],
                                          "budget_bucket": "original_cash12_packet3"},
                           prior=frozen["prior_fit_units"], year=2025, tuple_sha=tuple_sha,
                           receipt=receipt, worker_target=owner._fusion_worker)


@dataclass
class OriginalCashFusionFit:
    native: object
    sigma: float
    receipt: dict


def fit_one(freeze_path, method):
    """Explicitly run one authorized 2025 slot; imports/data/fits occur only here."""
    need(method in METHODS, "UNPLANNED_ORIGINAL_CASH_METHOD")
    freeze_path = Path(freeze_path).resolve()
    frozen = json.loads(freeze_path.read_text(encoding="utf-8-sig"))
    validate_freeze(frozen)
    from scripts.common.storage_paths import resolve, assert_safe_output_path
    paths = resolve(REPO)
    run = Path(frozen["run_dir"]).resolve()
    assert_safe_output_path(run, kind="backtest", paths=paths)
    for path in frozen["dependency_paths"]:
        need(Path(path).resolve().is_relative_to(paths.envs_root.resolve()), "UNAPPROVED_DEPENDENCY_PATH")
    state_receipt = pinned_metadata(frozen["state_source_ref"])
    need(state_receipt["state_basis"] == STATE_BASIS, "STATE_BUILDER_SCOPE_CHANGED")
    _publication_pins(frozen)
    reuse = {"research_id": frozen["research_id"], "parent_research_id": frozen["parent_research_id"],
             "year": 2025, "method": method, "freeze_ref": ref(freeze_path),
             "packet": list(PACKET), "source_pins": frozen["source_pins"],
             "inputs": frozen["inputs"], "expert_oof_pins": frozen["expert_oof_pins"],
             "membership_sha256": frozen["membership_sha256"], "input_binding_sha256": frozen["input_binding_sha256"],
             "state_source_ref": frozen["state_source_ref"], "seed": frozen["seed"],
             "feature_binding": frozen["feature_binding"], "label_definition": frozen["label_definition"],
             "train_maturity_exclusive": frozen["train_maturity_exclusive"],
             "calibration_maturity_exclusive": frozen["calibration_maturity_exclusive"],
             "calibration_sessions": frozen["calibration_sessions"]}
    token = digest(reuse)
    slot = run / "models/original_cash12_fusion" / method / "2025"
    rp, mp, log = slot / "receipt.json", slot / "model.joblib", run / "FIT_LOG.jsonl"
    import joblib
    if rp.exists():
        receipt = json.loads(rp.read_text(encoding="utf-8"))
        need(receipt["status"] == "TRAINED" and receipt["reuse_tuple"] == reuse
             and receipt["reuse_tuple_sha256"] == token and sha(mp) == receipt["model_sha256"],
             "EXISTING_SLOT_PRESERVE_NO_SILENT_RETRY")
        verify_calibration_predictions(receipt, slot / "calibration_predictions.parquet",
                                       frozen["inputs"]["calibration"]["rows"])
        _owners()[1]._native(frozen["dependency_paths"])
        model = joblib.load(mp)
        model.receipt = receipt
        return model
    need(not slot.exists(), "UNRECEIPTED_SLOT_PRESERVE")
    arrays = _inputs(frozen)
    owners = _owners()
    values, owner, predictors = owners
    need(values.feature_binding() == frozen["feature_binding"], "ORIGINAL_FEATURE_BINDING_CHANGED")
    need(set(frozen["allowed_feature_sources"]) <= set(owner.ALLOWED_SOURCES), "UNQUALIFIED_SOURCE_ALLOWLIST")
    receipt = {"status": "IN_PROGRESS", "research_id": frozen["research_id"], "model_id": method,
               "year": 2025, "packet": list(PACKET), "fit_units": 0,
               "reuse_tuple": reuse, "reuse_tuple_sha256": token,
               "receipt_path": str(rp), "model_path": str(mp),
               "source_policy": "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY", "strict_PIT_certified": False,
               "train_rows": frozen["inputs"]["train"]["rows"],
               "calibration_rows": frozen["inputs"]["calibration"]["rows"],
               "uncertainty_authority": "ONLY_CHRONOLOGICAL_PAST60_HELDOUT_SIGMA",
               "calibration_is_oof": False, "native_insample_statistics_used": False}
    with predictors.fit_lock(run):
        need(not slot.exists(), "SLOT_CREATED_BY_OTHER_WORKER")
        slot.mkdir(parents=True)
        values.write_json_atomic(rp, receipt)
        values._append(log, {"event": "ORIGINAL_CASH12_SLOT_STARTED", "model_id": method,
                             "year": 2025, "reuse_tuple_sha256": token})
        try:
            x, y, state = arrays["train"]
            cx, cy, cstate = arrays["calibration"]
            # Register native pickle classes before receiving the canonical worker result.
            owner._native(frozen["dependency_paths"])
            native = _fit_native(method, x, y, state, frozen, log, receipt, token, owners)
            raw = native.predict(cx, cstate)
            auth = {"max_fit_units": frozen["max_fit_units"], "max_new_bucket_fit_units": frozen["max_new_fit_units"],
                    "budget_bucket": "original_cash12_packet3"}
            values._component_start(log, auth, frozen["prior_fit_units"], method, 2025,
                                    "HELDOUT_RESIDUAL_SIGMA", token)
            receipt["fit_units"] += 1
            values.write_json_atomic(rp, receipt)
            sigma = values.heldout_calibration("ridge", raw, cy)["sigma"]
            need(sha(freeze_path) == reuse["freeze_ref"]["sha256"]
                 and frozen["source_pins"] == source_pins(), "FROZEN_IDENTITY_CHANGED_DURING_FIT")
            calibration_ref = save_calibration_predictions(
                slot / "calibration_predictions.parquet", arrays["calibration_keys"], cy, raw, sigma)
            receipt.update(status="TRAINED", sigma=sigma, calibration_predictions_ref=calibration_ref)
            model = OriginalCashFusionFit(native, sigma, receipt)
            joblib.dump(model, mp)
            receipt["model_sha256"] = sha(mp)
            values.write_json_atomic(rp, receipt)
            values._append(log, {"event": "ORIGINAL_CASH12_SLOT_COMPLETE", "model_id": method,
                                 "year": 2025, "fit_units": receipt["fit_units"], "reuse_tuple_sha256": token})
            return model
        except BaseException as exc:
            receipt.update(status="FAILED", failure={"type": type(exc).__name__, "message": str(exc)})
            values.write_json_atomic(rp, receipt)
            values._append(log, {"event": "ORIGINAL_CASH12_SLOT_FAILED", "model_id": method,
                                 "year": 2025, "fit_units": receipt["fit_units"], "reuse_tuple_sha256": token})
            raise


def main(argv=None):
    if __name__ == "__main__":
        import importlib
        return importlib.import_module(
            "scripts.research.a2.training.consensus_original_cash12").main(argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--method", choices=METHODS, required=True)
    args = parser.parse_args(argv)
    result = fit_one(args.freeze, args.method)
    print(json.dumps(result.receipt, ensure_ascii=False, allow_nan=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

