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


LEGACY_PAPER_STRATEGY_IDS = ("RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5")
ACTIVE_PAPER_STRATEGY_IDS = ("RAW_A2", "HGB_DIAG_5", "R10_DIRECT_MEAN4_ELASTICNET_MID",
    "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR")
# Query membership grants no execution or broker authority. The accepted paper
# roster is versioned separately; retain the original five-ID v1 contract.
QUERYABLE_STRATEGY_IDS = (*ACTIVE_PAPER_STRATEGY_IDS, "R6_BUY_NEURAL",
    "R6_DURATION_TREE", "RAW_s10")
APPLIED_STRATEGY_NAMES = {"RAW_A2": "Raw A2", "HGB_DIAG_5": "HGB + 对角风险",
    "HGB_FACTOR_5": "HGB + 因子 / 收缩风险",
    "R10_DIRECT_MEAN4_ELASTICNET_MID": "ElasticNet MID",
    "R10_DIRECT_H5_RIDGE_MID": "Ridge H5 MID", "R7_GROSS_LINEAR": "R7 LINEAR",
    "R6_BUY_NEURAL": "R6 Buy NEURAL", "R6_DURATION_TREE": "R6 Duration TREE",
    "RAW_s10": "同池 RAW · Consensus Top100"}


def requested_gross_input(saved, signal_date):
    """Use state-before for the same signal, and the accepted request for its successor."""
    if not isinstance(saved, dict) or saved.get("last_signal_date", signal_date) > signal_date:
        raise ValueError("FUTURE_REQUESTED_GROSS_STATE_FORBIDDEN")
    value = (saved.get("previous_input_gross", 1.0) if saved.get("last_signal_date") == signal_date
        else saved.get("previous_requested_gross", 1.0))
    value = number(value, "前期请求总仓位")
    if value > 1:
        raise ValueError("REQUESTED_GROSS_MUST_BE_LONG_ONLY")
    return value


def accepted_requested_gross_state(plan, state_before, signal_date):
    """Persist one accepted G transition; realized fills never enter this rule."""
    after = plan.get("strategy_state_after")
    previous = number(state_before.get("previous_requested_gross"), "前期请求总仓位")
    requested = number(plan.get("requested_gross"), "本期请求总仓位")
    if (previous > 1 or requested > 1 or not isinstance(after, dict)
            or after.get("last_signal_date") != signal_date
            or abs(number(plan.get("previous_requested_gross"), "计划前期请求总仓位") - previous) > 1e-12
            or abs(number(after.get("previous_requested_gross"), "请求状态后值") - requested) > 1e-12):
        raise ValueError("R7_REQUESTED_STATE_CONTRACT_INVALID")
    return {**after, "previous_requested_gross": requested, "previous_input_gross": previous}


def exact_hold_units(plan):
    """A frozen unit HOLD must never be resized from a drifted dollar weight."""
    result = {}
    sid = plan.get("strategy_id")
    from scripts.research.a2.inference.consensus_paper import PAPER_CURRENT_IDS
    scoped = (sid in PAPER_CURRENT_IDS
        and plan.get("policy_id") == sid and plan.get("account_basis") == "OWN_SIGNAL_CLOSE_FROZEN_CONSENSUS"
        and plan.get("valuation_basis") == "SIGNAL_CLOSE" and plan.get("status") == "READY"
        and plan.get("broker_action_allowed") is False and type(plan.get("model_fit_calls")) is int
        and plan["model_fit_calls"] == 0)
    for row in plan.get("rows", []):
        if scoped and row.get("action") == "SKIP":
            target = row.get("target_weight")
            if (row.get("explicit_target") is not False or "exact_hold_units" in row
                    or not code_valid(row.get("code")) or type(target) not in (int, float)
                    or not math.isfinite(target) or target != 0):
                raise ValueError("EXACT_HOLD_UNIT_CONTRACT_INVALID")
            continue  # A frozen zero-capital entry SKIP is not a unit HOLD.
        if "exact_hold_units" not in row and row.get("explicit_target") is not False:
            continue
        code, quantity = row.get("code"), row.get("exact_hold_units")
        if (scoped and type(quantity) is float and math.isfinite(quantity)
                and 0 <= quantity <= 2**53 and quantity.is_integer()):
            quantity = int(quantity)  # Lossless boundary view; frozen plan bytes stay untouched.
        if (not code_valid(code) or code in result or row.get("action") != "HOLD"
                or row.get("explicit_target") is not False
                or type(quantity) is not int or quantity < 0):
            raise ValueError("EXACT_HOLD_UNIT_CONTRACT_INVALID")
        result[code] = quantity
    return result


def validate_auto_completion_policy(value):
    """The one explicit, audited simulation authority; never a model parameter."""
    expected = {"schema_version", "enabled", "policy_id", "reason", "authorized_at_utc",
        "effective_execution_date", "evaluation_end_exclusive", "priority_window_seconds",
        "close_buffer_seconds", "one_tick_spread", "normal_spread_bps",
        "max_single_tick_spread_bps", "quote_max_age_seconds", "price_deviation_fraction",
        "active_strategy_ids", "broker_account_id", "broker_budget"}
    from datetime import date
    from zoneinfo import ZoneInfo
    schema_two = (isinstance(value, dict) and type(value.get("schema_version")) is int
        and value["schema_version"] == 2)
    if schema_two:
        expected = expected | {"execution_delay_minutes"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("AUTOMATIC_COMPLETION_POLICY_SCHEMA_INVALID")
    integer_constants = {"schema_version": 1, "priority_window_seconds": 600,
        "close_buffer_seconds": 600, "normal_spread_bps": 50,
        "max_single_tick_spread_bps": 200, "quote_max_age_seconds": 30}
    if schema_two:
        integer_constants.update(schema_version=2, execution_delay_minutes=25,
            priority_window_seconds=1500)
    if (any(type(value[k]) is not int or value[k] != v for k, v in integer_constants.items())
            or type(value["enabled"]) is not bool or type(value["one_tick_spread"]) is not bool
            or not isinstance(value["policy_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", value["policy_id"])
            or value["reason"] != "USER_EXPLICIT_DAILY_AUTO_COMPLETION"
            or value["active_strategy_ids"] != ["HGB_DIAG_5", "HGB_FACTOR_5"]
            or value["evaluation_end_exclusive"] != "2027-01-01"
            or isinstance(value["price_deviation_fraction"], bool)
            or value["price_deviation_fraction"] != .02
            or isinstance(value["broker_budget"], bool) or value["broker_budget"] != 10000
            or not isinstance(value["broker_account_id"], str)
            or not re.fullmatch(r"[0-9]{1,64}", value["broker_account_id"])):
        raise ValueError("AUTOMATIC_COMPLETION_POLICY_BOUNDARY_INVALID")
    if not isinstance(value["effective_execution_date"], str):
        raise ValueError("AUTOMATIC_COMPLETION_POLICY_EFFECTIVE_DATE_INVALID")
    effective = date.fromisoformat(value["effective_execution_date"])
    authorized = timestamp(value["authorized_at_utc"])
    if (not "2026-01-01" <= effective.isoformat() < "2027-01-01"
            or effective <= authorized.astimezone(ZoneInfo("America/New_York")).date()):
        raise ValueError("AUTOMATIC_COMPLETION_POLICY_EFFECTIVE_DATE_INVALID")
    return value


def automatic_completion_clock_matches(policy, delay, window):
    """Match only the clock explicitly bound by the original standing policy."""
    validate_auto_completion_policy(policy)
    if type(delay) is not int or type(window) is not int:
        return False
    if policy["schema_version"] == 1:
        return delay in (0, 30) and window == 600
    return delay == policy["execution_delay_minutes"] and window == policy["priority_window_seconds"]


def auto_completion_spread_is_valid(quote):
    """50bp normally; one actual minimum tick may pass, always <=200bp."""
    from decimal import Decimal, InvalidOperation
    try:
        if not isinstance(quote, dict):
            return False
        bid, ask = (Decimal(str(quote[k])) for k in ("bid", "ask"))
        if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
            return False
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid * 10000
        if spread > 200:
            return False
        if spread <= 50:
            return True
        raw_tick = quote.get("price_tick")
        if "price_tick" in quote and "tick_size" in quote and Decimal(str(quote["price_tick"])) != Decimal(str(quote["tick_size"])):
            return False
        if isinstance(raw_tick, bool):
            return False
        tick = Decimal(str(raw_tick))
        return tick.is_finite() and tick > 0 and ask - bid <= tick
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
        return False
