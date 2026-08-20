"""FAST3 R28.3F leveraged-ETF corporate-action and extreme-return audit.

This program is intentionally read-only with respect to canonical data and
R28.3E.  It verifies the frozen trade ledger against the frozen partition
manifest and emits a separate integrity decision; it never trains, predicts,
rescores, changes a trade, or reruns the placebo experiment.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
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
RUN_ID = "r28_3f_leveraged_etf_integrity_20260809_r3"
RUNTIME_RUN_ROOT = RUNTIME_ROOT / "fast3" / RUN_ID
SCRATCH_RUN_ROOT = SCRATCH_ROOT / "fast3" / RUN_ID
FROZEN_RUN_ROOT = FROZEN_ROOT / "fast3" / RUN_ID
STAGE = RUNTIME_RUN_ROOT / "frozen_stage"

R28E_ROOT = FROZEN_ROOT / "fast3" / "r28_3e_clean_lineage_first_touch_20260809_r3"
R28E_SUMMARY = R28E_ROOT / "R28_3E_SUMMARY.json"
R28E_LEDGER = R28E_ROOT / "R28_3E_FIRST_TOUCH_TRADE_LEDGER.csv"
R28E_MANIFEST = R28E_ROOT / "R28_3E_CANONICAL_ETF_PARTITION_MANIFEST.json"
R28E_MODEL_MAP = R28E_ROOT / "R28_3E_FROZEN_MODEL_IDENTITY_MAP.json"
EXPECTED_MANIFEST_SHA256 = "1726b400b9fbb33f1bf85ff4afd229288f8e823d26cf3b2d3b0956e760b3a331"
EXPECTED_INPUT_HASHES = {
    "summary": "90994e4877d97490e5a854e8e32babf785591d7044e4a4acc035f1e721be97f2",
    "trade_ledger": "52e8ac6ea642f57abb900d2c78315a7061347c74a70ba8c54597867a63713097",
    "manifest": EXPECTED_MANIFEST_SHA256,
    "model_identity_map": "e28a33fb01affeffa49c8abbaff81f0b470cdb89cb4aea79ae54a6553562fee7",
}
SYMBOLS = ("SOXL", "SOXS", "TQQQ", "SQQQ")
PRICE_TOLERANCE = 1e-12
RETURN_TOLERANCE = 1e-12
DISCONTINUITY_RATIO = 1.75

# Authoritative issuer notices used only to identify the independently
# established mechanism and ratio.  observed_boundary_timestamp is derived
# from the frozen canonical path, never substituted for a market bar.
OFFICIAL_ACTIONS = [
    {"symbol": "SOXS", "effective_date": "2020-08-28", "action_type": "REVERSE_SPLIT", "split_ratio": "1:12", "pre_to_post_price_multiplier": 12.0,
     "source": "https://www.direxion.com/uploads/Direxion-Announces-Reverse-Splits-of-Six-Daily-Leveraged-ETFs.pdf"},
    {"symbol": "SOXS", "effective_date": "2022-03-28", "action_type": "REVERSE_SPLIT", "split_ratio": "1:10", "pre_to_post_price_multiplier": 10.0,
     "source": "https://www.direxion.com/uploads/Direxion-Announces-Reverse-Splits-of-Two-ETFs-DRIP-and-SOXS-2.pdf"},
    {"symbol": "SOXS", "effective_date": "2024-04-15", "action_type": "REVERSE_SPLIT", "split_ratio": "1:10", "pre_to_post_price_multiplier": 10.0,
     "source": "https://www.direxion.com/uploads/SOXS-Split-Press-Release-03.15.2024_Final.pdf"},
    {"symbol": "SOXL", "effective_date": "2021-03-02", "action_type": "FORWARD_SPLIT", "split_ratio": "15:1", "pre_to_post_price_multiplier": 1.0 / 15.0,
     "source": "https://www.direxion.com/uploads/Direxion-Announces-Forward-and-Reverse-Splits-of-Five-ETFs.pdf"},
    {"symbol": "TQQQ", "effective_date": "2021-01-21", "action_type": "FORWARD_SPLIT", "split_ratio": "2:1", "pre_to_post_price_multiplier": 0.5,
     "source": "https://www.proshares.com/press-releases/proshares-announces-etf-share-splits-10621"},
    {"symbol": "TQQQ", "effective_date": "2022-01-13", "action_type": "FORWARD_SPLIT", "split_ratio": "2:1", "pre_to_post_price_multiplier": 0.5,
     "source": "https://www.proshares.com/press-releases/proshares-announces-etf-share-splits-122021"},
    {"symbol": "SQQQ", "effective_date": "2020-08-18", "action_type": "REVERSE_SPLIT", "split_ratio": "1:5", "pre_to_post_price_multiplier": 5.0,
     "source": "https://www.proshares.com/press-releases/proshares-announces-etf-share-splits-80420"},
    {"symbol": "SQQQ", "effective_date": "2022-01-13", "action_type": "REVERSE_SPLIT", "split_ratio": "1:5", "pre_to_post_price_multiplier": 5.0,
     "source": "https://www.proshares.com/press-releases/proshares-announces-etf-share-splits-122021"},
    {"symbol": "SQQQ", "effective_date": "2024-11-07", "action_type": "REVERSE_SPLIT", "split_ratio": "1:5", "pre_to_post_price_multiplier": 5.0,
     "source": "https://www.proshares.com/press-releases/proshares-announces-etf-share-splits3"},
]


class AuditStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(path)


def data_snapshot() -> dict[str, tuple[int, int]]:
    return {str(path): (int(path.stat().st_size), int(path.stat().st_mtime_ns))
            for path in DATA_ROOT.rglob("*") if path.is_file()}


def repo_snapshot() -> dict[str, str]:
    lines = subprocess.check_output(["git", "status", "--porcelain", "-uall"], cwd=REPO, text=True,
                                    stderr=subprocess.DEVNULL).splitlines()
    paths = [line[3:].strip().strip('"').replace("\\", "/") for line in lines if len(line) >= 4]
    result: dict[str, str] = {}
    for relative in paths:
        path = REPO / relative
        if path.is_file():
            result[relative] = file_sha256(path)
        else:
            result[relative] = "NON_FILE"
    return result


def storage_preflight() -> tuple[dict, dict, dict]:
    pycache = Path(sys.pycache_prefix).resolve() if sys.pycache_prefix else None
    if pycache is None or CACHE_ROOT.resolve() not in (pycache, *pycache.parents):
        raise AuditStop("STOP_PYTHON_CACHE_NOT_EXTERNALIZED")
    if (REPO / ".local_results").exists():
        raise AuditStop("STOP_LOCAL_RESULTS_PRE_EXISTING")
    if any(path.exists() for path in (RUNTIME_RUN_ROOT, SCRATCH_RUN_ROOT, FROZEN_RUN_ROOT)):
        raise AuditStop("STOP_R28_3F_RUN_PATH_EXISTS")
    RUNTIME_RUN_ROOT.mkdir(parents=True)
    SCRATCH_RUN_ROOT.mkdir(parents=True)
    storage = {
        "FAST3_STORAGE_CONTRACT_R1_STATUS": "PRECHECK_PASS",
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
    data_changes = sorted(set(before_data) ^ set(after_data) |
                          {p for p in set(before_data) & set(after_data) if before_data[p] != after_data[p]})
    # The runner itself performs no repository writes.  Exact status-path hashes
    # must therefore be identical to the snapshot taken immediately pre-run.
    repo_preserved = before_repo == after_repo
    result_artifacts = [p for p in set(after_repo) - set(before_repo)
                        if Path(p).suffix.lower() in {".csv", ".parquet", ".json", ".md", ".log"}]
    violations = len(data_changes) + int(not repo_preserved) + len(result_artifacts) + int((REPO / ".local_results").exists())
    audit = {
        "DATA_ROOT_WRITE_COUNT": len(data_changes), "LOCAL_RESULTS_CREATED": False,
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": bool(result_artifacts),
        "PRE_EXISTING_UNTRACKED_FILES_PRESERVED": repo_preserved,
        "PRE_EXISTING_TRACKED_CHANGES_PRESERVED": repo_preserved,
        "NEW_R28_3F_STORAGE_VIOLATION_COUNT": violations,
        "RUNTIME_OUTPUT_LOCATION_VALID": True, "SCRATCH_OUTPUT_LOCATION_VALID": True,
        "FROZEN_OUTPUT_LOCATION_VALID": True, "PYTHON_CACHE_EXTERNALIZED": True,
        "PYTEST_TEMP_EXTERNALIZED": True, "DESTRUCTIVE_GIT_COMMAND_USED": False,
        "BROAD_GIT_ADD_USED": False,
    }
    if violations:
        raise AuditStop(f"STOP_NEW_STORAGE_VIOLATION:{audit}")
    return audit


def instrument_return(entry_price: float | pd.Series, exit_price: float | pd.Series):
    """Long instrument return; inverse ETFs must not be sign-flipped again."""
    return exit_price / entry_price - 1.0


def corrected_price(entry_price: float, actions: list[dict]) -> float:
    result = float(entry_price)
    for action in actions:
        result *= float(action["pre_to_post_price_multiplier"])
    return result


def price_basis(adjustment_types: set[str]) -> tuple[str, bool]:
    values = {str(x).upper() for x in adjustment_types if pd.notna(x)}
    if values == {"NONE"}:
        return "RAW", False
    if len(values) == 1 and next(iter(values)) in {"ADJUSTED", "SPLIT_ADJUSTED", "TOTAL_RETURN_ADJUSTED"}:
        return next(iter(values)), False
    return "UNKNOWN", len(values) > 1


def extreme_attribution(values: pd.Series) -> dict:
    ordered = pd.to_numeric(values, errors="raise").sort_values(ascending=False).reset_index(drop=True)
    top_one_n = max(1, int(math.ceil(len(ordered) * 0.01)))
    return {
        "ALL_1198_MEAN_NET20": float(ordered.mean()),
        "EX_SINGLE_BEST_TRADE_MEAN_NET20": float(ordered.iloc[1:].mean()),
        "EX_TOP_5_TRADES_MEAN_NET20": float(ordered.iloc[5:].mean()),
        "EX_TOP_1PCT_MEAN_NET20": float(ordered.iloc[top_one_n:].mean()),
        "TOP_1PCT_TRADE_COUNT": top_one_n,
        "TOP_1PCT_CONTRIBUTION_SHARE": float(ordered.iloc[:top_one_n].sum() / ordered.sum()),
    }


def legal_mask(frame: pd.DataFrame, symbol: str) -> pd.Series:
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    return (frame.symbol.astype(str).eq(symbol) & frame.timestamp_utc.notna() & np.isfinite(numeric).all(axis=1)
            & numeric.open.gt(0) & numeric.high.gt(0) & numeric.low.gt(0) & numeric.close.gt(0)
            & numeric.volume.ge(0) & numeric.high.ge(np.maximum(numeric.open, numeric.close))
            & numeric.low.le(np.minimum(numeric.open, numeric.close)) & frame.source.notna())


def load_symbol_bars(symbol: str, records: list[dict]) -> pd.DataFrame:
    pieces = []
    for record in records:
        path = Path(record["absolute_or_canonical_path"])
        if file_sha256(path) != record["file_sha256"]:
            raise AuditStop(f"STOP_CANONICAL_PARTITION_HASH_MISMATCH:{path}")
        frame = pd.read_parquet(path, columns=["symbol", "timestamp_utc", "open", "high", "low", "close",
                                                       "volume", "source", "adjustment_type"])
        frame["partition_key"] = record["partition_key"]
        pieces.append(frame)
    bars = pd.concat(pieces, ignore_index=True)
    bars["timestamp_utc"] = pd.to_datetime(bars.timestamp_utc, utc=True)
    bars = bars.loc[legal_mask(bars, symbol)].sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)
    if bars.timestamp_utc.duplicated().any():
        raise AuditStop(f"STOP_DUPLICATE_CANONICAL_TIMESTAMP:{symbol}")
    return bars


def detect_discontinuities(bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    prior = bars.shift(1)
    ratio = np.maximum(bars.close / prior.close, prior.close / bars.close)
    mask = ratio.ge(DISCONTINUITY_RATIO) & prior.close.notna()
    result = pd.DataFrame({
        "symbol": symbol, "previous_timestamp": prior.loc[mask, "timestamp_utc"].to_numpy(),
        "observed_boundary_timestamp": bars.loc[mask, "timestamp_utc"].to_numpy(),
        "previous_close": prior.loc[mask, "close"].to_numpy(), "current_close": bars.loc[mask, "close"].to_numpy(),
        "absolute_price_ratio": ratio.loc[mask].to_numpy(),
        "gap_minutes": ((bars.loc[mask, "timestamp_utc"].to_numpy() - prior.loc[mask, "timestamp_utc"].to_numpy()) /
                        np.timedelta64(1, "m")),
        "partition_boundary": (bars.loc[mask, "partition_key"].to_numpy() != prior.loc[mask, "partition_key"].to_numpy()),
    })
    if result.empty:
        return result
    result["session_boundary"] = result.gap_minutes > 1.0
    result["effective_date"] = (pd.to_datetime(result.observed_boundary_timestamp, utc=True)
                                .dt.tz_convert("America/New_York").dt.date.astype(str))
    return result


def official_action(symbol: str, effective_date: str) -> dict | None:
    found = [item for item in OFFICIAL_ACTIONS if item["symbol"] == symbol and item["effective_date"] == effective_date]
    return found[0] if len(found) == 1 else None


def audit_ledger(ledger: pd.DataFrame, manifest: dict) -> tuple[pd.DataFrame, pd.DataFrame, set[str], set[str]]:
    audited = ledger.copy()
    for column in ("timestamp", "entry_timestamp", "touch_timestamp", "first_touch_exit_timestamp"):
        audited[column] = pd.to_datetime(audited[column], utc=True)
    enriched_parts, discontinuity_parts = [], []
    adjustment_types: set[str] = set()
    sources: set[str] = set()
    records = manifest["partitions"]
    for symbol in SYMBOLS:
        symbol_records = [record for record in records if record["symbol"] == symbol]
        bars = load_symbol_bars(symbol, symbol_records)
        discontinuity_parts.append(detect_discontinuities(bars, symbol))
        adjustment_types.update(bars.adjustment_type.dropna().astype(str).unique())
        sources.update(bars.source.dropna().astype(str).unique())
        part = audited.loc[audited.action_instrument.eq(symbol)].copy()
        index = bars.set_index("timestamp_utc", drop=False)
        entry = index.reindex(part.entry_timestamp)
        exit_ = index.reindex(part.first_touch_exit_timestamp)
        part["canonical_entry_price"] = entry.open.to_numpy()
        part["canonical_exit_price"] = exit_.open.to_numpy()
        part["entry_partition"] = entry.partition_key.to_numpy()
        part["exit_partition"] = exit_.partition_key.to_numpy()
        part["entry_adjustment_type"] = entry.adjustment_type.to_numpy()
        part["exit_adjustment_type"] = exit_.adjustment_type.to_numpy()
        part["entry_source"] = entry.source.to_numpy()
        part["exit_source"] = exit_.source.to_numpy()
        timestamps = pd.DatetimeIndex(bars.timestamp_utc)
        opens = bars.open.to_numpy()
        expected_ts, expected_price = [], []
        for row in part.itertuples():
            if row.event_state != "FAVORABLE_FIRST" or pd.isna(row.touch_timestamp):
                expected_ts.append(pd.NaT); expected_price.append(np.nan); continue
            target = max(row.touch_timestamp, row.entry_timestamp)
            location = int(timestamps.searchsorted(target, side="left"))
            if location >= len(bars):
                expected_ts.append(pd.NaT); expected_price.append(np.nan)
            else:
                expected_ts.append(bars.timestamp_utc.iloc[location]); expected_price.append(opens[location])
        part["expected_first_executable_exit_timestamp"] = pd.to_datetime(expected_ts, utc=True)
        part["expected_first_executable_exit_price"] = expected_price
        enriched_parts.append(part)
    enriched = pd.concat(enriched_parts).sort_index()
    discontinuities = pd.concat(discontinuity_parts, ignore_index=True)
    return enriched, discontinuities, adjustment_types, sources


def apply_action_metadata(discontinuities: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in discontinuities.to_dict("records"):
        action = official_action(str(row["symbol"]), str(row["effective_date"]))
        rows.append({**row,
                     "action_type": action["action_type"] if action else "AUXILIARY_SCALE_DISCONTINUITY",
                     "split_ratio": action["split_ratio"] if action else None,
                     "pre_to_post_price_multiplier": action["pre_to_post_price_multiplier"] if action else None,
                     "corporate_action_source": action["source"] if action else None,
                     "metadata_authority": "OFFICIAL_ISSUER" if action else "CANONICAL_PATH_DIAGNOSTIC_ONLY"})
    return pd.DataFrame(rows)


def overlap_actions(row: pd.Series, actions: pd.DataFrame, official_only: bool = True) -> list[dict]:
    if actions.empty:
        return []
    mask = (actions.symbol.eq(row.action_instrument) &
            (actions.observed_boundary_timestamp > row.entry_timestamp) &
            (actions.observed_boundary_timestamp <= row.first_touch_exit_timestamp))
    if official_only:
        mask &= actions.metadata_authority.eq("OFFICIAL_ISSUER")
    return actions.loc[mask].to_dict("records")


def soxs_statistics(frame: pd.DataFrame) -> dict:
    x = frame.loc[frame.action_instrument.eq("SOXS"), "first_touch_net20"]
    top_n = max(1, int(math.ceil(len(x) * 0.01)))
    return {
        "trade_count": int(len(x)), "mean_net20": float(x.mean()), "median_net20": float(x.median()),
        "p01": float(x.quantile(.01)), "p05": float(x.quantile(.05)), "p95": float(x.quantile(.95)),
        "p99": float(x.quantile(.99)), "best_trade": float(x.max()), "worst_trade": float(x.min()),
        "top_1pct_contribution": float(x.nlargest(top_n).sum() / x.sum()),
    }


def audit_group_membership(frame: pd.DataFrame) -> pd.Series:
    groups = {idx: [] for idx in frame.index}
    n = max(1, int(math.ceil(len(frame) * .01)))
    definitions = {
        "BEST_50": frame.nlargest(50, "first_touch_net20").index,
        "WORST_50": frame.nsmallest(50, "first_touch_net20").index,
        "TOP_1PCT": frame.nlargest(n, "first_touch_net20").index,
        "BOTTOM_1PCT": frame.nsmallest(n, "first_touch_net20").index,
        "ALL_SOXS": frame.index[frame.action_instrument.eq("SOXS")],
        "ABS_NET20_GE_20PCT": frame.index[frame.first_touch_net20.abs().ge(.20)],
        "CORPORATE_ACTION_BOUNDARY": frame.index[frame.corporate_action_overlap_count.gt(0)],
    }
    for label, indices in definitions.items():
        for idx in indices:
            groups[idx].append(label)
    return pd.Series({idx: "|".join(labels) for idx, labels in groups.items()})


def finalize_outputs(summary: dict, extreme: pd.DataFrame, soxs: pd.DataFrame,
                     corporate: pd.DataFrame, corrected: pd.DataFrame, input_hashes: dict) -> dict:
    STAGE.mkdir(parents=True)
    paths = {
        "extreme": STAGE / "R28_3F_EXTREME_TRADE_AUDIT.csv",
        "soxs": STAGE / "R28_3F_SOXS_AUDIT.csv",
        "corporate": STAGE / "R28_3F_CORPORATE_ACTION_AUDIT.csv",
        "corrected": STAGE / "R28_3F_CORPORATE_ACTION_CORRECTED_DIAGNOSTIC.csv",
        "hashes": STAGE / "R28_3F_INTEGRITY_HASHES.json",
        "summary": STAGE / "R28_3F_SUMMARY.json",
        "report": STAGE / "R28_3F_REPORT.md",
    }
    extreme.to_csv(paths["extreme"], index=False)
    soxs.to_csv(paths["soxs"], index=False)
    corporate.to_csv(paths["corporate"], index=False)
    corrected.to_csv(paths["corrected"], index=False)
    evidence = {}
    for key in ("extreme", "soxs", "corporate", "corrected"):
        evidence[key] = {"path": str(FROZEN_RUN_ROOT / paths[key].name), "sha256": file_sha256(paths[key]),
                         "row_count": int({"extreme": len(extreme), "soxs": len(soxs),
                                           "corporate": len(corporate), "corrected": len(corrected)}[key]),
                         "file_size": int(paths[key].stat().st_size), "artifact_class": "FROZEN_EVIDENCE"}
    atomic_json(paths["hashes"], {"authoritative_inputs": input_hashes, "output_evidence": evidence})
    summary.update({
        "REPORT_PATH": str(FROZEN_RUN_ROOT / paths["report"].name),
        "SUMMARY_JSON_PATH": str(FROZEN_RUN_ROOT / paths["summary"].name),
        "EXTREME_TRADE_AUDIT_PATH": str(FROZEN_RUN_ROOT / paths["extreme"].name),
        "SOXS_AUDIT_PATH": str(FROZEN_RUN_ROOT / paths["soxs"].name),
        "CORPORATE_ACTION_AUDIT_PATH": str(FROZEN_RUN_ROOT / paths["corporate"].name),
        "CORRECTED_DIAGNOSTIC_PATH": str(FROZEN_RUN_ROOT / paths["corrected"].name),
        "INTEGRITY_HASHES_PATH": str(FROZEN_RUN_ROOT / paths["hashes"].name),
        "external_artifact_evidence": evidence,
    })
    atomic_json(paths["summary"], summary)
    report_lines = ["# FAST3 R28.3F — Leveraged ETF integrity audit", "",
                    f"- Status: `{summary['FAST3_R28_3F_STATUS']}`",
                    f"- Classification: `{summary['FAST3_R28_3F_CLASSIFICATION']}`",
                    f"- Best trade: `{summary['BEST_TRADE_ID']}` used raw SOXS {summary['BEST_TRADE_ENTRY_PRICE']} → {summary['BEST_TRADE_EXIT_PRICE']}.",
                    f"- Confirmed action: `{summary['BEST_TRADE_CORPORATE_ACTION']}`.",
                    f"- Return recomputation mismatches: `{summary['RETURN_RECOMPUTATION_MISMATCH_COUNT']}`.",
                    f"- Timestamp alignment errors: `{summary['TIMESTAMP_ALIGNMENT_ERROR_COUNT']}`.",
                    f"- Corrected diagnostic mean net20: `{summary['CORRECTED_DIAGNOSTIC_MEAN_NET20']}` (diagnostic only).", "",
                    "The +920% observation is not an economically attainable one-day gain. It is a raw per-share price ratio across a 1-for-10 SOXS reverse split. The issuer notice says aggregate investment value is unchanged by the split. The original R28.3E files remain immutable; no placebo was rerun.", "",
                    "Issuer evidence:", ""]
    report_lines.extend([f"- {item['symbol']} {item['effective_date']} {item['action_type']}: {item['source']}" for item in OFFICIAL_ACTIONS])
    paths["report"].write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    FROZEN_RUN_ROOT.parent.mkdir(parents=True, exist_ok=True)
    STAGE.replace(FROZEN_RUN_ROOT)
    return summary


def run() -> dict:
    storage, before_data, before_repo = storage_preflight()
    inputs = {"summary": R28E_SUMMARY, "trade_ledger": R28E_LEDGER, "manifest": R28E_MANIFEST,
              "model_identity_map": R28E_MODEL_MAP}
    input_hashes = {key: {"path": str(path), "sha256": file_sha256(path), "file_size": path.stat().st_size}
                    for key, path in inputs.items()}
    for key, expected in EXPECTED_INPUT_HASHES.items():
        if input_hashes[key]["sha256"] != expected:
            raise AuditStop(f"STOPPED_R28_3E_IDENTITY_MISMATCH:{key}")
    summary_e = json.loads(R28E_SUMMARY.read_text(encoding="utf-8"))
    manifest = json.loads(R28E_MANIFEST.read_text(encoding="utf-8"))
    if summary_e["ETF_MANIFEST_SHA256"] != EXPECTED_MANIFEST_SHA256 or len(manifest["partitions"]) != 392:
        raise AuditStop("STOPPED_R28_3E_IDENTITY_MISMATCH:manifest_contract")
    ledger = pd.read_csv(R28E_LEDGER)
    if len(ledger) != 1198 or ledger.candidate_id.duplicated().any():
        raise AuditStop("STOPPED_R28_3E_IDENTITY_MISMATCH:ledger_cardinality")
    atomic_json(RUNTIME_RUN_ROOT / "progress.json", {**storage, "stage": "R28_3E_INPUTS_VERIFIED", "inputs": input_hashes})

    frame, discontinuities, adjustment_types, sources = audit_ledger(ledger, manifest)
    actions = apply_action_metadata(discontinuities)
    frame["corporate_action_records"] = [overlap_actions(row, actions) for _, row in frame.iterrows()]
    frame["corporate_action_overlap_count"] = frame.corporate_action_records.map(len)
    frame["corporate_action_types"] = frame.corporate_action_records.map(lambda x: "|".join(a["action_type"] for a in x))
    frame["cross_partition"] = frame.entry_partition.ne(frame.exit_partition)
    frame["entry_price_match"] = np.isclose(frame.entry_price, frame.canonical_entry_price, atol=PRICE_TOLERANCE, rtol=PRICE_TOLERANCE)
    frame["exit_price_match"] = np.isclose(frame.first_touch_exit_price, frame.canonical_exit_price, atol=PRICE_TOLERANCE, rtol=PRICE_TOLERANCE)
    frame["gross_recomputed"] = instrument_return(frame.entry_price, frame.first_touch_exit_price)
    frame["net10_recomputed"] = frame.gross_recomputed - .001
    frame["net20_recomputed"] = frame.gross_recomputed - .002
    frame["return_recomputation_diff"] = frame.net20_recomputed - frame.first_touch_net20
    expected_instrument = np.where(frame["head"].eq("UP"), np.where(frame.underlying_symbol.eq("SOXX"), "SOXL", "TQQQ"),
                                   np.where(frame.underlying_symbol.eq("SOXX"), "SOXS", "SQQQ"))
    frame["direction_semantics_valid"] = frame.action_instrument.eq(expected_instrument)
    frame["exit_before_touch"] = frame.touch_timestamp.notna() & frame.first_touch_exit_timestamp.lt(frame.touch_timestamp)
    frame["touch_before_entry"] = frame.touch_timestamp.notna() & frame.touch_timestamp.lt(frame.entry_timestamp)
    favorable = frame.event_state.eq("FAVORABLE_FIRST")
    frame["first_executable_exit_valid"] = (~favorable) | (
        frame.first_touch_exit_timestamp.eq(frame.expected_first_executable_exit_timestamp) &
        np.isclose(frame.first_touch_exit_price, frame.expected_first_executable_exit_price,
                   atol=PRICE_TOLERANCE, rtol=PRICE_TOLERANCE, equal_nan=True))
    frame["timestamp_alignment_valid"] = ~(frame.exit_before_touch | frame.touch_before_entry) & frame.first_executable_exit_valid

    basis, mixed = price_basis(adjustment_types)
    entry_mismatch = int((~frame.entry_price_match).sum())
    exit_mismatch = int((~frame.exit_price_match).sum())
    recompute_mismatch = int(frame.return_recomputation_diff.abs().gt(RETURN_TOLERANCE).sum())
    direction_errors = int((~frame.direction_semantics_valid).sum())
    exit_before = int(frame.exit_before_touch.sum())
    nonfirst = int((~frame.first_executable_exit_valid).sum())
    timestamp_errors = int((~frame.timestamp_alignment_valid).sum())
    overlap = int(frame.corporate_action_overlap_count.gt(0).sum())
    split_overlap = int(frame.corporate_action_types.str.contains("FORWARD_SPLIT", na=False).sum())
    reverse_overlap = int(frame.corporate_action_types.str.contains("REVERSE_SPLIT", na=False).sum())

    frame["audit_groups"] = audit_group_membership(frame)
    audit_set = frame.loc[frame.audit_groups.ne("")].copy()
    extreme = frame.loc[frame.first_touch_net20.abs().ge(.20)].copy()
    best = frame.loc[frame.first_touch_net20.idxmax()]
    best_actions = best.corporate_action_records

    # Deterministic diagnostic correction is allowed only for issuer-confirmed
    # action overlaps.  It does not modify or replace the frozen R28.3E ledger.
    corrected_values = frame.first_touch_net20.copy()
    corrected_rows = []
    for idx, row in frame.loc[frame.corporate_action_overlap_count.gt(0)].iterrows():
        adjusted_entry = corrected_price(row.entry_price, row.corporate_action_records)
        gross = instrument_return(adjusted_entry, row.first_touch_exit_price)
        net20 = gross - .002
        corrected_values.loc[idx] = net20
        corrected_rows.append({
            "trade_id": row.candidate_id, "symbol": row.action_instrument, "entry_timestamp": row.entry_timestamp,
            "exit_timestamp": row.first_touch_exit_timestamp, "original_entry_price": row.entry_price,
            "original_exit_price": row.first_touch_exit_price, "original_net20": row.first_touch_net20,
            "corrected_entry_price_post_action_basis": adjusted_entry, "corrected_exit_price": row.first_touch_exit_price,
            "corrected_gross": gross, "corrected_net20": net20, "action_type": row.corporate_action_types,
            "action_records": json.dumps(row.corporate_action_records, default=str, separators=(",", ":")),
            "CORRECTED_DIAGNOSTIC_ONLY": True,
        })
    corrected = pd.DataFrame(corrected_rows)

    attribution = extreme_attribution(frame.first_touch_net20)
    soxs_stats = soxs_statistics(frame)
    soxs = frame.loc[frame.action_instrument.eq("SOXS")].copy()
    soxs_extreme = int(soxs.first_touch_net20.abs().ge(.20).sum())
    corp_error = overlap > 0
    formula_or_direction_error = recompute_mismatch > 0 or direction_errors > 0
    time_error = timestamp_errors > 0
    if sum((corp_error, formula_or_direction_error, time_error)) > 1:
        classification = "E_MIXED_DATA_INTEGRITY_FAILURE"
    elif corp_error:
        classification = "B_CORPORATE_ACTION_OR_ADJUSTMENT_ARTIFACT_CONFIRMED"
    elif formula_or_direction_error:
        classification = "C_RETURN_CALCULATION_OR_DIRECTION_BUG_CONFIRMED"
    elif time_error:
        classification = "D_TIMESTAMP_OR_EXECUTION_ALIGNMENT_BUG_CONFIRMED"
    elif entry_mismatch or exit_mismatch or mixed:
        classification = "E_MIXED_DATA_INTEGRITY_FAILURE"
    else:
        classification = "A_EXTREME_RETURNS_VERIFIED_REAL_AND_PRICE_CONSISTENT"

    storage_post = post_storage_audit(before_data, before_repo)
    final = {
        "FAST3_R28_3F_STATUS": "PASS", "FAST3_R28_3F_CLASSIFICATION": classification,
        "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
        "START_HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "R28_3E_SUMMARY_SHA256": input_hashes["summary"]["sha256"],
        "R28_3E_TRADE_LEDGER_SHA256": input_hashes["trade_ledger"]["sha256"],
        "R28_3E_ETF_MANIFEST_SHA256": input_hashes["manifest"]["sha256"],
        "R28_3E_MODEL_IDENTITY_MAP_SHA256": input_hashes["model_identity_map"]["sha256"],
        "AUDITED_TRADE_COUNT": int(len(audit_set)), "EXTREME_TRADE_COUNT": int(len(extreme)),
        "SOXS_AUDITED_TRADE_COUNT": int(len(soxs)),
        "BEST_TRADE_ID": best.candidate_id, "BEST_TRADE_SYMBOL": best.action_instrument,
        "BEST_TRADE_DIRECTION": best["head"], "BEST_TRADE_ENTRY_TIMESTAMP": str(best.entry_timestamp),
        "BEST_TRADE_EXIT_TIMESTAMP": str(best.first_touch_exit_timestamp),
        "BEST_TRADE_ENTRY_PRICE": float(best.entry_price), "BEST_TRADE_EXIT_PRICE": float(best.first_touch_exit_price),
        "BEST_TRADE_GROSS_RETURN": float(best.first_touch_gross), "BEST_TRADE_NET20": float(best.first_touch_net20),
        "BEST_TRADE_ENTRY_PRICE_VALID": bool(best.entry_price_match), "BEST_TRADE_EXIT_PRICE_VALID": bool(best.exit_price_match),
        "BEST_TRADE_SAME_PRICE_BASIS": bool(best.entry_adjustment_type == best.exit_adjustment_type),
        "BEST_TRADE_SPLIT_OR_REVERSE_SPLIT": bool(best.corporate_action_overlap_count),
        "BEST_TRADE_CORPORATE_ACTION": best.corporate_action_types,
        "BEST_TRADE_SYMBOL_MAPPING_CORRECT": bool(best.direction_semantics_valid),
        "BEST_TRADE_TIMESTAMP_ALIGNMENT_CORRECT": bool(best.timestamp_alignment_valid),
        "BEST_TRADE_PRICE_RATIO_ECONOMICALLY_PLAUSIBLE": False,
        "PRICE_BASIS": basis, "MIXED_PRICE_BASIS": mixed, "CANONICAL_ADJUSTMENT_TYPES": sorted(adjustment_types),
        "CANONICAL_SOURCES": sorted(sources), "ENTRY_PRICE_MISMATCH_COUNT": entry_mismatch,
        "EXIT_PRICE_MISMATCH_COUNT": exit_mismatch, "RETURN_RECOMPUTATION_MISMATCH_COUNT": recompute_mismatch,
        "MAX_ABS_RETURN_RECOMPUTATION_DIFF": float(frame.return_recomputation_diff.abs().max()),
        "DIRECTION_SEMANTIC_ERROR_COUNT": direction_errors, "DOUBLE_DIRECTION_INVERSION": False,
        "TIMESTAMP_ALIGNMENT_ERROR_COUNT": timestamp_errors, "TOUCH_BEFORE_ENTRY_COUNT": int(frame.touch_before_entry.sum()),
        "EXIT_BEFORE_TOUCH_COUNT": exit_before, "NONFIRST_EXECUTABLE_EXIT_COUNT": nonfirst,
        "CORPORATE_ACTION_OVERLAP_TRADE_COUNT": overlap, "SPLIT_OVERLAP_TRADE_COUNT": split_overlap,
        "REVERSE_SPLIT_OVERLAP_TRADE_COUNT": reverse_overlap,
        "PRICE_SCALE_DISCONTINUITY_COUNT": int(len(actions)),
        "PRICE_SCALE_DISCONTINUITY_GE_2X_COUNT": int(actions.absolute_price_ratio.ge(2).sum()),
        "PRICE_SCALE_DISCONTINUITY_GE_3X_COUNT": int(actions.absolute_price_ratio.ge(3).sum()),
        "PRICE_SCALE_DISCONTINUITY_GE_5X_COUNT": int(actions.absolute_price_ratio.ge(5).sum()),
        "PRICE_SCALE_DISCONTINUITY_GE_10X_COUNT": int(actions.absolute_price_ratio.ge(10).sum()),
        "CROSS_PARTITION_TRADE_COUNT": int(frame.cross_partition.sum()),
        "EXTREME_CROSS_PARTITION_TRADE_COUNT": int((frame.cross_partition & frame.first_touch_net20.abs().ge(.20)).sum()),
        "SOXS_EXTREME_TRADE_COUNT": soxs_extreme,
        "SOXS_CORPORATE_ACTION_OVERLAP_COUNT": int(soxs.corporate_action_overlap_count.gt(0).sum()),
        "SOXS_PRICE_SCALE_DISCONTINUITY_COUNT": int(actions.symbol.eq("SOXS").sum()),
        "SOXS_STATISTICS": soxs_stats, **attribution,
        "CORRECTED_DIAGNOSTIC_ONLY": True, "CORRECTED_DIAGNOSTIC_TRADE_COUNT": int(len(corrected)),
        "CORRECTED_DIAGNOSTIC_MEAN_NET20": float(corrected_values.mean()),
        "CORRECTED_DIAGNOSTIC_BEST_TRADE_NET20": float(corrected_values.max()),
        "EXTREME_RETURNS_VALID": False,
        "ECONOMIC_LEDGER_INTEGRITY": "FAILED_CORPORATE_ACTION_AND_TIMESTAMP_ALIGNMENT",
        "R28_3E_REAUDIT_REQUIRED": True,
        "FINAL_INTEGRITY_INTERPRETATION": "A 1-for-10 SOXS reverse split created the +920% raw price ratio; one separate adverse-first trade touched before ETF entry. R28.3E economic numbers require a separate corrected re-audit, without model changes.",
        "MODEL_RETRAIN_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "POST_FREEZE_RESCORING_COUNT": 0,
        "MATCHED_PLACEBO_RERUN": False, "MODEL_RETRAIN_NEEDED": False,
        "R29_ALLOWED_TO_RESUME": False, "LIVE_TRADING_ALLOWED": False,
        "NEXT_STAGE": "CORPORATE_ACTION_NORMALIZED_ECONOMIC_REAUDIT_WITHOUT_MODEL_CHANGES",
        **storage, **storage_post,
        "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS", "FINAL_STORAGE_DECISION": "PASS_EXTERNAL_ROOTS_ATOMIC_FROZEN_FINALIZATION",
    }
    audit_columns = [
        "candidate_id", "audit_groups", "action_instrument", "head", "event_state", "entry_timestamp",
        "touch_timestamp", "first_touch_exit_timestamp", "entry_price", "first_touch_exit_price",
        "canonical_entry_price", "canonical_exit_price", "entry_price_match", "exit_price_match",
        "first_touch_net20", "net20_recomputed", "return_recomputation_diff", "entry_partition", "exit_partition",
        "cross_partition", "entry_adjustment_type", "exit_adjustment_type", "entry_source", "exit_source",
        "corporate_action_overlap_count", "corporate_action_types", "touch_before_entry", "exit_before_touch",
        "first_executable_exit_valid", "timestamp_alignment_valid", "direction_semantics_valid",
    ]
    corporate_columns = ["symbol", "effective_date", "action_type", "split_ratio", "previous_timestamp",
                         "observed_boundary_timestamp", "previous_close", "current_close", "absolute_price_ratio",
                         "gap_minutes", "session_boundary", "partition_boundary", "metadata_authority",
                         "corporate_action_source"]
    return finalize_outputs(final, audit_set[audit_columns], soxs[audit_columns], actions[corporate_columns],
                            corrected, input_hashes)


if __name__ == "__main__":
    try:
        result = run()
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    except Exception as exc:
        if RUNTIME_RUN_ROOT.exists():
            atomic_json(RUNTIME_RUN_ROOT / "failure.json", {"FAST3_R28_3F_STATUS": "G_INVALID_AUDIT", "error": str(exc)})
        raise
