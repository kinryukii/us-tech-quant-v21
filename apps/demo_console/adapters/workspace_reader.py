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
    if day is None:
        # A later execution record is not a new signal snapshot on first entry.
        current = [strategy["application"].get("requested_signal_date") or
                   strategy["application"].get("signal_date") for strategy in package["strategies"].values()]
        scores = package.get("shared_scores", {}).get("current", {})
        current.append(scores.get("requested_signal_date") or scores.get("signal_date"))
        current = [value for value in current if value in dates]
        day = max(current) if current else None
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


def applied_history_cutoff(day, *, raw_model=None, sample="test_2026"):
    """Allow only the current owner's verified next-session execution in a latest view.

    This does not move the signal/score/target cutoff or extend an archived binding.
    Historical callers retain their exact selected observation day.
    """
    cutoff = _observation_day(day)
    if (sample != "test_2026" or cutoff is None or raw_model is None
            or not is_updated(raw_model) or raw_model.error or raw_model.decision_date != cutoff
            or raw_model.execution_status != "EXECUTED"):
        return cutoff
    try:
        start, end = SAMPLE_BOUNDS[sample]
        dates = tuple(_observation_day(value) for value in raw_model.available_dates if start <= value <= end)
        execution = _observation_day(raw_model.provenance.execution_date)
        scheduled = _observation_day(raw_model.scheduled_execution_date)
        performance = _observation_day(raw_model.performance_cutoff_date)
        if (not dates or max(dates) != cutoff or raw_model.provenance.information_as_of != cutoff
                or execution is None or not cutoff < execution <= end
                or execution != scheduled or execution != performance):
            return cutoff
        reference = source_reference(raw_model)
        current = updated.binding()
        if any(current[key] != reference[key] for key in ("path", "sha256")):
            return cutoff
        return execution
    except (ValueError, TypeError, KeyError, OSError):
        return cutoff


def _applied_raw_view(latest, cutoff, sample, *, history_cutoff=None):
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
    history_end = history_cutoff or cutoff
    model = replace(model, performance_cutoff_date=min(model.performance_cutoff_date, history_end))
    history = read_performance(model)
    if history.error or not history.points:
        raise ValueError(history.error or "APPLIED_RAW_PERFORMANCE_UNAVAILABLE")
    points = tuple(point for point in history.points if point.execution_date <= history_end)
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
    if not execution or not book_signal or not book_signal <= cutoff or not book_signal <= execution <= history_end:
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
            "normalization_basis": "NAV_BEFORE_FIRST_SAMPLE_RECORD", "requested_end_date": history_end},
        "target": {"kind": "RECORDED_EXECUTED_BOOK", "status": "READY", "signal_date": book_signal,
            "execution_date": execution, "rows": rows, "target_cash_weight": cash_weight,
            "account_basis": "RECORDED_EXECUTED_BOOK", "execution_status": "EXECUTED", "reason": ""}}


def load_applied_strategies(day, *, package, sample="test_2026", raw_model=None, history_cutoff=None):
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
    history_end = _observation_day(history_cutoff) if history_cutoff is not None else cutoff
    if history_end != cutoff and history_end != applied_history_cutoff(cutoff, raw_model=latest, sample=sample):
        raise ValueError("APPLIED_HISTORY_CUTOFF_NOT_VERIFIED_LATEST_EXECUTION")
    views = {sid: selected.workspace_view(sid, cutoff, package=package) for sid in selected.STRATEGY_IDS}
    if history_end != cutoff:
        for sid, view in views.items():
            if view.get("status") == "AVAILABLE":
                # Reuse the original projection; copy performance only, never its later target.
                recorded = selected.workspace_view(sid, history_end, package=package)
                view["history"] = recorded["history"]
    if cutoff is None:
        for view in views.values():
            view["requested_cutoff"] = None
            view["history"].update(status="UNAVAILABLE", daily=[], summary=None, start=None, end=None)
            view["target"].update(status="UNAVAILABLE", kind="UNAVAILABLE", rows=[],
                signal_date=None, target_cash_weight=None, reason="当前样本暂无可用观察日。")
    try:
        if latest is None or cutoff is None:
            raise ValueError(raw_error or "APPLIED_RAW_NO_AVAILABLE_OBSERVATION")
        raw = _applied_raw_view(latest, cutoff, sample, history_cutoff=history_end)
    except Exception as exc:
        raw = _unavailable_raw_view(cutoff, str(exc), debug_error=f"{type(exc).__name__}: {exc}")
    # New packages carry the same cash-start research ledger as both HGB
    # policies. The PIT replay remains a separate, explicitly bound book.
    # Legacy packages retain their existing reader contract.
    if "raw_reference" in package:
        latest_book = raw
        try:
            raw = selected.raw_reference_view(cutoff, package=package)
            if history_end != cutoff:
                raw["history"] = selected.raw_reference_view(history_end, package=package)["history"]
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


def load_applied_stock_history(*, package=None, raw_model=None, as_of=None, catalog=None):
    """Bind full Raw coverage and shared HGB scores to one observation cutoff."""
    from apps.demo_console.adapters import stock_history_reader
    history = stock_history_reader.load_applied_history(package=package, raw_model=raw_model, as_of=as_of)
    return stock_history_reader.bind_catalog_history(catalog, history) if catalog is not None else history


def load_applied_stock_catalog(*, package=None, raw_model=None, as_of=None):
    from apps.demo_console.adapters import stock_history_reader
    return stock_history_reader.load_applied_catalog(package=package, raw_model=raw_model, as_of=as_of)


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


def load_active_strategies(day, *, package, sample="test_2026", raw_model=None,
                           history_cutoff=None, account_state=None, research_views=None, strategy_ids=None):
    """Keep replay evidence separate from all five actual-account target plans."""
    from apps.demo_console.adapters import applied_account_reader as accounts
    from apps.moomoo_trading_component.moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS, QUERYABLE_STRATEGY_IDS
    ids = ACTIVE_PAPER_STRATEGY_IDS if strategy_ids is None else tuple(strategy_ids)
    if len(set(ids)) != len(ids) or not set(ids) <= set(QUERYABLE_STRATEGY_IDS):
        raise ValueError("UNKNOWN_QUERYABLE_STRATEGY")
    original = load_applied_strategies(day, package=package, sample=sample,
        raw_model=raw_model, history_cutoff=history_cutoff)
    cutoff = original["RAW_A2"]["requested_cutoff"]
    state = accounts.load_state() if account_state is None else account_state
    current = {sid: accounts.current_view(state, sid, cutoff) for sid in ids}
    for sid in set(ids) & set(ACTIVE_PAPER_STRATEGY_IDS[:2]):
        view, plan = original[sid], current[sid]
        original[sid] = {**view, "research_target": view.get("research_target", view["target"]),
            "target": plan["target"], "signal_target": plan["target"],
            "current_account": plan.get("current_account"), "target_source_refs": plan.get("source_refs", {})}
    if research_views is None:
        from apps.demo_console.adapters import new_strategy_replay_reader
        research_views = new_strategy_replay_reader.load_views(cutoff,
            history_cutoff=history_cutoff, sample=sample,
            **({"strategy_ids": tuple(sid for sid in ids if sid not in ACTIVE_PAPER_STRATEGY_IDS[:2])}
               if any(sid not in ACTIVE_PAPER_STRATEGY_IDS for sid in ids) else {}))
    for sid, replay in research_views.items():
        if sid in current and sid not in original:
            current[sid] = {**current[sid], **{key: replay[key] for key in (
                "history", "model_identity", "provenance") if key in replay}}
    return {sid: original[sid] if sid in original else current[sid] for sid in ids}


def load_active_rankings(day, *, package, raw_model=None, account_state=None, research_rankings=None, strategy_ids=None):
    from apps.demo_console.adapters import applied_account_reader as accounts
    from apps.moomoo_trading_component.moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS, QUERYABLE_STRATEGY_IDS
    ids = ACTIVE_PAPER_STRATEGY_IDS if strategy_ids is None else tuple(strategy_ids)
    if len(set(ids)) != len(ids) or not set(ids) <= set(QUERYABLE_STRATEGY_IDS):
        raise ValueError("UNKNOWN_ACTIVE_RANKING_STRATEGY")
    # Raw/HGB share the original qualified ranking capture. Native actions need
    # neither that capture nor any strategy's performance history.
    snapshot = (load_applied_rankings(day, package=package, raw_model=raw_model)
        if set(ids) & set(ACTIVE_PAPER_STRATEGY_IDS[:2]) else {"strategies": {}})
    state = accounts.load_state() if account_state is None else account_state
    current = accounts.rankings(state, day, **({"strategy_ids": ids} if ids != ACTIVE_PAPER_STRATEGY_IDS else {}))
    strategies = {}
    for sid in ids:
        if sid not in snapshot.get("strategies", {}):
            strategies[sid] = current[sid]
            continue
        recorded = snapshot["strategies"][sid]
        target = accounts.current_view(state, sid, day)["target"]
        known = target["kind"] != "UNAVAILABLE"
        weights = {row["ticker"]: row["target_weight"] for row in target["rows"]}
        rows = [{**row, "target_weight": weights.get(row["ticker"], 0.) if known else None,
            "selected": weights.get(row["ticker"], 0.) > 0 if known else None,
            "target_kind": target["kind"], "weight_date": target["signal_date"]}
            for row in recorded.get("rows", [])]
        strategies[sid] = {**recorded, "rows": rows, "target_kind": target["kind"],
            "weight_date": target["signal_date"], "target_status": target["status"],
            "target_source_refs": target.get("source_refs", {})}
    needed = tuple(sid for sid in ids if sid not in ACTIVE_PAPER_STRATEGY_IDS[:2]
                   and current[sid]["status"] == "UNAVAILABLE")
    if needed and isinstance(day, str) and "2026-01-01" <= day < "2027-01-01":
        try:
            if research_rankings is None:
                from apps.demo_console.adapters import new_strategy_stock_history_reader as native
                research = native.rankings(day, cutoff=day, strategy_ids=needed)
            else:
                research = research_rankings
        except (OSError, ValueError, KeyError, TypeError) as exc:
            research = {"strategies": {}, "error": str(exc)}
        for sid in needed:
            leaf = research.get("strategies", {}).get(sid, {})
            book_plan = (accounts.books(state).get(sid, {}).get("plan") or {})
            if (leaf.get("status") == "AVAILABLE" and leaf.get("actual_signal_date") == day
                    and leaf.get("weight_date") == day and leaf.get("source_kind") == "research"
                    and leaf.get("target_kind") == "RECORDED_RESEARCH_SIGNAL_PLAN"):
                strategies[sid] = {**leaf, "current_target_status": current[sid]["status"],
                    "paper_plan_signal_date": book_plan.get("signal_date")
                        if book_plan.get("strategy_id") == sid else None}
            elif leaf.get("error") or research.get("error") or leaf.get("status") == "AVAILABLE":
                strategies[sid] = {**strategies[sid], "status": "BLOCKED", "source_kind": "research",
                    "error": leaf.get("error") or research.get("error") or "RESEARCH_RANKING_DATE_BINDING_FAILED",
                    "current_target_status": current[sid]["status"],
                    "paper_plan_signal_date": book_plan.get("signal_date")
                        if book_plan.get("strategy_id") == sid else None}
    return {**snapshot, "strategies": strategies}


def load_active_stock_history(*, package=None, raw_model=None, as_of=None, account_state=None, catalog=None):
    from apps.demo_console.adapters import applied_account_reader as accounts
    history = load_applied_stock_history(package=package, raw_model=raw_model, as_of=as_of, **({"catalog": catalog} if catalog is not None else {}))
    from apps.demo_console.adapters import new_strategy_stock_history_reader as native
    first = min(history.get("start_date") or native._FIRST, native._FIRST) if str(as_of or history.get("as_of") or "") >= native._FIRST else history.get("start_date")
    from apps.moomoo_trading_component.moomoo_component.strategy import QUERYABLE_STRATEGY_IDS
    return {**history, "start_date": first, "_active_account_state": accounts.load_state() if account_state is None else account_state,
        "_native_stock_sources": native.source_refs(strategy_ids=QUERYABLE_STRATEGY_IDS[2:])}


def load_active_stock_catalog(*, package=None, raw_model=None, as_of=None, account_state=None):
    history = load_applied_stock_catalog(package=package, raw_model=raw_model, as_of=as_of)
    # The native history starts at its frozen baseline. Source verification and
    # account capture are deferred to the original full loader after selection.
    if history.get('status') == 'CATALOG_READY':
        from apps.demo_console.adapters import new_strategy_stock_history_reader as native
        first = min(history['start_date'], native._FIRST) if str(as_of) >= native._FIRST else history['start_date']
        history = {**history, 'start_date': first, '_active_catalog': True, '_catalog_account_state': account_state}
    return history


def query_active_stock_history(history, ticker, start_date=None, end_date=None, security_id=None, **kwargs):
    from apps.demo_console.adapters import applied_account_reader as accounts, new_strategy_stock_history_reader as native
    from apps.moomoo_trading_component.moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS, QUERYABLE_STRATEGY_IDS
    result = query_applied_stock_history(history, ticker, start_date, end_date, security_id=security_id, **kwargs)
    if result.get("status") == "AMBIGUOUS_IDENTITY":
        return result
    start, end = str(start_date or history["start_date"]), str(end_date or history["as_of"])
    research = native.query(ticker, start, min(end, history["as_of"]), sources=history.get("_native_stock_sources", {}), strategy_ids=QUERYABLE_STRATEGY_IDS[2:])
    recorded = {row["date"]: row for row in result.get("daily", [])}
    native_days = {day for leaf in research["strategies"].values() for day in leaf["daily"]}
    if result.get("status") != "READY" and not native_days:
        return result
    daily = []
    symbol = result.get("ticker", str(ticker).strip().upper())
    for day in sorted(set(recorded) | native_days):
        row = recorded.get(day, {"date": day, "in_pool": None, "security_id": None,
                                "status": "NO_VERIFIED_RAW_POOL_RECORD"})
        current = accounts.rankings(history.get("_active_account_state", {}), day, strategy_ids=QUERYABLE_STRATEGY_IDS)
        strategies = {sid: row.get("strategies", {}).get(sid, {}) for sid in ACTIVE_PAPER_STRATEGY_IDS[:2]}
        for sid in QUERYABLE_STRATEGY_IDS[2:]:
            historical = research["strategies"].get(sid, {}).get("daily", {}).get(day, {})
            leaf = current[sid]
            ticker_rows = [item for item in leaf["rows"] if item["ticker"] == symbol]
            security = row.get("security_id")
            known = lambda value: value is not None and str(value).strip().lower() not in {"", "none", "nan", "null", "unknown", "<na>"}
            matches = [item for item in ticker_rows if known(security)
                and known(item.get("security_id")) and str(item["security_id"]) == str(security)]
            plan = matches[0] if len(matches) == 1 else {}
            absent = leaf["status"] == "AVAILABLE" and not ticker_rows
            target = {**historical}
            if leaf["status"] == "AVAILABLE":
                identity_ok = len(matches) == 1 or absent
                target.update(plan, target_weight=plan.get("target_weight", 0. if absent else None),
                    selected=plan.get("selected", False if absent else None), weight_date=leaf["weight_date"],
                    target_kind=leaf["target_kind"] if identity_ok else "UNAVAILABLE",
                    target_status="READY" if identity_ok else "SECURITY_IDENTITY_UNVERIFIED")
            strategies[sid] = {"model_rank": None, "score": None, "target_weight": None, "selected": None,
                "weight_date": None, "target_kind": None, "score_status": "NO_VERIFIED_SCORE",
                "target_status": "NO_RECORDED_TARGET", **target}
        daily.append({**row, "strategies": strategies})
    return {**result, "status": "READY", "ticker": symbol, "daily": daily,
        "memberships": result.get("memberships", []), "selected_security_ids": result.get("selected_security_ids", []),
        "native_stock_note": research["note"], "native_stock_source_refs": {
            sid: leaf["source_refs"] for sid, leaf in research["strategies"].items()},
        "native_stock_errors": {sid: leaf["error"] for sid, leaf in research["strategies"].items() if leaf.get("error")}}




def ml_observation_dates(package=None, sample="test_2026", *, account_state=None, package_dates=None):
    """Union original package dates and one current capture, without Raw/history."""
    if sample not in SAMPLE_BOUNDS:
        raise ValueError("UNKNOWN_ML_WORKSPACE_SAMPLE")
    if sample == "historical":
        return ()
    from apps.demo_console.adapters import applied_account_reader as accounts
    start, end = SAMPLE_BOUNDS[sample]
    if package_dates is not None and not isinstance(package_dates, tuple):
        raise ValueError("INVALID_ML_PACKAGE_DATES")
    observed = list(selected.workspace_dates(package) if package_dates is None else package_dates)
    state = accounts.load_state() if account_state is None else account_state
    if isinstance(state, dict):
        ids = tuple(accounts.books(state))
        for day in accounts.observation_dates(state):
            if any(accounts.current_view(state, sid, day)["status"] == "AVAILABLE" for sid in ids):
                observed.append(day)
    return tuple(sorted({day for day in observed if start <= day <= end}))


def _ml_identity(strategy_id):
    """Delegate frozen declarations to their original owners; never open models."""
    from apps.moomoo_trading_component.moomoo_component.strategy import QUERYABLE_STRATEGY_IDS
    if strategy_id not in QUERYABLE_STRATEGY_IDS:
        raise ValueError("UNKNOWN_ML_WORKSPACE_STRATEGY")
    if strategy_id in selected.STRATEGY_IDS:
        return selected.model_identity(strategy_id)
    if strategy_id in QUERYABLE_STRATEGY_IDS[2:]:
        from apps.demo_console.adapters import new_strategy_replay_reader
        return new_strategy_replay_reader.model_identity(strategy_id)
    return {}


def load_ml_overview(strategy_id, day=None, *, sample="test_2026", observation_dates=()):
    """A source-free shell for the selected ML view; no Raw or performance read."""
    identity = _ml_identity(strategy_id)
    if sample not in SAMPLE_BOUNDS:
        raise ValueError("UNKNOWN_ML_WORKSPACE_SAMPLE")
    requested = _observation_day(day)
    start, end = SAMPLE_BOUNDS[sample]
    dates = tuple(sorted({_observation_day(value) for value in observation_dates
        if value is not None and start <= _observation_day(value) <= end}))
    # A shared explicit day is a query, not proof that this model has a record.
    # Keep it even when its package calendar lags; exact output reads stay gated.
    chosen = (requested if start <= requested <= end else None) if requested is not None else (dates[-1] if dates else None)
    from apps.demo_console.models import LearningProfile
    return DecisionOverview(decision_date=chosen, available_dates=dates, source_id=strategy_id,
        provenance=Provenance(strategy_identity=strategy_id,
            information_as_of=chosen if chosen in dates else None),
        learning=LearningProfile(target=identity.get("target")),
        sample_start_date=start, sample_end_date=end, ranking_limit=40)


def load_ml_workspace(strategy_id, day, *, package=None, sample="test_2026",
                      raw_model=None, account_state=None):
    """Load only the selected output/target; reuse original qualification owners."""
    from copy import deepcopy
    identity = _ml_identity(strategy_id)
    if sample not in SAMPLE_BOUNDS:
        raise ValueError("UNKNOWN_ML_WORKSPACE_SAMPLE")
    cutoff = _observation_day(day)
    start, end = SAMPLE_BOUNDS[sample]
    context = {"strategy_id": strategy_id, "model_identity": identity}
    if sample == "historical" or cutoff is None or not start <= cutoff <= end:
        result = ml_workspace(strategy_id, cutoff, snapshot={"strategies": {}}, context=context)
        return {**result, "mechanism_only": True}
    if package is None and (strategy_id == "RAW_A2" or strategy_id in selected.STRATEGY_IDS):
        package = selected.load_package(include_performance=False)
    from apps.demo_console.adapters import applied_account_reader as accounts
    state = accounts.load_state() if account_state is None else account_state
    current = accounts.current_view(state, strategy_id, cutoff)
    context.update(target=current["target"], target_source_refs=current.get("source_refs", {}))
    if current["target"].get("signal_date") == cutoff:
        context["model_identity"] = {**identity, **deepcopy(current.get("model_identity") or {})}
    snapshot = load_active_rankings(cutoff, package=package, raw_model=raw_model,
        account_state=state, strategy_ids=(strategy_id,))
    if strategy_id in selected.STRATEGY_IDS:
        context["model_identity"]["prediction_scores_available"] = (
            snapshot.get("strategies", {}).get(strategy_id, {}).get("status") in ("READY", "AVAILABLE"))
    return ml_workspace(strategy_id, cutoff, snapshot=snapshot, context=context,
        raw_model=raw_model, package=package)


def ml_workspace(strategy_id, day, *, snapshot, context, raw_model=None, package=None):
    """Project already verified same-date outputs into one ML display contract.

    This is a pure presentation adapter: callers supply the original reader
    capture. No fallback reads, fitted objects, predictions, ranks or cash are
    created here. In particular, a native action value is never a stock score.
    """
    from copy import deepcopy
    from dataclasses import asdict
    from apps.demo_console.models import LearningProfile
    from apps.moomoo_trading_component.moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS, QUERYABLE_STRATEGY_IDS

    if strategy_id not in QUERYABLE_STRATEGY_IDS:
        raise ValueError("UNKNOWN_ML_WORKSPACE_STRATEGY")
    day = _observation_day(day)
    leaf = snapshot.get("strategies", {}).get(strategy_id, {})
    if not isinstance(leaf, dict) or not isinstance(context, dict):
        raise ValueError("INVALID_ML_WORKSPACE_CAPTURE")
    kind = ("RANK_SCORE" if strategy_id in (*ACTIVE_PAPER_STRATEGY_IDS[:2], "RAW_s10") else
            "GROSS_EXPOSURE" if strategy_id == "R7_GROSS_LINEAR" else "ACTION_VALUE")
    source = leaf.get("source_kind", "recorded")
    basis = ("RECORDED_MAIN_RESEARCH" if source == "research" else
             "CURRENT_PAPER_ACCOUNT" if leaf.get("target_kind") == "CURRENT_ACCOUNT_TARGET" else
             "RECORDED_MODEL_OUTPUT")
    identity = deepcopy(context.get("model_identity") or {})
    context_target = context.get("target") or {}
    for field in ("requested_gross", "previous_requested_gross", "previous_gross"):
        if field in context_target and context_target.get("signal_date") == day:
            identity[field] = deepcopy(context_target[field])
    learning = LearningProfile(target=identity.get("target"))
    provenance = deepcopy(context.get("provenance") or {})
    if not isinstance(provenance, dict):
        provenance = asdict(provenance)
    if strategy_id == "RAW_A2" and raw_model is not None and not raw_model.error and raw_model.decision_date == day:
        learning = raw_model.learning
        provenance = {**asdict(raw_model.provenance), **provenance}
    provenance.update(scope=leaf.get("scope"),
        source_refs=deepcopy(leaf.get("source_refs", snapshot.get("source_refs", context.get("source_refs", {})))),
        target_source_refs=deepcopy(leaf.get("target_source_refs", context.get("target_source_refs", {}))))
    status = leaf.get("status", "UNAVAILABLE")
    score_day, target_day = leaf.get("actual_signal_date"), leaf.get("weight_date")
    result = dict(strategy_id=strategy_id, output_kind=kind, rows=[], model_identity=identity,
        learning=learning, provenance=provenance, source=source, status=status,
        score_date=score_day, target_date=target_day, record_basis=basis,
        target={"kind": "UNAVAILABLE", "status": "UNAVAILABLE", "signal_date": None,
                "execution_date": None, "rows": [], "target_cash_weight": None}, error=None)
    if context.get("strategy_id", strategy_id) != strategy_id:
        result.update(status="BLOCKED", error="ML_WORKSPACE_CONTEXT_IDENTITY_MISMATCH")
        return result
    if day is None or status not in ("AVAILABLE", "READY") or score_day != day:
        result["error"] = leaf.get("error") or "ML_WORKSPACE_EXACT_DATE_OUTPUT_UNAVAILABLE"
        if score_day is not None and score_day != day:
            result["status"] = "UNAVAILABLE"
        return result
    rows = leaf.get("rows", [])
    if not isinstance(rows, (list, tuple)) or any(not isinstance(row, dict) or not isinstance(row.get("ticker"), str)
            or not row["ticker"] for row in rows) or len({row["ticker"] for row in rows}) != len(rows):
        result.update(status="BLOCKED", error="ML_WORKSPACE_INVALID_OUTPUT_ROWS")
        return result

    def number(value):
        return value if type(value) in (int, float) and isfinite(value) else None

    target_rows = {}
    if target_day == day and context_target.get("signal_date") == day and context_target.get("kind") == leaf.get("target_kind"):
        target_rows = {row["ticker"]: row for row in context_target.get("rows", []) if isinstance(row, dict) and row.get("ticker")}
    for original in rows:
        matched = target_rows.get(original["ticker"], {})
        if (original.get("security_id") is not None and matched.get("security_id") is not None
                and original["security_id"] != matched["security_id"]):
            matched = {}
        row = {**{key: value for key, value in matched.items() if key in (
            "action", "weight_before", "explicit_target", "exact_hold_units", "raw_model_weight", "adaptation_reasons")},
            **original}
        projected = {key: deepcopy(row[key]) for key in (
            "ticker", "security_id", "action", "explicit_target", "policy_explicit", "decision_semantic",
            "adaptation_reasons", "security_identity_status", "target_kind", "weight_date") if key in row}
        projected.update(rank=row.get("model_rank") if kind == "RANK_SCORE" else None,
            score=number(row.get("score")) if kind == "RANK_SCORE" else None,
            raw_rank=row.get("raw_rank"), raw_score=number(row.get("raw_score")
                if row.get("raw_score") is not None else row.get("raw_input_score")),
            native_action_score=number(row.get("source_score")) if kind == "ACTION_VALUE" else None,
            target_weight=number(row.get("target_weight")) if target_day == day else None)
        for field in ("weight_before", "research_weight_before", "original_policy_weight", "hold_units",
                      "exact_hold_units", "raw_model_weight", "research_order_target_weight", "adapted_target_weight"):
            projected[field] = number(row.get(field))
        result["rows"].append(projected)
    if target_day == day:
        if (context_target.get("signal_date") == day
                and context_target.get("kind") == leaf.get("target_kind")):
            result["target"] = deepcopy(context_target)
        else:
            result["target"] = {"kind": leaf.get("target_kind"), "status": leaf.get("target_status", status),
                "signal_date": day, "execution_date": None,
                "rows": [{"ticker": row["ticker"], "target_weight": row["target_weight"]} for row in result["rows"]],
                "target_cash_weight": None}
    return result
