#!/usr/bin/env python
"""FAST3 R28 Phase 2 fixed-period, fixed-candidate predictive comparison only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CONTROL = RESULTS_ROOT / "frozen" / "fast3" / "cleanroom_r2_20260808"
sys.path.insert(0, str(SOURCE_ROOT / "fast3" / "src"))
from fast3.r28_multisignal import BASELINE_FEATURES, R28_FEATURES, build_features, pit_audit  # noqa: E402

R1_SOURCE = SOURCE_ROOT / "fast3" / "scripts" / "run" / "fast3_cleanroom_r1_preholdout.py"
HGB_PARAMS = {"learning_rate": 0.08, "max_iter": 100, "max_leaf_nodes": 7,
              "min_samples_leaf": 200, "l2_regularization": 1.0, "random_state": 1729}
CANDIDATES = {
    "R28_0_BASELINE": BASELINE_FEATURES,
    "R28_1_VOLATILITY_RISK": BASELINE_FEATURES + ("downside_vol_60m", "intrabar_range_15m"),
    "R28_2_TREND_STRUCTURE": BASELINE_FEATURES + ("trend_ema_gap_60m", "breakout_position_120m"),
    "R28_3_CROSS_ASSET_FLOW": BASELINE_FEATURES + ("volume_zscore_60m", "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m"),
    "R28_4_FULL_MULTI_SIGNAL": BASELINE_FEATURES + R28_FEATURES,
}
HEADS = ("UP", "DOWN")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


R1 = load_module(R1_SOURCE, "cleanroom_r1_r28_phase2")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def control_inputs() -> tuple[dict, dict, list[dict]]:
    manifest = read_json(CONTROL / "cleanroom_r2_freeze_manifest.json")
    source = read_json(CONTROL / "cleanroom_r2_preholdout_source_manifest.json")
    required = {"oof_folds", "features", "thresholds", "true_holdout_start_utc", "oof_metrics"}
    if required.difference(manifest):
        raise RuntimeError("R28_CONTROL_MANIFEST_INCOMPLETE")
    if tuple(manifest["features"]) != tuple(BASELINE_FEATURES):
        raise RuntimeError("R28_CONTROL_BASELINE_FEATURE_MISMATCH")
    if manifest["oof_folds"] != [list(row) for row in R1.OOF_FOLDS]:
        raise RuntimeError("R28_CONTROL_FOLD_MISMATCH")
    return manifest, source, source["files"]


def exact_paths(source_files: list[dict]) -> dict[str, list[Path]]:
    output = {symbol: [] for symbol in R1.SYMBOLS}
    for record in source_files:
        path = Path(record["path"])
        if not path.is_file() or DATA_ROOT not in path.parents:
            raise RuntimeError("R28_CONTROL_SOURCE_PATH_INVALID")
        if sha_file(path) != record["sha256"]:
            raise RuntimeError("R28_CONTROL_SOURCE_HASH_MISMATCH:" + str(path))
        output[record["symbol"]].append(path)
    if any(not output[symbol] for symbol in R1.SYMBOLS):
        raise RuntimeError("R28_CONTROL_SOURCE_SYMBOL_MISSING")
    return {symbol: sorted(paths) for symbol, paths in output.items()}


def read_symbol(paths: list[Path]) -> pd.DataFrame:
    frame = pd.concat([pd.read_parquet(path, columns=list(R1.REQUIRED_COLUMNS)) for path in paths], ignore_index=True)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    frame["timestamp_et"] = R1.normalized_et(frame["timestamp_et"])
    frame = frame.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["session_code"] = frame["session"].astype(str).str.upper().map(R1.SESSION_CODE).fillna(4).astype(int)
    frame["valid"] = ((frame["open"] > 0) & (frame["high"] >= frame[["open", "low", "close"]].max(axis=1))
                      & (frame["low"] <= frame[["open", "high", "close"]].min(axis=1)))
    return frame


def build_common_universe(data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    frames, audits = [], {}
    for symbol, peer in (("QQQ", "SOXX"), ("SOXX", "QQQ")):
        candidates, candidate_audit = R1.candidate_features(data[symbol], symbol, include_labels=True)
        new_features = build_features(data[symbol], data[peer])
        feature_pit = pit_audit(new_features.dropna(subset=list(R28_FEATURES)))["pit_pass"]
        new = new_features.rename(columns={"timestamp_utc": "decision_timestamp_utc"})
        merge_columns = ["decision_timestamp_utc", *R28_FEATURES, "source_timestamp_utc", "max_feature_timestamp_utc", "feature_information_available"]
        joined = candidates.merge(new[merge_columns], on="decision_timestamp_utc", how="inner", suffixes=("", "_r28"))
        if not joined["feature_information_available_r28"].all() or not (joined["max_feature_timestamp_utc_r28"] <= joined["decision_timestamp_utc"]).all():
            raise RuntimeError("R28_FEATURE_PIT_FAILURE:" + symbol)
        audits[symbol] = {"candidate_rows": int(len(candidates)), "joined_rows": int(len(joined)),
                          "feature_pit": feature_pit, **candidate_audit}
        frames.append(joined)
    raw = pd.concat(frames, ignore_index=True)
    complete = raw.dropna(subset=list(R28_FEATURES)).copy().reset_index(drop=True)
    complete["candidate_id"] = (complete["underlying_symbol"].astype(str) + "|" + complete["direction"].astype(str)
                                + "|" + complete["decision_timestamp_utc"].astype(str))
    if complete["candidate_id"].duplicated().any():
        raise RuntimeError("R28_COMMON_UNIVERSE_DUPLICATE_CANDIDATE")
    return complete, {"raw_row_count": int(len(raw)), "common_comparable_row_count": int(len(complete)), "symbols": audits}


def hgb(features: tuple[str, ...]) -> HistGradientBoostingClassifier:
    categorical = [name in {"symbol_code", "session_code"} for name in features]
    return HistGradientBoostingClassifier(**HGB_PARAMS, categorical_features=categorical)


def ranking_metrics(frame: pd.DataFrame, probability: np.ndarray, threshold: float) -> tuple[dict, pd.DataFrame]:
    scored = frame[["candidate_id", "decision_timestamp_utc", "underlying_symbol", "direction", "target_first"]].copy()
    scored["probability"] = probability
    ranked = scored.sort_values(["probability", "decision_timestamp_utc", "underlying_symbol", "direction"], ascending=[False, True, True, True], kind="mergesort")
    base = float(scored["target_first"].mean())
    selected5, selected10 = max(1, int(np.ceil(len(scored) * .05))), max(1, int(np.ceil(len(scored) * .10)))
    top5 = float(ranked.head(selected5)["target_first"].mean())
    top10 = float(ranked.head(selected10)["target_first"].mean())
    scored["selected"] = scored["probability"] >= threshold
    metrics = {"sample_count": int(len(scored)), "positive_count": int(scored["target_first"].sum()), "selected_count": int(scored["selected"].sum()),
               "base_rate": base, "top5_lift": float(top5 / base) if base else None, "top10_lift": float(top10 / base) if base else None,
               "pr_auc": float(average_precision_score(scored["target_first"], probability)),
               "roc_auc": float(roc_auc_score(scored["target_first"], probability)), "brier": float(brier_score_loss(scored["target_first"], probability))}
    return metrics, scored


def gain_audit(model: HistGradientBoostingClassifier, features: tuple[str, ...]) -> dict:
    gains = {name: 0.0 for name in features}; splits = {name: 0 for name in features}
    for stage in model._predictors:
        for tree in stage:
            nodes = tree.nodes
            for node in nodes[nodes["is_leaf"] == 0]:
                name = features[int(node["feature_idx"])]
                splits[name] += 1; gains[name] += max(0.0, float(node["gain"]))
    total = sum(gains.values())
    rows = [{"feature": name, "split_count": splits[name], "gain_sum": gains[name], "gain_share": gains[name] / total if total else 0.0} for name in features]
    return {"features": sorted(rows, key=lambda row: (-row["gain_sum"], row["feature"])), "total_gain": total}


def aggregate(rows: list[dict]) -> dict:
    values5 = np.asarray([row["top5_lift"] for row in rows], dtype=float); values10 = np.asarray([row["top10_lift"] for row in rows], dtype=float)
    return {"median_top5_lift": float(np.median(values5)), "median_top10_lift": float(np.median(values10)),
            "worst_quartile_top5_lift": float(np.quantile(values5, .25)), "top5_slice_dispersion": float(np.std(values5)),
            "total_selected_count": int(sum(row["selected_count"] for row in rows))}


def run_candidate(candidate: str, universe: pd.DataFrame, folds: list[list[str]], thresholds: dict, feature_manifest_sha: str,
                  scratch: Path, created_at: str) -> tuple[list[dict], dict]:
    features = CANDIDATES[candidate]; results, audits = [], {}
    for head in HEADS:
        head_frame = universe[universe["direction"].eq(head)].copy()
        head_rows, gain_rows = [], []
        for fold_name, raw_start, raw_end in folds:
            train, validation, audit = R1.construct_purged_fold(head_frame, fold_name, raw_start, raw_end)
            if train.empty or validation.empty or train["target_first"].nunique() < 2 or not (audit["purge_pass"] and audit["embargo_pass"] and audit["time_order_pass"]):
                raise RuntimeError(f"R28_PIT_OR_FOLD_FAILURE:{candidate}:{head}:{fold_name}")
            model = hgb(features).fit(train[list(features)], train["target_first"].astype(int))
            model_path = scratch / "models" / f"{candidate}_{head}_{fold_name}.joblib"
            joblib.dump(model, model_path, compress=3)
            model_sha = sha_file(model_path)
            metrics, ledger = ranking_metrics(validation, model.predict_proba(validation[list(features)])[:, 1], thresholds[f"{head}_HGB_THRESHOLD"])
            snapshot = sha_text("\n".join(validation["candidate_id"].astype(str)) + "|" + "|".join(features))
            ledger["candidate"] = candidate; ledger["head"] = head; ledger["validation_slice"] = fold_name
            ledger["feature_snapshot_hash"] = snapshot; ledger["feature_manifest_sha256"] = feature_manifest_sha; ledger["model_sha256"] = model_sha
            ledger["frozen_threshold"] = thresholds[f"{head}_HGB_THRESHOLD"]; ledger["created_at"] = created_at
            ledger.to_parquet(scratch / "ledgers" / f"{candidate}_{head}_{fold_name}.parquet", index=False)
            row = {"candidate": candidate, "head": head, "validation_slice": fold_name, **metrics, "model_sha256": model_sha, "feature_snapshot_hash": snapshot}
            results.append(row); head_rows.append(row); gain_rows.append(gain_audit(model, features)["features"]); audits.setdefault(head, []).append(audit)
        combined = pd.concat([pd.read_parquet(scratch / "ledgers" / f"{candidate}_{head}_{fold[0]}.parquet") for fold in folds], ignore_index=True)
        combined.to_parquet(scratch / "ledgers" / f"{candidate}_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet", index=False)
        gain = pd.DataFrame([item for rows in gain_rows for item in rows]).groupby("feature", as_index=False)[["split_count", "gain_sum"]].sum()
        total = float(gain["gain_sum"].sum()); gain["gain_share"] = gain["gain_sum"] / total if total else 0.0
        audits[head] = {"folds": audits[head], "gain": gain.sort_values(["gain_sum", "feature"], ascending=[False, True]).to_dict("records"), "ledger_sha256": sha_file(scratch / "ledgers" / f"{candidate}_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet")}
    return results, audits


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", required=True); args = parser.parse_args()
    if any(SOURCE_ROOT.rglob(".local_results")):
        raise RuntimeError("R28_LOCAL_RESULTS_FORBIDDEN")
    runtime = RESULTS_ROOT / "runtime" / "fast3" / f"r28_phase2_{args.run_id}"; scratch = RESULTS_ROOT / "scratch" / "fast3" / f"r28_phase2_{args.run_id}"; frozen = RESULTS_ROOT / "frozen" / "fast3" / f"r28_phase2_{args.run_id}"
    for directory in (runtime, scratch / "models", scratch / "ledgers", frozen): directory.mkdir(parents=True, exist_ok=False)
    control, source, records = control_inputs(); paths = exact_paths(records); data = {symbol: read_symbol(paths[symbol]) for symbol in R1.SYMBOLS}
    universe, universe_audit = build_common_universe(data); created_at = datetime.now(timezone.utc).isoformat()
    feature_manifest = {"baseline_features": list(BASELINE_FEATURES), "new_features": list(R28_FEATURES), "candidates": {name: list(features) for name, features in CANDIDATES.items()}, "categorical_features": ["symbol_code", "session_code"], "blocked_features": ["VIX", "SPY", "external_flow", "options_metrics"], "source_manifest_sha256": source["sha256"]}
    feature_manifest_path = frozen / "R28_FEATURE_MANIFEST.json"; write_json(feature_manifest_path, feature_manifest); feature_manifest_sha = sha_file(feature_manifest_path)
    baseline_rows, baseline_audit = run_candidate("R28_0_BASELINE", universe, control["oof_folds"], control["thresholds"], feature_manifest_sha, scratch, created_at)
    baseline_global = {head: ranking_metrics(pd.concat([pd.read_parquet(scratch / "ledgers" / f"R28_0_BASELINE_{head}_{fold[0]}.parquet") for fold in control["oof_folds"]], ignore_index=True).rename(columns={"probability": "probability"}), np.array([]), 0.0) for head in []}
    baseline_summary = {head: aggregate([row for row in baseline_rows if row["head"] == head]) for head in HEADS}
    reproduction = {head: abs(float(np.average([row["top5_lift"] for row in baseline_rows if row["head"] == head], weights=[row["sample_count"] for row in baseline_rows if row["head"] == head])) - float(control["oof_metrics"][f"{head}_HGB"]["lift"])) <= .20 for head in HEADS}
    if not all(reproduction.values()):
        decision = {"status": "STOP_R28_BASELINE_REPRODUCTION_FAILURE", "baseline_reproduction": reproduction, "universe": universe_audit, "data_root_write_count": 0}
        write_json(runtime / "R28_PHASE2_RUNTIME_SUMMARY.json", decision); write_json(frozen / "R28_PHASE2_DECISION.json", decision); print(json.dumps(decision)); return
    all_rows, all_audits = baseline_rows, {"R28_0_BASELINE": baseline_audit}
    for candidate in tuple(CANDIDATES)[1:]:
        rows, audit = run_candidate(candidate, universe, control["oof_folds"], control["thresholds"], feature_manifest_sha, scratch, created_at); all_rows.extend(rows); all_audits[candidate] = audit
    comparisons = {}
    for head in HEADS:
        baseline = [row for row in all_rows if row["candidate"] == "R28_0_BASELINE" and row["head"] == head]; baseline_by_fold = {row["validation_slice"]: row for row in baseline}
        comparisons[head] = {}
        for candidate in CANDIDATES:
            rows = [row for row in all_rows if row["candidate"] == candidate and row["head"] == head]; summary = aggregate(rows)
            if candidate == "R28_0_BASELINE": stable = False
            else:
                ratio = float(np.mean([row["top5_lift"] >= baseline_by_fold[row["validation_slice"]]["top5_lift"] for row in rows]))
                stable = bool(summary["median_top5_lift"] > aggregate(baseline)["median_top5_lift"] and summary["median_top10_lift"] >= aggregate(baseline)["median_top10_lift"] - .02 and ratio >= .70 and summary["total_selected_count"] >= max(100, int(.001 * sum(row["sample_count"] for row in rows))))
                summary["noninferior_slice_ratio"] = ratio
            summary["stability_pass"] = stable; comparisons[head][candidate] = summary
    champions = {head: next((candidate for candidate in CANDIDATES if comparisons[head][candidate]["stability_pass"]), "NONE") for head in HEADS}
    decision_name = "PASS_R28_STABLE_INCREMENTAL_EDGE" if any(value != "NONE" for value in champions.values()) else "STOP_R28_NO_STABLE_INCREMENTAL_FACTOR_EDGE"
    decision = {"status": "PASS" if decision_name.startswith("PASS") else "STOP", "decision": decision_name, "created_at": created_at, "period_lock": {"train_start": "2018-07-19", "train_end": control["final_training_candidate_max_timestamp"], "validation_start": control["oof_folds"][0][1], "validation_end": control["oof_folds"][-1][2], "folds": control["oof_folds"]}, "baseline_period_reproduction_pass": all(reproduction.values()), "baseline_reproduction_by_head": reproduction, "common_universe": universe_audit, "results": all_rows, "comparisons": comparisons, "champions": champions, "feature_audit": all_audits, "feature_manifest_sha256": feature_manifest_sha, "post_hoc_historical_rescoring_for_economic_test": "PROHIBITED", "data_root_write_count": 0, "newer_historical_data_used": False, "hyperparameter_search_executed": False, "threshold_optimization_executed": False, "new_feature_search_executed": False, "holdout_rescoring_executed": False, "prospective_outcome_used_for_training": False, "prospective_outcome_used_for_selection": False, "economic_evaluation_executed": False}
    write_json(runtime / "R28_PHASE2_RUNTIME_SUMMARY.json", decision); write_json(frozen / "R28_PHASE2_DECISION.json", decision); write_json(frozen / "R28_PHASE2_LINEAGE.json", {"control_manifest_sha256": sha_file(CONTROL / "cleanroom_r2_freeze_manifest.json"), "source_manifest_sha256": source["sha256"], "feature_manifest_sha256": feature_manifest_sha, "ledger_hashes": {candidate: {head: all_audits[candidate][head]["ledger_sha256"] for head in HEADS} for candidate in CANDIDATES}})
    print(json.dumps({"status": decision["status"], "decision": decision_name, "champions": champions, "common_rows": len(universe)}))


if __name__ == "__main__": main()
