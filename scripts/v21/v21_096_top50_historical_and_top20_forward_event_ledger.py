#!/usr/bin/env python
"""V21.096 Top50 historical SEC and Top20 forward event ledger."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUT = Path("outputs/v21")
D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
BASE_EVENT_REL = Path("outputs/v21/v21_095_r4_certified_event_snapshot_ledger.csv")
TOP20_DIR = Path("data/events/manual_import/top20_forward")
TOP50_DIR = Path("data/events/manual_import/top50_historical")
RAW_SEC = Path("data/events/raw_snapshots/sec")
RAW_MACRO = Path("data/events/raw_snapshots/official_macro")
CIK_MANUAL = TOP50_DIR / "top50_ticker_cik_mapping.csv"
FORMS = {
    "10-Q", "10-K", "8-K", "8-K/A", "S-3", "S-3ASR", "424B2", "424B3",
    "424B5", "DEF 14A", "SC 13D", "SC 13G", "13D/A", "13G/A",
}
FORWARD_TYPES = {
    "ticker_earnings", "sector_key_earnings", "company_split",
    "company_financing", "company_regulatory", "company_lockup",
    "company_mna", "company_product_event", "company_investor_day",
    "manual_watch_event",
}
UNIVERSE_COLUMNS = [
    "rank", "ticker", "final_score", "sector_or_industry_if_available",
    "theme_or_bucket_if_available", "top20_flag", "top50_flag",
    "cik_if_available", "event_priority", "notes",
]
SEC_COLUMNS = [
    "event_id", "ticker", "cik", "form_type", "filing_date",
    "accepted_datetime", "accession_number", "primary_document",
    "filing_url_or_sec_reference", "event_type", "event_name", "event_date",
    "event_time", "event_timezone", "known_as_of_timestamp",
    "retrieval_timestamp_utc", "source_name", "source_url_or_reference",
    "historical_event_occurrence_usable",
    "historical_pre_event_calendar_usable", "forward_observation_usable",
    "pit_certified", "pit_exclusion_reason", "research_only", "notes",
]
MACRO_COLUMNS = [
    "event_id", "event_type", "event_name", "event_date", "event_time",
    "event_timezone", "affected_ticker", "affected_sector", "source_name",
    "source_url_or_reference", "retrieval_timestamp_utc",
    "known_as_of_timestamp", "event_severity", "event_confidence",
    "historical_event_occurrence_usable",
    "historical_pre_event_calendar_usable", "forward_observation_usable",
    "pit_certified", "research_only", "notes",
]
FORWARD_NORMALIZED_COLUMNS = [
    "event_id", "ticker", "rank", "event_type", "event_name", "event_date",
    "event_time", "event_timezone", "event_window_start", "event_window_end",
    "event_severity", "event_confidence", "source_name",
    "source_url_or_reference", "retrieval_timestamp_utc",
    "provider_available_date", "known_as_of_timestamp", "affected_sector",
    "sector_propagation_allowed", "historical_event_occurrence_usable",
    "historical_pre_event_calendar_usable", "forward_observation_usable",
    "pit_certified", "pit_exclusion_reason", "research_only", "notes",
]
OUTPUTS = (
    "v21_096_r1_current_d_top50_event_universe.csv",
    "v21_096_r1_current_d_top20_forward_watchlist.csv",
    "v21_096_r2_ticker_cik_mapping.csv",
    "v21_096_r2_ticker_cik_mapping_validation.json",
    "v21_096_r2_ticker_cik_mapping_report.md",
    "v21_096_r3_top50_sec_raw_fetch_manifest.csv",
    "v21_096_r3_top50_sec_event_filings_raw.csv",
    "v21_096_r3_top50_sec_event_filings_classified.csv",
    "v21_096_r3_top50_sec_fetch_validation.json",
    "v21_096_r3_top50_sec_event_report.md",
    "v21_096_r4_top20_forward_manual_template_manifest.csv",
    "v21_096_r4_top20_forward_manual_event_validation.csv",
    "v21_096_r4_top20_forward_events_normalized.csv",
    "v21_096_r4_top20_forward_events_quarantined.csv",
    "v21_096_r5_official_macro_and_market_event_ledger.csv",
    "v21_096_r5_official_macro_source_audit.csv",
    "v21_096_r5_macro_event_report.md",
    "v21_096_r6_certified_event_master_ledger.csv",
    "v21_096_r6_event_coverage_by_top50_ticker.csv",
    "v21_096_r6_event_coverage_by_top20_ticker.csv",
    "v21_096_r6_event_coverage_by_event_type.csv",
    "v21_096_r6_event_pit_certification_audit.csv",
    "v21_096_r6_event_usage_policy.csv",
    "v21_096_r6_rejected_or_quarantined_events.csv",
    "v21_096_r7_top50_historical_top20_forward_event_ledger_report.md",
    "v21_096_r7_top50_historical_top20_forward_event_ledger_summary.json",
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def markdown(title: str, payload: dict[str, Any], note: str = "") -> str:
    lines = [f"# {title}", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in payload.items())
    if note:
        lines.extend(["", note])
    return "\n".join(lines) + "\n"


def protected_snapshot(root: Path, output_paths: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    event_root = (root / "data/events").resolve()
    result = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() in output_paths:
                continue
            if event_root in path.resolve().parents:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def fetch_bytes(url: str, user_agent: str, timeout: int = 30) -> bytes:
    effective_agent = (
        "Mozilla/5.0 (compatible; us-tech-quant-research/21.096)"
        if "bls.gov" in url else user_agent
    )
    request = urllib.request.Request(
        url, headers={
            "User-Agent": effective_agent, "Accept-Encoding": "identity",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def extract_universe(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    path = root / D_REL
    if not path.is_file():
        return pd.DataFrame(columns=UNIVERSE_COLUMNS), pd.DataFrame(columns=UNIVERSE_COLUMNS), ""
    frame = pd.read_csv(path, low_memory=False)
    frame["as_of_date"] = frame["as_of_date"].astype(str)
    frame["final_shadow_rank"] = pd.to_numeric(frame["final_shadow_rank"], errors="coerce")
    ranked = frame[frame["final_shadow_rank"].notna()]
    if ranked.empty:
        return pd.DataFrame(columns=UNIVERSE_COLUMNS), pd.DataFrame(columns=UNIVERSE_COLUMNS), ""
    latest = ranked["as_of_date"].max()
    current = ranked[ranked["as_of_date"].eq(latest)].sort_values("final_shadow_rank")
    rows = []
    for _, row in current.head(50).iterrows():
        rank = int(row["final_shadow_rank"])
        rows.append({
            "rank": rank, "ticker": str(row["ticker"]).upper().strip(),
            "final_score": row["final_shadow_score"],
            "sector_or_industry_if_available": "",
            "theme_or_bucket_if_available": (
                row.get("theme") if pd.notna(row.get("theme")) else row.get("momentum_state", "")
            ),
            "top20_flag": rank <= 20, "top50_flag": True,
            "cik_if_available": "", "event_priority": (
                "HIGH" if rank <= 20 else "MEDIUM"
            ),
            "notes": f"D baseline preserved; as_of_date={latest}",
        })
    top50 = pd.DataFrame(rows, columns=UNIVERSE_COLUMNS)
    return top50, top50.head(20).copy(), latest


def local_cik_candidates(root: Path) -> list[Path]:
    candidates = []
    for base_name in ("data", "state", "outputs", "archive", "config", "configs"):
        base = root / base_name
        if not base.exists():
            continue
        for path in base.rglob("*.csv"):
            name = path.name.lower()
            if "cik" in name and ("ticker" in name or "company" in name):
                candidates.append(path)
    if (root / CIK_MANUAL).is_file():
        candidates.insert(0, root / CIK_MANUAL)
    return candidates


def parse_local_cik(path: Path, tickers: set[str], run_ts: pd.Timestamp) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()
    lookup = {str(c).lower().strip(): c for c in frame.columns}
    ticker_col = next((lookup[x] for x in ("ticker", "symbol") if x in lookup), None)
    cik_col = next((lookup[x] for x in ("cik", "cik_str", "cik_number") if x in lookup), None)
    name_col = next((lookup[x] for x in ("company_name", "title", "name") if x in lookup), None)
    if not ticker_col or not cik_col:
        return pd.DataFrame()
    out = pd.DataFrame({
        "ticker": frame[ticker_col].astype(str).str.upper().str.strip(),
        "cik": pd.to_numeric(frame[cik_col], errors="coerce"),
        "company_name": frame[name_col].astype(str) if name_col else "",
    })
    out = out[out["ticker"].isin(tickers) & out["cik"].notna()]
    out["cik"] = out["cik"].astype("int64").astype(str).str.zfill(10)
    out["mapping_source"] = path.relative_to(path.parents[len(path.parts) - 1]).as_posix() if False else path.as_posix()
    out["mapping_confidence"] = "HIGH" if path.name == CIK_MANUAL.name else "MEDIUM"
    out["mapping_timestamp_utc"] = run_ts.isoformat()
    out["usable_for_sec_fetch"] = True
    out["notes"] = "Local read-only ticker/CIK mapping."
    return out


def build_cik_mapping(
    root: Path, top50: pd.DataFrame, enable_network: bool,
    user_agent: str, run_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    tickers = set(top50["ticker"])
    parts = []
    audit = []
    for path in local_cik_candidates(root):
        parsed = parse_local_cik(path, tickers, run_ts)
        if not parsed.empty:
            parts.append(parsed)
            audit.append({"source": path.as_posix(), "status": "LOCAL_MAPPING_USED", "rows": len(parsed)})
    if enable_network:
        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            payload = fetch_bytes(url, user_agent)
            snapshot = root / RAW_SEC / run_ts.date().isoformat() / "company_tickers.json"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(payload)
            decoded = json.loads(payload)
            rows = list(decoded.values()) if isinstance(decoded, dict) else decoded
            frame = pd.DataFrame(rows)
            frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
            frame = frame[frame["ticker"].isin(tickers)]
            network = pd.DataFrame({
                "ticker": frame["ticker"],
                "cik": pd.to_numeric(frame["cik_str"], errors="coerce").astype("Int64").astype(str).str.zfill(10),
                "company_name": frame["title"],
                "mapping_source": url,
                "mapping_confidence": "HIGH",
                "mapping_timestamp_utc": run_ts.isoformat(),
                "usable_for_sec_fetch": True,
                "notes": f"SEC company_tickers.json sha256={sha256_bytes(payload)}",
            })
            parts.append(network)
            audit.append({"source": url, "status": "NETWORK_MAPPING_USED", "rows": len(network)})
        except Exception as exc:
            audit.append({"source": url, "status": f"NETWORK_MAPPING_FAILED:{type(exc).__name__}", "rows": 0})
    if parts:
        merged = pd.concat(parts, ignore_index=True)
        priority = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        merged["_p"] = merged["mapping_confidence"].map(priority).fillna(9)
        merged = merged.sort_values(["ticker", "_p"]).drop_duplicates("ticker").drop(columns="_p")
    else:
        merged = pd.DataFrame(columns=[
            "ticker", "cik", "company_name", "mapping_source",
            "mapping_confidence", "mapping_timestamp_utc",
            "usable_for_sec_fetch", "notes",
        ])
    missing = sorted(tickers - set(merged["ticker"]))
    if missing:
        merged = pd.concat([merged, pd.DataFrame([{
            "ticker": ticker, "cik": "", "company_name": "",
            "mapping_source": "", "mapping_confidence": "NONE",
            "mapping_timestamp_utc": run_ts.isoformat(),
            "usable_for_sec_fetch": False, "notes": "MISSING_CIK_QUARANTINE",
        } for ticker in missing])], ignore_index=True)
    return merged.sort_values("ticker"), audit


def filing_arrays(payload: dict[str, Any]) -> pd.DataFrame:
    recent = payload.get("filings", {}).get("recent", {})
    if not recent:
        return pd.DataFrame()
    max_len = max((len(v) for v in recent.values() if isinstance(v, list)), default=0)
    data = {}
    for key, values in recent.items():
        if isinstance(values, list):
            data[key] = values + [None] * (max_len - len(values))
    return pd.DataFrame(data)


def classify_filing(form: str, items: str) -> tuple[str, str]:
    item_text = str(items)
    if form in {"10-Q", "10-K"}:
        return "filing_financial_report", f"{form} financial report filing"
    if form in {"S-3", "S-3ASR", "424B2", "424B3", "424B5"}:
        return "company_financing_or_shelf_offering", f"{form} financing/shelf filing"
    if form == "DEF 14A":
        return "shareholder_meeting_proxy", "Definitive proxy filing"
    if form in {"SC 13D", "SC 13G", "13D/A", "13G/A"}:
        return "ownership_event", f"{form} ownership filing"
    item_rules = (
        ("2.02", "ticker_earnings_occurrence", "Results of Operations filing"),
        ("1.01", "company_material_agreement", "Material definitive agreement"),
        ("2.01", "company_mna", "Acquisition or disposition"),
        ("3.02", "company_financing", "Unregistered sale of equity"),
        ("5.02", "company_management_change", "Officer or director change"),
        ("7.01", "company_reg_fd", "Regulation FD disclosure"),
        ("8.01", "company_other_material_event", "Other material event"),
    )
    for code, event_type, name in item_rules:
        if code in item_text:
            return event_type, name
    return "company_other_material_event", f"{form} material filing"


def sec_events_for_ticker(
    root: Path, ticker: str, cik: str, run_ts: pd.Timestamp,
    lookback: pd.Timestamp, user_agent: str, enable_network: bool,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
    snapshot_dir = root / RAW_SEC / run_ts.date().isoformat() / "submissions"
    snapshot = snapshot_dir / f"CIK{str(cik).zfill(10)}.json"
    manifest = []
    payload = None
    if snapshot.is_file():
        payload = snapshot.read_bytes()
        manifest.append({"ticker": ticker, "cik": cik, "source_url": url, "snapshot_path": snapshot.relative_to(root).as_posix(), "raw_payload_hash": sha256_bytes(payload), "fetch_status": "LOCAL_SNAPSHOT_REUSED", "retrieval_timestamp_utc": run_ts.isoformat(), "notes": ""})
    elif enable_network:
        try:
            payload = fetch_bytes(url, user_agent)
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(payload)
            manifest.append({"ticker": ticker, "cik": cik, "source_url": url, "snapshot_path": snapshot.relative_to(root).as_posix(), "raw_payload_hash": sha256_bytes(payload), "fetch_status": "NETWORK_FETCHED", "retrieval_timestamp_utc": run_ts.isoformat(), "notes": ""})
        except Exception as exc:
            manifest.append({"ticker": ticker, "cik": cik, "source_url": url, "snapshot_path": "", "raw_payload_hash": "", "fetch_status": f"FETCH_FAILED:{type(exc).__name__}", "retrieval_timestamp_utc": run_ts.isoformat(), "notes": ""})
    else:
        manifest.append({"ticker": ticker, "cik": cik, "source_url": url, "snapshot_path": "", "raw_payload_hash": "", "fetch_status": "NETWORK_DISABLED_NO_CACHE", "retrieval_timestamp_utc": run_ts.isoformat(), "notes": ""})
    if payload is None:
        return pd.DataFrame(columns=SEC_COLUMNS), manifest
    decoded = json.loads(payload)
    filings = filing_arrays(decoded)
    if filings.empty:
        return pd.DataFrame(columns=SEC_COLUMNS), manifest
    filings["filingDate_dt"] = pd.to_datetime(filings.get("filingDate"), errors="coerce", utc=True)
    filings = filings[
        filings["form"].isin(FORMS)
        & filings["filingDate_dt"].between(lookback, run_ts)
    ]
    rows = []
    for _, filing in filings.iterrows():
        form = str(filing.get("form", ""))
        filing_date = str(filing.get("filingDate", ""))
        accepted = pd.to_datetime(filing.get("acceptanceDateTime"), utc=True, errors="coerce")
        known = accepted if not pd.isna(accepted) else pd.to_datetime(filing_date, utc=True, errors="coerce")
        event_type, event_name = classify_filing(form, filing.get("items", ""))
        accession = str(filing.get("accessionNumber", ""))
        accession_clean = accession.replace("-", "")
        primary = str(filing.get("primaryDocument", ""))
        archive_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{primary}"
        event_date = known.date().isoformat() if not pd.isna(known) else filing_date
        rows.append({
            "event_id": "V21_096_SEC_" + hashlib.sha256(
                f"{ticker}|{accession}|{event_type}".encode()
            ).hexdigest()[:20].upper(),
            "ticker": ticker, "cik": str(cik).zfill(10), "form_type": form,
            "filing_date": filing_date,
            "accepted_datetime": "" if pd.isna(accepted) else accepted.isoformat(),
            "accession_number": accession, "primary_document": primary,
            "filing_url_or_sec_reference": archive_url, "event_type": event_type,
            "event_name": event_name, "event_date": event_date,
            "event_time": "" if pd.isna(accepted) else accepted.strftime("%H:%M:%S"),
            "event_timezone": "UTC",
            "known_as_of_timestamp": "" if pd.isna(known) else known.isoformat(),
            "retrieval_timestamp_utc": run_ts.isoformat(),
            "source_name": "SEC EDGAR Submissions API",
            "source_url_or_reference": url,
            "historical_event_occurrence_usable": not pd.isna(known),
            "historical_pre_event_calendar_usable": False,
            "forward_observation_usable": False,
            "pit_certified": not pd.isna(known),
            "pit_exclusion_reason": "" if not pd.isna(known) else "FILING_TIMESTAMP_MISSING",
            "research_only": True,
            "notes": (
                "Occurrence evidence only; filing timestamp is not a pre-announced event date. "
                f"items={filing.get('items', '')}"
            ),
        })
    return pd.DataFrame(rows, columns=SEC_COLUMNS), manifest


def create_forward_template(root: Path, top20: pd.DataFrame, run_ts: pd.Timestamp) -> tuple[Path, bool]:
    directory = root / TOP20_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"top20_forward_risk_events_template_{run_ts:%Y%m%d}.csv"
    created = not path.exists()
    if created:
        pd.DataFrame([{
            "ticker": row["ticker"], "rank": row["rank"], "event_type": "",
            "event_name": "", "event_date": "", "event_time": "",
            "event_timezone": "America/New_York", "event_window_start": "",
            "event_window_end": "", "event_severity": "",
            "event_confidence": "", "source_name": "",
            "source_url_or_reference": "", "retrieval_timestamp_utc": "",
            "provider_available_date": "", "affected_sector": "",
            "sector_propagation_allowed": False, "source_notes": "",
            "operator_notes": "",
        } for _, row in top20.iterrows()]).to_csv(path, index=False)
    return path, created


def normalize_forward_manual(
    root: Path, top20: pd.DataFrame, run_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    validations = []
    certified = []
    rejected = []
    ranks = top20.set_index("ticker")["rank"].to_dict()
    required = {
        "ticker", "rank", "event_type", "event_name", "event_date",
        "retrieval_timestamp_utc",
    }
    for path in sorted((root / TOP20_DIR).glob("*.csv")):
        try:
            frame = pd.read_csv(path, low_memory=False)
        except Exception as exc:
            validations.append({"source_path": path.relative_to(root).as_posix(), "row_number": 0, "status": "FILE_READ_ERROR", "reason": type(exc).__name__})
            continue
        if not required.issubset(frame.columns):
            validations.append({"source_path": path.relative_to(root).as_posix(), "row_number": 0, "status": "FILE_SCHEMA_INVALID", "reason": "|".join(sorted(required - set(frame.columns)))})
            continue
        for index, row in frame.iterrows():
            # Blank template rows are placeholders, not rejected events.
            if not any(str(row.get(c, "")).strip() not in {"", "nan"} for c in ("event_type", "event_name", "event_date", "source_name")):
                continue
            ticker = str(row.get("ticker", "")).upper().strip()
            event_type = str(row.get("event_type", "")).strip()
            event_date = pd.to_datetime(row.get("event_date"), errors="coerce")
            retrieval = pd.to_datetime(row.get("retrieval_timestamp_utc"), utc=True, errors="coerce")
            provider = pd.to_datetime(row.get("provider_available_date"), utc=True, errors="coerce")
            known = provider if not pd.isna(provider) and (pd.isna(retrieval) or provider < retrieval) else retrieval
            reasons = []
            if ticker not in ranks:
                reasons.append("TICKER_NOT_CURRENT_TOP20")
            if event_type not in FORWARD_TYPES:
                reasons.append("INVALID_EVENT_TYPE")
            if pd.isna(event_date):
                reasons.append("EVENT_DATE_MISSING")
            if pd.isna(retrieval):
                reasons.append("RETRIEVAL_TIMESTAMP_MISSING")
            if not pd.isna(event_date) and event_date.date() > (run_ts + pd.Timedelta(days=93)).date():
                reasons.append("EVENT_OUTSIDE_THREE_MONTH_WINDOW")
            record = {
                "event_id": "V21_096_FWD_" + hashlib.sha256(
                    f"{path}|{index}|{ticker}|{event_type}|{event_date}".encode()
                ).hexdigest()[:20].upper(),
                "ticker": ticker, "rank": ranks.get(ticker, row.get("rank")),
                "event_type": event_type, "event_name": row.get("event_name", ""),
                "event_date": "" if pd.isna(event_date) else event_date.date().isoformat(),
                "event_time": row.get("event_time", ""),
                "event_timezone": row.get("event_timezone", "America/New_York"),
                "event_window_start": row.get("event_window_start", ""),
                "event_window_end": row.get("event_window_end", ""),
                "event_severity": row.get("event_severity", ""),
                "event_confidence": row.get("event_confidence", ""),
                "source_name": row.get("source_name", ""),
                "source_url_or_reference": row.get("source_url_or_reference", ""),
                "retrieval_timestamp_utc": "" if pd.isna(retrieval) else retrieval.isoformat(),
                "provider_available_date": "" if pd.isna(provider) else provider.isoformat(),
                "known_as_of_timestamp": "" if pd.isna(known) else known.isoformat(),
                "affected_sector": row.get("affected_sector", ""),
                "sector_propagation_allowed": truth(row.get("sector_propagation_allowed")),
                "historical_event_occurrence_usable": False,
                "historical_pre_event_calendar_usable": False,
                "forward_observation_usable": not reasons,
                "pit_certified": not reasons,
                "pit_exclusion_reason": "|".join(reasons),
                "research_only": True,
                "notes": f"{row.get('source_notes', '')} {row.get('operator_notes', '')}".strip(),
            }
            validations.append({"source_path": path.relative_to(root).as_posix(), "row_number": index + 2, "status": "CERTIFIED" if not reasons else "QUARANTINED", "reason": "|".join(reasons)})
            (certified if not reasons else rejected).append(record)
    return (
        pd.DataFrame(certified, columns=FORWARD_NORMALIZED_COLUMNS),
        pd.DataFrame(rejected, columns=FORWARD_NORMALIZED_COLUMNS),
        pd.DataFrame(validations, columns=["source_path", "row_number", "status", "reason"]),
    )


def observed(day: date) -> date:
    return day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=1) if day.weekday() == 6 else day


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    return current + timedelta(days=(weekday - current.weekday()) % 7 + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def easter(year: int) -> date:
    a = year % 19; b, c = divmod(year, 100); d, e = divmod(b, 4)
    f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7; m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, (h + l - 7 * m + 114) % 31 + 1)


def deterministic_market_events(run_ts: pd.Timestamp, end_date: date) -> list[dict[str, Any]]:
    rows = []
    current = run_ts.date()
    for year in {current.year, end_date.year}:
        for month in range(1, 13):
            day = nth_weekday(year, month, 4, 3)
            if current <= day <= end_date:
                quad = month in {3, 6, 9, 12}
                rows.append(("market_quad_witching" if quad else "market_opex", "Quarterly quadruple witching" if quad else "Monthly options expiration", day, "16:00:00", 60 if quad else 42))
        holidays = [
            (observed(date(year, 7, 4)), "Independence Day"),
            (nth_weekday(year, 9, 0, 1), "Labor Day"),
            (nth_weekday(year, 11, 3, 4), "Thanksgiving"),
            (observed(date(year, 12, 25)), "Christmas Day"),
            (observed(date(year, 1, 1)), "New Year's Day"),
            (nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
            (nth_weekday(year, 2, 0, 3), "Presidents Day"),
            (easter(year) - timedelta(days=2), "Good Friday"),
            (last_weekday(year, 5, 0), "Memorial Day"),
            (observed(date(year, 6, 19)), "Juneteenth"),
        ]
        for day, name in holidays:
            if current <= day <= end_date:
                rows.append(("holiday_liquidity", f"{name} market liquidity", day, "00:00:00", 52))
    return [{
        "event_type": event_type, "event_name": name, "event_date": day,
        "event_time": event_time, "severity": severity,
        "source_name": "Deterministic US market calendar rule",
        "source_url": "RULE_BASED_MARKET_CALENDAR",
        "confidence": "HIGH", "notes": "Rule-derived schedule; no price or return data used.",
    } for event_type, name, day, event_time, severity in sorted(set(rows), key=lambda x: x[2])]


def parse_official_tables(
    html: bytes, source_kind: str, current: date, end_date: date,
) -> list[dict[str, Any]]:
    events = []
    try:
        tables = pd.read_html(io.BytesIO(html))
    except Exception:
        tables = []
    patterns = {
        "bea": {
            "personal income and outlays": ("macro_pce", "Personal Income and Outlays / PCE release"),
            "gdp ": ("macro_gdp", "Gross Domestic Product release"),
        },
    }.get(source_kind, {})
    for table in tables:
        inferred_year = None
        for column in table.columns:
            match_year = re.search(r"20\d{2}", str(column))
            if match_year:
                inferred_year = int(match_year.group(0))
                break
        for _, row in table.iterrows():
            text = " | ".join(str(v) for v in row.tolist())
            lower = text.lower()
            if source_kind in {"bls_cpi", "bls_nfp"}:
                match = (
                    ("macro_cpi", "Consumer Price Index release")
                    if source_kind == "bls_cpi"
                    else ("macro_nfp", "Employment Situation / NFP release")
                )
            else:
                match = next((value for key, value in patterns.items() if key in lower), None)
            if not match:
                continue
            date_match = re.search(
                r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})|"
                r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
                r"(?:uary|ruary|ch|il|e|y|ust|tember|ober|ember|ember)?\.?)\s+"
                r"(\d{1,2}),?\s+(20\d{2})",
                text, re.I,
            )
            if not date_match:
                if inferred_year:
                    date_without_year = re.search(
                        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
                        r"(?:uary|ruary|ch|il|e|y|ust|tember|ober|ember|ember)?\.?)\s+"
                        r"(\d{1,2})", text, re.I,
                    )
                    parsed = pd.to_datetime(
                        f"{date_without_year.group(0)} {inferred_year}",
                        errors="coerce",
                    ) if date_without_year else pd.NaT
                else:
                    continue
            else:
                parsed = pd.to_datetime(date_match.group(0), errors="coerce")
            if pd.isna(parsed) or not current <= parsed.date() <= end_date:
                continue
            time_match = re.search(r"(\d{1,2}:\d{2})\s*(a\.m\.|p\.m\.|AM|PM)", text, re.I)
            events.append({
                "event_type": match[0], "event_name": match[1],
                "event_date": parsed.date(), "event_time": time_match.group(0) if time_match else "",
                "severity": 70, "confidence": "HIGH", "notes": "Parsed from official release schedule.",
            })
    return events


def parse_fomc(html: bytes, current: date, end_date: date) -> list[dict[str, Any]]:
    try:
        from bs4 import BeautifulSoup
        text = "\n".join(BeautifulSoup(html, "html.parser").stripped_strings)
    except Exception:
        text = re.sub(r"<[^>]+>", "\n", html.decode("utf-8", errors="ignore"))
    events = []
    month_map = {name: index for index, name in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], 1
    )}
    for year_match in re.finditer(r"(20\d{2}) FOMC Meetings", text):
        year = int(year_match.group(1))
        section_end = text.find(" FOMC Meetings", year_match.end())
        section = text[year_match.end():section_end if section_end > 0 else None]
        for month_name, month in month_map.items():
            for match in re.finditer(
                rf"{month_name}\s+(\d{{1,2}})(?:-(\d{{1,2}}))?\*?", section
            ):
                day = int(match.group(2) or match.group(1))
                meeting = date(year, month, day)
                if current <= meeting <= end_date:
                    events.append({
                        "event_type": "macro_fomc", "event_name": "FOMC meeting conclusion",
                        "event_date": meeting, "event_time": "14:00:00",
                        "severity": 85, "confidence": "HIGH",
                        "notes": "Parsed from Federal Reserve meeting calendar; time is standard statement time.",
                    })
    unique = {(e["event_date"], e["event_type"]): e for e in events}
    return list(unique.values())


def build_macro(
    root: Path, run_ts: pd.Timestamp, enable_network: bool, user_agent: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    current, end_date = run_ts.date(), (run_ts + pd.Timedelta(days=93)).date()
    source_specs = [
        ("fomc", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
        ("bls_cpi", "https://www.bls.gov/schedule/news_release/cpi.htm"),
        ("bls_nfp", "https://www.bls.gov/schedule/news_release/empsit.htm"),
        ("bea", "https://www.bea.gov/news/schedule"),
    ]
    raw_events = deterministic_market_events(run_ts, end_date)
    audit = [{
        "source_name": "Deterministic US market calendar rule",
        "source_url_or_reference": "RULE_BASED_MARKET_CALENDAR",
        "fetch_status": "DETERMINISTIC", "raw_payload_hash": "",
        "parsed_event_rows": len(raw_events), "retrieval_timestamp_utc": run_ts.isoformat(),
        "notes": "",
    }]
    for kind, url in source_specs:
        events = []
        status = "NETWORK_DISABLED"
        payload_hash = ""
        if enable_network:
            try:
                payload = fetch_bytes(url, user_agent)
                directory = root / RAW_MACRO / run_ts.date().isoformat()
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"{kind}.html"
                path.write_bytes(payload)
                payload_hash = sha256_bytes(payload)
                events = parse_fomc(payload, current, end_date) if kind == "fomc" else parse_official_tables(payload, kind, current, end_date)
                for event in events:
                    event["source_name"] = {
                        "fomc": "Federal Reserve",
                        "bls_cpi": "U.S. Bureau of Labor Statistics",
                        "bls_nfp": "U.S. Bureau of Labor Statistics",
                        "bea": "U.S. Bureau of Economic Analysis",
                    }[kind]
                    event["source_url"] = url
                status = "FETCHED_PARSED" if events else "FETCHED_NO_MATCHING_EVENTS"
                raw_events.extend(events)
            except Exception as exc:
                status = f"FETCH_FAILED:{type(exc).__name__}"
        audit.append({
            "source_name": kind.upper(), "source_url_or_reference": url,
            "fetch_status": status, "raw_payload_hash": payload_hash,
            "parsed_event_rows": len(events), "retrieval_timestamp_utc": run_ts.isoformat(),
            "notes": "Official schedule dates only; release values not ingested.",
        })
    rows = []
    for event in raw_events:
        known = run_ts
        rows.append({
            "event_id": "V21_096_MACRO_" + hashlib.sha256(
                f"{event['event_type']}|{event['event_date']}|{event['source_name']}".encode()
            ).hexdigest()[:20].upper(),
            "event_type": event["event_type"], "event_name": event["event_name"],
            "event_date": event["event_date"].isoformat(),
            "event_time": event["event_time"], "event_timezone": "America/New_York",
            "affected_ticker": "ALL", "affected_sector": "ALL",
            "source_name": event["source_name"],
            "source_url_or_reference": event["source_url"],
            "retrieval_timestamp_utc": run_ts.isoformat(),
            "known_as_of_timestamp": known.isoformat(),
            "event_severity": event["severity"],
            "event_confidence": event["confidence"],
            "historical_event_occurrence_usable": False,
            "historical_pre_event_calendar_usable": False,
            "forward_observation_usable": True, "pit_certified": True,
            "research_only": True, "notes": event["notes"],
        })
    return pd.DataFrame(rows, columns=MACRO_COLUMNS).drop_duplicates("event_id"), pd.DataFrame(audit)


def canonical_merge(
    base: pd.DataFrame, sec: pd.DataFrame, forward: pd.DataFrame, macro: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "event_id", "event_type", "event_name", "event_date", "event_time",
        "event_timezone", "ticker", "affected_sector", "known_as_of_timestamp",
        "retrieval_timestamp_utc", "source_name", "source_url_or_reference",
        "historical_event_occurrence_usable",
        "historical_pre_event_calendar_usable", "forward_observation_usable",
        "pit_certified", "pit_exclusion_reason", "research_only", "notes",
        "source_branch",
    ]
    parts = []
    if not base.empty:
        parts.append(pd.DataFrame({
            "event_id": base["event_id"], "event_type": base["event_type"],
            "event_name": base["event_name"], "event_date": base["event_date"],
            "event_time": base["event_time"], "event_timezone": base["event_timezone"],
            "ticker": base["affected_ticker"], "affected_sector": base["affected_sector"],
            "known_as_of_timestamp": base["known_as_of_timestamp"],
            "retrieval_timestamp_utc": base["retrieval_timestamp_utc"],
            "source_name": base["source_name"],
            "source_url_or_reference": base["source_url_or_provider"],
            "historical_event_occurrence_usable": base["historical_backtest_usable"].map(truth),
            "historical_pre_event_calendar_usable": base["historical_backtest_usable"].map(truth),
            "forward_observation_usable": base["forward_usable"].map(truth),
            "pit_certified": base["pit_certified"].map(truth),
            "pit_exclusion_reason": base["pit_exclusion_reason"],
            "research_only": True, "notes": base["notes"],
            "source_branch": "V21_095_BASE",
        }))
    if not sec.empty:
        temp = sec.rename(columns={"source_url_or_reference": "_source"}) if False else sec
        parts.append(pd.DataFrame({
            **{c: temp[c] for c in [
                "event_id", "event_type", "event_name", "event_date", "event_time",
                "event_timezone", "known_as_of_timestamp", "retrieval_timestamp_utc",
                "source_name", "source_url_or_reference",
                "historical_event_occurrence_usable",
                "historical_pre_event_calendar_usable", "forward_observation_usable",
                "pit_certified", "pit_exclusion_reason", "research_only", "notes",
            ]},
            "ticker": temp["ticker"], "affected_sector": "",
            "source_branch": "TOP50_SEC_OCCURRENCE",
        }))
    if not forward.empty:
        parts.append(pd.DataFrame({
            **{c: forward[c] for c in [
                "event_id", "event_type", "event_name", "event_date", "event_time",
                "event_timezone", "known_as_of_timestamp", "retrieval_timestamp_utc",
                "source_name", "source_url_or_reference",
                "historical_event_occurrence_usable",
                "historical_pre_event_calendar_usable", "forward_observation_usable",
                "pit_certified", "pit_exclusion_reason", "research_only", "notes",
            ]},
            "ticker": forward["ticker"], "affected_sector": forward["affected_sector"],
            "source_branch": "TOP20_FORWARD_MANUAL",
        }))
    if not macro.empty:
        parts.append(pd.DataFrame({
            "event_id": macro["event_id"], "event_type": macro["event_type"],
            "event_name": macro["event_name"], "event_date": macro["event_date"],
            "event_time": macro["event_time"], "event_timezone": macro["event_timezone"],
            "ticker": macro["affected_ticker"], "affected_sector": macro["affected_sector"],
            "known_as_of_timestamp": macro["known_as_of_timestamp"],
            "retrieval_timestamp_utc": macro["retrieval_timestamp_utc"],
            "source_name": macro["source_name"],
            "source_url_or_reference": macro["source_url_or_reference"],
            "historical_event_occurrence_usable": macro["historical_event_occurrence_usable"],
            "historical_pre_event_calendar_usable": macro["historical_pre_event_calendar_usable"],
            "forward_observation_usable": macro["forward_observation_usable"],
            "pit_certified": macro["pit_certified"],
            "pit_exclusion_reason": "",
            "research_only": True, "notes": macro["notes"],
            "source_branch": "OFFICIAL_MACRO_MARKET",
        }))
    merged = pd.concat(parts, ignore_index=True)[columns] if parts else pd.DataFrame(columns=columns)
    merged = merged.drop_duplicates("event_id", keep="last")
    usage = pd.DataFrame({
        "event_id": merged["event_id"], "event_type": merged["event_type"],
        "ticker": merged["ticker"],
        "historical_event_occurrence_usable": merged["historical_event_occurrence_usable"].map(truth),
        "historical_pre_event_calendar_usable": merged["historical_pre_event_calendar_usable"].map(truth),
        "forward_observation_usable": merged["forward_observation_usable"].map(truth),
    })
    usage["allowed_for_historical_random_retest"] = usage["historical_pre_event_calendar_usable"]
    usage["allowed_for_forward_observation"] = usage["forward_observation_usable"]
    usage["allowed_for_entry_throttle_research"] = usage["forward_observation_usable"]
    usage["allowed_for_exposure_overlay_research"] = (
        usage["historical_event_occurrence_usable"] | usage["forward_observation_usable"]
    )
    usage["notes"] = np.where(
        usage["historical_event_occurrence_usable"] & ~usage["historical_pre_event_calendar_usable"],
        "Occurrence research only; not pre-event avoidance evidence.",
        "Usage follows certified timestamp policy.",
    )
    return merged, usage


def run(root: Path, enable_network: bool, sec_user_agent: str) -> dict[str, Any]:
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUTS}
    before = protected_snapshot(root, output_paths)
    d_hash_before = sha256(root / D_REL) if (root / D_REL).is_file() else ""
    run_ts = pd.Timestamp(datetime.now(timezone.utc))
    user_agent = sec_user_agent.strip() or "us-tech-quant-research/21.096 research-only"

    top50, top20, as_of = extract_universe(root)
    top50.to_csv(out / OUTPUTS[0], index=False)
    top20.to_csv(out / OUTPUTS[1], index=False)

    mapping, mapping_audit = build_cik_mapping(root, top50, enable_network, user_agent, run_ts)
    mapping.to_csv(out / OUTPUTS[2], index=False)
    mapped = mapping[mapping["usable_for_sec_fetch"].map(truth)]
    top50_coverage = len(set(mapped["ticker"]) & set(top50["ticker"])) / len(top50) if len(top50) else 0
    top20_coverage = len(set(mapped["ticker"]) & set(top20["ticker"])) / len(top20) if len(top20) else 0
    r2 = {
        "status": "PASS", "top50_mapping_coverage_ratio": top50_coverage,
        "top20_mapping_coverage_ratio": top20_coverage,
        "duplicate_ticker_count": int(mapping.duplicated("ticker").sum()),
        "duplicate_cik_count": int(mapped.duplicated("cik").sum()),
        "missing_cik_count": int((~mapping["usable_for_sec_fetch"].map(truth)).sum()),
        "network_enabled": enable_network, "mapping_source_audit": mapping_audit,
        "research_only": True, "official_adoption_allowed": False,
    }
    write_json(out / OUTPUTS[3], r2)
    (out / OUTPUTS[4]).write_text(markdown(
        "V21.096-R2 Ticker-CIK Mapping", r2,
        "Missing CIK rows remain quarantined and are not sent to SEC.",
    ), encoding="utf-8")

    lookback = run_ts - pd.Timedelta(days=730)
    sec_parts, sec_manifest_rows = [], []
    for _, row in mapped.iterrows():
        events, manifest = sec_events_for_ticker(
            root, row["ticker"], row["cik"], run_ts, lookback,
            user_agent, enable_network,
        )
        if not events.empty:
            sec_parts.append(events)
        sec_manifest_rows.extend(manifest)
    sec = pd.concat(sec_parts, ignore_index=True) if sec_parts else pd.DataFrame(columns=SEC_COLUMNS)
    sec_manifest = pd.DataFrame(sec_manifest_rows)
    sec_manifest.to_csv(out / OUTPUTS[5], index=False)
    sec.to_csv(out / OUTPUTS[6], index=False)
    sec.to_csv(out / OUTPUTS[7], index=False)
    r3 = {
        "status": "PASS", "mapped_tickers_attempted": len(mapped),
        "successful_ticker_fetches": int(sec_manifest["fetch_status"].isin(["NETWORK_FETCHED", "LOCAL_SNAPSHOT_REUSED"]).sum()) if not sec_manifest.empty else 0,
        "filing_rows": len(sec), "certified_occurrence_rows": int(sec["pit_certified"].map(truth).sum()) if not sec.empty else 0,
        "historical_pre_event_calendar_rows": int(sec["historical_pre_event_calendar_usable"].map(truth).sum()) if not sec.empty else 0,
        "lookback_start": lookback.date().isoformat(), "lookback_end": run_ts.date().isoformat(),
        "post_event_values_or_prices_used": False, "research_only": True,
    }
    write_json(out / OUTPUTS[8], r3)
    (out / OUTPUTS[9]).write_text(markdown(
        "V21.096-R3 Top50 SEC Event Occurrence Report", r3,
        "SEC filing timestamps certify event occurrence only. They are not pre-announced earnings calendar dates.",
    ), encoding="utf-8")

    template, created = create_forward_template(root, top20, run_ts)
    forward, forward_rejected, forward_validation = normalize_forward_manual(root, top20, run_ts)
    pd.DataFrame([{
        "template_path": template.relative_to(root).as_posix(),
        "created_this_run": created, "template_rows": len(top20),
        "template_hash": sha256(template), "run_timestamp_utc": run_ts.isoformat(),
        "research_only": True,
    }]).to_csv(out / OUTPUTS[10], index=False)
    forward_validation.to_csv(out / OUTPUTS[11], index=False)
    forward.to_csv(out / OUTPUTS[12], index=False)
    forward_rejected.to_csv(out / OUTPUTS[13], index=False)

    macro, macro_audit = build_macro(root, run_ts, enable_network, user_agent)
    macro.to_csv(out / OUTPUTS[14], index=False)
    macro_audit.to_csv(out / OUTPUTS[15], index=False)
    (out / OUTPUTS[16]).write_text(markdown(
        "V21.096-R5 Official Macro and Market Event Report",
        {"certified_rows": len(macro), "source_count": len(macro_audit),
         "network_enabled": enable_network, "research_only": True},
        "Official schedule rows use retrieval time as known-as-of unless an earlier publication timestamp is certified.",
    ), encoding="utf-8")

    base = pd.read_csv(root / BASE_EVENT_REL, low_memory=False) if (root / BASE_EVENT_REL).is_file() else pd.DataFrame()
    master, usage = canonical_merge(base, sec, forward, macro)
    master.to_csv(out / OUTPUTS[17], index=False)
    top50_counts = master[master["ticker"].isin(set(top50["ticker"]))].groupby("ticker").agg(
        event_rows=("event_id", "count"),
        occurrence_rows=("historical_event_occurrence_usable", lambda s: int(s.map(truth).sum())),
        forward_rows=("forward_observation_usable", lambda s: int(s.map(truth).sum())),
        event_types=("event_type", lambda s: "|".join(sorted(set(s)))),
    ).reset_index()
    top50_cov = top50[["rank", "ticker"]].merge(top50_counts, on="ticker", how="left")
    top50_cov["event_rows"] = top50_cov["event_rows"].fillna(0).astype(int)
    top50_cov.to_csv(out / OUTPUTS[18], index=False)
    top20_counts = master[master["ticker"].isin(set(top20["ticker"]))].groupby("ticker").agg(
        event_rows=("event_id", "count"),
        forward_rows=("forward_observation_usable", lambda s: int(s.map(truth).sum())),
        event_types=("event_type", lambda s: "|".join(sorted(set(s)))),
    ).reset_index()
    top20_cov = top20[["rank", "ticker"]].merge(top20_counts, on="ticker", how="left")
    top20_cov["event_rows"] = top20_cov["event_rows"].fillna(0).astype(int)
    top20_cov.to_csv(out / OUTPUTS[19], index=False)
    master.groupby("event_type").agg(
        event_rows=("event_id", "count"),
        occurrence_rows=("historical_event_occurrence_usable", lambda s: int(s.map(truth).sum())),
        pre_event_rows=("historical_pre_event_calendar_usable", lambda s: int(s.map(truth).sum())),
        forward_rows=("forward_observation_usable", lambda s: int(s.map(truth).sum())),
        ticker_count=("ticker", lambda s: s[~s.isin(["", "ALL"])].nunique()),
    ).reset_index().to_csv(out / OUTPUTS[20], index=False)
    audit = master.copy()
    audit["known_timestamp_parseable"] = pd.to_datetime(
        audit["known_as_of_timestamp"], utc=True, errors="coerce", format="mixed"
    ).notna()
    audit["pit_leakage_warning"] = (
        audit["pit_certified"].map(truth) & ~audit["known_timestamp_parseable"]
    )
    audit.to_csv(out / OUTPUTS[21], index=False)
    usage.to_csv(out / OUTPUTS[22], index=False)
    rejected = pd.concat([
        forward_rejected.assign(rejection_branch="TOP20_FORWARD"),
    ], ignore_index=True) if not forward_rejected.empty else pd.DataFrame(
        columns=[*FORWARD_NORMALIZED_COLUMNS, "rejection_branch"]
    )
    rejected.to_csv(out / OUTPUTS[23], index=False)

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_preserved = (root / D_REL).is_file() and sha256(root / D_REL) == d_hash_before
    official_changed = [p for p in changed if "official" in p.lower() or "broker" in p.lower()]
    warnings = int(audit["pit_leakage_warning"].sum())
    sec_certified = int(sec["pit_certified"].map(truth).sum()) if not sec.empty else 0
    sec_earnings = int(sec["event_type"].eq("ticker_earnings_occurrence").sum()) if not sec.empty else 0
    top50_event_coverage = top50_cov["event_rows"].gt(0).mean() if len(top50_cov) else 0
    top20_forward_coverage = (
        len(set(forward["ticker"]) & set(top20["ticker"])) / len(top20)
        if len(top20) else 0
    )
    if not len(top50):
        decision = "D_TOP50_SOURCE_NOT_FOUND"
    elif warnings:
        decision = "REJECT_EVENT_LEDGER_DUE_TO_PIT_LEAKAGE"
    elif changed or not d_preserved:
        decision = "REJECT_EVENT_LEDGER_DUE_TO_PROTECTED_MUTATION"
    elif top50_coverage < 0.80:
        decision = "TOP50_CIK_MAPPING_INSUFFICIENT"
    elif sec_certified > 0 and len(forward) > 0:
        decision = "TOP50_HISTORICAL_AND_TOP20_FORWARD_EVENTS_READY_FOR_OBSERVATION"
    elif sec_certified > 0 and len(macro) > 0:
        decision = "HISTORICAL_AND_MACRO_EVENTS_READY_TOP20_FORWARD_REQUIRED"
    elif sec_certified > 0:
        decision = "TOP50_HISTORICAL_EVENTS_READY_TOP20_FORWARD_FILL_REQUIRED"
    else:
        decision = "TOP50_CIK_MAPPING_INSUFFICIENT"
    summary = {
        "FINAL_STATUS": "PASS" if not warnings and not changed and d_preserved and len(top50) else "FAIL",
        "DECISION": decision, "D_TOP50_TICKERS_FOUND": len(top50),
        "D_TOP20_TICKERS_FOUND": len(top20),
        "TOP50_CIK_MAPPING_COVERAGE_RATIO": top50_coverage,
        "TOP50_SEC_FILINGS_FETCHED": len(sec),
        "TOP50_HISTORICAL_EVENT_ROWS_CERTIFIED": sec_certified,
        "TOP50_HISTORICAL_EARNINGS_OCCURRENCE_ROWS": sec_earnings,
        "TOP20_FORWARD_MANUAL_ROWS_FOUND": int((forward_validation["status"].isin(["CERTIFIED", "QUARANTINED"])).sum()) if not forward_validation.empty else 0,
        "TOP20_FORWARD_MANUAL_ROWS_CERTIFIED": len(forward),
        "OFFICIAL_MACRO_EVENT_ROWS_CERTIFIED": int(macro["pit_certified"].map(truth).sum()),
        "CERTIFIED_EVENT_ROWS_TOTAL": int(master["pit_certified"].map(truth).sum()),
        "CERTIFIED_EVENT_ROWS_NEW": sec_certified + len(forward) + len(macro),
        "TOP50_EVENT_COVERAGE_RATIO": float(top50_event_coverage),
        "TOP20_FORWARD_EVENT_COVERAGE_RATIO": float(top20_forward_coverage),
        "HISTORICAL_EVENT_OCCURRENCE_OBSERVATION_ALLOWED": sec_certified > 0,
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED": False,
        "FORWARD_EVENT_OBSERVATION_ALLOWED": bool(len(forward) or len(macro)),
        "PIT_LEAKAGE_WARNINGS": warnings,
        "PROTECTED_OUTPUTS_MODIFIED": bool(changed or not d_preserved),
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "D_BASELINE_PRESERVED": d_preserved,
        "RECOMMENDED_NEXT_STAGE": (
            "FILL_TOP20_FORWARD_EVENT_TEMPLATE"
            if len(forward) == 0 else "V21.097_EVENT_OCCURRENCE_AND_FORWARD_OBSERVATION"
        ),
    }
    write_json(out / OUTPUTS[25], summary)
    (out / OUTPUTS[24]).write_text(markdown(
        "V21.096 Top50 Historical and Top20 Forward Event Ledger", summary,
        "No event penalties, price-derived labels, or adoption logic were executed.",
    ), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--enable-network", action="store_true")
    parser.add_argument("--sec-user-agent", default=os.environ.get("SEC_USER_AGENT", ""))
    args = parser.parse_args()
    summary = run(args.root.resolve(), args.enable_network, args.sec_user_agent)
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    import os
    raise SystemExit(main())
