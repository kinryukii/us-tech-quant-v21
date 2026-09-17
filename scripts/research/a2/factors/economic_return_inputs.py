"""Pinned raw OHLCV/action input adapter; computes no returns or strategies.

The old affine surface remains immutable with no fallback. This separate reader
requires its own frozen pre-2026 contract before any real table materialization.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

WORK = Path("C:/Users/Lenovo/Documents/CODING开发/strategy-lab-20260913")
BINDINGS = WORK / "audits/raw_return_source_bindings.json"
TAIL_ADAPTER = Path("D:/us-tech-quant/scripts/research/a2/factors/tail_research_inputs.py")
TAIL_ADAPTER_SHA256 = "c7f668a4582169f23247b27c8c2bf7b59472b0a9456ca685be129df8d2072e08"
START = pd.Timestamp("2020-01-01")
END = pd.Timestamp("2026-01-01")
OHLC = ("open", "high", "low", "close")
RAW_COLUMNS = ("ticker", "trade_date", "code", *OHLC, "volume", "autype", "source")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_hashes(pins: dict[str, str]) -> None:
    for name, expected in pins.items():
        if sha(Path(name)) != expected:
            raise RuntimeError(f"RAW_INPUT_HASH_MISMATCH:{name}")


def read_contract(contract_path: Path, bindings_path: Path) -> tuple[dict, dict]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if (contract.get("status") != "FROZEN_PRE2026_RAW_READ"
            or contract.get("cutoff_exclusive") != "2026-01-01"
            or contract.get("start_inclusive") != "2020-01-01"
            or contract.get("oldtarget_retained_as_reference_only") is not True):
        raise RuntimeError("NEW_RAW_READ_CONTRACT_NOT_FROZEN_OR_WRONG_DATES")
    if contract.get("reader_source_sha256") != sha(Path(__file__)):
        raise RuntimeError("RAW_READER_SOURCE_NOT_FROZEN")
    if contract.get("bindings_sha256") != sha(bindings_path):
        raise RuntimeError("RAW_BINDINGS_NOT_FROZEN")
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    if (bindings.get("status") != "PASS_STRUCTURAL_BINDINGS_NOT_RETURN_CERTIFICATION"
            or bindings.get("equity_count") != 644 or len(bindings.get("equities", [])) != 644
            or bindings.get("failures")):
        raise RuntimeError("RAW_BINDINGS_INCOMPLETE")
    return contract, bindings


def load_tail_definitions():
    check_hashes({str(TAIL_ADAPTER): TAIL_ADAPTER_SHA256})
    spec = importlib.util.spec_from_file_location("economic_input_existing_tail", TAIL_ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("EXISTING_INPUT_ADAPTER_IMPORT_FAILURE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize_raw(frame: pd.DataFrame, *, ticker: str, code: str) -> pd.DataFrame:
    required = {"trade_date", "code", *OHLC, "volume"}
    if not required.issubset(frame.columns) or frame.empty:
        raise RuntimeError(f"RAW_SCHEMA_OR_EMPTY:{ticker}")
    out = frame[["trade_date", "code", *OHLC, "volume"]].copy()
    if out.code.isna().any() or not out.code.astype(str).eq(code).all():
        raise RuntimeError(f"RAW_TICKER_IDENTITY_FAILURE:{ticker}")
    out["trade_date"] = pd.to_datetime(out.trade_date, errors="raise")
    if (out.trade_date.isna().any() or out.trade_date.dt.tz is not None
            or not out.trade_date.eq(out.trade_date.dt.normalize()).all()
            or out.trade_date.lt(START).any() or out.trade_date.ge(END).any()):
        raise RuntimeError(f"RAW_DATE_BOUNDARY_FAILURE:{ticker}")
    if out.trade_date.duplicated().any():
        raise RuntimeError(f"RAW_DUPLICATE_SESSION:{ticker}")
    for column in (*OHLC, "volume"):
        out[column] = pd.to_numeric(out[column], errors="raise").astype(float)
    if (not np.isfinite(out[[*OHLC, "volume"]]).all().all()
            or out[list(OHLC)].le(0).any().any() or out.volume.lt(0).any()):
        raise RuntimeError(f"INVALID_RAW_OHLCV:{ticker}")
    if ((out.high < out[list(OHLC)].max(axis=1)).any()
            or (out.low > out[list(OHLC)].min(axis=1)).any()):
        raise RuntimeError(f"INVALID_RAW_HIGH_LOW_ORDER:{ticker}")
    out["ticker"], out["autype"], out["source"] = ticker, "RAW_UNADJUSTED", "MOOMOO_OPEND_RAW"
    return out[list(RAW_COLUMNS)].sort_values("trade_date", kind="stable").reset_index(drop=True)


def read_stock(binding: dict, r5) -> pd.DataFrame:
    # Reuse the audited Arrow predicate and duplicate-conflict implementation.
    frame = r5._raw_pre2026(binding["moomoo_transport_code"], [Path(binding["raw_source_path"])])
    # Known stock sources have footer minima >=2020. A changed source cannot
    # enter because its manifest byte hash is checked before/after the read.
    return normalize_raw(frame, ticker=binding["ticker"], code=binding["moomoo_transport_code"])


def read_qqq(binding: dict, *, dataset_factory=ds.dataset) -> pd.DataFrame:
    if binding["ticker"] != "QQQ":
        raise RuntimeError("BENCHMARK_BINDING_NOT_QQQ")
    predicate = (ds.field("date") >= "2020-01-01") & (ds.field("date") < "2026-01-01")
    table = dataset_factory(Path(binding["raw_source_path"]), format="parquet").to_table(
        columns=["ticker", "moomoo_symbol", "date", *OHLC, "volume"], filter=predicate)
    frame = table.to_pandas()
    if not frame.ticker.astype(str).eq("QQQ").all():
        raise RuntimeError("QQQ_SOURCE_TICKER_MISMATCH")
    frame = frame.rename(columns={"date": "trade_date", "moomoo_symbol": "code"})
    return normalize_raw(frame, ticker="QQQ", code=binding["moomoo_transport_code"])


def read_events(path: Path, codes: set[str], *, dataset_factory=ds.dataset) -> pd.DataFrame:
    predicate = ((ds.field("ex_div_date") >= "2020-01-01")
                 & (ds.field("ex_div_date") < "2026-01-01") & ds.field("code").isin(sorted(codes)))
    # Preserve ALL existing action fields. No factorA/B→cash/share inference.
    frame = dataset_factory(path, format="parquet").to_table(filter=predicate).to_pandas()
    required = {"code", "ex_div_date", "per_cash_div", "special_dividend", "split_ratio",
                "split_base", "split_ert", "join_base", "join_ert", "spin_off_ratio"}
    if not required.issubset(frame.columns):
        raise RuntimeError("EXPLICIT_ACTION_FIELDS_MISSING")
    frame["ex_div_date"] = pd.to_datetime(frame.ex_div_date, errors="raise")
    if (frame.ex_div_date.isna().any() or frame.ex_div_date.lt(START).any()
            or frame.ex_div_date.ge(END).any() or frame.code.isna().any()
            or not set(frame.code.astype(str)).issubset(codes)):
        raise RuntimeError("EVENT_DATE_OR_CODE_BOUNDARY_FAILURE")
    return frame.sort_values(["code", "ex_div_date"], kind="stable").reset_index(drop=True)


def validate_calendar(raw: pd.DataFrame, calendar: pd.DatetimeIndex, wanted: set[str]) -> None:
    if set(raw.ticker) != wanted | {"QQQ"}:
        raise RuntimeError("RAW_SECURITY_COVERAGE_FAILURE")
    qqq_dates = pd.DatetimeIndex(raw.loc[raw.ticker.eq("QQQ"), "trade_date"])
    if not qqq_dates.equals(calendar):
        raise RuntimeError("RAW_QQQ_CALENDAR_MISMATCH")
    if not raw.trade_date.isin(calendar).all():
        raise RuntimeError("RAW_STOCK_SESSION_OUTSIDE_MARKET_CALENDAR")
    if raw.duplicated(["ticker", "trade_date"]).any():
        raise RuntimeError("RAW_DUPLICATE_IDENTITY_SESSION")


def load_economic_return_inputs(*, contract_path: Path, bindings_path: Path = BINDINGS):
    """Return raw prices, original action fields, old panel, calendar, lineage.

    Requires a separate frozen contract; no output is written. ``old_panel``
    includes legacy observable controls and ``legacy_affine_target``, which is
    reference metadata rather than a newly certified return target. There is
    deliberately no ``target`` column for a generic model caller to consume.
    """
    contract_path, bindings_path = Path(contract_path), Path(bindings_path)
    contract, bindings = read_contract(contract_path, bindings_path)
    pins = {str(contract_path): sha(contract_path), str(bindings_path): sha(bindings_path),
            str(Path(__file__).resolve()): contract["reader_source_sha256"], str(TAIL_ADAPTER): TAIL_ADAPTER_SHA256}
    for key in ("manifest", "source_audit", "universe", "checkpoint", "rehab"):
        pins[bindings[key]["path"]] = bindings[key]["sha256"]
    for binding in [*bindings["equities"], bindings["QQQ"]]:
        pins[binding["raw_source_path"]] = binding["sha256"]
    check_hashes(pins)
    inputs = load_tail_definitions()
    pins.update({str(path): digest for path, digest in inputs.PINNED.items()})
    check_hashes(pins)
    r5, _, _ = inputs.load_sources()  # source definitions; no frozen-surface read
    # Date footers and schemas precede raw bodies. Mixed source dates are legal
    # only under the new contract's explicit pre-conversion predicate boundary.
    for binding in bindings["equities"]:
        audit = inputs.footer_dates(Path(binding["raw_source_path"]), ("time_key",), physical_pre2026=False)
        if pd.Timestamp(audit["columns"]["time_key"]["min"]) < START:
            raise RuntimeError("UNEXPECTED_PRE2020_STOCK_SOURCE_HISTORY")
    inputs.footer_dates(Path(bindings["QQQ"]["raw_source_path"]), ("date",), physical_pre2026=False)
    inputs.footer_dates(Path(bindings["rehab"]["path"]), ("ex_div_date",), physical_pre2026=False)
    checkpoint = inputs.load_full_checkpoint()
    inputs.footer_dates(inputs.TRAINING_MATRIX, ("signal_date", "target_end_date"), physical_pre2026=True)
    original_matrix = ds.dataset(inputs.TRAINING_MATRIX, format="parquet").to_table(
        filter=(ds.field("signal_date") < END.to_pydatetime()) & (ds.field("target_end_date") < END.to_pydatetime())).to_pandas()
    old_panel, old_panel_audit = inputs._join_authoritative_panel(checkpoint, original_matrix, r5)
    old_panel = old_panel.rename(columns={"target": "legacy_affine_target"})
    wanted = set(checkpoint.ticker.astype(str))
    if wanted != {binding["ticker"] for binding in bindings["equities"]}:
        raise RuntimeError("RAW_BINDINGS_CHECKPOINT_NAMES_CHANGED")
    records = [read_stock(binding, r5) for binding in bindings["equities"]]
    records.append(read_qqq(bindings["QQQ"]))
    raw = pd.concat(records, ignore_index=True).sort_values(["trade_date", "ticker"], kind="stable").reset_index(drop=True)
    codes = {binding["moomoo_transport_code"] for binding in [*bindings["equities"], bindings["QQQ"]]}
    events = read_events(Path(bindings["rehab"]["path"]), codes)
    calendar_frame = ds.dataset(inputs.CALENDAR_PATH, format="parquet").to_table(columns=["trade_date"],
        filter=(ds.field("trade_date") >= "2020-01-01") & (ds.field("trade_date") < "2026-01-01")).to_pandas()
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar_frame.trade_date)).sort_values()
    validate_calendar(raw, calendar, wanted)
    check_hashes(pins)
    lineage = {"contract_path": str(contract_path), "contract": contract,
               "source_and_input_hashes": pins, "source_unchanged_after_read": True,
               "read_boundary": "NEW_TASK_RAW_CONTRACT_ARROW_PREDICATE_BEFORE_PANDAS",
               "frozen_affine_surface_used": False, "frozen_surface_fallback": False,
               "raw_prices": {"rows": len(raw), "tickers": raw.ticker.nunique(), "min_date": str(raw.trade_date.min()), "max_date": str(raw.trade_date.max())},
               "events": {"rows": len(events), "codes": events.code.nunique(), "columns": list(events.columns),
                          "duplicate_code_event_dates": int(events.duplicated(["code", "ex_div_date"], keep=False).sum()),
                          "semantics": "ORIGINAL_VENDOR_FIELDS_NO_ENTITLEMENT_INFERENCE"},
               "old_panel": old_panel_audit, "old_target_status": "LEGACY_AFFINE_INDEX_LABEL_REFERENCE_NOT_NEW_ECONOMIC_TARGET",
               "old_base_features_status": "EXISTING_OBSERVABLE_CONTROLS_NOT_CERTIFIED_HISTORICAL_DOLLAR_VOLUME",
               "calendar_sessions": len(calendar), "prices_or_events_forward_filled": False,
               "post2025_row_values_materialized": 0, "returns_computed": 0, "new_targets_computed": 0,
               "factors_computed": 0, "fits": 0, "performance_evaluations": 0,
               "limitations": ["Raw source access does not certify corporate-action entitlement semantics",
                              "Missing event payment/announcement/observation timestamps remain unresolved",
                              "All historical evaluation remains exposed adaptive research"]}
    return raw, events, old_panel, calendar, lineage
