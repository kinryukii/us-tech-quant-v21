"""Pure C14 risk-statistics continuation over physically verified frozen evidence.

No readers, writers, fits, solvers or old bootstrap calls. The caller verifies
artifact custody before supplying an independently pinned precomputed payload.
Only original evidence-owner primitives calculate new hypotheses.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import PureWindowsPath
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import selector_maximal_breadth_evidence as owner
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

SCHEMA = "C14_FROZEN_PRECOMPUTED_JOINT_V1"
ADDITIONS = set(owner.HYBRIDS + owner.GATES + owner.CLASSICAL + tuple(owner.CONTRASTS)) - {"C14_D12"}
need = owner._require


def _identifier(row):
    return row.get("candidate_id", row.get("test_id"))


def _finite(value):
    return isinstance(value, (int, float, np.number)) and not isinstance(value, (bool, np.bool_)) and np.isfinite(value)


def _rows(rows, ids, *, legacy=False):
    need([_identifier(r) for r in rows] == list(ids), "EXACT_ORDERED_PRECOMPUTED_SUMMARY_ROSTER_REQUIRED")
    for row in rows:
        complete = legacy or row.get("status") == "COMPLETE"
        need(not legacy or row.get("status", "COMPLETE") == "COMPLETE", "ALL147_LEGACY_NUMERIC_REQUIRED")
        mean, se, years = row.get("pooled_edge"), row.get("bootstrap_se"), row.get("year_edges")
        need(isinstance(years, dict) and set(years) == {"2023", "2024", "2025"},
             "ALL_PRECOMPUTED_YEAR_COORDINATES_REQUIRED")
        if complete:
            need(_finite(mean) and _finite(se) and se >= 0, "FINITE_PRECOMPUTED_MEAN_SE_REQUIRED")
            progressive = not legacy and row["domain"] == "PROGRESSIVE_482"
            need(all(_finite(years[y]) for y in (("2024", "2025") if progressive else tuple(years)))
                 and (not progressive or years["2023"] is None), "NO_PRECOMPUTED_YEAR_TRIMMING_OR_FILL")
        else:
            need(isinstance(row.get("failure_reason"), str) and bool(row["failure_reason"])
                 and mean is None and se is None and all(v is None for v in years.values()),
                 "FAILED_HYPOTHESIS_CANNOT_HAVE_ZERO_PLACEHOLDER")


def _precomputed(payload, expected_sha256, clock, rule, legacy_ids, specs):
    need(owner._sha(expected_sha256) and content_hash(payload) == expected_sha256,
         "INDEPENDENT_PRECOMPUTED_CONTENT_PIN_REQUIRED")
    need(payload.get("schema") == SCHEMA and payload.get("research_id") == owner.RESEARCH_ID
         and payload.get("strict_PIT_promotion_eligible") is False
         and payload.get("clock_sha256") == content_hash(clock)
         and payload.get("legacy_ids") == list(legacy_ids), "EXACT_FROZEN_PRECOMPUTED_IDENTITY_REQUIRED")
    custody = payload.get("source_custody", {})
    refs = custody.get("artifact_refs", {})
    need(custody.get("status") == "PHYSICAL_FROZEN_EVIDENCE_VERIFIED"
         and custody.get("physical_sha256_verified") is True
         and set(refs) == {"c14_evidence", "c14_maxima", "legacy_summaries"},
         "CALLER_VERIFIED_FROZEN_ARTIFACT_CUSTODY_REQUIRED")
    roots = (PureWindowsPath("D:/us-tech-quant-backtests"), PureWindowsPath("D:/us-tech-quant-results"))
    for ref in refs.values():
        path = PureWindowsPath(ref.get("path", ""))
        need(owner._sha(ref.get("sha256")) and path.is_absolute()
             and ".." not in path.parts and any(root in path.parents for root in roots), "EXTERNAL_FROZEN_EVIDENCE_REFERENCE_REQUIRED")
    receipt = payload["bootstrap"]
    need(receipt.get("status") == "COMPLETE" and receipt.get("repeats") == rule["repeats"]
         and receipt.get("block_sessions") == 20 and receipt.get("seed") == 20260928
         and receipt.get("quantile_method") == "higher" and receipt.get("se_ddof") == 1
         and receipt.get("se_zero_tolerance") == owner.shared.SE_TOL
         and receipt.get("studentization") == "fixed bootstrap-SE plugin; no per-replicate SE refit"
         and receipt.get("centering") == "sample-centered observations, then conditional bootstrap mean recentered per column"
         and receipt.get("exposure_namespace") == 321 and receipt.get("legacy_numeric_complete_series") == 147
         and receipt.get("legacy_exposure_namespace") == 226
         and receipt.get("independent_holdout") is False and receipt.get("strict_PIT_promotion_eligible") is False,
         "REAL_FROZEN_SHARED_MAXT_RECEIPT_REQUIRED")
    maxima = np.asarray(payload["maxima"], float)
    need(maxima.shape == (rule["repeats"],) and np.isfinite(maxima).all()
         and _finite(receipt.get("critical_max_t"))
         and float(np.quantile(maxima, .95, method="higher")) == receipt["critical_max_t"]
         and _finite(receipt.get("legacy_critical_max_t"))
         and receipt["critical_max_t"] >= receipt["legacy_critical_max_t"]
         and _finite(receipt.get("minimum_draw_wise_max_increment"))
         and receipt["minimum_draw_wise_max_increment"] >= 0,
         "EXACT_REAL_PRECOMPUTED_MAXT_VECTOR_AND_HIGHER_THRESHOLD_REQUIRED")
    rows = payload["summaries"]
    need(all(r.get("status") != "COMPLETE" for r in rows
             if _identifier(r) in set(owner.DELTA) | {"C14_D12"}), "BLOCKED_BUDGET_CANNOT_BE_PRECOMPUTED_NUMERIC")
    _rows(rows, [s["candidate_id"] for s in specs])
    _rows(payload["legacy_summaries"], legacy_ids, legacy=True)
    need(all({k:r.get(k) for k in s} == s for r,s in zip(rows,specs)), "FROZEN_PRECOMPUTED_ROLE_SPECS_REQUIRED")
    risk_rows = receipt.get("risk_tests", [])
    need([r.get("candidate_id") for r in risk_rows] == [s["candidate_id"] for s in owner.RISK_SPECS],
         "ALL20_PRECOMPUTED_RISK_HYPOTHESES_REQUIRED")
    for row, spec in zip(risk_rows, owner.RISK_SPECS):
        need(all(row.get(k) == v for k,v in spec.items()), "EXACT_PRECOMPUTED_RISK_SPEC_REQUIRED")
        if row.get("status") == "COMPLETE":
            need(_finite(row.get("pooled_risk_improvement")) and _finite(row.get("bootstrap_se"))
                 and row["bootstrap_se"] >= 0, "FINITE_PRECOMPUTED_RISK_ESTIMATE_REQUIRED")
        else:
            need(isinstance(row.get("failure_reason"), str) and bool(row["failure_reason"])
                 and row.get("pooled_risk_improvement") is None and row.get("bootstrap_se") is None,
                 "UNKNOWN_RISK_HYPOTHESIS_CANNOT_BE_ZERO")
    all_se = [r["bootstrap_se"] for r in payload["legacy_summaries"]]
    all_se += [r["bootstrap_se"] for r in rows + risk_rows if r.get("status") == "COMPLETE"]
    need(receipt.get("numeric_complete_series") == len(all_se)
         and receipt.get("family_candidates") == len(all_se)
         and receipt.get("active_nonzero_se_columns") == sum(se > owner.shared.SE_TOL for se in all_se),
         "PRECOMPUTED_NUMERIC_AND_ACTIVE_COUNTS_MUST_MATCH")
    return deepcopy(rows), deepcopy(risk_rows), deepcopy(receipt), maxima.copy()


def _refresh_alpha(row, critical):
    complete = row["status"] == "COMPLETE"
    mean, se, yearly = row["pooled_edge"], row["bootstrap_se"], row["year_edges"]
    nz = bool(complete and se > owner.shared.SE_TOL)
    lower = mean-critical*se if nz else None
    progressive = row["domain"] == "PROGRESSIVE_482"
    conditions = dict(complete_required_oof=complete, pooled_positive=bool(complete and mean > 0),
        year2025_positive=bool(yearly["2025"] is not None and yearly["2025"] > 0),
        nonzero_bootstrap_se=nz, simultaneous_lower_positive=bool(lower is not None and lower > 0))
    conditions["both_learning_years_positive" if progressive else "two_of_three_years_positive"] = (
        bool(yearly["2024"] is not None and yearly["2024"] > 0 and yearly["2025"] is not None and yearly["2025"] > 0)
        if progressive else sum(v is not None and v > 0 for v in yearly.values()) >= 2)
    supported = all(conditions.values())
    row.update(simultaneous_lower_95=lower, research_support_conditions=conditions, supported=supported,
        support_status=("PROGRESSIVE_MECHANISM_SUPPORTED" if progressive else "FULL_RISK_MECHANISM_SUPPORTED")
            if supported else "NO_SUPPORT", strict_PIT_promotion_eligible=False, economic_promotion_allowed=False)


def incremental_statistics(precomputed, new_edges, clock, rule, legacy_ids, new_specs, failed=None, *,
        expected_precomputed_sha256, retained_endpoints=None, expected_endpoint_sha256=None,
        risk_inputs=None, synthetic=False, design=None, gate=None, assembly=None, expected_design_sha256=None):
    """Add newly complete frozen risk roles; old bootstrap/means/SE are never rerun.

    retained_endpoints contains only original completed ML endpoints needed to
    prove new matched differences. They are separately pinned and never resampled.
    expected_precomputed_sha256 must come from the caller's verified artifact
    loading boundary, not from a mutated payload supplied to this function.
    """
    if not synthetic:
        ev = owner.validate_design(design)
        owner.validate_final_pipeline_gate(design, gate, assembly, expected_design_sha256)
        need(list(new_specs) == ev["new_specs"] and legacy_ids == ev["legacy"]["numeric_ids"]
             and owner.bootstrap_rule(rule) == owner.bootstrap_rule(ev["bootstrap"]),
             "FROZEN_INCREMENTAL_EVIDENCE_PAYLOAD_CHANGED")
    rule = owner.bootstrap_rule(rule); owner._rule(rule, synthetic)
    specs = owner._specs(new_specs)
    need(specs == owner.role_specs() and len(legacy_ids) == len(set(legacy_ids)) == 147,
         "ALL147_AND_ALL75_FROZEN_SUMMARIES_REQUIRED")
    _, positions, index = owner._clock(clock)
    rows, risk_rows, previous, maxima = _precomputed(precomputed, expected_precomputed_sha256,
        clock, rule, legacy_ids, specs)
    old_maxima = maxima.copy()
    counts, draw_sha, draws = owner._draw_counts(positions, rule)
    need(draw_sha == previous["shared_draw_sha256"] == previous["legacy_shared_draw_sha256"],
         "EXACT_ORIGINAL_SHARED_DRAW_SHA_REQUIRED")
    lookup = {r["candidate_id"]:r for r in rows}
    failed = dict(failed or {}); new_edges = dict(new_edges)
    need(set(new_edges) <= ADDITIONS and set(failed) <= ADDITIONS and not set(new_edges) & set(failed),
         "ONLY_NEW_FROZEN_RISK_ALPHA_ROLES_NO_FAILED_FILL")
    need(all(lookup[cid]["status"] != "COMPLETE" for cid in set(new_edges) | set(failed)),
         "COMPLETE_FROZEN_HYPOTHESIS_MUST_BE_REUSED_NOT_RECOMPUTED")
    endpoints = dict(retained_endpoints or {})
    need(not endpoints or (owner._sha(expected_endpoint_sha256)
         and content_hash(endpoints) == expected_endpoint_sha256), "INDEPENDENT_RETAINED_ENDPOINT_PIN_REQUIRED")
    needed = {side for cid in new_edges if cid in owner.CONTRASTS for side in owner.CONTRASTS[cid]
              if side not in new_edges}
    need(set(endpoints) == needed and all(lookup[cid]["status"] == "COMPLETE" for cid in endpoints),
         "ONLY_EXACT_RETAINED_CONTRAST_ENDPOINTS_REQUIRED")
    for cid, series in {**endpoints, **new_edges}.items():
        wanted = index if lookup[cid]["domain"] == "FULL_732" else index[index.year >= 2024]
        need(isinstance(series, pd.Series) and series.index.equals(wanted)
             and np.isfinite(series.to_numpy(float)).all(), "NO_MISSING_DATE_OR_ZERO_PADDING:"+cid)
        if cid in new_edges and not synthetic:
            need(gate["role_statuses"][cid] == "COMPLETE" and cid in assembly["complete_candidates"],
                 "NEW_RISK_PIPELINE_MUST_BE_FROZEN_COMPLETE")
    for cid, reason in failed.items():
        need(isinstance(reason, str) and bool(reason), "TYPED_FAILURE_REASON_REQUIRED")
        lookup[cid]["failure_reason"] = reason
    active_added = numeric_added = 0
    for cid, series in new_edges.items():
        if cid in owner.CONTRASTS:
            left, right = owner.CONTRASTS[cid]; all_endpoints = {**endpoints, **new_edges}
            need(np.array_equal(series.to_numpy(float),
                 all_endpoints[left].to_numpy(float)-all_endpoints[right].to_numpy(float)),
                 "ORIGINAL_MATCHED_CONTRAST_ENDPOINT_BINDING_REQUIRED")
        boot = owner.masked_bootstrap(series.to_numpy(float), counts[:, index.isin(series.index)])
        se = float(boot.std(ddof=1))
        row = lookup[cid]
        row.update(status="COMPLETE", failure_reason=None, pooled_edge=float(series.mean()), bootstrap_se=se,
            year_edges={str(y):float(series.loc[series.index.year == y].mean()) if (series.index.year == y).any()
                else None for y in (2023,2024,2025)})
        numeric_added += 1
        if se > owner.shared.SE_TOL:
            maxima = np.maximum(maxima, boot/se); active_added += 1
    inputs = dict(risk_inputs or {})
    need(set(inputs) <= set(owner.RISK_CLASSICAL), "ONLY_FIXED20_CLASSICAL_RISK_HYPOTHESES")
    rlookup = {r["candidate_id"]:r for r in risk_rows}
    for spec in owner.RISK_SPECS:
        cid, role = spec["candidate_id"], spec["role"]
        if role not in inputs: continue
        need(rlookup[cid]["status"] != "COMPLETE", "COMPLETE_RISK_BOOTSTRAP_MUST_NOT_RERUN")
        proof = inputs[role]["qualification"]
        need(proof.get("status") == "PASS" and owner._sha(proof.get("source_receipt_sha256"))
             and proof.get("horizon_sessions") == 5 and proof.get("complete_dates") == 732
             and proof.get("labels_mature_pre2026") is True and proof.get("native_shareholder_coordinate") is True
             and lookup[role]["status"] == "COMPLETE", "QUALIFIED_NATIVE_FULL732_H5_OWNER_REQUIRED")
        raw, selected = inputs[role]["raw"], inputs[role]["selected"]
        need(isinstance(raw,pd.Series) and isinstance(selected,pd.Series)
             and raw.index.equals(index) and selected.index.equals(index), "EXACT_FULL732_H5_CLOCK_REQUIRED")
        observed, boot = owner.risk_bootstrap(raw.to_numpy(float), selected.to_numpy(float), spec["metric"], draws)
        se = float(boot.std(ddof=1))
        rlookup[cid].update(status="COMPLETE", failure_reason=None, pooled_risk_improvement=observed, bootstrap_se=se)
        numeric_added += 1
        if se > owner.shared.SE_TOL:
            maxima = np.maximum(maxima, boot/se); active_added += 1
    critical = float(np.quantile(maxima, .95, method="higher"))
    need((maxima >= old_maxima).all() and critical >= previous["critical_max_t"],
         "JOINT_MAXT_THRESHOLD_MUST_NOT_DECREASE")
    for row in rows: _refresh_alpha(row, critical)
    for row in risk_rows:
        se = row["bootstrap_se"]
        lower = row["pooled_risk_improvement"]-critical*se if row["status"] == "COMPLETE" and se > owner.shared.SE_TOL else None
        row.update(simultaneous_lower_95=lower, positive_lower=bool(lower is not None and lower > 0),
                   strict_PIT_promotion_eligible=False)
    legacy = deepcopy(precomputed["legacy_summaries"])
    for row in legacy:
        se = row["bootstrap_se"]
        row["simultaneous_lower_95"] = row["pooled_edge"]-critical*se if se > owner.shared.SE_TOL else None
        row["legacy_reselected"] = False
    efficiency = {}
    for role in owner.RISK_CLASSICAL:
        a = lookup[role]; lb = a["simultaneous_lower_95"]
        down, tail = (rlookup[f"C14_RISK_{metric}_{role[-3:]}"] for metric in ("DOWN","CVAR"))
        old_predicted = previous.get("risk_efficiency", {}).get(role, {}).get("conditions", {}).get("predicted_risk_decreased")
        conditions = dict(complete_full732_alpha=a["status"] == "COMPLETE",
            alpha_noninferiority_lower_ge_zero=bool(lb is not None and lb >= 0),
            downside_simultaneous_lower_positive=down["positive_lower"], cvar_simultaneous_lower_positive=tail["positive_lower"],
            predicted_risk_decreased=inputs.get(role, {}).get("qualification", {}).get("predicted_risk_decreased", old_predicted) is True)
        efficiency[role] = dict(supported=all(conditions.values()), conditions=conditions,
            status="RISK_EFFICIENCY_SUPPORTED_ONLY" if all(conditions.values()) else "NO_RISK_EFFICIENCY_SUPPORT")
    receipt = dict(previous, critical_max_t=critical,
        numeric_complete_series=previous["numeric_complete_series"]+numeric_added,
        family_candidates=previous["family_candidates"]+numeric_added,
        active_nonzero_se_columns=previous["active_nonzero_se_columns"]+active_added,
        failed_or_untestable={r["candidate_id"]:r.get("failure_reason") for r in rows+risk_rows if r["status"] != "COMPLETE"},
        risk_tests=risk_rows, risk_efficiency=efficiency,
        minimum_draw_wise_max_increment=float((maxima-old_maxima).min()),
        incremental_previous_critical_max_t=previous["critical_max_t"],
        incremental_precomputed_sha256=expected_precomputed_sha256, incremental_numeric_added=numeric_added,
        old147_bootstrap_calls=0, old_ml_bootstrap_calls=0, exposure_namespace=321,
        legacy_reselected=False, independent_holdout=False, strict_PIT_promotion_eligible=False)
    return rows, receipt, maxima, legacy
