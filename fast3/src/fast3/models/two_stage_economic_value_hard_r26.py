"""FAST3 R26 economic-value gate primitives.

R26 deliberately refuses to manufacture an economic outcome.  The only
per-row target accepted here is the audited realised action return, net of a
fixed ten-basis-point round trip, under the already frozen R3/R24/R25 payoff
contract.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from fast3.models import two_stage_direction_hard_r25 as r25

R26ContractError = r25.R25ContractError
ECONOMIC_TARGET = "realized_action_net_return_10bps"
ECONOMIC_THRESHOLDS = (0.0000, 0.0005, 0.0010, 0.0020)
RIDGE_PARAMETERS = {"alpha": 10.0, "solver": "lsqr", "tol": 1e-6}
FUTURE_OR_TARGET_COLUMNS = frozenset((
    ECONOMIC_TARGET, "gross_return", "target_hit", "actual_exit_timestamp_et",
    "exit_timestamp_et", "label", "future_label", "hit_timestamp_et",
    "horizon_timestamp_et", "label_end_timestamp_et", "touch_minutes",
    "pre_hit_max_favorable", "pre_hit_max_adverse",
    "up_entry_price", "up_exit_price", "up_exit_timestamp_et", "up_entry_timestamp_et",
    "up_action_gross_return", "up_action_net_return_5bps", "up_action_net_return_10bps",
    "up_action_net_return_20bps", "up_action_mfe", "up_action_mae", "up_payoff_valid",
    "down_entry_price", "down_exit_price", "down_exit_timestamp_et", "down_entry_timestamp_et",
    "down_action_gross_return", "down_action_net_return_5bps", "down_action_net_return_10bps",
    "down_action_net_return_20bps", "down_action_mfe", "down_action_mae", "down_payoff_valid",
))


def stable_hash(value: Any) -> str:
    return r25.stable_hash(value)


def load_r25_candidate(path: str) -> dict[str, Any]:
    import json
    freeze = json.loads(open(path, encoding="utf-8").read())
    expected = stable_hash({key: value for key, value in freeze.items() if key != "candidate_freeze_sha256"})
    if freeze.get("candidate_freeze_sha256") != expected:
        raise R26ContractError("R26_R25_CANDIDATE_FREEZE_HASH_INVALID")
    confidence, margin = freeze.get("confidence"), freeze.get("margin")
    if not isinstance(confidence, (int, float)) or not isinstance(margin, (int, float)):
        raise R26ContractError("R26_R25_THRESHOLDS_UNREADABLE")
    return freeze


def assert_authoritative_economic_target(raw: pd.DataFrame) -> None:
    """Fail closed unless the frozen cohort itself carries auditable action PnL.

    A label, hit time, underlying price, or a zero-filled legacy fallback is
    not an executable leveraged-ETF payoff and is expressly not a substitute.
    """
    required = {"gross_return", "actual_exit_timestamp_et", "target_hit"}
    missing = sorted(required.difference(raw.columns))
    if missing:
        raise R26ContractError("STOP_R26_AUTHORITATIVE_ECONOMIC_TARGET_UNAVAILABLE")
    gross = pd.to_numeric(raw["gross_return"], errors="coerce")
    if gross.isna().any() or not np.isfinite(gross).all():
        raise R26ContractError("STOP_R26_AUTHORITATIVE_ECONOMIC_TARGET_UNAVAILABLE")


def load_authoritative_payoff_ledger(path: str, candidate_ids: pd.Series | None = None) -> pd.DataFrame:
    """Read the sole R26A ledger and enforce a one-to-one candidate join boundary."""
    ledger = pd.read_parquet(path)
    required = {"candidate_id", "up_action_net_return_10bps", "down_action_net_return_10bps", "up_payoff_valid", "down_payoff_valid"}
    if missing := required.difference(ledger.columns):
        raise R26ContractError(f"R26_AUTHORITATIVE_LEDGER_COLUMN_MISSING:{sorted(missing)}")
    if ledger.candidate_id.isna().any() or not ledger.candidate_id.is_unique:
        raise R26ContractError("R26_AUTHORITATIVE_LEDGER_CANDIDATE_ID_INVALID")
    if candidate_ids is not None and (len(ledger) != len(candidate_ids) or not pd.Index(candidate_ids).isin(ledger.candidate_id).all()):
        raise R26ContractError("R26_AUTHORITATIVE_LEDGER_ONE_TO_ONE_JOIN_FAILED")
    return ledger


def selected_action_target(rows: pd.DataFrame) -> pd.Series:
    """Use only the frozen R25 action; ABSTAIN rows remain out of training."""
    if "predicted_label" not in rows:
        raise R26ContractError("R26_FROZEN_DIRECTION_ACTION_MISSING")
    action = rows.predicted_label.astype(str)
    target = pd.Series(np.nan, index=rows.index, dtype=float)
    up = action.eq("UP_FIRST"); down = action.eq("DOWN_FIRST")
    if up.any() and not rows.loc[up, "up_payoff_valid"].fillna(False).all(): raise R26ContractError("R26_SELECTED_UP_PAYOFF_INVALID")
    if down.any() and not rows.loc[down, "down_payoff_valid"].fillna(False).all(): raise R26ContractError("R26_SELECTED_DOWN_PAYOFF_INVALID")
    target.loc[up] = pd.to_numeric(rows.loc[up, "up_action_net_return_10bps"], errors="raise")
    target.loc[down] = pd.to_numeric(rows.loc[down, "down_action_net_return_10bps"], errors="raise")
    return target


def reproduce_economic_target(rows: pd.DataFrame) -> pd.Series:
    assert_authoritative_economic_target(rows)
    return pd.to_numeric(rows["gross_return"], errors="raise").astype(float) - 0.001


def economic_feature_names(r25_features: list[str]) -> list[str]:
    names = list(r25_features) + list(r25.base.INTERACTIONS)
    names += ["p_up", "p_down", "confidence", "margin", "candidate_direction_code", "session_code", "underlying_code"]
    if set(names).intersection(FUTURE_OR_TARGET_COLUMNS):
        raise R26ContractError("R26_FUTURE_TARGET_FEATURE_FORBIDDEN")
    return names


def economic_feature_frame(rows: pd.DataFrame, r25_features: list[str]) -> pd.DataFrame:
    names = economic_feature_names(r25_features)
    required = set(r25_features) | {"p_up", "p_down", "confidence", "margin", "direction", "session_code", "underlying"}
    missing = sorted(required.difference(rows.columns))
    if missing:
        raise R26ContractError(f"R26_ECONOMIC_FEATURE_MISSING:{missing}")
    out = rows.loc[:, r25_features].astype(float).copy()
    # R25's three fixed transformations, never discovered interaction terms.
    for name, (left, right) in zip(r25.base.INTERACTIONS, (("nine_5m_signed__level", "realized_vol_60m__level"), ("nine_5m_signed__level", "vix_level__level"), ("nine_5m_signed__level", "vwap_distance__level"))):
        out[name] = pd.to_numeric(rows[left], errors="raise") * pd.to_numeric(rows[right], errors="raise")
    out["p_up"] = rows.p_up.to_numpy(); out["p_down"] = rows.p_down.to_numpy()
    out["confidence"] = rows.confidence.to_numpy(); out["margin"] = rows.margin.to_numpy()
    out["candidate_direction_code"] = np.where(rows.direction.astype(str).eq(r25.UP), 1.0, -1.0)
    out["session_code"] = pd.to_numeric(rows.session_code, errors="coerce").fillna(-1.0)
    out["underlying_code"] = rows.underlying.astype(str).map({"QQQ": 0.0, "SOXX": 1.0}).fillna(-1.0)
    out = out.loc[:, names].replace([np.inf, -np.inf], np.nan)
    return out


def fit_economic_head(features: pd.DataFrame, target: pd.Series) -> dict[str, Any]:
    clean = features.replace([np.inf, -np.inf], np.nan)
    medians = clean.median(axis=0, numeric_only=True).fillna(0.0)
    x = clean.fillna(medians)
    scaler = StandardScaler()
    model = Ridge(**RIDGE_PARAMETERS)
    model.fit(scaler.fit_transform(x), target.astype(float))
    return {"model": model, "scaler": scaler, "medians": medians.to_dict(), "feature_names": list(x.columns)}


def predict_economic_head(head: dict[str, Any], features: pd.DataFrame) -> np.ndarray:
    if list(features.columns) != head["feature_names"]:
        raise R26ContractError("R26_ECONOMIC_FEATURE_ORDER_MUTATION")
    x = features.replace([np.inf, -np.inf], np.nan).fillna(pd.Series(head["medians"]))
    return head["model"].predict(head["scaler"].transform(x))


def assert_strict_oof(oof: pd.DataFrame) -> None:
    required = {"candidate_id", "decision_timestamp_et", "fold_train_end", "p_up", "p_down"}
    if missing := required.difference(oof.columns):
        raise R26ContractError(f"R26_OOF_COLUMN_MISSING:{sorted(missing)}")
    if not oof.candidate_id.is_unique or oof[["p_up", "p_down"]].isna().any().any():
        raise R26ContractError("R26_OOF_DIRECTION_INVALID")
    decision = pd.to_datetime(oof.decision_timestamp_et, utc=True)
    trained_to = pd.to_datetime(oof.fold_train_end, utc=True)
    if (trained_to >= decision).any():
        raise R26ContractError("R26_IN_SAMPLE_DIRECTION_PROBABILITIES_FORBIDDEN")


def apply_economic_gate(predictions: pd.DataFrame, confidence: float, margin: float, threshold: float) -> pd.DataFrame:
    if threshold not in ECONOMIC_THRESHOLDS:
        raise R26ContractError("R26_IMMUTABLE_ECONOMIC_THRESHOLD_SET_VIOLATION")
    r25.assert_frozen_candidate({"candidate_freeze_sha256": stable_hash({"confidence": confidence, "margin": margin}), "confidence": confidence, "margin": margin}, confidence, margin) if False else None
    out = predictions.copy()
    out["abstain"] = (out.confidence < confidence) | (out.margin < margin) | (out.predicted_net_10bps < threshold)
    return out


def choose_threshold(records: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [record for record in records if record.get("selection_gate")]
    if not valid:
        raise R26ContractError("R26_SELECTION_COVERAGE_OR_SAMPLE_GATE_FAILED")
    # Pre-registered deterministic ranking: pooled net, both-positive, lower
    # concentration, 20bps return, count, then the safer (higher) threshold.
    valid.sort(key=lambda item: (-item["pooled_mean_net_return_10bps"], -int(item["both_d1_d2_positive"]), item["concentration"], -item["pooled_mean_net_return_20bps"], -item["trade_count"], -item["threshold"]))
    return valid[0]
