"""Bounded reset/step bridge over the existing cash/shareholder replay owner.

Caller supplies one qualified, frozen 2021/22 episode and the separately frozen
activity projection. The explicit new-research delta gate reuses account state;
no market readers, reward simulator, source qualification, artifact writes or
fit-budget authority are added here.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import copy
import hashlib
from pathlib import Path
import queue
import threading
import numpy as np
import pandas as pd
from scripts.research.a2.training import consensus_auxiliary as auxiliary
from scripts.research.a2.evaluation import consensus_cash_account as account

require = auxiliary.require


@dataclass
class AccountEpisode:
    """run(policy, ledger_callback) binds the canonical owner and legal inputs.

    It must request collect_ledgers=False wherever the existing owner permits it.
    A fresh episode/owner lifecycle is built at each reset; no old account is
    reused. market is only used for date/ticker coordinates, never as observation.
    """
    market: object
    policy: object
    run: object
    qualification: dict


def _ref_valid(ref):
    return (isinstance(ref, dict) and isinstance(ref.get('path'), str)
            and isinstance(ref.get('sha256'), str) and len(ref['sha256']) == 64)


def account_observation(account_state, max_positions=20):
    nav = float(account_state['nav'])
    require(np.isfinite(nav) and nav > 0, 'RL_POSITIVE_CERTIFIED_NAV_REQUIRED')
    values = np.asarray(account_state['position_market_values'], float)
    units = np.asarray(account_state['position_units'], float)
    return np.array([account_state['settled_cash']/nav,
        account_state['unsettled_receivable']/nav, values.sum()/nav,
        np.count_nonzero(units > account.TOL)/max_positions], dtype=float)


def activity_delta_gate(decision, context, cap):
    """Scale ordinary PTO target deltas by cap/.95; retain owner restrictions.

    This is the explicitly authorized new-research meaning of the activity cap.
    At .95 the original decision object passes through, including its failures.
    A zero/intermediate cap cannot erase a base name-limit failure either.
    Forced exits are already represented by the owner's operational mask,
    including stock-distribution exits; this function never changes that context.
    """
    require(cap in auxiliary.CAPS, 'LEGAL_ACCOUNT_ACTIVITY_CAP_REQUIRED')
    if cap == .95:
        return decision
    require(isinstance(decision, account.engine.TargetDecision),
            'CANONICAL_PTO_TARGET_DECISION_REQUIRED')
    raw = np.asarray(decision.weights, dtype=float)
    current = np.asarray(context.current_weights, dtype=float)
    allowed = np.asarray(context.decision_mask, dtype=bool)
    explicit = allowed.copy() if decision.explicit_mask is None else np.asarray(decision.explicit_mask, bool).copy()
    operational = np.asarray(context.operational_mask, dtype=bool)
    reserved = np.asarray(context.reserved_mask, dtype=bool)
    restricted = np.asarray(context.sell_restricted, dtype=bool)
    held = np.asarray(context.current_units, dtype=float) > account.TOL
    require(raw.shape == current.shape == allowed.shape == explicit.shape
            == operational.shape == reserved.shape == restricted.shape == held.shape,
            'ACTIVITY_GATE_CANONICAL_CONTEXT_SHAPE_REQUIRED')
    # Preserve invalid source decisions rather than laundering them through a cap.
    if (explicit & ~allowed).any() or not np.isfinite(raw[explicit]).all() or (
            (raw[explicit] < 0) | (raw[explicit] > context.max_weight + 1e-7)).any():
        return decision
    ordinary = explicit & allowed & ~operational & ~reserved & ~restricted
    forced_free = operational & ~restricted
    base_names = np.where(ordinary, raw > account.TOL, held) & ~forced_free
    if (base_names.sum(axis=1) > context.max_positions).any():
        return decision
    weights = raw.copy()
    if cap == 0:
        explicit[ordinary] = False
    else:
        require(np.isfinite(current[ordinary]).all(),
                'CERTIFIED_CURRENT_WEIGHTS_REQUIRED_FOR_ACTIVITY_DELTA')
        weights[ordinary] = current[ordinary] + (float(cap)/.95) * (raw[ordinary] - current[ordinary])
        # Drift may put a held name above 10%; HOLD_UNITS keeps owner semantics.
        drift_hold = ordinary & (weights > context.max_weight)
        explicit[drift_hold] = False
        projected_names = np.where(explicit & ordinary, weights > account.TOL, held) & ~forced_free
        overflow = projected_names.sum(axis=1) > context.max_positions
        # Partial sales leave residual names. Cancel this account's ordinary
        # changes together; the owner still performs its original forced exits.
        explicit[overflow[:, None] & ordinary] = False
    return replace(decision, weights=weights, explicit_mask=explicit)


class AccountEnvironment:
    """One bounded queue pair; a live canonical account pauses at each policy.

    A caller-provided gate projects a base TargetDecision, preserving the exact
    separately frozen economic meaning of CAPS. An unavailable gate is rejected;
    this adapter deliberately cannot invent a cash/gross/turnover interpretation.
    """
    def __init__(self, source_contract, episode_factory, activity_gate):
        require(callable(episode_factory) and callable(activity_gate),
                'QUALIFIED_EPISODE_FACTORY_AND_FROZEN_ACTIVITY_GATE_REQUIRED')
        c = copy.deepcopy(source_contract)
        require(c.get('chronological_oof_only') is True
                and c.get('primary_horizon_sessions') == 5
                and c.get('outer_development_rewards_used') is False,
                'PAST_2021_2022_OOF_PRIMARY_5D_REWARDS_ONLY')
        require(_ref_valid(c.get('activity_gate_ref'))
                and _ref_valid(c.get('training_inputs_ref')),
                'FROZEN_ACTIVITY_GATE_AND_TRAINING_INPUT_REFS_REQUIRED')
        c.update(environment_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            account_owner='scripts.research.a2.evaluation.consensus_cash_account.run_cash_account',
            account_owner_sha256=hashlib.sha256(Path(account.__file__).read_bytes()).hexdigest(),
            observation_fields=list(auxiliary.ACCOUNT_FIELDS))
        self.source_contract = c
        require(auxiliary.environment_contract(self) is not None,
                'QUALIFIED_FROZEN_2021_2022_ENVIRONMENT_CONTRACT_REQUIRED')
        self._factory, self._gate = episode_factory, activity_gate
        self._thread = None
        self._states = self._actions = None
        self._waiting = False
        self._closed = threading.Event()
        self._last_state = None

    def _receive(self):
        kind, payload = self._states.get()
        if kind == 'ERROR':
            self._waiting = False
            raise RuntimeError('CANONICAL_ACCOUNT_EPISODE_FAILED: ' + payload)
        self._waiting = not payload['terminated']
        self._last_state = payload
        return payload

    def reset(self, segment_id, seed):
        self.close()
        segment = next((s for s in self.source_contract['reset_segments']
                        if s['segment_id'] == segment_id), None)
        require(segment is not None, 'REGISTERED_FROZEN_ACCOUNT_SEGMENT_REQUIRED')
        episode = self._factory(segment_id, seed)
        require(isinstance(episode, AccountEpisode), 'CANONICAL_ACCOUNT_EPISODE_REQUIRED')
        q = episode.qualification
        require(all(q.get(k) is True for k in ('source_qualified',
            'chronological_oof_only', 'cash_shareholder_owner_bound',
            'unsupported_events_fail_closed', 'fresh_lifecycle')),
            'SOURCE_QUALIFIED_OOF_SHAREHOLDER_EPISODE_REQUIRED')
        require(q.get('training_inputs_ref') == self.source_contract['training_inputs_ref']
                and _ref_valid(q.get('runner_ref')),
                'FROZEN_EPISODE_INPUT_AND_CANONICAL_RUNNER_BINDING_REQUIRED')
        dates = pd.DatetimeIndex(episode.market.dates)
        lower, upper = pd.Timestamp(segment['start']), pd.Timestamp(segment['end_exclusive'])
        require(len(dates) >= 2 and dates.is_monotonic_increasing and not dates.has_duplicates
                and lower <= dates[0] < dates[-1] < upper <= pd.Timestamp('2023-01-01'),
                'ACCOUNT_EPISODE_DATE_COORDINATES_MUST_PRECEDE_2023')
        signals = np.asarray(episode.market.signal_mask, bool)
        require(signals.shape == (len(dates),) and signals[:-1].all() and not signals[-1],
                'CONTIGUOUS_ACCOUNT_DECISIONS_AND_ONE_TERMINAL_SESSION_REQUIRED')
        require(callable(episode.run) and callable(episode.policy), 'CANONICAL_ACCOUNT_CALLABLES_REQUIRED')
        self._states, self._actions = queue.Queue(maxsize=1), queue.Queue(maxsize=1)
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(episode, segment),
                                        name='consensus-account-rl', daemon=True)
        self._thread.start()
        return self._receive()

    def step(self, cap):
        require(self._waiting and cap in auxiliary.CAPS, 'LEGAL_PENDING_ACCOUNT_ACTIVITY_ACTION_REQUIRED')
        self._waiting = False
        self._actions.put(float(cap))
        return self._receive()

    def close(self):
        if self._thread is None:
            return
        self._closed.set()
        # A pending canonical policy waits only on this bounded action queue.
        try:
            self._actions.put_nowait(None)
        except queue.Full:
            pass
        # Release a producer blocked on its one-item state queue as well.
        try:
            self._states.get_nowait()
        except queue.Empty:
            pass
        self._thread.join(timeout=5.)
        require(not self._thread.is_alive(), 'CANONICAL_ACCOUNT_EPISODE_CLOSE_DID_NOT_FINISH')
        self._thread = None
        self._waiting = False

    def _run(self, episode, segment):
        daily = None
        positions = {}
        fees = 0.
        previous = None
        try:
            def ledger(name, frame):
                nonlocal daily, positions, fees
                if self._closed.is_set():
                    raise InterruptedError('ACCOUNT_EPISODE_CLOSED')
                if name == 'daily':
                    require(len(frame) == 1, 'SINGLE_INDEPENDENT_RL_ACCOUNT_REQUIRED')
                    daily = frame.iloc[0].to_dict()
                    day = pd.Timestamp(daily['date'])
                    require(pd.Timestamp(segment['start']) <= day < pd.Timestamp(segment['end_exclusive'])
                            and day < pd.Timestamp('2023-01-01'), 'RL_LEDGER_OUTSIDE_TRAINING_SEGMENT')
                    require(np.isfinite(daily['certified_nav']) and daily['certified_nav'] > 0
                            and daily.get('accounting_qualified', True) is True,
                            'CERTIFIED_QUALIFIED_ACCOUNT_REWARD_REQUIRED')
                    positions = {}
                    fees += float(daily['transaction_cost_amount']) + float(daily.get('fx_conversion_fee_usd', 0.))
                elif name == 'positions':
                    require(daily is not None and pd.to_datetime(frame.date).eq(pd.Timestamp(daily['date'])).all(),
                            'SAME_SESSION_CERTIFIED_POSITION_LEDGER_REQUIRED')
                    for row in frame.itertuples():
                        require(not bool(row.stale) and not bool(row.unknown), 'UNCERTIFIED_POSITION_REWARD_FORBIDDEN')
                        positions[str(row.ticker)] = (float(row.index_units), float(row.market_value))

            def state(terminated):
                nonlocal previous
                require(daily is not None, 'ACTUAL_CANONICAL_DAILY_LEDGER_REQUIRED')
                units = np.array([positions.get(str(t), (0., 0.))[0] for t in episode.market.tickers])
                marked = np.array([positions.get(str(t), (0., 0.))[1] for t in episode.market.tickers])
                cash = float(daily.get('settled_cash', daily['cash']))
                unsettled = float(daily.get('unsettled_cash', 0.))
                corporate = float(daily.get('corporate_receivable', daily.get('receivable_value_usd', 0.)))
                nav = float(daily['certified_nav'])
                a = dict(settled_cash=cash, unsettled_receivable=unsettled,
                    corporate_receivable=corporate, nav=nav, position_units=units,
                    position_market_values=marked, cumulative_fees=fees,
                    nav_identity_error=nav-cash-unsettled-corporate-marked.sum())
                out = dict(observation=account_observation(a), legal_actions=np.ones(5, dtype=bool),
                    as_of=pd.Timestamp(daily['date']), terminated=bool(terminated),
                    source_qualified=True, account_state=a)
                if previous is not None:
                    out.update(reward=nav/previous['account_state']['nav']-1.,
                        reward_mature_at=out['as_of'],
                        transaction_fee_usd=fees-previous['account_state']['cumulative_fees'])
                auxiliary.validate_state(out, self.source_contract, segment,
                    None if previous is None else previous['as_of'])
                previous = out
                return out

            def policy(di, context):
                out = state(False)
                self._states.put(('STATE', out))
                cap = self._actions.get()
                if cap is None or self._closed.is_set():
                    raise InterruptedError('ACCOUNT_EPISODE_CLOSED')
                decision = episode.policy(di, context)
                return self._gate(decision, context, cap)

            episode.run(policy, ledger)
            if not self._closed.is_set():
                self._states.put(('STATE', state(True)))
        except BaseException as error:
            if not self._closed.is_set():
                self._states.put(('ERROR', type(error).__name__ + ': ' + str(error)))


def fit_activity_policy(method, environment, *, on_fit_started):
    """Reuse the original fixed gradient recipe and always release its account."""
    require(isinstance(environment, AccountEnvironment), 'CANONICAL_ACCOUNT_ENVIRONMENT_REQUIRED')
    try:
        return auxiliary.fit_account_rl(method, environment, on_fit_started=on_fit_started)
    finally:
        environment.close()


class FrozenActivityPolicy:
    """Apply a fitted gate to a canonical PTO target; no new fitting at inference."""
    def __init__(self, base_policy, fitted, state_provider, activity_gate):
        require(isinstance(fitted, auxiliary.RLFit) and callable(base_policy)
                and callable(state_provider) and callable(activity_gate),
                'FROZEN_RL_FIT_CAUSAL_STATE_AND_EXISTING_ACTIVITY_GATE_REQUIRED')
        self.base_policy, self.fitted = base_policy, fitted
        self.state_provider, self.activity_gate = state_provider, activity_gate

    def __call__(self, di, context):
        observation, legal_actions = self.state_provider(di, context)
        cap = self.fitted.activity_cap(observation, legal_actions)
        return self.activity_gate(self.base_policy(di, context), context, cap)
