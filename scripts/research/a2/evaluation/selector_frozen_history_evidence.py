"""Frozen-history cadence evidence using the established selector statistics.

This is a run adapter, not a new estimator or statistical implementation.
It preserves the closed R2 exposure and cannot authorize production promotion.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.common.storage_paths import assert_safe_output_path, resolve
from scripts.research.a2.evaluation import selector_evidence as evidence
from scripts.research.a2.evaluation.selector_account_compare import (
    pre2026, readj, score_panel, score_path, sha,
)

REPO = Path(__file__).resolve().parents[4]
ROLES = (
    "MONTHLY_FIXED_CORE_RIDGE", "MONTHLY_FIXED_CORE_HGB",
    "MONTHLY_COVERAGE_FLAG_ONLY_RIDGE", "MONTHLY_COVERAGE_FLAG_ONLY_HGB",
)
REFERENCES = (
    "MATCHED_ANNUAL_FIXED_CORE_RIDGE_REFERENCE",
    "MATCHED_ANNUAL_FIXED_CORE_HGB_REFERENCE",
)
CONTRASTS = (
    ("CONTRAST_MONTHLY_FULL_VS_MATCHED_ANNUAL_RIDGE", ROLES[0], REFERENCES[0]),
    ("CONTRAST_MONTHLY_FULL_VS_MATCHED_ANNUAL_HGB", ROLES[1], REFERENCES[1]),
    ("CONTRAST_MONTHLY_FULL_VS_MONTHLY_FLAG_ONLY_RIDGE", ROLES[0], ROLES[2]),
    ("CONTRAST_MONTHLY_FULL_VS_MONTHLY_FLAG_ONLY_HGB", ROLES[1], ROLES[3]),
)
YEARS = (2023, 2024, 2025)
YEAR_COUNTS = {"2023": 250, "2024": 252, "2025": 230}
PRIMARY = "TOP20_REPLACEMENT_EDGE=(sum matured labels entrants - sum matured labels exits)/20"
BOOT_METHOD = "shared noncircular 20-session moving blocks; centered studentized one-sided maxT simultaneous lower"


def validate_design(design):
    """Reject altered questions, family exposure or promotion semantics."""
    if not (design.get("official_freeze") is True
            and design.get("formal_freeze_applied") is True):
        raise ValueError("FORMAL_FREEZE_REQUIRED")
    if (design.get("mechanism_research_eligible") is not True
            or design.get("strict_PIT_promotion_eligible") is not False):
        raise ValueError("FROZEN_HISTORY_DUAL_ELIGIBILITY_REQUIRED")
    if (tuple(design.get("roles", ())) != ROLES
            or tuple(design.get("fixed_reference_roles", ())) != REFERENCES
            or design.get("target") != "MEAN_ER_3D_5D_10D_20D"
            or tuple(design.get("primary_eval_years", ())) != YEARS):
        raise ValueError("FOUR_FROZEN_ROLES_TARGET_AND_ALL_YEARS_REQUIRED")
    if (design.get("test2026_locked") is not True
            or design.get("monthly2026_estimation_authorized") is not False):
        raise ValueError("TEST2026_MUST_REMAIN_LOCKED")
    ev = design["evaluation"]
    if (ev.get("primary") != PRIMARY
            or ev.get("common_mature_date_count") != 732
            or ev.get("year_counts") != YEAR_COUNTS
            or ev.get("candidate_namespace") != 95
            or ev.get("contrast_namespace") != 4
            or ev.get("exposure_namespace") != 99
            or ev.get("fixed_mechanism_pairs") != [[a, b] for _, a, b in CONTRASTS]):
        raise ValueError("FROZEN_CLOCK_AND_99_TEST_EXPOSURE_REQUIRED")
    rule = ev["bootstrap"]
    if (rule.get("method") != BOOT_METHOD or rule.get("repeats") != 5000
            or rule.get("seed") != 20260928 or rule.get("confidence") != .95):
        raise ValueError("ORIGINAL_SHARED_MAXT_RULE_REQUIRED")
    expected = dict(pooled_edge_positive=True, year2025_edge_positive=True,
                    positive_years_min=2, simultaneous_lower_bound_gt_zero=True)
    if any(ev.get("inherited_selection_requirements", {}).get(k) != v
           for k, v in expected.items()):
        raise ValueError("ORIGINAL_SELECTION_THRESHOLD_REQUIRED")
    legacy = ev["legacy"]
    ids, complete, failed = (legacy[k] for k in
                            ("candidate_ids", "complete_ids", "failed_or_untestable"))
    if (len(ids) != 91 or len(set(ids)) != 91 or len(complete) != 79
            or len(set(complete)) != 79 or len(failed) != 12
            or set(complete) & set(failed) or set(complete) | set(failed) != set(ids)
            or set(ids) & set(ROLES + REFERENCES)):
        raise ValueError("CLOSED_91_ROLE_HISTORY_AND_79_REAL_SERIES_REQUIRED")
    return ev


def statistics(legacy_edges, new_edges, positions, calendar, rule, legacy_ids):
    """Joint maxT over actual complete series; failed roles stay in metadata."""
    legacy_ids = list(legacy_ids)
    if (list(legacy_edges.columns) != legacy_ids or legacy_edges.index.has_duplicates
            or not legacy_edges.index.equals(new_edges.index)
            or not np.isfinite(legacy_edges.to_numpy(float)).all()
            or not np.isfinite(new_edges.to_numpy(float)).all()):
        raise ValueError("EXACT_FINITE_COMMON_CLOCK_REQUIRED")
    if (len(positions) != len(legacy_edges)
            or not pd.DatetimeIndex(calendar)[positions].equals(legacy_edges.index)):
        raise ValueError("ORIGINAL_CALENDAR_POSITIONS_REQUIRED")
    ids = list(legacy_ids)
    matrix = legacy_edges.copy()
    for cid in ROLES:
        if cid in new_edges:
            matrix[cid] = new_edges[cid]
            ids.append(cid)
    failed_contrasts = {}
    for cid, full, reference in CONTRASTS:
        if full in new_edges and reference in new_edges:
            matrix[cid] = new_edges[full] - new_edges[reference]
            ids.append(cid)
        else:
            failed_contrasts[cid] = "INCOMPLETE_FROZEN_PAIR"
    legacy_rule = {**rule, "family_candidates": len(legacy_ids)}
    total_rule = {**rule, "family_candidates": len(ids)}
    _, _, old_receipt, old_maxima = evidence.shared_max_t(
        legacy_edges.to_numpy(float), positions, [True] * len(legacy_ids), legacy_rule)
    lower, se, receipt, maxima = evidence.shared_max_t(
        matrix.to_numpy(float), positions, [True] * len(ids), total_rule)
    if (receipt.get("status") != "COMPLETE" or old_receipt.get("status") != "COMPLETE"
            or receipt["shared_draw_sha256"] != old_receipt["shared_draw_sha256"]
            or len(maxima) != len(old_maxima)
            or np.any(maxima + 1e-12 < old_maxima)
            or receipt["critical_max_t"] + 1e-12 < old_receipt["critical_max_t"]):
        raise ValueError("JOINT_MAXT_MUST_NOT_LOWER_LEGACY_THRESHOLD")
    summaries = []
    year_array = legacy_edges.index.year
    for j, cid in enumerate(ids):
        if cid in legacy_ids:
            continue  # Old R2 remains closed; do not select its finalists again.
        yearly = {str(y): float(matrix.loc[year_array == y, cid].mean())
                  if (year_array == y).any() else None for y in YEARS}
        pooled = float(matrix[cid].mean())
        conditions = dict(
            complete_oof=True, all_three_years_present=all(v is not None for v in yearly.values()),
            pooled_positive=pooled > 0, year2025_positive=yearly["2025"] is not None and yearly["2025"] > 0,
            two_of_three_years_positive=sum(v is not None and v > 0 for v in yearly.values()) >= 2,
            nonzero_bootstrap_se=bool(np.isfinite(se[j]) and se[j] > evidence.SE_TOL),
            simultaneous_lower_positive=bool(np.isfinite(lower[j]) and lower[j] > 0))
        summaries.append(dict(
            test_id=cid, test_kind="SCIENTIFIC_CANDIDATE" if cid in ROLES else "FIXED_MECHANISM_CONTRAST",
            pooled_edge=pooled, year_edges=yearly,
            bootstrap_se=float(se[j]) if np.isfinite(se[j]) else None,
            simultaneous_lower_95=float(lower[j]) if np.isfinite(lower[j]) else None,
            research_support_conditions=conditions, mechanism_supported=all(conditions.values()),
            strict_PIT_promotion_eligible=False, economic_promotion_allowed=False))
    receipt.update(
        exposure_namespace=99, candidate_namespace=95, contrast_namespace=4,
        numeric_complete_series=len(ids), legacy_numeric_complete_series=len(legacy_ids),
        legacy_failed_series="metadata only; not fabricated numeric placeholders",
        legacy_shared_draw_sha256=old_receipt["shared_draw_sha256"],
        legacy_critical_max_t=old_receipt["critical_max_t"],
        draw_wise_legacy_max_not_exceeded_downward=True,
        minimum_draw_wise_max_increment=float((maxima - old_maxima).min()),
        legacy_R2_reselected=False)
    return matrix, summaries, receipt, maxima, failed_contrasts


def _pinned(item, paths, kind):
    path = Path(item["path"]).resolve()
    root = paths.backtest_root if kind == "backtest" else paths.results_root
    if not path.is_relative_to(root.resolve()) or sha(path) != item["sha256"]:
        raise ValueError("FROZEN_ARTIFACT_PIN_CHANGED:" + str(path))
    return path


def _clock(legacy, paths):
    edge_path = _pinned(legacy["edge"], paths, "backtest")
    clock_path = _pinned(legacy["clock"], paths, "backtest")
    # Physical boundary proof precedes all date/value projections.
    clock = pre2026(clock_path, ["signal_date", "included"], "signal_date")
    clock["signal_date"] = pd.to_datetime(clock.signal_date)
    if (clock.signal_date.duplicated().any() or not clock.signal_date.is_monotonic_increasing
            or clock.included.isna().any() or not pd.api.types.is_bool_dtype(clock.included)
            or set(clock.signal_date.dt.year) != set(YEARS)):
        raise ValueError("EXACT_OLD_COMMON_DATE_CLOCK_REQUIRED")
    included = clock.included.to_numpy(bool)
    index = pd.DatetimeIndex(clock.loc[included, "signal_date"])
    counts = {str(y): int((index.year == y).sum()) for y in YEARS}
    if len(index) != 732 or counts != YEAR_COUNTS:
        raise ValueError("DO_NOT_DROP_2023_OR_CHANGE_OLD_732_DATES")
    # Read complete series only. Failed legacy columns, if present in old
    # evidence, are not consumed as observations.
    cols = ["signal_date", *legacy["complete_ids"]]
    edge = pre2026(edge_path, cols, "signal_date")
    edge["signal_date"] = pd.to_datetime(edge.signal_date)
    edge = edge.set_index("signal_date")
    if not edge.index.equals(index):
        raise ValueError("OLD_EDGE_AND_MATURITY_CLOCK_MUST_MATCH_EXACTLY")
    return clock, edge, edge_path, clock_path


def run(run_directory):
    root = Path(run_directory).resolve()
    paths = resolve(REPO)
    assert_safe_output_path(root, kind="backtest", paths=paths)
    cfg = readj(root / "run_config.json")
    freeze = root / "DESIGN_FREEZE.json"
    freeze_hash = sha(freeze)
    if (freeze_hash != readj(root / "DESIGN_FREEZE_SHA.json")["sha256"]
            or freeze_hash != cfg["design_freeze_sha256"]
            or cfg.get("research_line") != "C_SELECTOR"):
        raise ValueError("FROZEN_C_SELECTOR_RUN_REQUIRED")
    design = readj(freeze)
    ev = validate_design(design)
    if cfg.get("research_id") != design["research_id"]:
        raise ValueError("CANONICAL_RESEARCH_ID_MISMATCH")
    required_sources = (Path(__file__), Path(evidence.__file__),
                        REPO / "scripts/research/a2/evaluation/selector_account_compare.py")
    for source in required_sources:
        if design.get("sources", {}).get(str(source)) != sha(source):
            raise ValueError("FROZEN_EVALUATION_SOURCE_CHANGED:" + str(source))
    results = Path(cfg["results_directory"]).resolve()
    out = root / "diagnostics/selector_evidence"
    assert_safe_output_path(results, kind="results", paths=paths)
    assert_safe_output_path(out, kind="backtest", paths=paths)
    if ((results / "SELECTION_EVIDENCE.json").exists()
            or (out / "SELECTION_EVIDENCE.json").exists()):
        raise FileExistsError("PRESERVE_EXISTING_FROZEN_HISTORY_EVIDENCE")
    assembly_path = root / "SCORE_ASSEMBLY.json"
    activation = readj(root / "EVALUATION_CODE_ACTIVATION.json")
    if (activation.get("design_freeze_sha256") != freeze_hash
            or activation.get("score_assembly_sha256") != sha(assembly_path)
            or any(activation.get("sources", {}).get(str(s)) != sha(s)
                   for s in required_sources)):
        raise ValueError("ASSEMBLY_AND_EVALUATION_ACTIVATION_REQUIRED")
    assembly = readj(assembly_path)
    complete = assembly["complete_candidates"]
    references = assembly["complete_fixed_references"]
    failed = assembly["failed_or_untestable"]
    if (len(set(complete)) != len(complete) or len(set(references)) != len(references)
            or not set(complete).issubset(ROLES) or not set(references).issubset(REFERENCES)
            or (set(complete) | set(references)) & set(failed)
            or set(complete) | set(references) | set(failed) != set(ROLES + REFERENCES)
            or assembly.get("forecast2026_rows") != 0
            or assembly.get("mechanism_research_eligible") is not True
            or assembly.get("strict_PIT_promotion_eligible") is not False):
        raise ValueError("EVERY_FROZEN_ROLE_REQUIRES_EXPLICIT_READINESS")
    legacy = ev["legacy"]
    # Verify original identities without rerunning or reopening their experiments.
    _pinned(legacy["design"], paths, "backtest")
    _pinned(legacy["assembly"], paths, "backtest")
    old_design = readj(legacy["design"]["path"])
    old_assembly = readj(legacy["assembly"]["path"])
    if (old_design["candidates"] != legacy["candidate_ids"]
            or old_assembly["complete_candidates"] != legacy["complete_ids"]
            or old_assembly["failed_or_untestable"] != legacy["failed_or_untestable"]):
        raise ValueError("ORIGINAL_91_ROLE_EXPOSURE_CHANGED")
    training = _pinned(design["inputs"]["training"], paths, "results")
    evidence.prove_label_boundary(training, "target_end_date")
    raw_path = score_path(root, evidence.RAW)
    evidence.prove_label_boundary(raw_path, "label_end_date", allow_null=True)
    reference, raw_hash = score_panel(root, evidence.RAW)
    evidence.validate_rank(reference)
    labels = pre2026(raw_path, evidence.KEY + ["target", "label_end_date"], "signal_date")
    labels["signal_date"] = pd.to_datetime(labels.signal_date)
    if not labels.loc[labels.label_end_date.isna(), "target"].isna().all():
        raise ValueError("TARGET_WITH_UNKNOWN_LABEL_MATURITY")
    reference = reference.merge(labels, on=evidence.KEY, validate="one_to_one", how="left")
    if (len(reference) != assembly["common_rows"]
            or reference.signal_date.nunique() != assembly["common_dates"]):
        raise ValueError("RAW_FULL_U_T_AND_ASSEMBLY_MUST_MATCH")
    arrays = {evidence.RAW: (reference.score.to_numpy(float), reference["rank"].to_numpy(float))}
    hashes = {evidence.RAW: raw_hash}
    selected_union = reference["rank"].le(20).to_numpy(copy=True)
    for cid in [*complete, *references]:
        panel, digest = score_panel(root, cid)
        evidence.validate_rank(panel)
        evidence.align(reference, panel)
        arrays[cid] = (panel.score.to_numpy(float), panel["rank"].to_numpy(float))
        hashes[cid] = digest
        selected_union |= panel["rank"].le(20).to_numpy()
    mature, new_maturity = evidence.maturity(reference, selected_union)
    clock, old_edges, edge_path, clock_path = _clock(legacy, paths)
    calendar = pd.DatetimeIndex(clock.signal_date)
    raw_calendar = pd.DatetimeIndex(sorted(reference.signal_date.unique()))
    if not raw_calendar.equals(calendar):
        raise ValueError("FULL_U_T_CALENDAR_MUST_MATCH_ORIGINAL")
    if (not new_maturity.signal_date.equals(clock.signal_date)
            or not new_maturity.loc[clock.included, "included"].all()):
        raise ValueError("NEW_SELECTED_LABELS_IMMATURE_ON_ORIGINAL_COMMON_DATE_NO_SHRINK")
    common = clock.set_index("signal_date").included
    daily = pd.DataFrame([
        row for cid, (scores, ranks) in arrays.items()
        for row in evidence.diagnose(cid, reference, scores, ranks, arrays[evidence.RAW][1], mature, common)
    ])
    common_index = old_edges.index
    new_edges = pd.DataFrame(index=common_index)
    for cid in [*complete, *references]:
        edge = daily.loc[daily.candidate_id.eq(cid) & daily.common_mature_date]
        new_edges[cid] = edge.set_index("signal_date").replacement_edge.reindex(common_index)
    matrix, summaries, bootstrap, maxima, failed_contrasts = statistics(
        old_edges, new_edges, np.flatnonzero(clock.included.to_numpy(bool)), calendar,
        ev["bootstrap"], legacy["complete_ids"])
    supported = [s["test_id"] for s in summaries
                 if s["test_kind"] == "SCIENTIFIC_CANDIDATE" and s["mechanism_supported"]]
    receipt = dict(
        schema="C_FROZEN_HISTORY_SELECTION_EVIDENCE_V1",
        status="MECHANISM_EVIDENCE_COMPLETE", research_id=design["research_id"],
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        financial_verified=False, economic_promotion_allowed=False,
        strict_PIT_production_upgrade=False, research_supported_roles=supported,
        finalists=[], finalist_status="NO_PRODUCTION_PROMOTION_FROZEN_HISTORY_ONLY",
        design_freeze_sha256=freeze_hash, score_assembly_sha256=sha(assembly_path),
        evaluation_source_sha256=sha(Path(__file__)), score_sha256=hashes,
        candidates=[s for s in summaries if s["test_kind"] == "SCIENTIFIC_CANDIDATE"],
        fixed_mechanism_contrasts=[s for s in summaries if s["test_kind"] == "FIXED_MECHANISM_CONTRAST"],
        bootstrap=bootstrap, failed_or_untestable=failed, failed_contrasts=failed_contrasts,
        legacy_failed_or_untestable=legacy["failed_or_untestable"],
        legacy_exposure_roles=legacy["candidate_ids"],
        legacy_R2_disposition="FINALIST_NONE_NO_PROMOTION_CLOSED",
        legacy_daily_edge_sha256=sha(edge_path), legacy_common_clock_sha256=sha(clock_path),
        label_source_sha256=design["inputs"]["training"]["sha256"],
        common_mature_dates=732, common_year_dates=YEAR_COUNTS,
        excluded_dates=int((~clock.included).sum()),
        frozen_history_limitations=[
            "Source is an explicitly authorized frozen-history research snapshot; strict historical revision/vintage authority remains unproved.",
            "Risk target/horizon unchanged: 1D frozen return proxy features; MEAN_ER_3D_5D_10D_20D target.",
            "2025 and earlier C outcomes were exposed; new identity does not create an independent holdout.",
            "Complete old series share the exact original maturity clock and bootstrap draws; failed trials remain exposure metadata.",
            "Selection-label evidence does not establish executable net profit, corporate-action completeness or a strict-PIT production upgrade.",
        ],
        identification=dict(monthly_vs_annual="same fixed core, head, target and identity policy; cadence differs",
                            full_vs_flag_only="same monthly history and base OOF; risk magnitude/structure vs coverage flags"),
        diagnostics_directory=str(out), run_directory=str(root),
        test2026_locked=True, monthly2026_estimation_authorized=False,
        test2026_rows_read_by_this_runner=0)
    metrics = ["ic", "spearman_ic", "ndcg20", "truth_top20_recall",
               "top20_target_mean", "precision_target_positive", "overlap20",
               "score_std", "score_iqr", "rank_migration_mean_absolute"]
    year_diagnostics = daily.assign(year=daily.signal_date.dt.year).groupby(
        ["candidate_id", "year"])[metrics].mean().reset_index()
    out.mkdir(parents=True, exist_ok=True)
    audit_clock = clock.copy()
    audit_clock["new_selected_union_mature"] = new_maturity.included.to_numpy(bool)
    audit_clock.to_parquet(out / "COMMON_DATE_MATURITY.parquet", index=False)
    daily.to_parquet(out / "DAILY_DIAGNOSTICS.parquet", index=False)
    year_diagnostics.to_parquet(out / "YEAR_DIAGNOSTICS.parquet", index=False)
    matrix.rename_axis("signal_date").reset_index().to_parquet(out / "PRIMARY_DAILY_EDGE.parquet", index=False)
    pd.DataFrame({"replicate": np.arange(len(maxima)),
                  "centered_standardized_max_t": maxima}).to_parquet(out / "BOOTSTRAP_MAXT.parquet", index=False)
    receipt["diagnostic_sha256"] = {p.name: sha(p) for p in out.glob("*.parquet")}
    evidence.putj(out / "SELECTION_EVIDENCE.json", receipt)
    results.mkdir(parents=True, exist_ok=True)
    evidence.putj(results / "SELECTION_EVIDENCE.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    receipt = run(parser.parse_args().run)
    print(json.dumps({k: receipt[k] for k in
                      ("status", "research_id", "mechanism_research_eligible",
                       "strict_PIT_promotion_eligible", "common_mature_dates",
                       "research_supported_roles")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

