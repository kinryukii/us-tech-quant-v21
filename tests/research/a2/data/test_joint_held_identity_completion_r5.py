"""Synthetic-only tests of exact interval identity qualification."""
import pandas as pd
import pytest
from scripts.research.a2.data.joint_held_identity_completion_r5 import qualify_identity, IDENTITY


def inputs():
    held = pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-02","2023-01-03","2023-01-04","2023-01-05"]),
        "ticker":["AAA"]*4})
    for c in IDENTITY:
        held[c] = None
    intervals = pd.DataFrame([dict(ticker="AAA",effective_start="2023-01-03",effective_end="2023-01-04",
        report_quarter="2022Q3",security_id="123456789",security_id_type="CUSIP",cusip="123456789",
        quarter_universe_fingerprint="fp",mapping_status="RESOLVED")])
    quarters = pd.DataFrame([dict(report_quarter="2022Q3",effective_date="2023-01-02",effective_end="2023-01-05",universe_fingerprint="fp")])
    return held,intervals,quarters


def test_exact_interval_no_past_future_or_gap_carry_preserves_full_keys():
    held,intervals,quarters=inputs()
    out=qualify_identity(held,intervals,quarters,source_qualified=True)
    assert out[["signal_date","ticker"]].equals(held[["signal_date","ticker"]])
    assert out.identity_qualified.tolist()==[False,True,True,False]
    assert out.security_id.tolist()==[pd.NA,"123456789","123456789",pd.NA]
    assert out.reason.tolist()==["NO_LEGAL_ASOF_SECURITY_INTERVAL","QUALIFIED_EXACT_ACTIVE_MEMBERSHIP_SOURCE","QUALIFIED_EXACT_ACTIVE_MEMBERSHIP_SOURCE","NO_LEGAL_ASOF_SECURITY_INTERVAL"]
    assert out.quarter_state_qualified.all()
    assert out.active_13f_quarter.eq("2022Q3").all()
    assert out.parent_row_ordinal.tolist()==list(range(4))


def test_ambiguous_overlapping_interval_fails_closed():
    h,i,q=inputs()
    other=i.copy();other["security_id"]="987654321";other["cusip"]="987654321"
    out=qualify_identity(h,pd.concat([i,other]),q,source_qualified=True)
    assert not out.identity_qualified.any()
    assert out.loc[1,"reason"]=="AMBIGUOUS_ACTIVE_SECURITY_INTERVAL"
    assert pd.isna(out.loc[1,"security_id"])


def test_original_nonempty_conflict_is_not_overwritten_or_stitched():
    h,i,q=inputs();h.loc[1,"security_id"]="987654321"
    out=qualify_identity(h,i,q,source_qualified=True)
    assert out.loc[1,"original_security_id"]=="987654321"
    assert out.loc[1,"reason"]=="ORIGINAL_IDENTITY_CONFLICT"
    assert pd.isna(out.loc[1,"security_id"])
    assert out.loc[2,"identity_qualified"]


@pytest.mark.parametrize("field,value",[("cusip",None),("security_id_type","UNKNOWN"),("security_id","HELD_AAA"),("mapping_status","UNRESOLVED")])
def test_missing_or_placeholder_identity_never_qualifies(field,value):
    h,i,q=inputs();i.loc[0,field]=value
    out=qualify_identity(h,i,q,source_qualified=True)
    assert not out.identity_qualified.any()
    assert out.loc[1,"reason"]=="INCOMPLETE_IDENTITY_SOURCE"


def test_source_authority_failure_blocks_even_exact_match_and_global_state():
    h,i,q=inputs()
    out=qualify_identity(h,i,q,source_qualified=False)
    assert not out.identity_qualified.any()
    assert not out.quarter_state_qualified.any()
    assert out.reason.eq("SOURCE_AUTHORITY_UNQUALIFIED").all()
    assert out[IDENTITY].isna().all().all()


def test_quarter_source_is_independent_and_conflict_is_explicit():
    h,i,q=inputs();q["universe_fingerprint"]="different"
    out=qualify_identity(h,i,q,source_qualified=True)
    assert out.quarter_state_qualified.all()
    assert out.loc[1,"reason"]=="ORIGINAL_IDENTITY_CONFLICT"
    assert not out.identity_qualified.any()
    assert out.quarter_universe_fingerprint.eq("different").all()


def test_duplicate_parent_keys_and_2026_are_rejected():
    h,i,q=inputs()
    with pytest.raises(ValueError,match="UNIQUE_UNCHANGED"):
        qualify_identity(pd.concat([h,h.iloc[[0]]]),i,q,source_qualified=True)
    h.loc[0,"signal_date"]=pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError,match="PRE2026"):
        qualify_identity(h,i,q,source_qualified=True)


def test_future_interval_not_read_as_identity_for_earlier_keys():
    h,i,q=inputs();i["effective_start"]="2024-01-01";i["effective_end"]="2024-02-01"
    out=qualify_identity(h,i,q,source_qualified=True)
    assert not out.identity_qualified.any()
    assert out.reason.eq("NO_LEGAL_ASOF_SECURITY_INTERVAL").all()



def test_pinned_pure_metadata_rule_inline_array_and_legacy_conflict_preserved(tmp_path,monkeypatch):
    import json
    from scripts.research.a2.data import joint_held_identity_completion_r5 as m
    source={name:(tmp_path/(name+".json"),str(n)*64) for n,name in enumerate(("intervals","quarters","rule","manifest"),1)}
    producers={name:(str(tmp_path/(name+".py")),str(n)*64) for n,name in enumerate(("freeze","producer","integrity"),5)}
    rule={"research_cutoff_exclusive":"2026-01-01","authoritative_rules_verified":True,"rule_discrepancy_count":0,
        "identity_rule":{"dedup_keys_in_order":["quarter+ticker","quarter+code"]}}
    for name,field in (("freeze","authoritative_freeze_manifest"),("producer","authoritative_rebuild_source"),("integrity","upstream_integrity_source")):
        rule[field]={"path":producers[name][0],"sha256":producers[name][1]}
    # Frozen source writer has an inline array unlike fixed ledger writer.
    rule_text=json.dumps(rule,indent=2).replace('[\n      "quarter+ticker",\n      "quarter+code"\n    ]','["quarter+ticker", "quarter+code"]')
    source["rule"][0].write_text(rule_text,encoding="utf-8")
    manifest={"existing_package_hash_verified":True,"frozen_hash_match_count":46,"frozen_hash_mismatch_count":0,
        "outputs":[{"path":str(source[name][0]),"sha256":source[name][1]} for name in ("intervals","quarters","rule")],
        "notes":{"outcomes":"must skip before decoding"}}
    source["manifest"][0].write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    monkeypatch.setattr(m,"SOURCE_PINS",source);monkeypatch.setattr(m,"PRODUCER_PINS",producers)
    monkeypatch.setattr(m,"_pin",lambda path,digest:{"path":str(path),"sha256":digest})
    authority=m.source_authority()
    assert authority["current_source_internally_pinned"] is True
    assert authority["legacy_manifest_custody_conflict"]["closed"] is False
    assert authority["legacy_manifest_custody_conflict"]["parent_qualification_restored"] is False
    assert authority["strict_PIT_promotion_eligible"] is False
