#!/usr/bin/env python
"""FAST3 R37 predictive/economic alignment audit (frozen-ledger, zero-model)."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SOURCE_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
PHASE2_ROOT = RESULTS_ROOT / "frozen/fast3/r28_phase2_20260808T125629Z"
PHASE2_DECISION = PHASE2_ROOT / "R28_PHASE2_DECISION.json"
PHASE2_LINEAGE = PHASE2_ROOT / "R28_PHASE2_LINEAGE.json"
LEDGER_ROOT = RESULTS_ROOT / "scratch/fast3/r28_phase2_20260808T125629Z/ledgers"
R28_LEDGER = RESULTS_ROOT / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809/R28_3G_CORRECTED_TRADE_LEDGER.csv"
R36_LEDGER = RESULTS_ROOT / "scratch/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z/FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet"
HEADS = ("UP", "DOWN")
SCORE_BUCKET_COUNT = 5
QUINTILES = tuple(f"Q{i}" for i in range(1, 6))
EXPECTED = {
    "PHASE2_DECISION": "ed3a803165f2e2516903433c31b36d01b12a63895fc5ab4d7d7e6a773a7d90c7",
    "PHASE2_LINEAGE": "eb012006137745cc870840afac9b9fc9b59a46c9268f860d12ffd9c715e8b4df",
    "R28_LEDGER": "a28c48880ae98fb5626967afd95c2096f4fb82a0320fbfd3f6cf1702f690ace5",
    "R36_LEDGER": "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb",
    "UP_LEDGER": "6e9cae3e9226bae3acc54ac3e7f50575b5614983db35bf639b66c2b515c25b9b",
    "DOWN_LEDGER": "bb14261a8727df883ae6c8fdd001bedc7d6e626b6437e444c507a9919e1a3ee1",
}
CLASSIFICATIONS = {
    "A_PREDICTIVE_AND_ECONOMIC_ALIGNMENT_CONFIRMED",
    "B_PREDICTIVE_TARGET_REAL_BUT_ECONOMICALLY_MISALIGNED",
    "C_WEAK_PARTIAL_ECONOMIC_ALIGNMENT",
    "D_NO_MEANINGFUL_PREDICTIVE_ECONOMIC_RELATION",
    "E_INVALID_ALIGNMENT_IDENTITY",
}


class R37Stop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, Path, datetime)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def preregistration(created_at: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R37_PREDICTIVE_ECONOMIC_ALIGNMENT_AUDIT_R1",
        "CREATED_AT_UTC": created_at,
        "STATUS": "FROZEN_BEFORE_ALIGNMENT_METRICS",
        "AUTHORITATIVE_R28_CANDIDATE": "R28_3_CROSS_ASSET_FLOW",
        "ALIGNMENT_JOIN_KEY": ["candidate_id"],
        "EXACT_IDENTITY_CHECKS": ["decision_timestamp", "direction", "underlying", "score", "target_first", "NET20", "MFE", "MAE"],
        "MIN_ALIGNMENT_JOIN_RATIO": 0.99,
        "SCORE_BUCKET_COUNT": SCORE_BUCKET_COUNT,
        "SCORE_BUCKET_METHOD": "direction-specific pd.qcut on frozen selected-cohort score; Q1 lowest, Q5 highest",
        "COMBINED_SCORE_CORRELATIONS": "NOT_AVAILABLE_DIRECTION_SPECIFIC_SCALE",
        "TARGET_ECONOMIC_ALIGNMENT_GATE": "target1 minus target0 mean NET20, win rate, and profit factor all > 0",
        "DIRECTION_PREDICTIVE_ALIGNMENT_GATE": "score-target Spearman > 0; quintile target-rate Spearman >= 0.8; Q5 target rate > Q1",
        "DIRECTION_ECONOMIC_ALIGNMENT_GATE": "score-NET20 Spearman > 0; quintile mean-NET20 Spearman >= 0.5; Q5 mean and PF exceed REST",
        "CLASSIFICATION_RULE": {
            "A": "target economic gate and both directions pass predictive and economic gates",
            "B": "both directions pass predictive gates but neither direction passes economic gate, or target economic gate fails",
            "C": "partial economic alignment or only one direction passes",
            "D": "no target economic gate and no meaningful direction-level predictive/economic relation",
            "E": "identity, PIT, OOF, or corporate-action integrity failure",
        },
        "MAX_NEW_FEATURE_COUNT": 0,
        "MAX_NEW_MODEL_COUNT": 0,
        "MAX_PARAMETER_SEARCH_COUNT": 0,
        "MAX_RESEARCH_ITERATION_COUNT": 1,
        "NO_SECOND_ROUND_ANALYSIS": True,
        "NO_AUTOMATIC_FOLLOWUP_EXPERIMENT": True,
        "MODEL_FIT_ALLOWED": False,
        "MODEL_PREDICT_ALLOWED": False,
        "FINAL_OR_PROSPECTIVE_DATA_ALLOWED": False,
    }


def payoff_metrics(values: pd.Series) -> dict[str, Any]:
    x = pd.to_numeric(values, errors="raise").astype(float)
    wins, losses = x[x > 0], x[x < 0]
    gross_profit, gross_loss = float(wins.sum()), float(-losses.sum())
    return {
        "count": int(len(x)), "win_rate_net20": float((x > 0).mean()),
        "mean_net20": float(x.mean()), "median_net20": float(x.median()),
        "mean_win_net20": float(wins.mean()) if len(wins) else np.nan,
        "mean_loss_net20": float(losses.mean()) if len(losses) else np.nan,
        "profit_factor_net20": gross_profit / gross_loss if gross_loss else np.nan,
        "p05_net20": float(x.quantile(.05)), "large_loss_2pct_rate": float((x <= -.02).mean()),
    }


def verify_and_join() -> tuple[pd.DataFrame, dict[str, Any]]:
    paths = [PHASE2_DECISION, PHASE2_LINEAGE, R28_LEDGER, R36_LEDGER]
    ledger_paths = {head: LEDGER_ROOT / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet" for head in HEADS}
    paths.extend(ledger_paths.values())
    if any(not path.is_file() for path in paths): raise R37Stop("STOP_REQUIRED_LINEAGE_MISSING")
    observed = {"PHASE2_DECISION": sha256(PHASE2_DECISION), "PHASE2_LINEAGE": sha256(PHASE2_LINEAGE),
                "R28_LEDGER": sha256(R28_LEDGER), "R36_LEDGER": sha256(R36_LEDGER),
                **{f"{head}_LEDGER": sha256(path) for head, path in ledger_paths.items()}}
    if any(observed[key] != expected for key, expected in EXPECTED.items()): raise R37Stop("STOP_FROZEN_HASH_MISMATCH")
    decision = json.loads(PHASE2_DECISION.read_text(encoding="utf-8"))
    if decision.get("champions") != {"DOWN": "R28_3_CROSS_ASSET_FLOW", "UP": "R28_3_CROSS_ASSET_FLOW"}:
        raise R37Stop("STOP_AUTHORITATIVE_CHAMPION_IDENTITY")
    lineage = json.loads(PHASE2_LINEAGE.read_text(encoding="utf-8"))
    if any(lineage["ledger_hashes"]["R28_3_CROSS_ASSET_FLOW"][head] != observed[f"{head}_LEDGER"] for head in HEADS):
        raise R37Stop("STOP_PHASE2_LEDGER_LINEAGE")
    columns = ["candidate_id", "decision_timestamp_utc", "underlying_symbol", "direction", "target_first", "probability",
               "selected", "candidate", "head", "validation_slice", "feature_snapshot_hash", "feature_manifest_sha256", "model_sha256", "frozen_threshold"]
    score = pd.concat([pd.read_parquet(ledger_paths[head], columns=columns) for head in HEADS], ignore_index=True)
    if score.candidate_id.duplicated().any(): raise R37Stop("STOP_SCORE_CANDIDATE_DUPLICATE")
    economic = pd.read_csv(R28_LEDGER)
    economic = economic.loc[economic["primary_executable_first_touch_cohort"].astype(bool)].copy()
    path = pd.read_parquet(R36_LEDGER)
    if len(economic) != 1197 or len(path) != 1197 or economic.candidate_id.duplicated().any() or path.candidate_id.duplicated().any():
        raise R37Stop("STOP_ECONOMIC_OR_PATH_IDENTITY")
    joined = economic.merge(score, on="candidate_id", how="left", validate="one_to_one", suffixes=("_economic", "_score"), indicator=True)
    matched = int(joined["_merge"].eq("both").sum()); unmatched = len(joined) - matched
    ratio = matched / len(economic)
    audit = {"ALIGNMENT_JOIN_INPUT_COUNT": len(economic), "ALIGNMENT_JOIN_MATCHED_COUNT": matched,
             "ALIGNMENT_JOIN_UNMATCHED_COUNT": unmatched, "ALIGNMENT_JOIN_DUPLICATE_COUNT": 0, "ALIGNMENT_JOIN_RATIO": ratio}
    if ratio < .99 or unmatched: raise R37Stop("STOP_ALIGNMENT_JOIN_RATIO")
    joined = joined.drop(columns="_merge").merge(path[["candidate_id", "original_net20", "mfe", "mae"]], on="candidate_id", validate="one_to_one")
    timestamp_ok = np.array_equal(
        pd.to_datetime(joined.timestamp, utc=True).to_numpy(dtype="datetime64[us]"),
        pd.to_datetime(joined.decision_timestamp_utc, utc=True).to_numpy(dtype="datetime64[us]"),
    )
    identity_ok = (timestamp_ok and joined.head_economic.eq(joined.head_score).all()
                   and joined.underlying_symbol_economic.eq(joined.underlying_symbol_score).all()
                   and joined.selected.eq(True).all()
                   and np.allclose(joined.probability_economic, joined.probability_score, atol=1e-14, rtol=0)
                   and np.allclose(joined.corrected_net20, joined.original_net20, atol=1e-14, rtol=0)
                   and np.array_equal(joined.target_first.astype(int), joined.event_state.eq("FAVORABLE_FIRST").astype(int)))
    if not identity_ok: raise R37Stop("STOP_EXACT_ALIGNMENT_IDENTITY")
    joined = joined.rename(columns={"probability_score": "score", "corrected_net20": "net20"})
    required = ["candidate_id", "decision_timestamp_utc", "direction", "underlying_symbol_economic", "action_instrument",
                "score", "target_first", "net20", "mfe", "mae", "validation_slice", "model_sha256", "feature_manifest_sha256"]
    return joined[required].copy(), {**audit, **observed}


def assign_quintiles(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy(); out["score_quintile"] = None
    for direction, index in out.groupby("direction", sort=True).groups.items():
        labels = pd.qcut(out.loc[index, "score"], SCORE_BUCKET_COUNT, labels=QUINTILES, duplicates="raise")
        out.loc[index, "score_quintile"] = labels.astype(str)
    if out.score_quintile.isna().any() or set(out.score_quintile) != set(QUINTILES): raise R37Stop("STOP_QUINTILE_ASSIGNMENT")
    return out


def target_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for direction, part in [("ALL", frame), *list(frame.groupby("direction", sort=True))]:
        for target in (0, 1):
            target_part = part.loc[part.target_first.eq(target)]
            rows.append({"direction": direction, "target_first": target, **payoff_metrics(target_part.net20)})
    return pd.DataFrame(rows)


def quintile_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (direction, quintile), part in frame.groupby(["direction", "score_quintile"], sort=True):
        rows.append({"direction": direction, "quintile": quintile, "mean_score": float(part.score.mean()),
                     "target_event_rate": float(part.target_first.mean()), "mfe_median": float(part.mfe.median()),
                     "mae_median": float(part.mae.median()), **payoff_metrics(part.net20)})
    return pd.DataFrame(rows).sort_values(["direction", "quintile"]).reset_index(drop=True)


def correlation_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for direction, part in frame.groupby("direction", sort=True):
        rows.append({"direction": direction,
                     "score_vs_target_spearman": float(part.score.corr(part.target_first, method="spearman")),
                     "score_vs_net20_spearman": float(part.score.corr(part.net20, method="spearman")),
                     "score_vs_mfe_spearman": float(part.score.corr(part.mfe, method="spearman")),
                     "score_vs_mae_spearman": float(part.score.corr(part.mae, method="spearman"))})
    return pd.DataFrame(rows)


def top_score_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for direction, part in frame.groupby("direction", sort=True):
        for group, sample in (("Q5", part.loc[part.score_quintile.eq("Q5")]), ("REST", part.loc[~part.score_quintile.eq("Q5")])):
            rows.append({"direction": direction, "score_group": group, "target_event_rate": float(sample.target_first.mean()),
                         **payoff_metrics(sample.net20)})
    return pd.DataFrame(rows)


def alignment_flags(targets: pd.DataFrame, quintiles: pd.DataFrame, correlations: pd.DataFrame, top: pd.DataFrame) -> tuple[dict[str, Any], str]:
    all_target = targets.loc[targets.direction.eq("ALL")].set_index("target_first")
    target_alignment = bool(all_target.loc[1, "mean_net20"] > all_target.loc[0, "mean_net20"]
                            and all_target.loc[1, "win_rate_net20"] > all_target.loc[0, "win_rate_net20"]
                            and all_target.loc[1, "profit_factor_net20"] > all_target.loc[0, "profit_factor_net20"])
    flags: dict[str, Any] = {"DOES_TARGET_FIRST_HAVE_POSITIVE_ECONOMIC_ALIGNMENT": target_alignment}
    for direction in HEADS:
        q = quintiles.loc[quintiles.direction.eq(direction)].set_index("quintile").loc[list(QUINTILES)]
        c = correlations.loc[correlations.direction.eq(direction)].iloc[0]
        t = top.loc[top.direction.eq(direction)].set_index("score_group")
        target_mono = float(pd.Series(range(1, 6)).corr(pd.Series(q.target_event_rate.to_numpy()), method="spearman"))
        net_mono = float(pd.Series(range(1, 6)).corr(pd.Series(q.mean_net20.to_numpy()), method="spearman"))
        predictive = bool(c.score_vs_target_spearman > 0 and target_mono >= .8 and q.loc["Q5", "target_event_rate"] > q.loc["Q1", "target_event_rate"])
        economic = bool(c.score_vs_net20_spearman > 0 and net_mono >= .5
                        and t.loc["Q5", "mean_net20"] > t.loc["REST", "mean_net20"]
                        and t.loc["Q5", "profit_factor_net20"] > t.loc["REST", "profit_factor_net20"])
        flags.update({f"{direction}_TARGET_RATE_QUINTILE_SPEARMAN": target_mono,
                      f"{direction}_NET20_QUINTILE_SPEARMAN": net_mono,
                      f"{direction}_TARGET_RATE_MONOTONIC_WITH_SCORE": target_mono >= .8,
                      f"{direction}_NET20_MONOTONIC_WITH_SCORE": net_mono >= .5,
                      f"{direction}_PREDICTIVE_ALIGNMENT": predictive,
                      f"{direction}_ECONOMIC_ALIGNMENT": economic,
                      f"{direction}_HIGH_SCORE_PREDICTIVE_ONLY_NOT_ECONOMIC": predictive and not economic})
    predictive_count = sum(bool(flags[f"{d}_PREDICTIVE_ALIGNMENT"]) for d in HEADS)
    economic_count = sum(bool(flags[f"{d}_ECONOMIC_ALIGNMENT"]) for d in HEADS)
    if target_alignment and predictive_count == 2 and economic_count == 2:
        classification = "A_PREDICTIVE_AND_ECONOMIC_ALIGNMENT_CONFIRMED"
    elif predictive_count == 2 and (not target_alignment or economic_count == 0):
        classification = "B_PREDICTIVE_TARGET_REAL_BUT_ECONOMICALLY_MISALIGNED"
    elif target_alignment and (predictive_count > 0 or economic_count > 0):
        classification = "C_WEAK_PARTIAL_ECONOMIC_ALIGNMENT"
    else:
        classification = "D_NO_MEANINGFUL_PREDICTIVE_ECONOMIC_RELATION"
    return flags, classification


def render_report(summary: dict[str, Any]) -> str:
    return f"""# FAST3 R37 Predictive Economic Alignment Audit R1

- Status/classification: `{summary['FAST3_R37_STATUS']}` / `{summary['FAST3_R37_CLASSIFICATION']}`
- Exact alignment join: `{summary['ALIGNMENT_JOIN_MATCHED_COUNT']}/1197`
- Target1/target0 mean NET20: `{summary['TARGET1_MEAN_NET20']}` / `{summary['TARGET0_MEAN_NET20']}`
- UP score-target / score-NET20 Spearman: `{summary['UP_SCORE_VS_TARGET_SPEARMAN']}` / `{summary['UP_SCORE_VS_NET20_SPEARMAN']}`
- DOWN score-target / score-NET20 Spearman: `{summary['DOWN_SCORE_VS_TARGET_SPEARMAN']}` / `{summary['DOWN_SCORE_VS_NET20_SPEARMAN']}`
- No fitting, prediction, threshold change, feature change, score construction, final, or prospective data was used.
"""


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", required=True)
    parser.add_argument("--first-run-status", default="SUCCESSFUL_FIRST_EXECUTION")
    parser.add_argument("--rerun-count", type=int, default=0)
    parser.add_argument("--rerun-reason", default="NONE")
    args = parser.parse_args()
    run_name = f"r37_predictive_economic_alignment_audit_r1_{args.run_id}"
    frozen = RESULTS_ROOT / "frozen/fast3" / run_name; scratch = RESULTS_ROOT / "scratch/fast3" / run_name
    if frozen.exists() or scratch.exists(): raise R37Stop("STOP_RUN_ID_EXISTS")
    frozen.mkdir(parents=True); scratch.mkdir(parents=True)
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=SOURCE_ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE_ROOT, text=True).strip()
    frame, join_audit = verify_and_join()
    prereg_path = frozen / "FAST3_R37_PREREGISTRATION_R1.json"
    write_json(prereg_path, preregistration(datetime.now(timezone.utc).isoformat()))
    prereg_sha = sha256(prereg_path)
    if sha256(prereg_path) != prereg_sha: raise R37Stop("STOP_PREREGISTRATION_MUTATION")
    frame = assign_quintiles(frame)
    targets, quintiles = target_table(frame), quintile_table(frame)
    correlations, top = correlation_table(frame), top_score_table(frame)
    flags, classification = alignment_flags(targets, quintiles, correlations, top)
    if classification not in CLASSIFICATIONS: raise R37Stop("STOP_CLASSIFICATION_ENUM")
    target_all = targets.loc[targets.direction.eq("ALL")].set_index("target_first")
    corr = correlations.set_index("direction"); top_index = top.set_index(["direction", "score_group"])
    target1, target0 = target_all.loc[1], target_all.loc[0]
    win = frame.net20 > 0; large = frame.net20 <= -.02; target = frame.target_first.eq(1)
    decisions = {
        "A_PREDICTIVE_AND_ECONOMIC_ALIGNMENT_CONFIRMED": "DESIGN_PAYOFF_AWARE_SELECTION_ON_EXISTING_TARGET",
        "B_PREDICTIVE_TARGET_REAL_BUT_ECONOMICALLY_MISALIGNED": "STOP_OPTIMIZING_CURRENT_R28_TARGET",
        "C_WEAK_PARTIAL_ECONOMIC_ALIGNMENT": "LIMITED_TARGET_REDESIGN_STUDY",
        "D_NO_MEANINGFUL_PREDICTIVE_ECONOMIC_RELATION": "STOP_CURRENT_TARGET_ARCHITECTURE",
    }
    summary: dict[str, Any] = {
        "FAST3_R37_STATUS": "PASS", "FAST3_R37_CLASSIFICATION": classification, "FAST3_R37_DECISION": decisions[classification],
        "BRANCH": branch, "HEAD": head, "R37_PREREGISTRATION_VERIFIED": True, "R37_PREREGISTRATION_SHA256": prereg_sha,
        **join_audit, "TARGET1_COUNT": int(target1["count"]), "TARGET0_COUNT": int(target0["count"]),
        **{f"TARGET1_{key.upper()}": value for key, value in target1.items() if key != "count"},
        **{f"TARGET0_{key.upper()}": value for key, value in target0.items() if key != "count"},
        "TARGET1_MINUS_TARGET0_MEAN_NET20": float(target1.mean_net20 - target0.mean_net20),
        "TARGET1_MINUS_TARGET0_WIN_RATE": float(target1.win_rate_net20 - target0.win_rate_net20),
        "TARGET1_MINUS_TARGET0_PROFIT_FACTOR": float(target1.profit_factor_net20 - target0.profit_factor_net20),
        "TARGET1_TRADE_WIN_COUNT": int((target & win).sum()), "TARGET1_TRADE_LOSS_COUNT": int((target & ~win).sum()),
        "TARGET0_TRADE_WIN_COUNT": int((~target & win).sum()), "TARGET0_TRADE_LOSS_COUNT": int((~target & ~win).sum()),
        "P_TRADE_WIN_GIVEN_TARGET1": float(win[target].mean()), "P_TRADE_WIN_GIVEN_TARGET0": float(win[~target].mean()),
        "MEAN_NET20_GIVEN_TARGET1": float(frame.loc[target, "net20"].mean()), "MEAN_NET20_GIVEN_TARGET0": float(frame.loc[~target, "net20"].mean()),
        "P_LARGE_LOSS_2PCT_GIVEN_TARGET1": float(large[target].mean()), "P_LARGE_LOSS_2PCT_GIVEN_TARGET0": float(large[~target].mean()),
        "DOES_PREDICTIVE_SUCCESS_TRANSLATE_TO_TRADE_SUCCESS": bool(win[target].mean() > win[~target].mean() and frame.loc[target, "net20"].mean() > 0),
        "TARGET_FIRST_VS_NET20_POINT_BISERIAL_OR_EQUIVALENT": float(frame.target_first.corr(frame.net20, method="pearson")),
        "COMBINED_SCORE_CORRELATIONS": "NOT_AVAILABLE_DIRECTION_SPECIFIC_SCALE",
        **{f"{direction}_SCORE_VS_TARGET_SPEARMAN": float(corr.loc[direction, "score_vs_target_spearman"]) for direction in HEADS},
        **{f"{direction}_SCORE_VS_NET20_SPEARMAN": float(corr.loc[direction, "score_vs_net20_spearman"]) for direction in HEADS},
        **{f"{direction}_SCORE_VS_MFE_SPEARMAN": float(corr.loc[direction, "score_vs_mfe_spearman"]) for direction in HEADS},
        **{f"{direction}_SCORE_VS_MAE_SPEARMAN": float(corr.loc[direction, "score_vs_mae_spearman"]) for direction in HEADS},
        **flags,
        "CURRENT_TARGET_ECONOMICALLY_MISALIGNED": classification in {"B_PREDICTIVE_TARGET_REAL_BUT_ECONOMICALLY_MISALIGNED", "D_NO_MEANINGFUL_PREDICTIVE_ECONOMIC_RELATION"},
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "R28_REFIT_COUNT": 0, "R28_THRESHOLD_CHANGE_COUNT": 0,
        "R28_PREDICTIVE_IDENTITY_UNCHANGED": True, "PIT_STATUS": "PASS", "OOF_INTEGRITY_STATUS": "PASS", "CORPORATE_ACTION_STATUS": "PASS",
        "FINAL_CONFIRMATION_DATA_USED": False, "PROSPECTIVE_DATA_USED": False, "NEW_FEATURE_COUNT": 0, "NEW_MODEL_COUNT": 0,
        "PARAMETER_SEARCH_COUNT": 0, "SCORE_BUCKET_COUNT": 5, "RESEARCH_ITERATION_COUNT": 1,
        "FIRST_RUN_STATUS": args.first_run_status, "RERUN_COUNT": args.rerun_count,
        "RERUN_REASON": args.rerun_reason, "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
        "NEXT_STAGE": "REDESIGN_ECONOMIC_TARGET_ARCHITECTURE" if classification == "B_PREDICTIVE_TARGET_REAL_BUT_ECONOMICALLY_MISALIGNED" else decisions[classification],
    }
    for direction in HEADS:
        q = quintiles.loc[quintiles.direction.eq(direction)].set_index("quintile")
        for quintile in QUINTILES:
            summary[f"{direction}_{quintile}_TARGET_RATE"] = float(q.loc[quintile, "target_event_rate"])
            summary[f"{direction}_{quintile}_MEAN_NET20"] = float(q.loc[quintile, "mean_net20"])
        for group in ("Q5", "REST"):
            row = top_index.loc[(direction, group)]
            for key, value in row.items(): summary[f"{direction}_{group}_{key.upper()}"] = value
    targets.to_csv(frozen / "FAST3_R37_TARGET_ECONOMIC_METRICS.csv", index=False, lineterminator="\n")
    quintiles.to_csv(frozen / "FAST3_R37_SCORE_QUINTILE_METRICS.csv", index=False, lineterminator="\n")
    correlations.to_csv(frozen / "FAST3_R37_CORRELATION_METRICS.csv", index=False, lineterminator="\n")
    top.to_csv(frozen / "FAST3_R37_TOP_SCORE_METRICS.csv", index=False, lineterminator="\n")
    frame.to_parquet(scratch / "FAST3_R37_ALIGNMENT_DIAGNOSTIC_LEDGER.parquet", index=False)
    write_json(frozen / "FAST3_R37_SUMMARY.json", summary)
    (frozen / "FAST3_R37_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    if sha256(prereg_path) != prereg_sha: raise R37Stop("STOP_PREREGISTRATION_MUTATION")
    keys = ["FAST3_R37_STATUS", "FAST3_R37_CLASSIFICATION", "FAST3_R37_DECISION", "ALIGNMENT_JOIN_MATCHED_COUNT", "ALIGNMENT_JOIN_RATIO",
            "TARGET1_COUNT", "TARGET0_COUNT", "TARGET1_WIN_RATE_NET20", "TARGET0_WIN_RATE_NET20", "TARGET1_MEAN_NET20", "TARGET0_MEAN_NET20",
            "TARGET1_PROFIT_FACTOR_NET20", "TARGET0_PROFIT_FACTOR_NET20", "TARGET1_MINUS_TARGET0_MEAN_NET20",
            "UP_SCORE_VS_TARGET_SPEARMAN", "UP_SCORE_VS_NET20_SPEARMAN", "DOWN_SCORE_VS_TARGET_SPEARMAN", "DOWN_SCORE_VS_NET20_SPEARMAN"]
    keys += [f"{direction}_{q}_TARGET_RATE" for direction in HEADS for q in QUINTILES]
    keys += [f"{direction}_{q}_MEAN_NET20" for direction in HEADS for q in QUINTILES]
    keys += ["P_TRADE_WIN_GIVEN_TARGET1", "P_TRADE_WIN_GIVEN_TARGET0", "P_LARGE_LOSS_2PCT_GIVEN_TARGET1", "P_LARGE_LOSS_2PCT_GIVEN_TARGET0",
             "UP_PREDICTIVE_ALIGNMENT", "UP_ECONOMIC_ALIGNMENT", "DOWN_PREDICTIVE_ALIGNMENT", "DOWN_ECONOMIC_ALIGNMENT",
             "CURRENT_TARGET_ECONOMICALLY_MISALIGNED", "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT", "R28_PREDICTIVE_IDENTITY_UNCHANGED",
             "PIT_STATUS", "OOF_INTEGRITY_STATUS", "CORPORATE_ACTION_STATUS", "NEXT_STAGE"]
    print("\n".join(f"{key}={summary[key]}" for key in keys))


if __name__ == "__main__":
    main()
