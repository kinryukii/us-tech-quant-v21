"""R5 event-clock qualification over the unchanged frozen family policy.

No readers, fitters, covariance completion, allocator or account implementation.
The caller supplies pinned bank metadata and CURRENT source/maturity witnesses.
Calendar membership is checked without deriving or consulting a next event.
"""
from dataclasses import dataclass, fields, replace
from pathlib import Path
import hashlib
from typing import Mapping
import pandas as pd
from . import joint_frozen_history_policy_r3 as parent
from scripts.research.a2.portfolio import shared_joint_adapter_r2 as ad
from scripts.research.a2.risk import event_risk_contract_r5 as event
from scripts.research.a2.risk.shared_risk_engine_r2 import _time, CUTOFF
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

CURRENT_POOL_RULE = "CURRENT_CLOSE_ACCEPTED_FEATURE_RAW_KNOWN_UID_FULL_POOL_NO_OUTCOME_SCREEN"
PARENT_FAMILIES = {
    "R0": "LW", "RD": "EWMA", "RM": "MULTI_HORIZON", "RB": "QQQ_RESIDUAL",
    "RH": "FF48_HIERARCHICAL", "RT": "DOWNSIDE_SEMIVARIANCE",
    "RR": "REGIME_COVARIANCE", "RU": "UNCERTAINTY_JACKKNIFE",
    "RE": "DISAGREEMENT_ENSEMBLE", "SHR_HP": "SHR_HP", "SHR_EB": "SHR_EB",
    "SHR_CC": "SHR_CC", "SHR_FACTOR": "SHR_FACTOR",
    "OAS": "OAS", "CONSTANT_CORRELATION": "CONSTANT_CORRELATION",
    "PCA_FACTOR": "PCA_FACTOR", "TAIL_CVAR": "TAIL_CVAR"}
REPRESENTATIONS = {"EVENT_CLASSICAL", "EVENT_CLASSICAL_WITH_PRIOR_COMPLETION",
                   "EVENT_HIERARCHICAL_PRIOR"}


def source_pins():
    """Code custody only; no bank/model/data reads."""
    pins = parent.source_pins()
    for module in (event,):
        path = Path(module.__file__).resolve()
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    path = Path(__file__).resolve()
    pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return pins


def _check(condition, reason):
    if not condition:
        raise parent.FamilyPolicyBlocked(reason)


def _sessions(values):
    sessions = pd.DatetimeIndex([_time(v) for v in values])
    _check(not sessions.empty and not sessions.has_duplicates and
           not sessions.normalize().has_duplicates and sessions.is_monotonic_increasing and
           sessions[-1] < CUTOFF, "EXACT_PRE2026_EVENT_LEGAL_CALENDAR_REQUIRED")
    return sessions


@dataclass(frozen=True)
class EventMethodBinding:
    parent_risk: str
    method: str
    family: str
    representation: str
    recipe_sha256: str
    producer_sha256: str
    availability: str = "READY"

    def validate(self):
        _check(PARENT_FAMILIES.get(self.parent_risk) == self.family and
               self.method.startswith(("R5_", "R5::")) and self.method not in ad.SCHEDULE and
               ad._sha(self.recipe_sha256), "EXPLICIT_RELATED_EVENT_SCIENTIFIC_DESCENDANT_REQUIRED")
        _check(self.representation in REPRESENTATIONS and
               self.availability in {"READY", "BLOCKED_UNBOUND_HORIZONS", "BLOCKED_MISSING_PRODUCER"},
               "EXPLICIT_EVENT_REPRESENTATION_AND_SUPPORT_STATUS_REQUIRED")
        _check(self.parent_risk != "RM" or self.availability == "BLOCKED_UNBOUND_HORIZONS",
               "RM_3_10_20_UNBOUND_MUST_REMAIN_BLOCKED")
        _check(self.availability != "READY" or ad._sha(self.producer_sha256),
               "PINNED_EVENT_PRODUCER_REQUIRED")
        _check(self.representation != "EVENT_HIERARCHICAL_PRIOR" or self.family.startswith("SHR_"),
               "CLASSICAL_FAMILY_CANNOT_BE_RELABELED_AS_HP")


def _binding(bindings, method):
    found = [b for b in bindings if b.method == method]
    _check(len(found) == 1, "EXACT_EVENT_METHOD_BINDING_REQUIRED")
    found[0].validate()
    return found[0]


@dataclass(frozen=True, kw_only=True)
class FrozenEventMechanismActivation(ad.FrozenMechanismActivation):
    method_bindings: tuple[EventMethodBinding, ...]
    bank_manifest_sha256: str
    event_source_sha256: Mapping[str, str]

    def validate(self, expected_sha256, decision_asof):
        _check(self.digest() == expected_sha256 and ad._sha(expected_sha256),
               "FROZEN_EVENT_ACTIVATION_MUTATION")
        _check(ad._sha(self.bank_manifest_sha256) and self.event_source_sha256 == source_pins(),
               "PINNED_EVENT_BANK_AND_CODE_CLOSURE_REQUIRED")
        methods = tuple(b.method for b in self.method_bindings)
        _check(len(set(methods)) == len(methods) and
               len({b.parent_risk for b in self.method_bindings}) == len(methods) and
               methods == self.allowed_risk_methods, "EXACT_EVENT_METHOD_ROSTER_REQUIRED")
        for b in self.method_bindings:
            b.validate()
        # Reuse every generic parent authority/Q/A/G/cost guard. This validation
        # view replaces only the parent's native risk-name allowlist; no state,
        # recipe or numerical method is relabeled for policy evaluation.
        values = {f.name: getattr(self, f.name) for f in fields(ad.FrozenMechanismActivation)}
        values["allowed_risk_methods"] = tuple(ad.SCHEDULE)
        view = ad.FrozenMechanismActivation(**values)
        view.validate(view.digest(), _time(decision_asof))


@dataclass(frozen=True, kw_only=True)
class EventRiskStateUseReceipt(ad.RiskStateUseReceipt):
    witness: event.EventWitness
    bank_manifest_sha256: str
    model_producer_sha256: str
    asset_uids: Mapping[str, str]
    asset_epochs: Mapping[str, str]
    source_support_identity: Mapping[str, object]
    representation: str
    parent_risk: str
    recipe_sha256: str

    def structural_identity(self):
        return event.structural_identity(assets=self.assets, uids=dict(self.asset_uids),
            epochs=dict(self.asset_epochs), security_coordinate=self.source.return_coordinate,
            source_support_identity=dict(self.source_support_identity))

    def validate(self, state, binding, activation, expected_sha256, decision_asof):
        _check(isinstance(activation, FrozenEventMechanismActivation), "TYPED_EVENT_ACTIVATION_REQUIRED")
        _check(self.next_refresh_as_of == "", "FUTURE_NEXT_EVENT_DATE_FORBIDDEN")
        _check(ad._sha(expected_sha256) and self.frozen_sha256 == expected_sha256 and
               self.digest() == expected_sha256, "FROZEN_EVENT_STATE_USE_MUTATION")
        b = _binding(activation.method_bindings, self.method)
        _check(b.availability == "READY", b.availability)
        _check((self.parent_risk, self.representation, self.recipe_sha256, self.model_producer_sha256) ==
               (b.parent_risk, b.representation, b.recipe_sha256, b.producer_sha256) and
               self.bank_manifest_sha256 == activation.bank_manifest_sha256,
               "EVENT_MODEL_RECIPE_OR_BANK_IDENTITY_MISMATCH")
        _check(self.risk_state_id == state.risk_state_id and
               self.risk_state_sha256 == ad.risk_state_sha256(state) and self.source == binding and
               self.assets == tuple(state.assets) and self.identity_epoch == binding.identity_epoch and
               self.method == state.method, "EVENT_RISK_STATE_SOURCE_UID_OR_METHOD_MISMATCH")
        sessions = _sessions(self.legal_sessions)
        _check(ad.legal_calendar_sha256(self.legal_sessions) == activation.legal_calendar_sha256,
               "FROZEN_EVENT_CALENDAR_MUTATION")
        fit, cutoff, decision = _time(self.fit_as_of), _time(self.fit_cutoff), _time(decision_asof)
        i, j = sessions.get_indexer([fit, decision])
        _check(i > 0 and j >= i and cutoff == sessions[i-1] and
               fit == _time(state.as_of) and cutoff == _time(state.cutoff),
               "EVENT_FIT_CURRENT_CLOSE_AND_PRIOR_CUTOFF_REQUIRED")
        _check(isinstance(self.witness, event.EventWitness) and
               _time(self.witness.decision_asof) == decision and
               ad._sha(self.witness.current_structural_identity) and
               self.structural_identity() == self.witness.state_structural_identity,
               "CURRENT_EVENT_STRUCTURAL_WITNESS_REQUIRED")
        self.witness.validate(fit)
        proof = state.notes.get("event_policy_binding", {})
        expected = dict(parent_risk=self.parent_risk, representation=self.representation,
            recipe_sha256=self.recipe_sha256, model_producer_sha256=self.model_producer_sha256,
            structural_identity=self.structural_identity(),
            source_support_identity_sha256=content_hash(self.source_support_identity),
            asset_uid_epoch_sha256=content_hash(dict(uids=self.asset_uids, epochs=self.asset_epochs)))
        _check(proof == expected, "FROZEN_BANK_EVENT_PRODUCER_SOURCE_UID_PROOF_REQUIRED")
        for a in self.assets:
            _check(state.coverage.get(a, {}).get("uid") == self.asset_uids[a] and
                   state.coverage.get(a, {}).get("identity_epoch") == self.asset_epochs[a],
                   "EVENT_STATE_COVERAGE_UID_EPOCH_MISMATCH")


@dataclass(frozen=True, kw_only=True)
class CurrentEventRiskPoolReceipt(parent.FrozenRiskPoolReceipt):
    current_pool_asof: str
    current_accepted_features: tuple[bool, ...]
    current_raw_rows: tuple[bool, ...]
    current_uids: tuple[str | None, ...]
    current_epochs: tuple[str | None, ...]
    source_support_identity: Mapping[str, object]
    pool_rule: str = CURRENT_POOL_RULE

    def structural_identity(self, coordinate):
        positions = [self.master_assets.index(a) for a in self.assets]
        return event.structural_identity(assets=self.assets,
            uids={a:self.current_uids[i] for a,i in zip(self.assets,positions)},
            epochs={a:self.current_epochs[i] for a,i in zip(self.assets,positions)},
            security_coordinate=coordinate, source_support_identity=dict(self.source_support_identity))

    def validate(self, state, master, expected_sha256, contract):
        _check(self.digest() == expected_sha256 and ad._sha(expected_sha256) and
               self.pool_rule == CURRENT_POOL_RULE, "FROZEN_CURRENT_POOL_MUTATION")
        _check(not self.prior_accepted_features and not self.prior_raw_rows and not self.prior_known_uids,
               "LEGACY_PRIOR_POOL_FIELDS_MUST_BE_EMPTY_IN_CURRENT_EVENT_RECEIPT")
        _check(self.master_assets == tuple(master) and len(set(master)) == len(master) and
               self.assets == tuple(state.assets) and self.identity_epoch == state.identity_epoch and
               self.source_contract_sha256 == contract.source_contract_sha256 and
               _time(self.cutoff) == _time(self.current_pool_asof), "CURRENT_POOL_IDENTITY_OR_CLOCK_MISMATCH")
        n = len(master)
        _check(all(len(v)==n for v in (self.current_accepted_features,self.current_raw_rows,
                   self.current_uids,self.current_epochs)) and
               all(type(v) is bool for v in self.current_accepted_features+self.current_raw_rows),
               "COMPLETE_CURRENT_FEATURE_RAW_UID_METADATA_REQUIRED")
        requested = tuple(a for i,a in enumerate(master)
            if self.current_accepted_features[i] and self.current_raw_rows[i])
        _check(requested == self.assets, "FULL_CURRENT_REQUESTED_POOL_CANNOT_SHRINK_OR_PAD")
        self.structural_identity(state.return_coordinate)  # Unknown/duplicate UID/epoch fails closed.
        for a in self.assets:
            i = self.master_assets.index(a)
            _check(state.coverage.get(a,{}).get("uid") == self.current_uids[i] and
                   state.coverage.get(a,{}).get("identity_epoch") == self.current_epochs[i],
                   "CURRENT_POOL_AND_STATE_UID_EPOCH_MISMATCH")


@dataclass(frozen=True, kw_only=True)
class FrozenEventFamilyPolicyContract(parent.FrozenFamilyPolicyContract):
    parent_rows: tuple[parent.FrozenFamilyRow, ...]
    parent_policy_binding_sha256: str
    parent_rows_sha256: str
    contrast_binding_sha256: str
    event_source_sha256: Mapping[str, str]


class EventFamilyPolicy(parent.FrozenHistoryFamilyPolicy):
    """Only transport/qualification changes; parent owns all numeric policy logic.

    evaluate is a zero-account qualification API. The inherited __call__ uses
    the unchanged common-account interface only with an independently frozen
    ACCOUNT_REPLAY token; constructing this class never authorizes that replay.
    """
    def __init__(self, contract, *, activation, input_provider, **kwargs):
        _check(isinstance(contract,FrozenEventFamilyPolicyContract) and
               isinstance(activation,FrozenEventMechanismActivation), "TYPED_EVENT_FAMILY_CONTRACT_REQUIRED")
        _check(all(ad._sha(v) for v in (contract.parent_policy_binding_sha256,
                   contract.parent_rows_sha256,contract.contrast_binding_sha256)) and
               contract.parent_rows_sha256 == content_hash(contract.parent_rows) and
               contract.event_source_sha256 == activation.event_source_sha256 == source_pins(),
               "PINNED_PARENT_TUPLE_CONTRAST_AND_EVENT_CODE_REQUIRED")
        _check(len(contract.rows) == len(contract.parent_rows) and bool(contract.rows),
               "PARENT_POLICY_PATHS_CANNOT_EXPAND_OR_SHRINK")
        for child, prior in zip(contract.rows, contract.parent_rows):
            risk = "NONE" if prior.risk == "NONE" else next(
                (b.method for b in activation.method_bindings if b.parent_risk == prior.risk), None)
            _check(replace(child,risk=prior.risk) == prior and child.risk == risk,
                   "PARENT_FORECAST_Q_ACTION_G_COST_SEED_TUPLE_CHANGED")
        super().__init__(contract, activation=activation, input_provider=input_provider, **kwargs)

    def evaluate(self, day, path_id, ctx, inputs=None):
        try:
            self._validate_frozen_contract()
            self.activation.validate(self.activation_sha, _time(ctx.signal_asof))
            row = self.rows[path_id]
            data = inputs if inputs is not None else self.provider(day,row,ctx)
            _check(isinstance(data,parent.FamilyPolicyInputs), "TYPED_FROZEN_POLICY_INPUTS_REQUIRED")
            if row.risk != "NONE":
                b = _binding(self.activation.method_bindings,row.risk)
                _check(b.availability == "READY", b.availability)
                _check(isinstance(data.pool_receipt,CurrentEventRiskPoolReceipt) and
                       isinstance(data.risk_use_receipt,EventRiskStateUseReceipt),
                       "TYPED_CURRENT_POOL_AND_EVENT_STATE_USE_REQUIRED")
                pool, use = data.pool_receipt, data.risk_use_receipt
                asof = _time(ctx.signal_asof)
                sessions = _sessions(use.legal_sessions)
                i = sessions.get_indexer([asof])[0]
                _check(i > 0 and _time(data.prior_cutoff) == sessions[i-1] and
                       _time(pool.current_pool_asof) == asof and _time(pool.cutoff) == asof,
                       "CURRENT_POOL_CLOSE_AND_CURRENT_PRIOR_LEGAL_CLOSE_MUST_BE_DISTINCT")
                pool.validate(data.risk_state,tuple(str(a) for a in ctx.tickers),
                              data.expected_pool_sha256,self.contract)
                _check(pool.structural_identity(data.risk_state.return_coordinate) ==
                       use.witness.current_structural_identity,
                       "CURRENT_POOL_WITNESS_UID_EPOCH_SOURCE_MISMATCH")
            # This single call reuses parent forecast lineage/P2, actual held mask,
            # SharedJointAdapter allocate_q -> G -> action, and target transport.
            return super().evaluate(day,path_id,ctx,data)
        except (ad.AdapterBlocked,ValueError,TypeError,KeyError,AttributeError) as error:
            return parent.FamilyPolicyResult(path_id,"BLOCKED_MECHANISM_POLICY",None,
                dict(block_reason=str(error),event_policy=True,strict_PIT_promotion_eligible=False,
                     quote_qualified=False,certified_NAV=False))
