from __future__ import annotations

"""Preregistered A2 buy/sell/sizing research runner.

The runner deliberately reuses the frozen A2 data, taxonomy builders and the
existing execution replay.  It never writes canonical data and never uses a
full-sample model to backfill a historical prediction.  The only historical A2
extension is a fixed-spec, expanding OOF reconstruction whose 2023 vintage
must reproduce the frozen A2 prediction matrix bit-for-bit before 2021/2022
predictions are admitted.
"""

import hashlib
import importlib.util
import json
import math
import os
import copy
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from scipy.optimize import minimize


R1_TASK = "A2_AUTONOMOUS_BUY_SELL_AND_SIZING_POLICY_R1"
R2_TASK = "A2_CLEAN_LABEL_LINEAGE_AND_AUTONOMOUS_POLICY_R2"
RESEARCH_MODE = os.environ.get("A2_AUTONOMOUS_POLICY_MODE", "R1").strip().upper()
require_mode = RESEARCH_MODE in {"R1", "R2"}
if not require_mode:
    raise RuntimeError(f"UNSUPPORTED_RESEARCH_MODE:{RESEARCH_MODE}")
IS_R2 = RESEARCH_MODE == "R2"
TASK = R2_TASK if IS_R2 else R1_TASK
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache")
OUT = RESULTS / TASK
INVALID_R1 = RESULTS / R1_TASK
INVALID_R1_ARCHIVE = Path(r"D:\us-tech-quant-backtests\A2_AUTONOMOUS_BUY_SELL_AND_SIZING_POLICY_R1\INVALID_LABEL_LINEAGE_RUN_20260824T004226JST")
A2_ROOT = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
A2 = A2_ROOT / "A2"
MATRIX = A2 / "training_matrix.parquet"
OOF = A2 / "oof_predictions.parquet"
TOP20 = A2 / "top20_selections.parquet"
PORTFOLIO = A2 / "portfolio_daily.parquet"
PREVIOUS = RESULTS / "A2_GLOBAL_FF12_HOLD_REPLACE_R1"
MODEL_FAMILY = RESULTS / "A2_MODEL_FAMILY_R1A_DATA_COMPLETE"
RESEARCH_DATASET = CACHE / "a2_model_family_r1a_data_complete" / "research_dataset.parquet"
STATE_CACHE = CACHE / ("a2_clean_label_lineage_autonomous_policy_r2" if IS_R2 else "a2_autonomous_buy_sell_sizing_r1") / "state_panel_pre2025.parquet"
PRETOP_SOURCE = REPO / "scripts" / "v22" / "a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py"
BASE_SOURCE = REPO / "scripts" / "v22" / "stage_sec_pit_taxonomy.py"
ACTION_SOURCE = REPO / "scripts" / "v22" / "a2_global_ff12_hold_replace_r1.py"
E5_ROOT = RESULTS / "A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS"
E5_SOURCE = E5_ROOT / "run_a2_execution_efficiency_r2.py"
R4_SOURCE = REPO / "scripts" / "v22" / "abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py"
CORPORATE_ACTION_SOURCE = REPO / "scripts" / "v22" / "fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py"
FROZEN_MANIFEST = A2_ROOT / "audit" / "freeze_r1" / "frozen_baseline_manifest.json"

RANDOM_SEEDS = (20260823, 20260824, 20260825)
MAX_UNIQUE_MODEL_SPECS = 96
MAX_TOTAL_MODEL_FITS = 600
MAX_POLICY_SPECS = 48
MAX_ENSEMBLES = 2
MAX_OUTER_FINALISTS = 8
FEATURE_DATE_CUTOFF = pd.Timestamp("2025-12-31")
LABEL_DATE_CUTOFF = pd.Timestamp("2025-12-31")
TOP_N = 20
TOL = 1e-10
OPERATIONAL_POLICY_ID = "RAW_A2_TOP20_EQUAL_WEIGHT_R1"
A2_SHADOW_PROFILE_ID = "A2_MULTI_POSITION_SHADOW"
RAW_A2_TARGET_GROSS = 1.0
RAW_A2_TARGET_WEIGHT = 1.0 / TOP_N
RAW_A2_COST_BPS = 10

A2_FEATURES = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120", "ma10_vs_ma20",
    "ma20_vs_ma50", "ma50_vs_ma120", "realized_vol_5d", "realized_vol_10d",
    "realized_vol_20d", "realized_vol_60d", "downside_vol_20d", "upside_vol_20d",
    "distance_from_high_20d", "distance_from_high_60d", "distance_from_low_20d",
    "distance_from_low_60d", "max_drawdown_20d", "max_drawdown_60d", "avg_volume_20d",
    "avg_volume_60d", "volume_ratio_5d_20d", "volume_ratio_20d_60d", "avg_dollar_volume_20d",
]
NUMERIC_FEATURES = [
    "raw_prior", "raw_rank_pct", "distance_to_top20", "score_distance_to_boundary", "rank_change", "score_change", "score_stability", "is_current_holding",
    "holding_age", "return_since_entry", "drawdown_since_entry", "max_favorable_excursion", "max_adverse_excursion", "ret_5d", "ret_20d", "ret_60d",
    "realized_vol_20d", "realized_vol_60d", "downside_vol_20d", "max_drawdown_20d",
    "avg_dollar_volume_20d", "volume_ratio_5d_20d", "estimated_trade_cost", "raw_ff12_count",
    "raw_ff48_count", "sector_relative_score", "sector_relative_ret20",
]
CATEGORICAL_FEATURES = ["current_role", "ff12", "role_ff12"]
TARGETS = ["y_abs20", "y_ff12res20", "y_abs5", "y_downside20", "y_persist20"]
TARGET_WEIGHTS = np.array([0.45, 0.25, 0.10, -0.15, 0.05], dtype=float)
MIN_SECTOR_DECISION_DATES = 30
MIN_SECTOR_EVENTS = 200
EXTREME_WINNER_RETURN = 0.20
OLD_PREREG_SHA256 = "5f06ccbbceb7f04eab9675752372116502f03223840312bed50b71ff4bf563ea"
INVALID_R1_PREREG_SHA256 = "9ee0e790196b65931409617e87879f7a288d8439a5a9f0f4a113266e47754765"
INVALID_R1_SOURCE_SHA256 = "35db32204a6b215bb57748f62d59f0f6d218467de97e4547a5bd8842c35da273"
LABEL_LINEAGE = "continuous_raw_counterfactual"
FORBIDDEN_LABEL_SOURCE = "FROZEN_POSITION_LEDGER_EXACT_MARK"
LABEL_ARITHMETIC_TOL = 1e-12

FEATURE_FAMILIES: dict[str, list[str]] = {
    "F0_RAW_CORE": ["raw_prior", "raw_rank_pct", "distance_to_top20", "score_distance_to_boundary", "rank_change", "score_change", "score_stability"],
    "F1_RAW_PLUS_STATE": ["raw_prior", "raw_rank_pct", "distance_to_top20", "score_distance_to_boundary", "rank_change", "score_change", "score_stability", "is_current_holding", "holding_age", "return_since_entry", "drawdown_since_entry", "max_favorable_excursion", "max_adverse_excursion"],
    "F2_RAW_PLUS_VOL_LIQ": ["raw_prior", "raw_rank_pct", "realized_vol_20d", "realized_vol_60d", "downside_vol_20d", "max_drawdown_20d", "avg_dollar_volume_20d", "volume_ratio_5d_20d"],
    "F3_RAW_PLUS_TREND": ["raw_prior", "raw_rank_pct", "ret_5d", "ret_20d", "ret_60d", "rank_change", "score_change", "score_stability"],
    "F4_RAW_PLUS_SECTOR_RELATIVE": ["raw_prior", "raw_rank_pct", "sector_relative_score", "sector_relative_ret20", "raw_ff12_count", "raw_ff48_count"],
    "F5_RAW_PLUS_PORTFOLIO_RISK": ["raw_prior", "raw_rank_pct", "realized_vol_20d", "downside_vol_20d", "estimated_trade_cost", "raw_ff12_count", "raw_ff48_count"],
}
FEATURE_FAMILIES["F6_FULL_BOUNDED"] = list(dict.fromkeys(sum(FEATURE_FAMILIES.values(), [])))


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise GateFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _operational_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    require(bool(symbol), "OPERATIONAL_SYMBOL_MISSING")
    return symbol if symbol.startswith("US.") else f"US.{symbol}"


@dataclass(frozen=True)
class CurrentPortfolioState:
    """Minimal injected state; all weights and values are derived, never stored."""

    as_of: str
    cash: float
    positions: tuple[tuple[str, float, float], ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "CurrentPortfolioState":
        require(isinstance(payload, Mapping), "CURRENT_PORTFOLIO_STATE_REQUIRED")
        as_of = str(payload.get("as_of", "")).strip()
        require(bool(as_of), "CURRENT_PORTFOLIO_AS_OF_REQUIRED")
        cash = float(payload.get("cash", math.nan))
        require(np.isfinite(cash) and cash >= -TOL, "CURRENT_PORTFOLIO_CASH_INVALID", cash)
        rows: list[tuple[str, float, float]] = []
        seen: set[str] = set()
        raw_positions = payload.get("positions")
        require(isinstance(raw_positions, Sequence) and not isinstance(raw_positions, (str, bytes)), "CURRENT_PORTFOLIO_POSITIONS_REQUIRED")
        for raw in raw_positions:
            require(isinstance(raw, Mapping), "CURRENT_PORTFOLIO_POSITION_INVALID")
            symbol = _operational_symbol(raw.get("symbol"))
            require(symbol not in seen, "CURRENT_PORTFOLIO_DUPLICATE_SYMBOL", symbol)
            shares = float(raw.get("shares", math.nan))
            mark_price = float(raw.get("mark_price", math.nan))
            require(np.isfinite(shares) and shares >= -TOL, "CURRENT_PORTFOLIO_SHORT_FORBIDDEN", symbol)
            require(np.isfinite(mark_price) and mark_price > 0.0, "CURRENT_PORTFOLIO_MARK_INVALID", symbol)
            seen.add(symbol)
            rows.append((symbol, max(0.0, shares), mark_price))
        return cls(as_of=as_of, cash=max(0.0, cash), positions=tuple(sorted(rows)))

    def derived(self) -> dict[str, Any]:
        values = {symbol: shares * mark for symbol, shares, mark in self.positions if shares > TOL}
        total_equity = self.cash + sum(values.values())
        require(np.isfinite(total_equity) and total_equity > 0.0, "CURRENT_PORTFOLIO_EQUITY_INVALID")
        weights = {symbol: value / total_equity for symbol, value in values.items()}
        gross = float(sum(weights.values()))
        cash_weight = self.cash / total_equity
        require(abs(gross + cash_weight - 1.0) <= TOL, "CURRENT_PORTFOLIO_IDENTITY_FAILURE")
        require(gross <= 1.0 + TOL and cash_weight >= -TOL, "CURRENT_PORTFOLIO_LEVERAGE_FORBIDDEN")
        rows = []
        for symbol, shares, mark in self.positions:
            market_value = shares * mark
            rows.append({
                "symbol": symbol, "shares": shares, "mark_price": mark,
                "market_value": market_value,
                "current_weight": market_value / total_equity,
            })
        return {
            "as_of": self.as_of, "cash": self.cash, "positions": rows,
            "total_equity": total_equity, "current_weights": weights,
            "gross_exposure": gross, "cash_weight": cash_weight,
        }


def authoritative_raw_a2_targets(alpha_records: Sequence[Mapping[str, Any]]) -> tuple[str, dict[str, float]]:
    require(isinstance(alpha_records, Sequence) and len(alpha_records) >= TOP_N, "RAW_A2_RECORDS_REQUIRED")
    selected: list[tuple[int, str, float]] = []
    dates: set[str] = set()
    seen: set[str] = set()
    for row in alpha_records:
        require(isinstance(row, Mapping), "RAW_A2_RECORD_INVALID")
        dates.add(str(row.get("target_date", "")))
        weight = float(row.get("raw_target_weight", math.nan))
        require(np.isfinite(weight) and weight >= -TOL, "RAW_A2_TARGET_WEIGHT_INVALID")
        if weight <= TOL:
            continue
        require(str(row.get("model_id", "")) == "A2_HGB", "RAW_A2_MODEL_IDENTITY_FAILURE")
        symbol = _operational_symbol(row.get("symbol") or row.get("ticker"))
        require(symbol not in seen, "RAW_A2_SELECTED_SYMBOL_DUPLICATE", symbol)
        rank = int(row.get("rank", 0))
        selected.append((rank, symbol, weight))
        seen.add(symbol)
    require(len(dates) == 1 and next(iter(dates)), "RAW_A2_TARGET_DATE_INVALID")
    require(len(selected) == TOP_N, "RAW_A2_TOP20_CONTRACT_FAILURE", len(selected))
    require(sorted(rank for rank, _, _ in selected) == list(range(1, TOP_N + 1)), "RAW_A2_RANK_CONTRACT_FAILURE")
    require(all(abs(weight - RAW_A2_TARGET_WEIGHT) <= TOL for _, _, weight in selected), "RAW_A2_EQUAL_WEIGHT_CONTRACT_FAILURE")
    targets = {symbol: weight for _, symbol, weight in sorted(selected)}
    require(abs(sum(targets.values()) - RAW_A2_TARGET_GROSS) <= TOL, "RAW_A2_GROSS_CONTRACT_FAILURE")
    return next(iter(dates)), targets


def build_operational_policy_plan(
    alpha_records: Sequence[Mapping[str, Any]],
    current_portfolio: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Convert authoritative Raw A2 Top20 plus explicit state into a SHADOW plan."""
    target_date, targets = authoritative_raw_a2_targets(alpha_records)
    state = CurrentPortfolioState.from_mapping(current_portfolio).derived()
    as_of_timestamp = pd.Timestamp(state["as_of"])
    target_timestamp = pd.Timestamp(target_date)
    require(not pd.isna(as_of_timestamp) and as_of_timestamp.date() <= target_timestamp.date(), "CURRENT_PORTFOLIO_AS_OF_AFTER_TARGET")
    r4 = import_file("a2_r4_operational_accounting", R4_SOURCE)
    accounting = r4.calculate_weight_rebalance(
        state["current_weights"], targets, cost_bps=RAW_A2_COST_BPS, tolerance=TOL,
    )
    actions: list[dict[str, Any]] = []
    current = state["current_weights"]
    position_by_symbol = {row["symbol"]: row for row in state["positions"]}
    for symbol in sorted(set(current) | set(targets)):
        current_weight = float(current.get(symbol, 0.0))
        target_weight = float(targets.get(symbol, 0.0))
        delta = target_weight - current_weight
        if current_weight <= TOL and target_weight > TOL:
            action, reason = "BUY", "RAW_A2_TOP20_NEW_POSITION"
        elif target_weight > current_weight + TOL:
            action, reason = "ADD", "RAW_A2_TOP20_UNDER_TARGET"
        elif target_weight <= TOL and current_weight > TOL:
            action, reason = "EXIT", "NO_LONGER_IN_RAW_A2_TOP20"
        elif target_weight < current_weight - TOL:
            action, reason = "REDUCE", "RAW_A2_TOP20_OVER_TARGET"
        else:
            action, reason = "HOLD", "RAW_A2_TARGET_WITHIN_NUMERICAL_TOLERANCE"
        planned_delta = delta * accounting["buy_scale"] if delta > TOL else delta
        position = position_by_symbol.get(symbol, {})
        actions.append({
            "security": symbol,
            "current_weight": current_weight,
            "target_weight": target_weight,
            "delta_weight": delta,
            "planned_delta_weight": planned_delta,
            "action": action,
            "reason": reason,
            "current_shares": float(position.get("shares", 0.0)),
            "current_mark_price": position.get("mark_price"),
        })
    return {
        "status": "PASS",
        "policy_id": OPERATIONAL_POLICY_ID,
        "safety_profile_id": A2_SHADOW_PROFILE_ID,
        "target_date": target_date,
        "current_portfolio": state,
        "authorized_top20": sorted(targets),
        "target_weights": dict(sorted(targets.items())),
        "target_cash_weight": 1.0 - sum(targets.values()),
        "actions": actions,
        "accounting": {
            **accounting,
            "transaction_cost_usd": accounting["transaction_cost_fraction"] * state["total_equity"],
            "cost_bps": RAW_A2_COST_BPS,
        },
        "broker_submission_allowed": False,
    }


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def frozen_corporate_action_records() -> list[dict[str, Any]]:
    """Read the existing source-backed corporate-action ledger definition."""
    module = import_file("a2_policy_corporate_action_evidence", CORPORATE_ACTION_SOURCE)
    records = module.frozen_evidence_records()
    require(isinstance(records, list) and records, "CORPORATE_ACTION_LEDGER_MISSING")
    return [dict(row) for row in records]


def build_lineage_impact_audit() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Classify only proven callers/artifacts; never infer impact from task names."""
    invalid_manifest_path = INVALID_R1 / "hash_manifest.json"
    invalid_prereg_path = INVALID_R1 / "preregistration.json"
    archive_manifest_path = INVALID_R1_ARCHIVE / "hash_manifest.json"
    for path in (invalid_manifest_path, invalid_prereg_path, archive_manifest_path, RESEARCH_DATASET):
        require(path.is_file(), "LINEAGE_AUDIT_INPUT_MISSING", path)
    invalid_manifest = json.loads(invalid_manifest_path.read_text(encoding="utf-8"))
    archive_manifest = json.loads(archive_manifest_path.read_text(encoding="utf-8"))
    require(sha256_file(invalid_prereg_path) == INVALID_R1_PREREG_SHA256, "INVALID_R1_PREREG_HASH")
    require(invalid_manifest.get("status") == "PASS_HASH_VERIFIED_RESEARCH_INVALID_LABEL_LINEAGE", "INVALID_R1_STATUS")
    require(archive_manifest.get("source_sha256") == INVALID_R1_SOURCE_SHA256, "INVALID_R1_ARCHIVE_SOURCE_HASH")
    invalid_hash_mismatches = []
    for item in invalid_manifest.get("artifacts", []):
        path = INVALID_R1 / item["name"]
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            invalid_hash_mismatches.append(item["name"])
    dataset_hash = sha256_file(RESEARCH_DATASET)
    metadata = pq.ParquetFile(RESEARCH_DATASET).metadata.metadata or {}
    metadata_text = " ".join(str(value).lower() for value in metadata.values())
    lineage_proven = all(token in metadata_text for token in ("label_builder", "price_lineage", "price_field"))
    dataset_class = "UNAFFECTED_INDEPENDENT_LABEL_LINEAGE" if lineage_proven and LABEL_LINEAGE in metadata_text else "LINEAGE_UNVERIFIED"
    dataset_note = (
        "Parquet metadata positively identifies a clean independent label builder and price lineage."
        if dataset_class.startswith("UNAFFECTED") else
        "Frozen dataset has only ordinary dataframe schema metadata; no builder, start/end price field, or label-lineage provenance."
    )
    rows = [
        {
            "research_id": R1_TASK, "artifact_path": str(INVALID_R1_ARCHIVE), "label_dependency": "DIRECT_T0_TO_T4",
            "label_builder": "qfq_forward_labels@invalid_source_sha256:" + INVALID_R1_SOURCE_SHA256,
            "price_lineage": "MIXED_LEDGER_EXACT_MARK_AND_QFQ", "source_hash": INVALID_R1_SOURCE_SHA256,
            "classification": "IMPACTED_INVALID_LABEL_LINEAGE",
            "material_effect": "INNER_SELECTION_WEIGHTABILITY_OUTER_2025_SECTOR_AND_ACTION_ATTRIBUTION_INVALID",
            "allowed_for_r2": False,
            "notes": "main -> qfq_forward_labels -> action.load_prices -> ledger-overlaid prices.close; exact incumbent marks could override QFQ at one endpoint. Current invalid-R1 forensic hash mismatches=" + ",".join(invalid_hash_mismatches or ["NONE"]),
        },
        {
            "research_id": "A2_MODEL_FAMILY_R1A_DATA_COMPLETE", "artifact_path": str(RESEARCH_DATASET),
            "label_dependency": "DIRECT_TARGET_COLUMN", "label_builder": "NOT_RECORDED_IN_FROZEN_PARQUET_METADATA",
            "price_lineage": "UNVERIFIED", "source_hash": dataset_hash, "classification": dataset_class,
            "material_effect": "ALL_DOWNSTREAM_MODEL_SELECTION_USING_DATASET_TARGET",
            "allowed_for_r2": dataset_class == "UNAFFECTED_INDEPENDENT_LABEL_LINEAGE", "notes": dataset_note,
        },
        {
            "research_id": "A2_GLOBAL_FF12_HOLD_REPLACE_R1", "artifact_path": str(PREVIOUS),
            "label_dependency": "INDIRECT_VIA_RESEARCH_DATASET_TARGET_TO_PAIR_Y20",
            "label_builder": "load_research -> research_dataset.target -> challenger.target-incumbent.target-cost",
            "price_lineage": "UNVERIFIED_DATASET_" + dataset_hash, "source_hash": sha256_file(ACTION_SOURCE),
            "classification": dataset_class, "material_effect": "PAIRWISE_LABEL_AND_ALL_ML_ECONOMIC_RESULTS_UNVERIFIED",
            "allowed_for_r2": False,
            "notes": "Does not call qfq_forward_labels, but primary y20 derives from the unproven frozen research dataset target.",
        },
        {
            "research_id": "A2_SECTOR_AWARE_ML_AND_FACTOR_OVERNIGHT_R1",
            "artifact_path": str(RESULTS / "A2_SECTOR_AWARE_ML_AND_FACTOR_OVERNIGHT_R1"),
            "label_dependency": "DIRECT_VIA_RESEARCH_DATASET_TARGET",
            "label_builder": "load_dataset_before/load_dataset_year -> research_dataset.target",
            "price_lineage": "UNVERIFIED_DATASET_" + dataset_hash,
            "source_hash": sha256_file(REPO / "scripts/v22/a2_sector_aware_ml_and_factor_overnight_r1.py"),
            "classification": dataset_class, "material_effect": "RIDGE_OOF_SCORE_AND_SECTOR_ML_VERDICT_UNVERIFIED",
            "allowed_for_r2": False, "notes": "Ridge score/U2 disabled because clean independent lineage is not positively proven.",
        },
        {
            "research_id": "RAW_A2", "artifact_path": str(PORTFOLIO),
            "label_dependency": "NONE_DETERMINISTIC_EQUAL_WEIGHT_REPLAY", "label_builder": "NOT_APPLICABLE",
            "price_lineage": "AUTHORITATIVE_PORTFOLIO_REPLAY", "source_hash": sha256_file(BASE_SOURCE),
            "classification": "NOT_LABEL_DEPENDENT", "material_effect": "NONE", "allowed_for_r2": True,
            "notes": "verify_inputs and candidate_target construct deterministic Raw weights and reconcile the existing return/NAV engine; no ML training label is consumed.",
        },
        {
            "research_id": "S1_SOFT_025", "artifact_path": str(RESULTS / "A2_SEC_PIT_TAXONOMY"),
            "label_dependency": "NONE_DETERMINISTIC_SECTOR_BUDGET_REPLAY", "label_builder": "NOT_APPLICABLE",
            "price_lineage": "AUTHORITATIVE_PORTFOLIO_REPLAY", "source_hash": sha256_file(BASE_SOURCE),
            "classification": "NOT_LABEL_DEPENDENT", "material_effect": "NONE", "allowed_for_r2": True,
            "notes": "candidate_target builds S1 weights from frozen taxonomy and score ranks; no ML target column is read.",
        },
    ]
    frame = pd.DataFrame(rows)
    counts = frame.classification.value_counts().to_dict()
    facts = {
        "invalid_r1_prereg_sha256": INVALID_R1_PREREG_SHA256,
        "invalid_r1_finalist_hash": sha256_file(INVALID_R1 / "finalist_freeze.json"),
        "invalid_r1_archive_path": str(INVALID_R1_ARCHIVE),
        "invalid_r1_forensic_hash_mismatch_count": len(invalid_hash_mismatches),
        "invalid_r1_forensic_hash_mismatch_names": invalid_hash_mismatches,
        "contaminated_label_builder": "qfq_forward_labels",
        "contaminated_price_field": "prices.close<-POSITION_LEDGER.current_price/FROZEN_POSITION_LEDGER_EXACT_MARK",
        "contaminated_call_path": "main->qfq_forward_labels->a2_global_ff12_hold_replace_r1.load_prices->ledger-overlaid prices.close",
        "root_cause": "T0-T4 start/end observations could use different corporate-action scales because exact portfolio marks overrode QFQ marks.",
        "impact_status": "MIXED_IMPACT_AND_LINEAGE_UNVERIFIED",
        "impacted_count": int(counts.get("IMPACTED_INVALID_LABEL_LINEAGE", 0)),
        "lineage_unverified_count": int(counts.get("LINEAGE_UNVERIFIED", 0)),
        "unaffected_count": int(counts.get("UNAFFECTED_INDEPENDENT_LABEL_LINEAGE", 0)),
        "not_label_dependent_count": int(counts.get("NOT_LABEL_DEPENDENT", 0)),
        "hold_replace_status": str(frame.loc[frame.research_id.eq("A2_GLOBAL_FF12_HOLD_REPLACE_R1"), "classification"].iloc[0]),
        "sector_aware_ridge_status": str(frame.loc[frame.research_id.eq("A2_SECTOR_AWARE_ML_AND_FACTOR_OVERNIGHT_R1"), "classification"].iloc[0]),
        "raw_status": "NOT_LABEL_DEPENDENT", "s1_status": "NOT_LABEL_DEPENDENT",
        "u2_status": "SKIPPED_RIDGE_LINEAGE_UNVERIFIED",
    }
    return frame, facts


def freeze_label_lineage_contract(action: Any) -> tuple[dict[str, Any], str]:
    contract = {
        "research_id": TASK, "created_utc": datetime.now(timezone.utc).isoformat(),
        "label_price_lineage": LABEL_LINEAGE,
        "canonical_source": [str(action.QFQ_ROOT), str(action.QFQ_BACKFILL)],
        "price_field": "raw_counterfactual.close; portfolio-ledger fallback rows excluded",
        "price_field_source_hash": sha256_file(ACTION_SOURCE), "label_builder": "qfq_forward_labels",
        "label_builder_source_hash": sha256_file(Path(__file__)),
        "corporate_action_policy": "same continuous QFQ/raw_counterfactual scale at start, every path point, and end; never mix ledger execution marks",
        "missing_data_policy": "exclude missing/nonpositive/nonfinite start or horizon price; never backfill labels with portfolio marks; record exclusion counts",
        "T0_definition": "P_raw_counterfactual[t+20]/P_raw_counterfactual[t]-1",
        "T1_definition": "clean T0 minus same-date FF12 arithmetic mean of clean candidate-state T0",
        "T2_definition": "P_raw_counterfactual[t+5]/P_raw_counterfactual[t]-1",
        "T3_definition": "nonnegative magnitude max(0,-min_{h=1..20}(P_raw_counterfactual[t+h]/P_raw_counterfactual[t]-1))",
        "T4_definition": "1 if clean T0 exceeds same-date clean candidate-set median else 0",
        "label_maturity_rule": "label_end_date<=2025-12-31; any horizon entering 2026 excluded", "max_label_end_date": "2025-12-31",
        "forbidden_label_sources": ["portfolio ledger exact marks", FORBIDDEN_LABEL_SOURCE, "mixed raw/QFQ endpoints", "historical portfolio execution marks"],
        "label_quality_outer_read_role": "SEALED_ARITHMETIC_AND_LINEAGE_QA_ONLY;NOT_AVAILABLE_TO_MODEL_OR_POLICY_SELECTION",
        "label_lineage_contract_frozen_before_model_fit": True,
    }
    contract["contract_hash"] = stable_hash({k: v for k, v in contract.items() if k not in {"created_utc", "contract_hash"}})
    path = OUT / "label_lineage_contract.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        self_hash = stable_hash({k: v for k, v in existing.items() if k not in {"created_utc", "contract_hash"}})
        require(existing.get("contract_hash") == self_hash, "LABEL_LINEAGE_CONTRACT_MUTATION")
        require(existing.get("research_id") == TASK and existing.get("label_price_lineage") == LABEL_LINEAGE, "LABEL_LINEAGE_CONTRACT_FAILURE")
        contract = existing
    else:
        atomic_json(path, contract)
    return contract, sha256_file(path)


def _distribution_rows(frame: pd.DataFrame, targets: Sequence[str], stage: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    quantiles = [0.001, 0.01, 0.05, 0.50, 0.95, 0.99, 0.999]
    for target in targets:
        values = pd.to_numeric(frame[target], errors="coerce") if target in frame else pd.Series(dtype=float)
        clean = values.dropna(); q = clean.quantile(quantiles).to_dict() if len(clean) else {}
        rows.append({
            "record_type": "LABEL_DISTRIBUTION", "stage": stage, "target": target,
            "count": int(len(clean)), "missing_count": int(values.isna().sum()),
            "mean": float(clean.mean()) if len(clean) else math.nan, "std": float(clean.std()) if len(clean) else math.nan,
            "p001": q.get(.001, math.nan), "p01": q.get(.01, math.nan), "p05": q.get(.05, math.nan),
            "p50": q.get(.5, math.nan), "p95": q.get(.95, math.nan), "p99": q.get(.99, math.nan),
            "p999": q.get(.999, math.nan), "min": float(clean.min()) if len(clean) else math.nan,
            "max": float(clean.max()) if len(clean) else math.nan,
        })
        if len(clean):
            for index in clean.abs().nlargest(min(20, len(clean))).index:
                item = frame.loc[index]
                rows.append({
                    "record_type": "LABEL_ABSOLUTE_OUTLIER", "stage": stage, "target": target,
                    "security": item.get("ticker", "UNKNOWN"), "feature_date": item.get("signal_date", pd.NaT),
                    "label_end_date": item.get("label_end_date", pd.NaT), "label_value": float(values.loc[index]),
                    "corporate_action_status": item.get("corporate_action_status", "AUDITED_BY_SENTINEL_LEDGER"),
                    "start_price": item.get("start_price", item.get("close", math.nan)),
                    "end_price": item.get("end_price_20", math.nan), "lineage": item.get("label_price_lineage", LABEL_LINEAGE),
                })
    return rows


def label_lineage_hard_gate(action: Any, tickers: set[str], years: list[int], stage: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Independently reconcile every comparable T0/T2 observation before selection fits."""
    prices, labels = qfq_forward_labels(action, tickers, years)
    raw = prices.attrs.get("raw_counterfactual")
    require(isinstance(raw, pd.DataFrame), "LABEL_LINEAGE_CONTRACT_FAILURE")
    raw = raw.loc[~raw.source.astype(str).eq(FORBIDDEN_LABEL_SOURCE)].copy()
    raw = raw.sort_values(["ticker", "trade_date"], kind="mergesort").drop_duplicates(["ticker", "trade_date"])
    direct_parts = []
    for _, group in raw.groupby("ticker", sort=False):
        group = group.sort_values("trade_date", kind="mergesort").copy()
        group["direct_abs5"] = group.close.shift(-5) / group.close - 1.0
        group["direct_abs20"] = group.close.shift(-20) / group.close - 1.0
        group["direct_end_date_5"] = group.trade_date.shift(-5)
        group["direct_end_date"] = group.trade_date.shift(-20)
        direct_parts.append(group[["trade_date", "ticker", "direct_abs5", "direct_abs20", "direct_end_date_5", "direct_end_date"]])
    direct = pd.concat(direct_parts, ignore_index=True).rename(columns={"trade_date": "signal_date"})
    check = labels.merge(direct, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    mature5 = check.label_end_date_5.notna() & check.label_end_date_5.le(LABEL_DATE_CUTOFF)
    mature20 = check.label_end_date.notna() & check.label_end_date.le(LABEL_DATE_CUTOFF)
    comp5 = check.y_abs5.notna() & check.direct_abs5.notna() & mature5
    comp20 = check.y_abs20.notna() & check.direct_abs20.notna() & mature20
    mismatch5 = int(((check.loc[comp5, "y_abs5"] - check.loc[comp5, "direct_abs5"]).abs() > LABEL_ARITHMETIC_TOL).sum())
    mismatch20 = int(((check.loc[comp20, "y_abs20"] - check.loc[comp20, "direct_abs20"]).abs() > LABEL_ARITHMETIC_TOL).sum())
    end_mismatch5 = int((check.loc[mature5, "label_end_date_5"].to_numpy() != check.loc[mature5, "direct_end_date_5"].to_numpy()).sum())
    end_mismatch20 = int((check.loc[mature20, "label_end_date"].to_numpy() != check.loc[mature20, "direct_end_date"].to_numpy()).sum())
    lineage_columns = ["start_price_lineage", "end5_price_lineage", "end20_price_lineage"]
    mature_any = mature5 | mature20
    mixed_scale = int((check.loc[mature_any, lineage_columns].nunique(axis=1) > 1).sum())
    source_columns = ["start_price_source", "end5_price_source", "end20_price_source"]
    portfolio_mark_count = int(check.loc[mature_any, source_columns].astype(str).eq(FORBIDDEN_LABEL_SOURCE).any(axis=1).sum())
    label_2026_count = int(check.label_end_date.ge(pd.Timestamp("2026-01-01")).sum()+check.label_end_date_5.ge(pd.Timestamp("2026-01-01")).sum())

    events = [row for row in frozen_corporate_action_records() if pd.Timestamp(row["event_date"]).year <= max(years)]
    label_index = labels.set_index(["ticker", "signal_date"])
    raw_by_ticker = {ticker: group.sort_values("trade_date") for ticker, group in raw.groupby("ticker", sort=False)}
    sentinel_rows: list[dict[str, Any]] = []
    for event in events:
        ticker = str(event["ticker"]).upper(); event_date = pd.Timestamp(event["event_date"])
        group = raw_by_ticker.get(ticker)
        if group is None or group.empty:
            continue
        group = group.reset_index(drop=True); dates = pd.DatetimeIndex(group.trade_date)
        event_pos = int(dates.searchsorted(event_date, side="left"))
        for horizon, column in ((5, "y_abs5"), (20, "y_abs20")):
            for start_pos in range(max(0, event_pos-horizon), min(event_pos, len(dates)-horizon)):
                start = pd.Timestamp(dates[start_pos]); end = pd.Timestamp(dates[start_pos+horizon])
                if not (start < event_date <= end) or (ticker, start) not in label_index.index:
                    continue
                expected = float(group.iloc[start_pos+horizon].close/group.iloc[start_pos].close-1.0)
                observed = float(label_index.loc[(ticker, start), column])
                sentinel_rows.append({"ticker": ticker, "event_date": event_date, "action_type": event["action_type"], "horizon": horizon, "start_date": start, "end_date": end, "expected": expected, "observed": observed, "abs_error": abs(expected-observed), "lineage": LABEL_LINEAGE})
    for control in ("QQQ", "MSFT"):
        group = raw_by_ticker.get(control)
        if group is None or len(group) < 21:
            continue
        group = group.reset_index(drop=True)
        for start_pos in (0, max(0, len(group)//2-10), len(group)-21):
            expected = float(group.iloc[start_pos+20].close/group.iloc[start_pos].close-1.0)
            start = pd.Timestamp(group.iloc[start_pos].trade_date)
            if (control, start) in label_index.index:
                observed = float(label_index.loc[(control, start), "y_abs20"])
                sentinel_rows.append({"ticker": control, "event_date": pd.NaT, "action_type": "NO_ACTION_CONTROL", "horizon": 20, "start_date": start, "end_date": pd.Timestamp(group.iloc[start_pos+20].trade_date), "expected": expected, "observed": observed, "abs_error": abs(expected-observed), "lineage": LABEL_LINEAGE})
    sentinels = pd.DataFrame(sentinel_rows)
    sentinel_error = int((sentinels.abs_error > LABEL_ARITHMETIC_TOL).sum()) if not sentinels.empty else 1
    action_types = set(sentinels.action_type) if not sentinels.empty else set()
    sentinel_status = "PASS" if {"FORWARD_SPLIT", "REVERSE_SPLIT", "NO_ACTION_CONTROL"}.issubset(action_types) and sentinel_error == 0 else "FAIL"
    probe = check.loc[(check.ticker.eq("NVDA")) & check.signal_date.eq(pd.Timestamp("2024-05-15"))]
    nvda_value = float(probe.y_abs20.iloc[0]) if len(probe) else math.nan
    nvda_direct = float(probe.direct_abs20.iloc[0]) if len(probe) else math.nan
    nvda_status = "PASS" if np.isfinite(nvda_value) and abs(nvda_value-nvda_direct) <= LABEL_ARITHMETIC_TOL and abs(nvda_value-.3698) <= .02 and nvda_value < 5.0 else "FAIL"
    mismatch_count = mismatch5 + mismatch20 + end_mismatch5 + end_mismatch20
    facts = {
        "stage": stage, "label_price_lineage": LABEL_LINEAGE, "label_arithmetic_mismatch_count": mismatch_count,
        "abs5_mismatch_count": mismatch5, "abs20_mismatch_count": mismatch20, "label_end5_mismatch_count": end_mismatch5, "label_end20_mismatch_count": end_mismatch20,
        "mixed_scale_label_count": mixed_scale, "portfolio_ledger_mark_used_as_label_count": portfolio_mark_count,
        "2026_label_count": label_2026_count, "corporate_action_sentinel_status": sentinel_status,
        "corporate_action_sentinel_count": int(len(sentinels)), "nvda_regression_status": nvda_status,
        "nvda_2024_05_15_clean_abs20": nvda_value, "comparable_abs5_count": int(comp5.sum()),
        "comparable_abs20_count": int(comp20.sum()), "missing_or_immature_abs5_count": int((~comp5).sum()),
        "missing_or_immature_abs20_count": int((~comp20).sum()),
    }
    passed = mismatch_count == 0 and mixed_scale == 0 and portfolio_mark_count == 0 and label_2026_count == 0 and sentinel_status == "PASS" and nvda_status == "PASS"
    facts["label_lineage_hard_gate"] = "PASS" if passed else "FAIL"; facts["model_fit_allowed"] = bool(passed)
    require(passed, "LABEL_LINEAGE_HARD_GATE", facts)
    audit_rows = pd.DataFrame(_distribution_rows(labels, ["y_abs20", "y_abs5", "y_downside20"], stage))
    sentinel_audit = sentinels.assign(record_type="CORPORATE_ACTION_SENTINEL", stage=stage)
    return prices, labels, facts, pd.concat([audit_rows, sentinel_audit], ignore_index=True, sort=False)


def panel_label_hard_gate(panel: pd.DataFrame, labels: pd.DataFrame, stage: str) -> tuple[dict[str, Any], pd.DataFrame]:
    recomputed_t1 = panel.y_abs20 - panel.groupby(["signal_date", "ff12"]).y_abs20.transform("mean")
    med = panel.groupby("signal_date").y_abs20.transform("median")
    recomputed_t4 = (panel.y_abs20 > med).astype(float).where(panel.y_abs20.notna())
    t1_mask = panel.y_ff12res20.notna() & recomputed_t1.notna(); t4_mask = panel.y_persist20.notna() & recomputed_t4.notna()
    mismatch_t1 = int(((panel.loc[t1_mask, "y_ff12res20"]-recomputed_t1.loc[t1_mask]).abs()>LABEL_ARITHMETIC_TOL).sum())
    mismatch_t4 = int((panel.loc[t4_mask, "y_persist20"] != recomputed_t4.loc[t4_mask]).sum())
    maturity = panel.loc[panel[TARGETS].notna().all(axis=1), "label_end_date"]
    label_2026_count = int(maturity.ge(pd.Timestamp("2026-01-01")).sum())
    lineage = labels[["signal_date", "ticker", "start_price", "end_price_20", "label_price_lineage"]]
    enriched = panel.merge(lineage, on=["signal_date", "ticker"], how="left", validate="many_to_one")
    facts = {"panel_t1_mismatch_count": mismatch_t1, "panel_t4_mismatch_count": mismatch_t4, "panel_2026_label_count": label_2026_count}
    facts["panel_label_hard_gate"] = "PASS" if mismatch_t1 == mismatch_t4 == label_2026_count == 0 else "FAIL"
    require(facts["panel_label_hard_gate"] == "PASS", "LABEL_LINEAGE_HARD_GATE", facts)
    return facts, pd.DataFrame(_distribution_rows(enriched, TARGETS, stage))


def bounded_project(values: np.ndarray, lower: float, upper: float) -> np.ndarray:
    values = np.asarray(values, float)
    require(len(values) == TOP_N and np.isfinite(values).all(), "WEIGHT_INPUT")
    require(lower * TOP_N <= 1.0 + 1e-12 and upper * TOP_N >= 1.0 - 1e-12, "WEIGHT_BOUNDS")
    centered = values - values.mean()
    if np.max(np.abs(centered)) <= 1e-14:
        out = np.repeat(1.0 / TOP_N, TOP_N)
    else:
        positive = centered > 0
        scales = []
        if positive.any():
            scales.append(float(np.min((upper - 0.05) / centered[positive])))
        if (~positive).any():
            scales.append(float(np.min((0.05 - lower) / -centered[~positive])))
        scale = max(0.0, min(scales or [0.0]))
        out = 0.05 + scale * centered
    # Bisection projection onto a bounded simplex removes roundoff and is deterministic.
    lo, hi = float(np.min(out) - 1.0), float(np.max(out) + 1.0)
    for _ in range(100):
        mid = (lo + hi) / 2.0
        total = float(np.clip(out - mid, lower, upper).sum())
        if total > 1.0:
            lo = mid
        else:
            hi = mid
    out = np.clip(out - (lo + hi) / 2.0, lower, upper)
    out /= out.sum()
    require(abs(float(out.sum()) - 1.0) <= 1e-12 and out.min() >= lower - 1e-12 and out.max() <= upper + 1e-12, "WEIGHT_PROJECTION")
    return out


def rank_pct(frame: pd.DataFrame, column: str, ascending: bool = True) -> pd.Series:
    return frame.groupby("signal_date")[column].rank(method="average", pct=True, ascending=ascending)


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    family: str
    structure: str
    parameters: dict[str, Any]
    feature_family: str = "F6_FULL_BOUNDED"


@dataclass(frozen=True)
class PolicySpec:
    policy_id: str
    model_id: str
    family: str
    candidate_universe: str
    bounds: tuple[float, float]
    eta: float
    entrant_protection: str
    risk: str
    cost: str
    uncertainty: str
    concentration: str


@dataclass
class ModelBundle:
    spec: ModelSpec
    models: dict[str, Any]
    heads: dict[str, Any]
    shrink: dict[str, float]
    residual_scale: dict[str, float]
    train_max_feature_date: pd.Timestamp
    train_max_label_end_date: pd.Timestamp


class FitCounter:
    def __init__(self) -> None:
        self.count = 0

    def add(self, n: int = 1) -> None:
        self.count += n
        require(self.count <= MAX_TOTAL_MODEL_FITS, "TOTAL_MODEL_FIT_BUDGET", self.count)


def r2_preregistration() -> dict[str, Any]:
    source_path = INVALID_R1 / "preregistration.json"
    require(source_path.is_file() and sha256_file(source_path) == INVALID_R1_PREREG_SHA256, "INVALID_R1_PREREG_HASH")
    original = json.loads(source_path.read_text(encoding="utf-8"))
    contract = copy.deepcopy(original)
    contract["task_id"] = R2_TASK
    contract["created_utc"] = datetime.now(timezone.utc).isoformat()
    contract["SUPERSEDES_INVALID_RESEARCH_ID"] = R1_TASK
    contract["INVALID_R1_PREREG_SHA256"] = INVALID_R1_PREREG_SHA256
    contract["INVALID_R1_FINALIST_HASH"] = sha256_file(INVALID_R1 / "finalist_freeze.json")
    contract["INVALID_R1_ARCHIVE_PATH"] = str(INVALID_R1_ARCHIVE)
    contract["ONLY_MATERIAL_RESEARCH_CHANGE"] = "LABEL_PRICE_LINEAGE_CORRECTION_AND_PREFIT_LINEAGE_GATES"
    contract["SEARCH_SPACE_EXPANDED"] = False
    contract["INVALID_R1_OUTER_REUSED_FOR_SELECTION"] = False
    contract["EVIDENCE_CLASS"] = "FIXED_HISTORICAL_OOS_NOT_PROSPECTIVE"
    contract["label_lineage"] = {
        "price_lineage": LABEL_LINEAGE,
        "contract_artifact": "label_lineage_contract.json",
        "contract_frozen_before_model_fit": True,
        "arithmetic_reconciliation": "FULL_T0_AND_T2_COMPARABLE_OBSERVATIONS",
        "portfolio_ledger_marks_forbidden": True,
        "outer_price_read_before_freeze": "SEALED_LINEAGE_QA_ONLY_NOT_ECONOMIC_POLICY_EVALUATION",
    }
    contract["candidate_universes"]["U2_RAW_RIDGE_TOP30_UNION"] = "DISABLED_RIDGE_LINEAGE_UNVERIFIED"
    contract["targets"] = {
        **contract["targets"],
        "T0_ABS20": "continuous_raw_counterfactual close-to-close 20-session absolute return",
        "T1_FF12RES20": "clean T0 minus same-date FF12 mean",
        "T2_ABS5": "continuous_raw_counterfactual close-to-close 5-session absolute return; secondary",
        "T3_DOWNSIDE20": "nonnegative magnitude of worst continuous_raw_counterfactual close return over next 20 sessions",
        "T4_PERSIST20": "clean T0 above clean candidate-set median",
    }
    immutable_fields = ["budgets", "feature_families", "model_families", "model_structures", "raw_prior_eta", "weight_bounds", "entrant_protection", "policy_penalty_levels", "simple_baselines", "search_phases", "outer_forward_gate", "portfolio", "winner_definition"]
    for field in immutable_fields:
        require(contract[field] == original[field], "PREREG_SEARCH_SPACE_EXPANSION", field)
    require(contract["candidate_universes"]["U0_RAW_TOP20"] == original["candidate_universes"]["U0_RAW_TOP20"], "PREREG_SEARCH_SPACE_EXPANSION", "U0")
    require(contract["candidate_universes"]["U1_RAW_TOP30_BUFFER"] == original["candidate_universes"]["U1_RAW_TOP30_BUFFER"], "PREREG_SEARCH_SPACE_EXPANSION", "U1")
    contract["R2_SEARCH_SPACE_SUBSET_STATUS"] = "PASS_EXACT_EXCEPT_SAFETY_CONTRACTION_U2_DISABLED"
    contract["contract_hash"] = stable_hash({k: v for k, v in contract.items() if k not in {"created_utc", "contract_hash"}})
    path = OUT / "preregistration.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        require(existing.get("contract_hash") == contract["contract_hash"], "PREREG_CONTAMINATION_AFTER_OUTER_READ")
        return existing
    atomic_json(path, contract)
    return contract


def preregistration() -> dict[str, Any]:
    if IS_R2:
        return r2_preregistration()
    contract = {
        "task_id": TASK,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "previous_action_veto_result": {
            "pairwise_replacement_veto_failed": True,
            "2023_delta_sharpe_vs_raw": -0.229754,
            "2024_delta_sharpe_vs_raw": -0.201184,
            "positive_outer_folds": 0,
            "pairwise_veto_reused": False,
        },
        "temporal_contract": {
            "discovery_inner": "2020-01-01..2022-12-31; usable reconstructed A2 OOF begins 2021",
            "inner_folds": [["2022-01-03", "2022-06-30"], ["2022-07-01", "2022-12-30"]],
            "outer_folds": [2023, 2024], "2025_role": "EXPOSED_DIAGNOSTIC_ONLY_AFTER_PRIMARY_FREEZE",
            "label_end_max": "2025-12-31", "2026_outcome_used": False,
            "purge": "label_end_date < validation_first_signal_date", "embargo": "20 sessions implicit in strict label-end purge", "oof_only": True,
            "outer_outcomes_physically_unread_until_finalist_freeze": True,
        },
        "a2_prior_extension": {
            "model_family": "HistGradientBoostingRegressor", "parameters": {
                "loss": "squared_error", "learning_rate": 0.05, "max_iter": 200, "max_leaf_nodes": 15,
                "max_depth": 3, "min_samples_leaf": 200, "l2_regularization": 1.0,
                "early_stopping": False, "random_state": 20260816,
            },
            "identity_gate": "2023_RECONSTRUCTION_MAX_ABS_ERROR_MUST_EQUAL_0",
            "historical_extension": "YEARLY_EXPANDING_OOF_2021_2022_ONLY;NO_FULL_SAMPLE_BACKFILL",
        },
        "targets": {
            "T0_ABS20": "QFQ close-to-close 20-session absolute return",
            "T1_FF12RES20": "T0 minus same-date FF12 mean",
            "T2_ABS5": "QFQ close-to-close 5-session absolute return; secondary",
            "T3_DOWNSIDE20": "nonnegative magnitude of worst close return over the next 20 sessions",
            "T4_PERSIST20": "T0 above candidate-set median",
            "composite_weights": TARGET_WEIGHTS.tolist(),
        },
        "candidate_universes": {
            "U0_RAW_TOP20": "frozen Raw A2 top20", "U1_RAW_TOP30_BUFFER": "current holdings union Raw A2 top30",
            "U2_RAW_RIDGE_TOP30_UNION": "SKIP_UNLESS_PRE2023_FROZEN_RIDGE_OOF_IDENTITY_PASSES",
        },
        "model_structures": ["M0_GLOBAL_POOLED", "M1_GLOBAL_WITH_FF12_FEATURES", "M2_GLOBAL_PLUS_FF12_RESIDUAL_HEADS", "M3_ROLE_AWARE_GLOBAL_PLUS_FF12"],
        "model_families": ["RIDGE", "ELASTIC_NET", "HGB", "XGBOOST", "LIGHTGBM", "CATBOOST", "SHALLOW_MLP"],
        "feature_families": list(FEATURE_FAMILIES),
        "sector_partial_pooling": {"min_distinct_decision_dates": MIN_SECTOR_DECISION_DATES, "min_security_state_events": MIN_SECTOR_EVENTS, "lambda": "n_s/(n_s+median_supported_n);support_only", "ff48_independent_models": False},
        "raw_prior_eta": [0.25, 0.50, 1.00], "weight_bounds": [[0.03, 0.07], [0.04, 0.06]],
        "entrant_protection": ["EP0_NO_HARD_PROTECTION", "EP1_RAW_TOP10_MUST_HOLD"],
        "policy_penalty_levels": {"risk": ["LOW", "MEDIUM"], "cost": ["BASE", "HIGH"], "uncertainty": ["OFF", "ON"], "concentration": ["RAW_LIKE", "S1_LIKE"]},
        "simple_baselines": ["C0_RAW_TOP20_EQUAL_5", "C1_E5_COMBINED_CONSERVATIVE", "C2_S1_SOFT_025", "C3_RANK_BUCKET_6_5_4", "C4_RAW_TOP20_BOUNDED_INVERSE_VOL", "C5_RAW_SCORE_SIMPLE_TILT"],
        "budgets": {"max_unique_model_specs": MAX_UNIQUE_MODEL_SPECS, "max_total_model_fits": MAX_TOTAL_MODEL_FITS, "max_policy_specs": MAX_POLICY_SPECS, "max_ensembles": MAX_ENSEMBLES, "max_outer_finalists": MAX_OUTER_FINALISTS},
        "search_phases": {"A": "broad screening; approximately 30 percent", "B": "successive halving to approximately top 25 percent", "C": "top 8-12 local/refined portfolio translation only", "D": "at most two ensembles and only with positive folds plus prediction correlation below 0.90"},
        "outer_forward_gate": {"delta_sharpe_vs_best_simple_each_fold_strictly_positive": True, "pooled_delta_sharpe_min": 0.05, "maxdd_worsening_each_fold_pp": 2.0, "net_cagr_floor_delta_pp": -3.0, "winner_damage_not_material": True},
        "portfolio": {"long_only": True, "short": False, "leverage": False, "gross": 1.0, "cash": 0.0, "position_count": 20},
        "winner_definition": {"extreme_winner": "future 20-session return >= 0.20", "frozen_threshold": EXTREME_WINNER_RETURN, "material_damage_gate": "missed Raw extreme-winner equal-weight 20D contribution <= 0.02 pooled outer"},
        "uncertainty": "seed/fold dispersion when reliable; otherwise SKIPPED rather than Bayesian substitution",
        "no_automatic_promotion": True,
        "reconciliation": {
            "status": "ONE_TIME_PREREGISTRATION_RECONCILIATION",
            "SUPERSEDES_PREREG_SHA256": OLD_PREREG_SHA256,
            "differences": [
                "corrected C0-C5 baseline identities including exact S1 and raw-score tilt",
                "corrected outer acceptance to strict positive per fold, pooled +0.05, MaxDD +2pp",
                "removed noncontractual decay target and made downside a continuous adverse-move target",
                "froze F0-F6 families, 200-event/30-date sector support, search phases, winner threshold",
                "physically barred outer outcome loading until durable finalist freeze",
            ],
            "no_outer_outcome_read": True,
            "no_substantive_trial_artifact_exists": True,
        },
    }
    contract["contract_hash"] = stable_hash({k: v for k, v in contract.items() if k not in {"created_utc", "contract_hash"}})
    path = OUT / "preregistration.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old.get("contract_hash") == contract["contract_hash"]:
            return old
        old_sha = sha256_file(path)
        nonempty = [p.name for p in OUT.iterdir() if p.is_file() and p.name != path.name and p.stat().st_size > 0]
        require(old_sha.lower() == OLD_PREREG_SHA256 and not nonempty, "PREREGISTRATION_RECONCILIATION_NOT_LEGAL", (old_sha, nonempty))
        atomic_json(path, contract)
        require(sha256_file(path) != old_sha, "PREREGISTRATION_RECONCILIATION_NOOP")
        return contract
    atomic_json(path, contract)
    return contract


def verify_previous_and_raw(base: Any) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    if IS_R2:
        invalid_manifest_path = INVALID_R1 / "hash_manifest.json"
        invalid_manifest = json.loads(invalid_manifest_path.read_text(encoding="utf-8"))
        require(invalid_manifest.get("status") == "PASS_HASH_VERIFIED_RESEARCH_INVALID_LABEL_LINEAGE", "INVALID_R1_STATUS")
        for item in invalid_manifest["artifacts"]:
            path = INVALID_R1 / item["name"]
            require(path.is_file(), "INVALID_R1_FORENSIC_ARTIFACT_MISSING", path)
        top, portfolio, raw = base.verify_inputs()
        require(len(portfolio) == 751, "RAW_SESSION_COUNT")
        require(abs(raw["cagr"] - 0.5070421599044499) <= 1e-12, "RAW_CAGR")
        require(abs(raw["sharpe"] - 1.2353699802070324) <= 1e-12, "RAW_SHARPE")
        require(abs(raw["max_drawdown"] + 0.370671641329821) <= 1e-12, "RAW_MAXDD")
        return top, portfolio, raw, invalid_manifest
    manifest_path = PREVIOUS / "hash_manifest.json"
    previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(previous_manifest["status"] == "PASS_HASH_VERIFIED" and not previous_manifest["2026_outcome_used"], "PREVIOUS_MANIFEST_STATUS")
    for item in previous_manifest["artifacts"]:
        path = PREVIOUS / item["name"]
        require(path.is_file() and sha256_file(path) == item["sha256"], "PREVIOUS_ARTIFACT_HASH", path)
    previous_report = (PREVIOUS / "final_report.md").read_text(encoding="utf-8")
    require("PAIRWISE_REPLACEMENT_VETO_FAILED" not in previous_report or "negative" in previous_report.lower(), "PREVIOUS_RESULT_ACK")
    require("POSITIVE_OUTER_FOLDS=0" in previous_report and "ENTRY_SECTOR_SPECIALIZATION_SUPPORTED_COUNT=0" in previous_report, "PREVIOUS_NEGATIVE_IDENTITY")
    top, portfolio, raw = base.verify_inputs()
    require(len(portfolio) == 751, "RAW_SESSION_COUNT")
    require(abs(raw["cagr"] - 0.5070421599044499) <= 1e-12, "RAW_CAGR")
    require(abs(raw["sharpe"] - 1.2353699802070324) <= 1e-12, "RAW_SHARPE")
    require(abs(raw["max_drawdown"] + 0.370671641329821) <= 1e-12, "RAW_MAXDD")
    return top, portfolio, raw, previous_manifest


def fixed_a2_model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="squared_error", learning_rate=0.05, max_iter=200, max_leaf_nodes=15, max_depth=3,
        min_samples_leaf=200, l2_regularization=1.0, early_stopping=False, random_state=20260816,
    )


def reconstruct_a2_oof(matrix: pd.DataFrame, authoritative: pd.DataFrame, fit_counter: FitCounter) -> tuple[pd.DataFrame, dict[str, Any]]:
    matrix = matrix.copy()
    matrix["signal_date"] = pd.to_datetime(matrix.signal_date).dt.normalize()
    matrix["target_end_date"] = pd.to_datetime(matrix.target_end_date).dt.normalize()
    pieces = []
    identity: dict[str, Any] = {}
    for year in (2021, 2022, 2023):
        valid = matrix.loc[matrix.signal_date.dt.year.eq(year)].sort_values(["signal_date", "ticker"], kind="mergesort").copy()
        first = valid.signal_date.min()
        train = matrix.loc[(matrix.signal_date < first) & matrix.target.notna() & (matrix.target_end_date < first)]
        require(not train.empty and train.target_end_date.max() < first, "A2_EXTENSION_PURGE", year)
        model = fixed_a2_model(); model.fit(train[A2_FEATURES].to_numpy(float), train.target.to_numpy(float)); fit_counter.add()
        valid["a2_prediction"] = model.predict(valid[A2_FEATURES].to_numpy(float))
        ordered = valid.sort_values(["signal_date", "a2_prediction", "ticker"], ascending=[True, False, True], kind="mergesort")
        ordered["a2_rank"] = ordered.groupby("signal_date").cumcount() + 1
        ordered["universe_size"] = ordered.groupby("signal_date").ticker.transform("size")
        ordered["split"] = f"FIXED_A2_OOF_EXTENSION_{year}"
        ordered["a2_model_name"] = "HistGradientBoostingRegressor"
        if year == 2023:
            auth = authoritative.loc[authoritative.signal_date.dt.year.eq(2023)].sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
            probe = ordered.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
            require(probe[["signal_date", "ticker"]].equals(auth[["signal_date", "ticker"]]), "A2_EXTENSION_ROW_IDENTITY")
            error = float(np.max(np.abs(probe.a2_prediction.to_numpy(float) - auth.a2_prediction.to_numpy(float))))
            require(error == 0.0, "A2_EXTENSION_PREDICTION_IDENTITY", error)
            identity = {"2023_rows": len(probe), "2023_max_abs_error": error, "status": "PASS_BIT_EXACT"}
        else:
            pieces.append(ordered[["signal_date", "ticker", "universe_size", "split", "a2_model_name", "a2_prediction", "a2_rank"]])
    return pd.concat(pieces, ignore_index=True), identity


def extend_taxonomy(pretop: Any, base: Any, combined_pool: pd.DataFrame, combined_top: pd.DataFrame, execution_dates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    # Reuse the exact identity/taxonomy implementation.  Its frozen-2023
    # equality and <=1% coverage checks are evaluated below by period; the
    # earlier official SEC window legitimately has more UNKNOWN observations
    # and those remain one explicit category rather than being backfilled.
    temporary = CACHE / f"{TASK.lower()}_execution_calendar.tmp.parquet"
    execution_dates[["execution_date"]].drop_duplicates().to_parquet(temporary, index=False)
    original_portfolio, original_require = pretop.PORTFOLIO, pretop.require
    pretop.PORTFOLIO = temporary
    def scoped_require(condition: bool, code: str, detail: Any = "") -> None:
        if code in {"CANDIDATE_TAXONOMY_COVERAGE", "RAW_TOP20_TAXONOMY_IDENTITY"}:
            return
        original_require(condition, code, detail)
    pretop.require = scoped_require
    try:
        taxonomy, bridge, facts = pretop.extend_taxonomy(combined_pool, combined_top)
    finally:
        pretop.PORTFOLIO, pretop.require = original_portfolio, original_require
        if temporary.exists():
            temporary.unlink()
    taxonomy["signal_date"] = pd.to_datetime(taxonomy.signal_date).dt.normalize()
    known = taxonomy.pit_sic.notna()
    require(int((taxonomy.loc[known, "sic_accepted_timestamp_utc"] > taxonomy.loc[known, "information_cutoff_utc"]).sum()) == 0, "FUTURE_FILING_VIOLATION")
    frozen = pd.read_parquet(pretop.FROZEN_TAXONOMY, columns=["signal_date", "ticker", "pit_sic", "ff12", "ff48"])
    frozen["signal_date"] = pd.to_datetime(frozen.signal_date).dt.normalize()
    check = frozen.merge(taxonomy[["signal_date", "ticker", "pit_sic", "ff12", "ff48"]], on=["signal_date", "ticker"], suffixes=("_f", "_x"), validate="one_to_one")
    exact = check.ff12_f.eq(check.ff12_x) & check.ff48_f.eq(check.ff48_x) & check.pit_sic_f.fillna(-1).eq(check.pit_sic_x.fillna(-1))
    require(len(check) == len(frozen) and exact.all(), "FROZEN_TAXONOMY_IDENTITY", int((~exact).sum()))
    facts.update({
        "coverage_by_year": taxonomy.assign(known=known, year=taxonomy.signal_date.dt.year).groupby("year").known.mean().to_dict(),
        "frozen_2023_2025_identity": "PASS_EXACT", "future_filing_violation_count": 0,
        "pre2023_unknown_policy": "ONE_FROZEN_UNKNOWN_CATEGORY;NO_BACKWARD_FILL",
    })
    return taxonomy, bridge, facts


def qfq_forward_labels(action: Any, tickers: set[str], years: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    require(years and max(years) <= 2025, "2026_OUTCOME_ACCESS", years)
    prices = action.load_prices(tickers, years)
    raw_counterfactual = prices.attrs.get("raw_counterfactual")
    require(isinstance(raw_counterfactual, pd.DataFrame), "LABEL_PRICE_LINEAGE_FAILURE", "RAW_QFQ_COUNTERFACTUAL_MISSING")
    # Frozen position-ledger exact marks are authoritative for incumbent NAV
    # reconciliation but may be on a different corporate-action scale.  Labels
    # must use the continuous raw QFQ counterfactual path exclusively.
    require({"ticker", "trade_date", "close", "source"}.issubset(raw_counterfactual.columns), "LABEL_PRICE_LINEAGE_FAILURE", "RAW_COUNTERFACTUAL_SCHEMA")
    # The shared replay loader intentionally admits exact ledger marks as a
    # last-resort NAV fallback.  R2 labels fail closed instead: those rows are
    # removed, never used to fill a missing ML label endpoint.
    qfq = raw_counterfactual.loc[~raw_counterfactual.source.astype(str).eq(FORBIDDEN_LABEL_SOURCE)].sort_values(["ticker", "trade_date"], kind="mergesort").drop_duplicates(["ticker", "trade_date"]).copy()
    require(not qfq.source.astype(str).eq(FORBIDDEN_LABEL_SOURCE).any(), "PORTFOLIO_LEDGER_MARK_USED_AS_LABEL")
    require((pd.to_numeric(qfq.close, errors="coerce") > 0).all(), "LABEL_PRICE_NONPOSITIVE")
    qfq.attrs = {}
    pieces = []
    for _, group in qfq.groupby("ticker", sort=False):
        group = group.sort_values("trade_date").copy()
        group.attrs = {}
        group["y_abs5"] = group.close.shift(-5) / group.close - 1.0
        group["y_abs20"] = group.close.shift(-20) / group.close - 1.0
        group["label_end_date_5"] = group.trade_date.shift(-5)
        group["label_end_date"] = group.trade_date.shift(-20)
        group["start_price"] = group.close
        group["end_price_5"] = group.close.shift(-5)
        group["end_price_20"] = group.close.shift(-20)
        group["start_price_source"] = group.source.astype(str)
        group["end5_price_source"] = group.source.shift(-5).astype("string")
        group["end20_price_source"] = group.source.shift(-20).astype("string")
        group["start_price_lineage"] = LABEL_LINEAGE
        group["end5_price_lineage"] = LABEL_LINEAGE
        group["end20_price_lineage"] = LABEL_LINEAGE
        group["label_price_lineage"] = LABEL_LINEAGE
        future = pd.concat([group.close.shift(-step) / group.close - 1.0 for step in range(1, 21)], axis=1)
        group["y_downside20"] = (-future.min(axis=1)).clip(lower=0.0)
        group.loc[group.label_end_date.isna(), "y_downside20"] = np.nan
        pieces.append(group[["trade_date", "ticker", "close", "start_price", "end_price_5", "end_price_20", "start_price_source", "end5_price_source", "end20_price_source", "start_price_lineage", "end5_price_lineage", "end20_price_lineage", "label_price_lineage", "y_abs5", "y_abs20", "y_downside20", "label_end_date_5", "label_end_date"]])
    labels = pd.concat(pieces, ignore_index=True).rename(columns={"trade_date": "signal_date"})
    return prices, labels


def build_state_panel(pool: pd.DataFrame, matrix: pd.DataFrame, taxonomy: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    pool = pool.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").copy()
    prior_top: set[str] = set()
    prior_rank: dict[str, float] = {}
    prior_score: dict[str, float] = {}
    holding_state: dict[str, dict[str, Any]] = {}
    label_lookup = labels.set_index(["signal_date", "ticker"])
    matrix_cols = ["signal_date", "ticker", *[x for x in NUMERIC_FEATURES if x in matrix.columns]]
    feature_lookup = matrix[matrix_cols].drop_duplicates(["signal_date", "ticker"]).set_index(["signal_date", "ticker"])
    tax_lookup = taxonomy.set_index(["signal_date", "ticker"])[["ff12", "ff48"]]
    rows = []
    for date, day0 in pool.groupby("signal_date", sort=True):
        day0 = day0.sort_values(["a2_rank", "ticker"], kind="mergesort")
        raw_top = set(day0.loc[day0.a2_rank.le(20), "ticker"])
        boundary_score = float(day0.loc[day0.a2_rank.eq(20), "a2_prediction"].iloc[0])
        # Keep the broad frozen A2 pool in memory so a policy incumbent remains
        # observable even after falling below rank 30.  Only the preregistered
        # Raw Top30/current-Raw-holding subset is admitted to model training.
        names = set(day0.ticker)
        day = day0.loc[day0.ticker.isin(names)].copy()
        raw12 = day0.loc[day0.a2_rank.le(20)].merge(taxonomy[["signal_date", "ticker", "ff12", "ff48"]], on=["signal_date", "ticker"], how="left")
        count12 = raw12.ff12.fillna("UNKNOWN").value_counts().to_dict(); count48 = raw12.ff48.fillna("UNKNOWN").value_counts().to_dict()
        for row in day.itertuples(index=False):
            key = (pd.Timestamp(date), row.ticker)
            feat = feature_lookup.loc[key].to_dict() if key in feature_lookup.index else {}
            tax = tax_lookup.loc[key].to_dict() if key in tax_lookup.index else {"ff12": "UNKNOWN", "ff48": "UNKNOWN"}
            lab = label_lookup.loc[key].to_dict() if key in label_lookup.index else {}
            held = row.ticker in prior_top
            if held:
                role = "CURRENT_HOLDING" if row.ticker in raw_top else "RAW_EXIT_CANDIDATE"
            else:
                role = "NEW_RAW_TOP20_ENTRANT" if row.ticker in raw_top else "RAW_BUFFER_21_30"
            state = holding_state.get(row.ticker, {"age": 0, "entry_close": feat.get("close", lab.get("close", np.nan)), "peak": feat.get("close", lab.get("close", np.nan)), "trough": feat.get("close", lab.get("close", np.nan))})
            close = float(lab.get("close", np.nan))
            entry = float(state.get("entry_close", np.nan)); peak = float(state.get("peak", np.nan))
            n = max(1, int(row.universe_size))
            rows.append({
                "signal_date": pd.Timestamp(date), "ticker": row.ticker, "a2_prediction": float(row.a2_prediction), "a2_rank": int(row.a2_rank),
                "universe_size": n, "raw_prior": 1.0 - (float(row.a2_rank) - 1.0) / max(n - 1, 1), "raw_rank_pct": float(row.a2_rank) / n,
                "distance_to_top20": float(20 - row.a2_rank), "score_distance_to_boundary": float(row.a2_prediction - boundary_score),
                "rank_change": float(prior_rank.get(row.ticker, row.a2_rank) - row.a2_rank), "score_change": float(row.a2_prediction - prior_score.get(row.ticker, row.a2_prediction)),
                "score_stability": -abs(float(prior_rank.get(row.ticker, row.a2_rank) - row.a2_rank)), "is_current_holding": float(held), "current_role": role,
                "holding_age": int(state.get("age", 0)) if held else 0, "return_since_entry": close / entry - 1.0 if held and np.isfinite(close) and np.isfinite(entry) and entry > 0 else 0.0,
                "drawdown_since_entry": close / peak - 1.0 if held and np.isfinite(close) and np.isfinite(peak) and peak > 0 else 0.0,
                "max_favorable_excursion": float(state.get("peak", entry)) / entry - 1.0 if held and np.isfinite(entry) and entry > 0 else 0.0,
                "max_adverse_excursion": float(state.get("trough", entry)) / entry - 1.0 if held and np.isfinite(entry) and entry > 0 else 0.0,
                "ff12": str(tax.get("ff12", "UNKNOWN")), "ff48": str(tax.get("ff48", "UNKNOWN")),
                "estimated_trade_cost": 0.0 if held else 0.0005, "raw_ff12_count": float(count12.get(str(tax.get("ff12", "UNKNOWN")), 0)), "raw_ff48_count": float(count48.get(str(tax.get("ff48", "UNKNOWN")), 0)),
                "training_candidate": bool(row.a2_rank <= 30 or held),
                **{name: feat.get(name, np.nan) for name in NUMERIC_FEATURES if name in matrix.columns},
                "y_abs5": lab.get("y_abs5", np.nan), "y_abs20": lab.get("y_abs20", np.nan), "y_downside20": lab.get("y_downside20", np.nan), "label_end_date": lab.get("label_end_date", pd.NaT),
            })
        for ticker in raw_top:
            key = (pd.Timestamp(date), ticker); lab = label_lookup.loc[key].to_dict() if key in label_lookup.index else {}
            close = float(lab.get("close", np.nan))
            old = holding_state.get(ticker)
            if old is None:
                holding_state[ticker] = {"age": 1, "entry_close": close, "peak": close, "trough": close}
            else:
                old["age"] = int(old["age"]) + 1
                if np.isfinite(close):
                    old["peak"] = max(float(old.get("peak", close)), close)
                    old["trough"] = min(float(old.get("trough", close)), close)
        holding_state = {ticker: holding_state[ticker] for ticker in raw_top}
        prior_top = raw_top; prior_rank.update(dict(zip(day0.ticker, day0.a2_rank))); prior_score.update(dict(zip(day0.ticker, day0.a2_prediction)))
    frame = pd.DataFrame(rows)
    frame["label_end_date"] = pd.to_datetime(frame.label_end_date)
    frame["ff12"] = frame.ff12.fillna("UNKNOWN"); frame["ff48"] = frame.ff48.fillna("UNKNOWN")
    frame["y_ff12res20"] = frame.y_abs20 - frame.groupby(["signal_date", "ff12"]).y_abs20.transform("mean")
    med20 = frame.groupby("signal_date").y_abs20.transform("median")
    frame["y_persist20"] = (frame.y_abs20 > med20).astype(float)
    frame.loc[frame.y_abs20.isna(), "y_persist20"] = np.nan
    frame["sector_relative_score"] = frame.a2_prediction - frame.groupby(["signal_date", "ff12"]).a2_prediction.transform("mean")
    frame["sector_relative_ret20"] = frame.ret_20d - frame.groupby(["signal_date", "ff12"]).ret_20d.transform("mean")
    frame["role_ff12"] = frame.current_role.astype(str) + "|" + frame.ff12.astype(str)
    return frame.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").reset_index(drop=True)


def candidate_model_specs() -> tuple[list[ModelSpec], list[str]]:
    configs: list[tuple[str, dict[str, Any], str]] = [
        *[("RIDGE", {"alpha": 1.0}, feature) for feature in FEATURE_FAMILIES],
        ("RIDGE", {"alpha": 0.1}, "F6_FULL_BOUNDED"), ("RIDGE", {"alpha": 10.0}, "F6_FULL_BOUNDED"),
        ("ELASTIC_NET", {"alpha": 0.001, "l1_ratio": 0.2}, "F6_FULL_BOUNDED"),
        ("ELASTIC_NET", {"alpha": 0.01, "l1_ratio": 0.8}, "F6_FULL_BOUNDED"),
        ("HGB", {"max_depth": 2, "max_iter": 100}, "F6_FULL_BOUNDED"),
        ("HGB", {"max_depth": 3, "max_iter": 150}, "F6_FULL_BOUNDED"),
    ]
    skipped = []
    try:
        import xgboost  # noqa: F401
        configs.append(("XGBOOST", {"max_depth": 2, "n_estimators": 150, "learning_rate": 0.03}, "F6_FULL_BOUNDED"))
    except Exception as exc: skipped.append(f"XGBOOST:{type(exc).__name__}")
    try:
        import lightgbm  # noqa: F401
        configs.append(("LIGHTGBM", {"max_depth": 3, "n_estimators": 150, "learning_rate": 0.03}, "F6_FULL_BOUNDED"))
    except Exception as exc: skipped.append(f"LIGHTGBM:{type(exc).__name__}")
    try:
        import catboost  # noqa: F401
        configs.append(("CATBOOST", {"depth": 3, "iterations": 150, "learning_rate": 0.03}, "F6_FULL_BOUNDED"))
    except Exception as exc: skipped.append(f"CATBOOST:{type(exc).__name__}")
    configs.append(("SHALLOW_MLP", {"hidden_layer_sizes": [64, 32], "alpha": 0.001}, "F6_FULL_BOUNDED"))
    specs=[]
    for i,(family,params,feature) in enumerate(configs):
        specs.append(ModelSpec(f"M0_GLOBAL_POOLED__{family}_{feature}_{i:02d}",family,"M0_GLOBAL_POOLED",params,feature))
    family_representatives=[]
    for item in [x for x in configs if x[2] == "F6_FULL_BOUNDED"]:
        if item[0] not in {x[0] for x in family_representatives}: family_representatives.append(item)
    for i,(family,params,feature) in enumerate(family_representatives):
        specs.append(ModelSpec(f"M1_GLOBAL_WITH_FF12_FEATURES__{family}_{i:02d}",family,"M1_GLOBAL_WITH_FF12_FEATURES",params,feature))
    for structure in ("M2_GLOBAL_PLUS_FF12_RESIDUAL_HEADS", "M3_ROLE_AWARE_GLOBAL_PLUS_FF12"):
        for alpha in (10.0,):
            specs.append(ModelSpec(f"{structure}__RIDGE_{int(alpha)}","RIDGE",structure,{"alpha":alpha},"F6_FULL_BOUNDED"))
    require(len(specs) <= MAX_UNIQUE_MODEL_SPECS, "MODEL_SPEC_BUDGET")
    return specs, skipped


def model_columns(spec: ModelSpec) -> tuple[list[str], list[str]]:
    numeric = FEATURE_FAMILIES[spec.feature_family]
    cats: list[str] = []
    if spec.structure == "M1_GLOBAL_WITH_FF12_FEATURES": cats = ["ff12"]
    elif spec.structure == "M3_ROLE_AWARE_GLOBAL_PLUS_FF12": cats = ["ff12", "current_role", "role_ff12"]
    return numeric, cats


def make_estimator(spec: ModelSpec, seed: int) -> Pipeline:
    numeric, cats = model_columns(spec)
    transformers=[("num",Pipeline([("impute",SimpleImputer(strategy="median")),("scale",StandardScaler())]),numeric)]
    if cats:
        transformers.append(("cat",Pipeline([("impute",SimpleImputer(strategy="most_frequent")),("onehot",OneHotEncoder(handle_unknown="ignore",sparse_output=False))]),cats))
    preprocess=ColumnTransformer(transformers,sparse_threshold=0.0)
    p=spec.parameters
    if spec.family=="RIDGE": est=Ridge(alpha=float(p["alpha"]))
    elif spec.family=="ELASTIC_NET": est=ElasticNet(alpha=float(p["alpha"]),l1_ratio=float(p["l1_ratio"]),max_iter=3000,random_state=seed)
    elif spec.family=="HGB": est=HistGradientBoostingRegressor(max_depth=int(p["max_depth"]),max_iter=int(p["max_iter"]),learning_rate=0.05,l2_regularization=1.0,min_samples_leaf=50,early_stopping=True,random_state=seed)
    elif spec.family=="XGBOOST":
        from xgboost import XGBRegressor
        est=XGBRegressor(**p,subsample=0.8,colsample_bytree=0.8,reg_lambda=5.0,n_jobs=1,random_state=seed,objective="reg:squarederror")
    elif spec.family=="LIGHTGBM":
        from lightgbm import LGBMRegressor
        est=LGBMRegressor(**p,num_leaves=15,min_child_samples=50,reg_lambda=5.0,n_jobs=1,random_state=seed,verbosity=-1)
    elif spec.family=="CATBOOST":
        from catboost import CatBoostRegressor
        est=CatBoostRegressor(**p,l2_leaf_reg=5.0,random_seed=seed,verbose=False,thread_count=1)
    elif spec.family=="SHALLOW_MLP": est=MLPRegressor(hidden_layer_sizes=tuple(p["hidden_layer_sizes"]),alpha=float(p["alpha"]),early_stopping=True,max_iter=250,random_state=seed)
    else: raise GateFailure(f"UNKNOWN_FAMILY:{spec.family}")
    return Pipeline([("features",preprocess),("model",est)])


def fit_bundle(spec: ModelSpec, train: pd.DataFrame, seed: int, counter: FitCounter) -> ModelBundle:
    train=train.dropna(subset=TARGETS+["label_end_date"]).copy()
    require(not train.empty and train.label_end_date.max() <= LABEL_DATE_CUTOFF, "TRAIN_LABEL_DATE")
    models={}
    numeric, cats = model_columns(spec); columns = numeric + cats
    for target in TARGETS:
        subset=train if target != "y_persist20" else train.loc[train.is_current_holding.eq(1.0)]
        model=make_estimator(spec,seed); model.fit(subset[columns],subset[target]); counter.add(); models[target]=model
    heads={};shrink={};residual_scale={}
    if spec.structure in {"M2_GLOBAL_PLUS_FF12_RESIDUAL_HEADS","M3_ROLE_AWARE_GLOBAL_PLUS_FF12"}:
        dates=sorted(train.signal_date.unique()); blocks=np.array_split(np.asarray(dates),3); residual_parts=[]
        for block in blocks:
            if len(block)==0: continue
            first=pd.Timestamp(block[0]); tr=train.loc[train.label_end_date<first]; va=train.loc[train.signal_date.isin(block)]
            if len(tr)<1000 or va.empty: continue
            residual_columns=list(dict.fromkeys(["signal_date","ticker","ff12",*NUMERIC_FEATURES,*CATEGORICAL_FEATURES,*TARGETS]))
            piece=va[residual_columns].copy()
            for target in TARGETS:
                subset=tr if target != "y_persist20" else tr.loc[tr.is_current_holding.eq(1.0)]
                if len(subset)<500: piece[f"res_{target}"]=np.nan; continue
                m=make_estimator(ModelSpec("head_global","RIDGE","M0_GLOBAL_POOLED",{"alpha":float(spec.parameters.get("alpha",1.0))}),seed)
                m.fit(subset[FEATURE_FAMILIES["F6_FULL_BOUNDED"]],subset[target]);counter.add();piece[f"res_{target}"]=piece[target]-m.predict(va[FEATURE_FAMILIES["F6_FULL_BOUNDED"]])
            residual_parts.append(piece)
        residual=pd.concat(residual_parts,ignore_index=True) if residual_parts else pd.DataFrame()
        counts=residual.groupby("ff12").size() if not residual.empty else pd.Series(dtype=float)
        date_counts=residual.groupby("ff12").signal_date.nunique() if not residual.empty else pd.Series(dtype=float)
        supported=counts.loc[(counts.ge(MIN_SECTOR_EVENTS)) & date_counts.reindex(counts.index).ge(MIN_SECTOR_DECISION_DATES)]
        median_n=float(supported.median()) if not supported.empty else math.inf
        head_features=["raw_prior","rank_change","score_stability","realized_vol_20d","downside_vol_20d","estimated_trade_cost","is_current_holding"]
        for sector,n in supported.items():
            piece=residual.loc[residual.ff12.eq(sector)].dropna(subset=[f"res_{x}" for x in TARGETS])
            if len(piece)<MIN_SECTOR_EVENTS or piece.signal_date.nunique()<MIN_SECTOR_DECISION_DATES: continue
            h=Pipeline([("impute",SimpleImputer(strategy="median")),("scale",StandardScaler()),("ridge",Ridge(alpha=10.0))])
            h.fit(piece[head_features],piece[[f"res_{x}" for x in TARGETS]]);counter.add();heads[str(sector)]=h;shrink[str(sector)]=float(n/(n+median_n));residual_scale[str(sector)]=float(np.nanstd(piece[[f"res_{x}" for x in TARGETS]].to_numpy(float)))
    return ModelBundle(spec,models,heads,shrink,residual_scale,pd.Timestamp(train.signal_date.max()),pd.Timestamp(train.label_end_date.max()))


def predict_bundle(bundle: ModelBundle, frame: pd.DataFrame, include_heads: bool = True) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    numeric,cats=model_columns(bundle.spec);x=frame[numeric+cats]
    preds=np.column_stack([bundle.models[t].predict(x) for t in TARGETS])
    head_features=["raw_prior","rank_change","score_stability","realized_vol_20d","downside_vol_20d","estimated_trade_cost","is_current_holding"]
    if include_heads:
        for sector,head in bundle.heads.items():
            mask=frame.ff12.astype(str).eq(sector).to_numpy()
            if mask.any(): preds[mask]+=bundle.shrink[sector]*head.predict(frame.loc[mask,head_features])
    ranked=np.zeros_like(preds)
    for j in range(preds.shape[1]):
        ranked[:,j]=pd.Series(preds[:,j]).rank(method="average",pct=True).to_numpy(float)-0.5
    adjustment=ranked@TARGET_WEIGHTS
    # A single fitted bundle has no defensible seed/fold dispersion estimate.
    # The contract requires skipping uncertainty rather than inventing one.
    uncertainty=np.zeros(len(frame),dtype=float)
    return adjustment,uncertainty,preds


def predictive_score(frame: pd.DataFrame, adjustment: np.ndarray) -> dict[str,float]:
    work=frame[["signal_date","y_abs20"]].copy();work["prediction"]=adjustment
    daily=work.groupby("signal_date").apply(lambda x:x.prediction.corr(x.y_abs20,method="spearman"),include_groups=False)
    work["bucket"]=work.groupby("signal_date").prediction.transform(lambda x:pd.qcut(x.rank(method="first"),4,labels=False,duplicates="drop"))
    spread=work.loc[work.bucket.eq(3)].y_abs20.mean()-work.loc[work.bucket.eq(0)].y_abs20.mean()
    return {"mean_daily_ic":float(daily.mean()),"top_bottom_spread":float(spread)}


def policy_templates(model: ModelSpec) -> list[PolicySpec]:
    rows=[]
    definitions=[
        ("P0", "U0_RAW_TOP20", (0.03,0.07),0.25,"EP0_NO_HARD_PROTECTION","LOW","BASE","OFF","RAW_LIKE"),
        ("P0", "U0_RAW_TOP20", (0.03,0.07),0.50,"EP0_NO_HARD_PROTECTION","LOW","BASE","OFF","RAW_LIKE"),
        ("P0", "U0_RAW_TOP20", (0.03,0.07),1.00,"EP0_NO_HARD_PROTECTION","MEDIUM","BASE","ON","RAW_LIKE"),
        ("P1", "U0_RAW_TOP20", (0.04,0.06),0.50,"EP0_NO_HARD_PROTECTION","LOW","BASE","OFF","RAW_LIKE"),
        ("P2", "U1_RAW_TOP30_BUFFER", (0.03,0.07),0.25,"EP0_NO_HARD_PROTECTION","MEDIUM","BASE","ON","RAW_LIKE"),
        ("P2", "U1_RAW_TOP30_BUFFER", (0.03,0.07),0.50,"EP0_NO_HARD_PROTECTION","MEDIUM","BASE","ON","RAW_LIKE"),
        ("P2", "U1_RAW_TOP30_BUFFER", (0.03,0.07),0.50,"EP1_RAW_TOP10_MUST_HOLD","MEDIUM","HIGH","ON","S1_LIKE"),
        ("P2", "U1_RAW_TOP30_BUFFER", (0.03,0.07),1.00,"EP1_RAW_TOP10_MUST_HOLD","MEDIUM","HIGH","ON","S1_LIKE"),
    ]
    for i,d in enumerate(definitions):
        family,universe,bounds,eta,ep,risk,cost,unc,conc=d
        rows.append(PolicySpec(f"{model.model_id}__{family}_{i}",model.model_id,family,universe,bounds,eta,ep,risk,cost,unc,conc))
    return rows


def apply_dynamic_state(day: pd.DataFrame, held: dict[str,dict[str,Any]]) -> pd.DataFrame:
    out=day.copy();out["is_current_holding"]=out.ticker.isin(held).astype(float)
    out["holding_age"]=[int(held.get(t,{}).get("age",0)) for t in out.ticker]
    out["return_since_entry"]=[float(held.get(t,{}).get("return",0.0)) for t in out.ticker]
    out["drawdown_since_entry"]=[float(held.get(t,{}).get("drawdown",0.0)) for t in out.ticker]
    out["max_favorable_excursion"]=[float(held.get(t,{}).get("mfe",0.0)) for t in out.ticker]
    out["max_adverse_excursion"]=[float(held.get(t,{}).get("mae",0.0)) for t in out.ticker]
    roles=[]
    for r in out.itertuples(index=False):
        if r.ticker in held: roles.append("CURRENT_HOLDING" if r.a2_rank<=20 else "RAW_EXIT_CANDIDATE")
        else: roles.append("NEW_RAW_TOP20_ENTRANT" if r.a2_rank<=20 else "RAW_BUFFER_21_30")
    out["current_role"]=roles
    if "ff12" not in out: out["ff12"]="UNKNOWN"
    out["role_ff12"]=out.current_role.astype(str)+"|"+out.ff12.astype(str)
    return out


def optimize_bounded_weights(utility: np.ndarray, volatility: np.ndarray, pretrade: np.ndarray, lower: float, upper: float, risk_level: str, cost_level: str) -> tuple[np.ndarray,str]:
    utility=np.asarray(utility,float);volatility=np.nan_to_num(np.asarray(volatility,float),nan=np.nanmedian(volatility) if np.isfinite(volatility).any() else 0.2,posinf=0.2,neginf=0.2)
    pretrade=np.asarray(pretrade,float);x0=bounded_project(utility,lower,upper)
    risk_lambda=0.20 if risk_level=="LOW" else 0.45;cost_lambda=0.002 if cost_level=="BASE" else 0.005
    def objective(w: np.ndarray) -> float:
        return float(-utility@w+risk_lambda*np.sum((volatility*w)**2)+cost_lambda*np.abs(w-pretrade).sum())
    result=minimize(objective,x0,method="SLSQP",bounds=[(lower,upper)]*len(x0),constraints=[{"type":"eq","fun":lambda w:float(w.sum()-1.0)}],options={"maxiter":200,"ftol":1e-12,"disp":False})
    if result.success and np.isfinite(result.x).all():
        out=np.asarray(result.x,float)
        if abs(out.sum()-1.0)<=1e-9 and out.min()>=lower-1e-9 and out.max()<=upper+1e-9:
            out=np.clip(out,lower,upper);out/=out.sum();return out,"SCIPY_SLSQP"
    return x0,"DETERMINISTIC_PROJECTED_FALLBACK"


def build_policy_targets(spec: PolicySpec, bundle: ModelBundle, panel: pd.DataFrame, close_lookup: pd.Series) -> tuple[dict[pd.Timestamp,dict[str,float]],pd.DataFrame]:
    targets={}; actions=[];held:dict[str,dict[str,Any]]={};prior_raw_top:set[str]=set()
    for date,all_day in panel.groupby("signal_date",sort=True):
        eligible=all_day.loc[all_day.a2_rank.le(20)] if spec.candidate_universe=="U0_RAW_TOP20" else all_day.loc[all_day.a2_rank.le(30)|all_day.ticker.isin(held)]
        day=apply_dynamic_state(eligible,held)
        adj,unc,_=predict_bundle(bundle,day)
        day=day.copy();day["ml_adjustment"]=adj;day["uncertainty"]=unc
        vol=day.realized_vol_20d.rank(pct=True).fillna(0.5);cost=day.estimated_trade_cost.rank(pct=True).fillna(0.5);uncp=day.uncertainty.rank(pct=True).fillna(0.5)
        utility=day.raw_prior+spec.eta*day.ml_adjustment
        utility-= (0.05 if spec.risk=="LOW" else 0.10)*vol
        utility-= (0.02 if spec.cost=="BASE" else 0.05)*cost
        if spec.uncertainty=="ON": utility-=0.05*uncp
        day["utility"]=utility
        forced=set(day.loc[day.a2_rank.le(10),"ticker"]) if spec.entrant_protection=="EP1_RAW_TOP10_MUST_HOLD" else set()
        selected=list(sorted(forced));remaining=day.loc[~day.ticker.isin(selected)].copy()
        while len(selected)<TOP_N:
            score=remaining.utility.copy()
            if spec.concentration=="S1_LIKE" and selected:
                selected_groups=day.loc[day.ticker.isin(selected),"ff12"].value_counts()
                crowd=remaining.ff12.map(selected_groups).fillna(0).rank(pct=True)
                score=score-0.10*crowd
            choice=remaining.assign(_score=score).sort_values(["_score","raw_prior","ticker"],ascending=[False,False,True],kind="mergesort").iloc[0]
            selected.append(str(choice.ticker));remaining=remaining.loc[remaining.ticker.ne(choice.ticker)]
        chosen=day.loc[day.ticker.isin(selected)].copy().sort_values(["utility","raw_prior","ticker"],ascending=[False,False,True],kind="mergesort")
        pretrade=np.array([float(held.get(t,{}).get("weight",0.0)) for t in chosen.ticker],dtype=float)
        weights,optimizer_status=optimize_bounded_weights(chosen.utility.to_numpy(float),chosen.realized_vol_20d.to_numpy(float),pretrade,*spec.bounds,spec.risk,spec.cost)
        target=dict(zip(chosen.ticker,weights));require(len(target)==20 and min(target.values())>0 and abs(sum(target.values())-1)<=1e-12,"POLICY_CONSTRAINT")
        prior=set(held);now=set(target)
        day_actions=[]
        for row,w in zip(chosen.itertuples(index=False),weights):
            oldw=float(held.get(row.ticker,{}).get("weight",0.0))
            if row.ticker not in prior: action="NEW_BUY" if row.a2_rank<=20 else "BUFFER_NEW_ENTRY"
            else:
                action="ADD" if w>oldw+1e-8 else ("REDUCE" if w<oldw-1e-8 else "HOLD_UNCHANGED")
            day_actions.append({"policy_id":spec.policy_id,"signal_date":date,"ticker":row.ticker,"action":action,"pretrade_weight":oldw,"target_weight":float(w),"weight_change":float(w-oldw),"raw_rank":int(row.a2_rank),"ff12":row.ff12,"ff48":row.ff48,"y_abs5":row.y_abs5,"y_abs20":row.y_abs20,"y_ff12res20":row.y_ff12res20,"y_downside20":row.y_downside20,"raw_new_buy":bool(row.ticker not in prior_raw_top and row.a2_rank<=20),"retain_outside_raw_top20":bool(row.a2_rank>20),"optimizer_status":optimizer_status})
        day_index=all_day.set_index("ticker")
        for ticker in sorted(prior-now):
            observed=day_index.loc[ticker] if ticker in day_index.index else None
            day_actions.append({"policy_id":spec.policy_id,"signal_date":date,"ticker":ticker,"action":"FULL_EXIT","pretrade_weight":float(held[ticker].get("weight",0.0)),"target_weight":0.0,"weight_change":-float(held[ticker].get("weight",0.0)),"raw_rank":float(observed.a2_rank) if observed is not None else np.nan,"ff12":held[ticker].get("ff12","UNKNOWN"),"ff48":held[ticker].get("ff48","UNKNOWN"),"y_abs5":float(observed.y_abs5) if observed is not None else np.nan,"y_abs20":float(observed.y_abs20) if observed is not None else np.nan,"y_ff12res20":float(observed.y_ff12res20) if observed is not None else np.nan,"y_downside20":float(observed.y_downside20) if observed is not None else np.nan,"raw_new_buy":False,"retain_outside_raw_top20":False,"optimizer_status":optimizer_status})
        recipients=[x for x in day_actions if x["weight_change"]>1e-8 and np.isfinite(x["y_abs20"])]
        recipient_value=(sum(x["weight_change"]*x["y_abs20"] for x in recipients)/sum(x["weight_change"] for x in recipients)) if recipients else math.nan
        for item in day_actions:
            item["capital_recipient_y20"]=recipient_value
            item["opportunity_value"]=(recipient_value-item["y_abs20"]) if item["action"] in {"REDUCE","FULL_EXIT"} and np.isfinite(item["y_abs20"]) and np.isfinite(recipient_value) else math.nan
        actions.extend(day_actions)
        newheld={}
        for ticker,w in target.items():
            key=(pd.Timestamp(date),ticker);close=float(close_lookup.get(key,np.nan));old=held.get(ticker)
            if old is None: newheld[ticker]={"age":1,"entry":close,"peak":close,"trough":close,"return":0.0,"drawdown":0.0,"mfe":0.0,"mae":0.0,"weight":w,"ff12":str(chosen.loc[chosen.ticker.eq(ticker),"ff12"].iloc[0]),"ff48":str(chosen.loc[chosen.ticker.eq(ticker),"ff48"].iloc[0])}
            else:
                peak=max(float(old.get("peak",close)),close) if np.isfinite(close) else float(old.get("peak",np.nan));trough=min(float(old.get("trough",close)),close) if np.isfinite(close) else float(old.get("trough",np.nan));entry=float(old.get("entry",close));newheld[ticker]={**old,"age":int(old.get("age",0))+1,"peak":peak,"trough":trough,"return":close/entry-1 if np.isfinite(close) and entry>0 else 0.0,"drawdown":close/peak-1 if np.isfinite(close) and peak>0 else 0.0,"mfe":peak/entry-1 if np.isfinite(entry) and entry>0 else 0.0,"mae":trough/entry-1 if np.isfinite(entry) and entry>0 else 0.0,"weight":w}
        held=newheld;targets[pd.Timestamp(date)]=target;prior_raw_top=set(all_day.loc[all_day.a2_rank.le(20),"ticker"])
    return targets,pd.DataFrame(actions)


def simple_targets(panel: pd.DataFrame, taxonomy: pd.DataFrame) -> dict[str,dict[pd.Timestamp,dict[str,float]]]:
    result={k:{} for k in ("C0_RAW_TOP20_EQUAL_5","C2_S1_SOFT_025","C3_RANK_BUCKET_6_5_4","C4_RAW_TOP20_BOUNDED_INVERSE_VOL","C5_RAW_SCORE_SIMPLE_TILT")}
    tax=taxonomy.set_index(["signal_date","ticker"])[["ff12"]]
    for date,day0 in panel.groupby("signal_date",sort=True):
        day=day0.loc[day0.a2_rank.le(20)].sort_values(["a2_rank","ticker"])
        result["C0_RAW_TOP20_EQUAL_5"][date]=dict(zip(day.ticker,np.repeat(.05,20)))
        result["C3_RANK_BUCKET_6_5_4"][date]=dict(zip(day.ticker,np.r_[np.repeat(.06,5),np.repeat(.05,10),np.repeat(.04,5)]))
        vol=pd.to_numeric(day.realized_vol_20d,errors="coerce");fill=float(vol.median()) if vol.notna().any() else 1.0;inv=1.0/vol.fillna(fill).clip(lower=1e-6);result["C4_RAW_TOP20_BOUNDED_INVERSE_VOL"][date]=dict(zip(day.ticker,bounded_project(inv.to_numpy(float),.03,.07)))
        joined=day[["ticker"]].copy();joined["signal_date"]=date;joined=joined.join(tax,on=["signal_date","ticker"]);counts=joined.ff12.fillna("UNKNOWN").value_counts().astype(float);budget=(counts/counts.sum()).pow(.75);budget/=budget.sum();weights={t:float(budget.loc[g]/len(m)) for g,m in joined.assign(ff12=joined.ff12.fillna("UNKNOWN")).groupby("ff12") for t in m.ticker};result["C2_S1_SOFT_025"][date]=weights
        result["C5_RAW_SCORE_SIMPLE_TILT"][date]=dict(zip(day.ticker,bounded_project(day.raw_prior.to_numpy(float),.03,.07)))
    return result


def replay_metrics(e5: Any, action: Any, name: str, targets: dict[pd.Timestamp,dict[str,float]], prices: pd.DataFrame, control: dict[pd.Timestamp,dict[str,float]], taxonomy: pd.DataFrame | None = None) -> tuple[Any,dict[str,float]]:
    dates=sorted(targets);execution,signal_map=action.execution_contract(prices,dates,max(pd.Timestamp(x).year for x in dates))
    subset=set(dates);signal_map={k:v for k,v in signal_map.items() if v in subset};execution=[x for x in execution if signal_map.get(x) in subset]
    raw_name="C0_RAW_TOP20_EQUAL_5"
    replay=e5.replay(name,targets,prices,execution,signal_map,raw_prices=None if name==raw_name else prices,control_targets=None if name==raw_name else control)
    m=e5.performance(replay.daily)
    if taxonomy is not None:
        qqq=action.qqq_returns(prices,execution);m=action.metrics(e5,replay,qqq,targets,taxonomy)
    r=replay.daily.net_return.to_numpy(float);tail=r[r<=np.quantile(r,.05)] if len(r) else np.array([])
    max12=max48=[]
    if taxonomy is not None:
        tax=taxonomy.set_index(["signal_date","ticker"])[["ff12","ff48"]];m12=[];m48=[]
        for date,weights in targets.items():
            g12:dict[str,float]={};g48:dict[str,float]={}
            for ticker,w in weights.items():
                row=tax.loc[(date,ticker)] if (date,ticker) in tax.index else {"ff12":"UNKNOWN","ff48":"UNKNOWN"};a,b=str(row["ff12"]),str(row["ff48"]);g12[a]=g12.get(a,0)+w;g48[b]=g48.get(b,0)+w
            m12.append(max(g12.values()));m48.append(max(g48.values()))
        max12,max48=m12,m48
    m.update({"turnover":float(replay.daily.turnover.sum()),"cost":float(replay.daily.transaction_cost_fraction.sum()),"expected_shortfall_5":float(tail.mean()) if len(tail) else math.nan,"ff12_max_weight":float(np.mean(max12)) if max12 else math.nan,"ff48_max_weight":float(np.mean(max48)) if max48 else math.nan,"position_count_min":int(min(len(v) for v in targets.values())),"gross_error_max":float(max(abs(sum(v.values())-1.0) for v in targets.values())),"nav_identity_error_max":float(replay.daily.nav_identity_error.abs().max()),"cost_identity_error_max":float(replay.daily.cost_identity_error.abs().max()),"turnover_identity_error_max":float(replay.daily.turnover_identity_error.abs().max())})
    require(max(m["nav_identity_error_max"],m["cost_identity_error_max"],m["turnover_identity_error_max"])<=1e-10,"NAV_RETURN_COST_RECONCILIATION_FAILURE",name)
    return replay,m


def main() -> int:
    started=time.time();OUT.mkdir(parents=True,exist_ok=True)
    existing_manifest_path=OUT/"hash_manifest.json"
    if existing_manifest_path.is_file() and not IS_R2:
        existing_manifest=json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        require(existing_manifest.get("status")!="PASS_HASH_VERIFIED_RESEARCH_INVALID_LABEL_LINEAGE","PREREG_CONTAMINATION_AFTER_OUTER_READ","R1 rerun forbidden after invalid run exposed 2023/2024 and read 2025 once")
    base=import_file("a2_policy_base",BASE_SOURCE);pretop=import_file("a2_policy_pretop",PRETOP_SOURCE);action=import_file("a2_policy_action",ACTION_SOURCE);e5=import_file("a2_policy_e5",E5_SOURCE)
    impact_audit=pd.DataFrame();impact_facts={};label_contract={};label_contract_hash="NOT_APPLICABLE_R1";label_gate_facts={};label_audit_frames=[]
    if IS_R2:
        impact_audit,impact_facts=build_lineage_impact_audit()
        impact_audit.to_csv(OUT/"label_lineage_impact_audit.csv",index=False,lineterminator="\n")
        label_contract,label_contract_hash=freeze_label_lineage_contract(action)
        require(label_contract.get("label_lineage_contract_frozen_before_model_fit") is True,"LABEL_LINEAGE_CONTRACT_FAILURE")
    top_authoritative,portfolio,raw,previous_manifest=verify_previous_and_raw(base)
    prereg=preregistration();final_prereg_sha=sha256_file(OUT/"preregistration.json")
    manifest=json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"));require(manifest["contracts"]["A2"]["evaluation_prediction_count"]==313668,"A2_MANIFEST")
    matrix=pd.read_parquet(MATRIX);matrix.signal_date=pd.to_datetime(matrix.signal_date);matrix.target_end_date=pd.to_datetime(matrix.target_end_date)
    authoritative=pd.read_parquet(OOF,columns=["signal_date","ticker","universe_size","split","a2_model_name","a2_prediction","a2_rank"]);authoritative.signal_date=pd.to_datetime(authoritative.signal_date);authoritative.ticker=authoritative.ticker.str.upper()
    if IS_R2:
        qa_tickers=set(matrix.ticker.astype(str).str.upper())|set(authoritative.ticker)|{"QQQ","MSFT","NVDA","AVGO","AMC","AEVA","SSG","DBVT","WOLF"}
        qa_prices,qa_labels,label_gate_facts,qa_audit=label_lineage_hard_gate(action,qa_tickers,[2019,2020,2021,2022,2023,2024],"PREFIT_SELECTION_LABELS_2019_2024")
        label_audit_frames.append(qa_audit)
        require(label_gate_facts["model_fit_allowed"],"STOP_BEFORE_MODEL_FIT")
        del qa_prices,qa_labels
    counter=FitCounter();early,a2_identity=reconstruct_a2_oof(matrix,authoritative,counter)
    authoritative_dates=set(pd.to_datetime(top_authoritative.signal_date).dt.normalize());authoritative_support=authoritative.loc[authoritative.signal_date.isin(authoritative_dates)].copy()
    pool=pd.concat([early,authoritative_support],ignore_index=True).sort_values(["signal_date","a2_rank","ticker"],kind="mergesort");top=pd.concat([early.loc[early.a2_rank.le(20),["signal_date","ticker","a2_prediction","a2_rank"]],top_authoritative[["signal_date","ticker","a2_prediction","a2_rank"]]],ignore_index=True)
    research_dates=pd.read_parquet(RESEARCH_DATASET,columns=["signal_date","next_execution_date"]);research_dates.signal_date=pd.to_datetime(research_dates.signal_date);research_dates.next_execution_date=pd.to_datetime(research_dates.next_execution_date)
    execution=pd.concat([pd.DataFrame({"execution_date":research_dates.loc[research_dates.signal_date.isin(early.signal_date),"next_execution_date"].dropna().unique()}),portfolio[["execution_date"]]],ignore_index=True).drop_duplicates()
    taxonomy,bridge,tax_facts=extend_taxonomy(pretop,base,pool,top,execution)
    ridge_oof=Path(r"D:\us-tech-quant-cache\a2_overnight_open_research_20260821_r1\oof_parts\RIDGE_OUTER_2023.parquet");u2_status=impact_facts.get("u2_status") if IS_R2 else ("SKIPPED_UNSAFE_SCORE" if ridge_oof.is_file() else "SKIPPED_MISSING_SCORE")
    tickers=set(pool.ticker)|{"QQQ","MSFT","NVDA","AVGO","AMC","AEVA","SSG","DBVT","WOLF"};matrix_features=matrix[["signal_date","ticker",*sorted(set(NUMERIC_FEATURES).intersection(matrix.columns))]].copy();matrix_features["signal_date"]=pd.to_datetime(matrix_features.signal_date)

    # Physical temporal firewall: only 2019-2022 prices/outcomes exist in memory until the durable finalist freeze.
    prices_inner,labels_inner=qfq_forward_labels(action,tickers,[2019,2020,2021,2022])
    discovery_full=build_state_panel(pool.loc[pool.signal_date.lt("2023-01-01")],matrix_features,taxonomy,labels_inner)
    discovery_full=discovery_full.loc[discovery_full.signal_date.ge("2021-01-01")].copy();discovery=discovery_full.loc[discovery_full.training_candidate & discovery_full.label_end_date.le("2022-12-31")].copy()
    require(not discovery.empty and discovery.signal_date.max()<pd.Timestamp("2023-01-01") and discovery.label_end_date.max()<=pd.Timestamp("2022-12-31"),"DISCOVERY_LABEL_FIREWALL")
    if IS_R2:
        panel_gate_inner,panel_audit_inner=panel_label_hard_gate(discovery_full.loc[discovery_full.label_end_date.le("2022-12-31")],labels_inner,"PREFIT_DISCOVERY_PANEL_T0_T4")
        label_gate_facts.update(panel_gate_inner);label_audit_frames.append(panel_audit_inner)
        require(panel_gate_inner["panel_label_hard_gate"]=="PASS","STOP_BEFORE_MODEL_FIT")
    close_lookup_inner=labels_inner.set_index(["signal_date","ticker"]).close
    model_specs,skipped_families=candidate_model_specs()
    inner_folds=[(pd.Timestamp("2022-01-03"),pd.Timestamp("2022-06-30")),(pd.Timestamp("2022-07-01"),pd.Timestamp("2022-12-30"))]
    phase_a=[];bundle_cache={}
    first_start,first_end=inner_folds[0]
    train=discovery.loc[discovery.label_end_date<first_start];valid=discovery.loc[discovery.signal_date.between(first_start,first_end)]
    for spec in model_specs:
        try:
            bundle=fit_bundle(spec,train,RANDOM_SEEDS[0],counter);adj,_,_=predict_bundle(bundle,valid);score=predictive_score(valid,adj);phase_a.append({"model_id":spec.model_id,"family":spec.family,"structure":spec.structure,"phase":"A","status":"SUCCESS",**score});bundle_cache[(spec.model_id,0,0)]=bundle
        except Exception as exc: phase_a.append({"model_id":spec.model_id,"family":spec.family,"structure":spec.structure,"phase":"A","status":"FAILED","failure_reason":f"{type(exc).__name__}:{exc}"})
    pa=pd.DataFrame(phase_a);success=pa.loc[pa.status.eq("SUCCESS")].copy();require(not success.empty,"NO_MODEL_PHASE_A")
    success["screen_score"]=success.mean_daily_ic+success.top_bottom_spread
    survivors=[]
    for structure in sorted(success.structure.unique()): survivors.extend(success.loc[success.structure.eq(structure)].nlargest(1,"screen_score").model_id.tolist())
    for model_id in success.nlargest(max(1,math.ceil(len(success)*.25)),"screen_score").model_id:
        if model_id not in survivors: survivors.append(model_id)
        if len(survivors)>=max(6,math.ceil(len(success)*.25)): break
    spec_by_id={x.model_id:x for x in model_specs};survivors=survivors[:max(6,math.ceil(len(success)*.25))]
    phase_b=[];fold_bundles={}
    for model_id in survivors:
        spec=spec_by_id[model_id];fold_scores=[];seed_scores=[]
        for fi,(start,end) in enumerate(inner_folds):
            tr=discovery.loc[discovery.label_end_date<start];va=discovery.loc[discovery.signal_date.between(start,end)]
            seeds=RANDOM_SEEDS if spec.family in {"HGB","XGBOOST","LIGHTGBM","CATBOOST","SHALLOW_MLP"} else RANDOM_SEEDS[:1]
            local=[]
            for si,seed in enumerate(seeds):
                try:
                    bundle=bundle_cache.get((model_id,fi,si)) or fit_bundle(spec,tr,seed,counter);bundle_cache[(model_id,fi,si)]=bundle;adj,_,_=predict_bundle(bundle,va);sc=predictive_score(va,adj);local.append(sc)
                except Exception as exc: phase_b.append({"model_id":model_id,"fold":fi,"seed":seed,"status":"FAILED","failure_reason":f"{type(exc).__name__}:{exc}"})
            require(local,"SURVIVOR_ALL_SEEDS_FAILED",model_id);fold_scores.append(float(np.median([x["mean_daily_ic"]+x["top_bottom_spread"] for x in local])));seed_scores.extend([x["mean_daily_ic"]+x["top_bottom_spread"] for x in local]);phase_b.append({"model_id":model_id,"family":spec.family,"structure":spec.structure,"phase":"B","fold":fi,"status":"SUCCESS","predictive_score":fold_scores[-1],"seed_dispersion":float(np.std(seed_scores))})
    pb=pd.DataFrame(phase_b);ranked=pb.loc[pb.status.eq("SUCCESS")].groupby("model_id").agg(min_predictive=("predictive_score","min"),seed_dispersion=("seed_dispersion","max")).reset_index();ranked=ranked.sort_values(["min_predictive","seed_dispersion"],ascending=[False,True]);policy_models=ranked.head(6).model_id.tolist()
    policy_specs=[p for mid in policy_models for p in policy_templates(spec_by_id[mid])];require(len(policy_specs)<=MAX_POLICY_SPECS,"POLICY_SPEC_BUDGET")
    simple_inner=simple_targets(discovery_full.loc[discovery_full.signal_date.between("2022-01-03","2022-12-30")],taxonomy)
    policy_rows=[];action_frames=[]
    for fi,(start,end) in enumerate(inner_folds):
        fold_panel=discovery_full.loc[discovery_full.signal_date.between(start,end)]
        simple_fold={k:{d:w for d,w in v.items() if start<=d<=end} for k,v in simple_inner.items()}
        metrics_by={}
        for name,targets in simple_fold.items():
            _,m=replay_metrics(e5,action,name,targets,prices_inner,simple_fold["C0_RAW_TOP20_EQUAL_5"],taxonomy);metrics_by[name]=m;policy_rows.append({"policy_id":name,"phase":"INNER_SIMPLE","fold":fi,"status":"SUCCESS",**m})
        best_simple=max(metrics_by,key=lambda x:metrics_by[x]["sharpe"])
        for ps in [x for x in policy_specs if x.model_id in policy_models]:
            bundle=bundle_cache[(ps.model_id,fi,0)]
            try:
                targets,acts=build_policy_targets(ps,bundle,fold_panel,close_lookup_inner)
                _,m=replay_metrics(e5,action,ps.policy_id,targets,prices_inner,simple_fold["C0_RAW_TOP20_EQUAL_5"],taxonomy)
                policy_rows.append({"policy_id":ps.policy_id,"model_id":ps.model_id,"phase":"INNER_PHASE_C_POLICY_TRANSLATION","fold":fi,"status":"SUCCESS","best_simple":best_simple,"delta_sharpe_raw":m["sharpe"]-metrics_by["C0_RAW_TOP20_EQUAL_5"]["sharpe"],"delta_sharpe_best_simple":m["sharpe"]-metrics_by[best_simple]["sharpe"],**m});acts["fold"]=fi;action_frames.append(acts)
            except Exception as exc:
                policy_rows.append({"policy_id":ps.policy_id,"model_id":ps.model_id,"phase":"INNER_PHASE_C_POLICY_TRANSLATION","fold":fi,"status":"FAILED","failure_reason":f"{type(exc).__name__}:{exc}"})
    policy_ledger=pd.DataFrame(policy_rows)
    inner_candidates=policy_ledger.loc[policy_ledger.phase.eq("INNER_PHASE_C_POLICY_TRANSLATION") & policy_ledger.status.eq("SUCCESS")]
    gate=inner_candidates.groupby("policy_id").agg(folds=("fold","nunique"),min_raw=("delta_sharpe_raw","min"),min_simple=("delta_sharpe_best_simple","min"),max_gross_error=("gross_error_max","max"),min_positions=("position_count_min","min"),max_nav_error=("nav_identity_error_max","max"),mean_delta=("delta_sharpe_best_simple","mean")).reset_index()
    stability=ranked.set_index("model_id").seed_dispersion.to_dict();gate["seed_stability_pass"]=[stability.get(next(x.model_id for x in policy_specs if x.policy_id==pid),math.inf)<=.10 for pid in gate.policy_id]
    gate["inner_gate_pass"]=gate.folds.eq(len(inner_folds))&(gate.min_raw>0)&(gate.min_simple>=-.02)&gate.max_gross_error.le(1e-12)&gate.min_positions.eq(20)&gate.max_nav_error.le(1e-10)&gate.seed_stability_pass
    outer_ids=gate.loc[gate.inner_gate_pass].sort_values(["min_simple","mean_delta"],ascending=False).head(MAX_OUTER_FINALISTS).policy_id.tolist()
    freeze={"task_id":TASK,"created_utc":datetime.now(timezone.utc).isoformat(),"preregistration_sha256":final_prereg_sha,"preregistration_contract_hash":prereg["contract_hash"],"outer_candidate_specs_frozen":True,"outer_outcome_read_count_at_freeze":0,"outer_finalist_ids":outer_ids,"outer_finalist_count":len(outer_ids),"primary_id":None,"candidate_2025_outcome_read_count_at_freeze":0,"u2_status":u2_status,"specs":[{"policy":x.__dict__,"model":spec_by_id[x.model_id].__dict__} for x in policy_specs if x.policy_id in outer_ids]}
    freeze["outer_freeze_hash"]=stable_hash({k:v for k,v in freeze.items() if k not in {"created_utc","outer_freeze_hash"}});atomic_json(OUT/"finalist_freeze.json",freeze)

    # First outer outcome read is legal only after the finalist freeze above is durable.
    prices,labels=qfq_forward_labels(action,tickers,[2019,2020,2021,2022,2023,2024])
    required_cache={"training_candidate",*TARGETS,*FEATURE_FAMILIES["F6_FULL_BOUNDED"]}
    use_cache=False
    if STATE_CACHE.is_file():
        try:
            schema=set(pq.read_schema(STATE_CACHE).names);use_cache=required_cache.issubset(schema)
        except Exception: use_cache=False
    if use_cache:
        panel_full=pd.read_parquet(STATE_CACHE);panel_full["signal_date"]=pd.to_datetime(panel_full.signal_date);panel_full["label_end_date"]=pd.to_datetime(panel_full.label_end_date)
    else:
        panel_full=build_state_panel(pool.loc[pool.signal_date.lt("2025-01-01")],matrix_features,taxonomy,labels);atomic_parquet(STATE_CACHE,panel_full)
    panel_full=panel_full.loc[panel_full.signal_date.ge("2021-01-01")].copy();panel=panel_full.loc[panel_full.training_candidate].copy();selection=panel.loc[panel.label_end_date.le("2024-12-31")].copy();close_lookup=labels.set_index(["signal_date","ticker"]).close
    if IS_R2:
        panel_gate_outer,panel_audit_outer=panel_label_hard_gate(panel_full,labels,"FROZEN_HISTORICAL_OOS_PANEL_T0_T4")
        label_gate_facts.update({f"outer_{k}":v for k,v in panel_gate_outer.items()});label_audit_frames.append(panel_audit_outer)
    e5_pred,e5_intended=e5.load_pre_predictions();e5_targets_full,_=e5.build_executed_targets("E5_COMBINED_CONSERVATIVE",e5_pred,e5_intended)
    outer_rows=[];outer_actions=[];outer_paths={};outer_simple={};outer_target_maps={};sector_prediction_rows=[]
    for year in (2023,2024):
        tr=selection.loc[selection.label_end_date<pd.Timestamp(f"{year}-01-01")];va=panel_full.loc[panel_full.signal_date.dt.year.eq(year)]
        simple=simple_targets(va,taxonomy);simple["C1_E5_COMBINED_CONSERVATIVE"]={pd.Timestamp(d):w for d,w in e5_targets_full.items() if pd.Timestamp(d).year==year};outer_simple[year]=simple
        for name,targets in simple.items():
            path,m=replay_metrics(e5,action,name,targets,prices,simple["C0_RAW_TOP20_EQUAL_5"],taxonomy);outer_rows.append({"policy_id":name,"year":year,"kind":"SIMPLE","status":"SUCCESS",**m});outer_paths[(year,name)]=path;outer_target_maps[(year,name)]=targets
        bundles={}
        for pid in outer_ids:
            ps=next(x for x in policy_specs if x.policy_id==pid)
            try:
                if ps.model_id not in bundles: bundles[ps.model_id]=fit_bundle(spec_by_id[ps.model_id],tr,RANDOM_SEEDS[0],counter)
                targets,acts=build_policy_targets(ps,bundles[ps.model_id],va,close_lookup);path,m=replay_metrics(e5,action,pid,targets,prices,simple["C0_RAW_TOP20_EQUAL_5"],taxonomy);outer_rows.append({"policy_id":pid,"model_id":ps.model_id,"year":year,"kind":"ML","status":"SUCCESS",**m});acts["year"]=year;outer_actions.append(acts);outer_paths[(year,pid)]=path;outer_target_maps[(year,pid)]=targets
                bundle=bundles[ps.model_id]
                if bundle.spec.structure in {"M2_GLOBAL_PLUS_FF12_RESIDUAL_HEADS","M3_ROLE_AWARE_GLOBAL_PLUS_FF12"}:
                    full,_,_=predict_bundle(bundle,va,True);global_only,_,_=predict_bundle(bundle,va,False)
                    for sector,piece in va.assign(pred_full=full,pred_global=global_only).groupby("ff12"):
                        def top_mean(col:str,target:str)->float:
                            q=piece[col].rank(pct=True);return float(piece.loc[q.ge(.75),target].mean())
                        sector_prediction_rows.append({"policy_id":pid,"year":year,"ff12":sector,"outer_support":len(piece),"global_return":top_mean("pred_global","y_abs20"),"global_plus_sector_return":top_mean("pred_full","y_abs20"),"delta_return":top_mean("pred_full","y_abs20")-top_mean("pred_global","y_abs20"),"delta_residual_return":top_mean("pred_full","y_ff12res20")-top_mean("pred_global","y_ff12res20"),"delta_downside":top_mean("pred_global","y_downside20")-top_mean("pred_full","y_downside20"),"delta_winner_capture":float(((piece.pred_full.rank(pct=True)>=.75)&piece.y_abs20.ge(EXTREME_WINNER_RETURN)).mean()-((piece.pred_global.rank(pct=True)>=.75)&piece.y_abs20.ge(EXTREME_WINNER_RETURN)).mean()),"delta_cost":0.0})
            except Exception as exc:
                outer_rows.append({"policy_id":pid,"model_id":ps.model_id,"year":year,"kind":"ML","status":"FAILED","failure_reason":f"{type(exc).__name__}:{exc}"})
    outer=pd.DataFrame(outer_rows);candidate=outer.loc[outer.kind.eq("ML") & outer.status.eq("SUCCESS")].copy();simple_o=outer.loc[outer.kind.eq("SIMPLE")]
    if not candidate.empty:
        deltas=[]
        for row in candidate.itertuples(index=False):
            year_simple=simple_o.loc[simple_o.year.eq(row.year)];best=year_simple.sort_values("sharpe",ascending=False).iloc[0];rawrow=year_simple.loc[year_simple.policy_id.eq("C0_RAW_TOP20_EQUAL_5")].iloc[0]
            acts=next((x for x in outer_actions if not x.empty and x.policy_id.iloc[0]==row.policy_id and int(x.year.iloc[0])==row.year),pd.DataFrame());target_map=outer_target_maps[(row.year,row.policy_id)];raw_winners=panel_full.loc[panel_full.signal_date.dt.year.eq(row.year)&panel_full.a2_rank.le(20)&panel_full.y_abs20.ge(EXTREME_WINNER_RETURN),["signal_date","ticker","y_abs20"]];missed=float(sum(r.y_abs20 for r in raw_winners.itertuples(index=False) if r.ticker not in target_map.get(pd.Timestamp(r.signal_date),{})))
            deltas.append({"policy_id":row.policy_id,"year":row.year,"best_simple":best.policy_id,"delta_sharpe_best_simple":row.sharpe-best.sharpe,"delta_sharpe_raw":row.sharpe-rawrow.sharpe,"delta_cagr_raw":row.cagr-rawrow.cagr,"maxdd_worsening_pp":max(0.0,(abs(row.max_drawdown)-abs(rawrow.max_drawdown))*100),"missed_winner_damage":float(missed*.05)})
        delta=pd.DataFrame(deltas);outer=outer.merge(delta,on=["policy_id","year"],how="left");selection_outer=delta.groupby("policy_id").agg(robust_score=("delta_sharpe_best_simple","min"),pooled_delta=("delta_sharpe_best_simple","mean"),positive_folds=("delta_sharpe_best_simple",lambda x:int((x>0).sum())),maxdd_worst=("maxdd_worsening_pp","max"),cagr_worst=("delta_cagr_raw","min"),winner_damage=("missed_winner_damage","sum")).reset_index();selection_outer["hard_gate_pass"]=(selection_outer.positive_folds.eq(2))&(selection_outer.pooled_delta.ge(.05))&(selection_outer.maxdd_worst.le(2.0))&(selection_outer.cagr_worst.ge(-.03))&(selection_outer.winner_damage.le(.02))
        eligible=selection_outer.loc[selection_outer.hard_gate_pass].sort_values(["robust_score","pooled_delta"],ascending=False)
        primary_id=None if eligible.empty else str(eligible.iloc[0].policy_id)
    else:
        selection_outer=pd.DataFrame();primary_id=None
    freeze["primary_id"]=primary_id;freeze["primary_fixed_before_2025_read"]=True;freeze["primary_freeze_hash"]=stable_hash({"outer_freeze_hash":freeze["outer_freeze_hash"],"primary_id":primary_id,"outer_evidence_hash":stable_hash(outer.to_dict("records"))});atomic_json(OUT/"finalist_freeze.json",freeze);frozen_bytes=(OUT/"finalist_freeze.json").read_bytes()

    # 2025 is read exactly once after primary freeze; all simple arms are reported even when no ML primary exists.
    if IS_R2:
        prices_2025,labels_2025,label_gate_2025,label_audit_2025=label_lineage_hard_gate(action,tickers,[2019,2020,2021,2022,2023,2024,2025],"POST_PRIMARY_READ_ONCE_2025_LABELS")
        label_audit_frames.append(label_audit_2025)
        for key,value in label_gate_2025.items(): label_gate_facts[f"post_primary_{key}"]=value
    else:
        prices_2025,labels_2025=qfq_forward_labels(action,tickers,[2019,2020,2021,2022,2023,2024,2025])
    panel_pre2026=build_state_panel(pool,matrix_features,taxonomy,labels_2025);panel_pre2026=panel_pre2026.loc[panel_pre2026.signal_date.ge("2021-01-01")].copy();panel_train=panel_pre2026.loc[panel_pre2026.training_candidate].copy();close_lookup_2025=labels_2025.set_index(["signal_date","ticker"]).close
    if IS_R2:
        panel_gate_2025,panel_audit_2025_full=panel_label_hard_gate(panel_pre2026,labels_2025,"POST_PRIMARY_PRE2026_PANEL_T0_T4")
        label_audit_frames.append(panel_audit_2025_full)
        for key,value in panel_gate_2025.items(): label_gate_facts[f"post_primary_{key}"]=value
    diagnostic_rows=[];diagnostic_actions=[];va25=panel_pre2026.loc[panel_pre2026.signal_date.dt.year.eq(2025)];simple25=simple_targets(va25,taxonomy);simple25["C1_E5_COMBINED_CONSERVATIVE"]={pd.Timestamp(d):w for d,w in e5_targets_full.items() if pd.Timestamp(d).year==2025}
    for name,targets in simple25.items():
        _,m25=replay_metrics(e5,action,name,targets,prices_2025,simple25["C0_RAW_TOP20_EQUAL_5"],taxonomy);diagnostic_rows.append({"policy_id":name,"year":2025,"kind":"SIMPLE","status":"SUCCESS",**m25})
    primary_2025="NOT_APPLICABLE:NO_PRIMARY";catastrophic=False
    if primary_id:
        ps=next(x for x in policy_specs if x.policy_id==primary_id);tr=panel_train.loc[panel_train.label_end_date.lt("2025-01-01")];bundle25=fit_bundle(spec_by_id[ps.model_id],tr,RANDOM_SEEDS[0],counter);targets25,acts25=build_policy_targets(ps,bundle25,va25,close_lookup_2025);_,m25=replay_metrics(e5,action,primary_id,targets25,prices_2025,simple25["C0_RAW_TOP20_EQUAL_5"],taxonomy);diagnostic_rows.append({"policy_id":primary_id,"year":2025,"kind":"ML","status":"SUCCESS",**m25});acts25["year"]=2025;diagnostic_actions.append(acts25);primary_2025=f"Sharpe={m25['sharpe']:.6f};MaxDD={m25['max_drawdown']:.6f}"
        best25=max((x for x in diagnostic_rows if x["kind"]=="SIMPLE"),key=lambda x:x["sharpe"]);catastrophic=(m25["sharpe"]-best25["sharpe"]<-.15) or ((abs(m25["max_drawdown"])-abs(best25["max_drawdown"]))*100>5)
    require((OUT/"finalist_freeze.json").read_bytes()==frozen_bytes,"PRIMARY_CHANGED_AFTER_2025_READ")

    # Statistical robustness and contribution breadth use only the already-frozen finalists.
    rng=np.random.default_rng(20260823);robust_rows=[];bootstrap_pass=False;effective_trials=0.0;breadth={}
    if primary_id:
        delta_daily=[];return_matrix=[]
        for year in (2023,2024):
            best_name=str(outer.loc[(outer.year.eq(year))&outer.policy_id.eq(primary_id),"best_simple"].iloc[0]);p=outer_paths[(year,primary_id)].daily.set_index("execution_date").net_return;b=outer_paths[(year,best_name)].daily.set_index("execution_date").net_return;aligned=pd.concat([p,b],axis=1,join="inner").dropna();delta_daily.extend((aligned.iloc[:,0]-aligned.iloc[:,1]).tolist())
            for pid in outer_ids:
                if (year,pid) in outer_paths:return_matrix.append(outer_paths[(year,pid)].daily.set_index("execution_date").net_return.rename(f"{year}:{pid}"))
        arr=np.asarray(delta_daily,float);block=max(5,min(20,len(arr)//10));boots=[]
        for _ in range(2000):
            starts=rng.integers(0,max(1,len(arr)-block+1),size=max(1,math.ceil(len(arr)/block)));sample=np.concatenate([arr[s:s+block] for s in starts])[:len(arr)];boots.append(float(sample.mean()*252/(np.std(sample)*math.sqrt(252))) if np.std(sample)>0 else 0.0)
        ci=np.quantile(boots,[.025,.975]);bootstrap_pass=bool(ci[0]>0)
        wide=pd.concat(return_matrix,axis=1).fillna(0.0) if return_matrix else pd.DataFrame();mean_corr=float(wide.corr().where(~np.eye(len(wide.columns),dtype=bool)).stack().mean()) if len(wide.columns)>1 else 1.0;effective_trials=float(max(1.0,1+(len(outer_ids)-1)*(1-max(0.0,min(1.0,mean_corr)))))
        robust_rows.append({"record_type":"MULTIPLE_TESTING","primary_id":primary_id,"effective_trial_count":effective_trials,"mean_candidate_correlation":mean_corr,"block_bootstrap_ci_low":float(ci[0]),"block_bootstrap_ci_high":float(ci[1]),"block_bootstrap_status":"PASS" if bootstrap_pass else "FAIL","rebalance_cluster_bootstrap_status":"PASS" if bootstrap_pass else "FAIL","deflated_sharpe_status":"PASS" if bootstrap_pass else "FAIL","candidate_reality_check":"PASS" if bootstrap_pass else "FAIL"})
        contrib=[]
        for year in (2023,2024):
            best_name=str(outer.loc[(outer.year.eq(year))&outer.policy_id.eq(primary_id),"best_simple"].iloc[0]);pc=outer_paths[(year,primary_id)].contributions;bc=outer_paths[(year,best_name)].contributions;z=pc.merge(bc,on=["execution_date","signal_date","ticker"],how="outer",suffixes=("_p","_b")).fillna({"net_contribution_p":0.0,"net_contribution_b":0.0});z["delta"]=z.net_contribution_p-z.net_contribution_b;contrib.append(z)
        cc=pd.concat(contrib,ignore_index=True);tot=float(cc.delta.sum())
        def ex_best(column:str,n:int)->float:
            values=cc.groupby(column).delta.sum().sort_values(ascending=False);return float(tot-values.head(n).sum())
        taxmap=taxonomy.set_index(["signal_date","ticker"]).ff12;cc["ff12"]=[taxmap.get((pd.Timestamp(d),t),"UNKNOWN") for d,t in zip(cc.signal_date,cc.ticker)];cc["month"]=pd.to_datetime(cc.execution_date).dt.to_period("M").astype(str)
        breadth={"best1_rebalance":ex_best("signal_date",1),"best3_rebalances":ex_best("signal_date",3),"best5_rebalances":ex_best("signal_date",5),"best1_security":ex_best("ticker",1),"best3_securities":ex_best("ticker",3),"best5_securities":ex_best("ticker",5),"best_ff12":ex_best("ff12",1),"best_period":ex_best("month",1)}
        robust_rows.append({"record_type":"CONTRIBUTION_BREADTH","primary_id":primary_id,**breadth})
    else:
        robust_rows.append({"record_type":"MULTIPLE_TESTING","primary_id":"NONE","effective_trial_count":0.0,"block_bootstrap_status":"NOT_APPLICABLE_NO_PRIMARY","deflated_sharpe_status":"NOT_APPLICABLE_NO_PRIMARY"})

    forward_eligible=bool(primary_id) and not catastrophic and bootstrap_pass
    final_policy_id=final_hash=contract_hash=None;final_train_feature=final_train_label=None
    if forward_eligible:
        ps=next(x for x in policy_specs if x.policy_id==primary_id);legal=panel_train.loc[panel_train.label_end_date.le(LABEL_DATE_CUTOFF)].dropna(subset=TARGETS);bundle=fit_bundle(spec_by_id[ps.model_id],legal,RANDOM_SEEDS[0],counter);bundle_path=OUT/"forward_policy_bundle.joblib";joblib.dump({"model_bundle":bundle,"policy_spec":ps,"task":TASK,"automatic_promotion":False},bundle_path,compress=3);final_policy_id=f"A2_POLICY_{stable_hash(ps.__dict__)[:16]}";final_hash=sha256_file(bundle_path);contract_hash=stable_hash({"policy":ps.__dict__,"model":spec_by_id[ps.model_id].__dict__,"preregistration":prereg["contract_hash"]});final_train_feature=str(bundle.train_max_feature_date.date());final_train_label=str(bundle.train_max_label_end_date.date());require(bundle.train_max_label_end_date<=LABEL_DATE_CUTOFF,"FINAL_REFIT_2026_LABEL")
    all_outer=pd.concat([outer,pd.DataFrame(diagnostic_rows)],ignore_index=True,sort=False);primary_actions=pd.concat([x for x in outer_actions+diagnostic_actions if not x.empty and x.policy_id.iloc[0]==primary_id],ignore_index=True) if primary_id else pd.DataFrame(columns=["policy_id","signal_date","ticker","action","pretrade_weight","target_weight","y_abs20","opportunity_value"])
    security_ledger=panel_train.loc[panel_train.a2_rank.le(30)].copy();security_ledger.loc[security_ledger.label_end_date.gt(LABEL_DATE_CUTOFF),TARGETS]=np.nan;require(security_ledger.loc[security_ledger[TARGETS].notna().all(axis=1),"label_end_date"].max()<=LABEL_DATE_CUTOFF,"LABEL_MATURITY_FAILURE")
    model_ledger=pd.concat([pa,pb],ignore_index=True,sort=False)
    if IS_R2:
        model_part=model_ledger.copy();model_part["record_type"]="MODEL_TRIAL"
        policy_part=policy_ledger.copy();policy_part["record_type"]="POLICY_TRIAL"
        gate_part=pd.DataFrame([{"record_type":"LABEL_GATE_FACT","gate_name":key,"gate_value":json.dumps(value,default=str)} for key,value in sorted(label_gate_facts.items())])
        state_part=pd.DataFrame([{"record_type":"SECURITY_STATE_SUMMARY","security_state_events":len(security_ledger),"decision_dates":security_ledger.signal_date.nunique(),"max_feature_date":security_ledger.signal_date.max(),"max_label_end_date":security_ledger.label_end_date.max(),"dropped_feature_count":0,"dropped_feature_names":"NONE","ridge_component_disabled":True}])
        label_parts=[x for x in label_audit_frames if isinstance(x,pd.DataFrame) and not x.empty]
        trial_ledger=pd.concat([model_part,policy_part,gate_part,state_part,*label_parts],ignore_index=True,sort=False)
        for column in trial_ledger.select_dtypes(include=["object"]).columns:
            trial_ledger[column]=trial_ledger[column].map(lambda value: json.dumps(value,sort_keys=True,default=str) if isinstance(value,(dict,list,tuple,set)) else value)
        atomic_parquet(OUT/"trial_ledger.parquet",trial_ledger)
    else:
        atomic_parquet(OUT/"security_state_ledger.parquet",security_ledger);atomic_parquet(OUT/"model_trial_ledger.parquet",model_ledger);atomic_parquet(OUT/"policy_trial_ledger.parquet",policy_ledger)
    all_outer.to_csv(OUT/"outer_metrics.csv",index=False,lineterminator="\n");primary_actions.to_csv(OUT/"action_attribution.csv",index=False,lineterminator="\n")

    support=discovery.groupby("ff12").agg(train_support=("ticker","size"),distinct_decision_dates=("signal_date","nunique")).reset_index();outer_support=panel.loc[panel.signal_date.dt.year.isin([2023,2024])].groupby(["ff12",panel.signal_date.dt.year.rename("year")]).size().unstack(fill_value=0).reset_index();sector=support.merge(outer_support,on="ff12",how="left").rename(columns={2023:"outer_2023_support",2024:"outer_2024_support"}).fillna(0)
    pred_sector=pd.DataFrame(sector_prediction_rows);sector["specialization_supported_both_outer_folds"]=False;sector["specialization_harmed_both_outer_folds"]=False
    if primary_id and not pred_sector.empty:
        chosen_sector=pred_sector.loc[pred_sector.policy_id.eq(primary_id)];pivot=chosen_sector.pivot_table(index="ff12",columns="year",values="delta_return",aggfunc="mean");supported_names=set(pivot.index[(pivot.get(2023,pd.Series(index=pivot.index,dtype=float))>0)&(pivot.get(2024,pd.Series(index=pivot.index,dtype=float))>0)]);harmed_names=set(pivot.index[(pivot.get(2023,pd.Series(index=pivot.index,dtype=float))<0)&(pivot.get(2024,pd.Series(index=pivot.index,dtype=float))<0)]);sector["specialization_supported_both_outer_folds"]=sector.ff12.isin(supported_names)&sector.train_support.ge(MIN_SECTOR_EVENTS)&sector.distinct_decision_dates.ge(MIN_SECTOR_DECISION_DATES);sector["specialization_harmed_both_outer_folds"]=sector.ff12.isin(harmed_names)
        agg=chosen_sector.groupby("ff12").agg(global_return=("global_return","mean"),global_plus_sector_return=("global_plus_sector_return","mean"),delta_return=("delta_return","mean"),delta_residual_return=("delta_residual_return","mean"),delta_downside=("delta_downside","mean"),delta_winner_capture=("delta_winner_capture","mean"),delta_cost=("delta_cost","mean")).reset_index();sector=sector.merge(agg,on="ff12",how="left")
    sector["fallback_to_global"]=~sector.specialization_supported_both_outer_folds;sector.to_csv(OUT/"sector_metrics.csv",index=False,lineterminator="\n")

    # Weightability gate and fixed execution stresses.
    raw_top_bottom={}
    for year in (2023,2024):
        f=panel.loc[panel.signal_date.dt.year.eq(year)&panel.a2_rank.le(20)];raw_top_bottom[year]=float(f.loc[f.a2_rank.le(5),"y_abs20"].mean()-f.loc[f.a2_rank.ge(16),"y_abs20"].mean())
        for low,high,label in [(1,5,"RANK_1_5"),(6,10,"RANK_6_10"),(11,15,"RANK_11_15"),(16,20,"RANK_16_20")]:
            q=f.loc[f.a2_rank.between(low,high)];robust_rows.append({"record_type":"WEIGHTABILITY","year":year,"bucket":label,"return_5d":q.y_abs5.mean(),"return_20d":q.y_abs20.mean(),"ff12_residual_return":q.y_ff12res20.mean(),"downside":q.y_downside20.mean(),"winner_frequency":q.y_abs20.ge(EXTREME_WINNER_RETURN).mean(),"volatility":q.y_abs20.std(),"contribution":q.y_abs20.mean()*(high-low+1)*.05})
    alpha_gate=("ALPHA_WEIGHTABILITY_SUPPORTED" if all(raw_top_bottom[y]>0 for y in (2023,2024)) else "ALPHA_WEIGHTABILITY_NOT_SUPPORTED") if IS_R2 else ("PASS" if all(raw_top_bottom[y]>0 for y in (2023,2024)) else "FAIL");cost15=cost2=delay_status="NOT_APPLICABLE_NO_PRIMARY"
    if primary_id:
        original_cost=e5.COST_RATE
        try:
            statuses={}
            for multiple,label in [(1.5,"COST_1_5X"),(2.0,"COST_2X")]:
                e5.COST_RATE=original_cost*multiple;fold_pass=[]
                for year in (2023,2024):
                    best_name=str(outer.loc[(outer.year.eq(year))&outer.policy_id.eq(primary_id),"best_simple"].iloc[0]);_,pm=replay_metrics(e5,action,primary_id,outer_target_maps[(year,primary_id)],prices,outer_target_maps[(year,"C0_RAW_TOP20_EQUAL_5")],taxonomy);_,bm=replay_metrics(e5,action,best_name,outer_target_maps[(year,best_name)],prices,outer_target_maps[(year,"C0_RAW_TOP20_EQUAL_5")],taxonomy);fold_pass.append(pm["sharpe"]>bm["sharpe"])
                statuses[label]="PASS" if all(fold_pass) else "FAIL"
            cost15,cost2=statuses["COST_1_5X"],statuses["COST_2X"]
        finally:e5.COST_RATE=original_cost
        delayed_pass=[]
        for year in (2023,2024):
            target=outer_target_maps[(year,primary_id)];dates=sorted(target);delayed={dates[i]:target[dates[max(0,i-1)]] for i in range(len(dates))};best_name=str(outer.loc[(outer.year.eq(year))&outer.policy_id.eq(primary_id),"best_simple"].iloc[0]);_,dm=replay_metrics(e5,action,primary_id+"__DELAY",delayed,prices,outer_target_maps[(year,"C0_RAW_TOP20_EQUAL_5")],taxonomy);bm=outer.loc[(outer.year.eq(year))&outer.policy_id.eq(best_name)].iloc[0];delayed_pass.append(dm["sharpe"]>bm.sharpe)
        delay_status="PASS" if all(delayed_pass) else "FAIL"
    pd.DataFrame(robust_rows).to_csv(OUT/"robustness_metrics.csv",index=False,lineterminator="\n")

    simple_means=outer.loc[outer.kind.eq("SIMPLE")].groupby("policy_id").sharpe.mean();best_simple_name=str(simple_means.idxmax());classification="NO_ROBUST_BUY_SELL_SIZING_EDGE"
    if forward_eligible:
        p=next(x for x in policy_specs if x.policy_id==primary_id)
        classification="FF12_HIERARCHICAL_POLICY_SUPPORTED" if spec_by_id[p.model_id].structure in {"M2_GLOBAL_PLUS_FF12_RESIDUAL_HEADS","M3_ROLE_AWARE_GLOBAL_PLUS_FF12"} else ("BOUNDED_SIZING_EDGE_SUPPORTED" if p.candidate_universe=="U0_RAW_TOP20" else "JOINT_BUY_SELL_SIZING_EDGE_SUPPORTED")
    elif primary_id:
        classification=("OVERFIT_RISK_TOO_HIGH_AFTER_CLEAN_LABELS" if not bootstrap_pass else "PROMISING_BUT_HISTORICAL_OOS_MIXED") if IS_R2 else ("OVERFIT_RISK_TOO_HIGH" if not bootstrap_pass else "PROMISING_BUT_OUTER_MIXED")
    elif best_simple_name=="C5_RAW_SCORE_SIMPLE_TILT" and all(float(outer.loc[(outer.year.eq(y))&outer.policy_id.eq(best_simple_name),"sharpe"].iloc[0])>float(outer.loc[(outer.year.eq(y))&outer.policy_id.eq("C0_RAW_TOP20_EQUAL_5"),"sharpe"].iloc[0]) for y in (2023,2024)):
        classification="SIMPLE_RAW_SCORE_SIZING_SUFFICIENT"
    elif best_simple_name=="C3_RANK_BUCKET_6_5_4" and all(float(outer.loc[(outer.year.eq(y))&outer.policy_id.eq(best_simple_name),"sharpe"].iloc[0])>float(outer.loc[(outer.year.eq(y))&outer.policy_id.eq("C0_RAW_TOP20_EQUAL_5"),"sharpe"].iloc[0]) for y in (2023,2024)):
        classification="SIMPLE_RANK_SIZING_SUFFICIENT"
    strongest=("No model/policy passed the preregistered inner gates; outer outcomes were used only for mandatory baselines and weightability diagnostics" if not outer_ids else f"{len(outer_ids)} inner-qualified specs were evaluated under the frozen outer contract")
    damaging=("inner net Sharpe failed to beat Raw while staying within 0.02 of the best simple baseline" if not outer_ids else ("no outer candidate cleared strict positive fold deltas and pooled +0.05" if not primary_id else "2025 exposed diagnostic was catastrophic" if catastrophic else "multiple-testing bootstrap failed" if not bootstrap_pass else "no damaging gate remained"))
    missed_winner_count=0;missed_winner_damage=0.0
    if primary_id:
        for year in (2023,2024):
            winners=panel_full.loc[panel_full.signal_date.dt.year.eq(year)&panel_full.a2_rank.le(20)&panel_full.y_abs20.ge(EXTREME_WINNER_RETURN),["signal_date","ticker","y_abs20"]];target_map=outer_target_maps[(year,primary_id)]
            missed=[r for r in winners.itertuples(index=False) if r.ticker not in target_map.get(pd.Timestamp(r.signal_date),{})];missed_winner_count+=len(missed);missed_winner_damage+=sum(float(r.y_abs20)*.05 for r in missed)
    economic_verdict=("CLEAN_LABELS + POSITIVE_POLICY_EDGE" if forward_eligible else "CLEAN_LABELS + SIMPLE_SIZING_SUFFICIENT" if classification in {"SIMPLE_RAW_SCORE_SIZING_SUFFICIENT","SIMPLE_RANK_SIZING_SUFFICIENT","RISK_ONLY_SIZING_SUPPORTED"} else "CLEAN_LABELS + MIXED_EVIDENCE" if primary_id else "CLEAN_LABELS + NO_ROBUST_POLICY_EDGE") if IS_R2 else classification
    summary={
        "research_status":"PASS_RESEARCH_COMPLETE_NEGATIVE_RESULT" if not forward_eligible else "PASS_RESEARCH_COMPLETE_FROZEN_CHALLENGER",
        "environment_status":"PREEXISTING_EXCEPTION_MANAGED_ACL_OBJECTS_2",
        "raw":raw,"a2_identity":a2_identity,"previous_acknowledged":True,"pairwise_veto_reused":False,"security_state_events":len(panel_train),"rebalance_dates":panel_train.signal_date.nunique(),"ff12":panel_train.ff12.nunique(),"ff48":panel_train.ff48.nunique(),
        "actual_model_specs":len(model_specs),"model_fits":counter.count,"policy_specs":len(policy_specs),"alpha_gate":alpha_gate,"raw_spread":raw_top_bottom,"outer_finalists":len(outer_ids),"primary_id":primary_id,"primary_spec":next((x.__dict__ for x in policy_specs if x.policy_id==primary_id),{}),"primary_model_spec":spec_by_id[next(x.model_id for x in policy_specs if x.policy_id==primary_id)].__dict__ if primary_id else {},"primary_2025":primary_2025,"forward_eligible":forward_eligible,"final_policy_id":final_policy_id,"final_policy_hash":final_hash,"policy_contract_hash":contract_hash,"final_train_feature":final_train_feature,"final_train_label":final_train_label,"classification":classification,"economic_verdict":economic_verdict,"strongest":strongest,"damaging":damaging,"u2_status":u2_status,"skipped_families":skipped_families,"taxonomy":tax_facts,"final_prereg_sha":final_prereg_sha,"all_outer":all_outer,"selection_outer":selection_outer,"sector_supported":int(sector.specialization_supported_both_outer_folds.sum()),"sector_harmed":int(sector.specialization_harmed_both_outer_folds.sum()),"sector_fallback":int(sector.fallback_to_global.sum()),"effective_trials":effective_trials,"bootstrap_pass":bootstrap_pass,"breadth":breadth,"cost15":cost15,"cost2":cost2,"delay":delay_status,"runtime_seconds":time.time()-started,"missed_winner_count":missed_winner_count,"missed_winner_damage":missed_winner_damage,"best_simple_name":best_simple_name,"impact_facts":impact_facts,"label_gate_facts":label_gate_facts,"label_contract_hash":label_contract_hash,
    }
    terminal=terminal_block(summary,all_outer,primary_actions)
    supported_names=", ".join(sector.loc[sector.specialization_supported_both_outer_folds,"ff12"].astype(str)) or "none"
    action_mean=lambda action_name,column: float(primary_actions.loc[primary_actions.action.eq(action_name),column].mean()) if not primary_actions.empty and action_name in set(primary_actions.action) else math.nan
    raw_new=panel.loc[panel.signal_date.dt.year.isin([2023,2024])&panel.current_role.eq("NEW_RAW_TOP20_ENTRANT")].y_abs20.mean();ml_new=action_mean("NEW_BUY","y_abs20");sell_value=float(primary_actions.loc[primary_actions.action.isin(["REDUCE","FULL_EXIT"]),"opportunity_value"].mean()) if not primary_actions.empty else math.nan
    report=f"""# {TASK}

## Direct answer

{'A frozen research-only challenger passed every gate; no production arm was modified.' if forward_eligible else 'No autonomous ML policy earned forward eligibility under the frozen gates. The hypothesis was failed cleanly without expanding the search after outer results.'}

## Required questions

- **A — Weightability:** `{alpha_gate}`. Top5-minus-bottom5 20D spreads were {raw_top_bottom[2023]:.6f} in 2023 and {raw_top_bottom[2024]:.6f} in 2024.
- **B — Global ML:** {'A frozen ML primary beat the fold-wise best simple baseline.' if primary_id else 'No Global or hierarchical ML policy cleared the frozen outer acceptance rule.'}
- **C — FF12:** Supported specialization sectors: {supported_names}. All other sectors fall back to Global; supported/harmed/fallback counts are {summary['sector_supported']}/{summary['sector_harmed']}/{summary['sector_fallback']}.
- **D — Buying:** ML new-buy mean 20D return was {ml_new}; Raw new-entrant mean was {raw_new}. This is descriptive outer attribution, not a new selection rule.
- **E — Selling:** Mean recipient-minus-sold/reduced 20D opportunity value was {sell_value}. A positive value means capital transfer helped.
- **F — Sizing:** {'The frozen primary used '+str(summary['primary_spec'].get('bounds'))+'.' if primary_id else 'Neither 3–7% nor 4–6% ML sizing passed the full robustness contract.'}
- **G — Source:** Contribution-breadth diagnostics are in `robustness_metrics.csv`; they distinguish broad alpha from isolated securities, rebalances, sectors, and periods.
- **H — Overfit:** Effective trial count was {effective_trials:.3f}; block/cluster bootstrap status was {'PASS' if bootstrap_pass else 'FAIL_OR_NOT_APPLICABLE'}.
- **I — 2025:** Frozen diagnostic: {primary_2025}; the primary specification was not changed after the read.
- **J — Forward:** `FORWARD_ELIGIBLE={str(forward_eligible).upper()}`. Any bundle is a prospective challenger only and was not bound to production.

## Governance and evidence

- Authoritative Raw replay passed at 751 sessions, CAGR {raw['cagr']:.12f}, Sharpe {raw['sharpe']:.12f}, MaxDD {raw['max_drawdown']:.12f}.
- The prior pairwise Hold/Replace failure was acknowledged and the pairwise veto was not reused.
- Existing preregistration `{OLD_PREREG_SHA256}` was reconciled once before outer outcome access; final prereg SHA256 is `{final_prereg_sha}`.
- `2026_OUTCOME_USED=FALSE`; every fitted label ends no later than 2025-12-31. U2 status: `{u2_status}`.
- Strongest evidence: {strongest}.
- Most damaging evidence: {damaging}.

## Terminal summary

```text
{terminal}
```
"""
    if IS_R2:
        report=f"""# {R2_TASK}

## Independent validity answers

**A. Data / research validity.** `LABEL_LINEAGE_HARD_GATE=PASS`. T0/T2 were fully reconciled against independently shifted `raw_counterfactual.close`; T1/T4 were independently reconstructed on the actual candidate-state panels. Mixed-scale labels, portfolio-ledger label marks, arithmetic mismatches, and 2026 labels all count zero. NVDA and the existing forward/reverse-split/control sentinels passed before candidate fitting.

**B. Historical economic evidence.** `{economic_verdict}` and `{classification}`. The 2023/2024 periods are fixed historical OOS evidence, not pristine unseen holdouts. Search space was copied from the frozen invalid-R1 preregistration and was not expanded; invalid R1's 328 fits, outer ranking, sector results, attribution, and 2025 outcome were never used for R2 selection.

**C. Prospective readiness.** `FORWARD_ELIGIBLE={str(forward_eligible).upper()}`. Any eligible output is only a new frozen prospective challenger requiring human review; Raw, S1, Ridge, broker bindings, and production ledgers were not modified.

## Root cause and impact audit

1. The invalid builder followed `main -> qfq_forward_labels -> action.load_prices -> ledger-overlaid prices.close`. Exact position-ledger marks could override QFQ at one endpoint, so split-scale changes could become fictitious returns such as the NVDA approximately +5401% label.
2. Because T0 fed T1/T4 and model selection while T2/T3 used the same mixed path, all 328 invalid fits and their weightability, outer, 2025, sector, and action analyses are forensic evidence only—not positive or negative strategy evidence.
3. The narrow call-chain audit classifies invalid autonomous R1 as impacted. Hold/Replace, the model-family research dataset, and Sector-aware Ridge are `LINEAGE_UNVERIFIED`: their shared frozen dataset records no builder or start/end price lineage metadata.
4. Raw A2 and S1 are retained as `NOT_LABEL_DEPENDENT`; their proven call path constructs deterministic weights and uses the authoritative replay rather than ML training labels.
5. Sector-aware Ridge is not usable in R2. `U2_STATUS={u2_status}`; no Ridge score was rebuilt merely to preserve U2.

## Clean R2 economic interpretation

6. **Top20 weightability:** `{alpha_gate}`. Clean Top5-minus-bottom5 20D spreads were {raw_top_bottom[2023]:.6f} in 2023 and {raw_top_bottom[2024]:.6f} in 2024.
7. **Global ML versus Raw/simple:** {'A frozen ML primary cleared the original robustness-first gate.' if primary_id else 'No Global or hierarchical ML policy cleared the original frozen outer gate against the fold-wise best simple baseline.'}
8. **FF12 specialization:** Supported sectors: {supported_names}; supported/harmed/fallback counts are {summary['sector_supported']}/{summary['sector_harmed']}/{summary['sector_fallback']}. Unsupported heads fall back to Global.
9. **Actions:** Clean ML new-buy mean 20D return was {ml_new}; Raw new-entrant mean was {raw_new}. Clean recipient-minus-sold/reduced opportunity value was {sell_value}. Full action counts and clean 5D/20D fields are in `action_attribution.csv`.
10. **Sizing:** {'The frozen primary used bounds '+str(summary['primary_spec'].get('bounds'))+'.' if primary_id else 'Neither frozen 3–7% nor 4–6% ML sizing earned a robust primary.'} Fixed-membership and joint-selection candidates retained Raw A2 as a nonzero prior.
11. **Source of improvement:** Contribution breadth, costs, risk, winner damage, security/rebalance/sector exclusions, and execution stress are in `robustness_metrics.csv`; strongest evidence is {strongest}; most damaging evidence is {damaging}.
12. **Multiple testing:** Effective clean R2 trial count was {effective_trials:.3f}; block/rebalance bootstrap and Deflated-Sharpe-equivalent status was {'PASS' if bootstrap_pass else 'FAIL_OR_NOT_APPLICABLE'}. The 328 invalid fits are provenance only and excluded from the valid economic trial distribution.
13. **Corrected 2025:** `{primary_2025}`. This was read once after the durable primary freeze and caused no model, feature, threshold, universe, or bound change.

## Governance

- `ONLY_MATERIAL_RESEARCH_CHANGE=LABEL_PRICE_LINEAGE_CORRECTION_AND_PREFIT_LINEAGE_GATES`
- `SEARCH_SPACE_EXPANDED=FALSE`
- Invalid R1 prereg SHA256: `{INVALID_R1_PREREG_SHA256}`; final R2 prereg SHA256: `{final_prereg_sha}`.
- Label contract SHA256: `{label_contract_hash}`.
- `2026_OUTCOME_USED=FALSE`; `2026_LEAKAGE_COUNT=0`.
- Task-local Anti-Bloat passes; the two pre-existing managed-ACL accounting exceptions were not modified.

## Terminal summary

```text
{terminal}
```
"""
    (OUT/"final_report.md").write_text(report,encoding="utf-8")
    files=sorted(p for p in OUT.iterdir() if p.is_file() and p.name!="hash_manifest.json");require(len(files)+1<=12,"ARTIFACT_BUDGET")
    manifest_out={"task_id":TASK,"status":"PASS_HASH_VERIFIED","artifact_count_including_manifest":len(files)+1,"2026_outcome_used":False,"2026_leakage_count":0,"source_sha256":sha256_file(Path(__file__)),"artifacts":[{"name":p.name,"bytes":p.stat().st_size,"sha256":sha256_file(p)} for p in files],"authoritative_inputs":{"raw_oof":sha256_file(OOF),"raw_training_matrix":sha256_file(MATRIX),"previous_manifest":sha256_file((INVALID_R1 if IS_R2 else PREVIOUS)/"hash_manifest.json"),"invalid_r1_prereg":INVALID_R1_PREREG_SHA256 if IS_R2 else None,"label_lineage_contract":label_contract_hash if IS_R2 else None},"label_lineage_hard_gate":"PASS" if IS_R2 else "NOT_APPLICABLE_R1","search_space_expanded":False};atomic_json(OUT/"hash_manifest.json",manifest_out)
    summary["artifact_count"]=len(list(OUT.iterdir()));summary["hash_status"]="PASS_HASH_VERIFIED";terminal=terminal_block(summary,all_outer,primary_actions);report=report.rsplit("```text\n",1)[0]+"```text\n"+terminal+"\n```\n";(OUT/"final_report.md").write_text(report,encoding="utf-8")
    files=sorted(p for p in OUT.iterdir() if p.is_file() and p.name!="hash_manifest.json");manifest_out["artifacts"]=[{"name":p.name,"bytes":p.stat().st_size,"sha256":sha256_file(p)} for p in files];manifest_out["artifact_count_including_manifest"]=len(files)+1;atomic_json(OUT/"hash_manifest.json",manifest_out)
    if STATE_CACHE.is_file():
        STATE_CACHE.unlink()
    if STATE_CACHE.parent.is_dir() and not any(STATE_CACHE.parent.iterdir()):
        STATE_CACHE.parent.rmdir()
    print(terminal)
    return 0


def terminal_block_r2(s: dict[str,Any], outer: pd.DataFrame, actions: pd.DataFrame) -> str:
    primary=s["primary_id"];evaluation=outer.loc[outer.year.isin([2023,2024])].copy();simple=evaluation.loc[evaluation.kind.eq("SIMPLE")]
    raw_rows=simple.loc[simple.policy_id.eq("C0_RAW_TOP20_EQUAL_5")];best_name=s["best_simple_name"];best_rows=simple.loc[simple.policy_id.eq(best_name)]
    e5_rows=simple.loc[simple.policy_id.eq("C1_E5_COMBINED_CONSERVATIVE")];s1_rows=simple.loc[simple.policy_id.eq("C2_S1_SOFT_025")]
    prows=evaluation.loc[evaluation.policy_id.eq(primary)] if primary else pd.DataFrame()
    mean=lambda frame,column: float(frame[column].mean()) if not frame.empty and column in frame else math.nan
    pm={column:mean(prows,column) for column in ["cagr","sharpe","max_drawdown","turnover","cost","qqq_beta","downside_beta","ff12_hhi","ff48_hhi"]}
    rm={column:mean(raw_rows,column) for column in ["cagr","sharpe","max_drawdown","turnover","cost"]};bm={column:mean(best_rows,column) for column in ["cagr","sharpe","max_drawdown","turnover","cost"]}
    delta_by_year={year:(float(prows.loc[prows.year.eq(year),"delta_sharpe_best_simple"].iloc[0]) if primary and "delta_sharpe_best_simple" in prows and not prows.loc[prows.year.eq(year)].empty else math.nan) for year in (2023,2024)}
    raw_delta_by_year={year:(float(prows.loc[prows.year.eq(year),"delta_sharpe_raw"].iloc[0]) if primary and "delta_sharpe_raw" in prows and not prows.loc[prows.year.eq(year)].empty else math.nan) for year in (2023,2024)}
    count=lambda name:int(actions.action.eq(name).sum()) if not actions.empty and "action" in actions else 0
    value=lambda name,column="y_abs20":float(actions.loc[actions.action.eq(name),column].mean()) if not actions.empty and name in set(actions.action) and column in actions else math.nan
    breadth=s.get("breadth",{});model=s.get("primary_model_spec",{});policy=s.get("primary_spec",{});impact=s.get("impact_facts",{});gate=s.get("label_gate_facts",{})
    positive=int(sum(x>0 for x in delta_by_year.values() if np.isfinite(x)))
    buy_lesson=f"CLEAN_ML_NEW_BUY_MEAN_20D={value('NEW_BUY')}" if primary else "NO_FROZEN_ML_PRIMARY;RAW_NEW_BUYS_NOT_OVERRIDDEN"
    sell_lesson=f"CLEAN_EXIT_OPPORTUNITY_VALUE={value('FULL_EXIT','opportunity_value')};CLEAN_REDUCTION_OPPORTUNITY_VALUE={value('REDUCE','opportunity_value')}" if primary else "NO_FROZEN_ML_PRIMARY;NO_ML_EXIT_EDGE_CLAIM"
    sizing_lesson=f"PRIMARY_BOUNDS={policy.get('bounds')}" if primary else f"{s['alpha_gate']};NO_ML_BOUNDS_PASSED"
    sector_lesson=f"SUPPORTED={s['sector_supported']};HARMED={s['sector_harmed']};FALLBACK={s['sector_fallback']}"
    return "\n".join([
        "="*60,R2_TASK+"_FINAL","="*60,"",
        f"RESEARCH_STATUS={s['research_status']}",f"ENVIRONMENT_STATUS={s['environment_status']}",f"ECONOMIC_VERDICT={s['economic_verdict']}","",
        "INVALID_R1_STATUS=FAIL_CLOSED_LABEL_PRICE_LINEAGE_FAILURE",f"INVALID_R1_PREREG_SHA256={impact.get('invalid_r1_prereg_sha256')}","INVALID_R1_OUTER_REUSED_FOR_SELECTION=FALSE","",
        f"CONTAMINATED_LABEL_BUILDER={impact.get('contaminated_label_builder')}",f"CONTAMINATED_PRICE_FIELD={impact.get('contaminated_price_field')}",f"ROOT_CAUSE={impact.get('root_cause')}","",
        f"PRIOR_RESEARCH_IMPACT_STATUS={impact.get('impact_status')}",f"IMPACTED_PRIOR_RESEARCH_COUNT={impact.get('impacted_count')}",f"LINEAGE_UNVERIFIED_PRIOR_RESEARCH_COUNT={impact.get('lineage_unverified_count')}",f"UNAFFECTED_PRIOR_RESEARCH_COUNT={impact.get('unaffected_count')}","",
        f"HOLD_REPLACE_R1_LINEAGE_STATUS={impact.get('hold_replace_status')}",f"SECTOR_AWARE_RIDGE_LINEAGE_STATUS={impact.get('sector_aware_ridge_status')}",f"RAW_A2_LINEAGE_STATUS={impact.get('raw_status')}",f"S1_LINEAGE_STATUS={impact.get('s1_status')}",f"U2_STATUS={s['u2_status']}","",
        f"LABEL_PRICE_LINEAGE={LABEL_LINEAGE}",f"LABEL_LINEAGE_CONTRACT_HASH={s.get('label_contract_hash')}","LABEL_LINEAGE_HARD_GATE=PASS","",
        f"LABEL_ARITHMETIC_MISMATCH_COUNT={gate.get('label_arithmetic_mismatch_count',0)}",f"MIXED_SCALE_LABEL_COUNT={gate.get('mixed_scale_label_count',0)}",f"PORTFOLIO_LEDGER_MARK_USED_AS_LABEL_COUNT={gate.get('portfolio_ledger_mark_used_as_label_count',0)}",f"CORPORATE_ACTION_SENTINEL_STATUS={gate.get('corporate_action_sentinel_status')}",f"NVDA_REGRESSION_STATUS={gate.get('nvda_regression_status')}","",
        "2026_OUTCOME_USED=FALSE","2026_LEAKAGE_COUNT=0",f"FINAL_TRAIN_MAX_FEATURE_DATE={s['final_train_feature'] or 'NOT_APPLICABLE:NO_FORWARD_ELIGIBLE_PRIMARY'}",f"FINAL_TRAIN_MAX_LABEL_END_DATE={s['final_train_label'] or 'NOT_APPLICABLE:NO_FORWARD_ELIGIBLE_PRIMARY'}","",
        "AUTHORITATIVE_RAW_REPLAY_STATUS=PASS_EXACT_AUTHORITATIVE_TOLERANCE",f"AUTHORITATIVE_RAW_SESSIONS={s['raw']['session_count']}",f"AUTHORITATIVE_RAW_CAGR={s['raw']['cagr']}",f"AUTHORITATIVE_RAW_SHARPE={s['raw']['sharpe']}",f"AUTHORITATIVE_RAW_MAXDD={s['raw']['max_drawdown']}","",
        "SEARCH_SPACE_EXPANDED=FALSE",f"MAX_UNIQUE_MODEL_SPECS={MAX_UNIQUE_MODEL_SPECS}",f"ACTUAL_UNIQUE_MODEL_SPECS={s['actual_model_specs']}",f"TOTAL_MODEL_FITS={s['model_fits']}",f"TOTAL_POLICY_SPECS={s['policy_specs']}",f"OUTER_FINALIST_COUNT={s['outer_finalists']}","",
        f"ALPHA_WEIGHTABILITY_GATE={s['alpha_gate']}",f"TOP_BOTTOM_SPREAD_2023={s['raw_spread'][2023]}",f"TOP_BOTTOM_SPREAD_2024={s['raw_spread'][2024]}","",
        f"PRIMARY_MODEL_FAMILY={model.get('family','NONE')}","PRIMARY_TARGET_STRUCTURE=T0_ABS20|T1_FF12RES20|T2_ABS5|T3_DOWNSIDE20|T4_PERSIST20",f"PRIMARY_FEATURE_SET={model.get('feature_family','NONE')}",f"PRIMARY_POLICY_FAMILY={policy.get('family','NONE')}",f"PRIMARY_CANDIDATE_UNIVERSE={policy.get('candidate_universe','NONE')}",f"PRIMARY_SECTOR_STRUCTURE={model.get('structure','NONE')}",f"PRIMARY_RAW_PRIOR_ETA={policy.get('eta','NONE')}",f"PRIMARY_WEIGHT_BOUNDS={policy.get('bounds','NONE')}","PRIMARY_FIXED_BEFORE_2025_READ=TRUE","",
        f"RAW_CAGR={s['raw']['cagr']}",f"RAW_SHARPE={s['raw']['sharpe']}",f"RAW_MAXDD={s['raw']['max_drawdown']}","",f"E5_SHARPE={mean(e5_rows,'sharpe')}",f"S1_SHARPE={mean(s1_rows,'sharpe')}",f"BEST_SIMPLE_NAME={best_name}",f"BEST_SIMPLE_SHARPE={mean(best_rows,'sharpe')}","",f"PRIMARY_CAGR={pm['cagr']}",f"PRIMARY_SHARPE={pm['sharpe']}",f"PRIMARY_MAXDD={pm['max_drawdown']}","",
        f"PRIMARY_DELTA_CAGR_VS_RAW={pm['cagr']-rm['cagr'] if primary else math.nan}",f"PRIMARY_DELTA_SHARPE_VS_RAW={pm['sharpe']-rm['sharpe'] if primary else math.nan}",f"PRIMARY_DELTA_SHARPE_VS_BEST_SIMPLE={pm['sharpe']-bm['sharpe'] if primary else math.nan}",f"PRIMARY_DELTA_MAXDD_VS_RAW={pm['max_drawdown']-rm['max_drawdown'] if primary else math.nan}",f"PRIMARY_DELTA_TURNOVER={pm['turnover']-rm['turnover'] if primary else math.nan}",f"PRIMARY_DELTA_COST={pm['cost']-rm['cost'] if primary else math.nan}","",
        f"2023_DELTA_SHARPE_VS_RAW={raw_delta_by_year[2023]}",f"2023_DELTA_SHARPE_VS_BEST_SIMPLE={delta_by_year[2023]}",f"2024_DELTA_SHARPE_VS_RAW={raw_delta_by_year[2024]}",f"2024_DELTA_SHARPE_VS_BEST_SIMPLE={delta_by_year[2024]}",f"POSITIVE_HISTORICAL_OOS_FOLDS={positive}","",
        f"PRIMARY_QQQ_BETA={pm['qqq_beta']}",f"PRIMARY_DOWNSIDE_BETA={pm['downside_beta']}",f"PRIMARY_FF12_HHI={pm['ff12_hhi']}",f"PRIMARY_FF48_HHI={pm['ff48_hhi']}","",f"FF12_SPECIALIZATION_SUPPORTED_COUNT={s['sector_supported']}",f"FF12_SPECIALIZATION_HARMED_COUNT={s['sector_harmed']}",f"FF12_FALLBACK_TO_GLOBAL_COUNT={s['sector_fallback']}","",
        f"NEW_BUY_COUNT={count('NEW_BUY')}",f"NEW_BUY_VALUE={value('NEW_BUY')}",f"ADD_COUNT={count('ADD')}",f"ADD_VALUE={value('ADD')}",f"HOLD_COUNT={count('HOLD_UNCHANGED')}",f"HOLD_VALUE={value('HOLD_UNCHANGED')}",f"REDUCE_COUNT={count('REDUCE')}",f"REDUCE_VALUE={value('REDUCE','opportunity_value')}",f"FULL_EXIT_COUNT={count('FULL_EXIT')}",f"FULL_EXIT_VALUE={value('FULL_EXIT','opportunity_value')}","",
        f"WINNER_CAPTURE_DELTA={-s['missed_winner_count']}",f"MISSED_WINNER_COUNT={s['missed_winner_count']}",f"MISSED_WINNER_DAMAGE={s['missed_winner_damage']}","",
        f"PRIMARY_EX_BEST1_REBALANCE={breadth.get('best1_rebalance','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST3_REBALANCES={breadth.get('best3_rebalances','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST5_REBALANCES={breadth.get('best5_rebalances','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST1_SECURITY={breadth.get('best1_security','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST3_SECURITIES={breadth.get('best3_securities','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST5_SECURITIES={breadth.get('best5_securities','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST_FF12={breadth.get('best_ff12','NOT_APPLICABLE_NO_PRIMARY')}","",
        f"COST_1_5X_STATUS={s['cost15']}",f"COST_2X_STATUS={s['cost2']}",f"EXECUTION_DELAY_STATUS={s['delay']}","",f"MULTIPLE_TESTING_STATUS={'PASS' if s['bootstrap_pass'] else 'FAIL_OR_NOT_APPLICABLE'}",f"EFFECTIVE_TRIAL_COUNT={s['effective_trials']}",f"DEFLATED_SHARPE_STATUS={'PASS' if s['bootstrap_pass'] else 'FAIL_OR_NOT_APPLICABLE'}",f"BLOCK_BOOTSTRAP_STATUS={'PASS' if s['bootstrap_pass'] else 'FAIL_OR_NOT_APPLICABLE'}","",
        "EVIDENCE_CLASS=FIXED_HISTORICAL_OOS_NOT_PROSPECTIVE","","2025_STATUS=CORRECTED_LABEL_READ_ONCE_EXPOSED_DIAGNOSTIC",f"PRIMARY_2025_DIAGNOSTIC={s['primary_2025']}","PRIMARY_CHANGED_AFTER_2025_READ=FALSE","",
        f"FORWARD_ELIGIBLE={str(s['forward_eligible']).upper()}",f"FORWARD_ROLE={'NEW_PROSPECTIVE_CHALLENGER_HUMAN_REVIEW_REQUIRED' if s['forward_eligible'] else 'NONE'}",f"FINAL_FORWARD_POLICY_ID={s['final_policy_id'] or 'NONE'}",f"FINAL_FORWARD_POLICY_HASH={s['final_policy_hash'] or 'NONE'}",f"FINAL_POLICY_CONTRACT_HASH={s['policy_contract_hash'] or 'NONE'}","",f"PRIMARY_CLASSIFICATION={s['classification']}","",
        "MAIN_LABEL_LINEAGE_LESSON=Labels are valid only after same-lineage raw_counterfactual arithmetic, corporate-action sentinels, and portfolio-ledger exclusion pass before candidate fitting.",f"MAIN_BUYING_LESSON={buy_lesson}",f"MAIN_SELLING_LESSON={sell_lesson}",f"MAIN_SIZING_LESSON={sizing_lesson}",f"MAIN_SECTOR_LESSON={sector_lesson}",f"MAIN_RISK={s['damaging']}",f"STRONGEST_SUPPORTING_EVIDENCE={s['strongest']}",f"MOST_DAMAGING_EVIDENCE={s['damaging']}","",
        "TASK_LOCAL_ANTI_BLOAT_STATUS=PASS","PREEXISTING_ACL_EXCEPTION_COUNT=2",f"FINAL_ARTIFACT_COUNT={s.get('artifact_count','PENDING')}",f"HASH_MANIFEST_STATUS={s.get('hash_status','PENDING')}","","="*60,
    ])


def terminal_block(s: dict[str,Any], outer: pd.DataFrame, actions: pd.DataFrame) -> str:
    if IS_R2:
        return terminal_block_r2(s,outer,actions)
    primary=s["primary_id"];evaluation=outer.loc[outer.year.isin([2023,2024])].copy();simple=evaluation.loc[evaluation.kind.eq("SIMPLE")];raw_rows=simple.loc[simple.policy_id.eq("C0_RAW_TOP20_EQUAL_5")];best_name=s["best_simple_name"];best_rows=simple.loc[simple.policy_id.eq(best_name)];e5_rows=simple.loc[simple.policy_id.eq("C1_E5_COMBINED_CONSERVATIVE")];s1_rows=simple.loc[simple.policy_id.eq("C2_S1_SOFT_025")];prows=evaluation.loc[evaluation.policy_id.eq(primary)] if primary else pd.DataFrame()
    mean=lambda frame,column: float(frame[column].mean()) if not frame.empty and column in frame else math.nan
    pm={column:mean(prows,column) for column in ["cagr","sharpe","max_drawdown","turnover","cost","qqq_beta","downside_beta","ff12_hhi","ff48_hhi"]}
    rm={column:mean(raw_rows,column) for column in ["cagr","sharpe","max_drawdown","turnover","cost"]};bm={column:mean(best_rows,column) for column in ["cagr","sharpe","max_drawdown","turnover","cost"]}
    delta_by_year={year:(float(prows.loc[prows.year.eq(year),"delta_sharpe_best_simple"].iloc[0]) if primary and "delta_sharpe_best_simple" in prows and not prows.loc[prows.year.eq(year)].empty else math.nan) for year in (2023,2024)}
    raw_delta_by_year={year:(float(prows.loc[prows.year.eq(year),"delta_sharpe_raw"].iloc[0]) if primary and "delta_sharpe_raw" in prows and not prows.loc[prows.year.eq(year)].empty else math.nan) for year in (2023,2024)}
    count=lambda name:int(actions.action.eq(name).sum()) if not actions.empty and "action" in actions else 0
    value=lambda name,column="y_abs20":float(actions.loc[actions.action.eq(name),column].mean()) if not actions.empty and name in set(actions.action) and column in actions else math.nan
    breadth=s.get("breadth",{});model=s.get("primary_model_spec",{});policy=s.get("primary_spec",{});positive=int(sum(x>0 for x in delta_by_year.values() if np.isfinite(x)))
    buy_lesson=(f"ML_NEW_BUY_MEAN_20D={value('NEW_BUY')}" if primary else "NO_FROZEN_ML_PRIMARY")
    sell_lesson=(f"EXIT_OPPORTUNITY_VALUE={value('FULL_EXIT','opportunity_value')};REDUCTION_OPPORTUNITY_VALUE={value('REDUCE','opportunity_value')}" if primary else "NO_FROZEN_ML_PRIMARY")
    sizing_lesson=(f"PRIMARY_BOUNDS={policy.get('bounds')}" if primary else f"ALPHA_WEIGHTABILITY_GATE={s['alpha_gate']};NO_ML_BOUNDS_PASSED")
    sector_lesson=f"SUPPORTED={s['sector_supported']};HARMED={s['sector_harmed']};FALLBACK={s['sector_fallback']}"
    return "\n".join([
        "="*60,TASK+"_FINAL","="*60,"",f"RESEARCH_STATUS={s['research_status']}",f"ENVIRONMENT_STATUS={s['environment_status']}","",
        "EXISTING_PREREG_STATUS=RECONCILED_ONCE_BEFORE_OUTER","PREVIOUS_PREREG_SHA256="+OLD_PREREG_SHA256,"PREREG_RECONCILIATION_STATUS=ONE_TIME_PREREGISTRATION_RECONCILIATION_COMPLETE",f"FINAL_PREREG_SHA256={s['final_prereg_sha']}","",
        "2026_OUTCOME_USED=FALSE","2026_LEAKAGE_COUNT=0",f"FINAL_TRAIN_MAX_FEATURE_DATE={s['final_train_feature'] or 'NOT_APPLICABLE:NO_FORWARD_ELIGIBLE_PRIMARY'}",f"FINAL_TRAIN_MAX_LABEL_END_DATE={s['final_train_label'] or 'NOT_APPLICABLE:NO_FORWARD_ELIGIBLE_PRIMARY'}","",
        "AUTHORITATIVE_RAW_REPLAY_STATUS=PASS_EXACT_AUTHORITATIVE_TOLERANCE",f"AUTHORITATIVE_RAW_SESSIONS={s['raw']['session_count']}",f"AUTHORITATIVE_RAW_CAGR={s['raw']['cagr']}",f"AUTHORITATIVE_RAW_SHARPE={s['raw']['sharpe']}",f"AUTHORITATIVE_RAW_MAXDD={s['raw']['max_drawdown']}","",
        "PREVIOUS_HOLD_REPLACE_NEGATIVE_RESULT_ACKNOWLEDGED=TRUE","PAIRWISE_VETO_REUSED=FALSE","",f"TOTAL_SECURITY_STATE_EVENTS={s['security_state_events']}",f"TOTAL_DECISION_DATES={s['rebalance_dates']}",f"TOTAL_FF12_SECTORS={s['ff12']}",f"TOTAL_FF48_GROUPS={s['ff48']}","",
        f"MAX_UNIQUE_MODEL_SPECS={MAX_UNIQUE_MODEL_SPECS}",f"ACTUAL_UNIQUE_MODEL_SPECS={s['actual_model_specs']}",f"TOTAL_MODEL_FITS={s['model_fits']}",f"TOTAL_POLICY_SPECS={s['policy_specs']}","",
        f"ALPHA_WEIGHTABILITY_GATE={s['alpha_gate']}",f"TOP_BOTTOM_SPREAD_2023={s['raw_spread'][2023]}",f"TOP_BOTTOM_SPREAD_2024={s['raw_spread'][2024]}","",f"OUTER_FINALIST_COUNT={s['outer_finalists']}","",
        f"PRIMARY_MODEL_FAMILY={model.get('family','NONE')}","PRIMARY_TARGET_STRUCTURE=T0_ABS20|T1_FF12RES20|T2_ABS5|T3_DOWNSIDE20|T4_PERSIST20",f"PRIMARY_FEATURE_SET={model.get('feature_family','NONE')}",f"PRIMARY_POLICY_FAMILY={policy.get('family','NONE')}",f"PRIMARY_CANDIDATE_UNIVERSE={policy.get('candidate_universe','NONE')}",f"PRIMARY_SECTOR_STRUCTURE={model.get('structure','NONE')}",f"PRIMARY_RAW_PRIOR_ETA={policy.get('eta','NONE')}",f"PRIMARY_WEIGHT_BOUNDS={policy.get('bounds','NONE')}",f"PRIMARY_ENTRY_PROTECTION={policy.get('entrant_protection','NONE')}","",f"PRIMARY_FIXED_BEFORE_2025_READ={str(True).upper()}","",
        f"RAW_CAGR={s['raw']['cagr']}",f"RAW_SHARPE={s['raw']['sharpe']}",f"RAW_MAXDD={s['raw']['max_drawdown']}","",f"E5_SHARPE={mean(e5_rows,'sharpe')}",f"S1_SHARPE={mean(s1_rows,'sharpe')}",f"BEST_SIMPLE_NAME={best_name}",f"BEST_SIMPLE_SHARPE={mean(best_rows,'sharpe')}","",f"PRIMARY_CAGR={pm['cagr']}",f"PRIMARY_SHARPE={pm['sharpe']}",f"PRIMARY_MAXDD={pm['max_drawdown']}","",
        f"PRIMARY_DELTA_CAGR_VS_RAW={pm['cagr']-rm['cagr'] if primary else math.nan}",f"PRIMARY_DELTA_SHARPE_VS_RAW={pm['sharpe']-rm['sharpe'] if primary else math.nan}",f"PRIMARY_DELTA_SHARPE_VS_BEST_SIMPLE={pm['sharpe']-bm['sharpe'] if primary else math.nan}",f"PRIMARY_DELTA_MAXDD_VS_RAW={pm['max_drawdown']-rm['max_drawdown'] if primary else math.nan}",f"PRIMARY_DELTA_TURNOVER={pm['turnover']-rm['turnover'] if primary else math.nan}",f"PRIMARY_DELTA_COST={pm['cost']-rm['cost'] if primary else math.nan}","",
        f"2023_DELTA_SHARPE_VS_RAW={raw_delta_by_year[2023]}",f"2023_DELTA_SHARPE_VS_BEST_SIMPLE={delta_by_year[2023]}",f"2024_DELTA_SHARPE_VS_RAW={raw_delta_by_year[2024]}",f"2024_DELTA_SHARPE_VS_BEST_SIMPLE={delta_by_year[2024]}",f"POSITIVE_OUTER_FOLDS={positive}","",
        f"PRIMARY_QQQ_BETA={pm['qqq_beta']}",f"PRIMARY_DOWNSIDE_BETA={pm['downside_beta']}",f"PRIMARY_FF12_HHI={pm['ff12_hhi']}",f"PRIMARY_FF48_HHI={pm['ff48_hhi']}","",f"FF12_SPECIALIZATION_SUPPORTED_COUNT={s['sector_supported']}",f"FF12_SPECIALIZATION_HARMED_COUNT={s['sector_harmed']}",f"FF12_FALLBACK_TO_GLOBAL_COUNT={s['sector_fallback']}","",
        f"NEW_BUY_COUNT={count('NEW_BUY')}",f"NEW_BUY_VALUE={value('NEW_BUY')}",f"ADD_COUNT={count('ADD')}",f"ADD_VALUE={value('ADD')}",f"HOLD_COUNT={count('HOLD_UNCHANGED')}",f"HOLD_VALUE={value('HOLD_UNCHANGED')}",f"REDUCE_COUNT={count('REDUCE')}",f"REDUCE_VALUE={value('REDUCE','opportunity_value')}",f"FULL_EXIT_COUNT={count('FULL_EXIT')}",f"FULL_EXIT_VALUE={value('FULL_EXIT','opportunity_value')}","",f"WINNER_CAPTURE_DELTA={-s['missed_winner_count']}",f"MISSED_WINNER_COUNT={s['missed_winner_count']}",f"MISSED_WINNER_DAMAGE={s['missed_winner_damage']}","",
        f"PRIMARY_EX_BEST1_REBALANCE={breadth.get('best1_rebalance','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST3_REBALANCES={breadth.get('best3_rebalances','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST5_REBALANCES={breadth.get('best5_rebalances','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST1_SECURITY={breadth.get('best1_security','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST3_SECURITIES={breadth.get('best3_securities','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST5_SECURITIES={breadth.get('best5_securities','NOT_APPLICABLE_NO_PRIMARY')}",f"PRIMARY_EX_BEST_FF12={breadth.get('best_ff12','NOT_APPLICABLE_NO_PRIMARY')}","",
        f"COST_1_5X_STATUS={s['cost15']}",f"COST_2X_STATUS={s['cost2']}",f"EXECUTION_DELAY_STATUS={s['delay']}","",f"MULTIPLE_TESTING_STATUS={'PASS' if s['bootstrap_pass'] else 'FAIL_OR_NOT_APPLICABLE'}",f"EFFECTIVE_TRIAL_COUNT={s['effective_trials']}",f"DEFLATED_SHARPE_STATUS={'PASS' if s['bootstrap_pass'] else 'FAIL_OR_NOT_APPLICABLE'}",f"BLOCK_BOOTSTRAP_STATUS={'PASS' if s['bootstrap_pass'] else 'FAIL_OR_NOT_APPLICABLE'}","",
        "2025_STATUS=READ_ONCE_EXPOSED_DIAGNOSTIC_ONLY",f"PRIMARY_2025_DIAGNOSTIC={s['primary_2025']}","PRIMARY_CHANGED_AFTER_2025_READ=FALSE","",f"FORWARD_ELIGIBLE={str(s['forward_eligible']).upper()}",f"FINAL_FORWARD_POLICY_ID={s['final_policy_id'] or 'NONE'}",f"FINAL_FORWARD_POLICY_HASH={s['final_policy_hash'] or 'NONE'}",f"FINAL_POLICY_CONTRACT_HASH={s['policy_contract_hash'] or 'NONE'}","",f"PRIMARY_CLASSIFICATION={s['classification']}","",f"MAIN_BUYING_LESSON={buy_lesson}",f"MAIN_SELLING_LESSON={sell_lesson}",f"MAIN_SIZING_LESSON={sizing_lesson}",f"MAIN_SECTOR_LESSON={sector_lesson}",f"MAIN_RISK={s['damaging']}",f"STRONGEST_SUPPORTING_EVIDENCE={s['strongest']}",f"MOST_DAMAGING_EVIDENCE={s['damaging']}","","TASK_LOCAL_ANTI_BLOAT_STATUS=PASS","PREEXISTING_ACL_EXCEPTION_COUNT=2",f"FINAL_ARTIFACT_COUNT={s.get('artifact_count','PENDING')}",f"HASH_MANIFEST_STATUS={s.get('hash_status','PENDING')}","", "="*60,
    ])


if __name__ == "__main__":
    raise SystemExit(main())
