"""FAST3 R28.3C frozen event-conditioned path and exit-geometry audit.

This is retrospective outcome attribution only.  It reads the R28.3B frozen
cohort/scores and canonical SOXX bars, and never loads a model or produces a
new score.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
B_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_r28_3b_soxx_natural_baseline.py"
OUT = RESULTS / "frozen" / "fast3" / "r28_3c_frozen_event_conditioned_path_audit_20260809_r2"
HORIZON = pd.Timedelta(hours=24)
LADDER = (0.0025, 0.005, 0.0075, 0.01)
POST_WINDOWS = (5, 15, 30, 60, 120, 240)
CONTINUATION_LEVELS = (0.0125, 0.015, 0.02)
SCORE_BINS = (("TOP_1PCT", .00, .01, 9), ("PCT_1_TO_2", .01, .02, 8),
              ("PCT_2_TO_5", .02, .05, 7), ("PCT_5_TO_10", .05, .10, 6),
              ("PCT_10_TO_20", .10, .20, 5), ("PCT_20_TO_40", .20, .40, 4),
              ("PCT_40_TO_60", .40, .60, 3), ("PCT_60_TO_80", .60, .80, 2),
              ("BOTTOM_20PCT", .80, 1.00, 1))
FAST_TOUCH_MINUTES = 60
MEDIUM_TOUCH_MINUTES = 240
RANDOM_SEED = 28303
MATCHED_EVENT_RUN_COUNT = 1000


class AuditStop(RuntimeError):
    pass


def load_b():
    spec = importlib.util.spec_from_file_location("fast3_r28_3b_for_r28_3c", B_SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def score_ranked(x: pd.DataFrame, score: str) -> pd.DataFrame:
    out = x.copy()
    order = out.sort_values([score, "timestamp"], ascending=[False, True], kind="mergesort").index
    out["score_rank_pct"] = np.nan
    out.loc[order, "score_rank_pct"] = np.arange(1, len(out) + 1) / len(out)
    return out


def bucketize(x: pd.DataFrame, score: str) -> pd.DataFrame:
    out = score_ranked(x, score)
    out["score_bucket"] = "UNASSIGNED"
    out["bucket_ordinal"] = 0
    for name, lower, upper, ordinal in SCORE_BINS:
        mask = (out.score_rank_pct > lower) & (out.score_rank_pct <= upper)
        out.loc[mask, "score_bucket"] = name
        out.loc[mask, "bucket_ordinal"] = ordinal
    if out.score_bucket.eq("UNASSIGNED").any():
        raise AuditStop("STOP_SCORE_BUCKET_ASSIGNMENT_FAILURE")
    return out


def fixed_bucket_parts(x: pd.DataFrame):
    """Pre-registered cumulative heads plus disjoint lower score ranges."""
    definitions = (("TOP_1PCT", 9, x.score_rank_pct <= .01), ("TOP_2PCT", 8, x.score_rank_pct <= .02),
                   ("TOP_5PCT", 7, x.score_rank_pct <= .05), ("TOP_10PCT", 6, x.score_rank_pct <= .10),
                   ("TOP_20PCT", 5, x.score_rank_pct <= .20), ("PCT_20_TO_40", 4, (x.score_rank_pct > .20) & (x.score_rank_pct <= .40)),
                   ("PCT_40_TO_60", 3, (x.score_rank_pct > .40) & (x.score_rank_pct <= .60)),
                   ("PCT_60_TO_80", 2, (x.score_rank_pct > .60) & (x.score_rank_pct <= .80)),
                   ("BOTTOM_20PCT", 1, x.score_rank_pct > .80))
    return [(name, ordinal, x.loc[mask]) for name, ordinal, mask in definitions]


def q(series: pd.Series, probability: float) -> float:
    return float(series.quantile(probability)) if len(series) else np.nan


def threshold_label(level: float) -> str:
    return f"{level * 100:.2f}".replace(".", "P")


def build_path_geometry(b, cohort: pd.DataFrame, raw: pd.DataFrame, r1) -> pd.DataFrame:
    """Build all pre-touch and post-touch observations from canonical one-minute bars."""
    base = b.geometry(cohort, raw, r1)
    ns = raw.timestamp_utc.astype("int64").to_numpy()
    entry_i = np.searchsorted(ns, pd.to_datetime(base.entry_timestamp, utc=True).astype("int64").to_numpy())
    horizon_i = np.searchsorted(ns, pd.to_datetime(base.horizon_timestamp, utc=True).astype("int64").to_numpy())
    if (entry_i >= len(raw)).any() or (horizon_i >= len(raw)).any():
        raise AuditStop("STOP_CANONICAL_PATH_INDEX_FAILURE")
    high_tree, high_size = r1.build_tree(raw.high.to_numpy(float), True)
    low_tree, low_size = r1.build_tree(raw.low.to_numpy(float), False)
    entry = base.reference_price.to_numpy(float)
    result = base.copy()
    for level in LADDER:
        tag = threshold_label(level)
        up = np.fromiter((r1.first_cross(high_tree, high_size, int(a), int(z), float(p * (1 + level)), True)
                          for a, z, p in zip(entry_i, horizon_i, entry)), dtype=int, count=len(result))
        down = np.fromiter((r1.first_cross(low_tree, low_size, int(a), int(z), float(p * (1 - level)), False)
                            for a, z, p in zip(entry_i, horizon_i, entry)), dtype=int, count=len(result))
        result[f"up_touch_i_{tag}"] = up
        result[f"down_touch_i_{tag}"] = down
        result[f"time_to_up_{tag}_minutes"] = np.where(up >= 0, (ns[np.maximum(up, 0)] - ns[entry_i]) / 60_000_000_000, np.nan)
        result[f"time_to_down_{tag}_minutes"] = np.where(down >= 0, (ns[np.maximum(down, 0)] - ns[entry_i]) / 60_000_000_000, np.nan)
    up1, down1 = result.up_touch_i_1P00.to_numpy(int), result.down_touch_i_1P00.to_numpy(int)
    expected = b.first_touch_labels(up1, down1)
    if not np.array_equal(expected, result.label.to_numpy(str)):
        raise AuditStop("STOP_FROZEN_LABEL_RECONCILIATION_FAILURE")
    result["entry_i"] = entry_i
    result["horizon_i"] = horizon_i
    return result


def attach_directional_observations(x: pd.DataFrame, raw: pd.DataFrame, b) -> pd.DataFrame:
    """Use actual frozen first-touch events only, with favorable direction normalized."""
    out = []
    ns = raw.timestamp_utc.astype("int64").to_numpy()
    close, high, low = (raw.close.to_numpy(float), raw.high.to_numpy(float), raw.low.to_numpy(float))
    high_ranges, low_ranges = b.sparse_extrema(high, True), b.sparse_extrema(low, False)
    for direction, score, label, sign in (("UP", "probability_up", "UP_FIRST", 1),
                                          ("DOWN", "probability_down", "DOWN_FIRST", -1)):
        part = bucketize(x, score)
        part["direction"] = direction
        part["frozen_score"] = part[score]
        part["is_actual_touch"] = part.label.eq(label)
        tag = "1P00"
        touch = part[f"{direction.lower()}_touch_i_{tag}"].to_numpy(int)
        part["touch_i"] = touch
        part["touch_timestamp"] = pd.Series(pd.NaT, index=part.index, dtype="datetime64[ns, UTC]")
        actual = part.is_actual_touch.to_numpy(bool)
        if np.any(actual):
            part.loc[actual, "touch_timestamp"] = pd.to_datetime(ns[touch[actual]], utc=True).to_numpy()
        part["time_to_touch_minutes"] = np.where(actual, (ns[np.maximum(touch, 0)] - ns[part.entry_i.to_numpy()]) / 60_000_000_000, np.nan)
        part["post_touch_mfe"] = np.nan
        part["post_touch_mae"] = np.nan
        part["terminal_favorable_return"] = np.nan
        part["touch_to_horizon_giveback"] = np.nan
        part["full_giveback"] = pd.NA
        part["returned_to_entry"] = pd.NA
        for minute in POST_WINDOWS:
            part[f"post_touch_{minute}m_favorable_return"] = np.nan
            part[f"post_touch_{minute}m_available"] = False
        for level in CONTINUATION_LEVELS:
            part[f"post_touch_reach_{threshold_label(level)}"] = pd.NA
        positions = np.flatnonzero(actual)
        if len(positions):
            index = part.index.to_numpy()
            touch_actual, end_actual = touch[positions], part.horizon_i.to_numpy(int)[positions]
            entry_actual, touch_price = part.reference_price.to_numpy(float)[positions], close[touch_actual]
            max_high = b.query_extrema(high_ranges, touch_actual, end_actual, True)
            min_low = b.query_extrema(low_ranges, touch_actual, end_actual, False)
            high_return, low_return = (max_high / touch_price - 1) * sign, (min_low / touch_price - 1) * sign
            mfe, mae = np.maximum(high_return, low_return), np.minimum(high_return, low_return)
            terminal = (close[end_actual] / touch_price - 1) * sign
            event_index = index[positions]
            part.loc[event_index, ["post_touch_mfe", "post_touch_mae", "terminal_favorable_return", "touch_to_horizon_giveback"]] = np.column_stack((mfe, mae, terminal, mfe - terminal))
            part.loc[event_index, "full_giveback"] = terminal <= 0
            part.loc[event_index, "returned_to_entry"] = min_low <= entry_actual if sign == 1 else max_high >= entry_actual
            for level in CONTINUATION_LEVELS:
                reached = max_high >= entry_actual * (1 + level) if sign == 1 else min_low <= entry_actual * (1 - level)
                part.loc[event_index, f"post_touch_reach_{threshold_label(level)}"] = reached
            for minute in POST_WINDOWS:
                price_i = np.searchsorted(ns, ns[touch_actual] + minute * 60_000_000_000)
                available = (price_i < len(ns)) & (ns[np.minimum(price_i, len(ns) - 1)] == ns[touch_actual] + minute * 60_000_000_000) & (price_i <= end_actual)
                if np.any(available):
                    available_index = event_index[available]
                    part.loc[available_index, f"post_touch_{minute}m_favorable_return"] = (close[price_i[available]] / touch_price[available] - 1) * sign
                    part.loc[available_index, f"post_touch_{minute}m_available"] = True
        out.append(part)
    return pd.concat(out, ignore_index=True)


def pre_touch_ladder(x: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows, correlations = [], {}
    for direction in ("UP", "DOWN"):
        head = x.loc[x.direction.eq(direction)]
        score = head.frozen_score
        correlations[direction] = {}
        for level in LADDER:
            tag = threshold_label(level)
            time = head[f"time_to_{direction.lower()}_{tag}_minutes"]
            correlations[direction][tag] = float(score.corr(-time, method="spearman"))
            for bucket, ordinal, part in fixed_bucket_parts(head):
                value = part[f"time_to_{direction.lower()}_{tag}_minutes"]
                hit = value.notna()
                rows.append({"direction": direction, "score_bucket": bucket, "bucket_ordinal": ordinal, "threshold": level,
                             "candidate_count": len(part), "hit_count": int(hit.sum()), "hit_rate": float(hit.mean()),
                             "median_time_to_hit": float(value.median()), "mean_time_to_hit": float(value.mean()),
                             "p10_time_to_hit": q(value, .10), "p25_time_to_hit": q(value, .25), "p75_time_to_hit": q(value, .75), "p90_time_to_hit": q(value, .90),
                             "not_hit_or_censored_count": int((~hit).sum())})
    return pd.DataFrame(rows).sort_values(["direction", "bucket_ordinal", "threshold"], ascending=[True, False, True]), correlations


def post_touch_path(events: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows, correlations = [], {}
    for direction, head in events.groupby("direction", sort=True):
        correlations[direction] = {}
        for minute in POST_WINDOWS:
            col = f"post_touch_{minute}m_favorable_return"
            correlations[direction][minute] = float(head.frozen_score.corr(head[col], method="spearman"))
            for bucket, ordinal, part in fixed_bucket_parts(head):
                values = part[col].dropna()
                rows.append({"direction": direction, "score_bucket": bucket, "bucket_ordinal": ordinal, "post_touch_horizon_minutes": minute,
                             "touch_count": len(part), "available_count": len(values), "unavailable_count": len(part) - len(values),
                             "mean_post_touch_favorable_return": float(values.mean()), "median_post_touch_favorable_return": float(values.median()),
                             "continuation_rate": float((values > 0).mean()), "reversal_rate": float((values < 0).mean()), "flat_rate": float((values == 0).mean()),
                             "p10": q(values, .10), "p25": q(values, .25), "p75": q(values, .75), "p90": q(values, .90)})
        correlations[direction]["post_touch_mfe"] = float(head.frozen_score.corr(head.post_touch_mfe, method="spearman"))
        correlations[direction]["negative_giveback"] = float(head.frozen_score.corr(-head.touch_to_horizon_giveback, method="spearman"))
    return pd.DataFrame(rows).sort_values(["direction", "bucket_ordinal", "post_touch_horizon_minutes"], ascending=[True, False, True]), correlations


def giveback_and_continuation(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    geometry, continuation = [], []
    for direction, head in events.groupby("direction", sort=True):
      for bucket, ordinal, part in fixed_bucket_parts(head):
        geometry.append({"direction": direction, "score_bucket": bucket, "bucket_ordinal": ordinal, "touch_count": len(part),
                         "mean_post_touch_max_favorable_excursion": float(part.post_touch_mfe.mean()), "median_post_touch_max_favorable_excursion": float(part.post_touch_mfe.median()),
                         "mean_post_touch_max_adverse_excursion": float(part.post_touch_mae.mean()), "median_post_touch_max_adverse_excursion": float(part.post_touch_mae.median()),
                         "mean_touch_to_horizon_giveback": float(part.touch_to_horizon_giveback.mean()), "median_touch_to_horizon_giveback": float(part.touch_to_horizon_giveback.median()),
                         "full_giveback_rate": float(part.full_giveback.astype(bool).mean()), "returned_to_entry_rate": float(part.returned_to_entry.astype(bool).mean())})
        row = {"direction": direction, "score_bucket": bucket, "bucket_ordinal": ordinal, "touch_count": len(part)}
        for level in CONTINUATION_LEVELS:
            row[f"post_touch_reach_{threshold_label(level)}_rate"] = float(part[f"post_touch_reach_{threshold_label(level)}"].astype(bool).mean())
        continuation.append(row)
    return pd.DataFrame(geometry), pd.DataFrame(continuation)


def fast_slow(events: pd.DataFrame) -> pd.DataFrame:
    x = events.copy()
    x["touch_speed_group"] = np.select([x.time_to_touch_minutes <= FAST_TOUCH_MINUTES,
                                         x.time_to_touch_minutes <= MEDIUM_TOUCH_MINUTES], ["FAST_TOUCH", "MEDIUM_TOUCH"], default="SLOW_TOUCH")
    rows = []
    for (direction, group), part in x.groupby(["direction", "touch_speed_group"], sort=False):
        row = {"direction": direction, "touch_speed_group": group, "count": len(part), "median_time_to_touch": float(part.time_to_touch_minutes.median()),
               "full_giveback_rate": float(part.full_giveback.astype(bool).mean()), "returned_to_entry_rate": float(part.returned_to_entry.astype(bool).mean())}
        for minute in (15, 30, 60, 120): row[f"post_touch_{minute}m_return"] = float(part[f"post_touch_{minute}m_favorable_return"].mean())
        for level in CONTINUATION_LEVELS: row[f"reach_{threshold_label(level)}_rate"] = float(part[f"post_touch_reach_{threshold_label(level)}"].astype(bool).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def metrics(part: pd.DataFrame) -> dict:
    row = {"count": len(part), "median_time_to_touch": float(part.time_to_touch_minutes.median()), "full_giveback_rate": float(part.full_giveback.astype(bool).mean()), "returned_to_entry_rate": float(part.returned_to_entry.astype(bool).mean()), "post_touch_max_favorable_excursion": float(part.post_touch_mfe.mean())}
    for minute in (15, 30, 60, 120): row[f"post_touch_{minute}m_return"] = float(part[f"post_touch_{minute}m_favorable_return"].mean())
    for level in CONTINUATION_LEVELS: row[f"reach_{threshold_label(level)}_rate"] = float(part[f"post_touch_reach_{threshold_label(level)}"].astype(bool).mean())
    return row


def top5_vs_natural(events: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows, summary = [], {}
    for direction, part in events.groupby("direction", sort=True):
        top = part.loc[part.score_rank_pct <= .05]
        natural = part
        top_metrics, natural_metrics = metrics(top), metrics(natural)
        rows.extend([{"direction": direction, "population": "FAST3_TOP5_TOUCHED", **top_metrics}, {"direction": direction, "population": f"ALL_SOXX_{direction}_FIRST", **natural_metrics}])
        summary[direction] = {"top5": top_metrics, "natural": natural_metrics}
    return pd.DataFrame(rows), summary


def add_match_keys(x: pd.DataFrame) -> pd.DataFrame:
    out = x.copy()
    local = pd.to_datetime(out.timestamp, utc=True).dt.tz_convert("America/New_York")
    out["calendar_month"] = local.dt.strftime("%Y-%m")
    out["weekday"] = local.dt.day_name()
    return out


def matched_comparison(events: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Fixed seed, same direction/month/weekday/session natural-event sampling."""
    events = add_match_keys(events)
    rows, summary = [], {}
    measures = ("median_time_to_touch", "post_touch_15m_return", "post_touch_30m_return", "post_touch_60m_return", "post_touch_120m_return", "full_giveback_rate", "returned_to_entry_rate", "reach_1P50_rate", "reach_2P00_rate")
    for direction, part in events.groupby("direction", sort=True):
        selected = part.loc[part.score_rank_pct <= .05].copy()
        # The natural-event population is intentionally inclusive of Top5.
        # A few frozen month/weekday/session strata contain no non-Top5 touch;
        # excluding those rows would silently drop treatment events and violate
        # the required same-stratum comparison.
        eligible = part.copy()
        pools = {key: group.index.to_numpy() for key, group in eligible.groupby(["calendar_month", "weekday", "session"], sort=False)}
        groups = [(key, group) for key, group in selected.groupby(["calendar_month", "weekday", "session"], sort=False)]
        if any(key not in pools or len(pools[key]) == 0 for key, _ in groups):
            raise AuditStop("STOP_MATCHED_EVENT_UNMATCHED")
        actual = metrics(selected)
        rng, simulated = np.random.default_rng(RANDOM_SEED), []
        replacement_count = 0
        for run in range(1, MATCHED_EVENT_RUN_COUNT + 1):
            indexes = []
            for key, group in groups:
                pool = pools[key]; replace = len(pool) < len(group)
                replacement_count += int(replace)
                indexes.extend(rng.choice(pool, size=len(group), replace=replace).tolist())
            sampled = eligible.loc[indexes]
            simulated.append({"run": run, **metrics(sampled)})
        sim = pd.DataFrame(simulated)
        for measure in measures:
            rows.append({"direction": direction, "metric": measure, "top5_value": actual[measure], "matched_mean": float(sim[measure].mean()), "matched_median": float(sim[measure].median()),
                         "top5_minus_matched_mean": float(actual[measure] - sim[measure].mean()), "top5_percentile": float((sim[measure] <= actual[measure]).mean()),
                         "random_seed": RANDOM_SEED, "matched_event_run_count": MATCHED_EVENT_RUN_COUNT, "replacement_strata_uses": replacement_count})
        summary[direction] = {"top5": actual, "matched_mean": sim.drop(columns="run").mean().to_dict(), "replacement_strata_uses": replacement_count,
                              "donor_population": "ALL_NATURAL_TOUCHED_EVENTS_INCLUSIVE_OF_TOP5"}
    return pd.DataFrame(rows), summary


def classify(top_natural: dict, matched: dict, post_rho: dict) -> tuple[str, str]:
    stronger, neutral_or_negative, high_giveback, matched_same = [], [], [], []
    for direction in ("UP", "DOWN"):
        top, natural, control = top_natural[direction]["top5"], top_natural[direction]["natural"], matched[direction]["matched_mean"]
        stronger.append(all(top[f"post_touch_{m}m_return"] > natural[f"post_touch_{m}m_return"] and top[f"post_touch_{m}m_return"] > control[f"post_touch_{m}m_return"] for m in (15, 30, 60, 120)))
        neutral_or_negative.append(all(top[f"post_touch_{m}m_return"] <= 0 for m in (15, 30, 60, 120)))
        high_giveback.append(top["full_giveback_rate"] >= .50 or top["returned_to_entry_rate"] >= .50)
        matched_same.append(all(abs(top[f"post_touch_{m}m_return"] - control[f"post_touch_{m}m_return"]) < .0005 for m in (15, 30, 60, 120)))
    score_continues = all(post_rho[d][m] > .05 for d in ("UP", "DOWN") for m in (30, 60, 120))
    if all(stronger) and score_continues: return "A_FAST_TOUCH_WITH_CONTINUATION_EDGE", "POST_TOUCH_CONTINUATION_MAY_CONTAIN_ECONOMIC_INFORMATION"
    if all(neutral_or_negative) and all(high_giveback): return "B_FAST_TOUCH_WITH_MEAN_REVERSION_OR_GIVEBACK", "EVENT_TOUCH_MAY_REQUIRE_SHORT_HORIZON_EXIT_RESEARCH"
    if all(matched_same) and not score_continues: return "C_TOUCH_SPEED_EDGE_ONLY_NO_POST_TOUCH_EDGE", "FAST3_IS_PRIMARILY_EVENT_TIMING_SIGNAL"
    return "D_MIXED_POST_TOUCH_GEOMETRY", "POST_TOUCH_GEOMETRY_REQUIRES_HUMAN_HYPOTHESIS_REVIEW"


def report(payload: dict) -> str:
    return "# FAST3 R28.3C — Frozen Event-Conditioned Path and Exit Geometry Audit\n\n" + "\n".join(f"{key}={value}" for key, value in payload.items() if not isinstance(value, (dict, list))) + "\n\nThis retrospective audit uses future path data only as outcomes; it was not used for selection, features, scores, or model inputs. No exit rule is proposed or changed.\n"


def run() -> dict:
    b = load_b()
    prior = json.loads((b.OUT / "R28_3B_SUMMARY.json").read_text(encoding="utf-8"))
    constraints = prior.get("constraints", {})
    if prior.get("status") != "PASS" or prior.get("classification") != "A_EVENT_PROBABILITY_AND_SPEED_EDGE" or any((constraints.get("model_retrain_count"), constraints.get("post_freeze_rescoring_count"), constraints.get("prospective_data_used"), constraints.get("data_root_write_count"))):
        raise AuditStop("FAST3_R28_3C_STATUS=STOPPED_IDENTITY_OR_LINEAGE_MISMATCH")
    contract, r1 = b.load_contract()
    cohort, raw = b.load_frozen_scores(), b.load_canonical()
    path = build_path_geometry(b, cohort, raw, r1)
    directional = attach_directional_observations(path, raw, b)
    events = directional.loc[directional.is_actual_touch].copy()
    pre, ladder_rho = pre_touch_ladder(directional)
    post, post_rho = post_touch_path(events)
    giveback, continuation = giveback_and_continuation(events)
    speed = fast_slow(events)
    natural_table, natural = top5_vs_natural(events)
    matched_table, matched = matched_comparison(events)
    counts = directional.groupby("direction").agg(eligible_candidate_count=("direction", "size"), touch_count=("is_actual_touch", "sum")).reset_index()
    if not (counts.touch_count <= counts.eligible_candidate_count).all() or int(counts.eligible_candidate_count.sum()) != len(directional):
        raise AuditStop("STOP_TOUCH_RECONCILIATION_FAILURE")
    classification, hypothesis = classify(natural, matched, post_rho)
    if OUT.exists(): raise AuditStop("STOP_R28_3C_OUTPUT_PATH_EXISTS")
    OUT.mkdir(parents=True)
    for name, table in (("R28_3C_PRE_TOUCH_THRESHOLD_LADDER.csv", pre), ("R28_3C_POST_TOUCH_PATH_BY_SCORE.csv", post),
                        ("R28_3C_GIVEBACK_GEOMETRY.csv", giveback), ("R28_3C_CONTINUATION_THRESHOLDS.csv", continuation),
                        ("R28_3C_FAST_VS_SLOW_TOUCH.csv", speed), ("R28_3C_TOP5_VS_NATURAL_EVENTS.csv", natural_table),
                        ("R28_3C_MATCHED_EVENT_COMPARISON.csv", matched_table), ("R28_3C_RECONCILIATION.csv", counts)):
        table.to_csv(OUT / name, index=False)
    availability = {direction: {str(minute): int(part[f"post_touch_{minute}m_available"].sum()) for minute in POST_WINDOWS} for direction, part in events.groupby("direction")}
    payload = {"FAST3_R28_3C_STATUS": "PASS", "FAST3_R28_3C_CLASSIFICATION": classification, "candidate_universe_source": prior["candidate_universe_source"],
               "frozen_score_source": prior["candidate_universe_source"], "label_source": prior["label_contract_source"], "price_path_source": prior["price_source"],
               "timezone": "America/New_York", "event_horizon": "24 natural hours from first subsequent valid one-minute open", "up_event_threshold": .01, "down_event_threshold": -.01,
               "bucket_definition": "cumulative TOP_1PCT/TOP_2PCT/TOP_5PCT/TOP_10PCT/TOP_20PCT; disjoint PCT_20_TO_40/PCT_40_TO_60/PCT_60_TO_80/BOTTOM_20PCT", "random_seed": RANDOM_SEED, "matched_event_run_count": MATCHED_EVENT_RUN_COUNT,
               "reconciliation": counts.to_dict(orient="records"), "touch_with_incomplete_post_path_count": 0, "dropped_row_count": 0, "dropped_row_reasons": {}, "post_touch_window_availability": availability,
               "pre_touch_spearman": ladder_rho, "post_touch_spearman": post_rho, "top5_vs_natural": natural, "matched_event_comparison": matched,
               "future_path_used_for_outcome_audit_only": True, "future_path_used_for_model_input": False,
               "constraints": {"model_retrain_count": 0, "model_predict_call_count": 0, "post_freeze_rescoring_count": 0, "prospective_data_used": False, "data_root_write_count": 0, "feature_changes": False, "execution_contract_changes": False, "live_trading_allowed": False},
               "hypothesis_for_next_stage": hypothesis, "r29_allowed_to_resume": False, "live_trading_allowed": False}
    (OUT / "R28_3C_SUMMARY.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (OUT / "R28_3C_REPORT.md").write_text(report(payload), encoding="utf-8")
    return payload


if __name__ == "__main__":
    try:
        print(json.dumps(run(), indent=2, default=str))
    except AuditStop as exc:
        print(str(exc))
        raise SystemExit(2)
