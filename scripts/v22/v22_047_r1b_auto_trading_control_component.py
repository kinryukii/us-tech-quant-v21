from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

REVISION = "V22.047_R1B"
COMPONENT_NAME = "NASDAQ_AUTO_TRADING_CONTROL_COMPONENT"
BENCHMARK_SYMBOL = "US.QQQ"
ALLOWED_EXECUTION_SYMBOLS = ("US.IQQ", "US.TQQQ", "US.SQQQ")
SYMBOL_ROLES = {
    "US.IQQ": "NASDAQ_1X_LONG_QQQ_REPLACEMENT",
    "US.TQQQ": "NASDAQ_3X_LONG",
    "US.SQQQ": "NASDAQ_3X_INVERSE_LONG",
}
SWITCH_MODES = ("OFF", "SHADOW", "PAPER", "LIVE", "FLATTEN_ONLY")
ENTRY_ACTIONS = ("ENTER_LONG", "REBALANCE_LONG")
EXIT_ACTIONS = ("EXIT",)
ALL_ACTIONS = ENTRY_ACTIONS + EXIT_ACTIONS + ("HOLD",)
LIVE_CONFIRMATION_EXPECTED = "I_ACCEPT_REAL_MONEY_EQUITY_EXECUTION"


class ComponentError(RuntimeError):
    pass


@dataclass(frozen=True)
class StrategyDecision:
    action: str = "HOLD"
    symbol: str | None = None
    target_notional_usd: float = 0.0
    confidence: float = 0.0
    reason_code: str = "NO_STRATEGY_SIGNAL"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkMetrics:
    status: str
    observation_count: int
    strategy_return: float | None
    qqq_return: float | None
    excess_return: float | None
    underperformance_threshold: float
    block_new_entries: bool
    reason_code: str


@dataclass(frozen=True)
class Authorization:
    switch_mode: str
    requested_action: str
    broker_action_allowed: bool
    order_intent_allowed: bool
    new_entry_allowed: bool
    exit_allowed: bool
    effective_mode: str
    reason_code: str
    checks: dict[str, bool]


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    action: str
    side: str
    symbol: str
    quantity: int
    order_type: str
    limit_price: float | None
    notional_usd: float
    reason_code: str
    strategy_reason_code: str
    benchmark_symbol: str
    benchmark_status: str
    created_at_utc: str


@dataclass
class RuntimeState:
    schema_version: int = 1
    samples: list[dict[str, Any]] = field(default_factory=list)
    cycle_count: int = 0
    last_cycle_at_utc: str = ""
    last_decision_action: str = "HOLD"
    last_decision_symbol: str = ""
    last_intent_id: str = ""
    benchmark_pause_active: bool = False


DEFAULT_CONFIG: dict[str, Any] = {
    "component": {
        "enabled": True,
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "allowed_execution_symbols": list(ALLOWED_EXECUTION_SYMBOLS),
        "symbol_roles": SYMBOL_ROLES,
    },
    "risk": {
        "account_reference_usd": 400.0,
        "max_open_positions": 1,
        "max_order_notional_usd": 120.0,
        "max_gross_exposure_usd": 120.0,
        "max_daily_loss_usd": 6.0,
        "max_weekly_loss_usd": 16.0,
        "allow_fractional": False,
        "market_orders_allowed": False,
        "margin_allowed": False,
        "short_selling_allowed": False,
        "options_allowed": False,
        "averaging_down_allowed": False,
        "max_quote_age_seconds": 15.0,
        "max_spread_ratio": 0.006,
    },
    "benchmark": {
        "primary_metric": "STRATEGY_NAV_RETURN_MINUS_QQQ_BUY_AND_HOLD_RETURN",
        "underperformance_pause_enabled": True,
        "underperformance_threshold_pct": -0.02,
        "recovery_threshold_pct": -0.005,
        "minimum_observations": 20,
        "lookback_observations": 390,
    },
    "strategy_plugin": {
        "path": "scripts/v22/v22_047_r1b_strategy_plugin_template.py",
        "entrypoint": "generate_decision",
        "parameters": {},
    },
    "control": {
        "default_switch_mode": "OFF",
        "require_execute_flag_for_broker_action": True,
        "require_live_environment_confirmation": True,
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def read_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise ComponentError(f"FILE_NOT_FOUND:{path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComponentError(f"INVALID_JSON:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise ComponentError(f"JSON_ROOT_MUST_BE_OBJECT:{path}")
    return payload


def load_config(path: Path | None) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path is not None and path.exists():
        config = deep_merge(config, read_json(path))
    validate_config(config)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    component = config.get("component", {})
    benchmark_symbol = component.get("benchmark_symbol")
    allowed = tuple(component.get("allowed_execution_symbols", []))
    if benchmark_symbol != BENCHMARK_SYMBOL:
        raise ComponentError("BENCHMARK_SYMBOL_IS_IMMUTABLE_US_QQQ")
    if allowed != ALLOWED_EXECUTION_SYMBOLS:
        raise ComponentError("EXECUTION_SYMBOL_SCOPE_MUST_BE_EXACTLY_IQQ_TQQQ_SQQQ")
    risk = config.get("risk", {})
    if float(risk.get("max_order_notional_usd", 0)) <= 0:
        raise ComponentError("MAX_ORDER_NOTIONAL_MUST_BE_POSITIVE")
    if int(risk.get("max_open_positions", 0)) != 1:
        raise ComponentError("R1B_REQUIRES_SINGLE_POSITION")
    if bool(risk.get("market_orders_allowed")):
        raise ComponentError("MARKET_ORDERS_MUST_REMAIN_DISABLED")
    if bool(risk.get("margin_allowed")) or bool(risk.get("short_selling_allowed")) or bool(risk.get("options_allowed")):
        raise ComponentError("MARGIN_SHORT_OPTIONS_MUST_REMAIN_DISABLED")


def default_switch_state(default_mode: str = "OFF") -> dict[str, Any]:
    mode = default_mode.upper()
    if mode not in SWITCH_MODES:
        mode = "OFF"
    return {
        "schema_version": 1,
        "mode": mode,
        "updated_at_utc": utc_now_iso(),
        "updated_by": "INITIALIZER",
        "note": "Default fail-closed state",
    }


def read_switch_state(path: Path, default_mode: str = "OFF") -> dict[str, Any]:
    if not path.exists():
        state = default_switch_state(default_mode)
        atomic_write_json(path, state)
        return state
    state = read_json(path)
    mode = str(state.get("mode", "OFF")).upper()
    if mode not in SWITCH_MODES:
        raise ComponentError(f"INVALID_SWITCH_MODE:{mode}")
    state["mode"] = mode
    return state


def set_switch_state(path: Path, mode: str, note: str, updated_by: str, confirm_live: bool) -> dict[str, Any]:
    normalized = mode.upper()
    if normalized not in SWITCH_MODES:
        raise ComponentError(f"INVALID_SWITCH_MODE:{normalized}")
    if normalized == "LIVE" and not confirm_live:
        raise ComponentError("LIVE_SWITCH_REQUIRES_EXPLICIT_CONFIRMATION")
    state = {
        "schema_version": 1,
        "mode": normalized,
        "updated_at_utc": utc_now_iso(),
        "updated_by": updated_by or "LOCAL_USER",
        "note": note or "",
    }
    atomic_write_json(path, state)
    return state


def load_runtime_state(path: Path) -> RuntimeState:
    if not path.exists():
        return RuntimeState()
    payload = read_json(path)
    known = {field_name for field_name in RuntimeState.__dataclass_fields__}
    filtered = {k: v for k, v in payload.items() if k in known}
    state = RuntimeState(**filtered)
    if not isinstance(state.samples, list):
        state.samples = []
    return state


def load_strategy_callable(plugin_path: Path, entrypoint: str) -> Callable[[dict[str, Any]], Mapping[str, Any]]:
    if not plugin_path.exists():
        raise ComponentError(f"STRATEGY_PLUGIN_NOT_FOUND:{plugin_path}")
    module_name = f"v22_047_r1b_strategy_{abs(hash(str(plugin_path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        raise ComponentError(f"STRATEGY_PLUGIN_LOAD_FAILED:{plugin_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    func = getattr(module, entrypoint, None)
    if not callable(func):
        raise ComponentError(f"STRATEGY_ENTRYPOINT_NOT_CALLABLE:{entrypoint}")
    return func


def parse_strategy_decision(payload: Mapping[str, Any]) -> StrategyDecision:
    if not isinstance(payload, Mapping):
        raise ComponentError("STRATEGY_DECISION_MUST_BE_OBJECT")
    action = str(payload.get("action", "HOLD")).upper()
    symbol_raw = payload.get("symbol")
    symbol = str(symbol_raw).upper() if symbol_raw not in (None, "") else None
    decision = StrategyDecision(
        action=action,
        symbol=symbol,
        target_notional_usd=float(payload.get("target_notional_usd", 0.0) or 0.0),
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        reason_code=str(payload.get("reason_code", "UNSPECIFIED")),
        metadata=dict(payload.get("metadata", {}) or {}),
    )
    if decision.action not in ALL_ACTIONS:
        raise ComponentError(f"INVALID_STRATEGY_ACTION:{decision.action}")
    if decision.action in ENTRY_ACTIONS:
        if decision.symbol not in ALLOWED_EXECUTION_SYMBOLS:
            raise ComponentError(f"INVALID_EXECUTION_SYMBOL:{decision.symbol}")
        if decision.target_notional_usd <= 0:
            raise ComponentError("ENTRY_REQUIRES_POSITIVE_TARGET_NOTIONAL")
    if not 0.0 <= decision.confidence <= 1.0:
        raise ComponentError("CONFIDENCE_OUT_OF_RANGE")
    return decision


def normalize_position_map(account: Mapping[str, Any]) -> dict[str, float]:
    positions = account.get("positions", {})
    result = {symbol: 0.0 for symbol in ALLOWED_EXECUTION_SYMBOLS}
    if isinstance(positions, Mapping):
        for symbol in ALLOWED_EXECUTION_SYMBOLS:
            value = positions.get(symbol, 0.0)
            if isinstance(value, Mapping):
                value = value.get("qty", 0.0)
            result[symbol] = float(value or 0.0)
    elif isinstance(positions, list):
        for item in positions:
            if not isinstance(item, Mapping):
                continue
            symbol = str(item.get("symbol", "")).upper()
            if symbol in result:
                result[symbol] = float(item.get("qty", 0.0) or 0.0)
    return result


def validate_snapshots(market: Mapping[str, Any], account: Mapping[str, Any], config: Mapping[str, Any]) -> None:
    benchmark = market.get("benchmark", {})
    if str(benchmark.get("symbol", "")).upper() != BENCHMARK_SYMBOL:
        raise ComponentError("MARKET_SNAPSHOT_BENCHMARK_MUST_BE_US_QQQ")
    qqq_last = float(benchmark.get("last", 0.0) or 0.0)
    if qqq_last <= 0:
        raise ComponentError("QQQ_LAST_PRICE_INVALID")
    nav = float(account.get("net_liquidation_value_usd", 0.0) or 0.0)
    if nav <= 0:
        raise ComponentError("ACCOUNT_NAV_INVALID")
    quotes = market.get("execution_quotes", {})
    if not isinstance(quotes, Mapping):
        raise ComponentError("EXECUTION_QUOTES_MUST_BE_OBJECT")
    max_age = float(config["risk"]["max_quote_age_seconds"])
    max_spread = float(config["risk"]["max_spread_ratio"])
    for symbol in ALLOWED_EXECUTION_SYMBOLS:
        quote = quotes.get(symbol)
        if quote is None:
            continue
        if not isinstance(quote, Mapping):
            raise ComponentError(f"QUOTE_MUST_BE_OBJECT:{symbol}")
        bid = float(quote.get("bid", 0.0) or 0.0)
        ask = float(quote.get("ask", 0.0) or 0.0)
        age = float(quote.get("age_seconds", 0.0) or 0.0)
        if bid <= 0 or ask <= 0 or ask < bid:
            raise ComponentError(f"INVALID_QUOTE:{symbol}")
        mid = (bid + ask) / 2.0
        spread_ratio = (ask - bid) / mid if mid > 0 else math.inf
        if age > max_age:
            raise ComponentError(f"STALE_QUOTE:{symbol}")
        if spread_ratio > max_spread:
            raise ComponentError(f"SPREAD_TOO_WIDE:{symbol}")


def compute_benchmark_metrics(state: RuntimeState, nav: float, qqq_last: float, config: Mapping[str, Any]) -> BenchmarkMetrics:
    benchmark_cfg = config["benchmark"]
    lookback = max(2, int(benchmark_cfg["lookback_observations"]))
    min_obs = max(2, int(benchmark_cfg["minimum_observations"]))
    threshold = float(benchmark_cfg["underperformance_threshold_pct"])
    samples = (state.samples + [{"nav": nav, "qqq": qqq_last}])[-lookback:]
    if len(samples) < min_obs:
        return BenchmarkMetrics(
            status="INSUFFICIENT_DATA",
            observation_count=len(samples),
            strategy_return=None,
            qqq_return=None,
            excess_return=None,
            underperformance_threshold=threshold,
            block_new_entries=False,
            reason_code="BENCHMARK_MIN_OBSERVATIONS_NOT_REACHED",
        )
    first = samples[0]
    start_nav = float(first.get("nav", 0.0) or 0.0)
    start_qqq = float(first.get("qqq", 0.0) or 0.0)
    if start_nav <= 0 or start_qqq <= 0:
        raise ComponentError("BENCHMARK_BASELINE_INVALID")
    strategy_return = nav / start_nav - 1.0
    qqq_return = qqq_last / start_qqq - 1.0
    excess = strategy_return - qqq_return
    enabled = bool(benchmark_cfg.get("underperformance_pause_enabled", True))
    recovery_threshold = float(benchmark_cfg.get("recovery_threshold_pct", threshold))
    if not enabled:
        block = False
    elif state.benchmark_pause_active:
        block = excess < recovery_threshold
    else:
        block = excess < threshold
    if block:
        status = "UNDERPERFORMING_QQQ"
        reason = "STRATEGY_TRAILS_QQQ_BENCHMARK_GUARD_ACTIVE"
    elif state.benchmark_pause_active and excess >= recovery_threshold:
        status = "QQQ_BENCHMARK_GUARD_RECOVERED"
        reason = "STRATEGY_RECOVERED_TO_QQQ_REENTRY_THRESHOLD"
    elif excess > 0:
        status = "OUTPERFORMING_QQQ"
        reason = "STRATEGY_AHEAD_OF_QQQ"
    else:
        status = "MATCHING_OR_SLIGHTLY_TRAILING_QQQ"
        reason = "WITHIN_ALLOWED_QQQ_GAP"
    return BenchmarkMetrics(
        status=status,
        observation_count=len(samples),
        strategy_return=strategy_return,
        qqq_return=qqq_return,
        excess_return=excess,
        underperformance_threshold=threshold,
        block_new_entries=block,
        reason_code=reason,
    )


def build_authorization(
    switch_mode: str,
    decision: StrategyDecision,
    account: Mapping[str, Any],
    benchmark: BenchmarkMetrics,
    config: Mapping[str, Any],
    *,
    execute_requested: bool,
    live_confirmation: str,
) -> Authorization:
    risk = config["risk"]
    positions = normalize_position_map(account)
    held = {symbol: qty for symbol, qty in positions.items() if qty > 0}
    open_position_count = len(held)
    daily_pnl = float(account.get("realized_pnl_today_usd", 0.0) or 0.0)
    weekly_pnl = float(account.get("realized_pnl_week_usd", 0.0) or 0.0)
    has_open_orders = int(account.get("open_order_count", 0) or 0) > 0
    is_entry = decision.action in ENTRY_ACTIONS
    is_exit = decision.action in EXIT_ACTIONS
    component_enabled = bool(config["component"].get("enabled", True))

    checks = {
        "component_enabled": component_enabled,
        "switch_known": switch_mode in SWITCH_MODES,
        "decision_valid": decision.action in ALL_ACTIONS,
        "symbol_allowed": decision.symbol in ALLOWED_EXECUTION_SYMBOLS if is_entry else True,
        "single_position_scope": open_position_count <= int(risk["max_open_positions"]),
        "no_open_orders": not has_open_orders,
        "daily_loss_guard": daily_pnl > -float(risk["max_daily_loss_usd"]),
        "weekly_loss_guard": weekly_pnl > -float(risk["max_weekly_loss_usd"]),
        "benchmark_guard": not benchmark.block_new_entries,
        "execute_flag": execute_requested,
        "live_confirmation": live_confirmation == LIVE_CONFIRMATION_EXPECTED,
    }

    exit_allowed = is_exit and open_position_count > 0 and component_enabled and not has_open_orders
    new_entry_allowed = (
        is_entry
        and component_enabled
        and not held
        and all(
            checks[key]
            for key in (
                "symbol_allowed",
                "single_position_scope",
                "no_open_orders",
                "daily_loss_guard",
                "weekly_loss_guard",
                "benchmark_guard",
            )
        )
    )

    if switch_mode == "OFF":
        return Authorization(switch_mode, decision.action, False, False, False, False, "OFF", "AUTOMATION_SWITCH_OFF", checks)
    if switch_mode == "SHADOW":
        allowed = new_entry_allowed or exit_allowed
        return Authorization(switch_mode, decision.action, False, allowed, new_entry_allowed, exit_allowed, "SHADOW", "SHADOW_PLAN_ONLY", checks)
    if switch_mode == "FLATTEN_ONLY":
        broker_allowed = execute_requested and checks["live_confirmation"] and exit_allowed
        reason = "FLATTEN_ONLY_BROKER_EXIT_ALLOWED" if broker_allowed else "ONLY_EXISTING_POSITION_EXIT_INTENT_ALLOWED"
        return Authorization(switch_mode, decision.action, broker_allowed, exit_allowed, False, exit_allowed, "FLATTEN_ONLY", reason, checks)
    if switch_mode == "PAPER":
        broker_allowed = execute_requested and (new_entry_allowed or exit_allowed)
        reason = "PAPER_BROKER_ACTION_ALLOWED" if broker_allowed else "PAPER_EXECUTE_OR_RISK_GATE_BLOCKED"
        return Authorization(switch_mode, decision.action, broker_allowed, new_entry_allowed or exit_allowed, new_entry_allowed, exit_allowed, "PAPER", reason, checks)
    if switch_mode == "LIVE":
        broker_allowed = execute_requested and checks["live_confirmation"] and (new_entry_allowed or exit_allowed)
        reason = "LIVE_BROKER_ACTION_ALLOWED" if broker_allowed else "LIVE_CONFIRMATION_EXECUTE_OR_RISK_GATE_BLOCKED"
        return Authorization(switch_mode, decision.action, broker_allowed, new_entry_allowed or exit_allowed, new_entry_allowed, exit_allowed, "LIVE" if broker_allowed else "LIVE_BLOCKED", reason, checks)
    raise ComponentError(f"UNHANDLED_SWITCH_MODE:{switch_mode}")


def choose_limit_price(symbol: str, side: str, market: Mapping[str, Any]) -> float:
    quote = market["execution_quotes"].get(symbol)
    if not isinstance(quote, Mapping):
        raise ComponentError(f"QUOTE_MISSING_FOR_ORDER:{symbol}")
    bid = float(quote["bid"])
    ask = float(quote["ask"])
    return round(ask if side == "BUY" else bid, 4)


def build_order_intent(
    decision: StrategyDecision,
    authorization: Authorization,
    market: Mapping[str, Any],
    account: Mapping[str, Any],
    benchmark: BenchmarkMetrics,
    config: Mapping[str, Any],
) -> OrderIntent | None:
    if not authorization.order_intent_allowed:
        return None
    positions = normalize_position_map(account)
    created = utc_now_iso()
    intent_id = f"{REVISION}_{created.replace(':', '').replace('-', '').replace('+00:00', 'Z').replace('.', '')}"

    if decision.action in EXIT_ACTIONS:
        held = [(symbol, qty) for symbol, qty in positions.items() if qty > 0]
        if len(held) != 1:
            return None
        symbol, qty = held[0]
        quantity = int(math.floor(qty))
        if quantity <= 0:
            return None
        limit_price = choose_limit_price(symbol, "SELL", market)
        return OrderIntent(
            intent_id=intent_id,
            action="EXIT",
            side="SELL",
            symbol=symbol,
            quantity=quantity,
            order_type="LIMIT",
            limit_price=limit_price,
            notional_usd=round(quantity * limit_price, 4),
            reason_code=authorization.reason_code,
            strategy_reason_code=decision.reason_code,
            benchmark_symbol=BENCHMARK_SYMBOL,
            benchmark_status=benchmark.status,
            created_at_utc=created,
        )

    if decision.action in ENTRY_ACTIONS:
        symbol = decision.symbol
        if symbol is None:
            return None
        max_notional = float(config["risk"]["max_order_notional_usd"])
        requested = min(decision.target_notional_usd, max_notional)
        limit_price = choose_limit_price(symbol, "BUY", market)
        available_cash = float(account.get("available_cash_usd", 0.0) or 0.0)
        budget = min(requested, available_cash, max_notional)
        quantity = int(math.floor(budget / limit_price))
        if quantity <= 0:
            return None
        return OrderIntent(
            intent_id=intent_id,
            action=decision.action,
            side="BUY",
            symbol=symbol,
            quantity=quantity,
            order_type="LIMIT",
            limit_price=limit_price,
            notional_usd=round(quantity * limit_price, 4),
            reason_code=authorization.reason_code,
            strategy_reason_code=decision.reason_code,
            benchmark_symbol=BENCHMARK_SYMBOL,
            benchmark_status=benchmark.status,
            created_at_utc=created,
        )
    return None


def resolve_plugin_path(repo_root: Path, config: Mapping[str, Any], cli_path: Path | None) -> Path:
    if cli_path is not None:
        return cli_path.resolve()
    configured = Path(str(config["strategy_plugin"]["path"]))
    return configured if configured.is_absolute() else (repo_root / configured).resolve()


def run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else repo_root / "outputs" / "v22" / "V22.047_R1B_NASDAQ_AUTO_TRADING_CONTROL_COMPONENT"
    config_path = Path(args.config_path).resolve() if args.config_path else repo_root / "config" / "v22_047_r1b_auto_trading_control.json"
    switch_path = Path(args.switch_path).resolve() if args.switch_path else output_dir / "v22_047_r1b_switch_state.json"
    runtime_path = output_dir / "v22_047_r1b_runtime_state.json"
    summary_path = output_dir / "v22_047_r1b_summary.json"
    ledger_path = output_dir / "v22_047_r1b_cycle_ledger.jsonl"
    intent_path = output_dir / "v22_047_r1b_order_intent.json"

    config = load_config(config_path)
    switch = read_switch_state(switch_path, str(config["control"]["default_switch_mode"]))
    market = read_json(Path(args.market_snapshot).resolve())
    account = read_json(Path(args.account_snapshot).resolve())
    validate_snapshots(market, account, config)
    runtime = load_runtime_state(runtime_path)

    nav = float(account["net_liquidation_value_usd"])
    qqq_last = float(market["benchmark"]["last"])
    benchmark = compute_benchmark_metrics(runtime, nav, qqq_last, config)

    plugin_path = resolve_plugin_path(repo_root, config, Path(args.strategy_plugin) if args.strategy_plugin else None)
    strategy_callable = load_strategy_callable(plugin_path, str(config["strategy_plugin"]["entrypoint"]))
    context = {
        "revision": REVISION,
        "component_name": COMPONENT_NAME,
        "timestamp_utc": utc_now_iso(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "benchmark_metrics": asdict(benchmark),
        "allowed_execution_symbols": list(ALLOWED_EXECUTION_SYMBOLS),
        "symbol_roles": SYMBOL_ROLES,
        "market": market,
        "account": account,
        "strategy_parameters": config["strategy_plugin"].get("parameters", {}),
        "switch_mode": switch["mode"],
    }
    try:
        raw_decision = strategy_callable(context)
        decision = parse_strategy_decision(raw_decision)
        strategy_error = ""
    except Exception as exc:
        decision = StrategyDecision(action="HOLD", reason_code="STRATEGY_PLUGIN_ERROR")
        strategy_error = f"{type(exc).__name__}:{exc}"

    live_confirmation = os.environ.get("V22_LIVE_EQUITY_CONFIRMATION", "")
    authorization = build_authorization(
        str(switch["mode"]),
        decision,
        account,
        benchmark,
        config,
        execute_requested=bool(args.execute),
        live_confirmation=live_confirmation,
    )
    intent = build_order_intent(decision, authorization, market, account, benchmark, config)

    runtime.samples.append({"timestamp_utc": utc_now_iso(), "nav": nav, "qqq": qqq_last})
    lookback = max(2, int(config["benchmark"]["lookback_observations"]))
    runtime.samples = runtime.samples[-lookback:]
    runtime.cycle_count += 1
    runtime.last_cycle_at_utc = utc_now_iso()
    runtime.last_decision_action = decision.action
    runtime.last_decision_symbol = decision.symbol or ""
    runtime.last_intent_id = intent.intent_id if intent else ""
    runtime.benchmark_pause_active = benchmark.block_new_entries
    atomic_write_json(runtime_path, asdict(runtime))

    if intent:
        atomic_write_json(intent_path, asdict(intent))
    elif intent_path.exists():
        intent_path.unlink()

    final_status = "PASS_V22_047_R1B_CONTROL_COMPONENT_READY"
    if strategy_error:
        final_status = "WARN_V22_047_R1B_STRATEGY_PLUGIN_ERROR_FAIL_CLOSED"
    final_decision = authorization.reason_code
    summary = {
        "revision": REVISION,
        "component_name": COMPONENT_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        "timestamp_utc": utc_now_iso(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "qqq_replacement_execution_symbol": "US.IQQ",
        "allowed_execution_symbols": list(ALLOWED_EXECUTION_SYMBOLS),
        "symbol_roles": SYMBOL_ROLES,
        "switch": switch,
        "strategy_plugin_path": str(plugin_path),
        "strategy_decision": asdict(decision),
        "strategy_error": strategy_error,
        "benchmark_metrics": asdict(benchmark),
        "authorization": asdict(authorization),
        "order_intent": asdict(intent) if intent else None,
        "order_submission_implemented": False,
        "order_submission_note": "This component gates and emits order intent; connect a separately reviewed broker executor later.",
        "config_path": str(config_path),
        "switch_path": str(switch_path),
        "runtime_state_path": str(runtime_path),
        "summary_path": str(summary_path),
    }
    atomic_write_json(summary_path, summary)
    append_jsonl(ledger_path, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{REVISION} {COMPONENT_NAME}")
    parser.add_argument("--repo-root", default=r"D:\us-tech-quant")
    parser.add_argument("--config-path")
    parser.add_argument("--output-dir")
    parser.add_argument("--switch-path")
    parser.add_argument("--market-snapshot")
    parser.add_argument("--account-snapshot")
    parser.add_argument("--strategy-plugin")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--set-switch", choices=SWITCH_MODES)
    parser.add_argument("--switch-note", default="")
    parser.add_argument("--updated-by", default="LOCAL_USER")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--show-switch", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else repo_root / "outputs" / "v22" / "V22.047_R1B_NASDAQ_AUTO_TRADING_CONTROL_COMPONENT"
    switch_path = Path(args.switch_path).resolve() if args.switch_path else output_dir / "v22_047_r1b_switch_state.json"
    try:
        if args.set_switch:
            state = set_switch_state(switch_path, args.set_switch, args.switch_note, args.updated_by, args.confirm_live)
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if args.show_switch:
            state = read_switch_state(switch_path)
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if not args.market_snapshot or not args.account_snapshot:
            parser.error("--market-snapshot and --account-snapshot are required for a cycle")
        summary = run_cycle(args)
        print(f"final_status={summary['final_status']}")
        print(f"final_decision={summary['final_decision']}")
        print(f"switch_mode={summary['switch']['mode']}")
        print(f"benchmark_status={summary['benchmark_metrics']['status']}")
        print(f"broker_action_allowed={summary['authorization']['broker_action_allowed']}")
        print(f"order_intent_created={summary['order_intent'] is not None}")
        print(f"summary_path={summary['summary_path']}")
        return 0
    except ComponentError as exc:
        print(f"final_status=FAIL_V22_047_R1B_CONTROL_COMPONENT", file=sys.stderr)
        print(f"final_decision={exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"final_status=FAIL_V22_047_R1B_UNHANDLED", file=sys.stderr)
        print(f"final_decision={type(exc).__name__}:{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
