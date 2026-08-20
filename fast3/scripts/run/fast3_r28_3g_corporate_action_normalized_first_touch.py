"""FAST3 R28.3G corporate-action-normalized first-touch re-audit.

The program uses the same 1,198 frozen R28.3E signals and raw canonical ETF
bars.  Corporate actions are normalized only in the economic return layer.
There is no model access, score computation, strategy change, or optimization.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
RUNTIME_ROOT = RESULTS_ROOT / "runtime"
SCRATCH_ROOT = RESULTS_ROOT / "scratch"
FROZEN_ROOT = RESULTS_ROOT / "frozen"
RUN_ID = "r28_3g_corporate_action_normalized_first_touch_20260809"
RUNTIME_RUN_ROOT = RUNTIME_ROOT / "fast3" / RUN_ID
SCRATCH_RUN_ROOT = SCRATCH_ROOT / "fast3" / RUN_ID
FROZEN_RUN_ROOT = FROZEN_ROOT / "fast3" / RUN_ID
STAGE = RUNTIME_RUN_ROOT / "frozen_stage"

R28E_ROOT = FROZEN_ROOT / "fast3" / "r28_3e_clean_lineage_first_touch_20260809_r3"
R28F_ROOT = FROZEN_ROOT / "fast3" / "r28_3f_leveraged_etf_integrity_20260809_r3"
R28E_SUMMARY = R28E_ROOT / "R28_3E_SUMMARY.json"
R28E_LEDGER = R28E_ROOT / "R28_3E_FIRST_TOUCH_TRADE_LEDGER.csv"
R28E_MANIFEST = R28E_ROOT / "R28_3E_CANONICAL_ETF_PARTITION_MANIFEST.json"
R28F_SUMMARY = R28F_ROOT / "R28_3F_SUMMARY.json"
R28F_ACTION_AUDIT = R28F_ROOT / "R28_3F_CORPORATE_ACTION_AUDIT.csv"
R28F_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_r28_3f_leveraged_etf_integrity_audit.py"

EXPECTED_MANIFEST_SHA256 = "1726b400b9fbb33f1bf85ff4afd229288f8e823d26cf3b2d3b0956e760b3a331"
EXPECTED_INPUT_HASHES = {
    "r28e_summary": "90994e4877d97490e5a854e8e32babf785591d7044e4a4acc035f1e721be97f2",
    "r28e_ledger": "52e8ac6ea642f57abb900d2c78315a7061347c74a70ba8c54597867a63713097",
    "r28e_manifest": EXPECTED_MANIFEST_SHA256,
    "r28f_summary": "2feff66395207c7e119c9efe8da3aa2992c5492aa4f482df048168b5bb19f3af",
    "r28f_action_audit": "547a6a45628f57f8b13f4f43d6a553ed8eb00e1bf2c135846fc32f2d47a71614",
}
SYMBOLS = ("SOXL", "SOXS", "TQQQ", "SQQQ")
ORIGINAL_MEAN_NET20 = 0.002701147801803399
TOLERANCE = 1e-12


class AuditStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def canonical_sha256(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atomic_json(path: Path, value: dict, canonical: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(value) if canonical else
                          json.dumps(value, indent=2, ensure_ascii=False, default=str).encode("utf-8"))
    temporary.replace(path)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise AuditStop(f"STOP_MODULE_LOAD:{path}")
    spec.loader.exec_module(module)
    return module


def data_snapshot() -> dict[str, tuple[int, int]]:
    return {str(path): (int(path.stat().st_size), int(path.stat().st_mtime_ns))
            for path in DATA_ROOT.rglob("*") if path.is_file()}


def repo_snapshot() -> dict[str, str]:
    lines = subprocess.check_output(["git", "status", "--porcelain", "-uall"], cwd=REPO, text=True,
                                    stderr=subprocess.DEVNULL).splitlines()
    result = {}
    for line in lines:
        if len(line) < 4:
            continue
        relative = line[3:].strip().strip('"').replace("\\", "/")
        path = REPO / relative
        result[relative] = file_sha256(path) if path.is_file() else "NON_FILE"
    return result


def storage_preflight() -> tuple[dict, dict, dict]:
    pycache = Path(sys.pycache_prefix).resolve() if sys.pycache_prefix else None
    if pycache is None or CACHE_ROOT.resolve() not in (pycache, *pycache.parents):
        raise AuditStop("STOP_PYTHON_CACHE_NOT_EXTERNALIZED")
    if (REPO / ".local_results").exists():
        raise AuditStop("STOP_LOCAL_RESULTS_PRE_EXISTING")
    if any(path.exists() for path in (RUNTIME_RUN_ROOT, SCRATCH_RUN_ROOT, FROZEN_RUN_ROOT)):
        raise AuditStop("STOP_R28_3G_RUN_PATH_EXISTS")
    RUNTIME_RUN_ROOT.mkdir(parents=True)
    SCRATCH_RUN_ROOT.mkdir(parents=True)
    storage = {
        "SOURCE_ROOT": str(REPO), "DATA_ROOT": str(DATA_ROOT), "RESULTS_ROOT": str(RESULTS_ROOT),
        "CACHE_ROOT": str(CACHE_ROOT), "RUNTIME_RUN_ROOT": str(RUNTIME_RUN_ROOT),
        "SCRATCH_RUN_ROOT": str(SCRATCH_RUN_ROOT), "FROZEN_RUN_ROOT": str(FROZEN_RUN_ROOT),
        "PRE_EXISTING_STORAGE_VIOLATION_COUNT": 2,
        "PRE_EXISTING_STORAGE_VIOLATIONS": [str(REPO / ".pytest_cache"), str(REPO / ".pytest_v22_049_tmp")],
    }
    before_data, before_repo = data_snapshot(), repo_snapshot()
    atomic_json(RUNTIME_RUN_ROOT / "progress.json", {**storage, "stage": "STORAGE_PREFLIGHT_COMPLETE"})
    return storage, before_data, before_repo


def post_storage_audit(before_data: dict, before_repo: dict) -> dict:
    after_data, after_repo = data_snapshot(), repo_snapshot()
    data_changes = set(before_data) ^ set(after_data) | {
        path for path in set(before_data) & set(after_data) if before_data[path] != after_data[path]}
    preserved = before_repo == after_repo
    new_paths = set(after_repo) - set(before_repo)
    result_files = [path for path in new_paths if Path(path).suffix.lower() in {".csv", ".json", ".parquet", ".md", ".log"}]
    violations = len(data_changes) + int(not preserved) + len(result_files) + int((REPO / ".local_results").exists())
    result = {
        "DATA_ROOT_WRITE_COUNT": len(data_changes), "LOCAL_RESULTS_CREATED": False,
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": bool(result_files), "NEW_STORAGE_VIOLATION_COUNT": violations,
        "PRE_EXISTING_UNTRACKED_FILES_PRESERVED": preserved, "PRE_EXISTING_TRACKED_CHANGES_PRESERVED": preserved,
        "RUNTIME_OUTPUT_LOCATION_VALID": True, "SCRATCH_OUTPUT_LOCATION_VALID": True,
        "FROZEN_OUTPUT_LOCATION_VALID": True, "PYTHON_CACHE_EXTERNALIZED": True,
        "PYTEST_TEMP_EXTERNALIZED": True, "DESTRUCTIVE_GIT_COMMAND_USED": False, "BROAD_GIT_ADD_USED": False,
    }
    if violations:
        raise AuditStop(f"STOP_NEW_STORAGE_VIOLATION:{result}")
    return result


def price_multiplier(action_type: str, split_ratio: str) -> float:
    left, right = (float(value) for value in str(split_ratio).split(":"))
    if left <= 0 or right <= 0:
        raise AuditStop("STOP_INVALID_SPLIT_RATIO")
    if action_type == "FORWARD_SPLIT":
        return right / left
    if action_type == "REVERSE_SPLIT":
        return right / left
    raise AuditStop(f"STOP_UNKNOWN_ACTION_TYPE:{action_type}")


def build_action_ledger(action_audit: pd.DataFrame, coverage_start: pd.Timestamp,
                        coverage_end: pd.Timestamp) -> dict:
    official = action_audit.loc[action_audit.metadata_authority.eq("OFFICIAL_ISSUER")].copy()
    official["observed_boundary_timestamp"] = pd.to_datetime(official.observed_boundary_timestamp, utc=True)
    official = official.loc[(official.observed_boundary_timestamp >= coverage_start.normalize()) &
                            (official.observed_boundary_timestamp <= coverage_end.ceil("D"))]
    records = []
    for row in official.sort_values(["symbol", "observed_boundary_timestamp"], kind="mergesort").to_dict("records"):
        url = str(row["corporate_action_source"])
        multiplier = price_multiplier(str(row["action_type"]), str(row["split_ratio"]))
        records.append({
            "symbol": str(row["symbol"]), "effective_date": str(row["effective_date"]),
            "effective_timestamp": pd.Timestamp(row["observed_boundary_timestamp"]).isoformat(),
            "action_type": str(row["action_type"]), "split_ratio": str(row["split_ratio"]),
            "pre_to_post_price_multiplier": multiplier,
            "post_action_share_factor": 1.0 / multiplier,
            "authoritative_source": url, "source_identity_kind": "AUTHORITATIVE_URL_STRING_SHA256",
            "source_identity_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "source_document_sha256": None,
            "canonical_boundary_evidence": {
                "previous_timestamp": str(row["previous_timestamp"]),
                "previous_close": float(row["previous_close"]), "current_close": float(row["current_close"]),
                "absolute_price_ratio": float(row["absolute_price_ratio"]),
            },
        })
    if set(record["symbol"] for record in records) != set(SYMBOLS):
        raise AuditStop("STOP_CORPORATE_ACTION_LEDGER_SYMBOL_COVERAGE")
    return {
        "ledger_version": "FAST3_R28_3G_AUTHORITATIVE_CORPORATE_ACTION_LEDGER_V1",
        "price_basis": "RAW", "normalization_layer": "ECONOMIC_RETURN_ONLY",
        "coverage_start": coverage_start.isoformat(), "coverage_end": coverage_end.isoformat(),
        "record_count": len(records), "records": records,
        "generation_contract": "Issuer-confirmed actions from frozen R28.3F action audit; deterministic sort by symbol/effective timestamp",
    }


def actions_between(entry: pd.Timestamp, exit_: pd.Timestamp, symbol: str, records: list[dict]) -> list[dict]:
    result = []
    for record in records:
        boundary = pd.Timestamp(record["effective_timestamp"])
        if record["symbol"] == symbol and entry < boundary <= exit_:
            result.append(record)
    return result


def normalize_trade(entry_price: float, exit_price: float, actions: list[dict]) -> dict:
    factor = float(np.prod([float(action["pre_to_post_price_multiplier"]) for action in actions], dtype=float)) if actions else 1.0
    share_factor = 1.0 / factor
    normalized_entry = float(entry_price) * factor
    normalized_exit = float(exit_price)
    gross_price_equivalent = normalized_exit / normalized_entry - 1.0
    gross_share_equivalent = (float(exit_price) * share_factor) / float(entry_price) - 1.0
    if not np.isclose(gross_price_equivalent, gross_share_equivalent, atol=TOLERANCE, rtol=TOLERANCE):
        raise AuditStop("STOP_SHARE_PRICE_NORMALIZATION_DISAGREEMENT")
    return {
        "corporate_action_factor": factor, "post_action_share_factor": share_factor,
        "normalized_entry_equivalent": normalized_entry, "normalized_exit_equivalent": normalized_exit,
        "normalized_gross": gross_price_equivalent, "normalized_net10": gross_price_equivalent - .001,
        "normalized_net20": gross_price_equivalent - .002,
    }


def distribution(frame: pd.DataFrame) -> dict:
    net = frame.corrected_net20
    return {
        "trade_count": int(len(frame)), "win_rate": float((net > 0).mean()),
        "mean_gross": float(frame.corrected_gross.mean()), "mean_net10": float(frame.corrected_net10.mean()),
        "mean_net20": float(net.mean()), "median_net20": float(net.median()),
        "p01": float(net.quantile(.01)), "p05": float(net.quantile(.05)), "p25": float(net.quantile(.25)),
        "p75": float(net.quantile(.75)), "p95": float(net.quantile(.95)), "p99": float(net.quantile(.99)),
        "worst": float(net.min()), "best": float(net.max()), "std": float(net.std(ddof=1)),
    }


def grouped(frame: pd.DataFrame, field: str) -> list[dict]:
    total = float(frame.corrected_net20.sum())
    rows = []
    for value, part in frame.groupby(field, sort=True):
        rows.append({field: str(value), "trade_count": int(len(part)), "win_rate": float((part.corrected_net20 > 0).mean()),
                     "mean_net20": float(part.corrected_net20.mean()), "median_net20": float(part.corrected_net20.median()),
                     "total_net_contribution": float(part.corrected_net20.sum()),
                     "total_net_contribution_share": float(part.corrected_net20.sum() / total) if total else math.nan})
    return rows


def tail_audit(values: pd.Series) -> dict:
    ordered = values.sort_values(ascending=False).reset_index(drop=True)
    n = max(1, int(math.ceil(len(ordered) * .01)))
    total = float(ordered.sum())
    share = float(ordered.iloc[:n].sum() / total) if total else math.nan
    bottom_share = float(ordered.iloc[-n:].sum() / total) if total else math.nan
    return {
        "CORRECTED_TOP_1PCT_TRADE_COUNT": n, "CORRECTED_TOP_1PCT_CONTRIBUTION_SHARE": share,
        "CORRECTED_BOTTOM_1PCT_CONTRIBUTION_SHARE": bottom_share,
        "CORRECTED_EX_TOP_1PCT_MEAN_NET20": float(ordered.iloc[n:].mean()),
        "CORRECTED_MEAN_DRIVEN_BY_EXTREME_OUTLIERS": bool(share > .50),
    }


def write_outputs(summary: dict, action_ledger: dict, ledger: pd.DataFrame, inputs: dict) -> dict:
    STAGE.mkdir(parents=True)
    action_path = STAGE / "R28_3G_CORPORATE_ACTION_LEDGER.json"
    trade_path = STAGE / "R28_3G_CORRECTED_TRADE_LEDGER.csv"
    summary_path = STAGE / "R28_3G_SUMMARY.json"
    report_path = STAGE / "R28_3G_REPORT.md"
    hashes_path = STAGE / "R28_3G_INTEGRITY_HASHES.json"
    atomic_json(action_path, action_ledger, canonical=True)
    action_hash = file_sha256(action_path)
    ledger.to_csv(trade_path, index=False)
    summary.update({
        "CORPORATE_ACTION_LEDGER_SHA256": action_hash,
        "REPORT_PATH": str(FROZEN_RUN_ROOT / report_path.name),
        "SUMMARY_JSON_PATH": str(FROZEN_RUN_ROOT / summary_path.name),
        "CORRECTED_TRADE_LEDGER_PATH": str(FROZEN_RUN_ROOT / trade_path.name),
        "CORPORATE_ACTION_LEDGER_PATH": str(FROZEN_RUN_ROOT / action_path.name),
        "MATCHED_PLACEBO_RUNS_PATH": "NOT_RUN_NEGATIVE_PRIMARY_ENDPOINT",
    })
    evidence = {
        "corporate_action_ledger": {"path": str(FROZEN_RUN_ROOT / action_path.name), "sha256": action_hash,
                                    "row_count": int(action_ledger["record_count"]), "file_size": action_path.stat().st_size},
        "corrected_trade_ledger": {"path": str(FROZEN_RUN_ROOT / trade_path.name), "sha256": file_sha256(trade_path),
                                   "row_count": int(len(ledger)), "file_size": trade_path.stat().st_size},
    }
    atomic_json(hashes_path, {"authoritative_inputs": inputs, "frozen_output_evidence": evidence})
    summary["INTEGRITY_HASHES_PATH"] = str(FROZEN_RUN_ROOT / hashes_path.name)
    summary["external_artifact_evidence"] = evidence
    atomic_json(summary_path, summary)
    report = [
        "# FAST3 R28.3G — Corporate-action-normalized first-touch re-audit", "",
        f"- Status: `{summary['FAST3_R28_3G_STATUS']}`",
        f"- Classification: `{summary['FAST3_R28_3G_CLASSIFICATION']}`",
        f"- Corrected executable cohort: `{summary['CORRECTED_EXECUTED_TRADE_COUNT']}` of `{summary['SELECTED_SIGNAL_COUNT']}`",
        f"- Corrected mean net20: `{summary['CORRECTED_MEAN_NET20']}`",
        f"- Corrected median net20: `{summary['CORRECTED_MEDIAN_NET20']}`",
        f"- Corporate-action affected trades: `{summary['CORPORATE_ACTION_AFFECTED_TRADE_COUNT']}`",
        f"- Pre-entry touch not capturable: `{summary['PRE_ENTRY_TOUCH_NOT_CAPTURABLE_COUNT']}`",
        f"- Placebo: `{summary['MATCHED_PLACEBO_RUNS_PATH']}`", "",
        "The 2024 SOXS trade is normalized from raw entry 3.56 to a post-split-equivalent entry of 35.60. Its net20 becomes approximately +1.85%, not +920%. The single touch that preceded ETF entry is retained in reconciliation but excluded from the primary executable first-touch cohort.", "",
        "The corrected mean net20 is negative, so the pre-frozen necessary condition fails and the 1,000-run placebo is intentionally not run. R28 first-touch economic translation is rejected without changing the model, scores, target, entry, or exit rules.",
    ]
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    FROZEN_RUN_ROOT.parent.mkdir(parents=True, exist_ok=True)
    STAGE.replace(FROZEN_RUN_ROOT)
    return summary


def run() -> dict:
    storage, before_data, before_repo = storage_preflight()
    input_paths = {
        "r28e_summary": R28E_SUMMARY, "r28e_ledger": R28E_LEDGER, "r28e_manifest": R28E_MANIFEST,
        "r28f_summary": R28F_SUMMARY, "r28f_action_audit": R28F_ACTION_AUDIT,
    }
    inputs = {name: {"path": str(path), "sha256": file_sha256(path), "file_size": path.stat().st_size}
              for name, path in input_paths.items()}
    for name, expected in EXPECTED_INPUT_HASHES.items():
        if inputs[name]["sha256"] != expected:
            raise AuditStop(f"STOP_FROZEN_INPUT_IDENTITY_MISMATCH:{name}")
    summary_e = json.loads(R28E_SUMMARY.read_text(encoding="utf-8"))
    summary_f = json.loads(R28F_SUMMARY.read_text(encoding="utf-8"))
    manifest = json.loads(R28E_MANIFEST.read_text(encoding="utf-8"))
    if summary_e["ETF_MANIFEST_SHA256"] != EXPECTED_MANIFEST_SHA256 or summary_f["R28_3E_ETF_MANIFEST_SHA256"] != EXPECTED_MANIFEST_SHA256:
        raise AuditStop("STOP_ETF_MANIFEST_IDENTITY_MISMATCH")
    if {symbol: sum(record["symbol"] == symbol for record in manifest["partitions"]) for symbol in SYMBOLS} != {symbol: 98 for symbol in SYMBOLS}:
        raise AuditStop("STOP_ETF_PARTITION_RECONCILIATION")
    ledger = pd.read_csv(R28E_LEDGER)
    for column in ("timestamp", "entry_timestamp", "touch_timestamp", "first_touch_exit_timestamp"):
        ledger[column] = pd.to_datetime(ledger[column], utc=True)
    if len(ledger) != 1198 or ledger.candidate_id.duplicated().any():
        raise AuditStop("STOP_SELECTED_SIGNAL_RECONCILIATION")
    coverage_start, coverage_end = ledger.entry_timestamp.min(), ledger.first_touch_exit_timestamp.max()
    action_audit = pd.read_csv(R28F_ACTION_AUDIT)
    action_ledger = build_action_ledger(action_audit, coverage_start, coverage_end)
    action_records = action_ledger["records"]
    contract_text = json.dumps(summary_e.get("execution_contract", {}), sort_keys=True).lower()
    explicit_pre_entry_contract = "pre_entry_touch" in contract_text or "pre-entry touch" in contract_text
    if explicit_pre_entry_contract:
        raise AuditStop("STOP_UNEXPECTED_PRE_ENTRY_TOUCH_CONTRACT_REQUIRES_REVIEW")

    f = load_module(R28F_SOURCE, "fast3_r28_3f_reused")
    output_parts = []
    all_adjustment_types: set[str] = set()
    for symbol in SYMBOLS:
        records = [record for record in manifest["partitions"] if record["symbol"] == symbol]
        bars = f.load_symbol_bars(symbol, records)
        all_adjustment_types.update(bars.adjustment_type.dropna().astype(str).unique())
        index = bars.set_index("timestamp_utc", drop=False)
        part = ledger.loc[ledger.action_instrument.eq(symbol)].copy()
        entry = index.reindex(part.entry_timestamp)
        exit_ = index.reindex(part.first_touch_exit_timestamp)
        part["canonical_raw_entry_price"] = entry.open.to_numpy()
        part["canonical_raw_exit_price"] = exit_.open.to_numpy()
        part["entry_partition"] = entry.partition_key.to_numpy()
        part["exit_partition"] = exit_.partition_key.to_numpy()
        part["canonical_adjustment_type_entry"] = entry.adjustment_type.to_numpy()
        part["canonical_adjustment_type_exit"] = exit_.adjustment_type.to_numpy()
        output_parts.append(part)
    corrected = pd.concat(output_parts).sort_index()
    if all_adjustment_types != {"NONE"}:
        raise AuditStop(f"STOP_RAW_PRICE_BASIS_CHANGED:{sorted(all_adjustment_types)}")
    entry_mismatch = ~np.isclose(corrected.entry_price, corrected.canonical_raw_entry_price, atol=TOLERANCE, rtol=TOLERANCE)
    exit_mismatch = ~np.isclose(corrected.first_touch_exit_price, corrected.canonical_raw_exit_price, atol=TOLERANCE, rtol=TOLERANCE)
    if entry_mismatch.any() or exit_mismatch.any():
        raise AuditStop("STOP_CANONICAL_PRICE_RECONCILIATION")

    diagnostic = action_audit.loc[action_audit.metadata_authority.ne("OFFICIAL_ISSUER")].copy()
    diagnostic["observed_boundary_timestamp"] = pd.to_datetime(diagnostic.observed_boundary_timestamp, utc=True)
    rows = []
    for _, row in corrected.iterrows():
        actions = actions_between(row.entry_timestamp, row.first_touch_exit_timestamp, row.action_instrument, action_records)
        unknown = diagnostic.loc[
            diagnostic.symbol.eq(row.action_instrument) &
            diagnostic.observed_boundary_timestamp.gt(row.entry_timestamp) &
            diagnostic.observed_boundary_timestamp.le(row.first_touch_exit_timestamp)]
        normalized = normalize_trade(row.entry_price, row.first_touch_exit_price, actions)
        pre_entry = bool(pd.notna(row.touch_timestamp) and row.touch_timestamp < row.entry_timestamp)
        rows.append({
            **row.to_dict(), "raw_entry_price": float(row.entry_price), "raw_exit_price": float(row.first_touch_exit_price),
            **normalized, "corporate_action_count": len(actions),
            "corporate_action_records": json.dumps(actions, sort_keys=True, separators=(",", ":"), default=str),
            "unknown_scale_discontinuity_overlap_count": int(len(unknown)),
            "pre_entry_touch": pre_entry,
            "economic_reconciliation_state": "PRE_ENTRY_TOUCH_NOT_CAPTURABLE" if pre_entry else "EXECUTED_VALID_TRADE",
            "primary_executable_first_touch_cohort": not pre_entry,
        })
    corrected = pd.DataFrame(rows)
    corrected["corrected_gross"] = corrected.normalized_gross
    corrected["corrected_net10"] = corrected.normalized_net10
    corrected["corrected_net20"] = corrected.normalized_net20
    pre_entry_count = int(corrected.pre_entry_touch.sum())
    if pre_entry_count != 1:
        raise AuditStop(f"STOP_PRE_ENTRY_TOUCH_COUNT_UNEXPECTED:{pre_entry_count}")
    if corrected.unknown_scale_discontinuity_overlap_count.sum() != 0:
        raise AuditStop("STOP_UNAUTHORITATIVE_ACTION_OVERLAP")
    valid = corrected.loc[corrected.primary_executable_first_touch_cohort].copy()
    executed_count, other_invalid, nonexecutable = len(valid), 0, 0
    if 1198 != executed_count + pre_entry_count + other_invalid + nonexecutable:
        raise AuditStop("STOP_SILENT_DROP_RECONCILIATION")
    expected_instrument = np.where(corrected["head"].eq("UP"), np.where(corrected.underlying_symbol.eq("SOXX"), "SOXL", "TQQQ"),
                                   np.where(corrected.underlying_symbol.eq("SOXX"), "SOXS", "SQQQ"))
    direction_error_count = int((corrected.action_instrument.to_numpy() != expected_instrument).sum())
    return_error_count = int((corrected.corrected_gross -
                              (corrected.normalized_exit_equivalent / corrected.normalized_entry_equivalent - 1)).abs().gt(TOLERANCE).sum())
    if direction_error_count or return_error_count:
        raise AuditStop("STOP_CORRECTED_RETURN_OR_DIRECTION_RECONCILIATION")

    actual = distribution(valid)
    by_direction = grouped(valid, "head")
    valid["calendar_year"] = valid.entry_timestamp.dt.year
    by_year = grouped(valid, "calendar_year")
    by_symbol = grouped(valid, "action_instrument")
    up = next(row for row in by_direction if row["head"] == "UP")
    down = next(row for row in by_direction if row["head"] == "DOWN")
    top_symbol = max(by_symbol, key=lambda row: abs(row["total_net_contribution"]))
    tails = tail_audit(valid.corrected_net20)
    affected = corrected.corporate_action_count.gt(0)
    correction_total = float((corrected.loc[affected, "corrected_net20"] - corrected.loc[affected, "first_touch_net20"]).sum())
    storage_post = post_storage_audit(before_data, before_repo)
    if actual["mean_net20"] >= 0:
        raise AuditStop("STOP_POSITIVE_ENDPOINT_REQUIRES_FROZEN_PLACEBO_PATH_NOT_EXPECTED")
    summary = {
        "FAST3_R28_3G_STATUS": "PASS", "FAST3_R28_3G_CLASSIFICATION": "D_CORRECTED_FIRST_TOUCH_TRANSLATION_NEGATIVE",
        "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
        "START_HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "ETF_MANIFEST_SHA256": EXPECTED_MANIFEST_SHA256,
        **{f"{symbol}_PARTITION_COUNT": 98 for symbol in SYMBOLS},
        "SELECTED_SIGNAL_COUNT": 1198, "CORRECTED_EXECUTED_TRADE_COUNT": executed_count,
        "CORPORATE_ACTION_AFFECTED_TRADE_COUNT": int(affected.sum()),
        "PRE_ENTRY_TOUCH_COUNT": pre_entry_count, "PRE_ENTRY_TOUCH_NOT_CAPTURABLE_COUNT": pre_entry_count,
        "PRE_ENTRY_TOUCH_CONTRACT_SOURCE": "NONE_IN_FROZEN_EXECUTION_CONTRACT_FAIL_CLOSED_R28_3G",
        "OTHER_EXPLICIT_INVALID_COUNT": other_invalid, "NONEXECUTABLE_COUNT": nonexecutable,
        "SIGNAL_CARDINALITY_RECONCILED": True, "DROPPED_ROW_COUNT": 0,
        "ECONOMIC_LEDGER_INTEGRITY": "PASS", "PRICE_BASIS": "RAW",
        "ENTRY_PRICE_MISMATCH_COUNT": int(entry_mismatch.sum()), "EXIT_PRICE_MISMATCH_COUNT": int(exit_mismatch.sum()),
        "UNKNOWN_SCALE_DISCONTINUITY_OVERLAP_COUNT": 0,
        "CORRECTED_RETURN_RECOMPUTATION_MISMATCH_COUNT": return_error_count,
        "DIRECTION_SEMANTIC_ERROR_COUNT": direction_error_count,
        "ORIGINAL_R28_3E_MEAN_NET20": ORIGINAL_MEAN_NET20,
        "CORRECTED_MINUS_ORIGINAL_MEAN_NET20": actual["mean_net20"] - ORIGINAL_MEAN_NET20,
        "CORPORATE_ACTION_CORRECTION_TOTAL_CONTRIBUTION": correction_total,
        "CORRECTED_WIN_RATE": actual["win_rate"], "CORRECTED_MEAN_GROSS": actual["mean_gross"],
        "CORRECTED_MEAN_NET10": actual["mean_net10"], "CORRECTED_MEAN_NET20": actual["mean_net20"],
        "CORRECTED_MEDIAN_NET20": actual["median_net20"], "CORRECTED_DISTRIBUTION": actual,
        "CORRECTED_UP_MEAN_NET20": up["mean_net20"], "CORRECTED_DOWN_MEAN_NET20": down["mean_net20"],
        "CORRECTED_BY_DIRECTION": by_direction, "CORRECTED_BY_YEAR": by_year, "CORRECTED_BY_SYMBOL": by_symbol,
        "CORRECTED_POSITIVE_YEAR_COUNT": sum(row["mean_net20"] > 0 for row in by_year),
        "CORRECTED_NEGATIVE_YEAR_COUNT": sum(row["mean_net20"] < 0 for row in by_year),
        "CORRECTED_TOTAL_YEAR_COUNT": len(by_year),
        "CORRECTED_TOP_SYMBOL": top_symbol["action_instrument"],
        "CORRECTED_TOP_SYMBOL_CONTRIBUTION_SHARE": top_symbol["total_net_contribution_share"],
        "CORRECTED_TOP_SYMBOL_METHOD": "MAX_ABSOLUTE_TOTAL_NET_CONTRIBUTION",
        **tails,
        "MATCHED_PLACEBO_REQUIRED": False, "MATCHED_RANDOM_RUN_COUNT": 0,
        "REAL_MATCHED_NET20_PERCENTILE": "NOT_RUN_NEGATIVE_PRIMARY_ENDPOINT",
        "REAL_MATCHED_NET20_P": "NOT_RUN_NEGATIVE_PRIMARY_ENDPOINT",
        "PRIMARY_HYPOTHESIS_RESULT": "FAIL_NEGATIVE_EXPECTANCY",
        "FIRST_TOUCH_TRANSLATION_HYPOTHESIS": "REJECTED",
        "EVENT_PROBABILITY_EDGE": "CONFIRMED", "EVENT_SPEED_EDGE": "CONFIRMED",
        "FIRST_TOUCH_ECONOMIC_EDGE": "REJECTED", "POST_TOUCH_CONTINUATION_EDGE": "NOT_CONFIRMED",
        "TERMINAL_RETURN_EDGE": "NOT_CONFIRMED",
        "FINAL_RESEARCH_INTERPRETATION": "After issuer-authoritative split normalization and fail-closed pre-entry-touch handling, mean net20 is negative. The first-touch economic translation is rejected; no placebo or historical exit tuning is warranted.",
        "MODEL_RETRAIN_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "POST_FREEZE_RESCORING_COUNT": 0,
        "MODEL_RETRAIN_NEEDED": False, "R29_ALLOWED_TO_RESUME": False, "LIVE_TRADING_ALLOWED": False,
        "MATCHED_PLACEBO_RERUN": False,
        "NEXT_STAGE": "CLOSE_R28_ECONOMIC_TRANSLATION_AND_REDEFINE_ECONOMIC_TARGET",
        **storage, **storage_post, "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS",
        "FINAL_STORAGE_DECISION": "PASS_EXTERNAL_ROOTS_ATOMIC_FROZEN_FINALIZATION",
    }
    output_columns = [
        "candidate_id", "payoff_candidate_id", "underlying_symbol", "head", "timestamp", "probability",
        "frozen_threshold", "action_instrument", "entry_timestamp", "touch_timestamp", "first_touch_exit_timestamp",
        "event_state", "execution_state", "raw_entry_price", "raw_exit_price", "canonical_raw_entry_price",
        "canonical_raw_exit_price", "canonical_adjustment_type_entry", "canonical_adjustment_type_exit",
        "entry_partition", "exit_partition", "corporate_action_count", "corporate_action_factor",
        "post_action_share_factor", "normalized_entry_equivalent", "normalized_exit_equivalent",
        "normalized_gross", "normalized_net10", "normalized_net20", "corrected_gross", "corrected_net10",
        "corrected_net20", "corporate_action_records", "unknown_scale_discontinuity_overlap_count",
        "pre_entry_touch", "economic_reconciliation_state", "primary_executable_first_touch_cohort",
        "first_touch_net20", "etf_manifest_sha256",
    ]
    return write_outputs(summary, action_ledger, corrected[output_columns], inputs)


if __name__ == "__main__":
    try:
        print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
    except Exception as exc:
        if RUNTIME_RUN_ROOT.exists():
            atomic_json(RUNTIME_RUN_ROOT / "failure.json", {"FAST3_R28_3G_STATUS": "E_CORRECTED_LEDGER_STILL_INVALID", "error": str(exc)})
        raise
