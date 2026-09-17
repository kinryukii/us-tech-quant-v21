"""Validate frozen pre-2026 execution observations without replaying a strategy."""
from __future__ import annotations

from dataclasses import replace
from math import isclose, isfinite

from apps.demo_console.adapters.artifact_reader import ArtifactError, iso_date, read_frozen_parquet
from apps.demo_console.adapters.system_status_reader import read_freeze, read_reference_binding
from apps.demo_console.config.demo_config import DemoConfig, default_config
from apps.demo_console.models import PerformanceHistory, PerformancePoint


ACCOUNTING_TOLERANCE = 1e-12
_IDENTITY_FIELDS = (
    "NAV_ACCOUNTING_IDENTITY_ERROR", "CASH_IDENTITY_ERROR", "POSITION_VALUE_IDENTITY_ERROR",
    "TURNOVER_IDENTITY_ERROR", "TRANSACTION_COST_IDENTITY_ERROR",
)
_COLUMNS = (
    "execution_date", "model", "reconstruction_mode", "cash_before", "cash_after", "pretrade_nav",
    "reconstructed_nav", "reconstructed_gross_return", "reconstructed_daily_return",
    "target_turnover", "reconstructed_turnover", "reconstructed_transaction_cost", "position_value",
    "actual_risky_name_count", "stale_mark_count", "skipped_buy_count",
    "blocked_sell_or_rebalance_count", "buy_cash_scale", *_IDENTITY_FIELDS,
)
LIMITATIONS = (
    "Frozen historical A2 execution observations, not a live account or a combined A2 + RX portfolio.",
    "Archive NAV starts from 1 before the first execution. The first observation includes entry costs; the full archive includes terminal liquidation.",
    "Transaction costs and cash are amounts in initial-NAV units, not percentages or currency account balances.",
    "Gross returns are before the current execution's transaction cost on the recorded holdings path; they are not a separate cost-free strategy replay.",
    "Performance is indexed by execution date. A selected signal corresponds to its later execution; the terminal liquidation has no displayed selection signal.",
    "Execution performance is verified separately from holdings comparisons; the first two historical holdings comparisons remain unavailable in the decision view.",
    "The frozen A reference is a strategy control, not QQQ or a market benchmark. Historical performance and accounting integrity do not establish independent alpha or live readiness.",
)


def _number(row, field, *, nonnegative=False):
    value = row[field]
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            or (nonnegative and value < 0)):
        raise ArtifactError(f"INVALID_PERFORMANCE_NUMBER:{field}")
    return float(value)


def _equal(actual, expected, code):
    if not isclose(actual, expected, rel_tol=0.0, abs_tol=ACCOUNTING_TOLERANCE):
        raise ArtifactError(code)


def _validated_points(spec, expected_model):
    if "execution_date" not in spec.date_columns or "execution_date" in spec.nullable_date_columns:
        raise ArtifactError("PERFORMANCE_EXECUTION_DATE_BOUNDARY_REQUIRED")
    rows = read_frozen_parquet(spec, _COLUMNS).to_pylist()
    dates = tuple(iso_date(row["execution_date"]) for row in rows)
    if not dates or dates != tuple(sorted(set(dates))):
        raise ArtifactError("PERFORMANCE_DATE_ORDER_OR_DUPLICATE")
    points = []
    prior_nav, prior_cash, compounded = 1.0, 1.0, 1.0
    for row, day in zip(rows, dates):
        if row["model"] != expected_model or row["reconstruction_mode"] != "POSITION_LEDGER":
            raise ArtifactError("PERFORMANCE_MODEL_IDENTITY_MISMATCH")
        for field in _IDENTITY_FIELDS:
            _equal(_number(row, field), 0.0, f"PERFORMANCE_RECORDED_ACCOUNTING_ERROR:{field}")
        nav = _number(row, "reconstructed_nav")
        pretrade = _number(row, "pretrade_nav")
        net = _number(row, "reconstructed_daily_return")
        gross = _number(row, "reconstructed_gross_return")
        if nav <= 0 or pretrade <= 0 or net <= -1 or gross <= -1:
            raise ArtifactError("INVALID_PERFORMANCE_NAV_OR_RETURN")
        cash = _number(row, "cash_after", nonnegative=True)
        cost = _number(row, "reconstructed_transaction_cost", nonnegative=True)
        value = _number(row, "position_value", nonnegative=True)
        turnover = _number(row, "reconstructed_turnover", nonnegative=True)
        _number(row, "target_turnover", nonnegative=True)
        scale = _number(row, "buy_cash_scale", nonnegative=True)
        if scale > 1:
            raise ArtifactError("INVALID_BUY_CASH_SCALE")
        counts = {}
        for field in ("actual_risky_name_count", "stale_mark_count", "skipped_buy_count",
                      "blocked_sell_or_rebalance_count"):
            number = _number(row, field, nonnegative=True)
            if number < 0 or int(number) != number:
                raise ArtifactError(f"INVALID_EXECUTION_COUNT:{field}")
            counts[field] = int(number)
        _equal(_number(row, "cash_before", nonnegative=True), prior_cash, "PERFORMANCE_CASH_CONTINUITY_MISMATCH")
        _equal(nav, cash + value, "PERFORMANCE_NAV_ACCOUNTING_MISMATCH")
        _equal(pretrade, prior_nav * (1 + gross), "PERFORMANCE_GROSS_NAV_MISMATCH")
        _equal(nav, pretrade - cost, "PERFORMANCE_COST_NAV_MISMATCH")
        _equal(gross - net, cost / prior_nav, "PERFORMANCE_GROSS_NET_COST_MISMATCH")
        _equal(net, nav / prior_nav - 1, "PERFORMANCE_RETURN_NAV_MISMATCH")
        _equal(cost, turnover * pretrade * 0.001, "PERFORMANCE_COST_RATE_MISMATCH")
        compounded *= 1 + net
        _equal(nav, compounded, "PERFORMANCE_COMPOUND_NAV_MISMATCH")
        points.append(PerformancePoint(day, nav, net, gross, cost, turnover, cash, value,
            counts["actual_risky_name_count"], counts["stale_mark_count"], counts["skipped_buy_count"],
            counts["blocked_sell_or_rebalance_count"], scale))
        prior_nav, prior_cash = nav, cash
    _equal(_number(rows[0], "pretrade_nav"), 1.0, "PERFORMANCE_INITIAL_NAV_MISMATCH")
    if points[-1].holding_count != 0 or abs(points[-1].position_value) > ACCOUNTING_TOLERANCE:
        raise ArtifactError("PERFORMANCE_TERMINAL_LIQUIDATION_MISSING")
    return tuple(points)


def read_performance(end_date: str | None = None, config: DemoConfig | None = None) -> PerformanceHistory:
    """Read a verified execution archive, then expose observations through end_date.

    The existing footer-first reader establishes the whole-file temporal boundary
    before hashing or projecting data. Date cutoff is output selection, not the
    authorization boundary. The optional A arm fails independently from A2.
    """
    requested = end_date
    try:
        if end_date is not None:
            requested = iso_date(end_date)
            if requested >= "2026-01-01":
                raise ArtifactError("POST2025_DATE_BLOCKED")
        config = config or default_config()
        manifest = read_freeze(config)
        contract = manifest.get("contracts", {}).get("evaluation", {})
        if (contract.get("cost_bps_round_trip") != 10
                or contract.get("signal_execution") != "close signal -> next US equity session open"):
            raise ArtifactError("PERFORMANCE_EXECUTION_CONTRACT_MISMATCH")
        points = _validated_points(config.daily, "A2_HGB")
        dates = tuple(point.execution_date for point in points)
        source_refs = [(str(config.manifest_path), config.manifest_sha256),
                       (str(config.hash_manifest_path), config.hash_manifest_sha256),
                       (str(config.daily.path), config.daily.sha256)]
        reference_available, reference_error, reference_debug = False, None, None
        if config.reference_daily is None:
            reference_error = "Frozen A reference is not configured."
        else:
            try:
                read_reference_binding(config, manifest)
                reference = _validated_points(config.reference_daily, "A1")
                if tuple(point.execution_date for point in reference) != dates:
                    raise ArtifactError("REFERENCE_EXECUTION_DATES_MISMATCH")
                points = tuple(replace(point, reference_nav=ref.nav, reference_net_return=ref.net_return,
                    reference_gross_return=ref.gross_return, reference_transaction_cost=ref.transaction_cost)
                    for point, ref in zip(points, reference))
                source_refs.append((str(config.reference_daily.path), config.reference_daily.sha256))
                reference_available = True
            except Exception as exc:
                reference_error = "Frozen A reference is unavailable; A2 remains independently available."
                reference_debug = f"{type(exc).__name__}: {exc}"
        selected = tuple(point for point in points if requested is None or point.execution_date <= requested)
        return PerformanceHistory(points=selected, available_dates=dates,
            archive_start=dates[0], archive_end=dates[-1], requested_end_date=requested,
            effective_end_date=selected[-1].execution_date if selected else None,
            reference_identity="A1" if reference_available else None,
            reference_available=reference_available, source_refs=tuple(source_refs),
            reference_error=reference_error, reference_debug_error=reference_debug,
            error=None if selected else "No frozen execution observations are available through the selected date.",
            limitations=LIMITATIONS)
    except Exception as exc:
        return PerformanceHistory(requested_end_date=requested,
            error="Frozen performance is unavailable. Check the source evidence in Debug mode.",
            debug_error=f"{type(exc).__name__}: {exc}", limitations=LIMITATIONS)
