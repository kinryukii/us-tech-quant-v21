"""C13 pure equal-membership consumers of a caller-qualified frozen covariance.

No readers, labels, fitting, risk estimation, weights, account or source authority.
D02/D09 exhaust the same 658 rank-only feasible sets. Exact dyadic sums avoid
turning distinct native-float quadratic objectives into approximate ties.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import combinations
import copy
import hashlib
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, cut_tree
from scipy.spatial.distance import squareform
from scripts.research.a2.risk.joint_risk_estimators import validate_covariance

METHODS = ("D02", "D05", "D06", "D09", "D10", "D11")
SPEC = dict(schema="C13_CONSTRAINED_MEMBERSHIP_V1", methods=list(METHODS),
    raw_domain=40, fixed_core=10, final_members=20, final_equal_weight=.05,
    alpha="a=(41-RawOrdinal)/40; normalize by sum over Raw40", alpha_floor=.975,
    integer_rank_loss_cap=15, alpha_floor_methods=["D02", "D09"],
    tie="objective first; lex selected Raw-rank tuple; UID already bound to unique rank",
    D02="exact minimum equal-weight variance over all fixed-core alpha-feasible sets",
    D05="best-improving one-boundary-swap diversification-ratio local search; no alpha floor",
    D05_max_accepted_swaps=30, D05_global_optimum_claim=False,
    D06="positive rank-alpha boundary11-40; minimum signed marginal equal-weight variance, Rawrank, UID",
    D09="exact minimum Herfindahl of absolute risk contributions; zero variance blocks whole request",
    hierarchy_domain="boundary30 only; stable UID order before distance/linkage",
    linkage="single", distance="sqrt(max(0,(1-clipped_correlation)/2))",
    hierarchy_positive_diagonal_required=True, D11_input_normalization="covariance/max(Raw40 marginal variance); dimensionless scalar, original HRP floor is dimensionless",
    clusters=10, cluster_cut="cut_tree n_clusters=10; exactly10 even equal linkage heights",
    D10="one best Raw-rank member per cluster plus fixed core10",
    D11="existing HRP boundary mass; sum per same10 clusters; capped largest-deficit integer apportionment of10 slots",
    D11_slot_tie="cluster minimum Rawrank then UID; choose best Rawrank within cluster",
    consumer_psd="existing validate_covariance regularize=False; no new state/repair",
    source_authority="caller qualification required; no authority upgrade",
    scientific_retry=0, estimations=0, learned_states=0)


def specification():
    return copy.deepcopy(SPEC)


@lru_cache(maxsize=1)
def feasible_geometry():
    """All legal fixed-core sets: k replacements cost at least k**2 ranks."""
    baseline = tuple(range(20))
    rows = {baseline}
    for k in (1, 2, 3):
        for removed in combinations(range(10, 20), k):
            for added in combinations(range(20, 40), k):
                if sum(added)-sum(removed) <= SPEC["integer_rank_loss_cap"]:
                    rows.add(tuple(sorted((set(baseline)-set(removed)) | set(added))))
    values = np.asarray(sorted(rows), dtype=np.int64)
    # Immutable backing bytes prevent callers re-enabling writes to cached geometry.
    return np.frombuffer(values.tobytes(), dtype=np.int64).reshape(values.shape)


def _clock(value):
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise ValueError("FINITE_CLOCK_REQUIRED")
    return parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")


def _inputs(covariance, covariance_uids, raw_uids, raw_ranks, decision_at, state_cutoff):
    decision, cutoff = _clock(decision_at), _clock(state_cutoff)
    if not cutoff < decision < pd.Timestamp("2026-01-01", tz="UTC"):
        raise ValueError("PRE2026_PRIOR_STATE_CLOCK_REQUIRED")
    raw_uids, covariance_uids = tuple(raw_uids), tuple(covariance_uids)
    for ids in (raw_uids, covariance_uids):
        if len(ids) != 40 or len(set(ids)) != 40 or any(not isinstance(u, str) or not u.strip() for u in ids):
            raise ValueError("EXACT40_UNIQUE_NONEMPTY_UIDS_REQUIRED")
    if set(raw_uids) != set(covariance_uids):
        raise ValueError("RAW_COVARIANCE_UID_DOMAIN_MISMATCH")
    ranks = np.asarray(raw_ranks, dtype=float)
    if ranks.shape != (40,) or not np.isfinite(ranks).all() or not np.array_equal(np.sort(ranks), np.arange(1, 41)):
        raise ValueError("EXACT_RAW_ORDINALS_1_TO_40_REQUIRED")
    matrix = np.asarray(covariance, dtype=float)
    if matrix.shape != (40, 40):
        raise ValueError("EXACT40_COVARIANCE_REQUIRED")
    matrix, _ = validate_covariance(matrix, regularize=False)
    order = np.argsort(ranks, kind="stable")
    uids = tuple(raw_uids[i] for i in order)
    locations = {u: i for i, u in enumerate(covariance_uids)}
    indices = [locations[u] for u in uids]
    return matrix[np.ix_(indices, indices)].copy(), uids, decision, cutoff


def _dyadic(matrix):
    ratios = [[float(v).as_integer_ratio() for v in row] for row in matrix]
    denominator = max(d for row in ratios for _, d in row)
    return [[n*(denominator//d) for n, d in row] for row in ratios]


def _total(integer_matrix, selected):
    return sum(integer_matrix[i][j] for i in selected for j in selected)


def _variance(matrix, selected):
    return float(np.sum(matrix[np.ix_(selected, selected)]))/len(selected)**2


def _exact(matrix, method):
    integers = _dyadic(matrix)
    winner, best = None, None
    for row in feasible_geometry():
        selected = tuple(map(int, row))
        if method == "D02":
            value = (_total(integers, selected), 1)
        else:
            totals = [sum(integers[i][j] for j in selected) for i in selected]
            if sum(totals) <= 0:
                raise ValueError("D09_ZERO_PORTFOLIO_VARIANCE_BLOCKED")
            value = (sum(v*v for v in totals), sum(abs(v) for v in totals)**2)
        if best is None or value[0]*best[1] < best[0]*value[1]:
            winner, best = selected, value
    return winner, dict(feasible_sets_evaluated=len(feasible_geometry()),
        global_optimum_claim=True, exact_objective_comparison="dyadic integer sum/rational cross-product",
        objective=float(best[0]/best[1]) if method == "D09" else _variance(matrix, winner))


def _diversification(matrix, selected):
    variance = _variance(matrix, selected)
    if variance <= 0:
        raise ValueError("D05_ZERO_PORTFOLIO_VARIANCE_BLOCKED")
    ratio = float(np.sqrt(np.diag(matrix)[list(selected)]).mean()/np.sqrt(variance))
    if not np.isfinite(ratio):
        raise ValueError("D05_NONFINITE_DIVERSIFICATION_RATIO")
    return ratio


def _local_diversification(matrix):
    selected = tuple(range(20))
    current = _diversification(matrix, selected)
    evaluated, trace, capped = 1, [], True
    for step in range(SPEC["D05_max_accepted_swaps"]):
        winner, value = selected, current
        remaining = [i for i in range(10, 40) if i not in selected]
        for removed in selected[10:]:
            for added in remaining:
                proposed = tuple(sorted((set(selected)-{removed}) | {added}))
                score = _diversification(matrix, proposed)
                evaluated += 1
                if score > value or (score == value and score > current and proposed < winner):
                    winner, value = proposed, score
        if value <= current:
            capped = False
            break
        trace.append(dict(step=step+1, removed_rank=next(i+1 for i in selected if i not in winner),
                          added_rank=next(i+1 for i in winner if i not in selected), objective=value))
        selected, current = winner, value
    return selected, dict(objective=current, accepted_swaps=len(trace), swap_trace=trace,
        objective_evaluations=evaluated, iteration_cap_reached=capped, global_optimum_claim=False)


def _greedy(matrix, uids):
    integers, selected, trace = _dyadic(matrix), list(range(10)), []
    for step in range(10):
        remaining = [i for i in range(10, 40) if i not in selected]
        before = _variance(matrix, selected)
        totals = {i: _total(integers, selected+[i]) for i in remaining}
        chosen = min(remaining, key=lambda i: (totals[i], i+1, uids[i]))
        after = _variance(matrix, selected+[chosen])
        trace.append(dict(step=step+1, chosen_rank=chosen+1, marginal_variance=after-before))
        selected.append(chosen)
    return tuple(sorted(selected)), dict(greedy_trace=trace, objective_evaluations=sum(range(21, 31)),
        global_optimum_claim=False, marginal_coordinate="variance of each intermediate equal-weight set")


def _clusters(matrix, uids):
    if np.any(np.diag(matrix) <= 0):
        raise ValueError("HIERARCHY_POSITIVE_MARGINAL_VARIANCE_REQUIRED")
    boundary = sorted(range(10, 40), key=lambda i: uids[i])
    sub = matrix[np.ix_(boundary, boundary)]
    sd = np.sqrt(np.diag(sub))
    corr = np.clip((sub/sd[:, None])/sd[None, :], -1, 1)
    distance = np.sqrt(np.maximum(0, (1-corr)/2))
    np.fill_diagonal(distance, 0.)
    tree = linkage(squareform(distance, checks=False), method=SPEC["linkage"])
    labels = cut_tree(tree, n_clusters=[SPEC["clusters"]]).ravel()
    groups = [sorted(boundary[i] for i in np.flatnonzero(labels == label)) for label in sorted(set(labels))]
    groups.sort(key=lambda g: (g[0]+1, uids[g[0]]))
    if len(groups) != 10 or sorted(i for g in groups for i in g) != list(range(10, 40)):
        raise ValueError("EXACT10_FULL_BOUNDARY_CLUSTERS_REQUIRED")
    return boundary, groups


def _hierarchical(matrix, uids, method):
    boundary, groups = _clusters(matrix, uids)
    if method == "D10":
        slots = np.ones(10, dtype=int)
        masses = None
    else:
        # Existing owner returns continuous hierarchy mass. Here it is only an
        # apportionment input: final memberships always have exactly 1/20 weight.
        from scripts.research.a2.portfolio.joint_allocation_methods import _hrp
        normalizer = float(np.max(np.diag(matrix)))
        asset_mass = _hrp(matrix/normalizer, np.asarray(boundary))
        if not np.isfinite(asset_mass).all() or (asset_mass < 0).any() or asset_mass.sum() <= 0:
            raise ValueError("D11_HRP_BOUNDARY_MASS_INVALID")
        by_asset = dict(zip(boundary, asset_mass))
        masses = np.array([sum(by_asset[i] for i in g) for g in groups])
        quotas = 10*masses/masses.sum()
        capacities = np.array([len(g) for g in groups])
        slots = np.minimum(np.floor(quotas).astype(int), capacities)
        while slots.sum() < 10:
            eligible = [i for i in range(10) if slots[i] < capacities[i]]
            chosen = min(eligible, key=lambda i: (-(quotas[i]-slots[i]), groups[i][0]+1, uids[groups[i][0]]))
            slots[chosen] += 1
    selected = tuple(sorted([*range(10), *(i for g, n in zip(groups, slots) for i in g[:n])]))
    return selected, dict(global_optimum_claim=False, clusters=[[uids[i] for i in g] for g in groups],
        cluster_slots=slots.tolist(), cluster_mass=None if masses is None else masses.tolist(),
        deterministic_transform_calls=2 if method == "D10" else 5,
        hrp_dimensionless_normalizer=None if method == "D10" else normalizer)


def select(method, covariance, covariance_uids, raw_uids, raw_ranks, *, decision_at, state_cutoff):
    """One dated request; outputs membership only, never authority or fitted risk.

    UID lists carry caller-proven bindings. A numerically identical matrix cannot
    itself prove those bindings truthful; the caller must pin the source receipt.
    """
    if method not in METHODS:
        raise ValueError("FROZEN_MEMBERSHIP_METHOD_REQUIRED")
    matrix, uids, decision, cutoff = _inputs(covariance, covariance_uids, raw_uids, raw_ranks, decision_at, state_cutoff)
    if method in {"D02", "D09"}:
        selected, detail = _exact(matrix, method)
    elif method == "D05":
        selected, detail = _local_diversification(matrix)
    elif method == "D06":
        selected, detail = _greedy(matrix, uids)
    else:
        selected, detail = _hierarchical(matrix, uids, method)
    if len(selected) != 20 or len(set(selected)) != 20 or not set(range(10)).issubset(selected):
        raise ValueError("EXACT20_FIXED_CORE_INVARIANT")
    sacrifice = sum(selected)-sum(range(20))
    if method in {"D02", "D09"} and sacrifice > 15:
        raise ValueError("FIXED_ALPHA_FLOOR_VIOLATION")
    variance = _variance(matrix, selected)
    raw_variance = _variance(matrix, tuple(range(20)))
    alpha_raw = 610/820
    alpha_selected = (610-sacrifice)/820
    geometry = feasible_geometry() if method in {"D02", "D09"} else None
    receipt = dict(method=method, decision_at=decision.isoformat(), state_cutoff=cutoff.isoformat(),
        optimizer_solve_calls=1, deterministic_transform_calls=detail.pop("deterministic_transform_calls", 1),
        covariance_estimations=0, learned_states=0, retries=0, final_weight=.05,
        geometry_sha256=None if geometry is None else hashlib.sha256(geometry.tobytes()).hexdigest(),
        source_authority_qualified=False, caller_source_receipt_required=True,
        full_U_panel_owner="caller; this module only chooses within Raw40", **detail)
    return dict(chosen_uids=[uids[i] for i in selected], selected_raw_ranks=[i+1 for i in selected],
        predicted_risk=dict(variance=variance, raw_variance=raw_variance,
            std=float(np.sqrt(max(variance, 0.))), raw_std=float(np.sqrt(max(raw_variance, 0.)))),
        alpha_sacrifice=dict(rank_loss=sacrifice, raw_mass=alpha_raw, selected_mass=alpha_selected,
            mass_ratio=alpha_selected/alpha_raw, boundary_replacements=len(set(selected)-set(range(20)))),
        receipt=receipt)
