"""Read-only, pinned adapter over authoritative Raw-A2 panel and price loaders.

No fitting or economic evaluation occurs here. The equity loader verifies the
immutable pre-2026 surface. R5's benchmark loader pushes the date predicate into
Arrow before pandas; this campaign explicitly permits that read boundary.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pyarrow.dataset as pads
import pyarrow.parquet as pq

END = pd.Timestamp("2026-01-01")
START = pd.Timestamp("2020-01-01")
R5_ROOT = Path("D:/us-tech-quant-worktrees/harness-task-20260827-041928-8076")
SURFACE_ROOT = Path("D:/us-tech-quant-worktrees/a2-raw-a2-true-return-attribution-r1-20260827-013537")
R5_SOURCE = R5_ROOT / "scripts/v22/a2_free_factor_discovery.py"
R4_SOURCE = R5_ROOT / "scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py"
SURFACE_SOURCE = SURFACE_ROOT / "scripts/v22/a2_pre2026_raw_moomoo_rehab_builder_r2.py"
SURFACE_MANIFEST = Path("D:/us-tech-quant-results/A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2/surface_manifest.json")
TRAINING_MATRIX = Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/training_matrix.parquet")
CALENDAR_PATH = Path("D:/us-tech-quant-data/reference/trading_calendar/XNYS/versions/xnys_sessions_f61c8f8d47cd94ae4b75.parquet")
LEGACY_RESEARCH_DATASET = {"path": "D:/us-tech-quant-cache/a2_model_family_r1a_data_complete/research_dataset.parquet", "sha256": "82e0020a3e15a8020fa041dea428b45a3d57a5e7101901e50159d517e6cf1c11", "status": "READ_DURING_INPUT_INSPECTION_ONLY_NOT_USED_IN_FINAL_ADAPTER_OR_ANY_FIT", "reason": "Authoritative raw-plus-forward-rehab training matrix replaces legacy QFQ-plus-overlay research matrix"}
PINNED = {
    R5_SOURCE: "1cdff21546e4ad5bd7cfd732b221f784222977d476a640b3b8765c911139b880",
    R4_SOURCE: "d643102915e138b24ca4dbfe9cea4fb9e6b076b96fcdd81bae81f66d25ee219b",
    SURFACE_SOURCE: "f0b1111051ff6dd986241ec43aea9469f9906747d67dae2f31ade9a0af1d3d8c",
    SURFACE_MANIFEST: "94d3bec3c8fe34075b6dc4a3bc03954015b87c28247d3e49e79b254795c4c7ec",
    CALENDAR_PATH: "f61c8f8d47cd94ae4b75eab51566917bd809abd2afe8b280858fb04ba36e93e4",
    CALENDAR_PATH.with_suffix(".manifest.json"): "df46c7df02af5addd584957e3980474ef9b2a87e5044fae29944fba94b3dbca7",
    Path("D:/us-tech-quant-results/A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1/raw_a2_top40_membership_checkpoint.parquet"): "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17",
    TRAINING_MATRIX: "31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb",
    Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/portfolio_daily.parquet"): "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73",
    Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/scripts/run_rebuild.py"): "68f4eb6599638db4c6af51b0ff8894f757b78a60dba27ce03e5c798e9508cc0e",
    Path("D:/us-tech-quant-cache/13f_pit_v1/a_a2_quarterly_13f_r1/rehab_factors.parquet"): "57e82836d7674cf5e19e1fd247f3133c36e560badd54800aa3644167b3aae423",
    # Mutable provider containers pinned at this campaign's input inspection.
    Path("D:/us-tech-quant-data/stocks/QQQ/daily_raw.parquet"): "3f0942fb709d8b8d654137c2d35271fb81750f144010d2d039f1e316a3618ed3",
    Path("D:/us-tech-quant-data/stocks/SOXX/daily_raw.parquet"): "b3af9946a33cb0cb6f1be2681bebe2d00755153970a808720a8d747bffe9900a",
}


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_hash(path: Path, expected: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"INPUT_HASH_MISMATCH:{path}")
    return actual


def footer_dates(path: Path, columns: tuple[str, ...], *, physical_pre2026: bool) -> dict:
    """Inspect only Parquet metadata; fail before a physical-only body read."""
    metadata = pq.ParquetFile(path)
    result = {"path": str(path), "rows": metadata.metadata.num_rows, "columns": {}}
    for column in columns:
        index = metadata.schema_arrow.names.index(column)
        extrema = []
        for group in range(metadata.metadata.num_row_groups):
            statistics = metadata.metadata.row_group(group).column(index).statistics
            if statistics is None or not statistics.has_min_max:
                raise RuntimeError(f"DATE_STATISTICS_MISSING:{path}:{column}")
            extrema.extend([pd.Timestamp(statistics.min), pd.Timestamp(statistics.max)])
        low, high = min(extrema), max(extrema)
        if physical_pre2026 and high >= END:
            raise RuntimeError(f"PHYSICAL_POST2025_DATE:{path}:{column}")
        result["columns"][column] = {"min": str(low), "max": str(high)}
    result["read_boundary"] = "PHYSICAL_PRE2026" if physical_pre2026 else "ARROW_PREDICATE_BEFORE_PANDAS"
    return result


def _import(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_sources() -> tuple[ModuleType, ModuleType, ModuleType]:
    """Import definitions only, with no broad R5 preflight or result reads."""
    for path in (R5_SOURCE, R4_SOURCE, SURFACE_SOURCE):
        verify_hash(path, PINNED[path])
    # Shared imports are ordinary source helpers. Exact business implementations
    # below are loaded by path, so archived/current module name collisions cannot
    # substitute another simulator, panel builder, or frozen-surface loader.
    for root in (SURFACE_ROOT, R5_ROOT):
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
    r5 = _import("tail_input_existing_r5", R5_SOURCE)
    r4 = _import("tail_input_existing_r4", R4_SOURCE)
    surface = _import("tail_input_existing_frozen_surface", SURFACE_SOURCE)
    return r5, r4, surface


def _validate_prices(prices: pd.DataFrame, wanted: set[str]) -> None:
    if prices.empty or not wanted.issubset(set(prices.ticker)):
        raise RuntimeError("PRICE_TICKER_COVERAGE_FAILURE")
    if prices.trade_date.ge(END).any() or prices.trade_date.lt(START).any():
        raise RuntimeError("PRICE_DATE_BOUNDARY_FAILURE")
    if prices.duplicated(["ticker", "trade_date"]).any():
        raise RuntimeError("DUPLICATE_PRICE_IDENTITY")
    values = prices[["open", "high", "low", "close"]].to_numpy(float)
    if not np.isfinite(values).all() or not (values > 0).all():
        raise RuntimeError("INVALID_OHLC")
    if set(prices.autype) != {"PIT_FORWARD_REHAB_INDEX"}:
        raise RuntimeError("PRICE_ADJUSTMENT_IDENTITY_FAILURE")
    if set(prices.source) != {"MOOMOO_OPEND_RAW_PLUS_REHAB"}:
        raise RuntimeError("PRICE_PROVIDER_IDENTITY_FAILURE")


def load_full_checkpoint() -> pd.DataFrame:
    """Read the full pre-2026 frozen checkpoint, independent of label maturity."""
    path = Path("D:/us-tech-quant-results/A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1/raw_a2_top40_membership_checkpoint.parquet")
    verify_hash(path, PINNED[path])
    footer_dates(path, ("decision_date",), physical_pre2026=True)
    frame = pads.dataset(path, format="parquet").to_table(
        filter=pads.field("decision_date") < END.to_pydatetime(),
    ).to_pandas().rename(columns={"decision_date": "signal_date", "ticker_if_available": "ticker"})
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if frame.groupby("signal_date").size().ne(40).any() or frame.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("FULL_CHECKPOINT_CARDINALITY_FAILURE")
    return frame.sort_values(["signal_date", "raw_rank"], kind="mergesort").reset_index(drop=True)


def _join_authoritative_panel(checkpoint: pd.DataFrame, research: pd.DataFrame, r5: ModuleType) -> tuple[pd.DataFrame, dict]:
    """Reuse the frozen checkpoint's one-to-one date/ticker identity bridge."""
    panel = checkpoint.merge(research, on=["signal_date", "ticker"], how="inner", validate="one_to_one")
    panel = panel.sort_values(["signal_date", "raw_rank"], kind="mergesort").reset_index(drop=True)
    if panel.empty or panel.groupby("signal_date").size().ne(40).any():
        raise RuntimeError("MATURE_AUTHORITATIVE_TOP40_CARDINALITY_FAILURE")
    expected_dates = pd.DatetimeIndex(checkpoint.loc[checkpoint.signal_date.le(panel.signal_date.max()), "signal_date"].unique())
    if not expected_dates.isin(pd.DatetimeIndex(panel.signal_date.unique())).all():
        raise RuntimeError("INTERNAL_CHECKPOINT_DATE_DROPPED")
    if panel.signal_date.ge(END).any() or panel.target_end_date.ge(END).any():
        raise RuntimeError("AUTHORITATIVE_PANEL_DATE_FAILURE")
    if panel.target.isna().any() or not np.isfinite(panel[list(r5.BASE_FEATURES)].to_numpy(float)).all():
        raise RuntimeError("AUTHORITATIVE_PANEL_FEATURE_OR_LABEL_FAILURE")
    if (pd.to_datetime(panel.prediction_asof_date) > panel.signal_date).any():
        raise RuntimeError("PREDICTION_AVAILABILITY_FAILURE")
    panel["raw_rank_strength"] = 1.0 - (panel.raw_rank.astype(float) - 1.0) / 39.0
    panel["raw_score_z"] = r5._safe_zscore(panel, "raw_score")
    return panel, {"rows": len(panel), "decision_dates": panel.signal_date.nunique(), "decision_start": panel.signal_date.min(), "decision_end": panel.signal_date.max(), "max_label_realization_date": panel.target_end_date.max(), "dropped_unmatured_checkpoint_dates": checkpoint.signal_date.nunique() - panel.signal_date.nunique(), "target_contract": "MEAN_ER_3D_5D_10D_20D_CLOSE_TO_CLOSE_QQQ_RELATIVE", "maximum_label_horizon_sessions": 20, "pit_availability_violation_count": 0}


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, ModuleType, dict]:
    """Return mature Top40 panel, 2020-2025 OHLCV, frozen R4, and lineage.

    Panel target is a label, never a feature candidate. It is the mean QQQ-relative
    close-return target over 3/5/10/20 sessions, not a pure 20-day return.
    The panel's intersection ends when the maximum 20-session label matures;
    this adapter preserves that known selection/exposure limitation.
    """
    hashes = {str(path): verify_hash(path, digest) for path, digest in PINNED.items()}
    r5, r4, surface_loader = load_sources()
    footers = [
        footer_dates(r5.RAW_TOP40, ("decision_date",), physical_pre2026=True),
        footer_dates(TRAINING_MATRIX, ("signal_date", "target_end_date"), physical_pre2026=True),
        footer_dates(r5.REHAB_FACTORS, ("ex_div_date",), physical_pre2026=False),
        *[footer_dates(path, ("date",), physical_pre2026=False) for path in r5.BENCHMARK_RAW.values()],
    ]
    manifest = json.loads(SURFACE_MANIFEST.read_text(encoding="utf-8"))
    surface_loader.verify_manifest_contract(manifest)
    for part in manifest["partitions"]:
        footers.append(footer_dates(Path(manifest["surface_path"]) / part["relative_path"], ("trade_date",), physical_pre2026=True))
    full_checkpoint = load_full_checkpoint()
    research = pads.dataset(TRAINING_MATRIX, format="parquet").to_table(
        filter=(pads.field("signal_date") < END.to_pydatetime()) & (pads.field("target_end_date") < END.to_pydatetime()),
    ).to_pandas()
    panel, panel_audit = _join_authoritative_panel(full_checkpoint, research, r5)
    # Load price coverage for the full frozen control as well as mature-label
    # research; this does not add those names to any earlier decision universe.
    wanted = set(full_checkpoint.ticker.astype(str))
    # Preserve authoritative ticker/transport identities; never guess US.+ticker.
    equity = surface_loader.load_frozen_surface(manifest_path=SURFACE_MANIFEST)
    equity = equity.loc[equity.ticker.isin(wanted)].copy()
    if not wanted.issubset(set(equity.ticker)):
        raise RuntimeError("FROZEN_EQUITY_COVERAGE_FAILURE")
    benchmarks, benchmark_audit = r5.load_raw_rehab_benchmarks()
    # This lower truncation occurs after PIT forward-rehab calculation so events
    # before 2020 cannot silently change the benchmark's adjustment initialization.
    benchmarks = benchmarks.loc[benchmarks.trade_date.ge(START)].copy()
    prices = pd.concat([equity, benchmarks], ignore_index=True)
    prices = prices.sort_values(["trade_date", "ticker"], kind="mergesort").reset_index(drop=True)
    _validate_prices(prices, wanted | {"QQQ", "SOXX"})
    calendar = pd.DatetimeIndex(prices.loc[prices.ticker.eq("QQQ"), "trade_date"])
    expected_calendar = pads.dataset(CALENDAR_PATH, format="parquet").to_table(
        columns=["trade_date"],
        filter=(pads.field("trade_date") >= "2020-01-01") & (pads.field("trade_date") < "2026-01-01"),
    ).to_pandas()
    expected_calendar = pd.DatetimeIndex(pd.to_datetime(expected_calendar.trade_date)).sort_values()
    if not calendar.equals(expected_calendar):
        raise RuntimeError("QQQ_CALENDAR_DIFFERS_FROM_PINNED_XNYS_SESSIONS")
    if not pd.DatetimeIndex(panel.signal_date.unique()).isin(calendar).all():
        raise RuntimeError("PANEL_DATE_NOT_ON_BENCHMARK_CALENDAR")
    lineage = {
        "scope": "PRE2026_EXPLORATORY_INPUTS_ONLY",
        "source_and_input_hashes": hashes,
        "excluded_legacy_input": LEGACY_RESEARCH_DATASET,
        "footer_audits": footers,
        "surface_contract_sha256": manifest["contract_sha256"],
        "surface_full_content_sha256": manifest["full_content_sha256"],
        "panel": {**panel_audit, "schema": {c: str(t) for c, t in panel.dtypes.items()}},
        "full_checkpoint": {"rows": len(full_checkpoint), "date_start": full_checkpoint.signal_date.min(), "date_end": full_checkpoint.signal_date.max(), "date_count": full_checkpoint.signal_date.nunique(), "tickers": full_checkpoint.ticker.nunique()},
        "prices": {"rows": len(prices), "tickers": prices.ticker.nunique(), "min_date": prices.trade_date.min(), "max_date": prices.trade_date.max()},
        "benchmarks": benchmark_audit,
        "calendar": {"path": str(CALENDAR_PATH), "session_count": len(calendar), "matches_pinned_XNYS": True},
        "simulator_source": str(R4_SOURCE),
        "cost_convention": "cost_bps * 0.5 * (buy_notional + sell_notional) / pretrade_NAV",
        "read_boundary": "FROZEN_PHYSICAL_EQUITIES_AND_PANEL;ARROW_PRE2026_BENCHMARK_AND_REHAB_PREDICATES",
        "limitations": ["2023-2025 repeatedly exposed validation, not untouched test", "Mature maximum-20-session multi-horizon target intersection retained", "Historical universe/PIT identity inherited, not newly established", "Daily OHLCV availability inherited; this adapter does not prove intraday publication timing"],
        "fits": 0, "economic_evaluations": 0,
    }
    for path, digest in PINNED.items():
        verify_hash(path, digest)
    lineage["source_unchanged_after_read"] = True
    return panel, prices, r4, lineage
