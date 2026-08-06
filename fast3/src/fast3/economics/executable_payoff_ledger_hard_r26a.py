"""R26A authoritative executable-payoff construction.

This module deliberately has one execution contract.  It joins candidate
anchors to real canonical ETF bars; it never derives a leveraged payoff from
an underlying series.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

SYMBOL_MAP = {
    "QQQ": ("QQQ", 1), "TQQQ": ("QQQ", 1), "SQQQ": ("QQQ", -1),
    "SOXX": ("SOXX", 1), "SOXL": ("SOXX", 1), "SOXS": ("SOXX", -1),
}
ACTION_MAP = {("QQQ", 1): "TQQQ", ("QQQ", -1): "SQQQ",
              ("SOXX", 1): "SOXL", ("SOXX", -1): "SOXS"}
COSTS = (0.0005, 0.0010, 0.0020)
HORIZON_HOURS = 24

_BASE_PAYOFF_ROW_FIELDS = (
    "candidate_id", "candidate_instrument", "decision_timestamp_et", "authoritative_anchor_timestamp_et",
    "family", "polarity", "up_action_instrument", "down_action_instrument",
)
_ACTION_PAYOFF_FIELDS = (
    "entry_timestamp_et", "entry_price", "entry_delay_minutes", "exit_target_timestamp_et",
    "exit_timestamp_et", "exit_price", "exit_delay_minutes", "exit_reason", "action_gross_return",
    "action_net_return_5bps", "action_net_return_10bps", "action_net_return_20bps", "action_mfe",
    "action_mae", "entry_bar_hash", "exit_bar_hash", "path_hash", "payoff_valid", "invalid_reason",
)
PAYOFF_ROW_HASH_SCHEMA = _BASE_PAYOFF_ROW_FIELDS + tuple(
    f"{direction}_{field}" for direction in ("up", "down") for field in _ACTION_PAYOFF_FIELDS
) + ("frozen_horizon_hours", "source_candidate_hash", "canonical_partition_manifest_hash", "execution_contract_hash")
_VALID_PAYOFF_NUMERIC_FIELDS = (
    "entry_price", "exit_price", "action_gross_return", "action_net_return_5bps",
    "action_net_return_10bps", "action_net_return_20bps", "action_mfe", "action_mae",
)
_INVALID_UNAVAILABLE_PAYOFF_FIELDS = (
    "entry_timestamp_et", "entry_price", "entry_delay_minutes", "exit_timestamp_et", "exit_price",
    "exit_delay_minutes", "exit_reason", "action_gross_return", "action_net_return_5bps",
    "action_net_return_10bps", "action_net_return_20bps", "action_mfe", "action_mae",
    "entry_bar_hash", "exit_bar_hash", "path_hash",
)


class R26AContractError(RuntimeError):
    pass


def _is_missing(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    missing = pd.isna(value)
    return bool(missing) if isinstance(missing, (bool, np.bool_)) else False


def _canonical_json_value(value: Any) -> Any:
    """Convert supported scalar/container values to deterministic strict-JSON values."""
    if _is_missing(value):
        return None
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (pd.Timestamp, np.datetime64, datetime)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise R26AContractError("R26A_CANONICAL_TIMESTAMP_TIMEZONE_MISSING")
        return timestamp.isoformat(timespec="nanoseconds")
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        if not np.isfinite(value):
            raise R26AContractError("R26A_CANONICAL_JSON_NONFINITE_FLOAT")
        return value
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise R26AContractError("R26A_CANONICAL_JSON_KEY_TYPE_INVALID")
        return {key: _canonical_json_value(item) for key, item in value.items()}
    raise R26AContractError(f"R26A_CANONICAL_JSON_TYPE_UNSUPPORTED:{type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(_canonical_json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bar_hash(row: pd.Series) -> str:
    return stable_hash({key: (str(row[key]) if key in ("symbol", "timestamp_et") else float(row[key]))
                        for key in ("symbol", "timestamp_et", "open", "high", "low", "close", "volume")})


def _assert_payoff_row_contract(row: dict[str, Any]) -> None:
    candidate_id = row["candidate_id"]
    for direction in ("up", "down"):
        valid_value = row[f"{direction}_payoff_valid"]
        if _is_missing(valid_value):
            raise R26AContractError(f"R26A_PAYOFF_VALIDITY_MISSING:{candidate_id}:{direction}")
        valid = bool(valid_value)
        if valid:
            for field in _VALID_PAYOFF_NUMERIC_FIELDS:
                value = row[f"{direction}_{field}"]
                if _is_missing(value) or not np.isfinite(float(value)):
                    raise R26AContractError(f"R26A_VALID_PAYOFF_NONFINITE:{candidate_id}:{direction}_{field}")
        else:
            if _is_missing(row[f"{direction}_invalid_reason"]):
                raise R26AContractError(f"R26A_INVALID_PAYOFF_REASON_MISSING:{candidate_id}:{direction}")
            for field in _INVALID_UNAVAILABLE_PAYOFF_FIELDS:
                if not _is_missing(row[f"{direction}_{field}"]):
                    raise R26AContractError(f"R26A_INVALID_PAYOFF_FIELD_NOT_NULL:{candidate_id}:{direction}_{field}")


def payoff_row_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Return the fixed-schema, contract-checked input to one payoff row hash."""
    if tuple(row) != PAYOFF_ROW_HASH_SCHEMA:
        raise R26AContractError("R26A_PAYOFF_ROW_HASH_SCHEMA_INVALID")
    _assert_payoff_row_contract(row)
    return {field: row[field] for field in PAYOFF_ROW_HASH_SCHEMA}


def payoff_row_hashes(frame: pd.DataFrame) -> list[str]:
    """Hash every retained candidate over the complete fixed payoff-row schema."""
    if tuple(frame.columns) != PAYOFF_ROW_HASH_SCHEMA:
        raise R26AContractError("R26A_PAYOFF_ROW_HASH_SCHEMA_INVALID")
    return [stable_hash(payoff_row_payload(row)) for row in frame.to_dict("records")]


def assert_candidate_map(candidates: pd.DataFrame) -> pd.DataFrame:
    instrument = candidates["candidate_instrument"].astype(str)
    unknown = sorted(set(instrument).difference(SYMBOL_MAP))
    if unknown:
        raise R26AContractError("STOP_R26A_INSTRUMENT_MAPPING_UNRESOLVED")
    out = candidates.copy()
    out["family"] = instrument.map(lambda x: SYMBOL_MAP[x][0])
    out["polarity"] = instrument.map(lambda x: SYMBOL_MAP[x][1]).astype(int)
    out["up_action_instrument"] = [ACTION_MAP[(f, p)] for f, p in zip(out.family, out.polarity)]
    out["down_action_instrument"] = [ACTION_MAP[(f, -p)] for f, p in zip(out.family, out.polarity)]
    return out


def legal_bars(canonical_root: Path, symbol: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    root = Path(canonical_root) / f"symbol={symbol}"
    if not root.is_dir():
        raise R26AContractError(f"CANONICAL_SYMBOL_MISSING:{symbol}")
    files = sorted(root.rglob("*.parquet"))
    if not files:
        raise R26AContractError(f"CANONICAL_SYMBOL_EMPTY:{symbol}")
    table = ds.dataset(root, format="parquet").to_table(columns=["symbol", "timestamp_et", "open", "high", "low", "close", "volume", "source"])
    bars = table.to_pandas()
    bars["timestamp_et"] = pd.to_datetime(bars.timestamp_et, utc=True)
    numeric = bars[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    legal = (bars.symbol.astype(str).eq(symbol) & bars.timestamp_et.notna()
             & np.isfinite(numeric).all(axis=1) & numeric.open.gt(0) & numeric.high.gt(0)
             & numeric.low.gt(0) & numeric.close.gt(0) & numeric.volume.ge(0)
             & numeric.high.ge(np.maximum(numeric.open, numeric.close))
             & numeric.low.le(np.minimum(numeric.open, numeric.close))
             & bars.source.notna())
    bars = bars.loc[legal].copy().sort_values("timestamp_et", kind="mergesort")
    if bars.timestamp_et.duplicated().any():
        raise R26AContractError(f"CANONICAL_DUPLICATE_TIMESTAMP:{symbol}")
    bars["bar_hash"] = [bar_hash(row) for _, row in bars.iterrows()]
    manifest = {"symbol": symbol, "file_count": len(files), "files": [
        {"relative_path": str(p.relative_to(canonical_root)).replace("\\", "/"), "sha256": file_hash(p), "bytes": p.stat().st_size}
        for p in files], "legal_bar_count": int(len(bars)), "rejected_bar_count": int((~legal).sum())}
    return bars.reset_index(drop=True), manifest


def _range_extreme(values: np.ndarray, starts: np.ndarray, ends: np.ndarray, maximum: bool) -> np.ndarray:
    """Static sparse-table range query: O(n log n) build, O(q log n), no row scans."""
    n = len(values); q = len(starts)
    out = np.full(q, np.nan)
    valid = (starts >= 0) & (ends >= starts) & (ends < n)
    if not valid.any(): return out
    levels = [values]
    while len(levels[-1]) > 1:
        prev = levels[-1]; span = 1 << (len(levels) - 1)
        levels.append(np.maximum(prev[:-span], prev[span:]) if maximum else np.minimum(prev[:-span], prev[span:]))
    s, e = starts[valid].copy(), ends[valid].copy(); result = np.full(len(s), -np.inf if maximum else np.inf)
    length = e - s + 1; bit = 0
    while np.any(length):
        use = (length & 1).astype(bool)
        if use.any():
            chunk = levels[bit][s[use]]
            result[use] = np.maximum(result[use], chunk) if maximum else np.minimum(result[use], chunk)
            s[use] += 1 << bit
        length >>= 1; bit += 1
    out[valid] = result
    return out


def _assert_path_extrema_alignment(frame: pd.DataFrame, prefix: str, expected_candidate_ids: pd.Series) -> None:
    """Fail closed if an action join has lost positional candidate alignment."""
    required = (f"{prefix}_action_mfe", f"{prefix}_action_mae", f"{prefix}_payoff_valid")
    if (not frame.index.equals(pd.RangeIndex(len(frame))) or len(frame) != len(expected_candidate_ids)
            or not frame.candidate_id.astype(str).equals(expected_candidate_ids.astype(str))
            or any(column not in frame for column in required)):
        raise R26AContractError("R26A_PATH_EXTREMA_CANDIDATE_ALIGNMENT_INVALID")
    valid = frame[f"{prefix}_payoff_valid"].to_numpy(bool)
    extrema = frame[[f"{prefix}_action_mfe", f"{prefix}_action_mae"]].to_numpy(float)
    # Invalid paths deliberately remain null, but no valid candidate may lose its
    # deterministic entry-to-exit (inclusive) extrema interval.
    if not bool(np.isfinite(extrema[valid]).all()):
        raise R26AContractError("R26A_PATH_EXTREMA_VALID_INTERVAL_MISSING")


def _join_action(rows: pd.DataFrame, bars: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if rows.candidate_id.isna().any() or not rows.candidate_id.is_unique:
        raise R26AContractError("R26A_CANDIDATE_ID_INVALID")
    # Action partitions originate from boolean masks and therefore inherit a
    # sparse parent index.  Canonicalize before deriving *any* aligned Series:
    # merge_asof later resets its result, so retaining that index would make
    # pandas form an index union while calculating delays/validity.
    x = rows.copy().sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    anchor = pd.Series(pd.to_datetime(x.authoritative_anchor_timestamp_et, utc=True).to_numpy(), index=x.index)
    x["_anchor"] = anchor; x["_target"] = anchor + pd.Timedelta(hours=HORIZON_HOURS)
    right = bars[["timestamp_et", "open", "bar_hash"]].rename(columns={"timestamp_et": "_bar_ts", "open": "_price", "bar_hash": "_bar_hash"})
    ent = pd.merge_asof(x.sort_values("_anchor"), right.sort_values("_bar_ts"), left_on="_anchor", right_on="_bar_ts", direction="forward", allow_exact_matches=False)
    ex = pd.merge_asof(x.sort_values("_target"), right.sort_values("_bar_ts"), left_on="_target", right_on="_bar_ts", direction="forward", allow_exact_matches=True)
    ent = ent.sort_values("candidate_id", kind="mergesort").reset_index(drop=True); ex = ex.sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    if not (ent.candidate_id.equals(x.candidate_id) and ex.candidate_id.equals(x.candidate_id)):
        raise R26AContractError("R26A_ASOF_CANDIDATE_ALIGNMENT_INVALID")
    entry_ts, exit_ts = ent._bar_ts, ex._bar_ts
    entry_delay = (entry_ts - anchor).dt.total_seconds() / 60; exit_delay = (exit_ts - x._target).dt.total_seconds() / 60
    valid = entry_ts.notna() & exit_ts.notna() & entry_delay.gt(0) & entry_delay.le(15) & exit_delay.ge(0) & exit_delay.le(15)
    gross = ex._price / ent._price - 1
    x[f"{prefix}_entry_timestamp_et"] = entry_ts.where(valid); x[f"{prefix}_entry_price"] = ent._price.where(valid)
    x[f"{prefix}_entry_delay_minutes"] = entry_delay.where(valid); x[f"{prefix}_exit_target_timestamp_et"] = x._target
    x[f"{prefix}_exit_timestamp_et"] = exit_ts.where(valid); x[f"{prefix}_exit_price"] = ex._price.where(valid)
    x[f"{prefix}_exit_delay_minutes"] = exit_delay.where(valid); x[f"{prefix}_exit_reason"] = np.where(valid, "FIXED_FROZEN_HORIZON", None)
    x[f"{prefix}_action_gross_return"] = gross.where(valid)
    for cost in COSTS: x[f"{prefix}_action_net_return_{int(cost*10000)}bps"] = (gross - cost).where(valid)
    starts = bars.timestamp_et.searchsorted(entry_ts.fillna(pd.Timestamp("1900-01-01", tz="UTC")).to_numpy(), side="left")
    ends = bars.timestamp_et.searchsorted(exit_ts.fillna(pd.Timestamp("1900-01-01", tz="UTC")).to_numpy(), side="right") - 1
    max_high = _range_extreme(bars.high.to_numpy(float), starts, ends, True); min_low = _range_extreme(bars.low.to_numpy(float), starts, ends, False)
    x[f"{prefix}_action_mfe"] = (max_high / ent._price.to_numpy(float) - 1); x[f"{prefix}_action_mae"] = (min_low / ent._price.to_numpy(float) - 1)
    x.loc[~valid, [f"{prefix}_action_mfe", f"{prefix}_action_mae"]] = np.nan
    x[f"{prefix}_entry_bar_hash"] = ent._bar_hash.where(valid); x[f"{prefix}_exit_bar_hash"] = ex._bar_hash.where(valid)
    x[f"{prefix}_path_hash"] = [stable_hash({"entry": a, "exit": b, "instrument": i}) if ok else None for a,b,i,ok in zip(x[f"{prefix}_entry_bar_hash"], x[f"{prefix}_exit_bar_hash"], x[f"{prefix}_action_instrument"], valid)]
    x[f"{prefix}_payoff_valid"] = valid
    x[f"{prefix}_invalid_reason"] = np.where(valid, None, np.where(entry_ts.isna(), "ENTRY_BAR_UNAVAILABLE", np.where(exit_ts.isna(), "EXIT_BAR_UNAVAILABLE", "EXECUTION_DELAY_OUT_OF_BOUNDS")))
    _assert_path_extrema_alignment(x, prefix, x.candidate_id)
    return x.drop(columns=["_anchor", "_target"])


def construct_payoffs(candidates: pd.DataFrame, canonical_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    x = assert_candidate_map(candidates)
    if x.candidate_id.isna().any() or not x.candidate_id.is_unique:
        raise R26AContractError("R26A_CANDIDATE_ID_INVALID")
    x = x.sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    pieces: dict[str, list[pd.DataFrame]] = {"up": [], "down": []}; manifests = {}
    # The only loop is four instrument partitions; each partition is a vectorized as-of join.
    for instrument in sorted(set(x.up_action_instrument).union(x.down_action_instrument)):
        bars, manifest = legal_bars(canonical_root, instrument); manifests[instrument] = manifest
        for direction in ("up", "down"):
            mask = x[f"{direction}_action_instrument"].eq(instrument)
            if mask.any():
                joined = _join_action(x.loc[mask], bars, direction)
                # Keep only fields produced by this join.  `joined` also carries
                # the opposite static action-instrument column from `x`; merging
                # that column as though it were a payoff field would create
                # _x/_y collisions across canonical action partitions.
                keep = ["candidate_id"] + [c for c in joined if c.startswith(direction + "_") and c not in x.columns]
                pieces[direction].append(joined.loc[:, keep])
    out = x.copy()
    for direction in ("up", "down"):
        part = pd.concat(pieces[direction], ignore_index=True).sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
        if (len(part) != len(x) or part.candidate_id.duplicated().any()
                or not part.candidate_id.equals(x.candidate_id)):
            raise R26AContractError("R26A_ACTION_PARTITION_CANDIDATE_COVERAGE_INVALID")
        out = out.merge(part, on="candidate_id", how="left", validate="one_to_one")
    for direction in ("up", "down"):
        _assert_path_extrema_alignment(out, direction, x.candidate_id)
    out["frozen_horizon_hours"] = HORIZON_HOURS
    out["source_candidate_hash"] = [stable_hash({"candidate_id": cid, "anchor": str(anchor), "instrument": inst}) for cid,anchor,inst in zip(out.candidate_id, out.authoritative_anchor_timestamp_et, out.candidate_instrument)]
    partition_hash = stable_hash(manifests); out["canonical_partition_manifest_hash"] = partition_hash
    contract = {"anchor_field":"entry_timestamp_et", "horizon_hours":HORIZON_HOURS, "entry":"first legal open strictly after anchor <=15m", "exit":"first legal open at/after anchor+24h <=15m", "costs":list(COSTS)}
    out["execution_contract_hash"] = stable_hash(contract)
    out["payoff_row_hash"] = payoff_row_hashes(out)
    return out, {"partition_manifest": manifests, "partition_manifest_hash": partition_hash, "execution_contract": contract}


def payoff_audit(frame: pd.DataFrame, expected_ids: pd.Series) -> dict[str, Any]:
    duplicate = int(frame.candidate_id.duplicated().sum()); missing = int((~expected_ids.isin(frame.candidate_id)).sum()); unexpected = int((~frame.candidate_id.isin(expected_ids)).sum())
    both = frame.up_payoff_valid & frame.down_payoff_valid
    price_ok = True; arithmetic_ok = True
    for p in ("up", "down"):
        valid = frame[f"{p}_payoff_valid"]
        price_ok &= bool(np.isfinite(frame.loc[valid, [f"{p}_entry_price",f"{p}_exit_price"]].to_numpy(float)).all() and (frame.loc[valid, f"{p}_entry_price"]>0).all() and (frame.loc[valid, f"{p}_exit_price"]>0).all())
        gross = frame.loc[valid, f"{p}_exit_price"] / frame.loc[valid, f"{p}_entry_price"] - 1
        for cost in COSTS: arithmetic_ok &= bool(np.allclose(gross-cost, frame.loc[valid, f"{p}_action_net_return_{int(cost*10000)}bps"], rtol=0, atol=1e-14))
    return {"candidate_count":int(len(frame)), "unique_candidate_count":int(frame.candidate_id.nunique()), "duplicate_candidate_count":duplicate, "missing_candidate_count":missing, "unexpected_candidate_count":unexpected, "both_direction_valid_rate":float(both.mean()), "valid_prices_pass":price_ok, "cost_reproduction_pass":arithmetic_ok}
