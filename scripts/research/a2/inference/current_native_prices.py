"""Current-2026 inference inputs for explicitly added, verified 13F securities.

The old frozen anchor and equivalence paths retain their original gates. This
path accepts only their explicit ORIGINAL_RAW_ANCHOR_UNBOUND exclusions, never
a failed equivalence/rehab/overlap result. It uses native Moomoo raw provenance,
the original event-date adjustment, and the same frozen 32-feature function.
There is no fitting, provider request, historical publication, or catalog write.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from collections import OrderedDict
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from scripts import daily_recommendation_prices as prices
from scripts.research.a2.inference.historical_top40_prices import _rehab_frame, _merge_raw, _append_raw


SQ_TRANSPORT_ALIAS = {
    "logical_ticker": "SQ", "source_ticker": "XYZ", "provider_code": "US.XYZ",
    "security_id": "852234103", "rule": "REGISTERED_CUSIP_AND_ISSUER_TICKER_CHANGE",
    "evidence_url": "https://investors.block.xyz/investor-news/news-details/2025/Block-Announces-Ticker-Symbol-Change-to-XYZ-To-Report-Fourth-Quarter-Results/default.aspx",
}


def validate_explicit_alias(proof, ticker, code, security_ids):
    """Validate the one reviewed issuer/registry alias; never infer code aliases."""
    if (proof != SQ_TRANSPORT_ALIAS or ticker != "SQ" or code != "US.XYZ"
            or not security_ids or set(security_ids) != {"852234103"}):
        raise ValueError("NATIVE_EXPLICIT_TRANSPORT_ALIAS_INVALID")
    return proof["source_ticker"]


class _RunCache:
    """Bounded projections; every unique source hash is rechecked before return."""
    def __init__(self, codes):
        self.codes = set(codes)
        self.checked = {}
        self.frames = OrderedDict()

    def verify(self, path, expected):
        path = Path(path)
        key = str(path.resolve())
        stat = path.stat()
        identity = (stat.st_size, stat.st_mtime_ns)
        old = self.checked.get(key)
        if old is not None:
            if old != (expected, identity):
                raise ValueError("NATIVE_SOURCE_CHANGED_DURING_READ")
        else:
            prices.verify(path, expected)
            self.checked[key] = (expected, identity)
        return path

    def finish(self):
        for path, (expected, _) in self.checked.items():
            prices.verify(path, expected)


def _read_source(path, ticker, code, cache=None):
    """Project only raw price/transport fields from a bound provider leaf."""
    path = Path(path)
    identity = ["ticker", "code", "moomoo_symbol", "provider_code", "source", "adjustment"]
    dates = ["trade_date", "date", "time_key"]
    allowed = set(identity + dates + prices.PRICE_FIELDS)
    key = str(path.resolve())
    frame = cache.frames.get(key) if cache is not None else None
    if frame is not None:
        cache.frames.move_to_end(key)
    elif path.suffix.lower() == ".csv":
        wanted_codes = cache.codes if cache is not None else {code}
        pieces = []
        for chunk in pd.read_csv(path, usecols=lambda name: name in allowed, chunksize=50000):
            transport = next((field for field in ("code", "moomoo_symbol", "provider_code") if field in chunk), None)
            if transport is None:
                raise ValueError("NATIVE_RAW_LEAF_TRANSPORT_UNBOUND")
            pieces.append(chunk.loc[chunk[transport].isin(wanted_codes)])
        frame = pd.concat(pieces, ignore_index=True)
    elif path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq
        columns = [name for name in pq.read_schema(path).names if name in allowed]
        frame = pq.read_table(path, columns=columns).to_pandas()
    else:
        raise ValueError("NATIVE_RAW_SOURCE_FORMAT_UNSUPPORTED")
    if cache is not None and key not in cache.frames and len(frame) <= 250000:
        while cache.frames and (len(cache.frames) >= 2 or sum(len(item) for item in cache.frames.values()) + len(frame) > 250000):
            cache.frames.popitem(last=False)
        cache.frames[key] = frame
    codes = [field for field in ("code", "moomoo_symbol", "provider_code") if field in frame]
    if not codes:
        raise ValueError("NATIVE_RAW_LEAF_TRANSPORT_UNBOUND")
    frame = frame.loc[frame[codes[0]].eq(code)].copy()
    if frame.empty or "source" not in frame or "adjustment" not in frame:
        raise ValueError("NATIVE_RAW_LEAF_IDENTITY_OR_BASIS_UNBOUND")
    return _merge_raw([prices._raw_frame(frame, code)])


def _native_raw(store, ticker, code, target, cache=None, transport_alias_proof=None):
    verify = cache.verify if cache is not None else prices.verify
    source_ticker = ticker
    if transport_alias_proof is not None:
        source_ticker = validate_explicit_alias(transport_alias_proof, ticker, code,
                                               [transport_alias_proof.get("security_id")])
    record = store.metadata("prices_daily", source_ticker, "raw")
    if (record.get("dataset"), record.get("ticker"), record.get("adjustment"), record.get("source")) != (
            "prices_daily", source_ticker, "raw", "MOOMOO_OPEND"):
        raise ValueError("NATIVE_RAW_CATALOG_PROVIDER_MISMATCH")
    if record.get("format") != "parquet":
        raise ValueError("NATIVE_RAW_PARQUET_REQUIRED")
    path = verify(record["path"], record.get("source_sha256"))
    refs = store.resolve_price_inputs(record, verify_raw=False)
    if not refs:
        raise ValueError("NATIVE_RAW_LEAF_PROVENANCE_MISSING")
    by_hash = {item["sha256"]: item for item in refs}
    frame = store.daily(source_ticker, "raw", end_date=target,
                        columns=["date", "ticker", *prices.PRICE_FIELDS, "source", "adjustment", "provider_code", "source_id"])
    verify(path, record["source_sha256"])
    if (frame.empty or not frame.ticker.eq(source_ticker).all() or not frame.provider_code.eq(code).all()
            or not frame.source.eq("MOOMOO_OPEND").all() or not frame.adjustment.eq("raw").all()
            or frame.source_id.isna().any() or not set(frame.source_id) <= set(by_hash)):
        raise ValueError("NATIVE_RAW_ROW_PROVENANCE_MISMATCH")
    raw = _merge_raw([prices._raw_frame(frame, code)])
    checked = []
    for identity, part in frame.groupby("source_id", sort=True):
        reference = by_hash[identity]
        source_path = verify(reference["path"], reference["sha256"])
        original = _read_source(source_path, source_ticker, code, cache)
        normalized = prices._raw_frame(part, code)
        comparison = normalized.merge(original, on="trade_date", suffixes=("_normalized", "_source"), validate="one_to_one")
        if len(comparison) != len(normalized) or any(not np.array_equal(
                comparison[field + "_normalized"].to_numpy(float), comparison[field + "_source"].to_numpy(float))
                for field in prices.PRICE_FIELDS):
            raise ValueError("NATIVE_RAW_NORMALIZED_LEAF_MISMATCH")
        checked.append({"path": str(source_path), "sha256": reference["sha256"]})
    proof = {"path": str(path), "sha256": record["source_sha256"], "raw_inputs": checked,
             "provider": "MOOMOO_OPEND", "provider_code": code, "adjustment": "RAW"}
    if transport_alias_proof is not None:
        proof["transport_alias_proof"] = dict(transport_alias_proof)
    return raw, proof


def build_current_native_features(universe, target, sessions, acquisitions, store, rehab_receipt,
                                  source, source_reference, legacy_gaps, *, observed_target=None,
                                  _signal_dates=None, _candidate_union=False):
    """Return current-date inputs; the batch wrapper returns unranked candidates."""
    signal_dates = list(_signal_dates) if _signal_dates is not None else [target]
    if (not signal_dates or signal_dates != sorted(set(signal_dates))
            or signal_dates[-1] != target or any(pd.Timestamp(day).year != 2026 for day in signal_dates)):
        raise ValueError("NATIVE_CURRENT_INFERENCE_IS_2026_ONLY")
    observed_target = observed_target or target
    if observed_target < target:
        raise ValueError("NATIVE_OBSERVATION_PRECEDES_SIGNAL")
    if not _candidate_union and (not universe.get("current") or not universe.get("universe_id")
            or not universe.get("effective_date") or universe["effective_date"] > target):
        raise ValueError("NATIVE_CURRENT_PIT_UNIVERSE_REQUIRED")
    columns = list(source.FEATURE_COLUMNS)
    if len(columns) != 32:
        raise ValueError("NATIVE_REQUIRES_ORIGINAL_32_FEATURES")
    prices.verify(source_reference["path"], source_reference["sha256"])
    days = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize()
    if days.has_duplicates or not days.is_monotonic_increasing or not set(pd.to_datetime(signal_dates)) <= set(days):
        raise ValueError("NATIVE_VERIFIED_SESSION_CALENDAR_REQUIRED")
    offset = days.get_loc(pd.Timestamp(signal_dates[0]))
    if offset < 120:
        raise ValueError("NATIVE_TARGET_NEEDS_120_PRIOR_SESSIONS")
    required = days[offset - 120:days.get_loc(pd.Timestamp(target)) + 1]
    paths = getattr(store, "paths", None)
    if paths is None:
        raise ValueError("NATIVE_STORAGE_PATHS_REQUIRED")
    coverage_path = paths.backtest_root / "research/a2/demo_2026_calendar_replay/input_coverage.json"
    coverage = json.loads(prices.verify(coverage_path, prices.COVERAGE_SHA).read_text(encoding="utf-8"))
    old_codes = set(coverage["raw"]["code_map"])
    old_tickers = {item["ticker"] for item in coverage["raw"]["code_map"].values()}
    eligible_gap = {row["ticker"] for row in legacy_gaps
                    if row.get("reasons") == ["ORIGINAL_RAW_ANCHOR_UNBOUND"]}
    members = universe["members"]
    selected = [row for row in members if row["ticker"] in eligible_gap]
    if _candidate_union:
        selected = list({row["ticker"]: row for row in selected}.values())
    native_cache = _RunCache(row.get("moomoo_symbol") or row.get("moomoo_transport_code") for row in selected)
    close = datetime.combine(pd.Timestamp(observed_target).date(), datetime.min.time(), ZoneInfo("America/New_York")) + timedelta(hours=16)
    if rehab_receipt.get("source") != "MOOMOO_OPEND_GET_REHAB" or rehab_receipt.get("target_date") != observed_target:
        raise ValueError("NATIVE_FRESH_REHAB_RECEIPT_REQUIRED")
    fresh = [row for row in rehab_receipt.get("results", []) if row.get("status") == "PASS"]
    if len({row["code"] for row in fresh}) != len(fresh):
        raise ValueError("NATIVE_DUPLICATE_REHAB_CODE")
    by_code = {row["code"]: row for row in fresh}
    adapter = prices._adapter(target)
    wolf = {"event_date": coverage["adjustment"]["wolf_event_date"],
            "quantity_multiplier": coverage["adjustment"]["wolf_new_shares_per_old_share"]}
    massive = {row["ticker"]: row for row in acquisitions.get("massive", {}).get("catalog_records", [])}
    alternate = acquisitions.get("alternate", {})
    if alternate.get("receipt"):
        alternate = json.loads(Path(alternate["receipt"]).read_text(encoding="utf-8"))
    yahoo = {row["contract"]["ticker"]: row for row in alternate.get("results", []) if row.get("status") == "SUCCESS"}
    features, lineage, gaps, raw_cache = [], [], [], {}
    for member in selected:
        ticker = member["ticker"]
        code = member.get("moomoo_symbol") or member.get("moomoo_transport_code")
        try:
            identities = [row for row in members if row["ticker"] == ticker]
            security_ids = sorted({row.get("security_id") for row in identities if row.get("security_id")})
            if (not code or not member.get("security_id") or ticker in old_tickers or code in old_codes
                    or any(not row.get("security_id") for row in identities)
                    or (not _candidate_union and len(identities) != 1)
                    or {row.get("moomoo_symbol") or row.get("moomoo_transport_code") for row in identities} != {code}
                    or {row["ticker"] for row in members if (row.get("moomoo_symbol") or row.get("moomoo_transport_code")) == code} != {ticker}):
                raise ValueError("NATIVE_IDENTITY_AMBIGUOUS_OR_ORIGINAL_FROZEN_ANCHOR")
            rehab = by_code.get(code)
            if not rehab or pd.Timestamp(rehab["fetched_at"]) < close:
                raise ValueError("NATIVE_LATEST_REHAB_MISSING_OR_PREDATES_CLOSE")
            factors = _rehab_frame(rehab["path"], rehab["sha256"], code, rehab["row_count"], native_cache.verify)
            alias = dict(SQ_TRANSPORT_ALIAS) if ticker == "SQ" else None
            if alias is not None:
                validate_explicit_alias(alias, ticker, code, security_ids)
            raw, native_proof = _native_raw(store, ticker, code, target, native_cache, alias)
            anchor_date = raw.trade_date.min().strftime("%Y-%m-%d")
            bridge, rejections = None, []
            raw_dates = set(raw.trade_date)
            gap_dates = [day.strftime("%Y-%m-%d") for day in required
                         if raw.trade_date.min() <= day <= raw.trade_date.max() and day not in raw_dates]
            if raw.trade_date.max() < pd.Timestamp(target) or gap_dates:
                # Keep immutable provider tickers intact. Only the reviewed SQ
                # alias may use XYZ; each candidate still passes the full gate.
                candidates = []
                for provider_ticker in [ticker] + ([alias["source_ticker"]] if alias else []):
                    candidate = massive.get(provider_ticker)
                    if candidate is None:
                        try:
                            candidate = store.metadata("prices_daily_massive", provider_ticker, "raw")
                        except (KeyError, FileNotFoundError):
                            pass
                    if candidate:
                        candidates.append((provider_ticker, candidate))
                for provider_ticker, candidate in candidates:
                    try:
                        if alias and provider_ticker == ticker:
                            meta = candidate.get("lineage") or json.loads(candidate.get("lineage_json") or "{}")
                            mapping = meta.get("provider_mapping", {})
                            if (mapping.get("provider_symbol") != alias["source_ticker"]
                                    or mapping.get("evidence_url") != alias["evidence_url"]):
                                raise ValueError("NATIVE_MASSIVE_ALIAS_EXPLICIT_MAPPING_REQUIRED")
                        options = {"gap_dates": gap_dates} if gap_dates else {}
                        tail, candidate_bridge = prices._qualified_massive_tail(candidate, raw, provider_ticker, target, store, raw_cache, **options)
                        raw = _append_raw(raw, tail, days)
                        bridge = ({**candidate_bridge, "transport_alias_proof": dict(alias)}
                                  if provider_ticker != ticker else candidate_bridge)
                        break
                    except (ValueError, KeyError, OSError, RuntimeError) as exc:
                        rejections.append(str(exc)); bridge = None
                if raw.trade_date.max() < pd.Timestamp(target) and ticker in yahoo:
                    try:
                        tail, bridge = prices._qualified_yahoo_tail(yahoo[ticker], raw, ticker, target)
                        raw = _append_raw(raw, tail, days)
                    except (ValueError, KeyError, OSError, RuntimeError) as exc:
                        rejections.append(str(exc)); bridge = None
            if not _candidate_union and (raw.trade_date.max() != pd.Timestamp(target) or not set(required) <= set(raw.trade_date)):
                raise ValueError("NATIVE_RAW_CONTIGUOUS_121_SESSIONS_INCOMPLETE" + (":" + ";".join(rejections) if rejections else ""))
            adjusted, events = adapter.adjusted_price_frame(code, ticker, raw, factors, wolf)
            built = source.build_stock_state_features(adjusted[["ticker", "trade_date", "close", "volume"]])
            positions = built.trade_date.map(pd.Series(np.arange(len(days)), index=days))
            contiguous = positions.diff().eq(1).rolling(120, min_periods=120).sum().eq(120)
            eligible = positions.sub(positions.shift(120)).eq(120) & contiguous & np.isfinite(built[columns].to_numpy(float)).all(axis=1)
            row = built.loc[built.trade_date.isin(pd.to_datetime(signal_dates)) & eligible, ["trade_date", "ticker", *columns]]
            if row.empty or (not _candidate_union and len(row) != 1):
                raise ValueError("NATIVE_FROZEN_FEATURES_INCOMPLETE")
            missing_dates = sorted(set(signal_dates) - set(row.trade_date.dt.strftime("%Y-%m-%d")))
            if missing_dates:
                gaps.append({"ticker": ticker, "reason": "NATIVE_FEATURE_COVERAGE_INCOMPLETE", "missing_feature_dates": missing_dates,
                             "alternate_rejections": rejections, "category": "NATIVE_CURRENT_PRICE_INPUT"})
            provider = (bridge or {}).get("provider")
            source_label = ("MOOMOO_RAW_PLUS_QUALIFIED_MASSIVE_TAIL_PLUS_MOOMOO_REHAB" if provider == "MASSIVE_GROUPED" else
                            "MOOMOO_RAW_PLUS_QUALIFIED_YAHOO_TAIL_PLUS_MOOMOO_REHAB" if provider == "YAHOO_CHART" else "MOOMOO_OPEND_RAW_PLUS_REHAB")
            lineage.append({"ticker": ticker, "code": code, "security_id": security_ids[0] if len(security_ids) == 1 else None,
                "security_ids": security_ids, "source": source_label,
                "price_basis": "PIT_FORWARD_REHAB_INDEX", "anchor_date": anchor_date, "raw_end": raw.trade_date.max().strftime("%Y-%m-%d"),
                "anchor_proof": {"kind": "NEW_13F_MEMBER_NATIVE_RAW_ANCHOR", "scope": "2026_INFERENCE_ONLY",
                    "old_frozen_equivalence_claimed": False, "native_source": native_proof},
                "universe_id": universe.get("universe_id"), "universe_effective_date": universe.get("effective_date"),
                "membership_validation": "REQUIRES_DOWNSTREAM_DAILY_PIT_JOIN" if _candidate_union else "CALLER_VERIFIED_CURRENT_PIT_UNIVERSE",
                "feature_source": {**source_reference, "path": str(source_reference["path"])}, "raw_sources": [{**native_proof, "role": "NATIVE_MOOMOO_ANCHOR"}],
                "rehab": {"path": rehab["path"], "sha256": rehab["sha256"], "fetched_at": rehab["fetched_at"], "kind": "CURRENT_SNAPSHOT"},
                "alternate_bridge": bridge, "alternate_rejections": rejections, "required_sessions": required.strftime("%Y-%m-%d").tolist(),
                "corporate_action_events": len(events), "feature_rows": len(row), "observed_target": observed_target,
                "vintage_semantics": "LATER_VENDOR_RETRIEVAL_NOT_HISTORICAL_PUBLICATION_VINTAGE"})
            features.append(row)
        except (ValueError, KeyError, OSError, RuntimeError, TypeError) as exc:
            gaps.append({"ticker": ticker, "reason": str(exc), "category": "NATIVE_CURRENT_PRICE_INPUT"})
    frame = pd.concat(features, ignore_index=True) if features else pd.DataFrame(columns=["trade_date", "ticker", *columns])
    native_cache.finish()
    return frame, lineage, gaps


def build_native_2026_feature_candidates(members, signal_dates, sessions, acquisitions, store, rehab_receipt,
                                        source, source_reference, legacy_gaps, *, observed_target):
    """Build a 2026 candidate union once; the caller MUST join daily PIT members.

    Returns (DataFrame[trade_date,ticker,*32 frozen features], lineage, gaps).
    This function does not claim every member was active on every returned date.
    All dates use one explicit later event snapshot, replayed by actual ex-date.
    Pre-2026 signal dates are rejected; no historical ranking/model is selected.
    """
    signal_dates = list(signal_dates)
    if not signal_dates:
        raise ValueError("NATIVE_SIGNAL_DATES_REQUIRED")
    return build_current_native_features({"members": list(members)}, signal_dates[-1], sessions,
        acquisitions, store, rehab_receipt, source, source_reference, legacy_gaps,
        observed_target=observed_target, _signal_dates=signal_dates, _candidate_union=True)
