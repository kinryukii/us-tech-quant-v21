#!/usr/bin/env python
"""Minimal future-only, frozen R2-vs-R28.3 prediction ledger scorer."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import joblib
import pandas as pd


SOURCE = Path(r"D:\us-tech-quant")
DATA = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")
FROZEN = RESULTS / "frozen" / "fast3" / "r28_phase3_20260808T131135Z"
R2_FROZEN = RESULTS / "frozen" / "fast3" / "cleanroom_r2_20260808"
CANONICAL = DATA / "fast3" / "moomoo_24h_1m" / "canonical"
RUNTIME = RESULTS / "runtime" / "fast3" / "r28_prospective_dual_shadow_r1"
SCRATCH = RESULTS / "scratch" / "fast3" / "r28_prospective_dual_shadow_r1"
SEALED = RESULTS / "frozen" / "fast3" / "r28_prospective_dual_shadow_r1"
if str(SOURCE / "fast3" / "src") not in sys.path:
    sys.path.insert(0, str(SOURCE / "fast3" / "src"))


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _json_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def prospective_timestamp_allowed(candidate_timestamp_utc: str, registration_utc: str) -> bool:
    return _utc(candidate_timestamp_utc) > _utc(registration_utc)


def _registration() -> dict:
    return json.loads((FROZEN / "R28_PROSPECTIVE_SHADOW_REGISTRATION.json").read_text(encoding="utf-8"))


def _first_legal_timestamp(registration_utc: str) -> pd.Timestamp:
    from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as calendar

    registration = _utc(registration_utc)
    local = registration.tz_convert("America/New_York")
    holidays = calendar._holiday_dates(registration, registration + pd.Timedelta(days=14))
    for day in pd.date_range(local.normalize() + pd.Timedelta(days=1), periods=14, freq="D", tz="America/New_York"):
        if day.weekday() < 5 and day.date() not in holidays:
            return pd.Timestamp(f"{day.date().isoformat()} 09:30:00", tz="America/New_York").tz_convert("UTC")
    raise RuntimeError("R28_PROSPECTIVE_FROZEN_CALENDAR_NO_NEXT_SESSION")


def frozen_identity() -> dict:
    r2_manifest = json.loads((R2_FROZEN / "cleanroom_r2_freeze_manifest.json").read_text(encoding="utf-8"))
    r28_identity = json.loads((FROZEN / "R28_PHASE3_RESEARCH_IDENTITY.json").read_text(encoding="utf-8"))
    r2_models = {row["model"]: row for row in r2_manifest["models"]}
    r2 = {}
    for head in ("UP", "DOWN"):
        row = r2_models[f"{head}_HGB"]
        path = Path(row["path"])
        if not path.is_file() or _sha(path) != row["sha256"]:
            raise RuntimeError(f"R2_FROZEN_MODEL_HASH_MISMATCH:{head}")
        r2[head] = {"path": path, "sha256": row["sha256"], "threshold": r2_manifest["thresholds"][f"{head}_HGB_THRESHOLD"]}
    r28 = {}
    for head in ("UP", "DOWN"):
        path = FROZEN / "models" / f"R28_3_{head}_FINAL.joblib"
        expected = r28_identity["r28_model_sha256"][head]
        if not path.is_file() or _sha(path) != expected:
            raise RuntimeError(f"R28_FROZEN_MODEL_HASH_MISMATCH:{head}")
        r28[head] = {"path": path, "sha256": expected, "threshold": r28_identity["thresholds"][f"{head}_HGB_THRESHOLD"]}
    return {"r2": r2, "r28": r28, "r2_verified": True, "r28_verified": True,
            "baseline_features": tuple(r2_manifest["features"]), "r28_features": tuple(r28_identity["features"])}


def immutable_shadow_ledger(r2: pd.DataFrame, r28: pd.DataFrame, registration_utc: str, created_at: str) -> pd.DataFrame:
    """Freeze one common, outcome-blind row per model/candidate; never score history."""
    key = ["candidate_id", "head", "timestamp", "symbol"]
    required = set(key + ["research_identity", "model_role", "model_id", "model_sha256",
                          "feature_snapshot_hash", "probability", "threshold", "selected", "execution_eligible"])
    for name, frame in (("R2", r2), ("R28", r28)):
        if required.difference(frame.columns):
            raise ValueError(f"PROSPECTIVE_LEDGER_COLUMNS_MISSING:{name}")
        if frame.duplicated(key).any():
            raise ValueError(f"PROSPECTIVE_DUPLICATE_CANDIDATE:{name}")
        if not all(prospective_timestamp_allowed(str(value), registration_utc) for value in frame["timestamp"]):
            raise ValueError("PROSPECTIVE_HISTORICAL_BACKFILL_FORBIDDEN")
    if set(map(tuple, r2[key].to_numpy())) != set(map(tuple, r28[key].to_numpy())):
        raise ValueError("PROSPECTIVE_COMMON_UNIVERSE_MISMATCH")
    out = pd.concat([r2.copy(), r28.copy()], ignore_index=True)
    if any("outcome" in column.lower() or "payoff" in column.lower() for column in out.columns):
        raise ValueError("PROSPECTIVE_OUTCOME_FIELD_FORBIDDEN")
    out["created_at"] = created_at
    out["ledger_row_hash"] = [_json_hash(dict(zip(
        key + ["model_id", "model_sha256", "probability", "threshold", "selected"], row)))
        for row in out[key + ["model_id", "model_sha256", "probability", "threshold", "selected"]].to_numpy()]
    return out.sort_values(["timestamp", "symbol", "head", "model_role"], kind="mergesort").reset_index(drop=True)


def maturity_ready(ledger: pd.DataFrame, now_utc: str, label_horizon_hours: int = 24) -> pd.Series:
    now = _utc(now_utc)
    timestamp = pd.to_datetime(ledger["timestamp"], utc=True, errors="raise")
    return timestamp + pd.Timedelta(hours=label_horizon_hours) <= now


def _recent_paths(symbol: str) -> list[Path]:
    paths = sorted(CANONICAL.glob(f"symbol={symbol}/year=*/month=*/data.parquet"))
    if not paths:
        raise RuntimeError(f"R28_PROSPECTIVE_CANONICAL_SYMBOL_MISSING:{symbol}")
    return paths[-2:]


def _canonical_latest() -> pd.Timestamp:
    values = []
    for symbol in ("QQQ", "SOXX"):
        frame = pd.read_parquet(_recent_paths(symbol)[-1], columns=["timestamp_utc"])
        values.append(pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise").max())
    return min(values)


def common_prospective_input_universe(registration_utc: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return only rows complete for both frozen feature sets and explicit misses."""
    p2 = _load(SOURCE / "fast3" / "scripts" / "run" / "fast3_r28_phase2_fixed_training.py", "r28_p2_prospective")
    from fast3.r28_multisignal import R28_FEATURES, build_features, pit_audit

    complete, missing = [], []
    cutoff = max(_utc(registration_utc), _first_legal_timestamp(registration_utc))
    data = {symbol: p2.read_symbol(_recent_paths(symbol)) for symbol in ("QQQ", "SOXX")}
    for symbol, peer in (("QQQ", "SOXX"), ("SOXX", "QQQ")):
        base, _ = p2.R1.candidate_features(data[symbol], symbol, include_labels=False)
        base = base[pd.to_datetime(base["decision_timestamp_utc"], utc=True) >= cutoff].copy()
        new = build_features(data[symbol], data[peer])
        if not pit_audit(new.dropna(subset=list(R28_FEATURES)))["pit_pass"]:
            raise RuntimeError(f"R28_PROSPECTIVE_FEATURE_PIT_FAILURE:{symbol}")
        new = new.rename(columns={"timestamp_utc": "decision_timestamp_utc"})
        joined = base.merge(new[["decision_timestamp_utc", *R28_FEATURES]], on="decision_timestamp_utc", how="left",
                            validate="many_to_one")
        joined["candidate_id"] = (joined["underlying_symbol"].astype(str) + "|" + joined["direction"].astype(str)
                                  + "|" + joined["decision_timestamp_utc"].astype(str))
        absent = joined.loc[joined.loc[:, list(R28_FEATURES)].isna().any(axis=1)].copy()
        if not absent.empty:
            absent["missing_reason"] = "R28_3_FEATURE_WARMUP_OR_EXACT_PEER_TIMESTAMP_MISSING"
            missing.append(absent[["candidate_id", "underlying_symbol", "direction", "decision_timestamp_utc", "missing_reason"]])
        complete.append(joined.dropna(subset=list(R28_FEATURES)))
    common = pd.concat(complete, ignore_index=True) if complete else pd.DataFrame()
    diagnostics = pd.concat(missing, ignore_index=True) if missing else pd.DataFrame(
        columns=["candidate_id", "underlying_symbol", "direction", "decision_timestamp_utc", "missing_reason"])
    if not common.empty and common["candidate_id"].duplicated().any():
        raise RuntimeError("R28_PROSPECTIVE_COMMON_UNIVERSE_DUPLICATE")
    return common, diagnostics


def _score_rows(common: pd.DataFrame, identity: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    outputs = []
    for role, model_key, features, research_identity in (
        ("CHAMPION", "r2", identity["baseline_features"], "FAST3_CLEANROOM_R2"),
        ("CHALLENGER", "r28", identity["r28_features"], "FAST3_R28_3_CROSS_ASSET_FLOW"),
    ):
        for head in ("UP", "DOWN"):
            rows = common.loc[common["direction"].eq(head)].copy()
            if rows.empty:
                continue
            record = identity[model_key][head]
            model = joblib.load(record["path"])
            rows["probability"] = model.predict_proba(rows.loc[:, list(features)])[:, 1]
            rows["threshold"] = float(record["threshold"])
            rows["selected"] = rows["probability"] >= rows["threshold"]
            rows["research_identity"] = research_identity
            rows["model_role"] = role
            rows["model_id"] = f"{research_identity}_{head}_HGB_FINAL"
            rows["model_sha256"] = record["sha256"]
            rows["candidate_id"] = rows["candidate_id"].astype(str)
            rows["head"] = head
            rows["timestamp"] = rows["decision_timestamp_utc"]
            rows["symbol"] = rows["underlying_symbol"]
            rows["feature_snapshot_hash"] = [
                _json_hash({"features": list(features), "values": [str(value) for value in row]})
                for row in rows.loc[:, list(features)].to_numpy()
            ]
            rows["frozen_threshold"] = rows["threshold"]
            rows["execution_eligible"] = True
            rows["decision"] = rows["selected"].map({True: head, False: "NO_SIGNAL"})
            outputs.append(rows[["research_identity", "model_role", "model_id", "model_sha256", "candidate_id", "timestamp",
                                 "symbol", "head", "feature_snapshot_hash", "probability", "threshold", "frozen_threshold",
                                 "selected", "decision", "execution_eligible"]])
    r2 = pd.concat([x for x in outputs if x.model_role.iat[0] == "CHAMPION"], ignore_index=True)
    r28 = pd.concat([x for x in outputs if x.model_role.iat[0] == "CHALLENGER"], ignore_index=True)
    return r2, r28


def _existing_candidate_keys() -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for path in RUNTIME.rglob("*.parquet") if RUNTIME.is_dir() else []:
        frame = pd.read_parquet(path, columns=["model_role", "candidate_id", "head", "timestamp"])
        keys.update(map(tuple, frame[["model_role", "candidate_id", "head", "timestamp"]].astype(str).to_numpy()))
    return keys


def seal_prediction_ledger(ledger: pd.DataFrame) -> dict:
    if ledger.empty:
        raise ValueError("R28_PROSPECTIVE_EMPTY_LEDGER_CANNOT_SEAL")
    keys = set(map(tuple, ledger[["model_role", "candidate_id", "head", "timestamp"]].astype(str).to_numpy()))
    if keys.intersection(_existing_candidate_keys()):
        raise ValueError("PROSPECTIVE_DUPLICATE_CANDIDATE")
    created = _utc(ledger["created_at"].iat[0])
    token = created.strftime("%Y%m%dT%H%M%S%fZ")
    temporary = SCRATCH / f"{token}.parquet"
    destination = RUNTIME / f"day={created.strftime('%Y-%m-%d')}" / f"{token}.parquet"
    temporary.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_parquet(temporary, index=False)
    digest = _sha(temporary)
    os.replace(temporary, destination)
    sidecar = destination.with_suffix(destination.suffix + ".sha256")
    with sidecar.open("x", encoding="ascii") as handle:
        handle.write(digest + "\n")
    manifest = {"schema_version": "FAST3_R28_PROSPECTIVE_DUAL_LEDGER_R1", "ledger_path": str(destination),
                "ledger_sha256": digest, "row_count": int(len(ledger)),
                "min_timestamp": str(pd.to_datetime(ledger["timestamp"], utc=True).min()),
                "max_timestamp": str(pd.to_datetime(ledger["timestamp"], utc=True).max()),
                "model_sha256": {str(role): sorted(set(group.model_sha256)) for role, group in ledger.groupby("model_role")},
                "outcome_read_before_ledger_freeze": False}
    SEALED.mkdir(parents=True, exist_ok=True)
    with (SEALED / f"{token}.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def run() -> dict:
    registration = _registration()
    identity = frozen_identity()
    first = _first_legal_timestamp(registration["registration_utc"])
    latest = _canonical_latest()
    base = {"R2_MODEL_HASH_VERIFIED": identity["r2_verified"], "R28_3_MODEL_HASH_VERIFIED": identity["r28_verified"],
            "R2_SCORER_READY": True, "R28_3_SCORER_READY": True, "COMMON_UNIVERSE_CONTRACT_READY": True,
            "IMMUTABLE_LEDGER_FREEZE_READY": True, "FIRST_LEGAL_PROSPECTIVE_TIMESTAMP": str(first),
            "CANONICAL_LATEST_TIMESTAMP": str(latest), "OUTCOME_READ_BEFORE_LEDGER_FREEZE": False,
            "PRE_REGISTRATION_LEDGER_ROW_COUNT": 0, "HISTORICAL_BACKFILL_COUNT": 0, "MATURED_ROW_COUNT": 0}
    if latest < first:
        return {**base, "PREDICTION_LEDGER_FROZEN": False,
                "PROSPECTIVE_STATUS": "WAITING_FOR_FIRST_UNOBSERVED_MARKET_DATA"}
    common, missing = common_prospective_input_universe(registration["registration_utc"])
    if not missing.empty:
        raise RuntimeError("R28_PROSPECTIVE_COMMON_UNIVERSE_MISSING_FEATURES:" + str(len(missing)))
    if common.empty:
        return {**base, "PREDICTION_LEDGER_FROZEN": False,
                "PROSPECTIVE_STATUS": "WAITING_FOR_FIRST_UNOBSERVED_MARKET_DATA"}
    r2, r28 = _score_rows(common, identity)
    ledger = immutable_shadow_ledger(r2, r28, registration["registration_utc"], pd.Timestamp.now(tz="UTC").isoformat())
    manifest = seal_prediction_ledger(ledger)
    return {**base, "PREDICTION_LEDGER_FROZEN": True, "LEDGER_ROW_COUNT": manifest["row_count"],
            "LEDGER_SHA256": manifest["ledger_sha256"], "PROSPECTIVE_STATUS": "PASS_LEDGER_FROZEN"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FAST3 R28 future-only dual scorer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidate-timestamp-utc")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    registration = _registration()
    if args.candidate_timestamp_utc:
        if not prospective_timestamp_allowed(args.candidate_timestamp_utc, registration["registration_utc"]):
            raise RuntimeError("R28_PROSPECTIVE_HISTORICAL_BACKFILL_FORBIDDEN")
        print("R28_PROSPECTIVE_TIMESTAMP_ELIGIBLE=true")
    else:
        for key, value in run().items():
            print(f"{key}={str(value).lower() if isinstance(value, bool) else value}")
