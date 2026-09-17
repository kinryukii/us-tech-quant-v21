from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast6.acquisition import RawDocument, cache_key, sha256_file  # noqa: E402
from fast6.archive import (  # noqa: E402
    BLS_API_VALUE_COLUMNS, BLS_CALENDAR_COLUMNS, FORBIDDEN_VALUE_COLUMNS,
    calendar_coverage, contract_sha256, feature_contract, join_bls_calendar_values,
    load_bls_static_calendar, parse_bea_release_document, parse_source_datetime,
    visible_actual, visible_revision, write_immutable,
)

_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "fast6_data_r1_entrypoint", ROOT / "scripts" / "run_fast6_data_r1_macro_event_archive.py"
)
assert _SCRIPT_SPEC and _SCRIPT_SPEC.loader
_SCRIPT_MODULE = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(_SCRIPT_MODULE)
_readiness_gate = _SCRIPT_MODULE._readiness_gate


CONFIG = json.loads((ROOT / "config" / "fast6_data_r1_macro_events.json").read_text(encoding="utf-8"))


def test_firewalls_and_no_broker_surface() -> None:
    script = (ROOT / "scripts" / "run_fast6_data_r1_macro_event_archive.py").read_text(encoding="utf-8")
    assert '"TARGET_VALUE_READ_COUNT": 0' in script
    assert '"MODEL_FIT_COUNT": 0' in script
    assert '"MODEL_PREDICT_COUNT": 0' in script
    assert '"ORDER_API_CALL_COUNT": 0' in script
    assert not any(token in script for token in (".fit(", ".predict(", "submit_order", "place_order"))


def test_source_timestamp_utc_and_dst() -> None:
    winter = parse_source_datetime("Tuesday, January 14, 2020", "08:30 AM")
    summer = parse_source_datetime("Tuesday, July 14, 2020", "08:30 AM")
    assert winter.isoformat() == "2020-01-14T13:30:00+00:00"
    assert summer.isoformat() == "2020-07-14T12:30:00+00:00"


def test_pre_and_post_release_actual_visibility() -> None:
    record = {"information_available_time_utc": "2020-01-14T13:30:00Z", "first_release_value": "0.2"}
    assert visible_actual(record, datetime(2020, 1, 14, 13, 29, tzinfo=timezone.utc)) is None
    assert visible_actual(record, datetime(2020, 1, 14, 13, 31, tzinfo=timezone.utc)) == "0.2"


def test_revision_availability() -> None:
    record = {"revision_available_time_utc": "2020-02-01T13:30:00Z", "revised_value": "1.1"}
    assert visible_revision(record, datetime(2020, 2, 1, 13, 29, tzinfo=timezone.utc)) is None
    assert visible_revision(record, datetime(2020, 2, 1, 13, 30, tzinfo=timezone.utc)) == "1.1"


def test_event_uniqueness_and_release_order_contract() -> None:
    rows = pd.DataFrame({"event_id": ["a", "b"], "actual_release_time_utc": pd.to_datetime(["2020-01-01T13:30Z", "2020-02-01T13:30Z"]), "information_available_time_utc": pd.to_datetime(["2020-01-01T13:30Z", "2020-02-01T13:31Z"])})
    assert not rows.event_id.duplicated().any()
    assert (rows.information_available_time_utc >= rows.actual_release_time_utc).all()


def test_no_event_vs_missing_distinction() -> None:
    candidates = pd.Series(pd.to_datetime(["2020-01-02T14:00Z"], utc=True))
    empty = pd.DataFrame(columns=["scheduled_time_utc"])
    report = calendar_coverage(empty, candidates, {"CPI": "TIER_C_UNSAFE_OR_UNAVAILABLE"})
    assert report["candidate_on_known_no_event_day_count"] == 0
    assert report["candidate_unknown_missing_calendar_count"] == 1


def test_contract_budget_and_sha_stability() -> None:
    first = feature_contract(CONFIG)
    second = feature_contract(CONFIG)
    assert first == second
    assert first["feature_count"] <= 60
    assert contract_sha256(first) == contract_sha256(second)


def test_deterministic_cache_key_and_immutable_write(tmp_path: Path) -> None:
    url = "https://www.bls.gov/schedule/2020/home.htm"
    assert cache_key(url) == cache_key(url)
    target = tmp_path / "frozen.json"
    write_immutable(target, b"{}\n")
    write_immutable(target, b"{}\n")
    with pytest.raises(RuntimeError, match="FROZEN_FAST_ARTIFACT_MUTATION"):
        write_immutable(target, b'{"changed": true}\n')


def test_external_storage_contract() -> None:
    assert Path(CONFIG["raw_root"]).drive == "D:"
    assert Path(CONFIG["result_root"]).drive == "D:"
    assert not str(CONFIG["raw_root"]).startswith(str(ROOT))
    assert not str(CONFIG["result_root"]).startswith(str(ROOT))


def test_target_columns_are_never_candidate_projection() -> None:
    assert "decision_timestamp_utc" not in FORBIDDEN_VALUE_COLUMNS
    assert CONFIG["candidate_source"]["timestamp_column"] == "decision_timestamp_utc"


def _calendar_rows() -> list[dict[str, str]]:
    return [
        {"event_family": "CPI", "reference_period": "2020-01", "release_date": "2020-02-13", "release_time_et": "08:30 AM", "timezone": "America/New_York", "source_url": "https://www.bls.gov/schedule/2020/home.htm", "source_year": "2020", "source_type": "BLS_OFFICIAL_HISTORICAL_RELEASE_CALENDAR", "quality_flag": "OFFICIAL_VERIFIED"},
        {"event_family": "PPI", "reference_period": "2020-01", "release_date": "2020-02-19", "release_time_et": "08:30 AM", "timezone": "America/New_York", "source_url": "https://www.bls.gov/schedule/2020/home.htm", "source_year": "2020", "source_type": "BLS_OFFICIAL_HISTORICAL_RELEASE_CALENDAR", "quality_flag": "OFFICIAL_VERIFIED"},
        {"event_family": "EMPLOYMENT_SITUATION", "reference_period": "2020-01", "release_date": "2020-02-07", "release_time_et": "08:30 AM", "timezone": "America/New_York", "source_url": "https://www.bls.gov/schedule/2020/home.htm", "source_year": "2020", "source_type": "BLS_OFFICIAL_HISTORICAL_RELEASE_CALENDAR", "quality_flag": "OFFICIAL_VERIFIED"},
        {"event_family": "CPI", "reference_period": "2020-06", "release_date": "2020-07-14", "release_time_et": "08:30 AM", "timezone": "America/New_York", "source_url": "https://www.bls.gov/schedule/2020/home.htm", "source_year": "2020", "source_type": "BLS_OFFICIAL_HISTORICAL_RELEASE_CALENDAR", "quality_flag": "OFFICIAL_VERIFIED"},
    ]


def _write_calendar(path: Path, rows: list[dict[str, str]]) -> None:
    pd.DataFrame(rows, columns=BLS_CALENDAR_COLUMNS).to_csv(path, index=False)


def _api_values(reference_period: str = "2020-01") -> pd.DataFrame:
    rows = []
    for series_id, spec in CONFIG["bls_api"]["series"].items():
        rows.append({
            "series_id": series_id, "event_family": spec["event_family"],
            "event_type": spec["event_type"], "reference_period": reference_period,
            "value": "100.0", "units": spec["units"],
            "seasonal_adjustment": spec["seasonal_adjustment"],
            "retrieval_timestamp": "2026-08-13T00:00:00Z",
            "source": CONFIG["bls_api"]["endpoint"], "revision_status": spec["revision_status"],
        })
    return pd.DataFrame(rows, columns=BLS_API_VALUE_COLUMNS)


def test_missing_static_calendar_fails_closed(tmp_path: Path) -> None:
    frame, status = load_bls_static_calendar(CONFIG, tmp_path / "missing.csv")
    assert frame.empty
    assert status == "WAITING_FOR_STATIC_OFFICIAL_CALENDAR"


def test_static_calendar_contract_urls_families_timezone_and_dst(tmp_path: Path) -> None:
    path = tmp_path / "calendar.csv"
    _write_calendar(path, _calendar_rows())
    frame, status = load_bls_static_calendar(CONFIG, path)
    assert status == "AVAILABLE_OFFICIAL_VERIFIED"
    assert set(frame.event_family) <= {"CPI", "PPI", "EMPLOYMENT_SITUATION"}
    assert set(frame.timezone) == {"America/New_York"}
    assert all(url == "https://www.bls.gov/schedule/2020/home.htm" for url in frame.source_url)
    winter = frame.loc[(frame.event_family == "CPI") & (frame.reference_period == "2020-01"), "information_available_time_utc"].iloc[0]
    summer = frame.loc[(frame.event_family == "CPI") & (frame.reference_period == "2020-06"), "information_available_time_utc"].iloc[0]
    assert winter == "2020-02-13T13:30:00Z"
    assert summer == "2020-07-14T12:30:00Z"


def test_static_calendar_schema_and_reference_uniqueness(tmp_path: Path) -> None:
    bad_schema = tmp_path / "bad_schema.csv"
    pd.DataFrame(_calendar_rows()).drop(columns="quality_flag").to_csv(bad_schema, index=False)
    with pytest.raises(RuntimeError, match="SCHEMA_INVALID"):
        load_bls_static_calendar(CONFIG, bad_schema)
    duplicate = tmp_path / "duplicate.csv"
    rows = _calendar_rows()
    _write_calendar(duplicate, rows + [rows[0]])
    with pytest.raises(RuntimeError, match="REFERENCE_PERIOD_DUPLICATE"):
        load_bls_static_calendar(CONFIG, duplicate)


@pytest.mark.parametrize(
    ("field", "bad_value", "error"),
    [
        ("event_family", "JOLTS", "FAMILY_INVALID"),
        ("timezone", "UTC", "TIMEZONE_INVALID"),
        ("source_url", "https://example.com/calendar", "SOURCE_URL_INVALID"),
    ],
)
def test_static_calendar_rejects_noncontract_family_timezone_or_url(
    tmp_path: Path, field: str, bad_value: str, error: str
) -> None:
    rows = _calendar_rows()
    rows[0] = {**rows[0], field: bad_value}
    path = tmp_path / f"bad_{field}.csv"
    _write_calendar(path, rows)
    with pytest.raises(RuntimeError, match=error):
        load_bls_static_calendar(CONFIG, path)


def test_api_calendar_one_value_one_calendar_join_and_revision_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "calendar.csv"
    rows = [row for row in _calendar_rows() if row["reference_period"] == "2020-01"]
    _write_calendar(path, rows)
    calendar_frame, _ = load_bls_static_calendar(CONFIG, path)
    first, status = join_bls_calendar_values(CONFIG, calendar_frame, _api_values())
    second, second_status = join_bls_calendar_values(CONFIG, calendar_frame, _api_values())
    assert status == second_status == "PASS_ONE_CALENDAR_ROW_PER_API_VALUE"
    assert len(first) == 6
    assert first.equals(second)
    assert first.first_release_value.isna().all()
    assert first.information_available_time_utc.notna().all()


def test_bls_series_frozen_and_no_html_ics_sources() -> None:
    assert set(CONFIG["bls_api"]["series"]) == {
        "CUSR0000SA0", "CUSR0000SA0L1E", "WPSFD4", "LNS14000000",
        "CES0000000001", "CES0500000003",
    }
    for family in ("CPI", "PPI", "EMPLOYMENT_NFP"):
        spec = CONFIG["event_families"][family]
        assert "calendar_urls" not in spec
        assert "archive_url" not in spec


def test_frozen_feature_contract_expected_sha_unchanged() -> None:
    contract = feature_contract(CONFIG)
    assert contract_sha256(contract) == "8a5c2a589922c1a268a0228da9c33595ebd4956f16dcb0ec90ebc800116361db"


def test_original_readiness_gate_accepts_pit_safe_ppi_without_bea() -> None:
    rows = []
    for family in ("CPI", "PPI", "EMPLOYMENT_NFP", "FOMC"):
        rows.append({
            "event_family": family,
            "actual_release_time_utc": "2024-01-10T13:30:00Z",
            "information_available_time_utc": "2024-01-10T13:30:00Z",
        })
    gate = _readiness_gate(
        pd.DataFrame(rows), calendar_status="AVAILABLE_OFFICIAL_VERIFIED",
        api_status="AVAILABLE", join_status="PASS_ONE_CALENDAR_ROW_PER_API_VALUE",
        fed_status="AVAILABLE",
        pce_status="UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS",
        gdp_status="UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS",
        pit_status="PASS", contract_unchanged=True,
    )
    assert gate["PPI_OR_PCE_OR_GDP_GATE_STATUS"] == "PASS"
    assert gate["MINIMUM_DATA_GATE_STATUS"] == "PASS"
    assert gate["READY_FOR_FAST6_EVENT_R1"] is True


def test_original_readiness_gate_fails_without_any_alternative_family() -> None:
    rows = [{
        "event_family": family,
        "actual_release_time_utc": "2024-01-10T13:30:00Z",
        "information_available_time_utc": "2024-01-10T13:30:00Z",
    } for family in ("CPI", "EMPLOYMENT_NFP", "FOMC")]
    gate = _readiness_gate(
        pd.DataFrame(rows), calendar_status="AVAILABLE_OFFICIAL_VERIFIED",
        api_status="AVAILABLE", join_status="PASS_ONE_CALENDAR_ROW_PER_API_VALUE",
        fed_status="AVAILABLE",
        pce_status="UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS",
        gdp_status="UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS",
        pit_status="PASS", contract_unchanged=True,
    )
    assert gate["PPI_OR_PCE_OR_GDP_GATE_STATUS"] == "FAIL"
    assert gate["READY_FOR_FAST6_EVENT_R1"] is False


def _bea_doc(tmp_path: Path, name: str, body: str, url: str) -> RawDocument:
    path = tmp_path / name
    path.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return RawDocument(
        "PCE" if "personal-income" in url else "GDP",
        "U.S. Bureau of Economic Analysis", url, "release_document", str(path),
        hashlib.sha256(path.read_bytes()).hexdigest(), "2026-08-13T00:00:00Z", "CACHED",
    )


def test_bea_pce_release_parses_first_release_values_and_dst(tmp_path: Path) -> None:
    body = """
    EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT, Friday, June 28, 2024
    U.S. Bureau of Economic Analysis
    Personal Income and Outlays, May 2024
    From the preceding month, the PCE price index for May increased 0.1 percent.
    Excluding food and energy, the PCE price index increased 0.1 percent.
    """
    doc = _bea_doc(tmp_path, "pce.html", body, "https://www.bea.gov/news/2024/personal-income-and-outlays-may-2024")
    rows = parse_bea_release_document(
        doc, "PCE", CONFIG["event_families"]["PCE"],
        datetime(2020, 1, 1).date(), datetime(2025, 1, 30).date(),
    )
    assert [row["event_type"] for row in rows] == ["PCE", "CORE_PCE"]
    assert {row["reference_period"] for row in rows} == {"2024-05"}
    assert {row["information_available_time_utc"] for row in rows} == {"2024-06-28T12:30:00Z"}
    assert [row["first_release_value"] for row in rows] == ["0.1", "0.1"]
    assert all("LATER_REVISIONS_NOT_MATERIALIZED" in row["quality_flags"] for row in rows)


def test_bea_gdp_advance_is_first_release_but_later_vintage_is_revision(tmp_path: Path) -> None:
    advance = _bea_doc(
        tmp_path, "gdp_advance.html",
        """EMBARGOED UNTIL RELEASE AT 8:30 a.m. EST, Thursday, January 25, 2024
        U.S. Bureau of Economic Analysis
        Gross Domestic Product, Fourth Quarter and Year 2023 (Advance Estimate)
        Real gross domestic product (GDP) increased at an annual rate of 3.3 percent in the fourth quarter of 2023.""",
        "https://www.bea.gov/news/2024/gross-domestic-product-fourth-quarter-and-year-2023-advance-estimate",
    )
    second = _bea_doc(
        tmp_path, "gdp_second.html",
        """EMBARGOED UNTIL RELEASE AT 8:30 a.m. EST, Wednesday, February 28, 2024
        U.S. Bureau of Economic Analysis
        Gross Domestic Product, Fourth Quarter and Year 2023 (Second Estimate)
        Real gross domestic product (GDP) increased at an annual rate of 3.2 percent in the fourth quarter of 2023.""",
        "https://www.bea.gov/news/2024/gross-domestic-product-fourth-quarter-and-year-2023-second-estimate",
    )
    start, end = datetime(2020, 1, 1).date(), datetime(2025, 1, 30).date()
    advance_row = parse_bea_release_document(advance, "GDP", CONFIG["event_families"]["GDP"], start, end)[0]
    second_row = parse_bea_release_document(second, "GDP", CONFIG["event_families"]["GDP"], start, end)[0]
    assert advance_row["reference_period"] == second_row["reference_period"] == "2023-Q4"
    assert advance_row["first_release_value"] == "3.3"
    assert advance_row["revised_value"] is None
    assert second_row["first_release_value"] is None
    assert second_row["revised_value"] == "3.2"
    assert second_row["revision_available_time_utc"] == "2024-02-28T13:30:00Z"


def test_bea_parser_fails_closed_without_embargo_or_official_host(tmp_path: Path) -> None:
    body = "U.S. Bureau of Economic Analysis Personal Income and Outlays, May 2024 The PCE price index increased 0.1 percent."
    missing_time = _bea_doc(tmp_path, "missing.html", body, "https://www.bea.gov/news/2024/personal-income-and-outlays-may-2024")
    secondary = _bea_doc(
        tmp_path, "secondary.html",
        "EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT, Friday, June 28, 2024 " + body,
        "https://example.com/personal-income-and-outlays-may-2024",
    )
    start, end = datetime(2020, 1, 1).date(), datetime(2025, 1, 30).date()
    assert parse_bea_release_document(missing_time, "PCE", CONFIG["event_families"]["PCE"], start, end) == []
    assert parse_bea_release_document(secondary, "PCE", CONFIG["event_families"]["PCE"], start, end) == []
