"""Refresh a separate current external25 pool using the existing 13F registry.

Only this request's directory is written. Frozen A2 registries, historical
membership, catalog pointers, and the model remain unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from scripts.daily_recommendation_inputs import required_reporting_quarter
from scripts.storage.refresh_13f_quarter import (
    PERSHING_ALIAS, active_managers, build_quarter, configured_user_agent,
    import_source, manager_roster_identity, parse_sec_txt,
)


def _hash(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _verified(reference: dict) -> Path:
    path = Path(reference["path"])
    if not path.is_file() or _hash(path) != reference.get("sha256"):
        raise ValueError(f"13F_SOURCE_HASH_MISMATCH:{path.name}")
    return path


def _save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


class _SecReader:
    """Bounded official-source requests with the established SEC user agent."""
    def __init__(self, root: Path, user_agent: str):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.receipts = []

    def get(self, url: str) -> bytes:
        if not re.fullmatch(r"https://(?:data|www)\.sec\.gov/[A-Za-z0-9/_.-]+", url):
            raise ValueError("13F_UNEXPECTED_SOURCE_URL")
        if len(self.receipts) >= 120:
            raise ValueError("13F_BOUNDED_REQUEST_LIMIT")
        # Same conservative source rate used by the previous personal-contact capture.
        time.sleep(0.4)
        response = self.session.get(url, timeout=(15, 45), allow_redirects=False)
        receipt = {"url": url, "status": response.status_code,
                   "observed_at": datetime.now(timezone.utc).isoformat(),
                   "sha256": hashlib.sha256(response.content).hexdigest()}
        self.receipts.append(receipt)
        _save(self.root / "request_receipts.json", {"sources": self.receipts})
        if response.status_code != 200:
            raise ValueError(f"13F_SEC_HTTP_{response.status_code}")
        raw = self.root / (receipt["sha256"] + ".raw")
        if not raw.exists():
            raw.write_bytes(response.content)
        receipt["raw_path"] = str(raw)
        _save(self.root / "request_receipts.json", {"sources": self.receipts})
        return response.content


def _submission_records(manager: dict, document: dict, reader: _SecReader, minimum_period: str, as_of: pd.Timestamp) -> list[dict]:
    cik = int(manager["cik"])
    if int(document.get("cik", -1)) != cik:
        raise ValueError("13F_SUBMISSIONS_CIK_MISMATCH")
    arrays_list = [document.get("filings", {}).get("recent", {})]
    for descriptor in document.get("filings", {}).get("files", []):
        if str(descriptor.get("filingTo", "")) < minimum_period:
            continue
        name = descriptor.get("name", "")
        if not re.fullmatch(r"CIK\d{10}-submissions-\d+\.json", name):
            raise ValueError("13F_UNEXPECTED_HISTORY_MEMBER")
        arrays_list.append(json.loads(reader.get(f"https://data.sec.gov/submissions/{name}")))
    found = {}
    for arrays in arrays_list:
        count = len(arrays.get("accessionNumber", []))
        if any(len(arrays.get(name, [])) != count for name in ("form", "reportDate", "filingDate", "acceptanceDateTime")):
            raise ValueError("13F_SUBMISSIONS_ARRAY_LENGTH_MISMATCH")
        for index in range(count):
            form, period = arrays["form"][index], arrays["reportDate"][index]
            if form not in {"13F-HR", "13F-HR/A"} or period < minimum_period:
                continue
            accepted = pd.Timestamp(arrays["acceptanceDateTime"][index])
            if accepted.tzinfo is None:
                raise ValueError("13F_ACCEPTANCE_TIMEZONE_MISSING")
            if accepted > as_of:
                continue
            accession = arrays["accessionNumber"][index]
            if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
                raise ValueError("13F_INVALID_ACCESSION")
            row = {"manager_id": manager["manager_id"], "manager_name": manager["manager_name"],
                   "manager_weight": float(manager["manager_weight"]), "cik": cik,
                   "required_for_gate": bool(manager["required_for_gate"]),
                   "quarter": str(pd.Period(period, freq="Q")), "report_date": period,
                   "form": form, "accession": accession, "filed_date": arrays["filingDate"][index],
                   "accepted_at": accepted.isoformat(),
                   "source_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}.txt"}
            if accession in found and found[accession] != row:
                raise ValueError("13F_CONFLICTING_ACCESSION_METADATA")
            found[accession] = row
    return list(found.values())


def _xml_field(root: ET.Element, name: str, required: bool = True) -> str:
    values = [(node.text or "").strip() for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() == name.lower()]
    if len(values) != 1 or (required and not values[0]):
        if not required and not values:
            return ""
        raise ValueError(f"13F_AMBIGUOUS_XML_FIELD:{name}")
    return values[0]


def _inspect_filing(payload: bytes, filing: dict, parser) -> tuple[list[dict], dict]:
    text = payload.decode("utf-8")
    if not text.rstrip().endswith("</SEC-DOCUMENT>"):
        raise ValueError("13F_INCOMPLETE_RAW_FILING")
    header = text.split("</SEC-HEADER>", 1)[0]
    expected = [(r"CONFORMED SUBMISSION TYPE:\s*([^\r\n]+)", filing["form"]),
                (r"CONFORMED PERIOD OF REPORT:\s*(\d{8})", filing["report_date"].replace("-", ""))]
    for pattern, value in expected:
        matched = re.findall(pattern, header)
        if len(matched) != 1 or matched[0].strip() != value:
            raise ValueError("13F_HEADER_METADATA_MISMATCH")
    cik = re.findall(r"CENTRAL INDEX KEY:\s*(\d+)", header)
    if len(cik) != 1 or int(cik[0]) != int(filing["cik"]):
        raise ValueError("13F_HEADER_CIK_MISMATCH")
    roots = [ET.fromstring(block.strip()) for block in re.findall(r"<XML>\s*(.*?)\s*</XML>", text, re.S)]
    covers = [root for root in roots if root.tag.rsplit("}", 1)[-1].lower() == "edgarsubmission"]
    if len(covers) != 1:
        raise ValueError("13F_COVER_MISSING")
    cover = covers[0]
    if _xml_field(cover, "submissionType") != filing["form"] or pd.Timestamp(_xml_field(cover, "periodOfReport")).date().isoformat() != filing["report_date"]:
        raise ValueError("13F_COVER_METADATA_MISMATCH")
    rows = parse_sec_txt(payload, filing, parser)
    info = [node for root in roots for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() == "infotable"]
    if len(rows) != len(info) or len(rows) != int(_xml_field(cover, "tableEntryTotal")):
        raise ValueError("13F_HOLDING_COUNT_MISMATCH")
    amendment = _xml_field(cover, "amendmentType", False).upper()
    is_amendment = _xml_field(cover, "isAmendment", False).lower() in {"true", "1"}
    if (filing["form"] == "13F-HR/A") != is_amendment:
        raise ValueError("13F_AMENDMENT_FLAG_MISMATCH")
    if is_amendment and amendment not in {"RESTATEMENT", "NEW HOLDINGS"}:
        raise ValueError("13F_UNKNOWN_AMENDMENT_SEMANTICS")
    total = sum((Decimal(_xml_field(node, "value")) for node in info), Decimal(0))
    difference = total - Decimal(_xml_field(cover, "tableValueTotal"))
    return rows, {"amendment_type": amendment, "confidential_omitted": _xml_field(cover, "isConfidentialOmitted", False),
                  "detail_minus_cover": str(difference), "source_value_total_reconciled": difference == 0}


def _apply_filings(records: list[tuple[dict, list[dict], dict]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    holdings, effective_filings = [], []
    grouped = {}
    for record in records:
        grouped.setdefault(record[0]["manager_id"], []).append(record)
    for items in grouped.values():
        current, initial_count = [], 0
        for filing, rows, details in sorted(items, key=lambda value: (value[0]["accepted_at"], value[0]["accession"])):
            if details.get("confidential_omitted", "").lower() in {"true", "1"}:
                raise ValueError("13F_CONFIDENTIAL_HOLDINGS_OMITTED")
            if filing["form"] == "13F-HR":
                initial_count += 1
                if initial_count != 1:
                    raise ValueError("13F_MULTIPLE_INITIAL_FILINGS")
                current = list(rows)
            elif initial_count != 1:
                raise ValueError("13F_AMENDMENT_WITHOUT_INITIAL")
            elif details["amendment_type"] == "RESTATEMENT":
                current = list(rows)
            elif details["amendment_type"] == "NEW HOLDINGS":
                old = {(row["cusip"], row["title_of_class"], row["put_call"]) for row in current}
                if any((row["cusip"], row["title_of_class"], row["put_call"]) in old for row in rows):
                    raise ValueError("13F_ADDITIONAL_HOLDING_IDENTITY_COLLISION")
                current.extend(rows)
            else:
                raise ValueError("13F_UNKNOWN_AMENDMENT_SEMANTICS")
        if initial_count != 1:
            raise ValueError("13F_INITIAL_FILING_MISSING")
        latest = items[-1][0] if len(items) == 1 else max((x[0] for x in items), key=lambda row: (row["accepted_at"], row["accession"]))
        effective_filings.append(latest)
        for row in current:
            holdings.append({**row, "quarter": latest["quarter"], "manager_id": latest["manager_id"],
                             "manager_name": latest["manager_name"], "manager_weight": latest["manager_weight"],
                             "accession_key": latest["accession"].replace("-", ""),
                             "reported_value_usd": row["value_usd"], "ssh_prnamt_type": row["share_type"]})
    return pd.DataFrame(holdings), pd.DataFrame(effective_filings)


def _map_universe(universe: pd.DataFrame, identity: pd.DataFrame, *, as_of=None) -> tuple[list[dict], list[dict]]:
    mappings = {str(cusip): frame for cusip, frame in identity.groupby("cusip")}
    accepted, missing = [], []
    truth = lambda value: str(value).strip().lower() in {"true", "1", "yes"}
    for row in universe.to_dict("records"):
        cusip = str(row["cusip"])
        if cusip in {"02079K404", "02079K602"}:
            missing.append({"cusip": cusip, "issuer_name": row.get("issuer_name"),
                            "reason": "NON_COMMON_STOCK_PREFERRED_DEPOSITARY_SHARES"})
            continue
        matches = mappings.get(cusip)
        reason = "NO_EXISTING_CUSIP_MAPPING"
        if matches is not None and len(matches) == 1:
            mapped = matches.iloc[0]
            ticker, code = str(mapped.get("ticker") or ""), str(mapped.get("moomoo_transport_code") or "")
            flags = " ".join(str(mapped.get(key, "")) for key in ("mapping_status", "transport_alias_status", "transport_interval_status")).upper()
            valid = (mapped.get("mapping_status") == "RESOLVED" and truth(mapped.get("transport_static_validated"))
                     and bool(re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", ticker))
                     and bool(re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._/-]*", code))
                     and not any(word in flags for word in ("REJECT", "INVALID", "UNRESOLVED", "QUARANTINE", "BLOCKED")))
            interval = {key: str(mapped[key]) for key in ("identity_valid_from", "identity_valid_to")
                        if key in mapped and pd.notna(mapped[key]) and str(mapped[key]).strip()}
            try:
                if any(datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") != value for value in interval.values()):
                    raise ValueError("INVALID_IDENTITY_INTERVAL")
                if interval.get("identity_valid_from", "") > interval.get("identity_valid_to", "9999-12-31"):
                    raise ValueError("REVERSED_IDENTITY_INTERVAL")
            except ValueError:
                missing.append({"cusip": cusip, "issuer_name": row.get("issuer_name"), "reason": "INVALID_IDENTITY_INTERVAL"})
                continue
            if interval and (as_of is None or (interval.get("identity_valid_from") and str(as_of) < interval["identity_valid_from"])
                             or (interval.get("identity_valid_to") and str(as_of) > interval["identity_valid_to"])):
                missing.append({"cusip": cusip, "issuer_name": row.get("issuer_name"), "reason": "IDENTITY_OUTSIDE_VERIFIED_INTERVAL"})
                continue
            if valid:
                accepted.append({"security_id": cusip, "ticker": ticker, "moomoo_symbol": code,
                                 "moomoo_transport_code": code, "mapping_source": str(mapped.get("mapping_source", "")), **interval})
                continue
            reason = "UNVERIFIED_OR_REJECTED_TRANSPORT_MAPPING"
        elif matches is not None:
            reason = "AMBIGUOUS_EXISTING_CUSIP_MAPPING"
        missing.append({"cusip": cusip, "issuer_name": row.get("issuer_name"), "reason": reason})
    collisions = {key: set() for key in ("ticker", "moomoo_symbol")}
    for key in collisions:
        counts = pd.Series([row[key] for row in accepted]).value_counts()
        collisions[key] = set(counts[counts > 1].index)
    safe = []
    for row in accepted:
        if any(row[key] in values for key, values in collisions.items()):
            missing.append({"cusip": row["security_id"], "ticker": row["ticker"], "reason": "SIMULTANEOUS_IDENTITY_COLLISION"})
        else:
            safe.append(row)
    return safe, missing


def _exact_us_composite(record: dict, valid_ticker) -> dict | None:
    """Accept only one exact-CUSIP US composite/share-class identity, never names."""
    response = record.get("response", {})
    candidates = []
    for row in response.get("data", []) if isinstance(response, dict) else []:
        if (row.get("exchCode") != "US" or row.get("marketSector") != "Equity"
                or "option" in str(row.get("securityType", "")).lower()
                or not valid_ticker(row.get("ticker"))):
            continue
        if not row.get("compositeFIGI") or not row.get("shareClassFIGI"):
            continue
        candidates.append(row)
    identities = {(row["ticker"], row["compositeFIGI"], row["shareClassFIGI"]) for row in candidates}
    return candidates[0] if len(identities) == 1 else None


_PRIMARY_IDENTITY = {
    # Explicit security identifiers and ordinary-share ticker declarations in
    # the issuer's SEC filing / listing exchange's corporate-action notice.
    "G87052109": {"ticker": "TEL", "url": "https://www.sec.gov/Archives/edgar/data/1385157/000110465924102061/tm2424199d2_8k.htm",
                   "required": ["existing ticker", "TEL", "ordinary shares", "G87052109"]},
    "G9572D103": {"ticker": "BULL", "url": "https://m.nasdaqtrader.com/TraderNews.aspx?id=ECA2025-188",
                   "required": ["Webull Corporation Ordinary Shares", "G9572D103", "Symbol: BULL"]},
}


_PRIMARY_IDENTITY.update({
    "N52A8C105": {"ticker": "INIO", "documents": [
        {"url": "https://www.sec.gov/Archives/edgar/data/2109150/000114036126032833/xslSCHEDULE_13G_X02/primary_doc.xml", "required": ["N52A8C105", "INNIO", "common"]},
        {"url": "https://www.sec.gov/Archives/edgar/data/2109150/000119312526319072/R1.htm", "required": ["INNIO", "INIO", "NASDAQ", "Common shares"]}]},
    "G4253H101": {"ticker": "JHX", "documents": [
        {"url": "https://www.sec.gov/Archives/edgar/data/1159152/000031506626001221/xslSCHEDULE_13G_X02/primary_doc.xml", "required": ["G4253H101", "James Hardie", "COMMON STOCK"]},
        {"url": "https://www.sec.gov/Archives/edgar/data/1159152/000115915226000045/jhx-20260331.htm", "required": ["James Hardie", "JHX", "ordinary shares", "New York Stock Exchange"]}]},
    "G2R11M108": {"ticker": "DPC", "documents": [
        {"url": "https://www.sec.gov/Archives/edgar/data/2107018/000119312526345016/xslSCHEDULE_13G_X02/primary_doc.xml", "required": ["G2R11M108", "DPC Holdings", "Ordinary Shares"]},
        {"url": "https://www.sec.gov/Archives/edgar/data/2107018/000110465926077412/xslF345X03/tm2618562-3_3seq1.xml", "required": ["DPC Holdings", "DPC", "Ordinary"]}]},
    "G2004J103": {"ticker": "CCL", "documents": [
        {"url": "https://www.sec.gov/Archives/edgar/data/876661/000087666126000397/ruleprovisionnotice.htm", "required": ["G2004J103", "Carnival Corporation Ltd", "CCL", "Common Shares"]}]},
    "G9600F104": {"ticker": "VGNT", "documents": [
        {"url": "https://www.sec.gov/Archives/edgar/data/1010911/000101091126000015/xslForm13F_X02/information_table.xml", "required": ["VERSIGENT", "G9600F104", "ORDINARY SHARES"]},
        {"url": "https://www.sec.gov/Archives/edgar/data/2078008/000207800826000014/vgnt-20260804.htm", "required": ["Versigent", "VGNT", "Ordinary Shares", "New York Stock Exchange"]}]},
    "G3730V105": {"ticker": "FTAI", "documents": [
        {"url": "https://www.sec.gov/Archives/edgar/data/1590364/000201238326001663/xslSCHEDULE_13G_X02/primary_doc.xml", "required": ["G3730V105", "FTAI Aviation", "Common Stock"]},
        {"url": "https://www.sec.gov/Archives/edgar/data/1590364/000162828026012940/ftai-20251231.htm", "required": ["FTAI", "Ordinary shares", "Nasdaq Global Select"]}]},
})
# This is an admission boundary for the reviewed snapshot, not a claim that
# these companies first listed on this date. Earlier transport intervals remain unproved.
for _cusip in ("N52A8C105", "G4253H101", "G2R11M108", "G2004J103", "G9600F104", "G3730V105"):
    _PRIMARY_IDENTITY[_cusip]["identity_valid_from"] = "2026-09-22"


def _primary_documents(spec):
    return spec.get("documents") or [{"url": spec["url"], "required": spec["required"]}]


def _primary_plain(raw):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", raw))).strip().casefold()


def _verified_primary_candidate(cusip, receipt_file, receipt_sha256):
    """Revalidate exact configured declarations from immutable local receipts."""
    spec = _PRIMARY_IDENTITY.get(cusip)
    if spec is None:
        return None
    bundle = json.loads(_verified({"path": str(receipt_file), "sha256": receipt_sha256}).read_text(encoding="utf-8"))
    receipts = [row for row in bundle.get("sources", []) if row.get("cusip") == cusip]
    for document in _primary_documents(spec):
        matching = [row for row in receipts if row.get("url") == document["url"] and row.get("status") == 200]
        if len(matching) != 1:
            return None
        raw = _verified({"path": matching[0]["raw_path"], "sha256": matching[0]["sha256"]}).read_text(encoding="utf-8")
        if not all(token.casefold() in _primary_plain(raw) for token in document["required"]):
            return None
    return {"ticker": spec["ticker"], "primary_evidence": receipts,
            **{key: spec[key] for key in ("identity_valid_from", "identity_valid_to") if key in spec}}


def _primary_identity_candidates(paths, targets: list[str], root: Path) -> dict:
    found, receipts = {}, []
    receipt_path = root / "primary_identity_evidence.json"
    # Reuse verified raw documents within a run without refreshing failed evidence.
    if receipt_path.exists():
        for cusip in targets:
            try:
                candidate = _verified_primary_candidate(cusip, receipt_path, _hash(receipt_path))
                if candidate:
                    found[cusip] = candidate
            except (ValueError, KeyError, OSError, TypeError):
                pass
        receipts = json.loads(receipt_path.read_text(encoding="utf-8")).get("sources", [])
    ua = configured_user_agent(paths.repo_root / "scripts/v22/stage_sec_pit_taxonomy.py")
    for cusip in targets:
        if cusip not in _PRIMARY_IDENTITY or cusip in found:
            continue
        receipts = [row for row in receipts if row.get("cusip") != cusip]
        for document in _primary_documents(_PRIMARY_IDENTITY[cusip]):
            time.sleep(0.4)
            try:
                response = requests.get(document["url"], headers={"User-Agent": ua}, timeout=(15, 45), allow_redirects=False)
                digest = hashlib.sha256(response.content).hexdigest()
                receipt = {"cusip": cusip, "url": document["url"], "status": response.status_code,
                           "sha256": digest, "observed_at": datetime.now(timezone.utc).isoformat()}
                receipts.append(receipt)
                if response.status_code == 200:
                    raw_path = root / f"primary_identity_{cusip}_{digest[:16]}.html"
                    raw_path.write_bytes(response.content)
                    receipt["raw_path"] = str(raw_path)
            except requests.RequestException as exc:
                receipts.append({"cusip": cusip, "url": document["url"], "status": "REQUEST_FAILED", "error_type": type(exc).__name__})
    _save(receipt_path, {"sources": receipts})
    for cusip in targets:
        try:
            candidate = _verified_primary_candidate(cusip, receipt_path, _hash(receipt_path))
            if candidate:
                found[cusip] = candidate
        except (ValueError, KeyError, OSError, TypeError):
            pass
    return found


def _identity_cache_path(paths):
    return paths.cache_root / "daily_recommendation/identity_evidence/current.json"


def _identity_report_references(paths, root, explicit=None):
    if explicit is not None:
        return [{"path": str(Path(path)), "sha256": _hash(Path(path))} for path in explicit]
    references = []
    index = _identity_cache_path(paths)
    if index.exists():
        try:
            saved = json.loads(index.read_text(encoding="utf-8")).get("reports", [])
            if not isinstance(saved, list) or any(not isinstance(ref, dict) or not {"path", "sha256"}.issubset(ref) for ref in saved):
                raise ValueError("INVALID_IDENTITY_REFERENCE_INDEX")
            references.extend(saved)
        except (OSError, ValueError, TypeError):
            # Surface a rejected reference while still trying the independently
            # saved last-run pointer; a broken cache is not negative identity.
            references.append({"path": str(index), "sha256": "INVALID_REFERENCE_INDEX"})
    pointer = paths.daily_root / "A2_today_recommendation/current_universe.json"
    if pointer.exists():
        snapshot = json.loads(pointer.read_text(encoding="utf-8"))
        prior = Path(snapshot["report_path"])
        if prior.is_file() and prior.parent.resolve() != root.resolve():
            references.append({"path": str(prior), "sha256": _hash(prior)})
    return list({(ref["path"], ref["sha256"]): ref for ref in references}.values())[-16:]


def _remember_identity_report(paths, report_path, prior_references=()):
    path = _identity_cache_path(paths)
    references = list(prior_references)
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8")).get("reports", [])
            if not isinstance(saved, list) or any(not isinstance(ref, dict) or not {"path", "sha256"}.issubset(ref) for ref in saved):
                return  # Preserve malformed cache evidence; do not block a completed run.
            references += saved
        except (OSError, ValueError, TypeError):
            return
    references.append({"path": str(report_path), "sha256": _hash(report_path)})
    references = list({(ref["path"], ref["sha256"]): ref for ref in references}.values())[-16:]
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(path, {"role": "VERIFIED_CURRENT_IDENTITY_EVIDENCE_REFERENCES", "reports": references})


def _prior_identity_evidence(paths, universe, root, context, *, prior_reports=None):
    """Reuse exact positive evidence; never infer identity from a network error.

    These are current-pool transport observations, never historical identities.
    Prior OpenFIGI positives can seed later runs with matching quarter/base
    registries. Static transport validation is reused only on the same UTC day
    and target; later targets still require the existing current OpenD check.
    """
    result = {"openfigi": {}, "overlay": {}, "validation": {}, "sources": [], "issues": []}
    if context is None:
        return result
    current_path = root / "openfigi_exact_cusip.json"
    current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else {}
    static_path = root / "identity_transport_validation.parquet"
    current_static = pd.read_parquet(static_path) if static_path.exists() else pd.DataFrame()
    targets, conflicts = set(universe.cusip.astype(str)), set()
    now = pd.Timestamp(context["latest_disclosures_checked_at"])
    valid_ticker = lambda value: isinstance(value, str) and bool(re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", value))
    for reference in _identity_report_references(paths, root, prior_reports):
        try:
            report_path = _verified(reference)
            if not report_path.resolve().is_relative_to(paths.daily_root.resolve()):
                raise ValueError("IDENTITY_PRIOR_REPORT_OUTSIDE_DAILY_ROOT")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report.get("status") != "READY" or not report.get("current") or report.get("quarter") != context["quarter"]:
                continue
            if any(report.get(key, {}).get("sha256") != context[key]["sha256"] for key in ("registry", "identity_source")):
                continue
            for key in ("registry", "identity_source"):
                _verified(report[key])
            observed = pd.Timestamp(report["latest_disclosures_checked_at"])
            if observed.tzinfo is None or now.tzinfo is None or observed > now:
                continue
            directory = report_path.parent
            artifact_refs = report.get("identity_artifacts", {})
            cache_ref = artifact_refs.get("openfigi", {"path": str(directory / "openfigi_exact_cusip.json"),
                "sha256": report.get("identity_completion", {}).get("raw_evidence_sha256")})
            cache_file = _verified(cache_ref)
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
            members_file = _verified({"path": str(directory / "mapped_members.parquet"), "sha256": report["universe_members_sha256"]})
            members = pd.read_parquet(members_file)
            if members.security_id.duplicated().any() or members.ticker.duplicated().any() or members.moomoo_symbol.duplicated().any():
                raise ValueError("IDENTITY_PRIOR_MEMBERS_COLLIDE")
            member_map = {row["security_id"]: row for row in members.to_dict("records")}
            overlay_file, validation_file = directory / "identity_overlay.parquet", directory / "identity_transport_validation.parquet"
            if "overlay" in artifact_refs:
                overlay_file = _verified(artifact_refs["overlay"])
            if "validation" in artifact_refs:
                validation_file = _verified(artifact_refs["validation"])
            overlay, validation = pd.read_parquet(overlay_file), pd.read_parquet(validation_file)
            if overlay.cusip.duplicated().any():
                raise ValueError("IDENTITY_PRIOR_OVERLAY_AMBIGUOUS")
            hits = validation.loc[validation.request_status.eq("PASS") & validation.direct_static_hit.eq(True)]
            hits = {row["moomoo_transport_code"]: row for row in hits.to_dict("records")}
            source = {"report": reference, "openfigi": cache_ref,
                      "overlay": {"path": str(overlay_file), "sha256": _hash(overlay_file)},
                      "validation": {"path": str(validation_file), "sha256": _hash(validation_file)}}
            same_day = observed.tz_convert("UTC").date() == now.tz_convert("UTC").date() and report.get("target_date") == context["target_date"]
            used = []
            for row in overlay.to_dict("records"):
                cusip, ticker, code = str(row["cusip"]), row["ticker"], row["moomoo_transport_code"]
                row_observed = pd.Timestamp(row.get("identity_observed_at"))
                if pd.isna(row_observed) or row_observed.tzinfo is None or row_observed > now:
                    continue
                if str(row.get("mapping_source", "")).startswith("PRIMARY_CUSIP_"):
                    primary = _verified_primary_candidate(cusip, row.get("identity_evidence_path"), row.get("identity_evidence_sha256"))
                    member = member_map.get(cusip, {})
                    live_exact = _exact_us_composite(current.get(cusip, {}), valid_ticker)
                    if live_exact is not None and live_exact["ticker"] != ticker:
                        continue
                    checks = current_static.loc[current_static.moomoo_transport_code.eq(code)] if not current_static.empty else pd.DataFrame()
                    if (not primary or primary["ticker"] != ticker or code != "US." + ticker or code not in hits
                            or member.get("ticker") != ticker or member.get("moomoo_symbol") != code
                            or any(("" if pd.isna(row.get(key)) else str(row.get(key, ""))) != str(primary.get(key, "")) for key in ("identity_valid_from", "identity_valid_to"))
                            or (not checks.empty and not (checks.request_status.eq("PASS") & checks.direct_static_hit.eq(True)).all())):
                        continue
                    accepted, rejected = _map_universe(pd.DataFrame([{"cusip": cusip}]), pd.DataFrame([row]), as_of=context.get("target_date"))
                    if accepted and not rejected and same_day and row_observed.tz_convert("UTC").date() == now.tz_convert("UTC").date():
                        result["overlay"][cusip] = row
                        result["validation"][code] = hits[code]
                        used.append(cusip)
                    continue
                raw = cache.get(cusip, {})
                exact = _exact_us_composite(raw, valid_ticker)
                member = member_map.get(cusip, {})
                if (cusip not in targets or raw.get("status") != "PASS" or raw.get("query", {}).get("idType") != "ID_CUSIP"
                        or raw.get("query", {}).get("idValue") != cusip or exact is None
                        or exact["ticker"] != ticker or code != "US." + ticker or code not in hits
                        or member.get("ticker") != ticker or member.get("moomoo_symbol") != code
                        or row.get("composite_figi") != exact["compositeFIGI"] or row.get("share_class_figi") != exact["shareClassFIGI"]):
                    continue
                accepted, gaps = _map_universe(pd.DataFrame([{"cusip": cusip}]), pd.DataFrame([row]), as_of=context.get("target_date"))
                if not accepted or gaps:
                    continue
                live = current.get(cusip)
                if live is not None and live.get("status") != "NETWORK_FAILED":
                    latest = _exact_us_composite(live, valid_ticker)
                    if live.get("status") != "PASS" or latest is None or any(latest[key] != exact[key] for key in ("ticker", "compositeFIGI", "shareClassFIGI")):
                        continue
                if not current_static.empty:
                    checks = current_static.loc[current_static.moomoo_transport_code.eq(code)]
                    if not checks.empty and not (checks.request_status.eq("PASS") & checks.direct_static_hit.eq(True)).all():
                        continue
                previous = result["openfigi"].get(cusip)
                if previous and any(_exact_us_composite(previous, valid_ticker)[key] != exact[key]
                                    for key in ("ticker", "compositeFIGI", "shareClassFIGI")):
                    conflicts.add(cusip)
                    continue
                result["openfigi"][cusip] = raw
                if same_day and row_observed.tz_convert("UTC").date() == now.tz_convert("UTC").date():
                    result["overlay"][cusip] = row
                    result["validation"][code] = hits[code]
                used.append(cusip)
            if used:
                result["sources"].append({**source, "cusips": sorted(used), "reuse_static_same_day_target": same_day})
        except (ValueError, KeyError, OSError, TypeError) as exc:
            result["issues"].append({"report_path": reference.get("path"), "reason": type(exc).__name__ + ":" + str(exc)})
    for cusip in conflicts:
        result["openfigi"].pop(cusip, None)
        result["overlay"].pop(cusip, None)
        result["issues"].append({"cusip": cusip, "reason": "CONFLICTING_VERIFIED_PRIOR_IDENTITIES_REQUIRE_FRESH_EVIDENCE"})
    return result


def recover_current_identity(paths, current_report_path, prior_report_paths, output_dir):
    """Offline current-pool recovery; original runs and current pointers stay put.

    Reuses the already selected SEC quarter and its verified mapped members.
    It neither reselects a universe nor supplies historical pool membership.
    The caller may explicitly adopt the returned separate report afterwards.
    """
    source = Path(current_report_path).resolve()
    report = json.loads(source.read_text(encoding="utf-8"))
    if report.get("status") != "READY" or not report.get("current"):
        raise ValueError("IDENTITY_RECOVERY_REQUIRES_CURRENT_READY_REPORT")
    for key in ("registry", "identity_source"):
        _verified(report[key])
    catalog = paths.cache_root / "derived/data_catalog/catalog.sqlite3"
    with sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        active = connection.execute("SELECT path,source_sha256 FROM data_files WHERE dataset='13f_identity' AND is_current=1").fetchall()
    if active != [(report["identity_source"]["path"], report["identity_source"]["sha256"])]:
        raise ValueError("IDENTITY_RECOVERY_BASE_CATALOG_CHANGED")
    quarter_file = _verified({"path": str(source.parent / "quarter_universe.parquet"), "sha256": report["universe_manifest_sha256"]})
    members_file = _verified({"path": str(source.parent / "mapped_members.parquet"), "sha256": report["universe_members_sha256"]})
    universe, current_members = pd.read_parquet(quarter_file), pd.read_parquet(members_file)
    prior = _prior_identity_evidence(paths, universe, source.parent, report, prior_reports=prior_report_paths)
    old_members = {row["security_id"]: row for row in current_members.to_dict("records")}
    prior["overlay"] = {cusip: row for cusip, row in prior["overlay"].items()
        if cusip not in old_members or (old_members[cusip]["ticker"], old_members[cusip]["moomoo_symbol"]) != (row["ticker"], row["moomoo_transport_code"])}
    if not prior["overlay"]:
        raise ValueError("IDENTITY_RECOVERY_NO_VERIFIED_SAME_DAY_EVIDENCE")
    identity = pd.DataFrame([{**row, "cusip": row["security_id"], "moomoo_transport_code": row["moomoo_symbol"],
        "mapping_status": "RESOLVED", "transport_static_validated": True} for row in current_members.to_dict("records")])
    reused = pd.DataFrame(prior["overlay"].values())
    identity = pd.concat([identity.loc[~identity.cusip.isin(set(reused.cusip))], reused], ignore_index=True)
    members, gaps = _map_universe(universe, identity, as_of=report.get("target_date"))
    if not set(current_members.security_id).issubset({row["security_id"] for row in members}):
        raise ValueError("IDENTITY_RECOVERY_WOULD_REMOVE_VERIFIED_MEMBER")
    destination = Path(output_dir).resolve()
    if not destination.is_relative_to(paths.daily_root.resolve()) or destination.is_relative_to(source.parent):
        raise ValueError("IDENTITY_RECOVERY_REQUIRES_SEPARATE_DAILY_OUTPUT")
    if destination.exists():
        raise FileExistsError("IDENTITY_RECOVERY_OUTPUT_ALREADY_EXISTS")
    # Keep current failed raw observations in the original run; this new view
    # explicitly references them and the independently verified positive source.
    cache = json.loads((source.parent / "openfigi_exact_cusip.json").read_text(encoding="utf-8"))
    if _hash(source.parent / "openfigi_exact_cusip.json") != report["identity_completion"]["raw_evidence_sha256"]:
        raise ValueError("IDENTITY_CURRENT_OPENFIGI_HASH_CHANGED")
    for cusip, row in prior["openfigi"].items():
        if cusip not in cache or cache[cusip].get("status") == "NETWORK_FAILED":
            cache[cusip] = row
    overlay = pd.read_parquet(source.parent / "identity_overlay.parquet")
    for row in overlay.to_dict("records"):
        old = old_members.get(str(row["cusip"]), {})
        if old.get("ticker") != row["ticker"] or old.get("moomoo_symbol") != row["moomoo_transport_code"]:
            raise ValueError("IDENTITY_CURRENT_OVERLAY_NOT_BOUND_TO_VERIFIED_MEMBER")
    overlay = pd.concat([overlay.loc[~overlay.cusip.isin(set(reused.cusip))], reused], ignore_index=True)
    validation = pd.read_parquet(source.parent / "identity_transport_validation.parquet")
    validation = pd.concat([validation, pd.DataFrame(prior["validation"].values())], ignore_index=True).drop_duplicates("moomoo_transport_code", keep="first")
    destination.mkdir(parents=True)
    pd.DataFrame(members).to_parquet(destination / "mapped_members.parquet", index=False)
    (destination / "quarter_universe.parquet").write_bytes(quarter_file.read_bytes())
    overlay.to_parquet(destination / "identity_overlay.parquet", index=False)
    validation.to_parquet(destination / "identity_transport_validation.parquet", index=False)
    _save(destination / "openfigi_exact_cusip.json", cache)
    _save(destination / "identity_reuse.json", {key: prior[key] for key in ("sources", "issues")})
    changed = {row["security_id"]: row for row in members}
    report.update(report_path=str(destination / "universe_report.json"), members=members,
        mapped_member_count=len(members), mapping_gaps=gaps, mapping_gap_count=len(gaps),
        coverage_status="PARTIAL_IDENTITY_COVERAGE" if gaps else "FULL_IDENTITY_COVERAGE",
        universe_members_sha256=_hash(destination / "mapped_members.parquet"),
        universe_id=hashlib.sha256(json.dumps({"quarter": report["quarter"], "cusips": sorted(universe.cusip.astype(str)),
            "mapped_members": sorted((row["security_id"], row["ticker"], row["moomoo_symbol"]) for row in members)}, sort_keys=True).encode()).hexdigest(),
        identity_recovery={"source_report": {"path": str(source), "sha256": _hash(source)}, "network_requests": 0,
            "reused_cusips": sorted(prior["overlay"]), "added_cusips": sorted(set(changed)-set(old_members)),
            "corrected_cusips": sorted(cusip for cusip in old_members if changed[cusip]["ticker"] != old_members[cusip]["ticker"]),
            "prior_evidence_sources": prior["sources"], "issues": prior["issues"]})
    report["identity_completion"] = {**report["identity_completion"], "added_or_updated": len(overlay),
        "reused_verified_same_day": len(reused), "remaining_gaps": len(gaps),
        "unresolved": [row["cusip"] for row in gaps], "raw_evidence_sha256": _hash(destination / "openfigi_exact_cusip.json")}
    report["identity_artifacts"] = {key: {"path": str(destination / name), "sha256": _hash(destination / name)}
        for key, name in (("openfigi", "openfigi_exact_cusip.json"), ("overlay", "identity_overlay.parquet"),
                          ("validation", "identity_transport_validation.parquet"))}
    _save(destination / "universe_report.json", report)
    _remember_identity_report(paths, destination / "universe_report.json", [item["report"] for item in prior["sources"]])
    return report


def complete_identity_mapping(paths, universe: pd.DataFrame, identity: pd.DataFrame, root: Path,
                              *, context=None, reusable_evidence=None) -> tuple[pd.DataFrame, dict]:
    """Extend this run's copy with exact CUSIP + US FIGI + current OpenD evidence."""
    prior = reusable_evidence if reusable_evidence is not None else _prior_identity_evidence(paths, universe, root, context)
    if prior["overlay"]:
        reusable = pd.DataFrame(prior["overlay"].values())
        identity = pd.concat([identity.loc[~identity.cusip.astype(str).isin(set(reusable.cusip))], reusable], ignore_index=True)
        reusable.to_parquet(root / "identity_overlay.parquet", index=False)
        if not (root / "identity_transport_validation.parquet").exists():
            pd.DataFrame(prior["validation"].values()).to_parquet(root / "identity_transport_validation.parquet", index=False)
    if prior["sources"] or prior["issues"]:
        _save(root / "identity_reuse.json", {key: prior[key] for key in ("sources", "issues")})
    cache_path = root / "openfigi_exact_cusip.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    for cusip, row in prior["openfigi"].items():
        if cusip not in cache:
            cache[cusip] = row
    if cache and not cache_path.exists():
        _save(cache_path, cache)
    _, gaps = _map_universe(universe, identity, as_of=(context or {}).get("target_date"))
    if not gaps:
        return identity, {"requested": 0, "added_or_updated": 0, "reused_verified_same_day": len(prior["overlay"]),
                          "prior_evidence_sources": prior["sources"], "prior_evidence_issues": prior["issues"],
                          "raw_evidence_sha256": _hash(cache_path) if cache_path.exists() else None}
    targets = sorted({row["cusip"] for row in gaps})
    summary = {"requested": len(targets), "added_or_updated": 0, "openfigi_requests": 0,
               "reused_verified_same_day": len(prior["overlay"]), "prior_evidence_sources": prior["sources"],
               "prior_evidence_issues": prior["issues"],
               "mapping_rule": "EXACT_CUSIP_US_COMPOSITE_SHARE_CLASS_OR_EXPLICIT_PRIMARY_ORDINARY_SHARE_DECLARATION_PLUS_CURRENT_OPEND_STATIC_HIT"}
    package = paths.results_root / "13f_pit_v1"
    helper_path = package / "scripts/v17c/two_gap_closeout_v17c.py"
    helper = import_source(helper_path, "daily_current_identity_completion")
    summary["resolver_source"] = {"path": str(helper_path), "sha256": _hash(helper_path)}
    # OpenFIGI's existing exact-ID helper is called in public-API-sized batches.
    # https://www.openfigi.com/api/documentation: 10 jobs, 25 requests/minute without a key.
    for start in range(0, len(targets), 10):
        if start and any(cusip not in cache for cusip in targets[start:start + 10]):
            time.sleep(3)
        cache, count = helper.query_openfigi_exact(targets[start:start + 10], cache_path)
        summary["openfigi_requests"] += count
    summary["openfigi_evidenced_cusips"] = len(cache)
    candidates = {}
    for cusip in targets:
        row = _exact_us_composite(cache.get(cusip, {}), helper.valid_ticker)
        if row is not None:
            candidates[cusip] = row
    summary["exact_us_candidates"] = len(candidates)
    primary = _primary_identity_candidates(paths, [cusip for cusip in targets if cusip not in candidates], root)
    candidates.update(primary)
    summary["primary_source_candidates"] = len(primary)
    if not candidates:
        summary["unresolved"] = targets
        _save(root / "identity_completion.json", summary)
        return identity, summary
    from scripts.storage.refresh_market_data import load_module, PROFILE
    profile_module = load_module(paths.repo_root / PROFILE, "daily_identity_connection_profile")
    profile = profile_module.load_profile(paths.repo_root / "config/moomoo_opend_connection.json", dict(os.environ))
    connected, reason = profile_module.tcp_probe(profile)
    if not connected:
        summary["transport_status"] = str(reason)
        _save(root / "identity_completion.json", summary)
        return identity, summary
    codes = ["US." + row["ticker"] for row in candidates.values()]
    validation, count = helper.validate_transport_codes(codes, profile.host, profile.port, root / "identity_sdk_logs")
    validation = pd.concat([validation, pd.DataFrame(prior["validation"].values())], ignore_index=True).drop_duplicates("moomoo_transport_code", keep="first")
    validation.to_parquet(root / "identity_transport_validation.parquet", index=False)
    summary["static_requests"] = count
    hits = set(validation.loc[validation.direct_static_hit.eq(True) & validation.request_status.eq("PASS"), "moomoo_transport_code"])
    overlay = [row for cusip, row in prior["overlay"].items() if cusip not in candidates]
    for cusip, row in candidates.items():
        code = "US." + row["ticker"]
        if code not in hits:
            continue
        overlay.append({"cusip": cusip, "ticker": row["ticker"], "moomoo_transport_code": code,
                        "mapping_status": "RESOLVED", "transport_static_validated": True,
                        "transport_alias_status": "CURRENT_EXACT_CUSIP_US_COMPOSITE_VALIDATED",
                        "transport_interval_status": "CURRENT_SNAPSHOT_ONLY_NOT_HISTORICAL_INTERVAL_AUTHORITY",
                        "mapping_source": "PRIMARY_CUSIP_ORDINARY_SHARE_TICKER_PLUS_MOOMOO_STATIC" if "primary_evidence" in row else "OPENFIGI_ID_CUSIP_CURRENT_US_COMPOSITE_PLUS_MOOMOO_STATIC",
                        "figi": row.get("figi"), "composite_figi": row.get("compositeFIGI"),
                        "share_class_figi": row.get("shareClassFIGI"), "identity_observed_at": datetime.now(timezone.utc).isoformat(),
                        "identity_evidence_path": str(root / "primary_identity_evidence.json") if "primary_evidence" in row else str(cache_path),
                        "identity_evidence_sha256": _hash(root / "primary_identity_evidence.json") if "primary_evidence" in row else _hash(cache_path),
                        **{key: row[key] for key in ("identity_valid_from", "identity_valid_to") if key in row}})
    if overlay:
        added = pd.DataFrame(overlay)
        added.to_parquet(root / "identity_overlay.parquet", index=False)
        completed = pd.concat([identity.loc[~identity.cusip.astype(str).isin(set(added.cusip))], added], ignore_index=True)
    else:
        completed = identity
    _, remaining = _map_universe(universe, completed, as_of=(context or {}).get("target_date"))
    summary.update(added_or_updated=len(overlay), remaining_gaps=len(remaining),
                   unresolved=[row["cusip"] for row in remaining],
                   original_registry_changed=False, raw_evidence_sha256=_hash(cache_path))
    _save(root / "identity_completion.json", summary)
    return completed, summary


def _complete_reporting_periods(initial: pd.DataFrame, registry: pd.DataFrame) -> list[str]:
    """A quarter is complete only for its own applicable registered identities."""
    complete = []
    for period, group in initial.groupby("report_date", sort=True):
        if not isinstance(period, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", period):
            raise ValueError("13F_REPORT_DATE_NOT_QUARTER_END")
        reporting_quarter = pd.Period(period, freq="Q")
        if period != str(reporting_quarter.end_time.date()):
            raise ValueError("13F_REPORT_DATE_NOT_QUARTER_END")
        quarter = str(reporting_quarter)
        expected = set(active_managers(registry, quarter).manager_id.astype(str))
        if set(group.manager_id.astype(str)) == expected:
            complete.append(str(period))
    return complete


def refresh_universe(paths, target, run_dir: Path, execute: bool = True) -> dict:
    """Separate current disclosures from explicit partial identity coverage."""
    target_date = target["target_date"] if isinstance(target, dict) else str(target)
    required = required_reporting_quarter(target_date)
    root = Path(run_dir) / "universe_refresh"
    root.mkdir(parents=True, exist_ok=True)
    result = {"status": "WAITING_DATA", "current": False, "inference_ready": False,
              "target_date": target_date, "required_quarter": required, "quarter": required,
              "members": [], "universe_id": "", "reason": "13F_REFRESH_NOT_COMPLETED",
              "report_path": str(root / "universe_report.json"), "membership_scope": "CURRENT_EXTERNAL25_USER_REQUESTED",
              "frozen_a2_history_changed": False, "mapping_gaps": []}
    reader = None
    try:
        baseline_path = paths.data_root / "13f/recovery_20260913/quarter_manifest.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        registry_path = _verified(baseline["sources"]["registry"])
        parser_path = _verified(baseline["sources"]["xml_parser"])
        selection_path = _verified(baseline["sources"]["selection"])
        registry = pd.read_csv(registry_path, dtype=str, keep_default_na=False)
        managers = active_managers(registry, required)
        roster = manager_roster_identity(registry, required)
        result["registry"] = {"path": str(registry_path), "sha256": _hash(registry_path),
                              "manager_count": len(managers), "quarter_roster": roster}
        catalog = paths.cache_root / "derived/data_catalog/catalog.sqlite3"
        with sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            mapping = connection.execute("SELECT path,source_sha256 FROM data_files WHERE dataset='13f_identity' AND is_current=1").fetchall()
        if len(mapping) != 1:
            raise ValueError("13F_IDENTITY_CATALOG_AMBIGUOUS")
        identity_path = _verified({"path": mapping[0][0], "sha256": mapping[0][1]})
        result["identity_source"] = {"path": str(identity_path), "sha256": mapping[0][1]}
        # Cached originals are immutable accession evidence. Every reused byte
        # is checked against its prior receipt, then reparsed with current metadata.
        originals = {row["url"]: {"path": row["path"], "sha256": row["sha256"]} for row in baseline["raw_filings"]}
        later = paths.results_root / "13f_intake/13f_personal_contact_20260914/acquisition.json"
        if later.exists():
            prior = json.loads(later.read_text(encoding="utf-8"))
            for row in prior.get("verified_filings", []):
                originals[row["source_url"]] = {"path": row["raw_path"], "sha256": row["source_sha256"]}
        if not execute:
            result["reason"] = "13F_LATEST_DISCLOSURES_NOT_CHECKED_DRY_RUN"
            return result
        ua = configured_user_agent(paths.repo_root / "scripts/v22/stage_sec_pit_taxonomy.py")
        reader = _SecReader(root / "raw", ua)
        now = pd.Timestamp(datetime.now(timezone.utc))
        minimum = str(pd.Period(required, freq="Q").end_time.date())
        discovered = []
        for manager in managers.to_dict("records"):
            if manager["manager_id"] == "pershing_square" and required >= "2026Q2":
                manager["cik"] = PERSHING_ALIAS["cik"]
                result["identity_alias"] = PERSHING_ALIAS
            payload = reader.get(f"https://data.sec.gov/submissions/CIK{int(manager['cik']):010d}.json")
            discovered.extend(_submission_records(manager, json.loads(payload), reader, minimum, now))
        frame = pd.DataFrame(discovered)
        if frame.empty:
            raise ValueError("13F_NO_CURRENT_DISCLOSURES")
        initial = frame.loc[frame.form.eq("13F-HR")]
        complete = _complete_reporting_periods(initial, registry)
        if not complete:
            raise ValueError("13F_CURRENT_QUARTER_INCOMPLETE")
        period = complete[-1]
        filings = frame.loc[frame.report_date.eq(period)].sort_values(["manager_id", "accepted_at", "accession"])
        quarter = str(pd.Period(period, freq="Q"))
        roster = manager_roster_identity(registry, quarter)
        result["registry"].update(manager_count=roster["applicable_manager_count"], quarter_roster=roster)
        result.update(quarter=quarter, latest_disclosures_checked_at=now.isoformat(), filing_count=len(filings))
        parser = import_source(parser_path, "daily_current_13f_parser")
        selection = import_source(selection_path, "daily_current_13f_selection")
        records, issues, evidence = [], [], []
        for filing in filings.to_dict("records"):
            url = filing["source_url"]
            if url in originals:
                original = _verified(originals[url])
                payload = original.read_bytes()
            else:
                payload = reader.get(url)
            rows, details = _inspect_filing(payload, filing, parser)
            records.append((filing, rows, details))
            evidence.append({**filing, **details, "source_sha256": hashlib.sha256(payload).hexdigest()})
            if not details["source_value_total_reconciled"]:
                issues.append({"manager_id": filing["manager_id"], "accession": filing["accession"],
                               "reason": "SOURCE_COVER_DETAIL_VALUE_DIFFERENCE", "difference": details["detail_minus_cover"]})
        raw, effective_filings = _apply_filings(records)
        selected, universe = build_quarter(raw, effective_filings, selection, parser)
        universe["manager_roster_sha256"] = roster["roster_sha256"]
        universe["applicable_manager_count"] = roster["applicable_manager_count"]
        identity = pd.read_parquet(identity_path)
        try:
            prior_identity = _prior_identity_evidence(paths, universe, root, result)
            if prior_identity["overlay"]:
                prior_rows = pd.DataFrame(prior_identity["overlay"].values())
                identity = pd.concat([identity.loc[~identity.cusip.astype(str).isin(set(prior_rows.cusip))], prior_rows], ignore_index=True)
            identity, completion = complete_identity_mapping(paths, universe, identity, root,
                context=result, reusable_evidence=prior_identity)
            result["identity_completion"] = completion
        except Exception as exc:
            # Optional mapping enrichment cannot erase already verified members.
            result["identity_completion"] = {"status": "INCOMPLETE", "reason": f"{type(exc).__name__}:{exc}"}
        members, missing = _map_universe(universe, identity, as_of=target_date)
        original = pd.read_parquet(_verified(baseline["files"]["quarter_universe"]), columns=["cusip"])
        old_cusips, new_cusips = set(original.cusip.astype(str)), set(universe.cusip.astype(str))
        fingerprint = hashlib.sha256(json.dumps({"quarter": quarter, "cusips": sorted(new_cusips),
            "mapped_members": sorted((row["security_id"], row["ticker"], row["moomoo_symbol"]) for row in members)},
            sort_keys=True).encode()).hexdigest()
        effective = str(pd.Timestamp(universe.effective_date.iloc[0]).date())
        pd.DataFrame(members).to_parquet(root / "mapped_members.parquet", index=False)
        universe.to_parquet(root / "quarter_universe.parquet", index=False)
        _save(root / "filing_evidence.json", {"filings": evidence})
        result.update(members=members, universe_id=fingerprint, effective_date=effective,
                      universe_member_count=len(universe), mapped_member_count=len(members),
                      mapping_gaps=missing, mapping_gap_count=len(missing), source_issues=issues,
                      coverage_status="PARTIAL_IDENTITY_COVERAGE" if missing else "FULL_IDENTITY_COVERAGE",
                      changes={"baseline_quarter": baseline["quarter"], "baseline_count": len(old_cusips),
                               "current_count": len(new_cusips), "added_cusips": sorted(new_cusips-old_cusips),
                               "removed_cusips": sorted(old_cusips-new_cusips),
                               "added_count": len(new_cusips-old_cusips), "removed_count": len(old_cusips-new_cusips)},
                      selection_contract="EXISTING_V17B_TOP100_PROTECTED20_CAP900",
                      universe_members_sha256=_hash(root / "mapped_members.parquet"),
                      universe_manifest_sha256=_hash(root / "quarter_universe.parquet"))
        result["identity_artifacts"] = {key: {"path": str(root / name), "sha256": _hash(root / name)}
            for key, name in (("openfigi", "openfigi_exact_cusip.json"), ("overlay", "identity_overlay.parquet"),
                              ("validation", "identity_transport_validation.parquet")) if (root / name).is_file()}
        if effective > target_date:
            result["reason"] = f"CURRENT_13F_NOT_EFFECTIVE_UNTIL:{effective}"
        else:
            result["current"] = True
            if len(members) < 20:
                result["reason"] = f"CURRENT_13F_FEWER_THAN_20_VERIFIED_MEMBERS:{len(members)}"
            else:
                result.update(status="READY", inference_ready=True, reason="")
    except Exception as exc:
        result["reason"] = f"13F_REFRESH_FAILED:{type(exc).__name__}:{exc}"
    finally:
        if reader is not None:
            reader.session.close()
            result["request_count"] = len(reader.receipts)
        result["failure_reason"] = result["reason"]
        _save(root / "universe_report.json", result)
        if result.get("status") == "READY" and result.get("identity_artifacts", {}).get("openfigi"):
            _remember_identity_report(paths, root / "universe_report.json")
    return result
