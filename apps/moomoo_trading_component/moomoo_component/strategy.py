"""Data-only strategy boundary: uploaded strategies cannot execute code."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("时间必须是带时区的 ISO 8601 字符串")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("时间必须明确时区")
    return result.astimezone(timezone.utc)


def number(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{label} 必须是有限数且不小于 {minimum}")
    return value


def code_valid(value):
    return isinstance(value, str) and re.fullmatch(r"US\.[A-Z]{1,8}(?:\.[A-Z])?", value) is not None


def validate_manifest(value):
    if not isinstance(value, dict):
        raise ValueError("策略必须是 JSON 对象")
    required = {"schema_version", "strategy_id", "name", "revision", "asof", "expires_at", "provenance", "targets"}
    if not required <= value.keys() or value.keys() - required - {"source"}:
        raise ValueError("策略字段缺失或存在未支持字段，请使用 v1 契约")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("仅支持 schema_version=1")
    if not isinstance(value["strategy_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value["strategy_id"]):
        raise ValueError("strategy_id 只能包含字母、数字、下划线和短横线，最多64字符")
    for key in ("name", "revision", "source"):
        item = value.get(key, "")
        if not isinstance(item, str) or len(item) > (4096 if key == "source" else 512) or (key != "source" and not item.strip()):
            raise ValueError(f"{key} 无效")
    start, end = timestamp(value["asof"]), timestamp(value["expires_at"])
    if end <= start:
        raise ValueError("expires_at 必须晚于 asof")
    if value["provenance"] not in ("demo", "live", "historical"):
        raise ValueError("provenance 必须为 demo/live/historical")
    if not isinstance(value["targets"], list) or not 1 <= len(value["targets"]) <= 100:
        raise ValueError("targets 必须包含1至100个明确目标")
    seen = set()
    for target in value["targets"]:
        if not isinstance(target, dict) or set(target) != {"code", "target_qty"}:
            raise ValueError("每个 target 仅包含 code 和 target_qty")
        if not code_valid(target["code"]) or target["code"] in seen:
            raise ValueError("仅支持不重复的 US 股票/ETF代码；证券类型还将在券商端验证")
        qty = target["target_qty"]
        if type(qty) is not int or not 0 <= qty <= 1_000_000:
            raise ValueError("target_qty 必须为非负整数，禁止做空和小数股")
        seen.add(target["code"])
    return value


def execution_reasons(manifest, mode, max_age):
    now = datetime.now(timezone.utc)
    start, end = timestamp(manifest["asof"]), timestamp(manifest["expires_at"])
    reasons = []
    if start > now:
        reasons.append("策略信号来自未来，禁止执行")
    if end <= now or (now - start).total_seconds() > max_age:
        reasons.append("策略信号已过期，请由原系统生成新的信号")
    if manifest["provenance"] == "historical":
        reasons.append("历史研究产物不能直接执行")
    if manifest["provenance"] == "demo" and mode != "paper":
        reasons.append("演示策略仅允许本地纸面交易")
    return reasons
