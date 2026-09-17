"""Bounded quote-only 24h minute acquisition; preserve old canonical partitions.

Reuse V22.049 pagination/normalization and V21's global history limiter. Only
securities already present in the live history quota may be requested.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import importlib
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from refresh_market_data import load_module, digest, write_json

MINUTE_SOURCE = "scripts/v22/v22_049_fast3_six_etf_24h_minute_data_ingest_r1.py"
LIMITER_SOURCE = "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py"


def plan_intervals(tickers, start, end, days=7):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or days < 1 or days > 31:
        raise ValueError("Invalid interval range/segment days")
    result = []
    for ticker in dict.fromkeys(tickers):
        if not ticker.isalnum() or ticker.upper() != ticker:
            raise ValueError("Expected uppercase plain ETF ticker")
        cursor = first
        while cursor <= last:
            stop = min(last, cursor + timedelta(days=days - 1))
            result.append({"ticker": ticker, "code": "US." + ticker,
                           "start": str(cursor), "end": str(stop)})
            cursor = stop + timedelta(days=1)
    return result


class LimitedQuoteHistory:
    def __init__(self, context, limiter, known, pagination_rate_policy="all-requests"):
        if pagination_rate_policy not in {"all-requests", "first-page"}:
            raise ValueError("Unknown pagination rate policy")
        self.context, self.limiter, self.known = context, limiter, known
        self.pagination_rate_policy = pagination_rate_policy
        self.audit_rows = []

    def request_history_kline(self, **kwargs):
        code = kwargs["code"]
        if code not in self.known:
            raise ValueError("NEW_SECURITY_TOUCH_FORBIDDEN: " + code)
        first_page = kwargs.get("page_req_key") is None
        rate_limited = self.pagination_rate_policy == "all-requests" or first_page
        if rate_limited:
            self.limiter.acquire({"ticker": code[3:], "adjustment": "raw", "frequency": "1m"})
        # Provider exempts continuation pages; V22.049 retains its 0.05s page
        # delay and restarts retries with no key, so retry first pages are limited.
        row = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
               "ticker": code[3:], "adjustment": "raw", "frequency": "1m",
               "api_call": "request_history_kline", "start": kwargs.get("start"),
               "end": kwargs.get("end"), "first_page": first_page,
               "rate_limited": rate_limited, "pagination_rate_policy": self.pagination_rate_policy,
               "outcome": "CALL_STARTED"}
        self.audit_rows.append(row)
        try:
            result = self.context.request_history_kline(**kwargs)
        except Exception as exc:
            row.update(outcome="RAISED", error_type=type(exc).__name__)
            raise
        row["outcome"] = "RETURNED"
        if isinstance(result, tuple) and result:
            row["return_code"] = str(result[0])
        return result


def validate_raw_identity(raw, item):
    # normalize() sets code/symbol from the request; authenticate raw identity
    # first so a different provider code cannot be silently relabelled.
    if raw.empty:
        raise ValueError("EMPTY_INTERVAL")
    if "code" not in raw.columns or raw["code"].isna().any() or not raw["code"].eq(item["code"]).all():
        raise ValueError("Unexpected raw provider identity")


def validate(frame, item):
    if frame.empty:
        raise ValueError("EMPTY_INTERVAL")
    if not frame.code.eq(item["code"]).all() or not frame.symbol.eq(item["ticker"]).all():
        raise ValueError("Unexpected provider identity")
    if frame.duplicated(["code", "timestamp_utc"]).any():
        raise ValueError("Duplicate code/timestamp")
    dates = frame.timestamp_et.dt.strftime("%Y-%m-%d")
    if not dates.between(item["start"], item["end"]).all():
        raise ValueError("Provider returned dates outside requested ET interval")
    values = frame[["open", "high", "low", "close", "volume"]]
    valid = np.isfinite(values).all(axis=1)
    valid &= frame[["open", "high", "low", "close"]].gt(0).all(axis=1)
    valid &= frame.volume.ge(0)
    valid &= frame.high.ge(frame[["open", "low", "close"]].max(axis=1))
    valid &= frame.low.le(frame[["open", "high", "close"]].min(axis=1))
    if not valid.all():
        raise ValueError(f"Invalid OHLCV rows: {int((~valid).sum())}")
    if not frame.source.eq("moomoo_opend").all() or not frame.adjustment_type.eq("NONE").all():
        raise ValueError("Unexpected source/adjustment")


def interval_paths(root, item):
    base = root / "intervals" / item["ticker"] / (item["start"] + "_" + item["end"])
    return base, base / "manifest.json"


def read_checkpoint(root, item):
    _, path = interval_paths(root, item)
    if not path.exists():
        return None
    result = json.loads(path.read_text(encoding="utf-8"))
    if result["item"] != item or result["status"] != "ACQUIRED":
        raise ValueError("Unexpected checkpoint contract")
    for field in ("raw", "output"):
        ref = result[field]
        if digest(Path(ref["path"])) != ref["sha256"]:
            raise ValueError("Changed checkpoint: " + ref["path"])
    return {**result, "status": "REUSED"}


def acquire_interval(root, item, minute, sdk, quote):
    base, manifest = interval_paths(root, item)
    base.mkdir(parents=True, exist_ok=True)
    if any(base.iterdir()):
        raise ValueError("Uncommitted interval files preserved; inspect before retry: " + str(base))
    raw = minute.call_history(quote, sdk, item["code"], item["start"], item["end"])
    observed = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    raw_path = base / "raw.parquet"
    raw.to_parquet(raw_path, index=False)
    validate_raw_identity(raw, item)
    frame = minute.normalize(raw, item["code"], observed)
    validate(frame, item)
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    output_path = base / "minute.parquet"
    minute.atomic_parquet(frame, output_path)
    result = {"status": "ACQUIRED", "item": item, "observed_at": observed,
              "raw": {"path": str(raw_path), "sha256": digest(raw_path), "row_count": len(raw)},
              "output": {"path": str(output_path), "sha256": digest(output_path),
                         "row_count": len(frame), "columns": list(frame.columns),
                         "min_timestamp_utc": frame.timestamp_utc.min().isoformat(),
                         "max_timestamp_utc": frame.timestamp_utc.max().isoformat()},
              "sessions": frame.session.value_counts().to_dict(),
              "contract": {"frequency": "K_1M", "adjustment": "NONE", "session": "ALL",
                           "extended_time": False, "native_timestamp_timezone": "America/New_York"}}
    write_json(manifest, result)
    return result


def build_tails(root, canonical_root, plan, allow_volume_revisions=False):
    """Join only a verified unchanged overlap, leaving old partitions intact."""
    policy = "volume_revisions" if allow_volume_revisions else "strict"
    tail_root = root / "tails" / (policy + "_" + digest(root / "acquisition_report.json")[:20])
    tail_root.mkdir(parents=True, exist_ok=True)
    results = []
    for ticker in dict.fromkeys(x["ticker"] for x in plan):
        result = {"ticker": ticker, "status": "BLOCKED"}
        try:
            references = [read_checkpoint(root, x) for x in plan if x["ticker"] == ticker]
            if any(x is None for x in references):
                raise ValueError("Incomplete acquisition checkpoints")
            incoming = pd.concat([pq.ParquetFile(x["output"]["path"]).read().to_pandas()
                                  for x in references], ignore_index=True).sort_values("timestamp_utc")
            if incoming.duplicated(["code", "timestamp_utc"]).any():
                raise ValueError("Duplicate timestamp across acquired intervals")
            old_files = sorted((canonical_root / f"symbol={ticker}").glob("year=*/month=*/data.parquet"))
            if not old_files:
                raise ValueError("No existing canonical partition")
            last_path = old_files[-1]
            old_hash = digest(last_path)
            old = pq.ParquetFile(last_path).read().to_pandas()
            old["timestamp_utc"] = pd.to_datetime(old.timestamp_utc, utc=True).astype("datetime64[ns, UTC]")
            if incoming.timestamp_utc.min() < old.timestamp_utc.min():
                raise ValueError("Requested overlap extends before last old partition; explicit multi-partition comparison required")
            old_max = old.timestamp_utc.max()
            overlap = incoming[incoming.timestamp_utc <= old_max].set_index("timestamp_utc")
            baseline = old[old.timestamp_utc >= incoming.timestamp_utc.min()].set_index("timestamp_utc")
            common = baseline.index.intersection(overlap.index)
            if not len(common):
                raise ValueError("No old/new overlap; continuity not established")
            columns = ["open", "high", "low", "close", "volume", "turnover"]
            old_values = baseline.loc[common, columns].to_numpy(float)
            new_values = overlap.loc[common, columns].to_numpy(float)
            equality = (old_values == new_values) | (np.isnan(old_values) & np.isnan(new_values))
            changed = common[(~equality).any(axis=1)]
            comparison = {"old_last_partition": str(last_path), "old_last_partition_sha256": old_hash,
                          "old_max_timestamp_utc": old_max.isoformat(), "compared_rows": len(common),
                          "changed_ohlcv_turnover_rows": len(changed),
                          "changed_timestamp_examples": [x.isoformat() for x in changed[:20]],
                          "new_overlap_keys_not_in_old": len(overlap.index.difference(baseline.index)),
                          "old_overlap_keys_not_returned": len(baseline.index.difference(overlap.index)),
                          "numeric_tolerance": {"relative": 0, "absolute": 0}}
            comparison["changed_rows_by_column"] = {column: int((~equality[:, i]).sum())
                                                    for i, column in enumerate(columns)}
            differences = []
            for row, col in zip(*np.where(~equality)):
                differences.append({"ticker": ticker, "timestamp_utc": common[row],
                                    "column": columns[col], "previous_value": old_values[row, col],
                                    "current_retrieval_value": new_values[row, col]})
            if differences:
                difference_path = tail_root / (ticker + "_overlap_differences.parquet")
                difference_frame = pd.DataFrame(differences)
                if difference_path.exists():
                    pd.testing.assert_frame_equal(difference_frame, pq.ParquetFile(difference_path).read().to_pandas())
                else:
                    difference_frame.to_parquet(difference_path, index=False)
                comparison["row_level_differences"] = {"path": str(difference_path),
                                                       "sha256": digest(difference_path),
                                                       "row_count": len(difference_frame)}
                csv_path = difference_path.with_suffix(".csv")
                csv_bytes = difference_frame.to_csv(index=False).encode("utf-8")
                if csv_path.exists() and csv_path.read_bytes() != csv_bytes:
                    raise ValueError("Immutable difference CSV changed")
                if not csv_path.exists():
                    csv_path.write_bytes(csv_bytes)
                comparison["row_level_differences"]["csv_path"] = str(csv_path)
                comparison["row_level_differences"]["csv_sha256"] = digest(csv_path)
            result["overlap_comparison"] = comparison
            result["interval_sources"] = [{"item": x["item"], "raw": x["raw"], "output": x["output"]}
                                           for x in references]
            if comparison["old_overlap_keys_not_returned"] or comparison["new_overlap_keys_not_in_old"]:
                raise ValueError("OVERLAP_KEY_DIFFERENCE_REQUIRES_REVIEW")
            if not equality[:, :4].all():
                raise ValueError("OHLC_REVISION_BLOCKS_HISTORY_APPEND")
            if len(changed) and not allow_volume_revisions:
                raise ValueError("VOLUME_TURNOVER_REVISIONS_REQUIRE_EXPLICIT_POLICY")
            if digest(last_path) != old_hash:
                raise ValueError("Old source changed during comparison")
            tail = incoming[incoming.timestamp_utc > old_max].copy().reset_index(drop=True)
            if tail.empty:
                raise ValueError("No new tail rows")
            path = tail_root / (ticker + ".parquet")
            if path.exists():
                existing = pq.ParquetFile(path).read().to_pandas()
                pd.testing.assert_frame_equal(tail, existing)
            else:
                tail.to_parquet(path, index=False)
            result.update(status="VERIFIED_TAIL", warnings=["VOLUME_TURNOVER_REVISIONS_OBSERVED"] if len(changed) else [],
                          vintage_semantics="OLD_BYTES_PRESERVED_NEW_TAIL_CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT_CORRECTION",
                          output={"path": str(path), "sha256": digest(path),
                          "row_count": len(tail), "columns": list(tail.columns),
                          "min_timestamp_utc": tail.timestamp_utc.min().isoformat(),
                          "max_timestamp_utc": tail.timestamp_utc.max().isoformat(),
                          "min_calendar_date_et": tail.calendar_date_et.min(),
                          "max_calendar_date_et": tail.calendar_date_et.max(),
                          "sessions": tail.session.value_counts().to_dict()})
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
        print(json.dumps({"ticker": ticker, "status": result["status"], "error": result.get("error")}), flush=True)
    report = {"status": "VERIFIED" if all(x["status"] == "VERIFIED_TAIL" for x in results) else "PARTIAL",
              "results": results, "overlap_policy": "EXACT_KEYS_AND_OHLC_REQUIRED_OLD_BYTES_PRESERVED",
              "allow_volume_turnover_revisions": allow_volume_revisions,
              "acquisition_report": {"path": str(root / "acquisition_report.json"), "sha256": digest(root / "acquisition_report.json")}}
    report_path = tail_root / "tail_report.json"
    if report_path.exists():
        if json.loads(report_path.read_text(encoding="utf-8")) != report:
            raise ValueError("Immutable tail report differs; preserve and use another snapshot")
    else:
        write_json(report_path, report)
    print(json.dumps({"status": report["status"], "tail_report": str(report_path)}), flush=True)
    return report


def reconcile_revision_frames(old, incoming, confirmation):
    """Preserve every original minute; current rows replace only a verified overlap."""
    frames = []
    for frame in (old, incoming, confirmation):
        frame = frame.copy()
        frame["timestamp_utc"] = pd.to_datetime(frame.timestamp_utc, utc=True).astype("datetime64[ns, UTC]")
        if frame.empty or frame.duplicated(["code", "timestamp_utc"]).any():
            raise ValueError("Empty or duplicate minute revision input")
        frames.append(frame.sort_values("timestamp_utc").set_index("timestamp_utc"))
    old, incoming, confirmation = frames
    for field in ("symbol", "code", "source", "adjustment_type"):
        values = set().union(*(set(frame[field]) for frame in frames))
        if len(values) != 1:
            raise ValueError("Revision source/identity/adjustment mismatch: " + field)
    if incoming.index.min() < old.index.min() or incoming.index.max() <= old.index.max():
        raise ValueError("Revision must begin within the last partition and extend it")
    baseline = old.loc[old.index >= incoming.index.min()]
    overlap = incoming.loc[incoming.index <= old.index.max()]
    missing = baseline.index.difference(overlap.index)
    if len(missing):
        raise ValueError(f"OLD_MINUTES_NOT_RETURNED: {len(missing)}; examples={[str(x) for x in missing[:5]]}")
    columns = ["open", "high", "low", "close", "volume", "turnover"]
    common = baseline.index.intersection(overlap.index)
    if not len(common):
        raise ValueError("No old/new overlap")
    a, b = baseline.loc[common, columns], overlap.loc[common, columns]
    equal = a.eq(b) | (a.isna() & b.isna())
    changed_ohlc = common[(~equal.iloc[:, :4]).any(axis=1)]
    if not len(changed_ohlc):
        raise ValueError("Use ordinary tail path when no OHLC revision needs reconciliation")
    if len(changed_ohlc.difference(confirmation.index)):
        raise ValueError("OHLC_REVISION_NOT_IN_CONFIRMATION")
    if len(confirmation.index.difference(incoming.index)):
        raise ValueError("Confirmation contains keys absent from incoming data")
    retrieved = incoming.loc[confirmation.index, columns]
    verified = confirmation[columns]
    if not (retrieved.eq(verified) | (retrieved.isna() & verified.isna())).all().all():
        raise ValueError("CONFIRMATION_VALUES_DISAGREE")
    changes = []
    for row, col in zip(*np.where(~equal.to_numpy())):
        timestamp, column = common[row], columns[col]
        changes.append({"ticker": baseline.loc[timestamp, "symbol"], "timestamp_utc": timestamp,
                        "column": column, "previous_value": a.iloc[row, col], "current_value": b.iloc[row, col],
                        "previous_downloaded_at_utc": baseline.loc[timestamp, "downloaded_at_utc"],
                        "current_downloaded_at_utc": overlap.loc[timestamp, "downloaded_at_utc"],
                        "confirmation_downloaded_at_utc": confirmation.loc[timestamp, "downloaded_at_utc"] if timestamp in confirmation.index else None})
    prefix = old.loc[old.index < incoming.index.min()]
    merged = pd.concat([prefix, incoming]).sort_index()
    if merged.index.duplicated().any() or len(old.index.difference(merged.index)):
        raise ValueError("Original timestamp loss or duplicate after revision reconciliation")
    pd.testing.assert_frame_equal(merged.loc[prefix.index], prefix, check_dtype=False)
    added = overlap.index.difference(baseline.index)
    return merged.reset_index()[frames[0].reset_index().columns], pd.DataFrame(changes), {
        "old_rows": len(old), "incoming_rows": len(incoming), "retained_old_prefix_rows": len(prefix),
        "compared_rows": len(common), "old_keys_missing_from_incoming": len(missing),
        "new_overlap_keys_not_in_old": len(added), "new_overlap_key_examples": [str(x) for x in added[:20]],
        "original_keys_missing_from_output": len(old.index.difference(merged.index)),
        "confirmation_rows": len(confirmation), "changed_ohlc_minutes": len(changed_ohlc),
        "changed_rows_by_column": {column: int((~equal[column]).sum()) for column in columns},
        "new_tail_rows": int((incoming.index > old.index.max()).sum()), "output_rows": len(merged)}


def materialize_current_revision(store, baseline_manifest_path, acquisition_root, confirmation_root,
                                 output_root, ticker, start, end):
    """Offline adapter: current-vintage reconciliation, with no catalog write."""
    from scripts.storage.build_parquet_manifest import load_manifest, prepare
    from scripts.storage.restore_sec_data import write_frame
    baseline_manifest_path = Path(baseline_manifest_path).resolve()
    acquisition_root, confirmation_root = Path(acquisition_root).resolve(), Path(confirmation_root).resolve()
    output_root = store._check_data_path(Path(output_root), must_exist=False)
    baseline = json.loads(baseline_manifest_path.read_text(encoding="utf-8"))
    baseline_row = {key: baseline[key] for key in ("dataset", "ticker", "adjustment", "row_count", "min_date", "max_date")}
    baseline_row.update(path=str(baseline_manifest_path), source_sha256=digest(baseline_manifest_path))
    _, old_paths, _ = load_manifest(store, baseline_row)
    if baseline["ticker"] != ticker or baseline["dataset"] != "prices_intraday_1m" or baseline["adjustment"] != "raw":
        raise ValueError("Unexpected baseline minute dataset")
    plans = plan_intervals([ticker], start, end)
    checkpoints = [read_checkpoint(acquisition_root, item) for item in plans]
    confirmation_report = json.loads((confirmation_root / "acquisition_report.json").read_text(encoding="utf-8"))
    confirm_items = confirmation_report["plan"]
    if confirmation_report["status"] != "ACQUIRED" or not confirm_items or any(item["ticker"] != ticker for item in confirm_items):
        raise ValueError("Unexpected confirmation acquisition scope/status")
    confirmed = [read_checkpoint(confirmation_root, item) for item in confirm_items]
    if any(item is None for item in checkpoints + confirmed):
        raise ValueError("Missing immutable acquisition checkpoint")
    def read_set(refs):
        parts = []
        for item in refs:
            frame = pq.ParquetFile(item["output"]["path"]).read().to_pandas()
            validate(frame, item["item"])
            parts.append(frame)
        return pd.concat(parts, ignore_index=True)
    incoming, confirmation = read_set(checkpoints), read_set(confirmed)
    if pd.to_datetime(confirmation.downloaded_at_utc, utc=True).min() <= pd.to_datetime(incoming.downloaded_at_utc, utc=True).max():
        raise ValueError("Confirmation must be observed after the incoming source retrieval")
    last = old_paths[-1]
    old = pq.ParquetFile(last).read().to_pandas()
    merged, differences, comparison = reconcile_revision_frames(old, incoming, confirmation)
    merged = merged[old.columns]
    sources = [{"path": str(baseline_manifest_path), "sha256": digest(baseline_manifest_path)},
               {"path": str(acquisition_root / "acquisition_report.json"), "sha256": digest(acquisition_root / "acquisition_report.json")},
               {"path": str(confirmation_root / "acquisition_report.json"), "sha256": digest(confirmation_root / "acquisition_report.json")}]
    contract = {"schema_version": 1, "ticker": ticker, "start": start, "as_of": end,
                "policy": "CONFIRMED_CURRENT_RETRIEVAL_REPLACES_OVERLAP", "sources": sources,
                "old_partition": {"path": str(last), "sha256": digest(last)},
                "incoming": [{"item": x["item"], "raw": x["raw"], "output": x["output"]} for x in checkpoints],
                "confirmation": [{"item": x["item"], "raw": x["raw"], "output": x["output"]} for x in confirmed]}
    identity = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    root = output_root / "versions" / identity[:24]
    if any(Path(item["path"]).is_relative_to(root) for item in sources) or last.is_relative_to(root):
        raise ValueError("Revision output must not contain original inputs")
    if digest(baseline_manifest_path) != baseline_row["source_sha256"]:
        raise ValueError("Baseline manifest changed during reconciliation")
    expected_old_hash = next(item["sha256"] for item in baseline["files"] if Path(item["path"]).resolve() == last)
    if digest(last) != expected_old_hash:
        raise ValueError("Old source partition changed during reconciliation")
    for item in checkpoints:
        read_checkpoint(acquisition_root, item["item"])
    for item in confirmed:
        read_checkpoint(confirmation_root, item["item"])
    output = write_frame(root / "reconciled_minutes.parquet", merged)
    difference_output = write_frame(root / "revisions.parquet", differences)
    evidence = {"status": "CONFIRMED_CURRENT_VINTAGE_RECONCILIATION", "contract": contract,
                "comparison": comparison, "output": output, "revisions": difference_output,
                "old_sources_modified": False, "catalog_written": False,
                "availability_policy": "PRESERVE_ROW_DOWNLOAD_TIMES_NOT_HISTORICAL_PIT_CORRECTION",
                "provider_revision_published_at": None,
                "limitations": ["Provider supplies no revision publication timestamp; observed/download times bound retrieval only.",
                                "All old timestamps are retained. Missing returned old keys fail rather than silently disappearing.",
                                "Sparse provider output is preserved; no fabricated minute bars or full-session completeness claim."]}
    evidence_path = root / "reconciliation_manifest.json"
    if evidence_path.exists() and json.loads(evidence_path.read_text(encoding="utf-8")) != evidence:
        raise ValueError("Immutable reconciliation evidence differs")
    if not evidence_path.exists():
        write_json(evidence_path, evidence)
    snapshot = prepare(store, old_paths[:-1] + [Path(output["path"])], root / "manifests",
                       dataset="prices_intraday_1m", ticker=ticker, adjustment="raw", date_column="timestamp_utc",
                       ticker_column="symbol", source=baseline["source"], expected_values=baseline["expected_values"],
                       supporting_manifests=[baseline_manifest_path, acquisition_root / "acquisition_report.json",
                                             confirmation_root / "acquisition_report.json", evidence_path])
    snapshot["catalog_record"]["lineage"].update(authority="CURRENT_VINTAGE_RECONCILIATION_OLD_SOURCE_BYTES_RETAINED",
        update_status="CONFIRMED_CURRENT_VINTAGE_RECONCILIATION", reconciliation_manifest=str(evidence_path),
        reconciliation_manifest_sha256=digest(evidence_path), availability_policy=evidence["availability_policy"])
    result = {"status": evidence["status"], "snapshot": snapshot, "reconciliation_manifest": str(evidence_path),
              "reconciliation_manifest_sha256": digest(evidence_path), "comparison": comparison,
              "incremental_candidate_policy": "All incoming rows are included exactly; catalog alias may retire after reference audit, raw checkpoint files remain sources.",
              "catalog_written": False, "source_files_modified": False}
    write_json(root / "publication_candidate.json", result)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path("D:/us-tech-quant"))
    p.add_argument("--work-root", type=Path, required=True)
    p.add_argument("--tickers", nargs="+", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--segment-days", type=int, default=7)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18441)
    p.add_argument("--pagination-rate-policy", choices=("all-requests", "first-page"), default="all-requests",
                   help="Apply the existing limiter to every request (default) or only each segment/retry first page; continuation pages retain the existing 0.05s delay.")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--build-tails-only", action="store_true")
    p.add_argument("--canonical-root", type=Path)
    p.add_argument("--allow-volume-revisions", action="store_true")
    args = p.parse_args(argv)
    plan = plan_intervals(args.tickers, args.start, args.end, args.segment_days)
    if not args.execute:
        print(json.dumps({"status": "DRY_RUN", "plan": plan, "new_security_touches_allowed": 0,
                          "pagination_rate_policy": args.pagination_rate_policy}))
        return 0
    root = args.work_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.build_tails_only:
        if args.canonical_root is None:
            raise ValueError("--build-tails-only requires --canonical-root")
        return 0 if build_tails(root, args.canonical_root, plan, args.allow_volume_revisions)["status"] == "VERIFIED" else 2
    report = root / "acquisition_report.json"
    result = {"status": "RUNNING", "plan": plan, "results": [], "new_security_touches_allowed": 0,
              "pagination_rate_policy": args.pagination_rate_policy}
    context = None
    limiter = None
    quote = None
    try:
        pending = []
        for item in plan:
            cached = read_checkpoint(root, item)
            if cached:
                result["results"].append(cached)
            else:
                pending.append(item)
        if pending:
            appdata = root / "sdk_appdata"
            appdata.mkdir(exist_ok=True)
            os.environ["APPDATA"] = str(appdata)
            sdk = importlib.import_module("moomoo")
            sdk.SysConfig.set_all_thread_daemon(True)
            context = sdk.OpenQuoteContext(host=args.host, port=args.port, is_async_connect=True)
            context.set_sync_query_connect_timeout(10)
            ret, quota = context.get_history_kl_quota(get_detail=True)
            if ret != sdk.RET_OK:
                raise ValueError("QUOTA_QUERY_FAILED: " + str(quota))
            used, remaining, details = quota
            known = {str(row.get("code", "")) for row in details}
            result["quota_before"] = {"used": int(used), "remaining": int(remaining), "requested_already_touched": sorted(known & {x['code'] for x in plan})}
            if {x["code"] for x in pending} - known:
                raise ValueError("Some requested symbols are not in existing live quota")
            minute = load_module(args.repo / MINUTE_SOURCE, "existing_minute_ingest")
            daily = load_module(args.repo / LIMITER_SOURCE, "existing_history_limiter")
            limiter = daily.HistoryKlineLimiter()
            quote = LimitedQuoteHistory(context, limiter, known, args.pagination_rate_policy)
            result["sdk_version"] = version("moomoo-api")
            result["source_code_sha256"] = {MINUTE_SOURCE: digest(args.repo / MINUTE_SOURCE), LIMITER_SOURCE: digest(args.repo / LIMITER_SOURCE)}
            for item in pending:
                try:
                    acquired = acquire_interval(root, item, minute, sdk, quote)
                except Exception as exc:
                    acquired = {"status": "FAILED", "item": item, "error": f"{type(exc).__name__}: {exc}"}
                result["results"].append(acquired)
                result["history_request_count"] = len(quote.audit_rows)
                result["rate_limited_request_count"] = len(limiter.audit_rows)
                write_json(report, result)
                print(json.dumps({"item": item, "status": acquired["status"], "rows": acquired.get("output", {}).get("row_count"), "error": acquired.get("error")}), flush=True)
            ret, after = context.get_history_kl_quota(get_detail=False)
            if ret == sdk.RET_OK:
                result["quota_after"] = {"used": int(after[0]), "remaining": int(after[1])}
        result["status"] = "ACQUIRED" if all(x["status"] in {"ACQUIRED", "REUSED"} for x in result["results"]) else "PARTIAL"
    except Exception as exc:
        result.update(status="BLOCKED", error=f"{type(exc).__name__}: {exc}")
    finally:
        if context is not None:
            context.close()
        if quote is not None:
            result["history_request_count"] = len(quote.audit_rows)
            result["request_audit"] = quote.audit_rows
        if limiter is not None:
            result["rate_limited_request_count"] = len(limiter.audit_rows)
            result["rate_limit_audit"] = limiter.audit_rows
        write_json(report, result)
    print(json.dumps({"status": result["status"], "report": str(report)}))
    return 0 if result["status"] == "ACQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
