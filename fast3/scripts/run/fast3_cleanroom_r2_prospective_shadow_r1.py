#!/usr/bin/env python
"""Forward-only economic shadow for the frozen FAST3 Clean-Room R2 HGB heads.

This is deliberately a small operational wrapper, not a new research stage.
It writes immutable JSONL partitions outside the repository and does not look
at action-ETF data while registering a signal.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd


REPO = Path(__file__).parents[3]
if str(REPO / "fast3" / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "fast3" / "src"))

R2_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_cleanroom_r2_freeze.py"
CANONICAL_ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R2_FROZEN = RESULTS_ROOT / "frozen" / "fast3" / "cleanroom_r2_20260808"
COMPLETED_CONTRACT = (RESULTS_ROOT / "frozen" / "fast3"
                      / "cleanroom_r2_execution_contract_completion_20260808"
                      / "execution_contract_completion.json")
EXPECTED_MODELS = {
    "UP_HGB": "dc1c05be91a50cc2fc8fdd1a622ba5fd24592fb1a42e5e008da2274e7e1b88eb",
    "DOWN_HGB": "70f216be92b90e295f0eaac0295ac057259ab0e5b4f90f1e9ef60a900b59372d",
}
EXPECTED_THRESHOLDS = {"UP_HGB_THRESHOLD": 0.46572965916785564,
                       "DOWN_HGB_THRESHOLD": 0.44665972406431553}
COMPLETED_CONTRACT_SHA256 = "17bf95775457e76c1f0e9f6d2c7fde41c5c7e117cac3f133a6da0f2cd639b55e"
SHADOW_NAME = "fast3_cleanroom_r2_prospective_shadow_r1"
ET = "America/New_York"


class ShadowStop(RuntimeError):
    """A fail-closed prospective-contract violation."""


def _load_r2():
    spec = importlib.util.spec_from_file_location("fast3_cleanroom_r2_frozen", R2_SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


R2 = _load_r2()
R1 = R2.R1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise ShadowStop("STOP_TIMESTAMP_TIMEZONE_MISSING")
        return timestamp.isoformat(timespec="nanoseconds")
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    return value


def stable_hash(value: dict) -> str:
    encoded = json.dumps(canonical_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def json_line(value: dict) -> bytes:
    return (json.dumps(canonical_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def utc(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ShadowStop("STOP_TIMESTAMP_TIMEZONE_MISSING")
    return result.tz_convert("UTC")


def now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def next_five_minute(timestamp: pd.Timestamp) -> pd.Timestamp:
    """First deterministic five-minute candidate clock instant strictly later."""
    timestamp = utc(timestamp)
    floor = timestamp.floor("5min")
    return floor + pd.Timedelta(minutes=5)


def outside_repo(path: Path) -> bool:
    try:
        Path(path).resolve().relative_to(REPO.resolve())
    except ValueError:
        return True
    return False


def validate_storage(runtime_root: Path, scratch_root: Path, frozen_root: Path, cache_root: Path,
                     canonical_root: Path) -> None:
    approved = RESULTS_ROOT.resolve()
    for label, path in (("runtime", runtime_root), ("scratch", scratch_root), ("frozen", frozen_root)):
        if not outside_repo(path):
            raise ShadowStop(f"STOP_REPOSITORY_LOCAL_RESULT_CACHE_VIOLATION:{label}")
        try:
            Path(path).resolve().relative_to(approved)
        except ValueError:
            # Unit tests intentionally use an isolated external temporary root.
            if os.environ.get("FAST3_SHADOW_TEST_MODE") != "1":
                raise ShadowStop(f"STOP_STORAGE_CONTRACT_VIOLATION:{label}")
    if not outside_repo(cache_root):
        raise ShadowStop("STOP_REPOSITORY_LOCAL_RESULT_CACHE_VIOLATION:cache")
    if not Path(canonical_root).is_dir():
        raise ShadowStop("STOP_CANONICAL_DATA_MISSING")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_frozen_identity(r2_frozen: Path = R2_FROZEN, completed_contract: Path = COMPLETED_CONTRACT) -> dict:
    manifest_path = r2_frozen / "cleanroom_r2_freeze_manifest.json"
    threshold_path = r2_frozen / "cleanroom_r2_thresholds.json"
    if not (manifest_path.is_file() and threshold_path.is_file() and completed_contract.is_file()):
        raise ShadowStop("STOP_IDENTITY_FAILURE:MISSING_FROZEN_ARTIFACT")
    manifest, thresholds = _read_json(manifest_path), _read_json(threshold_path).get("thresholds", {})
    models = {row.get("model"): row for row in manifest.get("models", [])}
    model_ok = all(key in models and Path(models[key]["path"]).is_file()
                   and sha256_file(Path(models[key]["path"])) == expected
                   and models[key].get("sha256") == expected
                   for key, expected in EXPECTED_MODELS.items())
    threshold_ok = all(thresholds.get(key) == expected for key, expected in EXPECTED_THRESHOLDS.items())
    contract_ok = sha256_file(completed_contract) == COMPLETED_CONTRACT_SHA256
    if not model_ok:
        raise ShadowStop("STOP_IDENTITY_FAILURE:FROZEN_MODEL_HASH_MISMATCH")
    if not threshold_ok:
        raise ShadowStop("STOP_IDENTITY_FAILURE:FROZEN_THRESHOLD_MISMATCH")
    if not contract_ok:
        raise ShadowStop("STOP_IDENTITY_FAILURE:FROZEN_EXECUTION_CONTRACT_MISMATCH")
    return {"models": models, "thresholds": {key: thresholds[key] for key in EXPECTED_THRESHOLDS},
            "model_identity_verified": True, "thresholds_verified": True,
            "execution_contract_verified": True, "manifest_path": str(manifest_path),
            "threshold_path": str(threshold_path), "completed_contract_path": str(completed_contract)}


def registration_path(frozen_root: Path) -> Path:
    return frozen_root / "fast3" / SHADOW_NAME / "registration_manifest.json"


def ensure_registration(frozen_root: Path, identity: dict, registered_at: pd.Timestamp) -> dict:
    """Create the one-way prospective boundary before any candidate processing."""
    path = registration_path(frozen_root)
    if path.exists():
        registration = _read_json(path)
        start = utc(registration["shadow_start_candidate_time_utc"])
        registered = utc(registration["shadow_registration_utc"])
        if start <= registered or registration.get("completed_execution_contract_sha256") != COMPLETED_CONTRACT_SHA256:
            raise ShadowStop("STOP_IDENTITY_FAILURE:REGISTRATION_MANIFEST_INVALID")
        if registration.get("model_hashes") != EXPECTED_MODELS or registration.get("thresholds") != identity["thresholds"]:
            raise ShadowStop("STOP_IDENTITY_FAILURE:REGISTRATION_IDENTITY_CHANGED")
        return registration
    registered_at = utc(registered_at)
    registration = {
        "artifact": "FAST3_CLEANROOM_R2_PROSPECTIVE_SHADOW_R1_REGISTRATION",
        "immutable": True,
        "shadow_registration_utc": registered_at,
        "shadow_start_candidate_time_utc": next_five_minute(registered_at),
        "candidate_frequency": "deterministic completed valid 5-minute candidate timestamps",
        "historical_backfill_performed": False,
        "models": {key: identity["models"][key]["path"] for key in EXPECTED_MODELS},
        "model_hashes": EXPECTED_MODELS,
        "thresholds": identity["thresholds"],
        "completed_execution_contract_sha256": COMPLETED_CONTRACT_SHA256,
        "same_direction_cross_underlying_tie": "ABSTAIN",
        "feature_names": list(R1.FEATURES),
        "feature_count": len(R1.FEATURES),
        "live_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(canonical_value(registration), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
    except FileExistsError:
        return ensure_registration(frozen_root, identity, registered_at)
    return registration


def _ledger_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.jsonl")) if root.is_dir() else []


def read_immutable_ledger(root: Path, hash_field: str, key_field: str) -> list[dict]:
    rows: list[dict] = []
    for path in _ledger_files(root):
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if not sidecar.is_file() or sidecar.read_text(encoding="ascii").strip() != sha256_file(path):
            raise ShadowStop(f"STOP_IMMUTABLE_LEDGER_HASH_FAILURE:{path}")
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            row = json.loads(line)
            actual = row.pop(hash_field, None)
            if actual != stable_hash(row):
                raise ShadowStop(f"STOP_IMMUTABLE_LEDGER_ROW_HASH_FAILURE:{path}:{line_no}")
            row[hash_field] = actual
            rows.append(row)
    keys = [row.get(key_field) for row in rows]
    if len(keys) != len(set(keys)):
        raise ShadowStop(f"STOP_DUPLICATE_IMMUTABLE_REGISTRATION:{key_field}")
    return rows


def append_immutable_rows(root: Path, rows: list[dict], hash_field: str, timestamp: pd.Timestamp) -> str | None:
    if not rows:
        return None
    prepared = []
    for row in rows:
        payload = canonical_value(row)
        payload[hash_field] = stable_hash(payload)
        prepared.append(payload)
    day = utc(timestamp).strftime("day=%Y-%m-%d")
    destination = root / day
    destination.mkdir(parents=True, exist_ok=True)
    file_path = destination / (utc(timestamp).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl")
    try:
        with file_path.open("xb") as handle:
            for row in prepared:
                handle.write(json_line(row))
    except FileExistsError:
        raise ShadowStop("STOP_DUPLICATE_IMMUTABLE_APPEND_PATH")
    digest = sha256_file(file_path)
    with file_path.with_suffix(file_path.suffix + ".sha256").open("x", encoding="ascii") as handle:
        handle.write(digest + "\n")
    return digest


def signal_ledger_root(runtime_root: Path) -> Path:
    return runtime_root / "fast3" / SHADOW_NAME / "signal_ledger"


def maturity_ledger_root(runtime_root: Path) -> Path:
    return runtime_root / "fast3" / SHADOW_NAME / "matured_trade_ledger"


def candidate_id(underlying: str, timestamp: pd.Timestamp) -> str:
    return f"CLEANROOM_R2_SHADOW_R1|{underlying}|{utc(timestamp).isoformat()}"


def symbol_paths(canonical_root: Path, symbol: str) -> list[Path]:
    paths = sorted(Path(canonical_root).glob(f"symbol={symbol}/year=*/month=*/data.parquet"))
    if not paths:
        raise ShadowStop(f"STOP_CANONICAL_SYMBOL_MISSING:{symbol}")
    return paths


def available_candidates(canonical_root: Path, start: pd.Timestamp) -> tuple[pd.DataFrame, str | None]:
    """Compute frozen PIT features, then discard every pre-registration candidate."""
    pieces, latest = [], []
    for symbol in R1.SYMBOLS:
        raw = R2.read_symbol(symbol, symbol_paths(canonical_root, symbol))
        latest.append(raw["timestamp_utc"].max())
        directional, _ = R1.candidate_features(raw, symbol, include_labels=False)
        # The function returns identical raw features for both heads except fixed direction_code.
        up = directional[directional["direction"].eq("UP")].copy()
        down = directional[directional["direction"].eq("DOWN")].copy()
        keys = ["underlying_symbol", "decision_timestamp_utc"]
        merged = up.merge(down[keys + ["direction_code"]], on=keys, how="inner", validate="one_to_one",
                          suffixes=("", "_down"))
        merged = merged[pd.to_datetime(merged["decision_timestamp_utc"], utc=True) >= utc(start)].copy()
        if not merged.empty:
            merged["candidate_id"] = [candidate_id(s, t) for s, t in zip(merged.underlying_symbol, merged.decision_timestamp_utc)]
            pieces.append(merged)
    frame = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    canonical_latest = min(latest).isoformat() if latest else None
    return frame, canonical_latest


def score_and_resolve(candidates: pd.DataFrame, models: dict, thresholds: dict, registration_time: pd.Timestamp) -> list[dict]:
    if candidates.empty:
        return []
    up_model, down_model = joblib.load(models["UP_HGB"]["path"]), joblib.load(models["DOWN_HGB"]["path"])
    feature_names = list(R1.FEATURES)
    up_x = candidates[feature_names].copy()
    down_x = up_x.copy(); down_x["direction_code"] = candidates["direction_code_down"].astype(int)
    candidates = candidates.copy()
    candidates["up_hgb_score"] = up_model.predict_proba(up_x)[:, 1]
    candidates["down_hgb_score"] = down_model.predict_proba(down_x)[:, 1]
    candidates["up_selected"] = candidates.up_hgb_score >= thresholds["UP_HGB_THRESHOLD"]
    candidates["down_selected"] = candidates.down_hgb_score >= thresholds["DOWN_HGB_THRESHOLD"]
    candidates["decision"] = np.select(
        [candidates.up_selected & candidates.down_selected, candidates.up_selected, candidates.down_selected],
        ["OPPOSITE_DIRECTION_TIE_ABSTAIN", "UP", "DOWN"], default="NO_SIGNAL")
    for _, index in candidates.groupby("decision_timestamp_utc", sort=True).groups.items():
        group = candidates.loc[index]
        active = group[group.decision.isin(["UP", "DOWN"])]
        if active.empty:
            continue
        if active.decision.nunique() > 1:
            candidates.loc[active.index, "decision"] = "OPPOSITE_DIRECTION_TIE_ABSTAIN"
        elif len(active) > 1:
            candidates.loc[active.index, "decision"] = "SAME_DIRECTION_CROSS_UNDERLYING_TIE_ABSTAIN"
    rows = []
    for item in candidates.sort_values(["decision_timestamp_utc", "underlying_symbol"], kind="mergesort").to_dict("records"):
        feature_values = {name: item[name] for name in feature_names}
        anchor = utc(item["decision_timestamp_utc"])
        row = {"candidate_id": item["candidate_id"], "candidate_timestamp_utc": anchor,
               "candidate_timestamp_et": anchor.tz_convert(ET), "underlying": item["underlying_symbol"],
               "feature_values": feature_values, "feature_asof_timestamp_utc": item["max_feature_timestamp_utc"],
               "up_hgb_score": float(item["up_hgb_score"]), "down_hgb_score": float(item["down_hgb_score"]),
               "up_selected": bool(item["up_selected"]), "down_selected": bool(item["down_selected"]),
               "decision": str(item["decision"]), "model_hashes": EXPECTED_MODELS,
               "thresholds": thresholds, "execution_contract_sha256": COMPLETED_CONTRACT_SHA256,
               "signal_registration_timestamp_utc": utc(registration_time),
               "payoff_maturity_timestamp_utc": anchor + pd.Timedelta(hours=24), "payoff_opened": False}
        rows.append(row)
    return rows


def _selected_payoff_row(signal: dict, payoff: pd.Series, status: str, trade_id: str | None = None) -> dict:
    side = signal["decision"].lower()
    valid = bool(payoff[f"{side}_payoff_valid"])
    output = {"candidate_id": signal["candidate_id"], "candidate_timestamp_utc": signal["candidate_timestamp_utc"],
              "underlying": signal["underlying"], "decision": signal["decision"], "maturity_status": status,
              "payoff_opened": True, "payoff_valid": valid, "trade_id": trade_id,
              "action_instrument": payoff[f"{side}_action_instrument"],
              "payoff_row_sha256": payoff.get("payoff_row_hash"),
              "entry_timestamp_et": payoff[f"{side}_entry_timestamp_et"],
              "exit_timestamp_et": payoff[f"{side}_actual_exit_timestamp_et"],
              "entry_price": payoff[f"{side}_entry_price"], "exit_price": payoff[f"{side}_exit_price"],
              "net_return_20bps": payoff[f"{side}_action_net_return_20bps"],
              "invalid_reason": payoff[f"{side}_invalid_reason"],
              "execution_contract_sha256": COMPLETED_CONTRACT_SHA256}
    return output


def mature_signals(signals: list[dict], existing: list[dict], canonical_root: Path, authoritative_now: pd.Timestamp) -> list[dict]:
    """Open action-ETF data only for eligible, flat, still-unmatured signals."""
    from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as payoff_module

    recorded = {row["candidate_id"] for row in existing}
    prior_trades = [row for row in existing if row.get("maturity_status") == "EXECUTED_TRADE"]
    open_until = max((utc(row["exit_timestamp_et"]) for row in prior_trades), default=None)
    trade_no = len(prior_trades)
    output = []
    for signal in sorted(signals, key=lambda row: (utc(row["candidate_timestamp_utc"]), row["candidate_id"])):
        if signal["candidate_id"] in recorded or signal["decision"] not in ("UP", "DOWN"):
            continue
        anchor = utc(signal["candidate_timestamp_utc"])
        if utc(authoritative_now) < utc(signal["payoff_maturity_timestamp_utc"]):
            continue
        if open_until is not None and anchor < open_until:
            output.append({"candidate_id": signal["candidate_id"], "candidate_timestamp_utc": anchor,
                           "underlying": signal["underlying"], "decision": signal["decision"],
                           "maturity_status": "IGNORED_WHILE_OPEN", "payoff_opened": False,
                           "execution_contract_sha256": COMPLETED_CONTRACT_SHA256})
            continue
        candidates = pd.DataFrame([{"candidate_id": signal["candidate_id"], "candidate_instrument": signal["underlying"],
                                    "decision_timestamp_et": utc(signal["candidate_timestamp_utc"]).tz_convert(ET),
                                    "authoritative_anchor_timestamp_et": utc(signal["candidate_timestamp_utc"]).tz_convert(ET)}])
        # This is the sole payoff-data access point and is unreachable for immature signals.
        payoffs, _ = payoff_module.construct_payoffs(candidates, canonical_root)
        payoff = payoffs.iloc[0]
        side = signal["decision"].lower()
        valid = bool(payoff[f"{side}_payoff_valid"])
        if not valid and utc(authoritative_now) < anchor + pd.Timedelta(hours=24 + 96):
            # Action-market coverage could still legitimately close the frozen exit later.
            break
        if not valid:
            output.append(_selected_payoff_row(signal, payoff, "PAYOFF_INVALID"))
            continue
        trade_no += 1
        trade_id = f"CLEANROOM_R2_SHADOW_R1-{trade_no:06d}"
        event = _selected_payoff_row(signal, payoff, "EXECUTED_TRADE", trade_id)
        output.append(event)
        open_until = utc(event["exit_timestamp_et"])
    return output


def counts(signals: list[dict], maturities: list[dict]) -> dict:
    decisions = pd.Series([row["decision"] for row in signals], dtype="object")
    return {"TOTAL_REGISTERED_PROSPECTIVE_CANDIDATES": len(signals),
            "TOTAL_REGISTERED_UP_SIGNALS": int(decisions.eq("UP").sum()),
            "TOTAL_REGISTERED_DOWN_SIGNALS": int(decisions.eq("DOWN").sum()),
            "TOTAL_MATURED_SIGNALS": len(maturities),
            "TOTAL_EXECUTED_TRADES": int(sum(row.get("maturity_status") == "EXECUTED_TRADE" for row in maturities))}


def run(runtime_root: Path = RESULTS_ROOT / "runtime", scratch_root: Path = RESULTS_ROOT / "scratch",
        frozen_root: Path = RESULTS_ROOT / "frozen", cache_root: Path = Path(r"D:\us-tech-quant-cache"),
        canonical_root: Path = CANONICAL_ROOT, registered_at: pd.Timestamp | None = None,
        authoritative_now: pd.Timestamp | None = None) -> dict:
    validate_storage(runtime_root, scratch_root, frozen_root, cache_root, canonical_root)
    identity = verify_frozen_identity()
    registration_time = utc(registered_at or now_utc())
    registration = ensure_registration(frozen_root, identity, registration_time)
    start = utc(registration["shadow_start_candidate_time_utc"])
    signal_root, maturity_root = signal_ledger_root(runtime_root), maturity_ledger_root(runtime_root)
    signals = read_immutable_ledger(signal_root, "signal_row_sha256", "candidate_id")
    if any(utc(row["candidate_timestamp_utc"]) < start for row in signals):
        raise ShadowStop("STOP_HISTORICAL_CANDIDATE_IN_PROSPECTIVE_LEDGER")
    candidates, canonical_latest = available_candidates(canonical_root, start)
    existing_ids = {row["candidate_id"] for row in signals}
    new_frame = candidates[~candidates["candidate_id"].isin(existing_ids)].copy() if not candidates.empty else candidates
    new_rows = score_and_resolve(new_frame, identity["models"], identity["thresholds"], registration_time)
    signal_hash = append_immutable_rows(signal_root, new_rows, "signal_row_sha256", registration_time)
    signals.extend(new_rows)
    maturities = read_immutable_ledger(maturity_root, "matured_row_sha256", "candidate_id")
    mature_rows = mature_signals(signals, maturities, canonical_root, utc(authoritative_now or now_utc()))
    maturity_hash = append_immutable_rows(maturity_root, mature_rows, "matured_row_sha256", registration_time)
    maturities.extend(mature_rows)
    total = counts(signals, maturities)
    duplicate_signal = len(signals) - len({row["candidate_id"] for row in signals})
    trade_rows = [row for row in maturities if row.get("maturity_status") == "EXECUTED_TRADE"]
    trade_ids = [row.get("trade_id") for row in trade_rows]
    ordered = sorted(trade_rows, key=lambda row: utc(row["entry_timestamp_et"]))
    overlaps = sum(utc(next_row["entry_timestamp_et"]) < utc(row["exit_timestamp_et"])
                   for row, next_row in zip(ordered, ordered[1:]))
    status = "PASS" if new_rows else "PASS_REGISTERED_WAITING_FOR_NEW_DATA"
    return {"PROSPECTIVE_SHADOW_STATUS": status, "SHADOW_REGISTRATION_UTC": registration["shadow_registration_utc"],
            "SHADOW_START_CANDIDATE_TIME": registration["shadow_start_candidate_time_utc"],
            "FROZEN_MODEL_IDENTITY_VERIFIED": True, "FROZEN_THRESHOLDS_VERIFIED": True,
            "FROZEN_EXECUTION_CONTRACT_VERIFIED": True, "CANONICAL_LATEST_TIMESTAMP": canonical_latest,
            "NEW_PROSPECTIVE_CANDIDATES": len(new_rows), "NEW_UP_SIGNALS": int(sum(r["decision"] == "UP" for r in new_rows)),
            "NEW_DOWN_SIGNALS": int(sum(r["decision"] == "DOWN" for r in new_rows)),
            "NEW_OPPOSITE_DIRECTION_TIE_ABSTAINS": int(sum(r["decision"] == "OPPOSITE_DIRECTION_TIE_ABSTAIN" for r in new_rows)),
            "NEW_SAME_DIRECTION_CROSS_UNDERLYING_TIE_ABSTAINS": int(sum(r["decision"] == "SAME_DIRECTION_CROSS_UNDERLYING_TIE_ABSTAIN" for r in new_rows)),
            **total, "NEWLY_MATURED_SIGNALS": len(mature_rows),
            "NEW_EXECUTED_TRADES": int(sum(r.get("maturity_status") == "EXECUTED_TRADE" for r in mature_rows)),
            "DUPLICATE_CANDIDATE_ID_COUNT": 0, "DUPLICATE_SIGNAL_REGISTRATION_COUNT": duplicate_signal,
            "DUPLICATE_TRADE_ID_COUNT": len(trade_ids) - len(set(trade_ids)), "OVERLAPPING_TRADE_COUNT": overlaps,
            "SIGNAL_LEDGER_SHA256_OR_MANIFEST_ID": signal_hash or maturity_hash or "NO_NEW_APPEND",
            "STORAGE_CONTRACT_PASS": True, "MODEL_REFIT": False, "THRESHOLD_RECOMPUTED": False,
            "FEATURE_CHANGE": False, "PARAMETER_CHANGE": False, "LIVE_TRADING_ALLOWED": False,
            "OFFICIAL_ADOPTION_ALLOWED": False, "FIRST_FAILURE": None,
            "NEXT_STEP": "RUN_THE_SAME_PROSPECTIVE_SHADOW_ENTRYPOINT_ON_FUTURE_CANONICAL_DATA_UPDATES",
            "REGISTRATION_MANIFEST_PATH": str(registration_path(frozen_root)), "SIGNAL_LEDGER_PATH": str(signal_root),
            "MATURED_TRADE_LEDGER_PATH": str(maturity_root)}


def main() -> int:
    parser = argparse.ArgumentParser(description="FAST3 Clean-Room R2 prospective economic shadow R1")
    parser.add_argument("--runtime-root", type=Path, default=RESULTS_ROOT / "runtime")
    parser.add_argument("--scratch-root", type=Path, default=RESULTS_ROOT / "scratch")
    parser.add_argument("--frozen-root", type=Path, default=RESULTS_ROOT / "frozen")
    parser.add_argument("--cache-root", type=Path, default=Path(r"D:\us-tech-quant-cache"))
    parser.add_argument("--canonical-root", type=Path, default=CANONICAL_ROOT)
    args = parser.parse_args()
    try:
        report = run(args.runtime_root, args.scratch_root, args.frozen_root, args.cache_root, args.canonical_root)
    except ShadowStop as error:
        print("PROSPECTIVE_SHADOW_STATUS=" + str(error))
        print("FIRST_FAILURE=" + str(error))
        return 2
    for key, value in report.items():
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
