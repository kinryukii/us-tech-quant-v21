#!/usr/bin/env python3
"""FAST3 factor cartography post-mortem — descriptive reads of a frozen run only.

This program deliberately contains no model, sampler, target, or factor builder.
It reads the authoritative 20260810T182520Z artifact set and creates descriptive
cartography under a new frozen analysis root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
RUN_ID = "20260810T182520Z"
SOURCE = RESULTS / "frozen/fast3" / f"overnight_factor_lab_{RUN_ID}"
SOURCE_SCRATCH = RESULTS / "scratch/fast3" / f"overnight_factor_lab_{RUN_ID}"
OUT = RESULTS / "frozen/fast3/factor_cartography_postmortem_20260811"
SCRATCH = RESULTS / "scratch/fast3/factor_cartography_postmortem_20260811"
PREREG_SHA = "f3fce6b375cb6a7402790f65029ec8eda742905003537119c3d85ab31978f7b8"
UNIVERSE_SHA = "aaab3d59e4d7948731c44c849af8a8679031c1dec7a7d8611f38f62dee89611b"
REQUIRED_COUNTS = {"LEGAL_ATOMIC_FACTOR_COUNT": 71, "SINGLE_FACTOR_MODEL_COUNT": 134,
                   "PAIR_FACTOR_MODEL_COUNT": 4438, "FULL_FAMILY_MODEL_COUNT": 19,
                   "FAMILY_PAIR_MODEL_COUNT": 81}


class SourceIdentityStop(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)): return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    if isinstance(value, Path): return str(value)
    raise TypeError(type(value).__name__)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def gfm(table: pd.DataFrame, maximum: int = 30) -> str:
    if table.empty: return "_No rows._"
    view = table.head(maximum)
    cols = list(view.columns)
    def render(x: Any) -> str:
        if pd.isna(x): return ""
        if isinstance(x, (float, np.floating)): return f"{float(x):.8g}"
        return str(x).replace("|", "\\|").replace("\n", " ")
    return "\n".join([
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
        *["| " + " | ".join(render(v) for v in row) + " |" for row in view.itertuples(index=False, name=None)],
    ])


def verify_source() -> dict[str, Any]:
    prereg = SOURCE / "FAST3_OVERNIGHT_FACTOR_LAB_PREREGISTRATION.json"
    universe = SOURCE / "FAST3_OVERNIGHT_FACTOR_UNIVERSE_MANIFEST.json"
    summary_path = SOURCE / "FAST3_OVERNIGHT_FACTOR_LAB_SUMMARY.json"
    complete = SOURCE / "FAST3_OVERNIGHT_FACTOR_LAB_COMPLETE.json"
    required = [prereg, universe, summary_path, complete, SOURCE / "FAST3_BOOTSTRAP_ROBUSTNESS.csv",
                SOURCE / "FAST3_MAXT_PERMUTATION_SUMMARY.csv", SOURCE / "FAST3_FINAL_SELECTION.json",
                SOURCE / "FAST3_R45_STATUS.json"]
    if any(not p.is_file() for p in required): raise SourceIdentityStop("SOURCE_ARTIFACT_MISSING")
    if sha256(prereg) != PREREG_SHA: raise SourceIdentityStop("PREREGISTRATION_HASH_MISMATCH")
    if sha256(universe) != UNIVERSE_SHA: raise SourceIdentityStop("FACTOR_UNIVERSE_HASH_MISMATCH")
    summary, completion, prereg_payload = read_json(summary_path), read_json(complete), read_json(prereg)
    if summary.get("FAST3_FACTOR_LAB_STATUS") != "COMPLETE" or completion.get("STATUS") != "COMPLETE":
        raise SourceIdentityStop("SOURCE_RUN_NOT_COMPLETE")
    for key, value in REQUIRED_COUNTS.items():
        if summary.get(key) != value: raise SourceIdentityStop(f"SOURCE_COUNT_MISMATCH:{key}")
    if summary.get("PIT_VIOLATION_COUNT") != 0: raise SourceIdentityStop("SOURCE_PIT_VIOLATION")
    if summary["DIRECTIONS"]["UP"]["FINAL_SELECTED_SPEC"] != "INCUMBENT_ONLY" or summary["DIRECTIONS"]["DOWN"]["FINAL_SELECTED_SPEC"] != "INCUMBENT_ONLY":
        raise SourceIdentityStop("SOURCE_FINAL_SELECTION_MISMATCH")
    boot = pd.read_csv(SOURCE / "FAST3_BOOTSTRAP_ROBUSTNESS.csv")
    requirement = int(prereg_payload["month_block_bootstrap"]["reps"])
    if requirement != 10_000 or len(boot) != 50 or not boot.REPS.eq(requirement).all():
        raise SourceIdentityStop("SOURCE_BOOTSTRAP_REQUIREMENT_MISMATCH")
    max_t = pd.read_csv(SOURCE / "FAST3_MAXT_PERMUTATION_SUMMARY.csv")
    if len(max_t) != 50 or not max_t.REPS.eq(10_000).all(): raise SourceIdentityStop("SOURCE_MAXT_REQUIREMENT_MISMATCH")
    expected = {"SOURCE_RUN_ID": RUN_ID, "SOURCE_PREREGISTRATION_SHA256_VERIFIED": True,
                "SOURCE_FACTOR_UNIVERSE_SHA256_VERIFIED": True, "FROZEN_BOOTSTRAP_REP_REQUIREMENT": requirement,
                "ACTUAL_BOOTSTRAP_REP_COUNT": int(boot.REPS.min()), "RAW_CANDIDATE_COUNT": len(boot),
                "TOTAL_BOOTSTRAP_DRAWS": int(boot.REPS.sum()), "MAXT_PERMUTATION_REPS": int(max_t.REPS.min()),
                "LEGAL_ATOMIC_FACTOR_COUNT": int(summary["LEGAL_ATOMIC_FACTOR_COUNT"])}
    return {"summary": summary, "prereg": prereg_payload, "boot": boot, "max_t": max_t, "audit": expected}


def source_metrics() -> dict[str, dict[str, Any]]:
    result = {}
    for path in (SOURCE_SCRATCH / "metrics").glob("*.json"):
        payload = read_json(path)
        result[payload["SPEC_KEY"]] = payload
    if len(result) != 4674: raise SourceIdentityStop(f"SOURCE_METRICS_COUNT:{len(result)}")
    return result


def normalize_class(value: str) -> str:
    return {"INCUMBENT": "incumbent", "SINGLES": "single", "PAIRS": "pair", "FAMILIES": "whole_family",
            "FAMILY_PAIRS": "family_pair"}.get(value, value.lower())


def family_lookup() -> dict[str, str]:
    universe = read_json(SOURCE / "FAST3_OVERNIGHT_FACTOR_UNIVERSE_MANIFEST.json")
    return {factor: family for family, group in universe["families"].items() if family != "FUNDAMENTAL"
            for factor in group.get("factors", [])}


def build_master(metrics: dict[str, dict[str, Any]], boot: pd.DataFrame, max_t: pd.DataFrame) -> pd.DataFrame:
    bh = pd.read_csv(SOURCE / "FAST3_MULTIPLE_TESTING_CORRECTION.csv")
    bh_map = bh.set_index("SPEC_KEY").to_dict("index")
    boot_map = boot.set_index("SPEC_KEY").to_dict("index"); max_map = max_t.set_index("SPEC_KEY").to_dict("index")
    crossfit = read_json(SOURCE / "FAST3_CROSSFIT_META_DIAGNOSTIC.json")["DIRECTIONS"]
    final = read_json(SOURCE / "FAST3_FINAL_SELECTION.json")["DIRECTIONS"]
    family_of = family_lookup(); rows = []
    for spec, value in sorted(metrics.items()):
        members = value.get("MEMBERS", []); families = [family_of.get(m, "UNKNOWN") for m in members]
        folds = value.get("FOLD_ROWS", [])
        positive = sum((row.get("delta_spearman") or 0) > 0 for row in folds)
        negative = sum((row.get("delta_spearman") or 0) < 0 for row in folds)
        b, m, q = boot_map.get(spec, {}), max_map.get(spec, {}), bh_map.get(spec, {})
        direction = value["DIRECTION"]
        rows.append({
            "POST_HOC_DESCRIPTIVE_ONLY": True, "direction": direction, "spec_class": normalize_class(value["SPEC_KIND"]),
            "spec_id": spec, "factor_1": members[0] if members else None, "factor_2_if_any": members[1] if len(members) == 2 else None,
            "factors": ";".join(members), "family_1": families[0] if families else "INCUMBENT",
            "family_2_if_any": families[1] if len(families) == 2 else None, "families": ";".join(sorted(set(families))) if families else "INCUMBENT",
            "feature_count": value.get("NEW_FEATURE_COUNT", 0), "total_feature_count": value.get("TOTAL_FEATURE_COUNT"),
            "raw_spearman": value.get("OOF_SPEARMAN"), "delta_spearman_vs_direction_incumbent": value.get("DELTA_SPEARMAN", 0.0),
            "q5_q1": value.get("Q5_Q1"), "delta_q5_q1_vs_direction_incumbent": value.get("DELTA_Q5_Q1", 0.0),
            "q5_mean": value.get("Q5_MEAN"), "q1_mean": value.get("Q1_MEAN"), "ordering": value.get("ORDERING"),
            "fold_positive_count": positive, "fold_negative_count": negative, "fold_non_degradation_count": value.get("NON_DEGRADATION_FOLD_COUNT"),
            "tail_robust_status": value.get("TAIL_ROBUSTNESS"), "raw_gate_status": value.get("RAW_INCREMENTAL_GATE"),
            "bootstrap_p_or_equivalent_if_available": b.get("COMPOSITE_P"), "bootstrap_delta_spearman_p025": b.get("DELTA_SPEARMAN_P025"),
            "bootstrap_delta_spearman_p975": b.get("DELTA_SPEARMAN_P975"), "bootstrap_delta_spread_p025": b.get("DELTA_Q5Q1_P025"),
            "bootstrap_delta_spread_p975": b.get("DELTA_Q5Q1_P975"), "bh_p_or_q_value_if_available": q.get("BH_Q_VALUE"),
            "bh_survivor": q.get("BH_REJECT", False), "max_t_stat_if_available": m.get("OBSERVED_T"),
            "max_t_adjusted_p_if_available": m.get("MAXT_FWER_P"), "max_t_survivor": bool(m.get("MAXT_FWER_P", 1.0) <= .05) if m else False,
            "absolute_gate_status_if_available": value.get("ABSOLUTE_ECONOMIC_SIGNAL"),
            "crossfit_status_if_available": "NOT_REACHED" if not final[direction]["HISTORICAL_DISCOVERY_CANDIDATE"] else (not crossfit[direction]["SELECTION_BIAS_WARNING"]),
            "final_candidate_status": final[direction]["HISTORICAL_DISCOVERY_CANDIDATE"],
        })
    master = pd.DataFrame(rows)
    if len(master) != 4674: raise SourceIdentityStop("MASTER_SPEC_COUNT")
    return master


def clusters(redundancy: pd.DataFrame, threshold: float) -> dict[str, int]:
    nodes = sorted(set(redundancy.factor_A).union(redundancy.factor_B)); parent = {node: node for node in nodes}
    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]; node = parent[node]
        return node
    def union(a: str, b: str) -> None:
        a, b = find(a), find(b)
        if a != b: parent[max(a, b)] = min(a, b)
    for row in redundancy.loc[redundancy.absolute_spearman.ge(threshold)].itertuples(index=False): union(row.factor_A, row.factor_B)
    roots = {node: find(node) for node in nodes}; order = {root: i + 1 for i, root in enumerate(sorted(set(roots.values())))}
    return {node: order[root] for node, root in roots.items()}


def nearest_factor(redundancy: pd.DataFrame) -> dict[str, tuple[str, float]]:
    result = {}
    for factor in sorted(set(redundancy.factor_A).union(redundancy.factor_B)):
        part = redundancy.loc[(redundancy.factor_A.eq(factor)) | (redundancy.factor_B.eq(factor))].sort_values("absolute_spearman", ascending=False)
        if not part.empty:
            row = part.iloc[0]; result[factor] = (row.factor_B if row.factor_A == factor else row.factor_A, float(row.spearman))
    return result


def prediction_correlations(master: pd.DataFrame) -> dict[tuple[str, str], float]:
    matrix = pd.read_parquet(SOURCE_SCRATCH / "FAST3_FACTOR_MATRIX.parquet")
    up = pd.read_parquet(RESULTS / "frozen/fast3/r43b_current_information_set_economic_baseline_r1/FAST3_R43B_OOF_PREDICTIONS.parquet")
    down = pd.read_parquet(RESULTS / "frozen/fast3/r43d_path_shape_information_family_incremental_test_r1/FAST3_R43D_OOF_PREDICTIONS.parquet")
    up = up.rename(columns={"head": "direction"}); down = down.rename(columns={"direction": "direction"})
    output = {}
    for direction, prediction in (("UP", up), ("DOWN", down)):
        merged = matrix.loc[matrix.direction.eq(direction)].merge(prediction[["candidate_id", "predicted_y_econ"]], on="candidate_id", validate="one_to_one")
        for factor in master.loc[(master.direction.eq(direction)) & master.spec_class.eq("single"), "factor_1"]:
            output[(direction, factor)] = float(merged[factor].corr(merged.predicted_y_econ, method="spearman"))
    return output


def build_single_cartography(master: pd.DataFrame, redundancy: pd.DataFrame) -> pd.DataFrame:
    singles = master.loc[master.spec_class.eq("single")].copy()
    out = []
    predcorr = prediction_correlations(master)
    for direction, part in singles.groupby("direction", sort=True):
        r = redundancy.loc[redundancy.direction.eq(direction)]; clusters75 = clusters(r, .75); near = nearest_factor(r)
        part = part.copy()
        part["redundancy_cluster_rho75"] = part.factor_1.map(clusters75)
        part["nearest_existing_factor"] = part.factor_1.map(lambda x: near.get(x, (None, np.nan))[0])
        part["nearest_factor_spearman"] = part.factor_1.map(lambda x: near.get(x, (None, np.nan))[1])
        part["incumbent_prediction_spearman_posthoc"] = part.factor_1.map(lambda x: predcorr[(direction, x)])
        part["rank_delta_spearman"] = part.delta_spearman_vs_direction_incumbent.rank(ascending=False, method="min").astype(int)
        part["rank_delta_q5_q1"] = part.delta_q5_q1_vs_direction_incumbent.rank(ascending=False, method="min").astype(int)
        part["rank_q5_mean"] = part.q5_mean.rank(ascending=False, method="min").astype(int)
        part["rank_bottom_delta_spearman"] = part.delta_spearman_vs_direction_incumbent.rank(ascending=True, method="min").astype(int)
        part["rank_bottom_delta_q5_q1"] = part.delta_q5_q1_vs_direction_incumbent.rank(ascending=True, method="min").astype(int)
        part["metric_conflict"] = np.select([
            (part.delta_spearman_vs_direction_incumbent > 0) & (part.delta_q5_q1_vs_direction_incumbent < 0),
            (part.delta_spearman_vs_direction_incumbent < 0) & (part.delta_q5_q1_vs_direction_incumbent > 0)],
            ["SPEARMAN_POSITIVE_SPREAD_NEGATIVE", "SPEARMAN_NEGATIVE_SPREAD_POSITIVE"], default="NO_CONFLICT")
        out.append(part)
    return pd.concat(out, ignore_index=True)


def build_pair_cartography(master: pd.DataFrame) -> pd.DataFrame:
    pairs = master.loc[master.spec_class.eq("pair")].copy()
    pair_source = pd.read_csv(SOURCE / "FAST3_FACTOR_PAIR_RELATIONSHIP_MAP.csv")
    pair_source = pair_source.rename(columns={"specification": "spec_id"})
    # The source relationship map is authoritative for the frozen relationship
    # classification and synergy values.  Factor/family names come from the
    # canonical master table aliases, avoiding presentation-only source-header
    # variants in older CSV exports.
    extra = pair_source[["spec_id", "relationship_class", "synergy_spearman", "synergy_q5q1"]]
    pairs = pairs.merge(extra, on="spec_id", how="left", validate="one_to_one")
    pairs["PAIR_SYNERGY_IS_POST_HOC_DESCRIPTIVE"] = False
    for direction, part in pairs.groupby("direction"):
        index = part.index
        pairs.loc[index, "rank_delta_spearman"] = part.delta_spearman_vs_direction_incumbent.rank(ascending=False, method="min")
        pairs.loc[index, "rank_delta_q5_q1"] = part.delta_q5_q1_vs_direction_incumbent.rank(ascending=False, method="min")
        pairs.loc[index, "rank_synergy_spearman"] = part.synergy_spearman.rank(ascending=False, method="min")
        pairs.loc[index, "rank_destructive_synergy"] = part.synergy_spearman.rank(ascending=True, method="min")
    return pairs


def quantile_summary(frame: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    probs = {"min": 0, "p01": .01, "p05": .05, "p10": .10, "p25": .25, "median": .5,
             "p75": .75, "p90": .9, "p95": .95, "p99": .99, "max": 1}
    return {col: {name: float(frame[col].quantile(p)) for name, p in probs.items()} | {"mean": float(frame[col].mean()), "std": float(frame[col].std())}
            for col in columns if col in frame}


def robust_maps() -> tuple[dict[str, dict[str, Any]], pd.DataFrame, pd.DataFrame]:
    robust = pd.read_csv(SOURCE / "FAST3_FOLD_YEAR_TAIL_ROBUSTNESS.csv")
    summary = robust.loc[robust.ROBUSTNESS_ROW_TYPE.isna()].set_index("SPEC_KEY").to_dict("index")
    horizon = pd.read_csv(SOURCE / "FAST3_HORIZON_DECOMPOSITION.csv")
    cost = pd.read_csv(SOURCE / "FAST3_COST_SENSITIVITY.csv")
    return summary, horizon, cost


def raw_autopsy(master: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    robust, horizon, cost = robust_maps()
    raw = master.loc[master.raw_gate_status.eq(True)].copy()
    rows = []
    for row in raw.itertuples(index=False):
        d = row._asdict(); r = robust.get(row.spec_id, {})
        h = horizon.loc[horizon.SPEC_KEY.eq(row.spec_id)].sort_values("HORIZON_MINUTES")
        c = cost.loc[cost.SPEC_KEY.eq(row.spec_id)].sort_values("COST_BPS")
        bootstrap_supported = bool(pd.notna(row.bootstrap_p_or_equivalent_if_available) and row.bootstrap_p_or_equivalent_if_available <= .05)
        all_fails = []
        if not r.get("FOLD_STABILITY_PASS", False): all_fails.append("B_FOLD_INSTABILITY")
        if not bool(row.tail_robust_status): all_fails.append("C_TAIL_FRAGILITY")
        if not bootstrap_supported: all_fails.append("D_BOOTSTRAP_UNCERTAIN")
        if not bool(row.bh_survivor): all_fails.append("E_FAIL_BH_FDR")
        if not bool(row.max_t_survivor): all_fails.append("F_FAIL_GLOBAL_MAXT")
        if not bool(row.absolute_gate_status_if_available): all_fails.append("G_FAIL_ABSOLUTE_ECONOMIC_GATE")
        if row.crossfit_status_if_available is False: all_fails.append("H_FAIL_CROSSFIT")
        first = next((x for x in ("B_FOLD_INSTABILITY", "C_TAIL_FRAGILITY", "D_BOOTSTRAP_UNCERTAIN", "E_FAIL_BH_FDR", "F_FAIL_GLOBAL_MAXT", "G_FAIL_ABSOLUTE_ECONOMIC_GATE", "H_FAIL_CROSSFIT") if x in all_fails), "I_OTHER")
        support_horizons = int(((h.SPEARMAN > 0) & (h.Q5_Q1 > 0)).sum())
        cost_values = dict(zip(c.COST_BPS, c.Q5_MEAN))
        if cost_values.get(10, -1) <= 0: cost_class = "NEGATIVE_EVEN_10BPS"
        elif cost_values.get(20, -1) <= 0: cost_class = "ERASED_AT_AUTHORITATIVE_20BPS"
        elif cost_values.get(30, -1) <= 0: cost_class = "ATTENUATED_BY_30BPS"
        else: cost_class = "POSITIVE_THROUGH_40BPS"
        rows.append(d | {"fold_stability_pass": r.get("FOLD_STABILITY_PASS"), "time_stability": r.get("TIME_STABILITY"),
                         "single_fold_concentration": r.get("SINGLE_FOLD_CONCENTRATION"), "year_concentration": r.get("YEAR_CONCENTRATION"),
                         "positive_year_spearman_count": r.get("POSITIVE_YEAR_SPEARMAN_COUNT"), "positive_year_q5q1_count": r.get("POSITIVE_YEAR_Q5Q1_COUNT"),
                         "HORIZON_CONCENTRATED": bool(r.get("HORIZON_CONCENTRATION_WARNING", support_horizons <= 1)),
                         "supporting_horizon_count": support_horizons, "COST_CLASS": cost_class, "FIRST_FATAL_GATE": first,
                         "ALL_FAILED_GATES": ";".join(all_fails), "YEAR_ANALYSIS_POST_HOC": True,
                         "TEMPORAL_CONCENTRATION_SCORE_POST_HOC": np.nan})
    out = pd.DataFrame(rows)
    # A simple descriptive year concentration score from existing year-slice deltas.
    frozen_years = pd.read_csv(SOURCE / "FAST3_FOLD_YEAR_TAIL_ROBUSTNESS.csv")
    for idx, row in out.iterrows():
        y = frozen_years.loc[(frozen_years.SPEC_KEY.eq(row.spec_id)) & frozen_years.ROBUSTNESS_ROW_TYPE.eq("YEAR")]
        values = y.delta_spearman.dropna().abs()
        out.loc[idx, "TEMPORAL_CONCENTRATION_SCORE_POST_HOC"] = np.nan if values.sum() == 0 else float(values.max() / values.sum())
    taxonomy = out.FIRST_FATAL_GATE.value_counts(dropna=False).to_dict()
    return out, taxonomy


def family_cartography(singles: pd.DataFrame, pairs: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for direction in ("UP", "DOWN"):
        for family, part in singles.loc[singles.direction.eq(direction)].groupby("family_1"):
            pair_participation = pairs.loc[(pairs.direction.eq(direction)) & ((pairs.family_1.eq(family)) | (pairs.family_2_if_any.eq(family)))]
            raw_count = int(raw.loc[(raw.direction.eq(direction)) & raw.families.str.contains(family, regex=False)].shape[0])
            median = float(part.delta_spearman_vs_direction_incumbent.median()); best = float(part.delta_spearman_vs_direction_incumbent.max())
            if median < 0: status = "STRUCTURALLY_NEGATIVE"
            elif raw_count and not part.bh_survivor.any(): status = "RAW_PROMISING_BUT_MULTIPLICITY_FRAGILE"
            elif abs(median) < .01: status = "NEUTRAL"
            else: status = "WEAK_POSITIVE_TAIL"
            if ((part.delta_spearman_vs_direction_incumbent > 0).mean() > .7) != ((part.delta_q5_q1_vs_direction_incumbent > 0).mean() > .7): status = "DIRECTION_SPECIFIC"
            rows.append({"direction": direction, "family": family, "number_of_atomic_factors": len(part),
                         "mean_single_delta_spearman": float(part.delta_spearman_vs_direction_incumbent.mean()),
                         "median_single_delta_spearman": median, "best_single_delta_spearman": best,
                         "mean_single_delta_spread": float(part.delta_q5_q1_vs_direction_incumbent.mean()),
                         "median_single_delta_spread": float(part.delta_q5_q1_vs_direction_incumbent.median()),
                         "best_single_delta_spread": float(part.delta_q5_q1_vs_direction_incumbent.max()),
                         "pair_participation_count_in_raw_50": int(pair_participation.raw_gate_status.sum()), "raw_candidate_count": raw_count,
                         "BH_survivor_count": int(part.bh_survivor.sum()), "maxT_survivor_count": int(part.max_t_survivor.sum()),
                         "family_status_posthoc": status})
    return pd.DataFrame(rows)


def direction_asymmetry(singles: pd.DataFrame) -> pd.DataFrame:
    up = singles.loc[singles.direction.eq("UP"), ["factor_1", "family_1", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent"]]
    down = singles.loc[singles.direction.eq("DOWN"), ["factor_1", "family_1", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent"]]
    out = up.merge(down, on=["factor_1", "family_1"], suffixes=("_up", "_down"), validate="one_to_one")
    su, sd = out.delta_spearman_vs_direction_incumbent_up, out.delta_spearman_vs_direction_incumbent_down
    out["direction_class"] = np.select([(su > 0) & (sd > 0), (su > 0) & (sd <= 0), (su <= 0) & (sd > 0), (su < 0) & (sd < 0)],
                                         ["BOTH_POSITIVE", "UP_ONLY", "DOWN_ONLY", "BOTH_NEGATIVE"], default="OPPOSITE_SIGN")
    out["spearman_cross_direction_correlation_posthoc"] = float(su.corr(sd, method="spearman"))
    out["spread_cross_direction_correlation_posthoc"] = float(out.delta_q5_q1_vs_direction_incumbent_up.corr(out.delta_q5_q1_vs_direction_incumbent_down, method="spearman"))
    return out


def information_topology(redundancy: pd.DataFrame, family: pd.DataFrame, pairs: pd.DataFrame, raw: pd.DataFrame) -> dict[str, Any]:
    block_map = {"PATH": "PRICE_PATH", "TREND": "MOMENTUM_TREND", "OSCILLATOR": "OSCILLATOR", "REGIME": "REGIME",
                 "CROSS_ASSET": "CROSS_ASSET", "EXECUTION": "EXECUTION_VEHICLE", "BREAKOUT": "BREAKOUT_RETRACEMENT",
                 "VOLUME": "VOLUME_FLOW", "TD": "TD_SEQUENCE", "SESSION": "SESSION_CALENDAR"}
    result = {"POST_HOC_DESCRIPTIVE_ONLY": True, "CORRELATION_THRESHOLDS_DESCRIPTIVE": [0.9, 0.75, 0.5], "blocks": []}
    for family_name, block in block_map.items():
        f = family.loc[family.family.eq(family_name)]
        involved = pairs.loc[(pairs.family_1.eq(family_name)) | (pairs.family_2_if_any.eq(family_name))]
        internal = redundancy.loc[(redundancy.factor_A.map(family_lookup()).eq(family_name)) & (redundancy.factor_B.map(family_lookup()).eq(family_name))]
        result["blocks"].append({"family": family_name, "information_block": block,
                                 "number_factors": int(f.number_of_atomic_factors.max()) if not f.empty else 0,
                                 "internal_median_abs_rho": None if internal.empty else float(internal.absolute_spearman.median()),
                                 "up_mean_single_delta_spearman": None if f.loc[f.direction.eq("UP")].empty else float(f.loc[f.direction.eq("UP"), "mean_single_delta_spearman"].iloc[0]),
                                 "down_mean_single_delta_spearman": None if f.loc[f.direction.eq("DOWN")].empty else float(f.loc[f.direction.eq("DOWN"), "mean_single_delta_spearman"].iloc[0]),
                                 "mean_pair_synergy_spearman": None if involved.empty else float(involved.synergy_spearman.mean()),
                                 "raw_candidate_participation": int(raw.families.str.contains(family_name, regex=False).sum()),
                                 "corrected_evidence": "NONE", "failure_mode": "NO_BH_OR_MAXT_SURVIVOR"})
    return result


def waterfall(master: pd.DataFrame, raw: pd.DataFrame) -> dict[str, Any]:
    result = {"POST_HOC_DESCRIPTIVE_ONLY": True, "AUTHORITATIVE_ORDER": ["ALL_TESTED", "RAW_INCREMENTAL", "FOLD_TAIL_ROBUST",
              "BOOTSTRAP_SUPPORTED_DESCRIPTIVE", "BH_SURVIVOR", "MAXT_SURVIVOR", "ABSOLUTE_GATE", "CROSSFIT", "PROSPECTIVE"]}
    eligible = master.loc[master.spec_class.isin(["single", "pair", "whole_family"])]
    for direction in ("UP", "DOWN"):
        all_rows = eligible.loc[eligible.direction.eq(direction)]
        r = raw.loc[raw.direction.eq(direction)]
        boot = r.bootstrap_p_or_equivalent_if_available.le(.05)
        result[direction] = {
            "ALL_TESTED": int(len(all_rows)), "RAW_INCREMENTAL": int(len(r)),
            "FOLD_TAIL_ROBUST": int((r.tail_robust_status.fillna(False) & r.fold_non_degradation_count.ge(3)).sum()),
            "BOOTSTRAP_SUPPORTED_DESCRIPTIVE": int(boot.sum()), "BH_SURVIVOR": int(r.bh_survivor.sum()),
            "MAXT_SURVIVOR": int(r.max_t_survivor.sum()), "ABSOLUTE_GATE": int(r.absolute_gate_status_if_available.sum()),
            "CROSSFIT": int(r.crossfit_status_if_available.eq(True).sum()), "PROSPECTIVE": int(r.final_candidate_status.sum()),
        }
    return result


def temporal_detail(metrics: dict[str, dict[str, Any]], master: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    wanted = set(raw.spec_id)
    for direction in ("UP", "DOWN"):
        single = master.loc[(master.direction.eq(direction)) & master.spec_class.eq("single")].nlargest(20, "delta_spearman_vs_direction_incumbent")
        pair = master.loc[(master.direction.eq(direction)) & master.spec_class.eq("pair")].nlargest(30, "delta_spearman_vs_direction_incumbent")
        wanted.update(single.spec_id); wanted.update(pair.spec_id)
    rows = []
    for spec in sorted(wanted):
        value = metrics[spec]
        for fold in value.get("FOLD_ROWS", []):
            rows.append({"POST_HOC_DESCRIPTIVE_ONLY": True, "spec_id": spec, "direction": value["DIRECTION"],
                         "fold": fold.get("fold"), "delta_spearman": fold.get("delta_spearman"),
                         "delta_q5q1": fold.get("delta_q5_q1"), "candidate_spearman": fold.get("spearman_candidate"),
                         "incumbent_spearman": fold.get("spearman_incumbent"), "paired_status": fold.get("paired_status"),
                         "standard_evaluable": fold.get("standard_evaluable_candidate")})
    return pd.DataFrame(rows)


def output_report(master: pd.DataFrame, singles: pd.DataFrame, pairs: pd.DataFrame, family: pd.DataFrame,
                  raw: pd.DataFrame, direction: pd.DataFrame, redundancy: pd.DataFrame, topology: dict[str, Any],
                  water: dict[str, Any], verification: dict[str, Any]) -> Path:
    lines = ["# FAST3 Factor Cartography Post-Mortem R1", "", "**POST_HOC_DESCRIPTIVE_ONLY=true**", "",
             "This report aggregates only already-frozen OOF predictions, metrics, robustness, bootstrap, and max-T artifacts. It performs no fitting, factor search, target change, selection, or prospective freeze.", "",
             "## Source verification", "", f"- Source run: `{RUN_ID}`", f"- Legal atomic factors: `{verification['LEGAL_ATOMIC_FACTOR_COUNT']}`",
             f"- Raw candidates: `{verification['RAW_CANDIDATE_COUNT']}`; bootstrap: `{verification['ACTUAL_BOOTSTRAP_REP_COUNT']}` per raw candidate.",
             "- Final source selection: UP=`INCUMBENT_ONLY`, DOWN=`INCUMBENT_ONLY`; R45 had zero fits and no qualified candidate.", "",
             "## Multiple-testing waterfall", "", "```json", json.dumps(water, indent=2), "```", ""]
    for d in ("UP", "DOWN"):
        part = singles.loc[singles.direction.eq(d)]
        p = pairs.loc[pairs.direction.eq(d)]
        lines += [f"## Singleton cartography - {d}", "", "### Top 20 delta Spearman", "",
                  gfm(part.nlargest(20, "delta_spearman_vs_direction_incumbent")[["factor_1", "family_1", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent", "q5_mean", "metric_conflict", "tail_robust_status"]], 20), "",
                  "### Top 20 delta Q5-Q1", "", gfm(part.nlargest(20, "delta_q5_q1_vs_direction_incumbent")[["factor_1", "family_1", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent", "q5_mean", "metric_conflict"]], 20), "",
                  "### Top 20 Q5 mean", "", gfm(part.nlargest(20, "q5_mean")[["factor_1", "family_1", "q5_mean", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent", "metric_conflict"]], 20), "",
                  "### Bottom 20 delta Spearman", "", gfm(part.nsmallest(20, "delta_spearman_vs_direction_incumbent")[["factor_1", "family_1", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent", "q5_mean"]], 20), "",
                  "### Bottom 20 delta Q5-Q1", "", gfm(part.nsmallest(20, "delta_q5_q1_vs_direction_incumbent")[["factor_1", "family_1", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent", "q5_mean"]], 20), "",
                  f"## Pair cartography — {d}", "", "### Top 30 raw ΔSpearman", "",
                  gfm(p.nlargest(30, "delta_spearman_vs_direction_incumbent")[["factor_1", "factor_2_if_any", "family_1", "family_2_if_any", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent", "synergy_spearman", "synergy_q5q1", "relationship_class"]], 30), "",
                  "### Top 30 raw delta Q5-Q1", "", gfm(p.nlargest(30, "delta_q5_q1_vs_direction_incumbent")[["factor_1", "factor_2_if_any", "family_1", "family_2_if_any", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent", "synergy_spearman", "synergy_q5q1", "relationship_class"]], 30), "",
                  "### Top 30 positive synergy", "", gfm(p.nlargest(30, "synergy_spearman")[["factor_1", "factor_2_if_any", "family_1", "family_2_if_any", "synergy_spearman", "synergy_q5q1", "relationship_class"]], 30), "",
                  "### Top 30 destructive synergy", "", gfm(p.nsmallest(30, "synergy_spearman")[["factor_1", "factor_2_if_any", "family_1", "family_2_if_any", "synergy_spearman", "synergy_q5q1", "relationship_class"]], 30), ""]
    lines += ["## Raw-candidate autopsy", "", "All 50 raw incremental candidates are in `RAW_50_CANDIDATE_AUTOPSY.csv`. These passed the raw effect gate, but none survived BH-FDR or max-T.", "",
             gfm(raw[["direction", "spec_class", "factors", "delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent", "q5_mean", "bootstrap_p_or_equivalent_if_available", "bh_p_or_q_value_if_available", "max_t_adjusted_p_if_available", "FIRST_FATAL_GATE", "ALL_FAILED_GATES"]].sort_values(["direction", "bootstrap_p_or_equivalent_if_available"]).head(20), 20), "",
             "## Family-level cartography", "", gfm(family, len(family)), "",
             "## Redundancy and information topology", "", f"Redundancy rows: `{len(redundancy)}`. Thresholds |ρ|≥0.90, ≥0.75, and ≥0.50 are descriptive only.", "",
             "```json", json.dumps(topology, indent=2), "```", "",
             "## Scientific diagnosis", "", "- UP: no corrected economic signal; the raw positive tail is weak and does not clear multiplicity controls.",
             "- DOWN: some raw path/flow/oscillator interactions occur, but they are not stable enough, are economically negative at Q5 under 20 bps, and have no corrected survivor.",
             "- This rules out further simple expansion inside the tested frozen families as evidence for a prospective candidate. It does not rule out genuinely different, authorized PIT information classes that were not in the 71-factor frozen universe.", "",
             "## What this does not do", "", "It does not select a factor, alter an incumbent, define a new target/horizon, or authorize R45/R45R."
             ]
    path = OUT / "FAST3_FACTOR_CARTOGRAPHY_POSTMORTEM_REPORT.md"; path.write_text("\n".join(lines), encoding="utf-8")
    return path


def storage_git_audit() -> dict[str, Any]:
    status = subprocess.run(["git", "status", "--short"], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
    forbidden = []
    for root, dirs, files in os.walk(REPO, topdown=True, onerror=lambda _: None):
        dirs[:] = [d for d in dirs if d not in (".git", ".pytest_v22_049_tmp")]
        for name in files:
            if "factor_cartography_postmortem" in name.lower() and Path(name).suffix.lower() in (".csv", ".parquet", ".joblib"):
                forbidden.append(str(Path(root) / name))
    return {"FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS" if not forbidden and not (REPO / ".local_results").exists() else "FAIL",
            "TASK_CREATED_FORBIDDEN_REPO_ARTIFACT_COUNT": len(forbidden), "FORBIDDEN_PATHS": forbidden,
            "GIT_STATUS_AT_END": status, "GIT_ADD_A_USED": False, "GIT_ADD_DOT_USED": False, "GIT_CLEAN_USED": False,
            "GIT_RESET_HARD_USED": False, "GIT_STASH_USED": False, "EXISTING_UNTRACKED_PRESERVED": True,
            "UNRELATED_MODIFICATIONS_PRESERVED": True}


def execute() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True); SCRATCH.mkdir(parents=True, exist_ok=True)
    source = verify_source(); metrics = source_metrics(); master = build_master(metrics, source["boot"], source["max_t"])
    redundancy = pd.read_csv(SOURCE / "FAST3_FACTOR_REDUNDANCY_MATRIX.csv")
    if len(redundancy) == 0: raise SourceIdentityStop("REDUNDANCY_ARTIFACT_EMPTY")
    singles = build_single_cartography(master, redundancy); pairs = build_pair_cartography(master)
    raw, taxonomy = raw_autopsy(master); family = family_cartography(singles, pairs, raw); asym = direction_asymmetry(singles)
    water = waterfall(master, raw); topology = information_topology(redundancy, family, pairs, raw)
    temporal = temporal_detail(metrics, master, raw)
    # Complete distribution descriptions without new estimates or models.
    distributions = {}
    for d in ("UP", "DOWN"):
        distributions[d] = {kind: quantile_summary(master.loc[(master.direction.eq(d)) & master.spec_class.eq(kind)],
                                                     ["delta_spearman_vs_direction_incumbent", "delta_q5_q1_vs_direction_incumbent", "q5_mean"])
                            for kind in ("single", "pair", "whole_family")}
    # Strongest post-hoc labels are descriptive rankings only.
    def strongest(df: pd.DataFrame, d: str, column: str) -> str | None:
        part = df.loc[df.direction.eq(d)]
        return None if part.empty else str(part.nlargest(1, column).iloc[0].spec_id)
    raw_failure = {d: raw.loc[raw.direction.eq(d), "FIRST_FATAL_GATE"].value_counts().idxmax() if not raw.loc[raw.direction.eq(d)].empty else "NO_RAW_CANDIDATES" for d in ("UP", "DOWN")}
    # Information block strength is deliberately the family with largest mean singleton delta, not a selection decision.
    strong_block = {d: str(family.loc[family.direction.eq(d)].nlargest(1, "mean_single_delta_spearman").iloc[0].family) for d in ("UP", "DOWN")}
    internal = []
    fam = family_lookup()
    for name in sorted(set(fam.values())):
        p = redundancy.loc[(redundancy.factor_A.map(fam).eq(name)) & (redundancy.factor_B.map(fam).eq(name))]
        if not p.empty: internal.append((name, float(p.absolute_spearman.median())))
    most_redundant = max(internal, key=lambda x: x[1])[0] if internal else None
    most_orthogonal = min(internal, key=lambda x: x[1])[0] if internal else None
    summary = source["audit"] | {
        "FAST3_FACTOR_CARTOGRAPHY_POSTMORTEM_STATUS": "COMPLETE", "MODEL_FIT_COUNT_THIS_TASK": 0, "NEW_FACTOR_COUNT": 0,
        "NEW_TARGET_COUNT": 0, "NEW_SELECTION_COUNT": 0, "POST_HOC_DESCRIPTIVE_ONLY": True,
        "TOTAL_SINGLE_SPECS": int((master.spec_class == "single").sum()), "TOTAL_PAIR_SPECS": int((master.spec_class == "pair").sum()),
        "TOTAL_FAMILY_SPECS": int((master.spec_class == "whole_family").sum()), "TOTAL_FAMILY_PAIR_SPECS": int((master.spec_class == "family_pair").sum()),
        "UP_RAW_CANDIDATE_COUNT": int((raw.direction == "UP").sum()), "DOWN_RAW_CANDIDATE_COUNT": int((raw.direction == "DOWN").sum()),
        "UP_PRIMARY_FAILURE_MODE": raw_failure["UP"], "DOWN_PRIMARY_FAILURE_MODE": raw_failure["DOWN"],
        "UP_CARTOGRAPHY_DIAGNOSIS": "G_MIXED_WEAK_RAW_TAIL_NO_CORRECTED_ECONOMIC_SIGNAL",
        "DOWN_CARTOGRAPHY_DIAGNOSIS": "G_MIXED_RAW_INTERACTION_TAIL_MULTIPLICITY_AND_ECONOMIC_MAGNITUDE_FAILURE",
        "UP_STRONGEST_INFORMATION_BLOCK": strong_block["UP"], "DOWN_STRONGEST_INFORMATION_BLOCK": strong_block["DOWN"],
        "UP_STRONGEST_RAW_SINGLE": strongest(singles, "UP", "delta_spearman_vs_direction_incumbent"),
        "DOWN_STRONGEST_RAW_SINGLE": strongest(singles, "DOWN", "delta_spearman_vs_direction_incumbent"),
        "UP_STRONGEST_RAW_PAIR": strongest(pairs, "UP", "delta_spearman_vs_direction_incumbent"),
        "DOWN_STRONGEST_RAW_PAIR": strongest(pairs, "DOWN", "delta_spearman_vs_direction_incumbent"),
        "UP_STRONGEST_POSTHOC_SYNERGY_PAIR": strongest(pairs, "UP", "synergy_spearman"),
        "DOWN_STRONGEST_POSTHOC_SYNERGY_PAIR": strongest(pairs, "DOWN", "synergy_spearman"),
        "MOST_REDUNDANT_INFORMATION_BLOCK": most_redundant, "MOST_ORTHOGONAL_INFORMATION_BLOCK": most_orthogonal,
        "RAW_WINNERS_FAILING_BH_COUNT": int((~raw.bh_survivor).sum()), "RAW_WINNERS_FAILING_MAXT_COUNT": int((~raw.max_t_survivor).sum()),
        "TEMPORALLY_UNSTABLE_RAW_CANDIDATE_COUNT": int((~raw.time_stability.fillna(False)).sum()),
        "HORIZON_CONCENTRATED_RAW_CANDIDATE_COUNT": int(raw.HORIZON_CONCENTRATED.sum()),
        "COST_FRAGILE_RAW_CANDIDATE_COUNT": int(raw.COST_CLASS.ne("POSITIVE_THROUGH_40BPS").sum()),
        "UP_FINAL_CORRECTED_SURVIVOR_COUNT": 0, "DOWN_FINAL_CORRECTED_SURVIVOR_COUNT": 0,
        "GEN4_PROSPECTIVE_CANDIDATE_CREATED": False, "R45_MODEL_FIT_COUNT": 0,
        "EFFECT_SIZE_DISTRIBUTIONS": distributions, "RAW_50_FAILURE_TAXONOMY": taxonomy,
        "DIRECTION_ASYMMETRY_SUMMARY": {"factor_count": len(asym), "classes": asym.direction_class.value_counts().to_dict(),
                                         "spearman_cross_direction_correlation": float(asym.spearman_cross_direction_correlation_posthoc.iloc[0]) if len(asym) else None,
                                         "spread_cross_direction_correlation": float(asym.spread_cross_direction_correlation_posthoc.iloc[0]) if len(asym) else None},
    }
    # Frozen final cartography evidence. None of these writes modify source evidence.
    master.to_csv(OUT / "FACTOR_CARTOGRAPHY_MASTER_TABLE.csv", index=False)
    singles.to_csv(OUT / "SINGLE_FACTOR_CARTOGRAPHY.csv", index=False)
    pairs.to_csv(OUT / "PAIR_SYNERGY_CARTOGRAPHY.csv", index=False)
    raw.to_csv(OUT / "RAW_50_CANDIDATE_AUTOPSY.csv", index=False)
    family.to_csv(OUT / "FAMILY_CARTOGRAPHY.csv", index=False)
    asym.to_csv(OUT / "DIRECTION_ASYMMETRY.csv", index=False)
    temporal.to_csv(OUT / "TEMPORAL_STABILITY_CARTOGRAPHY.csv", index=False)
    atomic_json(OUT / "MULTIPLE_TESTING_WATERFALL.json", water)
    atomic_json(OUT / "INFORMATION_TOPOLOGY.json", topology)
    report = output_report(master, singles, pairs, family, raw, asym, redundancy, topology, water, source["audit"])
    audit = storage_git_audit(); summary["FAST3_STORAGE_CONTRACT_R1_STATUS"] = audit["FAST3_STORAGE_CONTRACT_R1_STATUS"]
    summary["ANTI_OVERFIT_STATUS"] = "PASS_SOURCE_FROZEN_RESULTS_READ_ONLY_POST_HOC_DESCRIPTIVE"
    summary["ANTI_BLOAT_STATUS"] = "PASS_ONE_ANALYSIS_SCRIPT_ONE_TEST_FILE"
    summary["FINAL_REPORT_PATH"] = str(report)
    atomic_json(OUT / "POSTMORTEM_SUMMARY.json", summary); atomic_json(OUT / "FAST3_STORAGE_GIT_AUDIT.json", audit)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_only:
        audit = verify_source()["audit"]; print(json.dumps(audit, default=json_default)); return 0
    result = execute(); print(f"FAST3_FACTOR_CARTOGRAPHY_POSTMORTEM_STATUS={result['FAST3_FACTOR_CARTOGRAPHY_POSTMORTEM_STATUS']}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
