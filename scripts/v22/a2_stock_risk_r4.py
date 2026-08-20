"""A2 Stock Risk R4: alpha-conditioned residual-risk position translation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_STOCK_RISK_R4"
R3A_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_stock_risk_r3a_r3r.py"
R3R_ROOT = RESULTS_ROOT / "A2_STOCK_RISK_R3A_R3R"
R3R_OOF_PATH = R3R_ROOT / "r3r_oof_predictions.parquet"
R3R_BACKFILL_PATH = R3R_ROOT / "r3r_moomoo_qfq_execution_backfill.parquet"
R3R_SUMMARY_PATH = R3R_ROOT / "r3a_r3r_summary.json"
REFERENCE_CANDIDATE = "LGBM_STOCK_Q90_1"
RIDGE_ALPHA = 1.0
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R3A = _load_module(R3A_SCRIPT, "a2_stock_risk_r3a_r3r_for_r4")
R3 = R3A.R3


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    r3r_summary = json.loads(R3R_SUMMARY_PATH.read_text(encoding="utf-8"))
    if r3r_summary.get("RISK_SIGNAL_CLASSIFICATION") != "A" or r3r_summary.get("EXECUTION_REFERENCE_COVERAGE") != 1.0:
        raise RuntimeError("R3R risk signal or execution coverage is not qualified")
    panel, score_panel, daily, positions, _ = R3.build_panels()
    prices = R3A.load_canonical_prices(set(score_panel.ticker))
    backfill = pd.read_parquet(R3R_BACKFILL_PATH).rename(columns={"internal_symbol": "ticker", "date": "trade_date", "adjustment_mode": "autype"})
    backfill["source"] = "MOOMOO_OPEND"
    backfill["trade_date"] = pd.to_datetime(backfill.trade_date)
    if backfill.trade_date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("R4 backfill read includes 2026")
    prices = pd.concat([prices, backfill[prices.columns]], ignore_index=True).drop_duplicates(["ticker", "trade_date"], keep="first")
    coverage, required = R3A.coverage_table(score_panel, prices)
    if len(coverage) != len(score_panel) or not coverage.exact_execution_reference.all() or not coverage.complete_5d_path.all():
        raise RuntimeError("R4 cannot reproduce complete R3R execution coverage")
    corrected = R3A.build_corrected_targets(score_panel, required)
    if len(corrected) != len(score_panel) or corrected.target_end_date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("R4 corrected target firewall failure")
    labeled = score_panel.merge(corrected, on=["signal_date", "ticker"], validate="one_to_one").rename(
        columns={"post_entry_forward_1d_return": "next_day_stock_return", "post_entry_forward_5d_return": "forward_5d_stock_return", "post_entry_5d_mae": "forward_5d_stock_mae"}
    )
    oof = pd.read_parquet(R3R_OOF_PATH)
    oof["signal_date"] = pd.to_datetime(oof.signal_date)
    if oof.signal_date.ge(TRAINING_CUTOFF).any() or oof.candidate_id.eq(REFERENCE_CANDIDATE).sum() == 0:
        raise RuntimeError("R4 authoritative OOF firewall or candidate failure")
    return labeled, score_panel, corrected, daily, positions, oof, r3r_summary


def build_residual_oof(labeled: pd.DataFrame, score_panel: pd.DataFrame, daily: pd.DataFrame, oof: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    candidate = next(item for item in R3.CANDIDATES if item.candidate_id == REFERENCE_CANDIDATE)
    authoritative = oof.loc[oof.candidate_id.eq(REFERENCE_CANDIDATE)].copy()
    results = []
    calibration_rows = []
    max_reproduction_error = 0.0
    for fold_name, start, end in R3.FOLDS:
        train, _, cutoff = R3.fold_split(labeled, pd.DatetimeIndex(daily.execution_date), start, end)
        validation_features = score_panel.loc[score_panel.signal_date.between(start, end)].copy()
        stored = authoritative.loc[authoritative.fold.eq(fold_name)].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
        validation_features = validation_features.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
        if not stored[["signal_date", "ticker"]].equals(validation_features[["signal_date", "ticker"]]):
            raise RuntimeError(f"R4 stored OOF key mismatch: {fold_name}")
        risk_model = R3.make_model(candidate)
        risk_model.fit(train[R3.FEATURES], train.forward_5d_stock_mae)
        reproduced = R3.qpredict(risk_model, validation_features)
        error = float(np.max(np.abs(reproduced - stored.predicted_q90.to_numpy(dtype=float))))
        max_reproduction_error = max(max_reproduction_error, error)
        if error > 1e-12:
            raise RuntimeError(f"R4 R3R OOF reproduction mismatch: {fold_name}:{error}")
        training_risk_score = R3.qpredict(risk_model, train)
        calibration = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=RIDGE_ALPHA))])
        calibration.fit(train[["A2_PREDICTION"]], training_risk_score)
        expected_train = calibration.predict(train[["A2_PREDICTION"]])
        expected_validation = calibration.predict(stored[["A2_PREDICTION"]])
        training_residual = training_risk_score - expected_train
        residual = stored.predicted_q90.to_numpy(dtype=float) - expected_validation
        stored["expected_risk_given_alpha"] = expected_validation
        stored["alpha_conditioned_residual_risk"] = residual
        stored["residual_risk_percentile"] = R3.R1.empirical_percentile(training_residual, residual)
        stored["r3_raw_risk_multiplier"] = R3.R1.direct_multiplier(stored.risk_percentile.to_numpy())
        stored["r4_residual_risk_multiplier"] = R3.R1.direct_multiplier(stored.residual_risk_percentile.to_numpy())
        results.append(stored)
        scaler, ridge = calibration.named_steps["scale"], calibration.named_steps["ridge"]
        raw_slope = float(ridge.coef_[0] / scaler.scale_[0])
        raw_intercept = float(ridge.intercept_ - ridge.coef_[0] * scaler.mean_[0] / scaler.scale_[0])
        calibration_rows.append({"fold": fold_name, "train_rows": len(train), "validation_rows": len(stored), "embargo_cutoff": cutoff, "ridge_alpha": RIDGE_ALPHA, "raw_alpha_slope": raw_slope, "raw_intercept": raw_intercept, "train_residual_mean": float(training_residual.mean()), "train_residual_std": float(training_residual.std()), "validation_score_reproduction_max_abs_error": error})
    scored = pd.concat(results, ignore_index=True).sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    audit = {"risk_model_reproduction_fit_count": len(R3.FOLDS), "alpha_calibration_fit_count": len(R3.FOLDS), "validation_score_reproduction_max_abs_error": max_reproduction_error, "authoritative_validation_score_replacement_count": 0}
    return scored, pd.DataFrame(calibration_rows), audit


def scaling_attribution(scored: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    rows = []
    for name, column in [("R3_RAW_RISK_SCALING_A2", "r3_raw_risk_multiplier"), ("R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2", "r4_residual_risk_multiplier")]:
        removed = 0.05 * (1.0 - scored[column])
        contribution = removed * scored.forward_5d_stock_return
        avoided = float(-contribution.loc[scored.forward_5d_stock_return < 0].sum())
        sacrificed = float(contribution.loc[scored.forward_5d_stock_return > 0].sum())
        rows.append({"strategy": name, "observation_count": len(scored), "gross_loss_avoided": avoided, "gross_winner_upside_sacrificed": sacrificed, "net_scaling_value": avoided - sacrificed})
    table = pd.DataFrame(rows).set_index("strategy")
    r3, r4 = table.loc["R3_RAW_RISK_SCALING_A2"], table.loc["R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2"]
    values = {"WINNER_SACRIFICE_REDUCTION_VS_R3": 1.0 - r4.gross_winner_upside_sacrificed / r3.gross_winner_upside_sacrificed, "LOSS_AVOIDANCE_RETENTION_VS_R3": r4.gross_loss_avoided / r3.gross_loss_avoided}
    return table.reset_index(), values


def risk_deciles(scored: pd.DataFrame, corrected: pd.DataFrame) -> pd.DataFrame:
    frame = scored.merge(corrected[["signal_date", "ticker", "post_entry_5d_mfe"]], on=["signal_date", "ticker"], validate="one_to_one")
    rows = []
    for scheme, percentile in [("R3_RAW_RISK", "risk_percentile"), ("R4_RESIDUAL_RISK", "residual_risk_percentile")]:
        frame["diagnostic_decile"] = np.clip(np.ceil(frame[percentile] * 10), 1, 10).astype(int)
        table = frame.groupby("diagnostic_decile", sort=True).agg(observation_count=("ticker", "size"), mean_a2_prediction=("A2_PREDICTION", "mean"), mean_a2_rank=("A2_RANK", "mean"), mean_post_entry_5d_mae=("forward_5d_stock_mae", "mean"), mean_post_entry_5d_mfe=("post_entry_5d_mfe", "mean"), mean_final_5d_return=("forward_5d_stock_return", "mean"), positive_return_frequency=("forward_5d_stock_return", lambda x: float((x > 0).mean())), severe_loss_frequency=("stock_severe_5d", "mean")).reset_index()
        table.insert(0, "risk_scheme", scheme)
        rows.append(table)
    return pd.concat(rows, ignore_index=True)


def portfolio_economics(scored: pd.DataFrame, positions: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, dict[pd.Timestamp, dict[str, float]]]]:
    scored = scored.copy()
    scored["raw_multiplier"] = 1.0
    scored["stock_vol_multiplier"] = np.clip(R3.STOCK_VOL_TARGET / scored.REALIZED_VOL_20D, R3.STOCK_VOL_MIN_MULTIPLIER, 1.0)
    definitions = [("RAW_A2", "raw_multiplier"), ("STOCK_VOL_SCALING_A2", "stock_vol_multiplier"), ("R3_RAW_RISK_SCALING_A2", "r3_raw_risk_multiplier"), ("R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2", "r4_residual_risk_multiplier")]
    targets = {name: R3.target_maps(scored, column) for name, column in definitions}
    simulations = {name: R3.simulate(targets[name], positions)[0] for name, _ in definitions}
    scored["constant_multiplier"] = float(simulations["R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2"].target_exposure.mean())
    targets["CONSTANT_EXPOSURE_MATCHED_A2"] = R3.target_maps(scored, "constant_multiplier")
    simulations["CONSTANT_EXPOSURE_MATCHED_A2"] = R3.simulate(targets["CONSTANT_EXPOSURE_MATCHED_A2"], positions)[0]
    output_order = ["RAW_A2", "CONSTANT_EXPOSURE_MATCHED_A2", "STOCK_VOL_SCALING_A2", "R3_RAW_RISK_SCALING_A2", "R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2"]
    authoritative = daily.set_index("execution_date").reconstructed_daily_return.reindex(simulations["RAW_A2"].date)
    identity_error = float(np.max(np.abs(simulations["RAW_A2"].daily_return.to_numpy() - authoritative.to_numpy())))
    if identity_error > 1e-4:
        raise RuntimeError("R4 raw A2 identity failure")
    simulations["RAW_A2"] = simulations["RAW_A2"].copy()
    simulations["RAW_A2"]["daily_return"] = authoritative.to_numpy()
    rows = []
    for name in output_order:
        rows.append(R3.strategy_row(name, simulations[name], R3.overlay_turnover(targets[name], targets["RAW_A2"])))
    metrics = pd.DataFrame(rows)
    metrics["raw_identity_max_abs_error"] = identity_error
    return metrics, simulations, targets


def fold_economics(simulations: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, int]:
    rows = []
    useful_count = 0
    for fold_name, start, end in R3.FOLDS:
        fold_metrics = {}
        for name, daily in simulations.items():
            window = daily.loc[daily.date.between(start, end)]
            values = {**R3.R1.performance_metrics(window.daily_return), "mean_exposure": float(window.target_exposure.mean())}
            fold_metrics[name] = values
            rows.append({"fold": fold_name, "strategy": name, **values})
        constant, r4 = fold_metrics["CONSTANT_EXPOSURE_MATCHED_A2"], fold_metrics["R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2"]
        useful = bool(r4["total_return"] >= constant["total_return"] - 0.02 and r4["sharpe"] >= constant["sharpe"] and (abs(r4["maximum_drawdown"]) < abs(constant["maximum_drawdown"]) or r4["expected_shortfall_5"] > constant["expected_shortfall_5"]))
        useful_count += int(useful)
        for row in rows[-len(simulations):]:
            row["r4_useful_economic_direction"] = useful
    return pd.DataFrame(rows), useful_count


def classify(metrics: pd.DataFrame, attribution: pd.DataFrame, useful_folds: int, integrity_failure: bool = False) -> tuple[str, dict[str, float | bool]]:
    if integrity_failure:
        return "E", {}
    by = metrics.set_index("strategy")
    raw, constant, r3, r4 = by.loc["RAW_A2"], by.loc["CONSTANT_EXPOSURE_MATCHED_A2"], by.loc["R3_RAW_RISK_SCALING_A2"], by.loc["R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2"]
    attr = attribution.set_index("strategy")
    a3, a4 = attr.loc["R3_RAW_RISK_SCALING_A2"], attr.loc["R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2"]
    values: dict[str, float | bool] = {
        "RETURN_RETENTION_VS_RAW": float(r4.total_return / raw.total_return) if raw.total_return > 0 else np.nan,
        "MDD_REDUCTION_VS_RAW": float(1.0 - abs(r4.maximum_drawdown) / abs(raw.maximum_drawdown)),
        "ES5_IMPROVEMENT_VS_RAW": float(1.0 - abs(r4.expected_shortfall_5) / abs(raw.expected_shortfall_5)),
        "RETURN_VALUE_OVER_CONSTANT": float(r4.total_return - constant.total_return), "MDD_VALUE_OVER_CONSTANT": float(abs(constant.maximum_drawdown) - abs(r4.maximum_drawdown)), "ES_VALUE_OVER_CONSTANT": float(r4.expected_shortfall_5 - constant.expected_shortfall_5),
        "RETURN_VALUE_OVER_R3_RAW_RISK": float(r4.total_return - r3.total_return), "MDD_VALUE_OVER_R3_RAW_RISK": float(abs(r3.maximum_drawdown) - abs(r4.maximum_drawdown)), "ES_VALUE_OVER_R3_RAW_RISK": float(r4.expected_shortfall_5 - r3.expected_shortfall_5),
        "WINNER_SACRIFICE_REDUCTION_VS_R3": float(1.0 - a4.gross_winner_upside_sacrificed / a3.gross_winner_upside_sacrificed), "LOSS_AVOIDANCE_RETENTION_VS_R3": float(a4.gross_loss_avoided / a3.gross_loss_avoided),
    }
    material_constant = bool(r4.sharpe >= constant.sharpe + 0.05 and (values["MDD_VALUE_OVER_CONSTANT"] >= 0.05 * abs(constant.maximum_drawdown) or values["ES_VALUE_OVER_CONSTANT"] >= 0.05 * abs(constant.expected_shortfall_5)) and values["RETURN_VALUE_OVER_CONSTANT"] >= -0.02)
    improved_balance = bool(values["WINNER_SACRIFICE_REDUCTION_VS_R3"] >= 0.25 and values["LOSS_AVOIDANCE_RETENTION_VS_R3"] >= 0.50 and a4.net_scaling_value > a3.net_scaling_value)
    pass_a = bool(values["RETURN_RETENTION_VS_RAW"] >= 0.90 and (values["MDD_REDUCTION_VS_RAW"] >= 0.10 or values["ES5_IMPROVEMENT_VS_RAW"] >= 0.15) and material_constant and improved_balance and useful_folds >= 4)
    pass_b = bool(values["RETURN_RETENTION_VS_RAW"] >= 0.85 and useful_folds >= 3 and values["WINNER_SACRIFICE_REDUCTION_VS_R3"] > 0 and values["LOSS_AVOIDANCE_RETENTION_VS_R3"] >= 0.25 and (r4.sharpe > constant.sharpe or values["MDD_VALUE_OVER_CONSTANT"] > 0 or values["ES_VALUE_OVER_CONSTANT"] > 0))
    materially_destructive = bool(values["RETURN_RETENTION_VS_RAW"] < 0.75 or (values["RETURN_VALUE_OVER_CONSTANT"] < -0.10 and r4.sharpe < constant.sharpe))
    values.update({"MATERIALLY_BEATS_CONSTANT_GATE": material_constant, "WINNER_LOSS_BALANCE_GATE": improved_balance, "A_GATE_PASS": pass_a, "B_GATE_PASS": pass_b})
    return "A" if pass_a else ("B" if pass_b else ("D" if materially_destructive else "C")), values


def print_summary(summary: dict[str, Any]) -> None:
    keys = ["A2_STOCK_RISK_R4_STATUS", "A2_STOCK_RISK_R4_CLASSIFICATION", "R3R_RISK_SIGNAL_HASH", "RAW_A2_RETURN", "CONSTANT_RETURN", "STOCK_VOL_RETURN", "R3_RAW_RISK_RETURN", "R4_RESIDUAL_RISK_RETURN", "RAW_A2_MDD", "CONSTANT_MDD", "R3_RAW_RISK_MDD", "R4_RESIDUAL_RISK_MDD", "RAW_A2_ES5", "CONSTANT_ES5", "R3_RAW_RISK_ES5", "R4_RESIDUAL_RISK_ES5", "R4_RETURN_RETENTION", "R4_MDD_REDUCTION", "R4_ES5_IMPROVEMENT", "R3_WINNER_UPSIDE_SACRIFICED", "R4_WINNER_UPSIDE_SACRIFICED", "WINNER_SACRIFICE_REDUCTION_VS_R3", "R3_LOSS_AVOIDED", "R4_LOSS_AVOIDED", "LOSS_AVOIDANCE_RETENTION_VS_R3", "R4_USEFUL_ECONOMIC_FOLDS", "TRAINING_DATA_2026_COUNT", "HOLDOUT_FILE_READ_COUNT", "LOOKAHEAD_VIOLATION_COUNT", "NEW_RISK_R4_REPO_VIOLATION_COUNT", "NEXT_AUTHORIZED_STEP"]
    for key in keys:
        value = summary.get(key)
        if isinstance(value, float) and np.isfinite(value):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: output directory not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    prediction_hash = R3.R1.sha256_file(R3R_OOF_PATH)
    labeled, score_panel, corrected, daily, positions, oof, r3r_summary = load_inputs()
    scored, calibrations, reproduction_audit = build_residual_oof(labeled, score_panel, daily, oof)
    attribution, balance = scaling_attribution(scored)
    deciles = risk_deciles(scored, corrected)
    strategy_metrics, simulations, _ = portfolio_economics(scored, positions, daily)
    fold_metrics, useful_folds = fold_economics(simulations)
    classification, economics = classify(strategy_metrics, attribution, useful_folds)
    guard = R3.R1.guard_audit()
    lookahead = int((scored.information_date >= scored.signal_date).sum() + (scored.train_max_target_end >= scored.embargo_cutoff).sum())
    integrity_failure = bool(lookahead or guard["new_risk_r1_repo_violation_count"] or reproduction_audit["validation_score_reproduction_max_abs_error"] > 1e-12)
    if integrity_failure:
        classification = "E"
    status = "VALID_PRE2026_R4_RESULT" + ("_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE" if guard["repository_guard_status"] != "PASS" else "")
    by = strategy_metrics.set_index("strategy"); attr = attribution.set_index("strategy")
    raw, constant, stock_vol, r3, r4 = by.loc["RAW_A2"], by.loc["CONSTANT_EXPOSURE_MATCHED_A2"], by.loc["STOCK_VOL_SCALING_A2"], by.loc["R3_RAW_RISK_SCALING_A2"], by.loc["R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2"]
    a3, a4 = attr.loc["R3_RAW_RISK_SCALING_A2"], attr.loc["R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2"]
    summary = {"A2_STOCK_RISK_R4_STATUS": status, "A2_STOCK_RISK_R4_CLASSIFICATION": classification, "R3R_RISK_SIGNAL_HASH": prediction_hash, "RAW_A2_RETURN": raw.total_return, "CONSTANT_RETURN": constant.total_return, "STOCK_VOL_RETURN": stock_vol.total_return, "R3_RAW_RISK_RETURN": r3.total_return, "R4_RESIDUAL_RISK_RETURN": r4.total_return, "RAW_A2_MDD": raw.maximum_drawdown, "CONSTANT_MDD": constant.maximum_drawdown, "R3_RAW_RISK_MDD": r3.maximum_drawdown, "R4_RESIDUAL_RISK_MDD": r4.maximum_drawdown, "RAW_A2_ES5": raw.expected_shortfall_5, "CONSTANT_ES5": constant.expected_shortfall_5, "R3_RAW_RISK_ES5": r3.expected_shortfall_5, "R4_RESIDUAL_RISK_ES5": r4.expected_shortfall_5, "R4_RETURN_RETENTION": economics["RETURN_RETENTION_VS_RAW"], "R4_MDD_REDUCTION": economics["MDD_REDUCTION_VS_RAW"], "R4_ES5_IMPROVEMENT": economics["ES5_IMPROVEMENT_VS_RAW"], "R3_WINNER_UPSIDE_SACRIFICED": a3.gross_winner_upside_sacrificed, "R4_WINNER_UPSIDE_SACRIFICED": a4.gross_winner_upside_sacrificed, "WINNER_SACRIFICE_REDUCTION_VS_R3": balance["WINNER_SACRIFICE_REDUCTION_VS_R3"], "R3_LOSS_AVOIDED": a3.gross_loss_avoided, "R4_LOSS_AVOIDED": a4.gross_loss_avoided, "LOSS_AVOIDANCE_RETENTION_VS_R3": balance["LOSS_AVOIDANCE_RETENTION_VS_R3"], "R4_USEFUL_ECONOMIC_FOLDS": useful_folds, "TRAINING_DATA_2026_COUNT": 0, "HOLDOUT_FILE_READ_COUNT": 0, "2026_USED_FOR_RULE_SELECTION_COUNT": 0, "2026_USED_FOR_PARAMETER_SELECTION_COUNT": 0, "LOOKAHEAD_VIOLATION_COUNT": lookahead, "NEW_RISK_R4_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"], "NEXT_AUTHORIZED_STEP": "STOP_AFTER_R4;DO_NOT_OPEN_2026;DO_NOT_START_ANOTHER_MODEL_FAMILY", "economic_gate_details": economics, "reference_r3r_summary": r3r_summary}
    audit = {"summary": summary, "r3r_prediction_artifact": str(R3R_OOF_PATH), "r3r_prediction_artifact_sha256": prediction_hash, "r3r_reference_candidate": REFERENCE_CANDIDATE, "feature_count": len(R3.FEATURES), "feature_schema_sha256": R3.R1.canonical_hash(R3.FEATURES), "new_feature_count": 0, "alpha_conditioning": {"variable": "A2_PREDICTION", "model": "StandardScaler plus Ridge", "ridge_alpha": RIDGE_ALPHA, "functional_form_search_count": 0}, "reproduction": reproduction_audit, "risk_model_family_count_added": 0, "parameter_search_count": 0, "optuna_trial_count": 0, "random_cv_count": 0, "training_data_2026_count": 0, "holdout_file_read_count": 0, "lookahead_violation_count": lookahead, "repository_governance": guard}
    R3.R1.write_parquet(output / "r4_oof_residual_scores.parquet", scored)
    R3.R1.write_csv(output / "r4_alpha_calibration_folds.csv", calibrations)
    R3.R1.write_csv(output / "r4_risk_deciles.csv", deciles)
    R3.R1.write_csv(output / "r4_scaling_attribution.csv", attribution)
    R3.R1.write_csv(output / "r4_strategy_metrics.csv", strategy_metrics)
    R3.R1.write_csv(output / "r4_strategy_fold_metrics.csv", fold_metrics)
    R3.R1.write_json(output / "r4_audit.json", audit)
    R3.R1.write_json(output / "r4_summary.json", summary)
    print_summary(summary)
    return summary


def repair_existing(output: Path) -> dict[str, Any]:
    """Rematch the constant control to realized R4 exposure without refitting."""
    summary_path, audit_path = output / "r4_summary.json", output / "r4_audit.json"
    scored_path, attribution_path = output / "r4_oof_residual_scores.parquet", output / "r4_scaling_attribution.csv"
    if not all(path.exists() for path in [summary_path, audit_path, scored_path, attribution_path]):
        raise RuntimeError("R4 repair requires completed persisted evidence")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    scored = pd.read_parquet(scored_path)
    _, _, daily, positions, _ = R3.build_panels()
    metrics, simulations, _ = portfolio_economics(scored, positions, daily)
    folds, useful_folds = fold_economics(simulations)
    attribution = pd.read_csv(attribution_path)
    classification, economics = classify(metrics, attribution, useful_folds)
    by = metrics.set_index("strategy")
    raw, constant, stock_vol, r3, r4 = by.loc["RAW_A2"], by.loc["CONSTANT_EXPOSURE_MATCHED_A2"], by.loc["STOCK_VOL_SCALING_A2"], by.loc["R3_RAW_RISK_SCALING_A2"], by.loc["R4_ALPHA_CONDITIONED_RESIDUAL_RISK_A2"]
    summary.update({"A2_STOCK_RISK_R4_CLASSIFICATION": classification, "RAW_A2_RETURN": raw.total_return, "CONSTANT_RETURN": constant.total_return, "STOCK_VOL_RETURN": stock_vol.total_return, "R3_RAW_RISK_RETURN": r3.total_return, "R4_RESIDUAL_RISK_RETURN": r4.total_return, "RAW_A2_MDD": raw.maximum_drawdown, "CONSTANT_MDD": constant.maximum_drawdown, "R3_RAW_RISK_MDD": r3.maximum_drawdown, "R4_RESIDUAL_RISK_MDD": r4.maximum_drawdown, "RAW_A2_ES5": raw.expected_shortfall_5, "CONSTANT_ES5": constant.expected_shortfall_5, "R3_RAW_RISK_ES5": r3.expected_shortfall_5, "R4_RESIDUAL_RISK_ES5": r4.expected_shortfall_5, "R4_RETURN_RETENTION": economics["RETURN_RETENTION_VS_RAW"], "R4_MDD_REDUCTION": economics["MDD_REDUCTION_VS_RAW"], "R4_ES5_IMPROVEMENT": economics["ES5_IMPROVEMENT_VS_RAW"], "R4_USEFUL_ECONOMIC_FOLDS": useful_folds, "economic_gate_details": economics})
    audit["summary"] = summary
    audit["reporting_repair"] = {"model_fit_count": 0, "reason": "match constant control to realized R4 exposure after initialization"}
    R3.R1.write_csv(output / "r4_strategy_metrics.csv", metrics)
    R3.R1.write_csv(output / "r4_strategy_fold_metrics.csv", folds)
    R3.R1.write_json(audit_path, audit)
    R3.R1.write_json(summary_path, summary)
    print_summary(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--repair-existing", action="store_true")
    args = parser.parse_args()
    try:
        repair_existing(args.output_dir.resolve()) if args.repair_existing else run(args.output_dir.resolve())
        return 0
    except Exception as exc:
        print("A2_STOCK_RISK_R4_STATUS=FAIL_CLOSED", file=sys.stderr)
        print("A2_STOCK_RISK_R4_CLASSIFICATION=E", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
