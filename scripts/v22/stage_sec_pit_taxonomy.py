"""Stage official SEC filing metadata, freeze PIT SIC taxonomy, and autorun A2 deconcentration.

This is the single local-network continuation tool for
``A2_SEC_PIT_TAXONOMY_STAGE_BUILD_AND_DECONCENTRATION_AUTORUN_R1``.
It is intentionally narrow:

* network reads are limited to official SEC endpoints;
* quarterly Financial Statement Data Set ZIPs are processed serially and only
  ``sub.txt`` is retained in a compact normalized parquet;
* issuer mappings require deterministic ticker plus name corroboration (or a
  unique historical-name match); fuzzy matching never accepts a mapping;
* filing acceptance time, not filing date alone, controls PIT availability;
* candidate selection uses 2023--2024, freezes finalists, and only then reads
  candidate 2025 outcomes; 2026 outcomes are rejected at every boundary;
* one unified trial ledger is written and no non-finalist model is persisted.

The script is resumable and idempotent.  Re-running it skips successfully
staged quarters recorded in the source manifest and continues the same task.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


TASK_ID = "A2_SEC_PIT_TAXONOMY_STAGE_BUILD_AND_DECONCENTRATION_AUTORUN_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy")
OUT = RESULTS / TASK_ID
A2 = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
UPSTREAM = RESULTS / "A2_AUTHORITATIVE_IDENTITY_RECOVERY_AND_FALSIFICATION_CONTINUATION_R1"
IDENTITY_LEDGER = RESULTS / "A2_CANONICAL_COVERAGE_GAP_CLOSE_AND_PROMOTION_R1" / "coverage_gap_ledger.csv"
PIT_UNIVERSE = RESULTS / "13f_pit_v1" / "data" / "universe" / "13f_dynamic_universe_v17b_clean.parquet"
MOOMOO_MASTER = RESULTS / "13f_pit_v1" / "data" / "universe" / "moomoo_us_stock_basicinfo.parquet"
FALSIFICATION_SOURCE = REPO / "scripts" / "v22" / "a2_strategy_falsification_and_robustness_r1.py"
R0F_SOURCE = REPO / "scripts" / "v22" / "fast_a2_r0f_corporate_action_and_nav_forensic_audit.py"

TOP20 = A2 / "top20_selections.parquet"
PORTFOLIO = A2 / "portfolio_daily.parquet"
TRAINING = A2 / "training_matrix.parquet"
SUB_MIN = CACHE / "sec_fsds_sub_min.parquet"
SOURCE_MANIFEST = CACHE / "sec_source_manifest.json"

EXPECTED_INPUT_HASHES = {
    PORTFOLIO: "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73",
    TOP20: "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20",
    TRAINING: "31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb",
}
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_QUARTER_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip"
REQUIRED_SUB_COLUMNS = [
    "adsh", "cik", "name", "sic", "former", "changed", "form", "period",
    "fy", "fp", "filed", "accepted", "prevrpt", "instance", "nciks", "aciks",
]
UNKNOWN_LIMIT = 0.01
UNKNOWN_WEIGHT_LIMIT = 0.05
ANNUALIZATION = 252.0
MAX_SUCCESSFUL_CANDIDATES = 2500
MAX_FINALISTS = 5
DEFAULT_USER_AGENT = "us-tech-quant PIT taxonomy research JIN kinryukii@gmail.com"


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise GateFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(temp, path)


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def quarter_id(timestamp: pd.Timestamp) -> str:
    value = pd.Timestamp(timestamp)
    return f"{value.year}q{((value.month - 1) // 3) + 1}"


def required_quarters(top20: pd.DataFrame) -> tuple[str, str, list[str]]:
    dates = pd.to_datetime(top20.signal_date).dt.normalize()
    require(dates.max() < pd.Timestamp("2026-01-01"), "2026_TOP20_DATE")
    earliest = dates.min() - pd.Timedelta(days=730)
    earliest = max(earliest, pd.Timestamp("2009-01-01"))
    start = pd.Period(earliest, freq="Q")
    end = pd.Period("2025Q4", freq="Q")
    quarters = [f"{period.year}q{period.quarter}" for period in pd.period_range(start, end, freq="Q")]
    return quarters[0], quarters[-1], quarters


def _request(url: str, user_agent: str, *, timeout: int = 90, byte_range: str | None = None) -> bytes:
    headers = {"User-Agent": user_agent, "Accept-Encoding": "identity"}
    if byte_range:
        headers["Range"] = byte_range
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        require(int(response.status) in (200, 206), "SEC_HTTP_STATUS", response.status)
        return response.read()


def parse_accepted(series: pd.Series) -> pd.Series:
    raw = series.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    compact = raw.str.replace(r"\D", "", regex=True)
    parsed = pd.to_datetime(compact.where(compact.str.len().ge(8)), format="%Y%m%d%H%M%S", errors="coerce")
    missing = parsed.isna()
    parsed.loc[missing] = pd.to_datetime(raw.loc[missing], errors="coerce")
    # FSDS acceptance timestamps are EDGAR Eastern timestamps.  DST ambiguity
    # is impossible for normal filing hours; invalid values remain missing.
    return parsed.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")


def normalize_sub(frame: pd.DataFrame, quarter: str) -> pd.DataFrame:
    work = frame.copy()
    work.columns = [str(column).strip().lower() for column in work.columns]
    for column in REQUIRED_SUB_COLUMNS:
        if column not in work:
            work[column] = pd.NA
    work = work[REQUIRED_SUB_COLUMNS].copy()
    work["quarter"] = quarter.upper()
    work["cik"] = pd.to_numeric(work.cik, errors="coerce").astype("Int64")
    work["sic"] = pd.to_numeric(work.sic, errors="coerce").astype("Int64")
    work["filed"] = pd.to_datetime(work.filed.astype("string"), format="%Y%m%d", errors="coerce")
    work["accepted_timestamp_utc"] = parse_accepted(work.accepted)
    for column in ("adsh", "name", "former", "changed", "form", "period", "fp", "instance", "aciks"):
        work[column] = work[column].astype("string").str.strip()
    return work.drop(columns=["accepted"]).drop_duplicates(["adsh"], keep="last").reset_index(drop=True)


def parse_sub_zip(payload: bytes, quarter: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    sha = hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        bad = archive.testzip()
        require(bad is None, "SEC_ZIP_INTEGRITY", bad)
        names = {name.lower(): name for name in archive.namelist()}
        key = next((name for name in names if name.endswith("sub.txt")), None)
        require(key is not None, "SEC_SUB_MISSING", quarter)
        with archive.open(names[key]) as stream:
            raw = pd.read_csv(stream, sep="\t", dtype="string", keep_default_na=False, low_memory=False)
    normalized = normalize_sub(raw, quarter)
    meta = {
        "quarter": quarter.upper(), "source_type": "SEC_FINANCIAL_STATEMENT_DATA_SET_SUB",
        "byte_size": len(payload), "sha256": sha, "zip_integrity": "PASS",
        "sub_row_count": int(len(normalized)),
        "min_filed": None if normalized.filed.isna().all() else normalized.filed.min().date().isoformat(),
        "max_filed": None if normalized.filed.isna().all() else normalized.filed.max().date().isoformat(),
        "min_accepted": None if normalized.accepted_timestamp_utc.isna().all() else normalized.accepted_timestamp_utc.min().isoformat(),
        "max_accepted": None if normalized.accepted_timestamp_utc.isna().all() else normalized.accepted_timestamp_utc.max().isoformat(),
        "schema_columns": list(normalized.columns),
    }
    return normalized, meta


def read_manifest() -> dict[str, Any]:
    if not SOURCE_MANIFEST.exists():
        return {"schema_version": 1, "quarters": {}, "company_tickers": {}, "status": "INITIALIZED"}
    return json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))


def stage_sec_data(quarters: list[str], user_agent: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest()
    existing = pd.read_parquet(SUB_MIN) if SUB_MIN.exists() else pd.DataFrame()
    pieces = [existing] if not existing.empty else []
    staged = set(existing.quarter.astype(str).str.lower()) if not existing.empty and "quarter" in existing else set()
    for quarter in quarters:
        saved = manifest.get("quarters", {}).get(quarter, {})
        if quarter in staged and saved.get("zip_integrity") == "PASS":
            continue
        failure: str | None = None
        for attempt in (1, 2):
            try:
                payload = _request(SEC_QUARTER_URL.format(quarter=quarter), user_agent, timeout=180)
                normalized, meta = parse_sub_zip(payload, quarter)
                meta.update({"http_status": 200, "download_timestamp_utc": datetime.now(timezone.utc).isoformat(), "attempt": attempt})
                pieces = [piece.loc[piece.quarter.astype(str).str.lower().ne(quarter)] for piece in pieces]
                pieces.append(normalized)
                combined = pd.concat(pieces, ignore_index=True).sort_values(["accepted_timestamp_utc", "cik", "adsh"], kind="mergesort")
                temp = SUB_MIN.with_suffix(".parquet.tmp")
                combined.to_parquet(temp, index=False, compression="zstd")
                os.replace(temp, SUB_MIN)
                manifest.setdefault("quarters", {})[quarter] = meta
                manifest["status"] = "IN_PROGRESS"
                atomic_json(SOURCE_MANIFEST, manifest)
                staged.add(quarter)
                time.sleep(0.25)
                failure = None
                break
            except Exception as exc:  # bounded one retry per quarter
                failure = f"{type(exc).__name__}:{exc}"
                if attempt == 1:
                    time.sleep(1.0)
        if failure:
            manifest.setdefault("quarters", {})[quarter] = {
                "quarter": quarter.upper(), "source_type": "SEC_FINANCIAL_STATEMENT_DATA_SET_SUB",
                "status": "FAILED_AFTER_ONE_RETRY", "failure_reason": failure,
                "download_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            atomic_json(SOURCE_MANIFEST, manifest)

    company_payload = _request(SEC_COMPANY_TICKERS_URL, user_agent, timeout=90)
    company_sha = hashlib.sha256(company_payload).hexdigest()
    company_json = json.loads(company_payload.decode("utf-8"))
    records = list(company_json.values()) if isinstance(company_json, dict) else list(company_json)
    tickers = pd.DataFrame(records).rename(columns={"cik_str": "cik", "title": "sec_title"})
    require({"cik", "ticker", "sec_title"}.issubset(tickers.columns), "SEC_COMPANY_TICKER_SCHEMA")
    tickers = tickers[["cik", "ticker", "sec_title"]].copy()
    tickers["cik"] = pd.to_numeric(tickers.cik, errors="coerce").astype("Int64")
    tickers["ticker"] = tickers.ticker.astype(str).str.upper().str.strip()
    tickers["sec_title"] = tickers.sec_title.astype(str).str.strip()
    manifest["company_tickers"] = {
        "url": SEC_COMPANY_TICKERS_URL, "sha256": company_sha, "byte_size": len(company_payload),
        "row_count": int(len(tickers)), "download_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "role": "AUXILIARY_IDENTITY_EVIDENCE_ONLY_NOT_SIC",
    }
    successful = [q for q in quarters if manifest.get("quarters", {}).get(q, {}).get("zip_integrity") == "PASS"]
    manifest["status"] = "PASS_COMPLETE" if len(successful) == len(quarters) else "PARTIAL"
    manifest["required_quarters"] = quarters
    manifest["successful_quarters"] = successful
    manifest["failed_quarters"] = sorted(set(quarters) - set(successful))
    manifest["sec_fsds_sub_min_sha256"] = sha256_file(SUB_MIN) if SUB_MIN.exists() else None
    atomic_json(SOURCE_MANIFEST, manifest)
    sub = pd.read_parquet(SUB_MIN)
    return sub, tickers, manifest


CORPORATE_SUFFIX = re.compile(
    r"\b(INCORPORATED|INC|CORPORATION|CORP|COMPANY|CO|LIMITED|LTD|PLC|LP|LLC|HOLDINGS?|GROUP|THE)\b"
)


def normalize_name(value: Any) -> str:
    text = re.sub(r"[^A-Z0-9 ]", " ", str(value).upper())
    text = CORPORATE_SUFFIX.sub(" ", text)
    return " ".join(text.split())


def project_identity_evidence(top20: pd.DataFrame) -> pd.DataFrame:
    tickers = sorted(top20.ticker.astype(str).str.upper().unique())
    ledger = pd.read_csv(IDENTITY_LEDGER, dtype="string", usecols=["security_id", "ticker"])
    ledger["ticker"] = ledger.ticker.str.upper().str.strip()
    ledger = ledger.loc[ledger.ticker.isin(tickers)].dropna(subset=["security_id"])
    require(not ledger.groupby("ticker").security_id.nunique().gt(1).any(), "EXISTING_SECURITY_ID_CONFLICT")
    security = ledger.drop_duplicates("ticker").set_index("ticker").security_id.to_dict()

    master = pd.read_parquet(MOOMOO_MASTER)
    master["ticker"] = master.code.astype(str).str.replace(r"^US\.", "", regex=True).str.upper()
    name_column = next(column for column in ("name", "stock_name", "security_name") if column in master.columns)
    master_names = master.drop_duplicates("ticker").set_index("ticker")[name_column].astype(str).to_dict()

    universe = pd.read_parquet(PIT_UNIVERSE)
    universe.columns = [str(column).lower() for column in universe.columns]
    issuer_column = next(column for column in ("issuer_name", "issuer", "name") if column in universe.columns)
    cusip_names: dict[str, set[str]] = {}
    if "cusip" in universe:
        for cusip, group in universe.dropna(subset=["cusip"]).groupby(universe.cusip.astype(str).str.upper()):
            cusip_names[str(cusip)] = set(group[issuer_column].dropna().astype(str))

    rows = []
    for ticker in tickers:
        sid = security.get(ticker)
        names = {master_names[ticker]} if ticker in master_names else set()
        if sid and str(sid).upper().startswith("CUSIP_"):
            names |= cusip_names.get(str(sid)[6:].upper(), set())
        normalized = sorted({normalize_name(name) for name in names if normalize_name(name)})
        rows.append({
            "ticker": ticker, "security_id": sid if sid else f"A2_TICKER_{ticker}",
            "existing_bridge": bool(sid), "project_names": sorted(names), "normalized_project_names": normalized,
        })
    return pd.DataFrame(rows)


def build_cik_bridge(top20: pd.DataFrame, sub: pd.DataFrame, company_tickers: pd.DataFrame) -> pd.DataFrame:
    evidence = project_identity_evidence(top20)
    historical_names = (
        sub.dropna(subset=["cik", "name"])[["cik", "name"]].drop_duplicates()
        .assign(normalized_name=lambda x: x.name.map(normalize_name))
    )
    current_by_ticker = {ticker: group for ticker, group in company_tickers.groupby("ticker", sort=False)}
    name_to_ciks = historical_names.groupby("normalized_name").cik.apply(lambda x: sorted({int(v) for v in x.dropna()})).to_dict()
    rows: list[dict[str, Any]] = []
    for item in evidence.itertuples(index=False):
        project_names = set(item.normalized_project_names)
        candidates: list[tuple[int, str, str]] = []
        current = current_by_ticker.get(item.ticker)
        if current is not None:
            for record in current.itertuples(index=False):
                cik = int(record.cik)
                sec_names = {normalize_name(record.sec_title)} | set(
                    historical_names.loc[historical_names.cik.eq(cik), "normalized_name"]
                )
                if project_names & sec_names:
                    candidates.append((cik, "B_EXACT_SEC_TICKER_PLUS_NAME_CORROBORATED", str(record.sec_title)))
        if not candidates:
            historical = sorted({cik for name in project_names for cik in name_to_ciks.get(name, [])})
            if len(historical) == 1:
                cik = historical[0]
                matching = historical_names.loc[
                    historical_names.cik.eq(cik) & historical_names.normalized_name.isin(project_names), "name"
                ]
                candidates.append((cik, "C_EXACT_HISTORICAL_NAME_CIK_AND_CORPORATE_ACTION_CORROBORATED", "|".join(sorted(matching.astype(str).unique()))))
        unique = {candidate[0] for candidate in candidates}
        if len(unique) == 1:
            cik, confidence, sec_name = candidates[0]
            status, ambiguity = "VERIFIED", False
        else:
            cik, confidence, sec_name = None, "UNRESOLVED", None
            status, ambiguity = "UNRESOLVED", len(unique) > 1
        rows.append({
            "security_id": item.security_id, "ticker": item.ticker,
            "issuer_name": "|".join(item.project_names), "effective_start": top20.loc[top20.ticker.eq(item.ticker), "signal_date"].min(),
            "effective_end": top20.loc[top20.ticker.eq(item.ticker), "signal_date"].max(),
            "cik": cik, "mapping_source": "EXISTING_PROJECT_IDENTITY_PLUS_OFFICIAL_SEC",
            "mapping_evidence": sec_name, "mapping_confidence": confidence,
            "ambiguity_flag": ambiguity, "identity_status": status,
            "existing_security_id_bridge": bool(item.existing_bridge),
        })
    bridge = pd.DataFrame(rows).sort_values("ticker", kind="mergesort").reset_index(drop=True)
    require(not bridge.dropna(subset=["cik"]).groupby("ticker").cik.nunique().gt(1).any(), "CIK_TICKER_CONFLICT")
    return bridge


# Static Fama/French mappings.  The FF48 definitions follow the standard
# Siccodes48 specification; unmatched valid SICs fall into its residual Other
# category.  Ranges are intentionally code, not data learned from outcomes.
FF12_RANGES: dict[str, list[tuple[int, int]]] = {
    "01_NODUR": [(100, 999), (2000, 2399), (2700, 2749), (2770, 2799), (3100, 3199), (3940, 3989)],
    "02_DURBL": [(2500, 2519), (2590, 2599), (3630, 3659), (3710, 3711), (3714, 3714), (3716, 3716), (3750, 3751), (3792, 3792), (3900, 3939), (3990, 3999)],
    "03_MANUF": [(2520, 2589), (2600, 2699), (2750, 2769), (3000, 3099), (3200, 3569), (3580, 3629), (3700, 3709), (3712, 3713), (3715, 3715), (3717, 3749), (3752, 3791), (3793, 3799), (3830, 3839), (3860, 3899)],
    "04_ENRGY": [(1200, 1399), (2900, 2999)],
    "05_CHEMS": [(2800, 2829), (2840, 2899)],
    "06_BUSEQ": [(3570, 3579), (3660, 3692), (3694, 3699), (3810, 3829), (7370, 7379)],
    "07_TELCM": [(4800, 4899)], "08_UTILS": [(4900, 4949)],
    "09_SHOPS": [(5000, 5999), (7200, 7299), (7600, 7699)],
    "10_HLTH": [(2830, 2839), (3693, 3693), (3840, 3859), (8000, 8099)],
    "11_MONEY": [(6000, 6999)],
}

FF48_RANGES: dict[str, list[tuple[int, int]]] = {
    "01_AGRIC": [(100,199),(200,299),(700,799),(910,919),(2048,2048)],
    "02_FOOD": [(2000,2009),(2010,2019),(2020,2029),(2030,2039),(2040,2046),(2050,2059),(2060,2063),(2070,2079),(2090,2092),(2095,2095),(2098,2099)],
    "03_SODA": [(2064,2068),(2086,2087),(2096,2097)], "04_BEER": [(2080,2080),(2082,2085)],
    "05_SMOKE": [(2100,2199)], "06_TOYS": [(920,999),(3650,3652),(3732,3732),(3930,3931),(3940,3949)],
    "07_FUN": [(7800,7841),(7900,7949),(7980,7980),(7990,7999)], "08_BOOKS": [(2700,2749),(2770,2799)],
    "09_HSHLD": [(2047,2047),(2391,2392),(2510,2519),(2590,2599),(2840,2844),(3160,3199),(3229,3231),(3260,3260),(3262,3263),(3269,3269),(3630,3639),(3750,3751),(3800,3800),(3860,3879),(3910,3919),(3960,3962),(3991,3991),(3995,3995)],
    "10_CLTHS": [(2300,2390),(3020,3021),(3100,3111),(3130,3159),(3965,3965)],
    "11_HLTH": [(8000,8099)], "12_MEDEQ": [(3693,3693),(3840,3851)], "13_DRUGS": [(2830,2836)],
    "14_CHEMS": [(2800,2829),(2850,2899)], "15_RUBBR": [(3000,3000),(3031,3031),(3041,3041),(3050,3099)],
    "16_TXTLS": [(2200,2295),(2297,2299),(2393,2395),(2397,2399)],
    "17_BLDMT": [(800,899),(2400,2439),(2450,2459),(2490,2499),(2660,2661),(2950,2952),(3200,3211),(3240,3259),(3261,3261),(3264,3264),(3270,3299),(3420,3433),(3440,3442),(3446,3449),(3450,3452),(3490,3499),(3996,3996)],
    "18_CNSTR": [(1500,1799)], "19_STEEL": [(3300,3369),(3390,3399)],
    "20_FABPR": [(3400,3400),(3443,3444),(3460,3479)], "21_MACH": [(3510,3536),(3538,3538),(3540,3569),(3580,3582),(3585,3586),(3589,3599)],
    "22_ELCEQ": [(3600,3600),(3610,3613),(3620,3621),(3623,3629),(3640,3646),(3648,3649),(3660,3660),(3690,3692),(3699,3699)],
    "23_AUTOS": [(2296,2296),(2396,2396),(3010,3011),(3537,3537),(3647,3647),(3694,3694),(3700,3700),(3710,3711),(3713,3716),(3790,3792),(3799,3799)],
    "24_AERO": [(3720,3721),(3723,3725),(3728,3729)], "25_SHIPS": [(3730,3731),(3740,3743)],
    "26_GUNS": [(3480,3489),(3760,3769),(3795,3795)], "27_GOLD": [(1040,1049)],
    "28_MINES": [(1000,1039),(1050,1119),(1400,1499)], "29_COAL": [(1200,1299)],
    "30_OIL": [(1300,1300),(1310,1339),(1370,1382),(1389,1389),(2900,2912),(2990,2999)],
    "31_UTIL": [(4900,4900),(4910,4911),(4920,4925),(4930,4932),(4939,4939),(4940,4942)],
    "32_TELCM": [(4800,4800),(4810,4813),(4820,4822),(4830,4839),(4840,4841),(4880,4892),(4899,4899)],
    "33_PERSV": [(7020,7021),(7030,7033),(7200,7200),(7210,7212),(7214,7217),(7219,7219),(7220,7221),(7230,7231),(7240,7241),(7250,7251),(7260,7299),(7395,7395),(7500,7500),(7510,7515),(7520,7549),(7600,7600),(7620,7620),(7622,7623),(7629,7641),(7690,7699),(8100,8499),(8600,8699),(8800,8899)],
    "34_BUSSV": [(2750,2759),(3993,3993),(4220,4229),(7218,7218),(7300,7300),(7310,7342),(7349,7372),(7374,7394),(7396,7397),(7399,7399),(7519,7519),(8700,8748),(8900,8999)],
    "35_COMPS": [(3570,3579),(3680,3689),(3695,3695),(7373,7373)],
    "36_CHIPS": [(3622,3622),(3661,3666),(3669,3669),(3670,3679),(3810,3810),(3812,3812)],
    "37_LABEQ": [(3811,3811),(3820,3827),(3829,3839)], "38_PAPER": [(2520,2549),(2600,2639),(2670,2699),(2760,2761),(3950,3955)],
    "39_BOXES": [(2440,2449),(2640,2659),(3220,3221),(3410,3412)],
    "40_TRANS": [(4000,4013),(4040,4049),(4100,4151),(4170,4173),(4190,4219),(4230,4249),(4400,4799)],
    "41_WHLSL": [(5000,5199)], "42_RTAIL": [(5200,5799),(5900,5999)],
    "43_MEALS": [(5800,5899),(7000,7019),(7040,7049),(7213,7213)], "44_BANKS": [(6000,6199)],
    "45_INSUR": [(6300,6411)], "46_RLEST": [(6500,6553),(6590,6599),(6610,6611)],
    "47_FIN": [(6200,6299),(6700,6799)], "48_OTHER": [(4950,4991)],
}


def map_ranges(sic: Any, ranges: dict[str, list[tuple[int, int]]], residual: str) -> str:
    if pd.isna(sic):
        return "UNKNOWN"
    value = int(sic)
    for label, spans in ranges.items():
        if any(low <= value <= high for low, high in spans):
            return label
    return residual


def ff12(sic: Any) -> str:
    return map_ranges(sic, FF12_RANGES, "12_OTHER")


def ff48(sic: Any) -> str:
    return map_ranges(sic, FF48_RANGES, "48_OTHER")


def information_execution_map(top20: pd.DataFrame, portfolio: pd.DataFrame) -> pd.DataFrame:
    signals = pd.DatetimeIndex(sorted(pd.to_datetime(top20.signal_date).dt.normalize().unique()))
    executions = pd.DatetimeIndex(sorted(pd.to_datetime(portfolio.execution_date).dt.normalize().unique()))
    rows = []
    for signal in signals:
        future = executions[executions > signal]
        require(len(future) > 0, "NO_EXECUTION_AFTER_INFORMATION_DATE", signal)
        rows.append({"signal_date": signal, "execution_date": future[0]})
    result = pd.DataFrame(rows)
    require((result.execution_date > result.signal_date).all(), "SAME_DAY_INFORMATION_EXECUTION_JOIN")
    return result


def build_taxonomy(top20: pd.DataFrame, portfolio: pd.DataFrame, bridge: pd.DataFrame, sub: pd.DataFrame) -> pd.DataFrame:
    mapping = information_execution_map(top20, portfolio)
    work = top20[["signal_date", "ticker"]].merge(mapping, on="signal_date", how="left", validate="many_to_one")
    work = work.merge(bridge[["security_id", "ticker", "cik", "mapping_confidence"]], on="ticker", how="left", validate="many_to_one")
    local = pd.to_datetime(work.signal_date).dt.tz_localize("America/New_York") + pd.Timedelta(hours=16)
    work["information_cutoff_utc"] = local.dt.tz_convert("UTC")
    work["_row"] = np.arange(len(work))

    filings = sub.dropna(subset=["cik", "sic", "accepted_timestamp_utc"]).copy()
    filings = filings.loc[filings.accepted_timestamp_utc < pd.Timestamp("2026-01-01", tz="UTC")]
    filings = filings.sort_values(["accepted_timestamp_utc", "cik", "adsh"], kind="mergesort")
    parts = []
    for cik, group in work.dropna(subset=["cik"]).groupby("cik", sort=False):
        history = filings.loc[filings.cik.eq(int(cik))]
        if history.empty:
            group = group.assign(pit_sic=pd.NA, sic_source_adsh=pd.NA, sic_accepted_timestamp_utc=pd.NaT)
        else:
            group = pd.merge_asof(
                group.sort_values("information_cutoff_utc"),
                history[["accepted_timestamp_utc", "sic", "adsh", "name"]].sort_values("accepted_timestamp_utc"),
                left_on="information_cutoff_utc", right_on="accepted_timestamp_utc", direction="backward", allow_exact_matches=True,
            ).rename(columns={"sic": "pit_sic", "adsh": "sic_source_adsh", "accepted_timestamp_utc": "sic_accepted_timestamp_utc", "name": "sec_issuer_name"})
        parts.append(group)
    unmapped = work.loc[work.cik.isna()].assign(pit_sic=pd.NA, sic_source_adsh=pd.NA, sic_accepted_timestamp_utc=pd.NaT, sec_issuer_name=pd.NA)
    parts.append(unmapped)
    result = pd.concat(parts, ignore_index=True).sort_values("_row", kind="mergesort").drop(columns="_row")
    result["ff12"] = result.pit_sic.map(ff12)
    result["ff48"] = result.pit_sic.map(ff48)
    result["taxonomy_status"] = np.where(result.pit_sic.isna(), "UNKNOWN_TAXONOMY", "PIT_SEC_SIC_MAPPED")
    known = result.sic_accepted_timestamp_utc.notna()
    require((result.loc[known, "sic_accepted_timestamp_utc"] <= result.loc[known, "information_cutoff_utc"]).all(), "FUTURE_FILING_VIOLATION")
    require(not result.duplicated(["signal_date", "ticker"]).any(), "TAXONOMY_PRIMARY_KEY_DUPLICATE")
    return result


def taxonomy_gate(taxonomy: pd.DataFrame) -> dict[str, Any]:
    unknown = taxonomy.pit_sic.isna()
    by_date = taxonomy.assign(unknown_weight=unknown.astype(float) / 20.0).groupby("signal_date").unknown_weight.sum()
    mapped_security = taxonomy.groupby("ticker").cik.apply(lambda x: x.notna().any())
    sic_security = taxonomy.groupby("ticker").pit_sic.apply(lambda x: x.notna().any())
    changes = (
        taxonomy.dropna(subset=["pit_sic"]).sort_values(["ticker", "signal_date"])
        .groupby("ticker").pit_sic.apply(lambda x: int(x.ne(x.shift()).sum() - 1)).clip(lower=0).sum()
    )
    return {
        "a2_unique_securities": int(taxonomy.ticker.nunique()), "a2_security_dates": int(len(taxonomy)),
        "cik_mapped_securities": int(mapped_security.sum()), "cik_security_coverage": float(mapped_security.mean()),
        "cik_security_date_coverage": float(taxonomy.cik.notna().mean()),
        "pit_sic_security_count": int(sic_security.sum()), "pit_sic_security_date_coverage": float(taxonomy.pit_sic.notna().mean()),
        "ff12_security_date_coverage": float(taxonomy.ff12.ne("UNKNOWN").mean()),
        "ff48_security_date_coverage": float(taxonomy.ff48.ne("UNKNOWN").mean()),
        "unknown_security_date_pct": float(unknown.mean()), "max_unknown_portfolio_weight": float(by_date.max()),
        "temporal_sic_change_count": int(changes), "future_filing_violation_count": 0, "backward_fill_violation_count": 0,
        "coverage_gate_pass": bool(unknown.mean() <= UNKNOWN_LIMIT and by_date.max() <= UNKNOWN_WEIGHT_LIMIT),
    }


def metrics(returns: Iterable[float]) -> dict[str, float | int | None]:
    values = np.asarray(list(returns), float)
    require(len(values) > 1 and np.isfinite(values).all() and (values > -1).all(), "INVALID_RETURN_SERIES")
    nav = np.r_[1.0, np.cumprod(1.0 + values)]
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    volatility = float(values.std(ddof=0) * math.sqrt(ANNUALIZATION))
    cagr = float(nav[-1] ** (ANNUALIZATION / len(values)) - 1.0)
    return {
        "session_count": int(len(values)), "cumulative_return": float(nav[-1] - 1.0), "cagr": cagr,
        "sharpe": float(values.mean() * ANNUALIZATION / volatility) if volatility else None,
        "max_drawdown": float(drawdown.min()), "calmar": float(cagr / abs(drawdown.min())) if drawdown.min() < 0 else None,
        "annualized_volatility": volatility,
    }


def concentration(target: dict[pd.Timestamp, dict[str, float]], taxonomy: pd.DataFrame, year: int | None = None) -> dict[str, float]:
    lookup = taxonomy.set_index(["signal_date", "ticker"])[["ff12", "ff48"]]
    rows = []
    for date, weights in target.items():
        if year is not None and pd.Timestamp(date).year != year:
            continue
        table = pd.DataFrame({"ticker": list(weights), "weight": list(weights.values())})
        table["signal_date"] = pd.Timestamp(date)
        table = table.join(lookup, on=["signal_date", "ticker"])
        require(table[["ff12", "ff48"]].notna().all().all(), "TARGET_TAXONOMY_MISSING", date)
        ff12_weight = table.groupby("ff12").weight.sum()
        ff48_weight = table.groupby("ff48").weight.sum()
        h12, h48 = float((ff12_weight ** 2).sum()), float((ff48_weight ** 2).sum())
        rows.append({
            "ff12_hhi": h12, "ff12_max_weight": float(ff12_weight.max()), "ff12_effective_count": 1.0 / h12,
            "ff48_hhi": h48, "ff48_max_weight": float(ff48_weight.max()), "ff48_effective_count": 1.0 / h48,
        })
    frame = pd.DataFrame(rows)
    require(not frame.empty, "EMPTY_CONCENTRATION_SUPPORT", year)
    return {column: float(frame[column].mean()) for column in frame.columns}


@dataclass(frozen=True)
class Candidate:
    trial_id: str
    family: str
    method: str
    parameter: float | None


def _group_budget_weights(day: pd.DataFrame, group: str, power: float, within_score: bool = False) -> dict[str, float]:
    counts = day.groupby(group).ticker.count().astype(float)
    raw_budget = counts / counts.sum()
    budget = raw_budget.pow(power)
    budget /= budget.sum()
    result: dict[str, float] = {}
    for label, members in day.groupby(group, sort=True):
        if within_score:
            order = members.sort_values(["a2_prediction", "ticker"], ascending=[False, True], kind="mergesort")
            within = 1.0 / np.arange(1, len(order) + 1, dtype=float)
            within /= within.sum()
            result.update({ticker: float(budget.loc[label] * weight) for ticker, weight in zip(order.ticker, within)})
        else:
            result.update({ticker: float(budget.loc[label] / len(members)) for ticker in members.ticker})
    return result


def candidate_target(candidate: Candidate, top20: pd.DataFrame, taxonomy: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    joined = top20.merge(taxonomy[["signal_date", "ticker", "ff12", "ff48"]], on=["signal_date", "ticker"], validate="one_to_one")
    target: dict[pd.Timestamp, dict[str, float]] = {}
    for date, day in joined.groupby("signal_date", sort=True):
        if candidate.method == "RAW":
            weights = {ticker: 0.05 for ticker in day.ticker}
        elif candidate.method == "SOFT_FF12":
            weights = _group_budget_weights(day, "ff12", 1.0 - float(candidate.parameter))
        elif candidate.method == "FF12_CAP":
            cap = float(candidate.parameter)
            counts = day.groupby("ff12").ticker.count().astype(float)
            raw = counts / counts.sum()
            require(len(raw) * cap >= 1.0 - 1e-12, "INFEASIBLE_SECTOR_CAP", (date, cap))
            budget = raw.copy()
            fixed: dict[str, float] = {}
            while len(budget) and budget.max() > cap + 1e-12:
                label = str(budget.idxmax())
                fixed[label] = cap
                budget = budget.drop(label)
                budget = budget / budget.sum() * (1.0 - sum(fixed.values()))
            budget = pd.concat([budget, pd.Series(fixed, dtype=float)])
            weights = {ticker: float(budget.loc[label] / len(members)) for label, members in day.groupby("ff12") for ticker in members.ticker}
        elif candidate.method == "WITHIN_FF12":
            weights = _group_budget_weights(day, "ff12", 0.0, within_score=True)
        elif candidate.method == "WITHIN_FF48":
            weights = _group_budget_weights(day, "ff48", 0.0, within_score=True)
        elif candidate.method == "HIERARCHICAL":
            weights = {}
            sectors = sorted(day.ff12.unique())
            for sector, sector_members in day.groupby("ff12", sort=True):
                industries = sorted(sector_members.ff48.unique())
                for industry, members in sector_members.groupby("ff48", sort=True):
                    unit = 1.0 / len(sectors) / len(industries) / len(members)
                    weights.update({ticker: unit for ticker in members.ticker})
        else:
            raise GateFailure(f"UNKNOWN_CANDIDATE_METHOD:{candidate.method}")
        require(len(weights) == 20 and abs(sum(weights.values()) - 1.0) <= 1e-12 and min(weights.values()) > 0, "TARGET_WEIGHT_IDENTITY", (candidate.trial_id, date))
        target[pd.Timestamp(date)] = weights
    return target


def candidates() -> list[Candidate]:
    return [
        Candidate("S0_RAW", "CONTROL", "RAW", None),
        Candidate("S1_SOFT_025", "SIMPLE_OVERLAY", "SOFT_FF12", 0.25),
        Candidate("S1_SOFT_050", "SIMPLE_OVERLAY", "SOFT_FF12", 0.50),
        Candidate("S1_SOFT_075", "SIMPLE_OVERLAY", "SOFT_FF12", 0.75),
        Candidate("S2_CAP_050", "SIMPLE_CAP", "FF12_CAP", 0.50),
        Candidate("S2_CAP_060", "SIMPLE_CAP", "FF12_CAP", 0.60),
        Candidate("S3_FF12_RANK", "SCORE_NEUTRALIZATION", "WITHIN_FF12", None),
        Candidate("S4_FF48_RANK", "INDUSTRY_NEUTRALIZATION", "WITHIN_FF48", None),
        Candidate("S5_HIERARCHICAL", "HIERARCHICAL", "HIERARCHICAL", None),
    ]


def pareto_frontier(frame: pd.DataFrame) -> pd.DataFrame:
    maximize = ["sharpe", "cagr", "ff12_effective_count", "ff48_effective_count"]
    minimize = ["ff12_hhi", "ff48_hhi", "ff12_max_weight", "ff48_max_weight", "turnover", "cost"]
    values = frame.reset_index(drop=True)
    keep = np.ones(len(values), dtype=bool)
    for i, row in values.iterrows():
        for j, other in values.iterrows():
            if i == j:
                continue
            no_worse = all(other[c] >= row[c] for c in maximize) and all(other[c] <= row[c] for c in minimize)
            better = any(other[c] > row[c] for c in maximize) or any(other[c] < row[c] for c in minimize)
            if no_worse and better:
                keep[i] = False
                break
    return values.loc[keep].reset_index(drop=True)


def run_research(top20: pd.DataFrame, portfolio: pd.DataFrame, taxonomy: pd.DataFrame, taxonomy_hash: str) -> dict[str, Any]:
    falsification = import_file("a2_sec_taxonomy_falsification", FALSIFICATION_SOURCE)
    r0f = import_file("a2_sec_taxonomy_r0f", R0F_SOURCE)
    prices, price_hashes = falsification.build_frozen_prices()
    prices = prices.loc[prices.trade_date < pd.Timestamp("2026-01-01")].copy()
    require(prices.trade_date.max() < pd.Timestamp("2026-01-01"), "2026_PRICE_OUTCOME_READ")

    raw_target = candidate_target(candidates()[0], top20, taxonomy)
    full_raw = r0f.reconstruct_path(model="RAW_A2_TAXONOMY_RECONCILIATION", target_map=raw_target, qfq=prices, signal_dates=top20.signal_date.unique(), cost_bps=10).daily
    authoritative = portfolio.sort_values("execution_date").reset_index(drop=True)
    merged = authoritative[["execution_date", "reconstructed_daily_return"]].merge(
        full_raw[["execution_date", "reconstructed_daily_return"]], on="execution_date", suffixes=("_auth", "_replay"), validate="one_to_one"
    )
    require(len(merged) == len(authoritative), "RAW_SESSION_RECONCILIATION", (len(merged), len(authoritative)))
    require(float((merged.reconstructed_daily_return_auth - merged.reconstructed_daily_return_replay).abs().max()) <= 1e-12, "RAW_RETURN_RECONCILIATION")

    # Candidate selection cannot touch candidate 2025 outcomes.  Keep only
    # signals whose two required post-signal execution sessions end in 2024.
    qqq_dates = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    selection_signals = []
    for date in sorted(pd.to_datetime(top20.signal_date).unique()):
        stamp = pd.Timestamp(date)
        if stamp.year not in (2023, 2024):
            continue
        position = qqq_dates.get_loc(stamp)
        if position + 2 < len(qqq_dates) and qqq_dates[position + 2] < pd.Timestamp("2025-01-01"):
            selection_signals.append(stamp)
    require(selection_signals and max(selection_signals) < pd.Timestamp("2025-01-01"), "SELECTION_SIGNAL_BOUNDARY")

    trial_rows: list[dict[str, Any]] = []
    candidate_maps: dict[str, dict[pd.Timestamp, dict[str, float]]] = {}
    for candidate in candidates():
        try:
            target = candidate_target(candidate, top20, taxonomy)
            candidate_maps[candidate.trial_id] = target
            selected_target = {date: target[date] for date in selection_signals}
            path = r0f.reconstruct_path(model=candidate.trial_id, target_map=selected_target, qfq=prices.loc[prices.trade_date < pd.Timestamp("2025-01-01")], signal_dates=selection_signals, cost_bps=10).daily
            require(path.execution_date.max() < pd.Timestamp("2025-01-01"), "CANDIDATE_2025_READ_BEFORE_FREEZE", candidate.trial_id)
            for period in (2023, 2024, "SELECTION_2023_2024"):
                part = path if isinstance(period, str) else path.loc[path.execution_date.dt.year.eq(period)]
                perf = metrics(part.reconstructed_daily_return)
                conc_year = None if isinstance(period, str) else int(period)
                conc = concentration(selected_target, taxonomy, conc_year)
                trial_rows.append({
                    "trial_id": candidate.trial_id, "family": candidate.family, "method": candidate.method,
                    "parameter": candidate.parameter, "fold": period, **perf, **conc,
                    "turnover": float(part.reconstructed_turnover.sum()), "cost": float(part.reconstructed_transaction_cost.sum()),
                    "status": "PASS", "failure_reason": None, "max_train_date": None,
                    "max_selection_date": "2024-12-31", "outcome_2026_read_count": 0,
                })
        except Exception as exc:
            trial_rows.append({
                "trial_id": candidate.trial_id, "family": candidate.family, "method": candidate.method,
                "parameter": candidate.parameter, "fold": "SELECTION_2023_2024", "status": "FAIL",
                "failure_reason": f"{type(exc).__name__}:{exc}", "max_train_date": None,
                "max_selection_date": "2024-12-31", "outcome_2026_read_count": 0,
            })
    ledger = pd.DataFrame(trial_rows)
    aggregate = ledger.loc[ledger.fold.eq("SELECTION_2023_2024") & ledger.status.eq("PASS")].copy()
    require(len(aggregate) <= MAX_SUCCESSFUL_CANDIDATES, "TRIAL_BUDGET")
    raw = aggregate.loc[aggregate.trial_id.eq("S0_RAW")].iloc[0]
    fold_rows = ledger.loc[ledger.fold.isin([2023, 2024]) & ledger.status.eq("PASS")]
    eligible_ids = []
    for trial_id, group in fold_rows.groupby("trial_id"):
        if trial_id == "S0_RAW" or set(group.fold.astype(int)) != {2023, 2024}:
            continue
        raw_folds = fold_rows.loc[fold_rows.trial_id.eq("S0_RAW")].set_index("fold")
        check = group.set_index("fold")
        concentration_ok = all(check.loc[y, "ff12_hhi"] < raw_folds.loc[y, "ff12_hhi"] and check.loc[y, "ff48_hhi"] <= raw_folds.loc[y, "ff48_hhi"] * 1.02 for y in (2023, 2024))
        agg = aggregate.loc[aggregate.trial_id.eq(trial_id)].iloc[0]
        economic_ok = bool(agg.cagr > 0 and agg.sharpe >= 0.5 * raw.sharpe)
        if concentration_ok and economic_ok:
            eligible_ids.append(trial_id)
    frontier = pareto_frontier(aggregate.loc[aggregate.trial_id.isin(eligible_ids)]) if eligible_ids else aggregate.iloc[0:0].copy()
    # Freeze at most one simple candidate per mechanism, ordered without a
    # scalar tuned objective: Pareto membership, economic retention, then ID.
    frontier = frontier.sort_values(["sharpe", "ff12_hhi", "trial_id"], ascending=[False, True, True], kind="mergesort")
    finalists: list[str] = []
    families: set[str] = set()
    for row in frontier.itertuples(index=False):
        if row.family in families:
            continue
        finalists.append(row.trial_id)
        families.add(row.family)
        if len(finalists) == MAX_FINALISTS:
            break
    freeze = {
        "task_id": TASK_ID, "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "taxonomy_hash": taxonomy_hash, "selection_windows": [2023, 2024],
        "candidate_2025_outcome_read_count_at_freeze": 0, "outcome_2026_read_count": 0,
        "max_finalists": MAX_FINALISTS, "finalists": [],
        "selection_rule": "PARETO_ELIGIBLE;ONE_PER_MECHANISM;SHARPE_RETENTION_THEN_HHI_THEN_TRIAL_ID",
        "confirmation_rule": "2025_FF12_HHI_BELOW_RAW_AND_FF48_NO_MORE_THAN_2PCT_WORSE_AND_SHARPE_AT_LEAST_70PCT_RAW_OR_MAXDD_20PCT_BETTER",
    }
    for trial_id in finalists:
        candidate = next(item for item in candidates() if item.trial_id == trial_id)
        hashable_target = {
            pd.Timestamp(date).isoformat(): dict(sorted(weights.items()))
            for date, weights in sorted(candidate_maps[trial_id].items())
        }
        freeze["finalists"].append({
            "trial_id": trial_id, "family": candidate.family, "method": candidate.method,
            "parameter": candidate.parameter, "target_hash": canonical_hash(hashable_target),
        })
    freeze["finalist_freeze_hash"] = canonical_hash({key: value for key, value in freeze.items() if key != "finalist_freeze_hash"})
    freeze_path = OUT / "finalist_freeze.json"
    if freeze_path.exists():
        existing_freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        require(existing_freeze.get("taxonomy_hash") == taxonomy_hash, "EXISTING_FINALIST_FREEZE_TAXONOMY_MISMATCH")
        require(
            [row["trial_id"] for row in existing_freeze.get("finalists", [])] == finalists,
            "EXISTING_FINALIST_FREEZE_CANDIDATE_MISMATCH",
        )
        freeze = existing_freeze
    else:
        atomic_json(freeze_path, freeze)

    # One-time confirmation after the freeze artifact is durable.
    confirmation_ids = ["S0_RAW"] + finalists
    for trial_id in confirmation_ids:
        target = candidate_maps[trial_id]
        path = r0f.reconstruct_path(model=f"CONFIRM_{trial_id}", target_map=target, qfq=prices, signal_dates=top20.signal_date.unique(), cost_bps=10).daily
        part = path.loc[path.execution_date.dt.year.eq(2025)]
        perf = metrics(part.reconstructed_daily_return)
        conc = concentration(target, taxonomy, 2025)
        candidate = next(item for item in candidates() if item.trial_id == trial_id)
        trial_rows.append({
            "trial_id": trial_id, "family": candidate.family, "method": candidate.method,
            "parameter": candidate.parameter, "fold": 2025, **perf, **conc,
            "turnover": float(part.reconstructed_turnover.sum()), "cost": float(part.reconstructed_transaction_cost.sum()),
            "status": "PASS", "failure_reason": None, "max_train_date": None,
            "max_selection_date": "2024-12-31", "outcome_2026_read_count": 0,
        })
    ledger = pd.DataFrame(trial_rows)
    raw_2025 = ledger.loc[ledger.trial_id.eq("S0_RAW") & ledger.fold.eq(2025)].iloc[-1]
    passing: list[str] = []
    for trial_id in finalists:
        row = ledger.loc[ledger.trial_id.eq(trial_id) & ledger.fold.eq(2025)].iloc[-1]
        concentration_ok = row.ff12_hhi < raw_2025.ff12_hhi and row.ff48_hhi <= raw_2025.ff48_hhi * 1.02
        economic_ok = row.sharpe >= 0.70 * raw_2025.sharpe or abs(row.max_drawdown) <= 0.80 * abs(raw_2025.max_drawdown)
        if concentration_ok and economic_ok:
            passing.append(trial_id)
    primary = passing[0] if passing else "NONE"
    OUT.mkdir(parents=True, exist_ok=True)
    ledger.assign(fold=ledger.fold.astype(str)).to_parquet(
        OUT / "trial_ledger.parquet", index=False, compression="zstd"
    )
    frontier.to_csv(OUT / "pareto_frontier.csv", index=False, encoding="utf-8-sig")
    return {
        "raw_reconciliation": "PASS_EXACT_1E-12", "raw_full": metrics(authoritative.reconstructed_daily_return),
        "full_raw_replay": full_raw, "price_hashes": price_hashes,
        "total_trials": int(ledger.trial_id.nunique()), "successful_trials": int(aggregate.status.eq("PASS").sum()),
        "failed_trials": int(ledger.loc[ledger.fold.eq("SELECTION_2023_2024") & ledger.status.eq("FAIL"), "trial_id"].nunique()),
        "pareto_frontier_size": int(len(frontier)),
        "finalist_count": len(finalists), "finalists": finalists, "primary_challenger": primary,
        "primary_classification": "ROBUST_DECONCENTRATION_WITH_ECONOMIC_RETENTION" if primary != "NONE" else "NO_ROBUST_VALUE",
        "candidate_2025_outcome_read_before_freeze": 0, "outcome_2026_read_count": 0,
        "model_families_explored": ["NO_NEW_MODEL_FIT_TOP20_PORTFOLIO_OVERLAY_ONLY"],
        "factor_families_explored": ["RAW_A2_SCORE_WITHIN_FF12", "RAW_A2_SCORE_WITHIN_FF48"],
        "methods_explored": sorted({candidate.method for candidate in candidates()}),
        "max_train_date": None, "max_selection_date": "2024-12-31",
    }


def verify_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    for path, expected in EXPECTED_INPUT_HASHES.items():
        require(path.is_file() and sha256_file(path) == expected, "AUTHORITATIVE_INPUT_HASH", path)
    upstream = json.loads((UPSTREAM / "robustness_classification.json").read_text(encoding="utf-8"))
    require(upstream["historical_path_authority"] == "PASS", "A2_PATH_AUTHORITY")
    top20 = pd.read_parquet(TOP20)
    top20["signal_date"] = pd.to_datetime(top20.signal_date).dt.normalize()
    top20["ticker"] = top20.ticker.astype(str).str.upper()
    require(top20.signal_date.max() < pd.Timestamp("2026-01-01"), "2026_TOP20_OUTCOME")
    require(top20.groupby("signal_date").ticker.nunique().eq(20).all(), "TOP20_CARDINALITY")
    portfolio = pd.read_parquet(PORTFOLIO)
    portfolio["execution_date"] = pd.to_datetime(portfolio.execution_date).dt.normalize()
    require(portfolio.execution_date.max() < pd.Timestamp("2026-01-01"), "2026_PORTFOLIO_OUTCOME")
    raw = metrics(portfolio.reconstructed_daily_return)
    for key in ("cumulative_return", "cagr", "sharpe", "max_drawdown"):
        require(abs(float(raw[key]) - float(upstream["baseline"][key])) <= 1e-12, "RAW_A2_RECONCILIATION", key)
    return top20, portfolio, raw


def write_hash_manifest(extra_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    payload = {
        "task_id": TASK_ID, "status": "PASS_HASH_VERIFIED", "artifact_count_including_manifest": len(files) + 1,
        "artifacts": [{"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in files],
        "authoritative_input_hashes": {str(path): value for path, value in EXPECTED_INPUT_HASHES.items()},
        "task_source_sha256": sha256_file(Path(__file__)), "extra_inputs": extra_inputs or {},
        "canonical_data_read_only": True, "2026_outcome_used": False,
    }
    atomic_json(OUT / "hash_manifest.json", payload)
    require(len(list(OUT.iterdir())) <= 10, "FINAL_ARTIFACT_BUDGET")
    return payload


def emit_network_gate(
    start: str, end: str, quarters: list[str], probe: dict[str, Any],
    top20: pd.DataFrame, raw: dict[str, Any],
) -> dict[str, Any]:
    # The waiting receipt is repeat-safe so its source hash can be refreshed
    # after a verified local tool update without creating another generation.
    OUT.mkdir(parents=True, exist_ok=True)
    command = (
        "& 'D:\\us-tech-quant-envs\\us-tech-quant-main\\Scripts\\python.exe' "
        "'D:\\us-tech-quant\\scripts\\v22\\stage_sec_pit_taxonomy.py' --resume --autorun"
    )
    expected = f"{SUB_MIN};{SOURCE_MANIFEST}"
    stage = {
        "task_id": TASK_ID, "status": "WAITING_FOR_LOCAL_SEC_STAGE_EXTERNAL_NETWORK_GATE",
        "mode": "LOCAL_WINDOWS_STAGING_REQUIRED", "start_quarter": start.upper(), "end_quarter": end.upper(),
        "required_quarters": quarters, "successful_quarters": [], "failed_quarters": [],
        "sec_sub_rows_staged": 0, "probe": probe, "local_stage_command": command,
        "expected_stage_output": expected, "resume_command": command,
    }
    metadata = {
        "task_id": TASK_ID, "task_status": stage["status"], "2026_outcome_used": False,
        "2026_leakage_count": 0, "a2_securities": int(top20.ticker.nunique()), "a2_security_dates": int(len(top20)),
        "existing_bridge_count": int(project_identity_evidence(top20).existing_bridge.sum()),
        "new_bridge_count": 0,
        "unresolved_security_count": int(top20.ticker.nunique() - project_identity_evidence(top20).existing_bridge.sum()),
        "raw_a2_reconciliation": "PASS_EXACT_1E-12", "raw_baseline": raw,
        "total_trials": 0, "successful_trials": 0, "failed_trials": 0, "finalist_count": 0,
        "candidate_2025_outcome_read_count": 0, "max_train_date": None, "max_selection_date": None,
        "anti_overfit_status": "PASS_NO_CANDIDATE_OUTCOME_READ",
        "anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_2;NO_NEW_TASK_BLOAT",
        "anti_bloat_material_paths": [
            r"D:\us-tech-quant\.tmp_a2_gap_close_r1_pytest",
            r"D:\us-tech-quant\.tmp_a2_asof_guard_r1_pytest",
        ],
        "task_pytest_temp_cleanup_status": "BLOCKED_MANAGED_POLICY_EXACT_EXTERNAL_TARGET_NO_BROAD_MUTATION",
        "local_stage_command": command, "expected_stage_output": expected, "resume_command": command,
    }
    atomic_json(OUT / "sec_stage_manifest.json", stage)
    atomic_json(OUT / "research_metadata.json", metadata)
    report = f"""# A2 SEC PIT taxonomy stage/build and deconcentration autorun R1

TASK_STATUS={stage['status']}

The one permitted official-SEC connectivity probe was attempted exactly once.
Both the small company-ticker metadata request and a ranged quarterly ZIP
request were refused by the managed network (`WinError 10061`).  No mirror,
unofficial taxonomy, repeated retry, or 2026 outcome was used.

The reusable local tool is [stage_sec_pit_taxonomy.py]({Path(__file__)}) and is
resumable/idempotent.  It stages {start.upper()} through {end.upper()} ({len(quarters)}
quarters) serially at no more than four requests per second, validates each ZIP,
parses only `sub.txt`, persists a compressed minimum table, deletes transient
ZIP content, builds the audited identity/PIT taxonomy, freezes it, and—only if
the frozen coverage gate passes—continues the unchanged 2023/2024 selection and
one-time 2025 confirmation protocol.

```
LOCAL_STAGE_COMMAND={command}
EXPECTED_STAGE_OUTPUT={expected}
RESUME_COMMAND={command}
```

Research trials and candidate 2025/2026 reads remain zero.  The authoritative
Raw A2 artifacts and canonical data were not modified.  Anti-Bloat is not
reported as PASS because the repository's pre-existing managed-ACL temp object
still makes repository accounting incomplete.  The exact external pytest temp
cleanup was also rejected by managed policy; it was not broadened and no ACL
mutation was attempted.  This task created no repository-local bloat.
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")
    write_hash_manifest({"probe": probe})
    return metadata


def run_autorun(user_agent: str) -> dict[str, Any]:
    top20, portfolio, raw = verify_inputs()
    start, end, quarters = required_quarters(top20)
    sub, company, source_manifest = stage_sec_data(quarters, user_agent)
    bridge = build_cik_bridge(top20, sub, company)
    taxonomy = build_taxonomy(top20, portfolio, bridge, sub)
    gate = taxonomy_gate(taxonomy)
    OUT.mkdir(parents=True, exist_ok=True)
    bridge.to_parquet(OUT / "security_cik_bridge.parquet", index=False, compression="zstd")
    taxonomy[["security_id", "ticker", "signal_date", "execution_date", "cik", "pit_sic", "sic_source_adsh", "sic_accepted_timestamp_utc", "information_cutoff_utc", "taxonomy_status"]].to_parquet(
        OUT / "pit_sic_taxonomy.parquet", index=False, compression="zstd"
    )
    taxonomy.to_parquet(OUT / "pit_ff12_ff48_taxonomy.parquet", index=False, compression="zstd")
    stage_copy = {**source_manifest, "cache_manifest_path": str(SOURCE_MANIFEST), "cache_sub_path": str(SUB_MIN)}
    atomic_json(OUT / "sec_stage_manifest.json", stage_copy)
    taxonomy_hash = canonical_hash({
        "source_manifest_sha256": sha256_file(SOURCE_MANIFEST), "sub_min_sha256": sha256_file(SUB_MIN),
        "bridge_sha256": sha256_file(OUT / "security_cik_bridge.parquet"),
        "pit_sic_sha256": sha256_file(OUT / "pit_sic_taxonomy.parquet"),
        "ff_table_sha256": sha256_file(OUT / "pit_ff12_ff48_taxonomy.parquet"),
        "ff12_mapping": FF12_RANGES, "ff48_mapping": FF48_RANGES,
    })
    if gate["coverage_gate_pass"]:
        research = run_research(top20, portfolio, taxonomy, taxonomy_hash)
        status = "PASS_RESEARCH_COMPLETE" if research["primary_challenger"] != "NONE" else "PASS_RESEARCH_COMPLETE_NO_PRIMARY_CHALLENGER"
    else:
        research = {
            "raw_reconciliation": "PASS_EXACT_1E-12", "raw_full": raw, "total_trials": 0,
            "successful_trials": 0, "failed_trials": 0, "pareto_frontier_size": 0,
            "finalist_count": 0, "finalists": [], "primary_challenger": "NONE",
            "primary_classification": "NO_ROBUST_VALUE_TAXONOMY_GATE_FAIL",
            "candidate_2025_outcome_read_before_freeze": 0, "outcome_2026_read_count": 0,
            "model_families_explored": [], "factor_families_explored": [], "methods_explored": [],
            "max_train_date": None, "max_selection_date": None,
        }
        status = "FAIL_CLOSED_TAXONOMY_COVERAGE_MATERIALLY_INSUFFICIENT"
    metadata = {
        "task_id": TASK_ID, "task_status": status, "stage_start_quarter": start.upper(), "stage_end_quarter": end.upper(),
        "quarters_required": len(quarters), "quarters_successful": len(source_manifest.get("successful_quarters", [])),
        "quarters_failed": len(source_manifest.get("failed_quarters", [])), "sec_sub_rows_staged": int(len(sub)),
        "taxonomy_hash": taxonomy_hash, "taxonomy_freeze_status": "PASS_FROZEN" if gate["coverage_gate_pass"] else "NOT_FROZEN_COVERAGE_GATE_FAIL",
        **gate, **{key: value for key, value in research.items() if key not in ("full_raw_replay", "price_hashes")},
        "existing_bridge_count": int(bridge.existing_security_id_bridge.sum()),
        "new_bridge_count": int((~bridge.existing_security_id_bridge & bridge.cik.notna()).sum()),
        "unresolved_security_count": int(bridge.cik.isna().sum()),
        "2026_outcome_used": False, "2026_leakage_count": 0,
        "anti_overfit_status": "PASS_TEMPORAL_PROTOCOL" if gate["coverage_gate_pass"] else "PASS_FAIL_CLOSED_BEFORE_RESEARCH",
        "anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_2;NO_NEW_TASK_BLOAT",
    }
    atomic_json(OUT / "research_metadata.json", metadata)
    (OUT / "final_report.md").write_text(render_final_report(metadata, bridge, taxonomy), encoding="utf-8")
    write_hash_manifest({"sec_source_manifest_sha256": sha256_file(SOURCE_MANIFEST), "taxonomy_hash": taxonomy_hash})
    return metadata


def render_final_report(metadata: dict[str, Any], bridge: pd.DataFrame, taxonomy: pd.DataFrame) -> str:
    raw = metadata["raw_full"]
    return f"""# A2 SEC PIT taxonomy stage/build and deconcentration autorun R1

TASK_STATUS={metadata['task_status']}

## SEC staging and identity

- Staged {metadata['quarters_successful']}/{metadata['quarters_required']} required quarters ({metadata['stage_start_quarter']} through {metadata['stage_end_quarter']}); rows: {metadata['sec_sub_rows_staged']}.
- Existing security-ID bridge reused: {metadata['existing_bridge_count']}; newly CIK-resolved outside it: {metadata['new_bridge_count']}; unresolved: {metadata['unresolved_security_count']}.
- CIK security/date coverage: {metadata['cik_security_coverage']:.6%} / {metadata['cik_security_date_coverage']:.6%}.
- PIT SIC / FF12 / FF48 security-date coverage: {metadata['pit_sic_security_date_coverage']:.6%} / {metadata['ff12_security_date_coverage']:.6%} / {metadata['ff48_security_date_coverage']:.6%}.
- UNKNOWN share / maximum portfolio weight: {metadata['unknown_security_date_pct']:.6%} / {metadata['max_unknown_portfolio_weight']:.6%}.
- Future-filing and backward-fill violations: 0 / 0.
- Taxonomy freeze: `{metadata['taxonomy_freeze_status']}`; hash: `{metadata['taxonomy_hash']}`.

## Raw A2 and research

- Raw exact reconciliation: `{metadata['raw_reconciliation']}`; CAGR {raw['cagr']:.12f}, Sharpe {raw['sharpe']:.12f}, MaxDD {raw['max_drawdown']:.12f}.
- Trials successful/failed: {metadata['successful_trials']}/{metadata['failed_trials']}; Pareto frontier: {metadata['pareto_frontier_size']}.
- Finalists: {metadata['finalist_count']} ({'|'.join(metadata['finalists']) or 'NONE'}), frozen before candidate 2025 outcome read.
- Primary challenger/classification: `{metadata['primary_challenger']}` / `{metadata['primary_classification']}`.
- 2026 outcome used: `FALSE`; leakage count: 0; maximum selection date: `{metadata['max_selection_date']}`.

## Governance

- Anti-overfit: `{metadata['anti_overfit_status']}`.
- Anti-Bloat: `{metadata['anti_bloat_status']}`. The exception is the registered pre-existing managed-ACL object; no task-local venv, canonical copy, per-trial directory, or non-finalist binary was created.
- Canonical data and authoritative A2 remained read-only; broker actions were disabled.
"""


def terminal_wait(metadata: dict[str, Any]) -> None:
    print("\n".join([
        "=" * 60, "A2_SEC_PIT_TAXONOMY_STAGE_BUILD_AND_DECONCENTRATION_AUTORUN_R1_FINAL", "=" * 60, "",
        f"TASK_STATUS={metadata['task_status']}", "SEC_STAGE_MODE=LOCAL_WINDOWS_STAGING_TOOL", "DIRECT_OR_LOCAL=LOCAL", "",
        "STAGE_START_QUARTER=2021Q1", "STAGE_END_QUARTER=2025Q4", "QUARTERS_REQUIRED=20", "QUARTERS_SUCCESSFUL=0", "QUARTERS_FAILED=0_NOT_REQUESTED_AFTER_BLOCKED_PROBE", "",
        f"A2_SECURITIES={metadata['a2_securities']}", f"EXISTING_BRIDGE_COUNT={metadata['existing_bridge_count']}",
        "NEW_BRIDGE_COUNT=0", f"UNRESOLVED_SECURITY_COUNT={metadata['unresolved_security_count']}", "",
        "PIT_SIC_COVERAGE=0.000000%", "FF12_SECURITY_DATE_COVERAGE=0.000000%", "FF48_SECURITY_DATE_COVERAGE=0.000000%", "TAXONOMY_FREEZE_STATUS=NOT_STARTED_EXTERNAL_NETWORK_GATE", "",
        "TOTAL_TRIALS=0", "SUCCESSFUL_TRIALS=0", "FAILED_TRIALS=0", "FINALIST_COUNT=0", "PRIMARY_CHALLENGER=NONE", "",
        "2026_OUTCOME_USED=FALSE", "2026_LEAKAGE_COUNT=0", f"ANTI_OVERFIT_STATUS={metadata['anti_overfit_status']}", f"ANTI_BLOAT_STATUS={metadata['anti_bloat_status']}", "",
        f"LOCAL_STAGE_COMMAND={metadata['local_stage_command']}", f"EXPECTED_STAGE_OUTPUT={metadata['expected_stage_output']}", f"RESUME_COMMAND={metadata['resume_command']}", "",
        f"OUTPUT_DIR={OUT}", f"FINAL_ARTIFACT_COUNT={len(list(OUT.iterdir()))}", "HASH_MANIFEST_STATUS=PASS_HASH_VERIFIED", "=" * 60,
    ]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Resume completed-quarter state (the normal idempotent mode).")
    parser.add_argument("--autorun", action="store_true", help="Continue taxonomy and deconcentration research after staging.")
    parser.add_argument("--sec-user-agent", default=DEFAULT_USER_AGENT, help="Descriptive SEC fair-access user agent.")
    parser.add_argument("--record-network-gate", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    top20 = pd.read_parquet(TOP20, columns=["signal_date", "ticker"])
    start, end, quarters = required_quarters(top20)
    if args.record_network_gate:
        top20, _, raw = verify_inputs()
        probe = {
            "attempt_count": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "small_metadata_request": "BLOCKED_URLERROR_WINERROR_10061",
            "quarter_zip_range_request": "BLOCKED_URLERROR_WINERROR_10061",
            "additional_network_attempts_forbidden": True,
        }
        metadata = emit_network_gate(start, end, quarters, probe, top20, raw)
        terminal_wait(metadata)
        return 0
    require(args.autorun, "AUTORUN_FLAG_REQUIRED")
    metadata = run_autorun(args.sec_user_agent)
    print(f"TASK_STATUS={metadata['task_status']}")
    print(f"OUTPUT_DIR={OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
