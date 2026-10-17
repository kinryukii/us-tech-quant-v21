from pathlib import Path
import importlib.util
import pandas as pd
import pytest

from scripts.storage.build_data_catalog import normalize, combine_candidates


def bars(dates, close=10, ticker='ABC'):
    return pd.DataFrame({'ticker':ticker,'date':dates,'open':close,'high':close+1,
                         'low':close-1,'close':close,'volume':100,'adjustment':'qfq','source':'MOOMOO_OPEND'})


def test_bad_values_and_duplicates_are_not_accepted():
    with pytest.raises(ValueError,match='invalid OHLCV'):
        normalize(bars(['2026-01-02'],close=-1),'qfq','hash','2026-09-11')
    with pytest.raises(ValueError,match='duplicate'):
        normalize(bars(['2026-01-02','2026-01-02']),'qfq','hash','2026-09-11')


def test_unproved_qfq_intervals_do_not_create_false_continuity():
    a=normalize(bars(['2026-01-02','2026-01-05']),'qfq','a','2026-09-11')
    b=normalize(bars(['2026-01-06']),'qfq','b','2026-09-11')
    out,_,issues=combine_candidates([(1,a,'a'),(2,b,'b')],'qfq')
    assert len(out)==2 and issues[0]['reason']=='QFQ_NO_OVERLAP_VINTAGE_UNPROVEN'


def test_matching_overlap_can_extend_history():
    a=normalize(bars(['2026-01-02','2026-01-05']),'qfq','a','2026-09-11')
    b=normalize(bars(['2026-01-05','2026-01-06']),'qfq','b','2026-09-11')
    out,_,issues=combine_candidates([(1,a,'a'),(2,b,'b')],'qfq')
    assert len(out)==3 and not issues


def test_split_vintages_not_spliced():
    a=normalize(bars(['2026-01-02','2026-01-05']),'qfq','a','2026-09-11')
    b=normalize(bars(['2026-01-05','2026-01-06'],close=20),'qfq','b','2026-09-11')
    out,_,issues=combine_candidates([(1,a,'a'),(2,b,'b')],'qfq')
    assert len(out)==2 and out.close.nunique()==1
    assert issues[0]['reason']=='PRICE_VINTAGE_CONFLICT'


def test_larger_new_vintage_must_not_drop_an_existing_date():
    a=normalize(bars(['2026-01-02','2026-01-05','2026-01-06']),'qfq','a','2026-09-11')
    b=normalize(bars(['2026-01-02','2026-01-05','2026-01-07','2026-01-08'],close=20),'qfq','b','2026-09-11')
    out,_,issues=combine_candidates([(1,a,'a'),(2,b,'b')],'qfq')
    assert set(a.date).issubset(set(out.date))


def test_symbol_with_slash_retained_without_guessing_identity():
    data=bars(['2026-01-02'],ticker='LEN/B')
    with pytest.raises(ValueError,match='explicit provider mapping'):
        normalize(data,'qfq','a','2026-09-11')
    data['provider_code']='US.LEN.B'
    out=normalize(data,'qfq','a','2026-09-11')
    assert out.ticker.iloc[0]=='LEN/B' and out.provider_code.iloc[0]=='US.LEN.B'


def test_future_rows_not_materialized_and_observation_not_invented():
    out=normalize(bars(['2026-01-02','2026-10-01']),'qfq','a','2026-09-11')
    assert len(out)==1 and out.observed_at.isna().all()


def test_unproven_source_not_relabelled():
    data=bars(['2026-01-02']); data['source']='SYNTHETIC'
    with pytest.raises(ValueError,match='provenance'):
        normalize(data,'qfq','a','2026-09-11')


def test_transport_mapping_is_preserved():
    data=bars(['2026-01-02'],ticker='BRK.B');data['provider_code']='US.BRK-B'
    assert normalize(data,'qfq','a','2026-09-11').provider_code.iloc[0]=='US.BRK-B'


def test_invalid_row_is_audited_without_losing_the_valid_history():
    data=bars(['2026-01-02','2026-01-05']);data.loc[0,'high']=1
    quarantine=[];out=normalize(data,'qfq','a','2026-09-11',quarantine)
    assert len(out)==1 and len(quarantine)==1 and quarantine[0]['date']=='2026-01-02'


def test_explicit_legacy_provider_and_price_type_supported():
    data=bars(['2026-01-02']).drop(columns=['source','adjustment'])
    data['provider']='MOOMOO';data['price_type']='QFQ_DAILY'
    out=normalize(data,'qfq','a','2026-09-11')
    assert out.source.iloc[0]=='MOOMOO'


@pytest.mark.parametrize('column,value', [('adjustment',None),('provider','YAHOO'),('price_type','RAW_DAILY'),('provider_code','HK.ABC'),('ticker','A..B')])
def test_contradictory_or_missing_explicit_evidence_rejected(column,value):
    data=bars(['2026-01-02']);data[column]=value
    with pytest.raises(ValueError):normalize(data,'qfq','a','2026-09-11')


def test_transport_alias_requires_evidence_before_combining_histories():
    a=normalize(bars(['2026-01-02']),'qfq','a','2026-09-11')
    b=normalize(bars(['2026-01-02','2026-01-05']),'qfq','b','2026-09-11')
    b['provider_code']='US.OTHER'
    out,_,issues=combine_candidates([(1,a,'a'),(2,b,'b')],'qfq')
    assert len(out)==1 and issues[0]['reason']=='PROVIDER_MAPPING_CONFLICT_REQUIRES_ALIAS_EVIDENCE'


def _unprojected_catalog_combiner():
    """Restore only the old allocation expression for a finite differential check."""
    import inspect
    from scripts.storage import build_data_catalog as api
    source = inspect.getsource(api.combine_candidates)
    projected = "left=result.loc[:,['date','open','high','low','close']].set_index('date')"
    assert source.count(projected) == 1
    source = source.replace(projected, "left=result.set_index('date')", 1)
    namespace = dict(api.__dict__)
    exec(compile(source, "catalog-before-overlap-projection", "exec"), namespace)
    return namespace["combine_candidates"]


@pytest.mark.parametrize("adjustment", ["raw", "qfq"])
@pytest.mark.parametrize("scenario", [
    "compatible", "partial_revision", "full_revision",
    "disjoint", "provider_conflict", "three_intervals",
])
def test_merge_overlap_projection_preserves_full_contract(monkeypatch, adjustment, scenario):
    old = normalize(bars(["2026-01-02", "2026-01-05"]).assign(adjustment=adjustment),
                    adjustment, "old_source", "2026-09-11")
    dates = ["2026-01-05", "2026-01-06"]
    if scenario == "full_revision":
        dates = ["2026-01-02", *dates]
    elif scenario == "disjoint":
        dates = ["2026-01-06"]
    value = 20 if scenario in {"partial_revision", "full_revision"} else 10
    incoming = normalize(bars(dates, close=value).assign(adjustment=adjustment),
                         adjustment, "new_source", "2026-09-11")
    if scenario == "provider_conflict":
        incoming["provider_code"] = "US.OTHER"
    incoming["volume"], incoming["turnover"] = 200, 2000.
    old["observed_at"], incoming["observed_at"] = "2026-01-05T22:00:00Z", "2026-01-07T22:00:00Z"
    old["opaque_metadata"], incoming["opaque_metadata"] = "old", "new"
    candidates = [(1, old, "old.csv"), (2, incoming, "new.csv")]
    if scenario == "three_intervals":
        latest = normalize(bars(["2026-01-06", "2026-01-07"]).assign(adjustment=adjustment),
                           adjustment, "latest_source", "2026-09-11")
        latest["volume"], latest["turnover"] = 300, 3000.
        latest["observed_at"], latest["opaque_metadata"] = "2026-01-08T22:00:00Z", "latest"
        candidates.append((3, latest, "latest.csv"))
    originals = [row[1].copy(deep=True) for row in candidates]
    expected_frame, expected_used, expected_issues = _unprojected_catalog_combiner()(candidates, adjustment)
    indexed_columns = []
    original_set_index = pd.DataFrame.set_index

    def record_index(frame, *args, **kwargs):
        if (args and args[0] == "date") or kwargs.get("keys") == "date":
            indexed_columns.append(list(frame.columns))
        return original_set_index(frame, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "set_index", record_index)
    actual_frame, actual_used, actual_issues = combine_candidates(candidates, adjustment)
    pd.testing.assert_frame_equal(actual_frame, expected_frame)
    assert actual_used == expected_used and actual_issues == expected_issues
    assert list(actual_frame.columns) == list(old.columns)
    for candidate, original in zip(candidates, originals):
        pd.testing.assert_frame_equal(candidate[1], original)
    assert indexed_columns or scenario == "provider_conflict"
    for columns in indexed_columns[::2]:
        assert columns == ["date", "open", "high", "low", "close"]
    for columns in indexed_columns[1::2]:
        assert columns == list(incoming.columns)
