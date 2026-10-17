"""The two frozen C14 risk hybrids composed from existing fit/decode owners.

No estimator, loss, capacity rule, matcher or risk producer is implemented here.
All 752 native inputs must have an independent journal activation before labels
are read. Original ML files and reservations are never opened or rewritten.
"""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training import selector_maximal_breadth as owner
from scripts.research.a2.training.selector_maximal_risk_journal import OWNER_SHA
from scripts.research.a2.data import selector_maximal_risk_binding as risk
from scripts.research.a2.data.selector_shared_risk_consumer import decision_close
from scripts.research.a2.risk import event_risk_contract_r5 as event

ROLES = {'C14_RX_HGB_LW': ('HGB', 'LW'), 'C14_RX_XGB_QQQ_RESIDUAL': ('XGB', 'QQQ_RESIDUAL')}
CUTS = ('2023-07-01', '2024-01-01', '2024-07-01', '2025-01-01')
CALENDAR_DATES, OUTER_DATES = 752, 502
COORDS = ('native_family_marginal_variance', 'covariance_with_equal_Raw20')


def feature_order():
    columns = [f'{side}__{name}' for side in ('challenger', 'incumbent', 'delta') for name in COORDS]
    return owner.feature_order() + columns + [c + '__missing' for c in columns]


def qualified_features(raw, geometry, base_x, role, get_risk, journal):
    owner.require(role in journal.roles, 'FULL752_NUMERIC_JOURNAL_ACTIVATION_REQUIRED')
    journal.verify()
    dates = tuple(d.isoformat() for d in sorted(raw.signal_date.unique()))
    owner.require(len(dates) == CALENDAR_DATES and dates == tuple(journal.dates), 'EXACT752_INPUT_DATE_MASK_REQUIRED')
    owner.require(geometry.signal_date.isin(raw.signal_date).all()
                  and len(geometry) == CALENDAR_DATES * 200, 'WHOLE752_BY200_GEOMETRY_REQUIRED')
    xx = np.asarray(base_x, float)
    owner.require(xx.shape == (len(geometry), 216) and np.isfinite(xx).all(), 'FINITE_FROZEN_CURRENT216_REQUIRED')
    extra = np.empty((len(geometry), 12), float)
    for day, ix in geometry.groupby('signal_date', sort=True).indices.items():
        frame = raw.loc[raw.signal_date.eq(day)].sort_values('raw_rank')
        meta, payload = get_risk(role, day)
        owner.require(meta.role == role and meta.family == ROLES[role][1]
                      and risk.clock(meta.decision_asof) == risk.clock(decision_close(day)),
                      'EXACT_ROLE_FAMILY_CURRENT_RISK_CLOSE_REQUIRED')
        uids = risk._consumer_uids(meta)
        owner.require(set(frame.security_uid) == set(uids) and len(frame) == len(uids), 'HYBRID_EXACT_CURRENT_FULL_U_REQUIRED')
        positions = {uid: i for i, uid in enumerate(uids)}
        values = risk.hybrid_coordinates(meta, payload, frame.security_uid.iloc[:40].tolist())
        pair = geometry.iloc[ix]
        extra[ix] = risk.pair_risk_columns(values, pair.challenger_uid.map(positions).to_numpy(), pair.incumbent_uid.map(positions).to_numpy())
    owner.require(np.isfinite(extra).all(), 'ALL752_NATIVE_RISK12_REQUIRED_BEFORE_LABELS')
    return np.column_stack((xx, extra))


def fit_owners(run, role, journal, kernel):
    """Bind byte-identical owners to the original conditional node namespace."""
    head, family = ROLES[role]
    columns = feature_order()
    def stored_fit(_ledger, node, identity, _old_path, fit):
        parts = node.split('|')
        if parts[0] == 'SCALER':
            actual = 'RX_SCALER|' + role + '|' + parts[1]
        else:
            owner.require(parts[:2] == ['MODEL', head], 'EXACT_FROZEN_HYBRID_NODE_REQUIRED')
            actual = '|'.join(['RX_MODEL', role, *parts[2:]])
        identity = dict(identity, role=role, risk_family=family,
                        risk_input_qualification=journal.roles[role]['qualification_ref']['sha256'])
        path = Path(run) / 'risk_execution' / 'models' / (owner.content_hash(actual) + '.joblib')
        return journal.stored_fit(actual, identity, path, fit)
    def identity(*args, **kwargs):
        value = owner.model_identity(*args, **kwargs)
        value['feature_order'] = columns
        return value
    scaler = event.bind_pinned_kernel(owner.scaler_at, physical_path=owner.__file__, expected_sha256=OWNER_SHA,
        dependencies=dict(feature_order=lambda: columns, stored_fit=stored_fit))
    bundle = event.bind_pinned_kernel(owner.fit_bundle, physical_path=owner.__file__, expected_sha256=OWNER_SHA,
        dependencies=dict(stored_fit=stored_fit, model_identity=identity))
    def component(*args, **kwargs):
        return kernel.fit_component(*args, **kwargs, input_feature_count=228)
    bound_kernel = SimpleNamespace(capacity_specs=lambda: kernel.capacity_specs(input_feature_count=228),
        component_specs=kernel.component_specs, fit_component=component,
        predict_component=kernel.predict_component, combine_predictions=kernel.combine_predictions)
    return scaler, bundle, bound_kernel


def execute_hybrid(run, design, q, raw, geometry, base_x, role, get_risk, journal, kernel, runtime, *, artifact_root=None):
    """Execute only one activated frozen hybrid; runtime is retained predictor owner."""
    owner.require(role in ROLES, 'ONLY_TWO_QUALIFIED_FROZEN_RX_ROLES')
    owner.require(design['research_id'] == q['research_id'] == owner.ID and Path(run).resolve() == journal.run,
                  'ORIGINAL_C14_IDENTITY_REQUIRED')
    head, family = ROLES[role]
    owner.require(dict(candidate_id=role, head=head, family=family) in design['risk']['hybrid_bindings']
                  and design['risk']['hybrid_feature_recipe']['input_columns'] == 228
                  and design['risk']['hybrid_feature_recipe']['new_per_asset'] == list(COORDS), 'FROZEN_HYBRID_RECIPE_CHANGED')
    owner.require(q['pair_key_sha256'] == owner.pairs.pair_key_sha256(geometry), 'FROZEN_PAIR_KEY_CHANGED')
    base = Path(run) / 'risk_execution' if artifact_root is None else Path(artifact_root).resolve()
    owner.require(base.resolve() in {(Path(run)/'risk_execution').resolve(),
        (Path(run)/'risk_execution/source_metadata_recovery_r1').resolve(),
        (Path(run)/'risk_execution/source_guard_recovery_r1').resolve()}, 'EXACT_CONDITIONAL_ARTIFACT_ROOT_REQUIRED')
    root = base / role
    assert_safe_output_path(root, kind='backtest', paths=resolve(owner.REPO))
    raw = raw.copy(); geometry = geometry.copy()
    raw['signal_date'] = pd.to_datetime(raw.signal_date); geometry['signal_date'] = pd.to_datetime(geometry.signal_date)
    owner.require(raw.signal_date.lt('2026-01-01').all() and geometry.signal_date.lt('2026-01-01').all(), 'PRE2026_ONLY_HYBRID_INPUT')
    xx = qualified_features(raw, geometry, base_x, role, get_risk, journal)
    scaler_fit, bundle_fit, bound_kernel = fit_owners(run, role, journal, kernel)
    labels, records, choices, native, outer, lineage = {}, [], {}, {}, {}, {}
    def load(cut):
        if cut not in labels:
            labels[cut] = owner.label_pairs(run, design, q, cut)
        return labels[cut]
    for c, end in zip(CUTS, (*CUTS[1:], '2026-01-01')):
        if c == CUTS[-1] and choices.get(2025) is None:
            continue
        train, y, tasks, ends, receipt = load(c)
        owner.require(pd.to_datetime(ends).lt(c).all(), 'STRICT_HYBRID_TRAIN_MATURITY_REQUIRED')
        tx = owner.aligned_training(train, geometry, xx)
        scaler = scaler_fit(run, journal.fit_ledger, c, train, tx, q)
        vg = geometry.loc[geometry.signal_date.ge(c) & geometry.signal_date.lt(end)].reset_index(drop=True)
        caps = owner.CAPACITIES if c != CUTS[-1] else (choices[2025],)
        for cap in caps:
            values = None if scaler is None else bundle_fit(run, journal.fit_ledger, bound_kernel, head, cap, c,
                train, tx, y, tasks, scaler, scaler.transform(owner.aligned_training(vg, geometry, xx)), runtime, q,
                selected=c == CUTS[-1])
            if values is None:
                if c != CUTS[-1]:
                    records.append(dict(paradigm=head, capacity=cap, fit_cutoff=c, validation_end=end,
                                        status='BLOCKED_DEPENDENCY', dates=0, reason='REQUIRED_SCALER_OR_COMPONENT_FAILED'))
                continue
            table = owner.table_prediction(vg, values, c, cap, head)
            native[(c, cap)] = table
            lineage[f'{c}|{cap}'] = dict(cutoff=c, capacity=cap, source_kind='MODEL_OOF', genuine_oof=True,
                train_pair_key_sha256=owner.pairs.pair_key_sha256(train), prediction_pair_key_sha256=owner.pairs.pair_key_sha256(vg),
                feature_count=228, spec=bound_kernel.capacity_specs()[head][cap],
                scaler_node=f'RX_SCALER|{role}|{c}', model_node=f'RX_MODEL|{role}|{c}|{"SELECTED" if c == CUTS[-1] else cap}|20260928|None',
                label_receipt=receipt)
            if c != CUTS[-1]:
                full, vy, vt, ve, _ = load(end)
                valid = full.loc[full.signal_date.ge(c)].reset_index(drop=True)
                keys = list(owner.PAIR_KEYS)
                yi = pd.MultiIndex.from_frame(full[keys]).get_indexer(pd.MultiIndex.from_frame(valid[keys]))
                pi = pd.MultiIndex.from_frame(vg[keys]).get_indexer(pd.MultiIndex.from_frame(valid[keys]))
                owner.require((yi >= 0).all() and (pi >= 0).all(), 'WHOLE_INNER_KEY_ALIGNMENT_REQUIRED')
                records.append(owner.inner_record(run, head, cap, c, end, valid,
                    {k: a[pi] for k, a in values.items()}, vy[yi], vt[yi], ve.iloc[yi], raw))
        if c == CUTS[0]:
            choices[2024] = owner.choose_capacity(records, [(CUTS[0], CUTS[1])])[0]
        if c == CUTS[2]:
            selected = [r for r in records if r['fit_cutoff'] in CUTS[1:3]]
            choices[2025] = owner.choose_capacity(selected, [(CUTS[1], CUTS[2]), (CUTS[2], CUTS[3])])[0]
        if c in (CUTS[1], CUTS[-1]):
            year = int(c[:4]); cap = choices.get(year)
            if cap is None or scaler is None:
                continue
            future = geometry.loc[geometry.signal_date.dt.year.eq(year)].reset_index(drop=True)
            values = owner.values_from_table(native[(c, cap)]) if year == 2025 and (c, cap) in native else bundle_fit(
                run, journal.fit_ledger, bound_kernel, head, cap, c, train, tx, y, tasks, scaler,
                scaler.transform(owner.aligned_training(future, geometry, xx)), runtime, q, selected=year == 2025)
            if values is not None:
                outer[year] = (future, values, owner.table_prediction(future, values, c, cap, head))
    journal.block_remaining(role, 'REQUIRED_UPSTREAM_FIT_OR_CAPACITY_UNAVAILABLE')
    failure = None
    if set(outer) != {2024, 2025}:
        failure = 'BLOCKED_INCOMPLETE_LEARNED_OUTER_NO_RAW_SUCCESS'
    panel_parts, matches, native_parts = [], [], []
    if failure is None:
        fallback = raw.loc[raw.signal_date.dt.year.eq(2023)].copy()
        fallback['score'] = fallback.raw_score; fallback['rank'] = fallback.raw_rank; fallback['candidate_id'] = role
        panel_parts.append(fallback)
        try:
            for year in (2024, 2025):
                g, values, table = outer[year]
                score, eligible = owner.decision_values(values, 'U0_POINT_GT0')
                for day, ix in g.groupby('signal_date', sort=True).indices.items():
                    panel, matching = journal.checkpoint_decode(f'HYBRID|{role}|{day.isoformat()}',
                        raw.loc[raw.signal_date.eq(day)], g.iloc[ix], score[ix], role, eligible[ix])
                    panel_parts.append(panel); matches.append(matching)
                native_parts.append(table)
        except Exception as error:
            failure = f'{type(error).__name__}:{error}'
    result = dict(status='HYBRID_COMPLETE' if failure is None else 'HYBRID_FAILED', research_id=owner.ID,
        role=role, head=head, family=family, feature_count=228, feature_order=feature_order(),
        complete_candidates=[] if failure else [role], failed_or_untestable={role:failure} if failure else {},
        panels={}, native_pair_predictions={}, capacity_selection=dict(records=records, choices={str(y):v for y,v in choices.items()}),
        oof_lineage=lineage, fit_failures={n:{k:s.get(k) for k in ('status','entered','error')} for n,s in journal.slots.items()
            if s['candidate_id'] == role and s['status'] in ('FAILED','BLOCKED_DEPENDENCY')},
        forecast2026_rows=0, strict_PIT_promotion_eligible=False, scientific_retry=0)
    if failure is None:
        panel = pd.concat(panel_parts, ignore_index=True)[[*owner.KEYS,'ticker','U_t_fingerprint','score','rank','candidate_id']]
        forecast = pd.concat(native_parts, ignore_index=True); matched = pd.concat(matches, ignore_index=True)
        owner.require(forecast.signal_date.nunique() == OUTER_DATES and panel.signal_date.nunique() == CALENDAR_DATES
                      and len(panel) == len(raw), 'COMPLETE752_PANEL_502_LEARNED_DATES_REQUIRED')
        pref = owner.write_table(root / 'scores_pre2026.parquet', panel)
        pref.update(calendar_dates=CALENDAR_DATES, common_rows=len(raw), raw_fallback_2023_exact=True)
        nref = owner.write_table(root / 'native_pairs_pre2026.parquet', forecast)
        mref = owner.write_table(root / 'matching_pre2026.parquet', matched)
        result['panels'][role] = pref
        result['native_pair_predictions'][role] = dict(nref, kind='U0_POINT_GT0', matching_path=mref['path'], matching_sha256=mref['sha256'])
    owner.write_json(root / 'HYBRID_ASSEMBLY.json', result)
    return result
