"""Locked 2026 evaluation adapter for the A2 open-research freeze.

The module is intentionally separate from ``a2_open_research_engine.py`` so a
pre-2026 search can continue undisturbed.  The only path to market/target data
is through :func:`run_locked_holdout`, whose first operation verifies the
complete pre-2026 freeze.  This module never fits, tunes, recalibrates, or
selects a model.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import joblib
import numpy as np
import pandas as pd


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
DEFAULT_RESEARCH_ROOT = RESULTS_ROOT / "A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1"
R2A_SOURCE = REPO_ROOT / "scripts/v22/a2_algorithm_r2a_2026_retrospective_and_forward_shadow_anchor.py"
ECONOMICS_SOURCE = REPO_ROOT / "scripts/v22/a_a2_2026_pre_risk_holdout_r1.py"
ENGINE_SOURCE = REPO_ROOT / "scripts/v22/a2_open_research_engine.py"
HOLDOUT_DIRECTORY = "10_2026_locked_holdout"
HOLDOUT_LABEL = "USER_AUTHORIZED_LOCKED_2026_HOLDOUT"
TOP_K = 20
COST_BPS = 10

ZERO_COUNTERS = (
    "2026_training_rows",
    "2026_feature_selection_rows",
    "2026_parameter_search_count",
    "2026_threshold_search_count",
    "2026_model_selection_count",
    "2026_ensemble_weight_search_rows",
    "2026_factor_discovery_target_reads",
)


class HoldoutGovernanceError(RuntimeError):
    """A fail-closed holdout or temporal-governance violation."""


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        suffix = f"|{evidence}" if evidence != "" else ""
        raise HoldoutGovernanceError(f"{code}{suffix}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_source_module(name: str, path: Path) -> Any:
    require(path.is_file(), "SOURCE_MODULE_MISSING", path)
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "SOURCE_MODULE_LOAD_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


@dataclass(frozen=True)
class VerifiedFreeze:
    research_root: Path
    freeze_sha256: str
    freeze_manifest: dict[str, Any]
    champion_manifest: dict[str, Any]

    @property
    def frozen_models(self) -> list[dict[str, Any]]:
        return list(self.champion_manifest["frozen_models"])


def _verify_core_freeze_hash(manifest: dict[str, Any]) -> str:
    claimed = manifest.get("pre2026_freeze_sha256")
    require(isinstance(claimed, str) and len(claimed) == 64, "PRE2026_FREEZE_SHA_MISSING")
    core = {
        key: value
        for key, value in manifest.items()
        if key not in {"pre2026_freeze_sha256", "post_freeze_identifier_artifact_hashes"}
    }
    require(canonical_hash(core) == claimed, "PRE2026_FREEZE_SHA_MISMATCH")
    return claimed


def verify_freeze_gate(
    research_root: Path,
    *,
    engine_source: Path = ENGINE_SOURCE,
) -> VerifiedFreeze:
    """Verify the full freeze without touching any 2026 market/outcome data."""
    root = research_root.resolve()
    freeze_dir = root / "09_pre2026_freeze"
    freeze_path = freeze_dir / "pre2026_freeze_manifest.json"
    champion_path = freeze_dir / "pre2026_champion_manifest.json"
    require(freeze_path.is_file(), "PRE2026_FREEZE_MISSING", freeze_path)
    require(champion_path.is_file(), "PRE2026_CHAMPION_MANIFEST_MISSING", champion_path)

    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    champion = json.loads(champion_path.read_text(encoding="utf-8"))
    require(freeze.get("pre2026_research_complete") is True, "PRE2026_RESEARCH_INCOMPLETE")
    require(freeze.get("pre2026_selection_complete") is True, "PRE2026_SELECTION_INCOMPLETE")
    require(freeze.get("pre2026_champion_frozen") is True, "PRE2026_CHAMPION_NOT_FROZEN")
    require(freeze.get("2026_outcome_read_count_at_freeze") == 0, "PRE_FREEZE_2026_OUTCOME_READ")
    freeze_sha = _verify_core_freeze_hash(freeze)

    artifact_hashes = freeze.get("artifact_hashes", {})
    require(artifact_hashes.get(champion_path.name) == sha256_file(champion_path), "CHAMPION_MANIFEST_HASH_MISMATCH")
    for name, expected in artifact_hashes.items():
        artifact = freeze_dir / name
        require(artifact.is_file(), "FROZEN_ARTIFACT_MISSING", artifact)
        require(sha256_file(artifact) == expected, "FROZEN_ARTIFACT_HASH_MISMATCH", name)

    require(champion.get("run_id") == freeze.get("run_id"), "FREEZE_RUN_ID_MISMATCH")
    require(champion.get("status") == "RESEARCH_CHALLENGER_NOT_DEPLOYMENT_AUTHORIZATION", "CHAMPION_STATUS_INVALID")
    require(champion.get("champion_id") in freeze.get("selected_candidate_ids", []), "CHAMPION_ID_MISMATCH")
    counters = champion.get("temporal_counters", {})
    for counter in ZERO_COUNTERS:
        require(counter in counters, "HOLDOUT_GATE_COUNTER_MISSING", counter)
        require(counters[counter] == 0, "HOLDOUT_GATE_COUNTER_NONZERO", counter)

    thresholds = champion.get("thresholds", {})
    execution = champion.get("execution", {})
    require(thresholds.get("holdout_top_k") == TOP_K, "HOLDOUT_TOP_K_NOT_FROZEN_TOP20")
    require(thresholds.get("economic_top_k") == TOP_K, "ECONOMIC_TOP_K_NOT_FROZEN_TOP20")
    require(execution.get("cost_bps") == COST_BPS, "HOLDOUT_COST_NOT_FROZEN_10BPS")
    require(
        execution.get("mapping") == "FROZEN_R4_CLOSE_TO_NEXT_OPEN_EQUAL_WEIGHT_LONG_ONLY",
        "EXECUTION_MAPPING_MISMATCH",
    )

    ensemble = champion.get("ensemble", {})
    members = list(ensemble.get("members", []))
    weights = np.asarray(ensemble.get("weights", []), dtype=float)
    require(members and len(members) == len(weights), "ENSEMBLE_IDENTITY_INVALID")
    require(np.isfinite(weights).all() and np.all(weights > 0), "ENSEMBLE_WEIGHT_INVALID")
    require(abs(float(weights.sum()) - 1.0) <= 1e-12, "ENSEMBLE_WEIGHT_SUM_INVALID")
    if ensemble.get("type") == "FIXED_EQUAL_RANK_AVERAGE":
        require(np.allclose(weights, np.repeat(1.0 / len(weights), len(weights))), "ENSEMBLE_NOT_FIXED_EQUAL_WEIGHT")
    else:
        require(ensemble.get("type") == "NONE" and len(members) == 1, "UNSUPPORTED_ENSEMBLE_TYPE")

    require(engine_source.is_file(), "FROZEN_MODEL_CODE_MISSING", engine_source)
    require(sha256_file(engine_source) == freeze.get("model_code_sha256"), "FROZEN_MODEL_CODE_HASH_MISMATCH")
    models = champion.get("frozen_models", [])
    require(isinstance(models, list) and models, "FROZEN_MODELS_MISSING")
    freeze_model_hashes = freeze.get("model_hashes", {})
    for model in models:
        path = Path(model["model_path"])
        require(path.is_file(), "FROZEN_MODEL_MISSING", path)
        actual = sha256_file(path)
        require(actual == model.get("model_sha256"), "CHAMPION_MODEL_HASH_MISMATCH", path.name)
        require(actual == freeze_model_hashes.get(path.name), "FREEZE_MODEL_HASH_MISMATCH", path.name)
        features = model.get("features", [])
        require(len(features) >= 32 and len(features) == len(set(features)), "FROZEN_FEATURE_SET_INVALID", path.name)
        require(model.get("training_rows", 0) > 0, "FROZEN_MODEL_TRAINING_IDENTITY_INVALID", path.name)
        require(pd.Timestamp(model["max_label_maturity"]) < pd.Timestamp("2026-01-01"), "FROZEN_MODEL_LABEL_CROSSES_CUTOFF", path.name)

    return VerifiedFreeze(root, freeze_sha, freeze, champion)


def assert_locked_temporal_rows(frame: pd.DataFrame, available_through: pd.Timestamp) -> None:
    required = {"feature_information_available_timestamp", "label_maturity_timestamp", "target"}
    require(required.issubset(frame.columns), "LOCKED_TEMPORAL_COLUMNS_MISSING", sorted(required - set(frame.columns)))
    feature_time = pd.to_datetime(frame.feature_information_available_timestamp)
    label_time = pd.to_datetime(frame.label_maturity_timestamp)
    require(feature_time.notna().all() and feature_time.le(available_through).all(), "UNAVAILABLE_FEATURE_INFORMATION")
    require(label_time.notna().all() and label_time.le(available_through).all(), "UNMATURED_2026_LABEL")
    require(frame.target.notna().all() and np.isfinite(frame.target.to_numpy(float)).all(), "UNMATURED_OR_NONFINITE_TARGET")


def _build_feature_matrix(
    gate: VerifiedFreeze,
    feature_source: Any,
    factor_source: Any,
    prices: pd.DataFrame,
    qqq: pd.DataFrame,
    universe: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    features = feature_source.build_stock_state_features(
        prices[["ticker", "trade_date", "close", "volume"]].copy()
    ).rename(columns={"trade_date": "signal_date"})
    calendar = pd.DatetimeIndex(qqq.trade_date)
    positions = pd.Series(np.arange(len(calendar)), index=calendar)
    features["calendar_position"] = features.signal_date.map(positions)
    features["position_120_prior"] = features.groupby("ticker").calendar_position.shift(120)
    features["required_observations"] = features.groupby("ticker").cumcount() + 1
    features["sufficient_history"] = (
        features.required_observations.ge(121)
        & features.position_120_prior.notna()
        & features.calendar_position.sub(features.position_120_prior).eq(120)
    )
    model_features = [list(model["features"]) for model in gate.frozen_models]
    base_features = list(feature_source.FEATURE_COLUMNS)
    require(len(base_features) == 32, "BASE_FEATURE_COUNT_NOT_32")
    require(all(columns[:32] == base_features for columns in model_features), "FROZEN_BASE_FEATURE_ORDER_MISMATCH")
    require(set(base_features).issubset(features.columns), "BASE_FEATURE_NOT_MATERIALIZED")
    features["complete_base_features"] = np.isfinite(features[base_features].to_numpy(float)).all(axis=1)
    matrix = universe.merge(
        features[["signal_date", "ticker", "close", *base_features, "sufficient_history", "complete_base_features"]],
        on=["signal_date", "ticker"], how="left", validate="one_to_one",
    )
    coverage = matrix.groupby(["signal_date", "quarter", "effective_date"], as_index=False).agg(
        authoritative_universe_count=("ticker", "size"),
        price_row_count=("close", "count"),
        sufficient_history_count=("sufficient_history", lambda value: int(value.fillna(False).sum())),
        complete_base_feature_count=("complete_base_features", lambda value: int(value.fillna(False).sum())),
    )
    matrix = matrix.loc[
        matrix.sufficient_history.fillna(False) & matrix.complete_base_features.fillna(False)
    ].copy()
    # This function is hash-pinned to the exact engine source by the freeze gate.
    matrix = factor_source.materialize_factors(matrix)
    all_features = list(dict.fromkeys(column for columns in model_features for column in columns))
    require(set(all_features).issubset(matrix.columns), "FROZEN_FACTOR_NOT_MATERIALIZED", sorted(set(all_features) - set(matrix.columns)))
    finite = np.isfinite(matrix[all_features].to_numpy(float)).all(axis=1)
    matrix = matrix.loc[finite].copy()
    require(matrix.groupby("signal_date").size().ge(TOP_K).all(), "LOCKED_UNIVERSE_BELOW_TOP20")
    matrix["feature_information_available_timestamp"] = (
        pd.to_datetime(matrix.signal_date) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    )
    return matrix.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True), coverage


def _score_frozen_models(gate: VerifiedFreeze, matrix: pd.DataFrame, factor_source: Any) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for index, frozen in enumerate(gate.frozen_models):
        model = joblib.load(Path(frozen["model_path"]))
        columns = list(frozen["features"])
        expected = getattr(model, "n_features_in_", len(columns))
        require(int(expected) == len(columns), "FROZEN_MODEL_FEATURE_COUNT_MISMATCH", frozen["model_path"])
        scored = matrix[["signal_date", "ticker"]].copy()
        scored["family"] = str(frozen["family"])
        scored["seed"] = int(frozen["seed"])
        scored["score"] = np.asarray(model.predict(matrix[columns].to_numpy(np.float32)), dtype=float)
        require(np.isfinite(scored.score).all(), "NONFINITE_FROZEN_MODEL_PREDICTION")
        pieces.append(scored)
    raw = pd.concat(pieces, ignore_index=True)
    family = raw.groupby(["signal_date", "ticker", "family"], as_index=False).score.mean()
    family = family.rename(columns={"score": "family_score"})
    family["family_rank"] = factor_source.stable_rank(
        family.rename(columns={"family_score": "prediction"})
    )
    ensemble = gate.champion_manifest["ensemble"]
    members = list(ensemble["members"])
    # Multi-seed MLP is represented by its frozen base family after seed mean.
    if members == ["MLP_MULTI_SEED_MEAN"] and set(family.family) == {"MLP"}:
        members = ["MLP"]
    require(set(members).issubset(set(family.family)), "FROZEN_ENSEMBLE_MEMBER_MISSING")
    wide = family.loc[family.family.isin(members)].pivot(
        index=["signal_date", "ticker"], columns="family", values="family_rank"
    )
    require(not wide.isna().any().any(), "FROZEN_ENSEMBLE_MEMBER_COVERAGE_MISMATCH")
    weights = pd.Series(gate.champion_manifest["ensemble"]["weights"], index=members, dtype=float)
    score = wide.loc[:, members].mul(weights, axis=1).sum(axis=1)
    result = score.rename("score").reset_index()
    result["rank"] = factor_source.stable_rank(result.rename(columns={"score": "prediction"}))
    result["model"] = str(gate.champion_manifest["champion_id"])
    return result.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)


def _locked_data_and_evaluation(gate: VerifiedFreeze) -> dict[str, Any]:
    """The sole 2026-read path. Call only after ``verify_freeze_gate``."""
    r2a = load_source_module("a2_locked_r2a_source", R2A_SOURCE)
    old = load_source_module("a2_locked_economics_source", ECONOMICS_SOURCE)
    factor_source = load_source_module("a2_locked_factor_source", ENGINE_SOURCE)
    feature_source = load_source_module("a2_locked_feature_source", r2a.FEATURE_SOURCE)
    price_adapter = load_source_module("a2_locked_price_adapter", r2a.ADAPTER)

    qqq, pointer = r2a.load_qqq()
    latest = pd.Timestamp(qqq.trade_date.max())
    active, members = r2a.validate_pit_manifest(qqq)
    prices, price_audit = r2a.load_equity_prices(price_adapter, members, latest)
    universe = r2a.active_universe_by_date(qqq, active, members, latest)
    matrix, coverage = _build_feature_matrix(
        gate, feature_source, factor_source, prices, qqq, universe
    )
    predictions = _score_frozen_models(gate, matrix, factor_source)
    evaluation = r2a.attach_targets(predictions.merge(
        matrix[["signal_date", "ticker", "close", "feature_information_available_timestamp"]],
        on=["signal_date", "ticker"], validate="one_to_one",
    ), prices, qqq)
    available_through = latest + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    evaluation["label_maturity_timestamp"] = (
        pd.to_datetime(evaluation.target_end_date) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    )
    evaluation = evaluation.loc[
        evaluation.signal_date.dt.year.eq(2026)
        & evaluation.target.notna()
        & evaluation.label_maturity_timestamp.le(available_through)
    ].copy()
    require(not evaluation.empty, "NO_MATURE_LOCKED_2026_ROWS")
    assert_locked_temporal_rows(evaluation, available_through)
    require(evaluation.groupby("signal_date").size().ge(TOP_K).all(), "MATURE_LOCKED_UNIVERSE_BELOW_TOP20")
    require(evaluation.loc[evaluation["rank"].le(TOP_K), "target"].notna().all(), "TOP20_TARGET_NOT_MATURE")

    first_date = pd.Timestamp(evaluation.signal_date.min())
    last_signal = pd.Timestamp(evaluation.signal_date.max())
    calendar = pd.DatetimeIndex(qqq.trade_date)
    expected = calendar[(calendar >= first_date) & (calendar <= last_signal)]
    actual = pd.DatetimeIndex(sorted(evaluation.signal_date.unique()))
    require(actual.equals(expected), "LOCKED_EVALUATION_DATE_GAP")
    require(calendar.get_loc(last_signal) + 1 < len(calendar), "NEXT_OPEN_EXECUTION_NOT_AVAILABLE")
    execution_end = pd.Timestamp(calendar[calendar.get_loc(last_signal) + 1])

    old.EFFECTIVE_START = first_date
    old.COST_BPS = COST_BPS
    target_map = old.build_target_map(evaluation, "rank")
    all_prices = pd.concat([
        prices.loc[prices.trade_date.le(execution_end)],
        qqq.loc[qqq.trade_date.le(execution_end), ["ticker", "trade_date", "open", "close", "volume"]],
    ], ignore_index=True, sort=False)
    champion = str(gate.champion_manifest["champion_id"])
    path = old.reconstruct_open_ended(champion, target_map, all_prices, calendar, execution_end)
    require(not path.missing_price_events, "LOCKED_EXECUTION_MISSING_PRICE_EVENT", path.missing_price_events[:5])

    long = evaluation[["signal_date", "ticker", "target", "target_end_date", "score", "rank"]].copy()
    long = long.rename(columns={"signal_date": "prediction_date"})
    long["model"] = champion
    long["selected_top20"] = long["rank"].le(TOP_K)
    predictive = r2a.predictive_metrics(long)
    economics = r2a.economic_metrics(old, {champion: path})
    return {
        "latest": latest, "first_date": first_date, "last_signal": last_signal,
        "execution_end": execution_end, "predictions": long, "predictive": predictive,
        "economics": economics, "daily": path.daily, "coverage": coverage,
        "input_audit": {"benchmark_pointer": pointer, "price_audit": price_audit},
    }


def _external_holdout_output(research_root: Path) -> Path:
    root = research_root.resolve()
    require(root == DEFAULT_RESEARCH_ROOT.resolve() or root.is_relative_to(RESULTS_ROOT.resolve()), "RESEARCH_ROOT_NOT_EXTERNAL_RESULTS")
    require(not root.is_relative_to(REPO_ROOT.resolve()), "RESEARCH_ROOT_INSIDE_REPOSITORY")
    output = root / HOLDOUT_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    require(not any(output.iterdir()), "LOCKED_HOLDOUT_OUTPUT_NOT_EMPTY", output)
    return output


def run_locked_holdout(
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    *,
    evaluator: Callable[[VerifiedFreeze], dict[str, Any]] = _locked_data_and_evaluation,
) -> dict[str, Any]:
    """Verify, read exactly once, evaluate frozen identities, and persist externally."""
    gate = verify_freeze_gate(research_root)
    output = _external_holdout_output(gate.research_root)
    # No evaluator (and therefore no 2026 reader) can run before the gate above.
    result = evaluator(gate)
    atomic_parquet(output / "locked_2026_predictions.parquet", result["predictions"])
    atomic_csv(output / "locked_2026_predictive_metrics.csv", result["predictive"])
    atomic_csv(output / "locked_2026_economic_metrics.csv", result["economics"])
    atomic_parquet(output / "locked_2026_daily.parquet", result["daily"])
    atomic_csv(output / "locked_2026_universe_coverage.csv", result["coverage"])
    report = {
        "holdout_label": HOLDOUT_LABEL,
        "no_new_research_decision_used_2026": True,
        "pre2026_freeze_sha256": gate.freeze_sha256,
        "champion_id": gate.champion_manifest["champion_id"],
        "first_2026_signal_date": str(result["first_date"].date()),
        "last_mature_2026_signal_date": str(result["last_signal"].date()),
        "latest_available_market_date": str(result["latest"].date()),
        "execution_end": str(result["execution_end"].date()),
        "2026_training_rows": 0,
        "2026_feature_selection_count": 0,
        "2026_parameter_search_count": 0,
        "2026_threshold_search_count": 0,
        "2026_model_selection_count": 0,
        "2026_ensemble_weight_search_count": 0,
        "model_refit_count": 0,
        "threshold": {"top_k": TOP_K},
        "cost_bps": COST_BPS,
        "predictive_metrics": result["predictive"].to_dict(orient="records"),
        "economic_metrics": result["economics"].to_dict(orient="records"),
        "2026_result_classification": "LOCKED_RESULT_REPORTED_NO_ADAPTATION",
        "deployment_status": "RESEARCH_CHALLENGER_NOT_AUTHORIZED_FOR_DEPLOYMENT",
        "input_audit": result["input_audit"],
    }
    atomic_json(output / "locked_2026_holdout_report.json", report)
    artifacts = []
    for path in sorted(output.iterdir(), key=lambda item: item.name):
        if path.name != "manifest.json":
            artifacts.append({"artifact": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    atomic_json(output / "manifest.json", {
        "classification": HOLDOUT_LABEL,
        "pre2026_freeze_sha256": gate.freeze_sha256,
        "artifacts": artifacts,
        "self_hash_excluded_because_recursive": True,
    })
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-root", type=Path, default=DEFAULT_RESEARCH_ROOT)
    parser.add_argument("--execute-locked-holdout", action="store_true")
    args = parser.parse_args(argv)
    try:
        gate = verify_freeze_gate(args.research_root)
        print(f"PRE2026_CHAMPION_FROZEN=true\nPRE2026_FREEZE_SHA256={gate.freeze_sha256}")
        if not args.execute_locked_holdout:
            print("2026_HOLDOUT_OPENED_AFTER_FREEZE=false")
            print("NEXT_STEP=RERUN_WITH_--execute-locked-holdout")
            return 0
        report = run_locked_holdout(args.research_root)
        print("2026_HOLDOUT_OPENED_AFTER_FREEZE=true")
        print(f"2026_RESULT_CLASSIFICATION={report['2026_result_classification']}")
        return 0
    except Exception as exc:
        print(f"LOCKED_2026_HOLDOUT_STATUS=FAIL_CLOSED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
