"""Restore SEC data from retained ZIPs without executing any research runner.

Historical financial features reuse the unchanged research parser. Current
disclosures are generic SEC records, with no feature selection or model fit.
Ticker/CIK identity is supplied by an existing mapping, never inferred here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def load_parser(path: Path):
    spec = importlib.util.spec_from_file_location("sec_data_recovery_source", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot import parser: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_ciks(path: Path) -> list[int]:
    if path.suffix.lower() == ".parquet":
        columns = pq.read_schema(path).names
        filters = [("record_type", "==", "CIK_MAPPING")] if "record_type" in columns else None
        frame = pd.read_parquet(path, columns=["cik"], filters=filters)
    else:
        frame = pd.read_csv(path, usecols=["cik"], dtype="string")
    values = pd.to_numeric(frame.cik, errors="coerce").dropna()
    if ((values <= 0) | (values % 1 != 0)).any():
        raise ValueError("CIKs must be positive integer SEC identifiers")
    ciks = sorted(set(values.astype(int)))
    if not ciks:
        raise ValueError("No mapped CIKs in mapping source")
    return ciks


def lineage(path: Path, member: str, payload: bytes, archive_sha256: str) -> dict:
    return {"source_archive": str(path.resolve()), "source_archive_sha256": archive_sha256,
            "source_member": member, "source_member_sha256": hashlib.sha256(payload).hexdigest()}


def disclosure_rows(document: dict, cik: int, start: str, as_of: str, source: dict) -> list[dict]:
    recent = document.get("filings", {}).get("recent", {}) if "filings" in document else document
    arrays = {key: value for key, value in recent.items() if isinstance(value, list)}
    begin = pd.Timestamp(start, tz="America/New_York").tz_convert("UTC")
    end = (pd.Timestamp(as_of) + pd.Timedelta(days=1)).tz_localize("America/New_York").tz_convert("UTC")
    accepted_times = pd.to_datetime(arrays.get("acceptanceDateTime", []), utc=True, errors="coerce", format="mixed")
    rows = []
    for i, accession in enumerate(arrays.get("accessionNumber", [])):
        at = lambda name: arrays.get(name, [])[i] if i < len(arrays.get(name, [])) else None
        filed = str(at("filingDate") or "")
        accepted = accepted_times[i] if i < len(accepted_times) else pd.NaT
        # Unknown acceptance remains visible as a quality gap, never as a PIT fact.
        if pd.isna(accepted):
            if not start <= filed <= as_of:
                continue
        elif not begin <= accepted < end:
            continue
        rows.append({"cik": cik, "accession": str(accession), "form": at("form"),
                     "filed_date": filed, "report_date": at("reportDate"),
                     "accepted_at": accepted, "primary_document": at("primaryDocument"),
                     "acceptance_status": "MISSING_ACCEPTANCE" if pd.isna(accepted) else "KNOWN",
                     **source})
    return rows


def fact_rows(document: dict, cik: int, start: str, as_of: str, source: dict) -> list[dict]:
    rows = []
    for taxonomy, concepts in document.get("facts", {}).items():
        for concept, block in concepts.items():
            for unit, observations in block.get("units", {}).items():
                for observation in observations:
                    filed = str(observation.get("filed") or "")
                    if not start <= filed <= as_of:
                        continue
                    rows.append({"cik": cik, "taxonomy": taxonomy, "concept": concept,
                                 "unit": unit, "accession": observation.get("accn"),
                                 "start_date": observation.get("start"), "end_date": observation.get("end"),
                                 "raw_value": observation.get("val"), "form": observation.get("form"),
                                 "filed_date": filed, "fiscal_year": observation.get("fy"),
                                 "fiscal_period": observation.get("fp"), "frame": observation.get("frame"),
                                 **source})
    return rows


def parse_current(companyfacts: Path, submissions: Path, ciks: list[int], start: str,
                  as_of: str, identities: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fact_records, disclosure_records, audit = [], [], []
    for role, path in (("submissions", submissions), ("companyfacts", companyfacts)):
        with zipfile.ZipFile(path) as archive:
            for number, cik in enumerate(ciks, 1):
                member = f"CIK{cik:010d}.json"
                if member not in archive.NameToInfo:
                    audit.append({"role": role, "cik": cik, "member": member, "status": "MISSING_ENTRY"})
                    continue
                payload = archive.read(member)
                document = json.loads(payload)
                source = lineage(path, member, payload, identities[role]["sha256"])
                if role == "companyfacts":
                    fact_records.extend(fact_rows(document, cik, start, as_of, source))
                else:
                    disclosure_records.extend(disclosure_rows(document, cik, start, as_of, source))
                    for history in document.get("filings", {}).get("files", []):
                        if str(history.get("filingTo") or "") < start or str(history.get("filingFrom") or "") > as_of:
                            continue
                        old_member = str(history.get("name") or "")
                        if old_member not in archive.NameToInfo:
                            audit.append({"role": role, "cik": cik, "member": old_member, "status": "MISSING_HISTORY_ENTRY"})
                            continue
                        old_payload = archive.read(old_member)
                        old_source = lineage(path, old_member, old_payload, identities[role]["sha256"])
                        disclosure_records.extend(disclosure_rows(json.loads(old_payload), cik, start, as_of, old_source))
                audit.append({"role": role, "cik": cik, "member": member, "status": "READ"})
                if number % 250 == 0:
                    print(f"SEC_CURRENT_{role.upper()}={number}/{len(ciks)}", flush=True)
    disclosures = pd.DataFrame(disclosure_records)
    if not disclosures.empty:
        conflicts = disclosures.groupby(["cik", "accession"]).accepted_at.nunique().gt(1)
        if conflicts.any():
            raise ValueError("Conflicting acceptance timestamps for SEC accession")
        disclosures = disclosures.sort_values(["cik", "accession", "source_member"]).drop_duplicates(["cik", "accession"])
    facts = pd.DataFrame(fact_records)
    if not facts.empty:
        if disclosures.empty:
            facts["accepted_at"] = pd.NaT
        else:
            facts = facts.merge(disclosures[["cik", "accession", "accepted_at"]],
                                on=["cik", "accession"], how="left", validate="many_to_one")
        facts["acceptance_status"] = facts.accepted_at.notna().map({True: "KNOWN", False: "MISSING_ACCEPTANCE"})
    return facts, disclosures, pd.DataFrame(audit)


def write_frame(path: Path, frame: pd.DataFrame) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    if path.exists() and sha256_file(path) != sha256_file(temporary):
        raise FileExistsError(f"Preserving a different existing output: {path}")
    os.replace(temporary, path)
    return {**file_identity(path), "rows": len(frame), "columns": list(frame.columns)}


def historical_frames(parser, companyfacts: Path, submissions: Path, ciks: list[int], sessions_file: Path | None,
                      states_file: Path | None = None, states_manifest: Path | None = None):
    verified_states = None
    if states_file:
        if not states_manifest:
            raise ValueError("--states-file requires --expected-states-manifest")
        expected = json.loads(states_manifest.read_text(encoding="utf-8"))
        states_source = file_identity(states_file)
        if not expected.get("state_sha256") or states_source["sha256"] != expected["state_sha256"]:
            raise ValueError("Existing states SHA256 does not match expected frozen states manifest")
        verified_states = pd.read_parquet(states_file)
        if "state_rows" in expected and len(verified_states) != expected["state_rows"]:
            raise ValueError("Existing states row count does not match expected frozen states manifest")
    sub, sub_audit, sub_index = parser.read_relevant_bulk_submissions(submissions, ciks)
    facts, fact_audit, fact_index = parser.read_relevant_bulk_companyfacts(companyfacts, ciks)
    if verified_states is not None:
        states = verified_states
        state_lineage = expected.get("lineage_facts", {})
        calendar_source = {"status": "PRESERVED_IN_HASH_VERIFIED_STATES",
                           "source_manifest": file_identity(states_manifest)}
    elif sessions_file:
        calendar = pd.read_csv(sessions_file, usecols=["trade_date"])
        sessions = pd.DatetimeIndex(pd.to_datetime(calendar.trade_date)).sort_values().unique()
        if sessions.max() > pd.Timestamp("2025-12-31"):
            raise ValueError("Historical recovery session calendar exceeds 2025 cutoff")
        calendar_source = file_identity(sessions_file)
    else:
        import pandas_market_calendars as mcal
        sessions = mcal.get_calendar("NYSE").valid_days("2018-01-01", "2025-12-31").tz_localize(None)
        calendar_source = {"provider": "pandas_market_calendars", "calendar": "NYSE",
                           "version": mcal.__version__, "status": "CALENDAR_RECONSTRUCTION_NOT_FROZEN_QQQ_DATES"}
    if verified_states is None:
        states, state_lineage = parser.build_feature_states(facts, sub, sessions)
    frames = {"relevant_companyfacts": facts, "relevant_submissions": sub,
              "bulk_read_audit": pd.concat([sub_audit, fact_audit], ignore_index=True, sort=False),
              "relevant_zip_index": pd.concat([sub_index, fact_index], ignore_index=True, sort=False),
              "fundamental_feature_states": states}
    metadata = {"state_lineage": state_lineage, "calendar": calendar_source}
    if verified_states is not None:
        metadata.update({"states_restoration": "HASH_VERIFIED_EXISTING_STATES", "states_source": states_source})
    return frames, metadata


def expected_hashes(parse_manifest: Path | None, states_manifest: Path | None) -> dict:
    expected = {}
    if parse_manifest:
        data = json.loads(parse_manifest.read_text(encoding="utf-8"))
        expected.update({Path(value["path"]).name: value["sha256"] for value in data["files"].values()})
    if states_manifest:
        data = json.loads(states_manifest.read_text(encoding="utf-8"))
        expected[Path(data["state_path"]).name] = data["state_sha256"]
    return expected


def run(args: argparse.Namespace) -> dict:
    for label in ("as_of", "current_start"):
        if pd.Timestamp(getattr(args, label)).strftime("%Y-%m-%d") != getattr(args, label):
            raise ValueError(f"{label} must use YYYY-MM-DD")
    if args.current_start < "2026-01-01" or args.current_start > args.as_of:
        raise ValueError("Current disclosure range must start in 2026 or later and end at as-of")
    output = args.output_root.resolve()
    if args.states_file and args.skip_historical:
        raise ValueError("--states-file cannot be combined with --skip-historical")
    if args.states_file and not args.expected_states_manifest:
        raise ValueError("--states-file requires --expected-states-manifest")
    source_paths = [args.companyfacts_zip, args.submissions_zip, args.mapping_file, args.parser_source]
    if args.states_file:
        source_paths.append(args.states_file)
    if any(path.resolve().is_relative_to(output) for path in source_paths):
        raise ValueError("Output root must not contain source inputs")
    ciks = read_ciks(args.mapping_file)
    identities = {"companyfacts": file_identity(args.companyfacts_zip),
                  "submissions": file_identity(args.submissions_zip),
                  "mapping": file_identity(args.mapping_file), "parser": file_identity(args.parser_source)}
    contract = {"sources": identities, "ciks": ciks, "as_of": args.as_of,
                "current_start": args.current_start, "skip_historical": args.skip_historical,
                "sessions": file_identity(args.sessions_file) if args.sessions_file else None,
                "manager_registry": file_identity(args.manager_registry) if args.manager_registry else None,
                "expected_parse_manifest": file_identity(args.expected_parse_manifest) if args.expected_parse_manifest else None,
                "expected_states_manifest": file_identity(args.expected_states_manifest) if args.expected_states_manifest else None}
    if args.states_file:
        contract["states_file"] = file_identity(args.states_file)
    cache_key = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    manifest_path = output / "sec_restore_manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["cache_key"] != cache_key:
            raise FileExistsError("Different restoration contract already occupies output root")
        if all(Path(item["path"]).is_file() and sha256_file(Path(item["path"])) == item["sha256"] for item in previous["files"].values()):
            return previous
    files, history_metadata = {}, {}
    if not args.skip_historical:
        parser = load_parser(args.parser_source)
        frames, history_metadata = historical_frames(parser, args.companyfacts_zip, args.submissions_zip, ciks,
                                                     args.sessions_file, args.states_file, args.expected_states_manifest)
        expected = expected_hashes(args.expected_parse_manifest, args.expected_states_manifest)
        for name, frame in frames.items():
            item = write_frame(output / "historical" / f"{name}.parquet", frame)
            item["frozen_expected_sha256"] = expected.get(f"{name}.parquet")
            item["frozen_hash_match"] = item["sha256"] == item["frozen_expected_sha256"] if item["frozen_expected_sha256"] else None
            files[f"historical/{name}"] = item
    current_ciks = sorted(set(ciks + (read_ciks(args.manager_registry) if args.manager_registry else [])))
    facts, disclosures, audit = parse_current(args.companyfacts_zip, args.submissions_zip,
                                               current_ciks, args.current_start, args.as_of, identities)
    for name, frame in (("companyfacts", facts), ("submissions", disclosures), ("read_audit", audit)):
        files[f"current/{name}"] = write_frame(output / "current" / f"{name}.parquet", frame)
    manifest = {"schema_version": 1, "status": "RESTORED_WITH_EXPLICIT_COVERAGE",
                "cache_key": cache_key, "created_at": datetime.now(timezone.utc).isoformat(),
                "contract": contract, "resolved_cik_count": len(ciks), "current_cik_count": len(current_ciks),
                "historical": history_metadata, "files": files,
                "current_filed_max": None if facts.empty else str(facts.filed_date.max()),
                "current_accepted_max": None if disclosures.empty else str(disclosures.accepted_at.max()),
                "missing_entries": 0 if audit.empty else int(audit.status.ne("READ").sum()),
                "facts_missing_acceptance": 0 if facts.empty else int(facts.acceptance_status.ne("KNOWN").sum()),
                "limitations": ["Source snapshot availability does not imply completeness through requested as-of.",
                                "Current raw facts include all source taxonomies and units; consumers must filter explicitly.",
                                "No ticker mapping inference, research execution, fitting, or frozen-file replacement.",
                                "Historical outputs are restored candidates; only exact hash matches are byte-identical."]}
    output.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parser-source", type=Path, required=True)
    parser.add_argument("--companyfacts-zip", type=Path, required=True)
    parser.add_argument("--submissions-zip", type=Path, required=True)
    parser.add_argument("--mapping-file", type=Path, required=True, help="CSV CIK registry or Parquet identity mapping; mixed ledger filters CIK_MAPPING before column read")
    parser.add_argument("--manager-registry", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--as-of", default="2026-09-04")
    parser.add_argument("--current-start", default="2026-01-01")
    parser.add_argument("--sessions-file", type=Path, help="Optional frozen historical trade_date CSV for exact feature-state restoration")
    parser.add_argument("--expected-parse-manifest", type=Path)
    parser.add_argument("--expected-states-manifest", type=Path)
    parser.add_argument("--states-file", type=Path, help="Reuse existing states only if their SHA256 matches --expected-states-manifest")
    parser.add_argument("--skip-historical", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps({key: result[key] for key in ("status", "resolved_cik_count", "current_cik_count", "current_filed_max", "missing_entries")}, indent=2))
