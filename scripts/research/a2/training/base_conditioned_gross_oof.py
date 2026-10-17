"""Finite restoration of the two 2024 ElasticNet heads; no account engine.

Metadata release is required before numeric reads. Original input/target/scaler
commitments remain authoritative. Historical consensus application is a separate
consumer: this module never relabels the original RAW opportunity OOF as TOP100.
"""
from __future__ import annotations
import argparse
from datetime import date
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

TASK = "A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1"
FIT_CUTOFF = "2024-01-01"
CONTROL_CUTOFF = "2024-10-07"
GROUPS = ("ENTRY", "INCUMBENT")
PARAMETERS = dict(alpha=.0001, l1_ratio=.35, max_iter=25000,
                  selection="cyclic", tol=1e-5)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def reference(path):
    path = Path(path).resolve()
    before = path.stat()
    with path.open("rb") as handle:
        value = hashlib.file_digest(handle, "sha256").hexdigest()
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) ==
            (after.st_size, after.st_mtime_ns), "SOURCE_CHANGED_DURING_HASH")
    return dict(path=str(path), sha256=value)


def physical(ref):
    require(reference(ref["path"]) == ref, "PHYSICAL_REFERENCE_CHANGED")
    return Path(ref["path"])


def document(ref, limit=500000):
    path = physical(ref)
    require(path.stat().st_size <= limit, "METADATA_SIZE_LIMIT")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def put(path, value, roots):
    from scripts.common.storage_paths import assert_safe_output_path
    assert_safe_output_path(path, kind="backtest", paths=roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False, default=str) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _load(ref, name):
    path = physical(ref)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def helpers(release):
    refs = release["helper_refs"]
    require(set(refs) == {"bounded", "preparation", "solver", "scaler_memmap"},
            "EXACT_REUSED_HELPERS")
    for ref in refs.values():
        physical(ref)
    paths = {str(Path(ref["path"]).parent.resolve()) for ref in refs.values()}
    prior = list(sys.path)
    names = ("bounded_original_inputs", "scaler_memmap_input")
    old = {name: sys.modules.get(name) for name in names}
    try:
        sys.path[:0] = sorted(paths)
        bounded = _load(refs["bounded"], names[0])
        memmap = _load(refs["scaler_memmap"], names[1])
        sys.modules[names[0]], sys.modules[names[1]] = bounded, memmap
        preparation = _load(refs["preparation"], "_gross_oof_preparation")
        solver = _load(refs["solver"], "_gross_oof_solver")
        yield bounded, preparation, solver
    finally:
        sys.path[:] = prior
        for name, value in old.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def validate(contract_ref, release_ref, run):
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.training import stateful_mechanism_models as models
    contract, release = document(contract_ref), document(release_ref)
    require(contract["research_id"] == TASK and release["task_id"] == TASK
            and release["schema"] == "BASE_CONDITIONED_GROSS_OOF_RELEASE_R1",
            "TASK_IDENTITY")
    require(release["contract_ref"] == contract_ref
            and release["driver_ref"] == reference(__file__), "CONTRACT_DRIVER_PIN")
    require(contract["historical_base_2024_fit_cutoff_exclusive"] == FIT_CUTOFF
            and contract["controller_signal_and_label_maturity_cutoff_exclusive"]
            == CONTROL_CUTOFF, "EARLIER_CUTOFFS")
    require(contract["fit_budget"]["historical_EN_components"] == 2
            and contract["fit_budget"]["base_scaler_refits"] == 0, "FINITE_FIT_BUDGET")
    roots = resolve(Path(__file__).resolve().parents[4])
    run = Path(run).resolve()
    require(run == Path(release["run_root"]).resolve()
            and run.parent == (roots.backtest_root / TASK).resolve()
            and run.is_dir(), "RESOLVED_EXISTING_RUN_REQUIRED")
    current_pins = models.source_pins()
    require(current_pins == release["current_execution_source_pins"],
            "CURRENT_MODEL_SOURCE_PINS")
    design = document(release["original_design_ref"])
    old_pins = design["model_specifications"]["source_pins"]
    changed = sorted(key for key in set(old_pins) | set(current_pins)
                     if old_pins.get(key) != current_pins.get(key))
    require(changed == release["approved_old_source_pin_differences"]
            and set(changed) <= {"fusion_owner_sha256"}, "ONLY_UNUSED_FUSION_DRIFT")
    for ref in release["original_source_refs"]:
        physical(ref)
    for ref in release["helper_refs"].values():
        physical(ref)
    records = {}
    require(set(release["nodes"]) == set(GROUPS)
            and set(release["ridge_receipt_refs"]) == set(GROUPS)
            and set(release["ridge_scaler_receipt_refs"]) == set(GROUPS), "EXACT_FOUR_HEADS")
    for group in GROUPS:
        pair = release["nodes"][group]
        old, scaler = document(pair["failure_ref"]), document(pair["scaler_receipt_ref"])
        slot = f"ACTION_VALUE_{group}_HMEAN_2024_elasticnet_MID_20260928"
        require(old["slot_id"] == slot and old["status"] == "FAILED"
                and old["cutoff_exclusive"] == FIT_CUTOFF
                and "OPTIMIZER_DID_NOT_CONVERGE" in old.get("error", ""),
                "ORIGINAL_2024_OPTIMIZER_FAILURE")
        identity = old["scientific_tuple"]
        require(identity["group"] == group and identity["year"] == 2024
                and identity["seed"] == 20260928 and identity["family"] == "elasticnet"
                and identity["capacity"] == "MID" and identity["horizon"] == "MEAN",
                "ORIGINAL_ELASTIC_TUPLE")
        require(scaler["status"] == "TRAINED" and scaler["slot_id"] ==
                f"ACTION_VALUE_{group}_HMEAN_2024_SCALER", "ORIGINAL_2024_SCALER")
        scaler_ref = dict(path=scaler["model_path"], sha256=scaler["model_sha256"])
        physical(scaler_ref)
        ridge = document(release["ridge_receipt_refs"][group])
        require(ridge["status"] == "TRAINED" and ridge["slot_id"] ==
                f"ACTION_VALUE_{group}_H5_2024_ridge_MID_20260928"
                and ridge["cutoff_exclusive"] == FIT_CUTOFF
                and ridge["publication"]["prediction_role"] == "GENUINE_PAST_ONLY_R10_OOF",
                "ORIGINAL_RIDGE_OOF")
        ridge_ref = dict(path=ridge["model_path"], sha256=ridge["model_sha256"])
        physical(ridge_ref)
        ridge_scaler = document(release["ridge_scaler_receipt_refs"][group])
        require(ridge_scaler["status"] == "TRAINED" and ridge_scaler["slot_id"] ==
                f"ACTION_VALUE_{group}_H5_2024_SCALER", "ORIGINAL_RIDGE_SCALER")
        ridge_scaler_ref = dict(path=ridge_scaler["model_path"],
                                sha256=ridge_scaler["model_sha256"])
        physical(ridge_scaler_ref)
        records[group] = dict(original=old, scaler=scaler, scaler_ref=scaler_ref,
                              ridge_ref=ridge_ref, ridge_receipt=release["ridge_receipt_refs"][group],
                              ridge_scaler_ref=ridge_scaler_ref,
                              original_receipt=pair["failure_ref"])
    return contract, release, roots, run / "derived/base_oof", records


def event_projection(stream, cutoff=CONTROL_CUTOFF):
    """Exact indent=2 binding layout: date prefix before any payload decode.

    This is intentionally not a general JSON reader. It accepts the original
    owner's flat event records and event_records-last layout, or fails closed.
    Rejected event payload lines are discarded without JSON decoding/buffering.
    """
    boundary = date.fromisoformat(cutoff)
    require(cutoff == CONTROL_CUTOFF, "FIXED_EVENT_READ_BOUNDARY")
    header, size = [], 0
    while True:
        line = stream.readline()
        require(bool(line), "EVENT_ARRAY_MISSING")
        if line.rstrip("\r\n") == '  "event_records": [':
            break
        size += len(line)
        require(size <= 16384, "EVENT_HEADER_BOUND")
        header.append(line)
    metadata = json.loads("".join(header) + '  "event_records": []\n}')
    require("event_records" in metadata, "EVENT_HEADER_SCHEMA")
    selected, skipped = [], 0
    line = stream.readline()
    while line.rstrip("\r\n") != "  ]":
        require(line.rstrip("\r\n") == "    {", "EXACT_FLAT_EVENT_OBJECT")
        ticker_line, date_line = stream.readline(), stream.readline()
        require(ticker_line.startswith('      "ticker": ')
                and ticker_line.rstrip().endswith(",")
                and date_line.startswith('      "event_date": ')
                and date_line.rstrip().endswith(","), "DATE_MUST_PRECEDE_EVENT_PAYLOAD")
        prefix = json.loads("{" + ticker_line + date_line.rstrip().rstrip(",") + "}")
        require(isinstance(prefix["ticker"], str)
                and isinstance(prefix["event_date"], str), "EVENT_PREFIX_TYPES")
        event_day = date.fromisoformat(prefix["event_date"])
        require(event_day.isoformat() == prefix["event_date"], "CANONICAL_EVENT_DATE")
        keep = event_day < boundary
        parts = [line, ticker_line, date_line] if keep else None
        while True:
            line = stream.readline()
            require(bool(line), "UNTERMINATED_EVENT")
            closing = line.rstrip("\r\n")
            if closing in ("    }", "    },"):
                if keep:
                    parts.append("    }\n")
                break
            # No payload value is decoded on this path for excluded events.
            require(line.startswith('      "') and len(line) <= 16384,
                    "ORIGINAL_FLAT_EVENT_LAYOUT")
            if keep:
                parts.append(line)
        if keep:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    require(key not in result, "DUPLICATE_EVENT_KEY")
                    result[key] = value
                return result
            event = json.loads("".join(parts), object_pairs_hook=unique)
            require(event["event_date"] == prefix["event_date"]
                    and event["ticker"] == prefix["ticker"], "EVENT_PREFIX_CHANGED")
            selected.append(event)
        else:
            skipped += 1
        line = stream.readline()
        require(closing.endswith(",") or line.rstrip("\r\n") == "  ]",
                "EVENT_SEPARATOR_LAYOUT")
    require(stream.readline().rstrip("\r\n") == "}" and not stream.read(1),
            "EVENT_RECORDS_MUST_BE_LAST")
    metadata["event_records"] = selected
    return metadata, dict(selected_events=len(selected), skipped_events=skipped,
                          excluded_payloads_decoded=0)


def project_events(original_ref, roots, out):
    path = physical(original_ref)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        metadata, audit = event_projection(stream)
    physical(original_ref)
    projection = dict(metadata, schema="BOUNDED_R10_EVENT_BINDING_R1",
        original_binding_ref=original_ref, cutoff_exclusive=CONTROL_CUTOFF,
        original_metadata_preserved=True, projection_audit=audit)
    put(out / "BOUNDED_EVENT_BINDING.json", projection, roots)
    return projection


@contextmanager
def bounded_events(projection, inputs):
    """Supply only the qualified projection to the unchanged event-window owner."""
    require(projection["schema"] == "BOUNDED_R10_EVENT_BINDING_R1"
            and projection["cutoff_exclusive"] == CONTROL_CUTOFF,
            "BOUNDED_EVENT_PROJECTION")
    original = inputs.load_event_owner
    def load(meta):
        require(projection["original_binding_ref"] == meta["event_binding"],
                "EVENT_PROJECTION_PARENT")
        owner = _load(meta["event_window_owner"], "_gross_oof_event_window")
        return projection["event_records"], owner.apply_event_windows
    inputs.load_event_owner = load
    try:
        yield
    finally:
        inputs.load_event_owner = original


def resource_admission(solver):
    admission = solver.memory()
    require(admission["physical_gib"] >= 1.5 and admission["page_gib"] >= 8,
            "ORIGINAL_RESOURCE_ADMISSION")
    return admission


def prepare(release, roots, out, records, release_ref):
    require(release["permits"].get("prepare") is True, "METADATA_RELEASE_BEFORE_READ")
    import joblib
    import numpy as np
    import pandas as pd
    from scripts.research.a2.training import stateful_mechanism as original
    from scripts.research.a2.training import stateful_mechanism_inputs as inputs
    path = out / "PREPARATION.json"
    if path.exists():
        receipt = document(reference(path))
        require(receipt["release_ref"] == release_ref and receipt["status"] == "PREPARED",
                "PREPARATION_FAILURE_PRESERVED")
        for item in receipt["groups"].values():
            for array in item["arrays"].values():
                physical({k: array[k] for k in ("path", "sha256")})
        return receipt
    with helpers(release) as (_, _, solver):
        admission = resource_admission(solver)
    design = document(release["original_design_ref"])
    auth = release["original_read_authorization_ref"]
    permit = inputs.ReadPermit.from_files(release["original_design_ref"]["path"],
        release["original_design_ref"]["sha256"], auth["path"], auth["sha256"])
    manifest = inputs.r10_source_manifest()
    sources = manifest["parquet_sources"]
    receipt = dict(status="PREPARING", release_ref=release_ref, groups={},
                   source_read_cutoff=CONTROL_CUTOFF, fit_cutoff=FIT_CUTOFF,
                   new_fits=0, scaler_fits=0, resource_admission=admission)
    put(path, receipt, roots)
    try:
        projection = project_events(manifest["metadata_pins"]["event_binding"], roots, out)
        with helpers(release) as (bounded, recovery, _), bounded_events(projection, inputs):
            with bounded.narrowed_reads(sources, CONTROL_CUTOFF) as calls:
                bundle = inputs.build_real_frames(permit, design)
                frames = recovery.frame_for_recovery(bundle)
                receipt["source_reads"] = list(calls)
                for group, record in records.items():
                    frame = original.mature_train(frames[group], pd.Timestamp(FIT_CUTOFF))
                    cols = original.SINGLE if group == "ENTRY" else (*original.PAIR, "action_type")
                    x, names = original.encode(frame, cols)
                    dates = frame.signal_date.to_numpy()
                    weight, target = original.role_weights(frame), frame.target.to_numpy(float)
                    require(len(frame) > 0 and frame.label_mature_date.lt(FIT_CUTOFF).all(),
                            "MATURE_2024_FIT_ROWS")
                    recovery.check_commitments(x, dates, weight, np.zeros(len(x)), names,
                                               record["scaler"]["scientific_tuple"])
                    scaler = joblib.load(physical(record["scaler_ref"]))
                    transformed = np.nan_to_num(scaler.transform(x), nan=0.)
                    recovery.check_commitments(transformed, dates, weight, target, names,
                                               record["original"]["scientific_tuple"])
                    folder = out / "inputs" / group
                    folder.mkdir(parents=True, exist_ok=False)
                    arrays = {key: recovery.save_array(folder / (key + ".npy"), value)
                              for key, value in dict(x=transformed, dates=dates,
                                                     weights=weight, target=target).items()}
                    receipt["groups"][group] = dict(arrays=arrays, features=list(names),
                        scaler_ref=record["scaler_ref"], original_receipt=record["original_receipt"],
                        signal_max=str(frame.signal_date.max()),
                        maturity_max=str(frame.label_mature_date.max()))
                    put(path, receipt, roots)
        receipt["status"] = "PREPARED"
    except BaseException as exc:
        receipt.update(status="FAILED", error=type(exc).__name__ + ":" + str(exc))
        raise
    finally:
        put(path, receipt, roots)
    return receipt


def fit(release, roots, out, records, release_ref):
    require(release["permits"].get("fit") is True, "FIT_RELEASE_REQUIRED")
    import joblib
    import numpy as np
    from scripts.research.a2.training import stateful_mechanism_models as models
    prepared = document(reference(out / "PREPARATION.json"))
    require(prepared["status"] == "PREPARED" and prepared["release_ref"] == release_ref,
            "PREPARED_EXACT_RELEASE")
    design = document(release["original_design_ref"])
    result = dict(schema="BASE_HISTORICAL_2024_MODEL_BUNDLE_R1", task_id=TASK,
                  release_ref=release_ref, original_pool_only=True,
                  consensus_application_validated=False, nodes={})
    with helpers(release) as (_, recovery, solver):
        old = models.parameters("ElasticNet", "MID")
        require({**old, "max_iter":25000} == PARAMETERS, "FIXED_ELASTIC_PARAMETERS")
        fitted = solver.adapt(models, "ElasticNet", "MID", old, PARAMETERS)
        for group, record in records.items():
            folder = out / "models" / group
            receipt_path = folder / "fit_receipt.json"
            row = None
            if receipt_path.exists():
                row = document(reference(receipt_path))
                require(row["release_ref"] == release_ref
                        and row["parent_receipt"] == record["original_receipt"]
                        and row["original_identity"] == record["original"]["scientific_tuple"]
                        and row["configuration"] == PARAMETERS and row["group"] == group,
                        "RESUME_FIT_IDENTITY_CHANGED")
                if row["status"] == "TRAINED":
                    physical(row["model_ref"])
                else:
                    require(type(row.get("fit_units")) is int and row["fit_units"] == 0,
                            "ORIGINAL_FAILURE_PRESERVED_NO_RETRY")
            if row is None or row["status"] != "TRAINED":
                # Admission precedes any slot/receipt mutation. Resource denial
                # is neither an estimator attempt nor a failed scientific trial.
                admission = resource_admission(solver)
                require(not (folder / "model.joblib").exists(), "UNRECEIPTED_MODEL_PRESERVED")
                folder.mkdir(parents=True, exist_ok=True)
                if row is None:
                    row = dict(status="VALIDATING", group=group, release_ref=release_ref,
                        parent_receipt=record["original_receipt"], fit_units=0, scaler_fit=0,
                        configuration=PARAMETERS,
                        original_identity=record["original"]["scientific_tuple"])
                else:
                    history = list(row.get("pre_fit_recovery_history", []))
                    history.append(dict(status=row["status"], error=row.get("error"), fit_units=0))
                    row = dict(row, status="VALIDATING", pre_fit_recovery_history=history)
                    row.pop("error", None)
                row["resource_admission"] = admission
                put(receipt_path, row, roots)
                try:
                    data = prepared["groups"][group]
                    arrays = {key: np.load(physical({k: ref[k] for k in ("path","sha256")}),
                                           mmap_mode="r", allow_pickle=False)
                              for key, ref in data["arrays"].items()}
                    recovery.check_commitments(arrays["x"], arrays["dates"], arrays["weights"],
                        arrays["target"], data["features"], record["original"]["scientific_tuple"])
                    require((arrays["dates"] < np.datetime64(FIT_CUTOFF)).all(), "FIT_DATE_BOUND")
                    node = dict(record["original"]["scientific_tuple"],
                                source_pins=release["current_execution_source_pins"])
                    payload = dict(node, target=arrays["target"], weights=arrays["weights"])
                    def start(component):
                        require(row["fit_units"] == 0, "SINGLE_FIT_ONLY")
                        row.update(status="FITTING", fit_units=1, component=component)
                        put(receipt_path, row, roots)
                    model, meta = fitted(node, arrays["x"], payload,
                        dependencies=tuple(design["dependency_paths"]), on_fit_started=start)
                    require(meta["actual_fit_count"] == 1 and meta["parameters"] == PARAMETERS,
                            "EXACT_FINITE_FIT")
                    require(np.isfinite(model.estimator.coef_).all()
                            and np.isfinite(model.estimator.intercept_).all(), "FINITE_MODEL")
                    model.metadata.update(new_scientific_id=TASK + ":" + group + ":2024",
                        parent_receipt=record["original_receipt"], same_identity_recovery=False)
                    model_path = folder / "model.joblib"
                    joblib.dump(model, model_path)
                    row.update(status="TRAINED", model_ref=reference(model_path), metadata=meta)
                except BaseException as exc:
                    row.update(status="FAILED", error=type(exc).__name__ + ":" + str(exc))
                    raise
                finally:
                    put(receipt_path, row, roots)
            result["nodes"][group] = dict(elasticnet_model_ref=row["model_ref"],
                elasticnet_receipt_ref=reference(receipt_path), elasticnet_scaler_ref=record["scaler_ref"],
                ridge_scaler_ref=record["ridge_scaler_ref"],
                ridge_model_ref=record["ridge_ref"], ridge_receipt_ref=record["ridge_receipt"])
    result["status"] = "MODELS_READY_PENDING_CONSENSUS_APPLICATION"
    put(out / "MODEL_BUNDLE.json", result, roots)
    return result


COMPONENT_SLOTS = tuple(
    f"ACTION_VALUE_{group}_{horizon}_2024_{suffix}"
    for group in GROUPS
    for horizon, suffix in (("HMEAN", "SCALER"), ("H5", "SCALER"),
                            ("H5", "ridge_MID_20260928")))
COMPONENT_CAP = dict(scalers=4, ridge=2, elasticnet=0)


CORRECTION_SLOTS = tuple(f"ACTION_VALUE_INCUMBENT_{h}_2024_SCALER" for h in ("HMEAN", "H5"))
CORRECTION_CAP = dict(scalers=2, ridge=0, elasticnet=0)


def component_parent(release, release_ref):
    if "base_component_restore_release_ref" not in release:
        return release, release_ref
    parent_ref = release["base_component_restore_release_ref"]
    parent = document(parent_ref)
    require(parent["schema"] == release["schema"]
            == "BASE_HISTORICAL_2024_COMPONENT_RESTORE_RELEASE_R1"
            and parent["status"] == release["status"] == "ROOT_AUTHORIZED_COMPONENT_RESTORATION"
            and parent["task_id"] == release["task_id"] == TASK
            and "base_component_restore_release_ref" not in parent,
            "EXACT_INITIAL_COMPONENT_RELEASE")
    for key in ("contract_ref", "original_model_bundle_ref", "original_oof_release_ref",
                "recovery_delta_ref", "receipt_refs", "run_root"):
        require(parent[key] == release[key], "NUMERIC_CORRECTION_PARENT:" + key)
    return parent, parent_ref


def numeric_correction_delta(release, release_ref):
    _, parent_ref = component_parent(release, release_ref)
    require(parent_ref != release_ref, "NUMERIC_CORRECTION_PARENT_REQUIRED")
    delta = document(release["correction_delta_ref"])
    require(delta["schema"] == "BASE_HISTORICAL_2024_INC_SCALER_NUMERIC_EXECUTION_CORRECTION_R1"
            and delta["status"] == "ROOT_AUTHORIZED_NUMERIC_EXECUTION_CORRECTION"
            and delta["task_id"] == TASK
            and delta["base_component_restore_release_ref"] == parent_ref
            and delta["correction_slots"] == list(CORRECTION_SLOTS)
            and delta["physical_fit_cap"] == CORRECTION_CAP
            and delta["actual_total_scaler_fits_cap"] == 6
            and delta["original_signal_and_label_maturity_cutoff_exclusive"] == FIT_CUTOFF
            and delta["native_execution"] == "original values._fit_job spawn with host default thread environment"
            and delta["no_thread_search"] is True
            and delta["exact_original_model_sha_required"] is True
            and delta["original_transformed_x_sha_required"] is True,
            "EXACT_NUMERIC_EXECUTION_CORRECTION")
    physical(delta["baseline_attempt_ref"])
    return delta, parent_ref


def component_numeric_correction(release, old_release, roots, out, records, release_ref):
    require(release["permits"].get("numeric_correction") is True, "NUMERIC_CORRECTION_RELEASE_REQUIRED")
    delta, parent_ref = numeric_correction_delta(release, release_ref)
    # Host default once, never a search over thread settings. The original
    # spawn worker receives an ndarray and no observed-mask override.
    require(all(os.environ.get(key) is None for key in
                ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")),
            "NUMERIC_CORRECTION_HOST_DEFAULT_ENVIRONMENT")
    import joblib
    import numpy as np
    from scripts.research.a2.training import stateful_values as values
    from scripts.research.a2.training import stateful_mechanism_models as models
    prepared_ref = reference(out / "PREPARATION.json")
    prepared = document(prepared_ref)
    require(prepared["status"] == "PREPARED" and prepared["release_ref"] == parent_ref,
            "NUMERIC_CORRECTION_EXACT_PARENT_PREPARATION")
    initial = {}
    for slot, record in records.items():
        if record["kind"] != "scalers":
            continue
        rp = out / "objects" / slot / "fit_receipt.json"
        row = document(reference(rp))
        require(row["status"] == "TRAINED" and row["fit_units"] == 1
                and row["release_ref"] == parent_ref
                and row["parent_receipt_ref"] == record["receipt_ref"]
                and row["original_identity"] == record["identity"], "EXACT_INITIAL_SCALER_ATTEMPTS")
        physical(row["model_ref"])
        if record["group"] == "ENTRY":
            require(row["model_ref"]["sha256"] == record["original_model_ref"]["sha256"], "EXACT_ENTRY_SCALER_REUSE")
        initial[slot] = reference(rp)
    require(len(initial) == 4, "FOUR_INITIAL_SCALER_FITS_PRESERVED")
    correction_out = out / "native_execution_correction"
    result = dict(schema="BASE_HISTORICAL_2024_CORRECTED_SCALERS_R1", status="CORRECTING",
        task_id=TASK, release_ref=release_ref, base_component_restore_release_ref=parent_ref,
        correction_delta_ref=release["correction_delta_ref"], preparation_ref=prepared_ref,
        initial_scaler_receipt_refs=initial, nodes={}, initial_scaler_fits=4,
        correction_scaler_fits=0, actual_total_scaler_fits=4)
    result_path = correction_out / "CORRECTED_SCALERS.json"
    with helpers(old_release) as (_, recovery, solver):
        for slot in CORRECTION_SLOTS:
            data = prepared["inputs"][slot]
            model_identity = (records[slot]["en_identity"] if records[slot]["horizon"] == "HMEAN"
                else records["ACTION_VALUE_INCUMBENT_H5_2024_ridge_MID_20260928"]["identity"])
            require(data["scaler_identity"] == records[slot]["identity"]
                    and data["model_identity"] == model_identity, "COMPONENT_PREPARED_IDENTITY")
            check_component_raw({**data, **_component_arrays(data)}, records[slot]["identity"], model_identity, recovery)
        try:
            for slot in CORRECTION_SLOTS:
                record, data = records[slot], prepared["inputs"][slot]
                arrays = _component_arrays(data)
                folder = correction_out / "objects" / slot
                rp, mp = folder / "fit_receipt.json", folder / "model.joblib"
                if rp.exists():
                    row = document(reference(rp))
                    require(row["release_ref"] == release_ref
                            and row["parent_receipt_ref"] == record["receipt_ref"]
                            and row["original_identity"] == record["identity"], "CORRECTION_RESUME_IDENTITY")
                    if row["status"] == "TRAINED" and row["fit_units"] == 1:
                        require(row["model_ref"]["sha256"] == record["original_model_ref"]["sha256"],
                                "EXACT_ORIGINAL_SCALER_SHA")
                        model = joblib.load(physical(row["model_ref"]))
                    else:
                        require(row["fit_units"] == 0 and row["status"] in ("FAILED", "VALIDATING")
                                and not mp.exists(), "FAILED_NUMERIC_CORRECTION_PRESERVED")
                        model = None
                else:
                    require(not mp.exists(), "UNRECEIPTED_COMPONENT_PRESERVED")
                    row, model = None, None
                if model is None:
                    prior = row
                    row = dict(schema="BASE_HISTORICAL_2024_COMPONENT_FIT_R1", task_id=TASK,
                        status="VALIDATING", slot_id=slot, kind="scalers", fit_units=0,
                        release_ref=release_ref, parent_receipt_ref=record["receipt_ref"],
                        original_identity=record["identity"], original_model_ref=record["original_model_ref"],
                        base_component_restore_release_ref=parent_ref, correction_delta_ref=release["correction_delta_ref"],
                        receipt_path=str(rp), automatic_scientific_retry=False,
                        resource_admission=resource_admission(solver),
                        native_execution=delta["native_execution"], historical_effective_threads="UNKNOWN")
                    if prior is not None:
                        row["pre_fit_recovery_history"] = list(prior.get("pre_fit_recovery_history", [])) + [
                            dict(status=prior["status"], error=prior.get("error"), fit_units=0)]
                    put(rp, row, roots)
                    try:
                        payload = {"weights":np.array(arrays["weights"], dtype=float, order="K", copy=True)}
                        model = values._fit_job("mechanism_scaler", slot,
                            np.array(arrays["x"], dtype=float, order="K", copy=True), payload,
                            np.array(arrays["dates"], copy=True), None, design_dependencies(old_release),
                            data["features"], None, log=correction_out / "FIT_LOG.jsonl",
                            auth=dict(max_fit_units=2, max_new_bucket_fit_units=2, budget_bucket="NUMERIC_EXECUTION_CORRECTION"),
                            prior=0, year=2024, tuple_sha=record["receipt"]["scientific_tuple_sha256"],
                            receipt=row, worker_target=models.fit_worker)
                        require(row["fit_units"] == 1, "ONE_CORRECTION_PHYSICAL_FIT")
                        joblib.dump(model, mp)
                        row["model_ref"] = reference(mp)
                        row["original_object_bytes_restored"] = row["model_ref"]["sha256"] == record["original_model_ref"]["sha256"]
                        require(row["original_object_bytes_restored"], "EXACT_ORIGINAL_SCALER_SHA")
                        row["status"] = "TRAINED"
                    except BaseException as exc:
                        row.update(status="FAILED", error=type(exc).__name__ + ":" + str(exc))
                        raise
                    finally:
                        put(rp, row, roots)
                tx = np.nan_to_num(model.transform(arrays["x"]), nan=0.)
                try:
                    recovery.check_commitments(tx, arrays["dates"], arrays["weights"], arrays["target"],
                        data["features"], data["model_identity"])
                except BaseException as exc:
                    row.update(status="FAILED", error=type(exc).__name__ + ":" + str(exc))
                    put(rp, row, roots)
                    raise
                row["transformed_model_x_sha256"] = data["model_identity"]["x_sha256"]
                put(rp, row, roots)
                result["nodes"][slot] = dict(model_ref=row["model_ref"], receipt_ref=reference(rp))
            result.update(status="CORRECTED_SCALERS_VERIFIED", correction_scaler_fits=2, actual_total_scaler_fits=6)
        except BaseException as exc:
            result.update(status="FAILED", error=type(exc).__name__ + ":" + str(exc))
            raise
        finally:
            # Fit counters are read from actual receipts, including a failed slot.
            result["correction_scaler_fits"] = sum(document(reference(p))["fit_units"]
                for p in (correction_out / "objects").glob("*/fit_receipt.json"))
            result["actual_total_scaler_fits"] = 4 + result["correction_scaler_fits"]
            put(result_path, result, roots)
    return result


def design_dependencies(old_release):
    return tuple(document(old_release["original_design_ref"])["dependency_paths"])


def validated_correction_rows(release, release_ref, out, records):
    _, parent_ref = numeric_correction_delta(release, release_ref)
    expected = out / "native_execution_correction" / "CORRECTED_SCALERS.json"
    supplied = release.get("numeric_correction_ref")
    require(supplied is None or Path(supplied["path"]).resolve() == expected.resolve(), "CORRECTION_RESULT_NAMESPACE")
    result_ref = reference(expected) if supplied is None else supplied
    result = document(result_ref)
    producer_ref = release.get("verified_numeric_correction_release_ref", release_ref)
    if producer_ref != release_ref:
        producer = document(producer_ref)
        _, producer_parent = component_parent(producer, producer_ref)
        require(producer_parent == parent_ref, "CORRECTION_PRODUCER_PARENT")
        for key in ("contract_ref", "original_model_bundle_ref", "original_oof_release_ref",
                    "recovery_delta_ref", "receipt_refs", "run_root", "correction_delta_ref"):
            require(producer[key] == release[key], "CORRECTION_PRODUCER:" + key)
        require(supplied is not None, "SEALED_EXISTING_CORRECTION_REFERENCE_REQUIRED")
    initial_refs = {slot:reference(out / "objects" / slot / "fit_receipt.json")
                    for slot, record in records.items() if record["kind"] == "scalers"}
    require(result["schema"] == "BASE_HISTORICAL_2024_CORRECTED_SCALERS_R1"
            and result["task_id"] == TASK and result["status"] == "CORRECTED_SCALERS_VERIFIED"
            and result["preparation_ref"] == reference(out / "PREPARATION.json")
            and result["initial_scaler_receipt_refs"] == initial_refs
            and result["release_ref"] == producer_ref
            and result["base_component_restore_release_ref"] == parent_ref
            and result["correction_delta_ref"] == release["correction_delta_ref"]
            and set(result["nodes"]) == set(CORRECTION_SLOTS)
            and result["initial_scaler_fits"] == 4 and result["correction_scaler_fits"] == 2
            and result["actual_total_scaler_fits"] == 6, "VERIFIED_NUMERIC_CORRECTION_REQUIRED")
    rows = {}
    for slot, refs in result["nodes"].items():
        row = document(refs["receipt_ref"])
        identity = (records[slot]["en_identity"] if records[slot]["horizon"] == "HMEAN"
                    else records["ACTION_VALUE_INCUMBENT_H5_2024_ridge_MID_20260928"]["identity"])
        require(row["status"] == "TRAINED" and row["fit_units"] == 1
                and row["release_ref"] == producer_ref and row["original_identity"] == records[slot]["identity"]
                and row["parent_receipt_ref"] == records[slot]["receipt_ref"]
                and row["base_component_restore_release_ref"] == parent_ref
                and row["correction_delta_ref"] == release["correction_delta_ref"]
                and row["model_ref"] == refs["model_ref"]
                and refs["model_ref"]["sha256"] == records[slot]["original_model_ref"]["sha256"]
                and row["transformed_model_x_sha256"] == identity["x_sha256"], "CORRECTED_SCALER_EXACT_CUSTODY")
        physical(refs["model_ref"])
        rows[slot] = dict(row, _actual_receipt_ref=refs["receipt_ref"])
    return rows, result_ref


def validate_component_restore(contract_ref, release_ref, run):
    """A separate root delta preserves the original zero-refit contract."""
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.training import stateful_mechanism as original
    from scripts.research.a2.training import stateful_mechanism_models as models
    contract, release = document(contract_ref), document(release_ref)
    require(contract["research_id"] == release["task_id"] == TASK
            and release["schema"] == "BASE_HISTORICAL_2024_COMPONENT_RESTORE_RELEASE_R1"
            and release["status"] == "ROOT_AUTHORIZED_COMPONENT_RESTORATION"
            and release["contract_ref"] == contract_ref
            and release["driver_ref"] == reference(__file__), "COMPONENT_ROOT_RELEASE")
    require(contract["historical_base_2024_fit_cutoff_exclusive"] == FIT_CUTOFF
            and contract["controller_signal_and_label_maturity_cutoff_exclusive"] == CONTROL_CUTOFF
            and contract["fit_budget"]["base_scaler_refits"] == 0
            and contract["fit_budget"]["historical_EN_components"] == 2,
            "ORIGINAL_CONTRACT_PRESERVED")
    component_parent(release, release_ref)
    if "base_component_restore_release_ref" in release:
        numeric_correction_delta(release, release_ref)
    delta = document(release["recovery_delta_ref"])
    require(delta["schema"] == "BASE_HISTORICAL_2024_COMPONENT_RESTORE_DELTA_R1"
            and delta["task_id"] == TASK
            and delta["status"] == "ROOT_AUTHORIZED_COMPONENT_RESTORATION"
            and delta["contract_ref"] == contract_ref
            and delta["original_model_bundle_ref"] == release["original_model_bundle_ref"]
            and delta["physical_fit_cap"] == COMPONENT_CAP
            and len(delta["deleted_slots"]) == len(COMPONENT_SLOTS)
            and set(delta["deleted_slots"]) == set(COMPONENT_SLOTS), "EXACT_COMPONENT_DELTA")
    physical(delta["deletion_plan_ref"])
    deletion = document(delta["deletion_receipt_ref"])
    require(deletion["status"] == "COMPLETED"
            and deletion["plan_sha256"] == delta["deletion_plan_ref"]["sha256"],
            "DELETION_PROVENANCE")
    roots = resolve(Path(__file__).resolve().parents[4])
    run = Path(run).resolve()
    require(run == Path(release["run_root"]).resolve()
            and run.parent == (roots.backtest_root / TASK).resolve()
            and run.is_dir(), "RESOLVED_EXISTING_RUN_REQUIRED")
    old_release = document(release["original_oof_release_ref"])
    require(old_release["task_id"] == TASK and old_release["contract_ref"] == contract_ref
            and old_release["schema"] == "BASE_CONDITIONED_GROSS_OOF_RELEASE_R1"
            and old_release["current_execution_source_pins"] == models.source_pins(),
            "ORIGINAL_OOF_SOURCE_CUSTODY")
    for ref in old_release["original_source_refs"]:
        physical(ref)
    for ref in old_release["helper_refs"].values():
        physical(ref)
    design = document(old_release["original_design_ref"])
    changed = sorted(key for key in set(design["model_specifications"]["source_pins"])
                     | set(models.source_pins()) if
                     design["model_specifications"]["source_pins"].get(key)
                     != models.source_pins().get(key))
    require(changed == old_release["approved_old_source_pin_differences"]
            and set(changed) <= {"fusion_owner_sha256"}, "ONLY_UNUSED_FUSION_DRIFT")
    bundle = document(release["original_model_bundle_ref"])
    require(bundle["task_id"] == TASK and bundle["original_pool_only"] is True
            and set(bundle["nodes"]) == set(GROUPS)
            and set(release["receipt_refs"]) == set(COMPONENT_SLOTS), "EXACT_SIX_COMPONENTS")
    records = {}
    for group in GROUPS:
        node = bundle["nodes"][group]
        # Existing EN objects are opaque dependencies and are never fitted here.
        physical(node["elasticnet_model_ref"])
        en = document(node["elasticnet_receipt_ref"])
        require(en["status"] == "TRAINED" and en["group"] == group
                and en["model_ref"] == node["elasticnet_model_ref"], "EXISTING_EN_CUSTODY")
        for horizon, suffix, role, expected_receipt in (
            ("HMEAN", "SCALER", "elasticnet_scaler_ref", old_release["nodes"][group]["scaler_receipt_ref"]),
            ("H5", "SCALER", "ridge_scaler_ref", old_release["ridge_scaler_receipt_refs"][group]),
            ("H5", "ridge_MID_20260928", "ridge_model_ref", old_release["ridge_receipt_refs"][group])):
            slot = f"ACTION_VALUE_{group}_{horizon}_2024_{suffix}"
            receipt_ref = release["receipt_refs"][slot]
            require(receipt_ref["sha256"] == expected_receipt["sha256"], "ARCHIVED_RECEIPT_SAME_BYTES")
            receipt = document(receipt_ref)
            identity = receipt["scientific_tuple"]
            require(receipt["slot_id"] == slot and receipt["status"] == "TRAINED"
                    and receipt["model_sha256"] == node[role]["sha256"]
                    and Path(receipt["model_path"]).resolve() == Path(node[role]["path"]).resolve()
                    and identity["year"] == 2024 and identity["bucket"] == "ACTION_VALUE"
                    and identity["design_sha256"] == old_release["original_design_ref"]["sha256"]
                    and original.digest(identity) == receipt["scientific_tuple_sha256"],
                    "ORIGINAL_COMPONENT_IDENTITY")
            require(not Path(node[role]["path"]).exists(), "PREFER_EXISTING_ORIGINAL_OBJECT")
            if suffix != "SCALER":
                require(receipt["family"] == "ridge" and receipt["capacity"] == "MID"
                        and receipt["seed"] == 20260928
                        and receipt["cutoff_exclusive"] == FIT_CUTOFF
                        and receipt["group"] == group and receipt["horizon"] == 5,
                        "ORIGINAL_RIDGE_CONFIGURATION")
            records[slot] = dict(group=group, horizon=horizon,
                kind="scalers" if suffix == "SCALER" else "ridge", role=role,
                receipt_ref=receipt_ref, receipt=receipt, identity=identity,
                original_model_ref=node[role], en_identity=en["original_identity"])
    return release, old_release, roots, run / "derived/base_component_restore", records


def component_training_input(bundle, group, horizon, original, recovery, *, frames=None):
    """Dispatch to original cohorts; H5 never inherits HMEAN qualification."""
    import numpy as np
    import pandas as pd
    if frames is None:
        frames = (recovery.frame_for_recovery(bundle) if horizon == "HMEAN"
                  else original.structured_action_frame(bundle.frames, 5))
    train = original.mature_train(frames[group], pd.Timestamp(FIT_CUTOFF))
    require(len(train) > 0 and train.signal_date.lt(FIT_CUTOFF).all()
            and train.label_mature_date.lt(FIT_CUTOFF).all(), "COMPONENT_MATURE_PRE2024")
    columns = original.SINGLE if group == "ENTRY" else (*original.PAIR, "action_type")
    x, names = original.encode(train, columns)
    return dict(x=x, dates=train.signal_date.to_numpy(), weights=original.role_weights(train),
                target=train.target.to_numpy(float), features=names,
                signal_max=str(train.signal_date.max()), maturity_max=str(train.label_mature_date.max()))


def check_component_raw(data, scaler_identity, model_identity, recovery):
    """Raw scaler inputs and model labels are known before a scaler fit."""
    import numpy as np
    recovery.check_commitments(data["x"], data["dates"], data["weights"],
        np.zeros(len(data["x"])), data["features"], scaler_identity)
    require((data["dates"] < np.datetime64(FIT_CUTOFF)).all()
            and data["signal_max"] < FIT_CUTOFF and data["maturity_max"] < FIT_CUTOFF,
            "COMPONENT_MATURE_PRE2024")
    for key in ("dates_sha256", "weights_sha256", "x_shape", "features"):
        require(model_identity[key] == scaler_identity[key], "COMPONENT_MODEL_COHORT:" + key)
    require(recovery.array_hash(np.asarray(data["target"], float)) == model_identity["target_sha256"]
            and list(np.asarray(data["target"]).shape) == model_identity["target_shape"],
            "COMPONENT_MODEL_TARGET")


def component_prepare(release, old_release, roots, out, records, release_ref):
    require(release["permits"].get("prepare") is True, "COMPONENT_PREPARE_RELEASE_REQUIRED")
    require("base_component_restore_release_ref" not in release, "NUMERIC_CORRECTION_REUSES_PARENT_PREPARATION")
    from scripts.research.a2.training import stateful_mechanism as original
    from scripts.research.a2.training import stateful_mechanism_inputs as inputs
    path = out / "PREPARATION.json"
    previous_attempts = []
    attempt = 1
    if path.exists():
        saved = document(reference(path))
        require(saved["release_ref"] == release_ref, "COMPONENT_PREPARATION_IDENTITY")
        if saved["status"] == "PREPARED":
            for data in saved["inputs"].values():
                for ref in data["arrays"].values():
                    physical({k: ref[k] for k in ("path", "sha256")})
            return saved
        require(saved["status"] in ("FAILED", "PREPARING")
                and saved.get("physical_fits") == 0
                and saved["fit_cutoff"] == FIT_CUTOFF
                and saved["source_read_cutoff"] == CONTROL_CUTOFF,
                "COMPONENT_PREPARATION_FAILURE_PRESERVED")
        # No physical fit has started. Preserve the prior attempt and partial
        # arrays; this engineering continuation writes a new input namespace.
        attempt = saved.get("attempt", 1) + 1
        previous_attempts = list(saved.get("previous_preparation_attempts", []))
        snapshot = out / f"PREPARATION_ATTEMPT_{attempt-1:03d}.json"
        if snapshot.exists():
            require(document(reference(snapshot)) == saved, "PREPARATION_SNAPSHOT_PRESERVED")
        else:
            put(snapshot, saved, roots)
        previous_attempts.append(reference(snapshot))
    with helpers(old_release) as (_, _, solver):
        admission = resource_admission(solver)
    design = document(old_release["original_design_ref"])
    auth = old_release["original_read_authorization_ref"]
    permit = inputs.ReadPermit.from_files(old_release["original_design_ref"]["path"],
        old_release["original_design_ref"]["sha256"], auth["path"], auth["sha256"])
    manifest = inputs.r10_source_manifest()
    row = dict(schema="BASE_HISTORICAL_2024_COMPONENT_INPUTS_R1", status="PREPARING",
               task_id=TASK, release_ref=release_ref, inputs={}, physical_fits=0,
               fit_cutoff=FIT_CUTOFF, source_read_cutoff=CONTROL_CUTOFF,
               resource_admission=admission, attempt=attempt, previous_preparation_attempts=previous_attempts,
               scaled_model_x_commitments="PENDING_SCALER_RESTORATION")
    put(path, row, roots)
    try:
        projection = project_events(manifest["metadata_pins"]["event_binding"], roots, out)
        with helpers(old_release) as (bounded, recovery, _), bounded_events(projection, inputs):
            with bounded.narrowed_reads(manifest["parquet_sources"], CONTROL_CUTOFF) as calls:
                bundle = inputs.build_real_frames(permit, design)
                for horizon in ("HMEAN", "H5"):
                    frames = (recovery.frame_for_recovery(bundle) if horizon == "HMEAN"
                              else original.structured_action_frame(bundle.frames, 5))
                    for group in GROUPS:
                        slot = f"ACTION_VALUE_{group}_{horizon}_2024_SCALER"
                        record = records[slot]
                        data = component_training_input(bundle, group, horizon, original, recovery, frames=frames)
                        model_identity = (record["en_identity"] if horizon == "HMEAN"
                            else records[f"ACTION_VALUE_{group}_H5_2024_ridge_MID_20260928"]["identity"])
                        check_component_raw(data, record["identity"], model_identity, recovery)
                        folder = out / "inputs" / f"attempt_{attempt:03d}" / slot
                        folder.mkdir(parents=True, exist_ok=False)
                        arrays = {key: recovery.save_array(folder / (key + ".npy"), data[key])
                                  for key in ("x", "dates", "weights", "target")}
                        row["inputs"][slot] = dict(arrays=arrays, features=list(data["features"]),
                            signal_max=data["signal_max"], maturity_max=data["maturity_max"],
                            scaler_identity=record["identity"], model_identity=model_identity)
                    del frames
                row["source_reads"] = list(calls)
        require(len(row["inputs"]) == COMPONENT_CAP["scalers"], "ALL_RAW_INPUTS_REQUIRED")
        row["status"] = "PREPARED"
    except BaseException as exc:
        row.update(status="FAILED", error=type(exc).__name__ + ":" + str(exc))
        raise
    finally:
        put(path, row, roots)
    return row


def _component_arrays(data, keys=None):
    import numpy as np
    arrays = {}
    try:
        for key, ref in data["arrays"].items():
            if keys is None or key in keys:
                arrays[key] = np.load(physical({k: ref[k] for k in ("path", "sha256")}),
                                      mmap_mode="r", allow_pickle=False)
        return arrays
    except BaseException:
        close_component_arrays(arrays)
        raise



def close_component_arrays(arrays):
    """Release only this invocation's read-only mmap handles."""
    for value in arrays.values():
        mapping = getattr(value, "_mmap", None)
        if mapping is not None and not mapping.closed:
            mapping.close()
    arrays.clear()


def additional_workspace_budget(working_bytes, *, resident_bytes=0, physical_reserve_bytes=128 * 1024**2,
                                commit_reserve_bytes=256 * 1024**2):
    """Bytes still to allocate plus reserves; callers retain their phase model."""
    require(all(type(v) is int and v >= 0 for v in
                (working_bytes, resident_bytes, physical_reserve_bytes, commit_reserve_bytes)), "WORKSPACE_BUDGET_BYTES")
    incremental = max(0, working_bytes - resident_bytes)
    return dict(estimated_total_working_bytes=working_bytes, already_resident_bytes=resident_bytes,
        estimated_incremental_working_bytes=incremental, physical_reserve_bytes=physical_reserve_bytes,
        required_available_physical_bytes=incremental + physical_reserve_bytes,
        required_available_page_bytes=incremental + physical_reserve_bytes + commit_reserve_bytes)


def component_memory_admission(solver, shape, phase, *, resident_bytes=0):
    """Dense Ridge/transform workspace, not a full research-run minimum."""
    require(phase in ("transform", "fit") and len(shape) == 2
            and all(type(v) is int and v > 0 for v in shape), "COMPONENT_MEMORY_SHAPE")
    rows, columns = shape
    matrix = rows * columns * 8
    # The unchanged hash owner holds a C-order block plus its bytes, not an
    # entire second matrix. Ridge may hold original/copy/rescaled float64 X.
    hash_buffers = 2 * min(rows, 8192) * columns * 8
    vectors = rows * 8 * 6
    gram = 2 * columns * columns * 8
    native_import_allowance = 64 * 1024**2 if phase == "fit" else 0
    reserve = 128 * 1024**2
    working = (3 if phase == "fit" else 2) * matrix + hash_buffers + vectors + gram + native_import_allowance
    budget = additional_workspace_budget(working, resident_bytes=resident_bytes,
        physical_reserve_bytes=reserve, commit_reserve_bytes=256 * 1024**2)
    admission = dict(solver.memory(), **budget, phase=phase, shape=list(shape), dtype="float64",
        matrix_bytes=matrix,
        calibration="DEFAULT_NATIVE_RIDGE_SYNTHETIC_35670x242_RSS366.68MiB;increment203.02MiB",
        calibration_baseline="canonical stateful_mechanism_models already imported; native import allowance included")
    require(admission["physical_gib"] * 1024**3 >= budget["required_available_physical_bytes"]
            and admission["page_gib"] * 1024**3 >= budget["required_available_page_bytes"],
            "COMPONENT_STAGE_RESOURCE_ADMISSION")
    return admission


def verified_component_scaled_inputs(release, release_ref, out, records, completed, prepared, recovery, solver, roots):
    """All four commitments pass before fitting; retain only disk H5 inputs."""
    import joblib
    import numpy as np
    namespace = out / "verified_h5_inputs" / release_ref["sha256"][:16]
    path = namespace / "SCALED_INPUTS.json"
    prepared_ref = reference(out / "PREPARATION.json")
    model_refs = {slot:completed[slot]["model_ref"] for slot in prepared["inputs"]}
    if path.exists():
        saved = document(reference(path))
        require(saved["status"] == "VERIFIED_ALL_FOUR_TRANSFORMS"
                and saved["release_ref"] == release_ref and saved["prepared_ref"] == prepared_ref
                and saved["scaler_model_refs"] == model_refs
                and set(saved["groups"]) == set(GROUPS), "VERIFIED_SCALED_INPUT_IDENTITY")
        for group, data in saved["groups"].items():
            source = prepared["inputs"][f"ACTION_VALUE_{group}_H5_2024_SCALER"]
            require(data["features"] == source["features"]
                    and data["model_identity"] == source["model_identity"]
                    and {k:v for k,v in data["arrays"].items() if k != "x"}
                    == {k:v for k,v in source["arrays"].items() if k != "x"}
                    and data["arrays"]["x"]["array_sha256"] == source["model_identity"]["x_sha256"]
                    and data["arrays"]["x"]["shape"] == source["model_identity"]["x_shape"]
                    and data["arrays"]["x"]["dtype"] == "float64", "VERIFIED_SCALED_INPUT_COHORT")
            layouts = []
            for sample in (source, data):
                header = _component_arrays(sample, ("x",))
                try:
                    x = header["x"]
                    layout = {key:bool(getattr(x.flags, key)) for key in ("c_contiguous", "f_contiguous")}
                    require(x.dtype == np.dtype("float64") and list(x.shape) == source["model_identity"]["x_shape"]
                            and all(sample["arrays"]["x"].get(key, value) == value for key,value in layout.items()),
                            "VERIFIED_SCALED_INPUT_LAYOUT")
                    layouts.append(layout)
                finally:
                    close_component_arrays(header)
            require(layouts[0] == layouts[1], "VERIFIED_SCALED_INPUT_LAYOUT")
            for ref in data["arrays"].values():
                physical({k:ref[k] for k in ("path", "sha256")})
        return saved
    # A pre-fit failure preserves its partial files. Continue in a fresh bounded
    # namespace; only a complete four-transform receipt becomes reusable.
    attempt = 1
    while (namespace / f"attempt_{attempt:03d}").exists():
        attempt += 1
        require(attempt <= 1000, "VERIFIED_INPUT_ATTEMPT_LIMIT")
    attempt_out = namespace / f"attempt_{attempt:03d}"
    attempt_out.mkdir(parents=True, exist_ok=False)
    saved = dict(schema="BASE_HISTORICAL_2024_VERIFIED_H5_INPUTS_R1", status="VERIFYING",
        release_ref=release_ref, prepared_ref=prepared_ref, scaler_model_refs=model_refs, groups={}, attempt=attempt)
    try:
        for slot, data in prepared["inputs"].items():
            admission = component_memory_admission(solver, data["scaler_identity"]["x_shape"], "transform")
            arrays = _component_arrays(data)
            scaler = tx = None
            try:
                scaler = joblib.load(physical(completed[slot]["model_ref"]))
                tx = scaler.transform(arrays["x"])
                require(tx.dtype == np.dtype("float64") and not np.shares_memory(tx, arrays["x"]),
                        "OWNED_FLOAT64_TRANSFORM_REQUIRED")
                layout = {key:bool(getattr(arrays["x"].flags, key)) for key in ("c_contiguous", "f_contiguous")}
                require(all(bool(getattr(tx.flags, key)) == value
                            and data["arrays"]["x"].get(key, value) == value for key,value in layout.items()),
                        "ORIGINAL_TRANSFORM_LAYOUT_REQUIRED")
                np.nan_to_num(tx, nan=0., copy=False)
                recovery.check_commitments(tx, arrays["dates"], arrays["weights"], arrays["target"],
                                           data["features"], data["model_identity"])
                if records[slot]["horizon"] == "H5":
                    group = records[slot]["group"]
                    folder = attempt_out / group
                    folder.mkdir(parents=True, exist_ok=False)
                    x_ref = recovery.save_array(folder / "x.npy", tx)
                    saved["groups"][group] = dict(arrays={**{k:v for k,v in data["arrays"].items() if k != "x"}, "x":x_ref},
                        features=data["features"], model_identity=data["model_identity"], transform_admission=admission)
            finally:
                scaler = tx = None
                close_component_arrays(arrays)
        require(set(saved["groups"]) == set(GROUPS), "ALL_H5_TRANSFORMS_VERIFIED")
        saved["status"] = "VERIFIED_ALL_FOUR_TRANSFORMS"
        put(path, saved, roots)
        return saved
    except BaseException as exc:
        saved.update(status="FAILED_BEFORE_RIDGE", error=type(exc).__name__ + ":" + str(exc))
        put(attempt_out / "FAILED.json", saved, roots)
        raise



def component_fit(release, old_release, roots, out, records, release_ref):
    """Four scalers, all transformed-X checks, then at most two Ridge fits."""
    require(release["permits"].get("fit") is True, "COMPONENT_FIT_RELEASE_REQUIRED")
    import joblib
    import numpy as np
    from scripts.research.a2.training import stateful_mechanism_models as models
    prepared = document(reference(out / "PREPARATION.json"))
    _, preparation_release_ref = component_parent(release, release_ref)
    require(prepared["status"] == "PREPARED" and prepared["release_ref"] == preparation_release_ref
            and set(prepared["inputs"]) == {s for s, r in records.items() if r["kind"] == "scalers"},
            "COMPONENT_PREPARED_EXACT_RELEASE")
    design = document(old_release["original_design_ref"])
    completed, zero_fit_attempts = {}, {}
    with helpers(old_release) as (_, recovery, solver):
        # Every raw cohort and target is checked before the first physical fit.
        for slot, data in prepared["inputs"].items():
            record = records[slot]
            model_identity = (record["en_identity"] if record["horizon"] == "HMEAN"
                else records[f'ACTION_VALUE_{record["group"]}_H5_2024_ridge_MID_20260928']["identity"])
            require(data["scaler_identity"] == record["identity"]
                    and data["model_identity"] == model_identity, "COMPONENT_PREPARED_IDENTITY")
            arrays = _component_arrays(data)
            try:
                check_component_raw({**data, **arrays}, record["identity"], model_identity, recovery)
            finally:
                close_component_arrays(arrays)
        for slot, record in records.items():
            rp = out / "objects" / slot / "fit_receipt.json"
            if rp.exists():
                row = document(reference(rp))
                expected_release_ref = preparation_release_ref if record["kind"] == "scalers" else release_ref
                require(row["release_ref"] == expected_release_ref
                        and row["parent_receipt_ref"] == record["receipt_ref"]
                        and row["original_identity"] == record["identity"],
                        "COMPONENT_RESUME_IDENTITY")
                if row["status"] == "TRAINED" and row["fit_units"] == 1:
                    physical(row["model_ref"])
                    completed[slot] = row
                else:
                    require(row["status"] in ("VALIDATING", "FAILED")
                            and type(row["fit_units"]) is int and row["fit_units"] == 0
                            and not (rp.parent / "model.joblib").exists(),
                            "FAILED_OR_INTERRUPTED_COMPONENT_PRESERVED")
                    zero_fit_attempts[slot] = row
        correction_result_ref = None
        if "base_component_restore_release_ref" in release:
            require({s for s in completed if records[s]["kind"] == "scalers"}
                    == {s for s, r in records.items() if r["kind"] == "scalers"}, "REUSE_FOUR_INITIAL_SCALERS_ONLY")
            correction_rows, correction_result_ref = validated_correction_rows(release, release_ref, out, records)
            completed.update(correction_rows)
        def fit_one(slot, data):
            if slot in completed:
                return completed[slot]
            record = records[slot]
            folder = out / "objects" / slot
            require(not (folder / "model.joblib").exists(), "UNRECEIPTED_COMPONENT_PRESERVED")
            row = dict(schema="BASE_HISTORICAL_2024_COMPONENT_FIT_R1", status="VALIDATING",
                task_id=TASK, slot_id=slot, release_ref=release_ref, fit_units=0,
                kind=record["kind"], parent_receipt_ref=record["receipt_ref"],
                original_identity=record["identity"], original_model_ref=record["original_model_ref"],
                automatic_scientific_retry=False,
                resource_admission=component_memory_admission(solver, list(data["x"].shape), "fit", resident_bytes=0 if getattr(data["x"], "_mmap", None) is not None else int(data["x"].nbytes)))
            if slot in zero_fit_attempts:
                prior = zero_fit_attempts[slot]
                history = list(prior.get("pre_fit_recovery_history", []))
                history.append(dict(status=prior["status"], error=prior.get("error"), fit_units=0))
                row["pre_fit_recovery_history"] = history
            rp = folder / "fit_receipt.json"
            put(rp, row, roots)
            def started(component):
                used = sum(r["fit_units"] for r in completed.values() if r["kind"] == record["kind"])
                require(row["fit_units"] == 0 and used < COMPONENT_CAP[record["kind"]], "COMPONENT_PHYSICAL_CAP")
                row.update(status="FITTING", fit_units=1, component=component)
                put(rp, row, roots)
            try:
                if record["kind"] == "scalers":
                    model, meta = models.fit_weighted_scaler(data["x"], {"weights":data["weights"]}, on_fit_started=started)
                else:
                    spec = {key:record["receipt"][key] for key in
                            ("slot_id", "family", "capacity", "seed", "group", "horizon", "year", "bucket", "objective", "cutoff_exclusive")}
                    payload = dict(spec, target=data["target"], weights=data["weights"],
                                   source_pins=old_release["current_execution_source_pins"])
                    model, meta = models.fit(slot, data["x"], payload,
                        dependencies=tuple(design["dependency_paths"]), on_fit_started=started)
                    require(meta["parameters"] == models.parameters("Ridge", "MID"), "ORIGINAL_RIDGE_PARAMETERS")
                require(row["fit_units"] == meta["actual_fit_count"] == 1, "ONE_PHYSICAL_COMPONENT_FIT")
                mp = folder / "model.joblib"
                joblib.dump(model, mp)
                model_ref = reference(mp)
                row.update(status="TRAINED", model_ref=model_ref, metadata=meta,
                    original_object_bytes_restored=model_ref["sha256"] == record["original_model_ref"]["sha256"])
            except BaseException as exc:
                row.update(status="FAILED", error=type(exc).__name__ + ":" + str(exc))
                raise
            finally:
                put(rp, row, roots)
            completed[slot] = row
            return row
        # Preserve the initial R1 API. A linked R2/R3 stage was already required
        # to reuse all four existing scaler receipts before reaching this point.
        if "base_component_restore_release_ref" not in release:
            for slot, data in prepared["inputs"].items():
                if slot in completed:
                    continue
                arrays = _component_arrays(data)
                try:
                    fit_one(slot, arrays)
                finally:
                    close_component_arrays(arrays)
        require({s for s in completed if records[s]["kind"] == "scalers"}
                == set(prepared["inputs"]), "COMPLETED_SCALERS_REQUIRED_BEFORE_RIDGE")
        scaled = verified_component_scaled_inputs(release, release_ref, out, records, completed,
                                                  prepared, recovery, solver, roots)
        for group in GROUPS:
            slot = f"ACTION_VALUE_{group}_H5_2024_ridge_MID_20260928"
            data = scaled["groups"][group]
            if slot in completed:
                continue
            component_memory_admission(solver, data["model_identity"]["x_shape"], "fit")
            arrays = _component_arrays(data)
            try:
                recovery.check_commitments(arrays["x"], arrays["dates"], arrays["weights"], arrays["target"],
                                           data["features"], data["model_identity"])
                fit_one(slot, arrays)
            finally:
                close_component_arrays(arrays)
    bundle = document(release["original_model_bundle_ref"])
    bundle = dict(bundle, original_model_bundle_ref=release["original_model_bundle_ref"],
                  component_restore_release_ref=release_ref, restoration_receipt_refs={})
    for slot, record in records.items():
        bundle["nodes"][record["group"]][record["role"]] = completed[slot]["model_ref"]
        rp = completed[slot].get("_actual_receipt_ref") or reference(out / "objects" / slot / "fit_receipt.json")
        bundle["restoration_receipt_refs"][slot] = rp
        if record["kind"] == "ridge":
            bundle["nodes"][record["group"]]["ridge_receipt_ref"] = rp
    bundle["physical_restoration_fits"] = dict(scalers=6 if correction_result_ref else 4, ridge=2, elasticnet=0)
    if correction_result_ref:
        bundle["numeric_execution_correction_ref"] = correction_result_ref
        bundle["physical_restoration_fit_breakdown"] = dict(initial_scalers=4, numeric_correction_scalers=2, ridge=2, elasticnet=0)
    put(out / "MODEL_BUNDLE_RESTORED_R1.json", bundle, roots)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("contract", "contract-sha", "release", "release-sha", "run"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--stage", choices=("metadata", "prepare", "fit", "component-metadata", "component-prepare", "component-fit", "component-numeric-correction"), default="metadata")
    args = parser.parse_args()
    contract_ref = dict(path=str(Path(args.contract).resolve()), sha256=args.contract_sha)
    release_ref = dict(path=str(Path(args.release).resolve()), sha256=args.release_sha)
    if args.stage.startswith("component-"):
        release, old_release, roots, out, records = validate_component_restore(contract_ref, release_ref, args.run)
        if args.stage == "component-metadata":
            result = dict(status="COMPONENT_METADATA_VALIDATED", numeric_read=False, physical_fits=0)
        else:
            from scripts.research.a2.training.stateful_execution import continuation_lock
            with continuation_lock(Path(args.run).resolve(), release["driver_ref"]["sha256"], namespace=TASK):
                if args.stage == "component-numeric-correction":
                    result = component_numeric_correction(release, old_release, roots, out, records, release_ref)
                elif args.stage == "component-prepare":
                    result = component_prepare(release, old_release, roots, out, records, release_ref)
                else:
                    result = component_fit(release, old_release, roots, out, records, release_ref)
        print(json.dumps({"status":result["status"]}, sort_keys=True))
        return
    _, release, roots, out, records = validate(contract_ref, release_ref, args.run)
    if args.stage == "metadata":
        result = dict(status="METADATA_VALIDATED", groups=list(records),
                      numeric_read=False, fit=False, consensus_application_validated=False)
    else:
        from scripts.research.a2.training.stateful_execution import continuation_lock
        # One existing owner lock covers the complete mutable stage, including
        # zero-fit recovery. A competing process never reaches reads or fitting.
        with continuation_lock(Path(args.run).resolve(),
                               release["driver_ref"]["sha256"], namespace=TASK):
            if args.stage == "prepare":
                result = prepare(release, roots, out, records, release_ref)
            else:
                result = fit(release, roots, out, records, release_ref)
    print(json.dumps({key: result[key] for key in ("status",) if key in result}, sort_keys=True))


if __name__ == "__main__":
    main()

