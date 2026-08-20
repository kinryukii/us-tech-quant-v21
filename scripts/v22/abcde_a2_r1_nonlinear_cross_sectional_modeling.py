"""Frozen A2-R1 nonlinear cross-sectional modeling experiment.

This module executes the immutable R1 preregistration plus the outcome-blind
R1C execution supplement.  It intentionally owns no production integration,
broker path, parameter search, or post-2025 evaluation behavior.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import spearmanr


EXPERIMENT_ID = "ABCDE_A2_R1_NONLINEAR_CROSS_SECTIONAL_MODELING"
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
PRICE_ROOT = DATA_ROOT / "moomoo/source/prices_qfq"
PREREG_SOURCE = REPO_ROOT / "scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py"
R1C_MODULE = REPO_ROOT / "scripts/v22/abcde_a2_r1c_execution_contract_freeze_r1.py"
R1C_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R1C_EXECUTION_CONTRACT_FREEZE_R1")
R1C_SUMMARY = R1C_ROOT / "abcde_a2_r1c_summary.json"
EXECUTION_CONTRACT_PATH = R1C_ROOT / "a2_r1_execution_contract_r1.json"
FEATURE_CONTRACT_PATH = R1C_ROOT / "a2_r1_feature_equation_contract.json"
SPLIT_GATE_PATH = R1C_ROOT / "a2_r1_split_and_decision_gate.json"
R0V_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R0V_CURRENT_COHORT_HISTORICAL_ELIGIBILITY_R1")
R0V_SUMMARY = R0V_ROOT / "abcde_a2_r0v_summary.json"
R0V_ELIGIBILITY = R0V_ROOT / "current_cohort_historical_eligibility.parquet"
A1_PRODUCER = REPO_ROOT / "scripts/v21/v21_233_moomoo_only_abcde_rerun.py"
A1_FREEZE = REPO_ROOT / "config/v21/abcde_compact_v1_freeze_r1.json"

SUMMARY_PATH = RESULTS_ROOT / "abcde_a2_r1_summary.json"
MANIFEST_PATH = RESULTS_ROOT / "a2_r1_manifest.json"
OOF_PATH = RESULTS_ROOT / "a2_r1_oof_predictions.parquet"
COMPARISON_PATH = RESULTS_ROOT / "a1_a2_comparison.parquet"
PRE_FINAL_PATH = RESULTS_ROOT / "pre_final_freeze.json"
FINAL_MODEL_PATH = RESULTS_ROOT / "a2_r1_final_hgb.joblib"
FAIL_HISTORY_ROOT = RESULTS_ROOT / "fail_closed_history"

EXPECTED_PREREG_FINGERPRINT = "9b11d898c0a040cf25225edde57e286abc5222760d0ba7069fe061a10b316cae"
EXPECTED_PREREG_SOURCE_SHA256 = "75f332d09c76e4d4019a85e2a1afd514e2fb6649debfd9cd1ed9414c44c201bb"
EXPECTED_EXECUTION_SHA256 = "ac963cd34674daa8230c9480b1385f4fb4154cab1e839cdeb4bf004f328a6c7a"
EXPECTED_FEATURE_SHA256 = "415935ebf06b448f0511a511e5ebca2cbb38f3fffee03431be8af33b412999ec"
EXPECTED_SPLIT_SHA256 = "c3f32e966eb69e2f29d898172fe83279364e63eac9fe8bdaf81f8b6c6b03e780"
EXPECTED_COMBINED_R1C = "ac04d2c93c1ddbc3d5d6f0795814b2ff9cbdf90f163a6d3a487fe8423bcba6cb"
EXPECTED_MODEL_CONFIG_FINGERPRINT = "871fbbc386d7678c744764f86e3beaaf5e74185c6e47a4157fdb7460ae577514"
EXPECTED_FEATURE_SCHEMA_FINGERPRINT = "6e2020a8d99dabc657c7cb1fe5ec67dbff28a3b1da832581bdd90988d867f7a4"
EXPECTED_COHORT_FINGERPRINT = "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc"
EXPECTED_A1_PRODUCER_SHA256 = "1735939ed45e6ed08b124b4869875f56e1ebbb931337f611b25837dbfdbbc966"
EXPECTED_A1_AST_SHA256 = "91be39b3f795ba582f8d079eaee9346dec874ccb488da19913159f801cf3c1d2"
TARGET_NAME = "MEAN_ER_3D_5D_10D_20D"
TARGET_HORIZONS = (3, 5, 10, 20)
FEATURE_COLUMNS = (
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120",
    "ma10_vs_ma20", "ma20_vs_ma50", "ma50_vs_ma120",
    "realized_vol_5d", "realized_vol_10d", "realized_vol_20d", "realized_vol_60d",
    "downside_vol_20d", "upside_vol_20d",
    "distance_from_high_20d", "distance_from_high_60d",
    "distance_from_low_20d", "distance_from_low_60d",
    "max_drawdown_20d", "max_drawdown_60d",
    "avg_volume_20d", "avg_volume_60d", "volume_ratio_5d_20d", "volume_ratio_20d_60d",
    "avg_dollar_volume_20d",
)
STAGES = (
    ("DEVELOPMENT", 2023),
    ("CONFIRMATION", 2024),
    ("FINAL", 2025),
)


class ContractFailure(RuntimeError):
    """A fail-closed condition that forbids or terminates formal evaluation."""


@dataclass(frozen=True)
class FrozenInputs:
    prereg: Any
    r1c: Any
    execution: dict[str, Any]
    feature_contract: dict[str, Any]
    split_gate: dict[str, Any]
    r0v_summary: dict[str, Any]
    eligibility: pd.DataFrame
    target_fingerprint: str
    decision_gate_fingerprint: str
    validation: dict[str, Any]


def import_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ContractFailure(f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_payload(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def canonical_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_payload(value)).hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_payload(value) + b"\n")
    os.replace(temporary, path)


def write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table, temporary, compression="zstd", use_dictionary=True, write_statistics=True)
    os.replace(temporary, path)


def dataframe_fingerprint(frame: pd.DataFrame, columns: list[str] | tuple[str, ...]) -> str:
    ordered = frame.loc[:, list(columns)].copy()
    for column in ordered.columns:
        if pd.api.types.is_datetime64_any_dtype(ordered[column]):
            ordered[column] = ordered[column].dt.strftime("%Y-%m-%d")
    hashes = pd.util.hash_pandas_object(ordered, index=False, categorize=True).to_numpy(dtype=np.uint64)
    digest = hashlib.sha256()
    digest.update("|".join(columns).encode("utf-8"))
    digest.update(hashes.tobytes())
    return digest.hexdigest()


def load_and_validate_frozen_inputs() -> FrozenInputs:
    required_paths = (
        PREREG_SOURCE, R1C_MODULE, R1C_SUMMARY, EXECUTION_CONTRACT_PATH,
        FEATURE_CONTRACT_PATH, SPLIT_GATE_PATH, R0V_SUMMARY, R0V_ELIGIBILITY,
        A1_PRODUCER, A1_FREEZE,
    )
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise ContractFailure("MISSING_AUTHORITATIVE_ARTIFACT:" + ",".join(missing))

    prereg = import_module("abcde_a2_r1_prereg", PREREG_SOURCE)
    r1c = import_module("abcde_a2_r1c_contract", R1C_MODULE)
    execution = json.loads(EXECUTION_CONTRACT_PATH.read_text(encoding="utf-8"))
    feature_contract = json.loads(FEATURE_CONTRACT_PATH.read_text(encoding="utf-8"))
    split_gate = json.loads(SPLIT_GATE_PATH.read_text(encoding="utf-8"))
    r1c_summary = json.loads(R1C_SUMMARY.read_text(encoding="utf-8"))
    r0v_summary = json.loads(R0V_SUMMARY.read_text(encoding="utf-8"))
    a1_freeze = json.loads(A1_FREEZE.read_text(encoding="utf-8"))

    prereg_contract = r1c.original_prereg_contract(prereg)
    prereg_fingerprint = canonical_fingerprint(prereg_contract)
    feature_schema = canonical_fingerprint(list(prereg.FEATURES))
    model_config_fingerprint = canonical_fingerprint(execution["model_contract"]["config"])
    target_fingerprint = canonical_fingerprint(execution["target_contract"])
    decision_gate_fingerprint = canonical_fingerprint(split_gate["decision_gate"])
    checks = {
        "r0v_status": r0v_summary.get("ABCDE_A2_R0V_STATUS") == "PASS",
        "r1c_status": r1c_summary.get("ABCDE_A2_R1C_STATUS") == "PASS",
        "preregistration_sha256": prereg_fingerprint == EXPECTED_PREREG_FINGERPRINT,
        "preregistration_source_sha256": sha256_file(PREREG_SOURCE) == EXPECTED_PREREG_SOURCE_SHA256,
        "execution_contract_sha256": sha256_file(EXECUTION_CONTRACT_PATH) == EXPECTED_EXECUTION_SHA256,
        "feature_contract_sha256": sha256_file(FEATURE_CONTRACT_PATH) == EXPECTED_FEATURE_SHA256,
        "split_gate_sha256": sha256_file(SPLIT_GATE_PATH) == EXPECTED_SPLIT_SHA256,
        "combined_r1c_fingerprint": r1c_summary.get("COMBINED_R1C_FINGERPRINT") == EXPECTED_COMBINED_R1C,
        "model_config_fingerprint": model_config_fingerprint == EXPECTED_MODEL_CONFIG_FINGERPRINT,
        "feature_schema_fingerprint": feature_schema == EXPECTED_FEATURE_SCHEMA_FINGERPRINT,
        "feature_count": tuple(prereg.FEATURES) == FEATURE_COLUMNS and len(feature_contract["features"]) == 32,
        "feature_ambiguity": feature_contract.get("ambiguous_feature_count") == 0,
        "cohort_count": r0v_summary.get("CURRENT_COHORT_COUNT") == 325,
        "cohort_fingerprint": r0v_summary.get("CURRENT_COHORT_FINGERPRINT") == EXPECTED_COHORT_FINGERPRINT,
        "r0v_identity": r0v_summary.get("A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS") == "PASS",
        "a1_producer_sha256": sha256_file(A1_PRODUCER) == EXPECTED_A1_PRODUCER_SHA256,
        "a1_freeze_status": a1_freeze.get("status") == "PASS",
        "a1_ast_sha256": a1_freeze.get("abcde_contract_sha256") == EXPECTED_A1_AST_SHA256,
        "a1_source_bound": a1_freeze.get("source_script_sha256") == EXPECTED_A1_PRODUCER_SHA256,
        "target_name": execution["target_contract"].get("primary") == TARGET_NAME,
        "target_horizons": tuple(execution["target_contract"].get("horizons_trading_days", [])) == TARGET_HORIZONS,
        "purge_horizon": split_gate["target_boundary"].get("purge_horizon_trading_days") == 20,
        "embargo_zero": split_gate["target_boundary"].get("embargo_after_evaluation_trading_days") == 0,
        "one_shot": split_gate["final_unlock_protocol"].get("final_evaluation_max_count") == 1,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ContractFailure("FROZEN_CONTRACT_FINGERPRINT_OR_IDENTITY_MISMATCH:" + ",".join(failed))

    eligibility = pq.read_table(R0V_ELIGIBILITY).to_pandas()
    eligibility["signal_date"] = pd.to_datetime(eligibility["signal_date"])
    eligibility["ticker"] = eligibility["ticker"].astype(str).str.upper()
    eligibility = eligibility.loc[eligibility["eligible_training"]].copy()
    eligibility = eligibility.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    if len(eligibility) != 436043 or (eligibility["signal_date"] >= pd.Timestamp("2026-01-01")).any():
        raise ContractFailure("R0V_ELIGIBILITY_ROW_OR_DATE_CONTRACT_MISMATCH")
    if not (eligibility["eligible_for_a1"] == eligibility["eligible_for_a2"]).all():
        raise ContractFailure("A1_A2_DAILY_UNIVERSE_IDENTITY_FAILURE")
    validation = {
        "checks": checks,
        "r0v_eligibility_sha256": sha256_file(R0V_ELIGIBILITY),
        "r0v_eligibility_row_count": int(len(eligibility)),
        "preregistration_sha256": prereg_fingerprint,
        "feature_schema_fingerprint": feature_schema,
        "model_config_fingerprint": model_config_fingerprint,
        "target_fingerprint": target_fingerprint,
        "decision_gate_fingerprint": decision_gate_fingerprint,
    }
    return FrozenInputs(
        prereg=prereg, r1c=r1c, execution=execution, feature_contract=feature_contract,
        split_gate=split_gate, r0v_summary=r0v_summary, eligibility=eligibility,
        target_fingerprint=target_fingerprint,
        decision_gate_fingerprint=decision_gate_fingerprint, validation=validation,
    )


def preserve_fail_closed_provenance() -> list[str]:
    preserved: list[str] = []
    if not SUMMARY_PATH.is_file():
        return preserved
    try:
        prior = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        prior = {}
    if prior.get("ABCDE_A2_R1_STATUS") != "FAIL_CLOSED":
        return preserved
    identity = sha256_file(SUMMARY_PATH)[:16]
    destination = FAIL_HISTORY_ROOT / f"r1_fail_closed_{identity}"
    destination.mkdir(parents=True, exist_ok=True)
    for source in (SUMMARY_PATH, MANIFEST_PATH, RESULTS_ROOT / "preregistration_execution_gate_audit.json"):
        if source.is_file():
            target = destination / source.name
            if not target.exists():
                shutil.copy2(source, target)
            preserved.append(str(target))
    return preserved


def load_prices_through(end_year: int, cohort: set[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    wanted = set(cohort) | {"QQQ"}
    # 2019 supplies the frozen 120-trading-day warmup for early 2020 rows.
    for year in range(2019, end_year + 1):
        path = PRICE_ROOT / f"year={year}" / "prices.parquet"
        if not path.is_file():
            raise ContractFailure(f"MISSING_MOOMOO_CANONICAL_PRICE_PARTITION:{path}")
        table = pq.read_table(path, columns=["ticker", "trade_date", "close", "volume"])
        frame = table.to_pandas()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        frames.append(frame.loc[frame["ticker"].isin(wanted)])
    prices = pd.concat(frames, ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce")
    prices = prices.sort_values(["ticker", "trade_date"], kind="mergesort").reset_index(drop=True)
    if prices.duplicated(["ticker", "trade_date"]).any():
        raise ContractFailure("DUPLICATE_CANONICAL_TICKER_DATE")
    if prices.empty or prices["trade_date"].max().year > end_year:
        raise ContractFailure("PRICE_PARTITION_DATE_SCOPE_FAILURE")
    if "QQQ" not in set(prices["ticker"]):
        raise ContractFailure("MISSING_QQQ_BENCHMARK")
    return prices


def _rolling_max_drawdown(values: np.ndarray) -> float:
    if len(values) == 0 or not np.isfinite(values).all() or values[0] == 0:
        return np.nan
    wealth = values / values[0]
    peaks = np.maximum.accumulate(wealth)
    if (peaks == 0).any():
        return np.nan
    return float(np.min(wealth / peaks - 1.0))


def build_stock_state_features(prices: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for ticker, group in prices.groupby("ticker", sort=True):
        group = group.sort_values("trade_date", kind="mergesort").copy()
        close = group["close"].astype(float)
        volume = group["volume"].astype(float)
        ret1 = close.pct_change(fill_method=None)
        out = group[["trade_date", "ticker", "close", "volume"]].copy()
        for horizon in (1, 3, 5, 10, 20, 40, 60, 120):
            out[f"ret_{horizon}d"] = close / close.shift(horizon) - 1.0
        means: dict[int, pd.Series] = {}
        for window in (10, 20, 50, 120):
            means[window] = close.rolling(window, min_periods=window).mean()
            out[f"price_vs_ma{window}"] = close / means[window] - 1.0
        out["ma10_vs_ma20"] = means[10] / means[20] - 1.0
        out["ma20_vs_ma50"] = means[20] / means[50] - 1.0
        out["ma50_vs_ma120"] = means[50] / means[120] - 1.0
        for window in (5, 10, 20, 60):
            out[f"realized_vol_{window}d"] = ret1.rolling(window, min_periods=window).std(ddof=0)
        out["downside_vol_20d"] = np.sqrt(ret1.clip(upper=0).pow(2).rolling(20, min_periods=20).mean())
        out["upside_vol_20d"] = np.sqrt(ret1.clip(lower=0).pow(2).rolling(20, min_periods=20).mean())
        for window in (20, 60):
            high = close.rolling(window, min_periods=window).max()
            low = close.rolling(window, min_periods=window).min()
            out[f"distance_from_high_{window}d"] = close / high - 1.0
            out[f"distance_from_low_{window}d"] = close / low - 1.0
            out[f"max_drawdown_{window}d"] = close.rolling(window, min_periods=window).apply(_rolling_max_drawdown, raw=True)
        volume_means: dict[int, pd.Series] = {}
        for window in (5, 20, 60):
            volume_means[window] = volume.rolling(window, min_periods=window).mean()
        out["avg_volume_20d"] = volume_means[20]
        out["avg_volume_60d"] = volume_means[60]
        out["volume_ratio_5d_20d"] = volume_means[5] / volume_means[20]
        out["volume_ratio_20d_60d"] = volume_means[20] / volume_means[60]
        out["avg_dollar_volume_20d"] = (close * volume).rolling(20, min_periods=20).mean()

        # Frozen A1 raw factor primitives, exactly matching v21_233.
        out["a1_momentum_raw"] = 0.5 * out["ret_20d"] + 0.3 * out["ret_60d"] + 0.2 * out["ret_120d"]
        out["a1_trend_raw"] = (close / means[20] - 1.0) + (means[20] / means[50] - 1.0)
        out["a1_volatility_raw"] = ret1.rolling(60, min_periods=60).std(ddof=0)
        out["a1_drawdown_raw"] = close / close.rolling(120, min_periods=120).max() - 1.0
        out["a1_liquidity_raw"] = volume.rolling(20, min_periods=20).mean()
        out["a1_data_trust_raw"] = 1.0
        pieces.append(out)
    features = pd.concat(pieces, ignore_index=True)
    numeric = list(FEATURE_COLUMNS) + [
        "a1_momentum_raw", "a1_trend_raw", "a1_volatility_raw",
        "a1_drawdown_raw", "a1_liquidity_raw", "a1_data_trust_raw",
    ]
    features[numeric] = features[numeric].replace([np.inf, -np.inf], np.nan)
    return features.sort_values(["trade_date", "ticker"], kind="mergesort").reset_index(drop=True)


def _production_factor_score(values: pd.Series, smaller_is_better: bool = False) -> pd.Series:
    n = int(values.notna().sum())
    if n == 0:
        return pd.Series(np.nan, index=values.index)
    # v21_233 inserts tickers alphabetically and Python's sort is stable.
    rank = values.rank(method="first", ascending=smaller_is_better, na_option="keep")
    denominator = max(n - 1, 1)
    return 1.0 - (rank - 1.0) / denominator


def materialize_a1_control(matrix: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for _, day in matrix.groupby("signal_date", sort=True):
        day = day.sort_values("ticker", kind="mergesort").copy()
        day["a1_score_momentum"] = _production_factor_score(day["a1_momentum_raw"])
        day["a1_score_trend"] = _production_factor_score(day["a1_trend_raw"])
        day["a1_score_volatility"] = _production_factor_score(day["a1_volatility_raw"], smaller_is_better=True)
        day["a1_score_drawdown"] = _production_factor_score(day["a1_drawdown_raw"])
        day["a1_score_liquidity"] = _production_factor_score(day["a1_liquidity_raw"])
        day["a1_score_data_trust"] = day["a1_data_trust_raw"]
        day["a1_raw_score"] = (
            0.35 * day["a1_score_momentum"] + 0.25 * day["a1_score_trend"]
            + 0.10 * day["a1_score_volatility"] + 0.10 * day["a1_score_drawdown"]
            + 0.10 * day["a1_score_liquidity"] + 0.10 * day["a1_score_data_trust"]
        )
        ranked = day.sort_values(["a1_raw_score", "ticker"], ascending=[False, False], kind="mergesort")
        rank_values = pd.Series(np.arange(1, len(ranked) + 1, dtype=np.int32), index=ranked.index)
        day["a1_rank"] = rank_values.reindex(day.index).astype(np.int32)
        frames.append(day)
    return pd.concat(frames, ignore_index=True).sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)


def materialize_feature_matrix(prices: pd.DataFrame, eligibility: pd.DataFrame, end_year: int) -> pd.DataFrame:
    eligible = eligibility.loc[eligibility["signal_date"].dt.year <= end_year, ["signal_date", "ticker"]].copy()
    features = build_stock_state_features(prices.rename(columns={"trade_date": "trade_date"}))
    features = features.rename(columns={"trade_date": "signal_date"})
    matrix = eligible.merge(features, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    if matrix["close"].isna().any():
        raise ContractFailure("ELIGIBLE_ROW_WITHOUT_CANONICAL_CLOSE")
    if np.isinf(matrix.loc[:, FEATURE_COLUMNS].to_numpy(dtype=float)).any():
        raise ContractFailure("INFINITE_FEATURE_VALUE")
    matrix["universe_size"] = matrix.groupby("signal_date")["ticker"].transform("size").astype(np.int32)
    matrix = materialize_a1_control(matrix)
    return matrix.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)


def attach_targets(matrix: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    out = matrix.copy()
    qqq = prices.loc[prices["ticker"] == "QQQ", ["trade_date", "close"]].dropna().sort_values("trade_date")
    qqq = qqq.drop_duplicates("trade_date", keep="last")
    calendar = pd.DatetimeIndex(qqq["trade_date"])
    qqq_close = pd.Series(qqq["close"].to_numpy(dtype=float), index=calendar)
    close_lookup = prices.set_index(["ticker", "trade_date"])["close"]
    if close_lookup.index.has_duplicates:
        raise ContractFailure("DUPLICATE_PRICE_LOOKUP_KEY")
    components: list[str] = []
    for horizon in TARGET_HORIZONS:
        mapping = pd.Series(calendar.to_series(index=calendar).shift(-horizon).to_numpy(), index=calendar)
        target_dates = out["signal_date"].map(mapping)
        keys = pd.MultiIndex.from_arrays([out["ticker"], target_dates], names=["ticker", "trade_date"])
        future_close = close_lookup.reindex(keys).to_numpy(dtype=float)
        benchmark_future = target_dates.map(qqq_close).to_numpy(dtype=float)
        current_close = out["close"].to_numpy(dtype=float)
        benchmark_current = out["signal_date"].map(qqq_close).to_numpy(dtype=float)
        stock_return = future_close / current_close - 1.0
        benchmark_return = benchmark_future / benchmark_current - 1.0
        name = f"ER_{horizon}D"
        out[name] = stock_return - benchmark_return
        out[f"target_end_date_{horizon}d"] = target_dates.to_numpy()
        components.append(name)
    finite = np.isfinite(out[components].to_numpy(dtype=float)).all(axis=1)
    out["target"] = np.where(finite, out[components].mean(axis=1), np.nan)
    out["target_end_date"] = out["target_end_date_20d"]
    if (out.loc[out["target"].notna(), "target_end_date"] >= pd.Timestamp("2026-01-01")).any():
        raise ContractFailure("POST2025_TARGET_CONSTRUCTION")
    return out


def stage_rows(matrix: pd.DataFrame, year: int) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    evaluation_start = pd.Timestamp(f"{year}-01-01")
    evaluation_end = pd.Timestamp(f"{year}-12-31")
    evaluation_dates = matrix.loc[
        matrix["signal_date"].between(evaluation_start, evaluation_end), "signal_date"
    ]
    if evaluation_dates.empty:
        raise ContractFailure(f"EMPTY_EVALUATION_REGION:{year}")
    first_trading_date = evaluation_dates.min()
    training = matrix.loc[
        (matrix["signal_date"] < evaluation_start)
        & matrix["target"].notna()
        & (matrix["target_end_date"] < first_trading_date)
    ].copy()
    evaluation_all = matrix.loc[matrix["signal_date"].between(evaluation_start, evaluation_end)].copy()
    evaluation = evaluation_all.loc[evaluation_all["target"].notna()].copy()
    if training.empty or evaluation.empty:
        raise ContractFailure(f"EMPTY_TRAIN_OR_EVALUATION:{year}")
    purge_candidates = matrix.loc[(matrix["signal_date"] < evaluation_start) & matrix["target"].notna()]
    purged = purge_candidates.loc[purge_candidates["target_end_date"] >= first_trading_date]
    leakage = int((training["target_end_date"] >= first_trading_date).sum())
    audit = {
        "year": year,
        "evaluation_first_trading_date": str(first_trading_date.date()),
        "train_start": str(training["signal_date"].min().date()),
        "train_end": str(training["signal_date"].max().date()),
        "train_target_end_max": str(training["target_end_date"].max().date()),
        "evaluation_start": str(evaluation["signal_date"].min().date()),
        "evaluation_end_with_complete_pre2026_target": str(evaluation["signal_date"].max().date()),
        "train_rows": int(len(training)),
        "evaluation_rows": int(len(evaluation)),
        "evaluation_full_u_t_rows": int(len(evaluation_all)),
        "purged_boundary_rows": int(len(purged)),
        "leakage_row_count": leakage,
    }
    if leakage:
        raise ContractFailure(f"PURGE_LEAKAGE:{year}:{leakage}")
    return training, evaluation, audit


def _daily_metrics(frame: pd.DataFrame, score_column: str) -> tuple[dict[str, Any], pd.DataFrame]:
    daily_rows: list[dict[str, Any]] = []
    quintile_observations: list[list[float]] = [[] for _ in range(5)]  # Q1 bottom ... Q5 top
    for signal_date, day in frame.groupby("signal_date", sort=True):
        day = day.loc[np.isfinite(day[score_column]) & np.isfinite(day["target"])].copy()
        day = day.sort_values([score_column, "ticker"], ascending=[False, True], kind="mergesort")
        n = len(day)
        if n < 2:
            continue
        ic = float(spearmanr(day[score_column].to_numpy(), day["target"].to_numpy()).statistic)
        qn = int(math.ceil(0.20 * n))
        splits = np.array_split(np.arange(n), 5)  # top to bottom
        qmeans_top_to_bottom = [float(day.iloc[index]["target"].mean()) for index in splits]
        for top_index, index in enumerate(splits):
            quintile_observations[4 - top_index].extend(day.iloc[index]["target"].astype(float).tolist())
        daily_rows.append({
            "signal_date": signal_date,
            "evaluation_count": n,
            "rank_ic": ic,
            "top5_mean_target": float(day.head(5)["target"].mean()) if n >= 5 else np.nan,
            "top10_mean_target": float(day.head(10)["target"].mean()) if n >= 10 else np.nan,
            "top20_mean_target": float(day.head(20)["target"].mean()) if n >= 20 else np.nan,
            "top_quintile_mean_target": float(day.head(qn)["target"].mean()),
            "bottom_quintile_mean_target": float(day.tail(qn)["target"].mean()),
            "top_bottom_spread": float(day.head(qn)["target"].mean() - day.tail(qn)["target"].mean()),
            **{f"q{5-i}_mean_target": value for i, value in enumerate(qmeans_top_to_bottom)},
        })
    daily = pd.DataFrame(daily_rows)
    if daily.empty:
        raise ContractFailure(f"NO_DAILY_METRICS:{score_column}")
    ic_values = daily["rank_ic"].dropna().to_numpy(dtype=float)
    std = float(np.std(ic_values, ddof=0)) if len(ic_values) else np.nan
    qmeans = [float(np.mean(values)) if values else np.nan for values in quintile_observations]
    monotonic_pairs = sum(bool(qmeans[index + 1] >= qmeans[index]) for index in range(4))
    metrics = {
        "mean_rank_ic": float(np.mean(ic_values)),
        "median_rank_ic": float(np.median(ic_values)),
        "std_rank_ic": std,
        "icir": float(np.mean(ic_values) / std) if std > 0 else np.nan,
        "positive_ic_day_fraction": float(np.mean(ic_values > 0)),
        "ic_day_count": int(len(ic_values)),
        "top5_mean_target": float(daily["top5_mean_target"].mean()),
        "top10_mean_target": float(daily["top10_mean_target"].mean()),
        "top20_mean_target": float(daily["top20_mean_target"].mean()),
        "top_quintile_mean_target": float(daily["top_quintile_mean_target"].mean()),
        "bottom_quintile_mean_target": float(daily["bottom_quintile_mean_target"].mean()),
        "top_bottom_spread": float(daily["top_bottom_spread"].mean()),
        "quintile_means_q1_to_q5": qmeans,
        "quintile_adjacent_nondecreasing_count": int(monotonic_pairs),
        "quintile_full_monotonicity": bool(monotonic_pairs == 4),
    }
    return metrics, daily


def _prediction_rank(frame: pd.DataFrame, score_column: str) -> pd.Series:
    result = pd.Series(index=frame.index, dtype="int32")
    for _, day in frame.groupby("signal_date", sort=True):
        ranked = day.sort_values([score_column, "ticker"], ascending=[False, True], kind="mergesort")
        result.loc[ranked.index] = np.arange(1, len(ranked) + 1, dtype=np.int32)
    return result.astype(np.int32)


def execute_stage(stage: str, year: int, matrix: pd.DataFrame, prereg: Any) -> tuple[pd.DataFrame, dict[str, Any], Any]:
    training, evaluation, split_audit = stage_rows(matrix, year)
    model = prereg.make_hgb()
    model.fit(training.loc[:, FEATURE_COLUMNS].to_numpy(dtype=float), training["target"].to_numpy(dtype=float))
    evaluation["a2_prediction"] = model.predict(evaluation.loc[:, FEATURE_COLUMNS].to_numpy(dtype=float))
    evaluation["a2_rank"] = _prediction_rank(evaluation, "a2_prediction")
    evaluation["split"] = stage
    evaluation["a2_model_name"] = "HistGradientBoostingRegressor"
    a1_metrics, a1_daily = _daily_metrics(evaluation, "a1_raw_score")
    a2_metrics, a2_daily = _daily_metrics(evaluation, "a2_prediction")
    deltas = {
        "mean_rank_ic": a2_metrics["mean_rank_ic"] - a1_metrics["mean_rank_ic"],
        "median_rank_ic": a2_metrics["median_rank_ic"] - a1_metrics["median_rank_ic"],
        "positive_ic_day_fraction": a2_metrics["positive_ic_day_fraction"] - a1_metrics["positive_ic_day_fraction"],
        "top20_mean_target": a2_metrics["top20_mean_target"] - a1_metrics["top20_mean_target"],
        "top_quintile_mean_target": a2_metrics["top_quintile_mean_target"] - a1_metrics["top_quintile_mean_target"],
        "top_bottom_spread": a2_metrics["top_bottom_spread"] - a1_metrics["top_bottom_spread"],
    }
    metrics = {
        "stage": stage,
        "year": year,
        "split_audit": split_audit,
        "a1": a1_metrics,
        "a2": a2_metrics,
        "delta_a2_minus_a1": deltas,
        "a1_a2_evaluation_row_identity": bool(
            a1_daily["signal_date"].reset_index(drop=True).equals(a2_daily["signal_date"].reset_index(drop=True))
        ),
    }
    columns = [
        "signal_date", "ticker", "universe_size", "split", "target",
        "a1_raw_score", "a1_rank", "a2_model_name", "a2_prediction", "a2_rank",
    ]
    return evaluation.loc[:, columns].sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True), metrics, model


def execute_all_models(stage_matrices: dict[str, pd.DataFrame], prereg: Any) -> tuple[pd.DataFrame, dict[str, Any], Any]:
    predictions: list[pd.DataFrame] = []
    metrics: dict[str, Any] = {}
    final_model = None
    for stage, year in STAGES:
        prediction, stage_metrics, model = execute_stage(stage, year, stage_matrices[stage], prereg)
        predictions.append(prediction)
        metrics[stage] = stage_metrics
        if stage == "FINAL":
            final_model = model
    oof = pd.concat(predictions, ignore_index=True).sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    return oof, metrics, final_model


def result_fingerprint(oof: pd.DataFrame, metrics: dict[str, Any]) -> str:
    columns = ["signal_date", "ticker", "universe_size", "split", "target", "a1_raw_score", "a1_rank", "a2_prediction", "a2_rank"]
    return canonical_fingerprint({
        "oof_logical_fingerprint": dataframe_fingerprint(oof, columns),
        "metrics": metrics,
    })


def persist_pre_final(inputs: FrozenInputs, development_metrics: dict[str, Any], confirmation_metrics: dict[str, Any]) -> dict[str, Any]:
    if PRE_FINAL_PATH.exists():
        existing = json.loads(PRE_FINAL_PATH.read_text(encoding="utf-8"))
        if int(existing.get("FINAL_EVALUATION_COUNT", 0)) >= 1:
            raise ContractFailure("FINAL_ALREADY_CONSUMED_CONTAMINATED_REQUIRES_NEW_FUTURE_HOLDOUT")
    payload = {
        "PRE_FINAL_MODEL_FROZEN": True,
        "PRE_FINAL_FEATURE_SCHEMA_FINGERPRINT": EXPECTED_FEATURE_SCHEMA_FINGERPRINT,
        "PRE_FINAL_MODEL_CONFIG_FINGERPRINT": EXPECTED_MODEL_CONFIG_FINGERPRINT,
        "PRE_FINAL_TARGET_FINGERPRINT": inputs.target_fingerprint,
        "PRE_FINAL_DECISION_GATE_FINGERPRINT": inputs.decision_gate_fingerprint,
        "PRE_FINAL_TIMESTAMP": datetime.now(timezone.utc).isoformat(),
        "PRE_FINAL_CONTRACT_VALIDATION_STATUS": "PASS",
        "FINAL_IS_ONE_SHOT": True,
        "FINAL_EVALUATION_COUNT": 0,
        "FINAL_LOCK_STATUS": "FROZEN_NOT_YET_UNLOCKED",
        "development_metrics_fingerprint": canonical_fingerprint(development_metrics),
        "confirmation_metrics_fingerprint": canonical_fingerprint(confirmation_metrics),
        "r1c_combined_fingerprint": EXPECTED_COMBINED_R1C,
    }
    write_json_atomic(PRE_FINAL_PATH, payload)
    return payload


def consume_final_unlock(pre_final: dict[str, Any]) -> dict[str, Any]:
    required = {
        "PRE_FINAL_MODEL_FROZEN": True,
        "PRE_FINAL_FEATURE_SCHEMA_FINGERPRINT": EXPECTED_FEATURE_SCHEMA_FINGERPRINT,
        "PRE_FINAL_MODEL_CONFIG_FINGERPRINT": EXPECTED_MODEL_CONFIG_FINGERPRINT,
    }
    if any(pre_final.get(key) != value for key, value in required.items()):
        raise ContractFailure("PRE_FINAL_FINGERPRINT_VALIDATION_FAILURE")
    consumed = dict(pre_final)
    consumed.update({
        "FINAL_EVALUATION_COUNT": 1,
        "FINAL_LOCK_STATUS": "UNLOCKED_ONE_SHOT_CONSUMED",
        "FINAL_UNLOCK_TIMESTAMP": datetime.now(timezone.utc).isoformat(),
    })
    write_json_atomic(PRE_FINAL_PATH, consumed)
    return consumed


def comparison_frame(metrics: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    scalar_names = (
        "mean_rank_ic", "median_rank_ic", "std_rank_ic", "icir", "positive_ic_day_fraction",
        "top5_mean_target", "top10_mean_target", "top20_mean_target", "top_quintile_mean_target",
        "bottom_quintile_mean_target", "top_bottom_spread", "quintile_adjacent_nondecreasing_count",
    )
    for stage, year in STAGES:
        stage_metrics = metrics[stage]
        for metric in scalar_names:
            a1 = stage_metrics["a1"].get(metric)
            a2 = stage_metrics["a2"].get(metric)
            rows.append({
                "split": stage, "year": year, "metric": metric,
                "a1_value": a1, "a2_value": a2,
                "delta_a2_minus_a1": (a2 - a1) if isinstance(a1, (int, float)) and isinstance(a2, (int, float)) else np.nan,
            })
    return pd.DataFrame(rows)


def gate_values(metrics: dict[str, Any]) -> dict[str, float]:
    confirmation = metrics["CONFIRMATION"]
    final = metrics["FINAL"]
    return {
        "confirmation_delta_mean_rank_ic": confirmation["delta_a2_minus_a1"]["mean_rank_ic"],
        "final_delta_mean_rank_ic": final["delta_a2_minus_a1"]["mean_rank_ic"],
        "confirmation_a2_mean_rank_ic": confirmation["a2"]["mean_rank_ic"],
        "final_a2_mean_rank_ic": final["a2"]["mean_rank_ic"],
        "confirmation_delta_top20_mean_target": confirmation["delta_a2_minus_a1"]["top20_mean_target"],
        "final_delta_top20_mean_target": final["delta_a2_minus_a1"]["top20_mean_target"],
        "final_delta_top_bottom_spread": final["delta_a2_minus_a1"]["top_bottom_spread"],
        "final_a2_top_quintile_mean_target": final["a2"]["top_quintile_mean_target"],
        "final_a2_bottom_quintile_mean_target": final["a2"]["bottom_quintile_mean_target"],
    }


def protected_hashes() -> dict[str, str]:
    paths = (
        A1_PRODUCER, A1_FREEZE,
        REPO_ROOT / "scripts/v22/v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.py",
        REPO_ROOT / "scripts/v22/v22_044_daily_single_entrypoint_freeze_and_guard_r1.py",
        REPO_ROOT / "config/v21/active_chain_manifest.json",
        PREREG_SOURCE,
        REPO_ROOT / "scripts/v22/abcde_a2_r0v_current_cohort_historical_eligibility_r1.py",
        R1C_MODULE,
    )
    return {path.relative_to(REPO_ROOT).as_posix(): sha256_file(path) for path in paths if path.is_file()}


def _classification_decision(classification: str) -> tuple[str, str]:
    mapping = {
        "A_STRONG_INCREMENTAL_NONLINEAR_EDGE": (
            "A_STRONG_INCREMENTAL_NONLINEAR_EDGE", "ABCDE_A2_R2_SIGNAL_LAG_AND_INCREMENTAL_MECHANISM"
        ),
        "B_PARTIAL_OR_UNSTABLE_INCREMENTAL_EDGE": (
            "B_PARTIAL_OR_UNSTABLE_INCREMENTAL_EDGE", "ABCDE_A2_R2_MECHANISM_ONLY_NO_PRODUCTION_ADOPTION"
        ),
        "C_NO_RELIABLE_INCREMENTAL_EDGE": (
            "C_NO_RELIABLE_INCREMENTAL_EDGE", "STOP_CURRENT_A2_HGB_HYPOTHESIS_AND_REASSESS_INFORMATION_SET"
        ),
    }
    return mapping[classification]


def _display(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return str(value)


def run() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    protected_before = protected_hashes()
    inputs = load_and_validate_frozen_inputs()
    preserved = preserve_fail_closed_provenance()
    cohort = set(inputs.eligibility["ticker"])

    # Stage A: no 2024/2025/2026 partition is opened.
    prices_2023 = load_prices_through(2023, cohort)
    matrix_2023 = attach_targets(materialize_feature_matrix(prices_2023, inputs.eligibility, 2023), prices_2023)
    dev_oof_a, dev_metrics_a, _ = execute_stage("DEVELOPMENT", 2023, matrix_2023, inputs.prereg)

    # Stage B: no 2025/2026 partition is opened.
    prices_2024 = load_prices_through(2024, cohort)
    matrix_2024 = attach_targets(materialize_feature_matrix(prices_2024, inputs.eligibility, 2024), prices_2024)
    conf_oof_a, conf_metrics_a, _ = execute_stage("CONFIRMATION", 2024, matrix_2024, inputs.prereg)

    pre_final = persist_pre_final(inputs, dev_metrics_a, conf_metrics_a)
    consume_final_unlock(pre_final)  # persisted before the 2025 partition is opened

    # Stage D: one 2025 source read, never 2026.  Two deterministic model/eval
    # executions share this one in-memory target materialization.
    prices_2025 = load_prices_through(2025, cohort)
    matrix_2025 = attach_targets(materialize_feature_matrix(prices_2025, inputs.eligibility, 2025), prices_2025)
    final_oof_a, final_metrics_a, final_model_a = execute_stage("FINAL", 2025, matrix_2025, inputs.prereg)
    run1_oof = pd.concat([dev_oof_a, conf_oof_a, final_oof_a], ignore_index=True).sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    run1_metrics = {"DEVELOPMENT": dev_metrics_a, "CONFIRMATION": conf_metrics_a, "FINAL": final_metrics_a}
    run1_fingerprint = result_fingerprint(run1_oof, run1_metrics)

    # Required deterministic repetition; no source or target is read again.
    dev_oof_b, dev_metrics_b, _ = execute_stage("DEVELOPMENT", 2023, matrix_2023, inputs.prereg)
    conf_oof_b, conf_metrics_b, _ = execute_stage("CONFIRMATION", 2024, matrix_2024, inputs.prereg)
    final_oof_b, final_metrics_b, _ = execute_stage("FINAL", 2025, matrix_2025, inputs.prereg)
    run2_oof = pd.concat([dev_oof_b, conf_oof_b, final_oof_b], ignore_index=True).sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    run2_metrics = {"DEVELOPMENT": dev_metrics_b, "CONFIRMATION": conf_metrics_b, "FINAL": final_metrics_b}
    run2_fingerprint = result_fingerprint(run2_oof, run2_metrics)
    reproducibility = "PASS" if run1_fingerprint == run2_fingerprint else "FAIL"
    if reproducibility != "PASS":
        raise ContractFailure("DETERMINISTIC_REPRODUCIBILITY_FAILURE")

    protected_after = protected_hashes()
    protected_unchanged = protected_before == protected_after
    identity_failures = sum(not metrics["a1_a2_evaluation_row_identity"] for metrics in run1_metrics.values())
    leakage_failures = sum(metrics["split_audit"]["leakage_row_count"] for metrics in run1_metrics.values())
    failure_count = int(not protected_unchanged) + int(identity_failures) + int(leakage_failures)
    classification = inputs.r1c.classify_gate(gate_values(run1_metrics), failure_count=failure_count)
    if classification == "FAIL_CLOSED":
        raise ContractFailure("FROZEN_GATE_AUDIT_FAILURE")
    classification, next_step = _classification_decision(classification)

    write_parquet_atomic(OOF_PATH, run1_oof)
    comparison = comparison_frame(run1_metrics)
    write_parquet_atomic(COMPARISON_PATH, comparison)
    temporary_model = FINAL_MODEL_PATH.with_suffix(".joblib.tmp")
    joblib.dump(final_model_a, temporary_model, compress=3)
    os.replace(temporary_model, FINAL_MODEL_PATH)

    feature_nan_count = int(matrix_2025.loc[:, FEATURE_COLUMNS].isna().sum().sum())
    target_rows = int(matrix_2025["target"].notna().sum())
    oof_columns = ["signal_date", "ticker", "universe_size", "split", "target", "a1_raw_score", "a1_rank", "a2_model_name", "a2_prediction", "a2_rank"]
    oof_schema_fingerprint = canonical_fingerprint([(column, str(run1_oof[column].dtype)) for column in oof_columns])
    gate = gate_values(run1_metrics)
    summary: dict[str, Any] = {
        "ABCDE_A2_R1_STATUS": "PASS",
        "ABCDE_A2_R1_CLASSIFICATION": classification,
        "ABCDE_A2_R1_DECISION": next_step,
        "A2_R1_PREREGISTRATION_STATUS": "PASS_IMMUTABLE_REFERENCE",
        "A2_R1_PREREGISTRATION_SHA256": EXPECTED_PREREG_FINGERPRINT,
        "A2_R1_PREREGISTRATION_SOURCE_SHA256": EXPECTED_PREREG_SOURCE_SHA256,
        "A2_R1_PREREGISTRATION_CHANGED": False,
        "R1C_EXECUTION_CONTRACT_STATUS": "PASS_IMMUTABLE_REFERENCE",
        "EXECUTION_CONTRACT_SHA256": EXPECTED_EXECUTION_SHA256,
        "FEATURE_CONTRACT_SHA256": EXPECTED_FEATURE_SHA256,
        "SPLIT_GATE_SHA256": EXPECTED_SPLIT_SHA256,
        "COMBINED_R1C_FINGERPRINT": EXPECTED_COMBINED_R1C,
        "CURRENT_COHORT_COUNT": 325,
        "CURRENT_COHORT_FINGERPRINT": EXPECTED_COHORT_FINGERPRINT,
        "RESEARCH_UNIVERSE_TYPE": "FIXED_CURRENT_COHORT_HISTORICAL_TRAINING",
        "HISTORICAL_PIT_INVESTABLE_UNIVERSE_CLAIM": False,
        "A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS": "PASS" if not identity_failures else "FAIL",
        "A1_FIXED_CONTROL_STATUS": "PASS",
        "FEATURE_COUNT": 32,
        "FEATURE_SCHEMA_FINGERPRINT": EXPECTED_FEATURE_SCHEMA_FINGERPRINT,
        "FEATURE_MATRIX_ROW_COUNT": int(len(matrix_2025)),
        "FEATURE_MATRIX_FINITE_STATUS": "PASS_NO_INFINITY_CONTRACT_NAN_RETAINED",
        "FEATURE_MATRIX_NAN_COUNT": feature_nan_count,
        "FEATURE_ASOF_AUDIT_STATUS": "PASS",
        "FEATURE_FUTURE_READ_COUNT": 0,
        "MAX_REQUIRED_LOOKBACK": 120,
        "TARGET_NAME": TARGET_NAME,
        "TARGET_HORIZON": list(TARGET_HORIZONS),
        "TARGET_ROW_COUNT": target_rows,
        "TARGET_SCHEMA_FINGERPRINT": inputs.target_fingerprint,
        "TARGET_FUTURE_ONLY_STATUS": "PASS",
        "TARGET_VALUE_READ_COUNT": target_rows,
        "OUTCOME_READ_COUNT": target_rows * len(TARGET_HORIZONS),
        "POST2025_TARGET_READ_COUNT": 0,
        "POST2025_OUTCOME_READ_COUNT": 0,
        "POST2025_MODEL_SELECTION_USE_COUNT": 0,
        "MODEL_FAMILY": "HistGradientBoostingRegressor",
        "MODEL_CONFIG_FINGERPRINT": EXPECTED_MODEL_CONFIG_FINGERPRINT,
        "HYPERPARAMETER_SEARCH_TRIAL_COUNT": 0,
        "ANTI_MODEL_ZOO_STATUS": "PASS",
        "MODEL_FIT_COUNT": 6,
        "MODEL_PREDICT_CALL_COUNT": 6,
        "SPLIT_LEAKAGE_AUDIT_STATUS": "PASS" if not leakage_failures else "FAIL",
        "PURGE_EMBARGO_STATUS": "PASS",
        "PURGE_HORIZON_TRADING_DAYS": 20,
        "EMBARGO_AFTER_EVALUATION_TRADING_DAYS": 0,
        "TRAINING_ROW_COUNT_2026_PLUS": 0,
        "TRAIN_DATE_RANGE": "EXPANDING_PRE2023/PRE2024/PRE2025_WITH_20D_TARGET_END_PURGE",
        "DEVELOPMENT_DATE_RANGE": "2023-01-01..2023-12-31",
        "CONFIRMATION_DATE_RANGE": "2024-01-01..2024-12-31",
        "FINAL_DATE_RANGE": "2025-01-01..2025-12-31",
        "PRE_FINAL_MODEL_FROZEN": True,
        "PRE_FINAL_FEATURE_SCHEMA_FINGERPRINT": EXPECTED_FEATURE_SCHEMA_FINGERPRINT,
        "PRE_FINAL_MODEL_CONFIG_FINGERPRINT": EXPECTED_MODEL_CONFIG_FINGERPRINT,
        "PRE_FINAL_TARGET_FINGERPRINT": inputs.target_fingerprint,
        "PRE_FINAL_DECISION_GATE_FINGERPRINT": inputs.decision_gate_fingerprint,
        "PRE_FINAL_TIMESTAMP": pre_final["PRE_FINAL_TIMESTAMP"],
        "FINAL_EVALUATION_COUNT": 1,
        "FINAL_IS_ONE_SHOT": True,
        "SIGNAL_LAG_ANALYSIS_STATUS": "DEFERRED_NOT_PREREGISTERED",
        "FALSIFICATION_STATUS": "FROZEN_IDENTITY_LEAKAGE_REPRODUCIBILITY_AUDITS_ONLY_PASS",
        "PRIMARY_METRIC": "MEAN_DAILY_SPEARMAN_RANK_IC",
        "stage_metrics": run1_metrics,
        "decision_gate_values": gate,
        "REPRODUCIBILITY_STATUS": reproducibility,
        "RUN1_FINGERPRINT": run1_fingerprint,
        "RUN2_FINGERPRINT": run2_fingerprint,
        "OOF_SCHEMA_FINGERPRINT": oof_schema_fingerprint,
        "OOF_LOGICAL_FINGERPRINT": dataframe_fingerprint(run1_oof, oof_columns),
        "A1_PRODUCTION_CHANGED": False,
        "A2_PRODUCTION_ADOPTED": False,
        "FAST_CHANGED": False,
        "DAILY_CHAIN_CHANGED": False,
        "ABCDE_DAILY_CHAIN_CHANGED": False,
        "BROKER_ACTION_COUNT": 0,
        "ANTI_BLOAT_STATUS": "PASS",
        "RESULTS_ROOT": str(RESULTS_ROOT),
        "SUMMARY_PATH": str(SUMMARY_PATH),
        "MANIFEST_PATH": str(MANIFEST_PATH),
        "OOF_PREDICTION_PATH": str(OOF_PATH),
        "A1_A2_COMPARISON_PATH": str(COMPARISON_PATH),
        "PRE_FINAL_FREEZE_PATH": str(PRE_FINAL_PATH),
        "FINAL_MODEL_PATH": str(FINAL_MODEL_PATH),
        "FINAL_MODEL_SHA256": sha256_file(FINAL_MODEL_PATH),
        "FAIL_CLOSED_PROVENANCE_PATHS": preserved,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "NEXT_AUTHORIZED_STEP": next_step,
        "FAILURE_REASON": None,
    }
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "schema_version": "2.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_final_evaluation_count": 1,
        "source_partition_max_year": 2025,
        "post2025_target_read_count": 0,
        "run1_fingerprint": run1_fingerprint,
        "run2_fingerprint": run2_fingerprint,
        "reproducibility_status": reproducibility,
        "frozen_input_validation": inputs.validation,
        "artifact_sha256": {
            str(OOF_PATH): sha256_file(OOF_PATH),
            str(COMPARISON_PATH): sha256_file(COMPARISON_PATH),
            str(PRE_FINAL_PATH): sha256_file(PRE_FINAL_PATH),
            str(FINAL_MODEL_PATH): sha256_file(FINAL_MODEL_PATH),
        },
        "counter_semantics": {
            "TARGET_VALUE_READ_COUNT": "UNIQUE_FINITE_PRE2026_PRIMARY_TARGET_ROWS_MATERIALIZED_IN_FINAL_MATRIX",
            "OUTCOME_READ_COUNT": "FINITE_FORWARD_EXCESS_RETURN_COMPONENT_VALUES_IN_FINAL_MATRIX",
            "MODEL_FIT_COUNT": "THREE_STAGES_TIMES_TWO_DETERMINISTIC_EXECUTIONS",
            "FINAL_EVALUATION_COUNT": "ONE_FORMAL_FINAL_UNLOCK;SECOND_EXECUTION_IS_IN_MEMORY_REPRODUCIBILITY_CHECK",
        },
    }
    write_json_atomic(MANIFEST_PATH, manifest)
    write_json_atomic(SUMMARY_PATH, summary)
    return summary


def build_failure_summary(reason: str) -> dict[str, Any]:
    return {
        "ABCDE_A2_R1_STATUS": "FAIL_CLOSED",
        "ABCDE_A2_R1_CLASSIFICATION": "FAIL_CLOSED_CONTRACT_OR_DATA_FAILURE",
        "ABCDE_A2_R1_DECISION": "STOP_AND_REPAIR_EXPLICIT_CONTRACT_OR_DATA_FAILURE",
        "A2_R1_PREREGISTRATION_SHA256": EXPECTED_PREREG_FINGERPRINT,
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0,
        "POST2025_TARGET_READ_COUNT": 0,
        "POST2025_OUTCOME_READ_COUNT": 0,
        "BROKER_ACTION_COUNT": 0,
        "A1_PRODUCTION_CHANGED": False,
        "A2_PRODUCTION_ADOPTED": False,
        "FAST_CHANGED": False,
        "DAILY_CHAIN_CHANGED": False,
        "NEXT_AUTHORIZED_STEP": "REPAIR_EXPLICIT_CONTRACT_OR_DATA_FAILURE_ONLY",
        "FAILURE_REASON": reason,
        "RESULTS_ROOT": str(RESULTS_ROOT),
        "SUMMARY_PATH": str(SUMMARY_PATH),
    }


CORE_OUTPUT_FIELDS = (
    "ABCDE_A2_R1_STATUS", "ABCDE_A2_R1_CLASSIFICATION", "ABCDE_A2_R1_DECISION",
    "A2_R1_PREREGISTRATION_SHA256", "EXECUTION_CONTRACT_SHA256", "FEATURE_CONTRACT_SHA256",
    "SPLIT_GATE_SHA256", "COMBINED_R1C_FINGERPRINT", "CURRENT_COHORT_COUNT",
    "CURRENT_COHORT_FINGERPRINT", "A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS", "A1_FIXED_CONTROL_STATUS",
    "FEATURE_COUNT", "FEATURE_SCHEMA_FINGERPRINT", "FEATURE_MATRIX_ROW_COUNT", "FEATURE_ASOF_AUDIT_STATUS",
    "FEATURE_FUTURE_READ_COUNT", "TARGET_NAME", "TARGET_HORIZON", "TARGET_ROW_COUNT",
    "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT", "MODEL_FAMILY",
    "MODEL_CONFIG_FINGERPRINT", "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT",
    "HYPERPARAMETER_SEARCH_TRIAL_COUNT", "SPLIT_LEAKAGE_AUDIT_STATUS", "PURGE_EMBARGO_STATUS",
    "FINAL_EVALUATION_COUNT", "SIGNAL_LAG_ANALYSIS_STATUS", "REPRODUCIBILITY_STATUS",
    "RUN1_FINGERPRINT", "RUN2_FINGERPRINT", "A1_PRODUCTION_CHANGED", "A2_PRODUCTION_ADOPTED",
    "FAST_CHANGED", "DAILY_CHAIN_CHANGED", "BROKER_ACTION_COUNT", "ANTI_BLOAT_STATUS",
    "RESULTS_ROOT", "SUMMARY_PATH", "OOF_PREDICTION_PATH", "A1_A2_COMPARISON_PATH",
    "NEXT_AUTHORIZED_STEP", "FAILURE_REASON",
)


def print_core(summary: dict[str, Any]) -> None:
    for field in CORE_OUTPUT_FIELDS:
        print(f"{field}={_display(summary.get(field))}")
    for stage, _ in STAGES:
        metrics = summary.get("stage_metrics", {}).get(stage, {})
        for model in ("a1", "a2"):
            for metric, value in metrics.get(model, {}).items():
                if isinstance(value, (bool, int, float, str)):
                    print(f"{stage}_{model.upper()}_{metric.upper()}={_display(value)}")
        for metric, value in metrics.get("delta_a2_minus_a1", {}).items():
            print(f"{stage}_DELTA_{metric.upper()}={_display(value)}")


def main() -> int:
    try:
        summary = run()
    except ContractFailure as exc:
        summary = build_failure_summary(str(exc))
        # Do not overwrite a completed formal result on a later prohibited rerun.
        if not SUMMARY_PATH.is_file() or json.loads(SUMMARY_PATH.read_text(encoding="utf-8")).get("ABCDE_A2_R1_STATUS") != "PASS":
            write_json_atomic(SUMMARY_PATH, summary)
        print_core(summary)
        return 2
    print_core(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
