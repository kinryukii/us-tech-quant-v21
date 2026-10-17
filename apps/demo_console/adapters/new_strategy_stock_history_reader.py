"""Exact-ticker views of fixed MAIN research actions, orders, holdings and fills.

These records are descriptive research evidence, never paper-account fills.
No stock rank or CUSIP is inferred from ticker-only native ledgers.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from datetime import date
from functools import lru_cache
import json
import math
from pathlib import Path
import re

from apps.demo_console.adapters.new_strategy_replay_reader import SOURCES as REPLAY_SOURCES, CATALOG_SOURCES, _verified, observed_ref, qualified_sources, qualified_manifest, _validate_catalog_source

_FIRST, _LAST = "2026-01-02", "2026-10-08"
_HASHES = {
    "R10_DIRECT_MEAN4_ELASTICNET_MID": {
        "actions": "20735e266db503251608d355f7a2053827618041b9bae420691d8284745a0ce5",
        "orders": "5b94a743f83a562aca2b6eb5674e43b5b654a8970b13d37307940b4457bce6e0",
        "positions": "d147d8f8edeed9d1cbfda48846b90bcb9a399ee1c7a139933bbc8a90928c4cd4",
        "fills": "c3e5810b83a28860fb3f7cf3b8542de558d0ea225fc8174806466c1908ff6a21"},
    "R10_DIRECT_H5_RIDGE_MID": {
        "actions": "fadf60d113a4bd875e4e3908d38a29a2a1279e1ae0ef251a58ecbde8ce6689be",
        "orders": "f89f56b33bf97861ac4f29eea5163adfd606452a81eaca421ac8642e72e23942",
        "positions": "3bba4e5d80eff8c968e2141da17b767ae8d42becaf2addff8e93f6b17d1fe6ea",
        "fills": "8d07e58258ebc9adfcd210ab19166676c7b6cf9de67ded2f7842a54fba1940cd"},
    "R7_GROSS_LINEAR": {
        "actions": "e134481305e2df7704c695a6dcb6e46daba8ef7affe304936ef8b738e913203f",
        "orders": "8a68411cc561464fe583721dc297e456e02a104c4ea085759da7e3741f7d1cf8",
        "positions": "c4639921fb9e49a2cdfc9643e068c0958ac34d6b912d84f3cd43270bfb451c2d",
        "fills": "10ee1a8344123912fe66d4ce242e6d0d53103fc99126784e18c6df11095951ef"}}
_RIDGE_SHARED_IDS = ("R10_DIRECT_H5_RIDGE_MID", "R6_BUY_NEURAL", "R6_DURATION_TREE")
_CATALOG_HASHES = {
    **_HASHES,
    **{sid: _HASHES["R10_DIRECT_H5_RIDGE_MID"] for sid in _RIDGE_SHARED_IDS[1:]},
    "RAW_s10": {
        "actions": "121e062777bad8ee76ed6ceeed43c299bce3d138d0b12056dd3c51cd73b2cf71",
        "orders": "8b37e6e9ff408ad6f8529f5cb2e22f7f5627e37960c9333ebef3b7fd57fa5146",
        "positions": "b2007b036e43ba48771f7fcdf0a9a94be3d435bf6e7f04fe9dc33c64237d6f17",
        "fills": "fc8297e8a6658c74a27dbcb1a6f1418a624dbc2aeb2dd301106120b068a4072c"},
}
_COLUMNS = {
    "actions": ("signal_date", "ticker", "policy_explicit", "policy_weight", "policy_action", "actual_weight", "planned_execution_date"),
    "orders": ("signal_date", "ticker", "execution_date", "target_weight", "adapted_target_weight", "hold_units", "decision_semantic", "status"),
    "positions": ("date", "ticker", "weight", "fractional_shares", "mark_date", "stale", "unknown", "accounting_qualified"),
    "fills": ("execution_date", "signal_date", "ticker", "side", "actual_fill_price", "fractional_shares", "actual_fill_notional", "transaction_fee"),
}
_NOTE = "固定 MAIN 研究逐股记录；原动作、计划权重、研究持仓和研究成交分别保留。原表未记录股票模型排名和 CUSIP，因此保持未知；不是模拟账户成交。"


def source_refs(*, bundle=None, strategy_ids=None):
    """Keep the original three-strategy publication and extra frozen refs separate."""
    ids = tuple(_HASHES if strategy_ids is None else strategy_ids)
    if len(set(ids)) != len(ids) or not set(ids) <= set(_CATALOG_HASHES):
        raise ValueError("NATIVE_STOCK_CANDIDATE_SCOPE_REQUIRED")
    chosen = (qualified_sources() if bundle is None else bundle) if set(ids) & set(_HASHES) else {}
    # Keep full v1 custody until it is checked, then append only frozen additions.
    result = deepcopy(chosen["stock_sources"]) if chosen.get("status") == "QUALIFIED_EXTENSION" else {}
    for sid in ids:
        if sid in result:
            continue
        replay, hashes = CATALOG_SOURCES[sid], _CATALOG_HASHES[sid]
        folder = Path(replay["path"]).parent
        if sid in _RIDGE_SHARED_IDS or sid == "RAW_s10":
            folder = folder.parent / "attempt_001"
        result[sid] = {name: {"path": str(folder / (name + ".parquet")), "sha256": digest}
                       for name, digest in hashes.items()}
        result[sid]["receipt"] = {"path": replay["receipt"], "sha256": replay["receipt_sha256"]}
        if sid in _RIDGE_SHARED_IDS:
            result[sid]["recovery"] = {"path": str(Path(replay["path"]).parent / "saved_replay_recovery.json"),
                "sha256": "875ad64cc803ccaae28a5ab83ef1a4e5eeafa3fddc9d85cd99c44ba6d8415a17"}
        if sid == "RAW_s10":
            result[sid].update(universe_variant=replay["universe_variant"], pool_variant_id=replay["pool_variant_id"],
                selector_scope={"path": replay["selector_scope_path"], "sha256": replay["selector_scope_sha256"]})
    return result


def _day(value):
    return str(value.date()) if hasattr(value, "date") else date.fromisoformat(str(value)[:10]).isoformat()


def _finite(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _rows(ref, sid, kind, ticker, start, end, *, columns=None):
    import pandas as pd
    import pyarrow as pa
    import pyarrow.dataset as ds
    dataset = ds.dataset(_verified(ref["path"], ref["sha256"]), format="parquet")
    selected = _COLUMNS[kind] if columns is None else tuple(columns)
    if not set(selected) <= set(_COLUMNS[kind]):
        raise ValueError("NATIVE_STOCK_PROJECTED_COLUMNS_REQUIRED")
    required = ("path_id", *selected)
    if not set(required) <= set(dataset.schema.names):
        raise ValueError("NATIVE_STOCK_PROJECTED_SCHEMA_REQUIRED:" + kind)
    clock = "date" if kind == "positions" else "execution_date" if kind == "fills" else "signal_date"
    typ = dataset.schema.field(clock).type
    first = start if pa.types.is_string(typ) else pd.Timestamp(start).to_pydatetime()
    last = end if pa.types.is_string(typ) else pd.Timestamp(end).to_pydatetime()
    rule = ((ds.field("path_id") == sid)
            & (ds.field(clock) >= first) & (ds.field(clock) <= last))
    if ticker is not None:
        rule &= ds.field("ticker") == ticker
    row_limit = 4096 if ticker is None else 2048
    rows = []
    scanner = dataset.scanner(columns=list(required), filter=rule, batch_size=256,
        use_threads=False, batch_readahead=1, fragment_readahead=1)
    for batch in scanner.to_batches():
        if len(rows) + batch.num_rows > row_limit:
            raise ValueError(("NATIVE_STOCK_DAY_ROW_LIMIT:" if ticker is None
                              else "NATIVE_STOCK_EXACT_TICKER_ROW_LIMIT:") + kind)
        for raw in batch.to_pylist():
            row = {key: _day(value) if key.endswith("date") and value is not None else value
                   for key, value in raw.items() if key != "path_id"}
            rows.append(row)
    return rows


def _validate_receipt(refs, sid):
    from scripts.common.json_projection import metadata_fields
    if sid == "RAW_s10":
        scope = refs.get("selector_scope", {})
        _validate_catalog_source({"universe_variant": refs.get("universe_variant"),
            "pool_variant_id": refs.get("pool_variant_id"), "selector_scope_path": scope.get("path"),
            "selector_scope_sha256": scope.get("sha256")}, sid)
    receipt = _verified(refs["receipt"]["path"], refs["receipt"]["sha256"])
    with receipt.open("rb") as stream:
        identity = metadata_fields(stream, {"candidate_ids"})
    if sid not in identity.get("candidate_ids", ()):
        raise ValueError("NATIVE_STOCK_RECEIPT_IDENTITY_MISMATCH")
    if "recovery" in refs:
        recovery = _verified(refs["recovery"]["path"], refs["recovery"]["sha256"])
        with recovery.open("rb") as stream:
            meta = metadata_fields(stream, {"account_replay", "new_fit", "raw_artifact_refs"})
        if meta.get("account_replay") != 0 or meta.get("new_fit") != 0 or any(
                meta.get("raw_artifact_refs", {}).get(name) != refs[name] for name in _COLUMNS):
            raise ValueError("NATIVE_STOCK_ORIGINAL_RESTORE_BINDING_REQUIRED")


def _project(refs, sid, ticker, start, end):
    _validate_receipt(refs, sid)
    groups = {name: _rows(refs[name], sid, name, ticker, start, end) for name in _COLUMNS}
    daily = defaultdict(dict)
    for row in groups["actions"]:
        day = row["signal_date"]
        if "native_action" in daily[day]:
            raise ValueError("NATIVE_STOCK_DUPLICATE_ACTION")
        daily[day].update(native_action=row["policy_action"], research_weight_before=_finite(row["actual_weight"]),
            original_policy_weight=_finite(row["policy_weight"]), policy_explicit=row["policy_explicit"],
            planned_execution_date=row["planned_execution_date"])
    orders = defaultdict(list)
    for row in groups["orders"]:
        orders[row["signal_date"]].append(row)
    for day, items in orders.items():
        values = {_finite(row.get("adapted_target_weight")) if _finite(row.get("adapted_target_weight")) is not None
                  else _finite(row.get("target_weight")) for row in items}
        value = next(iter(values)) if len(values) == 1 else None
        daily[day].update(target_weight=value, selected=value > 0 if value is not None else None,
            target_kind="RECORDED_RESEARCH_SIGNAL_PLAN", weight_date=day,
            target_status="READY" if value is not None else "NO_RECORDED_TARGET", research_orders=items)
    for row in groups["positions"]:
        day = row["date"]
        if "research_weight" in daily[day]:
            raise ValueError("NATIVE_STOCK_DUPLICATE_HOLDING")
        daily[day].update(research_weight=_finite(row["weight"]), research_units=_finite(row["fractional_shares"]),
            research_mark_date=row["mark_date"], research_stale=row["stale"], research_unknown=row["unknown"],
            research_accounting_qualified=row["accounting_qualified"])
    for row in groups["fills"]:
        daily[row["execution_date"]].setdefault("research_fills", []).append(row)
    return {day: {"model_rank": None, "score": None, "raw_input_rank": None, "raw_input_score": None,
        "score_status": "NO_VERIFIED_SCORE", "security_id": None,
        "security_identity_status": "TICKER_ONLY_NO_RECORDED_CUSIP", "evidence_kind": "FIXED_MAIN_RESEARCH_LEDGER",
        "target_weight": None, "selected": None, "weight_date": None, "target_kind": None,
        "target_status": "NO_RECORDED_TARGET", **value} for day, value in daily.items()}


@lru_cache(maxsize=1)
def _cached(ticker, start, end, sources_key):
    import json
    result = {}
    for sid, raw_refs, observed_hashes in sources_key:
        refs = json.loads(raw_refs)
        try:
            accepted_end = end if sid in _HASHES else min(end, _LAST)
            if start > accepted_end:
                result[sid] = {"status": "UNAVAILABLE", "daily": {}, "source_refs": refs,
                    "error": "RESEARCH_DAY_EXCEEDS_ACCEPTED_END"}
                continue
            result[sid] = {"status": "READY", "daily": _project(refs, sid, ticker, start, accepted_end), "source_refs": refs}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result[sid] = {"status": "UNAVAILABLE", "daily": {}, "source_refs": refs, "error": str(exc)}
    return result


def _bound_sources(chosen, end):
    bound = _LAST
    if any(refs.get("extension_manifest") for refs in chosen.values()):
        extended = {sid: refs for sid, refs in chosen.items() if refs.get("extension_manifest")}
        manifests = {json.dumps(refs["extension_manifest"], sort_keys=True) for refs in extended.values()}
        if set(extended) != set(_HASHES) or len(manifests) != 1:
            raise ValueError("NATIVE_STOCK_SINGLE_THREE_STRATEGY_PUBLICATION_REQUIRED")
        publication = qualified_manifest(json.loads(next(iter(manifests))))
        if extended != publication["stock_sources"]:
            raise ValueError("NATIVE_STOCK_PUBLICATION_BINDING_CHANGED")
        bound = publication["end"]
        if date.fromisoformat(str(end)).isoformat() <= _LAST:
            chosen = {sid: ({**refs["baseline_refs"], "qualified_publication_ref": publication["publication_ref"]}
                           if sid in extended else refs) for sid, refs in chosen.items()}
            bound = _LAST
    return chosen, bound


def query(ticker, start, end, *, sources=None, strategy_ids=None):
    import json
    ticker = str(ticker).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,11}", ticker):
        return {"strategies": {}, "note": _NOTE}
    ids = tuple(_HASHES if sources is None else sources) if strategy_ids is None else tuple(strategy_ids)
    if len(set(ids)) != len(ids) or not set(ids) <= set(_CATALOG_HASHES):
        raise ValueError("NATIVE_STOCK_CANDIDATE_SCOPE_REQUIRED")
    chosen = source_refs(strategy_ids=ids) if sources is None else sources
    if set(chosen) - set(_CATALOG_HASHES):
        raise ValueError("NATIVE_STOCK_CANDIDATE_SCOPE_REQUIRED")
    missing = tuple(sid for sid in ids if sid not in chosen)
    chosen, bound = _bound_sources(chosen, end)
    chosen = {sid: chosen[sid] for sid in ids if sid in chosen}
    start, end = max(date.fromisoformat(str(start)).isoformat(), _FIRST), min(date.fromisoformat(str(end)).isoformat(), bound)
    if start > end:
        return {"strategies": {}, "note": _NOTE}
    key = tuple((sid, json.dumps(refs, sort_keys=True),
                 tuple((name, observed_ref(ref)) for name, ref in refs.items()
                       if isinstance(ref, dict) and "path" in ref)) for sid, refs in chosen.items())
    result = deepcopy(_cached(ticker, start, end, key))
    result.update({sid: {"status": "UNAVAILABLE", "daily": {}, "source_refs": {},
        "error": "NATIVE_STOCK_SOURCE_UNAVAILABLE"} for sid in missing})
    return {"strategies": {sid: result[sid] for sid in ids}, "note": _NOTE}

def _research_day(refs, sid, day):
    """Project recorded signal decisions; never infer holdings, ranks or cash."""
    _validate_receipt(refs, sid)
    actions = _rows(refs["actions"], sid, "actions", None, day, day,
        columns=("signal_date", "ticker", "policy_explicit", "policy_weight", "policy_action", "actual_weight"))
    # Later order execution/status maturity is not a same-signal input.
    orders = _rows(refs["orders"], sid, "orders", None, day, day,
        columns=("signal_date", "ticker", "target_weight", "adapted_target_weight", "hold_units", "decision_semantic"))
    values = {}
    for row in actions:
        ticker = row["ticker"]
        if ticker in values:
            raise ValueError("RESEARCH_DAY_DUPLICATE_ACTION")
        values[ticker] = dict(ticker=ticker, action=row["policy_action"],
            policy_explicit=row["policy_explicit"], original_policy_weight=_finite(row["policy_weight"]),
            research_weight_before=_finite(row["actual_weight"]))
    by_ticker = defaultdict(list)
    for row in orders:
        by_ticker[row["ticker"]].append(row)
    for ticker, items in by_ticker.items():
        if len({json.dumps(item, sort_keys=True) for item in items}) != 1:
            raise ValueError("RESEARCH_DAY_CONFLICTING_ORDERS")
        original = items[0]
        adapted = _finite(original["adapted_target_weight"])
        weight = adapted if adapted is not None else _finite(original["target_weight"])
        values.setdefault(ticker, {"ticker": ticker}).update(target_weight=weight,
            selected=weight > 0 if weight is not None else None,
            research_order_target_weight=_finite(original["target_weight"]), adapted_target_weight=adapted,
            hold_units=_finite(original["hold_units"]), decision_semantic=original["decision_semantic"],
            research_orders=deepcopy(items))
    # An identity change during the read cannot become a successful cached view.
    for name in ("actions", "orders", "receipt"):
        _verified(refs[name]["path"], refs[name]["sha256"])
    return [{"model_rank": None, "score": None, "raw_rank": None, "raw_score": None,
        "source_score": None, "security_id": None, "security_identity_status": "TICKER_ONLY_NO_RECORDED_CUSIP",
        "target_weight": None, "selected": None, "weight_date": day,
        "target_kind": "RECORDED_RESEARCH_SIGNAL_PLAN", "source_kind": "research", **values[ticker]}
        for ticker in sorted(values)]


@lru_cache(maxsize=1)
def _cached_rankings(day, sources_key):
    result = {}
    for sid, raw_refs, observed_hashes in sources_key:
        refs = json.loads(raw_refs)
        try:
            if sid not in _HASHES and day > _LAST:
                raise ValueError("RESEARCH_DAY_EXCEEDS_ACCEPTED_END")
            rows = _research_day(refs, sid, day)
            result[sid] = dict(status="AVAILABLE" if rows else "UNAVAILABLE", rows=rows,
                source_kind="research", actual_signal_date=day if rows else None,
                weight_date=day if rows else None, target_kind="RECORDED_RESEARCH_SIGNAL_PLAN",
                scope="RECORDED_MAIN_RESEARCH", source_refs=refs)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result[sid] = dict(status="BLOCKED", rows=[], source_kind="research", error=str(exc))
    return result


def rankings(day, *, cutoff=None, strategy_ids=None, sources=None):
    """Single-date MAIN evidence, independent of any current PAPER plan."""
    for value in (day, cutoff if cutoff is not None else day):
        if (not isinstance(value, str) or date.fromisoformat(value).isoformat() != value
                or not "2026-01-01" <= value < "2027-01-01"):
            raise ValueError("RESEARCH_DAY_EXACT_2026_DATE_REQUIRED")
    if day > (cutoff if cutoff is not None else day):
        raise ValueError("RESEARCH_DAY_EXCEEDS_SELECTED_CUTOFF")
    ids = tuple(_HASHES if sources is None else sources) if strategy_ids is None else tuple(strategy_ids)
    if len(set(ids)) != len(ids) or not set(ids) <= set(_CATALOG_HASHES):
        raise ValueError("NATIVE_STOCK_CANDIDATE_SCOPE_REQUIRED")
    try:
        publication = qualified_sources() if sources is None and not (set(ids) - set(_HASHES)) else None
        chosen = source_refs(bundle=publication, strategy_ids=ids) if sources is None else sources
        if set(chosen) - set(_CATALOG_HASHES):
            raise ValueError("NATIVE_STOCK_CANDIDATE_SCOPE_REQUIRED")
        missing = tuple(sid for sid in ids if sid not in chosen)
        chosen, bound = _bound_sources(chosen, day)
        if day > bound:
            raise ValueError((publication or {}).get("reason") or "RESEARCH_DAY_EXCEEDS_ACCEPTED_END")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return dict(status="BLOCKED", requested_date=day, source_kind="research",
            strategies={sid: dict(status="BLOCKED", rows=[], source_kind="research", error=str(exc)) for sid in ids})
    key = tuple((sid, json.dumps(chosen[sid], sort_keys=True),
        tuple((name, observed_ref(ref)) for name, ref in chosen[sid].items()
              if isinstance(ref, dict) and "path" in ref)) for sid in ids if sid in chosen)
    result = deepcopy(_cached_rankings(day, key))
    result.update({sid: {"status": "BLOCKED", "rows": [], "source_kind": "research",
        "error": "NATIVE_STOCK_SOURCE_UNAVAILABLE"} for sid in missing})
    result = {sid: result[sid] for sid in ids}
    return dict(status="READY" if result and all(v["status"] == "AVAILABLE" for v in result.values())
                else "PARTIAL", strategies=result, requested_date=day, source_kind="research")

