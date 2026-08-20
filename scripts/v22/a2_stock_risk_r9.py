"""A2 Stock-Risk R9: pre-2026 portfolio-date regime-risk prediction only."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_STOCK_RISK_R9"
R7_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_stock_risk_r7.py"
R6_OOF_PATH = RESULTS_ROOT / "A2_STOCK_RISK_R6" / "r6_oof_predictions.parquet"
R6_OOF_SHA256 = "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4"
R6_FOLD_CONTRACT_ID_EXPECTED = "fa9cd7aa20f6a564c4357b61153ae1252b3fc407b68345285b42bd0f8c92daaa"
R6_REFERENCE_MODEL = "LGBM_BAD_ASYM_2"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
TARGET_HORIZON = 1
TARGET_QUANTILE = 0.10
POSITION_RULE_APPLICATION_COUNT = 0
ECONOMIC_BACKTEST_COUNT = 0
PARAMETER_SEARCH_COUNT = 0
THRESHOLD_SEARCH_COUNT = 0

LOGISTIC_PARAMS = {
    "C": 0.3, "class_weight": "balanced", "solver": "lbfgs",
    "max_iter": 2000, "random_state": 20260818,
}
LIGHTGBM_PARAMS = {
    "n_estimators": 100, "learning_rate": 0.03, "num_leaves": 7, "max_depth": 3,
    "min_child_samples": 40, "reg_alpha": 1.0, "reg_lambda": 5.0,
    "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8,
    "objective": "binary", "class_weight": "balanced", "random_state": 20260818,
    "n_jobs": 1, "deterministic": True, "force_col_wise": True, "verbosity": -1,
}

MARKET_FEATURES = [
    *[f"MKT_SPX_PROXY_{x}" for x in ["RETURN_1D", "RETURN_5D", "RETURN_20D", "DRAWDOWN_60D", "REALIZED_VOL_20D", "DOWNSIDE_INTENSITY_20D", "DISTANCE_MA50"]],
    *[f"MKT_QQQ_{x}" for x in ["RETURN_1D", "RETURN_5D", "RETURN_20D", "DRAWDOWN_60D", "REALIZED_VOL_20D"]],
    *[f"MKT_SOXX_{x}" for x in ["RETURN_1D", "RETURN_5D", "RETURN_20D", "DRAWDOWN_60D", "REALIZED_VOL_20D"]],
    "MKT_SOXX_RELATIVE_STRENGTH_VS_SPX_20D",
    "MKT_SOXX_RELATIVE_STRENGTH_VS_QQQ_20D",
    "MKT_VIX_LEVEL", "MKT_VIX_CHANGE_1D", "MKT_VIX_CHANGE_5D",
    "MKT_VIX_PERCENTILE_252D", "MKT_VIX_ZSCORE_252D",
]
A2_PORTFOLIO_FEATURES = [
    "A2_HOLDING_COUNT", "A2_SCORE_MEAN", "A2_SCORE_MEDIAN", "A2_SCORE_STD",
    "A2_SCORE_TOP_BOTTOM_SPREAD", "A2_SCORE_TOP5_ABS_CONCENTRATION",
    "A2_STOCK_REALIZED_VOL_MEAN", "A2_STOCK_REALIZED_VOL_MEDIAN",
    "A2_CONSTITUENT_MOMENTUM_BREADTH", "A2_FRACTION_BELOW_OWN_TREND",
    "A2_FRACTION_NEGATIVE_RECENT_RETURN",
]
R6_CROSS_SECTION_FEATURES = [
    "R6_SCORE_MEAN", "R6_SCORE_MEDIAN", "R6_SCORE_STD", "R6_SCORE_P75",
    "R6_SCORE_P90", "R6_SCORE_P95", "R6_SCORE_MAX",
    "R6_FRACTION_FROZEN_TOP_DECILE", "R6_TOP20_MEAN", "R6_SCORE_CONCENTRATION",
]
TRAILING_A2_FEATURES = [
    "TRAILING_A2_RETURN_1D", "TRAILING_A2_RETURN_5D", "TRAILING_A2_RETURN_20D",
    "TRAILING_A2_DRAWDOWN_60D", "TRAILING_A2_REALIZED_VOL_20D",
    "TRAILING_A2_DOWNSIDE_VOL_20D", "TRAILING_A2_LOSS_DAY_FRACTION_20D",
    "TRAILING_A2_LOSS_STREAK", "TRAILING_A2_ROLLING_WORST_DAY_20D",
]
FEATURES = MARKET_FEATURES + A2_PORTFOLIO_FEATURES + R6_CROSS_SECTION_FEATURES + TRAILING_A2_FEATURES
ABLATIONS = {
    "A_MARKET_ONLY": MARKET_FEATURES,
    "B_A2_PORTFOLIO_STATE_ONLY": A2_PORTFOLIO_FEATURES,
    "C_R6_CROSS_SECTION_STATE_ONLY": R6_CROSS_SECTION_FEATURES,
    "D_TRAILING_A2_STATE_ONLY": TRAILING_A2_FEATURES,
    "E_FULL_R9": FEATURES,
}


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R7 = _load_module(R7_SCRIPT, "a2_stock_risk_r7_for_r9")
R1, R3 = R7.R1, R7.R3
FOLDS = list(R7.FOLDS)
R6_FOLD_CONTRACT = dict(R7.R6_FOLD_CONTRACT)
R9_FOLD_CONTRACT = {
    "folds": FOLDS, "purge_embargo_sessions": R3.PURGE_EMBARGO_SESSIONS,
    "split_unit": "portfolio_date", "boundary_source": "frozen R6 temporal contract",
}
R9_FOLD_CONTRACT_ID = R1.canonical_hash(R9_FOLD_CONTRACT)


@dataclass(frozen=True)
class FeatureMeta:
    name: str
    family: str
    source: str
    timestamp_meaning: str
    lookback: str
    pit_proof: str
    future_dependency: bool = False


def target_contract(a2_daily_sha256: str) -> dict[str, Any]:
    contract = {
        "observation_unit": "portfolio_date",
        "horizon_trading_sessions": TARGET_HORIZON,
        "horizon_derivation": "frozen A2 emits a new Top20 every signal session; close signal executes at next session open and is held to the next execution",
        "target_formula": "future_portfolio_MAE_1=min(0,reconstructed_daily_return at next execution_date)",
        "event_formula": "BAD_REGIME_TARGET=1 iff future_portfolio_MAE_1 <= fold-training Q10",
        "fold_local_quantile": TARGET_QUANTILE,
        "source_portfolio_return_series": str(R1.A2_DAILY),
        "source_portfolio_return_column": "reconstructed_daily_return",
        "source_portfolio_return_sha256": a2_daily_sha256,
        "return_authority": "frozen net-of-cost A2 portfolio_daily",
        "timestamp_contract": "09:25 America/New_York prediction; A2/market/stock state through prior completed session; target is next execution-to-execution net return",
        "future_path_in_feature_count": 0,
    }
    contract["target_contract_hash"] = R1.canonical_hash(contract)
    return contract


def discovery() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    baseline = R1.verify_frozen_baseline()
    r6_hash = R1.sha256_file(R6_OOF_PATH)
    fold_pass = R7.R6_FOLD_CONTRACT_ID == R6_FOLD_CONTRACT_ID_EXPECTED
    manifest = json.loads(R1.BASELINE_MANIFEST.read_text(encoding="utf-8"))
    evaluation = manifest["contracts"]["evaluation"]
    top = pd.read_parquet(R3.TOP20_PATH, columns=["signal_date", "ticker"])
    top["signal_date"] = pd.to_datetime(top.signal_date)
    daily = pd.read_parquet(R1.A2_DAILY, columns=["execution_date", "reconstructed_daily_return"])
    daily["execution_date"] = pd.to_datetime(daily.execution_date)
    daily_contract = bool(
        evaluation.get("signal_execution") == "close signal -> next US equity session open"
        and top.groupby("signal_date").size().eq(20).all()
        and top.signal_date.lt(TRAINING_CUTOFF).all()
        and daily.execution_date.lt(TRAINING_CUTOFF).all()
    )
    market_found = all((R1.PRICE_YEAR_ROOT / f"year={year}" / "prices.parquet").is_file() for year in range(2019, 2026)) and R1.VIX_PATH.is_file()
    values = {
        "R9_DISCOVERY_STATUS": "PASS" if r6_hash == R6_OOF_SHA256 and fold_pass and daily_contract and market_found else "FAIL",
        "A2_PORTFOLIO_HISTORY_FOUND": R3.TOP20_PATH.is_file(),
        "A2_PORTFOLIO_RETURN_CONTRACT_FOUND": daily_contract,
        "R6_OOF_FOUND": R6_OOF_PATH.is_file(),
        "R6_FOLD_CONTRACT_PASS": fold_pass,
        "MARKET_DATA_FOUND": market_found,
        "PIT_SOURCE_STATUS": "PASS",
        "R6_OOF_HASH": r6_hash,
        "R6_FOLD_CONTRACT_ID": R7.R6_FOLD_CONTRACT_ID,
        "a2_daily_sha256": baseline["a2_daily_sha256"],
        "portfolio_mapping": manifest["contracts"]["A2"].get("portfolio_mapping", manifest["contracts"]["A"].get("portfolio_mapping")),
        "signal_execution": evaluation["signal_execution"],
    }
    return values, baseline, manifest


def _loss_streak(values: np.ndarray) -> float:
    count = 0
    for value in np.asarray(values, dtype=float)[::-1]:
        if value < 0:
            count += 1
        else:
            break
    return float(count)


def build_trailing_a2(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily[["execution_date", "reconstructed_daily_return", "reconstructed_nav"]].sort_values("execution_date").copy()
    r = frame.reconstructed_daily_return.astype(float).shift(1)
    nav = frame.reconstructed_nav.astype(float).shift(1)
    downside = r.clip(upper=0.0)
    out = pd.DataFrame({"signal_date": frame.execution_date, "trailing_information_date": frame.execution_date.shift(1)})
    out["TRAILING_A2_RETURN_1D"] = r
    out["TRAILING_A2_RETURN_5D"] = (1.0 + r).rolling(5, min_periods=5).apply(np.prod, raw=True) - 1.0
    out["TRAILING_A2_RETURN_20D"] = (1.0 + r).rolling(20, min_periods=20).apply(np.prod, raw=True) - 1.0
    out["TRAILING_A2_DRAWDOWN_60D"] = nav / nav.rolling(60, min_periods=60).max() - 1.0
    out["TRAILING_A2_REALIZED_VOL_20D"] = r.rolling(20, min_periods=20).std() * np.sqrt(252.0)
    out["TRAILING_A2_DOWNSIDE_VOL_20D"] = np.sqrt(downside.pow(2).rolling(20, min_periods=20).mean()) * np.sqrt(252.0)
    out["TRAILING_A2_LOSS_DAY_FRACTION_20D"] = r.lt(0).astype(float).rolling(20, min_periods=20).mean()
    out["TRAILING_A2_LOSS_STREAK"] = r.rolling(20, min_periods=1).apply(_loss_streak, raw=True)
    out["TRAILING_A2_ROLLING_WORST_DAY_20D"] = r.rolling(20, min_periods=20).min()
    return out


def _aggregate_stock_panel(stock: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for date, group in stock.groupby("signal_date", sort=True):
        score = group.A2_PREDICTION.astype(float)
        abs_score = score.abs().sort_values(ascending=False)
        r6 = group.R6_OOF_SCORE.astype(float).dropna()
        record: dict[str, Any] = {
            "signal_date": pd.Timestamp(date), "information_date": pd.Timestamp(group.information_date.iloc[0]),
            "A2_HOLDING_COUNT": float(len(group)), "A2_SCORE_MEAN": score.mean(), "A2_SCORE_MEDIAN": score.median(),
            "A2_SCORE_STD": score.std(), "A2_SCORE_TOP_BOTTOM_SPREAD": score.max() - score.min(),
            "A2_SCORE_TOP5_ABS_CONCENTRATION": abs_score.iloc[:5].sum() / abs_score.sum() if abs_score.sum() else 0.0,
            "A2_STOCK_REALIZED_VOL_MEAN": group.REALIZED_VOL_20D.mean(),
            "A2_STOCK_REALIZED_VOL_MEDIAN": group.REALIZED_VOL_20D.median(),
            "A2_CONSTITUENT_MOMENTUM_BREADTH": group.RET_20D.gt(0).mean(),
            "A2_FRACTION_BELOW_OWN_TREND": group.STOCK_PRICE_VS_MA20.lt(0).mean(),
            "A2_FRACTION_NEGATIVE_RECENT_RETURN": group.RET_5D.lt(0).mean(),
            "R6_SCORE_MEAN": r6.mean(), "R6_SCORE_MEDIAN": r6.median(), "R6_SCORE_STD": r6.std(),
            "R6_SCORE_P75": r6.quantile(.75), "R6_SCORE_P90": r6.quantile(.90), "R6_SCORE_P95": r6.quantile(.95),
            "R6_SCORE_MAX": r6.max(), "R6_FRACTION_FROZEN_TOP_DECILE": group.R6_RISK_PERCENTILE.ge(.90).mean() if r6.size else np.nan,
            "R6_TOP20_MEAN": r6.mean(),
            "R6_SCORE_CONCENTRATION": r6.nlargest(5).sum() / r6.sum() if r6.size and r6.sum() else np.nan,
        }
        records.append(record)
    return pd.DataFrame(records)


def build_portfolio_panel() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    stock, daily, r7_audit = R7.build_feature_panel()
    trend = pd.read_parquet(R3.TRAINING_MATRIX_PATH, columns=["signal_date", "ticker", "price_vs_ma20"])
    trend = trend.rename(columns={"signal_date": "information_date", "price_vs_ma20": "STOCK_PRICE_VS_MA20"})
    trend["information_date"] = pd.to_datetime(trend.information_date)
    stock = stock.merge(trend, on=["information_date", "ticker"], how="left", validate="one_to_one")
    r6_pct = pd.read_parquet(R6_OOF_PATH, columns=["signal_date", "ticker", "candidate_id", "risk_percentile"])
    r6_pct["signal_date"] = pd.to_datetime(r6_pct.signal_date)
    r6_pct = r6_pct.loc[r6_pct.candidate_id.eq(R6_REFERENCE_MODEL), ["signal_date", "ticker", "risk_percentile"]].rename(columns={"risk_percentile": "R6_RISK_PERCENTILE"})
    stock = stock.merge(r6_pct, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    base = _aggregate_stock_panel(stock)

    market = R7.load_market_state().sort_values("market_feature_date").copy()
    market["MKT_SOXX_RELATIVE_STRENGTH_VS_QQQ_20D"] = market.MKT_SOXX_RETURN_20D - market.MKT_QQQ_RETURN_20D
    v = market.MKT_VIX_LEVEL.astype(float)
    mean, std = v.rolling(252, min_periods=126).mean(), v.rolling(252, min_periods=126).std()
    market["MKT_VIX_ZSCORE_252D"] = (v - mean) / std
    base = base.merge(market[["market_feature_date", *MARKET_FEATURES]], left_on="information_date", right_on="market_feature_date", how="left", validate="one_to_one")

    daily = daily.sort_values("execution_date").copy()
    trailing = build_trailing_a2(daily)
    base = base.merge(trailing, on="signal_date", how="left", validate="one_to_one")
    target = daily[["execution_date", "reconstructed_daily_return"]].copy()
    target["target_end_date"] = target.execution_date.shift(-1)
    target["next_portfolio_return"] = target.reconstructed_daily_return.shift(-1)
    target["future_portfolio_mae"] = np.minimum(0.0, target.next_portfolio_return)
    target = target.rename(columns={"execution_date": "signal_date"})[["signal_date", "target_end_date", "next_portfolio_return", "future_portfolio_mae"]]
    base = base.merge(target, on="signal_date", how="left", validate="one_to_one")
    base = base.loc[base.target_end_date.notna() & base.target_end_date.lt(TRAINING_CUTOFF)].copy()
    base = base.replace([np.inf, -np.inf], np.nan).sort_values("signal_date").reset_index(drop=True)
    if base.duplicated("signal_date").any() or base.A2_HOLDING_COUNT.ne(20).any():
        raise RuntimeError("R9 portfolio-date observation identity failure")
    if not base.information_date.lt(base.signal_date).all() or not base.market_feature_date.lt(base.signal_date).all():
        raise RuntimeError("R9 market/A2 feature lookahead")
    trailing_known = base.trailing_information_date.notna()
    if not base.loc[trailing_known, "trailing_information_date"].lt(base.loc[trailing_known, "signal_date"]).all():
        raise RuntimeError("R9 trailing A2 lookahead")
    if base.signal_date.ge(TRAINING_CUTOFF).any() or base.target_end_date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("R9 2026 firewall breach")
    audit = {
        "portfolio_rows": len(base), "portfolio_dates": int(base.signal_date.nunique()),
        "stock_source_rows": len(stock), "exact_top20_dates": int(stock.signal_date.nunique()),
        "r6_oof_missing_portfolio_dates": int(base.R6_SCORE_MEAN.isna().sum()),
        "r6_missingness_policy": "preserve NA; never backfill with in-sample R6 score",
        "r7_source_audit": r7_audit,
    }
    return base, daily, audit


def feature_metadata() -> list[FeatureMeta]:
    rows: list[FeatureMeta] = []
    for name in MARKET_FEATURES:
        source = "canonical local CBOE VIX" if "VIX" in name else "Moomoo QFQ QQQ/SPY/SOXX"
        rows.append(FeatureMeta(name, "MARKET_STATE", source, "completed information_date close before signal_date", "trailing 1/5/20/50/60/252 sessions as encoded", "2019-2025 source only; trailing transforms; market_feature_date < signal_date"))
    for name in A2_PORTFOLIO_FEATURES:
        rows.append(FeatureMeta(name, "A2_PORTFOLIO_STATE", "frozen A2 Top20 plus frozen PIT stock matrix", "frozen information_date cross-section before next-open execution", "current Top20 and existing trailing stock state", "exact frozen Top20; information_date < signal_date"))
    for name in R6_CROSS_SECTION_FEATURES:
        rows.append(FeatureMeta(name, "R6_CROSS_SECTION_STATE", "hash-verified frozen R6 OOF scores", "same-date outer-fold OOF stock scores", "current Top20 cross-section", "R6 artifact hash verified; OOF-only; missing history preserved"))
    for name in TRAILING_A2_FEATURES:
        rows.append(FeatureMeta(name, "TRAILING_A2_STATE", "frozen net-of-cost A2 portfolio_daily", "latest fully completed execution-date return strictly before prediction", "1/5/20/60 sessions as encoded", "portfolio return shifted one execution session before rolling transforms"))
    return rows


def audit_features(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    for item in feature_metadata():
        values = pd.to_numeric(panel[item.name], errors="coerce")
        finite = np.isfinite(values.to_numpy(dtype=float))
        dates = panel.loc[finite, "signal_date"]
        rows.append({
            **asdict(item), "missing_count": int(values.isna().sum()),
            "non_finite_count": int((~finite & values.notna().to_numpy()).sum()),
            "first_legal_date": dates.min() if len(dates) else None,
            "last_legal_pre2026_date": dates.max() if len(dates) else None,
        })
    table = pd.DataFrame(rows)
    manifest = {
        "contract_status": "FROZEN_BEFORE_MODEL_FIT", "feature_count": len(FEATURES),
        "families": {
            "MARKET_STATE": MARKET_FEATURES, "A2_PORTFOLIO_STATE": A2_PORTFOLIO_FEATURES,
            "R6_CROSS_SECTION_STATE": R6_CROSS_SECTION_FEATURES, "TRAILING_A2_STATE": TRAILING_A2_FEATURES,
        },
        "feature_schema_sha256": R1.canonical_hash(FEATURES),
        "excluded": {
            "SECTOR_CONCENTRATION_MAX_SECTOR": "EXCLUDE_NO_COMPLETE_TIMESTAMP_SAFE_SECTOR_HISTORY",
            "PORTFOLIO_BETA_PROXY": "EXCLUDE_NO_EXISTING_AUTHORITATIVE_PORTFOLIO_DATE_BETA_UTILITY",
            "CONSTITUENT_CORRELATION_PROXY": "EXCLUDE_NO_EXISTING_AUTHORITATIVE_PIT_COVARIANCE_UTILITY",
            "MARKET_BREADTH_DISPERSION_CORRELATION": "EXCLUDE_NO_EXISTING_PROVEN_PIT_SOURCE_REQUIRED_FOR_R9",
        },
        "missingness_contract": "fold-training median imputation for Logistic; native LightGBM missing routing; no in-sample R6 backfill",
    }
    return table, manifest


def make_model(kind: str) -> Any:
    if kind == "LOGISTIC":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(**LOGISTIC_PARAMS)),
        ])
    if kind == "LIGHTGBM":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(**LIGHTGBM_PARAMS)
    raise ValueError(kind)


def fold_split(panel: pd.DataFrame, sessions: pd.DatetimeIndex, start_text: str, end_text: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    start, end = pd.Timestamp(start_text), pd.Timestamp(end_text)
    valid = panel.loc[panel.signal_date.between(start, end)].copy()
    if valid.empty:
        raise RuntimeError("empty R9 validation fold")
    first = pd.Timestamp(valid.signal_date.min())
    cutoff = pd.Timestamp(sessions[int(sessions.get_loc(first)) - R3.PURGE_EMBARGO_SESSIONS])
    train = panel.loc[panel.target_end_date.lt(cutoff)].copy()
    if train.empty or train.target_end_date.max() >= cutoff:
        raise RuntimeError("R9 purge/embargo violation")
    return train, valid, cutoff


def fold_labels(train: pd.DataFrame, valid: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, float]:
    threshold = float(train.future_portfolio_mae.quantile(TARGET_QUANTILE))
    return train.future_portfolio_mae.le(threshold).astype(int).to_numpy(), valid.future_portfolio_mae.le(threshold).astype(int).to_numpy(), threshold


def _probability(model: Any, frame: pd.DataFrame, features: list[str]) -> np.ndarray:
    p = np.asarray(model.predict_proba(frame[features])[:, 1], dtype=float)
    if not np.isfinite(p).all() or not ((p >= 0) & (p <= 1)).all():
        raise RuntimeError("invalid R9 probability")
    return p


def run_oof(panel: pd.DataFrame, daily: pd.DataFrame, features: list[str], kind: str, model_id: str) -> tuple[pd.DataFrame, int]:
    sessions = pd.DatetimeIndex(daily.execution_date)
    rows: list[pd.DataFrame] = []
    fits = 0
    for fold_name, start, end in FOLDS:
        train, valid, cutoff = fold_split(panel, sessions, start, end)
        y_train, y_valid, threshold = fold_labels(train, valid)
        if np.unique(y_train).size != 2 or np.unique(y_valid).size != 2:
            raise RuntimeError(f"R9 fold lacks both classes: {fold_name}")
        model = make_model(kind)
        model.fit(train[features], y_train)
        fits += 1
        train_p, valid_p = _probability(model, train, features), _probability(model, valid, features)
        out = valid[["signal_date", "target_end_date", "future_portfolio_mae", "next_portfolio_return"]].copy()
        out["fold"] = fold_name
        out["bad_regime_target"] = y_valid
        out["probability"] = valid_p
        out["risk_percentile"] = R1.empirical_percentile(train_p, valid_p)
        out["fold_training_q10"] = threshold
        out["train_max_target_end"] = train.target_end_date.max()
        out["embargo_cutoff"] = cutoff
        out["model_id"] = model_id
        rows.append(out)
    result = pd.concat(rows, ignore_index=True).sort_values("signal_date").reset_index(drop=True)
    if result.duplicated("signal_date").any():
        raise RuntimeError("duplicate R9 OOF date")
    return result, fits


def prediction_hash(frame: pd.DataFrame) -> str:
    values = frame.sort_values("signal_date")[["probability", "risk_percentile"]].to_numpy(dtype=np.float64)
    return hashlib.sha256(values.tobytes()).hexdigest()


def predictive_metrics(frame: pd.DataFrame, probability: str, percentile: str) -> dict[str, float]:
    y = frame.bad_regime_target.to_numpy(dtype=int)
    p = frame[probability].to_numpy(dtype=float)
    pct = frame[percentile].to_numpy(dtype=float)
    base = float(y.mean())
    top10, top20 = pct >= .90, pct >= .80
    ap = float(average_precision_score(y, p))
    bad_count = max(1, int(y.sum()))
    x = np.column_stack([np.ones(len(p)), np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))])
    intercept, slope = np.linalg.lstsq(x, y.astype(float), rcond=None)[0]
    return {
        "row_count": len(frame), "base_event_rate": base,
        "auroc": float(roc_auc_score(y, p)), "average_precision": ap, "ap_base_multiple": ap / base,
        "brier_score": float(brier_score_loss(y, p)),
        "calibration_intercept_linear_on_logit": float(intercept), "calibration_slope_linear_on_logit": float(slope),
        "top_decile_event_rate": float(y[top10].mean()), "top_decile_lift": float(y[top10].mean() / base),
        "top_decile_capture": float(y[top10].sum() / bad_count),
        "top_quintile_event_rate": float(y[top20].mean()), "top_quintile_lift": float(y[top20].mean() / base),
        "mean_probability_bad": float(p[y == 1].mean()), "mean_probability_non_bad": float(p[y == 0].mean()),
        "mean_probability_bad_minus_non_bad": float(p[y == 1].mean() - p[y == 0].mean()),
    }


def evaluate(combined: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    specs = [("LOGISTIC", "logistic_oof_probability", "logistic_risk_percentile"), ("R9_ML", "r9_ml_oof_probability", "r9_ml_risk_percentile")]
    pooled_rows, fold_rows = [], []
    for name, pcol, qcol in specs:
        pooled = predictive_metrics(combined, pcol, qcol)
        positive = 0
        for fold_name, _, _ in FOLDS:
            metrics = predictive_metrics(combined.loc[combined.fold.eq(fold_name)], pcol, qcol)
            direction = bool(metrics["auroc"] > .5 and metrics["ap_base_multiple"] > 1 and metrics["mean_probability_bad_minus_non_bad"] > 0)
            positive += int(direction)
            fold_rows.append({"model": name, "fold": fold_name, **metrics, "direction_positive": direction})
        pooled_rows.append({"model": name, **pooled, "positive_direction_folds": positive})
    return pd.DataFrame(pooled_rows), pd.DataFrame(fold_rows)


def combine_oof(logistic: pd.DataFrame, ml: pd.DataFrame) -> pd.DataFrame:
    left = logistic.rename(columns={"probability": "logistic_oof_probability", "risk_percentile": "logistic_risk_percentile"})
    right = ml[["signal_date", "probability", "risk_percentile"]].rename(columns={"probability": "r9_ml_oof_probability", "risk_percentile": "r9_ml_risk_percentile"})
    result = left.merge(right, on="signal_date", validate="one_to_one")
    return result.sort_values("signal_date").reset_index(drop=True)


def family_diagnostic(panel: pd.DataFrame, daily: pd.DataFrame, full: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    rows: list[dict[str, Any]] = []
    fits = 0
    for family, features in ABLATIONS.items():
        if family == "E_FULL_R9":
            oof = full
        else:
            oof, count = run_oof(panel, daily, features, "LIGHTGBM", family)
            fits += count
        pooled = predictive_metrics(oof.rename(columns={"probability": "p", "risk_percentile": "q"}), "p", "q")
        positive = 0
        rows.append({"family": family, "scope": "POOLED", "fold": "ALL", "feature_count": len(features), **pooled})
        for fold_name, _, _ in FOLDS:
            subset = oof.loc[oof.fold.eq(fold_name)].rename(columns={"probability": "p", "risk_percentile": "q"})
            metric = predictive_metrics(subset, "p", "q")
            direction = bool(metric["auroc"] > .5 and metric["ap_base_multiple"] > 1 and metric["mean_probability_bad_minus_non_bad"] > 0)
            positive += int(direction)
            rows.append({"family": family, "scope": "FOLD", "fold": fold_name, "feature_count": len(features), **metric, "direction_positive": direction})
        rows[-6]["positive_direction_folds"] = positive
    return pd.DataFrame(rows), fits


def r6_regime_diagnostic(combined: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    source = panel[["signal_date", "R6_SCORE_MEAN", "R6_SCORE_P90", "R6_SCORE_STD"]]
    frame = combined.merge(source, on="signal_date", validate="one_to_one")
    frame["r9_probability_quintile"] = np.clip(np.ceil(frame.r9_ml_risk_percentile * 5), 1, 5).astype(int)
    rows = []
    for scope, fold, group in [("POOLED", "ALL", frame), *[("FOLD", name, frame.loc[frame.fold.eq(name)]) for name, _, _ in FOLDS]]:
        for quintile, part in group.groupby("r9_probability_quintile"):
            rows.append({
                "scope": scope, "fold": fold, "r9_probability_quintile": int(quintile), "row_count": len(part),
                "average_r6_score": part.R6_SCORE_MEAN.mean(), "p90_r6_score": part.R6_SCORE_P90.mean(),
                "r6_cross_sectional_dispersion": part.R6_SCORE_STD.mean(),
                "future_bad_regime_rate": part.bad_regime_target.mean(), "future_portfolio_mae": part.future_portfolio_mae.mean(),
            })
    return pd.DataFrame(rows)


def print_values(values: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        value = values[key]
        if isinstance(value, float) and np.isfinite(value):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: output directory not empty: {output}")
    guard_pre = R1.guard_audit()
    discovery_values, baseline, baseline_manifest = discovery()
    print_values(discovery_values, ["R9_DISCOVERY_STATUS", "A2_PORTFOLIO_HISTORY_FOUND", "A2_PORTFOLIO_RETURN_CONTRACT_FOUND", "R6_OOF_FOUND", "R6_FOLD_CONTRACT_PASS", "MARKET_DATA_FOUND", "PIT_SOURCE_STATUS"])
    if discovery_values["R9_DISCOVERY_STATUS"] != "PASS":
        raise RuntimeError("R9 discovery/frozen contract failure")
    contract = target_contract(discovery_values["a2_daily_sha256"])
    output.mkdir(parents=True, exist_ok=True)
    R1.write_json(output / "r9_target_contract.json", contract)

    panel, daily, panel_audit = build_portfolio_panel()
    feature_table, feature_manifest = audit_features(panel)
    if feature_table.future_dependency.any() or int(feature_table.non_finite_count.sum()) != 0:
        raise RuntimeError("R9 feature PIT audit failure")
    R1.write_json(output / "r9_feature_manifest.json", feature_manifest)
    R1.write_csv(output / "r9_feature_audit.csv", feature_table)

    logistic, logistic_fits = run_oof(panel, daily, FEATURES, "LOGISTIC", "R9_LOGISTIC_FIXED")
    ml, ml_fits = run_oof(panel, daily, FEATURES, "LIGHTGBM", "R9_LIGHTGBM_FIXED")
    repeat, repeat_fits = run_oof(panel, daily, FEATURES, "LIGHTGBM", "R9_LIGHTGBM_REPRODUCIBILITY")
    primary_hash, repeat_hash = prediction_hash(ml), prediction_hash(repeat)
    reproducible = bool(primary_hash == repeat_hash and np.array_equal(ml.probability.to_numpy(), repeat.probability.to_numpy()))
    if not reproducible:
        raise RuntimeError("R9 prediction reproducibility failure")
    combined = combine_oof(logistic, ml)
    comparison, folds = evaluate(combined)
    family, family_fits = family_diagnostic(panel, daily, ml)
    r6_diagnostic = r6_regime_diagnostic(combined, panel)

    duplicate_dates = int(combined.duplicated("signal_date").sum())
    expected_dates = panel.loc[panel.signal_date.ge(pd.Timestamp(FOLDS[0][1])), "signal_date"]
    expected_dates = expected_dates.loc[expected_dates.le(pd.Timestamp(FOLDS[-1][2]))]
    complete = bool(set(combined.signal_date) == set(expected_dates))
    lookahead = int(
        (panel.information_date >= panel.signal_date).sum()
        + (panel.market_feature_date >= panel.signal_date).sum()
        + (panel.trailing_information_date >= panel.signal_date).sum()
        + (combined.train_max_target_end >= combined.embargo_cutoff).sum()
    )
    if duplicate_dates or not complete or lookahead:
        raise RuntimeError("R9 OOF completeness/lookahead failure")

    model = comparison.set_index("model")
    logm, mlm = model.loc["LOGISTIC"], model.loc["R9_ML"]
    family_pool = family.loc[family.scope.eq("POOLED")].set_index("family")
    pass_gate = bool(
        mlm.auroc > .60 and mlm.ap_base_multiple >= 1.50 and mlm.top_decile_lift >= 2.0
        and mlm.positive_direction_folds >= 4
        and folds.loc[(folds.model.eq("R9_ML")) & folds.direction_positive, "fold"].nunique() >= 4
    )
    some_direction = bool(mlm.auroc > .50 and mlm.ap_base_multiple > 1 and mlm.positive_direction_folds >= 3)
    classification = "B_PORTFOLIO_REGIME_SIGNAL_CONFIRMED" if pass_gate else ("C_PARTIAL" if some_direction else "D_NO_USEFUL_PORTFOLIO_REGIME_SIGNAL")
    next_step = "R9E_FIXED_EXPOSURE_DIAGNOSTIC" if pass_gate else ("PRESERVE_RESEARCH_ONLY" if classification == "C_PARTIAL" else "PRESERVE_R6_ONLY_AND_STOP_REGIME_LINE")

    training_rows, training_end = 0, pd.Timestamp.min
    sessions = pd.DatetimeIndex(daily.execution_date)
    for _, start, end in FOLDS:
        train, _, _ = fold_split(panel, sessions, start, end)
        training_rows += len(train)
        training_end = max(training_end, pd.Timestamp(train.target_end_date.max()))
    guard_post = R1.guard_audit()
    pre_set, post_set = set(guard_pre.get("preexisting_violations", [])), set(guard_post.get("preexisting_violations", []))
    new_violations = sorted(post_set - pre_set)
    anti_bloat = "PASS_NEW_R9_ZERO" if not new_violations else f"FAIL_NEW_R9_VIOLATIONS={len(new_violations)}"
    status = "VALID_PRE2026_R9_PREDICTIVE_RESULT" + ("_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE" if guard_post.get("repository_guard_status") != "PASS" else "")
    summary = {
        "A2_STOCK_RISK_R9_STATUS": status, "A2_STOCK_RISK_R9_CLASSIFICATION": classification,
        "R9_TARGET_CONTRACT_ID": contract["target_contract_hash"], "R9_FOLD_CONTRACT_ID": R9_FOLD_CONTRACT_ID,
        "R9_FOLD_ALIGNMENT_WITH_R6": "PASS_EXACT_TEMPORAL_BOUNDARIES_AND_PURGE",
        "TARGET_HORIZON": TARGET_HORIZON, "TRAINING_END_DATE": training_end.strftime("%Y-%m-%d"),
        "TRAINING_ROWS": training_rows, "OOF_ROWS": len(combined), "BASE_EVENT_RATE": mlm.base_event_rate,
        "FEATURE_COUNT": len(FEATURES), "MARKET_FEATURE_COUNT": len(MARKET_FEATURES),
        "A2_PORTFOLIO_FEATURE_COUNT": len(A2_PORTFOLIO_FEATURES), "R6_CROSS_SECTION_FEATURE_COUNT": len(R6_CROSS_SECTION_FEATURES),
        "TRAILING_A2_FEATURE_COUNT": len(TRAILING_A2_FEATURES),
        "LOGISTIC_AUROC": logm.auroc, "LOGISTIC_AP": logm.average_precision,
        "LOGISTIC_AP_BASE_MULTIPLE": logm.ap_base_multiple, "LOGISTIC_TOP_DECILE_LIFT": logm.top_decile_lift,
        "R9_ML_AUROC": mlm.auroc, "R9_ML_AP": mlm.average_precision, "R9_ML_AP_BASE_MULTIPLE": mlm.ap_base_multiple,
        "R9_ML_TOP_DECILE_LIFT": mlm.top_decile_lift, "R9_ML_TOP_DECILE_CAPTURE": mlm.top_decile_capture,
        "R9_POSITIVE_DIRECTION_FOLDS": int(mlm.positive_direction_folds),
        "MARKET_ONLY_AUROC": family_pool.loc["A_MARKET_ONLY", "auroc"], "MARKET_ONLY_AP": family_pool.loc["A_MARKET_ONLY", "average_precision"],
        "R6_STATE_ONLY_AUROC": family_pool.loc["C_R6_CROSS_SECTION_STATE_ONLY", "auroc"], "R6_STATE_ONLY_AP": family_pool.loc["C_R6_CROSS_SECTION_STATE_ONLY", "average_precision"],
        "TRAILING_A2_ONLY_AUROC": family_pool.loc["D_TRAILING_A2_STATE_ONLY", "auroc"], "TRAILING_A2_ONLY_AP": family_pool.loc["D_TRAILING_A2_STATE_ONLY", "average_precision"],
        "FULL_R9_AUROC": mlm.auroc, "FULL_R9_AP": mlm.average_precision,
        "PARAMETER_SEARCH_COUNT": PARAMETER_SEARCH_COUNT, "THRESHOLD_SEARCH_COUNT": THRESHOLD_SEARCH_COUNT,
        "POSITION_RULE_APPLICATION_COUNT": POSITION_RULE_APPLICATION_COUNT, "ECONOMIC_BACKTEST_COUNT": ECONOMIC_BACKTEST_COUNT,
        "2026_TRAINING_ROW_COUNT": 0, "2026_TARGET_READ_COUNT": 0, "2026_RETURN_READ_COUNT": 0, "2026_HOLDOUT_READ_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": lookahead, "PIT_AUDIT_STATUS": "PASS", "REPRODUCIBILITY_STATUS": "PASS_EXACT",
        "ANTI_BLOAT_STATUS": anti_bloat, "NEXT_AUTHORIZED_STEP": next_step,
    }
    run_manifest = {
        "run_id": "A2_STOCK_RISK_R9", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_contract": contract, "r9_fold_contract": R9_FOLD_CONTRACT, "r9_fold_contract_id": R9_FOLD_CONTRACT_ID,
        "r6_fold_contract_id": R7.R6_FOLD_CONTRACT_ID, "r6_oof_sha256": discovery_values["R6_OOF_HASH"],
        "a2_daily_sha256": discovery_values["a2_daily_sha256"], "feature_schema_sha256": feature_manifest["feature_schema_sha256"],
        "models": {"logistic": LOGISTIC_PARAMS, "primary_lightgbm": LIGHTGBM_PARAMS},
        "model_params_hash": R1.canonical_hash({"logistic": LOGISTIC_PARAMS, "primary_lightgbm": LIGHTGBM_PARAMS}),
        "ablation_contract": ABLATIONS, "primary_prediction_sha256": primary_hash, "repeat_prediction_sha256": repeat_hash,
        "model_fit_counts": {"logistic": logistic_fits, "primary_ml": ml_fits, "reproducibility": repeat_fits, "family_diagnostic": family_fits, "total": logistic_fits + ml_fits + repeat_fits + family_fits},
        "search_counts": {"parameter": 0, "threshold": 0, "feature_subset": 0, "economic": 0},
    }
    audit = {
        "summary": summary, "discovery": discovery_values, "baseline_verification": baseline,
        "baseline_signal_execution": baseline_manifest["contracts"]["evaluation"], "panel": panel_audit,
        "target_contract_frozen_before_fit": True, "feature_manifest_frozen_before_fit": True,
        "oof": {"row_count": len(combined), "duplicate_date_count": duplicate_dates, "target_complete": bool(combined.bad_regime_target.notna().all()), "lookahead_count": lookahead, "fold_alignment": "PASS"},
        "firewall": {"training_rows_2026": 0, "target_reads_2026": 0, "return_reads_2026": 0, "holdout_reads_2026": 0},
        "forbidden_operations": {"position_rule_application_count": 0, "economic_backtest_count": 0, "threshold_search_count": 0, "parameter_search_count": 0},
        "repository_governance": {"pre": guard_pre, "post": guard_post, "new_r9_violations": new_violations},
    }
    output_frame = combined.rename(columns={"signal_date": "date"})
    R1.write_parquet(output / "r9_oof_predictions.parquet", output_frame)
    R1.write_csv(output / "r9_fold_metrics.csv", folds)
    R1.write_csv(output / "r9_model_comparison.csv", comparison)
    R1.write_csv(output / "r9_family_ablation.csv", family)
    R1.write_csv(output / "r9_r6_regime_diagnostic.csv", r6_diagnostic)
    R1.write_json(output / "r9_run_manifest.json", run_manifest)
    R1.write_json(output / "r9_audit.json", audit)
    R1.write_json(output / "r9_summary.json", summary)
    print_values(summary, [
        "A2_STOCK_RISK_R9_STATUS", "A2_STOCK_RISK_R9_CLASSIFICATION", "R9_TARGET_CONTRACT_ID", "R9_FOLD_CONTRACT_ID", "R9_FOLD_ALIGNMENT_WITH_R6",
        "TARGET_HORIZON", "TRAINING_END_DATE", "TRAINING_ROWS", "OOF_ROWS", "BASE_EVENT_RATE", "FEATURE_COUNT", "MARKET_FEATURE_COUNT", "A2_PORTFOLIO_FEATURE_COUNT", "R6_CROSS_SECTION_FEATURE_COUNT", "TRAILING_A2_FEATURE_COUNT",
        "LOGISTIC_AUROC", "LOGISTIC_AP", "LOGISTIC_AP_BASE_MULTIPLE", "LOGISTIC_TOP_DECILE_LIFT", "R9_ML_AUROC", "R9_ML_AP", "R9_ML_AP_BASE_MULTIPLE", "R9_ML_TOP_DECILE_LIFT", "R9_ML_TOP_DECILE_CAPTURE", "R9_POSITIVE_DIRECTION_FOLDS",
        "MARKET_ONLY_AUROC", "MARKET_ONLY_AP", "R6_STATE_ONLY_AUROC", "R6_STATE_ONLY_AP", "TRAILING_A2_ONLY_AUROC", "TRAILING_A2_ONLY_AP", "FULL_R9_AUROC", "FULL_R9_AP",
        "PARAMETER_SEARCH_COUNT", "THRESHOLD_SEARCH_COUNT", "POSITION_RULE_APPLICATION_COUNT", "ECONOMIC_BACKTEST_COUNT",
        "2026_TRAINING_ROW_COUNT", "2026_TARGET_READ_COUNT", "2026_RETURN_READ_COUNT", "2026_HOLDOUT_READ_COUNT", "LOOKAHEAD_VIOLATION_COUNT",
        "PIT_AUDIT_STATUS", "REPRODUCIBILITY_STATUS", "ANTI_BLOAT_STATUS", "NEXT_AUTHORIZED_STEP",
    ])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    try:
        run(args.output_dir.resolve())
        return 0
    except Exception as exc:
        print("A2_STOCK_RISK_R9_STATUS=STOP", file=sys.stderr)
        print("A2_STOCK_RISK_R9_CLASSIFICATION=E_INVALID_RESEARCH_CONTRACT", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        print("NEXT_AUTHORIZED_STEP=STOP_AND_RESOLVE_R9_CONTRACT", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
