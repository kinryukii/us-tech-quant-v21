"""Read-only A2 recommendation bridge; never infer share counts from scores.

This module accepts data dictionaries only. It does not read model binaries,
execute producer code, open files, contact a broker, or update source artifacts.
Historical research and incomplete recommendations remain inspectable, but are
ineligible for conversion to an executable strategy.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MODEL_ID = "A2_HGB"
MODEL_SHA256 = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
MAX_SOURCE_AGE = timedelta(hours=24)
_HASH = re.compile(r"[0-9a-f]{64}")
_SIMPLE_TICKER = re.compile(r"[A-Z][A-Z0-9]{0,9}")
_REASON_TEXT = {
    "UNIVERSE_METADATA_REQUIRED": "缺少股票池资料，无法确认范围。",
    "COVERAGE_METADATA_REQUIRED": "缺少数据覆盖资料，不能视为完整。",
    "HISTORICAL_OR_RESEARCH_SOURCE": "这是历史回放、研究或诊断资料，仅供查看。",
    "SOURCE_NOT_READY": "来源尚未生成可用推荐。",
    "UNRECOGNIZED_FROZEN_MODEL": "策略或模型指纹与已接入的冻结 A2 模型不一致。",
    "SOURCE_BROKER_ACTION_NOT_ALLOWED": "原系统明确未允许券商操作，导入不会解除这个限制。",
    "SOURCE_RUN_ID_REQUIRED": "缺少有效的来源运行编号。",
    "INPUT_MANIFEST_IDENTITY_REQUIRED": "缺少有效的输入清单指纹。",
    "SOURCE_REPORT_REFERENCE_REQUIRED": "缺少可追溯的原始报告位置。",
    "UNIVERSE_NOT_CURRENT_AND_READY": "股票池未明确标记为当前、就绪且可推理。",
    "UNIVERSE_COVERAGE_NOT_COMPLETE": "证券身份覆盖不完整或未知。",
    "IDENTITY_GAPS_OR_UNKNOWN": "存在证券身份缺口，或缺口数量未知。",
    "COVERAGE_COUNTS_REQUIRED": "缺少有效的覆盖数量，不能推断为零缺口。",
    "PARTIAL_COVERAGE": "存在行情、特征或证券身份排除项。",
    "COVERAGE_COUNTS_MISMATCH": "可计算数量、已映射数量与股票池总数不一致。",
    "INSUFFICIENT_ELIGIBLE_UNIVERSE": "可用股票少于 20 支。",
    "SOURCE_GENERATED_IN_FUTURE": "来源生成时间位于未来。",
    "SOURCE_GENERATED_TOO_OLD": "来源生成时间超过 24 小时。",
    "SOURCE_GENERATED_TIMEZONE_REQUIRED": "来源生成时间无效或缺少时区。",
    "UNIVERSE_DATA_DATE_MISMATCH": "股票池日期与信号日期不一致。",
    "DATA_DATE_NOT_LATEST_COMPLETED_WEEKDAY": "信号日期不是最近已收盘工作日；假日或提前收盘需独立核验。",
    "SOURCE_PREDATES_DATA_CLOSE": "来源生成时间早于信号日的纽约 16:00。",
    "NEW_YORK_TIMEZONE_DATA_UNAVAILABLE": "缺少纽约时区资料，无法确认时效。",
    "SOURCE_DATA_DATE_INVALID": "信号日期格式无效。",
    "TOP20_ROWS_REQUIRED": "来源必须提供完整的 20 条选股记录。",
    "INVALID_TARGET_ROW": "选股记录不是合法对象。",
    "EXPLICIT_SYMBOL_ADAPTER_REQUIRED": "该证券代码需要单独确认 Moomoo 代码映射。",
    "SECURITY_TRANSPORT_IDENTITY_MISMATCH": "股票代码与来源 Moomoo 代码不一致。",
    "SECURITY_IDENTITY_REQUIRED": "缺少有效证券身份编号。",
    "INVALID_RANK": "原始排名无效。",
    "INVALID_TARGET_WEIGHT": "原始权重缺失或无效；不会根据评分补造仓位。",
    "INVALID_SCORE": "原始评分缺失或不是有限数。",
    "ROW_SIGNAL_IDENTITY_MISMATCH": "单条记录的日期或模型身份与报告不一致。",
    "ROW_UNIVERSE_IDENTITY_MISMATCH": "单条记录不属于报告指定股票池。",
    "DUPLICATE_SECURITY": "存在重复证券或证券身份。",
    "TOP20_RANKS_NOT_CONTIGUOUS": "Top20 排名存在重复或缺口。",
    "TOP20_WEIGHTS_DO_NOT_SUM_TO_ONE": "原始 Top20 权重之和不等于 1。",
    "SOURCE_NOT_FINITE_JSON": "来源含非 JSON 值或 NaN、无穷大。",
}


class DailyImportError(ValueError):
    """A recommendation cannot safely be converted."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a timezone-qualified string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp timezone is required")
    return result.astimezone(timezone.utc)


def _date(value: object) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("ISO date is required")
    return date.fromisoformat(value)


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _finite(value: object) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _latest_weekday_close(now: datetime, ny: ZoneInfo) -> date:
    """Conservative freshness check, not an exchange calendar.

    Require the most recent weekday at/after 16:00 New York. Holidays and early
    closes may therefore be rejected. They are never guessed into eligibility.
    The broker must independently enforce the real session at execution time.
    """
    local = now.astimezone(ny)
    candidate = local.date()
    if local.time() < time(16):
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def inspect_daily(payload: dict) -> dict:
    """Return a weight-only preview with explicit reasons conversion is blocked.

    A producer's READY status is insufficient: full identity/price coverage,
    original timestamps, pinned model identity, and broker permission are checked
    separately. Source weights are informational and never become quantities.
    """
    if not isinstance(payload, dict):
        raise DailyImportError("DAILY_JSON_OBJECT_REQUIRED")
    reasons: list[str] = []

    def reject(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    now = _now_utc()
    universe = payload.get("universe")
    if not isinstance(universe, dict):
        universe = {}
        reject("UNIVERSE_METADATA_REQUIRED")
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        coverage = {}
        reject("COVERAGE_METADATA_REQUIRED")
    source_kind = "A2_today_recommendation"
    historical = payload.get("provenance") == "historical" or any(
        token in str(payload.get(key, "")).lower()
        for key in ("source", "source_id", "scope")
        for token in ("historical", "replay", "diagnostic", "research", "preparation")
    )
    if historical:
        source_kind = "historical_or_research"
        reject("HISTORICAL_OR_RESEARCH_SOURCE")
    if payload.get("status") != "READY":
        reject("SOURCE_NOT_READY")
    if payload.get("model_id") != MODEL_ID or payload.get("model_sha256") != MODEL_SHA256:
        reject("UNRECOGNIZED_FROZEN_MODEL")
    if payload.get("broker_action_allowed") is not True:
        reject("SOURCE_BROKER_ACTION_NOT_ALLOWED")
    if not isinstance(payload.get("run_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,100}", payload["run_id"]):
        reject("SOURCE_RUN_ID_REQUIRED")
    if not isinstance(payload.get("input_manifest_sha256"), str) or not _HASH.fullmatch(payload["input_manifest_sha256"]):
        reject("INPUT_MANIFEST_IDENTITY_REQUIRED")
    if not isinstance(payload.get("report_path"), str) or not payload["report_path"].strip():
        reject("SOURCE_REPORT_REFERENCE_REQUIRED")
    if universe.get("current") is not True or universe.get("inference_ready") is not True or universe.get("status") != "READY":
        reject("UNIVERSE_NOT_CURRENT_AND_READY")
    if universe.get("coverage_status") not in ("COMPLETE", "FULL", "READY", "FULL_IDENTITY_COVERAGE"):
        reject("UNIVERSE_COVERAGE_NOT_COMPLETE")
    if not _count(universe.get("mapping_gap_count")) or universe["mapping_gap_count"] != 0:
        reject("IDENTITY_GAPS_OR_UNKNOWN")
    if universe.get("mapping_gaps") not in ([], None):
        reject("IDENTITY_GAPS_OR_UNKNOWN")
    required_counts = ("eligible_count", "mapped_count", "excluded_count")
    if any(not _count(coverage.get(key)) for key in required_counts):
        reject("COVERAGE_COUNTS_REQUIRED")
    else:
        if coverage["excluded_count"] != 0 or coverage.get("status") not in (None, "READY", "COMPLETE", "FULL"):
            reject("PARTIAL_COVERAGE")
        member_count = universe.get("universe_member_count")
        if not _count(member_count) or not (coverage["eligible_count"] == coverage["mapped_count"] == member_count):
            reject("COVERAGE_COUNTS_MISMATCH")
        if coverage["eligible_count"] < 20:
            reject("INSUFFICIENT_ELIGIBLE_UNIVERSE")

    generated = None
    data_day = None
    try:
        generated = _timestamp(payload.get("generated_at"))
        if generated > now:
            reject("SOURCE_GENERATED_IN_FUTURE")
        elif now - generated > MAX_SOURCE_AGE:
            reject("SOURCE_GENERATED_TOO_OLD")
    except (ValueError, OverflowError):
        reject("SOURCE_GENERATED_TIMEZONE_REQUIRED")
    try:
        data_day = _date(payload.get("data_date"))
        if data_day.year < 2026:
            reject("HISTORICAL_OR_RESEARCH_SOURCE")
        if universe.get("target_date") != data_day.isoformat():
            reject("UNIVERSE_DATA_DATE_MISMATCH")
        ny = ZoneInfo("America/New_York")
        expected_day = _latest_weekday_close(now, ny)
        if data_day != expected_day:
            reject("DATA_DATE_NOT_LATEST_COMPLETED_WEEKDAY")
        if generated and generated < datetime.combine(data_day, time(16), ny).astimezone(timezone.utc):
            reject("SOURCE_PREDATES_DATA_CLOSE")
    except ZoneInfoNotFoundError:
        reject("NEW_YORK_TIMEZONE_DATA_UNAVAILABLE")
    except (ValueError, OverflowError):
        reject("SOURCE_DATA_DATE_INVALID")

    targets: list[dict] = []
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != 20:
        reject("TOP20_ROWS_REQUIRED")
    if isinstance(rows, list):
        # Bound untrusted preview work; oversized reports are rejected above.
        for row in rows[:40]:
            if not isinstance(row, dict):
                reject("INVALID_TARGET_ROW")
                continue
            ticker, weight, rank = row.get("ticker"), row.get("raw_target_weight"), row.get("rank")
            security_id = row.get("security_id")
            if not isinstance(ticker, str) or not _SIMPLE_TICKER.fullmatch(ticker):
                reject("EXPLICIT_SYMBOL_ADAPTER_REQUIRED")
                code = None
            else:
                code = "US." + ticker
                if row.get("moomoo_transport_code") not in (None, code):
                    reject("SECURITY_TRANSPORT_IDENTITY_MISMATCH")
            if not isinstance(security_id, str) or not re.fullmatch(r"[A-Z0-9]{9}", security_id):
                reject("SECURITY_IDENTITY_REQUIRED")
                security_id = None
            if not _count(rank) or rank < 1:
                reject("INVALID_RANK")
            if not _finite(weight) or weight <= 0 or weight > 1:
                reject("INVALID_TARGET_WEIGHT")
                weight = None
            if not _finite(row.get("score")):
                reject("INVALID_SCORE")
            if row.get("target_date") != payload.get("data_date") or row.get("model_id") != MODEL_ID:
                reject("ROW_SIGNAL_IDENTITY_MISMATCH")
            if not isinstance(row.get("universe_id"), str) or row["universe_id"] != universe.get("universe_id"):
                reject("ROW_UNIVERSE_IDENTITY_MISMATCH")
            if any(token in str(row.get("source", "")).lower() for token in ("historical", "replay", "diagnostic", "research")):
                reject("HISTORICAL_OR_RESEARCH_SOURCE")
            targets.append({"code": code, "ticker": ticker, "security_id": security_id,
                            "rank": rank, "weight": weight})
    if targets:
        codes = [row["code"] for row in targets]
        ranks = [row["rank"] for row in targets]
        identities = [row["security_id"] for row in targets]
        if len(set(codes)) != len(codes) or len(set(identities)) != len(identities):
            reject("DUPLICATE_SECURITY")
        if all(_count(rank) for rank in ranks) and sorted(ranks) != list(range(1, 21)):
            reject("TOP20_RANKS_NOT_CONTIGUOUS")
        if all(row["weight"] is not None for row in targets) and not math.isclose(sum(row["weight"] for row in targets), 1.0, abs_tol=1e-9):
            reject("TOP20_WEIGHTS_DO_NOT_SUM_TO_ONE")
    try:
        source_hash = _canonical_hash(payload)
    except (TypeError, ValueError, OverflowError):
        source_hash = None
        reject("SOURCE_NOT_FINITE_JSON")
    return {
        "source": source_kind, "strategy_id": "a2-daily", "model_id": payload.get("model_id"),
        "model_sha256": payload.get("model_sha256"), "run_id": payload.get("run_id"),
        "data_date": payload.get("data_date"), "generated_at": payload.get("generated_at"),
        "report_path": payload.get("report_path"), "source_sha256": source_hash,
        "coverage": {**coverage, "universe_member_count": universe.get("universe_member_count"),
                     "identity_coverage_status": universe.get("coverage_status"),
                     "mapping_gap_count": universe.get("mapping_gap_count")},
        "broker_action_allowed": payload.get("broker_action_allowed") is True,
        "targets": targets, "rejection_reasons": reasons, "eligible_for_conversion": not reasons,
        "rejection_details": [{"code": code, "message": _REASON_TEXT[code]} for code in reasons],
        "summary": "仅供检查，不能转换为执行策略。" if reasons else "来源校验通过；转换仍需明确填写目标股数。",
        "weight_note": "权重仅显示原始记录，不会从评分、排名或权重自动生成股数。",
        "freshness_policy": "24h source age; latest weekday 16:00 America/New_York; holiday/early-close uncertainty blocks",
    }


def convert_daily(payload: dict, quantities: dict, asof: str, expires_at: str) -> dict:
    """Convert a fully eligible source using caller-specified absolute quantities.

    Keys are exact US broker codes present in the source Top20. A subset is
    allowed; omitted codes stay untouched, and explicit zero means exit. No
    prices, portfolio weights, scores, or historical positions determine sizing.
    """
    review = inspect_daily(payload)
    if review["rejection_reasons"]:
        raise DailyImportError("; ".join(review["rejection_reasons"]))
    try:
        source_asof = _timestamp(payload["generated_at"])
        requested_asof = _timestamp(asof)
        expiry = _timestamp(expires_at)
    except (ValueError, OverflowError) as exc:
        raise DailyImportError("STRATEGY_TIMEZONE_REQUIRED") from exc
    if requested_asof != source_asof:
        raise DailyImportError("ASOF_MUST_PRESERVE_SOURCE_GENERATED_AT")
    if not source_asof < expiry <= source_asof + MAX_SOURCE_AGE or expiry <= _now_utc():
        raise DailyImportError("EXPIRY_MUST_BE_FUTURE_WITHIN_SOURCE_24H")
    if not isinstance(quantities, dict) or not 1 <= len(quantities) <= 20:
        raise DailyImportError("EXPLICIT_QUANTITIES_REQUIRED")
    known = {row["code"] for row in review["targets"]}
    targets = []
    for code, quantity in quantities.items():
        if not isinstance(code, str) or code not in known:
            raise DailyImportError("QUANTITY_CODE_NOT_IN_SOURCE_TOP20")
        if not _count(quantity) or quantity > 1_000_000:
            raise DailyImportError("QUANTITY_MUST_BE_BOUNDED_NONNEGATIVE_INTEGER")
        targets.append({"code": code, "target_qty": quantity})
    source = {"adapter": "a2-daily-v1", "run_id": payload["run_id"],
              "data_date": payload["data_date"], "generated_at": payload["generated_at"],
              "model_id": MODEL_ID, "model_sha256": MODEL_SHA256,
              "input_manifest_sha256": payload["input_manifest_sha256"],
              "payload_sha256": review["source_sha256"], "report_path": payload["report_path"],
              "quantities": "explicit_caller_input"}
    return {"schema_version": 1, "strategy_id": "a2-daily", "name": "A2 每日信号（明确股数）",
            "revision": payload["run_id"], "asof": payload["generated_at"], "expires_at": expires_at,
            "provenance": "live", "targets": targets,
            "source": json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}
