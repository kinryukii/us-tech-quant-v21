#!/usr/bin/env python
"""FAST3 R43C frozen regime-information-family incremental OOF test."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import (average_precision_score, brier_score_loss, mean_absolute_error,
                             mean_squared_error, r2_score, roc_auc_score)


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
DATA = Path(r"D:\us-tech-quant-data")
AUTHORITATIVE_ROOT = RESULTS / "frozen/fast3/r43c_regime_information_family_incremental_test_r1"
STAGING_ROOT = RESULTS / "scratch/fast3/.r43c_regime_information_family_incremental_test_r1.staging"

R42R_ROOT = RESULTS / "frozen/fast3/r42r_frozen_confirmation_preregistration_repair_r1"
R42R_PREREG = R42R_ROOT / "FAST3_R42R_CONFIRMATION_PREREGISTRATION.json"
R42R_SHA256 = "2df064f334d6a8bc45d79d8bd4f308ee9b82a33c97129a6ae36ba6aecfc9c3e1"
R43A_ROOT = RESULTS / "frozen/fast3/r43a_independent_economic_target_contract_freeze_r1"
R43A_CONTRACT = R43A_ROOT / "FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json"
R43A_SHA256 = "a5d43651433c6dde50eef791facd02047db2be073a0097acaf31cd1af25d2d6a"
R43B_ROOT = RESULTS / "frozen/fast3/r43b_current_information_set_economic_baseline_r1"
R43B_SUMMARY = R43B_ROOT / "FAST3_R43B_SUMMARY.json"
R43B_PREREG = R43B_ROOT / "FAST3_R43B_PREREGISTRATION.json"
R43B_FEATURE_IDENTITY = R43B_ROOT / "FAST3_R43B_FEATURE_IDENTITY.csv"
R43B_PREDICTIONS = R43B_ROOT / "FAST3_R43B_OOF_PREDICTIONS.parquet"
R43B_FOLD_SCHEDULE = R43B_ROOT / "FAST3_R43B_OOF_FOLD_SCHEDULE.csv"
R43B_ACCEPTANCE = R43B_ROOT / "FAST3_R43B_FUTURE_FAMILY_ACCEPTANCE_CONTRACT.json"
R43B_FEATURES_SHA256 = "19dbd063d9efda297cdcfdd6ce1db266cac210ee0171d5421fe348944853bb83"

R28_SOURCE_MANIFEST = RESULTS / "frozen/fast3/cleanroom_r2_20260808/cleanroom_r2_preholdout_source_manifest.json"
R28_MODELS_ROOT = RESULTS / "frozen/fast3/r28_phase3_20260808T131135Z/models"
R28_PROSPECTIVE_RUNTIME = RESULTS / "runtime/fast3/r28_prospective_dual_shadow_r1"
R28_PROSPECTIVE_SEALED = RESULTS / "frozen/fast3/r28_prospective_dual_shadow_r1"
R36_LEDGER = RESULTS / "scratch/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z/FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet"
VIX_CANONICAL = DATA / "fast3/vix_cboe_daily/canonical/vix_daily.parquet"
VIX_PIT_FEATURES = DATA / "fast3/vix_cboe_daily/features/vix_prior_day_regime_features.parquet"
VIX_INGEST_SUMMARY = RESULTS / "v22/V22.056_FAST3_CBOE_DAILY_VIX_INGEST_AND_PIT_REGIME_R1/v22_056_summary.json"

BASELINE_FEATURES = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m", "realized_vol_60m",
    "relative_volume", "range_position", "symbol_code", "direction_code", "session_code",
    "volume_zscore_60m", "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m",
)
REGIME_FEATURES = (
    "vix_level", "vix_change_1d", "vix_percentile_252d",
    "soxx_realized_vol_60m_percentile_20d",
    "soxx_realized_vol_1d_percentile_60d",
    "soxx_intraday_range_percentile_20d",
    "soxx_volume_regime_percentile_20d",
)
ALL_FEATURES = BASELINE_FEATURES + REGIME_FEATURES
CATEGORICAL_FEATURES = ("symbol_code", "session_code")
BLOCKS = ("OOF_2020", "OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN")
VALIDATION_FOLDS = BLOCKS[1:]
QUINTILES = ("Q1", "Q2", "Q3", "Q4", "Q5")
RETURN_COLUMNS = tuple(f"return_{minute}m_net20" for minute in (5, 10, 15, 30, 60))
HGB_STRUCTURE = {
    "learning_rate": .08, "max_iter": 100, "max_leaf_nodes": 7,
    "min_samples_leaf": 200, "l2_regularization": 1., "random_state": 1729,
    "early_stopping": False,
}
MIN_QUINTILE_SAMPLE = 25
EXPECTED_HASHES = {
    "R43B_SUMMARY": "53447bbd5c970b7740d939b14beb9641f6e46e747f9e60082e8a01abeead81e2",
    "R43B_PREREG": "3bcb1b3e3ad6c37df3fad02339cf1237788a9ab9c876c29eda1dee8f74e1eda3",
    "R43B_FEATURE_IDENTITY": "3721263e9bcfaf9a84363669dcfb10b2fdd8e66b292732f164e93dbaac58b537",
    "R43B_PREDICTIONS": "dc058c5e72f3372811a74f25c28ed6b446daf2311032fbf5bef5ef622eb2dce1",
    "R43B_FOLD_SCHEDULE": "97fcd9995c9c8a7799c3871bebc9175741dab8ee2f259a9f1f7ffaf5a69217f2",
    "R43B_ACCEPTANCE": "2f13af96de6cc0b5a9d598223dc19e481dcab628abfebe6b8bfb1a368d3168e5",
    "R28_SOURCE_MANIFEST": "8ef4126e586350a8c67180e6c375309867d498370ddfffcd93a93eee7fc62610",
    "R36_LEDGER": "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb",
    "VIX_CANONICAL": "bd589dd1d9daa0ca2e7bb2d5f2db1aeedada0641255bb1cde709f38d13576a99",
    "VIX_PIT_FEATURES": "685f975bbae87e65bb3bf9bb339fc341f2035d0af27b2dc0b6cb81e9309c372f",
    "VIX_INGEST_SUMMARY": "7452dfbf181b9c5d868dd1aea87f8e9d248bddea00713d338d47b6b98c581f68",
}
BASELINE_REFERENCE = {
    "UP": {"spearman": -0.048662932206013074, "q5_q1": -0.0008127071790722919,
           "secondary_auroc": 0.4620422535211267},
    "DOWN": {"spearman": -0.06529282988030344, "q5_q1": -0.0006257940729066124,
             "secondary_auroc": 0.46465040288143783},
}


class IdentityStop(RuntimeError):
    pass


class PITContractStop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False) + "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, Path)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False, default=json_default) + "\n", encoding="utf-8")


def tree_hashes(root: Path, allow_missing: bool = False) -> dict[str, str]:
    if not root.exists():
        if allow_missing: return {}
        raise IdentityStop(f"STOP_FROZEN_ROOT_MISSING:{root}")
    return {str(path.relative_to(root)).replace("\\", "/"): sha256(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def isolation_snapshot() -> dict[str, Any]:
    return {
        "R42R": tree_hashes(R42R_ROOT), "R43A": tree_hashes(R43A_ROOT),
        "R43B": tree_hashes(R43B_ROOT), "R28_MODELS": tree_hashes(R28_MODELS_ROOT),
        "R28_RUNTIME": tree_hashes(R28_PROSPECTIVE_RUNTIME, True),
        "R28_SEALED": tree_hashes(R28_PROSPECTIVE_SEALED, True),
    }


def verify_frozen_contracts() -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    if sha256(R42R_PREREG) != R42R_SHA256: raise IdentityStop("STOP_R42R_HASH_MISMATCH")
    if sha256(R43A_CONTRACT) != R43A_SHA256: raise IdentityStop("STOP_R43A_HASH_MISMATCH")
    paths = {
        "R43B_SUMMARY": R43B_SUMMARY, "R43B_PREREG": R43B_PREREG,
        "R43B_FEATURE_IDENTITY": R43B_FEATURE_IDENTITY, "R43B_PREDICTIONS": R43B_PREDICTIONS,
        "R43B_FOLD_SCHEDULE": R43B_FOLD_SCHEDULE, "R43B_ACCEPTANCE": R43B_ACCEPTANCE,
        "R28_SOURCE_MANIFEST": R28_SOURCE_MANIFEST, "R36_LEDGER": R36_LEDGER,
        "VIX_CANONICAL": VIX_CANONICAL, "VIX_PIT_FEATURES": VIX_PIT_FEATURES,
        "VIX_INGEST_SUMMARY": VIX_INGEST_SUMMARY,
    }
    actual = {name: sha256(path) for name, path in paths.items()}
    if actual != EXPECTED_HASHES: raise IdentityStop("STOP_FROZEN_SOURCE_HASH_MISMATCH")
    r43b = json.loads(R43B_SUMMARY.read_text(encoding="utf-8"))
    prereg = json.loads(R43B_PREREG.read_text(encoding="utf-8"))
    if (r43b.get("BASELINE_FEATURES_SHA256") != R43B_FEATURES_SHA256
            or tuple(r43b.get("BASELINE_FEATURES", [])) != BASELINE_FEATURES
            or tuple(prereg.get("BASELINE_FEATURES", [])) != BASELINE_FEATURES
            or r43b.get("OOF_FOLD_COUNT") != 5 or r43b.get("OOF_PREDICTION_COUNT") != 998
            or prereg.get("HGB_BASELINE_CONFIG") != HGB_STRUCTURE
            or prereg.get("OOF_FOLD_COUNT") != 5
            or prereg.get("FUTURE_FAMILY_MIN_DELTA_SPEARMAN") != .02
            or prereg.get("FUTURE_FAMILY_MIN_DELTA_Q5_Q1") != .0005
            or r43b.get("MODEL_CONFIG_CHANGED_AFTER_RESULT") is not False):
        raise IdentityStop("STOP_R43B_BASELINE_IDENTITY_MISMATCH")
    for head in ("UP", "DOWN"):
        if (not np.isclose(r43b[f"{head}_PRIMARY_OOF_SPEARMAN"], BASELINE_REFERENCE[head]["spearman"], atol=1e-15, rtol=0)
                or not np.isclose(r43b[f"{head}_Q5_MINUS_Q1_REALIZED_Y_ECON_MEAN"], BASELINE_REFERENCE[head]["q5_q1"], atol=1e-15, rtol=0)):
            raise IdentityStop(f"STOP_R43B_REFERENCE_METRIC_MISMATCH:{head}")
    vix = json.loads(VIX_INGEST_SUMMARY.read_text(encoding="utf-8"))
    if (vix.get("final_status") != "PASS" or vix.get("prior_day_shift_validated") is not True
            or vix.get("daily_vix_regime_ready") is not True
            or vix.get("intraday_vix_features_allowed") is not False):
        raise PITContractStop("STOP_VIX_AUTHORITATIVE_PIT_CONTRACT")
    return r43b, prereg, actual


def feature_manifest(created_at: str, source_hashes: dict[str, str]) -> dict[str, Any]:
    common = {"missing_policy": "HGB_NATIVE_NAN_NO_IMPUTATION_NO_MISSING_INDICATOR",
              "selection_policy": "FROZEN_MEMBER_NOT_SELECTED_OR_REMOVED_AFTER_RESULT"}
    features = [
        {"name": "vix_level", "formula": "latest CBOE VIX CLOSE with observation DATE strictly before SOXX broker_trade_date",
         "source": str(VIX_CANONICAL), "lookback": "latest prior completed trading day", "minimum_history": 1,
         "PIT_rule": "current-day VIX close is never used for any signal on that broker_trade_date", **common},
        {"name": "vix_change_1d", "formula": "VIX_prior_close/VIX_second_prior_close-1",
         "source": str(VIX_CANONICAL), "lookback": "two prior completed VIX observations", "minimum_history": 2,
         "PIT_rule": "both daily observations have DATE strictly before broker_trade_date", **common},
        {"name": "vix_percentile_252d", "formula": "mean(last min(252,n) completed VIX closes <= latest prior close)",
         "source": str(VIX_CANONICAL), "lookback": "maximum 252 completed observations", "minimum_history": 60,
         "PIT_rule": "window ends at latest VIX DATE strictly before broker_trade_date", **common},
        {"name": "soxx_realized_vol_60m_percentile_20d",
         "formula": "current SOXX std(ddof=1) of 60 one-minute log returns ending at decision bar; empirical percentile versus last 20 prior broker dates at identical canonical session and ET HH:MM",
         "source": str(R28_SOURCE_MANIFEST), "lookback": "60 completed bars plus 20 prior comparable broker dates", "minimum_history": 20,
         "PIT_rule": "current window ends at decision timestamp; reference observations have broker_trade_date strictly earlier", **common},
        {"name": "soxx_realized_vol_1d_percentile_60d",
         "formula": "prior completed SOXX RTH daily RV=sqrt(sum(one-minute within-RTH log-return^2)); percentile within last 60 completed RTH daily RV values ending at prior broker date",
         "source": str(R28_SOURCE_MANIFEST), "lookback": "60 completed RTH broker dates", "minimum_history": 60,
         "PIT_rule": "daily RV date is strictly before signal broker_trade_date; each daily RV requires >=300 returns", **common},
        {"name": "soxx_intraday_range_percentile_20d",
         "formula": "((SOXX cumulative high-low from first canonical broker-day bar through decision bar)/first valid broker-day open) percentile versus last 20 prior broker dates at identical session and ET HH:MM",
         "source": str(R28_SOURCE_MANIFEST), "lookback": "current completed broker-day path plus 20 prior comparable broker dates", "minimum_history": 20,
         "PIT_rule": "current cumulative state ends at decision timestamp; all references are earlier broker dates", **common},
        {"name": "soxx_volume_regime_percentile_20d",
         "formula": "SOXX cumulative volume from first canonical broker-day bar through decision bar percentile versus last 20 prior broker dates at identical session and ET HH:MM",
         "source": str(R28_SOURCE_MANIFEST), "lookback": "current completed broker-day path plus 20 prior comparable broker dates", "minimum_history": 20,
         "PIT_rule": "time-of-day comparability is exact canonical session+ET HH:MM; references are earlier broker dates", **common},
    ]
    return {
        "CONTRACT_ID": "FAST3_R43C_REGIME_INFORMATION_FAMILY_INCREMENTAL_TEST_R1",
        "CREATED_AT_UTC": created_at, "STATUS": "FROZEN_BEFORE_R43C_TARGET_READ_AND_MODEL_FIT",
        "REGIME_FEATURE_COUNT": len(features), "REGIME_FEATURES": features,
        "REGIME_FEATURE_NAMES": list(REGIME_FEATURES), "MAX_NEW_FEATURE_COUNT": 8,
        "EXCLUDED_CANDIDATE": {"name": "market_vol_regime_interaction", "status": "NOT_INCLUDED_MINIMAL_FAMILY",
                               "reason": "seven legal primitive continuous states are sufficient; no interaction/formula mining"},
        "VIX_SOURCE": str(VIX_CANONICAL), "VIX_TIME_RESOLUTION": "DAILY_CLOSE_PRIOR_COMPLETED_TRADING_DAY_ONLY",
        "VIX_HISTORY_START": "1990-01-02", "VIX_HISTORY_END": "2026-07-24",
        "VIX_PIT_STATUS": "PASS_PRIOR_COMPLETED_DAILY_ONLY_INTRADAY_VIX_FORBIDDEN",
        "MISSING_VALUE_POLICY": "HGB_NATIVE_MISSING; no imputation, forward fill, row deletion, or missing indicators",
        "TARGET_ROW_DELETION_ALLOWED": False, "TARGET_CONTRACT_CHANGE_ALLOWED": False,
        "FEATURE_SELECTION_ALLOWED": False, "SHAP_ALLOWED": False,
        "MODEL_FAMILY": "sklearn HistGradientBoosting", "MODEL_CONFIG": HGB_STRUCTURE,
        "BASELINE_FEATURES_SHA256": R43B_FEATURES_SHA256, "R43A_TARGET_CONTRACT_SHA256": R43A_SHA256,
        "R42R_PREREGISTRATION_SHA256": R42R_SHA256, "OOF_FOLDS": list(VALIDATION_FOLDS),
        "INCREMENTAL_GATE": {"MIN_DELTA_SPEARMAN": .02, "MIN_DELTA_Q5_Q1": .0005,
                             "MAJORITY_FOLD_NON_DEGRADATION": "at least 3 of 5 folds"},
        "FOLD_NON_DEGRADATION_RULE": (
            "compare raw Spearman when both exist; a constant baseline is a zero-information reference, so a nonnegative regime "
            "Spearman is non-degraded, a negative one degraded; regime constant against numeric baseline is degraded; both constant is unchanged"
        ),
        "ABSOLUTE_GATE": {"SPEARMAN": .05, "Q5_Q1": ">0", "ORDERING": ["MONOTONIC_POSITIVE", "MOSTLY_POSITIVE"],
                          "FOLD_STABILITY": ">half positive among >=3 standard evaluable folds"},
        "STRONG_GATE": {"SPEARMAN": .10, "Q5_Q1": .001, "Q5_MEAN": ">0", "FOLD_STABILITY": True,
                        "TAIL_ROBUSTNESS": True},
        "HARMFUL_CLASSIFICATION_RULE": (
            "both directions delta Spearman<=-0.02 and delta Q5-Q1<=-0.0005 and at least 3/5 folds degraded"
        ),
        "SECONDARY_TARGET_IS_SUPPORTING_ONLY": True, "BASELINE_REFIT_ALLOWED": False,
        "REGIME_MODEL_FIT_BUDGET": 20, "FULL_SAMPLE_REFIT_ALLOWED": False,
        "SOURCE_SHA256": source_hashes, "RESEARCH_CHOICE_CHANGED_AFTER_RESULT": False,
    }


def load_soxx_bars_and_verify() -> pd.DataFrame:
    manifest = json.loads(R28_SOURCE_MANIFEST.read_text(encoding="utf-8"))
    records = [row for row in manifest["files"] if row["symbol"] == "SOXX"]
    if len(records) != 79: raise IdentityStop("STOP_SOXX_SOURCE_FILE_COUNT")
    for row in records:
        path = Path(row["path"])
        if not path.is_file() or sha256(path).lower() != row["sha256"].lower():
            raise IdentityStop(f"STOP_SOXX_SOURCE_FILE_HASH:{path}")
    columns = ["timestamp_utc", "timestamp_et", "broker_trade_date", "session", "open", "high", "low", "close", "volume"]
    bars = pd.concat([pd.read_parquet(row["path"], columns=columns) for row in records], ignore_index=True)
    bars["timestamp_utc"] = pd.to_datetime(bars["timestamp_utc"], utc=True, errors="raise")
    bars["timestamp_et"] = pd.to_datetime(bars["timestamp_et"], utc=True, errors="raise").dt.tz_convert("America/New_York")
    bars = bars.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
    for column in ("open", "high", "low", "close", "volume"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    bars["broker_date"] = pd.to_datetime(bars["broker_trade_date"], errors="raise").dt.normalize()
    bars["session"] = bars["session"].astype(str).str.upper()
    bars["slot"] = bars["session"] + "|" + bars["timestamp_et"].dt.strftime("%H:%M")
    valid = ((bars["open"] > 0) & (bars["close"] > 0) & (bars["volume"] >= 0)
             & (bars["high"] >= bars[["open", "low", "close"]].max(axis=1))
             & (bars["low"] <= bars[["open", "high", "close"]].min(axis=1)))
    if len(bars) != 1_822_329 or not valid.all() or bars["timestamp_utc"].duplicated().any():
        raise PITContractStop("STOP_SOXX_CANONICAL_BAR_INTEGRITY")
    log_return = np.log(bars["close"]).diff()
    bars["rv60"] = log_return.rolling(60, min_periods=60).std(ddof=1)
    grouped = bars.groupby("broker_date", sort=False)
    bars["range_state"] = (grouped["high"].cummax() - grouped["low"].cummin()) / grouped["open"].transform("first")
    bars["volume_state"] = grouped["volume"].cumsum()
    return bars


def empirical_percentile(history: np.ndarray, current: float, lookback: int, minimum: int) -> float:
    values = np.asarray(history, dtype=float)
    values = values[np.isfinite(values)][-lookback:]
    if len(values) < minimum or not np.isfinite(current): return np.nan
    return float(np.mean(values <= current))


def comparable_percentile(decisions: pd.DataFrame, bars: pd.DataFrame, value: str) -> np.ndarray:
    relevant = bars.loc[bars["slot"].isin(decisions["slot"].unique()), ["broker_date", "slot", value]].copy()
    if relevant.duplicated(["broker_date", "slot"]).any():
        raise PITContractStop(f"STOP_SOXX_COMPARABLE_SLOT_DUPLICATE:{value}")
    groups = {slot: part.sort_values("broker_date", kind="mergesort") for slot, part in relevant.groupby("slot", sort=False)}
    output = np.full(len(decisions), np.nan)
    for position, row in enumerate(decisions.itertuples(index=False)):
        history = groups[row.slot]
        dates = history["broker_date"].to_numpy(dtype="datetime64[ns]")
        cutoff = np.searchsorted(dates, np.datetime64(row.broker_date), side="left")
        output[position] = empirical_percentile(history[value].to_numpy()[:cutoff], getattr(row, value), 20, 20)
    return output


def daily_rv_percentile(decisions: pd.DataFrame, bars: pd.DataFrame) -> np.ndarray:
    rth = bars.loc[bars["session"].eq("RTH"), ["broker_date", "close"]].copy()
    rth["log_return"] = rth.groupby("broker_date", sort=False)["close"].transform(lambda x: np.log(x).diff())
    daily = rth.groupby("broker_date", sort=True)["log_return"].agg(
        observation_count=lambda x: int(x.notna().sum()), rv=lambda x: float(np.sqrt(np.square(x.dropna()).sum())))
    daily.loc[daily["observation_count"].lt(300), "rv"] = np.nan
    dates = daily.index.to_numpy(dtype="datetime64[ns]"); values = daily["rv"].to_numpy(float)
    output = np.full(len(decisions), np.nan)
    for position, date in enumerate(decisions["broker_date"]):
        cutoff = np.searchsorted(dates, np.datetime64(date), side="left")
        legal = values[:cutoff]; legal = legal[np.isfinite(legal)][-60:]
        if len(legal) == 60: output[position] = float(np.mean(legal <= legal[-1]))
    return output


def vix_features(decisions: pd.DataFrame) -> pd.DataFrame:
    daily = pd.read_parquet(VIX_CANONICAL, columns=["DATE", "CLOSE"])
    daily["DATE"] = pd.to_datetime(daily["DATE"], errors="raise").dt.normalize()
    daily["CLOSE"] = pd.to_numeric(daily["CLOSE"], errors="raise")
    if (len(daily) != 9236 or daily["DATE"].duplicated().any() or (daily["CLOSE"] <= 0).any()
            or str(daily["DATE"].min().date()) != "1990-01-02" or str(daily["DATE"].max().date()) != "2026-07-24"):
        raise PITContractStop("STOP_VIX_CANONICAL_INTEGRITY")
    dates = daily["DATE"].to_numpy(dtype="datetime64[ns]"); closes = daily["CLOSE"].to_numpy(float)
    rows = []
    for date in decisions["broker_date"]:
        cutoff = np.searchsorted(dates, np.datetime64(date), side="left")
        legal = closes[:cutoff]
        if not len(legal): rows.append((np.nan, np.nan, np.nan, None)); continue
        window = legal[-252:]
        rows.append((legal[-1], legal[-1] / legal[-2] - 1 if len(legal) >= 2 else np.nan,
                     float(np.mean(window <= legal[-1])) if len(window) >= 60 else np.nan,
                     str(pd.Timestamp(dates[cutoff - 1]).date())))
    return pd.DataFrame(rows, columns=["vix_level", "vix_change_1d", "vix_percentile_252d", "vix_information_cutoff"])


def materialize_regime_features(identity: pd.DataFrame, bars: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    decisions = identity[["candidate_id", "decision_timestamp_utc"]].copy()
    decisions["decision_timestamp_utc"] = pd.to_datetime(decisions["decision_timestamp_utc"], utc=True, errors="raise")
    state = bars[["timestamp_utc", "broker_date", "session", "slot", "rv60", "range_state", "volume_state"]]
    decisions = decisions.merge(state, left_on="decision_timestamp_utc", right_on="timestamp_utc", how="left", validate="many_to_one", indicator=True)
    if not decisions["_merge"].eq("both").all(): raise PITContractStop("STOP_SOXX_DECISION_TIMESTAMP_MATCH")
    vix = vix_features(decisions)
    for column in vix.columns: decisions[column] = vix[column].to_numpy()
    decisions["soxx_realized_vol_60m_percentile_20d"] = comparable_percentile(decisions, bars, "rv60")
    decisions["soxx_realized_vol_1d_percentile_60d"] = daily_rv_percentile(decisions, bars)
    decisions["soxx_intraday_range_percentile_20d"] = comparable_percentile(decisions, bars, "range_state")
    decisions["soxx_volume_regime_percentile_20d"] = comparable_percentile(decisions, bars, "volume_state")
    output = decisions[["candidate_id", *REGIME_FEATURES]].copy()
    if output["candidate_id"].duplicated().any(): raise PITContractStop("STOP_REGIME_FEATURE_DUPLICATE")
    cutoff = pd.to_datetime(decisions["vix_information_cutoff"], errors="coerce")
    if cutoff.isna().any() or not (cutoff < decisions["broker_date"]).all():
        raise PITContractStop("STOP_VIX_CURRENT_DAY_LEAKAGE")
    for column in REGIME_FEATURES:
        valid = output[column].dropna()
        if valid.empty or not np.isfinite(valid.to_numpy(float)).all():
            raise PITContractStop(f"STOP_REGIME_FEATURE_UNAVAILABLE:{column}")
        if ("percentile" in column and ((valid < 0).any() or (valid > 1).any())):
            raise PITContractStop(f"STOP_PERCENTILE_RANGE:{column}")
    audit = {
        "SOXX_SOURCE_ROW_COUNT": len(bars), "DECISION_TIMESTAMP_MATCH_COUNT": len(decisions),
        "FEATURE_VALID_COUNTS": {column: int(output[column].notna().sum()) for column in REGIME_FEATURES},
        "FEATURE_MISSING_COUNTS": {column: int(output[column].isna().sum()) for column in REGIME_FEATURES},
        "VIX_INFORMATION_CUTOFF_MAX": str(cutoff.max().date()),
        "VIX_CURRENT_DAY_VALUE_USED_COUNT": int((cutoff >= decisions["broker_date"]).sum()),
    }
    return output, audit


def load_frame_and_baseline() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    identity = pd.read_csv(R43B_FEATURE_IDENTITY)
    identity["decision_timestamp_utc"] = pd.to_datetime(identity["decision_timestamp_utc"], utc=True, errors="raise")
    if len(identity) != 1197 or identity["candidate_id"].duplicated().any(): raise IdentityStop("STOP_R43B_FEATURE_ROWS")
    target = pd.read_parquet(R36_LEDGER, columns=["candidate_id", "path_complete", *RETURN_COLUMNS])
    numeric = target.loc[:, RETURN_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if len(target) != 1197 or not target["path_complete"].eq(True).all() or not np.isfinite(numeric.to_numpy(float)).all():
        raise IdentityStop("STOP_R43A_TARGET_ROWS")
    target["realized_y_econ"] = numeric.mean(axis=1)
    target["realized_positive_majority"] = numeric.gt(0).sum(axis=1).ge(3).astype(int)
    frame = identity.merge(target[["candidate_id", "realized_y_econ", "realized_positive_majority"]], on="candidate_id", validate="one_to_one")
    baseline = pd.read_parquet(R43B_PREDICTIONS)
    baseline["decision_timestamp_utc"] = pd.to_datetime(baseline["decision_timestamp_utc"], utc=True, errors="raise")
    schedule = pd.read_csv(R43B_FOLD_SCHEDULE)
    if (len(baseline) != 998 or baseline["candidate_id"].duplicated().any()
            or set(schedule["fold"]) != set(VALIDATION_FOLDS)):
        raise IdentityStop("STOP_R43B_OOF_ROW_OR_FOLD_IDENTITY")
    expected = frame.loc[frame["validation_slice"].isin(VALIDATION_FOLDS), "candidate_id"]
    if set(expected) != set(baseline["candidate_id"]): raise IdentityStop("STOP_R43B_OOF_CANDIDATE_IDENTITY")
    return frame, baseline, schedule


def model_config(kind: str) -> dict[str, Any]:
    config = dict(HGB_STRUCTURE)
    config["categorical_features"] = [name in CATEGORICAL_FEATURES for name in ALL_FEATURES]
    config["loss"] = "squared_error" if kind == "regressor" else "log_loss"
    return config


def make_model(kind: str):
    config = model_config(kind)
    return HistGradientBoostingRegressor(**config) if kind == "regressor" else HistGradientBoostingClassifier(**config)


def run_oof(frame: pd.DataFrame, model_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    model_dir.mkdir(parents=True); predictions, manifest = [], []; reg_fits = cls_fits = 0
    for fold in VALIDATION_FOLDS:
        position = BLOCKS.index(fold)
        for head in ("UP", "DOWN"):
            train = frame.loc[frame["direction"].eq(head) & frame["validation_slice"].isin(BLOCKS[:position])]
            valid = frame.loc[frame["direction"].eq(head) & frame["validation_slice"].eq(fold)]
            if train.empty or valid.empty or train["realized_positive_majority"].nunique() != 2:
                raise IdentityStop(f"STOP_OOF_TRAIN_IDENTITY:{head}:{fold}")
            regressor = make_model("regressor"); regressor.fit(train.loc[:, ALL_FEATURES], train["realized_y_econ"]); reg_fits += 1
            classifier = make_model("classifier"); classifier.fit(train.loc[:, ALL_FEATURES], train["realized_positive_majority"]); cls_fits += 1
            reg_path = model_dir / f"{head}_{fold}_REGIME_PRIMARY_REGRESSOR.joblib"
            cls_path = model_dir / f"{head}_{fold}_REGIME_SECONDARY_CLASSIFIER.joblib"
            joblib.dump(regressor, reg_path, compress=3); joblib.dump(classifier, cls_path, compress=3)
            manifest.extend([
                {"direction": head, "fold": fold, "role": "REGIME_PRIMARY_REGRESSOR", "path": f"models/{reg_path.name}", "sha256": sha256(reg_path)},
                {"direction": head, "fold": fold, "role": "REGIME_SECONDARY_CLASSIFIER", "path": f"models/{cls_path.name}", "sha256": sha256(cls_path)},
            ])
            out = valid[["candidate_id", "decision_timestamp_utc", "validation_slice", "direction", "realized_y_econ", "realized_positive_majority"]].copy()
            out["predicted_y_econ"] = regressor.predict(valid.loc[:, ALL_FEATURES])
            out["predicted_positive_majority_probability"] = classifier.predict_proba(valid.loc[:, ALL_FEATURES])[:, 1]
            predictions.append(out)
    counts = {"PRIMARY_REGRESSION_FIT_COUNT": reg_fits, "SECONDARY_CLASSIFICATION_FIT_COUNT": cls_fits,
              "MODEL_FIT_COUNT": reg_fits + cls_fits, "FULL_SAMPLE_REFIT_COUNT": 0}
    if counts["MODEL_FIT_COUNT"] != 20: raise IdentityStop("STOP_MODEL_FIT_BUDGET")
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(manifest), counts


def correlation(x: pd.Series, y: pd.Series, method: str = "spearman") -> float | None:
    mask = x.notna() & y.notna(); x, y = x[mask], y[mask]
    if len(x) < 2 or x.nunique() < 2 or y.nunique() < 2: return None
    value = x.corr(y, method=method)
    return float(value) if pd.notna(value) else None


def stable_quintiles(frame: pd.DataFrame, prediction: str) -> pd.Series:
    result = pd.Series(index=frame.index, dtype="object")
    for _, indices in frame.groupby("direction", sort=True).groups.items():
        ordered = frame.loc[indices].sort_values([prediction, "decision_timestamp_utc", "candidate_id"], kind="mergesort")
        bucket = np.minimum(np.floor(np.arange(len(ordered)) * 5 / len(ordered)).astype(int), 4)
        result.loc[ordered.index] = [QUINTILES[index] for index in bucket]
    if result.isna().any(): raise IdentityStop("STOP_QUINTILE_IDENTITY")
    return result


def ordering(values: list[float]) -> str:
    delta = np.diff(np.asarray(values, dtype=float))
    if np.all(delta >= 0): return "MONOTONIC_POSITIVE"
    if int((delta > 0).sum()) >= 3 and values[-1] > values[0]: return "MOSTLY_POSITIVE"
    if np.all(delta <= 0): return "MONOTONIC_NEGATIVE"
    return "NON_MONOTONIC"


def remove_one(part: pd.DataFrame, best: bool) -> pd.DataFrame:
    if part.empty: return part
    ordered = part.sort_values(["realized_y_econ", "candidate_id"], ascending=[not best, True], kind="mergesort")
    return part.drop(index=ordered.index[0])


def primary_metrics(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metrics, quintiles, tails = [], [], []
    for head, part in predictions.groupby("direction", sort=True):
        actual, predicted = part["realized_y_econ"], part["predicted_y_econ"]
        for quintile in QUINTILES:
            q = part.loc[part["primary_quintile"].eq(quintile)]
            quintiles.append({"direction": head, "quintile": quintile, "count": len(q),
                              "mean_prediction": float(q["predicted_y_econ"].mean()),
                              "realized_y_econ_mean": float(q["realized_y_econ"].mean()),
                              "realized_y_econ_median": float(q["realized_y_econ"].median()),
                              "positive_y_econ_rate": float(q["realized_y_econ"].gt(0).mean())})
        q1 = part.loc[part["primary_quintile"].eq("Q1")]; q5 = part.loc[part["primary_quintile"].eq("Q5")]
        means = [float(part.loc[part["primary_quintile"].eq(q), "realized_y_econ"].mean()) for q in QUINTILES]
        metrics.append({"direction": head, "count": len(part), "spearman": correlation(predicted, actual),
                        "pearson": correlation(predicted, actual, "pearson"),
                        "mae": float(mean_absolute_error(actual, predicted)),
                        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
                        "r2": float(r2_score(actual, predicted)), "q1_mean": means[0], "q5_mean": means[-1],
                        "q5_q1": means[-1] - means[0], "ordering": ordering(means)})
        union = pd.concat([q1, q5])
        def spread(sample: pd.DataFrame) -> float:
            return float(sample.loc[sample["primary_quintile"].eq("Q5"), "realized_y_econ"].mean()
                         - sample.loc[sample["primary_quintile"].eq("Q1"), "realized_y_econ"].mean())
        raw = spread(union); ex_best = spread(remove_one(union, True)); ex_worst = spread(remove_one(union, False))
        tails.append({"direction": head, "q5_minus_q1_raw": raw, "q5_minus_q1_excluding_best1": ex_best,
                      "q5_minus_q1_excluding_worst1": ex_worst,
                      "tail_robustness": None if raw <= 0 else bool(ex_best > 0 and ex_worst > 0)})
    return pd.DataFrame(metrics), pd.DataFrame(quintiles), pd.DataFrame(tails)


def local_fold_metrics(predictions: pd.DataFrame, prefix: str) -> pd.DataFrame:
    rows = []
    for (head, fold), part in predictions.groupby(["direction", "validation_slice"], sort=True):
        low = len(part) < MIN_QUINTILE_SAMPLE; spearman = correlation(part["predicted_y_econ"], part["realized_y_econ"])
        q5_q1 = None
        if not low and part["predicted_y_econ"].nunique() >= 5:
            local = part.copy(); local["q"] = stable_quintiles(local, "predicted_y_econ")
            q5_q1 = float(local.loc[local["q"].eq("Q5"), "realized_y_econ"].mean()
                          - local.loc[local["q"].eq("Q1"), "realized_y_econ"].mean())
        rows.append({"direction": head, "validation_slice": fold, f"{prefix}_sample_count": len(part),
                     f"{prefix}_prediction_unique_count": int(part["predicted_y_econ"].nunique()),
                     f"{prefix}_spearman": spearman, f"{prefix}_q5_q1": q5_q1,
                     f"{prefix}_standard_evaluable": bool(not low and spearman is not None)})
    return pd.DataFrame(rows)


def paired_folds(baseline: pd.DataFrame, regime: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    base = baseline.rename(columns={"head": "direction"}).copy()
    base = base.rename(columns={"predicted_y_econ": "base_prediction"})
    base["predicted_y_econ"] = base["base_prediction"]
    base_table = local_fold_metrics(base, "baseline")
    regime_table = local_fold_metrics(regime, "regime")
    table = base_table.merge(regime_table, on=["direction", "validation_slice"], validate="one_to_one")
    delta_s, delta_q, status = [], [], []
    for row in table.itertuples(index=False):
        bs, rs = row.baseline_spearman, row.regime_spearman
        delta_s.append(None if pd.isna(bs) or pd.isna(rs) else float(rs - bs))
        delta_q.append(None if pd.isna(row.baseline_q5_q1) or pd.isna(row.regime_q5_q1) else float(row.regime_q5_q1 - row.baseline_q5_q1))
        if pd.isna(bs) and pd.isna(rs): status.append("NON_DEGRADED_BOTH_CONSTANT")
        elif pd.isna(bs): status.append("NON_DEGRADED_FROM_ZERO_INFORMATION" if rs >= 0 else "DEGRADED_FROM_ZERO_INFORMATION")
        elif pd.isna(rs): status.append("DEGRADED_TO_CONSTANT")
        else: status.append("NON_DEGRADED" if rs >= bs else "DEGRADED")
    table["delta_spearman"] = delta_s; table["delta_q5_q1"] = delta_q; table["paired_status"] = status
    flags = {}
    for head in ("UP", "DOWN"):
        part = table.loc[table["direction"].eq(head)]
        non_degraded = int(part["paired_status"].str.startswith("NON_DEGRADED").sum())
        standard = part.loc[part["regime_standard_evaluable"]]
        flags[head] = {
            "FOLDS_WITH_POSITIVE_DELTA_SPEARMAN": int(part["delta_spearman"].gt(0).sum()),
            "FOLDS_WITH_POSITIVE_DELTA_Q5_Q1": int(part["delta_q5_q1"].gt(0).sum()),
            "FOLD_NON_DEGRADATION_COUNT": non_degraded, "MAJORITY_FOLD_NON_DEGRADATION": non_degraded >= 3,
            "FOLD_DEGRADATION_COUNT": 5 - non_degraded,
            "REGIME_EVALUABLE_SPEARMAN_FOLD_COUNT": len(standard),
            "REGIME_POSITIVE_SPEARMAN_FOLD_COUNT": int(standard["regime_spearman"].gt(0).sum()),
            "REGIME_FOLD_STABILITY": bool(len(standard) >= 3 and standard["regime_spearman"].gt(0).sum() > len(standard) / 2),
        }
    return table, flags


def secondary_metrics(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    metrics, quintiles = [], []
    for head, part in predictions.groupby("direction", sort=True):
        actual = part["realized_positive_majority"].astype(int); probability = part["predicted_positive_majority_probability"]
        metrics.append({"direction": head, "base_rate": float(actual.mean()),
                        "auroc": float(roc_auc_score(actual, probability)),
                        "pr_auc": float(average_precision_score(actual, probability)),
                        "brier": float(brier_score_loss(actual, probability))})
        for quintile in QUINTILES:
            q = part.loc[part["secondary_quintile"].eq(quintile)]
            quintiles.append({"direction": head, "quintile": quintile, "count": len(q),
                              "mean_probability": float(q["predicted_positive_majority_probability"].mean()),
                              "positive_majority_rate": float(q["realized_positive_majority"].mean())})
    return pd.DataFrame(metrics), pd.DataFrame(quintiles)


def univariate_diagnostic(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for feature in REGIME_FEATURES:
        row = {"feature_name": feature}
        for head in ("UP", "DOWN"):
            part = frame.loc[frame["direction"].eq(head)]
            row[f"{head.lower()}_univariate_spearman"] = correlation(part[feature], part["realized_y_econ"])
        rows.append(row)
    return pd.DataFrame(rows)


def evaluate(primary: pd.DataFrame, quintiles: pd.DataFrame, tails: pd.DataFrame,
             fold_flags: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], str, bool]:
    flags: dict[str, Any] = {}; accepted = absolute = strong = False; harmful_heads = []
    for head in ("UP", "DOWN"):
        row = primary.loc[primary["direction"].eq(head)].iloc[0]
        delta_s = float(row["spearman"] - BASELINE_REFERENCE[head]["spearman"])
        delta_q = float(row["q5_q1"] - BASELINE_REFERENCE[head]["q5_q1"])
        stable = fold_flags[head]["REGIME_FOLD_STABILITY"]
        incremental = bool(delta_s >= .02 and delta_q >= .0005 and fold_flags[head]["MAJORITY_FOLD_NON_DEGRADATION"])
        absolute_head = bool(row["spearman"] >= .05 and row["q5_q1"] > 0
                             and row["ordering"] in ("MONOTONIC_POSITIVE", "MOSTLY_POSITIVE") and stable)
        tail = tails.loc[tails["direction"].eq(head), "tail_robustness"].iloc[0]
        tail_ok = bool(tail) if pd.notna(tail) else False
        strong_head = bool(row["spearman"] >= .10 and row["q5_q1"] >= .001 and row["q5_mean"] > 0
                           and stable and tail_ok)
        harmful_heads.append(bool(delta_s <= -.02 and delta_q <= -.0005 and fold_flags[head]["FOLD_DEGRADATION_COUNT"] >= 3))
        flags.update({f"{head}_DELTA_SPEARMAN": delta_s, f"{head}_DELTA_Q5_Q1": delta_q,
                      f"{head}_REGIME_PRIMARY_INCREMENTAL_ACCEPTANCE": incremental,
                      f"{head}_REGIME_ABSOLUTE_ECONOMIC_SIGNAL": absolute_head,
                      f"{head}_REGIME_STRONG_ECONOMIC_SIGNAL": strong_head})
        accepted |= incremental; absolute |= absolute_head; strong |= strong_head
    harmful = bool(all(harmful_heads))
    classification = ("B_REGIME_INFORMATION_ESTABLISHES_ABSOLUTE_ECONOMIC_SIGNAL" if accepted and absolute else
                      "A_REGIME_INFORMATION_INCREMENTALLY_USEFUL" if accepted else
                      "D_REGIME_INFORMATION_HARMFUL" if harmful else
                      "C_REGIME_INFORMATION_NOT_INCREMENTALLY_USEFUL")
    flags.update({"REGIME_PRIMARY_INCREMENTAL_ACCEPTANCE": accepted,
                  "REGIME_ABSOLUTE_ECONOMIC_SIGNAL": absolute,
                  "REGIME_STRONG_ECONOMIC_SIGNAL": strong})
    return flags, classification, bool(classification.startswith(("A_", "B_")))


def render_terminal(summary: dict[str, Any]) -> str:
    keys = [
        "FAST3_R43C_STATUS", "FAST3_R43C_CLASSIFICATION", "FAST3_R43C_DECISION",
        "REGIME_FEATURE_COUNT", "REGIME_FEATURES", "R43C_REGIME_FEATURE_MANIFEST_SHA256",
        "TARGET_ROW_IDENTITY_UNCHANGED", "OOF_FOLD_IDENTITY_MATCH",
        "UP_BASELINE_SPEARMAN", "UP_REGIME_SPEARMAN", "UP_DELTA_SPEARMAN",
        "DOWN_BASELINE_SPEARMAN", "DOWN_REGIME_SPEARMAN", "DOWN_DELTA_SPEARMAN",
        "UP_BASELINE_Q5_Q1", "UP_REGIME_Q5_Q1", "UP_DELTA_Q5_Q1",
        "DOWN_BASELINE_Q5_Q1", "DOWN_REGIME_Q5_Q1", "DOWN_DELTA_Q5_Q1",
        "UP_REGIME_PRIMARY_INCREMENTAL_ACCEPTANCE", "DOWN_REGIME_PRIMARY_INCREMENTAL_ACCEPTANCE",
        "UP_REGIME_ABSOLUTE_ECONOMIC_SIGNAL", "DOWN_REGIME_ABSOLUTE_ECONOMIC_SIGNAL",
        "REGIME_STRONG_ECONOMIC_SIGNAL", "UP_FOLDS_WITH_POSITIVE_DELTA_SPEARMAN",
        "DOWN_FOLDS_WITH_POSITIVE_DELTA_SPEARMAN", "UP_FOLDS_WITH_POSITIVE_DELTA_Q5_Q1",
        "DOWN_FOLDS_WITH_POSITIVE_DELTA_Q5_Q1", "UP_BASELINE_SECONDARY_AUROC",
        "UP_REGIME_SECONDARY_AUROC", "DOWN_BASELINE_SECONDARY_AUROC", "DOWN_REGIME_SECONDARY_AUROC",
        "REGIME_FAMILY_RETAINED", "MODEL_FIT_COUNT", "FULL_SAMPLE_REFIT_COUNT",
        "R43A_TARGET_CONTRACT_SHA256_VERIFIED", "R43B_BASELINE_FEATURES_SHA256_VERIFIED",
        "R42R_PREREGISTRATION_SHA256_VERIFIED", "R28_PROSPECTIVE_LINE_ISOLATION",
        "PIT_STATUS", "OOF_INTEGRITY_STATUS", "TARGET_CONTRACT_STATUS", "STORAGE_CONTRACT_STATUS", "NEXT_STAGE",
    ]
    def show(value: Any) -> str:
        if isinstance(value, bool): return str(value).lower()
        if isinstance(value, (list, dict)): return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        if value is None or (isinstance(value, float) and not np.isfinite(value)): return "NOT_AVAILABLE"
        return str(value)
    return "\n".join(f"{key}={show(summary[key])}" for key in keys)


def execute() -> dict[str, Any]:
    if AUTHORITATIVE_ROOT.exists(): raise IdentityStop("STOP_AUTHORITATIVE_R43C_ALREADY_EXISTS")
    if STAGING_ROOT.exists(): raise IdentityStop("STOP_R43C_STAGING_ALREADY_EXISTS")
    isolation_before = isolation_snapshot()
    r43b, _, source_hashes = verify_frozen_contracts()
    STAGING_ROOT.mkdir(parents=True)
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = feature_manifest(created_at, source_hashes)
    manifest_path = STAGING_ROOT / "FAST3_R43C_REGIME_FEATURE_MANIFEST.json"
    write_json(manifest_path, manifest); manifest_hash = sha256(manifest_path)

    frame, baseline, schedule = load_frame_and_baseline()
    bars = load_soxx_bars_and_verify()
    regime_features, feature_audit = materialize_regime_features(frame, bars)
    frame = frame.merge(regime_features, on="candidate_id", validate="one_to_one")
    predictions, model_manifest, fit_counts = run_oof(frame, STAGING_ROOT / "models")
    predictions["primary_quintile"] = stable_quintiles(predictions, "predicted_y_econ")
    predictions["secondary_quintile"] = stable_quintiles(predictions, "predicted_positive_majority_probability")
    primary, quintiles, tails = primary_metrics(predictions)
    fold_table, fold_flags = paired_folds(baseline, predictions)
    secondary, secondary_quintiles = secondary_metrics(predictions)
    diagnostic = univariate_diagnostic(frame)
    flags, classification, retained = evaluate(primary, quintiles, tails, fold_flags)

    baseline_ids = set(baseline["candidate_id"]); regime_ids = set(predictions["candidate_id"])
    exact_rows = len(baseline_ids & regime_ids); row_identity = baseline_ids == regime_ids and len(predictions) == 998
    if not row_identity: raise IdentityStop("STOP_REGIME_DATA_IDENTITY_FAILURE")
    if set(schedule["fold"]) != set(predictions["validation_slice"]): raise IdentityStop("STOP_OOF_FOLD_IDENTITY")
    summary: dict[str, Any] = {
        "FAST3_R43C_STATUS": "PASS", "FAST3_R43C_CLASSIFICATION": classification,
        "FAST3_R43C_DECISION": "R43D_PATH_SHAPE_INFORMATION_FAMILY_INCREMENTAL_TEST",
        "NEXT_STAGE": "R43D_PATH_SHAPE_INFORMATION_FAMILY_INCREMENTAL_TEST",
        "CREATED_AT_UTC": created_at, "REGIME_FEATURE_COUNT": len(REGIME_FEATURES),
        "REGIME_FEATURES": list(REGIME_FEATURES), "R43C_REGIME_FEATURE_MANIFEST_SHA256": manifest_hash,
        "BASELINE_FEATURE_COUNT": len(BASELINE_FEATURES), "BASELINE_ROW_COUNT": len(baseline),
        "REGIME_ELIGIBLE_ROW_COUNT": len(predictions), "EXACT_ROW_MATCH_COUNT": exact_rows,
        "TARGET_ROW_IDENTITY_UNCHANGED": row_identity, "OOF_FOLD_IDENTITY_MATCH": True, "OOF_FOLD_COUNT": 5,
        "R43B_MODEL_CONFIG_EXACT_MATCH": True, "HGB_REGIME_CONFIG": {"regressor": model_config("regressor"), "classifier": model_config("classifier")},
        "VIX_SOURCE": str(VIX_CANONICAL), "VIX_TIME_RESOLUTION": "DAILY_CLOSE_PRIOR_COMPLETED_TRADING_DAY_ONLY",
        "VIX_HISTORY_START": "1990-01-02", "VIX_HISTORY_END": "2026-07-24",
        "VIX_PIT_STATUS": "PASS_PRIOR_COMPLETED_DAILY_ONLY_INTRADAY_VIX_FORBIDDEN",
        "REGIME_FAMILY_RETAINED": retained, "SECONDARY_TARGET_IS_SUPPORTING_ONLY": True,
        **fit_counts, **flags, **feature_audit,
        "R43A_TARGET_CONTRACT_SHA256_VERIFIED": True, "R43B_BASELINE_FEATURES_SHA256_VERIFIED": True,
        "R42R_PREREGISTRATION_SHA256_VERIFIED": True, "R28_MODEL_CHANGED": False,
        "R28_FEATURE_CHANGED": False, "R28_THRESHOLD_CHANGED": False, "R28_CONFIRMATION_LEDGER_CHANGED": False,
        "PIT_STATUS": "PASS_ALL_REGIME_FEATURES_STRICTLY_TRAILING_DECISION_TIME",
        "OOF_INTEGRITY_STATUS": "PASS_EXACT_R43B_FIVE_EXPANDING_FOLDS_NO_SHUFFLE",
        "TARGET_CONTRACT_STATUS": "PASS_R43A_EXACT_HASH_TARGET_UNCHANGED",
        "STORAGE_CONTRACT_STATUS": "PASS_FAST3_STORAGE_CONTRACT_R1_EXTERNAL_GENERATION_RESEARCH_ONLY",
        "RESEARCH_CHOICE_CHANGED_AFTER_RESULT": False, "PARAMETER_SEARCH_COUNT": 0,
        "FEATURE_SELECTION_COUNT": 0, "BASELINE_REFIT_COUNT": 0,
        "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
        "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
    }
    for head in ("UP", "DOWN"):
        p = primary.loc[primary["direction"].eq(head)].iloc[0]
        s = secondary.loc[secondary["direction"].eq(head)].iloc[0]
        base_secondary = r43b[f"{head}_SECONDARY_AUROC"]
        base_pr_auc = r43b[f"{head}_SECONDARY_PR_AUC"]
        base_brier = r43b[f"{head}_SECONDARY_BRIER_SCORE"]
        summary.update({
            f"{head}_BASELINE_SPEARMAN": BASELINE_REFERENCE[head]["spearman"], f"{head}_REGIME_SPEARMAN": p["spearman"],
            f"{head}_BASELINE_Q5_Q1": BASELINE_REFERENCE[head]["q5_q1"], f"{head}_REGIME_Q5_Q1": p["q5_q1"],
            f"{head}_REGIME_Q1_REALIZED_Y_ECON_MEAN": p["q1_mean"], f"{head}_REGIME_Q5_REALIZED_Y_ECON_MEAN": p["q5_mean"],
            f"{head}_REGIME_ORDERING": p["ordering"], f"{head}_REGIME_PEARSON": p["pearson"],
            f"{head}_REGIME_MAE": p["mae"], f"{head}_REGIME_RMSE": p["rmse"], f"{head}_REGIME_R2": p["r2"],
            f"{head}_FOLDS_WITH_POSITIVE_DELTA_SPEARMAN": fold_flags[head]["FOLDS_WITH_POSITIVE_DELTA_SPEARMAN"],
            f"{head}_FOLDS_WITH_POSITIVE_DELTA_Q5_Q1": fold_flags[head]["FOLDS_WITH_POSITIVE_DELTA_Q5_Q1"],
            f"{head}_MAJORITY_FOLD_NON_DEGRADATION": fold_flags[head]["MAJORITY_FOLD_NON_DEGRADATION"],
            f"{head}_FOLD_NON_DEGRADATION_COUNT": fold_flags[head]["FOLD_NON_DEGRADATION_COUNT"],
            f"{head}_BASELINE_SECONDARY_AUROC": base_secondary, f"{head}_REGIME_SECONDARY_AUROC": s["auroc"],
            f"{head}_DELTA_SECONDARY_AUROC": float(s["auroc"] - base_secondary),
            f"{head}_BASELINE_SECONDARY_PR_AUC": base_pr_auc, f"{head}_REGIME_SECONDARY_PR_AUC": s["pr_auc"],
            f"{head}_DELTA_SECONDARY_PR_AUC": float(s["pr_auc"] - base_pr_auc),
            f"{head}_BASELINE_SECONDARY_BRIER": base_brier, f"{head}_REGIME_SECONDARY_BRIER": s["brier"],
            f"{head}_DELTA_SECONDARY_BRIER": float(s["brier"] - base_brier),
        })
    isolation_after = isolation_snapshot(); isolation_unchanged = isolation_before == isolation_after
    if not isolation_unchanged: raise IdentityStop("STOP_FROZEN_LINE_MUTATION")
    summary["R28_PROSPECTIVE_LINE_ISOLATION"] = True
    summary["FROZEN_ISOLATION_TREE_SHA256"] = isolation_before

    regime_features.to_parquet(STAGING_ROOT / "FAST3_R43C_REGIME_FEATURE_VALUES.parquet", index=False)
    predictions.to_parquet(STAGING_ROOT / "FAST3_R43C_OOF_PREDICTIONS.parquet", index=False)
    model_manifest.to_csv(STAGING_ROOT / "FAST3_R43C_MODEL_MANIFEST.csv", index=False)
    primary.to_csv(STAGING_ROOT / "FAST3_R43C_PRIMARY_METRICS.csv", index=False)
    quintiles.to_csv(STAGING_ROOT / "FAST3_R43C_PRIMARY_QUINTILES.csv", index=False)
    tails.to_csv(STAGING_ROOT / "FAST3_R43C_TAIL_ROBUSTNESS.csv", index=False)
    fold_table.to_csv(STAGING_ROOT / "FAST3_R43C_FOLD_PAIRED_COMPARISON.csv", index=False)
    secondary.to_csv(STAGING_ROOT / "FAST3_R43C_SECONDARY_METRICS.csv", index=False)
    secondary_quintiles.to_csv(STAGING_ROOT / "FAST3_R43C_SECONDARY_QUINTILES.csv", index=False)
    diagnostic.to_csv(STAGING_ROOT / "FAST3_R43C_REGIME_UNIVARIATE_DIAGNOSTIC.csv", index=False)
    write_json(STAGING_ROOT / "FAST3_R43C_SUMMARY.json", summary)
    report = ["# FAST3 R43C Regime Information Family Incremental Test R1", "",
              f"- Classification: `{classification}`", f"- Family retained: `{retained}`",
              f"- Model fits: `{fit_counts['MODEL_FIT_COUNT']}` regime OOF only; baseline reused; no full-sample refit.", "",
              "The seven-feature continuous regime family was frozen before target read and model fit. No threshold, feature, model, target, row, fold, or hyperparameter search occurred.", "",
              "## Terminal summary", "", "```text", render_terminal(summary), "```", ""]
    (STAGING_ROOT / "FAST3_R43C_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    AUTHORITATIVE_ROOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(STAGING_ROOT), str(AUTHORITATIVE_ROOT))
    summary["ARTIFACT_ROOT"] = str(AUTHORITATIVE_ROOT)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    if not args.execute: print("FAST3_R43C_STATUS=READY_REQUIRES_EXECUTE"); return 0
    try: summary = execute()
    except IdentityStop as exc:
        print("FAST3_R43C_STATUS=STOP\nFAST3_R43C_CLASSIFICATION=E_REGIME_DATA_IDENTITY_FAILURE")
        print(f"FAST3_R43C_DECISION={exc}"); return 2
    except PITContractStop as exc:
        print("FAST3_R43C_STATUS=STOP\nFAST3_R43C_CLASSIFICATION=F_PIT_OR_CONTRACT_FAILURE")
        print(f"FAST3_R43C_DECISION={exc}"); return 2
    print(render_terminal(summary)); print(f"ARTIFACT_ROOT={summary['ARTIFACT_ROOT']}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
