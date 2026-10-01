"""Explicit source routing for the original DEMO views; no mutable global source."""
from dataclasses import replace
from datetime import date
from math import fsum, isclose, isfinite

from apps.demo_console.adapters import decision_reader, performance_reader
from apps.demo_console.adapters import selected_strategies_reader as selected
from apps.demo_console.adapters import updated_research_reader as updated
from apps.demo_console.models import DecisionOverview, PerformanceHistory, PipelineStage, Provenance

LATEST = updated.SOURCE_ID
FROZEN = "frozen"
SELECTED_HGB = "SELECTED_HGB"
SOURCE_LABELS = {LATEST: "最新重算研究", FROZEN: "冻结历史"}
SAMPLE_BOUNDS = {"historical": ("1900-01-01", "2025-12-31"),
                 "test_2026": ("2026-01-01", "2026-12-31")}


def _observation_day(day):
    if day is None:
        return None
    day = day.isoformat() if isinstance(day, date) else day
    try:
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("INVALID_SELECTED_WORKSPACE_DATE") from None
    return day


def applied_observation_dates(package, sample="test_2026", *, raw_model=None):
    """Union verified Raw/HGB observations without synthesizing missing dates."""
    start, end = SAMPLE_BOUNDS[sample]
    try:
        observed = list(selected.workspace_dates(package))
    except (ValueError, TypeError, KeyError, OSError):
        observed = []
    try:
        raw_model = load_overview(source=LATEST) if raw_model is None else raw_model
        if is_updated(raw_model) and not raw_model.error:
            observed.extend(_observation_day(day) for day in scope_overview(raw_model, sample).available_dates)
    except Exception:
        pass
    return tuple(sorted({day for day in observed if day is not None and start <= day <= end}))


def scope_overview(model, sample):
    """Partition display dates and performance without changing recorded signals."""
    start, end = SAMPLE_BOUNDS[sample]
    dates = tuple(day for day in model.available_dates if start <= day <= end)
    cutoff = min(model.performance_cutoff_date, end) if model.performance_cutoff_date else None
    return replace(model, available_dates=dates, sample_start_date=start, sample_end_date=end,
                   performance_cutoff_date=cutoff)


def is_updated(model):
    return model.source_id == LATEST


def source_reference(model):
    if not is_updated(model) or not model.source_manifest_path or not model.source_manifest_sha256:
        raise ValueError("UPDATED_WORKSPACE_REFERENCE_MISSING")
    return {"path": model.source_manifest_path, "sha256": model.source_manifest_sha256}


def load_overview(day=None, *, source=LATEST, reference=None):
    if source == FROZEN:
        return decision_reader.load_overview(day)
    if source != LATEST:
        raise ValueError("UNKNOWN_WORKSPACE_SOURCE")
    try:
        return updated.load_overview(day, reference=reference)
    except Exception as exc:
        return DecisionOverview(decision_date=day, source_id=LATEST, ranking_limit=40,
            pipeline=(PipelineStage("Evidence", "BLOCKED", "最新研究产物读取未通过校验"),),
            error="最新研究数据暂不可用，请查看更新状态；不会用冻结结果冒充本次更新。",
            debug_error=f"{type(exc).__name__}: {exc}", limitations=updated.LIMITATIONS)


def load_selected_overview(strategy_id, day=None, *, package=None, sample="test_2026", observation_dates=None):
    """Bind the existing HGB projection to the shared workspace display contract.

    Both policies share one observed date calendar and one verified package.
    Rankings and executed holdings remain empty: the package exposes targets,
    and its recorded NAV does not supply the Raw execution-ledger fields.
    """
    if strategy_id not in selected.STRATEGY_IDS:
        raise ValueError("UNKNOWN_SELECTED_WORKSPACE_STRATEGY")
    day = _observation_day(day)
    package = selected.load_package() if package is None else selected.validate_package(package)
    start, end = SAMPLE_BOUNDS[sample]
    observed_dates = (selected.workspace_dates(package) if observation_dates is None
                      else tuple(_observation_day(value) for value in observation_dates))
    if any(value is None for value in observed_dates):
        raise ValueError("INVALID_SELECTED_WORKSPACE_CALENDAR")
    dates = tuple(sorted({value for value in observed_dates if start <= value <= end}))
    eligible = dates if day is None else tuple(value for value in dates if value <= day)
    observed = eligible[-1] if eligible else None
    view = selected.workspace_view(strategy_id, observed, package=package) if observed else None
    refs = package.get("source_refs", {})
    sources = tuple(refs[name]["path"] if name in refs else name for name in sorted(package["source_hashes"]))
    hashes = tuple((refs[name]["path"] if name in refs else name, package["source_hashes"][name])
                   for name in sorted(package["source_hashes"]))
    return DecisionOverview(decision_date=observed, available_dates=dates, source_id=SELECTED_HGB,
        source_manifest_path=package.get("package_path"), source_manifest_sha256=package.get("package_sha256"),
        performance_cutoff_date=view["history"]["end"] if view else None,
        sample_start_date=start, sample_end_date=end, execution_status="TARGET_ONLY",
        provenance=Provenance(decision_date=observed, information_as_of=observed,
            strategy_identity=strategy_id, artifact_sources=sources, artifact_hashes=hashes),
        limitations=tuple(package.get("limitations", ())))


def _unavailable_raw_view(cutoff, reason, *, debug_error=None):
    return {"strategy_id": "RAW_A2", "label": "Raw A2", "status": "UNAVAILABLE",
        "requested_cutoff": cutoff, "available_dates": (), "error": reason, "debug_error": debug_error,
        "history": {"status": "UNAVAILABLE", "daily": [], "summary": None, "start": None,
            "end": None, "archive_start": None, "archive_end": None, "initial_nav": 1.0,
            "requested_end_date": cutoff, "reason": reason},
        "target": {"kind": "UNAVAILABLE", "status": "UNAVAILABLE", "signal_date": None,
            "execution_date": None, "rows": [], "target_cash_weight": None,
            "account_basis": "RECORDED_EXECUTED_BOOK", "execution_status": "UNAVAILABLE", "reason": reason}}


def _recorded_number(value, name, *, low=None, high=None):
    if isinstance(value, bool):
        raise ValueError("APPLIED_RAW_INVALID:" + name)
    number = float(value)
    if not isfinite(number) or (low is not None and number < low) or (high is not None and number > high):
        raise ValueError("APPLIED_RAW_INVALID:" + name)
    return number


def _raw_signal_target(model, cutoff):
    target = {"kind": "RAW_RULE_TARGET", "status": "UNAVAILABLE", "signal_date": None,
              "execution_date": None, "rows": [], "target_cash_weight": None,
              "account_basis": "RAW_TOP20_EQUAL_WEIGHT_RULE", "execution_status": "TARGET_ONLY",
              "reason": "所查日期没有完整、已验证的 Raw Top20 信号。"}
    if model is None or not is_updated(model) or model.error or cutoff not in model.available_dates:
        return target
    try:
        current = model if model.decision_date == cutoff else load_overview(
            cutoff, source=LATEST, reference=source_reference(model))
        rows = sorted((row for row in current.ranking if row.rank is not None and row.rank <= 20),
                      key=lambda row: row.rank)
        if current.error or [row.rank for row in rows] != list(range(1, 21)) or len({row.ticker for row in rows}) != 20:
            return target
        execution = current.scheduled_execution_date
        if not execution and current.execution_status == 'EXECUTED':
            execution = current.provenance.execution_date
        execution = _observation_day(execution)
        if execution and execution <= cutoff:
            raise ValueError('APPLIED_RAW_PLANNED_EXECUTION_CLOCK_INVALID')
        return {**target, "status": "READY", "signal_date": cutoff,
                "execution_date": execution,
                "rows": [{"ticker": row.ticker, "target_weight": .05} for row in rows],
                "target_cash_weight": 0., "reason": ""}
    except (ValueError, KeyError, OSError, TypeError):
        return target


def _applied_raw_view(latest, cutoff, sample):
    if not is_updated(latest) or latest.error:
        raise ValueError(latest.error or "APPLIED_RAW_CANONICAL_SOURCE_UNAVAILABLE")
    scoped = scope_overview(latest, sample)
    dates = tuple(day for day in scoped.available_dates if cutoff and day <= cutoff)
    if not dates:
        raise ValueError("APPLIED_RAW_NO_RECORDED_SIGNAL_BY_CUTOFF")
    reference = source_reference(latest)
    signal = dates[-1]
    model = scoped if signal == scoped.decision_date else scope_overview(
        load_overview(signal, source=LATEST, reference=reference), sample)
    if not is_updated(model) or model.error or not model.performance_cutoff_date:
        raise ValueError(model.error or "APPLIED_RAW_PERFORMANCE_CUTOFF_UNAVAILABLE")
    model = replace(model, performance_cutoff_date=min(model.performance_cutoff_date, cutoff))
    history = read_performance(model)
    if history.error or not history.points:
        raise ValueError(history.error or "APPLIED_RAW_PERFORMANCE_UNAVAILABLE")
    points = tuple(point for point in history.points if point.execution_date <= cutoff)
    if len(points) != len(history.points) or not points:
        raise ValueError("APPLIED_RAW_PERFORMANCE_EXCEEDS_CUTOFF")
    dates = tuple(_observation_day(point.execution_date) for point in points)
    if dates != tuple(sorted(set(dates))):
        raise ValueError("APPLIED_RAW_PERFORMANCE_CALENDAR_INVALID")
    first_nav = _recorded_number(points[0].nav, "first_nav", low=0)
    first_return = _recorded_number(points[0].net_return, "first_net_return", low=-1)
    if first_nav <= 0 or first_return <= -1:
        raise ValueError("APPLIED_RAW_NORMALIZATION_UNAVAILABLE")
    baseline = _recorded_number(first_nav / (1 + first_return), "baseline_nav", low=0)
    if baseline <= 0:
        raise ValueError("APPLIED_RAW_NORMALIZATION_UNAVAILABLE")
    daily = []
    for point in points:
        nav = _recorded_number(point.nav, "nav", low=0)
        cash = _recorded_number(point.cash, "cash", low=0)
        if nav <= 0:
            raise ValueError("APPLIED_RAW_INVALID:nav")
        cash_weight = _recorded_number(cash / nav, "cash_weight", low=0, high=1)
        normalized = _recorded_number(nav / baseline, "normalized_nav", low=0)
        if normalized <= 0:
            raise ValueError("APPLIED_RAW_INVALID:normalized_nav")
        daily.append({"date": point.execution_date, "nav": normalized, "cash_weight": cash_weight})
    book = latest_executed_overview(model)
    if book is None or not is_updated(book) or book.error or book.execution_status != "EXECUTED":
        raise ValueError("APPLIED_RAW_EXECUTED_BOOK_UNAVAILABLE")
    execution = _observation_day(book.provenance.execution_date)
    book_signal = _observation_day(book.decision_date)
    if not execution or not book_signal or not book_signal <= execution <= cutoff:
        raise ValueError("APPLIED_RAW_EXECUTED_BOOK_CLOCK_INVALID")
    rows, seen = [], set()
    for row in book.holdings:
        if not isinstance(row.ticker, str) or not row.ticker or row.ticker in seen or row.weight is None:
            raise ValueError("APPLIED_RAW_EXECUTED_WEIGHT_UNAVAILABLE")
        seen.add(row.ticker)
        rows.append({"ticker": row.ticker,
                     "target_weight": _recorded_number(row.weight, "executed_weight", low=0, high=1)})
    total = fsum(row["target_weight"] for row in rows)
    if total > 1 + 1e-7:
        raise ValueError("APPLIED_RAW_EXECUTED_WEIGHT_IDENTITY_INVALID")
    book_point = next((point for point in points if point.execution_date == execution), None)
    cash_weight = book_point.cash / book_point.nav if book_point is not None else max(0., 1 - total)
    cash_weight = _recorded_number(cash_weight, "executed_cash_weight", low=0, high=1)
    if not isclose(total + cash_weight, 1., rel_tol=0., abs_tol=1e-7):
        raise ValueError("APPLIED_RAW_EXECUTED_CASH_IDENTITY_INVALID")
    return {"strategy_id": "RAW_A2", "label": "Raw A2", "status": "AVAILABLE",
        "requested_cutoff": cutoff, "available_dates": scoped.available_dates,
        "source_id": LATEST, "source_path": reference["path"], "package_sha256": reference["sha256"],
        "error": None, "debug_error": None,
        "history": {"status": "AVAILABLE", "daily": daily, "summary": None,
            "start": daily[0]["date"], "end": daily[-1]["date"],
            "archive_start": history.archive_start, "archive_end": history.archive_end,
            "initial_nav": 1., "baseline_source_nav": baseline, "baseline_date": history.baseline_date,
            "normalization_basis": "NAV_BEFORE_FIRST_SAMPLE_RECORD", "requested_end_date": cutoff},
        "target": {"kind": "RECORDED_EXECUTED_BOOK", "status": "READY", "signal_date": book_signal,
            "execution_date": execution, "rows": rows, "target_cash_weight": cash_weight,
            "account_basis": "RECORDED_EXECUTED_BOOK", "execution_status": "EXECUTED", "reason": ""}}


def load_applied_strategies(day, *, package, sample="test_2026", raw_model=None):
    """Read three applied policies at one cutoff, retaining each evidence basis.

    Research curves use the same frozen cash-start batch. The separate Raw
    replay book retains its canonical source; signal targets retain the fixed
    Top20 rule and never acquire an executed status from that book.
    """
    cutoff = _observation_day(day)
    start, end = SAMPLE_BOUNDS[sample]
    latest = raw_model
    raw_error = None
    try:
        if latest is None:
            latest = load_overview(source=LATEST)
    except Exception as exc:
        raw_error = f"{type(exc).__name__}: {exc}"
    if cutoff is None:
        calendar_raw = latest if latest is not None else DecisionOverview(source_id=LATEST,
            error=raw_error or "APPLIED_RAW_CANONICAL_SOURCE_UNAVAILABLE")
        dates = applied_observation_dates(package, sample, raw_model=calendar_raw)
        cutoff = max(dates) if dates else None
    views = {sid: selected.workspace_view(sid, cutoff, package=package) for sid in selected.STRATEGY_IDS}
    if cutoff is None:
        for view in views.values():
            view["requested_cutoff"] = None
            view["history"].update(status="UNAVAILABLE", daily=[], summary=None, start=None, end=None)
            view["target"].update(status="UNAVAILABLE", kind="UNAVAILABLE", rows=[],
                signal_date=None, target_cash_weight=None, reason="当前样本暂无可用观察日。")
    try:
        if latest is None or cutoff is None:
            raise ValueError(raw_error or "APPLIED_RAW_NO_AVAILABLE_OBSERVATION")
        raw = _applied_raw_view(latest, cutoff, sample)
    except Exception as exc:
        raw = _unavailable_raw_view(cutoff, str(exc), debug_error=f"{type(exc).__name__}: {exc}")
    # New packages carry the same cash-start research ledger as both HGB
    # policies. The PIT replay remains a separate, explicitly bound book.
    # Legacy packages retain their existing reader contract.
    if "raw_reference" in package:
        latest_book = raw
        try:
            raw = selected.raw_reference_view(cutoff, package=package)
            raw = {**raw, "latest_book": latest_book,
                   "research_target": raw["target"], "target": latest_book["target"]}
            if cutoff is None or not start <= (raw["history"].get("start") or "") <= end:
                raw["history"].update(status="UNAVAILABLE", daily=[], summary=None, start=None, end=None)
        except Exception as exc:
            raw = _unavailable_raw_view(cutoff, str(exc), debug_error=f"{type(exc).__name__}: {exc}")
            raw["latest_book"] = latest_book
    raw["signal_target"] = _raw_signal_target(latest, cutoff)
    signal_targets = {cutoff: raw['signal_target']}
    for view in views.values():
        target = view['target']
        signal = target.get('signal_date')
        if target.get('execution_status') == 'TARGET_ONLY' and signal:
            if signal not in signal_targets:
                signal_targets[signal] = _raw_signal_target(latest, signal)
            planned = signal_targets[signal].get('execution_date')
            if planned:
                view['target'] = {**target, 'execution_date': planned}
    return {"RAW_A2": raw, **views}


def load_applied_rankings(day, *, package=None, raw_model=None, history=None):
    """Read an exact-day three-policy ranking/target snapshot, without inference."""
    from apps.demo_console.adapters import stock_history_reader
    return stock_history_reader.load_applied_rankings(
        day, package=package, raw_model=raw_model, history=history)


def load_applied_stock_history(*, package=None, raw_model=None, as_of=None):
    """Bind full Raw coverage and shared HGB scores to one observation cutoff."""
    from apps.demo_console.adapters import stock_history_reader
    return stock_history_reader.load_applied_history(package=package, raw_model=raw_model, as_of=as_of)


def query_applied_stock_history(history, ticker, start_date=None, end_date=None, security_id=None,
                                *, identity_mode="SECURITY", identity_chain=None):
    from apps.demo_console.adapters import stock_history_reader
    return stock_history_reader.query_applied_history(
        history, ticker, start_date, end_date, security_id,
        identity_mode=identity_mode, identity_chain=identity_chain)


def load_history(model, window=60):
    if model.source_id == FROZEN:
        return decision_reader.load_history(model.decision_date, window=window)
    if not is_updated(model):
        raise ValueError("UNSUPPORTED_WORKSPACE_HISTORY_SOURCE:" + str(model.source_id))
    dates = tuple(day for day in model.available_dates if day <= model.decision_date)
    if window is not None:
        dates = dates[-window:]
    reference = source_reference(model)
    return tuple(replace(load_overview(day, source=LATEST, reference=reference),
                         available_dates=model.available_dates,
                         sample_start_date=model.sample_start_date, sample_end_date=model.sample_end_date)
                 for day in dates)


def read_performance(model):
    if model.source_id == FROZEN:
        return performance_reader.read_performance(model.provenance.execution_date)
    if not is_updated(model):
        return PerformanceHistory(requested_end_date=model.performance_cutoff_date,
            model_identity=model.provenance.strategy_identity or str(model.source_id),
            error="该策略的执行绩效未在此读取接口提供；不会使用 Raw A2 结果替代。",
            debug_error="UNSUPPORTED_WORKSPACE_PERFORMANCE_SOURCE:" + str(model.source_id))
    try:
        history = updated.read_performance(model.performance_cutoff_date, reference=source_reference(model))
        if not model.sample_start_date or not model.sample_end_date:
            return history
        start, end = model.sample_start_date, model.sample_end_date
        dates = tuple(day for day in history.available_dates if start <= day <= end)
        points = tuple(point for point in history.points if start <= point.execution_date <= end)
        prior = tuple(point.execution_date for point in history.points if points and point.execution_date < points[0].execution_date)
        return replace(history, points=points, available_dates=dates,
                       archive_start=dates[0] if dates else None, archive_end=dates[-1] if dates else None,
                       effective_end_date=points[-1].execution_date if points else None,
                       baseline_date=prior[-1] if prior else history.baseline_date)
    except Exception as exc:
        return PerformanceHistory(requested_end_date=model.performance_cutoff_date,
            error="本次研究的绩效数据暂不可用；排名与持仓不能代替绩效。",
            debug_error=f"{type(exc).__name__}: {exc}", limitations=updated.LIMITATIONS)


def latest_executed_overview(model):
    """Read a separate completed book from the same updated bundle and cutoff.

    Return None for unavailable evidence or other sources. This never changes
    the selected signal date or switches to a different latest pointer.
    """
    if not is_updated(model) or model.error or not model.decision_date or not model.performance_cutoff_date:
        return None
    try:
        reference = source_reference(model)
        _, calendar, _, _, _, _ = updated.bundle(reference)
        candidates = [(str(row["execution_date"])[:10], day) for day, row in calendar.items()
            if row["execution_status"] == "EXECUTED" and row.get("execution_date")
            and day <= model.decision_date
            and str(row["execution_date"])[:10] <= model.performance_cutoff_date]
        if not candidates:
            return None
        return updated.load_overview(max(candidates)[1], reference=reference)
    except (ValueError, KeyError, OSError, TypeError):
        return None


def rank_band(model, selection):
    if not is_updated(model):
        return model
    bounds = {"Top20": (1, 20), "21–40": (21, 40), "Top40": (1, 40)}
    low, high = bounds.get(selection, bounds["Top20"])
    return replace(model, ranking=tuple(row for row in model.ranking if row.rank is not None and low <= row.rank <= high))
