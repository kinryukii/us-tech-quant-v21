"""Only invented data; actual real-bound integration is exercised by recorded CLI runs."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.options import cli, input_adapter as adapter
from scripts.research.a2.options.contracts import Invalid, calendar


def vintages():
    return [{"year": y, "train_max_date": f"{y-1}-11-01", "train_target_end_max": f"{y-1}-12-20",
             "prediction_min_date": f"{y}-01-03" if y == 2023 else f"{y}-01-02",
             "prediction_max_date": f"{y}-12-31", "vintage": str(y), "effective_model_vintage_fingerprint": str(y),
             "future_usage_contract": "CONSUME_FROZEN_PREDICTIONS;DO_NOT_RETRAIN_SILENTLY"} for y in (2023,2024,2025)]


def frames():
    day = pd.Timestamp("2023-01-03")
    cp = pd.DataFrame([dict(decision_date=day, security_id=str(i), ticker_if_available=f"T{i}", raw_rank=i,
                            raw_score=21.-i, is_raw_top20=True, prediction_asof_date=day,
                            oof_or_authoritative_replay_status="FROZEN_AUTHORITATIVE_OOF", source_research_id=adapter.BASELINE,
                            model_hash="2023", fold_id="2023", training_cutoff=pd.Timestamp("2022-12-20"),
                            feature_contract_hash="fixture", training_contract_hash="fixture", source_artifact_hash="fixture")
                       for i in range(1,21)])
    top = pd.DataFrame(dict(signal_date=day, ticker=cp.ticker_if_available, a2_rank=cp.raw_rank, a2_prediction=cp.raw_score))
    members = pd.DataFrame(dict(signal_date=day, ticker=cp.ticker_if_available, cusip=cp.security_id,
                                required_observations=800., active_13f_quarter="Q", U_t_fingerprint="fixture"))
    active = pd.DataFrame([dict(signal_date=day, quarter_effective_date=pd.Timestamp("2022-11-01"), active_quarter_count=1)])
    return dict(checkpoint=cp, a2_top20=top, daily_u_membership=members, daily_active_quarter=active)


def paths(day="2025-03-07"):
    sessions = calendar().sessions
    start = sessions.get_loc(pd.Timestamp(day)) + 1
    days = sessions[start:start+21]
    panel = pd.DataFrame([dict(decision_id="fixture", signal_date=pd.Timestamp(day), underlying_uid="UID", ticker="T",
                               input_reason="OK", planned_entry=calendar().schedule.loc[days[0], "open"].isoformat())])
    # These invented prices end at 2025; calendar-only future dates are omitted.
    legal = days[days < "2026-01-01"]
    marks = pd.DataFrame(dict(date=legal, ticker="T", current_price=100.+np.arange(len(legal)),
                              mark_source_date=legal, stale_mark=False))
    members = pd.DataFrame(dict(signal_date=legal, ticker="T", cusip="UID"))
    return panel, marks, members


def test_training_label_after_prediction_rejected_despite_pre2026():
    v = vintages(); v[0]["train_target_end_max"] = "2023-01-04"
    with pytest.raises(Invalid, match="TRAIN_LABEL_AFTER_PREDICTION"):
        adapter.validate_vintages(v)


def test_late_ingestion_does_not_invent_publication_or_reject_history():
    f = frames(); f["checkpoint"]["ingested_at"] = "2026-09-13"
    p = adapter.opportunity_panel(f, vintages())
    assert p.input_reason.eq("OK").all()  # accumulated 800 >= original 121 threshold
    assert p.signal_available_at.isna().all()
    assert p.planned_entry.iloc[0] == "2023-01-04T14:30:00+00:00"
    assert "ingested_at" not in p
    assert "absolute_return" not in p


def test_rank_not_replenished_and_decisions_independent_of_outcomes():
    f = frames(); f["checkpoint"]["future_return"] = -999.
    p = adapter.opportunity_panel(f, vintages())
    f["checkpoint"]["future_return"] = 999.
    f["checkpoint"] = f["checkpoint"].sample(frac=1, random_state=4)
    pd.testing.assert_frame_equal(p, adapter.opportunity_panel(f, vintages()))
    f["a2_top20"].loc[0, "a2_rank"] = 21
    with pytest.raises(Invalid, match="TOP20_IDENTITY"):
        adapter.opportunity_panel(f, vintages())


def test_missing_identity_retains_original_twenty():
    f = frames(); f["daily_u_membership"] = f["daily_u_membership"].iloc[1:]
    p = adapter.opportunity_panel(f, vintages())
    assert len(p) == 20 and p.input_reason.ne("OK").sum() == 1


def test_daily_elapsed_sessions_dst_and_outcome_separation():
    p,m,u = paths()
    labels, trace = adapter.daily_labels(p,m,u)
    assert p.planned_entry.iloc[0] == "2025-03-10T13:30:00+00:00"
    assert labels.absolute_return.tolist() == pytest.approx([.05,.20])
    assert labels.label_end.tolist() == ["2025-03-17T13:30:00+00:00", "2025-04-07T13:30:00+00:00"]
    assert labels.first_positive_session.tolist() == [1,1]
    assert labels.clock.eq("STOCK_DAILY_PATH_NEXT_SESSION_OPEN").all()
    assert "absolute_return" not in p and "label_end" not in p
    pd.testing.assert_frame_equal(labels, adapter.daily_labels(p,m.sample(frac=1,random_state=8),u)[0])


def test_missing_exit_and_independent_horizons():
    p,m,u = paths(); m = m.iloc[:-1]
    labels,_ = adapter.daily_labels(p,m,u)
    assert labels.status.tolist() == ["COMPLETE","MISSING"]
    assert labels.reason.iloc[1] == "MISSING_PATH_MARKS" and len(labels) == 2


def test_cutoff_is_not_missing_or_illegal_future_read():
    p,m,u = paths("2025-12-12")
    labels,_ = adapter.daily_labels(p,m,u)
    assert labels.status.iloc[0] == "COMPLETE"
    assert labels.reason.iloc[1] == "CUTOFF_CENSORED"
    assert pd.isna(labels.label_available_at.iloc[1])


@pytest.mark.parametrize("change,reason", [("stale", "STALE_OR_INVALID_PATH_MARK"),
                                          ("identity", "PATH_HISTORICAL_IDENTITY_MISSING_OR_CHANGED")])
def test_nontrading_marks_not_used(change, reason):
    p,m,u = paths()
    if change == "stale": m.loc[2,"stale_mark"] = True
    else: u.loc[2,"cusip"] = "DIFFERENT"
    labels,_ = adapter.daily_labels(p,m,u)
    assert labels.reason.eq(reason).all()


def test_duplicate_and_future_mark_fail_closed():
    p,m,u = paths()
    with pytest.raises(Invalid, match="DUPLICATE_PRICE"):
        adapter.daily_labels(p,pd.concat([m,m.iloc[:1]]),u)
    m.loc[0,"date"] = pd.Timestamp("2026-01-02")
    with pytest.raises(Invalid, match="NON_PRE2026"):
        adapter.daily_labels(p,m,u)


def test_unbound_input_rejected_without_open(monkeypatch):
    def denied(*args, **kwargs): raise AssertionError("unexpected input open")
    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(Invalid, match="UNBOUND_INPUT"):
        adapter.run_real_stock(None,None,input_path=Path("never-read-2026.parquet"))
    with pytest.raises(Invalid, match="UNBOUND_CONFIG"):
        adapter.run_real_stock(None,None)


@pytest.mark.parametrize("success,expected", [(False,3),(True,0)])
def test_required_real_stage_exit_not_masked_by_synthetic(monkeypatch, success, expected):
    monkeypatch.setattr(adapter,"run_real_stock",lambda *a,**k: dict(run_identity="test", scope="FULL_FROZEN_RANGE",
                      stock_path_research_status="COMPLETE" if success else "NOT_RUN", required_stage_success=success,
                      opportunity_rows=20 if success else 0, synthetic={"status":"PASS"}))
    assert cli.main(["--mode","real-stock"]) == expected


def test_same_day_cross_section_not_independent_interval():
    p,m,u = paths(); labels,_ = adapter.daily_labels(p,m,u)
    many = pd.concat([labels]*100,ignore_index=True)
    summary = adapter.summarize(many)
    assert all(s["complete_dates"] == 1 and s["exploratory_95_interval"] is None for s in summary)


def test_never_positive_complete_paths_serialize_without_fabricated_speed():
    p,m,u = paths()
    m["current_price"] = 100. - np.arange(len(m))
    labels,_ = adapter.daily_labels(p,m,u)
    assert labels.absolute_return.tolist() == pytest.approx([-.05,-.20])
    summary = adapter.summarize(labels)
    assert all(s["first_positive_session_median"] is None and s["never_positive"] == 1 for s in summary)
    json.dumps(summary, allow_nan=False)
