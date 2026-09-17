from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SUPPORT_FIELDS = [
    "decision_id",
    "as_of_date",
    "symbol",
    "model_id",
    "model_fit_id",
    "deployment_id",
    "data_snapshot_id",
    "feature_schema_hash",
    "universe_id",
    "eligibility_status",
    "prediction_status",
    "exclusion_reason",
    "fold_or_vintage_id_if_applicable",
]

PREDICTION_FIELDS = [
    "decision_id",
    "as_of_date",
    "symbol",
    "model_id",
    "model_fit_id",
    "deployment_id",
    "prediction_score",
]

POSITION_FIELDS = [
    "decision_id",
    "as_of_date",
    "symbol",
    "model_id",
    "model_fit_id",
    "deployment_id",
    "position_slot",
    "target_weight",
]


class ContractError(RuntimeError):
    """Raised when a fail-closed successor contract is violated."""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_bytes(path: Path | str, payload: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_json(path: Path | str, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def csv_bytes(fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> bytes:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return buffer.getvalue().encode("utf-8")


def load_config(path: Path | str) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_config(config)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    required = {
        "successor_control_model_id",
        "successor_model_spec_id",
        "parent_legacy_control_id",
        "successor_relation",
        "build_mode",
        "model_artifact_sha256",
        "train_rowset_hash",
        "max_train_label_end_date",
        "features",
        "fixed_hyperparameters",
        "universe_contract",
        "portfolio_contract",
        "cost_contract",
        "execution_contract",
        "outcome_columns_blocked",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ContractError(f"missing config fields: {missing}")
    if config["successor_control_model_id"] == config["parent_legacy_control_id"]:
        raise ContractError("legacy control ID reuse is forbidden")
    if config["successor_relation"] != "SEMANTIC_DESCENDANT_NOT_PROVEN_BYTE_IDENTICAL":
        raise ContractError("successor relation is not the fixed non-identical relation")
    if config["build_mode"] != "REUSE_HASH_VERIFIED_FITTED_ARTIFACT_AS_NEW_SUCCESSOR_DEPLOYMENT":
        raise ContractError("this implementation accepts only the resolved fixed reuse mode")
    if str(config["max_train_label_end_date"]) >= "2026-01-01":
        raise ContractError("label maturity failed")
    if len(config["features"]) != 32 or len(set(config["features"])) != 32:
        raise ContractError("feature schema must contain exactly 32 unique ordered features")
    if config.get("broker_action_allowed") is not False:
        raise ContractError("broker action must be false")
    if config.get("canonical_data_read_only") is not True:
        raise ContractError("canonical data must be read-only")
    if config["universe_contract"].get("expected_count") != 613:
        raise ContractError("frozen universe count must remain 613")
    if config["universe_contract"].get("completeness_gate") != "EXACT_613_SECURITY_SET_REQUIRED_NO_PARTIAL_FALLBACK":
        raise ContractError("partial-universe fallback is forbidden")


def derived_contracts(config: Mapping[str, Any]) -> dict[str, str]:
    feature_schema = [
        {"feature_name": name, "dtype": config["feature_dtype"], "transformation": config["preprocessing"]}
        for name in config["features"]
    ]
    model_spec = {
        "model_family": config["model_family"],
        "objective": config["objective"],
        "hyperparameters": config["fixed_hyperparameters"],
        "features": config["features"],
        "preprocessing": config["preprocessing"],
        "missing_value_semantics": config["missing_value_semantics"],
        "label_name": config["label_name"],
        "label_horizon_sessions": config["label_horizon_sessions"],
        "purge_sessions": config["purge_sessions"],
        "embargo_sessions": config["embargo_sessions"],
    }
    return {
        "feature_schema_hash": sha256_bytes(canonical_json_bytes(feature_schema)),
        "model_spec_hash": sha256_bytes(canonical_json_bytes(model_spec)),
        "portfolio_contract_hash": sha256_bytes(canonical_json_bytes(config["portfolio_contract"])),
        "cost_contract_hash": sha256_bytes(canonical_json_bytes(config["cost_contract"])),
        "execution_contract_hash": sha256_bytes(canonical_json_bytes(config["execution_contract"])),
    }


def successor_model_fit_id(config: Mapping[str, Any]) -> str:
    return "A2S1_" + str(config["model_artifact_sha256"])[:12].upper() + "_" + str(config["train_rowset_hash"])[:12].upper()


def successor_deployment_id(source_bundle_sha256: str, portfolio_contract_hash: str) -> str:
    return "A2S1_DEPLOY_" + source_bundle_sha256[:12].upper() + "_" + portfolio_contract_hash[:12].upper()


def validate_model_artifact(config: Mapping[str, Any], artifact_path: Path | str) -> Any:
    path = Path(artifact_path)
    if not path.is_file():
        raise ContractError(f"model artifact missing: {path}")
    actual = sha256_file(path)
    if actual != config["model_artifact_sha256"]:
        raise ContractError(f"model artifact hash mismatch: {actual}")
    import joblib

    model = joblib.load(path)
    if int(getattr(model, "n_features_in_", -1)) != len(config["features"]):
        raise ContractError("model feature count mismatch")
    expected = config["fixed_hyperparameters"]
    for name, value in expected.items():
        actual_value = getattr(model, name, None)
        if actual_value != value:
            raise ContractError(f"model hyperparameter mismatch: {name}={actual_value!r}")
    return model


def blocked_outcome_columns(columns: Iterable[str], config: Mapping[str, Any]) -> list[str]:
    blocked = {str(x).casefold() for x in config["outcome_columns_blocked"]}
    fixed_features = {str(x).casefold() for x in config["features"]}
    found = []
    for column in columns:
        normalized = str(column).strip().casefold()
        if normalized in fixed_features:
            continue
        if normalized in blocked or any(
            token in normalized for token in ("realized_return", "forward_return", "daily_return", "drawdown", "sharpe", "cagr", "maxdd")
        ):
            found.append(str(column))
    return sorted(found)


def validate_input_columns(columns: Iterable[str], config: Mapping[str, Any]) -> None:
    found = blocked_outcome_columns(columns, config)
    if found:
        raise ContractError(f"outcome-equivalent columns blocked: {found}")


def load_universe(path: Path | str, config: Mapping[str, Any]) -> tuple[list[dict[str, str]], str]:
    p = Path(path)
    if sha256_file(p) != config["universe_contract"]["members_file_sha256"]:
        raise ContractError("universe source hash mismatch")
    payload = json.loads(p.read_text(encoding="utf-8"))
    members = [
        {"security_id": str(row["security_id"]), "symbol": str(row["ticker"])} for row in payload["members"]
    ]
    if len(members) != config["universe_contract"]["expected_count"]:
        raise ContractError("universe cardinality mismatch")
    keys = [(row["security_id"], row["symbol"]) for row in members]
    if len(keys) != len(set(keys)):
        raise ContractError("duplicate universe member")
    normalized = "\n".join(f"{a}|{b}" for a, b in sorted(keys)) + "\n"
    return members, sha256_bytes(normalized.encode("utf-8"))


def _number(value: Any) -> float:
    if value is None or value == "":
        return math.nan
    return float(value)


def build_no_outcome_artifacts(
    *,
    config: Mapping[str, Any],
    model: Any,
    feature_rows: Sequence[Mapping[str, Any]],
    universe_members: Sequence[Mapping[str, str]],
    output_dir: Path | str,
    decision_id: str,
    as_of_date: str,
    data_snapshot_id: str,
    universe_hash: str,
    source_bundle_sha256: str,
    formal_decision: bool,
    classification: str,
) -> dict[str, Any]:
    validate_input_columns(feature_rows[0].keys() if feature_rows else [], config)
    by_symbol: dict[str, Mapping[str, Any]] = {}
    duplicates: list[str] = []
    for row in feature_rows:
        symbol = str(row.get("symbol") or row.get("ticker") or "").strip()
        if not symbol:
            raise ContractError("empty feature-row symbol")
        if symbol in by_symbol:
            duplicates.append(symbol)
        by_symbol[symbol] = row
    if duplicates:
        raise ContractError(f"duplicate feature-row symbols: {sorted(set(duplicates))}")

    contracts = derived_contracts(config)
    fit_id = successor_model_fit_id(config)
    deployment_id = successor_deployment_id(source_bundle_sha256, contracts["portfolio_contract_hash"])
    support_rows: list[dict[str, Any]] = []
    eligible_symbols: list[str] = []
    matrix: list[list[float]] = []
    for member in sorted(universe_members, key=lambda x: (x["symbol"], x.get("security_id", ""))):
        symbol = str(member["symbol"])
        row = by_symbol.get(symbol)
        if row is None:
            eligibility = "EXCLUDED"
            prediction_status = "NOT_PREDICTED"
            exclusion_reason = "MISSING_FEATURE_ROW"
        else:
            missing_columns = [name for name in config["features"] if name not in row]
            if missing_columns:
                eligibility = "EXCLUDED"
                prediction_status = "NOT_PREDICTED"
                exclusion_reason = "MISSING_FEATURE_COLUMNS:" + ",".join(missing_columns)
            else:
                eligibility = "ELIGIBLE"
                prediction_status = "PREDICTED"
                exclusion_reason = ""
                eligible_symbols.append(symbol)
                matrix.append([_number(row[name]) for name in config["features"]])
        support_rows.append(
            {
                "decision_id": decision_id,
                "as_of_date": as_of_date,
                "symbol": symbol,
                "model_id": config["successor_control_model_id"],
                "model_fit_id": fit_id,
                "deployment_id": deployment_id,
                "data_snapshot_id": data_snapshot_id,
                "feature_schema_hash": contracts["feature_schema_hash"],
                "universe_id": config["universe_contract"]["universe_id"],
                "eligibility_status": eligibility,
                "prediction_status": prediction_status,
                "exclusion_reason": exclusion_reason,
                "fold_or_vintage_id_if_applicable": "FULL_PRE2026_REUSED_ARTIFACT",
            }
        )
    complete = len(universe_members) == config["universe_contract"]["expected_count"] and len(eligible_symbols) == len(universe_members)
    if formal_decision and not complete:
        raise ContractError("formal decision blocked by incomplete 613-security universe")
    if formal_decision and len(eligible_symbols) < config["portfolio_contract"]["top_n"]:
        raise ContractError("formal decision has fewer eligible rows than TOP_N")

    import numpy as np

    scores = model.predict(np.asarray(matrix, dtype="float64")) if matrix else []
    prediction_rows = []
    for symbol, score in zip(eligible_symbols, scores):
        prediction_rows.append(
            {
                "decision_id": decision_id,
                "as_of_date": as_of_date,
                "symbol": symbol,
                "model_id": config["successor_control_model_id"],
                "model_fit_id": fit_id,
                "deployment_id": deployment_id,
                "prediction_score": format(float(score), ".17g"),
            }
        )
    prediction_rows.sort(key=lambda row: row["symbol"])
    ranked = sorted(prediction_rows, key=lambda row: (-float(row["prediction_score"]), row["symbol"]))
    selected = ranked[: min(config["portfolio_contract"]["top_n"], len(ranked))]
    denominator = config["portfolio_contract"]["top_n"] if formal_decision else max(1, len(selected))
    position_rows = [
        {
            "decision_id": decision_id,
            "as_of_date": as_of_date,
            "symbol": row["symbol"],
            "model_id": config["successor_control_model_id"],
            "model_fit_id": fit_id,
            "deployment_id": deployment_id,
            "position_slot": index + 1,
            "target_weight": format(1.0 / denominator, ".17g"),
        }
        for index, row in enumerate(selected)
    ]

    output = Path(output_dir)
    support_payload = csv_bytes(SUPPORT_FIELDS, support_rows)
    prediction_payload = csv_bytes(PREDICTION_FIELDS, prediction_rows)
    position_payload = csv_bytes(POSITION_FIELDS, position_rows)
    atomic_write_bytes(output / "model_native_support.csv", support_payload)
    atomic_write_bytes(output / "predictions.csv", prediction_payload)
    atomic_write_bytes(output / "position_decision.csv", position_payload)
    receipt = {
        "decision_id": decision_id,
        "as_of_date": as_of_date,
        "classification": classification,
        "formal_decision": formal_decision,
        "live_captured_prospective": False,
        "outcome_available": False,
        "broker_action_allowed": False,
        "model_id": config["successor_control_model_id"],
        "model_fit_id": fit_id,
        "deployment_id": deployment_id,
        "data_snapshot_id": data_snapshot_id,
        "universe_hash": universe_hash,
        "source_bundle_sha256": source_bundle_sha256,
        "native_support_hash": sha256_bytes(support_payload),
        "prediction_hash": sha256_bytes(prediction_payload),
        "position_decision_hash": sha256_bytes(position_payload),
        "portfolio_contract_hash": contracts["portfolio_contract_hash"],
        "support_row_count": len(support_rows),
        "prediction_row_count": len(prediction_rows),
        "position_row_count": len(position_rows),
        "completeness_gate_pass": complete,
    }
    atomic_write_json(output / "decision_receipt.json", receipt)
    return receipt


def append_hash_chain(chain_path: Path | str, entry: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(chain_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ContractError("forward hash-chain lock already exists") from exc
    os.close(fd)
    try:
        existing: list[dict[str, Any]] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    existing.append(json.loads(line))
        decision_id = str(entry["DECISION_ID"])
        same = [row for row in existing if row["DECISION_ID"] == decision_id]
        if same:
            comparison = {key: value for key, value in same[0].items() if key not in {"CHAIN_INDEX", "PREVIOUS_ENTRY_HASH", "ENTRY_HASH"}}
            if canonical_json_bytes(comparison) == canonical_json_bytes(dict(entry)):
                return same[0]
            raise ContractError("duplicate decision ID with conflicting content")
        previous = existing[-1]["ENTRY_HASH"] if existing else "GENESIS"
        row = {"CHAIN_INDEX": len(existing) + 1, "PREVIOUS_ENTRY_HASH": previous, **dict(entry)}
        row["ENTRY_HASH"] = sha256_bytes(canonical_json_bytes(row))
        payload = b"".join(canonical_json_bytes(item) for item in [*existing, row])
        atomic_write_bytes(path, payload)
        return row
    finally:
        lock.unlink(missing_ok=True)


def validate_hash_chain(path: Path | str) -> bool:
    previous = "GENESIS"
    for index, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        row = json.loads(line)
        actual = row.pop("ENTRY_HASH")
        if row["CHAIN_INDEX"] != index or row["PREVIOUS_ENTRY_HASH"] != previous:
            return False
        if sha256_bytes(canonical_json_bytes(row)) != actual:
            return False
        previous = actual
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifact", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    validate_model_artifact(config, args.artifact)
    print(json.dumps({"status": "PASS", "model_fit_id": successor_model_fit_id(config), **derived_contracts(config)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
