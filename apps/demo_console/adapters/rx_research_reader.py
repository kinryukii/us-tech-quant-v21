"""Read independently published RX replay evidence, always pinned to its A2 parent.

This adapter never computes selections, returns, prices, or orders. A missing or
stale RX publication cannot replace or shorten the original A2 workspace.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from apps.demo_console.adapters import updated_research_reader as base
from apps.demo_console.adapters.artifact_reader import iso_date
from apps.demo_console.models import PerformanceHistory

SOURCE_ID = "A2_RX_UPDATED_RESEARCH"
MODEL = "A2_RX"
POLICY = "RX_MARGIN_R1"
AUTHORITY_SHA = "e9735b812549bd147a4fa311027f5d5cc0cedf06bbe29352c4cd564fa449832e"
PRICE_BASIS = "PIT_FORWARD_REHAB_INDEX"
LIMITATION = "Frozen RX selection rules use the shared next-open execution and fee rules. This is an open-ended descriptive replay, not a reproduction of the old frozen RX ledger."


@dataclass(frozen=True)
class RXView:
    reference: dict | None = None
    manifest: dict | None = None
    history: PerformanceHistory = PerformanceHistory(model_identity=MODEL)
    calendar: dict | None = None
    selections: tuple = ()
    holdings: tuple = ()
    decisions: tuple = ()
    error: str | None = None
    debug_error: str | None = None


def _same_ref(a, b):
    return base._ref(a) == base._ref(b)


def binding(a2_reference, paths=None):
    if paths is None:
        from scripts.common.storage_paths import resolve
        paths = resolve()
    root = Path(paths.daily_root) / "A2_updated_research_rx"
    manifest = base._json(root / "latest.json")
    run_id = str(manifest.get("run_id", ""))
    if (manifest.get("source_id") != SOURCE_ID or manifest.get("status") not in {"READY", "PARTIAL"}
            or not re.fullmatch(r"[A-Za-z0-9_-]{3,100}", run_id)):
        raise ValueError("RX_PUBLICATION_IDENTITY_INVALID")
    path = Path(manifest.get("report_path") or root / "runs" / run_id / "manifest.json").resolve()
    if path.parent != (root / "runs" / run_id).resolve() or base._json(path) != manifest:
        raise ValueError("RX_POINTER_BINDING_INVALID")
    if not _same_ref(manifest["parent_a2_manifest"], a2_reference):
        raise ValueError("RX_PARENT_A2_MISMATCH")
    return {"path": str(path), "sha256": base._hash(path)}


def _read_all(ref, parent):
    path, digest = base._ref(ref, parent=parent)
    if base._hash(path) != digest:
        raise ValueError("RX_OUTPUT_HASH_MISMATCH")
    names = base.pq.read_schema(path).names
    return base._table(ref, names, parent=parent)


@lru_cache(maxsize=2)
def _cached(path, digest, parent_path, parent_sha, stamps):
    if base._hash(path) != digest or base._hash(parent_path) != parent_sha:
        raise ValueError("RX_MANIFEST_HASH_MISMATCH")
    manifest = base._json(path)
    if manifest.get("source_id") != SOURCE_ID or manifest.get("status") not in {"READY", "PARTIAL"}:
        raise ValueError("RX_PUBLICATION_IDENTITY_INVALID")
    if not _same_ref(manifest["parent_a2_manifest"], {"path": parent_path, "sha256": parent_sha}):
        raise ValueError("RX_PARENT_A2_MISMATCH")
    parent = Path(path).parent
    evaluation = manifest.get("evaluation", {})
    if any(evaluation.get(key) != value or isinstance(evaluation.get(key), bool) != isinstance(value, bool)
           for key, value in base.EVALUATION.items()):
        raise ValueError("RX_EXECUTION_CONTRACT_CHANGED")
    contract_path, contract_sha = base._ref(manifest["selection_contract"])
    if base._hash(contract_path) != contract_sha:
        raise ValueError("RX_SELECTION_AUTHORITY_MISMATCH")
    selection_contract = base._json(contract_path)
    frozen_path, frozen_sha = base._ref(selection_contract["frozen_contract"])
    if frozen_sha != AUTHORITY_SHA or base._hash(frozen_path) != frozen_sha:
        raise ValueError("RX_SELECTION_AUTHORITY_MISMATCH")
    if (selection_contract.get("policy_id") != POLICY or selection_contract.get("warmup_sessions") != 60
            or selection_contract.get("predictive_model_fit_count") != 0 or selection_contract.get("threshold_search_count") != 0):
        raise ValueError("RX_SELECTION_POLICY_MISMATCH")
    contract_path, contract_sha = base._ref(manifest["evaluation_contract"], parent=parent)
    if base._hash(contract_path) != contract_sha:
        raise ValueError("RX_EVALUATION_CONTRACT_HASH_MISMATCH")
    contract = base._json(contract_path)
    if contract.get("source_id") != SOURCE_ID or contract.get("evaluation") != evaluation or not _same_ref(
            contract["parent_a2_manifest"], manifest["parent_a2_manifest"]) or not _same_ref(
            contract["selection_contract"], manifest["selection_contract"]):
        raise ValueError("RX_EVALUATION_CONTRACT_BINDING_MISMATCH")
    outputs = manifest["outputs"]
    tables = {name: _read_all(outputs[name], parent) for name in
              ("portfolio_daily", "positions", "decision_calendar", "selections", "decisions")}
    points = base._points(tables["portfolio_daily"], expected_model=MODEL)
    a2 = base.bundle({"path": parent_path, "sha256": parent_sha})
    parent_rankings = a2[2]
    by_day = defaultdict(list)
    for row in tables["selections"]:
        day = iso_date(row["target_date"])
        rank = base._count(row["rank"])
        raw_rank = base._count(row["raw_rank"])
        original = next((item for item in parent_rankings.get(day, ()) if item["ticker"] == row["ticker"]), None)
        if (not row["ticker"] or not 1 <= raw_rank <= 40 or row["candidate_id"] != POLICY
                or original is None or original["rank"] != raw_rank or original["security_id"] != row["security_id"]):
            raise ValueError("RX_SELECTION_INVALID")
        base._number(row["candidate_score"])
        by_day[day].append({**row, "signal_date": day, "candidate_rank": rank})
    for day, rows in by_day.items():
        rows.sort(key=lambda row: row["candidate_rank"])
        if [row["candidate_rank"] for row in rows] != list(range(1, 21)) or len({row["ticker"] for row in rows}) != 20:
            raise ValueError("RX_SELECTION_DUPLICATE_OR_GAP")
    calendar = {iso_date(row["signal_date"]): row for row in tables["decision_calendar"]}
    if not by_day or len(calendar) != len(tables["decision_calendar"]) or set(calendar) != set(by_day):
        raise ValueError("RX_DECISION_CALENDAR_MISMATCH")
    positions = defaultdict(list)
    for row in tables["positions"]:
        if row["model"] != MODEL or row["portfolio"] != "TOP20_EQUAL_WEIGHT_LONG_ONLY":
            raise ValueError("RX_POSITION_IDENTITY_MISMATCH")
        for key in ("shares_before", "shares_after", "posttrade_weight"):
            base._number(row[key], nonnegative=True)
        positions[iso_date(row["date"])].append(row)
    point_map = {row.execution_date: row for row in points}
    if manifest.get("ranking_end_date") != max(calendar) or manifest.get("performance_end_date") != points[-1].execution_date:
        raise ValueError("RX_DATE_BOUNDS_MISMATCH")
    for day, row in calendar.items():
        planned = iso_date(row["scheduled_execution_date"]) if row.get("scheduled_execution_date") else None
        executed = iso_date(row["execution_date"]) if row.get("execution_date") else None
        snapshot = iso_date(row["portfolio_snapshot_date"]) if row.get("portfolio_snapshot_date") else None
        cutoff = iso_date(row["performance_cutoff_date"]) if row.get("performance_cutoff_date") else None
        if planned and planned <= day:
            raise ValueError("RX_EXECUTION_NOT_AFTER_SIGNAL")
        if row["execution_status"] == "EXECUTED":
            if not executed or executed != planned or snapshot != executed or cutoff != executed or executed not in point_map:
                raise ValueError("RX_EXECUTION_DATE_MISMATCH")
            book = positions[executed]
            if len({item["ticker"] for item in book}) != len(book) or any(iso_date(item["previous_date"]) != day for item in book):
                raise ValueError("RX_POSITION_DATE_MISMATCH")
            point = point_map[executed]
            if sum(item["shares_after"] > 1e-14 for item in book) != point.holding_count:
                raise ValueError("RX_POSITION_COUNT_MISMATCH")
            base._equal(sum(item["posttrade_weight"] for item in book), point.position_value / point.nav)
        elif row["execution_status"] in {"PENDING_NEXT_OPEN", "BLOCKED_PRICE_INPUT"}:
            if executed or snapshot or cutoff and (cutoff > day or cutoff not in point_map):
                raise ValueError("RX_PENDING_HAS_EXECUTION")
        else:
            raise ValueError("RX_EXECUTION_STATUS_UNKNOWN")
    decisions = defaultdict(list)
    for row in tables["decisions"]:
        day = iso_date(row["signal_date"])
        if day not in calendar or row["replacement_decision"] not in {"REPLACE", "RETAIN"}:
            raise ValueError("RX_PAIR_DECISION_INVALID")
        margin, required = base._number(row["score_margin"]), base._number(row["required_margin"], nonnegative=True)
        if (row["replacement_decision"] == "REPLACE") != (margin >= required):
            raise ValueError("RX_PAIR_MARGIN_MISMATCH")
        decisions[day].append(row)
    return manifest, calendar, by_day, positions, points, decisions


def bundle(reference, a2_reference):
    path, digest = base._ref(reference)
    parent_path, parent_sha = base._ref(a2_reference)
    if base._hash(path) != digest or base._hash(parent_path) != parent_sha:
        raise ValueError("RX_MANIFEST_HASH_MISMATCH")
    manifest = base._json(path)
    stamps = tuple(base._stamp(ref) for ref in [*manifest["outputs"].values(),
        manifest["selection_contract"], manifest["evaluation_contract"]])
    return _cached(str(path), digest, str(parent_path), parent_sha, stamps)


def read(model, *, reference=None, paths=None):
    """Fail locally: A2 and ETF reads remain independent of RX availability."""
    try:
        from apps.demo_console.adapters.workspace_reader import source_reference
        a2 = source_reference(model)
        a2_path, a2_sha = base._ref(a2)
        if base._hash(a2_path) != a2_sha:
            raise ValueError("RX_PARENT_A2_HASH_MISMATCH")
        reference = reference or binding(a2, paths)
        manifest, calendar, selections, positions, points, decisions = bundle(reference, a2)
        day = model.decision_date
        if day not in calendar:
            raise ValueError("RX_SIGNAL_NOT_AVAILABLE")
        row = calendar[day]
        cutoff = min(str(row["performance_cutoff_date"])[:10], model.performance_cutoff_date) if row.get("performance_cutoff_date") and model.performance_cutoff_date else None
        selected = tuple(point for point in points if cutoff and point.execution_date <= cutoff
            and (not model.sample_start_date or point.execution_date >= model.sample_start_date)
            and (not model.sample_end_date or point.execution_date <= model.sample_end_date))
        dates = tuple(point.execution_date for point in points if
            (not model.sample_start_date or point.execution_date >= model.sample_start_date)
            and (not model.sample_end_date or point.execution_date <= model.sample_end_date))
        prior = [point.execution_date for point in points if selected and point.execution_date < selected[0].execution_date]
        history = PerformanceHistory(points=selected, available_dates=dates, archive_start=dates[0] if dates else None,
            archive_end=dates[-1] if dates else None, requested_end_date=cutoff,
            effective_end_date=selected[-1].execution_date if selected else None, baseline_date=prior[-1] if prior else None,
            model_identity=MODEL, source_refs=((reference["path"], reference["sha256"]),), limitations=(LIMITATION,))
        execution = iso_date(row["execution_date"]) if row.get("execution_date") else None
        holdings = tuple(item for item in positions.get(execution, ()) if item["shares_after"] > 1e-14) if execution else ()
        return RXView(reference, manifest, history, row, tuple(selections[day]), holdings, tuple(decisions[day]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return RXView(error="A2 + RX is not available for this A2 update and selected signal. The original A2 and market references remain available.",
                      debug_error=f"{type(exc).__name__}: {exc}")


@lru_cache(maxsize=2)
def _prices(path, digest, stamp):
    rows = _read_all({"path": path, "sha256": digest}, Path(path).parent)
    keys = set()
    for row in rows:
        row["date"] = iso_date(row["date"])
        key = row["date"], row["ticker"]
        if key in keys or not row["ticker"] or row.get("adjustment") != PRICE_BASIS or row.get("source") != "VERIFIED_RAW_PLUS_PIT_REHAB":
            raise ValueError("RX_PRICE_IDENTITY_INVALID")
        keys.add(key)
        if min(base._number(row["open"]), base._number(row["close"])) <= 0:
            raise ValueError("RX_PRICE_VALUE_INVALID")
    return tuple(rows)


def price_evidence(view, model, *, strategy="A2_RX"):
    """Return display evidence only; trades remain engine records, not rankings."""
    if strategy not in {"A2_HGB", MODEL}:
        raise ValueError("RX_PRICE_CONTEXT_UNAVAILABLE")
    from apps.demo_console.adapters.workspace_reader import source_reference
    parent_ref = source_reference(model)
    a2_manifest, _, rankings, a2_positions, a2_points, _ = base.bundle(parent_ref)
    if strategy == MODEL:
        if view.error or not view.reference:
            raise ValueError("RX_PRICE_CONTEXT_UNAVAILABLE")
        manifest, _, _, positions, _, _ = bundle(view.reference, parent_ref)
        parent = Path(view.reference["path"]).parent
        books = tuple(row for records in positions.values() for row in records)
        trades = _read_all(manifest["outputs"]["trades"], parent)
        signals = [{**row, "signal_date": iso_date(row["target_date"])}
            for row in _read_all(manifest["outputs"]["selections"], parent)]
        price_ref = manifest["outputs"]["price_paths"]
    else:
        # A2 prices and holdings have no dependency on RX publication. Older A2
        # manifests may use the same-parent RX projection as an optional source.
        manifest, parent = a2_manifest, Path(parent_ref["path"]).parent
        books = tuple(row for records in a2_positions.values() for row in records)
        trades = _read_all(manifest["outputs"]["trades"], parent)
        signals = [{**row, "signal_date": day} for day, records in rankings.items() for row in records if row["rank"] <= 20]
        price_ref = manifest["outputs"].get("price_paths")
        if price_ref is None and not view.error and view.reference:
            rx_manifest, *_ = bundle(view.reference, parent_ref)
            price_ref = rx_manifest["outputs"].get("price_paths")
            price_parent = Path(view.reference["path"]).parent
        else:
            price_parent = parent
    rows = ()
    if price_ref is not None:
        price_path, price_sha = base._ref(price_ref, parent=parent if strategy == MODEL else price_parent)
        rows = _prices(str(price_path), price_sha, base._stamp(price_ref))
    cutoff = min(model.performance_cutoff_date or model.decision_date, manifest["performance_end_date"])
    def before(row, key="date"):
        return iso_date(row[key]) <= cutoff
    events = _read_all(manifest["outputs"]["corporate_action_events"], parent) if "corporate_action_events" in manifest["outputs"] else ()
    for row in trades:
        if row.get("model") != strategy or row["side"] not in {"BUY", "SELL"} or not row["ticker"]:
            raise ValueError("RX_TRADE_IDENTITY_INVALID")
        if min(base._number(row["shares"]), base._number(row["execution_price"])) <= 0:
            raise ValueError("RX_TRADE_VALUE_INVALID")
    calendar_dates = tuple(point.execution_date for point in a2_points)
    return {"prices": tuple(row for row in rows if before(row)),
        "positions": tuple(row for row in books if before(row)), "trades": tuple(row for row in trades if before(row)),
        "signals": tuple(row for row in signals if iso_date(row["signal_date"]) <= model.decision_date),
        "events": tuple(events), "cutoff": cutoff, "adjustment": PRICE_BASIS,
        "calendar_dates": calendar_dates}


def selection_tickers(model, *, strategy="A2_HGB", view=None):
    """A selector is independent of price availability and RX success."""
    from apps.demo_console.adapters.workspace_reader import source_reference
    try:
        a2_ref = source_reference(model)
        if strategy == MODEL:
            if view is None or view.error or not view.reference:
                return ()
            rankings = bundle(view.reference, a2_ref)[2]
            rows = ((day, row) for day, records in rankings.items() for row in records)
        elif strategy == "A2_HGB":
            rankings = base.bundle(a2_ref)[2]
            rows = ((day, row) for day, records in rankings.items() for row in records if row["rank"] <= 20)
        else:
            return ()
        return tuple(sorted({row["ticker"] for day, row in rows if day <= model.decision_date
            and (not model.sample_start_date or day >= model.sample_start_date)
            and (not model.sample_end_date or day <= model.sample_end_date)}))
    except (OSError, ValueError, KeyError, TypeError):
        # The current validated page still supplies its own names. The 13F
        # reader independently re-verifies identity and never trusts this list.
        return tuple(sorted({row.ticker for row in model.ranking if row.rank is not None and row.rank <= 20})) if strategy == "A2_HGB" else ()


def clear_cache():
    _cached.cache_clear()
    _prices.cache_clear()
