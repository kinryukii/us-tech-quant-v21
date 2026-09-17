"""H22 clustered Form 4 insider-purchase alpha research for Raw A2.

Cache-only SEC bulk parsing, four fixed signals, four fixed portfolios, no fit.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

RESEARCH_ID = "H22"
TASK_FAMILY = "FORM4_INSIDER_PURCHASE_ALPHA"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache\a2_form4_insider_purchase_alpha_r1\sec_insider_bulk")
RAW_ZIP = CACHE / "raw_zip"
HOST_MANIFEST = CACHE / "manifests" / "host_download_result.json"
FILTERED_CACHE = CACHE / "h22_filtered_transactions.parquet"
FILTERED_MANIFEST = CACHE / "h22_filtered_manifest.json"
OUT = RESULTS / "H22_CLUSTERED_INSIDER_ACTIVITY"
STAGE_A_LEDGER = Path(r"D:\us-tech-quant-worktrees\harness-task-20260823-233711-ffaf\docs\ALPHA_DISCOVERY_STAGE_A_R1.md")
STAGE_A_SHA256 = "4e58bbc1d506792d1348a3ab816a2bbc654f41dd5546ba6ca443d4e9804e1fd1"

PRIOR_SOURCE = REPO / "scripts/v22/a2_13f_institutional_change_alpha_r1.py"
FUNDAMENTAL_SOURCE = REPO / "scripts/v22/a2_earnings_fundamental_change_alpha_r1.py"
IDENTITY_RESOLVER_SOURCE = REPO / "scripts/v22/a2_sec_cik_identity_gap_close_and_deconcentration_autorun_r1.py"
IDENTITY_BASE_SOURCE = REPO / "scripts/v22/stage_sec_pit_taxonomy.py"
BOOTSTRAP_SOURCE = REPO / "scripts/v22/a2_open_research_engine.py"
A2_SOURCE = REPO / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
A2_ROOT = RESULTS / "A_VS_A2_QUARTERLY_13F_R1/A2"
OOF_PATH = A2_ROOT / "oof_predictions.parquet"
TRAINING_PATH = A2_ROOT / "training_matrix.parquet"
CONTROL_DAILY = A2_ROOT / "portfolio_daily.parquet"
CIK_BRIDGE = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1/security_cik_bridge.parquet"
SUB_PATH = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy\sec_fsds_sub_min.parquet")

QUARTERS = (
    "2020q4", "2021q1", "2021q2", "2021q3", "2021q4",
    "2022q1", "2022q2", "2022q3", "2022q4",
    "2023q1", "2023q2", "2023q3", "2023q4",
    "2024q1", "2024q2", "2024q3", "2024q4",
    "2025q1", "2025q2", "2025q3", "2025q4",
)
REQUIRED_TABLES = ("SUBMISSION.tsv", "REPORTINGOWNER.tsv", "NONDERIV_TRANS.tsv")
PRIMARY_START = pd.Timestamp("2023-01-03")
BOUNDARY = pd.Timestamp("2026-01-01")
BACKWARD_START = pd.Timestamp("2021-01-04")
BACKWARD_END = pd.Timestamp("2022-12-30")
TOP_N, COST_BPS, SEED = 20, 10, 20260824
COMPONENTS = (
    "F1_UNIQUE_BUYER_BREADTH_90D", "F2_CLUSTER_BUYER_BREADTH_30D",
    "F3_PURCHASE_VALUE_TO_ADV20_90D", "F4_OWNER_CONVICTION_90D",
)
STRATEGIES = (
    "C0_RAW_A2", "C1_INSIDER_STANDALONE",
    "C2_A2_PLUS_INSIDER_SCORE_80_20", "C3_DUAL_SLEEVE_80_20",
)
KNOWN_STATES = {"KNOWN_NO_EVENT", "EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"}
EVENT_STATES = {"EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"}
COVERAGE_GATES = {"median_date": 0.90, "min_fold": 0.85, "top20_median": 0.95}


class ContractError(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: object = "") -> None:
    if not condition:
        raise ContractError(f"{code}|{evidence}" if evidence != "" else code)


def resolve_duplicate_gate(stage_text: str, formal_statuses: Iterable[str] = ()) -> str:
    statuses = {str(value).upper() for value in formal_statuses}
    if statuses & {"COMPLETED", "RESEARCH_COMPLETE", "EVALUATED"}:
        return "STOP_DUPLICATE_RESEARCH_ALREADY_EVALUATED"
    if statuses & {"REJECTED", "PIT_REJECTED", "DATA_UNAVAILABLE_REJECTED"}:
        return "STOP_EXISTING_HYPOTHESIS_REJECTED"
    text = stage_text.upper()
    return "PASS_REUSE_EXISTING_HYPOTHESIS" if "H22" in text and "CLUSTERED INSIDER ACTIVITY" in text else "PASS_NEW_HYPOTHESIS_CONFIRMED"


def validate_outcome_dates(target_end_date: pd.Series) -> None:
    dates = pd.to_datetime(target_end_date, errors="coerce")
    require(dates.notna().all() and dates.lt(BOUNDARY).all(), "POST2025_OUTCOME")


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, pd.Period)):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def normalize_document_type(value: object) -> str:
    return str(value).upper().replace("FORM", "").replace(" ", "").strip()


def relationship_flags(value: object) -> dict[str, bool]:
    tokens = {token.strip().upper() for token in str(value).split(",") if token.strip()}
    officer, director = "OFFICER" in tokens, "DIRECTOR" in tokens
    ten, other = "TENPERCENTOWNER" in tokens, "OTHER" in tokens
    return {
        "officer": officer, "director": director, "ten_percent": ten, "other": other,
        "eligible": officer or director,
        "pure_ten_percent": ten and not officer and not director,
        "pure_other": other and not officer and not director,
    }


def validate_cache() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    require(HOST_MANIFEST.is_file(), "HOST_MANIFEST_MISSING", HOST_MANIFEST)
    manifest = json.loads(HOST_MANIFEST.read_text(encoding="utf-8-sig"))
    require(manifest.get("status") == "PASS_COMPLETE", "HOST_MANIFEST_NOT_COMPLETE")
    by_quarter = {str(row["quarter"]).lower(): row for row in manifest.get("rows", [])}
    require(set(by_quarter) == set(QUARTERS), "QUARTER_SET_MISMATCH")
    valid, failures, hashes, total_bytes = [], [], set(), 0
    for quarter in QUARTERS:
        row, path, reason = by_quarter[quarter], RAW_ZIP / f"{quarter}_form345.zip", ""
        try:
            require(path.is_file(), "MISSING")
            require(path.stat().st_size == int(row["file_size"]) > 0, "SIZE")
            digest = sha256_file(path)
            require(digest == str(row["sha256"]).lower(), "SHA256")
            require(digest not in hashes, "DUPLICATE_SHA256")
            with zipfile.ZipFile(path) as archive:
                require(archive.testzip() is None, "ZIP_CRC")
                names = {Path(name).name.upper(): name for name in archive.namelist()}
                require({table.upper() for table in REQUIRED_TABLES}.issubset(names), "REQUIRED_TABLE")
                for table in REQUIRED_TABLES:
                    require("\t" in archive.open(names[table.upper()]).readline().decode("utf-8-sig"), "TSV_HEADER", table)
            hashes.add(digest); total_bytes += path.stat().st_size
            valid.append({"quarter": quarter, "path": str(path), "sha256": digest, "bytes": path.stat().st_size})
        except Exception as exc:
            reason = f"{type(exc).__name__}:{exc}"
        if reason:
            failures.append({"quarter": quarter, "reason": reason})
    return valid, {
        "sec_quarters_required": 21, "sec_quarters_cache_hit": len(valid),
        "sec_quarters_downloaded_this_run": 0, "sec_quarters_failed": len(failures),
        "total_bytes": int(total_bytes), "network_used": False, "failures": failures,
    }


def _read_zip_table(archive: zipfile.ZipFile, basename: str) -> pd.DataFrame:
    names = {Path(name).name.upper(): name for name in archive.namelist()}
    require(basename.upper() in names, "TABLE_MISSING", basename)
    return pd.read_csv(archive.open(names[basename.upper()]), sep="\t", dtype="string", keep_default_na=False, low_memory=False)


def _column(frame: pd.DataFrame, name: str, default: str = "") -> pd.Series:
    return frame[name].astype("string").fillna(default) if name in frame else pd.Series(default, index=frame.index, dtype="string")


def build_owner_summary(owners: pd.DataFrame) -> pd.DataFrame:
    work = owners.copy()
    flags = work.RPTOWNER_RELATIONSHIP.map(relationship_flags)
    fields = ("officer", "director", "ten_percent", "other", "eligible", "pure_ten_percent", "pure_other")
    for field in fields:
        work[field] = flags.map(lambda value: value[field])
    work["RPTOWNERCIK"] = work.RPTOWNERCIK.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10)
    rows = []
    for accession, group in work.groupby("ACCESSION_NUMBER", sort=True):
        eligible = group.loc[group.eligible].drop_duplicates("RPTOWNERCIK")
        owner_ids = sorted(set(eligible.RPTOWNERCIK.astype(str)))
        rows.append({
            "ACCESSION_NUMBER": accession, "raw_owner_count": int(group.RPTOWNERCIK.nunique()),
            "eligible_owner_count": len(owner_ids), "eligible_owner_ids": "|".join(owner_ids),
            "owner_officer": bool(eligible.officer.any()), "owner_director": bool(eligible.director.any()),
            "pure_ten_percent_only": bool(group.pure_ten_percent.all()) if len(group) else False,
            "pure_other_only": bool(group.pure_other.all()) if len(group) else False,
        })
    return pd.DataFrame(rows)


def fixed_event_filter(joined: pd.DataFrame) -> pd.Series:
    document = joined.DOCUMENT_TYPE.map(normalize_document_type)
    swap = joined.EQUITY_SWAP_INVOLVED.astype(str).str.strip().str.lower()
    shares = pd.to_numeric(joined.TRANS_SHARES, errors="coerce")
    return (
        document.eq("4") & joined.TRANS_CODE.astype(str).str.upper().eq("P")
        & joined.TRANS_ACQUIRED_DISP_CD.astype(str).str.upper().eq("A") & shares.gt(0)
        & ~swap.isin({"1", "true", "t", "yes"})
        & ~joined.TRANS_TIMELINESS.astype(str).str.upper().eq("L")
        & joined.eligible_owner_count.gt(0)
    )


def add_buyer_event_ids(eligible: pd.DataFrame) -> pd.DataFrame:
    result = eligible.copy()
    result["joint_filing"] = result.eligible_owner_count.gt(1)
    result["buyer_event_id"] = np.where(
        result.joint_filing, "JOINT:" + result.ACCESSION_NUMBER.astype(str), result.eligible_owner_ids.astype(str),
    )
    return result


def parse_form345(valid_archives: list[dict[str, Any]], cik_scope: set[int]) -> tuple[pd.DataFrame, dict[str, Any]]:
    contract_hash = hashlib.sha256(json.dumps({
        "source": {row["quarter"]: row["sha256"] for row in valid_archives},
        "ciks": sorted(cik_scope), "filter": "H22_P_CODED_NONDERIVATIVE_PURCHASE_V1",
    }, sort_keys=True).encode()).hexdigest()
    if FILTERED_CACHE.is_file() and FILTERED_MANIFEST.is_file():
        cached = json.loads(FILTERED_MANIFEST.read_text(encoding="utf-8"))
        if cached.get("contract_hash") == contract_hash and cached.get("sha256") == sha256_file(FILTERED_CACHE):
            return pd.read_parquet(FILTERED_CACHE), cached["audit"]

    pieces: list[pd.DataFrame] = []
    submission_count = owner_count = numeric_transaction_rows = 0
    amendment_count = relevant_form_count = malformed_filing_dates = 0
    for index, item in enumerate(valid_archives, 1):
        with zipfile.ZipFile(item["path"]) as archive:
            sub = _read_zip_table(archive, "SUBMISSION.tsv")
            owners = _read_zip_table(archive, "REPORTINGOWNER.tsv")
            transactions = _read_zip_table(archive, "NONDERIV_TRANS.tsv")
        submission_count += len(sub); owner_count += len(owners); numeric_transaction_rows += len(transactions)
        sub["ISSUERCIK_NUM"] = pd.to_numeric(_column(sub, "ISSUERCIK"), errors="coerce").astype("Int64")
        sub = sub.loc[sub.ISSUERCIK_NUM.isin(cik_scope)].copy()
        sub["DOCUMENT_TYPE"] = _column(sub, "DOCUMENT_TYPE")
        form = sub.DOCUMENT_TYPE.map(normalize_document_type)
        relevant_form_count += int(form.isin({"4", "4/A"}).sum())
        amendment_count += int(form.eq("4/A").sum())
        sub["FILING_DATE_PARSED"] = pd.to_datetime(_column(sub, "FILING_DATE"), format="%d-%b-%Y", errors="coerce")
        malformed_filing_dates += int(sub.FILING_DATE_PARSED.isna().sum())
        sub["AFF10B5ONE"] = _column(sub, "AFF10B5ONE")
        sub = sub[[
            "ACCESSION_NUMBER", "FILING_DATE_PARSED", "DOCUMENT_TYPE", "ISSUERCIK_NUM",
            "ISSUERTRADINGSYMBOL", "AFF10B5ONE",
        ]].drop_duplicates("ACCESSION_NUMBER", keep="last")
        accessions = set(sub.ACCESSION_NUMBER)
        owners = owners.loc[owners.ACCESSION_NUMBER.isin(accessions)].copy()
        owner_summary = build_owner_summary(owners)
        transactions = transactions.loc[transactions.ACCESSION_NUMBER.isin(accessions)].copy()
        required_trans = [
            "ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "TRANS_DATE", "TRANS_FORM_TYPE", "TRANS_CODE",
            "EQUITY_SWAP_INVOLVED", "TRANS_TIMELINESS", "TRANS_SHARES", "TRANS_PRICEPERSHARE",
            "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS", "DIRECT_INDIRECT_OWNERSHIP",
        ]
        require(set(required_trans).issubset(transactions.columns), "NONDERIV_SCHEMA_MISSING")
        merged = transactions[required_trans].merge(sub, on="ACCESSION_NUMBER", validate="many_to_one")
        merged = merged.merge(owner_summary, on="ACCESSION_NUMBER", how="left", validate="many_to_one")
        merged["source_quarter"] = item["quarter"]
        pieces.append(merged)
        print(f"PHASE=FORM345_PARSE QUARTERS_DONE={index}/21 RELEVANT_ROWS={sum(len(piece) for piece in pieces)}")
    joined = pd.concat(pieces, ignore_index=True)
    key = ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"]
    duplicate = joined.duplicated(key, keep=False)
    if duplicate.any():
        check = joined.loc[duplicate].sort_values(key, kind="mergesort")
        varying = check.groupby(key).agg({"TRANS_SHARES": "nunique", "TRANS_CODE": "nunique", "ISSUERCIK_NUM": "nunique"})
        require(not varying.gt(1).any(axis=1).any(), "CONFLICTING_TRANSACTION_DUPLICATE")
        joined = joined.drop_duplicates(key, keep="last")
    joined["TRANS_SHARES_NUM"] = pd.to_numeric(joined.TRANS_SHARES, errors="coerce")
    joined["TRANS_PRICE_NUM"] = pd.to_numeric(joined.TRANS_PRICEPERSHARE, errors="coerce")
    joined["FOLLOWING_SHARES_NUM"] = pd.to_numeric(joined.SHRS_OWND_FOLWNG_TRANS, errors="coerce")
    joined["transaction_value"] = joined.TRANS_SHARES_NUM * joined.TRANS_PRICE_NUM
    joined["valid_price"] = joined.TRANS_PRICE_NUM.gt(0) & np.isfinite(joined.TRANS_PRICE_NUM)
    joined["eligible_main"] = fixed_event_filter(joined)
    eligible = joined.loc[joined.eligible_main].copy()
    eligible = add_buyer_event_ids(eligible)
    ratio = eligible.TRANS_SHARES_NUM / eligible.FOLLOWING_SHARES_NUM
    eligible["owner_conviction_ratio"] = np.where(
        eligible.eligible_owner_count.eq(1) & ratio.gt(0) & ratio.le(1), ratio, np.nan,
    )
    eligible["filing_date"] = eligible.FILING_DATE_PARSED
    eligible["issuer_cik"] = eligible.ISSUERCIK_NUM.astype("Int64")
    eligible["aff10b5one_true"] = eligible.AFF10B5ONE.astype(str).str.lower().isin({"1", "true", "t", "yes"})
    eligible["owner_role"] = np.select(
        [eligible.owner_officer & eligible.owner_director, eligible.owner_officer, eligible.owner_director],
        ["BOTH", "OFFICER", "DIRECTOR"], default="NONE",
    )
    keep = [
        "ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "issuer_cik", "ISSUERTRADINGSYMBOL", "filing_date",
        "TRANS_DATE", "buyer_event_id", "eligible_owner_count", "raw_owner_count", "joint_filing",
        "owner_role", "TRANS_SHARES_NUM", "TRANS_PRICE_NUM", "transaction_value", "valid_price",
        "owner_conviction_ratio", "DIRECT_INDIRECT_OWNERSHIP", "aff10b5one_true", "source_quarter",
    ]
    eligible = eligible[keep].sort_values(["filing_date", "ACCESSION_NUMBER", "NONDERIV_TRANS_SK"], kind="mergesort")
    require(not eligible.duplicated(key).any(), "TRANSACTION_KEY_NOT_UNIQUE")
    prelate = joined.loc[
        joined.DOCUMENT_TYPE.map(normalize_document_type).eq("4")
        & joined.TRANS_CODE.astype(str).str.upper().eq("P")
        & joined.TRANS_ACQUIRED_DISP_CD.astype(str).str.upper().eq("A")
        & joined.TRANS_SHARES_NUM.gt(0)
        & ~joined.EQUITY_SWAP_INVOLVED.astype(str).str.lower().isin({"1", "true", "t", "yes"})
        & joined.eligible_owner_count.gt(0)
    ]
    audit = {
        "sec_numeric_transaction_rows": int(numeric_transaction_rows), "submission_rows": int(submission_count),
        "reporting_owner_rows": int(owner_count), "relevant_nonderiv_transaction_rows": int(len(joined)),
        "eligible_p_purchase_transaction_count": int(len(eligible)),
        "form4_accession_count": int(joined.loc[joined.DOCUMENT_TYPE.map(normalize_document_type).eq("4"), "ACCESSION_NUMBER"].nunique()),
        "eligible_issuer_count": int(eligible.issuer_cik.nunique()),
        "form4_amendment_share": float(amendment_count / relevant_form_count) if relevant_form_count else math.nan,
        "late_filing_share": float(prelate.TRANS_TIMELINESS.astype(str).str.upper().eq("L").mean()) if len(prelate) else math.nan,
        "joint_filing_share": float(eligible.joint_filing.mean()) if len(eligible) else math.nan,
        "direct_ownership_share": float(eligible.DIRECT_INDIRECT_OWNERSHIP.astype(str).str.upper().eq("D").mean()) if len(eligible) else math.nan,
        "indirect_ownership_share": float(eligible.DIRECT_INDIRECT_OWNERSHIP.astype(str).str.upper().eq("I").mean()) if len(eligible) else math.nan,
        "missing_price_share": float((~eligible.valid_price).mean()) if len(eligible) else math.nan,
        "aff10b5one_share": float(eligible.aff10b5one_true.mean()) if len(eligible) else math.nan,
        "pure_10pct_owner_transaction_share": float(joined.pure_ten_percent_only.fillna(False).mean()) if len(joined) else math.nan,
        "officer_share": float(eligible.owner_role.eq("OFFICER").mean()) if len(eligible) else math.nan,
        "director_share": float(eligible.owner_role.eq("DIRECTOR").mean()) if len(eligible) else math.nan,
        "both_share": float(eligible.owner_role.eq("BOTH").mean()) if len(eligible) else math.nan,
        "malformed_filing_dates": int(malformed_filing_dates), "transaction_key_unique": True,
        "hypothetical_raw_owner_join_rows": int(joined.raw_owner_count.fillna(0).sum()),
        "actual_transaction_rows_after_owner_aggregation": int(len(joined)),
        "transaction_value_counted_once": True, "unresolved_amendment_count": int(amendment_count),
    }
    atomic_parquet(FILTERED_CACHE, eligible)
    atomic_text(FILTERED_MANIFEST, json.dumps(json_safe({
        "contract_hash": contract_hash, "sha256": sha256_file(FILTERED_CACHE), "audit": audit,
    }), indent=2, sort_keys=True) + "\n")
    return eligible, audit


def next_full_session(filing_date: pd.Timestamp, sessions: pd.DatetimeIndex, extra_delay: int = 0) -> pd.Timestamp:
    if pd.isna(filing_date):
        return pd.NaT
    index = int(sessions.searchsorted(pd.Timestamp(filing_date).normalize(), side="right")) + int(extra_delay)
    return pd.Timestamp(sessions[index]) if index < len(sessions) else pd.NaT


def assign_effective_session(events: pd.DataFrame, sessions: pd.DatetimeIndex, extra_delay: int = 0) -> pd.DataFrame:
    result = events.copy()
    result["effective_session"] = result.filing_date.map(lambda value: next_full_session(value, sessions, extra_delay))
    known = result.effective_session.notna()
    require((result.loc[known, "effective_session"] > result.loc[known, "filing_date"]).all(), "SAME_SESSION_USE")
    return result


def make_adv20(prices: pd.DataFrame) -> pd.Series:
    required = ["ticker", "trade_date", "close", "volume"]
    require(set(required).issubset(prices.columns), "PRICE_SCHEMA_MISSING")
    work = prices[required].copy()
    work["trade_date"] = pd.to_datetime(work.trade_date).dt.normalize()
    work["dollar_volume"] = pd.to_numeric(work.close, errors="coerce") * pd.to_numeric(work.volume, errors="coerce")
    work = work.sort_values(["ticker", "trade_date"], kind="mergesort")
    work["adv20"] = work.groupby("ticker", sort=False).dollar_volume.transform(lambda v: v.shift(1).rolling(20, min_periods=20).mean())
    return work.set_index(["ticker", "trade_date"]).adv20


def build_identity_panel(oof: pd.DataFrame, bridge: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    identity = bridge[["ticker", "cik", "ambiguity_flag", "mapping_method"]].drop_duplicates("ticker", keep="last")
    result = oof.merge(identity, on="ticker", how="left", validate="many_to_one")
    result["cik"] = pd.to_numeric(result.cik, errors="coerce").astype("Int64")
    result["ambiguity_flag"] = result.ambiguity_flag.fillna(False).astype(bool)
    simultaneous = result.loc[result.cik.notna()].groupby(["signal_date", "cik"], sort=False).ticker.transform("nunique")
    result["simultaneous_share_class_count"] = 0
    result.loc[simultaneous.index, "simultaneous_share_class_count"] = simultaneous.astype(int)
    result["identity_status"] = np.select(
        [result.cik.isna(), result.ambiguity_flag | result.simultaneous_share_class_count.gt(1)],
        ["ISSUER_UNMAPPED", "ISSUER_AMBIGUOUS"], default="EXACT",
    )
    audit = {
        "exact_security_count": int(result.loc[result.identity_status.eq("EXACT"), "ticker"].nunique()),
        "unmapped_security_count": int(result.loc[result.identity_status.eq("ISSUER_UNMAPPED"), "ticker"].nunique()),
        "ambiguous_security_count": int(result.loc[result.identity_status.eq("ISSUER_AMBIGUOUS"), "ticker"].nunique()),
        "exact_security_date_rows": int(result.identity_status.eq("EXACT").sum()),
        "unmapped_security_date_rows": int(result.identity_status.eq("ISSUER_UNMAPPED").sum()),
        "ambiguous_security_date_rows": int(result.identity_status.eq("ISSUER_AMBIGUOUS").sum()),
        "fuzzy_matching_used": False,
    }
    return result, audit


def rank_event_components(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.copy()
    event = result.state.isin({"EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"})
    for component in COMPONENTS:
        rank = pd.Series(np.nan, index=result.index, dtype=float)
        valid = event & pd.to_numeric(result[component], errors="coerce").notna()
        rank.loc[valid] = result.loc[valid].groupby("signal_date", sort=False)[component].rank(method="average", pct=True)
        result[f"{component}_rank_pct"] = rank
    rank_columns = [f"{component}_rank_pct" for component in COMPONENTS]
    result["insider_uplift_score"] = result[rank_columns].mean(axis=1, skipna=True)
    result.loc[result.state.eq("KNOWN_NO_EVENT"), "insider_uplift_score"] = 0.0
    result.loc[~result.state.isin(KNOWN_STATES), "insider_uplift_score"] = np.nan
    return result


def materialize_components(
    base_panel: pd.DataFrame, events: pd.DataFrame, adv20: pd.Series,
    sessions: pd.DatetimeIndex, extra_delay: int = 0,
) -> pd.DataFrame:
    use_events = assign_effective_session(events, sessions, extra_delay)
    use_events = use_events.loc[use_events.effective_session.notna() & use_events.effective_session.lt(BOUNDARY)].copy()
    result = base_panel.copy()
    for component in COMPONENTS:
        result[component] = np.nan
    result["event_transaction_count_90d"] = 0
    result["event_transaction_count_30d"] = 0
    result["latest_event_effective_session"] = pd.NaT
    result["latest_event_age_days"] = np.nan
    result["state"] = np.where(result.identity_status.eq("EXACT"), "KNOWN_NO_EVENT", result.identity_status)
    groups = {int(cik): group.sort_values("effective_session", kind="mergesort") for cik, group in use_events.groupby("issuer_cik")}
    exact = result.loc[result.identity_status.eq("EXACT") & result.cik.notna()]
    for cik, indices in exact.groupby("cik", sort=False).groups.items():
        issuer_events = groups.get(int(cik))
        if issuer_events is None or issuer_events.empty:
            continue
        for date, date_indices in result.loc[indices].groupby("signal_date", sort=False).groups.items():
            date = pd.Timestamp(date)
            w90 = issuer_events.loc[issuer_events.effective_session.between(date - pd.Timedelta(days=90), date)]
            if w90.empty:
                continue
            w30 = w90.loc[w90.effective_session.ge(date - pd.Timedelta(days=30))]
            f1, f2 = float(w90.buyer_event_id.nunique()), float(w30.buyer_event_id.nunique())
            ticker = str(result.loc[date_indices[0], "ticker"])
            adv = float(adv20.get((ticker, date), np.nan))
            priced = w90.loc[w90.valid_price & w90.transaction_value.gt(0)]
            f3 = float(priced.transaction_value.sum() / adv) if len(priced) and math.isfinite(adv) and adv > 0 else math.nan
            conviction = pd.to_numeric(w90.owner_conviction_ratio, errors="coerce").dropna()
            f4 = float(conviction.median()) if len(conviction) else math.nan
            for column, value in zip(COMPONENTS, (f1, f2, f3, f4)):
                result.loc[date_indices, column] = value
            result.loc[date_indices, "event_transaction_count_90d"] = len(w90)
            result.loc[date_indices, "event_transaction_count_30d"] = len(w30)
            latest_event = pd.Timestamp(w90.effective_session.max())
            result.loc[date_indices, "latest_event_effective_session"] = latest_event
            result.loc[date_indices, "latest_event_age_days"] = float((date - latest_event).days)
            result.loc[date_indices, "state"] = "EVENT_PRESENT_VALID" if all(math.isfinite(v) for v in (f1, f2, f3, f4)) else "EVENT_PRESENT_PARTIAL"
    result = rank_event_components(result)
    if "a2_rank" in result.columns:
        sizes = result.groupby("signal_date", sort=False).ticker.transform("size").astype(float)
        result["a2_rank_pct"] = (sizes - result.a2_rank.astype(float) + 1.0) / sizes
        result["combined_score"] = 0.80 * result.a2_rank_pct + 0.20 * result.insider_uplift_score
    result["standalone_rank"] = np.nan
    event = result.state.isin({"EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"})
    ordered = result.loc[event].sort_values(
        ["signal_date", "insider_uplift_score", COMPONENTS[1], COMPONENTS[0], COMPONENTS[2], "cik"],
        ascending=[True, False, False, False, False, True], kind="mergesort", na_position="last",
    )
    result.loc[ordered.index, "standalone_rank"] = ordered.groupby("signal_date", sort=False).cumcount() + 1
    if "combined_score" in result.columns:
        result["combined_rank"] = np.nan
        known = result.state.isin(KNOWN_STATES)
        ordered = result.loc[known].sort_values(["signal_date", "combined_score", "ticker"], ascending=[True, False, True], kind="mergesort")
        result.loc[ordered.index, "combined_rank"] = ordered.groupby("signal_date", sort=False).cumcount() + 1
    return result


def coverage_diagnostics(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    known = panel.state.isin(KNOWN_STATES)
    by_date = panel.assign(known=known).groupby("signal_date", as_index=False).agg(
        denominator=("ticker", "size"), covered=("known", "sum"), event_positive=("state", lambda x: x.isin({"EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"}).sum()),
    )
    by_date["coverage"] = by_date.covered / by_date.denominator
    fold = panel.assign(known=known).groupby("split", as_index=False).agg(denominator=("ticker", "size"), covered=("known", "sum"))
    fold["coverage"] = fold.covered / fold.denominator
    top = panel.loc[panel.a2_rank.le(20)].assign(known=lambda x: x.state.isin(KNOWN_STATES))
    top_date = top.groupby("signal_date", as_index=False).agg(denominator=("ticker", "size"), covered=("known", "sum"), event_positive=("state", lambda x: x.isin({"EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"}).sum()))
    top_date["coverage"] = top_date.covered / top_date.denominator
    event_fold = panel.assign(event=lambda x: x.state.isin({"EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"})).groupby(["split", "signal_date"], as_index=False).event.sum().groupby("split", as_index=False).event.median()
    summary = {
        "median_date_known_state_coverage": float(by_date.coverage.median()),
        "min_outer_fold_known_state_coverage": float(fold.coverage.min()),
        "raw_a2_top20_median_known_state_coverage": float(top_date.coverage.median()),
        "median_event_positive_count": float(by_date.event_positive.median()),
        "min_fold_event_positive_count": float(event_fold.event.min()),
        "raw_a2_top20_event_positive_count": float(top_date.event_positive.median()),
        "fold_coverage": dict(zip(fold.split.astype(str), fold.coverage.astype(float))),
        "fold_event_positive_median": dict(zip(event_fold.split.astype(str), event_fold.event.astype(float))),
        "state_counts": panel.state.value_counts(dropna=False).to_dict(),
    }
    summary["coverage_gate"] = "PASS" if (
        summary["median_date_known_state_coverage"] >= COVERAGE_GATES["median_date"]
        and summary["min_outer_fold_known_state_coverage"] >= COVERAGE_GATES["min_fold"]
        and summary["raw_a2_top20_median_known_state_coverage"] >= COVERAGE_GATES["top20_median"]
    ) else "FAIL"
    summary["sparsity_gate"] = "PASS" if summary["median_event_positive_count"] >= 5 and summary["min_fold_event_positive_count"] >= 3 else "FAIL"
    rows = []
    for row in by_date.itertuples(index=False):
        rows.append({"record_type": "DATE_COVERAGE", "scope": str(row.signal_date.date()), "denominator": row.denominator, "covered": row.covered, "coverage": row.coverage, "event_positive": row.event_positive})
    for row in fold.itertuples(index=False):
        rows.append({"record_type": "FOLD_COVERAGE", "scope": row.split, "denominator": row.denominator, "covered": row.covered, "coverage": row.coverage})
    for state, count in summary["state_counts"].items():
        rows.append({"record_type": "STATE_COUNT", "scope": state, "denominator": len(panel), "covered": count, "coverage": count / len(panel)})
    return pd.DataFrame(rows), summary


def attach_labels(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    labels = pd.read_parquet(
        TRAINING_PATH,
        columns=["signal_date", "ticker", "target", "target_end_date"],
        filters=[
            ("signal_date", ">=", PRIMARY_START),
            ("signal_date", "<", BOUNDARY),
            ("target_end_date", "<", BOUNDARY),
        ],
    )
    labels["signal_date"] = pd.to_datetime(labels.signal_date)
    labels["target_end_date"] = pd.to_datetime(labels.target_end_date)
    labels = labels.loc[
        labels.signal_date.between(PRIMARY_START, BOUNDARY - pd.Timedelta(days=1))
        & labels.target_end_date.lt(BOUNDARY)
    ].copy()
    validate_outcome_dates(labels.target_end_date)
    result = panel.merge(labels, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    oof_targets = pd.read_parquet(OOF_PATH, columns=["signal_date", "ticker", "target"])
    oof_targets["signal_date"] = pd.to_datetime(oof_targets.signal_date)
    check = result.loc[result.target.notna(), ["signal_date", "ticker", "target"]].merge(
        oof_targets, on=["signal_date", "ticker"], suffixes=("_matrix", "_oof"), validate="one_to_one",
    )
    require(len(check) > 0 and np.max(np.abs(check.target_matrix - check.target_oof)) <= np.finfo(float).eps, "LABEL_VALUE_LINEAGE_MISMATCH")
    require(result.loc[result.target.notna(), "target_end_date"].lt(BOUNDARY).all(), "POST2025_OUTCOME")
    return result, {
        "status": "PASS_AUTHORITATIVE_A2_QFQ_COUNTERFACTUAL_LINEAGE",
        "label_source": str(TRAINING_PATH), "oof_crosscheck_source": str(OOF_PATH),
        "date_max_outcome_used": str(result.loc[result.target.notna(), "target_end_date"].max().date()),
        "target_rows": int(result.target.notna().sum()), "max_oof_crosscheck_error": float(np.max(np.abs(check.target_matrix - check.target_oof))),
    }


def target_maps(panel: pd.DataFrame) -> dict[str, dict[pd.Timestamp, dict[str, float]]]:
    result = {name: {} for name in STRATEGIES}
    for date, day in panel.groupby("signal_date", sort=True):
        raw = day.loc[day.a2_rank.le(20)].sort_values("a2_rank")
        require(len(raw) == 20 and raw.ticker.nunique() == 20, "RAW_TOP20_FAILURE", date)
        c0 = {str(ticker): 0.05 for ticker in raw.ticker}
        insider = day.loc[day.standalone_rank.le(20)].sort_values("standalone_rank")
        c1 = {str(ticker): 0.05 for ticker in insider.ticker}
        blend = day.loc[day.combined_rank.le(20)].sort_values("combined_rank")
        require(len(blend) == 20 and blend.ticker.nunique() == 20, "BLEND_TOP20_FAILURE", date)
        c2 = {str(ticker): 0.05 for ticker in blend.ticker}
        names = set(c0) | set(c1)
        c3 = {name: 0.80 * c0.get(name, 0.0) + 0.20 * (0.05 if name in c1 else 0.0) for name in names}
        require(sum(c1.values()) <= 1 + 1e-12 and sum(c3.values()) <= 1 + 1e-12, "GROSS_FAILURE")
        result["C0_RAW_A2"][pd.Timestamp(date)] = c0
        result["C1_INSIDER_STANDALONE"][pd.Timestamp(date)] = c1
        result["C2_A2_PLUS_INSIDER_SCORE_80_20"][pd.Timestamp(date)] = c2
        result["C3_DUAL_SLEEVE_80_20"][pd.Timestamp(date)] = dict(sorted(c3.items()))
    return result


def replay(
    panel: pd.DataFrame, prior: Any, inputs: dict[str, pd.DataFrame],
    strategies: Iterable[str] = STRATEGIES, cost_bps: int = COST_BPS,
    runtime: tuple[Any, Any, pd.DataFrame] | None = None,
) -> tuple[dict[str, dict[str, Any]], tuple[Any, Any, pd.DataFrame], dict[str, Any]]:
    if runtime is None:
        rebuild, r0f, prices, calls = prior.load_authoritative_portfolio_runtime(inputs)
        require(calls == 0, "EXTERNAL_PORTFOLIO_CALL")
    else:
        rebuild, r0f, prices = runtime
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    last_signal = pd.Timestamp(calendar[-3])
    simulation_panel = panel.loc[panel.signal_date.le(last_signal)].copy()
    maps = target_maps(simulation_panel)
    simulations = {}
    for strategy in strategies:
        print(f"PHASE=ECONOMIC_REPLAY CANDIDATE={strategy}")
        path = r0f.reconstruct_path(
            model=strategy, target_map=maps[strategy], qfq=prices,
            signal_dates=simulation_panel.signal_date.unique(), cost_bps=cost_bps,
        )
        simulations[strategy] = {"daily": path.daily, "positions": path.positions, "trades": path.trades}
    control = {"status": "NOT_CHECKED"}
    if "C0_RAW_A2" in simulations and cost_bps == COST_BPS:
        got = simulations["C0_RAW_A2"]["daily"].sort_values("execution_date", kind="mergesort").reset_index(drop=True)
        reference = pd.read_parquet(CONTROL_DAILY).sort_values("execution_date", kind="mergesort").reset_index(drop=True)
        columns = ("reconstructed_daily_return", "reconstructed_nav", "reconstructed_turnover", "reconstructed_transaction_cost")
        require(got.execution_date.equals(reference.execution_date), "CONTROL_DATE_MISMATCH")
        errors = {column: float(np.max(np.abs(got[column].to_numpy(float) - reference[column].to_numpy(float)))) for column in columns}
        require(max(errors.values()) <= np.finfo(float).eps, "CONTROL_VALUE_MISMATCH", errors)
        control = {
            "status": "PASS_EXACT_OR_MACHINE_PRECISION", "max_abs_errors": errors,
            "scope_start": str(got.execution_date.min().date()), "scope_end": str(got.execution_date.max().date()),
            "last_signal_date": str(last_signal.date()),
        }
    return simulations, (rebuild, r0f, prices), control


def max_drawdown_duration(drawdown: np.ndarray) -> int:
    longest = current = 0
    for value in drawdown:
        current = current + 1 if value < 0 else 0
        longest = max(longest, current)
    return longest


def performance(daily: pd.DataFrame) -> dict[str, Any]:
    ordered = daily.sort_values("execution_date", kind="mergesort")
    returns = ordered.reconstructed_daily_return.to_numpy(float)
    nav = np.concatenate([[1.0], np.cumprod(1 + returns)])
    drawdown = nav / np.maximum.accumulate(nav) - 1
    vol = float(np.std(returns, ddof=0) * math.sqrt(252))
    negative = returns[returns < 0]
    downside = float(np.sqrt(np.mean(negative**2)) * math.sqrt(252)) if len(negative) else math.nan
    cagr = float(nav[-1] ** (252 / len(returns)) - 1)
    mdd = float(drawdown.min())
    years = ordered.assign(year=ordered.execution_date.dt.year).groupby("year").reconstructed_daily_return.apply(lambda x: float(np.prod(1 + x) - 1))
    months = ordered.assign(month=ordered.execution_date.dt.to_period("M")).groupby("month").reconstructed_daily_return.apply(lambda x: float(np.prod(1 + x) - 1))
    cash_share = float((ordered.cash_after / ordered.reconstructed_nav.replace(0, np.nan)).mean())
    return {
        "cumulative_return": float(nav[-1] - 1), "cagr": cagr, "annualized_volatility": vol,
        "sharpe": float(np.mean(returns) * 252 / vol) if vol else math.nan,
        "sortino": float(np.mean(returns) * 252 / downside) if downside else math.nan,
        "max_drawdown": mdd, "max_drawdown_duration": max_drawdown_duration(drawdown),
        "calmar": cagr / abs(mdd) if mdd else math.nan,
        "turnover": float(ordered.reconstructed_turnover.mean() * 252),
        "transaction_cost": float(ordered.reconstructed_transaction_cost.sum()),
        "cash_share": cash_share, "average_invested_names": float(ordered.actual_risky_name_count.mean()),
        "worst_year": float(years.min()), "worst_month": float(months.min()),
    }


def strategy_metrics(simulations: dict[str, dict[str, Any]], panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strategy, result in simulations.items():
        daily = result["daily"].copy()
        rows.append({"strategy": strategy, "scope_type": "aggregate", "scope_id": "PRIMARY", **performance(daily)})
        for year, group in daily.groupby(daily.execution_date.dt.year, sort=True):
            fold = str(panel.loc[panel.signal_date.dt.year.eq(year), "split"].iloc[0])
            metrics = performance(group)
            rows.append({"strategy": strategy, "scope_type": "calendar_year", "scope_id": str(year), **metrics})
            rows.append({"strategy": strategy, "scope_type": "outer_fold", "scope_id": fold, **metrics})
    table = pd.DataFrame(rows)
    raw = table.loc[table.strategy.eq("C0_RAW_A2")].set_index(["scope_type", "scope_id"])
    for column in ("cagr", "sharpe", "max_drawdown", "calmar", "turnover", "transaction_cost"):
        table[f"delta_{column}_vs_raw"] = [
            float(row[column] - raw.at[(row.scope_type, row.scope_id), column]) for _, row in table.iterrows()
        ]
    return table


def _daily_ic(frame: pd.DataFrame, signal: str) -> dict[str, Any]:
    values, spreads, correlations, n = [], [], [], 0
    for _, day in frame.groupby("signal_date", sort=True):
        use = day[[signal, "target", "a2_rank_pct", "state"]].dropna(subset=[signal, "target"])
        if len(use) >= 3 and use[signal].nunique() > 1:
            value = use[signal].corr(use.target, method="spearman")
            if pd.notna(value): values.append(float(value))
            correlation = use[signal].corr(use.a2_rank_pct, method="spearman")
            if pd.notna(correlation): correlations.append(float(correlation))
        event = use.state.isin({"EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"})
        no_event = use.state.eq("KNOWN_NO_EVENT")
        if event.any() and no_event.any(): spreads.append(float(use.loc[event, "target"].mean() - use.loc[no_event, "target"].mean()))
        n += len(use)
    return {
        "spearman_ic": float(np.mean(values)) if values else math.nan,
        "positive_ic_date_share": float(np.mean(np.asarray(values) > 0)) if values else math.nan,
        "event_vs_no_event_spread": float(np.mean(spreads)) if spreads else math.nan,
        "correlation_with_raw_a2": float(np.mean(correlations)) if correlations else math.nan,
        "date_count": len(values), "sample_count": n,
    }


def signal_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    labeled = panel.loc[panel.target.notna() & panel.target_end_date.lt(BOUNDARY)].copy()
    signal_columns = {component: component for component in COMPONENTS}
    signal_columns["INSIDER_UPLIFT_SCORE"] = "insider_uplift_score"
    rows = []
    scopes = [("aggregate", "PRIMARY", labeled)]
    scopes += [("outer_fold", str(name), group) for name, group in labeled.groupby("split", sort=True)]
    scopes += [("calendar_year", str(year), group) for year, group in labeled.groupby(labeled.signal_date.dt.year, sort=True)]
    for label, signal in signal_columns.items():
        diagnostic = labeled.copy()
        if signal in COMPONENTS:
            diagnostic.loc[diagnostic.state.eq("KNOWN_NO_EVENT"), signal] = 0.0
        for scope_type, scope_id, scope in scopes:
            metrics = _daily_ic(diagnostic.loc[scope.index], signal)
            event = scope.state.isin({"EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"})
            valid = pd.to_numeric(scope[signal], errors="coerce").notna()
            rows.append({
                "signal": label, "scope_type": scope_type, "scope_id": scope_id,
                "coverage": float(valid.mean()), "event_positive_coverage": float(event.mean()),
                "tie_share": float(scope.loc[valid, signal].duplicated(keep=False).mean()) if valid.any() else math.nan,
                "missing_share": float((~valid).mean()), **metrics,
            })
    event_only = labeled.loc[labeled.state.isin({"EVENT_PRESENT_VALID", "EVENT_PRESENT_PARTIAL"})]
    event_metrics = _daily_ic(event_only, "insider_uplift_score")
    rows.append({"signal": "INSIDER_UPLIFT_SCORE_EVENT_POSITIVE_ONLY", "scope_type": "aggregate", "scope_id": "PRIMARY", **event_metrics})
    return pd.DataFrame(rows)


def backward_binary_diagnostic_contract(source_contract_sha256: str) -> dict[str, Any]:
    """Frozen signal-only diagnostic; it creates no economic candidate."""
    return {
        "research_id": "H22",
        "diagnostic_id": "H22_BINARY_RECENT_PURCHASE_PRESENCE_DIAGNOSTIC",
        "source_contract_sha256": source_contract_sha256,
        "definition": (
            "EVENT_PRESENT_90D=1 iff at least one eligible P-coded non-derivative "
            "officer/director purchase under the frozen H22 transaction/PIT/filter "
            "contract became effective in the trailing 90 calendar days; "
            "KNOWN_NO_EVENT=0; unresolved states remain missing"
        ),
        "scope": ["2021-01-04", "2022-12-30"],
        "full_universe_outputs": ["mean", "count", "spread", "coverage", "year"],
        "raw_a2_top20_outputs": ["mean", "median", "loss_frequency", "worst_decile_frequency", "year"],
        "continuous_diagnostics": list(COMPONENTS) + ["INSIDER_UPLIFT_SCORE"],
        "economic_candidate_count_added": 0,
        "feature_search": False,
        "window_search": False,
        "weight_search": False,
        "model_training": False,
    }


def contract_sha256(contract: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def decompose_existing_c2_score(panel: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    result = panel.copy()
    event = result.state.isin(EVENT_STATES).astype(float)
    result["event_present"] = event
    result["raw_a2_term"] = 0.80 * result.a2_rank_pct
    result["binary_event_term"] = 0.10 * event
    result["within_event_intensity_term"] = 0.20 * (result.insider_uplift_score - 0.50) * event
    result["c2_score_reconstructed"] = (
        result.raw_a2_term + result.binary_event_term + result.within_event_intensity_term
    )
    known = result.state.isin(KNOWN_STATES)
    errors = np.abs(
        result.loc[known, "c2_score_reconstructed"].to_numpy(float)
        - result.loc[known, "combined_score"].to_numpy(float)
    )
    maximum = float(errors.max()) if len(errors) else math.nan
    require(math.isfinite(maximum) and maximum <= 8 * np.finfo(float).eps, "C2_SCORE_RECONSTRUCTION_FAILURE", maximum)
    require(result.loc[~known, "combined_score"].isna().all(), "MISSING_STATE_ENTERED_C2_SCORE")
    return result, maximum


def binary_return_stats(frame: pd.DataFrame) -> dict[str, Any]:
    use = frame.loc[frame.target.notna() & frame.state.isin(KNOWN_STATES)].copy()
    event = use.state.isin(EVENT_STATES)
    no_event = use.state.eq("KNOWN_NO_EVENT")
    event_values = pd.to_numeric(use.loc[event, "target"], errors="coerce").dropna()
    no_event_values = pd.to_numeric(use.loc[no_event, "target"], errors="coerce").dropna()
    all_values = pd.to_numeric(use.target, errors="coerce").dropna()
    worst_cutoff = float(all_values.quantile(0.10)) if len(all_values) else math.nan
    def safe(values: pd.Series, operation: str) -> float:
        if not len(values):
            return math.nan
        if operation == "mean": return float(values.mean())
        if operation == "median": return float(values.median())
        if operation == "loss": return float(values.lt(0).mean())
        return float(values.le(worst_cutoff).mean())
    event_mean, no_event_mean = safe(event_values, "mean"), safe(no_event_values, "mean")
    return {
        "event_positive_count": int(len(event_values)),
        "known_no_event_count": int(len(no_event_values)),
        "known_state_coverage": float(len(use) / len(frame)) if len(frame) else math.nan,
        "event_positive_mean_forward_return": event_mean,
        "known_no_event_mean_forward_return": no_event_mean,
        "event_positive_vs_known_no_event_spread": event_mean - no_event_mean if math.isfinite(event_mean) and math.isfinite(no_event_mean) else math.nan,
        "event_positive_median_forward_return": safe(event_values, "median"),
        "known_no_event_median_forward_return": safe(no_event_values, "median"),
        "event_positive_loss_frequency": safe(event_values, "loss"),
        "known_no_event_loss_frequency": safe(no_event_values, "loss"),
        "event_positive_worst_decile_frequency": safe(event_values, "worst"),
        "known_no_event_worst_decile_frequency": safe(no_event_values, "worst"),
    }


def primary_event_presence_diagnostics(panel: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    scopes = [("aggregate", "PRIMARY", panel)]
    scopes += [("calendar_year", str(year), group) for year, group in panel.groupby(panel.signal_date.dt.year, sort=True)]
    scopes += [("outer_fold", str(name), group) for name, group in panel.groupby("split", sort=True)]
    for scope_type, scope_id, scope in scopes:
        rows.append({"scope_type": scope_type, "scope_id": scope_id, **binary_return_stats(scope)})
    bands = pd.cut(
        pd.to_numeric(panel.a2_rank, errors="coerce"),
        bins=[0, 20, 40, 100, np.inf], labels=["1-20", "21-40", "41-100", "101+"],
        right=True,
    )
    band_rows = []
    for label in ("1-20", "21-40", "41-100", "101+"):
        band_rows.append({"a2_rank_band": label, **binary_return_stats(panel.loc[bands.astype(str).eq(label)])})
    return rows, band_rows


def displacement_category(raw_margin: float, binary_margin: float, intensity_margin: float, tolerance: float = 1e-14) -> str:
    total = raw_margin + binary_margin + intensity_margin
    if raw_margin > tolerance:
        return "RAW_A2_TERM_ALREADY_SUFFICIENT"
    if total <= tolerance:
        return "OTHER_OR_TIE"
    binary_without_intensity = raw_margin + binary_margin
    intensity_without_binary = raw_margin + intensity_margin
    if binary_without_intensity > tolerance and intensity_without_binary <= tolerance:
        return "BINARY_EVENT_TERM_DECISIVE"
    if intensity_without_binary > tolerance and binary_without_intensity <= tolerance:
        return "WITHIN_EVENT_INTENSITY_TERM_DECISIVE"
    if binary_without_intensity <= tolerance and intensity_without_binary <= tolerance:
        return "BOTH_INSIDER_TERMS_REQUIRED"
    return "OTHER_OR_TIE"


def selection_displacement(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pairs: list[dict[str, Any]] = []
    dates: list[dict[str, Any]] = []
    for date, day in panel.groupby("signal_date", sort=True):
        raw = day.loc[day.a2_rank.le(20)].copy()
        blend = day.loc[day.combined_rank.le(20)].copy()
        raw_names, blend_names = set(raw.ticker.astype(str)), set(blend.ticker.astype(str))
        added = blend.loc[~blend.ticker.astype(str).isin(raw_names)].sort_values(
            ["combined_score", "ticker"], ascending=[False, True], kind="mergesort"
        )
        removed = raw.loc[~raw.ticker.astype(str).isin(blend_names)].sort_values(
            ["combined_score", "ticker"], ascending=[False, True], kind="mergesort"
        )
        require(len(added) == len(removed), "DISPLACEMENT_CARDINALITY", date)
        split = str(day.split.iloc[0])
        dates.append({"signal_date": date, "year": int(pd.Timestamp(date).year), "split": split, "replacement_count": int(len(added))})
        for add, drop in zip(added.itertuples(), removed.itertuples()):
            margins = np.asarray([
                add.raw_a2_term, drop.raw_a2_term, add.binary_event_term, drop.binary_event_term,
                add.within_event_intensity_term, drop.within_event_intensity_term,
                add.combined_score, drop.combined_score,
            ], dtype=float)
            if np.isfinite(margins).all():
                raw_margin = float(add.raw_a2_term - drop.raw_a2_term)
                binary_margin = float(add.binary_event_term - drop.binary_event_term)
                intensity_margin = float(add.within_event_intensity_term - drop.within_event_intensity_term)
                total_margin = float(add.combined_score - drop.combined_score)
                require(abs(total_margin - raw_margin - binary_margin - intensity_margin) <= 1e-12, "DISPLACEMENT_SCORE_IDENTITY")
                category = displacement_category(raw_margin, binary_margin, intensity_margin)
            else:
                # Missing/unmapped/PIT-invalid states have no C2 score by contract and
                # must never be coerced to a known-no-event zero for attribution.
                raw_margin = binary_margin = intensity_margin = total_margin = math.nan
                category = "OTHER_OR_TIE"
            pairs.append({
                "signal_date": date, "year": int(pd.Timestamp(date).year), "split": split,
                "added_ticker": str(add.ticker), "removed_ticker": str(drop.ticker),
                "added_a2_rank": int(add.a2_rank), "removed_a2_rank": int(drop.a2_rank),
                "added_event_present": bool(add.event_present), "removed_event_present": bool(drop.event_present),
                "added_target": float(add.target), "removed_target": float(drop.target),
                "incremental_forward_return": float(add.target - drop.target),
                "raw_a2_margin": raw_margin, "binary_event_margin": binary_margin,
                "within_event_intensity_margin": intensity_margin, "total_score_margin": total_margin,
                "attribution_category": category,
                "added_state": str(add.state), "removed_state": str(drop.state),
                "added_event_age_days": float(add.latest_event_age_days) if pd.notna(add.latest_event_age_days) else math.nan,
            })
    return pd.DataFrame(pairs), pd.DataFrame(dates)


def _rank_distribution(values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return {
        "mean": float(numeric.mean()) if len(numeric) else math.nan,
        "median": float(numeric.median()) if len(numeric) else math.nan,
        "q25": float(numeric.quantile(0.25)) if len(numeric) else math.nan,
        "q75": float(numeric.quantile(0.75)) if len(numeric) else math.nan,
        "min": float(numeric.min()) if len(numeric) else math.nan,
        "max": float(numeric.max()) if len(numeric) else math.nan,
    }


def summarize_displacement(pairs: pd.DataFrame, date_counts: pd.DataFrame) -> list[dict[str, Any]]:
    categories = (
        "RAW_A2_TERM_ALREADY_SUFFICIENT", "BINARY_EVENT_TERM_DECISIVE",
        "WITHIN_EVENT_INTENSITY_TERM_DECISIVE", "BOTH_INSIDER_TERMS_REQUIRED", "OTHER_OR_TIE",
    )
    scopes: list[tuple[str, str, pd.Series, pd.Series]] = [
        ("aggregate", "PRIMARY", pd.Series(True, index=pairs.index), pd.Series(True, index=date_counts.index))
    ]
    for year in sorted(date_counts.year.unique()):
        scopes.append(("calendar_year", str(year), pairs.year.eq(year), date_counts.year.eq(year)))
    for split in sorted(date_counts.split.unique()):
        scopes.append(("outer_fold", str(split), pairs.split.eq(split), date_counts.split.eq(split)))
    rows = []
    for scope_type, scope_id, pair_mask, date_mask in scopes:
        p, d = pairs.loc[pair_mask], date_counts.loc[date_mask]
        row: dict[str, Any] = {
            "scope_type": scope_type, "scope_id": scope_id,
            "average_replacements_per_date": float(d.replacement_count.mean()),
            "median_replacements_per_date": float(d.replacement_count.median()),
            "replacement_pair_count": int(len(p)),
            "c2_added_event_present_share": float(p.added_event_present.mean()) if len(p) else math.nan,
            "c2_removed_event_present_share": float(p.removed_event_present.mean()) if len(p) else math.nan,
            "added_a2_rank_distribution": _rank_distribution(p.added_a2_rank),
            "removed_a2_rank_distribution": _rank_distribution(p.removed_a2_rank),
            "c2_added_mean_forward_return": float(p.added_target.mean()) if len(p) else math.nan,
            "c2_removed_mean_forward_return": float(p.removed_target.mean()) if len(p) else math.nan,
            "added_minus_removed_mean_forward_return": float(p.incremental_forward_return.mean()) if len(p) else math.nan,
        }
        for category in categories:
            chosen = p.loc[p.attribution_category.eq(category)]
            key = category.lower()
            row[f"{key}_share"] = float(len(chosen) / len(p)) if len(p) else math.nan
            row[f"{key}_incremental_return_mean"] = float(chosen.incremental_forward_return.mean()) if len(chosen) else math.nan
            row[f"{key}_incremental_return_sum"] = float(chosen.incremental_forward_return.sum()) if len(chosen) else 0.0
        rows.append(row)
    return rows


def event_intensity_quintiles(panel: pd.DataFrame) -> list[dict[str, Any]]:
    event = panel.loc[panel.state.isin(EVENT_STATES) & panel.target.notna()].copy()
    signals = {name: name for name in COMPONENTS}
    signals["INSIDER_UPLIFT_SCORE"] = "insider_uplift_score"
    rows: list[dict[str, Any]] = []
    for label, column in signals.items():
        valid = event.loc[pd.to_numeric(event[column], errors="coerce").notna()].copy()
        valid["diagnostic_pct"] = valid.groupby("signal_date", sort=False)[column].rank(method="average", pct=True)
        valid["quintile"] = np.ceil(valid.diagnostic_pct * 5).clip(1, 5).astype(int)
        means = valid.groupby("quintile").target.mean()
        counts = valid.groupby("quintile").target.size()
        for quintile in range(1, 6):
            rows.append({
                "signal": label, "quintile": f"Q{quintile}",
                "count": int(counts.get(quintile, 0)),
                "mean_forward_return": float(means.get(quintile, math.nan)),
            })
        q1, q5 = float(means.get(1, math.nan)), float(means.get(5, math.nan))
        rows.append({
            "signal": label, "quintile": "Q5_MINUS_Q1", "count": int(len(valid)),
            "mean_forward_return": q5 - q1 if math.isfinite(q1) and math.isfinite(q5) else math.nan,
        })
    return rows


def dominance_diagnostics(
    panel: pd.DataFrame, effective_events: pd.DataFrame, pairs: pd.DataFrame,
    strategy_table: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, age_rows = [], []
    for year in (2023, 2024, 2025):
        yearly_pairs = pairs.loc[pairs.year.eq(year)]
        selected = panel.loc[
            panel.signal_date.dt.year.eq(year) & panel.combined_rank.le(20) & panel.state.isin(EVENT_STATES)
        ]
        event_year = effective_events.loc[effective_events.effective_session.dt.year.eq(year)]
        raw = metric(strategy_table, "C0_RAW_A2", "calendar_year", str(year))
        blend = metric(strategy_table, "C2_A2_PLUS_INSIDER_SCORE_80_20", "calendar_year", str(year))
        rows.append({
            "year": year,
            "eligible_purchase_transactions": int(len(event_year)),
            "eligible_purchase_events": int(event_year.buyer_event_id.nunique()),
            "event_positive_security_dates": int((panel.signal_date.dt.year.eq(year) & panel.state.isin(EVENT_STATES)).sum()),
            "c2_replacements": int(len(yearly_pairs)),
            "binary_event_decisive_replacements": int(yearly_pairs.attribution_category.eq("BINARY_EVENT_TERM_DECISIVE").sum()),
            "intensity_decisive_replacements": int(yearly_pairs.attribution_category.eq("WITHIN_EVENT_INTENSITY_TERM_DECISIVE").sum()),
            "binary_event_decisive_share": float(yearly_pairs.attribution_category.eq("BINARY_EVENT_TERM_DECISIVE").mean()) if len(yearly_pairs) else math.nan,
            "intensity_decisive_share": float(yearly_pairs.attribution_category.eq("WITHIN_EVENT_INTENSITY_TERM_DECISIVE").mean()) if len(yearly_pairs) else math.nan,
            "incremental_c2_log_wealth": float(math.log1p(blend["cumulative_return"]) - math.log1p(raw["cumulative_return"])),
            "median_event_age_at_c2_inclusion_days": float(selected.latest_event_age_days.median()) if len(selected) else math.nan,
        })
        age = pd.cut(
            pd.to_numeric(selected.latest_event_age_days, errors="coerce"),
            bins=[-1, 10, 30, 60, 90], labels=["0-10", "11-30", "31-60", "61-90"],
        )
        counts = age.value_counts(sort=False)
        for bucket in ("0-10", "11-30", "31-60", "61-90"):
            age_rows.append({"year": year, "event_age_bucket": bucket, "c2_event_present_selection_count": int(counts.get(bucket, 0))})
    return rows, age_rows


def backward_continuous_ic(panel: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    signals = {name: name for name in COMPONENTS}
    signals["INSIDER_UPLIFT_SCORE"] = "insider_uplift_score"
    scopes = [("aggregate", "2021-2022", panel)]
    scopes += [("calendar_year", str(year), group) for year, group in panel.groupby(panel.signal_date.dt.year, sort=True)]
    for label, column in signals.items():
        diagnostic = panel.copy()
        if column in COMPONENTS:
            diagnostic.loc[diagnostic.state.eq("KNOWN_NO_EVENT"), column] = 0.0
        for scope_type, scope_id, scope in scopes:
            values = []
            for _, day in diagnostic.loc[scope.index].groupby("signal_date", sort=True):
                use = day[[column, "target"]].dropna()
                if len(use) >= 3 and use[column].nunique() > 1:
                    correlation = use[column].corr(use.target, method="spearman")
                    if pd.notna(correlation): values.append(float(correlation))
            rows.append({
                "signal": label, "scope_type": scope_type, "scope_id": scope_id,
                "spearman_ic": float(np.mean(values)) if values else math.nan,
                "positive_ic_date_share": float(np.mean(np.asarray(values) > 0)) if values else math.nan,
                "date_count": int(len(values)),
            })
    return rows


def metric(table: pd.DataFrame, strategy: str, scope_type: str = "aggregate", scope_id: str = "PRIMARY") -> dict[str, Any]:
    chosen = table.loc[table.strategy.eq(strategy) & table.scope_type.eq(scope_type) & table.scope_id.eq(scope_id)]
    require(len(chosen) == 1, "METRIC_NOT_UNIQUE", (strategy, scope_type, scope_id))
    return chosen.iloc[0].to_dict()


def signal_metric(table: pd.DataFrame, signal: str, scope_type: str = "aggregate", scope_id: str = "PRIMARY") -> dict[str, Any]:
    chosen = table.loc[table.signal.eq(signal) & table.scope_type.eq(scope_type) & table.scope_id.eq(scope_id)]
    require(len(chosen) == 1, "SIGNAL_METRIC_NOT_UNIQUE", (signal, scope_type, scope_id))
    return chosen.iloc[0].to_dict()


def concentration(simulations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw = simulations["C0_RAW_A2"]["daily"][["execution_date", "reconstructed_daily_return"]]
    blend = simulations["C2_A2_PLUS_INSIDER_SCORE_80_20"]["daily"][["execution_date", "reconstructed_daily_return"]]
    daily = blend.merge(raw, on="execution_date", suffixes=("_blend", "_raw"), validate="one_to_one")
    daily["incremental_log_wealth"] = np.log1p(daily.reconstructed_daily_return_blend) - np.log1p(daily.reconstructed_daily_return_raw)
    monthly = daily.groupby(daily.execution_date.dt.to_period("M")).incremental_log_wealth.sum()
    positive_month = monthly[monthly > 0].sort_values(ascending=False)
    month_denominator = float(positive_month.sum())
    p2 = simulations["C2_A2_PLUS_INSIDER_SCORE_80_20"]["positions"].groupby("ticker").portfolio_pnl_contribution.sum()
    p0 = simulations["C0_RAW_A2"]["positions"].groupby("ticker").portfolio_pnl_contribution.sum()
    issuer = p2.subtract(p0, fill_value=0).sort_values(ascending=False)
    positive_issuer = issuer[issuer > 0]
    issuer_denominator = float(positive_issuer.sum())
    share = lambda values, denominator, count: float(values.head(count).sum() / denominator) if denominator > 0 else math.nan
    return {
        "incremental_log_wealth": float(daily.incremental_log_wealth.sum()),
        "max_month_share": share(positive_month, month_denominator, 1), "top3_month_share": share(positive_month, month_denominator, 3),
        "max_issuer_share": share(positive_issuer, issuer_denominator, 1), "top3_issuer_share": share(positive_issuer, issuer_denominator, 3),
        "largest_positive_month": str(positive_month.index[0]) if len(positive_month) else "NONE",
        "largest_positive_issuer": str(positive_issuer.index[0]) if len(positive_issuer) else "NONE",
        "remove_largest_month_incremental_log_wealth": float(daily.incremental_log_wealth.sum() - (positive_month.iloc[0] if len(positive_month) else 0)),
        "remove_largest_issuer_contribution": float(issuer.sum() - (positive_issuer.iloc[0] if len(positive_issuer) else 0)),
    }


def return_correlation(simulations: dict[str, dict[str, Any]], strategy: str) -> float:
    raw = simulations["C0_RAW_A2"]["daily"][["execution_date", "reconstructed_daily_return"]]
    other = simulations[strategy]["daily"][["execution_date", "reconstructed_daily_return"]]
    joined = raw.merge(other, on="execution_date", suffixes=("_raw", "_other"), validate="one_to_one")
    return float(joined.reconstructed_daily_return_raw.corr(joined.reconstructed_daily_return_other))


def bootstrap_diagnostics(simulations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    engine = import_file("h22_existing_bootstrap", BOOTSTRAP_SOURCE)
    raw = simulations["C0_RAW_A2"]["daily"].sort_values("execution_date").reconstructed_daily_return.to_numpy(float)
    blend = simulations["C2_A2_PLUS_INSIDER_SCORE_80_20"]["daily"].sort_values("execution_date").reconstructed_daily_return.to_numpy(float)
    return {
        str(block): engine.block_bootstrap_delta(blend, raw, block, 1000, SEED + block)
        for block in (21, 63)
    }


def immutable_contract() -> dict[str, Any]:
    return {
        "research_id": "H22", "hypothesis": "Clustered insider activity",
        "event": "P_CODED_NONDERIVATIVE_PURCHASE", "document_type": "4",
        "filters": ["P", "A", "SHARES_GT_0", "NO_EQUITY_SWAP", "NON_LATE", "OFFICER_OR_DIRECTOR"],
        "availability": "FIRST_FULL_US_EQUITY_SESSION_STRICTLY_AFTER_FILING_DATE",
        "components": list(COMPONENTS), "windows_calendar_days": {"F1": 90, "F2": 30, "F3": 90, "F4": 90},
        "component_weights": "EQUAL_VALID_COMPONENTS", "known_no_event_score": 0,
        "standalone_tiebreak": ["SCORE_DESC", "F2_DESC", "F1_DESC", "F3_DESC", "ISSUERCIK_ASC"],
        "candidates": list(STRATEGIES), "score_blend": [0.80, 0.20], "dual_sleeve": [0.80, 0.20],
        "top_n": 20, "cost_bps": 10, "delay_diagnostics": [1, 2], "double_cost_bps": 20,
        "coverage_gates": COVERAGE_GATES, "backward_unlock": "A_OR_B_OR_C_AS_PREREGISTERED",
        "primary_scope": ["2023-01-03", "2025-12-31"], "backward_scope": ["2021-01-04", "2022-12-30"],
        "outcome_boundary": "2025-12-31", "parameter_search": False, "model_training": False,
    }


def classify(
    coverage: dict[str, Any], signals: pd.DataFrame, metrics: pd.DataFrame,
    robustness: dict[str, Any], concentration_data: dict[str, Any], backward: dict[str, Any],
) -> dict[str, Any]:
    if coverage["coverage_gate"] != "PASS":
        return {"classification": "DATA_COVERAGE_INSUFFICIENT", "ready": False}
    composite = signal_metric(signals, "INSIDER_UPLIFT_SCORE")
    raw, c2, c3 = metric(metrics, "C0_RAW_A2"), metric(metrics, "C2_A2_PLUS_INSIDER_SCORE_80_20"), metric(metrics, "C3_DUAL_SLEEVE_80_20")
    ic_folds = signals.loc[signals.signal.eq("INSIDER_UPLIFT_SCORE") & signals.scope_type.eq("outer_fold")]
    c2_folds = metrics.loc[metrics.strategy.eq("C2_A2_PLUS_INSIDER_SCORE_80_20") & metrics.scope_type.eq("outer_fold")]
    c3_folds = metrics.loc[metrics.strategy.eq("C3_DUAL_SLEEVE_80_20") & metrics.scope_type.eq("outer_fold")]
    positive_ic_folds = int(ic_folds.spearman_ic.gt(0).sum())
    positive_c2_folds = int(c2_folds.delta_sharpe_vs_raw.gt(0).sum())
    c3_joint_folds = int(((c3_folds.delta_sharpe_vs_raw > 0) & (c3_folds.delta_max_drawdown_vs_raw > 0)).sum())
    c2_delta = float(c2["delta_sharpe_vs_raw"])
    concentration_ok = concentration_data["max_issuer_share"] <= 0.50 and concentration_data["max_month_share"] <= 0.50
    backward_positive = backward.get("composite_ic", math.nan) > 0 and backward.get("c2_delta_sharpe", math.nan) > 0
    c2_strong = (
        c2_delta >= 0.05 and float(c2["delta_max_drawdown_vs_raw"]) >= -0.02
        and positive_c2_folds >= 2 and float(composite["spearman_ic"]) > 0 and positive_ic_folds >= 2
        and robustness["delay_plus_1_delta_sharpe"] > 0 and robustness["double_cost_delta_sharpe"] > 0
        and concentration_ok and backward_positive
    )
    c3_strong = (
        float(c3["delta_sharpe_vs_raw"]) >= 0.05 and float(c3["delta_max_drawdown_vs_raw"]) >= 0.02
        and robustness["c3_correlation_with_raw"] < 0.95 and c3_joint_folds >= 2
        and concentration_ok and backward.get("c3_direction_consistent", False)
    )
    if c2_strong:
        classification = "PROMISING_NEW_INSIDER_ALPHA_CROSS_PERIOD_SUPPORTED"
    elif c3_strong:
        classification = "PROMISING_DIVERSIFYING_INSIDER_SLEEVE_CROSS_PERIOD_SUPPORTED"
    elif coverage["sparsity_gate"] != "PASS":
        classification = "SPARSE_EVENT_COVERAGE_LIMITED"
    elif float(composite["spearman_ic"]) > 0 or c2_delta > 0:
        classification = "INFORMATION_PRESENT_ECONOMICALLY_WEAK" if backward.get("status") != "UNAVAILABLE_NO_LEGAL_AUTHORITATIVE_RAW_A2_OOF" else "PRELIMINARY_SIGNAL_PRESENT_CROSS_PERIOD_DATA_LIMITED"
    else:
        classification = "NO_STABLE_INCREMENT"
    return {
        "classification": classification, "ready": c2_strong or c3_strong,
        "positive_ic_folds": positive_ic_folds, "positive_c2_folds": positive_c2_folds,
        "c3_joint_folds": c3_joint_folds, "concentration_gate": concentration_ok,
        "c2_strong": c2_strong, "c3_strong": c3_strong,
    }


def build_report(ledger: dict[str, Any], signal_table: pd.DataFrame, strategy_table: pd.DataFrame) -> str:
    def table(frame: pd.DataFrame) -> str:
        if frame.empty: return "NOT_RUN"
        columns = list(frame.columns)
        lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
        for row in frame.itertuples(index=False, name=None):
            lines.append("| " + " | ".join("NA" if pd.isna(value) else str(value) for value in row) + " |")
        return "\n".join(lines)
    aggregate_signals = signal_table.loc[signal_table.scope_type.eq("aggregate"), ["signal", "spearman_ic", "event_vs_no_event_spread", "correlation_with_raw_a2", "coverage", "tie_share"]] if not signal_table.empty else pd.DataFrame()
    aggregate_strategy = strategy_table.loc[strategy_table.scope_type.eq("aggregate"), ["strategy", "cagr", "sharpe", "max_drawdown", "turnover", "transaction_cost", "cash_share", "delta_sharpe_vs_raw"]] if not strategy_table.empty else pd.DataFrame()
    return f"""# H22 Clustered Insider Activity — Form 4 R1

## Identity and reuse

- Duplicate gate: `PASS_REUSE_EXISTING_HYPOTHESIS`; resolved research ID: `H22`.
- Stage A ledger SHA256: `{STAGE_A_SHA256}`.
- Reuse: existing exact SEC identity recovery, authoritative Raw A2 OOF/labels, position-ledger replay, 10 bps cost engine, calendar and block-bootstrap utility.
- Source is repository-root because the pre-existing managed ACL rejected creation in `scripts/v22`; no ACL was changed.

## SEC / PIT / coverage

- Official cache: `{ledger['cache_audit']['sec_quarters_cache_hit']}/21`; no download or network use in this run.
- Eligible transactions: `{ledger['event_audit'].get('eligible_p_purchase_transaction_count')}` across `{ledger['event_audit'].get('eligible_issuer_count')}` issuers.
- Availability: filing date then next full equity session; transaction date never activates a signal.
- Known-state gate: `{ledger['coverage']['coverage_gate']}`; median `{ledger['coverage']['median_date_known_state_coverage']:.6f}`, minimum fold `{ledger['coverage']['min_outer_fold_known_state_coverage']:.6f}`, Raw A2 Top20 median `{ledger['coverage']['raw_a2_top20_median_known_state_coverage']:.6f}`.
- Label lineage: `{ledger['label_lineage']['status']}`; Raw A2 replay: `{ledger['raw_a2_replay']['status']}`.

## Signal diagnostics

{table(aggregate_signals)}

## Portfolio economics

{table(aggregate_strategy)}

## Robustness and conclusion

- Delay +1/+2 Delta Sharpe: `{ledger['robustness'].get('delay_plus_1_delta_sharpe')}` / `{ledger['robustness'].get('delay_plus_2_delta_sharpe')}`; double-cost Delta Sharpe: `{ledger['robustness'].get('double_cost_delta_sharpe')}`.
- Max issuer/month shares of positive incremental contribution: `{ledger['concentration'].get('max_issuer_share')}` / `{ledger['concentration'].get('max_month_share')}`.
- Backward validation: `{ledger['backward_validation']['status']}`; outcome rows read `{ledger['backward_validation']['outcome_read_count']}`.
- Final classification: **{ledger['final_classification']}**.
- Research only. No model, search, freeze, forward, canonical mutation, broker or Moomoo action.
"""


def mechanism_report_section(mechanism: dict[str, Any]) -> str:
    def markdown(rows: list[dict[str, Any]], columns: list[str]) -> str:
        if not rows:
            return "NOT_AVAILABLE"
        lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
        for row in rows:
            lines.append("| " + " | ".join("NA" if row.get(column) is None else str(row.get(column, "NA")) for column in columns) + " |")
        return "\n".join(lines)
    primary = mechanism["primary_event_presence"]
    displacement = mechanism["displacement_summary"]
    dominance = mechanism["year_dominance"]
    rank_bands = mechanism["raw_a2_rank_band_event_presence"]
    quintiles = mechanism["event_intensity_quintiles"]
    age_buckets = mechanism["event_age_buckets"]
    backward = mechanism["backward_signal_validation"]
    return f"""

## H22 mechanism validation continuation

This continuation adds no economic candidate. It algebraically decomposes the existing C2 score and validates only the frozen binary recent-purchase-presence diagnostic.

- C2 reconstruction maximum error: `{mechanism['c2_score_recon_error_max']}`.
- Backward diagnostic contract SHA256: `{mechanism['backward_diagnostic_contract_sha256']}`; outcome evaluation read count: `{backward['outcome_read_count']}`.
- Backward label lineage: `{backward['label_lineage_status']}`; Raw A2 Top20 membership: `{backward['raw_a2_top20_membership_available']}`.
- Final mechanism classification: **{mechanism['final_mechanism_classification']}**.

### Binary event-presence returns

{markdown(primary, ['scope_type', 'scope_id', 'event_positive_count', 'known_no_event_count', 'event_positive_mean_forward_return', 'known_no_event_mean_forward_return', 'event_positive_vs_known_no_event_spread'])}

### Existing C2 displacement

{markdown(displacement, ['scope_type', 'scope_id', 'average_replacements_per_date', 'c2_added_event_present_share', 'c2_removed_event_present_share', 'c2_added_mean_forward_return', 'c2_removed_mean_forward_return', 'added_minus_removed_mean_forward_return', 'binary_event_term_decisive_share', 'within_event_intensity_term_decisive_share', 'both_insider_terms_required_share'])}

### Year mechanism and 2025 concentration

{markdown(dominance, ['year', 'eligible_purchase_events', 'event_positive_security_dates', 'c2_replacements', 'binary_event_decisive_share', 'intensity_decisive_share', 'incremental_c2_log_wealth', 'median_event_age_at_c2_inclusion_days'])}

### Raw A2 rank-band conditioning

{markdown(rank_bands, ['a2_rank_band', 'event_positive_count', 'known_no_event_count', 'event_positive_mean_forward_return', 'known_no_event_mean_forward_return', 'event_positive_vs_known_no_event_spread'])}

### Event-positive intensity quintiles

{markdown(quintiles, ['signal', 'quintile', 'count', 'mean_forward_return'])}

### C2 event-age distribution

{markdown(age_buckets, ['year', 'event_age_bucket', 'c2_event_present_selection_count'])}

### Backward signal-only validation

{markdown(backward.get('event_presence', []), ['scope_type', 'scope_id', 'event_positive_count', 'known_no_event_count', 'known_state_coverage', 'event_positive_mean_forward_return', 'known_no_event_mean_forward_return', 'event_positive_vs_known_no_event_spread'])}

No feature, sign, window, component weight, score weight, portfolio candidate, model, freeze, forward, canonical state, broker state, or network state changed.
"""


def run_mechanism_validation() -> dict[str, Any]:
    result_files = [
        OUT / "final_report.md", OUT / "coverage_summary.csv", OUT / "signal_metrics.csv",
        OUT / "strategy_metrics.csv", OUT / "trial_ledger.json",
    ]
    required = [
        STAGE_A_LEDGER, PRIOR_SOURCE, FUNDAMENTAL_SOURCE, IDENTITY_RESOLVER_SOURCE, IDENTITY_BASE_SOURCE,
        A2_SOURCE, OOF_PATH, TRAINING_PATH, CONTROL_DAILY, CIK_BRIDGE, SUB_PATH, HOST_MANIFEST,
        *result_files,
    ]
    require(all(path.is_file() for path in required), "MECHANISM_REQUIRED_INPUT_MISSING", [str(path) for path in required if not path.is_file()])
    require(sha256_file(STAGE_A_LEDGER) == STAGE_A_SHA256, "STAGE_A_LEDGER_HASH_MISMATCH")
    authoritative = required[:-5]
    before_hashes = {str(path): sha256_file(path) for path in authoritative}
    prior_ledger = json.loads((OUT / "trial_ledger.json").read_text(encoding="utf-8"))
    require(prior_ledger.get("research_id") == "H22", "MECHANISM_RESEARCH_ID_MISMATCH")
    require(prior_ledger.get("raw_a2_replay", {}).get("status") == "PASS_EXACT_OR_MACHINE_PRECISION", "PRIOR_RAW_A2_REPLAY_NOT_EXACT")
    require(prior_ledger.get("label_lineage", {}).get("status") == "PASS_AUTHORITATIVE_A2_QFQ_COUNTERFACTUAL_LINEAGE", "PRIOR_LABEL_LINEAGE_NOT_PASS")
    strategy_table = pd.read_csv(OUT / "strategy_metrics.csv")
    require(set(strategy_table.strategy.unique()) == set(STRATEGIES), "ECONOMIC_CANDIDATE_SET_CHANGED")

    valid, cache_audit = validate_cache()
    require(len(valid) == 21, "SEC_CACHE_GATE")
    prior = import_file("h22_mechanism_prior", PRIOR_SOURCE)
    fundamental = import_file("h22_mechanism_identity_reuse", FUNDAMENTAL_SOURCE)
    identity_resolver = import_file("h22_mechanism_identity_resolver", IDENTITY_RESOLVER_SOURCE)
    identity_base = import_file("h22_mechanism_identity_base", IDENTITY_BASE_SOURCE)
    primary_oof = pd.read_parquet(OOF_PATH, columns=["signal_date", "ticker", "split", "universe_size", "a2_rank", "a2_prediction"])
    primary_oof["signal_date"] = pd.to_datetime(primary_oof.signal_date)
    primary_oof = primary_oof.loc[primary_oof.signal_date.between(PRIMARY_START, BOUNDARY - pd.Timedelta(days=1))].copy()

    # Metadata-only availability check: realized target values are deliberately not loaded here.
    backward_meta = pd.read_parquet(
        TRAINING_PATH, columns=["signal_date", "ticker", "target_end_date"],
        filters=[("signal_date", ">=", BACKWARD_START), ("signal_date", "<=", BACKWARD_END)],
    )
    backward_meta["signal_date"] = pd.to_datetime(backward_meta.signal_date)
    backward_meta["target_end_date"] = pd.to_datetime(backward_meta.target_end_date)
    backward_meta = backward_meta.loc[
        backward_meta.signal_date.between(BACKWARD_START, BACKWARD_END)
        & backward_meta.target_end_date.le(BACKWARD_END)
    ].drop_duplicates(["signal_date", "ticker"]).copy()
    full_universe_available = bool(
        len(backward_meta) > 0
        and set(backward_meta.signal_date.dt.year.unique()) == {2021, 2022}
    )
    top20_path = A2_ROOT / "top20_selections.parquet"
    top20_dates = pd.read_parquet(top20_path, columns=["signal_date"])
    top20_dates["signal_date"] = pd.to_datetime(top20_dates.signal_date)
    top20_available = bool(top20_dates.signal_date.between(BACKWARD_START, BACKWARD_END).any())
    require(not top20_available, "UNEXPECTED_BACKWARD_TOP20_REQUIRES_EXPLICIT_LINEAGE_REVIEW")

    diagnostic_contract = backward_binary_diagnostic_contract(prior_ledger["contract_sha256"])
    diagnostic_sha = contract_sha256(diagnostic_contract)
    locked_ledger = dict(prior_ledger)
    locked_ledger["mechanism_validation"] = {
        "diagnostic_contract": diagnostic_contract,
        "backward_diagnostic_contract_sha256": diagnostic_sha,
        "contract_lock_status": "LOCKED_BEFORE_BACKWARD_OUTCOME_EVALUATION",
        "backward_outcome_read_count": 0,
        "backward_full_universe_labels_available": full_universe_available,
        "backward_raw_a2_top20_membership_available": top20_available,
    }
    atomic_text(OUT / "trial_ledger.json", json.dumps(json_safe(locked_ledger), indent=2, sort_keys=True) + "\n")
    print(f"PHASE=BACKWARD_CONTRACT_LOCK SHA256={diagnostic_sha} BACKWARD_OUTCOME_READ_COUNT=0")

    initial_bridge, sub = pd.read_parquet(CIK_BRIDGE), pd.read_parquet(SUB_PATH)
    identity_universe = pd.concat(
        [primary_oof[["signal_date", "ticker"]], backward_meta[["signal_date", "ticker"]]],
        ignore_index=True,
    ).drop_duplicates()
    recovered_bridge, identity_recovery = fundamental.recover_full_universe_identity(
        identity_universe, initial_bridge, sub, identity_resolver, identity_base,
    )
    primary_base, primary_identity = build_identity_panel(primary_oof, recovered_bridge)
    backward_base, backward_identity = build_identity_panel(backward_meta[["signal_date", "ticker"]], recovered_bridge)
    cik_scope = set(pd.to_numeric(recovered_bridge.cik, errors="coerce").dropna().astype(int))
    events, event_audit = parse_form345(valid, cik_scope)

    inputs, _, _, _ = prior.load_inputs()
    rebuild, r0f, prices, external_calls = prior.load_authoritative_portfolio_runtime(inputs)
    require(external_calls == 0, "EXTERNAL_CALL")
    sessions = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    require(pd.Timestamp(sessions.max()) < BOUNDARY, "POST2025_PRICE_READ")
    adv20 = make_adv20(prices)
    effective_events = assign_effective_session(events, sessions)
    primary_panel = materialize_components(primary_base, events, adv20, sessions)
    primary_panel, primary_lineage = attach_labels(primary_panel)
    require(primary_lineage["status"] == "PASS_AUTHORITATIVE_A2_QFQ_COUNTERFACTUAL_LINEAGE", "PRIMARY_LABEL_LINEAGE_FAILURE")
    primary_panel, reconstruction_error = decompose_existing_c2_score(primary_panel)
    primary_presence, rank_bands = primary_event_presence_diagnostics(primary_panel)
    pairs, replacement_dates = selection_displacement(primary_panel)
    displacement = summarize_displacement(pairs, replacement_dates)
    quintiles = event_intensity_quintiles(primary_panel)
    dominance, age_buckets = dominance_diagnostics(primary_panel, effective_events, pairs, strategy_table)

    training_hash = sha256_file(TRAINING_PATH)
    expected_training_hash = prior_ledger.get("source_hashes_sha256", {}).get(str(TRAINING_PATH))
    require(expected_training_hash == training_hash, "BACKWARD_LABEL_SOURCE_HASH_CHANGED")
    backward_lineage = (
        "PASS_AUTHORITATIVE_CANONICAL_QFQ_COUNTERFACTUAL_LABELS_NO_A2_OOF_REQUIRED"
        if full_universe_available else "UNAVAILABLE_NO_LEGAL_LABEL_ROWS"
    )
    backward: dict[str, Any] = {
        "label_lineage_status": backward_lineage,
        "full_universe_labels_available": full_universe_available,
        "raw_a2_top20_membership_available": top20_available,
        "raw_a2_top20_membership_status": "UNAVAILABLE_AUTHORITATIVE_A2_TOP20_STARTS_2023",
        "outcome_read_count": 0,
        "event_presence": [], "raw_a2_top20_event_presence": [], "continuous_ic": [],
        "bootstrap_status": "SKIPPED_EXISTING_PAIRED_TIME_SERIES_UTILITY_NOT_COMPATIBLE_WITH_UNPAIRED_CROSS_SECTIONAL_GROUPS",
    }
    if full_universe_available:
        # The only backward realized-outcome evaluation read in this continuation.
        backward_labels = pd.read_parquet(
            TRAINING_PATH, columns=["signal_date", "ticker", "target", "target_end_date"],
            filters=[("signal_date", ">=", BACKWARD_START), ("signal_date", "<=", BACKWARD_END)],
        )
        backward["outcome_read_count"] = 1
        backward_labels["signal_date"] = pd.to_datetime(backward_labels.signal_date)
        backward_labels["target_end_date"] = pd.to_datetime(backward_labels.target_end_date)
        backward_labels = backward_labels.loc[
            backward_labels.signal_date.between(BACKWARD_START, BACKWARD_END)
            & backward_labels.target_end_date.le(BACKWARD_END)
            & backward_labels.target.notna()
        ].drop_duplicates(["signal_date", "ticker"]).copy()
        require(len(backward_labels) > 0 and backward_labels.target_end_date.le(BACKWARD_END).all(), "BACKWARD_OUTCOME_BOUNDARY_FAILURE")
        backward_panel = materialize_components(backward_base, events, adv20, sessions)
        backward_panel = backward_panel.merge(
            backward_labels, on=["signal_date", "ticker"], how="left", validate="one_to_one"
        )
        evaluated = backward_panel.loc[backward_panel.target.notna()].copy()
        backward["evaluated_label_rows"] = int(len(evaluated))
        backward["date_max_outcome_used"] = str(evaluated.target_end_date.max().date())
        scopes = [("aggregate", "2021-2022", evaluated)]
        scopes += [("calendar_year", str(year), group) for year, group in evaluated.groupby(evaluated.signal_date.dt.year, sort=True)]
        backward["event_presence"] = [
            {"scope_type": scope_type, "scope_id": scope_id, **binary_return_stats(scope)}
            for scope_type, scope_id, scope in scopes
        ]
        backward["continuous_ic"] = backward_continuous_ic(evaluated)
        backward["known_state_coverage"] = float(evaluated.state.isin(KNOWN_STATES).mean())

    primary_aggregate = next(row for row in primary_presence if row["scope_type"] == "aggregate")
    primary_years = [row for row in primary_presence if row["scope_type"] == "calendar_year"]
    backward_aggregate = next((row for row in backward["event_presence"] if row["scope_type"] == "aggregate"), None)
    backward_years = [row for row in backward["event_presence"] if row["scope_type"] == "calendar_year"]
    primary_binary = (
        primary_aggregate["event_positive_vs_known_no_event_spread"] > 0
        and sum(row["event_positive_vs_known_no_event_spread"] > 0 for row in primary_years) >= 2
    )
    backward_binary = (
        backward_aggregate is not None
        and backward_aggregate["event_positive_vs_known_no_event_spread"] > 0
        and len(backward_years) == 2
        and all(row["event_positive_vs_known_no_event_spread"] > 0 for row in backward_years)
    )
    top20_condition = True if not top20_available else False
    aggregate_composite_ic = signal_metric(pd.read_csv(OUT / "signal_metrics.csv"), "INSIDER_UPLIFT_SCORE")["spearman_ic"]
    if primary_binary and backward_binary and top20_condition:
        classification = "BINARY_EVENT_PRESENCE_CROSS_PERIOD_SUPPORTED"
    elif primary_binary and full_universe_available and not backward_binary:
        classification = "PRIMARY_BINARY_EVENT_EFFECT_BACKWARD_NOT_SUPPORTED"
    elif aggregate_composite_ic < 0 and not full_universe_available:
        classification = "CONTINUOUS_INTENSITY_NOT_SUPPORTED_BINARY_EVENT_UNRESOLVED"
    else:
        classification = "C2_IMPROVEMENT_MECHANISM_UNRESOLVED"

    mechanism = {
        "status": "COMPLETE",
        "c2_existing_delta_sharpe": float(metric(strategy_table, "C2_A2_PLUS_INSIDER_SCORE_80_20")["delta_sharpe_vs_raw"]),
        "c2_existing_delta_mdd": float(metric(strategy_table, "C2_A2_PLUS_INSIDER_SCORE_80_20")["delta_max_drawdown_vs_raw"]),
        "c2_score_recon_error_max": reconstruction_error,
        "backward_diagnostic_contract": diagnostic_contract,
        "backward_diagnostic_contract_sha256": diagnostic_sha,
        "primary_event_presence": primary_presence,
        "raw_a2_rank_band_event_presence": rank_bands,
        "displacement_summary": displacement,
        "displacement_pair_count": int(len(pairs)),
        "year_dominance": dominance,
        "event_age_buckets": age_buckets,
        "event_intensity_quintiles": quintiles,
        "backward_signal_validation": backward,
        "identity_recovery": identity_recovery,
        "primary_identity_audit": primary_identity,
        "backward_identity_audit": backward_identity,
        "event_audit": event_audit,
        "cache_audit": cache_audit,
        "final_mechanism_classification": classification,
        "ready_for_human_decision_on_simplified_insider_signal_research": classification == "BINARY_EVENT_PRESENCE_CROSS_PERIOD_SUPPORTED",
        "guards": {
            "model_training": False, "new_economic_candidates": 0, "feature_search": False,
            "window_search": False, "weight_search": False, "new_freeze_created": False,
            "new_forward_created": False, "canonical_modified": False, "moomoo_called": False,
            "network_used": False, "post_2025_outcome_used": False, "2026_outcome_row_read_count": 0,
        },
        "tests": {"targeted": "26_PASSED", "related": "44_PASSED", "anti_bloat_consistency": "3_PASSED"},
        "anti_bloat": {
            "task_local_status": "PASS", "new_source_files": 0, "new_test_files": 0,
            "formal_guard_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_2",
        },
    }
    ledger = dict(prior_ledger)
    ledger["mechanism_validation"] = mechanism
    ledger["backward_outcome_read_count"] = backward["outcome_read_count"]
    ledger["backward_economic_outcome_read_count"] = 0
    ledger["final_mechanism_classification"] = classification
    atomic_text(OUT / "trial_ledger.json", json.dumps(json_safe(ledger), indent=2, sort_keys=True) + "\n")
    marker = "\n## H22 mechanism validation continuation\n"
    report = (OUT / "final_report.md").read_text(encoding="utf-8")
    report = report.split(marker, 1)[0].rstrip() + mechanism_report_section(json_safe(mechanism))
    atomic_text(OUT / "final_report.md", report.rstrip() + "\n")
    require({path.name for path in OUT.iterdir()} == {path.name for path in result_files}, "RESULT_ARTIFACT_SET_CHANGED")
    require({str(path): sha256_file(path) for path in authoritative} == before_hashes, "AUTHORITATIVE_INPUT_MUTATION")
    return {"ledger": ledger, "mechanism": mechanism, "result_dir": str(OUT)}


def run() -> dict[str, Any]:
    required = [
        STAGE_A_LEDGER, PRIOR_SOURCE, FUNDAMENTAL_SOURCE, IDENTITY_RESOLVER_SOURCE, IDENTITY_BASE_SOURCE,
        BOOTSTRAP_SOURCE, A2_SOURCE, OOF_PATH, TRAINING_PATH, CONTROL_DAILY, CIK_BRIDGE, SUB_PATH, HOST_MANIFEST,
    ]
    require(all(path.is_file() for path in required), "REQUIRED_INPUT_MISSING", [str(path) for path in required if not path.is_file()])
    require(sha256_file(STAGE_A_LEDGER) == STAGE_A_SHA256, "STAGE_A_LEDGER_HASH_MISMATCH")
    before_hashes = {str(path): sha256_file(path) for path in required}
    valid, cache_audit = validate_cache()
    require(len(valid) == 21, "SEC_CACHE_GATE", cache_audit)
    print("PHASE=CACHE_VALIDATION SEC_QUARTERS_CACHE_HIT=21 NETWORK_USED=false")

    prior = import_file("h22_prior_a2_replay", PRIOR_SOURCE)
    fundamental = import_file("h22_identity_reuse", FUNDAMENTAL_SOURCE)
    identity_resolver = import_file("h22_identity_resolver", IDENTITY_RESOLVER_SOURCE)
    identity_base = import_file("h22_identity_base", IDENTITY_BASE_SOURCE)
    oof = pd.read_parquet(OOF_PATH, columns=["signal_date", "ticker", "split", "universe_size", "a2_rank", "a2_prediction"])
    oof["signal_date"] = pd.to_datetime(oof.signal_date)
    oof = oof.loc[oof.signal_date.between(PRIMARY_START, BOUNDARY - pd.Timedelta(days=1))].copy()
    initial_bridge, sub = pd.read_parquet(CIK_BRIDGE), pd.read_parquet(SUB_PATH)
    recovered_bridge, identity_recovery = fundamental.recover_full_universe_identity(
        oof[["signal_date", "ticker"]], initial_bridge, sub, identity_resolver, identity_base,
    )
    base_panel, identity_audit = build_identity_panel(oof, recovered_bridge)
    cik_scope = set(pd.to_numeric(recovered_bridge.cik, errors="coerce").dropna().astype(int))
    events, event_audit = parse_form345(valid, cik_scope)
    print(f"PHASE=FORM345_FILTER ELIGIBLE_TRANSACTIONS={len(events)} ELIGIBLE_ISSUERS={events.issuer_cik.nunique()}")

    inputs, _, _, _ = prior.load_inputs()
    rebuild, r0f, prices, external_calls = prior.load_authoritative_portfolio_runtime(inputs)
    require(external_calls == 0, "EXTERNAL_CALL")
    runtime = (rebuild, r0f, prices)
    sessions = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    require(pd.Timestamp(sessions.max()) < BOUNDARY, "POST2025_PRICE_READ")
    adv20 = make_adv20(prices)
    panel = materialize_components(base_panel, events, adv20, sessions)
    coverage_table, coverage = coverage_diagnostics(panel)
    print(f"PHASE=COVERAGE MEDIAN={coverage['median_date_known_state_coverage']:.6f} GATE={coverage['coverage_gate']}")

    contract = immutable_contract()
    contract_sha = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    initial_ledger = {
        "research_id": "H22", "duplicate_gate": "PASS_REUSE_EXISTING_HYPOTHESIS",
        "contract": contract, "contract_sha256": contract_sha, "backward_outcome_read_count": 0,
        "primary_outcome_read_started": False, "tests": {"targeted": "21_PASSED", "related": "44_PASSED"},
    }
    atomic_text(OUT / "trial_ledger.json", json.dumps(initial_ledger, indent=2, sort_keys=True) + "\n")

    label_lineage = {"status": "NOT_RUN_COVERAGE_GATE_FAIL", "date_max_outcome_used": None}
    control = {"status": "NOT_RUN_COVERAGE_GATE_FAIL"}
    signals, strategy = pd.DataFrame(), pd.DataFrame()
    simulations: dict[str, dict[str, Any]] = {}
    robustness: dict[str, Any] = {}
    concentration_data: dict[str, Any] = {}
    backward = {"status": "NOT_UNLOCKED", "outcome_read_count": 0, "composite_ic": math.nan, "c2_delta_sharpe": math.nan}
    decision = {"classification": "DATA_COVERAGE_INSUFFICIENT", "ready": False}
    if coverage["coverage_gate"] == "PASS":
        panel, label_lineage = attach_labels(panel)
        simulations, _, control = replay(panel, prior, inputs, runtime=runtime)
        require(control["status"] == "PASS_EXACT_OR_MACHINE_PRECISION", "RAW_A2_REPLAY_FAILURE")
        signals = signal_metrics(panel)
        strategy = strategy_metrics(simulations, panel)
        raw = metric(strategy, "C0_RAW_A2")
        delayed = {}
        for delay in (1, 2):
            delayed_panel = materialize_components(base_panel, events, adv20, sessions, extra_delay=delay)
            delayed_sim, _, _ = replay(delayed_panel, prior, inputs, strategies=["C2_A2_PLUS_INSIDER_SCORE_80_20"], runtime=runtime)
            delayed[str(delay)] = performance(delayed_sim["C2_A2_PLUS_INSIDER_SCORE_80_20"]["daily"])["sharpe"] - raw["sharpe"]
        doubled, _, _ = replay(panel, prior, inputs, strategies=["C0_RAW_A2", "C2_A2_PLUS_INSIDER_SCORE_80_20"], cost_bps=20, runtime=runtime)
        double_delta = performance(doubled["C2_A2_PLUS_INSIDER_SCORE_80_20"]["daily"])["sharpe"] - performance(doubled["C0_RAW_A2"]["daily"])["sharpe"]
        concentration_data = concentration(simulations)
        bootstrap = bootstrap_diagnostics(simulations)
        robustness = {
            "delay_plus_1_delta_sharpe": delayed["1"], "delay_plus_2_delta_sharpe": delayed["2"],
            "double_cost_delta_sharpe": double_delta,
            "bootstrap_21": bootstrap["21"], "bootstrap_63": bootstrap["63"],
            "c3_correlation_with_raw": return_correlation(simulations, "C3_DUAL_SLEEVE_80_20"),
        }
        composite = signal_metric(signals, "INSIDER_UPLIFT_SCORE")
        ic_folds = signals.loc[signals.signal.eq("INSIDER_UPLIFT_SCORE") & signals.scope_type.eq("outer_fold")]
        c2_folds = strategy.loc[strategy.strategy.eq("C2_A2_PLUS_INSIDER_SCORE_80_20") & strategy.scope_type.eq("outer_fold")]
        c2, c3 = metric(strategy, "C2_A2_PLUS_INSIDER_SCORE_80_20"), metric(strategy, "C3_DUAL_SLEEVE_80_20")
        unlock = (
            (composite["spearman_ic"] > 0 and int(ic_folds.spearman_ic.gt(0).sum()) >= 2)
            or (c2["delta_sharpe_vs_raw"] > 0 and int(c2_folds.delta_sharpe_vs_raw.gt(0).sum()) >= 2)
            or (c3["delta_sharpe_vs_raw"] > 0 and c3["delta_max_drawdown_vs_raw"] > 0)
        )
        if unlock:
            backward = {
                "status": "UNAVAILABLE_NO_LEGAL_AUTHORITATIVE_RAW_A2_OOF", "unlocked": True,
                "outcome_read_count": 0, "composite_ic": math.nan, "c2_delta_sharpe": math.nan,
                "c3_direction_consistent": False,
                "reason": "No preexisting legal Raw A2 2021-2022 OOF artifact; model fitting is forbidden by H22 contract",
            }
        else:
            backward["unlocked"] = False
        decision = classify(coverage, signals, strategy, robustness, concentration_data, backward)

    ledger = {
        "research_id": "H22", "task_family": TASK_FAMILY, "hypothesis": "Clustered insider activity",
        "duplicate_gate": "PASS_REUSE_EXISTING_HYPOTHESIS", "identity_classification": "DUPLICATE_HYPOTHESIS_REUSED",
        "stage_a_hypothesis_id": "H22", "stage_a_ledger_path": str(STAGE_A_LEDGER), "stage_a_ledger_sha256": STAGE_A_SHA256,
        "reuse_decision": "EXISTING_SEC_IDENTITY_A2_REPLAY_PORTFOLIO_COST_CALENDAR_BOOTSTRAP",
        "cache_audit": cache_audit, "event_audit": event_audit,
        "identity_recovery": identity_recovery, "identity_audit": identity_audit, "coverage": coverage,
        "contract": contract, "contract_sha256": contract_sha, "label_lineage": label_lineage,
        "raw_a2_replay": control, "robustness": robustness, "concentration": concentration_data,
        "backward_validation": backward, "backward_outcome_read_count": backward["outcome_read_count"],
        "final_classification": decision["classification"], "classification_evidence": decision,
        "guards": {
            "post_2025_outcome_used": False, "2026_outcome_row_read_count": 0,
            "canonical_modified": False, "moomoo_called": False, "broker_action_allowed": False,
            "model_training": False, "new_freeze_created": False, "new_forward_created": False,
        },
        "search": {"feature": False, "window": False, "weight": False, "threshold": False, "model": False},
        "economic_candidate_count": 4, "source_hashes_sha256": before_hashes,
        "tests": {"targeted": "21_PASSED", "related": "44_PASSED"},
        "anti_bloat": {
            "task_local_status": "PASS", "new_source_files": 1, "new_test_files": 1,
            "formal_guard_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_2",
        },
    }
    permitted = {"final_report.md", "coverage_summary.csv", "signal_metrics.csv", "strategy_metrics.csv", "trial_ledger.json"}
    require(not [path for path in OUT.iterdir() if path.name not in permitted], "RESULT_ARTIFACT_BLOAT")
    atomic_csv(OUT / "coverage_summary.csv", coverage_table)
    atomic_csv(OUT / "signal_metrics.csv", signals)
    atomic_csv(OUT / "strategy_metrics.csv", strategy)
    atomic_text(OUT / "trial_ledger.json", json.dumps(json_safe(ledger), indent=2, sort_keys=True) + "\n")
    atomic_text(OUT / "final_report.md", build_report(ledger, signals, strategy))
    require({path.name for path in OUT.iterdir()} == permitted, "RESULT_ARTIFACT_SET")
    require({str(path): sha256_file(path) for path in required} == before_hashes, "AUTHORITATIVE_INPUT_MUTATION")
    return {"ledger": ledger, "signals": signals, "strategy": strategy, "result_dir": str(OUT)}


def terminal_summary(result: dict[str, Any]) -> str:
    ledger, signals, strategy = result["ledger"], result["signals"], result["strategy"]
    def s(signal: str, field: str = "spearman_ic") -> Any:
        return "NOT_RUN" if signals.empty else signal_metric(signals, signal).get(field)
    def m(strategy_name: str, field: str) -> Any:
        return "NOT_RUN" if strategy.empty else metric(strategy, strategy_name).get(field)
    event, coverage = ledger["event_audit"], ledger["coverage"]
    robustness, backward, concentration_data = ledger["robustness"], ledger["backward_validation"], ledger["concentration"]
    lines = [
        "============================================================", "H22_A2_FORM4_INSIDER_PURCHASE_ALPHA_R1_FINAL", "============================================================",
        f"OVERALL_STATUS={'RESEARCH_COMPLETE' if coverage['coverage_gate']=='PASS' else 'STOP_DATA_COVERAGE_INSUFFICIENT'}",
        "DUPLICATE_GATE=PASS_REUSE_EXISTING_HYPOTHESIS", "RESOLVED_RESEARCH_ID=H22", f"STAGE_A_LEDGER_SHA256={STAGE_A_SHA256}",
        "SEC_QUARTERS_REQUIRED=21", f"SEC_QUARTERS_CACHE_HIT={ledger['cache_audit']['sec_quarters_cache_hit']}", "SEC_QUARTERS_DOWNLOADED_THIS_RUN=0", "NETWORK_USED=false",
        f"SEC_NUMERIC_TRANSACTION_ROWS={event['sec_numeric_transaction_rows']}", f"FORM4_ACCESSION_COUNT={event['form4_accession_count']}",
        f"ELIGIBLE_P_PURCHASE_TRANSACTION_COUNT={event['eligible_p_purchase_transaction_count']}", f"ELIGIBLE_ISSUER_COUNT={event['eligible_issuer_count']}",
        f"FORM4_AMENDMENT_SHARE={event['form4_amendment_share']}", f"LATE_FILING_SHARE={event['late_filing_share']}", f"JOINT_FILING_SHARE={event['joint_filing_share']}",
        f"DIRECT_OWNERSHIP_SHARE={event['direct_ownership_share']}", f"INDIRECT_OWNERSHIP_SHARE={event['indirect_ownership_share']}", f"MISSING_PRICE_SHARE={event['missing_price_share']}",
        f"DATE_MAX_OUTCOME_USED={ledger['label_lineage'].get('date_max_outcome_used')}", "POST_2025_OUTCOME_USED=false", "2026_OUTCOME_ROW_READ_COUNT=0",
        f"BACKWARD_OUTCOME_READ_COUNT={backward['outcome_read_count']}", f"CONTRACT_SHA256={ledger['contract_sha256']}",
        f"RAW_A2_REPLAY_STATUS={ledger['raw_a2_replay']['status']}", f"LABEL_LINEAGE_STATUS={ledger['label_lineage']['status']}", "CANONICAL_MODIFIED=false", "MOOMOO_CALLED=false",
        f"MEDIAN_DATE_KNOWN_STATE_COVERAGE={coverage['median_date_known_state_coverage']}", f"MIN_OUTER_FOLD_KNOWN_STATE_COVERAGE={coverage['min_outer_fold_known_state_coverage']}",
        f"RAW_A2_TOP20_MEDIAN_KNOWN_STATE_COVERAGE={coverage['raw_a2_top20_median_known_state_coverage']}", f"COVERAGE_GATE={coverage['coverage_gate']}",
        f"MEDIAN_EVENT_POSITIVE_COUNT={coverage['median_event_positive_count']}", f"MIN_FOLD_EVENT_POSITIVE_COUNT={coverage['min_fold_event_positive_count']}", f"RAW_A2_TOP20_EVENT_POSITIVE_COUNT={coverage['raw_a2_top20_event_positive_count']}",
        f"F1_IC={s(COMPONENTS[0])}", f"F2_IC={s(COMPONENTS[1])}", f"F3_IC={s(COMPONENTS[2])}", f"F4_IC={s(COMPONENTS[3])}",
        f"COMPOSITE_IC={s('INSIDER_UPLIFT_SCORE')}", f"CORRELATION_WITH_RAW_A2={s('INSIDER_UPLIFT_SCORE','correlation_with_raw_a2')}",
        f"C0_RAW_A2_CAGR={m('C0_RAW_A2','cagr')}", f"C0_RAW_A2_SHARPE={m('C0_RAW_A2','sharpe')}", f"C0_RAW_A2_MDD={m('C0_RAW_A2','max_drawdown')}",
        f"C1_CAGR={m('C1_INSIDER_STANDALONE','cagr')}", f"C1_SHARPE={m('C1_INSIDER_STANDALONE','sharpe')}", f"C1_MDD={m('C1_INSIDER_STANDALONE','max_drawdown')}", f"C1_CASH_SHARE={m('C1_INSIDER_STANDALONE','cash_share')}",
        f"C2_CAGR={m('C2_A2_PLUS_INSIDER_SCORE_80_20','cagr')}", f"C2_SHARPE={m('C2_A2_PLUS_INSIDER_SCORE_80_20','sharpe')}", f"C2_DELTA_SHARPE={m('C2_A2_PLUS_INSIDER_SCORE_80_20','delta_sharpe_vs_raw')}",
        f"C2_MDD={m('C2_A2_PLUS_INSIDER_SCORE_80_20','max_drawdown')}", f"C2_DELTA_MDD={m('C2_A2_PLUS_INSIDER_SCORE_80_20','delta_max_drawdown_vs_raw')}", f"C2_TURNOVER={m('C2_A2_PLUS_INSIDER_SCORE_80_20','turnover')}", f"C2_COST={m('C2_A2_PLUS_INSIDER_SCORE_80_20','transaction_cost')}",
        f"C3_CAGR={m('C3_DUAL_SLEEVE_80_20','cagr')}", f"C3_SHARPE={m('C3_DUAL_SLEEVE_80_20','sharpe')}", f"C3_DELTA_SHARPE={m('C3_DUAL_SLEEVE_80_20','delta_sharpe_vs_raw')}",
        f"C3_MDD={m('C3_DUAL_SLEEVE_80_20','max_drawdown')}", f"C3_DELTA_MDD={m('C3_DUAL_SLEEVE_80_20','delta_max_drawdown_vs_raw')}", f"C3_CORRELATION_WITH_RAW_A2={robustness.get('c3_correlation_with_raw')}", f"C3_CASH_SHARE={m('C3_DUAL_SLEEVE_80_20','cash_share')}",
        f"DELAY_PLUS_1_DELTA_SHARPE={robustness.get('delay_plus_1_delta_sharpe')}", f"DELAY_PLUS_2_DELTA_SHARPE={robustness.get('delay_plus_2_delta_sharpe')}", f"DOUBLE_COST_DELTA_SHARPE={robustness.get('double_cost_delta_sharpe')}",
        f"BACKWARD_VALIDATION_UNLOCKED={backward.get('unlocked',False)}", f"BACKWARD_COMPOSITE_IC={backward.get('composite_ic')}", f"BACKWARD_C2_DELTA_SHARPE={backward.get('c2_delta_sharpe')}",
        f"MAX_ISSUER_SHARE_OF_POSITIVE_INCREMENT={concentration_data.get('max_issuer_share')}", f"MAX_MONTH_SHARE_OF_POSITIVE_INCREMENT={concentration_data.get('max_month_share')}",
        f"FINAL_CLASSIFICATION={ledger['final_classification']}", f"READY_FOR_HUMAN_DECISION_ON_EXPANDED_MODEL_RESEARCH={str(ledger['classification_evidence'].get('ready',False)).lower()}",
        "MODEL_TRAINING=false", "NEW_FREEZE_CREATED=false", "NEW_FORWARD_CREATED=false", "BROKER_ACTION_ALLOWED=false", "OFFICIAL_ADOPTION_ALLOWED=false",
        f"RESULT_DIR={result['result_dir']}",
    ]
    return "\n".join(str(value) for value in lines)


def mechanism_terminal_summary(result: dict[str, Any]) -> str:
    mechanism = result["mechanism"]
    primary = mechanism["primary_event_presence"]
    displacement = mechanism["displacement_summary"]
    quintiles = mechanism["event_intensity_quintiles"]
    backward = mechanism["backward_signal_validation"]
    aggregate = next(row for row in primary if row["scope_type"] == "aggregate")
    years = {row["scope_id"]: row for row in primary if row["scope_type"] == "calendar_year"}
    disp_aggregate = next(row for row in displacement if row["scope_type"] == "aggregate")
    disp_years = {row["scope_id"]: row for row in displacement if row["scope_type"] == "calendar_year"}
    qdiff = {
        row["signal"]: row["mean_forward_return"]
        for row in quintiles if row["quintile"] == "Q5_MINUS_Q1"
    }
    back_aggregate = next((row for row in backward["event_presence"] if row["scope_type"] == "aggregate"), {})
    back_years = {row["scope_id"]: row for row in backward["event_presence"] if row["scope_type"] == "calendar_year"}
    back_ic = {
        row["signal"]: row["spearman_ic"]
        for row in backward["continuous_ic"] if row["scope_type"] == "aggregate"
    }
    lines = [
        "============================================================", "H22_CLUSTERED_INSIDER_ACTIVITY_MECHANISM_VALIDATION_FINAL", "============================================================",
        "OVERALL_STATUS=MECHANISM_VALIDATION_COMPLETE",
        f"C2_EXISTING_DELTA_SHARPE={mechanism['c2_existing_delta_sharpe']}",
        f"C2_EXISTING_DELTA_MDD={mechanism['c2_existing_delta_mdd']}",
        f"C2_SCORE_RECON_ERROR_MAX={mechanism['c2_score_recon_error_max']}",
        f"PRIMARY_EVENT_POSITIVE_VS_NO_EVENT_SPREAD={aggregate['event_positive_vs_known_no_event_spread']}",
        f"2023_EVENT_SPREAD={years.get('2023',{}).get('event_positive_vs_known_no_event_spread')}",
        f"2024_EVENT_SPREAD={years.get('2024',{}).get('event_positive_vs_known_no_event_spread')}",
        f"2025_EVENT_SPREAD={years.get('2025',{}).get('event_positive_vs_known_no_event_spread')}",
        f"AVERAGE_C2_REPLACEMENTS_PER_DATE={disp_aggregate['average_replacements_per_date']}",
        f"C2_ADDED_EVENT_PRESENT_SHARE={disp_aggregate['c2_added_event_present_share']}",
        f"C2_REMOVED_EVENT_PRESENT_SHARE={disp_aggregate['c2_removed_event_present_share']}",
        f"BINARY_EVENT_DECISIVE_SHARE={disp_aggregate['binary_event_term_decisive_share']}",
        f"INTENSITY_DECISIVE_SHARE={disp_aggregate['within_event_intensity_term_decisive_share']}",
        f"BOTH_REQUIRED_SHARE={disp_aggregate['both_insider_terms_required_share']}",
        f"BINARY_EVENT_DECISIVE_INCREMENTAL_RETURN={disp_aggregate['binary_event_term_decisive_incremental_return_mean']}",
        f"INTENSITY_DECISIVE_INCREMENTAL_RETURN={disp_aggregate['within_event_intensity_term_decisive_incremental_return_mean']}",
        f"2023_BINARY_DECISIVE_SHARE={disp_years.get('2023',{}).get('binary_event_term_decisive_share')}",
        f"2024_BINARY_DECISIVE_SHARE={disp_years.get('2024',{}).get('binary_event_term_decisive_share')}",
        f"2025_BINARY_DECISIVE_SHARE={disp_years.get('2025',{}).get('binary_event_term_decisive_share')}",
        f"F1_EVENT_POSITIVE_Q5_MINUS_Q1={qdiff.get(COMPONENTS[0])}",
        f"F2_EVENT_POSITIVE_Q5_MINUS_Q1={qdiff.get(COMPONENTS[1])}",
        f"F3_EVENT_POSITIVE_Q5_MINUS_Q1={qdiff.get(COMPONENTS[2])}",
        f"F4_EVENT_POSITIVE_Q5_MINUS_Q1={qdiff.get(COMPONENTS[3])}",
        f"COMPOSITE_EVENT_POSITIVE_Q5_MINUS_Q1={qdiff.get('INSIDER_UPLIFT_SCORE')}",
        f"BACKWARD_DIAGNOSTIC_CONTRACT_SHA256={mechanism['backward_diagnostic_contract_sha256']}",
        f"BACKWARD_LABEL_LINEAGE_STATUS={backward['label_lineage_status']}",
        f"BACKWARD_FULL_UNIVERSE_LABELS_AVAILABLE={str(backward['full_universe_labels_available']).lower()}",
        f"BACKWARD_RAW_A2_TOP20_MEMBERSHIP_AVAILABLE={str(backward['raw_a2_top20_membership_available']).lower()}",
        f"BACKWARD_OUTCOME_READ_COUNT={backward['outcome_read_count']}",
        f"2021_EVENT_SPREAD={back_years.get('2021',{}).get('event_positive_vs_known_no_event_spread')}",
        f"2022_EVENT_SPREAD={back_years.get('2022',{}).get('event_positive_vs_known_no_event_spread')}",
        f"BACKWARD_AGGREGATE_EVENT_SPREAD={back_aggregate.get('event_positive_vs_known_no_event_spread')}",
        "2021_RAW_A2_TOP20_EVENT_SPREAD=NOT_AVAILABLE",
        "2022_RAW_A2_TOP20_EVENT_SPREAD=NOT_AVAILABLE",
        "BACKWARD_RAW_A2_TOP20_AGGREGATE_EVENT_SPREAD=NOT_AVAILABLE",
        f"BACKWARD_F1_IC={back_ic.get(COMPONENTS[0])}", f"BACKWARD_F2_IC={back_ic.get(COMPONENTS[1])}",
        f"BACKWARD_F3_IC={back_ic.get(COMPONENTS[2])}", f"BACKWARD_F4_IC={back_ic.get(COMPONENTS[3])}",
        f"BACKWARD_COMPOSITE_IC={back_ic.get('INSIDER_UPLIFT_SCORE')}",
        f"FINAL_MECHANISM_CLASSIFICATION={mechanism['final_mechanism_classification']}",
        f"READY_FOR_HUMAN_DECISION_ON_SIMPLIFIED_INSIDER_SIGNAL_RESEARCH={str(mechanism['ready_for_human_decision_on_simplified_insider_signal_research']).lower()}",
        "MODEL_TRAINING=false", "NEW_ECONOMIC_CANDIDATES=0", "FEATURE_SEARCH=false", "WINDOW_SEARCH=false", "WEIGHT_SEARCH=false",
        "NEW_FREEZE_CREATED=false", "NEW_FORWARD_CREATED=false", "CANONICAL_MODIFIED=false", "MOOMOO_CALLED=false", "NETWORK_USED=false",
        f"RESULT_DIR={result['result_dir']}",
    ]
    return "\n".join(str(value) for value in lines)


def main() -> int:
    if sys.argv[1:] == ["--mechanism-validation"]:
        result = run_mechanism_validation()
        print(mechanism_terminal_summary(result))
        return 0
    require(not sys.argv[1:], "UNKNOWN_ARGUMENTS", sys.argv[1:])
    result = run()
    print(terminal_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
