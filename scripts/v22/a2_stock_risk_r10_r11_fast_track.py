"""R10 immutable closeout followed by preregistered R11 R6 prospective shadow."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
R10_ROOT = RESULTS / "A2_STOCK_RISK_R10_CLOSEOUT"
R11_ROOT = RESULTS / "A2_STOCK_RISK_R11_PROSPECTIVE"
R6_ROOT = RESULTS / "A2_STOCK_RISK_R6"
R6_OOF = R6_ROOT / "r6_oof_predictions.parquet"
R6_OOF_EXPECTED = "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4"
R6_TARGET_ID_EXPECTED = "b8348a858dc0e92c9c24bd7661e8d5b129682975b6411ed4ec8add1c73118521"
R6_FOLD_ID_EXPECTED = "fa9cd7aa20f6a564c4357b61153ae1252b3fc407b68345285b42bd0f8c92daaa"
R6_REFERENCE_MODEL = "LGBM_BAD_ASYM_2"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
NA = "NA_NOT_AUTHORIZED_OR_NO_FROZEN_RULE"

ROOTS = {
    "R3": RESULTS / "A2_STOCK_RISK_ML_R3",
    "R3R": RESULTS / "A2_STOCK_RISK_R3A_R3R",
    "R6": R6_ROOT,
    "R6E": RESULTS / "A2_STOCK_RISK_R6E",
    "R7": RESULTS / "A2_STOCK_RISK_R7",
    "R8": RESULTS / "A2_STOCK_RISK_R8",
    "R9": RESULTS / "A2_STOCK_RISK_R9",
}
AUTH_FILES = {
    "R3": ["stock_risk_r3_summary.json", "stock_risk_r3_audit.json", "stock_risk_r3_oof_predictions.parquet"],
    "R3R": ["r3a_r3r_summary.json", "r3a_r3r_audit.json", "r3r_oof_predictions.parquet"],
    "R6": ["r6_summary.json", "r6_audit.json", "r6_oof_predictions.parquet"],
    "R6E": ["r6e_summary.json", "r6e_audit.json", "r6e_strategy_metrics.csv"],
    "R7": ["r7_summary.json", "r7_audit.json", "r7_run_manifest.json", "r7_oof_predictions.parquet"],
    "R8": ["r8_summary.json", "r8_audit.json", "r8_run_manifest.json", "r8_oof_predictions.parquet"],
    "R9": ["r9_summary.json", "r9_audit.json", "r9_run_manifest.json", "r9_oof_predictions.parquet"],
}


def import_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R7 = import_path("a2_r7_for_r10r11", REPO / "scripts/v22/a2_stock_risk_r7.py")
R6, R3, R1 = R7.R6, R7.R3, R7.R1
HOLDOUT = import_path("a2_holdout_for_r11", REPO / "scripts/v22/a_a2_2026_pre_risk_holdout_r1.py")


def sha(path: Path) -> str:
    return R1.sha256_file(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_inventory() -> tuple[dict[str, dict[str, str]], list[str]]:
    inventory: dict[str, dict[str, str]] = {}
    missing: list[str] = []
    for experiment, names in AUTH_FILES.items():
        inventory[experiment] = {}
        for name in names:
            path = ROOTS[experiment] / name
            if not path.is_file():
                missing.append(str(path))
            else:
                inventory[experiment][name] = sha(path)
    return inventory, missing


def lineage_table() -> pd.DataFrame:
    r3 = read_json(ROOTS["R3"] / "stock_risk_r3_summary.json")
    r3r = read_json(ROOTS["R3R"] / "r3a_r3r_summary.json")
    r6 = read_json(ROOTS["R6"] / "r6_summary.json")
    r6e = read_json(ROOTS["R6E"] / "r6e_summary.json")
    r7 = read_json(ROOTS["R7"] / "r7_summary.json")
    r8 = read_json(ROOTS["R8"] / "r8_summary.json")
    r9 = read_json(ROOTS["R9"] / "r9_summary.json")
    base6 = float(r6["BAD_ASYMMETRY_BASE_RATE"])
    rows = [
        {
            "experiment": "R3", "research_question": "predict absolute stock 5D MAE among frozen A2 Top20", "observation_unit": "date,ticker",
            "target": "conditional Q90 execution-misaligned 5D stock MAE", "primary_model": r3["REFERENCE_MODEL"],
            "AUROC": r3["OOF_AUROC"], "AP": r3["OOF_AVERAGE_PRECISION"], "AP_base_multiple": r3["OOF_AVERAGE_PRECISION"] / r3["selected_diagnostic"]["severe_base_rate"],
            "positive_folds": r3["POSITIVE_DIRECTION_FOLDS"], "top_decile_lift": r3["TOP_DECILE_SEVERE_LOSS_LIFT"],
            "worst100_capture": np.nan, "best100_capture": np.nan, "worst_best_ratio": np.nan,
            "economic_test_authorized": True, "economic_result": "D_RETURN_DESTRUCTION;useful_folds=1",
            "classification": r3["A2_STOCK_RISK_R3_CLASSIFICATION"], "final_disposition": "REJECT_AS_PRIMARY_DIRECTIONAL_RISK_SIGNAL",
        },
        {
            "experiment": "R6", "research_question": "predict execution-aligned severe downside with weak favorable excursion", "observation_unit": "date,ticker",
            "target": "MAE>=training Q90 AND MFE<=training Q50", "primary_model": r6["REFERENCE_MODEL"],
            "AUROC": r6["OOF_AUROC"], "AP": r6["OOF_AVERAGE_PRECISION"], "AP_base_multiple": r6["OOF_AVERAGE_PRECISION"] / base6,
            "positive_folds": r6["POSITIVE_DIRECTION_FOLDS"], "top_decile_lift": r6["TOP_DECILE_BAD_ASYMMETRY_LIFT"],
            "worst100_capture": r6["TOP_DECILE_WORST100_CAPTURE"], "best100_capture": r6["TOP_DECILE_BEST100_CAPTURE"], "worst_best_ratio": r6["TOP_DECILE_WORST100_CAPTURE"] / r6["TOP_DECILE_BEST100_CAPTURE"],
            "economic_test_authorized": False, "economic_result": "NOT_RUN_IN_FORMAL_R6_PREDICTIVE_GATE_FAILED",
            "classification": r6["A2_STOCK_RISK_R6_CLASSIFICATION"], "final_disposition": "PRESERVE_AS_BEST_CURRENT_STOCK_RISK_SIGNAL",
        },
        {
            "experiment": "R6E", "research_question": "exploratory economics of frozen R6 predictions and frozen sparse rule", "observation_unit": "date,ticker",
            "target": "unchanged frozen R6 bad asymmetry", "primary_model": R6_REFERENCE_MODEL,
            "AUROC": r6["OOF_AUROC"], "AP": r6["OOF_AVERAGE_PRECISION"], "AP_base_multiple": r6["OOF_AVERAGE_PRECISION"] / base6,
            "positive_folds": r6["POSITIVE_DIRECTION_FOLDS"], "top_decile_lift": r6["TOP_DECILE_BAD_ASYMMETRY_LIFT"],
            "worst100_capture": r6["TOP_DECILE_WORST100_CAPTURE"], "best100_capture": r6["TOP_DECILE_BEST100_CAPTURE"], "worst_best_ratio": r6["TOP_DECILE_WORST100_CAPTURE"] / r6["TOP_DECILE_BEST100_CAPTURE"],
            "economic_test_authorized": True, "economic_result": f"{r6e['ECONOMIC_DIAGNOSTIC']};useful_folds={r6e['R6_USEFUL_ECONOMIC_FOLDS']}",
            "classification": f"FORMAL_R6={r6e['FORMAL_R6_CLASSIFICATION']};ECONOMIC={r6e['ECONOMIC_DIAGNOSTIC']}", "final_disposition": "PRESERVE_AS_PARTIAL_ECONOMIC_EVIDENCE",
        },
        {
            "experiment": "R7", "research_question": "unified stock-level market/A2/stock/risk information", "observation_unit": "date,ticker",
            "target": "unchanged frozen R6 bad asymmetry", "primary_model": "R7_LIGHTGBM_FIXED",
            "AUROC": r7["R7_ML_AUROC"], "AP": r7["R7_ML_AP"], "AP_base_multiple": r7["R7_ML_AP_BASE_MULTIPLE"],
            "positive_folds": r7["R7_POSITIVE_DIRECTION_FOLDS"], "top_decile_lift": r7["R7_ML_TOP_DECILE_LIFT"],
            "worst100_capture": r7["R7_WORST100_CAPTURE"], "best100_capture": r7["R7_BEST100_CAPTURE"], "worst_best_ratio": r7["R7_WORST_BEST_RATIO"],
            "economic_test_authorized": False, "economic_result": "NOT_AUTHORIZED", "classification": r7["A2_STOCK_RISK_R7_CLASSIFICATION"], "final_disposition": "CLOSED_NO_INCREMENTAL_UNIFIED_ML_VALUE",
        },
        {
            "experiment": "R8", "research_question": "separate bad-tail risk from good-tail opportunity", "observation_unit": "date,ticker",
            "target": "frozen R6 bad head plus symmetric fixed good head", "primary_model": "R8_BAD_AND_GOOD_FIXED_LIGHTGBM",
            "AUROC": r8["BAD_HEAD_AUROC"], "AP": r8["BAD_HEAD_AP"], "AP_base_multiple": r8["BAD_HEAD_AP"] / r8["BAD_BASE_RATE"],
            "positive_folds": r8["BAD_HEAD_POSITIVE_FOLDS"], "top_decile_lift": r8["BAD_HEAD_TOP_DECILE_LIFT"],
            "worst100_capture": r8["DUAL_SCORE_A_WORST100_CAPTURE"], "best100_capture": r8["DUAL_SCORE_A_BEST100_CAPTURE"], "worst_best_ratio": r8["DUAL_SCORE_A_WORST_BEST_RATIO"],
            "economic_test_authorized": False, "economic_result": "NOT_AUTHORIZED", "classification": r8["A2_STOCK_RISK_R8_CLASSIFICATION"], "final_disposition": "CLOSED_NO_USEFUL_DUAL_TAIL_INCREMENT",
        },
        {
            "experiment": "R9", "research_question": "predict portfolio-date severe downside regime", "observation_unit": "date",
            "target": "future portfolio MAE H=1 <= fold-training Q10", "primary_model": "R9_LIGHTGBM_FIXED",
            "AUROC": r9["R9_ML_AUROC"], "AP": r9["R9_ML_AP"], "AP_base_multiple": r9["R9_ML_AP_BASE_MULTIPLE"],
            "positive_folds": r9["R9_POSITIVE_DIRECTION_FOLDS"], "top_decile_lift": r9["R9_ML_TOP_DECILE_LIFT"],
            "worst100_capture": np.nan, "best100_capture": np.nan, "worst_best_ratio": np.nan,
            "economic_test_authorized": False, "economic_result": "NOT_AUTHORIZED", "classification": r9["A2_STOCK_RISK_R9_CLASSIFICATION"], "final_disposition": "CLOSED_NO_USEFUL_PORTFOLIO_REGIME_SIGNAL",
        },
    ]
    # R3R is recovered as the execution-aligned bridge supporting the R6 lineage.
    for row in rows:
        row["r3r_execution_alignment_reference"] = r3r["R3R_REFERENCE_MODEL"]
    return pd.DataFrame(rows)


def run_r10(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"R10 output already exists: {output}")
    output.mkdir(parents=True, exist_ok=True)
    guard_pre = R1.guard_audit()
    inventory, missing = file_inventory()
    r6_hash = sha(R6_OOF)
    target_id, fold_id = R7.R6_TARGET_CONTRACT_ID, R7.R6_FOLD_CONTRACT_ID
    identity = bool(r6_hash == R6_OOF_EXPECTED and target_id == R6_TARGET_ID_EXPECTED and fold_id == R6_FOLD_ID_EXPECTED)
    if missing or not identity:
        raise RuntimeError(f"R6/lineage identity failure: missing={missing},r6={r6_hash},target={target_id},fold={fold_id}")
    lineage = lineage_table()
    R1.write_csv(output / "r10_research_lineage.csv", lineage)
    summary = {
        "R10_STATUS": "PASS", "R10_CLASSIFICATION": "PASS_IMMUTABLE_PRE2026_RISK_RESEARCH_CLOSEOUT",
        "BEST_CURRENT_STOCK_RISK_SIGNAL": "R6_BAD_ASYMMETRY", "PRE2026_NEW_RISK_MODEL_DISCOVERY_STATUS": "STOPPED",
        "R7_LINE_STATUS": "CLOSED", "R8_LINE_STATUS": "CLOSED", "R9_REGIME_LINE_STATUS": "CLOSED",
        "R6_TARGET_CONTRACT_ID": target_id, "R6_FOLD_CONTRACT_ID": fold_id, "R6_OOF_HASH": r6_hash,
        "R6_IDENTITY_PASS": True, "R3_R9_AUTHORITATIVE_ARTIFACTS_READABLE": True,
        "NO_NEW_MODEL_FIT": True, "NO_NEW_PARAMETER_SEARCH": True, "NO_NEW_THRESHOLD_SEARCH": True,
        "R11_2026_PROSPECTIVE_AUTHORIZED": True,
    }
    R1.write_json(output / "r10_closeout_summary.json", summary)
    freeze_payload = {
        "freeze_name": "A2_STOCK_RISK_RESEARCH_CLOSEOUT_R10", "schema": "R10_IMMUTABLE_CLOSEOUT_V1",
        "authoritative_input_hashes": inventory,
        "r6_identity": {"target_contract_id": target_id, "fold_contract_id": fold_id, "oof_sha256": r6_hash},
        "conclusions": {
            "BEST_CURRENT_STOCK_RISK_SIGNAL": "R6_BAD_ASYMMETRY", "PRE2026_NEW_RISK_MODEL_DISCOVERY_STATUS": "STOPPED",
            "R7_LINE_STATUS": "CLOSED", "R8_LINE_STATUS": "CLOSED", "R9_REGIME_LINE_STATUS": "CLOSED",
        },
        "prohibitions": ["DO_NOT_TUNE_R6", "DO_NOT_REDEFINE_R6_TARGET", "DO_NOT_SEARCH_NEW_R6_THRESHOLD", "DO_NOT_REOPEN_R7_R8_R9_USING_2026_RESULTS"],
        "lineage_sha256": sha(output / "r10_research_lineage.csv"), "summary_sha256": sha(output / "r10_closeout_summary.json"),
    }
    freeze_hash = R1.canonical_hash(freeze_payload)
    manifest = {"freeze_payload": freeze_payload, "freeze_hash": freeze_hash, "created_at_utc": datetime.now(timezone.utc).isoformat()}
    R1.write_json(output / "r10_freeze_manifest.json", manifest)
    freeze_hash_pass = R1.canonical_hash(read_json(output / "r10_freeze_manifest.json")["freeze_payload"]) == freeze_hash
    guard_post = R1.guard_audit()
    pre, post = set(guard_pre.get("preexisting_violations", [])), set(guard_post.get("preexisting_violations", []))
    audit = {
        "pass_gate": {"R6_IDENTITY_PASS": identity, "R3_R9_AUTHORITATIVE_ARTIFACTS_READABLE": not missing,
                      "NO_NEW_MODEL_FIT": True, "NO_NEW_PARAMETER_SEARCH": True, "NO_NEW_THRESHOLD_SEARCH": True,
                      "FREEZE_MANIFEST_WRITTEN": (output / "r10_freeze_manifest.json").is_file(), "FREEZE_HASH_PASS": freeze_hash_pass},
        "freeze_manifest_file_sha256": sha(output / "r10_freeze_manifest.json"), "input_inventory": inventory,
        "model_fit_count": 0, "parameter_search_count": 0, "threshold_search_count": 0,
        "2026_file_read_count": 0, "new_repo_violations": sorted(post - pre), "repository_governance": guard_post,
    }
    if not all(audit["pass_gate"].values()) or audit["new_repo_violations"]:
        raise RuntimeError(f"R10 pass gate failure: {audit['pass_gate']},new={audit['new_repo_violations']}")
    summary["R10_FREEZE_HASH"] = freeze_hash
    R1.write_json(output / "r10_closeout_summary.json", summary)
    # Update the summary digest after adding only the externally reported freeze hash; freeze payload remains immutable.
    audit["final_summary_sha256"] = sha(output / "r10_closeout_summary.json")
    R1.write_json(output / "r10_audit.json", audit)
    print(f"R10_STATUS={summary['R10_STATUS']}")
    print(f"R10_CLASSIFICATION={summary['R10_CLASSIFICATION']}")
    print(f"R10_FREEZE_HASH={freeze_hash}")
    return summary


def verify_r10() -> dict[str, Any]:
    summary = read_json(R10_ROOT / "r10_closeout_summary.json")
    manifest = read_json(R10_ROOT / "r10_freeze_manifest.json")
    if summary.get("R10_CLASSIFICATION") != "PASS_IMMUTABLE_PRE2026_RISK_RESEARCH_CLOSEOUT":
        raise RuntimeError("R10 authorization absent")
    if R1.canonical_hash(manifest["freeze_payload"]) != manifest["freeze_hash"] or summary.get("R10_FREEZE_HASH") != manifest["freeze_hash"]:
        raise RuntimeError("R10 freeze hash failure")
    for experiment, files in manifest["freeze_payload"]["authoritative_input_hashes"].items():
        for name, expected in files.items():
            if sha(ROOTS[experiment] / name) != expected:
                raise RuntimeError(f"post-closeout mutation: {experiment}/{name}")
    return summary


def deploy_r6(output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    panel, _, _, _, _, _, _ = R6.load_inputs()
    if panel.signal_date.ge(TRAINING_CUTOFF).any() or panel.target_end_date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("deployment training crosses 2026")
    mae = float(panel.forward_5d_stock_mae.quantile(R6.MAE_SEVERE_QUANTILE))
    mfe = float(panel.forward_5d_stock_mfe.quantile(R6.MFE_COMPENSATION_QUANTILE))
    y, _ = R6.event_labels(panel, mae, mfe)
    candidate = next(x for x in R6.CANDIDATES if x.candidate_id == R6_REFERENCE_MODEL)
    model = R6.make_model(candidate)
    R6.fit_model(model, candidate, panel[R3.FEATURES], y)
    reference_scores = R6.predict_probability(model, panel)
    spec = {
        "artifact_id": "R6_FROZEN_DEPLOY_R1", "deployment_source": "EXACT_DETERMINISTIC_REMATERIALIZATION_FROM_FROZEN_R6_CONTRACT",
        "reference_model": candidate.candidate_id, "model_family": candidate.family, "candidate_params": candidate.params,
        "full_model_params": model.get_params(), "features": list(R3.FEATURES), "feature_contract_id": R1.canonical_hash(list(R3.FEATURES)),
        "target_contract_id": R6_TARGET_ID_EXPECTED, "mae_threshold_q90_pre2026": mae, "mfe_threshold_q50_pre2026": mfe,
        "training_rows": len(panel), "training_end_date": str(pd.Timestamp(panel.target_end_date.max()).date()),
        "training_row_identity": R1.canonical_hash(panel[["signal_date", "ticker", "target_end_date"]].astype(str).to_dict(orient="records")),
        "reference_score_count": len(reference_scores), "reference_score_sha256": hashlib.sha256(np.sort(reference_scores).astype(np.float64).tobytes()).hexdigest(),
        "fit_count": 1, "2026_model_fit_rows": 0,
    }
    spec["deploy_model_spec_hash"] = R1.canonical_hash(spec)
    artifact = {"model": model, "features": list(R3.FEATURES), "reference_scores_sorted": np.sort(reference_scores), "spec": spec}
    path = output / "r6_frozen_deploy_r1.joblib"
    joblib.dump(artifact, path)
    identity = {**spec, "artifact_path": str(path), "artifact_sha256": sha(path)}
    return artifact, identity


def write_preregistration(output: Path, deploy: dict[str, Any]) -> tuple[dict[str, Any], str]:
    r6e = read_json(ROOTS["R6E"] / "r6e_audit.json")
    rule = r6e.get("position_rule")
    unique_rule = rule == {"risk_percentile_at_least_90": 0.5, "risk_percentile_below_90": 1.0, "removed_weight_destination": "CASH"}
    payload = {
        "schema": "R11_PREREGISTERED_PROSPECTIVE_EVALUATION_V1", "research_only": True,
        "r10_freeze_hash": read_json(R10_ROOT / "r10_closeout_summary.json")["R10_FREEZE_HASH"],
        "r6_deployment": deploy, "r6_feature_contract_id": deploy["feature_contract_id"], "r6_target_contract_id": R6_TARGET_ID_EXPECTED,
        "target": {"definition": "MAE>=frozen pre2026 Q90 AND MFE<=frozen pre2026 Q50", "horizon_sessions": 5,
                   "mae_threshold": deploy["mae_threshold_q90_pre2026"], "mfe_threshold": deploy["mfe_threshold_q50_pre2026"]},
        "evaluation_start_requested": "2026-01-01", "population": "authoritative frozen-A2 2026 Top20 rows with complete five-session execution-open path",
        "maturity_rule": "complete signal-date execution open plus five Moomoo QFQ sessions; incomplete rows excluded, never labeled negative",
        "percentile_reference": "sorted full pre2026 deployment-training predictions only",
        "metrics": ["AUROC", "AP", "AP_BASE", "BRIER", "TOP_DECILE_LIFT_CAPTURE", "MECHANICAL_WORST_BEST_K", "DECILE_MONOTONICITY", "NATURAL_TIME_STABILITY"],
        "predictive_gates": {
            "A": {"auroc": 0.60, "ap_base": 1.30, "top_decile_lift": 1.50, "worst_best_ratio": 2.0, "positive_periods": 2},
            "B": {"auroc": 0.55, "ap_base": 1.10, "top_decile_lift": 1.20, "worst_best_ratio": 1.0},
        },
        "economic_shadow": {"authorized": unique_rule, "source": str(ROOTS["R6E"] / "r6e_audit.json"), "source_sha256": sha(ROOTS["R6E"] / "r6e_audit.json"), "rule": rule},
        "no_tuning_declaration": {"2026_fit": 0, "feature_selection": 0, "parameter_search": 0, "threshold_search": 0, "target_search": 0, "model_selection": 0},
    }
    prereg = {"preregistered_payload": payload, "preregistration_timestamp": datetime.now(timezone.utc).isoformat()}
    prereg["preregistration_hash"] = R1.canonical_hash(payload)
    path = output / "r11_preregistered_evaluation_contract.json"
    R1.write_json(path, prereg)
    file_hash = sha(path)
    if read_json(path)["preregistration_hash"] != R1.canonical_hash(read_json(path)["preregistered_payload"]):
        raise RuntimeError("R11 preregistration hash failure")
    return prereg, file_hash


def _load_market_2026() -> pd.DataFrame:
    pointer = read_json(HOLDOUT.BENCHMARK_POINTER)
    path = Path(pointer["canonical_qfq_path"])
    prices = pd.read_csv(path, usecols=["ticker", "date", "close", "source", "source_policy", "adjustment"])
    prices = prices.loc[prices.ticker.isin(["QQQ", "SPY"])].rename(columns={"date": "trade_date"})
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    if (set(prices.ticker.unique()) != {"QQQ", "SPY"} or not prices.source.astype(str).str.contains("MOOMOO", case=False).all()
            or not prices.adjustment.astype(str).str.upper().eq("QFQ").all() or not prices.source_policy.eq("MOOMOO_ONLY").all()):
        raise RuntimeError("R11 market source integrity failure")
    vix = pd.read_parquet(R1.VIX_PATH, columns=["DATE", "CLOSE"]).rename(columns={"DATE": "market_date", "CLOSE": "vix_close"})
    vix["market_date"] = pd.to_datetime(vix.market_date)
    return R1.build_market_features(prices[["ticker", "trade_date", "close"]].drop_duplicates(["ticker", "trade_date"]), vix)


def load_2026_population(deploy_artifact: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    # First 2026 outcome reads in the run occur below, after preregistration is durably written and verified.
    qqq, qqq_audit = HOLDOUT.load_qqq()
    latest_benchmark = pd.Timestamp(qqq.trade_date.max())
    adapter = HOLDOUT.import_path("a2_r11_frozen_adapter", HOLDOUT.ADAPTER_PATH)
    alpha = HOLDOUT.import_path("a2_r11_frozen_alpha", HOLDOUT.A2_SOURCE)
    prices, ca_events, price_audit = HOLDOUT.build_adjusted_equity_prices(adapter, latest_benchmark + pd.Timedelta(days=1))
    end = min(latest_benchmark, pd.Timestamp(prices.trade_date.max()))
    alpha_model = joblib.load(HOLDOUT.MODEL_PATH)
    signals, eligibility = HOLDOUT.build_signals(alpha, alpha_model, prices, qqq, end)
    top = signals.loc[signals.a2_rank.le(20)].copy().rename(columns={"signal_date": "information_date", "a2_rank": "A2_RANK", "a2_prediction": "A2_PREDICTION"})
    feature_input = prices[["ticker", "trade_date", "close", "volume"]]
    stock = alpha.build_stock_state_features(feature_input).rename(columns={"trade_date": "information_date"})
    panel = top.merge(stock, on=["information_date", "ticker"], how="left", validate="one_to_one")
    market = _load_market_2026()
    latest_common_feature_date = pd.Timestamp(market.market_date.max())
    unscorable_feature_rows = int(top.information_date.gt(latest_common_feature_date).sum())
    panel = panel.loc[panel.information_date.le(latest_common_feature_date)].copy()
    raw_count = len(panel)
    panel = panel.merge(market[["market_date", *R3.MARKET_FEATURES, "QQQ_RETURN_20D"]], left_on="information_date", right_on="market_date", how="left", validate="many_to_one")
    for feature, source in R3.SOURCE_COLUMNS.items():
        panel[feature] = panel[source]
    panel["VOL_ACCELERATION_5D_60D"] = panel.REALIZED_VOL_5D / panel.REALIZED_VOL_60D - 1.0
    panel["STOCK_MINUS_QQQ_20D"] = panel.RET_20D - panel.QQQ_RETURN_20D
    calendar = pd.DatetimeIndex(qqq.trade_date.drop_duplicates().sort_values())
    next_date = {pd.Timestamp(date): pd.Timestamp(calendar[calendar.searchsorted(date, side="right")]) for date in panel.information_date.unique() if calendar.searchsorted(date, side="right") < len(calendar)}
    panel["signal_date"] = panel.information_date.map(next_date)
    panel = panel.loc[panel.signal_date.notna()].copy()
    if panel[R3.FEATURES].isna().any().any() or not panel.information_date.lt(panel.signal_date).all():
        raise RuntimeError("R11 feature completeness/PIT failure")
    model = deploy_artifact["model"]
    panel["R6_frozen_risk_score"] = R6.predict_probability(model, panel)
    reference = np.asarray(deploy_artifact["reference_scores_sorted"], dtype=float)
    panel["R6_risk_percentile_using_pre2026_reference"] = np.searchsorted(reference, panel.R6_frozen_risk_score, side="right") / len(reference)

    bars = prices[["ticker", "trade_date", "open", "high", "low", "close", "autype", "source"]].copy()
    bar_map = {(str(x.ticker), pd.Timestamp(x.trade_date)): x for x in bars.itertuples(index=False)}
    outcomes = []
    for row in panel[["signal_date", "ticker"]].itertuples(index=False):
        start = int(calendar.get_loc(row.signal_date))
        dates = calendar[start:start + 5]
        found = [bar_map.get((str(row.ticker), pd.Timestamp(date))) for date in dates]
        if len(dates) != 5 or any(x is None for x in found):
            continue
        numeric = np.array([[x.open, x.high, x.low, x.close] for x in found], dtype=float)
        allowed_autype = {"qfq", "pit_forward_rehab_index"}
        allowed_source = {"MOOMOO_OPEND", "MOOMOO_OPEND_RAW_PLUS_REHAB"}
        if (not np.isfinite(numeric).all() or (numeric <= 0).any()
                or any(str(x.autype).lower() not in allowed_autype or str(x.source).upper() not in allowed_source for x in found)):
            continue
        entry = float(found[0].open)
        outcomes.append({
            "signal_date": row.signal_date, "ticker": row.ticker,
            "post_entry_forward_1d_return": float(found[0].close / entry - 1.0),
            "post_entry_forward_5d_return": float(found[-1].close / entry - 1.0),
            "post_entry_5d_mae": max(0.0, float(1.0 - min(x.low for x in found) / entry)),
            "post_entry_5d_mfe": max(0.0, float(max(x.high for x in found) / entry - 1.0)),
            "target_end_date": pd.Timestamp(dates[-1]),
        })
    outcomes = pd.DataFrame(outcomes)
    if outcomes.empty:
        raise RuntimeError("no mature authoritative Moomoo execution paths")
    mature = panel.merge(outcomes, on=["signal_date", "ticker"], how="inner", validate="one_to_one")
    spec = deploy_artifact["spec"]
    mature["bad_target"] = ((mature.post_entry_5d_mae >= spec["mae_threshold_q90_pre2026"]) & (mature.post_entry_5d_mfe <= spec["mfe_threshold_q50_pre2026"])).astype(int)
    mature["realized_outcome"] = mature.post_entry_forward_5d_return
    mature["date"] = mature.signal_date
    audit = {
        "2026_RAW_ROW_COUNT": raw_count, "2026_MATURE_EVALUATION_ROW_COUNT": len(mature),
        "2026_IMMATURE_EXCLUDED_ROW_COUNT": raw_count - len(mature),
        "2026_UNSCORABLE_FEATURE_CUTOFF_ROW_COUNT": unscorable_feature_rows,
        "2026_FIRST_EVAL_DATE": str(pd.Timestamp(mature.signal_date.min()).date()),
        "2026_LAST_MATURE_EVAL_DATE": str(pd.Timestamp(mature.signal_date.max()).date()),
        "latest_common_feature_information_date": str(latest_common_feature_date.date()),
        "latest_benchmark_date": str(latest_benchmark.date()), "latest_equity_price_date": str(pd.Timestamp(prices.trade_date.max()).date()),
        "effective_end_date": str(end.date()), "price_audit": price_audit, "benchmark_audit": qqq_audit,
        "corporate_action_event_count": len(ca_events), "eligibility_rows": len(eligibility),
    }
    last_scored_execution = pd.Timestamp(panel.signal_date.max())
    context = {"prices": prices, "qqq": qqq, "calendar": calendar, "signals": signals, "all_scored": panel, "effective_end": last_scored_execution}
    return mature, panel, audit, context


def predictive_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    y = frame.bad_target.to_numpy(int)
    p = frame.R6_frozen_risk_score.to_numpy(float)
    pct = frame.R6_risk_percentile_using_pre2026_reference.to_numpy(float)
    base = float(y.mean())
    top = pct >= .90
    k = min(100, int(math.floor(.01 * len(frame))))
    worst = frame.nsmallest(k, "post_entry_forward_5d_return") if k else frame.iloc[:0]
    best = frame.nlargest(k, "post_entry_forward_5d_return") if k else frame.iloc[:0]
    wc = float(worst.R6_risk_percentile_using_pre2026_reference.ge(.90).mean()) if k else np.nan
    bc = float(best.R6_risk_percentile_using_pre2026_reference.ge(.90).mean()) if k else np.nan
    ap = float(average_precision_score(y, p))
    return {
        "2026_BASE_EVENT_RATE": base, "2026_AUROC": float(roc_auc_score(y, p)), "2026_AP": ap,
        "2026_AP_BASE_MULTIPLE": ap / base, "2026_BRIER": float(brier_score_loss(y, p)),
        "2026_TOP_DECILE_BAD_EVENT_RATE": float(y[top].mean()) if top.any() else np.nan,
        "2026_TOP_DECILE_LIFT": float(y[top].mean() / base) if top.any() else np.nan,
        "2026_TOP_DECILE_BAD_CAPTURE": float(y[top].sum() / y.sum()) if y.sum() else np.nan,
        "2026_WORST_K": k, "2026_WORST_K_CAPTURE": wc, "2026_BEST_K_CAPTURE": bc,
        "2026_WORST_BEST_CAPTURE_RATIO": wc / bc if bc > 0 else (np.inf if wc > 0 else np.nan),
    }


def decile_table(frame: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    data = frame.copy()
    data["risk_decile"] = np.clip(np.ceil(data.R6_risk_percentile_using_pre2026_reference * 10), 1, 10).astype(int)
    table = data.groupby("risk_decile", as_index=False).agg(
        row_count=("ticker", "size"), bad_event_rate=("bad_target", "mean"),
        mean_realized_return=("post_entry_forward_5d_return", "mean"), median_realized_return=("post_entry_forward_5d_return", "median"),
        mean_MAE=("post_entry_5d_mae", "mean"), mean_MFE=("post_entry_5d_mfe", "mean"),
    )
    return table, float(table.risk_decile.corr(table.bad_event_rate, method="spearman")), float(table.risk_decile.corr(table.mean_realized_return, method="spearman"))


def time_stability(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], int]:
    rows, directions, positive = [], {}, 0
    quarters = [("2026_Q1", "2026-01-01", "2026-03-31"), ("2026_Q2", "2026-04-01", "2026-06-30"), ("2026_Q3", "2026-07-01", "2026-09-30")]
    for name, start, end in quarters:
        part = frame.loc[frame.signal_date.between(start, end)]
        sufficient = len(part) >= 50 and part.bad_target.nunique() == 2
        if sufficient:
            metric = predictive_metrics(part)
            direction = "POSITIVE" if metric["2026_AUROC"] > .5 and metric["2026_AP_BASE_MULTIPLE"] > 1 and metric["2026_TOP_DECILE_LIFT"] > 1 else "NEGATIVE"
            positive += int(direction == "POSITIVE")
            rows.append({"segment_type": "QUARTER", "segment": name, "rows": len(part), "AUROC": metric["2026_AUROC"], "AP": metric["2026_AP"], "AP_base": metric["2026_AP_BASE_MULTIPLE"], "top_decile_lift": metric["2026_TOP_DECILE_LIFT"], "direction": direction})
        else:
            direction = "INSUFFICIENT"
            rows.append({"segment_type": "QUARTER", "segment": name, "rows": len(part), "direction": direction})
        directions[name] = direction
    for month, part in frame.groupby(frame.signal_date.dt.to_period("M")):
        high = part.R6_risk_percentile_using_pre2026_reference.ge(.90)
        rows.append({"segment_type": "MONTH", "segment": str(month), "rows": len(part), "high_risk_bad_rate": part.loc[high, "bad_target"].mean(), "low_risk_bad_rate": part.loc[~high, "bad_target"].mean(), "direction": "DIAGNOSTIC_ONLY"})
    return pd.DataFrame(rows), directions, positive


def economic_shadow(mature: pd.DataFrame, context: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any], str]:
    scored = context["all_scored"].copy()
    scored["multiplier"] = np.where(scored.R6_risk_percentile_using_pre2026_reference.ge(.90), .50, 1.0)
    mean_exposure = float(scored.groupby("information_date").multiplier.mean().mean())
    def target_map(kind: str) -> dict[pd.Timestamp, dict[str, float]]:
        result = {}
        for date, group in scored.groupby("information_date"):
            if kind == "RAW_A2": weights = dict(zip(group.ticker.astype(str), np.repeat(.05, len(group))))
            elif kind == "CONSTANT_MATCHED": weights = dict(zip(group.ticker.astype(str), np.repeat(.05 * mean_exposure, len(group))))
            else: weights = dict(zip(group.ticker.astype(str), .05 * group.multiplier))
            result[pd.Timestamp(date)] = weights
        return result
    qqq = context["qqq"]
    prices = context["prices"]
    all_prices = pd.concat([prices, qqq[["ticker", "trade_date", "open", "close"]].assign(volume=np.nan, autype="qfq", source="MOOMOO_ONLY_PROMOTED")], ignore_index=True, sort=False)
    paths = {name: HOLDOUT.reconstruct_open_ended(name, target_map(name), all_prices, context["calendar"], context["effective_end"]) for name in ["RAW_A2", "CONSTANT_MATCHED", "R6_SHADOW"]}
    rows = []
    for name, path in paths.items():
        daily = path.daily
        metric = HOLDOUT.metric_set(daily.daily_return, daily.nav, daily.turnover)
        r = daily.daily_return.iloc[1:]
        q = r.quantile(.05)
        metric["expected_shortfall_5"] = float(r.loc[r <= q].mean())
        metric["mean_exposure"] = float(daily.exposure.mean())
        rows.append({"strategy": name, **metric})
    table = pd.DataFrame(rows)
    joined = mature[["signal_date", "ticker", "post_entry_forward_5d_return", "R6_risk_percentile_using_pre2026_reference"]].copy()
    joined["multiplier"] = np.where(joined.R6_risk_percentile_using_pre2026_reference.ge(.90), .50, 1.0)
    removed = .05 * (1 - joined.multiplier) * joined.post_entry_forward_5d_return
    loss, winner = float(-removed.loc[removed < 0].sum()), float(removed.loc[removed > 0].sum())
    ratio = loss / winner if winner > 0 else np.inf
    concentration = float(removed.abs().max() / removed.abs().sum()) if removed.abs().sum() else np.nan
    by = table.set_index("strategy")
    raw, const, shadow = by.loc["RAW_A2"], by.loc["CONSTANT_MATCHED"], by.loc["R6_SHADOW"]
    attribution = {
        "R6_GROSS_LOSS_AVOIDED": loss, "R6_WINNER_UPSIDE_SACRIFICED": winner,
        "R6_LOSS_AVOIDED_TO_WINNER_SACRIFICE_RATIO": ratio, "R6_NET_SCALING_VALUE": loss - winner,
        "largest_removed_contribution_share": concentration,
        "R6_VS_CONSTANT_RETURN_DELTA": shadow.total_return - const.total_return,
        "R6_VS_CONSTANT_SHARPE_DELTA": shadow.sharpe - const.sharpe,
        "R6_VS_CONSTANT_MDD_DELTA": shadow.maximum_drawdown - const.maximum_drawdown,
    }
    positive = bool(shadow.sharpe >= const.sharpe and shadow.maximum_drawdown >= const.maximum_drawdown and ratio > 1 and concentration < .50)
    negative = bool(shadow.sharpe < const.sharpe and shadow.maximum_drawdown < const.maximum_drawdown and ratio <= 1)
    return table, attribution, "ECONOMIC_POSITIVE" if positive else "ECONOMIC_NEGATIVE" if negative else "ECONOMIC_MIXED"


def classify_predictive(m: dict[str, Any], positive_periods: int) -> str:
    ratio = m["2026_WORST_BEST_CAPTURE_RATIO"]
    a = m["2026_AUROC"] >= .60 and m["2026_AP_BASE_MULTIPLE"] >= 1.30 and m["2026_TOP_DECILE_LIFT"] >= 1.50 and ratio >= 2 and positive_periods >= 2
    b = m["2026_AUROC"] > .55 and m["2026_AP_BASE_MULTIPLE"] > 1.10 and m["2026_TOP_DECILE_LIFT"] > 1.20 and ratio > 1
    reverse = sum([m["2026_AUROC"] <= .50, m["2026_AP_BASE_MULTIPLE"] <= 1, m["2026_TOP_DECILE_LIFT"] <= 1, ratio <= 1])
    return "A_STRONG_PROSPECTIVE_CONFIRMATION" if a else "B_MODERATE_PROSPECTIVE_CONFIRMATION" if b else "D_FAILED_TO_GENERALIZE" if reverse >= 3 else "C_INCONCLUSIVE_PARTIAL"


def run_r11(output: Path) -> dict[str, Any]:
    verify_r10()
    output.mkdir(parents=True, exist_ok=True)
    guard_pre = R1.guard_audit()
    existing = {p.name for p in output.iterdir()}
    prereg_name, model_name = "r11_preregistered_evaluation_contract.json", "r6_frozen_deploy_r1.joblib"
    if existing:
        if existing != {prereg_name, model_name}:
            raise RuntimeError(f"R11 output contains non-resumable artifacts: {sorted(existing)}")
        deploy_artifact = joblib.load(output / model_name)
        deploy = {**deploy_artifact["spec"], "artifact_path": str(output / model_name), "artifact_sha256": sha(output / model_name)}
        prereg = read_json(output / prereg_name)
        prereg_file_hash = sha(output / prereg_name)
        if prereg["preregistered_payload"]["r6_deployment"]["artifact_sha256"] != deploy["artifact_sha256"]:
            raise RuntimeError("resumed deployment/preregistration artifact mismatch")
        if prereg["preregistration_hash"] != R1.canonical_hash(prereg["preregistered_payload"]):
            raise RuntimeError("resumed preregistration hash failure")
    else:
        deploy_artifact, deploy = deploy_r6(output)
        prereg, prereg_file_hash = write_preregistration(output, deploy)
    prereg_time = pd.Timestamp(prereg["preregistration_timestamp"])
    outcome_read_time = pd.Timestamp.now(tz="UTC")
    if outcome_read_time <= prereg_time:
        raise RuntimeError("2026 outcome read did not follow preregistration")
    mature, all_scored, population_audit, context = load_2026_population(deploy_artifact)
    if mature.empty or mature.signal_date.dt.year.ne(2026).any():
        raise RuntimeError("invalid R11 evaluation population")
    metrics = predictive_metrics(mature)
    deciles, bad_spear, return_spear = decile_table(mature)
    stability, directions, positive_periods = time_stability(mature)
    predictive_class = classify_predictive(metrics, positive_periods)
    target_hash = R1.canonical_hash({"r6_target_contract_id": R6_TARGET_ID_EXPECTED, "mae_threshold": deploy["mae_threshold_q90_pre2026"], "mfe_threshold": deploy["mfe_threshold_q50_pre2026"], "horizon": 5})

    economic_authorized = prereg["preregistered_payload"]["economic_shadow"]["authorized"]
    if economic_authorized:
        economics, attribution, economic_class = economic_shadow(mature, context)
        R1.write_csv(output / "r11_2026_economic_comparison.csv", economics)
        R1.write_json(output / "r11_2026_economic_attribution.json", attribution)
        economic_status = "RUN_EXACT_FROZEN_R6E_RULE"
        eby = economics.set_index("strategy")
        raw, const, shadow = eby.loc["RAW_A2"], eby.loc["CONSTANT_MATCHED"], eby.loc["R6_SHADOW"]
    else:
        attribution, economic_class, economic_status = {}, NA, "NOT_RUN_NO_UNIQUE_FROZEN_RULE"
        raw = const = shadow = pd.Series(dtype=float)
    if predictive_class.startswith("A_") and economic_class != "ECONOMIC_NEGATIVE": final_class = "A_PROSPECTIVE_CONFIRMED"
    elif predictive_class.startswith("B_") or (predictive_class.startswith("A_") and economic_class == "ECONOMIC_MIXED"): final_class = "B_PROSPECTIVE_SUPPORTED"
    elif predictive_class.startswith("D_"): final_class = "D_PROSPECTIVE_FAILED"
    else: final_class = "C_PROSPECTIVE_INCONCLUSIVE"
    next_steps = {
        "A_PROSPECTIVE_CONFIRMED": "PRESERVE_R6_FROZEN_AND_BEGIN_FORWARD_SHADOW_ACCUMULATION;DO_NOT_RETUNE",
        "B_PROSPECTIVE_SUPPORTED": "CONTINUE_R6_FORWARD_SHADOW_WITHOUT_MODEL_CHANGES",
        "C_PROSPECTIVE_INCONCLUSIVE": "ACCUMULATE_MORE_PROSPECTIVE_EVIDENCE;NO_RETUNING",
        "D_PROSPECTIVE_FAILED": "REJECT_R6_FOR_DEPLOYMENT;PRESERVE_FOR_RESEARCH_HISTORY;DO_NOT_MINE_2026_FOR_REPLACEMENT",
    }
    guard_post = R1.guard_audit()
    pre, post = set(guard_pre.get("preexisting_violations", [])), set(guard_post.get("preexisting_violations", []))
    new_violations = sorted(post - pre)
    summary = {
        "R10_STATUS": "PASS", "R10_CLASSIFICATION": "PASS_IMMUTABLE_PRE2026_RISK_RESEARCH_CLOSEOUT", "R10_FREEZE_HASH": read_json(R10_ROOT / "r10_closeout_summary.json")["R10_FREEZE_HASH"],
        "PRE2026_NEW_RISK_MODEL_DISCOVERY_STATUS": "STOPPED", "BEST_CURRENT_STOCK_RISK_SIGNAL": "R6_BAD_ASYMMETRY",
        "R11_STATUS": "PASS_VALID_PROSPECTIVE_EVALUATION", "R11_CLASSIFICATION": final_class,
        "R6_DEPLOYMENT_SOURCE": deploy["deployment_source"], "R6_DEPLOYMENT_MODEL_HASH": deploy["artifact_sha256"],
        "R6_TARGET_CONTRACT_ID": R6_TARGET_ID_EXPECTED, "R6_FEATURE_CONTRACT_ID": deploy["feature_contract_id"],
        "2026_FIRST_EVAL_DATE": population_audit["2026_FIRST_EVAL_DATE"], "2026_LAST_MATURE_EVAL_DATE": population_audit["2026_LAST_MATURE_EVAL_DATE"],
        "2026_MATURE_EVALUATION_ROWS": len(mature), **metrics,
        "RISK_DECILE_BAD_RATE_SPEARMAN": bad_spear, "RISK_DECILE_RETURN_SPEARMAN": return_spear,
        "2026_Q1_DIRECTION": directions["2026_Q1"], "2026_Q2_DIRECTION": directions["2026_Q2"], "2026_Q3_DIRECTION": directions["2026_Q3"],
        "R11_PREDICTIVE_CLASSIFICATION": predictive_class, "R11_ECONOMIC_SHADOW_STATUS": economic_status, "R11_ECONOMIC_CLASSIFICATION": economic_class,
        "RAW_A2_RETURN": raw.get("total_return", NA), "CONSTANT_MATCHED_RETURN": const.get("total_return", NA), "R6_SHADOW_RETURN": shadow.get("total_return", NA),
        "RAW_A2_SHARPE": raw.get("sharpe", NA), "CONSTANT_MATCHED_SHARPE": const.get("sharpe", NA), "R6_SHADOW_SHARPE": shadow.get("sharpe", NA),
        "RAW_A2_MDD": raw.get("maximum_drawdown", NA), "CONSTANT_MATCHED_MDD": const.get("maximum_drawdown", NA), "R6_SHADOW_MDD": shadow.get("maximum_drawdown", NA),
        "R6_GROSS_LOSS_AVOIDED": attribution.get("R6_GROSS_LOSS_AVOIDED", NA), "R6_WINNER_UPSIDE_SACRIFICED": attribution.get("R6_WINNER_UPSIDE_SACRIFICED", NA),
        "R6_LOSS_AVOIDED_TO_WINNER_SACRIFICE_RATIO": attribution.get("R6_LOSS_AVOIDED_TO_WINNER_SACRIFICE_RATIO", NA), "R6_NET_SCALING_VALUE": attribution.get("R6_NET_SCALING_VALUE", NA),
        "R11_PRE2026_DEPLOYMENT_MODEL_FIT_COUNT": 1, "2026_MODEL_FIT_ROWS": 0, "2026_PARAMETER_SEARCH_COUNT": 0,
        "2026_THRESHOLD_SEARCH_COUNT": 0, "2026_FEATURE_SELECTION_COUNT": 0, "2026_TARGET_SEARCH_COUNT": 0, "2026_MODEL_SELECTION_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": 0, "PIT_AUDIT_STATUS": "PASS", "REPRODUCIBILITY_STATUS": "PASS_EXACT_SAME_ARTIFACT_DOUBLE_PREDICT",
        "ANTI_BLOAT_STATUS": "PASS_NEW_R10_R11_ZERO" if not new_violations else f"FAIL_NEW_VIOLATIONS={len(new_violations)}",
        "NEXT_AUTHORIZED_STEP": next_steps[final_class],
    }
    double = R6.predict_probability(deploy_artifact["model"], all_scored)
    if not np.array_equal(double, all_scored.R6_frozen_risk_score.to_numpy()) or new_violations:
        raise RuntimeError("R11 reproducibility/anti-bloat failure")
    prediction_cols = ["date", "signal_date", "information_date", "ticker", "A2_RANK", "A2_PREDICTION", "R6_frozen_risk_score", "R6_risk_percentile_using_pre2026_reference", "bad_target", "realized_outcome", "post_entry_forward_1d_return", "post_entry_forward_5d_return", "post_entry_5d_mae", "post_entry_5d_mfe", "target_end_date"]
    R1.write_parquet(output / "r11_2026_r6_predictions.parquet", mature[prediction_cols])
    R1.write_csv(output / "r11_2026_time_stability.csv", stability)
    R1.write_csv(output / "r11_2026_risk_deciles.csv", deciles)
    R1.write_json(output / "r11_2026_predictive_metrics.json", {**metrics, "RISK_DECILE_BAD_RATE_SPEARMAN": bad_spear, "RISK_DECILE_RETURN_SPEARMAN": return_spear})
    run_manifest = {
        "run_id": "A2_STOCK_RISK_R11_PROSPECTIVE", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "r10_freeze_hash": summary["R10_FREEZE_HASH"], "preregistration_file_sha256": prereg_file_hash,
        "preregistration_hash": prereg["preregistration_hash"], "preregistration_timestamp": prereg["preregistration_timestamp"],
        "first_2026_outcome_read_timestamp": outcome_read_time.isoformat(), "2026_OUTCOME_READ_AFTER_PREREGISTRATION": "PASS",
        "deployment": deploy, "2026_target_contract_hash": target_hash, "population": population_audit,
        "search_counts": {"parameter": 0, "threshold": 0, "feature": 0, "target": 0, "model_selection": 0},
    }
    audit = {
        "summary": summary, "population": population_audit, "R6_TARGET_IDENTITY_POLICY_PASS": True,
        "2026_TARGET_CONTRACT_HASH": target_hash, "R6E_SCALING_CONTRACT_FOUND": bool(economic_authorized),
        "R6E_SCALING_CONTRACT_HASH": R1.canonical_hash(prereg["preregistered_payload"]["economic_shadow"]["rule"]),
        "R6E_SCALING_RULE_UNIQUELY_REPRODUCIBLE": bool(economic_authorized),
        "preregistration": {"timestamp": prereg["preregistration_timestamp"], "hash": prereg["preregistration_hash"], "file_sha256": prereg_file_hash, "outcome_read_after": "PASS"},
        "firewall": {"2026_model_fit_rows": 0, "parameter_search": 0, "threshold_search": 0, "feature_selection": 0, "target_search": 0, "model_selection": 0},
        "new_repo_violations": new_violations, "repository_governance": guard_post,
    }
    R1.write_json(output / "r11_run_manifest.json", run_manifest)
    R1.write_json(output / "r11_audit.json", audit)
    R1.write_json(output / "r11_summary.json", summary)
    print_final(summary)
    return summary


def print_final(summary: dict[str, Any]) -> None:
    keys = [
        "R10_STATUS", "R10_CLASSIFICATION", "R10_FREEZE_HASH", "PRE2026_NEW_RISK_MODEL_DISCOVERY_STATUS", "BEST_CURRENT_STOCK_RISK_SIGNAL",
        "R11_STATUS", "R11_CLASSIFICATION", "R6_DEPLOYMENT_SOURCE", "R6_DEPLOYMENT_MODEL_HASH", "R6_TARGET_CONTRACT_ID", "R6_FEATURE_CONTRACT_ID",
        "2026_FIRST_EVAL_DATE", "2026_LAST_MATURE_EVAL_DATE", "2026_MATURE_EVALUATION_ROWS", "2026_BASE_EVENT_RATE", "2026_AUROC", "2026_AP", "2026_AP_BASE_MULTIPLE",
        "2026_TOP_DECILE_LIFT", "2026_TOP_DECILE_BAD_CAPTURE", "2026_WORST_K", "2026_WORST_K_CAPTURE", "2026_BEST_K_CAPTURE", "2026_WORST_BEST_CAPTURE_RATIO",
        "RISK_DECILE_BAD_RATE_SPEARMAN", "RISK_DECILE_RETURN_SPEARMAN", "2026_Q1_DIRECTION", "2026_Q2_DIRECTION", "2026_Q3_DIRECTION",
        "R11_PREDICTIVE_CLASSIFICATION", "R11_ECONOMIC_SHADOW_STATUS", "R11_ECONOMIC_CLASSIFICATION",
        "RAW_A2_RETURN", "CONSTANT_MATCHED_RETURN", "R6_SHADOW_RETURN", "RAW_A2_SHARPE", "CONSTANT_MATCHED_SHARPE", "R6_SHADOW_SHARPE",
        "RAW_A2_MDD", "CONSTANT_MATCHED_MDD", "R6_SHADOW_MDD", "R6_GROSS_LOSS_AVOIDED", "R6_WINNER_UPSIDE_SACRIFICED", "R6_LOSS_AVOIDED_TO_WINNER_SACRIFICE_RATIO", "R6_NET_SCALING_VALUE",
        "R11_PRE2026_DEPLOYMENT_MODEL_FIT_COUNT", "2026_MODEL_FIT_ROWS", "2026_PARAMETER_SEARCH_COUNT", "2026_THRESHOLD_SEARCH_COUNT", "2026_FEATURE_SELECTION_COUNT", "2026_TARGET_SEARCH_COUNT", "2026_MODEL_SELECTION_COUNT",
        "LOOKAHEAD_VIOLATION_COUNT", "PIT_AUDIT_STATUS", "REPRODUCIBILITY_STATUS", "ANTI_BLOAT_STATUS", "NEXT_AUTHORIZED_STEP",
    ]
    for key in keys:
        value = summary[key]
        if isinstance(value, float) and np.isfinite(value): value = f"{value:.12g}"
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["r10", "r11"], required=True)
    args = parser.parse_args()
    try:
        if args.stage == "r10": run_r10(R10_ROOT)
        else: run_r11(R11_ROOT)
        return 0
    except Exception as exc:
        stage = args.stage.upper()
        print(f"{stage}_STATUS=STOP", file=sys.stderr)
        print(f"{stage}_CLASSIFICATION=E_INVALID", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        print("NEXT_AUTHORIZED_STEP=STOP_AND_RESOLVE_CONTRACT", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
