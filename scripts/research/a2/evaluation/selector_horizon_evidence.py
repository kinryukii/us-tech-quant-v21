"""Target-horizon evidence binding; reuse frozen selector statistics and readers.

Only target horizon changes.  All comparisons use the inherited mean-ER endpoint;
MEAN heads are exact-reuse references, never new trials or exposure entries.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.common.storage_paths import assert_safe_output_path, resolve
from scripts.research.a2.evaluation import selector_evidence as evidence
from scripts.research.a2.evaluation import selector_algorithm_breadth_evidence as r5
from scripts.research.a2.evaluation.selector_account_compare import pre2026, readj, score_panel, score_path, sha

REPO = Path(__file__).resolve().parents[4]
RESEARCH_ID = "V24_C_SELECTOR_TARGET_HORIZON_BREADTH_C7"
ANCHORS = ("HORIZON_MEAN_RIDGE", "HORIZON_MEAN_HGB")
ROLES = tuple(f"HORIZON_ER_{h}D_{head}" for h in (3, 5, 10, 20) for head in ("RIDGE", "HGB"))
ALL_ROLES = (*ANCHORS, *ROLES)
CONTRASTS = tuple((f"{role}_VS_MEAN", role, f"HORIZON_MEAN_{role.rsplit('_', 1)[1]}") for role in ROLES)
TEST_IDS = (*ROLES, *(c[0] for c in CONTRASTS))
YEARS, YEAR_COUNTS, PRIMARY, BOOT_METHOD = r5.YEARS, r5.YEAR_COUNTS, r5.PRIMARY, r5.BOOT_METHOD
TARGET = "MEAN_ER_3D_5D_10D_20D"


def validate_design(design):
    if not (design.get("official_freeze") is True and design.get("formal_freeze_applied") is True):
        raise ValueError("FORMAL_FREEZE_REQUIRED")
    if (design.get("research_id") != RESEARCH_ID or tuple(design.get("roles", ())) != ALL_ROLES
            or design.get("target") != TARGET or tuple(design.get("primary_eval_years", ())) != YEARS):
        raise ValueError("TEN_HORIZON_ROLES_UNIFORM_MEAN_ENDPOINT_REQUIRED")
    if (design.get("mechanism_research_eligible") is not True
            or design.get("strict_PIT_promotion_eligible") is not False
            or design.get("test2026_locked") is not True
            or design.get("new2026_estimation_authorized") is not False):
        raise ValueError("MECHANISM_ONLY_2026_LOCK_REQUIRED")
    ev = design["evaluation"]
    if (ev.get("primary") != PRIMARY or ev.get("common_mature_date_count") != 732
            or ev.get("year_counts") != YEAR_COUNTS or ev.get("exposure_namespace") != 133):
        raise ValueError("ORIGINAL_732_CLOCK_AND_133_EXPOSURE_REQUIRED")
    rule = ev["bootstrap"]
    if (rule.get("method") != BOOT_METHOD or rule.get("repeats") != 5000
            or rule.get("seed") != 20260928 or rule.get("confidence") != .95
            or rule.get("family_candidates") != 121):
        raise ValueError("ORIGINAL_SHARED_MAXT_RULE_REQUIRED")
    expected = dict(pooled_edge_positive=True, year2025_edge_positive=True,
                    positive_years_min=2, simultaneous_lower_bound_gt_zero=True)
    if any(ev.get("inherited_selection_requirements", {}).get(k) != v for k, v in expected.items()):
        raise ValueError("ORIGINAL_SELECTION_THRESHOLD_REQUIRED")
    legacy = ev["legacy"]
    numeric, exposure, failed = (legacy[k] for k in ("numeric_ids", "exposure_ids", "failed_or_untestable"))
    if (len(numeric) != 105 or len(set(numeric)) != 105
            or len(exposure) != 117 or len(set(exposure)) != 117 or len(failed) != 12
            or set(numeric) & set(failed) or set(numeric) | set(failed) != set(exposure)
            or set(exposure) & set(ALL_ROLES + TEST_IDS)):
        raise ValueError("CLOSED_105_NUMERIC_117_EXPOSURE_HISTORY_REQUIRED")
    if ev.get("fixed_mechanism_pairs") != [[a, b] for _, a, b in CONTRASTS]:
        raise ValueError("EIGHT_SAME_HEAD_MEAN_CONTRASTS_REQUIRED")
    if ev.get("mechanism_support") != "RAW_ENDPOINT_AND_MATCHED_MEAN_BOTH_PASS":
        raise ValueError("RAW_AND_MATCHED_MEAN_SUPPORT_REQUIRED")
    return ev


def statistics(legacy_edges, new_edges, positions, calendar, rule, legacy_ids, failed=None):
    """Delegate shared draws/maxT to the existing owner, retaining all old tests."""
    legacy_ids, failed = list(legacy_ids), dict(failed or {})
    calendar = pd.DatetimeIndex(calendar)
    if (len(legacy_ids) != 105 or len(set(legacy_ids)) != 105
            or list(legacy_edges.columns) != legacy_ids or legacy_edges.index.has_duplicates
            or not legacy_edges.index.equals(new_edges.index) or new_edges.columns.has_duplicates
            or not set(new_edges).issubset(TEST_IDS) or not set(failed).issubset(TEST_IDS)
            or set(new_edges) & set(failed) or not np.isfinite(legacy_edges.to_numpy(float)).all()
            or not np.isfinite(new_edges.to_numpy(float)).all()
            or calendar.hasnans or calendar.has_duplicates or not calendar.is_monotonic_increasing
            or (calendar >= pd.Timestamp("2026-01-01")).any()):
        raise ValueError("EXACT_FINITE_PRE2026_COMMON_CLOCK_REQUIRED")
    positions = np.asarray(positions)
    if (not np.issubdtype(positions.dtype, np.integer) or len(positions) != len(legacy_edges)
            or (positions < 0).any() or (positions >= len(calendar)).any()
            or not np.all(np.diff(positions) > 0) or not calendar[positions].equals(legacy_edges.index)):
        raise ValueError("ORIGINAL_CALENDAR_POSITIONS_REQUIRED")
    for cid, role, _ in CONTRASTS:
        if (cid in new_edges) != (role in new_edges):
            raise ValueError("ROLE_AND_MATCHED_MEAN_REQUIRE_IDENTICAL_READINESS")
    matrix = legacy_edges.copy()
    for cid in TEST_IDS:
        if cid in new_edges:
            matrix[cid] = new_edges[cid]
        else:
            failed.setdefault(cid, "INCOMPLETE_FROZEN_ROLE_OR_DEPENDENCY")
    ids = list(matrix)
    _, _, old_receipt, old_maxima = evidence.shared_max_t(legacy_edges.to_numpy(float), positions,
        [True] * 105, {**rule, "family_candidates": 105})
    lower, se, receipt, maxima = evidence.shared_max_t(matrix.to_numpy(float), positions,
        [True] * len(ids), {**rule, "family_candidates": len(ids)})
    if (receipt.get("status") != "COMPLETE" or old_receipt.get("status") != "COMPLETE"
            or receipt["shared_draw_sha256"] != old_receipt["shared_draw_sha256"]
            or len(maxima) != len(old_maxima) or np.any(maxima + 1e-12 < old_maxima)
            or receipt["critical_max_t"] + 1e-12 < old_receipt["critical_max_t"]):
        raise ValueError("JOINT_MAXT_MUST_NOT_LOWER_LEGACY_THRESHOLD")
    summaries = []
    for cid in TEST_IDS:
        complete = cid in matrix
        j = ids.index(cid) if complete else None
        yearly = {str(y): float(matrix.loc[matrix.index.year == y, cid].mean())
                  if complete and (matrix.index.year == y).any() else None for y in YEARS}
        pooled = float(matrix[cid].mean()) if complete else None
        conditions = dict(complete_oof=complete, all_three_years_present=all(v is not None for v in yearly.values()),
            pooled_positive=pooled is not None and pooled > 0,
            year2025_positive=yearly["2025"] is not None and yearly["2025"] > 0,
            two_of_three_years_positive=sum(v is not None and v > 0 for v in yearly.values()) >= 2,
            nonzero_bootstrap_se=bool(complete and np.isfinite(se[j]) and se[j] > evidence.SE_TOL),
            simultaneous_lower_positive=bool(complete and np.isfinite(lower[j]) and lower[j] > 0))
        summaries.append(dict(candidate_id=cid, test_id=cid,
            test_kind="MATCHED_MEAN_CONTRAST" if cid.endswith("_VS_MEAN") else "RAW_ENDPOINT",
            status="COMPLETE" if complete else "FAILED_UNTESTABLE", failure_reason=failed.get(cid),
            pooled_edge=pooled, year_edges=yearly,
            bootstrap_se=float(se[j]) if complete and np.isfinite(se[j]) else None,
            simultaneous_lower_95=float(lower[j]) if complete and np.isfinite(lower[j]) else None,
            research_support_conditions=conditions, mechanism_supported=all(conditions.values()),
            strict_PIT_promotion_eligible=False, economic_promotion_allowed=False))
    lookup = {s["test_id"]: s for s in summaries}
    for cid, role, _ in CONTRASTS:
        result = lookup[role]
        result["endpoint_supported"] = result["mechanism_supported"]
        result["matched_mean_contrast_supported"] = lookup[cid]["mechanism_supported"]
        result["research_support_conditions"]["matched_mean_contrast_supported"] = lookup[cid]["mechanism_supported"]
        result["mechanism_supported"] = all(result["research_support_conditions"].values())
    receipt.update(exposure_namespace=133, new_exposure_tests=16, new_candidate_roles=8,
        exact_reused_mean_anchors=2, legacy_exposure_namespace=117,
        numeric_complete_series=len(ids), legacy_numeric_complete_series=105,
        failed_series="exposure metadata only; no numeric zero placeholders",
        legacy_shared_draw_sha256=old_receipt["shared_draw_sha256"], legacy_critical_max_t=old_receipt["critical_max_t"],
        draw_wise_legacy_max_not_exceeded_downward=True,
        minimum_draw_wise_max_increment=float((maxima - old_maxima).min()),
        legacy_R2_reselected=False, legacy_R4_reselected=False, legacy_R5_reselected=False)
    return matrix, summaries, receipt, maxima


def _legacy_identity(legacy, paths):
    """Only pinned R5 design/assembly metadata; never reopen its outcome selection."""
    design = readj(r5._pinned(legacy["design"], paths, "backtest"))
    assembly = readj(r5._pinned(legacy["assembly"], paths, "backtest"))
    ev = r5.validate_design(design)
    if (assembly.get("complete_candidates") != list(r5.ROLES) or assembly.get("failed_or_untestable") != {}
            or assembly.get("design_freeze_sha256") != legacy["design"]["sha256"]
            or legacy["numeric_ids"] != [*ev["legacy"]["numeric_ids"], *r5.ROLES]
            or legacy["exposure_ids"] != [*ev["legacy"]["exposure_ids"], *r5.ROLES]
            or legacy["failed_or_untestable"] != ev["legacy"]["failed_or_untestable"]):
        raise ValueError("CLOSED_R5_NUMERIC_AND_EXPOSURE_IDENTITIES_CHANGED")


def _bound_panel(root, cid, assembly):
    binding = assembly["score_paths"][cid]
    actual = score_path(root, cid).resolve()
    if actual != Path(binding["path"]).resolve() or sha(actual) != binding["sha256"]:
        raise ValueError("ASSEMBLED_SCORE_BINDING_CHANGED:" + cid)
    panel, digest = score_panel(root, cid)
    evidence.validate_rank(panel)
    return panel, digest


def run(run_directory):
    root, paths = Path(run_directory).resolve(), resolve(REPO)
    assert_safe_output_path(root, kind="backtest", paths=paths)
    from scripts.research.a2.training import selector_horizon_breadth as training
    cfg, design = training.checked(root)
    ev = validate_design(design)
    freeze_hash = sha(root / "DESIGN_FREEZE.json")
    results, out = Path(cfg["results_directory"]).resolve(), root / "diagnostics/selector_evidence"
    assert_safe_output_path(results, kind="results", paths=paths)
    assert_safe_output_path(out, kind="backtest", paths=paths)
    if (results / "SELECTION_EVIDENCE.json").exists() or (out / "SELECTION_EVIDENCE.json").exists():
        raise FileExistsError("PRESERVE_EXISTING_HORIZON_EVIDENCE")
    assembly_path = root / "SCORE_ASSEMBLY.json"
    activation = readj(root / "EVALUATION_CODE_ACTIVATION.json")
    sources = (Path(__file__), Path(evidence.__file__), Path(r5.__file__),
               REPO / "scripts/research/a2/evaluation/selector_account_compare.py")
    if (activation.get("design_freeze_sha256") != freeze_hash
            or activation.get("score_assembly_sha256") != sha(assembly_path)
            or any(activation.get("sources", {}).get(str(s)) != sha(s)
                   or design.get("sources", {}).get(str(s)) != sha(s) for s in sources)):
        raise ValueError("FROZEN_EVALUATION_AND_ASSEMBLY_ACTIVATION_REQUIRED")
    assembly = readj(assembly_path)
    complete, failed = assembly["complete_candidates"], dict(assembly["failed_or_untestable"])
    if (len(set(complete)) != len(complete) or not set(complete).issubset(ROLES)
            or set(complete) & set(failed) or set(complete) | set(failed) != set(ROLES)
            or assembly.get("complete_fixed_references") != list(ANCHORS)
            or assembly.get("forecast2026_rows") != 0 or assembly.get("design_freeze_sha256") != freeze_hash):
        raise ValueError("EVERY_NEW_ROLE_AND_TWO_REUSED_ANCHORS_REQUIRE_BOUND_READINESS")
    legacy = ev["legacy"]
    _legacy_identity(legacy, paths)
    training_path = r5._pinned(design["inputs"]["training"], paths, "results")
    evidence.prove_label_boundary(training_path, "target_end_date")
    clock, old_edges, edge_path, clock_path = r5._clock(legacy, paths)
    raw_path = score_path(root, evidence.RAW)
    raw_binding = assembly["score_paths"][evidence.RAW]
    if raw_path.resolve() != Path(raw_binding["path"]).resolve() or sha(raw_path) != raw_binding["sha256"]:
        raise ValueError("ASSEMBLED_RAW_SCORE_BINDING_CHANGED")
    evidence.prove_label_boundary(raw_path, "label_end_date", allow_null=True)
    reference, raw_hash = _bound_panel(root, evidence.RAW, assembly)
    labels = pre2026(raw_path, evidence.KEY + ["target", "label_end_date"], "signal_date")
    labels["signal_date"] = pd.to_datetime(labels.signal_date)
    if not labels.loc[labels.label_end_date.isna(), "target"].isna().all():
        raise ValueError("TARGET_WITH_UNKNOWN_LABEL_MATURITY")
    reference = reference.merge(labels, on=evidence.KEY, validate="one_to_one", how="left")
    calendar = pd.DatetimeIndex(clock.signal_date)
    if (len(reference) != assembly["common_rows"] or reference.signal_date.nunique() != assembly["common_dates"]
            or not pd.DatetimeIndex(sorted(reference.signal_date.unique())).equals(calendar)):
        raise ValueError("FULL_U_T_MUST_RETAIN_ORIGINAL_752_CALENDAR")
    arrays = {evidence.RAW: (reference.score.to_numpy(float), reference["rank"].to_numpy(float))}
    hashes, maturity_rows = {evidence.RAW: raw_hash}, []
    raw_selected = reference["rank"].le(20).to_numpy()
    mature, raw_maturity = evidence.maturity(reference, raw_selected)
    if not raw_maturity.loc[clock.included, "included"].all():
        raise ValueError("RAW_IMMATURE_ON_ORIGINAL_COMMON_DATE")
    for cid in ANCHORS:
        panel, digest = _bound_panel(root, cid, assembly)
        evidence.align(reference, panel)
        _, maturity = evidence.maturity(reference, raw_selected | panel["rank"].le(20).to_numpy())
        if not maturity.loc[clock.included, "included"].all():
            raise ValueError("FIXED_MEAN_ANCHOR_IMMATURE_ON_ORIGINAL_COMMON_DATE:" + cid)
        arrays[cid], hashes[cid] = (panel.score.to_numpy(float), panel["rank"].to_numpy(float)), digest
    for cid in ROLES:
        if cid not in complete:
            continue
        panel, digest = _bound_panel(root, cid, assembly)
        evidence.align(reference, panel)
        _, maturity = evidence.maturity(reference, raw_selected | panel["rank"].le(20).to_numpy())
        maturity["candidate_id"] = cid
        maturity_rows.append(maturity)
        if not maturity.loc[clock.included, "included"].all():
            failed[cid] = "NEW_SELECTED_LABELS_IMMATURE_ON_ORIGINAL_COMMON_DATE_NO_SHRINK"
            continue
        arrays[cid], hashes[cid] = (panel.score.to_numpy(float), panel["rank"].to_numpy(float)), digest
    for contrast, role, _ in CONTRASTS:
        if role not in arrays:
            failed[contrast] = "DEPENDENCY_FAILED:" + role + ":" + failed.get(role, "INCOMPLETE_ROLE")
    common = clock.set_index("signal_date").included
    diagnostics = [row for cid, (scores, ranks) in arrays.items()
        for row in evidence.diagnose(cid, reference, scores, ranks, arrays[evidence.RAW][1], mature, common)]
    for contrast, role, anchor in CONTRASTS:
        if role in arrays:
            scores, ranks = arrays[role]
            diagnostics.extend(evidence.diagnose(contrast, reference, scores, ranks, arrays[anchor][1], mature, common))
    daily = pd.DataFrame(diagnostics)
    new_edges = pd.DataFrame(index=old_edges.index)
    for cid in TEST_IDS:
        if cid not in failed:
            rows = daily.loc[daily.candidate_id.eq(cid) & daily.common_mature_date]
            new_edges[cid] = rows.set_index("signal_date").replacement_edge.reindex(old_edges.index)
    matrix, summaries, bootstrap, maxima = statistics(old_edges, new_edges,
        np.flatnonzero(clock.included.to_numpy(bool)), calendar, ev["bootstrap"], legacy["numeric_ids"], failed)
    candidates = [s for s in summaries if s["test_id"] in ROLES]
    contrasts = [s for s in summaries if s["test_id"] not in ROLES]
    receipt = dict(schema="C_TARGET_HORIZON_SELECTION_EVIDENCE_V1", status="MECHANISM_EVIDENCE_COMPLETE",
        research_id=RESEARCH_ID, mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        financial_verified=False, economic_promotion_allowed=False, strict_PIT_production_upgrade=False,
        research_supported_roles=[s["candidate_id"] for s in candidates if s["mechanism_supported"]],
        finalists=[], finalist_status="NO_PRODUCTION_PROMOTION_FROZEN_HISTORY_ONLY",
        design_freeze_sha256=freeze_hash, score_assembly_sha256=sha(assembly_path),
        evaluation_source_sha256=sha(Path(__file__)), score_sha256=hashes,
        candidates=candidates, contrasts=contrasts, tests=summaries, bootstrap=bootstrap,
        failed_or_untestable=failed, exposure_namespace=133, exposure_roles=[*legacy["exposure_ids"], *TEST_IDS],
        exact_reused_mean_anchors=list(ANCHORS), anchors_are_new_exposure=False,
        mechanism_support_rule="RAW_ENDPOINT_AND_MATCHED_MEAN_BOTH_PASS",
        unified_evaluation_target=TARGET,
        legacy_failed_or_untestable=legacy["failed_or_untestable"],
        legacy_exposure_roles=legacy["exposure_ids"], legacy_numeric_ids=legacy["numeric_ids"],
        legacy_R2_disposition="CLOSED_NO_RESELECTION_NO_PROMOTION",
        legacy_R4_disposition="CLOSED_NO_RESELECTION_NO_PROMOTION",
        legacy_R5_disposition="NO_RESELECTION_NO_PROMOTION",
        legacy_daily_edge_sha256=sha(edge_path), legacy_common_clock_sha256=sha(clock_path),
        label_source_sha256=design["inputs"]["training"]["sha256"], common_mature_dates=732,
        common_year_dates=YEAR_COUNTS, original_calendar_dates=752, excluded_dates=int((~clock.included).sum()),
        claim="Frozen-history target-horizon mechanism evidence; exposed development; no executable profit claim",
        diagnostics_directory=str(out), run_directory=str(root),
        test2026_locked=True, new2026_estimation_authorized=False,
        test2026_rows_read=0, test2026_rows_read_by_this_runner=0)
    out.mkdir(parents=True, exist_ok=True)
    clock.to_parquet(out / "COMMON_DATE_MATURITY.parquet", index=False)
    daily.to_parquet(out / "DAILY_DIAGNOSTICS.parquet", index=False)
    metrics = ["ic", "spearman_ic", "ndcg20", "truth_top20_recall", "top20_target_mean",
               "precision_target_positive", "overlap20", "score_std", "score_iqr", "rank_migration_mean_absolute"]
    daily.assign(year=daily.signal_date.dt.year).groupby(["candidate_id", "year"])[metrics].mean().reindex(
        pd.MultiIndex.from_product([[evidence.RAW, *ANCHORS, *TEST_IDS], YEARS],
            names=["candidate_id", "year"])).reset_index().to_parquet(out / "YEAR_DIAGNOSTICS.parquet", index=False)
    if maturity_rows:
        pd.concat(maturity_rows, ignore_index=True).to_parquet(out / "ROLE_DATE_MATURITY.parquet", index=False)
    matrix.rename_axis("signal_date").reset_index().to_parquet(out / "PRIMARY_DAILY_EDGE.parquet", index=False)
    pd.DataFrame(dict(replicate=np.arange(len(maxima)), centered_standardized_max_t=maxima)).to_parquet(
        out / "BOOTSTRAP_MAXT.parquet", index=False)
    receipt["diagnostic_sha256"] = {p.name: sha(p) for p in out.glob("*.parquet")}
    evidence.putj(out / "SELECTION_EVIDENCE.json", receipt)
    evidence.putj(results / "SELECTION_EVIDENCE.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    print(run(args.run)["status"])
