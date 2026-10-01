import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
P=Path(__file__).parents[1]/'scripts/research/a2/evaluation/demo_rx_performance.py'
spec=importlib.util.spec_from_file_location('demo_rx_tests',P);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

@pytest.fixture
def example():
    days=pd.bdate_range('2025-09-01',periods=90);rng=np.random.default_rng(10);frames=[]
    for i in range(40):
        c=100*np.exp(np.cumsum(rng.normal(0,.01,len(days))))
        frames.append(pd.DataFrame(dict(ticker=f'T{i:02}',trade_date=days,open=c,high=c*1.02,low=c*.98,close=c,volume=rng.integers(1000,2000,len(days)))))
    ranks=pd.DataFrame([dict(target_date=str(d.date()),ticker=f'T{i:02}',security_id=f'ID{i}',rank=i+1,score=40-i) for d in days[-3:] for i in range(40)])
    return ranks,pd.concat(frames,ignore_index=True),days


def test_trailing_ast_exactly_equals_frozen_features_and_no_labels(example):
    ranks,prices,calendar=example;r5,_=module.authority()
    panel=ranks.rename(columns={'target_date':'signal_date'});panel.signal_date=pd.to_datetime(panel.signal_date);panel['residual_cluster_id']=0
    r5.FOLD_YEARS=(2026,);r5.CUTOFF=calendar[-1];r5.BOUNDARY_EXCLUSIVE=calendar[-1]+pd.Timedelta(days=1)
    expected,_=r5.attach_price_path_features(panel,prices);actual=module.frozen_price_features(panel,prices)
    for col in module.FEATURES:pd.testing.assert_series_equal(expected[col],actual[col])
    assert not any('future' in col or 'label' in col for col in actual)


def test_selection_top20_margin_rule_and_pending_latest(example):
    ranks,prices,calendar=example;r5,rx=module.authority()
    selected,ledger,audit=module.select_rx(ranks,prices,calendar,r5,rx)
    assert selected.groupby('target_date').size().eq(20).all()
    assert set(selected.ticker)<=set(ranks.ticker)
    assert ledger.replacement_decision.eq('REPLACE').equals(ledger.score_margin.ge(ledger.required_margin))
    assert ledger.loc[ledger.signal_date.eq(calendar[-1]),'execution_date'].isna().all()
    assert audit['future_label_columns_computed'] is False


def test_future_price_changes_do_not_change_earlier_selection(example):
    ranks,prices,calendar=example;r5,rx=module.authority()
    first=ranks.loc[ranks.target_date.eq(str(calendar[-3].date()))]
    a,_,_=module.select_rx(first,prices,calendar,r5,rx)
    changed=prices.copy();changed.loc[changed.trade_date.gt(calendar[-3]),'close']*=2
    b,_,_=module.select_rx(first,changed,calendar,r5,rx)
    pd.testing.assert_frame_equal(a,b)


def test_missing_top40_cannot_silently_become_rx(example):
    ranks,prices,calendar=example;r5,rx=module.authority()
    with pytest.raises(ValueError,match='EXACT_TOP40'):
        module.select_rx(ranks.iloc[1:],prices,calendar,r5,rx)


def test_rx_uses_existing_open_ended_engine_and_accounting(example):
    ranks,prices,calendar=example;r5,rx=module.authority()
    signals,_,_=module.select_rx(ranks,prices,calendar,r5,rx)
    from scripts.common.storage_paths import resolve
    engine,_=module.base._authority(resolve())
    engine.EFFECTIVE_START=pd.Timestamp(signals.target_date.min())
    targets=engine.build_target_map(signals.rename(columns={'target_date':'signal_date'}),'rank')
    ledger=engine.reconstruct_open_ended('A2_RX',targets,prices,calendar,calendar[-1])
    daily,positions,trades=module.base.normalize_ledger(ledger,signals,calendar)
    assert len(daily)==3 and daily.iloc[0].reconstructed_nav==1
    assert daily[[c for c in daily if c.endswith('IDENTITY_ERROR')]].abs().max().max()<1e-9
    assert positions.loc[positions.date.eq(calendar[-1]),'shares_after'].gt(0).any()
    assert set(trades.side)<= {'BUY','SELL'} and trades.execution_price.gt(0).all()


def test_execution_union_retains_pending_a2_review_scope():
    rx=pd.DataFrame({'ticker':['RX']})
    a2=pd.DataFrame({'ticker':['PENDING','OTHER40'],'rank':[1,40]})
    positions=pd.DataFrame({'ticker':['HELD']})
    assert module.execution_tickers(rx,a2,positions)==['HELD','PENDING','RX']


def test_unreviewed_rx_held_event_still_blocks():
    days=pd.bdate_range('2026-01-05',periods=3)
    signals=pd.DataFrame({'target_date':days,'ticker':['RX']*3,'rank':[1]*3})
    prices=pd.DataFrame({'trade_date':days,'ticker':['RX']*3,'open':[100.,100.,110.]})
    events=pd.DataFrame({'ticker':['RX'],'event_date':[days[-1]],'audit_kind':['LARGE_RAW_MOVE_NO_VENDOR_EVENT']})
    cutoff,blocked=module.base.safe_execution_end(signals,prices,days,events,set())
    assert cutoff==days[1] and blocked['reason']=='HELD_CORPORATE_ACTION_EXCEPTION'


def test_missing_parent_inference_blocks_rx_without_invented_prices():
    with pytest.raises(ValueError,match='MISSING_SIGNAL_FEATURE_LINEAGE'):
        module.parent_rankings({'missing_signal_inference':{'path':'unread'}})


def test_signal_must_have_actual_same_session_full_price(example):
    ranks,prices,calendar=example
    missing=prices.loc[~(prices.ticker.eq('T00') & prices.trade_date.eq(calendar[-1]))]
    with pytest.raises(ValueError,match='FULL_OHLCV_DATE_MISSING'):
        module.validate_signal_price_dates(ranks,missing,calendar)


def test_current_price_merge_requires_all_ohlcv_exact(example):
    _,prices,_=example
    old=prices.loc[prices.ticker.eq('T00')].iloc[:-1]
    new=prices.loc[prices.ticker.eq('T00')].iloc[-5:].copy()
    combined=module.merge_qualified_frames(old,new)
    assert len(combined)==len(old)+1
    new.loc[new.index[0],'volume']+=1
    with pytest.raises(ValueError,match='FULL_OHLCV_OVERLAP_CHANGED'):
        module.merge_qualified_frames(old,new)


def test_qualified_feature_loader_uses_store_and_real_hashed_fixture(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from scripts import daily_recommendation_prices as original
    from scripts.research.a2.inference import historical_top40_prices as historical
    dates=pd.bdate_range('2025-12-29',periods=4)
    raw=pd.DataFrame({'ticker':['X']*4,'trade_date':dates,'open':[100.]*4,'high':[101.]*4,
                      'low':[99.]*4,'close':[100.]*4,'volume':[1000.]*4})
    factor=tmp_path/'rehab.parquet';pd.DataFrame({'code':['US.X']}).to_parquet(factor,index=False)
    entry={'ticker':'X','code':'US.X','rehab':{**module.base.reference(factor),'kind':'CURRENT_SNAPSHOT'}}
    inputs=tmp_path/'prices.json';inputs.write_text(json.dumps({'lineage':[entry]}))
    hist=tmp_path/'manifest.json';hist.write_text(json.dumps({'price_manifest':module.base.reference(inputs)}))
    coverage=tmp_path/'coverage.json';coverage.write_text(json.dumps({'adjustment':{'wolf_event_date':'2025-09-29','wolf_new_shares_per_old_share':.008352}}))
    monkeypatch.setattr(original,'COVERAGE_PATH',coverage);monkeypatch.setattr(original,'COVERAGE_SHA',module.base.digest(coverage))
    store=object();calls=[]
    monkeypatch.setattr(historical,'_store',lambda paths:calls.append(paths) or store)
    def raw_reader(entry,verify,used_store,cache):
        assert used_store is store
        return raw.copy()
    monkeypatch.setattr(module.price_reader,'_raw',raw_reader)
    monkeypatch.setattr(original,'_adapter',lambda end:SimpleNamespace(adjusted_price_frame=lambda *a:(raw.copy(),[])))
    paths=SimpleNamespace()
    result,refs,gaps=module.qualified_feature_prices(paths,hist,{'X'},'2026-01-01')
    pd.testing.assert_frame_equal(result,raw)
    assert calls==[paths] and gaps==[] and refs==[module.base.reference(factor)]


def test_authority_import_preserves_canonical_storage_and_search_path():
    import sys
    from scripts.storage import storage_r2a
    import scripts.storage
    assert hasattr(storage_r2a,'DataStore')
    before=list(sys.path);store=storage_r2a.DataStore
    module.authority()
    from scripts.storage import storage_r2a as after
    assert sys.path==before
    assert after is storage_r2a and after.DataStore is store
    assert scripts.storage.storage_r2a is storage_r2a


def test_frozen_import_scope_restores_replaced_modules_and_stubs():
    import sys
    from types import ModuleType
    from scripts.storage import storage_r2a
    import scripts.storage
    before=list(sys.path)
    with module.isolated_frozen_imports():
        fake=ModuleType('scripts.storage.storage_r2a')
        sys.modules[fake.__name__]=fake;scripts.storage.storage_r2a=fake
        sys.modules['scripts.storage.rx_fake_stub']=ModuleType('scripts.storage.rx_fake_stub')
        scripts.storage.rx_fake_stub=sys.modules['scripts.storage.rx_fake_stub']
        sys.path.insert(0,'OLD_WORKTREE_SYNTHETIC')
    assert sys.path==before
    assert sys.modules['scripts.storage.storage_r2a'] is storage_r2a
    assert scripts.storage.storage_r2a is storage_r2a
    assert 'scripts.storage.rx_fake_stub' not in sys.modules
    assert not hasattr(scripts.storage,'rx_fake_stub')


def test_real_graph_audit_is_json_serializable_without_changing_values(example,tmp_path):
    import json
    ranks,prices,calendar=example;r5,rx=module.authority()
    _,_,audit=module.select_rx(ranks,prices,calendar,r5,rx)
    path=tmp_path/'selection_audit.json'
    module.save(path,module.json_audit(audit))
    actual=json.loads(path.read_text())
    assert actual['graph']['maximum_price_date_materialized']==calendar[-1].isoformat()
    assert actual['graph']['minimum_history_sessions']==audit['graph']['minimum_history_sessions']
    assert isinstance(audit['graph']['maximum_price_date_materialized'],pd.Timestamp)
