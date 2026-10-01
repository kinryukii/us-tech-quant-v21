"""Synthetic state, execution feedback and bounded RL validation only."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.inference import joint_stateful_policy as action
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision, AccountContext


def account():
    return dict(base_currency="USD",fractional_shares=True,integer_share_rounding=False,
                cash_interest=0,transaction_cost_bps=0,financing=False,borrowed_cash=False,
                long_only=True,initial_nav=3000,initial_cash=3000,initial_holdings=[],
                max_weight=.1,max_positions=20,max_invested=1,capacity_fraction=.01)


def fixture(names=25, days=38, first="2023-01-03"):
    dates = pd.bdate_range(first,periods=days)
    ticker = np.array([f"T{i:03d}" for i in range(names)])
    t = np.arange(days)[:,None]
    opening = 100*(1+.003*np.sin(t+np.arange(names)))*(1+.001*(np.arange(names)%3)*t)
    close = opening*(1+.001*np.cos(t))
    features = np.zeros((days,names,32),np.float32)
    features[:,:,0] = np.sin(t+np.arange(names))
    features[:,:,31] = np.log1p(1e6)
    mu = .005+.005*np.cos(t+np.arange(names))
    uncertainty = np.full((days,names),.01)
    market = MarketArrays(dates,ticker,opening,close,adv=np.full((days,names),1e6),
                          signal_mask=np.r_[np.ones(days-2,bool),False,False])
    return market,features,mu,uncertainty


def initial_bundle():
    torch = pytest.importorskip("torch")
    torch.manual_seed(action.SPEC["seed"])
    actor = action.SequentialActor()
    return dict(actor_state={k:v.detach().clone() for k,v in actor.state_dict().items()},
                mean=np.zeros(32),scale=np.ones(32),capital=3000)


@pytest.mark.parametrize("method",["reinforce","ppo"])
def test_real_updates_complete_date_rollout_and_identical_zero_initialization(method):
    torch = pytest.importorskip("torch")
    torch.set_num_threads(2)
    m,x,mu,sigma = fixture(names=6)
    fitted = action.train_sequential(method,m,x,mu,sigma,account(),cutoff="2024-01-01")
    assert fitted["status"] == "FIT_COMPLETE"
    assert fitted["actor_parameter_delta_l2"] > 0
    assert fitted["actual_parameter_updates"] >= 4
    assert fitted["normalization_rows"] == len(m.dates)*len(m.tickers)
    assert all(log["trajectory_signal_steps"] == len(m.dates)-2 for log in fitted["logs"])
    assert all(log["legal_reward_steps"] == len(m.dates)-2 for log in fitted["logs"])
    p = action._primitives()
    zero_actor = action.SequentialActor()
    zero_actor.load_state_dict(fitted["zero_bundle"]["actor_state"])
    assert p["state_digest"](zero_actor) == fitted["initial_actor_sha256"]
    assert fitted["final_actor_sha256"] != fitted["initial_actor_sha256"]
    assert all(a.reward_end_date.max() < pd.Timestamp("2024-01-01") for a in fitted["reward_audits"])
    trained = action.SequentialPolicy(fitted["trained_bundle"],x,mu,sigma,capture=True)
    replay = run_continuous_account(m,["trained"],trained,account())
    assert replay.daily.actual_name_count.max() <= 20
    assert replay.daily.cash.min() >= -1e-7
    assert np.count_nonzero(trained.experiences[1]["current_units"]) > 0
    assert trained.experiences[1]["decision_cash"] < 3000
    assert np.nanmax(trained.experiences[2]["holding_age"]) >= 1
    assert np.isfinite(trained.experiences[2]["entry_execution_open"]).any()


def test_full_candidate_inputs_q_gross_and_future_open_invariance():
    m,x,mu,sigma = fixture(names=85,days=6)
    bundle = initial_bundle()
    observations = []
    def run(market):
        policy = action.SequentialPolicy(bundle,x,mu,sigma,capture=True)
        run_continuous_account(market,["frozen"],policy,account())
        observations.append(policy.experiences)
    run(m)
    changed = MarketArrays(m.dates,m.tickers,m.open.copy(),m.close.copy(),adv=m.adv,signal_mask=m.signal_mask)
    changed.open[1] *= 2
    run(changed)
    first = observations[0][0]
    assert len(first["modeled_tickers"]) == 85
    assert np.count_nonzero(first["q"]) <= 20
    assert first["q"].sum() == pytest.approx(1)
    assert 0 <= first["gross_target"] <= 1
    np.testing.assert_array_equal(first["q"],observations[1][0]["q"])
    np.testing.assert_array_equal(first["observations"],observations[1][0]["observations"])


def test_signal_state_does_not_add_out_of_pool_or_erase_missing_input_holding():
    m,x,mu,sigma = fixture(names=2,days=7)
    m.new_buy_eligible[:,1] = False
    m.input_present[1] = False
    policy = action.SequentialPolicy(initial_bundle(),x,mu,sigma,capture=True)
    replay = run_continuous_account(m,["frozen"],policy,account())
    assert not replay.fills.ticker.eq(m.tickers[1]).any()
    a = replay.positions.loc[replay.positions.date.eq(m.dates[1])].index_units.to_numpy()
    b = replay.positions.loc[replay.positions.date.eq(m.dates[2])].index_units.to_numpy()
    np.testing.assert_array_equal(a,b)


def test_unqualified_reward_is_masked_and_cannot_bridge_credit():
    m,x,mu,sigma = fixture(names=4,days=15)
    x[:] = 0
    mu[:] = .01
    fitted = action.train_sequential("reinforce",m,x,mu,sigma,account(),cutoff="2024-01-01",
        replay_kwargs={"unsupported_events":[dict(ticker="T000",effective_date=str(m.dates[5].date()),reason="SYNTHETIC_UNKNOWN_CASH_EVENT")]})
    assert fitted["status"] == "FIT_COMPLETE"
    masks = fitted["reward_audits"][0]
    assert (~masks.valid_learning_reward).any()
    assert masks.loc[~masks.valid_learning_reward].log_net_reward.eq(0).all()
    assert masks.loc[~masks.valid_learning_reward].mask_reason.str.contains("UNQUALIFIED").any()
    np.testing.assert_allclose(action._returns([.1,.2,.3],[True,False,True]),[.1,0,.3])


def test_all_unobservable_episode_is_blocked_reward_and_preserves_zero_bundle():
    m,x,mu,sigma = fixture(names=2,days=7)
    m.open[:] = np.nan
    m.close[:] = np.nan
    fitted = action.train_sequential("ppo",m,x,mu,sigma,account(),cutoff="2024-01-01")
    assert fitted["status"] == "BLOCKED_REWARD"
    assert fitted["actual_parameter_updates"] == 0
    assert "zero_bundle" in fitted


def test_training_boundary_and_update_budget_are_enforced():
    m,x,mu,sigma = fixture(names=6,days=38)
    fitted = action.train_sequential("ppo",m,x,mu,sigma,account(),cutoff="2024-01-01",max_optimizer_updates=1)
    assert fitted["status"] == "BLOCKED_UPDATE_BUDGET"
    assert fitted["actual_parameter_updates"] == 1
    future = fixture(first="2026-01-02")
    with pytest.raises(ValueError,match="TRAINING_BOUNDARY"):
        action.train_sequential("ppo",*future,account(),cutoff="2027-01-01")
    with pytest.raises(ValueError,match="SEARCH_BUDGET"):
        action.train_sequential("ppo",m,x,mu,sigma,account(),cutoff="2024-01-01",seed=42)


def test_rule_action_reserves_close_call_before_joint_risk_and_marks_explicit_exit():
    n=3
    current=np.array([[.05,0,0.]])
    seen=[]
    class Base:
        mu=np.array([[[.099,.1,.08]]])
        uncertainty=np.full((1,1,n),.01)
        def __call__(self,day,ctx):
            seen.append(ctx)
            target=np.zeros((1,n))
            target[0,1]=.05
            return TargetDecision(target,ctx.decision_mask)
    ctx=AccountContext(0,pd.Timestamp("2024-01-02"),pd.Timestamp("2024-01-02"),
        ("rule",),np.array(["HELD","NEW","LOW"]),np.array([[1.,0,0]]),current,
        np.array([2850.]),np.array([.95]),np.array([3000.]),np.zeros((1,n),bool),
        np.array([0.]),np.array([0]),np.array([1.]),np.array([2]),
        np.ones((1,n),bool),np.zeros((1,n),bool),np.ones((1,n),bool),
        np.ones((1,n),bool),np.zeros((1,n),bool),2,.1,1)
    rows=[]
    policy=action.RuleStatefulPolicy(Base(),on_diagnostics=rows.append)
    decision=policy(0,ctx)
    assert seen[0].reserved_mask[0,0]
    assert seen[0].available_slots[0] == 1
    assert not decision.explicit_mask[0,0]
    assert rows[0].loc[rows[0].ticker.eq("HELD"),"action"].iloc[0] == "HOLD"

def test_training_initial_floor_projection_allows_only_authorized_2021_history():
    m,x,mu,sigma=fixture(names=6,days=12,first="2021-01-04")
    fitted=action.train_sequential("reinforce",m,x,mu,sigma,account(),cutoff="2023-01-01")
    assert fitted["status"]=="FIT_COMPLETE"
    assert fitted["training_projection"]["source_sha256"].startswith("99038f")
    assert fitted["normalization_signal_max"]<"2023-01-01"
    assert all(a.reward_end_date.max()<pd.Timestamp("2023-01-01") for a in fitted["reward_audits"])
    with pytest.raises(ValueError,match="first legal 2023"):
        run_continuous_account(m,["ordinary"],action.SequentialPolicy(fitted["trained_bundle"],x,mu,sigma),account())

