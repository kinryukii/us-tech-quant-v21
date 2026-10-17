"""Current paper consumer of explicit frozen TOP100 strategy capabilities.

No fits, research account execution, outcome reads or changes to historical
admission. Pool source, input clock and frozen state are separately bound here.
The mathematical encoders, cohort builder, predictor and action decoder retain
original ownership. Models are loaded one head at a time and released.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import gc
import hashlib
import json
import ctypes
import weakref

POOL = "FIXED_TRACKED_MANAGER_CONSENSUS_TOP100_INSTITUTION_COUNT_THEN_SUM_PORTFOLIO_WEIGHTS_THEN_CUSIP"
SCHEMA = "CONSENSUS_PAPER_SOURCE_V1"
NEW_IDS = ("R10_DIRECT_MEAN4_ELASTICNET_MID", "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR")
# Current-paper capability is separate from the original MAIN/v1 membership.
PAPER_CURRENT_IDS = (*NEW_IDS, "R6_DURATION_TREE")
TASK = "A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1"
RUN = "20261010T155614+0000_8a89315b"
RIDGE_RUN = "V24_A_STATEFUL_ACTION_RISK_FULL_BREADTH_R10/20261003T202647+0000_977bc52d"
BUNDLE_SHA = "237f56ef00af728a623673fe0514b07223f0e4c1f6975b17b521d7dfb8296fe0"
OLD_STATES_SHA = "84d2f4a644d1fdfae4f6954a3751be3bc156ec0141f537dbf64cdb55a0bf25a9"
ELASTIC_CLOSURE_SHA = "90e8197fb6f6cc282e51d4efe601368e3d8ab5bd80e40e1ea47668ec729f1ec8"
R7_CLOSURE_SHA = "700d2991fed512629668d56c5285d430728d31ed51289863d7366616b9e32eac"
FORBIDDEN = {"target", "y", "y_open5", "label_value", "label_mature_date", "label_available", "edge", "basket_y"}


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def reference(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": digest}


def verify(ref):
    need(isinstance(ref, dict) and reference(ref["path"])["sha256"] == ref["sha256"], "CONSENSUS_SOURCE_HASH_CHANGED")
    return Path(ref["path"])


def metadata(ref, fields):
    from scripts.common.json_projection import metadata_fields
    with verify(ref).open("rb") as stream:
        return metadata_fields(stream, set(fields))


def resource_check():
    if __import__("os").name != "nt":
        return
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
            ("total_phys", "avail_phys", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_extended_virtual")]
    item = Memory(); item.length = ctypes.sizeof(item)
    need(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(item)), "CONSENSUS_MEMORY_STATUS_UNAVAILABLE")
    need(item.avail_phys >= 1.5 * 2**30 and item.avail_page >= 8 * 2**30, "CONSENSUS_RESOURCE_FLOOR")


def process_memory():
    """Read this worker's memory only; peak is process-wide, not phase-specific."""
    if __import__("os").name != "nt":
        return {"status": "UNAVAILABLE"}
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("page_fault_count", ctypes.c_ulong)] + [(name, ctypes.c_size_t) for name in
            ("peak_working_set", "working_set", "peak_paged_pool", "paged_pool", "peak_nonpaged_pool", "nonpaged_pool", "pagefile", "peak_pagefile")]
    kernel = ctypes.windll.kernel32; kernel.GetCurrentProcess.restype = ctypes.c_void_p
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    if not query(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return {"status": "UNAVAILABLE"}
    return {"status": "MEASURED", "working_set_bytes": counters.working_set, "process_peak_working_set_bytes": counters.peak_working_set,
            "pagefile_bytes": counters.pagefile, "peak_scope": "CURRENT_WORKER_PROCESS"}


def _release_arrow_cache():
    """Return unused allocator pages after a complete input stage, if loaded."""
    import sys
    pa = sys.modules.get("pyarrow")
    if pa is not None:
        try:
            pa.default_memory_pool().release_unused()
        except Exception:
            # Optional allocator cleanup must never replace the real result/error.
            pass


def bounded_frame(ref, columns, date_column, first, last):
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pandas as pd
    path = verify(ref)
    dataset = ds.dataset(path, format="parquet")
    need(set(columns) <= set(dataset.schema.names), "CONSENSUS_PROJECTED_INPUT_FIELDS_REQUIRED")
    rule = (ds.field(date_column) >= pd.Timestamp(first).to_pydatetime()) & (ds.field(date_column) <= pd.Timestamp(last).to_pydatetime())
    # Dictionary batches can have distinct categories: retain concat's dtype rule.
    dictionary = any(pa.types.is_dictionary(dataset.schema.field(column).type) for column in columns)
    parts = []; count = 0
    batch = table = scanner = None
    try:
        scanner = dataset.scanner(columns=list(columns), filter=rule, batch_size=4096,
            use_threads=False, batch_readahead=1, fragment_readahead=1)
        for batch in scanner.to_batches():
            count += batch.num_rows
            need(count <= 600000, "CONSENSUS_PREFIX_ROW_LIMIT")
            parts.append(batch.to_pandas() if dictionary else batch)
        if not parts:
            return pd.DataFrame(columns=columns)
        if dictionary:
            return pd.concat(parts, ignore_index=True)
        table = pa.Table.from_batches(parts)
        return table.to_pandas(split_blocks=True, use_threads=False).reset_index(drop=True)
    finally:
        # No per-batch trims: keep live output buffers, release only scratch pages.
        parts.clear()
        batch = table = scanner = dataset = None
        _release_arrow_cache()


class _ProxySchemaFallback(Exception):
    pass


class _ScopedProxyRows(list):
    """Retain consumed rows and bounded dtype witnesses; all transitions still run."""
    def __init__(self, prediction, first, last):
        import numpy as np
        import pandas as pd
        from datetime import date, timedelta
        self.np, self.pd = np, pd
        self.temporal_types = (datetime, date, timedelta, np.datetime64, np.timedelta64)
        self.first, self.last = first, last
        self.total, self.ordinals, self.categories = 0, [], {}
        self.columns = None
        self.variable = {name for name, dtype in prediction.dtypes.items()
            if not isinstance(dtype, np.dtype) or dtype.kind not in "bifmM" or dtype.kind == "u"}
        if "raw_a2_rank" in self.variable: self.variable.update(("raw_rank", "rank_change"))
        if "raw_a2_prediction" in self.variable: self.variable.update(("raw_score", "score_change"))

    def category(self, value):
        np, pd = self.np, self.pd
        kind = type(value)
        if value is None or value is pd.NA or value is pd.NaT:
            return (kind,)
        if isinstance(value, (bool, str, bytes, float, np.floating, np.bool_, np.str_, np.bytes_)):
            return (kind,)
        if isinstance(value, (int, np.integer)):
            return (kind, "negative64" if -2**63 <= value < 0 else "positive64" if 0 <= value <= 2**63-1
                else "unsigned64" if 0 <= value <= 2**64-1 else "outside64")
        if isinstance(value, pd.Timestamp):
            return (kind, str(value.tz), getattr(value, "unit", "ns"))
        if isinstance(value, self.temporal_types):
            return (kind, str(getattr(value, "dtype", "")), str(getattr(value, "tzinfo", None)))
        raise _ProxySchemaFallback()

    def append(self, row):
        ordinal = self.total; self.total += 1
        if self.columns is None:
            self.columns = tuple(row)
            if len(self.columns) > 128: raise _ProxySchemaFallback()
        elif tuple(row) != self.columns:
            raise _ProxySchemaFallback()
        witness = ordinal == 0
        for name in self.variable:
            if name not in row: continue
            key = self.category(row[name]); known = self.categories.setdefault(name, set())
            if key not in known:
                known.add(key); witness = True
                if len(known) > 16: raise _ProxySchemaFallback()
        if witness or self.first <= row["signal_date"] <= self.last:
            super().append(row); self.ordinals.append(ordinal)


def scoped_proxy_frame(function, prediction, calendar, first, last, friction_bps=10):
    """Private storage projection of the exact original proxy, never a state reset."""
    import ast
    import inspect
    import textwrap
    import pandas as pd
    from copy import deepcopy
    from scripts.research.a2.training import stateful_mechanism_inputs as owner
    need(function.__code__ is owner.proxy_state.__code__, "CONSENSUS_ORIGINAL_PROXY_OWNER_REQUIRED")
    first, last = pd.Timestamp(first), pd.Timestamp(last)
    need(first.tzinfo is None and last.tzinfo is None and first <= last, "CONSENSUS_PROXY_OUTPUT_SCOPE_REQUIRED")
    original = ast.parse(textwrap.dedent(inspect.getsource(owner.proxy_state)))
    tree = deepcopy(original)
    seams = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
        and len(n.targets) == 1 and ast.unparse(n.targets[0]) == "(active, output)"]
    need(len(seams) == 1 and ast.unparse(seams[0].value) == "({}, [])", "CONSENSUS_PROXY_STORAGE_SEAM_CHANGED")
    seams[0].value.elts[1] = ast.Name(id="_scoped_proxy_rows", ctx=ast.Load())
    restored = deepcopy(tree)
    restored_seam = next(n for n in ast.walk(restored) if isinstance(n, ast.Assign)
        and len(n.targets) == 1 and ast.unparse(n.targets[0]) == "(active, output)")
    restored_seam.value.elts[1] = ast.List(elts=[], ctx=ast.Load())
    need(ast.dump(restored, include_attributes=False) == ast.dump(original, include_attributes=False), "CONSENSUS_PROXY_ALGORITHM_CHANGED")
    rows = _ScopedProxyRows(prediction, first, last)
    namespace = dict(function.__globals__); namespace["_scoped_proxy_rows"] = rows
    exec(compile(ast.fix_missing_locations(tree), inspect.getsourcefile(owner.proxy_state), "exec"), namespace)
    try:
        result = namespace[owner.proxy_state.__name__](prediction, calendar, friction_bps)
    except _ProxySchemaFallback:
        result = None
    finally:
        # The compiled private function must not keep its own globals and row list in a cycle.
        namespace.pop(owner.proxy_state.__name__, None)
        namespace.pop("_scoped_proxy_rows", None)
    if result is None:
        # Release the partial private namespace before unusual schemas use the original path.
        del namespace, rows; gc.collect()
        return function(prediction, calendar, friction_bps)
    selected = [i for i, row in enumerate(rows) if first <= row["signal_date"] <= last]
    if selected:
        begin, end = selected[0], selected[-1] + 1
        ordinal = rows.ordinals[begin]
        need(rows.ordinals[begin:end] == list(range(ordinal, ordinal + end - begin)), "CONSENSUS_PROXY_OUTPUT_ORDINAL_CHANGED")
        result = result.iloc[begin:end]
        result.index = pd.RangeIndex(ordinal, ordinal + len(result))
    else:
        result = result.iloc[:0]; result.index = pd.RangeIndex(0)
    return result


def r10_encoded_input(frame, columns):
    """Same frozen encoder; concatenate performs its identical float64 mask cast."""
    import ast
    import inspect
    import textwrap
    from copy import deepcopy
    from scripts.research.a2.training import stateful_mechanism as owner
    original = ast.parse(textwrap.dedent(inspect.getsource(owner.encode)))
    tree = deepcopy(original)
    seams = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "astype" and ast.unparse(n.func.value) == "np.isnan(raw)"]
    need(len(seams) == 1 and ast.unparse(seams[0]) == "np.isnan(raw).astype(float)", "CONSENSUS_ORIGINAL_ENCODING_SEAM_CHANGED")
    target = seams[0]
    class MaskPromotion(ast.NodeTransformer):
        def visit_Call(self, node):
            return deepcopy(node.func.value) if node is target else self.generic_visit(node)
    tree = MaskPromotion().visit(tree)
    # Reinsert the one removed allocation to verify every original math/guard node.
    restored = deepcopy(tree)
    concatenation = next(n for n in ast.walk(restored) if isinstance(n, ast.Call) and ast.unparse(n.func) == "np.concatenate")
    concatenation.args[0].elts[1] = deepcopy(target)
    need(ast.dump(restored, include_attributes=False) == ast.dump(original, include_attributes=False), "CONSENSUS_ENCODING_ALGORITHM_CHANGED")
    namespace = dict(owner.encode.__globals__)
    exec(compile(ast.fix_missing_locations(tree), inspect.getsourcefile(owner.encode), "exec"), namespace)
    try:
        return namespace[owner.encode.__name__](frame, columns)
    finally:
        namespace.pop(owner.encode.__name__, None)


def original_frames(prefix, calendar, day):
    """Existing pure cohort/ALL-pair kernels, with empty label annotations.

    This current consumer scopes its own date inputs. It never calls or changes
    the old research authority loader, and never claims historical admission.
    """
    import pandas as pd
    from scripts.research.a2.inference import frozen_a94_state as state
    from scripts.research.a2.training import stateful_mechanism_inputs as inputs, stateful_mechanism as mechanism
    from scripts.research.a2.data import state_label_foundation as foundation
    day = pd.Timestamp(day)
    need(calendar[0] == pd.Timestamp("2023-01-03") and calendar[-1] == day and calendar.is_unique and calendar.is_monotonic_increasing,
         "CONSENSUS_ORIGINAL_COHORT_PHASE_REQUIRED")
    need(set(pd.to_datetime(prefix.signal_date)) == set(calendar), "CONSENSUS_FULL_PREFIX_CALENDAR_REQUIRED")
    def dates(values, nullable=False):
        result = pd.to_datetime(values)
        need((nullable or not pd.isna(result).any()) and (not len(result) or pd.DatetimeIndex(result).dropna().max() <= day), "CONSENSUS_FUTURE_INPUT")
        return result
    proxy = state._clone(inputs.proxy_state, _pre2026=dates, _calendar=lambda x: pd.DatetimeIndex(dates(x)))
    projected = scoped_proxy_frame(proxy, prefix, calendar, day, day, 10)
    # proxy_state already owns the original buy/hold partition and all cohort
    # fields. The ALL-pair owner takes identity keys only, before any outcomes.
    today = projected.loc[pd.to_datetime(projected.signal_date).eq(day)].copy()
    keycols = ["signal_date", "ticker", "security_id", "cohort_age_sessions", "raw_rank"]
    keys = {"buy": today.loc[today.entrant.eq(1), keycols], "hold": today.loc[today.entrant.eq(0), keycols]}
    pairs = foundation.all_incumbent_pairs(keys)
    labels = today.iloc[:0][["signal_date", "ticker", "security_id"]].copy()
    labels = labels.assign(label_value=pd.Series(dtype=float), label_qualified=pd.Series(dtype=bool),
                           label_mature_date=pd.Series(dtype="datetime64[ns]"), source_label_identity=pd.Series(dtype=str))
    heads = {name: inputs.attach_single_labels(today, labels, name) for name in ("ENTRY", "INCUMBENT", "CONTINUATION")}
    heads["REPLACE"] = inputs.attach_pair_labels(pairs, today, labels)
    roles = mechanism.structured_action_frame(SimpleNamespace(heads={5: heads}), 5)
    clean = {}
    from scripts.research.a2.inference.frozen_a94_actions import role_features
    ids = ("signal_date", "sample_id", "ticker", "security_id", "cohort_age_sessions", "action_type", "entrant_ticker", "entrant_sid")
    for name in ("ENTRY", "INCUMBENT"):
        frame = roles[name]
        clean[name] = frame[list(dict.fromkeys([c for c in ids if c in frame] + list(role_features("R10:" + name))))].copy()
    return clean


def gross_frame(current, day):
    """Use original R7 full20 aggregation/encoder without reading labels."""
    import pandas as pd
    from scripts.research.a2.training import stateful_decision as decision
    from scripts.research.a2.inference.frozen_a94_state import _clone, _DateInputs
    fn = _clone(decision.build_samples, inputs=_DateInputs(pd.Timestamp(day) + pd.Timedelta(days=1)))
    rows, _ = fn(current, pd.DataFrame(columns=decision.LABEL_COLS), pd.DatetimeIndex([pd.Timestamp(day)]))
    frame = rows["gross"]
    need(len(frame) == 5, "CONSENSUS_R7_COMPLETE_RAW20_REQUIRED")
    return frame[["signal_date", "sample_id", *decision.GROSS]].copy()


def validate_extension(ref, flags_ref, source_bundle_ref, day, clock):
    """Current source proof retains historical limitations and exact pool/model."""
    import pandas as pd
    fields = ("schema", "task_id", "status", "signal_date", "observed_at_utc", "decision_as_of", "source_bundle_ref",
              "parent_flags_ref", "flags_ref", "raw_model_ref", "feature_source_ref", "new_fit", "selection_rule",
              "pool_variant_id", "cohort_count", "current_day_proofs", "parent_source_role",
              "parent_source_completeness_unknown", "parent_historical_available_at_bound", "execution_admission_inherited",
              "continued_flags_ref", "prior_source_extension_ref")
    need(source_bundle_ref.get("sha256") == BUNDLE_SHA, "CONSENSUS_ORIGINAL_TOP100_BUNDLE_REQUIRED")
    proof = metadata(ref, fields)
    need(proof.get("schema") == "CURRENT_CONSENSUS_PAPER_SOURCE_EXTENSION_R1" and proof.get("task_id") == "DEMO_FIVE_STRATEGY_PAPER_20261013_R1"
         and proof.get("status") == "READY" and proof.get("signal_date") == str(day.date()) and proof.get("flags_ref") == flags_ref
         and proof.get("source_bundle_ref") == source_bundle_ref and proof.get("new_fit") == 0
         and proof.get("selection_rule") == "MANAGER_COUNT_WEIGHT_SUM" and proof.get("pool_variant_id") == "TOP100"
         and proof.get("cohort_count") == 25 and proof.get("execution_admission_inherited") is False, "CONSENSUS_CURRENT_SOURCE_PROOF_REQUIRED")
    observed = pd.Timestamp(proof["observed_at_utc"]); decision = pd.Timestamp(proof["decision_as_of"])
    need(observed.tzinfo is not None and decision.tzinfo is not None and decision <= clock and observed <= clock
         and observed >= day.tz_localize("America/New_York") + pd.Timedelta(hours=16), "CONSENSUS_CURRENT_OBSERVATION_CLOCK")
    need(proof["parent_flags_ref"]["sha256"] == "8598030725df0758336ca6e2a7b559f4c203d0d106e1e79a1064437a2b1dfa06"
         and proof["raw_model_ref"]["sha256"] == "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
         and proof["feature_source_ref"]["sha256"] == "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19", "CONSENSUS_FROZEN_SOURCE_MODEL_IDENTITY")
    for key in ("parent_flags_ref", "raw_model_ref", "feature_source_ref"): verify(proof[key])
    continued = proof.get("continued_flags_ref"); previous_ref = proof.get("prior_source_extension_ref")
    need((continued is None) == (previous_ref is None), "CONSENSUS_SOURCE_CHAIN_PAIR_REQUIRED")
    if continued is not None:
        verify(continued)
        previous = metadata(previous_ref, ("schema", "status", "signal_date", "source_bundle_ref", "flags_ref", "cohort_count", "pool_variant_id", "selection_rule", "raw_model_ref", "feature_source_ref", "new_fit"))
        need(previous.get("schema") == proof["schema"] and previous.get("status") == "READY"
             and pd.Timestamp(previous["signal_date"]) < day and previous.get("flags_ref") == continued
             and previous.get("source_bundle_ref") == source_bundle_ref and previous.get("cohort_count") == 25
             and previous.get("pool_variant_id") == "TOP100" and previous.get("selection_rule") == "MANAGER_COUNT_WEIGHT_SUM"
             and previous.get("raw_model_ref") == proof["raw_model_ref"] and previous.get("feature_source_ref") == proof["feature_source_ref"]
             and previous.get("new_fit") == 0, "CONSENSUS_PRIOR_ACCEPTED_SOURCE_CHAIN")
    parent = metadata(source_bundle_ref, ("source_role", "source_completeness_unknown", "historical_available_at_bound"))
    need(all(proof.get("parent_" + key) == parent.get(key) for key in ("source_role", "source_completeness_unknown", "historical_available_at_bound")), "CONSENSUS_PARENT_LIMITATIONS_CHANGED")
    days = proof.get("current_day_proofs", [])
    need(isinstance(days, list) and bool(days) and days[-1]["signal_date"] == str(day.date())
         and len({p["signal_date"] for p in days}) == len(days), "CONSENSUS_CURRENT_DAY_PROOFS")
    for item in days:
        pool = item.get("ordered_pool_security_ids", [])
        ranked = item.get("ranked_pool_security_ids", [])
        unranked = item.get("unranked_pool_security_ids", [])
        need(pd.Timestamp(item["signal_date"]) <= day and isinstance(pool, list) and len(pool) == 100
             and len(set(pool)) == 100 and isinstance(ranked, list) and 40 <= len(ranked) <= 100
             and len(set(ranked)) == len(ranked) and isinstance(unranked, list) and len(set(unranked)) == len(unranked)
             and not set(ranked) & set(unranked) and set(ranked) | set(unranked) == set(pool)
             and item.get("ranked_rows") == len(ranked) and item.get("rows", 0) >= len(ranked)
             and item.get("input_coverage_status") == ("READY" if len(ranked) == 100 else "PARTIAL")
             and bool(item.get("source_snapshot_id")), "CONSENSUS_CURRENT_POOL_ORDER_PROOF")
        verify(item["mapping_ref"]); verify(item["feature_ref"])
        need(item["feature_ref"].get("signal_date") == item["signal_date"]
             and item["feature_ref"].get("feature_source_ref") == proof["feature_source_ref"]
             and item["feature_ref"].get("frozen_model_sha256") == proof["raw_model_ref"]["sha256"], "CONSENSUS_CURRENT_FEATURE_PROOF")
    return proof


def _duration_prefix(paths, base):
    import pandas as pd
    from scripts.research.a2.inference import frozen_a94_state as state
    bundle = metadata(base["source_bundle_ref"], ("prehistory_ref", "prehistory_calendar_ref"))
    columns = list(state._PRED)
    prior = bounded_frame(bundle["prehistory_ref"], columns, "signal_date", "2023-01-01", "2025-12-31")
    current = bounded_frame(base["flags_ref"], columns, "signal_date", "2026-01-01", base["signal_date"])
    cal = bounded_frame(bundle["prehistory_calendar_ref"], ["trade_date"], "trade_date", "2023-01-01", "2025-12-31")
    calendar = pd.DatetimeIndex(pd.to_datetime(cal.trade_date)).append(
        pd.DatetimeIndex(pd.to_datetime(current.signal_date).drop_duplicates().sort_values()))
    return pd.concat([prior, current], ignore_index=True), calendar


def _prepare_duration_frame(paths, base, source, *, prefix=None, calendar=None):
    import pandas as pd
    need(isinstance(source, dict) and source.get("schema") == "CURRENT_R6_PROBE_SOURCE_V1"
         and source.get("signal_date") == base["signal_date"]
         and source.get("flags_ref") == base["flags_ref"] and source.get("source_bundle_ref") == base["source_bundle_ref"],
         "CONSENSUS_DURATION_PRODUCER_REQUIRED")
    clock = pd.Timestamp(source["decision_as_of"])
    need(clock.tzinfo is not None and clock >= pd.Timestamp(base["decision_as_of"]),
         "CONSENSUS_DURATION_SOURCE_PREDATES_BASE")
    if source.get("status") != "READY":
        return dict(status="BLOCKED", reason=source.get("reason") or "CONSENSUS_DURATION_PROBE_SOURCE_BLOCKED",
                    decision_as_of=clock.isoformat())
    try:
        from scripts.research.a2.inference.current_r6_probes import build_current_duration_frame, validate_current_duration_frame
        if prefix is None:
            prefix, calendar = _duration_prefix(paths, base)
        built = build_current_duration_frame(paths, prediction_prefix=prefix, calendar_prefix=calendar,
            signal_date=base["signal_date"], decision_as_of=source["decision_as_of"], r6_probe_source=source)
        validate_current_duration_frame(paths, frame=built["frame"], qualification=built["qualification"],
            r6_probe_source=source, signal_date=base["signal_date"], decision_as_of=source["decision_as_of"])
        return dict(status="READY", decision_as_of=source["decision_as_of"], **built)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return dict(status="BLOCKED", reason=str(exc), decision_as_of=clock.isoformat())


def _duration_source_identity(source):
    return {key: value for key, value in source.items() if key != "decision_as_of"}


def _save_duration_document(path, document):
    body = json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if path.exists():
        need(json.loads(path.read_text(encoding="utf8")) == document, "CONSENSUS_PRESERVE_DURATION_DOCUMENT")
    else:
        path.write_text(body, encoding="utf8")
    return reference(path)


def publish_duration_extension(paths, base, base_ref, source, *, prepared=None):
    """One candidate sidecar; original latest.json and accepted three inputs stay intact."""
    import pandas as pd
    from scripts.common.storage_paths import assert_safe_output_path
    need(isinstance(source, dict) and source.get("schema") == "CURRENT_R6_PROBE_SOURCE_V1"
         and source.get("signal_date") == base["signal_date"]
         and source.get("flags_ref") == base["flags_ref"] and source.get("source_bundle_ref") == base["source_bundle_ref"],
         "CONSENSUS_DURATION_PRODUCER_REQUIRED")
    clock = pd.Timestamp(source["decision_as_of"])
    need(clock.tzinfo is not None and clock >= pd.Timestamp(base["decision_as_of"]),
         "CONSENSUS_DURATION_SOURCE_PREDATES_BASE")
    pointer = paths.daily_root / "A2_consensus_paper/duration_latest.json"
    if pointer.exists():
        previous_ref = json.loads(pointer.read_text(encoding="utf8"))
        previous = json.loads(verify(previous_ref).read_text(encoding="utf8"))
        if (previous.get("schema") == "CURRENT_CONSENSUS_DURATION_SOURCE_V1"
                and previous.get("base_publication_ref") == base_ref
                and _duration_source_identity(previous.get("r6_probe_source", {})) == _duration_source_identity(source)
                and pd.Timestamp(previous["decision_as_of"]) <= clock):
            # Keep the genuine earlier availability clock; never restamp old evidence.
            checked, _ = _load_duration_publication(paths, base, base_ref, source["decision_as_of"])
            if previous["status"] == "READY":
                frame = _qualified_duration_frame(paths, checked); del frame
            return dict(status=previous["status"], publication_ref=previous_ref,
                decision_as_of=previous["decision_as_of"], reused=True, reason=previous.get("reason"))
    prepared = prepared if prepared is not None else _prepare_duration_frame(paths, base, source)
    output = (paths.daily_root / "A2_consensus_paper/inputs" / base["signal_date"]).resolve()
    assert_safe_output_path(output, kind="daily", paths=paths); output.mkdir(parents=True, exist_ok=True)
    document = dict(schema="CURRENT_CONSENSUS_DURATION_SOURCE_V1", candidate_id="R6_DURATION_TREE",
        status=prepared["status"], signal_date=base["signal_date"], decision_as_of=prepared["decision_as_of"],
        pool_contract=POOL, base_publication_ref=base_ref, flags_ref=base["flags_ref"],
        source_bundle_ref=base["source_bundle_ref"], source_extension_ref=base["source_extension_ref"],
        r6_probe_source=source, model_fit_calls=0, execution_admission_inherited=False, historical_strict_pit_claim=False)
    if prepared["status"] == "READY":
        frame, qualification = prepared["frame"], prepared["qualification"]
        identity = hashlib.sha256(json.dumps(qualification["input_commitment"], sort_keys=True).encode()).hexdigest()[:20]
        frame_path = output / ("R6_DURATION_" + identity + ".parquet")
        if frame_path.exists():
            import pandas as pd
            pd.testing.assert_frame_equal(pd.read_parquet(frame_path), frame, check_dtype=True)
        else:
            frame.to_parquet(frame_path, index=False, compression="zstd")
        frame_ref = reference(frame_path)
        input_proof = dict(schema="CURRENT_CONSENSUS_DURATION_INPUT_R1", signal_date=base["signal_date"],
            decision_as_of=prepared["decision_as_of"], input_ref=frame_ref, r6_probe_source=source, qualification=qualification)
        proof_id = hashlib.sha256(json.dumps(input_proof, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()[:20]
        document.update(input_ref=frame_ref,
            qualification_ref=_save_duration_document(output / ("duration_input_" + proof_id + ".json"), input_proof))
    else:
        document.update(reason=prepared.get("reason") or "CONSENSUS_DURATION_INPUT_BLOCKED", input_ref=None, qualification_ref=None)
    identity = hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()[:20]
    pub_ref = _save_duration_document(output / ("duration_publication_" + identity + ".json"), document)
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(json.dumps(pub_ref), encoding="utf8"); temporary.replace(pointer)
    return dict(status=document["status"], publication_ref=pub_ref,
        decision_as_of=document["decision_as_of"], reused=False, reason=document.get("reason"))


def _load_duration_publication(paths, base, base_ref, as_of):
    import pandas as pd
    from scripts.common.storage_paths import assert_safe_output_path
    pointer = paths.daily_root / "A2_consensus_paper/duration_latest.json"
    need(pointer.exists(), "CONSENSUS_DURATION_PUBLICATION_REQUIRED")
    ref = json.loads(pointer.read_text(encoding="utf8")); path = verify(ref)
    assert_safe_output_path(path, kind="daily", paths=paths)
    document = json.loads(path.read_text(encoding="utf8"))
    need(document.get("schema") == "CURRENT_CONSENSUS_DURATION_SOURCE_V1"
         and document.get("candidate_id") == "R6_DURATION_TREE" and document.get("status") in ("READY", "BLOCKED")
         and document.get("signal_date") == base["signal_date"] and document.get("pool_contract") == POOL
         and document.get("base_publication_ref") == base_ref and document.get("flags_ref") == base["flags_ref"]
         and document.get("source_bundle_ref") == base["source_bundle_ref"]
         and document.get("source_extension_ref") == base["source_extension_ref"]
         and document.get("r6_probe_source", {}).get("flags_ref") == base["flags_ref"]
         and document.get("r6_probe_source", {}).get("source_bundle_ref") == base["source_bundle_ref"]
         and document.get("r6_probe_source", {}).get("signal_date") == base["signal_date"]
         and document.get("r6_probe_source", {}).get("decision_as_of") == document.get("decision_as_of")
         and type(document.get("model_fit_calls")) is int and document["model_fit_calls"] == 0
         and document.get("execution_admission_inherited") is False and document.get("historical_strict_pit_claim") is False,
         "CONSENSUS_DURATION_PUBLICATION_IDENTITY_CHANGED")
    clock = pd.Timestamp(document["decision_as_of"]); observed = pd.Timestamp(as_of)
    need(clock.tzinfo is not None and observed.tzinfo is not None
         and pd.Timestamp(base["decision_as_of"]) <= clock <= observed, "CONSENSUS_DURATION_OBSERVATION_CLOCK")
    statuses = {**base["strategy_status"], "R6_DURATION_TREE": {"status": document["status"]}}
    if document.get("reason"):
        statuses["R6_DURATION_TREE"]["reason"] = document["reason"]
    doc = {**base, "strategy_status": statuses, "decision_as_of": document["decision_as_of"],
        "base_publication_ref": base_ref, "duration_publication_ref": ref, "r6_probe_source": document["r6_probe_source"],
        "duration_qualification_ref": document["qualification_ref"],
        "input_refs": {**base["input_refs"], **({"R6_DURATION": document["input_ref"]} if document["input_ref"] else {})}}
    return doc, ref


def _qualified_duration_frame(paths, doc):
    import pandas as pd
    from scripts.research.a2.inference.current_r6_probes import validate_current_duration_frame
    need(doc.get("strategy_status", {}).get("R6_DURATION_TREE", {}).get("status") == "READY",
        doc.get("strategy_status", {}).get("R6_DURATION_TREE", {}).get("reason") or "CONSENSUS_DURATION_SOURCE_NOT_READY")
    proof = json.loads(verify(doc["duration_qualification_ref"]).read_text(encoding="utf8"))
    need(proof.get("schema") == "CURRENT_CONSENSUS_DURATION_INPUT_R1"
         and proof.get("input_ref") == doc["input_refs"]["R6_DURATION"]
         and proof.get("signal_date") == doc["signal_date"] and proof.get("decision_as_of") == doc["decision_as_of"]
         and proof.get("r6_probe_source") == doc["r6_probe_source"]
         and proof.get("qualification", {}).get("source_refs", {}).get("flags") == doc["flags_ref"]
         and proof.get("qualification", {}).get("source_refs", {}).get("pool") == doc["source_bundle_ref"],
         "CONSENSUS_DURATION_INPUT_BINDING_CHANGED")
    frame = pd.read_parquet(verify(proof["input_ref"]))
    validate_current_duration_frame(paths, frame=frame, qualification=proof["qualification"],
        r6_probe_source=proof["r6_probe_source"], signal_date=doc["signal_date"], decision_as_of=doc["decision_as_of"])
    return frame


def _duration_source_refs(doc, member):
    return {"consensus/flags": doc["flags_ref"], "consensus/pool": doc["source_bundle_ref"],
        "current": doc["input_refs"]["current"], "R6_DURATION": doc["input_refs"]["R6_DURATION"],
        "consensus/base_publication": doc["base_publication_ref"], "consensus/duration_publication": doc["duration_publication_ref"],
        "consensus/duration_qualification": doc["duration_qualification_ref"],
        "consensus/r6_probe": doc["r6_probe_source"]["probe_ref"],
        "consensus/r6_probe_qualification": doc["r6_probe_source"]["qualification_ref"],
        "model/duration_tree_2025": member["model_ref"], "model_receipt/duration_tree_2025": member["receipt_ref"],
        "model_contract/R6": member["r6_contract_ref"], "model_closure/R6": member["closure_ref"]}


def _optional_duration_extension(paths, base, base_ref, source, *, prefix=None, calendar=None):
    """Only optional-candidate faults are closed after the original base commits."""
    try:
        prepared = (_prepare_duration_frame(paths, base, source, prefix=prefix, calendar=calendar)
                    if prefix is not None else None)
        return publish_duration_extension(paths, base, base_ref, source, prepared=prepared)
    except Exception as exc:
        return dict(status="BLOCKED", reason=(type(exc).__name__ + ":" + str(exc))[:1024],
                    publication_ref=None, decision_as_of=None, reused=False)


def publish_inputs(paths, *, flags_ref, source_bundle_ref, signal_date, decision_as_of, source_extension_ref, r6_probe_source=None):
    """Publish source inputs under daily_root; caller holds original daily lock."""
    import pandas as pd
    from scripts.common.storage_paths import assert_safe_output_path
    from scripts.research.a2.inference import frozen_a94_state as state
    clock = pd.Timestamp(decision_as_of); day = pd.Timestamp(signal_date)
    need(clock.tzinfo is not None and pd.Timestamp("2026-01-01") <= day < pd.Timestamp("2027-01-01")
         and clock >= day.tz_localize("America/New_York") + pd.Timedelta(hours=16), "CONSENSUS_DECISION_CLOSE_CLOCK_REQUIRED")
    need(source_bundle_ref["sha256"] == BUNDLE_SHA, "CONSENSUS_ORIGINAL_TOP100_BUNDLE_REQUIRED")
    bundle = metadata(source_bundle_ref, ("schema", "pool_variant_id", "selection_rule", "prehistory_ref", "prehistory_calendar_ref", "source_manifest_ref"))
    need(bundle.get("schema") == "CONSENSUS_VARIANT_INPUT_BUNDLE_R1" and bundle.get("pool_variant_id") == "TOP100"
         and bundle.get("selection_rule") == "MANAGER_COUNT_WEIGHT_SUM", "CONSENSUS_POOL_IDENTITY_REQUIRED")
    proof = validate_extension(source_extension_ref, flags_ref, source_bundle_ref, day, clock)
    if r6_probe_source is not None:
        pointer = paths.daily_root / "A2_consensus_paper/latest.json"
        if pointer.exists():
            prior_ref = json.loads(pointer.read_text(encoding="utf8"))
            if metadata(prior_ref, ("signal_date",)).get("signal_date") == signal_date:
                base, base_ref = load_publication(paths, signal_date, decision_as_of)
                need(base["flags_ref"] == flags_ref and base["source_bundle_ref"] == source_bundle_ref
                     and base["source_extension_ref"] == source_extension_ref, "CONSENSUS_DURATION_BASE_SOURCE_CHANGED")
                extension = _optional_duration_extension(paths, base, base_ref, r6_probe_source)
                return {**base, "paper_current_extension": extension}
    resource_check()
    columns = list(state._PRED)
    current_prefix = bounded_frame(flags_ref, columns, "signal_date", "2026-01-01", signal_date)
    need(not current_prefix.empty and pd.to_datetime(current_prefix.signal_date).max() == day, "CONSENSUS_CURRENT_FLAGS_MISSING")
    prior = bounded_frame(bundle["prehistory_ref"], columns, "signal_date", "2023-01-01", "2025-12-31")
    cal = bounded_frame(bundle["prehistory_calendar_ref"], ["trade_date"], "trade_date", "2023-01-01", "2025-12-31")
    calendar = pd.DatetimeIndex(pd.to_datetime(cal.trade_date)).append(pd.DatetimeIndex(pd.to_datetime(current_prefix.signal_date).drop_duplicates().sort_values()))
    prefix = pd.concat([prior, current_prefix], ignore_index=True)
    del prior; gc.collect()
    current = current_prefix.loc[pd.to_datetime(current_prefix.signal_date).eq(day)].copy()
    need(not current.duplicated(["signal_date", "ticker"]).any() and current.is_raw_top20.sum() == 20
         and current.loc[current.is_raw_top20, "raw_top20_set_complete"].eq(True).all(), "CONSENSUS_CURRENT_TOP20_REQUIRED")
    ranked_current = current.loc[current.raw_a2_rank.notna()]
    ranked_ids = proof["current_day_proofs"][-1]["ranked_pool_security_ids"]
    need(len(ranked_current) == len(ranked_ids) and 40 <= len(ranked_current) <= 100
         and ranked_current.sort_values("raw_a2_rank").security_id.astype(str).tolist() == ranked_ids
         and set(ranked_current.raw_a2_rank) == set(range(1, len(ranked_ids) + 1)), "CONSENSUS_CURRENT_FLAGS_POOL_PROOF_MISMATCH")
    output = (paths.daily_root / "A2_consensus_paper" / "inputs" / signal_date).resolve()
    assert_safe_output_path(output, kind="daily", paths=paths); output.mkdir(parents=True, exist_ok=True)
    refs = {}
    def store(name, frame):
        frame = frame.reset_index(drop=True)
        need(not set(frame) & FORBIDDEN, "CONSENSUS_OUTCOME_EXPORT_FORBIDDEN")
        path = output / (name + ".parquet")
        if path.exists():
            existing = pd.read_parquet(path)
            try:
                pd.testing.assert_frame_equal(existing, frame, check_dtype=False)
            except AssertionError as exc:
                raise ValueError("CONSENSUS_PRESERVE_EXISTING_INPUT") from exc
        else:
            frame.to_parquet(path, index=False, compression="zstd")
        refs[name] = reference(path)
    store("current", current)
    statuses = {}
    try:
        roles = original_frames(prefix, calendar, signal_date)
        for name, frame in roles.items(): store(name, frame)
        statuses.update({sid: {"status": "READY"} for sid in NEW_IDS[:2]})
        del roles
    except (ValueError, KeyError, TypeError) as exc:
        statuses.update({sid: {"status": "BLOCKED", "reason": str(exc)} for sid in NEW_IDS[:2]})
    if r6_probe_source is None:
        del prefix
    del current_prefix; gc.collect()
    try:
        store("GROSS", gross_frame(current, signal_date)); statuses[NEW_IDS[2]] = {"status": "READY"}
    except (ValueError, KeyError, TypeError) as exc:
        statuses[NEW_IDS[2]] = {"status": "BLOCKED", "reason": str(exc)}
    source_status = "READY" if all(item["status"] == "READY" for item in statuses.values()) else "PARTIAL" if any(item["status"] == "READY" for item in statuses.values()) else "BLOCKED"
    document = dict(schema=SCHEMA, status=source_status, signal_date=signal_date, decision_as_of=clock.isoformat(), pool_contract=POOL,
                    source_bundle_ref=source_bundle_ref, flags_ref=flags_ref, source_extension_ref=source_extension_ref,
                    parent_source_role=proof["parent_source_role"], parent_source_completeness_unknown=proof["parent_source_completeness_unknown"],
                    parent_historical_available_at_bound=proof["parent_historical_available_at_bound"],
                    historical_strict_pit_claim=False, execution_admission_inherited=False,
                    input_refs=refs, strategy_status=statuses,
                    generated_at=datetime.now(timezone.utc).isoformat(), model_fit_calls=0, label_columns_decoded=0)
    stable = {key: value for key, value in document.items() if key != "generated_at"}
    identity = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf8")).hexdigest()[:20]
    destination = output / ("publication_" + identity + ".json")
    body = json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if destination.exists():
        old = json.loads(destination.read_text(encoding="utf8")); need(all(old[k] == document[k] for k in document if k != "generated_at"), "CONSENSUS_PRESERVE_EXISTING_PUBLICATION")
        document = old
    else: destination.write_text(body, encoding="utf8")
    pointer = paths.daily_root / "A2_consensus_paper" / "latest.json"
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(json.dumps(reference(destination)), encoding="utf8"); temporary.replace(pointer)
    if r6_probe_source is not None:
        try:
            extension = _optional_duration_extension(paths, document, reference(destination), r6_probe_source,
                prefix=prefix, calendar=calendar)
        finally:
            del prefix; gc.collect()
        return {**document, "paper_current_extension": extension}
    return document


def load_publication(paths, day, as_of, *, paper_current=False):
    from scripts.common.storage_paths import assert_safe_output_path
    pointer = paths.daily_root / "A2_consensus_paper/latest.json"
    ref = json.loads(pointer.read_text(encoding="utf8")); path = verify(ref)
    assert_safe_output_path(path, kind="daily", paths=paths)
    doc = json.loads(path.read_text(encoding="utf8"))
    import pandas as pd
    need(doc.get("schema") == SCHEMA and doc.get("signal_date") == day and doc.get("pool_contract") == POOL
         and doc.get("model_fit_calls") == 0 and doc.get("label_columns_decoded") == 0
         and pd.Timestamp(doc["decision_as_of"]) <= pd.Timestamp(as_of), "CONSENSUS_CURRENT_PUBLICATION_REQUIRED")
    validate_extension(doc["source_extension_ref"], doc["flags_ref"], doc["source_bundle_ref"], pd.Timestamp(day), pd.Timestamp(as_of))
    if paper_current:
        return _load_duration_publication(paths, doc, ref, as_of)
    return doc, ref


def frozen_states(paths, sid):
    """Decode only small, pure identity closure documents; never fit receipts."""
    need(sid in PAPER_CURRENT_IDS, "CONSENSUS_EXACT_CURRENT_CANDIDATE_REQUIRED")
    if sid == "R6_DURATION_TREE":
        path = paths.results_root / "_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/A_ALL_FROZEN_STATE_DEPENDENCIES.json"
        ref = dict(path=str(path), sha256=OLD_STATES_SHA)
        from scripts.common.json_projection import array_metadata_fields
        data = metadata(ref, ("authority_refs",))
        fields = ("slot_id", "stage", "objective", "learner", "year", "status",
            "model_path", "model_sha256", "receipt_ref")
        with verify(ref).open("rb") as stream:
            rows = [row for row in array_metadata_fields(stream, ("model_states",), fields)
                if row.get("slot_id") == "duration_tree_2025"]
        need(len(rows) == 1, "CONSENSUS_DURATION_ONE_FROZEN_STATE")
        row = rows[0]
        need(row.get("stage") == "R6" and row.get("objective") == "duration" and row.get("learner") == "tree"
             and type(row.get("year")) is int and row["year"] == 2025 and row.get("status") == "TRAINED",
             "CONSENSUS_DURATION_FROZEN_IDENTITY")
        # Same state-ref construction as frozen_a94_profile._profile_contract.
        return {"duration_tree_2025": dict(model_ref=dict(path=row["model_path"], sha256=row["model_sha256"]),
            receipt_ref=row["receipt_ref"], r6_contract_ref=data["authority_refs"]["R6_contract"],
            closure_ref=ref, metadata_row=row)}
    if sid == NEW_IDS[1]:
        path = paths.results_root / "_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/A_ALL_FROZEN_STATE_DEPENDENCIES.json"
        verify(dict(path=str(path), sha256=OLD_STATES_SHA))
        data = json.loads(path.read_text(encoding="utf8")); result = {}
        for row in [*data["model_states"], *data["external_scaler_states"]]:
            if row["slot_id"].startswith(("ACTION_VALUE_ENTRY_H5_2025_", "ACTION_VALUE_INCUMBENT_H5_2025_")) and (row.get("family") in ("ridge", "SCALER")) and row.get("capacity") in ("MID", "SHARED"):
                result[row["slot_id"]] = dict(model_ref=dict(path=row["model_path"], sha256=row["model_sha256"]), metadata_row=row)
        need(len(result) == 4, "CONSENSUS_RIDGE_FOUR_FROZEN_STATES")
        return result
    folder = paths.backtest_root / TASK / RUN / "derived/remaining10"
    path, digest = ((folder / "solver_continuation/ACCOUNT_MODEL_CLOSURE_R3.json", ELASTIC_CLOSURE_SHA)
                    if sid == NEW_IDS[0] else (folder / "R7/model_closure/MODEL_CLOSURE_R1.json", R7_CLOSURE_SHA))
    verify(dict(path=str(path), sha256=digest)); data = json.loads(path.read_text(encoding="utf8"))
    need(data.get("schema") == "REMAINING10_FROZEN_ACCOUNT_MODEL_CLOSURE_R1", "CONSENSUS_MODEL_CLOSURE_SCHEMA")
    states = {key: value for key, value in data["states"].items() if value["candidate_id"] == sid}
    cutoff = "2025-01-01" if sid == NEW_IDS[0] else "2024-10-07"
    need(len(states) == (4 if sid == NEW_IDS[0] else 1) and all(s["signal_cutoff_exclusive"] == cutoff and s["label_maturity_cutoff_exclusive"] == cutoff for s in states.values()), "CONSENSUS_EARLIER_FROZEN_CUTOFF")
    return states


def predict_r10(model, x):
    """Pin all used owners; qualify only the declared unused-fusion pin delta."""
    from scripts.research.a2.training import stateful_mechanism_models as owner
    from scripts.research.a2.inference.frozen_a94_state import _clone
    expected = model.metadata["source_pins"]; actual = owner.source_pins()
    differences = {k for k in expected if expected[k] != actual.get(k)}
    need(set(expected) == set(actual) and differences <= {"fusion_owner_sha256"}, "CONSENSUS_USED_PREDICTOR_SOURCE_CHANGED")
    if differences:
        need(expected["fusion_owner_sha256"] == "f83c8e09c0cf2856a61f98b51775cf6f382d70b6266878876ced1eba2754ae3b"
             and actual["fusion_owner_sha256"] == "1e1609bf2ec9ac20793ca18b402e3b5ae6be1da8759b91bf2f557c1cd4157e7c", "CONSENSUS_EXACT_UNUSED_FUSION_COMPATIBILITY")
    predictor = owner.predict if not differences else _clone(owner.predict, source_pins=lambda: dict(expected))
    return predictor(model, x)


def r10_scaled_input(scaler, encoded):
    """Original transform/zero-fill; reuse only an owned StandardScaler result."""
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    transformed = scaler.transform(encoded)
    exclusive = (type(scaler) is StandardScaler and scaler.copy is True
        and getattr(scaler.transform, "__func__", None) is StandardScaler.transform
        and type(transformed) is np.ndarray and transformed.flags.owndata and transformed.flags.writeable
        and not np.shares_memory(transformed, encoded))
    return np.nan_to_num(transformed, nan=0., copy=not exclusive)


def r10_decoder_input(record, native, *, group):
    """Restore the original bound R10 support and replacement SID interface.

    frozen_a94_actions.bind_action_input/predict_r10 mask unsupported INCUMBENT
    outputs; decode_candidate copies entrant_sid before the original row decoder.
    The full original custody handles remain owned by their frozen authority.
    """
    import pandas as pd
    need(group in ("ENTRY", "INCUMBENT") and isinstance(record, dict) and isinstance(native, dict),
         "CONSENSUS_R10_DECODER_INPUT_SCHEMA")
    need(not (set(record) | set(native)) & FORBIDDEN, "CONSENSUS_R10_DECODER_OUTCOME_FORBIDDEN")
    first = {**record, **native}
    if group == "INCUMBENT":
        need({"e_friction", "i_friction", "action_type", "entrant_sid"} <= set(record),
             "CONSENSUS_R10_ORIGINAL_SUPPORT_AND_SID_FIELDS_REQUIRED")
        if not (pd.notna(record["e_friction"]) and pd.notna(record["i_friction"])):
            first.update({key: float("nan") for key in native})
    if first.get("action_type") == 1:
        first["entrant_security_id"] = first.get("entrant_sid")
    return first


def decoded_actions(paths, sid, doc):
    import joblib
    import numpy as np
    import pandas as pd
    from scripts.research.a2.training import stateful_mechanism as mechanism, stateful_final_action_packets as packets
    from scripts.research.a2.inference.frozen_a94_actions import role_features
    from threadpoolctl import threadpool_limits
    states = frozen_states(paths, sid); output = []; refs = {}
    for group in ("ENTRY", "INCUMBENT"):
        resource_check()
        candidates = [(key, s) for key, s in states.items() if s.get("metadata_row", {}).get("group") == group and s.get("state_type", "new_model") == "new_model"]
        if sid == NEW_IDS[1]:
            candidates = [(key, s) for key, s in states.items() if key.startswith("ACTION_VALUE_" + group + "_H5") and s["metadata_row"]["family"] == "ridge"]
        need(len(candidates) == 1, "CONSENSUS_HEAD_CLOSURE")
        key, state = candidates[0]; row = state["metadata_row"]
        scaler_states = [s for k, s in states.items() if "SCALER" in k and ("ACTION_VALUE_" + group + "_") in k]
        need(len(scaler_states) == 1, "CONSENSUS_SHARED_SCALER_CLOSURE")
        model = joblib.load(verify(state["model_ref"])); scaler = joblib.load(verify(scaler_states[0]["model_ref"]))
        model_lifetime, scaler_lifetime = weakref.ref(model), weakref.ref(scaler)
        refs[key] = state["model_ref"]; refs[group + "_SCALER"] = scaler_states[0]["model_ref"]
        frame = pd.read_parquet(verify(doc["input_refs"][group]))
        need(not set(frame) & FORBIDDEN and pd.to_datetime(frame.signal_date).eq(pd.Timestamp(doc["signal_date"])).all(), "CONSENSUS_ACTION_DATE_OR_OUTCOME")
        x, names = r10_encoded_input(frame, role_features("R10:" + group))
        need(tuple(names) == tuple(row["feature_order"]), "CONSENSUS_ORIGINAL_FEATURE_ORDER")
        predictions = {}
        if len(x):
            x = r10_scaled_input(scaler, x)
            with threadpool_limits(limits=1): predictions = predict_r10(model, x)
        del model, scaler, x; gc.collect()
        need(model_lifetime() is None and scaler_lifetime() is None, "CONSENSUS_HEAD_MODEL_RELEASE_REQUIRED")
        for start in range(0, len(frame), 4096):
            for index, record in enumerate(frame.iloc[start:start + 4096].to_dict("records"), start):
                native = {k: float(v[index]) for k, v in predictions.items() if isinstance(v, np.ndarray) and v.shape == (len(frame),)}
                output.append(packets.decode_r10_row(r10_decoder_input(record, native, group=group), len(output), group=group))
        del frame, predictions
    return output, refs


def duration_actions(paths, doc):
    """Original duration_tree_2025 and p_failure decoder; no old authority is forged."""
    import joblib
    import numpy as np
    import pandas as pd
    from scripts.research.a2.training import stateful_decision as decision, stateful_decision_models as owner
    from scripts.research.a2.training import stateful_final_action_packets as packets
    frame = _qualified_duration_frame(paths, doc)  # Qualification fails before any model load.
    states = frozen_states(paths, "R6_DURATION_TREE"); member = states["duration_tree_2025"]; row = member["metadata_row"]
    receipt = metadata(member["receipt_ref"], ("status", "year", "model_sha256", "model_path", "seed", "objective", "learner", "scientific_tuple", "scientific_tuple_sha256"))
    contract = metadata(member["r6_contract_ref"], ("specification_sha256", "input_manifest_sha256"))
    tup = receipt.get("scientific_tuple", {})
    features = tuple(decision.SINGLE) + tuple(c + "__missing" for c in decision.SINGLE)
    boundary = pd.Timestamp(tup.get("calibration_start"))
    model_path = Path(member["model_ref"]["path"]).resolve()
    need(receipt.get("status") == "TRAINED" and receipt.get("year") == 2025
         and receipt.get("objective") == "duration" and receipt.get("learner") == "tree"
         and receipt.get("model_sha256") == member["model_ref"]["sha256"]
         and Path(receipt.get("model_path", "")).resolve() == model_path
         and model_path.parent == Path(member["receipt_ref"]["path"]).resolve().parent
         and hashlib.sha256(json.dumps(tup, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest() == receipt.get("scientific_tuple_sha256")
         and receipt.get("seed") == tup.get("seed") == owner.SEED
         and tup.get("slot") == dict(stage="R6", objective="duration", learner="tree", year=2025, slot_id="duration_tree_2025")
         and pd.Timestamp(tup.get("training_signal_max")) < boundary
         and pd.Timestamp(tup.get("training_maturity_max")) < boundary < pd.Timestamp("2025-01-01")
         and tup.get("contract_sha256") == contract.get("specification_sha256")
         and tup.get("input_manifest_sha256") == contract.get("input_manifest_sha256")
         and tuple(tup.get("feature_order", ())) == features,
         "CONSENSUS_DURATION_ORIGINAL_FROZEN_TUPLE")
    need(reference(model_path.parents[3] / "input_manifest.json")["sha256"] == tup["input_manifest_sha256"],
         "CONSENSUS_DURATION_INPUT_MANIFEST_CHANGED")
    resource_check(); model = joblib.load(verify(member["model_ref"])); lifetime = weakref.ref(model)
    need(type(model) is owner.Model and model.objective == "duration" and model.learner == "tree"
         and tuple(model.features) == features, "CONSENSUS_DURATION_SERIALIZED_IDENTITY")
    x, names = decision.encode_features(frame, decision.SINGLE)
    need(tuple(names) == features, "CONSENSUS_DURATION_ORIGINAL_FEATURE_ORDER")
    prediction = owner.predict(model, x)  # Original source/spec/backend/native probability checks.
    probability = prediction.get("p_failure")
    need(isinstance(probability, np.ndarray) and probability.shape == (len(frame),),
         "CONSENSUS_DURATION_NATIVE_FAILURE_PROBABILITY_REQUIRED")
    records = [packets.decode_r6_row({**record, "p_failure": float(probability[i])}, "duration", i)
        for i, record in enumerate(frame.to_dict("records"))]
    del model, x, prediction, probability, frame; gc.collect()
    need(lifetime() is None, "CONSENSUS_DURATION_MODEL_RELEASE_REQUIRED")
    return records, {"duration_tree_2025": member["model_ref"]}


def requested_gross(paths, doc, state):
    import joblib
    import pandas as pd
    from scripts.research.a2.training import stateful_decision as decision, stateful_decision_models as owner
    states = frozen_states(paths, NEW_IDS[2]); member = next(iter(states.values()))
    resource_check(); model = joblib.load(verify(member["model_ref"]))
    model_lifetime = weakref.ref(model)
    frame = pd.read_parquet(verify(doc["input_refs"]["GROSS"]))
    need(not set(frame) & FORBIDDEN and pd.to_datetime(frame.signal_date).eq(pd.Timestamp(doc["signal_date"])).all(), "CONSENSUS_GROSS_DATE_OR_OUTCOME")
    previous = float(state.get("previous_requested_gross", 1.))
    need(previous in decision.G and len(frame) == 5 and set(frame.gross_previous_proxy) == set(decision.G), "CONSENSUS_R7_FULL_GRID_REQUIRED")
    x, names = decision.encode_features(frame, decision.GROSS)
    need(tuple(names) == tuple(model.features) and model.objective == "gross" and model.learner == "linear", "CONSENSUS_R7_MODEL_IDENTITY")
    output = owner.predict(model, x)
    requested = float(output["gross"][frame.gross_previous_proxy.eq(previous).to_numpy()][0])
    del model, frame, x; gc.collect()
    need(model_lifetime() is None, "CONSENSUS_R7_MODEL_RELEASE_REQUIRED")
    return previous, requested, {"R7_GROSS_LINEAR": member["model_ref"]}


def infer_application(paths, sid, state, doc):
    import numpy as np
    import pandas as pd
    from scripts.research.a2.training.stateful_account import reference_policy_class
    from scripts.research.a2.training.stateful_decision import _valid_sid
    from scripts.research.a2.training.stateful_final_action_packets import decode_resource_proposals
    need(sid in PAPER_CURRENT_IDS and doc["strategy_status"].get(sid, {}).get("status") == "READY", "CONSENSUS_STRATEGY_SOURCE_NOT_READY")
    memory_before = process_memory()
    current = pd.read_parquet(verify(doc["input_refs"]["current"]))
    top = current.loc[current.is_raw_top20.eq(True)].sort_values("raw_a2_rank")
    need(len(top) == 20 and top.security_id.nunique() == 20, "CONSENSUS_COMPLETE_TOP20")
    weights = state["weights"]
    current_identity = {str(row.ticker): str(row.security_id) for row in current.itertuples() if _valid_sid(row.security_id)}
    for ticker in weights:
        recorded = state.get("security_ids", {}).get(ticker)
        need(recorded is None or ticker not in current_identity or str(recorded) == current_identity[ticker], "CONSENSUS_ACCOUNT_HELD_SECURITY_CHANGED")
    from scripts.research.a2.inference.frozen_target_adaptation import frozen_limits, adapt_targets
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
    limits = frozen_limits()
    tickers = sorted(set(current.ticker) | set(weights)); ti = {t: i for i, t in enumerate(tickers)}
    qualified_tickers = set(current.loc[current.feature_available.eq(True) & current.raw_a2_rank.notna()
        & current.security_id.map(_valid_sid), "ticker"])
    qualified = np.array([[t in qualified_tickers for t in tickers]])
    topmask = np.array([[t in set(top.ticker) for t in tickers]])
    held = set(weights); allowed = set(top.loc[top.new_buy_eligible.eq(True), "ticker"]) & qualified_tickers
    masks = qualified.copy(); accepted = []; models = {}; previous = requested = None
    if sid == NEW_IDS[2]: previous, requested, models = requested_gross(paths, doc, state)
    else:
        records, models = duration_actions(paths, doc) if sid == "R6_DURATION_TREE" else decoded_actions(paths, sid, doc)
        # Match FinalActionOverlay's original decision-input and dated-SID gate.
        legal = []
        for record in records:
            t = str(record.get("ticker", "")); entrant = record.get("entrant")
            if t not in qualified_tickers or not _valid_sid(record.get("security_id")) or str(record["security_id"]) != current_identity.get(t):
                continue
            if entrant and (not _valid_sid(record.get("entrant_security_id")) or str(record["entrant_security_id"]) != current_identity.get(str(entrant))):
                continue
            legal.append(record)
        accepted = decode_resource_proposals(legal, held=held, allowed=allowed)["accepted"]
        for record in accepted:
            if record["kind"] == "HOLD" and record["ticker"] in held: masks[0, ti[record["ticker"]]] = False
    closeweights = np.array([[weights.get(t, 0.) for t in tickers]])
    units = state.get("units", {}); current_units = np.array([[units.get(t, 1. if t in held else 0.) for t in tickers]])
    reserved = (current_units > 1e-10) & ~qualified
    reserved_weight = np.sum(np.where(reserved, closeweights, 0.), axis=1)
    buy_tickers = set(current.loc[current.new_buy_eligible.eq(True), "ticker"]) & qualified_tickers
    buy_allowed = np.array([[t in buy_tickers for t in tickers]])
    context = SimpleNamespace(current_units=current_units, current_weights=closeweights, cash=np.array([state["cash_weight"]]),
        cash_weight=np.array([state["cash_weight"]]), nav=np.array([1.]),
        available_budget=np.maximum(0., limits["max_invested"] - reserved_weight),
        available_slots=np.maximum(0, limits["max_positions"] - reserved.sum(axis=1)),
        reserved_mask=reserved, reserved_weight=reserved_weight, reserved_slots=reserved.sum(axis=1),
        decision_mask=masks, input_present=qualified, buy_allowed=buy_allowed,
        sell_restricted=np.zeros_like(masks), operational_mask=np.zeros_like(masks),
        max_positions=limits["max_positions"], max_weight=limits["max_weight"], max_invested=limits["max_invested"],
        path_ids=("B",), tickers=tickers, signal_date=pd.Timestamp(doc["signal_date"]))
    policy = reference_policy_class()(np.zeros_like(topmask, dtype=float), np.zeros(1), None, np.zeros(1), np.zeros_like(topmask, dtype=float), topmask, qualified, ["CONSENSUS_PAPER_SOURCE_V1"])
    target = policy(0, context); out = target.weights[0].copy(); explicit = target.explicit_mask[0].copy()
    decisions = {}; action_scores = {}
    for record in accepted:
        t = record["ticker"]; j = ti.get(t)
        if j is None: continue
        kind, decision = record["kind"], record.get("decision", record["kind"]); decisions[t] = decision
        action_scores[t] = record.get("source_score")
        if decision == "SKIP" and t not in held: out[j] = 0.; explicit[j] = False
        elif kind == "HOLD" and t in held: explicit[j] = False
        elif kind == "SELL" and t in held: out[j] = 0.; explicit[j] = True
        elif kind == "REPLACE" and t in held:
            entrant = record.get("entrant")
            if entrant in allowed and entrant not in held: out[j] = 0.; explicit[j] = True
    if requested is not None:
        # R7GrossOverlay scales requested targets, never hard-frozen HOLD units.
        explicit &= masks[0] & ~reserved[0]
        out *= requested; out[~explicit] = 0.
    repaired = adapt_targets(context, TargetDecision(out[None, :], explicit_mask=explicit[None, :]))
    raw_requested = repaired["raw_weights"][0]
    out = repaired["weights"][0]
    keep = repaired["exact_hold_mask"][0]
    explicit &= ~keep
    result_rows = []; identity = {str(row.ticker): str(row.security_id) for row in current.itertuples() if _valid_sid(row.security_id)}
    ranked = top.set_index("ticker")
    for t, j in ti.items():
        weight = float(out[j]) if explicit[j] else float(closeweights[0, j])
        if weight == 0 and t not in held and t not in set(top.ticker): continue
        row = dict(ticker=t, security_id=identity.get(t) or state.get("security_ids", {}).get(t), target_weight=weight, explicit_target=bool(explicit[j]), action=decisions.get(t, "TARGET"),
                   source_score=action_scores.get(t), raw_rank=int(ranked.loc[t, "raw_a2_rank"]) if t in ranked.index else None,
                   raw_score=float(ranked.loc[t, "raw_a2_prediction"]) if t in ranked.index else None)
        reasons = []
        if repaired["ineligible_adaptation"][0, j]: reasons.append("SIGNAL_NEW_CAPITAL_INELIGIBLE")
        if repaired["slot_adaptation"][0, j]: reasons.append("SIGNAL_RESERVED_SLOT_BUDGET")
        if out[j] > 0 and repaired["receipt"]["capital_scale"] < 1.: reasons.append("SIGNAL_RESERVED_CAPITAL_BUDGET")
        row.update(raw_model_weight=float(raw_requested[j]) if explicit[j] else None,
                   adaptation_reasons="|".join(reasons))
        if keep[j] and t in held:
            need(t in units and units[t] > 0, "CONSENSUS_EXACT_HOLD_UNITS_REQUIRED")
            row.update(action="HOLD", exact_hold_units=float(units[t]))
        result_rows.append(row)
    cash = 1. - sum(r["target_weight"] for r in result_rows)
    need(cash >= -1e-8, "CONSENSUS_LONG_ONLY_CASH_BUDGET")
    result = dict(status="READY", signal_date=doc["signal_date"], rows=result_rows, target_cash_weight=max(0., cash),
                  account_basis="OWN_SIGNAL_CLOSE_FROZEN_CONSENSUS", policy_id=sid, model_refs=models, pool_contract=POOL,
                  target_adaptation_receipt=repaired["receipt"],
                  source_refs=(_duration_source_refs(doc, frozen_states(paths, sid)["duration_tree_2025"]) if sid == "R6_DURATION_TREE" else
                    {"consensus/flags": doc["flags_ref"], "consensus/pool": doc["source_bundle_ref"], **doc["input_refs"]}),
                  resource_receipt={"model_load_mode": "SEQUENTIAL_HEADS_RELEASED", "max_loaded_frozen_states": 1 if sid in (NEW_IDS[2], "R6_DURATION_TREE") else 2,
                                    "release_weakrefs_checked": True, "global_model_cache": False, "resource_floor_physical_gib": 1.5,
                                    "resource_floor_page_gib": 8., "model_fit_calls": 0, "memory_before": memory_before,
                                    "memory_after_model_release": process_memory()}, model_fit_calls=0)
    if requested is not None:
        result.update(previous_requested_gross=previous, requested_gross=requested,
                      strategy_state_after=dict(previous_requested_gross=requested, last_signal_date=doc["signal_date"]))
    return result


def candidate_source_refs(paths, sid, doc, publication_ref, *, as_of=None):
    """Recheck current input/model bytes without loading any fitted object."""
    need(sid in PAPER_CURRENT_IDS, "CONSENSUS_EXACT_CURRENT_CANDIDATE_REQUIRED")
    clock = as_of or datetime.now(timezone.utc).isoformat()
    from scripts.research.a2.inference.frozen_target_adaptation import frozen_limits, _projection
    frozen_limits(); _projection()  # Fixed original limits/algorithm bytes; no models or account reads.
    checked, checked_ref = load_publication(paths, doc["signal_date"], clock, **({"paper_current": True} if sid == "R6_DURATION_TREE" else {}))
    need(checked == doc and checked_ref == publication_ref
         and doc.get("strategy_status", {}).get(sid, {}).get("status") == "READY",
         "CONSENSUS_CURRENT_CANDIDATE_PUBLICATION_CHANGED")
    states = frozen_states(paths, sid); models = {}
    if sid == "R6_DURATION_TREE":
        frame = _qualified_duration_frame(paths, doc); del frame
        member = states["duration_tree_2025"]
        refs = {**_duration_source_refs(doc, member), "consensus/publication": publication_ref}
        for ref in refs.values(): verify(ref)
        return refs
    if sid == NEW_IDS[2]:
        need(len(states) == 1, "CONSENSUS_R7_FROZEN_STATE_REQUIRED")
        member = next(iter(states.values())); models[sid] = member["model_ref"]
    else:
        for group in ("ENTRY", "INCUMBENT"):
            candidates = [(key, value) for key, value in states.items()
                if value.get("metadata_row", {}).get("group") == group and value.get("state_type", "new_model") == "new_model"]
            if sid == NEW_IDS[1]:
                candidates = [(key, value) for key, value in states.items()
                    if key.startswith("ACTION_VALUE_" + group + "_H5") and value["metadata_row"]["family"] == "ridge"]
            scales = [value for key, value in states.items() if "SCALER" in key and ("ACTION_VALUE_" + group + "_") in key]
            need(len(candidates) == 1 and len(scales) == 1, "CONSENSUS_SHARED_CURRENT_HEAD_CLOSURE")
            key, member = candidates[0]
            models[key] = member["model_ref"]; models[group + "_SCALER"] = scales[0]["model_ref"]
    refs = {"consensus/flags": doc["flags_ref"], "consensus/pool": doc["source_bundle_ref"],
            **doc["input_refs"], "consensus/publication": publication_ref,
            **{"model/" + key: value for key, value in models.items()}}
    for ref in refs.values(): verify(ref)
    return refs
