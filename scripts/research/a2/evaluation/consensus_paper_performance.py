"""Bounded extension of the three fixed MAIN paper curves; no fits or selection.

This consumer owns a new finite descriptive gate. The original admissions,
algorithms, releases and MAIN ledgers remain immutable. Publication requires
identity of the entire accepted prefix, including cash, positions, fills and CA.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import gc
import hashlib
import inspect
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import textwrap

TASK = "DEMO_FIVE_STRATEGY_PAPER_20261013_R1"
SCHEMA = "CONSENSUS_FIXED_MAIN_PAPER_EXTENSION_R1"
START, FIRST_EXECUTION, PREFIX_END, MAX_END = "2026-01-02", "2026-01-05", "2026-10-08", "2026-10-12"
IDS = ("R10_DIRECT_MEAN4_ELASTICNET_MID", "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR")
TABLES = {"daily": ("date", ["date", "path_id"]),
          "positions": ("date", ["date", "path_id", "ticker"]),
          "fills": ("execution_date", ["execution_date", "path_id", "ticker", "side"]),
          "entitlements": ("session", ["session", "path_id", "event_id", "phase"])}
STOCK_TABLES = {"actions": ("signal_date", ["signal_date", "path_id", "ticker"]),
                "orders": ("signal_date", ["signal_date", "path_id", "ticker", "order_id"])}
LEDGER_TABLES = {**TABLES, **STOCK_TABLES}
_SEAL = object()
_REPAIR = Path("D:/us-tech-quant-backtests/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/20261010T155614+0000_8a89315b/derived/remaining10")
_RIDGE = Path("D:/us-tech-quant-backtests/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/20261009T040010+0000_ebc89ace/derived/consensus_all_a")
ACCEPTED_MAIN = {
    IDS[0]: dict(path=str(_REPAIR / "solver_continuation/accounts/shared_batch/MAIN/COMPLETION.json"), sha256="6f5cca2e95754e9f2b968c4eefe3018c29385971f18da62cff4c00787b74249e"),
    IDS[1]: dict(path=str(_RIDGE / "accounts/MAIN/FINAL_ACTION_OVERLAY_10bps/completion.json"), sha256="93dadc2336c2a74f688a17c153dd2cfa94332b9ed8513fc0d86b3cb78ca9b5b0"),
    IDS[2]: dict(path=str(_REPAIR / "R7/accounts/attempt_001/MAIN/SHARED_BATCH_COMPLETION.json"), sha256="a450b6d33e59531f9a92ea854c3c70264174254d3be96b222824436e6864b972"),
}
ROOT_RELEASES = {
    IDS[0]: dict(path="D:/us-tech-quant-results/_maintenance/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/NUMERICAL_CONTINUATION_ROOT_ACCOUNT_RELEASE_R5.json", sha256="fd7fd204159e76e7af629f6f18b0bd2b026b2dbdbc6bc25717f9744af650c707"),
    IDS[2]: dict(path="D:/us-tech-quant-results/_maintenance/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/R7_ACCOUNT_ADAPTER_ROOT_ACCOUNT_RELEASE_R1.json", sha256="4f24d51d15090e5f4b7a0f07c8ba098b8a50c2558754c004639aba3f4400fb02"),
}
RIDGE_CONFIG = dict(path=str(_RIDGE / "account_inputs/attempt_002/A_ALL_ACCOUNT_EXECUTION_CONFIG.json"), sha256="8de6c969b5fc08c2af5ac31ac8f010e3ddf7c47a1071c4b0c74fcd2df66aafa0")
R7_RELEASE = ROOT_RELEASES[IDS[2]]
CALENDAR_HELPER = "scripts.daily_recommendation_inputs.latest_completed_session"


def need(ok, message):
    if not ok:
        raise ValueError(message)


def resource_snapshot():
    """OS/worker diagnostics only; the existing consumer owns the admission floor."""
    import ctypes
    import os
    from scripts.research.a2.inference import consensus_paper as consumer
    result = dict(worker=consumer.process_memory())
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(key, ctypes.c_ulonglong) for key in
                ("total_phys", "avail_phys", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_extended_virtual")]
        memory = Memory(); memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result.update(available_physical_bytes=memory.avail_phys, available_page_bytes=memory.avail_page)
    return result


def check_resources(stage, *, candidate_id=None, group=None):
    from scripts.research.a2.inference import consensus_paper as consumer
    try:
        consumer.resource_check()
    except ValueError:
        # A bounded technical event supplements the unchanged original exception.
        # Diagnostics cannot admit, retry, clear caches or alter any model state.
        print(canonical(dict(event="PAPER_EXTENSION_RESOURCE_GATE_REJECTED", stage=stage,
            candidate_id=candidate_id, group=group, memory=resource_snapshot())), flush=True)
        raise


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def reference(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(path=str(path), sha256=digest)


def verified(ref):
    need(isinstance(ref, dict) and reference(ref["path"]) == {"path": str(Path(ref["path"]).resolve()), "sha256": ref["sha256"]}, "PAPER_EXTENSION_REFERENCE_CHANGED")
    return Path(ref["path"]).resolve()


def projected_metadata(ref, keys, path=()):
    from scripts.common.json_projection import _parser_type
    with verified(ref).open("rb") as stream:
        reader = _parser_type()(stream)
        if path:
            reader.descend(path)
        return reader.metadata_fields(set(keys))


_ACCOUNT_CATALOG_FILE_BYTES = 32 * 1024 * 1024
_ACCOUNT_CASH_ITEM_BYTES = 65536
_ACCOUNT_CASH_MAX_ITEMS = 2500


def projected_account_catalog(ref):
    """Keep the original exact cash-event sequence with bounded item decoding."""
    from scripts.common.json_projection import _parser_type
    path = verified(ref)
    need(path.stat().st_size <= _ACCOUNT_CATALOG_FILE_BYTES, "PAPER_EXTENSION_ACCOUNT_CATALOG_FILE_LIMIT")
    keys = {"share_events", "cash_events", "terminal_events", "strict_terminal_events", "known_at", "unsupported_events",
        "engine_scheduled_unsupported_record_indices", "security_tickers", "entitlement_source_binding", "source_completeness_unknown"}
    catalog = {}
    with path.open("rb") as stream:
        reader = _parser_type()(stream); reader.expect(b"{"); reader.white()
        while reader.peek() != b"}":
            key = reader.string(True); reader.expect(b":")
            if key in keys:
                need(key not in catalog, "SOURCE_JSON_DUPLICATE_METADATA_KEY")
                if key == "cash_events":
                    events = []; reader.expect(b"["); reader.white()
                    while reader.peek() != b"]":
                        need(len(events) < _ACCOUNT_CASH_MAX_ITEMS, "PAPER_EXTENSION_ACCOUNT_CASH_EVENT_COUNT_LIMIT")
                        event = reader.scalar(limit=_ACCOUNT_CASH_ITEM_BYTES)
                        need(isinstance(event, dict), "PAPER_EXTENSION_ACCOUNT_CASH_EVENT_OBJECT_REQUIRED")
                        events.append(event)
                        reader.white(); separator = reader.take()
                        if separator == b"]": break
                        need(separator == b",", "PAPER_EXTENSION_ACCOUNT_CASH_EVENT_ARRAY_CHANGED")
                        reader.white(); need(reader.peek() != b"]", "SOURCE_JSON_EMPTY_VALUE")
                    else: reader.take()
                    catalog[key] = events
                else: catalog[key] = reader.scalar(limit=65536)
            else: reader.skip()
            reader.white(); separator = reader.take()
            if separator == b"}": break
            need(separator == b",", "SOURCE_JSON_STRUCTURE_CHANGED")
        else: reader.take()
    verified(ref)  # Reject a changed catalog before passing any decoded events to the original owner.
    return catalog


def completion_refs(ref, candidate_id):
    identity = projected_metadata(ref, ("candidate_ids", "window", "identity_ref", "new_fit"))
    need(candidate_id in identity.get("candidate_ids", []), "PAPER_EXTENSION_ORIGINAL_CANDIDATE_MISMATCH")
    if "window" in identity:
        window = identity["window"]
        need(window.get("window_id") == "MAIN" and window.get("start") == START and window.get("end") == PREFIX_END
             and window.get("first_execution_date") == FIRST_EXECUTION, "PAPER_EXTENSION_ORIGINAL_MAIN_CHANGED")
    need(identity.get("new_fit", 0) == 0, "PAPER_EXTENSION_ORIGINAL_NO_FIT_REQUIRED")
    result = {name: projected_metadata(ref, ("path", "sha256"), ("artifacts", name)) for name in LEDGER_TABLES}
    need(all(set(value) == {"path", "sha256"} for value in result.values()), "PAPER_EXTENSION_ORIGINAL_LEDGER_REFS_REQUIRED")
    return result, identity


def bounded_ledger(ref, table, candidate_id, end):
    """Decode only this fixed strategy and the explicitly authorized prefix."""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.dataset as ds
    need(table in LEDGER_TABLES and candidate_id in IDS and PREFIX_END <= str(end) < "2027-01-01", "PAPER_EXTENSION_LEDGER_SCOPE")
    data = ds.dataset(verified(ref), format="parquet")
    clock, _ = LEDGER_TABLES[table]
    need({"path_id", clock} <= set(data.schema.names), "PAPER_EXTENSION_LEDGER_SCHEMA")
    dtype = data.schema.field(clock).type
    def day(value):
        return value if pa.types.is_string(dtype) or pa.types.is_large_string(dtype) else pd.Timestamp(value).to_pydatetime()
    predicate = (ds.field("path_id") == candidate_id) & (ds.field(clock) >= day(START)) & (ds.field(clock) <= day(str(end)))
    chunks, count = [], 0
    for batch in data.scanner(columns=data.schema.names, filter=predicate, batch_size=1024, use_threads=False).to_batches():
        count += batch.num_rows
        need(count <= 200000, "PAPER_EXTENSION_LEDGER_ROW_LIMIT")
        chunks.append(batch.to_pandas())
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=data.schema.names)


def _ordered(frame, table, sid, end):
    import pandas as pd
    clock, keys = LEDGER_TABLES[table]
    need({"path_id", clock} <= set(frame), "PAPER_EXTENSION_LEDGER_SCHEMA")
    subset = frame.loc[frame.path_id.eq(sid) & pd.to_datetime(frame[clock]).between(START, end)].copy()
    need(set(keys) <= set(subset), "PAPER_EXTENSION_LEDGER_KEYS_REQUIRED")
    return subset.sort_values(keys, kind="stable").reset_index(drop=True)


def _prefix_failure_diagnostic(actual, expected, *, candidate_id, table, event="PAPER_EXTENSION_ACCEPTED_PREFIX_CHANGED"):
    """Only bounded schema metadata; assertion text and cell values never enter output."""
    def label(value, limit=64):
        return value[:limit] if isinstance(value, str) else type(value).__name__[:limit]
    def schema(frame):
        return dict(shape=[int(size) for size in frame.shape], column_count=len(frame.columns),
            columns=[dict(name=label(name), dtype=str(dtype)[:64])
                for name,dtype in list(zip(frame.columns,frame.dtypes))[:32]],
            columns_truncated=len(frame.columns)>32)
    left, right = set(actual.columns), set(expected.columns)
    changed=[]
    for name in list(actual.columns)[:64]:
        if name in right and not actual[name].equals(expected[name]):
            changed.append(label(name))
            if len(changed)==16:break
    payload=dict(event=label(event,128), candidate_id=label(candidate_id,128),table=label(table),
        actual=schema(actual),expected=schema(expected),
        actual_only_columns=[label(name) for name in actual.columns if name not in right][:16],
        expected_only_columns=[label(name) for name in expected.columns if name not in left][:16],
        different_columns=changed,different_columns_scan_limit=64,cell_values_included=False)
    encoded=canonical(payload)
    if len(encoded.encode("utf8"))+2>16384:
        for name in ("actual","expected"):
            payload[name]["columns"]=payload[name]["columns"][:8]
            payload[name]["columns_truncated"]=True
        payload["schema_details_truncated"]=True
        encoded=canonical(payload)
    if len(encoded.encode("utf8"))+2>16384:
        for name in ("actual","expected"):payload[name]["columns"]=[]
        payload.update(actual_only_columns=[],expected_only_columns=[],different_columns=[])
        encoded=canonical(payload)
    return encoded


def compare_prefix(frames, baseline_refs, candidate_id):
    """Exact cells/schema plus the original account prefix-identity algorithm."""
    import pandas as pd
    from scripts.research.a2.evaluation.continuous_research_account import account_prefix_identity
    need(candidate_id in IDS and set(TABLES) <= set(frames) and set(TABLES) <= set(baseline_refs), "PAPER_EXTENSION_FOUR_PREFIX_TABLES_REQUIRED")
    expected, actual, receipts = {}, {}, {}
    for name in TABLES:
        expected[name] = _ordered(bounded_ledger(baseline_refs[name], name, candidate_id, PREFIX_END), name, candidate_id, PREFIX_END)
        actual[name] = _ordered(frames[name], name, candidate_id, PREFIX_END)
        try:
            pd.testing.assert_frame_equal(actual[name], expected[name], check_exact=True, check_dtype=True, check_like=True)
        except AssertionError as exc:
            try:
                print(_prefix_failure_diagnostic(actual[name],expected[name],candidate_id=candidate_id,table=name),flush=True)
            except Exception:
                pass  # A diagnostic failure must not replace the original strict rejection.
            raise ValueError("PAPER_EXTENSION_ACCEPTED_PREFIX_CHANGED:" + name) from exc
        receipts[name] = dict(status="EXACT_MATCH", rows=len(actual[name]), original_ref=baseline_refs[name])
    def replay(values):
        return SimpleNamespace(**values, metadata=dict(path_ids=[candidate_id], entitlement_lifecycle_enabled=True))
    old_identity = account_prefix_identity(replay(expected), PREFIX_END, [candidate_id])
    new_identity = account_prefix_identity(replay(actual), PREFIX_END, [candidate_id])
    need(old_identity == new_identity, "PAPER_EXTENSION_ORIGINAL_PREFIX_IDENTITY_CHANGED")
    return dict(status="EXACT_MATCH", table_comparisons=receipts, account_prefix_identity=old_identity)



_RIDGE_SCOPE_SEAL = object()
_RIDGE_TUPLE = "aa855dac33518f1cfc9ef9fe8cb472b2d64a80cecf82d14a88a81d83c03eff3b"
_RIDGE_REGISTRY = dict(path=str(Path("D:/us-tech-quant-results/_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/A_ALL_FROZEN_CANDIDATE_INVENTORY.json")), sha256="3a4d491fad4fcd79bad84f93257345592bd2f9a0c7077eebae9a81bee6f5f7dc")
_RIDGE_CENSUS = dict(path="D:/us-tech-quant-results/_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/A_ALL_FROZEN_STATE_DEPENDENCIES.json", sha256="84d2f4a644d1fdfae4f6954a3751be3bc156ec0141f537dbf64cdb55a0bf25a9")
_RIDGE_MODEL_SHA = dict(
 ACTION_VALUE_ENTRY_H5_2025_ridge_MID_20260928="53bf8a44748b4f1aed1dc38e1351b0031ca177ba3ba318e2545c447b04af361d",
 ACTION_VALUE_INCUMBENT_H5_2025_ridge_MID_20260928="759d194ea9ed20e1e7674f728330825a219985b739534c1faec9ae722d0523c6",
 ACTION_VALUE_ENTRY_H5_2025_SCALER="1b3da6f44c316d11f57152a9bc6e92a1d2905726f13980138492ee82f3953a71",
 ACTION_VALUE_INCUMBENT_H5_2025_SCALER="edf769bcec5f43405745e6b28232633535bf563aed96e6a0bf8abe853382b8c0")

@dataclass(frozen=True)
class RidgeOriginalSourceScope:
    """New source/account-input capability; never an old ALL admission seal."""
    task_id: str
    window_id: str
    start: object
    end: object
    as_of: object
    feature_history_start: object
    allowed_path_ids: tuple
    provenance_json: str
    research_cash_reconstruction_json: str
    research_terminal_reconstruction_json: str
    runtime_policy_ids: tuple = ()
    source_ready_policy_ids: tuple = (IDS[1],)
    capability: str = "ACCOUNT"  # Input role used by unchanged accounting-event guard math.
    seal: object = field(default=None, repr=False)


def _ridge_scope(value):
    need(type(value) is RidgeOriginalSourceScope and value.seal is _RIDGE_SCOPE_SEAL
         and value.allowed_path_ids == (IDS[1],) and value.source_ready_policy_ids == (IDS[1],),
         "PAPER_RIDGE_SINGLE_SOURCE_CAPABILITY_REQUIRED")
    need(value.task_id == "A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1" and value.window_id == "MAIN"
         and str(getattr(value.start, "date", lambda: None)()) == START
         and str(getattr(value.end, "date", lambda: None)()) == PREFIX_END and value.capability == "ACCOUNT",
         "PAPER_RIDGE_ORIGINAL_SOURCE_WINDOW_REQUIRED")
    provenance = json.loads(value.provenance_json)
    need(provenance.get("schema") == "PAPER_RIDGE_SINGLE_SOURCE_SCOPE_R1"
         and provenance.get("state_closure_scope") == "EXACT_SINGLE_RIDGE_H5_MID_FOUR_CENSUS_STATES"
         and provenance.get("legacy_all_admission") == "BLOCKED_NOT_INHERITED", "PAPER_RIDGE_SOURCE_SCOPE_CHANGED")
    return value


def _project_rows(ref, container, fields, *, selected=None, nested=None):
    """Original lexical parser: skip values before selecting identity rows."""
    from scripts.common.json_projection import _parser_type
    offsets = []
    with verified(ref).open("rb") as stream:
        q = _parser_type()(stream); q.descend((container,)); q.expect(b"["); q.white()
        while q.peek() != b"]":
            pos = q.tell(); header = q.metadata_fields({"slot_id"})
            if selected is None or header.get("slot_id") in selected: offsets.append(pos)
            q.white(); sep = q.take()
            if sep == b"]": break
            need(sep == b",", "PAPER_RIDGE_METADATA_ARRAY_CHANGED"); q.white()
    result = []
    for pos in offsets:
        with verified(ref).open("rb") as stream:
            stream.seek(pos); q = _parser_type()(stream); q.base = pos
            row=q.metadata_fields(set(fields))
        for field,names in (nested or {}).items():
            with verified(ref).open("rb") as stream:
                stream.seek(pos); q=_parser_type()(stream); q.base=pos; q.descend((field,))
                row[field]=q.metadata_fields(set(names))
        result.append(row)
    return result


def ridge_source_evidence(meta):
    """Required accepted census alternative; missing old receipts are never verified."""
    need(meta["candidate"].get("candidate_id") == IDS[1] and meta["release_ref"] == RIDGE_CONFIG,
         "PAPER_RIDGE_EXACT_CURRENT_CANDIDATE_REQUIRED")
    config = projected_metadata(meta["release_ref"], ("admission_ref", "inventory_ref", "schedule_ref"))
    need(config["inventory_ref"] == _RIDGE_REGISTRY and meta["request"] == dict(
        schema="A_2026_DESCRIPTIVE_AUTHORITY_REF_R1", task_id="A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1",
        admission_ref=config["admission_ref"], window_id="MAIN")
        and meta["release"].get("schedule_ref") == config["schedule_ref"], "PAPER_RIDGE_ORIGINAL_CONFIG_BINDING_CHANGED")
    binding = selected_rows(_RIDGE_REGISTRY, "candidates", IDS[1])
    need(binding["scientific_tuple_sha256"] == _RIDGE_TUPLE and canonical(binding["specification"]) == canonical(meta["candidate"]),
         "PAPER_RIDGE_ORIGINAL_SCIENTIFIC_TUPLE_CHANGED")
    # A second projection binds the registry's original dependency closure; not a missing-file selection.
    from scripts.common.json_projection import _parser_type
    closure = None
    with verified(_RIDGE_REGISTRY).open("rb") as stream:
        q = _parser_type()(stream); q.descend(("candidates",)); q.expect(b"["); q.white()
        while q.peek() != b"]":
            pos = q.tell(); head = q.metadata_fields({"candidate_id"})
            if head.get("candidate_id") == IDS[1]:
                with verified(_RIDGE_REGISTRY).open("rb") as other:
                    other.seek(pos); reader = _parser_type()(other); reader.base = pos
                    closure = reader.metadata_fields({"dependency_closure", "runtime_owner", "required_action_roles"})
            q.white(); sep=q.take()
            if sep == b"]": break
            need(sep == b",", "PAPER_RIDGE_REGISTRY_ARRAY_CHANGED"); q.white()
    expected = ["new_model:"+key for key in _RIDGE_MODEL_SHA if "SCALER" not in key] + ["new_scaler:"+key for key in _RIDGE_MODEL_SHA if "SCALER" in key]
    need(closure and closure.get("runtime_owner") == "FINAL_ACTION_OVERLAY"
         and closure.get("required_action_roles") == ["R10:ENTRY", "R10:INCUMBENT"]
         and closure.get("dependency_closure") == dict(status="COMPLETE", state_ids=expected, reason=None),
         "PAPER_RIDGE_DECLARED_REQUIRED4_CLOSURE_CHANGED")
    fields = {"slot_id","model_path","model_sha256","receipt_ref","status","year","family","capacity","group","horizon",
        "cutoff_exclusive","scientific_tuple","scientific_tuple_sha256","feature_order","feature_count","feature_schema_sha256",
        "scientific_tuple_projection_note","model_binary_hash_verified","receipt_hash_matches_census","identity_matches_census"}
    rows = _project_rows(_RIDGE_CENSUS, "model_states", fields, selected=set(_RIDGE_MODEL_SHA))
    rows += _project_rows(_RIDGE_CENSUS, "external_scaler_states", fields, selected=set(_RIDGE_MODEL_SHA))
    need(len(rows) == 4 and {r["slot_id"] for r in rows} == set(_RIDGE_MODEL_SHA), "PAPER_RIDGE_REQUIRED4_CENSUS_CHANGED")
    states, receipts = {}, []
    for row in rows:
        key = row["slot_id"]; scaler = "SCALER" in key; tup = row["scientific_tuple"]
        need(row.get("model_sha256") == _RIDGE_MODEL_SHA[key] and row.get("status") == "TRAINED" and row.get("year") == 2025
             and all(row.get(field) is True for field in ("model_binary_hash_verified", "receipt_hash_matches_census", "identity_matches_census")),
             "PAPER_RIDGE_ORIGINAL_FIT_CENSUS_REQUIRED")
        need(tup.get("slot_id") == key and tup.get("year") == 2025 and tup.get("family") == ("SCALER" if scaler else "ridge")
             and row.get("family") == tup["family"] and row.get("capacity") == ("SHARED" if scaler else "MID")
             and tup.get("capacity") == row["capacity"], "PAPER_RIDGE_FROZEN_ROLE_CHANGED")
        if not scaler:
            need(tup.get("horizon") == row.get("horizon") == 5 and tup.get("cutoff_exclusive") == row.get("cutoff_exclusive") == "2025-01-01",
                 "PAPER_RIDGE_ORIGINAL_PRE2025_FIT_REQUIRED")
        features=row["feature_order"]; schema=hashlib.sha256(canonical(features).encode()).hexdigest()
        need(isinstance(features,list) and len(features)==len(set(features))==row.get("feature_count")
             and schema==row.get("feature_schema_sha256")==tup.get("features_ref"), "PAPER_RIDGE_ORIGINAL_FEATURE_ORDER_CHANGED")
        restored={k:v for k,v in tup.items() if k!="features_ref"}; restored["features"]=features
        need(hashlib.sha256(canonical(restored).encode()).hexdigest()==row["scientific_tuple_sha256"],
             "PAPER_RIDGE_ORIGINAL_TUPLE_COMMITMENT_CHANGED")
        model_ref=dict(path=row["model_path"],sha256=row["model_sha256"]); verified(model_ref)
        receipt=row["receipt_ref"]; need(isinstance(receipt,dict) and set(receipt)=={"path","sha256"}
            and isinstance(receipt["sha256"],str) and len(receipt["sha256"])==64, "PAPER_RIDGE_ORIGINAL_RECEIPT_COMMITMENT_REQUIRED")
        # This capability requires the immutable accepted census and tuple proof, not unavailable receipt bytes.
        receipts.append(dict(slot_id=key, original_receipt_ref=receipt, original_receipt_bytes_present=Path(receipt["path"]).is_file(),
            original_receipt_bytes_verified=False, accepted_census_ref=_RIDGE_CENSUS,
            restored_scientific_tuple_sha256=row["scientific_tuple_sha256"], feature_schema_sha256=schema))
        states[("new_scaler:" if scaler else "new_model:")+key]=dict(model_ref=model_ref,receipt_ref=receipt)
    by={row["slot_id"]:row for row in rows}
    for role in ("ENTRY","INCUMBENT"):
        model=by[f"ACTION_VALUE_{role}_H5_2025_ridge_MID_20260928"]; scale=by[f"ACTION_VALUE_{role}_H5_2025_SCALER"]
        need(model["feature_order"]==scale["feature_order"] and all(model["scientific_tuple"][key]==scale["scientific_tuple"][key]
            for key in ("dates_sha256","design_sha256","year","features_ref","x_shape","weights_sha256")), "PAPER_RIDGE_SCALER_TRAINING_LINEAGE_CHANGED")
    return dict(candidate_id=IDS[1], scientific_tuple_sha256=_RIDGE_TUPLE, registry_ref=_RIDGE_REGISTRY,
        census_ref=_RIDGE_CENSUS, states=states, required_state_ids=expected, receipt_evidence=receipts,
        scaler_clock_basis="EXACT_SAME_DATES_SHA_AS_DECLARED_PRE2025_MODEL", legacy_all_status="BLOCKED_NOT_INHERITED",
        unused_legacy_hgb_ref=dict(path="D:/us-tech-quant-backtests/V24_A_STATEFUL_ACTION_RISK_FULL_BREADTH_R10/20261003T202647+0000_977bc52d/models/mechanism/ACTION_VALUE_ENTRY_H10_2025_hgb_MID_20260928/model.joblib",
            sha256="0feab6d28a77659491d3e528a5342f5e8ffde5561803083292646295df046b9c"), model_fit_calls=0)


def _ridge_scope_result(task, request, start, end, as_of, history, contract, bindings, ready_ids, provenance, cash, terminal, evidence):
    need(task=="A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1" and request.get("window_id")=="MAIN"
         and str(start.date())==START and str(end.date())==PREFIX_END and IDS[1] in ready_ids,
         "PAPER_RIDGE_ORIGINAL_SOURCE_WINDOW_REQUIRED")
    row=next(r for r in bindings if r["candidate_id"]==IDS[1])
    need(row["scientific_tuple_sha256"]==_RIDGE_TUPLE and row["dependency_closure"]["state_ids"]==evidence["required_state_ids"],
         "PAPER_RIDGE_SOURCE_POLICY_BINDING_CHANGED")
    provenance=dict(provenance, schema="PAPER_RIDGE_SINGLE_SOURCE_SCOPE_R1",
        original_authority_ref_schema=request["schema"], candidate_bindings=[row],
        source_ready_policy_ids=[IDS[1]], state_closure_scope="EXACT_SINGLE_RIDGE_H5_MID_FOUR_CENSUS_STATES",
        legacy_all_admission="BLOCKED_NOT_INHERITED", required_frozen_source_evidence=evidence)
    return RidgeOriginalSourceScope(task,"MAIN",start,end,as_of,history,(IDS[1],),canonical(provenance),cash,terminal,seal=_RIDGE_SCOPE_SEAL)


def _ridge_identity_document(profile, ref):
    """Retain original model-ref declarations, lexically skipping all fit-stat extras."""
    profile._safe_path(ref); verified(ref)
    if ref.get("sha256")==_RIDGE_CENSUS["sha256"]:
        keys={"slot_id","model_path","model_sha256","receipt_ref"}
        return {name:_project_rows(ref,name,keys) for name in ("model_states","external_scaler_states")}
    if ref.get("sha256")=="e8afd4d49a87eedd12958f0cb9479ad2b2df32a2abd50f6ebf2b91f4c8440a65":
        return dict(value_models=_project_rows(ref,"value_models",{"model_id","receipt_ref"},nested={"metadata":{"model_path","model_sha256"}}),
            risk_models=_project_rows(ref,"risk_models",{"risk_id","bundle_ref","receipt_ref"}))
    # All other original source/qualification objects retain the exact original reader.
    return profile._document(ref)


def _ridge_qualification_projection(profile, evidence):
    """Private guard namespace; only full-state custody and old seal construction change."""
    from types import FunctionType
    source=textwrap.dedent(inspect.getsource(profile.load_authority)); original=ast.parse(source); tree=deepcopy(original)
    fn=tree.body[0]; loops=[node for node in fn.body if isinstance(node,ast.For)
        and ast.unparse(node.iter)=="contract['state_refs'].values()"]
    need(len(loops)==1 and len(loops[0].body)==2
         and ast.unparse(loops[0].body[0])=="_physical(state['model_ref'])"
         and ast.unparse(loops[0].body[1])=="_document(state['receipt_ref'])", "PAPER_RIDGE_QUALIFICATION_CUSTODY_SEAM_CHANGED")
    loop=loops[0]; loop.iter=ast.parse("_ridge_required_states(contract)",mode="eval").body
    loop.body=ast.parse("_ridge_validate_census_leaf(state)").body
    last=fn.body[-1]
    need(isinstance(last,ast.Return) and isinstance(last.value,ast.Call)
         and ast.unparse(last.value.func)=="f.ValidatedDescriptiveAuthority", "PAPER_RIDGE_QUALIFICATION_SEAL_SEAM_CHANGED")
    replacement=ast.parse("return _ridge_build_scope(task, authority, start, end, as_of, history, contract, bindings, ready_ids, provenance, cash_binding, terminal_binding)").body[0]
    fn.body[-1]=replacement
    # Restoring the two declared qualification seams must recover every original AST node.
    restored=deepcopy(tree); idx=fn.body.index(loop); restored.body[0].body[idx]=deepcopy(original.body[0].body[idx]);restored.body[0].body[-1]=deepcopy(original.body[0].body[-1])
    need(ast.dump(restored,include_attributes=False)==ast.dump(original,include_attributes=False), "PAPER_RIDGE_OTHER_QUALIFICATION_AST_CHANGED")
    namespace=dict(profile.__dict__)
    for name,value in list(namespace.items()):
        if isinstance(value,FunctionType) and value.__module__==profile.__name__:
            copied=FunctionType(value.__code__,namespace,value.__name__,value.__defaults__,value.__closure__)
            copied.__kwdefaults__=value.__kwdefaults__;namespace[name]=copied
    def required(contract):
        need(all(contract["state_refs"].get(key)==evidence["states"][key] for key in evidence["required_state_ids"]),
             "PAPER_RIDGE_ORIGINAL_STATE_BINDING_CHANGED")
        return [contract["state_refs"][key] for key in evidence["required_state_ids"]]
    def leaf(state):
        need(state in evidence["states"].values(), "PAPER_RIDGE_UNDECLARED_LEAF")
        profile._physical(state["model_ref"])  # Original physical root and SHA gate; actual model bytes required.
    namespace.update(_document=lambda ref:_ridge_identity_document(profile,ref),
        _ridge_required_states=required,_ridge_validate_census_leaf=leaf,
        _ridge_build_scope=lambda *args:_ridge_scope_result(*args,evidence))
    exec(compile(ast.fix_missing_locations(tree),inspect.getsourcefile(profile.load_authority),"exec"),namespace)
    return namespace["load_authority"],dict(owner_ref=reference(profile.__file__),function="load_authority",
        qualification_seams=["EXACT_REQUIRED4_CENSUS_CUSTODY","NEW_SINGLE_RIDGE_SOURCE_TYPE_AND_SEAL"],
        other_qualification_ast_unchanged=True, legacy_all_guard_unchanged=True,
        original_ast_sha256=hashlib.sha256(ast.dump(original,include_attributes=False).encode()).hexdigest())


def _ridge_source_authority(meta):
    from scripts.research.a2.evaluation import frozen_a94_profile as profile
    evidence=ridge_source_evidence(meta)
    projected,receipt=_ridge_qualification_projection(profile,evidence)
    value=projected(meta["request"])
    need(canonical(json.loads(value.provenance_json)["candidate_bindings"][0]["specification"])==canonical(meta["candidate"]),
         "PAPER_RIDGE_SOURCE_POLICY_SPEC_CHANGED")
    proof=json.loads(value.provenance_json);proof["qualification_projection"]=receipt
    from dataclasses import replace
    return replace(value,provenance_json=canonical(proof))


def _ridge_policy(value,candidates):
    from scripts.research.a2.evaluation import frozen_a94_profile as profile, frozen_test_authority as common
    proxy=SimpleNamespace(**dict(common.__dict__));proxy._verified=_ridge_scope
    fn,receipt=guard_projection(profile.validate_policy,_common=lambda:proxy)
    result=fn(_ridge_scope(value),candidates)
    need(result.runtime_policy_ids==(IDS[1],), "PAPER_RIDGE_SINGLE_POLICY_REQUIRED")
    return result


def validate_account_friction(value,ids,friction):
    """Private original-profile import target for the new Ridge scope only."""
    from scripts.research.a2.evaluation import frozen_a94_profile as profile, frozen_test_authority as common
    proxy=SimpleNamespace(**dict(common.__dict__));proxy._verified=_ridge_scope
    require,_=guard_projection(profile.require_runtime_policy,_common=lambda:proxy)
    fn,_=guard_projection(profile.validate_account_friction,_common=lambda:proxy,require_runtime_policy=require)
    return fn(_ridge_scope(value),ids,friction)


def _ridge_original_dates(value,dates,*,feature_context=False):
    from scripts.research.a2.evaluation import frozen_test_authority as common
    fn,_=guard_projection(common.validate_descriptive_input_dates,_verified=_ridge_scope)
    return fn(_ridge_scope(value),dates,feature_context=feature_context)


def _ridge_original_account(value,dates,ids,account,friction):
    from scripts.research.a2.evaluation import frozen_test_authority as common
    fn,_=guard_projection(common.validate_descriptive_account,load_descriptive_authority=_ridge_scope,
        validate_descriptive_input_dates=_ridge_original_dates)
    return fn(_ridge_scope(value),dates,ids,account,friction)


def _ridge_original_accounting(value,events,*,require_exact=False):
    from scripts.research.a2.evaluation import frozen_test_authority as common
    fn,_=guard_projection(common.validate_reconstructed_accounting_events,_verified=_ridge_scope)
    return fn(_ridge_scope(value),events,require_exact=require_exact)


@dataclass(frozen=True)
class PaperAuthority:
    start: object
    end: object
    as_of: object
    allowed_path_ids: tuple
    candidate_json: str
    account_json: str
    friction_json: str
    provenance_json: str
    original_authority: object = field(repr=False)
    research_cash_reconstruction_json: str = "{}"
    research_terminal_reconstruction_json: str = "{}"
    seal: object = field(default=None, repr=False)


def _authority(value):
    need(isinstance(value, PaperAuthority) and value.seal is _SEAL, "PAPER_EXTENSION_FINITE_AUTHORITY_REQUIRED")
    return value


def bind_authority(original, *, candidates, dates, as_of, source_refs, qualification_receipt, account, friction):
    """Only the source builder can provide original quote/CA qualification proof."""
    import pandas as pd
    from scripts.research.a2.evaluation import frozen_test_authority as old
    ridge_scope = type(original) is RidgeOriginalSourceScope
    (_ridge_scope if ridge_scope else old.load_descriptive_authority)(original)
    dates = pd.DatetimeIndex(dates); clock = pd.Timestamp(as_of)
    ids = tuple(c["candidate_id"] for c in candidates)
    need(bool(ids) and len(ids) == len(set(ids)) and set(ids) <= set(IDS), "PAPER_EXTENSION_EXACT_NAMED_CANDIDATES_REQUIRED")
    need(clock.tzinfo is not None and dates.is_unique and dates.is_monotonic_increasing and dates[0] == pd.Timestamp(START)
         and pd.Timestamp(PREFIX_END) < dates[-1] < pd.Timestamp("2027-01-01"), "PAPER_EXTENSION_COMPLETED_FIXED_MAIN_REQUIRED")
    calendar_proof = qualification_receipt.get("calendar_qualification", {}) if isinstance(qualification_receipt, dict) else {}
    validate_calendar_proof(calendar_proof, clock, str(dates[-1].date()))
    need(calendar_proof["main_sessions"] == [str(d.date()) for d in dates], "PAPER_EXTENSION_SOURCE_CALENDAR_CHANGED")
    need(original.start == pd.Timestamp(START) and original.end == pd.Timestamp(PREFIX_END), "PAPER_EXTENSION_ORIGINAL_WINDOW_REQUIRED")
    if ridge_scope:
        original = _ridge_policy(original, tuple(candidates))
        _ridge_original_account(original, dates[dates <= pd.Timestamp(PREFIX_END)], ids, account, friction)
    else:
        original = old.validate_descriptive_policy(original, tuple(candidates))
        old.validate_descriptive_account(original, dates[dates <= pd.Timestamp(PREFIX_END)], ids, account, friction)
    need(isinstance(qualification_receipt, dict) and qualification_receipt.get("seal") is _SEAL
         and qualification_receipt.get("dates") == [str(d.date()) for d in dates]
         and qualification_receipt.get("as_of") == clock.isoformat()
         and qualification_receipt.get("refs") == source_refs, "PAPER_EXTENSION_ACTUAL_SOURCE_QUALIFICATION_REQUIRED")
    for ref in source_refs.values():
        verified(ref)
    provenance = dict(schema=SCHEMA, task_id=TASK, window_id="MAIN", start=START, end=str(dates[-1].date()), as_of=clock.isoformat(),
                      source_refs=source_refs, original_authority_provenance=json.loads(original.provenance_json),
                      calendar_qualification=calendar_proof,
                      model_fit_calls=0, selection_using_2026=False, historical_strict_pit_claim=False,
                      execution_admission_inherited=False, independent_holdout_claim=False, broker_action_allowed=False)
    return PaperAuthority(dates[0], dates[-1], clock, ids, canonical(candidates), canonical(account), canonical(friction),
                          canonical(provenance), original, original.research_cash_reconstruction_json,
                          original.research_terminal_reconstruction_json, _SEAL)


def validate_descriptive_input_dates(authority, dates, *, feature_context=False):
    import pandas as pd
    value = _authority(authority); dates = pd.DatetimeIndex(pd.to_datetime(dates))
    first = pd.Timestamp("2023-01-03") if feature_context else value.start
    need(len(dates) > 0 and dates.tz is None and not dates.hasnans and dates.equals(dates.normalize())
         and dates.min() >= first and dates.max() <= value.end, "PAPER_EXTENSION_INPUT_OUTSIDE_BOUND")
    return value


def require_descriptive_decision(authority, date, path_id=None, **kwargs):
    value = validate_descriptive_input_dates(authority, [date])
    need(path_id is None or path_id in value.allowed_path_ids, "PAPER_EXTENSION_POLICY_ID_CHANGED")
    return value


def validate_descriptive_account(authority, dates, path_ids, account_config, execution_friction):
    import pandas as pd
    value = validate_descriptive_input_dates(authority, dates); dates = pd.DatetimeIndex(dates)
    need(dates.is_unique and dates.is_monotonic_increasing and dates[0] == value.start and dates[-1] == value.end
         and tuple(path_ids) == value.allowed_path_ids and canonical(account_config) == value.account_json
         and canonical(execution_friction) == value.friction_json, "PAPER_EXTENSION_ACCOUNT_IDENTITY_CHANGED")
    return value


def validate_reconstructed_accounting_events(authority, events, *, require_exact=False):
    from scripts.research.a2.evaluation.frozen_test_authority import validate_reconstructed_accounting_events as original
    value = _authority(authority)
    # This extension cannot invent a new post-verified cash/terminal convention.
    if type(value.original_authority) is RidgeOriginalSourceScope:
        return _ridge_original_accounting(value.original_authority, events, require_exact=require_exact)
    return original(value.original_authority, events, require_exact=require_exact)


def guard_projection(function, **bindings):
    """Change only named internal guard imports; record original algorithm AST."""
    source = textwrap.dedent(inspect.getsource(function)); tree = ast.parse(source)
    allowed = {"require_descriptive_decision", "validate_descriptive_account", "validate_reconstructed_accounting_events", "validate_descriptive_input_dates"}
    imports = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.ImportFrom) and node.module == "scripts.research.a2.evaluation.frozen_a94_profile"
                and set(alias.name for alias in node.names)=={"validate_account_friction"}):
            node.module=__name__;imports+=1
        if isinstance(node, ast.ImportFrom) and node.module == "scripts.research.a2.evaluation.frozen_test_authority":
            need(set(alias.name for alias in node.names) <= allowed, "PAPER_EXTENSION_UNREGISTERED_GUARD_IMPORT")
            node.module = __name__; imports += 1
    original = ast.parse(source)
    def normalized(value):
        value = deepcopy(value)
        for node in ast.walk(value):
            if isinstance(node, ast.ImportFrom) and node.module in (__name__, "scripts.research.a2.evaluation.frozen_test_authority", "scripts.research.a2.evaluation.frozen_a94_profile"):
                node.module = "FINITE_DESCRIPTIVE_GUARD_BINDING"
        return ast.dump(value, include_attributes=False)
    need(normalized(tree) == normalized(original), "PAPER_EXTENSION_ALGORITHM_AST_CHANGED")
    namespace = dict(function.__globals__); namespace.update(bindings)
    exec(compile(ast.fix_missing_locations(tree), inspect.getsourcefile(function), "exec"), namespace)
    projected = namespace[function.__name__]
    receipt = dict(owner_ref=reference(inspect.getsourcefile(function)), function=function.__qualname__, guard_imports_rebound=imports, namespace_guard_dependency_bindings=sorted(bindings),
                   algorithm_ast_sha256=hashlib.sha256(normalized(original).encode()).hexdigest(), algorithm_ast_unchanged=True)
    return projected, receipt


def replay_projection():
    """Private guard-bound view of the same policy and continuous account math."""
    from scripts.research.a2.training import stateful_replay as replay, stateful_account as policy, stateful_final_action as action
    # The original accepted numerical/R7 closure requires this exact recovered
    # CBC algorithm. Latest canonical source bytes cannot replace its owner pin.
    cbc_ref = dict(path="D:/us-tech-quant-worktrees/a-repair-ca-source-20261011-r1/scripts/research/a2/evaluation/continuous_research_account.py",
                   sha256="4dd3b001485afab6bff4bb618391814f34063f7e262fb9a51a9864103fef9253")
    continuous = load_original_owner(cbc_ref, "_finite_paper_original_cbc")
    receipts = []
    state_call, receipt = guard_projection(policy.StatefulOverlay.__call__); receipts.append(receipt)
    state_cls = type("PaperStatefulOverlay", (policy.StatefulOverlay,), {"__call__": state_call})
    action_init, receipt = guard_projection(action.FinalActionOverlay.__init__, StatefulOverlay=state_cls); receipts.append(receipt)
    action_call, receipt = guard_projection(action.FinalActionOverlay.__call__); receipts.append(receipt)
    action_cls = type("PaperFinalActionOverlay", (action.FinalActionOverlay,), {"__init__": action_init, "__call__": action_call})
    lifecycle, receipt = guard_projection(continuous.apply_entitlement_lifecycle); receipts.append(receipt)
    account_fn, receipt = guard_projection(continuous.run_continuous_account, apply_entitlement_lifecycle=lifecycle); receipts.append(receipt)
    execute_fn, receipt = guard_projection(replay.execute_market, run_continuous_account=account_fn, StatefulOverlay=state_cls); receipts.append(receipt)
    return dict(execute_market=execute_fn, StatefulOverlay=state_cls, FinalActionOverlay=action_cls), receipts


def publish_verified(paths, *, candidate_id, frames, baseline_refs, authority, source_refs, projection_receipts):
    from scripts.common.storage_paths import assert_safe_output_path
    value = _authority(authority)
    need(candidate_id in value.allowed_path_ids and source_refs == json.loads(value.provenance_json)["source_refs"], "PAPER_EXTENSION_PUBLICATION_CUSTODY_CHANGED")
    need(baseline_refs == accepted_baseline_refs(candidate_id), "PAPER_EXTENSION_ACCEPTED_BASELINE_PINS_REQUIRED")
    provenance = json.loads(value.provenance_json)
    calendar_proof = provenance.get("calendar_qualification", {})
    validate_calendar_proof(calendar_proof, value.as_of, str(value.end.date()))
    prefix = compare_prefix(frames, baseline_refs, candidate_id)
    stock_prefix = compare_stock_prefix(frames, baseline_refs, candidate_id,
        next_execution_date=calendar_proof["tail_sessions"][0])
    import pandas as pd
    daily = _ordered(frames["daily"], "daily", candidate_id, str(value.end.date()))
    need(len(daily) > 0 and pd.Timestamp(daily.date.iloc[0]) == value.start and pd.Timestamp(daily.date.iloc[-1]) == value.end,
         "PAPER_EXTENSION_FULL_MAIN_CURVE_REQUIRED")
    need(pd.to_datetime(daily.date).dt.strftime("%Y-%m-%d").tolist() == calendar_proof["main_sessions"],
         "PAPER_EXTENSION_FULL_COMPLETED_CALENDAR_REQUIRED")
    for ref in source_refs.values():
        verified(ref)
    identity = hashlib.sha256(canonical(dict(candidate=candidate_id, authority=json.loads(value.provenance_json), prefix=prefix)).encode()).hexdigest()[:20]
    output = paths.backtest_root / TASK / "descriptive_main_extension" / str(value.end.date()) / candidate_id / identity
    assert_safe_output_path(output, kind="backtest", paths=paths); output.mkdir(parents=True, exist_ok=True)
    refs = {}
    for name in LEDGER_TABLES:
        frame = _ordered(frames[name], name, candidate_id, str(value.end.date()))
        destination = output / (name + ".parquet")
        if destination.exists():
            try:
                pd.testing.assert_frame_equal(pd.read_parquet(destination), frame, check_exact=True)
            except AssertionError as exc:
                raise ValueError("PAPER_EXTENSION_PRESERVE_ACCEPTED_OUTPUT") from exc
        else:
            frame.to_parquet(destination, index=False, compression="zstd")
        refs[name] = reference(destination)
        del frame
    receipt = dict(schema=SCHEMA, task_id=TASK, status="PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION", candidate_id=candidate_id,
                   candidate_ids=[candidate_id], window_id="MAIN", start=START, first_execution_date=FIRST_EXECUTION, prefix_end=PREFIX_END,
                   end=str(value.end.date()), as_of=value.as_of.isoformat(), calendar_qualification=calendar_proof,
                   artifacts=refs, baseline_artifacts=baseline_refs, baseline_completion_ref=ACCEPTED_MAIN[candidate_id],
                   original_prefix_comparison=prefix, stock_prefix_comparison=stock_prefix, source_refs=source_refs, runtime_projection_receipts=projection_receipts,
                   model_fit_calls=0, selection_using_2026=False, independent_holdout_claim=False, historical_strict_pit_claim=False,
                   production_qualified=False, broker_action_allowed=False)
    destination = output / "EXTENSION_COMPLETION.json"
    body = canonical(receipt) + "\n"
    if destination.exists():
        need(destination.read_text(encoding="utf8") == body, "PAPER_EXTENSION_PRESERVE_ACCEPTED_RECEIPT")
    else:
        destination.write_text(body, encoding="utf8")
    report = paths.results_root / "_maintenance" / TASK / "new_strategy_main_extension" / candidate_id / (identity + ".json")
    assert_safe_output_path(report, kind="results", paths=paths); report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        need(report.read_text(encoding="utf8") == body, "PAPER_EXTENSION_PRESERVE_ACCEPTED_REPORT")
    else:
        report.write_text(body, encoding="utf8")
    gc.collect()
    return receipt, reference(destination)


def full_r10_roles(prefix, calendar, end):
    """Original proxy/ALL-pair/structured kernels over a fixed input-only window."""
    import pandas as pd
    from scripts.research.a2.inference.frozen_a94_state import _clone
    from scripts.research.a2.training import stateful_mechanism_inputs as inputs, stateful_mechanism as mechanism
    from scripts.research.a2.data import state_label_foundation as foundation
    from scripts.research.a2.inference.frozen_a94_actions import role_features
    from scripts.research.a2.inference.consensus_paper import FORBIDDEN, scoped_proxy_frame
    end = pd.Timestamp(end); calendar = pd.DatetimeIndex(calendar)
    need(calendar[0] == pd.Timestamp("2023-01-03") and calendar[-1] == end and calendar.is_unique
         and calendar.is_monotonic_increasing and set(pd.to_datetime(prefix.signal_date)) == set(calendar), "PAPER_EXTENSION_ORIGINAL_COHORT_CALENDAR")
    need(not set(prefix) & FORBIDDEN, "PAPER_EXTENSION_OUTCOME_FEATURE_FORBIDDEN")
    def dates(values, nullable=False):
        result = pd.to_datetime(values)
        need((nullable or not pd.isna(result).any()) and (not len(result) or pd.DatetimeIndex(result).dropna().max() <= end), "PAPER_EXTENSION_FUTURE_INPUT")
        return result
    fn = _clone(inputs.proxy_state, _pre2026=dates, _calendar=lambda x:pd.DatetimeIndex(dates(x)))
    proxy = scoped_proxy_frame(fn, prefix, calendar, START, end, 10)
    current = proxy.loc[pd.to_datetime(proxy.signal_date).between(START, end)].copy()
    del proxy
    keys = ["signal_date", "ticker", "security_id", "cohort_age_sessions", "raw_rank"]
    pairs = foundation.all_incumbent_pairs({"buy":current.loc[current.entrant.eq(1),keys], "hold":current.loc[current.entrant.eq(0),keys]})
    labels = current.iloc[:0][["signal_date","ticker","security_id"]].copy().assign(label_value=pd.Series(dtype=float),
        label_qualified=pd.Series(dtype=bool),label_mature_date=pd.Series(dtype="datetime64[ns]"),source_label_identity=pd.Series(dtype=str))
    heads = {name:inputs.attach_single_labels(current,labels,name) for name in ("ENTRY","INCUMBENT","CONTINUATION")}
    heads["REPLACE"] = inputs.attach_pair_labels(pairs,current,labels)
    roles = mechanism.structured_action_frame(SimpleNamespace(heads={5:heads}),5)
    del heads, pairs, current
    identities = ("signal_date","sample_id","ticker","security_id","cohort_age_sessions","action_type","entrant_ticker","entrant_sid")
    return {name:roles[name][list(dict.fromkeys([key for key in identities if key in roles[name]]+list(role_features("R10:"+name))))].copy() for name in ("ENTRY","INCUMBENT")}


def forward_r10(paths, candidate_id, roles, authority):
    """One original frozen head/scaler at a time, then original packet decoding."""
    import joblib
    import numpy as np
    import pandas as pd
    import weakref
    from threadpoolctl import threadpool_limits
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.research.a2.inference.frozen_a94_actions import role_features
    from scripts.research.a2.training import stateful_mechanism as mechanism, stateful_final_action_packets as packets
    value = _authority(authority)
    need(candidate_id in IDS[:2] and candidate_id in value.allowed_path_ids, "PAPER_EXTENSION_R10_IDENTITY")
    states = consumer.frozen_states(paths,candidate_id); outputs, refs = {}, {}
    for group in ("ENTRY","INCUMBENT"):
        check_resources("R10_BEFORE_FROZEN_HEAD", candidate_id=candidate_id, group=group); frame = roles[group]
        if not frame.empty:
            validate_descriptive_input_dates(value,frame.signal_date)
        need(not set(frame) & consumer.FORBIDDEN, "PAPER_EXTENSION_OUTCOME_FEATURE_FORBIDDEN")
        members = [(key,state) for key,state in states.items() if state.get("metadata_row",{}).get("group")==group and state.get("state_type","new_model")=="new_model"]
        if candidate_id == IDS[1]:
            members = [(key,state) for key,state in states.items() if key.startswith("ACTION_VALUE_"+group+"_H5") and state["metadata_row"]["family"]=="ridge"]
        scales = [state for key,state in states.items() if "SCALER" in key and "ACTION_VALUE_"+group+"_" in key]
        need(len(members)==1 and len(scales)==1, "PAPER_EXTENSION_FROZEN_HEAD_CLOSURE")
        key,state=members[0]; model=joblib.load(consumer.verify(state["model_ref"])); scaler=joblib.load(consumer.verify(scales[0]["model_ref"]))
        lifetime, scale_lifetime = weakref.ref(model), weakref.ref(scaler)
        x,names = consumer.r10_encoded_input(frame,role_features("R10:"+group))
        need(tuple(names)==tuple(state["metadata_row"]["feature_order"]), "PAPER_EXTENSION_FROZEN_FEATURE_ORDER")
        predictions = {}
        if len(x):
            x=consumer.r10_scaled_input(scaler,x)
            with threadpool_limits(limits=1):
                predictions=consumer.predict_r10(model,x)
        refs[key]=state["model_ref"]; refs[group+"_SCALER"]=scales[0]["model_ref"]
        del model,scaler,x;gc.collect()
        need(lifetime() is None and scale_lifetime() is None, "PAPER_EXTENSION_HEAD_MODEL_RELEASE_REQUIRED")
        for start in range(0, len(frame), 4096):
            for index,row in enumerate(frame.iloc[start:start + 4096].to_dict("records"), start):
                date=pd.Timestamp(row["signal_date"]); day=outputs.setdefault(date,[])
                native={name:float(output[index]) for name,output in predictions.items() if isinstance(output,np.ndarray) and output.shape==(len(frame),)}
                day.append(packets.decode_r10_row(consumer.r10_decoder_input(row, native, group=group),len(day),group=group))
        del predictions, frame
    return {candidate_id:outputs},refs


_R7_NATIVE_TRACE_OWNER = dict(path="D:/us-tech-quant-cache/_maintenance/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/remaining10/R7/r7_gross_account_adapter.py",sha256="3df38039028f6a2ccdeeee3e16460e4b110a67a981081bdbc1a5827cdeda5d23")
_R7_ACTION_FORMAT_OWNER = dict(path="D:/us-tech-quant-cache/_maintenance/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/remaining10/R7/r7_prepared_windows.py",sha256="bb7b907b42615cc638aaf726465f8b00a027f6261163c9ef1e50c3e7885bde6c")


def _r7_native_prediction_trace(frame, output, model_ref):
    """Exact pure table segment of original native_grid, using its one existing prediction."""
    import numpy as np
    verified(_R7_NATIVE_TRACE_OWNER)
    cid=IDS[2];contract={"model_refs":{cid:model_ref}}
    action=np.asarray(output["action"]);gross=np.asarray(output["gross"]);probability=np.asarray(output["probabilities"])
    need(action.dtype==np.dtype("int64") and gross.dtype==np.dtype("float64") and probability.shape==(len(frame),5)
         and action.shape==gross.shape==(len(frame),) and np.isfinite(probability).all()
         and np.array_equal(gross,action/4.) and np.array_equal(action,probability.argmax(axis=1)),
         "PAPER_R7_ORIGINAL_NATIVE_OUTPUT_REQUIRED")
    table=frame[['signal_date','gross_previous_proxy']].copy()
    table['candidate_id']=cid
    table['action']=output['action']
    table['requested_gross']=output['gross']
    for k in range(5):table['probability_'+str(k)]=output['probabilities'][:,k]
    table['model_sha256']=contract['model_refs'][cid]['sha256']
    table['decoder']='ORIGINAL_ARGMAX_FIRST_TIE_CLASS_DIVIDED_BY4'
    return table


def _r7_original_action_frames(frames, native_trace, path_ids, model_refs):
    """Only the original persist_r7_window pure joins; no writer, metrics or extra models."""
    import numpy as np
    import pandas as pd
    need(tuple(path_ids)==(IDS[2],) and isinstance(native_trace,dict) and set(native_trace)=={IDS[2]},
         "PAPER_R7_SINGLE_NATIVE_ACTION_TRACE_REQUIRED")
    verified(_R7_NATIVE_TRACE_OWNER);verified(_R7_ACTION_FORMAT_OWNER)
    bound=native_trace[IDS[2]]
    need(isinstance(bound,dict) and set(bound)=={"frame","model_ref"} and isinstance(model_refs,dict) and set(model_refs)=={IDS[2]}
         and bound["model_ref"]==model_refs[IDS[2]],"PAPER_R7_NATIVE_ACTION_MODEL_REF_CHANGED")
    trace=bound["frame"]
    need(isinstance(model_refs[IDS[2]],dict) and set(model_refs[IDS[2]])=={"path","sha256"}
         and isinstance(model_refs[IDS[2]]["sha256"],str) and len(model_refs[IDS[2]]["sha256"])==64
         and trace.model_sha256.eq(model_refs[IDS[2]]["sha256"]).all(),"PAPER_R7_NATIVE_ACTION_MODEL_SHA_CHANGED")
    columns=["signal_date","gross_previous_proxy","candidate_id","action","requested_gross"]+["probability_"+str(k) for k in range(5)]+["model_sha256","decoder"]
    need(list(trace.columns)==columns and not trace.empty and trace.candidate_id.eq(IDS[2]).all()
         and not trace.duplicated(["signal_date","gross_previous_proxy"]).any(),"PAPER_R7_COMPLETE_NATIVE_ACTION_TRACE_REQUIRED")
    action=trace.action.to_numpy();probability=trace[["probability_"+str(k) for k in range(5)]].to_numpy()
    need(action.dtype==np.dtype("int64") and trace.requested_gross.dtype==np.dtype("float64")
         and trace.gross_previous_proxy.dtype==np.dtype("float64") and np.isfinite(probability).all()
         and np.array_equal(trace.requested_gross.to_numpy(),action/4.) and np.array_equal(action,probability.argmax(axis=1))
         and trace.decoder.eq("ORIGINAL_ARGMAX_FIRST_TIE_CLASS_DIVIDED_BY4").all(),"PAPER_R7_NATIVE_ACTION_DECODER_CHANGED")
    need(all(set(day.gross_previous_proxy)=={0.,.25,.5,.75,1.} for _,day in trace.groupby("signal_date")),"PAPER_R7_FULL_NATIVE_ACTION_GRID_REQUIRED")
    def project(frames,shared,IDS):
        audit=frames['gross']
        need(len(audit)>0 and not audit.duplicated(['candidate_id','signal_date']).any(),'R7_MODEL_TO_ACCOUNT_DECISION_TRACE')
        merged=[]
        for cid in IDS:
            g=audit.loc[audit.candidate_id.eq(cid)].copy();g['signal_date']=pd.to_datetime(g.signal_date);g=g.rename(columns={'previous_requested_grid':'gross_previous_proxy'})
            t=shared['predictions'][cid].drop(columns=['requested_gross','candidate_id'])
            m=g.merge(t,on=['signal_date','gross_previous_proxy'],how='left',validate='one_to_one')
            need(m.action.notna().all() and np.array_equal(m.requested_grid.to_numpy(),m.action.to_numpy()/4.),'R7_ACTUAL_MODEL_OUTPUT_EQUALS_ACCOUNT_REQUEST')
            merged.append(m)
        frames['gross']=pd.concat(merged,ignore_index=True)
        actions=frames['actions']
        need(not actions.empty,'R7_ACTUAL_RULE_TO_ORDERS_TRACE')
        targets=frames['gross'][['candidate_id','signal_date','gross_previous_proxy','requested_grid','action']].rename(columns={'candidate_id':'path_id','action':'r7_model_action'})
        targets['signal_date']=pd.to_datetime(targets.signal_date)
        frames['actions']=actions.merge(targets,on=['path_id','signal_date'],how='left',validate='many_to_one')
        need(frames['actions'].requested_grid.notna().all(),'R7_EVERY_ACCOUNT_TARGET_NATIVE_REQUEST_LINKED')
        return frames
    projected=project(dict(frames),{"predictions":{IDS[2]:trace}},tuple(path_ids))
    need(projected["actions"].r7_model_action.dtype==np.dtype("int64")
         and projected["actions"].gross_previous_proxy.dtype==np.dtype("float64")
         and projected["actions"].requested_grid.dtype==np.dtype("float64"),"PAPER_R7_ORIGINAL_ACTION_FORMAT_DTYPES_REQUIRED")
    receipt=dict(kind="ORIGINAL_R7_NATIVE_ACTION_FORMAT",native_owner_ref=dict(_R7_NATIVE_TRACE_OWNER),format_owner_ref=dict(_R7_ACTION_FORMAT_OWNER),
        native_function="native_grid",native_table_AST_sha256="f26482e666e68a00d1da43052c66cb5fe7f6ab7118a3a54307b142c3e0fad4e4",format_function="persist_r7_window",format_block_AST_sha256="d6e538929592fbafbbd613625b0aa2c8e10e6d8f20b75056c86c507cca0a967f",
        model_prediction_calls_added=0,account_math_changed=False,model_refs=deepcopy(model_refs))
    return projected,receipt


def forward_r7(paths, flags, dates, authority, *, include_native_trace=False):
    """Original five-counterstate grid; main state later follows requests from G=1."""
    import joblib
    import numpy as np
    import pandas as pd
    import weakref
    from threadpoolctl import threadpool_limits
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.research.a2.inference.frozen_a94_state import _clone, _DateInputs
    from scripts.research.a2.training import stateful_decision as decision, stateful_decision_models as models
    value=_authority(authority); validate_descriptive_input_dates(value,dates)
    need(IDS[2] in value.allowed_path_ids and not set(flags)&consumer.FORBIDDEN, "PAPER_EXTENSION_R7_IDENTITY_OR_OUTCOME")
    builder=_clone(decision.build_samples,inputs=_DateInputs(value.end+pd.Timedelta(days=1)))
    scoped_flags=flags.loc[pd.to_datetime(flags.signal_date).isin(pd.DatetimeIndex(dates))].copy()
    samples,_=builder(scoped_flags,pd.DataFrame(columns=decision.LABEL_COLS),pd.DatetimeIndex(dates)); frame=samples["gross"]
    state=next(iter(consumer.frozen_states(paths,IDS[2]).values()))
    check_resources("R7_AFTER_SAMPLE_GRID_BEFORE_FROZEN_MODEL", candidate_id=IDS[2]);model=joblib.load(consumer.verify(state["model_ref"]));lifetime=weakref.ref(model)
    x,names=decision.encode_features(frame,decision.GROSS)
    need(tuple(names)==tuple(model.features) and model.objective=="gross" and model.learner=="linear", "PAPER_EXTENSION_R7_FROZEN_MODEL")
    with threadpool_limits(limits=1):
        predictions=models.predict(model,x)
    grid={}
    for row,requested in zip(frame.itertuples(),predictions["gross"]):
        grid.setdefault(pd.Timestamp(row.signal_date),{})[float(row.gross_previous_proxy)]=float(requested)
    need(set(grid)==set(pd.DatetimeIndex(dates)) and all(set(day)==set(decision.G) and set(day.values())<=set(decision.G) for day in grid.values()), "PAPER_EXTENSION_R7_FULL_GRID_REQUIRED")
    del model,x;gc.collect();need(lifetime() is None,"PAPER_EXTENSION_R7_MODEL_RELEASE_REQUIRED")
    result=({IDS[2]:grid},{IDS[2]:state["model_ref"]})
    if include_native_trace:
        return *result,{IDS[2]:dict(frame=_r7_native_prediction_trace(frame,predictions,state["model_ref"]),model_ref=deepcopy(state["model_ref"]))}
    return result


def load_original_owner(ref, name):
    import importlib.util
    import sys
    path=verified(ref); spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def _original_nav_output_frames(result, frames, path_ids):
    """Preserve Ridge's accepted raw entitlement label after the sole NAV projection."""
    import pandas as pd
    from scripts.research.a2.evaluation.stateful_frozen_six_path import _dual_nav_frames
    projected=_dual_nav_frames(result,frames)
    if tuple(path_ids)==(IDS[1],):
        raw,view=frames["entitlements"],projected["entitlements"]
        need(raw.columns.is_unique and view.columns.is_unique and "scenario" in raw and "scenario" not in view
             and set(raw.columns)==set(view.columns)|{"scenario"},"PAPER_RIDGE_ENTITLEMENT_FORMAT_ONLY_SCENARIO_REQUIRED")
        pd.testing.assert_frame_equal(raw.drop(columns=["scenario"]),view,check_exact=True,check_dtype=True,
            check_index_type=True,check_column_type=True)
        projected["entitlements"]=raw.copy()
    return projected


def execute_prepared(prepared, authority, *, action_packets=None, gross_calendar=None, native_trace=None, native_model_refs=None):
    """Use the sole original account math, with a new finite scope guard only."""
    from scripts.research.a2.training.stateful_final_action_packets import decode_resource_proposals
    value=_authority(authority); candidates=prepared["candidates"]
    need(canonical(candidates)==value.candidate_json and canonical(prepared["account"])==value.account_json
         and canonical(prepared["execution_friction"])==value.friction_json, "PAPER_EXTENSION_PREPARED_ECONOMICS_CHANGED")
    validate_descriptive_account(value,prepared["market"].dates,value.allowed_path_ids,prepared["account"],prepared["execution_friction"])
    methods,receipts=replay_projection()
    need((native_trace is None)==(native_model_refs is None) and (native_trace is None or value.allowed_path_ids==(IDS[2],)),"PAPER_R7_NATIVE_TRACE_CANNOT_ALTER_OTHER_CANDIDATES")
    if set(value.allowed_path_ids)<=set(IDS[:2]):
        need(isinstance(action_packets,dict) and set(action_packets)==set(value.allowed_path_ids) and gross_calendar is None, "PAPER_EXTENSION_COMPLETE_R10_ACTIONS_REQUIRED")
        def factory(actual,*args,**kwargs):
            return methods["FinalActionOverlay"](actual,*args,**kwargs,action_packets=action_packets,
                resource_decoder=decode_resource_proposals,sid_by_key=prepared["sid_by_key"])
    else:
        need(value.allowed_path_ids==(IDS[2],) and action_packets is None and set(gross_calendar or {})=={IDS[2]}, "PAPER_EXTENSION_R7_ONLY_ORIGINAL_GRID")
        driver_ref={"path":"D:/us-tech-quant-cache/_maintenance/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/remaining10/R7/r7_gross_account_adapter.py","sha256":"3df38039028f6a2ccdeeee3e16460e4b110a67a981081bdbc1a5827cdeda5d23"}
        driver=load_original_owner(driver_ref,"_finite_paper_r7_original")
        init,receipt=guard_projection(driver.R7GrossOverlay.__init__,IDS=(IDS[2],));receipts.append(receipt)
        call,receipt=guard_projection(driver.R7GrossOverlay.__call__,IDS=(IDS[2],));receipts.append(receipt)
        overlay=type("PaperR7GrossOverlay",(driver.R7GrossOverlay,),{"__init__":init,"__call__":call})
        def factory(actual,*args,**kwargs):
            return overlay(actual,*args,**kwargs,gross_calendar=gross_calendar,reference_factory=methods["StatefulOverlay"])
    source=prepared["account_source_kwargs"]
    need(source.get("entitlement_enabled") is True and isinstance(source.get("entitlement_source_binding"),dict), "PAPER_EXTENSION_ORIGINAL_CA_BINDING_REQUIRED")
    result,frames=methods["execute_market"](prepared["market"],tuple(candidates),prepared["packets"],prepared["top"],prepared["qualified"],prepared["vol"],deepcopy(prepared["account"]),
        stock_present=prepared["stock_present"],raw_selector_present=prepared["raw_selector_present"],policy_factory=factory,
        execution_friction=deepcopy(prepared["execution_friction"]),descriptive_evaluation_authority=value,**source)
    projected=_original_nav_output_frames(result,frames,value.allowed_path_ids)
    if native_trace is not None:
        projected,receipt=_r7_original_action_frames(projected,native_trace,value.allowed_path_ids,native_model_refs);receipts.append(receipt)
    return result,projected,receipts


def capture_raw_proofs(capture_ref, wanted):
    """Select ticker metadata before decoding its input-reference fields."""
    from scripts.common.json_projection import _parser_type
    path=verified(capture_ref); wanted=set(wanted); result={}
    for branch in ("accepted_closed_vintage_continuation","qualified_existing_raw_candidate_tails"):
        offsets=[]
        with path.open("rb") as stream:
            reader=_parser_type()(stream)
            try:
                reader.descend(("capture_reuse",branch,"ticker_proofs"))
            except ValueError:
                continue
            reader.expect(b"[");reader.white();count=0
            while reader.peek()!=b"]":
                reader.white();start=reader.tell();row=reader.metadata_fields({"ticker"});count+=1
                need(count<=2500,"PAPER_EXTENSION_SOURCE_PROOF_COUNT_BOUND")
                if row.get("ticker") in wanted:
                    offsets.append((row["ticker"],start))
                reader.white();separator=reader.take()
                if separator==b"]":break
                need(separator==b",","PAPER_EXTENSION_SOURCE_PROOF_ARRAY")
        for ticker,start in offsets:
            with path.open("rb") as stream:
                stream.seek(start);reader=_parser_type()(stream);reader.base=start
                row=reader.metadata_fields({"ticker","code","security_id","incoming_raw_sources","incoming_rehab","past_factor_stream_exact"})
            need(row.get("past_factor_stream_exact") is True,"PAPER_EXTENSION_CURRENT_FACTOR_VINTAGE_UNBOUND:"+ticker)
            current=[ref for ref in row.get("incoming_raw_sources",[]) if ref.get("role")=="CURRENT_RAW"]
            need(len(current)==1,"PAPER_EXTENSION_CURRENT_RAW_LEAF_UNBOUND:"+ticker)
            clean={"path":current[0]["path"],"sha256":current[0]["sha256"]};verified(clean)
            if ticker in result:
                need(result[ticker]["raw_ref"]==clean,"PAPER_EXTENSION_AMBIGUOUS_CURRENT_RAW_LEAF:"+ticker)
            result[ticker]=dict(ticker=ticker,code=row["code"],security_id=row.get("security_id"),raw_ref=clean,
                                capture_ref=capture_ref,qualification_branch=branch,past_factor_stream_exact=True)
    return result


def raw_csv_tail(ref, ticker, code, dates, as_of):
    """Date-only pass, then parse numeric fields from exactly authorized CSV rows."""
    import csv
    import numpy as np
    import pandas as pd
    path=verified(ref);clock=pd.Timestamp(as_of);days={str(pd.Timestamp(day).date()) for day in dates}
    with path.open(encoding="utf-8-sig",newline="") as stream:
        columns=next(csv.reader(stream))
    required={"date","ticker","moomoo_symbol","open","close","adjustment","source","source_policy","fetched_at_utc"}
    need(required<=set(columns),"PAPER_EXTENSION_NATIVE_RAW_CSV_SCHEMA")
    first=pd.read_csv(path,usecols=["date"],dtype=str)
    need(len(first)<=250000,"PAPER_EXTENSION_RAW_LEAF_ROW_LIMIT")
    keep={index+1 for index,day in enumerate(first.date) if str(day)[:10] in days}
    frame=pd.read_csv(path,usecols=sorted(required),skiprows=lambda index:index>0 and index not in keep)
    need(not frame.empty and frame.ticker.eq(ticker).all() and frame.moomoo_symbol.eq(code).all()
         and frame.adjustment.eq("raw").all() and frame.source.eq("MOOMOO_OPEND").all()
         and frame.source_policy.eq("MOOMOO_ONLY").all(),"PAPER_EXTENSION_NATIVE_RAW_SOURCE_IDENTITY")
    frame["trade_date"]=pd.to_datetime(frame.date).dt.normalize();available=pd.to_datetime(frame.fetched_at_utc,utc=True)
    need(not available.isna().any() and available.le(clock).all() and not frame.trade_date.duplicated().any()
         and set(frame.trade_date)<=set(pd.DatetimeIndex(dates)) and np.isfinite(frame[["open","close"]].to_numpy(float)).all()
         and frame[["open","close"]].gt(0).all().all(),"PAPER_EXTENSION_CURRENT_RAW_QUOTES_OR_CLOCK")
    # Missing rows stay missing and remain visible to the original account.
    return frame[["ticker","trade_date","open","close"]].copy(),dict(raw_ref=ref,ticker=ticker,code=code,
        observed_at_min=available.min().isoformat(),observed_at_max=available.max().isoformat(),
        qualified_dates=[str(day.date()) for day in frame.trade_date],missing_dates=sorted(days-{str(day.date()) for day in frame.trade_date}),
        price_basis="RAW_PROVIDER_SHARE_COORDINATE",historical_publication_time_certified=False)


def selected_source_rows(ref, wanted, fields, *, branch=(), identity="ticker"):
    """Select array identities first; decode only the requested source records."""
    from scripts.common.json_projection import _parser_type
    path = verified(ref); starts = []; wanted = set(wanted)
    with path.open("rb") as stream:
        reader = _parser_type()(stream)
        if branch: reader.descend(branch)
        reader.expect(b"["); reader.white(); count = 0
        while reader.peek() != b"]":
            reader.white(); start = reader.tell(); row = reader.metadata_fields({identity}); count += 1
            need(count <= 2500, "PAPER_EXTENSION_SOURCE_RECORD_COUNT_BOUND")
            if row.get(identity) in wanted: starts.append((row[identity], start))
            reader.white(); separator = reader.take()
            if separator == b"]": break
            need(separator == b",", "PAPER_EXTENSION_SOURCE_RECORD_ARRAY")
    result = {}
    for key, start in starts:
        with path.open("rb") as stream:
            stream.seek(start); reader = _parser_type()(stream); reader.base = start
            row = reader.metadata_fields(set(fields) | {identity})
        need(key not in result, "PAPER_EXTENSION_DUPLICATE_SOURCE_IDENTITY:" + key)
        result[key] = row
    return result


def tail_required_scope(flags_ref, baselines, dates, domain):
    """Fixed-pool targets plus accepted prefix carry; no value-based selection."""
    import pandas as pd
    import pyarrow.dataset as ds
    flags = ds.dataset(verified(flags_ref), format="parquet")
    keys = flags.to_table(columns=["ticker", "signal_date", "raw_a2_rank", "is_raw_top20"],
        filter=ds.field("signal_date").isin([pd.Timestamp(d).to_pydatetime() for d in dates])).to_pandas()
    carry = set(); carry_refs = {}
    for sid in IDS:
        ref = baselines[sid]["positions"]; carry_refs[sid] = ref
        positions = ds.dataset(verified(ref), format="parquet").to_table(columns=["ticker", "date", "path_id"],
            filter=(ds.field("path_id") == sid) & (ds.field("date") == pd.Timestamp(PREFIX_END).to_pydatetime())).to_pandas()
        carry.update(positions.ticker.astype(str))
    ranked = set(keys.loc[keys.raw_a2_rank.notna(), "ticker"].astype(str))
    need(ranked <= set(domain) and carry <= set(domain), "PAPER_EXTENSION_REQUIRED_TICKER_OUTSIDE_ORIGINAL_MARKET_ABI")
    required = {}; targets = set()
    for day in pd.DatetimeIndex(dates):
        selected = keys.loc[keys.signal_date.eq(day) & keys.is_raw_top20, "ticker"].astype(str)
        need(len(selected) == 20 and selected.nunique() == 20, "PAPER_EXTENSION_CURRENT_TOP20_INCOMPLETE")
        targets.update(selected); required[str(day.date())] = sorted(set(selected) | carry)
    required = {day: sorted(targets | carry) for day in required}
    return required, dict(carry_tickers=sorted(carry), target_tickers=sorted(targets),
        baseline_position_refs=carry_refs, ranked_tail_tickers=sorted(ranked))


def source_date_projection(ref, dates, fields):
    """Read dates first, then only authorized leaf rows and requested columns."""
    import csv
    import pandas as pd
    import pyarrow.dataset as ds
    path = verified(ref); days = {str(pd.Timestamp(d).date()) for d in dates}
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream: names = next(csv.reader(stream))
        day = next((k for k in ("trade_date", "date", "time_key") if k in names), None)
        need(day is not None, "PAPER_EXTENSION_RAW_DATE_SCHEMA")
        clock = pd.read_csv(path, usecols=[day], dtype=str)[day]
        need(len(clock) <= 250000, "PAPER_EXTENSION_RAW_LEAF_ROW_LIMIT")
        keep = {i + 1 for i, value in enumerate(clock) if str(value)[:10] in days}
        return pd.read_csv(path, usecols=[k for k in fields if k in names],
            skiprows=lambda i: i > 0 and i not in keep)
    need(path.suffix.lower() == ".parquet", "PAPER_EXTENSION_RAW_SOURCE_FORMAT")
    data = ds.dataset(path, format="parquet")
    day = next((k for k in ("trade_date", "date", "time_key") if k in data.schema.names), None)
    need(day is not None, "PAPER_EXTENSION_RAW_DATE_SCHEMA")
    raw_clock = data.to_table(columns=[day])[day]
    need(len(raw_clock) <= 250000, "PAPER_EXTENSION_RAW_LEAF_ROW_LIMIT")
    values = raw_clock.to_pandas(); mask = pd.to_datetime(values).dt.strftime("%Y-%m-%d").isin(days)
    selected = raw_clock.filter(__import__("pyarrow").array(mask.to_numpy())).unique()
    return data.to_table(columns=[k for k in fields if k in data.schema.names],
        filter=ds.field(day).isin(selected)).to_pandas()


def _catalog_raw_tail(store, ticker, code, ref, dates, as_of):
    """Invoke the existing native owner with an immutable, date-bounded store view."""
    import sqlite3
    from contextlib import closing
    from scripts.research.a2.inference import current_native_prices as native
    from scripts import daily_recommendation_prices as prices
    with closing(sqlite3.connect(f"file:{store.catalog_path.as_posix()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute(
            "SELECT dataset,ticker,adjustment,source,format,path,source_sha256,lineage_json FROM data_files WHERE path=? AND source_sha256=?",
            (str(verified(ref)), ref["sha256"]))]
    need(len(rows) == 1, "PAPER_EXTENSION_EXACT_CATALOG_RAW_VERSION_REQUIRED:" + ticker)
    record = rows[0]; inputs = store.resolve_price_inputs(record, verify_raw=False)
    fields = ["date", "ticker", *prices.PRICE_FIELDS, "source", "adjustment", "provider_code", "source_id"]
    frame = source_date_projection(ref, dates, fields)
    cache = native._RunCache([code]); leaf_receipts = []
    selected = set(frame.source_id) if "source_id" in frame else set()
    for leaf in inputs:
        if leaf["sha256"] not in selected: continue
        clean = {k: leaf[k] for k in ("path", "sha256")}
        _, receipt = raw_csv_tail(clean, ticker, code, dates, as_of)
        projected = source_date_projection(clean, dates, ["ticker", "code", "moomoo_symbol", "provider_code", "source", "adjustment",
            "trade_date", "date", "time_key", *prices.PRICE_FIELDS])
        cache.frames[str(verified(clean))] = projected; leaf_receipts.append(receipt)
    class BoundedStore:
        def metadata(self, *args): return record
        def resolve_price_inputs(self, *args, **kwargs): return inputs
        def daily(self, *args, **kwargs): return frame.copy()
    raw, proof = native._native_raw(BoundedStore(), ticker, code, max(str(d)[:10] for d in dates), cache)
    cache.finish(); raw["ticker"] = ticker
    return raw[["ticker", "trade_date", "open", "close"]], dict(native_source_proof=proof, raw_leaf_receipts=leaf_receipts,
        qualifier="scripts.research.a2.inference.current_native_prices._native_raw", normalized_leaf_exact=True)


def qualified_native_tail(store, ticker, code, ref, dates, as_of):
    # The original producer can label an immutable normalized Parquet CURRENT_RAW.
    # Format chooses the existing native qualifier; the role never makes it CSV.
    if Path(ref["path"]).suffix.lower() != ".csv":
        return _catalog_raw_tail(store, ticker, code, ref, dates, as_of)
    import pandas as pd
    from scripts.research.a2.inference import current_native_prices as native
    from scripts import daily_recommendation_prices as prices
    tail, raw_receipt = raw_csv_tail(ref, ticker, code, dates, as_of)
    cache = native._RunCache([code]); cache.frames[str(verified(ref))] = source_date_projection(ref, dates,
        ["ticker", "moomoo_symbol", "provider_code", "code", "source", "adjustment", "trade_date", "date", "time_key", *prices.PRICE_FIELDS])
    exact = native._read_source(verified(ref), ticker, code, cache); cache.finish()
    check = exact.assign(ticker=ticker)[["ticker", "trade_date", "open", "close"]]
    pd.testing.assert_frame_equal(tail.reset_index(drop=True), check.reset_index(drop=True), check_exact=True)
    return tail, dict(raw_ref=ref, raw_leaf_receipts=[raw_receipt], qualifier="scripts.research.a2.inference.current_native_prices._read_source")


def _current_quote_source(paths, document, end, as_of):
    import pandas as pd
    proof = projected_metadata(document["source_extension_ref"], ("current_day_proofs",))
    current = [r for r in proof["current_day_proofs"] if r["signal_date"] == end]
    need(len(current) == 1, "PAPER_EXTENSION_CURRENT_MAPPING_PROOF_REQUIRED")
    mapping_ref = current[0]["mapping_ref"]; mapping = verified(mapping_ref)
    run = mapping.parent.parent; report_ref = reference(run / "report.json")
    report = projected_metadata(report_ref, ("status", "data_date", "generated_at", "accepted_source", "accepted_inputs"))
    need(report.get("status") == "READY" and report.get("data_date") == end, "PAPER_EXTENSION_ACCEPTED_DAILY_SOURCE_REQUIRED")
    clock = pd.Timestamp(report["generated_at"]); limit = pd.Timestamp(as_of)
    need(clock.tzinfo is not None and clock <= limit, "PAPER_EXTENSION_DAILY_SOURCE_AFTER_ASOF")
    source_ref = report["accepted_source"]; need(verified(source_ref) == run / "recommendation_source.json", "PAPER_EXTENSION_DAILY_SOURCE_COORDINATE")
    source = projected_metadata(source_ref, ("status", "data_date", "generated_at"))
    need(source.get("status") == "READY" and source.get("data_date") == end and pd.Timestamp(source["generated_at"]).tzinfo is not None
         and pd.Timestamp(source["generated_at"]) <= limit, "PAPER_EXTENSION_ACCEPTED_SOURCE_CLOCK")
    universe = projected_metadata(source_ref, ("report_path", "universe_members_sha256", "identity_source"), ("universe",))
    need(mapping_ref == dict(path=str(Path(universe["report_path"]).parent / "mapped_members.parquet"), sha256=universe["universe_members_sha256"]),
         "PAPER_EXTENSION_ACCEPTED_MAPPING_CHANGED")
    refs = {Path(r["path"]).name: r for r in report["accepted_inputs"]}
    for name in ("input_lineage.json", "rehab_receipt.json"):
        need(name in refs and verified(refs[name]) == run / name, "PAPER_EXTENSION_ACCEPTED_SOURCE_INPUT_REQUIRED:" + name)
    return dict(report_ref=report_ref, accepted_source_ref=source_ref, mapping_ref=mapping_ref,
        lineage_ref=refs["input_lineage.json"], rehab_receipt_ref=refs["rehab_receipt.json"], identity_ref=universe["identity_source"])



_CA_LOCATOR_SCHEMA = "CONSENSUS_SUPPLEMENTAL_CA_LOCATOR_R1"
_CA_LOCATOR_BYTES = 4096
_CA_LOCATOR_MAX_REFS = 16


def _ca_locator_clock(value):
    need(isinstance(value, str), "PAPER_EXTENSION_CA_LOCATOR_CLOCK_REQUIRED")
    clock = datetime.fromisoformat(value.replace("Z", "+00:00"))
    need(clock.tzinfo is not None and clock.utcoffset() is not None, "PAPER_EXTENSION_CA_LOCATOR_CLOCK_REQUIRED")
    return clock


def _ca_locator_ref(ref):
    import re
    need(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
         and isinstance(ref["path"], str) and 0 < len(ref["path"]) <= 1024 and "\x00" not in ref["path"]
         and isinstance(ref["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) is not None,
         "PAPER_EXTENSION_CA_LOCATOR_REF_SCHEMA")
    # Reject forbidden lexical drives before any resolution or I/O.
    need(not re.match(r"^[EF]:", ref["path"], re.I) and Path(ref["path"]).is_absolute(),
         "PAPER_EXTENSION_CA_LOCATOR_REF_PATH")
    verified(ref)
    return dict(ref)


def _ca_locator_path(paths, target_session):
    import re
    from scripts.common.storage_paths import assert_safe_output_path
    need(isinstance(target_session, str) and re.fullmatch(r"2026-\d{2}-\d{2}", target_session) is not None,
         "PAPER_EXTENSION_CA_LOCATOR_TARGET_REQUIRED")
    datetime.strptime(target_session, "%Y-%m-%d")
    output = paths.daily_root / "A2_consensus_paper/current_tail_ca" / target_session / "supplemental_refs.json"
    assert_safe_output_path(output, kind="daily", paths=paths)
    return output


def _ca_locator_origin(paths, *, target_session, publication_ref, capture_ref, daily_report_ref, as_of):
    """Reuse current identity acceptance; only report branch fields may vary."""
    for ref in (publication_ref, capture_ref, daily_report_ref): _ca_locator_ref(ref)
    _ca_locator_clock(as_of)
    preflight = metadata_preflight(paths, capture_ref=capture_ref, as_of=as_of)
    need(preflight["end"] == target_session and preflight["publication_ref"] == publication_ref
         and preflight["capture_ref"] == capture_ref, "PAPER_EXTENSION_CA_LOCATOR_CURRENT_BINDING_CHANGED")
    source = _current_quote_source(paths, preflight["document"], target_session, as_of)
    need(source["report_ref"] == daily_report_ref, "PAPER_EXTENSION_CA_LOCATOR_CURRENT_REPORT_CHANGED")
    report = projected_metadata(daily_report_ref, ("accepted_source", "accepted_inputs"))
    need(report["accepted_source"] == source["accepted_source_ref"] and isinstance(report["accepted_inputs"], list)
         and 0 < len(report["accepted_inputs"]) <= 16, "PAPER_EXTENSION_CA_LOCATOR_ACCEPTED_INPUTS_REQUIRED")
    _ca_locator_ref(report["accepted_source"])
    for ref in report["accepted_inputs"]: _ca_locator_ref(ref)
    # Full report SHA remains a retry coordinate in the caller. Persist only its
    # exact accepted input identity, so a branch-status rewrite grants nothing.
    binding = dict(target_session=target_session, publication_ref=publication_ref, capture_ref=capture_ref,
        daily_report_binding=dict(path=daily_report_ref["path"], accepted_source_ref=report["accepted_source"],
            accepted_input_refs=report["accepted_inputs"]))
    return binding, preflight["calendar_qualification"]


def _ca_locator_receipts(refs, *, target_session, as_of, calendar_proof):
    """Check receipt metadata only; native event/term qualification stays original."""
    from scripts.common.json_projection import _parser_type
    need(isinstance(refs, (list, tuple)) and 0 < len(refs) <= _CA_LOCATOR_MAX_REFS,
         "PAPER_EXTENSION_CA_LOCATOR_RECEIPT_BOUND")
    clock = _ca_locator_clock(as_of); close = _ca_locator_clock(calendar_proof["session_close_utc"])
    result = []; seen = set()
    for ref in refs:
        ref = _ca_locator_ref(ref); key = canonical(ref)
        need(key not in seen, "PAPER_EXTENSION_CA_LOCATOR_DUPLICATE_RECEIPT"); seen.add(key)
        path = verified(ref); need(path.stat().st_size <= 2 * 1024 * 1024, "PAPER_EXTENSION_CA_LOCATOR_RECEIPT_FILE_BOUND")
        head = projected_metadata(ref, ("status", "source", "target_date", "completed_at", "history_requests", "trade_requests"))
        need(head.get("status") == "READY" and head.get("source") == "MOOMOO_OPEND_GET_REHAB"
             and head.get("target_date") == target_session and head.get("history_requests") == 0 and head.get("trade_requests") == 0,
             "PAPER_EXTENSION_CA_LOCATOR_RECEIPT_INVALID")
        completed = _ca_locator_clock(head["completed_at"])
        need(close <= completed <= clock, "PAPER_EXTENSION_CA_LOCATOR_RECEIPT_CLOCK")
        with path.open("rb") as stream:
            reader = _parser_type()(stream); reader.descend(("results",)); reader.expect(b"["); reader.white()
            count = 0; codes = set()
            while reader.peek() != b"]":
                row = reader.metadata_fields({"code", "status", "fetched_at"}); count += 1
                need(count <= 1500 and isinstance(row.get("code"), str) and 0 < len(row["code"]) <= 128
                     and row["code"] not in codes and row.get("status") == "PASS", "PAPER_EXTENSION_CA_LOCATOR_RESPONSE_METADATA")
                codes.add(row["code"]); fetched = _ca_locator_clock(row["fetched_at"])
                need(close <= fetched <= completed, "PAPER_EXTENSION_CA_LOCATOR_RESPONSE_CLOCK")
                reader.white(); separator = reader.take()
                if separator == b"]": break
                need(separator == b",", "PAPER_EXTENSION_CA_LOCATOR_RESPONSE_ARRAY"); reader.white()
                need(reader.peek() != b"]", "PAPER_EXTENSION_CA_LOCATOR_RESPONSE_ARRAY")
            need(count > 0, "PAPER_EXTENSION_CA_LOCATOR_RESPONSE_METADATA")
        verified(ref)
        result.append(ref)
    return result


def _ca_locator_read(path):
    need(path.stat().st_size <= _CA_LOCATOR_BYTES, "PAPER_EXTENSION_CA_LOCATOR_FILE_BOUND")
    before = reference(path)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "PAPER_EXTENSION_CA_LOCATOR_DUPLICATE_KEY"); result[key] = value
        return result
    def reject(value): raise ValueError("PAPER_EXTENSION_CA_LOCATOR_NONFINITE_JSON")
    with path.open("rb") as stream:
        raw = stream.read(_CA_LOCATOR_BYTES + 1)
    need(len(raw) <= _CA_LOCATOR_BYTES, "PAPER_EXTENSION_CA_LOCATOR_FILE_BOUND")
    body = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    need(reference(path) == before, "PAPER_EXTENSION_CA_LOCATOR_CHANGED_DURING_READ")
    need(isinstance(body, dict) and set(body) == {"schema", "status", "registered_as_of", "binding", "ca_receipt_refs"}
         and body["schema"] == _CA_LOCATOR_SCHEMA and body["status"] == "LOCATOR_ONLY_NOT_QUALIFIED",
         "PAPER_EXTENSION_CA_LOCATOR_SCHEMA")
    return body, before


def register_supplemental_ca_receipts(paths, *, target_session, publication_ref, capture_ref, daily_report_ref, as_of, ca_receipt_refs):
    """Register explicit native receipt locations; this grants no CA admission."""
    from scripts.common.daily_support import save, single_update
    output = _ca_locator_path(paths, target_session)
    with single_update(paths.daily_root / "A2_today_recommendation"):
        binding, proof = _ca_locator_origin(paths, target_session=target_session, publication_ref=publication_ref,
            capture_ref=capture_ref, daily_report_ref=daily_report_ref, as_of=as_of)
        refs = _ca_locator_receipts(ca_receipt_refs, target_session=target_session, as_of=as_of, calendar_proof=proof)
        if output.exists():
            old, _ = _ca_locator_read(output)
            need(old["binding"] == binding, "PAPER_EXTENSION_CA_LOCATOR_EXISTING_BINDING_CHANGED")
            need(_ca_locator_clock(old["registered_as_of"]) <= _ca_locator_clock(as_of), "PAPER_EXTENSION_CA_LOCATOR_AFTER_ASOF")
            if old["ca_receipt_refs"] == refs:
                return dict(locator_ref=reference(output), ca_receipt_refs=refs)
        body = dict(schema=_CA_LOCATOR_SCHEMA, status="LOCATOR_ONLY_NOT_QUALIFIED", registered_as_of=as_of,
            binding=binding, ca_receipt_refs=refs)
        encoded = json.dumps(body, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        need(len(encoded.encode("utf8")) <= _CA_LOCATOR_BYTES, "PAPER_EXTENSION_CA_LOCATOR_FILE_BOUND")
        save(output, body)
        _, ref = _ca_locator_read(output)
        return dict(locator_ref=ref, ca_receipt_refs=refs)


def resolve_supplemental_ca_receipts(paths, *, target_session, publication_ref, capture_ref, daily_report_ref, as_of):
    """Resolve only this completed date and input identity, never a latest run."""
    output = _ca_locator_path(paths, target_session)
    if not output.exists(): return dict(locator_ref=None, ca_receipt_refs=[])
    body, ref = _ca_locator_read(output)
    binding, proof = _ca_locator_origin(paths, target_session=target_session, publication_ref=publication_ref,
        capture_ref=capture_ref, daily_report_ref=daily_report_ref, as_of=as_of)
    need(body["binding"] == binding, "PAPER_EXTENSION_CA_LOCATOR_BINDING_CHANGED")
    need(_ca_locator_clock(body["registered_as_of"]) <= _ca_locator_clock(as_of), "PAPER_EXTENSION_CA_LOCATOR_AFTER_ASOF")
    refs = _ca_locator_receipts(body["ca_receipt_refs"], target_session=target_session, as_of=as_of, calendar_proof=proof)
    verified(ref)
    return dict(locator_ref=ref, ca_receipt_refs=refs)


def tail_ca_qualification(receipt_refs, codes, dates, as_of, calendar_proof):
    """A current native factor response proves absence, never a guessed empty event list."""
    import pandas as pd
    import pyarrow.dataset as ds
    clock = pd.Timestamp(as_of); close = pd.Timestamp(calendar_proof["session_close_utc"]); selected = {}
    for ref in receipt_refs:
        head = projected_metadata(ref, ("status", "source", "target_date", "completed_at", "history_requests", "trade_requests"))
        need(head.get("status") == "READY" and head.get("source") == "MOOMOO_OPEND_GET_REHAB"
             and head.get("target_date") == calendar_proof["target_session"] and head.get("history_requests") == 0
             and head.get("trade_requests") == 0, "PAPER_EXTENSION_CURRENT_CA_RECEIPT_INVALID")
        completed = pd.Timestamp(head["completed_at"])
        need(completed.tzinfo is not None and close <= completed <= clock, "PAPER_EXTENSION_CA_RECEIPT_AFTER_ASOF")
        rows = selected_source_rows(ref, codes, ("code", "status", "path", "sha256", "row_count", "fetched_at"), branch=("results",), identity="code")
        for code, row in rows.items():
            fetched = pd.Timestamp(row["fetched_at"])
            need(row.get("status") == "PASS" and fetched.tzinfo is not None and close <= fetched <= completed,
                 "PAPER_EXTENSION_CA_RESPONSE_CLOCK_OR_STATUS:" + code)
            leaf = {k: row[k] for k in ("path", "sha256")}; data = ds.dataset(verified(leaf), format="parquet")
            need({"code", "ex_div_date", "forward_adj_factorA", "forward_adj_factorB"} <= set(data.schema.names), "PAPER_EXTENSION_CA_RESPONSE_SCHEMA:" + code)
            keys = data.to_table(columns=["code", "ex_div_date"]).to_pandas()
            need(len(keys) == row["row_count"] and keys.code.eq(code).all(), "PAPER_EXTENSION_CA_RESPONSE_IDENTITY:" + code)
            event_days = pd.to_datetime(keys.ex_div_date, errors="coerce")
            need(keys.empty or not event_days.isna().any(), "PAPER_EXTENSION_CA_EVENT_DATE_INVALID:" + code)
            events = sorted(set(event_days.loc[event_days.gt(pd.Timestamp(PREFIX_END)) & event_days.le(pd.Timestamp(calendar_proof["target_session"]))].dt.strftime("%Y-%m-%d")))
            value = dict(code=code, receipt_ref=ref, response_ref=leaf, fetched_at=fetched.isoformat(),
                in_scope_event_dates=events, in_scope_event_count=len(events), absence_proven_from_current_native_response=not events)
            if code in selected:
                need(selected[code]["response_ref"] == leaf, "PAPER_EXTENSION_CONFLICTING_CA_RESPONSE:" + code)
            selected[code] = value
    missing = sorted(set(codes) - set(selected)); events = {k: v["in_scope_event_dates"] for k, v in selected.items() if v["in_scope_event_count"]}
    return dict(status="READY" if not missing and not events else "BLOCKED", missing_codes=missing,
        typed_event_terms_required=events, response_proofs=selected, historical_factor_vintage_equivalence_claimed=False)


def tail_security_identity(identities, flags, ticker, mapping=None):
    # Aux feature rows outside the fixed pool legitimately have no current SID;
    # accepted carry identity remains the last bound observation, never "nan".
    dated = flags.loc[flags.ticker.eq(ticker) & flags.security_id.notna() & flags.security_id.astype(str).ne("")].sort_values("signal_date")
    need(not dated.empty, "PAPER_EXTENSION_DATED_CARRY_IDENTITY_REQUIRED:" + ticker)
    sid = str(dated.security_id.iloc[-1])
    if mapping is not None:
        current = mapping.loc[mapping.ticker.eq(ticker)]
        if not current.empty:
            current = current.loc[current.security_id.astype(str).eq(sid)]
            need(len(current) == 1 and current.moomoo_symbol.notna().all(), "PAPER_EXTENSION_CURRENT_DATED_MAPPING_INVALID:" + ticker)
            return str(current.moomoo_symbol.iloc[0]), sid
    identity = identities.loc[identities.ticker.eq(ticker) & identities.cusip.astype(str).eq(sid)]
    need(len(identity) == 1 and identity.moomoo_current_validated.eq(True).all() and identity.transport_static_validated.eq(True).all()
         and identity.mapping_status.eq("RESOLVED").all(), "PAPER_EXTENSION_CURRENT_SECURITY_IDENTITY_INVALID:" + ticker)
    return str(identity.moomoo_transport_code.iloc[0]), sid


def qualify_current_tail(paths, *, document, baselines, domain, as_of, calendar_qualification, ca_receipt_refs=()):
    """Light source-only recovery entry: no provider requests, model or account replay."""
    import pandas as pd
    import pyarrow.dataset as ds
    from scripts.storage.storage_r2a import DataStore
    dates = calendar_qualification["tail_sessions"]; end = calendar_qualification["target_session"]
    owner_refs = {name: reference(paths.repo_root / name) for name in (
        "scripts/research/a2/inference/current_native_prices.py", "scripts/daily_recommendation_prices.py", "scripts/storage/storage_r2a.py")}
    validate_calendar_proof(calendar_qualification, as_of, end)
    required, scope = tail_required_scope(document["flags_ref"], baselines, dates, domain)
    wanted = set().union(*(set(v) for v in required.values())); source = _current_quote_source(paths, document, end, as_of)
    rows = selected_source_rows(source["lineage_ref"], wanted, ("ticker", "code", "source", "raw_sources"))
    identities = ds.dataset(verified(source["identity_ref"]), format="parquet").to_table(
        columns=["ticker", "cusip", "moomoo_transport_code", "moomoo_current_validated", "transport_static_validated", "mapping_status"],
        filter=ds.field("ticker").isin(sorted(wanted))).to_pandas()
    mapping = ds.dataset(verified(source["mapping_ref"]), format="parquet").to_table(columns=["ticker", "security_id", "moomoo_symbol"],
        filter=ds.field("ticker").isin(sorted(wanted))).to_pandas()
    flags = ds.dataset(verified(document["flags_ref"]), format="parquet").to_table(columns=["ticker", "signal_date", "security_id"],
        filter=ds.field("ticker").isin(sorted(wanted)) & (ds.field("signal_date") <= pd.Timestamp(end).to_pydatetime())).to_pandas()
    store = DataStore(paths); pieces = []; proofs = {}; codes = {}; missing_raw = {}
    for ticker in sorted(wanted):
        code, sid = tail_security_identity(identities, flags, ticker, mapping)
        codes[ticker] = code; row = rows.get(ticker)
        if row is None:
            need(ticker in scope["carry_tickers"] and ticker not in scope["target_tickers"], "PAPER_EXTENSION_CURRENT_TARGET_LINEAGE_MISSING:" + ticker)
            record = store.metadata("prices_daily", ticker, "raw"); ref = dict(path=record["path"], sha256=record["source_sha256"])
            route = "ACCEPTED_PREFIX_CARRY_NATIVE_RAW_ONLY"
        else:
            need(row["code"] == code and row["source"] == "MOOMOO_OPEND_RAW_PLUS_REHAB", "PAPER_EXTENSION_CURRENT_LINEAGE_IDENTITY:" + ticker)
            candidates = [r for r in row["raw_sources"] if r.get("role") in ("CURRENT_RAW", "CURRENT_CATALOG_RAW", "NATIVE_MOOMOO_ANCHOR")]
            need(len(candidates) == 1, "PAPER_EXTENSION_CURRENT_RAW_ROUTE_AMBIGUOUS:" + ticker)
            selected = candidates[0]; ref = {k: selected[k] for k in ("path", "sha256")}; route = selected["role"]
        tail, raw_proof = qualified_native_tail(store, ticker, code, ref, dates, as_of)
        supplied = set(pd.to_datetime(tail.trade_date).dt.strftime("%Y-%m-%d")); needed = {day for day, members in required.items() if ticker in members}
        if needed - supplied: missing_raw[ticker] = sorted(needed - supplied)
        tail["quality"] = False; pieces.append(tail)
        proofs[ticker] = dict(ticker=ticker, code=code, security_id=sid, route=route, **raw_proof,
            identity_binding_role="CURRENT_ACCEPTED_DATED_MAPPING" if mapping.ticker.eq(ticker).any() else "ACCEPTED_PREFIX_CARRY_MASTER_BINDING",
            current_asof_qualification_only=True, historical_publication_time_certified=False, past_factor_stream_exact_claimed=False)
    ca = tail_ca_qualification([source["rehab_receipt_ref"], *ca_receipt_refs], set(codes.values()), dates, as_of, calendar_qualification)
    for ref in owner_refs.values(): verified(ref)
    result = dict(schema="CONSENSUS_FIXED_MAIN_CURRENT_TAIL_QUALIFICATION_R1", task_id=TASK,
        status="READY" if not missing_raw and ca["status"] == "READY" else "BLOCKED", as_of=str(as_of), end=end,
        calendar_qualification=calendar_qualification, source_refs=source, native_qualifier_owner_refs=owner_refs, flags_ref=document["flags_ref"], required_tickers_by_date=required,
        original_market_tickers=sorted(domain), inactive_tickers_not_required=sorted(set(domain)-wanted), scope=scope,
        raw_qualified_tickers=sorted(proofs), raw_source_proofs=proofs, missing_raw_dates=missing_raw, ca_qualification=ca,
        model_fit_calls=0, models_loaded=0, account_replays=0, broker_action_allowed=False, source_or_account_admission_inherited=False,
        strict_historical_pit_claim=False)
    return pd.concat(pieces, ignore_index=True), result


def prepare_raw_quote_extension(paths, *, original_market_ref, flags_ref, capture_ref, as_of, calendar_qualification, document, baselines, ca_receipt_refs=()):
    """Preserve the exact old market domain/prefix; append qualified native leaves."""
    import pandas as pd
    import pyarrow.dataset as ds
    from scripts.common.storage_paths import assert_safe_output_path
    from scripts.research.a2.inference.consensus_paper import bounded_frame
    need(original_market_ref.get("sha256")=="a057aea7f8c667589740a42fdab59678d3c99cf3d1224e8ad63940cf1e03072a","PAPER_EXTENSION_ORIGINAL_QUOTE_PIN_REQUIRED")
    clock=pd.Timestamp(as_of);need(clock.tzinfo is not None,"PAPER_EXTENSION_ASOF_CLOCK_REQUIRED")
    capture=projected_metadata(capture_ref,("end_date","captured_prices","events","vintage_semantics"))
    end = calendar_qualification["target_session"]
    validate_calendar_proof(calendar_qualification, clock, end)
    dates = pd.DatetimeIndex(calendar_qualification["tail_sessions"])
    need(capture.get("end_date")==end,"PAPER_EXTENSION_CAPTURE_CALENDAR_CHANGED")
    original=bounded_frame(original_market_ref,["ticker","trade_date","open","close","quality"],"trade_date",START,PREFIX_END)
    domain=set(original.ticker.astype(str))
    source=ds.dataset(verified(flags_ref),format="parquet")
    rule=ds.field("signal_date").isin([d.to_pydatetime() for d in dates])
    keys=source.to_table(columns=["ticker","signal_date","raw_a2_rank","is_raw_top20"],filter=rule).to_pandas()
    ranked=set(keys.loc[keys.raw_a2_rank.notna(),"ticker"].astype(str))
    need(ranked<=domain,"PAPER_EXTENSION_NEW_RANKED_TICKER_OUTSIDE_ORIGINAL_MARKET_ABI")
    need(document["flags_ref"] == flags_ref, "PAPER_EXTENSION_CURRENT_FLAGS_BINDING_CHANGED")
    tail, current_proof = qualify_current_tail(paths, document=document, baselines=baselines, domain=domain,
        as_of=clock.isoformat(), calendar_qualification=calendar_qualification, ca_receipt_refs=ca_receipt_refs)
    need(not current_proof["missing_raw_dates"], "PAPER_EXTENSION_REQUIRED_CURRENT_RAW_QUOTE_GAP:" + canonical(current_proof["missing_raw_dates"]))
    ca = current_proof["ca_qualification"]
    need(not ca["missing_codes"], "PAPER_EXTENSION_CURRENT_CA_RESPONSE_MISSING:" + ",".join(ca["missing_codes"]))
    need(not ca["typed_event_terms_required"], "PAPER_EXTENSION_IN_SCOPE_NEW_CA_TERMS_REQUIRED:" + canonical(ca["typed_event_terms_required"]))
    need(current_proof["status"] == "READY" and not tail.duplicated(["trade_date", "ticker"]).any(), "PAPER_EXTENSION_CURRENT_NATIVE_QUOTE_NOT_READY")
    event_source=ds.dataset(verified(capture["events"]),format="parquet")
    predicate=ds.field("event_date").isin([day.to_pydatetime() for day in dates])&ds.field("ticker").isin(sorted(domain))
    events=event_source.to_table(columns=["ticker","event_date","audit_kind","share_event"],filter=predicate).to_pandas()
    need(events.empty,"PAPER_EXTENSION_IN_SCOPE_NEW_CA_TERMS_REQUIRED:"+",".join(sorted(set(events.ticker.astype(str)))))
    # The recorded market domain is an input identity, independent of returns or
    # realized holdings. Auxiliary Raw/HGB names cannot expand its CA domain.
    combined=pd.concat([original,tail],ignore_index=True).sort_values(["trade_date","ticker"],kind="stable").reset_index(drop=True)
    identity=hashlib.sha256(canonical(dict(base=original_market_ref,flags=flags_ref,capture=capture_ref,as_of=clock.isoformat(), current_tail_qualification=current_proof)).encode()).hexdigest()[:20]
    output=paths.backtest_root/TASK/"descriptive_main_extension"/"source"/identity
    assert_safe_output_path(output,kind="backtest",paths=paths);output.mkdir(parents=True,exist_ok=True)
    destination=output/"raw_quotes.parquet"
    if destination.exists():
        pd.testing.assert_frame_equal(pd.read_parquet(destination),combined,check_exact=True)
    else:
        combined.to_parquet(destination,index=False,compression="zstd")
    proof=dict(schema="CONSENSUS_FIXED_MAIN_RAW_QUOTE_EXTENSION_R1",task_id=TASK,status="NATIVE_RAW_TAIL_BOUND_WITH_ORIGINAL_PREFIX",
        as_of=clock.isoformat(),end=end,calendar_qualification=calendar_qualification,
        original_market_ref=original_market_ref,flags_ref=flags_ref,capture_ref=capture_ref,quotes_ref=reference(destination),
        original_market_tickers=sorted(domain),ranked_tail_tickers=sorted(ranked),qualified_current_tickers=current_proof["raw_qualified_tickers"],
        current_tail_qualification=current_proof, current_in_scope_ca_event_count=0,
        ca_scope_basis="FIXED_ORIGINAL_MARKET_DOMAIN_CURRENT_TARGET_UNION_AND_ACCEPTED_PREFIX_CARRY_IDENTITY_ONLY",
        auxiliary_capture_events_outside_original_domain_are_not_account_admission=True,
        model_fit_calls=0,strict_historical_pit_claim=False,source_completeness_unknown=True,source_or_account_admission_inherited=False)
    receipt=output/"RAW_QUOTE_EXTENSION.json";body=canonical(proof)+"\n"
    if receipt.exists():need(receipt.read_text(encoding="utf8")==body,"PAPER_EXTENSION_PRESERVE_SOURCE_RECEIPT")
    else:receipt.write_text(body,encoding="utf8")
    return combined,proof,reference(receipt)


def compare_stock_prefix(frames, baseline_refs, candidate_id, *, next_execution_date=None):
    """Exact old stock history, except the original final pending Open matures."""
    import pandas as pd
    need(set(STOCK_TABLES)<=set(frames) and set(STOCK_TABLES)<=set(baseline_refs),"PAPER_EXTENSION_STOCK_TABLES_REQUIRED")
    if next_execution_date is None:
        post_prefix = pd.to_datetime(frames["daily"].loc[frames["daily"].path_id.eq(candidate_id), "date"])
        post_prefix = post_prefix[post_prefix.gt(pd.Timestamp(PREFIX_END))]
        need(not post_prefix.empty, "PAPER_EXTENSION_NEXT_SESSION_REQUIRED")
        next_execution_date = str(post_prefix.min().date())
    comparisons={}
    for name in STOCK_TABLES:
        before=_ordered(bounded_ledger(baseline_refs[name],name,candidate_id,PREFIX_END),name,candidate_id,PREFIX_END)
        actual=_ordered(frames[name],name,candidate_id,PREFIX_END)
        try:
            need(set(actual)==set(before) and len(actual)==len(before),"PAPER_EXTENSION_STOCK_PREFIX_SCHEMA_CHANGED:"+name)
        except ValueError:
            try:
                print(_prefix_failure_diagnostic(actual,before,candidate_id=candidate_id,table=name,event="PAPER_EXTENSION_STOCK_PREFIX_SCHEMA_CHANGED"),flush=True)
            except Exception:
                pass
            raise
        columns=["planned_execution_date"] if name=="actions" else ["execution_date","status"]
        need(set(columns)<=set(before),"PAPER_EXTENSION_STOCK_PENDING_SCHEMA_REQUIRED")
        aligned=actual[list(before)].copy()
        masks=[]
        for index in before.index:
            if pd.Timestamp(before.loc[index,"signal_date"])!=pd.Timestamp(PREFIX_END):continue
            clock_column=columns[0]
            if pd.isna(before.loc[index,clock_column]) and not pd.isna(aligned.loc[index,clock_column]):
                need(pd.Timestamp(aligned.loc[index,clock_column])==pd.Timestamp(next_execution_date),"PAPER_EXTENSION_PENDING_OPEN_CLOCK_CHANGED")
                if name=="orders":
                    need(before.loc[index,"status"]=="no_next_session" and aligned.loc[index,"status"]=="submitted",
                         "PAPER_EXTENSION_PENDING_ORDER_SEMANTIC_CHANGED")
                masks.append(index)
        def fields_hash(frame):
            keys=STOCK_TABLES[name][1]
            return hashlib.sha256(frame.loc[masks,keys+columns].to_csv(index=False,na_rep="NA").encode()).hexdigest()
        old_hash,new_hash=fields_hash(before),fields_hash(aligned)
        for column in columns:
            aligned.loc[masks,column]=before.loc[masks,column]
        try:
            pd.testing.assert_frame_equal(aligned,before,check_exact=True,check_dtype=True)
        except AssertionError as exc:
            try:
                print(_prefix_failure_diagnostic(aligned,before,candidate_id=candidate_id,table=name,event="PAPER_EXTENSION_STOCK_ACCEPTED_PREFIX_CHANGED"),flush=True)
            except Exception:
                pass
            raise ValueError("PAPER_EXTENSION_STOCK_ACCEPTED_PREFIX_CHANGED:"+name) from exc
        comparisons[name]=dict(status="EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY",original_ref=baseline_refs[name],rows=len(before),
            unchanged_columns_status="EXACT_MATCH",pending_maturity=dict(signal_date=PREFIX_END,next_execution_date=next_execution_date,
                allowed_columns=columns,changed_rows=len(masks),old_fields_sha256=old_hash,new_fields_sha256=new_hash))
    return dict(status="EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY",table_comparisons=comparisons,
                historical_cutoff_at_or_before_prefix_uses_original_baseline=True)


def publish_manifest(paths, completion_refs_by_id):
    """One shared pointer; all three qualified six-table receipts switch together."""
    from scripts.common.storage_paths import assert_safe_output_path
    need(set(completion_refs_by_id)==set(IDS),"PAPER_EXTENSION_THREE_COMPLETIONS_REQUIRED")
    receipts={sid:projected_metadata(ref,("schema","status","candidate_ids","window_id","start","first_execution_date","prefix_end","end","as_of","calendar_qualification",
        "artifacts","baseline_artifacts","model_fit_calls","selection_using_2026","independent_holdout_claim","broker_action_allowed","original_prefix_comparison","stock_prefix_comparison"))
        for sid,ref in completion_refs_by_id.items()}
    clocks=set(); ends=set(); calendars=set()
    for sid,receipt in receipts.items():
        need(receipt.get("schema")==SCHEMA and receipt.get("status")=="PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION"
             and receipt.get("candidate_ids")==[sid] and receipt.get("window_id")=="MAIN" and receipt.get("start")==START
             and receipt.get("first_execution_date")==FIRST_EXECUTION and receipt.get("prefix_end")==PREFIX_END and PREFIX_END < receipt.get("end", "") < "2027-01-01"
             and receipt.get("model_fit_calls")==0 and receipt.get("selection_using_2026") is False and receipt.get("broker_action_allowed") is False
             and receipt.get("independent_holdout_claim") is False and receipt.get("original_prefix_comparison",{}).get("status")=="EXACT_MATCH"
             and receipt.get("stock_prefix_comparison",{}).get("status")=="EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY"
             and set(receipt.get("artifacts",{}))==set(LEDGER_TABLES) and set(LEDGER_TABLES)<=set(receipt.get("baseline_artifacts",{})),
             "PAPER_EXTENSION_SHARED_QUALIFICATION_REQUIRED")
        for ref in [*receipt["artifacts"].values(),*receipt["baseline_artifacts"].values()]:verified(ref)
        validate_calendar_proof(receipt["calendar_qualification"],receipt["as_of"],receipt["end"])
        need(receipt["baseline_artifacts"]==accepted_baseline_refs(sid),"PAPER_EXTENSION_ACCEPTED_BASELINE_PINS_REQUIRED")
        clocks.add(receipt["as_of"]); ends.add(receipt["end"]); calendars.add(canonical(receipt["calendar_qualification"]))
    need(len(clocks)==len(ends)==len(calendars)==1,"PAPER_EXTENSION_SHARED_ASOF_REQUIRED")
    end=next(iter(ends)); calendar_proof=json.loads(next(iter(calendars)))
    manifest=dict(schema="CONSENSUS_FIXED_MAIN_PAPER_EXTENSION_MANIFEST_R1",task_id=TASK,status="PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION",
        candidate_ids=list(IDS),window_id="MAIN",start=START,first_execution_date=FIRST_EXECUTION,prefix_end=PREFIX_END,end=end,as_of=next(iter(clocks)),calendar_qualification=calendar_proof,
        model_fit_calls=0,selection_using_2026=False,broker_action_allowed=False,independent_holdout_claim=False,
        extensions=completion_refs_by_id,baseline_stock_sources={sid:receipt["baseline_artifacts"] for sid,receipt in receipts.items()})
    identity=hashlib.sha256(canonical(manifest).encode()).hexdigest()[:20]
    output=paths.backtest_root/TASK/"descriptive_main_extension"/end/("MAIN_EXTENSION_MANIFEST_"+identity+".json")
    assert_safe_output_path(output,kind="backtest",paths=paths);output.parent.mkdir(parents=True,exist_ok=True)
    body=canonical(manifest)+"\n"
    if output.exists():need(output.read_text(encoding="utf8")==body,"PAPER_EXTENSION_PRESERVE_SHARED_MANIFEST")
    else:output.write_text(body,encoding="utf8")
    pointer=paths.daily_root/"A2_consensus_paper"/"MAIN_extension_latest.json"
    assert_safe_output_path(pointer,kind="daily",paths=paths);pointer.parent.mkdir(parents=True,exist_ok=True)
    temporary=pointer.with_suffix(".tmp");temporary.write_text(canonical(reference(output)),encoding="utf8");temporary.replace(pointer)
    return manifest,reference(output)


def accepted_baseline_refs(candidate_id):
    """The accepted completion pin, not a caller-selected ledger, owns all six refs."""
    need(candidate_id in IDS, "PAPER_EXTENSION_EXACT_BASELINE_CANDIDATE")
    refs, _ = completion_refs(ACCEPTED_MAIN[candidate_id], candidate_id)
    for ref in refs.values(): verified(ref)
    return refs


def selected_rows(ref, container, candidate_id):
    """Only decode the named candidate's specification; skip other rows lexically."""
    from scripts.common.json_projection import _parser_type
    starts = []
    with verified(ref).open("rb") as stream:
        reader = _parser_type()(stream); reader.descend((container,)); reader.expect(b"["); reader.white()
        while reader.peek() != b"]":
            start = reader.tell(); identity = reader.metadata_fields({"candidate_id"})
            if identity.get("candidate_id") == candidate_id: starts.append(start)
            reader.white(); separator = reader.take()
            if separator == b"]": break
            need(separator == b",", "PAPER_EXTENSION_CANDIDATE_ARRAY_CHANGED")
            reader.white()
    need(len(starts) == 1, "PAPER_EXTENSION_ORIGINAL_CANDIDATE_NOT_UNIQUE")
    with verified(ref).open("rb") as stream:
        stream.seek(starts[0]); reader = _parser_type()(stream); reader.base = starts[0]
        return reader.metadata_fields({"candidate_id", "specification", "scientific_tuple_sha256"})


def completed_calendar(paths, as_of):
    """Use the existing daily/calendar component and its frozen rules verbatim."""
    from datetime import date
    from scripts.daily_recommendation_inputs import latest_completed_session
    clock = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    need(clock.tzinfo is not None, "PAPER_EXTENSION_ASOF_CLOCK_REQUIRED")
    config = projected_metadata(reference(paths.repo_root / "config/research_governance/a2_forward_shadow_unified_r1.json"),
        ("production_binding_manifest", "production_binding_sha256"))
    binding_ref = dict(path=config["production_binding_manifest"], sha256=config["production_binding_sha256"])
    calendar_ref = projected_metadata(binding_ref, ("path", "sha256"), ("readiness_sources", "trading_calendar"))
    binding = dict(readiness_sources=dict(trading_calendar=calendar_ref))
    result = latest_completed_session(binding, clock)
    contract_path = verified(calendar_ref)
    provider_ref = reference(contract_path.parents[2] / "scripts/v22/forward_shadow/trading_calendar.py")
    provider_module = load_original_owner(provider_ref, "_paper_original_completed_calendar")
    provider = provider_module.ForwardShadowTradingCalendarProvider(contract_path)
    end = result["target_date"]
    state = provider.completed_session_metadata(end, clock.isoformat(), "UTC")
    sessions = [str(d) for d in result["sessions"] if START <= str(d) <= end]
    need(state["target_session_completed"] is True and state["latest_completed_us_session"] == end
         and sessions and sessions[0] == START and sessions[1] == FIRST_EXECUTION
         and PREFIX_END in sessions and PREFIX_END < end < "2027-01-01", "PAPER_EXTENSION_CURRENT_MAIN_CALENDAR_REQUIRED")
    # This is the provider's recorded regular-close rule, not a second session rule.
    close = datetime.combine(date.fromisoformat(end), provider.regular_close, provider.timezone).astimezone(timezone.utc)
    proof = dict(helper=CALENDAR_HELPER, helper_ref=reference(paths.repo_root / "scripts/daily_recommendation_inputs.py"),
        calendar_ref=calendar_ref, provider_ref=provider_ref, production_binding_ref=binding_ref,
        target_session=end, latest_completed_us_session=end, target_session_completed=True,
        session_close_utc=close.isoformat(), as_of_utc=clock.astimezone(timezone.utc).isoformat(),
        main_sessions=sessions, tail_sessions=[d for d in sessions if d > PREFIX_END],
        original_provider_regular_close_rule_retained=True)
    validate_calendar_proof(proof, clock, end)
    return proof


def validate_calendar_proof(proof, as_of, end):
    need(isinstance(proof, dict) and proof.get("helper") == CALENDAR_HELPER
         and proof.get("target_session") == end == proof.get("latest_completed_us_session")
         and proof.get("target_session_completed") is True, "PAPER_EXTENSION_COMPLETED_CALENDAR_PROOF_REQUIRED")
    clock = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    close = datetime.fromisoformat(str(proof["session_close_utc"]).replace("Z", "+00:00"))
    need(clock.tzinfo is not None and close.tzinfo is not None and close <= clock,
         "PAPER_EXTENSION_COMPLETED_CALENDAR_CLOCK_INVALID")
    sessions = proof.get("main_sessions"); tail = proof.get("tail_sessions")
    need(isinstance(sessions, list) and len(sessions) >= 3 and sessions == sorted(set(sessions))
         and sessions[0] == START and sessions[1] == FIRST_EXECUTION and sessions[-1] == end
         and PREFIX_END in sessions and PREFIX_END < end < "2027-01-01"
         and isinstance(tail, list) and tail == [d for d in sessions if d > PREFIX_END],
         "PAPER_EXTENSION_COMPLETED_SESSION_KEYS_INVALID")
    for key in ("calendar_ref", "helper_ref", "provider_ref", "production_binding_ref"):
        verified(proof[key])
    return proof


def original_metadata(candidate_id):
    """Project immutable source/economics metadata, never a result record."""
    keys = ("research_id", "runtime_bootstrap_ref", "account", "execution_friction", "source_bundle_ref", "schedule_ref")
    r7 = projected_metadata(R7_RELEASE, (*keys, "original_top100_inference_ref", "original_account_helpers_ref", "quote_helper_ref"))
    if candidate_id in ROOT_RELEASES:
        ref = ROOT_RELEASES[candidate_id]; release = projected_metadata(ref, keys)
        row = selected_rows(ref, "candidate_bindings", candidate_id)
        request = dict(schema="REMAINING10_DESCRIPTIVE_AUTHORITY_REF_R1", task_id="A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1",
            research_id=release["research_id"], root_release_ref=ref, window_id="MAIN")
        inference_ref = r7["original_top100_inference_ref"]
        inference = projected_metadata(inference_ref, ("flags_ref", "flags_read_columns", "account_catalog_ref", "value_outputs", "quote_execution_context", "source_bundle_ref", "new_fit"))
        return dict(candidate=row["specification"], request=request, release=release, release_ref=ref,
            inference=inference, inference_ref=inference_ref, r7_release=r7)
    need(candidate_id == IDS[1], "PAPER_EXTENSION_EXACT_CANDIDATE")
    config = projected_metadata(RIDGE_CONFIG, ("admission_ref", "inventory_ref", "bridge_bundle_ref", "schedule_ref"))
    bridge = projected_metadata(config["bridge_bundle_ref"], ("source_bundle_ref", "flags_output_ref", "account_catalog_ref", "value_outputs_ref", "start", "end"))
    source = projected_metadata(bridge["source_bundle_ref"], ("stage", "start", "end", "bars_ref", "bars_read_columns", "original_consensus_source_bundle_ref"))
    need(source.get("stage") == "ORIGINAL_RAW_COLUMN_READER_VIEW" and source.get("start") == START and source.get("end") == PREFIX_END,
         "PAPER_EXTENSION_ORIGINAL_RIDGE_QUOTE_VIEW_CHANGED")
    scientific_ref = source["original_consensus_source_bundle_ref"]
    science = projected_metadata(scientific_ref, ("universe_variant", "prehistory_ref", "prehistory_calendar_ref"))
    need(science.get("universe_variant") == "CONSENSUS100", "PAPER_EXTENSION_ORIGINAL_RIDGE_SCIENTIFIC_BUNDLE_CHANGED")
    flags = projected_metadata(bridge.get("flags_output_ref", bridge["source_bundle_ref"]), ("flags_ref", "flags_read_columns"))
    ridge_value = projected_metadata(bridge["value_outputs_ref"], ("frame_ref", "sigma", "lineage"), ("outputs", "ridge"))
    row = selected_rows(config["inventory_ref"], "candidates", candidate_id)
    request = dict(schema="A_2026_DESCRIPTIVE_AUTHORITY_REF_R1", task_id="A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1",
        admission_ref=config["admission_ref"], window_id="MAIN")
    inference = dict(**flags, account_catalog_ref=bridge["account_catalog_ref"], value_outputs=dict(ridge=ridge_value),
        source_bundle_ref=scientific_ref, original_quote_reader_ref=bridge["source_bundle_ref"],
        market_source=dict(bars_ref=source["bars_ref"], read_columns=source["bars_read_columns"]),
        prehistory_ref=science["prehistory_ref"], prehistory_calendar_ref=science["prehistory_calendar_ref"])
    return dict(candidate=row["specification"], request=request, release=dict(schedule_ref=config["schedule_ref"]),
        release_ref=RIDGE_CONFIG, inference=inference, inference_ref=config["bridge_bundle_ref"], r7_release=r7)


def metadata_preflight(paths, *, capture_ref, as_of):
    """Identity/clock preflight only: no model, ledger values or raw-price decode."""
    calendar_proof = completed_calendar(paths, as_of); end = calendar_proof["target_session"]
    pointer = paths.daily_root / "A2_consensus_paper/latest.json"
    need(pointer.stat().st_size <= 4096, "PAPER_EXTENSION_SOURCE_POINTER_SIZE")
    publication_ref = json.loads(pointer.read_text(encoding="utf8"))
    document = projected_metadata(publication_ref, ("schema", "signal_date", "decision_as_of", "source_bundle_ref", "flags_ref", "source_extension_ref", "strategy_status", "model_fit_calls"))
    need(document.get("schema") == "CONSENSUS_PAPER_SOURCE_V1" and document.get("signal_date") == end
         and document.get("model_fit_calls") == 0 and all(document.get("strategy_status", {}).get(sid, {}).get("status") == "READY" for sid in IDS),
         "PAPER_EXTENSION_CURRENT_PUBLICATION_NOT_READY")
    stamp = datetime.fromisoformat(document["decision_as_of"].replace("Z", "+00:00"))
    need(stamp <= datetime.fromisoformat(str(as_of).replace("Z", "+00:00")), "PAPER_EXTENSION_SOURCE_AFTER_ASOF")
    capture = projected_metadata(capture_ref, ("end_date", "captured_prices", "events"))
    need(capture.get("end_date") == end, "PAPER_EXTENSION_CAPTURE_CALENDAR_CHANGED")
    for ref in (document["source_bundle_ref"], document["flags_ref"], document["source_extension_ref"], capture["events"], capture["captured_prices"]): verified(ref)
    baselines = {sid: accepted_baseline_refs(sid) for sid in IDS}
    metadata = {sid: original_metadata(sid) for sid in IDS}
    return dict(status="METADATA_PREFLIGHT_READY_NOT_SOURCE_OR_REPLAY_QUALIFICATION", end=end, as_of=as_of,
        publication_ref=publication_ref, document=document, capture_ref=capture_ref, calendar_qualification=calendar_proof,
        baselines=baselines, originals=metadata, model_fit_calls=0, models_loaded=0, ledger_values_decoded=0)


def _tail_proof_chain(document, calendar_proof, as_of):
    import pandas as pd
    from scripts.research.a2.inference import consensus_paper as consumer
    covered = set(); seen = set(); ref = document["source_extension_ref"]
    for _ in range(256):
        key = (ref["path"], ref["sha256"]); need(key not in seen, "PAPER_EXTENSION_SOURCE_PROOF_CYCLE"); seen.add(key)
        head = projected_metadata(ref, ("signal_date", "flags_ref", "prior_source_extension_ref"))
        proof = consumer.validate_extension(ref, head["flags_ref"], document["source_bundle_ref"], pd.Timestamp(head["signal_date"]), pd.Timestamp(as_of))
        covered.update(row["signal_date"] for row in proof["current_day_proofs"])
        ref = proof.get("prior_source_extension_ref")
        if ref is None: break
    else: raise ValueError("PAPER_EXTENSION_SOURCE_CHAIN_BOUND")
    need(set(calendar_proof["tail_sessions"]) <= covered, "PAPER_EXTENSION_TAIL_POOL_PROOFS_REQUIRED")
    return len(seen)


_RUNTIME_SOURCE_ROOT = Path("D:/us-tech-quant-cache/_maintenance/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/remaining10")
_RUNTIME_CUSTODY = {
    IDS[0]: {
        "profile": dict(path=str(_RUNTIME_SOURCE_ROOT / "Cox/engineering_source_custody_r1/frozen_a94_profile.py"), sha256="61ca6ae1fcb60b4fe77457c759aff55e500ad23e13f9d0c9dccbfca65e34ede2"),
        "remaining10_profile": dict(path=str(_RUNTIME_SOURCE_ROOT / "Cox/engineering_source_custody_r1/remaining10_profile.py"), sha256="ea181aa0435c0bd41f344b266e441e07a81dc07d0b88c91d4e8d0223a0a03e64"),
    },
    IDS[2]: {
        "profile": dict(path=str(_RUNTIME_SOURCE_ROOT / "R7/source_history_before_numeric_calendar_R1/frozen_a94_profile.py.source"), sha256="27f3029f5fb81c4eccbab53ae70c10a20999b97da367a0eebe240b5114c98ade"),
        "remaining10_profile": dict(path=str(_RUNTIME_SOURCE_ROOT / "R7/source_history_before_numeric_calendar_R1/remaining10_profile.py.source"), sha256="679d43d3ed5d1a188110f3bc790d3f9a468033b222b46c2ce9ff6ab9b1546b32"),
    },
}
_RUNTIME_NAMES = {"profile": "scripts.research.a2.evaluation.frozen_a94_profile", "remaining10_profile": "scripts.research.a2.evaluation.remaining10_profile"}


@contextmanager
def original_runtime_custody(meta):
    """Execute exact candidate bytes in a finite, fully restored namespace.

    A module's actual origin remains the custody file. Only function-global
    logical paths and the tiny original _owners namespace seam retain declared
    paths, so unchanged original directory/path guards continue to run. The two
    original physical pins are rebound to exact bytes, never to current bytes.
    """
    import importlib
    import importlib.util
    from importlib.machinery import SourceFileLoader
    import sys
    from scripts.research.a2.evaluation import frozen_test_authority as common
    sid = meta["candidate"]["candidate_id"]
    if sid == IDS[1]:
        yield None
        return
    need(sid in _RUNTIME_CUSTODY and meta["release_ref"] == ROOT_RELEASES[sid], "PAPER_EXTENSION_EXACT_RUNTIME_RELEASE_REQUIRED")
    pinned = projected_metadata(meta["release_ref"], ("runtime_source_refs",))["runtime_source_refs"]
    mappings, modules, namespaces, previous, parent_values = {}, {}, {}, {}, {}
    parent = importlib.import_module("scripts.research.a2.evaluation")
    for key, name in _RUNTIME_NAMES.items():
        declared, custody = pinned[key], _RUNTIME_CUSTODY[sid][key]
        expected_path = Path(__file__).with_name(name.rsplit(".", 1)[1] + ".py").resolve()
        need(Path(declared["path"]).resolve() == expected_path and declared["sha256"] == custody["sha256"],
             "PAPER_EXTENSION_RUNTIME_VERSION_SPLICE")
        origin = verified(custody)
        body = origin.read_bytes()
        tree = ast.parse(body, filename=str(origin))
        need(not any(isinstance(node, ast.ClassDef) for node in tree.body), "PAPER_EXTENSION_RUNTIME_NAMESPACE_ABI_CHANGED")
        namespace = dict(__name__=name, __package__=name.rsplit(".", 1)[0], __file__=str(expected_path))
        # Original statements/function bodies execute unmodified from verified bytes.
        exec(compile(tree, str(origin), "exec"), namespace)
        module = ModuleType(name)
        module.__dict__.update(namespace)
        module.__file__ = str(origin)
        module.__spec__ = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(origin)))
        module._paper_declared_logical_source_path = str(expected_path)
        modules[key], namespaces[key] = module, namespace
        mappings[declared["path"]] = dict(original_ref=declared, custody_ref=custody,
            actual_origin=str(origin), function_global_logical_path=str(expected_path),
            original_algorithm_ast_sha256=hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest(),
            original_algorithm_ast_unchanged=True, main_source_observed_ref=reference(expected_path))
        previous[name] = importlib.import_module(name)
        parent_values[name] = getattr(parent, name.rsplit(".", 1)[1])
    physical = common._physical
    def exact_physical(ref):
        key = ref.get("path") if isinstance(ref, dict) and isinstance(ref.get("path"), str) else None
        if key in mappings:
            binding = mappings[key]
            need(ref == binding["original_ref"], "PAPER_EXTENSION_RUNTIME_VERSION_SPLICE")
            return physical(binding["custody_ref"])
        return physical(ref)
    original_owners = namespaces["remaining10_profile"]["_owners"]
    logical_profile = SimpleNamespace(**namespaces["profile"])
    def scoped_owners():
        profile, authority = original_owners()
        need(profile is modules["profile"] and authority is common, "PAPER_EXTENSION_RUNTIME_NAMESPACE_CHANGED")
        return logical_profile, authority
    namespaces["remaining10_profile"]["_owners"] = scoped_owners
    modules["remaining10_profile"]._owners = scoped_owners
    proof = dict(schema="CONSENSUS_PAPER_EXACT_RUNTIME_CUSTODY_R1", task_id=TASK, candidate_id=sid,
        original_release_ref=meta["release_ref"], source_mappings=list(mappings.values()),
        actual_module_origins={key:dict(path=module.__file__, spec_origin=module.__spec__.origin) for key,module in modules.items()},
        logical_path_role="DECLARED_ORIGINAL_PIN_FOR_UNCHANGED_GUARDS_NOT_CURRENT_MAIN_BYTES",
        namespace_owner_hook="remaining10_profile._owners:original_call_then_verified_logical_profile_view",
        other_physical_references_use_unchanged_original_guard=True,
        restoration_policy="FINALLY_RESTORE_TWO_MODULE_ALIASES_PARENT_ATTRIBUTES_AND_PHYSICAL_GUARD",
        historical_strict_pit_claim=False, execution_admission_inherited=False, model_fit_calls=0,
        broker_action_allowed=False)
    try:
        for key, name in _RUNTIME_NAMES.items():
            sys.modules[name] = modules[key]
            setattr(parent, name.rsplit(".", 1)[1], modules[key])
        common._physical = exact_physical
        yield proof
    finally:
        common._physical = physical
        for name, module in previous.items():
            sys.modules[name] = module
            setattr(parent, name.rsplit(".", 1)[1], parent_values[name])
        need(common._physical is physical and all(sys.modules[name] is module for name,module in previous.items())
            and all(getattr(parent,name.rsplit(".",1)[1]) is value for name,value in parent_values.items()),
            "PAPER_EXTENSION_RUNTIME_RESTORE_FAILED")


def runtime_custody_receipt(paths, proof):
    if proof is None: return None
    from scripts.common.storage_paths import assert_safe_output_path
    payload = canonical(proof) + "\n"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    output = paths.results_root / "_maintenance" / TASK / "source_compatibility" / proof["candidate_id"] / (digest + ".json")
    assert_safe_output_path(output, paths=paths, kind="results")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists(): need(output.read_text(encoding="utf8") == payload, "PAPER_EXTENSION_CUSTODY_RECEIPT_CHANGED")
    else: output.write_text(payload, encoding="utf8")
    return reference(output)


def original_authority_preflight(paths):
    """Validate exact source capabilities without model/ledger decode."""
    from scripts.research.a2.evaluation import frozen_test_authority as old
    results = []
    for sid in IDS:
        meta = original_metadata(sid)
        with original_runtime_custody(meta) as custody:
            admitted = _original_authority(meta)
            admitted = (_ridge_policy if type(admitted) is RidgeOriginalSourceScope else old.validate_descriptive_policy)(admitted, (meta["candidate"],))
            need(str(admitted.start.date()) == START and str(admitted.end.date()) == PREFIX_END,
                 "PAPER_EXTENSION_ORIGINAL_WINDOW_REQUIRED")
            results.append(dict(candidate_id=sid, start=START, end=PREFIX_END, status=("FINITE_RIDGE_SOURCE_AND_POLICY_QUALIFIED" if type(admitted) is RidgeOriginalSourceScope else "ORIGINAL_AUTHORITY_AND_POLICY_QUALIFIED"),
                runtime_custody_ref=runtime_custody_receipt(paths,custody)))
    return dict(status="THREE_SOURCE_CAPABILITIES_QUALIFIED_NO_MODEL_OR_REPLAY", candidates=results,
        model_fit_calls=0, models_loaded=0, account_replays=0, ledger_rows_decoded=0, broker_action_allowed=False)


def _original_authority(meta):
    from scripts.research.a2.evaluation.frozen_test_authority import load_descriptive_authority
    if meta["candidate"].get("candidate_id")==IDS[1]:
        return _ridge_source_authority(meta)
    if meta["release"].get("runtime_bootstrap_ref"):
        bootstrap = load_original_owner(meta["release"]["runtime_bootstrap_ref"], "_paper_original_runtime_bootstrap")
        bootstrap.bootstrap(meta["release"]["research_id"]); bootstrap.assert_bound(meta["release"]["research_id"])
    return load_descriptive_authority(meta["request"])


def qualified_inputs(paths, preflight, *, ca_receipt_refs=()):
    """Qualify raw quotes/CA/pool/clock before any frozen predictor is loaded."""
    from scripts.research.a2.inference import consensus_paper as consumer
    end, clock = preflight["end"], preflight["as_of"]
    doc, publication = consumer.load_publication(paths, end, clock)
    need(publication == preflight["publication_ref"], "PAPER_EXTENSION_CURRENT_PUBLICATION_CHANGED")
    chain_count = _tail_proof_chain(doc, preflight["calendar_qualification"], clock)
    original = _original_authority(preflight["originals"][IDS[2]])
    r7 = preflight["originals"][IDS[2]]
    quote = load_original_owner(r7["r7_release"]["quote_helper_ref"], "_paper_original_quote_helper")
    context, source = quote.accepted_quotes(original, "TOP100", doc["source_bundle_ref"],
        r7["inference"]["quote_execution_context"], check_schema=True)
    bars, quote_proof, quote_ref = prepare_raw_quote_extension(paths, original_market_ref=source["bars_ref"],
        flags_ref=doc["flags_ref"], capture_ref=preflight["capture_ref"], as_of=clock,
        calendar_qualification=preflight["calendar_qualification"], document=doc, baselines=preflight["baselines"], ca_receipt_refs=ca_receipt_refs)
    return dict(document=doc, bars=bars, quote_proof=quote_proof, quote_receipt_ref=quote_ref,
        quote_execution_context=context, original_market_source=source, proof_chain_count=chain_count)


def _prepare_candidate(paths, sid, preflight, qualified, runtime_custody_ref=None):
    import numpy as np
    import pandas as pd
    from scripts.research.a2.inference import consensus_paper as consumer, frozen_a94_state as state, stateful_test_inputs as inputs
    from scripts.research.a2.training import stateful_replay as replay
    meta = preflight["originals"][sid]; original = _original_authority(meta)
    candidate = meta["candidate"]; inference = meta["inference"]
    if "market_source" in inference:
        need(inference["market_source"]["bars_ref"] == qualified["original_market_source"]["bars_ref"],
             "PAPER_EXTENSION_ORIGINAL_RIDGE_QUOTES_NOT_IDENTICAL")
    helper = load_original_owner(meta["r7_release"]["original_account_helpers_ref"], "_paper_original_account_helpers")
    catalog = projected_account_catalog(inference["account_catalog_ref"])
    if type(original) is RidgeOriginalSourceScope:
        account_inputs,account_receipt=guard_projection(helper.account_inputs,
            authority=SimpleNamespace(validate_reconstructed_accounting_events=_ridge_original_accounting))
        account,source_kwargs=account_inputs(catalog,original)
    else:
        account, source_kwargs = helper.account_inputs(catalog, original)
    friction = candidate["execution_friction"]
    schedule = projected_metadata(meta["release"]["schedule_ref"], ("common_sessions",))
    main_sessions = preflight["calendar_qualification"]["main_sessions"]
    need([d for d in main_sessions if d <= PREFIX_END] == schedule["common_sessions"], "PAPER_EXTENSION_ORIGINAL_CALENDAR_PREFIX_CHANGED")
    dates = pd.DatetimeIndex(main_sessions)
    refs = dict(current_publication=preflight["publication_ref"], current_flags=qualified["document"]["flags_ref"],
        current_pool_proof=qualified["document"]["source_extension_ref"], original_completion=ACCEPTED_MAIN[sid],
        original_release=meta["release_ref"], original_inference=meta["inference_ref"], original_flags=inference["flags_ref"],
        original_account_catalog=inference["account_catalog_ref"], native_quote_extension=qualified["quote_receipt_ref"],
        native_quotes=qualified["quote_proof"]["quotes_ref"], calendar=preflight["calendar_qualification"]["calendar_ref"])
    if runtime_custody_ref is not None: refs["original_runtime_custody"] = runtime_custody_ref
    if qualified.get("quote_runtime_custody_ref") is not None: refs["original_quote_runtime_custody"] = qualified["quote_runtime_custody_ref"]
    if "original_quote_reader_ref" in inference:
        refs.update(original_quote_reader=inference["original_quote_reader_ref"], original_scientific_bundle=inference["source_bundle_ref"],
                    original_prehistory=inference["prehistory_ref"], original_prehistory_calendar=inference["prehistory_calendar_ref"])
    source_qualification = dict(seal=_SEAL, dates=main_sessions, as_of=pd.Timestamp(preflight["as_of"]).isoformat(), refs=refs,
        calendar_qualification=preflight["calendar_qualification"])
    authority = bind_authority(original, candidates=[candidate], dates=dates, as_of=preflight["as_of"], source_refs=refs,
        qualification_receipt=source_qualification, account=account, friction=friction)
    market_bits = ("is_max_group", "decision_information_present_union", "stock_forecast_input_present", "raw_selector_input_present")
    need(set(market_bits) <= set(inference["flags_read_columns"]), "PAPER_EXTENSION_ORIGINAL_MARKET_FLAG_FIELDS_UNDECLARED")
    columns = list(dict.fromkeys((*state._PRED, *market_bits)))
    original_flags = consumer.bounded_frame(inference["flags_ref"], columns, "signal_date", START, PREFIX_END)
    tail = consumer.bounded_frame(qualified["document"]["flags_ref"], columns, "signal_date", dates[dates > pd.Timestamp(PREFIX_END)][0], preflight["end"])
    flags = pd.concat([original_flags, tail], ignore_index=True)
    # The original input domain is retained; no current auxiliary ticker expands account identities.
    domain = set(qualified["quote_proof"]["original_market_tickers"])
    flags = flags.loc[flags.ticker.isin(domain)].copy()
    need(pd.DatetimeIndex(flags.signal_date.drop_duplicates().sort_values()).equals(dates), "PAPER_EXTENSION_FULL_FLAG_CALENDAR_REQUIRED")
    projected, projection_receipt = guard_projection(inputs.project_window,
        authority=SimpleNamespace(validate_descriptive_input_dates=validate_descriptive_input_dates))
    view = projected(flags, qualified["bars"], dates, authority, values_function=replay._old().values)
    v = inference["value_outputs"]["ridge"]
    packet_frame = consumer.bounded_frame(v["frame_ref"], ["signal_date", "ticker", "prediction", "prediction_qualified"], "signal_date", START, PREFIX_END)
    packets = helper.values_for(dict(value_outputs=dict(ridge=dict(frame=packet_frame, sigma=v["sigma"], lineage=v["lineage"]))), view, {"ridge"})
    for packet in packets.values():
        packet["lineage"][dates > pd.Timestamp(PREFIX_END)] = "RAW_REFERENCE_UNUSED_VALUE_CARRIER_NO_NEW_RIDGE_INFERENCE"
    need(candidate["action"] == "raw" and candidate["gross"] == "fixed" and candidate.get("forecast", "none") == "none",
        "PAPER_EXTENSION_UNUSED_VALUE_PACKET_ONLY")
    prepared = dict(**view, packets=packets, account=account, account_source_kwargs=source_kwargs,
        candidates=[candidate], execution_friction=friction, source_refs=refs, authority=authority,
        projection_receipts=[projection_receipt]+([account_receipt] if type(original) is RidgeOriginalSourceScope else []), helper=helper)
    return prepared, flags



def _account_quality_failure_diagnostic(qualification, *, candidate_id, end, as_of, owner_ref):
    """Bounded display of original checks only; no values or guards recomputed."""
    names = ("accounting_qualified", "quote_qualified", "certified_NAV_all_window_finite", "cash_identity_correct", "entitlement_identity_correct",
        "complete_dates", "fresh_initial_nav", "no_initial_fills", "no_initial_positions")
    original_groups = qualification.get("groups", {})
    groups = {name: original_groups[name] for name in names if type(original_groups.get(name)) is bool}
    checks = qualification.get("owner_checks", {})
    count_names = ("full_window_sessions", "stale_holding_rows", "stale_holding_days", "unknown_holding_rows",
        "open_stale_sessions", "open_unknown_sessions", "actual_CA_exception_rows")
    counts = {name: checks[name] for name in count_names if type(checks.get(name)) is int and 0 <= checks[name] <= 10**9}
    details = {}; remaining = 20; strings_truncated = False
    limits = {"date":64, "effective_date":64, "ticker":128, "path_id":128, "reason":256}
    for name in ("stale_keys", "unknown_keys", "accounting_exception_keys"):
        rows = checks.get(name, [])
        if type(rows) is not list: continue
        selected = []
        for row in rows[:remaining]:
            if type(row) is not dict: continue
            item = {}
            for field, limit in limits.items():
                value = row.get(field)
                if field in ("date", "effective_date") and isinstance(value, datetime): value = value.isoformat()
                if isinstance(value, str):
                    strings_truncated = strings_truncated or len(value) > limit
                    item[field] = value[:limit]
            selected.append(item)
        remaining -= len(selected)
        details[name] = dict(total=len(rows), keys=selected, truncated=len(selected) < len(rows))
    bound_owner = {name: owner_ref[name] for name in ("path", "sha256")
        if isinstance(owner_ref.get(name), str) and len(owner_ref[name]) <= (1024 if name == "path" else 64)}
    payload = dict(event="ORIGINAL_ACCOUNT_QUALIFICATION_FAILED", candidate_id=candidate_id[:128], end=str(end)[:32], as_of=str(as_of)[:64],
        original_quality_owner_ref=bound_owner, groups=groups, failed_groups=[name for name in names if groups.get(name) is False],
        all_passed=qualification["all_passed"] if type(qualification.get("all_passed")) is bool else None,
        owner_counts=counts, owner_keys=details, detail_strings_truncated=strings_truncated,
        model_fit_calls=0, broker_action_allowed=False)
    encoded = canonical(payload)
    if len(encoded.encode("utf8")) + 2 > 16384:
        payload["owner_keys"] = {name:{**value, "keys":[], "truncated":value["total"] > 0} for name,value in details.items()}
        payload["key_details_omitted_for_output_bound"] = True
        encoded = canonical(payload)
    return encoded


def run_qualified_main(paths, *, capture_ref=None, as_of, execute=False, auto=False, ca_receipt_refs=()):
    """Reusable, full-prefix zero-fit driver; publish all three only after qualification."""
    if auto:
        calendar_proof = completed_calendar(paths, as_of)
        ready = already_current(paths, calendar_proof, as_of)
        if ready is not None: return ready
        if capture_ref is None: capture_ref = resolve_current_capture(paths, calendar_proof)
    need(capture_ref is not None, "PAPER_EXTENSION_CURRENT_CAPTURE_REF_REQUIRED")
    preflight = metadata_preflight(paths, capture_ref=capture_ref, as_of=as_of)
    if not execute:
        return {k: v for k, v in preflight.items() if k not in ("originals", "document", "baselines")}
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.common.daily_support import single_update
    import pandas as pd
    check_resources("AFTER_METADATA_BEFORE_SOURCE_AND_LOCK")
    with single_update(paths.daily_root / "A2_today_recommendation"):
        with original_runtime_custody(preflight["originals"][IDS[2]]) as custody:
            qualified = qualified_inputs(paths, preflight, ca_receipt_refs=ca_receipt_refs)
            qualified["quote_runtime_custody_ref"] = runtime_custody_receipt(paths, custody)
        completions = {}
        for sid in IDS:
            with original_runtime_custody(preflight["originals"][sid]) as custody:
                check_resources("BEFORE_CANDIDATE_PREPARATION", candidate_id=sid)
                prepared, flags = _prepare_candidate(paths, sid, preflight, qualified, runtime_custody_receipt(paths, custody))
                value = prepared["authority"]; model_refs = {}
                if sid == IDS[2]:
                    grid, model_refs, native_trace = forward_r7(paths, flags, prepared["market"].dates, value,include_native_trace=True)
                    result, frames, projections = execute_prepared(prepared, value, gross_calendar=grid,native_trace=native_trace,native_model_refs=model_refs)
                    del grid,native_trace
                else:
                    bundle = consumer.metadata(qualified["document"]["source_bundle_ref"], ("prehistory_ref", "prehistory_calendar_ref"))
                    if sid == IDS[1]:
                        native = original_metadata(sid)["inference"]
                        bundle = {key: native[key] for key in ("prehistory_ref", "prehistory_calendar_ref")}
                    from scripts.research.a2.inference.frozen_a94_state import _PRED
                    prior = consumer.bounded_frame(bundle["prehistory_ref"], _PRED, "signal_date", "2023-01-01", "2025-12-31")
                    old_calendar = consumer.bounded_frame(bundle["prehistory_calendar_ref"], ["trade_date"], "trade_date", "2023-01-01", "2025-12-31")
                    calendar = pd.DatetimeIndex(old_calendar.trade_date).append(prepared["market"].dates)
                    prefix = pd.concat([prior, flags], ignore_index=True); del prior
                    roles = full_r10_roles(prefix, calendar, value.end); del prefix, old_calendar
                    packets, model_refs = forward_r10(paths, sid, roles, value); del roles
                    result, frames, projections = execute_prepared(prepared, value, action_packets=packets)
                    del packets
                qualification = prepared["helper"].quality(result, frames, sid, prepared["market"].dates)
                if qualification["all_passed"] is not True:
                    print(_account_quality_failure_diagnostic(qualification, candidate_id=sid, end=preflight["end"], as_of=preflight["as_of"],
                        owner_ref=preflight["originals"][sid]["r7_release"]["original_account_helpers_ref"]), flush=True)
                need(qualification["all_passed"] is True, "PAPER_EXTENSION_ORIGINAL_ACCOUNT_QUALIFICATION_FAILED:" + sid)
                # Quality is the unchanged original owner, not a new return threshold.
                projections += prepared["projection_receipts"]
                projections.append(dict(owner_ref=reference(prepared["helper"].__file__), function="quality", all_passed=True, model_refs=model_refs))
                _, completions[sid] = publish_verified(paths, candidate_id=sid, frames=frames,
                    baseline_refs=preflight["baselines"][sid], authority=value, source_refs=prepared["source_refs"], projection_receipts=projections)
                del prepared, flags, result, frames, value, model_refs; gc.collect()
        manifest, ref = publish_manifest(paths, completions)
        return dict(status=manifest["status"], end=manifest["end"], manifest_ref=ref, model_fit_calls=0,
            candidate_ids=list(IDS), independent_holdout_claim=False, broker_action_allowed=False)


def _selected_capture_refs(manifest_ref):
    from scripts.common.json_projection import _parser_type
    result = []
    with verified(manifest_ref).open("rb") as stream:
        reader = _parser_type()(stream); reader.descend(("source_refs",)); reader.expect(b"["); reader.white()
        count = 0
        while reader.peek() != b"]":
            row = reader.metadata_fields({"path", "sha256"}); count += 1
            need(count <= 30000, "PAPER_EXTENSION_CAPTURE_REFERENCE_BOUND")
            if Path(row.get("path", "")).name == "three_strategy_price_inputs.json": result.append(row)
            reader.white(); separator = reader.take()
            if separator == b"]": break
            need(separator == b",", "PAPER_EXTENSION_CAPTURE_REFERENCE_ARRAY_CHANGED"); reader.white()
    return result


def resolve_current_capture(paths, calendar_proof):
    """Use the accepted HGB manifest's source refs; never discover runs by mtime."""
    policy_config = paths.repo_root / "config/research_governance/selected_hgb_policy.json"
    relative = "A2_selected_hgb/latest.json"
    if policy_config.is_file():
        setting = projected_metadata(reference(policy_config), ("policy_id", "package_relative_path"))
        need(setting.get("package_relative_path") in ("A2_selected_hgb/latest.json", "A2_selected_hgb/direct_hgb_r1/latest.json"),
             "PAPER_EXTENSION_SELECTED_PACKAGE_OWNER_CHANGED")
        relative = setting["package_relative_path"]
    package_ref = reference(paths.daily_root / relative)
    manifest_ref = projected_metadata(package_ref, ("path", "sha256"), ("performance_extension", "manifest"))
    bound = projected_metadata(package_ref, ("path", "sha256"), ("source_refs", "performance_extension/manifest"))
    need(bound == manifest_ref, "PAPER_EXTENSION_SELECTED_MANIFEST_NOT_BOUND")
    identity = projected_metadata(manifest_ref, ("source_id", "model_fit_calls", "broker_action_allowed"))
    need(identity == dict(source_id="NEW_PIT_COMPARISON", model_fit_calls=0, broker_action_allowed=False),
         "PAPER_EXTENSION_SELECTED_CAPTURE_OWNER_REQUIRED")
    candidates = _selected_capture_refs(manifest_ref); matching = {}
    for ref in candidates:
        value = projected_metadata(ref, ("end_date", "captured_prices", "events"))
        if value.get("end_date") == calendar_proof["target_session"]:
            matching[(str(Path(ref["path"]).resolve()), ref["sha256"])] = ref
    need(len(matching) == 1, "PAPER_EXTENSION_CURRENT_CLOSED_CAPTURE_NOT_UNIQUE")
    return next(iter(matching.values()))


def already_current(paths, calendar_proof, as_of):
    """Hash-bound same-input fast path: no model imports or ledger decode."""
    pointer = paths.daily_root / "A2_consensus_paper/MAIN_extension_latest.json"
    if not pointer.is_file(): return None
    need(pointer.stat().st_size <= 4096, "PAPER_EXTENSION_PUBLICATION_POINTER_SIZE")
    ref = json.loads(pointer.read_text(encoding="utf8"))
    manifest = projected_metadata(ref, ("schema", "status", "candidate_ids", "window_id", "start", "first_execution_date", "prefix_end", "end", "as_of",
        "calendar_qualification", "model_fit_calls", "selection_using_2026", "independent_holdout_claim", "broker_action_allowed", "extensions"))
    need(manifest.get("schema") == "CONSENSUS_FIXED_MAIN_PAPER_EXTENSION_MANIFEST_R1" and manifest.get("status") == "PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION"
         and manifest.get("candidate_ids") == list(IDS) and manifest.get("window_id") == "MAIN"
         and manifest.get("start") == START and manifest.get("first_execution_date") == FIRST_EXECUTION and manifest.get("prefix_end") == PREFIX_END
         and manifest.get("model_fit_calls") == 0 and all(manifest.get(key) is False for key in ("selection_using_2026", "independent_holdout_claim", "broker_action_allowed")),
         "PAPER_EXTENSION_PREVIOUS_MANIFEST_CHANGED")
    validate_calendar_proof(manifest["calendar_qualification"], manifest["as_of"], manifest["end"])
    need(datetime.fromisoformat(manifest["as_of"].replace("Z", "+00:00")) <= datetime.fromisoformat(str(as_of).replace("Z", "+00:00")),
         "PAPER_EXTENSION_PREVIOUS_MANIFEST_AFTER_ASOF")
    if manifest["end"] != calendar_proof["target_session"]: return None
    source_pointer = paths.daily_root / "A2_consensus_paper/latest.json"
    need(source_pointer.stat().st_size <= 4096, "PAPER_EXTENSION_SOURCE_POINTER_SIZE")
    current_publication = json.loads(source_pointer.read_text(encoding="utf8")); verified(current_publication)
    need(set(manifest["extensions"]) == set(IDS), "PAPER_EXTENSION_PREVIOUS_GROUP_INCOMPLETE")
    for sid, completion in manifest["extensions"].items():
        receipt = projected_metadata(completion, ("schema", "candidate_ids", "end", "source_refs", "artifacts", "baseline_artifacts", "original_prefix_comparison", "stock_prefix_comparison"))
        need(receipt.get("schema") == SCHEMA and receipt.get("candidate_ids") == [sid] and receipt.get("end") == manifest["end"]
             and receipt.get("baseline_artifacts") == accepted_baseline_refs(sid)
             and receipt.get("original_prefix_comparison", {}).get("status") == "EXACT_MATCH"
             and receipt.get("stock_prefix_comparison", {}).get("status") == "EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY"
             and set(receipt.get("artifacts", {})) == set(LEDGER_TABLES), "PAPER_EXTENSION_PREVIOUS_COMPLETION_CHANGED")
        for artifact in receipt["artifacts"].values(): verified(artifact)
        if receipt.get("source_refs", {}).get("current_publication") != current_publication: return None
    return dict(status="ALREADY_CURRENT_PREFIX_VERIFIED", end=manifest["end"], manifest_ref=ref,
        candidate_ids=list(IDS), model_fit_calls=0, models_loaded=0, account_replays=0,
        ledger_values_decoded=0, broker_action_allowed=False)


def main(argv=None):
    import argparse
    from scripts.common.storage_paths import resolve
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-ref", help="JSON {path,sha256} of current three_strategy_price_inputs.json")
    parser.add_argument("--ca-receipt-ref", action="append", default=[], help="JSON path/sha256 of an independent current native get_rehab receipt; no provider requests occur here")
    parser.add_argument("--auto", action="store_true", help="Resolve the current accepted capture; same-date same-input publication skips all model work")
    parser.add_argument("--as-of", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--execute", action="store_true", help="Run original zero-fit MAIN replay after metadata/source qualification")
    args = parser.parse_args(argv)
    try:
        result = run_qualified_main(resolve(), capture_ref=json.loads(args.capture_ref) if args.capture_ref else None,
            as_of=args.as_of, execute=args.execute, auto=args.auto, ca_receipt_refs=[json.loads(r) for r in args.ca_receipt_ref])
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(canonical(dict(status="BLOCKED", reason=str(exc), error_type=type(exc).__name__,
            model_fit_calls=0, broker_action_allowed=False)))
        return 2
    print(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
