"""Read the explicit updated-research bundle; never execute a producer or trade."""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from math import isclose, isfinite
from pathlib import Path
import re

import pyarrow.parquet as pq

from apps.demo_console.adapters.artifact_reader import iso_date
from apps.demo_console.models import (
    DecisionOverview, HoldingRow, LearningProfile, ModelVintage, PerformanceHistory,
    PerformancePoint, PipelineStage, Provenance, ResearchCoverage,
)

SOURCE_ID = "A2_UPDATED_RESEARCH"
MODEL_2026_SHA = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
EVALUATION = {"signal_execution": "close signal -> next US equity session open",
    "top_n": 20, "cost_bps_round_trip": 10, "terminal_liquidation": False, "initial_nav": 1,
    "turnover": "0.5 * traded_notional / pretrade_nav", "cost_formula": "0.5 * traded_notional * 10 / 10000"}
LIMITATIONS = (
    "更新数据后的描述性研究回放，使用原既定持仓与费用规则；不是实盘账户。",
    "排名、实际模拟持仓和执行日绩效分别读取；待执行信号不具有已执行持仓或收益。",
    "覆盖不足的证券不进入本次排名，历史复权事件快照不代表每个历史时点的发布快照。",
    "2023–2025 使用固定规则重建年度模型，2026 使用原 pre-2026 冻结模型；本次绩效回放不训练或调参。",
    "绩效为次日开盘执行后的持仓估值，首信号日为现金基线；不是当日收盘净值。",
)
DAILY_COLUMNS = (
    "execution_date", "model", "reconstruction_mode", "cash_before", "cash_after", "pretrade_nav",
    "reconstructed_nav", "reconstructed_gross_return", "reconstructed_daily_return",
    "target_turnover", "reconstructed_turnover", "reconstructed_transaction_cost", "position_value",
    "actual_risky_name_count", "stale_mark_count", "skipped_buy_count", "blocked_sell_or_rebalance_count",
    "buy_cash_scale", "NAV_ACCOUNTING_IDENTITY_ERROR", "CASH_IDENTITY_ERROR",
    "POSITION_VALUE_IDENTITY_ERROR", "TURNOVER_IDENTITY_ERROR", "TRANSACTION_COST_IDENTITY_ERROR",
)


def _hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("UPDATED_EXPECTED_JSON_OBJECT")
    return value


def _root(paths=None):
    if paths is None:
        from scripts.common.storage_paths import resolve
        paths = resolve()
    return Path(paths.daily_root) / "A2_updated_research"


def binding(paths=None):
    """Re-read the atomic pointer on every UI rerun; never cache a mutable latest."""
    root = _root(paths)
    pointer = root / "latest.json"
    payload = _json(pointer)
    run_id = str(payload.get("run_id", ""))
    if (payload.get("source_id") != SOURCE_ID or payload.get("status") not in {"READY", "PARTIAL"}
            or not re.fullmatch(r"[A-Za-z0-9_-]{3,100}", run_id)):
        raise ValueError("UPDATED_MANIFEST_IDENTITY_INVALID")
    path = Path(payload.get("report_path") or root / "runs" / run_id / "manifest.json").resolve()
    if path.parent != (root / "runs" / run_id).resolve():
        raise ValueError("UPDATED_MANIFEST_OUTSIDE_RUN")
    digest = _hash(path)
    if _json(path) != payload:
        raise ValueError("UPDATED_POINTER_REPORT_MISMATCH")
    return {"path": str(path), "sha256": digest, "run_id": run_id,
            "generated_at": payload.get("generated_at"), "status": payload["status"]}


def _ref(ref, *, parent=None):
    path = Path(ref["path"]).resolve()
    digest = str(ref["sha256"]).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("UPDATED_REFERENCE_HASH_REQUIRED")
    if parent is not None and not path.is_relative_to(parent):
        raise ValueError("UPDATED_OUTPUT_OUTSIDE_RUN")
    return path, digest


def _stamp(ref):
    path, digest = _ref(ref)
    stat = path.stat()
    return str(path), digest, stat.st_size, stat.st_mtime_ns


def _table(ref, required, *, parent, optional=()):
    path, expected = _ref(ref, parent=parent)
    if _hash(path) != expected:
        raise ValueError("UPDATED_OUTPUT_HASH_MISMATCH:" + path.name)
    names = pq.read_schema(path).names
    if not set(required).issubset(names):
        raise ValueError("UPDATED_OUTPUT_COLUMNS_MISSING:" + path.name)
    rows = pq.read_table(path, columns=[*required, *(key for key in optional if key in names)]).to_pylist()
    if _hash(path) != expected:
        raise ValueError("UPDATED_OUTPUT_CHANGED_DURING_READ:" + path.name)
    return rows


def _number(value, *, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or (nonnegative and value < 0):
        raise ValueError("UPDATED_INVALID_FINITE_NUMBER")
    return float(value)


def _count(value):
    number = _number(value, nonnegative=True)
    if int(number) != number:
        raise ValueError("UPDATED_INVALID_COUNT")
    return int(number)


def _equal(left, right):
    if not isclose(left, right, abs_tol=1e-12, rel_tol=0):
        raise ValueError("UPDATED_ACCOUNTING_IDENTITY_MISMATCH")


def _points(rows, *, expected_model="A2_HGB"):
    points, prior_nav, prior_cash = [], 1.0, 1.0
    days = [iso_date(row["execution_date"]) for row in rows]
    if not rows or days != sorted(set(days)):
        raise ValueError("UPDATED_PERFORMANCE_DATE_ORDER")
    for day, row in zip(days, rows):
        if row["model"] != expected_model or row["reconstruction_mode"] != "POSITION_LEDGER":
            raise ValueError("UPDATED_PERFORMANCE_IDENTITY")
        values = {key: _number(row[key]) for key in DAILY_COLUMNS if key not in {"execution_date", "model", "reconstruction_mode"}}
        for key in DAILY_COLUMNS:
            if key.endswith("IDENTITY_ERROR"):
                _equal(values[key], 0)
        nav, pretrade = values["reconstructed_nav"], values["pretrade_nav"]
        net, gross = values["reconstructed_daily_return"], values["reconstructed_gross_return"]
        cash, value = values["cash_after"], values["position_value"]
        cost, turnover = values["reconstructed_transaction_cost"], values["reconstructed_turnover"]
        if min(nav, pretrade) <= 0 or min(net, gross) <= -1 or min(cash, value, cost, turnover) < 0 or not 0 <= values["buy_cash_scale"] <= 1:
            raise ValueError("UPDATED_INVALID_PERFORMANCE_VALUE")
        _equal(values["cash_before"], prior_cash)
        _equal(nav, cash + value)
        _equal(pretrade, prior_nav * (1 + gross))
        _equal(nav, pretrade - cost)
        _equal(net, nav / prior_nav - 1)
        _equal(gross - net, cost / prior_nav)
        _equal(cost, turnover * pretrade * 0.001)
        counts = [_count(row[key]) for key in ("actual_risky_name_count", "stale_mark_count", "skipped_buy_count", "blocked_sell_or_rebalance_count")]
        points.append(PerformancePoint(day, nav, net, gross, cost, turnover, cash, value, *counts, values["buy_cash_scale"]))
        prior_nav, prior_cash = nav, cash
    return tuple(points)


def _learning(manifest, rankings):
    reference = manifest.get("ranking_manifest")
    if not reference:
        raise ValueError("UPDATED_RANKING_LINEAGE_REQUIRED")
    path, expected = _ref(reference)
    if _hash(path) != expected:
        raise ValueError("UPDATED_RANKING_LINEAGE_HASH_MISMATCH")
    source = _json(path)
    models = source.get("models", {})
    parameters, fingerprint, target = (), None, None
    lineage = models.get("lineage", {})
    if lineage.get("freeze_path") or lineage.get("freeze_sha256"):
        freeze_path, freeze_sha = _ref({"path": lineage["freeze_path"], "sha256": lineage["freeze_sha256"]})
        if _hash(freeze_path) != freeze_sha:
            raise ValueError("UPDATED_MODEL_METADATA_HASH_MISMATCH")
        alpha = _json(freeze_path).get("contracts", {}).get("A2", {})
        fingerprint = alpha.get("source_fingerprint")
        if (alpha.get("feature_schema") != models.get("feature_columns")
                or fingerprint != lineage.get("feature_source_sha256")
                or not re.fullmatch(r"[0-9a-f]{64}", str(fingerprint))
                or alpha.get("prereg_fingerprint") != lineage.get("model_params_source_sha256")
                or alpha.get("supplemental_full_pre2026_model", {}).get("sha256") != MODEL_2026_SHA):
            raise ValueError("UPDATED_MODEL_METADATA_IDENTITY_MISMATCH")
        values = alpha.get("hyperparameters")
        if (not isinstance(values, dict) or any(not isinstance(key, str)
                or not isinstance(value, (str, int, float, bool, type(None)))
                or isinstance(value, float) and not isfinite(value) for key, value in values.items())):
            raise ValueError("UPDATED_MODEL_PARAMETERS_INVALID")
        parameters = tuple((key, json.dumps(value, ensure_ascii=False, allow_nan=False))
            for key, value in sorted(values.items()))
        target = alpha.get("target")
    vintages = []
    for year, item in models.get("artifacts", {}).items():
        shown = [row for row in rankings if iso_date(row["target_date"])[:4] == str(year)]
        if not shown:
            continue
        if (int(year) == 2026 and item.get("sha256") != MODEL_2026_SHA) or any(
                row["model_year"] != int(year) or row["model_sha256"] != item.get("sha256") for row in shown):
            raise ValueError("UPDATED_RANKING_MODEL_MISMATCH")
        if parameters and (item.get("lineage", {}).get("freeze_sha256") != lineage["freeze_sha256"]
                or item.get("lineage", {}).get("feature_source_sha256") != fingerprint
                or item.get("lineage", {}).get("model_params_source_sha256") != lineage["model_params_source_sha256"]):
            raise ValueError("UPDATED_MODEL_PARAMETER_LINEAGE_MISMATCH")
        vintages.append(ModelVintage(int(year), "A2 年度重建" if int(year) < 2026 else "A2 冻结模型",
            item.get("train_end", ""), item.get("labelmax", ""),
            min(iso_date(row["target_date"]) for row in shown), max(iso_date(row["target_date"]) for row in shown),
            item.get("training_row_count", 0), len(shown), item.get("sha256", ""), "SERIALIZED"))
    if {int(iso_date(row["target_date"])[:4]) for row in rankings} != {item.year for item in vintages}:
        raise ValueError("UPDATED_MODEL_YEAR_MISSING")
    return LearningProfile(feature_columns=tuple(models.get("feature_columns", ())), parameters=parameters,
        target=target, vintages=tuple(vintages), source_fingerprint=fingerprint)


@lru_cache(maxsize=2)
def _cached_bundle(path, digest, output_stamps):
    if _hash(path) != digest:
        raise ValueError("UPDATED_MANIFEST_CHANGED")
    manifest = _json(path)
    if manifest.get("source_id") != SOURCE_ID or manifest.get("status") not in {"READY", "PARTIAL"}:
        raise ValueError("UPDATED_BUNDLE_STATUS_INVALID")
    parent = Path(path).resolve().parent
    outputs = manifest["outputs"]
    evaluation = manifest.get("evaluation", {})
    if any(evaluation.get(key) != value or isinstance(evaluation.get(key), bool) != isinstance(value, bool)
           for key, value in EVALUATION.items()):
        raise ValueError("UPDATED_EVALUATION_CONTRACT_CHANGED")
    contract_path, contract_hash = _ref(manifest["evaluation_contract"], parent=parent)
    if _hash(contract_path) != contract_hash:
        raise ValueError("UPDATED_EVALUATION_CONTRACT_HASH_MISMATCH")
    contract = _json(contract_path)
    if (contract.get("source_id") != SOURCE_ID or contract.get("evaluation") != evaluation
            or contract.get("rankings") != {key: outputs["rankings"][key] for key in ("path", "sha256")}):
        raise ValueError("UPDATED_EVALUATION_CONTRACT_BINDING_MISMATCH")
    calendar = _table(outputs["decision_calendar"], ("signal_date", "scheduled_execution_date", "execution_date", "execution_status", "performance_cutoff_date", "portfolio_snapshot_date"),
        parent=parent, optional=("quarter", "effective_date", "institution_count", "universe_member_count", "mapped_count", "eligible_count", "excluded_count", "coverage_status"))
    rankings = _table(outputs["rankings"], ("target_date", "security_id", "ticker", "rank", "score", "model_year", "model_sha256"), parent=parent,
        optional=("universe_id", "universe_quarter", "universe_effective_date", "institution_count"))
    positions = _table(outputs["positions"], ("date", "previous_date", "ticker", "shares_before", "shares_after", "model", "portfolio", "posttrade_weight"),
        parent=parent, optional=("security_id",))
    points = _points(_table(outputs["portfolio_daily"], DAILY_COLUMNS, parent=parent))
    rank_by_day, position_by_day = defaultdict(list), defaultdict(list)
    for row in rankings:
        rank = _count(row["rank"])
        if not 1 <= rank <= 40 or not row["ticker"] or not row["security_id"]:
            raise ValueError("UPDATED_RANKING_INVALID")
        rank_by_day[iso_date(row["target_date"])].append({**row, "rank": rank, "score": _number(row["score"])})
    for rows in rank_by_day.values():
        rows.sort(key=lambda item: item["rank"])
        if ([row["rank"] for row in rows] != list(range(1, 41))
                or len({row["ticker"] for row in rows}) != 40 or len({row["security_id"] for row in rows}) != 40):
            raise ValueError("UPDATED_RANKING_DUPLICATE_OR_GAP")
    for row in positions:
        if row["model"] != "A2_HGB" or row["portfolio"] != "TOP20_EQUAL_WEIGHT_LONG_ONLY":
            raise ValueError("UPDATED_POSITION_IDENTITY_INVALID")
        _number(row["shares_before"], nonnegative=True)
        _number(row["shares_after"], nonnegative=True)
        _number(row["posttrade_weight"], nonnegative=True)
        position_by_day[iso_date(row["date"])].append(row)
    calendar_by_day = {iso_date(row["signal_date"]): row for row in calendar}
    if not rank_by_day or len(calendar_by_day) != len(calendar) or set(rank_by_day) != set(calendar_by_day):
        raise ValueError("UPDATED_DECISION_CALENDAR_INVALID")
    points_by_day = {point.execution_date: point for point in points}
    if manifest.get("ranking_end_date") != max(rank_by_day) or manifest.get("performance_end_date") != points[-1].execution_date:
        raise ValueError("UPDATED_MANIFEST_DATE_BOUNDS")
    for day, row in calendar_by_day.items():
        scheduled = iso_date(row["scheduled_execution_date"]) if row.get("scheduled_execution_date") else None
        executed = iso_date(row["execution_date"]) if row.get("execution_date") else None
        snapshot = iso_date(row["portfolio_snapshot_date"]) if row.get("portfolio_snapshot_date") else None
        cutoff = iso_date(row["performance_cutoff_date"]) if row.get("performance_cutoff_date") else None
        if scheduled is not None and scheduled <= day:
            raise ValueError("UPDATED_EXECUTION_NOT_AFTER_SIGNAL")
        if row["execution_status"] == "EXECUTED":
            if not executed or executed != scheduled or executed != snapshot or cutoff != executed or executed not in points_by_day:
                raise ValueError("UPDATED_EXECUTED_CALENDAR_MISMATCH")
            book = position_by_day.get(executed, [])
            if any(iso_date(item["previous_date"]) != day for item in book) or len({item["ticker"] for item in book}) != len(book):
                raise ValueError("UPDATED_POSITION_SIGNAL_MISMATCH")
            point = points_by_day[executed]
            if sum(item["shares_after"] > 1e-14 for item in book) != point.holding_count:
                raise ValueError("UPDATED_POSITION_COUNT_MISMATCH")
            _equal(sum(item["posttrade_weight"] for item in book), point.position_value / point.nav)
        elif row["execution_status"] in {"PENDING_NEXT_OPEN", "BLOCKED_PRICE_INPUT"}:
            if executed or snapshot or (cutoff and (cutoff > day or cutoff not in points_by_day)):
                raise ValueError("UPDATED_PENDING_CALENDAR_MISMATCH")
        else:
            raise ValueError("UPDATED_EXECUTION_STATUS_UNKNOWN")
    return manifest, calendar_by_day, rank_by_day, position_by_day, points, _learning(manifest, rankings)


def bundle(reference):
    path, digest = _ref(reference)
    if _hash(path) != digest:
        raise ValueError("UPDATED_MANIFEST_HASH_MISMATCH")
    manifest = _json(path)
    stamps = tuple(_stamp(manifest["outputs"][name]) for name in ("rankings", "positions", "portfolio_daily", "decision_calendar"))
    if manifest.get("ranking_manifest"):
        stamps += (_stamp(manifest["ranking_manifest"]),)
        ranking_path, ranking_sha = _ref(manifest["ranking_manifest"])
        if _hash(ranking_path) != ranking_sha:
            raise ValueError("UPDATED_RANKING_LINEAGE_HASH_MISMATCH")
        lineage = _json(ranking_path).get("models", {}).get("lineage", {})
        if lineage.get("freeze_path") or lineage.get("freeze_sha256"):
            stamps += (_stamp({"path": lineage["freeze_path"], "sha256": lineage["freeze_sha256"]}),)
    stamps += (_stamp(manifest["evaluation_contract"]),)
    return _cached_bundle(str(path), digest, stamps)


def clear_cache():
    _cached_bundle.cache_clear()


def load_overview(day=None, *, reference=None, paths=None):
    reference = reference or binding(paths)
    manifest, calendar, ranks, positions, points, learning = bundle(reference)
    dates = tuple(sorted(ranks))
    day = day or dates[-1]
    if day not in ranks:
        raise ValueError("UPDATED_SIGNAL_DATE_NOT_AVAILABLE")
    row = calendar[day]
    status = row["execution_status"]
    execution = iso_date(row["execution_date"]) if row.get("execution_date") else None
    scheduled = iso_date(row["scheduled_execution_date"]) if row.get("scheduled_execution_date") else None
    if status != "EXECUTED" and execution is not None:
        raise ValueError("UPDATED_PENDING_HAS_EXECUTION_DATE")
    raw_cutoff = iso_date(row["performance_cutoff_date"]) if row.get("performance_cutoff_date") else None
    cutoff = min(raw_cutoff, execution or day, points[-1].execution_date) if raw_cutoff else None
    index = dates.index(day)
    previous_day = dates[index - 1] if index else None
    previous_ranks = {item["ticker"]: item["rank"] for item in ranks.get(previous_day, [])}
    holdings, before = (), None
    retained = entered = exited = None
    if execution is not None:
        records = positions.get(execution, [])
        if any(iso_date(item["previous_date"]) != day for item in records) or len({item["ticker"] for item in records}) != len(records):
            raise ValueError("UPDATED_POSITION_SIGNAL_MISMATCH")
        before = tuple(sorted(item["ticker"] for item in records if item["shares_before"] > 1e-14))
        holdings = tuple(HoldingRow(None, item["ticker"], held_before=item["shares_before"] > 1e-14,
            weight=item.get("posttrade_weight")) for item in records if item["shares_after"] > 1e-14)
        after = {item.ticker for item in holdings}
        retained, entered, exited = tuple(sorted(after & set(before))), tuple(sorted(after - set(before))), tuple(sorted(set(before) - after))
    elif (status == "PENDING_NEXT_OPEN" and cutoff == day and day in positions
            and any(item["execution_status"] == "EXECUTED" and item.get("execution_date")
                    and iso_date(item["execution_date"]) == day for item in calendar.values())):
        # The day's validated opening book precedes this closing signal. Its
        # post-trade shares are known; this signal's next-open result is not.
        before = tuple(sorted(item["ticker"] for item in positions[day] if item["shares_after"] > 1e-14))
    rows = tuple(HoldingRow(item["rank"], item["ticker"], item["score"],
        previous_ranks[item["ticker"]] - item["rank"] if item["ticker"] in previous_ranks else None,
        item["ticker"] in before if before is not None else None) for item in ranks[day])
    point = next((item for item in points if item.execution_date == execution), None)
    sample = ranks[day][0]
    coverage = ResearchCoverage(status=row.get("coverage_status"), quarter=row.get("quarter", sample.get("universe_quarter")),
        effective_date=row.get("effective_date", sample.get("universe_effective_date")), institution_count=row.get("institution_count", sample.get("institution_count")),
        universe_member_count=row.get("universe_member_count"), mapped_count=row.get("mapped_count"),
        eligible_count=row.get("eligible_count"), excluded_count=row.get("excluded_count"))
    return DecisionOverview(day, dates, rows, holdings, before, retained, entered, exited,
        turnover=point.turnover if point else None, eligible_universe_count=coverage.eligible_count,
        pipeline=(PipelineStage("Ranking", "AVAILABLE", "本次更新排名"), PipelineStage("Portfolio", "AVAILABLE" if execution else "PENDING", status)),
        provenance=Provenance(day, day, execution, sample.get("universe_id"), "Raw A2 · 更新数据描述性回放",
            artifact_sources=(reference["path"],), artifact_hashes=((reference["path"], reference["sha256"]),), replay_identity=manifest["run_id"], raw_status=manifest["status"], config_identity=sample["model_sha256"]),
        limitations=LIMITATIONS, previous_decision_date=previous_day, learning=learning, source_id=SOURCE_ID,
        source_manifest_path=reference["path"], source_manifest_sha256=reference["sha256"], performance_cutoff_date=cutoff,
        scheduled_execution_date=scheduled, execution_status=status, ranking_limit=40, coverage=coverage)


def read_performance(cutoff, *, reference):
    manifest, calendar, ranks, positions, points, learning = bundle(reference)
    selected = tuple(point for point in points if cutoff and point.execution_date <= cutoff)
    return PerformanceHistory(points=selected, available_dates=tuple(point.execution_date for point in points),
        archive_start=points[0].execution_date, archive_end=points[-1].execution_date, requested_end_date=cutoff,
        effective_end_date=selected[-1].execution_date if selected else None, source_refs=((reference["path"], reference["sha256"]),),
        model_identity="A2_HGB", reference_identity=None, reference_available=False,
        error=None if selected else "所选日期之前没有已完成的执行日绩效。", limitations=LIMITATIONS)
