"""Meaningful checks on intervention, independent cash and immutable inputs."""
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT.parent / 'a2_pto_full_compat_20260928_r2'))
import numpy as np
import pandas as pd
import pytest
import integrity
import run_retest
from analyze_retest import pareto_flags
from fast_account import MarketArrays, run_many
from portfolio_policy import PortfolioPolicy
from shared import RISKS

class Cache(dict):
    @property
    def files(self):
        return list(self)

def test_full_roster_preserves_old_and_adds_only_a2(tmp_path, monkeypatch):
    monkeypatch.setattr(run_retest, 'ROOT', tmp_path)
    roster = run_retest.make_roster()
    original = pd.read_csv(run_retest.OLD / 'PREDECLARED_PATHS.csv')
    assert roster.iloc[:8194].reset_index(drop=True).equals(original)
    assert len(roster) == 8247
    extra = roster.iloc[8194:8246]
    assert len(extra) == 52 and extra.group.eq('a2_reference').all()
    assert extra.risk.nunique() == 13 and extra.optimizer.nunique() == 4
    assert roster.iloc[-1].layer == 'a2_raw_score_reference'
    assert roster.loc[roster.layer.eq('rl_control')].path_id.tolist() == original.loc[
        original.layer.eq('rl_control')].path_id.tolist()

def test_source_mutation_rejects_frozen_batch(tmp_path, monkeypatch):
    source = tmp_path / 'source.txt'
    source.write_bytes(b'original')
    monkeypatch.setattr(integrity, 'ROOT', tmp_path)
    marker = {'bindings': {str(source): integrity.sha(source)}}
    (tmp_path / 'FROZEN_BEFORE_2026.json').write_text(json.dumps(marker), encoding='utf-8')
    integrity.verify_freeze()
    source.write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='FROZEN_SOURCE_CHANGED'):
        integrity.verify_freeze()

def test_no_freeze_rejects_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(integrity, 'ROOT', tmp_path)
    with pytest.raises(RuntimeError, match='NEW_BATCH_FREEZE_REQUIRED'):
        integrity.verify_freeze()

def test_intercept_changes_fee_gate_without_forcing_cash_or_coupling_accounts():
    dates = pd.bdate_range('2025-06-02', periods=4)
    tickers = np.array(['A', 'B', 'C'])
    prices = np.full((4, 3), 100.)
    market = MarketArrays(dates, tickers, prices, prices.copy(), adv=np.full((4, 3), 1e9),
                          signal_mask=np.array([True, True, True, False]))
    roster = pd.DataFrame([{'path_id': 'corrected', 'group': 'ridge', 'fusion': 'identity',
                           'risk': 'diagonal', 'optimizer': 'positive_equal'},
                          {'path_id': 'control', 'group': 'huber', 'fusion': 'identity',
                           'risk': 'diagonal', 'optimizer': 'positive_equal'}])
    risk = Cache(scales=np.full((4, len(RISKS), 3), .02), corr_diagonal=np.eye(3),
                 scenario_diagonal=np.zeros((32, 3)))
    original_mu = np.zeros((4, 2, 3))
    original_mu[:, 0, :] = .0008
    original_mu[:, 1, :] = .002
    def replay(mu):
        forecast = {'mu': mu, 'stream_ids': np.array(['ridge__identity', 'huber__identity'])}
        return run_many(market, roster.path_id.tolist(), PortfolioPolicy(roster, forecast, risk))
    original = replay(original_mu)
    corrected_mu = original_mu.copy()
    corrected_mu[:, 0, :] += .00031727937244615677
    corrected = replay(corrected_mu)
    assert original.daily.loc[original.daily.path_id.eq('corrected'), 'gross_exposure'].eq(0).all()
    assert corrected.daily.loc[corrected.daily.path_id.eq('corrected'), 'gross_exposure'].max() > .29
    pd.testing.assert_frame_equal(original.daily.loc[original.daily.path_id.eq('control')].reset_index(drop=True),
                                  corrected.daily.loc[corrected.daily.path_id.eq('control')].reset_index(drop=True))
    negative_mu = original_mu.copy()
    negative_mu[:, 0, :] = -.01
    negative = replay(negative_mu)
    assert negative.daily.loc[negative.daily.path_id.eq('corrected'), 'gross_exposure'].eq(0).all()
    assert corrected.audit['next_open_violations'] == 0
    assert corrected.audit['capacity_violations'] == 0

def test_pareto_reports_return_drawdown_tradeoffs_in_separate_configuration_cells():
    frame = pd.DataFrame({'year': [2026]*4, 'risk': ['lw']*4,
                          'optimizer': ['mv', 'mv', 'mv', 'cvar'],
                          'indicative_return': [.20, .10, .05, -.2],
                          'indicative_max_drawdown': [-.15, -.05, -.10, -.8]})
    flags = pareto_flags(frame)
    assert flags.tolist() == [True, True, False, True]

def test_raw_a2_reference_is_score_rank_not_return_threshold_and_does_not_fill_missing_names():
    from raw_a2_reference import RawA2ScoreReferencePolicy
    dates = pd.bdate_range('2025-06-02', periods=3)
    prices = np.full((3, 2), 100.)
    market = MarketArrays(dates, ['A', 'B'], prices, prices.copy(), adv=np.full((3, 2), 1e9),
                          signal_mask=np.array([True, True, False]))
    score = np.tile([-.02, -.01], (3, 1))
    result = run_many(market, ['raw_reference'], RawA2ScoreReferencePolicy(score))
    assert result.daily.gross_exposure.max() > .09
    assert result.daily.gross_exposure.max() < .10
    assert result.orders.raw_model_weight.max() == .0475
    assert result.audit['next_open_violations'] == 0

def test_raw_a2_sell_only_holding_never_requests_recapitalization():
    from raw_a2_reference import RawA2ScoreReferencePolicy
    dates = pd.bdate_range('2025-06-02', periods=4)
    prices = np.array([[100., 100.], [10., 100.], [10., 100.], [10., 100.]])
    eligibility = np.array([[True, True], [False, True], [False, True], [False, True]])
    market = MarketArrays(dates, ['A', 'B'], prices, prices.copy(), adv=np.full((4, 2), 1e9),
                          new_buy_eligible=eligibility, signal_mask=np.array([True, True, True, False]))
    scores = np.tile([.02, .01], (4, 1))
    result = run_many(market, ['raw_reference'], RawA2ScoreReferencePolicy(scores))
    sell_only_orders = result.orders.loc[result.orders.ticker.eq('A') &
                                         result.orders.signal_date.gt(dates[0])]
    assert len(sell_only_orders)
    assert (sell_only_orders.raw_model_weight <= sell_only_orders.current_weight + 1e-12).all()
    assert result.audit['capacity_violations'] == 0
