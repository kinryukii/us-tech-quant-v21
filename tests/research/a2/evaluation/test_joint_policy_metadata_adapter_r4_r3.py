"""Equivalent metadata-only carry and exact administrative scope binding."""
import pandas as pd
import pytest
from scripts.research.a2.evaluation import joint_policy_metadata_adapter_r4_r3 as r3
from tests.research.a2.evaluation.test_joint_policy_metadata_adapter_r4 import inputs, Reader
m=r3.base


@pytest.mark.parametrize("case", ["stable", "offpool_unknown", "offpool_duplicate", "eligible_unknown",
    "eligible_duplicate", "unknown_becomes_eligible", "same_uid_gap", "decision_gap", "uid_change"])
def test_exact_full_requested_pool_and_epoch_equivalence(case):
    days, selected, frame, witness = inputs()
    day = pd.Timestamp("2023-01-05")
    if case in {"offpool_unknown", "offpool_duplicate"}:
        extra = frame.loc[frame.ticker.eq("A") & frame.signal_date.eq(day)].copy()
        extra["ticker"] = "OFFPOOL"; extra["security_id"] = None; extra["feature_available"] = False
        frame = pd.concat([frame, extra, extra if case == "offpool_duplicate" else extra.iloc[:0]], ignore_index=True)
    elif case == "eligible_unknown":
        frame.loc[frame.ticker.eq("B") & frame.signal_date.eq(day), "security_id"] = None
    elif case == "eligible_duplicate":
        frame = pd.concat([frame, frame.loc[frame.ticker.eq("B") & frame.signal_date.eq(day)]], ignore_index=True)
    elif case == "unknown_becomes_eligible":
        extra = frame.loc[frame.ticker.eq("A")].copy()
        extra["ticker"] = "NEW"; extra["security_id"] = None
        extra["feature_available"] = extra.signal_date.ge(day)
        frame = pd.concat([frame, extra], ignore_index=True)
    elif case == "same_uid_gap":
        frame = frame.loc[~(frame.ticker.eq("B") & frame.signal_date.eq(day))]
    elif case == "uid_change":
        frame.loc[frame.ticker.eq("B") & frame.signal_date.ge(day), "security_id"] = "NEW_UID_B"
    requested = selected[selected >= pd.Timestamp("2023-01-03")]
    if case == "decision_gap":requested = requested[requested != day]
    class AllRawReader(Reader):
        def read(self,name,columns,**kw):
            if name=="raw_open_close":
                return pd.DataFrame({"ticker": ["A", "B", "NEW", "OFFPOOL"], "trade_date":kw["day"]})
            return super().read(name,columns,**kw)
    reader=AllRawReader(frame)
    adapter=r3.EpochCarryMetadataPoolR3(reader,days,witness=witness,audit_dates=requested)
    results={}
    for date in requested:
        actual=adapter(date)
        raw=reader.read("raw_open_close",("ticker","trade_date"),day=date)
        expected=m.old.current_pool(frame.loc[frame.signal_date.le(date)],raw,days,m._clock(date))
        assert m.content_hash(m.identity(actual))==m.content_hash(m.identity(expected))
        results[date]=actual
    assert all(row["exact_identity_equal"] for row in adapter.audits)
    if case in {"stable","offpool_unknown","offpool_duplicate"}:
        assert adapter.full_helper_calls==1 and adapter.carry_calls==len(requested)-1
    if case in {"eligible_unknown","eligible_duplicate","unknown_becomes_eligible"}:
        assert results[day]["blocked_assets"]
        assert adapter.full_helper_calls>=2
    if case=="unknown_becomes_eligible":assert "NEW" in results[day]["assets"] and "NEW" in results[day]["blocked_assets"]
    if case=="same_uid_gap":
        assert results[pd.Timestamp("2023-01-06")]["segment_starts"]["B"]=="2023-01-06"
        assert results[pd.Timestamp("2023-01-06")]["asset_epochs"]["B"]!=results[pd.Timestamp("2023-01-04")]["asset_epochs"]["B"]


def test_past_rewrite_still_blocks_and_scope_does_not_change_science():
    days,selected,frame,witness=inputs()
    reader=Reader(frame);adapter=r3.EpochCarryMetadataPoolR3(reader,days,witness=witness)
    adapter("2023-01-03");original=reader.read
    def rewritten(name,columns,**kw):
        result=original(name,columns,**kw)
        if name=="prediction_features":result=pd.concat([result,frame.loc[frame.signal_date.eq("2023-01-03")]],ignore_index=True)
        return result
    reader.read=rewritten
    with pytest.raises(m.policy.PolicyInputBlocked,match="REWRITES_PAST"):adapter("2023-01-04")
    spec={"original_main":[{"id":"OLD","risk":"R0","rho":.5}],"original_sensitivity":[{"id":"S","scope":"SENSITIVITY"}]}
    projected=r3.r2.canonical_inherited(lambda root,s:s,None,spec)
    assert projected["original_main"]==[{"id":"OLD","risk":"R0","rho":.5,"scope":"MAIN"}]
    assert projected["original_sensitivity"]==spec["original_sensitivity"] and "scope" not in spec["original_main"][0]
    with pytest.raises(m.policy.PolicyInputBlocked,match="SCOPE_CONTRADICTION"):
        r3.r2.canonical_inherited(lambda root,s:s,None,{"original_main":[{"id":"OLD","scope":"OTHER"}]})


def test_process_only_pool_binding_does_not_recurse(monkeypatch):
    days,selected,frame,witness=inputs()
    adapter=r3.EpochCarryMetadataPoolR3(Reader(frame),days,witness=witness)
    monkeypatch.setattr(r3.policy,"DailyMetadataPool",r3.EpochCarryMetadataPoolR3)
    assert adapter("2023-01-03")["assets"]==("A","B")
