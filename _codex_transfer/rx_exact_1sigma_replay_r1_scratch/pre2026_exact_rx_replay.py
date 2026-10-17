"""Scratch-only exact pre-2026 RX_MARGIN_R1 retrospective replay.

This is deliberately an orchestration adapter over the hash-pinned R5 producer
and R4 portfolio simulator.  It does not implement a second scorer, simulator,
calendar, turnover definition, or cost model.  Every loader used here is the
R5 pre-2026 loader, whose predicate and runtime guards reject 2026 rows.

Default output is below this script's scratch directory.  No live Registry,
prospective authority store, canonical data, or final result root is written.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
os.environ.setdefault("JOBLIB_MULTIPROCESSING", "0")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import pandas as pd
import pyarrow.dataset as pads


SCRIPT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_ROOT / "output"
R5_ROOT = Path(r"D:\us-tech-quant-worktrees\harness-task-20260827-041928-8076")
R5_SOURCE = R5_ROOT / "scripts/v22/a2_free_factor_discovery.py"
R4_SOURCE = R5_ROOT / "scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py"
RX_CONTRACT = Path(
    r"D:\us-tech-quant-results\RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1\frozen_contract.json"
)
R5_MANIFEST = Path(r"D:\us-tech-quant-results\A2_FREE_FACTOR_DISCOVERY_STAGE_A_R5\run_manifest.json")
R5_COMPARISON = Path(r"D:\us-tech-quant-results\A2_FREE_FACTOR_DISCOVERY_STAGE_A_R5\finalist_comparison.csv")
RECOVERED_PRICE = Path(
    r"D:\us-tech-quant-results\RX_PREACTIVATION_AUTHORITY_REPAIR_R1\price_lineage_recovery\adjusted_prices_pre2026.parquet"
)
HAC_SOURCE = Path(r"D:\us-tech-quant\raw_a2_strict_counterfactual_stock_selection_identification_r1.py")
HAC_CONTRACT = Path(
    r"D:\us-tech-quant-results\RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1\counterfactual_identification_contract.json"
)

EXPECTED = {
    R5_SOURCE: "1cdff21546e4ad5bd7cfd732b221f784222977d476a640b3b8765c911139b880",
    R4_SOURCE: "d643102915e138b24ca4dbfe9cea4fb9e6b076b96fcdd81bae81f66d25ee219b",
    RX_CONTRACT: "e9735b812549bd147a4fa311027f5d5cc0cedf06bbe29352c4cd564fa449832e",
    R5_MANIFEST: "809c3b74d112245c76efc8ee9ec625425c200169f7f80db4f6da038fc2952f7c",
    R5_COMPARISON: "4fef4fa6c76928c4f91a88e2c58eef6d7a5f73840c06cf7f73b1043f32476980",
    RECOVERED_PRICE: "c7af8cdee219a8c1ec9d043cccbd6bb2d88582ca9a4e7be5fc4c10642e0951ae",
    HAC_SOURCE: "80d68a09d497741b660360b31e201982bcd2716e8b14c8a6ee321177967b109c",
    HAC_CONTRACT: "8b396170c58afe2a756f7d674c0166309bca9b8dbc6fbf8482d15be30a474533",
}
EXPECTED_SOURCE_FINGERPRINT = "569fc218d8b2751abbfd016d12523546a3babb06f7f84a6bce35e80cc0023a15"
EXPECTED_PRICE_SHA256 = "c7af8cdee219a8c1ec9d043cccbd6bb2d88582ca9a4e7be5fc4c10642e0951ae"
EXPECTED_MEMBERSHIP_SHA256 = "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17"
EXPECTED_OUTCOME_BLIND_SELECTION_SHA256 = "0737411a9b00ad4bfcace18fbce07d1042574c72e86661079b4d8e31a00e29b2"
EXPECTED_COMPLETE_SELECTION_SHA256 = "b89f6d8e8977089357338f390f451ec193f935adf40659545586b751c26213ea"
THRESHOLD_SIGMA = 1.0
DDOF = 0
COST_BPS = 10
BOUNDARY = pd.Timestamp("2026-01-01")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILURE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_authority(r5: Any) -> dict[str, Any]:
    actual = {str(path): sha256_file(path) for path in EXPECTED}
    mismatches = {
        str(path): {"expected": expected, "actual": actual[str(path)]}
        for path, expected in EXPECTED.items()
        if actual[str(path)] != expected
    }
    if mismatches:
        raise RuntimeError("PINNED_AUTHORITY_SHA256_MISMATCH:" + json.dumps(mismatches, sort_keys=True))
    if sha256_file(r5.RAW_TOP40) != EXPECTED_MEMBERSHIP_SHA256:
        raise RuntimeError("MEMBERSHIP_SHA256_MISMATCH")
    if sha256_file(RECOVERED_PRICE) != EXPECTED_PRICE_SHA256:
        raise RuntimeError("PRICE_LINEAGE_SHA256_MISMATCH")
    contract = json.loads(RX_CONTRACT.read_text(encoding="utf-8"))
    if contract["source_r5_fingerprint"] != EXPECTED_SOURCE_FINGERPRINT:
        raise RuntimeError("RX_CONTRACT_SOURCE_FINGERPRINT_MISMATCH")
    rule = contract["exact_replacement_rule"]
    if (
        rule["threshold_sigma"] != THRESHOLD_SIGMA
        or rule["comparison_operator"] != ">="
        or rule["cross_sectional_score_std"]["ddof"] != DDOF
    ):
        raise RuntimeError("RX_CONTRACT_RULE_MISMATCH")
    definitions = {item.candidate_id: item for item in r5.R4_CANDIDATES}
    specification = definitions["R5_RANGE_EXHAUSTION"]
    source_fingerprint = r5.semantic_fingerprint(r5.r4_semantic_spec(specification))
    if source_fingerprint != EXPECTED_SOURCE_FINGERPRINT:
        raise RuntimeError("R5_RANGE_EXHAUSTION_SEMANTIC_FINGERPRINT_MISMATCH")
    hac_contract = json.loads(HAC_CONTRACT.read_text(encoding="utf-8"))
    inference = hac_contract["inference"]
    if (
        hac_contract["runner_sha256"] != EXPECTED[HAC_SOURCE]
        or inference["method"] != "BARTLETT_NEWEY_WEST"
        or inference["lags"] != 5
        or inference["finite_sample_correction"] != "N_OVER_N_MINUS_K"
    ):
        raise RuntimeError("HAC_AUTHORITY_CONTRACT_MISMATCH")
    return {
        "source_hashes": actual,
        "membership_sha256": EXPECTED_MEMBERSHIP_SHA256,
        "price_lineage_sha256": EXPECTED_PRICE_SHA256,
        "price_lineage_recovered_authority_path": str(RECOVERED_PRICE),
        "source_r5_fingerprint": source_fingerprint,
        "threshold_sigma": THRESHOLD_SIGMA,
        "ddof": DDOF,
    }


def materialize_exact_r5_inputs(
    r5: Any,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Reuse only R5 components needed by the frozen deterministic candidate."""
    panel, panel_audit = r5.prepare_panel()
    taxonomy = pads.dataset(r5.TAXONOMY, format="parquet").to_table(
        columns=[
            "signal_date", "ticker", "cik", "ff12", "ff48",
            "information_cutoff_utc", "sic_accepted_timestamp_utc",
        ],
        filter=pads.field("signal_date") < r5.BOUNDARY_FILTER,
    ).to_pandas()
    panel, peer_audit = r5.attach_peer_features(panel, taxonomy)

    # R5's fixed mapping uses same-date residual-cluster membership.  Reuse its
    # exact price, benchmark, lagged-beta, graph, and OHLCV path transforms.
    wanted = set(panel.ticker.astype(str))
    prices, price_audit = r5.load_raw_rehab_prices(wanted)
    benchmarks, benchmark_audit = r5.load_raw_rehab_benchmarks()
    panel, idio_audit = r5.attach_idiosyncratic_features(panel, prices, benchmarks)
    panel, graph_audit = r5.attach_residual_graph_features(panel, prices)
    panel, price_path_audit = r5.attach_price_path_features(panel, prices)

    # r4_candidate_scores eagerly constructs every R5 score, including models
    # whose now-retired nonprice caches are irrelevant to RX.  Invoke the
    # pinned R5 same-date z-score helper on exactly the three frozen formula
    # fields instead; this is the literal R5_RANGE_EXHAUSTION expression.
    z_range = r5._safe_zscore(panel, "range_shock_5_20")
    z_close = r5._safe_zscore(panel, "close_location_5")
    z_volume = r5._safe_zscore(panel, "volume_shock_5_20")
    range_score = (
        -z_range * z_close * (1.0 + 0.25 * z_volume)
    ).replace([np.inf, -np.inf], np.nan).fillna(-10.0)
    if range_score.isna().any() or not np.isfinite(range_score.to_numpy(float)).all():
        raise RuntimeError("NONFINITE_FROZEN_RANGE_SCORE")
    panel = panel.copy()
    panel["candidate_score"] = range_score.to_numpy(float)
    specification = next(item for item in r5.R4_CANDIDATES if item.candidate_id == "R5_RANGE_EXHAUSTION")
    r5_selection = r5.r4_make_selection(panel, range_score, specification)
    raw_selection = r5.raw_selection(panel)

    for frame_name, frame in {
        "panel": panel,
        "r5_selection": r5_selection,
        "raw_selection": raw_selection,
        "prices": prices,
    }.items():
        date_columns = [column for column in ("signal_date", "trade_date", "target_end_date", "short_label_end_date_5") if column in frame]
        for column in date_columns:
            values = pd.to_datetime(frame[column]).dropna()
            if len(values) and values.ge(BOUNDARY).any():
                raise RuntimeError(f"POST2025_ROW_MATERIALIZED:{frame_name}:{column}")
    dates = sorted(r5_selection.signal_date.unique())
    if dates != sorted(raw_selection.signal_date.unique()):
        raise RuntimeError("R5_RAW_SIGNAL_DATE_SUPPORT_MISMATCH")
    if r5_selection.groupby("signal_date").size().ne(r5.TOP_N).any():
        raise RuntimeError("R5_SELECTION_CARDINALITY_MISMATCH")
    if raw_selection.groupby("signal_date").size().ne(r5.TOP_N).any():
        raise RuntimeError("RAW_SELECTION_CARDINALITY_MISMATCH")
    audits = {
        "panel": panel_audit,
        "peer": peer_audit,
        "prices": price_audit,
        "benchmarks": benchmark_audit,
        "idiosyncratic": idio_audit,
        "residual_graph": graph_audit,
        "price_path": price_path_audit,
        "model_fit_count": 0,
        "range_score_materialization": (
            "PINNED_R5_SAFE_ZSCORE_AND_LITERAL_R5_RANGE_EXHAUSTION_FORMULA_ONLY;"
            "R5_ALL_CANDIDATE_EAGER_CONSTRUCTOR_INTENTIONALLY_NOT_CALLED"
        ),
        "post2025_row_count": 0,
    }
    return panel, raw_selection, r5_selection, prices, audits


def build_exact_rx_selection(
    panel: pd.DataFrame,
    raw_selection: pd.DataFrame,
    r5_selection: pd.DataFrame,
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the frozen positional 1.0-sigma replacement veto exactly."""
    selection_columns = list(r5_selection.columns)
    rows: list[pd.DataFrame] = []
    ledger: list[dict[str, Any]] = []
    panel_by_date = {pd.Timestamp(date): day for date, day in panel.groupby("signal_date", sort=True)}
    raw_by_date = {pd.Timestamp(date): day for date, day in raw_selection.groupby("signal_date", sort=True)}
    r5_by_date = {pd.Timestamp(date): day for date, day in r5_selection.groupby("signal_date", sort=True)}
    qqq_calendar = pd.DatetimeIndex(
        sorted(pd.to_datetime(prices.loc[prices.ticker.eq("QQQ"), "trade_date"]).unique())
    )
    next_session = {
        pd.Timestamp(signal): pd.Timestamp(execution)
        for signal, execution in zip(qqq_calendar[:-1], qqq_calendar[1:], strict=True)
    }

    for signal_date in sorted(raw_by_date):
        if signal_date not in next_session:
            raise RuntimeError(f"MISSING_NEXT_QQQ_SESSION:{signal_date.date()}")
        execution_date = next_session[signal_date]
        universe = panel_by_date[signal_date].copy()
        raw_day = raw_by_date[signal_date].copy()
        r5_day = r5_by_date[signal_date].copy()
        if len(universe) != 40 or universe.ticker.nunique() != 40:
            raise RuntimeError(f"ELIGIBLE_SCORE_UNIVERSE_NOT_40:{signal_date.date()}")
        if universe.candidate_score.isna().any() or not np.isfinite(universe.candidate_score.to_numpy(float)).all():
            raise RuntimeError(f"NONFINITE_ELIGIBLE_SCORE_UNIVERSE:{signal_date.date()}")
        score_std = float(universe.candidate_score.std(ddof=DDOF))
        if not np.isfinite(score_std):
            raise RuntimeError(f"INVALID_SCORE_STD:{signal_date.date()}")

        raw_names = set(raw_day.ticker.astype(str))
        r5_names = set(r5_day.ticker.astype(str))
        entrant_names = r5_names - raw_names
        incumbent_names = raw_names - r5_names
        if len(entrant_names) != len(incumbent_names):
            raise RuntimeError(f"PAIR_CARDINALITY_MISMATCH:{signal_date.date()}")

        score_lookup = universe.set_index("ticker")["candidate_score"]
        entrants = r5_day.loc[r5_day.ticker.isin(entrant_names)].copy()
        incumbents = raw_day.loc[raw_day.ticker.isin(incumbent_names)].copy()
        entrants["candidate_score"] = entrants.ticker.map(score_lookup)
        incumbents["candidate_score"] = incumbents.ticker.map(score_lookup)
        entrants = entrants.sort_values(
            ["candidate_score", "raw_score", "ticker"],
            ascending=[False, False, True], kind="mergesort",
        )
        incumbents = incumbents.sort_values(
            ["candidate_score", "raw_rank", "ticker"],
            ascending=[True, False, False], kind="mergesort",
        )

        accepted_entrants: set[str] = set()
        accepted_incumbents: set[str] = set()
        day_ledger: list[dict[str, Any]] = []
        for pair_index, (entrant, incumbent) in enumerate(
            zip(entrants.itertuples(index=False), incumbents.itertuples(index=False), strict=True), start=1
        ):
            margin = float(entrant.candidate_score - incumbent.candidate_score)
            required = THRESHOLD_SIGMA * score_std
            accepted = bool(margin >= required)
            if accepted:
                accepted_entrants.add(str(entrant.ticker))
                accepted_incumbents.add(str(incumbent.ticker))
            day_ledger.append({
                "signal_date": signal_date,
                "execution_date": execution_date,
                "pair_index": pair_index,
                "incumbent_ticker": str(incumbent.ticker),
                "entrant_ticker": str(entrant.ticker),
                "incumbent_score": float(incumbent.candidate_score),
                "entrant_score": float(entrant.candidate_score),
                "score_margin": margin,
                "cross_sectional_std": score_std,
                "threshold_sigma": THRESHOLD_SIGMA,
                "required_margin": required,
                "replacement_decision": "REPLACE" if accepted else "RETAIN",
                "final_incumbent_member": not accepted,
                "final_entrant_member": accepted,
            })

        final_names = (raw_names - accepted_incumbents) | accepted_entrants
        if len(final_names) != 20:
            raise RuntimeError(f"RX_FINAL_CARDINALITY_MISMATCH:{signal_date.date()}")
        final_membership = "|".join(sorted(final_names))
        for record in day_ledger:
            record["final_selected_membership"] = final_membership
        ledger.extend(day_ledger)
        # Preserve the exact freeze-time F0weak ranking representation.
        final = universe.loc[universe.ticker.isin(final_names)].copy()
        final = final.sort_values(
            ["candidate_score", "raw_score", "ticker"],
            ascending=[False, False, True], kind="mergesort",
        )
        final["candidate_rank"] = np.arange(1, 21)
        final["candidate_id"] = "RX_MARGIN_R1"
        for column in selection_columns:
            if column not in final:
                raise RuntimeError(f"RX_SELECTION_COLUMN_MISSING:{column}")
        rows.append(final[selection_columns])

    selection = pd.concat(rows, ignore_index=True).sort_values(
        ["signal_date", "candidate_rank"], kind="mergesort",
    ).reset_index(drop=True)
    decisions = pd.DataFrame(ledger).sort_values(
        ["signal_date", "pair_index"], kind="mergesort",
    ).reset_index(drop=True)
    if selection.groupby("signal_date").size().ne(20).any():
        raise RuntimeError("RX_SELECTION_CARDINALITY_FAILURE")
    return selection, decisions


def candidate_selection_hashes(r5: Any, selection: pd.DataFrame) -> dict[str, str]:
    """Reproduce the exact freeze-time full and four-field outcome-blind hashes."""
    blind_columns = ["signal_date", "ticker", "candidate_rank", "candidate_score"]
    complete = r5.dataframe_sha256(selection)
    blind = r5.dataframe_sha256(selection[blind_columns])
    membership = r5.dataframe_sha256(selection[["signal_date", "ticker", "candidate_rank"]])
    return {
        "natural_outcome_blind_sha256": blind,
        "natural_complete_sha256": complete,
        "membership_sha256": membership,
        "frozen_expected_outcome_blind_sha256": EXPECTED_OUTCOME_BLIND_SELECTION_SHA256,
        "frozen_expected_complete_sha256": EXPECTED_COMPLETE_SELECTION_SHA256,
        "frozen_selection_identity_status": (
            "PASS" if blind == EXPECTED_OUTCOME_BLIND_SELECTION_SHA256 and complete == EXPECTED_COMPLETE_SELECTION_SHA256
            else "FAIL"
        ),
    }


def holding_diagnostics(
    raw_selection: pd.DataFrame, rx_selection: pd.DataFrame,
) -> dict[str, Any]:
    raw_sets = raw_selection.groupby("signal_date").ticker.apply(lambda values: frozenset(map(str, values)))
    rx_sets = rx_selection.groupby("signal_date").ticker.apply(lambda values: frozenset(map(str, values)))
    if not raw_sets.index.equals(rx_sets.index):
        raise RuntimeError("HOLDING_DIAGNOSTIC_DATE_MISMATCH")
    overlaps = np.asarray([len(raw_sets.loc[date] & rx_sets.loc[date]) / 20.0 for date in raw_sets.index])
    changed = np.asarray([len(raw_sets.loc[date] ^ rx_sets.loc[date]) / 2.0 for date in raw_sets.index])

    def membership_turnover(sets: pd.Series) -> float:
        values = list(sets)
        if not values:
            return 0.0
        # Equal-weight one-way turnover implied solely by target membership.
        total = 0.5  # initial deployment from cash to 20 equal-weight names
        for before, after in zip(values[:-1], values[1:], strict=True):
            total += len(before ^ after) / 40.0
        total += 0.5  # terminal liquidation required by the frozen R4 replay
        return float(total)

    raw_membership_turnover = membership_turnover(raw_sets)
    rx_membership_turnover = membership_turnover(rx_sets)
    return {
        "raw_a2_to_rx_daily_holding_overlap": float(overlaps.mean()),
        "mean_number_changed_names_per_rebalance": float(changed.mean()),
        "raw_a2_membership_implied_turnover": raw_membership_turnover,
        "rx_membership_implied_turnover": rx_membership_turnover,
        "membership_turnover_saved": raw_membership_turnover - rx_membership_turnover,
        "membership_turnover_reduction_percent": (
            100.0 * (raw_membership_turnover - rx_membership_turnover) / raw_membership_turnover
            if raw_membership_turnover else None
        ),
    }


def replay(
    r4: Any, r5: Any, hac: Any, raw_selection: pd.DataFrame,
    r5_selection: pd.DataFrame, rx_selection: pd.DataFrame, prices: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    raw_path = r4.simulate_portfolio(
        r5.simulator_signals(raw_selection), prices, "RAW_A2_ALIGNED", "a2_rank", 20, COST_BPS,
    )
    rx_path = r4.simulate_portfolio(
        r5.simulator_signals(rx_selection), prices, "RX_MARGIN_R1", "a2_rank", 20, COST_BPS,
    )
    r5_path = r4.simulate_portfolio(
        r5.simulator_signals(r5_selection), prices, "R5_RANGE_EXHAUSTION", "a2_rank", 20, COST_BPS,
    )
    raw_metrics = r5.metrics(raw_path, r4)
    rx_metrics = r5.metrics(rx_path, r4)
    r5_metrics = r5.metrics(r5_path, r4)
    if not raw_path.execution_date.equals(rx_path.execution_date) or not raw_path.execution_date.equals(r5_path.execution_date):
        raise RuntimeError("PAIRED_EXECUTION_DATE_MISMATCH")
    if (
        raw_path.execution_date.ge(BOUNDARY).any()
        or rx_path.execution_date.ge(BOUNDARY).any()
        or r5_path.execution_date.ge(BOUNDARY).any()
    ):
        raise RuntimeError("POST2025_ECONOMIC_ROW_MATERIALIZED")

    # This durable checkpoint is intentionally a CSV whose numeric authority is
    # serialized at 12 significant digits.  Compare at that exact persisted
    # precision; a sub-serialization binary-float tail is not a replay defect.
    frozen_comparison = pd.read_csv(R5_COMPARISON, dtype=str, keep_default_na=False)
    mapping = {
        "cumulative_return": "cumulative_return_10bps",
        "cagr": "cagr_10bps",
        "annualized_volatility": "annualized_volatility_10bps",
        "sharpe_rf0": "sharpe_rf0_10bps",
        "max_drawdown": "max_drawdown_10bps",
        "calmar": "calmar_10bps",
        "total_turnover": "total_turnover_10bps",
        "annualized_turnover": "annualized_turnover_10bps",
        "total_transaction_cost": "total_transaction_cost_10bps",
    }
    def validate_checkpoint(candidate_id: str, metrics: dict[str, Any]) -> dict[str, Any]:
        checkpoint = frozen_comparison.loc[frozen_comparison.candidate_id.eq(candidate_id)]
        if len(checkpoint) != 1:
            raise RuntimeError(f"FROZEN_COMPARISON_ROW_MISSING:{candidate_id}")
        checkpoint_row = checkpoint.iloc[0]
        validation: dict[str, Any] = {}
        for metric, column in mapping.items():
            actual = float(metrics[metric])
            expected_text = str(checkpoint_row[column]).strip()
            expected = float(expected_text)
            absolute_error = abs(actual - expected)
            validation[metric] = {
                "pass": format(actual, ".12g") == expected_text,
                "actual_full_precision": actual,
                "actual_serialized_12_significant_digits": format(actual, ".12g"),
                "expected_serialized_12_significant_digits": expected_text,
                "absolute_error": absolute_error,
                "relative_error": absolute_error / abs(expected) if expected != 0.0 else absolute_error,
            }
        failures = [metric for metric, detail in validation.items() if not detail["pass"]]
        if failures:
            raise RuntimeError(
                f"FROZEN_CONTROL_IDENTITY_FAILURE:{candidate_id}:"
                + json.dumps({metric: validation[metric] for metric in failures}, sort_keys=True)
            )
        return validation

    raw_validation = validate_checkpoint("RAW_A2", raw_metrics)
    r5_validation = validate_checkpoint("R5_RANGE_EXHAUSTION", r5_metrics)

    paired = raw_path[["execution_date", "net_return"]].merge(
        rx_path[["execution_date", "net_return"]], on="execution_date",
        suffixes=("_raw_a2", "_rx"), validate="one_to_one",
    )
    active = paired.net_return_rx.to_numpy(float) - paired.net_return_raw_a2.to_numpy(float)
    active_mean = float(active.mean())
    tracking_error = float(active.std(ddof=0) * np.sqrt(252.0))
    hac_result = hac.ols_hac(active, lags=5)
    if int(hac_result["n"]) != len(active) or int(hac_result["k"]) != 1:
        raise RuntimeError("HAC_RESULT_SHAPE_MISMATCH")

    period_active = paired.copy()
    period_active["month"] = period_active.execution_date.dt.to_period("M")
    period_active["year"] = period_active.execution_date.dt.year

    def compounded_active_difference(group: pd.DataFrame) -> float:
        return float(
            np.prod(1.0 + group.net_return_rx.to_numpy(float))
            - np.prod(1.0 + group.net_return_raw_a2.to_numpy(float))
        )

    monthly_active = pd.Series({
        str(period): compounded_active_difference(group)
        for period, group in period_active.groupby("month", sort=True)
    })
    yearly_active = pd.Series({
        int(year): compounded_active_difference(group)
        for year, group in period_active.groupby("year", sort=True)
    })

    yearly: dict[str, Any] = {}
    for year in (2023, 2024, 2025):
        raw_year = raw_path.loc[raw_path.execution_date.dt.year.eq(year)].copy()
        rx_year = rx_path.loc[rx_path.execution_date.dt.year.eq(year)].copy()
        if not raw_year.execution_date.equals(rx_year.execution_date):
            raise RuntimeError(f"YEARLY_DATE_MISMATCH:{year}")
        raw_year_metrics = r4.portfolio_metrics(raw_year)
        rx_year_metrics = r4.portfolio_metrics(rx_year)
        yearly[str(year)] = {
            "raw_a2": raw_year_metrics,
            "rx_1sigma": rx_year_metrics,
            "active_return": float(
                np.prod(1.0 + rx_year.net_return.to_numpy(float))
                - np.prod(1.0 + raw_year.net_return.to_numpy(float))
            ),
        }

    summary = {
        "raw_a2_control_identity": "PASS",
        "raw_a2_checkpoint_fields": raw_validation,
        "unrestricted_r5_control_identity": "PASS",
        "unrestricted_r5_checkpoint_fields": r5_validation,
        "raw_a2": raw_metrics,
        "unrestricted_r5": r5_metrics,
        "rx_1sigma": rx_metrics,
        "delta": {
            key: float(rx_metrics[key] - raw_metrics[key])
            for key in (
                "cumulative_return", "cagr", "annualized_volatility", "sharpe_rf0",
                "max_drawdown", "calmar", "total_turnover", "annualized_turnover",
                "total_transaction_cost",
            )
        },
        "mean_active_return": active_mean,
        "active_annualized_return": active_mean * 252.0,
        "tracking_error": tracking_error,
        "active_information_ratio": active_mean * 252.0 / tracking_error if tracking_error > 0 else None,
        "positive_month_fraction": float(monthly_active.gt(0.0).mean()),
        "positive_year_fraction": float(yearly_active.gt(0.0).mean()),
        "positive_period_definition": (
            "COMPOUND_RX_NET_RETURN_WITHIN_PERIOD_MINUS_"
            "COMPOUND_RAW_A2_NET_RETURN_WITHIN_PERIOD_GT_ZERO"
        ),
        "hac_newey_west_lag_5": {
            "authority_contract": str(HAC_CONTRACT),
            "authority_runner_sha256": sha256_file(HAC_SOURCE),
            "method": "BARTLETT_NEWEY_WEST",
            "lags": 5,
            "finite_sample_correction": "N_OVER_N_MINUS_K",
            "mean_active_return": float(hac_result["alpha_daily"]),
            "hac_t_active_return": float(hac_result["alpha_t_hac"]),
            "confidence_interval_daily_95": [float(hac_result["ci_low"]), float(hac_result["ci_high"])],
        },
        "yearly": yearly,
        "holding_diagnostics": holding_diagnostics(raw_selection, rx_selection),
        "mean_session_turnover": {
            "raw_a2": float(raw_path.executed_turnover.mean()),
            "rx_1sigma": float(rx_path.executed_turnover.mean()),
            "delta": float(rx_path.executed_turnover.mean() - raw_path.executed_turnover.mean()),
        },
        "rx_vs_raw_a2_turnover_delta": float(rx_metrics["total_turnover"] - raw_metrics["total_turnover"]),
        "rx_vs_raw_a2_turnover_saved": float(raw_metrics["total_turnover"] - rx_metrics["total_turnover"]),
        "rx_vs_raw_a2_turnover_reduction_percent": (
            100.0 * float(raw_metrics["total_turnover"] - rx_metrics["total_turnover"])
            / float(raw_metrics["total_turnover"])
            if raw_metrics["total_turnover"] else None
        ),
        "turnover_saved_by_vetoes_vs_unrestricted_r5": float(
            r5_metrics["total_turnover"] - rx_metrics["total_turnover"]
        ),
        "turnover_reduction_percent_vs_unrestricted_r5": (
            100.0 * float(r5_metrics["total_turnover"] - rx_metrics["total_turnover"])
            / float(r5_metrics["total_turnover"])
            if r5_metrics["total_turnover"] else None
        ),
        "trade_count": "NOT_AVAILABLE_EXISTING_FROZEN_R4_AUTHORITY",
        "flip_count": "NOT_AVAILABLE_EXISTING_FROZEN_R4_AUTHORITY",
        "flip_rate": "NOT_AVAILABLE_EXISTING_FROZEN_R4_AUTHORITY",
        "average_holding_period": "NOT_AVAILABLE_EXISTING_FROZEN_R4_AUTHORITY",
        "session_count": len(paired),
        "execution_start": str(paired.execution_date.min().date()),
        "execution_end": str(paired.execution_date.max().date()),
    }
    return raw_path, r5_path, rx_path, summary


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    return value


def write_scratch_outputs(output: Path, frames: dict[str, pd.DataFrame], summary: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    expected_names = {*(f"{name}.parquet" for name in frames), "summary.json"}
    extras = {path.name for path in output.iterdir()} - expected_names
    if extras:
        raise RuntimeError("SCRATCH_OUTPUT_NOT_EMPTY_OR_UNKNOWN:" + ",".join(sorted(extras)))
    for name, frame in frames.items():
        frame.to_parquet(output / f"{name}.parquet", index=False)
    (output / "summary.json").write_text(
        json.dumps(json_ready(summary), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8", newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--selection-only", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    r5 = load_module("rx_exact_pre2026_r5", R5_SOURCE)
    r4 = load_module("rx_exact_pre2026_r4", R4_SOURCE)
    hac = load_module("rx_exact_pre2026_hac", HAC_SOURCE)
    # The original cache location was retired after byte-identical lineage
    # recovery.  Point the unchanged R5 loader at the durable, hash-identical
    # recovered authority before any price materialization.
    r5.RAW_PRICE_CACHE = RECOVERED_PRICE
    authority = verify_authority(r5)
    panel, raw_selection, r5_selection, prices, input_audits = materialize_exact_r5_inputs(r5)
    rx_selection, decision_ledger = build_exact_rx_selection(panel, raw_selection, r5_selection, prices)
    selection_hashes = candidate_selection_hashes(r5, rx_selection)
    mechanism = {
        "total_replacement_proposals": len(decision_ledger),
        "replacements_accepted": int(decision_ledger.replacement_decision.eq("REPLACE").sum()),
        "replacements_vetoed": int(decision_ledger.replacement_decision.eq("RETAIN").sum()),
    }
    mechanism["replacement_acceptance_rate"] = (
        mechanism["replacements_accepted"] / mechanism["total_replacement_proposals"]
        if mechanism["total_replacement_proposals"] else None
    )
    mechanism["veto_rate"] = (
        mechanism["replacements_vetoed"] / mechanism["total_replacement_proposals"]
        if mechanism["total_replacement_proposals"] else None
    )
    summary: dict[str, Any] = {
        "classification": "PRE2026_EXACT_FROZEN_RULE_RETROSPECTIVE_REPLAY",
        "authority": authority,
        "input_audits": input_audits,
        "selection_hashes": selection_hashes,
        "mechanism": mechanism,
        "signal_start": str(pd.Timestamp(rx_selection.signal_date.min()).date()),
        "signal_end": str(pd.Timestamp(rx_selection.signal_date.max()).date()),
        "signal_date_count": int(rx_selection.signal_date.nunique()),
        "threshold_search_count": 0,
        "ddof_search_count": 0,
        "feature_search_count": 0,
        "model_search_count": 0,
        "ml_training_count": 0,
        "hyperparameter_search_count": 0,
        "portfolio_policy_search_count": 0,
        "cost_model_selection_count": 0,
        "2026_rule_selection_count": 0,
        "post2025_outcome_access_count": 0,
    }
    frames = {
        "raw_a2_selection": raw_selection,
        "r5_range_selection": r5_selection,
        "rx_1sigma_selection": rx_selection,
        "rx_decision_ledger": decision_ledger,
    }
    if not args.selection_only:
        raw_path, r5_path, rx_path, economics = replay(
            r4, r5, hac, raw_selection, r5_selection, rx_selection, prices,
        )
        summary["economics"] = economics
        frames.update({
            "raw_a2_path": raw_path,
            "unrestricted_r5_path": r5_path,
            "rx_1sigma_path": rx_path,
        })
    if not args.no_write:
        write_scratch_outputs(args.output.resolve(), frames, summary)
    print(json.dumps(json_ready(summary), indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
