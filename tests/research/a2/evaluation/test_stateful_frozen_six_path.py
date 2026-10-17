"""Synthetic-only six-path scheduling/account-owner/description checks."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import stateful_frozen_six_path as six
from scripts.research.a2.evaluation import frozen_test_authority as authority
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision
from scripts.research.a2.training import stateful_account as policy
from scripts.research.a2.training import stateful_decision as decision
from scripts.research.a2.training.stateful_final_action_packets import decode_r6_row
from scripts.research.a2.inference import stateful_frozen_test as frozen_inference
from scripts.v22.corporate_action_transition_r1 import RAW_OLD_SHARE_COORDINATE

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("_six_path_synthetic_common_fixture",
    ROOT / "tests/research/a2/evaluation/test_continuous_research_account.py")
fixtures = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)
descriptive_fixture = fixtures.descriptive_fixture


@pytest.fixture(autouse=True)
def no_real_model_custody_reads(monkeypatch):
    # Handles below are synthetic serialized-state stand-ins. Real source/model
    # custody is separately tested by test_stateful_frozen_test; no model is read.
    monkeypatch.setattr(frozen_inference, "_check_sources", lambda bundle: {})


def policies(plan=None):
    plan = plan or dict(account=dict(fractional=True, execution="ORIGINAL_NEXT_LEGAL_RAW_OPEN",
        friction_bps_each_executed_notional=10, terminal_liquidation=False),
        comparison=dict(benchmark_contract="SYNTHETIC_FROZEN_ETF_CONTRACT"))
    rows = []
    for cid in six.PATH_IDS[:4]:
        row = dict(candidate_id=cid, action="stateful" if cid == six.PATH_IDS[3] else "raw",
            action_cost_mode="aware" if cid == six.PATH_IDS[3] else "blind",
            control="none", gross="fixed", risk="diag20_reference", forecast="none",
            value_model="ngboost" if cid == six.PATH_IDS[3] else "ridge", target_role="shareholder5d",
            scientific_tuple_sha256=authority.POLICY_TUPLE_SHA256[cid],
            execution_friction=fixtures._descriptive_friction())
        if cid in six.PATH_IDS[1:3]:
            row.update(original_scientific_family="R6_buy_tree" if cid == six.PATH_IDS[1] else "R6_replace_tree",
                model_output_state="ORIGINAL_FROZEN_PROXY_NOT_ACTUAL_ACCOUNT_STATE")
        rows.append(row)
    for cid in six.PATH_IDS[4:]:
        contract = authority.benchmark_contract(plan, cid)
        rows.append(dict(candidate_id=cid, benchmark_contract=contract,
            scientific_tuple_sha256=six._commit(contract), execution_friction=fixtures._descriptive_friction()))
    return rows


def test_metadata_loader_reuses_full_rows_and_checks_physical_pins(tmp_path, monkeypatch):
    rows = policies()
    plan = dict(account=dict(fractional=True, execution="ORIGINAL_NEXT_LEGAL_RAW_OPEN",
        friction_bps_each_executed_notional=10, terminal_liquidation=False),
        comparison=dict(benchmark_contract="SYNTHETIC_FROZEN_ETF_CONTRACT"))
    def ref(name, value):
        p = tmp_path / name; p.write_text(json.dumps(value), encoding="utf-8")
        return dict(path=str(p), sha256=six.hashlib.sha256(p.read_bytes()).hexdigest())
    rows[1]["original_member_refs"] = [dict(source="SYNTHETIC_2025_FROZEN_ARTIFACT")]
    refs = dict(raw=ref("raw.json", rows[:1]), action=ref("action.json", dict(candidates=rows[1:3])),
        breadth=ref("breadth.json", dict(specification=dict(candidates_in_exact_order=rows[3:4]))))
    pref = ref("plan.json", plan)
    monkeypatch.setattr(six, "POLICY_REFS", refs)
    monkeypatch.setattr(authority, "PLAN_SHA256", pref["sha256"])
    actual = six.load_frozen_policies(pref)
    assert actual[1]["original_member_refs"] == rows[1]["original_member_refs"]
    assert actual[3]["value_model"] == "ngboost" and actual[3]["action_cost_mode"] == "aware"
    Path(refs["raw"]["path"]).write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="SOURCE_SHA_CHANGED"):
        six.load_frozen_policies(pref)


@pytest.mark.parametrize("index,field,value", [
    (0,"action","stateful"),(0,"value_model","ngboost"),(1,"gross","dynamic"),
    (2,"control","hysteresis"),(3,"action_cost_mode","blind"),(3,"forecast","return_shrink"),
    (0,"scientific_tuple_sha256","a"*64),(4,"scientific_tuple_sha256","b"*64)])
def test_exact_policy_scalar_changes_rejected(index, field, value):
    rows = policies(); rows[index][field] = value
    with pytest.raises(ValueError, match="FROZEN_POLICY_SCALARS|FROZEN_ETF_CONTRACT"):
        six._validate_policy_rows(rows)


def test_schedule_fixed_100_seed_order_606_and_signal_context():
    dates = pd.bdate_range("2026-01-02", "2026-10-07")
    result = six.build_schedule(dates, as_of="2026-10-08T09:00:00+09:00")
    assert result["account_paths"] == 606 and result["random_start_count"] == 100
    main = result["windows"][0]
    assert main["account_initialization"] == "2026-01-02"
    assert main["first_execution_date"] == "2026-01-05"
    eligible = np.arange(2, len(dates)-19)
    expected = np.sort(np.random.Generator(np.random.PCG64(20261008)).choice(eligible, 100, replace=False))
    assert [w["first_execution_date"] for w in result["windows"][1:]] == [str(dates[i].date()) for i in expected]
    assert all(w["execution_sessions"] >= 20 for w in result["windows"][1:])
    assert all(w["start"] < w["first_execution_date"] <= w["end"] for w in result["windows"])
    assert six.build_schedule(dates, as_of=result["as_of"]) == result


def test_schedule_uses_all_short_eligible_and_excludes_incomplete_close():
    dates = pd.bdate_range("2026-01-02", periods=25)
    result = six.build_schedule(dates, as_of=(dates[-1]+pd.Timedelta(hours=15)).tz_localize("America/New_York"))
    assert result["common_end"] == str(dates[-2].date())
    assert result["random_start_count"] == 3
    assert result["account_paths"] == 24


@pytest.mark.parametrize("dates", [["2025-12-31","2026-01-02"],["2026-12-31","2027-01-01"],
    ["2026-01-05","2026-01-02"],["2026-01-02","2026-01-02"]])
def test_calendar_boundary_rejected(dates):
    with pytest.raises(ValueError, match="2026_CALENDAR"):
        six.build_schedule(dates, as_of="2026-10-08T00:00:00+09:00")


class SyntheticReference:
    def __init__(self, value, sigma, unused, vol_unused, vol, top, qualified, lineage):
        self.top, self.qualified = top, qualified
    def __call__(self, j, ctx):
        eligible = self.top[j] & self.qualified[j] & ctx.buy_allowed[0] & ctx.decision_mask[0]
        w = eligible.astype(float)[None, :] / max(int(self.top[j].sum()), 1)
        return TargetDecision(w, ctx.decision_mask.copy())


def synthetic_inputs(dates):
    names = tuple(f"S{i:02d}" for i in range(20)); shape = (len(dates),20)
    top = np.ones(shape,bool)
    market = MarketArrays(dates, names, np.full(shape,10.), np.full(shape,10.),
        input_present=top.copy(), new_buy_eligible=top.copy(), adv=np.full(shape,1e9))
    kwargs = dict(entitlement_enabled=True, entitlement_events=(), entitlement_security_tickers={},
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",
            source_fingerprint="d"*64, event_fingerprints=[], security_tickers={},
            quantity_coordinate=RAW_OLD_SHARE_COORDINATE))
    packets = {name:dict(mu=np.full(shape,.03), sigma=np.full(len(dates),.001),
        lineage=np.full(len(dates),"SYNTHETIC_NO_MODEL_PREDICT")) for name in ("ridge","ngboost")}
    account = fixtures.config(); account["capacity_fraction"] = None
    stocks = dict(market=market, packets=packets, top=top, qualified=top.copy(),
        vol=np.full(shape,.02), account=account, account_source_kwargs=kwargs,
        stock_present=top.copy(), raw_selector_present=top.copy(),
        sid_by_key={(d,n):"SID_"+n for d in dates for n in names},
        action_packets={})
    evidence = {}
    for cid, objective, features in zip(authority.MODEL_IDS, ("buy", "replace", "ngboost"),
                                        (decision.SINGLE, decision.PAIR, decision.inputs.FEATURES)):
        bundle = frozen_inference.Frozen2025Model(cid, objective, tuple(features), None, "{}",
            dict(path="synthetic://model",sha256=authority.MODEL_SHA256[cid]),
            dict(path="synthetic://receipt",sha256=frozen_inference.RECEIPT_SHA256[cid]),frozen_inference._SEAL)
        if objective == "buy":
            row = dict.fromkeys(features, .01)
            row.update(signal_date=dates[0],sample_id="SYNTHETIC_BUY_SKIP",ticker="S00",
                       security_id="SID_S00",cohort_age_sessions=0)
            samples = pd.DataFrame([row])
            pred = samples[["signal_date","sample_id","ticker","security_id","cohort_age_sessions"]].assign(p_superior=.2,model_year=2025)
            stocks["action_packets"][cid] = {dates[0]:[decode_r6_row(pred.iloc[0].to_dict(),"buy",0)]}
        elif objective == "replace":
            samples = pd.DataFrame(columns=["signal_date","sample_id","ticker","security_id","incumbent","incumbent_sid",*features])
            pred = pd.DataFrame(columns=["signal_date","sample_id","ticker","security_id","incumbent","incumbent_sid","p_superior","model_year"])
            stocks["action_packets"][cid] = {}
        else:
            samples = None
            pred = pd.DataFrame([dict(signal_date=d,ticker=t,prediction_qualified=True,
                prediction=.03,value_sigma=.001,year=2025,model_sha256=authority.MODEL_SHA256[cid])
                for d in dates for t in names])
        counts=pred.groupby("signal_date").size()
        support=pd.DataFrame(dict(signal_date=dates,eligible_count=[int(counts.get(d,0)) for d in dates]))
        support["status"]=np.where(support.eligible_count.gt(0),"INFERRED","NO_SUPPORT")
        support["reason"]=np.where(support.eligible_count.gt(0),"", "ORIGINAL_PRODUCER_SUPPORT_MASK_EMPTY")
        evidence[cid]=dict(bundle=bundle,samples=samples,predictions=pred,support=support)
    stocks["inference_evidence"] = evidence
    result = dict(stocks=stocks)
    for cid, price in zip(six.PATH_IDS[4:], (100.,200.)):
        result[cid] = dict(market=MarketArrays(dates,[cid.split("_")[0]],
            np.full((len(dates),1),price),np.full((len(dates),1),price),adv=np.full((len(dates),1),1e9)),
            account=account, account_source_kwargs=kwargs)
    return result


def test_six_accounts_use_sole_owners_first_nextopen_fees_and_isolation(descriptive_fixture, monkeypatch):
    _, bound, ref, _ = descriptive_fixture
    monkeypatch.setattr(policy, "reference_policy_class", lambda:SyntheticReference)
    dates = pd.DatetimeIndex(["2026-01-02","2026-01-05","2026-01-06","2026-01-07","2026-01-08"])
    schedule = six.build_schedule(dates, as_of=bound["as_of"])
    inputs = synthetic_inputs(dates); events=[]; saved={}; owners=[]
    original_stock=six.replay.execute_market; original_etf=six.run_continuous_account
    def stock(*a,**kw): owners.append("sole_stock_replay"); return original_stock(*a,**kw)
    def etf(*a,**kw): owners.append("sole_common_account"); return original_etf(*a,**kw)
    monkeypatch.setattr(six.replay,"execute_market",stock)
    monkeypatch.setattr(six,"run_continuous_account",etf)
    reports = six.execute_schedule(schedule, policies(), authority_for_window=lambda w:ref(),
        inputs_for_window=lambda w,a:inputs, record_event=events.append,
        consume_result=lambda w,c,f,r:saved.update({c["candidate_id"]:f}))
    assert [r["status"] for r in reports] == ["QUALIFIED_DESCRIPTIVE"]*6, [
        (r["candidate_id"],r.get("error")) for r in reports if "error" in r]
    assert owners == ["sole_stock_replay"]*4+["sole_common_account"]*2
    assert [e["event"] for e in events] == ["STARTED","COMPLETE"]*6
    for cid, frames in saved.items():
        d=frames["daily"]
        assert d.iloc[0].cash == 3000 and d.iloc[0].TOTAL_ECONOMIC_NAV == 3000
        assert not frames["fills"].execution_date.lt("2026-01-05").any()
        assert frames["daily"].actual_cash_flow_identity_error.abs().max() < 1e-8
    assert "S00" in set(saved[six.PATH_IDS[0]]["fills"].ticker)
    first=saved[six.PATH_IDS[1]]["fills"]
    assert "S00" not in set(first.loc[first.execution_date.eq("2026-01-05"),"ticker"])
    assert inputs["stocks"]["account"]["max_positions"] == 20
    assert inputs["stocks"]["account"]["capacity_fraction"] is None
    for cid in six.PATH_IDS[4:]:
        frames=saved[cid]
        assert frames["fills"].side.tolist() == ["BUY"]
        assert reports[six.PATH_IDS.index(cid)]["metrics"]["cumulative_return"] == pytest.approx(1/1.001-1)
        assert frames["daily"].transaction_cost_amount.sum() == pytest.approx(3000*.001/1.001)
    assert six.execute_schedule(schedule, policies(), authority_for_window=lambda w:pytest.fail("no replay"),
        inputs_for_window=lambda w,a:pytest.fail("no input"), record_event=events.append,
        consume_result=lambda *a:pytest.fail("no outputs"),prior_events=events.copy()) == []


def test_unbound_authority_rejects_before_any_numeric_input(descriptive_fixture):
    _, bound, ref, _ = descriptive_fixture
    schedule = six.build_schedule(pd.bdate_range("2026-01-02",periods=5),as_of=bound["as_of"])
    bad=deepcopy(bound); bad["source_refs"]={}
    with pytest.raises(ValueError, match="SOURCE_SLOTS_UNBOUND"):
        six.execute_schedule(schedule,policies(),authority_for_window=lambda w:ref(bad),
            inputs_for_window=lambda *a:pytest.fail("numeric read before source admission"),
            record_event=lambda *a:pytest.fail("no account attempt"), consume_result=lambda *a:None)


@pytest.mark.parametrize("change", ["budget","order","seed","outstanding","duplicate"])
def test_controller_budget_order_retry_guards(change):
    schedule=six.build_schedule(pd.bdate_range("2026-01-02",periods=5),as_of="2026-01-08T22:00:00Z")
    events=[]
    if change=="budget":schedule["account_paths"]=607
    if change=="order":schedule["path_ids"].reverse()
    if change=="seed":schedule["seed"]=1
    if change in ("outstanding","duplicate"):
        events=[dict(event="STARTED",window_id="MAIN",candidate_id=six.PATH_IDS[0])]
        if change=="duplicate":events*=2
    with pytest.raises(ValueError,match="SCHEDULE_OR_BUDGET|DUPLICATE_OR_OUTSTANDING"):
        six.execute_schedule(schedule,policies(),authority_for_window=lambda w:pytest.fail("preflight only"),
            inputs_for_window=lambda *a:pytest.fail("no input"),record_event=lambda *a:None,
            consume_result=lambda *a:None,prior_events=events)


def test_failed_paths_preserved_no_scientific_retry(descriptive_fixture,monkeypatch):
    _,bound,ref,_=descriptive_fixture
    dates=pd.bdate_range("2026-01-02",periods=5)
    schedule=six.build_schedule(dates,as_of=bound["as_of"]);events=[]
    def fail(*a,**kw): raise RuntimeError("SYNTHETIC_ENGINEERING_FAILURE")
    monkeypatch.setattr(six,"_execute_path",fail)
    reports=six.execute_schedule(schedule,policies(),authority_for_window=lambda w:ref(),
        inputs_for_window=lambda *a:synthetic_inputs(dates),record_event=events.append,consume_result=lambda *a:None)
    assert len(reports)==6 and all(r["scientific_retry"]==0 for r in reports)
    assert [e["event"] for e in events]==["STARTED","FAILED"]*6


def test_daily_comparisons_null_zero_denominators_exact_alignment_and_first_cost():
    d=pd.DataFrame(dict(date=list(pd.bdate_range("2026-01-02",periods=3))*2,
        path_id=["P"]*3+["B"]*3,TOTAL_ECONOMIC_NAV=[3000.,2997.,3030.,3000.,3000.,3000.]))
    r=six.matched_daily_comparison(d,"P","B")
    assert r["net_return_difference"] == pytest.approx(.01)
    assert r["descriptive_OLS_beta"] is None and r["descriptive_OLS_daily_alpha"] is None
    assert r["daily_excess_positive_fraction"] == pytest.approx(1/3)
    with pytest.raises(ValueError,match="MATCHED_INTERVAL"):
        six.matched_daily_comparison(d.iloc[:-1],"P","B")


def test_random_summary_qualified_denominator_ties_failures_all_reported():
    windows=[dict(window_id="MAIN",kind="MAIN")]+[dict(window_id=f"R{i}",kind="RANDOM") for i in range(4)]
    reports=[]
    for i,excess in enumerate((.1,0.,-.1)):
        for cid,value in (("P",excess),("B",0.)):
            reports.append(dict(window_id=f"R{i}",candidate_id=cid,status="QUALIFIED_DESCRIPTIVE",
                metrics=dict(cumulative_return=value)))
    reports.append(dict(window_id="R3",candidate_id="P",status="NOT_TESTABLE"))
    r=six.random_start_summary(reports,dict(windows=windows),"P","B")
    assert r["matched_qualified_starts"]==3 and r["win_rate"]==pytest.approx(1/3)
    assert r["ties"]==1 and r["losses"]==1 and r["unqualified_or_missing_starts"]==["R3"]
    assert r["excess_median"]==0.


def metric_frames(nav):
    n=len(nav);dates=pd.bdate_range("2026-01-02",periods=n);cid="RAW_s10"
    d=pd.DataFrame(dict(path_id=[cid]*n,date=dates,TOTAL_ECONOMIC_NAV=nav,LIQUID_NAV=nav,
        cash=nav,nav=nav,certified_nav=nav,accounting_qualified=True,
        transaction_cost_amount=0.,buy_notional=0.,sell_notional=0.,turnover=0.,
        research_gross=0.,research_cash_weight=1.,receivable_value_usd=0.,actual_cash_flow_identity_error=0.))
    return dict(daily=d,positions=pd.DataFrame(columns=["path_id","date","ticker","holding_age","index_units","market_value","stale","unknown"]),
        fills=pd.DataFrame(columns=["path_id","ticker","execution_date","signal_date","side","index_units_before","index_units_after"]),
        actions=pd.DataFrame(columns=["path_id","policy_action"]),
        execution_results=pd.DataFrame(columns=["path_id","status"]))


@pytest.mark.parametrize("nav", [[3000.,3000.,3000.],[3000.,2997.,3027.,3000.]])
def test_frozen_metric_formulas_and_null_denominators(nav):
    frames=metric_frames(nav);r=np.asarray(nav)/np.r_[3000.,np.asarray(nav)[:-1]]-1.
    metrics=six.descriptive_metrics(policies()[0],frames)
    if np.std(r,ddof=1)==0:
        assert metrics["Sharpe_rf0"] is None and metrics["Sortino_MAR0"] is None and metrics["Calmar"] is None
    else:
        assert metrics["Sharpe_rf0"]==pytest.approx(np.sqrt(252.)*np.mean(r)/np.std(r,ddof=1))
        assert metrics["Sortino_MAR0"]==pytest.approx(np.sqrt(252.)*np.mean(r)/np.sqrt(np.mean(np.minimum(r,0.)**2)))
        assert metrics["drawdown_duration_max_sessions"]==1
    assert metrics["annualized_geometric_return"]==pytest.approx((nav[-1]/3000.)**(252/len(nav))-1.)
    assert metrics["calendar_month_return"]["2026-01"]==pytest.approx(nav[-1]/3000.-1.)


@pytest.mark.parametrize("field,value", [("accounting_qualified",False),("certified_nav",np.nan),("actual_cash_flow_identity_error",1.)])
def test_account_failure_has_no_qualified_economic_report(descriptive_fixture,monkeypatch,field,value):
    _,bound,ref,_=descriptive_fixture;dates=pd.bdate_range("2026-01-02",periods=5)
    schedule=six.build_schedule(dates,as_of=bound["as_of"]);frames=metric_frames([3000.]*5)
    frames["daily"].loc[1,field]=value
    monkeypatch.setattr(six,"_execute_path",lambda *a:frames)
    monkeypatch.setattr(six,"descriptive_metrics",lambda *a:pytest.fail("unqualified economics"))
    reports=six.execute_schedule(schedule,policies(),authority_for_window=lambda w:ref(),
        inputs_for_window=lambda *a:synthetic_inputs(dates),record_event=lambda e:None,consume_result=lambda *a:None)
    assert all(r["status"]=="NOT_TESTABLE" and r["metrics"] is None for r in reports)


@pytest.mark.parametrize("kind,expected", [
    ("missing_evidence","FROZEN_HEAD_EVIDENCE_REQUIRED"),
    ("wrong_bundle","ACTUAL_FROZEN_BUNDLE_REQUIRED"),
    ("missing_session","EXPLICIT_SESSION_SUPPORT_REQUIRED"),
    ("missing_prediction","SUPPORTED_R6_OUTPUT_MISSING"),
    ("empty_supported_packets","SUPPORTED_ACTION_PACKET_MISSING"),
    ("changed_prediction_sid","R6_PREDICTION_IDENTITY_CHANGED"),
    ("changed_decoder","ORIGINAL_DECODER_OUTPUT_CHANGED"),
    ("empty_without_no_support","NO_SUPPORT_MUST_BE_EXPLICIT")])
def test_r6_missing_head_or_inference_never_silent_raw(descriptive_fixture,kind,expected):
    _,_,ref,_=descriptive_fixture
    admitted=authority.load_descriptive_authority(ref())
    inputs=synthetic_inputs(pd.bdate_range("2026-01-02",periods=5))["stocks"]
    cid=six.PATH_IDS[1]; evidence=inputs["inference_evidence"][cid]
    if kind=="missing_evidence":inputs["inference_evidence"].pop(cid)
    elif kind=="wrong_bundle":evidence["bundle"]={"loaded":True}
    elif kind=="missing_session":evidence["support"]=evidence["support"].iloc[:-1]
    elif kind=="missing_prediction":evidence["predictions"]=evidence["predictions"].iloc[:0]
    elif kind=="empty_supported_packets":inputs["action_packets"][cid]={}
    elif kind=="changed_prediction_sid":evidence["predictions"].loc[0,"security_id"]="WRONG_SID"
    elif kind=="changed_decoder":inputs["action_packets"][cid][admitted.start][0]["decision"]="BUY"
    elif kind=="empty_without_no_support":evidence["support"].loc[1,"status"]="INFERRED"
    with pytest.raises(ValueError,match=expected):
        six._inference_coverage(policies()[1],inputs,admitted)


def test_entire_replace_head_legally_empty_requires_actual_bundle_and_no_support(descriptive_fixture):
    _,_,ref,_=descriptive_fixture;admitted=authority.load_descriptive_authority(ref())
    inputs=synthetic_inputs(pd.bdate_range("2026-01-02",periods=5))["stocks"]
    got=six._inference_coverage(policies()[2],inputs,admitted)
    assert got["inferred_rows"]==0 and got["no_support_sessions"]==5
    inputs["inference_evidence"][six.PATH_IDS[2]]["support"].loc[0,"reason"]=""
    with pytest.raises(ValueError,match="NO_SUPPORT_MUST_BE_EXPLICIT"):
        six._inference_coverage(policies()[2],inputs,admitted)


@pytest.mark.parametrize("reason",["UNKNOWN_SID","OUTSIDE_ORIGINAL_PROXY_AGE"])
def test_original_unsupported_rows_can_have_explicit_empty_output(descriptive_fixture,reason):
    _,_,ref,_=descriptive_fixture;admitted=authority.load_descriptive_authority(ref())
    inputs=synthetic_inputs(pd.bdate_range("2026-01-02",periods=5))["stocks"]
    cid=six.PATH_IDS[1];evidence=inputs["inference_evidence"][cid]
    if reason=="UNKNOWN_SID":evidence["samples"].loc[0,"security_id"]=pd.NA
    else:evidence["samples"].loc[0,"cohort_age_sessions"]=21
    evidence["predictions"]=evidence["predictions"].iloc[:0]
    evidence["support"]["status"]="NO_SUPPORT";evidence["support"]["eligible_count"]=0
    evidence["support"]["reason"]=reason;inputs["action_packets"][cid]={}
    got=six._inference_coverage(policies()[1],inputs,admitted)
    assert got["inferred_rows"]==0 and got["no_support_sessions"]==5


@pytest.mark.parametrize("kind,expected", [
    ("missing_evidence","FROZEN_HEAD_EVIDENCE_REQUIRED"),
    ("missing_prediction","SUPPORTED_VALUE_OUTPUT_MISSING"),
    ("changed_mu","FROZEN_VALUE_PACKET_CHANGED"),
    ("wrong_year","FROZEN_VALUE_OUTPUT_REQUIRED")])
def test_ngboost_requires_actual_head_and_exact_qualified_packet(descriptive_fixture,kind,expected):
    _,_,ref,_=descriptive_fixture;admitted=authority.load_descriptive_authority(ref())
    inputs=synthetic_inputs(pd.bdate_range("2026-01-02",periods=5))["stocks"]
    cid=six.PATH_IDS[3];evidence=inputs["inference_evidence"][cid]
    if kind=="missing_evidence":inputs["inference_evidence"].pop(cid)
    elif kind=="missing_prediction":evidence["predictions"]=evidence["predictions"].iloc[1:]
    elif kind=="changed_mu":inputs["packets"]["ngboost"]["mu"][0,0]=.2
    elif kind=="wrong_year":evidence["predictions"]["year"]=2026
    with pytest.raises(ValueError,match=expected):
        six._inference_coverage(policies()[3],inputs,admitted)


@pytest.fixture
def durable_case(tmp_path, monkeypatch):
    """All authority/inputs/outputs here are synthetic; no model/account runs."""
    from scripts.storage import storage_r2a
    def safe(path, purpose):
        Path(path).resolve().relative_to(tmp_path.resolve())
        assert purpose == "backtest"
    for module in (six, six.execution_owner, six.replay, storage_r2a):
        monkeypatch.setattr(module, "assert_write_path", safe)
    schedule = six.build_schedule(pd.bdate_range("2026-01-02", periods=5),
                                  as_of="2026-01-08T22:00:00Z")
    run = tmp_path / authority.TASK / "SYNTHETIC_EXISTING_MANAGED_RUN"
    run.mkdir(parents=True)
    config = dict(strategy_id=authority.TASK, research_only=True,
                  broker_action_allowed=False, official_adoption_allowed=False)
    (run / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
    attempts = []
    def admit(w):
        return SimpleNamespace(task_id=authority.TASK, window_id=w["window_id"],
                               start=pd.Timestamp(w["start"]), end=pd.Timestamp(w["end"]))
    monkeypatch.setattr(authority, "load_descriptive_authority", lambda w:admit(w))
    def inputs(w, admitted):
        dates = pd.DatetimeIndex([w["start"],w["first_execution_date"],w["end"]]).unique()
        data = dict(market=SimpleNamespace(dates=dates, signal_mask=np.ones(len(dates),bool)))
        return dict(stocks=data, **{cid:data for cid in six.PATH_IDS[4:]})
    def execute(c, data, admitted):
        attempts.append((admitted.window_id,c["candidate_id"]))
        return dict(daily=pd.DataFrame(dict(date=data["market"].dates,
            path_id=c["candidate_id"], TOTAL_ECONOMIC_NAV=3000.)))
    monkeypatch.setattr(six, "_execute_path", execute)
    monkeypatch.setattr(six, "_qualification", lambda frames:dict(all_passed=True))
    monkeypatch.setattr(six, "descriptive_metrics", lambda *a:dict(cumulative_return=0.))
    kwargs = dict(authority_for_window=lambda w:w, inputs_for_window=inputs,
                  expected_run_config_sha256=six.sha256(run / "run_config.json"))
    return run, schedule, kwargs, attempts


def test_durable_results_resume_hashes_and_no_repeat(durable_case):
    run,schedule,kwargs,attempts=durable_case
    reports=six.execute_durable(run,schedule,policies(),**kwargs)
    assert len(reports)==6 and len(attempts)==6
    history=six.execution_owner.events(run,"ACCOUNT_PATH_LOG.jsonl")
    assert [e["event"] for e in history]==["ACCOUNT_PATH_ATTEMPT_STARTED","ACCOUNT_PATH_COMPLETE"]*6
    assert [e["attempt_ordinal"] for e in history[::2]]==list(range(1,7))
    assert all(Path(e["result_ref"]["path"]).exists() for e in history[1::2])
    assert not (run / "CONTINUATION_LOCK.json").exists()
    before=(run / "ACCOUNT_PATH_LOG.jsonl").read_bytes()
    again=six.execute_durable(run,schedule,policies(),**kwargs)
    assert again==reports and len(attempts)==6
    assert (run / "ACCOUNT_PATH_LOG.jsonl").read_bytes()==before
    done=json.loads((run / "SIX_PATH_COMPLETION.json").read_text(encoding="utf-8"))
    assert done["terminal_attempts"]==6 and done["scientific_retry"]==done["real_fit"]==0


def test_complete_audit_recovers_without_repeat_or_false_failed(durable_case,monkeypatch):
    run,schedule,kwargs,attempts=durable_case
    original=six.replay._append
    def fail_terminal(path,event):
        if event["event"]=="ACCOUNT_PATH_COMPLETE":raise OSError("SYNTHETIC_TERMINAL_IO")
        return original(path,event)
    monkeypatch.setattr(six.replay,"_append",fail_terminal)
    with pytest.raises(OSError,match="TERMINAL_IO"):
        six.execute_durable(run,schedule,policies(),**kwargs)
    assert len(attempts)==1
    history=six.execution_owner.events(run,"ACCOUNT_PATH_LOG.jsonl")
    assert [e["event"] for e in history]==["ACCOUNT_PATH_ATTEMPT_STARTED"]
    monkeypatch.setattr(six.replay,"_append",original)
    reports=six.execute_durable(run,schedule,policies(),**kwargs)
    assert len(attempts)==6 and all(r["status"]=="QUALIFIED_DESCRIPTIVE" for r in reports)


def test_interrupted_attempt_preserved_failed_and_never_replayed(durable_case,monkeypatch):
    run,schedule,kwargs,attempts=durable_case
    original=six._execute_path
    def interrupted(c,data,admitted):
        attempts.append((admitted.window_id,c["candidate_id"]))
        target=run / "ledgers/stateful/attempt_0001"
        target.mkdir(parents=True)
        (target / "partial.bin").write_bytes(b"SYNTHETIC_PARTIAL_EVIDENCE")
        raise KeyboardInterrupt("SYNTHETIC_PROCESS_INTERRUPTION")
    monkeypatch.setattr(six,"_execute_path",interrupted)
    with pytest.raises(KeyboardInterrupt):six.execute_durable(run,schedule,policies(),**kwargs)
    monkeypatch.setattr(six,"_execute_path",original)
    reports=six.execute_durable(run,schedule,policies(),**kwargs)
    assert len(attempts)==6 and attempts.count(("MAIN",six.PATH_IDS[0]))==1
    assert reports[0]["status"]=="FAILED_ENGINEERING"
    assert reports[0]["error_stage"]=="INTERRUPTED_ATTEMPT_NO_RETRY"
    assert reports[0]["metrics"] is None
    assert (run / "ledgers/stateful/attempt_0001/partial.bin").read_bytes()==b"SYNTHETIC_PARTIAL_EVIDENCE"


def test_storage_failure_is_engineering_and_other_paths_still_attempted(durable_case,monkeypatch):
    run,schedule,kwargs,attempts=durable_case
    original=pd.DataFrame.to_parquet
    calls=[]
    def fail_once(frame,*a,**kw):
        calls.append(1)
        if len(calls)==1:raise OSError("SYNTHETIC_OUTPUT_STORAGE_FAILURE")
        return original(frame,*a,**kw)
    monkeypatch.setattr(pd.DataFrame,"to_parquet",fail_once)
    reports=six.execute_durable(run,schedule,policies(),**kwargs)
    assert len(attempts)==6 and reports[0]["status"]=="FAILED_ENGINEERING"
    assert reports[0]["error_stage"]=="RESULT_STORAGE" and reports[0]["metrics"] is None
    assert [r["status"] for r in reports[1:]]==["QUALIFIED_DESCRIPTIVE"]*5
    assert "OUTPUT_STORAGE_FAILURE" in reports[0]["error"]


@pytest.mark.parametrize("change,expected", [
    ("config","RUN_CONFIG_PIN_CHANGED"),("binding","DURABLE_BINDING_CHANGED"),
    ("artifact","RESULT_ARTIFACT_CHANGED"),("duplicate","JOURNAL_ORDER_OR_DUPLICATE"),
    ("tail","INCOMPLETE_METADATA_APPEND_TAIL")])
def test_durable_resume_refuses_custody_drift_before_inputs(durable_case,change,expected):
    run,schedule,kwargs,attempts=durable_case
    six.execute_durable(run,schedule,policies(),**kwargs)
    journal=run / "ACCOUNT_PATH_LOG.jsonl"
    if change=="config":(run / "run_config.json").write_text("{}",encoding="utf-8")
    elif change=="binding":(run / "SIX_PATH_EXECUTION_BINDING.json").write_text("{}",encoding="utf-8")
    elif change=="artifact":(run / "ledgers/stateful/attempt_0001/daily.parquet").write_bytes(b"CHANGED_SYNTHETIC_ARTIFACT")
    elif change=="duplicate":journal.write_bytes(journal.read_bytes()+journal.read_bytes().splitlines(keepends=True)[0])
    else:journal.write_bytes(journal.read_bytes()+b'{"event":')
    with pytest.raises((ValueError,six.execution_owner.ExecutionBlocked),match=expected):
        six.execute_durable(run,schedule,policies(),**kwargs)
    assert len(attempts)==6


def test_existing_owner_lock_never_taken_over(durable_case):
    run,schedule,kwargs,attempts=durable_case
    lock=run / "CONTINUATION_LOCK.json";lock.write_text("{}",encoding="utf-8")
    with pytest.raises(six.execution_owner.ExecutionBlocked,match="OWNED_LOCK_ALREADY_EXISTS_NO_TAKEOVER"):
        six.execute_durable(run,schedule,policies(),**kwargs)
    assert lock.read_text(encoding="utf-8")=="{}" and not attempts


def test_full606_sequential_main_terminal_barrier_and_no_failed_retry(durable_case,monkeypatch):
    _,_,kwargs,attempts=durable_case
    schedule=six.build_schedule(pd.bdate_range("2026-01-02","2026-10-07"),
                                as_of="2026-10-08T09:00:00+09:00")
    events=[];original=six._execute_path
    def fail_first(c,data,admitted):
        if not attempts:
            attempts.append((admitted.window_id,c["candidate_id"]))
            raise RuntimeError("SYNTHETIC_MAIN_FAILURE")
        return original(c,data,admitted)
    monkeypatch.setattr(six,"_execute_path",fail_first)
    def inputs(w,a):
        if w["kind"]=="RANDOM":
            assert len([e for e in events if e["window_id"]=="MAIN" and e["event"] in ("COMPLETE","FAILED")])==6
        return kwargs["inputs_for_window"](w,a)
    reports=six.execute_schedule(schedule,policies(),authority_for_window=kwargs["authority_for_window"],
        inputs_for_window=inputs,record_event=events.append,consume_result=lambda *a:None)
    assert len(reports)==len(attempts)==606
    assert len(set(attempts))==606 and reports[0]["status"]=="FAILED_ENGINEERING"
    assert [e["candidate_id"] for e in events[:12:2]]==list(six.PATH_IDS)
    assert [e["event"] for e in events[:12]]==["STARTED","FAILED"]+["STARTED","COMPLETE"]*5


@pytest.fixture
def all_pool_descendant(tmp_path, monkeypatch):
    def save(name, value):
        p = tmp_path / name
        p.write_text(json.dumps(value), encoding='utf-8')
        return dict(path=str(p), sha256=six.hashlib.sha256(p.read_bytes()).hexdigest())
    dates = pd.bdate_range('2026-01-02', '2026-10-08')
    now = '2026-10-09T03:46:22+00:00'
    original = six.build_schedule(dates, as_of=now)
    root = dict(task_id=authority.ALL_POOL_ROOT_TASK, as_of=now, common_end='2026-10-08',
        common_sessions=list(dates.strftime('%Y-%m-%d')), windows=original['windows'])
    schedule_ref = save('root_schedule.json', root)
    monkeypatch.setattr(authority, 'ALL_POOL_SCHEDULE_SHA256', schedule_ref['sha256'])
    parent = dict(task_id=authority.AGGREGATE_TASK, candidates=list(six.PATH_IDS[:4]),
        benchmarks=list(six.PATH_IDS[4:]), account=dict(initial_cash_usd=3000),
        universe_change=dict(selection_rule='AGGREGATE_USD'), model_rule='FROZEN_ORIGINAL',
        test_interval=['2026-01-01','2027-01-01'], training_content_cutoff_exclusive='2026-01-01',
        earlier_cutoffs_retained=True, comparison=dict(benchmark_contract='ORIGINAL'))
    pref = save('parent.json', parent)
    monkeypatch.setattr(authority, 'AGGREGATE_PLAN_SHA256', pref['sha256'])
    cref = save('parent_candidates.json', dict(task_id=authority.AGGREGATE_TASK))
    rootref = save('root_plan.json', dict(task_id=authority.ALL_POOL_ROOT_TASK))
    scoperef = save('scope.json', dict(task_id=authority.ALL_POOL_ROOT_TASK, root_plan_ref=rootref,
        branches=[dict(original_task_id=authority.AGGREGATE_TASK)]))
    monkeypatch.setattr(authority, 'ALL_POOL_PLAN_SHA256', rootref['sha256'])
    monkeypatch.setattr(authority, 'ALL_POOL_SCOPE_SHA256', scoperef['sha256'])
    monkeypatch.setattr(authority, 'ALL_POOL_DESCENDANTS', {
        authority.ALL_AMOUNT_TASK: ('a'*64, authority.AGGREGATE_TASK, pref['sha256'], cref['sha256'])})
    child = deepcopy(parent)
    child.update(task_id=authority.ALL_AMOUNT_TASK, frozen_parent_plan_ref=pref,
        parent_contract_ref=pref, frozen_parent_candidate_manifest_ref=cref,
        root_plan_ref=rootref, scope_addendum_ref=scoperef, root_task_id=authority.ALL_POOL_ROOT_TASK,
        as_of_utc=now, evaluation_target_end='2026-10-08')
    child['comparison']['exact_window_source_ref'] = schedule_ref
    return dates, schedule_ref, root, child


def test_all_pool_descendant_exact_root_calendar_and_606(all_pool_descendant):
    dates, ref, root, child = all_pool_descendant
    authority._pool_descendant_plan(child, authority.ALL_AMOUNT_TASK)
    actual = six.build_schedule(dates, as_of=root['as_of'], task_id=authority.ALL_AMOUNT_TASK,
        inherited_schedule_ref=ref)
    assert actual['windows'] == root['windows']
    assert actual['account_paths'] == 606 and len(six._schedule_keys(actual)) == 606
    assert actual['path_ids'] == list(six.PATH_IDS)
    assert actual['parent_schedule_ref'] == ref


@pytest.mark.parametrize('field,value', [
    ('account', {'initial_cash_usd':1}), ('universe_change', {'selection_rule':'WRONG'}),
    ('model_rule','NEW_MODEL'), ('candidates',['UNREGISTERED'])])
def test_all_pool_descendant_cannot_change_parent_science(all_pool_descendant,field,value):
    _, _, _, child = all_pool_descendant
    child[field] = value
    with pytest.raises(ValueError, match='ORIGINAL_SCIENCE_CHANGED'):
        authority._pool_descendant_plan(child, authority.ALL_AMOUNT_TASK)


def test_all_pool_descendant_calendar_gap_and_window_tamper_rejected(all_pool_descendant):
    dates, ref, root, _ = all_pool_descendant
    with pytest.raises(ValueError, match='CALENDAR_CHANGED'):
        six.build_schedule(dates.delete(5), as_of=root['as_of'], task_id=authority.ALL_AMOUNT_TASK,
            inherited_schedule_ref=ref)
    actual = six.build_schedule(dates, as_of=root['as_of'], task_id=authority.ALL_AMOUNT_TASK,
        inherited_schedule_ref=ref)
    actual['windows'][1]['start'] = actual['windows'][0]['start']
    with pytest.raises(ValueError, match='FROZEN_SCHEDULE_CHANGED'):
        six._schedule_keys(actual)


def test_all_pool_descendant_wrong_scope_pin_rejected(all_pool_descendant):
    _, _, _, child = all_pool_descendant
    child['scope_addendum_ref'] = dict(child['scope_addendum_ref'],sha256='f'*64)
    with pytest.raises(ValueError,match='SCOPE_CHANGED'):
        authority._pool_descendant_plan(child, authority.ALL_AMOUNT_TASK)
