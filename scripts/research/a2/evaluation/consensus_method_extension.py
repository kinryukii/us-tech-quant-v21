"""Explicit matrix adapter over the existing estimators and cash account.

No readers, selector, fit launcher, registry or alternate execution engine live
here. The caller supplies isolated pre-2026 inputs, a frozen matrix and durable
fit adapters. Each coordinate keeps its own USD3000 continuous account.
"""
from __future__ import annotations

import ast
import builtins
import copy
from dataclasses import dataclass, asdict
import hashlib
import inspect
import json
import textwrap
from types import FunctionType, SimpleNamespace

import numpy as np
import pandas as pd

from scripts.research.a2.risk import joint_risk_estimators as bank
from scripts.research.a2.portfolio import joint_allocation_methods as allocation
from scripts.research.a2.inference.consensus_joint_policy import ALLOCATION_METHODS as CONSENSUS_ALLOCATION_METHODS

SCHEMA = "CONSENSUS_METHOD_MATRIX_EXTENSION_R1"
BOUNDARY = pd.Timestamp("2026-01-01")
R2_METHODS = ("RD", "RM", "RB", "RH", "RT", "RR", "RU", "RE")
EXTERNAL_DECISION_METHODS = ("rl_ppo", "rl_reinforce")
CONTROLS = ("partial_rebalancing", "no_trade_band", "minimum_trade_usd")
SCENARIO_METHODS = ("mean_cvar", "mean_es", "mean_semivariance", "kelly", "log_growth")


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _before(value, cutoff=BOUNDARY):
    stamp = pd.Timestamp(value)
    bound = pd.Timestamp(cutoff)
    _require(not pd.isna(stamp) and not pd.isna(bound), "FINITE_CLOCK_REQUIRED")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    if bound.tzinfo is not None:
        bound = bound.tz_convert("UTC").tz_localize(None)
    _require(stamp < bound <= BOUNDARY, "STRICT_PRE2026_AVAILABLE_CLOCK_REQUIRED")
    return stamp


@dataclass(frozen=True)
class Coordinate:
    forecast_pack: str
    risk_combination: str
    decision_method: str

    @property
    def identity(self):
        return _digest(asdict(self))


def validate_scope(scope, coordinate=None):
    s = copy.deepcopy(scope)
    _require(s.get("schema") == SCHEMA and bool(s.get("research_id")), "MATRIX_SCOPE_REQUIRED")
    _require(s.get("selection_boundary_exclusive") == "2026-01-01"
             and s.get("initial_cash") == 3000
             and type(s.get("prior_fit_units")) is int and s["prior_fit_units"] >= 2063
             and s.get("max_fit_units") == 10000
             and s["prior_fit_units"] < s["max_fit_units"]
             and s.get("lookback_sessions") == 120
             and tuple(s.get("controls", ())) == CONTROLS, "MATRIX_ACCOUNT_OR_BUDGET_CONTRACT_CHANGED")
    _require(s.get("fee_config") == dict(one_way_all_in_bps=10., fixed_per_fill_usd=0., minimum_trade_usd=5., settlement_enabled=True),
             "ORIGINAL_ACCOUNT_FEES_REQUIRED")
    packs = s.get("forecast_packs")
    _require(isinstance(packs, list) and packs and all(isinstance(p, str) and p for p in packs)
             and len(set(packs)) == len(packs), "EXPLICIT_FORECAST_PACKS_REQUIRED")
    methods = s.get("decision_methods")
    _require(isinstance(methods, list) and methods and len(set(methods)) == len(methods)
             and set(methods) <= set(CONSENSUS_ALLOCATION_METHODS) | set(EXTERNAL_DECISION_METHODS),
             "REGISTERED_DECISION_METHODS_REQUIRED")
    combinations = s.get("risk_combinations")
    _require(isinstance(combinations, dict) and combinations, "RISK_COMBINATIONS_REQUIRED")
    for name, item in combinations.items():
        members, weights = item.get("members"), item.get("weights")
        _require(isinstance(name, str) and name and isinstance(members, list) and members
                 and len(set(members)) == len(members)
                 and set(members) <= set(bank.CONFIGS) | set(R2_METHODS),
                 "REGISTERED_UNIQUE_RISK_MEMBERS_REQUIRED")
        _require(isinstance(weights, list) and len(weights) == len(members)
                 and all(type(w) in (int, float) and np.isfinite(w) and w > 0 for w in weights)
                 and np.isclose(sum(weights), 1., rtol=0., atol=1e-12), "FROZEN_POSITIVE_RISK_WEIGHTS_REQUIRED")
    if coordinate is not None:
        _require(type(coordinate) is Coordinate and coordinate.forecast_pack in packs
                 and coordinate.risk_combination in combinations and coordinate.decision_method in methods,
                 "UNFROZEN_MATRIX_COORDINATE")
    return s


def catalogue():
    """Names/aliases describe implementation identity, never attempted status."""
    aliases = {k: v for k, v in allocation.ALIASES.items() if k != "robust_cost_aware"}
    # This name includes the owner's separate hard account-target control.
    aliases.pop("turnover_limit", None)
    return dict(bank_methods=list(bank.CONFIGS), r2_methods=list(R2_METHODS),
                decision_methods=list(CONSENSUS_ALLOCATION_METHODS) + list(EXTERNAL_DECISION_METHODS),
                external_policy_factory_required=list(EXTERNAL_DECISION_METHODS),
                exact_owner_decision_aliases=aliases,
                exact_same_input_risk_aliases={"HISTVOL": "DIAG"},
                attempted=False)


def risk_fit_unit_upper(method, n_assets=None):
    """Bank owner: preprocessing + its actual estimator-state recipe."""
    method = bank.canonical_method(method)
    return 4 if method in ("SINGLE_INDEX", "INDUSTRY", "FUNDAMENTAL") else (
        3 if method in ("GARCH", "GJR_GARCH", "COV_ENSEMBLE") else 2)


def risk_fit_worker(pipe, operation, model_id, x, y, dates, quantile, dependencies, features, observed):
    """Canonical spawn target; reserve/ACK every physical state before fitting."""
    try:
        _require(operation == "risk" and model_id in bank.CONFIGS, "REGISTERED_BANK_RISK_OPERATION_REQUIRED")
        _require(isinstance(x, pd.DataFrame) and isinstance(x.index, pd.DatetimeIndex)
                 and not x.empty and x.index.is_unique and x.index.is_monotonic_increasing,
                 "ISOLATED_CAUSAL_RISK_FRAME_REQUIRED")
        _before(x.index.max(), observed["fit_cutoff"])
        for unit in range(risk_fit_unit_upper(model_id, x.shape[1])):
            pipe.send(("FIT_START", "MATRIX_RISK_STATE_ATTEMPT_" + str(unit + 1)))
            _require(pipe.recv() is True, "GLOBAL_FIT_BUDGET_REJECTED")
        dependency = dependencies if isinstance(dependencies, dict) else {}
        result = bank.fit_risk_estimator(model_id, x,
            market_returns=dependency.get("market_returns"),
            exposure_frame=dependency.get("exposure_frame"), params=observed)
        _require(result.budget["total_state_estimations"] <= risk_fit_unit_upper(model_id),
                 "ACTUAL_RISK_BUDGET_EXCEEDS_RESERVED_ATTEMPTS")
        _require(all(pd.Timestamp(d) < pd.Timestamp(observed["fit_cutoff"]) <= BOUNDARY
                     for d in result.fitted_dates), "RISK_FIT_CLOCK_CHANGED")
        pipe.send(("RESULT", result, dict(actual_bundle_budget=result.budget, status=result.status,
                                         failed_reason=result.failure_reason,
                                         reservation="CONSERVATIVE_PHYSICAL_ATTEMPT_UPPER; NO_REFUND")))
    except BaseException as error:
        pipe.send(("ERROR", type(error).__name__, str(error)))
    finally:
        pipe.close()


def _data_hash(value):
    if value is None:
        return None
    if isinstance(value, (pd.Series, pd.DataFrame)):
        return _digest(dict(values=hashlib.sha256(pd.util.hash_pandas_object(value, index=True).to_numpy().tobytes()).hexdigest(),
                            columns=list(map(str, value.columns)) if isinstance(value, pd.DataFrame) else [str(value.name)],
                            attrs=value.attrs))
    raise ValueError("TYPED_RISK_DEPENDENCY_REQUIRED")


def _risk_dependency(method, cutoff, assets, provider):
    if method not in ("SINGLE_INDEX", "INDUSTRY", "FUNDAMENTAL"):
        return {}
    dependency = {} if provider is None else provider(method, cutoff, tuple(assets))
    _require(isinstance(dependency, dict), "RISK_DEPENDENCY_MAPPING_REQUIRED")
    # A missing source is handed to the numerical owner's genuine BLOCKED_INPUT
    # path; a present source needs its own exact provenance and availability.
    for name in ("market_returns", "exposure_frame"):
        value = dependency.get(name)
        if value is not None:
            _require(isinstance(dependency.get("source_refs"), dict) and dependency["source_refs"],
                     "QUALIFIED_DEPENDENCY_SOURCE_REFS_REQUIRED")
            _before(dependency["available_at"], cutoff)
            if name == "market_returns":
                _require(isinstance(value, pd.Series) and isinstance(value.index, pd.DatetimeIndex)
                         and not value.index.empty, "ISOLATED_MARKET_RETURN_SERIES_REQUIRED")
                _before(value.index.max(), cutoff)
    return dependency


def _participating_assets(ctx):
    """Proof from the account's masks, independent of labels/scenario coverage."""
    assets = tuple(ctx.tickers)
    units = np.asarray(ctx.current_units, float)
    _require(units.ndim == 2 and units.shape[1] == len(assets)
             and np.isfinite(units).all() and (units >= 0).all(), "EXACT_CASH_ACCOUNT_UNITS_REQUIRED")
    participating = units != 0.
    for name in ("decision_mask", "reserved_mask", "operational_mask"):
        mask = np.asarray(getattr(ctx, name), bool)
        _require(mask.shape == units.shape, "EXACT_ACCOUNT_PARTICIPATION_MASK_REQUIRED")
        participating |= mask
    required = participating.any(axis=0)
    return tuple(a for a, active in zip(assets, required) if active)


def _qualified_vector(mapping, date, assets, *, scenario, required_assets=None, decision_as_of=None,
                      return_metadata=False):
    account = tuple(assets)
    required = account if required_assets is None else tuple(required_assets)
    # Providers receive the account proof before reading dated UIDs or labels.
    # Legacy prequalified mappings retain exactly the same date lookup.
    item = mapping(date, account, required) if callable(mapping) else (
        None if mapping is None else mapping.get(date))
    if item is None:
        return (None, None) if return_metadata else None
    _require(isinstance(item, dict) and item.get("source_refs"), "QUALIFIED_ACCOUNT_INPUT_REFS_REQUIRED")
    estimated = tuple(item.get("assets", ()))
    _require(estimated and len(set(estimated)) == len(estimated)
             and estimated == tuple(a for a in account if a in set(estimated)),
             "EXACT_ORDERED_ACCOUNT_INPUT_ASSET_DOMAIN_REQUIRED")
    missing = tuple(a for a in account if a not in set(estimated))
    _require(set(required) <= set(estimated), "ALL_ACTIVE_HELD_LOCKED_INPUT_ASSETS_REQUIRED")
    if missing:
        _require(tuple(item.get("account_assets", ())) == account
                 and tuple(item.get("inactive_zero_padding_assets", ())) == missing
                 and not set(missing) & set(required), "EXPLICIT_PROVEN_INACTIVE_ZERO_PADDING_REQUIRED")
    if not scenario and "decision_as_of" in item:
        declared, actual, available = map(pd.Timestamp, (item["decision_as_of"], decision_as_of, item["available_at"]))
        _require(all(t.tzinfo is not None for t in (declared, actual, available)),
                 "EXPLICIT_AWARE_REFERENCE_DECISION_ASOF_REQUIRED")
        _before(actual)
        _require(declared.tz_convert("UTC") == actual.tz_convert("UTC")
                 and available.tz_convert("UTC") <= actual.tz_convert("UTC"),
                 "REFERENCE_AVAILABLE_BY_EXACT_CURRENT_SIGNAL_ASOF_REQUIRED")
    else:
        _before(item["available_at"], date)
    if scenario:
        _before(item["label_mature_max"], date)
        _require(item.get("unit") == "FIVE_SESSION_NEXT_OPEN_SHAREHOLDER_VALUE_RETURN",
                 "GENUINE_SHAREHOLDER_H5_SCENARIOS_REQUIRED")
    values = np.asarray(item["values"], float)
    _require(np.isfinite(values).all() and (
        values.ndim == 2 and values.shape[0] >= 30 and values.shape[1] == len(estimated) if scenario
        else values.shape == (len(estimated),) and np.all(values >= 0) and values.sum() > 0),
        "INVALID_MATURE_SCENARIOS_OR_FROZEN_REFERENCE")
    result = np.zeros((len(values), len(account)) if scenario else (len(account),), float)
    destinations = [account.index(a) for a in estimated]
    if scenario: result[:, destinations] = values
    else: result[destinations] = values
    detail = dict(estimated_assets=estimated, scenario_assets=estimated if scenario else None,
                  required_active_held_locked_assets=required, inactive_zero_padding_assets=missing,
                  padding_proof="EXACT_ZERO_UNITS_AND_FALSE_DECISION_RESERVED_OPERATIONAL_MASKS",
                  source_refs=copy.deepcopy(item["source_refs"]))
    return (result, detail) if return_metadata else result


def _clone(function, namespace):
    result = FunctionType(function.__code__, namespace, function.__name__,
                          function.__defaults__, function.__closure__)
    result.__kwdefaults__ = copy.deepcopy(function.__kwdefaults__)
    return result


def _transition_adapter(base):
    """Instrument the existing AST compiler; retain every account operation."""
    compiler_ns = dict(base._project_allocator.__globals__)
    compiler_ns["_allocator_template_cache"] = None

    def capture_compile(tree, filename, mode, *args, **kwargs):
        _require(isinstance(tree, ast.Module) and len(tree.body) == 1
                 and isinstance(tree.body[0], ast.FunctionDef) and tree.body[0].name == "allocate_q",
                 "EXACT_ALLOCATOR_COMPILER_REQUIRED")
        body = tree.body[0].body
        positions = [i for i, node in enumerate(body)
                     if isinstance(node, ast.FunctionDef) and node.name == "objective_gradient"]
        _require(len(positions) == 1, "EXACT_OWNER_OBJECTIVE_REQUIRED")
        body.insert(positions[0] + 1, ast.parse("_transition._capture_objective(objective_gradient)").body[0])
        return builtins.compile(ast.fix_missing_locations(tree), filename, mode, *args, **kwargs)

    compiler_ns["compile"] = capture_compile
    projector = _clone(base._project_allocator, compiler_ns)
    node = ast.parse(textwrap.dedent(inspect.getsource(base.allocate_transition))).body[0]
    _require(isinstance(node, ast.FunctionDef), "EXACT_ACCOUNT_TRANSITION_REQUIRED")
    node.args.kwonlyargs.append(ast.arg(arg="reference"))
    node.args.kw_defaults.append(ast.Constant(None))
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "solver"]
    _require(len(calls) == 1, "EXACT_OWNER_SOLVER_CALL_REQUIRED")
    calls[0].keywords.append(ast.keyword(arg="reference", value=ast.Name(id="reference", ctx=ast.Load())))
    utilities = [n for n in ast.walk(node) if isinstance(n, ast.FunctionDef) and n.name == "utility"]
    _require(len(utilities) == 1, "EXACT_ACCOUNT_HOLD_UTILITY_REQUIRED")
    utilities[0].body[:0] = ast.parse(
        "extension_value = _extension_utility(w)\n"
        "if extension_value is not None:\n    return extension_value").body
    tree = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    code = builtins.compile(tree, base.allocate_transition.__code__.co_filename, "exec")
    template_ns = dict(base.allocate_transition.__globals__)
    exec(code, template_ns)
    template = template_ns["allocate_transition"]

    def transition(*args, **kwargs):
        captured = {}
        requested = args[0] if args else kwargs["method"]
        _require(requested not in EXTERNAL_DECISION_METHODS, "EXTERNAL_RL_METHOD_MUST_NOT_ENTER_SOLVER")
        def rules_factory(current, locked, nav, cash, fee, method="cost_aware"):
            rules = base._TransitionRules(current, locked, nav, cash, fee,
                                          "erc" if method == "risk_budgeting" else method)
            rules._capture_objective = lambda fn: captured.update(objective=fn)
            return rules
        def utility(w):
            objective = captured.get("objective")
            # Every pre-existing decision keeps its original hold comparison.
            if objective is None or requested in base.CANDIDATE_ALLOCATIONS:
                return None
            try:
                return -float(objective(w)[0])
            except allocation.AllocationUnavailable as error:
                # Same domain convention as the existing ERC hold comparison:
                # risk-parity utility is undefined at a zero-risk all-cash hold.
                if requested == "risk_budgeting" and str(error) == "NONPOSITIVE_RISK_BUDGET_VARIANCE":
                    return -np.inf
                raise
        namespace = dict(template_ns, CANDIDATE_ALLOCATIONS=CONSENSUS_ALLOCATION_METHODS,
                         _TransitionRules=rules_factory, _project_allocator=projector,
                         _extension_utility=utility)
        return _clone(template, namespace)(*args, **kwargs)
    return transition


def bind_joint(base_joint, *, scope, coordinate, bank_fit, bank_dependencies=None,
               r2_fit=None, scenarios=None, references=None, external_policy_factory=None):
    """Private joint namespace. All forecasts remain supplied by the caller."""
    frozen = validate_scope(scope, coordinate)
    external = coordinate.decision_method in EXTERNAL_DECISION_METHODS
    _require(not external or callable(external_policy_factory), "EXPLICIT_EXTERNAL_RL_POLICY_FACTORY_REQUIRED")
    _require(callable(bank_fit), "DURABLE_BANK_FIT_ADAPTER_REQUIRED")
    transition = _transition_adapter(base_joint)
    chosen = frozen["risk_combinations"][coordinate.risk_combination]
    scope_identity = _digest(frozen)

    class MatrixConfig(base_joint.PolicyConfig):
        def __post_init__(self):
            _require(self.risk_method == coordinate.risk_combination
                     and self.allocation_method == coordinate.decision_method
                     and self.lookback_sessions == frozen["lookback_sessions"]
                     and tuple(self.controls) == CONTROLS, "MATRIX_CONFIG_COORDINATE_CHANGED")

    class MatrixPolicy(base_joint.ConsensusJointPolicy):
        def __init__(self, forecasts, past_daily_returns, **kwargs):
            config = kwargs.pop("config", None) or MatrixConfig(
                coordinate.risk_combination, coordinate.decision_method, frozen["lookback_sessions"])
            _require(isinstance(config, MatrixConfig), "BOUND_MATRIX_POLICY_CONFIG_REQUIRED")
            _require(kwargs.get("fee_config", base_joint.FeeConfig()) == base_joint.FeeConfig(**frozen["fee_config"]),
                     "MATRIX_FEE_CONFIG_CHANGED")
            _require(isinstance(past_daily_returns.index, pd.DatetimeIndex) and not past_daily_returns.empty,
                     "ISOLATED_PRE2026_RETURNS_REQUIRED")
            _before(past_daily_returns.index.max())
            dates = pd.to_datetime(forecasts["signal_date"])
            _require(not dates.empty, "ISOLATED_FORECASTS_REQUIRED")
            _before(dates.max())
            super().__init__(forecasts, past_daily_returns, config=config, **kwargs)
            self.matrix_coordinate = asdict(coordinate)
            self._context_assets = tuple(map(str, past_daily_returns.columns))
            self._scenario_mapping, self._reference_mapping = scenarios, references
            self._external_policy = self._external_owner = None
            if external:
                owner_kwargs = dict(kwargs)
                owner_kwargs.pop("fee_config", None)
                self._external_policy = external_policy_factory(coordinate.decision_method,
                    forecasts, past_daily_returns, config=config, fee_config=self.fee_config, **owner_kwargs)
                _require(callable(self._external_policy), "CALLABLE_EXTERNAL_RL_POLICY_REQUIRED")
                self._external_owner = getattr(self._external_policy, "base_policy", self._external_policy)
                _require(all(hasattr(self._external_owner, name) for name in
                    ("diagnostics", "risk_cache", "monthly_state_keys", "_risk", "fee_config")),
                    "EXTERNAL_POLICY_ACCOUNT_OWNER_METADATA_REQUIRED")
                _require(self._external_owner.fee_config == self.fee_config,
                         "EXTERNAL_POLICY_ACCOUNT_FEES_CHANGED")
                for name in ("diagnostics", "risk_cache", "monthly_state_keys"):
                    setattr(self, name, getattr(self._external_owner, name))

        def _risk(self, date, tickers, *, fit_assets=None, allow_final_fit=False):
            if self._external_owner is not None:
                return self._external_owner._risk(date, tickers, fit_assets=fit_assets, allow_final_fit=allow_final_fit)
            cutoff = pd.Timestamp(date)
            if cutoff.tzinfo is not None:
                cutoff = cutoff.tz_convert("UTC").tz_localize(None)
            _require(cutoff <= BOUNDARY and (cutoff < BOUNDARY or allow_final_fit),
                     "MATRIX_FINAL_PRE2026_FREEZE_REQUIRED")
            assets = tuple(sorted(set(tickers if fit_assets is None else fit_assets)))
            month = cutoff.to_period("M").start_time
            monthly_key = month
            if monthly_key not in self.monthly_state_keys:
                member_keys = []
                for requested in chosen["members"]:
                    if requested in R2_METHODS:
                        _require(callable(r2_fit), "TYPED_R2_FIT_ADAPTER_REQUIRED")
                        bundle, cache_key = r2_fit(requested, cutoff=cutoff, assets=assets)
                        self.risk_cache[cache_key] = bundle
                    else:
                        method = "DIAG" if requested == "HISTVOL" else requested
                        columns = [a for a in assets if a in self.returns.columns]
                        past = self.returns.loc[self.returns.index < cutoff, columns].tail(self.config.lookback_sessions)
                        dependency = _risk_dependency(method, cutoff, columns, bank_dependencies)
                        fingerprint = hashlib.sha256(pd.util.hash_pandas_object(past, index=True).to_numpy().tobytes())
                        fingerprint.update(repr(tuple(map(str, past.columns))).encode())
                        fingerprint.update(_digest(dict(fit_assets=assets, source_metadata=self.returns.attrs)).encode())
                        if dependency:
                            fingerprint.update(_digest(dict(source_refs=dependency.get("source_refs"),
                                market=_data_hash(dependency.get("market_returns")),
                                exposure=_data_hash(dependency.get("exposure_frame")))).encode())
                        cache_key = (month, method, self.config.lookback_sessions, fingerprint.hexdigest())
                        if cache_key not in self.risk_cache:
                            event = dict(method=method, cutoff=cutoff.isoformat(), month=month.isoformat(),
                                         assets=columns, input_sha256=fingerprint.hexdigest())
                            if self.on_risk_fit_started is not None:
                                self.on_risk_fit_started(copy.deepcopy(event))
                            bundle = bank_fit(method, past, params=dict(fit_cutoff=cutoff,
                                return_unit="DAILY_DECIMAL_RETURN", return_horizon_sessions=1,
                                source_id=self.returns.attrs.get("source_id", "UNKNOWN"),
                                information_set_id="CAUSAL_MATURE_DAILY_RETURNS_PRE2026"),
                                dependencies=dependency, event=copy.deepcopy(event))
                            _require(isinstance(bundle, bank.RiskBundle), "CANONICAL_RISK_BUNDLE_REQUIRED")
                            self.risk_cache[cache_key] = bundle
                    member_keys.append((requested, cache_key))
                self.monthly_state_keys[monthly_key] = member_keys
            covariance = None
            metadata = []
            for weight, (requested, key) in zip(chosen["weights"], self.monthly_state_keys[monthly_key]):
                bundle = self.risk_cache[key]
                fitted_cutoff = pd.Timestamp(bundle.specification["fit_cutoff"])
                if fitted_cutoff.tzinfo is not None:
                    fitted_cutoff = fitted_cutoff.tz_convert("UTC").tz_localize(None)
                compare_cutoff = cutoff.tz_convert("UTC").tz_localize(None) if cutoff.tzinfo is not None else cutoff
                _require(fitted_cutoff <= compare_cutoff,
                         "BACKWARD_DECISION_BEFORE_FROZEN_RISK_CUTOFF")
                if requested in R2_METHODS and bundle.status == "FITTED":
                    _require(set(assets) <= set(bundle.estimated_assets),
                             "R2_ACTIVE_OR_HELD_ASSET_OUTSIDE_FROZEN_ESTIMATION_DOMAIN")
                matrix, detail = bank.risk_matrix(bundle, tickers, return_metadata=True)
                scale = 1. if requested in R2_METHODS else 5.
                term = matrix * (weight * scale)
                covariance = term if covariance is None else covariance + term
                metadata.append(dict(requested=requested, weight=weight, cache_key=repr(key),
                                     covariance_horizon_sessions=5, detail=detail))
            return covariance, dict(members=metadata, combination=coordinate.risk_combination,
                scope_identity=scope_identity, risk_cache_domain=assets, horizon_sessions=5)

        def __call__(self, di, ctx):
            if self._external_policy is not None:
                decision = self._external_policy(di, ctx)
                self.last_forced_exit_assets = self._external_owner.last_forced_exit_assets
                return decision
            date = pd.Timestamp(ctx.signal_date)
            # The existing caller aligns all account tickers. Metadata must bind
            # that domain; no unknown-name zero scenarios may enter the solver.
            required = _participating_assets(ctx)
            scenario, scenario_domain = _qualified_vector(
                self._scenario_mapping if coordinate.decision_method in SCENARIO_METHODS else None,
                date, ctx.tickers, scenario=True,
                required_assets=required, decision_as_of=ctx.signal_asof, return_metadata=True)
            reference, reference_domain = _qualified_vector(
                self._reference_mapping if coordinate.decision_method in ("reference_regularization", "tracking_error") else None,
                date, ctx.tickers, scenario=False,
                required_assets=required, decision_as_of=ctx.signal_asof, return_metadata=True)
            self.scenarios[date] = scenario
            def with_reference(*args, **kwargs):
                kwargs["reference"] = reference
                return transition(*args, **kwargs)
            ns = dict(base_joint.ConsensusJointPolicy.__call__.__globals__,
                      allocate_transition=with_reference)
            diagnostic_start = len(self.diagnostics)
            decision = _clone(base_joint.ConsensusJointPolicy.__call__, ns)(self, di, ctx)
            for audit in self.diagnostics[diagnostic_start:]:
                audit["account_input_domains"] = dict(scenarios=scenario_domain, reference=reference_domain)
            if coordinate.decision_method == "turnover_limit":
                return allocation.TradingControlPolicy(lambda _di, _ctx: decision, "turnover_limit")(di, ctx)
            return decision

    namespace = dict(vars(base_joint))
    namespace.update(PolicyConfig=MatrixConfig, ConsensusJointPolicy=MatrixPolicy,
                     allocate_transition=transition, PRIMARY_RISKS=tuple(frozen["risk_combinations"]),
                     CANDIDATE_ALLOCATIONS=tuple(frozen["decision_methods"]),
                     matrix_scope=copy.deepcopy(frozen), matrix_coordinate=asdict(coordinate))
    return SimpleNamespace(**namespace)


def evaluate_flow(runner, coordinate, *args, binding, make_policy=None, **kwargs):
    """Run the original continuous-account evaluator, never a staged selector."""
    _require(binding.matrix_coordinate == asdict(coordinate), "MATRIX_BINDING_COORDINATE_CHANGED")
    source_hook = hasattr(runner, "_matrix_evaluation_source")
    guard_hook = hasattr(runner, "_matrix_execution_guard")
    _require(source_hook == guard_hook, "PAIRED_MATRIX_SOURCE_AND_EXECUTION_GUARD_REQUIRED")
    source = runner._matrix_evaluation_source if source_hook else runner.evaluate_flow
    guard = runner._matrix_execution_guard if guard_hook else None
    _require(callable(source) and (not guard_hook or callable(guard)),
             "CALLABLE_MATRIX_SOURCE_AND_EXECUTION_GUARD_REQUIRED")
    _require(not guard_hook or callable(make_policy), "GUARDED_MATRIX_EXPLICIT_POLICY_FACTORY_REQUIRED")
    node = ast.parse(textwrap.dedent(inspect.getsource(source))).body[0]
    anchors = [n for n in node.body if isinstance(n, ast.If)
               and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name)
               and n.test.left.id == "allocation_method"
               and any(isinstance(c, ast.Name) and c.id == "SCENARIO_METHODS" for c in n.test.comparators)]
    _require(len(anchors) == 1, "EXACT_EVALUATOR_SCENARIO_ANCHOR_REQUIRED")
    # Qualification is performed by MatrixPolicy with actual mature source
    # metadata; the original early blanket NT must not bypass the account.
    anchors[0].test = ast.Constant(False)
    def flow_id(method, risk_method, allocation_method, diagnostic=None, *, run=None):
        _require((method, risk_method, allocation_method) ==
                 (coordinate.forecast_pack, coordinate.risk_combination, coordinate.decision_method)
                 and diagnostic is None, "EXACT_MATRIX_COORDINATE_AND_NO_IMPLICIT_SENSITIVITY_REQUIRED")
        return "matrix__" + coordinate.identity
    ns = dict(source.__globals__, joint=binding, flow_id=flow_id,
              _matrix_coordinate=asdict(coordinate), _matrix_scope_identity=_digest(binding.matrix_scope))
    receipt_assign = next((i for i, n in enumerate(node.body)
                           if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "receipt" for t in n.targets)), None)
    _require(receipt_assign is not None, "EXACT_ACCOUNT_RECEIPT_ANCHOR_REQUIRED")
    node.body[receipt_assign+1:receipt_assign+1] = ast.parse(
        "receipt['matrix_coordinate'] = copy.deepcopy(_matrix_coordinate)\n"
        "receipt['matrix_scope_identity'] = _matrix_scope_identity").body
    if make_policy is None:
        native = runner.make_policy
        ns["make_policy"] = _clone(native, dict(native.__globals__, joint=binding,
                                                _risk_worker=risk_fit_worker))
    else:
        _require(callable(make_policy), "EXPLICIT_MATRIX_POLICY_FACTORY_REQUIRED")
        ns["make_policy"] = make_policy
    anchor = next((n for n in ast.walk(node) if isinstance(n, ast.If)
                   and isinstance(n.test, ast.Call)
                   and isinstance(n.test.func, ast.Name) and n.test.func.id == "any"
                   and any(isinstance(v, ast.Constant) and v.value == "NOT_TESTABLE_RISK_PRESERVE_UNITS"
                           for v in ast.walk(n))), None)
    _require(anchor is not None, "EXACT_ACCOUNT_QUALIFICATION_ANCHOR_REQUIRED")
    anchor.test = ast.parse(
        "any(d.get('status') in ('NOT_TESTABLE_RISK_PRESERVE_UNITS', "
        "'NOT_TESTABLE_OR_INFEASIBLE_PRESERVE_UNITS') for d in policy.diagnostics)",
        mode="eval").body
    exec(builtins.compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                          source.__code__.co_filename, "exec"), ns)
    evaluator = ns[node.name]
    if guard_hook:
        evaluator = guard(evaluator)
        _require(callable(evaluator), "CALLABLE_REAPPLIED_MATRIX_EXECUTION_GUARD_REQUIRED")
    return evaluator(*args, **kwargs)


class R2FitHook:
    """Typed original eight-direction engine with the durable budget callback.

    The engine retains its exact-input StateCache. No per-method planning cap
    is substituted for actual learned reservations, and failed keys stay spent.
    """
    def __init__(self, input_provider, *, durable_reserve, prior_fit_units=2063, max_fit_units=10000):
        from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget
        from scripts.research.a2.risk.shared_risk_engine_r2 import SharedRiskEngine
        _require(callable(input_provider) and callable(durable_reserve),
                 "TYPED_INPUT_AND_DURABLE_RESERVATION_CALLBACK_REQUIRED")
        _require(type(prior_fit_units) is int and 2063 <= prior_fit_units < max_fit_units == 10000,
                 "CUMULATIVE_R2_BUDGET_REQUIRED")
        self.input_provider = input_provider
        self.prior_fit_units = prior_fit_units
        self.budget = StateBudget(limit=max_fit_units-prior_fit_units, reserve_callback=durable_reserve)
        self.engine = SharedRiskEngine(budget=self.budget)
        self.last_reservation_delta = 0
        self.states, self.bundles, self.period_states = {}, {}, {}
        self.configuration_identity = _digest(dict(bank_specifications=bank.specs(),
            engine_definition=inspect.getsource(SharedRiskEngine)))

    def __call__(self, method, *, cutoff, assets):
        from scripts.research.a2.risk.shared_risk_budget_r2 import LEARNED_KINDS
        from scripts.research.a2.risk.shared_risk_engine_r2 import RiskInput, SCHEDULE, _calendar
        _require(method in R2_METHODS, "ORIGINAL_EIGHT_RISK_DIRECTION_REQUIRED")
        date = _before(cutoff)
        provided = self.input_provider(method, date, tuple(assets))
        if isinstance(provided, tuple) and len(provided) == 2:
            inputs, as_of = provided
        else:
            inputs, as_of = provided, cutoff
        _before(as_of)
        _require(pd.Timestamp(as_of).tzinfo is not None
                 and pd.Timestamp(as_of).tz_convert("UTC").date() == date.date(),
                 "EXPLICIT_AWARE_SIGNAL_ASOF_REQUIRED")
        _require(type(inputs) is RiskInput and tuple(inputs.assets) == tuple(assets),
                 "EXACT_TYPED_R2_ACCOUNT_ASSET_DOMAIN_REQUIRED")
        # Only already-isolated pre2026 source tables may be handed to the
        # engine. Its original stricter per-decision maturity checks still run.
        for frame in (inputs.observations, inputs.qqq_observations):
            if frame is not None:
                for field in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
                    _require(field in frame, "TYPED_R2_OBSERVATION_CLOCKS_REQUIRED")
                    _before(pd.to_datetime(frame[field], utc=True).max())
        receipts = {"stock": inputs.source_receipt}
        if method in ("RB", "RH", "RR", "RE"): receipts["QQQ"] = inputs.qqq_receipt
        if method == "RH": receipts["FF48"] = inputs.industry_receipt
        source_identity, clocks = {}, {}
        for role, receipt in receipts.items():
            if receipt is None:
                source_identity[role], clocks[role] = None, None
                continue
            identity = copy.deepcopy(receipt.cache_identity())
            # Advancing an explicit historical observation cutoff is not a new
            # physical source or scientific rule. Keep every other semantic.
            identity.get("execution_semantics", {}).pop("assumed_observation_at", None)
            semantics = asdict(receipt)
            semantics.pop("available_at")
            source_identity[role] = dict(identity=identity, receipt_semantics=semantics)
            clocks[role] = pd.Timestamp(receipt.available_at)
        identity = _digest(dict(assets=inputs.assets, uids=dict(inputs.asset_uids), epoch=inputs.identity_epoch,
            sources=source_identity, configuration=self.configuration_identity))
        period = pd.Timestamp(as_of).tz_convert("UTC").tz_localize(None).to_period(
            "M" if SCHEDULE[method] == "monthly" else "Q")
        key = (method, str(period), identity)
        cached = self.period_states.get(key)
        try:
            _calendar(inputs, as_of, method)
        except ValueError as error:
            _require(str(error) == "OFF_SCHEDULE_FIT_USE_FROZEN_PRIOR_STATE", str(error))
            _require(cached is not None, "TYPED_R2_SCHEDULED_STATE_UNAVAILABLE_OR_SOURCE_UID_DOMAIN_CHANGED")
        if cached is not None:
            state, previous_clocks = cached
            _require(pd.Timestamp(state.as_of) <= pd.Timestamp(as_of), "TYPED_R2_BACKWARD_DECISION_BEFORE_FROZEN_STATE")
            for role, receipt in receipts.items():
                if receipt is None: continue
                _require(pd.Timestamp(previous_clocks[role]) <= clocks[role] <= pd.Timestamp(as_of),
                         "TYPED_R2_ASSUMED_OBSERVATION_CLOCK_CHANGED_BACKWARD_OR_FUTURE")
                if role == "stock": receipt.validate(as_of)
                else: receipt.validate(as_of, role="benchmark" if role == "QQQ" else "industry", primary=inputs.source_receipt)
            self.last_reservation_delta = 0
        else:
            before = self.budget.learned_total
            state = self.engine.fit(method, inputs, as_of=as_of)
            self.last_reservation_delta = self.budget.learned_total-before
            self.period_states[key] = (state, clocks)
        self.states[state.risk_state_id] = state
        if state.risk_state_id in self.bundles:
            return self.bundles[state.risk_state_id], ("TYPED_R2", method, state.risk_state_id)
        by_key = {e["key"]: e for e in self.budget.events}
        learned = [by_key[k] for k in state.fit_dependency_ids
                   if k in by_key and by_key[k]["kind"] in LEARNED_KINDS]
        fitted = state.status in ("PASS_SYNTHETIC", "PASS_FROZEN_HISTORY_MECHANISM")
        bundle = bank.RiskBundle(method, "FITTED" if fitted else "BLOCKED_INPUT",
            tuple(state.assets), (), estimated_assets=tuple(state.assets) if fitted else (),
            covariance=None if not fitted else np.asarray(state.covariance, float).copy(),
            fallback_variance=None if not fitted else float(np.median(np.diag(state.covariance))),
            coverage=pd.DataFrame([dict(asset=a, **detail) for a, detail in state.coverage.items()]),
            specification=dict(fit_cutoff=str(state.cutoff), horizon_sessions=5,
                               source_id=state.source_identity, typed_r2_state_id=state.risk_state_id),
            fitted_state=dict(typed_state=state, exact_dependency_keys=state.fit_dependency_ids,
                              return_unit=state.return_coordinate, return_horizon_sessions=5,
                              new_learned_reservations=self.last_reservation_delta,
                              out_of_domain_padding="PRIOR_VARIANCE_NUMERICAL_ONLY; NEVER_ACTIVE_OR_HELD"),
            budget=dict(total_state_estimations=len(learned),
                        new_state_estimations=self.last_reservation_delta,
                        cumulative_prior=self.prior_fit_units),
            failure_reason="" if fitted else str(state.notes.get("block_reason", state.status)))
        self.bundles[state.risk_state_id] = bundle
        return bundle, ("TYPED_R2", method, state.risk_state_id)


def matrix_plan(scope):
    """Expand all coordinates and exact alias mappings without selecting one."""
    frozen = validate_scope(scope)
    aliases = catalogue()["exact_owner_decision_aliases"]
    risk_aliases = catalogue()["exact_same_input_risk_aliases"]
    risk_identity = {}
    for name, item in frozen["risk_combinations"].items():
        combined = {}
        for method, weight in zip(item["members"], item["weights"]):
            method = risk_aliases.get(method, method)
            combined[method] = combined.get(method, 0.) + weight
        risk_identity[name] = _digest(sorted(combined.items()))
    representatives = {}
    rows = []
    for pack in frozen["forecast_packs"]:
        for risk_name in frozen["risk_combinations"]:
            for decision in frozen["decision_methods"]:
                coordinate = Coordinate(pack, risk_name, decision)
                key = (pack, risk_identity[risk_name], aliases.get(decision, decision))
                original = representatives.setdefault(key, coordinate)
                rows.append(dict(coordinate=asdict(coordinate),
                                 evaluation_coordinate=asdict(original),
                                 disposition="ACTUAL_ACCOUNT_REQUIRED" if original == coordinate else
                                     "EXACT_OWNER_ALIAS_MAPPING_REQUIRES_ORIGINAL_ACCOUNT_RESULT",
                                 alias_is_execution=False))
    return rows
