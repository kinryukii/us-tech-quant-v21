"""Exact-date, inference-only component functions for Unified staging.

Frozen model/rule files remain read-only.  These functions accept an already
materialized exact-date input contract and return normalized records; they do
not append legacy or authoritative history.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd


class ExactDateComponentError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_frozen_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ExactDateComponentError(f"FROZEN_MODULE_NOT_LOADABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _artifact(component: Mapping[str, Any], artifact_id: str) -> Mapping[str, Any]:
    matches = [row for row in component.get("artifacts", []) if row.get("artifact_id") == artifact_id]
    if len(matches) != 1:
        raise ExactDateComponentError(f"ARTIFACT_ID_NOT_UNIQUE:{artifact_id}")
    row = matches[0]
    path = Path(str(row["path"]))
    if not path.is_file() or file_sha256(path) != row.get("sha256"):
        raise ExactDateComponentError(f"FROZEN_ARTIFACT_SHA256_MISMATCH:{artifact_id}")
    return row


def _validate_component_identity(component: Mapping[str, Any]) -> None:
    artifacts = [
        {"artifact_id": row["artifact_id"], "path": Path(row["path"]).as_posix(), "sha256": row["sha256"]}
        for row in sorted(component.get("artifacts", []), key=lambda value: str(value["artifact_id"]))
    ]
    if not artifacts or _canonical_component_hash(artifacts) != component.get("composite_sha256"):
        raise ExactDateComponentError("FROZEN_COMPONENT_COMPOSITE_SHA256_MISMATCH")


def _canonical_component_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_exact_date_input(reference: Mapping[str, Any], target_date: str) -> dict[str, Any]:
    path = Path(str(reference.get("path", "")))
    if not path.is_file() or file_sha256(path) != reference.get("sha256"):
        raise ExactDateComponentError("EXACT_DATE_INPUT_SHA256_MISMATCH")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("target_date") != target_date:
        raise ExactDateComponentError("EXACT_DATE_INPUT_TARGET_MISMATCH")
    return payload


def write_staging_only(
    staging_directory: Path,
    filename: str,
    payload: Mapping[str, Any],
    *,
    authoritative_roots: Sequence[Path] = (),
) -> Path:
    stage = staging_directory.resolve()
    for root in authoritative_roots:
        authority = root.resolve()
        if stage == authority or authority in stage.parents:
            raise ExactDateComponentError("AUTHORITATIVE_OUTPUT_PATH_FORBIDDEN")
    stage.mkdir(parents=True, exist_ok=True)
    final = stage / filename
    temporary = final.with_suffix(final.suffix + ".tmp")
    if final.exists() or temporary.exists():
        raise ExactDateComponentError("STAGING_OUTPUT_ALREADY_EXISTS")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, final)
    return final


def run_alpha_single_date(
    target_date: str,
    input_payload: Mapping[str, Any],
    component: Mapping[str, Any],
    *,
    model_loader: Callable[[Path], Any] = joblib.load,
    module_loader: Callable[[Path, str], Any] = load_frozen_module,
) -> tuple[dict[str, Any], ...]:
    _validate_component_identity(component)
    if input_payload.get("target_date") != target_date:
        raise ExactDateComponentError("ALPHA_EXACT_DATE_REQUIRED")
    model_ref = _artifact(component, "model")
    source_ref = _artifact(component, "source")
    contract_ref = _artifact(component, "frozen_contracts")
    source = module_loader(Path(str(source_ref["path"])), "a2_frozen_exact_date_api")
    frame = pd.DataFrame(input_payload.get("feature_rows", []))
    required = {"security_id", "ticker", *source.FEATURE_COLUMNS}
    if frame.empty or required - set(frame.columns):
        raise ExactDateComponentError("ALPHA_FEATURE_CONTRACT_INCOMPLETE")
    if frame.security_id.astype(str).duplicated().any():
        raise ExactDateComponentError("ALPHA_SECURITY_ID_DUPLICATE")
    frame["signal_date"] = pd.Timestamp(target_date)
    model = model_loader(Path(str(model_ref["path"])))
    score = np.asarray(model.predict(frame.loc[:, source.FEATURE_COLUMNS].to_numpy(dtype=float)), dtype=float)
    if len(score) != len(frame) or not np.isfinite(score).all():
        raise ExactDateComponentError("ALPHA_PREDICTION_INVALID")
    frame["score"] = score
    frame["rank"] = source._prediction_rank(frame, "score")
    frozen_contract = json.loads(Path(str(contract_ref["path"])).read_text(encoding="utf-8"))
    top_n = int(frozen_contract["TOP_N"])
    if len(frame) < top_n:
        raise ExactDateComponentError("ALPHA_UNIVERSE_BELOW_FROZEN_TOP_N")
    frame["raw_target_weight"] = np.where(frame["rank"].le(top_n), 1.0 / top_n, 0.0)
    records = []
    for row in frame.sort_values(["rank", "ticker"], kind="mergesort").itertuples(index=False):
        records.append({
            "target_date": target_date,
            "security_id": str(row.security_id),
            "ticker": str(row.ticker).upper(),
            "rank": int(row.rank),
            "score": float(row.score),
            "raw_target_weight": float(row.raw_target_weight),
            "model_id": str(component["model_id"]),
            "universe_id": str(input_payload.get("universe_id", "UNKNOWN")),
            "vintage_id": str(input_payload.get("vintage_id", "UNKNOWN")),
        })
    return tuple(records)


def _risk_rule(preregistration: Mapping[str, Any]) -> tuple[float, float]:
    rule = preregistration["preregistered_payload"]["economic_shadow"]["rule"]
    keys = [key for key in rule if key.startswith("risk_percentile_at_least_")]
    if len(keys) != 1:
        raise ExactDateComponentError("R6_FROZEN_THRESHOLD_RULE_INVALID")
    threshold = float(keys[0].removeprefix("risk_percentile_at_least_")) / 100.0
    return threshold, float(rule[keys[0]])


def run_risk_single_date(
    target_date: str,
    input_payload: Mapping[str, Any],
    component: Mapping[str, Any],
    alpha_records: Sequence[Mapping[str, Any]],
    run_id: str,
    *,
    artifact_loader: Callable[[Path], Any] = joblib.load,
) -> tuple[dict[str, Any], ...]:
    _validate_component_identity(component)
    if input_payload.get("target_date") != target_date:
        raise ExactDateComponentError("RISK_EXACT_DATE_REQUIRED")
    if input_payload.get("input_alpha_run_id") != run_id:
        raise ExactDateComponentError("RISK_ALPHA_LINEAGE_MISMATCH")
    selected = {str(row["security_id"]): row for row in alpha_records if float(row["raw_target_weight"]) > 0}
    frame = pd.DataFrame(input_payload.get("feature_rows", []))
    if frame.empty or set(frame.security_id.astype(str)) != set(selected):
        raise ExactDateComponentError("RISK_ALPHA_SECURITY_ALIGNMENT_MISMATCH")
    model_ref = _artifact(component, "model")
    prereg_ref = _artifact(component, "r11_preregistration")
    deploy = artifact_loader(Path(str(model_ref["path"])))
    features = list(deploy["features"])
    if set(features) - set(frame.columns) or frame[features].isna().any().any():
        raise ExactDateComponentError("RISK_FEATURE_CONTRACT_INCOMPLETE")
    probability = np.asarray(deploy["model"].predict_proba(frame[features])[:, 1], dtype=float)
    if len(probability) != len(frame) or not np.isfinite(probability).all() or ((probability < 0) | (probability > 1)).any():
        raise ExactDateComponentError("RISK_PROBABILITY_INVALID")
    reference = np.asarray(deploy["reference_scores_sorted"], dtype=float)
    if not len(reference) or not np.isfinite(reference).all():
        raise ExactDateComponentError("RISK_REFERENCE_DISTRIBUTION_INVALID")
    percentile = np.searchsorted(reference, probability, side="right") / len(reference)
    prereg = json.loads(Path(str(prereg_ref["path"])).read_text(encoding="utf-8"))
    threshold, high_multiplier = _risk_rule(prereg)
    records = []
    for index, row in frame.reset_index(drop=True).iterrows():
        pct = float(percentile[index])
        records.append({
            "target_date": target_date,
            "security_id": str(row.security_id),
            "ticker": str(row.ticker).upper(),
            "risk_score": float(probability[index]),
            "risk_percentile": pct,
            "risk_bucket": "HIGH" if pct >= threshold else "NORMAL",
            "risk_action_or_multiplier": high_multiplier if pct >= threshold else 1.0,
            "risk_model_id": str(component["model_id"]),
        })
    return tuple(records)


def run_execution_single_date(
    target_date: str,
    input_payload: Mapping[str, Any],
    component: Mapping[str, Any],
    alpha_records: Sequence[Mapping[str, Any]],
    run_id: str,
    *,
    module_loader: Callable[[Path, str], Any] = load_frozen_module,
) -> tuple[dict[str, Any], ...]:
    _validate_component_identity(component)
    if input_payload.get("target_date") != target_date:
        raise ExactDateComponentError("EXECUTION_EXACT_DATE_REQUIRED")
    if input_payload.get("input_alpha_run_id") != run_id or input_payload.get("input_risk_run_id") != run_id:
        raise ExactDateComponentError("EXECUTION_UPSTREAM_LINEAGE_MISMATCH")
    source_ref = _artifact(component, "source")
    frozen = module_loader(Path(str(source_ref["path"])), "e5_frozen_exact_date_api")
    previous_date = str(input_payload.get("previous_date", ""))
    if not previous_date or previous_date >= target_date:
        raise ExactDateComponentError("EXECUTION_PREVIOUS_DATE_INVALID")
    previous_rows = list(input_payload.get("previous_alpha_rows", []))
    previous_holdings = {str(value).upper() for value in input_payload.get("previous_executed_holdings", [])}
    if len(previous_holdings) != 20:
        raise ExactDateComponentError("EXECUTION_PREVIOUS_HOLDINGS_NOT_TOP20")
    current = pd.DataFrame(alpha_records)
    previous = pd.DataFrame(previous_rows)
    required = {"ticker", "rank"}
    if current.empty or previous.empty or required - set(current.columns) or required - set(previous.columns):
        raise ExactDateComponentError("EXECUTION_ALPHA_PANEL_INCOMPLETE")
    current_panel = pd.DataFrame({
        "signal_date": pd.Timestamp(target_date), "ticker": current.ticker.astype(str).str.upper(),
        "a2_rank": current["rank"].astype(float), "universe_size": float(len(current)),
    })
    previous_panel = pd.DataFrame({
        "signal_date": pd.Timestamp(previous_date), "ticker": previous.ticker.astype(str).str.upper(),
        "a2_rank": previous["rank"].astype(float), "universe_size": float(len(previous)),
    })
    prediction_panel = pd.concat([previous_panel, current_panel], ignore_index=True)
    current_wanted = set(current.loc[current.raw_target_weight.astype(float).gt(0), "ticker"].astype(str).str.upper())
    if len(current_wanted) != 20:
        raise ExactDateComponentError("EXECUTION_CURRENT_INTENDED_NOT_TOP20")
    intended = {pd.Timestamp(previous_date): previous_holdings, pd.Timestamp(target_date): current_wanted}
    targets, decisions = frozen.build_executed_targets("E5_COMBINED_CONSERVATIVE", prediction_panel, intended)
    post = targets[pd.Timestamp(target_date)]
    suppressed_old = set(decisions.loc[decisions.suppressed.astype(bool), "old_name"].astype(str)) if len(decisions) else set()
    security_by_ticker = {str(row["ticker"]).upper(): str(row["security_id"]) for row in alpha_records}
    records = []
    for ticker, weight in sorted(post.items()):
        if ticker not in security_by_ticker:
            raise ExactDateComponentError("EXECUTION_SECURITY_NOT_IN_CURRENT_ALPHA_UNIVERSE")
        if ticker in suppressed_old:
            action = "SUPPRESS_REPLACEMENT"
        elif ticker in previous_holdings:
            action = "HOLD"
        else:
            action = "ENTER"
        records.append({
            "target_date": target_date,
            "security_id": security_by_ticker[ticker],
            "ticker": ticker,
            "pre_execution_weight": 0.05 if ticker in previous_holdings else 0.0,
            "post_execution_weight": float(weight),
            "execution_action": action,
            "execution_overlay_id": str(component["model_id"]),
        })
    return tuple(records)
