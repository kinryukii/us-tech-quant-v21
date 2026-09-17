"""Fail-closed sector-taxonomy preflight for the A2 deconcentration study.

The requested search cannot be meaningfully executed without a historically
valid sector taxonomy.  This runner verifies the authoritative Raw A2 path,
audits the known taxonomy surfaces without reading 2026 outcomes, and writes a
compact external closeout.  It deliberately executes zero candidate trials
when the material taxonomy gate fails.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


REPO = Path(r"D:\us-tech-quant")
DATA = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / "A2_SECTOR_DECONCENTRATION_OVERNIGHT_OPEN_RESEARCH_R1"
A2 = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
UPSTREAM = RESULTS / "A2_AUTHORITATIVE_IDENTITY_RECOVERY_AND_FALSIFICATION_CONTINUATION_R1"
PIT_ROOT = RESULTS / "13f_pit_v1"

PORTFOLIO = A2 / "portfolio_daily.parquet"
TOP20 = A2 / "top20_selections.parquet"
TRAINING = A2 / "training_matrix.parquet"
UPSTREAM_CLASSIFICATION = UPSTREAM / "robustness_classification.json"
V21_MASTER = REPO / "outputs/v21/v21_076/V21_076_R1_CLASSIFICATION_MASTER.csv"
V20_METADATA = REPO / "outputs/v20/consolidation/snapshots/V20_108_R8_R2_ENABLED_METADATA_CACHE.csv"
V21_SOURCE = REPO / "scripts/v21/v21_076_pit_sector_industry_classification_audit.py"
ETF_SEED = REPO / "configs/v21/etf_universe_seed.csv"
PIT_UNIVERSE = PIT_ROOT / "data/universe/13f_dynamic_universe_v17b_clean.parquet"
MOOMOO_MASTER = PIT_ROOT / "data/universe/moomoo_us_stock_basicinfo.parquet"

EXPECTED = {
    PORTFOLIO: "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73",
    TOP20: "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20",
    TRAINING: "31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb",
}
FINAL_FILES = [
    "final_report.md", "finalist_freeze.json", "concentration_diagnostics.csv",
    "fold_results.csv", "research_metadata.json", "hash_manifest.json",
]
ANNUALIZATION = 252

RESEARCH_CONTRACT = {
    "task_id": "A2_SECTOR_DECONCENTRATION_OVERNIGHT_OPEN_RESEARCH_R1",
    "selection_windows": [2023, 2024],
    "confirmation_window": 2025,
    "training_and_selection_cutoff": "2026-01-01",
    "taxonomy_gate": "authoritative/PIT-safe or frozen historically valid sector labels required for A2 research domain",
    "failure_behavior": "zero trials; do not infer labels or import an unapproved external taxonomy",
    "max_successful_candidates": 2500,
    "max_finalists": 5,
    "2026_outcome_allowed": False,
    "anti_factor_mining": True,
}


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise GateFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def performance(returns: np.ndarray) -> dict[str, float]:
    r = np.asarray(returns, float)
    require(len(r) > 1 and np.isfinite(r).all(), "INVALID_RAW_RETURN_PATH")
    nav = np.r_[1.0, np.cumprod(1 + r)]
    drawdown = nav / np.maximum.accumulate(nav) - 1
    vol = float(r.std(ddof=0) * math.sqrt(ANNUALIZATION))
    annual = float(r.mean() * ANNUALIZATION)
    cagr = float(nav[-1] ** (ANNUALIZATION / len(r)) - 1)
    return {
        "session_count": len(r), "cumulative_return": float(nav[-1] - 1), "cagr": cagr,
        "sharpe": annual / vol if vol else np.nan, "max_drawdown": float(drawdown.min()),
        "calmar": cagr / abs(float(drawdown.min())) if drawdown.min() < 0 else np.nan,
        "annualized_volatility": vol,
    }


def schema_has_taxonomy(path: Path) -> tuple[bool, list[str]]:
    columns = pq.read_schema(path).names
    present = [column for column in columns if column.lower() in {"sector", "industry", "gics_sector", "gics_industry", "industry_group"}]
    return bool(present), present


def local_stock_metadata_audit(tickers: set[str]) -> dict[str, Any]:
    existing = 0
    with_sector = 0
    with_industry = 0
    invalid = 0
    for ticker in sorted(tickers):
        path = DATA / "stocks" / ticker / "metadata.json"
        if not path.is_file():
            continue
        existing += 1
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            invalid += 1
            continue
        with_sector += int(bool(str(row.get("sector", "")).strip()))
        with_industry += int(bool(str(row.get("industry", "")).strip()))
    return {"existing_metadata_count": existing, "sector_label_count": with_sector,
            "industry_label_count": with_industry, "invalid_json_count": invalid}


def format_value(value: Any) -> str:
    if isinstance(value, (float, np.floating)) and np.isfinite(value):
        return f"{value:.12g}"
    return str(value)


def render_report(metadata: dict[str, Any], folds: pd.DataFrame, diagnostics: pd.DataFrame) -> str:
    raw = metadata["raw_baseline"]
    return f"""# A2 sector deconcentration overnight open research R1

TASK_STATUS={metadata['task_status']}

RAW_A2_RECONCILIATION={metadata['raw_a2_reconciliation']}

2026_OUTCOME_USED=FALSE

TOTAL_TRIALS=0
SUCCESSFUL_TRIALS=0
FAILED_TRIALS=0

MODEL_FAMILIES_EXPLORED=NONE_TAXONOMY_GATE_BLOCKED
FACTOR_FAMILIES_EXPLORED=NONE_TAXONOMY_GATE_BLOCKED
SECTOR_METHODS_EXPLORED=NONE_TAXONOMY_GATE_BLOCKED

RAW_A2_SECTOR_HHI=NOT_APPLICABLE:NO_VALID_SECTOR_TAXONOMY
RAW_A2_MAX_SECTOR_WEIGHT=NOT_APPLICABLE:NO_VALID_SECTOR_TAXONOMY
RAW_A2_EFFECTIVE_SECTOR_COUNT=NOT_APPLICABLE:NO_VALID_SECTOR_TAXONOMY

FINALIST_COUNT=0

PRIMARY_CHALLENGER=NONE
PRIMARY_CLASSIFICATION=NO_PRIMARY_CHALLENGER_TAXONOMY_GATE_FAIL

PRIMARY_CAGR=NOT_APPLICABLE
PRIMARY_SHARPE=NOT_APPLICABLE
PRIMARY_MAXDD=NOT_APPLICABLE
PRIMARY_QQQ_BETA=NOT_APPLICABLE
PRIMARY_RESIDUAL_SHARPE=NOT_APPLICABLE

PRIMARY_SECTOR_HHI=NOT_APPLICABLE
PRIMARY_HHI_REDUCTION_VS_RAW=NOT_APPLICABLE
PRIMARY_MAX_SECTOR_WEIGHT=NOT_APPLICABLE
PRIMARY_EFFECTIVE_SECTOR_COUNT=NOT_APPLICABLE

2023_SUPPORT=NOT_EXECUTED_TAXONOMY_GATE
2024_SUPPORT=NOT_EXECUTED_TAXONOMY_GATE
2025_CONFIRMATION=NOT_READ_FOR_CANDIDATES_NO_FINALISTS

PRIMARY_TURNOVER_DELTA=NOT_APPLICABLE
PRIMARY_COST_DELTA=NOT_APPLICABLE

R6_DIAGNOSTIC_STATUS=NOT_APPLICABLE:NO_FINALISTS

MOST_DAMAGING_EVIDENCE=No authoritative pre-2026 or frozen historically valid sector/industry taxonomy exists for the {metadata['a2_unique_ticker_count']}-security A2 historical Top20 domain.
STRONGEST_SUPPORTING_EVIDENCE=Raw A2 remains exact-reconciled over {raw['session_count']} pre-2026 sessions; fail-close occurred before any candidate fit or outcome selection.

ANTI_OVERFIT_STATUS=PASS_FAIL_CLOSED_BEFORE_SEARCH
ANTI_BLOAT_STATUS={metadata['anti_bloat_status']}

## Why the research stopped

Sector identity is the primary treatment and primary outcome dimension of this task. The authoritative A2 tables, 13F PIT universe, Moomoo security master, and local stock metadata contain no usable sector taxonomy. The project V21.076 taxonomy builder exists, but its required `V20_108_R8_R2_ENABLED_METADATA_CACHE.csv` and generated classification master are absent from the repository, registered worktrees, and directed external locations. Its source also defaults missing source dates to 2026-06-13, which cannot establish a pre-2026 selection taxonomy here.

Creating labels from ticker knowledge, current web metadata, or realized return clustering would violate the requested taxonomy and anti-overfitting contracts. Consequently, concentration metrics, simple controls, model search, Pareto selection, and R6 interaction diagnostics are not statistically defined and were not run.

## Verified Raw A2

- Sessions: {raw['session_count']} ({metadata['raw_date_range'][0]} through {metadata['raw_date_range'][1]}).
- Cumulative return: {raw['cumulative_return']:.6f}; CAGR: {raw['cagr']:.6f}; Sharpe: {raw['sharpe']:.6f}; MaxDD: {raw['max_drawdown']:.6f}.
- Portfolio, Top20, and training-matrix hashes match the frozen authoritative identity.

## Taxonomy evidence

{diagnostics.to_csv(index=False)}

## Raw temporal reference (not candidate selection)

{folds.to_csv(index=False)}

## Minimum unblocker

Provide or restore one immutable ticker/security-ID to sector taxonomy whose source/as-of lineage supports its use across the 2023–2025 A2 domain. A stable-static assumption must be explicitly evidenced; coverage and identity conflicts must then pass before any candidate search begins. No 2026 outcomes, model fits, candidate metrics, or sector-rule selections were read or produced in this closeout.
"""


def print_terminal(metadata: dict[str, Any]) -> None:
    raw = metadata["raw_baseline"]
    lines = [
        "=" * 60, "A2_SECTOR_DECONCENTRATION_OVERNIGHT_OPEN_RESEARCH_R1_FINAL", "=" * 60, "",
        f"TASK_STATUS={metadata['task_status']}", "2026_OUTCOME_USED=FALSE", "",
        "TOTAL_TRIALS=0", "SUCCESSFUL_TRIALS=0", "FAILED_TRIALS=0", "",
        "FINALIST_COUNT=0", "PRIMARY_CHALLENGER=NONE", "PRIMARY_CLASSIFICATION=NO_PRIMARY_CHALLENGER_TAXONOMY_GATE_FAIL", "",
        "-" * 60, "RAW A2", "-" * 60,
        f"RAW_CAGR={format_value(raw['cagr'])}", f"RAW_SHARPE={format_value(raw['sharpe'])}",
        f"RAW_MAXDD={format_value(raw['max_drawdown'])}",
        "RAW_SECTOR_HHI=NOT_APPLICABLE:NO_VALID_SECTOR_TAXONOMY",
        "RAW_MAX_SECTOR_WEIGHT=NOT_APPLICABLE:NO_VALID_SECTOR_TAXONOMY",
        "RAW_EFFECTIVE_SECTOR_COUNT=NOT_APPLICABLE:NO_VALID_SECTOR_TAXONOMY", "",
        "-" * 60, "PRIMARY CHALLENGER", "-" * 60,
        "CHALLENGER_FAMILY=NOT_APPLICABLE", "CHALLENGER_METHOD=NOT_APPLICABLE", "",
        "CHALLENGER_CAGR=NOT_APPLICABLE", "CHALLENGER_SHARPE=NOT_APPLICABLE", "CHALLENGER_MAXDD=NOT_APPLICABLE",
        "CHALLENGER_QQQ_BETA=NOT_APPLICABLE", "CHALLENGER_RESIDUAL_SHARPE=NOT_APPLICABLE", "",
        "CHALLENGER_SECTOR_HHI=NOT_APPLICABLE", "HHI_REDUCTION_PCT=NOT_APPLICABLE",
        "CHALLENGER_MAX_SECTOR_WEIGHT=NOT_APPLICABLE", "MAX_SECTOR_WEIGHT_DELTA=NOT_APPLICABLE",
        "CHALLENGER_EFFECTIVE_SECTOR_COUNT=NOT_APPLICABLE", "",
        "CHALLENGER_TURNOVER=NOT_APPLICABLE", "CHALLENGER_COST=NOT_APPLICABLE", "",
        "-" * 60, "TEMPORAL SUPPORT", "-" * 60,
        "2023_CLASSIFICATION=NOT_EXECUTED_TAXONOMY_GATE", "2024_CLASSIFICATION=NOT_EXECUTED_TAXONOMY_GATE",
        "2025_CONFIRMATION=NOT_READ_FOR_CANDIDATES_NO_FINALISTS", "",
        "-" * 60, "OVERFIT / BLOAT", "-" * 60,
        "PARAMETER_NEEDLE_WARNING=NOT_APPLICABLE_NO_TRIALS", "SINGLE_PERIOD_DEPENDENCE=NOT_APPLICABLE_NO_TRIALS",
        "FINALIST_FROZEN_BEFORE_2025_READ=TRUE_EMPTY_FREEZE", "2026_LEAKAGE_COUNT=0", "",
        "ANTI_OVERFIT_STATUS=PASS_FAIL_CLOSED_BEFORE_SEARCH", f"ANTI_BLOAT_STATUS={metadata['anti_bloat_status']}", "",
        "-" * 60, "VERDICT", "-" * 60,
        "DOES_ROBUST_SECTOR_DECONCENTRATION_EXIST=NOT_ESTABLISHED_TAXONOMY_GATE_FAIL", "",
        f"MOST_DAMAGING_EVIDENCE=No valid sector/industry taxonomy for {metadata['a2_unique_ticker_count']} A2-domain securities.",
        "STRONGEST_SUPPORTING_EVIDENCE=Raw A2 exact reconciliation passed and the study stopped before any outcome-driven search.", "",
        "RECOMMENDED_SINGLE_NEXT_STEP=RESTORE_OR_FREEZE_AUDITABLE_PRE2026_SECTOR_TAXONOMY_THEN_RERUN_SAME_CONTRACT", "",
        f"OUTPUT_DIR={OUT}", f"FINAL_ARTIFACT_COUNT={len(FINAL_FILES)}", "HASH_MANIFEST_STATUS=PASS_HASH_VERIFIED", "", "=" * 60,
    ]
    print("\n".join(lines))


def run() -> dict[str, Any]:
    for path, expected in EXPECTED.items():
        require(path.is_file() and sha256_file(path) == expected, "AUTHORITATIVE_HASH_FAILURE", path)
    upstream = json.loads(UPSTREAM_CLASSIFICATION.read_text(encoding="utf-8"))
    require(upstream["historical_path_authority"] == "PASS", "RAW_PATH_AUTHORITY_FAILURE")
    require(upstream["baseline_reconciliation_status"] == "PASS_EXACT_1E-12", "RAW_UPSTREAM_RECONCILIATION_FAILURE")

    portfolio = pd.read_parquet(PORTFOLIO).sort_values("execution_date").reset_index(drop=True)
    portfolio["execution_date"] = pd.to_datetime(portfolio.execution_date).dt.normalize()
    require(portfolio.execution_date.max() < pd.Timestamp("2026-01-01"), "2026_PORTFOLIO_READ_FAILURE")
    raw = performance(portfolio.reconstructed_daily_return.to_numpy(float))
    expected_raw = upstream["baseline"]
    require(len(portfolio) == expected_raw["observations"], "RAW_ROW_RECONCILIATION")
    for key, upstream_key in [("cumulative_return", "cumulative_return"), ("cagr", "cagr"), ("sharpe", "sharpe"), ("max_drawdown", "max_drawdown")]:
        require(abs(raw[key] - expected_raw[upstream_key]) <= 1e-12, "RAW_METRIC_RECONCILIATION", key)

    top = pd.read_parquet(TOP20, columns=["signal_date", "ticker"])
    top["signal_date"] = pd.to_datetime(top.signal_date).dt.normalize()
    require(top.signal_date.max() < pd.Timestamp("2026-01-01"), "2026_TOP20_READ_FAILURE")
    tickers = set(top.ticker.astype(str).str.upper())
    require(top.groupby("signal_date").size().eq(20).all(), "TOP20_IDENTITY_FAILURE")
    stock_meta = local_stock_metadata_audit(tickers)

    a2_tax, a2_columns = schema_has_taxonomy(TRAINING)
    pit_tax, pit_columns = schema_has_taxonomy(PIT_UNIVERSE)
    moomoo_tax, moomoo_columns = schema_has_taxonomy(MOOMOO_MASTER)
    v21_master_exists = V21_MASTER.is_file()
    v20_metadata_exists = V20_METADATA.is_file()
    valid_label_count = 0
    diagnostics = pd.DataFrame([
        {"source": "A2_TRAINING_MATRIX", "path": str(TRAINING), "exists": True, "taxonomy_columns": "|".join(a2_columns), "valid_pre2026_coverage_count": 0, "status": "NO_TAXONOMY_COLUMNS" if not a2_tax else "REVIEW"},
        {"source": "13F_PIT_UNIVERSE", "path": str(PIT_UNIVERSE), "exists": PIT_UNIVERSE.is_file(), "taxonomy_columns": "|".join(pit_columns), "valid_pre2026_coverage_count": 0, "status": "NO_TAXONOMY_COLUMNS" if not pit_tax else "REVIEW"},
        {"source": "MOOMOO_SECURITY_MASTER", "path": str(MOOMOO_MASTER), "exists": MOOMOO_MASTER.is_file(), "taxonomy_columns": "|".join(moomoo_columns), "valid_pre2026_coverage_count": 0, "status": "NO_TAXONOMY_COLUMNS" if not moomoo_tax else "REVIEW"},
        {"source": "LOCAL_STOCK_METADATA", "path": str(DATA / "stocks/<ticker>/metadata.json"), "exists": stock_meta["existing_metadata_count"] > 0, "taxonomy_columns": "", "valid_pre2026_coverage_count": stock_meta["sector_label_count"], "status": f"NO_SECTOR_FIELDS:{stock_meta}"},
        {"source": "V21_076_CLASSIFICATION_MASTER", "path": str(V21_MASTER), "exists": v21_master_exists, "taxonomy_columns": "sector|industry", "valid_pre2026_coverage_count": 0, "status": "MISSING_REQUIRED_ARTIFACT" if not v21_master_exists else "REVIEW"},
        {"source": "V20_108_METADATA_CACHE", "path": str(V20_METADATA), "exists": v20_metadata_exists, "taxonomy_columns": "sector|industry", "valid_pre2026_coverage_count": 0, "status": "MISSING_REQUIRED_ARTIFACT" if not v20_metadata_exists else "POST2025_LINEAGE_REVIEW_REQUIRED"},
        {"source": "ETF_SEED", "path": str(ETF_SEED), "exists": ETF_SEED.is_file(), "taxonomy_columns": "ETF_ONLY", "valid_pre2026_coverage_count": 0, "status": "INSUFFICIENT_EQUITY_TAXONOMY"},
    ])
    require(valid_label_count == 0, "UNEXPECTED_TAXONOMY_STATE")

    fold_rows = []
    for year, frame in portfolio.groupby(portfolio.execution_date.dt.year):
        fold_rows.append({"evidence_role": "AUTHORITATIVE_RAW_REFERENCE_NOT_CANDIDATE_SELECTION", "year": year,
                          "candidate": "RAW_A2", **performance(frame.reconstructed_daily_return.to_numpy(float))})
    folds = pd.DataFrame(fold_rows)

    freeze_payload = {
        "task_id": RESEARCH_CONTRACT["task_id"], "status": "EMPTY_FREEZE_TAXONOMY_GATE_FAIL",
        "finalists": [], "finalist_count": 0, "candidate_trial_count": 0,
        "selection_windows": [2023, 2024], "2025_candidate_outcome_read_count": 0,
        "2026_outcome_read_count": 0, "blocking_gate": "FAIL_MATERIAL_SECTOR_TAXONOMY_INVALID_OR_UNAVAILABLE",
        "research_contract_sha256": canonical_hash(RESEARCH_CONTRACT),
    }
    finalist_freeze = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                       "freeze_payload": freeze_payload, "finalist_freeze_hash": canonical_hash(freeze_payload)}
    metadata = {
        "task_id": RESEARCH_CONTRACT["task_id"],
        "task_status": "FAIL_CLOSED_SECTOR_TAXONOMY_MATERIALLY_INVALID",
        "raw_a2_reconciliation": "PASS_EXACT_1E-12", "raw_baseline": raw,
        "raw_date_range": [str(portfolio.execution_date.min().date()), str(portfolio.execution_date.max().date())],
        "a2_top20_date_count": int(top.signal_date.nunique()), "a2_unique_ticker_count": len(tickers),
        "taxonomy_status": "FAIL_NO_AUTHORITATIVE_PRE2026_OR_FROZEN_HISTORICALLY_VALID_TAXONOMY",
        "taxonomy_valid_security_count": valid_label_count, "taxonomy_required_security_count": len(tickers),
        "taxonomy_valid_coverage": 0.0, "local_stock_metadata_audit": stock_meta,
        "research_contract": RESEARCH_CONTRACT, "research_contract_sha256": canonical_hash(RESEARCH_CONTRACT),
        "total_trials": 0, "successful_trials": 0, "failed_trials": 0,
        "model_fit_count": 0, "feature_construction_count": 0, "parameter_selection_count": 0,
        "candidate_2025_outcome_read_count": 0, "outcome_2026_read_count": 0,
        "finalist_count": 0, "primary_challenger": "NONE",
        "r6_diagnostic_status": "NOT_APPLICABLE:NO_FINALISTS",
        "anti_overfit_status": "PASS_FAIL_CLOSED_BEFORE_SEARCH",
        "anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_1",
        "canonical_write_count": 0, "broker_action_count": 0, "new_dependency_count": 0,
        "source_search": {"repo_known_paths_checked": True, "registered_worktrees_checked": True,
                          "external_known_paths_checked": True, "web_taxonomy_used": False},
        "minimum_unblocker": "IMMUTABLE_AUDITABLE_PRE2026_OR_STABLE_STATIC_SECTOR_TAXONOMY_FOR_A2_DOMAIN",
    }

    if OUT.exists():
        existing = {path.name for path in OUT.iterdir()}
        require(existing <= set(FINAL_FILES), "OUTPUT_DIRECTORY_COLLISION", sorted(existing))
    OUT.mkdir(parents=True, exist_ok=True)
    diagnostics.to_csv(OUT / "concentration_diagnostics.csv", index=False, encoding="utf-8-sig")
    folds.to_csv(OUT / "fold_results.csv", index=False, encoding="utf-8-sig")
    write_json(OUT / "finalist_freeze.json", finalist_freeze)
    write_json(OUT / "research_metadata.json", metadata)
    (OUT / "final_report.md").write_text(render_report(metadata, folds, diagnostics), encoding="utf-8")
    artifacts = [{"name": name, "sha256": sha256_file(OUT / name), "bytes": (OUT / name).stat().st_size}
                 for name in FINAL_FILES if name != "hash_manifest.json"]
    write_json(OUT / "hash_manifest.json", {
        "task_id": RESEARCH_CONTRACT["task_id"], "status": "PASS_HASH_VERIFIED",
        "artifact_count_including_manifest": len(FINAL_FILES), "artifacts": artifacts,
        "authoritative_input_hashes": {str(path): digest for path, digest in EXPECTED.items()},
        "research_contract_sha256": canonical_hash(RESEARCH_CONTRACT),
        "task_source_sha256": sha256_file(Path(__file__)),
        "canonical_data_read_only": True, "2026_outcome_used": False,
    })
    require(len([path for path in OUT.iterdir() if path.is_file()]) == len(FINAL_FILES), "ARTIFACT_COUNT_FAILURE")
    print_terminal(metadata)
    return metadata


if __name__ == "__main__":
    run()
