import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location('raw_display_subject',
    Path(__file__).parents[1] / 'adapters/raw_stock_price_reader.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def frame(open=9.54, close=9.85, date='2026-09-22'):
    return pd.DataFrame([dict(trade_date=pd.Timestamp(date), open=open,
        close=close, high=max(open, close), low=min(open, close), volume=123)])


def test_quotes_remain_dollars_and_dates_are_not_filled():
    rows = subject._combine([frame(), frame(10., 11., '2026-09-24')], 'CHPT', '2026-09-22', '2026-09-24')
    assert [row['date'] for row in rows] == ['2026-09-22', '2026-09-24']
    assert rows[0]['raw_open'] == 9.54
    assert rows[0]['raw_close'] == 9.85
    assert rows[0]['currency'] == 'USD'
    assert rows[0]['adjustment'] == 'RAW'


def test_conflicting_vintages_are_not_silently_selected():
    with pytest.raises(ValueError, match='CONFLICTING_OVERLAP_RAW_PRICE'):
        subject._combine([frame(), frame(open=9.55)], 'CHPT', '2026-09-22', '2026-09-22')


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 0., -1.])
def test_invalid_quote_never_appears_as_usd(value):
    with pytest.raises(ValueError, match='RAW_DISPLAY_INVALID_PRICE'):
        subject._combine([frame(open=value)], 'CHPT', '2026-09-22', '2026-09-22')


def test_hash_failure_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(subject, '_checked_json', lambda ref: (_ for _ in ()).throw(
        ValueError('RAW_DISPLAY_REFERENCE_HASH_MISMATCH')))
    result = subject.read_raw_stock_prices({}, 'CHPT', '2026-09-22', '2026-09-22', paths=object())
    assert result['status'] == 'UNAVAILABLE'
    assert result['rows'] == ()
    assert result['error'] == 'RAW_DISPLAY_REFERENCE_HASH_MISMATCH'


def test_reverse_split_preserves_real_quotes_and_only_rebases_before_event():
    rows = subject._combine([frame(.65, .70, '2025-07-25'),
                             frame(13., 14., '2025-07-28')], 'CHPT', '2025-07-25', '2025-07-28')
    actions = [dict(event_date='2025-07-28', price_multiplier=20.)]
    adjusted = subject._with_split_display(rows, actions, '2025-07-28')
    assert adjusted[0]['raw_open'] == .65
    assert adjusted[0]['split_adjusted_open'] == 13.
    assert adjusted[1]['split_adjusted_open'] == 13.
    assert adjusted[1]['raw_open'] == 13.
    before = subject._with_split_display(rows[:1], actions, '2025-07-25')
    assert before[0]['split_adjusted_open'] == .65


def binding_fixture(monkeypatch):
    from scripts.research.a2.evaluation import demo_performance_prices
    from types import SimpleNamespace
    refs = lambda path: dict(path=path, sha256='hash')
    h = dict(start_date='2023-01-03', outputs={'ranked': refs('full-ranked')}, price_manifest=refs('inputs'))
    a2 = dict(source_id='A2_UPDATED_RESEARCH', ranking_end_date='2026-09-22',
        ranking_manifest=refs('hist'), evaluation_contract=refs('contract'))
    entry = dict(ticker='CHPT', cusips=['OLD', 'NEW'], code='US.CHPT')
    docs = {'a2': a2, 'hist': h, 'contract': {'ranking_manifest': refs('hist')}, 'inputs': {'lineage': [entry]}}
    monkeypatch.setattr(subject, '_checked_json', lambda ref: docs[ref['path']])
    monkeypatch.setattr(subject.base, '_ref', lambda ref: (ref['path'], ref['sha256']))
    monkeypatch.setattr(subject.base, '_hash', lambda path: 'hash')
    seen = []
    def table(path, **kwargs):
        seen.append(path)
        return SimpleNamespace(to_pylist=lambda: [dict(target_date='2023-01-03', security_id='OLD'),
            dict(target_date='2026-09-22', security_id='NEW')])
    monkeypatch.setattr(subject.base.pq, 'read_table', table)
    monkeypatch.setattr(demo_performance_prices, '_raw', lambda *args: frame())
    monkeypatch.setattr(subject, '_split_actions', lambda *args: [])
    return refs('a2'), seen


def test_reader_uses_full_ranked_and_date_bounded_identity(monkeypatch):
    ref, seen = binding_fixture(monkeypatch)
    result = subject.read_raw_stock_prices(ref, 'CHPT', '2026-09-01', '2026-09-22', paths=object())
    assert result['status'] == 'READY'
    assert seen == ['full-ranked']
    assert result['rows'][0]['raw_open'] == 9.54
    assert result['rows'][0]['raw_close'] == 9.85


def test_unproven_multi_cusip_range_stays_ambiguous(monkeypatch):
    ref, _ = binding_fixture(monkeypatch)
    result = subject.read_raw_stock_prices(ref, 'CHPT', '2023-01-03', '2026-09-22', paths=object())
    assert result['status'] == 'UNAVAILABLE'
    assert result['error'] == 'RAW_DISPLAY_AMBIGUOUS_SECURITY_IDENTITY'


def test_explicit_identity_must_exist_in_requested_period(monkeypatch):
    ref, _ = binding_fixture(monkeypatch)
    result = subject.read_raw_stock_prices(ref, 'CHPT', '2026-09-01', '2026-09-22',
        paths=object(), security_id='OLD')
    assert result['status'] == 'UNAVAILABLE'
    assert result['error'] == 'RAW_DISPLAY_SECURITY_IDENTITY_MISMATCH'


def test_split_reader_excludes_future_noop_and_reports_mixed_action(monkeypatch):
    from types import SimpleNamespace
    records = [dict(code='US.X', ex_div_date=day, join_base=old, join_ert=new,
                    forward_adj_factorA=a, forward_adj_factorB=b)
               for day, old, new, a, b in [('2025-01-02', 1., 1., 1., 0.),
                   ('2025-01-03', 20., 1., 20., .5),
                   ('2025-01-04', 20., 1., 20., 0.),
                   ('2027-01-01', 10., 1., 10., 0.)]]
    monkeypatch.setattr(subject.base.pq, 'read_schema', lambda _: SimpleNamespace(names=list(records[0])))
    monkeypatch.setattr(subject.base.pq, 'read_table', lambda _, **kwargs: SimpleNamespace(
        to_pandas=lambda: pd.DataFrame(records)[kwargs['columns']]))
    result = subject._split_actions(dict(code='US.X', rehab=dict(path='p', sha256='s')),
        lambda *args: 'p', '2026-09-22')
    assert [row['event_date'] for row in result] == ['2025-01-03', '2025-01-04']
    assert result[0]['price_multiplier'] is None
    assert result[1]['price_multiplier'] == 20.


def test_identity_chain_is_not_enabled_for_unknown_ticker_or_changed_evidence(monkeypatch):
    spec = importlib.util.spec_from_file_location('identity_display_subject',
        Path(__file__).parents[1] / 'adapters/stock_identity_display.py')
    identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(identity)
    assert identity.read_identity_chain({}, 'UNKNOWN')['status'] == 'UNVERIFIED'
    monkeypatch.setattr(identity, '_json', lambda ref: (_ for _ in ()).throw(ValueError('changed evidence')))
    assert identity.read_identity_chain({}, 'CHPT')['status'] == 'UNVERIFIED'
    with pytest.raises(ValueError):
        identity.validate_identity_chain({'status': 'VERIFIED', 'ticker': 'CHPT', 'parent_a2_manifest': {}})


def anchored(ticker='AMD', identity=None, anchor_sha='original'):
    row = dict(ticker=ticker, code='US.' + ticker, anchor_date='2020-01-02',
        raw_sources=[dict(path='raw.parquet', sha256=anchor_sha, role='ORIGINAL_ANCHOR')])
    if identity is not None:
        row['cusips'] = [identity]
    return row


def test_current_missing_identity_reuses_exact_bound_original_anchor():
    historical = anchored(identity='007903107')
    current = anchored()
    result = subject._bind_current_identity(current, [historical])
    assert result['security_ids'] == ['007903107']
    assert 'security_ids' not in current
    assert result['raw_sources'] is current['raw_sources']


@pytest.mark.parametrize('change', [dict(code='US.OTHER'), dict(anchor_date='2020-01-03'),
    dict(raw_sources=[dict(path='raw.parquet', sha256='different', role='ORIGINAL_ANCHOR')]),
    dict(raw_sources=[])])
def test_changed_original_anchor_never_inherits_security_identity(change):
    with pytest.raises(ValueError, match='CURRENT_IDENTITY_ANCHOR_UNPROVEN'):
        subject._bind_current_identity({**anchored(), **change}, [anchored(identity='007903107')])


def test_explicit_current_identity_is_never_overwritten_by_historical_identity():
    current = anchored(identity='DIFFERENT')
    assert subject._bind_current_identity(current, [anchored(identity='007903107')]) is current


def test_duplicate_original_anchor_identity_stays_unproven():
    with pytest.raises(ValueError, match='CURRENT_IDENTITY_ANCHOR_UNPROVEN'):
        subject._bind_current_identity(anchored(), [anchored(identity='ONE'), anchored(identity='TWO')])


def test_execution_input_binding_rejects_changed_date_and_duplicate_bridge(monkeypatch):
    value = dict(end_date='2026-09-22', price_basis='PIT_FORWARD_REHAB_INDEX',
        execution_bridges=[dict(ticker='HIVE')])
    monkeypatch.setattr(subject, '_checked_json', lambda _: value)
    assert subject._execution_bridges({'price_inputs': {}}, {'data_date': '2026-09-22'}, 'HIVE') == ()
    contract = {'price_inputs': {'path': 'prices'}}
    assert len(subject._execution_bridges(contract, {'data_date': '2026-09-22'}, 'HIVE')) == 1
    with pytest.raises(ValueError, match='EXECUTION_INPUT_BINDING_INVALID'):
        subject._execution_bridges(contract, {'data_date': '2026-09-23'}, 'HIVE')
    value['execution_bridges'].append(dict(ticker='HIVE'))
    with pytest.raises(ValueError, match='DUPLICATE_EXECUTION_BRIDGE'):
        subject._execution_bridges(contract, {'data_date': '2026-09-22'}, 'HIVE')


def test_recorded_raw_bridge_revalidates_proof_and_all_immutable_leaves(monkeypatch):
    from scripts.research.a2.evaluation import demo_performance_prices as prices
    native = frame(date='2026-09-21')
    tail = frame(date='2026-09-22')
    proof = dict(normalized_path='normalized', normalized_sha256='normalized-sha',
        provider_symbol='HIVE', provider_mapping={'provider_symbol': 'HIVE'},
        raw_inputs=[dict(path='raw', sha256='raw-sha', date='2026-09-22', observed_at='clock',
            checkpoint_path='checkpoint', checkpoint_sha256='checkpoint-sha')],
        gate=prices.EXECUTION_GATE, consumer_fields=['open', 'close'],
        model_feature_eligibility_granted=False, tail_end='2026-09-22')
    bridge = dict(ticker='HIVE', target_date='2026-09-22', historical_end='2026-09-21',
        model_feature_eligibility_granted=False, qualification=proof)
    seen = []
    def qualify(record, original, ticker, target, store, cache):
        assert record['ticker'] == ticker == 'HIVE'
        assert record['source_sha256'] == 'normalized-sha'
        assert record['lineage']['vintage_semantics'] == 'CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT'
        assert original is native and target == '2026-09-22'
        return tail, dict(proof)
    monkeypatch.setattr(prices, 'qualify_execution_massive_tail', qualify)
    verify = lambda path, digest: seen.append((path, digest))
    result = prices.replay_recorded_execution_bridge(bridge, native, 'HIVE', '2026-09-22', verify, object())
    assert result is tail
    assert seen == [('normalized', 'normalized-sha'), ('raw', 'raw-sha'), ('checkpoint', 'checkpoint-sha')]
    monkeypatch.setattr(prices, 'qualify_execution_massive_tail', lambda *args: (tail, {**proof, 'tail_end': 'changed'}))
    with pytest.raises(ValueError, match='QUALIFICATION_CHANGED'):
        prices.replay_recorded_execution_bridge(bridge, native, 'HIVE', '2026-09-22', verify, object())
    with pytest.raises(ValueError, match='DISPLAY_BRIDGE_BINDING_INVALID'):
        prices.replay_recorded_execution_bridge({**bridge, 'model_feature_eligibility_granted': True},
            native, 'HIVE', '2026-09-22', verify, object())


def test_raw_day_cache_keeps_only_latest_verified_day():
    cache = subject._RawDayCache()
    for day in range(30):
        cache[day] = {'a large grouped vendor payload': day}
        assert len(cache) == 1 and cache.get(day) is not None
    assert cache.get(0) is None


def test_identity_scan_projects_and_pushes_requested_dates_to_arrow(monkeypatch):
    ref, _ = binding_fixture(monkeypatch)
    original = subject.base.pq.read_table
    calls = []
    def table(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(subject.base.pq, 'read_table', table)
    result = subject.read_raw_stock_prices(ref, 'CHPT', '2026-09-01', '2026-09-22', paths=object())
    assert result['status'] == 'READY'
    assert calls == [dict(columns=['target_date', 'security_id'], filters=[('ticker', '=', 'CHPT'),
        ('target_date', '>=', '2026-09-01'), ('target_date', '<=', '2026-09-22')])]


def test_new_published_member_uses_bound_current_rankings_and_supplement(monkeypatch):
    from types import SimpleNamespace
    from scripts.research.a2.evaluation import demo_performance_prices as prices
    ref, seen = binding_fixture(monkeypatch)
    old_json = subject._checked_json
    refs = lambda path: dict(path=path, sha256='hash')
    def checked(reference):
        result = old_json(reference)
        if reference['path'] == 'a2':
            return {**result, 'outputs': {'rankings': {**refs('current-ranked'), 'rows': 1}}}
        if reference['path'] == 'contract':
            return {**result, 'rankings': refs('current-ranked'),
                'additional_price_manifest': refs('supplement')}
        return result
    monkeypatch.setattr(subject, '_checked_json', checked)
    def table(path, **kwargs):
        seen.append(path)
        assert kwargs['filters'][0] == ('ticker', '=', 'P')
        rows = [] if path == 'full-ranked' else [dict(target_date='2026-09-22', security_id='74624M102')]
        return SimpleNamespace(to_pylist=lambda: rows)
    monkeypatch.setattr(subject.base.pq, 'read_table', table)
    calls = []
    def supplement(path, historical_sha, verify, expected_sha):
        calls.append((path, historical_sha, expected_sha))
        return [dict(ticker='P', code='US.P', security_id='74624M102')]
    monkeypatch.setattr(prices, 'read_execution_supplement', supplement)
    result = subject.read_raw_stock_prices(ref, 'P', '2026-09-01', '2026-09-22', paths=object())
    assert result['status'] == 'READY'
    assert seen == ['full-ranked', 'current-ranked']
    assert calls == [('supplement', 'hash', 'hash')]
    assert result['rows'][0]['ticker'] == 'P'


def test_current_rankings_must_belong_to_same_published_parent(monkeypatch):
    ref, _ = binding_fixture(monkeypatch)
    old_json = subject._checked_json
    def checked(reference):
        result = old_json(reference)
        if reference['path'] == 'a2':
            return {**result, 'outputs': {'rankings': {'path': 'one', 'sha256': 'hash'}}}
        if reference['path'] == 'contract':
            return {**result, 'rankings': {'path': 'different', 'sha256': 'hash'}}
        return result
    monkeypatch.setattr(subject, '_checked_json', checked)
    result = subject.read_raw_stock_prices(ref, 'CHPT', '2026-09-01', '2026-09-22', paths=object())
    assert result['status'] == 'UNAVAILABLE'
    assert result['error'] == 'RAW_DISPLAY_CURRENT_RANKING_BINDING_MISMATCH'


def test_supplement_keeps_one_qualified_contract_and_bound_sha(monkeypatch):
    from scripts.research.a2.evaluation import demo_performance_prices as prices
    manifest = dict(schema='A2_EXECUTION_PRICE_SUPPLEMENT_V1', historical_manifest_sha256='parent',
        gate=prices.EXECUTION_GATE, model_feature_eligibility_granted=False,
        lineage=[dict(ticker='P', security_id='74624M102')])
    monkeypatch.setattr(prices, '_json', lambda _: manifest)
    monkeypatch.setattr(prices.original, 'digest', lambda _: pytest.fail('ignored bound supplement SHA'))
    checks = []
    result = prices.read_execution_supplement('supplement', 'parent',
        lambda path, digest: checks.append((path, digest)), 'bound-sha')
    assert result is manifest['lineage'] and checks[0][1] == 'bound-sha'
    with pytest.raises(ValueError, match='SUPPLEMENT_CONTRACT_MISMATCH'):
        prices.read_execution_supplement('supplement', 'changed-parent', lambda *args: None, 'bound-sha')
    manifest['model_feature_eligibility_granted'] = True
    with pytest.raises(ValueError, match='SUPPLEMENT_CONTRACT_MISMATCH'):
        prices.read_execution_supplement('supplement', 'parent', lambda *args: None, 'bound-sha')
    manifest['model_feature_eligibility_granted'] = False
    manifest['lineage'] = [dict(ticker='UNKNOWN')]
    with pytest.raises(ValueError, match='TICKER_NOT_AUTHORIZED'):
        prices.read_execution_supplement('supplement', 'parent', lambda *args: None, 'bound-sha')


def test_historical_only_prices_do_not_require_an_unused_current_bridge(monkeypatch):
    monkeypatch.setattr(subject, '_checked_json', lambda _: dict(execution_bridges=[]))
    assert subject._execution_bridges({'price_inputs': {'path': 'old-accepted-inputs'}}, None, 'OLD') == ()


def _synthetic_rehab(path, *, optional=True, omit=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows=[]
    for code,day,base,amount,a,b in [('US.X','2025-01-02',1.,1.,1.,0.),
        ('US.X','2025-01-03',20.,1.,20.,.5),('US.X','2025-01-04',20.,1.,20.,0.),
        ('US.X','2025-02-01',10.,1.,10.,0.),('US.Y','2025-01-03',7.,1.,7.,0.)]:
        row=dict(code=code,ex_div_date=day,join_base=base,join_ert=amount,
            forward_adj_factorA=a,forward_adj_factorB=b)
        if optional:row.update(split_base=base,split_ert=amount)
        row.update({'unused_'+str(i):float(i) for i in range(22)})
        if omit:row.pop(omit)
        rows.append(row)
    pq.write_table(pa.Table.from_pylist(rows),path)
    return rows


def _full_sha_verify(path,expected):
    import hashlib
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected:
        raise ValueError('RAW_DISPLAY_SOURCE_HASH_MISMATCH')
    return path


@pytest.mark.parametrize('optional',[True,False])
def test_split_column_projection_equals_original_full_input_and_limits_decode(tmp_path,monkeypatch,optional):
    import hashlib
    import pyarrow.parquet as pq
    path=tmp_path/'synthetic_rehab.parquet';_synthetic_rehab(path,optional=optional)
    digest=hashlib.sha256(path.read_bytes()).hexdigest();entry=dict(code='US.X',rehab=dict(path=str(path),sha256=digest))
    full=pq.read_table(path);reader=pq.read_table;decoded=[]
    # Same untouched original split loop over the old full-column input.
    with monkeypatch.context() as patch:
        patch.setattr(subject.base.pq,'read_table',lambda *args,**kwargs:full)
        old=subject._split_actions(entry,_full_sha_verify,'2025-01-31')
    def projected(*args,**kwargs):
        table=reader(*args,**kwargs);decoded.append((kwargs['columns'],table.nbytes,table.num_rows));return table
    monkeypatch.setattr(subject.base.pq,'read_table',projected)
    new=subject._split_actions(entry,_full_sha_verify,'2025-01-31')
    assert new==old
    assert [row['event_date'] for row in new]==['2025-01-03','2025-01-04']
    assert len(decoded)==1 and decoded[0][2]==full.num_rows
    assert len(decoded[0][0])==(8 if optional else 6)
    assert all(not name.startswith('unused_') for name in decoded[0][0])
    assert decoded[0][1]<full.nbytes
    print({'case':'synthetic CA decode','input_columns':full.num_columns,
        'projected_columns':len(decoded[0][0]),'rows_unchanged':full.num_rows,
        'full_arrow_bytes':full.nbytes,'projected_arrow_bytes':decoded[0][1]})


@pytest.mark.parametrize('missing,error',[('code',AttributeError),('ex_div_date',KeyError)])
def test_split_projection_keeps_original_missing_required_field_failure(tmp_path,missing,error):
    import hashlib
    path=tmp_path/'synthetic_missing.parquet';_synthetic_rehab(path,omit=missing)
    entry=dict(code='US.X',rehab=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    with pytest.raises(error):subject._split_actions(entry,_full_sha_verify,'2025-01-31')


def test_split_projection_still_rejects_change_in_a_column_it_does_not_decode(tmp_path,monkeypatch):
    import hashlib
    import pyarrow as pa
    import pyarrow.parquet as pq
    path=tmp_path/'synthetic_tamper.parquet';rows=_synthetic_rehab(path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    rows[0]['unused_21']=999.;pq.write_table(pa.Table.from_pylist(rows),path)
    calls=[]
    monkeypatch.setattr(subject.base.pq,'read_schema',lambda *args:calls.append('schema'))
    monkeypatch.setattr(subject.base.pq,'read_table',lambda *args,**kwargs:calls.append('table'))
    entry=dict(code='US.X',rehab=dict(path=str(path),sha256=digest))
    with pytest.raises(ValueError,match='RAW_DISPLAY_SOURCE_HASH_MISMATCH'):
        subject._split_actions(entry,_full_sha_verify,'2025-01-31')
    assert calls==[]


@pytest.mark.parametrize('missing',['join_base','join_ert','split_base','split_ert',
    'forward_adj_factorA','forward_adj_factorB'])
def test_split_projection_preserves_optional_fallback_and_unsupported_fact_result(tmp_path,monkeypatch,missing):
    import hashlib
    import pyarrow.parquet as pq
    path=tmp_path/'synthetic_optional.parquet';_synthetic_rehab(path,omit=missing)
    entry=dict(code='US.X',rehab=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    full=pq.read_table(path)
    with monkeypatch.context() as patch:
        patch.setattr(subject.base.pq,'read_table',lambda *args,**kwargs:full)
        original=subject._split_actions(entry,_full_sha_verify,'2025-01-31')
    assert subject._split_actions(entry,_full_sha_verify,'2025-01-31')==original
