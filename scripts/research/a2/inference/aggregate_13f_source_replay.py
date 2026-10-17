"""Task-scoped 13F source replay; no model, market, training or outcome reader.

Reuses existing raw SEC inspection/amendment logic, the exact frozen instrument
classifier, five-NYSE-session calendar function and aggregate Top100 helper.
Earlier complete SEC bulk infotables retain their established full-accession
extraction lineage. Their original downloaded ZIPs were deleted by that existing
reducer; this reconstruction does not promote that limitation to strict PIT proof.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import types

import pandas as pd
import pandas_market_calendars as mcal
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.daily_recommendation_universe import (
    _inspect_filing, _apply_filings, _reconcile_acceptance,
)
from scripts.storage.refresh_13f_quarter import active_managers, manager_roster_identity, PERSHING_ALIAS
from scripts.research.a2.inference.aggregate_13f_universe import aggregate_snapshot_top100

TASK = "V24_A_13F_AGGREGATE_TOP100_RETEST_20261008_R1"
QUARTERS = ("2025Q3", "2025Q4", "2026Q1", "2026Q2")
PACKAGES = {"2025Q3": "2025_sep_nov", "2025Q4": "2025dec_2026feb", "2026Q1": "2026_mar_may"}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def reference(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def load_verified(ref):
    path = Path(ref["path"])
    if digest(path) != ref["sha256"]:
        raise ValueError("SOURCE_HASH_MISMATCH:" + str(path))
    return path.read_bytes()


def pure_source_functions(path, names, namespace):
    """Extract existing pure definitions without the historical import's mkdir."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in selected} != set(names):
        raise ValueError("BOUND_SOURCE_FUNCTION_MISSING")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return types.SimpleNamespace(**namespace)


def quarter_inventory(receipts, registry, as_of):
    """Select only four authorized report periods, with quarter-effective CIK."""
    documents, originals = {}, {}
    for receipt in receipts:
        if receipt["status"] != 200:
            raise ValueError("SOURCE_REQUEST_NOT_SUCCESSFUL")
        ref = {"path": receipt["raw_path"], "sha256": receipt["sha256"]}
        payload = load_verified(ref)
        if "/submissions/" in receipt["url"]:
            document = json.loads(payload)
            cik = int(document["cik"])
            if cik in documents:
                raise ValueError("DUPLICATE_CURRENT_CIK_SOURCE")
            documents[cik] = (document, {**ref, "url": receipt["url"], "observed_at": receipt["observed_at"], "status": 200})
        else:
            originals[receipt["url"]] = ref
    inventory = []
    for quarter in QUARTERS:
        report_date = str(pd.Period(quarter, freq="Q").end_time.date())
        for manager in active_managers(registry, quarter).to_dict("records"):
            cik = int(manager["cik"])
            if manager["manager_id"] == "pershing_square" and quarter >= PERSHING_ALIAS["valid_from_quarter"]:
                cik = int(PERSHING_ALIAS["cik"])
            document, source = documents[cik]
            arrays = document["filings"]["recent"]
            fields = ("form", "reportDate", "filingDate", "acceptanceDateTime", "accessionNumber")
            if len({len(arrays[field]) for field in fields}) != 1:
                raise ValueError("SUBMISSION_ARRAY_LENGTH_MISMATCH")
            found = []
            for i, period in enumerate(arrays["reportDate"]):
                form = arrays["form"][i]
                if period != report_date or form not in {"13F-HR", "13F-HR/A"}:
                    continue
                accepted = pd.Timestamp(arrays["acceptanceDateTime"][i])
                if accepted.tzinfo is None or pd.isna(accepted):
                    raise ValueError("SOURCE_ACCEPTANCE_TIMEZONE_MISSING")
                if accepted > as_of:
                    continue
                accession = arrays["accessionNumber"][i]
                found.append({"quarter": quarter, "manager_id": manager["manager_id"],
                    "manager_name": manager["manager_name"], "manager_weight": float(manager["manager_weight"]),
                    "cik": cik, "form": form, "report_date": period,
                    "filed_date": arrays["filingDate"][i], "accepted_at": accepted.isoformat(),
                    "current_summary_accepted_at": accepted.isoformat(), "accession": accession,
                    "source_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}.txt",
                    "submission_metadata_reference": source})
            if sum(row["form"] == "13F-HR" for row in found) != 1:
                raise ValueError("EXACT_ONE_INITIAL_REQUIRED:" + quarter + ":" + manager["manager_id"])
            inventory.extend(found)
    return inventory, originals


def bulk_initial_records(root, quarter, filings):
    """Read the one authorized package, retaining every row of each accession."""
    label = PACKAGES[quarter]
    meta_path = root / (label + "_meta.json")
    sub_path = root / (label + "_submission.parquet")
    info_path = root / (label + "_infotable.parquet")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta["infotable_rows"] != pq.ParquetFile(info_path).metadata.num_rows or meta["submission_rows"] != pq.ParquetFile(sub_path).metadata.num_rows:
        raise ValueError("BULK_PACKAGE_ROW_COUNT_MISMATCH")
    submissions = pd.read_parquet(sub_path)
    initial = [row for row in filings if row["form"] == "13F-HR"]
    accessions = [row["accession"] for row in initial]
    # All three packages are inside this evaluation's authorized source window;
    # the predicate isolates selected initial accessions before materialization.
    info = pd.read_parquet(info_path, filters=[("ACCESSION_NUMBER", "in", accessions)]).fillna("")
    refs = {"bulk_meta": reference(meta_path), "bulk_submissions": reference(sub_path), "bulk_infotable": reference(info_path)}
    records = []
    for filing in initial:
        matches = submissions.loc[submissions.ACCESSION_NUMBER.eq(filing["accession"])]
        if len(matches) != 1:
            raise ValueError("BULK_INITIAL_ACCESSION_MISSING_OR_DUPLICATE")
        row = matches.iloc[0]
        if (int(row.CIK) != filing["cik"] or str(pd.to_datetime(row.PERIODOFREPORT).date()) != filing["report_date"]
                or str(pd.to_datetime(row.FILING_DATE).date()) != filing["filed_date"] or row.SUBMISSIONTYPE != "13F-HR"):
            raise ValueError("BULK_CURRENT_SUBMISSION_IDENTITY_MISMATCH")
        group = info.loc[info.ACCESSION_NUMBER.eq(filing["accession"])]
        if group.empty or group.INFOTABLE_SK.duplicated().any():
            raise ValueError("BULK_FULL_INITIAL_ROWS_MISSING_OR_DUPLICATE")
        # Every scoped filing postdates the existing SEC USD-unit cutover. No
        # current-price conversion or old v17b unconditional x1000 is used.
        if filing["filed_date"] < "2023-01-03":
            raise ValueError("OUTSIDE_TASK_POST_CUTOVER_USD_SCOPE")
        rows = []
        for raw in group.to_dict("records"):
            value = Decimal(str(raw["VALUE"]))
            if not value.is_finite() or value < 0:
                raise ValueError("BULK_VALUE_INVALID")
            rows.append({"issuer_name": raw["NAMEOFISSUER"], "title_of_class": raw["TITLEOFCLASS"],
                "cusip": str(raw["CUSIP"]).strip().upper(), "figi": raw.get("FIGI", ""),
                "value_usd": str(value), "shares": str(raw["SSHPRNAMT"]),
                "share_type": raw["SSHPRNAMTTYPE"], "put_call": raw["PUTCALL"],
                "original_source_row_id": str(raw["INFOTABLE_SK"]), "original_accession": filing["accession"]})
        details = {"amendment_type": "", "confidential_omitted": "",
            "source_value_total_reconciled": None, "detail_minus_cover": None,
            "completeness_basis": "EXISTING_SEC_BULK_FULL_ACCESSION_EXTRACTION_NO_HOLDING_CAP",
            "refs": refs, "source_row_count": len(rows),
            "source_usd_total": str(sum((Decimal(row["value_usd"]) for row in rows), Decimal(0)))}
        records.append((filing, rows, details))
    return records


def raw_record(filing, ref, parser, prior_acquisition, as_of):
    payload = load_verified(ref)
    reconciled = None
    if prior_acquisition is not None:
        filing, reconciled = _reconcile_acceptance(payload, filing, prior_acquisition,
            filing["submission_metadata_reference"], as_of)
    rows, details = _inspect_filing(payload, filing, parser)

    for index, row in enumerate(rows):
        row["value_usd"] = str(Decimal(str(row["value_usd"])))
        row["original_source_row_id"] = str(index)
        row["original_accession"] = filing["accession"]
    details.update(refs={"raw_filing": ref}, completeness_basis="RAW_SEC_COVER_ROW_COUNT_RECONCILED_USD_TOTAL_DIFFERENCE_RETAINED",
        source_row_count=len(rows), source_usd_total=str(sum((Decimal(row["value_usd"]) for row in rows), Decimal(0))))
    if reconciled:
        details["acceptance_reconciliation"] = reconciled
    return filing, rows, details


def construct_snapshot(records, registry, quarter, snapshot_id, effective_at, as_of, classifier, unit_ref):
    """Apply initial+as-of amendment states with the existing business owner."""
    full, effective_filings = _apply_filings(records)
    if set(effective_filings.manager_id) != set(active_managers(registry, quarter).manager_id):
        raise ValueError("SNAPSHOT_MANAGER_COHORT_INCOMPLETE")
    if "shares" in full:
        full["shares"] = full.shares.map(lambda value: "" if pd.isna(value) else str(value))
    full["snapshot_id"] = snapshot_id
    full["value_usd"] = full.value_usd.map(lambda value: str(Decimal(str(value))))
    evidence, qualifications = [], []
    for manager in sorted(effective_filings.manager_id):
        contributing = [record for record in records if record[0]["manager_id"] == manager]
        group = full.loc[full.manager_id.eq(manager)].copy()
        source = [{"filing": record[0], "details": record[2]} for record in contributing]
        qualification_sha = hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()
        source_sha = hashlib.sha256(group.to_json(orient="records", date_format="iso").encode()).hexdigest()
        latest = effective_filings.loc[effective_filings.manager_id.eq(manager)].iloc[0]
        full.loc[group.index, "source_row_id"] = [str(index) for index in range(len(group))]
        full.loc[group.index, "source_sha256"] = source_sha
        evidence.append({"snapshot_id": snapshot_id, "quarter": quarter, "manager_id": manager,
            "holdings_scope": "FULL_AS_FILED_HOLDINGS", "full_report_complete": True,
            "amendment_resolved": True, "full_row_count": len(group),
            "full_value_usd": str(sum((Decimal(value) for value in group.value_usd), Decimal(0))),
            "source_sha256": source_sha, "qualification_sha256": qualification_sha,
            "unit_evidence_sha256": unit_ref["sha256"], "accepted_at": latest.accepted_at,
            "qualification_available_at": latest.accepted_at, "effective_at": effective_at.isoformat(),
            "availability_basis": "PUBLIC_AS_FILED_INFORMATION_RECONSTRUCTED_NOT_HISTORICAL_VENDOR_ARRIVAL"})
        qualifications.append({"manager_id": manager, "qualification_sha256": qualification_sha,
            "source_sha256": source_sha, "contributing_filings": source})
    evidence = pd.DataFrame(evidence)
    result = aggregate_snapshot_top100(full, evidence, registry, quarter=quarter,
        snapshot_id=snapshot_id, decision_at=as_of, classify_equity=classifier)
    return full, evidence, result, qualifications


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return reference(path)


def run(as_of):
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        raise ValueError("AS_OF_TIMEZONE_REQUIRED")
    paths = resolve(Path(__file__).resolve().parents[4])
    cache = paths.cache_root / "V24" / TASK / "sec_verification"
    output = paths.backtest_root / TASK / "source_snapshots"
    reports = paths.results_root / "_maintenance" / TASK
    for folder, kind in ((output, "backtest"), (reports, "results")):
        assert_safe_output_path(folder, kind=kind, paths=paths)
        folder.mkdir(parents=True, exist_ok=True)
    package = paths.results_root / "13f_pit_v1"
    registry_path = package / "config/manager_registry.csv"
    registry = pd.read_csv(registry_path, dtype=str, keep_default_na=False)
    parser_path = package / "scripts/build_13f_history.py"
    parser = pure_source_functions(parser_path, {"localname", "text_at", "parse_holdings", "add_five_nyse_sessions"}, {"dt": dt, "mcal": mcal})
    classifier_path = package / "scripts/v17b/eligibility_v17b.py"
    scope = {}; exec(compile(classifier_path.read_text(encoding="utf-8-sig"), str(classifier_path), "exec"), scope)
    classifier = scope["classify_equity"]
    receipt_path = cache / "request_receipts.json"
    receipts = json.loads(receipt_path.read_text(encoding="utf-8"))["sources"]
    inventory, originals = quarter_inventory(receipts, registry, as_of)
    acquisition_path = paths.results_root / "13f_intake/13f_personal_contact_20260914/acquisition.json"
    acquisition_ref = reference(acquisition_path)
    prior = json.loads(acquisition_path.read_text(encoding="utf-8"))
    q2_raw = {row["accession"]: {"path": row["raw_path"], "sha256": row["source_sha256"]} for row in prior["verified_filings"]}
    records, source_gaps = [], []
    for quarter in QUARTERS:
        scoped = [row for row in inventory if row["quarter"] == quarter]
        if quarter in PACKAGES:
            records.extend(bulk_initial_records(paths.cache_root / "13f_pit_v1/sec_bulk_reduced", quarter, scoped))
        for filing in scoped:
            if quarter in PACKAGES and filing["form"] == "13F-HR":
                continue
            ref = originals.get(filing["source_url"]) or q2_raw.get(filing["accession"])
            if ref is None:
                source_gaps.append({"accession": filing["accession"], "reason": "RAW_AMENDMENT_OR_Q2_INITIAL_SOURCE_MISSING"})
                continue
            prior_ref = acquisition_ref if filing["accession"] in q2_raw else None
            records.append(raw_record(filing, ref, parser, prior_ref, as_of))
    if source_gaps:
        raise ValueError("SOURCE_GAPS:" + json.dumps(source_gaps))
    all_members, all_full, all_evidence, schedule, qualification_details = [], [], [], [], []
    for quarter in QUARTERS:
        initial = [record for record in records if record[0]["quarter"] == quarter and record[0]["form"] == "13F-HR"]
        amendments = sorted([record for record in records if record[0]["quarter"] == quarter and record[0]["form"] == "13F-HR/A"], key=lambda record: (record[0]["accepted_at"], record[0]["accession"]))
        states = [initial]
        for index in range(len(amendments)):
            states.append(initial + amendments[:index + 1])
        for revision, state in enumerate(states):
            latest_date = max(record[0]["filed_date"] for record in state)
            effective_day = parser.add_five_nyse_sessions(latest_date)
            effective = pd.Timestamp(effective_day + " 09:30:00", tz="America/New_York").tz_convert("UTC")
            if effective > as_of:
                continue
            snapshot_id = quarter + "_r" + str(revision) + "_" + effective_day
            full, evidence, ranked, qualifications = construct_snapshot(state, registry, quarter, snapshot_id, effective, as_of, classifier, reference(parser_path))
            all_members.append(ranked["members"]); all_full.append(full); all_evidence.append(evidence)
            schedule.append({"snapshot_id": snapshot_id, "quarter": quarter, "revision": revision,
                "effective_at": effective.isoformat(), "latest_accepted_at": max(pd.Timestamp(row[0]["accepted_at"]) for row in state).isoformat(),
                "latest_filing_date": latest_date, "institution_count": len(evidence),
                "applicable_manager_count": len(evidence), "universe_member_count": len(ranked["members"]),
                "roster_sha256": ranked["audit"]["roster"]["roster_sha256"],
                "source_qualification": "AS_FILED_SOURCE_RECONSTRUCTION_WITH_DECLARED_PROVENANCE_LIMITS"})
            qualification_details.append({"snapshot_id": snapshot_id, "audit": ranked["audit"], "managers": qualifications})
    files = {}
    for name, frame in (("schedule", pd.DataFrame(schedule)), ("members", pd.concat(all_members, ignore_index=True)),
                        ("full_holdings", pd.concat(all_full, ignore_index=True)), ("manager_evidence", pd.concat(all_evidence, ignore_index=True))):
        path = output / (name + ".parquet")
        frame.to_parquet(path, index=False, compression="zstd")
        files[name] = {**reference(path), "rows": len(frame), "columns": list(frame.columns)}
    files["filing_inventory"] = write_json(output / "filing_inventory.json", {"task_id": TASK, "as_of": as_of.isoformat(), "filings": inventory})
    files["qualification_details"] = write_json(output / "qualification_details.json", {"task_id": TASK, "snapshots": qualification_details})
    plan_path = reports / "EVALUATION_PLAN.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    limitations = ["Original SEC bulk ZIPs for the first three quarters were deleted by the existing reducer; retained full-accession tables, package counts, source URL and unchanged extraction code establish the existing lineage, not a new raw-archive proof.",
        "Initial bulk filings have no retained cover-page totals/confidential-omission fields; full INFOTABLE extraction is used, not fabricated independent cover reconciliation.",
        "Current source retrieval is retrospective. Public accepted timestamps and forward-only amendment states reconstruct public information; historical vendor arrival and original qualification computation times are not certified.",
        "qualification_available_at in manager evidence means underlying public as-filed information availability, not the date this replay verified it.",
        "CUSIP membership is ranked before mapping/price coverage. Missing identities or prices may not be replaced by rank101."]
    source_refs = {"registry": reference(registry_path), "parser_and_unit_rule": reference(parser_path),
        "classifier": reference(classifier_path), "bulk_reducer": reference(package / "scripts/v11/bulk_13f_rebuild.py"),
        "current_sec_receipts": reference(receipt_path), "prior_q2_acquisition": acquisition_ref,
        "adapter": reference(Path(__file__)), "aggregate_helper": reference(Path(__file__).with_name("aggregate_13f_universe.py")),
        "evaluation_plan": reference(plan_path)}
    report = {"task_id": TASK, "status": "SOURCE_REPLAY_EXECUTED_WITH_DECLARED_PROVENANCE_LIMITS", "strict_pit_status": "NOT_PROMOTED_NOT_HISTORICAL_VENDOR_ARRIVAL_CERTIFIED",
        "as_of": as_of.isoformat(), "source_scope": "FOUR_QUARTERS_FULL_HOLDINGS_AND_ASOF_AMENDMENTS_NO_MARKET_OUTCOMES",
        "tracked_manager_count": len(registry), "filing_count": len(inventory), "initial_count": sum(row["form"] == "13F-HR" for row in inventory),
        "amendments": [{"filing": record[0], "details": record[2]} for record in records if record[0]["form"] == "13F-HR/A"],
        "source_value_issues": [{"accession": record[0]["accession"], "manager_id": record[0]["manager_id"], "detail_minus_cover": record[2]["detail_minus_cover"]} for record in records if record[2].get("source_value_total_reconciled") is False], "snapshots": schedule, "files": files, "source_refs": source_refs, "limitations": limitations}
    report_ref = write_json(reports / "source_qualification.json", report)
    manifest = {"task_id": TASK, "as_of": as_of.isoformat(), "status": report["status"], "strict_pit_status": report["strict_pit_status"],
        "universe_change": plan["universe_change"], "source_qualification_ref": report_ref,
        "files": files, "source_refs": source_refs, "snapshot_availability": schedule, "limitations": limitations}
    manifest_ref = write_json(output / "source_manifest.json", manifest)
    print(json.dumps({"status": report["status"], "source_manifest": manifest_ref, "snapshot_count": len(schedule), "member_rows": sum(len(frame) for frame in all_members), "filings": len(inventory)}, indent=2))
    return manifest


if __name__ == "__main__":
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--as-of", required=True)
    run(argument_parser.parse_args().as_of)
