from __future__ import annotations

import calendar
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .acquisition import RawDocument, sha256_file


NY = ZoneInfo("America/New_York")
UTC = timezone.utc
FORBIDDEN_VALUE_COLUMNS = {
    "y_primary", "y_5m", "y_10m", "y_15m", "y_30m", "y_60m", "payoff",
    "trade_return", "win", "loss", "severe_loss_target", "oof_model_results",
    "prospective_outcomes"
}
BLS_CALENDAR_COLUMNS = [
    "event_family", "reference_period", "release_date", "release_time_et",
    "timezone", "source_url", "source_year", "source_type", "quality_flag",
]
BLS_ALLOWED_CALENDAR_FAMILIES = {"CPI", "PPI", "EMPLOYMENT_SITUATION"}
BLS_OFFICIAL_SCHEDULE_URLS = {
    year: f"https://www.bls.gov/schedule/{year}/home.htm" for year in range(2020, 2026)
}
BLS_API_VALUE_COLUMNS = [
    "series_id", "event_family", "event_type", "reference_period", "value", "units",
    "seasonal_adjustment", "retrieval_timestamp", "source", "revision_status",
]
ARCHIVE_COLUMNS = [
    "event_id", "event_family", "event_type", "reference_period", "scheduled_time_utc",
    "actual_release_time_utc", "information_available_time_utc", "first_release_value",
    "previous_known_value", "revised_value", "revision_available_time_utc", "units", "source",
    "source_reference", "source_document_id", "retrieval_timestamp_utc", "source_timezone",
    "quality_flags"
]


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def stable_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def contract_sha256(contract: dict[str, Any]) -> str:
    return hashlib.sha256(stable_json_bytes(contract)).hexdigest()


def write_immutable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"FROZEN_FAST_ARTIFACT_MUTATION: {path}")
        return
    path.write_bytes(data)


def parse_source_datetime(date_text: str, time_text: str, source_timezone: str = "America/New_York") -> datetime:
    clean_date = re.sub(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*", "", date_text.strip(), flags=re.I)
    clean_date = clean_date.replace("Sept ", "Sep ")
    parsed_date: date | None = None
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            parsed_date = datetime.strptime(clean_date, fmt).date()
            break
        except ValueError:
            continue
    if parsed_date is None:
        raise ValueError(f"unrecognized date: {date_text}")
    parsed_time = datetime.strptime(time_text.strip().upper().replace(".", ""), "%I:%M %p").time()
    return datetime.combine(parsed_date, parsed_time, ZoneInfo(source_timezone)).astimezone(UTC)


def normalize_reference_period(value: str) -> str:
    text = " ".join(str(value).strip().split())
    direct = re.fullmatch(r"(20\d{2})-(0[1-9]|1[0-2])", text)
    if direct:
        return text
    api_style = re.fullmatch(r"(20\d{2})[- ]?M(0[1-9]|1[0-2])", text, re.I)
    if api_style:
        return f"{api_style.group(1)}-{api_style.group(2)}"
    for fmt in ("%B %Y", "%b %Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return f"{parsed.year:04d}-{parsed.month:02d}"
        except ValueError:
            continue
    raise ValueError(f"invalid reference_period: {value}")


def load_bls_static_calendar(config: dict[str, Any], path_override: Path | None = None) -> tuple[pd.DataFrame, str]:
    path = path_override or Path(config["bls_static_calendar_path"])
    if not path.exists():
        return pd.DataFrame(columns=BLS_CALENDAR_COLUMNS + ["reference_period_normalized", "information_available_time_utc"]), "WAITING_FOR_STATIC_OFFICIAL_CALENDAR"
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(frame.columns) != BLS_CALENDAR_COLUMNS:
        raise RuntimeError(f"BLS_STATIC_CALENDAR_SCHEMA_INVALID: expected {BLS_CALENDAR_COLUMNS}, got {list(frame.columns)}")
    if not set(frame["event_family"]).issubset(BLS_ALLOWED_CALENDAR_FAMILIES):
        raise RuntimeError("BLS_STATIC_CALENDAR_FAMILY_INVALID")
    if set(frame["timezone"]) != {"America/New_York"}:
        raise RuntimeError("BLS_STATIC_CALENDAR_TIMEZONE_INVALID")
    if set(frame["source_type"]) != {"BLS_OFFICIAL_HISTORICAL_RELEASE_CALENDAR"}:
        raise RuntimeError("BLS_STATIC_CALENDAR_SOURCE_TYPE_INVALID")
    if set(frame["quality_flag"]) != {"OFFICIAL_VERIFIED"}:
        raise RuntimeError("BLS_STATIC_CALENDAR_QUALITY_FLAG_INVALID")
    source_year = pd.to_numeric(frame["source_year"], errors="raise").astype(int)
    expected_urls = source_year.map(BLS_OFFICIAL_SCHEDULE_URLS)
    if expected_urls.isna().any() or not (frame["source_url"] == expected_urls).all():
        raise RuntimeError("BLS_STATIC_CALENDAR_SOURCE_URL_INVALID")
    frame["reference_period_normalized"] = frame["reference_period"].map(normalize_reference_period)
    if frame.duplicated(["event_family", "reference_period_normalized"]).any():
        raise RuntimeError("BLS_STATIC_CALENDAR_REFERENCE_PERIOD_DUPLICATE")
    release_dates = pd.to_datetime(frame["release_date"], format="%Y-%m-%d", errors="raise")
    if not (release_dates.dt.year == source_year).all():
        raise RuntimeError("BLS_STATIC_CALENDAR_SOURCE_YEAR_MISMATCH")
    available: list[str] = []
    for row in frame.itertuples(index=False):
        if not re.fullmatch(r"\d{1,2}:\d{2}\s+[AP]M", row.release_time_et.strip().upper()):
            raise RuntimeError("BLS_STATIC_CALENDAR_RELEASE_TIME_INVALID")
        available.append(iso_utc(parse_source_datetime(row.release_date, row.release_time_et, row.timezone)))
    frame["information_available_time_utc"] = available
    return frame, "AVAILABLE_OFFICIAL_VERIFIED"


def normalize_bls_api_values(config: dict[str, Any], documents: Iterable[RawDocument]) -> tuple[pd.DataFrame, str]:
    api_doc = next((d for d in documents if d.document_kind == "bls_api_values"), None)
    empty = pd.DataFrame(columns=BLS_API_VALUE_COLUMNS)
    if api_doc is None or api_doc.status == "FAILED" or not api_doc.local_path:
        return empty, "UNAVAILABLE"
    payload = json.loads(Path(api_doc.local_path).read_text(encoding="utf-8"))
    if payload.get("status") != "REQUEST_SUCCEEDED":
        return empty, "API_RESPONSE_FAILED"
    specs = config["bls_api"]["series"]
    rows: list[dict[str, str]] = []
    seen_series: set[str] = set()
    for series in payload.get("Results", {}).get("series", []):
        series_id = series.get("seriesID")
        if series_id not in specs:
            raise RuntimeError(f"BLS_API_UNREGISTERED_SERIES: {series_id}")
        seen_series.add(series_id)
        spec = specs[series_id]
        for observation in series.get("data", []):
            period = str(observation.get("period", ""))
            if not re.fullmatch(r"M(0[1-9]|1[0-2])", period):
                continue
            reference = f"{observation['year']}-{period[1:]}"
            rows.append({
                "series_id": series_id, "event_family": spec["event_family"],
                "event_type": spec["event_type"], "reference_period": reference,
                "value": str(observation.get("value", "")), "units": spec["units"],
                "seasonal_adjustment": spec["seasonal_adjustment"],
                "retrieval_timestamp": api_doc.retrieval_timestamp_utc,
                "source": api_doc.source_reference, "revision_status": spec["revision_status"],
            })
    if seen_series != set(specs):
        return pd.DataFrame(rows, columns=BLS_API_VALUE_COLUMNS), "PARTIAL_SERIES_RESPONSE"
    frame = pd.DataFrame(rows, columns=BLS_API_VALUE_COLUMNS)
    if frame.duplicated(["series_id", "reference_period"]).any():
        raise RuntimeError("BLS_API_DUPLICATE_SERIES_REFERENCE_PERIOD")
    return frame.sort_values(["reference_period", "series_id"]).reset_index(drop=True), "AVAILABLE"


def join_bls_calendar_values(
    config: dict[str, Any], calendar_frame: pd.DataFrame, api_values: pd.DataFrame
) -> tuple[pd.DataFrame, str]:
    if calendar_frame.empty:
        return pd.DataFrame(columns=ARCHIVE_COLUMNS), "WAITING_FOR_STATIC_OFFICIAL_CALENDAR"
    archive_start = date.fromisoformat(config["archive_start"])
    archive_end = date.fromisoformat(config["archive_end"])
    calendar_relevant = calendar_frame.loc[
        (pd.to_datetime(calendar_frame["release_date"], errors="raise").dt.date >= archive_start)
        & (pd.to_datetime(calendar_frame["release_date"], errors="raise").dt.date <= archive_end)
    ].copy()
    expected: list[dict[str, Any]] = []
    for cal in calendar_relevant.to_dict("records"):
        for series_id, series_spec in config["bls_api"]["series"].items():
            if series_spec["event_family"] == cal["event_family"]:
                expected.append({
                    **cal, "series_id": series_id, "event_type": series_spec["event_type"],
                    "event_family_api_key": series_spec["event_family"],
                    "reference_period_api_key": cal["reference_period_normalized"],
                })
    if not expected:
        return pd.DataFrame(columns=ARCHIVE_COLUMNS), "NO_API_CALENDAR_OVERLAP"
    expected_frame = pd.DataFrame(expected)
    relevant = expected_frame.merge(
        api_values,
        left_on=["series_id", "event_family_api_key", "event_type", "reference_period_api_key"],
        right_on=["series_id", "event_family", "event_type", "reference_period"],
        how="left", validate="one_to_one", indicator=True, suffixes=("_calendar", "_api"),
    )
    if not (relevant["_merge"] == "both").all():
        return pd.DataFrame(columns=ARCHIVE_COLUMNS), "INCOMPLETE_API_CALENDAR_JOIN"
    rows: list[dict[str, Any]] = []
    family_map = {"EMPLOYMENT_SITUATION": "EMPLOYMENT_NFP", "CPI": "CPI", "PPI": "PPI"}
    for row in relevant.itertuples(index=False):
        available = datetime.fromisoformat(row.information_available_time_utc.replace("Z", "+00:00"))
        flags = ["BLS_API_CALENDAR_JOINED", row.quality_flag, row.revision_status]
        if row.revision_status != "FIRST_RELEASE_SAFE":
            flags.append("CURRENT_API_VALUE_RETAINED_NOT_EXPOSED")
        record = _base_record(
            family_map[row.event_family_calendar], row.event_type, row.reference_period_api,
            available, available, available, "U.S. Bureau of Labor Statistics",
            row.source_url, None, row.retrieval_timestamp, flags,
        )
        record["units"] = row.units
        if row.revision_status == "FIRST_RELEASE_SAFE":
            record["first_release_value"] = row.value
        rows.append(record)
    frame = pd.DataFrame(rows, columns=ARCHIVE_COLUMNS)
    return frame.sort_values(["scheduled_time_utc", "event_family", "event_type"]).reset_index(drop=True), "PASS_ONE_CALENDAR_ROW_PER_API_VALUE"


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("naive datetime forbidden")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _reference_period(label: str) -> str | None:
    match = re.search(r"\bfor\s+(.+?)(?:\s*\(|$)", label, re.I)
    return match.group(1).strip() if match else None


def _event_id(family: str, event_type: str, reference: str | None, scheduled: str | None, source_ref: str) -> str:
    # Provenance is deliberately excluded: mirrored/indexed copies of one economic
    # release must resolve to one canonical identity.
    identity = "|".join([family, event_type, reference or "", scheduled or ""])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _base_record(
    family: str, event_type: str, reference: str | None, scheduled: datetime | None,
    actual: datetime | None, available: datetime | None, source: str, source_ref: str,
    doc_hash: str | None, retrieved: str | None, flags: list[str]
) -> dict[str, Any]:
    scheduled_iso, actual_iso, available_iso = iso_utc(scheduled), iso_utc(actual), iso_utc(available)
    return {
        "event_id": _event_id(family, event_type, reference, scheduled_iso, source_ref),
        "event_family": family, "event_type": event_type, "reference_period": reference,
        "scheduled_time_utc": scheduled_iso, "actual_release_time_utc": actual_iso,
        "information_available_time_utc": available_iso, "first_release_value": None,
        "previous_known_value": None, "revised_value": None, "revision_available_time_utc": None,
        "units": None, "source": source, "source_reference": source_ref,
        "source_document_id": doc_hash, "retrieval_timestamp_utc": retrieved,
        "source_timezone": "America/New_York", "quality_flags": json.dumps(sorted(set(flags)))
    }


def parse_bls_calendar(doc: RawDocument, spec: dict[str, Any], start: date, end: date) -> list[dict[str, Any]]:
    if not doc.local_path:
        return []
    text = Path(doc.local_path).read_bytes().decode("utf-8", errors="replace")
    parser = TableParser()
    parser.feed(text)
    records: list[dict[str, Any]] = []
    label = spec["release_label"].lower()
    for row in parser.rows:
        if len(row) < 3 or label not in row[-1].lower():
            continue
        try:
            scheduled = parse_source_datetime(row[0], row[1])
        except ValueError:
            continue
        if not (start <= scheduled.date() <= end):
            continue
        reference = _reference_period(row[-1])
        for event_type in spec["event_types"]:
            records.append(_base_record(
                next(k for k, v in EVENT_SPECS.items() if v is spec), event_type, reference,
                scheduled, None, None, spec["source"], doc.source_reference, doc.sha256,
                doc.retrieval_timestamp_utc, ["SCHEDULE_ONLY", "ACTUAL_VALUE_UNRESOLVED", "REVISION_UNRESOLVED"]
            ))
    return records


def _visible_text(raw: str) -> str:
    clean = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw)
    clean = re.sub(r"(?s)<[^>]+>", " ", clean)
    return " ".join(clean.replace("&nbsp;", " ").replace("&amp;", "&").split())


def _release_datetime(text: str) -> datetime | None:
    date_match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b", text)
    time_match = re.search(r"For release at\s+(\d{1,2}:\d{2})\s*([ap]\.?m\.?)\s*(E[DS]T|ET)?", text, re.I)
    if not date_match or not time_match:
        return None
    return parse_source_datetime(date_match.group(0), f"{time_match.group(1)} {time_match.group(2)}")


def _bea_release_datetime(text: str) -> datetime | None:
    match = re.search(
        r"EMBARGOED\s+UNTIL\s+RELEASE\s+AT\s+(\d{1,2}:\d{2})\s*([ap]\.?m\.?)\s*"
        r"(EST|EDT|ET),?\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s*(20\d{2})",
        text, re.I,
    )
    if not match:
        return None
    date_text = f"{match.group(4)} {match.group(5)}, {match.group(6)}"
    parsed = parse_source_datetime(date_text, f"{match.group(1)} {match.group(2)}")
    abbreviation = match.group(3).upper()
    local = parsed.astimezone(NY)
    if abbreviation == "EST" and local.utcoffset().total_seconds() != -5 * 3600:
        return None
    if abbreviation == "EDT" and local.utcoffset().total_seconds() != -4 * 3600:
        return None
    return parsed


def _bea_reference_period(text: str, family: str) -> str | None:
    if family == "PCE":
        match = re.search(
            r"Personal Income and Outlays,\s*"
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})",
            text, re.I,
        )
        if not match:
            return None
        month_number = list(calendar.month_name).index(match.group(1).title())
        return f"{match.group(2)}-{month_number:02d}"
    match = re.search(
        r"Gross Domestic Product,.*?\b(First|Second|Third|Fourth|1st|2nd|3rd|4th)\s+Quarter.*?\b(20\d{2})\b",
        text, re.I,
    )
    if not match:
        return None
    quarter_map = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}
    return f"{match.group(2)}-Q{quarter_map[match.group(1).lower()]}"


def _bea_gdp_vintage(text: str) -> str:
    title = re.search(r"Gross Domestic Product,.*?(?:\n|Real gross domestic product)", text, re.I)
    scope = title.group(0) if title else text[:1500]
    if re.search(r"\bAdvance Estimate\b", scope, re.I):
        return "ADVANCE_ESTIMATE"
    if re.search(r"\bSecond Estimate\b", scope, re.I):
        return "SECOND_ESTIMATE"
    if re.search(r"\bThird Estimate\b", scope, re.I):
        return "THIRD_ESTIMATE"
    return "UNKNOWN_GDP_VINTAGE"


def _extract_signed_percent(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    verb, number = match.group(1).lower(), match.group(2)
    value = float(number.replace(",", ""))
    if verb in {"decreased", "declined", "fell"}:
        value = -abs(value)
    rendered = f"{value:.12g}"
    return rendered


def _number(text: str) -> str:
    return text.replace(",", "").strip()


def _apply_release_values(records: list[dict[str, Any]], text: str, family: str) -> None:
    patterns: dict[str, tuple[str, str]] = {}
    if family == "CPI":
        patterns = {
            "CPI": (r"Consumer Price Index.*?(?:increased|rose|decreased|fell)\s+(-?\d+(?:\.\d+)?)\s+percent", "PERCENT_MOM_SA"),
            "CORE_CPI": (r"all items less food and energy.*?(?:increased|rose|decreased|fell)\s+(-?\d+(?:\.\d+)?)\s+percent", "PERCENT_MOM_SA")
        }
    elif family == "PPI":
        patterns = {"PPI": (r"final demand.*?(?:increased|rose|decreased|fell)\s+(-?\d+(?:\.\d+)?)\s+percent", "PERCENT_MOM_SA")}
    elif family == "EMPLOYMENT_NFP":
        patterns = {
            "EMPLOYMENT_NFP": (r"Total nonfarm payroll employment\s+(?:rose|increased|declined|fell)\s+by\s+([\d,.]+\s+(?:thousand|million)|[\d,]+)", "PERSON_CHANGE_TEXT"),
            "UNEMPLOYMENT_RATE": (r"unemployment rate.*?(\d+(?:\.\d+)?)\s+percent", "PERCENT"),
            "AVERAGE_HOURLY_EARNINGS": (r"Average hourly earnings.*?(?:rose|increased|declined|fell).*?or\s+(-?\d+(?:\.\d+)?)\s+percent", "PERCENT_MOM")
        }
    elif family == "FOMC":
        patterns = {"FOMC_RATE_DECISION_STATEMENT": (r"target range for the federal funds rate (?:at|to)\s+([\d\-/¼½¾\s]+?)\s+percent", "FED_FUNDS_TARGET_RANGE_PERCENT_TEXT")}
    elif family == "PCE":
        patterns = {
            "PCE": (r"PCE price index\s+(?:increased|rose|decreased|fell)\s+(-?\d+(?:\.\d+)?)\s+percent", "PERCENT_MOM"),
            "CORE_PCE": (r"Excluding food and energy, the PCE price index\s+(?:increased|rose|decreased|fell)\s+(-?\d+(?:\.\d+)?)\s+percent", "PERCENT_MOM")
        }
    elif family == "GDP":
        patterns = {"GDP": (r"real gross domestic product.*?(?:increased|decreased) at an annual rate of\s+(-?\d+(?:\.\d+)?)\s+percent", "PERCENT_ANNUAL_RATE")}
    for record in records:
        pattern = patterns.get(record["event_type"])
        if pattern:
            match = re.search(pattern[0], text, re.I)
            if match:
                record["first_release_value"] = _number(match.group(1))
                record["units"] = pattern[1]
                flags = set(json.loads(record["quality_flags"]))
                flags.discard("ACTUAL_VALUE_UNRESOLVED")
                flags.add("FIRST_RELEASE_DOCUMENT_VALUE")
                record["quality_flags"] = json.dumps(sorted(flags))


def parse_release_document(doc: RawDocument, family: str, spec: dict[str, Any], start: date, end: date) -> list[dict[str, Any]]:
    if not doc.local_path:
        return []
    raw = Path(doc.local_path).read_bytes().decode("utf-8", errors="replace")
    text = _visible_text(raw)
    actual = _release_datetime(text)
    if actual is None or not (start <= actual.date() <= end):
        return []
    reference = None
    period = re.search(r"\b(for|in)\s+((?:January|February|March|April|May|June|July|August|September|October|November|December|first quarter|second quarter|third quarter|fourth quarter)[^,.]{0,20}20\d{2})", text, re.I)
    if period:
        reference = period.group(2)
    records = [
        _base_record(family, event_type, reference, actual, actual, actual, spec["source"], doc.source_reference,
                     doc.sha256, doc.retrieval_timestamp_utc, ["ORIGINAL_RELEASE_DOCUMENT", "REVISION_UNRESOLVED", "ACTUAL_VALUE_UNRESOLVED"])
        for event_type in spec["event_types"]
    ]
    _apply_release_values(records, text, family)
    return records


def parse_bea_release_document(doc: RawDocument, family: str, spec: dict[str, Any], start: date, end: date) -> list[dict[str, Any]]:
    if not doc.local_path or urlparse(doc.source_reference).hostname not in {"www.bea.gov", "bea.gov"}:
        return []
    raw = Path(doc.local_path).read_bytes().decode("utf-8", errors="replace")
    text = _visible_text(raw)
    if "Bureau of Economic Analysis" not in text:
        return []
    actual = _bea_release_datetime(text)
    reference = _bea_reference_period(text, family)
    if actual is None or reference is None or not (start <= actual.date() <= end):
        return []
    base_flags = ["BEA_ORIGINAL_HISTORICAL_RELEASE_DOCUMENT", "PREVIOUS_VALUE_UNRESOLVED"]
    records = [
        _base_record(
            family, event_type, reference, actual, actual, actual, spec["source"],
            doc.source_reference, doc.sha256, doc.retrieval_timestamp_utc,
            base_flags + ["ACTUAL_VALUE_UNRESOLVED"],
        )
        for event_type in spec["event_types"]
    ]
    if family == "PCE":
        patterns = {
            "PCE": r"(?:From the preceding month,\s+)?the PCE price index(?:\s+for\s+[A-Za-z]+)?\s+"
                   r"(increased|decreased|rose|declined|fell)\s+(-?\d+(?:\.\d+)?)\s+percent",
            "CORE_PCE": r"Excluding food and energy,\s+the PCE price index(?:\s+for\s+[A-Za-z]+)?\s+"
                        r"(increased|decreased|rose|declined|fell)\s+(-?\d+(?:\.\d+)?)\s+percent",
        }
        for record in records:
            value = _extract_signed_percent(text, patterns[record["event_type"]])
            flags = set(json.loads(record["quality_flags"]))
            if value is not None:
                record["first_release_value"] = value
                record["units"] = "PERCENT_MOM"
                flags.discard("ACTUAL_VALUE_UNRESOLVED")
                flags.add("CURRENT_PERIOD_FIRST_RELEASE_DOCUMENT_VALUE")
            flags.add("LATER_REVISIONS_NOT_MATERIALIZED")
            record["quality_flags"] = json.dumps(sorted(flags))
        return records

    vintage = _bea_gdp_vintage(text)
    value = _extract_signed_percent(
        text,
        r"Real gross domestic product\s*\(GDP\)\s+"
        r"(increased|decreased|rose|declined|fell)\s+at an annual rate of\s+"
        r"(-?\d+(?:\.\d+)?)\s+percent",
    )
    record = records[0]
    flags = set(json.loads(record["quality_flags"]))
    flags.add(vintage)
    if value is not None and vintage == "ADVANCE_ESTIMATE":
        record["first_release_value"] = value
        record["units"] = "PERCENT_ANNUAL_RATE"
        flags.discard("ACTUAL_VALUE_UNRESOLVED")
        flags.add("GDP_ADVANCE_FIRST_RELEASE_DOCUMENT_VALUE")
    elif value is not None and vintage in {"SECOND_ESTIMATE", "THIRD_ESTIMATE"}:
        record["revised_value"] = value
        record["revision_available_time_utc"] = iso_utc(actual)
        record["units"] = "PERCENT_ANNUAL_RATE"
        flags.discard("ACTUAL_VALUE_UNRESOLVED")
        flags.add("GDP_LATER_VINTAGE_REVISION_VALUE")
        flags.add("FIRST_RELEASE_VALUE_NOT_BACKFILLED")
    else:
        flags.add("GDP_VALUE_OR_VINTAGE_UNRESOLVED")
    record["quality_flags"] = json.dumps(sorted(flags))
    return [record]


EVENT_SPECS: dict[str, dict[str, Any]] = {}


def normalize_documents(config: dict[str, Any], documents: Iterable[RawDocument]) -> tuple[pd.DataFrame, dict[str, Any]]:
    global EVENT_SPECS
    EVENT_SPECS = config["event_families"]
    start, end = date.fromisoformat(config["archive_start"]), date.fromisoformat(config["archive_end"])
    rows: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    for doc in documents:
        if doc.status == "FAILED":
            continue
        if doc.document_kind == "bls_api_values":
            continue
        spec = EVENT_SPECS[doc.event_family]
        try:
            if spec["adapter"] == "bls" and doc.document_kind == "calendar":
                rows.extend(parse_bls_calendar(doc, spec, start, end))
            elif doc.document_kind == "release_document":
                if spec["adapter"] == "bea":
                    rows.extend(parse_bea_release_document(doc, doc.event_family, spec, start, end))
                else:
                    rows.extend(parse_release_document(doc, doc.event_family, spec, start, end))
        except Exception as exc:
            parse_errors.append({"event_family": doc.event_family, "source_reference": doc.source_reference, "error": f"{type(exc).__name__}: {exc}"})
    if not rows:
        return pd.DataFrame(columns=ARCHIVE_COLUMNS), {"parse_errors": parse_errors, "duplicate_count": 0}
    frame = pd.DataFrame(rows, columns=ARCHIVE_COLUMNS)
    # A release document supersedes its schedule-only row when identity fields agree.
    frame["_rank"] = frame["actual_release_time_utc"].notna().astype(int)
    before = len(frame)
    frame = frame.sort_values(["event_id", "_rank"]).drop_duplicates("event_id", keep="last").drop(columns="_rank")
    duplicate_count = before - len(frame)
    return frame.sort_values(["scheduled_time_utc", "event_family", "event_type"], na_position="last").reset_index(drop=True), {
        "parse_errors": parse_errors, "duplicate_count": duplicate_count
    }


def write_parquet_immutable(frame: pd.DataFrame, path: Path, allow_runtime_replace: bool = False) -> str:
    work = frame.copy()
    for col in ARCHIVE_COLUMNS:
        if col not in work:
            work[col] = None
    for col in ("scheduled_time_utc", "actual_release_time_utc", "information_available_time_utc", "revision_available_time_utc"):
        work[col] = pd.to_datetime(work[col], utc=True, errors="coerce")
    table = pa.Table.from_pandas(work[ARCHIVE_COLUMNS], preserve_index=False)
    if path.exists():
        existing = pq.read_table(path)
        if not existing.equals(table):
            if not allow_runtime_replace:
                raise RuntimeError(f"FROZEN_FAST_ARTIFACT_MUTATION: {path}")
            pq.write_table(table, path, compression="zstd")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
    return sha256_file(path)


def load_candidate_timestamps(source: dict[str, str]) -> pd.Series:
    path = Path(source["path"])
    if not path.exists():
        return pd.Series([], dtype="datetime64[ns, UTC]")
    schema = pq.read_schema(path)
    column = source["timestamp_column"]
    if column not in schema.names:
        raise RuntimeError("candidate timestamp column missing")
    # Deliberately read exactly one allowed column; no outcome/target values are loaded.
    table = pq.read_table(path, columns=[column])
    values = pd.to_datetime(table[column].to_pandas(), utc=True, errors="coerce").dropna()
    return values.sort_values().reset_index(drop=True)


def calendar_coverage(frame: pd.DataFrame, candidates: pd.Series, family_status: dict[str, str]) -> dict[str, Any]:
    complete = all(status != "TIER_C_UNSAFE_OR_UNAVAILABLE" for status in family_status.values())
    event_times = pd.to_datetime(frame["scheduled_time_utc"], utc=True, errors="coerce").dropna() if len(frame) else pd.Series([], dtype="datetime64[ns, UTC]")
    event_dates = set(event_times.dt.tz_convert(NY).dt.date)
    candidate_dates = candidates.dt.tz_convert(NY).dt.date if len(candidates) else pd.Series([], dtype=object)
    known_event_day = candidate_dates.isin(event_dates) if len(candidates) else pd.Series([], dtype=bool)
    non_event = int((~known_event_day).sum()) if complete else 0
    unknown = 0 if complete else int((~known_event_day).sum())
    before = after = valid = 0
    if len(candidates) and len(event_times):
        sorted_events = event_times.sort_values().tolist()
        for ts in candidates:
            same = [e for e in sorted_events if e.tz_convert(NY).date() == ts.tz_convert(NY).date()]
            if same:
                valid += 1
                if any(ts < e for e in same): before += 1
                if any(ts >= e for e in same): after += 1
    return {
        "candidate_count": int(len(candidates)),
        "candidate_start_utc": iso_utc(candidates.iloc[0].to_pydatetime()) if len(candidates) else None,
        "candidate_end_utc": iso_utc(candidates.iloc[-1].to_pydatetime()) if len(candidates) else None,
        "candidate_with_valid_event_context_count": valid if complete else int(known_event_day.sum()),
        "candidate_before_event_count": before,
        "candidate_after_event_count": after,
        "candidate_on_known_no_event_day_count": non_event,
        "candidate_unknown_missing_calendar_count": unknown,
        "calendar_coverage_status": "PASS" if complete else "FAIL_INCOMPLETE_OFFICIAL_CALENDAR",
        "no_event_vs_missing_status": "PASS" if complete else "PASS_FAIL_CLOSED_UNKNOWN_DATA_MISSING",
        "missing_semantics": {"known_complete_day_without_event": "NO_RELEVANT_EVENT", "incomplete_family_calendar": "UNKNOWN_DATA_MISSING"}
    }


def feature_contract(config: dict[str, Any]) -> dict[str, Any]:
    families = list(config["event_families"])
    features = ["minutes_to_next_macro_event", "minutes_since_last_macro_event", "event_today", "next_event_type", "last_event_type"]
    for family in families:
        features += [f"{family}_within_{m}m" for m in (15, 30, 60, 120)]
        features += [f"post_{family}_{window}" for window in ("0_15m", "15_30m", "30_60m", "60_120m")]
    features += ["same_trading_day_before_event", "same_trading_day_after_event"]
    features += ["last_released_actual_value", "last_released_first_change", "last_released_actual_minus_prior_known", "last_released_revision_flag"]
    features += ["event_calendar_state"]
    if len(features) > int(config["feature_budget"]):
        raise RuntimeError("FAST6 event feature budget exceeded")
    return {
        "contract_name": "FAST6_EVENT_FEATURE_CONTRACT_R1", "schema_version": "1",
        "legal_event_families": families,
        "legal_event_types": [x for spec in config["event_families"].values() for x in spec["event_types"]],
        "legal_fields": ARCHIVE_COLUMNS,
        "pre_event_windows": ["within_15m", "within_30m", "within_60m", "within_120m", "same_trading_day_before_event"],
        "post_event_windows": ["0_15m", "15_30m", "30_60m", "60_120m", "same_trading_day_after_event"],
        "timestamp_rule": "released fields legal only when information_available_time_utc <= candidate decision timestamp",
        "pre_release_rule": "scheduled metadata only; actual, change, prior comparison, and revision fields are forbidden",
        "revision_rule": "revision values legal only when revision_available_time_utc <= candidate decision timestamp; no current-vintage backfill",
        "missing_data_semantics": {"complete_calendar_no_event": "NO_RELEVANT_EVENT", "incomplete_calendar": "UNKNOWN_DATA_MISSING"},
        "source_timezone": "America/New_York", "canonical_timezone": "UTC",
        "feature_names": features, "feature_count": len(features), "max_feature_count": int(config["feature_budget"]),
        "asset_interactions_allowed": False, "consensus_allowed": False
    }


def visible_actual(record: dict[str, Any], candidate_time: datetime) -> str | None:
    if candidate_time.tzinfo is None:
        raise ValueError("candidate_time must be timezone-aware")
    available = record.get("information_available_time_utc")
    if not available:
        return None
    parsed = datetime.fromisoformat(str(available).replace("Z", "+00:00"))
    return record.get("first_release_value") if parsed <= candidate_time.astimezone(UTC) else None


def visible_revision(record: dict[str, Any], candidate_time: datetime) -> str | None:
    available = record.get("revision_available_time_utc")
    if not available:
        return None
    parsed = datetime.fromisoformat(str(available).replace("Z", "+00:00"))
    return record.get("revised_value") if parsed <= candidate_time.astimezone(UTC) else None
