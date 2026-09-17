"""PIT sector-taxonomy recovery gate for the A2 deconcentration continuation.

The material treatment in this study is filing-time sector identity.  This
runner refuses to replace unavailable SEC filing evidence with present-day
labels, ticker guesses, or return-based clusters.  It verifies the frozen Raw
A2 path and records the bounded legacy/official-source recovery evidence.  If
the frozen coverage gate is not met it emits a compact, zero-trial closeout.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / "A2_PIT_SECTOR_TAXONOMY_AND_DECONCENTRATION_RESUME_R1"
A2 = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
UPSTREAM = RESULTS / "A2_AUTHORITATIVE_IDENTITY_RECOVERY_AND_FALSIFICATION_CONTINUATION_R1"
PRIOR = RESULTS / "A2_SECTOR_DECONCENTRATION_OVERNIGHT_OPEN_RESEARCH_R1"
IDENTITY_LEDGER = RESULTS / "A2_CANONICAL_COVERAGE_GAP_CLOSE_AND_PROMOTION_R1" / "coverage_gap_ledger.csv"

PORTFOLIO = A2 / "portfolio_daily.parquet"
TOP20 = A2 / "top20_selections.parquet"
TRAINING = A2 / "training_matrix.parquet"

EXPECTED = {
    PORTFOLIO: "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73",
    TOP20: "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20",
    TRAINING: "31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb",
}
FINAL_FILES = [
    "final_report.md", "taxonomy_contract.json", "finalist_freeze.json",
    "fold_results.csv", "research_metadata.json", "hash_manifest.json",
]
ANNUALIZATION = 252

SEC_SOURCES = {
    "historical_header_definition": "https://www.sec.gov/edgar/searchedgar/edgarzones.htm",
    "financial_statement_data_sets": "https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets",
    "financial_statement_data_documentation": "https://www.sec.gov/dera/data/fsds.pdf",
    "issuer_identity_registry": "https://www.sec.gov/files/company_tickers.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise RuntimeError(f"{code}:{detail}")


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def performance(returns: np.ndarray) -> dict[str, float]:
    nav = np.r_[1.0, np.cumprod(1.0 + returns)]
    cumulative = float(nav[-1] - 1.0)
    years = len(returns) / ANNUALIZATION
    cagr = float(nav[-1] ** (1.0 / years) - 1.0)
    volatility = float(np.std(returns, ddof=0) * np.sqrt(ANNUALIZATION))
    sharpe = float(np.mean(returns) * ANNUALIZATION / volatility)
    maxdd = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    return {
        "cumulative_return": cumulative, "cagr": cagr, "sharpe": sharpe,
        "max_drawdown": maxdd, "annualized_volatility": volatility,
        "calmar": float(cagr / abs(maxdd)), "session_count": int(len(returns)),
    }


def raw_folds(portfolio: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, group in portfolio.groupby(portfolio.execution_date.dt.year, sort=True):
        metrics = performance(group.reconstructed_daily_return.to_numpy(float))
        rows.append({
            "evidence_role": "AUTHORITATIVE_RAW_REFERENCE_NOT_CANDIDATE_SELECTION",
            "year": int(year), "candidate": "RAW_A2", **metrics,
        })
    return pd.DataFrame(rows)


def render_report(metadata: dict[str, Any], contract: dict[str, Any], folds: pd.DataFrame) -> str:
    raw = metadata["raw_baseline"]
    return f"""# A2 PIT sector taxonomy and deconcentration resume R1

TASK_STATUS={metadata['task_status']}

## Taxonomy

- Recovery path: `{metadata['taxonomy_recovery_path']}`.
- Legacy taxonomy recovered: `FALSE` after two bounded passes.
- A2 domain: {metadata['a2_unique_securities']} tickers and {metadata['a2_security_dates']} security-dates.
- Authoritative security-id bridge: {metadata['security_id_mapped_securities']}/{metadata['a2_unique_securities']} ({metadata['security_id_mapping_coverage']:.6%}); conflicts: {metadata['security_id_conflict_count']}.
- CIK, PIT SIC, FF12, and FF48 coverage: 0 because no official filing payload could be persisted or parsed.
- UNKNOWN security-date share: 100%; maximum UNKNOWN portfolio weight: 100%.
- Frozen continuation gate: UNKNOWN <=1% and max UNKNOWN weight <=5%; therefore Phase B is forbidden.

The two legacy passes covered the repository/Git/registered worktrees and the
known external results/cache/backtest/daily/archive roots.  A content-level scan
of 909 migrated V20/V21 tables found one 998-byte header-only table with
sector/industry columns and zero rows.  No V21 classification master, V20
metadata cache, CIK map, SEC submissions cache, quarterly `sub.txt`, or SEC ZIP
was recovered.

The official SEC source establishes that EDGAR SGML headers contain
`ASSIGNED-SIC`, and the Financial Statement Data Sets expose SIC as of filing
date.  The SEC data page was reachable for documentation, but the managed local
network refused HTTPS connections; the web retrieval surface rejects the ZIP's
`application/octet-stream`, and the in-app download runtime was unavailable.
Accordingly the required official historical payloads could not be acquired.
No present-day SIC was backfilled, no ticker was fuzzily classified, and no
return/price information was used to infer sector labels.

## Raw A2 identity

- Exact reconciliation: `{metadata['raw_a2_reconciliation']}`.
- Sessions: {raw['session_count']} ({metadata['raw_date_range'][0]} through {metadata['raw_date_range'][1]}).
- Cumulative return: {raw['cumulative_return']:.12f}; CAGR: {raw['cagr']:.12f}; Sharpe: {raw['sharpe']:.12f}; MaxDD: {raw['max_drawdown']:.12f}.
- Portfolio, Top20, and training-matrix SHA-256 identities match their frozen authoritative values.

## Research gate

- Total/successful/failed trials: 0/0/0.
- Candidate model fits, factor construction, parameter selection: 0/0/0.
- Candidate 2025 outcome reads: 0; 2026 outcome reads: 0.
- Finalists: 0; primary challenger: `NONE`.
- Taxonomy was not frozen because coverage failed.  No empty taxonomy or trial dataset was created.

## Raw fold reference (not candidate selection)

{folds.to_csv(index=False)}

## Governance

- Anti-overfit: `PASS_FAIL_CLOSED_BEFORE_CANDIDATE_SEARCH`.
- Anti-Bloat: `FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_1`.
- Canonical writes, broker actions, model fits, and new dependencies: all zero.
- The known unreadable `.tmp_a2_gap_close_r1_pytest` remains a registered pre-existing blocker; no ACL repair loop was attempted.

## Minimum unblocker

Make the official SEC quarterly Financial Statement Data Set archives (at
minimum the pre-2023 carry-forward quarter plus 2023--2025 quarters) available
under an approved external read-only/cache root, together with official issuer
identity evidence sufficient to resolve the 116 tickers absent from the frozen
security-id bridge.  Then rerun this same frozen taxonomy contract; do not use a
current-SIC backfill or reopen the research protocol.

Taxonomy contract SHA-256: `{canonical_hash(contract)}`.
"""


def terminal(metadata: dict[str, Any]) -> None:
    raw = metadata["raw_baseline"]
    fields = [
        "=" * 60, "A2_PIT_SECTOR_TAXONOMY_AND_DECONCENTRATION_RESUME_R1_FINAL", "=" * 60, "",
        f"TASK_STATUS={metadata['task_status']}", "", "-" * 60, "TAXONOMY", "-" * 60, "",
        f"TAXONOMY_RECOVERY_PATH={metadata['taxonomy_recovery_path']}", "LEGACY_TAXONOMY_RECOVERED=FALSE", "",
        "PRIMARY_TAXONOMY=FAMA_FRENCH_12_FROM_PIT_SEC_SIC_NOT_FROZEN",
        "SECONDARY_TAXONOMY=FAMA_FRENCH_48_FROM_PIT_SEC_SIC_NOT_FROZEN", "",
        f"A2_UNIQUE_SECURITIES={metadata['a2_unique_securities']}", f"A2_SECURITY_DATES={metadata['a2_security_dates']}", "",
        "CIK_MAPPING_COVERAGE=0.000000%", "PIT_SIC_COVERAGE=0.000000%",
        "FF12_SECURITY_DATE_COVERAGE=0.000000%", "FF48_SECURITY_DATE_COVERAGE=0.000000%", "",
        "UNKNOWN_SECURITY_DATE_PCT=100.000000%", "MAX_UNKNOWN_PORTFOLIO_WEIGHT=100.000000%", "",
        "TEMPORAL_SIC_CHANGE_COUNT=NOT_APPLICABLE:NO_PIT_SIC_ROWS",
        "FUTURE_FILING_VIOLATION_COUNT=0", "",
        "TAXONOMY_FREEZE_STATUS=NOT_FROZEN_COVERAGE_GATE_FAIL",
        "PRIMARY_TAXONOMY_HASH=NOT_APPLICABLE", "SECONDARY_TAXONOMY_HASH=NOT_APPLICABLE", "",
        "-" * 60, "RAW A2 CONCENTRATION", "-" * 60, "",
        f"RAW_CAGR={raw['cagr']:.12g}", f"RAW_SHARPE={raw['sharpe']:.12g}", f"RAW_MAXDD={raw['max_drawdown']:.12g}", "",
        "RAW_FF12_HHI=NOT_APPLICABLE:NO_VALID_TAXONOMY", "RAW_FF12_MAX_WEIGHT=NOT_APPLICABLE:NO_VALID_TAXONOMY",
        "RAW_FF12_EFFECTIVE_COUNT=NOT_APPLICABLE:NO_VALID_TAXONOMY", "RAW_TOP_FF12_CATEGORY=NOT_APPLICABLE", "",
        "RAW_FF48_HHI=NOT_APPLICABLE:NO_VALID_TAXONOMY", "RAW_FF48_MAX_WEIGHT=NOT_APPLICABLE:NO_VALID_TAXONOMY",
        "RAW_FF48_EFFECTIVE_COUNT=NOT_APPLICABLE:NO_VALID_TAXONOMY", "RAW_TOP_FF48_CATEGORY=NOT_APPLICABLE", "",
        "-" * 60, "RESEARCH", "-" * 60, "", "TOTAL_TRIALS=0", "SUCCESSFUL_TRIALS=0", "FAILED_TRIALS=0", "",
        "MODEL_FAMILIES_EXPLORED=NONE_TAXONOMY_GATE_BLOCKED", "FACTOR_FAMILIES_EXPLORED=NONE_TAXONOMY_GATE_BLOCKED",
        "SECTOR_METHODS_EXPLORED=NONE_TAXONOMY_GATE_BLOCKED", "", "FINALIST_COUNT=0",
        "FINALISTS_FROZEN_BEFORE_2025_READ=TRUE_EMPTY_FREEZE", "", "PRIMARY_CHALLENGER=NONE",
        "PRIMARY_CLASSIFICATION=NO_ROBUST_VALUE_TAXONOMY_GATE_FAIL", "", "-" * 60, "PRIMARY CHALLENGER", "-" * 60, "",
        "CHALLENGER_FAMILY=NOT_APPLICABLE", "CHALLENGER_METHOD=NOT_APPLICABLE", "",
        "CHALLENGER_CAGR=NOT_APPLICABLE", "CHALLENGER_SHARPE=NOT_APPLICABLE", "CHALLENGER_MAXDD=NOT_APPLICABLE",
        "CHALLENGER_QQQ_BETA=NOT_APPLICABLE", "CHALLENGER_RESIDUAL_SHARPE=NOT_APPLICABLE", "",
        "CHALLENGER_FF12_HHI=NOT_APPLICABLE", "FF12_HHI_REDUCTION_PCT=NOT_APPLICABLE",
        "CHALLENGER_FF12_MAX_WEIGHT=NOT_APPLICABLE", "CHALLENGER_FF12_EFFECTIVE_COUNT=NOT_APPLICABLE", "",
        "CHALLENGER_FF48_HHI=NOT_APPLICABLE", "FF48_HHI_REDUCTION_PCT=NOT_APPLICABLE",
        "CHALLENGER_FF48_MAX_WEIGHT=NOT_APPLICABLE", "CHALLENGER_FF48_EFFECTIVE_COUNT=NOT_APPLICABLE", "",
        "CHALLENGER_TURNOVER=NOT_APPLICABLE", "CHALLENGER_COST=NOT_APPLICABLE", "",
        "-" * 60, "TEMPORAL ROBUSTNESS", "-" * 60, "", "2023_CLASSIFICATION=NOT_EXECUTED_TAXONOMY_GATE",
        "2024_CLASSIFICATION=NOT_EXECUTED_TAXONOMY_GATE", "2025_CONFIRMATION=NOT_READ_FOR_CANDIDATES_NO_FINALISTS", "",
        "PARAMETER_NEEDLE_WARNING=NOT_APPLICABLE_NO_TRIALS", "SINGLE_PERIOD_DEPENDENCE=NOT_APPLICABLE_NO_TRIALS", "",
        "-" * 60, "R6", "-" * 60, "", "R6_DIAGNOSTIC_STATUS=NOT_APPLICABLE:NO_FINALISTS", "",
        "-" * 60, "GOVERNANCE", "-" * 60, "", "MAX_TRAIN_DATE=NOT_APPLICABLE:NO_TRAINING",
        "MAX_SELECTION_DATE=NOT_APPLICABLE:NO_SELECTION", "", "2026_OUTCOME_USED=FALSE", "2026_LEAKAGE_COUNT=0", "",
        "ANTI_OVERFIT_STATUS=PASS_FAIL_CLOSED_BEFORE_CANDIDATE_SEARCH",
        "ANTI_BLOAT_STATUS=FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_1", "",
        "-" * 60, "VERDICT", "-" * 60, "", "DOES_ROBUST_SECTOR_DECONCENTRATION_EXIST=NOT_ESTABLISHED_TAXONOMY_GATE_FAIL", "",
        "MOST_DAMAGING_EVIDENCE=Official filing-time SEC SIC payloads could not be acquired; 100% of security-dates remain UNKNOWN.",
        "STRONGEST_SUPPORTING_EVIDENCE=Raw A2 exact reconciliation and an unpolluted zero-trial research contract were preserved.", "",
        "RECOMMENDED_SINGLE_NEXT_STEP=STAGE_OFFICIAL_SEC_QUARTERLY_SUBMISSION_DATA_AND_IDENTITY_BRIDGE_THEN_RERUN_SAME_CONTRACT", "",
        f"OUTPUT_DIR={OUT}", f"FINAL_ARTIFACT_COUNT={len(FINAL_FILES)}", "HASH_MANIFEST_STATUS=PASS_HASH_VERIFIED", "", "=" * 60,
    ]
    print("\n".join(fields))


def run() -> dict[str, Any]:
    for path, expected in EXPECTED.items():
        require(path.is_file() and sha256_file(path) == expected, "AUTHORITATIVE_HASH_FAILURE", path)
    upstream = json.loads((UPSTREAM / "robustness_classification.json").read_text(encoding="utf-8"))
    prior = json.loads((PRIOR / "research_metadata.json").read_text(encoding="utf-8"))
    require(upstream["historical_path_authority"] == "PASS", "RAW_PATH_AUTHORITY_FAILURE")
    require(prior["total_trials"] == 0 and prior["outcome_2026_read_count"] == 0, "PRIOR_CONTRACT_POLLUTED")

    portfolio = pd.read_parquet(PORTFOLIO).sort_values("execution_date").reset_index(drop=True)
    portfolio["execution_date"] = pd.to_datetime(portfolio.execution_date).dt.normalize()
    require(portfolio.execution_date.max() < pd.Timestamp("2026-01-01"), "2026_PORTFOLIO_READ")
    raw = performance(portfolio.reconstructed_daily_return.to_numpy(float))
    for key in ("cumulative_return", "cagr", "sharpe", "max_drawdown"):
        require(abs(raw[key] - upstream["baseline"][key]) <= 1e-12, "RAW_RECONCILIATION", key)

    top = pd.read_parquet(TOP20, columns=["signal_date", "ticker"])
    top["signal_date"] = pd.to_datetime(top.signal_date).dt.normalize()
    top["ticker"] = top.ticker.astype(str).str.upper()
    require(top.signal_date.max() < pd.Timestamp("2026-01-01"), "2026_TOP20_READ")
    require(top.groupby("signal_date").size().eq(20).all(), "TOP20_CONTRACT_FAILURE")
    tickers = set(top.ticker)

    identity = pd.read_csv(IDENTITY_LEDGER, dtype=str, usecols=["security_id", "ticker"])
    identity["ticker"] = identity.ticker.astype(str).str.upper()
    matched = identity[identity.ticker.isin(tickers)].dropna(subset=["security_id"])
    conflicts = int(matched.groupby("ticker").security_id.nunique().gt(1).sum())
    mapped = int(matched.ticker.nunique())
    require(conflicts == 0, "SECURITY_ID_CONFLICT")

    contract = {
        "task_id": "A2_PIT_SECTOR_TAXONOMY_AND_DECONCENTRATION_RESUME_R1",
        "status": "NOT_FROZEN_COVERAGE_GATE_FAIL",
        "primary_taxonomy": "FAMA_FRENCH_12_FROM_PIT_SEC_SIC",
        "secondary_taxonomy": "FAMA_FRENCH_48_FROM_PIT_SEC_SIC",
        "pit_rule": "latest valid filing SIC with SEC acceptance_timestamp <= authoritative information cutoff",
        "backward_fill_forbidden": True, "current_sic_backfill_forbidden": True,
        "unknown_security_date_pct_limit": 0.01, "unknown_weight_limit": 0.05,
        "information_to_execution_join": "authoritative signal/information date mapped to execution calendar; no same-day assumption",
        "official_sources": SEC_SOURCES,
        "mapping_source": "Kenneth French standard FF12/FF48 SIC definitions; not acquired because upstream PIT SIC gate failed",
        "outcome_independent": True, "static_mapping": True,
        "legacy_recovery_passes": 2,
        "legacy_table_headers_checked": 909,
        "legacy_taxonomy_row_count": 0,
        "official_acquisition_attempts": [
            {"channel": "canonical_python_https", "status": "BLOCKED_CONNECTION_REFUSED_WINERROR_10061"},
            {"channel": "web_official_sec_zip", "status": "BLOCKED_UNSUPPORTED_CONTENT_TYPE_APPLICATION_OCTET_STREAM"},
            {"channel": "in_app_browser_download", "status": "BLOCKED_BROWSER_RUNTIME_UNAVAILABLE"},
        ],
        "taxonomy_mutation_forbidden_after_freeze": True,
        "selection_windows": [2023, 2024], "confirmation_window": 2025,
        "max_successful_candidates": 2500, "max_finalists": 5,
        "2026_outcome_allowed": False,
    }
    finalist_payload = {
        "task_id": contract["task_id"], "freeze_status": "EMPTY_FREEZE_TAXONOMY_GATE_FAIL",
        "finalists": [], "finalist_count": 0, "candidate_2025_outcome_read_count": 0,
        "outcome_2026_read_count": 0, "payload_sha256": "",
    }
    finalist_payload["payload_sha256"] = canonical_hash({k: v for k, v in finalist_payload.items() if k != "payload_sha256"})
    folds = raw_folds(portfolio)
    metadata = {
        "task_id": contract["task_id"],
        "task_status": "FAIL_CLOSED_TAXONOMY_COVERAGE_MATERIALLY_INSUFFICIENT",
        "taxonomy_recovery_path": "PATH_1_EXHAUSTED_THEN_PATH_2_OFFICIAL_SEC_ACQUISITION_BLOCKED",
        "legacy_taxonomy_recovered": False,
        "primary_taxonomy": contract["primary_taxonomy"], "secondary_taxonomy": contract["secondary_taxonomy"],
        "taxonomy_freeze_status": contract["status"], "primary_taxonomy_hash": None, "secondary_taxonomy_hash": None,
        "a2_unique_securities": len(tickers), "a2_security_dates": len(top),
        "security_id_mapped_securities": mapped, "security_id_mapping_coverage": mapped / len(tickers),
        "security_id_conflict_count": conflicts, "cik_mapped_securities": 0, "sic_mapped_securities": 0,
        "ff12_security_date_coverage": 0.0, "ff48_security_date_coverage": 0.0,
        "unknown_security_date_pct": 1.0, "max_unknown_portfolio_weight": 1.0,
        "temporal_sic_change_count": None, "future_filing_violation_count": 0,
        "raw_a2_reconciliation": "PASS_EXACT_1E-12", "raw_baseline": raw,
        "raw_date_range": [portfolio.execution_date.min().date().isoformat(), portfolio.execution_date.max().date().isoformat()],
        "total_trials": 0, "successful_trials": 0, "failed_trials": 0,
        "model_fit_count": 0, "factor_construction_count": 0, "parameter_selection_count": 0,
        "candidate_2025_outcome_read_count": 0, "outcome_2026_read_count": 0,
        "finalist_count": 0, "primary_challenger": "NONE", "r6_diagnostic_status": "NOT_APPLICABLE:NO_FINALISTS",
        "max_train_date": None, "max_selection_date": None,
        "anti_overfit_status": "PASS_FAIL_CLOSED_BEFORE_CANDIDATE_SEARCH",
        "anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_1",
        "canonical_write_count": 0, "broker_action_count": 0, "new_dependency_count": 0,
        "taxonomy_contract_sha256": canonical_hash(contract),
        "minimum_unblocker": "OFFICIAL_SEC_QUARTERLY_SUBMISSION_SIC_DATA_PLUS_AUDITABLE_IDENTITY_BRIDGE",
    }

    OUT.mkdir(parents=True, exist_ok=False)
    write_json(OUT / "taxonomy_contract.json", contract)
    write_json(OUT / "finalist_freeze.json", finalist_payload)
    folds.to_csv(OUT / "fold_results.csv", index=False, encoding="utf-8-sig")
    write_json(OUT / "research_metadata.json", metadata)
    (OUT / "final_report.md").write_text(render_report(metadata, contract, folds), encoding="utf-8")
    artifacts = [
        {"name": name, "sha256": sha256_file(OUT / name), "bytes": (OUT / name).stat().st_size}
        for name in FINAL_FILES if name != "hash_manifest.json"
    ]
    write_json(OUT / "hash_manifest.json", {
        "task_id": contract["task_id"], "status": "PASS_HASH_VERIFIED",
        "artifact_count_including_manifest": len(FINAL_FILES), "artifacts": artifacts,
        "authoritative_input_hashes": {str(path): digest for path, digest in EXPECTED.items()},
        "taxonomy_contract_sha256": canonical_hash(contract), "task_source_sha256": sha256_file(Path(__file__)),
        "canonical_data_read_only": True, "2026_outcome_used": False,
    })
    require(len([path for path in OUT.iterdir() if path.is_file()]) == len(FINAL_FILES), "ARTIFACT_COUNT")
    terminal(metadata)
    return metadata


if __name__ == "__main__":
    run()
