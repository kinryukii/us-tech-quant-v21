"""Bounded historical consensus input adapter for the fixed base/gross study.

No I/O on import. Metadata projection precedes every potential holdings read.
Amendment interpretation, ranking and daily projection keep their existing owners.
Metadata completeness does not certify public acceptance or amendment cover data.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.research.a2.data import consensus100_inputs as inputs
from scripts.research.a2.inference import aggregate_13f_source_replay as source
from scripts.research.a2.inference.aggregate_13f_universe import aggregate_snapshot_top100
from scripts.research.a2.evaluation import aggregate_13f_retest as projection
from scripts.storage.refresh_13f_quarter import active_managers

TASK = "A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1"
CUTOFF = pd.Timestamp("2024-10-07")
START = pd.Timestamp("2024-01-01")
QUARTERS = ("2023Q3", "2023Q4", "2024Q1", "2024Q2")
RULE = "MANAGER_COUNT_WEIGHT_SUM"


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _date_literals(lower, upper):
    """The unchanged SEC metadata parser's supported date encodings."""
    result = set()
    for day in pd.date_range(lower, upper):
        sec = day.strftime("%d-%b-%Y")
        result.update((sec, sec.upper(), sec.lower(), day.strftime("%Y-%m-%d"),
                       day.strftime("%m/%d/%Y")))
    return sorted(result)


def submission_metadata(meta_path):
    """Project legal filing metadata with a predicate before reading any rows.

    The mixed September-November archive is filtered at the Parquet reader, not
    loaded whole and filtered afterwards. No INFOTABLE payload is read or hashed.
    Unknown encodings/acceptance/cover evidence are not fabricated.
    """
    path = Path(meta_path)
    _require(path.stat().st_size <= 65536, "BOUNDED_PACKAGE_METADATA_REQUIRED")
    meta = json.loads(path.read_text(encoding="utf-8"))
    lower, upper = inputs.package_window(meta["filename"])
    _require(lower <= upper and lower < CUTOFF, "PACKAGE_OUTSIDE_HISTORY")
    url = urlparse(meta["url"])
    _require(url.scheme == "https" and url.netloc.lower() == "www.sec.gov"
             and url.path == "/files/structureddata/data/form-13f-data-sets/" + meta["filename"],
             "OFFICIAL_PACKAGE_ORIGIN_REQUIRED")
    label = meta["label"]
    _require(path.name == label + "_meta.json" and Path(label).name == label,
             "EXACT_PACKAGE_LABEL_REQUIRED")
    sub = path.with_name(label + "_submission.parquet")
    info = path.with_name(label + "_infotable.parquet")
    sub_file, info_file = pq.ParquetFile(sub), pq.ParquetFile(info)
    _require(set(inputs.SUB_COLUMNS) <= set(sub_file.schema_arrow.names)
             and set(inputs.INFO_COLUMNS) <= set(info_file.schema_arrow.names),
             "SOURCE_SCHEMA_REQUIRED")
    _require(pa.types.is_string(sub_file.schema_arrow.field("FILING_DATE").type)
             or pa.types.is_large_string(sub_file.schema_arrow.field("FILING_DATE").type),
             "SUPPORTED_SEC_DATE_ENCODING_REQUIRED")
    _require(sub_file.metadata.num_rows == meta["submission_rows"]
             and info_file.metadata.num_rows == meta["infotable_rows"], "PACKAGE_COUNT_CHANGED")
    before = inputs.file_ref(sub)
    literals = _date_literals(lower, min(upper, CUTOFF - pd.Timedelta(days=1)))
    table = pq.read_table(sub, columns=inputs.SUB_COLUMNS,
                          filters=[("FILING_DATE", "in", literals)]).to_pandas()
    inputs.verify_ref(before)
    filed, report = inputs.parse_dates(table.FILING_DATE), inputs.parse_dates(table.PERIODOFREPORT)
    _require((filed < CUTOFF).all() and (report <= filed).all()
             and (filed >= lower).all() and (filed <= upper).all(), "ILLEGAL_PROJECTED_CLOCK")
    if upper < CUTOFF:
        _require(len(table) == sub_file.metadata.num_rows, "DATE_PREDICATE_LOST_FINITE_METADATA")
    table = table.assign(filed_date=filed.strftime("%Y-%m-%d"),
                         report_date=report.strftime("%Y-%m-%d"), quarter=report.to_period("Q").astype(str))
    table = table.loc[table.quarter.isin(QUARTERS)
                      & table.SUBMISSIONTYPE.isin(("13F-HR", "13F-HR/A"))].copy()
    table["package"] = label
    table["accepted_at"] = None
    receipt = dict(meta_ref=inputs.file_ref(path), submission_ref=before,
                   infotable_footer=dict(path=str(info.resolve()), size=info.stat().st_size,
                       rows=info_file.metadata.num_rows, hash_deferred_until_holdings_authorization=True),
                   source_window=[str(lower.date()), str(upper.date())],
                   cutoff_exclusive=str(CUTOFF.date()), projected_rows=len(table),
                   predicate_columns=["FILING_DATE"], projected_columns=list(inputs.SUB_COLUMNS),
                   holding_values_read=False, acceptance_certified=False,
                   mixed_archive_date_predicate=upper >= CUTOFF)
    return table, receipt


def inventory_metadata(tables, registry, aliases):
    """Map source metadata using historical applicable rosters and CIK aliases."""
    rows = []
    for table in tables:
        for row in table.to_dict("records"):
            quarter = row["quarter"]
            active = active_managers(registry, quarter)
            valid = aliases.loc[aliases.manager_id.isin(active.manager_id)
                & aliases.cik.astype(str).map(int).eq(int(row["CIK"]))
                & aliases.valid_from_quarter.le(quarter)
                & (aliases.valid_to_quarter.eq("") | aliases.valid_to_quarter.ge(quarter))]
            names = sorted(set(valid.manager_id))
            if not names:
                continue
            _require(len(names) == 1, "AMBIGUOUS_HISTORICAL_CIK")
            manager = active.loc[active.manager_id.eq(names[0])].iloc[0]
            rows.append(dict(manager_id=names[0], manager_name=manager["manager_name"],
                manager_weight=float(manager["manager_weight"]), cik=int(row["CIK"]), quarter=quarter,
                accession=str(row["ACCESSION_NUMBER"]), form=row["SUBMISSIONTYPE"],
                filed_date=row["filed_date"], report_date=row["report_date"],
                accepted_at=row["accepted_at"], package=row["package"]))
    frame = pd.DataFrame(rows)
    _require(not frame.empty, "NO_LEGAL_TRACKED_FILING_METADATA")
    fields = [name for name in frame if name != "package"]
    _require(not frame.drop_duplicates(fields).accession.duplicated().any(), "ACCESSION_METADATA_CONFLICT")
    return frame.drop_duplicates(fields).reset_index(drop=True)


def load_records(metadata, raw_loader):
    """Validate all disclosure coordinates before invoking a holdings loader.

    A caller can attach actual locally evidenced accepted_at and cover/source
    references after metadata preflight. Missing evidence blocks the callback.
    No filing-date proxy is substituted for an SEC acceptance timestamp.
    """
    stamps = [pd.Timestamp(value) for value in metadata.accepted_at]
    _require(all(not pd.isna(value) and value.tzinfo is not None for value in stamps),
             "ACTUAL_ACCEPTANCE_EVIDENCE_REQUIRED")
    accepted = pd.DatetimeIndex([value.tz_convert("UTC") for value in stamps])
    cut = CUTOFF.tz_localize("America/New_York").tz_convert("UTC")
    _require((accepted < cut).all() and (pd.to_datetime(metadata.filed_date) < CUTOFF).all(),
             "FUTURE_FILING_BEFORE_HOLDINGS_READ")
    required = ["source_ref", "cover_evidence_ref"]
    _require(all(name in metadata and metadata[name].notna().all() for name in required),
             "LOCAL_SOURCE_AND_COVER_EVIDENCE_REQUIRED")
    result = []
    for row in metadata.to_dict("records"):
        record = raw_loader(row)
        _require(all(record[0][key] == row[key] for key in
            ("accession", "quarter", "manager_id", "form", "filed_date", "accepted_at")),
            "LOADED_FILING_IDENTITY_CHANGED")
        result.append(record)
    return result



def _code_sha(function):
    import hashlib, marshal
    return hashlib.sha256(marshal.dumps(function.__code__)).hexdigest()


PROJECTOR_OWNER_SHA = "9aa352e075b8b29fc3e11e1851e1cc690e09ac4dbee002cac598c865640b39a3"
PROJECTOR_CODE_SHA = "0b4ce3b165710c67274c18cebe41f04838351d77bb36750011a4191bc7e8347f"


class _HistoricalTaskRouting:
    """Pure routing for this one metadata transform; grants no source/fit rights."""
    @staticmethod
    def universe_variant_tasks():
        return frozenset((TASK,))

    @staticmethod
    def consensus_variant_tasks():
        return frozenset((TASK,))


def _isolated_projector():
    import types
    owner = inputs.file_ref(Path(projection.__file__))
    _require(owner["sha256"] == PROJECTOR_OWNER_SHA, "HISTORICAL_PROJECTOR_OWNER_CHANGED")
    _require(_code_sha(projection.project_universe) == PROJECTOR_CODE_SHA, "HISTORICAL_PROJECTOR_CODE_CHANGED")
    namespace = {"pd": pd, "_need": projection._need,
                 "authority": _HistoricalTaskRouting,
                 "__builtins__": projection.project_universe.__globals__["__builtins__"]}
    fn = types.FunctionType(projection.project_universe.__code__, namespace,
                            "qualified_historical_projection", projection.project_universe.__defaults__)
    fn.__kwdefaults__ = dict(projection.project_universe.__kwdefaults__)
    _require(fn.__code__ is projection.project_universe.__code__, "CANONICAL_PROJECTOR_CODE_REQUIRED")
    return fn, dict(owner_ref=owner, code_sha256=_code_sha(fn),
                    isolated_task_routing=[TASK], shared_globals_changed=False)


def source_records(metadata, paths, acquisition):
    """Reuse complete initial-accession loader and official amended originals.

    Original accepted_at for initials remains UNKNOWN. The compatibility input
    accepted_at slot transports an explicitly typed public-day upper bound;
    it is never recorded as a proven initial SEC acceptance timestamp. Distinct
    per-manager filing days make its ordering unambiguous. The five-NYSE clock
    continues to use filed_date, including every applicable manager.
    """
    import types
    from decimal import Decimal
    _require(not metadata.duplicated(["quarter", "manager_id", "filed_date"]).any(),
             "PUBLIC_DAY_ORDER_AMBIGUOUS")
    transport = []
    known = {row["accession"]: row for row in acquisition["sources"]}
    for row in metadata.to_dict("records"):
        filing = dict(row)
        upper = (pd.Timestamp(filing["filed_date"]) + pd.Timedelta(days=1)).tz_localize("America/New_York").tz_convert("UTC")
        original = known.get(filing["accession"])
        actual = original["filing"]["accepted_at"] if original else None
        filing.update(original_accepted_at=actual, disclosure_upper_bound_at=upper.isoformat(),
            accepted_at=actual or upper.isoformat(),
            accepted_at_role="ACTUAL_SEC_HEADER" if actual else "PUBLIC_DAY_UPPER_BOUND_ONLY")
        transport.append(filing)
    mapping = {q: next(r["package"] for r in transport if r["quarter"] == q and r["form"] == "13F-HR")
               for q in QUARTERS}
    _require(all({r["package"] for r in transport if r["quarter"] == q and r["form"] == "13F-HR"}
                 == {mapping[q]} for q in QUARTERS), "INITIAL_PACKAGE_AMBIGUOUS")
    namespace = dict(source.bulk_initial_records.__globals__, PACKAGES=mapping)
    bulk = types.FunctionType(source.bulk_initial_records.__code__, namespace,
                              "qualified_historical_bulk_initial", source.bulk_initial_records.__defaults__)
    records = []
    root = paths.cache_root / "13f_pit_v1/sec_bulk_reduced"
    for quarter in QUARTERS:
        meta_path = root / (mapping[quarter] + "_meta.json")
        window = inputs.package_window(json.loads(meta_path.read_text(encoding="utf-8"))["filename"])
        _require(window[1] < CUTOFF, "INITIAL_PACKAGE_MIXES_RESTRICTED_CLOCKS")
        records.extend(bulk(root, quarter, [r for r in transport if r["quarter"] == quarter]))
    parser, classifier, owners = inputs.existing_filing_owners(paths)
    for filing in transport:
        if filing["form"] != "13F-HR/A":
            continue
        item = known.get(filing["accession"])
        _require(item and item["status"] == "VERIFIED_ORIGINAL", "VERIFIED_ORIGINAL_AMENDMENT_REQUIRED")
        _require(all(item["filing"][k] == filing[k] for k in
            ("accession", "quarter", "manager_id", "form", "filed_date", "accepted_at")),
            "ORIGINAL_AMENDMENT_METADATA_CHANGED")
        records.append(source.raw_record(filing, item["raw_ref"], parser, None,
                           CUTOFF.tz_localize("America/New_York").tz_convert("UTC")))
    lineage = dict(clock_policy="PUBLIC_DAY_BOUNDS_TYPED_WITH_ACTUAL_AMENDMENT_HEADERS",
        original_initial_acceptance="UNKNOWN", unknown_initial_confidential_fields="RETAINED_UNKNOWN",
        source_owner_ref=inputs.file_ref(Path(source.__file__)),
        strict_apply_owner_ref=inputs.file_ref(Path(source._apply_filings.__code__.co_filename)),
        bulk_code_sha256=_code_sha(bulk), strict_apply_code_sha256=_code_sha(source._apply_filings),
        initial_packages=mapping, source_owners=owners,
        filing_clocks=[{k:r[k] for k in ("accession", "quarter", "manager_id", "filed_date",
                        "original_accepted_at", "disclosure_upper_bound_at", "accepted_at_role")} for r in transport])
    return records, classifier, owners["unit_parser"], lineage


def rank_states(records, registry, classifier, unit_ref, add_five_sessions=None):
    """Keep every state, including strict rejections; never fix metadata to pass."""
    import types
    cut = CUTOFF.tz_localize("America/New_York").tz_convert("UTC")
    for filing, _, _ in records:
        stamp = pd.Timestamp(filing["accepted_at"])
        _require(stamp.tzinfo is not None and stamp < cut
                 and pd.Timestamp(filing["filed_date"]) < CUTOFF
                 and filing["quarter"] in QUARTERS, "ILLEGAL_HISTORY_RECORD")
    def consensus_owner(*args, **kwargs):
        kwargs["selection_rule"] = RULE
        return aggregate_snapshot_top100(*args, **kwargs)
    snapshot_fn = types.FunctionType(source.construct_snapshot.__code__,
        dict(source.construct_snapshot.__globals__, aggregate_snapshot_top100=consensus_owner),
        "qualified_historical_consensus_snapshot", source.construct_snapshot.__defaults__)
    states, ranked = [], []
    for quarter in QUARTERS:
        original = [r for r in records if r[0]["quarter"] == quarter and r[0]["form"] == "13F-HR"]
        expected = set(active_managers(registry, quarter).manager_id)
        _require(len(original) == len(expected) and {r[0]["manager_id"] for r in original} == expected,
                 "ALL_APPLICABLE_INITIAL_FILINGS_REQUIRED")
        amended = sorted((r for r in records if r[0]["quarter"] == quarter and r[0]["form"] == "13F-HR/A"),
                         key=lambda r:(r[0]["accepted_at"],r[0]["accession"]))
        for revision in range(len(amended) + 1):
            state = original + amended[:revision]
            effective = inputs.initial_public_activation(r[0]["filed_date"] for r in state)
            sid = quarter + "_r" + str(revision) + "_" + str(effective.tz_convert("America/New_York").date())
            item = dict(snapshot_id=sid, quarter=quarter, effective_at=effective, revision=revision,
                        institution_count=len(expected), source_status="UNQUALIFIED", error=None)
            if effective >= cut:
                item["error"] = "ACTIVATION_AFTER_CONTROLLER_CUTOFF"
            else:
                try:
                    # Original strict amendment/confidential rules execute unchanged.
                    _, _, result, _ = snapshot_fn(state, registry, quarter, sid,
                        effective, cut-pd.Timedelta(nanoseconds=1), classifier, unit_ref)
                    ranked.append(result["members"])
                    item["source_status"] = "QUALIFIED_RESEARCH_SOURCE"
                except ValueError as exc:
                    item["error"] = str(exc)
            states.append(item)
    members = pd.concat(ranked, ignore_index=True) if ranked else pd.DataFrame()
    return pd.DataFrame(states), members


def qualification_schedule(states, sessions):
    """Select current qualified states, then leave quarter choice to its owner.

    A rejected newly effective revision revokes its prior state. Other quarters
    remain candidates under the frozen latest-complete-quarter policy.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(sessions))
    _require(len(dates) and dates.tz is None and dates.is_unique and dates.is_monotonic_increasing
             and (dates >= START).all() and (dates < CUTOFF).all(), "HISTORICAL_CONTROLLER_WINDOW_REQUIRED")
    states = states.copy()
    states["effective_at"] = states.effective_at.map(pd.Timestamp)
    book, ledgers = [], []
    for date in dates:
        close = date.tz_localize("America/New_York") + pd.Timedelta(hours=16)
        available = states.loc[states.effective_at.le(close)]
        latest = available.sort_values(["quarter", "effective_at", "revision"]).groupby("quarter").tail(1)
        qualified = latest.loc[latest.source_status.eq("QUALIFIED_RESEARCH_SOURCE")]
        ids = tuple(qualified.snapshot_id)
        book.append((date, qualified))
        ledgers.append(dict(signal_date=date, source_status="QUALIFIED_RESEARCH_SOURCE" if ids else "SOURCE_UNQUALIFIED",
            qualified_snapshot_ids=list(ids), rejected_latest_states=latest.loc[~latest.source_status.eq("QUALIFIED_RESEARCH_SOURCE"),
                ["quarter", "snapshot_id", "error"]].to_dict("records")))
    return book, ledgers


def frame_sha(frame):
    import hashlib
    return hashlib.sha256(frame.to_json(orient="records", date_format="iso").encode()).hexdigest()


def project_history(states, members, dated_identity, sessions, *, source_receipt=None):
    """Use unchanged CodeType in a private namespace; no shared whitelist edits."""
    book, ledgers = qualification_schedule(states, sessions)
    _require(source_receipt and source_receipt.get("task_id") == TASK
             and source_receipt.get("status") == "QUALIFIED_RESEARCH_SOURCE_WITH_EXPLICIT_REJECTIONS"
             and source_receipt.get("policy") == "LATEST_COMPLETE_PUBLIC_EFFECTIVE_QUARTER_WITH_ASOF_AMENDMENTS"
             and source_receipt.get("cutoff_exclusive") == str(CUTOFF.date())
             and source_receipt.get("strict_apply_unchanged") is True, "QUALIFIED_SOURCE_RECEIPT_REQUIRED")
    _require(frame_sha(states) == source_receipt.get("state_census_sha256")
             and frame_sha(members) == source_receipt.get("members_sha256"), "QUALIFIED_SOURCE_CONTENT_CHANGED")
    fn, routing = _isolated_projector()
    pieces = []
    for date, qualified in book:
        if qualified.empty:
            continue
        ids = set(qualified.snapshot_id)
        result = fn(qualified, members.loc[members.snapshot_id.isin(ids)],
            dated_identity.loc[pd.to_datetime(dated_identity.signal_date).eq(date)], [date],
            task_id=TASK, selection_rule=RULE)
        for row in ledgers:
            if row["signal_date"] == date:
                row.update(selected_quarter=result["schedule"].iloc[0].quarter,
                           selected_snapshot_id=result["schedule"].iloc[0].source_snapshot_id)
                break
        pieces.append(result)
    _require(pieces, "NO_QUALIFIED_HISTORICAL_PROJECTION")
    combined = {name:pd.concat([r[name] for r in pieces], ignore_index=True)
                for name in ("schedule", "members", "ledger", "dated_identity")}
    combined["source_daily_ledger"] = pd.DataFrame(ledgers)
    combined["projector_routing"] = routing
    return combined
