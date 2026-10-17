"""Pure synthetic C13 consumer checks: no readers, fit, labels or real outcomes."""
from itertools import combinations
from fractions import Fraction
import numpy as np
import pytest
from scripts.research.a2.factors import selector_constrained_membership as m


@pytest.fixture
def case():
    uids = tuple(f"SEC:{i:03d}" for i in range(1, 41))
    return dict(covariance=np.eye(40), covariance_uids=uids, raw_uids=uids,
                raw_ranks=np.arange(1, 41), decision_at="2024-04-02T20:00:00Z",
                state_cutoff="2024-04-01T20:00:00Z")


def run(case, method, matrix=None):
    args = dict(case)
    if matrix is not None:
        args["covariance"] = matrix
    return m.select(method, **args)


def independent_sets():
    raw = set(range(20))
    yield tuple(range(20))
    for k in (1, 2, 3):
        for removed in combinations(range(10, 20), k):
            for added in combinations(range(20, 40), k):
                if sum(added)-sum(removed) <= 15:
                    yield tuple(sorted((raw-set(removed)) | set(added)))


def exact_rc_objective(matrix, row):
    totals = [sum(Fraction(float(matrix[i, j])) for j in row) for i in row]
    return sum(t*t for t in totals)/sum(abs(t) for t in totals)**2


def test_feasible_geometry_complete_unique_immutable_and_floor_proof():
    got = m.feasible_geometry()
    assert got.shape == (658, 20)
    assert set(map(tuple, got)) == set(independent_sets())
    assert len(set(map(tuple, got))) == len(got)
    assert not got.flags.writeable
    with pytest.raises(ValueError):
        got.flags.writeable = True
    assert np.all(np.diff(got, axis=1) > 0)
    assert (got[:, :10] == np.arange(10)).all()
    assert (got.sum(axis=1)-sum(range(20))).max() == 15
    assert max(len(set(row)-set(range(20))) for row in got) == 3
    # Four nearest possible replacements lose 1+3+5+7=16, exceeding floor.
    assert sum(range(20, 24))-sum(range(16, 20)) == 16
    assert 610*(1-.975) < 16


@pytest.mark.parametrize("method", m.METHODS)
def test_fixed_core_membership_only_receipt_no_mutation(case, method):
    matrix = case["covariance"].copy()
    result = run(case, method)
    assert len(result["chosen_uids"]) == len(set(result["chosen_uids"])) == 20
    assert set(case["raw_uids"][:10]).issubset(result["chosen_uids"])
    assert set(result["chosen_uids"]).issubset(case["raw_uids"])
    assert result["selected_raw_ranks"] == sorted(result["selected_raw_ranks"])
    assert result["receipt"]["optimizer_solve_calls"] == 1
    assert result["receipt"]["covariance_estimations"] == result["receipt"]["learned_states"] == 0
    assert result["receipt"]["source_authority_qualified"] is False
    assert result["receipt"]["caller_source_receipt_required"] is True
    assert result["receipt"]["final_weight"] == .05
    assert result["receipt"]["retries"] == 0
    assert set(result) == {"chosen_uids", "selected_raw_ranks", "predicted_risk", "alpha_sacrifice", "receipt"}
    np.testing.assert_array_equal(case["covariance"], matrix)
    if method in ("D02", "D09"):
        assert result["alpha_sacrifice"]["mass_ratio"] >= .975
        assert result["receipt"]["global_optimum_claim"]
        assert result["receipt"]["feasible_sets_evaluated"] == 658
    else:
        assert not result["receipt"]["global_optimum_claim"]


def test_d02_exact_minimum_matches_independent_exhaustive_diagonal(case):
    diagonal = np.arange(40, 0, -1, dtype=float)
    matrix = np.diag(diagonal)
    expected = min(independent_sets(), key=lambda row: (sum(Fraction(float(diagonal[i])) for i in row), row))
    got = run(case, "D02", matrix)
    assert got["selected_raw_ranks"] == [i+1 for i in expected]
    assert got["predicted_risk"]["variance"] == sum(diagonal[list(expected)])/400
    assert got["alpha_sacrifice"]["rank_loss"] <= 15


def test_d02_does_not_take_alpha_infeasible_low_variance_rank40(case):
    matrix = np.eye(40)
    matrix[39, 39] = 0.
    got = run(case, "D02", matrix)
    assert got["selected_raw_ranks"] == list(range(1, 21))
    assert 40 not in got["selected_raw_ranks"]


def test_d02_native_one_ulp_difference_survives_float_total_tie(case):
    matrix = np.eye(40)
    matrix[20, 20] = np.nextafter(1., 0.)
    # Ordinary totals lose this difference; declared exact objective must not.
    assert matrix[np.ix_(list(range(20)), list(range(20)))].sum() == matrix[np.ix_([*range(19), 20], [*range(19), 20])].sum()
    got = run(case, "D02", matrix)
    assert got["selected_raw_ranks"] == [*range(1, 20), 21]


def test_d09_absolute_contributions_and_exact_feasible_global_minimum(case):
    signs = np.array([1, -2, 3, -1, *([1]*36)], dtype=float)
    matrix = np.outer(signs, signs)+np.eye(40)
    expected = min(independent_sets(), key=lambda row: (exact_rc_objective(matrix, row), row))
    got = run(case, "D09", matrix)
    assert got["selected_raw_ranks"] == [i+1 for i in expected]
    assert got["receipt"]["objective"] == pytest.approx(float(exact_rc_objective(matrix, expected)))
    raw_totals = matrix[:20, :20].sum(axis=1)
    assert (raw_totals < 0).any()  # Abs normalization is materially required.


@pytest.mark.parametrize("method", ["D05", "D09"])
def test_zero_portfolio_variance_is_typed_block(case, method):
    with pytest.raises(ValueError, match="ZERO_PORTFOLIO_VARIANCE"):
        run(case, method, np.zeros((40, 40)))


def test_d05_bounded_single_swap_local_no_floor(case):
    matrix = np.diag([*([1.]*16), *([9.]*4), *([1.]*20)])
    got = run(case, "D05", matrix)
    assert got["selected_raw_ranks"] == [*range(1, 17), *range(21, 25)]
    assert got["alpha_sacrifice"]["boundary_replacements"] == 4
    assert got["alpha_sacrifice"]["mass_ratio"] < .975
    assert got["receipt"]["accepted_swaps"] == 4
    assert got["receipt"]["objective"] == pytest.approx(np.sqrt(20))
    assert not got["receipt"]["iteration_cap_reached"]
    assert np.all(np.diff([r["objective"] for r in got["receipt"]["swap_trace"]]) > 0)


def test_d05_equal_objective_does_not_churn_and_is_not_global_claim(case):
    got = run(case, "D05")
    assert got["selected_raw_ranks"] == list(range(1, 21))
    assert got["receipt"]["accepted_swaps"] == 0
    assert not got["receipt"]["global_optimum_claim"]
    assert got["receipt"]["objective_evaluations"] == 201


def test_d06_signed_marginal_variance_is_negative_and_raw_tie(case):
    got = run(case, "D06")
    assert got["selected_raw_ranks"] == list(range(1, 21))
    trace = got["receipt"]["greedy_trace"]
    assert all(item["marginal_variance"] < 0 for item in trace)
    assert [item["chosen_rank"] for item in trace] == list(range(11, 21))
    assert trace[0]["marginal_variance"] == pytest.approx(1/11-1/10)
    assert got["receipt"]["objective_evaluations"] == 255


def test_d06_risk_first_has_no_alpha_penalty(case):
    matrix = np.diag([*([1.]*10), *([100.]*10), *([.01]*20)])
    got = run(case, "D06", matrix)
    assert got["selected_raw_ranks"] == [*range(1, 11), *range(21, 31)]
    assert got["alpha_sacrifice"]["rank_loss"] > 15


def test_d10_single_linkage_exactly10_clusters_even_all_distances_tie(case):
    got = run(case, "D10")
    clusters = got["receipt"]["clusters"]
    assert len(clusters) == 10
    assert sorted(u for cluster in clusters for u in cluster) == list(case["raw_uids"][10:])
    expected = {case["raw_uids"].index(min(group, key=case["raw_uids"].index))+1 for group in clusters}
    assert set(got["selected_raw_ranks"][10:]) == expected
    assert got["receipt"]["cluster_slots"] == [1]*10


def test_d11_reuses_existing_hrp_mass_and_integer_capacity_slots(case, monkeypatch):
    from scripts.research.a2.portfolio import joint_allocation_methods as owner
    observed = []
    def fake_hrp(matrix, ids):
        observed.append(tuple(ids))
        return np.ones(30)/30
    monkeypatch.setattr(owner, "_hrp", fake_hrp)
    got = run(case, "D11")
    assert len(observed) == 1
    assert observed[0] == tuple(range(10, 40))
    receipt = got["receipt"]
    assert len(receipt["cluster_slots"]) == 10
    assert sum(receipt["cluster_slots"]) == 10
    assert all(0 <= n <= len(group) for n, group in zip(receipt["cluster_slots"], receipt["clusters"]))
    assert sum(receipt["cluster_mass"]) == pytest.approx(1.)
    chosen = set(got["chosen_uids"])
    for group, n in zip(receipt["clusters"], receipt["cluster_slots"]):
        assert [u for u in group if u in chosen] == group[:n]


def test_d11_invalid_hierarchy_mass_blocks_no_fallback(case, monkeypatch):
    from scripts.research.a2.portfolio import joint_allocation_methods as owner
    monkeypatch.setattr(owner, "_hrp", lambda *args: np.full(30, np.nan))
    with pytest.raises(ValueError, match="HRP_BOUNDARY_MASS_INVALID"):
        run(case, "D11")


@pytest.mark.parametrize("method", m.METHODS)
def test_raw_and_covariance_permutations_preserve_uid_binding(case, method):
    generator = np.random.default_rng(19)
    values = generator.normal(size=(40, 40))
    matrix = values@values.T+np.eye(40)
    expected = run(case, method, matrix)
    p, q = generator.permutation(40), generator.permutation(40)
    changed = dict(case, covariance=matrix[np.ix_(p, p)],
        covariance_uids=tuple(case["covariance_uids"][i] for i in p),
        raw_uids=tuple(case["raw_uids"][i] for i in q), raw_ranks=case["raw_ranks"][q])
    actual = run(changed, method)
    assert actual["chosen_uids"] == expected["chosen_uids"]
    assert actual["alpha_sacrifice"] == expected["alpha_sacrifice"]
    assert actual["predicted_risk"] == expected["predicted_risk"]


@pytest.mark.parametrize("date,cutoff", [
    ("2026-01-01", "2025-12-31"), ("2027-01-01", "2025-12-31"),
    ("2024-04-02", "2024-04-02"), ("2024-04-02", "2024-04-03"), ("NaT", "2024-04-01")])
def test_cutoff_and_locked_years_fail_before_consumer(case, monkeypatch, date, cutoff):
    monkeypatch.setattr(m, "_exact", lambda *args: pytest.fail("consumer must not run"))
    with pytest.raises(ValueError, match="CLOCK"):
        run(dict(case, decision_at=date, state_cutoff=cutoff), "D02")


def test_same_frozen_prior_state_on_later_legal_date_does_not_change_selection(case):
    first = run(case, "D02")
    second = run(dict(case, decision_at="2024-12-31"), "D02")
    assert first["chosen_uids"] == second["chosen_uids"]
    assert first["receipt"]["geometry_sha256"] == second["receipt"]["geometry_sha256"]


@pytest.mark.parametrize("fault", ["duplicate_uid", "missing_uid", "swapped_identity", "bad_rank", "nan_rank", "wrong_size", "nan_cov", "asymmetric", "non_psd"])
def test_required_identity_and_matrix_fail_closed(case, fault):
    changed = dict(case)
    if fault == "duplicate_uid": changed["raw_uids"] = (case["raw_uids"][0], *case["raw_uids"][:-1])
    elif fault == "missing_uid": changed["raw_uids"] = ("", *case["raw_uids"][1:])
    elif fault == "swapped_identity": changed["covariance_uids"] = ("NEW:IDENTITY", *case["covariance_uids"][1:])
    elif fault == "bad_rank": changed["raw_ranks"] = np.r_[1, np.arange(1, 40)]
    elif fault == "nan_rank": changed["raw_ranks"] = np.r_[np.nan, np.arange(2, 41)]
    elif fault == "wrong_size": changed["covariance"] = np.eye(39)
    else:
        matrix = case["covariance"].copy()
        if fault == "nan_cov": matrix[0, 0] = np.nan
        elif fault == "asymmetric": matrix[0, 1] = 1.
        else: matrix[0, 1] = matrix[1, 0] = 2.
        changed["covariance"] = matrix
    with pytest.raises(ValueError):
        run(changed, "D02")


def test_spec_is_frozen_copy_and_no_unregistered_method(case):
    changed = m.specification()
    changed["alpha_floor"] = .5
    assert m.specification()["alpha_floor"] == .975
    with pytest.raises(ValueError, match="FROZEN_MEMBERSHIP_METHOD"):
        run(case, "D12")


def test_d05_local_stall_is_reported_without_claiming_global_optimum(case):
    matrix = np.diag([*([1.]*10), *([9.]*10), *([1.]*20)])
    got = run(case, "D05", matrix)
    assert got["selected_raw_ranks"] == list(range(1, 21))
    assert got["receipt"]["accepted_swaps"] == 0
    assert not got["receipt"]["global_optimum_claim"]
    all_same_variance = [*range(10), *range(20, 30)]
    global_better = np.sqrt(np.diag(matrix)[all_same_variance]).mean()/np.sqrt(matrix[np.ix_(all_same_variance, all_same_variance)].sum()/400)
    assert global_better > got["receipt"]["objective"]


@pytest.mark.parametrize("method", ["D10", "D11"])
@pytest.mark.parametrize("scale", [1e-16, 1e8])
def test_hierarchy_is_unit_invariant_with_strictly_positive_covariance(case, method, scale):
    generator = np.random.default_rng(87)
    values = generator.normal(size=(40, 40))
    matrix = values@values.T+np.eye(40)
    baseline = run(case, method, matrix)
    scaled = run(case, method, matrix*scale)
    assert scaled["chosen_uids"] == baseline["chosen_uids"]
    assert scaled["receipt"]["clusters"] == baseline["receipt"]["clusters"]
    assert scaled["receipt"]["cluster_slots"] == baseline["receipt"]["cluster_slots"]
    assert scaled["predicted_risk"]["variance"] == pytest.approx(baseline["predicted_risk"]["variance"]*scale)
    if method == "D11":
        np.testing.assert_allclose(scaled["receipt"]["cluster_mass"], baseline["receipt"]["cluster_mass"], rtol=1e-12, atol=1e-14)
        assert scaled["receipt"]["hrp_dimensionless_normalizer"] == pytest.approx(baseline["receipt"]["hrp_dimensionless_normalizer"]*scale)
        assert scaled["receipt"]["deterministic_transform_calls"] == 5


@pytest.mark.parametrize("method", ["D10", "D11"])
@pytest.mark.parametrize("zero_position", [0, 10, 39])
def test_zero_marginal_variance_cannot_fabricate_correlation(case, method, zero_position):
    matrix = np.eye(40)
    matrix[zero_position, zero_position] = 0.
    with pytest.raises(ValueError, match="POSITIVE_MARGINAL_VARIANCE"):
        run(case, method, matrix)


def test_existing_hrp_receives_dimensionless_scalar_only_real_risk_kept(case, monkeypatch):
    from scripts.research.a2.portfolio import joint_allocation_methods as owner
    matrix = np.diag(np.arange(1, 41, dtype=float))*1e-16
    seen = []
    def fake_hrp(supplied, ids):
        seen.append(supplied.copy())
        np.testing.assert_allclose(supplied, matrix/np.diag(matrix).max())
        assert np.diag(supplied).max() == 1.
        return np.ones(30)/30
    monkeypatch.setattr(owner, "_hrp", fake_hrp)
    got = run(case, "D11", matrix)
    assert len(seen) == 1
    selected = np.array(got["selected_raw_ranks"])-1
    assert got["predicted_risk"]["variance"] == matrix[np.ix_(selected, selected)].sum()/400
    assert got["receipt"]["hrp_dimensionless_normalizer"] == 40e-16
    assert m.specification()["hierarchy_positive_diagonal_required"] is True
