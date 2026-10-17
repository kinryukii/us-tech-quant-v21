"""Explicit C14 numeric-input qualification over the original R5 loader.

No automatic execution, persistence, estimator, solver, second bank or label
reader. Native state payloads are cached only in this process. A complete input
gate is distinct from realized-endpoint qualification and scientific completion.
"""
from __future__ import annotations
import copy
import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.research.a2.data import selector_maximal_risk_binding as b
from scripts.research.a2.data import selector_maximal_risk_current as current_owner

REPO = Path(__file__).resolve().parents[4]
OWNER_PINS = {
    'data/selector_maximal_risk_binding.py': '5d938fd7e4b5d110bed0fda7de09ad33fa36362f2e3a0f490ed6f4cd35ee0015',
    'data/selector_maximal_risk_current.py': '8fcbdb430aee0ddedb95941c1f025e1083af9591ef50326ae31b7553edd4c5ca',
    'data/selector_maximal_risk_consumer.py': 'a5ebdabfad83a30233bc03e93ed044807f4d256aded8ce5b6184424008fb5866',
    'data/selector_shared_risk_consumer.py': '71a57696ba1596ee03c17939d561b75cfcd9870969aadc32991fc4e0dbf79fd3',
    'data/joint_event_risk_support_r5.py': '6efadd3c9f9999352046f27a9753a24ef71e1f8da494bdd255fa14a872512783',
    'data/shared_risk_inputs_r3.py': 'd398dcc77ab32ff8a15ee041deac4e6ab23fcd7542c456dd8eb44b03d526f997',
    'evaluation/joint_event_risk_execution_r5.py': '955fff74f7eff3bab56063a17a3d4f3ee749b26bbad4b2a1452ddfe3e65c0643',
    'evaluation/joint_frozen_history_risk_r3.py': 'fc6aabffbdcd6f34d8a9c52f44a59ea10b122be3cec281fd6f732956b4ce2794',
    'inference/joint_event_risk_chain_r5.py': '58f6f272039f990abb050393cdfacbb952772970bd7968156fcd0c2c426050a7',
    'risk/shared_risk_engine_r2.py': 'db89f65d22dbd300973cfba8f11de1a3b758365f5a8067706b48ee2ee1a16647',
    'risk/joint_risk_estimators.py': '6ae94d300aa2fe2ded9fcb81548f2fb7b0c58c11a24aaed7db846b700a8aea97',
    'risk/shared_risk_budget_r2.py': '0b0cb0f83731d9b6222dfb8204f80a73d7b02fe6f0f6831bb061149000b463d7',
    'risk/event_risk_contract_r5.py': 'ef17df6d655cc25796613282a87c8f04fe9ade62cf815c3ce06d22dd245a0b90',
}


def source_pins():
    """Pins needed by the independent reviewer; this function grants no approval."""
    pins = {str((REPO / 'scripts/research/a2' / p).resolve()): h for p, h in OWNER_PINS.items()}
    pins[str(Path(__file__).resolve())] = b.sha(__file__)
    return pins


def stamp(path):
    s = Path(path).stat()
    return s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_dev, s.st_ino


def day_token(value):
    day = pd.Timestamp(value)
    b.need(not pd.isna(day) and day.tzinfo is None and day == day.normalize()
           and day < pd.Timestamp('2026-01-01'), 'EXACT_PRE2026_DECISION_DATE_REQUIRED')
    return day.isoformat()


def state_identity(meta):
    """Every native numerical coordinate must survive daily/role transport."""
    return b.content_hash(dict(family=meta.family, recipe=meta.recipe_sha256, parameters=meta.parameters,
        header={k: meta.header[k] for k in ('artifact_ref', 'risk_state_id', 'method', 'as_of', 'cutoff',
            'horizon_sessions', 'event_policy_binding', 'source_support_identity', 'covariance_sha256')},
        current={k: meta.current[k] for k in ('assets', 'asset_uids', 'asset_epochs', 'segment_starts',
            'security_coordinate', 'source_support_identity')}))


class RiskInputs:
    """Reviewed source custody first; qualify() is the explicit numeric boundary.

    c_raw_metadata is an independently projected C14 full-U key frame, restricted
    to current_owner.RAW_META. The caller owns its physical input receipt. The
    constructor never loads native state payloads or writes activation gates.
    """
    def __init__(self, publication, matrix, current_bindings, c_raw_metadata, *, source_review, source_review_ref):
        b.need(source_review.get('status') == 'PASS' and source_review.get('research_id') == b.contract.ID,
               'INDEPENDENT_INPUT_SOURCE_REVIEW_PASS_REQUIRED')
        self.review = copy.deepcopy(source_review)
        self.review_ref = copy.deepcopy(source_review_ref)
        ref = self.review_ref
        b.need(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}
               and Path(ref['path']).is_absolute() and Path(ref['path']).resolve().is_relative_to(b.RUN.resolve())
               and Path(ref['path']).resolve().parent == b.RUN.resolve()
               and re.fullmatch(r'RISK_INPUT_SOURCE_REVIEW_R[0-9]+\.json', Path(ref['path']).name),
               'ORIGINAL_C14_PHYSICAL_SOURCE_REVIEW_REQUIRED')
        before = stamp(ref['path'])
        b.need(b.sha(ref['path']) == ref['sha256'] and before == stamp(ref['path']), 'SOURCE_REVIEW_PHYSICAL_PIN_CHANGED')
        b.need(json.loads(Path(ref['path']).read_text(encoding='utf-8')) == self.review,
               'SOURCE_REVIEW_BODY_MISMATCH')
        self._review_seal = b.content_hash(self.review)
        self._pins = {str(Path(ref['path']).resolve()): before}
        required = source_pins()
        observed = self.review.get('source_pins', {})
        b.need(self.review.get('adapter_sha256') == OWNER_PINS['data/selector_maximal_risk_binding.py']
               and all(observed.get(p) == h for p, h in required.items()), 'EXACT_REVIEWED_INPUT_SOURCE_CLOSURE_REQUIRED')
        for p, h in observed.items():
            path = Path(p).resolve()
            b.need(path.is_relative_to(REPO) and path.suffix == '.py' and len(h) == 64,
                   'REVIEWED_SOURCE_ONLY_REQUIRED')
            before = stamp(path)
            b.need(b.sha(path) == h and before == stamp(path), 'REVIEWED_SOURCE_PHYSICAL_PIN_CHANGED')
            self._pins[str(path)] = before
        current_owner.namespace_source()
        design, dag = b.frozen_contract()
        b.need(b.content_hash(matrix) == b.content_hash(b.requirement_matrix(design, dag)),
               'EXACT_ORIGINAL_FROZEN_REQUIREMENT_MATRIX_REQUIRED')
        self.matrix = copy.deepcopy(matrix)
        self.requirements = {r['role']: r for r in self.matrix['roles']}
        b.need(len(self.requirements) == len(self.matrix['roles']), 'UNIQUE_FROZEN_ROLES_REQUIRED')
        dates = self.matrix['roles'][0]['required_dates']
        b.need(len(dates) == len(set(dates)) == 752 and dates == sorted(dates)
               and all(day_token(d) == d for d in dates)
               and all(r['required_dates'] == dates and r['calendar_positions'] == 752
                       and r['learned_support_mask'] == 482 and r['required_732_mature_day_support'] is True
                       for r in self.matrix['roles']), 'EXACT752_732_482_FROZEN_MASKS_REQUIRED')
        self.dates = tuple(dates)
        self.current = {day_token(d): copy.deepcopy(v) for d, v in current_bindings.items()}
        b.need(len(self.current) == len(current_bindings) and set(self.current) == set(self.dates),
               'ALL752_CURRENT_BINDINGS_REQUIRED')
        raw = current_owner.raw_metadata(c_raw_metadata)
        self.raw = {day_token(d): f.copy() for d, f in raw.groupby('signal_date', sort=True)}
        b.need(set(self.raw) == set(self.dates), 'INDEPENDENT_C14_FULL752_KEYS_REQUIRED')
        b.need(type(publication) is b.PublicationBinding, 'SEALED_ORIGINAL_R5_PUBLICATION_REQUIRED')
        publication.verify()
        self.publication = publication
        self._input_seal = b.content_hash(dict(matrix=self.matrix, current_dates=list(self.current)))
        self._current_seals = {d: b.content_hash(v) for d, v in self.current.items()}
        self._requirement_seals = {r: b.content_hash(v) for r, v in self.requirements.items()}
        self._control_seal = self._control_hash()
        self._raw_seals = {d: b.content_hash(f.astype(str).values.tolist()) for d, f in self.raw.items()}
        self._cache, self._failed, self._gates = {}, {}, {}
        self._qualified = False
        self.counts = dict(native_state_load_attempts=0, native_states_loaded=0, daily_role_bindings=0,
                           selector_fit=0, risk_estimator_fit=0, solver=0, bootstrap=0, risk_numeric_read=0,
                           test2026_rows_read=0, EF_access=0, provider_fetch=0)

    def _control_hash(self):
        return b.content_hash(dict(matrix_header={k: v for k, v in self.matrix.items() if k != 'roles'},
            role_names=[r['role'] for r in self.matrix['roles']], current_dates=list(self.current)))

    def _verify(self, *, full=False):
        b.need(all(stamp(p) == s for p, s in self._pins.items()), 'REVIEWED_INPUT_CUSTODY_CHANGED')
        b.need(self._review_seal == b.content_hash(self.review) and self._control_seal == self._control_hash(),
               'MUTATED_FROZEN_INPUT_CONTROL')
        if full:
            b.need(self._input_seal == b.content_hash(dict(matrix=self.matrix, current_dates=list(self.current))),
                   'MUTATED_FROZEN_INPUT_METADATA')
        self.publication.verify()

    def _current(self, day):
        value = self.current[day]
        b.need(self._current_seals[day] == b.content_hash(value), 'MUTATED_CURRENT_BINDING')
        raw = self.raw[day]
        b.need(self._raw_seals[day] == b.content_hash(raw.astype(str).values.tolist()), 'MUTATED_INDEPENDENT_C14_KEYS')
        events = [e for e in self.publication.support['events'] if e['event_id'] == value['support_epoch_event_id']]
        b.need(len(events) == 1, 'ONE_EXACT_ORIGINAL_EVENT_WITNESS_REQUIRED')
        pool = {k: copy.deepcopy(value[k]) for k in ('assets', 'asset_uids', 'asset_epochs', 'segment_starts')}
        pool['blocked_assets'] = {}
        exact = current_owner.bind_current(raw, pool, events[0], current_owner._clock(pd.Timestamp(day)),
            value['source_support_identity']['source_pins'], dependency=value['source_support_identity']['dependency'])
        b.need(exact == value, 'INDEPENDENT_C14_CURRENT_FULL_U_BINDING_CHANGED')
        return exact

    @staticmethod
    def _state_ref(meta):
        ref = meta.header['artifact_ref']; path = Path(ref['path']).resolve()
        b.need(path.is_relative_to(b.contract.B_RUN.resolve()) and path.suffix == '.joblib',
               'ORIGINAL_R5_NATIVE_STATE_ONLY')
        return ref, path

    def _rebind(self, requirement, original, current, day):
        h = original.header
        binding = dict(family=original.family, method=h['method'], recipe_sha256=original.recipe_sha256,
                       parameters=original.parameters, history_recipe=h['history_recipe'], representation=h['representation'])
        return b.bind_role_metadata(requirement, h, current, current_owner._clock(pd.Timestamp(day)), binding,
                                    original.publication_refs, required_dates=self.dates)

    def _get(self, role, day):
        self._verify()
        r = self.requirements[role]
        b.need(self._requirement_seals[role] == b.content_hash(r), 'MUTATED_FROZEN_ROLE_REQUIREMENT')
        b.need(r['current_status'] == 'WAITING_R5_PUBLICATION', 'FROZEN_ROLE_NOT_CURRENTLY_NUMERIC_QUALIFIABLE')
        current = self._current(day)
        # Original projector owns each native family/local-event/state admission.
        projected = b.project_r5_role(self.publication, r, current=current,
                                      decision_asof=current_owner._clock(pd.Timestamp(day)))
        projected.verify()
        ref, path = self._state_ref(projected)
        key = (projected.family, projected.header['risk_state_id'], str(path), ref['sha256'])
        b.need(key not in self._failed, 'ORIGINAL_NATIVE_INPUT_PREVIOUSLY_BLOCKED:' + self._failed.get(key, ''))
        identity = state_identity(projected)
        if key not in self._cache:
            before = stamp(path)
            try:
                self.counts['native_state_load_attempts'] += 1
                self.counts['risk_numeric_read'] += 1
                loaded = b.load_qualified_state(projected, self.publication, source_review=self.review)
                b.need(type(loaded) is b.NativeRiskPayload, 'ORIGINAL_SEALED_NATIVE_PAYLOAD_REQUIRED')
                loaded.verify()
                b._numeric_input(projected, loaded, self.raw[day].sort_values('raw_rank').security_uid.iloc[:40].tolist())
                b.need(stamp(path) == before and b.sha(path) == ref['sha256'] and stamp(path) == before,
                       'NATIVE_STATE_CHANGED_DURING_LOAD')
                # Immutable backing prevents changing values then resealing them.
                covariance = np.asarray(loaded['covariance'])
                immutable = np.frombuffer(covariance.tobytes(order='C'), dtype=covariance.dtype).reshape(covariance.shape)
                values = {k: copy.deepcopy(v) for k, v in loaded.values.items() if k != 'covariance'}
                values['covariance'] = immutable
                sealed = b.NativeRiskPayload(values, projected._seal, copy.deepcopy(loaded.artifact_ref), loaded.covariance_sha256)
                sealed.verify()
                self._cache[key] = dict(meta=projected, payload=sealed, identity=identity, stamp=before)
                self.counts['native_states_loaded'] += 1
            except Exception as error:
                self._failed[key] = type(error).__name__ + ':' + str(error)
                raise
        cached = self._cache[key]
        cached['meta'].verify(); cached['payload'].verify()
        b.need(cached['identity'] == identity and stamp(path) == cached['stamp'],
               'EXACT_CACHED_NATIVE_STATE_IDENTITY_OR_PHYSICAL_PIN_CHANGED')
        meta = self._rebind(r, cached['meta'], current, day)
        b.need(state_identity(meta) == cached['identity'], 'DAILY_ROLE_REBIND_CHANGED_NATIVE_COORDINATE')
        values = {k: copy.deepcopy(v) for k, v in cached['payload'].values.items() if k != 'covariance'}
        values['covariance'] = cached['payload']['covariance']
        payload = b.NativeRiskPayload(values, meta._seal, copy.deepcopy(cached['payload'].artifact_ref),
                                      cached['payload'].covariance_sha256)
        b._numeric_input(meta, payload, self.raw[day].sort_values('raw_rank').security_uid.iloc[:40].tolist())
        self.counts['daily_role_bindings'] += 1
        return meta, payload

    def qualify(self):
        """Attempt every frozen WAITING role; one failed input never activates it."""
        b.need(not self._qualified, 'INPUT_QUALIFICATION_IS_SINGLE_PASS_NO_IMPLICIT_RETRY')
        self._verify(full=True)
        for r in self.matrix['roles']:
            role = r['role']; states = []; reason = list(r['missing_inputs'])
            status = r['current_status']
            if status == 'WAITING_R5_PUBLICATION':
                try:
                    for day in self.dates:
                        meta, _ = self._get(role, day)
                        states.append(dict(decision_date=day, state_ref=copy.deepcopy(meta.header['artifact_ref']),
                            header_qualified=True, current_UID_qualified=True, numeric_qualified=True,
                            full_U_keys_sha256=meta.current['c14_current_key_sha256'],
                            native_as_of=meta.header['as_of'], native_cutoff=meta.header['cutoff']))
                    status, reason = 'FULL752_NUMERIC_INPUT_QUALIFIED', []
                except Exception as error:
                    status = 'PARTIAL_INPUT_BLOCKED' if states else 'BLOCKED_INPUT'
                    reason = [type(error).__name__ + ':' + str(error)]
            full = status == 'FULL752_NUMERIC_INPUT_QUALIFIED' and len(states) == 752
            self._gates[role] = dict(phase=status, research_id=b.contract.ID, role=role,
                family=r['required_family_method'], design_sha256=b.DESIGN_SHA, dag_sha256=b.DAG_SHA,
                source_review=copy.deepcopy(self.review_ref), full_required_dates_qualified=full,
                calendar_positions=752, full_risk_mature_positions=732, learned_positions=482,
                states=states, reasons=reason, realized_endpoint_qualified=False,
                selector_fit=0, solver=0, test2026_rows_read=0, strict_PIT_promotion_eligible=False)
        self._verify(full=True)
        self._qualified = True
        return self.status()

    def role_gate(self, role):
        """Return the same full752 input gate for membership/veto consumers."""
        self._verify()
        b.need(self._qualified and role in self._gates
               and self._gates[role]['full_required_dates_qualified'] is True,
               'FULL752_NUMERIC_ROLE_QUALIFICATION_REQUIRED')
        return copy.deepcopy(self._gates[role])

    def get_risk(self, role, day):
        """Only a completed full752 role can serve its already qualified inputs."""
        day = day_token(day)
        b.need(self._qualified and role in self._gates and self._gates[role]['full_required_dates_qualified'] is True
               and day in self.dates, 'FULL752_NUMERIC_ROLE_QUALIFICATION_REQUIRED')
        return self._get(role, day)

    def status(self):
        return dict(research_id=b.contract.ID, roles=copy.deepcopy(self._gates), counts=copy.deepcopy(self.counts),
                    strict_PIT_promotion_eligible=False, realized_endpoint_qualified=False)