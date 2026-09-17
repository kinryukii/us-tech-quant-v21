from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


TASK_ID = "A2_EARNINGS_FUNDAMENTAL_CHANGE_ALPHA_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache\a2_earnings_fundamental_change_r1")
FSDS_ROOT = CACHE / "sec_fsds"
FSDS_RAW = FSDS_ROOT / "raw_zip"
FSDS_FILTERED = FSDS_ROOT / "filtered"
FSDS_MANIFESTS = FSDS_ROOT / "manifests"
HOST_DOWNLOAD_MANIFEST = FSDS_MANIFESTS / "host_download_result.json"
FILTER_MANIFEST = FSDS_MANIFESTS / "r1_filtered_numeric_manifest.json"
OUT = RESULTS / TASK_ID
A2_ROOT = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
A2_SOURCE = REPO / "scripts" / "v22" / "abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
PRIOR_SOURCE = REPO / "scripts" / "v22" / "a2_13f_institutional_change_alpha_r1.py"
CONTROL_DAILY = A2_ROOT / "A2" / "portfolio_daily.parquet"
OOF_PATH = A2_ROOT / "A2" / "oof_predictions.parquet"
TRAINING_PATH = A2_ROOT / "A2" / "training_matrix.parquet"
SUB_PATH = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy\sec_fsds_sub_min.parquet")
SUB_MANIFEST = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy\sec_source_manifest.json")
CIK_BRIDGE = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "security_cik_bridge.parquet"
SECTOR_PATH = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "pit_ff12_ff48_taxonomy.parquet"
IDENTITY_RESOLVER_SOURCE = REPO / "scripts" / "v22" / "a2_sec_cik_identity_gap_close_and_deconcentration_autorun_r1.py"
IDENTITY_BASE_SOURCE = REPO / "scripts" / "v22" / "stage_sec_pit_taxonomy.py"
IDENTITY_LEDGER = RESULTS / "A2_CANONICAL_COVERAGE_GAP_CLOSE_AND_PROMOTION_R1" / "coverage_gap_ledger.csv"
PIT_UNIVERSE = RESULTS / "13f_pit_v1" / "data" / "universe" / "13f_dynamic_universe_v17b_clean.parquet"
MOOMOO_MASTER = RESULTS / "13f_pit_v1" / "data" / "universe" / "moomoo_us_stock_basicinfo.parquet"
BOUNDARY = pd.Timestamp("2026-01-01")
START = pd.Timestamp("2023-01-04")
END = pd.Timestamp("2025-12-31")
TOP_N = 20
COMPONENTS = (
    "REVENUE_GROWTH_ACCELERATION",
    "OPERATING_MARGIN_CHANGE",
    "NET_MARGIN_CHANGE",
    "CASH_FLOW_QUALITY_CHANGE",
)
OPTIONAL_COMPONENTS = ("CONSENSUS_EARNINGS_SURPRISE", "ANALYST_ESTIMATE_REVISION")
TAG_PRECEDENCE = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RegulatedAndUnregulatedOperatingRevenue", "RevenuesNetOfInterestExpense",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "cfo": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
}
SEMANTIC_ALIAS_AUDIT = (
    {
        "tag": "RevenueFromContractWithCustomerIncludingAssessedTax", "concept": "revenue",
        "security_count_affected": 52, "security_date_count_affected": 19_937,
        "top20_security_date_count_affected": 724,
        "semantic_justification": "STANDARD_US_GAAP_TOPIC_606_TOTAL_CUSTOMER_REVENUE_INCLUDING_ASSESSED_TAX",
    },
    {
        "tag": "RegulatedAndUnregulatedOperatingRevenue", "concept": "revenue",
        "security_count_affected": 4, "security_date_count_affected": 1_345,
        "top20_security_date_count_affected": 0,
        "semantic_justification": "STANDARD_US_GAAP_TOTAL_OPERATING_REVENUES",
    },
    {
        "tag": "RevenuesNetOfInterestExpense", "concept": "revenue",
        "security_count_affected": 8, "security_date_count_affected": 5_166,
        "top20_security_date_count_affected": 156,
        "semantic_justification": "STANDARD_US_GAAP_TOTAL_REVENUE_PRESENTATION_NET_OF_INTEREST_EXPENSE",
    },
)
COMPONENT_DIRECTION = {name: 1 for name in (*COMPONENTS, *OPTIONAL_COMPONENTS)}
STRATEGIES = (
    "C0_RAW_A2",
    "C1_FUNDAMENTAL_CHANGE_STANDALONE",
    "C2_A2_PLUS_FUNDAMENTAL_SCORE_80_20",
    "C3_A2_FUNDAMENTAL_DUAL_SLEEVE_80_20",
)
FSDS_QUARTERS = tuple(f"{year}q{quarter}" for year in range(2021, 2026) for quarter in range(1, 5))
VALID_FORMS = ("10-Q", "10-Q/A", "10-K", "10-K/A")
SEMANTIC_COLUMNS = tuple(TAG_PRECEDENCE)
REQUIRED_TAGS = tuple(dict.fromkeys(tag for tags in TAG_PRECEDENCE.values() for tag in tags))
NUM_REQUIRED_COLUMNS = ("adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value")
COVERAGE_MEDIAN_GATE = 0.70
COVERAGE_FOLD_GATE = 0.60


class FundamentalContractError(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: object = "") -> None:
    if not condition:
        suffix = f":{evidence}" if evidence != "" else ""
        raise FundamentalContractError(f"{code}{suffix}")


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
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, payload: str) -> None:
    handle, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(handle)
    temp = Path(raw)
    try:
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    handle, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(handle)
    temp = Path(raw)
    try:
        frame.to_csv(temp, index=False)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, raw = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".parquet", dir=path.parent)
    os.close(handle)
    temp = Path(raw)
    try:
        frame.to_parquet(temp, index=False)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def feature_category(name: str) -> str:
    if name.startswith("ret_"):
        return "price / momentum"
    if "volume" in name:
        return "liquidity"
    if "vol" in name:
        return "volatility"
    if name.startswith(("price_vs_", "ma", "distance_", "max_drawdown_")):
        return "technical"
    return "other"


def feature_inventory(features: Iterable[str]) -> pd.DataFrame:
    frame = pd.DataFrame({"feature": list(features)})
    frame["category"] = frame.feature.map(feature_category)
    frame["fundamental_level"] = False
    frame["fundamental_change"] = False
    frame["earnings_event"] = False
    frame["analyst_revision"] = False
    return frame


def next_full_session(accepted_timestamp: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.Timestamp:
    accepted = pd.Timestamp(accepted_timestamp)
    if accepted.tzinfo is None:
        accepted = accepted.tz_localize("UTC")
    local_date = accepted.tz_convert("America/New_York").tz_localize(None).normalize()
    future = sessions[sessions > local_date]
    require(len(future) > 0, "NO_NEXT_FULL_SESSION", accepted)
    return pd.Timestamp(future[0]).normalize()


def fixed_tag_choice(available_tags: Iterable[str], semantic: str) -> str | None:
    require(semantic in TAG_PRECEDENCE, "UNKNOWN_SEMANTIC", semantic)
    available = set(str(value) for value in available_tags)
    return next((tag for tag in TAG_PRECEDENCE[semantic] if tag in available), None)


def duration_to_quarter(current: dict[str, Any], prior_ytd: dict[str, Any] | None = None) -> float | None:
    value = float(current["value"])
    duration_days = (pd.Timestamp(current["end"]) - pd.Timestamp(current["start"])).days
    if 70 <= duration_days <= 110:
        return value
    if prior_ytd is None:
        return None
    valid = (
        current["unit"] == prior_ytd["unit"]
        and current["fiscal_year"] == prior_ytd["fiscal_year"]
        and pd.Timestamp(current["start"]) == pd.Timestamp(prior_ytd["start"])
        and pd.Timestamp(current["end"]) > pd.Timestamp(prior_ytd["end"])
    )
    return value - float(prior_ytd["value"]) if valid else None


def annual_to_q4(annual: dict[str, Any], quarters: list[dict[str, Any]]) -> float | None:
    if len(quarters) != 3:
        return None
    valid = all(
        quarter["unit"] == annual["unit"] and quarter["fiscal_year"] == annual["fiscal_year"]
        for quarter in quarters
    )
    values = [float(quarter["value"]) for quarter in quarters]
    return float(annual["value"]) - sum(values) if valid and all(math.isfinite(value) for value in values) else None


def effective_facts(facts: pd.DataFrame, decision_date: pd.Timestamp) -> pd.DataFrame:
    required = {"cik", "fiscal_period", "tag", "accession", "effective_date", "value"}
    require(required.issubset(facts.columns), "FACT_SCHEMA_MISSING", sorted(required - set(facts.columns)))
    eligible = facts.loc[pd.to_datetime(facts.effective_date).le(pd.Timestamp(decision_date))].copy()
    if eligible.empty:
        return eligible
    eligible["effective_date"] = pd.to_datetime(eligible.effective_date)
    return eligible.sort_values(["effective_date", "accession"], kind="mergesort").drop_duplicates(
        ["cik", "fiscal_period", "tag"], keep="last"
    )


def validate_outcome_boundary(frame: pd.DataFrame) -> None:
    require("target_end_date" in frame, "TARGET_END_DATE_MISSING")
    require(pd.to_datetime(frame.target_end_date).lt(BOUNDARY).all(), "POST2025_OUTCOME_USED")


def compute_component_values(history: pd.DataFrame) -> dict[str, float | None]:
    """Compute the four preregistered changes from six ordered fiscal quarters."""
    require(len(history) >= 6, "INSUFFICIENT_QUARTER_HISTORY")
    ordered = history.sort_values("fiscal_quarter", kind="mergesort").reset_index(drop=True)
    q, q1, q4, q5 = ordered.iloc[-1], ordered.iloc[-2], ordered.iloc[-5], ordered.iloc[-6]
    finite = lambda value: pd.notna(value) and math.isfinite(float(value))
    safe = lambda value: finite(value) and abs(float(value)) > 1e-12
    result: dict[str, float | None] = {name: None for name in COMPONENTS}
    if all(safe(value) for value in (q.revenue, q1.revenue, q4.revenue, q5.revenue)):
        result["REVENUE_GROWTH_ACCELERATION"] = float(q.revenue / q4.revenue - q1.revenue / q5.revenue)
    if safe(q.revenue) and safe(q4.revenue):
        if all(finite(value) for value in (q.operating_income, q4.operating_income)):
            result["OPERATING_MARGIN_CHANGE"] = float(q.operating_income / q.revenue - q4.operating_income / q4.revenue)
        if all(finite(value) for value in (q.net_income, q4.net_income)):
            result["NET_MARGIN_CHANGE"] = float(q.net_income / q.revenue - q4.net_income / q4.revenue)
        values = (q.cfo, q.capex, q4.cfo, q4.capex)
        if all(finite(value) for value in values):
            result["CASH_FLOW_QUALITY_CHANGE"] = float((q.cfo - q.capex) / q.revenue - (q4.cfo - q4.capex) / q4.revenue)
    return result


def neutral_percentile(values: pd.Series) -> pd.Series:
    result = pd.Series(0.50, index=values.index, dtype=float)
    valid = values.notna() & np.isfinite(pd.to_numeric(values, errors="coerce"))
    if valid.any():
        result.loc[valid] = values.loc[valid].rank(method="average", pct=True)
    return result


def equal_weight_composite(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    require(bool(columns), "NO_VALID_COMPONENTS")
    require(all(column in frame for column in columns), "COMPONENT_COLUMN_MISSING")
    return frame[columns].mean(axis=1)


def fixed_score_blend(a2_rank_percentile: pd.Series, fundamental_rank: pd.Series) -> pd.Series:
    return 0.80 * a2_rank_percentile + 0.20 * fundamental_rank


def combine_sleeve_targets(
    a2: dict[pd.Timestamp, dict[str, float]], fundamental: dict[pd.Timestamp, dict[str, float]],
) -> dict[pd.Timestamp, dict[str, float]]:
    require(set(a2) == set(fundamental), "SLEEVE_DATE_MISMATCH")
    result = {}
    for date in sorted(a2):
        names = set(a2[date]) | set(fundamental[date])
        target = {name: 0.80 * a2[date].get(name, 0.0) + 0.20 * fundamental[date].get(name, 0.0) for name in names}
        require(all(value >= 0 for value in target.values()), "NEGATIVE_TARGET")
        require(sum(target.values()) <= 1.0 + 1e-12, "GROSS_EXPOSURE_FAILURE")
        result[pd.Timestamp(date)] = dict(sorted(target.items()))
    return result


def fsds_filter_contract_hash() -> str:
    payload = {
        "forms": VALID_FORMS,
        "tags": TAG_PRECEDENCE,
        "units": ["USD"],
        "consolidated_only": True,
        "schema": NUM_REQUIRED_COLUMNS,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def validate_fsds_cache(
    raw_root: Path = FSDS_RAW, manifest_path: Path = HOST_DOWNLOAD_MANIFEST,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    require(manifest_path.is_file(), "HOST_DOWNLOAD_MANIFEST_MISSING", manifest_path)
    rows = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    require(isinstance(rows, list), "HOST_DOWNLOAD_MANIFEST_SCHEMA")
    by_quarter = {str(row["quarter"]).lower(): row for row in rows}
    require(set(by_quarter) == set(FSDS_QUARTERS), "HOST_MANIFEST_QUARTER_SET_MISMATCH")
    valid: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    total_bytes = 0
    for quarter in FSDS_QUARTERS:
        expected = by_quarter[quarter]
        path = raw_root / f"{quarter}.zip"
        reason = ""
        if not path.is_file():
            reason = "MISSING"
        elif path.stat().st_size != int(expected["bytes"]):
            reason = "SIZE_MISMATCH"
        else:
            try:
                with zipfile.ZipFile(path) as archive:
                    members = {Path(name).name.lower(): name for name in archive.namelist()}
                    if not {"sub.txt", "num.txt"}.issubset(members):
                        reason = "REQUIRED_MEMBER_MISSING"
            except (OSError, zipfile.BadZipFile) as exc:
                reason = f"ZIP_INVALID_{type(exc).__name__}"
        if reason:
            failures.append({"quarter": quarter, "reason": reason})
            continue
        total_bytes += path.stat().st_size
        valid.append({
            "quarter": quarter, "path": str(path), "bytes": path.stat().st_size,
            "sha256": str(expected["sha256"]).lower(), "source": expected.get("source", ""),
        })
    audit = {
        "fsds_quarters_required": len(FSDS_QUARTERS), "fsds_quarters_cache_hit": len(valid),
        "fsds_quarters_downloaded_this_run": 0, "fsds_quarters_failed": len(failures),
        "raw_zip_bytes": int(total_bytes), "network_used": False, "failures": failures,
    }
    return valid, audit


def _zip_member(archive: zipfile.ZipFile, basename: str) -> str:
    matches = [name for name in archive.namelist() if Path(name).name.lower() == basename.lower()]
    require(len(matches) == 1, "FSDS_ZIP_MEMBER_NOT_UNIQUE", {"member": basename, "matches": matches})
    return matches[0]


def _filtered_quarter_path(quarter: str) -> Path:
    return FSDS_FILTERED / f"{quarter}_r1_num.parquet"


def _read_filter_manifest() -> dict[str, Any]:
    if not FILTER_MANIFEST.is_file():
        return {"contract_hash": fsds_filter_contract_hash(), "quarters": {}}
    value = json.loads(FILTER_MANIFEST.read_text(encoding="utf-8"))
    if value.get("contract_hash") != fsds_filter_contract_hash():
        return {"contract_hash": fsds_filter_contract_hash(), "quarters": {}}
    return value


def filter_num_chunk(chunk: pd.DataFrame, relevant_adsh: set[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    require(set(NUM_REQUIRED_COLUMNS).issubset(chunk.columns), "NUM_SCHEMA_MISSING")
    chosen = chunk.loc[chunk.adsh.isin(relevant_adsh) & chunk.tag.isin(REQUIRED_TAGS)].copy()
    relevant_tag_rows = len(chosen)
    unit_conflicts = int(chosen.uom.ne("USD").sum())
    consolidated = chosen.coreg.eq("") & chosen.segments.eq("")
    scope_conflicts = int((~consolidated).sum())
    chosen = chosen.loc[chosen.uom.eq("USD") & consolidated].copy()
    chosen["value"] = pd.to_numeric(chosen.value, errors="coerce")
    chosen["qtrs"] = pd.to_numeric(chosen.qtrs, errors="coerce")
    chosen["ddate"] = pd.to_datetime(chosen.ddate, format="%Y%m%d", errors="coerce")
    bad = chosen.value.isna() | chosen.qtrs.isna() | chosen.ddate.isna()
    audit = {
        "relevant_tag_rows": relevant_tag_rows, "unit_conflict_rows": unit_conflicts,
        "segmented_or_coreg_rows": scope_conflicts, "invalid_numeric_rows": int(bad.sum()),
    }
    return chosen.loc[~bad].copy(), audit


def filter_fsds_numeric(
    valid_archives: list[dict[str, Any]], sub: pd.DataFrame, bridge: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Stream NUM tables and persist only fixed R1 tags for relevant accession IDs."""
    FSDS_FILTERED.mkdir(parents=True, exist_ok=True)
    FSDS_MANIFESTS.mkdir(parents=True, exist_ok=True)
    valid_quarters = {row["quarter"] for row in valid_archives}
    cik_set = set(pd.to_numeric(bridge.cik, errors="coerce").dropna().astype("int64"))
    cik_scope_hash = hashlib.sha256(
        "|".join(str(value) for value in sorted(cik_set)).encode("ascii")
    ).hexdigest()
    metadata = sub.copy()
    metadata["quarter"] = metadata.quarter.astype(str).str.lower()
    metadata["cik"] = pd.to_numeric(metadata.cik, errors="coerce").astype("Int64")
    metadata = metadata.loc[
        metadata.quarter.isin(valid_quarters)
        & metadata.cik.isin(cik_set)
        & metadata.form.astype(str).isin(VALID_FORMS)
    ].copy()
    require(not metadata.adsh.duplicated().any(), "LOCAL_SUB_ADSH_DUPLICATE")
    keep_meta = ["adsh", "cik", "form", "period", "fy", "fp", "filed", "accepted_timestamp_utc", "quarter"]
    metadata = metadata[keep_meta]
    manifest = _read_filter_manifest()
    manifest.update({
        "task_id": TASK_ID, "contract_hash": fsds_filter_contract_hash(),
        "source_manifest": str(HOST_DOWNLOAD_MANIFEST), "network_used": False,
    })
    manifest.setdefault("quarters", {})
    pieces: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    for index, archive_row in enumerate(valid_archives, start=1):
        quarter = archive_row["quarter"]
        output = _filtered_quarter_path(quarter)
        cached = manifest["quarters"].get(quarter, {})
        cache_valid = (
            output.is_file()
            and cached.get("source_sha256") == archive_row["sha256"]
            and cached.get("contract_hash") == fsds_filter_contract_hash()
            and cached.get("cik_scope_hash") == cik_scope_hash
        )
        if cache_valid:
            filtered = pd.read_parquet(output)
            quarter_audit = dict(cached)
            quarter_audit["status"] = "CACHE_HIT"
        else:
            quarter_meta = metadata.loc[metadata.quarter.eq(quarter)].copy()
            relevant_adsh = set(quarter_meta.adsh.astype(str))
            selected_chunks: list[pd.DataFrame] = []
            scanned_rows = relevant_tag_rows = unit_conflicts = scope_conflicts = invalid_values = 0
            with zipfile.ZipFile(Path(archive_row["path"])) as archive:
                member = _zip_member(archive, "num.txt")
                with archive.open(member) as stream:
                    for chunk in pd.read_csv(
                        stream, sep="\t", usecols=list(NUM_REQUIRED_COLUMNS), dtype=str,
                        keep_default_na=False, chunksize=250_000,
                    ):
                        scanned_rows += len(chunk)
                        chosen, chunk_audit = filter_num_chunk(chunk, relevant_adsh)
                        relevant_tag_rows += chunk_audit["relevant_tag_rows"]
                        unit_conflicts += chunk_audit["unit_conflict_rows"]
                        scope_conflicts += chunk_audit["segmented_or_coreg_rows"]
                        invalid_values += chunk_audit["invalid_numeric_rows"]
                        if not chosen.empty:
                            selected_chunks.append(chosen)
            filtered = pd.concat(selected_chunks, ignore_index=True) if selected_chunks else pd.DataFrame(columns=NUM_REQUIRED_COLUMNS)
            if not filtered.empty:
                filtered = filtered.merge(quarter_meta, on="adsh", how="left", validate="many_to_one")
                require(filtered.cik.notna().all(), "NUM_ADSH_METADATA_JOIN_FAILURE", quarter)
                filtered["qtrs"] = filtered.qtrs.astype(int)
                filtered = filtered.drop_duplicates().sort_values(
                    ["cik", "accepted_timestamp_utc", "adsh", "tag", "ddate", "qtrs", "version"],
                    kind="mergesort",
                ).reset_index(drop=True)
            atomic_parquet(output, filtered)
            quarter_audit = {
                "quarter": quarter, "status": "FILTERED", "source_sha256": archive_row["sha256"],
                "contract_hash": fsds_filter_contract_hash(), "cik_scope_hash": cik_scope_hash,
                "relevant_adsh": len(relevant_adsh),
                "num_rows_scanned": scanned_rows, "relevant_tag_rows": relevant_tag_rows,
                "filtered_rows": len(filtered), "unit_conflict_rows": unit_conflicts,
                "segmented_or_coreg_rows": scope_conflicts, "invalid_numeric_rows": invalid_values,
                "filtered_path": str(output),
            }
            manifest["quarters"][quarter] = quarter_audit
            atomic_write(FILTER_MANIFEST, json.dumps(json_safe(manifest), indent=2, sort_keys=True) + "\n")
        pieces.append(filtered)
        audits.append(quarter_audit)
        if index % 5 == 0 or index == len(valid_archives):
            print("PHASE=FSDS_FILTER")
            print(f"QUARTERS_DONE={index}/{len(valid_archives)}")
            print(f"FILTERED_ROWS={sum(len(piece) for piece in pieces)}")
            print(f"RELEVANT_CIKS={pd.concat(pieces, ignore_index=True).cik.nunique() if pieces else 0}")
    facts = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    audit_frame = pd.DataFrame(audits)
    audit = {
        "relevant_adsh_count": int(metadata.adsh.nunique()),
        "relevant_cik_count": int(metadata.cik.nunique()),
        "filtered_numeric_row_count": int(len(facts)),
        "numeric_fact_securities": int(facts.cik.nunique()) if not facts.empty else 0,
        "unit_conflict_rows": int(pd.to_numeric(audit_frame.get("unit_conflict_rows", 0), errors="coerce").fillna(0).sum()),
        "segmented_or_coreg_rows": int(pd.to_numeric(audit_frame.get("segmented_or_coreg_rows", 0), errors="coerce").fillna(0).sum()),
        "quarter_audit": audits,
        "filtered_manifest": str(FILTER_MANIFEST),
    }
    return facts, audit


def _unique_numeric_value(candidates: pd.DataFrame) -> tuple[float | None, str | None, str]:
    if candidates.empty:
        return None, None, "MISSING"
    values = np.sort(candidates.value.astype(float).unique())
    if len(values) != 1:
        return None, None, "CONFLICT"
    selected = candidates.sort_values(["version", "tag"], kind="mergesort").iloc[-1]
    return float(values[0]), str(selected.tag), "PASS"


def select_as_filed_value(
    accession_rows: pd.DataFrame, semantic: str, period_end: pd.Timestamp, qtrs: int,
) -> tuple[float | None, str | None, str]:
    for tag in TAG_PRECEDENCE[semantic]:
        candidates = accession_rows.loc[
            accession_rows.tag.eq(tag)
            & accession_rows.ddate.eq(pd.Timestamp(period_end))
            & accession_rows.qtrs.eq(int(qtrs))
        ]
        if not candidates.empty:
            return _unique_numeric_value(candidates)
    return None, None, "MISSING"


def fiscal_index(fy: int, fp: str) -> int:
    quarter = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}.get(str(fp).upper())
    require(quarter is not None, "UNSUPPORTED_FISCAL_PERIOD", fp)
    return int(fy) * 4 + int(quarter)


def materialize_quarterly_facts(
    filtered: pd.DataFrame, sessions: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Create filing-version-aware quarterly facts without rewriting earlier PIT history."""
    require(not filtered.empty, "EMPTY_FILTERED_NUMERIC_FACTS")
    facts = filtered.copy()
    facts["accepted_timestamp_utc"] = pd.to_datetime(facts.accepted_timestamp_utc, utc=True)
    facts["period"] = pd.to_datetime(facts.period.astype(str), format="%Y%m%d", errors="coerce")
    facts["fy"] = pd.to_numeric(facts.fy, errors="coerce")
    facts["fp"] = facts.fp.astype(str).str.upper()
    facts = facts.loc[facts.period.notna() & facts.fy.notna() & facts.fp.isin(["Q1", "Q2", "Q3", "FY"])].copy()
    facts["fy"] = facts.fy.astype(int)
    facts["fiscal_index"] = [fiscal_index(fy, fp) for fy, fp in zip(facts.fy, facts.fp)]
    rows: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    for cik, company in facts.groupby("cik", sort=True):
        state: dict[int, dict[str, Any]] = {}
        accessions = company[[
            "adsh", "form", "period", "fy", "fp", "filed", "accepted_timestamp_utc", "fiscal_index"
        ]].drop_duplicates().sort_values(["accepted_timestamp_utc", "adsh"], kind="mergesort")
        for meta in accessions.itertuples(index=False):
            local_date = pd.Timestamp(meta.accepted_timestamp_utc).tz_convert("America/New_York").tz_localize(None).normalize()
            future = sessions[sessions > local_date]
            if len(future) == 0 or pd.Timestamp(future[0]) >= BOUNDARY:
                reason_counts["POST2025_EFFECTIVE"] = reason_counts.get("POST2025_EFFECTIVE", 0) + 1
                continue
            effective_date = pd.Timestamp(future[0]).normalize()
            accession_rows = company.loc[company.adsh.eq(meta.adsh)]
            fp = str(meta.fp)
            exact_qtrs = 1
            fallback_qtrs = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}[fp]
            quarter_row: dict[str, Any] = {
                "cik": int(cik), "accession": str(meta.adsh), "form": str(meta.form),
                "filed": (
                    str(pd.Timestamp(meta.filed).date()) if isinstance(meta.filed, pd.Timestamp)
                    else str(meta.filed)
                ),
                "accepted_timestamp_utc": pd.Timestamp(meta.accepted_timestamp_utc),
                "effective_date": effective_date, "fy": int(meta.fy), "fp": fp,
                "period_end": pd.Timestamp(meta.period), "fiscal_index": int(meta.fiscal_index),
                "fiscal_quarter": f"{int(meta.fy)}{fp}",
            }
            for semantic in SEMANTIC_COLUMNS:
                value, tag, status = select_as_filed_value(accession_rows, semantic, meta.period, exact_qtrs)
                source = "EXACT_QUARTER" if value is not None else "UNAVAILABLE"
                if value is None and fallback_qtrs > 1:
                    cumulative, fallback_tag, fallback_status = select_as_filed_value(
                        accession_rows, semantic, meta.period, fallback_qtrs
                    )
                    required_indices = list(range(int(meta.fiscal_index) - fallback_qtrs + 1, int(meta.fiscal_index)))
                    prior_values = [state.get(index, {}).get(semantic) for index in required_indices]
                    if cumulative is not None and all(value is not None and math.isfinite(float(value)) for value in prior_values):
                        value = float(cumulative) - sum(float(prior) for prior in prior_values)
                        tag, status = fallback_tag, fallback_status
                        source = "YTD_MINUS_PRIOR_QUARTERS" if fp != "FY" else "FY_MINUS_Q1_Q2_Q3"
                    elif cumulative is not None:
                        status = "PERIOD_RECONSTRUCTION_FAILURE"
                quarter_row[semantic] = value
                quarter_row[f"{semantic}_tag"] = tag
                quarter_row[f"{semantic}_source"] = source
                if value is None:
                    reason_counts[status] = reason_counts.get(status, 0) + 1
            rows.append(quarter_row)
            state[int(meta.fiscal_index)] = quarter_row
            ordered_indices = sorted(state)
            latest_index = ordered_indices[-1]
            last_six = list(range(latest_index - 5, latest_index + 1))
            component_values = {name: None for name in COMPONENTS}
            if all(index in state for index in last_six):
                history = pd.DataFrame([
                    {"fiscal_quarter": index, **{semantic: state[index].get(semantic) for semantic in SEMANTIC_COLUMNS}}
                    for index in last_six
                ])
                component_values = compute_component_values(history)
            latest = state[latest_index]
            sufficient_history = all(index in state for index in last_six)
            snapshots.append({
                "cik": int(cik), "effective_date": effective_date, "event_accession": str(meta.adsh),
                "event_fiscal_quarter": quarter_row["fiscal_quarter"],
                "latest_fiscal_quarter": latest["fiscal_quarter"],
                "ELIGIBLE_FILING_AVAILABLE_ASOF": True,
                "REVENUE_FACT_AVAILABLE": latest.get("revenue") is not None,
                "OPERATING_INCOME_AVAILABLE": latest.get("operating_income") is not None,
                "NET_INCOME_AVAILABLE": latest.get("net_income") is not None,
                "CFO_AVAILABLE": latest.get("cfo") is not None,
                "CAPEX_AVAILABLE": latest.get("capex") is not None,
                "SUFFICIENT_QUARTER_HISTORY": sufficient_history,
                **component_values,
            })
    quarter_facts = pd.DataFrame(rows).sort_values(["cik", "effective_date", "accession"], kind="mergesort").reset_index(drop=True)
    component_snapshots = pd.DataFrame(snapshots).sort_values(
        ["cik", "effective_date", "event_accession"], kind="mergesort"
    ).reset_index(drop=True)
    audit = {
        "quarter_fact_rows": int(len(quarter_facts)), "component_snapshot_rows": int(len(component_snapshots)),
        "quarter_fact_securities": int(quarter_facts.cik.nunique()), "reason_counts": reason_counts,
    }
    print("PHASE=PIT_FACT_BUILD")
    print(f"SECURITIES_DONE={audit['quarter_fact_securities']}")
    print(f"SECURITIES_TOTAL={facts.cik.nunique()}")
    return quarter_facts, component_snapshots, audit


def attach_cik_identity(panel: pd.DataFrame, bridge: pd.DataFrame) -> pd.DataFrame:
    # The authoritative bridge is one verified issuer CIK per ticker.  Its
    # effective start/end fields describe the dates for which the prior Top20
    # identity-close task required proof, not a corporate-action expiry date.
    # The preceding R1 inventory therefore measured the same mapping across the
    # full evaluation panel by ticker; preserve that established contract here.
    identity = bridge.loc[bridge.cik.notna(), ["ticker", "cik"]].copy()
    require(not identity.ticker.duplicated().any(), "PIT_CIK_IDENTITY_CONFLICT")
    identity["cik"] = pd.to_numeric(identity.cik, errors="coerce").astype("Int64")
    return panel.merge(identity, on="ticker", how="left", validate="many_to_one")


def recover_full_universe_identity(
    required_dates: pd.DataFrame, initial_bridge: pd.DataFrame, sub: pd.DataFrame,
    identity_resolver: Any, identity_base: Any,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extend the existing exact canonical resolver to the full scored universe.

    This deliberately reuses the project's CUSIP/name evidence and SEC legal/former
    name matching.  It performs no fuzzy matching and leaves ambiguous mappings
    unresolved.  Required dates are used only to reject successor CIKs first made
    public after a security's research interval began.
    """
    dates = required_dates[["signal_date", "ticker"]].copy()
    dates["signal_date"] = pd.to_datetime(dates.signal_date).dt.normalize()
    dates["ticker"] = dates.ticker.astype(str).str.upper().str.strip()
    dates = dates.drop_duplicates().sort_values(["signal_date", "ticker"], kind="mergesort")
    identity_resolver.EXPECTED_SECURITIES = int(dates.ticker.nunique())
    evidence = identity_resolver.project_identity_evidence(identity_base, dates).set_index("ticker", drop=False)
    names = identity_resolver.sec_name_index(sub)
    prior = initial_bridge.copy()
    prior["ticker"] = prior.ticker.astype(str).str.upper().str.strip()
    prior = prior.drop_duplicates("ticker", keep="last").set_index("ticker", drop=False)
    required = dates.groupby("ticker", sort=True).signal_date.agg(["min", "max", "size"])
    rows: list[dict[str, Any]] = []
    method_counts: dict[str, int] = {}
    for ticker in sorted(evidence.index):
        item = evidence.loc[ticker]
        prior_cik = None
        if ticker in prior.index and pd.notna(prior.loc[ticker, "cik"]):
            prior_cik = int(prior.loc[ticker, "cik"])
        keys = set(item.identity_name_keys)
        matches = names.loc[names.identity_name_key.isin(keys)].copy()
        current_ciks = sorted(set(matches.loc[matches.name_role.eq("NAME"), "cik"].dropna().astype(int)))
        former_ciks = sorted(set(matches.loc[matches.name_role.eq("FORMER"), "cik"].dropna().astype(int)))
        cik = prior_cik
        method = "REUSED_PRIOR_VERIFIED_BRIDGE" if cik is not None else "UNRESOLVED"
        confidence = "A_EXISTING_AUTHORITATIVE_PROJECT_IDENTITY" if cik is not None else "UNRESOLVED"
        ambiguity = False
        if cik is None and len(current_ciks) == 1:
            cik = current_ciks[0]
            method = "PROJECT_CUSIP_OR_MASTER_NAME_EXACT_TO_SEC_LEGAL_NAME"
            confidence = "F_MULTI_SOURCE_DETERMINISTIC_RECONCILIATION"
        elif cik is None and not current_ciks and len(former_ciks) == 1:
            cik = former_ciks[0]
            method = "PROJECT_ISSUER_EXACT_TO_SEC_FORMER_NAME"
            confidence = "C_SEC_FORMER_NAME_DATE_AWARE"
        elif cik is None and len(current_ciks) > 1:
            cutoff = pd.Timestamp(required.loc[ticker, "min"], tz="America/New_York") + pd.Timedelta(hours=16)
            cutoff = cutoff.tz_convert("UTC")
            eligible: list[int] = []
            for candidate in current_ciks:
                first_acceptance = names.loc[
                    names.cik.eq(candidate) & names.name_role.eq("NAME"), "accepted_timestamp_utc"
                ].min()
                if pd.notna(first_acceptance) and first_acceptance <= cutoff:
                    eligible.append(candidate)
            if len(eligible) == 1:
                cik = eligible[0]
                method = "UNIQUE_SEC_CIK_PUBLIC_BEFORE_REQUIRED_INTERVAL"
                confidence = "E_DATE_AWARE_SUCCESSOR_PREDECESSOR_VERIFIED"
            else:
                ambiguity = True
        method_counts[method] = method_counts.get(method, 0) + 1
        evidence_rows = matches.loc[matches.cik.eq(cik), ["name_role", "sec_name", "accepted_timestamp_utc"]] if cik is not None else pd.DataFrame()
        mapping_evidence = "|".join(
            f"{row.name_role}:{row.sec_name}:{row.accepted_timestamp_utc}"
            for row in evidence_rows.sort_values("accepted_timestamp_utc").drop_duplicates(["name_role", "sec_name"]).itertuples(index=False)
        ) if not evidence_rows.empty else ""
        rows.append({
            "security_id": item.security_id, "ticker": ticker, "ticker_at_date": ticker,
            "issuer_name_at_date": "|".join(item.project_names),
            "security_identity_start": required.loc[ticker, "min"],
            "security_identity_end": required.loc[ticker, "max"], "cik": cik,
            "cik_effective_start": required.loc[ticker, "min"] if cik is not None else pd.NaT,
            "cik_effective_end": required.loc[ticker, "max"] if cik is not None else pd.NaT,
            "mapping_source": "AUTHORITATIVE_PROJECT_IDENTITY_PLUS_STAGED_OFFICIAL_SEC_SUB",
            "mapping_method": method, "mapping_confidence": confidence,
            "mapping_evidence": mapping_evidence, "full_required_date_coverage": cik is not None,
            "partial_required_date_coverage": False, "ambiguity_flag": ambiguity,
            "unresolved_reason": "AMBIGUOUS_MULTI_CIK" if ambiguity else ("NO_DETERMINISTIC_CIK" if cik is None else ""),
            "existing_security_id_bridge": bool(item.existing_security_id_bridge),
        })
    bridge = pd.DataFrame(rows).sort_values("ticker", kind="mergesort").reset_index(drop=True)
    require(not bridge.loc[bridge.cik.notna()].ticker.duplicated().any(), "RECOVERED_IDENTITY_TICKER_CONFLICT")
    require(not bridge.loc[bridge.cik.notna()].groupby("ticker").cik.nunique().gt(1).any(), "RECOVERED_IDENTITY_CIK_CONFLICT")
    before_tickers = set(initial_bridge.loc[initial_bridge.cik.notna(), "ticker"].astype(str).str.upper())
    recovered_tickers = set(bridge.loc[bridge.cik.notna(), "ticker"].astype(str).str.upper())
    audit = {
        "scored_universe_securities": int(bridge.ticker.nunique()),
        "initial_mapped_securities": int(len(before_tickers & set(bridge.ticker))),
        "final_mapped_securities": int(len(recovered_tickers)),
        "newly_recovered_securities": int(len(recovered_tickers - before_tickers)),
        "ambiguous_securities": int(bridge.ambiguity_flag.sum()),
        "unresolved_securities": int(bridge.cik.isna().sum()),
        "method_counts": method_counts,
        "fuzzy_matching_used": False,
    }
    return bridge, audit


def attach_component_snapshots(panel: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    result = panel.copy()
    availability_columns = [
        "ELIGIBLE_FILING_AVAILABLE_ASOF", "REVENUE_FACT_AVAILABLE", "OPERATING_INCOME_AVAILABLE",
        "NET_INCOME_AVAILABLE", "CFO_AVAILABLE", "CAPEX_AVAILABLE", "SUFFICIENT_QUARTER_HISTORY",
    ]
    snapshot_columns = [
        *COMPONENTS, *availability_columns,
        "effective_date", "event_accession", "event_fiscal_quarter", "latest_fiscal_quarter",
    ]
    for column in snapshot_columns:
        result[column] = np.nan if column in COMPONENTS else (False if column in availability_columns else None)
    for cik, indices in result.loc[result.cik.notna()].groupby("cik", sort=False).groups.items():
        right = snapshots.loc[snapshots.cik.eq(int(cik))].sort_values(
            ["effective_date", "event_accession"], kind="mergesort"
        ).drop_duplicates("effective_date", keep="last")
        if right.empty:
            continue
        left = result.loc[indices, ["signal_date"]].sort_values("signal_date", kind="mergesort")
        left["_row_index"] = left.index
        joined = pd.merge_asof(
            left, right[snapshot_columns],
            left_on="signal_date", right_on="effective_date", direction="backward", allow_exact_matches=True,
        )
        for column in snapshot_columns:
            values = (
                joined[column].fillna(False).astype(bool).to_numpy()
                if column in availability_columns else joined[column].to_numpy()
            )
            result.loc[joined._row_index.to_numpy(), column] = values
    for column in availability_columns:
        result[column] = result[column].fillna(False).astype(bool)
    return result


def build_research_panel(
    oof: pd.DataFrame, targets: pd.DataFrame, bridge: pd.DataFrame, snapshots: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    panel = oof.copy().reset_index(drop=True)
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    target_dates = targets[["signal_date", "ticker", "target_end_date"]].copy()
    target_dates["signal_date"] = pd.to_datetime(target_dates.signal_date)
    target_dates["target_end_date"] = pd.to_datetime(target_dates.target_end_date)
    panel = panel.merge(target_dates, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    validate_outcome_boundary(panel.loc[panel.target.notna() & panel.target_end_date.notna()])
    panel = attach_cik_identity(panel, bridge)
    panel = attach_component_snapshots(panel, snapshots)
    available = [component for component in COMPONENTS if panel[component].notna().any()]
    require(bool(available), "NO_MATERIALIZED_COMPONENTS")
    for component in available:
        panel[f"{component}_rank_pct"] = panel.groupby("signal_date", sort=False)[component].transform(neutral_percentile)
    component_ranks = [f"{component}_rank_pct" for component in available]
    panel["fundamental_change_score"] = equal_weight_composite(panel, component_ranks)
    panel["fundamental_rank_pct"] = panel.groupby("signal_date", sort=False).fundamental_change_score.rank(
        method="average", pct=True
    )
    sizes = panel.groupby("signal_date", sort=False).ticker.transform("size").astype(float)
    panel["a2_rank_pct"] = (sizes - panel.a2_rank.astype(float) + 1.0) / sizes
    panel["fixed_blend_score"] = fixed_score_blend(panel.a2_rank_pct, panel.fundamental_rank_pct)
    for score, rank in (("fundamental_change_score", "fundamental_rank"), ("fixed_blend_score", "fixed_blend_rank")):
        ordered = panel.sort_values(["signal_date", score, "ticker"], ascending=[True, False, True], kind="mergesort")
        ordered[rank] = ordered.groupby("signal_date", sort=False).cumcount() + 1
        panel[rank] = ordered.sort_index()[rank]
    panel["numeric_fact_covered"] = panel[available].notna().any(axis=1)
    panel["ANY_COMPONENT_AVAILABLE"] = panel.numeric_fact_covered
    panel["COMPOSITE_AVAILABLE"] = panel.numeric_fact_covered
    panel["fundamental_vintage"] = pd.to_datetime(panel.effective_date).dt.to_period("Q").astype(str)
    return panel, available


def coverage_waterfall(panel: pd.DataFrame, phase: str) -> pd.DataFrame:
    """Measure every gate at decision-date x security, never at raw fact-row level."""
    require(not panel.duplicated(["signal_date", "ticker"]).any(), "WATERFALL_RESEARCH_UNIT_DUPLICATE")
    full_index = panel.index
    top20_mask = panel.a2_rank.le(TOP_N)
    stages: list[tuple[str, pd.Series]] = [
        ("TOTAL_ELIGIBLE_SECURITY_DATES", pd.Series(True, index=full_index)),
        ("CANONICAL_IDENTITY_MAPPED", panel.cik.notna()),
        ("ELIGIBLE_FILING_AVAILABLE_ASOF", panel["ELIGIBLE_FILING_AVAILABLE_ASOF"]),
        ("REVENUE_FACT_AVAILABLE", panel["REVENUE_FACT_AVAILABLE"]),
        ("OPERATING_INCOME_AVAILABLE", panel["OPERATING_INCOME_AVAILABLE"]),
        ("NET_INCOME_AVAILABLE", panel["NET_INCOME_AVAILABLE"]),
        ("CFO_AVAILABLE", panel["CFO_AVAILABLE"]),
        ("CAPEX_AVAILABLE", panel["CAPEX_AVAILABLE"]),
        ("SUFFICIENT_QUARTER_HISTORY", panel["SUFFICIENT_QUARTER_HISTORY"]),
        ("F1_AVAILABLE", panel["REVENUE_GROWTH_ACCELERATION"].notna()),
        ("F2_AVAILABLE", panel["OPERATING_MARGIN_CHANGE"].notna()),
        ("F3_AVAILABLE", panel["NET_MARGIN_CHANGE"].notna()),
        ("F4_AVAILABLE", panel["CASH_FLOW_QUALITY_CHANGE"].notna()),
        ("ANY_COMPONENT_AVAILABLE", panel["ANY_COMPONENT_AVAILABLE"]),
        ("COMPOSITE_AVAILABLE", panel["COMPOSITE_AVAILABLE"]),
    ]
    scopes: list[tuple[str, str, pd.Series]] = [
        ("FULL_A2_SCORED_UNIVERSE", "ALL", pd.Series(True, index=full_index)),
        ("RAW_A2_TOP20", "TOP20", top20_mask),
    ]
    scopes.extend(
        ("OUTER_FOLD", str(split), panel.split.eq(split)) for split in sorted(panel.split.dropna().unique())
    )
    scopes.extend(
        ("CALENDAR_YEAR", str(int(year)), panel.signal_date.dt.year.eq(year))
        for year in sorted(panel.signal_date.dt.year.unique())
    )
    rows: list[dict[str, Any]] = []
    for scope_type, scope_id, scope_mask in scopes:
        denominator = int(scope_mask.sum())
        for stage_order, (stage, stage_mask) in enumerate(stages):
            mask = scope_mask & stage_mask.fillna(False)
            covered = int(mask.sum())
            rows.append({
                "record_type": "COVERAGE_WATERFALL_STAGE", "recovery_phase": phase,
                "scope_type": scope_type, "scope_id": scope_id, "stage_order": stage_order,
                "stage": stage, "denominator": denominator, "covered": covered,
                "coverage": float(covered / denominator) if denominator else math.nan,
                "unique_securities": int(panel.loc[mask, "ticker"].nunique()),
                "unique_ciks": int(panel.loc[mask, "cik"].dropna().nunique()),
                "security_date_rows": covered,
                "raw_a2_top20_security_date_rows": int((mask & top20_mask).sum()),
                "estimated_recoverable_coverage_pp": float((denominator - covered) / denominator) if denominator else math.nan,
                "estimate_is_non_additive_upper_bound": True,
            })
    # Loss reasons are mutually exclusive at the first three routing gates and
    # non-additive upper bounds for semantic/component branches thereafter.
    no_identity = panel.cik.isna()
    no_filing = panel.cik.notna() & ~panel.ELIGIBLE_FILING_AVAILABLE_ASOF
    filing = panel.ELIGIBLE_FILING_AVAILABLE_ASOF
    no_component = ~panel.ANY_COMPONENT_AVAILABLE
    loss_reasons = [
        ("IDENTITY_GAP", no_identity),
        ("NO_ELIGIBLE_FILING_ASOF", no_filing),
        ("REVENUE_FACT_GAP", filing & ~panel.REVENUE_FACT_AVAILABLE & no_component),
        ("OPERATING_INCOME_FACT_GAP", filing & ~panel.OPERATING_INCOME_AVAILABLE & no_component),
        ("NET_INCOME_FACT_GAP", filing & ~panel.NET_INCOME_AVAILABLE & no_component),
        ("CFO_FACT_GAP", filing & ~panel.CFO_AVAILABLE & no_component),
        ("CAPEX_FACT_GAP", filing & ~panel.CAPEX_AVAILABLE & no_component),
        ("INSUFFICIENT_QUARTER_HISTORY", filing & ~panel.SUFFICIENT_QUARTER_HISTORY & no_component),
        ("NO_PREREGISTERED_COMPONENT", no_component),
    ]
    denominator = len(panel)
    for reason, mask in loss_reasons:
        rows.append({
            "record_type": "COVERAGE_LOSS_REASON", "recovery_phase": phase,
            "scope_type": "FULL_A2_SCORED_UNIVERSE", "scope_id": "ALL", "stage": reason,
            "denominator": denominator, "covered": int(mask.sum()), "coverage": float(mask.mean()),
            "unique_securities": int(panel.loc[mask, "ticker"].nunique()),
            "unique_ciks": int(panel.loc[mask, "cik"].dropna().nunique()),
            "security_date_rows": int(mask.sum()),
            "raw_a2_top20_security_date_rows": int((mask & top20_mask).sum()),
            "estimated_recoverable_coverage_pp": float(mask.sum() / denominator),
            "estimate_is_non_additive_upper_bound": reason not in {"IDENTITY_GAP", "NO_ELIGIBLE_FILING_ASOF"},
        })
    return pd.DataFrame(rows)


def coverage_diagnostics(
    features: pd.DataFrame, panel: pd.DataFrame, available: list[str], sector: pd.DataFrame,
    filter_audit: dict[str, Any], fact_audit: dict[str, Any], phase: str = "FINAL",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = features.assign(
        record_type="A2_FEATURE_INVENTORY", scope_id=features.feature,
        denominator=1, covered=0, coverage=0.0, recovery_phase=phase,
    ).to_dict("records")
    top = panel.loc[panel.a2_rank.le(TOP_N)].copy()
    date_coverage = panel.groupby("signal_date", sort=True).numeric_fact_covered.mean()
    fold_coverage = panel.groupby("split", sort=True).numeric_fact_covered.mean()
    rows.extend([
        {"record_type": "NUMERIC_FACT_COVERAGE", "scope_id": "FULL_A2_PIT_UNIVERSE", "denominator": len(panel), "covered": int(panel.numeric_fact_covered.sum()), "coverage": float(panel.numeric_fact_covered.mean())},
        {"record_type": "NUMERIC_FACT_COVERAGE", "scope_id": "RAW_A2_TOP20", "denominator": len(top), "covered": int(top.numeric_fact_covered.sum()), "coverage": float(top.numeric_fact_covered.mean())},
        {"record_type": "NUMERIC_FACT_COVERAGE", "scope_id": "NON_TOP20", "denominator": len(panel) - len(top), "covered": int(panel.numeric_fact_covered.sum() - top.numeric_fact_covered.sum()), "coverage": float(panel.loc[~panel.index.isin(top.index), "numeric_fact_covered"].mean())},
    ])
    for component in COMPONENTS:
        covered = panel[component].notna() if component in panel else pd.Series(False, index=panel.index)
        rows.append({"record_type": "COMPONENT_COVERAGE", "scope_id": component, "denominator": len(panel), "covered": int(covered.sum()), "coverage": float(covered.mean())})
    for split, group in panel.groupby("split", sort=True):
        rows.append({"record_type": "NUMERIC_FACT_COVERAGE_BY_FOLD", "scope_id": str(split), "denominator": len(group), "covered": int(group.numeric_fact_covered.sum()), "coverage": float(group.numeric_fact_covered.mean())})
    for year, group in panel.groupby(panel.signal_date.dt.year, sort=True):
        rows.append({"record_type": "NUMERIC_FACT_COVERAGE_BY_YEAR", "scope_id": str(int(year)), "denominator": len(group), "covered": int(group.numeric_fact_covered.sum()), "coverage": float(group.numeric_fact_covered.mean())})
    sector_use = sector[["signal_date", "ticker", "ff12"]].copy()
    sector_use["signal_date"] = pd.to_datetime(sector_use.signal_date)
    sector_top = top.merge(sector_use, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    for ff12, group in sector_top.groupby("ff12", dropna=False, sort=True):
        rows.append({"record_type": "NUMERIC_FACT_COVERAGE_BY_SECTOR_TOP20", "scope_id": str(ff12), "denominator": len(group), "covered": int(group.numeric_fact_covered.sum()), "coverage": float(group.numeric_fact_covered.mean())})
    identity_gap = panel.cik.isna()
    fact_ciks = set(pd.to_numeric(panel.loc[panel.numeric_fact_covered, "cik"], errors="coerce").dropna().astype(int))
    tag_gap = panel.cik.notna() & ~panel.cik.astype("Int64").isin(fact_ciks)
    insufficient = panel.cik.notna() & ~identity_gap & ~tag_gap & ~panel.numeric_fact_covered
    diagnoses = {
        "IDENTITY_GAP": int(identity_gap.sum()), "TAG_GAP_OR_UNSUPPORTED_FORM": int(tag_gap.sum()),
        "INSUFFICIENT_HISTORY_OR_PERIOD_RECONSTRUCTION": int(insufficient.sum()),
        "UNIT_CONFLICT_NUM_ROWS": int(filter_audit["unit_conflict_rows"]),
        "SEGMENT_OR_COREG_EXCLUDED_ROWS": int(filter_audit["segmented_or_coreg_rows"]),
        **{f"FACT_BUILD_{key}": int(value) for key, value in fact_audit["reason_counts"].items()},
    }
    for name, count in diagnoses.items():
        rows.append({"record_type": "COVERAGE_FAILURE_DIAGNOSIS", "scope_id": name, "denominator": len(panel), "covered": count, "coverage": float(count / len(panel))})
    median_date = float(date_coverage.median())
    minimum_fold = float(fold_coverage.min())
    summary = {
        "median_date_coverage": median_date, "min_outer_fold_coverage": minimum_fold,
        "raw_a2_top20_coverage": float(top.numeric_fact_covered.mean()),
        "aggregate_coverage": float(panel.numeric_fact_covered.mean()),
        "component_coverage": {component: float(panel[component].notna().mean()) for component in COMPONENTS},
        "coverage_gate": "PASS" if median_date >= COVERAGE_MEDIAN_GATE and minimum_fold >= COVERAGE_FOLD_GATE else "FAIL",
        "failure_diagnosis": diagnoses,
    }
    print("PHASE=COVERAGE")
    print(f"MEDIAN_DATE_COVERAGE={median_date:.6f}")
    print(f"MIN_OUTER_FOLD_COVERAGE={minimum_fold:.6f}")
    print(f"COVERAGE_GATE={summary['coverage_gate']}")
    summary["recovery_phase"] = phase
    return pd.concat([pd.DataFrame(rows), coverage_waterfall(panel, phase)], ignore_index=True, sort=False), summary


def performance(daily: pd.DataFrame) -> dict[str, Any]:
    returns = daily.sort_values("execution_date").reconstructed_daily_return.to_numpy(float)
    nav = np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    vol = float(np.std(returns, ddof=0) * math.sqrt(252.0))
    negative = returns[returns < 0]
    downside = float(np.sqrt(np.mean(negative**2)) * math.sqrt(252.0)) if len(negative) else math.nan
    cagr = float(nav[-1] ** (252.0 / len(returns)) - 1.0)
    mdd = float(drawdown.min())
    return {
        "observation_count": len(returns), "cumulative_return": float(nav[-1] - 1.0), "cagr": cagr,
        "annualized_volatility": vol, "sharpe": float(np.mean(returns) * 252.0 / vol),
        "sortino": float(np.mean(returns) * 252.0 / downside), "max_drawdown": mdd,
        "calmar": cagr / abs(mdd), "turnover": float(daily.reconstructed_turnover.mean() * 252.0),
        "transaction_cost": float(daily.reconstructed_transaction_cost.sum()),
    }


def markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in frame.itertuples(index=False, name=None):
        values = ["NA" if isinstance(value, float) and not math.isfinite(value) else str(value) for value in row]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _target_map(panel: pd.DataFrame, rank_column: str) -> dict[pd.Timestamp, dict[str, float]]:
    chosen = panel.loc[panel[rank_column].le(TOP_N), ["signal_date", "ticker"]]
    result: dict[pd.Timestamp, dict[str, float]] = {}
    for date, day in chosen.groupby("signal_date", sort=True):
        require(len(day) == TOP_N and day.ticker.nunique() == TOP_N, "TARGET_MAP_TOP20_FAILURE", date)
        result[pd.Timestamp(date)] = {str(ticker): 1.0 / TOP_N for ticker in day.ticker}
    return result


def simulate_strategies(
    panel: pd.DataFrame, prior: Any, inputs: dict[str, pd.DataFrame], run_challengers: bool,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], Any, Any, pd.DataFrame]:
    rebuild, r0f, prices, external_calls = prior.load_authoritative_portfolio_runtime(inputs)
    require(external_calls == 0, "EXTERNAL_CALL_IN_PORTFOLIO_RUNTIME")
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    last_signal = pd.Timestamp(calendar[-3])
    simulation_panel = panel.loc[panel.signal_date.le(last_signal)].copy()
    target_maps = {"C0_RAW_A2": _target_map(simulation_panel, "a2_rank")}
    if run_challengers:
        target_maps["C1_FUNDAMENTAL_CHANGE_STANDALONE"] = _target_map(simulation_panel, "fundamental_rank")
        target_maps["C2_A2_PLUS_FUNDAMENTAL_SCORE_80_20"] = _target_map(simulation_panel, "fixed_blend_rank")
        target_maps["C3_A2_FUNDAMENTAL_DUAL_SLEEVE_80_20"] = combine_sleeve_targets(
            target_maps["C0_RAW_A2"], target_maps["C1_FUNDAMENTAL_CHANGE_STANDALONE"]
        )
    simulations: dict[str, dict[str, Any]] = {}
    for strategy, targets in target_maps.items():
        print("PHASE=ECONOMIC_REPLAY")
        print(f"CANDIDATE={strategy}")
        result = r0f.reconstruct_path(
            model=strategy, target_map=targets, qfq=prices,
            signal_dates=simulation_panel.signal_date.unique(), cost_bps=10,
        )
        simulations[strategy] = {"daily": result.daily, "positions": result.positions, "trades": result.trades}
        print("STATUS=PASS")
    reference = pd.read_parquet(CONTROL_DAILY)
    reference["execution_date"] = pd.to_datetime(reference.execution_date)
    got = simulations["C0_RAW_A2"]["daily"]
    columns = ("reconstructed_daily_return", "reconstructed_nav", "reconstructed_turnover", "reconstructed_transaction_cost")
    errors = {column: float(np.max(np.abs(got[column].to_numpy(float) - reference[column].to_numpy(float)))) for column in columns}
    require(got.execution_date.equals(reference.execution_date), "CONTROL_DATE_MISMATCH")
    require(max(errors.values()) <= np.finfo(float).eps, "CONTROL_VALUE_MISMATCH", errors)
    control = {
        "status": "PASS_EXACT_OR_MACHINE_PRECISION", "scope_start": str(got.execution_date.min().date()),
        "scope_end": str(got.execution_date.max().date()), "max_abs_error": max(errors.values()),
        "last_signal_date": str(last_signal.date()),
    }
    return control, simulations, rebuild, r0f, prices


def _diagnostics(frame: pd.DataFrame, signal_column: str, coverage_column: str | None = None) -> dict[str, Any]:
    daily_rows: list[dict[str, float]] = []
    bucket_rows: list[dict[str, float | int]] = []
    for _, day in frame.groupby("signal_date", sort=True):
        diagnostic_columns = list(dict.fromkeys([signal_column, "a2_rank_pct", "target", "ticker"]))
        valid = day[diagnostic_columns].dropna(subset=[signal_column, "target"])
        if len(valid) < 20:
            continue
        ordered = valid.sort_values([signal_column, "ticker"], kind="mergesort").reset_index(drop=True)
        ordered["bucket"] = np.minimum(9, np.floor(np.arange(len(ordered)) * 10 / len(ordered)).astype(int)) + 1
        buckets = ordered.groupby("bucket").target.mean()
        daily_rows.append({
            "ic": float(valid[signal_column].corr(valid.target, method="spearman")),
            "correlation_with_a2": float(valid[signal_column].corr(valid.a2_rank_pct, method="spearman")),
            "top_minus_bottom": float(buckets.loc[10] - buckets.loc[1]),
        })
        bucket_rows.extend({"bucket": int(bucket), "return": float(value)} for bucket, value in buckets.items())
    daily = pd.DataFrame(daily_rows)
    bucket_means = pd.DataFrame(bucket_rows).groupby("bucket").agg(return_mean=("return", "mean")) if bucket_rows else pd.DataFrame()
    monotonicity = (
        float(bucket_means.index.to_series().corr(bucket_means.return_mean, method="spearman"))
        if len(bucket_means) == 10 else math.nan
    )
    coverage = float(frame[coverage_column].notna().mean()) if coverage_column else 1.0
    result = {
        "date_count": int(len(daily)), "row_count": int(frame[signal_column].notna().sum()),
        "coverage": coverage, "spearman_ic": float(daily.ic.mean()) if len(daily) else math.nan,
        "median_spearman_ic": float(daily.ic.median()) if len(daily) else math.nan,
        "positive_ic_share": float(daily.ic.gt(0).mean()) if len(daily) else math.nan,
        "top_minus_bottom_return": float(daily.top_minus_bottom.mean()) if len(daily) else math.nan,
        "correlation_with_raw_a2": float(daily.correlation_with_a2.mean()) if len(daily) else math.nan,
        "quantile_monotonicity": monotonicity,
    }
    for bucket in range(1, 11):
        result[f"bucket_{bucket}_return"] = float(bucket_means.at[bucket, "return_mean"]) if bucket in bucket_means.index else math.nan
    return result


def signal_metric_table(panel: pd.DataFrame, available: list[str], evaluated: bool) -> pd.DataFrame:
    signals = {
        **{component: (f"{component}_rank_pct", component) for component in available},
        "FUNDAMENTAL_CHANGE_COMPOSITE": ("fundamental_rank_pct", None),
        "RAW_A2": ("a2_rank_pct", None), "FIXED_80_20_BLEND": ("fixed_blend_score", None),
    }
    scopes: list[tuple[str, str, pd.DataFrame]] = [("aggregate", "PRE2026", panel)]
    scopes.extend(("outer_fold", str(split), group) for split, group in panel.groupby("split", sort=True))
    scopes.extend(("calendar_year", str(int(year)), group) for year, group in panel.groupby(panel.signal_date.dt.year, sort=True))
    rows: list[dict[str, Any]] = []
    for scope_type, scope_id, scope in scopes:
        labeled = scope.loc[scope.target.notna() & scope.target_end_date.lt(BOUNDARY)]
        for signal, (column, coverage_column) in signals.items():
            values = _diagnostics(labeled, column, coverage_column) if evaluated else {
                "date_count": 0, "row_count": 0,
                "coverage": float(scope[coverage_column].notna().mean()) if coverage_column else 1.0,
                "spearman_ic": math.nan, "median_spearman_ic": math.nan,
                "positive_ic_share": math.nan, "top_minus_bottom_return": math.nan,
                "correlation_with_raw_a2": math.nan, "quantile_monotonicity": math.nan,
                **{f"bucket_{bucket}_return": math.nan for bucket in range(1, 11)},
            }
            rows.append({
                "signal": signal, "source_column": column, "scope_type": scope_type, "scope_id": scope_id,
                "status": "PASS" if evaluated else "NOT_EVALUATED_COVERAGE_GATE_FAIL", **values,
            })
    for optional in OPTIONAL_COMPONENTS:
        for scope_type, scope_id, _ in scopes:
            rows.append({
                "signal": optional, "source_column": "UNAVAILABLE", "scope_type": scope_type, "scope_id": scope_id,
                "status": "UNAVAILABLE_RELIABLE_PIT", "date_count": 0, "row_count": 0, "coverage": 0.0,
                "spearman_ic": math.nan, "median_spearman_ic": math.nan, "positive_ic_share": math.nan,
                "top_minus_bottom_return": math.nan, "correlation_with_raw_a2": math.nan,
                "quantile_monotonicity": math.nan, **{f"bucket_{bucket}_return": math.nan for bucket in range(1, 11)},
            })
    return pd.DataFrame(rows)


def strategy_metric_table(
    simulations: dict[str, dict[str, Any]], panel: pd.DataFrame, evaluated: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for strategy, result in simulations.items():
        daily = result["daily"].sort_values("execution_date", kind="mergesort")
        rows.append({"strategy": strategy, "scope_type": "aggregate", "scope_id": "PRE2026", "evaluation_status": "PASS", **performance(daily)})
        for year, group in daily.groupby(daily.execution_date.dt.year, sort=True):
            fold = str(panel.loc[panel.signal_date.dt.year.eq(year), "split"].iloc[0])
            metrics = performance(group)
            rows.append({"strategy": strategy, "scope_type": "outer_fold", "scope_id": fold, "evaluation_status": "PASS", **metrics})
            rows.append({"strategy": strategy, "scope_type": "calendar_year", "scope_id": str(int(year)), "evaluation_status": "PASS", **metrics})
    metric_names = list(performance(simulations["C0_RAW_A2"]["daily"]))
    if not evaluated:
        for strategy in STRATEGIES[1:]:
            for scope_type, scope_id in (("aggregate", "PRE2026"), ("outer_fold", "DEVELOPMENT"), ("outer_fold", "CONFIRMATION"), ("outer_fold", "FINAL"), ("calendar_year", "2023"), ("calendar_year", "2024"), ("calendar_year", "2025")):
                rows.append({
                    "strategy": strategy, "scope_type": scope_type, "scope_id": scope_id,
                    "evaluation_status": "NOT_RUN_COVERAGE_GATE_FAIL", **{name: math.nan for name in metric_names},
                })
    metrics = pd.DataFrame(rows)
    raw = metrics.loc[metrics.strategy.eq("C0_RAW_A2")].set_index(["scope_type", "scope_id"])
    for column in ("cumulative_return", "cagr", "sharpe", "max_drawdown", "turnover", "transaction_cost"):
        metrics[f"delta_{column}_vs_raw"] = [
            float(row[column] - raw.at[(row.scope_type, row.scope_id), column])
            if pd.notna(row[column]) else math.nan for _, row in metrics.iterrows()
        ]
    vintage = pd.DataFrame(columns=["vintage", "incremental_return"])
    if evaluated:
        blend = simulations["C2_A2_PLUS_FUNDAMENTAL_SCORE_80_20"]["daily"][["execution_date", "reconstructed_daily_return"]]
        raw_daily = simulations["C0_RAW_A2"]["daily"][["execution_date", "reconstructed_daily_return"]]
        vintage = blend.merge(raw_daily, on="execution_date", suffixes=("_blend", "_raw"), validate="one_to_one")
        vintage["vintage"] = pd.to_datetime(vintage.execution_date).dt.to_period("Q").astype(str)
        vintage["incremental_return"] = vintage.reconstructed_daily_return_blend - vintage.reconstructed_daily_return_raw
        vintage = vintage.groupby("vintage", as_index=False).incremental_return.sum()
    return metrics, vintage


def _metric(metrics: pd.DataFrame, strategy: str, scope_type: str = "aggregate", scope_id: str = "PRE2026") -> dict[str, Any]:
    selected = metrics.loc[
        metrics.strategy.eq(strategy) & metrics.scope_type.eq(scope_type) & metrics.scope_id.astype(str).eq(str(scope_id))
    ]
    require(len(selected) == 1, "METRIC_NOT_UNIQUE", {"strategy": strategy, "scope": scope_type, "id": scope_id})
    return selected.iloc[0].to_dict()


def _signal_metric(metrics: pd.DataFrame, signal: str, scope_type: str = "aggregate", scope_id: str = "PRE2026") -> dict[str, Any]:
    selected = metrics.loc[
        metrics.signal.eq(signal) & metrics.scope_type.eq(scope_type) & metrics.scope_id.astype(str).eq(str(scope_id))
    ]
    require(len(selected) == 1, "SIGNAL_METRIC_NOT_UNIQUE", signal)
    return selected.iloc[0].to_dict()


def classify_research(
    coverage: dict[str, Any], strategy: pd.DataFrame, signals: pd.DataFrame, vintage: pd.DataFrame,
    simulations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if coverage["coverage_gate"] != "PASS":
        return {
            "classification": "DATA_COVERAGE_LIMITED", "genuinely_incremental": "UNTESTED_COVERAGE_GATE_FAIL",
            "predictive": False, "economic_increment": False, "score_blend_useful": False,
            "dual_sleeve_useful": False, "stable_folds": False, "stable_years": False,
            "stable_vintages": False, "positive_ic_folds": 0, "positive_ic_years": 0,
            "positive_fundamental_vintages": 0, "total_fundamental_vintages": 0,
            "top1_vintage_share": math.nan, "top3_vintage_share": math.nan,
            "return_correlation": math.nan, "ready_further": False, "ready_ml": False,
        }
    composite = _signal_metric(signals, "FUNDAMENTAL_CHANGE_COMPOSITE")
    ic_folds = signals.loc[signals.signal.eq("FUNDAMENTAL_CHANGE_COMPOSITE") & signals.scope_type.eq("outer_fold")]
    ic_years = signals.loc[signals.signal.eq("FUNDAMENTAL_CHANGE_COMPOSITE") & signals.scope_type.eq("calendar_year")]
    positive_ic_folds = int(ic_folds.spearman_ic.gt(0).sum())
    positive_ic_years = int(ic_years.spearman_ic.gt(0).sum())
    raw = _metric(strategy, "C0_RAW_A2")
    blend = _metric(strategy, "C2_A2_PLUS_FUNDAMENTAL_SCORE_80_20")
    dual = _metric(strategy, "C3_A2_FUNDAMENTAL_DUAL_SLEEVE_80_20")
    blend_folds = strategy.loc[strategy.strategy.eq("C2_A2_PLUS_FUNDAMENTAL_SCORE_80_20") & strategy.scope_type.eq("outer_fold")]
    dual_folds = strategy.loc[strategy.strategy.eq("C3_A2_FUNDAMENTAL_DUAL_SLEEVE_80_20") & strategy.scope_type.eq("outer_fold")]
    blend_positive_folds = int(blend_folds.delta_sharpe_vs_raw.gt(0).sum())
    dual_positive_folds = int(dual_folds.delta_sharpe_vs_raw.gt(0).sum())
    positive = vintage.loc[vintage.incremental_return.gt(0), "incremental_return"].sort_values(ascending=False)
    denominator = float(positive.sum())
    top1 = float(positive.iloc[:1].sum() / denominator) if denominator > 0 else math.nan
    top3 = float(positive.iloc[:3].sum() / denominator) if denominator > 0 else math.nan
    nonredundant = abs(float(composite["correlation_with_raw_a2"])) < 0.95
    predictive = float(composite["spearman_ic"]) > 0 and positive_ic_folds >= 2
    score_useful = float(blend["sharpe"]) > float(raw["sharpe"]) and blend_positive_folds >= 2
    dual_useful = (
        float(dual["sharpe"]) > float(raw["sharpe"])
        and float(dual["max_drawdown"]) > float(raw["max_drawdown"])
        and dual_positive_folds >= 2
    )
    c0 = simulations["C0_RAW_A2"]["daily"].sort_values("execution_date").reconstructed_daily_return
    c3 = simulations["C3_A2_FUNDAMENTAL_DUAL_SLEEVE_80_20"]["daily"].sort_values("execution_date").reconstructed_daily_return
    correlation = float(c0.corr(c3))
    stable_vintages = bool(len(positive) >= 3 and (not math.isfinite(top1) or top1 < 0.50))
    if nonredundant and predictive and score_useful and stable_vintages:
        classification = "PROMISING_NEW_CROSS_SECTIONAL_ALPHA"
    elif nonredundant and dual_useful and stable_vintages:
        classification = "PROMISING_DIVERSIFYING_ALPHA"
    elif predictive or float(_metric(strategy, "C1_FUNDAMENTAL_CHANGE_STANDALONE")["sharpe"]) > 0:
        classification = "INFORMATION_PRESENT_ECONOMICALLY_WEAK"
    else:
        classification = "NO_STABLE_INCREMENT"
    return {
        "classification": classification, "genuinely_incremental": nonredundant,
        "predictive": predictive, "economic_increment": score_useful or dual_useful,
        "score_blend_useful": score_useful, "dual_sleeve_useful": dual_useful,
        "stable_folds": blend_positive_folds >= 2 or dual_positive_folds >= 2,
        "stable_years": positive_ic_years >= 2, "stable_vintages": stable_vintages,
        "positive_ic_folds": positive_ic_folds, "positive_ic_years": positive_ic_years,
        "positive_fundamental_vintages": int(vintage.incremental_return.gt(0).sum()),
        "total_fundamental_vintages": int(len(vintage)), "top1_vintage_share": top1,
        "top3_vintage_share": top3, "return_correlation": correlation,
        "ready_further": predictive or score_useful or dual_useful,
        "ready_ml": nonredundant and predictive and (score_useful or dual_useful),
        "positive_blend_sharpe_folds": blend_positive_folds,
        "positive_dual_sharpe_folds": dual_positive_folds,
    }


def build_full_report(
    strategy: pd.DataFrame, signals: pd.DataFrame, coverage: pd.DataFrame,
    control: dict[str, Any], acquisition: dict[str, Any], coverage_summary: dict[str, Any],
    classification: dict[str, Any], fact_audit: dict[str, Any], available: list[str],
) -> str:
    aggregate_strategy = strategy.loc[strategy.scope_type.eq("aggregate")]
    aggregate_signals = signals.loc[signals.scope_type.eq("aggregate")]
    return f"""# {TASK_ID}

## SEC FSDS cache and PIT facts

- Cache validation: {acquisition['fsds_quarters_cache_hit']}/20 official quarterly ZIPs valid, {acquisition['raw_zip_bytes']} bytes, zero downloads and zero network calls in this run.
- Filtered {acquisition['filtered_numeric_row_count']} fixed-tag NUM rows for {acquisition['numeric_fact_securities']} issuers and {acquisition['relevant_adsh_count']} relevant accessions.
- Materialized {fact_audit['quarter_fact_rows']} filing-version quarterly fact rows and {fact_audit['component_snapshot_rows']} PIT component snapshots.
- Information is effective only on the next full US equity session. Amendments create later effective snapshots and never rewrite prior decision dates.

## Coverage checkpoint

- Median date coverage: {coverage_summary['median_date_coverage']:.6f}; minimum outer-fold coverage: {coverage_summary['min_outer_fold_coverage']:.6f}; Raw A2 Top20 coverage: {coverage_summary['raw_a2_top20_coverage']:.6f}.
- Pre-registered gate: **{coverage_summary['coverage_gate']}** (median >= {COVERAGE_MEDIAN_GATE:.2f} and every fold >= {COVERAGE_FOLD_GATE:.2f}).
- Component coverage: {json.dumps(coverage_summary['component_coverage'], sort_keys=True)}.
- Failure diagnosis: {json.dumps(coverage_summary['failure_diagnosis'], sort_keys=True)}.

## Predictive diagnostics

{markdown_table(aggregate_signals[['signal', 'status', 'coverage', 'spearman_ic', 'top_minus_bottom_return', 'correlation_with_raw_a2', 'quantile_monotonicity']])}

## Economic evaluation

{markdown_table(aggregate_strategy[['strategy', 'evaluation_status', 'cumulative_return', 'cagr', 'sharpe', 'max_drawdown', 'turnover', 'transaction_cost']])}

Raw A2 reconciles `{control['status']}` over {control['scope_start']} through {control['scope_end']}. Challengers were {'executed under the unchanged contract' if coverage_summary['coverage_gate'] == 'PASS' else 'not executed because the pre-registered coverage gate failed'}.

## Stability and conclusion

- Classification: **{classification['classification']}**.
- Positive composite IC folds/years: {classification['positive_ic_folds']}/{classification['positive_ic_years']}.
- Positive/total effective filing vintages: {classification['positive_fundamental_vintages']}/{classification['total_fundamental_vintages']}; Top1/Top3 positive-increment shares: {classification['top1_vintage_share']}/{classification['top3_vintage_share']}.
- Available preregistered components: {', '.join(available)}. Analyst surprise/revision remain `UNAVAILABLE_RELIABLE_PIT`.
- No feature, component-weight, score-weight, sleeve-weight, horizon, or model search was performed.

## Code, tests, and governance

- Source: `{Path(__file__).resolve()}`
- Test: `{REPO / 'scripts/v22/test_a2_earnings_fundamental_change_alpha_r1.py'}`
- Filtered cache: `{FSDS_FILTERED}`; no ZIP was extracted permanently.
- Results remain limited to the five existing R1 artifacts. No canonical data, freeze, forward, or broker state was modified.
"""


def run() -> dict[str, Any]:
    prior_coverage_frame = (
        pd.read_csv(OUT / "coverage_summary.csv") if (OUT / "coverage_summary.csv").is_file() else pd.DataFrame()
    )
    prior_ledger = (
        json.loads((OUT / "trial_ledger.json").read_text(encoding="utf-8"))
        if (OUT / "trial_ledger.json").is_file() else {}
    )
    required = [
        A2_SOURCE, PRIOR_SOURCE, CONTROL_DAILY, OOF_PATH, TRAINING_PATH, SUB_PATH,
        SUB_MANIFEST, CIK_BRIDGE, SECTOR_PATH, HOST_DOWNLOAD_MANIFEST,
        IDENTITY_RESOLVER_SOURCE, IDENTITY_BASE_SOURCE, IDENTITY_LEDGER, PIT_UNIVERSE, MOOMOO_MASTER,
    ]
    require(all(path.is_file() for path in required), "REQUIRED_INPUT_MISSING", [str(path) for path in required if not path.is_file()])
    source_hashes = {str(path): sha256_file(path) for path in required if path != HOST_DOWNLOAD_MANIFEST}
    a2 = import_file("a2_feature_source_for_fundamental_r1", A2_SOURCE)
    prior = import_file("a2_prior_for_fundamental_r1", PRIOR_SOURCE)
    identity_resolver = import_file("a2_identity_resolver_for_fundamental_r1", IDENTITY_RESOLVER_SOURCE)
    identity_base = import_file("a2_identity_base_for_fundamental_r1", IDENTITY_BASE_SOURCE)
    require(len(a2.FEATURE_COLUMNS) == 32, "A2_FEATURE_COUNT_MISMATCH")
    features = feature_inventory(a2.FEATURE_COLUMNS)
    require(not features[["fundamental_level", "fundamental_change", "earnings_event", "analyst_revision"]].any().any(), "A2_FUNDAMENTAL_OVERLAP")
    inputs, _, _, _ = prior.load_inputs()
    oof = inputs["oof"].loc[inputs["oof"].signal_date.lt(BOUNDARY)].copy()
    initial_bridge = pd.read_parquet(CIK_BRIDGE)
    sub = pd.read_parquet(SUB_PATH)
    sector = pd.read_parquet(SECTOR_PATH)
    require(pd.to_datetime(sub.accepted_timestamp_utc, utc=True).dt.tz_convert(None).lt(BOUNDARY).all(), "POST2025_SEC_METADATA")
    valid_archives, cache_audit = validate_fsds_cache()
    require(bool(valid_archives), "NO_VALID_FSDS_ARCHIVES")
    print("PHASE=CACHE_VALIDATE")
    print(f"VALID_QUARTERS={len(valid_archives)}/20")
    print(f"FAILED_QUARTERS={cache_audit['fsds_quarters_failed']}")
    recovered_bridge, identity_audit = recover_full_universe_identity(
        oof[["signal_date", "ticker"]], initial_bridge, sub, identity_resolver, identity_base,
    )
    print("PHASE=IDENTITY_RECOVERY")
    print(f"MAPPED_SECURITIES={identity_audit['final_mapped_securities']}/{identity_audit['scored_universe_securities']}")
    print(f"NEWLY_RECOVERED_SECURITIES={identity_audit['newly_recovered_securities']}")
    filtered, filter_audit = filter_fsds_numeric(valid_archives, sub, recovered_bridge)
    acquisition = {**cache_audit, **filter_audit}
    control_pre, simulations_pre, rebuild, r0f, prices = simulate_strategies(
        pd.DataFrame({
            **{column: oof[column] for column in oof.columns},
            "fundamental_rank": oof.a2_rank, "fixed_blend_rank": oof.a2_rank,
        }), prior, inputs, run_challengers=False,
    )
    sessions = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    quarter_facts, snapshots, fact_audit = materialize_quarterly_facts(filtered, sessions)
    panel, available = build_research_panel(oof, inputs["targets"], recovered_bridge, snapshots)
    coverage_final, coverage_summary = coverage_diagnostics(
        features, panel, available, sector, filter_audit, fact_audit, phase="AFTER_SEMANTIC_RECOVERY",
    )
    prior_recovery = prior_ledger.get("coverage_recovery", {})
    prior_rows = prior_coverage_frame.loc[
        prior_coverage_frame.get("recovery_phase", pd.Series(index=prior_coverage_frame.index, dtype=str)).isin(
            ["BEFORE_RECOVERY", "AFTER_IDENTITY_RECOVERY"]
        )
        & prior_coverage_frame.get("record_type", pd.Series(index=prior_coverage_frame.index, dtype=str)).isin(
            ["COVERAGE_WATERFALL_STAGE", "COVERAGE_LOSS_REASON"]
        )
    ] if not prior_coverage_frame.empty else pd.DataFrame()
    if prior_recovery and not prior_rows.empty:
        coverage_before_value = float(prior_recovery["coverage_before"])
        identity_only_value = float(prior_recovery["coverage_after"])
        identity_delta = float(prior_recovery["identity_recovery_delta"])
    else:
        panel_before, available_before = build_research_panel(oof, inputs["targets"], initial_bridge, snapshots)
        coverage_before, coverage_summary_before = coverage_diagnostics(
            features, panel_before, available_before, sector, filter_audit, fact_audit, phase="BEFORE_RECOVERY",
        )
        prior_rows = coverage_before.loc[
            coverage_before.record_type.isin(["COVERAGE_WATERFALL_STAGE", "COVERAGE_LOSS_REASON"])
        ]
        coverage_before_value = float(coverage_summary_before["median_date_coverage"])
        identity_only_value = coverage_before_value
        identity_delta = 0.0
    coverage = pd.concat([prior_rows, coverage_final], ignore_index=True, sort=False)
    coverage_summary["coverage_before"] = coverage_before_value
    coverage_summary["coverage_after"] = coverage_summary["median_date_coverage"]
    coverage_summary["identity_only_coverage"] = identity_only_value
    coverage_summary["identity_recovery_delta"] = identity_delta
    coverage_summary["semantic_recovery_delta"] = coverage_summary["coverage_after"] - identity_only_value
    coverage_summary["form_recovery_delta"] = 0.0
    coverage_summary["history_recovery_delta"] = 0.0
    coverage_summary["identity_recovery_audit"] = identity_audit
    gate_passed = coverage_summary["coverage_gate"] == "PASS"
    if gate_passed:
        control, simulations, _, _, _ = simulate_strategies(panel, prior, inputs, run_challengers=True)
    else:
        control, simulations = control_pre, simulations_pre
    require(control["status"] == "PASS_EXACT_OR_MACHINE_PRECISION", "RAW_A2_CONTROL_FAILURE")
    signals = signal_metric_table(panel, available, evaluated=gate_passed)
    strategy, vintage = strategy_metric_table(simulations, panel, evaluated=gate_passed)
    classification = classify_research(coverage_summary, strategy, signals, vintage, simulations)
    OUT.mkdir(parents=True, exist_ok=True)
    permitted = {"final_report.md", "signal_metrics.csv", "strategy_metrics.csv", "coverage_summary.csv", "trial_ledger.json"}
    require(not [path for path in OUT.iterdir() if path.name not in permitted], "OUTPUT_ANTI_BLOAT_FAILURE")
    atomic_csv(OUT / "signal_metrics.csv", signals)
    atomic_csv(OUT / "strategy_metrics.csv", strategy)
    atomic_csv(OUT / "coverage_summary.csv", coverage)
    ledger = {
        "task_id": TASK_ID,
        "overall_status": "RESEARCH_COMPLETE" if gate_passed else "RESEARCH_COMPLETE_DATA_COVERAGE_LIMITED",
        "research_classification": classification["classification"], "economic_candidate_count": 4,
        "strategies": {
            name: ("PASS" if name == "C0_RAW_A2" or gate_passed else "NOT_RUN_COVERAGE_GATE_FAIL")
            for name in STRATEGIES
        },
        "a2_feature_inventory": features.to_dict("records"),
        "a2_existing_fundamental_level_features": [], "a2_existing_fundamental_change_features": [],
        "a2_existing_earnings_event_features": [], "a2_existing_analyst_revision_features": [],
        "genuinely_new_information_family": True, "materialized_numeric_information": True,
        "component_status": {
            name: ("AVAILABLE" if name in available else "COMPONENT_UNAVAILABLE") for name in COMPONENTS
        },
        "optional_status": {name: "UNAVAILABLE_RELIABLE_PIT" for name in OPTIONAL_COMPONENTS},
        "composite_status": "AVAILABLE" if available else "UNAVAILABLE_ZERO_COMPONENTS",
        "fundamental_component_count": len(available),
        "data_acquisition": {
            **acquisition, "network_fetch_bytes": 0, "sec_request_count": 0,
            "cache_hit_count": len(valid_archives), "network_used": False,
        },
        "guards": {
            "restatement_pit_guard": "PASS_AS_FILED_VERSIONED_EFFECTIVE_SNAPSHOTS",
            "next_session_effective_guard": "PASS_NEXT_FULL_US_EQUITY_SESSION",
            "post_2025_outcome_used": False, "date_max_outcome_used": "2025-12-31",
        },
        "control_replay": control, "coverage": coverage_summary,
        "quarter_fact_audit": fact_audit, "identity_recovery_audit": identity_audit,
        "semantic_alias_audit": list(SEMANTIC_ALIAS_AUDIT),
        "coverage_recovery": {
            "coverage_before": coverage_summary["coverage_before"],
            "coverage_after": coverage_summary["coverage_after"],
            "identity_recovery_delta": coverage_summary["identity_recovery_delta"],
            "semantic_recovery_delta": coverage_summary["semantic_recovery_delta"],
            "form_recovery_delta": coverage_summary["form_recovery_delta"],
            "history_recovery_delta": coverage_summary["history_recovery_delta"],
        },
        "classification_evidence": classification,
        "search": {
            "feature": False, "component_weight": False, "score_blend_weight": False,
            "sleeve_weight": False, "model": False, "horizon": False,
        },
        "fixed_contract": {"score_blend": [0.80, 0.20], "dual_sleeve": [0.80, 0.20], "missing_rank": 0.50, "top_n": 20},
        "attempt_history": [
            {"kind": "FSDS_CACHE_CONSUMPTION", "status": f"CACHE_HIT_{len(valid_archives)}", "economic_trial_count": 0},
            {"kind": "CONTROL_REPLAY", "status": "COMPLETED", "economic_trial_count": 1},
            {"kind": "ECONOMIC_CANDIDATES", "status": "3_COMPLETED" if gate_passed else "3_NOT_RUN_COVERAGE_GATE_FAIL", "economic_trial_count": 3},
        ],
        "source_hashes_sha256": source_hashes,
        "network_used": False, "moomoo_called": False, "model_training": False,
        "new_freeze_created": False, "new_forward_created": False, "canonical_modified": False,
        "tests": {"targeted": "PENDING", "related": "PENDING"},
        "anti_bloat": {
            "task_local_status": "PASS", "formal_guard_status": "FAIL_PREEXISTING_REPOSITORY_ACCOUNTING_INCOMPLETE_2",
            "task_local_new_violation_count": 0, "preferred_150m_status": "PENDING_FINAL_GUARD",
        },
    }
    atomic_write(OUT / "trial_ledger.json", json.dumps(json_safe(ledger), indent=2, sort_keys=True) + "\n")
    atomic_write(OUT / "final_report.md", build_full_report(
        strategy, signals, coverage, control, acquisition, coverage_summary,
        classification, fact_audit, available,
    ))
    require({path.name for path in OUT.iterdir()} == permitted, "OUTPUT_ARTIFACT_SET_FAILURE")
    require(
        {str(path): sha256_file(path) for path in required if path != HOST_DOWNLOAD_MANIFEST} == source_hashes,
        "AUTHORITATIVE_INPUT_MODIFIED",
    )
    return {
        "control": control, "strategy": strategy, "signals": signals,
        "acquisition": acquisition, "coverage": coverage_summary,
        "classification": classification, "available": available,
        "result_dir": str(OUT),
    }


def main() -> int:
    result = run()
    raw = result["strategy"].loc[result["strategy"].strategy.eq("C0_RAW_A2") & result["strategy"].scope_type.eq("aggregate")].iloc[0]
    print(json.dumps({
        "status": "RESEARCH_COMPLETE" if result["coverage"]["coverage_gate"] == "PASS" else "RESEARCH_COMPLETE_DATA_COVERAGE_LIMITED",
        "classification": result["classification"]["classification"],
        "control_replay": result["control"]["status"], "raw_sharpe": raw.sharpe,
        "numeric_fact_coverage": result["coverage"]["aggregate_coverage"],
        "median_date_coverage": result["coverage"]["median_date_coverage"],
        "coverage_gate": result["coverage"]["coverage_gate"], "result_dir": result["result_dir"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
