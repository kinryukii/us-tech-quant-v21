"""Read the exact frozen MAIN ledgers; no rerun, window selection or broker calls."""
from __future__ import annotations
from copy import deepcopy
from datetime import date, datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

_REPAIR = Path("D:/us-tech-quant-backtests/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/20261010T155614+0000_8a89315b/derived/remaining10")
_RIDGE = Path("D:/us-tech-quant-backtests/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/20261009T040010+0000_ebc89ace/derived/consensus_all_a/accounts/MAIN/FINAL_ACTION_OVERLAY_10bps")
SOURCES = {
    "R10_DIRECT_MEAN4_ELASTICNET_MID": dict(path=str(_REPAIR / "solver_continuation/accounts/shared_batch/MAIN/daily.parquet"), sha256="6a24db5e3e93bec0180cc68498b2d1e9a50a9f61071e9e0069bf40d5d78cb232", receipt=str(_REPAIR / "solver_continuation/accounts/shared_batch/MAIN/COMPLETION.json"), receipt_sha256="6f5cca2e95754e9f2b968c4eefe3018c29385971f18da62cff4c00787b74249e", research_id="A_TOP100_SOLVER_CONTINUATION_20261012_R1"),
    "R10_DIRECT_H5_RIDGE_MID": dict(path=str(_RIDGE / "attempt_002/daily.parquet"), sha256="c66d83d2493e1be0de09546ef24fe52bce695b05fa10b7bec4c901511b0e3fbf", receipt=str(_RIDGE / "completion.json"), receipt_sha256="93dadc2336c2a74f688a17c153dd2cfa94332b9ed8513fc0d86b3cb78ca9b5b0", research_id="V24_A_STATEFUL_ACTION_RISK_FULL_BREADTH_R10"),
    "R7_GROSS_LINEAR": dict(path=str(_REPAIR / "R7/accounts/attempt_001/MAIN/daily.parquet"), sha256="ef5921c288bedff4619676de909440c4087a1296346ff949989d95bd3905f12b", receipt=str(_REPAIR / "R7/accounts/attempt_001/MAIN/SHARED_BATCH_COMPLETION.json"), receipt_sha256="a450b6d33e59531f9a92ea854c3c70264174254d3be96b222824436e6864b972", research_id="A_TOP100_R7_GROSS_ACCOUNT_ADAPTER_20261012_R1"),
}
_CATALOG_ROOT = _RIDGE.parent
_RAW_SELECTOR_REF = {
    "path": "D:/us-tech-quant-results/_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/CONSENSUS_RAW_SELECTOR_SCOPE_R2.json",
    "sha256": "0c82334a83f6225ecaf7043f310ad6b267a255d5dd6d3044408aab818d398bd9",
}
_FROZEN_CLOSURE_REF = {
    "path": "D:/us-tech-quant-results/_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/A_ALL_FROZEN_STATE_DEPENDENCIES.json",
    "sha256": "84d2f4a644d1fdfae4f6954a3751be3bc156ec0141f537dbf64cdb55a0bf25a9",
}
# Query-only additions share their original ledgers; SOURCES and its v1
# publication contract remain the original three strategies.
CATALOG_SOURCES = {
    **SOURCES,
    **{sid: {**SOURCES["R10_DIRECT_H5_RIDGE_MID"],
             "research_id": "V24_A_DIRECT_DECISION_LEARNING_PRE2026_R6"}
       for sid in ("R6_BUY_NEURAL", "R6_DURATION_TREE")},
    "RAW_s10": {
        "path": str(_CATALOG_ROOT / "STATEFUL_OVERLAY_10bps/attempt_002/daily.parquet"),
        "sha256": "c175b8ecbcd00b295a882d77ecc534ca21ef5be3679ccb3ee31086fcfa317049",
        "receipt": str(_CATALOG_ROOT / "STATEFUL_OVERLAY_10bps/completion.json"),
        "receipt_sha256": "62a4ba5fb6be7261e8d1af80b46043328395a610a29edb311dbe57887d2513e7",
        "research_id": "A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1",
        "universe_variant": "CONSENSUS100", "pool_variant_id": "TOP100",
        "selector_scope_path": _RAW_SELECTOR_REF["path"],
        "selector_scope_sha256": _RAW_SELECTOR_REF["sha256"],
    },
}
CATALOG_IDS = tuple(CATALOG_SOURCES)
_PREFIX_END = "2026-10-08"
_MANIFEST_SCHEMA = "CONSENSUS_FIXED_MAIN_PAPER_EXTENSION_MANIFEST_R1"
_EXTENSION_SCHEMA = "CONSENSUS_FIXED_MAIN_PAPER_EXTENSION_R1"
_TABLES = ("daily", "positions", "fills", "entitlements", "actions", "orders")

# Identity metadata belongs to the original frozen closures. This presentation
# label does not read model state or loosen their earlier fitting boundaries.
_MODEL_IDENTITIES = {
    "R10_DIRECT_MEAN4_ELASTICNET_MID": {"signal_cutoff_exclusive": "2025-01-01",
        "label_maturity_cutoff_exclusive": "2025-01-01", "frozen_state_identity_ref": {
            "path": str(_REPAIR / "solver_continuation/ACCOUNT_MODEL_CLOSURE_R3.json"),
            "sha256": "90e8197fb6f6cc282e51d4efe601368e3d8ab5bd80e40e1ea47668ec729f1ec8"}},
    "R10_DIRECT_H5_RIDGE_MID": {"signal_cutoff_exclusive": "2025-01-01",
        "label_maturity_cutoff_exclusive": "2025-01-01", "frozen_state_identity_ref": {
            "path": "D:/us-tech-quant-results/_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/A_ALL_FROZEN_STATE_DEPENDENCIES.json",
            "sha256": "84d2f4a644d1fdfae4f6954a3751be3bc156ec0141f537dbf64cdb55a0bf25a9"}},
    "R7_GROSS_LINEAR": {"signal_cutoff_exclusive": "2024-10-07",
        "label_maturity_cutoff_exclusive": "2024-10-07", "frozen_state_identity_ref": {
            "path": str(_REPAIR / "R7/model_closure/MODEL_CLOSURE_R1.json"),
            "sha256": "700d2991fed512629668d56c5285d430728d31ed51289863d7366616b9e32eac"}},
}
_MODEL_IDENTITIES.update({
    sid: {"signal_cutoff_exclusive": "2024-10-07",
          "label_maturity_cutoff_exclusive": "2024-10-07",
          "frozen_state_identity_ref": _FROZEN_CLOSURE_REF,
          "frozen_model_slot": slot, "native_output": native,
          "state_semantics": "ORIGINAL_EXOGENOUS_PROXY_NOT_ACTUAL_ACCOUNT_AGE"}
    for sid, slot, native in (
        ("R6_BUY_NEURAL", "buy_neural_2025", "p_superior"),
        ("R6_DURATION_TREE", "duration_tree_2025", "p_failure"))
})
_MODEL_IDENTITIES["RAW_s10"] = {
    "signal_cutoff_exclusive": None, "label_maturity_cutoff_exclusive": None,
    "chronology_status": "UNKNOWN_NOT_PROJECTED",
    "frozen_state_identity_ref": _RAW_SELECTOR_REF,
    "selector_scope_ref": _RAW_SELECTOR_REF,
    "universe_variant": "CONSENSUS100", "pool_variant_id": "TOP100",
    "same_model_not_same_universe": True, "distinct_from": "RAW_A2",
}
_NOTE = "固定 MAIN 描述性研究账本：2026-01-02 空仓初始化，01-05 起执行；10bp 费用情景。保留原价格、公司行动及历史信息可得性限制；与模拟账户实际成交分开展示。"


def _verified(path, sha256):
    path = Path(path).resolve()
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("NEW_REPLAY_SOURCE_SIZE_LIMIT")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != sha256:
        raise ValueError("NEW_REPLAY_FROZEN_SOURCE_CHANGED")
    return path


def observed_ref(ref):
    """A changed file invalidates cached projections without decoding contents."""
    try:
        path = Path(ref["path"])
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("NEW_REPLAY_SOURCE_SIZE_LIMIT")
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except (OSError, ValueError) as exc:
        return type(exc).__name__ + ":" + str(exc)


def _metadata(ref, fields):
    from scripts.common.json_projection import metadata_fields
    path = _verified(ref["path"], ref["sha256"])
    with path.open("rb") as stream:
        return metadata_fields(stream, fields)


def _same_ref(left, right):
    return (isinstance(left, dict) and isinstance(right, dict)
            and left.get("sha256") == right.get("sha256")
            and Path(left.get("path", "")).resolve() == Path(right.get("path", "")).resolve())


def publication_pointer_path(paths=None):
    if paths is None:
        from scripts.common.storage_paths import resolve
        paths = resolve()
    return paths.daily_root / "A2_consensus_paper/MAIN_extension_latest.json"


def publication_observation_sha256(pointer_path=None):
    """Observe only the owner's <=4 KiB ref; qualification remains below.

    Missing/malformed pointers have stable identities so a failed publication
    never causes repeated UI reruns. No manifest, ledger or model is opened.
    """
    pointer = publication_pointer_path() if pointer_path is None else Path(pointer_path)
    try:
        with pointer.open("rb") as stream:
            payload = stream.read(4097)
        if len(payload) > 4096:
            return "INVALID_POINTER"
        ref = json.loads(payload)
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or not isinstance(ref["path"], str) or not ref["path"]
                or not isinstance(ref["sha256"], str) or len(ref["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in ref["sha256"])):
            return "INVALID_POINTER"
        identity = json.dumps(ref, sort_keys=True, separators=(",", ":")).encode("utf8")
        return hashlib.sha256(identity).hexdigest()
    except FileNotFoundError:
        return "NO_PUBLICATION"
    except (OSError, ValueError, TypeError):
        return "INVALID_POINTER"


def qualified_sources(pointer_path=None, *, baseline_sources=None):
    """One canonical pointer selects all three curves and native stock tables.

    A missing or unqualified extension retains the immutable Oct 8 sources.
    No series, model state or unselected candidate records are decoded here.
    """
    base = SOURCES if baseline_sources is None else baseline_sources
    fallback = dict(status="FALLBACK_ACCEPTED_PREFIX", end=_PREFIX_END, replay_sources=deepcopy(base))
    try:
        if set(base) != set(SOURCES):
            raise ValueError("NEW_REPLAY_EXACT_THREE_BASELINES_REQUIRED")
        production = pointer_path is None
        if production:
            from scripts.common.storage_paths import resolve
            roots = resolve()
            pointer_path = publication_pointer_path(roots)
        pointer = Path(pointer_path)
        if pointer.stat().st_size > 4096:
            raise ValueError("NEW_REPLAY_POINTER_SIZE_LIMIT")
        pointer_ref = json.loads(pointer.read_text(encoding="utf8"))
        if set(pointer_ref) != {"path", "sha256"}:
            raise ValueError("NEW_REPLAY_POINTER_REFERENCE_REQUIRED")
        if production and not Path(pointer_ref["path"]).resolve().is_relative_to(
                roots.backtest_root / "DEMO_FIVE_STRATEGY_PAPER_20261013_R1/descriptive_main_extension"):
            raise ValueError("NEW_REPLAY_PUBLICATION_ROOT_REQUIRED")
        return qualified_manifest(pointer_ref, baseline_sources=baseline_sources)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {**fallback, "reason": str(exc)}


def qualified_manifest(pointer_ref, *, baseline_sources=None):
    """Verify one immutable publication for both daily and per-stock readers."""
    base = SOURCES if baseline_sources is None else baseline_sources
    if set(base) != set(SOURCES):
        raise ValueError("NEW_REPLAY_EXACT_THREE_BASELINES_REQUIRED")
    fields = {"schema", "status", "candidate_ids", "window_id", "start", "first_execution_date",
              "prefix_end", "end", "as_of", "model_fit_calls", "selection_using_2026",
              "broker_action_allowed", "extensions", "calendar_qualification"}
    manifest = _metadata(pointer_ref, fields)
    end = date.fromisoformat(str(manifest["end"])).isoformat()
    if not _PREFIX_END < end < "2027-01-01":
        raise ValueError("NEW_REPLAY_COMPLETED_2026_EXTENSION_REQUIRED")
    common = {"status": "PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION", "window_id": "MAIN",
              "start": "2026-01-02", "first_execution_date": "2026-01-05", "prefix_end": _PREFIX_END,
              "end": end, "model_fit_calls": 0, "selection_using_2026": False, "broker_action_allowed": False}
    if (manifest.get("schema") != _MANIFEST_SCHEMA or tuple(manifest.get("candidate_ids", ())) != tuple(SOURCES)
            or any(manifest.get(key) != value for key, value in common.items())
            or set(manifest.get("extensions", {})) != set(SOURCES)):
        raise ValueError("NEW_REPLAY_QUALIFIED_MANIFEST_REQUIRED")
    as_of = datetime.fromisoformat(manifest["as_of"])
    calendar = manifest.get("calendar_qualification", {})
    if (calendar.get("helper") != "scripts.daily_recommendation_inputs.latest_completed_session"
            or calendar.get("target_session") != end or calendar.get("target_session_completed") is not True):
        raise ValueError("NEW_REPLAY_COMPLETED_CALENDAR_PROOF_REQUIRED")
    _verified(calendar["calendar_ref"]["path"], calendar["calendar_ref"]["sha256"])
    close = datetime.fromisoformat(calendar["session_close_utc"])
    if (as_of.tzinfo is None or close.tzinfo is None
            or close.astimezone(ZoneInfo("America/New_York")).date().isoformat() != end
            or not close <= as_of <= datetime.now(timezone.utc)):
        raise ValueError("NEW_REPLAY_COMPLETED_ASOF_REQUIRED")
    replay, stocks, completion_metadata = {}, {}, {}
    for sid in SOURCES:
        receipt_ref = manifest["extensions"][sid]
        meta = _metadata(receipt_ref, fields | {"candidate_id", "artifacts", "baseline_artifacts",
            "original_prefix_comparison", "stock_prefix_comparison", "production_qualified", "independent_holdout_claim", "source_refs"})
        completion_metadata[sid] = meta
        if (meta.get("schema") != _EXTENSION_SCHEMA or meta.get("candidate_id") != sid
                or meta.get("candidate_ids") != [sid] or meta.get("as_of") != manifest["as_of"]
                or meta.get("calendar_qualification") != calendar
                or any(meta.get(key) != value for key, value in common.items())
                or meta.get("production_qualified") is not False or meta.get("independent_holdout_claim") is not False):
            raise ValueError("NEW_REPLAY_QUALIFIED_RECEIPT_REQUIRED:" + sid)
        refs, baseline = meta.get("artifacts", {}), meta.get("baseline_artifacts", {})
        prefix = meta.get("original_prefix_comparison", {})
        if (set(refs) != set(_TABLES) or set(baseline) != set(_TABLES)
                or baseline["daily"].get("sha256") != base[sid]["sha256"]
                or prefix.get("status") != "EXACT_MATCH"
                or not prefix.get("account_prefix_identity")):
            raise ValueError("NEW_REPLAY_ORIGINAL_PREFIX_REQUIRED:" + sid)
        for name in _TABLES[:4]:
            proof = prefix.get("table_comparisons", {}).get(name, {})
            if proof.get("status") != "EXACT_MATCH" or not _same_ref(proof.get("original_ref"), baseline[name]):
                raise ValueError("NEW_REPLAY_CORE_PREFIX_REQUIRED:" + name)
        _validate_stock_prefix(meta.get("stock_prefix_comparison", {}), baseline)
        if baseline_sources is None:
            from apps.demo_console.adapters.new_strategy_stock_history_reader import _HASHES
            if any(baseline[name].get("sha256") != digest for name, digest in _HASHES[sid].items()):
                raise ValueError("NEW_REPLAY_ORIGINAL_NATIVE_HASH_REQUIRED:" + sid)
        for ref in (*refs.values(), *baseline.values()):
            _verified(ref["path"], ref["sha256"])
        replay[sid] = dict(path=refs["daily"]["path"], sha256=refs["daily"]["sha256"],
            receipt=receipt_ref["path"], receipt_sha256=receipt_ref["sha256"], research_id=base[sid]["research_id"],
            qualified_end=end, publication_path=pointer_ref["path"], publication_sha256=pointer_ref["sha256"])
        stocks[sid] = {name: refs[name] for name in ("actions", "orders", "positions", "fills")}
        stocks[sid].update(receipt=receipt_ref, extension_manifest=pointer_ref, qualified_end=end,
            baseline_refs={**{name: baseline[name] for name in ("actions", "orders", "positions", "fills")},
                "receipt": {"path": base[sid]["receipt"], "sha256": base[sid]["receipt_sha256"]}})
    finite_refs = [meta.get('source_refs', {}).get('finite_ca_admission_ref') for meta in completion_metadata.values()]
    continuation_proofs = any(meta.get('source_refs', {}).get('accepted_extension_prefix_comparison_ref') is not None
        for meta in completion_metadata.values())
    if any(ref is not None for ref in finite_refs) or continuation_proofs:
        if any(ref is None or ref != finite_refs[0] for ref in finite_refs):
            raise ValueError('NEW_REPLAY_FINITE_CA_IDENTITY_REQUIRED')
        from scripts.common.storage_paths import resolve
        from scripts.research.a2.evaluation.consensus_paper_ca_continuation import validate_published_continuation
        validate_published_continuation(resolve(), manifest_ref=pointer_ref, manifest=manifest,
            completion_receipts=completion_metadata)
    return dict(status="QUALIFIED_EXTENSION", end=end, replay_sources=replay, stock_sources=stocks,
                publication_ref=pointer_ref, as_of=manifest["as_of"])


def _validate_stock_prefix(proof, baseline):
    # The producer supplies exact closed-prefix identity and separately records
    # Oct 8 pending-order maturity. Never claim those changing fields were exact.
    if proof.get("status") != "EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY":
        raise ValueError("NEW_REPLAY_STOCK_PREFIX_REQUIRED")
    for name in ("actions", "orders"):
        part = proof.get("table_comparisons", {}).get(name, {})
        if part.get("status") != "EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY" or not _same_ref(part.get("original_ref"), baseline[name]):
            raise ValueError("NEW_REPLAY_STOCK_PREFIX_REQUIRED:" + name)
        pending = part.get("pending_maturity", {})
        columns = {"planned_execution_date"} if name == "actions" else {"execution_date", "status"}
        hashes = [pending.get("old_fields_sha256"), pending.get("new_fields_sha256")]
        if (pending.get("signal_date") != _PREFIX_END or pending.get("next_execution_date") != "2026-10-09"
                or set(pending.get("allowed_columns", ())) != columns
                or type(pending.get("changed_rows")) is not int or not 0 <= pending["changed_rows"] <= 20000
                or any(not isinstance(value, str) or len(value) != 64
                       or any(char not in "0123456789abcdef" for char in value) for value in hashes)):
            raise ValueError("NEW_REPLAY_DECLARED_PENDING_MATURITY_REQUIRED:" + name)


def _validate_catalog_source(source, sid):
    if sid != "RAW_s10":
        return
    if (source.get("universe_variant") != "CONSENSUS100" or source.get("pool_variant_id") != "TOP100"
            or source.get("selector_scope_path") != _RAW_SELECTOR_REF["path"]
            or source.get("selector_scope_sha256") != _RAW_SELECTOR_REF["sha256"]):
        raise ValueError("NEW_REPLAY_RAW_APPLICATION_SCOPE_REQUIRED")
    identity = _metadata(_RAW_SELECTOR_REF, {"schema", "task_id", "application_pool_origin",
        "new_model_or_fit", "pre2026_training_identity_unchanged"})
    if (identity.get("schema") != "ALL_A_CONSENSUS100_FROZEN_RAW_SELECTOR_APPLICATION_SCOPE_R2"
            or identity.get("task_id") != "A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1"
            or identity.get("application_pool_origin") != "CONSENSUS_TOP100_FULL_PIT32_APPLICATION_POOL"
            or identity.get("new_model_or_fit") is not False
            or identity.get("pre2026_training_identity_unchanged") is not True):
        raise ValueError("NEW_REPLAY_RAW_APPLICATION_SCOPE_REQUIRED")


def _scan_history(source, strategy_ids, cutoff):
    """One bounded scanner per identical physical daily/receipt reference."""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.dataset as ds
    from scripts.common.json_projection import metadata_fields
    receipt = _verified(source["receipt"], source["receipt_sha256"])
    with receipt.open("rb") as stream:
        identity = metadata_fields(stream, {"candidate_ids"})
    if not set(strategy_ids) <= set(identity.get("candidate_ids", [])):
        raise ValueError("NEW_REPLAY_CANDIDATE_RECEIPT_MISMATCH")
    dataset = ds.dataset(_verified(source["path"], source["sha256"]), format="parquet")
    columns = ["path_id", "date", "nav", "net_return", "research_cash_weight", "transaction_cost_amount", "turnover", "actual_name_count", "stale_count", "unknown_count", "accounting_qualified"]
    if not set(columns) <= set(dataset.schema.names):
        raise ValueError("NEW_REPLAY_PROJECTED_SCHEMA_REQUIRED")
    typ = dataset.schema.field("date").type
    first = "2026-01-02" if (pa.types.is_string(typ) or pa.types.is_large_string(typ)) else pd.Timestamp("2026-01-02").to_pydatetime()
    last = cutoff if (pa.types.is_string(typ) or pa.types.is_large_string(typ)) else pd.Timestamp(cutoff).to_pydatetime()
    rule = ds.field("path_id").isin(strategy_ids) & (ds.field("date") >= first) & (ds.field("date") <= last)
    parts, count = [], 0
    for batch in dataset.scanner(columns=columns, filter=rule, batch_size=256, use_threads=False,
                                 batch_readahead=1, fragment_readahead=1).to_batches():
        count += batch.num_rows
        if count > 253 * len(strategy_ids):
            raise ValueError("NEW_REPLAY_ONE_YEAR_ROW_LIMIT")
        parts.append(batch.to_pandas())
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)


def _optional_count(value):
    import pandas as pd
    if pd.isna(value):
        return None
    if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0 or not float(value).is_integer():
        raise ValueError("NEW_REPLAY_QUALITY_COUNT_INVALID")
    return int(value)


def _optional_bool(value):
    import pandas as pd
    import numpy as np
    if pd.isna(value):
        return None
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError("NEW_REPLAY_ACCOUNTING_FLAG_INVALID")
    return bool(value)


def _project_history(frame, source, sid, cutoff):
    import pandas as pd
    frame = frame.loc[frame.path_id.eq(sid)].copy()
    if len(frame) > 253:
        raise ValueError("NEW_REPLAY_ONE_YEAR_ROW_LIMIT")
    if frame.empty:
        return dict(status="UNAVAILABLE", daily=[], summary=None, start=None, end=None, price_basis=_NOTE)
    frame["date"] = pd.to_datetime(frame.date).dt.strftime("%Y-%m-%d")
    frame = frame.sort_values("date")
    if source.get("qualified_end") and cutoff >= source["qualified_end"] and frame.iloc[-1].date != source["qualified_end"]:
        raise ValueError("NEW_REPLAY_PUBLISHED_END_RECORD_REQUIRED")
    if frame.date.duplicated().any() or frame.iloc[0].date != "2026-01-02":
        raise ValueError("NEW_REPLAY_INITIAL_CASH_RECORD_REQUIRED")
    baseline = float(frame.iloc[0].nav)
    if not math.isfinite(baseline) or baseline <= 0:
        raise ValueError("NEW_REPLAY_INITIAL_NAV_INVALID")
    daily = []
    for row in frame.itertuples(index=False):
        nav, cash = float(row.nav), float(row.research_cash_weight)
        if not math.isfinite(nav) or nav <= 0 or not math.isfinite(cash) or not 0 <= cash <= 1:
            raise ValueError("NEW_REPLAY_RECORDED_NAV_OR_CASH_INVALID")
        net = float(row.net_return) if pd.notna(row.net_return) else None
        previous = daily[-1]["nav"] if daily else 1.0
        if net is not None and not math.isclose(net, nav / baseline / previous - 1, rel_tol=1e-8, abs_tol=1e-10):
            raise ValueError("NEW_REPLAY_NAV_RETURN_IDENTITY_INVALID")
        cost = float(row.transaction_cost_amount)
        if not math.isfinite(cost) or cost < 0:
            raise ValueError("NEW_REPLAY_COST_INVALID")
        daily.append(dict(date=row.date, nav=nav / baseline, net_return=net, gross_return=None,
            cash_weight=cash, transaction_cost_amount=cost / baseline, native_transaction_cost_amount=cost,
            turnover=float(row.turnover), holding_count=_optional_count(row.actual_name_count),
            stale_mark_count=_optional_count(row.stale_count), unknown_mark_count=_optional_count(row.unknown_count),
            accounting_qualified=_optional_bool(row.accounting_qualified)))
    # Keep the initial cash observation for correct first-execution/window baselines.
    executed = [point for point in daily if point["date"] >= "2026-01-05"]
    return dict(status="AVAILABLE" if executed else "UNAVAILABLE", daily=daily, summary=None,
        start=executed[0]["date"] if executed else None, end=executed[-1]["date"] if executed else None,
        price_basis=_NOTE, benchmark_qualification="UNAVAILABLE_DIFFERENT_PRICE_COORDINATE",
        native_initial_nav=baseline, window_id="MAIN", first_execution_date="2026-01-05",
        source_ref={"path": source["path"], "sha256": source["sha256"]},
        receipt_ref={"path": source["receipt"], "sha256": source["receipt_sha256"]},
        publication_ref={"path": source["publication_path"], "sha256": source["publication_sha256"]}
            if source.get("publication_path") else None)



def _history(source, sid, cutoff):
    _validate_catalog_source(source, sid)
    return _project_history(_scan_history(source, (sid,), cutoff), source, sid, cutoff)


def model_identity(strategy_id, *, research_id=None):
    """Return the existing frozen identity without reading models or ledgers."""
    identity = deepcopy(_MODEL_IDENTITIES[strategy_id])
    if strategy_id not in SOURCES:
        # Accepted frozen range boundary; not evidence of a record on that day.
        identity["frozen_main_end"] = _PREFIX_END
    return dict(candidate_id=strategy_id,
        research_id=CATALOG_SOURCES[strategy_id]["research_id"] if research_id is None else research_id,
        model_role="FROZEN_PRE2026_STATE_2026_INFERENCE_ONLY", **identity)


@lru_cache(maxsize=1)
def _cached(cutoff, refs):
    result, groups = {}, {}
    for sid, entries in refs:
        source = dict(entries)
        identity = model_identity(sid, research_id=source["research_id"])
        result[sid] = dict(model_identity=identity,
            provenance=dict(window_id="MAIN", scope="FIXED_ACCEPTED_DESCRIPTIVE_REPLAY", note=_NOTE))
        try:
            _validate_catalog_source(source, sid)
            key = tuple(source[field] for field in ("path", "sha256", "receipt", "receipt_sha256")) + (source.get("history_bound", cutoff),)
            groups.setdefault(key, []).append((sid, source))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result[sid]["history"] = _unavailable_history(exc)
    for group in groups.values():
        try:
            frame = _scan_history(group[0][1], tuple(sid for sid, _ in group), group[0][1].get("history_bound", cutoff))
        except (OSError, ValueError, KeyError, TypeError, NotImplementedError) as exc:
            for sid, _ in group:
                result[sid]["history"] = _unavailable_history(exc)
            continue
        for sid, source in group:
            try:
                result[sid]["history"] = _project_history(frame, source, sid, source.get("history_bound", cutoff))
            except (OSError, ValueError, KeyError, TypeError, NotImplementedError) as exc:
                result[sid]["history"] = _unavailable_history(exc)
    return result


def _unavailable_history(reason):
    return dict(status="UNAVAILABLE", daily=[], summary=None, start=None, end=None,
                price_basis=_NOTE, reason=str(reason))


def _strategy_ids(strategy_ids, default):
    ids = tuple(default if strategy_ids is None else strategy_ids)
    if not ids or len(set(ids)) != len(ids) or any(sid not in CATALOG_IDS for sid in ids):
        raise ValueError("NEW_REPLAY_QUERYABLE_STRATEGY_IDS_REQUIRED")
    return ids


def _observed_sources(sources):
    identities, observed = [], {}
    for sid, ref in sources.items():
        current = dict(ref)
        for field, key in (("path", "observed_source_sha256"), ("receipt", "observed_receipt_sha256")):
            if ref[field] not in observed:
                observed[ref[field]] = observed_ref({"path": ref[field]})
            current[key] = observed[ref[field]]
        if sid == "RAW_s10":
            current["observed_selector_scope_sha256"] = observed_ref(_RAW_SELECTOR_REF)
        identities.append((sid, tuple(sorted(current.items()))))
    return tuple(identities)


def load_views(cutoff, *, history_cutoff=None, sample="test_2026", sources=None, strategy_ids=None):
    if sample != "test_2026" or cutoff is None:
        return {}
    bound = history_cutoff or cutoff
    date.fromisoformat(str(bound))
    if not "2026-01-01" <= str(bound) < "2027-01-01":
        return {}
    ids = _strategy_ids(strategy_ids, SOURCES if sources is None else sources)
    publication = (qualified_sources() if any(sid in SOURCES for sid in ids) else
        {"status": "FALLBACK_ACCEPTED_PREFIX", "end": _PREFIX_END, "replay_sources": {}}) if sources is None else {
            "status": "SYNTHETIC_OR_PINNED_SOURCES", "end": _PREFIX_END, "replay_sources": sources}
    selected = {}
    for sid in ids:
        source = (publication["replay_sources"].get(sid, CATALOG_SOURCES[sid])
                  if sources is None else sources[sid])
        # Each source keeps its own accepted end. Mixed queries must not erase
        # a verified v1 extension or lend that extension to a frozen addition.
        selected[sid] = {**source, "history_bound": min(str(bound),
            publication["end"] if sid in SOURCES else _PREFIX_END)}
    limit = min(str(bound), publication["end"])
    result = deepcopy(_cached(limit, _observed_sources(selected)))
    for sid, view in result.items():
        old_publication = sid in SOURCES
        view["provenance"].update(extension_status=publication["status"] if old_publication else "FROZEN_MAIN_PREFIX_ONLY",
            publication_ref=publication.get("publication_ref") if old_publication else None,
            extension_reason=publication.get("reason") if old_publication else None)
    return result


def read_catalog(*, strategy_ids=None, sample="test_2026", sources=None):
    """Describe only the six frozen policies on their common accepted prefix.

    This is an exposed-sample display comparison, never fitting, independent
    validation, runtime source admission or authorization to trade.
    """
    if sample != "test_2026":
        return {}
    from apps.demo_console.components.performance_stats import summarize_nav_window
    ids = _strategy_ids(strategy_ids, CATALOG_IDS)
    selected = {sid: (CATALOG_SOURCES if sources is None else sources)[sid] for sid in ids}
    views = deepcopy(_cached(_PREFIX_END, _observed_sources(selected)))
    for view in views.values():
        history = view["history"]
        daily = history["daily"]
        executed = [point for point in daily if "2026-01-05" <= point["date"] <= _PREFIX_END]
        fields = ("stale_mark_count", "unknown_mark_count")
        view["qualification"] = {
            "initial_observation": daily[0]["date"] if daily else None,
            "last_observation": daily[-1]["date"] if daily else None,
            "observation_rows": len(daily), "execution_rows": len(executed),
            "accounting_qualified_days": sum(point["accounting_qualified"] is True for point in executed),
            "accounting_unqualified_days": sum(point["accounting_qualified"] is False for point in executed),
            "accounting_unknown_days": sum(point["accounting_qualified"] is None for point in executed),
            **{field: sum(point[field] for point in executed) if all(point[field] is not None for point in executed) else None
               for field in fields},
            **{field + "_missing_days": sum(point[field] is None for point in executed) for field in fields},
            "full_common_prefix": bool(daily and daily[0]["date"] == "2026-01-02"
                and history["start"] == "2026-01-05" and history["end"] == _PREFIX_END),
        }
        view["summary"] = summarize_nav_window(daily, "2026-01-05", _PREFIX_END) if executed else None
        view["provenance"].update(scope="EXPOSED_2026_COMMON_PREFIX_DISPLAY_COMPARISON",
            independent_holdout_claim=False, production_qualified=False, selection_changes_model=False,
            extension_status="FROZEN_MAIN_PREFIX_ONLY")
    return dict(candidate_ids=ids, window=dict(initial_observation="2026-01-02",
        first_execution_date="2026-01-05", end=_PREFIX_END, one_way_bps=10,
        metrics_owner="apps.demo_console.components.performance_stats.summarize_nav_window"), views=views)
