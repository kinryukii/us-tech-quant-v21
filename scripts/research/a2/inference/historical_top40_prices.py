"""Offline historical features using the original forward rehab price index.

Expanded anchors require equality to hash-bound frozen price observations.
Vendor rehab is a later retrieval, not a historical publication vintage.
No scores, targets, training, provider requests, or catalog writes occur here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts import daily_recommendation_prices as prices

LEDGER_SHA = "0cb9a5acaa0c9f9e2170bf3964292388395c5bfce446fb25a4ad3dcdcc1d1b3b"
FEATURE_SOURCE_SHA = "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"
VINTAGE = "LATER_VENDOR_REHAB_SNAPSHOT_REPLAYED_BY_EX_DATE_NOT_HISTORICAL_PUBLICATION_VINTAGE"


class ValidatedBatchStore:
    """Read-only catalog snapshot and bounded shared-manifest validation cache.

    Create a new instance after a catalog publication. Each shared manifest's
    complete canonical schema/leaf-path validation runs once per byte identity;
    every resolution still checks its current bytes and per-row indexes. Raw
    verification remains canonical and is never cached by this wrapper.
    """

    def __init__(self, store):
        self._store = store
        self._catalog_snapshots = {}
        self._validated_manifests = {}

    def __getattr__(self, name):
        return getattr(self._store, name)

    def metadata(self, dataset, ticker="", adjustment=""):
        from scripts.storage.storage_r2a import validate_daily_price_metadata
        ticker = self._store._ticker(ticker) if ticker else ""
        if not self.catalog_path.exists():
            return self._store.metadata(dataset, ticker, adjustment)
        key = (dataset, adjustment)
        if key not in self._catalog_snapshots:
            rows = self._store._catalog_rows(dataset, adjustment=adjustment)
            self._catalog_snapshots[key] = {row["ticker"]: row for row in rows}
        selected = self._catalog_snapshots[key].get(ticker)
        if selected is None:
            raise KeyError(f"no current catalog entry for {dataset}/{ticker}/{adjustment}")
        row = deepcopy(selected)
        if row.get("format") not in {"parquet", "parquet_manifest"}:
            raise ValueError("DataStore only reads Parquet or an explicit Parquet manifest")
        if not Path(row["path"]).is_absolute():
            raise ValueError("catalog paths must be absolute")
        row["path"] = str(self._store._check_data_path(Path(row["path"])))
        row["lineage"] = json.loads(row.get("lineage_json") or "{}")
        validate_daily_price_metadata(row, row["lineage"])
        if "inputs_manifest" in row["lineage"]:
            self.resolve_price_inputs(row, verify_raw=False)
        row["selection_source"] = "catalog_current"
        return row

    def resolve_price_inputs(self, row, *, verify_raw=True):
        from scripts.storage.storage_r2a import validate_daily_price_metadata
        lineage = row.get("lineage")
        if lineage is None:
            lineage = json.loads(row.get("lineage_json") or "{}")
        validate_daily_price_metadata(row, lineage)
        reference = lineage.get("inputs_manifest")
        if reference is None or verify_raw:
            return self._store.resolve_price_inputs(row, verify_raw=verify_raw)
        value, expected = reference["path"], reference["sha256"]
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("raw-input paths must be absolute")
        if (not isinstance(expected, str) or len(expected) != 64
                or any(char not in "0123456789abcdef" for char in expected)):
            raise ValueError("invalid raw-input SHA-256")
        path = self._store._check_data_path(Path(value))
        if not path.is_file():
            raise ValueError("raw-input path must name a regular file")
        before = path.read_bytes()
        if hashlib.sha256(before).hexdigest() != expected:
            raise ValueError("shared raw-input manifest SHA-256 mismatch")
        key = (str(path), expected)
        if key not in self._validated_manifests:
            # Validate every leaf, even if this ticker uses only a subset.
            complete = deepcopy(row)
            complete["lineage"] = deepcopy(lineage)
            complete["lineage"]["inputs_manifest"].pop("indexes", None)
            inputs = self._store.resolve_price_inputs(complete, verify_raw=False)
            self._validated_manifests[key] = deepcopy(inputs)
        inputs = self._validated_manifests[key]
        indexes = reference.get("indexes", range(len(inputs)))
        if any(index >= len(inputs) for index in indexes):
            raise ValueError("shared raw-input manifest index out of bounds")
        selected = [deepcopy(inputs[index]) for index in indexes]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("shared raw-input manifest changed during resolution")
        return selected

    def read(self, *args, **kwargs):
        from scripts.storage.storage_r2a import DataStore
        return DataStore.read(self, *args, **kwargs)

    def daily(self, *args, **kwargs):
        from scripts.storage.storage_r2a import DataStore
        return DataStore.daily(self, *args, **kwargs)


def _references(paths):
    return {
        "coverage": {"path": paths.backtest_root / "research/a2/demo_2026_calendar_replay/input_coverage.json", "sha256": prices.COVERAGE_SHA},
        "ledger": {"path": paths.results_root / "A_VS_A2_QUARTERLY_13F_R1/A/score_rank_ledger.parquet", "sha256": LEDGER_SHA},
        "source": {"path": paths.repo_root / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py", "sha256": FEATURE_SOURCE_SHA},
    }


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


def _member_identities(members):
    """Project the price contract; PIT authority stays in the caller's manifest.

    Pandas combines different universe sources with NaN/NA/NaT in optional
    metadata. Only the four identity fields affect price loading or its cache;
    missing identity cells become JSON null, never a stringified NaN identity.
    """
    records = members.to_dict("records") if isinstance(members, pd.DataFrame) else list(members)

    def identity(row, field):
        value = row.get(field)
        if value is None or pd.isna(value):
            return None
        if not isinstance(value, str):
            raise ValueError("HISTORICAL_MEMBER_IDENTITY_MUST_BE_TEXT:" + field)
        return value or None

    result = []
    for row in records:
        ticker = identity(row, "ticker")
        if ticker is None:
            raise ValueError("HISTORICAL_MEMBER_TICKER_REQUIRED")
        result.append({"ticker": ticker,
            "moomoo_symbol": identity(row, "moomoo_symbol") or identity(row, "moomoo_transport_code"),
            "security_id": identity(row, "security_id"), "cusip": identity(row, "cusip")})
    return result


def _source(reference):
    path = prices.verify(reference["path"], reference["sha256"])
    spec = importlib.util.spec_from_file_location("historical_a2_frozen_features", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if len(module.FEATURE_COLUMNS) != 32:
        raise ValueError("FROZEN_FEATURE_SCHEMA_NOT_32")
    return module


def _store(paths):
    from scripts.storage.storage_r2a import DataStore
    return ValidatedBatchStore(DataStore(paths))


def _metadata(store, dataset, ticker):
    try:
        return store.metadata(dataset, ticker, "raw")
    except (KeyError, FileNotFoundError):
        return None


def _merge_raw(parts):
    frame = pd.concat(parts, ignore_index=True)
    for _, group in frame.loc[frame.trade_date.duplicated(keep=False)].groupby("trade_date"):
        if any(group[field].nunique() != 1 for field in prices.PRICE_FIELDS):
            raise ValueError("CONFLICTING_OVERLAP_RAW_PRICE")
    return frame.sort_values("trade_date").drop_duplicates("trade_date").reset_index(drop=True)


def _append_raw(original, tail, sessions):
    merged = _merge_raw([original, tail.loc[tail.trade_date >= original.trade_date.min()]])
    required = {day for day in sessions if original.trade_date.max() < day <= merged.trade_date.max()}
    if not required <= set(merged.trade_date):
        raise ValueError("NEW_RAW_TAIL_SESSION_GAP")
    return merged


def _rehab_frame(path, expected, code, row_count, verify):
    frame = pd.read_parquet(verify(path, expected))
    if len(frame) != row_count or not frame.code.eq(code).all():
        raise ValueError("REHAB_RESPONSE_IDENTITY_MISMATCH")
    if not frame.empty:
        values = frame[["forward_adj_factorA", "forward_adj_factorB"]].to_numpy(float)
        if not np.isfinite(values).all() or (values[:, 0] <= 0).any():
            raise ValueError("REHAB_FACTORS_INVALID")
    return frame


def _prove_expanded_anchor(code, ticker, raw, factors, status, ledger, adapter, wolf):
    rows = status.loc[status.code.eq(code)]
    if len(rows) != 1 or rows.iloc[0].status != "PASS":
        raise ValueError("EXPANDED_ANCHOR_ORIGINAL_REHAB_NOT_PASS")
    if int(rows.iloc[0].row_count) != int(factors.code.eq(code).sum()):
        raise ValueError("EXPANDED_ANCHOR_REHAB_ROW_COUNT_MISMATCH")
    frozen = ledger.loc[ledger.ticker.eq(ticker)]
    if frozen.empty:
        raise ValueError("EXPANDED_ANCHOR_NO_FROZEN_PRICE_ROWS")
    if frozen.signal_date.ge(pd.Timestamp("2026-01-01")).any():
        raise ValueError("FROZEN_PRICE_EVIDENCE_OUTSIDE_PRE2026")
    historical = raw.loc[raw.trade_date < pd.Timestamp("2026-01-01")]
    if historical.empty:
        raise ValueError("EXPANDED_ANCHOR_NO_PRE2026_RAW")
    rebuilt, _ = adapter.adjusted_price_frame(code, ticker, historical, factors, wolf)
    joined = frozen.merge(rebuilt[["trade_date", "close", "volume"]], left_on="signal_date",
                          right_on="trade_date", suffixes=("_frozen", "_rebuilt"), validate="one_to_one")
    if len(joined) != len(frozen) or not np.array_equal(
            joined[["close_frozen", "volume_frozen"]].to_numpy(float),
            joined[["close_rebuilt", "volume_rebuilt"]].to_numpy(float)):
        raise ValueError("EXPANDED_ANCHOR_FROZEN_PRICE_MISMATCH")
    return {"kind": "FROZEN_PRE2026_PRICE_EQUIVALENCE", "compared_rows": len(joined),
            "columns": ["signal_date", "ticker", "close", "volume"], "absolute_error": 0.0}


def build_price_features(paths, members, start, end, sessions, acquisitions, rehab_receipt, output_dir):
    """Return (32-feature frame, lineage, gaps); cache immutable run artifacts.

    ``members`` is the historical PIT union, with ticker, explicit Moomoo code
    and cusip/security_id. The caller joins these features to each day's PIT
    membership. Historical delistings retain their valid earlier observations.
    """
    output = Path(output_dir).resolve() / "prices"
    allowed = [Path(getattr(paths, key)).resolve() for key in ("backtest_root", "daily_root", "cache_root", "results_root")]
    frozen_root = Path(paths.results_root).resolve() / "A_VS_A2_QUARTERLY_13F_R1"
    if not any(root in output.parents for root in allowed) or frozen_root in output.parents:
        raise ValueError("PRICE_OUTPUT_MUST_USE_EXTERNAL_NONFROZEN_RUN_DIRECTORY")
    dates = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize()
    if dates.has_duplicates or not dates.is_monotonic_increasing or pd.Timestamp(start) not in dates or pd.Timestamp(end) not in dates:
        raise ValueError("HISTORICAL_SESSION_CONTRACT_INVALID")
    if dates.get_loc(pd.Timestamp(start)) < 120 or start > end:
        raise ValueError("HISTORICAL_START_NEEDS_120_PRIOR_SESSIONS")
    members = _member_identities(members)
    refs = _references(paths)
    checked = {}
    implementation_refs = [{"path": str(Path(path).resolve()), "sha256": prices.digest(path)}
                           for path in (__file__, prices.__file__)]

    def verify(path, expected):
        key = str(Path(path).resolve())
        if checked.get(key) != expected:
            prices.verify(path, expected)
            checked[key] = expected
        return Path(path)

    coverage = json.loads(verify(refs["coverage"]["path"], refs["coverage"]["sha256"]).read_text(encoding="utf-8"))
    verify(refs["ledger"]["path"], refs["ledger"]["sha256"])
    source = _source(refs["source"])
    checked[str(Path(refs["source"]["path"]).resolve())] = refs["source"]["sha256"]
    adapter, proof_adapter = prices._adapter(end), prices._adapter("2025-12-31")
    checked[str(prices.ADAPTER_PATH.resolve())] = prices.ADAPTER_SHA
    original_rehab = coverage["rehab"]
    factors = pd.read_parquet(verify(original_rehab["factors_path"], original_rehab["factors_sha256"]))
    status = pd.read_csv(verify(original_rehab["status_path"], original_rehab["status_sha256"]))
    original_root = Path(coverage["raw"]["root"]).resolve()
    inventory = {}
    for path in sorted(original_root.rglob("*.parquet")):
        if original_root not in path.resolve().parents:
            raise ValueError("ORIGINAL_RAW_ROOT_ESCAPE")
        inventory[str(path)] = prices.digest(path)
    store = _store(paths)
    tickers = sorted({row["ticker"] for row in members})
    catalogs = {ticker: {dataset: _metadata(store, dataset, ticker)
                        for dataset in ("prices_daily", "prices_daily_massive")} for ticker in tickers}
    request_hash = _fingerprint({"schema": 1, "start": start, "end": end, "sessions": sessions,
        "members": members, "acquisitions": acquisitions, "rehab": rehab_receipt,
        "references": refs, "implementation_refs": implementation_refs,
        "raw_inventory": inventory, "catalogs": catalogs})
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        if saved.get("request_sha256") != request_hash:
            raise ValueError("HISTORICAL_PRICE_RUN_INPUTS_CHANGED_USE_NEW_DIRECTORY")
        for item in saved["verified_sources"]:
            verify(item["path"], item["sha256"])
        artifact = saved["features"]
        frame = pd.read_parquet(verify(artifact["path"], artifact["sha256"]))
        if list(frame.columns) != ["trade_date", "ticker", *source.FEATURE_COLUMNS] or len(frame) != artifact["row_count"]:
            raise ValueError("HISTORICAL_FEATURE_CACHE_SCHEMA_MISMATCH")
        return frame, saved["lineage"], saved["gaps"]
    output.mkdir(parents=True, exist_ok=True)
    wanted_codes = {row.get("moomoo_symbol") or row.get("moomoo_transport_code") for row in members}
    index = {}
    for name in inventory:
        frame = pq.read_table(name, columns=["code"]).to_pandas()
        for code in frame.code.dropna().astype(str).unique():
            if code in wanted_codes:
                index.setdefault(code, []).append(name)
    expanded = {row["ticker"] for row in members if (row.get("moomoo_symbol") or row.get("moomoo_transport_code")) not in coverage["raw"]["code_map"]}
    ledger = pq.read_table(refs["ledger"]["path"], columns=["signal_date", "ticker", "close", "volume"],
                           filters=[("ticker", "in", sorted(expanded))]).to_pandas() if expanded else pd.DataFrame(columns=["signal_date", "ticker", "close", "volume"])
    ledger["signal_date"] = pd.to_datetime(ledger.signal_date)
    fresh = {row["code"]: row for row in rehab_receipt.get("results", []) if row.get("status") == "PASS"}
    if len(fresh) != sum(row.get("status") == "PASS" for row in rehab_receipt.get("results", [])):
        raise ValueError("DUPLICATE_REHAB_RESPONSE_CODE")
    yahoo_receipt = acquisitions.get("alternate", {})
    if yahoo_receipt.get("receipt"):
        yahoo_receipt = json.loads(Path(yahoo_receipt["receipt"]).read_text(encoding="utf-8"))
    yahoo = {row["contract"]["ticker"]: row for row in yahoo_receipt.get("results", []) if row.get("status") == "SUCCESS"}
    massive = {row["ticker"]: row for row in acquisitions.get("massive", {}).get("catalog_records", [])}
    wolf = {"event_date": coverage["adjustment"]["wolf_event_date"], "quantity_multiplier": coverage["adjustment"]["wolf_new_shares_per_old_share"]}
    cutoff = (pd.Timestamp(coverage["adjustment"]["required_end_exclusive"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    frames, lineage, gaps, raw_cache = [], [], [], {}
    position = pd.Series(np.arange(len(dates)), index=dates)
    for ticker in tickers:
        rows = [row for row in members if row["ticker"] == ticker]
        codes = {row.get("moomoo_symbol") or row.get("moomoo_transport_code") for row in rows}
        issues = []
        try:
            if len(codes) != 1 or None in codes or any(not (row.get("cusip") or row.get("security_id")) for row in rows):
                raise ValueError("HISTORICAL_MEMBER_IDENTITY_UNBOUND")
            code = next(iter(codes))
            if {row["ticker"] for row in members if (row.get("moomoo_symbol") or row.get("moomoo_transport_code")) == code} != {ticker}:
                raise ValueError("HISTORICAL_CODE_TO_TICKER_AMBIGUITY")
            anchor = coverage["raw"]["code_map"].get(code)
            names = anchor["paths"] if anchor else index.get(code, [])
            if not names or (anchor and anchor["ticker"] != ticker):
                raise ValueError("ORIGINAL_RAW_ANCHOR_UNBOUND")
            parts, raw_refs = [], []
            for name in names:
                expected = coverage["raw"]["file_sha256"][name] if anchor else inventory[name]
                part = pq.read_table(verify(name, expected), columns=prices.RAW_COLUMNS, filters=[("code", "=", code)]).to_pandas()
                parts.append(prices._raw_frame(part, code))
                raw_refs.append({"path": name, "sha256": expected, "role": "ORIGINAL_ANCHOR"})
            raw = _merge_raw(parts)
            proof = {"kind": "ORIGINAL_613_HASH_BOUND_ANCHOR"} if anchor else _prove_expanded_anchor(
                code, ticker, raw, factors, status, ledger, proof_adapter, wolf)
            if anchor and raw.trade_date.min() != pd.Timestamp(anchor["first_date"]):
                raise ValueError("ORIGINAL_PRICE_INDEX_ANCHOR_CHANGED")
            old_status = status.loc[status.code.eq(code)]
            if len(old_status) != 1 or old_status.iloc[0].status != "PASS":
                raise ValueError("ORIGINAL_REHAB_NOT_PASS")
            use_factors, usable_end, rehab_ref = factors, min(end, cutoff), {
                "path": original_rehab["factors_path"], "sha256": original_rehab["factors_sha256"], "kind": "FROZEN_SNAPSHOT"}
            try:
                row = fresh.get(code)
                close = datetime.combine(pd.Timestamp(end).date(), datetime.min.time(), ZoneInfo("America/New_York")) + timedelta(hours=16)
                if (not row or rehab_receipt.get("target_date") != end or rehab_receipt.get("source") != "MOOMOO_OPEND_GET_REHAB"
                        or pd.Timestamp(row["fetched_at"]) < close):
                    raise ValueError("LATEST_REHAB_RESPONSE_MISSING_OR_PREDATES_END")
                use_factors = _rehab_frame(row["path"], row["sha256"], code, row["row_count"], verify)
                usable_end = end
                rehab_ref = {"path": row["path"], "sha256": row["sha256"], "kind": "CURRENT_SNAPSHOT", "fetched_at": row["fetched_at"]}
            except (ValueError, KeyError, TypeError, OSError) as exc:
                if end > cutoff:
                    issues.append(str(exc))
            candidate_rows = [row for row in acquisitions.get("moomoo", {}).get("results", [])
                              if row.get("status") in prices.SUCCESS and row.get("item", {}).get("ticker") == ticker
                              and row["item"].get("adjustment") == "raw"]
            metadata = catalogs[ticker]["prices_daily"]
            candidates = [{"path": row["path"], "sha256": row["sha256"], "format": "csv", "code": row["item"].get("moomoo_symbol")} for row in candidate_rows]
            if metadata:
                candidates.append({"path": metadata["path"], "sha256": metadata.get("source_sha256"), "format": metadata["format"], "code": code})
            for candidate in candidates:
                try:
                    if candidate["code"] != code:
                        raise ValueError("CURRENT_RAW_RECEIPT_CODE_MISMATCH")
                    path = verify(candidate["path"], candidate["sha256"])
                    part = pd.read_csv(path) if candidate["format"] == "csv" else pd.read_parquet(path)
                    part = prices._raw_frame(part, code)
                    part = part.loc[part.trade_date <= pd.Timestamp(usable_end)]
                    raw = _append_raw(raw, part, dates)
                    raw_refs.append({"path": str(path), "sha256": candidate["sha256"], "role": "CURRENT_RAW"})
                except (ValueError, KeyError, OSError) as exc:
                    issues.append(str(exc))
            raw = raw.loc[raw.trade_date <= pd.Timestamp(usable_end)].copy()
            bridge = None
            required_start = dates[dates.get_loc(pd.Timestamp(start)) - 120]
            present_dates = set(raw.trade_date)
            gap_dates = ([day.strftime("%Y-%m-%d") for day in dates
                          if max(required_start, raw.trade_date.min()) <= day <= raw.trade_date.max()
                          and day not in present_dates] if not raw.empty else [])
            if not raw.empty and (raw.trade_date.max() < pd.Timestamp(usable_end) or gap_dates):
                candidate = massive.get(ticker) or catalogs[ticker]["prices_daily_massive"]
                if candidate:
                    try:
                        options = {"gap_dates": gap_dates} if gap_dates else {}
                        tail, bridge = prices._qualified_massive_tail(candidate, raw, ticker, usable_end, store, raw_cache, **options)
                        raw = _append_raw(raw, tail, dates)
                    except (ValueError, KeyError, OSError, RuntimeError) as exc:
                        issues.append(str(exc)); bridge = None
                if raw.trade_date.max() < pd.Timestamp(usable_end) and ticker in yahoo:
                    try:
                        tail, bridge = prices._qualified_yahoo_tail(yahoo[ticker], raw, ticker, usable_end)
                        raw = _append_raw(raw, tail, dates)
                    except (ValueError, KeyError, OSError, RuntimeError) as exc:
                        issues.append(str(exc)); bridge = None
            if raw.empty:
                raise ValueError("NO_PRICE_HISTORY_IN_REQUESTED_RANGE")
            adjusted, _ = adapter.adjusted_price_frame(code, ticker, raw, use_factors, wolf)
            feature = source.build_stock_state_features(adjusted[["ticker", "trade_date", "close", "volume"]])
            positions = feature.trade_date.map(position)
            contiguous = positions.diff().eq(1).rolling(120, min_periods=120).sum().eq(120)
            eligible = positions.sub(positions.shift(120)).eq(120) & contiguous & np.isfinite(feature[list(source.FEATURE_COLUMNS)].to_numpy(float)).all(axis=1)
            select = eligible & feature.trade_date.between(pd.Timestamp(start), pd.Timestamp(end))
            selected = feature.loc[select, ["trade_date", "ticker", *source.FEATURE_COLUMNS]].copy()
            frames.append(selected)
            selected_dates = set(selected.trade_date)
            missing_dates = [day.strftime("%Y-%m-%d") for day in dates[(dates >= start) & (dates <= end)] if day not in selected_dates]
            if missing_dates:
                issues.append("PRICE_OR_CONTIGUOUS_121_FEATURE_COVERAGE_INCOMPLETE")
            if issues or missing_dates:
                gaps.append({"ticker": ticker, "code": code, "reasons": sorted(set(issues)), "missing_feature_dates": missing_dates})
            lineage.append({"ticker": ticker, "code": code, "cusips": sorted({str(row.get("cusip") or row.get("security_id")) for row in rows}),
                "anchor_date": raw.trade_date.min().strftime("%Y-%m-%d"), "anchor_proof": proof,
                "raw_sources": raw_refs, "rehab": rehab_ref, "alternate_bridge": bridge,
                "price_basis": "PIT_FORWARD_REHAB_INDEX", "vintage_semantics": VINTAGE,
                "raw_end": raw.trade_date.max().strftime("%Y-%m-%d"), "feature_rows": len(selected)})
            if bridge:
                for key in ("normalized_path", "raw_path"):
                    if bridge.get(key):
                        checked[str(Path(bridge[key]).resolve())] = prices.digest(bridge[key])
                for ref in bridge.get("raw_inputs", []):
                    checked[str(Path(ref["path"]).resolve())] = ref["sha256"]
                    if ref.get("checkpoint_path"):
                        checked[str(Path(ref["checkpoint_path"]).resolve())] = ref["checkpoint_sha256"]
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            gaps.append({"ticker": ticker, "reasons": [str(exc)], "missing_all_requested_dates": True})
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["trade_date", "ticker", *source.FEATURE_COLUMNS])
    frame = frame.sort_values(["trade_date", "ticker"]).reset_index(drop=True)
    feature_path = output / "features.parquet"
    temporary = output / "features.tmp.parquet"
    frame.to_parquet(temporary, index=False)
    temporary.replace(feature_path)
    manifest = {"schema": "A2_HISTORICAL_EXPANDED_PRICE_INPUTS_V1", "request_sha256": request_hash,
        "start": start, "end": end, "vintage_semantics": VINTAGE, "references": refs,
        "implementation_refs": implementation_refs,
        "verified_sources": [{"path": path, "sha256": sha} for path, sha in sorted(checked.items())],
        "features": {"path": str(feature_path), "sha256": prices.digest(feature_path), "row_count": len(frame)},
        "feature_columns": list(source.FEATURE_COLUMNS), "lineage": lineage, "gaps": gaps}
    prices._write(manifest_path, json.loads(json.dumps(manifest, default=str)))
    return frame, lineage, gaps
