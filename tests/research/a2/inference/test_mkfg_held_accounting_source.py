"""MKFG own-H label engineering only; fabricated quantities, no real account."""
import ast
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import reused_r5_risk_inputs as m

@pytest.fixture
def mkfg():
    ref=lambda label:dict(path="D:/synthetic/MKFG/"+label,sha256="a"*64)
    old=dict(security_id="57064N102",security_id_type="CUSIP",cusip="57064N102",share_class="Common Stock",raw_code="US.MKFG",raw_actual_share_coordinate="RAW_ACTUAL_SHARE")
    owner=ref("owner.py");event=ref("original_events.json");uid=ref("uid.parquet")
    source=object.__new__(m.FrozenHeldSourceGuards)
    source.binding=dict(account_owner_ref=owner,fill_owner_ref=owner,original_event_binding_ref=event,mapping_ref=ref("mapping.json"))
    source.held_accounting_account_id="OWN_MKFG"
    item=dict(source_ref=ref("source.json"),facts_ref=ref("split_only.json"),old_row={"ticker":"MKFG"},old_identity=old,
        original_uid_intervals_ref=uid,original_event_binding_ref=event,account_owner_ref=owner,
        original_seed_row_hashes=("original_row",),source_available_at="2024-09-09T20:16:05Z",post_split_trading_session="2024-09-19",
        runtime_typed_share_event_fingerprint="ORIGINAL_TYPED_SPLIT",public_current_CUSIP="57064N201")
    source.held_accounting_sources=(item,)
    source.base=SimpleNamespace(master_assets=("MKFG",))
    source.share_events=[dict(ticker="MKFG",day="2024-09-19",fp="ORIGINAL_TYPED_SPLIT")]
    source.unit_effects={"ORIGINAL_TYPED_SPLIT":dict(known_at=pd.Timestamp("2024-09-19T13:30Z"),old_ticker="MKFG",new_ticker="MKFG",old_security_id="OWNER_MKFG",new_security_id="OWNER_MKFG",typed_kind="OTHER_SHARE_COUNT_TRANSFORM",quantity_multiplier=.1,unit_before_quantity=1.,unit_after_quantity=.1)}
    source.lifecycle_effects={"2024-09-19":dict(account_id="OWN_MKFG",security_tickers={"CUSIP:57064N201":"MKFG"},positions_before={"CUSIP:57064N201":4.5})}
    source.mapping=dict(records=[dict(ticker="MKFG",start="2024-09-19",end="2026-01-01",coordinate="RAW_ACTUAL_SHARE",sid="CUSIP:57064N201")],basis_by_ticker={"MKFG":dict(kind="FROZEN_POST_VERIFIED_CUSIP_SPLIT_AND_TERMINAL_BINDING",proof=ref("postverified_NOT_read.json"))})
    def ctx(day,units):
        return SimpleNamespace(tickers=("MKFG",),signal_date=pd.Timestamp(day),signal_asof=m.producer._clock(day),current_units=np.array([[units]]),current_weights=np.array([[.1 if units else 0.]]))
    def guard(day,transitions=()):
        return dict(old,qualified=True,historical_observations_relabelled=False,decision_session=day,
            mapping_start="2023-01-03",mapping_end_exclusive="2026-01-01",mapping_row_count=1,raw_key_count=1,
            mapping_raw_code="US.MKFG",raw_key_code="US.MKFG",raw_key_session=day,current_accounting_mapping_ref=ref("mapping.json"),
            current_mapping_row_identity="mapping_"+day,raw_exact_key_ref=ref("raw.parquet"),raw_key_row_identity="raw_"+day,
            declared_catalogue_refs=[event],catalogue_checked_from_session="2024-06-13",catalogue_checked_through_session=day,
            processed_event_fingerprints=[r["event_fingerprint"] for r in transitions],unsupported_event_fingerprints=[],identity_conflict_count=0,quantity_transitions=list(transitions))
    book=m.HeldPositionLineageBook("OWN_MKFG",fill_owner_ref=owner,lineage_rule_ref=ref("rule.py"))
    seed=dict(old,qualified=True,historical_observations_relabelled=False,identity_asof=m.producer._clock("2024-06-13").isoformat(),seed_source_ref=uid,seed_source_row_identity="original_row",historical_source_epoch="ORIGINAL_UID_EPOCH")
    book.note_qualified_decision("2024-06-13",{"MKFG":seed})
    book.observe_fills(pd.DataFrame([dict(path_id="OWN_MKFG",order_id="ACTUAL_BUY",signal_date="2024-06-13",execution_date="2024-06-14",ticker="MKFG",side="BUY",fractional_shares=4.5,index_units_before=0.,index_units_after=4.5)]))
    book.qualified_proofs(ctx("2024-06-14",4.5),{"MKFG":guard("2024-06-14")})
    def proof(day="2024-09-19",units=.45,spells=None,eligible=()):
        return source._own_held_issuer_accounting_proof("MKFG",pd.Timestamp(day),ctx(day,units),book.source_lineages()["MKFG"] if spells is None else spells,eligible,book)
    def commit():
        result=proof();source._mapping("MKFG",pd.Timestamp("2024-09-19"),"US.MKFG",old,held_accounting_proof=result)
        book.qualified_proofs(ctx("2024-09-19",.45),{"MKFG":guard("2024-09-19",[result["own_original_share_effect"]])})
        return result
    return SimpleNamespace(source=source,item=item,book=book,old=old,ref=ref,proof=proof,commit=commit,ctx=ctx,guard=guard)

def test_mkfg_original_book_split_later_terminal_microflow(mkfg):
    x=mkfg;prior=deepcopy(x.book.source_lineages()["MKFG"][0]["seed"])
    proof=x.commit()
    assert proof["public_current_issuer_CUSIP"]=="57064N201"
    assert proof["immutable_admission_identity"]==x.old
    assert proof["own_original_share_effect"]["old_identity"]==proof["own_original_share_effect"]["new_identity"]==x.old
    assert proof["original_research_fractional_contract_unchanged"] and not proof["issuer_roundup_applied"]
    assert x.book._positions["MKFG"]["quantity"]==pytest.approx(.45)  # synthetic research units; no whole-share round-up
    later=x.proof("2024-09-20")
    assert later["phase"]=="OWN_BOOK_ALREADY_COMMITTED_ORIGINAL_SHARE_CHAIN"
    row,audit=x.source._mapping("MKFG",pd.Timestamp("2024-09-20"),"US.MKFG",x.old,held_accounting_proof=later)
    assert row["sid"]=="CUSIP:57064N201" and audit["direct_legal_identity"]==x.old
    assert not audit["terminal_or_settlement_qualification_granted"]
    x.book.qualified_proofs(x.ctx("2024-09-20",.45),{"MKFG":x.guard("2024-09-20")})
    assert x.book.source_lineages()["MKFG"][0]["seed"]==prior
    assert len(x.book._positions["MKFG"]["processed_share_transitions"])==1
    # Original terminal source uses its public accounting label; Book retains the immutable admission identity.
    terminal=SimpleNamespace(old_security_id="CUSIP:57064N201",available_at="2025-04-25T13:06:18Z")
    x.source.lifecycle_effects["2025-04-25"]=dict(account_id="OWN_MKFG",session_open_at="2025-04-25T13:30Z",
        security_tickers={"CUSIP:57064N201":"MKFG"},positions_before={"CUSIP:57064N201":.45},positions_after={"CUSIP:57064N201":0.},
        terminal_effect_records=[dict(event_fingerprint="TERMINAL",ticker="MKFG",old_security_id="CUSIP:57064N201",phase="SECURITY_EXTINGUISHED",session="2025-04-25")])
    endproof=x.proof("2025-04-25",0.)
    assert endproof["immutable_admission_identity"]==x.old
    spell=x.book.source_lineages()["MKFG"][0]
    transition=x.source._terminal_transition("MKFG",dict(fp="TERMINAL",event=terminal),x.ctx("2025-04-25",0.),spell,x.old)
    assert transition["old_identity"]==transition["new_identity"]==x.old and transition["after_raw_quantity"]==0.
    assert transition["actual_quantity_evidence_ref"]["security_id"]=="CUSIP:57064N201"
    assert x.book.qualified_proofs(x.ctx("2025-04-25",0.),{"MKFG":x.guard("2025-04-25",[transition])})=={}
    assert x.book.held_assets==()
    # No cash owner/settlement qualification is exercised by this identity-only microflow.

@pytest.mark.parametrize("defect",["no_source","wrong_account","eligible","pending","seed","row","late_clock","late_action","duplicate_action","conversion","rename","prior_quantity"])
def test_mkfg_current_source_rejects_scope_and_original_effect_defects(mkfg,defect):
    x=mkfg;spells=deepcopy(x.book.source_lineages()["MKFG"]);eligible=()
    if defect=="no_source":
        x.source.held_accounting_sources=()
        assert x.proof() is None
        with pytest.raises(m.HeldLineageUnavailable,match="DIRECT_CURRENT_LEGAL_ID"):
            x.source._mapping("MKFG",pd.Timestamp("2024-09-19"),"US.MKFG",x.old)
        return
    if defect=="wrong_account":x.source.held_accounting_account_id="OTHER"
    elif defect=="eligible":eligible=("MKFG",)
    elif defect=="pending":spells[0]["role"]="PENDING_ACTUAL_BUY"
    elif defect=="seed":spells[0]["seed"]["cusip"]="OTHER"
    elif defect=="row":spells[0]["seed"]["seed_source_row_identity"]="UNKNOWN"
    elif defect=="late_clock":x.item["source_available_at"]="2024-09-19T13:30:01Z"
    elif defect=="late_action":x.source.unit_effects["ORIGINAL_TYPED_SPLIT"]["known_at"]=pd.Timestamp("2024-09-19T13:30:01Z")
    elif defect=="duplicate_action":x.source.share_events*=2
    elif defect=="conversion":x.source.unit_effects["ORIGINAL_TYPED_SPLIT"]["typed_kind"]="CONVERSION"
    elif defect=="rename":x.source.unit_effects["ORIGINAL_TYPED_SPLIT"]["new_security_id"]="CUSIP:57064N201"
    elif defect=="prior_quantity":x.source.lifecycle_effects["2024-09-19"]["positions_before"]["CUSIP:57064N201"]=45.
    with pytest.raises(m.HeldLineageUnavailable):x.proof(spells=spells,eligible=eligible)
    assert x.book._positions["MKFG"]["quantity"]==4.5 and not x.book._positions["MKFG"].get("processed_share_transitions")

@pytest.mark.parametrize("defect",["missing","duplicate","position","source","owner","ratio","rename"])
def test_mkfg_later_source_uses_only_this_positions_once_committed_original_chain(mkfg,defect):
    x=mkfg;x.commit();spells=deepcopy(x.book.source_lineages()["MKFG"]);chain=spells[0]["processed_share_transitions"]
    if defect=="missing":chain.clear()
    elif defect=="duplicate":chain.append(deepcopy(chain[0]))
    elif defect=="position":chain[0]["position_id"]="OTHER"
    elif defect=="source":chain[0]["source_ref"]=x.ref("OTHER")
    elif defect=="owner":chain[0]["owner_ref"]=x.ref("OTHER")
    elif defect=="ratio":chain[0]["after_raw_quantity"]*=.1
    elif defect=="rename":chain[0]["new_identity"]["security_id"]="57064N201"
    with pytest.raises(m.HeldLineageUnavailable):x.proof("2024-09-20",spells=spells)
    assert x.book._positions["MKFG"]["quantity"]==pytest.approx(.45)

def test_mkfg_duplicate_quantity_effect_is_original_book_rejected(mkfg):
    x=mkfg;proof=x.commit()
    with pytest.raises(m.HeldLineageUnavailable):
        x.book.qualified_proofs(x.ctx("2024-09-20",.045),{"MKFG":x.guard("2024-09-20",[proof["own_original_share_effect"]])})
    assert x.book._positions["MKFG"]["quantity"]==pytest.approx(.45)

def test_mkfg_original_book_ast_unchanged():
    from pathlib import Path
    before=Path(r"D:/us-tech-quant-cache/V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/pto_dispatch/source_before/reused_r5_risk_inputs_before_mkfg_611bab81.py")
    def book(path):
        tree=ast.parse(Path(path).read_text(encoding="utf-8"))
        return ast.dump(next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="HeldPositionLineageBook"),include_attributes=False)
    assert book(before)==book(m.__file__)


def test_mkfg_public_source_session_commits_once_without_new_pool_or_risk_uid(mkfg):
    x=mkfg;s=x.source;calls=[]
    s.descriptor_bridges=();s.identity_transports=()
    for k in ("source_manifest_ref","static_event_source_ref","source_account_contract_ref"):s.binding[k]=x.ref(k)
    s.original_events=();s.static_events=();s.cash_events=[];s.terminal_events=[];s.unsupported=()
    row=dict(ticker="MKFG",effective_start=pd.Timestamp("2024-05-22"),effective_end=pd.Timestamp("2024-08-20"),security_id="57064N102",security_id_type="CUSIP",cusip="57064N102",issuer_name="Markforged Holding Corp",title_of_class="Common Stock",moomoo_transport_code="US.MKFG",mapping_status="RESOLVED",mapping_source="SYNTHETIC",source_filing="SYNTHETIC_PRE2026")
    current={"day":"2024-09-19"}
    class Reader:
        sources=dict(uid_intervals=x.item["original_uid_intervals_ref"],raw_open_close=x.ref("raw.parquet"),share_ca_audit=x.ref("audit.parquet"))
        def read(self,name,columns,**kwargs):
            calls.append((name,tuple(columns),kwargs))
            if name=="uid_intervals":return pd.DataFrame([row])[list(columns)]
            if name=="raw_open_close":return pd.DataFrame([dict(ticker="MKFG",trade_date=pd.Timestamp(current["day"]),code="US.MKFG")])[list(columns)]
            return pd.DataFrame(columns=columns)
    s.base._components=dict(reader=Reader(),refs={"source":s.binding["source_manifest_ref"]})
    s.base.market_dates=pd.DatetimeIndex(["2024-09-19","2024-09-20"]);s.present=np.ones((2,1),bool)
    original=dict(mask=np.array([False]),record=dict(asset_uids={},asset_epochs={}))
    for day,qty in (("2024-09-19",.45),("2024-09-20",.45)):
        current["day"]=day;ctx=x.ctx(day,qty);ctx.decision_mask=np.array([[True]]);ctx.buy_allowed=np.array([[True]])
        result=s.session(ctx,original,x.book)
        assert result["entry_seeds"]=={} and not result["domain"]["eligible_mask"].any()
        assert result["current_identities"]["MKFG"]==x.old
        assert result["historical_source_epochs"]["MKFG"]=="ORIGINAL_UID_EPOCH"
        guard=result["held_guards"]["MKFG"]
        assert guard["accounting_mapping_basis_proof"]["mapping_sid"]=="CUSIP:57064N201"
        x.book.qualified_proofs(ctx,result["held_guards"])
    assert len(x.book._positions["MKFG"]["processed_share_transitions"])==1
    assert all(not set(cols)&{"Open","Close","NAV","price","notional","return"} for _,cols,_ in calls)

@pytest.fixture
def mkfg_loader(tmp_path,monkeypatch):
    """Mock pin/parser authority only; keep actual dispatch, fragments, rows and source checks."""
    import json
    from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
    from scripts.storage import refresh_sec_event_originals as sec
    mapping={};reads=[]
    ref=lambda label:dict(path=str(tmp_path/label),sha256="a"*64)
    original=ref("original.source");original["sha256"]="7c3ac5071b586b9e16983130fcd7fd987d3fa987c3130292e26ed923d0f6c0a1"
    snippets=[("SPLIT_SAME_COMMON_RATIO_EFFECTIVE",b"<p>1-for-10 Common Stock 12:01 September 19, 2024</p>"),("SPLIT_COMMON_NEW_CUSIP_AND_TICKER",b"<p>57064N201 MKFG Common Stock</p>"),("SPLIT_FRACTIONAL_WHOLE_SHARE_TERM",b"<p>No fractional shares whole number of shares</p>")]
    prefix=b"ACCEPTANCE-DATETIME 20240909161605\nFILED 20240909\n<DOCUMENT>\n";payload=prefix;fragments=[]
    for role,raw in snippets:
        start=len(payload);payload+=raw;fref=ref(role+".fragment");Path(fref["path"]).write_bytes(raw)
        text=raw.decode().replace("<p>","").replace("</p>","")
        fragments.append(dict(role=role,original_byte_range=[start,len(payload)],original_ref=original,raw_fragment_ref=fref,visible_text=text,text_typed_content_sha256=content_hash(text)))
    Path(original["path"]).write_bytes(payload)
    factsref=ref("facts.json");mapping[factsref["path"]]=dict(schema="B_MKFG_2024_SPLIT_ONLY_ORIGINAL_SOURCE_FACTS_V1",date_scope_stop_exclusive="2025-01-01",original_research_fractional_contract_unchanged=True,issuer_roundup_applied=False,header=dict(original_ref=original,source_url="https://synthetic.invalid/pre2026",retrieved_at_utc="2025-01-01T00:00Z"),fragments=fragments)
    event=dict(ticker="MKFG",event_date="2024-09-19",status="SHARE_ONLY_SUPPORTED",quantity_multiplier=.1,source_fingerprint="aaed1d8d6f38463303413f22256579f9fe80814bf690be24a77b4e8883c158d0",event_fingerprint="1629807d873a24c7f3c99806351ee6fcf35bf4fbc861783b6239beadd8da7fc0")
    er=ref("events.json");obj=json.dumps(event).encode();Path(er["path"]).write_bytes(b"PREFIX"+obj+b"SUFFIX")
    objr=ref("object.json");Path(objr["path"]).write_bytes(obj)
    uid=ref("uid.parquet");owner=ref("owner.py");source=ref("source.json")
    row=dict(ticker="MKFG",effective_start=pd.Timestamp("2024-05-22"),effective_end=pd.Timestamp("2024-08-20"),security_id="57064N102",security_id_type="CUSIP",cusip="57064N102",issuer_name="Markforged Holding Corp",title_of_class="Common Stock",moomoo_transport_code="US.MKFG",mapping_status="RESOLVED",mapping_source="SYNTHETIC",source_filing="SYNTHETIC")
    old=dict(security_id="57064N102",security_id_type="CUSIP",cusip="57064N102",share_class="Common Stock",raw_code="US.MKFG",raw_actual_share_coordinate="RAW_ACTUAL_SHARE")
    value=dict(schema="B_MKFG_ISSUER_BOUND_OWN_HELD_ACCOUNTING_COORDINATE_SOURCE_V1",status="DECLARED_SOURCE_INPUT_NOT_RUNTIME_ADMISSION",scope="ORIGINAL_OWN_HELD_IMMUTABLE_SEED_AND_SOURCE_BOUND_POST_SPLIT_ACCOUNTING_LABEL_ONLY",original_uid_intervals_ref=uid,original_event_binding_ref=er,original_research_fractional_contract_unchanged=True,subject=dict(ticker="MKFG",issuer_CIK=1816613,old_CUSIP="57064N102",new_CUSIP="57064N201",share_class="Common Stock",raw_code="US.MKFG",original_issuer="Markforged Holding Corp",public_issuer="Markforged Holding Corporation"),split_only_facts_ref=factsref,original_uid_rows=[dict(source_row=row,source_row_content_sha256=content_hash(row),identity=old)],original_source_event_object_ref=objr,original_source_event_byte_range=[6,6+len(obj)],account_owner_ref=owner)
    for k in ("new_UID_pool_row","BUY_permission","risk_identity_alias","quantity_effect","issuer_roundup_applied","broker_nominee_actual_quantity_certified","historical_observations_relabelled","historical_availability_qualified","strict_PIT","production_qualified","quote_qualified","certified_NAV"):value[k]=False
    mapping[source["path"]]=value
    def read(path):reads.append(str(path));return mapping[str(path)]
    interface=SimpleNamespace(pin=lambda r:Path(r["path"]),read=read)
    monkeypatch.setattr(sec,"parse_original",lambda *args:(dict(accepted_at_utc="2024-09-09T20:16:05Z",accepted_source_raw="20240909161605"),[]))
    for name in ("_load_original_components",):
        monkeypatch.setattr(m,name,lambda *a,**kw:pytest.fail("MARKET_OR_ACCOUNT_OWNER_LOAD_FORBIDDEN"))
    def load():return m._load_delayed_identity_metadata_transport(interface,source,uid,er)
    return SimpleNamespace(load=load,value=value,facts=mapping[factsref["path"]],reads=reads,source=source,uid=uid,events=er)

def test_mkfg_loader_is_source_only_no_market_or_training(mkfg_loader):
    x=mkfg_loader;r=x.load()[0]
    assert r["old_identity"]["cusip"]=="57064N102" and r["public_current_CUSIP"]=="57064N201"
    assert r["issuer_bound_held_accounting_coordinate_only"]
    assert x.reads==[x.source["path"],x.value["split_only_facts_ref"]["path"]]

@pytest.mark.parametrize("defect",["BUY_permission","risk_identity_alias","quantity_effect","issuer_roundup_applied","broker_nominee_actual_quantity_certified","new_UID_pool_row","strict_PIT","subject","rowhash","fragment","facts_scope"])
def test_mkfg_loader_rejects_scope_and_original_fact_mutations(mkfg_loader,defect):
    x=mkfg_loader
    if defect=="subject":x.value["subject"]["new_CUSIP"]="OTHER"
    elif defect=="rowhash":x.value["original_uid_rows"][0]["source_row_content_sha256"]="b"*64
    elif defect=="fragment":x.facts["fragments"][0]["visible_text"]="FAKE"
    elif defect=="facts_scope":x.facts["date_scope_stop_exclusive"]="2026-01-01"
    else:x.value[defect]=True
    with pytest.raises(m.ExistingRiskInputUnavailable):x.load()
