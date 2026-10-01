"""Recover execution OHLC from accepted A2 price lineage without new inference.

The frozen raw-plus-forward-rehab adapter owns corporate-action mathematics.
This reader neither substitutes QFQ nor fills missing sessions. Later vendor
rehab snapshots retain their recorded, nonhistorical publication semantics.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts import daily_recommendation_prices as original
from scripts.daily_recommendation_inputs import MODEL_ID, MODEL_SHA256
from scripts.research.a2.inference.historical_top40_prices import _merge_raw

PRICE_COLUMNS = ["ticker", "trade_date", "open", "close", "high", "low", "volume"]
EVENT_COLUMNS = ["ticker", "event_date", "audit_kind"]
EXECUTION_BRIDGE_TICKERS = frozenset({"APLD", "WOLF", "FN", "KLAR", "CAI", "HIVE", "SDGR", "SFIX", "TEAM", "TEM", "XENE"})
RECENT_EXECUTION_BRIDGE_TICKERS = frozenset({"CAI", "HIVE", "SDGR", "SFIX", "TEAM", "TEM", "XENE"})
NATIVE_SUPPLEMENT_TICKERS = frozenset({"AMPL", "SLMT"})
EXECUTION_GATE = "FIVE_EXACT_OHLC_AND_ALL_OVERLAP_EXACT_OPEN_CLOSE_V1"
EVENT_REVIEW_POLICY = "TIER1_3_CONFIRMED_NON_CORPORATE_ACTION_ONLY"


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _current_entries(path, historical_path, historical_sha, verify):
    report_path = Path(path).resolve()
    report_sha = original.digest(report_path)
    report = _json(verify(report_path, report_sha))
    if (report.get("status") != "READY" or report.get("model_id") != MODEL_ID
            or report.get("model_sha256") != MODEL_SHA256
            or Path(report["report_path"]).resolve() != report_path):
        raise ValueError("EXECUTION_CURRENT_REPORT_IDENTITY_INVALID")
    lineage_path = report_path.parent / "input_lineage.json"
    lineage_sha = original.digest(lineage_path)
    lineage = _json(verify(lineage_path, lineage_sha))
    if isinstance(lineage, dict):
        if lineage_sha != report.get("input_manifest_sha256"):
            raise ValueError("EXECUTION_CURRENT_LINEAGE_HASH_MISMATCH")
        reference = lineage.get("historical_manifest", {})
        if (Path(reference.get("path", "")).resolve() != historical_path
                or reference.get("sha256") != historical_sha):
            raise ValueError("EXECUTION_CURRENT_HISTORICAL_BINDING_MISMATCH")
        return [], report
    if not isinstance(lineage, list):
        raise ValueError("EXECUTION_CURRENT_LINEAGE_SCHEMA_INVALID")
    canonical_sha = hashlib.sha256(json.dumps(lineage, sort_keys=True).encode()).hexdigest()
    if canonical_sha != report.get("input_manifest_sha256"):
        raise ValueError("EXECUTION_CURRENT_LINEAGE_HASH_MISMATCH")
    receipt_path = report_path.parent / "rehab_receipt.json"
    receipt = _json(verify(receipt_path, original.digest(receipt_path)))
    if (receipt.get("source") != "MOOMOO_OPEND_GET_REHAB"
            or receipt.get("target_date") != report["data_date"]):
        raise ValueError("EXECUTION_CURRENT_REHAB_RECEIPT_INVALID")
    passed = [row for row in receipt.get("results", []) if row.get("status") == "PASS"]
    if len({row["code"] for row in passed}) != len(passed):
        raise ValueError("EXECUTION_DUPLICATE_REHAB_CODE")
    factors = {row["code"]: row for row in passed}
    result = []
    for recorded in lineage:
        entry = dict(recorded)
        if "rehab" not in entry:
            factor = factors.get(entry["code"], {})
            if (factor.get("sha256") != entry.get("rehab_sha256")
                    or factor.get("fetched_at") != entry.get("rehab_fetched_at")
                    or entry.get("adapter_sha256") != original.ADAPTER_SHA
                    or entry.get("coverage_manifest_sha256") != original.COVERAGE_SHA):
                raise ValueError("EXECUTION_CURRENT_PRICE_PROOF_MISMATCH")
            entry["rehab"] = {**factor, "kind": "CURRENT_SNAPSHOT"}
        entry.setdefault("raw_end", report["data_date"])
        result.append(entry)
    return result, report


def _inference_entries(path, historical_path, historical_sha, historical_end, report, verify):
    if path is None:
        return []
    path = Path(path).resolve()
    manifest = _json(verify(path, original.digest(path)))
    if report is None:
        raise ValueError("EXECUTION_INFERENCE_CURRENT_REPORT_REQUIRED")
    historical = manifest.get("historical_manifest", {})
    current = manifest.get("current_report", {})
    current_path = Path(report["report_path"]).resolve()
    if (manifest.get("schema") != "A2_MISSED_SESSION_INFERENCE_V1"
            or manifest.get("status") != "READY" or Path(manifest.get("report_path", "")).resolve() != path
            or manifest.get("model_sha256") != MODEL_SHA256 or manifest.get("model_fit_count") != 0
            or Path(historical.get("path", "")).resolve() != historical_path
            or historical.get("sha256") != historical_sha
            or Path(current.get("path", "")).resolve() != current_path
            or current.get("sha256") != original.digest(current_path)
            or manifest.get("end_date") != report["data_date"]
            or not (historical_end < manifest.get("start_date", "") <= report["data_date"])):
        raise ValueError("EXECUTION_INFERENCE_MANIFEST_BINDING_MISMATCH")
    verify(current_path, current["sha256"])
    reference = manifest["price_manifest"]
    inputs = _json(verify(reference["path"], reference["sha256"]))
    if not isinstance(inputs, dict) or not isinstance(inputs.get("lineage"), list):
        raise ValueError("EXECUTION_INFERENCE_PRICE_LINEAGE_INVALID")
    return inputs["lineage"]


def _current_execution_records(path, historical_path, historical_sha, report, verify):
    """Bind offline execution-only records without replacing catalog authority."""
    if path is None:
        return {}
    if report is None:
        raise ValueError("CURRENT_EXECUTION_REPORT_REQUIRED")
    path = Path(path).resolve()
    manifest = _json(verify(path, original.digest(path)))
    historical, current = manifest.get("historical_manifest", {}), manifest.get("current_report", {})
    current_path = Path(report["report_path"]).resolve()
    records = manifest.get("catalog_records")
    if (manifest.get("schema") != "A2_CURRENT_EXECUTION_PRICE_RECORDS_V1"
            or manifest.get("gate") != EXECUTION_GATE
            or manifest.get("model_feature_eligibility_granted") is not False
            or manifest.get("target_date") != report["data_date"]
            or Path(historical.get("path", "")).resolve() != historical_path
            or historical.get("sha256") != historical_sha
            or Path(current.get("path", "")).resolve() != current_path
            or current.get("sha256") != original.digest(current_path)
            or not isinstance(records, list) or not records):
        raise ValueError("CURRENT_EXECUTION_MANIFEST_BINDING_MISMATCH")
    verify(current_path, current["sha256"])
    acquisition = manifest["acquisition_manifest"]
    verify(acquisition["path"], acquisition["sha256"])
    result = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("CURRENT_EXECUTION_RECORD_IDENTITY_INVALID")
        ticker = record.get("ticker")
        if (ticker not in RECENT_EXECUTION_BRIDGE_TICKERS or ticker in result
                or record.get("dataset") != "prices_daily_massive"
                or record.get("source") != "MASSIVE_GROUPED" or record.get("adjustment") != "raw"
                or record.get("format") != "parquet" or record.get("max_date") != report["data_date"]):
            raise ValueError("CURRENT_EXECUTION_RECORD_IDENTITY_INVALID")
        verify(record["path"], record["source_sha256"])
        result[ticker] = record
    return result


def qualify_execution_massive_tail(record, native, ticker, target, store, raw_cache=None):
    """Separate execution-only qualification; never grants feature eligibility."""
    if ticker not in EXECUTION_BRIDGE_TICKERS:
        raise ValueError("EXECUTION_BRIDGE_TICKER_NOT_AUTHORIZED")
    native = native.sort_values("trade_date")
    recent = native.tail(5)
    if len(recent) != 5:
        raise ValueError("EXECUTION_BRIDGE_REQUIRES_FIVE_NATIVE_SESSIONS")
    frame, proof = original._massive_raw_window(record, ticker,
        recent.trade_date.min().date().isoformat(), target, store, raw_cache)
    path = original.verify(record["path"], record["source_sha256"])
    entire = pd.read_parquet(path)
    entire["trade_date"] = pd.to_datetime(entire.date).dt.normalize()
    if (not entire.ticker.eq(ticker).all() or not entire.source.eq("MASSIVE_GROUPED").all()
            or not entire.adjustment.eq("raw").all() or not entire.currency.eq("USD").all()
            or not entire.provider_code.eq(proof["provider_symbol"]).all()
            or entire.trade_date.duplicated().any()):
        raise ValueError("EXECUTION_BRIDGE_FULL_IDENTITY_INVALID")
    overlap = native.merge(entire, on="trade_date", suffixes=("_native", "_massive"))
    five = recent.merge(frame, on="trade_date", suffixes=("_native", "_massive"))
    if len(five) != 5:
        raise ValueError("EXECUTION_BRIDGE_FIVE_SESSION_GAP")
    for field in ("open", "high", "low", "close"):
        if not five[field + "_native"].eq(five[field + "_massive"]).all():
            raise ValueError("EXECUTION_BRIDGE_RECENT_OHLC_MISMATCH:" + field)
    for field in ("open", "close"):
        if not overlap[field + "_native"].eq(overlap[field + "_massive"]).all():
            raise ValueError("EXECUTION_BRIDGE_FULL_EXECUTION_PRICE_MISMATCH:" + field)
    tail = frame.loc[frame.trade_date > native.trade_date.max(), ["trade_date", *original.PRICE_FIELDS]]
    if tail.empty or tail.trade_date.max() != pd.Timestamp(target):
        raise ValueError("EXECUTION_BRIDGE_NO_TARGET_TAIL")
    differences = {field: {"max_absolute_difference": float((overlap[field + "_native"] - overlap[field + "_massive"]).abs().max()),
        "unequal_rows": int(overlap[field + "_native"].ne(overlap[field + "_massive"]).sum())}
        for field in original.PRICE_FIELDS}
    return tail, {**proof, "gate": EXECUTION_GATE, "consumer_fields": ["open", "close"],
        "model_feature_eligibility_granted": False, "overlap_count": len(overlap),
        "recent_overlap_dates": recent.trade_date.dt.strftime("%Y-%m-%d").tolist(),
        "overlap_differences": differences, "tail_start": tail.trade_date.min().date().isoformat(),
        "tail_end": target}


def _alias_source_ticker(entry, proof):
    if proof is None:
        return entry["ticker"]
    from scripts.research.a2.inference.current_native_prices import validate_explicit_alias
    identities = entry.get("security_ids") or [entry.get("security_id")]
    return validate_explicit_alias(proof, entry["ticker"], entry["code"], identities)


def _native_anchor(entry, verify):
    """Revalidate the bound provider leaves, without consulting today's catalog."""
    from scripts.research.a2.inference.current_native_prices import _read_source
    proof = entry["anchor_proof"]
    source = proof.get("native_source", {})
    sources = entry.get("raw_sources", [])
    identities = entry.get("security_ids")
    dated_union_identity = (entry.get("membership_validation") == "REQUIRES_DOWNSTREAM_DAILY_PIT_JOIN"
        and entry.get("security_id") is None and isinstance(identities, list) and bool(identities)
        and all(isinstance(value, str) and bool(value) for value in identities)
        and identities == sorted(set(identities)))
    if (proof.get("scope") != "2026_INFERENCE_ONLY" or proof.get("old_frozen_equivalence_claimed") is not False
            or (not entry.get("security_id") and not dated_union_identity)
            or entry.get("raw_end", "") < "2026-01-01"
            or len(sources) != 1 or sources[0].get("role") != "NATIVE_MOOMOO_ANCHOR"
            or {key: value for key, value in sources[0].items() if key != "role"} != source
            or source.get("provider") != "MOOMOO_OPEND" or source.get("provider_code") != entry["code"]
            or source.get("adjustment") != "RAW" or not source.get("raw_inputs")):
        raise ValueError("EXECUTION_NATIVE_ANCHOR_PROOF_INVALID")
    path = verify(source["path"], source["sha256"])
    frame = pd.read_parquet(path)
    source_ticker = _alias_source_ticker(entry, source.get("transport_alias_proof"))
    if (not {"ticker", "provider_code", "source", "adjustment", "source_id"} <= set(frame)
            or not frame.ticker.eq(source_ticker).all() or not frame.provider_code.eq(entry["code"]).all()
            or not frame.source.eq("MOOMOO_OPEND").all() or not frame.adjustment.eq("raw").all()):
        raise ValueError("EXECUTION_NATIVE_NORMALIZED_IDENTITY_INVALID")
    refs = {row["sha256"]: row for row in source["raw_inputs"]}
    if frame.source_id.isna().any() or not set(frame.source_id) <= set(refs):
        raise ValueError("EXECUTION_NATIVE_RAW_LEAF_MISSING")
    for identity, part in frame.groupby("source_id"):
        ref = refs[identity]
        leaf = _read_source(verify(ref["path"], ref["sha256"]), source_ticker, entry["code"])
        normalized = original._raw_frame(part, entry["code"])
        compared = normalized.merge(leaf, on="trade_date", suffixes=("_normalized", "_leaf"), validate="one_to_one")
        if len(compared) != len(normalized) or any(not np.array_equal(compared[field + "_normalized"],
                compared[field + "_leaf"]) for field in original.PRICE_FIELDS):
            raise ValueError("EXECUTION_NATIVE_NORMALIZED_LEAF_MISMATCH")
    raw = _merge_raw([original._raw_frame(frame, entry["code"])])
    return raw.loc[raw.trade_date.between(pd.Timestamp(entry["anchor_date"]), pd.Timestamp(entry["raw_end"]))]


def _replay_alternate(entry, native, verify, store, raw_cache):
    recorded = entry["alternate_bridge"]
    provider = recorded.get("provider")
    if provider == "MASSIVE_GROUPED":
        alias = recorded.get("transport_alias_proof")
        source_ticker = _alias_source_ticker(entry, alias)
        if alias is not None and alias != entry.get("anchor_proof", {}).get("native_source", {}).get("transport_alias_proof"):
            raise ValueError("EXECUTION_BRIDGE_ALIAS_DIFFERS_FROM_NATIVE_ANCHOR")
        # Reconstruct only the immutable acquisition identity already recorded
        # by the qualified bridge; a new catalog vintage cannot replace it.
        refs = [{key: row[key] for key in ("path", "sha256", "date", "observed_at")}
                for row in recorded["raw_inputs"]]
        record = {"dataset": "prices_daily_massive", "ticker": source_ticker, "source": provider,
            "adjustment": "raw", "format": "parquet", "path": recorded["normalized_path"],
            "source_sha256": recorded["normalized_sha256"], "max_date": entry["raw_end"],
            "lineage": {"schema_version": 1, "role": "PROVIDER_DAILY_PRICE_SNAPSHOT", "provider": provider,
                "date_column": "date", "price_basis": "RAW", "currency": "USD",
                "exchange_timezone": "America/New_York", "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT",
                "provider_symbol": recorded["provider_symbol"], "provider_mapping": recorded["provider_mapping"],
                "inputs": refs}}
        tail, proof = original._qualified_massive_tail(record, native, source_ticker, entry["raw_end"], store, raw_cache,
            gap_dates=recorded.get("gap_fill", {}).get("requested_dates"))
        if alias is not None:
            proof["transport_alias_proof"] = alias
    elif provider == "YAHOO_CHART":
        receipt = recorded.get("acquisition_receipt")
        if not receipt:
            raise ValueError("EXECUTION_YAHOO_ACQUISITION_RECEIPT_MISSING")
        tail, proof = original._qualified_yahoo_tail(receipt, native, entry["ticker"], entry["raw_end"])
    else:
        raise ValueError("EXECUTION_RECORDED_BRIDGE_PROVIDER_INVALID")
    if proof != recorded:
        raise ValueError("EXECUTION_RECORDED_BRIDGE_QUALIFICATION_CHANGED")
    if provider == "MASSIVE_GROUPED":
        verify(proof["normalized_path"], proof["normalized_sha256"])
        for ref in proof["raw_inputs"]:
            verify(ref["path"], ref["sha256"])
            verify(ref["checkpoint_path"], ref["checkpoint_sha256"])
    else:
        for ref in proof["acquisition_receipt"]["files"]:
            verify(ref["path"], ref["sha256"])
    return tail


def _raw(entry, verify, store=None, raw_cache=None):
    if (entry.get("price_basis") != "PIT_FORWARD_REHAB_INDEX"
            or not entry.get("code") or not entry.get("ticker")):
        raise ValueError("EXECUTION_RECORDED_PRICE_IDENTITY_INVALID")
    anchor, end = pd.Timestamp(entry["anchor_date"]), pd.Timestamp(entry["raw_end"])
    if pd.isna(anchor) or pd.isna(end) or anchor > end:
        raise ValueError("EXECUTION_RECORDED_PRICE_RANGE_INVALID")
    parts = []
    sources = entry["raw_sources"]
    native = entry.get("anchor_proof", {}).get("kind") == "NEW_13F_MEMBER_NATIVE_RAW_ANCHOR"
    if native:
        parts.append(_native_anchor(entry, verify))
    elif not sources or not any(row.get("role") == "ORIGINAL_ANCHOR" for row in sources):
        raise ValueError("EXECUTION_ORIGINAL_ANCHOR_MISSING")
    for reference in (() if native else sources):
        path = verify(reference["path"], reference["sha256"])
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path)
        else:
            names = pq.read_schema(path).names
            frame = (pq.read_table(path, columns=original.RAW_COLUMNS,
                     filters=[("code", "=", entry["code"])]).to_pandas()
                     if set(original.RAW_COLUMNS) <= set(names) else pd.read_parquet(path))
        frame = original._raw_frame(frame, entry["code"])
        parts.append(frame.loc[frame.trade_date.between(anchor, end)])
    frame = _merge_raw(parts)
    alternate = entry.get("alternate_bridge")
    if alternate:
        if entry.get("execution_bridge"):
            raise ValueError("EXECUTION_DUPLICATE_BRIDGE_ROLES")
        frame = _merge_raw([frame, _replay_alternate(entry, frame, verify, store, raw_cache)])
    bridge = entry.get("execution_bridge")
    if bridge:
        tail, proof = qualify_execution_massive_tail(bridge["catalog_record"], frame,
            entry["ticker"], entry["raw_end"], store, raw_cache)
        if proof != bridge["qualification"]:
            raise ValueError("EXECUTION_BRIDGE_QUALIFICATION_CHANGED")
        verify(proof["normalized_path"], proof["normalized_sha256"])
        for ref in proof["raw_inputs"]:
            verify(ref["path"], ref["sha256"])
            verify(ref["checkpoint_path"], ref["checkpoint_sha256"])
        frame = _merge_raw([frame, tail])
    if frame.empty or frame.trade_date.min() != anchor or frame.trade_date.max() != end:
        raise ValueError("EXECUTION_RECORDED_ANCHOR_OR_END_CHANGED")
    return frame


def _adjust(entry, adapter, wolf, verify, factor_cache, store, raw_cache):
    raw = _raw(entry, verify, store, raw_cache)
    reference = entry["rehab"]
    path = verify(reference["path"], reference["sha256"])
    key = (str(path), reference["sha256"])
    if key not in factor_cache:
        factor_cache[key] = pd.read_parquet(path)
    factors = factor_cache[key]
    if "code" not in factors:
        raise ValueError("EXECUTION_REHAB_CODE_MISSING")
    if reference.get("kind") == "CURRENT_SNAPSHOT" and not factors.code.eq(entry["code"]).all():
        raise ValueError("EXECUTION_REHAB_CODE_MISMATCH")
    frame, events = adapter.adjusted_price_frame(entry["code"], entry["ticker"], raw, factors, wolf)
    if (frame.duplicated(["ticker", "trade_date"]).any()
            or not np.isfinite(frame[original.PRICE_FIELDS].to_numpy(float)).all()
            or (frame[["open", "high", "low", "close"]] <= 0).any().any()):
        raise ValueError("EXECUTION_ADJUSTED_PRICE_VALUES_INVALID")
    if entry.get("anchor_proof", {}).get("kind") == "NEW_13F_MEMBER_NATIVE_RAW_ANCHOR":
        frame = frame.loc[frame.trade_date >= pd.Timestamp("2026-01-01")]
        events = [event for event in events if pd.Timestamp(event["event_date"]) >= pd.Timestamp("2026-01-01")]
    return frame[PRICE_COLUMNS], events


def _validated_event_review(path, historical_sha, supplement_sha, events, selected, verify):
    if not path.is_file():
        return None
    reference = {"path": str(path.resolve()), "sha256": original.digest(path)}
    review = _json(verify(path, reference["sha256"]))
    if (review.get("schema") != "A2_EXECUTION_EVENT_REVIEW_V1"
            or review.get("policy") != EVENT_REVIEW_POLICY
            or review.get("review_type") != "AGENT_EVIDENCE_REVIEW"
            or review.get("historical_manifest_sha256") != historical_sha
            or review.get("execution_price_supplement_sha256") != supplement_sha
            or review.get("prices_or_share_quantities_changed") is not False
            or not review.get("evidence_refs")):
        raise ValueError("EXECUTION_EVENT_REVIEW_CONTRACT_MISMATCH")
    for item in review["evidence_refs"]:
        verify(item["path"], item["sha256"])
    actual = {(row.ticker, row.code, pd.Timestamp(row.event_date).date().isoformat(),
               row.audit_kind, float(row.raw_jump)) for row in events.itertuples()
              if row.audit_kind == "LARGE_RAW_MOVE_NO_VENDOR_EVENT"}
    seen = set()
    for row in review["records"]:
        key = (row["ticker"], row["code"], row["event_date"], row["audit_kind"], float(row["raw_jump"]))
        if (key in seen or row.get("status") != "RESOLVED_NON_CORPORATE_ACTION"
                or row["audit_kind"] != "LARGE_RAW_MOVE_NO_VENDOR_EVENT"
                or not np.isfinite(key[-1]) or row.get("prices_or_share_quantities_changed") is not False):
            raise ValueError("EXECUTION_EVENT_REVIEW_RECORD_INVALID")
        seen.add(key)
        if row["ticker"] in selected and key not in actual:
            raise ValueError("EXECUTION_EVENT_REVIEW_DOES_NOT_MATCH_RECORDED_EVENT")
    return reference


def load_execution_prices(paths, historical_manifest_path, *, tickers=None,
                          current_report_path=None, start=None, end=None,
                          additional_price_manifest_path=None, event_review_manifest_path=None,
                          inference_manifest_path=None, current_execution_manifest_path=None):
    """Return prices/events/gaps/refs; perform no writes, requests or returns.

    ``prices`` uses ticker, trade_date and the original adjusted OHLCV. Missing
    dates stay absent. The execution owner decides whether a required holding
    price is unavailable and where a defensible accounting prefix must stop.
    """
    checked = {}

    def verify(path, expected):
        path = Path(path).resolve()
        key = str(path)
        if key in checked and checked[key] != expected:
            raise ValueError("EXECUTION_CONFLICTING_SOURCE_HASH")
        if key not in checked:
            original.verify(path, expected)
            checked[key] = expected
        return path

    historical_path = Path(historical_manifest_path).resolve()
    historical_sha = original.digest(historical_path)
    manifest = _json(verify(historical_path, historical_sha))
    canonical_path = Path(manifest["report_path"]).resolve()
    if canonical_path != historical_path:
        if (historical_path.name != "latest.json"
                or not canonical_path.is_relative_to(historical_path.parent / "runs")):
            raise ValueError("EXECUTION_HISTORICAL_POINTER_PATH_INVALID")
        verify(canonical_path, historical_sha)
        historical_path = canonical_path
    if (manifest.get("schema_version") != 1 or manifest.get("status") not in {"READY", "PARTIAL"}
            or Path(manifest["report_path"]).resolve() != historical_path):
        raise ValueError("EXECUTION_HISTORICAL_MANIFEST_INVALID")
    reference = manifest["price_manifest"]
    inputs = _json(verify(reference["path"], reference["sha256"]))
    historical = inputs["lineage"]
    current, report = ([], None) if current_report_path is None else _current_entries(
        current_report_path, historical_path, historical_sha, verify)
    current_execution_records = _current_execution_records(current_execution_manifest_path,
        historical_path, historical_sha, report, verify)
    replayed = _inference_entries(inference_manifest_path, historical_path, historical_sha,
        manifest["end_date"], report, verify)
    start = str(start or manifest["start_date"])
    last = max(manifest["end_date"], report["data_date"] if report else manifest["end_date"])
    end = str(end or last)
    if start < manifest["start_date"] or start > end or end > last:
        raise ValueError("EXECUTION_REQUEST_OUTSIDE_RECORDED_RANGE")
    coverage_path = Path(paths.backtest_root) / "research/a2/demo_2026_calendar_replay/input_coverage.json"
    coverage = _json(verify(coverage_path, original.COVERAGE_SHA))
    wolf = {"event_date": coverage["adjustment"]["wolf_event_date"],
            "quantity_multiplier": coverage["adjustment"]["wolf_new_shares_per_old_share"]}
    verify(original.ADAPTER_PATH, original.ADAPTER_SHA)
    adapter = original._adapter(end)
    supplement_path = (Path(additional_price_manifest_path) if additional_price_manifest_path else
        Path(paths.daily_root) / "A2_updated_research/execution_price_inputs" / manifest["run_id"] / "manifest.json")
    supplements, supplement_sha = [], None
    if supplement_path.is_file():
        supplement_sha = original.digest(supplement_path)
        supplement = _json(verify(supplement_path, supplement_sha))
        if (supplement.get("schema") != "A2_EXECUTION_PRICE_SUPPLEMENT_V1"
                or supplement.get("historical_manifest_sha256") != historical_sha
                or supplement.get("gate") != EXECUTION_GATE
                or supplement.get("model_feature_eligibility_granted") is not False):
            raise ValueError("EXECUTION_SUPPLEMENT_CONTRACT_MISMATCH")
        supplements = supplement["lineage"]
        if any(row["ticker"] not in EXECUTION_BRIDGE_TICKERS | NATIVE_SUPPLEMENT_TICKERS for row in supplements):
            raise ValueError("EXECUTION_SUPPLEMENT_TICKER_NOT_AUTHORIZED")
    elif additional_price_manifest_path:
        raise ValueError("EXECUTION_SUPPLEMENT_MANIFEST_MISSING")
    selected = set(tickers) if tickers is not None else {row["ticker"] for row in historical + current + supplements + replayed}
    histories, updates, additions, missing_signals = {}, {}, {}, {}
    for rows, destination in ((historical, histories), (supplements, additions), (replayed, missing_signals), (current, updates)):
        for row in rows:
            ticker = row["ticker"]
            if ticker in destination:
                raise ValueError("EXECUTION_DUPLICATE_RECORDED_TICKER")
            destination[ticker] = row
    from scripts.research.a2.inference.historical_top40_prices import _store
    store = _store(paths) if (report is not None and selected & RECENT_EXECUTION_BRIDGE_TICKERS) or any(row.get("execution_bridge") or row.get("alternate_bridge")
        for row in historical + current + supplements + replayed) else None
    frames, all_events, gaps, factor_cache, raw_cache = [], [], [], {}, {}
    execution_bridges = []
    fresh_rehab = None
    for ticker in sorted(selected):
        built, events, first_entry = None, [], None
        for role, entry in (("HISTORICAL", histories.get(ticker)), ("EXECUTION_SUPPLEMENT", additions.get(ticker)),
                            ("REPLAYED_MISSING_SIGNALS", missing_signals.get(ticker)),
                            ("CURRENT", updates.get(ticker))):
            if entry is None:
                continue
            try:
                if pd.Timestamp(entry["raw_end"]) > pd.Timestamp(last):
                    raise ValueError("EXECUTION_PRICE_BEYOND_RECORDED_END")
                frame, event_rows = _adjust(entry, adapter, wolf, verify, factor_cache, store, raw_cache)
                if built is not None:
                    old = first_entry
                    if entry["code"] != old["code"] or entry["anchor_date"] != old["anchor_date"]:
                        raise ValueError("EXECUTION_CURRENT_ANCHOR_IDENTITY_CHANGED")
                    overlap = built.merge(frame, on=["ticker", "trade_date"], suffixes=("_old", "_new"))
                    fields = (["open", "close"] if role == "CURRENT" and
                        additions.get(ticker, {}).get("execution_bridge") else original.PRICE_FIELDS)
                    if overlap.empty or any(not overlap[field + "_old"].eq(overlap[field + "_new"]).all()
                                            for field in fields):
                        raise ValueError("EXECUTION_CURRENT_ADJUSTED_OVERLAP_CHANGED")
                    frame = pd.concat([built, frame.loc[~frame.trade_date.isin(built.trade_date)]], ignore_index=True)
                built = frame
                if first_entry is None:
                    first_entry = entry
                events.extend(event_rows)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                gaps.append({"ticker": ticker, "source_role": role, "reason": str(exc)})
        if built is None:
            gaps.append({"ticker": ticker, "reason": "EXECUTION_ACCEPTED_PRICE_LINEAGE_UNAVAILABLE"})
            continue
        if (ticker in RECENT_EXECUTION_BRIDGE_TICKERS and report is not None
                and end == report["data_date"] and built.trade_date.max() < pd.Timestamp(end)):
            try:
                historical_entry = histories[ticker]
                if first_entry["code"] != historical_entry["code"]:
                    raise ValueError("EXECUTION_BRIDGE_HISTORICAL_IDENTITY_CHANGED")
                if fresh_rehab is None:
                    receipt_path = Path(report["report_path"]).parent / "rehab_receipt.json"
                    fresh_rehab = _json(verify(receipt_path, original.digest(receipt_path)))
                    if (fresh_rehab.get("source") != "MOOMOO_OPEND_GET_REHAB"
                            or fresh_rehab.get("target_date") != end):
                        raise ValueError("EXECUTION_BRIDGE_FRESH_REHAB_RECEIPT_INVALID")
                factors = [row for row in fresh_rehab.get("results", [])
                           if row.get("code") == historical_entry["code"] and row.get("status") == "PASS"]
                if len(factors) != 1:
                    raise ValueError("EXECUTION_BRIDGE_FRESH_REHAB_MISSING")
                factor = factors[0]
                close = pd.Timestamp(end).tz_localize("America/New_York") + pd.Timedelta(hours=16)
                if pd.Timestamp(factor["fetched_at"]) < close:
                    raise ValueError("EXECUTION_BRIDGE_REHAB_PREDATES_CLOSE")
                factor_path = verify(factor["path"], factor["sha256"])
                key = (str(factor_path), factor["sha256"])
                if key not in factor_cache:
                    factor_cache[key] = pd.read_parquet(factor_path)
                if ("code" not in factor_cache[key]
                        or not factor_cache[key].code.eq(historical_entry["code"]).all()):
                    raise ValueError("EXECUTION_BRIDGE_REHAB_CODE_MISMATCH")
                raw = _raw(historical_entry, verify, store, raw_cache)
                if raw.trade_date.max() != built.trade_date.max():
                    raise ValueError("EXECUTION_BRIDGE_PREFIX_DATE_CHANGED")
                record = current_execution_records.get(ticker)
                if record is None:
                    record = store.metadata("prices_daily_massive", ticker, "raw")
                verify(record["path"], record["source_sha256"])
                tail, proof = qualify_execution_massive_tail(record, raw, ticker, end, store, raw_cache)
                verify(proof["normalized_path"], proof["normalized_sha256"])
                for ref in proof["raw_inputs"]:
                    verify(ref["path"], ref["sha256"])
                    verify(ref["checkpoint_path"], ref["checkpoint_sha256"])
                combined = pd.concat([raw, tail], ignore_index=True).sort_values("trade_date")
                adjusted, new_events = adapter.adjusted_price_frame(
                    historical_entry["code"], ticker, combined, factor_cache[key], wolf)
                overlap = built.merge(adjusted, on=["ticker", "trade_date"], suffixes=("_old", "_new"))
                if (len(overlap) != len(built) or any(not overlap[field + "_old"].eq(overlap[field + "_new"]).all()
                        for field in ("open", "high", "low", "close"))):
                    raise ValueError("EXECUTION_BRIDGE_ADJUSTED_PREFIX_CHANGED")
                if any(pd.Timestamp(event["event_date"]) > built.trade_date.max() for event in new_events):
                    raise ValueError("EXECUTION_BRIDGE_NEW_CORPORATE_ACTION_REVIEW_REQUIRED")
                extension = adjusted.loc[adjusted.trade_date.gt(built.trade_date.max())]
                if extension.empty or extension.trade_date.max() != pd.Timestamp(end):
                    raise ValueError("EXECUTION_BRIDGE_TARGET_PRICE_MISSING")
                built = pd.concat([built, extension], ignore_index=True)
                execution_bridges.append({"ticker": ticker, "historical_end": str(raw.trade_date.max().date()),
                    "target_date": end, "qualification": proof,
                    "rehab": {"path": str(factor_path), "sha256": factor["sha256"],
                              "fetched_at": factor["fetched_at"]},
                    "model_feature_eligibility_granted": False})
            except (ValueError, KeyError, TypeError, OSError) as exc:
                gaps.append({"ticker": ticker, "source_role": "RECENT_EXECUTION_BRIDGE", "reason": str(exc)})
        frames.append(built.loc[built.trade_date.between(pd.Timestamp(start), pd.Timestamp(end))])
        all_events.extend(events)
    prices = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)
    events = pd.DataFrame(all_events) if all_events else pd.DataFrame(columns=EVENT_COLUMNS)
    if not events.empty:
        events = events.drop_duplicates().reset_index(drop=True)
        events = events.loc[pd.to_datetime(events.event_date).between(pd.Timestamp(start), pd.Timestamp(end))]
    review_path = Path(event_review_manifest_path) if event_review_manifest_path else supplement_path.with_name("event_review.json")
    event_review = _validated_event_review(review_path, historical_sha, supplement_sha, events, selected, verify)
    if event_review_manifest_path and event_review is None:
        raise ValueError("EXECUTION_EVENT_REVIEW_MANIFEST_MISSING")
    # A changed input invalidates the whole read, including successful tickers.
    for path, expected in checked.items():
        original.verify(path, expected)
    return {"prices": prices.sort_values(["trade_date", "ticker"]).reset_index(drop=True),
            "events": events, "gaps": gaps, "event_review": event_review,
            "execution_bridges": execution_bridges,
            "refs": [{"path": path, "sha256": sha} for path, sha in sorted(checked.items())],
            "start_date": start, "end_date": end,
            "price_basis": "PIT_FORWARD_REHAB_INDEX",
            "vintage_semantics": "LATER_VENDOR_REHAB_SNAPSHOT_NOT_HISTORICAL_PUBLICATION_VINTAGE"}
