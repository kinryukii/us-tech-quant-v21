"""Validated, cached presentation reader for the two explicitly selected HGB policies."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from functools import lru_cache
import hashlib
import json
from math import isclose, isfinite
import os
from pathlib import Path
import re


STRATEGY_IDS = ("HGB_DIAG_5", "HGB_FACTOR_5")
STRATEGY_LABELS = {"HGB_DIAG_5": "HGB＋对角风险", "HGB_FACTOR_5": "HGB＋因子／收缩风险"}
SELECTION_BASIS = "USER_SELECTED_AFTER_EXPOSURE"
APPLICATION_STATUSES = {"READY", "LATEST_AVAILABLE_SIGNAL", "BLOCKED"}
_MAX_BYTES = 32 * 1024 * 1024
_WEIGHT_TOLERANCE = 1e-7
_DAILY_NUMBERS = {"net_return": (-1, None), "gross_return": (-1, None), "pretrade_nav": (0, None),
    "turnover": (0, None), "transaction_cost_amount": (0, None), "transaction_cost_fraction": (0, None),
    "gross_exposure": (0, 1), "buy_cash_scale": (0, 1)}
_DAILY_COUNTS = ("holding_count", "skipped_buy_count", "blocked_sell_count", "stale_mark_count", "blocked_rebalance_count")


def _fail(detail):
    raise ValueError("SELECTED_HGB_PACKAGE_INVALID:" + detail)


def _object(value, name):
    if not isinstance(value, dict):
        _fail(name)
    return value


def _number(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(name)
    try:
        value = float(value)
    except (OverflowError, ValueError):
        _fail(name)
    if not isfinite(value):
        _fail(name)
    if (low is not None and value < low) or (high is not None and value > high):
        _fail(name)
    return value


def _day(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _fail(name)
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail(name)
    return value


def _timestamp(value):
    if not isinstance(value, str):
        _fail("generated_at")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("generated_at")
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        _fail("generated_at_timezone")


def _rows(value, name, *, cash_start=False):
    if not isinstance(value, list) or len(value) > 1000:
        _fail(name)
    tickers, target_sum, before_sum = set(), 0.0, 0.0
    for row in value:
        _object(row, name + ".row")
        ticker = row.get("ticker")
        if (not isinstance(ticker, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9./^_-]{0,31}", ticker)
                or ticker in tickers):
            _fail(name + ".ticker")
        tickers.add(ticker)
        target = _number(row.get("target_weight"), name + ".target_weight", 0, 1)
        before = _number(row.get("weight_before"), name + ".weight_before", 0, 1)
        if "pre_cutoff_weight" in row:
            _number(row["pre_cutoff_weight"], name + ".pre_cutoff_weight", 0, .10 + _WEIGHT_TOLERANCE)
        expected_action = "BUY" if target - before > 1e-10 else "SELL" if before - target > 1e-10 else "HOLD"
        if row.get("action") != expected_action:
            _fail(name + ".action")
        if cash_start and before != 0:
            _fail(name + ".cash_start_weight")
        target_sum += target
        before_sum += before
    if target_sum > 1 + _WEIGHT_TOLERANCE or before_sum > 1 + _WEIGHT_TOLERANCE:
        _fail(name + ".weights_sum")
    return target_sum


def _extended_point(point, prior):
    for name, (low, high) in _DAILY_NUMBERS.items():
        if point.get(name) is not None:
            _number(point[name], "daily." + name, low, high)
    for name in _DAILY_COUNTS:
        if point.get(name) is not None and (type(point[name]) is not int or point[name] < 0):
            _fail("daily." + name)
    def identity(actual, expected, name):
        if not isclose(actual, expected, rel_tol=1e-7, abs_tol=1e-10):
            _fail("daily." + name)
    if point.get("net_return") is not None:
        identity(point["net_return"], point["nav"] / prior - 1, "net_return_identity")
    pre, gross, cost = (point.get(name) for name in ("pretrade_nav", "gross_return", "transaction_cost_amount"))
    if pre is not None and pre <= 0:
        _fail("daily.pretrade_nav")
    if pre is not None and gross is not None:
        identity(pre, prior * (1 + gross), "gross_return_identity")
    if pre is not None and cost is not None:
        identity(point["nav"], pre - cost, "cost_nav_identity")
        if point.get("transaction_cost_fraction") is not None:
            identity(point["transaction_cost_fraction"], cost / pre, "cost_fraction_identity")
        if point.get("turnover") is not None:
            identity(cost, point["turnover"] * pre * .001, "cost_turnover_identity")
    if point.get("gross_exposure") is not None:
        identity(point["cash_weight"] + point["gross_exposure"], 1., "cash_exposure_identity")


def _validate_recorded(strategy, name, period):
    start, end = period["start"], period["end"]
    summary = _object(strategy.get("summary"), name + ".summary")
    end_nav = _number(summary.get("end_nav"), "summary.end_nav", 0)
    if end_nav == 0:
        _fail("summary.end_nav")
    _number(summary.get("cumulative_return"), "summary.cumulative_return", -1)
    _number(summary.get("max_drawdown"), "summary.max_drawdown", -1, 0)
    _number(summary.get("mean_cash"), "summary.mean_cash", 0, 1)
    _number(summary.get("turnover"), "summary.turnover", 0)
    if type(summary.get("days")) is not int or summary["days"] < 1:
        _fail("summary.days")
    daily = strategy.get("daily")
    if not isinstance(daily, list) or not daily or len(daily) != summary["days"]:
        _fail(name + ".daily")
    previous, prior_nav = None, 1.0
    for point in daily:
        _object(point, "daily.point")
        day = _day(point.get("date"), "daily.date")
        if day < start or day > end or previous is not None and day <= previous:
            _fail("daily.date_order_or_period")
        previous = day
        if _number(point.get("nav"), "daily.nav", 0) == 0:
            _fail("daily.nav")
        _number(point.get("cash_weight"), "daily.cash_weight", 0, 1)
        _extended_point(point, prior_nav)
        prior_nav = point["nav"]
    if not isclose(daily[-1]["nav"], end_nav, rel_tol=1e-7, abs_tol=1e-9):
        _fail("summary.daily_nav_mismatch")
    if daily[0]["date"] != start or daily[-1]["date"] != end:
        _fail("daily.period_endpoints")
    if all(point.get("turnover") is not None for point in daily):
        if not isclose(sum(point["turnover"] for point in daily), summary["turnover"], rel_tol=1e-7, abs_tol=1e-9):
            _fail("summary.daily_turnover_mismatch")
    targets = strategy.get("targets")
    if not isinstance(targets, list):
        _fail(name + ".targets")
    previous = None
    for target in targets:
        _object(target, "targets.point")
        day = _day(target.get("signal_date"), "targets.signal_date")
        if previous is not None and day <= previous:
            _fail("targets.date_order")
        previous = day
        _rows(target.get("rows"), "targets.rows")
    return tuple(point["date"] for point in daily)


def _validate_score_rows(rows, name, *, historical=False):
    if not isinstance(rows, list) or len(rows) != 40:
        _fail(name + ".count")
    keys = {"ticker", "security_id", "raw_rank", "raw_score", "pred_hgb", "hgb_rank"}
    if historical:
        keys.add("signal_date")
    tickers, identities, raw_ranks, hgb_ranks = set(), set(), set(), set()
    for row in rows:
        _object(row, name + ".row")
        if set(row) != keys:
            _fail(name + ".fields")
        ticker, security = row["ticker"], row["security_id"]
        if not isinstance(ticker, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9./_-]{0,31}", ticker) or ticker in tickers:
            _fail(name + ".ticker")
        if not isinstance(security, str) or not security.strip() or len(security) > 128 or security in identities:
            _fail(name + ".security_id")
        tickers.add(ticker); identities.add(security)
        for field, ranks in (("raw_rank", raw_ranks), ("hgb_rank", hgb_ranks)):
            if type(row[field]) is not int or not 1 <= row[field] <= 40 or row[field] in ranks:
                _fail(name + "." + field)
            ranks.add(row[field])
        _number(row["raw_score"], name + ".raw_score")
        _number(row["pred_hgb"], name + ".pred_hgb")
    for rank, row in enumerate(sorted(rows, key=lambda item: (-item["pred_hgb"], item["ticker"])), 1):
        if row["hgb_rank"] != rank:
            _fail(name + ".ranking_basis")


def _validate_shared_scores(scores, hashes):
    _object(scores, "shared_scores")
    if (scores.get("model_id") != "HGB_2026092501" or scores.get("scoring_scope") != "RAW_TOP40"
            or scores.get("ranking_basis") != "PRED_HGB_DESC_TICKER_ASC"):
        _fail("shared_scores.identity")
    digest = scores.get("model_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        _fail("shared_scores.model_sha256")
    expected = hashes.get("frozen/models/hgb_2026092501.joblib")
    if expected is not None and digest != expected:
        _fail("shared_scores.model_binding")
    history = scores.get("historical")
    if not isinstance(history, list):
        _fail("shared_scores.historical")
    grouped, previous = {}, None
    for row in history:
        _object(row, "shared_scores.historical.row")
        day = _day(row.get("signal_date"), "shared_scores.historical.signal_date")
        if day < "2026-01-01" or previous is not None and day < previous:
            _fail("shared_scores.historical.date_order")
        previous = day
        grouped.setdefault(day, []).append(row)
    for rows in grouped.values():
        _validate_score_rows(rows, "shared_scores.historical", historical=True)
    current = _object(scores.get("current"), "shared_scores.current")
    if set(current) != {"status", "signal_date", "requested_signal_date", "rows", "reason"}:
        _fail("shared_scores.current.fields")
    if current.get("status") not in {"READY", "BLOCKED", "UNAVAILABLE"}:
        _fail("shared_scores.current.status")
    if not isinstance(current.get("reason"), str):
        _fail("shared_scores.current.reason")
    for key in ("signal_date", "requested_signal_date"):
        if current.get(key) is not None:
            _day(current[key], "shared_scores.current." + key)
    if current["status"] == "READY":
        if _day(current.get("signal_date"), "shared_scores.current.signal_date") < "2026-01-01":
            _fail("shared_scores.current.before_frozen_model")
        _validate_score_rows(current.get("rows"), "shared_scores.current")
        if current.get("requested_signal_date") and current["signal_date"] > current["requested_signal_date"]:
            _fail("shared_scores.current.future_signal")
    elif current.get("rows") != [] or current.get("signal_date") is not None or not current.get("reason"):
        _fail("shared_scores.current.unavailable_rows_or_reason")


def _validate_application_history(strategy, hashes, scores):
    history = strategy.get("application_history", [])
    if not isinstance(history, list):
        _fail("application_history")
    allowed = {"status", "signal_date", "requested_signal_date", "account_basis", "rows",
        "target_cash_weight", "cash_weight_before", "decision_clock", "broker_action_allowed",
        "model_fit_calls", "execution_status", "kind", "reason", "account_label", "source_ref"}
    current = strategy["application"]
    cutoff = current.get("requested_signal_date") or current.get("signal_date")
    previous = None
    for app in history:
        _object(app, "application_history.row")
        if set(app) != allowed:
            _fail("application_history.fields")
        day = _day(app.get("signal_date"), "application_history.signal_date")
        if previous is not None and day <= previous or cutoff and day >= cutoff:
            _fail("application_history.date_order_or_future")
        previous = day
        reference = "history/" + day + ".json"
        if app["source_ref"] != reference or reference not in hashes:
            _fail("application_history.source_binding")
        if (app["status"] != "READY" or app["requested_signal_date"] != day
                or app["account_basis"] != "CASH_START" or app["cash_weight_before"] != 1
                or app["kind"] != "ARCHIVED_CASH_START_TARGET" or app["execution_status"] != "TARGET_ONLY"
                or app["decision_clock"] != "SIGNAL_CLOSE_NEXT_SESSION_OPEN"
                or app["broker_action_allowed"] is not False or app["model_fit_calls"] != 0
                or app["reason"] != "" or not isinstance(app["account_label"], str) or not app["account_label"]):
            _fail("application_history.cash_start_identity")
        scored = [row for row in scores.get("historical", []) if row["signal_date"] == day]
        tickers = {row["ticker"] for row in scored if row["raw_rank"] <= 20}
        total = _rows(app["rows"], "application_history.rows", cash_start=True)
        if len(scored) != 40 or any(set(row) != {"ticker", "target_weight", "weight_before", "action"}
                or row["ticker"] not in tickers or row["target_weight"] > .10 + _WEIGHT_TOLERANCE for row in app["rows"]):
            _fail("application_history.score_or_weight_binding")
        cash = _number(app["target_cash_weight"], "application_history.target_cash_weight", 0, 1)
        if not isclose(total + cash, 1., abs_tol=_WEIGHT_TOLERANCE):
            _fail("application_history.cash_identity")


def validate_package(payload):
    """Check UI-facing identities and accounting; producers bind the source bytes."""
    _object(payload, "root")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        _fail("schema_version")
    if payload.get("selection_basis") != SELECTION_BASIS:
        _fail("selection_basis")
    _timestamp(payload.get("generated_at"))
    period = _object(payload.get("performance_period"), "performance_period")
    start = _day(period.get("start"), "performance_period.start")
    end = _day(period.get("end"), "performance_period.end")
    if start > end:
        _fail("performance_period.order")
    if (period.get("decision_clock") != "SIGNAL_CLOSE_NEXT_SESSION_OPEN"
            or period.get("price_basis") not in {"QFQ_PRICE_COORDINATE_PROXY", "PIT_FORWARD_REHAB_INDEX"}):
        _fail("performance_period.basis")
    hashes = _object(payload.get("source_hashes"), "source_hashes")
    if not hashes or any(not isinstance(name, str) or not name or not isinstance(digest, str)
                         or not re.fullmatch(r"[a-fA-F0-9]{64}", digest) for name, digest in hashes.items()):
        _fail("source_hashes")
    if "source_refs" in payload:
        refs = _object(payload["source_refs"], "source_refs")
        if set(refs) != set(hashes):
            _fail("source_refs.identity")
        for name, ref in refs.items():
            _object(ref, "source_refs.ref")
            if not isinstance(ref.get("path"), str) or not ref["path"] or ref.get("sha256") != hashes[name]:
                _fail("source_refs.binding")
    if period.get("price_basis") == "PIT_FORWARD_REHAB_INDEX":
        if "raw_reference" not in payload:
            _fail("performance_extension.raw_reference")
        extension = _object(payload.get("performance_extension"), "performance_extension")
        if (extension.get("source_id") != "NEW_PIT_COMPARISON"
                or type(extension.get("model_fit_calls")) is not int
                or extension["model_fit_calls"] != 0
                or extension.get("broker_action_allowed") is not False
                or extension.get("performance_period") != period):
            _fail("performance_extension.identity")
        manifest = _object(extension.get("manifest"), "performance_extension.manifest")
        if manifest not in payload.get("source_refs", {}).values():
            _fail("performance_extension.manifest_binding")
        requested = _day(extension.get("requested_end_date"), "performance_extension.requested_end_date")
        status, blocked = extension.get("status"), extension.get("blocked_next")
        if requested < end or status not in {"READY", "PARTIAL"}:
            _fail("performance_extension.status")
        if status == "READY":
            if requested != end or blocked is not None:
                _fail("performance_extension.ready_end")
        else:
            blocked = _object(blocked, "performance_extension.blocked_next")
            execution = _day(blocked.get("execution_date"), "performance_extension.execution_date")
            signal = _day(blocked.get("signal_date"), "performance_extension.signal_date")
            if (not end < execution <= requested or signal >= execution
                    or not isinstance(blocked.get("reason"), str) or not blocked["reason"]):
                _fail("performance_extension.blocked_next")
    strategies = _object(payload.get("strategies"), "strategies")
    if set(strategies) != set(STRATEGY_IDS):
        _fail("strategy_ids")
    calendars, labels = [], set()
    for strategy_id in STRATEGY_IDS:
        strategy = _object(strategies[strategy_id], strategy_id)
        if not isinstance(strategy.get("label"), str) or not strategy["label"]:
            _fail(strategy_id + ".label")
        if strategy["label"] in labels:
            _fail("strategy_labels_duplicate")
        labels.add(strategy["label"])
        calendars.append(_validate_recorded(strategy, strategy_id, period))
        application = _object(strategy.get("application"), "application")
        status = application.get("status")
        if status not in APPLICATION_STATUSES:
            _fail("application.status")
        if application.get("requested_signal_date") is not None:
            _day(application["requested_signal_date"], "application.requested_signal_date")
        if status == "BLOCKED":
            if application.get("signal_date") is not None:
                _day(application["signal_date"], "application.signal_date")
            if not isinstance(application.get("reason"), str) or not application["reason"]:
                _fail("application.blocked_reason")
            if application.get("rows"):
                _fail("application.blocked_rows")
            continue
        _day(application.get("signal_date"), "application.signal_date")
        if application.get("account_basis") != "CASH_START":
            _fail("application.account_basis")
        total = _rows(application.get("rows"), "application.rows", cash_start=True)
        cash = _number(application.get("target_cash_weight"), "application.target_cash_weight", 0, 1)
        if not isclose(total + cash, 1.0, abs_tol=_WEIGHT_TOLERANCE):
            _fail("application.cash_identity")
    if calendars[0] != calendars[1]:
        _fail("strategies.calendar_mismatch")
    if "raw_reference" in payload:
        raw = _object(payload["raw_reference"], "raw_reference")
        if raw.get("strategy_id") != "RAW_A2" or not isinstance(raw.get("label"), str) or not raw["label"]:
            _fail("raw_reference.identity")
        if raw.get("performance_period") != period:
            _fail("raw_reference.period_mismatch")
        if _validate_recorded(raw, "raw_reference", period) != calendars[0]:
            _fail("raw_reference.calendar_mismatch")
    if "shared_scores" in payload:
        _validate_shared_scores(payload["shared_scores"], hashes)
    for strategy in strategies.values():
        _validate_application_history(strategy, hashes, payload.get("shared_scores", {}))
    if [p["signal_date"] for p in strategies[STRATEGY_IDS[0]].get("application_history", [])] != [
            p["signal_date"] for p in strategies[STRATEGY_IDS[1]].get("application_history", [])]:
        _fail("application_history.calendar_mismatch")
    return payload


@lru_cache(maxsize=4)
def _decode(raw):
    def reject_constant(value):
        _fail("nonfinite_json:" + value)

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail("duplicate_json_key:" + key)
            result[key] = value
        return result

    payload = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)
    return validate_package(payload)


def package_path():
    override = os.environ.get("USTQ_SELECTED_HGB_PACKAGE")
    if override:
        return Path(override)
    from scripts.common.storage_paths import resolve
    return Path(resolve().daily_root) / "A2_selected_hgb/latest.json"


def load_package(path=None):
    """Read bytes each rerun, caching only a specific immutable JSON content."""
    source = Path(path) if path is not None else package_path()
    with source.open("rb") as stream:
        raw = stream.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        _fail("package_size")
    package = deepcopy(_decode(raw.decode("utf-8-sig")))
    package["package_sha256"] = hashlib.sha256(raw).hexdigest()
    package["package_path"] = str(source.resolve())
    return package


def workspace_dates(package, strategy_id=None):
    """Return recorded/explicitly requested dates, without extending NAV history."""
    validate_package(package)
    if strategy_id is not None and strategy_id not in STRATEGY_IDS:
        _fail("workspace.strategy_id")
    dates = set()
    for sid in (STRATEGY_IDS if strategy_id is None else (strategy_id,)):
        strategy = package["strategies"][sid]
        dates.update(point["date"] for point in strategy["daily"])
        dates.update(point["signal_date"] for point in strategy["targets"])
        dates.update(point["signal_date"] for point in strategy.get("application_history", []))
        application = strategy["application"]
        if application["status"] != "BLOCKED":
            dates.add(application["signal_date"])
        elif application.get("requested_signal_date") or application.get("signal_date"):
            # A recorded blocked update still has an explicit observation date.
            # Keep it selectable so the workspace shows the current failure,
            # while daily history and target rows retain their original dates.
            dates.add(application.get("requested_signal_date") or application["signal_date"])
    if "shared_scores" in package:
        scores = package["shared_scores"]
        dates.update(row["signal_date"] for row in scores["historical"])
        current = scores["current"]
        if current.get("signal_date") or current.get("requested_signal_date"):
            dates.add(current.get("signal_date") or current["requested_signal_date"])
        if current.get("requested_signal_date"):
            dates.add(current["requested_signal_date"])
    return tuple(sorted(dates))


def _workspace_history(strategy, cutoff):
    recorded = strategy["daily"]
    points, returns, prior, peak, drawdown = [], [], 1.0, 1.0, 0.0
    for point in recorded:
        if point["date"] > cutoff:
            break
        point = deepcopy(point)
        point["net_return"] = point["nav"] / prior - 1.0
        returns.append(point["net_return"])
        peak = max(peak, point["nav"])
        drawdown = min(drawdown, point["nav"] / peak - 1.0)
        prior = point["nav"]
        points.append(point)
    summary = None
    if points:
        summary = {"end_nav": points[-1]["nav"], "cumulative_return": points[-1]["nav"] - 1.0,
            "max_drawdown": drawdown, "mean_cash": sum(p["cash_weight"] for p in points) / len(points),
            "days": len(points), "turnover": None}
        if all(point.get("turnover") is not None for point in points):
            summary["turnover"] = sum(point["turnover"] for point in points)
        # Legacy packets carry only full-period turnover. New packets also
        # retain the daily records, so a cutoff can use their actual sum.
        if len(points) == len(recorded):
            summary.update(deepcopy(strategy["summary"]))
        summary.update(net_returns=returns, min_daily_return=min(returns))
    end = points[-1]["date"] if points else None
    return {"status": "AVAILABLE" if points else "UNAVAILABLE", "requested_end_date": cutoff,
        "start": points[0]["date"] if points else None, "end": end,
        "archive_start": recorded[0]["date"], "archive_end": recorded[-1]["date"],
        "daily": points, "summary": summary, "initial_nav": 1.0,
        "last_cash_weight": points[-1]["cash_weight"] if points else None,
        "reason": ("所选截止日之前暂无已记录绩效。" if not points else
                   "绩效仅截至实际已记录日期 " + end + "。" if end < cutoff else "")}


def raw_reference_view(cutoff=None, *, package=None):
    """Read the same-batch Raw proxy, independently of the PIT execution book."""
    if cutoff is not None:
        cutoff = _day(cutoff.isoformat() if isinstance(cutoff, date) else cutoff, "raw_reference.cutoff")
    package = load_package() if package is None else validate_package(package)
    reference = package.get("raw_reference")
    if reference is None:
        return {"strategy_id": "RAW_A2", "label": "Raw A2", "status": "UNAVAILABLE",
            "requested_cutoff": cutoff, "history": {"status": "UNAVAILABLE", "daily": [], "summary": None,
                "start": None, "end": None, "archive_start": None, "archive_end": None, "initial_nav": 1.0},
            "target": {"status": "UNAVAILABLE", "kind": "UNAVAILABLE", "signal_date": None, "rows": [],
                "target_cash_weight": None, "account_basis": None, "execution_status": "TARGET_ONLY",
                "reason": "旧数据包没有同批次 Raw 参考。"}}
    cutoff = cutoff or reference["daily"][-1]["date"]
    strategy = {**reference, "application": {"status": "BLOCKED", "signal_date": None,
        "rows": [], "reason": "该参考仅包含已冻结的历史回放。"}}
    return {"strategy_id": "RAW_A2", "label": reference["label"], "status": "AVAILABLE",
        "requested_cutoff": cutoff, "history": _workspace_history(strategy, cutoff),
        "target": _workspace_target(strategy, cutoff), "performance_period": deepcopy(reference["performance_period"]),
        "source_path": package.get("package_path"), "package_sha256": package.get("package_sha256"),
        "source_hashes": deepcopy(package["source_hashes"]), "source_refs": deepcopy(package.get("source_refs", {})),
        "source_id": package.get("performance_extension", {}).get("source_id", "SAME_BATCH_QFQ_PROXY"), "execution_status": "RECORDED_PROXY_REPLAY"}


def score_snapshot(day=None, *, package=None):
    """Return exactly one published signal date; never borrow another day's score."""
    if day is not None:
        day = _day(day.isoformat() if isinstance(day, date) else day, "shared_scores.requested_date")
    package = load_package() if package is None else validate_package(package)
    scores = package.get("shared_scores")
    meta = {key: scores[key] for key in ("model_id", "model_sha256", "scoring_scope", "ranking_basis")} if scores else {"scoring_scope": "RAW_TOP40"}
    empty = {**meta, "status": "UNAVAILABLE", "requested_signal_date": day,
        "signal_date": None, "actual_signal_date": None, "rows": [], "reason": "该信号日的共享 HGB 评分尚未发布。"}
    if scores is None:
        return empty
    current = scores["current"]
    day = day or current.get("requested_signal_date") or current.get("signal_date") or (
        scores["historical"][-1]["signal_date"] if scores["historical"] else None)
    empty["requested_signal_date"] = day
    if current["status"] != "READY" and day == current.get("requested_signal_date"):
        return {**empty, "status": current["status"], "reason": current["reason"]}
    if current["status"] == "READY" and day == current["signal_date"]:
        return {**meta, **deepcopy(current), "requested_signal_date": day, "actual_signal_date": day}
    rows = [{key: value for key, value in row.items() if key != "signal_date"}
            for row in scores["historical"] if row["signal_date"] == day]
    if rows:
        return {**meta, "status": "READY", "requested_signal_date": day, "signal_date": day,
            "actual_signal_date": day, "rows": deepcopy(rows), "reason": ""}
    return empty


def score_history(*, package=None, ticker=None, security_id=None, start_date=None, end_date=None):
    """Filter only stored historical predictions, keyed by date and security."""
    package = load_package() if package is None else validate_package(package)
    start = _day(start_date, "shared_scores.start_date") if start_date is not None else None
    end = _day(end_date, "shared_scores.end_date") if end_date is not None else None
    if start and end and start > end:
        _fail("shared_scores.range")
    if ticker is not None:
        if not isinstance(ticker, str) or not ticker.strip():
            _fail("shared_scores.ticker")
        ticker = ticker.strip().upper()
    if security_id is not None and (not isinstance(security_id, str) or not security_id):
        _fail("shared_scores.security_id")
    scores = package.get("shared_scores", {})
    return deepcopy([row for row in scores.get("historical", [])
        if (not start or row["signal_date"] >= start) and (not end or row["signal_date"] <= end)
        and (ticker is None or row["ticker"] == ticker) and (security_id is None or row["security_id"] == security_id)])


def _workspace_target(strategy, cutoff):
    application = strategy["application"]
    candidates = [point for point in strategy["targets"] if point["signal_date"] <= cutoff]
    archived = [point for point in strategy.get("application_history", []) if point["signal_date"] <= cutoff]
    latest_recorded = max([point["signal_date"] for point in (*candidates, *archived)], default=None)
    requested = application.get("requested_signal_date") or application.get("signal_date")
    empty = {"status": "UNAVAILABLE", "kind": "UNAVAILABLE", "signal_date": None,
        "rows": [], "target_cash_weight": None, "account_basis": None,
        "execution_status": "TARGET_ONLY", "reason": "所选截止日之前暂无已记录目标。"}
    if application["status"] == "BLOCKED" and requested and _day(requested, "application.requested_signal_date") <= cutoff:
        return {**empty, "status": "BLOCKED", "reason": application["reason"]}
    if (application["status"] != "BLOCKED" and application["signal_date"] <= cutoff
            and (latest_recorded is None or application["signal_date"] >= latest_recorded)):
        target = deepcopy(application)
        target.update(kind="CURRENT_CASH_START_TARGET", execution_status="TARGET_ONLY")
        if target["signal_date"] < cutoff:
            target.update(status="LATEST_AVAILABLE_SIGNAL", reason="最近完整目标信号日为 " + target["signal_date"] + "。")
        return target
    if archived and (not candidates or archived[-1]["signal_date"] >= candidates[-1]["signal_date"]):
        target = deepcopy(archived[-1])
        if target["signal_date"] < cutoff:
            target.update(status="LATEST_AVAILABLE_SIGNAL", reason="最近完整空仓目标信号日为 " + target["signal_date"] + "。")
        return target
    if not candidates:
        return empty
    target = deepcopy(candidates[-1])
    signal = target["signal_date"]
    target.update(status="READY" if signal == cutoff else "LATEST_AVAILABLE_SIGNAL",
        kind="HISTORICAL_SIGNAL_TARGET", account_basis="RECORDED_REPLAY_SIGNAL",
        execution_status="TARGET_ONLY", target_cash_weight=max(0.0, 1.0 - sum(row["target_weight"] for row in target["rows"])),
        reason="" if signal == cutoff else "最近已记录历史目标信号日为 " + signal + "。")
    return target


def workspace_view(strategy_id, cutoff=None, *, package=None, path=None):
    """Project one selected policy into the main workspace at an observed cutoff.

    History and targets keep independent dates. Targets are plans, never account
    positions. Passing one validated package lets comparison views share the
    same byte snapshot instead of rereading a changing latest pointer.
    """
    if strategy_id not in STRATEGY_IDS:
        _fail("workspace.strategy_id")
    if cutoff is not None:
        cutoff = _day(cutoff.isoformat() if isinstance(cutoff, date) else cutoff, "workspace.cutoff")
    try:
        package = load_package(path) if package is None else validate_package(package)
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "BLOCKED", "strategy_id": strategy_id, "label": STRATEGY_LABELS[strategy_id],
            "requested_cutoff": cutoff, "available_dates": (), "latest_application_date": None,
            "latest_requested_signal_date": None, "latest_application_status": "BLOCKED", "history": {"status": "UNAVAILABLE", "daily": [],
                "summary": None, "start": None, "end": None, "archive_start": None, "archive_end": None,
                "requested_end_date": cutoff, "initial_nav": 1.0, "last_cash_weight": None,
                "reason": "策略绩效数据包暂不可用。"},
            "target": {"status": "BLOCKED", "kind": "UNAVAILABLE", "signal_date": None, "rows": [],
                "target_cash_weight": None, "account_basis": None, "execution_status": "TARGET_ONLY",
                "reason": "策略目标数据包暂不可用。"},
            "error": "策略数据包暂不可用或未通过校验。", "debug_error": f"{type(exc).__name__}: {exc}"}
    strategy = package["strategies"][strategy_id]
    dates = workspace_dates(package, strategy_id)
    cutoff = cutoff or dates[-1]
    application = strategy["application"]
    history, target = _workspace_history(strategy, cutoff), _workspace_target(strategy, cutoff)
    return {"status": "AVAILABLE", "strategy_id": strategy_id, "label": strategy["label"],
        "requested_cutoff": cutoff, "available_dates": dates,
        "latest_application_date": application.get("signal_date"),
        "latest_requested_signal_date": application.get("requested_signal_date"), "latest_application_status": application["status"],
        "history": history, "target": target, "error": None, "debug_error": None,
        "generated_at": package["generated_at"], "selection_basis": package["selection_basis"],
        "package_sha256": package.get("package_sha256"), "source_path": package.get("package_path") or (str(path) if path is not None else None),
        "source_hashes": deepcopy(package["source_hashes"]), "source_refs": deepcopy(package.get("source_refs", {})),
        "limitations": deepcopy(package.get("limitations", [])),
        "model_identity": {"model_family": "HGB", "feature_count": 21,
            "feature_family": "RAW_TOP40_RANK_SCORE_BASE9_RET_LAGS",
            "target": "NEXT_OPEN_TO_FIVE_SESSION_LATER_OPEN_ABSOLUTE_RETURN",
            "fit_cutoff_exclusive": "2026-01-01", "prediction_scores_available": score_snapshot(cutoff, package=package)["status"] == "READY",
            "risk_model": "diagonal" if strategy_id == "HGB_DIAG_5" else "factor_shrink"}}


def clear_cache():
    _decode.cache_clear()
