"""C11 pure classical selectors: fixed formulas, no fitting or risk estimation.

Ranking adapts selector_challenge.rank_panel's stable sort/cumcount for the new
predeclared raw-rank tie rule. Covariance is supplied by its shared owner; this
module only validates alignment/PSD and evaluates equal-weight set risk.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

TREND_COLUMNS = ("ret_20d", "ret_40d", "ret_60d", "ret_120d", "price_vs_ma20",
                 "price_vs_ma50", "price_vs_ma120", "ma20_vs_ma50", "ma50_vs_ma120")
RISK_COLUMNS = ("realized_vol_20d", "downside_vol_20d", "max_drawdown_60d", "avg_dollar_volume_20d")
BASE_ROLES = ("C11_A1_ALPHA_VOL", "C11_A2_ALPHA_DOWNSIDE", "C11_A3_ALPHA_DRAWDOWN",
              "C11_A4_ALPHA_RISK3", "C11_A5_ALPHA_RISK4", "C11_A6_TREND_RISK3",
              "C11_A7_TREND_RISK4", "C11_A8_PARETO_ALPHA_RISK")
SANITY_ROLES = ("C11_SANITY_MIN_VOL", "C11_SANITY_RAW_TOP20")
RISK_ROLES = tuple("C11_B_" + name for name in ("DIAG", "SAMPLE_COV", "LW", "OAS", "CONSTANT_CORR",
                  "EWMA", "PCA", "GARCH", "GJR_GARCH", "COV_ENSEMBLE"))
COORDINATES = ("ALPHA", "TREND", "VOL_RISK", "DOWNSIDE_RISK", "DD_RISK", "ILLIQ_RISK")
DD_SEMANTICS = "r1._rolling_max_drawdown=min(wealth/cummax(wealth)-1)<=0; magnitude=-max_drawdown_60d"
TIE_POLICY = "score descending, raw_rank ascending, security_uid ascending"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _validated(frame):
    required = ("signal_date", "security_uid", "raw_score", "raw_rank", *TREND_COLUMNS, *RISK_COLUMNS)
    _require(isinstance(frame, pd.DataFrame) and len(frame) > 0 and set(required).issubset(frame.columns),
             "FULL_U_REQUIRED_COLUMNS")
    out = frame.copy().reset_index(drop=True)
    out["signal_date"] = pd.to_datetime(out.signal_date)
    _require(out.signal_date.notna().all() and out.signal_date.dt.tz is None
             and out.signal_date.lt(pd.Timestamp("2026-01-01")).all(), "PRE2026_DECISION_CLOCK_REQUIRED")
    _require(out.security_uid.notna().all() and out.security_uid.map(lambda s: isinstance(s, str) and bool(s.strip())).all(),
             "NONEMPTY_SECURITY_UID_REQUIRED")
    _require(not out.duplicated(["signal_date", "security_uid"]).any(), "DUPLICATE_DATE_UID")
    _require(np.isfinite(out[["raw_score", "raw_rank", *TREND_COLUMNS, *RISK_COLUMNS]].to_numpy(float)).all(),
             "FINITE_INPUT_NO_ROW_DROP")
    _require(out.max_drawdown_60d.le(0).all(), "MAX_DRAWDOWN_MUST_BE_NONPOSITIVE_OWNER_SEMANTICS")
    _require(out.realized_vol_20d.ge(0).all() and out.downside_vol_20d.ge(0).all()
             and out.avg_dollar_volume_20d.ge(0).all(), "NONNEGATIVE_RISK_LIQUIDITY_REQUIRED")
    for _, group in out.groupby("signal_date", sort=False):
        rank = group.raw_rank.to_numpy(float)
        _require(len(group) >= 40 and np.array_equal(np.sort(rank), np.arange(1, len(group) + 1)),
                 "FULL_U_RAW_ORDINAL_RANKS_AND_TOP40_REQUIRED")
        _require(np.all(np.diff(group.sort_values("raw_rank").raw_score.to_numpy(float)) <= 0),
                 "RAW_SCORE_RANK_BINDING_REQUIRED")
    return out


def _pct(values):
    return pd.Series(np.asarray(values)).rank(method="average", pct=True).to_numpy(float)


def coordinates(frame):
    """Fixed full-date cross-sectional percentile coordinates, retaining every UID."""
    out = _validated(frame)
    for _, indices in out.groupby("signal_date", sort=False).groups.items():
        g = out.loc[indices]
        out.loc[indices, "ALPHA"] = _pct(g.raw_score)
        out.loc[indices, "TREND"] = np.mean([_pct(g[name]) for name in TREND_COLUMNS], axis=0)
        out.loc[indices, "VOL_RISK"] = _pct(g.realized_vol_20d)
        out.loc[indices, "DOWNSIDE_RISK"] = _pct(g.downside_vol_20d)
        out.loc[indices, "DD_RISK"] = _pct(-g.max_drawdown_60d)
        out.loc[indices, "ILLIQ_RISK"] = 1. - _pct(g.avg_dollar_volume_20d)
    return out


def _panel(coords, cid, scores):
    out = coords.copy()
    out["score"] = np.asarray(scores, dtype=float)
    _require(np.isfinite(out.score).all(), "FINITE_FULL_U_SCORE_REQUIRED")
    out = out.sort_values(["signal_date", "score", "raw_rank", "security_uid"],
                          ascending=[True, False, True, True], kind="stable")
    out["rank"] = out.groupby("signal_date", sort=False).cumcount() + 1
    out["candidate_id"] = cid
    out.attrs.update(diagnostic_only=cid in SANITY_ROLES, mechanism_support_eligible=cid not in SANITY_ROLES,
                     production_promotion_allowed=False,
                     tie_policy=TIE_POLICY, fits=0, covariance_estimations=0, drawdown_semantics=DD_SEMANTICS)
    return out.sort_values(["signal_date", "security_uid"], kind="stable").reset_index(drop=True)


def pareto_fronts(good_coordinates):
    """All dimensions maximize; front numbers start at 1, with no weighted fusion."""
    values = np.asarray(good_coordinates, dtype=float)
    _require(values.ndim == 2 and len(values) > 0 and np.isfinite(values).all(), "FINITE_PARETO_INPUT")
    dominates = (values[:, None, :] >= values[None, :, :]).all(2) & (values[:, None, :] > values[None, :, :]).any(2)
    remaining, fronts = np.ones(len(values), dtype=bool), np.zeros(len(values), dtype=np.int64)
    current = 1
    while remaining.any():
        active = np.flatnonzero(remaining)
        front = active[~dominates[np.ix_(active, active)].any(0)]
        _require(len(front) > 0, "PARETO_FRONT_REQUIRED")
        fronts[front] = current
        remaining[front] = False
        current += 1
    return fronts


def _ordered_scores(coords, orders):
    scores = np.empty(len(coords), dtype=float)
    for indices, order in orders:
        _require(set(indices) == set(order) and len(order) == len(indices), "FULL_U_ORDER_REQUIRED")
        scores[np.asarray(order, dtype=int)] = -np.arange(1, len(order) + 1)
    return scores


def base_rules(frame):
    """Eight frozen scientific rules and two diagnostic-only sanity panels."""
    c = coordinates(frame)
    risk3 = c[["VOL_RISK", "DOWNSIDE_RISK", "DD_RISK"]].mean(axis=1)
    risk4 = c[["VOL_RISK", "DOWNSIDE_RISK", "DD_RISK", "ILLIQ_RISK"]].mean(axis=1)
    values = (c.ALPHA-c.VOL_RISK, c.ALPHA-c.DOWNSIDE_RISK, c.ALPHA-c.DD_RISK,
              c.ALPHA-risk3, c.ALPHA-risk4, c.TREND-risk3, c.TREND-risk4)
    panels = {cid: _panel(c, cid, value) for cid, value in zip(BASE_ROLES[:7], values)}
    fronts, orders = np.empty(len(c), dtype=np.int64), []
    for _, indices in c.groupby("signal_date", sort=False).groups.items():
        g = c.loc[indices]
        good = g[["ALPHA", "VOL_RISK", "DOWNSIDE_RISK", "DD_RISK", "ILLIQ_RISK"]].to_numpy(float)
        good[:, 1:] *= -1
        fronts[indices] = pareto_fronts(good)
        pool = g.loc[g.raw_rank.le(40)].sort_values(["realized_vol_20d", "raw_rank", "security_uid"], kind="stable")
        tail = g.loc[g.raw_rank.gt(40)].sort_values(["raw_rank", "security_uid"], kind="stable")
        orders.append((indices, list(pool.index) + list(tail.index)))
    pareto = c.copy()
    pareto["pareto_front"] = fronts
    panels[BASE_ROLES[7]] = _panel(pareto, BASE_ROLES[7], -fronts)
    panels[SANITY_ROLES[0]] = _panel(c, SANITY_ROLES[0], _ordered_scores(c, orders))
    panels[SANITY_ROLES[0]].attrs["score_meaning"] = "negative full-U selection ordinal; minimum realized_vol_20d only within Raw40"
    raw = _panel(c, SANITY_ROLES[1], c.raw_score)
    _require(np.array_equal(raw["rank"].to_numpy(), raw.raw_rank.to_numpy()), "RAW_SANITY_MUST_BE_EXACT")
    panels[SANITY_ROLES[1]] = raw
    return panels


def risk_boundary_greedy(frame, covariance, covariance_uids, candidate_id="C11_B_DIAG"):
    """Retain Raw1-10; greedily fill ten memberships using supplied full-U risk."""
    _require(candidate_id in RISK_ROLES, "FROZEN_RISK_ROLE_REQUIRED")
    c = coordinates(frame)
    _require(c.signal_date.nunique() == 1, "SINGLE_DECISION_RISK_STATE_REQUIRED")
    uids = list(covariance_uids)
    _require(all(isinstance(u, str) and bool(u.strip()) for u in uids), "NONEMPTY_COVARIANCE_UID_REQUIRED")
    _require(len(uids) == len(c) and len(set(uids)) == len(uids)
             and set(uids) == set(c.security_uid), "EXACT_FULL_U_COVARIANCE_UIDS_REQUIRED")
    matrix = np.asarray(covariance, dtype=float)
    _require(matrix.shape == (len(c), len(c)) and np.isfinite(matrix).all(), "FINITE_FULL_U_COVARIANCE_REQUIRED")
    scale = max(float(np.max(np.abs(matrix))), 1e-12)
    _require(np.allclose(matrix, matrix.T, rtol=0, atol=1e-10*scale), "SYMMETRIC_COVARIANCE_REQUIRED")
    eigenvalues = np.linalg.eigvalsh(matrix)
    _require(np.isfinite(eigenvalues).all() and eigenvalues.min() >= -1e-10*scale, "PSD_COVARIANCE_REQUIRED_NO_REPAIR")
    positions = {uid: index for index, uid in enumerate(uids)}
    order = [positions[uid] for uid in c.security_uid]
    matrix = matrix[np.ix_(order, order)]
    pool = c.loc[c.raw_rank.le(40)].sort_values(["raw_rank", "security_uid"], kind="stable")
    selected = list(pool.loc[pool.raw_rank.le(10)].index)
    remaining = list(pool.loc[pool.raw_rank.gt(10)].index)
    alpha = pd.Series(_pct(pool.raw_score), index=pool.index)
    trace = []
    for step in range(10):
        n = len(selected)
        total = float(matrix[np.ix_(selected, selected)].sum())
        _require(np.isfinite(total), "FINITE_SET_VARIANCE_REQUIRED")
        before = float(np.sqrt(max(total/n**2, 0.)))
        after = np.sqrt(np.maximum((total + 2*matrix[np.ix_(remaining, selected)].sum(1)
                                   + np.diag(matrix)[remaining])/(n+1)**2, 0.))
        marginal = after - before
        _require(np.isfinite(marginal).all(), "FINITE_MARGINAL_STD_REQUIRED")
        alpha_pct, risk_pct = _pct(alpha.loc[remaining]), _pct(marginal)
        utility = alpha_pct - risk_pct
        candidates = pd.DataFrame({"position": remaining, "utility": utility,
                                   "raw_rank": c.loc[remaining, "raw_rank"].to_numpy(),
                                   "security_uid": c.loc[remaining, "security_uid"].to_numpy()})
        chosen = int(candidates.sort_values(["utility", "raw_rank", "security_uid"],
                                           ascending=[False, True, True], kind="stable").position.iloc[0])
        trace.append(dict(step=step+1, chosen_uid=c.loc[chosen, "security_uid"],
                          portfolio_std_before=before, candidates=[dict(security_uid=c.loc[i, "security_uid"],
                          raw_rank=float(c.loc[i, "raw_rank"]), alpha_percentile=float(a),
                          marginal_std_delta=float(m), marginal_risk_percentile=float(r), utility=float(u))
                          for i,a,m,r,u in zip(remaining,alpha_pct,marginal,risk_pct,utility)]))
        selected.append(chosen)
        remaining.remove(chosen)
    _require(len(selected) == 20 and len(set(selected)) == 20, "EXACT_UNIQUE_TOP20_REQUIRED")
    tail = c.loc[~c.index.isin(selected)].sort_values(["raw_rank", "security_uid"], kind="stable").index.tolist()
    panel = _panel(c, candidate_id, _ordered_scores(c, [(c.index, selected + tail)]))
    panel.attrs.update(greedy_trace=trace, score_meaning="negative selection ordinal; greedy utilities are step-local diagnostics",
                       covariance_input_authority="CALLER_SUPPLIED_FROZEN_FULL_U_STATE; no estimation here",
                       portfolio_std_selected=float(np.sqrt(max(matrix[np.ix_(selected, selected)].sum()/400, 0.))),
                       portfolio_std_raw_top20=float(np.sqrt(max(matrix[np.ix_(pool.index[:20], pool.index[:20])].sum()/400, 0.))))
    return panel
