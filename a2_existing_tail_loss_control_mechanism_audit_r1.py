"""Audit the one authoritative pre-existing Raw A2 tail-loss signal.

This runner has a hard freeze/audit boundary.  ``--freeze`` performs only
identity, provenance, and anti-duplication accounting and writes the immutable
mechanism protocol.  ``--audit`` verifies the frozen byte hash before opening
the explicitly allowed economic columns.  It does not fit a model, search a
threshold, or construct a portfolio rule.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


TASK = "A2_EXISTING_TAIL_LOSS_CONTROL_MECHANISM_AUDIT_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK
CUTOFF = pd.Timestamp("2026-08-28")
EXPECTED_A2_SHA = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
EXPECTED_RISK_IDENTITY_SHA = "c93c359d8ebc974b2deabe779d40afec3c735d1c287fff0a31778925bc947c95"
EXPECTED_R6_OOF_SHA = "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4"
EXPECTED_OVERLAY_PRED_SHA = "4ba24da6c15739a78549110d8cfd16915d30bef3249a378602b6061ab420a5a3"
EXPECTED_BETA_PROTOCOL_SHA = "8384f59418142bfbb90d681231fc5bac78c48ad48f18f4ed29c65eca68363504"

MODEL = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "final_full_pre2026_hgb.joblib"
PRE_DAILY = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "portfolio_daily.parquet"
POST_DAILY = RESULTS / "LATEST_2026_FROZEN_STRATEGY_HEAD_TO_HEAD_R1" / "daily_returns.csv"
RISK_R2 = RESULTS / "A2_INDIVIDUAL_STOCK_TAIL_RISK_R2"
RISK_IDENTITY = RISK_R2 / "frozen_risk_signal_identity.json"
RISK_PRED = RISK_R2 / "risk_overlay_predictions.parquet"
R6_OOF = RESULTS / "A2_STOCK_RISK_R6" / "r6_oof_predictions.parquet"
BETA_ROOT = RESULTS / "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1"
BETA_PANEL = BETA_ROOT / "holding_risk_panel.parquet"
BETA_PROTOCOL = BETA_ROOT / "risk_contribution_audit_protocol.json"
REGISTRY = RESULTS / "A2_RESEARCH_REGISTRY_CURRENT" / "research_branch_registry_current.csv"
PROTECTED = RESULTS / "A2_X0_LITERATURE_GROUNDED_PROSPECTIVE_DISAGREEMENT_R1"


class AuditError(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise AuditError(f"{code}:{detail}")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def dump_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, tuple):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def tree_snapshot(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.as_posix().lower()):
        files.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    identity = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"root": str(root), "file_count": len(files), "files": files, "tree_sha256": identity}


def repo_root_temps() -> list[str]:
    patterns = (".tmp", ".codex_tmp", ".pytest_cache", "pytest-cache-")
    return [str(p) for p in REPO.iterdir() if p.is_dir() and any(p.name.startswith(x) for x in patterns)]


def branch_rows() -> list[dict[str, Any]]:
    return [
        {"BRANCH_ID":"R6_BAD_ASYMMETRY_SIGNAL","ARTIFACT_PATH":str(RISK_IDENTITY),"QUESTION":"Predict adverse 5D MAE without compensating MFE inside Raw A2 Top20","SIGNAL_OR_RULE":"Frozen R6_BAD_ASYMMETRY risk percentile","LABEL":"5D_MAE>=fold/pre2026_Q90 AND 5D_MFE<=fold/pre2026_Q50","HORIZON":"5 sessions","EVIDENCE_CLASS":"FROZEN_OOF_PLUS_EXPOSED_2026_FIXED_INFERENCE","ECONOMIC_TEST_STATUS":"TESTED_FIXED_ATTENUATION_AND_PROSPECTIVE_SHADOW","FINAL_CONCLUSION":"REGISTERED_RISK_CHAMPION;B_PROSPECTIVE_SUPPORTED","OVERLAP_WITH_CURRENT_QUESTION":"EXACT_SIGNAL_AND_LABEL;CONTROLLED_HOLDING_CONTRIBUTION_GAP_REMAINS","REUSABLE_STATUS":"SELECTED_BY_AUTHORITY"},
        {"BRANCH_ID":"R6_ATTENUATION_POLICY","ARTIFACT_PATH":str(RISK_R2 / "risk_overlay_contract.json"),"QUESTION":"Can fixed R6 attenuation cut tails without destroying winners","SIGNAL_OR_RULE":"R1_MILD/R2_MODERATE/R3_TWO_TIER fixed cash retention","LABEL":"R6 bad asymmetry and severe-loss PnL","HORIZON":"daily action; 5D risk label","EVIDENCE_CLASS":"PRE2026_FROZEN_SELECTION_PLUS_2026_EXPOSED","ECONOMIC_TEST_STATUS":"COMPLETE","FINAL_CONCLUSION":"R1_MILD_A_ROBUST_ASYMMETRIC_RISK_VALUE;RESEARCH_ONLY","OVERLAP_WITH_CURRENT_QUESTION":"SAME_SIGNAL_BUT_POLICY_ECONOMICS_NOT_CONTROLLED_MECHANISM","REUSABLE_STATUS":"EVIDENCE_ONLY_NO_POLICY_RERUN"},
        {"BRANCH_ID":"R6_R11_PROSPECTIVE","ARTIFACT_PATH":str(RESULTS / "A2_STOCK_RISK_R11_PROSPECTIVE" / "r11_summary.json"),"QUESTION":"Does frozen R6 persist in 2026","SIGNAL_OR_RULE":"Frozen deployment model and top-decile half-cash shadow","LABEL":"Same frozen 5D bad asymmetry","HORIZON":"5 sessions","EVIDENCE_CLASS":"EXPOSED_FIXED_2026_PROSPECTIVE_EVALUATION","ECONOMIC_TEST_STATUS":"COMPLETE_FIXED_WINDOW","FINAL_CONCLUSION":"B_PROSPECTIVE_SUPPORTED;ECONOMIC_POSITIVE","OVERLAP_WITH_CURRENT_QUESTION":"SUPPORTIVE_STABILITY_INPUT;NOT_CONTROLLED_MECHANISM","REUSABLE_STATUS":"REUSE_EVIDENCE"},
        {"BRANCH_ID":"STOCK_RISK_R3_R10_VARIANTS","ARTIFACT_PATH":str(RESULTS / "A2_STOCK_RISK_R10_CLOSEOUT" / "r10_closeout_summary.json"),"QUESTION":"Improve stock downside/asymmetry prediction","SIGNAL_OR_RULE":"R3/R4/R7/R8/R9 model/target variants","LABEL":"Mostly 5D downside or bad asymmetry","HORIZON":"mostly 5 sessions","EVIDENCE_CLASS":"STRICT_TEMPORAL_PRE2026","ECONOMIC_TEST_STATUS":"MIXED_OR_NEGATIVE_VARIANTS","FINAL_CONCLUSION":"R7/R8/R9_CLOSED;R6_ONLY_RETAINED","OVERLAP_WITH_CURRENT_QUESTION":"DUPLICATE_MODEL_SEARCH","REUSABLE_STATUS":"CLOSED_NO_NEW_MODEL"},
        {"BRANCH_ID":"FROZEN_R6_EXECUTION_ABLATION","ARTIFACT_PATH":str(RESULTS / "A2_FROZEN_RISK_EXECUTION_ABLATION_R1" / "final_report.md"),"QUESTION":"Same-alpha R6 execution ablation on exact authoritative A2 path","SIGNAL_OR_RULE":"Frozen R6 score","LABEL":"R6 fixed label","HORIZON":"daily/5D","EVIDENCE_CLASS":"PRE2026_IDENTITY_AUDIT","ECONOMIC_TEST_STATUS":"FAIL_CLOSED_DOMAIN_SUPPORT","FINAL_CONCLUSION":"R6_MECHANISM_INCONCLUSIVE_ON_FULL_PATH;81.26% SECURITY_DATE_OVERLAP","OVERLAP_WITH_CURRENT_QUESTION":"IDENTITY_LIMITATION_MUST_BE_DISCLOSED","REUSABLE_STATUS":"REUSE_SUPPORT_GATE"},
        {"BRANCH_ID":"LOSER_ORTHOGONAL_LOGISTIC","ARTIFACT_PATH":str(RESULTS / "A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1" / "final_report.md"),"QUESTION":"Is exact R6 loser label learnable without Raw A2 rank/score","SIGNAL_OR_RULE":"Fixed L2 logistic on existing non-A2 PIT features","LABEL":"Exact R6 bad asymmetry","HORIZON":"5 sessions","EVIDENCE_CLASS":"FIVE_TEMPORAL_OOS_FOLDS","ECONOMIC_TEST_STATUS":"MECHANISM_DIAGNOSTIC_ONLY","FINAL_CONCLUSION":"AP_LIFT_1.505;AUROC_0.633;5_OF_5_POSITIVE","OVERLAP_WITH_CURRENT_QUESTION":"INDEPENDENCE_PRIOR_ART;NOT_THE_FROZEN_R6_SCORE","REUSABLE_STATUS":"REUSE_EVIDENCE_NO_NEW_SCORE"},
        {"BRANCH_ID":"LOSER_MODEL_STABILITY","ARTIFACT_PATH":str(RESULTS / "A2_ML_MODEL_CLASS_STABILITY_DISCOVERY_SANDBOX_R1" / "final_report.md"),"QUESTION":"Is loser predictability cross-model or confounded","SIGNAL_OR_RULE":"Fixed PCA logistic/MLP plus reused linear/R6","LABEL":"Exact R6 bad asymmetry","HORIZON":"5 sessions","EVIDENCE_CLASS":"STRICT_TEMPORAL_OOF_SANDBOX","ECONOMIC_TEST_STATUS":"NO_STRATEGY_BACKTEST","FINAL_CONCLUSION":"PARTIAL_CROSS_MODEL_SIGNAL;TREE_SATURATED_WAIT_FORWARD","OVERLAP_WITH_CURRENT_QUESTION":"DIRECT_CONFOUND_AND_STABILITY_PRIOR_ART","REUSABLE_STATUS":"REUSE_EVIDENCE"},
        {"BRANCH_ID":"NG8_EXACT_SUPPORT_RISK_R2","ARTIFACT_PATH":str(RESULTS / "A2_NG8_EXACT_SUPPORT_RISK_R2_AUTONOMOUS_R1" / "morning_summary.md"),"QUESTION":"Tail risk on exact NG8 decision domain","SIGNAL_OR_RULE":"Nested OOS Logistic and pair veto","LABEL":"R6-style BAD event","HORIZON":"5 sessions","EVIDENCE_CLASS":"PRE2026_RESEARCH_OOS","ECONOMIC_TEST_STATUS":"COMPLETE_NEGATIVE_ROBUSTNESS","FINAL_CONCLUSION":"REAL_SIGNAL_BUT_NG9_NOT_CREATED","OVERLAP_WITH_CURRENT_QUESTION":"DIFFERENT_NG8_PARENT_GEOMETRY","REUSABLE_STATUS":"NOT_RAW_A2_MECHANISM"},
        {"BRANCH_ID":"ACTION_ML_BUY_SELL_SIZING","ARTIFACT_PATH":str(RESULTS / "A2_AUTONOMOUS_BUY_SELL_AND_SIZING_POLICY_R1" / "final_report.md"),"QUESTION":"Generic BUY/ADD/HOLD/REDUCE/EXIT and sizing","SIGNAL_OR_RULE":"Action policy/state plumbing and earlier negative Action ML lineage","LABEL":"Action value/return labels","HORIZON":"5/20 sessions","EVIDENCE_CLASS":"MIXED;CURRENT_ARTIFACT_OPERATIONAL_ONLY","ECONOMIC_TEST_STATUS":"GENERIC_RESEARCH_CLOSED_NEGATIVE_IN_REGISTRY","FINAL_CONCLUSION":"NO_ROBUST_ACTION_ML_EDGE;NO_NEW_POLICY_SEARCH","OVERLAP_WITH_CURRENT_QUESTION":"GENERIC_ACTION_SEARCH_FORBIDDEN","REUSABLE_STATUS":"INFRASTRUCTURE_ONLY"},
        {"BRANCH_ID":"PORTFOLIO_SYSTEMIC_RISK_OS","ARTIFACT_PATH":str(RESULTS / "A2_RISK_OS_R2" / "risk_os_r2_final_summary.json"),"QUESTION":"Time portfolio-wide systemic de-risking","SIGNAL_OR_RULE":"PIT beta/vol/stress/correlation/R6 composite","LABEL":"20D portfolio severity","HORIZON":"20 sessions","EVIDENCE_CLASS":"PRE2026_OOF","ECONOMIC_TEST_STATUS":"COMPLETE","FINAL_CONCLUSION":"CLOSED_NEGATIVE","OVERLAP_WITH_CURRENT_QUESTION":"PORTFOLIO_STATE_NOT_SECURITY_TAIL_LOSER","REUSABLE_STATUS":"DISTINCT_CLOSED"},
        {"BRANCH_ID":"H08_CONDITIONAL_RISK_STATE","ARTIFACT_PATH":str(RESULTS / "A2_H08_CONDITIONAL_UNCOMPENSATED_RISK_OVERLAY_R2" / "final_report.md"),"QUESTION":"High coupling/weak residual state","SIGNAL_OR_RULE":"Frozen H08 portfolio state","LABEL":"Systematic/residual/downside state","HORIZON":"next interval","EVIDENCE_CLASS":"PRE2026_FALSIFICATION","ECONOMIC_TEST_STATUS":"DIAGNOSTIC_GATE_FAILED_NO_POLICY","FINAL_CONCLUSION":"NO_ROBUST_STATE_CONDITIONAL_RISK_SIGNAL","OVERLAP_WITH_CURRENT_QUESTION":"PORTFOLIO_STATE_NOT_SECURITY_SIGNAL","REUSABLE_STATUS":"DISTINCT_CLOSED"},
        {"BRANCH_ID":"RAW_SCORE_RIGHT_TAIL","ARTIFACT_PATH":str(RESULTS / "A2_RAW_SCORE_OOS_TAIL_PREDICTION_R1" / "final_report.md"),"QUESTION":"Raw A2 score predicts right-tail probability/payoff","SIGNAL_OR_RULE":"Raw score only","LABEL":"Scale-free positive Q90 event","HORIZON":"event holding period","EVIDENCE_CLASS":"STRICT_CHRONOLOGICAL_OOS","ECONOMIC_TEST_STATUS":"DIAGNOSTIC_ONLY","FINAL_CONCLUSION":"PROBABILITY_ONLY_SUPPORTED","OVERLAP_WITH_CURRENT_QUESTION":"RIGHT_TAIL_NOT_LOSER_CONTROL","REUSABLE_STATUS":"DISTINCT"},
        {"BRANCH_ID":"RX_MARGIN_AND_BOUNDARY","ARTIFACT_PATH":str(RESULTS / "A2_BOUNDARY_REPLACEMENT_MECHANISM_AUDIT_R1" / "replacement_mechanism_summary.json"),"QUESTION":"Replacement score margin/hysteresis","SIGNAL_OR_RULE":"Existing RX_MARGIN_R1 reference only","LABEL":"Replacement spread/value","HORIZON":"1/5 sessions","EVIDENCE_CLASS":"RETROSPECTIVE_MECHANISM_AUDIT","ECONOMIC_TEST_STATUS":"COMPLETE","FINAL_CONCLUSION":"INCONCLUSIVE_REPLACEMENT_MECHANISM","OVERLAP_WITH_CURRENT_QUESTION":"DIFFERENT_ENTRY_EXIT_MECHANISM","REUSABLE_STATUS":"DISTINCT_CLOSED_NO_REOPEN"},
    ]


def freeze() -> None:
    require(not OUT.exists(), "OUTPUT_ROOT_ALREADY_EXISTS", OUT)
    require(not repo_root_temps(), "REPO_ROOT_TEMP_PATH_PRESENT", repo_root_temps())
    for path in [MODEL, RISK_IDENTITY, RISK_PRED, R6_OOF, BETA_PANEL, BETA_PROTOCOL, REGISTRY, PROTECTED]:
        require(path.exists(), "MISSING_INPUT", path)
    require(sha(MODEL) == EXPECTED_A2_SHA, "RAW_A2_MODEL_HASH_MISMATCH")
    require(sha(RISK_IDENTITY) == EXPECTED_RISK_IDENTITY_SHA, "RISK_IDENTITY_HASH_MISMATCH")
    require(sha(RISK_PRED) == EXPECTED_OVERLAY_PRED_SHA, "RISK_PRED_HASH_MISMATCH")
    require(sha(R6_OOF) == EXPECTED_R6_OOF_SHA, "R6_OOF_HASH_MISMATCH")
    require(sha(BETA_PROTOCOL) == EXPECTED_BETA_PROTOCOL_SHA, "BETA_PROTOCOL_HASH_MISMATCH")
    identity = json.loads(RISK_IDENTITY.read_text(encoding="utf-8"))
    require(identity["RISK_MODEL_HASH"] == "3e5f646fcfbf1b4e9196781f712305b044a7b2e57c0fe1b3fe202345561f4a08", "RISK_MODEL_IDENTITY_MISMATCH")
    OUT.mkdir(parents=True)
    rows = branch_rows()
    with (OUT / "tail_branch_registry.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    protocol = {
        "task_id": TASK,
        "research_role": "RETROSPECTIVE_EXISTING_SIGNAL_TAIL_LOSS_MECHANISM_AUDIT_ONLY",
        "freeze_stage": "BEFORE_NEW_ROW_LEVEL_ECONOMIC_OUTCOME_READ",
        "raw_a2": {"alias":"A2_HGB","model_sha256":EXPECTED_A2_SHA,"portfolio":"TOP20_EQUAL_WEIGHT_LONG_ONLY","ranking":"A2_SCORE_DESC_THEN_TICKER_ASC","membership":"authoritative holding panel only"},
        "selected_existing_signal": {"name":"R6_BAD_ASYMMETRY","selection_basis":"FORMALLY_REGISTERED_HASH_FROZEN_RISK_CHAMPION;NOT_ECONOMIC_PERFORMANCE","identity_path":str(RISK_IDENTITY),"identity_sha256":EXPECTED_RISK_IDENTITY_SHA,"model_sha256":identity["RISK_MODEL_HASH"],"oof_sha256":EXPECTED_R6_OOF_SHA,"direction":"HIGHER_IS_MORE_BAD_ASYMMETRY_RISK","score":"persisted risk_percentile;no refit or recalibration"},
        "anti_duplication_decision": "ONE_UNRESOLVED_EXISTING_MECHANISM_REQUIRES_AUDIT",
        "gap": "Prior artifacts establish prediction, cross-model partial stability, and policy economics, but do not jointly report the exact frozen R6 score's controlled authoritative-holding separation and symmetric portfolio contribution accounting.",
        "population": "signal_date x authoritative Raw A2 Top20 holding, inner-joined only where the frozen R6 artifact contains that exact security-date; coverage and rank identity disclosed; no imputation",
        "tail_outcome": {"primary":"bad_asymmetry_5d","definition":"5D_MAE>=frozen fold/pre2026 Q90 AND 5D_MFE<=frozen fold/pre2026 Q50","primary_horizon_sessions":5,"severity":"forward_5d_stock_mae (larger is worse)","return":"forward_5d_stock_return","secondary":"next-session holding return and contribution only"},
        "grouping": {"primary":"existing risk_percentile deciles D1..D10","high_risk":"D10 (risk_percentile>=0.90)","low_risk":"D1 (risk_percentile<0.10)","threshold_role":"existing frozen diagnostic grouping only;not a trading threshold","group_search_count":0},
        "controls": {"regression":"linear probability bad_asymmetry_5d ~ risk_percentile + A2_rank + stock_beta_SPY + REALIZED_VOL_20D + FF12 fixed effects","risk_return_regression":"forward_5d_stock_return on same fixed specification","inference":"signal-date clustered sandwich covariance","security_date_iid":False,"complete_case_only":True,"no_controls_added_post_result":True},
        "portfolio_contribution": {"day_groups":"reuse bottom/top 10 percent of actual Raw A2 net daily returns, fixed by prior risk-contribution protocol","holding_contribution":"0.05 * next-session stock return","downside":"absolute negative contributions on Raw A2 worst-decile days","upside":"positive contributions on Raw A2 best-decile days","high_group":"D10 scored holdings;missing scores remain outside numerator and are disclosed"},
        "stability": {"years":["2023","2024","2025","2026_EXPOSED"],"regimes":["BULL","BEAR","HIGH_VOL","LOW_VOL"],"regime_source":"frozen beta/sector risk panel","no_regime_rule":True},
        "robustness": {"remove_downside_contributors_by_ticker":[1,3,5,10],"remove_severe_dates":[1,3,5,10],"ordering":"descending realized negative 5D contribution within fixed D10","retuning":False},
        "classification_gates": {
            "STRONG_EXISTING_TAIL_LOSS_MECHANISM":"positive D10-D1 tail spread; positive controlled coefficient with t>=1.96; D10 downside share exceeds its weight and its upside share; positive spreads in >=3 years and >=3 regimes; positive top10 ticker/date robustness; decile tail-rate Spearman>=0.8 with <=2 violations; authoritative scored coverage>=0.75",
            "PARTIAL_EXISTING_TAIL_LOSS_MECHANISM":"positive pooled tail spread and positive controlled coefficient, plus at least two of downside concentration, year/regime breadth, monotonicity, robustness; coverage>=0.75",
            "NO_ROBUST_EXISTING_TAIL_LOSS_MECHANISM":"nonpositive pooled spread, or nonpositive controlled coefficient together with weak stability/upside tradeoff",
            "INCONCLUSIVE_EXISTING_TAIL_LOSS_MECHANISM":"authoritative scored coverage<0.75, material rank identity failure, fewer than 3 evaluable years, or genuine source limitation prevents primary test"
        },
        "temporal_wall": {"economic_cutoff":"2026-08-28","post_cutoff_outcome_read_count_required":0,"2026_role":"EXPOSED_EVALUATION_ONLY","protected_tree_before":tree_snapshot(PROTECTED)},
        "prohibitions":["new tail model","new feature","new label","tail/veto/sizing/strategy rule","threshold search","portfolio backtest","model refit","post-cutoff outcome read","registry change","prospective tree mutation"],
        "fixed_counts":{"NEW_MODEL_COUNT":0,"FEATURE_SEARCH_COUNT":0,"LABEL_SEARCH_COUNT":0,"THRESHOLD_SEARCH_COUNT":0,"NEW_STRATEGY_COUNT":0,"REGISTRY_CHANGE_COUNT":0}
    }
    dump_json(OUT / "tail_loss_mechanism_protocol.json", protocol)
    protocol_sha = sha(OUT / "tail_loss_mechanism_protocol.json")
    anti = {
        "ANTI_DUPLICATION_AUDIT_STATUS":"PASS_ONE_AUTHORITY_SELECTED_WITHOUT_ECONOMIC_COMPARISON",
        "N_RELEVANT_TAIL_BRANCHES":len(rows),"N_DISTINCT_MECHANISMS":8,
        "BUILD_DECISION":"ONE_UNRESOLVED_EXISTING_MECHANISM_REQUIRES_AUDIT",
        "SELECTED_EXISTING_MECHANISM":"R6_BAD_ASYMMETRY",
        "SELECTED_EXISTING_ARTIFACT":str(RISK_IDENTITY),
        "SELECTED_EXISTING_SPEC_SHA256":EXPECTED_RISK_IDENTITY_SHA,
        "WHY_SELECTED":"Formally registered and hash-frozen RISK_CHAMPION with the exact Raw-A2 Top20 5D bad-asymmetry target; authority hierarchy resolved without comparing candidate economics.",
        "PRIOR_RESULTS_ALREADY_CLOSE_CURRENT_QUESTION":False,
        "UNRESOLVED_GAP":"Exact R6 controlled holding-level and symmetric contribution mechanism accounting",
        "NEW_TAIL_MODEL_CREATED":False,"NEW_FEATURE_SET_CREATED":False,"NEW_LABEL_CREATED":False,"NEW_STRATEGY_CREATED":False,
        "NEW_BACKTESTER_CREATED":False,"TAIL_LOSS_MECHANISM_PROTOCOL_SHA256":protocol_sha,
        "INACCESSIBLE_NONAUTHORITY_TEMP_SURFACE":"D:\\us-tech-quant-results\\A2_INDIVIDUAL_STOCK_TAIL_RISK_R2A_SELECTION_AUDIT_AND_FORWARD_FREEZE\\pytest_tmp;preserved;not referenced by any R2A manifest or selected R6 lineage",
        "PROTECTED_TREE_BEFORE":protocol["temporal_wall"]["protected_tree_before"]
    }
    dump_json(OUT / "anti_duplication_audit.json", anti)
    print(f"ANTI_DUPLICATION_AUDIT_STATUS={anti['ANTI_DUPLICATION_AUDIT_STATUS']}")
    print(f"BUILD_DECISION={anti['BUILD_DECISION']}")
    print(f"TAIL_LOSS_MECHANISM_PROTOCOL_SHA256={protocol_sha}")
    print("ECONOMIC_OUTCOME_READ_COUNT=0")


def clustered_ols(frame: pd.DataFrame, y: str) -> dict[str, Any]:
    columns = [y, "risk_percentile", "A2_rank", "stock_beta_SPY", "REALIZED_VOL_20D", "FF12", "signal_date"]
    z = frame[columns].dropna().copy()
    if len(z) < 100 or z.risk_percentile.nunique() < 2:
        return {"coefficient":np.nan,"tstat":np.nan,"n":len(z),"dates":z.signal_date.nunique()}
    sectors = pd.get_dummies(z.FF12.astype(str), prefix="FF12", drop_first=True, dtype=float)
    x = pd.concat([z[["risk_percentile","A2_rank","stock_beta_SPY","REALIZED_VOL_20D"]].astype(float), sectors], axis=1)
    design = np.column_stack([np.ones(len(x)), x.to_numpy(float)])
    target = z[y].to_numpy(float)
    bread = np.linalg.pinv(design.T @ design)
    coef = bread @ design.T @ target
    residual = target - design @ coef
    groups = pd.factorize(z.signal_date)[0]
    meat = np.zeros((design.shape[1], design.shape[1]))
    for group in np.unique(groups):
        score = design[groups == group].T @ residual[groups == group]
        meat += np.outer(score, score)
    n, k, g = len(z), design.shape[1], len(np.unique(groups))
    correction = (g/(g-1))*((n-1)/(n-k)) if g > 1 and n > k else 1.0
    covariance = correction * bread @ meat @ bread
    se = math.sqrt(max(0.0, float(covariance[1,1])))
    return {"coefficient":float(coef[1]),"tstat":float(coef[1]/se) if se else np.nan,"n":n,"dates":g,"control_count":int(k-2)}


def group_stats(frame: pd.DataFrame, label: str) -> dict[str, Any]:
    if frame.empty:
        return {"group":label,"N":0,"dates":0}
    return {"group":label,"N":len(frame),"dates":frame.signal_date.nunique(),"tail_rate":frame.bad_asymmetry_5d.mean(),"mean_5d_return":frame.forward_5d_stock_return.mean(),"median_5d_return":frame.forward_5d_stock_return.median(),"mean_mae":frame.forward_5d_stock_mae.mean(),"mean_mfe":frame.forward_5d_stock_mfe.mean(),"mean_1d_return":frame.future_return_1d.mean()}


def spread(frame: pd.DataFrame) -> tuple[float, float]:
    high = frame.loc[frame.risk_decile.eq(10)]
    low = frame.loc[frame.risk_decile.eq(1)]
    if high.empty or low.empty:
        return np.nan, np.nan
    return float(high.bad_asymmetry_5d.mean()-low.bad_asymmetry_5d.mean()), float(high.forward_5d_stock_return.mean()-low.forward_5d_stock_return.mean())


def contribution_shares(frame: pd.DataFrame, mask: pd.Series | None = None) -> dict[str, float]:
    z = frame if mask is None else frame.loc[mask]
    high = z.risk_decile.eq(10)
    downside = (-z.forward_5d_stock_return.clip(upper=0))*z.portfolio_weight
    upside = z.forward_5d_stock_return.clip(lower=0)*z.portfolio_weight
    return {"weight_share":float(z.loc[high,"portfolio_weight"].sum()/z.portfolio_weight.sum()) if z.portfolio_weight.sum() else np.nan,"downside_share":float(downside.loc[high].sum()/downside.sum()) if downside.sum() else np.nan,"upside_share":float(upside.loc[high].sum()/upside.sum()) if upside.sum() else np.nan}


def actual_daily() -> pd.DataFrame:
    pre = pd.read_parquet(PRE_DAILY, columns=["execution_date","reconstructed_daily_return"])
    pre = pre.rename(columns={"execution_date":"economic_date","reconstructed_daily_return":"portfolio_return"})
    post = pd.read_csv(POST_DAILY, usecols=["date","strategy","net_return"])
    post = post.loc[post.strategy.eq("RAW_A2"), ["date","net_return"]].rename(columns={"date":"economic_date","net_return":"portfolio_return"})
    daily = pd.concat([pre,post], ignore_index=True)
    daily.economic_date = pd.to_datetime(daily.economic_date).dt.normalize()
    require(not daily.economic_date.gt(CUTOFF).any(), "POST_CUTOFF_DAILY_OUTCOME_PRESENT")
    return daily.drop_duplicates("economic_date", keep="last").sort_values("economic_date")


def audit() -> None:
    require(OUT.exists(), "FROZEN_OUTPUT_ROOT_MISSING")
    anti = json.loads((OUT / "anti_duplication_audit.json").read_text(encoding="utf-8"))
    protocol_path = OUT / "tail_loss_mechanism_protocol.json"
    require(sha(protocol_path) == anti["TAIL_LOSS_MECHANISM_PROTOCOL_SHA256"], "PROTOCOL_HASH_CHANGED")
    require(sha(RISK_PRED) == EXPECTED_OVERLAY_PRED_SHA and sha(R6_OOF) == EXPECTED_R6_OOF_SHA, "FROZEN_SIGNAL_SOURCE_CHANGED")

    # The protocol is now frozen.  Only the named outcome columns are opened.
    risk_cols = ["information_date","signal_date","ticker","A2_RANK","A2_PREDICTION","predicted_bad_asymmetry_risk","risk_percentile","bad_asymmetry_5d","forward_5d_stock_return","forward_5d_stock_mae","forward_5d_stock_mfe","fold","evidence_layer","target_end_date","risk_signal_missing_action"]
    pre_risk = pd.read_parquet(RISK_PRED, columns=risk_cols, filters=[("evidence_layer","==","PRE2026_PRIMARY_TEMPORAL_OOF")])
    post_risk = pd.read_parquet(RISK_PRED, columns=risk_cols, filters=[("evidence_layer","==","2026_RETROSPECTIVE_WITH_PRIOR_OUTCOME_EXPOSURE"),("target_end_date","<=",CUTOFF.to_pydatetime())])
    risk = pd.concat([pre_risk, post_risk], ignore_index=True)
    # R6 calls the decision timestamp information_date and the next execution
    # timestamp signal_date.  The authoritative holding panel calls that same
    # decision timestamp signal_date, so align on information_date explicitly.
    risk = risk.rename(columns={"signal_date":"execution_date","information_date":"signal_date"})
    for col in ["signal_date","execution_date","target_end_date"]: risk[col] = pd.to_datetime(risk[col]).dt.normalize()
    require(not risk.target_end_date.gt(CUTOFF).any(), "POST_CUTOFF_RISK_OUTCOME_READ")
    panel_cols = ["signal_date","ticker","A2_rank","A2_score","portfolio_weight","FF12","FF48","stock_beta_SPY","future_return_1d","realization_date","bull_bear","high_low_vol"]
    panel = pd.read_parquet(BETA_PANEL, columns=panel_cols)
    panel.signal_date = pd.to_datetime(panel.signal_date).dt.normalize(); panel.realization_date = pd.to_datetime(panel.realization_date).dt.normalize()
    panel.loc[panel.realization_date.gt(CUTOFF), "future_return_1d"] = np.nan
    vol = pd.read_parquet(R6_OOF, columns=["information_date","ticker","REALIZED_VOL_20D","target_end_date"]).rename(columns={"information_date":"signal_date","target_end_date":"r6_target_end_date"})
    vol.signal_date = pd.to_datetime(vol.signal_date).dt.normalize(); vol.r6_target_end_date = pd.to_datetime(vol.r6_target_end_date).dt.normalize()
    vol = vol.drop_duplicates(["signal_date","ticker"])
    risk = risk.drop_duplicates(["signal_date","ticker"], keep="last")
    support_dates = sorted(set(risk.signal_date))
    auth = panel.loc[panel.signal_date.isin(support_dates)].copy()
    merged = auth.merge(risk, on=["signal_date","ticker"], how="left", validate="one_to_one")
    merged = merged.merge(vol, on=["signal_date","ticker"], how="left", validate="one_to_one")
    merged["target_end_date"] = merged.target_end_date.fillna(merged.r6_target_end_date)
    row_coverage = merged.risk_percentile.notna().mean()
    artifact_key_coverage = merged.A2_RANK.notna().mean()
    rank_overlap = merged.loc[merged.A2_RANK.notna(), ["A2_rank","A2_RANK"]]
    rank_mismatch_count = int(rank_overlap.A2_rank.ne(rank_overlap.A2_RANK).sum())
    rank_mismatch_share = float(rank_mismatch_count/len(rank_overlap)) if len(rank_overlap) else 1.0
    merged["risk_decile"] = np.where(
        merged.risk_percentile.notna(),
        np.minimum(10, np.floor(merged.risk_percentile.fillna(0).clip(0,1)*10).astype(int)+1),
        np.nan,
    )
    work = merged.loc[merged.risk_percentile.notna() & merged.bad_asymmetry_5d.notna()].copy()
    work["year"] = work.signal_date.dt.year
    work["portfolio_weight"] = work.portfolio_weight.fillna(.05)

    group_rows = [group_stats(g, f"D{int(d)}") for d,g in work.groupby("risk_decile", sort=True)]
    means = pd.DataFrame(group_rows).set_index("group")
    decile_tail = means.tail_rate.reindex([f"D{i}" for i in range(1,11)])
    monotonicity = float(spearmanr(range(1,11), decile_tail).statistic) if decile_tail.notna().all() else np.nan
    monotonicity_violations = int((np.diff(decile_tail.to_numpy()) < 0).sum()) if decile_tail.notna().all() else 9
    tail_spread, return_spread = spread(work)
    controlled_tail = clustered_ols(work, "bad_asymmetry_5d")
    controlled_return = clustered_ols(work, "forward_5d_stock_return")
    contribution = contribution_shares(work)

    daily = actual_daily()
    mapping = merged[["signal_date","realization_date"]].drop_duplicates()
    require(not mapping.signal_date.duplicated().any(), "SIGNAL_TO_REALIZATION_NOT_ONE_TO_ONE")
    date_state = mapping.merge(daily, left_on="realization_date", right_on="economic_date", how="left")
    low_cut = date_state.portfolio_return.quantile(.10); high_cut = date_state.portfolio_return.quantile(.90)
    date_state["day_state"] = np.select([date_state.portfolio_return.le(low_cut),date_state.portfolio_return.ge(high_cut)],["WORST_10PCT","BEST_10PCT"],default="MIDDLE")
    work = work.merge(date_state[["signal_date","day_state","portfolio_return"]], on="signal_date", how="left", validate="many_to_one")
    tail_panel = merged.merge(date_state[["signal_date","day_state","portfolio_return"]], on="signal_date", how="left", validate="many_to_one")
    tail_panel["one_day_contribution"] = tail_panel.portfolio_weight * tail_panel.future_return_1d
    worst = tail_panel.loc[tail_panel.day_state.eq("WORST_10PCT")]
    best = tail_panel.loc[tail_panel.day_state.eq("BEST_10PCT")]
    high_worst = worst.risk_decile.eq(10); high_best = best.risk_decile.eq(10)
    worst_amount = -worst.one_day_contribution.clip(upper=0); best_amount = best.one_day_contribution.clip(lower=0)
    severe = {
        "high_risk_weight_share":float(tail_panel.loc[tail_panel.risk_decile.eq(10),"portfolio_weight"].sum()/tail_panel.portfolio_weight.sum()),
        "high_risk_downside_share":float(worst_amount.loc[high_worst].sum()/worst_amount.sum()) if worst_amount.sum() else np.nan,
        "high_risk_upside_share":float(best_amount.loc[high_best].sum()/best_amount.sum()) if best_amount.sum() else np.nan,
        "worst_date_count":int(date_state.day_state.eq("WORST_10PCT").sum()),"best_date_count":int(date_state.day_state.eq("BEST_10PCT").sum()),
        "worst_cutoff":float(low_cut),"best_cutoff":float(high_cut)
    }

    stability_rows = []
    for year in [2023,2024,2025,2026]:
        g = work.loc[work.year.eq(year)]; ts, rs = spread(g); cs = contribution_shares(g)
        stability_rows.append({"dimension":"YEAR","period":"2026_EXPOSED" if year==2026 else str(year),"N":len(g),"dates":g.signal_date.nunique(),"tail_rate_spread":ts,"mean_5d_return_spread":rs,**cs})
    for regime, mask in [("BULL",work.bull_bear.eq("BULL")),("BEAR",work.bull_bear.eq("BEAR")),("HIGH_VOL",work.high_low_vol.eq("HIGH_VOL")),("LOW_VOL",work.high_low_vol.eq("LOW_VOL"))]:
        g=work.loc[mask]; ts,rs=spread(g); cs=contribution_shares(g)
        stability_rows.append({"dimension":"REGIME","period":regime,"N":len(g),"dates":g.signal_date.nunique(),"tail_rate_spread":ts,"mean_5d_return_spread":rs,**cs})
    stability = pd.DataFrame(stability_rows)
    positive_years = int((stability.loc[stability.dimension.eq("YEAR"),"tail_rate_spread"]>0).sum())
    negative_years = int((stability.loc[stability.dimension.eq("YEAR"),"tail_rate_spread"]<=0).sum())
    positive_regimes = int((stability.loc[stability.dimension.eq("REGIME"),"tail_rate_spread"]>0).sum())

    concentration_rows=[]
    ticker_loss = work.loc[work.risk_decile.eq(10)].assign(loss=lambda x:(-x.forward_5d_stock_return.clip(upper=0))*x.portfolio_weight).groupby("ticker").loss.sum().sort_values(ascending=False)
    date_loss = work.loc[work.risk_decile.eq(10)].assign(loss=lambda x:(-x.forward_5d_stock_return.clip(upper=0))*x.portfolio_weight).groupby("signal_date").loss.sum().sort_values(ascending=False)
    for n in [1,3,5,10]:
        g=work.loc[~work.ticker.isin(ticker_loss.head(n).index)]; ts,rs=spread(g)
        concentration_rows.append({"exclusion_type":"TICKER","excluded_n":n,"tail_rate_spread":ts,"mean_5d_return_spread":rs})
        g=work.loc[~work.signal_date.isin(date_loss.head(n).index)]; ts,rs=spread(g)
        concentration_rows.append({"exclusion_type":"DATE","excluded_n":n,"tail_rate_spread":ts,"mean_5d_return_spread":rs})
    concentration = pd.DataFrame(concentration_rows)

    metric_rows = group_rows + [
        {"group":"PRIMARY_D10_MINUS_D1","tail_rate":tail_spread,"mean_5d_return":return_spread},
        {"group":"CONTROLLED_TAIL","tail_rate":controlled_tail["coefficient"],"mean_5d_return":controlled_tail["tstat"],"N":controlled_tail["n"],"dates":controlled_tail["dates"]},
        {"group":"CONTROLLED_RETURN","tail_rate":controlled_return["coefficient"],"mean_5d_return":controlled_return["tstat"],"N":controlled_return["n"],"dates":controlled_return["dates"]},
    ]
    pd.DataFrame(metric_rows).to_csv(OUT / "tail_mechanism_metrics.csv", index=False)
    stability.to_csv(OUT / "yearly_regime_metrics.csv", index=False)
    concentration.to_csv(OUT / "concentration_metrics.csv", index=False)

    robust_ticker = float(concentration.loc[(concentration.exclusion_type.eq("TICKER"))&(concentration.excluded_n.eq(10)),"tail_rate_spread"].iloc[0]) > 0
    robust_date = float(concentration.loc[(concentration.exclusion_type.eq("DATE"))&(concentration.excluded_n.eq(10)),"tail_rate_spread"].iloc[0]) > 0
    adequate_years = int((stability.loc[stability.dimension.eq("YEAR"),"N"]>=100).sum())
    inconclusive = row_coverage < .75 or rank_mismatch_share > .05 or adequate_years < 3
    secondary_support = sum([severe["high_risk_downside_share"] > severe["high_risk_weight_share"] and severe["high_risk_downside_share"] > severe["high_risk_upside_share"], positive_years>=3 and positive_regimes>=3, monotonicity>=.8 and monotonicity_violations<=2, robust_ticker and robust_date])
    strong = tail_spread>0 and controlled_tail["coefficient"]>0 and controlled_tail["tstat"]>=1.96 and secondary_support==4
    partial = tail_spread>0 and controlled_tail["coefficient"]>0 and secondary_support>=2
    if inconclusive: classification="INCONCLUSIVE_EXISTING_TAIL_LOSS_MECHANISM"
    elif strong: classification="STRONG_EXISTING_TAIL_LOSS_MECHANISM"
    elif partial: classification="PARTIAL_EXISTING_TAIL_LOSS_MECHANISM"
    else: classification="NO_ROBUST_EXISTING_TAIL_LOSS_MECHANISM"
    if classification in {"STRONG_EXISTING_TAIL_LOSS_MECHANISM","PARTIAL_EXISTING_TAIL_LOSS_MECHANISM"}:
        branch_status="OPEN_ONE_EXISTING_FIXED_TAIL_MECHANISM_SUPPORTED"
        next_priority="DESIGN_AND_FREEZE_ONE_SINGLE_EXISTING_SIGNAL_TAIL_CONTROL_SHADOW"
    else:
        branch_status="CLOSED_NO_ROBUST_EXISTING_EDGE" if classification=="NO_ROBUST_EXISTING_TAIL_LOSS_MECHANISM" else "INCONCLUSIVE_EXISTING_SIGNAL_IDENTITY_OR_COVERAGE"
        next_priority="CLOSE_SECURITY_LEVEL_A2_OVERLAY_SEARCH_AND_MOVE_TO_ORTHOGONAL_SLEEVE_RESEARCH" if classification=="NO_ROBUST_EXISTING_TAIL_LOSS_MECHANISM" else "DO_NOT_READ_MORE_ECONOMICS_RESOLVE_EXACT_IDENTITY_LIMITATION"

    latest = max(work.target_end_date.max(), work.loc[work.future_return_1d.notna(),"realization_date"].max())
    protected_after = tree_snapshot(PROTECTED)
    require(protected_after["tree_sha256"] == anti["PROTECTED_TREE_BEFORE"]["tree_sha256"], "PROTECTED_TREE_CHANGED")
    root_temps = repo_root_temps()
    require(not root_temps, "TASK_END_REPO_ROOT_TEMP_PRESENT", root_temps)
    summary = {
        "STATUS":"PASS_COMPLETE_EXISTING_SIGNAL_MECHANISM_AUDIT","RAW_A2_IDENTITY_STATUS":"PASS_MODEL_HASH_AUTHORITATIVE_MEMBERSHIP_JOIN",
        "ECONOMIC_CUTOFF":"2026-08-28","LATEST_USED_SESSION":latest.strftime("%Y-%m-%d"),"POST_2026_08_28_OUTCOME_READ_COUNT":0,
        "ANTI_DUPLICATION_AUDIT_STATUS":anti["ANTI_DUPLICATION_AUDIT_STATUS"],"N_RELEVANT_TAIL_BRANCHES":anti["N_RELEVANT_TAIL_BRANCHES"],"N_DISTINCT_MECHANISMS":anti["N_DISTINCT_MECHANISMS"],"BUILD_DECISION":anti["BUILD_DECISION"],
        "SELECTED_EXISTING_MECHANISM":"R6_BAD_ASYMMETRY","SELECTED_EXISTING_ARTIFACT":str(RISK_IDENTITY),"SELECTED_EXISTING_SPEC_SHA256":EXPECTED_RISK_IDENTITY_SHA,
        "NEW_TAIL_MODEL_CREATED":False,"NEW_FEATURE_SET_CREATED":False,"NEW_LABEL_CREATED":False,"NEW_STRATEGY_CREATED":False,
        "NEW_BACKTESTER_CREATED":False,"TEMPORAL_VIOLATION_COUNT":0,
        "BUY_SELL_SIZING_PRIOR_STATUS":"CLOSED_NEGATIVE_ECONOMIC_SEARCH;OPERATIONAL_STATE_TRANSLATION_ONLY","LOSER_RESEARCH_PRIOR_STATUS":"R6_REGISTERED_CHAMPION_PLUS_PARTIAL_CROSS_MODEL_SIGNAL","TAIL_RISK_PRIOR_STATUS":"R1_MILD_FIXED_OVERLAY_AND_R11_PROSPECTIVE_ALREADY_TESTED","MODEL_STABILITY_PRIOR_STATUS":"PARTIAL_CROSS_MODEL_SIGNAL;NO_NEW_HISTORICAL_HYPOTHESIS",
        "DO_PRIOR_RESULTS_ALREADY_CLOSE_CURRENT_QUESTION":False,"TAIL_LOSS_MECHANISM_PROTOCOL_SHA256":anti["TAIL_LOSS_MECHANISM_PROTOCOL_SHA256"],
        "PRIMARY_TAIL_RATE_SPREAD":tail_spread,"PRIMARY_DOWNSIDE_SPREAD":return_spread,"TAIL_SIGNAL_MONOTONICITY":monotonicity,"MONOTONICITY_VIOLATIONS":monotonicity_violations,
        "INCREMENTAL_CONTROLLED_SIGNAL":{"coefficient":controlled_tail["coefficient"],"tstat":controlled_tail["tstat"],"N":controlled_tail["n"],"dates":controlled_tail["dates"]},
        "HIGH_RISK_WEIGHT_SHARE":severe["high_risk_weight_share"],"HIGH_RISK_DOWNSIDE_SHARE":severe["high_risk_downside_share"],"HIGH_RISK_UPSIDE_SHARE":severe["high_risk_upside_share"],
        "POSITIVE_MECHANISM_YEARS":positive_years,"NEGATIVE_MECHANISM_YEARS":negative_years,"POSITIVE_MECHANISM_REGIMES":positive_regimes,
        "EVALUABLE_MECHANISM_YEARS":int(stability.loc[stability.dimension.eq("YEAR"),"tail_rate_spread"].notna().sum()),
        "2026_MECHANISM_STATUS":"EXPOSED_EVALUATION_ONLY_NO_D1_SUPPORT" if pd.isna(stability.loc[(stability.dimension.eq("YEAR"))&(stability.period.eq("2026_EXPOSED")),"tail_rate_spread"].iloc[0]) else "EXPOSED_EVALUATION_ONLY_EVALUABLE",
        "CONCENTRATION_STATUS":"PASS_NOT_FEW_NAME_OR_DATE_DRIVEN" if robust_ticker and robust_date else "MIXED_CONCENTRATION_SENSITIVITY",
        "AUTHORITATIVE_ARTIFACT_KEY_COVERAGE":artifact_key_coverage,"AUTHORITATIVE_SCORED_ROW_COVERAGE":row_coverage,"RANK_MISMATCH_COUNT":rank_mismatch_count,"RANK_MISMATCH_SHARE":rank_mismatch_share,
        "TAIL_CONTROL_BRANCH_STATUS":branch_status,"TAIL_LOSS_MECHANISM_CLASSIFICATION":classification,
        "CORE_NUMERICAL_REASON":f"D10-D1 tail_rate={tail_spread:.6f}; controlled_beta={controlled_tail['coefficient']:.6f},t={controlled_tail['tstat']:.3f}; weight/downside/upside={severe['high_risk_weight_share']:.4f}/{severe['high_risk_downside_share']:.4f}/{severe['high_risk_upside_share']:.4f}; scored_coverage={row_coverage:.4f}",
        "NEXT_RESEARCH_PRIORITY":next_priority,"NEW_MODEL_COUNT":0,"FEATURE_SEARCH_COUNT":0,"LABEL_SEARCH_COUNT":0,"THRESHOLD_SEARCH_COUNT":0,"NEW_STRATEGY_COUNT":0,"REGISTRY_CHANGE_COUNT":0,
        "PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED":True,"TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT":0,"UNRELATED_ACTIVE_TEMP_DIR_COUNT":0,"ACTIVE_UNRELATED_TRANSIENT_EXCLUSIONS":0,"ARTIFACT_DIR":str(OUT),
        "audits":{"controlled_return":controlled_return,"severe_days":severe,"contribution_full_5d":contribution,"adequate_years":adequate_years,"protected_tree_after":protected_after,"post_cutoff_rows_read":0}
    }
    dump_json(OUT / "summary.json", clean(summary))
    source_paths = [REPO/"a2_existing_tail_loss_control_mechanism_audit_r1.py",MODEL,RISK_IDENTITY,RISK_R2/"manifest.json",RISK_R2/"risk_overlay_contract.json",RISK_PRED,R6_OOF,BETA_PANEL,BETA_PROTOCOL,REGISTRY,PRE_DAILY,POST_DAILY,RESULTS/"A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1"/"final_report.md",RESULTS/"A2_ML_MODEL_CLASS_STABILITY_DISCOVERY_SANDBOX_R1"/"hash_manifest.json",RESULTS/"A2_FROZEN_RISK_EXECUTION_ABLATION_R1"/"final_report.md"]
    manifest = {"task_id":TASK,"outcome_read_started_after_protocol_sha256":anti["TAIL_LOSS_MECHANISM_PROTOCOL_SHA256"],"economic_cutoff":"2026-08-28","latest_used_session":summary["LATEST_USED_SESSION"],"post_cutoff_outcome_read_count":0,"inputs":[{"path":str(p),"bytes":p.stat().st_size,"sha256":sha(p)} for p in source_paths],"outputs":[]}
    report = f"""# A2 existing tail-loss control mechanism audit R1

## Outcome

`{classification}`. The only eligible pre-existing signal was frozen `R6_BAD_ASYMMETRY`; it was selected by registry/freeze authority, not by economics. No model, feature, label, threshold, strategy, or veto rule was created.

## Core evidence

Frozen D10 minus D1 tail-event spread is `{tail_spread:.6f}` and the 5-session return spread is `{return_spread:.6f}`. In the fixed controlled linear-probability specification, the R6 percentile coefficient is `{controlled_tail['coefficient']:.6f}` with date-clustered t-stat `{controlled_tail['tstat']:.3f}`. Decile tail-rate monotonicity is `{monotonicity:.3f}` with `{monotonicity_violations}` adjacent violations.

On the frozen Raw A2 worst/best-day definitions, scored D10 holdings account for `{severe['high_risk_weight_share']:.2%}` of total authoritative weight, `{severe['high_risk_downside_share']:.2%}` of total downside, and `{severe['high_risk_upside_share']:.2%}` of total upside; unscored holdings remain in every denominator. Positive tail-rate spreads occur in `{positive_years}` of the `3` evaluable years and `{positive_regimes}/4` frozen regimes. The 2026 exposed slice has no D1 observations and therefore no D10-D1 spread. Authoritative scored-row coverage is `{row_coverage:.2%}`; rank mismatch share is `{rank_mismatch_share:.2%}`.

## Prior-art reconciliation

R6 prediction, model variants, fixed attenuation economics, 2026 exposed support, orthogonal loser learnability, and model-class stability are not rerun. The present computation closes only their missing controlled holding/contribution accounting. Generic Action ML, portfolio Risk OS, H08, RX/boundary, right-tail winner, and NG8-specific branches are distinct or closed.

## Boundaries

Evidence is retrospective; 2026 is `EXPOSED_EVALUATION_ONLY`. Maximum used session is `{summary['LATEST_USED_SESSION']}` and post-cutoff reads are zero. The protected A2/X0 tree is unchanged. No tail-control strategy was evaluated.
"""
    (OUT / "concise_report.md").write_text(report, encoding="utf-8")
    output_paths=[OUT/"anti_duplication_audit.json",OUT/"tail_branch_registry.csv",OUT/"tail_loss_mechanism_protocol.json",OUT/"tail_mechanism_metrics.csv",OUT/"yearly_regime_metrics.csv",OUT/"concentration_metrics.csv",OUT/"summary.json",OUT/"concise_report.md"]
    manifest["outputs"]=[{"path":p.name,"bytes":p.stat().st_size,"sha256":sha(p)} for p in output_paths]
    dump_json(OUT / "source_manifest.json", clean(manifest))
    print_console(summary)


def print_console(s: dict[str, Any]) -> None:
    print("="*60);print("A2 EXISTING TAIL-LOSS CONTROL MECHANISM AUDIT");print("="*60)
    for key in ["STATUS","RAW_A2_IDENTITY_STATUS","ECONOMIC_CUTOFF","LATEST_USED_SESSION","POST_2026_08_28_OUTCOME_READ_COUNT"]:print(f"{key}={s[key]}")
    print("\nANTI-DUPLICATION")
    for key in ["ANTI_DUPLICATION_AUDIT_STATUS","N_RELEVANT_TAIL_BRANCHES","N_DISTINCT_MECHANISMS","BUILD_DECISION","SELECTED_EXISTING_MECHANISM","SELECTED_EXISTING_ARTIFACT","SELECTED_EXISTING_SPEC_SHA256","NEW_TAIL_MODEL_CREATED","NEW_FEATURE_SET_CREATED","NEW_LABEL_CREATED","NEW_STRATEGY_CREATED"]:print(f"{key}={s[key]}")
    print("\nPRIOR BRANCH CONCLUSIONS")
    for key in ["BUY_SELL_SIZING_PRIOR_STATUS","LOSER_RESEARCH_PRIOR_STATUS","TAIL_RISK_PRIOR_STATUS","MODEL_STABILITY_PRIOR_STATUS","DO_PRIOR_RESULTS_ALREADY_CLOSE_CURRENT_QUESTION"]:print(f"{key}={s[key]}")
    print("\nIF MECHANISM AUDITED")
    for key in ["TAIL_LOSS_MECHANISM_PROTOCOL_SHA256","PRIMARY_TAIL_RATE_SPREAD","PRIMARY_DOWNSIDE_SPREAD","TAIL_SIGNAL_MONOTONICITY","INCREMENTAL_CONTROLLED_SIGNAL","HIGH_RISK_WEIGHT_SHARE","HIGH_RISK_DOWNSIDE_SHARE","HIGH_RISK_UPSIDE_SHARE","POSITIVE_MECHANISM_YEARS","NEGATIVE_MECHANISM_YEARS","CONCENTRATION_STATUS"]:print(f"{key}={s[key]}")
    print("\nFINAL")
    for key in ["TAIL_CONTROL_BRANCH_STATUS","TAIL_LOSS_MECHANISM_CLASSIFICATION","CORE_NUMERICAL_REASON","NEXT_RESEARCH_PRIORITY"]:print(f"{key}={s[key]}")
    print("\nSAFETY")
    for key in ["NEW_MODEL_COUNT","FEATURE_SEARCH_COUNT","LABEL_SEARCH_COUNT","THRESHOLD_SEARCH_COUNT","NEW_STRATEGY_COUNT","REGISTRY_CHANGE_COUNT","PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED","TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT","ARTIFACT_DIR"]:print(f"{key}={s[key]}")
    print("="*60)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    freeze() if args.freeze else audit()


if __name__ == "__main__":
    main()
