"""Synthetic event-date/provenance/coverage integration; never call real reader."""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.factors import economic_return_features as features
from scripts.research.a2.factors import economic_return_targets as targets
from scripts.research.a2.factors import economic_return_preflight as stage
from scripts.research.a2.factors import issuer_date_revision_preflight as wrapper


def fixture():
    calendar = pd.bdate_range('2020-01-02', '2021-07-02').difference(pd.to_datetime(['2021-05-31']))
    raw = pd.DataFrame([(date, ticker, 100.) for date in calendar for ticker in ('TAC', 'ABC', 'QQQ')],
                       columns=['trade_date', 'ticker', 'close'])
    dates = calendar[(calendar >= '2021-05-10') & (calendar <= '2021-06-04')]
    panel = pd.DataFrame([(date, ticker) for date in dates for ticker in ('TAC', 'ABC')],
                         columns=['signal_date', 'ticker'])
    panel['target_end_date'] = panel.signal_date.map(pd.Series(calendar, index=calendar).shift(-20))
    row = dict.fromkeys(features.ACTION_FIELDS, np.nan)
    row.update(code='US.TAC', ex_div_date=pd.Timestamp('2021-05-31'), per_cash_div=.03723,
               forward_adj_factorA=1., forward_adj_factorB=-.03723)
    events = pd.DataFrame([row], index=[87])
    bindings = {'equities': [{'ticker': t, 'moomoo_transport_code': 'US.'+t} for t in ('TAC', 'ABC')],
                'QQQ': {'ticker': 'QQQ', 'moomoo_transport_code': 'US.QQQ'},
                'rehab': {'path': 'synthetic-original-archive', 'sha256': 'synthetic-original-hash'}}
    query = pd.DataFrame({'code': ['US.TAC', 'US.ABC', 'US.QQQ'], 'status': 'PASS', 'row_count': [1, 0, 0]})
    contract = {'cohort': {'rows': len(panel), 'dates': len(dates), 'names_per_date': 2,
            'first_date': str(dates.min().date()), 'last_date': str(dates.max().date()),
            'key_sha256': stage.key_fingerprint(panel)},
        'action_schema_basis': stage.ARCHIVE_SCHEMA, 'event_identity_conditioning': stage.TRANSPORT_CONDITION,
        'event_query_scope': stage.QUERY_SCOPE, 'start_inclusive': '2020-01-01',
        'sdk_schema': {'path': 'synthetic-sdk', 'sha256': 'synthetic-sdk-hash'},
        'rehab_status': {'path': 'synthetic-query-status', 'sha256': 'synthetic-status-hash'}}
    revision = {'correction': dict(wrapper.RULE), 'evidence_review': {'path': 'synthetic-review', 'sha256': 'synthetic-review-hash'},
                'event_audit': {'path': 'synthetic-audit', 'sha256': 'synthetic-audit-hash'}}
    return raw, events, panel, calendar, bindings, query, contract, revision


def test_exactly_one_original_cell_changes_and_both_dates_provenance_survive():
    _, events, _, calendar, bindings, query, contract, revision = fixture()
    original, old_bindings = events.copy(deep=True), copy.deepcopy(bindings)
    derived, change = wrapper.revise_event_metadata(events, calendar, revision)
    pd.testing.assert_frame_equal(events, original)
    assert derived.index.equals(events.index) and change['changed_original_cells'] == 1
    restored = derived[events.columns].copy()
    restored.loc[87, 'ex_div_date'] = pd.Timestamp('2021-05-31')
    pd.testing.assert_frame_equal(restored, original, check_exact=True)
    assert derived.loc[87, 'vendor_ex_div_date'] == pd.Timestamp('2021-05-31')
    assert derived.loc[87, 'ex_div_date'] == pd.Timestamp('2021-05-28')
    assert derived.loc[87, 'issuer_date_source_url'] == wrapper.ISSUER_URL
    copied, lineage = wrapper.derived_stage_bindings(bindings, revision, 'synthetic-revision-hash')
    assert bindings == old_bindings and copied['rehab']['sha256'] != bindings['rehab']['sha256']
    assert lineage['original_archive'] == bindings['rehab']
    proxy = wrapper.features_with_revision_provenance(features, bindings)
    classified, _, _ = stage.event_evidence(derived, copied, query, contract, proxy)
    assert classified.source_type.tolist() == ['DERIVED_VENDOR_ARCHIVE_WITH_ISSUER_DATE_CORRECTION']
    assert 'DERIVED_ISSUER_DATE_REVISION' in classified.source_reference.iloc[0]
    assert classified.event_status.tolist() == ['UNCONFIRMED_CASH_UNIT']
    assert not classified.event_supported.any()


def test_revision_only_unblocks_date_validation_keeps_all_keys_and_strict_zero():
    raw, events, panel, calendar, bindings, query, contract, revision = fixture()
    with pytest.raises(ValueError, match='active event date outside'):
        stage.stage_coverage(raw, events, panel, calendar, bindings, query, contract, features, targets)
    derived, _ = wrapper.revise_event_metadata(events, calendar, revision)
    copied, _ = wrapper.derived_stage_bindings(bindings, revision, 'synthetic-revision-hash')
    masks, summary = stage.stage_coverage(raw, derived, panel, calendar, copied, query, contract,
        wrapper.features_with_revision_provenance(features, bindings), targets)
    pd.testing.assert_frame_equal(masks[['signal_date', 'ticker']], panel[['signal_date', 'ticker']])
    assert stage.key_fingerprint(masks) == contract['cohort']['key_sha256']
    assert summary['strict_valid_label_rows'] == 0 and not masks.strict_target_valid.any()
    assert summary['event_status_counts'] == {'UNCONFIRMED_CASH_UNIT': 1}
    assert summary['fits_added'] == summary['candidate_comparisons_added'] == 0
    assert masks.transport_target_valid.sum() < len(masks)  # no forced PASS
    assert all(f'economic_stock_return_{h}d' not in masks for h in (3, 5, 10, 20))


def test_other_off_calendar_event_still_fails_without_generic_mapping():
    raw, events, panel, calendar, bindings, query, contract, revision = fixture()
    extra = events.iloc[0].copy()
    extra['code'], extra['ex_div_date'] = 'US.ABC', pd.Timestamp('2021-05-30')
    events = pd.concat([events, pd.DataFrame([extra], index=[15])])
    query.loc[query.code.eq('US.ABC'), 'row_count'] = 1
    derived, _ = wrapper.revise_event_metadata(events, calendar, revision)
    assert derived.loc[15, 'ex_div_date'] == pd.Timestamp('2021-05-30')
    copied, _ = wrapper.derived_stage_bindings(bindings, revision, 'synthetic-revision-hash')
    classified, _, _ = stage.event_evidence(derived, copied, query, contract,
        wrapper.features_with_revision_provenance(features, bindings))
    unchanged = classified.loc[classified.ticker.eq('ABC')].iloc[0]
    assert unchanged.source_type == 'PINNED_VENDOR_REHAB_ARCHIVE'
    assert unchanged.source_reference == bindings['rehab']['path']
    assert unchanged.source_fingerprint == bindings['rehab']['sha256']
    with pytest.raises(ValueError, match='active event date outside'):
        stage.stage_coverage(raw, derived, panel, calendar, copied, query, contract,
            wrapper.features_with_revision_provenance(features, bindings), targets)


@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'collision', 'cash'])
def test_exact_original_record_guard_rejects_ambiguous_or_changed_event(problem):
    _, events, _, calendar, _, _, _, revision = fixture()
    if problem == 'missing':
        events = events.iloc[:0]
    elif problem == 'duplicate':
        events = pd.concat([events, events])
    elif problem == 'collision':
        extra = events.copy(); extra['ex_div_date'] = pd.Timestamp('2021-05-28')
        events = pd.concat([events, extra], ignore_index=True)
    else:
        events.loc[87, 'per_cash_div'] = .045
    with pytest.raises(RuntimeError):
        wrapper.revise_event_metadata(events, calendar, revision)


def test_unfrozen_revision_rejected_before_import_or_original_reader(tmp_path, monkeypatch):
    path = tmp_path / 'revision.json'
    path.write_text(json.dumps({'status': 'DRAFT'}))
    monkeypatch.setattr(wrapper.importlib.util, 'spec_from_file_location', lambda *a, **k: pytest.fail('early import'))
    with pytest.raises(RuntimeError, match='NOT_FROZEN'):
        wrapper.setup(path)
