from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
DATA = Path(r"D:\us-tech-quant-data")
CACHE = Path(r"D:\us-tech-quant-cache")
CONFIG_PATH = REPO / "fast4/config/fast4_r1.json"
R43A_ROOT = RESULTS / "frozen/fast3/r43a_independent_economic_target_contract_freeze_r1"
R43A_CONTRACT = R43A_ROOT / "FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json"
R43B_ROOT = RESULTS / "frozen/fast3/r43b_current_information_set_economic_baseline_r1"
R43B_IDENTITY = R43B_ROOT / "FAST3_R43B_FEATURE_IDENTITY.csv"
R43C_ROOT = RESULTS / "frozen/fast3/r43c_regime_information_family_incremental_test_r1"
R43C_VALUES = R43C_ROOT / "FAST3_R43C_REGIME_FEATURE_VALUES.parquet"
R43C_MANIFEST = R43C_ROOT / "FAST3_R43C_REGIME_FEATURE_MANIFEST.json"
R43D_ROOT = RESULTS / "frozen/fast3/r43d_path_shape_information_family_incremental_test_r1"
R43D_VALUES = R43D_ROOT / "FAST3_R43D_PATH_FEATURE_VALUES.parquet"
R43D_MANIFEST = R43D_ROOT / "FAST3_R43D_PATH_SHAPE_FEATURE_MANIFEST.json"
TARGET_LEDGER = RESULTS / "scratch/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z/FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet"
SOURCE_MANIFEST = RESULTS / "frozen/fast3/cleanroom_r2_20260808/cleanroom_r2_preholdout_source_manifest.json"
VIX_DAILY = DATA / "fast3/vix_cboe_daily/canonical/vix_daily.parquet"

EXPECTED_HASHES = {
    R43A_CONTRACT: "a5d43651433c6dde50eef791facd02047db2be073a0097acaf31cd1af25d2d6a",
    R43B_IDENTITY: "3721263e9bcfaf9a84363669dcfb10b2fdd8e66b292732f164e93dbaac58b537",
    R43C_MANIFEST: "c1cbfcf948018cc701f447748764e3dc650dd1d053703fa9c708cdab6aaa1780",
    R43D_MANIFEST: "af98a3074efdbaf3f47814c2be63bf192ef46d7ed0d21dc7c915b5fbd42621ae",
    TARGET_LEDGER: "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb",
    SOURCE_MANIFEST: "8ef4126e586350a8c67180e6c375309867d498370ddfffcd93a93eee7fc62610",
}
HORIZONS = (5, 10, 15, 30, 60)
RETURN_COLUMNS = tuple(f"return_{h}m_net20" for h in HORIZONS)


class ContractError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, default=str, allow_nan=False) + "\n").encode("utf-8")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stable_bytes(value))


def config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def verify_contracts() -> dict[str, Any]:
    if REPO != Path(r"D:\us-tech-quant") or RESULTS != Path(r"D:\us-tech-quant-results") or not DATA.is_dir():
        raise ContractError("STOP_FAST4_STORAGE_CONTRACT")
    observed = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ContractError(f"STOP_FAST4_REQUIRED_CONTRACT_MISSING:{path}")
        observed[str(path)] = sha256(path)
        if observed[str(path)] != expected:
            raise ContractError(f"STOP_FAST4_FROZEN_IDENTITY_MISMATCH:{path}")
    target = json.loads(R43A_CONTRACT.read_text(encoding="utf-8"))
    if (target.get("PRIMARY_TARGET_NAME") != "AVERAGE_FIXED_HORIZON_NET20"
            or target.get("HORIZONS") != list(HORIZONS)
            or target.get("HORIZON_WEIGHTS") != {str(h): 0.2 for h in HORIZONS}
            or target.get("COST_CONTRACT", {}).get("ECONOMIC_COST_BPS") != 20
            or target.get("PRIMARY_TARGET_DEPENDS_ON_FIRST_TOUCH_EXIT") is not False
            or target.get("TARGET_PAYOFF_MECHANICAL_COUPLING") is not False):
        raise ContractError("STOP_FAST4_R43A_TARGET_CONTENT_MISMATCH")
    return {"observed_sha256": observed, "target_contract": target}


def load_targets() -> pd.DataFrame:
    columns = ["candidate_id", "decision_timestamp_utc", "entry_timestamp", "head", "underlying_symbol",
               "action_instrument", "path_complete", *RETURN_COLUMNS]
    frame = pd.read_parquet(TARGET_LEDGER, columns=columns)
    frame["decision_timestamp_utc"] = pd.to_datetime(frame.decision_timestamp_utc, utc=True, errors="raise")
    frame["entry_timestamp"] = pd.to_datetime(frame.entry_timestamp, utc=True, errors="raise")
    numeric = frame.loc[:, RETURN_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if (len(frame) != 1197 or frame.candidate_id.duplicated().any() or not frame.path_complete.eq(True).all()
            or not numeric.notna().all().all() or not (frame.entry_timestamp > frame.decision_timestamp_utc).all()):
        raise ContractError("STOP_FAST4_HISTORICAL_TARGET_LEDGER_INTEGRITY")
    for h, column in zip(HORIZONS, RETURN_COLUMNS):
        frame[f"y_{h}m"] = numeric[column].astype(float)
    frame["primary_target"] = numeric.mean(axis=1)
    frame["y_positive"] = frame.primary_target.gt(0).astype(int)
    frame["positive_horizon_majority"] = numeric.gt(0).sum(axis=1).ge(3).astype(int)
    frame["severe_loss"] = frame.primary_target.le(config()["severe_loss_threshold"]).astype(int)
    frame["target_end_timestamp_utc"] = frame.entry_timestamp + pd.to_timedelta(max(HORIZONS), unit="m")
    frame["trading_date"] = frame.decision_timestamp_utc.dt.tz_convert("America/New_York").dt.date.astype(str)
    return frame


def package_versions() -> dict[str, str]:
    packages = ["python", "numpy", "pandas", "scikit-learn", "pyarrow", "joblib", "lightgbm", "xgboost", "catboost", "optuna", "shap"]
    result = {}
    for package in packages:
        if package == "python":
            import platform
            result[package] = platform.python_version()
            continue
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = "NOT_INSTALLED"
    return result


def discovery_manifest() -> dict[str, Any]:
    verified = verify_contracts()
    targets = load_targets()
    source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = "GIT_IDENTITY_UNAVAILABLE"
    option_roots = sorted((RESULTS / "archive/fast3").glob("moomoo_option_history_r2_*"))
    return {
        "schema_version": "FAST4_R1_DISCOVERY_MANIFEST_V1",
        "project": "FAST4-R1 FULL ECONOMIC ENSEMBLE",
        "r43a_target_contract": str(R43A_CONTRACT),
        "r43a_target_contract_sha256": EXPECTED_HASHES[R43A_CONTRACT],
        "target_name": "AVERAGE_FIXED_HORIZON_NET20",
        "target_formula": verified["target_contract"]["PRIMARY_TARGET_FORMULA"],
        "transaction_cost": verified["target_contract"]["COST_CONTRACT"],
        "historical_target_ledger": str(TARGET_LEDGER),
        "historical_target_ledger_sha256": EXPECTED_HASHES[TARGET_LEDGER],
        "candidate_count": len(targets),
        "training_start": str(targets.decision_timestamp_utc.min()),
        "training_end": str(targets.decision_timestamp_utc.max()),
        "legal_training_cutoff": str(targets.target_end_timestamp_utc.max()),
        "direction_counts": targets["head"].value_counts().to_dict(),
        "underlying_counts": targets.underlying_symbol.value_counts().to_dict(),
        "execution_symbol_mapping": verified["target_contract"]["ENTRY_CONTRACT"]["EXECUTION_SYMBOL"],
        "r43b_feature_identity": str(R43B_IDENTITY),
        "r43c_regime_manifest": str(R43C_MANIFEST),
        "r43d_path_manifest": str(R43D_MANIFEST),
        "canonical_market_data_manifest": str(SOURCE_MANIFEST),
        "canonical_market_data_file_count": len(source["files"]),
        "canonical_market_data_symbols": sorted({row["symbol"] for row in source["files"]}),
        "canonical_data_root_read_only": str(DATA),
        "external_results_root": str(RESULTS),
        "external_cache_root": str(CACHE),
        "purge_minutes": 60, "embargo_minutes": 60,
        "option_archive_roots": [str(path) for path in option_roots],
        "option_feature_family_status": "SKIPPED_NO_HISTORICAL_PIT_OVERLAP_WITH_2020_2025_TARGET_COHORT",
        "installed_versions": package_versions(),
        "unavailable_requested_model_families": [name for name in ("lightgbm", "xgboost", "catboost", "optuna") if package_versions()[name] == "NOT_INSTALLED"],
        "package_install_attempt_status": "BLOCKED_BY_SANDBOX_NETWORK_NO_VENV_PACKAGE_CHANGE",
        "prospective_fast3_or_r36_outcomes_read": False,
        "broker_or_trade_api_allowed": False,
        "training_code_commit_hash": commit,
        "frozen_input_sha256": verified["observed_sha256"],
    }
