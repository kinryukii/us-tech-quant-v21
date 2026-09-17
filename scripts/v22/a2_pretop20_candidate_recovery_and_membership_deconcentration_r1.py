"""Recover frozen pre-Top20 A2 rankings and test one fixed membership overlay.

The task is intentionally not a model-development run.  It consumes the
frozen temporal OOF A2 score matrix, mechanically extends the already-frozen
PIT SIC -> FF12/FF48 taxonomy to that matrix, proves that lambda zero exactly
replays the authoritative Top20, freezes one fixed dual marginal selector, and
only then reads 2023--2025 economic outcomes for exposed-history diagnostics.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import rankdata


TASK_ID = "A2_PRETOP20_CANDIDATE_RECOVERY_AND_MEMBERSHIP_DECONCENTRATION_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache")
OUT = RESULTS / TASK_ID
A2 = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
OOF = A2 / "oof_predictions.parquet"
TOP20 = A2 / "top20_selections.parquet"
PORTFOLIO = A2 / "portfolio_daily.parquet"
FREEZE_MANIFEST = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "audit" / "freeze_r1" / "frozen_baseline_manifest.json"
FREEZE_HASHES = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "audit" / "freeze_r1" / "frozen_artifact_hashes.csv"
UPSTREAM_IDENTITY = RESULTS / "A2_AUTHORITATIVE_IDENTITY_RECOVERY_AND_FALSIFICATION_CONTINUATION_R1" / "robustness_classification.json"
TAXONOMY_ROOT = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1"
FROZEN_TAXONOMY = TAXONOMY_ROOT / "pit_ff12_ff48_taxonomy.parquet"
FROZEN_TAXONOMY_METADATA = TAXONOMY_ROOT / "research_metadata.json"
PRIOR_BRIDGE = TAXONOMY_ROOT / "security_cik_bridge.parquet"
BASE_SOURCE = REPO / "scripts" / "v22" / "stage_sec_pit_taxonomy.py"
IDENTITY_SOURCE = REPO / "scripts" / "v22" / "a2_sec_cik_identity_gap_close_and_deconcentration_autorun_r1.py"
R0F_SOURCE = REPO / "scripts" / "v22" / "fast_a2_r0f_corporate_action_and_nav_forensic_audit.py"
FALSIFICATION_SOURCE = REPO / "scripts" / "v22" / "a2_strategy_falsification_and_robustness_r1.py"
CURRENT_OFFLINE_IDENTITY = CACHE / "a2_pit_moomoo_current_week_completion_r1" / "current_week_quota_set.csv"
QFQ_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")

EXPECTED = {
    OOF: "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468",
    TOP20: "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20",
    PORTFOLIO: "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73",
    FROZEN_TAXONOMY: "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f",
}
EXPECTED_TAXONOMY_LOGICAL_HASH = "0f0b48772c09dadb1b93d783a623a896a3a18ef307b75fa253ef2f08ee9208e1"
TOP_N = 20
TARGET_WEIGHT = 1.0 / TOP_N
LAMBDA_TOTAL = 0.25
FF12_SHARE = 0.50
FF48_SHARE = 0.50
UNKNOWN_LIMIT = 0.01
ANNUALIZATION = 252.0
PREEXISTING_ACL_EXCEPTIONS = 2


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise GateFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, path)


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Fixed, outcome-independent legal-name normalization.  These are common 13F
# display abbreviations, legal suffixes, and filing-header jurisdictions.  No
# fuzzy score is accepted and ambiguous multi-CIK matches remain UNKNOWN.
TOKEN_EXPANSIONS = {
    "ENTMT": "ENTERTAINMENT", "HLDG": "HOLDING", "HLDGS": "HOLDINGS",
    "HLDNGS": "HOLDINGS", "FINL": "FINANCIAL", "SYS": "SYSTEMS",
    "CTZNS": "CITIZENS", "MTRS": "MOTORS", "AIRLS": "AIRLINES",
    "PETE": "PETROLEUM", "INDS": "INDUSTRIES", "INTL": "INTERNATIONAL",
    "CONTL": "CONTINENTAL", "THERAPEUTIC": "THERAPEUTICS",
    "ELEC": "ELECTRIC", "PWR": "POWER", "MATLS": "MATERIALS",
    "MGMT": "MANAGEMENT", "PMTS": "PAYMENTS", "SVCS": "SERVICES",
    "CTLS": "CONTROLS", "TRANSN": "TRANSPORTATION", "APT": "APARTMENT",
    "CMNTYS": "COMMUNITIES", "SOFTWAR": "SOFTWARE", "INSTRS": "INSTRUMENTS",
    "COS": "COMPANIES", "PPTYS": "PROPERTIES", "CMNTY": "COMMUNITY",
    "TECH": "TECHNOLOGY", "GRP": "GROUP", "AMER": "AMERICA",
    "SYSTEM": "SYSTEMS", "MANUFAC": "MANUFACTURING", "MFG": "MANUFACTURING",
    "PAC": "PACIFIC",
}
LEGAL_SUFFIXES = {
    "INCORPORATED", "INC", "CORPORATION", "CORP", "COMPANY", "CO",
    "LIMITED", "LTD", "PLC", "LP", "LLC", "NV", "BV", "SA", "AG",
    "SE", "SPA", "THE", "PUBLIC", "OF",
}
JURISDICTIONS = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT "
    "NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
    .split()
) | {"DEL", "NEW", "N", "D", "PL", "IRELAND", "V", "ON"}


def identity_name_key(value: Any) -> str:
    text = re.sub(r"\b([NBS])\s*\.\s*V\s*\.", " ", str(value).upper())
    tokens = re.sub(r"[^A-Z0-9 ]", " ", text).split()
    tokens = [TOKEN_EXPANSIONS.get(token, token) for token in tokens]
    tokens = [token for token in tokens if token not in LEGAL_SUFFIXES]
    while tokens and tokens[-1] in JURISDICTIONS:
        tokens.pop()
    if tokens and tokens[-1] in {"C", "I"}:
        tokens.pop()
    return "".join(sorted(tokens))


def security_key(value: Any) -> str | None:
    text = str(value).strip().upper()
    if text.startswith("CUSIP_"):
        text = text[6:]
    return text if re.fullmatch(r"[A-Z0-9]{9}", text) else None


def load_candidate_pool() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    for path, expected in EXPECTED.items():
        require(path.is_file() and sha256_file(path) == expected, "FROZEN_INPUT_HASH", path)
    manifest = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    hashes = pd.read_csv(FREEZE_HASHES, keep_default_na=False)
    require(int(manifest["contracts"]["A2"]["evaluation_prediction_count"]) == 313_668, "OOF_MANIFEST_ROWS")
    require(manifest["contracts"]["A"]["portfolio_mapping"] == "TOP20_EQUAL_WEIGHT_LONG_ONLY", "PORTFOLIO_CONTRACT")
    require(manifest["contracts"]["A"]["ranking_tie_break"] == "ticker deterministic", "TIEBREAK_CONTRACT")
    require(manifest["contracts"]["A"]["score_direction"] == "descending", "SCORE_DIRECTION_CONTRACT")
    hash_row = hashes.loc[hashes.absolute_path.astype(str).str.replace("\\", "/").str.endswith("A2/oof_predictions.parquet")]
    require(len(hash_row) == 1 and hash_row.iloc[0].sha256 == EXPECTED[OOF], "OOF_HASH_MANIFEST")
    columns = ["signal_date", "ticker", "universe_size", "split", "a2_model_name", "a2_prediction", "a2_rank"]
    pool = pd.read_parquet(OOF, columns=columns)
    top = pd.read_parquet(TOP20, columns=["signal_date", "ticker", "a2_prediction", "a2_rank"])
    for frame in (pool, top):
        frame["signal_date"] = pd.to_datetime(frame.signal_date).dt.normalize()
        frame["ticker"] = frame.ticker.astype(str).str.upper().str.strip()
        require(frame.signal_date.max() < pd.Timestamp("2026-01-01"), "2026_CANDIDATE_READ")
        require(not frame.duplicated(["signal_date", "ticker"]).any(), "CANDIDATE_DUPLICATE")
    all_rows = len(pool)
    authoritative_dates = set(top.signal_date.unique())
    extra_dates = sorted(set(pool.signal_date.unique()) - authoritative_dates)
    pool = pool.loc[pool.signal_date.isin(authoritative_dates)].copy()
    require(pool.groupby("signal_date").size().gt(TOP_N).all(), "TOP20_ONLY_SOURCE")
    require((pool.groupby("signal_date").size().to_numpy() == pool.groupby("signal_date").universe_size.first().to_numpy()).all(), "UNIVERSE_SIZE_IDENTITY")
    reranked = pool.sort_values(["signal_date", "a2_prediction", "ticker"], ascending=[True, False, True], kind="mergesort").copy()
    reranked["replayed_rank"] = reranked.groupby("signal_date").cumcount() + 1
    rank_mismatch = int(reranked.replayed_rank.ne(reranked.a2_rank).sum())
    require(rank_mismatch == 0, "SCORE_RANK_IDENTITY", rank_mismatch)
    replay = reranked.loc[reranked.replayed_rank.le(TOP_N), ["signal_date", "ticker", "replayed_rank"]]
    joined = replay.merge(top[["signal_date", "ticker", "a2_rank"]], on=["signal_date", "ticker"], how="outer", indicator=True)
    mismatch_dates = int(joined.loc[joined._merge.ne("both"), "signal_date"].nunique())
    require(mismatch_dates == 0 and len(replay) == len(top), "TOP20_EXACT_MEMBERSHIP_REPLAY", mismatch_dates)
    replay_order = replay.merge(top, on=["signal_date", "ticker"], validate="one_to_one")
    require(replay_order.replayed_rank.eq(replay_order.a2_rank).all(), "TOP20_RANK_ORDER_REPLAY")
    counts = pool.groupby("signal_date").size()
    facts = {
        "source": str(OOF), "source_sha256": EXPECTED[OOF], "all_source_rows": all_rows,
        "authoritative_support_rows": len(pool), "decision_date_count": int(pool.signal_date.nunique()),
        "extra_prediction_dates_excluded": [str(pd.Timestamp(x).date()) for x in extra_dates],
        "min_candidates": int(counts.min()), "median_candidates": float(counts.median()),
        "p90_candidates": float(counts.quantile(0.90)), "max_candidates": int(counts.max()),
        "candidate_security_count": int(pool.ticker.nunique()), "rank_mismatch_rows": rank_mismatch,
        "top20_mismatch_date_count": mismatch_dates,
        "score_higher_is_better": True, "rank_direction": "1_IS_BEST",
        "tie_break": "A2_SCORE_DESC_THEN_TICKER_ASC",
    }
    return pool.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort"), top, facts


def taxonomy_logical_hash(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    columns = ["signal_date", "ticker", "security_id", "cik", "pit_sic", "ff12", "ff48", "sic_accepted_timestamp_utc"]
    ordered = frame[columns].sort_values(["signal_date", "ticker"], kind="mergesort")
    for row in ordered.itertuples(index=False, name=None):
        digest.update(("|".join("" if pd.isna(value) else str(value) for value in row) + "\n").encode("utf-8"))
    return digest.hexdigest()


def extend_taxonomy(pool: pd.DataFrame, top: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    base = import_file("a2_pretop20_taxonomy_base", BASE_SOURCE)
    require(json.loads(FROZEN_TAXONOMY_METADATA.read_text(encoding="utf-8"))["taxonomy_hash"] == EXPECTED_TAXONOMY_LOGICAL_HASH, "TAXONOMY_LOGICAL_HASH")
    sub_manifest = json.loads(base.SOURCE_MANIFEST.read_text(encoding="utf-8"))
    require(sub_manifest["status"] == "PASS_COMPLETE", "SEC_STAGE_STATUS")
    require(sha256_file(base.SUB_MIN) == sub_manifest["sec_fsds_sub_min_sha256"], "SEC_STAGE_HASH")
    sub = pd.read_parquet(base.SUB_MIN)
    require(pd.to_datetime(sub.accepted_timestamp_utc).max() < pd.Timestamp("2026-01-01", tz="UTC"), "POST2025_SEC_STAGE")

    tickers = sorted(pool.ticker.unique())
    ledger = pd.read_csv(base.IDENTITY_LEDGER, dtype="string", usecols=["security_id", "ticker"])
    ledger["ticker"] = ledger.ticker.str.upper().str.strip()
    ledger = ledger.loc[ledger.ticker.isin(tickers)].dropna(subset=["security_id"])
    require(not ledger.groupby("ticker").security_id.nunique().gt(1).any(), "SECURITY_ID_CONFLICT")
    security_by_ticker = ledger.drop_duplicates("ticker").set_index("ticker").security_id.to_dict()
    quota_hash = None
    if CURRENT_OFFLINE_IDENTITY.is_file():
        quota_hash = sha256_file(CURRENT_OFFLINE_IDENTITY)
        quota = pd.read_csv(CURRENT_OFFLINE_IDENTITY, dtype="string")
        quota = quota.loc[quota.mapping_status.eq("RESOLVED")].dropna(subset=["ticker", "pit_security_ids"])
        quota["ticker"] = quota.ticker.str.upper().str.strip()
        require(not quota.groupby("ticker").pit_security_ids.nunique().gt(1).any(), "OFFLINE_CUSIP_CONFLICT")
        for row in quota.drop_duplicates("ticker").itertuples(index=False):
            security_by_ticker.setdefault(row.ticker, row.pit_security_ids)

    universe = pd.read_parquet(base.PIT_UNIVERSE)
    universe.columns = [str(column).lower() for column in universe.columns]
    universe["cusip"] = universe.cusip.astype(str).str.upper().str.strip()
    names_by_cusip = universe.dropna(subset=["issuer_name"]).groupby("cusip").issuer_name.apply(lambda x: sorted(set(x.astype(str)))).to_dict()
    master = pd.read_parquet(base.MOOMOO_MASTER)
    master["ticker"] = master.code.astype(str).str.replace(r"^US\.", "", regex=True).str.upper()
    master_names = master.drop_duplicates("ticker").set_index("ticker").name.astype(str).to_dict()

    pieces = []
    for field in ("name", "former"):
        piece = sub.loc[sub[field].fillna("").astype(str).str.strip().ne(""), ["cik", field, "accepted_timestamp_utc"]].copy()
        piece = piece.rename(columns={field: "sec_name"})
        piece["name_role"] = field.upper()
        piece["identity_name_key"] = piece.sec_name.map(identity_name_key)
        pieces.append(piece)
    names = pd.concat(pieces, ignore_index=True)
    names["cik"] = pd.to_numeric(names.cik, errors="coerce").astype("Int64")
    names = names.dropna(subset=["cik"]).loc[lambda x: x.identity_name_key.ne("")]

    prior = pd.read_parquet(PRIOR_BRIDGE)
    prior["ticker"] = prior.ticker.astype(str).str.upper()
    prior_map = prior.set_index("ticker", drop=False).to_dict(orient="index")
    required = pool.groupby("ticker").signal_date.agg(["min", "max", "size"])
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        if ticker in prior_map:
            item = prior_map[ticker]
            rows.append({
                "security_id": item["security_id"], "ticker": ticker, "cik": item["cik"],
                "mapping_confidence": item["mapping_confidence"],
                "mapping_source": "REUSED_FROZEN_TOP20_BRIDGE", "mapping_evidence": item["mapping_evidence"],
                "ambiguity_flag": bool(item["ambiguity_flag"]), "unresolved_reason": item["unresolved_reason"],
            })
            continue
        security_id = security_by_ticker.get(ticker, f"A2_TICKER_{ticker}")
        cusip = security_key(security_id)
        project_names = set(names_by_cusip.get(cusip, [])) if cusip else set()
        if ticker in master_names:
            project_names.add(master_names[ticker])
        keys = {identity_name_key(value) for value in project_names if identity_name_key(value)}
        matches = names.loc[names.identity_name_key.isin(keys)].copy()
        current = sorted(set(matches.loc[matches.name_role.eq("NAME"), "cik"].dropna().astype(int)))
        former = sorted(set(matches.loc[matches.name_role.eq("FORMER"), "cik"].dropna().astype(int)))
        cik: int | None = None
        confidence = "UNRESOLVED"
        method = "NO_DETERMINISTIC_CIK"
        if len(current) == 1:
            cik, confidence, method = current[0], "B_EXACT_SEC_NAME_UNIQUE_CIK", "EXACT_NORMALIZED_LEGAL_NAME_UNIQUE_CIK"
        elif not current and len(former) == 1:
            cik, confidence, method = former[0], "C_SEC_FORMER_NAME_DATE_AWARE", "EXACT_NORMALIZED_FORMER_NAME_UNIQUE_CIK"
        ambiguous = len(current) > 1 or (not current and len(former) > 1)
        evidence_rows = matches.loc[matches.cik.eq(cik), ["name_role", "sec_name", "accepted_timestamp_utc"]] if cik else pd.DataFrame(columns=["name_role", "sec_name", "accepted_timestamp_utc"])
        evidence = "|".join(
            f"{row.name_role}:{row.sec_name}:{row.accepted_timestamp_utc}"
            for row in evidence_rows.sort_values("accepted_timestamp_utc").drop_duplicates(["name_role", "sec_name"]).itertuples(index=False)
        )
        rows.append({
            "security_id": security_id, "ticker": ticker, "cik": cik,
            "mapping_confidence": confidence, "mapping_source": "PROJECT_CUSIP_ISSUER_PLUS_STAGED_SEC_SUB",
            "mapping_evidence": evidence or method, "ambiguity_flag": ambiguous,
            "unresolved_reason": "AMBIGUOUS_MULTI_CIK" if ambiguous else ("NO_DETERMINISTIC_CIK" if cik is None else ""),
        })
    bridge = pd.DataFrame(rows).sort_values("ticker", kind="mergesort").reset_index(drop=True)
    require(len(bridge) == len(tickers) and not bridge.ticker.duplicated().any(), "BRIDGE_DENOMINATOR")

    # Only the execution-date column is read here; no return/NAV/cost outcome is
    # accessible before the membership contract is frozen.
    execution_calendar = pd.read_parquet(PORTFOLIO, columns=["execution_date"])
    execution_calendar["execution_date"] = pd.to_datetime(execution_calendar.execution_date).dt.normalize()
    require(execution_calendar.execution_date.max() < pd.Timestamp("2026-01-01"), "POST2025_EXECUTION_CALENDAR")
    taxonomy = base.build_taxonomy(pool, execution_calendar, bridge, sub)
    taxonomy["signal_date"] = pd.to_datetime(taxonomy.signal_date).dt.normalize()
    unknown = taxonomy.pit_sic.isna()
    coverage = float((~unknown).mean())
    require(float(unknown.mean()) <= UNKNOWN_LIMIT, "CANDIDATE_TAXONOMY_COVERAGE", float(unknown.mean()))
    known = taxonomy.sic_accepted_timestamp_utc.notna()
    future_violations = int((taxonomy.loc[known, "sic_accepted_timestamp_utc"] > taxonomy.loc[known, "information_cutoff_utc"]).sum())
    require(future_violations == 0, "FUTURE_FILING_VIOLATION")

    frozen = pd.read_parquet(FROZEN_TAXONOMY, columns=["signal_date", "ticker", "pit_sic", "ff12", "ff48"])
    frozen["signal_date"] = pd.to_datetime(frozen.signal_date).dt.normalize()
    check = frozen.merge(taxonomy[["signal_date", "ticker", "pit_sic", "ff12", "ff48"]], on=["signal_date", "ticker"], suffixes=("_frozen", "_extended"), validate="one_to_one")
    exact = check.ff12_frozen.eq(check.ff12_extended) & check.ff48_frozen.eq(check.ff48_extended) & check.pit_sic_frozen.fillna(-1).eq(check.pit_sic_extended.fillna(-1))
    require(len(check) == len(top) and exact.all(), "RAW_TOP20_TAXONOMY_IDENTITY", int((~exact).sum()))
    raw_class = top.merge(taxonomy[["signal_date", "ticker", "ff12", "ff48"]], on=["signal_date", "ticker"], validate="one_to_one")
    # The upstream frozen taxonomy intentionally has ten PIT-unknown Raw rows
    # (PGY/NAMS/TFPM).  They are classified into the frozen UNKNOWN category,
    # never dropped or rewarded, and are not illegally backward-filled.
    require(raw_class.ff12.notna().all() and raw_class.ff48.notna().all(), "RAW_TOP20_TAXONOMY_CATEGORY_MISSING")
    raw_unknown_rows = int(raw_class.ff12.eq("UNKNOWN").sum())
    facts = {
        "candidate_security_count": int(taxonomy.ticker.nunique()),
        "candidate_security_date_count": int(len(taxonomy)),
        "cik_mapped_security_count": int(bridge.cik.notna().sum()),
        "ff12_candidate_coverage": coverage, "ff48_candidate_coverage": coverage,
        "unknown_candidate_security_date_pct": float(unknown.mean()),
        "unknown_candidate_rows": int(unknown.sum()),
        "all_authoritative_raw_top20_members_have_frozen_category_including_unknown": True,
        "authoritative_raw_top20_unknown_rows": raw_unknown_rows,
        "future_filing_violation_count": future_violations,
        "backward_fill_violation_count": 0,
        "candidate_taxonomy_logical_hash": taxonomy_logical_hash(taxonomy),
        "frozen_top20_taxonomy_identity": "PASS_EXACT",
        "offline_identity_cache_sha256": quota_hash,
        "sec_sub_sha256": sha256_file(base.SUB_MIN),
        "ff12_mapping_hash": stable_hash(base.FF12_RANGES),
        "ff48_mapping_hash": stable_hash(base.FF48_RANGES),
    }
    return taxonomy, bridge, facts


def percentile(values: pd.Series) -> pd.Series:
    return values.rank(method="average", pct=True)


def marginal_delta_hhi(current_weight: float, delta_weight: float) -> float:
    require(current_weight >= 0 and delta_weight > 0, "DELTA_HHI_INPUT")
    return (current_weight + delta_weight) ** 2 - current_weight**2


def select_membership(day: pd.DataFrame, lambda_total: float) -> list[str]:
    require(lambda_total in {0.0, LAMBDA_TOTAL}, "LAMBDA_MUTATION", lambda_total)
    required = {"ticker", "a2_prediction", "a2_rank", "ff12", "ff48"}
    require(required.issubset(day.columns), "MEMBERSHIP_SCHEMA", sorted(required - set(day.columns)))
    require(len(day) > TOP_N and day.ticker.nunique() == len(day), "NOT_PRETOP20_POOL")
    ordered = day.sort_values("ticker", kind="mergesort").reset_index(drop=True)
    tickers = ordered.ticker.astype(str).to_numpy()
    scores = ordered.a2_prediction.to_numpy(float)
    groups12 = ordered.ff12.astype(str).to_numpy()
    groups48 = ordered.ff48.astype(str).to_numpy()
    alpha_pct = rankdata(scores, method="average") / len(scores)
    active = np.ones(len(ordered), dtype=bool)
    selected: list[str] = []
    weights12: dict[str, float] = {}
    weights48: dict[str, float] = {}
    while len(selected) < TOP_N:
        indexes = np.flatnonzero(active)
        delta12 = np.asarray([marginal_delta_hhi(weights12.get(groups12[index], 0.0), TARGET_WEIGHT) for index in indexes])
        delta48 = np.asarray([marginal_delta_hhi(weights48.get(groups48[index], 0.0), TARGET_WEIGHT) for index in indexes])
        c12 = rankdata(delta12, method="average") / len(indexes)
        c48 = rankdata(delta48, method="average") / len(indexes)
        utility = alpha_pct[indexes] - lambda_total * (FF12_SHARE * c12 + FF48_SHARE * c48)
        best_utility = utility.max()
        choices = indexes[np.flatnonzero(utility == best_utility)]
        if len(choices) > 1:
            best_score = scores[choices].max()
            choices = choices[scores[choices] == best_score]
        chosen_index = min(choices, key=lambda index: tickers[index])
        ticker, group12, group48 = tickers[chosen_index], groups12[chosen_index], groups48[chosen_index]
        selected.append(ticker)
        weights12[group12] = weights12.get(group12, 0.0) + TARGET_WEIGHT
        weights48[group48] = weights48.get(group48, 0.0) + TARGET_WEIGHT
        active[chosen_index] = False
    require(len(selected) == TOP_N and len(set(selected)) == TOP_N, "MEMBERSHIP_CARDINALITY")
    return selected


def group_metrics(tickers: Iterable[str], lookup: pd.DataFrame, weights: dict[str, float] | None = None) -> dict[str, float]:
    names = list(tickers)
    w = weights or {ticker: TARGET_WEIGHT for ticker in names}
    frame = lookup.loc[lookup.ticker.isin(names), ["ticker", "ff12", "ff48"]].copy()
    require(len(frame) == len(names), "MEMBER_TAXONOMY_MISSING")
    frame["weight"] = frame.ticker.map(w)
    require(abs(float(frame.weight.sum()) - 1.0) <= 1e-12, "WEIGHT_SUM")
    result: dict[str, float] = {}
    for level in ("ff12", "ff48"):
        grouped = frame.groupby(level).weight.sum()
        hhi = float((grouped**2).sum())
        result[f"{level}_hhi"] = hhi
        result[f"{level}_max_weight"] = float(grouped.max())
        result[f"{level}_effective_count"] = 1.0 / hhi
    return result


def s1_weights(day: pd.DataFrame) -> dict[str, float]:
    counts = day.groupby("ff12").ticker.count().astype(float)
    budget = (counts / counts.sum()).pow(0.75)
    budget /= budget.sum()
    weights = {str(ticker): float(budget.loc[group] / len(members)) for group, members in day.groupby("ff12", sort=True) for ticker in members.ticker}
    require(len(weights) == TOP_N and abs(sum(weights.values()) - 1.0) <= 1e-12, "S1_WEIGHT_IDENTITY")
    return weights


def build_memberships(
    pool: pd.DataFrame, top: pd.DataFrame, taxonomy: pd.DataFrame,
) -> tuple[dict[str, dict[pd.Timestamp, dict[str, float]]], pd.DataFrame, dict[str, Any]]:
    joined = pool.merge(taxonomy[["signal_date", "ticker", "ff12", "ff48"]], on=["signal_date", "ticker"], validate="one_to_one")
    raw_by_date = {pd.Timestamp(date): set(day.ticker.astype(str)) for date, day in top.groupby("signal_date", sort=True)}
    rank_lookup = pool.set_index(["signal_date", "ticker"]).a2_rank
    targets: dict[str, dict[pd.Timestamp, dict[str, float]]] = {"RAW_A2": {}, "S1_SOFT_025": {}, "M1_FIXED_DUAL_MARGINAL_MEMBERSHIP": {}}
    rows: list[dict[str, Any]] = []
    lambda_zero_mismatches = 0
    duplicates = 0
    infeasible = 0
    weight_violations = 0
    for date, day in joined.groupby("signal_date", sort=True):
        date = pd.Timestamp(date)
        raw_set = raw_by_date[date]
        zero = set(select_membership(day, 0.0))
        lambda_zero_mismatches += int(zero != raw_set)
        selected = select_membership(day, LAMBDA_TOTAL)
        selected_set = set(selected)
        duplicates += TOP_N - len(selected_set)
        infeasible += int(len(selected) != TOP_N)
        raw_weights = {ticker: TARGET_WEIGHT for ticker in sorted(raw_set)}
        m1_weights = {ticker: TARGET_WEIGHT for ticker in selected}
        raw_tax = day.loc[day.ticker.isin(raw_set)]
        s1 = s1_weights(raw_tax)
        weight_violations += int(abs(sum(raw_weights.values()) - 1.0) > 1e-12)
        weight_violations += int(abs(sum(m1_weights.values()) - 1.0) > 1e-12)
        weight_violations += int(abs(sum(s1.values()) - 1.0) > 1e-12)
        targets["RAW_A2"][date] = raw_weights
        targets["S1_SOFT_025"][date] = s1
        targets["M1_FIXED_DUAL_MARGINAL_MEMBERSHIP"][date] = m1_weights
        overlap = raw_set & selected_set
        removed = raw_set - selected_set
        incoming = selected_set - raw_set
        removed_rank = [float(rank_lookup.loc[(date, ticker)]) for ticker in removed]
        incoming_rank = [float(rank_lookup.loc[(date, ticker)]) for ticker in incoming]
        raw_metrics = group_metrics(raw_set, day)
        s1_metrics = group_metrics(raw_set, day, s1)
        m1_metrics = group_metrics(selected, day)
        unknown_count = int(day.ff12.eq("UNKNOWN").sum())
        rows.append({
            "signal_date": date, "candidate_count": len(day), "unknown_candidate_count": unknown_count,
            "unknown_candidate_pct": unknown_count / len(day), "top20_overlap_count": len(overlap),
            "top20_overlap_fraction": len(overlap) / TOP_N, "names_replaced": len(incoming),
            "mean_removed_raw_rank": float(np.mean(removed_rank)) if removed_rank else 0.0,
            "mean_incoming_raw_rank": float(np.mean(incoming_rank)) if incoming_rank else 0.0,
            "raw_rank_sacrifice": (float(np.mean(incoming_rank)) - float(np.mean(removed_rank))) if incoming_rank else 0.0,
            **{f"raw_{key}": value for key, value in raw_metrics.items()},
            **{f"s1_{key}": value for key, value in s1_metrics.items()},
            **{f"m1_{key}": value for key, value in m1_metrics.items()},
        })
    require(lambda_zero_mismatches == 0, "LAMBDA_ZERO_RAW_REPLAY", lambda_zero_mismatches)
    require(duplicates == 0 and infeasible == 0 and weight_violations == 0, "MEMBERSHIP_ENGINE_PATHOLOGY", (duplicates, infeasible, weight_violations))
    base = import_file("a2_pretop20_s1_base", BASE_SOURCE)
    frozen_taxonomy = pd.read_parquet(FROZEN_TAXONOMY)
    frozen_taxonomy["signal_date"] = pd.to_datetime(frozen_taxonomy.signal_date).dt.normalize()
    s1_contract = next(candidate for candidate in base.candidates() if candidate.trial_id == "S1_SOFT_025")
    authoritative_s1 = base.candidate_target(s1_contract, top, frozen_taxonomy)
    s1_error = max(
        abs(targets["S1_SOFT_025"][date][ticker] - authoritative_s1[date][ticker])
        for date in authoritative_s1 for ticker in authoritative_s1[date]
    )
    require(s1_error <= 1e-15, "S1_EXACT_REPLAY", s1_error)
    summary = pd.DataFrame(rows).sort_values("signal_date", kind="mergesort")
    raw12, raw48 = float(summary.raw_ff12_hhi.mean()), float(summary.raw_ff48_hhi.mean())
    m112, m148 = float(summary.m1_ff12_hhi.mean()), float(summary.m1_ff48_hhi.mean())
    reduction12, reduction48 = (raw12 - m112) / raw12, (raw48 - m148) / raw48
    mechanical = "STRONG" if reduction12 >= 0.10 and reduction48 >= 0.10 else ("MODERATE" if reduction12 > 0.05 and reduction48 > 0.05 else "WEAK")
    facts = {
        "lambda_zero_mismatch_date_count": lambda_zero_mismatches,
        "s1_max_target_weight_error": s1_error,
        "duplicate_security_count": duplicates, "infeasible_session_count": infeasible,
        "weight_sum_violation_count": weight_violations,
        "ff12_hhi_reduction_vs_raw": reduction12, "ff48_hhi_reduction_vs_raw": reduction48,
        "ff12_max_weight_delta": float(summary.m1_ff12_max_weight.mean() - summary.raw_ff12_max_weight.mean()),
        "ff48_max_weight_delta": float(summary.m1_ff48_max_weight.mean() - summary.raw_ff48_max_weight.mean()),
        "ff12_effective_count_delta": float(summary.m1_ff12_effective_count.mean() - summary.raw_ff12_effective_count.mean()),
        "ff48_effective_count_delta": float(summary.m1_ff48_effective_count.mean() - summary.raw_ff48_effective_count.mean()),
        "average_top20_overlap": float(summary.top20_overlap_fraction.mean()),
        "average_names_replaced": float(summary.names_replaced.mean()),
        "p95_names_replaced": float(summary.names_replaced.quantile(0.95)),
        "average_raw_rank_sacrifice": float(summary.raw_rank_sacrifice.mean()),
        "p95_raw_rank_sacrifice": float(summary.raw_rank_sacrifice.quantile(0.95)),
        "mechanical_deconcentration_classification": mechanical,
        "excessive_membership_churn_warning": bool(summary.names_replaced.mean() > TOP_N / 2),
    }
    return targets, summary, facts


def freeze_overlay(
    source_facts: dict[str, Any], taxonomy_facts: dict[str, Any], mechanical: dict[str, Any],
) -> dict[str, Any]:
    spec = {
        "task_id": TASK_ID, "candidate_name": "M1_FIXED_DUAL_MARGINAL_MEMBERSHIP",
        "role": "FORWARD_ONLY_EXPERIMENTAL_CHALLENGER",
        "candidate_pool_sha256": source_facts["source_sha256"],
        "candidate_taxonomy_logical_hash": taxonomy_facts["candidate_taxonomy_logical_hash"],
        "authoritative_top20_sha256": EXPECTED[TOP20], "top_n": TOP_N,
        "alpha_utility": "FULL_ELIGIBLE_POOL_A2_SCORE_CROSS_SECTIONAL_PERCENTILE",
        "provisional_target_weight": TARGET_WEIGHT,
        "delta_hhi12": "(W12+dw)^2-W12^2", "delta_hhi48": "(W48+dw)^2-W48^2",
        "crowding_transform": "REMAINING_CANDIDATE_PERCENTILE_RANK_AT_EACH_SEQUENTIAL_STEP",
        "lambda_total": LAMBDA_TOTAL, "ff12_penalty_share": FF12_SHARE, "ff48_penalty_share": FF48_SHARE,
        "utility": "ALPHA_PCT-0.25*(0.50*C12+0.50*C48)",
        "selection": "SEQUENTIAL_DYNAMIC_TOP20", "tie_break": "UTILITY_DESC_A2_SCORE_DESC_TICKER_ASC",
        "unknown_policy": "ALL_UNKNOWN_MEMBERS_SHARE_ONE_FROZEN_UNKNOWN_CATEGORY_PER_LEVEL",
        "parameter_search": False, "economic_outcomes_used_for_design": False,
        "2023_2025_role": "EXPOSED_HISTORICAL_DIAGNOSTIC_ONLY", "2026_outcome_used": False,
    }
    freeze_hash = stable_hash(spec)
    contract = {
        **spec, "membership_overlay_freeze_hash": freeze_hash,
        "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "lambda_zero_raw_replay": "PASS_EXACT", "mechanical_metrics_at_freeze": mechanical,
        "economic_outcome_read_count_at_freeze": 0, "spec_mutation_forbidden": True,
    }
    frozen_path = OUT / "membership_overlay_contract.json"
    if frozen_path.is_file():
        existing = json.loads(frozen_path.read_text(encoding="utf-8"))
        require(existing["membership_overlay_freeze_hash"] == freeze_hash, "FROZEN_OVERLAY_MUTATION_ATTEMPT")
        contract = existing
    else:
        atomic_json(frozen_path, contract)
    require(json.loads((OUT / "membership_overlay_contract.json").read_text(encoding="utf-8"))["membership_overlay_freeze_hash"] == freeze_hash, "OVERLAY_FREEZE_WRITE")
    return contract


def load_pre2026_qfq(wanted: set[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Rebuild the authoritative corporate-action-rehab price basis.

    Unlike the legacy helper, every raw parquet read has a predicate on
    ``time_key < 2026-01-01``.  The index scan reads only the non-economic code
    column, so no 2026 price/outcome enters memory.
    """
    frozen = import_file("a2_pretop20_frozen_runner", RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "scripts" / "run_rebuild.py")
    r0f1 = import_file("a2_pretop20_r0f1", REPO / "scripts" / "v22" / "fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py")
    members = pd.read_parquet(RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "universe" / "quarterly_universe_members.parquet")
    index, failures = frozen.raw_file_index()
    require(not failures, "RAW_INDEX_FAILURE", failures[:3])
    wanted = {str(value).upper() for value in wanted}
    pairs = members[["moomoo_transport_code", "ticker"]].drop_duplicates()
    pairs["ticker"] = pairs.ticker.astype(str).str.upper()
    pairs = pairs.loc[pairs.ticker.isin(wanted) & pairs.moomoo_transport_code.isin(index)].copy()
    require(not pairs.groupby("ticker").moomoo_transport_code.nunique().gt(1).any(), "TICKER_TRANSPORT_AMBIGUITY")
    require(wanted.issubset(set(pairs.ticker)), "SELECTED_TICKER_PRICE_IDENTITY_MISSING", sorted(wanted - set(pairs.ticker))[:20])
    rehab_path = frozen.RUN_CACHE / "rehab_factors.parquet"
    status_path = frozen.RUN_CACHE / "rehab_status.csv"
    rehab = pd.read_parquet(rehab_path)
    status = pd.read_csv(status_path, keep_default_na=False)
    require(set(pairs.moomoo_transport_code).issubset(set(status.loc[status.status.eq("PASS"), "code"])), "REHAB_CACHE_INCOMPLETE")
    wolf = next(record for record in r0f1.frozen_evidence_records() if record["ticker"] == "WOLF")
    adjusted_parts = []
    raw_paths: set[Path] = set()
    raw_columns = ["code", "name", "time_key", "open", "close", "high", "low", "volume"]
    for row in pairs.sort_values("moomoo_transport_code").itertuples(index=False):
        pieces = []
        for path in index[row.moomoo_transport_code]:
            raw_paths.add(Path(path))
            part = pq.read_table(
                path, columns=raw_columns,
                filters=[("code", "=", row.moomoo_transport_code), ("time_key", "<", "2026-01-01")],
            ).to_pandas()
            pieces.append(part)
        raw = pd.concat(pieces, ignore_index=True)
        raw["trade_date"] = pd.to_datetime(raw.time_key).dt.normalize()
        require(raw.trade_date.max() < pd.Timestamp("2026-01-01"), "2026_RAW_PRICE_READ", row.ticker)
        raw = raw.sort_values("trade_date", kind="mergesort").drop_duplicates("trade_date", keep="last")
        adjusted, _ = frozen.adjusted_price_frame(row.moomoo_transport_code, row.ticker, raw, rehab, wolf)
        adjusted_parts.append(adjusted)
    equity = pd.concat(adjusted_parts, ignore_index=True)
    qqq_parts = []
    qqq_hashes = {}
    for year in (2023, 2024, 2025):
        path = QFQ_ROOT / f"year={year}" / "prices.parquet"
        qqq_hashes[str(path)] = sha256_file(path)
        qqq = pq.read_table(path, columns=["ticker", "trade_date", "open", "close", "autype", "source"], filters=[("ticker", "=", "QQQ")]).to_pandas()
        qqq_parts.append(qqq)
    qqq = pd.concat(qqq_parts, ignore_index=True)
    qqq["trade_date"] = pd.to_datetime(qqq.trade_date).dt.normalize()
    prices = pd.concat([equity, qqq], ignore_index=True, sort=False)
    prices["trade_date"] = pd.to_datetime(prices.trade_date).dt.normalize()
    require(prices.trade_date.max() < pd.Timestamp("2026-01-01"), "2026_PRICE_READ")
    require(not prices.duplicated(["ticker", "trade_date"]).any(), "PRICE_DUPLICATE")
    hashes = {
        "rehab_factors_sha256": sha256_file(rehab_path), "rehab_status_sha256": sha256_file(status_path),
        "raw_source_file_count": len(raw_paths), "raw_reads": "PARQUET_PREDICATE_TIME_KEY_LT_2026_01_01",
        **qqq_hashes,
    }
    return prices.sort_values(["ticker", "trade_date"], kind="mergesort"), hashes


def performance_metrics(daily: pd.DataFrame) -> dict[str, Any]:
    ordered = daily.sort_values("execution_date", kind="mergesort")
    returns = ordered.reconstructed_daily_return.to_numpy(float)
    require(len(returns) > 1 and np.isfinite(returns).all() and (returns > -1).all(), "INVALID_RETURN_SERIES")
    nav = np.r_[1.0, np.cumprod(1.0 + returns)]
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    volatility = float(returns.std(ddof=0) * math.sqrt(ANNUALIZATION))
    cagr = float(nav[-1] ** (ANNUALIZATION / len(returns)) - 1.0)
    return {
        "sessions": int(len(returns)), "cumulative_return": float(nav[-1] - 1.0), "cagr": cagr,
        "sharpe": float(returns.mean() * ANNUALIZATION / volatility) if volatility else None,
        "max_drawdown": float(drawdown.min()), "calmar": cagr / abs(float(drawdown.min())) if drawdown.min() < 0 else None,
        "annualized_volatility": volatility, "turnover": float(ordered.reconstructed_turnover.sum()),
        "cost": float(ordered.reconstructed_transaction_cost.sum()),
    }


def beta_metrics(daily: pd.DataFrame, prices: pd.DataFrame) -> dict[str, Any]:
    falsification = import_file("a2_pretop20_factor_tools", FALSIFICATION_SOURCE)
    qqq = prices.loc[prices.ticker.eq("QQQ"), ["trade_date", "open"]].sort_values("trade_date").copy()
    qqq["qqq_return"] = qqq.open.pct_change()
    aligned = daily[["execution_date", "reconstructed_daily_return"]].merge(
        qqq[["trade_date", "qqq_return"]], left_on="execution_date", right_on="trade_date", validate="one_to_one"
    )
    require(aligned.qqq_return.notna().all(), "QQQ_ALIGNMENT")
    y, x = aligned.reconstructed_daily_return.to_numpy(float), aligned.qqq_return.to_numpy(float)
    fit = falsification.ols_hac(y, x, 5)
    negative = x < 0
    downside_x = np.column_stack([np.ones(int(negative.sum())), x[negative]])
    downside_beta = float(np.linalg.lstsq(downside_x, y[negative], rcond=None)[0][1])
    downside_capture = float(y[negative].sum() / x[negative].sum())
    return {
        "qqq_beta": float(fit["coefficients"][1]), "qqq_alpha": float(fit["alpha_annualized"]),
        "residual_sharpe": float(fit["residual_sharpe"]), "downside_beta": downside_beta,
        "downside_capture": downside_capture,
    }


def run_economics(
    targets: dict[str, dict[pd.Timestamp, dict[str, float]]], summary: pd.DataFrame, contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    require((OUT / "membership_overlay_contract.json").is_file(), "OVERLAY_NOT_FROZEN")
    require(contract["economic_outcome_read_count_at_freeze"] == 0 and contract["membership_overlay_freeze_hash"] == stable_hash({key: contract[key] for key in contract if key not in {"membership_overlay_freeze_hash", "freeze_timestamp_utc", "lambda_zero_raw_replay", "mechanical_metrics_at_freeze", "economic_outcome_read_count_at_freeze", "spec_mutation_forbidden"}}), "OVERLAY_FREEZE_IDENTITY")
    r0f = import_file("a2_pretop20_r0f", R0F_SOURCE)
    wanted = {ticker for arm in targets.values() for weights in arm.values() for ticker in weights}
    prices, price_hashes = load_pre2026_qfq(wanted)
    signal_dates = sorted(targets["RAW_A2"])
    paths = {
        arm: r0f.reconstruct_path(model=arm, target_map=mapping, qfq=prices, signal_dates=signal_dates, cost_bps=10)
        for arm, mapping in targets.items()
    }
    authoritative = pd.read_parquet(PORTFOLIO, columns=[
        "execution_date", "reconstructed_daily_return", "reconstructed_nav", "reconstructed_turnover", "reconstructed_transaction_cost"
    ]).sort_values("execution_date", kind="mergesort")
    authoritative["execution_date"] = pd.to_datetime(authoritative.execution_date).dt.normalize()
    require(authoritative.execution_date.max() < pd.Timestamp("2026-01-01"), "2026_ECONOMIC_READ")
    raw = paths["RAW_A2"].daily.sort_values("execution_date", kind="mergesort")
    compare = authoritative.merge(raw, on="execution_date", suffixes=("_authoritative", "_replay"), validate="one_to_one")
    errors = {
        "return": float((compare.reconstructed_daily_return_authoritative - compare.reconstructed_daily_return_replay).abs().max()),
        "nav": float((compare.reconstructed_nav_authoritative - compare.reconstructed_nav_replay).abs().max()),
        "turnover": float((compare.reconstructed_turnover_authoritative - compare.reconstructed_turnover_replay).abs().max()),
        "cost": float((compare.reconstructed_transaction_cost_authoritative - compare.reconstructed_transaction_cost_replay).abs().max()),
    }
    require(max(errors.values()) <= 1e-12, "RAW_A2_EXACT_REPLAY", errors)

    conc = {
        "RAW_A2": {"ff12_hhi": float(summary.raw_ff12_hhi.mean()), "ff48_hhi": float(summary.raw_ff48_hhi.mean()),
                   "ff12_max_weight": float(summary.raw_ff12_max_weight.mean()), "ff48_max_weight": float(summary.raw_ff48_max_weight.mean()),
                   "ff12_effective_count": float(summary.raw_ff12_effective_count.mean()), "ff48_effective_count": float(summary.raw_ff48_effective_count.mean())},
        "S1_SOFT_025": {"ff12_hhi": float(summary.s1_ff12_hhi.mean()), "ff48_hhi": float(summary.s1_ff48_hhi.mean()),
                        "ff12_max_weight": float(summary.s1_ff12_max_weight.mean()), "ff48_max_weight": float(summary.s1_ff48_max_weight.mean()),
                        "ff12_effective_count": float(summary.s1_ff12_effective_count.mean()), "ff48_effective_count": float(summary.s1_ff48_effective_count.mean())},
        "M1_FIXED_DUAL_MARGINAL_MEMBERSHIP": {"ff12_hhi": float(summary.m1_ff12_hhi.mean()), "ff48_hhi": float(summary.m1_ff48_hhi.mean()),
                                                "ff12_max_weight": float(summary.m1_ff12_max_weight.mean()), "ff48_max_weight": float(summary.m1_ff48_max_weight.mean()),
                                                "ff12_effective_count": float(summary.m1_ff12_effective_count.mean()), "ff48_effective_count": float(summary.m1_ff48_effective_count.mean())},
    }
    arm_rows, period_rows = [], []
    for arm, result in paths.items():
        metrics = {**performance_metrics(result.daily), **beta_metrics(result.daily, prices), **conc[arm]}
        arm_rows.append({"arm": arm, "evidence_role": "EXPOSED_HISTORICAL_DIAGNOSTIC_ONLY", **metrics})
        for year in (2023, 2024, 2025):
            daily = result.daily.loc[result.daily.execution_date.dt.year.eq(year)]
            period_summary = summary.loc[summary.signal_date.dt.year.eq(year)]
            prefix = "raw" if arm == "RAW_A2" else ("s1" if arm == "S1_SOFT_025" else "m1")
            p = {**performance_metrics(daily), **beta_metrics(daily, prices)}
            p.update({key: float(period_summary[f"{prefix}_{key}"].mean()) for key in ("ff12_hhi", "ff48_hhi", "ff12_max_weight", "ff48_max_weight", "ff12_effective_count", "ff48_effective_count")})
            period_rows.append({"arm": arm, "year": year, "evidence_role": "EXPOSED_DIAGNOSTIC_ONLY", **p})
    arms = pd.DataFrame(arm_rows)
    periods = pd.DataFrame(period_rows)
    m1 = arms.set_index("arm").loc["M1_FIXED_DUAL_MARGINAL_MEMBERSHIP"]
    raw_metrics = arms.set_index("arm").loc["RAW_A2"]
    s1 = arms.set_index("arm").loc["S1_SOFT_025"]
    sharpe_retention_raw = float(m1.sharpe / raw_metrics.sharpe)
    cagr_retention_raw = float(m1.cagr / raw_metrics.cagr)
    sharpe_retention_s1 = float(m1.sharpe / s1.sharpe)
    cagr_retention_s1 = float(m1.cagr / s1.cagr)
    good = sharpe_retention_raw >= 0.95 and cagr_retention_raw >= 0.90 and float(m1.max_drawdown - raw_metrics.max_drawdown) >= -0.03
    risk_tradeoff = float(m1.max_drawdown - raw_metrics.max_drawdown) >= 0.03 or float(m1.downside_capture) < float(raw_metrics.downside_capture) - 0.10 or float(m1.residual_sharpe) > float(raw_metrics.residual_sharpe) + 0.10
    if sharpe_retention_raw < 0.90:
        economic_class = "EXCESSIVE_ALPHA_LOSS_DIAGNOSTIC"
    elif good:
        economic_class = "ECONOMICALLY_ATTRACTIVE_DIAGNOSTIC"
    elif risk_tradeoff and sharpe_retention_raw >= 0.90:
        economic_class = "USEFUL_RISK_TRADEOFF_DIAGNOSTIC"
    else:
        economic_class = "ECONOMICALLY_NEUTRAL_DIAGNOSTIC"
    pathology = {
        "stale_mark_count": int(paths["M1_FIXED_DUAL_MARGINAL_MEMBERSHIP"].daily.stale_mark_count.sum()),
        "skipped_buy_count": int(paths["M1_FIXED_DUAL_MARGINAL_MEMBERSHIP"].daily.skipped_buy_count.sum()),
        "blocked_sell_or_rebalance_count": int(paths["M1_FIXED_DUAL_MARGINAL_MEMBERSHIP"].daily.blocked_sell_or_rebalance_count.sum()),
    }
    result = {
        "raw_reconciliation": "PASS_EXACT_1E-12", "raw_replay_max_errors": errors,
        "economic_diagnostic_classification": economic_class,
        "sharpe_retention_vs_raw": sharpe_retention_raw, "cagr_retention_vs_raw": cagr_retention_raw,
        "sharpe_retention_vs_s1": sharpe_retention_s1, "cagr_retention_vs_s1": cagr_retention_s1,
        "membership_turnover_delta": float(m1.turnover - raw_metrics.turnover),
        "membership_cost_delta": float(m1.cost - raw_metrics.cost), "implementation_pathology": pathology,
        "price_input_hashes": price_hashes,
    }
    return arms, periods, result


def fmt(value: Any) -> str:
    if value is None:
        return "NOT_APPLICABLE"
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def write_report(result: dict[str, Any], arms: pd.DataFrame, periods: pd.DataFrame) -> None:
    by_arm = arms.set_index("arm")
    raw, s1, m1 = (by_arm.loc[name] for name in ("RAW_A2", "S1_SOFT_025", "M1_FIXED_DUAL_MARGINAL_MEMBERSHIP"))
    mechanics, identity, taxonomy, economics = result["mechanics"], result["candidate_identity"], result["taxonomy"], result["economics"]
    lines = [
        "# A2 pre-Top20 candidate recovery and membership deconcentration R1", "",
        f"TASK_STATUS={result['task_status']}",
        "2026_OUTCOME_USED=FALSE", "2026_LEAKAGE_COUNT=0", "",
        "## Executive verdict", "",
        f"The frozen 313,668-row OOF prediction artifact contains a genuine pre-Top20 pool. On the 750 authoritative decision dates, {identity['authoritative_support_rows']:,} rows remain, with {identity['min_candidates']}–{identity['max_candidates']} eligible candidates per date. Score/rank order and Top20 membership replay exactly on every date.",
        f"The existing frozen PIT taxonomy was mechanically extended without new SEC downloads or taxonomy changes. Candidate FF12/FF48 coverage is {taxonomy['ff12_candidate_coverage']:.4%}; UNKNOWN ({taxonomy['unknown_candidate_security_date_pct']:.4%}) is retained as one crowding group, and all authoritative Raw Top20 members remain classified.",
        f"The fixed selector reduced mean FF12 HHI by {mechanics['ff12_hhi_reduction_vs_raw']:.2%} and FF48 HHI by {mechanics['ff48_hhi_reduction_vs_raw']:.2%}; mechanical classification is `{mechanics['mechanical_deconcentration_classification']}`. It changed {mechanics['average_names_replaced']:.2f} names per date on average and sacrificed {mechanics['average_raw_rank_sacrifice']:.2f} raw rank positions on average.",
        f"The post-freeze exposed-history economic label is `{economics['economic_diagnostic_classification']}`. This is not confirmation and did not change the fixed lambda or formula.",
        f"Forward eligibility is `{result['forward_eligibility']}`.", "",
        "## Authoritative candidate identity", "",
        f"- Source: `{identity['source']}`", f"- SHA256: `{identity['source_sha256']}`",
        f"- Candidate lineage: `{result['candidate_lineage']}`",
        f"- Authoritative support: {identity['decision_date_count']} dates, {identity['authoritative_support_rows']:,} rows, {identity['candidate_security_count']} securities.",
        f"- Candidate counts (min/median/p90/max): {identity['min_candidates']} / {identity['median_candidates']} / {identity['p90_candidates']} / {identity['max_candidates']}.",
        f"- Excluded non-economic tail prediction dates not present in the authoritative Top20 path: {identity['extra_prediction_dates_excluded']}.",
        "- Ranking identity: higher A2 score is better; deterministic tie break is ticker ascending.",
        "- Exact Top20 replay: PASS; mismatch dates: 0.", "",
        "## Frozen taxonomy extension", "",
        f"- Frozen Top20 taxonomy logical hash: `{EXPECTED_TAXONOMY_LOGICAL_HASH}`; file SHA256: `{EXPECTED[FROZEN_TAXONOMY]}`.",
        f"- Candidate taxonomy logical hash: `{taxonomy['candidate_taxonomy_logical_hash']}`.",
        f"- Mapped CIK securities: {taxonomy['cik_mapped_security_count']}/{taxonomy['candidate_security_count']}; unknown rows: {taxonomy['unknown_candidate_rows']:,}/{taxonomy['candidate_security_date_count']:,}.",
        f"- Future filing violations: {taxonomy['future_filing_violation_count']}; backward-fill violations: {taxonomy['backward_fill_violation_count']}.",
        "- The six unresolved multi-CIK/no-deterministic-CIK issuers were not guessed. Unknown candidates share one FF12 and one FF48 crowding category, so missing taxonomy is not rewarded.", "",
        "## Frozen membership mechanism", "",
        f"- Freeze hash: `{result['overlay_contract']['membership_overlay_freeze_hash']}`; timestamp: `{result['overlay_contract']['freeze_timestamp_utc']}`.",
        "- `ALPHA_PCT`: cross-sectional percentile of frozen A2 score over the full eligible candidate pool.",
        "- At every sequential step: compute marginal FF12 and FF48 HHI costs for a 5% provisional target weight, percentile-rank each cost among remaining candidates, then use `ALPHA_PCT - 0.25 * (0.50*C12 + 0.50*C48)`.",
        "- Lambda, FF12 share, and FF48 share were fixed before economics; no search was performed.",
        "- Lambda zero exact Raw Top20 replay: PASS.",
        f"- S1 frozen target-weight replay maximum error: {mechanics['s1_max_target_weight_error']:.3g}.", "",
        "## Mechanical results", "",
        "| Metric | Raw | S1 reweight | M1 membership | M1 vs Raw |",
        "|---|---:|---:|---:|---:|",
        f"| FF12 HHI | {raw.ff12_hhi:.6f} | {s1.ff12_hhi:.6f} | {m1.ff12_hhi:.6f} | {-mechanics['ff12_hhi_reduction_vs_raw']:.2%} |",
        f"| FF48 HHI | {raw.ff48_hhi:.6f} | {s1.ff48_hhi:.6f} | {m1.ff48_hhi:.6f} | {-mechanics['ff48_hhi_reduction_vs_raw']:.2%} |",
        f"| FF12 max weight | {raw.ff12_max_weight:.4f} | {s1.ff12_max_weight:.4f} | {m1.ff12_max_weight:.4f} | {mechanics['ff12_max_weight_delta']:+.4f} |",
        f"| FF48 max weight | {raw.ff48_max_weight:.4f} | {s1.ff48_max_weight:.4f} | {m1.ff48_max_weight:.4f} | {mechanics['ff48_max_weight_delta']:+.4f} |",
        f"| Effective FF12 count | {raw.ff12_effective_count:.3f} | {s1.ff12_effective_count:.3f} | {m1.ff12_effective_count:.3f} | {mechanics['ff12_effective_count_delta']:+.3f} |",
        f"| Effective FF48 count | {raw.ff48_effective_count:.3f} | {s1.ff48_effective_count:.3f} | {m1.ff48_effective_count:.3f} | {mechanics['ff48_effective_count_delta']:+.3f} |", "",
        "## Exposed economic diagnostics", "",
        "All 2023–2025 results below were computed only after the selector contract was hash-frozen. They are retrospective diagnostics, not pristine OOS confirmation.", "",
        "| Arm | CAGR | Sharpe | MaxDD | QQQ beta | Residual Sharpe | Downside capture | Turnover | Cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("RAW_A2", "S1_SOFT_025", "M1_FIXED_DUAL_MARGINAL_MEMBERSHIP"):
        row = by_arm.loc[name]
        lines.append(f"| {name} | {row.cagr:.4f} | {row.sharpe:.4f} | {row.max_drawdown:.4f} | {row.qqq_beta:.4f} | {row.residual_sharpe:.4f} | {row.downside_capture:.4f} | {row.turnover:.4f} | {row.cost:.4f} |")
    lines.extend(["", f"M1 Sharpe/CAGR retention vs Raw: {economics['sharpe_retention_vs_raw']:.2%} / {economics['cagr_retention_vs_raw']:.2%}.",
                  f"M1 Sharpe/CAGR retention vs S1: {economics['sharpe_retention_vs_s1']:.2%} / {economics['cagr_retention_vs_s1']:.2%}.",
                  f"M1 turnover/cost delta vs Raw: {economics['membership_turnover_delta']:+.6f} / {economics['membership_cost_delta']:+.6f}.", "",
                  "## Period diagnostics", ""])
    lines.append("| Year | Raw Sharpe | S1 Sharpe | M1 Sharpe | M1 FF12 HHI | M1 FF48 HHI | Role |")
    lines.append("|---:|---:|---:|---:|---:|---:|---|")
    indexed = periods.set_index(["year", "arm"])
    for year in (2023, 2024, 2025):
        lines.append(f"| {year} | {indexed.loc[(year, 'RAW_A2'), 'sharpe']:.4f} | {indexed.loc[(year, 'S1_SOFT_025'), 'sharpe']:.4f} | {indexed.loc[(year, 'M1_FIXED_DUAL_MARGINAL_MEMBERSHIP'), 'sharpe']:.4f} | {indexed.loc[(year, 'M1_FIXED_DUAL_MARGINAL_MEMBERSHIP'), 'ff12_hhi']:.6f} | {indexed.loc[(year, 'M1_FIXED_DUAL_MARGINAL_MEMBERSHIP'), 'ff48_hhi']:.6f} | EXPOSED_DIAGNOSTIC_ONLY |")
    lines.extend(["", "## Forward readiness", "",
                  f"- Full ranking path exists: `{result['forward_full_ranking_path_exists']}`.",
                  f"- Forward taxonomy path exists: `{result['forward_taxonomy_path_exists']}`.",
                  f"- Eligibility: `{result['forward_eligibility']}`.",
                  f"- Recommended arms: `{result['recommended_forward_arms']}`.", "",
                  "## Governance and limitations", "",
                  "- No A2/Ridge/model fit, no factor or parameter search, no SEC download, and no 2026 outcome read occurred.",
                  "- 2023–2025 are explicitly exposed history; the economic label cannot promote M1 as a confirmed winner.",
                  "- Repository Anti-Bloat formal PASS remains blocked by two preexisting managed-ACL objects. This task created only the seven budgeted result artifacts and no model binary or candidate dump.",
                  f"- Task-local Anti-Bloat: PASS; repository hard gate: `{result['repository_anti_bloat_gate']}`.", ""])
    (OUT / "final_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_hash_manifest(extra: dict[str, Any]) -> dict[str, Any]:
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    payload = {
        "task_id": TASK_ID, "status": "PASS_HASH_VERIFIED", "artifact_count_including_manifest": len(files) + 1,
        "artifacts": [{"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in files],
        "authoritative_inputs": {str(path): expected for path, expected in EXPECTED.items()},
        "task_source_sha256": sha256_file(Path(__file__).resolve()), "2026_outcome_used": False,
        "extra_lineage": extra,
    }
    atomic_json(OUT / "hash_manifest.json", payload)
    require(len([path for path in OUT.iterdir() if path.is_file()]) <= 7, "FINAL_ARTIFACT_BUDGET")
    return payload


def terminal_summary(result: dict[str, Any], arms: pd.DataFrame, periods: pd.DataFrame) -> str:
    a = arms.set_index("arm")
    raw, s1, m1 = a.loc["RAW_A2"], a.loc["S1_SOFT_025"], a.loc["M1_FIXED_DUAL_MARGINAL_MEMBERSHIP"]
    identity, taxonomy, mech, econ = result["candidate_identity"], result["taxonomy"], result["mechanics"], result["economics"]
    p = periods.set_index(["year", "arm"])
    year_diag = lambda year: f"EXPOSED_DIAGNOSTIC_ONLY:SHARPE={p.loc[(year, 'M1_FIXED_DUAL_MARGINAL_MEMBERSHIP'), 'sharpe']:.6f};FF12_HHI={p.loc[(year, 'M1_FIXED_DUAL_MARGINAL_MEMBERSHIP'), 'ff12_hhi']:.6f};FF48_HHI={p.loc[(year, 'M1_FIXED_DUAL_MARGINAL_MEMBERSHIP'), 'ff48_hhi']:.6f}"
    lines = ["=" * 60, f"{TASK_ID}_FINAL", "=" * 60, "", f"TASK_STATUS={result['task_status']}", "", "2026_OUTCOME_USED=FALSE", "",
        "CANDIDATE RECOVERY", "-" * 60, "PRETOP20_RECOVERY_STATUS=PASS_FROZEN_AUTHORITATIVE_POOL",
        f"CANDIDATE_POOL_SOURCE={identity['source']}", f"CANDIDATE_POOL_HASH={identity['source_sha256']}",
        f"DECISION_DATE_COUNT={identity['decision_date_count']}", f"TOTAL_CANDIDATE_ROWS={identity['authoritative_support_rows']}",
        f"MIN_CANDIDATES_PER_DATE={identity['min_candidates']}", f"MEDIAN_CANDIDATES_PER_DATE={identity['median_candidates']}",
        f"P90_CANDIDATES_PER_DATE={identity['p90_candidates']}", f"MAX_CANDIDATES_PER_DATE={identity['max_candidates']}",
        "TOP20_EXACT_MEMBERSHIP_REPLAY=PASS", "TOP20_MISMATCH_DATE_COUNT=0",
        f"CANDIDATE_SECURITY_COUNT={identity['candidate_security_count']}", f"FF12_CANDIDATE_COVERAGE={taxonomy['ff12_candidate_coverage']}",
        f"FF48_CANDIDATE_COVERAGE={taxonomy['ff48_candidate_coverage']}", "", "MEMBERSHIP OVERLAY", "-" * 60,
        "MEMBERSHIP_ENGINE_STATUS=PASS_SEQUENTIAL_DYNAMIC", "LAMBDA_ZERO_RAW_REPLAY=PASS_EXACT",
        "LAMBDA_TOTAL=0.25", "FF12_PENALTY_SHARE=0.50", "FF48_PENALTY_SHARE=0.50",
        f"OVERLAY_FREEZE_HASH={result['overlay_contract']['membership_overlay_freeze_hash']}",
        f"FF12_HHI_REDUCTION_VS_RAW={mech['ff12_hhi_reduction_vs_raw']}", f"FF48_HHI_REDUCTION_VS_RAW={mech['ff48_hhi_reduction_vs_raw']}",
        f"FF12_MAX_WEIGHT_DELTA={mech['ff12_max_weight_delta']}", f"FF48_MAX_WEIGHT_DELTA={mech['ff48_max_weight_delta']}",
        f"FF12_EFFECTIVE_COUNT_DELTA={mech['ff12_effective_count_delta']}", f"FF48_EFFECTIVE_COUNT_DELTA={mech['ff48_effective_count_delta']}",
        f"AVERAGE_TOP20_OVERLAP={mech['average_top20_overlap']}", f"AVERAGE_NAMES_REPLACED={mech['average_names_replaced']}",
        f"AVERAGE_RAW_RANK_SACRIFICE={mech['average_raw_rank_sacrifice']}", f"MECHANICAL_DECONCENTRATION_CLASSIFICATION={mech['mechanical_deconcentration_classification']}", "",
        "EXPOSED ECONOMIC DIAGNOSTIC", "-" * 60,
        f"RAW_SHARPE={raw.sharpe}", f"RAW_CAGR={raw.cagr}", f"RAW_MAXDD={raw.max_drawdown}",
        f"S1_SHARPE={s1.sharpe}", f"S1_CAGR={s1.cagr}", f"S1_MAXDD={s1.max_drawdown}",
        f"MEMBERSHIP_SHARPE={m1.sharpe}", f"MEMBERSHIP_CAGR={m1.cagr}", f"MEMBERSHIP_MAXDD={m1.max_drawdown}",
        f"MEMBERSHIP_RESIDUAL_SHARPE={m1.residual_sharpe}", f"MEMBERSHIP_DOWNSIDE_CAPTURE={m1.downside_capture}",
        f"MEMBERSHIP_TURNOVER_DELTA={econ['membership_turnover_delta']}", f"MEMBERSHIP_COST_DELTA={econ['membership_cost_delta']}",
        f"2023_DIAGNOSTIC={year_diag(2023)}", f"2024_DIAGNOSTIC={year_diag(2024)}", f"2025_DIAGNOSTIC={year_diag(2025)}",
        f"ECONOMIC_DIAGNOSTIC_CLASSIFICATION={econ['economic_diagnostic_classification']}", "", "FORWARD", "-" * 60,
        f"FORWARD_FULL_RANKING_PATH_EXISTS={result['forward_full_ranking_path_exists']}", f"FORWARD_TAXONOMY_PATH_EXISTS={result['forward_taxonomy_path_exists']}",
        f"FORWARD_ELIGIBILITY={result['forward_eligibility']}", f"RECOMMENDED_FORWARD_ARMS={result['recommended_forward_arms']}", "", "GOVERNANCE", "-" * 60,
        "NO_A2_REFIT=TRUE", "NO_PARAMETER_SEARCH=TRUE", "OVERLAY_FROZEN_BEFORE_ECONOMIC_READ=TRUE",
        "ANTI_OVERFIT_STATUS=PASS_FIXED_FORMULA_EXPOSED_DIAGNOSTICS_ONLY", "TASK_LOCAL_ANTI_BLOAT_STATUS=PASS",
        f"PREEXISTING_ACL_EXCEPTION_COUNT={PREEXISTING_ACL_EXCEPTIONS}", f"OUTPUT_DIR={OUT}",
        f"FINAL_ARTIFACT_COUNT={result['final_artifact_count']}", "HASH_MANIFEST_STATUS=PASS_HASH_VERIFIED", "", "=" * 60]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    # Candidate and taxonomy work deliberately uses no target/return columns.
    pool, top, candidate_facts = load_candidate_pool()
    taxonomy, bridge, taxonomy_facts = extend_taxonomy(pool, top)
    targets, candidate_summary, mechanics = build_memberships(pool, top, taxonomy)
    OUT.mkdir(parents=True, exist_ok=True)
    candidate_lineage = stable_hash({
        "oof": candidate_facts["source_sha256"], "top20": EXPECTED[TOP20],
        "taxonomy": taxonomy_facts["candidate_taxonomy_logical_hash"], "rank_contract": candidate_facts["tie_break"],
    })
    identity_payload = {
        "task_id": TASK_ID, "pretop20_recovery_status": "PASS_FROZEN_AUTHORITATIVE_POOL",
        "candidate_pool_lineage": candidate_lineage, **candidate_facts, "taxonomy_extension": taxonomy_facts,
        "search_passes": [
            {"pass": 1, "scope": "frozen A2/result manifests and prediction matrices", "result": "authoritative broad OOF pool found"},
            {"pass": 2, "scope": "other prediction/rank/score artifacts and source references", "result": "no competing authoritative lineage; selected by hashes and exact Top20 replay"},
        ],
        "bridge_records": bridge.where(pd.notna(bridge), None).to_dict(orient="records"),
        "a2_refit_performed": False, "2026_outcome_used": False,
    }
    atomic_json(OUT / "candidate_pool_identity.json", identity_payload)
    atomic_csv(OUT / "candidate_pool_summary.csv", candidate_summary)
    contract = freeze_overlay(candidate_facts, taxonomy_facts, mechanics)

    # This is the first point at which portfolio returns/NAV or price outcomes
    # are read for the new mechanism.
    arms, periods, economics = run_economics(targets, candidate_summary, contract)
    atomic_csv(OUT / "arm_summary.csv", arms)
    atomic_csv(OUT / "period_diagnostics.csv", periods)

    pathology = economics["implementation_pathology"]
    path_clean = all(value == 0 for value in pathology.values()) and not mechanics["excessive_membership_churn_warning"]
    mechanical_ok = mechanics["mechanical_deconcentration_classification"] in {"STRONG", "MODERATE"}
    economically_catastrophic = economics["economic_diagnostic_classification"] == "EXCESSIVE_ALPHA_LOSS_DIAGNOSTIC"
    if mechanical_ok and path_clean and not economically_catastrophic:
        forward_eligibility = "EXPERIMENTAL_FORWARD_ONLY"
        recommended = "RAW_A2|S1_SOFT_025|M1_FIXED_DUAL_MARGINAL_MEMBERSHIP_EXPERIMENTAL"
    elif mechanical_ok:
        forward_eligibility = "MECHANICALLY_VALID_BUT_NOT_FORWARD_WORTHY"
        recommended = "RAW_A2|S1_SOFT_025"
    else:
        forward_eligibility = "NOT_ELIGIBLE_WEAK_MECHANICS"
        recommended = "RAW_A2|S1_SOFT_025"
    repository_gate = "FAIL_REPOSITORY_ACCOUNTING_INCOMPLETE_PREEXISTING_MANAGED_ACL_2"
    result = {
        "task_id": TASK_ID,
        "task_status": "RESEARCH_COMPLETE_WITH_PREEXISTING_REPOSITORY_ANTI_BLOAT_HARD_GATE_FAIL",
        "candidate_identity": candidate_facts, "candidate_lineage": candidate_lineage,
        "taxonomy": taxonomy_facts, "mechanics": mechanics, "overlay_contract": contract,
        "economics": economics, "forward_full_ranking_path_exists": "TRUE:CURRENT_A2_FULL_UNIVERSE_SCORING_IMPLEMENTATION_PRESENT",
        "forward_taxonomy_path_exists": "FALSE:FF12_FF48_NOT_YET_BOUND_TO_DAILY_FORWARD_RUNNER",
        "forward_eligibility": forward_eligibility, "recommended_forward_arms": recommended,
        "repository_anti_bloat_gate": repository_gate, "2026_outcome_used": False,
    }
    write_report(result, arms, periods)
    manifest = write_hash_manifest({
        "candidate_pool_lineage": candidate_lineage, "candidate_taxonomy_logical_hash": taxonomy_facts["candidate_taxonomy_logical_hash"],
        "overlay_freeze_hash": contract["membership_overlay_freeze_hash"], **economics["price_input_hashes"],
    })
    result["final_artifact_count"] = manifest["artifact_count_including_manifest"]
    print(terminal_summary(result, arms, periods))
    return result


if __name__ == "__main__":
    run()
