"""Fetch bounded official SEC disclosures using the existing durable SecCache.

No research entrypoint is called. Existing identity CIKs drive source retrieval;
only issuers with recent financial disclosures receive a companyfacts request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

if __package__:
    from .refresh_13f_quarter import configured_user_agent
    from .restore_sec_data import disclosure_rows, fact_rows, file_identity, load_parser, read_ciks, sha256_file
else:
    from refresh_13f_quarter import configured_user_agent
    from restore_sec_data import disclosure_rows, fact_rows, file_identity, load_parser, read_ciks, sha256_file


FINANCIAL_FORMS = {form + suffix for form in ("10-K", "10-Q", "8-K", "20-F", "6-K", "40-F") for suffix in ("", "/A")}


def index_candidates(payload: bytes, ciks: list[int], start: str, end: str) -> tuple[list[int], pd.DataFrame, dict]:
    """Parse the official pipe-delimited master index, without guessing columns."""
    lines = payload.decode("latin-1").splitlines()
    header = "CIK|Company Name|Form Type|Date Filed|Filename"
    positions = [i for i, line in enumerate(lines) if line.strip() == header]
    if len(positions) != 1:
        raise ValueError("SEC master index header not found exactly once")
    allowed, rows, dates = set(ciks), [], []
    for line in lines[positions[0] + 1:]:
        if not line.strip() or set(line.strip()) == {"-"}:
            continue
        parts = line.split("|")
        if len(parts) != 5 or not parts[0].isdigit():
            raise ValueError("Malformed SEC master index row")
        cik, company, form, filed, filename = parts
        if pd.Timestamp(filed).strftime("%Y-%m-%d") != filed or not filename.startswith("edgar/data/"):
            raise ValueError("Invalid date or SEC filename in master index")
        dates.append(filed)
        if int(cik) in allowed and start <= filed <= end:
            rows.append({"cik": int(cik), "company_name": company, "form": form,
                         "filed_date": filed, "filename": filename,
                         "accession": Path(filename).stem})
    if not dates or max(dates) < end:
        raise ValueError("SEC master index is not yet current through requested as-of date")
    selected = pd.DataFrame(rows, columns=["cik", "company_name", "form", "filed_date", "filename", "accession"])
    return sorted(set(selected.cik)), selected, {"index_rows": len(dates), "index_min_filed_date": min(dates),
                                                "index_max_filed_date": max(dates), "candidate_cik_count": selected.cik.nunique()}


def cache_source(cache, url: str, payload: bytes) -> dict:
    with sqlite3.connect(cache.database) as connection:
        row = connection.execute("SELECT fetched_utc,sha256 FROM responses WHERE url=? AND status=200", (url,)).fetchone()
    digest = hashlib.sha256(payload).hexdigest()
    if row is None or row[1] != digest:
        raise ValueError("SEC response cache lineage does not match parsed payload")
    return {"source_kind": "SEC_API", "source_url": url, "source_sha256": digest,
            "fetched_at": row[0], "source_cache_database": str(cache.database.resolve())}


def needs_history(document: dict, start: str, end: str) -> bool:
    return any(str(item.get("filingTo") or "") >= start and str(item.get("filingFrom") or "") <= end
               for item in document.get("filings", {}).get("files", []))


def audit_index_window(index: pd.DataFrame, disclosures: pd.DataFrame, database: Path, start: str, end: str):
    result = index.copy()
    if result.empty:
        return result, {}
    present = set() if disclosures.empty else set(zip(disclosures.cik, disclosures.accession))
    lower = pd.Timestamp(start, tz="America/New_York").tz_convert("UTC")
    upper = (pd.Timestamp(end) + pd.Timedelta(days=1)).tz_localize("America/New_York").tz_convert("UTC")
    statuses, observed = [], []
    with sqlite3.connect(database) as connection:
        for row in result.itertuples(index=False):
            status, accepted = "PRESENT_IN_ACCEPTANCE_WINDOW", pd.NaT
            if (row.cik, row.accession) not in present:
                status = "MISSING_FROM_PRIMARY_SOURCE"
                url = f"https://data.sec.gov/submissions/CIK{int(row.cik):010d}.json"
                cached = connection.execute("SELECT body_zlib FROM responses WHERE url=? AND status=200", (url,)).fetchone()
                if cached and cached[0]:
                    recent = json.loads(zlib.decompress(cached[0])).get("filings", {}).get("recent", {})
                    accessions = recent.get("accessionNumber", [])
                    if row.accession in accessions:
                        position = accessions.index(row.accession)
                        accepted = pd.to_datetime(recent.get("acceptanceDateTime", [])[position], utc=True, errors="coerce")
                        if pd.isna(accepted):
                            status = "MISSING_ACCEPTANCE"
                        elif accepted < lower:
                            status = "ACCEPTED_BEFORE_WINDOW"
                        elif accepted >= upper:
                            status = "ACCEPTED_AFTER_WINDOW"
                        else:
                            status = "UNEXPLAINED_WINDOW_OMISSION"
            statuses.append(status)
            observed.append(accepted)
    result["submission_window_status"] = statuses
    result["outside_window_accepted_at"] = pd.to_datetime(observed, utc=True)
    return result, result.submission_window_status.value_counts().to_dict()


def acceptance_exceptions(index: pd.DataFrame, database: Path, start: str, end: str) -> pd.DataFrame:
    """Retain late-indexed disclosures preceding this increment's acceptance window."""
    rows = []
    selected = index.loc[index.submission_window_status.eq("ACCEPTED_BEFORE_WINDOW")] if not index.empty else index
    with sqlite3.connect(database) as connection:
        for item in selected.itertuples(index=False):
            url = f"https://data.sec.gov/submissions/CIK{int(item.cik):010d}.json"
            cached = connection.execute("SELECT body_zlib,sha256,fetched_utc FROM responses WHERE url=? AND status=200", (url,)).fetchone()
            if not cached:
                raise ValueError("Acceptance exception has no cached official submission")
            payload = zlib.decompress(cached[0])
            digest = hashlib.sha256(payload).hexdigest()
            if digest != cached[1]:
                raise ValueError("Acceptance exception source hash mismatch")
            recent = json.loads(payload).get("filings", {}).get("recent", {})
            position = recent.get("accessionNumber", []).index(item.accession)
            single = {key: [values[position]] for key, values in recent.items()
                      if isinstance(values, list) and position < len(values)}
            source = {"source_kind": "SEC_API", "source_url": url, "source_sha256": digest,
                      "fetched_at": cached[2], "source_cache_database": str(database.resolve())}
            parsed = disclosure_rows(single, int(item.cik), "1900-01-01", end, source)
            if len(parsed) != 1 or pd.isna(parsed[0]["accepted_at"]) or parsed[0]["accepted_at"] != item.outside_window_accepted_at:
                raise ValueError("Acceptance exception timestamp disagrees with audited official source")
            rows.append({**parsed[0], "exception_reason": "INDEXED_IN_WINDOW_ACCEPTED_BEFORE_WINDOW",
                         "index_filed_date": item.filed_date, "requested_window_start": start, "requested_window_end": end})
    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=["cik", "accession", "form", "filed_date", "report_date", "accepted_at",
                                 "primary_document", "acceptance_status", "source_kind", "source_url", "source_sha256",
                                 "fetched_at", "source_cache_database", "exception_reason", "index_filed_date",
                                 "requested_window_start", "requested_window_end"])


def save_acceptance_exceptions(index: pd.DataFrame, database: Path, output: Path, start: str, end: str):
    frame = acceptance_exceptions(index, database, start, end)
    item = save_frame(output / "acceptance_exceptions.parquet", frame)
    manifest = {"schema_version": 1, "dataset_id": "sec_submissions_acceptance_exceptions",
                "status": "OFFICIAL_CACHED_SUBMISSION_SUPPLEMENT", "files": {"submissions": item},
                "requested_increment_window": {"start": start, "as_of": end}, "rows": len(frame),
                "reason": "Official index filing date falls inside increment while actual acceptance precedes it. Keep this separate to supplement an older baseline without changing the increment's acceptance window.",
                "source_cache_database": str(database.resolve()),
                "minimum_accepted_at": None if frame.empty else str(frame.accepted_at.min()),
                "maximum_accepted_at": None if frame.empty else str(frame.accepted_at.max()),
                "merge_key": ["cik", "accession"], "no_new_network_requests": True}
    path = output / "acceptance_exceptions_manifest.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return item, file_identity(path)


def collect(cache, ciks: list[int], start: str, end: str, max_seconds: float, initial_network_failures: int = 0):
    facts, disclosures, statuses = [], [], []
    deadline = time.monotonic() + max_seconds
    consecutive_network_failures = initial_network_failures
    stop_reason = "COMPLETE_CIK_SCAN"
    for index, cik in enumerate(ciks):
        if time.monotonic() >= deadline:
            stop_reason = "STOP_TIME_BUDGET"
            break
        status = {"cik": cik, "submissions_status": "NOT_REQUESTED", "facts_status": "NOT_REQUIRED",
                  "disclosure_rows": 0, "fact_rows": 0, "history_required_for_window": False}
        statuses.append(status)
        url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        try:
            payload = cache.request(url, timeout=20)
            consecutive_network_failures = 0
        except Exception as exc:
            status["submissions_status"] = "FETCH_FAILED"
            status["error"] = str(exc)
            consecutive_network_failures += 1
            if consecutive_network_failures >= 3:
                stop_reason = "STOP_THREE_CONSECUTIVE_NETWORK_FAILURES"
                break
            continue
        try:
            document = json.loads(payload)
            source = cache_source(cache, url, payload)
            rows = disclosure_rows(document, cik, start, end, source)
        except Exception as exc:
            status["submissions_status"] = "PARSE_OR_LINEAGE_FAILED"
            status["error"] = f"{type(exc).__name__}:{exc}"
            continue
        status["submissions_status"] = "PARSED"
        status["history_required_for_window"] = needs_history(document, start, end)
        status["disclosure_rows"] = len(rows)
        disclosures.extend(rows)
        financial = any(row["form"] in FINANCIAL_FORMS for row in rows)
        if financial:
            if time.monotonic() >= deadline:
                status["facts_status"] = "NOT_REQUESTED_TIME_BUDGET"
                stop_reason = "STOP_TIME_BUDGET"
                break
            fact_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
            try:
                fact_payload = cache.request(fact_url, timeout=20)
                consecutive_network_failures = 0
            except Exception as exc:
                status["facts_status"] = "FETCH_FAILED"
                status["error"] = str(exc)
                consecutive_network_failures += 1
                if consecutive_network_failures >= 3:
                    stop_reason = "STOP_THREE_CONSECUTIVE_NETWORK_FAILURES"
                    break
                continue
            try:
                fact_source = cache_source(cache, fact_url, fact_payload)
                fact_items = fact_rows(json.loads(fact_payload), cik, start, end, fact_source)
                facts.extend(fact_items)
                status["facts_status"] = "PARSED"
                status["fact_rows"] = len(fact_items)
            except Exception as exc:
                status["facts_status"] = "PARSE_OR_LINEAGE_FAILED"
                status["error"] = f"{type(exc).__name__}:{exc}"
        if (index + 1) % 50 == 0:
            print(f"SEC_INCREMENTAL_PROGRESS={index + 1}/{len(ciks)};facts_issuers={sum(row['facts_status'] == 'PARSED' for row in statuses)};requests={cache.request_count}", flush=True)
    processed = {row["cik"] for row in statuses}
    statuses.extend({"cik": cik, "submissions_status": "NOT_PROCESSED", "facts_status": "NOT_PROCESSED",
                     "disclosure_rows": 0, "fact_rows": 0, "history_required_for_window": False}
                    for cik in ciks if cik not in processed)
    disclosure_frame = pd.DataFrame(disclosures)
    if not disclosure_frame.empty:
        if disclosure_frame.groupby(["cik", "accession"]).accepted_at.nunique().gt(1).any():
            raise ValueError("Conflicting SEC accession acceptance timestamps")
        disclosure_frame = disclosure_frame.sort_values(["cik", "accession"]).drop_duplicates(["cik", "accession"])
    fact_frame = pd.DataFrame(facts)
    if not fact_frame.empty:
        if disclosure_frame.empty:
            fact_frame["accepted_at"] = pd.NaT
        else:
            fact_frame = fact_frame.merge(disclosure_frame[["cik", "accession", "accepted_at"]],
                                          on=["cik", "accession"], how="left", validate="many_to_one")
        fact_frame["acceptance_status"] = fact_frame.accepted_at.notna().map({True: "KNOWN", False: "MISSING_ACCEPTANCE"})
    return fact_frame, disclosure_frame, pd.DataFrame(statuses), stop_reason


def save_frame(path: Path, frame: pd.DataFrame) -> dict:
    temporary = path.with_suffix(".parquet.tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)
    return {**file_identity(path), "rows": len(frame), "columns": list(frame.columns)}


class SharedRequestGate:
    """One request-start schedule and failure gate for every worker and retry."""
    def __init__(self, interval: float = 0.21):
        self.interval = max(0.2, interval)
        self.lock = threading.Lock()
        self.next_start = 0.0
        self.consecutive_failures = 0
        self.stopped = threading.Event()

    def wait(self):
        with self.lock:
            if self.stopped.is_set():
                raise RuntimeError("GLOBAL_SEC_FAILURE_GATE_STOPPED")
            delay = self.next_start - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.next_start = time.monotonic() + self.interval

    def record(self, success: bool):
        with self.lock:
            if success:
                self.consecutive_failures = 0
            else:
                self.consecutive_failures += 1
                if self.consecutive_failures >= 3:
                    self.stopped.set()


def collect_parallel(parser, cache, ciks, start, end, max_seconds, workers, initial_network_failures=0, seeded=None):
    gate = SharedRequestGate()
    gate.consecutive_failures = initial_network_failures
    local = threading.local()
    instances = []
    deadline = time.monotonic() + max_seconds
    checkpoint_root = cache.root / "parsed_checkpoints"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    checkpoint_contract = hashlib.sha256(json.dumps({"start": start, "end": end,
                                                     "parser_version": 1, "implementation": sha256_file(Path(__file__))}, sort_keys=True).encode()).hexdigest()
    seeded = seeded or {}

    class WorkerCache:
        def __init__(self):
            self.inner = parser.SecCache(cache.root, cache.user_agent)
            self.inner._wait = gate.wait
            self.database = self.inner.database
            instances.append(self.inner)

        @property
        def request_count(self):
            return self.inner.request_count

        def request(self, url, timeout):
            if gate.stopped.is_set():
                raise RuntimeError("GLOBAL_SEC_FAILURE_GATE_STOPPED")
            try:
                payload = self.inner.request(url, timeout=timeout)
            except Exception:
                gate.record(False)
                raise
            gate.record(True)
            return payload

    def one(cik):
        if cik in seeded:
            return (*seeded[cik], True)
        marker = checkpoint_root / f"{cik}.json"
        if marker.exists():
            previous = json.loads(marker.read_text(encoding="utf-8"))
            if previous["contract"] == checkpoint_contract and all(Path(item["path"]).is_file() and sha256_file(Path(item["path"])) == item["sha256"] for item in previous["files"].values()):
                return tuple(pd.read_parquet(previous["files"][name]["path"]) for name in ("facts", "submissions", "status")) + (True,)
        if not hasattr(local, "cache"):
            local.cache = WorkerCache()
        remaining = deadline - time.monotonic()
        if gate.stopped.is_set():
            remaining = 0
        facts, disclosures, status, _ = collect(local.cache, [cik], start, end, remaining)
        complete = status.submissions_status.eq("PARSED").all() and status.facts_status.isin(["PARSED", "NOT_REQUIRED"]).all()
        if complete:
            checkpoint_files = {name: save_frame(checkpoint_root / f"{cik}.{name}.parquet", frame)
                                for name, frame in (("facts", facts), ("submissions", disclosures), ("status", status))}
            temporary = marker.with_suffix(".json.tmp")
            temporary.write_text(json.dumps({"contract": checkpoint_contract, "files": checkpoint_files}) + "\n", encoding="utf-8")
            os.replace(temporary, marker)
        return facts, disclosures, status, False

    pieces, checkpoint_hits = [], 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(one, cik) for cik in ciks]
        for number, future in enumerate(as_completed(futures), 1):
            result = future.result()
            pieces.append(result[:3])
            checkpoint_hits += int(result[3])
            if number % 50 == 0:
                print(f"SEC_INCREMENTAL_PARALLEL={number}/{len(ciks)};checkpoint_hits={checkpoint_hits};network_attempts={sum(item.request_count for item in instances)}", flush=True)
    combined = tuple(pd.concat([piece[i] for piece in pieces if not piece[i].empty], ignore_index=True)
                     if any(not piece[i].empty for piece in pieces) else pd.DataFrame() for i in range(3))
    facts, disclosures, statuses = combined
    if not statuses.empty:
        statuses = statuses.sort_values("cik").reset_index(drop=True)
    if not disclosures.empty:
        disclosures = disclosures.sort_values(["cik", "accession"]).reset_index(drop=True)
    if not facts.empty:
        facts = facts.sort_values(["cik", "accession", "taxonomy", "concept", "unit"]).reset_index(drop=True)
    cache.request_count += sum(item.request_count for item in instances)
    cache.cache_hit_count += sum(item.cache_hit_count for item in instances)
    reason = "COMPLETE_CIK_SCAN"
    if gate.stopped.is_set():
        reason = "STOP_THREE_CONSECUTIVE_NETWORK_FAILURES"
    elif not statuses.empty and (statuses.submissions_status.eq("NOT_PROCESSED").any() or statuses.facts_status.eq("NOT_REQUESTED_TIME_BUDGET").any()):
        reason = "STOP_TIME_BUDGET"
    return facts, disclosures, statuses, reason, {"workers": workers, "global_min_request_interval_seconds": gate.interval,
                                                "parsed_checkpoint_hits": checkpoint_hits, "checkpoint_path": str(checkpoint_root)}


def run(args):
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.as_of)
    if start.strftime("%Y-%m-%d") != args.start or end.strftime("%Y-%m-%d") != args.as_of or start > end:
        raise ValueError("Invalid disclosure date interval")
    if start < pd.Timestamp("2026-01-01"):
        raise ValueError("This ingestion path is scoped to current disclosures from 2026 onward")
    if start.to_period("Q") != end.to_period("Q"):
        raise ValueError("One incremental run must stay within one official SEC master-index quarter")
    output = args.output_root.resolve()
    if any(path.resolve().is_relative_to(output) for path in (args.mapping_file, args.parser_source)):
        raise ValueError("Output must not contain authoritative source inputs")
    ciks = read_ciks(args.mapping_file)
    if len(ciks) > args.max_ciks:
        raise ValueError("Mapped CIKs exceed the configured source-request budget")
    contract = {"mapping": file_identity(args.mapping_file), "parser": file_identity(args.parser_source),
                "start": args.start, "as_of": args.as_of, "ciks": ciks,
                "financial_forms": sorted(FINANCIAL_FORMS), "timeout_seconds": 20,
                "max_unique_submission_requests": len(ciks), "max_companyfacts_requests": len(ciks),
                "max_attempts_per_request": 2, "min_request_interval_seconds": 0.2,
                "candidate_selection": "OFFICIAL_QUARTER_MASTER_INDEX_WITH_FULL_SCAN_FALLBACK"}
    contract_hash = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    manifest_path = output / "incremental_manifest.json"
    previous = None
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["contract_hash"] != contract_hash:
            raise FileExistsError("A different SEC update already occupies the output root")
        for item in previous["files"].values():
            path = Path(item["path"])
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                raise ValueError("Prior incremental output changed; preserve it for review before resume")
        if previous["status"] in {"COMPLETE_CIK_SCAN", "COMPLETE_INDEXED_CANDIDATE_SCAN"}:
            changed = False
            database = Path(previous["source_cache"]["cache_path"]) / "sec_raw_cache.sqlite"
            if "index_audit_status_counts" not in previous:
                index = pd.read_parquet(previous["files"]["filing_index"]["path"])
                disclosures = pd.read_parquet(previous["files"]["submissions"]["path"])
                audited, counts = audit_index_window(index, disclosures, database, args.start, args.as_of)
                previous["files"]["filing_index"] = save_frame(Path(previous["files"]["filing_index"]["path"]), audited)
                previous["index_audit_status_counts"] = counts
                previous["index_unexplained_missing_filings"] = sum(counts.get(key, 0) for key in ("MISSING_FROM_PRIMARY_SOURCE", "MISSING_ACCEPTANCE", "UNEXPLAINED_WINDOW_OMISSION"))
                changed = True
            if "acceptance_exceptions" not in previous["files"]:
                index = pd.read_parquet(previous["files"]["filing_index"]["path"])
                item, supplemental_manifest = save_acceptance_exceptions(index, database, output, args.start, args.as_of)
                previous["files"]["acceptance_exceptions"] = item
                previous["acceptance_exceptions_manifest"] = supplemental_manifest
                changed = True
            if changed:
                temporary = manifest_path.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(previous, indent=2, default=str) + "\n", encoding="utf-8")
                os.replace(temporary, manifest_path)
            return previous
    output.mkdir(parents=True, exist_ok=True)
    parser = load_parser(args.parser_source)
    parser.REQUEST_INTERVAL = max(0.2, parser.REQUEST_INTERVAL)
    cache = parser.SecCache(output / "raw_cache", configured_user_agent(args.user_agent_source))
    index_url = f"https://www.sec.gov/Archives/edgar/full-index/{end.year}/QTR{end.quarter}/master.idx"
    index_frame = pd.DataFrame()
    index_network_failures = 0
    try:
        index_payload = cache.request(index_url, timeout=20)
    except Exception as exc:
        candidate_ciks = ciks
        index_network_failures = 1
        index_selection = {"status": "INDEX_UNAVAILABLE_FULL_CIK_SCAN_FALLBACK", "url": index_url, "error": str(exc)}
    else:
        try:
            candidate_ciks, index_frame, index_metadata = index_candidates(index_payload, ciks, args.start, args.as_of)
            index_selection = {"status": "OFFICIAL_MASTER_INDEX_SELECTION", **index_metadata,
                               "source": cache_source(cache, index_url, index_payload)}
        except Exception as exc:
            candidate_ciks = ciks
            index_selection = {"status": "INDEX_UNUSABLE_FULL_CIK_SCAN_FALLBACK", "url": index_url, "error": str(exc)}
    print(f"SEC_INDEX_SELECTION={index_selection['status']};candidates={len(candidate_ciks)}/{len(ciks)}", flush=True)
    seeded = {}
    if previous:
        prior_status = pd.read_parquet(previous["files"]["cik_status"]["path"])
        complete_ciks = set(prior_status.loc[prior_status.submissions_status.eq("PARSED") &
                                            prior_status.facts_status.isin(["PARSED", "NOT_REQUIRED"]), "cik"])
        grouped = []
        for name in ("companyfacts", "submissions", "cik_status"):
            frame = pd.read_parquet(previous["files"][name]["path"])
            grouped.append({int(cik): group.reset_index(drop=True) for cik, group in frame.groupby("cik")} if not frame.empty else {})
        seeded = {int(cik): tuple(groups.get(int(cik), pd.DataFrame()) for groups in grouped) for cik in complete_ciks}
        print(f"SEC_RESUME_PARSED_CIKS={len(seeded)}", flush=True)
    if args.workers > 1:
        facts, disclosures, statuses, stop_reason, execution = collect_parallel(parser, cache, candidate_ciks, args.start,
                                                                                 args.as_of, args.max_seconds, args.workers,
                                                                                 index_network_failures, seeded)
    else:
        facts, disclosures, statuses, stop_reason = collect(cache, candidate_ciks, args.start, args.as_of,
                                                             args.max_seconds, index_network_failures)
        execution = {"workers": 1, "global_min_request_interval_seconds": 0.2}
    if len(candidate_ciks) < len(ciks):
        candidate_set = set(candidate_ciks)
        not_filing = pd.DataFrame([{"cik": cik, "submissions_status": "NO_NEW_INDEXED_FILINGS", "facts_status": "NOT_REQUIRED",
                                   "disclosure_rows": 0, "fact_rows": 0, "history_required_for_window": False}
                                  for cik in ciks if cik not in candidate_set])
        statuses = pd.concat([statuses, not_filing], ignore_index=True)
    if not index_frame.empty:
        available = set() if disclosures.empty else set(zip(disclosures.cik, disclosures.accession))
        index_frame["present_in_submission_window"] = [(row.cik, row.accession) in available for row in index_frame.itertuples(index=False)]
    index_frame, index_audit_counts = audit_index_window(index_frame, disclosures, cache.database, args.start, args.as_of)
    if stop_reason == "COMPLETE_CIK_SCAN" and index_selection["status"] == "OFFICIAL_MASTER_INDEX_SELECTION":
        stop_reason = "COMPLETE_INDEXED_CANDIDATE_SCAN"
    files = {name: save_frame(output / f"{name}.parquet", frame)
             for name, frame in (("companyfacts", facts), ("submissions", disclosures), ("cik_status", statuses), ("filing_index", index_frame))}
    files["acceptance_exceptions"], supplemental_manifest = save_acceptance_exceptions(index_frame, cache.database, output, args.start, args.as_of)
    cache_manifest = cache.write_manifest({"task": "SEC_OFFICIAL_DISCLOSURE_INCREMENTAL", "start": args.start, "as_of": args.as_of})
    manifest = {"schema_version": 1, "dataset_id": "sec_official_disclosure_incremental", "status": stop_reason,
                "created_at": datetime.now(timezone.utc).isoformat(), "contract_hash": contract_hash, "contract": contract,
                "files": files, "source_cache": cache_manifest, "cik_count": len(ciks),
                "acceptance_exceptions_manifest": supplemental_manifest,
                "index_selection": index_selection,
                "execution": execution,
                "index_filings_missing_submission_window": 0 if index_frame.empty else int((~index_frame.present_in_submission_window).sum()),
                "index_audit_status_counts": index_audit_counts,
                "index_unexplained_missing_filings": sum(index_audit_counts.get(key, 0) for key in ("MISSING_FROM_PRIMARY_SOURCE", "MISSING_ACCEPTANCE", "UNEXPLAINED_WINDOW_OMISSION")),
                "submissions_status_counts": statuses.submissions_status.value_counts().to_dict(),
                "facts_status_counts": statuses.facts_status.value_counts().to_dict(),
                "history_window_gaps": int(statuses.history_required_for_window.sum()),
                "maximum_accepted_at": None if disclosures.empty else str(disclosures.accepted_at.max()),
                "maximum_fact_filed_date": None if facts.empty else str(facts.filed_date.max()),
                "facts_missing_acceptance": 0 if facts.empty else int(facts.acceptance_status.ne("KNOWN").sum()),
                "limitations": ["SEC API retrieval is a current snapshot; timestamps and source versions are retained.",
                                "Historical pages beyond the one primary submissions request per CIK remain explicit coverage gaps.",
                                "Companyfacts is fetched only for mapped CIKs with a financial disclosure in this interval.",
                                "Missing facts/acceptance are preserved as gaps, with no fabricated financial values.",
                                "No model fitting, research evaluation, security mapping inference, or data purchase."]}
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parser-source", type=Path, required=True)
    parser.add_argument("--mapping-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--user-agent-source", type=Path, default=Path("D:/us-tech-quant/scripts/v22/stage_sec_pit_taxonomy.py"))
    parser.add_argument("--start", default="2026-08-22")
    parser.add_argument("--as-of", default="2026-09-11")
    parser.add_argument("--max-ciks", type=int, default=1219)
    parser.add_argument("--max-seconds", type=float, default=600)
    parser.add_argument("--workers", type=int, choices=[1, 2, 3, 4], default=4)
    return parser.parse_args(argv)


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps({key: result[key] for key in ("status", "cik_count", "submissions_status_counts", "facts_status_counts", "maximum_accepted_at")}, indent=2))
