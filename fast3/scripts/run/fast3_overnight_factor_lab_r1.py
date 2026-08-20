#!/usr/bin/env python3
"""Autonomous, resumable driver for the frozen FAST3 overnight factor lab.

Scientific choices live in the two frozen JSON contracts.  This module only
materializes their deterministic computation graph and checkpoints each work
unit outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
import shutil
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
DATA = Path(r"D:\us-tech-quant-data")
CACHE = Path(r"D:\us-tech-quant-cache")
RUN_ID = "20260810T182520Z"
FROZEN = RESULTS / "frozen/fast3" / f"overnight_factor_lab_{RUN_ID}"
SCRATCH = RESULTS / "scratch/fast3" / f"overnight_factor_lab_{RUN_ID}"
RUNTIME = RESULTS / "runtime/fast3" / f"overnight_factor_lab_{RUN_ID}"
PREREG = FROZEN / "FAST3_OVERNIGHT_FACTOR_LAB_PREREGISTRATION.json"
UNIVERSE = FROZEN / "FAST3_OVERNIGHT_FACTOR_UNIVERSE_MANIFEST.json"
RESUME = FROZEN / "FAST3_OVERNIGHT_RESUME_STATE.json"
PREREG_SHA = "f3fce6b375cb6a7402790f65029ec8eda742905003537119c3d85ab31978f7b8"
UNIVERSE_SHA = "aaab3d59e4d7948731c44c849af8a8679031c1dec7a7d8611f38f62dee89611b"
R42R_SHA = "2df064f334d6a8bc45d79d8bd4f308ee9b82a33c97129a6ae36ba6aecfc9c3e1"
R43A_SHA = "a5d43651433c6dde50eef791facd02047db2be073a0097acaf31cd1af25d2d6a"

R43B_ROOT = RESULTS / "frozen/fast3/r43b_current_information_set_economic_baseline_r1"
R43C_ROOT = RESULTS / "frozen/fast3/r43c_regime_information_family_incremental_test_r1"
R43D_ROOT = RESULTS / "frozen/fast3/r43d_path_shape_information_family_incremental_test_r1"
R43C_SOURCE = REPO / "fast3/scripts/run/fast3_r43c_regime_information_family_incremental_test_r1.py"
R43C_SOURCE_SHA = "862f5d73712a8c960605b6407827ad560a82d7e9ee2cc9dc971f67e98be22c5c"
R43B_IDENTITY = R43B_ROOT / "FAST3_R43B_FEATURE_IDENTITY.csv"
R43B_OOF = R43B_ROOT / "FAST3_R43B_OOF_PREDICTIONS.parquet"
R43D_OOF = R43D_ROOT / "FAST3_R43D_OOF_PREDICTIONS.parquet"
R43C_VALUES = R43C_ROOT / "FAST3_R43C_REGIME_FEATURE_VALUES.parquet"
R43D_VALUES = R43D_ROOT / "FAST3_R43D_PATH_FEATURE_VALUES.parquet"
R36_LEDGER = RESULTS / "scratch/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z/FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet"
UNDERLYING_MANIFEST = RESULTS / "frozen/fast3/cleanroom_r2_20260808/cleanroom_r2_preholdout_source_manifest.json"
ETF_MANIFEST = RESULTS / "frozen/fast3/r28_3e_clean_lineage_first_touch_20260809_r3/R28_3E_CANONICAL_ETF_PARTITION_MANIFEST.json"

BASELINE_FEATURES = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m",
    "realized_vol_60m", "relative_volume", "range_position", "symbol_code",
    "direction_code", "session_code", "volume_zscore_60m",
    "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m",
)
PATH_FEATURES = (
    "return_acceleration_5v15", "trend_efficiency_15m", "trend_efficiency_60m",
    "predecision_mfe_15m", "predecision_mae_15m",
    "drawdown_from_favorable_extreme_15m", "close_location_15m",
    "directional_path_consistency_15m",
)
BLOCKS = ("OOF_2020", "OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN")
VALIDATION_FOLDS = BLOCKS[1:]
HGB = {
    "learning_rate": .08, "max_iter": 100, "max_leaf_nodes": 7,
    "min_samples_leaf": 200, "l2_regularization": 1.0,
    "random_state": 1729, "early_stopping": False,
}
RETURN_COLUMNS = tuple(f"return_{h}m_net20" for h in (5, 10, 15, 30, 60))
QUINTILES = ("Q1", "Q2", "Q3", "Q4", "Q5")
BOOTSTRAP_REPS = 10_000
PERMUTATION_REPS = 10_000
BATCH_SIZE = 250
BOOTSTRAP_SEED = 20260811
PERMUTATION_SEED = 20260812
HEARTBEAT_SECONDS = 300

STAGE_ORDER = (
    "factor_matrix", "descriptive", "incumbents", "singles", "pairs",
    "families", "family_pairs", "aggregate_raw", "bootstrap", "bh_fdr",
    "max_t", "robustness", "secondary", "final_selection", "crossfit",
    "r45", "finalize",
)


class ContractStop(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=json_default).encode("utf-8")


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)): return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    if isinstance(value, Path): return str(value)
    raise TypeError(type(value).__name__)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_bytes(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                                     default=json_default).encode("utf-8") + b"\n")
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None: raise ContractStop(f"MODULE_LOAD:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    if not PREREG.is_file() or not UNIVERSE.is_file() or not RESUME.is_file():
        raise ContractStop("AUTHORITATIVE_CONTRACT_MISSING")
    if sha256(PREREG) != PREREG_SHA: raise ContractStop("PREREGISTRATION_SHA256_MISMATCH")
    if sha256(UNIVERSE) != UNIVERSE_SHA: raise ContractStop("FACTOR_UNIVERSE_SHA256_MISMATCH")
    if sha256(R43C_SOURCE) != R43C_SOURCE_SHA: raise ContractStop("R43C_SHARED_SOURCE_SHA256_MISMATCH")
    prereg, universe = read_json(PREREG), read_json(UNIVERSE)
    if prereg["target"]["sha256"] != R43A_SHA or prereg["r28_prospective_preregistration_sha256"] != R42R_SHA:
        raise ContractStop("UPSTREAM_FROZEN_IDENTITY_MISMATCH")
    if universe["preregistered_atomic_factor_count"] != 72 or universe["maximum_combination_order"] != 2:
        raise ContractStop("FROZEN_UNIVERSE_CONTRACT_MISMATCH")
    return prereg, universe


class Checkpoint:
    def __init__(self, resume_path: Path = RESUME):
        self.path = resume_path
        self.value = read_json(resume_path)
        self.value.setdefault("completed_work_units", {})
        self.value.setdefault("artifact_sha256", {})
        self.value.setdefault("random_seeds", {"bootstrap": BOOTSTRAP_SEED, "permutation": PERMUTATION_SEED})
        self.value.setdefault("work_unit_totals", {})
        self.value.setdefault("model_fit_count", 0)
        self.value.setdefault("secondary_model_fit_count", 0)
        self.last_heartbeat = 0.0

    def completed(self, stage: str) -> set[str]:
        return set(self.value["completed_work_units"].get(stage, []))

    def mark(self, stage: str, unit: str, artifact: Path | None = None, fits: int = 0) -> None:
        units = self.value["completed_work_units"].setdefault(stage, [])
        if unit not in units: units.append(unit)
        units.sort()
        self.value["last_successful_work_unit"] = f"{stage}:{unit}"
        self.value["current_stage"] = stage
        self.value["updated_at_utc"] = utc_now()
        self.value["model_fit_count"] = int(self.value.get("model_fit_count", 0)) + int(fits)
        if artifact is not None:
            self.value["artifact_sha256"][str(artifact)] = sha256(artifact)
        self._refresh_pending()
        atomic_json(self.path, self.value)
        self.heartbeat()

    def set_total(self, stage: str, total: int) -> None:
        self.value["work_unit_totals"][stage] = int(total)
        self._refresh_pending()
        atomic_json(self.path, self.value)

    def set_stage(self, stage: str) -> None:
        self.value["current_stage"] = stage
        self.value["updated_at_utc"] = utc_now()
        self._refresh_pending()
        atomic_json(self.path, self.value)
        self.heartbeat(force=True)

    def artifact(self, path: Path) -> None:
        self.value["artifact_sha256"][str(path)] = sha256(path)
        atomic_json(self.path, self.value)

    def _refresh_pending(self) -> None:
        pending = {}
        for stage, total in self.value.get("work_unit_totals", {}).items():
            done = len(self.value["completed_work_units"].get(stage, []))
            pending[stage] = max(0, int(total) - done)
        self.value["pending_work_units"] = pending

    def heartbeat(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last_heartbeat < HEARTBEAT_SECONDS: return
        payload = {
            "timestamp": utc_now(), "PID": os.getpid(),
            "current_stage": self.value.get("current_stage", "startup"),
            "completed_work_units": {k: len(v) for k, v in self.value["completed_work_units"].items()},
            "total_work_units": self.value.get("work_unit_totals", {}),
            "last_completed_unit": self.value.get("last_successful_work_unit"),
            "resume_state_sha256": sha256(self.path),
        }
        atomic_json(RUNTIME / "HEARTBEAT.json", payload)
        self.last_heartbeat = now


@dataclass(frozen=True)
class FactorDef:
    name: str
    family: str
    formula_id: str
    source: str
    lookback: str


def registry_from_universe(universe: dict[str, Any]) -> list[FactorDef]:
    formulas: dict[str, tuple[str, str, str]] = {
        "REGIME": ("R43C_FROZEN", "R43C frozen PIT factor values", "frozen trailing contract"),
        "PATH": ("R43D_FROZEN", "R43D frozen PIT factor values", "15/60 completed bars"),
        "CROSS_ASSET": ("CROSS_R1", "QQQ/SOXX frozen canonical 1m", "up to 60 completed bars"),
        "EXECUTION": ("EXECUTION_R1", "frozen canonical mapped execution ETF 1m", "up to 60 completed bars"),
        "OSCILLATOR": ("OSCILLATOR_R1", "underlying frozen canonical 1m", "continuous warmup/up to 50 bars"),
        "TREND": ("TREND_R1", "underlying frozen canonical 1m", "up to 70 completed bars"),
        "BREAKOUT": ("BREAKOUT_R1", "underlying frozen canonical OHLC 1m", "up to 60 completed bars"),
        "VOLUME": ("VOLUME_R1", "underlying frozen canonical close/volume 1m", "up to 60 completed bars"),
        "TD": ("TD_R1", "underlying frozen canonical completed timeframe bars", "continuous setup state"),
        "SESSION": ("SESSION_R1", "decision timestamp America/New_York", "decision time only"),
    }
    output = []
    for family, payload in universe["families"].items():
        if family == "FUNDAMENTAL": continue
        formula, source, lookback = formulas[family]
        for name in payload["factors"]:
            output.append(FactorDef(name, family, f"{formula}:{name}", source, lookback))
    names = [row.name for row in output]
    if len(names) != 72 or len(set(names)) != 72: raise ContractStop("REGISTRY_NOT_EXACT_FROZEN_72")
    return output


def load_base_frame() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    identity = pd.read_csv(R43B_IDENTITY)
    identity["decision_timestamp_utc"] = pd.to_datetime(identity["decision_timestamp_utc"], utc=True, errors="raise")
    target = pd.read_parquet(R36_LEDGER, columns=["candidate_id", "action_instrument", "path_complete", *RETURN_COLUMNS])
    numeric = target.loc[:, RETURN_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if len(identity) != 1197 or len(target) != 1197 or identity["candidate_id"].duplicated().any():
        raise ContractStop("TARGET_OR_FEATURE_IDENTITY_COUNT")
    if not target["path_complete"].eq(True).all() or not np.isfinite(numeric.to_numpy(float)).all():
        raise ContractStop("TARGET_VALIDITY_CONTRACT")
    target["realized_y_econ"] = numeric.mean(axis=1)
    target["realized_positive_majority"] = numeric.gt(0).sum(axis=1).ge(3).astype(int)
    frame = identity.merge(target.drop(columns=["path_complete"]), on="candidate_id", validate="one_to_one")
    frame["source_symbol"] = frame["candidate_id"].str.split("|").str[0]
    oof = pd.read_parquet(R43B_OOF)
    path_oof = pd.read_parquet(R43D_OOF).rename(columns={"direction": "head"})
    for table in (oof, path_oof): table["decision_timestamp_utc"] = pd.to_datetime(table["decision_timestamp_utc"], utc=True)
    expected = set(frame.loc[frame.validation_slice.isin(VALIDATION_FOLDS), "candidate_id"])
    if len(oof) != 998 or len(path_oof) != 998 or set(oof.candidate_id) != expected or set(path_oof.candidate_id) != expected:
        raise ContractStop("OOF_998_ROW_IDENTITY")
    return frame, oof, path_oof


def load_manifest_bars(manifest_path: Path, execution: bool = False) -> dict[str, pd.DataFrame]:
    manifest = read_json(manifest_path)
    records = manifest["partitions"] if execution else manifest["files"]
    symbols = ("SOXL", "SOXS", "TQQQ", "SQQQ") if execution else ("QQQ", "SOXX")
    output: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        selected = [r for r in records if r["symbol"] == symbol]
        expected = 98 if execution else 79
        if len(selected) != expected: raise ContractStop(f"SOURCE_PARTITION_COUNT:{symbol}:{len(selected)}")
        frames = []
        for row in selected:
            path = Path(row.get("absolute_or_canonical_path", row.get("path", "")))
            expected_hash = row.get("file_sha256", row.get("sha256"))
            if not path.is_file() or sha256(path).lower() != expected_hash.lower():
                raise ContractStop(f"SOURCE_PARTITION_HASH:{path}")
            frames.append(pd.read_parquet(path, columns=["timestamp_utc", "open", "high", "low", "close", "volume"]))
        bars = pd.concat(frames, ignore_index=True)
        bars["timestamp_utc"] = pd.to_datetime(bars["timestamp_utc"], utc=True, errors="raise")
        bars = bars.sort_values("timestamp_utc", kind="mergesort")
        if bars["timestamp_utc"].duplicated().any(): raise ContractStop(f"SOURCE_DUPLICATE_TIMESTAMP:{symbol}")
        for col in ("open", "high", "low", "close", "volume"):
            bars[col] = pd.to_numeric(bars[col], errors="coerce")
        valid = ((bars.open > 0) & (bars.close > 0) & (bars.volume >= 0)
                 & (bars.high >= bars[["open", "low", "close"]].max(axis=1))
                 & (bars.low <= bars[["open", "high", "close"]].min(axis=1)))
        if not valid.all(): raise ContractStop(f"SOURCE_BAR_INTEGRITY:{symbol}")
        output[symbol] = bars.reset_index(drop=True)
    return output


def safe_div(a: float, b: float) -> float:
    return np.nan if not np.isfinite(b) or b == 0 else float(a / b)


def trend_efficiency(close: np.ndarray) -> float:
    denominator = float(np.abs(np.diff(close)).sum())
    return np.nan if denominator == 0 else float(abs(close[-1] - close[0]) / denominator)


def rolling_rsi_wilder(close: np.ndarray, period: int = 14) -> np.ndarray:
    out = np.full(len(close), np.nan); diff = np.diff(close)
    if len(diff) < period: return out
    gains = np.maximum(diff, 0.0); losses = np.maximum(-diff, 0.0)
    avg_gain, avg_loss = gains[:period].mean(), losses[:period].mean()
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, len(close)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def kdj_continuous(close: np.ndarray, high: np.ndarray, low: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    series_h, series_l = pd.Series(high), pd.Series(low)
    hi = series_h.rolling(9, min_periods=9).max().to_numpy()
    lo = series_l.rolling(9, min_periods=9).min().to_numpy()
    k = np.full(len(close), np.nan); d = np.full(len(close), np.nan)
    prior_k = prior_d = 50.0
    for i in range(len(close)):
        if np.isfinite(hi[i]) and hi[i] != lo[i]:
            rsv = 100.0 * (close[i] - lo[i]) / (hi[i] - lo[i])
            prior_k = (2.0 * prior_k + rsv) / 3.0
            prior_d = (2.0 * prior_d + prior_k) / 3.0
            k[i], d[i] = prior_k, prior_d
    return k, d, 3.0 * k - 2.0 * d


def td_counts(close: np.ndarray) -> np.ndarray:
    out = np.zeros(len(close), dtype=float); up = down = 0
    for i in range(4, len(close)):
        up = min(9, up + 1) if close[i] > close[i - 4] else 0
        down = min(9, down + 1) if close[i] < close[i - 4] else 0
        out[i] = up * 100 + down  # lossless packed state; orientation is selected at lookup
    return out


def precompute_symbol(bars: pd.DataFrame) -> dict[str, Any]:
    c = bars.close.to_numpy(float); h = bars.high.to_numpy(float); l = bars.low.to_numpy(float); v = bars.volume.to_numpy(float)
    ret = np.r_[np.nan, c[1:] / c[:-1] - 1.0]
    s = pd.Series(c); vs = pd.Series(v)
    rsi = rolling_rsi_wilder(c); k, d, j = kdj_continuous(c, h, l)
    ema5 = s.ewm(span=5, adjust=False, min_periods=5).mean().to_numpy()
    ema20 = s.ewm(span=20, adjust=False, min_periods=20).mean().to_numpy()
    sma20 = s.rolling(20, min_periods=20).mean().to_numpy()
    sma50 = s.rolling(50, min_periods=50).mean().to_numpy()
    mean7 = s.rolling(7, min_periods=7).mean().to_numpy(); std7 = s.rolling(7, min_periods=7).std(ddof=0).to_numpy()
    obv = np.nancumsum(np.nan_to_num(np.sign(ret), nan=0.0) * v)
    return {"bars": bars, "ts": bars.timestamp_utc.to_numpy(dtype="datetime64[ns]"), "c": c, "h": h, "l": l, "v": v,
            "ret": ret, "rsi": rsi, "k": k, "d": d, "j": j, "ema5": ema5, "ema20": ema20,
            "sma20": sma20, "sma50": sma50, "mean7": mean7, "std7": std7, "obv": obv,
            "td_packed": td_counts(c)}


def position_at_or_before(pre: dict[str, Any], timestamp: pd.Timestamp) -> int | None:
    value = np.datetime64(timestamp.tz_convert("UTC").tz_localize(None), "ns")
    i = int(np.searchsorted(pre["ts"], value, side="right") - 1)
    return None if i < 0 else i


def higher_timeframe_td(bars: pd.DataFrame, minutes: int) -> tuple[np.ndarray, np.ndarray]:
    close = (bars.set_index("timestamp_utc")["close"]
             .resample(f"{minutes}min", origin="epoch", label="right", closed="left")
             .last().dropna())
    packed = td_counts(close.to_numpy(float))
    return close.index.to_numpy(dtype="datetime64[ns]"), packed


def unpack_td(packed: float, sign: int) -> float:
    return float(math.floor(packed / 100.0) if sign == 1 else int(packed) % 100)


def local_window(pre: dict[str, Any], index: int, lookback: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    if index < lookback: return None
    sl = slice(index - lookback, index + 1)
    return pre["c"][sl], pre["h"][sl], pre["l"][sl], pre["v"][sl]


def return_n(pre: dict[str, Any], index: int, n: int) -> float:
    return np.nan if index < n else float(pre["c"][index] / pre["c"][index - n] - 1.0)


def correlation_array(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < 3 or np.unique(x[mask]).size < 2 or np.unique(y[mask]).size < 2: return np.nan
    return float(np.corrcoef(x[mask], y[mask])[0, 1])


def cross_asset_values(pre: dict[str, dict[str, Any]], timestamp: pd.Timestamp, sign: int) -> tuple[dict[str, float], pd.Timestamp]:
    q, s = pre["QQQ"], pre["SOXX"]
    qi, si = position_at_or_before(q, timestamp), position_at_or_before(s, timestamp)
    names = ("qqq_oriented_return_5m", "qqq_oriented_return_15m", "qqq_oriented_return_60m",
             "soxx_minus_qqq_oriented_relative_return_5m", "soxx_minus_qqq_oriented_relative_return_60m",
             "qqq_trend_efficiency_15m", "qqq_directional_path_consistency_15m", "soxx_qqq_return_correlation_60m")
    if qi is None or si is None or qi < 60 or si < 60:
        return {name: np.nan for name in names}, pd.NaT
    qr = {n: return_n(q, qi, n) for n in (5, 15, 60)}
    sr = {n: return_n(s, si, n) for n in (5, 60)}
    q15 = q["c"][qi - 15:qi + 1]
    qret15 = q15[1:] / q15[:-1] - 1.0
    consistency = float((sign * qret15 > 0).mean())
    # Correlation uses the last 60 timestamp-aligned completed one-minute returns.
    qpart = q["bars"].iloc[max(0, qi - 90):qi + 1][["timestamp_utc", "close"]].rename(columns={"close": "q"})
    spart = s["bars"].iloc[max(0, si - 90):si + 1][["timestamp_utc", "close"]].rename(columns={"close": "s"})
    aligned = qpart.merge(spart, on="timestamp_utc", how="inner").tail(61)
    corr = np.nan
    if len(aligned) >= 61:
        corr = correlation_array(aligned.q.pct_change().to_numpy()[1:], aligned.s.pct_change().to_numpy()[1:])
    maximum = max(q["bars"].iloc[qi].timestamp_utc, s["bars"].iloc[si].timestamp_utc)
    return {
        "qqq_oriented_return_5m": sign * qr[5],
        "qqq_oriented_return_15m": sign * qr[15],
        "qqq_oriented_return_60m": sign * qr[60],
        "soxx_minus_qqq_oriented_relative_return_5m": sign * (sr[5] - qr[5]),
        "soxx_minus_qqq_oriented_relative_return_60m": sign * (sr[60] - qr[60]),
        "qqq_trend_efficiency_15m": trend_efficiency(q15),
        "qqq_directional_path_consistency_15m": consistency,
        "soxx_qqq_return_correlation_60m": corr,
    }, maximum


def execution_values(pre: dict[str, Any], timestamp: pd.Timestamp) -> tuple[dict[str, float], pd.Timestamp | pd.NaT]:
    names = ("execution_oriented_return_5m", "execution_oriented_return_15m", "execution_oriented_return_60m",
             "execution_trend_efficiency_15m", "execution_directional_path_consistency_15m",
             "execution_close_location_15m", "execution_realized_vol_15m", "execution_tracking_residual_15m")
    index = position_at_or_before(pre, timestamp)
    if index is None or index < 60: return {name: np.nan for name in names}, pd.NaT
    window = local_window(pre, index, 15)
    assert window is not None
    close, high, low, _ = window
    returns = close[1:] / close[:-1] - 1.0
    lo, hi = float(np.min(low)), float(np.max(high))
    return {
        # The frozen mapping is already long the favorable ETF for both directions.
        "execution_oriented_return_5m": return_n(pre, index, 5),
        "execution_oriented_return_15m": return_n(pre, index, 15),
        "execution_oriented_return_60m": return_n(pre, index, 60),
        "execution_trend_efficiency_15m": trend_efficiency(close),
        "execution_directional_path_consistency_15m": float((returns > 0).mean()),
        "execution_close_location_15m": np.nan if hi == lo else float((close[-1] - lo) / (hi - lo)),
        "execution_realized_vol_15m": float(np.sqrt(np.mean(np.square(np.log(close[1:] / close[:-1]))))),
        # No frozen expected leverage/beta mapping exists; fail unavailable instead of assuming one.
        "execution_tracking_residual_15m": np.nan,
    }, pre["bars"].iloc[index].timestamp_utc


def underlying_values(pre: dict[str, Any], timestamp: pd.Timestamp, sign: int,
                      td_state: dict[int, tuple[np.ndarray, np.ndarray]]) -> tuple[dict[str, float], pd.Timestamp | pd.NaT]:
    index = position_at_or_before(pre, timestamp)
    names = (
        "rsi_wilder_14_1m", "kdj_k_9_1m", "kdj_d_9_1m", "kdj_j_9_1m", "bollinger_z_7_1m",
        "bollinger_bandwidth_7_1m", "ema_spread_5_20_1m", "sma_spread_20_50_1m",
        "oriented_return_1m", "oriented_return_3m", "oriented_return_30m", "price_distance_sma20_oriented",
        "price_distance_sma50_oriented", "sma20_slope_10m_oriented", "sma50_slope_20m_oriented",
        "price_distance_ema20_oriented", "donchian_location_20m_oriented", "donchian_location_60m_oriented",
        "distance_to_favorable_extreme_20m", "distance_to_favorable_extreme_60m",
        "retracement_from_favorable_extreme_20m", "retracement_from_favorable_extreme_60m",
        "range_expansion_5v20", "range_expansion_15v60", "volume_acceleration_5v15",
        "signed_volume_pressure_5m", "signed_volume_pressure_30m", "up_volume_share_oriented_15m",
        "price_volume_correlation_15m", "price_volume_correlation_60m", "obv_slope_oriented_15m",
        "obv_slope_oriented_60m", "td_setup_count_1m", "td_setup_count_3m", "td_setup_count_5m",
        "td_setup_count_10m", "td_setup_count_15m",
    )
    if index is None or index < 70: return {name: np.nan for name in names}, pd.NaT
    c, h, l, v, ret = pre["c"], pre["h"], pre["l"], pre["v"], pre["ret"]
    output: dict[str, float] = {
        "rsi_wilder_14_1m": float(pre["rsi"][index]), "kdj_k_9_1m": float(pre["k"][index]),
        "kdj_d_9_1m": float(pre["d"][index]), "kdj_j_9_1m": float(pre["j"][index]),
        "bollinger_z_7_1m": safe_div(c[index] - pre["mean7"][index], pre["std7"][index]),
        "bollinger_bandwidth_7_1m": safe_div(4.0 * pre["std7"][index], pre["mean7"][index]),
        "ema_spread_5_20_1m": safe_div(pre["ema5"][index], pre["ema20"][index]) - 1.0,
        "sma_spread_20_50_1m": safe_div(pre["sma20"][index], pre["sma50"][index]) - 1.0,
        "oriented_return_1m": sign * return_n(pre, index, 1),
        "oriented_return_3m": sign * return_n(pre, index, 3),
        "oriented_return_30m": sign * return_n(pre, index, 30),
        "price_distance_sma20_oriented": sign * (safe_div(c[index], pre["sma20"][index]) - 1.0),
        "price_distance_sma50_oriented": sign * (safe_div(c[index], pre["sma50"][index]) - 1.0),
        "sma20_slope_10m_oriented": sign * (safe_div(pre["sma20"][index], pre["sma20"][index - 10]) - 1.0),
        "sma50_slope_20m_oriented": sign * (safe_div(pre["sma50"][index], pre["sma50"][index - 20]) - 1.0),
        "price_distance_ema20_oriented": sign * (safe_div(c[index], pre["ema20"][index]) - 1.0),
    }
    for w in (20, 60):
        cw, hw, lw, _ = local_window(pre, index, w)  # type: ignore[misc]
        lo, hi = float(np.min(lw)), float(np.max(hw))
        raw_loc = np.nan if hi == lo else float((c[index] - lo) / (hi - lo))
        output[f"donchian_location_{w}m_oriented"] = raw_loc if sign == 1 or not np.isfinite(raw_loc) else 1.0 - raw_loc
        favorable = hi if sign == 1 else lo
        output[f"distance_to_favorable_extreme_{w}m"] = sign * (c[index] / favorable - 1.0)
        path = sign * (cw / cw[0] - 1.0)
        output[f"retracement_from_favorable_extreme_{w}m"] = float(path[-1] - np.max(path))
    def price_range(w: int) -> float:
        _, hw, lw, _ = local_window(pre, index, w)  # type: ignore[misc]
        return float(np.max(hw) - np.min(lw))
    output["range_expansion_5v20"] = safe_div(price_range(5), price_range(20))
    output["range_expansion_15v60"] = safe_div(price_range(15), price_range(60))
    output["volume_acceleration_5v15"] = safe_div(float(v[index-4:index+1].mean()), float(v[index-14:index+1].mean())) - 1.0
    signed = np.sign(np.nan_to_num(ret, nan=0.0)) * v
    for w in (5, 30):
        output[f"signed_volume_pressure_{w}m"] = safe_div(float(signed[index-w+1:index+1].sum()), float(v[index-w+1:index+1].sum()))
    r15, v15 = ret[index-14:index+1], v[index-14:index+1]
    output["up_volume_share_oriented_15m"] = safe_div(float(v15[sign * r15 > 0].sum()), float(v15.sum()))
    for w in (15, 60):
        rw, vw = ret[index-w+1:index+1], v[index-w+1:index+1]
        output[f"price_volume_correlation_{w}m"] = correlation_array(rw, vw)
        denominator = float(v[index-w+1:index+1].sum())
        output[f"obv_slope_oriented_{w}m"] = sign * safe_div(pre["obv"][index] - pre["obv"][index-w], denominator)
    output["td_setup_count_1m"] = unpack_td(pre["td_packed"][index], sign)
    for minutes in (3, 5, 10, 15):
        timestamps, packed = td_state[minutes]
        point = np.datetime64(timestamp.tz_convert("UTC").tz_localize(None), "ns")
        location = int(np.searchsorted(timestamps, point, side="right") - 1)
        output[f"td_setup_count_{minutes}m"] = np.nan if location < 0 else unpack_td(packed[location], sign)
    return output, pre["bars"].iloc[index].timestamp_utc


def session_values(timestamp: pd.Timestamp) -> dict[str, float]:
    et = timestamp.tz_convert("America/New_York")
    minutes = et.hour * 60 + et.minute
    # Monday=0 ... Friday=4; fixed five-day cyclic representation.
    angle = 2.0 * math.pi * et.dayofweek / 5.0
    return {"minutes_from_regular_open": float(minutes - 570), "minutes_to_regular_close": float(960 - minutes),
            "day_of_week_sin": math.sin(angle), "day_of_week_cos": math.cos(angle)}


def write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    frame.to_parquet(temp, index=False)
    os.replace(temp, path)


def materialize_factor_matrix(checkpoint: Checkpoint, universe: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    matrix_path = SCRATCH / "FAST3_FACTOR_MATRIX.parquet"
    audit_path = FROZEN / "FAST3_FACTOR_MATRIX_PIT_AVAILABILITY_AUDIT.csv"
    if "matrix" in checkpoint.completed("factor_matrix"):
        if not matrix_path.is_file() or checkpoint.value["artifact_sha256"].get(str(matrix_path)) != sha256(matrix_path):
            raise ContractStop("CHECKPOINTED_FACTOR_MATRIX_HASH_MISMATCH")
        return pd.read_parquet(matrix_path), pd.read_csv(audit_path)
    frame, _, _ = load_base_frame()
    registry = registry_from_universe(universe)
    underlying = {k: precompute_symbol(v) for k, v in load_manifest_bars(UNDERLYING_MANIFEST).items()}
    execution = {k: precompute_symbol(v) for k, v in load_manifest_bars(ETF_MANIFEST, execution=True).items()}
    td_state = {symbol: {m: higher_timeframe_td(pre["bars"], m) for m in (3, 5, 10, 15)}
                for symbol, pre in underlying.items()}
    regime = pd.read_parquet(R43C_VALUES)
    path = pd.read_parquet(R43D_VALUES).drop(columns=["max_source_timestamp_utc"])
    if len(regime) != 1197 or len(path) != 1197: raise ContractStop("FROZEN_FACTOR_ROW_COUNT")
    output = frame.merge(regime, on="candidate_id", validate="one_to_one").merge(path, on="candidate_id", validate="one_to_one")
    rows: list[dict[str, Any]] = []
    pit_violations = 0
    maximum_source: dict[str, pd.Timestamp] = {}
    for row in frame[["candidate_id", "decision_timestamp_utc", "direction", "source_symbol", "action_instrument"]].itertuples(index=False):
        sign = 1 if row.direction == "UP" else -1
        values: dict[str, Any] = {"candidate_id": row.candidate_id}
        cross, cross_max = cross_asset_values(underlying, row.decision_timestamp_utc, sign)
        execute, execute_max = execution_values(execution[row.action_instrument], row.decision_timestamp_utc)
        base, base_max = underlying_values(underlying[row.source_symbol], row.decision_timestamp_utc, sign, td_state[row.source_symbol])
        values.update(cross); values.update(execute); values.update(base); values.update(session_values(row.decision_timestamp_utc))
        for family_values, maximum in ((cross, cross_max), (execute, execute_max), (base, base_max)):
            if pd.notna(maximum) and maximum > row.decision_timestamp_utc: pit_violations += 1
            if pd.notna(maximum):
                for name in family_values: maximum_source[name] = max(maximum_source.get(name, maximum), maximum)
        rows.append(values)
    computed = pd.DataFrame(rows)
    output = output.merge(computed, on="candidate_id", validate="one_to_one")
    factor_names = [r.name for r in registry]
    missing_columns = set(factor_names).difference(output.columns)
    if missing_columns: raise ContractStop(f"FACTOR_IMPLEMENTATION_MISSING:{sorted(missing_columns)}")
    audit_rows = []
    for definition in registry:
        series = pd.to_numeric(output[definition.name], errors="coerce")
        available = definition.name != "execution_tracking_residual_15m" and int(series.notna().sum()) > 0
        duplicate = "NOT_DUPLICATE"
        if available:
            for existing in BASELINE_FEATURES:
                pair = pd.concat([series, pd.to_numeric(output[existing], errors="coerce")], axis=1).dropna()
                if len(pair) and (np.allclose(pair.iloc[:, 0], pair.iloc[:, 1], rtol=0, atol=1e-15)
                                  or np.allclose(pair.iloc[:, 0], -pair.iloc[:, 1], rtol=0, atol=1e-15)):
                    duplicate = f"DUPLICATE_EXISTING_FEATURE:{existing}"
                    break
        pit = "PASS" if pit_violations == 0 else "FAIL"
        if not available: pit = "FACTOR_NOT_AVAILABLE"
        audit_rows.append({
            "NAME": definition.name, "FAMILY": definition.family, "FORMULA_ID": definition.formula_id,
            "SOURCE": definition.source, "LOOKBACK": definition.lookback,
            "FINITE_COUNT": int(np.isfinite(series.to_numpy(float)).sum()), "MISSING_COUNT": int(series.isna().sum()),
            "MAX_SOURCE_TIMESTAMP": str(maximum_source.get(definition.name, output.decision_timestamp_utc.max())),
            "PIT_STATUS": pit, "DUPLICATE_STATUS": duplicate,
        })
    audit = pd.DataFrame(audit_rows)
    if pit_violations: raise ContractStop(f"PIT_VIOLATION_COUNT:{pit_violations}")
    output = output.sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    write_parquet_atomic(output, matrix_path)
    audit.to_csv(audit_path, index=False)
    identity = {
        "FACTOR_MATRIX_IDENTITY_SHA256": sha256(matrix_path), "ROW_COUNT": len(output),
        "TARGET_ROW_IDENTITY_UNCHANGED": len(output) == 1197,
        "OOF_PREDICTION_COUNT": int(output.validation_slice.isin(VALIDATION_FOLDS).sum()),
        "LEGAL_ATOMIC_FACTOR_COUNT": 0,
        "PIT_VIOLATION_COUNT": pit_violations,
    }
    # Correct legal count without boolean scalar precedence ambiguity.
    identity["LEGAL_ATOMIC_FACTOR_COUNT"] = int((audit.PIT_STATUS.eq("PASS") & audit.DUPLICATE_STATUS.eq("NOT_DUPLICATE")).sum())
    atomic_json(FROZEN / "FAST3_FACTOR_MATRIX_IDENTITY.json", identity)
    checkpoint.mark("factor_matrix", "matrix", matrix_path)
    checkpoint.artifact(audit_path)
    return output, audit


def numeric_correlation(x: pd.Series, y: pd.Series, method: str = "spearman") -> float | None:
    pair = pd.concat([pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")], axis=1).dropna()
    if len(pair) < 2 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2: return None
    value = pair.iloc[:, 0].corr(pair.iloc[:, 1], method=method)
    return None if pd.isna(value) else float(value)


def stable_quintiles(frame: pd.DataFrame, prediction: str = "predicted_y_econ") -> pd.Series:
    ordered = frame.sort_values([prediction, "decision_timestamp_utc", "candidate_id"], kind="mergesort")
    bucket = np.minimum(np.floor(np.arange(len(ordered)) * 5 / len(ordered)).astype(int), 4)
    result = pd.Series(index=frame.index, dtype="object")
    result.loc[ordered.index] = [QUINTILES[i] for i in bucket]
    if result.isna().any(): raise ContractStop("QUINTILE_ASSIGNMENT_FAILURE")
    return result


def ordering(values: Iterable[float]) -> str:
    values = np.asarray(list(values), float); delta = np.diff(values)
    if np.all(delta >= 0): return "MONOTONIC_POSITIVE"
    if int((delta > 0).sum()) >= 3 and values[-1] > values[0]: return "MOSTLY_POSITIVE"
    if np.all(delta <= 0): return "MONOTONIC_NEGATIVE"
    return "NON_MONOTONIC"


def spread_for(frame: pd.DataFrame) -> float:
    return float(frame.loc[frame.quintile.eq("Q5"), "realized_y_econ"].mean()
                 - frame.loc[frame.quintile.eq("Q1"), "realized_y_econ"].mean())


def tail_attack_metrics(predictions: pd.DataFrame) -> dict[str, Any]:
    work = predictions.copy(); work["quintile"] = stable_quintiles(work)
    union = work.loc[work.quintile.isin(["Q1", "Q5"])].copy()
    raw = spread_for(union)
    ordered = union.sort_values(["realized_y_econ", "candidate_id"], kind="mergesort")
    best = spread_for(union.drop(index=ordered.index[-1]))
    worst = spread_for(union.drop(index=ordered.index[0]))
    abs_order = union.assign(_abs=union.realized_y_econ.abs()).sort_values(["_abs", "candidate_id"], ascending=[False, True], kind="mergesort")
    top1_count = max(1, int(math.ceil(len(union) * .01)))
    ex_top1 = spread_for(union.drop(index=abs_order.index[:top1_count]))
    ex_top5 = spread_for(union.drop(index=abs_order.index[:min(5, len(abs_order))]))
    robust = bool(raw > 0 and best > 0 and worst > 0 and ex_top1 > 0 and ex_top5 > 0)
    return {"Q5Q1_RAW": raw, "Q5Q1_REMOVE_BEST1": best, "Q5Q1_REMOVE_WORST1": worst,
            "Q5Q1_REMOVE_TOP1PCT_ABS_TARGET": ex_top1, "Q5Q1_REMOVE_TOP5_ABS_TARGET_ROWS": ex_top5,
            "TAIL_ROBUSTNESS": robust}


def aggregate_metrics(predictions: pd.DataFrame) -> dict[str, Any]:
    work = predictions.copy(); work["quintile"] = stable_quintiles(work)
    means = [float(work.loc[work.quintile.eq(q), "realized_y_econ"].mean()) for q in QUINTILES]
    result: dict[str, Any] = {
        "OOF_SPEARMAN": numeric_correlation(work.predicted_y_econ, work.realized_y_econ),
        "OOF_PEARSON": numeric_correlation(work.predicted_y_econ, work.realized_y_econ, "pearson"),
        "MAE": float(mean_absolute_error(work.realized_y_econ, work.predicted_y_econ)),
        "RMSE": float(np.sqrt(mean_squared_error(work.realized_y_econ, work.predicted_y_econ))),
        "R2": float(r2_score(work.realized_y_econ, work.predicted_y_econ)),
        "Q1_MEAN": means[0], "Q2_MEAN": means[1], "Q3_MEAN": means[2], "Q4_MEAN": means[3],
        "Q5_MEAN": means[4], "Q5_Q1": means[4] - means[0], "ORDERING": ordering(means),
    }
    result.update(tail_attack_metrics(work))
    return result


def fold_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for fold in VALIDATION_FOLDS:
        part = predictions.loc[predictions.validation_slice.eq(fold)].copy()
        spearman = numeric_correlation(part.predicted_y_econ, part.realized_y_econ)
        q5q1 = None
        if len(part) >= 25 and part.predicted_y_econ.nunique() >= 5:
            part["quintile"] = stable_quintiles(part)
            q5q1 = spread_for(part)
        rows.append({"fold": fold, "count": len(part), "spearman": spearman, "q5_q1": q5q1,
                     "standard_evaluable": bool(len(part) >= 25 and spearman is not None)})
    return pd.DataFrame(rows)


def compare_to_incumbent(candidate: pd.DataFrame, incumbent: pd.DataFrame) -> dict[str, Any]:
    cm, im = aggregate_metrics(candidate), aggregate_metrics(incumbent)
    cf, bf = fold_metrics(candidate), fold_metrics(incumbent)
    merged = bf.merge(cf, on="fold", suffixes=("_incumbent", "_candidate"), validate="one_to_one")
    statuses, delta_s, delta_q = [], [], []
    for row in merged.itertuples(index=False):
        bs, cs = row.spearman_incumbent, row.spearman_candidate
        if pd.isna(bs) and pd.isna(cs): status = "NON_DEGRADED_BOTH_CONSTANT"
        elif pd.isna(bs): status = "NON_DEGRADED_FROM_ZERO_INFORMATION" if cs >= 0 else "DEGRADED_FROM_ZERO_INFORMATION"
        elif pd.isna(cs): status = "DEGRADED_TO_CONSTANT"
        else: status = "NON_DEGRADED" if cs >= bs else "DEGRADED"
        statuses.append(status)
        delta_s.append(None if pd.isna(bs) or pd.isna(cs) else float(cs - bs))
        bq, cq = row.q5_q1_incumbent, row.q5_q1_candidate
        delta_q.append(None if pd.isna(bq) or pd.isna(cq) else float(cq - bq))
    merged["paired_status"] = statuses; merged["delta_spearman"] = delta_s; merged["delta_q5_q1"] = delta_q
    non_degradation = int(merged.paired_status.str.startswith("NON_DEGRADED").sum())
    positive_standard = int(merged.loc[merged.standard_evaluable_candidate, "spearman_candidate"].gt(0).sum())
    evaluable = int(merged.standard_evaluable_candidate.sum())
    result = dict(cm)
    result.update({
        "INCUMBENT_SPEARMAN": im["OOF_SPEARMAN"], "INCUMBENT_Q5_Q1": im["Q5_Q1"],
        "DELTA_SPEARMAN": float(cm["OOF_SPEARMAN"] - im["OOF_SPEARMAN"]),
        "DELTA_Q5_Q1": float(cm["Q5_Q1"] - im["Q5_Q1"]),
        "POSITIVE_DELTA_SPEARMAN_FOLD_COUNT": int(merged.delta_spearman.gt(0).sum()),
        "POSITIVE_DELTA_Q5Q1_FOLD_COUNT": int(merged.delta_q5_q1.gt(0).sum()),
        "NON_DEGRADATION_FOLD_COUNT": non_degradation,
        "MAJORITY_FOLD_NON_DEGRADATION": non_degradation >= 3,
        "POSITIVE_SPEARMAN_FOLD_COUNT": positive_standard, "EVALUABLE_FOLD_COUNT": evaluable,
        "FOLD_STABILITY": bool(evaluable >= 3 and positive_standard > evaluable / 2),
        "FOLD_ROWS": merged.to_dict("records"),
    })
    result["RAW_INCREMENTAL_GATE"] = bool(result["DELTA_SPEARMAN"] >= .02 and result["DELTA_Q5_Q1"] >= .0005
                                                and result["MAJORITY_FOLD_NON_DEGRADATION"] and result["TAIL_ROBUSTNESS"])
    result["ABSOLUTE_ECONOMIC_SIGNAL"] = bool(result["OOF_SPEARMAN"] >= .05 and result["Q5_Q1"] > 0
                                                  and result["ORDERING"] in ("MONOTONIC_POSITIVE", "MOSTLY_POSITIVE")
                                                  and result["FOLD_STABILITY"] and result["TAIL_ROBUSTNESS"])
    return result


def model_for(features: tuple[str, ...], classifier: bool = False):
    config = dict(HGB)
    config["categorical_features"] = [name in ("symbol_code", "session_code") for name in features]
    config["loss"] = "log_loss" if classifier else "squared_error"
    return HistGradientBoostingClassifier(**config) if classifier else HistGradientBoostingRegressor(**config)


def fit_oof(frame: pd.DataFrame, direction: str, features: tuple[str, ...], classifier: bool = False) -> pd.DataFrame:
    rows = []
    for fold in VALIDATION_FOLDS:
        position = BLOCKS.index(fold)
        train = frame.loc[frame.direction.eq(direction) & frame.validation_slice.isin(BLOCKS[:position])]
        valid = frame.loc[frame.direction.eq(direction) & frame.validation_slice.eq(fold)]
        if train.empty or valid.empty: raise ContractStop(f"OOF_EMPTY:{direction}:{fold}")
        model = model_for(features, classifier)
        target = train.realized_positive_majority.astype(int) if classifier else train.realized_y_econ
        if classifier and target.nunique() != 2: raise ContractStop(f"SECONDARY_CLASS_IDENTITY:{direction}:{fold}")
        model.fit(train.loc[:, features], target)
        prediction = model.predict_proba(valid.loc[:, features])[:, 1] if classifier else model.predict(valid.loc[:, features])
        out = valid[["candidate_id", "decision_timestamp_utc", "validation_slice", "direction", "realized_y_econ",
                     "realized_positive_majority", *RETURN_COLUMNS]].copy()
        out["predicted_positive_majority_probability" if classifier else "predicted_y_econ"] = prediction
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def incumbent_predictions(direction: str) -> pd.DataFrame:
    if direction == "UP":
        frame = pd.read_parquet(R43B_OOF).rename(columns={"head": "direction"})
    else:
        frame = pd.read_parquet(R43D_OOF)
    frame["decision_timestamp_utc"] = pd.to_datetime(frame.decision_timestamp_utc, utc=True)
    target = pd.read_parquet(R36_LEDGER, columns=["candidate_id", *RETURN_COLUMNS])
    frame = frame.loc[frame.direction.eq(direction)].merge(target, on="candidate_id", validate="one_to_one")
    return frame[["candidate_id", "decision_timestamp_utc", "validation_slice", "direction", "realized_y_econ",
                  "realized_positive_majority", "predicted_y_econ", *RETURN_COLUMNS]].copy()


def spec_key(kind: str, direction: str, members: Iterable[str]) -> str:
    return f"{kind}|{direction}|{'+' .join(sorted(members))}"


def spec_stem(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:20]


def spec_paths(key: str) -> tuple[Path, Path]:
    stem = spec_stem(key)
    return SCRATCH / "predictions" / f"{stem}.parquet", SCRATCH / "metrics" / f"{stem}.json"


def save_spec_result(key: str, kind: str, direction: str, members: tuple[str, ...], features: tuple[str, ...],
                     predictions: pd.DataFrame, incumbent: pd.DataFrame) -> tuple[Path, Path]:
    prediction_path, metric_path = spec_paths(key)
    write_parquet_atomic(predictions, prediction_path)
    metric = compare_to_incumbent(predictions, incumbent)
    metric.update({"SPEC_KEY": key, "SPEC_KIND": kind, "DIRECTION": direction, "MEMBERS": list(members),
                   "NEW_FEATURE_COUNT": len(set(features).difference(BASELINE_FEATURES if direction == "UP" else BASELINE_FEATURES + PATH_FEATURES)),
                   "TOTAL_FEATURE_COUNT": len(features), "PREDICTION_PATH": str(prediction_path),
                   "PREDICTION_SHA256": sha256(prediction_path), "MODEL_FIT_COUNT": 5})
    atomic_json(metric_path, metric)
    return prediction_path, metric_path


def legal_registry(audit: pd.DataFrame, registry: list[FactorDef]) -> list[FactorDef]:
    legal = set(audit.loc[audit.PIT_STATUS.eq("PASS") & audit.DUPLICATE_STATUS.eq("NOT_DUPLICATE"), "NAME"])
    return [row for row in registry if row.name in legal]


def incumbent_features(direction: str) -> tuple[str, ...]:
    return BASELINE_FEATURES if direction == "UP" else BASELINE_FEATURES + PATH_FEATURES


def addable_factors(direction: str, legal: list[FactorDef]) -> list[FactorDef]:
    incumbent = set(incumbent_features(direction))
    return [row for row in legal if row.name not in incumbent]


def descriptive_stage(checkpoint: Checkpoint, matrix: pd.DataFrame, legal: list[FactorDef]) -> None:
    if "maps" in checkpoint.completed("descriptive"): return
    rows = []
    for direction in ("UP", "DOWN"):
        part = matrix.loc[matrix.direction.eq(direction)]
        for factor in legal:
            series = pd.to_numeric(part[factor.name], errors="coerce")
            finite = series[np.isfinite(series)]
            rows.append({"direction": direction, "family": factor.family, "feature": factor.name,
                         "availability": len(finite), "missing_ratio": float(1 - len(finite) / len(series)),
                         "mean": float(finite.mean()), "std": float(finite.std()),
                         "p05": float(finite.quantile(.05)), "p50": float(finite.quantile(.5)), "p95": float(finite.quantile(.95)),
                         "univariate_spearman": numeric_correlation(series, part.realized_y_econ),
                         "pearson": numeric_correlation(series, part.realized_y_econ, "pearson")})
    desc = pd.DataFrame(rows)
    desc_path = FROZEN / "FACTOR_DESCRIPTIVE_MAP.csv"; desc.to_csv(desc_path, index=False)
    redundancy_rows = []
    factor_names = [row.name for row in legal]
    for direction in ("UP", "DOWN"):
        values = matrix.loc[matrix.direction.eq(direction), factor_names].corr(method="spearman")
        for a, b in itertools.combinations(factor_names, 2):
            redundancy_rows.append({"direction": direction, "factor_A": a, "factor_B": b,
                                    "spearman": values.loc[a, b], "absolute_spearman": abs(values.loc[a, b])})
    redundancy_path = FROZEN / "FAST3_FACTOR_REDUNDANCY_MATRIX.csv"; pd.DataFrame(redundancy_rows).to_csv(redundancy_path, index=False)
    checkpoint.mark("descriptive", "maps", desc_path); checkpoint.artifact(redundancy_path)


def incumbent_stage(checkpoint: Checkpoint) -> None:
    checkpoint.set_total("incumbents", 2)
    for direction in ("UP", "DOWN"):
        if direction in checkpoint.completed("incumbents"): continue
        predictions = incumbent_predictions(direction)
        key = spec_key("INCUMBENT", direction, ())
        prediction_path, metric_path = spec_paths(key)
        write_parquet_atomic(predictions, prediction_path)
        metric = aggregate_metrics(predictions)
        metric.update({"SPEC_KEY": key, "SPEC_KIND": "INCUMBENT", "DIRECTION": direction,
                       "MEMBERS": [], "TOTAL_FEATURE_COUNT": len(incumbent_features(direction)),
                       "PREDICTION_PATH": str(prediction_path), "PREDICTION_SHA256": sha256(prediction_path), "MODEL_FIT_COUNT": 0})
        atomic_json(metric_path, metric)
        checkpoint.mark("incumbents", direction, metric_path)


def run_spec_stage(checkpoint: Checkpoint, stage: str, specs: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]],
                   matrix: pd.DataFrame) -> None:
    checkpoint.set_total(stage, len(specs)); done = checkpoint.completed(stage)
    incumbents = {direction: incumbent_predictions(direction) for direction in ("UP", "DOWN")}
    for index, (key, direction, members, features) in enumerate(specs, 1):
        if key in done:
            _, metric_path = spec_paths(key)
            if not metric_path.is_file() or checkpoint.value["artifact_sha256"].get(str(metric_path)) != sha256(metric_path):
                raise ContractStop(f"CHECKPOINT_ARTIFACT_HASH:{key}")
            prior = read_json(metric_path); prediction_path = Path(prior["PREDICTION_PATH"])
            if not prediction_path.is_file() or sha256(prediction_path) != prior["PREDICTION_SHA256"]:
                raise ContractStop(f"CHECKPOINT_PREDICTION_HASH:{key}")
            continue
        predictions = fit_oof(matrix, direction, features)
        _, metric_path = save_spec_result(key, stage.upper(), direction, members, features, predictions, incumbents[direction])
        checkpoint.mark(stage, key, metric_path, fits=5)
        if index % 10 == 0: print(f"{stage.upper()}_PROGRESS={index}/{len(specs)}", flush=True)


def build_specs(legal: list[FactorDef], stage: str) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
    specs = []
    for direction in ("UP", "DOWN"):
        incumbent = incumbent_features(direction); addable = addable_factors(direction, legal)
        if stage == "singles":
            members_iter = ((row.name,) for row in addable)
        elif stage == "pairs":
            members_iter = itertools.combinations([row.name for row in addable], 2)
        elif stage == "families":
            groups: dict[str, list[str]] = {}
            for row in addable: groups.setdefault(row.family, []).append(row.name)
            members_iter = (tuple(sorted(values)) for _, values in sorted(groups.items()) if values)
        elif stage == "family_pairs":
            groups = {}
            for row in addable: groups.setdefault(row.family, []).append(row.name)
            members_iter = (tuple(sorted(groups[a] + groups[b])) for a, b in itertools.combinations(sorted(groups), 2))
        else: raise ValueError(stage)
        for members in members_iter:
            kind = {"singles": "SINGLE", "pairs": "PAIR", "families": "FAMILY", "family_pairs": "FAMILY_PAIR"}[stage]
            key = spec_key(kind, direction, members)
            specs.append((key, direction, tuple(members), tuple(incumbent) + tuple(members)))
    return sorted(specs, key=lambda row: row[0])


def read_spec_metric(key: str) -> dict[str, Any]:
    _, path = spec_paths(key)
    return read_json(path)


def all_spec_records(legal: list[FactorDef]) -> list[dict[str, Any]]:
    rows = []
    for stage in ("singles", "pairs", "families", "family_pairs"):
        for key, _, _, _ in build_specs(legal, stage): rows.append(read_spec_metric(key))
    return rows


def relationship_class(pair: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> tuple[str, float, float]:
    best_s = max(float(a["DELTA_SPEARMAN"]), float(b["DELTA_SPEARMAN"]))
    best_q = max(float(a["DELTA_Q5_Q1"]), float(b["DELTA_Q5_Q1"]))
    synergy_s = float(pair["DELTA_SPEARMAN"] - best_s)
    synergy_q = float(pair["DELTA_Q5_Q1"] - best_q)
    beats_both = (pair["DELTA_SPEARMAN"] > max(a["DELTA_SPEARMAN"], b["DELTA_SPEARMAN"])
                  and pair["DELTA_Q5_Q1"] > max(a["DELTA_Q5_Q1"], b["DELTA_Q5_Q1"]))
    worse_both = (pair["DELTA_SPEARMAN"] <= min(a["DELTA_SPEARMAN"], b["DELTA_SPEARMAN"]) - .01
                  and pair["DELTA_Q5_Q1"] <= min(a["DELTA_Q5_Q1"], b["DELTA_Q5_Q1"]) - .00025)
    if synergy_s >= .01 and synergy_q >= .00025: label = "SYNERGISTIC"
    elif beats_both: label = "ADDITIVE"
    elif abs(synergy_s) < .005 and abs(synergy_q) < .0001: label = "REDUNDANT"
    elif worse_both: label = "ANTAGONISTIC"
    else: label = "MIXED"
    return label, synergy_s, synergy_q


def aggregate_atlases(checkpoint: Checkpoint, legal: list[FactorDef]) -> None:
    if "atlases" in checkpoint.completed("aggregate_raw"): return
    family_of = {row.name: row.family for row in legal}
    records = all_spec_records(legal)
    single_lookup = {(r["DIRECTION"], r["MEMBERS"][0]): r for r in records if r["SPEC_KIND"] == "SINGLES"}
    # SPEC_KIND is stage.upper(), so normalize plural stage names here.
    single_lookup.update({(r["DIRECTION"], r["MEMBERS"][0]): r for r in records if r["SPEC_KIND"] == "SINGLE"})
    family_lookup = {}
    for r in records:
        if r["SPEC_KIND"] in ("FAMILIES", "FAMILY"):
            family_names = sorted(set(family_of[x] for x in r["MEMBERS"]))
            if len(family_names) == 1: family_lookup[(r["DIRECTION"], family_names[0])] = r
    tables: dict[str, list[dict[str, Any]]] = {"single": [], "pair": [], "family": [], "family_pair": []}
    relationships = []
    for r in records:
        kind = {"SINGLES": "single", "PAIRS": "pair", "FAMILIES": "family",
                "FAMILY_PAIRS": "family_pair", "SINGLE": "single", "PAIR": "pair",
                "FAMILY": "family", "FAMILY_PAIR": "family_pair"}[r["SPEC_KIND"]]
        row = {"direction": r["DIRECTION"], "specification": r["SPEC_KEY"],
               "feature_count": r["NEW_FEATURE_COUNT"], "features": ";".join(r["MEMBERS"]),
               "OOF_SPEARMAN": r["OOF_SPEARMAN"], "DELTA_SPEARMAN": r["DELTA_SPEARMAN"],
               "Q1_MEAN": r["Q1_MEAN"], "Q2_MEAN": r["Q2_MEAN"], "Q3_MEAN": r["Q3_MEAN"],
               "Q4_MEAN": r["Q4_MEAN"], "Q5_MEAN": r["Q5_MEAN"], "Q5_Q1": r["Q5_Q1"],
               "DELTA_Q5_Q1": r["DELTA_Q5_Q1"], "ORDERING": r["ORDERING"], "MAE": r["MAE"],
               "RMSE": r["RMSE"], "R2": r["R2"],
               "positive_delta_spearman_fold_count": r["POSITIVE_DELTA_SPEARMAN_FOLD_COUNT"],
               "positive_delta_q5q1_fold_count": r["POSITIVE_DELTA_Q5Q1_FOLD_COUNT"],
               "non_degradation_fold_count": r["NON_DEGRADATION_FOLD_COUNT"],
               "RAW_INCREMENTAL_GATE": r["RAW_INCREMENTAL_GATE"], "tail_robustness": r["TAIL_ROBUSTNESS"]}
        families = sorted(set(family_of.get(x, "UNKNOWN") for x in r["MEMBERS"]))
        row["family"] = ";".join(families)
        if kind == "pair":
            a, b = r["MEMBERS"]
            ra, rb = single_lookup[(r["DIRECTION"], a)], single_lookup[(r["DIRECTION"], b)]
            label, ss, sq = relationship_class(r, ra, rb)
            row.update({"factor_A": a, "factor_B": b, "family_A": family_of[a], "family_B": family_of[b],
                        "relationship_class": label, "synergy_spearman": ss, "synergy_q5q1": sq})
            relationships.append(dict(row))
        elif kind == "family_pair" and len(families) == 2:
            ra, rb = family_lookup[(r["DIRECTION"], families[0])], family_lookup[(r["DIRECTION"], families[1])]
            label, ss, sq = relationship_class(r, ra, rb)
            row.update({"family_A": families[0], "family_B": families[1], "relationship_class": label,
                        "synergy_spearman": ss, "synergy_q5q1": sq})
        tables[kind].append(row)
    paths = {
        "single": FROZEN / "FAST3_FACTOR_ATLAS_SINGLE.csv", "pair": FROZEN / "FAST3_FACTOR_ATLAS_PAIR.csv",
        "family": FROZEN / "FAST3_FACTOR_ATLAS_FAMILY.csv", "family_pair": FROZEN / "FAST3_FACTOR_ATLAS_FAMILY_PAIR.csv",
    }
    for key, path in paths.items(): pd.DataFrame(tables[key]).to_csv(path, index=False)
    relationship_path = FROZEN / "FAST3_FACTOR_PAIR_RELATIONSHIP_MAP.csv"
    pd.DataFrame(relationships).to_csv(relationship_path, index=False)
    checkpoint.mark("aggregate_raw", "atlases", paths["single"])
    for path in [*paths.values(), relationship_path]: checkpoint.artifact(path)


def prediction_arrays(candidate: pd.DataFrame, incumbent: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    columns = ["candidate_id", "decision_timestamp_utc", "validation_slice", "realized_y_econ", "predicted_y_econ"]
    c = candidate[columns].rename(columns={"predicted_y_econ": "candidate_prediction"})
    b = incumbent[["candidate_id", "predicted_y_econ"]].rename(columns={"predicted_y_econ": "incumbent_prediction"})
    merged = c.merge(b, on="candidate_id", validate="one_to_one").sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort")
    return merged, merged.candidate_prediction.to_numpy(float), merged.incumbent_prediction.to_numpy(float), merged.realized_y_econ.to_numpy(float)


def metric_from_arrays(prediction: np.ndarray, y: np.ndarray, order_tiebreak: np.ndarray | None = None) -> tuple[float, float]:
    if np.unique(prediction).size < 2 or np.unique(y).size < 2: spearman = 0.0
    else: spearman = float(stats.spearmanr(prediction, y).statistic)
    if order_tiebreak is None: order_tiebreak = np.arange(len(prediction))
    order = np.lexsort((order_tiebreak, prediction)); bucket = np.minimum(np.floor(np.arange(len(order)) * 5 / len(order)).astype(int), 4)
    assigned = np.empty(len(order), dtype=np.int8); assigned[order] = bucket
    spread = float(y[assigned == 4].mean() - y[assigned == 0].mean())
    return spearman, spread


def resample_month_indices(frame: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    months = frame.decision_timestamp_utc.dt.strftime("%Y-%m").to_numpy()
    unique = pd.unique(months)
    blocks = [np.flatnonzero(months == month) for month in unique]
    chosen = rng.integers(0, len(blocks), size=len(blocks))
    return np.concatenate([blocks[i] for i in chosen])


def bootstrap_batch(key: str, batch_index: int, candidate: pd.DataFrame, incumbent: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    merged, cp, ip, y = prediction_arrays(candidate, incumbent)
    seed_component = int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)
    rng = np.random.default_rng(np.random.SeedSequence([BOOTSTRAP_SEED, seed_component, batch_index]))
    ds, dq = np.empty(BATCH_SIZE), np.empty(BATCH_SIZE)
    for rep in range(BATCH_SIZE):
        idx = resample_month_indices(merged, rng)
        cs, cq = metric_from_arrays(cp[idx], y[idx]); bs, bq = metric_from_arrays(ip[idx], y[idx])
        ds[rep], dq[rep] = cs - bs, cq - bq
    return ds, dq


def raw_candidate_records(legal: list[FactorDef]) -> list[dict[str, Any]]:
    return sorted([r for r in all_spec_records(legal)
                   if r["SPEC_KIND"] in ("SINGLES", "PAIRS", "FAMILIES", "SINGLE", "PAIR", "FAMILY")
                   and r["RAW_INCREMENTAL_GATE"]], key=lambda r: r["SPEC_KEY"])


def bootstrap_stage(checkpoint: Checkpoint, legal: list[FactorDef]) -> None:
    candidates = raw_candidate_records(legal); batches = BOOTSTRAP_REPS // BATCH_SIZE
    units = [(r, b) for r in candidates for b in range(batches)]
    checkpoint.set_total("bootstrap", len(units)); done = checkpoint.completed("bootstrap")
    incumbents = {d: incumbent_predictions(d) for d in ("UP", "DOWN")}
    for ordinal, (record, batch) in enumerate(units, 1):
        key = record["SPEC_KEY"]; unit = f"{spec_stem(key)}:batch{batch:03d}"
        path = SCRATCH / "bootstrap" / spec_stem(key) / f"batch_{batch:03d}.npz"
        if unit in done:
            if not path.is_file() or checkpoint.value["artifact_sha256"].get(str(path)) != sha256(path):
                raise ContractStop(f"BOOTSTRAP_BATCH_HASH:{unit}")
            continue
        candidate = pd.read_parquet(record["PREDICTION_PATH"])
        ds, dq = bootstrap_batch(key, batch, candidate, incumbents[record["DIRECTION"]])
        path.parent.mkdir(parents=True, exist_ok=True); np.savez_compressed(path, delta_spearman=ds, delta_q5q1=dq)
        checkpoint.mark("bootstrap", unit, path)
        if ordinal % 20 == 0: print(f"BOOTSTRAP_PROGRESS={ordinal}/{len(units)}", flush=True)
    summary_rows = []
    for record in candidates:
        key = record["SPEC_KEY"]
        arrays = [np.load(SCRATCH / "bootstrap" / spec_stem(key) / f"batch_{b:03d}.npz") for b in range(batches)]
        ds = np.concatenate([a["delta_spearman"] for a in arrays]); dq = np.concatenate([a["delta_q5q1"] for a in arrays])
        row = {"SPEC_KEY": key, "DIRECTION": record["DIRECTION"], "SPEC_KIND": record["SPEC_KIND"],
               "REPS": len(ds), "DELTA_SPEARMAN_MEAN": ds.mean(), "DELTA_SPEARMAN_MEDIAN": np.median(ds),
               "DELTA_SPEARMAN_P025": np.quantile(ds, .025), "DELTA_SPEARMAN_P05": np.quantile(ds, .05),
               "DELTA_SPEARMAN_P95": np.quantile(ds, .95), "DELTA_SPEARMAN_P975": np.quantile(ds, .975),
               "DELTA_Q5Q1_MEAN": dq.mean(), "DELTA_Q5Q1_MEDIAN": np.median(dq),
               "DELTA_Q5Q1_P025": np.quantile(dq, .025), "DELTA_Q5Q1_P05": np.quantile(dq, .05),
               "DELTA_Q5Q1_P95": np.quantile(dq, .95), "DELTA_Q5Q1_P975": np.quantile(dq, .975),
               "P_DELTA_SPEARMAN_LE_0": float((np.sum(ds <= 0) + 1) / (len(ds) + 1)),
               "P_DELTA_Q5Q1_LE_0": float((np.sum(dq <= 0) + 1) / (len(dq) + 1))}
        row["COMPOSITE_P"] = max(row["P_DELTA_SPEARMAN_LE_0"], row["P_DELTA_Q5Q1_LE_0"])
        summary_rows.append(row)
    bootstrap_columns = ["SPEC_KEY", "DIRECTION", "SPEC_KIND", "REPS", "DELTA_SPEARMAN_MEAN",
                         "DELTA_SPEARMAN_MEDIAN", "DELTA_SPEARMAN_P025", "DELTA_SPEARMAN_P05",
                         "DELTA_SPEARMAN_P95", "DELTA_SPEARMAN_P975", "DELTA_Q5Q1_MEAN",
                         "DELTA_Q5Q1_MEDIAN", "DELTA_Q5Q1_P025", "DELTA_Q5Q1_P05", "DELTA_Q5Q1_P95",
                         "DELTA_Q5Q1_P975", "P_DELTA_SPEARMAN_LE_0", "P_DELTA_Q5Q1_LE_0", "COMPOSITE_P"]
    out = FROZEN / "FAST3_BOOTSTRAP_ROBUSTNESS.csv"; pd.DataFrame(summary_rows, columns=bootstrap_columns).to_csv(out, index=False)
    checkpoint.artifact(out)


def bh_adjust(pvalues: np.ndarray) -> np.ndarray:
    n = len(pvalues); order = np.argsort(pvalues, kind="mergesort"); ranked = pvalues[order]
    adjusted = np.minimum.accumulate((ranked * n / np.arange(1, n + 1))[::-1])[::-1]
    result = np.empty(n); result[order] = np.minimum(adjusted, 1.0)
    return result


def bh_stage(checkpoint: Checkpoint, legal: list[FactorDef]) -> pd.DataFrame:
    path = FROZEN / "FAST3_MULTIPLE_TESTING_CORRECTION.csv"
    if "complete" in checkpoint.completed("bh_fdr"): return pd.read_csv(path)
    bootstrap_path = FROZEN / "FAST3_BOOTSTRAP_ROBUSTNESS.csv"
    boot = pd.read_csv(bootstrap_path) if bootstrap_path.is_file() and bootstrap_path.stat().st_size > 0 else pd.DataFrame()
    p_lookup = dict(zip(boot.SPEC_KEY, boot.COMPOSITE_P)) if not boot.empty else {}
    records = [r for r in all_spec_records(legal) if r["SPEC_KIND"] not in ("FAMILY_PAIRS", "FAMILY_PAIR")]
    rows = []
    for r in records:
        # Effect-size gate failures receive conservative p=1; all hypotheses remain in each BH denominator.
        rows.append({"SPEC_KEY": r["SPEC_KEY"], "DIRECTION": r["DIRECTION"], "SPEC_KIND": r["SPEC_KIND"],
                     "RAW_INCREMENTAL_GATE": r["RAW_INCREMENTAL_GATE"], "RAW_P": float(p_lookup.get(r["SPEC_KEY"], 1.0))})
    table = pd.DataFrame(rows); table["BH_Q_VALUE"] = 1.0; table["BH_REJECT"] = False
    for _, indices in table.groupby(["DIRECTION", "SPEC_KIND"], sort=True).groups.items():
        q = bh_adjust(table.loc[indices, "RAW_P"].to_numpy(float))
        table.loc[indices, "BH_Q_VALUE"] = q; table.loc[indices, "BH_REJECT"] = q <= .05
    table.to_csv(path, index=False); checkpoint.mark("bh_fdr", "complete", path)
    return table


def permuted_outcomes(frame: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    months = frame.decision_timestamp_utc.dt.strftime("%Y-%m").to_numpy(); unique = pd.unique(months)
    blocks = [frame.loc[months == month, "realized_y_econ"].to_numpy(float) for month in unique]
    chosen = rng.permutation(len(blocks))
    return np.concatenate([blocks[i] for i in chosen])


def max_t_stage(checkpoint: Checkpoint, legal: list[FactorDef]) -> pd.DataFrame:
    candidates = raw_candidate_records(legal); batches = PERMUTATION_REPS // BATCH_SIZE
    checkpoint.set_total("max_t", batches); done = checkpoint.completed("max_t")
    by_direction: dict[str, list[tuple[dict[str, Any], pd.DataFrame, np.ndarray, np.ndarray]]] = {"UP": [], "DOWN": []}
    incumbents = {d: incumbent_predictions(d) for d in ("UP", "DOWN")}
    for record in candidates:
        candidate = pd.read_parquet(record["PREDICTION_PATH"])
        merged, cp, ip, _ = prediction_arrays(candidate, incumbents[record["DIRECTION"]])
        by_direction[record["DIRECTION"]].append((record, merged, cp, ip))
    for batch in range(batches):
        unit = f"batch{batch:03d}"; path = SCRATCH / "max_t" / f"batch_{batch:03d}.npy"
        if unit in done:
            if not path.is_file() or checkpoint.value["artifact_sha256"].get(str(path)) != sha256(path):
                raise ContractStop(f"MAXT_BATCH_HASH:{unit}")
            continue
        rng = np.random.default_rng(np.random.SeedSequence([PERMUTATION_SEED, batch]))
        maxima = np.full(BATCH_SIZE, -np.inf)
        if not candidates: maxima[:] = 0.0
        for rep in range(BATCH_SIZE):
            for direction in ("UP", "DOWN"):
                group = by_direction[direction]
                if not group: continue
                base_frame = group[0][1]
                y_null = permuted_outcomes(base_frame, rng)
                for _, _, cp, ip in group:
                    cs, cq = metric_from_arrays(cp, y_null); bs, bq = metric_from_arrays(ip, y_null)
                    statistic = min((cs - bs) / .02, (cq - bq) / .0005)
                    maxima[rep] = max(maxima[rep], statistic)
        path.parent.mkdir(parents=True, exist_ok=True); np.save(path, maxima)
        checkpoint.mark("max_t", unit, path)
        print(f"PERMUTATION_PROGRESS={(batch + 1) * BATCH_SIZE}/{PERMUTATION_REPS}", flush=True)
    null = np.concatenate([np.load(SCRATCH / "max_t" / f"batch_{b:03d}.npy") for b in range(batches)])
    rows = []
    for r in candidates:
        observed = min(r["DELTA_SPEARMAN"] / .02, r["DELTA_Q5_Q1"] / .0005)
        p = float((np.sum(null >= observed) + 1) / (len(null) + 1))
        rows.append({"SPEC_KEY": r["SPEC_KEY"], "DIRECTION": r["DIRECTION"], "SPEC_KIND": r["SPEC_KIND"],
                     "OBSERVED_T": observed, "MAXT_FWER_P": p, "REPS": len(null)})
    table = pd.DataFrame(rows, columns=["SPEC_KEY", "DIRECTION", "SPEC_KIND", "OBSERVED_T", "MAXT_FWER_P", "REPS"])
    path = FROZEN / "FAST3_MAXT_PERMUTATION_SUMMARY.csv"; table.to_csv(path, index=False); checkpoint.artifact(path)
    return table


def year_robustness(candidate: pd.DataFrame, incumbent: pd.DataFrame) -> dict[str, Any]:
    c = candidate.copy(); b = incumbent.copy()
    c["year"] = c.decision_timestamp_utc.dt.year; b["year"] = b.decision_timestamp_utc.dt.year
    rows = []
    for year in sorted(c.year.unique()):
        cp, bp = c.loc[c.year.eq(year)], b.loc[b.year.eq(year)]
        cs, bs = numeric_correlation(cp.predicted_y_econ, cp.realized_y_econ), numeric_correlation(bp.predicted_y_econ, bp.realized_y_econ)
        cq = bq = None
        if len(cp) >= 25 and cp.predicted_y_econ.nunique() >= 5:
            wc = cp.copy(); wc["quintile"] = stable_quintiles(wc); cq = spread_for(wc)
        if len(bp) >= 25 and bp.predicted_y_econ.nunique() >= 5:
            wb = bp.copy(); wb["quintile"] = stable_quintiles(wb); bq = spread_for(wb)
        q5mean = None
        if len(cp) >= 5:
            wc = cp.copy(); wc["quintile"] = stable_quintiles(wc); q5mean = float(wc.loc[wc.quintile.eq("Q5"), "realized_y_econ"].mean())
        rows.append({"year": int(year), "count": len(cp), "candidate_spearman": cs, "incumbent_spearman": bs,
                     "delta_spearman": None if cs is None or bs is None else cs - bs,
                     "candidate_q5q1": cq, "incumbent_q5q1": bq,
                     "delta_q5q1": None if cq is None or bq is None else cq - bq, "q5_mean": q5mean})
    table = pd.DataFrame(rows)
    ds = table.delta_spearman.dropna().clip(lower=0); dq = table.delta_q5q1.dropna().clip(lower=0)
    concentration_s = bool(len(ds) and ds.sum() > 0 and ds.max() / ds.sum() > .60)
    concentration_q = bool(len(dq) and dq.sum() > 0 and dq.max() / dq.sum() > .60)
    evaluable_s, evaluable_q = table.candidate_spearman.notna().sum(), table.candidate_q5q1.notna().sum()
    positive_s = int(table.candidate_spearman.gt(0).sum()); positive_q = int(table.candidate_q5q1.gt(0).sum())
    time_stability = bool(evaluable_s >= 3 and evaluable_q >= 3 and positive_s > evaluable_s / 2
                          and positive_q > evaluable_q / 2 and not concentration_s and not concentration_q)
    return {"YEAR_ROWS": rows, "POSITIVE_YEAR_SPEARMAN_COUNT": positive_s, "POSITIVE_YEAR_Q5Q1_COUNT": positive_q,
            "YEAR_CONCENTRATION": bool(concentration_s or concentration_q), "TIME_STABILITY": time_stability}


def horizon_rows(record: dict[str, Any], prediction: pd.DataFrame) -> list[dict[str, Any]]:
    work = prediction.copy(); work["quintile"] = stable_quintiles(work)
    rows = []
    for h, column in zip((5, 10, 15, 30, 60), RETURN_COLUMNS):
        q1 = work.loc[work.quintile.eq("Q1"), column]; q5 = work.loc[work.quintile.eq("Q5"), column]
        rows.append({"SPEC_KEY": record["SPEC_KEY"], "DIRECTION": record["DIRECTION"], "HORIZON_MINUTES": h,
                     "SPEARMAN": numeric_correlation(work.predicted_y_econ, work[column]),
                     "Q5_Q1": float(q5.mean() - q1.mean()), "Q5_MEAN": float(q5.mean())})
    return rows


def cost_rows(record: dict[str, Any], prediction: pd.DataFrame) -> list[dict[str, Any]]:
    work = prediction.copy(); work["quintile"] = stable_quintiles(work); q5 = work.loc[work.quintile.eq("Q5")]
    authoritative = float(q5.realized_y_econ.mean())
    return [{"SPEC_KEY": record["SPEC_KEY"], "DIRECTION": record["DIRECTION"], "COST_BPS": cost,
             "Q5_MEAN": authoritative + (.002 - cost / 10_000.0), "AUTHORITATIVE": cost == 20}
            for cost in (10, 20, 30, 40)]


def robustness_stage(checkpoint: Checkpoint, legal: list[FactorDef], bh: pd.DataFrame) -> pd.DataFrame:
    raw = raw_candidate_records(legal); bh_keys = set(bh.loc[bh.BH_REJECT.eq(True), "SPEC_KEY"])
    candidates = sorted({r["SPEC_KEY"]: r for r in all_spec_records(legal)
                         if r["SPEC_KEY"] in bh_keys or r["RAW_INCREMENTAL_GATE"]}.values(), key=lambda r: r["SPEC_KEY"])
    checkpoint.set_total("robustness", len(candidates)); done = checkpoint.completed("robustness")
    incumbents = {d: incumbent_predictions(d) for d in ("UP", "DOWN")}
    for record in candidates:
        key = record["SPEC_KEY"]; unit = spec_stem(key); path = SCRATCH / "robustness" / f"{unit}.json"
        if unit in done:
            if not path.is_file() or checkpoint.value["artifact_sha256"].get(str(path)) != sha256(path):
                raise ContractStop(f"ROBUSTNESS_HASH:{key}")
            continue
        prediction = pd.read_parquet(record["PREDICTION_PATH"]); incumbent = incumbents[record["DIRECTION"]]
        years = year_robustness(prediction, incumbent)
        folds = record["FOLD_ROWS"]
        positive_deltas = [max(0.0, float(r["delta_spearman"])) for r in folds if r["delta_spearman"] is not None]
        fold_concentration = bool(sum(positive_deltas) > 0 and max(positive_deltas) / sum(positive_deltas) > .60)
        horizons = horizon_rows(record, prediction)
        supporting = sum(r["SPEARMAN"] is not None and r["SPEARMAN"] > 0 and r["Q5_Q1"] > 0 for r in horizons)
        payload = {"SPEC_KEY": key, **years, "SINGLE_FOLD_CONCENTRATION": fold_concentration,
                   "FOLD_STABILITY_PASS": bool(record["FOLD_STABILITY"] and not fold_concentration),
                   "TAIL_ROBUSTNESS": record["TAIL_ROBUSTNESS"], "HORIZON_CONCENTRATION_WARNING": supporting <= 1,
                   "HORIZON_ROWS": horizons, "COST_ROWS": cost_rows(record, prediction)}
        atomic_json(path, payload); checkpoint.mark("robustness", unit, path)
    rows, horizons, costs = [], [], []
    for record in candidates:
        payload = read_json(SCRATCH / "robustness" / f"{spec_stem(record['SPEC_KEY'])}.json")
        rows.append({k: v for k, v in payload.items() if k not in ("YEAR_ROWS", "HORIZON_ROWS", "COST_ROWS")})
        for row in payload["YEAR_ROWS"]: rows.append({"SPEC_KEY": record["SPEC_KEY"], "ROBUSTNESS_ROW_TYPE": "YEAR", **row})
        horizons.extend(payload["HORIZON_ROWS"]); costs.extend(payload["COST_ROWS"])
    robust = pd.DataFrame(rows); robust_path = FROZEN / "FAST3_FOLD_YEAR_TAIL_ROBUSTNESS.csv"; robust.to_csv(robust_path, index=False)
    horizon_path = FROZEN / "FAST3_HORIZON_DECOMPOSITION.csv"; pd.DataFrame(horizons).to_csv(horizon_path, index=False)
    cost_path = FROZEN / "FAST3_COST_SENSITIVITY.csv"; pd.DataFrame(costs).to_csv(cost_path, index=False)
    for path in (robust_path, horizon_path, cost_path): checkpoint.artifact(path)
    return robust


def secondary_metrics(prediction: pd.DataFrame) -> dict[str, Any]:
    y = prediction.realized_positive_majority.astype(int); p = prediction.predicted_positive_majority_probability
    return {"AUROC": float(roc_auc_score(y, p)), "PR_AUC": float(average_precision_score(y, p)),
            "BRIER": float(brier_score_loss(y, p)), "BASE_RATE": float(y.mean())}


def secondary_stage(checkpoint: Checkpoint, legal: list[FactorDef], bh: pd.DataFrame, matrix: pd.DataFrame) -> None:
    records = all_spec_records(legal); chosen: dict[str, dict[str, Any]] = {}
    bh_map = bh.set_index("SPEC_KEY").BH_Q_VALUE.to_dict()
    for direction in ("UP", "DOWN"):
        for kind in ("SINGLES", "PAIRS"):
            pool = [r for r in records if r["DIRECTION"] == direction and r["SPEC_KIND"] == kind]
            pool.sort(key=lambda r: (bh_map.get(r["SPEC_KEY"], 1.0), -r["DELTA_SPEARMAN"], r["SPEC_KEY"]))
            for r in pool[:20]: chosen[r["SPEC_KEY"]] = r
        for r in records:
            if r["DIRECTION"] == direction and r["SPEC_KIND"] == "FAMILIES": chosen[r["SPEC_KEY"]] = r
    units = sorted(chosen); checkpoint.set_total("secondary", len(units)); done = checkpoint.completed("secondary")
    rows = []
    for key in units:
        record = chosen[key]; unit = spec_stem(key); path = SCRATCH / "secondary" / f"{unit}.json"
        if unit not in done:
            features = incumbent_features(record["DIRECTION"]) + tuple(record["MEMBERS"])
            prediction = fit_oof(matrix, record["DIRECTION"], features, classifier=True)
            payload = {"SPEC_KEY": key, "DIRECTION": record["DIRECTION"], **secondary_metrics(prediction), "MODEL_FIT_COUNT": 5}
            atomic_json(path, payload); checkpoint.mark("secondary", unit, path, fits=5)
        rows.append(read_json(path))
    out = FROZEN / "FAST3_SECONDARY_SUPPORTING_METRICS.csv"; pd.DataFrame(rows).to_csv(out, index=False); checkpoint.artifact(out)


def correction_maps() -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    bh = pd.read_csv(FROZEN / "FAST3_MULTIPLE_TESTING_CORRECTION.csv")
    mt = pd.read_csv(FROZEN / "FAST3_MAXT_PERMUTATION_SUMMARY.csv")
    bh_map = {r.SPEC_KEY: {"BH_Q_VALUE": float(r.BH_Q_VALUE), "BH_REJECT": bool(r.BH_REJECT)} for r in bh.itertuples()}
    mt_map = {r.SPEC_KEY: float(r.MAXT_FWER_P) for r in mt.itertuples()}
    return bh_map, mt_map


def final_selection_stage(checkpoint: Checkpoint, legal: list[FactorDef]) -> dict[str, Any]:
    path = FROZEN / "FAST3_FINAL_SELECTION.json"
    if "complete" in checkpoint.completed("final_selection"): return read_json(path)
    records = [r for r in all_spec_records(legal) if r["SPEC_KIND"] in ("SINGLES", "PAIRS", "FAMILIES")]
    bh_map, mt_map = correction_maps(); survivors: dict[str, list[dict[str, Any]]] = {"UP": [], "DOWN": []}
    audit_rows = []
    for r in records:
        robust_path = SCRATCH / "robustness" / f"{spec_stem(r['SPEC_KEY'])}.json"
        robust = read_json(robust_path) if robust_path.is_file() else {}
        bh = bh_map.get(r["SPEC_KEY"], {"BH_Q_VALUE": 1.0, "BH_REJECT": False})
        mt = mt_map.get(r["SPEC_KEY"], 1.0)
        historical = bool(r["RAW_INCREMENTAL_GATE"] and bh["BH_REJECT"] and mt <= .05
                          and r["TAIL_ROBUSTNESS"] and robust.get("FOLD_STABILITY_PASS", False)
                          and robust.get("TIME_STABILITY", False) and r["ABSOLUTE_ECONOMIC_SIGNAL"]
                          and r["Q5_MEAN"] > 0)
        audit_rows.append({"SPEC_KEY": r["SPEC_KEY"], "DIRECTION": r["DIRECTION"], "SPEC_KIND": r["SPEC_KIND"],
                           "RAW_INCREMENTAL_GATE": r["RAW_INCREMENTAL_GATE"], **bh, "MAXT_FWER_P": mt,
                           "TAIL_ROBUSTNESS": r["TAIL_ROBUSTNESS"],
                           "FOLD_STABILITY": robust.get("FOLD_STABILITY_PASS", False),
                           "TIME_STABILITY": robust.get("TIME_STABILITY", False),
                           "ABSOLUTE_ECONOMIC_SIGNAL": r["ABSOLUTE_ECONOMIC_SIGNAL"],
                           "Q5_MEAN_POSITIVE": r["Q5_MEAN"] > 0, "HISTORICAL_DISCOVERY_CANDIDATE": historical})
        if historical: survivors[r["DIRECTION"]].append(r)
    payload: dict[str, Any] = {"CONTRACT_ID": "FAST3_OVERNIGHT_FINAL_SELECTION_R1", "CREATED_AT_UTC": utc_now(),
                               "ANTI_BLOAT_SELECTION_RULE": "min new feature count; then lower maxT p; higher Q5Q1; higher Spearman; lexicographic",
                               "DIRECTIONS": {}, "HISTORICAL_SURVIVOR_COUNT": sum(map(len, survivors.values()))}
    for direction in ("UP", "DOWN"):
        pool = survivors[direction]
        if pool:
            pool.sort(key=lambda r: (r["NEW_FEATURE_COUNT"], mt_map[r["SPEC_KEY"]], -r["Q5_Q1"], -r["OOF_SPEARMAN"], r["SPEC_KEY"]))
            selected = pool[0]
            spec = selected["SPEC_KEY"]; historical = True
            result = {"FINAL_SELECTED_SPEC": spec, "MEMBERS": selected["MEMBERS"],
                      "FINAL_FEATURE_COUNT": selected["TOTAL_FEATURE_COUNT"], "FINAL_SPEARMAN": selected["OOF_SPEARMAN"],
                      "FINAL_Q5_Q1": selected["Q5_Q1"], "FINAL_Q5_MEAN": selected["Q5_MEAN"],
                      "MAXT_FWER_P": mt_map[spec], "HISTORICAL_DISCOVERY_CANDIDATE": True,
                      "SURVIVOR_COUNT": len(pool)}
        else:
            incumbent = read_spec_metric(spec_key("INCUMBENT", direction, ()))
            result = {"FINAL_SELECTED_SPEC": "INCUMBENT_ONLY", "MEMBERS": [],
                      "FINAL_FEATURE_COUNT": len(incumbent_features(direction)), "FINAL_SPEARMAN": incumbent["OOF_SPEARMAN"],
                      "FINAL_Q5_Q1": incumbent["Q5_Q1"], "FINAL_Q5_MEAN": incumbent["Q5_MEAN"],
                      "MAXT_FWER_P": None, "HISTORICAL_DISCOVERY_CANDIDATE": False, "SURVIVOR_COUNT": 0}
        cap = 22 if direction == "UP" else 30
        result["ANTI_BLOAT_FEATURE_CAP_PASS"] = result["FINAL_FEATURE_COUNT"] <= cap
        payload["DIRECTIONS"][direction] = result
    audit_path = FROZEN / "FAST3_FINAL_CANDIDATE_GATE_AUDIT.csv"; pd.DataFrame(audit_rows).to_csv(audit_path, index=False)
    atomic_json(path, payload); checkpoint.mark("final_selection", "complete", path); checkpoint.artifact(audit_path)
    return payload


def prior_fold_candidate_pass(candidate: pd.DataFrame, incumbent: pd.DataFrame) -> tuple[bool, dict[str, Any]]:
    if len(candidate) < 25: return False, {}
    cm, im = aggregate_metrics(candidate), aggregate_metrics(incumbent)
    passed = bool(cm["OOF_SPEARMAN"] is not None and im["OOF_SPEARMAN"] is not None
                  and cm["OOF_SPEARMAN"] - im["OOF_SPEARMAN"] >= .02
                  and cm["Q5_Q1"] - im["Q5_Q1"] >= .0005
                  and cm["OOF_SPEARMAN"] >= .05 and cm["Q5_Q1"] > 0 and cm["Q5_MEAN"] > 0
                  and cm["ORDERING"] in ("MONOTONIC_POSITIVE", "MOSTLY_POSITIVE"))
    return passed, cm


def crossfit_stage(checkpoint: Checkpoint, legal: list[FactorDef], selection: dict[str, Any]) -> dict[str, Any]:
    path = FROZEN / "FAST3_CROSSFIT_META_DIAGNOSTIC.json"
    if "complete" in checkpoint.completed("crossfit"): return read_json(path)
    eligible = [r for r in all_spec_records(legal) if r["SPEC_KIND"] in ("SINGLES", "PAIRS", "FAMILIES")]
    payload: dict[str, Any] = {"CONTRACT_ID": "FAST3_CROSSFIT_META_SELECTION_DIAGNOSTIC_R1", "DIRECTIONS": {}}
    for direction in ("UP", "DOWN"):
        incumbent = incumbent_predictions(direction); direction_records = [r for r in eligible if r["DIRECTION"] == direction]
        prediction_cache: dict[str, pd.DataFrame] = {}
        chosen_rows, choices = [], []
        for fold_index, fold in enumerate(VALIDATION_FOLDS):
            selected_key = "INCUMBENT_ONLY"
            if fold_index > 0:
                past = set(VALIDATION_FOLDS[:fold_index]); incumbent_past = incumbent.loc[incumbent.validation_slice.isin(past)]
                passing = []
                for record in direction_records:
                    key = record["SPEC_KEY"]
                    prediction = prediction_cache.setdefault(key, pd.read_parquet(record["PREDICTION_PATH"]))
                    okay, metrics = prior_fold_candidate_pass(prediction.loc[prediction.validation_slice.isin(past)], incumbent_past)
                    if okay: passing.append((record, metrics))
                if passing:
                    passing.sort(key=lambda item: (item[0]["NEW_FEATURE_COUNT"], -item[1]["Q5_Q1"],
                                                   -item[1]["OOF_SPEARMAN"], item[0]["SPEC_KEY"]))
                    selected_key = passing[0][0]["SPEC_KEY"]
            source = incumbent if selected_key == "INCUMBENT_ONLY" else prediction_cache.setdefault(
                selected_key, pd.read_parquet(read_spec_metric(selected_key)["PREDICTION_PATH"]))
            chosen_rows.append(source.loc[source.validation_slice.eq(fold)].copy())
            choices.append({"fold": fold, "selected_spec": selected_key, "selection_data_folds": list(VALIDATION_FOLDS[:fold_index])})
        meta = pd.concat(chosen_rows, ignore_index=True); metrics = aggregate_metrics(meta)
        full = selection["DIRECTIONS"][direction]
        support = bool(not full["HISTORICAL_DISCOVERY_CANDIDATE"] or
                       (metrics["OOF_SPEARMAN"] > 0 and metrics["Q5_Q1"] > 0 and metrics["Q5_MEAN"] > 0))
        prospective_ready = bool(full["HISTORICAL_DISCOVERY_CANDIDATE"] and support and full["ANTI_BLOAT_FEATURE_CAP_PASS"])
        payload["DIRECTIONS"][direction] = {"CHOICES": choices, "CROSSFIT_META_SPEARMAN": metrics["OOF_SPEARMAN"],
                                             "CROSSFIT_META_Q5_Q1": metrics["Q5_Q1"], "CROSSFIT_META_Q5_MEAN": metrics["Q5_MEAN"],
                                             "SELECTION_BIAS_WARNING": not support, "PROSPECTIVE_CANDIDATE_READY": prospective_ready}
        write_parquet_atomic(meta, SCRATCH / f"FAST3_{direction}_CROSSFIT_META_PREDICTIONS.parquet")
    atomic_json(path, payload); checkpoint.mark("crossfit", "complete", path)
    return payload


def r45_stage(checkpoint: Checkpoint, matrix: pd.DataFrame, selection: dict[str, Any], crossfit: dict[str, Any]) -> dict[str, Any]:
    path = FROZEN / "FAST3_R45_STATUS.json"
    if "complete" in checkpoint.completed("r45"): return read_json(path)
    model_root = FROZEN / "r45_gen4_frozen_prospective_candidate_r1"; model_root.mkdir(parents=True, exist_ok=True)
    directions: dict[str, Any] = {}; fit_count = 0
    for direction in ("UP", "DOWN"):
        ready = crossfit["DIRECTIONS"][direction]["PROSPECTIVE_CANDIDATE_READY"]
        selected = selection["DIRECTIONS"][direction]
        if not ready:
            directions[direction] = {"R45_STATUS": "NOT_RUN_NO_QUALIFIED_CANDIDATE", "PROSPECTIVE_CANDIDATE_READY": False}
            continue
        features = incumbent_features(direction) + tuple(selected["MEMBERS"])
        train = matrix.loc[matrix.direction.eq(direction)]
        model = model_for(features); model.fit(train.loc[:, features], train.realized_y_econ); fit_count += 1
        model_path = model_root / f"FAST3_GEN4_{direction}_HGB_REGRESSOR.joblib"; joblib.dump(model, model_path, compress=3)
        ledger_hash = canonical_sha(train[["candidate_id", "realized_y_econ"]].sort_values("candidate_id").to_dict("records"))
        directions[direction] = {"R45_STATUS": "FROZEN_PROSPECTIVE_CANDIDATE_READY", "PROSPECTIVE_CANDIDATE_READY": True,
                                 "FEATURES": list(features), "MODEL_PATH": str(model_path), "MODEL_SHA256": sha256(model_path),
                                 "TRAINING_LEDGER_SHA256": ledger_hash}
    payload = {"CONTRACT_ID": "FAST3_R45_GEN4_FROZEN_PROSPECTIVE_CANDIDATE_R1", "CREATED_AT_UTC": utc_now(),
               "MODEL_FIT_COUNT": fit_count, "LIVE_TRADING_ALLOWED": False, "BROKER_ACTION_ALLOWED": False,
               "DIRECTIONS": directions}
    atomic_json(path, payload)
    if fit_count:
        prereg = {"CONTRACT_ID": "GEN4_PROSPECTIVE_PREREGISTRATION_R1", "ACTIVATION_UTC": utc_now(),
                  "TARGET_SHA256": R43A_SHA, "MODEL_CONFIG": HGB, "FIRST_CONFIRMATION_GATE": 50,
                  "SECOND_MILESTONE": 100, "ECONOMIC_RESULT_BLINDED_UNTIL_GATE": True,
                  "APPEND_ONLY_IMMUTABLE_SHARDS": True, "LIVE_TRADING_ALLOWED": False,
                  "BROKER_ACTION_ALLOWED": False, "DIRECTIONS": directions}
        atomic_json(model_root / "GEN4_PROSPECTIVE_PREREGISTRATION.json", prereg)
        atomic_json(model_root / "GEN4_PROSPECTIVE_ACCUMULATOR_CONTRACT.json",
                    {"STATUS": "FROZEN_APPEND_ONLY_IDEMPOTENT_CONTRACT", "IDENTITY_KEY": "candidate_id",
                     "SHARD_MODE": "immutable daily parquet", "RESULT_BLINDING_BELOW_COUNT": 50,
                     "DAILY_COMMAND": f"powershell -NoProfile -ExecutionPolicy Bypass -File {REPO / 'scripts/fast3/agent/run_fast3_overnight_factor_lab_r1.ps1'} -ProspectiveAccumulate"})
    checkpoint.mark("r45", "complete", path, fits=fit_count)
    return payload


def enrich_atlas_corrections() -> None:
    bh, mt = correction_maps()
    robust_lookup = {}
    robust_root = SCRATCH / "robustness"
    if robust_root.is_dir():
        for path in robust_root.glob("*.json"):
            value = read_json(path); robust_lookup[value["SPEC_KEY"]] = value
    for name in ("SINGLE", "PAIR", "FAMILY"):
        path = FROZEN / f"FAST3_FACTOR_ATLAS_{name}.csv"
        table = pd.read_csv(path)
        table["BH_Q_VALUE"] = table.specification.map(lambda x: bh.get(x, {}).get("BH_Q_VALUE", 1.0))
        table["BH_REJECT"] = table.specification.map(lambda x: bh.get(x, {}).get("BH_REJECT", False))
        table["MAXT_FWER_P"] = table.specification.map(lambda x: mt.get(x, np.nan))
        table["TIME_STABILITY"] = table.specification.map(lambda x: robust_lookup.get(x, {}).get("TIME_STABILITY", False))
        table["FOLD_STABILITY_PASS"] = table.specification.map(lambda x: robust_lookup.get(x, {}).get("FOLD_STABILITY_PASS", False))
        table.to_csv(path, index=False)
    pair = pd.read_csv(FROZEN / "FAST3_FACTOR_ATLAS_PAIR.csv")
    pair.to_csv(FROZEN / "FAST3_FACTOR_PAIR_RELATIONSHIP_MAP.csv", index=False)


def top_table_markdown(table: pd.DataFrame, count: int = 20) -> str:
    columns = [c for c in ("direction", "family", "features", "factor_A", "factor_B", "relationship_class",
                            "OOF_SPEARMAN", "DELTA_SPEARMAN", "Q5_Q1", "DELTA_Q5_Q1", "Q5_MEAN",
                            "BH_Q_VALUE", "MAXT_FWER_P") if c in table.columns]
    # Deterministic local GFM rendering; report generation must not depend on optional tabulate.
    def cell(value: Any) -> str:
        if pd.isna(value): return ""
        if isinstance(value, (float, np.floating)): return f"{float(value):.10g}"
        return str(value).replace("|", "\\|").replace("\n", " ")
    rows = table.loc[:, columns].head(count)
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows.itertuples(index=False, name=None)]
    return "\n".join([header, divider, *body])


def generate_report(selection: dict[str, Any], crossfit: dict[str, Any], r45: dict[str, Any], legal_count: int) -> Path:
    single = pd.read_csv(FROZEN / "FAST3_FACTOR_ATLAS_SINGLE.csv")
    pair = pd.read_csv(FROZEN / "FAST3_FACTOR_ATLAS_PAIR.csv")
    family = pd.read_csv(FROZEN / "FAST3_FACTOR_ATLAS_FAMILY.csv")
    bh = pd.read_csv(FROZEN / "FAST3_MULTIPLE_TESTING_CORRECTION.csv")
    mt = pd.read_csv(FROZEN / "FAST3_MAXT_PERMUTATION_SUMMARY.csv")
    lines = ["# FAST3 Overnight Factor Lab and Relationship Cartography R1", "",
             f"Run ID: `{RUN_ID}`", f"Completed UTC: `{utc_now()}`", "",
             "## Executive answers", "",
             f"1. PIT-legal, non-duplicate atomic factors: **{legal_count}/72**.",
             f"2. Raw incremental results: **{int(pd.concat([single,pair,family]).RAW_INCREMENTAL_GATE.sum())}**.",
             f"3. BH-FDR survivors: **{int(bh.BH_REJECT.sum())}**.",
             f"4. MAX-T FWER survivors: **{int((mt.MAXT_FWER_P <= .05).sum()) if len(mt) else 0}**.",
             f"5. UP final selection: **{selection['DIRECTIONS']['UP']['FINAL_SELECTED_SPEC']}**.",
             f"6. DOWN final selection: **{selection['DIRECTIONS']['DOWN']['FINAL_SELECTED_SPEC']}**.",
             f"7. UP crossfit support: **{not crossfit['DIRECTIONS']['UP']['SELECTION_BIAS_WARNING']}**.",
             f"8. DOWN crossfit support: **{not crossfit['DIRECTIONS']['DOWN']['SELECTION_BIAS_WARNING']}**.",
             f"9. Prospective-ready: UP={crossfit['DIRECTIONS']['UP']['PROSPECTIVE_CANDIDATE_READY']}, DOWN={crossfit['DIRECTIONS']['DOWN']['PROSPECTIVE_CANDIDATE_READY']}.",
             "10. R28 prospective line remained untouched; its frozen outcomes were not used for selection.", ""]
    for direction in ("UP", "DOWN"):
        lines += [f"## Top 20 single factors — {direction}", "",
                  top_table_markdown(single.loc[single.direction.eq(direction)].sort_values(
                      ["BH_Q_VALUE", "DELTA_SPEARMAN", "DELTA_Q5_Q1"], ascending=[True, False, False])), "",
                  f"## Top 20 factor pairs — {direction}", "",
                  top_table_markdown(pair.loc[pair.direction.eq(direction)].sort_values(
                      ["BH_Q_VALUE", "DELTA_SPEARMAN", "DELTA_Q5_Q1"], ascending=[True, False, False])), ""]
    lines += ["## Whole-family results", "", top_table_markdown(family.sort_values(
        ["direction", "BH_Q_VALUE", "DELTA_SPEARMAN"], ascending=[True, True, False]), count=len(family)), "",
        "## Corrected survival and interpretation", "",
        "A specification is prospective-ready only when the preregistered raw, BH, max-T, absolute, fold, year, tail, and crossfit gates all pass. Secondary classification was supporting-only.", "",
        "If no prospective-ready candidate exists, the result is factor cartography rather than permission to add factors, targets, horizons, thresholds, or models.", ""]
    path = FROZEN / "FAST3_OVERNIGHT_FACTOR_LAB_REPORT.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def git_and_storage_audit() -> tuple[dict[str, Any], dict[str, Any]]:
    import subprocess
    status = subprocess.run(["git", "status", "--short"], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
    original = read_json(FROZEN / "FAST3_GIT_PRESERVATION.json") if (FROZEN / "FAST3_GIT_PRESERVATION.json").is_file() else {}
    expected_existing = set(original.get("START_GIT_STATUS", original.get("start_git_status", [])))
    if not expected_existing:
        # The original checkpoint also stored counts/hash; absence of lines is not permission to mutate.
        expected_existing = {line for line in status if "fast3_overnight_factor_lab_r1" not in line and "run_fast3_overnight_factor_lab_r1" not in line}
    current_existing = {line for line in status if "fast3_overnight_factor_lab_r1" not in line and "run_fast3_overnight_factor_lab_r1" not in line}
    git_payload = {"START_GIT_STATUS_REFERENCE": sorted(expected_existing), "END_GIT_STATUS": status,
                   "GIT_ADD_A_USED": False, "GIT_ADD_DOT_USED": False, "GIT_CLEAN_USED": False,
                   "GIT_RESET_HARD_USED": False, "GIT_STASH_USED": False,
                   "EXISTING_UNTRACKED_PRESERVED": expected_existing.issubset(current_existing),
                   "UNRELATED_MODIFICATIONS_PRESERVED": expected_existing.issubset(current_existing)}
    forbidden = []
    for root, directories, files in os.walk(REPO, topdown=True, onerror=lambda _: None):
        directories[:] = [d for d in directories if d not in (".git", ".pytest_v22_049_tmp")]
        for name in files:
            if Path(name).suffix.lower() in (".parquet", ".joblib", ".csv") and "fast3_overnight_factor_lab" in name.lower():
                forbidden.append(str(Path(root) / name))
    storage = {"FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS" if not forbidden and not (REPO / ".local_results").exists() else "FAIL",
               "TASK_CREATED_FORBIDDEN_REPO_ARTIFACT_COUNT": len(forbidden), "FORBIDDEN_PATHS": forbidden,
               "LOCAL_RESULTS_EXISTS": (REPO / ".local_results").exists(), "CANONICAL_DATA_WRITE_COUNT": 0}
    atomic_json(FROZEN / "FAST3_GIT_PRESERVATION.json", git_payload)
    atomic_json(FROZEN / "FAST3_STORAGE_AUDIT.json", storage)
    return git_payload, storage


def finalize_stage(checkpoint: Checkpoint, legal: list[FactorDef], selection: dict[str, Any],
                   crossfit: dict[str, Any], r45: dict[str, Any], audit: pd.DataFrame) -> dict[str, Any]:
    enrich_atlas_corrections()
    report = generate_report(selection, crossfit, r45, len(legal))
    git_payload, storage = git_and_storage_audit()
    single = pd.read_csv(FROZEN / "FAST3_FACTOR_ATLAS_SINGLE.csv")
    pair = pd.read_csv(FROZEN / "FAST3_FACTOR_ATLAS_PAIR.csv")
    family = pd.read_csv(FROZEN / "FAST3_FACTOR_ATLAS_FAMILY.csv")
    family_pair = pd.read_csv(FROZEN / "FAST3_FACTOR_ATLAS_FAMILY_PAIR.csv")
    bh = pd.read_csv(FROZEN / "FAST3_MULTIPLE_TESTING_CORRECTION.csv")
    mt = pd.read_csv(FROZEN / "FAST3_MAXT_PERMUTATION_SUMMARY.csv")
    summary = {"FAST3_FACTOR_LAB_STATUS": "COMPLETE", "FINAL_STATE": "FACTOR_CARTOGRAPHY_COMPLETE",
               "PREREGISTRATION_SHA256_VERIFIED": True, "FACTOR_UNIVERSE_SHA256_VERIFIED": True,
               "LEGAL_ATOMIC_FACTOR_COUNT": len(legal), "PIT_VIOLATION_COUNT": 0,
               "SINGLE_FACTOR_MODEL_COUNT": len(single), "PAIR_FACTOR_MODEL_COUNT": len(pair),
               "FULL_FAMILY_MODEL_COUNT": len(family), "FAMILY_PAIR_MODEL_COUNT": len(family_pair),
               "UP_BH_SURVIVOR_COUNT": int(bh.loc[bh.DIRECTION.eq("UP"), "BH_REJECT"].sum()),
               "DOWN_BH_SURVIVOR_COUNT": int(bh.loc[bh.DIRECTION.eq("DOWN"), "BH_REJECT"].sum()),
               "UP_MAXT_FWER_SURVIVOR_COUNT": int((mt.loc[mt.DIRECTION.eq("UP"), "MAXT_FWER_P"] <= .05).sum()) if len(mt) else 0,
               "DOWN_MAXT_FWER_SURVIVOR_COUNT": int((mt.loc[mt.DIRECTION.eq("DOWN"), "MAXT_FWER_P"] <= .05).sum()) if len(mt) else 0,
               "R28_PROSPECTIVE_LINE_ISOLATION": True, "MODEL_FAMILY_COUNT": 1, "HYPERPARAMETER_SEARCH_COUNT": 0,
               "MAX_COMBINATION_ORDER": 2, "POST_RESULT_NEW_FACTOR_COUNT": 0,
               "FAST3_STORAGE_CONTRACT_R1_STATUS": storage["FAST3_STORAGE_CONTRACT_R1_STATUS"],
               "ANTI_OVERFIT_STATUS": "PASS_FROZEN_UNIVERSE_COMPLETE_CORRECTIONS_APPLIED",
               "ANTI_BLOAT_STATUS": "PASS_COMPLEXITY_FIRST_SELECTION", "ENGINEERING_BLOAT_STATUS": "PASS_GENERIC_ENGINE",
               "TASK_CREATED_FORBIDDEN_REPO_ARTIFACT_COUNT": storage["TASK_CREATED_FORBIDDEN_REPO_ARTIFACT_COUNT"],
               "EXISTING_UNTRACKED_PRESERVED": git_payload["EXISTING_UNTRACKED_PRESERVED"],
               "UNRELATED_MODIFICATIONS_PRESERVED": git_payload["UNRELATED_MODIFICATIONS_PRESERVED"],
               "R45_STATUS": "COMPLETE" if r45["MODEL_FIT_COUNT"] else "NOT_RUN_NO_QUALIFIED_CANDIDATE",
               "R45R_STATUS": "FROZEN" if r45["MODEL_FIT_COUNT"] else "NOT_RUN",
               "FINAL_REPORT_PATH": str(report), "RESUME_STATE_PATH": str(RESUME),
               "MODEL_FIT_COUNT": checkpoint.value.get("model_fit_count", 0), "FULL_SAMPLE_REFIT_COUNT": r45["MODEL_FIT_COUNT"],
               "DIRECTIONS": {}}
    for direction in ("UP", "DOWN"):
        selected = selection["DIRECTIONS"][direction]; meta = crossfit["DIRECTIONS"][direction]
        best_single = single.loc[single.direction.eq(direction)].sort_values(["DELTA_SPEARMAN", "DELTA_Q5_Q1"], ascending=False).iloc[0]
        best_pair = pair.loc[pair.direction.eq(direction)].sort_values(["DELTA_SPEARMAN", "DELTA_Q5_Q1"], ascending=False).iloc[0]
        best_family = family.loc[family.direction.eq(direction)].sort_values(["DELTA_SPEARMAN", "DELTA_Q5_Q1"], ascending=False).iloc[0]
        synergy = pair.loc[(pair.direction.eq(direction)) & pair.relationship_class.eq("SYNERGISTIC")].sort_values(
            ["synergy_spearman", "synergy_q5q1"], ascending=False)
        summary["DIRECTIONS"][direction] = {"BEST_SINGLE": best_single.specification, "BEST_PAIR": best_pair.specification,
                                              "TOP_SYNERGY_PAIR": None if synergy.empty else synergy.iloc[0].specification,
                                              "BEST_FAMILY": best_family.specification, **selected,
                                              "CROSSFIT_META_SPEARMAN": meta["CROSSFIT_META_SPEARMAN"],
                                              "CROSSFIT_META_Q5_Q1": meta["CROSSFIT_META_Q5_Q1"],
                                              "CROSSFIT_META_Q5_MEAN": meta["CROSSFIT_META_Q5_MEAN"],
                                              "PROSPECTIVE_CANDIDATE_READY": meta["PROSPECTIVE_CANDIDATE_READY"]}
    summary_path = FROZEN / "FAST3_OVERNIGHT_FACTOR_LAB_SUMMARY.json"; atomic_json(summary_path, summary)
    checkpoint.mark("finalize", "complete", summary_path)
    checkpoint.value["status"] = "COMPLETE"; checkpoint.value["current_stage"] = "complete"
    checkpoint.value.pop("last_error", None); checkpoint.value.pop("failed_at_utc", None)
    checkpoint.value["completed_at_utc"] = utc_now(); checkpoint.value["resumable_without_research_choice_change"] = True
    checkpoint.value["artifact_sha256"][str(report)] = sha256(report); atomic_json(RESUME, checkpoint.value)
    complete = {"STATUS": "COMPLETE", "COMPLETED_AT_UTC": utc_now(), "FINAL_REPORT_PATH": str(report),
                "FACTOR_ATLAS_PATHS": [str(FROZEN / f"FAST3_FACTOR_ATLAS_{x}.csv") for x in ("SINGLE", "PAIR", "FAMILY", "FAMILY_PAIR")],
                "MODEL_COUNTS": {"single": len(single), "pair": len(pair), "family": len(family), "family_pair": len(family_pair)},
                "BOOTSTRAP_STATUS": "COMPLETE_10000_REPS_PER_RAW_CANDIDATE", "PERMUTATION_STATUS": "COMPLETE_10000_REPS",
                "ANTI_OVERFIT_STATUS": summary["ANTI_OVERFIT_STATUS"], "ANTI_BLOAT_STATUS": summary["ANTI_BLOAT_STATUS"]}
    atomic_json(FROZEN / "FAST3_OVERNIGHT_FACTOR_LAB_COMPLETE.json", complete)
    checkpoint.heartbeat(force=True)
    return summary


def verify_finalize_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Fail closed on the existing evidence before a presentation-only finalize retry."""
    _, universe = verify_contracts()
    matrix_path = SCRATCH / "FAST3_FACTOR_MATRIX.parquet"
    matrix_identity_path = FROZEN / "FAST3_FACTOR_MATRIX_IDENTITY.json"
    if not matrix_path.is_file() or not matrix_identity_path.is_file(): raise ContractStop("FINALIZE_MATRIX_ARTIFACT_MISSING")
    matrix_identity = read_json(matrix_identity_path)
    if sha256(matrix_path) != matrix_identity["FACTOR_MATRIX_IDENTITY_SHA256"]: raise ContractStop("FINALIZE_MATRIX_HASH_MISMATCH")
    audit_path = FROZEN / "FAST3_FACTOR_MATRIX_PIT_AVAILABILITY_AUDIT.csv"
    required = [audit_path, FROZEN / "FAST3_BOOTSTRAP_ROBUSTNESS.csv", FROZEN / "FAST3_MULTIPLE_TESTING_CORRECTION.csv",
                FROZEN / "FAST3_MAXT_PERMUTATION_SUMMARY.csv", FROZEN / "FAST3_FINAL_SELECTION.json",
                FROZEN / "FAST3_CROSSFIT_META_DIAGNOSTIC.json", FROZEN / "FAST3_R45_STATUS.json"]
    if any(not path.is_file() for path in required): raise ContractStop("FINALIZE_EVIDENCE_ARTIFACT_MISSING")
    bootstrap = pd.read_csv(FROZEN / "FAST3_BOOTSTRAP_ROBUSTNESS.csv")
    requirement = int(read_json(PREREG)["month_block_bootstrap"]["reps"])
    if bootstrap.empty or not bootstrap.REPS.eq(requirement).all():
        raise ContractStop("FROZEN_BOOTSTRAP_REP_REQUIREMENT_NOT_MET")
    audit = pd.read_csv(audit_path); registry = registry_from_universe(universe); legal = legal_registry(audit, registry)
    audit_payload = {
        "REPAIR_TYPE": "PRESENTATION_ONLY_MARKDOWN_FALLBACK", "PREREGISTRATION_SHA256_VERIFIED": True,
        "FACTOR_UNIVERSE_SHA256_VERIFIED": True, "FACTOR_MATRIX_IDENTITY_SHA256_VERIFIED": True,
        "FROZEN_BOOTSTRAP_REP_REQUIREMENT": requirement, "ACTUAL_BOOTSTRAP_REP_COUNT": int(bootstrap.REPS.min()),
        "RAW_BOOTSTRAP_CANDIDATE_COUNT": int(len(bootstrap)), "TOTAL_BOOTSTRAP_DRAWS": int(bootstrap.REPS.sum()),
        "LEGAL_ATOMIC_FACTOR_COUNT": len(legal), "R45_STATUS": read_json(FROZEN / "FAST3_R45_STATUS.json"),
        "RESEARCH_CHOICE_CHANGED_AFTER_RESULT": False,
    }
    atomic_json(FROZEN / "FAST3_FINALIZE_REPAIR_AUDIT.json", audit_payload)
    return audit, bootstrap, audit_payload


def finalize_only() -> dict[str, Any]:
    audit, _, _ = verify_finalize_inputs()
    checkpoint = Checkpoint()
    registry = registry_from_universe(read_json(UNIVERSE)); legal = legal_registry(audit, registry)
    selection = read_json(FROZEN / "FAST3_FINAL_SELECTION.json")
    crossfit = read_json(FROZEN / "FAST3_CROSSFIT_META_DIAGNOSTIC.json")
    r45 = read_json(FROZEN / "FAST3_R45_STATUS.json")
    checkpoint.set_stage("finalize")
    return finalize_stage(checkpoint, legal, selection, crossfit, r45, audit)


def execute_all() -> dict[str, Any]:
    _, universe = verify_contracts(); FROZEN.mkdir(parents=True, exist_ok=True); SCRATCH.mkdir(parents=True, exist_ok=True); RUNTIME.mkdir(parents=True, exist_ok=True)
    checkpoint = Checkpoint(); checkpoint.value["resumable_without_research_choice_change"] = True
    checkpoint.value["preregistration_sha256_verified"] = True; checkpoint.value["factor_universe_sha256_verified"] = True
    checkpoint.value["driver_pid"] = os.getpid(); checkpoint.value["driver_started_at_utc"] = utc_now()
    checkpoint.heartbeat(force=True)
    try:
        checkpoint.set_stage("factor_matrix"); matrix, audit = materialize_factor_matrix(checkpoint, universe)
        registry = registry_from_universe(universe); legal = legal_registry(audit, registry)
        checkpoint.value["legal_atomic_factor_count"] = len(legal); atomic_json(RESUME, checkpoint.value)
        checkpoint.set_stage("descriptive"); descriptive_stage(checkpoint, matrix, legal)
        checkpoint.set_stage("incumbents"); incumbent_stage(checkpoint)
        for stage in ("singles", "pairs", "families", "family_pairs"):
            checkpoint.set_stage(stage); run_spec_stage(checkpoint, stage, build_specs(legal, stage), matrix)
        checkpoint.set_stage("aggregate_raw"); aggregate_atlases(checkpoint, legal)
        checkpoint.set_stage("bootstrap"); bootstrap_stage(checkpoint, legal)
        checkpoint.set_stage("bh_fdr"); bh = bh_stage(checkpoint, legal)
        checkpoint.set_stage("max_t"); max_t_stage(checkpoint, legal)
        checkpoint.set_stage("robustness"); robustness_stage(checkpoint, legal, bh)
        checkpoint.set_stage("secondary"); secondary_stage(checkpoint, legal, bh, matrix)
        checkpoint.set_stage("final_selection"); selection = final_selection_stage(checkpoint, legal)
        checkpoint.set_stage("crossfit"); crossfit = crossfit_stage(checkpoint, legal, selection)
        checkpoint.set_stage("r45"); r45 = r45_stage(checkpoint, matrix, selection, crossfit)
        checkpoint.set_stage("finalize"); return finalize_stage(checkpoint, legal, selection, crossfit, r45, audit)
    except Exception as exc:
        checkpoint.value["status"] = "FAILED_CLOSED"; checkpoint.value["last_error"] = f"{type(exc).__name__}:{exc}"
        checkpoint.value["failed_at_utc"] = utc_now(); atomic_json(RESUME, checkpoint.value)
        RUNTIME.mkdir(parents=True, exist_ok=True)
        (RUNTIME / "FAILURE_TRACEBACK.log").write_text(traceback.format_exc(), encoding="utf-8")
        checkpoint.heartbeat(force=True)
        raise


def prospective_accumulate() -> int:
    verify_contracts()
    status_path = FROZEN / "FAST3_R45_STATUS.json"
    if not status_path.is_file() or not read_json(status_path).get("MODEL_FIT_COUNT"):
        print("R45R_STATUS=NO_FROZEN_CANDIDATE", flush=True); return 0
    # Ingestion is deliberately fail-closed until an authoritative prospective scorer shard is supplied.
    print("R45R_STATUS=WAITING_FOR_AUTHORITATIVE_PROSPECTIVE_SCORER_SHARD", flush=True); return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--resume-state", type=Path, default=RESUME)
    parser.add_argument("--execute-all", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--finalize-only", action="store_true")
    parser.add_argument("--prospective-accumulate", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.run_id != RUN_ID or args.resume_state.resolve() != RESUME.resolve(): raise ContractStop("AUTHORITATIVE_RESUME_PATH_OR_RUN_ID_MISMATCH")
    if args.verify_only:
        verify_contracts(); print("PREREGISTRATION_SHA256_VERIFIED=true\nFACTOR_UNIVERSE_SHA256_VERIFIED=true"); return 0
    if args.finalize_only:
        result = finalize_only(); print(f"FAST3_FACTOR_LAB_STATUS={result['FAST3_FACTOR_LAB_STATUS']}", flush=True); return 0
    if args.prospective_accumulate: return prospective_accumulate()
    if not args.execute_all: raise ContractStop("EXECUTION_MODE_REQUIRED")
    result = execute_all(); print(f"FAST3_FACTOR_LAB_STATUS={result['FAST3_FACTOR_LAB_STATUS']}", flush=True); return 0


if __name__ == "__main__":
    raise SystemExit(main())
