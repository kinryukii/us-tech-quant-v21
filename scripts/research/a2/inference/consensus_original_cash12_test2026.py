"""Explicit frozen 2025 cash-head inference on the accepted 2026 value support.

No data, model loading or numerical owner import at module import. Old annual
guards remain unchanged; this separately authorized consumer never fits.
"""
from __future__ import annotations
import argparse
import ast
import gc
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SCHEMA = "CONSENSUS_ORIGINAL_CASH12_TEST2026_FREEZE_R1"
START, END = "2026-01-02", "2026-10-08"
POINTS = ("extra", "hgb", "hgb_q", "huber", "ngboost", "ridge", "xgb", "xgb_rank")
PACKET = ("ridge", "hgb", "lgb")
FUSIONS = ("equal", "convex", "stack_ridge", "gate_linear")
HEADS = (*POINTS, "lgb", *("fusion::" + m for m in FUSIONS))
KEYS = ("signal_date", "ticker")
FLAGS = ("security_id", "feature_available", "input_present", "feature_source")
DOMAIN = "CURRENT_POOL_UNION_PREVIOUSLY_EFFECTIVE_MEMBERS_ASOF"


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path)}


def source_pins():
    training = HERE.parent / "training"
    native = HERE.parent / "retained/a2_predict_then_optimize_20260928_r1"
    files = {"consumer": Path(__file__), "predictor_owner": training / "consensus_predictors.py",
             "value_owner": training / "stateful_values.py", "fusion_owner": training / "stateful_fusion.py",
             "training_adapter": training / "consensus_original_cash12.py",
             "pool_commitment_owner": HERE / "frozen_a94_values.py",
             "identity_owner": training / "stateful_risk.py",
             "native_value": native / "models_native.py", "native_fusion": native / "fusion_models.py",
             "native_common": native / "common.py"}
    return {key: ref(path) for key, path in files.items()}


def metadata(reference):
    path = Path(reference["path"])
    need(path.is_absolute() and path.resolve(strict=True) == path.absolute()
         and path.stat().st_size <= 8 * 1024 * 1024, "BOUNDED_PINNED_METADATA_REQUIRED")
    need(sha(path) == reference["sha256"], "METADATA_BYTES_CHANGED")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _same_ref(a, b):
    return Path(a["path"]) == Path(b["path"]) and a["sha256"] == b["sha256"]


def validate_freeze(frozen):
    need(frozen["schema"] == SCHEMA and frozen["status"] == "AUTHORIZED_FROZEN_INFERENCE_ONLY",
         "EXPLICIT_TEST2026_FREEZE_REQUIRED")
    need(frozen["research_id"] and frozen["start"] == START and frozen["end"] == END, "EXACT_EXPOSED_2026_SCOPE")
    need(frozen["source_pins"] == source_pins(), "INFERENCE_SOURCE_CHANGED")
    features = frozen["feature_binding"]["features"]
    need(len(features) == len(set(features)) == 32
         and frozen["input_read_columns"] == [*KEYS, *FLAGS, *features], "ORIGINAL_FEATURE_ONLY_PROJECTION")
    need(_same_ref(frozen["input_ref"], frozen["original_input_ref"]), "EXACT_ACCEPTED_INPUT_REQUIRED_NO_NEW_FEATURES")
    need(frozen.get("new_fit", 0) == 0 and frozen.get("strict_PIT_certified", False) is False,
         "INFERENCE_ONLY_NO_PROMOTION")


def _owned_function(path, name, namespace):
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), "exec"), scope)
    return scope[name]


def pool_commitment(frame, features):
    """Execute the pinned original commitment functions, without risk imports."""
    import numpy as np
    import pandas as pd
    training = HERE.parent / "training"
    identity = _owned_function(training / "stateful_risk.py", "identity_frame",
                               {"hashlib": hashlib, "pd": pd, "np": np})
    commit = _owned_function(HERE / "frozen_a94_values.py", "pool_session_commitment",
                            {"_KEYS": KEYS, "_FLAGS": FLAGS,
                             "risk_owner": SimpleNamespace(identity_frame=identity)})
    return commit(frame, tuple(features))


def validate_frame(frame, frozen, support, commitment=pool_commitment):
    import pandas as pd
    features = frozen["feature_binding"]["features"]
    need(list(frame.columns) == frozen["input_read_columns"], "NO_LABELS_BUY_FLAGS_OR_UNDECLARED_COLUMNS")
    need(not frame.duplicated(list(KEYS)).any(), "DUPLICATE_INFERENCE_KEYS")
    dates = pd.to_datetime(frame.signal_date, errors="raise")
    need(dates.notna().all() and dates.min() >= pd.Timestamp(START)
         and dates.max() <= pd.Timestamp(END), "INFERENCE_OUTSIDE_AUTHORIZED_DATES")
    proof = support["value_holding_support"]
    need(proof["domain_policy"] == DOMAIN and proof["role"] == "OFFPOOL_HOLDING_VALUE_CONTINUITY_ONLY"
         and proof["no_future_first_membership"] is True and proof["no_new_buy_eligibility"] is True
         and support["source_has_no_new_buy_flags"] is True, "CAUSAL_HOLDING_SUPPORT_REQUIRED")
    actual_days = {str(d.date()) for d in dates}
    need(actual_days == set(proof["sessions"]), "FULL_ORIGINAL_SUPPORT_CALENDAR_REQUIRED")
    first = proof["first_membership_by_ticker"]
    for day, rows in frame.groupby("signal_date", sort=False):
        key = str(pd.Timestamp(day).date())
        need(all(t in first and first[t] <= key for t in rows.ticker), "FUTURE_FIRST_MEMBERSHIP_FORBIDDEN")
        need(commitment(rows, features) == proof["sessions"][key], "ORIGINAL_SUPPORT_KEYS_OR_VALUES_CHANGED")
    for name in ("feature_available", "input_present"):
        need(frame[name].notna().all() and frame[name].isin([True, False]).all(), "BOOLEAN_SUPPORT_FLAGS_REQUIRED")


def _load_frame(frozen, support):
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    path = Path(frozen["input_ref"]["path"])
    pf = pq.ParquetFile(path)
    need(set(frozen["input_read_columns"]) <= set(pf.schema_arrow.names), "INPUT_SCHEMA_CHANGED")
    index = pf.schema_arrow.names.index("signal_date")
    for i in range(pf.num_row_groups):
        stat = pf.metadata.row_group(i).column(index).statistics
        need(stat is not None and stat.has_min_max and stat.null_count == 0
             and START <= str(stat.min)[:10] <= str(stat.max)[:10] <= END,
             "PHYSICAL_INPUT_DATE_BOUNDARY")
    need(sha(path) == frozen["input_ref"]["sha256"], "INPUT_BYTES_CHANGED")
    typ = pf.schema_arrow.field("signal_date").type
    first, last = pd.Timestamp(START), pd.Timestamp(END)
    lower, upper = (first.date(), last.date()) if pa.types.is_date(typ) else (first.to_pydatetime(), last.to_pydatetime())
    frame = pq.read_table(path, columns=frozen["input_read_columns"],
                          filters=[("signal_date", ">=", lower), ("signal_date", "<=", upper)]).to_pandas()
    need(len(frame) == pf.metadata.num_rows, "INPUT_PREDICATE_CARDINALITY_CHANGED")
    validate_frame(frame, frozen, support)
    return frame


def _owners():
    from scripts.research.a2.training import consensus_predictors, stateful_fusion
    return consensus_predictors, consensus_predictors.values, stateful_fusion


def point_prediction(model, receipt, frame, features, owners):
    import numpy as np
    from threadpoolctl import threadpool_limits
    predictors, values, _ = owners
    model_id = receipt["native_model_id"]
    need(model_id not in values.EXTENSIONS and tuple(features) == tuple(values.feature_binding()["features"]),
         "ONLY_BOUND_NATIVE_FEATURE32_HEADS")
    valid = values._bool(frame.feature_available, "feature_available") & values._bool(frame.input_present, "input_present")
    need(frame.loc[valid, "feature_source"].isin(values.SOURCES).all(), "UNQUALIFIED_INFERENCE_SOURCE")
    need(np.isfinite(frame.loc[valid, list(features)].to_numpy(float)).all(), "NONFINITE_QUALIFIED_PREDICTION_FEATURES")
    out = frame[list(KEYS)].copy()
    for column in ("prediction", "value_sigma", *values.diagnostic_columns(model_id)):
        out[column] = np.nan
    if valid.any():
        with threadpool_limits(limits=1):
            raw = predictors.raw_predict(model.native, model_id, frame.loc[valid].reset_index(drop=True), None)
        mu, sigma = model.mapped(raw)
        need(np.isfinite(mu).all() and np.isfinite(sigma).all() and (sigma > 0).all(), "NONFINITE_POINT_FORECAST")
        for column, vector in {"prediction": mu, "value_sigma": sigma, **values.raw_fields(model_id, raw)}.items():
            out.loc[valid, column] = vector
    out["prediction_qualified"] = valid.to_numpy()
    return out


def fusion_prediction(model, method, frame, experts, owners):
    import numpy as np
    from threadpoolctl import threadpool_limits
    _, values, owner = owners
    need(method in FUSIONS and tuple(owner.packet_for(method)) == PACKET and set(experts) == set(PACKET),
         "EXACT_ORIGINAL_PACKET3_REQUIRED")
    packets = {name: experts[name].rename(columns={"prediction": "expert_" + name}) for name in PACKET}
    joined, x = owner.join_packet(frame, packets, PACKET)
    valid = values._bool(frame.feature_available, "feature_available").to_numpy() & np.isfinite(x).all(axis=1)
    need(frame.loc[valid, "feature_source"].isin(owner.ALLOWED_SOURCES).all(), "UNQUALIFIED_FUSION_INPUT")
    out = frame[list(KEYS)].copy()
    out["prediction"], out["value_sigma"] = np.nan, np.nan
    if valid.any():
        # State uses all feature-qualified, expert-valid rows, before the final projection.
        state = owner.join_state(joined.loc[valid].reset_index(drop=True), owner.state_surface(joined, x)) \
            if owner.state_required(method) else np.zeros((int(valid.sum()), 4))
        with threadpool_limits(limits=1):
            mu = model.native.predict(x[valid], state)
        need(np.isfinite(mu).all() and np.isfinite(model.sigma) and model.sigma > 0, "NONFINITE_FUSION_FORECAST")
        out.loc[valid, "prediction"], out.loc[valid, "value_sigma"] = mu, model.sigma
    out["prediction_qualified"] = valid
    return out


def _bindings(frozen):
    binding = metadata(frozen["head_binding_ref"])
    acceptance = metadata(frozen["training_acceptance_ref"])
    need(acceptance["status"] == "COMPLETE"
         and _same_ref(acceptance["binding_ref"], frozen["head_binding_ref"]), "FINAL_TRAINING_ACCEPTANCE_REQUIRED")
    need(set(binding["heads"]) == set(POINTS) | {"fusion::" + m for m in FUSIONS}
         and len(binding["configurations"]) == 63, "EXACT_ACCEPTED_12_HEADS_AND_63_CONFIGURATIONS")
    reused = metadata(frozen["reused_heads_ref"])
    lgb = [r for r in reused["rows"] if r["head"] == "lgb"]
    need(len(lgb) == 1 and lgb[0]["new_fit_calls"] == 0, "NEW_POOL_LGB_SUPPORT_REQUIRED")
    heads = dict(binding["heads"], lgb=lgb[0])
    original = metadata(frozen["original_value_outputs_ref"])
    support = metadata(frozen["support_manifest_ref"])
    need(original["start"] == START and original["end"] == END and original["domain_policy"] == DOMAIN
         and _same_ref(original["pool_ref"], frozen["original_input_ref"])
         and _same_ref(original["support_manifest_ref"], frozen["support_manifest_ref"])
         and _same_ref(support["physical_support_ref"], frozen["original_input_ref"]), "ORIGINAL_INPUT_PROVENANCE_CHANGED")
    return heads, original, support


def _load_model(head, item, receipt, frozen, owners):
    import joblib
    predictors, values, fusion = owners
    need(sha(item["model_ref"]["path"]) == item["model_ref"]["sha256"], "BOUND_MODEL_BYTES_CHANGED")
    (fusion._native if head.startswith("fusion::") else values._native)(frozen["dependency_paths"])
    model = joblib.load(item["model_ref"]["path"])
    expected = ("scripts.research.a2.training.consensus_original_cash12", "OriginalCashFusionFit") \
        if head.startswith("fusion::") else ("scripts.research.a2.training.consensus_predictors", "ConsensusPredictor")
    need((type(model).__module__, type(model).__name__) == expected, "CANONICAL_FROZEN_MODEL_CLASS_REQUIRED")
    need(model.receipt["reuse_tuple_sha256"] == receipt["reuse_tuple_sha256"]
         and model.receipt["year"] == receipt["year"] == 2025, "MODEL_RECEIPT_IDENTITY_CHANGED")
    # The accepted equal portable transport intentionally has a distinct model hash.
    model.receipt = receipt
    if head.startswith("fusion::"):
        need(receipt["packet"] == list(PACKET) and model.sigma == receipt["sigma"], "FROZEN_PACKET_OR_SIGMA_CHANGED")
    else:
        need(model.calibration["sigma"] == receipt["calibration"]["sigma"] and model.bridge is None,
             "FROZEN_POINT_CALIBRATION_CHANGED")
    return model


def _head_identity(freeze_ref, head, item, frozen):
    return {"freeze_ref": freeze_ref, "head": head, "model_ref": item["model_ref"],
            "receipt_ref": item["receipt_ref"], "input_ref": frozen["input_ref"],
            "start": START, "end": END, "prediction_role": "FROZEN_FORWARD_INFERENCE"}


def resume_output(receipt_path, frame_path, identity):
    if not receipt_path.exists():
        need(not frame_path.exists(), "UNRECEIPTED_OUTPUT_PRESERVE")
        return None
    saved = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    need(saved["status"] == "COMPLETE" and saved["identity"] == identity
         and saved["output"]["frame_ref"] == ref(frame_path), "COMPLETED_OUTPUT_IDENTITY_OR_BYTES_CHANGED")
    return saved["output"]


def _write_json(path, value):
    from scripts.common.storage_paths import resolve, assert_safe_output_path
    assert_safe_output_path(path, kind="backtest", paths=resolve(REPO))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value) + "\n")


def run(freeze_path):
    from scripts.common.storage_paths import resolve, assert_safe_output_path
    import numpy as np
    import pandas as pd
    freeze_path = Path(freeze_path).resolve()
    frozen = json.loads(freeze_path.read_text(encoding="utf-8-sig"))
    validate_freeze(frozen)
    run_dir = Path(frozen["run_dir"]).resolve()
    paths = resolve(REPO)
    assert_safe_output_path(run_dir, kind="backtest", paths=paths)
    for dependency in frozen["dependency_paths"]:
        need(Path(dependency).resolve().is_relative_to(paths.envs_root.resolve()), "UNAPPROVED_DEPENDENCY")
    heads, original, support = _bindings(frozen)
    freeze_ref = ref(freeze_path)
    output = run_dir / "derived/evaluation2026/inference"
    assert_safe_output_path(output, kind="backtest", paths=paths)
    output.mkdir(parents=True, exist_ok=True)
    frame, owners = None, None
    outputs, computed, reused = {}, [], []
    for head in HEADS:
        item = heads[head]
        receipt = metadata(item["receipt_ref"])
        need(receipt["status"] == "TRAINED" and receipt["year"] == 2025, "FROZEN_2025_HEAD_REQUIRED")
        need(receipt["model_id"] == head.split("::")[-1]
             and item["reuse_tuple_sha256"] == receipt["reuse_tuple_sha256"], "BOUND_HEAD_RECEIPT_CHANGED")
        need(sha(item["model_ref"]["path"]) == item["model_ref"]["sha256"], "BOUND_MODEL_BYTES_CHANGED")
        stem = head.replace("::", "_")
        frame_path, receipt_path = output / (stem + ".parquet"), output / (stem + "_receipt.json")
        identity = _head_identity(freeze_ref, head, item, frozen)
        saved = resume_output(receipt_path, frame_path, identity)
        if saved is not None:
            outputs[head] = saved
            reused.append(head)
            continue
        if frame is None:
            frame = _load_frame(frozen, support)
            owners = _owners()
            need(owners[1].feature_binding() == frozen["feature_binding"], "ORIGINAL_FEATURE_BINDING_CHANGED")
        print(canonical({"head": head, "status": "INFERENCE_STARTED", "new_fit": 0}), flush=True)
        model = _load_model(head, item, receipt, frozen, owners)
        if head.startswith("fusion::"):
            experts = {}
            for member in PACKET:
                source = outputs[member]
                need(ref(source["frame_ref"]["path"]) == source["frame_ref"], "FROZEN_EXPERT_CACHE_CHANGED")
                experts[member] = pd.read_parquet(source["frame_ref"]["path"], columns=[*KEYS, "prediction"])
            result = fusion_prediction(model, head.split("::", 1)[1], frame, experts, owners)
            sigma = float(model.sigma)
            del experts
        else:
            result = point_prediction(model, receipt, frame, frozen["feature_binding"]["features"], owners)
            sigma = float(model.calibration["sigma"])
        need(result[list(KEYS)].equals(frame[list(KEYS)]), "INFERENCE_KEYS_DROPPED_OR_REORDERED")
        lineage = "FROZEN_2025|" + item["model_ref"]["sha256"] + "|" + receipt["reuse_tuple_sha256"]
        result["year"], result["evaluation_year"] = 2025, 2026
        result["model_id"] = receipt["model_id"]
        result["model_sha256"] = item["model_ref"]["sha256"]
        result["model_reuse_tuple_sha256"] = receipt["reuse_tuple_sha256"]
        result["model_lineage"] = lineage
        result["prediction_role"] = "FROZEN_FORWARD_INFERENCE"
        need(not frame_path.exists() and sha(freeze_path) == freeze_ref["sha256"]
             and source_pins() == frozen["source_pins"], "OUTPUT_FREEZE_OR_SOURCE_CHANGED")
        result.to_parquet(frame_path, index=False, compression="zstd", compression_level=3)
        entry = {"frame_ref": ref(frame_path), "read_columns": list(result), "sigma": sigma,
                 "lineage": lineage, "model_ref": item["model_ref"], "receipt_ref": item["receipt_ref"],
                 "role": "SUPPORT_ONLY" if head == "lgb" else "REQUESTED_HEAD", "rows": len(result),
                 "qualified_rows": int(result.prediction_qualified.sum())}
        _write_json(receipt_path, {"schema": "CASH12_TEST2026_HEAD_OUTPUT_R1", "status": "COMPLETE",
                                  "identity": identity, "output": entry, "new_fit": 0, "account": 0})
        outputs[head] = entry
        computed.append(head)
        print(canonical({"head": head, "status": "COMPLETE", "rows": len(result), "new_fit": 0}), flush=True)
        del model, result
        gc.collect()
    document = {"schema": "CASH12_TEST2026_VALUE_OUTPUTS_R1", "task_id": frozen["research_id"],
                "status": "COMPLETE", "start": START, "end": END, "outputs": outputs,
                "pool_ref": frozen["input_ref"], "support_manifest_ref": frozen["support_manifest_ref"],
                "source_ref": original["source_ref"], "original_authority_ref": original["authority_ref"],
                "original_value_outputs_ref": frozen["original_value_outputs_ref"],
                "head_binding_ref": frozen["head_binding_ref"], "training_acceptance_ref": frozen["training_acceptance_ref"],
                "freeze_ref": freeze_ref, "source_pins": frozen["source_pins"], "domain_policy": DOMAIN,
                "requested_heads": 12, "support_heads": ["lgb"], "new_fit": 0, "account": 0,
                "strict_PIT_certified": False, "primary_metrics": None}
    need(sha(freeze_path) == freeze_ref["sha256"] and source_pins() == frozen["source_pins"],
         "FINAL_FREEZE_OR_SOURCE_CHANGED")
    target = output / "VALUE_OUTPUTS.json"
    if target.exists():
        need(json.loads(target.read_text(encoding="utf-8-sig")) == document, "FINAL_MANIFEST_PRESERVE_CHANGED")
    else:
        _write_json(target, document)
    return {"status": "COMPLETE", "value_outputs_ref": ref(target),
            "computed_heads": computed, "reused_heads": reused, "new_fit": 0, "account": 0}


def main(argv=None):
    if __name__ == "__main__":
        import importlib
        return importlib.import_module("scripts.research.a2.inference.consensus_original_cash12_test2026").main(argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    args = parser.parse_args(argv)
    print(canonical(run(args.freeze)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
