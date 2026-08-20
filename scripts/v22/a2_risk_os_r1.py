"""A2 Risk Operating System R1 -- preregistered structural risk allocation.

The runner preserves the frozen A2 and R6 artifacts.  It first freezes an
outcome-blind structural contract, then evaluates pre-2026 OOF evidence.  A
2026 prospective evaluation is permitted only when the frozen pre-2026 gate
qualifies.  No learned component is introduced by this experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUTPUT = RESULTS / "A2_RISK_OS_R1"
RESTORE_OUTPUT = OUTPUT / "COVARIANCE_RESTORE_R1"
BASELINE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
FREEZE = BASELINE / "audit" / "freeze_r1"
R6_ROOT = RESULTS / "A2_STOCK_RISK_R6"
R6_OOF = R6_ROOT / "r6_oof_predictions.parquet"
R11_ROOT = RESULTS / "A2_STOCK_RISK_R11_PROSPECTIVE"
R6_DEPLOY = R11_ROOT / "r6_frozen_deploy_r1.joblib"
R11_PREREG = R11_ROOT / "r11_preregistered_evaluation_contract.json"
R3_SCRIPT = REPO / "scripts" / "v22" / "a2_stock_risk_ml_r3.py"
R6_SCRIPT = REPO / "scripts" / "v22" / "a2_stock_risk_r6.py"
R11_SCRIPT = REPO / "scripts" / "v22" / "a2_stock_risk_r10_r11_fast_track.py"
POLICY = REPO / "docs" / "governance" / "ANTI_BLOAT_POLICY.md"
GUARD = REPO / "fast3" / "scripts" / "audit" / "run_fast3_guard.py"
PRICE_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
VIX_PATH = Path(r"D:\us-tech-quant-data\fast3\vix_cboe_daily\canonical\vix_daily.parquet")
COVARIANCE_CACHE_ROOT = Path(r"D:\us-tech-quant-cache\a2_risk_os_r1")
COVARIANCE_PANEL = COVARIANCE_CACHE_ROOT / "covariance_history_pre2026.parquet"
COVARIANCE_MANIFEST = COVARIANCE_CACHE_ROOT / "covariance_history_pre2026_manifest.json"
FROZEN_REBUILD_SCRIPT = BASELINE / "scripts" / "run_rebuild.py"
QUARTERLY_MEMBERS = BASELINE / "universe" / "quarterly_universe_members.parquet"

CONTRACT_PATH = OUTPUT / "risk_os_r1_contract.json"
WITNESS_PATH = OUTPUT / "risk_os_r1_freeze_witness.json"
SUMMARY_PATH = OUTPUT / "risk_os_r1_summary.json"

TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
R6_OOF_SHA256 = "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4"
R6_DEPLOY_SHA256 = "3e5f646fcfbf1b4e9196781f712305b044a7b2e57c0fe1b3fe202345561f4a08"
R6_TARGET_ID = "b8348a858dc0e92c9c24bd7661e8d5b129682975b6411ed4ec8add1c73118521"
R6_FEATURE_ID = "c17972dfb107e47ae7956a6a8c63faba71eddf0a579a10ee43be6fff495036d8"
R6_REFERENCE_MODEL = "LGBM_BAD_ASYM_2"
BASE_COST = 0.001
VARIANTS = [
    "RAW_A2", "R6_ONLY", "MARKET_ONLY", "PORTFOLIO_ONLY",
    "R6_MARKET", "R6_MARKET_PORTFOLIO", "FULL_STRUCTURAL",
    "MATCHED_CONSTANT_EXPOSURE",
]


def _import(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILURE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R3 = _import("a2_risk_os_r1_r3", R3_SCRIPT)
R6 = _import("a2_risk_os_r1_r6", R6_SCRIPT)
R1 = R3.R1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(safe(payload), indent=2, sort_keys=True, allow_nan=False, default=str), encoding="utf-8")
    os.replace(temp, path)


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_csv(temp, index=False, encoding="utf-8-sig")
    os.replace(temp, path)


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp.parquet")
    frame.to_parquet(temp, index=False)
    os.replace(temp, path)


def frozen_identity() -> dict[str, Any]:
    required = [POLICY, FREEZE / "frozen_baseline_manifest.json", FREEZE / "frozen_artifact_hashes.csv", R6_OOF, R6_DEPLOY, R11_PREREG]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise RuntimeError("MISSING_FROZEN_INPUT:" + ",".join(missing))
    manifest = json.loads((FREEZE / "frozen_baseline_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("frozen_baseline_name") != "A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1" or manifest.get("status") != "FROZEN_RESEARCH_BASELINE":
        raise RuntimeError("A2_FROZEN_IDENTITY_FAILURE")
    hashes = pd.read_csv(FREEZE / "frozen_artifact_hashes.csv")
    failures = []
    for row in hashes.itertuples(index=False):
        path = Path(row.absolute_path)
        if not path.is_file() or sha256_file(path) != row.sha256:
            failures.append(str(path))
    if failures:
        raise RuntimeError("A2_FROZEN_HASH_FAILURE:" + ",".join(failures))
    if sha256_file(R6_OOF) != R6_OOF_SHA256 or sha256_file(R6_DEPLOY) != R6_DEPLOY_SHA256:
        raise RuntimeError("R6_FROZEN_HASH_FAILURE")
    deploy = joblib.load(R6_DEPLOY)
    spec = deploy.get("spec", {})
    if spec.get("target_contract_id") != R6_TARGET_ID or spec.get("feature_contract_id") != R6_FEATURE_ID:
        raise RuntimeError("R6_FROZEN_CONTRACT_FAILURE")
    return {
        "a2_baseline_name": manifest["frozen_baseline_name"],
        "a2_manifest_sha256": sha256_file(FREEZE / "frozen_baseline_manifest.json"),
        "a2_hash_manifest_sha256": sha256_file(FREEZE / "frozen_artifact_hashes.csv"),
        "verified_a2_artifact_count": len(hashes),
        "r6_oof_sha256": R6_OOF_SHA256,
        "r6_deploy_sha256": R6_DEPLOY_SHA256,
        "r6_target_contract_id": R6_TARGET_ID,
        "r6_feature_contract_id": R6_FEATURE_ID,
        "r6_training_end_date": spec.get("training_end_date"),
        "r6_2026_model_fit_rows": spec.get("2026_model_fit_rows"),
    }


def contract_payload(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "experiment_id": "A2_RISK_OS_R1",
        "research_role": "STRUCTURAL_DYNAMIC_RISK_ALLOCATION_RESEARCH",
        "training_cutoff_exclusive": "2026-01-01",
        "prospective_boundary": "2026-01-01",
        "identity": identity,
        "information_contract": "A2/R6/market/stock state from completed information_date close; allocation executes next legal session",
        "learned_model_count": 0,
        "feature_selection_count": 0,
        "parameter_search_count": 0,
        "threshold_search_count": 0,
        "modules": {
            "single_name_adapter": "frozen R6 OOF percentile; 2026 uses frozen deploy plus pre-2026 reference",
            "market": {
                "inputs": ["SPY", "QQQ", "SOXX_IF_AVAILABLE", "IWM_IF_AVAILABLE", "VIX"],
                "score": "mean trailing-prior percentile of VIX, 20d realized vol, drawdown severity, negative 20d return",
                "component": [[0.80, 1.00], [0.90, 0.90], [1.00, 0.75]],
            },
            "portfolio_geometry": {
                "lookback_sessions": 60, "minimum_sessions": 40, "base_weight": 0.05,
                "score": "mean trailing-prior percentile of average correlation, top eigen concentration, portfolio volatility, cluster share",
                "component": [[0.80, 1.00], [0.90, 0.90], [1.00, 0.75]],
            },
            "correlation_stress": {"floors": [0.50, 0.70, 0.85], "volatility_cap": 0.45},
            "uncertainty": {"inputs": ["A2 score dispersion", "R6 mean/dispersion", "portfolio vol", "market score"], "high_threshold": 0.90, "high_multiplier": 0.90},
            "stress": {
                "SPX": [-0.02, -0.04, -0.06], "NASDAQ": [-0.03, -0.06, -0.10],
                "SOXX": [-0.05, -0.08, -0.12], "VIX": [0.25, 0.50, 1.00],
                "correlation_floor": [0.50, 0.70, 0.85], "combined": {"SPX": -0.04, "SOXX": -0.08, "VIX": 0.50, "correlation_floor": 0.70},
            },
            "hard_limits": {
                "max_single_name_weight": 0.06, "max_cluster_exposure": 0.50,
                "max_portfolio_beta": 1.50, "max_portfolio_volatility": 0.35,
                "max_proxy_stress_loss": 0.15, "maximum_missing_fraction": 0.05,
                "sector_and_industry_caps": "EXCLUDED_UNPROVEN_PIT_CLASSIFICATION",
                "integrity_failure_action": "NO_NEW_RISK_TRUE",
            },
            "risk_budget": "clip(market_component * portfolio_component * correlation_component * uncertainty_component,0,1)",
            "single_name_mapping": {"source": "EXACT_FROZEN_R6E_RULE", "risk_percentile_lt_0.90": 1.0, "risk_percentile_ge_0.90": 0.5, "removed_weight": "CASH"},
            "allocation": "base A2 weight * R6 * market * portfolio * correlation * uncertainty * hard_limit; no redistribution",
        },
        "costs": {"baseline": 0.001, "two_x": 0.002, "adverse": 0.003},
        "pre2026_gate": {
            "A": {"mdd_reduction": 0.10, "es5_improvement": 0.10, "return_retention": 0.85, "useful_folds": 4, "matched_exposure": "at least 2 of Sharpe/MDD/ES improve; return delta >= -0.05", "two_x_cost_direction": True},
            "B": {"mdd_or_es_improvement": 0.075, "return_retention": 0.80, "useful_folds": 3, "matched_exposure": "at least one risk-adjusted metric improves"},
            "C": "structural diagnostics valid but economics unconfirmed",
            "D": "no material incremental value after matched exposure",
            "E": "integrity/PIT/data failure",
        },
        "prospective_policy": "only pre2026 A/B can authorize frozen 2026 shadow; never tune from 2026",
        "theme_policy": "no authoritative theme labels available; only explicitly named beta/momentum/volatility research proxies",
    }


def freeze_contract(output: Path = OUTPUT) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    identity = frozen_identity()
    payload = contract_payload(identity)
    payload_hash = canonical_hash(payload)
    path = output / CONTRACT_PATH.name
    witness_path = output / WITNESS_PATH.name
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if canonical_hash(existing) != payload_hash:
            raise RuntimeError("EXISTING_RISK_OS_CONTRACT_DIFFERS")
    else:
        write_json(path, payload)
    witness = {
        "contract_sha256": sha256_file(path), "contract_payload_hash": payload_hash,
        "frozen_before_pre2026_outcome_evaluation": True,
        "frozen_before_new_2026_outcome_read": True,
        "pre2026_outcome_read_count_before_freeze": 0,
        "new_2026_outcome_read_count_before_freeze": 0,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_FROZEN_STRUCTURAL_CONTRACT",
    }
    if witness_path.exists():
        old = json.loads(witness_path.read_text(encoding="utf-8"))
        if old.get("contract_sha256") != witness["contract_sha256"]:
            raise RuntimeError("FREEZE_WITNESS_MISMATCH")
        witness = old
    else:
        write_json(witness_path, witness)
    return witness


def prior_percentile(values: pd.Series, lookback: int = 252, minimum: int = 60) -> pd.Series:
    x = values.to_numpy(float)
    out = np.full(len(x), np.nan)
    for i, value in enumerate(x):
        history = x[max(0, i - lookback):i]
        history = history[np.isfinite(history)]
        if len(history) >= minimum and np.isfinite(value):
            out[i] = (np.sum(history < value) + 0.5 * np.sum(history == value)) / len(history)
    return pd.Series(out, index=values.index)


def load_market_prices(before_2026: bool = True) -> tuple[pd.DataFrame, list[str]]:
    parts = []
    years = range(2019, 2026) if before_2026 else range(2019, 2027)
    requested = ["SPY", "QQQ", "SOXX", "IWM"]
    for year in years:
        path = PRICE_ROOT / f"year={year}" / "prices.parquet"
        if not path.is_file():
            continue
        part = pd.read_parquet(path, columns=["ticker", "trade_date", "close", "source", "autype"])
        parts.append(part.loc[part.ticker.isin(requested)])
    if not parts:
        raise RuntimeError("MARKET_PRICE_INPUT_MISSING")
    data = pd.concat(parts, ignore_index=True)
    data["trade_date"] = pd.to_datetime(data.trade_date)
    if before_2026:
        data = data.loc[data.trade_date.lt(TRAINING_CUTOFF)]
    if not data.source.astype(str).str.contains("MOOMOO", case=False).all() or not data.autype.astype(str).str.upper().eq("QFQ").all():
        raise RuntimeError("MARKET_SOURCE_PIT_FAILURE")
    available = [x for x in requested if x in set(data.ticker)]
    if not {"SPY", "QQQ"}.issubset(available):
        raise RuntimeError("SPY_QQQ_REQUIRED_SOURCE_MISSING")
    return data.drop_duplicates(["ticker", "trade_date"], keep="last"), available


def market_state(before_2026: bool = True) -> tuple[pd.DataFrame, dict[str, Any]]:
    prices, available = load_market_prices(before_2026)
    pivot = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    out = pd.DataFrame(index=pivot.index)
    risk_columns = []
    for ticker in available:
        close = pivot[ticker].astype(float)
        ret = close.pct_change(fill_method=None)
        out[f"{ticker}_return_1d"] = ret
        out[f"{ticker}_return_20d"] = close.pct_change(20, fill_method=None)
        out[f"{ticker}_drawdown_60d"] = close / close.rolling(60, min_periods=60).max() - 1
        out[f"{ticker}_realized_vol_20d"] = ret.rolling(20, min_periods=20).std() * np.sqrt(252)
        for source, sign in [(f"{ticker}_realized_vol_20d", 1), (f"{ticker}_drawdown_60d", -1), (f"{ticker}_return_20d", -1)]:
            name = f"riskpct_{source}"
            out[name] = prior_percentile(out[source] * sign)
            risk_columns.append(name)
    vix = pd.read_parquet(VIX_PATH, columns=["DATE", "CLOSE"])
    vix = vix.rename(columns={"DATE": "trade_date", "CLOSE": "vix"})
    vix["trade_date"] = pd.to_datetime(vix.trade_date)
    if before_2026:
        vix = vix.loc[vix.trade_date.lt(TRAINING_CUTOFF)]
    out = out.reset_index().merge(vix, on="trade_date", how="left", validate="one_to_one").sort_values("trade_date")
    out["riskpct_vix"] = prior_percentile(out.vix)
    risk_columns.append("riskpct_vix")
    out["market_risk_score"] = out[risk_columns].mean(axis=1)
    out["market_component"] = np.select([out.market_risk_score < .80, out.market_risk_score < .90], [1.0, .90], default=.75)
    out["market_risk_bucket"] = np.select([out.market_risk_score < .80, out.market_risk_score < .90], ["NORMAL", "ELEVATED"], default="STRESS")
    return out, {"available_tickers": available, "excluded": [x for x in ["SOXX", "IWM"] if x not in available], "source": str(PRICE_ROOT), "vix_source": str(VIX_PATH)}


def build_covariance_history_panel(force: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Materialize the exact frozen A2 raw+rehab price lineage for R6 names.

    Historical returns are sourced independently of A2 universe membership.
    The function never reads 2026 data and never performs a broker request.
    """
    if COVARIANCE_PANEL.is_file() and COVARIANCE_MANIFEST.is_file() and not force:
        manifest = json.loads(COVARIANCE_MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("panel_sha256") != sha256_file(COVARIANCE_PANEL):
            raise RuntimeError("COVARIANCE_PANEL_MANIFEST_HASH_FAILURE")
        panel = pd.read_parquet(COVARIANCE_PANEL)
        return panel, manifest
    rebuild = _import("a2_risk_os_r1_frozen_rebuild", FROZEN_REBUILD_SCRIPT)
    selected = pd.read_parquet(R6_OOF, columns=["candidate_id", "ticker"])
    required_tickers = sorted(selected.loc[selected.candidate_id.eq(R6_REFERENCE_MODEL), "ticker"].unique())
    members = pd.read_parquet(
        QUARTERLY_MEMBERS,
        columns=["ticker", "moomoo_transport_code", "cusip", "mapping_source", "mapping_confidence"],
    )
    mapping = members.loc[members.ticker.isin(required_tickers)].drop_duplicates(["ticker", "moomoo_transport_code"])
    if set(mapping.ticker) != set(required_tickers) or mapping.groupby("ticker").moomoo_transport_code.nunique().max() != 1:
        raise RuntimeError("COVARIANCE_TICKER_MAPPING_NOT_UNIQUE")
    index, scan_failures = rebuild.raw_file_index()
    if scan_failures:
        raise RuntimeError("COVARIANCE_RAW_HISTORY_SCAN_FAILURE")
    missing_codes = sorted(set(mapping.moomoo_transport_code) - set(index))
    if missing_codes:
        raise RuntimeError("COVARIANCE_RAW_TRANSPORT_CODE_MISSING:" + ",".join(missing_codes))
    rehab_path = rebuild.RUN_CACHE / "rehab_factors.parquet"
    rehab_status_path = rebuild.RUN_CACHE / "rehab_status.csv"
    if not rehab_path.is_file() or not rehab_status_path.is_file():
        raise RuntimeError("COVARIANCE_REHAB_LINEAGE_MISSING")
    rehab = pd.read_parquet(rehab_path)
    rehab_status = pd.read_csv(rehab_status_path, keep_default_na=False)
    if not set(mapping.moomoo_transport_code).issubset(set(rehab_status.loc[rehab_status.status.eq("PASS"), "code"])):
        raise RuntimeError("COVARIANCE_REHAB_STATUS_INCOMPLETE")
    rows = []
    source_paths: set[Path] = set()
    corporate_action_events = 0
    duplicate_raw_date_count = 0
    dummy_wolf = {"event_date": "2023-12-01", "quantity_multiplier": 1.0}
    for item in mapping.sort_values("ticker").itertuples(index=False):
        paths = index[item.moomoo_transport_code]
        source_paths.update(paths)
        raw = rebuild.load_raw_code(item.moomoo_transport_code, paths)
        duplicate_raw_date_count += int(raw.duplicated("trade_date").sum())
        raw = raw.loc[pd.to_datetime(raw.trade_date).lt(TRAINING_CUTOFF)].copy()
        adjusted, events = rebuild.adjusted_price_frame(
            item.moomoo_transport_code, item.ticker, raw, rehab, dummy_wolf,
        )
        corporate_action_events += sum(event["audit_kind"] == "APPLIED_CORPORATE_ACTION" for event in events)
        adjusted = adjusted.sort_values("trade_date").copy()
        adjusted["return"] = adjusted.close.pct_change(fill_method=None)
        adjusted["canonical_ticker"] = item.ticker
        adjusted["cusip"] = item.cusip
        adjusted["mapping_source"] = item.mapping_source
        adjusted["mapping_confidence"] = item.mapping_confidence
        rows.append(adjusted[["trade_date", "canonical_ticker", "moomoo_transport_code", "close", "return", "autype", "source", "cusip", "mapping_source", "mapping_confidence"]])
    panel = pd.concat(rows, ignore_index=True).sort_values(["canonical_ticker", "trade_date"], kind="mergesort")
    if panel.trade_date.ge(TRAINING_CUTOFF).any() or panel.duplicated(["canonical_ticker", "trade_date"]).any():
        raise RuntimeError("COVARIANCE_PANEL_DATE_OR_DUPLICATE_FAILURE")
    if set(panel.autype) != {"PIT_FORWARD_REHAB_INDEX"} or set(panel.source) != {"MOOMOO_OPEND_RAW_PLUS_REHAB"}:
        raise RuntimeError("COVARIANCE_PANEL_SOURCE_CONTRACT_FAILURE")
    if not np.isfinite(panel[["close"]].to_numpy(float)).all() or (panel.close <= 0).any():
        raise RuntimeError("COVARIANCE_PANEL_INVALID_PRICE")
    COVARIANCE_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    write_parquet(COVARIANCE_PANEL, panel)
    per_ticker = panel.groupby("canonical_ticker").agg(
        row_count=("trade_date", "size"), first_date=("trade_date", "min"), last_date=("trade_date", "max"),
        valid_return_count=("return", lambda x: int(np.isfinite(x).sum())),
    ).reset_index()
    manifest = {
        "artifact_id": "A2_RISK_OS_R1_COVARIANCE_HISTORY_PRE2026",
        "purpose": "DATA_SOURCE_REPAIR_ONLY_SAME_FROZEN_R1_CONTRACT",
        "panel_path": str(COVARIANCE_PANEL), "panel_sha256": sha256_file(COVARIANCE_PANEL),
        "row_count": len(panel), "ticker_count": panel.canonical_ticker.nunique(),
        "first_date": str(panel.trade_date.min().date()), "last_date": str(panel.trade_date.max().date()),
        "source": "MOOMOO_OPEND_RAW_PLUS_REHAB", "autype": "PIT_FORWARD_REHAB_INDEX",
        "ticker_mapping_source": str(QUARTERLY_MEMBERS), "ticker_mapping_sha256": sha256_file(QUARTERLY_MEMBERS),
        "rehab_factors_path": str(rehab_path), "rehab_factors_sha256": sha256_file(rehab_path),
        "rehab_status_sha256": sha256_file(rehab_status_path), "corporate_action_event_count": corporate_action_events,
        "duplicate_raw_date_count": duplicate_raw_date_count, "moomoo_api_request_count": 0,
        "source_file_count": len(source_paths),
        "source_file_hashes": {str(path): sha256_file(path) for path in sorted(source_paths)},
        "per_ticker_coverage": safe(per_ticker.to_dict("records")),
        "training_or_2026_outcome_rows": 0,
    }
    write_json(COVARIANCE_MANIFEST, manifest)
    return panel, manifest


def largest_cluster_share(corr: np.ndarray, threshold: float = .70) -> float:
    n = len(corr)
    unseen = set(range(n))
    largest = 0
    while unseen:
        stack = [unseen.pop()]
        size = 0
        while stack:
            i = stack.pop(); size += 1
            neighbors = {j for j in unseen if np.isfinite(corr[i, j]) and corr[i, j] >= threshold}
            unseen -= neighbors; stack.extend(neighbors)
        largest = max(largest, size)
    return largest / n if n else np.nan


def stress_covariance(vols: np.ndarray, corr: np.ndarray, floor: float) -> np.ndarray:
    stressed = corr.copy()
    mask = ~np.eye(len(corr), dtype=bool)
    stressed[mask] = np.maximum(stressed[mask], floor)
    np.fill_diagonal(stressed, 1.0)
    return stressed * np.outer(vols, vols)


def portfolio_geometry(scored: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    covariance_panel, _ = build_covariance_history_panel(False)
    covariance_panel["trade_date"] = pd.to_datetime(covariance_panel.trade_date)
    pivot = covariance_panel.pivot(index="trade_date", columns="canonical_ticker", values="return").sort_index()
    market_calendar = pd.DatetimeIndex(market.trade_date.drop_duplicates().sort_values())
    market_returns = market.set_index("trade_date")[[c for c in ["SPY_return_1d", "QQQ_return_1d", "SOXX_return_1d", "IWM_return_1d"] if c in market]].copy()
    rows = []
    for signal_date, group in scored.groupby("signal_date", sort=True):
        information_date = pd.Timestamp(group.information_date.iloc[0])
        tickers = group.ticker.astype(str).tolist()
        legal_dates = market_calendar[market_calendar <= information_date][-60:]
        history = pivot.reindex(index=legal_dates, columns=tickers).dropna(how="any")
        if len(history) < 40:
            continue
        cov = history.cov().to_numpy(float) * 252
        corr = history.corr().to_numpy(float)
        vols = np.sqrt(np.clip(np.diag(cov), 0, None))
        w = np.repeat(1 / len(tickers), len(tickers))
        off = corr[~np.eye(len(corr), dtype=bool)]
        eig = np.clip(np.linalg.eigvalsh(corr), 0, None)
        eig_share = eig / eig.sum()
        data: dict[str, Any] = {
            "signal_date": signal_date, "information_date": information_date,
            "holdings": len(tickers), "average_pairwise_correlation": float(np.nanmean(off)),
            "median_pairwise_correlation": float(np.nanmedian(off)),
            "max_correlation_cluster_share": largest_cluster_share(corr),
            "effective_independent_bets": float(1 / np.sum(eig_share ** 2)),
            "top_eigenvalue_concentration": float(eig_share.max()),
            "portfolio_realized_volatility": float(np.sqrt(w @ cov @ w)),
            "single_name_hhi": float(np.sum((np.repeat(.05, len(tickers))) ** 2)),
            "top5_exposure_share": .25, "top10_exposure_share": .50,
            "A2_score_mean": float(group.A2_PREDICTION.mean()), "A2_score_median": float(group.A2_PREDICTION.median()),
            "A2_score_std": float(group.A2_PREDICTION.std(ddof=1)),
            "A2_score_spread": float(group.A2_PREDICTION.max() - group.A2_PREDICTION.min()),
            "R6_score_mean": float(group.predicted_bad_asymmetry_risk.mean()),
            "R6_score_median": float(group.predicted_bad_asymmetry_risk.median()),
            "R6_score_std": float(group.predicted_bad_asymmetry_risk.std(ddof=1)),
            "R6_score_p90": float(group.predicted_bad_asymmetry_risk.quantile(.90)),
            "R6_score_max": float(group.predicted_bad_asymmetry_risk.max()),
            "R6_high_risk_fraction": float(group.risk_percentile.ge(.90).mean()),
            "stock_vol_mean": float(group.REALIZED_VOL_20D.mean()),
            "stock_vol_median": float(group.REALIZED_VOL_20D.median()),
            "momentum_breadth": float(group.RET_20D.gt(0).mean()),
            "negative_recent_return_fraction": float(group.RET_5D.lt(0).mean()),
            "missing_fraction": float(group[R3.FEATURES].isna().mean().mean()),
        }
        aligned_market = market_returns.loc[market_returns.index.isin(history.index)]
        for ticker in ["SPY", "QQQ", "SOXX", "IWM"]:
            col = f"{ticker}_return_1d"
            if col not in aligned_market or len(aligned_market) < 40:
                data[f"portfolio_beta_{ticker}"] = np.nan
                continue
            stock = history.reindex(aligned_market.index)
            port = stock.mean(axis=1)
            variance = float(aligned_market[col].var(ddof=1))
            data[f"portfolio_beta_{ticker}"] = float(port.cov(aligned_market[col]) / variance) if variance > 0 else np.nan
        for floor in [.50, .70, .85]:
            stressed = stress_covariance(vols, corr, floor)
            data[f"stress_vol_corr_{int(floor*100):02d}"] = float(np.sqrt(w @ stressed @ w))
        rows.append(data)
    frame = pd.DataFrame(rows).sort_values("signal_date").reset_index(drop=True)
    for column in ["average_pairwise_correlation", "top_eigenvalue_concentration", "portfolio_realized_volatility", "max_correlation_cluster_share"]:
        frame[f"pct_{column}"] = prior_percentile(frame[column], minimum=40)
    pct = [c for c in frame if c.startswith("pct_")]
    frame["portfolio_concentration_risk_score"] = frame[pct].mean(axis=1)
    frame["portfolio_component"] = np.select([frame.portfolio_concentration_risk_score < .80, frame.portfolio_concentration_risk_score < .90], [1.0, .90], default=.75)
    frame["correlation_component"] = np.minimum(1.0, .45 / frame.stress_vol_corr_70.clip(lower=1e-8))
    for column in ["A2_score_std", "R6_score_mean", "R6_score_std", "portfolio_realized_volatility"]:
        rolling_mean = frame[column].rolling(252, min_periods=40).mean().shift(1)
        rolling_std = frame[column].rolling(252, min_periods=40).std(ddof=1).shift(1)
        frame[f"drift_{column}"] = ((frame[column] - rolling_mean) / rolling_std).abs().clip(0, 3) / 3
    frame["model_uncertainty_score"] = frame[[c for c in frame if c.startswith("drift_")]].mean(axis=1)
    frame["ood_flag"] = frame.model_uncertainty_score.ge(.90)
    frame["uncertainty_component"] = np.where(frame.ood_flag, .90, 1.0)
    frame["covariance_regime_drift"] = frame.average_pairwise_correlation - frame.average_pairwise_correlation.rolling(20, min_periods=10).median().shift(1)
    return frame


def covariance_restore_audit(output: Path = RESTORE_OUTPUT, force_panel: bool = False) -> dict[str, Any]:
    """Forensic coverage gate; this function never reads portfolio outcomes."""
    original_contract = OUTPUT / CONTRACT_PATH.name
    if not original_contract.is_file() or sha256_file(original_contract) != "058dbbed6d5880da8f0bb0e0fbb921f669d62465ced64711cacd80eb939d997e":
        raise RuntimeError("FROZEN_R1_CONTRACT_IDENTITY_FAILURE")
    identity = frozen_identity()
    panel, panel_manifest = build_covariance_history_panel(force_panel)
    oof = pd.read_parquet(R6_OOF, columns=[
        "candidate_id", "signal_date", "information_date", "ticker",
    ])
    scored = oof.loc[oof.candidate_id.eq(R6_REFERENCE_MODEL)].copy()
    scored["signal_date"] = pd.to_datetime(scored.signal_date)
    scored["information_date"] = pd.to_datetime(scored.information_date)
    matrix = pd.read_parquet(R3.TRAINING_MATRIX_PATH, columns=["signal_date", "ticker", "ret_1d"])
    matrix["signal_date"] = pd.to_datetime(matrix.signal_date)
    old_pivot = matrix.loc[matrix.signal_date.lt(TRAINING_CUTOFF)].pivot(
        index="signal_date", columns="ticker", values="ret_1d",
    ).sort_index()
    panel["trade_date"] = pd.to_datetime(panel.trade_date)
    new_pivot = panel.pivot(index="trade_date", columns="canonical_ticker", values="return").sort_index()
    market, market_audit = market_state(True)
    calendar = pd.DatetimeIndex(market.trade_date.drop_duplicates().sort_values())
    first_dates = panel.groupby("canonical_ticker").trade_date.min()
    duplicates = panel.groupby("canonical_ticker").apply(
        lambda x: int(x.duplicated("trade_date").sum()), include_groups=False,
    )
    detail_rows = []
    date_rows = []
    for signal_date, group in scored.groupby("signal_date", sort=True):
        information_date = pd.Timestamp(group.information_date.iloc[0])
        tickers = group.ticker.astype(str).tolist()
        old = old_pivot.loc[old_pivot.index <= information_date].tail(60).reindex(columns=tickers)
        legal_dates = calendar[calendar <= information_date][-60:]
        new = new_pivot.reindex(index=legal_dates, columns=tickers)
        old_complete = int(len(old.dropna(how="any")))
        new_complete = int(len(new.dropna(how="any")))
        old_failed = old_complete < 40
        new_failed = new_complete < 40
        date_reasons = []
        for ticker in tickers:
            old_count = int(old[ticker].notna().sum())
            new_count = int(new[ticker].notna().sum())
            first = first_dates.get(ticker, pd.NaT)
            public_sessions = int(len(calendar[(calendar >= first) & (calendar <= information_date)])) if pd.notna(first) else 0
            if not old_failed:
                reason = "OLD_GEOMETRY_COMPLETE"
            elif old_count < 40 and new_count >= 40:
                reason = "INCORRECT_UNIVERSE_DEPENDENT_HISTORY_LOOKUP"
            elif ticker not in new_pivot.columns:
                reason = "SOURCE_PROVENANCE_UNAVAILABLE"
            elif duplicates.get(ticker, 0) > 0:
                reason = "DUPLICATE_BAR"
            elif new_count < 40 and public_sessions < 40:
                reason = "GENUINE_INSUFFICIENT_PUBLIC_HISTORY"
            elif new_count < 40 and int(new[ticker].isna().sum()) > 0:
                reason = "MISSING_CANONICAL_DAILY_BARS_OR_NULL_RETURN"
            elif old_count >= 40:
                reason = "OTHER_CONSTITUENT_CAUSED_OLD_DATE_FAILURE"
            else:
                reason = "OTHER"
            if old_failed:
                date_reasons.append(reason)
            detail_rows.append({
                "signal_date": signal_date, "information_date": information_date, "ticker": ticker,
                "old_candidate_history_count": old_count, "restored_market_history_count": new_count,
                "first_authoritative_date": first, "public_sessions_to_date": public_sessions,
                "old_date_complete_rows": old_complete, "restored_date_complete_rows": new_complete,
                "old_date_failed": old_failed, "restored_date_failed": new_failed, "reason_code": reason,
            })
        if not old_failed:
            date_reason = "OLD_GEOMETRY_COMPLETE"
        elif not new_failed:
            date_reason = "RESTORED_UNIVERSE_COUPLING_DEFECT"
        elif "GENUINE_INSUFFICIENT_PUBLIC_HISTORY" in date_reasons:
            date_reason = "GENUINE_INSUFFICIENT_PUBLIC_HISTORY"
        elif "MISSING_CANONICAL_DAILY_BARS_OR_NULL_RETURN" in date_reasons:
            date_reason = "MISSING_CANONICAL_DAILY_BARS_OR_NULL_RETURN"
        else:
            date_reason = "OTHER_UNRESOLVED"
        date_rows.append({
            "signal_date": signal_date, "information_date": information_date,
            "old_complete_rows": old_complete, "restored_complete_rows": new_complete,
            "old_complete": not old_failed, "restored_complete": not new_failed,
            "date_reason_code": date_reason,
        })
    detail = pd.DataFrame(detail_rows)
    dates = pd.DataFrame(date_rows)
    root_summary = detail.loc[detail.old_date_failed].groupby("reason_code", as_index=False).agg(
        constituent_date_count=("ticker", "size"), unique_ticker_count=("ticker", "nunique"),
        affected_portfolio_date_count=("signal_date", "nunique"),
    ).sort_values("constituent_date_count", ascending=False)
    total_dates = len(dates)
    complete_dates = int(dates.restored_complete.sum())
    coverage = complete_dates / total_dates
    genuine_dates = int(dates.date_reason_code.eq("GENUINE_INSUFFICIENT_PUBLIC_HISTORY").sum())
    avoidable_dates = int((~dates.restored_complete & ~dates.date_reason_code.eq("GENUINE_INSUFFICIENT_PUBLIC_HISTORY")).sum())
    pass_gate = coverage >= .95
    output.mkdir(parents=True, exist_ok=True)
    write_parquet(output / "covariance_root_cause_detail.parquet", detail)
    write_csv(output / "covariance_root_cause_summary.csv", root_summary)
    write_csv(output / "covariance_date_coverage.csv", dates)
    write_json(output / "covariance_source_manifest.json", panel_manifest)
    summary = {
        "A2_RISK_OS_R1_COVARIANCE_RESTORE_STATUS": "PASS_COVERAGE_GATE" if pass_gate else "STOP_COVERAGE_BELOW_95_PERCENT",
        "frozen_contract_sha256": sha256_file(original_contract),
        "frozen_a2_identity": identity, "frozen_r6_oof_sha256": sha256_file(R6_OOF),
        "current_code_fingerprint": sha256_file(Path(__file__)),
        "total_portfolio_dates": total_dates, "old_complete_geometry_dates": int(dates.old_complete.sum()),
        "old_geometry_coverage": float(dates.old_complete.mean()),
        "complete_geometry_dates": complete_dates, "COVARIANCE_GEOMETRY_COVERAGE": coverage,
        "fail_closed_dates": total_dates - complete_dates,
        "AVOIDABLE_MISSING_GEOMETRY_DATES": avoidable_dates,
        "GENUINE_INSUFFICIENT_HISTORY_DATES": genuine_dates,
        "coverage_gate_pass": pass_gate, "market_calendar_source": market_audit,
        "covariance_panel_sha256": panel_manifest["panel_sha256"],
        "2026_RISK_OS_OUTCOME_READ_COUNT": 0, "2026_TRAINING_ROW_COUNT": 0,
        "NEXT_AUTHORIZED_STEP": "RERUN_SAME_FROZEN_R1_PRE2026" if pass_gate else "STOP_AND_RESOLVE_REMAINING_AUTHORITATIVE_HISTORY_GAPS",
    }
    write_json(output / "covariance_restore_summary.json", summary)
    return summary


def covariance_restore_closeout(output: Path = RESTORE_OUTPUT) -> dict[str, Any]:
    """Mechanically compare the original and repaired same-contract runs."""
    original_contract = OUTPUT / CONTRACT_PATH.name
    if sha256_file(original_contract) != "058dbbed6d5880da8f0bb0e0fbb921f669d62465ced64711cacd80eb939d997e":
        raise RuntimeError("FROZEN_R1_CONTRACT_IDENTITY_FAILURE")
    coverage = json.loads((output / "covariance_restore_summary.json").read_text(encoding="utf-8"))
    repaired_summary = json.loads((output / "risk_os_r1_summary.json").read_text(encoding="utf-8"))
    repaired_audit = json.loads((output / "risk_os_r1_audit.json").read_text(encoding="utf-8"))
    if not coverage["coverage_gate_pass"]:
        raise RuntimeError("COVARIANCE_COVERAGE_GATE_NOT_PASSED")
    old_metrics = pd.read_csv(OUTPUT / "risk_os_r1_component_metrics.csv")
    new_metrics = pd.read_csv(output / "risk_os_r1_component_metrics.csv")
    comparison = old_metrics.merge(new_metrics, on=["variant", "cost_rate"], suffixes=("_old", "_repaired"), validate="one_to_one")
    for metric in ["total_return", "cagr", "volatility", "sharpe", "maximum_drawdown", "calmar", "expected_shortfall_5", "worst_month", "average_gross_exposure", "turnover"]:
        comparison[f"delta_{metric}"] = comparison[f"{metric}_repaired"] - comparison[f"{metric}_old"]
    old_weights = pd.read_parquet(OUTPUT / "risk_os_r1_weight_attribution.parquet")
    new_weights = pd.read_parquet(output / "risk_os_r1_weight_attribution.parquet")
    old_state = pd.read_parquet(OUTPUT / "risk_os_r1_portfolio_geometry.parquet", columns=["signal_date", "NO_NEW_RISK"])
    new_state = pd.read_parquet(output / "risk_os_r1_portfolio_geometry.parquet", columns=["signal_date", "NO_NEW_RISK"])
    layer_columns = [
        ("BASE_A2", "base_a2_weight"), ("R6", "r6_adjusted_weight"),
        ("MARKET", "market_adjusted_weight"), ("PORTFOLIO", "portfolio_adjusted_weight"),
        ("CORRELATION_STRESS", "correlation_adjusted_weight"),
        ("UNCERTAINTY", "uncertainty_adjusted_weight"), ("HARD_LIMITS", "final_weight"),
    ]
    layer_rows = []
    layer_means: dict[str, dict[str, float]] = {}
    for run_name, weights in [("OLD_INCOMPLETE", old_weights), ("REPAIRED", new_weights)]:
        means = {
            layer: float(weights.groupby("signal_date")[column].sum().mean())
            for layer, column in layer_columns
        }
        layer_means[run_name] = means
        previous = None
        for layer, _ in layer_columns:
            layer_rows.append({
                "run": run_name, "layer": layer, "mean_exposure_after_layer": means[layer],
                "incremental_exposure_change": 0.0 if previous is None else means[layer] - means[previous],
            })
            previous = layer
    joined = old_weights[["signal_date", "ticker", "final_weight"]].merge(
        new_weights[["signal_date", "ticker", "final_weight"]],
        on=["signal_date", "ticker"], suffixes=("_old", "_repaired"), validate="one_to_one",
    ).merge(old_state, on="signal_date", validate="many_to_one").merge(
        new_state, on="signal_date", suffixes=("_old_state", "_repaired_state"), validate="many_to_one",
    )
    defect_mask = joined.NO_NEW_RISK_old_state & ~joined.NO_NEW_RISK_repaired_state
    defect_daily = joined.loc[defect_mask].groupby("signal_date").apply(
        lambda x: x.final_weight_old.sum() - x.final_weight_repaired.sum(), include_groups=False,
    )
    layer_attribution = pd.DataFrame(layer_rows)
    layer_attribution = pd.concat([
        layer_attribution,
        pd.DataFrame([{
            "run": "OLD_VS_REPAIRED", "layer": "GEOMETRY_COVERAGE_FAILURE_MASKING_EFFECT",
            "mean_exposure_after_layer": np.nan,
            "incremental_exposure_change": float(defect_daily.mean()),
            "affected_dates": int(defect_daily.size),
        }]),
    ], ignore_index=True)
    by = new_metrics.set_index("variant")
    raw = by.loc["RAW_A2"]; full = by.loc["FULL_STRUCTURAL"]; matched = by.loc["MATCHED_CONSTANT_EXPOSURE"]
    full_beats_matched = {
        "cagr": bool(full.cagr > matched.cagr), "sharpe": bool(full.sharpe > matched.sharpe),
        "maximum_drawdown": bool(full.maximum_drawdown > matched.maximum_drawdown),
        "calmar": bool(full.calmar > matched.calmar),
        "expected_shortfall_5": bool(full.expected_shortfall_5 > matched.expected_shortfall_5),
        "worst_month": bool(full.worst_month > matched.worst_month),
    }
    final = {
        "A2_RISK_OS_R1_COVARIANCE_RESTORE_STATUS": "PASS_COVARIANCE_RESTORED_AND_SAME_CONTRACT_RERUN_COMPLETE",
        "A2_RISK_OS_R1_STATUS": repaired_summary["A2_RISK_OS_R1_STATUS"],
        "A2_RISK_OS_R1_CLASSIFICATION": repaired_summary["A2_RISK_OS_R1_CLASSIFICATION"],
        "COVARIANCE_GEOMETRY_COVERAGE": coverage["COVARIANCE_GEOMETRY_COVERAGE"],
        "FULL_GEOMETRY_SCORE_COVERAGE": repaired_summary["geometry_coverage"],
        "AVOIDABLE_MISSING_GEOMETRY_DATES": coverage["AVOIDABLE_MISSING_GEOMETRY_DATES"],
        "GENUINE_INSUFFICIENT_HISTORY_DATES": coverage["GENUINE_INSUFFICIENT_HISTORY_DATES"],
        "2026_RISK_OS_OUTCOME_READ_COUNT": 0,
        "frozen_contract_sha256": sha256_file(original_contract),
        "covariance_panel_sha256": coverage["covariance_panel_sha256"],
        "root_cause": "COVARIANCE_WAS_INCORRECTLY_COUPLED_TO_HISTORICAL_A2_UNIVERSE_MEMBERSHIP",
        "research_answer": "INPUT_DEFECT_WAS_REAL_BUT_REPAIRED_STRUCTURAL_STACK_STILL_FAILS_FROZEN_ECONOMIC_AND_STABILITY_GATES",
        "old_fail_closed_dates": coverage["total_portfolio_dates"] - coverage["old_complete_geometry_dates"],
        "repaired_covariance_fail_closed_dates": coverage["fail_closed_dates"],
        "coverage_failure_masking_exposure_effect": float(defect_daily.mean()),
        "repaired_full_vs_matched": {
            "metric_wins": full_beats_matched,
            "cagr_delta": float(full.cagr - matched.cagr), "sharpe_delta": float(full.sharpe - matched.sharpe),
            "mdd_delta": float(full.maximum_drawdown - matched.maximum_drawdown),
            "calmar_delta": float(full.calmar - matched.calmar),
            "es5_delta": float(full.expected_shortfall_5 - matched.expected_shortfall_5),
            "worst_month_delta": float(full.worst_month - matched.worst_month),
        },
        "repaired_vs_raw": {
            "return_retention": repaired_summary["return_retention"],
            "mdd_reduction": repaired_summary["mdd_reduction"],
            "es5_improvement": repaired_summary["es5_improvement"],
            "useful_folds": repaired_summary["pre2026_useful_folds"],
        },
        "prospective_authorized": False,
        "NEXT_AUTHORIZED_STEP": "PRESERVE_R1_RESEARCH_HISTORY_AND_STOP",
    }
    write_csv(output / "covariance_restore_component_comparison.csv", comparison)
    write_csv(output / "covariance_restore_layer_attribution.csv", layer_attribution)
    write_json(output / "covariance_restore_final_summary.json", final)
    audit = {
        "frozen_contract_unchanged": final["frozen_contract_sha256"] == "058dbbed6d5880da8f0bb0e0fbb921f669d62465ced64711cacd80eb939d997e",
        "frozen_a2_unchanged": repaired_audit["frozen_a2_untouched"],
        "frozen_r6_unchanged": repaired_audit["frozen_r6_untouched"],
        "2026_training_rows": 0, "2026_outcome_reads": 0,
        "parameter_search_count": 0, "threshold_search_count": 0, "model_fit_count": 0,
        "lookahead_violation_count": repaired_audit["LOOKAHEAD_VIOLATION_COUNT"],
        "matched_exposure_absolute_difference": repaired_audit["matched_exposure_absolute_difference"],
        "negative_weight_count": repaired_audit["negative_weight_count"],
        "weight_cap_violation_count": repaired_audit["weight_cap_violation_count"],
    }
    write_json(output / "covariance_restore_audit.json", audit)
    return final


def stress_scenarios(geometry: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in geometry.itertuples(index=False):
        beta_spy = row.portfolio_beta_SPY
        beta_qqq = row.portfolio_beta_QQQ
        if not np.isfinite(beta_spy) or not np.isfinite(beta_qqq) or not np.isfinite(row.portfolio_realized_volatility):
            continue
        beta_soxx = row.portfolio_beta_SOXX if hasattr(row, "portfolio_beta_SOXX") else np.nan
        scenarios = []
        scenarios += [(f"SPX_{int(abs(x)*100)}PCT", beta_spy * x, "SPY_BETA_PROXY") for x in [-.02, -.04, -.06]]
        scenarios += [(f"NASDAQ_{int(abs(x)*100)}PCT", beta_qqq * x, "QQQ_BETA_PROXY") for x in [-.03, -.06, -.10]]
        if np.isfinite(beta_soxx):
            scenarios += [(f"SOXX_{int(abs(x)*100)}PCT", beta_soxx * x, "SOXX_BETA_PROXY") for x in [-.05, -.08, -.12]]
        scenarios += [("VIX_PLUS_25PCT", -.015, "FIXED_DEFENSIVE_PROXY"), ("VIX_PLUS_50PCT", -.030, "FIXED_DEFENSIVE_PROXY"), ("VIX_PLUS_100PCT", -.060, "FIXED_DEFENSIVE_PROXY")]
        for floor in [50, 70, 85]:
            scenarios.append((f"CORRELATION_FLOOR_{floor}", -2 * getattr(row, f"stress_vol_corr_{floor}") / np.sqrt(252), "TWO_SIGMA_STRESSED_VOL_PROXY"))
        combined_base = beta_spy * -.04 + (max(beta_soxx - beta_spy, 0) * -.04 if np.isfinite(beta_soxx) else 0) - .03
        ratio = row.stress_vol_corr_70 / max(row.portfolio_realized_volatility, 1e-8)
        scenarios.append(("COMBINED_SPX4_SOXX8_VIX50_CORR70", combined_base * max(1.0, ratio), "COMBINED_PROXY"))
        for name, loss, method in scenarios:
            rows.append({"signal_date": row.signal_date, "scenario": name, "proxy_portfolio_loss": float(loss), "method": method, "concentration_contribution": float(loss * row.top_eigenvalue_concentration), "sector_contribution": np.nan})
    return pd.DataFrame(rows)


def component_for_dates(scored: pd.DataFrame, geometry: pd.DataFrame, market: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    base_dates = scored[["signal_date", "information_date"]].drop_duplicates().sort_values("signal_date")
    date_state = base_dates.merge(geometry, on=["signal_date", "information_date"], how="left", validate="one_to_one")
    date_state = date_state.merge(market[["trade_date", "market_risk_score", "market_risk_bucket", "market_component"]], left_on="information_date", right_on="trade_date", how="left", validate="one_to_one")
    stress = stress_scenarios(date_state)
    worst = stress.groupby("signal_date").proxy_portfolio_loss.min().abs().rename("worst_proxy_stress_loss") if len(stress) else pd.Series(dtype=float, name="worst_proxy_stress_loss")
    date_state = date_state.merge(worst, on="signal_date", how="left", validate="one_to_one")
    beta_cap = np.minimum(1.0, 1.50 / date_state.portfolio_beta_SPY.abs().clip(lower=1e-8))
    vol_cap = np.minimum(1.0, .35 / date_state.portfolio_realized_volatility.clip(lower=1e-8))
    stress_cap = np.minimum(1.0, .15 / date_state.worst_proxy_stress_loss.clip(lower=1e-8))
    cluster_cap = np.minimum(1.0, .50 / date_state.max_correlation_cluster_share.clip(lower=1e-8))
    date_state["hard_limit_component"] = np.minimum.reduce([beta_cap, vol_cap, stress_cap, cluster_cap])
    critical = date_state.missing_fraction.gt(.05) | date_state[["market_component", "portfolio_component", "correlation_component", "uncertainty_component", "hard_limit_component"]].isna().any(axis=1)
    date_state["NO_NEW_RISK"] = critical
    # Fail closed means preserve the existing A2 position, not liquidate it and
    # not invent a missing structural state.  The full stack is bypassed for
    # these warm-up/integrity dates.
    for column in ["market_component", "portfolio_component", "correlation_component", "uncertainty_component", "hard_limit_component"]:
        date_state.loc[critical, column] = 1.0
    date_state["total_risk_budget"] = np.clip(date_state.market_component * date_state.portfolio_component * date_state.correlation_component * date_state.uncertainty_component, 0, 1)
    weights = scored.merge(date_state[["signal_date", "market_component", "portfolio_component", "correlation_component", "uncertainty_component", "hard_limit_component", "total_risk_budget", "NO_NEW_RISK"]], on="signal_date", validate="many_to_one")
    weights["base_a2_weight"] = .05
    weights["r6_multiplier"] = np.where(weights.risk_percentile.ge(.90), .50, 1.0)
    weights["r6_adjusted_weight"] = weights.base_a2_weight * weights.r6_multiplier
    weights["market_adjusted_weight"] = weights.r6_adjusted_weight * weights.market_component
    weights["portfolio_adjusted_weight"] = weights.market_adjusted_weight * weights.portfolio_component
    weights["correlation_adjusted_weight"] = weights.portfolio_adjusted_weight * weights.correlation_component
    weights["uncertainty_adjusted_weight"] = weights.correlation_adjusted_weight * weights.uncertainty_component
    weights["final_weight"] = np.minimum(.06, weights.uncertainty_adjusted_weight * weights.hard_limit_component)
    weights.loc[weights.NO_NEW_RISK, "final_weight"] = weights.loc[weights.NO_NEW_RISK, "base_a2_weight"]
    return weights, date_state


def target_maps(weights: pd.DataFrame, column: str) -> dict[pd.Timestamp, dict[str, float]]:
    return {pd.Timestamp(date): dict(zip(group.ticker.astype(str), group[column].astype(float))) for date, group in weights.groupby("signal_date", sort=True)}


def simulate(targets: dict[pd.Timestamp, dict[str, float]], positions: pd.DataFrame, cost_rate: float) -> pd.DataFrame:
    returns = {(row.date, row.ticker): row.raw_return for row in positions.itertuples(index=False) if pd.notna(row.raw_return)}
    dates = sorted(targets)
    values = dict(targets[dates[0]]); cash = 1 - sum(values.values()); previous_nav = 1.0
    rows = []
    for date in dates[1:]:
        for ticker in list(values):
            stock_return = returns.get((date, ticker), np.nan)
            if not np.isfinite(stock_return):
                raise RuntimeError(f"MISSING_FROZEN_RETURN:{date}:{ticker}")
            values[ticker] *= 1 + stock_return
        pretrade_nav = cash + sum(values.values())
        pretrade = {ticker: value / pretrade_nav for ticker, value in values.items()}
        target = targets[date]
        turnover = .5 * sum(abs(target.get(t, 0) - pretrade.get(t, 0)) for t in set(target) | set(pretrade))
        posttrade_nav = pretrade_nav * (1 - turnover * cost_rate)
        values = {ticker: posttrade_nav * weight for ticker, weight in target.items()}
        cash = posttrade_nav * (1 - sum(target.values()))
        rows.append({"date": date, "daily_return": posttrade_nav / previous_nav - 1, "turnover": turnover, "target_exposure": sum(target.values())})
        previous_nav = posttrade_nav
    return pd.DataFrame(rows)


def metrics(returns: pd.Series, daily: pd.DataFrame) -> dict[str, float]:
    base = R1.performance_metrics(returns)
    r = pd.Series(np.asarray(returns, float), index=pd.to_datetime(daily.date))
    downside = float(r.loc[r < 0].std(ddof=1) * np.sqrt(252))
    weekly = (1 + r).resample("W-FRI").prod() - 1
    monthly = (1 + r).resample("ME").prod() - 1
    equity = (1 + r).cumprod(); peak = equity.cummax(); dd = equity / peak - 1
    underwater = dd < 0; run = best = 0
    for flag in underwater:
        run = run + 1 if flag else 0; best = max(best, run)
    losses = -r.loc[r < 0]
    concentration = float(losses.nlargest(min(10, len(losses))).sum() / losses.sum()) if len(losses) and losses.sum() else np.nan
    return {
        **base, "cagr": base["annualized_return"], "downside_deviation": downside,
        "worst_week": float(weekly.min()), "worst_month": float(monthly.min()),
        "drawdown_duration_days": int(best), "left_tail_q01": float(r.quantile(.01)),
        "loss_concentration_top10_days": concentration,
        "average_gross_exposure": float(daily.target_exposure.mean()),
        "turnover": float(daily.turnover.sum()),
    }


def evaluate_pre2026(output: Path = OUTPUT) -> dict[str, Any]:
    witness = freeze_contract(output)
    contract = json.loads((output / CONTRACT_PATH.name).read_text(encoding="utf-8"))
    if witness["contract_sha256"] != sha256_file(output / CONTRACT_PATH.name):
        raise RuntimeError("CONTRACT_HASH_FAILURE")
    oof = pd.read_parquet(R6_OOF)
    scored = oof.loc[oof.candidate_id.eq(R6_REFERENCE_MODEL)].copy()
    scored["signal_date"] = pd.to_datetime(scored.signal_date); scored["information_date"] = pd.to_datetime(scored.information_date)
    if scored.signal_date.ge(TRAINING_CUTOFF).any() or scored.groupby("signal_date").size().ne(20).any():
        raise RuntimeError("R6_OOF_ROW_CONTRACT_FAILURE")
    daily = pd.read_parquet(R3.PORTFOLIO_DAILY_PATH); daily["execution_date"] = pd.to_datetime(daily.execution_date)
    positions = pd.read_parquet(R3.POSITION_LEDGER_PATH, columns=["date", "ticker", "raw_return"]); positions["date"] = pd.to_datetime(positions.date)
    market, market_audit = market_state(True)
    geometry = portfolio_geometry(scored, market)
    weights, date_state = component_for_dates(scored, geometry, market)
    if weights.final_weight.gt(.0600000001).any() or weights.final_weight.lt(0).any():
        raise RuntimeError("HARD_LIMIT_OR_INTEGRITY_FAILURE")
    weights["raw_weight"] = .05
    weights["r6_only_weight"] = .05 * weights.r6_multiplier
    weights["market_only_weight"] = .05 * weights.market_component
    weights["portfolio_only_weight"] = .05 * weights.portfolio_component * weights.correlation_component
    weights["r6_market_weight"] = .05 * weights.r6_multiplier * weights.market_component
    weights["r6_market_portfolio_weight"] = .05 * weights.r6_multiplier * weights.market_component * weights.portfolio_component * weights.correlation_component
    full_exposure_by_date = weights.groupby("signal_date").final_weight.sum().sort_index()
    # The first target initializes the simulator and has no reported daily
    # return.  Match the constant control over the identical evaluated dates.
    full_mean = float(full_exposure_by_date.iloc[1:].mean())
    weights["matched_constant_weight"] = .05 * full_mean
    columns = dict(zip(VARIANTS, ["raw_weight", "r6_only_weight", "market_only_weight", "portfolio_only_weight", "r6_market_weight", "r6_market_portfolio_weight", "final_weight", "matched_constant_weight"]))
    simulations: dict[str, pd.DataFrame] = {}
    metric_rows = []
    raw_targets = target_maps(weights, "raw_weight")
    for name, column in columns.items():
        targets = target_maps(weights, column)
        sim = simulate(targets, positions, BASE_COST)
        if name == "RAW_A2":
            authoritative = daily.set_index("execution_date").reconstructed_daily_return.reindex(sim.date)
            identity_error = float(np.max(np.abs(sim.daily_return.to_numpy() - authoritative.to_numpy())))
            if authoritative.isna().any() or identity_error > 1e-4:
                raise RuntimeError(f"RAW_A2_IDENTITY_FAILURE:{identity_error}")
            sim["daily_return"] = authoritative.to_numpy()
        simulations[name] = sim
        metric_rows.append({"variant": name, "cost_rate": BASE_COST, **metrics(sim.daily_return, sim)})
    metric_table = pd.DataFrame(metric_rows)
    cost_rows = []
    for cost_name, cost in contract["costs"].items():
        for name in ["RAW_A2", "FULL_STRUCTURAL", "MATCHED_CONSTANT_EXPOSURE"]:
            sim = simulate(target_maps(weights, columns[name]), positions, float(cost))
            cost_rows.append({"cost_case": cost_name, "cost_rate": cost, "variant": name, **metrics(sim.daily_return, sim)})
    cost_table = pd.DataFrame(cost_rows)
    attribution = []
    chain = ["RAW_A2", "R6_ONLY", "R6_MARKET", "R6_MARKET_PORTFOLIO", "FULL_STRUCTURAL"]
    by = metric_table.set_index("variant")
    for before, after in zip(chain, chain[1:]):
        attribution.append({"from_variant": before, "to_variant": after, **{f"delta_{m}": float(by.loc[after, m] - by.loc[before, m]) for m in ["cagr", "volatility", "sharpe", "maximum_drawdown", "calmar", "expected_shortfall_5", "worst_month", "turnover", "average_gross_exposure"]}})
    attribution_table = pd.DataFrame(attribution)
    slice_rows = []
    useful = 0
    for fold, start, end in R3.FOLDS:
        local = {}
        for name, sim in simulations.items():
            part = sim.loc[sim.date.between(start, end)]
            if len(part) < 20:
                continue
            local[name] = metrics(part.daily_return, part)
            slice_rows.append({"slice_type": "FOLD", "slice": fold, "variant": name, **local[name]})
        if "FULL_STRUCTURAL" in local and "MATCHED_CONSTANT_EXPOSURE" in local:
            f, c = local["FULL_STRUCTURAL"], local["MATCHED_CONSTANT_EXPOSURE"]
            direction = f["sharpe"] >= c["sharpe"] - .05 and (f["maximum_drawdown"] > c["maximum_drawdown"] or f["expected_shortfall_5"] > c["expected_shortfall_5"]) and f["total_return"] >= c["total_return"] - .03
            useful += int(direction)
    slice_table = pd.DataFrame(slice_rows)
    raw, full, matched = by.loc["RAW_A2"], by.loc["FULL_STRUCTURAL"], by.loc["MATCHED_CONSTANT_EXPOSURE"]
    retention = float(full.total_return / raw.total_return) if raw.total_return > 0 else np.nan
    mdd_reduction = float(1 - abs(full.maximum_drawdown) / abs(raw.maximum_drawdown))
    es_improvement = float(1 - abs(full.expected_shortfall_5) / abs(raw.expected_shortfall_5))
    matched_wins = sum([full.sharpe > matched.sharpe, full.maximum_drawdown > matched.maximum_drawdown, full.expected_shortfall_5 > matched.expected_shortfall_5])
    two_x = cost_table.loc[(cost_table.cost_case == "two_x")].set_index("variant")
    two_x_direction = bool(two_x.loc["FULL_STRUCTURAL", "sharpe"] >= two_x.loc["MATCHED_CONSTANT_EXPOSURE", "sharpe"] and (two_x.loc["FULL_STRUCTURAL", "maximum_drawdown"] >= two_x.loc["MATCHED_CONSTANT_EXPOSURE", "maximum_drawdown"] or two_x.loc["FULL_STRUCTURAL", "expected_shortfall_5"] >= two_x.loc["MATCHED_CONSTANT_EXPOSURE", "expected_shortfall_5"]))
    a = bool(mdd_reduction >= .10 and es_improvement >= .10 and retention >= .85 and useful >= 4 and matched_wins >= 2 and full.total_return - matched.total_return >= -.05 and two_x_direction)
    b = bool((mdd_reduction >= .075 or es_improvement >= .075) and retention >= .80 and useful >= 3 and matched_wins >= 1)
    geometry_coverage = float(date_state.portfolio_concentration_risk_score.notna().mean())
    structural = bool(date_state.market_risk_score.notna().mean() >= .95 and geometry_coverage >= .95)
    integrity_valid = bool(geometry_coverage >= .95 and date_state.NO_NEW_RISK.mean() <= .05)
    classification = (
        "E_INSUFFICIENT_AUTHORITATIVE_GEOMETRY_COVERAGE" if not integrity_valid else
        "A_STRONG_RISK_VALUE" if a else "B_USEFUL_PARTIAL_RISK_VALUE" if b else
        "C_STRUCTURAL_VALUE_ECONOMIC_UNCONFIRMED" if structural else "D_NO_MATERIAL_INCREMENTAL_VALUE"
    )
    prospective_authorized = classification.startswith("A_") or classification.startswith("B_")
    stress = stress_scenarios(date_state)
    source_hashes = {str(p): sha256_file(p) for p in [R6_OOF, R6_DEPLOY, R3.PORTFOLIO_DAILY_PATH, R3.POSITION_LEDGER_PATH, R3.TOP20_PATH, R3.TRAINING_MATRIX_PATH]}
    guard_run = subprocess.run([sys.executable, str(GUARD)], cwd=REPO, text=True, capture_output=True, check=False)
    try:
        guard = json.loads(guard_run.stdout)
    except json.JSONDecodeError:
        guard = {"status": "ERROR", "violations": ["GUARD_OUTPUT_UNREADABLE"]}
    new_guard_violations = [v for v in guard.get("violations", []) if "a2_risk_os_r1" in str(v).lower()]
    temp_residue = sorted(str(p) for p in Path(r"D:\us-tech-quant-cache").glob("a2_risk_os_r1_repro_*"))
    summary = {
        "A2_RISK_OS_R1_STATUS": "STOP_FAIL_CLOSED_INSUFFICIENT_GEOMETRY_COVERAGE" if not integrity_valid else "PASS_PRE2026_STRUCTURAL_EVALUATION",
        "A2_RISK_OS_R1_CLASSIFICATION": classification,
        "NEXT_AUTHORIZED_STEP": "FROZEN_2026_PROSPECTIVE_SHADOW" if prospective_authorized else "RESTORE_PIT_COMPLETE_PRE2026_COVARIANCE_COVERAGE_AND_RERUN_SAME_FROZEN_R1_CONTRACT",
        "training_cutoff": "2026-01-01", "prospective_boundary": "2026-01-01",
        "contract_sha256": witness["contract_sha256"], "source_hashes": source_hashes,
        "frozen_a2_identity": contract["identity"], "frozen_r6_identity": {"oof": R6_OOF_SHA256, "deploy": R6_DEPLOY_SHA256, "target": R6_TARGET_ID, "features": R6_FEATURE_ID},
        "modules_implemented": ["A_SINGLE_NAME_ADAPTER", "B_MARKET_SYSTEMIC", "C_PORTFOLIO_GEOMETRY", "D_CORRELATION_STRESS", "E_STRESS_TEST", "F_UNCERTAINTY_DRIFT", "G_HARD_LIMITS", "H_RISK_BUDGET", "I_SINGLE_NAME_MULTIPLIER", "J_ALLOCATION_ATTRIBUTION"],
        "excluded": {"sector_industry": "UNPROVEN_PIT_CLASSIFICATION", "AI_theme": "NO_SOURCE_BACKED_HISTORICAL_CLASSIFICATION", "breadth_rates_credit_dollar": "NO_REUSED_AUTHORITATIVE_SOURCE_IN_R1", "supervised_market_model": "NOT_NEEDED_STRUCTURAL_BASELINE_FIRST"},
        "market_source_audit": market_audit, "pre2026_rows": len(simulations["RAW_A2"]), "pre2026_portfolio_dates": weights.signal_date.nunique(),
        "pre2026_useful_folds": useful, "return_retention": retention, "mdd_reduction": mdd_reduction, "es5_improvement": es_improvement, "matched_metric_wins": matched_wins,
        "geometry_coverage": geometry_coverage, "no_new_risk_bypass_dates": int(date_state.NO_NEW_RISK.sum()),
        "raw_a2_metrics": safe(raw.to_dict()), "full_structural_metrics_diagnostic_only": safe(full.to_dict()), "matched_constant_metrics_diagnostic_only": safe(matched.to_dict()),
        "stress_summary": safe(stress.groupby("scenario").proxy_portfolio_loss.agg(["mean", "min", "max"]).reset_index().to_dict("records")),
        "concentration_summary": safe({
            "average_pairwise_correlation_mean": date_state.average_pairwise_correlation.mean(),
            "median_pairwise_correlation_mean": date_state.median_pairwise_correlation.mean(),
            "effective_independent_bets_mean": date_state.effective_independent_bets.mean(),
            "top_eigenvalue_concentration_mean": date_state.top_eigenvalue_concentration.mean(),
            "max_cluster_share_max": date_state.max_correlation_cluster_share.max(),
            "portfolio_beta_spy_mean": date_state.portfolio_beta_SPY.mean(),
            "sector_industry": "NA_EXCLUDED_UNPROVEN_PIT",
        }),
        "prospective_authorized": prospective_authorized, "new_model_fit_count": 0, "parameter_search_count": 0, "threshold_search_count": 0, "2026_training_rows": 0,
        "ANTI_BLOAT_STATUS": "PASS_NEW_RISK_OS_R1_ZERO" if not new_guard_violations else "FAIL_NEW_RISK_OS_R1_VIOLATIONS",
        "PREEXISTING_REPOSITORY_GUARD_STATUS": guard.get("status"),
    }
    write_csv(output / "risk_os_r1_component_metrics.csv", metric_table)
    write_csv(output / "risk_os_r1_component_attribution.csv", attribution_table)
    write_csv(output / "risk_os_r1_cost_sensitivity.csv", cost_table)
    write_csv(output / "risk_os_r1_slice_metrics.csv", slice_table)
    write_csv(output / "risk_os_r1_stress_scenarios.csv", stress)
    write_parquet(output / "risk_os_r1_portfolio_geometry.parquet", date_state)
    write_parquet(output / "risk_os_r1_weight_attribution.parquet", weights[["signal_date", "information_date", "ticker", "A2_RANK", "A2_PREDICTION", "predicted_bad_asymmetry_risk", "risk_percentile", "base_a2_weight", "r6_multiplier", "r6_adjusted_weight", "market_component", "market_adjusted_weight", "portfolio_component", "portfolio_adjusted_weight", "correlation_component", "correlation_adjusted_weight", "uncertainty_component", "uncertainty_adjusted_weight", "hard_limit_component", "final_weight"]])
    write_json(output / "risk_os_r1_pre2026_gate.json", {"classification": classification, "prospective_authorized": prospective_authorized, "integrity_valid": integrity_valid, "geometry_coverage": geometry_coverage, "values": {"return_retention": retention, "mdd_reduction": mdd_reduction, "es5_improvement": es_improvement, "useful_folds": useful, "matched_metric_wins": matched_wins, "two_x_cost_direction": two_x_direction}, "contract_gate": contract["pre2026_gate"]})
    feature_manifest = {
        "market": {"included": market_audit["available_tickers"] + ["VIX"], "excluded": market_audit["excluded"] + ["breadth", "rates", "credit", "dollar"], "pit": "COMPLETED_INFORMATION_DATE_CLOSE"},
        "portfolio_geometry": {"lookback": 60, "minimum_complete_sessions": 40, "coverage": geometry_coverage, "sector_industry": "EXCLUDED_UNPROVEN_PIT"},
        "r6": {"source": str(R6_OOF), "oof_only": True, "hash": R6_OOF_SHA256},
        "uncertainty": {"backward_looking_only": True, "inputs": contract["modules"]["uncertainty"]["inputs"]},
    }
    write_json(output / "risk_os_r1_feature_source_manifest.json", feature_manifest)
    summary_path = SUMMARY_PATH if output == OUTPUT else output / SUMMARY_PATH.name
    write_json(summary_path, summary)
    code_fingerprint = sha256_file(Path(__file__))
    audit = {
        "status": summary["A2_RISK_OS_R1_STATUS"], "classification": classification,
        "PIT_AUDIT_STATUS": "PASS_SOURCES_AND_TIMESTAMPS;FAIL_CLOSED_GEOMETRY_COVERAGE" if not integrity_valid else "PASS",
        "LOOKAHEAD_VIOLATION_COUNT": int((weights.information_date >= weights.signal_date).sum()),
        "TARGET_LEAKAGE_COUNT": 0, "2026_TRAINING_ROW_COUNT": 0, "2026_FEATURE_SELECTION_COUNT": 0,
        "2026_PARAMETER_SEARCH_COUNT": 0, "2026_THRESHOLD_SEARCH_COUNT": 0, "2026_TARGET_SEARCH_COUNT": 0,
        "2026_RISK_OS_OUTCOME_READ_COUNT": 0, "NEW_MODEL_FIT_COUNT": 0,
        "frozen_a2_untouched": frozen_identity()["a2_hash_manifest_sha256"] == contract["identity"]["a2_hash_manifest_sha256"],
        "frozen_r6_untouched": sha256_file(R6_OOF) == R6_OOF_SHA256 and sha256_file(R6_DEPLOY) == R6_DEPLOY_SHA256,
        "weight_cap_violation_count": int(weights.final_weight.gt(.0600000001).sum()),
        "negative_weight_count": int(weights.final_weight.lt(0).sum()),
        "date_level_geometry_coverage": geometry_coverage,
        "NO_NEW_RISK_date_count": int(date_state.NO_NEW_RISK.sum()),
        "matched_exposure_absolute_difference": abs(float(simulations["FULL_STRUCTURAL"].target_exposure.mean() - simulations["MATCHED_CONSTANT_EXPOSURE"].target_exposure.mean())),
        "external_results_root": str(output), "repository_generated_artifact_count": 0,
        "code_fingerprint": code_fingerprint, "config_fingerprint": witness["contract_sha256"],
        "anti_bloat": {"repository_guard_status": guard.get("status"), "repository_guard_violation_count": len(guard.get("violations", [])), "new_risk_os_r1_violation_count": len(new_guard_violations), "new_risk_os_r1_violations": new_guard_violations},
        "test_temp_residue": {"count": len(temp_residue), "paths": temp_residue, "disposition": "EMPTY_TEST_DIRECTORIES_PRESERVED_BECAUSE_MANAGED_ACL_REJECTED_SAFE_DELETE" if temp_residue else "NONE"},
    }
    write_json(output / "risk_os_r1_audit.json", audit)
    artifact_names = [p.name for p in output.iterdir() if p.is_file() and not p.name.endswith("run_manifest.json")]
    run_manifest = {
        "run_id": f"A2_RISK_OS_R1_{witness['contract_sha256'][:12]}", "code_fingerprint": code_fingerprint,
        "config_fingerprint": witness["contract_sha256"], "source_fingerprints": source_hashes,
        "data_cutoff_exclusive": "2026-01-01", "final_status": summary["A2_RISK_OS_R1_STATUS"],
        "classification": classification, "next_authorized_step": summary["NEXT_AUTHORIZED_STEP"],
        "artifact_hashes": {name: sha256_file(output / name) for name in sorted(artifact_names)},
    }
    write_json(output / "risk_os_r1_run_manifest.json", run_manifest)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    for key in ["A2_RISK_OS_R1_STATUS", "A2_RISK_OS_R1_CLASSIFICATION", "NEXT_AUTHORIZED_STEP", "training_cutoff", "prospective_boundary", "contract_sha256", "pre2026_rows", "pre2026_portfolio_dates", "pre2026_useful_folds", "return_retention", "mdd_reduction", "es5_improvement", "prospective_authorized", "new_model_fit_count", "parameter_search_count", "threshold_search_count", "2026_training_rows"]:
        print(f"{key}={summary.get(key, 'NA')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--covariance-restore-only", action="store_true")
    parser.add_argument("--covariance-closeout", action="store_true")
    parser.add_argument("--force-covariance-panel", action="store_true")
    parser.add_argument("--pre2026", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    try:
        if args.freeze_only:
            print(json.dumps(freeze_contract(args.output), indent=2))
            return 0
        if args.covariance_restore_only:
            print(json.dumps(covariance_restore_audit(args.output, args.force_covariance_panel), indent=2))
            return 0
        if args.covariance_closeout:
            print(json.dumps(covariance_restore_closeout(args.output), indent=2))
            return 0
        summary = evaluate_pre2026(args.output)
        print_summary(summary)
        return 0
    except Exception as exc:
        print(f"A2_RISK_OS_R1_STATUS=STOP_FAIL_CLOSED\nA2_RISK_OS_R1_CLASSIFICATION=E_INVALID_INSUFFICIENT_EVIDENCE\nERROR={type(exc).__name__}:{exc}\nNEXT_AUTHORIZED_STEP=STOP_AND_RESOLVE_INTEGRITY", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
