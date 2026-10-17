"""C12 synthetic-only geometry/matching proofs; no label data or fitting."""
from itertools import product
from fractions import Fraction
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.factors import selector_boundary_pairs as boundary

BASE = boundary.BASE32


@pytest.fixture
def raw():
    rank = np.arange(1, 49)
    frame = pd.DataFrame({"signal_date": pd.Timestamp("2024-04-03"),
                          "security_uid": [f"UID:{i:04d}" for i in rank],
                          "raw_rank": rank, "raw_score": (49-rank)/100.})
    for i, name in enumerate(BASE): frame[name] = rank*(i+1)/100.
    return frame


def weights_for(pairs, edges):
    return np.array([edges.get((int(r.incumbent_raw_rank), int(r.challenger_raw_rank)), 0.)
                     for r in pairs.itertuples()], dtype=float)


def members(panel):
    return set(panel.loc[panel["rank"].le(20), "security_uid"])


def test_geometry_exact_200_and_canonical_hash_permutation(raw):
    pairs = boundary.geometry(raw)
    assert len(pairs) == 200
    assert set(pairs.challenger_raw_rank) == set(range(21, 41))
    assert set(pairs.incumbent_raw_rank) == set(range(11, 21))
    assert pairs.groupby("challenger_uid").size().eq(10).all()
    assert pairs.groupby("incumbent_uid").size().eq(20).all()
    changed = raw.sample(frac=1., random_state=5)
    changed["synthetic_irrelevant_y"] = np.arange(len(raw)) * -99
    changed["raw_score"] *= 7
    other = boundary.geometry(changed)
    pd.testing.assert_frame_equal(other, pairs)
    assert pairs.attrs["pair_key_sha256"] == boundary.pair_key_sha256(pairs.sample(frac=1., random_state=4))
    assert pairs.attrs["target_values_read"] == 0
    assert pairs.attrs["caller_must_freeze_before_labels"]


def test_geometry_date_isolation_and_sha_identity_binding(raw):
    extra = raw.copy()
    extra["signal_date"] = pd.Timestamp("2025-04-03")
    extra["security_uid"] = "NEW:" + extra.security_uid
    original = boundary.geometry(raw)
    all_pairs = boundary.geometry(pd.concat([extra, raw], ignore_index=True))
    assert len(all_pairs) == 400
    past = all_pairs.loc[all_pairs.signal_date.eq(raw.signal_date.iloc[0])]
    assert boundary.pair_key_sha256(past) == boundary.pair_key_sha256(original)
    changed = raw.copy()
    changed.loc[20, "security_uid"] = "UID:IDENTITY_RESET"
    assert boundary.geometry(changed).attrs["pair_key_sha256"] != original.attrs["pair_key_sha256"]


def test_fixed_date_challenger_partner_weights_and_no_missing_pair_substitute(raw):
    pairs = boundary.geometry(raw)
    weights = boundary.pair_weights(pairs)
    assert weights.sum() == pytest.approx(1.)
    np.testing.assert_allclose(weights, .005)
    weighted = pairs.assign(weight=weights)
    np.testing.assert_allclose(weighted.groupby("challenger_uid").weight.sum(), .05)
    with pytest.raises(ValueError, match="EXACT_200"):
        boundary.pair_weights(pairs.iloc[:-1])


def test_history_previous_session_same_uid_with_zero_two_flags(raw):
    calendar = pd.DatetimeIndex(["2024-04-03", "2024-04-04", "2024-04-05"])
    days = []
    for j, date in enumerate(calendar):
        day = raw.copy()
        day["signal_date"] = date
        day["raw_score"] += j*.1
        if j == 1: day.loc[0, "security_uid"] = "UID:NEW_IDENTITY"
        days.append(day)
    got = boundary.add_history(pd.concat(days, ignore_index=True), calendar)
    first = got.loc[got.signal_date.eq(calendar[0])]
    assert first.raw_rank_change.eq(0).all() and first.raw_score_change.eq(0).all()
    assert first.raw_rank_change_missing.eq(1).all() and first.raw_score_change_missing.eq(1).all()
    old = got.loc[got.security_uid.eq(raw.security_uid.iloc[0])].sort_values("signal_date")
    assert old.raw_score_change_missing.eq(1).all()  # the middle session belonged to a different UID
    new = got.loc[got.security_uid.eq("UID:NEW_IDENTITY")]
    assert new.raw_rank_change_missing.eq(1).all()
    continuous = got.loc[got.security_uid.eq(raw.security_uid.iloc[1])].sort_values("signal_date")
    np.testing.assert_allclose(continuous.raw_score_change, [0., .1, .1])
    np.testing.assert_allclose(continuous.raw_score_change_missing, [1., 0., 0.])


def test_history_future_append_and_input_permutation_invariance(raw):
    calendar = pd.DatetimeIndex(["2024-04-03", "2024-04-04"])
    first = boundary.add_history(raw, calendar[:1]).sort_values("security_uid").reset_index(drop=True)
    future = raw.copy()
    future["signal_date"] = calendar[1]
    future["raw_score"] += 100.
    appended = boundary.add_history(pd.concat([future, raw], ignore_index=True).sample(frac=1., random_state=1), calendar)
    past = appended.loc[appended.signal_date.eq(calendar[0])].sort_values("security_uid").reset_index(drop=True)
    pd.testing.assert_frame_equal(past, first)


def test_pair_feature_three_blocks_114_and_delta_direction(raw):
    features = boundary.add_history(raw, [raw.signal_date.iloc[0]])
    pairs = boundary.geometry(raw)
    got = boundary.pair_features(features, pairs, BASE)
    order = boundary.feature_order(BASE)
    assert len(order) == 114 and got.attrs["feature_order"] == list(order)
    row = got.iloc[0]
    ch = features.loc[features.raw_rank.eq(21)].iloc[0]
    inc = features.loc[features.raw_rank.eq(11)].iloc[0]
    for field in (*BASE, *boundary.RAW_FEATURES):
        assert row["challenger__"+field] == ch[field]
        assert row["incumbent__"+field] == inc[field]
        assert row["delta__"+field] == pytest.approx(ch[field]-inc[field])
    changed = features.sample(frac=1., random_state=9)
    changed["synthetic_unused_outcome"] = -999999.
    pd.testing.assert_frame_equal(boundary.pair_features(changed, pairs, BASE), got)
    assert got.attrs["target_values_read"] == 0


def test_matching_is_global_optimum_not_edge_greedy(raw):
    pairs = boundary.geometry(raw)
    values = weights_for(pairs, {(11,21):10., (11,22):9., (12,21):9.})
    chosen = boundary.maximum_weight_matching(pairs, values)
    assert set(zip(chosen.incumbent_raw_rank, chosen.challenger_raw_rank)) == {(11,22), (12,21)}
    assert chosen.predicted_edge.sum() == 18.


def test_total_tie_prefers_higher_edge_before_rank(raw):
    pairs = boundary.geometry(raw)
    values = weights_for(pairs, {(11,21):6., (12,22):5., (11,22):10., (12,21):1.})
    chosen = boundary.maximum_weight_matching(pairs, values)
    assert set(zip(chosen.incumbent_raw_rank, chosen.challenger_raw_rank)) == {(11,22), (12,21)}
    assert chosen.predicted_edge.tolist() == [10., 1.]
    assert chosen.attrs["exact_weight_arithmetic"] == "INTEGER_DYADIC_PRIMARY_PLUS_BOUNDED_LEX_BITS"


def test_ties_prefer_challenger_then_incumbent_rank_and_permutation(raw):
    pairs = boundary.geometry(raw)
    values = np.ones(len(pairs))
    chosen = boundary.maximum_weight_matching(pairs, values)
    assert list(zip(chosen.incumbent_raw_rank, chosen.challenger_raw_rank)) == list(zip(range(11,21), range(21,31)))
    perm = np.random.default_rng(7).permutation(len(pairs))
    shuffled = boundary.maximum_weight_matching(pairs.iloc[perm], values[perm])
    pd.testing.assert_frame_equal(shuffled, chosen)


def test_exact_dyadic_difference_is_not_an_isclose_tie(raw):
    pairs = boundary.geometry(raw)
    better = np.nextafter(1., np.inf)
    values = weights_for(pairs, {(11,21):1.5, (12,22):.5, (11,22):1., (12,21):better})
    chosen = boundary.maximum_weight_matching(pairs, values)
    assert set(zip(chosen.incumbent_raw_rank, chosen.challenger_raw_rank)) == {(11,22), (12,21)}
    exact = sum(Fraction(float(x)) for x in chosen.predicted_edge)
    assert exact > Fraction(2)


def test_small_graph_exhaustive_optimum_and_no_argument_mutation(raw):
    pairs = boundary.geometry(raw)
    edges = {(i,c):float((i*7+c*3)%11) for i in range(11,14) for c in range(21,24)}
    values = weights_for(pairs, edges)
    eligible = values > 0
    before = eligible.copy()
    chosen = boundary.maximum_weight_matching(pairs, values, eligible)
    np.testing.assert_array_equal(eligible, before)
    totals = []
    for choices in product([None,21,22,23], repeat=3):
        selected = [x for x in choices if x is not None]
        if len(selected) != len(set(selected)): continue
        totals.append(sum(edges.get((i,c),0.) for i,c in zip(range(11,14), choices)))
    assert chosen.predicted_edge.sum() == max(totals)


def test_integer_assignment_fallback_equals_exhaustive_objective():
    small = [[7, 9, 0], [8, 1, 0]]
    large = [[x << 500 for x in row] for row in small]
    a = boundary._exact_assignment(small)
    b = boundary._exact_assignment(large)
    assert sum(small[i][j] for i,j in a) == 17
    assert sum(large[i][j] for i,j in b) == 17 << 500
    assert set(a) == set(b)

def test_no_positive_edge_exact_raw_full_u_and_fixed_top_ten(raw):
    pairs = boundary.geometry(raw)
    panel = boundary.resolve(raw, pairs, np.zeros(len(pairs)), boundary.ROLES[1])
    np.testing.assert_array_equal(panel["rank"], panel.raw_rank)
    assert members(panel) == set(raw.loc[raw.raw_rank.le(20), "security_uid"])
    assert panel.attrs["replacement_count"] == 0
    assert not panel.attrs["full_rerank"] and not panel.attrs["production_promotion_allowed"]
    assert len(panel) == len(raw) and panel.attrs["fits"] == 0


def test_resolver_ten_max_one_to_one_membership_slots_and_full_u(raw):
    pairs = boundary.geometry(raw)
    panel = boundary.resolve(raw, pairs, np.ones(len(pairs)), boundary.ROLES[3])
    assert panel.attrs["replacement_count"] == 10
    assert set(raw.loc[raw.raw_rank.le(10), "security_uid"]).issubset(members(panel))
    assert len(members(panel)) == 20
    assert set(panel.loc[panel.selected, "raw_rank"]) == set(range(1,11)) | set(range(21,31))
    assert set(panel.security_uid) == set(raw.security_uid)
    assert sorted(panel["rank"]) == list(range(1,49))
    assert panel.loc[panel.raw_rank.gt(40), "rank"].gt(20).all()
    for pair in panel.attrs["matched_pairs"]:
        assert panel.loc[panel.security_uid.eq(pair["challenger_uid"]), "rank"].iloc[0] == pair["incumbent_raw_rank"]


def test_logit_strict_probability_threshold(raw):
    pairs = boundary.geometry(raw)
    values = np.full(len(pairs), .5)
    panel = boundary.resolve(raw, pairs, values, boundary.ROLES[0])
    assert panel.attrs["replacement_count"] == 0
    values[0] = .500001
    panel = boundary.resolve(raw, pairs, values, boundary.ROLES[0])
    assert panel.attrs["replacement_count"] == 1
    assert panel.attrs["matched_pairs"][0]["predicted_edge"] == pytest.approx(.000001)
    values[0] = 1.1
    with pytest.raises(ValueError, match="PROBABILITY"):
        boundary.resolve(raw, pairs, values, boundary.ROLES[0])


def test_quantile_q10_and_positive_q50_both_required_no_crossing_repair(raw):
    pairs = boundary.geometry(raw)
    median = weights_for(pairs, {(11,21):.2, (12,22):.3, (13,23):-.4})
    lower = weights_for(pairs, {(11,21):0., (12,22):.1, (13,23):.2})
    panel = boundary.resolve(raw, pairs, median, boundary.ROLES[8], q10=lower)
    assert panel.attrs["replacement_count"] == 1
    assert panel.attrs["matched_pairs"][0]["challenger_raw_rank"] == 22
    assert median[22] == -.4 and lower[22] == .2  # input remains unchanged


@pytest.mark.parametrize("problem,match", [
    ("future", "PRE2026"), ("missing_uid", "UID"), ("duplicate_uid", "DUPLICATE"),
    ("rank_missing", "ORDINAL"), ("too_small", "TOP40"),
])
def test_geometry_failure_closed(raw, problem, match):
    if problem == "future": raw.loc[0,"signal_date"] = pd.Timestamp("2026-01-01")
    elif problem == "missing_uid": raw.loc[0,"security_uid"] = None
    elif problem == "duplicate_uid": raw.loc[0,"security_uid"] = raw.loc[1,"security_uid"]
    elif problem == "rank_missing": raw.loc[0,"raw_rank"] = 2
    elif problem == "too_small": raw = raw.iloc[:39]
    with pytest.raises(ValueError, match=match): boundary.geometry(raw)


@pytest.mark.parametrize("problem,match", [
    ("nan_prediction", "FINITE_200"), ("short_prediction", "FINITE_200"),
    ("missing_pair", "EXACT_200"), ("uid_binding", "BINDING"),
    ("unknown_role", "FROZEN_C12"), ("q10_missing", "FINITE_Q10"),
])
def test_resolver_failure_closed(raw, problem, match):
    pairs = boundary.geometry(raw)
    values = np.ones(len(pairs))
    role, q10 = boundary.ROLES[1], None
    if problem == "nan_prediction": values[0] = np.nan
    elif problem == "short_prediction": values = values[:-1]
    elif problem == "missing_pair": pairs = pairs.iloc[:-1]
    elif problem == "uid_binding": pairs.loc[pairs.challenger_raw_rank.eq(21), "challenger_uid"] = "UID:OTHER"
    elif problem == "unknown_role": role = "C12_NEW_FAMILY"
    elif problem == "q10_missing": role = boundary.ROLES[8]
    with pytest.raises(ValueError, match=match): boundary.resolve(raw, pairs, values, role, q10=q10)


def test_history_and_feature_dependency_failures(raw):
    pairs = boundary.geometry(raw)
    with pytest.raises(ValueError, match="OUTSIDE_CALENDAR"):
        boundary.add_history(raw, ["2024-04-02"])
    with pytest.raises(ValueError, match="ORDERED_UNIQUE"):
        boundary.add_history(raw, ["2024-04-03", "2024-04-03"])
    history = boundary.add_history(raw, ["2024-04-03"])
    with pytest.raises(ValueError, match="ALREADY_PRESENT"):
        boundary.add_history(history, ["2024-04-03"])
    with pytest.raises(ValueError, match="FEATURE_COLUMNS"):
        boundary.pair_features(history.drop(columns=BASE[0]), pairs, BASE)
    history.loc[0, BASE[0]] = np.nan
    with pytest.raises(ValueError, match="FINITE_PAIR"):
        boundary.pair_features(history, pairs, BASE)
    with pytest.raises(ValueError, match="BASE32"):
        boundary.feature_order(BASE[:-1])




def test_all_200_lex_bits_sum_strictly_less_than_one_primary_unit(raw, monkeypatch):
    pairs = boundary.geometry(raw)
    captured = []
    original = boundary._exact_assignment
    def spy(matrix):
        captured.append(matrix)
        return original(matrix)
    monkeypatch.setattr(boundary, "_exact_assignment", spy)
    boundary.maximum_weight_matching(pairs, np.ones(200))
    encoded = captured[0]
    unit = 1 << 200
    secondary = [encoded[i][j] % unit for i in range(10) for j in range(20)]
    assert all(encoded[i][j] // unit == 1 for i in range(10) for j in range(20))
    assert set(secondary) == {1 << bit for bit in range(200)}
    assert sum(secondary) == unit-1 < unit
    assert all(encoded[i][j] == 0 for i in range(10) for j in range(20,30))


def test_missing_history_zero_encoding_cannot_be_overridden(raw):
    history = boundary.add_history(raw, ["2024-04-03"])
    history.loc[0, "raw_score_change"] = 100.
    with pytest.raises(ValueError, match="MISSING_HISTORY_MUST_ENCODE_ZERO"):
        boundary.pair_features(history, boundary.geometry(raw), BASE)



def test_feature_order_rejects_substitution_and_reordering():
    with pytest.raises(ValueError, match="EXACT_BASE32"):
        boundary.feature_order(tuple(reversed(BASE)))
    with pytest.raises(ValueError, match="EXACT_BASE32"):
        boundary.feature_order((*BASE[:-1], "synthetic_future_target"))
