"""PIT 24-manager 13F-change alpha research layered on authoritative Raw A2.

The module deliberately reuses the canonical A2 universe, annual OOF ranks,
effective-quarter ledger, local corporate-action price construction, and the
position-ledger replay engine.  It performs three and only three economic
trials: Raw A2, standalone institutional change, and the fixed 80/20 blend.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


TASK_ID = "A2_13F_INSTITUTIONAL_CHANGE_ALPHA_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
SOURCE_ROOT = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
PIT_ROOT = RESULTS / "13f_pit_v1"
OUT = RESULTS / TASK_ID
REBUILD_SOURCE = SOURCE_ROOT / "scripts" / "run_rebuild.py"
A2_SOURCE = REPO / "scripts" / "v22" / "abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
BOOTSTRAP_SOURCE = REPO / "scripts" / "v22" / "a2_open_research_engine.py"
BOOTSTRAP_CONFIG = REPO / "config" / "v22" / "a2_open_research_r1.json"
MANAGER_CONFIG = REPO / "config" / "v22" / "authoritative_24_manager_master_r1.json"

SELECTED_PATH = SOURCE_ROOT / "universe" / "selected_top100_24_manager.parquet"
MEMBERS_PATH = SOURCE_ROOT / "universe" / "quarterly_universe_members.parquet"
ACTIVE_PATH = SOURCE_ROOT / "universe" / "daily_active_quarter_ledger.parquet"
ELIGIBLE_PATH = SOURCE_ROOT / "universe" / "daily_eligible_universe_membership.parquet"
MANAGER_MANIFEST_PATH = SOURCE_ROOT / "audit" / "authoritative_24_manager_manifest.csv"
OOF_PATH = SOURCE_ROOT / "A2" / "oof_predictions.parquet"
TRAINING_PATH = SOURCE_ROOT / "A2" / "training_matrix.parquet"
CONTROL_DAILY_PATH = SOURCE_ROOT / "A2" / "portfolio_daily.parquet"

BOUNDARY = pd.Timestamp("2026-01-01")
MANAGER_COUNT = 24
TOP_N = 20
COST_BPS = 10
BLEND_A2_WEIGHT = 0.80
BLEND_INSTITUTIONAL_WEIGHT = 0.20
VINTAGE_DOMINANCE_LIMIT = 0.50
REDUNDANCY_LIMIT = 0.95
COMPONENT_COLUMNS = (
    "holder_breadth_change",
    "top100_entry_exit_balance",
    "consensus_top100_position_weight_change",
    "accumulation_persistence",
)
COMPONENT_LABELS = {
    "holder_breadth_change": "HOLDER_BREADTH_CHANGE",
    "top100_entry_exit_balance": "TOP100_ENTRY_EXIT_BALANCE",
    "consensus_top100_position_weight_change": "CONSENSUS_TOP100_POSITION_WEIGHT_CHANGE",
    "accumulation_persistence": "ACCUMULATION_PERSISTENCE",
}
STRATEGY_RANKS = {
    "C0_RAW_A2": "a2_rank",
    "C1_INSTITUTIONAL_CHANGE_STANDALONE": "institutional_rank",
    "C2_A2_PLUS_INSTITUTIONAL_CHANGE": "fixed_blend_rank",
}


class ResearchContractError(RuntimeError):
    """A temporal, source, trial-count, or portfolio-contract violation."""


def require(condition: bool, code: str, evidence: object = "") -> None:
    if not condition:
        detail = f"|{evidence}" if evidence != "" else ""
        raise ResearchContractError(f"{code}{detail}")


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def quarter_key(value: str) -> tuple[int, int]:
    year, quarter = str(value).upper().split("Q")
    return int(year), int(quarter)


def detect_a2_change_overlap(feature_columns: Iterable[str]) -> str:
    """Detect exact/effective 13F-change inputs in the Raw A2 score lineage."""
    terms = ("holder", "breadth", "manager", "institution", "13f", "crowd", "entry", "exit")
    matches = sorted(column for column in feature_columns if any(term in column.lower() for term in terms))
    require(not matches, "RAW_A2_13F_CHANGE_FEATURE_OVERLAP", matches)
    return "NONE_IN_A2_SCORING_FEATURES__A2_UNIVERSE_IS_13F_LEVEL_DERIVED"


def validate_manager_contract(
    selected: pd.DataFrame, manager_ids: Iterable[str], quarters: Iterable[str]
) -> tuple[str, ...]:
    expected = tuple(sorted(str(value) for value in manager_ids))
    require(len(expected) == MANAGER_COUNT, "MANAGER_REGISTRY_COUNT_FAILURE", len(expected))
    require(len(set(expected)) == MANAGER_COUNT, "MANAGER_REGISTRY_DUPLICATE")
    actual = tuple(sorted(selected.manager_id.astype(str).unique()))
    require(actual == expected, "SELECTED_MANAGER_SET_MISMATCH")
    for quarter in quarters:
        present = tuple(sorted(selected.loc[selected.quarter.eq(quarter), "manager_id"].astype(str).unique()))
        require(present == expected, "QUARTER_MANAGER_SET_MISMATCH", quarter)
    return expected


def validate_outcome_boundary(frame: pd.DataFrame) -> None:
    labeled = frame.loc[frame.target.notna()].copy()
    require(not labeled.empty, "NO_MATURE_PRE2026_OUTCOMES")
    require(labeled.target_end_date.notna().all(), "MATURE_TARGET_END_MISSING")
    require(pd.to_datetime(labeled.target_end_date).lt(BOUNDARY).all(), "POST2025_OUTCOME_USED")


def build_quarter_change_features(
    selected: pd.DataFrame,
    quarters: Iterable[str],
    manager_ids: Iterable[str],
) -> pd.DataFrame:
    """Build the four fixed change components from truncated eligible Top100 rows.

    reported_value_usd is normalized inside each manager-quarter eligible Top100.
    Every manager contributes equally; a missing security has position weight zero.
    Appearance/disappearance is explicitly a Top100 transition, not a fund trade.
    """
    ordered_quarters = tuple(sorted(set(map(str, quarters)), key=quarter_key))
    managers = tuple(sorted(set(map(str, manager_ids))))
    require(len(managers) > 0, "EMPTY_MANAGER_SET")
    use = selected.loc[
        selected.quarter.astype(str).isin(ordered_quarters)
        & selected.manager_id.astype(str).isin(managers),
        ["quarter", "manager_id", "cusip", "reported_value_usd"],
    ].copy()
    require(not use.empty, "EMPTY_SELECTED_TOP100")
    require(not use.duplicated(["quarter", "manager_id", "cusip"]).any(), "DUPLICATE_MANAGER_SECURITY")
    use["reported_value_usd"] = pd.to_numeric(use.reported_value_usd, errors="coerce")
    require(np.isfinite(use.reported_value_usd).all() and use.reported_value_usd.gt(0).all(), "INVALID_REPORTED_VALUE")
    denominator = use.groupby(["quarter", "manager_id"], sort=False).reported_value_usd.transform("sum")
    require(denominator.gt(0).all(), "INVALID_TOP100_DENOMINATOR")
    use["top100_position_weight"] = use.reported_value_usd / denominator
    sums = use.groupby(["quarter", "manager_id"], sort=False).top100_position_weight.sum()
    require(np.allclose(sums.to_numpy(float), 1.0, atol=1e-12, rtol=0.0), "TOP100_WEIGHT_IDENTITY_FAILURE")

    rows: list[pd.DataFrame] = []
    for prior_quarter, current_quarter in zip(ordered_quarters[:-1], ordered_quarters[1:]):
        prior = use.loc[use.quarter.eq(prior_quarter), ["manager_id", "cusip", "top100_position_weight"]].rename(
            columns={"top100_position_weight": "prior_weight"}
        )
        current = use.loc[use.quarter.eq(current_quarter), ["manager_id", "cusip", "top100_position_weight"]].rename(
            columns={"top100_position_weight": "current_weight"}
        )
        joined = prior.merge(current, on=["manager_id", "cusip"], how="outer", validate="one_to_one")
        joined["prior_present"] = joined.prior_weight.notna()
        joined["current_present"] = joined.current_weight.notna()
        joined[["prior_weight", "current_weight"]] = joined[["prior_weight", "current_weight"]].fillna(0.0)
        joined["entry"] = (~joined.prior_present & joined.current_present).astype(int)
        joined["exit"] = (joined.prior_present & ~joined.current_present).astype(int)
        grouped = joined.groupby("cusip", as_index=False).agg(
            current_holders=("current_present", "sum"),
            prior_holders=("prior_present", "sum"),
            entries=("entry", "sum"),
            exits=("exit", "sum"),
            current_weight_sum=("current_weight", "sum"),
            prior_weight_sum=("prior_weight", "sum"),
        )
        grouped.insert(0, "quarter", current_quarter)
        count = float(len(managers))
        grouped["holder_breadth_change"] = (grouped.current_holders - grouped.prior_holders) / count
        grouped["top100_entry_exit_balance"] = (grouped.entries - grouped.exits) / count
        grouped["consensus_top100_position_weight_change"] = (
            grouped.current_weight_sum - grouped.prior_weight_sum
        ) / count
        rows.append(grouped[["quarter", "cusip", *COMPONENT_COLUMNS[:3]]])
    require(rows, "INSUFFICIENT_QUARTERS_FOR_CHANGE")
    change = pd.concat(rows, ignore_index=True).sort_values(["quarter", "cusip"], kind="mergesort")
    change["consensus_direction_rank"] = change.groupby("quarter", sort=False)[
        "consensus_top100_position_weight_change"
    ].rank(method="average", pct=True)
    next_quarter = {old: new for old, new in zip(ordered_quarters[:-1], ordered_quarters[1:])}
    lag = change[["quarter", "cusip", "consensus_direction_rank"]].copy()
    lag["quarter"] = lag.quarter.map(next_quarter)
    lag = lag.dropna(subset=["quarter"]).rename(columns={"consensus_direction_rank": "prior_consensus_direction_rank"})
    change = change.merge(lag, on=["quarter", "cusip"], how="left", validate="one_to_one")
    change["accumulation_persistence"] = (
        (change.consensus_direction_rank - 0.5)
        + (change.prior_consensus_direction_rank - 0.5)
    ) / 2.0
    require(not change.duplicated(["quarter", "cusip"]).any(), "DUPLICATE_QUARTER_CHANGE")
    return change.reset_index(drop=True)


def stable_rank(frame: pd.DataFrame, score_column: str, rank_column: str) -> pd.DataFrame:
    ranked = frame.sort_values(
        ["signal_date", score_column, "ticker"], ascending=[True, False, True], kind="mergesort"
    ).copy()
    ranked[rank_column] = ranked.groupby("signal_date", sort=False).cumcount() + 1
    return ranked.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)


def add_cross_sectional_scores(panel: pd.DataFrame) -> pd.DataFrame:
    scored = panel.copy()
    for component in COMPONENT_COLUMNS:
        scored[f"{component}_rank_pct"] = scored.groupby("signal_date", sort=False)[component].rank(
            method="average", pct=True
        )
    rank_columns = [f"{component}_rank_pct" for component in COMPONENT_COLUMNS]
    scored["institutional_change_score"] = scored[rank_columns].mean(axis=1, skipna=True)
    require(scored.institutional_change_score.notna().all(), "INSTITUTIONAL_COMPOSITE_MISSING")
    scored["institutional_change_rank_pct"] = scored.groupby("signal_date", sort=False)[
        "institutional_change_score"
    ].rank(method="average", pct=True)
    sizes = scored.groupby("signal_date", sort=False).ticker.transform("size").astype(float)
    scored["a2_rank_pct"] = (sizes - scored.a2_rank.astype(float) + 1.0) / sizes
    scored["fixed_blend_score"] = (
        BLEND_A2_WEIGHT * scored.a2_rank_pct
        + BLEND_INSTITUTIONAL_WEIGHT * scored.institutional_change_rank_pct
    )
    scored = stable_rank(scored, "institutional_change_score", "institutional_rank")
    scored = stable_rank(scored, "fixed_blend_score", "fixed_blend_rank")
    assert_portfolio_ranking_contract(scored)
    return scored


def assert_portfolio_ranking_contract(panel: pd.DataFrame) -> None:
    dates = pd.DatetimeIndex(sorted(panel.signal_date.unique()))
    require(not panel.duplicated(["signal_date", "ticker"]).any(), "DUPLICATE_DAILY_SECURITY")
    require(panel.groupby("signal_date").ticker.nunique().reindex(dates).gt(TOP_N).all(), "UNIVERSE_NOT_ABOVE_TOP20")
    for rank_column in STRATEGY_RANKS.values():
        top = panel.loc[panel[rank_column].le(TOP_N)]
        counts = top.groupby("signal_date").ticker.nunique().reindex(dates, fill_value=0)
        require(counts.eq(TOP_N).all(), "TOP20_CONTRACT_FAILURE", rank_column)


def attach_change_panel(inputs: dict[str, pd.DataFrame], changes: pd.DataFrame) -> pd.DataFrame:
    oof = inputs["oof"].copy()
    eligible = inputs["eligible"][["signal_date", "ticker", "active_13f_quarter", "cusip"]].copy()
    require(not eligible.duplicated(["signal_date", "ticker"]).any(), "ELIGIBLE_MEMBERSHIP_DUPLICATE")
    panel = oof.merge(eligible, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    require(panel.cusip.notna().all(), "OOF_TO_PIT_MEMBERSHIP_FAILURE")
    active = inputs["active"][["signal_date", "active_13f_quarter", "quarter_effective_date"]].copy()
    panel = panel.merge(active, on=["signal_date", "active_13f_quarter"], how="left", validate="many_to_one")
    require(panel.quarter_effective_date.notna().all(), "ACTIVE_QUARTER_JOIN_FAILURE")
    require((panel.signal_date >= panel.quarter_effective_date).all(), "PREMATURE_13F_INFORMATION")
    panel = panel.merge(
        changes,
        left_on=["active_13f_quarter", "cusip"],
        right_on=["quarter", "cusip"],
        how="left",
        validate="many_to_one",
    )
    for component in COMPONENT_COLUMNS[:3]:
        require(panel[component].notna().all(), "BASE_COMPONENT_COVERAGE_FAILURE", component)
    targets = inputs["targets"]
    panel = panel.merge(
        targets[["signal_date", "ticker", "target_end_date"]],
        on=["signal_date", "ticker"],
        how="left",
        validate="one_to_one",
    )
    validate_outcome_boundary(panel)
    return add_cross_sectional_scores(panel)


def load_inputs() -> tuple[dict[str, pd.DataFrame], Any, str, dict[str, str]]:
    required = [
        SELECTED_PATH, MEMBERS_PATH, ACTIVE_PATH, ELIGIBLE_PATH, MANAGER_MANIFEST_PATH,
        OOF_PATH, TRAINING_PATH, CONTROL_DAILY_PATH, REBUILD_SOURCE, A2_SOURCE, MANAGER_CONFIG,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    require(not missing, "AUTHORITATIVE_INPUT_MISSING", missing)
    r1 = import_file("a2_13f_change_r1_source", A2_SOURCE)
    overlap = detect_a2_change_overlap(r1.FEATURE_COLUMNS)
    manifest = pd.read_csv(MANAGER_MANIFEST_PATH)
    selected = pd.read_parquet(SELECTED_PATH)
    members = pd.read_parquet(MEMBERS_PATH)
    active = pd.read_parquet(ACTIVE_PATH)
    eligible = pd.read_parquet(ELIGIBLE_PATH)
    oof = pd.read_parquet(OOF_PATH)
    targets = pd.read_parquet(TRAINING_PATH, columns=["signal_date", "ticker", "target", "target_end_date"])
    for frame, columns in (
        (active, ["signal_date", "quarter_effective_date"]),
        (eligible, ["signal_date"]), (oof, ["signal_date"]),
        (targets, ["signal_date", "target_end_date"]),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    oof = oof.loc[oof.signal_date.lt(BOUNDARY)].copy()
    active = active.loc[active.signal_date.lt(BOUNDARY)].copy()
    eligible = eligible.loc[eligible.signal_date.lt(BOUNDARY)].copy()
    targets = targets.loc[targets.signal_date.lt(BOUNDARY) & targets.target_end_date.lt(BOUNDARY)].copy()
    require(oof.signal_date.max() == pd.Timestamp("2025-12-31"), "OOF_SCOPE_END_MISMATCH")
    require(oof.split.nunique() == 3, "OUTER_FOLD_COUNT_MISMATCH", oof.split.unique())
    require(oof.a2_model_name.eq("HistGradientBoostingRegressor").all(), "RAW_A2_MODEL_MISMATCH")
    require(oof.target.notna().sum() == len(targets.loc[targets.signal_date.isin(oof.signal_date.unique())]), "MATURE_TARGET_COUNT_MISMATCH")
    active_quarters = tuple(sorted(active.active_13f_quarter.astype(str).unique(), key=quarter_key))
    all_needed = tuple(q for q in sorted(selected.quarter.astype(str).unique(), key=quarter_key) if quarter_key(q) <= quarter_key(active_quarters[-1]))
    manager_ids = tuple(sorted(manifest.normalized_manager_id.astype(str).unique()))
    validate_manager_contract(selected, manager_ids, all_needed)
    config = json.loads(MANAGER_CONFIG.read_text(encoding="utf-8"))
    require(int(config["manager_count"]) == MANAGER_COUNT, "MANAGER_CONFIG_COUNT_MISMATCH")
    require(int(config["per_manager_top_n"]) == 100, "SOURCE_TOP100_CONTRACT_MISMATCH")
    require(int(config["max_universe_size"]) == 900, "UNIVERSE_CAP_CONTRACT_MISMATCH")
    hashes = {str(path): sha256_file(path) for path in required}
    return {
        "manifest": manifest, "selected": selected, "members": members,
        "active": active, "eligible": eligible, "oof": oof, "targets": targets,
        "active_quarters": pd.DataFrame({"quarter": active_quarters}),
        "needed_quarters": pd.DataFrame({"quarter": all_needed}),
    }, r1, overlap, hashes


def target_map(panel: pd.DataFrame, rank_column: str) -> dict[pd.Timestamp, dict[str, float]]:
    chosen = panel.loc[panel[rank_column].le(TOP_N), ["signal_date", "ticker"]]
    mapping: dict[pd.Timestamp, dict[str, float]] = {}
    for date, day in chosen.groupby("signal_date", sort=True):
        require(len(day) == TOP_N and day.ticker.nunique() == TOP_N, "TARGET_MAP_TOP20_FAILURE", date)
        mapping[pd.Timestamp(date)] = {str(ticker): 1.0 / TOP_N for ticker in day.ticker}
    return mapping


def load_authoritative_portfolio_runtime(inputs: dict[str, pd.DataFrame]) -> tuple[Any, Any, pd.DataFrame, int]:
    """Rebuild only the existing in-memory local runtime; external calls are impossible."""
    rebuild = import_file("a2_13f_change_rebuild", REBUILD_SOURCE)
    _, _, r1, r0f, r0f1 = rebuild.load_modules()
    index, scan_failures = rebuild.raw_file_index()
    require(not scan_failures, "RAW_HISTORY_SCAN_FAILURE", scan_failures[:3])
    available_codes = set(
        inputs["members"].loc[
            inputs["members"].moomoo_transport_code.isin(index), "moomoo_transport_code"
        ].astype(str)
    )
    rehab_status = pd.read_csv(rebuild.RUN_CACHE / "rehab_status.csv", keep_default_na=False)
    cached_codes = set(rehab_status.loc[rehab_status.status.eq("PASS"), "code"].astype(str))
    require(available_codes.issubset(cached_codes), "LOCAL_REHAB_CACHE_INCOMPLETE", sorted(available_codes - cached_codes)[:10])

    def forbidden_network() -> None:
        raise ResearchContractError("NETWORK_OR_MOOMOO_FORBIDDEN")

    rebuild.import_moomoo = forbidden_network
    rebuild.raw_file_index = lambda: (index, [])
    pieces = []
    for year in range(2020, 2026):
        path = rebuild.QFQ_ROOT / f"year={year}" / "prices.parquet"
        require(path.is_file(), "QQQ_PRICE_YEAR_MISSING", year)
        part = pd.read_parquet(path, columns=["ticker", "trade_date", "open", "close", "volume", "autype", "source"])
        pieces.append(part.loc[part.ticker.astype(str).str.upper().eq("QQQ")].copy())
    qqq = pd.concat(pieces, ignore_index=True)
    qqq["trade_date"] = pd.to_datetime(qqq.trade_date).dt.normalize()
    qqq = qqq.sort_values("trade_date", kind="mergesort").drop_duplicates("trade_date", keep="last").reset_index(drop=True)
    require(qqq.trade_date.lt(BOUNDARY).all(), "POST2025_QQQ_PRICE_READ")
    active = inputs["active"].loc[inputs["active"].signal_date.lt(BOUNDARY)].copy()
    prices, _, _, _, audit = rebuild.build_prices_and_u_t(r1, r0f1, inputs["members"], active, qqq)
    require(int(audit["rehab_request_count"]) == 0, "EXTERNAL_REHAB_REQUEST_OCCURRED")
    require(pd.to_datetime(prices.trade_date).lt(BOUNDARY).all(), "POST2025_PORTFOLIO_PRICE_READ")
    return rebuild, r0f, prices, 0


def reconcile_and_simulate(
    panel: pd.DataFrame, rebuild: Any, r0f: Any, prices: pd.DataFrame
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    last_signal = pd.Timestamp(calendar[-3])
    simulation_panel = panel.loc[panel.signal_date.le(last_signal)].copy()
    require(simulation_panel.signal_date.max() == last_signal, "TERMINAL_SIGNAL_DATE_MISMATCH")
    simulations: dict[str, dict[str, Any]] = {}
    for strategy, rank_column in STRATEGY_RANKS.items():
        result = r0f.reconstruct_path(
            model=strategy,
            target_map=target_map(simulation_panel, rank_column),
            qfq=prices,
            signal_dates=simulation_panel.signal_date.unique(),
            cost_bps=COST_BPS,
        )
        simulations[strategy] = {"daily": result.daily, "positions": result.positions, "trades": result.trades}
    got = simulations["C0_RAW_A2"]["daily"]
    reference = pd.read_parquet(CONTROL_DAILY_PATH)
    reference["execution_date"] = pd.to_datetime(reference.execution_date)
    require(got.execution_date.equals(reference.execution_date), "CONTROL_EXECUTION_DATE_MISMATCH")
    numeric = (
        "reconstructed_daily_return", "reconstructed_nav", "reconstructed_turnover",
        "reconstructed_transaction_cost", "actual_risky_name_count",
    )
    errors = {
        column: float(np.nanmax(np.abs(got[column].to_numpy(float) - reference[column].to_numpy(float))))
        for column in numeric
    }
    require(max(errors.values()) <= np.finfo(float).eps, "CONTROL_REPLAY_MISMATCH", errors)
    reconciliation = {
        "status": "PASS_EXACT_OR_MACHINE_PRECISION",
        "scope_start": str(got.execution_date.min().date()),
        "scope_end": str(got.execution_date.max().date()),
        "last_signal_date": str(last_signal.date()),
        "row_count": int(len(got)),
        "max_abs_errors": errors,
    }
    return reconciliation, simulations


def performance_metrics(daily: pd.DataFrame) -> dict[str, float | int]:
    ordered = daily.sort_values("execution_date", kind="mergesort")
    returns = ordered.reconstructed_daily_return.to_numpy(float)
    gross_returns = ordered.reconstructed_gross_return.to_numpy(float)
    require(len(returns) > 0 and np.isfinite(returns).all(), "INVALID_PORTFOLIO_RETURNS")
    nav = np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    gross_nav = np.concatenate([[1.0], np.cumprod(1.0 + gross_returns)])
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    annualized_volatility = float(np.std(returns, ddof=0) * np.sqrt(252.0))
    annualized_return = float(np.mean(returns) * 252.0)
    negative = returns[returns < 0]
    downside = float(np.sqrt(np.mean(negative**2)) * np.sqrt(252.0)) if len(negative) else math.nan
    cumulative = float(nav[-1] - 1.0)
    cagr = float(nav[-1] ** (252.0 / len(returns)) - 1.0)
    max_drawdown = float(drawdown.min())
    return {
        "observation_count": int(len(returns)),
        "cumulative_return": cumulative,
        "gross_cumulative_return": float(gross_nav[-1] - 1.0),
        "cagr": cagr,
        "annualized_volatility": annualized_volatility,
        "sharpe": annualized_return / annualized_volatility if annualized_volatility > 0 else math.nan,
        "sortino": annualized_return / downside if downside > 0 else math.nan,
        "max_drawdown": max_drawdown,
        "calmar": cagr / abs(max_drawdown) if max_drawdown < 0 else math.nan,
        "turnover": float(ordered.reconstructed_turnover.mean() * 252.0),
        "transaction_cost": float(ordered.reconstructed_transaction_cost.sum()),
        "average_holdings": float(ordered.actual_risky_name_count.mean()),
    }


def execution_vintage_map(panel: pd.DataFrame, daily: pd.DataFrame) -> pd.Series:
    signals = panel[["signal_date", "active_13f_quarter"]].drop_duplicates().sort_values("signal_date")
    lookup = signals.set_index("signal_date").active_13f_quarter
    execution = pd.DatetimeIndex(daily.execution_date)
    prior_signal = pd.DatetimeIndex([lookup.index[lookup.index < date].max() for date in execution])
    vintage = lookup.reindex(prior_signal).ffill()
    vintage.index = execution
    return vintage


def strategy_metric_table(
    simulations: dict[str, dict[str, Any]], panel: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    control_daily = simulations["C0_RAW_A2"]["daily"].sort_values("execution_date")
    vintage = execution_vintage_map(panel, control_daily)
    for strategy, result in simulations.items():
        daily = result["daily"].sort_values("execution_date").copy()
        rows.append({"strategy": strategy, "scope_type": "aggregate", "scope_id": "PRE2026", **performance_metrics(daily)})
        for year, group in daily.groupby(daily.execution_date.dt.year, sort=True):
            fold = panel.loc[panel.signal_date.dt.year.eq(year), "split"].iloc[0]
            metrics = performance_metrics(group)
            rows.append({"strategy": strategy, "scope_type": "outer_fold", "scope_id": str(fold), **metrics})
            rows.append({"strategy": strategy, "scope_type": "calendar_year", "scope_id": str(int(year)), **metrics})
        daily["vintage"] = vintage.reindex(pd.DatetimeIndex(daily.execution_date)).to_numpy()
        for quarter, group in daily.groupby("vintage", sort=True):
            rows.append({"strategy": strategy, "scope_type": "13f_vintage", "scope_id": str(quarter), **performance_metrics(group)})
    metrics = pd.DataFrame(rows)
    delta_columns = [
        "cumulative_return", "gross_cumulative_return", "cagr", "sharpe",
        "max_drawdown", "turnover", "transaction_cost",
    ]
    raw = metrics.loc[metrics.strategy.eq("C0_RAW_A2")].set_index(["scope_type", "scope_id"])
    for column in delta_columns:
        metrics[f"delta_{column}_vs_raw"] = [
            float(row[column] - raw.at[(row.scope_type, row.scope_id), column])
            for _, row in metrics.iterrows()
        ]
    deltas = simulations["C2_A2_PLUS_INSTITUTIONAL_CHANGE"]["daily"][["execution_date", "reconstructed_daily_return"]].merge(
        control_daily[["execution_date", "reconstructed_daily_return"]],
        on="execution_date", suffixes=("_blend", "_raw"), validate="one_to_one",
    )
    deltas["vintage"] = vintage.reindex(pd.DatetimeIndex(deltas.execution_date)).to_numpy()
    deltas["incremental_return"] = deltas.reconstructed_daily_return_blend - deltas.reconstructed_daily_return_raw
    vintage_pnl = deltas.groupby("vintage", as_index=False).incremental_return.sum().sort_values("vintage")
    return metrics, vintage_pnl


def cross_sectional_diagnostics(panel: pd.DataFrame, signal_column: str) -> dict[str, float | int]:
    daily_rows: list[dict[str, float]] = []
    bucket_rows: list[dict[str, float | int]] = []
    for _, day in panel.groupby("signal_date", sort=True):
        diagnostic_columns = list(dict.fromkeys([signal_column, "a2_rank_pct", "target", "ticker"]))
        valid = day[diagnostic_columns].dropna(subset=[signal_column, "target"])
        if len(valid) < 20:
            continue
        ic = valid[signal_column].corr(valid.target, method="spearman")
        corr = valid[signal_column].corr(valid.a2_rank_pct, method="spearman")
        ordered = valid.sort_values([signal_column, "ticker"], ascending=[True, True], kind="mergesort").reset_index(drop=True)
        ordered["bucket"] = np.minimum(9, np.floor(np.arange(len(ordered)) * 10 / len(ordered)).astype(int)) + 1
        bucket_mean = ordered.groupby("bucket").target.mean()
        daily_rows.append({
            "ic": float(ic), "correlation_with_a2": float(corr),
            "top_minus_bottom": float(bucket_mean.loc[10] - bucket_mean.loc[1]),
        })
        bucket_rows.extend({"bucket": int(bucket), "return": float(value)} for bucket, value in bucket_mean.items())
    daily = pd.DataFrame(daily_rows)
    buckets = pd.DataFrame(bucket_rows).groupby("bucket").agg(return_mean=("return", "mean"))
    monotonicity = buckets.index.to_series().corr(buckets.return_mean, method="spearman")
    result: dict[str, float | int] = {
        "date_count": int(len(daily)),
        "row_count": int(panel[signal_column].notna().sum()),
        "coverage": float(panel[signal_column].notna().mean()),
        "mean_spearman_ic": float(daily.ic.mean()),
        "median_spearman_ic": float(daily.ic.median()),
        "positive_ic_share": float((daily.ic > 0).mean()),
        "top_minus_bottom_return": float(daily.top_minus_bottom.mean()),
        "correlation_with_raw_a2": float(daily.correlation_with_a2.mean()),
        "bucket_monotonicity_spearman": float(monotonicity),
    }
    for bucket in range(1, 11):
        result[f"bucket_{bucket}_return"] = float(buckets.at[bucket, "return_mean"])
    return result


def signal_metric_table(panel: pd.DataFrame) -> pd.DataFrame:
    labeled = panel.loc[panel.target.notna() & panel.target_end_date.lt(BOUNDARY)].copy()
    signals = {
        **{COMPONENT_LABELS[c]: f"{c}_rank_pct" for c in COMPONENT_COLUMNS},
        "INSTITUTIONAL_CHANGE_COMPOSITE": "institutional_change_rank_pct",
        "RAW_A2": "a2_rank_pct",
        "FIXED_80_20_BLEND": "fixed_blend_score",
    }
    rows: list[dict[str, Any]] = []
    scopes: list[tuple[str, str, pd.DataFrame]] = [("aggregate", "PRE2026", labeled)]
    scopes.extend(("outer_fold", str(fold), group) for fold, group in labeled.groupby("split", sort=True))
    scopes.extend(("calendar_year", str(int(year)), group) for year, group in labeled.groupby(labeled.signal_date.dt.year, sort=True))
    for scope_type, scope_id, frame in scopes:
        for signal_name, column in signals.items():
            rows.append({
                "signal": signal_name, "source_column": column,
                "scope_type": scope_type, "scope_id": scope_id,
                **cross_sectional_diagnostics(frame, column),
            })
    metrics = pd.DataFrame(rows)
    raw = metrics.loc[metrics.signal.eq("RAW_A2")].set_index(["scope_type", "scope_id"])
    metrics["incremental_ic_vs_raw"] = [
        float(row.mean_spearman_ic - raw.at[(row.scope_type, row.scope_id), "mean_spearman_ic"])
        for _, row in metrics.iterrows()
    ]
    return metrics


def bootstrap_diagnostic(simulations: dict[str, dict[str, Any]]) -> dict[str, float]:
    config = json.loads(BOOTSTRAP_CONFIG.read_text(encoding="utf-8"))
    engine = import_file("a2_13f_change_bootstrap", BOOTSTRAP_SOURCE)
    blend = simulations["C2_A2_PLUS_INSTITUTIONAL_CHANGE"]["daily"].sort_values("execution_date")
    raw = simulations["C0_RAW_A2"]["daily"].sort_values("execution_date")
    return engine.block_bootstrap_delta(
        blend.reconstructed_daily_return.to_numpy(float),
        raw.reconstructed_daily_return.to_numpy(float),
        int(config["blocked_bootstrap_block_days"]),
        int(config["blocked_bootstrap_repeats"]),
        int(config["random_seed"]),
    )


def finite_or_none(value: Any) -> Any:
    if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
        return None
    return value.item() if isinstance(value, np.generic) else value


def record_from_frame(frame: pd.DataFrame, **where: str) -> dict[str, Any]:
    selected = frame.copy()
    for column, value in where.items():
        selected = selected.loc[selected[column].astype(str).eq(str(value))]
    require(len(selected) == 1, "METRIC_ROW_NOT_UNIQUE", where)
    return {column: finite_or_none(value) for column, value in selected.iloc[0].to_dict().items()}


def classify(
    strategy_metrics: pd.DataFrame, signal_metrics: pd.DataFrame, vintage_pnl: pd.DataFrame
) -> dict[str, Any]:
    raw = record_from_frame(strategy_metrics, strategy="C0_RAW_A2", scope_type="aggregate", scope_id="PRE2026")
    blend = record_from_frame(strategy_metrics, strategy="C2_A2_PLUS_INSTITUTIONAL_CHANGE", scope_type="aggregate", scope_id="PRE2026")
    folds = strategy_metrics.loc[
        strategy_metrics.strategy.eq("C2_A2_PLUS_INSTITUTIONAL_CHANGE")
        & strategy_metrics.scope_type.eq("outer_fold")
    ]
    positive_folds = int(folds.delta_sharpe_vs_raw.gt(0).sum())
    positive_fold_gate = positive_folds >= math.ceil(0.60 * len(folds))
    positive = vintage_pnl.loc[vintage_pnl.incremental_return.gt(0), "incremental_return"]
    denominator = float(positive.sum())
    shares = positive.sort_values(ascending=False) / denominator if denominator > 0 else pd.Series(dtype=float)
    top1 = float(shares.iloc[:1].sum()) if len(shares) else math.nan
    top3 = float(shares.iloc[:3].sum()) if len(shares) else math.nan
    composite = record_from_frame(
        signal_metrics, signal="INSTITUTIONAL_CHANGE_COMPOSITE", scope_type="aggregate", scope_id="PRE2026"
    )
    fixed_blend = record_from_frame(
        signal_metrics, signal="FIXED_80_20_BLEND", scope_type="aggregate", scope_id="PRE2026"
    )
    raw_signal = record_from_frame(signal_metrics, signal="RAW_A2", scope_type="aggregate", scope_id="PRE2026")
    nonredundant = abs(float(composite["correlation_with_raw_a2"])) < REDUNDANCY_LIMIT
    predictive = float(composite["mean_spearman_ic"]) > 0 and float(composite["top_minus_bottom_return"]) > 0
    gross_improved = float(blend["gross_cumulative_return"]) > float(raw["gross_cumulative_return"])
    net_improved = float(blend["cumulative_return"]) > float(raw["cumulative_return"])
    promising = (
        float(blend["sharpe"]) > float(raw["sharpe"])
        and positive_fold_gate
        and math.isfinite(top1) and top1 < VINTAGE_DOMINANCE_LIMIT
        and gross_improved and net_improved and nonredundant
    )
    classification = (
        "PROMISING_INCREMENTAL_ALPHA" if promising
        else "INFORMATION_PRESENT_ECONOMICALLY_WEAK" if predictive
        else "NO_STABLE_INCREMENT"
    )
    return {
        "classification": classification,
        "positive_outer_folds": positive_folds,
        "valid_outer_folds": int(len(folds)),
        "positive_fold_gate": positive_fold_gate,
        "top1_vintage_share": top1,
        "top3_vintage_share": top3,
        "positive_vintage_count": int((vintage_pnl.incremental_return > 0).sum()),
        "valid_vintage_count": int(len(vintage_pnl)),
        "nonredundant": nonredundant,
        "predictive_evidence": predictive,
        "fixed_blend_ic_incremental": float(fixed_blend["mean_spearman_ic"] - raw_signal["mean_spearman_ic"]),
        "gross_improved": gross_improved,
        "net_improved": net_improved,
        "promising": promising,
    }


def format_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "NA"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.10f}"
    return str(value)


def markdown_table(frame: pd.DataFrame) -> str:
    """Render a compact deterministic Markdown table without optional packages."""
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        rendered = []
        for value in row:
            if isinstance(value, (float, np.floating)):
                rendered.append("NA" if not math.isfinite(float(value)) else f"{float(value):.6f}")
            else:
                rendered.append(str(value).replace("|", "\\|"))
        lines.append("| " + " | ".join(rendered) + " |")
    return "\n".join(lines)


def build_report(
    overlap: str,
    reconciliation: dict[str, Any],
    strategy_metrics: pd.DataFrame,
    signal_metrics: pd.DataFrame,
    vintage_pnl: pd.DataFrame,
    decision: dict[str, Any],
    bootstrap: dict[str, float],
    panel: pd.DataFrame,
    hashes: dict[str, str],
) -> str:
    aggregate = strategy_metrics.loc[strategy_metrics.scope_type.eq("aggregate")]
    headline_columns = [
        "strategy", "cumulative_return", "cagr", "annualized_volatility", "sharpe",
        "sortino", "max_drawdown", "calmar", "turnover", "transaction_cost",
    ]
    composite = record_from_frame(signal_metrics, signal="INSTITUTIONAL_CHANGE_COMPOSITE", scope_type="aggregate", scope_id="PRE2026")
    fold_table = strategy_metrics.loc[strategy_metrics.scope_type.eq("outer_fold"), [
        "strategy", "scope_id", "cumulative_return", "sharpe", "delta_sharpe_vs_raw", "turnover", "transaction_cost"
    ]]
    year_table = strategy_metrics.loc[strategy_metrics.scope_type.eq("calendar_year"), [
        "strategy", "scope_id", "cumulative_return", "delta_cumulative_return_vs_raw"
    ]]
    vintage_table = strategy_metrics.loc[
        strategy_metrics.strategy.eq("C2_A2_PLUS_INSTITUTIONAL_CHANGE")
        & strategy_metrics.scope_type.eq("13f_vintage"),
        ["scope_id", "cumulative_return", "delta_cumulative_return_vs_raw"],
    ].merge(vintage_pnl, left_on="scope_id", right_on="vintage", how="left").drop(columns="vintage")
    component_table = signal_metrics.loc[
        signal_metrics.scope_type.eq("aggregate")
        & signal_metrics.signal.isin([*COMPONENT_LABELS.values(), "INSTITUTIONAL_CHANGE_COMPOSITE", "RAW_A2", "FIXED_80_20_BLEND"]),
        ["signal", "coverage", "mean_spearman_ic", "top_minus_bottom_return", "correlation_with_raw_a2", "bucket_monotonicity_spearman", "incremental_ic_vs_raw"],
    ]
    hash_rows = "\n".join(f"- `{Path(path).name}`: `{digest[:16]}`" for path, digest in sorted(hashes.items()))
    return f"""# {TASK_ID}

## Scope and provenance

- Research status: `{decision['classification']}`
- Raw A2 13F-change overlap: `{overlap}`. Raw A2's universe is 13F-derived, but its 32 scoring inputs contain no institutional level/change feature.
- 13F source: `{SELECTED_PATH}`; stable manager count: {MANAGER_COUNT}; semantics: eligible Top100 only.
- PIT rule: latest actual filing completion plus 5 US equity trading sessions; the active-quarter ledger is enforced row by row.
- Outcome boundary: maximum used target end `{pd.to_datetime(panel.loc[panel.target.notna(), 'target_end_date']).max().date()}`; no 2026 outcome or price was read.
- Economic contract: same daily decisions, PIT universe, Top20 equal weight, next-open execution, cash, corporate actions, 10 bps cost, turnover, and liquidation logic. Ranking is the only change.

## Fixed feature family

`HOLDER_BREADTH_CHANGE`, `TOP100_ENTRY_EXIT_BALANCE`, `CONSENSUS_TOP100_POSITION_WEIGHT_CHANGE`, and fixed two-quarter `ACCUMULATION_PERSISTENCE` are available. Position weights are normalized inside each manager's eligible Top100 because a full-portfolio denominator is not present. All managers enter the consensus equally. The composite is the equal-weight mean of valid daily cross-sectional percentile ranks.

## Control reconciliation

- Status: `{reconciliation['status']}`
- Scope: `{reconciliation['scope_start']}` through `{reconciliation['scope_end']}`; last signal `{reconciliation['last_signal_date']}`
- Daily rows: {reconciliation['row_count']}; maximum numeric replay error: `{max(reconciliation['max_abs_errors'].values())}`
- The applicable scope is the three annual OOF test blocks and exactly matches the current 24-manager authoritative Raw A2 replay.

## Economic results

{markdown_table(aggregate[headline_columns])}

### Outer folds

{markdown_table(fold_table)}

### Calendar years

{markdown_table(year_table)}

## Signal and incremental-information evidence

{markdown_table(component_table)}

- Composite coverage: `{composite['coverage']:.6f}`; average daily Spearman correlation with Raw A2: `{composite['correlation_with_raw_a2']:.6f}`.
- Existing paired moving-block utility: mean daily C2-C0 `{bootstrap['mean']:.8f}`, 95% CI `[{bootstrap['ci_low']:.8f}, {bootstrap['ci_high']:.8f}]`, block {int(bootstrap['block_length'])}, repeats {int(bootstrap['repeats'])}.

## 13F-vintage stability

{markdown_table(vintage_table)}

- Top-1 positive-vintage share of incremental arithmetic P&L: `{format_value(decision['top1_vintage_share'])}`.
- Top-3 positive-vintage share: `{format_value(decision['top3_vintage_share'])}`.
- Positive vintages: `{decision['positive_vintage_count']}/{decision['valid_vintage_count']}`.

## Decision

Classification: **{decision['classification']}**. Positive Delta-Sharpe outer folds: `{decision['positive_outer_folds']}/{decision['valid_outer_folds']}`. Non-redundancy gate: `{decision['nonredundant']}`. Gross/net improvement gates: `{decision['gross_improved']}/{decision['net_improved']}`. The fixed one-vintage dominance limit was 50%; no vintage was removed or retested.

This is research evidence only. No freeze, forward arm, canonical promotion, manager weighting, model training, or parameter search was performed.

## Trial ledger and code

- Economic candidates: exactly 3 (`C0`, `C1`, `C2`); blend fixed at 80/20.
- Code: `{Path(__file__).resolve()}`
- Targeted test: `{REPO / 'scripts/v22/test_a2_13f_institutional_change_alpha_r1.py'}`
- Test status: pending external targeted pytest at report generation; final terminal handoff records the executed result.
- Task-local artifacts: `final_report.md`, `signal_metrics.csv`, `strategy_metrics.csv`, `trial_ledger.json` only.

Relevant input hashes (SHA-256 prefix):

{hash_rows}
"""


def run() -> dict[str, Any]:
    inputs, _, overlap, before_hashes = load_inputs()
    manager_ids = tuple(sorted(inputs["manifest"].normalized_manager_id.astype(str).unique()))
    quarters = tuple(inputs["needed_quarters"].quarter.astype(str))
    changes = build_quarter_change_features(inputs["selected"], quarters, manager_ids)
    panel = attach_change_panel(inputs, changes)
    rebuild, r0f, prices, external_calls = load_authoritative_portfolio_runtime(inputs)
    reconciliation, simulations = reconcile_and_simulate(panel, rebuild, r0f, prices)
    strategy_metrics, vintage_pnl = strategy_metric_table(simulations, panel)
    signal_metrics = signal_metric_table(panel)
    bootstrap = bootstrap_diagnostic(simulations)
    decision = classify(strategy_metrics, signal_metrics, vintage_pnl)
    after_hashes = {path: sha256_file(Path(path)) for path in before_hashes}
    require(before_hashes == after_hashes, "CANONICAL_INPUT_MODIFIED")
    require(external_calls == 0, "EXTERNAL_CALL_COUNT_NONZERO")

    OUT.mkdir(parents=True, exist_ok=True)
    permitted = {"final_report.md", "signal_metrics.csv", "strategy_metrics.csv", "trial_ledger.json"}
    unexpected = [path for path in OUT.iterdir() if path.name not in permitted]
    require(not unexpected, "OUTPUT_ANTI_BLOAT_FAILURE", unexpected)
    atomic_csv(OUT / "signal_metrics.csv", signal_metrics)
    atomic_csv(OUT / "strategy_metrics.csv", strategy_metrics)
    trial_ledger = {
        "task_id": TASK_ID,
        "research_classification": decision["classification"],
        "economic_candidate_count": 3,
        "economic_candidates": list(STRATEGY_RANKS),
        "components": [
            {"name": label, "status": "AVAILABLE", "source_semantics": "ELIGIBLE_TOP100_NOT_FULL_PORTFOLIO"}
            for label in COMPONENT_LABELS.values()
        ],
        "composite": "EQUAL_WEIGHT_MEAN_OF_VALID_COMPONENT_DAILY_PERCENTILE_RANKS",
        "blend": {"raw_a2": BLEND_A2_WEIGHT, "institutional_change": BLEND_INSTITUTIONAL_WEIGHT},
        "blend_weight_search": False,
        "topn_search": False,
        "manager_weight_search": False,
        "model_training": False,
        "manager_weighting": "EQUAL_MANAGER",
        "entry_exit_semantics": "TOP100_ENTRY_EXIT_BALANCE_NOT_TRUE_BUY_SELL",
        "position_weight_semantics": "ELIGIBLE_TOP100_NORMALIZED_WITHIN_MANAGER_QUARTER",
        "pit_rule": "LATEST_ACTUAL_FILING_COMPLETION_PLUS_5_US_EQUITY_TRADING_SESSIONS",
        "outcome_max": str(pd.to_datetime(panel.loc[panel.target.notna(), "target_end_date"]).max().date()),
        "post_2025_outcome_used": False,
        "control_reconciliation": reconciliation,
        "robustness": bootstrap,
        "decision": decision,
        "attempt_history": [
            {"kind": "DEBUG_RETRY", "reason": "PANDAS_DUPLICATE_DIAGNOSTIC_COLUMN_COMPATIBILITY", "economic_trial_count": 0},
            {"kind": "DEBUG_RETRY", "reason": "OPTIONAL_TABULATE_NOT_INSTALLED_REPLACED_WITH_LOCAL_MARKDOWN_FORMATTER", "economic_trial_count": 0},
            {"kind": "ECONOMIC_RUN", "status": "COMPLETED", "economic_trial_count": 3},
        ],
        "input_hashes_sha256": before_hashes,
        "network_called": False,
        "moomoo_called": False,
        "new_freeze_created": False,
        "new_forward_created": False,
        "canonical_modified": False,
    }
    atomic_json(OUT / "trial_ledger.json", trial_ledger)
    report = build_report(
        overlap, reconciliation, strategy_metrics, signal_metrics, vintage_pnl,
        decision, bootstrap, panel, before_hashes,
    )
    atomic_text(OUT / "final_report.md", report)
    require({path.name for path in OUT.iterdir()} == permitted, "OUTPUT_ARTIFACT_SET_FAILURE")
    return {
        "overlap": overlap,
        "reconciliation": reconciliation,
        "strategy_metrics": strategy_metrics,
        "signal_metrics": signal_metrics,
        "vintage_pnl": vintage_pnl,
        "decision": decision,
        "bootstrap": bootstrap,
        "panel": panel,
        "result_dir": str(OUT),
    }


def terminal_summary(result: dict[str, Any]) -> str:
    strategy = result["strategy_metrics"]
    signal = result["signal_metrics"]
    raw = record_from_frame(strategy, strategy="C0_RAW_A2", scope_type="aggregate", scope_id="PRE2026")
    standalone = record_from_frame(strategy, strategy="C1_INSTITUTIONAL_CHANGE_STANDALONE", scope_type="aggregate", scope_id="PRE2026")
    blend = record_from_frame(strategy, strategy="C2_A2_PLUS_INSTITUTIONAL_CHANGE", scope_type="aggregate", scope_id="PRE2026")
    composite = record_from_frame(signal, signal="INSTITUTIONAL_CHANGE_COMPOSITE", scope_type="aggregate", scope_id="PRE2026")
    decision = result["decision"]
    lines = [
        "=" * 60, TASK_ID + "_FINAL", "=" * 60,
        "OVERALL_STATUS=PASS_RESEARCH_COMPLETE",
        "DATE_MAX_OUTCOME_USED=2025-12-31", "POST_2025_OUTCOME_USED=false",
        f"EXISTING_A2_13F_CHANGE_FEATURE_OVERLAP={result['overlap']}",
        f"SOURCE_13F_PACKAGE={SELECTED_PATH}", f"MANAGER_COUNT={MANAGER_COUNT}",
        "PIT_EFFECTIVE_DATE_RULE=LATEST_ACTUAL_FILING_COMPLETION_PLUS_5_US_EQUITY_TRADING_SESSIONS",
        "HOLDER_BREADTH_CHANGE_STATUS=AVAILABLE", "ENTRY_EXIT_BALANCE_STATUS=AVAILABLE_AS_TOP100_ENTRY_EXIT_BALANCE",
        "CONSENSUS_WEIGHT_CHANGE_STATUS=AVAILABLE_AS_TOP100_NORMALIZED", "ACCUMULATION_PERSISTENCE_STATUS=AVAILABLE_FIXED_TWO_QUARTER",
        f"INSTITUTIONAL_COMPONENT_COUNT={len(COMPONENT_COLUMNS)}",
        f"INSTITUTIONAL_COMPOSITE_COVERAGE={format_value(composite['coverage'])}",
        f"CORRELATION_WITH_RAW_A2={format_value(composite['correlation_with_raw_a2'])}",
        f"OUTER_FOLD_COUNT={decision['valid_outer_folds']}",
        "RAW_A2=" + json.dumps(raw, default=str),
        "INSTITUTIONAL_CHANGE_STANDALONE=" + json.dumps(standalone, default=str),
        "A2_PLUS_INSTITUTIONAL_CHANGE_80_20=" + json.dumps(blend, default=str),
        f"COMPOSITE_SPEARMAN_IC={format_value(composite['mean_spearman_ic'])}",
        f"TOP_MINUS_BOTTOM_RETURN={format_value(composite['top_minus_bottom_return'])}",
        f"TOP1_VINTAGE_SHARE_OF_INCREMENTAL_PNL={format_value(decision['top1_vintage_share'])}",
        f"TOP3_VINTAGE_SHARE_OF_INCREMENTAL_PNL={format_value(decision['top3_vintage_share'])}",
        f"RESEARCH_CLASSIFICATION={decision['classification']}",
        "ECONOMIC_CANDIDATE_COUNT=3", "BLEND_WEIGHT_SEARCH=false", "TOPN_SEARCH=false",
        "MANAGER_WEIGHT_SEARCH=false", "MODEL_TRAINING=false", "MOOMOO_CALLED=false", "NETWORK_CALLED=false",
        f"RESULT_DIR={OUT}",
    ]
    return "\n".join(lines)


def main() -> int:
    result = run()
    print(terminal_summary(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
