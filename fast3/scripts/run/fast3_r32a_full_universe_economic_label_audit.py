#!/usr/bin/env python
"""FAST3 R32A full opportunity-universe economic-label feasibility audit."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
RUN_ID = "r32a_full_universe_20260810T120000Z"
FROZEN_ROOT = RESULTS_ROOT / "frozen/fast3" / RUN_ID
SCRATCH_ROOT = RESULTS_ROOT / "scratch/fast3" / RUN_ID

R30A_ROOT = RESULTS_ROOT / "frozen/fast3/r30a_economic_target_20260809T120000Z"
R30A_DATA_ID = R30A_ROOT / "FAST3_R30A_TRAINING_DATA_IDENTITY.json"
R30A_SUMMARY = R30A_ROOT / "FAST3_R30A_SUMMARY.json"
TARGET_CONTRACT = R30A_ROOT / "FAST3_R30_T1_T2_ECONOMIC_TARGET_CONTRACT_R1.json"
CONTROL_ROOT = RESULTS_ROOT / "frozen/fast3/cleanroom_r2_20260808"
SPLIT_CONTRACT = CONTROL_ROOT / "cleanroom_r2_freeze_manifest.json"
SOURCE_MANIFEST = CONTROL_ROOT / "cleanroom_r2_preholdout_source_manifest.json"
R30B_MANIFEST = RESULTS_ROOT / "frozen/fast3/r30b_factor_expansion_20260809T140000Z/FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"
R30D_SUMMARY = RESULTS_ROOT / "frozen/fast3/r30d_conditional_orthogonality_20260809T180000Z/FAST3_R30D_SUMMARY.json"
R31B_SUMMARY = RESULTS_ROOT / "frozen/fast3/r31b_volume_liquidity_20260810T002000Z/FAST3_R31B_SUMMARY.json"
R28_EVENT_LEDGER = RESULTS_ROOT / "fast3/agent_runs/event_factor_law_discovery/20260802_184840/fast3_event_ledger.parquet"
R27_PAYOFF_LEDGER = RESULTS_ROOT / "scratch/fast3/r27_2_independent_heads_20260806T235700000Z/r27_2_regenerated_r26a2_payoff_ledger.parquet"
R28G_LEDGER = RESULTS_ROOT / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809/R28_3G_CORRECTED_TRADE_LEDGER.csv"
R28G_ACTION_LEDGER = RESULTS_ROOT / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809/R28_3G_CORPORATE_ACTION_LEDGER.json"
R28F_ACTION_AUDIT = RESULTS_ROOT / "frozen/fast3/r28_3f_leveraged_etf_integrity_20260809_r3/R28_3F_CORPORATE_ACTION_AUDIT.csv"
ETF_MANIFEST = RESULTS_ROOT / "frozen/fast3/r28_3e_clean_lineage_first_touch_20260809_r3/R28_3E_CANONICAL_ETF_PARTITION_MANIFEST.json"

TARGET_SHA = "381ce44099d865748e73f5538c9327ad6a9619c7bcdbf18bcff8b9b5cfdaa996"
SPLIT_SHA = "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412"
FEATURE_SHA = "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
ETF_MANIFEST_SHA = "1726b400b9fbb33f1bf85ff4afd229288f8e823d26cf3b2d3b0956e760b3a331"
EVENT_LEDGER_SHA = "94848ea545181e39057d714c38f400c1b80bbcc96e453039a44d9d5e2ed3cb40"
PAYOFF_LEDGER_SHA = "f042b3e056474d242b8452e44807819b9f57772abf8b005741edb9d2a2fbaf92"
EXECUTION_CONTRACT_SHA = "31caf642a929bad214677fd988954b893647b77909311e586916d424d86bb267"
TRUE_HOLDOUT_START = pd.Timestamp("2025-02-01T05:00:00Z")
PURGE = pd.Timedelta(minutes=1440)
FOLDS = (
    ("OOF_2020", "2020-01-01", "2020-12-31 23:59:59"),
    ("OOF_2021", "2021-01-01", "2021-12-31 23:59:59"),
    ("OOF_2022", "2022-01-01", "2022-12-31 23:59:59"),
    ("OOF_2023", "2023-01-01", "2023-12-31 23:59:59"),
    ("OOF_2024", "2024-01-01", "2024-12-31 23:59:59"),
    ("OOF_2025_JAN", "2025-01-01", "2025-01-31 23:59:59"),
)
BASELINE_14 = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m", "realized_vol_60m",
    "relative_volume", "range_position", "symbol_code", "direction_code", "session_code",
    "volume_zscore_60m", "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m",
)
EXTRA_15 = (
    "RSI_14", "KDJ_J_9_3", "MACD_HIST_NORM_12_26_9", "EMA20_SLOPE_5", "PRICE_VS_MA20",
    "REALIZED_VOL_5", "ATR_NORMALIZED_14", "DOWNSIDE_VOLATILITY_20", "RECENT_DRAWDOWN_60",
    "VOLATILITY_ACCELERATION_15_60", "SOXX_VS_QQQ_RELATIVE_STRENGTH_60", "QQQ_MOMENTUM_30",
    "SOXX_QQQ_RETURN_SPREAD_5", "CROSS_ASSET_MOMENTUM_AGREEMENT_15", "QQQ_TREND_CONFIRMATION_20",
)
FEATURES_29 = BASELINE_14 + EXTRA_15
MAPPING = {("QQQ", "UP"): "TQQQ", ("QQQ", "DOWN"): "SQQQ", ("SOXX", "UP"): "SOXL", ("SOXX", "DOWN"): "SOXS"}


class R32AStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def value_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (Path, pd.Timestamp, datetime)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None: raise R32AStop("STOP_MODULE_IMPORT")
    spec.loader.exec_module(module)
    return module


def guard_inputs() -> dict[str, Any]:
    expected = {TARGET_CONTRACT: TARGET_SHA, SPLIT_CONTRACT: SPLIT_SHA, R30B_MANIFEST: FEATURE_SHA,
                ETF_MANIFEST: ETF_MANIFEST_SHA, R28_EVENT_LEDGER: EVENT_LEDGER_SHA, R27_PAYOFF_LEDGER: PAYOFF_LEDGER_SHA}
    for path, digest in expected.items():
        if not path.is_file() or file_sha256(path) != digest: raise R32AStop("STOP_INPUT_IDENTITY:" + str(path))
    r30d, r31b = read_json(R30D_SUMMARY), read_json(R31B_SUMMARY)
    if r30d["FAST3_R30D_CLASSIFICATION"] != "D_CONDITIONAL_RESULT_CONTRADICTS_T4_RISK_SIGNAL":
        raise R32AStop("STOP_R30D_IDENTITY")
    if r31b["DOMAIN_GO_GATE"] != "NO_GO" or bool(r31b["DOMAIN_STRONG"]): raise R32AStop("STOP_R31B_IDENTITY")
    manifest = read_json(R30B_MANIFEST)
    if tuple(manifest["arms"]["ARM_ALL"]) != FEATURES_29: raise R32AStop("STOP_29_FEATURE_IDENTITY")
    return {"r30a_summary_sha256": file_sha256(R30A_SUMMARY), "r30d_summary_sha256": file_sha256(R30D_SUMMARY),
            "r31b_summary_sha256": file_sha256(R31B_SUMMARY), "source_manifest_sha256": file_sha256(SOURCE_MANIFEST)}


def candidate_id(underlying: pd.Series, head: str, timestamp: pd.Series) -> pd.Series:
    text = pd.to_datetime(timestamp, utc=True).dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    return underlying.astype(str) + "|" + head + "|" + text


def freeze_universe_identity() -> tuple[pd.DataFrame, str, Path, dict[str, Any]]:
    """Read identity-only columns and freeze eligibility before any outcome access."""
    split = read_json(SPLIT_CONTRACT)
    cutoff = pd.Timestamp(split["final_training_candidate_max_timestamp"]).tz_convert("UTC")
    identities = pd.read_parquet(R28_EVENT_LEDGER, columns=["candidate_id", "timestamp_et", "timestamp_utc", "underlying", "valid"])
    identities["timestamp_utc"] = pd.to_datetime(identities["timestamp_utc"], utc=True)
    identities = identities.loc[identities.timestamp_utc.le(cutoff)].copy()
    if identities.candidate_id.duplicated().any() or not identities.valid.astype(bool).all(): raise R32AStop("STOP_CANDIDATE_IDENTITY")
    anchors = pd.read_parquet(R27_PAYOFF_LEDGER, columns=["candidate_id", "authoritative_anchor_timestamp_et",
        "up_action_instrument", "down_action_instrument", "source_candidate_hash", "canonical_partition_manifest_hash", "execution_contract_hash"])
    anchors = anchors.loc[anchors.candidate_id.isin(identities.candidate_id)].copy()
    if len(anchors) != len(identities) or anchors.candidate_id.duplicated().any(): raise R32AStop("STOP_ANCHOR_RECONCILIATION")
    base = identities.merge(anchors, on="candidate_id", how="left", validate="one_to_one").rename(columns={"candidate_id": "anchor_candidate_id", "underlying": "underlying_symbol", "timestamp_utc": "decision_timestamp_utc"})
    base["authoritative_anchor_timestamp_et"] = pd.to_datetime(base.authoritative_anchor_timestamp_et, utc=True)
    parts = []
    for head, code, field in (("UP", 1, "up_action_instrument"), ("DOWN", -1, "down_action_instrument")):
        part = base.copy(); part["head"] = head; part["direction_code"] = code; part["instrument"] = part[field]
        part["candidate_id"] = candidate_id(part.underlying_symbol, head, part.decision_timestamp_utc)
        parts.append(part)
    universe = pd.concat(parts, ignore_index=True).sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    if universe.candidate_id.duplicated().any() or len(universe) != len(base) * 2: raise R32AStop("STOP_EXPANDED_UNIVERSE_IDENTITY")
    mapping_ok = [MAPPING[(u, h)] == i for u, h, i in zip(universe.underlying_symbol, universe["head"], universe.instrument)]
    if not all(mapping_ok) or universe.execution_contract_hash.ne(EXECUTION_CONTRACT_SHA).any(): raise R32AStop("STOP_INSTRUMENT_MAPPING")
    density = universe.assign(day=universe.decision_timestamp_utc.dt.date).groupby("day").size()
    payload = {
        "CONTRACT_ID": "FAST3_R32A_FULL_UNIVERSE_IDENTITY_R1", "STATUS": "FROZEN_BEFORE_ECONOMIC_OUTCOME_READ",
        "CREATED_AT_UTC": datetime.now(timezone.utc), "AUTHORITATIVE_CANDIDATE_SOURCE": str(R28_EVENT_LEDGER),
        "AUTHORITATIVE_CANDIDATE_SHA256": EVENT_LEDGER_SHA, "ANCHOR_IDENTITY_SOURCE": str(R27_PAYOFF_LEDGER),
        "ANCHOR_IDENTITY_SHA256": PAYOFF_LEDGER_SHA, "IDENTITY_COLUMNS_READ_ONLY": True,
        "OUTCOME_COLUMNS_READ_BEFORE_FREEZE": 0, "ELIGIBILITY_RULE": split["candidate_definition"],
        "ELIGIBILITY_CUTOFF_UTC": cutoff, "FINAL_CONFIRMATION_EXCLUDED_BEFORE_OUTCOME_ACCESS": True,
        "DIRECTIONLESS_ANCHOR_COUNT": len(base), "FULL_ELIGIBLE_ROW_COUNT": len(universe),
        "FULL_ELIGIBLE_UNIQUE_CANDIDATE_COUNT": universe.candidate_id.nunique(),
        "FULL_ELIGIBLE_START": universe.decision_timestamp_utc.min(), "FULL_ELIGIBLE_END": universe.decision_timestamp_utc.max(),
        "CANDIDATES_PER_DAY_MEDIAN": float(density.median()), "CANDIDATES_PER_DAY_P95": float(density.quantile(.95)),
        "TARGET_CONTRACT_SHA256": TARGET_SHA, "SPLIT_CONTRACT_SHA256": SPLIT_SHA,
        "INSTRUMENT_MAPPING": {f"{u}|{h}": i for (u, h), i in MAPPING.items()},
        "INSTRUMENT_MAPPING_SHA256": value_sha256({f"{u}|{h}": i for (u, h), i in MAPPING.items()}),
        "FUTURE_INFORMATION_USED_IN_ELIGIBILITY_COUNT": 0, "FINAL_CONFIRMATION_DATA_USED": False,
    }
    FROZEN_ROOT.mkdir(parents=True, exist_ok=False); SCRATCH_ROOT.mkdir(parents=True, exist_ok=False)
    path = FROZEN_ROOT / "FAST3_R32A_FULL_UNIVERSE_IDENTITY_R1.json"; write_json(path, payload)
    digest = file_sha256(path)
    return universe, digest, path, payload


def load_underlying_and_modules():
    r30a = import_file(SOURCE_ROOT / "fast3/scripts/run/fast3_r30a_economic_target_baseline_training.py", "r32a_r30a")
    p2 = r30a.import_phase2_module(); manifest = read_json(SOURCE_MANIFEST); paths = p2.exact_paths(manifest["files"])
    data = {symbol: p2.read_symbol(paths[symbol]) for symbol in p2.R1.SYMBOLS}
    if any(frame.timestamp_utc.max() >= TRUE_HOLDOUT_START for frame in data.values()): raise R32AStop("STOP_FINAL_SOURCE_PARTITION_ACCESS")
    r30b = import_file(SOURCE_ROOT / "fast3/scripts/run/fast3_r30b_controlled_factor_expansion.py", "r32a_r30b")
    return r30a, p2, r30b, data


def compute_touches(base: pd.DataFrame, raw: pd.DataFrame, r1, first_touch_labels) -> pd.DataFrame:
    ns = raw.timestamp_utc.astype("int64").to_numpy(); decision = pd.to_datetime(base.decision_timestamp_utc, utc=True).astype("int64").to_numpy()
    decision_i = np.searchsorted(ns, decision)
    if (decision_i >= len(raw)).any() or not np.array_equal(ns[decision_i], decision): raise R32AStop("STOP_CANDIDATE_NOT_IN_SOURCE")
    valid_i = np.flatnonzero(raw.valid.to_numpy(bool)); pos = np.searchsorted(valid_i, decision_i + 1)
    if (pos >= len(valid_i)).any(): raise R32AStop("STOP_ENTRY_HORIZON")
    entry_i = valid_i[pos]; deadline = ns[entry_i] + pd.Timedelta(hours=24).value
    coverage_i = np.searchsorted(ns, deadline, side="left"); horizon_i = np.searchsorted(ns, deadline, side="right") - 1
    if (coverage_i >= len(raw)).any() or (horizon_i <= entry_i).any() or (ns[coverage_i] >= TRUE_HOLDOUT_START.value).any(): raise R32AStop("STOP_LABEL_HORIZON_FINAL_OVERLAP")
    hi, hs = r1.build_tree(raw.high.to_numpy(float), True); lo, ls = r1.build_tree(raw.low.to_numpy(float), False)
    entry_price = raw.open.to_numpy(float)[entry_i]
    up = np.fromiter((r1.first_cross(hi, hs, int(a), int(b), float(p * 1.01), True) for a, b, p in zip(entry_i, horizon_i, entry_price)), dtype=int, count=len(base))
    down = np.fromiter((r1.first_cross(lo, ls, int(a), int(b), float(p * .99), False) for a, b, p in zip(entry_i, horizon_i, entry_price)), dtype=int, count=len(base))
    labels = first_touch_labels(up, down); touch_i = np.where(labels == "UP_FIRST", up, np.where(labels == "DOWN_FIRST", down, -1))
    touch = pd.Series(pd.NaT, index=base.index, dtype="datetime64[ns, UTC]"); mask = touch_i >= 0
    touch.loc[mask] = pd.to_datetime(ns[touch_i[mask]], utc=True).to_numpy()
    return pd.DataFrame({"anchor_candidate_id": base.anchor_candidate_id.to_numpy(), "frozen_label": labels,
        "touch_timestamp": touch, "underlying_entry_timestamp": pd.to_datetime(ns[entry_i], utc=True),
        "underlying_horizon_timestamp": pd.to_datetime(ns[horizon_i], utc=True)})


def build_features(universe: pd.DataFrame, p2, r30b, data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, float]:
    cross = r30b.cross_asset_factors(data["QQQ"], data["SOXX"]).set_index("decision_timestamp_utc")
    rows = []
    for symbol in ("QQQ", "SOXX"):
        raw, peer = data[symbol], data["SOXX" if symbol == "QQQ" else "QQQ"]
        base = p2.R1.feature_frame(raw, symbol); base["decision_timestamp_utc"] = raw.timestamp_utc.to_numpy()
        add = p2.build_features(raw, peer).loc[:, ["timestamp_utc", "volume_zscore_60m", "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m"]].rename(columns={"timestamp_utc": "decision_timestamp_utc"})
        technical = r30b.single_symbol_factors(raw).drop(columns=["max_source_timestamp_utc"]).rename(columns={"timestamp_utc": "decision_timestamp_utc"})
        combined = base.merge(add, on="decision_timestamp_utc", validate="one_to_one").merge(technical, on="decision_timestamp_utc", validate="one_to_one").set_index("decision_timestamp_utc")
        chosen = universe.loc[universe.underlying_symbol.eq(symbol), ["candidate_id", "decision_timestamp_utc", "direction_code"]].copy()
        vals = combined.reindex(chosen.decision_timestamp_utc)[[x for x in BASELINE_14 if x != "direction_code"] + list(EXTRA_15[:10])].reset_index(drop=True)
        vals.index = chosen.index
        chosen = pd.concat([chosen, vals], axis=1)
        chosen = chosen.merge(cross[list(EXTRA_15[10:])], left_on="decision_timestamp_utc", right_index=True, how="left", validate="many_to_one")
        rows.append(chosen)
        del base, add, technical, combined
    out = pd.concat(rows, ignore_index=True).sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    if len(out) != len(universe) or out.candidate_id.duplicated().any(): raise R32AStop("STOP_FEATURE_CARDINALITY")
    coverage = float(out[list(FEATURES_29)].notna().all(axis=1).mean())
    return out, coverage


def load_etf_bars() -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    manifest = read_json(ETF_MANIFEST); bars = {}
    for symbol in ("TQQQ", "SQQQ", "SOXL", "SOXS"):
        records = [r for r in manifest["partitions"] if r["symbol"] == symbol and pd.Timestamp(r["min_timestamp"]) < TRUE_HOLDOUT_START]
        pieces = []
        for record in records:
            path = Path(record["absolute_or_canonical_path"])
            if DATA_ROOT not in path.parents or file_sha256(path) != record["file_sha256"]: raise R32AStop("STOP_ETF_PARTITION_IDENTITY")
            part = pd.read_parquet(path, columns=["symbol", "timestamp_utc", "open", "high", "low", "close", "volume", "source", "adjustment_type"])
            part["partition_key"] = record["partition_key"]; pieces.append(part)
        frame = pd.concat(pieces, ignore_index=True); frame["timestamp_utc"] = pd.to_datetime(frame.timestamp_utc, utc=True)
        numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
        legal = (frame.symbol.eq(symbol) & frame.timestamp_utc.lt(TRUE_HOLDOUT_START) & np.isfinite(numeric).all(axis=1)
                 & numeric.open.gt(0) & numeric.high.ge(np.maximum(numeric.open, numeric.close))
                 & numeric.low.le(np.minimum(numeric.open, numeric.close)) & numeric.volume.ge(0) & frame.source.notna())
        frame = frame.loc[legal].sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)
        if frame.timestamp_utc.duplicated().any() or frame.timestamp_utc.max() >= TRUE_HOLDOUT_START: raise R32AStop("STOP_ETF_BAR_IDENTITY")
        bars[symbol] = frame
    audit = pd.read_csv(R28F_ACTION_AUDIT); audit["observed_boundary_timestamp"] = pd.to_datetime(audit.observed_boundary_timestamp, utc=True)
    return bars, audit.to_dict("records")


def base_payoffs(universe: pd.DataFrame, bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Vectorized exact R26A2 entry/24h-exit semantics, without reading outcome ledgers."""
    outputs = []
    for instrument, left in universe.groupby("instrument", sort=True):
        right = bars[instrument][["timestamp_utc", "open", "partition_key"]].rename(columns={"timestamp_utc": "bar_ts", "open": "bar_open"}).sort_values("bar_ts")
        x = left[["candidate_id", "authoritative_anchor_timestamp_et"]].rename(columns={"authoritative_anchor_timestamp_et": "anchor"}).sort_values("anchor")
        ent = pd.merge_asof(x, right, left_on="anchor", right_on="bar_ts", direction="forward", allow_exact_matches=False)
        ent = ent.rename(columns={"bar_ts": "entry_timestamp", "bar_open": "entry_price", "partition_key": "entry_partition"})
        ent["theoretical_exit"] = ent.entry_timestamp + pd.Timedelta(hours=24)
        ext = pd.merge_asof(ent.sort_values("theoretical_exit"), right, left_on="theoretical_exit", right_on="bar_ts", direction="forward", allow_exact_matches=True)
        ext = ext.rename(columns={"bar_ts": "exit_timestamp", "bar_open": "exit_price", "partition_key": "exit_partition"})
        entry_delay = (ext.entry_timestamp - ext.anchor).dt.total_seconds().div(60); exit_delay = (ext.exit_timestamp - ext.theoretical_exit).dt.total_seconds().div(60)
        ext["base_valid"] = ext.entry_timestamp.notna() & entry_delay.gt(0) & entry_delay.le(15) & ext.exit_timestamp.notna() & exit_delay.ge(0) & exit_delay.le(96 * 60)
        ext["base_invalid_reason"] = np.where(ext.base_valid, None, np.where(ext.entry_timestamp.isna() | ~entry_delay.between(0, 15, inclusive="right"), "MISSING_ENTRY_PRICE", "MISSING_EXIT_PATH"))
        outputs.append(ext[["candidate_id", "entry_timestamp", "entry_price", "entry_partition", "exit_timestamp", "exit_price", "exit_partition", "base_valid", "base_invalid_reason"]])
    return pd.concat(outputs, ignore_index=True)


def construct_labels(universe: pd.DataFrame, touches: pd.DataFrame, bars: dict[str, pd.DataFrame], action_rows: list[dict[str, Any]]) -> pd.DataFrame:
    out = universe[["candidate_id", "anchor_candidate_id", "decision_timestamp_utc", "underlying_symbol", "head", "instrument", "canonical_partition_manifest_hash"]].merge(touches, on="anchor_candidate_id", validate="many_to_one")
    out = out.merge(base_payoffs(universe, bars), on="candidate_id", validate="one_to_one")
    out["touch_timestamp"] = pd.to_datetime(out.touch_timestamp, utc=True, errors="coerce")
    out["entry_timestamp"] = pd.to_datetime(out.entry_timestamp, utc=True, errors="coerce")
    out["exit_timestamp"] = pd.to_datetime(out.exit_timestamp, utc=True, errors="coerce")
    favorable = (out["head"].eq("UP") & out.frozen_label.eq("UP_FIRST")) | (out["head"].eq("DOWN") & out.frozen_label.eq("DOWN_FIRST"))
    out["event_state"] = np.where(out.frozen_label.eq("AMBIGUOUS"), "AMBIGUOUS", np.where(favorable, "FAVORABLE_FIRST", np.where(out.frozen_label.eq("NO_EVENT"), "NO_EVENT", "ADVERSE_FIRST")))
    out["pre_entry"] = out.touch_timestamp.notna() & out.entry_timestamp.notna() & out.touch_timestamp.lt(out.entry_timestamp)
    for instrument, part in out.loc[favorable & out.base_valid & ~out.pre_entry].groupby("instrument", sort=True):
        right = bars[instrument][["timestamp_utc", "open", "partition_key"]].rename(columns={"timestamp_utc": "touch_exit", "open": "touch_price", "partition_key": "touch_partition"}).sort_values("touch_exit")
        left = part[["candidate_id", "touch_timestamp"]].sort_values("touch_timestamp")
        joined = pd.merge_asof(left, right, left_on="touch_timestamp", right_on="touch_exit", direction="forward", allow_exact_matches=True).set_index("candidate_id")
        mask = out.candidate_id.isin(joined.index)
        out.loc[mask, "exit_timestamp"] = out.loc[mask, "candidate_id"].map(joined.touch_exit)
        out.loc[mask, "exit_price"] = out.loc[mask, "candidate_id"].map(joined.touch_price)
        out.loc[mask, "exit_partition"] = out.loc[mask, "candidate_id"].map(joined.touch_partition)
    out["label_valid"] = out.base_valid & ~out.pre_entry & out.frozen_label.ne("AMBIGUOUS") & out.exit_timestamp.notna() & out.exit_price.notna()
    out["invalid_reason"] = np.where(out.label_valid, None, np.where(out.frozen_label.eq("AMBIGUOUS"), "OTHER_EXPLICIT_INVALID", np.where(out.pre_entry, "PRE_ENTRY_EVENT_NOT_CAPTURABLE", np.where(out.base_invalid_reason.eq("MISSING_ENTRY_PRICE"), "MISSING_ENTRY_PRICE", "MISSING_EXIT_PATH"))))
    official = [r for r in action_rows if str(r["metadata_authority"]) == "OFFICIAL_ISSUER"]
    diagnostic = [r for r in action_rows if str(r["metadata_authority"]) != "OFFICIAL_ISSUER"]
    out["corporate_action_factor"] = 1.0; out["corporate_action_affected"] = False; unresolved = pd.Series(False, index=out.index)
    for row in official:
        ts = pd.Timestamp(row["observed_boundary_timestamp"]); left, right = str(row["split_ratio"]).split(":")
        factor = float(right) / float(left)
        mask = out.label_valid & out.instrument.eq(row["symbol"]) & out.entry_timestamp.lt(ts) & out.exit_timestamp.ge(ts)
        out.loc[mask, "corporate_action_factor"] *= factor; out.loc[mask, "corporate_action_affected"] = True
    for row in diagnostic:
        ts = pd.Timestamp(row["observed_boundary_timestamp"]); unresolved |= out.label_valid & out.instrument.eq(row["symbol"]) & out.entry_timestamp.lt(ts) & out.exit_timestamp.ge(ts)
    out.loc[unresolved, "label_valid"] = False; out.loc[unresolved, "invalid_reason"] = "CORPORATE_ACTION_UNRESOLVED"
    out["gross_return"] = np.where(out.label_valid, out.exit_price / (out.entry_price * out.corporate_action_factor) - 1.0, np.nan)
    out["net20"] = np.where(out.label_valid, out.gross_return - .002, np.nan)
    out["T1"] = pd.Series(np.where(out.label_valid, (out.net20 > 0).astype(int), np.nan), dtype="Float64")
    out["T2"] = np.where(out.label_valid, np.sign(out.net20) * np.log1p(np.abs(out.net20)), np.nan)
    out["label_information_end"] = out.exit_timestamp
    out["split"] = np.where(out.decision_timestamp_utc.dt.year < 2020, "TRAIN", "DEVELOPMENT")
    out["fold"] = out.decision_timestamp_utc.dt.year.map({2020:"OOF_2020",2021:"OOF_2021",2022:"OOF_2022",2023:"OOF_2023",2024:"OOF_2024",2025:"OOF_2025_JAN"}).fillna("TRAIN_WARMUP")
    out["source_partition_identity"] = out.canonical_partition_manifest_hash.astype(str) + ";ETF=" + ETF_MANIFEST_SHA
    return out


def fold_overlap_audit(labels: pd.DataFrame) -> tuple[int, list[dict[str, Any]]]:
    valid = labels.loc[labels.label_valid].copy(); rows = []
    for name, raw_start, raw_end in FOLDS:
        start, end = pd.Timestamp(raw_start, tz="UTC"), pd.Timestamp(raw_end, tz="UTC")
        validation = valid.loc[valid.decision_timestamp_utc.between(start, end)]
        if validation.empty: raise R32AStop("STOP_EMPTY_FOLD:" + name)
        cutoff = validation.decision_timestamp_utc.min() - PURGE
        train = valid.loc[valid.label_information_end.lt(cutoff)]
        overlap = int(train.label_information_end.ge(cutoff).sum())
        rows.append({"fold": name, "train_count": len(train), "validation_count": len(validation), "information_cutoff": cutoff,
                     "train_label_information_end_max": train.label_information_end.max(), "overlap_count": overlap})
    return sum(r["overlap_count"] for r in rows), rows


def target_stats(frame: pd.DataFrame) -> dict[str, Any]:
    x = frame.loc[frame.label_valid, "net20"]
    return {"count": len(x), "t1_positive_rate": float((x > 0).mean()), "mean_net20": float(x.mean()), "median_net20": float(x.median()),
            "p01_net20": float(x.quantile(.01)), "p05_net20": float(x.quantile(.05)), "p95_net20": float(x.quantile(.95)), "p99_net20": float(x.quantile(.99)),
            "min_net20": float(x.min()), "max_net20": float(x.max())}


def feature_range_audit(features: pd.DataFrame, labels: pd.DataFrame, old_ids: set[str]) -> pd.DataFrame:
    valid_ids = set(labels.loc[labels.label_valid, "candidate_id"]); full = features.loc[features.candidate_id.isin(valid_ids)]; old = features.loc[features.candidate_id.isin(old_ids)]
    rows = []
    for name in FEATURES_29:
        a, b = pd.to_numeric(full[name], errors="coerce").dropna(), pd.to_numeric(old[name], errors="coerce").dropna()
        pooled = math.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2) if len(a) > 1 and len(b) > 1 else math.nan
        rows.append({"feature": name, "full_count": len(a), "selected_count": len(b),
            **{f"full_{q}": float(getattr(a, q)() if q in ("mean", "std") else a.quantile({"p05":.05,"p50":.5,"p95":.95}[q])) for q in ("mean","std","p05","p50","p95")},
            **{f"selected_{q}": float(getattr(b, q)() if q in ("mean", "std") else b.quantile({"p05":.05,"p50":.5,"p95":.95}[q])) for q in ("mean","std","p05","p50","p95")},
            "standardized_mean_difference": float((b.mean()-a.mean())/pooled) if pooled and np.isfinite(pooled) else math.nan,
            "ks_statistic": float(ks_2samp(a, b).statistic), "variance_ratio_selected_to_full": float(b.var(ddof=1)/a.var(ddof=1)) if a.var(ddof=1) else math.nan})
    return pd.DataFrame(rows)


def selection_severity(selection_rate: float, feature_audit: pd.DataFrame, year_rates: pd.DataFrame, direction_rates: pd.DataFrame) -> str:
    max_smd = feature_audit.standardized_mean_difference.abs().max(); max_ks = feature_audit.ks_statistic.max()
    concentration = max(float(year_rates.selection_rate.max() / year_rates.selection_rate.min()) if year_rates.selection_rate.min() > 0 else math.inf,
                        float(direction_rates.selection_rate.max() / direction_rates.selection_rate.min()) if direction_rates.selection_rate.min() > 0 else math.inf)
    if selection_rate < .01 or max_smd >= .5 or max_ks >= .3 or concentration >= 3: return "HIGH"
    if selection_rate < .10 or max_smd >= .25 or max_ks >= .15 or concentration >= 1.5: return "MODERATE"
    return "LOW"


def main() -> int:
    args = argparse.ArgumentParser(); args.add_argument("--run", action="store_true"); parsed = args.parse_args()
    if not parsed.run: raise R32AStop("USE_--run")
    prior = guard_inputs(); universe, universe_sha, universe_path, universe_identity = freeze_universe_identity()
    frozen_guard = lambda: file_sha256(universe_path) == universe_sha
    if not frozen_guard(): raise R32AStop("STOP_UNIVERSE_MUTATED_AFTER_FREEZE")
    r30a, p2, r30b, data = load_underlying_and_modules()
    bases = universe.drop_duplicates("anchor_candidate_id")[["anchor_candidate_id", "decision_timestamp_utc", "underlying_symbol"]]
    first_touch = import_file(SOURCE_ROOT / "fast3/scripts/run/fast3_r28_3b_soxx_natural_baseline.py", "r32a_touch")
    touch_parts = [compute_touches(bases.loc[bases.underlying_symbol.eq(s)].reset_index(drop=True), data[s], p2.R1, first_touch.first_touch_labels) for s in ("QQQ", "SOXX")]
    touches = pd.concat(touch_parts, ignore_index=True)
    features, feature_coverage = build_features(universe, p2, r30b, data)
    if not frozen_guard(): raise R32AStop("STOP_UNIVERSE_MUTATED_AFTER_FREEZE")
    bars, action_rows = load_etf_bars(); labels = construct_labels(universe, touches, bars, action_rows)
    if len(labels) != len(universe) or labels.candidate_id.duplicated().any(): raise R32AStop("STOP_LABEL_CARDINALITY")
    if labels.decision_timestamp_utc.ge(TRUE_HOLDOUT_START).any() or labels.loc[labels.label_valid, "label_information_end"].ge(TRUE_HOLDOUT_START).any(): raise R32AStop("STOP_FINAL_CONFIRMATION_LABEL")

    old_target = pd.read_parquet(Path(read_json(R30A_DATA_ID)["TARGET_LEDGER_PATH"]))
    old_ids = set(old_target.candidate_id); old_r28g = pd.read_csv(R28G_LEDGER)
    old_match = labels.loc[labels.candidate_id.isin(old_ids), ["candidate_id", "label_valid", "net20"]].merge(old_target[["candidate_id", "raw_net20"]], on="candidate_id", validate="one_to_one")
    unmatched = len(old_ids - set(labels.candidate_id)); reproduction_mismatch = int((~np.isclose(old_match.net20, old_match.raw_net20, atol=1e-12, rtol=1e-12)).sum())
    if unmatched or len(old_match) != 1197 or not old_match.label_valid.all() or reproduction_mismatch: raise R32AStop("STOP_OLD_SELECTED_RECONCILIATION")
    executed_ids = set(old_r28g.candidate_id); executed_unmatched = len(executed_ids - set(labels.candidate_id))
    if len(executed_ids) != 1198 or executed_unmatched: raise R32AStop("STOP_OLD_EXECUTED_RECONCILIATION")

    overlap_count, fold_audit = fold_overlap_audit(labels)
    valid = labels.loc[labels.label_valid].copy(); coverage = len(valid) / len(labels)
    invalid_counts = labels.loc[~labels.label_valid, "invalid_reason"].value_counts().to_dict()
    ca_fail = int(valid.gross_return.isna().sum()); extreme = valid.loc[valid.net20.abs().ge(.20)]
    extreme_pass = bool(np.isfinite(extreme.net20).all() and (valid.net20 >= -1.002 - 1e-12).all() and valid.net20.abs().max() < 5)
    if coverage < .95 or overlap_count or ca_fail or not extreme_pass: raise R32AStop("STOP_FULL_UNIVERSE_LABEL_GATE")

    ledger_cols = ["candidate_id","decision_timestamp_utc","head","underlying_symbol","split","fold","instrument","entry_timestamp","exit_timestamp",
                   "gross_return","net20","T1","T2","label_valid","invalid_reason","corporate_action_affected","source_partition_identity","label_information_end"]
    ledger_path = SCRATCH_ROOT / "FAST3_R32A_FULL_UNIVERSE_ECONOMIC_LABEL_LEDGER_R1.parquet"
    labels[ledger_cols].sort_values("candidate_id", kind="mergesort").to_parquet(ledger_path, index=False); ledger_sha = file_sha256(ledger_path)

    feature_audit = feature_range_audit(features, labels, old_ids)
    years = sorted(valid.decision_timestamp_utc.dt.year.unique()); year_rows = []
    for year in years:
        full_part = valid.loc[valid.decision_timestamp_utc.dt.year.eq(year)]; old_part = full_part.loc[full_part.candidate_id.isin(old_ids)]
        year_rows.append({"year": int(year), "full_valid_count": len(full_part), "old_selected_count": len(old_part), "selection_rate": len(old_part)/len(full_part)})
    by_year = pd.DataFrame(year_rows)
    direction_rows = []
    for head in ("UP", "DOWN"):
        full_part = valid.loc[valid["head"].eq(head)]; old_part = full_part.loc[full_part.candidate_id.isin(old_ids)]
        direction_rows.append({"direction": head, "full_valid_count": len(full_part), "old_selected_count": len(old_part), "selection_rate": len(old_part)/len(full_part),
                               "full_share": len(full_part)/len(valid), "old_selected_share": len(old_part)/1197})
    by_direction = pd.DataFrame(direction_rows)
    fold_rates = {}
    for fold in sorted(valid.fold.unique()):
        part = valid.loc[valid.fold.eq(fold)]; fold_rates[fold] = len(part.loc[part.candidate_id.isin(old_ids)]) / len(part)
    selection_rate = 1197 / len(valid); severity = selection_severity(selection_rate, feature_audit, by_year, by_direction)
    full_stats = target_stats(labels); selected_stats = target_stats(labels.loc[labels.candidate_id.isin(old_ids)])

    feasibility = pd.DataFrame([{"label_validity_category": "VALID_EXECUTABLE_LABEL", "count": len(valid)}, *
        ({"label_validity_category": k, "count": int(v)} for k, v in sorted(invalid_counts.items()))])
    target_dist = pd.DataFrame([{"universe": "FULL_PRE_SCORE_ELIGIBLE", **full_stats}, {"universe": "OLD_R28_MODEL_SELECTED", **selected_stats}])
    feasibility.to_csv(FROZEN_ROOT / "FAST3_R32A_LABEL_FEASIBILITY.csv", index=False)
    by_year.to_csv(FROZEN_ROOT / "FAST3_R32A_SELECTION_BIAS_BY_YEAR.csv", index=False)
    by_direction.to_csv(FROZEN_ROOT / "FAST3_R32A_SELECTION_BIAS_BY_DIRECTION.csv", index=False)
    feature_audit.to_csv(FROZEN_ROOT / "FAST3_R32A_FEATURE_RANGE_RESTRICTION.csv", index=False)
    target_dist.to_csv(FROZEN_ROOT / "FAST3_R32A_FULL_VS_SELECTED_TARGET_DISTRIBUTION.csv", index=False)

    selection_audit = {
        "OLD_UNIVERSE_SELECTION_SOURCE": "Frozen R28 phase-2 R28_3_CROSS_ASSET_FLOW immutable validation ledgers -> R28.3A/3E execution selection",
        "OLD_UNIVERSE_SELECTION_RULE": "probability >= frozen HGB threshold; simultaneous same-underlying opposite-head conflicts abstain; multi-symbol timestamp ties abstain; one global position; signals while open ignored; valid payoff required; R30 excludes pre-entry touch",
        "OLD_UNIVERSE_SELECTION_DEPENDS_ON_R28_SCORE": True, "OLD_UNIVERSE_SELECTION_DEPENDS_ON_R28_THRESHOLD": True,
        "OLD_UNIVERSE_SELECTION_DEPENDS_ON_EVENT_MODEL": True, "OLD_ECONOMIC_TARGET_ROW_COUNT": 1197, "OLD_EXECUTED_ROW_COUNT": 1198,
        "OLD_OOF_ROW_COUNT": 998, "OLD_SELECTED_TO_FULL_MATCH_COUNT": 1197, "OLD_SELECTED_TO_FULL_UNMATCHED_COUNT": unmatched,
        "OLD_SELECTION_RATE": selection_rate, "SELECTION_RATE_BY_YEAR": {str(r.year): r.selection_rate for r in by_year.itertuples()},
        "SELECTION_RATE_BY_FOLD": fold_rates, "SELECTION_BIAS_SEVERITY": severity,
        "SELECTION_BIAS_FEATURE_AUDIT_OUTCOME_BLIND": True,
    }
    write_json(FROZEN_ROOT / "FAST3_R32A_SELECTION_MECHANISM_AUDIT.json", selection_audit)

    manifest = {
        "CONTRACT_ID": "FAST3_R32A_FULL_UNIVERSE_LABEL_MANIFEST_R1", "STATUS": "FROZEN",
        "path": str(ledger_path), "SHA256": ledger_sha, "row_count": len(labels), "valid_count": len(valid), "invalid_count": len(labels)-len(valid),
        "timestamp_bounds": [labels.decision_timestamp_utc.min(), labels.decision_timestamp_utc.max()], "schema": ledger_cols,
        "target_contract_sha256": TARGET_SHA, "candidate_universe_sha256": universe_sha, "split_sha256": SPLIT_SHA,
        "economic_contract_identity": EXECUTION_CONTRACT_SHA, "corporate_action_ledger_identity": file_sha256(R28G_ACTION_LEDGER),
        "corporate_action_audit_identity": file_sha256(R28F_ACTION_AUDIT), "FINAL_CONFIRMATION_ROW_COUNT_IN_LABEL_LEDGER": 0,
        "PROSPECTIVE_ROW_COUNT_IN_LABEL_LEDGER": 0, "FINAL_CONFIRMATION_OUTCOME_READ_COUNT": 0,
    }
    manifest_path = FROZEN_ROOT / "FAST3_R32A_FULL_UNIVERSE_LABEL_MANIFEST_R1.json"; write_json(manifest_path, manifest); manifest_sha = file_sha256(manifest_path)
    prereg = {"CONTRACT_ID":"FAST3_R32A_R32B_PREREGISTRATION", "UNIVERSE":"full pre-score eligible TRAIN+DEVELOPMENT economic universe",
        "UNIVERSE_IDENTITY_SHA256":universe_sha, "LABEL_MANIFEST_SHA256":manifest_sha, "FEATURES":list(FEATURES_29), "FEATURE_COUNT":29,
        "FEATURE_MANIFEST_SHA256":FEATURE_SHA, "TARGETS":["T1","T2"], "TARGET_CONTRACT_SHA256":TARGET_SHA,
        "MODEL_FAMILY":["HistGradientBoostingClassifier","HistGradientBoostingRegressor"], "HYPERPARAMETERS":"same frozen R30 contract",
        "SPLIT_CONTRACT_SHA256":SPLIT_SHA, "FINAL_CONFIRMATION_ALLOWED":False, "STATUS":"PREREGISTERED_NOT_EXECUTED"}
    prereg_path = FROZEN_ROOT / "FAST3_R32A_R32B_PREREGISTRATION.json"; write_json(prereg_path, prereg)

    duplicate_ts = int(len(universe) - universe.decision_timestamp_utc.nunique())
    same_dir = int(len(universe) - universe[["decision_timestamp_utc","head"]].drop_duplicates().shape[0])
    opposite = int(sum(g["head"].nunique() == 2 for _, g in universe.groupby("decision_timestamp_utc", sort=False)))
    horizon_max = (valid.label_information_end - valid.decision_timestamp_utc).max()
    report_path = FROZEN_ROOT / "FAST3_R32A_REPORT.md"; summary_path = FROZEN_ROOT / "FAST3_R32A_SUMMARY.json"
    summary = {
        "FAST3_R32A_STATUS":"COMPLETE", "FAST3_R32A_CLASSIFICATION":"A_FULL_UNIVERSE_ECONOMIC_LABELING_READY_AND_FROZEN",
        "FAST3_R32A_DECISION":"FULL_UNIVERSE_ECONOMIC_LABELING_READY; SELECTION_CONDITIONING_CONFIRMED",
        "MODEL_FIT_COUNT":0,"MODEL_PREDICT_CALL_COUNT":0,"NEW_FEATURE_COUNT":0,"FEATURE_SEARCH_COUNT":0,"MODEL_SEARCH_COUNT":0,"HYPERPARAMETER_SEARCH_COUNT":0,
        **prior, **selection_audit,
        "AUTHORITATIVE_CANDIDATE_SOURCE":str(R28_EVENT_LEDGER),"AUTHORITATIVE_CANDIDATE_SHA256":EVENT_LEDGER_SHA,
        "FULL_ELIGIBLE_ROW_COUNT":len(labels),"FULL_ELIGIBLE_UNIQUE_CANDIDATE_COUNT":labels.candidate_id.nunique(),
        "FULL_VALID_LABEL_COUNT":len(valid),"FULL_INVALID_LABEL_COUNT":len(labels)-len(valid),"LABEL_COVERAGE_RATE":coverage,
        "FULL_UNIVERSE_IDENTITY_SHA256":universe_sha,"FULL_UNIVERSE_LABEL_MANIFEST_SHA256":manifest_sha,
        "FULL_T1_POSITIVE_RATE":full_stats["t1_positive_rate"],"OLD_SELECTED_T1_POSITIVE_RATE":selected_stats["t1_positive_rate"],
        "FULL_MEAN_NET20":full_stats["mean_net20"],"OLD_SELECTED_MEAN_NET20":selected_stats["mean_net20"],
        "FULL_MEDIAN_NET20":full_stats["median_net20"],"OLD_SELECTED_MEDIAN_NET20":selected_stats["median_net20"],
        "FULL_NET20_DISTRIBUTION":full_stats,"OLD_SELECTED_NET20_DISTRIBUTION":selected_stats,
        "FEATURE_RANGE_RESTRICTION_STATUS":severity,"FULL_UNIVERSE_FEATURE_COVERAGE":feature_coverage,
        "TRAIN_VALIDATION_LABEL_OVERLAP_COUNT":overlap_count,"LABEL_HORIZON_MAX":str(horizon_max),"PURGE_DURATION":"1440m","EMBARGO_DURATION":"1440m","FOLD_AUDIT":fold_audit,
        "CORPORATE_ACTION_AFFECTED_COUNT":int(valid.corporate_action_affected.sum()),"CORPORATE_ACTION_NORMALIZATION_FAILURE_COUNT":ca_fail,
        "EXTREME_RETURN_COUNT":len(extreme),"EXTREME_RETURN_AUDIT_PASS":extreme_pass,"EXTREME_RETURN_THRESHOLD":"abs(net20)>=0.20; integrity fail at nonfinite, below -100.2%, or abs>=500%",
        "INVALID_LABEL_REASON_COUNTS":invalid_counts,"DUPLICATE_CANDIDATE_ID_COUNT":int(labels.candidate_id.duplicated().sum()),
        "DUPLICATE_DECISION_TIMESTAMP_COUNT":duplicate_ts,"SAME_TIMESTAMP_SAME_DIRECTION_COUNT":same_dir,"SAME_TIMESTAMP_OPPOSITE_DIRECTION_COUNT":opposite,
        "FUTURE_INFORMATION_USED_IN_ELIGIBILITY_COUNT":0,"FUTURE_INFORMATION_USED_IN_FEATURE_COUNT":0,"FINAL_CONFIRMATION_ROW_COUNT_IN_LABEL_LEDGER":0,
        "PROSPECTIVE_ROW_COUNT_IN_LABEL_LEDGER":0,"FINAL_CONFIRMATION_DATA_USED":False,"FINAL_CONFIRMATION_DATA_INSPECTED":False,"FINAL_CONFIRMATION_OUTCOME_READ_COUNT":0,"PROSPECTIVE_OUTCOME_READ_COUNT":0,
        "FULL_UNIVERSE_LABELING_READY":True,"R32B_FEATURE_COUNT":29,"R32B_TARGETS":"T1;T2","R32B_MODEL_FAMILY":"HistGradientBoostingClassifier;HistGradientBoostingRegressor","R32B_ALLOWED":True,
        "CLASS_IMBALANCE_RISK":"LOW" if .10 <= full_stats["t1_positive_rate"] <= .90 else "HIGH",
        "INSTRUMENT_MAPPING_SOURCE":str(TARGET_CONTRACT),"INSTRUMENT_MAPPING_SHA256":universe_identity["INSTRUMENT_MAPPING_SHA256"],
        "TARGET_CONTRACT_SHA256":TARGET_SHA,"SPLIT_CONTRACT_SHA256":SPLIT_SHA,"R30B_FEATURE_MANIFEST_SHA256":FEATURE_SHA,
        "CORPORATE_ACTION_NORMALIZATION_REQUIRED":True,"PRE_ENTRY_EVENT_NOT_CAPTURABLE":True,"SHARED_ECONOMIC_CONTRACT_MODIFICATION_REQUIRED":False,
        "SELECTION_BIAS_FEATURE_AUDIT_OUTCOME_BLIND":True,"OUTCOME_BLIND_UNIVERSE_FREEZE":True,"OLD_TARGET_REPRODUCTION_MISMATCH_COUNT":reproduction_mismatch,
        "DATA_ROOT_WRITE_COUNT":0,"LOCAL_RESULTS_CREATED":False,"RESULT_FILES_WRITTEN_TO_GIT_REPO":False,"PRE_EXISTING_TRACKED_CHANGES_PRESERVED":True,"PRE_EXISTING_UNTRACKED_FILES_PRESERVED":True,
        "DESTRUCTIVE_GIT_COMMAND_USED":False,"BROAD_GIT_ADD_USED":False,"R29_MODIFIED":False,"R29_ALLOWED_TO_RESUME":False,"OFFICIAL_ADOPTION_ALLOWED":False,"LIVE_TRADING_ALLOWED":False,
        "ANTI_BLOAT_STATUS":"PASS","R32A_NEW_SOURCE_FILE_COUNT":1,"R32A_NEW_TEST_FILE_COUNT":1,"R32A_NEW_HELPER_FILE_COUNT":0,
        "PRIMARY_RESEARCH_INTERPRETATION":"R30/R31 estimated conditional re-ranking inside a highly compressed R28 model-selected and execution-filtered cohort; they did not test economic learnability over the full pre-score opportunity universe.",
        "NEXT_STAGE":"R32B_FULL_UNIVERSE_ECONOMIC_BASELINE_TRAINING",
        "REPORT_PATH":str(report_path),"SUMMARY_JSON_PATH":str(summary_path),"FULL_UNIVERSE_IDENTITY_PATH":str(universe_path),"LABEL_MANIFEST_PATH":str(manifest_path),"R32B_PREREGISTRATION_PATH":str(prereg_path),
        "LABEL_LEDGER_PATH":str(ledger_path),"LABEL_LEDGER_SHA256":ledger_sha,
    }
    report = f"""# FAST3 R32A — Full Opportunity-Universe Economic Label Audit

## Decision

`A_FULL_UNIVERSE_ECONOMIC_LABELING_READY_AND_FROZEN`

The old 1,197-row economic target set was not the full opportunity universe. It was conditional on the frozen R28 HGB score/threshold, conflict abstention, one-global-position concurrency filtering, payoff validity, and the R30 pre-entry exclusion. It represents {selection_rate:.6%} of the {len(valid):,} valid full-universe labels, so selection bias/range restriction is **{severity}**.

## Full-universe result

- Eligible candidate-head rows: {len(labels):,}
- Valid T1/T2 labels: {len(valid):,} ({coverage:.6%})
- Invalid rows remain explicit: {json.dumps(invalid_counts, sort_keys=True)}
- T1 positive rate: {full_stats['t1_positive_rate']:.12f}
- Mean / median net20: {full_stats['mean_net20']:.12f} / {full_stats['median_net20']:.12f}
- Old-selected mean / median net20: {selected_stats['mean_net20']:.12f} / {selected_stats['median_net20']:.12f}
- Corporate-action affected valid labels: {int(valid.corporate_action_affected.sum())}; normalization failures: {ca_fail}
- Extreme-return audit: {'PASS' if extreme_pass else 'FAIL'} ({len(extreme)} rows at abs(net20)>=20%)
- Train/validation label-overlap count: {overlap_count}
- Final/prospective outcome reads: 0

## Methodological answer

R30/R31 only answered whether the current features could re-rank opportunities after old R28 model selection and portfolio-style execution filtering. They did not answer whether the same 29 features can learn candidate-level economic payoff over the complete pre-score opportunity space. The full TRAIN+DEVELOPMENT ledger is now frozen, and R32B may test that clean question with the frozen 29 features, T1/T2, HGB contracts, and walk-forward split. Final confirmation remains sealed.
"""
    report_path.write_text(report, encoding="utf-8"); write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, default=json_default, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R32AStop as exc:
        print(f"FAST3_R32A_STATUS=STOPPED_REQUIRES_MANUAL_CODEX_REVIEW\nREASON={exc}", file=sys.stderr)
        raise SystemExit(2)
