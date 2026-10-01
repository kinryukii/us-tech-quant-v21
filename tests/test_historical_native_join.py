"""Native data may add 2026 coverage, never membership or prior-year scores."""
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.research.a2.inference import historical_top40 as runner
from scripts.research.a2.inference import historical_top40_prices as legacy
from scripts.research.a2.inference import current_native_prices as native


def fixture(monkeypatch):
    days = ['2025-12-31', '2026-01-02', '2026-01-05']
    pool = {
        'ledger': pd.DataFrame({'target_date': days, 'snapshot_id': ['old', 'old', 'new']}),
        'members': pd.DataFrame([
            {'snapshot_id': 'old', 'security_id': 'a', 'ticker': 'OLD', 'moomoo_symbol': 'US.OLD'},
            {'snapshot_id': 'new', 'security_id': 'b', 'ticker': 'NEW', 'moomoo_symbol': 'US.NEW'},
        ]),
    }
    original = pd.DataFrame([{'trade_date': pd.Timestamp(days[0]), 'ticker': 'OLD', 'f': 7.}])
    gaps = [{'ticker': 'NEW', 'reasons': ['ORIGINAL_RAW_ANCHOR_UNBOUND']}]
    monkeypatch.setattr(legacy, '_references', lambda _: {'source': {'path': 'bound', 'sha256': 'sha'}})
    monkeypatch.setattr(legacy, '_source', lambda _: SimpleNamespace(FEATURE_COLUMNS=['f']))
    monkeypatch.setattr(legacy, '_store', lambda _: object())
    extra = pd.DataFrame([{'trade_date': pd.Timestamp(day), 'ticker': 'NEW', 'f': 99.} for day in days[1:]])
    monkeypatch.setattr(native, 'build_native_2026_feature_candidates',
                        lambda *args, **kwargs: (extra, [{'ticker': 'NEW'}], []))
    return pool, original, gaps, days, extra


def test_native_prices_only_join_after_membership_and_preserve_original(monkeypatch):
    pool, original, gaps, days, _ = fixture(monkeypatch)
    result, lineage, missing = runner.extend_native_2026_prices(
        None, pool, original, [], gaps, days, {}, {}, days[0], days[-1])
    assert result[['ticker', 'f']].to_records(index=False).tolist() == [('OLD', 7.), ('NEW', 99.)]
    assert result.loc[result.ticker.eq('NEW'), 'trade_date'].tolist() == [pd.Timestamp('2026-01-05')]
    pd.testing.assert_frame_equal(result.iloc[:1].reset_index(drop=True), original)
    assert lineage == [{'ticker': 'NEW'}]
    assert missing == []


def test_native_builder_cannot_return_pre2026_features(monkeypatch):
    pool, original, gaps, days, extra = fixture(monkeypatch)
    extra.loc[0, 'trade_date'] = pd.Timestamp('2025-12-31')
    with pytest.raises(ValueError, match='NATIVE_HISTORICAL_CANDIDATE_IDENTITY_INVALID'):
        runner.extend_native_2026_prices(None, pool, original, [], gaps, days, {}, {}, days[0], days[-1])


def test_rejected_old_anchor_is_not_requalified_as_new_member(monkeypatch):
    pool, original, gaps, days, _ = fixture(monkeypatch)
    gaps[0]['reasons'] = ['EXPANDED_ANCHOR_PRICE_EQUIVALENCE_FAILED']
    monkeypatch.setattr(native, 'build_native_2026_feature_candidates',
                        lambda *a, **k: pytest.fail('must not bypass old proof'))
    result, _, missing = runner.extend_native_2026_prices(None, pool, original, [], gaps, days, {}, {}, days[0], days[-1])
    pd.testing.assert_frame_equal(result, original)
    assert missing == gaps


def test_native_partial_history_retains_explicit_prior_year_gap(monkeypatch):
    pool, original, gaps, days, _ = fixture(monkeypatch)
    pool['members'] = pd.concat([pool['members'], pd.DataFrame([
        {'snapshot_id': 'old', 'security_id': 'b', 'ticker': 'NEW', 'moomoo_symbol': 'US.NEW'}])], ignore_index=True)
    result, _, missing = runner.extend_native_2026_prices(None, pool, original, [], gaps, days, {}, {}, days[0], days[-1])
    assert missing[0]['missing_feature_dates'] == ['2025-12-31']
    assert result.loc[result.ticker.eq('NEW'), 'trade_date'].min().year == 2026
