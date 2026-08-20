"""R6E: no-fit exploratory economic translation of frozen R6 OOF scores."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_STOCK_RISK_R6E"
R6_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_stock_risk_r6.py"
R6_ROOT = RESULTS_ROOT / "A2_STOCK_RISK_R6"
R6_OOF_PATH = R6_ROOT / "r6_oof_predictions.parquet"
R6_SUMMARY_PATH = R6_ROOT / "r6_summary.json"
R6_OOF_SHA256 = "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4"
REFERENCE_MODEL = "LGBM_BAD_ASYM_2"
FORMAL_R6_CLASSIFICATION = "C"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R6 = _load_module(R6_SCRIPT, "a2_stock_risk_r6_for_r6e")
R3 = R6.R3


def load_frozen_scores() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    actual_hash = R3.R1.sha256_file(R6_OOF_PATH)
    if actual_hash != R6_OOF_SHA256:
        raise RuntimeError(f"frozen R6 OOF hash mismatch: {actual_hash}")
    summary = json.loads(R6_SUMMARY_PATH.read_text(encoding="utf-8"))
    if summary.get("A2_STOCK_RISK_R6_CLASSIFICATION") != FORMAL_R6_CLASSIFICATION or summary.get("REFERENCE_MODEL") != REFERENCE_MODEL:
        raise RuntimeError("frozen R6 classification/reference-model contract mismatch")
    oof = pd.read_parquet(R6_OOF_PATH)
    oof["signal_date"] = pd.to_datetime(oof.signal_date)
    if oof.signal_date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("R6 OOF artifact crosses 2026 firewall")
    selected = oof.loc[oof.candidate_id.eq(REFERENCE_MODEL)].copy()
    if len(selected) == 0 or selected.groupby("signal_date").size().ne(20).any():
        raise RuntimeError("frozen R6 OOF selection is incomplete")
    panel, _, _, daily, positions, old_r3r, _ = R6.load_inputs()
    old = old_r3r.loc[old_r3r.candidate_id.eq(R6.R3R_REFERENCE_MODEL), ["signal_date", "ticker", "risk_percentile"]].rename(columns={"risk_percentile": "old_r3r_risk_percentile"})
    selected = selected.merge(old, on=["signal_date", "ticker"], validate="one_to_one")
    if not selected[["information_date", "signal_date"]].eval("information_date < signal_date").all():
        raise RuntimeError("R6E information-time contract violation")
    return selected, daily, positions, summary


def extreme_attribution(scored: pd.DataFrame) -> pd.DataFrame:
    frame = scored.copy()
    frame["r3_multiplier"] = R3.R1.direct_multiplier(frame.old_r3r_risk_percentile.to_numpy())
    frame["r6_multiplier"] = np.where(frame.risk_percentile.ge(R6.R6_INTERVENTION_PERCENTILE), R6.R6_INTERVENTION_MULTIPLIER, 1.0)
    rows: list[dict[str, Any]] = []
    for strategy, column in [("R3_MAE_RISK_SCALING_A2", "r3_multiplier"), ("R6_BAD_ASYMMETRY_SCALING_A2", "r6_multiplier")]:
        removed = 0.05 * (1.0 - frame[column]) * frame.forward_5d_stock_return
        for count in (50, 100):
            for side, index in [("WORST", frame.nsmallest(count, "forward_5d_stock_return").index), ("BEST", frame.nlargest(count, "forward_5d_stock_return").index)]:
                signed = float(removed.loc[index].sum())
                rows.append({
                    "strategy": strategy, "outcome_group": f"{side}_{count}", "observation_count": count,
                    "identified_for_scaling_count": int((frame.loc[index, column] < 1.0).sum()),
                    "identified_for_scaling_fraction": float((frame.loc[index, column] < 1.0).mean()),
                    "signed_forward_contribution_removed": signed,
                    "loss_avoided" if side == "WORST" else "winner_upside_sacrificed": -signed if side == "WORST" else signed,
                })
    return pd.DataFrame(rows)


def compact_fold_report(fold_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for fold, group in fold_metrics.groupby("fold", sort=False):
        by = group.set_index("strategy")
        raw = by.loc["RAW_A2"]
        constant = by.loc["CONSTANT_EXPOSURE_MATCHED_A2"]
        r6 = by.loc["R6_BAD_ASYMMETRY_SCALING_A2"]
        rows.append({
            "fold": fold, "raw_return": raw.total_return, "constant_return": constant.total_return,
            "r6_return": r6.total_return, "raw_mdd": raw.maximum_drawdown, "r6_mdd": r6.maximum_drawdown,
            "raw_es5": raw.expected_shortfall_5, "r6_es5": r6.expected_shortfall_5,
            "r6_sharpe_delta_vs_raw": r6.sharpe - raw.sharpe,
            "r6_sharpe_delta_vs_constant": r6.sharpe - constant.sharpe,
            "R6_ECONOMICALLY_USEFUL": bool(group.r6_useful_economic_direction.iloc[0]),
        })
    return pd.DataFrame(rows)


def diagnostic(values: dict[str, float | bool], useful_folds: int) -> str:
    meaningful_tail = bool(values["MDD_REDUCTION_VS_RAW"] >= 0.10 or values["ES5_IMPROVEMENT_VS_RAW"] >= 0.15)
    strong = bool(values["RETURN_RETENTION_VS_RAW"] >= 0.90 and meaningful_tail and values["MATERIALLY_BEATS_CONSTANT"] and useful_folds >= 4)
    some_tail = bool(values["MDD_REDUCTION_VS_RAW"] > 0 or values["ES5_IMPROVEMENT_VS_RAW"] > 0)
    some_control_value = bool(values["SHARPE_VALUE_OVER_CONSTANT"] > 0 or values["MDD_VALUE_OVER_CONSTANT"] > 0 or values["ES_VALUE_OVER_CONSTANT"] > 0 or values["RETURN_VALUE_OVER_CONSTANT"] > 0)
    partial = bool(values["RETURN_RETENTION_VS_RAW"] >= 0.85 and some_tail and some_control_value and useful_folds >= 1)
    return "STRONG" if strong else "PARTIAL" if partial else "NONE"


def print_summary(summary: dict[str, Any]) -> None:
    keys = [
        "A2_STOCK_RISK_R6E_STATUS", "FORMAL_R6_CLASSIFICATION", "ECONOMIC_DIAGNOSTIC", "R6_MEAN_EXPOSURE",
        "RAW_A2_RETURN", "CONSTANT_RETURN", "R3_RETURN", "R6_RETURN", "RAW_A2_SHARPE", "CONSTANT_SHARPE", "R6_SHARPE",
        "RAW_A2_MDD", "CONSTANT_MDD", "R6_MDD", "RAW_A2_ES5", "CONSTANT_ES5", "R6_ES5",
        "R6_RETURN_RETENTION", "R6_MDD_REDUCTION", "R6_ES5_IMPROVEMENT", "R6_GROSS_LOSS_AVOIDED",
        "R6_GROSS_WINNER_UPSIDE_SACRIFICED", "LOSS_AVOIDED_TO_WINNER_SACRIFICE_RATIO", "R6_USEFUL_ECONOMIC_FOLDS",
        "MODEL_FIT_COUNT_R6E", "PARAMETER_SEARCH_COUNT", "THRESHOLD_SEARCH_COUNT", "HOLDOUT_FILE_READ_COUNT",
        "LOOKAHEAD_VIOLATION_COUNT", "NEXT_AUTHORIZED_STEP",
    ]
    for key in keys:
        value = summary[key]
        if isinstance(value, float) and np.isfinite(value):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: output directory not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    scored, daily, positions, frozen_summary = load_frozen_scores()
    metrics, simulations = R6.portfolio_economics(scored, positions, daily)
    fold_metrics, useful_folds = R6.fold_economics(simulations)
    fold_report = compact_fold_report(fold_metrics)
    scored["r3_multiplier"] = R3.R1.direct_multiplier(scored.old_r3r_risk_percentile.to_numpy())
    scored["r6_multiplier"] = np.where(scored.risk_percentile.ge(R6.R6_INTERVENTION_PERCENTILE), R6.R6_INTERVENTION_MULTIPLIER, 1.0)
    attribution = R6.scaling_attribution(scored)
    extremes = extreme_attribution(scored)
    values = R6.economic_values(metrics)
    interpretation = diagnostic(values, useful_folds)

    guard = R3.R1.guard_audit()
    lookahead = int((scored.information_date >= scored.signal_date).sum() + (scored.train_max_target_end >= scored.embargo_cutoff).sum())
    integrity_failure = bool(lookahead or guard["new_risk_r1_repo_violation_count"] or pd.to_datetime(scored.signal_date).ge(TRAINING_CUTOFF).any())
    if integrity_failure:
        raise RuntimeError("R6E integrity/firewall audit failure")

    by = metrics.set_index("strategy")
    raw, constant, r3, r6 = [by.loc[name] for name in ["RAW_A2", "CONSTANT_EXPOSURE_MATCHED_A2", "R3_RAW_MAE_RISK_SCALING_A2", "R6_BAD_ASYMMETRY_SCALING_A2"]]
    attr = attribution.set_index("strategy")
    r3_attr, r6_attr = attr.loc["R3_RAW_MAE_RISK_SCALING_A2"], attr.loc["R6_BAD_ASYMMETRY_SCALING_A2"]
    next_step = {
        "NONE": "STOP_ML_RISK_TARGET_RESEARCH;TRANSITION_TO_STRUCTURAL_NON_PREDICTIVE_RISK_LIMITS;DO_NOT_OPEN_2026",
        "PARTIAL": "PRESERVE_R6_RESEARCH_ONLY;DO_NOT_TUNE;DO_NOT_OPEN_2026",
        "STRONG": "PRESERVE_R6_PROMISING_RESEARCH_ONLY;REQUIRE_FRESH_PROSPECTIVE_CONFIRMATION;DO_NOT_OPEN_2026_AUTOMATICALLY",
    }[interpretation]
    status = "VALID_EXPLORATORY_PRE2026_R6E_RESULT" + ("_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE" if guard["repository_guard_status"] != "PASS" else "")
    summary = {
        "A2_STOCK_RISK_R6E_STATUS": status, "FORMAL_R6_CLASSIFICATION": FORMAL_R6_CLASSIFICATION,
        "ECONOMIC_DIAGNOSTIC": interpretation, "R6_MEAN_EXPOSURE": r6.mean_exposure,
        "RAW_A2_RETURN": raw.total_return, "CONSTANT_RETURN": constant.total_return, "R3_RETURN": r3.total_return, "R6_RETURN": r6.total_return,
        "RAW_A2_SHARPE": raw.sharpe, "CONSTANT_SHARPE": constant.sharpe, "R6_SHARPE": r6.sharpe,
        "RAW_A2_MDD": raw.maximum_drawdown, "CONSTANT_MDD": constant.maximum_drawdown, "R6_MDD": r6.maximum_drawdown,
        "RAW_A2_ES5": raw.expected_shortfall_5, "CONSTANT_ES5": constant.expected_shortfall_5, "R6_ES5": r6.expected_shortfall_5,
        "R6_RETURN_RETENTION": values["RETURN_RETENTION_VS_RAW"], "R6_MDD_REDUCTION": values["MDD_REDUCTION_VS_RAW"], "R6_ES5_IMPROVEMENT": values["ES5_IMPROVEMENT_VS_RAW"],
        "RETURN_VALUE_OVER_CONSTANT": values["RETURN_VALUE_OVER_CONSTANT"], "SHARPE_VALUE_OVER_CONSTANT": values["SHARPE_VALUE_OVER_CONSTANT"],
        "MDD_VALUE_OVER_CONSTANT": values["MDD_VALUE_OVER_CONSTANT"], "ES_VALUE_OVER_CONSTANT": values["ES_VALUE_OVER_CONSTANT"],
        "R6_GROSS_LOSS_AVOIDED": r6_attr.gross_loss_avoided, "R6_GROSS_WINNER_UPSIDE_SACRIFICED": r6_attr.gross_winner_upside_sacrificed,
        "R6_NET_SCALING_VALUE": r6_attr.net_scaling_value, "LOSS_AVOIDED_TO_WINNER_SACRIFICE_RATIO": r6_attr.loss_avoided_to_winner_sacrificed_ratio,
        "R3_GROSS_LOSS_AVOIDED": r3_attr.gross_loss_avoided, "R3_GROSS_WINNER_UPSIDE_SACRIFICED": r3_attr.gross_winner_upside_sacrificed,
        "R3_NET_SCALING_VALUE": r3_attr.net_scaling_value, "R3_LOSS_AVOIDED_TO_WINNER_SACRIFICE_RATIO": r3_attr.loss_avoided_to_winner_sacrificed_ratio,
        "R6_USEFUL_ECONOMIC_FOLDS": useful_folds, "MODEL_FIT_COUNT_R6E": 0, "PARAMETER_SEARCH_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0, "TRAINING_DATA_2026_COUNT": 0, "HOLDOUT_FILE_READ_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": lookahead, "NEW_RISK_R6E_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"],
        "NEXT_AUTHORIZED_STEP": next_step,
    }
    audit = {
        "summary": summary, "frozen_r6_summary": frozen_summary, "r6_oof_path": str(R6_OOF_PATH),
        "r6_oof_expected_sha256": R6_OOF_SHA256, "r6_oof_actual_sha256": R3.R1.sha256_file(R6_OOF_PATH),
        "reference_model": REFERENCE_MODEL, "formal_r6_classification_preserved": True,
        "position_rule": {"risk_percentile_below_90": 1.0, "risk_percentile_at_least_90": 0.5, "removed_weight_destination": "CASH"},
        "model_fit_count_r6e": 0, "parameter_search_count": 0, "threshold_search_count": 0,
        "holdout_file_read_count": 0, "training_data_2026_count": 0, "lookahead_violation_count": lookahead,
        "economic_diagnostic_contract": {"strong": "retention>=0.90; MDD reduction>=0.10 or ES5 improvement>=0.15; materially beats constant; useful folds>=4", "partial": "retention>=0.85; some tail and control-relative benefit; useful folds>=1", "none": "otherwise"},
        "repository_governance": guard,
    }
    R3.R1.write_csv(output / "r6e_strategy_metrics.csv", metrics)
    R3.R1.write_csv(output / "r6e_strategy_fold_metrics.csv", fold_report)
    R3.R1.write_csv(output / "r6e_scaling_attribution.csv", attribution)
    R3.R1.write_csv(output / "r6e_extreme_holding_attribution.csv", extremes)
    R3.R1.write_json(output / "r6e_audit.json", audit)
    R3.R1.write_json(output / "r6e_summary.json", summary)
    print_summary(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    try:
        run(args.output_dir.resolve())
        return 0
    except Exception as exc:
        print("A2_STOCK_RISK_R6E_STATUS=FAIL_CLOSED", file=sys.stderr)
        print("FORMAL_R6_CLASSIFICATION=C", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
