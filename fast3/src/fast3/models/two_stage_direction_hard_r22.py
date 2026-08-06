"""Frozen FAST3 R4 direct-versus-two-stage direction study.

This is intentionally a narrow, artifact-driven study runner.  It accepts an
already labelled R3 cohort, never derives a feature from a future path, and
does not select models or tune any parameter.  Files written by this module
are always beneath caller supplied external roots.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, brier_score_loss,
                             precision_score, recall_score, roc_auc_score)


UP, DOWN, NO_EVENT, AMBIGUOUS = "UP_FIRST", "DOWN_FIRST", "NO_EVENT", "AMBIGUOUS"
EVENT_LABELS = (UP, DOWN)
INTERACTIONS = ("nine_turn_x_realized_volatility", "nine_turn_x_vix_level", "nine_turn_x_vwap_distance")
SEEDS = {"development": (104729, 130363, 155921),
         "internal_holdout": (104729, 130363, 155921, 196613, 262147)}
MODEL_PARAMETERS = {"max_iter": 100, "learning_rate": 0.08, "max_leaf_nodes": 7,
                    "l2_regularization": 1.0}


class R4ContractError(RuntimeError):
    """Raised for a fail-closed R4 contract violation."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def stable_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    def safe(item: Any) -> Any:
        if isinstance(item, dict): return {str(key): safe(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)): return [safe(value) for value in item]
        if isinstance(item, (float, np.floating)):
            return float(item) if np.isfinite(item) else None
        if isinstance(item, (np.integer,)): return int(item)
        if isinstance(item, (pd.Timestamp,)): return item.isoformat()
        return item
    path.write_text(json.dumps(safe(value), indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def not_run(reason: str) -> dict[str, Any]:
    return {"status": "NOT_RUN", "reason": reason, "historical_status": "NON_PROSPECTIVE"}


def _required(mapping: dict[str, Any], key: str, expected: Any) -> None:
    if mapping.get(key) != expected:
        raise R4ContractError(f"SOURCE_FREEZE_INVALID:{key}")


def validate_source_freeze(source_r3_root: Path, source_r3_audit_root: Path, limits: dict[str, Any]) -> dict[str, Any]:
    """Validate the fixed R3 evidence and return the exact ordered feature freeze."""
    summary_path = source_r3_root / "fast3_event_factor_r3_summary.json"
    model_path = source_r3_root / "FAST3_MODEL_FREEZE.json"
    audit_path = source_r3_audit_root / "fast3_r3_post_audit_summary.json"
    if not all(path.is_file() for path in (summary_path, model_path, audit_path)):
        raise R4ContractError("SOURCE_FREEZE_ARTIFACT_MISSING")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    source = limits["source_freeze"]
    # R24 may only consume a newly frozen R3 rebuild.  The result identities
    # below are semantic contract checks; run IDs are intentionally fresh.
    if not isinstance(summary.get("RUN_ID"), str) or not summary["RUN_ID"]:
        raise R4ContractError("SOURCE_FREEZE_INVALID:RUN_ID")
    _required(summary, "FINAL_STATUS", source["r3_expected_status"])
    _required(summary, "FINAL_DECISION", source["r3_expected_decision"])
    _required(summary, "BEST_MODEL_NAME", source["r3_expected_best_model"])
    _required(summary, "STABLE_FACTOR_COLUMN_COUNT", source["r3_expected_stable_feature_count"])
    if not isinstance(audit.get("AUDIT_RUN_ID"), str) or not audit["AUDIT_RUN_ID"]:
        raise R4ContractError("SOURCE_FREEZE_INVALID:AUDIT_RUN_ID")
    _required(audit, "SOURCE_R3_RUN_ID", summary["RUN_ID"])
    _required(audit, "FINAL_DECISION", source["audit_expected_decision"])
    _required(audit, "UNIQUE_PRIMARY_TRADE_COUNT", source["audit_expected_unique_primary_trades"])
    features = model.get("frozen_columns")
    if not isinstance(features, list) or len(features) != 20 or len(set(features)) != 20:
        raise R4ContractError("SOURCE_FREEZE_FEATURES_NOT_EXACTLY_20")
    return {"r3_summary_hash": file_hash(summary_path), "r3_model_freeze_hash": file_hash(model_path),
            "r3_audit_hash": file_hash(audit_path), "features": features,
            "interactions": list(INTERACTIONS), "source_r3_decision": summary["FINAL_DECISION"],
            "source_r3_run_id": summary["RUN_ID"], "source_r3_audit_decision": audit["FINAL_DECISION"]}


def _column(frame: pd.DataFrame, options: Iterable[str], name: str) -> str:
    for item in options:
        if item in frame.columns:
            return item
    raise R4ContractError(f"DATA_REQUIRED_COLUMN_MISSING:{name}")


def _interaction_frame(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    x = frame.loc[:, features].astype(float).copy()
    # These are fixed transformations and deliberately not candidate features.
    bases = (("nine_5m_signed__level", "realized_vol_60m__level"),
             ("nine_5m_signed__level", "vix_level__level"),
             ("nine_5m_signed__level", "vwap_distance__level"))
    for name, (left, right) in zip(INTERACTIONS, bases):
        if left not in frame or right not in frame:
            raise R4ContractError(f"FROZEN_INTERACTION_SOURCE_MISSING:{name}")
        x[name] = pd.to_numeric(frame[left], errors="raise") * pd.to_numeric(frame[right], errors="raise")
    return x


def prepare_cohort(raw: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Select only permitted inputs/outcomes and fail closed on temporal leakage."""
    label_col = _column(raw, ("label", "future_label"), "label")
    time_col = _column(raw, ("decision_timestamp_et", "timestamp_et", "entry_timestamp_et"), "decision_timestamp")
    horizon_col = _column(raw, ("horizon_timestamp_et", "label_end_timestamp_et"), "label_end_timestamp")
    symbol_col = _column(raw, ("underlying", "underlying_symbol"), "underlying")
    required = set(features) | {label_col, time_col, horizon_col, symbol_col}
    missing = required - set(raw.columns)
    if missing:
        raise R4ContractError(f"DATA_FROZEN_FEATURE_OR_LABEL_MISSING:{sorted(missing)}")
    x = raw.copy()
    x["decision_timestamp_et"] = pd.to_datetime(x[time_col], errors="raise", utc=True)
    x["label_end_timestamp_et"] = pd.to_datetime(x[horizon_col], errors="raise", utc=True)
    if (x["label_end_timestamp_et"] < x["decision_timestamp_et"] + pd.Timedelta(hours=24)).any():
        raise R4ContractError("LABEL_HORIZON_SHORTER_THAN_24H")
    availability = next((c for c in ("feature_available_at_et", "feature_timestamp_et") if c in x), None)
    if availability:
        available = pd.to_datetime(x[availability], errors="raise", utc=True)
        if (available > x["decision_timestamp_et"]).any():
            raise R4ContractError("FEATURE_NOT_AVAILABLE_AT_DECISION")
    x["label"] = x[label_col].astype(str)
    x = x.loc[x.label.isin((UP, DOWN, NO_EVENT))].copy()
    if x.empty:
        raise R4ContractError("NO_NON_AMBIGUOUS_ROWS")
    x["underlying"] = x[symbol_col].astype(str)
    if not x.underlying.isin(("QQQ", "SOXX")).all():
        raise R4ContractError("UNSUPPORTED_UNDERLYING")
    x["event_id"] = x.get("event_id", x.underlying + "|" + x.decision_timestamp_et.astype(str)).astype(str)
    x["era"] = x.get("era", x.decision_timestamp_et.dt.year).astype(str)
    x["uniqueness_weight"] = pd.to_numeric(x.get("uniqueness_weight", 1.0), errors="coerce").fillna(1.0).clip(lower=0.0)
    if (x.uniqueness_weight <= 0).all():
        raise R4ContractError("INVALID_UNIQUENESS_WEIGHTS")
    x = x.sort_values(["decision_timestamp_et", "underlying", "event_id"], kind="mergesort").drop_duplicates(
        ["underlying", "decision_timestamp_et"], keep="first").reset_index(drop=True)
    return x


def deterministic_schedule(cohort: pd.DataFrame, *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Freeze eight 60-day observed blocks with at least five calendar days between them."""
    if existing is not None:
        expected = stable_hash({k: v for k, v in existing.items() if k != "schedule_hash"})
        if existing.get("schedule_hash") != expected:
            raise R4ContractError("RANDOM_BLOCK_SCHEDULE_HASH_INVALID")
        return existing
    dates = pd.DatetimeIndex(cohort.decision_timestamp_et.dt.normalize().unique()).sort_values()
    if len(dates) == 0:
        raise R4ContractError("NO_OBSERVED_INTERVALS")
    candidates: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    # The first block must itself have a strictly earlier expanding training
    # window after the fixed 24 h purge and 24 h embargo.
    cursor = dates.min() + pd.Timedelta(days=65)
    final = dates.max()
    while cursor + pd.Timedelta(days=59) <= final:
        end = cursor + pd.Timedelta(days=59, hours=23, minutes=59, seconds=59)
        if ((cohort.decision_timestamp_et >= cursor) & (cohort.decision_timestamp_et <= end)).any():
            candidates.append((cursor, end))
        cursor += pd.Timedelta(days=65)
    if len(candidates) < 8:
        raise R4ContractError("INSUFFICIENT_OBSERVED_INTERVALS_FOR_EIGHT_BLOCKS")
    rng = np.random.default_rng(20260803)
    chosen = sorted(rng.choice(len(candidates), size=8, replace=False).tolist())
    blocks = []
    for index, candidate_index in enumerate(chosen):
        start, end = candidates[candidate_index]
        blocks.append({"block_id": f"{'DEV' if index < 4 else 'HOLDOUT'}_{index + 1:02d}",
                       "phase": "development" if index < 4 else "internal_holdout",
                       "start": start.isoformat(), "end": end.isoformat(), "candidate_index": candidate_index})
    output = {"master_seed": 20260803, "block_length_calendar_days": 60,
              "minimum_gap_calendar_days": 5, "historical_status": "NON_PROSPECTIVE", "blocks": blocks}
    output["schedule_hash"] = stable_hash(output)
    return output


def block_rows(cohort: pd.DataFrame, block: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    start, end = pd.Timestamp(block["start"]), pd.Timestamp(block["end"])
    test = cohort.loc[(cohort.decision_timestamp_et >= start) & (cohort.decision_timestamp_et <= end)].copy()
    # Expanding past-only training; 24 h purge and 24 h embargo before test start.
    cutoff = start - pd.Timedelta(hours=48)
    train = cohort.loc[cohort.label_end_timestamp_et < cutoff].copy()
    if train.empty or test.empty:
        raise R4ContractError(f"EMPTY_PURGED_BLOCK:{block['block_id']}")
    if train.decision_timestamp_et.max() >= start - pd.Timedelta(hours=24):
        raise R4ContractError("PURGE_EMBARGO_INVARIANT_FAILED")
    return train, test


@dataclass
class FoldPreprocessor:
    columns: list[str]
    medians: dict[str, float]

    @classmethod
    def fit(cls, frame: pd.DataFrame, features: list[str]) -> "FoldPreprocessor":
        values = _interaction_frame(frame, features)
        medians = values.median(axis=0, numeric_only=True).fillna(0.0).to_dict()
        return cls(list(values.columns), {key: float(value) for key, value in medians.items()})

    def transform(self, frame: pd.DataFrame, features: list[str]) -> np.ndarray:
        values = _interaction_frame(frame, features).loc[:, self.columns].replace([np.inf, -np.inf], np.nan)
        return values.fillna(self.medians).to_numpy(dtype=float)


def training_weights(train: pd.DataFrame, target: pd.Series) -> np.ndarray:
    """Frozen uniqueness × fold-only class × fold-only era weights."""
    class_weight = target.map(len(target) / target.value_counts()).astype(float)
    era_weight = train.era.map(len(train) / train.era.value_counts()).astype(float)
    return (train.uniqueness_weight.astype(float) * class_weight * era_weight).to_numpy(dtype=float)


def _model(seed: int):
    return HistGradientBoostingClassifier(random_state=int(seed), **MODEL_PARAMETERS)


def _probability(model: Any, x: np.ndarray, target: Any) -> np.ndarray:
    classes = list(model.classes_)
    return model.predict_proba(x)[:, classes.index(target)] if target in classes else np.zeros(len(x), dtype=float)


def score_architecture(train: pd.DataFrame, test: pd.DataFrame, features: list[str], seed: int, architecture: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    preprocess = FoldPreprocessor.fit(train, features)
    x_train, x_test = preprocess.transform(train, features), preprocess.transform(test, features)
    if architecture == "direct":
        target = train.label
        model: Any = _model(seed) if target.nunique() > 1 else DummyClassifier(strategy="prior")
        model.fit(x_train, target, sample_weight=training_weights(train, target))
        up, down = _probability(model, x_test, UP), _probability(model, x_test, DOWN)
        artifact = {"direct": model}
    elif architecture == "two_stage":
        opportunity = train.label.isin(EVENT_LABELS).astype(int)
        stage1: Any = _model(seed) if opportunity.nunique() > 1 else DummyClassifier(strategy="prior")
        stage1.fit(x_train, opportunity, sample_weight=training_weights(train, opportunity))
        events = train.loc[train.label.isin(EVENT_LABELS)].copy()
        if events.label.nunique() > 1:
            stage2: Any = _model(seed)
            stage2.fit(preprocess.transform(events, features), events.label, sample_weight=training_weights(events, events.label))
        else:
            stage2 = DummyClassifier(strategy="prior").fit(preprocess.transform(events, features), events.label)
        event_p = _probability(stage1, x_test, 1)
        up = event_p * _probability(stage2, x_test, UP)
        down = event_p * _probability(stage2, x_test, DOWN)
        artifact = {"stage1": stage1, "stage2": stage2}
    else:
        raise R4ContractError(f"UNKNOWN_ARCHITECTURE:{architecture}")
    result = test[["event_id", "decision_timestamp_et", "label_end_timestamp_et", "underlying", "label"]].copy()
    result["p_up"] = up
    result["p_down"] = down
    result["p_event"] = up + down
    result["predicted_label"] = np.where(up >= down, UP, DOWN)
    result["combined_score"] = np.maximum(up, down)
    for name in ("gross_return", "target_hit", "actual_exit_timestamp_et", "exit_timestamp_et"):
        if name in test:
            result[name] = test[name].to_numpy()
    artifact["preprocessor"] = preprocess
    return result, artifact


def metrics(predictions: pd.DataFrame) -> dict[str, float | int]:
    actual_event = predictions.label.isin(EVENT_LABELS).astype(int)
    event_p = predictions.p_event.to_numpy()
    event_hat = event_p >= 0.60
    hit = float(actual_event.loc[event_hat].mean()) if event_hat.any() else float("nan")
    base = float(actual_event.mean())
    event_rows = predictions.loc[actual_event.astype(bool)]
    def safe(metric, *args, **kwargs):
        try: return float(metric(*args, **kwargs))
        except ValueError: return float("nan")
    order = predictions.combined_score.rank(method="first", ascending=False)
    top = predictions.loc[order <= max(1, int(np.ceil(len(predictions) * .05)))]
    return {"event_hit_rate": hit, "event_lift": hit / base if base else float("nan"),
            "event_auroc": safe(roc_auc_score, actual_event, event_p), "event_brier": safe(brier_score_loss, actual_event, event_p),
            "conditional_direction_accuracy": safe(accuracy_score, event_rows.label, event_rows.predicted_label),
            "conditional_direction_balanced_accuracy": safe(balanced_accuracy_score, event_rows.label, event_rows.predicted_label),
            "up_recall": safe(recall_score, event_rows.label, event_rows.predicted_label, pos_label=UP, zero_division=0),
            "down_recall": safe(recall_score, event_rows.label, event_rows.predicted_label, pos_label=DOWN, zero_division=0),
            "up_precision": safe(precision_score, event_rows.label, event_rows.predicted_label, pos_label=UP, zero_division=0),
            "down_precision": safe(precision_score, event_rows.label, event_rows.predicted_label, pos_label=DOWN, zero_division=0),
            "end_to_end_exact_accuracy": safe(accuracy_score, predictions.label, np.where(event_hat, predictions.predicted_label, NO_EVENT)),
            "legacy_compatible_top5_lift": float(top.label.isin(EVENT_LABELS).mean()) / base if len(top) and base else float("nan"),
            "test_rows": int(len(predictions))}


def economics(predictions: pd.DataFrame, block_id: str) -> tuple[dict[str, Any], pd.DataFrame]:
    selected = predictions.loc[predictions.p_event.ge(.60)].copy()
    selected = selected.nlargest(max(1, int(np.ceil(len(predictions) * .05))), "combined_score", keep="first")
    selected["direction"] = selected.predicted_label
    selected["execution_etf"] = selected.underlying + "|" + selected.direction
    selected["execution_etf"] = selected.execution_etf.map({"QQQ|UP_FIRST": "TQQQ", "QQQ|DOWN_FIRST": "SQQQ", "SOXX|UP_FIRST": "SOXL", "SOXX|DOWN_FIRST": "SOXS"})
    gross = selected["gross_return"] if "gross_return" in selected else pd.Series(0.0, index=selected.index)
    target_hit = selected["target_hit"] if "target_hit" in selected else pd.Series(False, index=selected.index)
    selected["gross_return"] = pd.to_numeric(gross, errors="coerce").fillna(0.0)
    selected["target_hit"] = target_hit.fillna(False).astype(bool)
    selected["exit_timestamp_et"] = pd.to_datetime(selected.get("actual_exit_timestamp_et", selected.get("exit_timestamp_et", selected.label_end_timestamp_et)), utc=True)
    selected["block_id"] = block_id
    selected = selected.sort_values(["decision_timestamp_et", "combined_score", "event_id"], ascending=[True, False, True], kind="mergesort")
    accepted: list[dict[str, Any]] = []
    active_exit: pd.Timestamp | None = None
    seen: set[str] = set()
    for item in selected.to_dict("records"):
        if item["event_id"] in seen or (active_exit is not None and item["decision_timestamp_et"] < active_exit):
            continue
        seen.add(item["event_id"]); active_exit = item["exit_timestamp_et"]
        accepted.append(item)
    trades = pd.DataFrame(accepted)
    if trades.empty:
        return {"accepted_records": int(len(selected)), "unique_primary_trades": 0, "target_hit_rate": float("nan"),
                "mean_net_10bps": float("nan"), "median_net_10bps": float("nan"), "mean_net_20bps": float("nan"),
                "median_net_20bps": float("nan"), "positive_trade_ratio": float("nan"), "max_drawdown": float("nan"),
                "remove_best_one_percent_mean_net_10bps": float("nan"), "maximum_single_block_positive_pnl_contribution": float("nan"),
                "maximum_single_etf_positive_pnl_contribution": float("nan"), "positive_pnl": 0.0,
                "positive_pnl_by_etf": {}, "daily_counts": {}, "monthly_counts": {}, "occupancy_days": 0}, trades
    trades["net10"] = trades.gross_return - .001
    trades["net20"] = trades.gross_return - .002
    equity = (1.0 + trades.net10).cumprod(); drawdown = equity / equity.cummax() - 1.0
    trim = trades.nlargest(max(1, int(np.ceil(len(trades) * .01))), "net10").index
    positive = trades.loc[trades.net10 > 0, "net10"]
    return {"accepted_records": int(len(selected)), "unique_primary_trades": int(len(trades)), "target_hit_rate": float(trades.target_hit.mean()),
            "mean_net_10bps": float(trades.net10.mean()), "median_net_10bps": float(trades.net10.median()),
            "mean_net_20bps": float(trades.net20.mean()), "median_net_20bps": float(trades.net20.median()),
            "positive_trade_ratio": float((trades.net10 > 0).mean()), "max_drawdown": float(drawdown.min()),
            "remove_best_one_percent_mean_net_10bps": float(trades.drop(index=trim).net10.mean()) if len(trades.drop(index=trim)) else float("nan"),
            "maximum_single_block_positive_pnl_contribution": float(trades.loc[trades.net10 > 0].groupby("block_id").net10.sum().max() / positive.sum()) if positive.sum() else 0.0,
            "maximum_single_etf_positive_pnl_contribution": float(trades.loc[trades.net10 > 0].groupby("execution_etf").net10.sum().max() / positive.sum()) if positive.sum() else 0.0,
            "positive_pnl": float(positive.sum()), "positive_pnl_by_etf": {str(k): float(v) for k, v in trades.loc[trades.net10 > 0].groupby("execution_etf").net10.sum().items()},
            "daily_counts": {str(k): int(v) for k, v in trades.groupby(trades.decision_timestamp_et.dt.date).size().items()},
            "monthly_counts": {str(k): int(v) for k, v in trades.groupby(trades.decision_timestamp_et.dt.tz_localize(None).dt.to_period("M")).size().items()},
            "occupancy_days": int((trades.exit_timestamp_et.dt.normalize() - trades.decision_timestamp_et.dt.normalize()).dt.days.clip(lower=0).sum())}, trades


def clustered_ci(values: list[float], seed: int = 20260803) -> tuple[float, float]:
    x = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if len(x) == 0: return float("nan"), float("nan")
    if len(x) == 1: return float(x[0]), float(x[0])
    rng = np.random.default_rng(seed)
    means = np.mean(rng.choice(x, size=(2000, len(x)), replace=True), axis=1)
    return float(np.quantile(means, .025)), float(np.quantile(means, .975))


def fixed_nulls(predictions: pd.DataFrame, train: pd.DataFrame, block_id: str, seed: int) -> dict[str, dict[str, Any]]:
    """Evaluate only the five preregistered nulls; no null is selected or tuned."""
    rng = np.random.default_rng(seed)
    prior_up = float((train.label == UP).mean())
    variants: dict[str, pd.DataFrame] = {}
    variants["ALWAYS_UP"] = predictions.assign(predicted_label=UP)
    variants["ALWAYS_DOWN"] = predictions.assign(predicted_label=DOWN)
    variants["TRAIN_PRIOR_RANDOM_DIRECTION"] = predictions.assign(predicted_label=np.where(rng.random(len(predictions)) < prior_up, UP, DOWN))
    variants["FIFTY_FIFTY_RANDOM_DIRECTION"] = predictions.assign(predicted_label=np.where(rng.random(len(predictions)) < .5, UP, DOWN))
    shuffled = predictions.copy(); shuffled["combined_score"] = rng.permutation(shuffled.combined_score.to_numpy())
    shuffled["p_event"] = rng.permutation(shuffled.p_event.to_numpy()); variants["SHUFFLED_SCORE_FULL_CANDIDATES"] = shuffled
    return {name: economics(frame, block_id)[0] for name, frame in variants.items()}


def gate(phase: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    by_block: dict[str, list[dict[str, Any]]] = {}
    for record in records: by_block.setdefault(record["block_id"], []).append(record)
    deltas = []
    for block_id, items in by_block.items():
        direct = np.mean([i["direct"]["conditional_direction_balanced_accuracy"] for i in items])
        two = np.mean([i["two_stage"]["conditional_direction_balanced_accuracy"] for i in items])
        event = np.mean([i["two_stage"]["event_lift"] - i["direct"]["event_lift"] for i in items])
        deltas.append({"block_id": block_id, "direction_delta": float(two - direct), "event_lift_delta": float(event),
                       "up_recall": float(np.mean([i["two_stage"]["up_recall"] for i in items])),
                       "down_recall": float(np.mean([i["two_stage"]["down_recall"] for i in items]))})
    direction = [x["direction_delta"] for x in deltas]; event = [x["event_lift_delta"] for x in deltas]
    econ_by_block: dict[str, dict[str, Any]] = {}
    for block_id, items in by_block.items():
        economics_for_block = [i["economic"] for i in items]
        econ_by_block[block_id] = {"unique_primary_trades": max(i["unique_primary_trades"] for i in economics_for_block),
            **{key: float(np.nanmean([i[key] for i in economics_for_block])) for key in ("mean_net_10bps", "median_net_10bps", "median_net_20bps", "remove_best_one_percent_mean_net_10bps")},
            "positive_pnl": float(np.nanmean([i["positive_pnl"] for i in economics_for_block]))}
    unique_trades = sum(v["unique_primary_trades"] for v in econ_by_block.values())
    result = {"phase": phase, "block_count": len(deltas), "block_deltas": deltas, "economic_by_block": econ_by_block,
              "unique_primary_trades": unique_trades, "direction_delta_mean": float(np.mean(direction)) if direction else float("nan"),
              "event_lift_delta_mean": float(np.mean(event)) if event else float("nan"),
              "direction_delta_ci": clustered_ci(direction), "event_lift_delta_ci": clustered_ci(event)}
    if phase == "development":
        result["pass"] = bool(len(deltas) == 4 and unique_trades >= 60 and result["event_lift_delta_mean"] >= -.05 and result["direction_delta_mean"] > .01 and
                              sum(v > 0 for v in direction) >= 3 and min(x["up_recall"] for x in deltas) >= .45 and min(x["down_recall"] for x in deltas) >= .45)
    else:
        learned_minus_null = []
        for block_id, items in by_block.items():
            learned = float(np.nanmean([i["economic"]["mean_net_10bps"] for i in items]))
            strongest = max(float(np.nanmean([i["nulls"][name]["mean_net_10bps"] for i in items])) for name in items[0]["nulls"])
            learned_minus_null.append(learned - strongest)
        result["learned_minus_strongest_null_net10_by_block"] = learned_minus_null
        result["learned_minus_strongest_null_net10_ci"] = clustered_ci(learned_minus_null)
        mean10 = float(np.nanmean([v["mean_net_10bps"] for v in econ_by_block.values()]))
        median10 = float(np.nanmedian([v["median_net_10bps"] for v in econ_by_block.values()]))
        median20 = float(np.nanmedian([v["median_net_20bps"] for v in econ_by_block.values()]))
        trimmed = float(np.nanmean([v["remove_best_one_percent_mean_net_10bps"] for v in econ_by_block.values()]))
        positive_by_block = {block: value["positive_pnl"] for block, value in econ_by_block.items()}
        total_positive = sum(positive_by_block.values())
        etf_positive: dict[str, float] = {}
        for item in records:
            for etf, pnl in item["economic"]["positive_pnl_by_etf"].items(): etf_positive[etf] = etf_positive.get(etf, 0.0) + pnl / len(SEEDS[phase])
        max_block = max(positive_by_block.values()) / total_positive if total_positive > 0 else float("inf")
        max_etf = max(etf_positive.values()) / sum(etf_positive.values()) if etf_positive and sum(etf_positive.values()) > 0 else float("inf")
        result.update({"mean_net_10bps": mean10, "median_net_10bps": median10, "median_net_20bps": median20,
                       "remove_best_one_percent_mean_net_10bps": trimmed, "maximum_single_block_positive_pnl_contribution": max_block,
                       "maximum_single_etf_positive_pnl_contribution": max_etf})
        result["pass"] = bool(len(deltas) == 4 and unique_trades >= 100 and result["direction_delta_ci"][0] > 0 and result["event_lift_delta_ci"][0] >= -.05 and
                              sum(v > 0 for v in direction) >= 3 and min(x["up_recall"] for x in deltas) >= .45 and min(x["down_recall"] for x in deltas) >= .45 and
                              mean10 > 0 and median10 > 0 and median20 >= 0 and trimmed > 0 and result["learned_minus_strongest_null_net10_ci"][0] > 0 and
                              max_block <= .35 and max_etf <= .5)
    return result


def checkpoint_fingerprint(source_freeze: dict[str, Any], schedule: dict[str, Any], phase: str, block_id: str, seed: int) -> str:
    return stable_hash({"source_freeze": source_freeze, "schedule_hash": schedule["schedule_hash"], "phase": phase,
                        "block_id": block_id, "seed": seed, "model_parameters": MODEL_PARAMETERS, "threshold": .60, "top_fraction": .05})


def run_checkpoint(train: pd.DataFrame, test: pd.DataFrame, features: list[str], phase: str, block_id: str, seed: int,
                   source_freeze: dict[str, Any], schedule: dict[str, Any], scratch_root: Path) -> dict[str, Any]:
    fingerprint = checkpoint_fingerprint(source_freeze, schedule, phase, block_id, seed)
    path = scratch_root / "checkpoints" / f"{phase}_{block_id}_{seed}.json"
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("fingerprint") == fingerprint and cached.get("status") == "COMPLETE": return cached
    direct, _ = score_architecture(train, test, features, seed, "direct")
    two_stage, _ = score_architecture(train, test, features, seed, "two_stage")
    direct_metrics, two_metrics = metrics(direct), metrics(two_stage)
    economic_metrics, _ = economics(two_stage, block_id)
    nulls = fixed_nulls(two_stage, train, block_id, seed)
    result = {"status": "COMPLETE", "historical_status": "NON_PROSPECTIVE", "fingerprint": fingerprint, "phase": phase,
              "block_id": block_id, "seed": seed, "direct": direct_metrics, "two_stage": two_metrics, "economic": economic_metrics,
              "nulls": nulls}
    write_json(path, result)
    return result


def run_phase(cohort: pd.DataFrame, schedule: dict[str, Any], source_freeze: dict[str, Any], scratch_root: Path, phase: str) -> list[dict[str, Any]]:
    output = []
    for block in (b for b in schedule["blocks"] if b["phase"] == phase):
        train, test = block_rows(cohort, block)
        for seed in SEEDS[phase]:
            output.append(run_checkpoint(train, test, source_freeze["features"], phase, block["block_id"], seed, source_freeze, schedule, scratch_root))
    return output


def diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    economic_records = [r["economic"] for r in records]
    daily: dict[str, int] = {}; monthly: dict[str, int] = {}
    for item in economic_records:
        for key, value in item["daily_counts"].items(): daily[key] = max(daily.get(key, 0), value)
        for key, value in item["monthly_counts"].items(): monthly[key] = monthly.get(key, 0) + value
    return {"historical_status": "NON_PROSPECTIVE", "economic_seed_records": economic_records,
            "daily_trade_counts_deduplicated_within_block": daily, "monthly_trade_counts": monthly,
            "occupancy_days_by_block_seed": {f"{r['block_id']}:{r['seed']}": r["economic"]["occupancy_days"] for r in records},
            "nulls": {f"{r['block_id']}:{r['seed']}": r["nulls"] for r in records},
            "repeated_seeds_not_independent_blocks": True}


def freeze_prospective_model(cohort: pd.DataFrame, features: list[str], seed: int, frozen_root: Path) -> dict[str, Any]:
    """Freeze exactly one post-gate model for future blind research shadow only."""
    preprocessor = FoldPreprocessor.fit(cohort, features)
    x = preprocessor.transform(cohort, features)
    event = cohort.label.isin(EVENT_LABELS).astype(int)
    stage1 = _model(seed).fit(x, event, sample_weight=training_weights(cohort, event))
    events = cohort.loc[cohort.label.isin(EVENT_LABELS)].copy()
    stage2 = _model(seed).fit(preprocessor.transform(events, features), events.label, sample_weight=training_weights(events, events.label))
    model_path = frozen_root / "FAST3_R4_PROSPECTIVE_SHADOW_MODEL.joblib"
    joblib.dump({"preprocessor": preprocessor, "stage1": stage1, "stage2": stage2, "features": features,
                 "interactions": list(INTERACTIONS), "parameters": MODEL_PARAMETERS}, model_path)
    return {"status": "FROZEN_FOR_FUTURE_BLIND_RESEARCH_SHADOW_ONLY", "historical_status": "NON_PROSPECTIVE",
            "model_path": str(model_path), "model_sha256": file_hash(model_path), "seed": seed,
            "broker_action_performed": False, "paper_order_performed": False, "live_order_performed": False}
