"""Six learned combinations plus two fixed controls; original durable owner.

Import is source-only. CLI preparation and account execution require the new
sealed evaluation release and all six trained gross states. Old baseline and
ETF ledgers are opaque report dependencies, never account execution keys.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import FunctionType, SimpleNamespace

TASK = "A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1"
BASES = ("R10_DIRECT_MEAN4_ELASTICNET_MID", "R10_DIRECT_H5_RIDGE_MID")
LEARNED_IDS = tuple(base + "__GROSS_" + learner for base in BASES for learner in ("LINEAR", "TREE", "NEURAL"))
IDS = LEARNED_IDS + tuple(base + "__GROSS_FIXED_050" for base in BASES)
PHASE = "FROZEN2026"
_FIXED_HALF = object()
# The new wrapper reuses these business owners; the release binds their bytes.
OWNER_FILES = (
    "evaluation/stateful_frozen_six_path.py", "evaluation/aggregate_13f_retest.py",
    "inference/stateful_test_inputs.py", "inference/frozen_a94_actions.py",
    "inference/consensus_paper.py", "training/stateful_replay.py",
    "training/stateful_final_action.py", "training/stateful_final_action_packets.py",
    "training/stateful_mechanism.py", "training/stateful_mechanism_models.py",
    "training/base_conditioned_gross.py", "training/base_conditioned_gross_history.py",
    "training/base_conditioned_gross_run.py", "training/stateful_execution.py",
    "evaluation/base_conditioned_gross_runtime.py", "evaluation/base_conditioned_gross_profile.py",
    "data/consensus_account_inputs.py", "../../common/json_projection.py",
)


def need(ok, code):
    if not ok:
        raise ValueError("BASE_GROSS_EVAL_" + code)


def reference(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(path=str(path), sha256=digest)


def verify(ref):
    need(isinstance(ref, dict) and reference(ref["path"]) == {**ref, "path": str(Path(ref["path"]).resolve())}, "REFERENCE_CHANGED")
    return Path(ref["path"])


def document(ref, *, limit=250_000):
    need(Path(ref["path"]).stat().st_size <= limit, "BOUNDED_METADATA_REQUIRED")
    value = json.loads(verify(ref).read_text(encoding="utf-8-sig"))
    need(isinstance(value, dict), "METADATA_OBJECT_REQUIRED")
    return value


def clone(fn, **changes):
    scope = dict(fn.__globals__)
    scope.update(changes)
    result = FunctionType(fn.__code__, scope, fn.__name__, fn.__defaults__, fn.__closure__)
    result.__kwdefaults__ = fn.__kwdefaults__
    return result


def module(ref, name):
    path = verify(ref)
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    exec(compile(path.read_bytes(), str(path), "exec"), value.__dict__)
    return value


def validate_source_owners(manifest, release):
    root = Path(__file__).resolve().parents[1]
    expected = {name: reference(root / name) for name in OWNER_FILES}
    need(manifest.get("source_owner_refs") == expected, "BUSINESS_SOURCE_OWNER_CHANGED")
    released = list(release.get("owner_refs", {}).values())
    need(all(ref in released for ref in expected.values()), "BUSINESS_SOURCE_OWNER_NOT_RELEASED")
    need(manifest.get("feature_provider_owner_ref") == expected["training/base_conditioned_gross_history.py"],
         "FEATURE_PROVIDER_OWNER_CHANGED")


def original_direct_roles(ref):
    """Project only the original complete-frame metadata; skip daily payloads."""
    from scripts.common.json_projection import _parser_type
    path = verify(ref)
    need(path.stat().st_size <= 2_000_000, "DIRECT_ROLE_METADATA_SIZE")
    parser_type = _parser_type()
    with path.open("rb") as stream:
        header = parser_type(stream).metadata_fields({"task_id", "new_fit", "model_predict", "account"})
    need(header == dict(task_id="A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1",
                        new_fit=0, model_predict=0, account=0), "ORIGINAL_DIRECT_METADATA_SCHEMA")
    roles = {}
    for role in ("R10:ENTRY", "R10:INCUMBENT"):
        with path.open("rb") as stream:
            parser = parser_type(stream)
            parser.descend(("roles", role))
            item = parser.metadata_fields({"frame_ref", "read_columns", "commitment", "computed_signal_dates"})
        dates = item.pop("computed_signal_dates")
        need(len(dates) == len(set(dates)) and dates == sorted(dates)
             and dates[0] == "2026-01-02" and dates[-1] == "2026-10-08", "COMPLETE_ORIGINAL_ROLE_CALENDAR")
        item["full_frame_scope"] = dict(date_column="signal_date", start=dates[0], end=dates[-1],
                                       computed_signal_date_count=len(dates))
        roles[role] = item
    return roles


def validate_direct_roles(manifest):
    roles = original_direct_roles(manifest["direct_role_metadata_ref"])
    closure = document(manifest["original_input_closure_ref"])
    need(manifest.get("direct_roles") == roles
         and closure.get("reused_direct_role_metadata_ref") == manifest["direct_role_metadata_ref"]
         and closure.get("new_fit_count") == closure.get("account_replay")
             == closure.get("outcome_columns_in_model_features") == closure.get("label_columns_decoded") == 0,
         "ORIGINAL_COMPLETE_ROLE_METADATA_CHANGED")
    for role, item in roles.items():
        need(closure["feature_frame_refs"][role] == item["frame_ref"]
             and closure["action_feature_inputs"][role]["commitment"] == item["commitment"],
             "ORIGINAL_FULL_FRAME_COMMITMENT_BINDING")


def gross_model_refs(bundle):
    need(bundle.get("status") == "SIX_GROSS_MODELS_TRAINED", "ALL_SIX_MODELS_MUST_BE_READY")
    rows = bundle.get("models", [])
    expected = [(base, learner) for base in BASES for learner in ("linear", "tree", "neural")]
    need([(r.get("base"), r.get("learner")) for r in rows] == expected
         and all(r.get("status") == "TRAINED" for r in rows), "EXACT_SIX_TRAINED_STATES")
    return {base + "__GROSS_" + learner.upper(): row["model_ref"]
            for (base, learner), row in zip(expected, rows)}


def startup(release_ref, input_manifest_ref, stage):
    """Bounded metadata and authority first; no model/input decoding."""
    from scripts.research.a2.evaluation import base_conditioned_gross_runtime as runtime
    from scripts.research.a2.evaluation import base_conditioned_gross_profile as profile
    need(stage in ("prepare", "account"), "EXACT_STAGE_REQUIRED")
    release = document(release_ref)
    need(release.get("status") == "ROOT_SOURCE_AND_POLICY_BOUND"
         and release.get("task_id") == TASK and release.get("phase") == PHASE
         and release.get("eval_input_manifest_ref") == input_manifest_ref
         and release.get("driver_ref") == reference(__file__)
         and release.get("permits", {}).get(stage) is True, "ROOT_STAGE_RELEASE_REQUIRED")
    manifest = document(input_manifest_ref)
    need(manifest.get("schema") == "BASE_CONDITIONED_GROSS_EVALUATION_INPUTS_R1"
         and manifest.get("task_id") == TASK and manifest.get("status") == "ROOT_FROZEN_EVALUATION_INPUTS"
         and manifest.get("candidate_ids") == list(IDS)
         and manifest.get("contract_ref") == profile.CONTRACT_REF, "EXACT_EVALUATION_INPUTS_REQUIRED")
    validate_source_owners(manifest, release)
    validate_direct_roles(manifest)
    refs = gross_model_refs(document(manifest["gross_bundle_ref"]))
    for cid, ref in refs.items():
        states = [s for s in release.get("state_refs", {}).values()
                  if s.get("role") == "gross" and s.get("candidate_id") == cid]
        need(len(states) == 1 and states[0].get("model_ref") == ref, "GROSS_STATE_RELEASE_BINDING")
    for base in BASES:
        for group in ("ENTRY", "INCUMBENT"):
            item = manifest["base_model_refs"][base][group]
            for role, key in (("base", "model_ref"), ("scaler", "scaler_ref")):
                matches = [state for state in release["state_refs"].values()
                           if state.get("role") == role and state.get("base_id") == base
                           and state.get("group") == group and state.get("model_ref") == item[key]]
                need(len(matches) == 1, "BASE_AND_SCALER_STATE_RELEASE_BINDING")
    need(release.get("source_refs", {}).get("corporate_actions") == manifest["account_catalog_ref"],
         "NEW_TASK_ACCOUNT_CATALOG_ROOT_BOUND")
    runtime.bootstrap(profile.RUNTIME_BINDING_REF, phase=PHASE)
    profile.install_routes(profile.RUNTIME_BINDING_REF, PHASE)
    from scripts.research.a2.evaluation import frozen_test_authority as authority
    auth = authority.load_descriptive_authority(dict(schema=profile.SCHEMA, task_id=TASK,
        release_ref=release_ref, window_id="MAIN"))
    candidates = [r["specification"] for r in release["candidate_bindings"]]
    authority.validate_descriptive_policy(auth, candidates)
    need(tuple(c["candidate_id"] for c in candidates) == IDS, "EXACT_EIGHT_POLICIES_REQUIRED")
    # Baselines are retained as opaque references. No old ledger is opened here.
    need(manifest.get("matched_baseline_index_ref") is None
         or isinstance(manifest["matched_baseline_index_ref"], dict), "OPAQUE_MATCHED_BASELINE_REFERENCE_REQUIRED")
    return release, manifest, refs


def _process_memory_bytes():
    """Read only this process; no working-set trimming or other-process control."""
    import ctypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ("peak_rss", "rss", "peak_paged", "paged",
                "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    read = ctypes.windll.psapi.GetProcessMemoryInfo
    read.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    need(read(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb), "PROCESS_MEMORY_READ")
    return dict(rss=int(counters.rss), private=int(counters.private))


def _prepare_resource_requirements(budget, current):
    """Reserve the measured remaining stage allocation plus explicit headroom."""
    peak_rss, peak_private = budget["peak_rss_ceiling_bytes"], budget["peak_private_ceiling_bytes"]
    need(0 < current["rss"] <= peak_rss and 0 < current["private"] <= peak_private,
         "PREPARE_MEMORY_CALIBRATION_EXCEEDED")
    return dict(physical_bytes=max(peak_rss - current["rss"], budget["max_stage_increment_bytes"]) + 256 * 2**20,
                commit_bytes=max(8 * 2**30, peak_private - current["private"] + 512 * 2**20))


def _resource(manifest, *, prepare=True):
    from scripts.research.a2.training.base_conditioned_gross_run import resource_gate
    ref = manifest.get("prepare_memory_budget_ref") if prepare else None
    if ref is None:
        return resource_gate(manifest["resource_owner_ref"])
    budget = document(ref)
    need(budget.get("schema") == "BASE_GROSS_PREPARE_MEMORY_BUDGET_R1"
         and budget.get("task_id") == TASK and budget.get("stage") == "prepare"
         and budget.get("driver_ref") == reference(__file__)
         and budget.get("flags_ref") == manifest["flags_ref"]
         and budget.get("source_bundle_ref") == manifest["source_bundle_ref"]
         and budget.get("base_model_refs") == manifest["base_model_refs"]
         and budget.get("direct_role_rows") == {role: item["commitment"]["rows"]
                                               for role, item in manifest["direct_roles"].items()},
         "PREPARE_MEMORY_SCOPE_CHANGED")
    probe = document(budget["calibration_ref"])
    numeric_increment = max(rows * (columns + 2 * encoded) * 8 for rows, columns, encoded in probe["shapes"].values())
    numeric_increment += probe["source_metadata_counts"]["flags"]["scope_rows"] * len(manifest["flags_read_columns"]) * 8
    numeric_increment += probe["source_metadata_counts"]["bars"]["total_footer_rows"] * 5 * 8
    need(probe.get("mode") == "chunks" and probe.get("source_driver_sha256") == budget["calibrated_driver_sha256"]
         and probe.get("task_id") == TASK and probe.get("new_fit") == 0
         and probe.get("actual_models_decoded") == 0 and probe.get("actual_account_executions") == 0
         and probe.get("output_rows_each_base") == sum(budget["direct_role_rows"].values())
         and budget.get("observed_peak_rss_bytes") == probe["observed_kernel_peak_rss_bytes"]
         and budget.get("observed_peak_private_bytes") == probe["observed_peak_process_pagefile_bytes"]
         and budget.get("max_stage_increment_bytes") == numeric_increment
         and budget.get("peak_rss_ceiling_bytes") == (3 * budget["observed_peak_rss_bytes"] + 1) // 2
         and budget.get("peak_private_ceiling_bytes") == (3 * budget["observed_peak_private_bytes"] + 1) // 2,
         "PREPARE_MEMORY_CALIBRATION_CHANGED")
    owner = module(manifest["resource_owner_ref"], "_base_gross_prepare_resource_owner")
    memory, current = owner.memory(), _process_memory_bytes()
    required = _prepare_resource_requirements(budget, current)
    need(memory["physical_gib"] * 2**30 >= required["physical_bytes"]
         and memory["page_gib"] * 2**30 >= required["commit_bytes"], "PREPARE_MEASURED_RESOURCE_ADMISSION")
    return dict(**memory, current_process=current, required=required, stage="prepare")


def _base_predictions(manifest, bridge, start, end):
    """Original complete-frame encoder/scaler/predictor/decoder, two heads."""
    import gc
    import joblib
    import numpy as np
    import pandas as pd
    from threadpoolctl import threadpool_limits
    from scripts.research.a2.inference import frozen_a94_actions as actions
    from scripts.research.a2.inference.consensus_paper import predict_r10, r10_scaled_input
    from scripts.research.a2.training import stateful_mechanism as mechanism
    from scripts.research.a2.training.stateful_final_action_packets import decode_r10_row
    roles = manifest["direct_roles"]
    need(set(roles) == {"R10:ENTRY", "R10:INCUMBENT"}, "EXACT_TWO_ORIGINAL_ROLES")
    output = {base: {} for base in BASES}
    for group in ("ENTRY", "INCUMBENT"):
        role = "R10:" + group
        item = roles[role]
        scope = item["full_frame_scope"]
        need(start == scope["start"] and end == scope["end"], "FULL_FRAME_FIRST_BEFORE_WINDOW_PROJECTION")
        features = actions.role_features(role)
        columns = item["read_columns"]
        need(set(features) <= set(columns) and not set(columns).intersection(actions.base.three._FORBIDDEN),
             "ORIGINAL_SIGNAL_ONLY_ROLE_COLUMNS")
        frame = bridge.bounded_frame(item["frame_ref"], columns, "signal_date", start, end)
        need(not frame.duplicated(["signal_date", "sample_id"]).any(), "ORIGINAL_ROLE_UNIQUE_KEYS")
        supported = ((frame.e_friction.notna() & frame.i_friction.notna()).to_numpy()
                     if group == "INCUMBENT" else np.ones(len(frame), bool))
        need(actions.input_commitment(frame, features, supported=supported) == item["commitment"],
             "ORIGINAL_FULL_FRAME_COMMITMENT_CHANGED")
        for base in BASES:
            _resource(manifest)
            refs = manifest["base_model_refs"][base][group]
            model = joblib.load(verify(refs["model_ref"]))
            scaler = joblib.load(verify(refs["scaler_ref"]))
            x, names = mechanism.encode(frame, features)
            need(x.shape[1] == scaler.n_features_in_ and len(names) == x.shape[1],
                 "ORIGINAL_ROLE_ENCODER_AND_SCALER_WIDTH")
            x = r10_scaled_input(scaler, x) if len(x) else x.copy()
            with threadpool_limits(limits=1):
                native = predict_r10(model, x) if len(x) else {}
            for chunk_start in range(0, len(frame), 256):
                records = frame.iloc[chunk_start:chunk_start + 256].to_dict("records")
                for i, row in enumerate(records, start=chunk_start):
                    values = {key: float(value[i]) if supported[i] else float("nan")
                              for key, value in native.items() if isinstance(value, np.ndarray) and value.shape == (len(frame),)}
                    day = pd.Timestamp(row["signal_date"])
                    rows = output[base].setdefault(day, [])
                    rows.append(decode_r10_row({**row, **values}, len(rows), group=group))
                del records
            del model, scaler, x, native
            gc.collect()
    return output


def prepare(release_ref, input_manifest_ref, run):
    release, manifest, _ = startup(release_ref, input_manifest_ref, "prepare")
    from scripts.research.a2.training.stateful_execution import continuation_lock, own_path
    from scripts.storage.storage_r2a import write_json_atomic
    run = Path(run).resolve()
    need(run.is_dir() and run.parent.name == TASK, "EXISTING_TASK_RUN_REQUIRED")
    target = own_path(run, run / "derived/gross_eval_source")
    receipt_path = target / "PREPARED_EVALUATION.json"
    identity = dict(release_ref=release_ref, input_manifest_ref=input_manifest_ref, driver_ref=reference(__file__))
    with continuation_lock(run, identity["driver_ref"]["sha256"], namespace=TASK + "_EVAL_SOURCE"):
        if receipt_path.exists():
            old = document(reference(receipt_path))
            need(old["identity"] == identity, "PREPARED_SOURCE_IDENTITY_CHANGED")
            verify(old["prepared_ref"])
            return old
        _resource(manifest)
        need(not target.exists(), "INCOMPLETE_SOURCE_PREPARATION_PRESERVED")
        import joblib
        import pandas as pd
        from scripts.research.a2.evaluation import base_conditioned_gross_profile as profile
        bridge = module(manifest["bounded_reader_ref"], "_base_gross_eval_bounded_reader")
        quote = module(manifest["quote_helper_ref"], "_base_gross_eval_quote_source")
        inference = document(manifest["original_top100_inference_ref"])
        need(inference["flags_ref"] == manifest["flags_ref"]
             and inference["flags_read_columns"] == manifest["flags_read_columns"], "REUSED_RAW_FLAGS_CHANGED")
        # Validate the original quote source's own custody, not old-task account authority.
        context, quote_source = quote.closed_context("TOP100", manifest["source_bundle_ref"], check_schema=True)
        need(context == manifest["quote_execution_context"], "EXACT_QUOTE_CUSTODY_REQUIRED")
        start, end = release["windows"][0]["start"], release["windows"][0]["end"]
        flags = bridge.bounded_frame(manifest["flags_ref"], manifest["flags_read_columns"], "signal_date", start, end)
        columns = quote_source.get("bars_read_columns", ["ticker", "trade_date", "open", "close", "quality"])
        bars = bridge.bounded_frame(quote_source["bars_ref"], columns, "trade_date", start, end)
        actions = _base_predictions(manifest, bridge, start, end)
        calendar = pd.DatetimeIndex(document(profile.SCHEDULE_REF)["common_sessions"])
        need(set(pd.to_datetime(flags.signal_date)) == set(calendar), "COMPLETE_ORIGINAL_SIGNAL_CALENDAR")
        catalog = load_account_catalog(manifest, run)
        target.mkdir(parents=True)
        path = target / "prepared_inputs.joblib"
        with path.open("xb") as stream:
            joblib.dump(dict(flags=flags, bars=bars, actions=actions, calendar=calendar, catalog=catalog), stream, compress=3)
        receipt = dict(status="PREPARED_FROZEN_SIGNAL_INPUTS", task_id=TASK, identity=identity,
            prepared_ref=reference(path), original_proxy_not_actual_account_state=True,
            account_executions=0, new_fit=0, formal_primary_metrics=None)
        write_json_atomic(receipt_path, receipt)
        return receipt


def load_account_catalog(manifest, run):
    expected = Path(run).resolve() / "derived/gross_evaluation_sources/ACCOUNT_CATALOG.json"
    ref = manifest["account_catalog_ref"]
    need(isinstance(ref, dict) and Path(ref["path"]).resolve() == expected,
         "NEW_TASK_TYPED_ACCOUNT_CATALOG_REQUIRED")
    catalog = document(ref, limit=2_000_000)
    need(catalog.get("task_id") == TASK and catalog.get("phase") == PHASE,
         "NEW_TASK_TYPED_ACCOUNT_CATALOG_SCOPE")
    return catalog


def make_gross_overlay(candidate, base_policy, model, input_provider):
    from scripts.research.a2.training import base_conditioned_gross as gross
    # This private clone changes only the fixed-control decoder. Shared globals stay untouched.
    def requested(actual_model, reference_inputs, previous):
        return .5 if actual_model is _FIXED_HALF else gross.predict_gross(actual_model, reference_inputs, previous)
    overlay_type = type("EvaluationGrossOverlay", (gross.BaseConditionedGrossOverlay,),
                        {"__call__": clone(gross.BaseConditionedGrossOverlay.__call__, predict_gross=requested)})
    cid = candidate["candidate_id"]
    need(cid in IDS, "EXACT_GROSS_CANDIDATE")
    need((model is _FIXED_HALF) == (cid not in LEARNED_IDS), "EXACT_FIXED_OR_LEARNED_REQUEST")
    return overlay_type((cid,), base_policy, {cid: model}, input_provider)


def execute_path(candidate, data, admitted):
    import pandas as pd
    from scripts.research.a2.evaluation import stateful_frozen_six_path as nav
    from scripts.research.a2.training import stateful_replay as replay
    from scripts.research.a2.training.stateful_final_action import FinalActionOverlay
    from scripts.research.a2.training.stateful_final_action_packets import decode_resource_proposals
    cid = candidate["candidate_id"]
    base = cid.split("__GROSS_", 1)[0]
    holder = {}
    def factory(candidates, packets, top, qualified, vol, **kwargs):
        base_overlay = FinalActionOverlay(candidates, packets, top, qualified, vol,
            action_packets={cid: data["action_packets"][base]}, resource_decoder=decode_resource_proposals,
            sid_by_key=data["sid_by_key"], **kwargs)
        overlay = make_gross_overlay(candidate, base_overlay, (data["models"][cid] if cid in LEARNED_IDS else _FIXED_HALF), data["input_provider"])
        holder.update(base=base_overlay, gross=overlay)
        return overlay
    result, frames = replay.execute_market(data["market"], [candidate], data["packets"], data["top"],
        data["qualified"], data["vol"], deepcopy(data["account"]),
        stock_present=data["stock_present"], raw_selector_present=data["raw_selector_present"],
        policy_factory=factory, execution_friction=candidate["execution_friction"],
        descriptive_evaluation_authority=admitted, **deepcopy(data["account_source_kwargs"]))
    frames = nav._dual_nav_frames(result, frames)
    frames["learned_action_decisions"] = pd.DataFrame(holder["base"].action_audit)
    return frames


def durable_runner(release, *, path_executor=execute_path):
    """Keep the original checkpoint/journal/failure code, scoped to eight paths."""
    from scripts.research.a2.evaluation import stateful_frozen_six_path as old
    from scripts.research.a2.evaluation import frozen_test_authority as authority
    from scripts.research.a2.evaluation import base_conditioned_gross_profile as profile
    candidates = [r["specification"] for r in release["candidate_bindings"]]
    def policies(rows):
        need(rows == candidates and tuple(r["candidate_id"] for r in rows) == IDS, "FULL_FROZEN_POLICY_BYTES_REQUIRED")
    def keys(schedule):
        need(schedule.get("task_id") == TASK and schedule.get("path_ids") == list(IDS)
             and schedule.get("windows") == release["windows"] and len(schedule["windows"]) == 101
             and schedule.get("account_paths") == 808, "EXACT_808_SCHEDULE_REQUIRED")
        return [(w["window_id"], cid) for w in schedule["windows"] for cid in IDS]
    source_ready = release.get("native_descriptive_metrics_allowed") is True
    def qualification(frames):
        gate = old._qualification(frames)
        gate["groups"]["source_admitted_for_native_metrics"] = source_ready
        gate["all_passed"] = gate["all_passed"] and source_ready
        return gate
    authority_view = SimpleNamespace(**{key: value for key, value in vars(authority).items() if not key.startswith("__")})
    authority_view.six_path_tasks = lambda: (TASK,)
    authority_view.six_path_plan_sha256 = lambda task: profile.CONTRACT_REF["sha256"] if task == TASK else None
    common = dict(PATH_IDS=IDS, MAX_PATHS=808, _validate_policy_rows=policies, _schedule_keys=keys,
                  authority=authority_view, _execute_path=path_executor, _qualification=qualification)
    original_schedule = clone(old.execute_schedule, **common)
    def schedule_runner(schedule, rows, *, record_event, consume_result, **kwargs):
        def decorate(report):
            report.update(formal_primary_metrics=None, source_completeness_unknown=True,
                          matched_baselines_replayed=False, scheduled_candidate_count=8, scheduled_window_count=101)
        def record(event):
            if event["event"] != "STARTED": decorate(event)
            record_event(event)
        def consume(window, candidate, frames, report):
            decorate(report)
            consume_result(window, candidate, frames, report)
        reports = original_schedule(schedule, rows, record_event=record, consume_result=consume, **kwargs)
        for report in reports: decorate(report)
        return reports
    return clone(old.execute_durable, **common, __file__=__file__, execute_schedule=schedule_runner)


def account(release_ref, input_manifest_ref, run):
    release, manifest, model_refs = startup(release_ref, input_manifest_ref, "account")
    from scripts.research.a2.evaluation import base_conditioned_gross_profile as profile
    from scripts.research.a2.evaluation import frozen_test_authority as authority
    from scripts.research.a2.inference import stateful_test_inputs
    from scripts.research.a2.training import stateful_replay as replay
    from scripts.research.a2.evaluation import aggregate_13f_retest
    from scripts.research.a2.training import base_conditioned_gross_history as history
    import joblib
    import pandas as pd
    run = Path(run).resolve()
    receipt = document(reference(run / "derived/gross_eval_source/PREPARED_EVALUATION.json"))
    need(receipt["identity"] == dict(release_ref=release_ref, input_manifest_ref=input_manifest_ref, driver_ref=reference(__file__)),
         "PREPARED_ACCOUNT_IDENTITY_CHANGED")
    need(manifest["feature_provider_owner_ref"] == reference(history.__file__), "FEATURE_PROVIDER_OWNER_CHANGED")
    candidates = [r["specification"] for r in release["candidate_bindings"]]
    schedule = dict(task_id=TASK, path_ids=list(IDS), windows=release["windows"], account_paths=808)
    shared = {}
    def authority_for_window(window):
        request = dict(schema=profile.SCHEMA, task_id=TASK, release_ref=release_ref, window_id=window["window_id"])
        return authority.validate_descriptive_policy(authority.load_descriptive_authority(request), candidates)
    def inputs_for_window(window, admitted):
        _resource(manifest, prepare=False)
        if not shared:
            prepared = joblib.load(verify(receipt["prepared_ref"]))
            models = {}
            for cid, ref in model_refs.items():
                _resource(manifest, prepare=False)
                models[cid] = joblib.load(verify(ref))
            old = module(manifest["account_helpers_ref"], "_base_gross_eval_account_sources")
            shared.update(prepared=prepared, models=models, old=old)
        data = shared["prepared"]
        dates = data["calendar"]
        dates = dates[(dates >= pd.Timestamp(window["start"])) & (dates <= pd.Timestamp(window["end"]))]
        view = stateful_test_inputs.project_window(data["flags"], data["bars"], dates, admitted, values_function=replay._old().values)
        config, sources = shared["old"].account_inputs(data["catalog"], admitted)
        need(config == manifest["account"], "ORIGINAL_ACCOUNT_CONFIG_REQUIRED")
        provider = history.feature_provider(data["flags"], view["market"].tickers)
        def signal_inputs(di, context, row):
            _, matrix, scores = provider(di, context, row)
            return matrix, scores
        view.update(account=config, account_source_kwargs=sources, action_packets=data["actions"],
            packets={"ridge": aggregate_13f_retest.raw_diagnostic_packet(dates, view["market"].tickers)},
            models=shared["models"], input_provider=signal_inputs)
        # The original executor routes paths after index 3 through their own key.
        return {"stocks": view, **{cid: view for cid in IDS}}
    execute = durable_runner(release)
    return execute(run, schedule, candidates, authority_for_window=authority_for_window,
        inputs_for_window=inputs_for_window, expected_run_config_sha256=manifest["run_config_ref"]["sha256"])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("prepare", "account"), required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--inputs-sha", required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    release = dict(path=str(Path(args.release).resolve()), sha256=args.release_sha)
    inputs = dict(path=str(Path(args.inputs).resolve()), sha256=args.inputs_sha)
    result = (prepare if args.stage == "prepare" else account)(release, inputs, args.run)
    print(json.dumps(dict(stage=args.stage, status="COMPLETE", task_id=TASK,
                         windows=101 if args.stage == "account" else 0, new_fit=0)))
    return result


if __name__ == "__main__":
    main()