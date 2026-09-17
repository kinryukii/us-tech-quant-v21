"""Stage one SEC 13F quarter and a new combined universe without changing history.

Reuses the package's XML parser and accepted v17b equity selection functions.
The incomplete-quarter path writes metadata and explicit gaps only.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd
import numpy as np
import requests

if __package__:
    from .restore_sec_data import file_identity, sha256_file, write_frame
else:
    from restore_sec_data import file_identity, sha256_file, write_frame


PERSHING_NOTICE = "https://www.sec.gov/Archives/edgar/data/1336528/000117266126003777/0001172661-26-003777.txt"
PERSHING_ALIAS = {"manager_id": "pershing_square", "old_cik": 1336528, "cik": 2026053,
                  "valid_from_quarter": "2026Q2", "source_url": PERSHING_NOTICE,
                  "source_accession": "0001172661-26-003777", "evidence_form": "13F-NT",
                  "reason": "Notice identifies public parent as the reporting manager for these holdings."}
SEC_UNIT_RULE = "https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f"


def import_source(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot import source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def configured_user_agent(source: Path) -> str:
    if os.environ.get("SEC_USER_AGENT"):
        return os.environ["SEC_USER_AGENT"]
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "DEFAULT_USER_AGENT" for target in node.targets):
            return str(ast.literal_eval(node.value))
    raise ValueError("No existing configured SEC User-Agent available")


def active_managers(registry: pd.DataFrame, quarter: str) -> pd.DataFrame:
    truth = lambda value: str(value).strip().lower() in {"true", "1", "yes"}
    mask = registry.enabled.map(truth) & registry.active_from_quarter.le(quarter)
    mask &= registry.active_to_quarter.eq("") | registry.active_to_quarter.ge(quarter)
    active = registry.loc[mask].copy()
    if active.manager_id.duplicated().any():
        raise ValueError("Duplicate active manager registry identity")
    for column in ("top_n", "protected_top_n", "manager_weight"):
        active[column] = pd.to_numeric(active[column], errors="raise")
    if not (active.top_n.eq(100) & active.protected_top_n.eq(20)).all():
        raise ValueError("v17b selection supports this existing cohort's Top100/protected Top20 contract only")
    active["required_for_gate"] = active.required_for_gate.map(truth)
    return active


def filing_plan(submissions_zip: Path, managers: pd.DataFrame, quarter: str, as_of: str) -> pd.DataFrame:
    report_date = str(pd.Period(quarter, freq="Q").end_time.date())
    cutoff = (pd.Timestamp(as_of) + pd.Timedelta(days=1)).tz_localize("America/New_York").tz_convert("UTC")
    rows = []
    with zipfile.ZipFile(submissions_zip) as archive:
        for manager in managers.to_dict("records"):
            cik = int(manager["cik"])
            alias = manager["manager_id"] == "pershing_square" and quarter >= "2026Q2"
            if alias:
                cik = PERSHING_ALIAS["cik"]
            member = f"CIK{cik:010d}.json"
            base = {"quarter": quarter, "manager_id": manager["manager_id"],
                    "manager_name": manager["manager_name"], "manager_weight": float(manager["manager_weight"]),
                    "cik": cik, "required_for_gate": bool(manager["required_for_gate"]),
                    "report_date": report_date, "submission_member": member,
                    "identity_evidence_url": PERSHING_NOTICE if alias else "EXISTING_MANAGER_REGISTRY"}
            if member not in archive.NameToInfo:
                rows.append({**base, "status": "MISSING_SUBMISSION_MEMBER"})
                continue
            payload = archive.read(member)
            import hashlib
            base["submission_member_sha256"] = hashlib.sha256(payload).hexdigest()
            document = json.loads(payload)
            records = [document.get("filings", {}).get("recent", {})]
            for descriptor in document.get("filings", {}).get("files", []):
                # Reports for this quarter cannot be filed before its period end.
                if str(descriptor.get("filingTo") or "") >= report_date:
                    member_name = str(descriptor.get("name") or "")
                    if member_name in archive.NameToInfo:
                        records.append(json.loads(archive.read(member_name)))
            candidates = []
            for arrays in records:
                for i, form in enumerate(arrays.get("form", [])):
                    at = lambda name: arrays.get(name, [])[i] if i < len(arrays.get(name, [])) else None
                    accepted = pd.to_datetime(at("acceptanceDateTime"), utc=True, errors="coerce")
                    if form == "13F-HR" and at("reportDate") == report_date and pd.notna(accepted) and accepted < cutoff:
                        accession = str(at("accessionNumber"))
                        candidates.append({"accession": accession, "filed_date": str(at("filingDate")),
                                           "accepted_at": accepted, "form": form,
                                           "source_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}.txt"})
            if candidates:
                first = sorted(candidates, key=lambda row: (row["accepted_at"], row["accession"]))[0]
                rows.append({**base, **first, "status": "INITIAL_FILING_IDENTIFIED"})
            else:
                rows.append({**base, "status": "MISSING_INITIAL_FILING"})
    return pd.DataFrame(rows)


def parse_sec_txt(payload: bytes, filing: dict, parser) -> list[dict]:
    text = payload.decode("utf-8")
    if not text.startswith("<SEC-DOCUMENT>"):
        raise ValueError("Downloaded payload is not an SEC document")
    header_accession = re.search(r"ACCESSION NUMBER:\s*([\d-]+)", text)
    if not header_accession or header_accession.group(1) != filing["accession"]:
        raise ValueError("SEC document accession mismatch")
    header_accepted = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", text)
    if not header_accepted:
        raise ValueError("Missing SEC acceptance header")
    accepted = pd.Timestamp(pd.to_datetime(header_accepted.group(1), format="%Y%m%d%H%M%S")).tz_localize("America/New_York").tz_convert("UTC")
    if accepted != pd.Timestamp(filing["accepted_at"]):
        raise ValueError("SEC acceptance header disagrees with submissions metadata")
    holdings, declared_total = [], None
    for xml in re.findall(r"<XML>\s*(.*?)\s*</XML>", text, flags=re.S):
        root = ET.fromstring(xml.strip())
        if any(parser.localname(node.tag) == "infotable" for node in root.iter()):
            holdings.extend(parser.parse_holdings(root, filing["filed_date"]))
        total = parser.text_at(root, "tableEntryTotal")
        if total:
            declared_total = int(total)
    if not holdings or (declared_total is not None and declared_total != len(holdings)):
        raise ValueError(f"13F holdings count mismatch: declared={declared_total}, parsed={len(holdings)}")
    return holdings


def download(url: str, path: Path, user_agent: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            time.sleep(0.25)
            response = requests.get(url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=60)
            response.raise_for_status()
            if not response.content.startswith(b"<SEC-DOCUMENT>"):
                raise ValueError("SEC response did not contain a complete filing")
            temporary = path.with_suffix(".txt.tmp")
            temporary.write_bytes(response.content)
            os.replace(temporary, path)
            return
        except Exception as exc:
            if "10013" in str(exc) or "Permission" in str(exc):
                raise PermissionError("SEC_NETWORK_PERMISSION_DENIED") from exc
            if attempt:
                raise
            time.sleep(1)


def build_quarter(raw: pd.DataFrame, filings: pd.DataFrame, source, xml_parser) -> tuple[pd.DataFrame, pd.DataFrame]:
    classified = raw.apply(lambda row: source.classify_equity(row.issuer_name, row.title_of_class,
                                                             row.ssh_prnamt_type, row.put_call), axis=1)
    raw = raw.copy()
    raw["eligible"] = classified.map(lambda value: value[0])
    selected = source.select_top100(source.aggregate_eligible_for_ranking(raw))
    quarter = str(filings.quarter.iloc[0])
    effective = xml_parser.add_five_nyse_sessions(str(filings.loc[filings.required_for_gate, "filed_date"].max()))
    timing = pd.DataFrame([{"quarter": quarter, "report_date": filings.report_date.iloc[0],
                            "effective_date": effective, "expiry_date": ""}])
    if selected.loc[selected.protected_core, "cusip"].nunique() > source.HARD_CAP:
        raise ValueError("Protected core exceeds universe cap")
    return selected, source.build_universe(selected, timing)


def merge_history(history: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    if set(history.quarter) & set(current.quarter):
        raise ValueError("Quarter already exists in historical source; use a reviewed revision workflow")
    merged = pd.concat([history, current], ignore_index=True)
    for column in ("report_date", "effective_date", "expiry_date"):
        merged[column] = pd.to_datetime(merged[column], errors="coerce")
    quarters = merged[["quarter", "effective_date"]].drop_duplicates().sort_values("effective_date")
    if quarters.quarter.duplicated().any() or quarters.effective_date.isna().any():
        raise ValueError("Inconsistent quarter activation dates")
    expiry = dict(zip(quarters.quarter.iloc[:-1], quarters.effective_date.iloc[1:] - pd.Timedelta(days=1)))
    for quarter, end in expiry.items():
        merged.loc[merged.quarter.eq(quarter), "expiry_date"] = end
    if merged.duplicated(["quarter", "cusip"]).any():
        raise ValueError("Duplicate quarter/CUSIP universe rows")
    return merged.sort_values(["quarter", "universe_rank"]).reset_index(drop=True)


def verify_historical_values(selected: pd.DataFrame, raw_totals: pd.DataFrame, filing_dates: pd.DataFrame):
    keys = ["quarter", "manager_id", "accession_key", "cusip"]
    result = selected.merge(raw_totals, on=keys, how="left", validate="one_to_one")
    result = result.merge(filing_dates, on=["quarter", "manager_id", "accession_key"], how="left", validate="many_to_one")
    result["legacy_reported_value_usd"] = result.reported_value_usd
    dates = pd.to_datetime(result.filing_date, errors="coerce")
    result["source_to_usd_factor"] = np.where(dates.ge("2023-01-03"), 1.0, 1000.0)
    verified = dates.notna() & result.source_reported_value.notna() & np.isclose(
        result.legacy_reported_value_usd, result.source_reported_value * 1000.0, rtol=0, atol=0.5)
    result["legacy_to_usd_factor"] = result.source_to_usd_factor / 1000.0
    result["unit_status"] = np.where(verified, "VERIFIED_SOURCE_VALUE_AND_FILING_DATE", "UNVERIFIED")
    result["reported_value_usd"] = (result.source_reported_value * result.source_to_usd_factor).where(verified)
    result["unit_rule_url"] = SEC_UNIT_RULE
    result["unit_source_ref"] = "SEC_REDUCED_INFOTABLE_ACCESSION:" + result.accession_key.astype(str)
    return result


def normalize_historical_units(package: Path, cache: Path, historical: pd.DataFrame, selection):
    selected_path = package / "data/holdings/selected_top100_master_v17b_clean.parquet"
    filing_path = package / "data/filings/filing_metadata.csv"
    filing_map = selection.load_authoritative_filing_map(package)
    source = selection.load_and_classify_source(package, cache, filing_map)
    keys = ["quarter", "manager_id", "accession_key", "cusip"]
    raw_totals = source.loc[source.eligible].groupby(keys, as_index=False).agg(source_reported_value=("reported_value_raw", "sum"))
    filings = pd.read_csv(filing_path, dtype=str, keep_default_na=False)
    filings = filings.loc[filings.status.eq("VERIFIED")].copy()
    filings["accession_key"] = filings.accession_number.map(selection.norm_accession)
    dates = filings[["quarter", "manager_id", "accession_key", "filing_date"]].drop_duplicates()
    repaired = verify_historical_values(pd.read_parquet(selected_path), raw_totals, dates)
    totals = repaired.groupby(["quarter", "cusip"], as_index=False).agg(
        verified_value_usd=("reported_value_usd", lambda values: values.sum(min_count=len(values))),
        rebuilt_legacy_value=("legacy_reported_value_usd", "sum"))
    result = historical.merge(totals, on=["quarter", "cusip"], how="left", validate="one_to_one")
    result["legacy_aggregate_value_usd"] = result.aggregate_value_usd
    verified = result.verified_value_usd.notna() & np.isclose(result.aggregate_value_usd, result.rebuilt_legacy_value, rtol=0, atol=0.5)
    result["aggregate_value_usd"] = result.verified_value_usd.where(verified)
    result["unit_status"] = np.where(verified, "VERIFIED_SOURCE_VALUE_AND_FILING_DATE", "UNVERIFIED")
    result["legacy_to_usd_factor"] = result.aggregate_value_usd / result.legacy_aggregate_value_usd
    result["unit_rule_url"] = SEC_UNIT_RULE
    result = result.drop(columns=["verified_value_usd", "rebuilt_legacy_value"])
    sources = {"selected_holdings": file_identity(selected_path), "filing_dates": file_identity(filing_path),
               "reduced_infotables": [file_identity(path) for path in sorted((cache / "sec_bulk_reduced").glob("*_infotable.parquet"))]}
    metadata = {"rule_url": SEC_UNIT_RULE, "rule_questions": [36, 62], "cutover_filing_date": "2023-01-03",
                "prior_value_multiplier_bug": "v17b multiplied every source VALUE by 1000 regardless of filing date",
                "sources": sources, "selected_rows": len(repaired),
                "selected_unverified_rows": int(repaired.unit_status.eq("UNVERIFIED").sum()),
                "universe_unverified_rows": int(result.unit_status.eq("UNVERIFIED").sum()),
                "repaired_selected_rows": int(repaired.legacy_to_usd_factor.eq(0.001).sum())}
    return result, repaired, metadata


def replace_owned_frame(path: Path, frame: pd.DataFrame, prior: dict) -> dict:
    """Only revise this run's own hash-recorded staging output, never an input."""
    if path.exists():
        owned = next((item for item in prior.get("files", {}).values() if Path(item["path"]).resolve() == path.resolve()), None)
        if owned is None or sha256_file(path) != owned["sha256"]:
            raise ValueError("Existing staging output is not owned and hash-valid for this run")
    temporary = path.with_suffix(".parquet.tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)
    return {**file_identity(path), "rows": len(frame), "columns": list(frame.columns)}


def run(args):
    package, output = args.package_root.resolve(), args.output_root.resolve()
    if output.is_relative_to(package) or package.is_relative_to(output):
        raise ValueError("Staging must be separate from the protected historical package")
    if not re.fullmatch(r"20\d{2}Q[1-4]", args.quarter):
        raise ValueError("Quarter must be YYYYQn")
    registry_path = package / "config" / "manager_registry.csv"
    managers = active_managers(pd.read_csv(registry_path, dtype=str, keep_default_na=False), args.quarter)
    plan = filing_plan(args.submissions_zip, managers, args.quarter, args.as_of)
    output.mkdir(parents=True, exist_ok=True)
    previous_path = output / "quarter_manifest.json"
    prior = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
    files = {"filings": write_frame(output / "filing_metadata.parquet", plan)}
    xml_source = package / "scripts" / "build_13f_history.py"
    selection_source = package / "scripts" / "v17b" / "integrity_rebuild_v17b.py"
    xml_parser = import_source(xml_source, "quarter_xml_parser")
    selection = import_source(selection_source, "quarter_v17b_selection")
    user_agent = configured_user_agent(args.user_agent_source) if args.fetch else ""
    raw, raw_manifest, gaps = [], [], []
    network_denied = False
    for filing in plan.to_dict("records"):
        if filing["status"] != "INITIAL_FILING_IDENTIFIED":
            gaps.append({"manager_id": filing["manager_id"], "reason": filing["status"]})
            continue
        path = output / "raw" / f"{filing['cik']}_{filing['accession']}.txt"
        if args.fetch and not network_denied:
            try:
                download(filing["source_url"], path, user_agent)
            except PermissionError:
                network_denied = True
            except Exception as exc:
                gaps.append({"manager_id": filing["manager_id"], "reason": f"FETCH_FAILED:{type(exc).__name__}"})
                continue
        if not path.exists():
            gaps.append({"manager_id": filing["manager_id"], "reason": "NETWORK_PERMISSION_DENIED" if network_denied else "RAW_FILING_NOT_STAGED"})
            continue
        try:
            rows = parse_sec_txt(path.read_bytes(), filing, xml_parser)
        except Exception as exc:
            gaps.append({"manager_id": filing["manager_id"], "reason": f"PARSE_FAILED:{type(exc).__name__}:{exc}"})
            continue
        raw_manifest.append({**file_identity(path), "url": filing["source_url"], "manager_id": filing["manager_id"], "rows": len(rows)})
        for row in rows:
            raw.append({**row, "quarter": args.quarter, "manager_id": filing["manager_id"],
                        "manager_name": filing["manager_name"], "manager_weight": filing["manager_weight"],
                        "accession_key": filing["accession"].replace("-", ""),
                        "reported_value_usd": row["value_usd"], "ssh_prnamt_type": row["share_type"],
                        "source_sha256": raw_manifest[-1]["sha256"], "source_url": filing["source_url"]})
    raw_frame = pd.DataFrame(raw)
    status = "INCOMPLETE_NO_UNIVERSE_ACTIVATION"
    unit_metadata = None
    if not gaps and len(raw_manifest) == len(managers):
        files["raw_holdings"] = write_frame(output / "raw_holdings.parquet", raw_frame)
        selected, universe = build_quarter(raw_frame, plan, selection, xml_parser)
        historical, repaired, unit_metadata = normalize_historical_units(package, args.cache_root, pd.read_parquet(args.historical_universe), selection)
        current = universe.copy()
        current["legacy_aggregate_value_usd"] = np.nan
        current["legacy_to_usd_factor"] = 1.0
        current["unit_status"] = "VERIFIED_SEC_XML_USD"
        current["unit_rule_url"] = SEC_UNIT_RULE
        merged = merge_history(historical, current)
        for name, frame in (("selected_top100", selected), ("quarter_universe", universe)):
            files[name] = write_frame(output / f"{name}.parquet", frame)
        for name, frame in (("historical_selected_top100_units", repaired), ("dynamic_universe", merged)):
            files[name] = replace_owned_frame(output / f"{name}.parquet", frame, prior)
        status = "QUARTER_AND_HISTORY_STAGED"
    manifest = {"schema_version": 1, "dataset_id": "13f_universe_external25", "status": status, "quarter": args.quarter, "as_of": args.as_of,
                "sources": {"registry": file_identity(registry_path), "submissions": file_identity(args.submissions_zip),
                            "historical_universe": file_identity(args.historical_universe),
                            "xml_parser": file_identity(xml_source), "selection": file_identity(selection_source)},
                "manager_count": len(managers), "identified_initial_filings": int(plan.status.eq("INITIAL_FILING_IDENTIFIED").sum()),
                "identity_alias": PERSHING_ALIAS if args.quarter >= "2026Q2" else None,
                "unit_normalization": unit_metadata,
                "previous_dynamic_universe_sha256": prior.get("files", {}).get("dynamic_universe", {}).get("sha256"),
                "raw_filings": raw_manifest, "files": files, "gaps": gaps,
                "limitations": ["The old package and its frozen records are unchanged.",
                                "This preserves the external package's 25-manager cohort; it does not replace the separate A2 frozen 24-manager universe.",
                                "CUSIP is canonical; no guessed ticker mapping is produced.",
                                "Only a complete quarter produces an activation and combined universe."]}
    temporary = output / "quarter_manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, output / "quarter_manifest.json")
    return manifest


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--submissions-zip", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, default=Path("D:/us-tech-quant-cache/13f_pit_v1"))
    parser.add_argument("--historical-universe", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--quarter", default="2026Q2")
    parser.add_argument("--as-of", default="2026-09-04")
    parser.add_argument("--user-agent-source", type=Path, default=Path("D:/us-tech-quant/scripts/v22/stage_sec_pit_taxonomy.py"))
    parser.add_argument("--fetch", action="store_true", help="Download missing SEC full filing TXT with existing configured SEC user agent")
    return parser.parse_args(argv)


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps({key: result[key] for key in ("status", "manager_count", "identified_initial_filings", "gaps")}, indent=2))
