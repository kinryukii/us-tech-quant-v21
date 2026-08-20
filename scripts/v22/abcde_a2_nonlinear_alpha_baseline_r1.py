"""ABCDE A2-R0/R1 nonlinear stock-state baseline with fail-closed PIT gates.

This module is research-only.  It deliberately performs the A2-R0 contract
audit before any target materialization or model fit.  A2-R1 is not allowed to
run unless the historical universe can be established point-in-time.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.ensemble import HistGradientBoostingRegressor


EXPERIMENT_ID = "ABCDE_A2_R0_R1_NONLINEAR_ALPHA_BASELINE_R1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(r"D:\us-tech-quant-data")
DEFAULT_RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
PRICE_ROOT = DATA_ROOT / "moomoo/source/prices_qfq"
UNIVERSE_MANIFEST = DATA_ROOT / "moomoo/metadata/abcde_price_universe_r2.active_manifest.json"
UNIVERSE_TABLE = DATA_ROOT / "moomoo/metadata/abcde_price_universe_r2.csv"
PROXY_MANIFEST = DATA_ROOT / "derived_cache/abcde_current_rule_proxy_rankings_r8/historical_proxy_rankings.json"
A1_FREEZE = REPO_ROOT / "config/v21/abcde_compact_v1_freeze_r1.json"
A1_PRODUCER = REPO_ROOT / "scripts/v21/v21_233_moomoo_only_abcde_rerun.py"
A1_GUARD = REPO_ROOT / "scripts/v22/abcde_compact_v1_freeze_r1_guard.py"
TRAINING_BOUNDARY = pd.Timestamp("2026-01-01")
TRAINING_CUTOFF = "2025-12-31"
TARGET_HORIZONS = (3, 5, 10, 20)
PRIMARY_TARGET = "MEAN_ER_3D_5D_10D_20D"
SECONDARY_TARGET = "ER_5D"
TARGET_BENCHMARK = "QQQ"
FEATURES = (
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120",
    "ma10_vs_ma20", "ma20_vs_ma50", "ma50_vs_ma120",
    "realized_vol_5d", "realized_vol_10d", "realized_vol_20d", "realized_vol_60d",
    "downside_vol_20d", "upside_vol_20d",
    "distance_from_high_20d", "distance_from_high_60d", "distance_from_low_20d", "distance_from_low_60d",
    "max_drawdown_20d", "max_drawdown_60d",
    "avg_volume_20d", "avg_volume_60d", "volume_ratio_5d_20d", "volume_ratio_20d_60d",
    "avg_dollar_volume_20d",
)
HGB_CONFIG: dict[str, Any] = {
    "loss": "squared_error",
    "learning_rate": 0.05,
    "max_iter": 200,
    "max_leaf_nodes": 15,
    "max_depth": 3,
    "min_samples_leaf": 200,
    "l2_regularization": 1.0,
    "early_stopping": False,
    "random_state": 20260816,
}
PLANNED_FOLDS = (
    {"fold_id": "OOF_2021", "train_end": "2020-12-31", "test_start": "2021-01-01", "test_end": "2021-12-31"},
    {"fold_id": "OOF_2022", "train_end": "2021-12-31", "test_start": "2022-01-01", "test_end": "2022-12-31"},
    {"fold_id": "OOF_2023", "train_end": "2022-12-31", "test_start": "2023-01-01", "test_end": "2023-12-31"},
    {"fold_id": "OOF_2024", "train_end": "2023-12-31", "test_start": "2024-01-01", "test_end": "2024-12-31"},
    {"fold_id": "OOF_2025", "train_end": "2024-12-31", "test_start": "2025-01-01", "test_end": "2025-12-31"},
)
SUMMARY_FIELDS = (
    "ABCDE_A2_R0_STATUS", "ABCDE_A2_R1_STATUS", "ABCDE_A2_R1_CLASSIFICATION", "ABCDE_A2_R1_DECISION",
    "A1_CONTROL_IDENTITY_STATUS", "PIT_AUDIT_STATUS", "AUTHORITATIVE_PRICE_SOURCE", "HISTORICAL_DATA_START",
    "HISTORICAL_DATA_END", "TRAINING_CUTOFF", "TRAINING_2026_ROW_COUNT", "MODEL_FIT_COUNT", "MODEL_FAMILY",
    "A2_HGB_CONFIG_FROZEN", "PRIMARY_TARGET", "SECONDARY_TARGET", "TARGET_BENCHMARK", "OOF_FOLD_COUNT",
    "A1_PRIMARY_DAILY_SPEARMAN_MEAN", "A2_PRIMARY_DAILY_SPEARMAN_MEAN", "DELTA_PRIMARY_DAILY_SPEARMAN",
    "A1_TOP20_PRIMARY_MEAN", "A2_TOP20_PRIMARY_MEAN", "DELTA_TOP20_PRIMARY_MEAN", "A2_BETTER_FOLD_COUNT",
    "A2_WORSE_FOLD_COUNT", "A1_A2_RANK_CORRELATION", "DISAGREEMENT_STUDY_STATUS", "TAIL_ROBUSTNESS_STATUS",
    "DAILY_CHAIN_CHANGED", "A1_CHANGED", "B_CHANGED", "C_CHANGED", "D_CHANGED", "E_CHANGED",
    "FAST_INTEGRATION_COUNT", "BROKER_ACTION_COUNT", "MOOMOO_API_REQUEST_COUNT", "ANTI_BLOAT_STATUS",
    "RESULTS_ROOT", "SUMMARY_PATH", "OOF_PREDICTION_PATH", "FAILURE_REASON",
)


class ContractStop(RuntimeError):
    """A fail-closed contract violation that forbids A2-R1 model fitting."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def schema_sha256(schema: Any) -> str:
    return hashlib.sha256(str(schema).encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (Path, pd.Timestamp)):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    raise TypeError(type(value).__name__)


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False, default=_json_default) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False, dir=path.parent) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def import_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ContractStop(f"IMPORT_SPEC_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_a1_identity() -> dict[str, Any]:
    required = (A1_FREEZE, A1_PRODUCER, A1_GUARD)
    if any(not path.is_file() for path in required):
        return {"status": "FAIL", "reason": "A1_IDENTITY_ARTIFACT_MISSING", "paths": [str(path) for path in required]}
    freeze = json.loads(A1_FREEZE.read_text(encoding="utf-8"))
    guard = import_path("abcde_compact_freeze_guard_a2", A1_GUARD)
    contract = guard.extract_contract(A1_PRODUCER)
    source_hash = guard.file_sha256(A1_PRODUCER)
    contract_hash = guard.contract_sha256(contract)
    passed = (
        freeze.get("source_script") == "scripts/v21/v21_233_moomoo_only_abcde_rerun.py"
        and source_hash == freeze.get("source_script_sha256")
        and contract_hash == freeze.get("abcde_contract_sha256")
        and "A1_CONTROL" in contract.get("strategy_weights", {})
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "producer_module_path": str(A1_PRODUCER),
        "producer_function": "build_rankings",
        "feature_function": "features_by_ticker",
        "source_script_sha256": source_hash,
        "expected_source_script_sha256": freeze.get("source_script_sha256"),
        "contract_sha256": contract_hash,
        "expected_contract_sha256": freeze.get("abcde_contract_sha256"),
        "factor_inputs": contract.get("factor_names"),
        "a1_weights": contract.get("strategy_weights", {}).get("A1_CONTROL"),
        "raw_score_computation": "fixed weighted sum of daily cross-sectional percentile ranks; volatility percentile reversed",
        "rank_logic": "sort raw score descending; rank 1 is highest",
        "universe_definition": "V21.231 expected/current active ABCDE universe minus effective exclusions; same-price-date rows only",
        "signal_timestamp_contract": "end of signal_date after same-day Moomoo qfq daily close is available",
        "canonical_dependencies": [str(PRICE_ROOT), str(UNIVERSE_TABLE)],
        "semantic_invariants": contract.get("semantic_invariants"),
        "freeze_id": freeze.get("freeze_id"),
    }


def audit_price_contract() -> dict[str, Any]:
    paths = [PRICE_ROOT / f"year={year}/prices.parquet" for year in range(2020, 2026)]
    if any(not path.is_file() for path in paths):
        return {"status": "FAIL", "reason": "REQUIRED_MOOMOO_QFQ_YEAR_PART_MISSING", "paths": [str(path) for path in paths]}
    frames: list[pd.DataFrame] = []
    schemas: list[Any] = []
    hashes: dict[str, str] = {}
    columns = ["ticker", "trade_date", "open", "high", "low", "close", "volume", "turnover", "autype", "source"]
    for path in paths:
        parquet = pq.ParquetFile(path)
        schemas.append(parquet.schema_arrow)
        hashes[str(path)] = sha256_file(path)
        frames.append(pd.read_parquet(path, columns=columns))
    frame = pd.concat(frames, ignore_index=True)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    required_values_ok = (
        frame["source"].eq("MOOMOO_OPEND").all()
        and frame["autype"].eq("qfq").all()
        and frame[["ticker", "trade_date", "open", "high", "low", "close", "volume"]].notna().all().all()
        and (frame[["open", "high", "low", "close"]] > 0).all().all()
        and not frame.duplicated(["ticker", "trade_date"]).any()
    )
    qqq = frame.loc[frame["ticker"].eq(TARGET_BENCHMARK)]
    qqq_ok = len(qqq) > 0 and qqq.trade_date.min() == frame.trade_date.min() and qqq.trade_date.max() == frame.trade_date.max()
    passed = bool(required_values_ok and qqq_ok and frame.trade_date.max() < TRAINING_BOUNDARY)
    return {
        "status": "PASS" if passed else "FAIL",
        "authoritative_price_source": "LOCAL_MOOMOO_CACHE_QFQ_FROM_MOOMOO_OPEND",
        "price_adjustment_contract": "qfq",
        "corporate_action_safe": bool(frame.autype.eq("qfq").all()),
        "historical_data_start": str(frame.trade_date.min().date()),
        "historical_data_end": str(frame.trade_date.max().date()),
        "row_count": int(len(frame)),
        "ticker_count": int(frame.ticker.nunique()),
        "duplicate_ticker_date_count": int(frame.duplicated(["ticker", "trade_date"]).sum()),
        "qqq_row_count": int(len(qqq)),
        "qqq_start": None if qqq.empty else str(qqq.trade_date.min().date()),
        "qqq_end": None if qqq.empty else str(qqq.trade_date.max().date()),
        "schema_sha256": schema_sha256(schemas[0]),
        "schema_consistent": all(str(schema) == str(schemas[0]) for schema in schemas),
        "source_file_sha256": hashes,
        "moomoo_api_request_count": 0,
    }


def audit_pit_universe() -> dict[str, Any]:
    if not UNIVERSE_MANIFEST.is_file() or not UNIVERSE_TABLE.is_file():
        return {"status": "FAIL_CLOSED", "reason": "ABCDE_UNIVERSE_MANIFEST_MISSING"}
    active = json.loads(UNIVERSE_MANIFEST.read_text(encoding="utf-8"))
    table = pd.read_csv(UNIVERSE_TABLE, nrows=10)
    columns = list(table.columns)
    has_dated_membership = (
        {"ticker", "effective_from", "effective_to"}.issubset(columns)
        or {"ticker", "signal_date", "in_universe"}.issubset(columns)
    )
    proxy = json.loads(PROXY_MANIFEST.read_text(encoding="utf-8")) if PROXY_MANIFEST.is_file() else {}
    rebuild = DATA_ROOT / "MOOMOO_2020_PRESENT_AUTHORITATIVE_HISTORY_REBUILD_R1/pre2026"
    rebuild_files = [path for path in rebuild.rglob("*") if path.is_file()] if rebuild.is_dir() else []
    passed = bool(has_dated_membership and rebuild_files)
    reason = None if passed else "NO_PIT_SAFE_2020_2025_ABCDE_UNIVERSE_MEMBERSHIP_CONTRACT"
    return {
        "status": "PASS" if passed else "FAIL_CLOSED",
        "reason": reason,
        "active_manifest_path": str(UNIVERSE_MANIFEST),
        "active_manifest_effective_date": active.get("effective_date"),
        "active_manifest_columns": columns,
        "dated_membership_columns_present": has_dated_membership,
        "current_fixed_proxy_manifest_path": str(PROXY_MANIFEST),
        "current_fixed_proxy_tier": proxy.get("backtest_tier"),
        "current_fixed_proxy_survivorship_warning": proxy.get("survivorship_warning"),
        "authoritative_pre2026_rebuild_path": str(rebuild),
        "authoritative_pre2026_rebuild_file_count": len(rebuild_files),
        "fail_closed_explanation": "Current-universe backfill is future membership/survivorship information and cannot define historical OOF cohorts.",
    }


def enforce_pre2026(frame: pd.DataFrame, date_column: str = "signal_date") -> pd.DataFrame:
    dates = pd.to_datetime(frame[date_column], errors="raise")
    eligible = frame.loc[dates < TRAINING_BOUNDARY].copy()
    if pd.to_datetime(eligible[date_column]).ge(TRAINING_BOUNDARY).any():
        raise ContractStop("TRAINING_2026_ROW_PRESENT")
    return eligible


def validate_temporal_folds(folds: tuple[dict[str, str], ...] = PLANNED_FOLDS) -> None:
    previous_test_end: pd.Timestamp | None = None
    for fold in folds:
        train_end = pd.Timestamp(fold["train_end"])
        test_start = pd.Timestamp(fold["test_start"])
        test_end = pd.Timestamp(fold["test_end"])
        if not train_end < test_start <= test_end < TRAINING_BOUNDARY:
            raise ContractStop(f"INVALID_TEMPORAL_FOLD:{fold['fold_id']}")
        if previous_test_end is not None and test_start <= previous_test_end:
            raise ContractStop(f"OVERLAPPING_TEMPORAL_FOLD:{fold['fold_id']}")
        previous_test_end = test_end


def validate_information_alignment(frame: pd.DataFrame) -> None:
    feature_time = pd.to_datetime(frame["feature_information_timestamp"], errors="raise")
    signal_time = pd.to_datetime(frame["signal_timestamp"], errors="raise")
    target_start = pd.to_datetime(frame["target_start_timestamp"], errors="raise")
    target_end = pd.to_datetime(frame["target_end_timestamp"], errors="raise")
    if not (feature_time <= signal_time).all():
        raise ContractStop("FEATURE_USES_POST_SIGNAL_INFORMATION")
    if not ((target_start > signal_time) & (target_end >= target_start)).all():
        raise ContractStop("TARGET_NOT_STRICTLY_FORWARD")


def make_hgb() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(**HGB_CONFIG)


def _repo_added_bytes() -> int:
    names = (
        "scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py",
        "scripts/v22/run_abcde_a2_nonlinear_alpha_baseline_r1.py",
        "scripts/v22/test_abcde_a2_nonlinear_alpha_baseline_r1.py",
    )
    return sum((REPO_ROOT / name).stat().st_size for name in names if (REPO_ROOT / name).is_file())


def build_fail_closed_summary(results_root: Path, a1: dict[str, Any], price: dict[str, Any], pit: dict[str, Any]) -> dict[str, Any]:
    summary_path = results_root / "abcde_a2_r0_r1_summary.json"
    failure = str(pit.get("reason") or price.get("reason") or a1.get("reason") or "UNKNOWN_CONTRACT_FAILURE")
    summary: dict[str, Any] = {
        "ABCDE_A2_R0_STATUS": "FAIL_CLOSED",
        "ABCDE_A2_R1_STATUS": "NOT_RUN_FAIL_CLOSED",
        "ABCDE_A2_R1_CLASSIFICATION": "NOT_CLASSIFIED_FAIL_CLOSED",
        "ABCDE_A2_R1_DECISION": "STOP_MODEL_COMPLEXITY_PATH_AND_REASSESS_INFORMATION_SET",
        "A1_CONTROL_IDENTITY_STATUS": a1.get("status", "FAIL"),
        "PIT_AUDIT_STATUS": "FAIL_CLOSED",
        "AUTHORITATIVE_PRICE_SOURCE": price.get("authoritative_price_source", "UNAVAILABLE"),
        "HISTORICAL_DATA_START": price.get("historical_data_start"),
        "HISTORICAL_DATA_END": price.get("historical_data_end"),
        "TRAINING_CUTOFF": TRAINING_CUTOFF,
        "TRAINING_2026_ROW_COUNT": 0,
        "MODEL_FIT_COUNT": 0,
        "MODEL_FAMILY": "HistGradientBoostingRegressor",
        "A2_HGB_CONFIG_FROZEN": True,
        "PRIMARY_TARGET": PRIMARY_TARGET,
        "SECONDARY_TARGET": SECONDARY_TARGET,
        "TARGET_BENCHMARK": TARGET_BENCHMARK,
        "OOF_FOLD_COUNT": 0,
        "A1_PRIMARY_DAILY_SPEARMAN_MEAN": None,
        "A2_PRIMARY_DAILY_SPEARMAN_MEAN": None,
        "DELTA_PRIMARY_DAILY_SPEARMAN": None,
        "A1_TOP20_PRIMARY_MEAN": None,
        "A2_TOP20_PRIMARY_MEAN": None,
        "DELTA_TOP20_PRIMARY_MEAN": None,
        "A2_BETTER_FOLD_COUNT": 0,
        "A2_WORSE_FOLD_COUNT": 0,
        "A1_A2_RANK_CORRELATION": None,
        "DISAGREEMENT_STUDY_STATUS": "NOT_RUN_FAIL_CLOSED",
        "TAIL_ROBUSTNESS_STATUS": "NOT_RUN_FAIL_CLOSED",
        "DAILY_CHAIN_CHANGED": False,
        "A1_CHANGED": False,
        "B_CHANGED": False,
        "C_CHANGED": False,
        "D_CHANGED": False,
        "E_CHANGED": False,
        "FAST_INTEGRATION_COUNT": 0,
        "BROKER_ACTION_COUNT": 0,
        "MOOMOO_API_REQUEST_COUNT": int(price.get("moomoo_api_request_count", 0)),
        "ANTI_BLOAT_STATUS": "PASS",
        "RESULTS_ROOT": str(results_root),
        "SUMMARY_PATH": str(summary_path),
        "OOF_PREDICTION_PATH": "NOT_CREATED_FAIL_CLOSED",
        "FAILURE_REASON": failure,
        "experiment_id": EXPERIMENT_ID,
        "research_only": True,
        "official_adoption_allowed": False,
        "planned_oof_fold_count": len(PLANNED_FOLDS),
        "planned_oof_folds": list(PLANNED_FOLDS),
        "feature_contract": {"architecture": "STOCK_STATE_ONLY", "feature_count": len(FEATURES), "features": list(FEATURES)},
        "target_contract": {
            "horizons": list(TARGET_HORIZONS),
            "primary": "arithmetic mean of benchmark-relative ER_3D, ER_5D, ER_10D, ER_20D",
            "secondary": SECONDARY_TARGET,
            "benchmark": TARGET_BENCHMARK,
        },
        "hgb_config": HGB_CONFIG,
        "a1_identity_audit": a1,
        "price_contract_audit": price,
        "pit_universe_audit": pit,
        "repo_bytes_added": _repo_added_bytes(),
        "external_result_paths": [str(summary_path), str(results_root / "a1_control_identity.json"), str(results_root / "a2_r0_contract_audit.json")],
    }
    missing = set(SUMMARY_FIELDS) - set(summary)
    if missing:
        raise AssertionError(f"summary schema missing: {sorted(missing)}")
    return summary


def run(results_root: Path = DEFAULT_RESULTS_ROOT) -> dict[str, Any]:
    results_root = results_root.resolve()
    if REPO_ROOT == results_root or REPO_ROOT in results_root.parents or results_root in REPO_ROOT.parents:
        raise ContractStop(f"RESULTS_ROOT_MUST_BE_EXTERNAL:{results_root}")
    validate_temporal_folds()
    a1 = audit_a1_identity()
    price = audit_price_contract()
    pit = audit_pit_universe()
    if a1.get("status") != "PASS":
        pit = {**pit, "status": "FAIL_CLOSED", "reason": "A1_CONTROL_IDENTITY_NOT_CONFIRMED"}
    elif price.get("status") != "PASS":
        pit = {**pit, "status": "FAIL_CLOSED", "reason": "AUTHORITATIVE_PRICE_CONTRACT_NOT_CONFIRMED"}
    if pit.get("status") == "PASS":
        raise ContractStop("PIT_UNIVERSE_GATE_PASSED_BUT_A2_R1_EXECUTION_NOT_PREREGISTERED_FOR_THIS_DATASET")
    summary = build_fail_closed_summary(results_root, a1, price, pit)
    write_json_atomic(results_root / "a1_control_identity.json", a1)
    write_json_atomic(results_root / "a2_r0_contract_audit.json", {"price": price, "pit_universe": pit})
    write_json_atomic(results_root / "abcde_a2_r0_r1_summary.json", summary)
    return summary


def print_core(summary: dict[str, Any]) -> None:
    for field in SUMMARY_FIELDS:
        value = summary[field]
        if value is None:
            value = "NA"
        elif isinstance(value, bool):
            value = str(value).lower()
        print(f"{field}={value}")
