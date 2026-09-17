from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_ID = "A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / RUN_ID
SCRIPT = REPO / "scripts" / "v22" / Path(__file__).name
PRIOR_2026_OUTCOME_ROOT = RESULTS / "A_A2_2026_PRE_RISK_HOLDOUT_R1"
R1A = RESULTS / "A2_ALGORITHM_BENCHMARK_R1A_TEMPORAL_BASELINE_RECONSTRUCTION"
R1C = RESULTS / "A2_ALGORITHM_BENCHMARK_R1C_REGIME_FORENSIC_AND_RANKING_REPAIR"
R1D = RESULTS / "A2_ALGORITHM_BENCHMARK_R1D_STATIC_BLEND"
HGB = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "final_full_pre2026_hgb.joblib"
XGB_LATEST_OUTER = Path(
    r"D:\us-tech-quant-cache\a2_algorithm_benchmark_r1a_temporal_baseline_reconstruction"
    r"\models\M2_XGB_REG_OUTER_2025.joblib"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def utc_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def outcome_metadata_only() -> list[dict[str, Any]]:
    if not PRIOR_2026_OUTCOME_ROOT.is_dir():
        return []
    rows = []
    for path in sorted(PRIOR_2026_OUTCOME_ROOT.iterdir(), key=lambda item: item.name):
        if path.is_file():
            stat = path.stat()
            rows.append(
                {
                    "name": path.name,
                    "bytes": stat.st_size,
                    "created_utc": utc_from_epoch(stat.st_ctime),
                    "modified_utc": utc_from_epoch(stat.st_mtime),
                    "content_read": False,
                }
            )
    return rows


def main() -> None:
    if OUT.exists():
        raise RuntimeError("FAIL_CLOSED_OUTPUT_EXISTS_PRESERVE")
    OUT.mkdir(parents=False)

    prior = outcome_metadata_only()
    now = datetime.now(timezone.utc)
    if not prior:
        raise RuntimeError("EXPECTED_PRIOR_HOLDOUT_EVIDENCE_NOT_FOUND_REAUDIT_REQUIRED")
    earliest = min(row["created_utc"] for row in prior)
    lineage = json.loads((R1A / "a2_temporal_lineage.json").read_text(encoding="utf-8"))
    r1d_manifest = json.loads((R1D / "manifest.json").read_text(encoding="utf-8"))
    r1d_contract = R1D / "static_blend_contract.json"
    r1c_thresholds = R1C / "tercile_thresholds.json"

    contract = {
        "run_id": RUN_ID,
        "contract_status": "NOT_FROZEN_FAIL_CLOSED_PRIOR_2026_OUTCOME_ARTIFACTS_PRECEDE_CONTRACT",
        "contract_recorded_at_utc": now.isoformat(),
        "HOLDOUT_CONTRACT_FROZEN_BEFORE_OUTCOME_READ": False,
        "current_run_2026_outcome_content_read_count": 0,
        "blocking_evidence": {
            "prior_2026_outcome_root": str(PRIOR_2026_OUTCOME_ROOT),
            "prior_outcome_file_count": len(prior),
            "earliest_prior_outcome_file_created_utc": earliest,
            "r1d_manifest_created_at_utc": r1d_manifest["created_at_utc"],
            "reason": "An earlier A/A2 2026 outcome evaluation exists before R1A/R1D and before this three-model holdout contract.",
        },
        "comparison_models_if_a_clean_contract_had_been_possible": {
            "M0_A2_HGB": {
                "artifact": str(HGB),
                "sha256": sha256(HGB),
                "identity_status": "CANDIDATE_PRE2026_FROZEN_ARTIFACT_NOT_EVALUATED",
            },
            "M1_XGB_REG": {
                "latest_existing_r1a_artifact": str(XGB_LATEST_OUTER),
                "sha256": sha256(XGB_LATEST_OUTER),
                "identity_status": "FULL_PRE2026_2026_INFERENCE_VINTAGE_NOT_RESOLVED_BEFORE_FAIL_CLOSED",
            },
            "M2_W50": {
                "formula": "0.5*HGB_PERCENTILE_RANK+0.5*XGB_PERCENTILE_RANK",
                "r1d_contract": str(r1d_contract),
                "r1d_contract_sha256": sha256(r1d_contract),
                "identity_status": "FORMULA_FROZEN_NOT_EVALUATED",
            },
        },
        "frozen_lineage_if_evaluation_were_clean": {
            "features": lineage["feature_names"],
            "target": lineage["target"],
            "target_maturity_rule": "ALL_FORWARD_HORIZONS_FULLY_MATURED_BEFORE_EVALUATION",
            "execution": lineage["signal_and_execution"],
            "transaction_cost": lineage["transaction_cost"],
            "portfolio": lineage["portfolio"],
            "pit_13f_rule": lineage["pit_rule"],
            "eligibility": "PIT_13F_UNIVERSE INTERSECTION SUFFICIENT_HISTORY INTERSECTION COMPLETE_FROZEN_FEATURES; SHARED_BY_ALL_MODELS",
        },
        "metrics": {
            "predictive": ["rank_ic", "pearson_ic", "mean_date_ic", "icir", "ndcg_at_20", "top20_return", "top20_spread", "hit_rate", "decile_monotonicity"],
            "economic": ["cumulative_return", "partial_year_annualized_return", "volatility", "sharpe", "sortino", "calmar", "max_drawdown", "profit_factor", "turnover", "transaction_cost", "average_holdings", "rebalance_count"],
            "concentration": ["top1_top5_top10_date_relative_pnl_share", "top1_top5_top10_ticker_relative_pnl_share"],
        },
        "classification_gates": {
            "A_PROSPECTIVE_STRONG_SUPPORT": "Rank IC >= A2; cumulative return, Sharpe, replacement spread > A2/0; MaxDD not materially worse; turnover <=1.10x; relative PnL not highly concentrated; no audit violation",
            "B_PROSPECTIVE_PARTIAL_SUPPORT": "predictive improvement with partial or insufficient economic support and no broad material degradation",
            "C_NO_CLEAR_PROSPECTIVE_ADVANTAGE": "mixed or near-zero evidence",
            "D_PROSPECTIVE_UNDERPERFORMANCE": "material economic underperformance across Sharpe/cumulative return/replacement spread",
        },
        "regime_hypothesis": {
            "only_allowed_directions": ["weak_trend", "deeper_drawdown", "low_breadth", "low_cross_sectional_return_dispersion"],
            "threshold_source": str(r1c_thresholds),
            "threshold_source_sha256": sha256(r1c_thresholds),
            "gate_creation_allowed": False,
        },
        "evaluation_authorized_after_this_record": False,
        "required_resolution": "User must explicitly decide whether to abandon pristine-holdout semantics and authorize a secondary contaminated 2026 comparison; this run cannot make that expansion.",
    }
    write_json(OUT / "2026_holdout_contract.json", contract)
    contract_hash = sha256(OUT / "2026_holdout_contract.json")
    audit = {
        "status": "FAIL_CLOSED",
        "contract_sha256": contract_hash,
        "prior_outcome_artifact_metadata": prior,
        "prior_outcome_content_read_count": 0,
        "current_run_2026_market_data_read_count": 0,
        "current_run_2026_target_read_count": 0,
        "current_run_2026_pnl_read_count": 0,
        "metadata_only_methods": ["Path.iterdir", "Path.stat"],
    }
    write_json(OUT / "preflight_contamination_audit.json", audit)
    status = {
        "A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT_STATUS": "FAIL_CLOSED_PRIOR_2026_OUTCOME_EXPOSURE_PRECEDES_CONTRACT",
        "HOLDOUT_CONTRACT_FROZEN_BEFORE_OUTCOME_READ": False,
        "2026_EVALUATION_ROWS": 0,
        "2026_TRAINING_ROWS": 0,
        "2026_PARAMETER_SEARCH_COUNT": 0,
        "2026_BLEND_SEARCH_COUNT": 0,
        "2026_FEATURE_SELECTION_COUNT": 0,
        "2026_REGIME_GATE_SEARCH_COUNT": 0,
        "2026_MODEL_REFIT_COUNT": 0,
        "POST_HOLDOUT_PARAMETER_CHANGE_COUNT": 0,
        "POST_HOLDOUT_BLEND_CHANGE_COUNT": 0,
        "POST_HOLDOUT_FEATURE_CHANGE_COUNT": 0,
        "POST_HOLDOUT_REGIME_RULE_CHANGE_COUNT": 0,
        "DEPLOYMENT_STATUS": "NOT_AUTHORIZED_BY_THIS_RUN",
        "NEXT_AUTHORIZED_STEP": "STOP_AND_REVIEW_PRIOR_2026_HOLDOUT_CONTAMINATION",
    }
    write_json(OUT / "status.json", status)
    report = f"""# {RUN_ID}\n\nStatus: fail-closed before any current-run 2026 outcome read.\n\nThe required ordering cannot be proven. {len(prior)} prior 2026 outcome artifacts exist under `{PRIOR_2026_OUTCOME_ROOT}`; the earliest file was created at `{earliest}`, before R1D and before this contract. Their contents were not opened by this run.\n\nA pristine three-model 2026 holdout evaluation is therefore not authorized. No winner, performance metric, classification, or regime validation was calculated.\n"""
    (OUT / "2026_holdout_report.md").write_text(report, encoding="utf-8")

    artifacts = []
    for path in sorted(OUT.iterdir(), key=lambda item: item.name):
        if path.name not in {"manifest.json", "sha256_manifest.txt"}:
            artifacts.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "run_id": RUN_ID,
        "created_at_utc": now.isoformat(),
        "classification": "FAIL_CLOSED_NO_2026_OUTCOME_CONTENT_READ",
        "source": str(SCRIPT),
        "source_sha256": sha256(SCRIPT),
        "artifacts": artifacts,
        "status": status,
    }
    write_json(OUT / "manifest.json", manifest)
    lines = [
        f"{sha256(path)}  {path.name}"
        for path in sorted(OUT.iterdir(), key=lambda item: item.name)
        if path.name != "sha256_manifest.txt"
    ]
    (OUT / "sha256_manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for key, value in status.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
