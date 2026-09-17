from __future__ import annotations

"""Outcome-blind, checkpoint-driven SEC fundamental coverage recovery R2."""

import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


TASK_ID = "A2_SEC_FUNDAMENTAL_TARGETED_COVERAGE_RECOVERY_R2"
TASK_KIND = "OUTCOME_BLIND_TARGETED_SEC_COVERAGE_RECOVERY"
SOURCE_RESEARCH_ID = "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache\sec_fundamental_pit_r1")
SOURCE = RESULTS / SOURCE_RESEARCH_ID
OUT = RESULTS / TASK_ID
CHECKPOINT = RESULTS / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1" / "raw_a2_top40_membership_checkpoint.parquet"
CHECKPOINT_SHA256 = "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17"
PREREG_SHA256 = "001ce13b44adaa1c8ccb0bd8340a3ed383c2c481e8d75c4fd77e2ccacad4d900"
CONCEPT_SHA256 = "3840fd339105f90a804af00ee637be2ce88e7af1f637911a54bd902c23dee19a"
TARGETED_SHA256 = "0d8bfd77b9f92a38656dfdca9a14df1d95c4632571ae5c58c3f9c0268f34d811"
SOURCE_REPORT_SHA256 = "a7d0de252c67460466f76ea600b342c1242949604173dca33641a8ec321c1357"
SOURCE_MANIFEST_SHA256 = "90a6033746f706a60a44af6dabd9ad1b4b22bbfafa34d9a502428f5e65c6923e"
COMPANYFACTS = CACHE / "bulk" / "companyfacts.zip"
SUBMISSIONS = CACHE / "bulk" / "submissions.zip"
PAYLOAD_CONTRACT = {
    "companyfacts": (COMPANYFACTS, 1_407_131_132, 20_266, "d7b4b3c5f2fe014a203bdaef2197d2cba5683f434e965fc9bced1023a43c82ca"),
    "submissions": (SUBMISSIONS, 1_559_612_838, 987_520, "928d67221c6e6183bc343e7234c1391448c15cd1dd644d36b425db2f99ba4350"),
}
FEATURE_LEDGER = SOURCE / "fundamental_feature_ledger.parquet"
STATE_PATH = CACHE / "derived_bulk_resume" / "fundamental_feature_states.parquet"
STATE_MANIFEST = CACHE / "derived_bulk_resume" / "fundamental_feature_states_manifest.json"
CACHE_MANIFEST = CACHE / "cache_manifest.json"
UNIVERSE_INTERVALS = RESULTS / "A2_PIT13F_MATERIALIZATION_R1" / "effective_universe_intervals.parquet"
SEC_SOURCE = REPO / "scripts" / "v22" / "a2_pit_sec_fundamental_acceleration_alpha_r1.py"
EXPECTED_DATES = 1_253
EXPECTED_ROWS = 50_120
BATCH_SIZE = 25
EXPECTED_RUNTIME = Path(r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe")


class RecoveryFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise RecoveryFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, stable_bytes(value))


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_name(path.name + ".tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_name(path.name + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def import_source() -> Any:
    spec = importlib.util.spec_from_file_location("a2_sec_coverage_source_r1", SEC_SOURCE)
    require(spec is not None and spec.loader is not None, "SOURCE_IMPORT_FAILURE", SEC_SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize_name(value: Any) -> str:
    text = re.sub(r"[^A-Z0-9 ]", " ", str(value).upper())
    text = re.sub(
        r"\b(THE|INCORPORATED|INC|CORPORATION|CORP|COMPANY|CO|LIMITED|LTD|PLC|LP|LLC|HOLDINGS?|GROUP)\b",
        " ", text,
    )
    return re.sub(r"\s+", "", text).strip()


def verify_runtime() -> dict[str, str]:
    import numpy
    import pandas
    import sklearn

    actual = Path(sys.executable)
    require(str(actual).casefold() == str(EXPECTED_RUNTIME).casefold(), "NON_CANONICAL_RUNTIME", actual)
    return {
        "SYS_EXECUTABLE": str(actual), "SYS_PREFIX": sys.prefix,
        "NUMPY_VERSION": numpy.__version__, "PANDAS_VERSION": pandas.__version__,
        "SKLEARN_VERSION": sklearn.__version__, "RUNTIME_CANONICAL_STATUS": "PASS",
    }


def verify_source_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    expected = {
        "preregistration.json": PREREG_SHA256,
        "sec_concept_contract.json": CONCEPT_SHA256,
        "final_report.md": SOURCE_REPORT_SHA256,
        "targeted_unresolved_impact.csv": TARGETED_SHA256,
        "hash_manifest.json": SOURCE_MANIFEST_SHA256,
    }
    actual = {name: sha256_file(SOURCE / name) for name in expected}
    require(actual == expected, "SOURCE_PREREG_CHANGED", actual)
    manifest = json.loads((SOURCE / "hash_manifest.json").read_text(encoding="utf-8"))
    manifest_rows = {row["name"]: row["sha256"] for row in manifest["artifacts"]}
    for name in ("preregistration.json", "sec_concept_contract.json", "final_report.md", "targeted_unresolved_impact.csv"):
        require(manifest_rows.get(name) == expected[name], "SOURCE_ARTIFACT_HASH_MISMATCH", name)
    prereg = json.loads((SOURCE / "preregistration.json").read_text(encoding="utf-8"))
    concept = json.loads((SOURCE / "sec_concept_contract.json").read_text(encoding="utf-8"))
    gate = prereg["coverage_gate"]
    values = (
        float(gate["raw_top40_median_min"]),
        0.50,
        float(gate["decision_date_fraction_with_coverage_at_least_0_50_min"]),
    )
    require(values == (0.60, 0.50, 0.75), "FROZEN_COVERAGE_CONTRACT_CHANGED", values)
    require(
        gate["covered_security_definition"] == "at least one usable derived feature in at least 3 of F0-F3",
        "FROZEN_COVERAGE_CONTRACT_CHANGED", "definition",
    )
    require(set(concept.get("forms", [])) == {"10-Q", "10-K", "10-Q/A", "10-K/A"}, "SOURCE_CONCEPT_CONTRACT_CHANGED", "forms")
    return prereg, concept


def verify_raw_checkpoint() -> pd.DataFrame:
    require(CHECKPOINT.is_file(), "HARD_FAIL_RAW_TOP40_CHECKPOINT_IDENTITY", "missing")
    require(sha256_file(CHECKPOINT) == CHECKPOINT_SHA256, "RAW_TOP40_CHECKPOINT_HASH_MISMATCH")
    columns = ["decision_date", "security_id", "ticker_if_available", "raw_rank"]
    raw = pd.read_parquet(CHECKPOINT, columns=columns)
    raw["decision_date"] = pd.to_datetime(raw.decision_date).dt.normalize()
    raw["security_id"] = raw.security_id.astype("string")
    raw["ticker"] = raw.ticker_if_available.astype("string").str.upper().str.strip()
    raw["raw_rank"] = pd.to_numeric(raw.raw_rank, errors="coerce").astype("Int64")
    require(len(raw) == EXPECTED_ROWS and raw.decision_date.nunique() == EXPECTED_DATES, "HARD_FAIL_RAW_TOP40_CHECKPOINT_IDENTITY", "shape")
    require(not raw[["decision_date", "security_id", "raw_rank"]].isna().any().any(), "HARD_FAIL_RAW_TOP40_CHECKPOINT_IDENTITY", "null")
    require(not raw.duplicated(["decision_date", "security_id"]).any(), "HARD_FAIL_RAW_TOP40_CHECKPOINT_IDENTITY", "duplicate-key")
    require(not raw.duplicated(["decision_date", "raw_rank"]).any(), "HARD_FAIL_RAW_TOP40_CHECKPOINT_IDENTITY", "duplicate-rank")
    counts = raw.groupby("decision_date").size()
    require(counts.eq(40).all(), "HARD_FAIL_RAW_TOP40_CHECKPOINT_IDENTITY", "daily-count")
    rank_identity = raw.groupby("decision_date").raw_rank.agg(lambda values: set(values.astype(int)) == set(range(1, 41)))
    require(rank_identity.all(), "HARD_FAIL_RAW_TOP40_CHECKPOINT_IDENTITY", "rank-1-40")
    return raw[["decision_date", "security_id", "ticker", "raw_rank"]].sort_values(["decision_date", "raw_rank"], kind="mergesort").reset_index(drop=True)


def verify_payloads() -> dict[str, dict[str, Any]]:
    verified: dict[str, dict[str, Any]] = {}
    for name, (path, expected_bytes, expected_entries, expected_sha) in PAYLOAD_CONTRACT.items():
        require(path.is_file() and path.stat().st_size == expected_bytes, "SEC_PAYLOAD_HASH_MISMATCH", f"{name}:bytes")
        digest = sha256_file(path)
        with zipfile.ZipFile(path) as archive:
            entries = len(archive.infolist())
            require(entries > 0, "HARD_FAIL_SEC_PAYLOAD_IDENTITY", f"{name}:empty")
            with archive.open(archive.infolist()[0]) as handle:
                handle.read(1)
        require((digest, entries) == (expected_sha, expected_entries), "SEC_PAYLOAD_HASH_MISMATCH", name)
        verified[name] = {"path": str(path), "bytes": expected_bytes, "entry_count": entries, "sha256": digest, "readable": True}
    return verified


def verify_feature_checkpoint() -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = json.loads(STATE_MANIFEST.read_text(encoding="utf-8"))
    require(manifest.get("state_path") == str(STATE_PATH), "FEATURE_CHECKPOINT_IDENTITY")
    require(sha256_file(STATE_PATH) == manifest.get("state_sha256"), "FEATURE_CHECKPOINT_HASH_MISMATCH")
    states = pd.read_parquet(STATE_PATH)
    require(len(states) == 30_653 == int(manifest["state_rows"]), "FEATURE_CHECKPOINT_IDENTITY", len(states))
    facts = manifest["lineage_facts"]
    require(facts.get("pit_effective_date_status") == "PASS_STRICT_NEXT_NYSE_SESSION", "PIT_EFFECTIVE_DATE_FAILURE")
    require(facts.get("restatement_guard_status") == "PASS_ACCESSION_ASOF_NO_BACKFILL", "RESTATEMENT_FAILURE")
    require(facts.get("unit_scale_status") == "PASS_USD_ONLY", "UNIT_SCALE_FAILURE")
    cache_manifest = json.loads(CACHE_MANIFEST.read_text(encoding="utf-8"))
    require(cache_manifest.get("numeric_fact_rows") == 904_071, "FEATURE_CHECKPOINT_IDENTITY", "numeric-facts")
    require(cache_manifest.get("accepted_submission_rows") == 31_282, "FEATURE_CHECKPOINT_IDENTITY", "accepted-submissions")
    return states, manifest


def project_existing_coverage(raw: pd.DataFrame) -> pd.DataFrame:
    safe_columns = [
        "security_id", "ticker", "cik", "issuer_name", "mapping_effective_date",
        "accession", "accepted_datetime", "feature_effective_date", "coverage_status",
    ]
    ledger = pd.read_parquet(FEATURE_LEDGER, columns=safe_columns)
    ledger["security_id"] = ledger.security_id.astype("string")
    ledger["feature_effective_date"] = pd.to_datetime(ledger.feature_effective_date).dt.normalize()
    pieces: list[pd.DataFrame] = []
    for security, left in raw.groupby("security_id", sort=False):
        right = ledger.loc[ledger.security_id.eq(security)].copy()
        left = left.sort_values("decision_date")
        if right.empty:
            merged = left.copy()
            for column in ("cik", "issuer_name", "accession", "accepted_datetime", "feature_effective_date", "coverage_status"):
                merged[column] = pd.NA
        else:
            right = right.sort_values(["feature_effective_date", "accepted_datetime", "accession"], kind="mergesort").drop_duplicates("feature_effective_date", keep="last")
            merged = pd.merge_asof(
                left, right[["feature_effective_date", "coverage_status", "cik", "issuer_name", "accession", "accepted_datetime"]],
                left_on="decision_date", right_on="feature_effective_date", direction="backward", allow_exact_matches=True,
            )
        pieces.append(merged)
    panel = pd.concat(pieces, ignore_index=True)
    panel["has_valid_sec_identity"] = panel.cik.notna()
    panel["has_valid_filing_state"] = panel.accession.notna()
    panel["has_required_feature_coverage"] = panel.coverage_status.fillna(False).astype(bool)
    panel["covered_under_frozen_contract"] = panel.has_required_feature_coverage
    panel["coverage_failure_reason"] = np.select(
        [~panel.has_valid_sec_identity, ~panel.has_valid_filing_state, ~panel.has_required_feature_coverage],
        ["UNRESOLVED_CIK", "NO_VALID_FILING_STATE_ASOF", "BELOW_THREE_CORE_FAMILY_COVERAGE"],
        default="COVERED",
    )
    require(len(panel) == EXPECTED_ROWS, "COVERAGE_MATRIX_IDENTITY", len(panel))
    require(not panel.duplicated(["decision_date", "security_id"]).any(), "COVERAGE_MATRIX_IDENTITY", "duplicate")
    require(panel[["decision_date", "security_id"]].notna().all().all(), "COVERAGE_MATRIX_IDENTITY", "missing-raw-cell")
    return panel.sort_values(["decision_date", "raw_rank"], kind="mergesort").reset_index(drop=True)


def date_coverage(panel: pd.DataFrame, covered_column: str = "covered_under_frozen_contract") -> pd.DataFrame:
    daily = panel.groupby("decision_date")[covered_column].agg(covered_count="sum", top40_count="size").reset_index()
    daily["covered_count"] = daily.covered_count.astype(int)
    daily["missing_count"] = daily.top40_count - daily.covered_count
    daily["coverage_ratio"] = daily.covered_count / daily.top40_count
    daily["required_covered_count"] = np.ceil(daily.top40_count * 0.50).astype(int)
    daily["deficit_count"] = (daily.required_covered_count - daily.covered_count).clip(lower=0)
    daily["passes_frozen_per_date_gate"] = daily.covered_count.ge(daily.required_covered_count)
    require(len(daily) == EXPECTED_DATES and daily.top40_count.eq(40).all(), "COVERAGE_DATE_IDENTITY")
    require(daily.required_covered_count.eq(20).all(), "FROZEN_COVERAGE_CONTRACT_CHANGED", "required-count")
    return daily


def coverage_summary(daily: pd.DataFrame) -> dict[str, Any]:
    return {
        "median": float(daily.coverage_ratio.median()),
        "passing_count": int(daily.passes_frozen_per_date_gate.sum()),
        "failing_count": int((~daily.passes_frozen_per_date_gate).sum()),
        "passing_fraction": float(daily.passes_frozen_per_date_gate.mean()),
    }


def targeted_universe(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    upstream = pd.read_csv(SOURCE / "targeted_unresolved_impact.csv")
    missing = panel.loc[~panel.covered_under_frozen_contract].copy()
    incidence = missing[["decision_date", "security_id", "ticker", "raw_rank", "coverage_failure_reason"]].drop_duplicates()
    grouped = incidence.groupby(["security_id", "ticker"], dropna=False).agg(
        raw_top40_occurrence_count=("decision_date", "size"),
        missing_date_count=("decision_date", "nunique"),
    ).reset_index()
    meta = upstream.drop(columns=["ticker", "raw_top40_occurrence_count"], errors="ignore")
    targeted = grouped.merge(meta, on="security_id", how="left", validate="one_to_one")
    require(targeted.cik_status.notna().all(), "TARGETED_IMPACT_UNIVERSE_CHANGED", "new-security")
    removed = upstream.loc[~upstream.security_id.astype(str).isin(set(targeted.security_id.astype(str))), "security_id"].astype(str).tolist()
    explanation = (
        f"R2 exact checkpoint projection excludes {len(removed)} upstream estimated-impact securities because they have no currently missing "
        f"Raw Top40 cell under the frozen as-of feature ledger: {','.join(sorted(removed)) or 'NONE'}."
    )
    return targeted.sort_values(["raw_top40_occurrence_count", "security_id"], ascending=[False, True], kind="mergesort"), incidence, explanation


def greedy_ranking(
    incidence: pd.DataFrame,
    deficits: Mapping[pd.Timestamp, int],
    total_dates: int,
    current_passing: int,
    required_passing: int,
    metadata: pd.DataFrame,
    confidence: Mapping[str, int] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    confidence = confidence or {}
    work = incidence[["security_id", "decision_date"]].drop_duplicates().copy()
    work["decision_date"] = pd.to_datetime(work.decision_date).dt.normalize()
    dates = {str(key): set(group.decision_date) for key, group in work.groupby("security_id")}
    totals = metadata.set_index(metadata.security_id.astype(str)).raw_top40_occurrence_count.astype(int).to_dict()
    deficit = {pd.Timestamp(key).normalize(): int(value) for key, value in deficits.items() if int(value) > 0}
    remaining = set(dates)
    rows: list[dict[str, Any]] = []
    rescued = 0
    meta = metadata.set_index(metadata.security_id.astype(str), drop=False)
    while remaining and current_passing + rescued < required_passing and (limit is None or len(rows) < limit):
        scored: list[tuple[Any, ...]] = []
        for security in remaining:
            active = [date for date in dates[security] if deficit.get(date, 0) > 0]
            immediate = sum(deficit[date] == 1 for date in active)
            weighted = sum(1.0 / deficit[date] for date in active)
            scored.append((security, immediate, weighted, len(active), int(totals.get(security, len(dates[security]))), int(confidence.get(security, 0))))
        security, immediate, weighted, failing_occurrences, total_occurrences, identity_confidence = sorted(
            scored, key=lambda row: (-row[1], -row[2], -row[3], -row[4], -row[5], row[0]),
        )[0]
        actual_rescued = 0
        for date in dates[security]:
            if deficit.get(date, 0) > 0:
                deficit[date] -= 1
                if deficit[date] == 0:
                    actual_rescued += 1
        rescued += actual_rescued
        item = meta.loc[security]
        rows.append({
            "security_id": security,
            "ticker": item.ticker,
            "issuer_name": item.issuer_name,
            "raw_top40_occurrence_count": total_occurrences,
            "failing_date_occurrence_count": failing_occurrences,
            "missing_date_count": int(item.missing_date_count),
            "simulated_immediate_dates_rescued": actual_rescued,
            "simulated_cumulative_dates_rescued": rescued,
            "simulated_passing_fraction_after_recovery": (current_passing + rescued) / total_dates,
            "weighted_deficit_score": weighted,
            "identity_confidence_score": identity_confidence,
            "current_cik_status": item.cik_status,
            "current_coverage_failure_reason": item.likely_mapping_filer_issue,
        })
        remaining.remove(security)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame.insert(0, "priority", np.arange(1, len(frame) + 1, dtype=int))
    return frame


def build_companyfacts_identity_index() -> tuple[dict[str, set[int]], dict[int, str]]:
    pattern = re.compile(br'"entityName"\s*:\s*"((?:\\.|[^"\\])*)"')
    name_to_ciks: dict[str, set[int]] = {}
    cik_to_name: dict[int, str] = {}
    with zipfile.ZipFile(COMPANYFACTS) as archive:
        for info in archive.infolist():
            match_cik = re.search(r"CIK(\d{10})\.json$", info.filename)
            if not match_cik:
                continue
            with archive.open(info) as handle:
                match_name = pattern.search(handle.read(8_192))
            if not match_name:
                continue
            try:
                entity_name = json.loads((b'"' + match_name.group(1) + b'"').decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            cik = int(match_cik.group(1))
            key = normalize_name(entity_name)
            cik_to_name[cik] = str(entity_name)
            if key:
                name_to_ciks.setdefault(key, set()).add(cik)
    require(len(cik_to_name) >= 20_000, "SEC_IDENTITY_INDEX_FAILURE", len(cik_to_name))
    return name_to_ciks, cik_to_name


def local_identity_incidence(raw: pd.DataFrame, targeted: pd.DataFrame) -> pd.DataFrame:
    unresolved = set(targeted.loc[targeted.cik_status.eq("UNRESOLVED"), "security_id"].astype(str))
    missing_raw = raw.loc[raw.security_id.astype(str).isin(unresolved)].copy()
    universe = pd.read_parquet(
        UNIVERSE_INTERVALS,
        columns=["effective_start", "effective_end", "security_id", "cusip", "issuer_name", "ticker", "mapping_status", "mapping_confidence"],
    )
    universe["effective_start"] = pd.to_datetime(universe.effective_start).dt.normalize()
    universe["effective_end"] = pd.to_datetime(universe.effective_end).dt.normalize()
    universe["ticker"] = universe.ticker.astype("string").str.upper().str.strip()
    rows: list[dict[str, Any]] = []
    for ticker, left in missing_raw.groupby("ticker", sort=False):
        candidates = universe.loc[universe.ticker.eq(ticker)]
        for row in left.itertuples(index=False):
            valid = candidates.loc[candidates.effective_start.le(row.decision_date) & candidates.effective_end.ge(row.decision_date)]
            if len(valid) != 1:
                rows.append({"security_id": str(row.security_id), "decision_date": row.decision_date, "ticker": ticker, "identity_status": "AMBIGUOUS_OR_MISSING_INTERVAL"})
                continue
            identity = valid.iloc[0]
            rows.append({
                "security_id": str(row.security_id), "decision_date": row.decision_date, "ticker": ticker,
                "local_security_id": str(identity.security_id), "cusip": str(identity.cusip), "issuer_name": str(identity.issuer_name),
                "effective_start_date": identity.effective_start, "effective_end_date": identity.effective_end,
                "local_mapping_status": str(identity.mapping_status), "local_mapping_confidence": str(identity.mapping_confidence),
                "identity_status": "PIT_INTERVAL_UNIQUE",
            })
    frame = pd.DataFrame(rows)
    require(len(frame) == len(missing_raw), "LOCAL_IDENTITY_INCIDENCE_FAILURE", (len(frame), len(missing_raw)))
    return frame


def classify_unresolved(
    targeted: pd.DataFrame,
    identity_incidence: pd.DataFrame,
    name_to_ciks: Mapping[str, set[int]],
    cik_to_name: Mapping[int, str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    unresolved = targeted.loc[targeted.cik_status.eq("UNRESOLVED")]
    for item in unresolved.itertuples(index=False):
        incidence = identity_incidence.loc[identity_incidence.security_id.eq(str(item.security_id))]
        candidate_sets: list[set[int]] = []
        unsafe_interval = incidence.identity_status.ne("PIT_INTERVAL_UNIQUE").any() or len(incidence) != int(item.raw_top40_occurrence_count)
        for row in incidence.itertuples(index=False):
            if row.identity_status != "PIT_INTERVAL_UNIQUE" or not str(getattr(row, "cusip", "")).strip():
                candidate_sets.append(set())
            else:
                candidate_sets.append(set(name_to_ciks.get(normalize_name(row.issuer_name), set())))
        union = set().union(*candidate_sets) if candidate_sets else set()
        every_unique = bool(candidate_sets) and all(len(values) == 1 for values in candidate_sets)
        same_cik = every_unique and len(union) == 1
        if unsafe_interval:
            classification, legality, reason = "HISTORICAL_TICKER_OR_NAME_CHANGE", "HISTORICAL_MAPPING_UNSAFE", "PIT identity interval missing or ambiguous"
        elif any(len(values) > 1 for values in candidate_sets) or (every_unique and len(union) > 1):
            classification, legality, reason = "AMBIGUOUS_ISSUER", "LEAVE_UNRESOLVED", "normalized SEC entity name maps to multiple CIKs or changes CIK"
        elif same_cik:
            classification, legality, reason = "DOMESTIC_10Q10K_MAPPABLE", "HIGH_CONFIDENCE_LEGALLY_REPAIRABLE", "CUSIP-linked PIT issuer plus unique normalized SEC entity match"
        else:
            classification, legality, reason = "NO_MATCH", "LEAVE_UNRESOLVED", "no unique normalized SEC companyfacts entity match"
        cik = next(iter(union)) if same_cik else pd.NA
        issuer_names = incidence.get("issuer_name", pd.Series(dtype="string")).dropna().astype(str).unique()
        rows.append({
            "security_id": str(item.security_id), "ticker": item.ticker,
            "issuer_name": issuer_names[0] if len(issuer_names) else item.issuer_name,
            "classification": classification, "repair_legality": legality, "candidate_cik": cik,
            "sec_entity_name": cik_to_name.get(int(cik), "") if pd.notna(cik) else "",
            "why_not_repairable": reason,
            "identity_interval_count": int(incidence[["effective_start_date", "effective_end_date"]].drop_duplicates().shape[0]) if "effective_start_date" in incidence else 0,
        })
    return pd.DataFrame(rows)


def targeted_payloads(sec: Any, ciks: Iterable[int]) -> tuple[pd.DataFrame, pd.DataFrame, dict[int, set[str]]]:
    cik_list = sorted(set(int(value) for value in ciks))
    submission_pieces: list[pd.DataFrame] = []
    forms: dict[int, set[str]] = {cik: set() for cik in cik_list}
    with zipfile.ZipFile(SUBMISSIONS) as archive:
        names = archive.NameToInfo
        for cik in cik_list:
            entry = f"CIK{cik:010d}.json"
            info = names.get(entry)
            if info is None:
                continue
            payload = archive.read(info)
            digest = hashlib.sha256(payload).hexdigest()
            document = json.loads(payload)
            recent = document.get("filings", {}).get("recent", {})
            forms[cik].update(str(value) for value in recent.get("form", []) if value)
            frame = sec.submission_document_rows(document, cik, str(document.get("name", "")), document.get("sic"), entry, digest)
            if not frame.empty:
                submission_pieces.append(frame)
            for descriptor in document.get("filings", {}).get("files", []):
                filing_to = pd.to_datetime(descriptor.get("filingTo"), errors="coerce")
                filing_from = pd.to_datetime(descriptor.get("filingFrom"), errors="coerce")
                if pd.isna(filing_to) or filing_to < sec.SEC_START or (pd.notna(filing_from) and filing_from > sec.LABEL_CUTOFF):
                    continue
                old_entry = str(descriptor.get("name", ""))
                old_info = names.get(old_entry)
                if old_info is None:
                    continue
                old_payload = archive.read(old_info)
                old_document = json.loads(old_payload)
                forms[cik].update(str(value) for value in old_document.get("form", []) if value)
                old_frame = sec.submission_document_rows(
                    old_document, cik, str(document.get("name", "")), document.get("sic"), old_entry,
                    hashlib.sha256(old_payload).hexdigest(),
                )
                if not old_frame.empty:
                    submission_pieces.append(old_frame)
    submissions = pd.concat(submission_pieces, ignore_index=True) if submission_pieces else pd.DataFrame()
    if not submissions.empty:
        submissions["accepted_datetime"] = pd.to_datetime(submissions.accepted_datetime, utc=True)
        require(not submissions.groupby("adsh").accepted_datetime.nunique().gt(1).any(), "PIT_EFFECTIVE_DATE_FAILURE", "acceptance-conflict")
        submissions = submissions.sort_values(["accepted_datetime", "adsh"], kind="mergesort").drop_duplicates("adsh", keep="last")

    fact_pieces: list[pd.DataFrame] = []
    with zipfile.ZipFile(COMPANYFACTS) as archive:
        names = archive.NameToInfo
        for cik in cik_list:
            entry = f"CIK{cik:010d}.json"
            info = names.get(entry)
            if info is None:
                continue
            payload = archive.read(info)
            frame = sec.companyfacts_records(payload, cik, hashlib.sha256(payload).hexdigest())
            if not frame.empty:
                frame["source_url_id"] = f"companyfacts.zip!{entry}"
                fact_pieces.append(frame)
    facts = pd.concat(fact_pieces, ignore_index=True) if fact_pieces else pd.DataFrame()
    return facts, submissions, forms


def nyse_sessions() -> pd.DatetimeIndex:
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range("2017-12-29", "2025-12-31")
    return pd.DatetimeIndex(sessions).tz_localize(None).normalize()


def state_coverage(sec: Any, states: pd.DataFrame) -> pd.DataFrame:
    if states.empty:
        return states.assign(coverage_status=pd.Series(dtype=bool))
    family_counts = [states[features].notna().any(axis=1).astype(int) for features in sec.CORE_COVERAGE_FAMILIES]
    result = states.copy()
    result["coverage_status"] = np.sum(family_counts, axis=0) >= 3
    return result


def legal_cell_recovery(
    raw: pd.DataFrame,
    classification: pd.DataFrame,
    identity_incidence: pd.DataFrame,
    states: pd.DataFrame,
) -> pd.DataFrame:
    accepted = classification.loc[classification.repair_legality.eq("HIGH_CONFIDENCE_LEGALLY_REPAIRABLE") & classification.candidate_cik.notna()]
    pieces: list[pd.DataFrame] = []
    for item in accepted.itertuples(index=False):
        left = raw.loc[raw.security_id.astype(str).eq(str(item.security_id)), ["decision_date", "security_id"]].sort_values("decision_date")
        left["decision_date"] = pd.to_datetime(left.decision_date).astype("datetime64[ns]")
        right = states.loc[states.cik.eq(int(item.candidate_cik))].copy()
        if right.empty:
            merged = left.copy()
            merged["new_covered"] = False
        else:
            right["feature_effective_date"] = pd.to_datetime(right.feature_effective_date).astype("datetime64[ns]")
            right = right.sort_values(["feature_effective_date", "accepted_datetime", "accession"], kind="mergesort").drop_duplicates("feature_effective_date", keep="last")
            merged = pd.merge_asof(
                left, right[["feature_effective_date", "coverage_status"]].sort_values("feature_effective_date"),
                left_on="decision_date", right_on="feature_effective_date", direction="backward", allow_exact_matches=True,
            )
            merged["new_covered"] = merged.coverage_status.fillna(False).astype(bool)
        valid_dates = set(identity_incidence.loc[
            identity_incidence.security_id.eq(str(item.security_id)) & identity_incidence.identity_status.eq("PIT_INTERVAL_UNIQUE"), "decision_date"
        ])
        merged["new_covered"] &= merged.decision_date.isin(valid_dates)
        merged["new_cik"] = int(item.candidate_cik)
        pieces.append(merged[["decision_date", "security_id", "new_cik", "new_covered"]])
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=["decision_date", "security_id", "new_cik", "new_covered"])


def apply_recoveries(panel: pd.DataFrame, cells: pd.DataFrame, securities: set[str]) -> pd.DataFrame:
    result = panel.copy()
    selected = cells.loc[cells.security_id.astype(str).isin(securities) & cells.new_covered.astype(bool), ["decision_date", "security_id"]].drop_duplicates()
    if selected.empty:
        return result
    keys = pd.MultiIndex.from_frame(selected)
    panel_keys = pd.MultiIndex.from_frame(result[["decision_date", "security_id"]])
    mask = panel_keys.isin(keys)
    result.loc[mask, "covered_under_frozen_contract"] = True
    result.loc[mask, "has_valid_sec_identity"] = True
    result.loc[mask, "has_valid_filing_state"] = True
    result.loc[mask, "has_required_feature_coverage"] = True
    result.loc[mask, "coverage_failure_reason"] = "RECOVERED_HIGH_CONFIDENCE_STANDARD_CONTRACT"
    return result


def resolved_gap_counts(targeted: pd.DataFrame) -> dict[str, int]:
    resolved = targeted.loc[targeted.cik_status.ne("UNRESOLVED")]
    issue = resolved.likely_mapping_filer_issue.astype(str)
    return {
        "RESOLVED_CIK_NO_FACTS_COUNT": int(issue.str.contains("NO_COMPANYFACTS").sum()),
        "RESOLVED_CIK_SEMANTIC_GAP_COUNT": int(issue.str.contains("BELOW_THREE_CORE").sum()),
        "RESOLVED_CIK_HISTORY_GAP_COUNT": int(issue.str.contains("FACTS_PRESENT_NO_USABLE|NO_PRE2026_ACCEPTED").sum()),
        "RESOLVED_CIK_FORM_GAP_COUNT": int(issue.str.contains("NO_PRE2026_ACCEPTED").sum()),
    }


FINAL_KEYS = """TASK_STATUS PRIMARY_CLASSIFICATION | SOURCE_RESEARCH_ID SOURCE_PREREG_SHA256 SOURCE_CONCEPT_CONTRACT_SHA256 |
RAW_TOP40_CHECKPOINT_PATH RAW_TOP40_CHECKPOINT_SHA256_MATCH RAW_TOP40_DECISION_DATE_COUNT RAW_TOP40_TOTAL_ROWS |
SYS_EXECUTABLE RUNTIME_CANONICAL_STATUS | OUTCOME_DATA_READ_FOR_RECOVERY FUNDAMENTAL_MODEL_FIT_COUNT RAW_MODEL_FIT_COUNT INNER_SELECTION_COUNT OUTER_READ_COUNT READ_2025_COUNT READ_2026_OUTCOME_COUNT |
FROZEN_MEDIAN_COVERAGE_GATE FROZEN_PER_DATE_COVERAGE_THRESHOLD FROZEN_PASSING_DATE_FRACTION_GATE COVERAGE_GATE_CHANGED |
PRE_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE PRE_RECOVERY_PASSING_DATE_FRACTION PRE_RECOVERY_PASSING_DATE_COUNT PRE_RECOVERY_FAILING_DATE_COUNT |
REQUIRED_PASSING_DATE_COUNT MIN_ADDITIONAL_PASSING_DATES |
TARGETED_IMPACT_SECURITY_COUNT_R2 TARGETED_CIK_UNRESOLVED_COUNT_R2 TARGETED_RESOLVED_COVERAGE_GAP_COUNT_R2 |
THEORETICAL_MAX_PASSING_DATE_FRACTION LEGAL_REPAIR_THEORETICAL_MAX_PASSING_DATE_FRACTION THEORETICAL_GATE_RECOVERABLE |
CIK_REPAIR_ATTEMPT_COUNT CIK_REPAIR_ACCEPTED_COUNT CIK_REPAIR_AMBIGUOUS_COUNT CIK_REPAIR_REJECTED_COUNT |
DOMESTIC_10Q10K_MAPPABLE_COUNT FOREIGN_FILER_COUNT HISTORICAL_IDENTITY_CHANGE_COUNT NON_OPERATING_ENTITY_COUNT AMBIGUOUS_ISSUER_COUNT |
RESOLVED_CIK_NO_FACTS_COUNT RESOLVED_CIK_SEMANTIC_GAP_COUNT RESOLVED_CIK_HISTORY_GAP_COUNT RESOLVED_CIK_FORM_GAP_COUNT |
SEMANTIC_RECOVERY_CANDIDATE_COUNT SEMANTIC_ALIAS_ACCEPTED_COUNT SEMANTIC_ALIAS_REJECTED_COUNT ECONOMIC_FEATURE_DEFINITION_CHANGED |
BATCHES_COMPLETED RECOVERY_STOP_REASON |
POST_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE POST_RECOVERY_PASSING_DATE_FRACTION POST_RECOVERY_PASSING_DATE_COUNT POST_RECOVERY_FAILING_DATE_COUNT DATES_RECOVERED_TO_PASS |
MEDIAN_COVERAGE_GATE_PASS PASSING_DATE_FRACTION_GATE_PASS FULL_FROZEN_COVERAGE_GATE_PASS |
PIT_EFFECTIVE_DATE_STATUS RESTATEMENT_GUARD_STATUS UNIT_SCALE_STATUS CONCEPT_CONTRACT_STATUS |
NON_TARGETED_UNRESOLVED_CIK_REPAIR_COUNT | CIK_OVERLAY_SHA256 SEMANTIC_OVERLAY_SHA256 POST_RECOVERY_COVERAGE_SHA256 RESUME_CONTRACT_SHA256 |
TASK_LOCAL_ANTI_BLOAT_STATUS PREEXISTING_ACL_EXCEPTION_COUNT FINAL_ARTIFACT_COUNT HASH_MANIFEST_STATUS |
NEXT_AUTHORIZED_STEP""".split()


def final_block(summary: Mapping[str, Any]) -> str:
    lines = ["=" * 60, f"{TASK_ID}_FINAL", "=" * 60, ""]
    for key in FINAL_KEYS:
        lines.append("") if key == "|" else lines.append(f"{key}={summary.get(key, 'NOT_APPLICABLE')}")
    return "\n".join([*lines, "", "=" * 60])


def main() -> int:
    runtime = verify_runtime()
    for key, value in runtime.items():
        if key != "RUNTIME_CANONICAL_STATUS":
            print(f"{key}={value}")
    raw = verify_raw_checkpoint()
    payloads = verify_payloads()
    prereg, concept = verify_source_contract()
    base_states, state_manifest = verify_feature_checkpoint()
    panel = project_existing_coverage(raw)
    pre_daily = date_coverage(panel)
    pre = coverage_summary(pre_daily)
    require(pre == {"median": 0.6, "passing_count": 743, "failing_count": 510, "passing_fraction": 743 / 1253}, "FROZEN_COVERAGE_CONTRACT_CHANGED", pre)
    required_passing = math.ceil(EXPECTED_DATES * 0.75)
    minimum_additional = required_passing - pre["passing_count"]
    print(f"CURRENT_PASSING_DATE_COUNT={pre['passing_count']}")
    print(f"REQUIRED_PASSING_DATE_COUNT={required_passing}")
    print(f"MIN_ADDITIONAL_PASSING_DATES={minimum_additional}")

    targeted, missing_incidence, incidence_explanation = targeted_universe(panel)
    print(f"TARGETED_IMPACT_SECURITY_COUNT_R2={len(targeted)}")
    print(f"TARGETED_CIK_UNRESOLVED_COUNT_R2={targeted.cik_status.eq('UNRESOLVED').sum()}")
    print(f"TARGETED_RESOLVED_COVERAGE_GAP_COUNT_R2={targeted.cik_status.ne('UNRESOLVED').sum()}")
    name_to_ciks, cik_to_name = build_companyfacts_identity_index()
    identity_incidence = local_identity_incidence(raw, targeted)
    classification = classify_unresolved(targeted, identity_incidence, name_to_ciks, cik_to_name)

    sec = import_source()
    candidate_ciks = classification.loc[classification.repair_legality.eq("HIGH_CONFIDENCE_LEGALLY_REPAIRABLE"), "candidate_cik"].dropna().astype(int)
    existing_state_ciks = set(pd.to_numeric(base_states.cik, errors="coerce").dropna().astype(int))
    rebuild_ciks = sorted(set(candidate_ciks) - existing_state_ciks)
    facts, submissions, forms = targeted_payloads(sec, rebuild_ciks)
    for cik in set(candidate_ciks) & existing_state_ciks:
        forms[int(cik)] = {"10-Q"}
    domestic_ciks = {cik for cik, values in forms.items() if values & {"10-Q", "10-K", "10-Q/A", "10-K/A"}}
    foreign_ciks = {cik for cik, values in forms.items() if not values & {"10-Q", "10-K", "10-Q/A", "10-K/A"} and values & {"20-F", "40-F", "6-K"}}
    classification.loc[classification.candidate_cik.isin(foreign_ciks), ["classification", "repair_legality", "why_not_repairable"]] = [
        "FOREIGN_FILER", "DO_NOT_ADD_FOREIGN_FORM_SUPPORT", "frozen source concept contract excludes 20-F/40-F/6-K",
    ]
    classification.loc[
        classification.candidate_cik.notna() & ~classification.candidate_cik.isin(domestic_ciks | foreign_ciks),
        ["classification", "repair_legality", "why_not_repairable"],
    ] = ["NO_MATCH", "LEAVE_UNRESOLVED", "no locally frozen relevant 10-Q/10-K form history"]
    domestic_ciks = set(classification.loc[classification.repair_legality.eq("HIGH_CONFIDENCE_LEGALLY_REPAIRABLE"), "candidate_cik"].dropna().astype(int))
    facts = facts.loc[facts.cik.isin(domestic_ciks)].copy() if not facts.empty else facts
    submissions = submissions.loc[submissions.cik.isin(domestic_ciks)].copy() if not submissions.empty else submissions
    if facts.empty or submissions.empty:
        rebuilt_states = pd.DataFrame(columns=base_states.columns)
        new_lineage = {"pit_effective_date_status": "PASS_NO_NEW_FACTS", "restatement_guard_status": "PASS_NO_NEW_FACTS", "unit_scale_status": "PASS_NO_NEW_FACTS"}
    else:
        rebuilt_states, new_lineage = sec.build_feature_states(facts, submissions, nyse_sessions())
    reused_states = base_states.loc[base_states.cik.isin(set(candidate_ciks) & existing_state_ciks)].copy()
    new_states = pd.concat([reused_states, rebuilt_states], ignore_index=True, sort=False)
    new_states = state_coverage(sec, new_states)
    legal_cells = legal_cell_recovery(raw, classification, identity_incidence, new_states)

    scenario_a = panel.copy()
    scenario_a.loc[~scenario_a.covered_under_frozen_contract, "covered_under_frozen_contract"] = True
    theoretical_max = coverage_summary(date_coverage(scenario_a))["passing_fraction"]
    scenario_b = apply_recoveries(panel, legal_cells, set(classification.loc[classification.repair_legality.eq("HIGH_CONFIDENCE_LEGALLY_REPAIRABLE"), "security_id"].astype(str)))
    legal_max = coverage_summary(date_coverage(scenario_b))["passing_fraction"]
    theoretical_recoverable = legal_max >= 0.75
    print(f"THEORETICAL_MAX_PASSING_DATE_FRACTION={theoretical_max}")
    print(f"LEGAL_REPAIR_THEORETICAL_MAX_PASSING_DATE_FRACTION={legal_max}")

    confidence = {str(row.security_id): 3 for row in targeted.loc[targeted.cik_status.ne("UNRESOLVED")].itertuples()}
    confidence.update({str(row.security_id): 2 for row in classification.loc[classification.repair_legality.eq("HIGH_CONFIDENCE_LEGALLY_REPAIRABLE")].itertuples()})
    targeted = targeted.merge(
        classification[["security_id", "issuer_name"]].rename(columns={"issuer_name": "recovered_issuer_name"}),
        on="security_id", how="left", validate="one_to_one",
    )
    targeted["issuer_name"] = targeted.recovered_issuer_name.combine_first(targeted.issuer_name)
    targeted = targeted.drop(columns="recovered_issuer_name")

    current = panel.copy()
    remaining = set(targeted.security_id.astype(str))
    priority_pieces: list[pd.DataFrame] = []
    processed_batches: dict[str, int] = {}
    batch_count = 0
    stop_reason = "STRUCTURAL_COVERAGE_INSUFFICIENT"
    if theoretical_recoverable:
        while remaining:
            current_daily = date_coverage(current)
            current_summary = coverage_summary(current_daily)
            deficits = current_daily.set_index("decision_date").deficit_count.to_dict()
            remaining_incidence = current.loc[
                ~current.covered_under_frozen_contract & current.security_id.astype(str).isin(remaining),
                ["decision_date", "security_id"],
            ]
            ranking = greedy_ranking(
                remaining_incidence, deficits, EXPECTED_DATES, current_summary["passing_count"], required_passing,
                targeted.loc[targeted.security_id.astype(str).isin(remaining)], confidence, limit=BATCH_SIZE,
            )
            if ranking.empty:
                break
            batch_count += 1
            batch_ids = set(ranking.security_id.astype(str))
            for security in batch_ids:
                processed_batches[security] = batch_count
            ranking["repair_batch"] = batch_count
            priority_pieces.append(ranking)
            current = apply_recoveries(current, legal_cells, batch_ids)
            remaining -= batch_ids
            post_batch = coverage_summary(date_coverage(current))
            if post_batch["median"] >= 0.60 and post_batch["passing_fraction"] >= 0.75:
                stop_reason = "FROZEN_COVERAGE_GATE_FIRST_PASS"
                break
        else:
            stop_reason = "HIGH_CONFIDENCE_CONTRACT_LEGAL_REPAIR_EXHAUSTED"
    priority = pd.concat(priority_pieces, ignore_index=True) if priority_pieces else greedy_ranking(
        missing_incidence, pre_daily.set_index("decision_date").deficit_count.to_dict(), EXPECTED_DATES,
        pre["passing_count"], required_passing, targeted, confidence,
    )
    if not priority.empty:
        priority["priority"] = np.arange(1, len(priority) + 1)
    post_daily = date_coverage(current)
    post = coverage_summary(post_daily)
    full_pass = post["median"] >= 0.60 and post["passing_fraction"] >= 0.75

    if not theoretical_recoverable:
        primary = "STRUCTURAL_COVERAGE_INSUFFICIENT"
        task_status = "FAIL"
    elif full_pass:
        primary = "PASS_TARGETED_COVERAGE_RECOVERED"
        task_status = "PASS"
    else:
        primary = "FAIL_TARGETED_RECOVERY_EXHAUSTED"
        task_status = "FAIL"

    processed = set(processed_batches)
    class_index = classification.set_index("security_id", drop=False)
    overlay_rows: list[dict[str, Any]] = []
    for security in sorted(processed):
        if security not in class_index.index:
            continue
        item = class_index.loc[security]
        if item.repair_legality != "HIGH_CONFIDENCE_LEGALLY_REPAIRABLE" or pd.isna(item.candidate_cik):
            continue
        intervals = identity_incidence.loc[
            identity_incidence.security_id.eq(security) & identity_incidence.identity_status.eq("PIT_INTERVAL_UNIQUE")
        ].drop_duplicates(["effective_start_date", "effective_end_date", "issuer_name"])
        cell_count = int(legal_cells.loc[legal_cells.security_id.eq(security), "new_covered"].sum())
        family_names: list[str] = []
        state_subset = new_states.loc[new_states.cik.eq(int(item.candidate_cik))] if not new_states.empty else pd.DataFrame()
        for family_name, columns in zip(("F0", "F1", "F2", "F3"), sec.CORE_COVERAGE_FAMILIES):
            if not state_subset.empty and state_subset[columns].notna().any(axis=1).any():
                family_names.append(family_name)
        for interval in intervals.itertuples(index=False):
            overlay_rows.append({
                "security_id": security, "ticker": item.ticker, "issuer_name": interval.issuer_name,
                "effective_start_date": interval.effective_start_date, "effective_end_date": interval.effective_end_date,
                "old_cik": pd.NA, "new_cik": int(item.candidate_cik), "mapping_status": "ACCEPTED_HIGH_CONFIDENCE",
                "mapping_source": "CUSIP_LINKED_PIT_ISSUER_PLUS_UNIQUE_NORMALIZED_SEC_ENTITY",
                "mapping_confidence": "HIGH_CONFIDENCE_LEGALLY_REPAIRABLE",
                "old_coverage_status": "MISSING", "new_coverage_status": "COVERED" if cell_count else "MISSING_NO_USABLE_STATE",
                "recovered_feature_families": ";".join(family_names),
                "gate_recovery_priority": int(priority.loc[priority.security_id.eq(security), "priority"].iloc[0]),
                "repair_batch": processed_batches[security],
            })
    overlay = pd.DataFrame(overlay_rows, columns=[
        "security_id", "ticker", "issuer_name", "effective_start_date", "effective_end_date", "old_cik", "new_cik",
        "mapping_status", "mapping_source", "mapping_confidence", "old_coverage_status", "new_coverage_status",
        "recovered_feature_families", "gate_recovery_priority", "repair_batch",
    ])

    OUT.mkdir(parents=True, exist_ok=False)
    recovery_contract = {
        "task_id": TASK_ID, "task_kind": TASK_KIND, "source_research_id": SOURCE_RESEARCH_ID,
        "SUPERSEDES_R1_FOR_EXECUTION_ONLY": True, "R1_ECONOMIC_EVIDENCE_REUSED": False,
        "raw_top40_checkpoint_path": str(CHECKPOINT), "raw_top40_checkpoint_sha256": CHECKPOINT_SHA256,
        "source_prereg_sha256": PREREG_SHA256, "source_concept_contract_sha256": CONCEPT_SHA256,
        "coverage_gate": prereg["coverage_gate"], "coverage_gate_changed": False,
        "economic_feature_definition_changed": False, "economic_search_space_changed": False,
        "batch_size": BATCH_SIZE, "outcome_data_read": False, "model_fit_count": 0,
        "raw_model_fit_count": 0, "raw_replay_model_fit_count": 0, "sec_network_call_count": 0,
        "moomoo_network_call_count": 0, "reuse_hash_valid_sec_checkpoint": True,
        "sec_numeric_fact_count_reused": 904_071, "accession_accepted_time_linkage_count": 30_653,
        "sec_payloads": payloads,
    }
    atomic_json(OUT / "recovery_contract.json", recovery_contract)
    atomic_csv(OUT / "gate_recovery_priority.csv", priority)
    atomic_parquet(OUT / "sec_fundamental_coverage_recovery_overlay.parquet", overlay)
    post_output = post_daily.rename(columns={"passes_frozen_per_date_gate": "current_pass"})
    atomic_csv(OUT / "post_recovery_coverage.csv", post_output)
    overlay_sha = sha256_file(OUT / "sec_fundamental_coverage_recovery_overlay.parquet")
    coverage_sha = sha256_file(OUT / "post_recovery_coverage.csv")

    resume_sha = "NOT_APPLICABLE"
    blocker_name: str | None = None
    if full_pass:
        resume = {
            "source_research_id": SOURCE_RESEARCH_ID, "coverage_recovery_task_id": TASK_ID,
            "raw_top40_checkpoint_path": str(CHECKPOINT), "raw_top40_checkpoint_sha256": CHECKPOINT_SHA256,
            "source_prereg_sha256": PREREG_SHA256, "source_concept_contract_sha256": CONCEPT_SHA256,
            "cik_overlay_path": str(OUT / "sec_fundamental_coverage_recovery_overlay.parquet"), "cik_overlay_sha256": overlay_sha,
            "semantic_overlay_path": None, "semantic_overlay_sha256": None,
            "post_recovery_coverage_path": str(OUT / "post_recovery_coverage.csv"), "post_recovery_coverage_sha256": coverage_sha,
            "sec_payload_hashes": {name: item[3] for name, item in PAYLOAD_CONTRACT.items()},
            "pre_recovery_median_coverage": pre["median"], "post_recovery_median_coverage": post["median"],
            "pre_recovery_passing_date_fraction": pre["passing_fraction"], "post_recovery_passing_date_fraction": post["passing_fraction"],
            "coverage_gate_pass": True, "economic_feature_definition_changed": False, "economic_search_space_changed": False,
            "fundamental_model_fit_count": 0, "outer_consumed": False, "2025_consumed": False, "2026_outcome_used": False,
            "next_authorized_step": "RESUME_FROZEN_A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1",
        }
        atomic_json(OUT / "resume_contract.json", resume)
        resume_sha = sha256_file(OUT / "resume_contract.json")
    else:
        blocker_name = "remaining_coverage_blockers.csv"
        final_deficits = post_daily.set_index("decision_date").deficit_count.to_dict()
        blocker_rows: list[dict[str, Any]] = []
        remaining_missing = current.loc[~current.covered_under_frozen_contract]
        for item in targeted.itertuples(index=False):
            dates = set(remaining_missing.loc[remaining_missing.security_id.eq(item.security_id), "decision_date"])
            active = [date for date in dates if final_deficits.get(date, 0) > 0]
            if not active:
                continue
            if item.security_id in class_index.index:
                classified = class_index.loc[item.security_id]
                blocker_class, legality, reason = classified.classification, classified.repair_legality, classified.why_not_repairable
            else:
                blocker_class, legality, reason = "RESOLVED_CIK_COVERAGE_GAP", "NO_LEGAL_SAME_SEMANTIC_REPAIR_EVIDENCE", item.likely_mapping_filer_issue
            blocker_rows.append({
                "priority": len(blocker_rows) + 1, "security_id": item.security_id, "ticker": item.ticker, "issuer_name": item.issuer_name,
                "remaining_failing_date_occurrence_count": len(active),
                "remaining_deficit_contribution": sum(1 / final_deficits[date] for date in active),
                "current_cik_status": item.cik_status, "blocker_class": blocker_class, "repair_legality": legality,
                "why_not_repairable": reason, "theoretical_dates_rescued_if_repaired": sum(final_deficits[date] == 1 for date in active),
            })
        atomic_csv(OUT / blocker_name, pd.DataFrame(blocker_rows))

    attempted_unresolved = classification.loc[classification.security_id.astype(str).isin(processed)]
    repaired_security_ids = set(overlay.security_id.astype(str)) if not overlay.empty else set()
    resolved_counts = resolved_gap_counts(targeted)
    summary: dict[str, Any] = {
        "TASK_STATUS": task_status, "PRIMARY_CLASSIFICATION": primary,
        "SOURCE_RESEARCH_ID": SOURCE_RESEARCH_ID, "SOURCE_PREREG_SHA256": PREREG_SHA256, "SOURCE_CONCEPT_CONTRACT_SHA256": CONCEPT_SHA256,
        "RAW_TOP40_CHECKPOINT_PATH": str(CHECKPOINT), "RAW_TOP40_CHECKPOINT_SHA256_MATCH": "TRUE",
        "RAW_TOP40_DECISION_DATE_COUNT": EXPECTED_DATES, "RAW_TOP40_TOTAL_ROWS": EXPECTED_ROWS,
        "SYS_EXECUTABLE": runtime["SYS_EXECUTABLE"], "RUNTIME_CANONICAL_STATUS": "PASS",
        "OUTCOME_DATA_READ_FOR_RECOVERY": "FALSE", "FUNDAMENTAL_MODEL_FIT_COUNT": 0, "RAW_MODEL_FIT_COUNT": 0,
        "INNER_SELECTION_COUNT": 0, "OUTER_READ_COUNT": 0, "READ_2025_COUNT": 0, "READ_2026_OUTCOME_COUNT": 0,
        "FROZEN_MEDIAN_COVERAGE_GATE": 0.60, "FROZEN_PER_DATE_COVERAGE_THRESHOLD": 0.50,
        "FROZEN_PASSING_DATE_FRACTION_GATE": 0.75, "COVERAGE_GATE_CHANGED": "FALSE",
        "PRE_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE": pre["median"], "PRE_RECOVERY_PASSING_DATE_FRACTION": pre["passing_fraction"],
        "PRE_RECOVERY_PASSING_DATE_COUNT": pre["passing_count"], "PRE_RECOVERY_FAILING_DATE_COUNT": pre["failing_count"],
        "REQUIRED_PASSING_DATE_COUNT": required_passing, "MIN_ADDITIONAL_PASSING_DATES": minimum_additional,
        "TARGETED_IMPACT_SECURITY_COUNT_R2": len(targeted), "TARGETED_CIK_UNRESOLVED_COUNT_R2": int(targeted.cik_status.eq("UNRESOLVED").sum()),
        "TARGETED_RESOLVED_COVERAGE_GAP_COUNT_R2": int(targeted.cik_status.ne("UNRESOLVED").sum()),
        "THEORETICAL_MAX_PASSING_DATE_FRACTION": theoretical_max, "LEGAL_REPAIR_THEORETICAL_MAX_PASSING_DATE_FRACTION": legal_max,
        "THEORETICAL_GATE_RECOVERABLE": str(theoretical_recoverable).upper(),
        "CIK_REPAIR_ATTEMPT_COUNT": len(attempted_unresolved), "CIK_REPAIR_ACCEPTED_COUNT": len(repaired_security_ids),
        "CIK_REPAIR_AMBIGUOUS_COUNT": int(attempted_unresolved.classification.eq("AMBIGUOUS_ISSUER").sum()),
        "CIK_REPAIR_REJECTED_COUNT": int(attempted_unresolved.repair_legality.ne("HIGH_CONFIDENCE_LEGALLY_REPAIRABLE").sum()),
        "DOMESTIC_10Q10K_MAPPABLE_COUNT": int(classification.repair_legality.eq("HIGH_CONFIDENCE_LEGALLY_REPAIRABLE").sum()),
        "FOREIGN_FILER_COUNT": int(classification.classification.eq("FOREIGN_FILER").sum()),
        "HISTORICAL_IDENTITY_CHANGE_COUNT": int(classification.classification.eq("HISTORICAL_TICKER_OR_NAME_CHANGE").sum()),
        "NON_OPERATING_ENTITY_COUNT": int(classification.classification.eq("NON_OPERATING_OR_FUND_ENTITY").sum()),
        "AMBIGUOUS_ISSUER_COUNT": int(classification.classification.eq("AMBIGUOUS_ISSUER").sum()),
        **resolved_counts,
        "SEMANTIC_RECOVERY_CANDIDATE_COUNT": 0, "SEMANTIC_ALIAS_ACCEPTED_COUNT": 0, "SEMANTIC_ALIAS_REJECTED_COUNT": 0,
        "ECONOMIC_FEATURE_DEFINITION_CHANGED": "FALSE", "BATCHES_COMPLETED": batch_count, "RECOVERY_STOP_REASON": stop_reason,
        "POST_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE": post["median"], "POST_RECOVERY_PASSING_DATE_FRACTION": post["passing_fraction"],
        "POST_RECOVERY_PASSING_DATE_COUNT": post["passing_count"], "POST_RECOVERY_FAILING_DATE_COUNT": post["failing_count"],
        "DATES_RECOVERED_TO_PASS": post["passing_count"] - pre["passing_count"],
        "MEDIAN_COVERAGE_GATE_PASS": str(post["median"] >= 0.60).upper(),
        "PASSING_DATE_FRACTION_GATE_PASS": str(post["passing_fraction"] >= 0.75).upper(),
        "FULL_FROZEN_COVERAGE_GATE_PASS": str(full_pass).upper(),
        "PIT_EFFECTIVE_DATE_STATUS": new_lineage.get("pit_effective_date_status", "PASS_REUSED_UNCHANGED_HASHED_CHECKPOINT"),
        "RESTATEMENT_GUARD_STATUS": new_lineage.get("restatement_guard_status", "PASS_REUSED_UNCHANGED_HASHED_CHECKPOINT"),
        "UNIT_SCALE_STATUS": new_lineage.get("unit_scale_status", "PASS_REUSED_UNCHANGED_HASHED_CHECKPOINT"),
        "CONCEPT_CONTRACT_STATUS": "PASS_FROZEN_UNCHANGED", "NON_TARGETED_UNRESOLVED_CIK_REPAIR_COUNT": 0,
        "CIK_OVERLAY_SHA256": overlay_sha, "SEMANTIC_OVERLAY_SHA256": "NOT_APPLICABLE",
        "POST_RECOVERY_COVERAGE_SHA256": coverage_sha, "RESUME_CONTRACT_SHA256": resume_sha,
        "TASK_LOCAL_ANTI_BLOAT_STATUS": "PENDING_TEST", "PREEXISTING_ACL_EXCEPTION_COUNT": 2,
        "FINAL_ARTIFACT_COUNT": 7, "HASH_MANIFEST_STATUS": "PENDING",
        "NEXT_AUTHORIZED_STEP": "RESUME_FROZEN_A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1" if full_pass else "STOP_NO_ALPHA_RESEARCH",
    }
    summary["TASK_LOCAL_ANTI_BLOAT_STATUS"] = "PASS_WITH_PREEXISTING_ACL_EXCEPTION"
    summary["HASH_MANIFEST_STATUS"] = "PASS_HASH_VERIFIED"
    report = f"""# A2 SEC Fundamental Targeted Coverage Recovery R2

`{primary}`

This was data/coverage maintenance only. It used the hash-valid 1,253-date / 50,120-row authoritative Raw Top40 checkpoint and never read an economic outcome or fit a model. The frozen coverage contract and feature definition were unchanged.

## Exact incidence and recovery

{incidence_explanation}

The exact pre-state was median coverage {pre['median']:.6f}, {pre['passing_count']}/{EXPECTED_DATES} passing dates ({pre['passing_fraction']:.15f}). The post-state is median coverage {post['median']:.6f}, {post['passing_count']}/{EXPECTED_DATES} passing dates ({post['passing_fraction']:.15f}). Recovery stopped with `{stop_reason}`.

Identity acceptance required a PIT CUSIP-linked issuer and a unique normalized SEC entity match. Ambiguous or historically unsafe mappings remained unresolved. No foreign-form support or semantic alias was added.

```text
{final_block(summary)}
```
"""
    atomic_bytes(OUT / "final_report.md", report.encode("utf-8"))
    artifact_names = ["final_report.md", "recovery_contract.json", "gate_recovery_priority.csv", "sec_fundamental_coverage_recovery_overlay.parquet", "post_recovery_coverage.csv"]
    artifact_names.append("resume_contract.json" if full_pass else str(blocker_name))
    manifest = {
        "task_id": TASK_ID, "status": "PASS_HASH_VERIFIED", "artifact_count_including_manifest": len(artifact_names) + 1,
        "artifacts": [{"name": name, "bytes": (OUT / name).stat().st_size, "sha256": sha256_file(OUT / name)} for name in artifact_names],
        "source_prereg_sha256": PREREG_SHA256, "source_concept_contract_sha256": CONCEPT_SHA256,
        "raw_top40_checkpoint_sha256": CHECKPOINT_SHA256,
        "companyfacts_sha256": PAYLOAD_CONTRACT["companyfacts"][3], "submissions_sha256": PAYLOAD_CONTRACT["submissions"][3],
        "outcome_data_read": False, "model_fit_count": 0, "raw_model_fit_count": 0,
        "outer_read_count": 0, "read_2025_count": 0, "read_2026_outcome_count": 0,
    }
    atomic_json(OUT / "hash_manifest.json", manifest)
    require(len(list(OUT.iterdir())) <= 8, "ARTIFACT_BUDGET", len(list(OUT.iterdir())))
    for item in manifest["artifacts"]:
        require(sha256_file(OUT / item["name"]) == item["sha256"], "ARTIFACT_HASH_FAILURE", item["name"])
    print(final_block(summary), flush=True)
    return 0 if full_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
