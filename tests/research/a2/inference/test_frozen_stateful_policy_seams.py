"""Synthetic checks for the four opt-in frozen-policy seams.

The only files read are test/source fixtures and the task's hashed pre-change
source snapshots. No market files, fitted models, prediction packets, or real
account outputs are loaded.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast
import hashlib
import importlib.util
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest
from scripts.research.a2.training import stateful_account as policy
from scripts.research.a2.training import stateful_final_action as action
from scripts.research.a2.training import stateful_final_action_packets as decoder
from scripts.research.a2.training import stateful_decision as decision
from scripts.research.a2.training import stateful_replay as replay
from scripts.research.a2.evaluation import frozen_test_authority as authority_module
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision

ROOT = Path(__file__).resolve().parents[4]
_FIXTURE_PATH = ROOT / "tests/research/a2/evaluation/test_continuous_research_account.py"
_spec = importlib.util.spec_from_file_location("_synthetic_descriptive_fixture", _FIXTURE_PATH)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
descriptive_fixture = _fixtures.descriptive_fixture

BEFORE = Path("D:/us-tech-quant-cache/V24/V24_A_FROZEN_THREE_POLICY_2026_RANDOM_START_EVALUATION_R1/source_before")
BEFORE_SHA = {
    "stateful_account.py": "0778df268a7ef9ee0898b78b3ad0ca26e31fb54e8b5fca8292614ca894106ad3",
    "stateful_final_action.py": "09f26a390322c34f35dc5477bccef0d517016ee23a0ca2dcb4b0be77bbfd3453",
    "stateful_decision.py": "b953408439e101987811a87b57fd5755db659adebbf156038e21e893eee15739",
    "stateful_replay.py": "0012d349bbad0f4bfe4e9204357b4f4cfcab3fdf4a85a3a86036f2e55b1645fc",
}
NAMES = tuple(f"S{j:02d}" for j in range(21))


def _before(module, name, **globals_override):
    path = BEFORE / Path(module.__file__).name
    if not path.is_file():
        pytest.skip("Task-owned pre-change source snapshot is not installed")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BEFORE_SHA[path.name]
    tree = ast.parse(raw.decode("utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    namespace = dict(vars(module), **globals_override)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class _SyntheticReference:
    """Deterministic source-policy stand-in; no frozen external source reader."""
    def __init__(self, value, sigma, unused, vol_unused, vol, top, qualified, lineage):
        self.top, self.qualified = top, qualified
    def __call__(self, j, ctx):
        eligible = self.top[j] & self.qualified[j] & ctx.buy_allowed[0] & ctx.decision_mask[0]
        weights = eligible.astype(float)[None, :] / max(int(self.top[j].sum()), 1)
        weights *= min(float(ctx.available_budget[0]), 1.)
        return TargetDecision(weights, ctx.decision_mask.copy())


@pytest.fixture(autouse=True)
def no_external_reference_read(monkeypatch):
    monkeypatch.setattr(policy, "reference_policy_class", lambda: _SyntheticReference)


def _candidate(name="R6_BUY_TREE", **changes):
    c = dict(candidate_id=name, action="raw", value_model="ridge", control="none",
        gross="fixed", risk="diag20_reference", forecast="none", action_cost_mode="blind",
        execution_friction=_fixtures._descriptive_friction())
    c.update(changes)
    return c


def _arrays(sessions=1):
    top = np.ones((sessions, len(NAMES)), bool); top[:, -1] = False
    packets = dict(ridge=dict(mu=np.full(top.shape, .03), sigma=np.full(sessions, .001),
        lineage=np.full(sessions, "SYNTHETIC_ONLY")))
    return packets, top, np.ones_like(top), np.full(top.shape, .02)


def _context(date, path="R6_BUY_TREE", *, held=False):
    units=np.zeros((1, len(NAMES)))
    if held: units[0,-1]=30
    weights=units*10/3000
    return SimpleNamespace(signal_date=pd.Timestamp(date), signal_asof=pd.Timestamp(date),
        path_ids=(path,), tickers=np.array(NAMES), current_units=units, current_weights=weights,
        cash=np.array([3000-units.sum()*10]), nav=np.array([3000.]), available_budget=np.array([1.]),
        decision_mask=np.ones_like(units,bool),buy_allowed=np.ones_like(units,bool),
        max_positions=20,max_invested=1.,max_weight=1.,holding_age=np.full_like(units,7,int),
        entry_date=np.full(units.shape,np.datetime64("2024-01-02")),
        entry_price=np.full_like(units,10.),entry_execution_open=np.full_like(units,10.))


def _proposal(kind="REFERENCE", *, decision_name="SKIP"):
    return dict(kind=kind, decision=decision_name, ticker="S00", entrant=None,
        security_id="SID_S00", entrant_security_id=None, source_order=0, source_score=.2,
        sample_id="SYNTHETIC",local_resolver="R6")


def _overlay(cls, date, *, authority=None, name="R6_BUY_TREE", records=()):
    kwargs={} if authority is None else dict(descriptive_evaluation_authority=authority)
    if cls is action.FinalActionOverlay:
        kwargs.update(action_packets={name:{pd.Timestamp(date):list(records)}},
            resource_decoder=decoder.decode_resource_proposals,
            sid_by_key={(pd.Timestamp(date),n):"SID_"+n for n in NAMES})
    return cls([_candidate(name)], *_arrays(), **kwargs)


@pytest.mark.parametrize("cls",[policy.StatefulOverlay,action.FinalActionOverlay])
def test_default_2026_stays_locked(cls):
    with pytest.raises(ValueError,match="LOCKED_TEST|2026_LOCKED"):
        _overlay(cls,"2026-01-02")(0,_context("2026-01-02"))


@pytest.mark.parametrize("cls",[policy.StatefulOverlay,action.FinalActionOverlay])
def test_physical_synthetic_authority_allows_only_registered_frozen_policy(cls,descriptive_fixture):
    _, _, ref, _ = descriptive_fixture
    admitted=authority_module.load_descriptive_authority(ref())
    instance=_overlay(cls,"2026-01-02",authority=admitted,records=[_proposal()])
    result=instance(0,_context("2026-01-02"))
    assert isinstance(result,TargetDecision)
    assert np.isfinite(result.weights).all()
    if cls is action.FinalActionOverlay:
        assert result.weights[0,0] == 0
        assert result.weights[0,1:].sum() == pytest.approx(.95)


@pytest.mark.parametrize("cls",[policy.StatefulOverlay,action.FinalActionOverlay])
@pytest.mark.parametrize("date",["2025-12-31","2026-01-01","2026-01-09","2027-01-01"])
def test_authorized_policy_rejects_wrong_decision_date(cls,date,descriptive_fixture):
    _, _, ref, _ = descriptive_fixture
    admitted=authority_module.load_descriptive_authority(ref())
    with pytest.raises(ValueError,match="DESCRIPTIVE_DECISION_OUTSIDE_WINDOW"):
        _overlay(cls,date,authority=admitted)(0,_context(date))


@pytest.mark.parametrize("cls",[policy.StatefulOverlay,action.FinalActionOverlay])
def test_wrong_policy_identity_and_unvalidated_dict_rejected(cls,descriptive_fixture):
    _, _, ref, _ = descriptive_fixture
    admitted=authority_module.load_descriptive_authority(ref())
    with pytest.raises(ValueError,match="DESCRIPTIVE_POLICY_NOT_REGISTERED"):
        _overlay(cls,"2026-01-02",authority=admitted,name="UNREGISTERED")(
            0,_context("2026-01-02",path="UNREGISTERED"))
    with pytest.raises(ValueError,match="VALIDATED_DESCRIPTIVE_AUTHORITY_REQUIRED"):
        _overlay(cls,"2026-01-02",authority=ref())(0,_context("2026-01-02"))


@pytest.mark.parametrize("action_kind,cost,control",[
    ("raw","blind","none"),("stateful","aware","none"),
    ("stateful","aware","hysteresis"),("raw","blind","partial_rebalancing"),
    ("raw","blind","minimum_trade_usd"),("raw","blind","no_trade_band")])
def test_pre2026_stateful_outputs_equal_original_source(action_kind,cost,control):
    old=_before(policy,"StatefulOverlay")
    c=_candidate(action=action_kind,action_cost_mode=cost,control=control)
    current=policy.StatefulOverlay([c],*_arrays())
    original=old([c],*_arrays())
    ctx=_context("2025-01-03",held=True)
    left=current(0,ctx);right=original(0,deepcopy(ctx))
    np.testing.assert_array_equal(left.weights,right.weights)
    np.testing.assert_array_equal(left.explicit_mask,right.explicit_mask)
    assert current.audit == original.audit


@pytest.mark.parametrize("records",[[],[_proposal()]])
def test_pre2026_final_action_outputs_equal_original_source(records):
    old_policy=_before(policy,"StatefulOverlay")
    old=_before(action,"FinalActionOverlay",StatefulOverlay=old_policy)
    date=pd.Timestamp("2025-01-03")
    kwargs=dict(action_packets={"R6_BUY_TREE":{date:records}},
        resource_decoder=decoder.decode_resource_proposals,
        sid_by_key={(date,n):"SID_"+n for n in NAMES})
    current=action.FinalActionOverlay([_candidate()],*_arrays(),**kwargs)
    original=old([_candidate()],*_arrays(),**kwargs)
    left=current(0,_context(date));right=original(0,_context(date))
    np.testing.assert_array_equal(left.weights,right.weights)
    np.testing.assert_array_equal(left.explicit_mask,right.explicit_mask)
    assert current.action_audit == original.action_audit


def _panel(dates):
    dates=pd.DatetimeIndex(dates); rows=[]; labels=[]
    for di,date in enumerate(dates):
        for j,ticker in enumerate(NAMES):
            member=(j<20) if di==0 else (j>0)
            rank=float(j+1 if di==0 else j if j else 21)
            row=dict(signal_date=date,ticker=ticker,security_id="SID_"+ticker,
                feature_available=True,is_raw_top20=member,new_buy_eligible=member,
                raw_top20_set_complete=True,raw_top20_set_count=20,
                raw_a2_rank=rank,raw_a2_prediction=.2-rank*.001+di*.0001,
                raw_a2_oof_split="SYNTHETIC",raw_selector_input_present=True,
                is_max_group=True,stock_forecast_input_present=True)
            row.update({f:.01+j*.001+di*.0001 for f in decision.inputs.FEATURES})
            rows.append(row)
            labels.append(dict(signal_date=date,ticker=ticker,security_id="SID_"+ticker,
                feature_available=True,label_available=True,account_event_unhandled=False,
                label_unsupported_common_event=False,label_mature_date=date,y_open5=.02))
    return pd.DataFrame(rows),pd.DataFrame(labels),dates


def test_pre2026_samples_equal_original_function():
    old=_before(decision,"build_samples")
    args=_panel(pd.bdate_range("2024-01-02",periods=30))
    current,audit=decision.build_samples(*args);original,old_audit=old(*args)
    for key in current: assert_frame_equal(current[key],original[key])
    assert audit == old_audit


def test_2026_samples_are_inference_only_and_preserve_proxy_inputs(descriptive_fixture):
    _, _, ref, _ = descriptive_fixture
    admitted=authority_module.load_descriptive_authority(ref())
    pred,labels,calendar=_panel(["2026-01-02","2026-01-05","2026-01-06","2026-01-07","2026-01-08"])
    with pytest.raises(ValueError,match="2026_LOCKED"):
        decision.build_samples(pred,labels.iloc[:0],calendar)
    with pytest.raises(ValueError,match="FORBIDS_LABEL_ROWS"):
        decision.build_samples(pred,labels,calendar,descriptive_evaluation_authority=admitted)
    actual,_=decision.build_samples(pred,labels.iloc[:0],calendar,descriptive_evaluation_authority=admitted)
    old_pred=pred.copy();old_pred["signal_date"]-=pd.DateOffset(years=1)
    old_calendar=calendar-pd.DateOffset(years=1)
    old=_before(decision,"build_samples")
    expected,_=old(old_pred,labels.iloc[:0],old_calendar)
    for key,features in (("buy",decision.SINGLE),("replace",decision.PAIR)):
        assert not actual[key].empty
        assert_frame_equal(actual[key][list(features)],expected[key][list(features)])
        assert not actual[key].label_qualified.any()
        assert actual[key].target.isna().all()
    bad=pred.copy();bad.loc[0,"signal_date"]=pd.Timestamp("2026-01-09")
    with pytest.raises(ValueError,match="INPUT_OUTSIDE_WINDOW"):
        decision.build_samples(bad,labels.iloc[:0],calendar,descriptive_evaluation_authority=admitted)


def _replay_inputs(dates):
    dates=pd.DatetimeIndex(dates);packets,top,qualified,vol=_arrays(len(dates))
    price=np.full(top.shape,10.)
    data=MarketArrays(dates,NAMES,price.copy(),price.copy(),input_present=np.ones_like(top),
        new_buy_eligible=top.copy(),adv=np.full(top.shape,1e9))
    account=_fixtures.config()
    return data,packets,top,qualified,vol,account


def test_replay_omits_optional_keyword_for_legacy_factory_and_preserves_outputs(monkeypatch):
    original=_before(replay,"execute_market")
    data,packets,top,qualified,vol,cfg=_replay_inputs(pd.bdate_range("2025-01-02",periods=5))
    c=_candidate(name="RAW_s10")
    calls=[]
    def legacy_factory(candidates,packets,top,qualified,vol,risk_provider=None):
        calls.append(True)
        return policy.StatefulOverlay(candidates,packets,top,qualified,vol,risk_provider=risk_provider)
    kwargs=dict(stock_present=np.ones_like(top),raw_selector_present=np.ones_like(top),
        execution_friction=c["execution_friction"],policy_factory=legacy_factory)
    left,frames=replay.execute_market(data,[c],packets,top,qualified,vol,cfg,**kwargs)
    right,oldframes=original(data,[c],packets,top,qualified,vol,cfg,**kwargs)
    assert len(calls)==2
    assert left.prefix_identity==right.prefix_identity
    assert set(frames)==set(oldframes)
    for name in frames: assert_frame_equal(frames[name],oldframes[name])


def test_replay_passes_the_same_validated_authority_to_policy_and_account(descriptive_fixture,monkeypatch):
    _, _, ref, _ = descriptive_fixture
    admitted=authority_module.load_descriptive_authority(ref())
    data,packets,top,qualified,vol,cfg=_replay_inputs(
        ["2026-01-02","2026-01-05","2026-01-06","2026-01-07","2026-01-08"])
    c=_candidate(name="RAW_s10");seen={}
    common=replay.run_continuous_account
    def account(*args,**kwargs):
        seen["account"]=kwargs["descriptive_evaluation_authority"]
        return common(*args,**kwargs)
    def factory(*args,**kwargs):
        seen["policy"]=kwargs["descriptive_evaluation_authority"]
        return policy.StatefulOverlay(*args,**kwargs)
    monkeypatch.setattr(replay,"run_continuous_account",account)
    result,frames=replay.execute_market(data,[c],packets,top,qualified,vol,cfg,
        stock_present=np.ones_like(top),raw_selector_present=np.ones_like(top),
        execution_friction=c["execution_friction"],policy_factory=factory,
        descriptive_evaluation_authority=admitted)
    assert seen["account"] is admitted and seen["policy"] is admitted
    assert result.prefix_identity is None
    assert frames["continuation"].pending_orders_semantics.str.startswith("FRESH_START").all()
    for frame in frames.values():
        assert not frame.scenario.str.contains("PRE2026").any()
