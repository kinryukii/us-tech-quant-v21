"""Synthetic clocks and metadata quarantine; no real 2026 prices/outcomes read."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import market_runtime as runtime


def synthetic_inputs(tmp_path,monkeypatch,year,dates,*,operations=None,frozen=True):
    dates=pd.DatetimeIndex(pd.to_datetime(dates))
    rows=[]
    for date in dates:
        for ticker in ["AAA","GLW"]:
            row={name:.01 for name in runtime.FEATURES}
            row.update(signal_date=date,ticker=ticker,new_buy_eligible=True,avg_dollar_volume_20d=1e8)
            rows.append(row)
    panel=pd.DataFrame(rows)
    prices=pd.DataFrame([dict(ticker=ticker,trade_date=date,open=100.,close=100.,price_quality_warning=False)
                         for date in dates for ticker in ["AAA","GLW","QQQ"]])
    calendar=pd.DataFrame(dict(trade_date=dates,is_test=np.full(len(dates),year==2026)))
    paths={}
    for name,frame in [("pre_panel",panel),("test_panel",panel),("pre_prices",prices),("test_prices",prices),("calendar",calendar)]:
        path=tmp_path/f"{name}.parquet";frame.to_parquet(path,index=False);paths[name]=str(path)
    ops=pd.DataFrame(operations or [],columns=["ticker","effective_date","known_at","reason","source_id"])
    path=tmp_path/"ops.csv";ops.to_csv(path,index=False);paths["ops"]=str(path)
    (tmp_path/"input_paths.json").write_text(json.dumps(paths),encoding="utf-8")
    if frozen:(tmp_path/"FROZEN_BEFORE_2026.json").write_text('{"synthetic_fixture":true}',encoding="utf-8")
    monkeypatch.setattr(runtime,"ROOT",tmp_path)
    return paths


@pytest.mark.parametrize("year,dates,expected_hours",[
    (2025,["2025-07-02","2025-07-03","2025-11-28","2025-12-23","2025-12-24"],[16,13,13,16,13]),
    (2026,["2026-07-02","2026-11-27","2026-12-23","2026-12-24"],[16,13,16,13])
])
def test_actual_session_clocks_include_early_close_and_july_2026_exception(tmp_path,monkeypatch,year,dates,expected_hours):
    synthetic_inputs(tmp_path,monkeypatch,year,dates)
    prepared=runtime.prepare_market(year)
    clocks=prepared.market.signal_asof
    local=[pd.Timestamp(value).tz_convert("America/New_York") for value in clocks]
    assert [value.hour for value in local]==expected_hours
    assert [value.minute for value in local]==[0]*len(local)
    assert [value.date() for value in local]==[pd.Timestamp(day).date() for day in dates]
    assert all(str(pd.Timestamp(value).tzinfo)=="UTC" for value in clocks)


def test_declared_glw_conflict_is_quarantined_in_memory_without_changing_raw_files(tmp_path,monkeypatch):
    dates=["2026-02-25","2026-02-26","2026-02-27","2026-03-02"]
    paths=synthetic_inputs(tmp_path,monkeypatch,2026,dates)
    before={key:hashlib.sha256(Path(value).read_bytes()).hexdigest() for key,value in paths.items()}
    prepared=runtime.prepare_market(2026);market=prepared.market
    glw=prepared.ticker_index["GLW"];other=prepared.ticker_index["AAA"]
    conflict=prepared.date_index[pd.Timestamp("2026-02-26")]
    next_open=prepared.date_index[pd.Timestamp("2026-02-27")]
    assert not market.input_present[conflict,glw]
    assert not market.new_buy_eligible[conflict,glw]
    assert market.quality[conflict,glw] and market.quality[next_open,glw]
    assert market.input_present[conflict,other] and market.new_buy_eligible[conflict,other]
    assert not market.quality[:,other].any()
    for day in ["2026-02-25","2026-03-02"]:
        di=prepared.date_index[pd.Timestamp(day)]
        assert market.input_present[di,glw] and market.new_buy_eligible[di,glw]
        assert not market.quality[di,glw]
    after={key:hashlib.sha256(Path(value).read_bytes()).hexdigest() for key,value in paths.items()}
    assert before==after
    raw_prices=pd.read_parquet(paths["test_prices"])
    assert not raw_prices.price_quality_warning.any()
    raw_panel=pd.read_parquet(paths["test_panel"])
    assert raw_panel.new_buy_eligible.all()


def test_operational_evidence_after_early_close_cannot_be_consumed_until_next_signal(tmp_path,monkeypatch):
    dates=["2026-07-02","2026-11-27","2026-12-01"]
    known=pd.Timestamp("2026-11-27 13:30").tz_localize("America/New_York").tz_convert("UTC")
    operations=[dict(ticker="GLW",effective_date="2026-11-27",known_at=known.isoformat(),reason="synthetic after-close mandate",source_id="synthetic:after-close")]
    synthetic_inputs(tmp_path,monkeypatch,2026,dates,operations=operations)
    prepared=runtime.prepare_market(2026)
    assert "GLW" not in prepared.market.operational_exits[pd.Timestamp("2026-11-27")]
    assert prepared.market.operational_exits[pd.Timestamp("2026-12-01")]["GLW"].source_id=="synthetic:after-close"


def test_2026_market_guard_runs_before_reading_any_panel(tmp_path,monkeypatch):
    synthetic_inputs(tmp_path,monkeypatch,2026,["2026-07-02"],frozen=False)
    def forbidden_read(*args,**kwargs):raise AssertionError("panel read before complete freeze")
    monkeypatch.setattr(runtime.pd,"read_parquet",forbidden_read)
    with pytest.raises(RuntimeError,match="FREEZE_ENTIRE_BATCH"):
        runtime.prepare_market(2026)


def test_undeclared_evaluation_year_rejected():
    with pytest.raises(ValueError,match="FIXED_EVALUATION_YEARS"):
        runtime.prepare_market(2024)
