"""C14 outcomes admission tests: real gates, entirely synthetic H5 projection."""
from copy import deepcopy
from pathlib import Path
import json
import pandas as pd
import pytest

from scripts.research.a2.data import selector_maximal_risk_outcomes as s

PRODUCTION_ML_SHA = "7d68b43b9ee7d63b35f80fa8515f19dc007a167c5e7eba53e2dcde905be52fed"


def put(path, value):
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")
    return dict(path=str(path), sha256=s.binding.sha(path))


def c14_design():
    ev = s.evidence
    ids = [f"SYNTHETIC_LEGACY_{i}" for i in range(147)]
    failed = {f"SYNTHETIC_BLOCKED_{i}": "RETAINED" for i in range(79)}
    sources = {str(Path(m.__file__).resolve()): s.binding.sha(m.__file__)
               for m in (s.owner, s.owner.owner, s.owner.identity_owner, s.owner.namespace_owner, ev)}
    return dict(research_id=s.ID, official_freeze=True, formal_freeze_applied=True,
        roles=list(ev.ROLES), target=ev.TARGET, mechanism_research_eligible=True,
        strict_PIT_promotion_eligible=False, test2026_locked=True, new2026_estimation_authorized=False,
        read2027_authorized=False, blocked_roles={r:"BLOCKED_BUDGET" for r in (*ev.DELTA,"C14_D12")},
        sources=sources, evaluation=dict(common_mature_date_count=732, original_calendar_dates=752,
            year_counts=ev.YEAR_COUNTS, progressive_mature_date_count=482,
            progressive_year_counts=ev.PROGRESSIVE_COUNTS, exposure_namespace=321,
            legacy=dict(numeric_ids=ids, exposure_ids=ids+list(failed), failed_or_untestable=failed),
            new_specs=ev.role_specs(), risk_specs=list(ev.RISK_SPECS),
            bootstrap=dict(method=ev.BOOT_METHOD,repeats=5000,block=20,seed=20260928,confidence=.95)))


@pytest.fixture
def state(tmp_path, monkeypatch):
    run = tmp_path / "C14_SYNTHETIC"
    run.mkdir()
    monkeypatch.setattr(s, "RUN", run)
    days = pd.bdate_range("2025-01-01", periods=30)
    when = days[10]
    keys = s.owner.requested_keys(pd.DataFrame(dict(signal_date=[when,when],
        security_uid=["CUSIP:123456789","CUSIP:987654321"],ticker=["AAA","BBB"])))
    design = c14_design()
    paths = {k:run/n for k,n in dict(design="DESIGN_FREEZE.json",review="SYNTHETIC_REVIEW.json",
        gate="SYNTHETIC_OUTCOME_GATE.json",assembly="SYNTHETIC_RISK_ASSEMBLY.json",
        final="SYNTHETIC_RISK_FINAL.json",old="FINAL_PIPELINES_FREEZE.json").items()}
    dref = put(paths["design"], design)
    monkeypatch.setattr(s.binding, "DESIGN_SHA", dref["sha256"])
    pins = dict(design["sources"])
    pins.update({str(Path(m.__file__).resolve()):s.binding.sha(m.__file__) for m in (s.binding,s)})
    review = dict(status="PASS",research_id=s.ID,source_pins=pins,
                  adapter_sha256=s.binding.sha(s.binding.__file__))
    rref = put(paths["review"], review)
    statuses = {r:("BLOCKED_BUDGET" if r in (*s.evidence.DELTA,"C14_D12") else "COMPLETE")
                for r in s.evidence.ROLES}
    assembly = dict(status="SCORE_ASSEMBLY_COMPLETE", design_freeze_sha256=dref["sha256"],
        pair_key_sha256="d"*64, complete_candidates=[r for r, status in statuses.items() if status=="COMPLETE"],
        failed_or_untestable={r:status for r,status in statuses.items() if status!="COMPLETE"},
        forecast2026_rows=0)
    aref = put(paths["assembly"], assembly)
    final = dict(status="FINAL_PIPELINES_FROZEN",research_id=s.ID,design_sha256=dref["sha256"],
        all_training_terminal=True,capacity_selection_complete=True,roles=list(s.evidence.ROLES),
        role_statuses=statuses,score_assembly_sha256=aref["sha256"],fit_ledger_sha256="c"*64,
        pair_key_sha256="d"*64,forecast2026_rows=0)
    fref = put(paths["final"], final)
    old = deepcopy(final)
    oldref = put(paths["old"], old)
    monkeypatch.setattr(s, "OLD_ML_GATE_SHA", oldref["sha256"])
    delta = run/"RISK_EXECUTION_DELTA.jsonl"
    delta.write_text("SYNTHETIC_OPAQUE_DELTA_NEVER_PARSE\n",encoding="utf-8")
    gate = dict(status="PASS",research_id=s.ID,design_sha256=dref["sha256"],review_ref=rref,
        decision_frozen=True,outcome_reads_before_gate=0,requested_keys_sha256=s.content_hash(keys),
        test2026_rows_read=0,strict_PIT_promotion_eligible=False,
        score_assembly_ref=aref,final_pipeline_ref=fref,all_applicable_risk_roles_terminal=True,
        full_calendar_count=752,mature_count=732,progressive_mature_count=482,
        risk_delta_ref=dict(path=str(delta),sha256=s.binding.sha(delta)),
        original_ml_gate_ref=oldref,h5_sources=deepcopy(s.H5_REFS))
    gref = put(paths["gate"],gate)
    calls = []
    def forbidden_reader(*args,**kwargs):
        calls.append("READER_CONSTRUCTOR")
        raise AssertionError("NO_NUMERIC_READER_BEFORE_ALL_GATES")
    monkeypatch.setattr(s.owner,"H5ProjectedReader",forbidden_reader)
    return dict(run=run,days=days,keys=keys,paths=paths,calls=calls,
        docs=dict(design=design,review=review,gate=gate,assembly=assembly,final=final,old=old),
        refs=dict(design=dref,review=rref,gate=gref))


def save(state, part, monkeypatch):
    docs, paths, refs = state["docs"], state["paths"], state["refs"]
    ref = put(paths[part], docs[part])
    if part == "review":
        refs["review"] = ref
        docs["gate"]["review_ref"] = ref
    elif part == "final":
        docs["gate"]["final_pipeline_ref"] = ref
    elif part == "assembly":
        docs["gate"]["score_assembly_ref"] = ref
        docs["final"]["score_assembly_sha256"] = ref["sha256"]
        save(state,"final",monkeypatch)
    elif part == "old":
        docs["gate"]["original_ml_gate_ref"] = ref
        # Only the small synthetic baseline constant is rebound, never production bytes.
        monkeypatch.setattr(s,"OLD_ML_GATE_SHA",ref["sha256"])
    elif part == "design":
        refs["design"] = ref
        monkeypatch.setattr(s.binding,"DESIGN_SHA",ref["sha256"])
        docs["gate"]["design_sha256"] = ref["sha256"]
        docs["assembly"]["design_freeze_sha256"] = ref["sha256"]
        docs["final"]["design_sha256"] = ref["sha256"]
        docs["old"]["design_sha256"] = ref["sha256"]
        save(state,"assembly",monkeypatch)
        save(state,"old",monkeypatch)
    refs["gate"] = put(paths["gate"],docs["gate"])


def call(state, keys=None):
    refs = state["refs"]
    return s.read_h5(refs["design"],refs["review"],refs["gate"],
                     state["keys"] if keys is None else keys)


@pytest.mark.parametrize("part,key,value", [
    ("design","formal_freeze_applied",False), ("design","research_id","C13_AUTHORITY"),
    ("design","strict_PIT_promotion_eligible",True), ("design","new2026_estimation_authorized",True),
    ("review","status","FAIL"), ("review","research_id","C13_AUTHORITY"),
    ("review","adapter_sha256","0"*64),
    ("gate","status","WAITING"), ("gate","decision_frozen",False),
    ("gate","outcome_reads_before_gate",1), ("gate","requested_keys_sha256","0"*64),
    ("gate","test2026_rows_read",1), ("gate","strict_PIT_promotion_eligible",True),
    ("gate","all_applicable_risk_roles_terminal",False),
    ("gate","full_calendar_count",751), ("gate","mature_count",731),
    ("gate","progressive_mature_count",481),
    ("assembly","status","INCOMPLETE"), ("assembly","pair_key_sha256","e"*64),
    ("assembly","forecast2026_rows",1), ("final","all_training_terminal",False),
    ("final","capacity_selection_complete",False), ("final","score_assembly_sha256","0"*64),
    ("final","forecast2026_rows",1), ("old","status","NOT_FROZEN"),
])
def test_each_real_gate_rejects_before_reader(state,monkeypatch,part,key,value):
    state["docs"][part][key] = value
    save(state,part,monkeypatch)
    with pytest.raises(ValueError):
        call(state)
    assert state["calls"] == []


@pytest.mark.parametrize("status", ["STARTED","WAITING","UNKNOWN","RESERVED","RUNNING","PENDING"])
def test_risk_final_exact_terminal_statuses_only_before_reader(state,monkeypatch,status):
    state["docs"]["final"]["role_statuses"]["C14_RX_HGB_LW"] = status
    save(state,"final",monkeypatch)
    with pytest.raises(ValueError):
        call(state)
    assert state["calls"] == []


@pytest.mark.parametrize("module_name", ["owner","projection","identity","namespace","evidence","binding","self"])
def test_every_required_frozen_or_reviewed_source_pin_cannot_be_omitted(state,monkeypatch,module_name):
    modules = dict(owner=s.owner,projection=s.owner.owner,identity=s.owner.identity_owner,
                   namespace=s.owner.namespace_owner,evidence=s.evidence,binding=s.binding,self=s)
    name = str(Path(modules[module_name].__file__).resolve())
    state["docs"]["review"]["source_pins"].pop(name)
    save(state,"review",monkeypatch)
    with pytest.raises(ValueError):
        call(state)
    assert state["calls"] == []


@pytest.mark.parametrize("module_name", ["owner","projection","identity","namespace","evidence"])
def test_original_design_dependency_pin_cannot_be_dropped(state,monkeypatch,module_name):
    modules = dict(owner=s.owner,projection=s.owner.owner,identity=s.owner.identity_owner,
                   namespace=s.owner.namespace_owner,evidence=s.evidence)
    state["docs"]["design"]["sources"].pop(str(Path(modules[module_name].__file__).resolve()))
    save(state,"design",monkeypatch)
    with pytest.raises(ValueError,match="CLOSURE"):
        call(state)
    assert state["calls"] == []


@pytest.mark.parametrize("which", ["delta_sha","delta_path","old_sha","old_path","H5_sha","H5_path","review_ref"])
def test_exact_delta_old_gate_h5_and_review_custody_before_reader(state,monkeypatch,which):
    gate = state["docs"]["gate"]
    if which == "delta_sha": gate["risk_delta_ref"]["sha256"] = "0"*64
    elif which == "delta_path": gate["risk_delta_ref"]["path"] = str(state["run"]/"OTHER_DELTA.jsonl")
    elif which == "old_sha": gate["original_ml_gate_ref"]["sha256"] = "0"*64
    elif which == "old_path": gate["original_ml_gate_ref"]["path"] = str(state["run"]/"OTHER_OLD_GATE.json")
    elif which == "H5_sha": gate["h5_sources"]["labels"]["sha256"] = "0"*64
    elif which == "H5_path": gate["h5_sources"]["labels"]["path"] = "D:/UNAUTHORIZED_H5.parquet"
    else: gate["review_ref"]["sha256"] = "0"*64
    save(state,"gate",monkeypatch)
    with pytest.raises(ValueError):
        call(state)
    assert state["calls"] == []


@pytest.mark.parametrize("module_name", ["owner","projection","identity","namespace","evidence","binding","self"])
def test_physical_source_digest_change_blocks_before_reader(state,monkeypatch,module_name):
    modules = dict(owner=s.owner,projection=s.owner.owner,identity=s.owner.identity_owner,
                   namespace=s.owner.namespace_owner,evidence=s.evidence,binding=s.binding,self=s)
    changed = Path(modules[module_name].__file__).resolve()
    real_sha = s.binding.sha
    monkeypatch.setattr(s.binding,"sha",lambda path: "0"*64 if Path(path).resolve()==changed else real_sha(path))
    with pytest.raises(ValueError):
        call(state)
    assert state["calls"] == []


def test_changed_physical_gate_bytes_cannot_be_reinterpreted(state):
    state["paths"]["gate"].write_text("{}",encoding="utf-8")
    with pytest.raises(ValueError,match="PHYSICAL_SHA_CHANGED"):
        call(state)
    assert state["calls"] == []


@pytest.mark.parametrize("kind", ["future","duplicate","unknown_uid","non_midnight"])
def test_requested_keys_are_checked_before_reader_or_numeric_source(state,kind):
    keys = state["keys"].copy()
    if kind == "future": keys.loc[0,"signal_date"] = pd.Timestamp("2026-01-01")
    elif kind == "duplicate": keys = pd.concat([keys,keys.iloc[:1]],ignore_index=True)
    elif kind == "unknown_uid": keys.loc[0,"security_uid"] = None
    else: keys.loc[0,"signal_date"] += pd.Timedelta(hours=1)
    with pytest.raises(ValueError):
        call(state,keys)
    assert state["calls"] == []


def test_only_two_kernel_dependencies_exact_code_and_c14_receipt_globals_unchanged(state,monkeypatch):
    keys,days = state["keys"],state["days"]
    when = days[10]
    origins = pd.DataFrame(dict(signal_date=[when,when],ticker=["AAA","BBB"],
        security_id=["123456789","987654321"],security_id_type="CUSIP",cusip=["123456789","987654321"]))
    members = pd.DataFrame([(day,ticker,uid) for day in days
        for ticker,uid in (("AAA","123456789"),("BBB","987654321"))],
        columns=["signal_date","ticker","cusip"])
    labels = pd.DataFrame(dict(signal_date=[when,when],ticker=["AAA","BBB"],
        execution_date=days[11],label_end_date=days[16],label_mature_date=days[16],
        label_coordinate=s.owner.H5_COORDINATE,label_available=True,endpoint_pair_available=True,
        label_unsupported_common_event=False,y_open5=[.02,.03]))
    frames = dict(calendar=pd.DataFrame(dict(trade_date=days)),membership=members,
                  identity=origins,labels=labels)
    projections = []
    class Reader:
        def __init__(self, refs):
            assert refs == s.H5_REFS
            self.phase,self.audit = "support",[]
        def read(self,name,columns,*,date_field,start=None,stop=None,day=None,tickers=None,**kwargs):
            if "y_open5" in columns:
                assert self.phase == "postdecision"
            projections.append((name,tuple(columns),self.phase))
            frame = frames[name]
            keep = pd.Series(True,index=frame.index)
            if start is not None: keep &= frame[date_field].ge(start)
            if stop is not None: keep &= frame[date_field].lt(stop)
            if day is not None: keep &= frame[date_field].eq(day)
            if tickers is not None: keep &= frame.ticker.isin(tickers)
            out = frame.loc[keep,list(columns)].copy()
            self.audit.append(dict(source=name,columns=list(columns),rows=len(out)))
            return out
    refs_seen = []
    def exact_synthetic_ref(ref):
        assert ref in list(s.H5_REFS.values())
        refs_seen.append(ref)
        return Path(ref["path"])
    monkeypatch.setattr(s.owner,"H5ProjectedReader",Reader)
    monkeypatch.setattr(s.owner,"_ref",exact_synthetic_ref)
    real_binder = s.bind_pinned_kernel
    clones = []
    def capture(function,**kwargs):
        assert function is s.owner.read_h5
        assert set(kwargs["dependencies"]) == {"gates","RESEARCH_ID"}
        assert kwargs["dependencies"]["gates"] is s.gates
        assert kwargs["dependencies"]["RESEARCH_ID"] == s.ID
        clone = real_binder(function,**kwargs)
        assert clone.__code__ is function.__code__
        assert clone.__globals__ is not function.__globals__
        clones.append(clone)
        return clone
    monkeypatch.setattr(s,"bind_pinned_kernel",capture)
    before = dict(s.owner.read_h5.__globals__)
    result,receipt = call(state)
    assert len(result) == 2 and result.qualified.all()
    assert result.return_value.tolist() == [.02,.03]
    assert receipt["research_id"] == s.ID
    assert receipt["schema"] == "C14_POSTDECISION_H5_SOURCE_RECEIPT_V1"
    assert receipt["kernel_receipt_schema"] == "C13_POSTDECISION_H5_SOURCE_RECEIPT_V1"
    assert receipt["C13_contract_or_bank_authority_used"] is False
    assert receipt["original_kernel_code_reused"] is receipt["original_module_globals_unchanged"] is True
    assert receipt["test2026_reads"] == receipt["outcome_reads_before_gate"] == receipt["new_fits"] == 0
    assert receipt["new_state_estimations"] == 0 and receipt["strict_PIT_promotion_eligible"] is False
    assert len(clones) == 1 and len(refs_seen) == 4
    after = s.owner.read_h5.__globals__
    assert set(before) == set(after) and all(before[k] is after[k] for k in before)
    assert [p for p in projections if "y_open5" in p[1]] == [("labels",("signal_date","ticker","y_open5"),"postdecision")]


def test_production_literals_and_frozen_projection_owner_remain_exact():
    assert s.OWNER_SHA == "db41eea99bdc80eb158bf2d978fde43cac9905517492402e9fe977bc01dfb252"
    assert s.OLD_ML_GATE_SHA == PRODUCTION_ML_SHA
    assert s.TERMINAL == {"COMPLETE","FAILED_UNTESTABLE","BLOCKED_INPUT","BLOCKED_BY_CURRENT_B_SCOPE","BLOCKED_BUDGET"}
    assert s.binding.sha(s.owner.__file__) == s.OWNER_SHA

