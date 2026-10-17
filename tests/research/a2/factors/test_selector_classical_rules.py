"""C11 validation is synthetic only: no fit, outcomes, reader or risk estimation."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.factors import selector_classical_rules as rules


@pytest.fixture
def rows():
    n = 48
    ranks = np.arange(1, n + 1)
    frame = pd.DataFrame(dict(signal_date=pd.Timestamp("2024-04-03"),
                              security_uid=[f"SEC:{i:06d}" for i in ranks],
                              raw_score=(n + 1 - ranks) / 100., raw_rank=ranks))
    for j, name in enumerate(rules.TREND_COLUMNS):
        frame[name] = ((ranks * (j + 3)) % 17) / 100.
    frame["realized_vol_20d"] = (ranks % 9 + 1) / 100.
    frame["downside_vol_20d"] = (ranks % 7 + 1) / 200.
    frame["max_drawdown_60d"] = -(ranks % 11) / 100.
    frame["avg_dollar_volume_20d"] = (ranks % 13 + 1) * 1e6
    return frame


def aligned(frame):
    return frame.sort_values(["signal_date", "security_uid"]).reset_index(drop=True)


def rank_pct(series):
    return series.rank(method="average", pct=True).to_numpy()


def test_coordinates_all_declared_columns_and_average_ties(rows):
    got = rules.coordinates(rows)
    np.testing.assert_allclose(got.ALPHA, rank_pct(rows.raw_score))
    np.testing.assert_allclose(got.TREND, np.mean([rank_pct(rows[c]) for c in rules.TREND_COLUMNS], axis=0))
    np.testing.assert_allclose(got.VOL_RISK, rank_pct(rows.realized_vol_20d))
    np.testing.assert_allclose(got.DOWNSIDE_RISK, rank_pct(rows.downside_vol_20d))
    np.testing.assert_allclose(got.DD_RISK, rank_pct(-rows.max_drawdown_60d))
    np.testing.assert_allclose(got.ILLIQ_RISK, 1 - rank_pct(rows.avg_dollar_volume_20d))
    tied = got.loc[rows.realized_vol_20d == rows.realized_vol_20d.iloc[0], "VOL_RISK"]
    assert tied.nunique() == 1
    assert len(rules.TREND_COLUMNS) == 9


def test_negative_drawdown_is_positive_risk_magnitude(rows):
    rows["max_drawdown_60d"] = -np.arange(len(rows)) / 100.
    got = rules.coordinates(rows)
    assert got.DD_RISK.is_monotonic_increasing
    assert got.DD_RISK.iloc[0] < got.DD_RISK.iloc[-1]
    assert "<=0" in rules.DD_SEMANTICS


def test_seven_fixed_formulas_and_full_universe(rows):
    coords = aligned(rules.coordinates(rows))
    risk3 = coords[["VOL_RISK", "DOWNSIDE_RISK", "DD_RISK"]].mean(axis=1)
    risk4 = coords[["VOL_RISK", "DOWNSIDE_RISK", "DD_RISK", "ILLIQ_RISK"]].mean(axis=1)
    expected = (coords.ALPHA-coords.VOL_RISK, coords.ALPHA-coords.DOWNSIDE_RISK,
                coords.ALPHA-coords.DD_RISK, coords.ALPHA-risk3, coords.ALPHA-risk4,
                coords.TREND-risk3, coords.TREND-risk4)
    panels = rules.base_rules(rows)
    assert tuple(panels) == (*rules.BASE_ROLES, *rules.SANITY_ROLES)
    for cid, score in zip(rules.BASE_ROLES[:7], expected):
        np.testing.assert_allclose(panels[cid].score, score)
    for cid, panel in panels.items():
        assert set(panel.security_uid) == set(rows.security_uid)
        assert len(panel) == len(rows)
        assert sorted(panel["rank"]) == list(range(1, len(rows) + 1))
        assert np.isfinite(panel[["score", "rank", *rules.COORDINATES]]).all().all()
        assert panel.candidate_id.eq(cid).all()
        assert panel.attrs["fits"] == panel.attrs["covariance_estimations"] == 0
        assert panel.attrs["production_promotion_allowed"] is False
        assert panel.attrs["diagnostic_only"] == (cid in rules.SANITY_ROLES)
        assert panel.attrs["mechanism_support_eligible"] == (cid in rules.BASE_ROLES)


def test_raw_sanity_is_exact_with_frozen_score_ties(rows):
    rows["raw_score"] = np.repeat(np.arange(24, 0, -1), 2) / 100.
    raw = rules.base_rules(rows)[rules.SANITY_ROLES[1]]
    np.testing.assert_array_equal(raw["rank"], raw.raw_rank)
    np.testing.assert_array_equal(raw.score, aligned(rows).raw_score)


def test_equal_score_tie_uses_raw_rank_not_input_or_uid_order(rows):
    rows["security_uid"] = rows.security_uid.iloc[::-1].to_numpy()
    rows["raw_score"] = 1.
    for name in (*rules.TREND_COLUMNS, *rules.RISK_COLUMNS):
        rows[name] = 0. if name == "max_drawdown_60d" else 1.
    for panel in rules.base_rules(rows.sample(frac=1., random_state=13)).values():
        np.testing.assert_array_equal(panel["rank"], panel.raw_rank)
        assert panel.attrs["tie_policy"] == rules.TIE_POLICY


def test_pareto_fronts_dominance_equal_and_incomparable():
    got = rules.pareto_fronts([[3, 3], [3, 3], [2, 2], [3, 1], [1, 3], [1, 1]])
    np.testing.assert_array_equal(got, [1, 1, 2, 2, 2, 3])
    np.testing.assert_array_equal(rules.pareto_fronts([[2, 1], [1, 2]]), [1, 1])


def test_a8_uses_alpha_maximize_four_risks_minimize(rows):
    panels = rules.base_rules(rows)
    panel = panels[rules.BASE_ROLES[7]]
    good = panel[["ALPHA", "VOL_RISK", "DOWNSIDE_RISK", "DD_RISK", "ILLIQ_RISK"]].to_numpy().copy()
    good[:, 1:] *= -1
    np.testing.assert_array_equal(panel.pareto_front, rules.pareto_fronts(good))
    np.testing.assert_array_equal(panel.score, -panel.pareto_front)
    for _, front in panel.groupby("pareto_front"):
        assert front.sort_values("rank").raw_rank.is_monotonic_increasing


def test_min_vol_is_top40_only_and_diagnostic(rows):
    rows["realized_vol_20d"] = rows.raw_rank / 100.
    rows.loc[rows.raw_rank.gt(40), "realized_vol_20d"] = 0.
    panel = rules.base_rules(rows)[rules.SANITY_ROLES[0]]
    chosen = panel.loc[panel["rank"].le(20)].sort_values("rank")
    np.testing.assert_array_equal(chosen.raw_rank, np.arange(1, 21))
    assert panel.loc[panel.raw_rank.gt(40), "rank"].gt(40).all()
    assert panel.attrs["diagnostic_only"]
    assert not panel.attrs["mechanism_support_eligible"]


def test_base_permutation_date_isolation_and_irrelevant_labels(rows):
    original = rules.base_rules(rows)
    extra = rows.copy()
    extra["signal_date"] = pd.Timestamp("2025-05-05")
    extra["raw_score"] *= 2
    extra["realized_vol_20d"] *= 7
    combined = pd.concat([extra, rows], ignore_index=True).sample(frac=1., random_state=42)
    combined["synthetic_unused_outcome"] = np.arange(len(combined)) * 999.
    appended = rules.base_rules(combined)
    for cid in original:
        got = appended[cid].loc[appended[cid].signal_date.eq(rows.signal_date.iloc[0])]
        pd.testing.assert_frame_equal(got.drop(columns="synthetic_unused_outcome").reset_index(drop=True),
                                      original[cid], check_flags=False)
        pd.testing.assert_frame_equal(rules.base_rules(rows.sample(frac=1., random_state=3))[cid],
                                      original[cid], check_flags=False)


@pytest.mark.parametrize("problem,match", [
    ("missing", "REQUIRED_COLUMNS"), ("nan", "FINITE_INPUT"), ("inf", "FINITE_INPUT"),
    ("positive_dd", "NONPOSITIVE"), ("negative_vol", "NONNEGATIVE"),
    ("negative_liquidity", "NONNEGATIVE"), ("missing_uid", "SECURITY_UID"),
    ("blank_uid", "SECURITY_UID"), ("numeric_uid", "SECURITY_UID"),
    ("duplicate_uid", "DUPLICATE"), ("bad_rank", "ORDINAL"),
    ("bad_score_binding", "RANK_BINDING"), ("future", "PRE2026"),
    ("missing_date", "PRE2026"), ("too_small", "TOP40"),
])
def test_input_failure_closed_without_row_drop(rows, problem, match):
    if problem == "missing": rows = rows.drop(columns=rules.TREND_COLUMNS[0])
    elif problem == "nan": rows.loc[0, rules.TREND_COLUMNS[0]] = np.nan
    elif problem == "inf": rows.loc[0, "raw_score"] = np.inf
    elif problem == "positive_dd": rows.loc[0, "max_drawdown_60d"] = .01
    elif problem == "negative_vol": rows.loc[0, "downside_vol_20d"] = -.01
    elif problem == "negative_liquidity": rows.loc[0, "avg_dollar_volume_20d"] = -1.
    elif problem == "missing_uid": rows.loc[0, "security_uid"] = None
    elif problem == "blank_uid": rows.loc[0, "security_uid"] = "  "
    elif problem == "numeric_uid":
        rows["security_uid"] = rows.security_uid.astype(object)
        rows.loc[0, "security_uid"] = 123
    elif problem == "duplicate_uid": rows.loc[0, "security_uid"] = rows.loc[1, "security_uid"]
    elif problem == "bad_rank": rows.loc[0, "raw_rank"] = 2
    elif problem == "bad_score_binding": rows.loc[47, "raw_score"] = 99
    elif problem == "future": rows.loc[0, "signal_date"] = pd.Timestamp("2026-01-01")
    elif problem == "missing_date": rows.loc[0, "signal_date"] = pd.NaT
    elif problem == "too_small": rows = rows.iloc[:39]
    with pytest.raises(ValueError, match=match):
        rules.base_rules(rows)


def test_future_append_rejected_without_returning_partial_panels(rows):
    future = rows.copy()
    future["signal_date"] = pd.Timestamp("2026-01-02")
    with pytest.raises(ValueError, match="PRE2026"):
        rules.base_rules(pd.concat([rows, future], ignore_index=True))


def test_greedy_identity_keeps_ten_unique_twenty_and_signed_delta(rows):
    panel = rules.risk_boundary_greedy(rows, np.eye(len(rows)), list(rows.security_uid))
    np.testing.assert_array_equal(panel.sort_values("rank").raw_rank.iloc[:20], np.arange(1, 21))
    assert len(panel) == len(rows) and panel.security_uid.nunique() == len(rows)
    assert len(panel.attrs["greedy_trace"]) == 10
    assert [len(t["candidates"]) for t in panel.attrs["greedy_trace"]] == list(range(30, 20, -1))
    assert all(c["marginal_std_delta"] < 0 for t in panel.attrs["greedy_trace"] for c in t["candidates"])
    assert panel.attrs["portfolio_std_selected"] == pytest.approx(np.sqrt(1/20))
    assert panel.attrs["fits"] == panel.attrs["covariance_estimations"] == 0


def test_greedy_lower_risk_boundary_but_fixed_raw_ten(rows):
    variances = np.ones(len(rows))
    variances[:10] = 1000.
    variances[10:20] = 10000.
    panel = rules.risk_boundary_greedy(rows, np.diag(variances), list(rows.security_uid))
    chosen = panel.loc[panel["rank"].le(20)].raw_rank.tolist()
    assert set(range(1, 11)).issubset(chosen)
    assert len(set(chosen)) == 20
    assert set(range(21, 31)).issubset(chosen)
    assert set(panel.security_uid) == set(rows.security_uid)
    assert panel.attrs["portfolio_std_selected"] < panel.attrs["portfolio_std_raw_top20"]


def test_greedy_covariance_uid_and_input_permutation_invariance(rows):
    matrix = np.diag(np.arange(1, len(rows) + 1, dtype=float))
    expected = rules.risk_boundary_greedy(rows, matrix, list(rows.security_uid))
    order = np.arange(len(rows))[::-1]
    shuffled = rows.sample(frac=1., random_state=7)
    got = rules.risk_boundary_greedy(shuffled, matrix[np.ix_(order, order)], list(rows.security_uid.iloc[order]))
    pd.testing.assert_frame_equal(got, expected, check_flags=False)
    assert got.attrs["greedy_trace"] == expected.attrs["greedy_trace"]
    assert got.attrs["portfolio_std_selected"] == expected.attrs["portfolio_std_selected"]


@pytest.mark.parametrize("problem,match", [
    ("non_psd", "PSD"), ("asymmetric", "SYMMETRIC"), ("nan", "FINITE_FULL"),
    ("shape", "FINITE_FULL"), ("missing_uid", "FULL_U_COVARIANCE_UIDS"),
    ("duplicate_uid", "FULL_U_COVARIANCE_UIDS"), ("blank_uid", "COVARIANCE_UID"),
    ("foreign_uid", "FULL_U_COVARIANCE_UIDS"), ("two_dates", "SINGLE_DECISION"),
    ("unknown_role", "FROZEN_RISK_ROLE"),
])
def test_covariance_fail_closed_without_padding_or_repair(rows, problem, match):
    matrix, uids = np.eye(len(rows)), list(rows.security_uid)
    cid = "C11_B_DIAG"
    if problem == "non_psd": matrix[0, 0] = -1.
    elif problem == "asymmetric": matrix[0, 1] = .1
    elif problem == "nan": matrix[0, 0] = np.nan
    elif problem == "shape": matrix = matrix[:-1, :-1]
    elif problem == "missing_uid": uids = uids[:-1]
    elif problem == "duplicate_uid": uids[0] = uids[1]
    elif problem == "blank_uid": uids[0] = ""
    elif problem == "foreign_uid": uids[0] = "SEC:UNKNOWN"
    elif problem == "two_dates":
        extra = rows.copy()
        extra["signal_date"] = pd.Timestamp("2025-05-05")
        rows = pd.concat([rows, extra], ignore_index=True)
    elif problem == "unknown_role": cid = "C11_B_NEW_FAMILY"
    with pytest.raises(ValueError, match=match):
        rules.risk_boundary_greedy(rows, matrix, uids, candidate_id=cid)

