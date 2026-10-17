"""C12 label-free boundary geometry and a Raw-anchored matching adapter.

The existing FF12 owner uses scipy.optimize.linear_sum_assignment; its forced
exits/account semantics cannot be used here. This thin adapter keeps that solver,
adds optional dummy assignments and exact dyadic integer costs with lex tie bits.
No labels, fit, risk estimation, provider, holdings or execution are consumed.
"""
from __future__ import annotations
import hashlib
import json
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scripts.research.a2.training.stateful_inputs import FEATURES as BASE32

RAW_KEYS = ("signal_date", "security_uid", "raw_rank")
PAIR_KEYS = ("signal_date", "challenger_uid", "incumbent_uid", "challenger_raw_rank", "incumbent_raw_rank")
RAW_FEATURES = ("raw_rank", "raw_score", "raw_rank_change", "raw_score_change",
                "raw_rank_change_missing", "raw_score_change_missing")
ROLES = ("C12_P1_LOGIT", "C12_P2_RIDGE", "C12_P3_HUBER", "C12_P4_HGB", "C12_P5_XGB",
         "C12_P6_CAT", "C12_P7_MLP", "C12_P8_MULTITASK_MLP", "C12_P9_QUANTILE_HGB")
TIE_POLICY = "exact maximum total; predicted edge descending, challenger Raw rank, incumbent Raw rank, challenger UID, incumbent UID"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _clock(values):
    clock = pd.DatetimeIndex(pd.to_datetime(values))
    _require(not clock.hasnans and clock.tz is None and (clock == clock.normalize()).all()
             and (clock < pd.Timestamp("2026-01-01")).all(), "PRE2026_NORMALIZED_CLOCK_REQUIRED")
    return clock


def _raw(raw, with_score=False):
    columns = (*RAW_KEYS, "raw_score") if with_score else RAW_KEYS
    _require(isinstance(raw, pd.DataFrame) and len(raw) > 0 and set(columns).issubset(raw), "RAW_KEYS_REQUIRED")
    out = raw.loc[:, list(columns)].copy().reset_index(drop=True)
    out["signal_date"] = _clock(out.signal_date)
    _require(out.security_uid.map(lambda x: isinstance(x, str) and bool(x.strip())).all(), "UID_REQUIRED")
    _require(not out.duplicated(["signal_date", "security_uid"]).any(), "DUPLICATE_RAW_UID")
    _require(np.isfinite(out.raw_rank.to_numpy(float)).all(), "FINITE_RAW_RANK_REQUIRED")
    for _, day in out.groupby("signal_date", sort=False):
        _require(len(day) >= 40 and np.array_equal(np.sort(day.raw_rank), np.arange(1, len(day)+1)), "FULL_U_ORDINAL_TOP40_REQUIRED")
        if with_score:
            values = day.sort_values("raw_rank").raw_score.to_numpy(float)
            _require(np.isfinite(values).all() and (np.diff(values) <= 0).all(), "RAW_SCORE_RANK_BINDING_REQUIRED")
    out["raw_rank"] = out.raw_rank.astype(np.int64)
    if with_score: out["raw_score"] = out.raw_score.astype(float)
    return out.sort_values(["signal_date", "raw_rank", "security_uid"], kind="stable").reset_index(drop=True)


def _pairs(pairs):
    _require(isinstance(pairs, pd.DataFrame) and len(pairs) > 0 and set(PAIR_KEYS).issubset(pairs), "PAIR_KEYS_REQUIRED")
    out = pairs.loc[:, list(PAIR_KEYS)].copy().reset_index(drop=True)
    out["signal_date"] = _clock(out.signal_date)
    for column in ("challenger_uid", "incumbent_uid"):
        _require(out[column].map(lambda x: isinstance(x, str) and bool(x.strip())).all(), "PAIR_UID_REQUIRED")
    _require(not out.duplicated(["signal_date", "challenger_uid", "incumbent_uid"]).any(), "DUPLICATE_PAIR")
    for _, day in out.groupby("signal_date", sort=False):
        ch = day[["challenger_uid", "challenger_raw_rank"]].drop_duplicates()
        inc = day[["incumbent_uid", "incumbent_raw_rank"]].drop_duplicates()
        _require(len(day) == 200 and len(ch) == 20 and len(inc) == 10
                 and ch.challenger_uid.nunique() == 20 and inc.incumbent_uid.nunique() == 10
                 and set(ch.challenger_raw_rank) == set(range(21, 41))
                 and set(inc.incumbent_raw_rank) == set(range(11, 21))
                 and set(ch.challenger_uid).isdisjoint(inc.incumbent_uid), "EXACT_200_BOUNDARY_PAIRS_REQUIRED")
    return out


def pair_key_sha256(pairs):
    """Canonical geometry-only bytes: rank/date/UID; no feature or y values."""
    out = _pairs(pairs).sort_values(list(PAIR_KEYS), kind="stable")
    digest = hashlib.sha256()
    for date, challenger, incumbent, cr, ir in out.itertuples(index=False, name=None):
        digest.update((json.dumps([date.isoformat(), challenger, incumbent, int(cr), int(ir)],
                                  ensure_ascii=True, separators=(",", ":"))+"\n").encode("utf-8"))
    return digest.hexdigest()


def geometry(raw):
    """Complete fixed 20 challengers x 10 incumbents before labels are opened."""
    r = _raw(raw)
    ch = r.loc[r.raw_rank.between(21, 40)].rename(columns={"security_uid": "challenger_uid", "raw_rank": "challenger_raw_rank"})
    inc = r.loc[r.raw_rank.between(11, 20)].rename(columns={"security_uid": "incumbent_uid", "raw_rank": "incumbent_raw_rank"})
    pairs = ch.merge(inc, on="signal_date", how="inner", validate="many_to_many")[list(PAIR_KEYS)]
    pairs = pairs.sort_values(["signal_date", "challenger_raw_rank", "incumbent_raw_rank", "challenger_uid", "incumbent_uid"], kind="stable").reset_index(drop=True)
    pairs.attrs.update(pair_key_sha256=pair_key_sha256(pairs), pair_construction_label_free=True,
                       caller_must_freeze_before_labels=True,
                       target_values_read=0, pair_policy="RAW21_40_X_RAW11_20_EXACT_200")
    return pairs


def add_history(raw, calendar):
    """UID-local previous legal session; missing changes are zero plus two flags."""
    keys = _raw(raw, with_score=True)
    cal = _clock(calendar)
    _require(len(cal) > 0 and cal.is_unique and cal.is_monotonic_increasing, "ORDERED_UNIQUE_CALENDAR_REQUIRED")
    positions = pd.Series(np.arange(len(cal)), index=cal)
    _require(keys.signal_date.isin(cal).all(), "RAW_DATE_OUTSIDE_CALENDAR")
    keys["_session"] = keys.signal_date.map(positions)
    grouped = keys.groupby("security_uid", sort=False)
    legal = keys._session.eq(grouped._session.shift(1)+1)
    result = raw.copy()
    columns = []
    for field in ("raw_rank", "raw_score"):
        change = field+"_change"
        keys[change] = (keys[field]-grouped[field].shift(1)).where(legal, 0.)
        keys[change+"_missing"] = (~legal).astype(float)
        columns += [change, change+"_missing"]
    _require(not set(columns).intersection(result), "HISTORY_ALREADY_PRESENT_NO_OVERWRITE")
    result["signal_date"] = _clock(result.signal_date)
    result = result.merge(keys[["signal_date", "security_uid", *columns]], on=["signal_date", "security_uid"], how="left", validate="one_to_one")
    result.attrs.update(history_policy="PREVIOUS_LEGAL_CALENDAR_SESSION_SAME_UID_ONLY", history_missing_encoding="ZERO_PLUS_TWO_FLAGS")
    return result


def pair_weights(pairs):
    """Each date sums to one; each challenger to 1/20; each partner to 1/200."""
    p = _pairs(pairs)
    challengers = p.groupby("signal_date").challenger_uid.transform("nunique").to_numpy(float)
    partners = p.groupby(["signal_date", "challenger_uid"]).incumbent_uid.transform("size").to_numpy(float)
    return 1./(challengers*partners)


def feature_order(base_features):
    base = tuple(base_features)
    _require(base == BASE32, "EXACT_BASE32_ORDER_REQUIRED")
    return tuple(side+"__"+field for side in ("challenger", "incumbent", "delta") for field in (*base, *RAW_FEATURES))


def pair_features(raw, pairs, base_features):
    """Three fixed blocks; no fitting, label join, history search or row removal."""
    base_features = tuple(base_features)
    names = feature_order(base_features)
    fields = (*base_features, *RAW_FEATURES)
    _raw(raw, with_score=True)
    p = _pairs(pairs)
    _require(pair_key_sha256(geometry(raw)) == pair_key_sha256(p), "PAIR_GEOMETRY_RAW_BINDING_MISMATCH")
    _require(set(fields).issubset(raw), "PAIR_FEATURE_COLUMNS_REQUIRED")
    source = raw[["signal_date", "security_uid", *fields]].copy()
    source["signal_date"] = _clock(source.signal_date)
    _require(np.isfinite(source[list(fields)].to_numpy(float)).all(), "FINITE_PAIR_FEATURES_NO_DROP")
    _require(source.raw_rank_change_missing.isin([0., 1.]).all() and source.raw_score_change_missing.isin([0., 1.]).all(), "BINARY_HISTORY_MISSING_FLAGS_REQUIRED")
    for field in ("raw_rank", "raw_score"):
        _require(source.loc[source[field+"_change_missing"].eq(1), field+"_change"].eq(0).all(), "MISSING_HISTORY_MUST_ENCODE_ZERO")
    blocks = []
    for uid in ("challenger_uid", "incumbent_uid"):
        side = p[["signal_date", uid]].merge(source, left_on=["signal_date", uid], right_on=["signal_date", "security_uid"], how="left", validate="many_to_one")
        blocks.append(side[list(fields)].to_numpy(float))
    matrix = np.column_stack([blocks[0], blocks[1], blocks[0]-blocks[1]])
    _require(np.isfinite(matrix).all() and len(matrix) == len(p), "FULL_PAIR_FEATURE_BINDING_REQUIRED")
    out = pd.concat([p, pd.DataFrame(matrix, columns=names)], axis=1)
    out.attrs.update(feature_order=list(names), feature_order_sha256=hashlib.sha256(json.dumps(names, separators=(",", ":")).encode()).hexdigest(), pair_key_sha256=pair_key_sha256(p), target_values_read=0)
    return out


def _exact_assignment(weights):
    """Rectangular assignment: SciPy for safely bounded ints; exact fallback.

    SciPy's double costs can lose a native-float ULP after summation. The tiny
    10x30 shortest augmenting-path fallback keeps arbitrary-precision integers.
    It implements the same assignment objective, not a second policy engine.
    """
    n, m = len(weights), len(weights[0])
    if max(max(row) for row in weights)*m <= 2**50:
        rows, cols = linear_sum_assignment(np.asarray(weights, dtype=float), maximize=True)
        return list(zip(rows.tolist(), cols.tolist()))
    u, v, owner, predecessor = [0]*(n+1), [0]*(m+1), [0]*(m+1), [0]*(m+1)
    for row in range(1, n+1):
        owner[0], column = row, 0
        best, used = [None]*(m+1), [False]*(m+1)
        while True:
            used[column] = True
            active, delta, next_column = owner[column], None, 0
            for j in range(1, m+1):
                if used[j]: continue
                cost = -weights[active-1][j-1]-u[active]-v[j]
                if best[j] is None or cost < best[j]: best[j], predecessor[j] = cost, column
                if delta is None or best[j] < delta: delta, next_column = best[j], j
            for j in range(m+1):
                if used[j]: u[owner[j]] += delta; v[j] -= delta
                elif best[j] is not None: best[j] -= delta
            column = next_column
            if owner[column] == 0: break
        while column:
            previous = predecessor[column]
            owner[column], column = owner[previous], previous
    return [(owner[j]-1, j-1) for j in range(1, m+1) if owner[j]]


def maximum_weight_matching(pairs, weights, eligible=None):
    """Exact dyadic main total plus lex bits whose whole sum is < one main unit."""
    p = _pairs(pairs)
    _require(p.signal_date.nunique() == 1, "SINGLE_DATE_MATCH_REQUIRED")
    values = np.asarray(weights, dtype=float)
    _require(values.shape == (len(p),) and np.isfinite(values).all(), "FINITE_PAIR_WEIGHTS_REQUIRED")
    ok = np.ones(len(p), bool) if eligible is None else np.asarray(eligible, dtype=bool).copy()
    _require(ok.shape == values.shape, "EDGE_ELIGIBILITY_SHAPE_REQUIRED")
    ok &= values > 0
    if not ok.any():
        empty = p.iloc[:0].assign(predicted_edge=pd.Series(dtype=float))
        empty.attrs.update(tie_policy=TIE_POLICY, exact_weight_arithmetic="INTEGER_DYADIC_PRIMARY_PLUS_BOUNDED_LEX_BITS")
        return empty
    ch = p[["challenger_uid", "challenger_raw_rank"]].drop_duplicates().sort_values(["challenger_raw_rank", "challenger_uid"])
    inc = p[["incumbent_uid", "incumbent_raw_rank"]].drop_duplicates().sort_values(["incumbent_raw_rank", "incumbent_uid"])
    ci, ii = {u:i for i,u in enumerate(ch.challenger_uid)}, {u:i for i,u in enumerate(inc.incumbent_uid)}
    loc = [(ii[i], ci[c]) for c,i in zip(p.challenger_uid, p.incumbent_uid)]
    priority = p.assign(_weight=values, _position=np.arange(len(p))).loc[ok].sort_values(
        ["_weight", "challenger_raw_rank", "incumbent_raw_rank", "challenger_uid", "incumbent_uid"],
        ascending=[False, True, True, True, True], kind="stable")
    positions = priority._position.tolist()
    ratios = {index: float(values[index]).as_integer_ratio() for index in positions}
    denominator = max(d for _,d in ratios.values())
    count, encoded, lookup = len(positions), [[0]*30 for _ in range(10)], {}
    for precedence, index in enumerate(positions):
        numerator, divisor = ratios[index]
        i,j = loc[index]
        encoded[i][j] = (numerator*(denominator//divisor) << count) + (1 << (count-precedence-1))
        lookup[i,j] = index
    chosen_set = {lookup[i,j] for i,j in _exact_assignment(encoded) if (i,j) in lookup}
    chosen = [index for index in positions if index in chosen_set]
    matched = p.iloc[chosen].copy()
    matched["predicted_edge"] = values[chosen]
    _require(len(matched) <= 10 and matched.challenger_uid.is_unique and matched.incumbent_uid.is_unique, "ONE_TO_ONE_REQUIRED")
    matched.attrs.update(tie_policy=TIE_POLICY, exact_weight_arithmetic="INTEGER_DYADIC_PRIMARY_PLUS_BOUNDED_LEX_BITS")
    return matched.reset_index(drop=True)

def resolve(raw, pairs, prediction, role, q10=None):
    """Full-U ordinal output represents anchored memberships, never full rerank."""
    _require(role in ROLES, "FROZEN_C12_ROLE_REQUIRED")
    r, p = _raw(raw, with_score=True), _pairs(pairs)
    _require(r.signal_date.nunique() == 1 and p.signal_date.nunique() == 1, "SINGLE_DATE_RESOLVER_REQUIRED")
    _require(pair_key_sha256(geometry(r)) == pair_key_sha256(p), "PAIR_GEOMETRY_RAW_BINDING_MISMATCH")
    values = np.asarray(prediction, dtype=float)
    _require(values.shape == (len(p),) and np.isfinite(values).all(), "FINITE_200_PREDICTIONS_REQUIRED")
    eligible = values > 0
    if role == ROLES[0]:
        _require(((values >= 0)&(values <= 1)).all(), "LOGIT_PROBABILITY_REQUIRED")
        values = values-.5
        eligible = values > 0
    if role == ROLES[8]:
        lower = np.asarray(q10, dtype=float)
        _require(lower.shape == values.shape and np.isfinite(lower).all(), "FINITE_Q10_REQUIRED")
        eligible &= lower > 0
    matched = maximum_weight_matching(p, values, eligible)
    replacements = dict(zip(matched.incumbent_uid, matched.challenger_uid))
    top = [replacements.get(u,u) for u in r.loc[r.raw_rank.le(20), "security_uid"]]
    _require(len(top) == len(set(top)) == 20 and set(r.loc[r.raw_rank.le(10), "security_uid"]).issubset(top), "EXACT_ANCHORED_TOP20_REQUIRED")
    order = top+[u for u in r.security_uid if u not in set(top)]
    ranks = {uid:index+1 for index,uid in enumerate(order)}
    out = r.copy()
    out["rank"] = out.security_uid.map(ranks).astype(np.int64)
    out["score"] = -out["rank"].astype(float)
    out["candidate_id"] = role
    out["selected"] = out["rank"].le(20)
    out = out.sort_values(["signal_date", "security_uid"], kind="stable").reset_index(drop=True)
    out.attrs.update(replacement_count=len(matched), matched_pairs=matched.to_dict("records"),
                     pair_key_sha256=pair_key_sha256(p), tie_policy=TIE_POLICY, fits=0,
                     production_promotion_allowed=False, full_rerank=False,
                     score_meaning="negative anchored membership ordinal; not a standalone stock prediction")
    return out





