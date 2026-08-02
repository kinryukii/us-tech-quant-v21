"""Development-only, nested, two-stage FAST3 research pipeline.

This module deliberately produces fold-local research scores.  It does not train
or serialize a final model, choose an opportunity threshold, or access Confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.preprocessing import StandardScaler

from ..backtest.portfolio_contract import simulate_primary_portfolio
from ..common.contracts import ContractViolation, assert_confirmation_forbidden
from ..validation.nested_purged_walk_forward import NestedPurgedWalkForward


@dataclass
class FitCallLedger:
    """Auditable record of every fit; no fitted estimator is retained as a champion."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, stage: str, candidate: str, role: str, row_count: int, fold: str) -> None:
        self.entries.append({"stage": stage, "candidate": candidate, "role": role,
                             "row_count": int(row_count), "fold": fold})


def load_fast3_004_config(path: str | Path) -> dict[str, Any]:
    """Load and fail closed on the FAST3-004 safety and frozen-contract invariants."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("stage_id") != "FAST3-004" or raw.get("schema_version") != "1.0.0":
        raise ContractViolation("FAST3_004_CONFIG_ID_OR_SCHEMA_INVALID")
    if raw["frozen_executable_contract_sha256"] != "72186180b40e0c4b866d482fd35033597334c89ba3ef2bca33da5ad2d637eead":
        raise ContractViolation("FAST3_002_CONTRACT_HASH_MISMATCH")
    safety = raw["safety"]
    if not safety["development_only"] or safety["live_trading_allowed"] or safety["broker_action_allowed"]:
        raise ContractViolation("FAST3_004_RESEARCH_ONLY_VIOLATION")
    if safety["confirmation_read_count"] != 0 or safety["final_model_training_allowed"]:
        raise ContractViolation("FAST3_004_CONFIRMATION_OR_FINAL_TRAINING_FORBIDDEN")
    validation = raw["validation"]
    if validation["purge_minutes"] != 1440 or validation["embargo_minutes"] != 1440:
        raise ContractViolation("FAST3_002_PURGE_EMBARGO_MISMATCH")
    if not validation["random_kfold_forbidden"] or not validation["outer_test_selection_forbidden"]:
        raise ContractViolation("NESTED_WALK_FORWARD_REQUIRED")
    if raw["opportunity"]["eligibility_rule"] != {"kind": "score_gte", "threshold": 0.6, "selection": "pre_registered_not_optimized"}:
        raise ContractViolation("OPPORTUNITY_GATE_NOT_FROZEN")
    candidates = raw["opportunity"]["candidates"] + raw["direction"]["candidates"]
    if len(candidates) > raw["selection"]["candidate_limit"]:
        raise ContractViolation("CANDIDATE_LIMIT_EXCEEDED")
    return raw


def validate_pit_features(events: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Reject unavailable features and all Confirmation-time rows before fitting."""
    data = config["data"]
    required = {data["decision_timestamp_column"], data["label_end_timestamp_column"],
                data["feature_availability_column"], config["opportunity"]["target_column"],
                config["direction"]["target_column"]}
    feature_columns = {column for feature_set in config["features"]["sets"] for column in feature_set["columns"]}
    missing = (required | feature_columns) - set(events.columns)
    if missing:
        raise ContractViolation(f"FAST3_004_MISSING_COLUMNS:{sorted(missing)}")
    x = events.copy()
    decision = data["decision_timestamp_column"]
    available = data["feature_availability_column"]
    x[decision] = pd.to_datetime(x[decision], errors="raise")
    x[available] = pd.to_datetime(x[available], errors="raise")
    if x[list(feature_columns)].isna().any().any() or x[available].isna().any():
        raise ContractViolation("PIT_FEATURE_VALUE_OR_TIMESTAMP_MISSING")
    if (x[available] > x[decision]).any():
        raise ContractViolation("PIT_FEATURE_NOT_AVAILABLE_AT_DECISION")
    assert_confirmation_forbidden(x[decision], data["confirmation_start_et"])
    if (x[decision] > pd.Timestamp(data["development_end_et"])).any():
        raise ContractViolation("DEVELOPMENT_BOUNDARY_EXCEEDED")
    return x.sort_values(decision, kind="mergesort").reset_index(drop=True)


class TwoStageResearchPipeline:
    """Nested fold-local Stage A opportunity and Stage B direction evaluation."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        v = config["validation"]
        self.splitter = NestedPurgedWalkForward(v["purge_minutes"], v["embargo_minutes"], config["data"]["confirmation_start_et"])
        self.ledger = FitCallLedger()

    @property
    def feature_columns(self) -> list[str]:
        return [column for item in self.config["features"]["sets"] for column in item["columns"]]

    @property
    def gate_threshold(self) -> float:
        return float(self.config["opportunity"]["eligibility_rule"]["threshold"])

    def _model(self, candidate: str):
        seed = self.config["selection"]["fixed_seeds"][0]
        if candidate == "dummy_prior":
            return DummyClassifier(strategy="prior"), False
        if candidate == "logistic_regression":
            return LogisticRegression(max_iter=200, random_state=seed), True
        if candidate == "hist_gradient_boosting":
            return HistGradientBoostingClassifier(max_iter=50, learning_rate=0.05, max_leaf_nodes=7,
                                                   l2_regularization=1.0, random_state=seed), False
        raise ContractViolation(f"UNKNOWN_FAST3_004_CANDIDATE:{candidate}")

    def _fit_score(self, candidate: str, x_train: pd.DataFrame, y_train: pd.Series, x_score: pd.DataFrame,
                   *, stage: str, fold: str) -> np.ndarray:
        model, needs_scaler = self._model(candidate)
        if y_train.nunique() < 2 and candidate != "dummy_prior":
            model, needs_scaler, candidate = DummyClassifier(strategy="prior"), False, "dummy_prior_fallback"
        if needs_scaler:
            scaler = StandardScaler().fit(x_train)
            self.ledger.record(stage=stage, candidate=candidate, role="scaler.fit", row_count=len(x_train), fold=fold)
            x_train, x_score = scaler.transform(x_train), scaler.transform(x_score)
        model.fit(x_train, y_train)
        self.ledger.record(stage=stage, candidate=candidate, role="model.fit", row_count=len(y_train), fold=fold)
        return model.predict_proba(x_score)[:, 1]

    def _select_candidate(self, events: pd.DataFrame, target: str, candidates: list[str], stage: str, fold: str) -> str:
        scores: dict[str, list[float]] = {candidate: [] for candidate in candidates}
        for inner_no, inner in enumerate(self.splitter.inner_splits(events.reset_index(drop=True), self.config["validation"]["inner_splits"])):
            train, test = events.iloc[inner.train_index], events.iloc[inner.test_index]
            if train.empty or test.empty:
                continue
            for candidate in candidates:
                probability = self._fit_score(candidate, train[self.feature_columns], train[target], test[self.feature_columns],
                                               stage=stage, fold=f"{fold}.inner{inner_no}")
                prediction = (probability >= 0.5).astype(int)
                scores[candidate].append(float(balanced_accuracy_score(test[target], prediction)))
        ranked = [(float(np.mean(values)) if values else float("-inf"), -candidates.index(candidate), candidate)
                  for candidate, values in scores.items()]
        return max(ranked)[2]

    def _oof_opportunity_scores(self, events: pd.DataFrame, candidate: str, fold: str) -> pd.Series:
        values = pd.Series(np.nan, index=events.index, dtype=float)
        for inner_no, inner in enumerate(self.splitter.inner_splits(events.reset_index(drop=True), self.config["validation"]["inner_splits"])):
            train, test = events.iloc[inner.train_index], events.iloc[inner.test_index]
            if not train.empty and not test.empty:
                values.loc[test.index] = self._fit_score(candidate, train[self.feature_columns], train[self.config["opportunity"]["target_column"]],
                                                         test[self.feature_columns], stage="opportunity_oof", fold=f"{fold}.inner{inner_no}")
        return values

    def run_nested(self, events: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        """Return only outer-test scores; no global model or outer-test selection is performed."""
        x = validate_pit_features(events, self.config)
        self.splitter.assert_development_only(x)
        rows: list[pd.DataFrame] = []
        fold_summaries: list[dict[str, Any]] = []
        for outer_no, outer in enumerate(self.splitter.split_outer(x, self.config["validation"]["outer_splits"])):
            train, test = x.iloc[outer.train_index].copy(), x.iloc[outer.test_index].copy()
            if train.empty or test.empty:
                continue
            opportunity_candidate = self._select_candidate(train, self.config["opportunity"]["target_column"],
                                                            self.config["opportunity"]["candidates"], "opportunity_selection", f"outer{outer_no}")
            oof = self._oof_opportunity_scores(train, opportunity_candidate, f"outer{outer_no}")
            direction_train = train.loc[oof.ge(self.gate_threshold)].copy()
            direction_candidate = "dummy_prior"
            if len(direction_train) >= 2:
                direction_candidate = self._select_candidate(direction_train, self.config["direction"]["target_column"],
                                                              self.config["direction"]["candidates"], "direction_selection", f"outer{outer_no}")
            opportunity_score = self._fit_score(opportunity_candidate, train[self.feature_columns], train[self.config["opportunity"]["target_column"]],
                                                test[self.feature_columns], stage="opportunity_outer_test", fold=f"outer{outer_no}")
            eligible = opportunity_score >= self.gate_threshold
            direction_score = np.full(len(test), np.nan)
            if eligible.any() and len(direction_train):
                direction_score[eligible] = self._fit_score(direction_candidate, direction_train[self.feature_columns],
                                                            direction_train[self.config["direction"]["target_column"]], test.loc[eligible, self.feature_columns],
                                                            stage="direction_outer_test", fold=f"outer{outer_no}")
            result = test.copy()
            result["outer_fold"] = outer_no
            result["opportunity_candidate"] = opportunity_candidate
            result["direction_candidate"] = direction_candidate
            result["opportunity_score"] = opportunity_score
            result["opportunity_eligible"] = eligible
            result["direction_score_up"] = direction_score
            result["predicted_direction"] = np.where(direction_score >= 0.5, "UP", np.where(eligible, "DOWN", "ABSTAIN"))
            rows.append(result)
            fold_summaries.append({"outer_fold": outer_no, "outer_test_rows": len(test), "opportunity_candidate": opportunity_candidate,
                                   "direction_candidate": direction_candidate, "opportunity_eligible_rows": int(eligible.sum()),
                                   "direction_train_oof_rows": int(len(direction_train)),
                                   "selection_bias_exposure": {"candidate_count": len(self.config["opportunity"]["candidates"]) + len(self.config["direction"]["candidates"]),
                                                               "outer_test_used_for_selection": False}})
        return (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()), fold_summaries

    @staticmethod
    def enforce_single_account(selected_labels: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Delegate duplicate and overlap enforcement to the frozen FAST3-002 portfolio contract."""
        return simulate_primary_portfolio(selected_labels)

    @staticmethod
    def cost_surface_metrics(portfolio_labels: pd.DataFrame) -> dict[int, dict[str, float | int]]:
        """Report frozen 10/20 bps surfaces from already executable, accepted labels."""
        required = {"cost_scenario_bps_round_trip", "net_return", "trade_accepted"}
        if missing := required - set(portfolio_labels.columns):
            raise ContractViolation(f"FAST3_004_COST_SURFACE_FIELDS_MISSING:{sorted(missing)}")
        accepted = portfolio_labels.loc[portfolio_labels.trade_accepted].copy()
        output: dict[int, dict[str, float | int]] = {}
        for cost_bps in (10, 20):
            subset = accepted.loc[accepted.cost_scenario_bps_round_trip == cost_bps]
            output[cost_bps] = {"accepted_trade_count": int(len(subset)),
                                "mean_net_return": float(subset.net_return.mean()) if len(subset) else float("nan")}
        return output

    @staticmethod
    def concentration_diagnostics(scored: pd.DataFrame) -> dict[str, dict[str, int]]:
        if scored.empty:
            return {"symbol": {}, "month": {}, "regime": {}, "side": {}}
        selected = scored.loc[scored.opportunity_eligible].copy()
        month = pd.to_datetime(selected.decision_timestamp_et).dt.to_period("M").astype(str)
        def counts(column, fallback="UNSPECIFIED"):
            return selected[column].fillna(fallback).astype(str).value_counts().to_dict() if column in selected else {fallback: len(selected)}
        return {"symbol": counts("underlying_symbol"), "month": month.value_counts().to_dict(),
                "regime": counts("regime"), "side": counts("predicted_direction")}
