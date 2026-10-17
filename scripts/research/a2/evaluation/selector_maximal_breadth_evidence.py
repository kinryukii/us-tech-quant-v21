"""C14 pure evidence: mixed fixed supports on the original shared maxT draws.

The runner owns source qualification, label reads and final-pipeline hash checks.
No reader, fit, decoder, risk engine, model choice or output writer lives here.
The frozen selector_evidence owner supplies the unchanged legacy statistics;
this thin adapter adds only fixed-support means and descriptive report formatting.
"""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import selector_evidence as shared
from scripts.research.a2.evaluation import selector_boundary_evidence as prior
from scripts.research.a2.evaluation import selector_constrained_evidence as risk_metrics
from scripts.research.a2.factors import selector_boundary_pairs as pairs_owner

RESEARCH_ID = "V24_C_SELECTOR_MAXIMAL_BREADTH_PRE2026_C14"
MAIN = tuple(f"C14_P{i:02d}" for i in range(1, 21)) + (
    "C14_MT_RIDGE", "C14_MT_EXTRA_TREES", "C14_MT_MLP")
FUSIONS = tuple(f"C14_F{i:02d}" for i in range(1, 13))
HYBRIDS = tuple("C14_RX_" + name for name in (
    "RIDGE_DIAG", "HGB_LW", "XGB_QQQ_RESIDUAL", "CAT_DOWNSIDE_SEMIVARIANCE",
    "MLP_REGIME_COVARIANCE", "QUANTILE_UNCERTAINTY_JACKKNIFE"))
GATES = tuple(f"C14_G{i}" for i in range(1, 5))
CLASSICAL = tuple(f"C14_D{i:02d}" for i in range(1, 13))
DELTA = tuple("C14_DELTA_" + name for name in (
    "RIDGE", "HGB", "XGB", "LGB", "CAT", "EXTRA_TREES", "MLP", "FT"))
CONTRASTS = {**{f"C14_INC_RX_{name}": (r, base)
    for name, r, base in zip(("RIDGE","HGB","XGB","CAT","MLP","QUANTILE"), HYBRIDS,
        ("C14_P01", "C14_P09", "C14_P10", "C14_P12", "C14_P13", "C14_P19"))},
    **{f"C14_INC_G{i}": (f"C14_G{i}", "C14_P01") for i in range(1, 5)}}
ROLES = MAIN + FUSIONS + HYBRIDS + GATES + CLASSICAL + DELTA + tuple(CONTRASTS)
RISK_CLASSICAL = ("C14_D01",) + tuple(f"C14_D{i:02d}" for i in range(3,12))
RISK_SPECS = tuple(dict(candidate_id=f"C14_RISK_{metric}_{role[-3:]}", role=role,
    metric=metric, domain="FULL_732") for role in RISK_CLASSICAL for metric in ("DOWN","CVAR"))
YEAR_COUNTS = {"2023": 250, "2024": 252, "2025": 230}
PROGRESSIVE_COUNTS = {"2024": 252, "2025": 230}
TARGET, BOOT_METHOD = prior.TARGET, prior.BOOT_METHOD
DOMAINS = ("PROGRESSIVE_482", "FULL_732")
COVERAGE_DIMENSIONS = ("learner family", "objective", "capacity", "seed", "representation",
    "multi-horizon", "uncertainty", "fusion", "classical risk", "event-risk", "ML×risk", "risk gate")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= set("0123456789abcdef")


def bootstrap_rule(rule):
    out = dict(rule)
    if "draws" in out:
        _require("repeats" not in out or out["repeats"] == out["draws"], "AMBIGUOUS_BOOTSTRAP_COUNT")
        out["repeats"] = out.pop("draws")
    _require(out.get("block",20) == 20, "FIXED_20_SESSION_BLOCK_REQUIRED")
    return out


def role_specs():
    return [dict(candidate_id=cid,domain="FULL_732" if cid in CLASSICAL else "PROGRESSIVE_482",
        test_kind="MATCHED_CONTRAST" if cid in CONTRASTS else "RAW_ENDPOINT",
        **(dict(left=CONTRASTS[cid][0],right=CONTRASTS[cid][1]) if cid in CONTRASTS else {})) for cid in ROLES]


def _rule(rule, synthetic=False):
    rule = bootstrap_rule(rule)
    _require(rule.get("method") == BOOT_METHOD and rule.get("seed") == 20260928
        and rule.get("confidence") == .95 and isinstance(rule.get("repeats"), int)
        and rule["repeats"] >= 2 and (synthetic or rule["repeats"] == 5000),
        "FROZEN_SHARED_5000_BLOCK20_SEED_REQUIRED")


def _specs(specs):
    entries = list(specs)
    ids = [s["candidate_id"] for s in entries]
    _require(len(ids) == len(set(ids)) and set(ids) <= set(ROLES)
        and all(s.get("domain") in DOMAINS for s in entries), "FROZEN_UNIQUE_ROLE_DOMAIN_REQUIRED")
    for s in entries:
        cid = s["candidate_id"]
        _require((s["domain"] == "FULL_732") == (cid in CLASSICAL), "ROLE_REQUIRED_DATE_DOMAIN_CHANGED")
        if cid in CONTRASTS:
            _require((s.get("left"), s.get("right")) == CONTRASTS[cid]
                and s.get("test_kind") == "MATCHED_CONTRAST", "FROZEN_MATCHED_CONTRAST_REQUIRED")
    return entries


def validate_design(design):
    _require(design.get("research_id") == RESEARCH_ID and design.get("official_freeze") is True
        and design.get("formal_freeze_applied") is True and tuple(design.get("roles", ())) == ROLES
        and design.get("target") == TARGET, "EXACT_C14_FORMAL_FREEZE_REQUIRED")
    _require(design.get("mechanism_research_eligible") is True
        and design.get("strict_PIT_promotion_eligible") is False and design.get("test2026_locked") is True
        and design.get("new2026_estimation_authorized") is False and design.get("read2027_authorized") is False,
        "EXPOSED_MECHANISM_ONLY_FUTURE_LOCK_REQUIRED")
    ev = design["evaluation"]; old = ev["legacy"]
    _require(ev.get("common_mature_date_count") == 732 and ev.get("original_calendar_dates") == 752
        and ev.get("year_counts") == YEAR_COUNTS and ev.get("progressive_mature_date_count") == 482
        and ev.get("progressive_year_counts") == PROGRESSIVE_COUNTS, "FIXED_732_AND_482_CLOCK_REQUIRED")
    ni, ei, failed = old["numeric_ids"], old["exposure_ids"], old["failed_or_untestable"]
    _require(len(ni) == len(set(ni)) == 147 and len(ei) == len(set(ei)) == 226
        and len(failed) == 79 and set(ni).isdisjoint(failed) and set(ni) | set(failed) == set(ei)
        and set(ei).isdisjoint(ROLES) and ev.get("exposure_namespace") == 321, "147_226_HISTORY_AND_321_EXPOSURE_REQUIRED")
    _rule(ev["bootstrap"])
    _require(ev.get("risk_specs") == list(RISK_SPECS), "TWENTY_FIXED_FULL732_RISK_HYPOTHESES_REQUIRED")
    _require(tuple(s["candidate_id"] for s in _specs(ev["new_specs"])) == ROLES,
        "ALL_75_FORMAL_EXPOSURES_REQUIRED")
    blocked = design.get("blocked_roles", {})
    _require(all(blocked.get(cid) == "BLOCKED_BUDGET" for cid in DELTA)
        and blocked.get("C14_D12") == "BLOCKED_BUDGET", "WHOLE_DELTA_AND_500_STABILITY_BUDGET_BLOCK_REQUIRED")
    return ev


def _gate(gate, expected_design_sha256):
    _require(isinstance(gate, dict) and gate.get("status") == "FINAL_PIPELINES_FROZEN"
        and gate.get("research_id") == RESEARCH_ID and _sha(expected_design_sha256)
        and gate.get("design_sha256") == expected_design_sha256
        and gate.get("all_training_terminal") is True and gate.get("capacity_selection_complete") is True
        and tuple(gate.get("roles", ())) == ROLES and set(gate.get("role_statuses", {})) == set(ROLES)
        and all(_sha(gate.get(k)) for k in ("score_assembly_sha256", "fit_ledger_sha256", "pair_key_sha256"))
        and gate.get("forecast2026_rows", 0) == 0, "FINAL_PIPELINE_FREEZE_REQUIRED_BEFORE_OUTCOMES")
    _require(all(v not in ("PENDING", "RESERVED", "RUNNING") for v in gate["role_statuses"].values()),
        "UNRESOLVED_PIPELINE_CANNOT_CONSUME_OUTCOMES")
    return gate


def validate_final_pipeline_gate(design, gate, assembly, expected_design_sha256):
    validate_design(design); _gate(gate, expected_design_sha256)
    _require(assembly.get("status") == "SCORE_ASSEMBLY_COMPLETE"
        and assembly.get("design_freeze_sha256") == expected_design_sha256
        and assembly.get("pair_key_sha256") == gate["pair_key_sha256"]
        and assembly.get("forecast2026_rows", 0) == 0
        and set(assembly.get("complete_candidates", ())).isdisjoint(assembly.get("failed_or_untestable", {})),
        "EXACT_TERMINAL_SCORE_ASSEMBLY_REQUIRED")
    return True


def _clock(clock):
    _require(isinstance(clock, pd.DataFrame) and len(clock) == 752
        and {"signal_date", "included"} <= set(clock)
        and pd.api.types.is_bool_dtype(clock.included) and not clock.included.isna().any(),
        "ORIGINAL_752_CALENDAR_REQUIRED")
    cal = pd.DatetimeIndex(clock.signal_date); positions = np.flatnonzero(clock.included.to_numpy(bool))
    index = cal[positions]
    _require(cal.tz is None and not cal.hasnans and cal.is_unique and cal.is_monotonic_increasing
        and (cal < pd.Timestamp("2026-01-01")).all() and len(index) == 732
        and {str(y): int((index.year == y).sum()) for y in (2023, 2024, 2025)} == YEAR_COUNTS,
        "EXACT_FINITE_PRE2026_732_CLOCK_REQUIRED")
    return cal, positions, index


def _draw_counts(positions, rule):
    # Numerically identical draw construction to frozen shared.shared_max_t.
    n = len(positions); length = 20
    starts = np.array([i for i in range(n-length+1)
        if np.all(np.diff(positions[i:i+length]) == 1)], dtype=int)
    _require(len(starts) > 0, "INSUFFICIENT_CONTIGUOUS_COMMON_SESSIONS")
    offsets = np.random.default_rng(rule["seed"]).choice(starts,
        size=(rule["repeats"], (n+length-1)//length))
    draws = (offsets[:, :, None] + np.arange(length)).reshape(rule["repeats"], -1)[:, :n]
    counts = np.zeros((rule["repeats"], n), dtype=float)
    for i, row in enumerate(draws):
        counts[i] = np.bincount(row, minlength=n)
    return counts, hashlib.sha256(draws.astype("<i8").tobytes()).hexdigest(), draws


def masked_bootstrap(values, support_counts):
    """Support-only values, not zero-padded edges; every draw uses its own mass."""
    x, counts = np.asarray(values, float), np.asarray(support_counts, float)
    _require(x.ndim == 1 and len(x) > 0 and counts.ndim == 2 and counts.shape[1] == len(x)
        and np.isfinite(x).all() and np.isfinite(counts).all() and (counts >= 0).all(),
        "FINITE_FIXED_SUPPORT_VALUES_AND_COUNTS_REQUIRED")
    mass = counts.sum(axis=1)
    _require((mass > 0).all(), "ZERO_FIXED_SUPPORT_BOOTSTRAP_MASS")
    boot = counts @ (x - x.mean()) / mass
    boot -= boot.mean()
    return boot


def risk_bootstrap(raw, selected, metric, draws):
    """Recompute the original nonadditive risk functional on every shared draw."""
    raw, selected = np.asarray(raw,float), np.asarray(selected,float)
    _require(raw.shape == selected.shape == (732,) and np.isfinite(raw).all()
        and np.isfinite(selected).all() and metric in ("DOWN","CVAR"), "FULL732_FINITE_H5_RISK_REQUIRED")
    def functional(x):
        if metric == "DOWN":
            return np.sqrt(np.square(np.minimum(x,0)).mean(axis=-1))
        return risk_metrics._empirical_cvar_owner()(-x,alpha=.95)
    observed = float(functional(raw)-functional(selected))
    boot = functional(raw[draws])-functional(selected[draws])-observed
    boot -= boot.mean()
    return observed, boot


def statistics(legacy_edges, new_edges, clock, rule, legacy_ids, new_specs, failed=None, *,
        synthetic=False, design=None, gate=None, assembly=None, expected_design_sha256=None, risk_inputs=None):
    """Return summaries, joint receipt, maxima; missing roles stay exposure-only."""
    if not synthetic:
        ev = validate_design(design)
        validate_final_pipeline_gate(design, gate, assembly, expected_design_sha256)
        _require(list(new_specs) == ev["new_specs"] and legacy_ids == ev["legacy"]["numeric_ids"]
            and bootstrap_rule(rule) == bootstrap_rule(ev["bootstrap"]), "FROZEN_EVIDENCE_PAYLOAD_CHANGED")
    rule = bootstrap_rule(rule); _rule(rule, synthetic); specs = _specs(new_specs); ids = list(legacy_ids); failed = dict(failed or {})
    _, positions, index = _clock(clock)
    _require(len(ids) == len(set(ids)) == 147 and list(legacy_edges) == ids
        and legacy_edges.index.equals(index) and np.isfinite(legacy_edges.to_numpy(float)).all()
        and set(new_edges) <= {s["candidate_id"] for s in specs} and set(failed) <= {s["candidate_id"] for s in specs}
        and not set(new_edges) & set(failed) and set(ids).isdisjoint(s["candidate_id"] for s in specs),
        "EXACT_LEGACY_147_SERIES_AND_FIXED_NEW_NAMES_REQUIRED")
    for s in specs:
        cid = s["candidate_id"]
        if cid in new_edges:
            series = new_edges[cid]; wanted = index if s["domain"] == "FULL_732" else index[index.year >= 2024]
            _require(isinstance(series, pd.Series) and series.index.equals(wanted)
                and np.isfinite(series.to_numpy(float)).all(), "NO_PARTIAL_WINDOW_OR_ZERO_PADDING:" + cid)
            if cid in DELTA or cid == "C14_D12":
                raise ValueError("BLOCKED_BUDGET_CANNOT_ENTER_NUMERIC:" + cid)
        else:
            failed.setdefault(cid, "BLOCKED_BUDGET" if cid in DELTA or cid=="C14_D12"
                else "BLOCKED_MISSING_COMPLETE_REQUIRED_DOMAIN")
    # When both endpoints are available the contrast must be their exact difference.
    for s in specs:
        cid = s["candidate_id"]
        if cid in new_edges and cid in CONTRASTS:
            left, right = CONTRASTS[cid]
            _require(left in new_edges and right in new_edges
                and new_edges[cid].index.equals(new_edges[left].index)
                and np.array_equal(new_edges[cid].to_numpy(float),
                    new_edges[left].to_numpy(float) - new_edges[right].to_numpy(float)),
                "MATCHED_CONTRAST_ENDPOINT_BINDING_REQUIRED")
    _, _, previous, old_max = shared.shared_max_t(legacy_edges.to_numpy(float), positions,
        [True]*147, {**rule, "family_candidates": 147})
    counts, draw_sha, draws = _draw_counts(positions, rule)
    _require(previous.get("status") == "COMPLETE" and draw_sha == previous["shared_draw_sha256"],
        "FROZEN_LEGACY_SHARED_DRAW_EQUIVALENCE_REQUIRED")
    maxima = old_max.copy(); estimates = {}
    for s in specs:
        cid = s["candidate_id"]
        if cid not in new_edges:
            continue
        series = new_edges[cid]; take = index.isin(series.index)
        boot = masked_bootstrap(series.to_numpy(float), counts[:, take])
        se = float(boot.std(ddof=1))
        estimates[cid] = (float(series.mean()), se)
        if np.isfinite(se) and se > shared.SE_TOL:
            maxima = np.maximum(maxima, boot/se)
    risk_inputs = dict(risk_inputs or {}); risk_estimates = {}; risk_failed = {}
    _require(set(risk_inputs) <= set(RISK_CLASSICAL), "ONLY_FIXED_CLASSICAL_RISK_EFFICIENCY_ROLES")
    for spec in RISK_SPECS:
        cid, role = spec["candidate_id"], spec["role"]
        if role not in risk_inputs:
            risk_failed[cid] = "BLOCKED_QUALIFIED_NATIVE_H5_FULL732_SOURCE"
            continue
        proof = risk_inputs[role]["qualification"]
        _require(proof.get("status") == "PASS" and _sha(proof.get("source_receipt_sha256"))
            and proof.get("horizon_sessions") == 5 and proof.get("complete_dates") == 732
            and proof.get("labels_mature_pre2026") is True and proof.get("native_shareholder_coordinate") is True,
            "QUALIFIED_NATIVE_FULL732_H5_OWNER_REQUIRED")
        _require(role in new_edges, "RISK_POLICY_FULL732_ALPHA_ENDPOINT_REQUIRED")
        raw, selected = risk_inputs[role]["raw"], risk_inputs[role]["selected"]
        _require(isinstance(raw,pd.Series) and isinstance(selected,pd.Series)
            and raw.index.equals(index) and selected.index.equals(index), "EXACT_FULL732_H5_CLOCK_REQUIRED")
        observed, boot = risk_bootstrap(raw.to_numpy(float),selected.to_numpy(float),spec["metric"],draws)
        se = float(boot.std(ddof=1)); risk_estimates[cid]=(observed,se)
        if np.isfinite(se) and se > shared.SE_TOL:
            maxima = np.maximum(maxima,boot/se)
    critical = float(np.quantile(maxima, rule["confidence"], method="higher"))
    _require((maxima >= old_max).all() and critical >= previous["critical_max_t"],
        "JOINT_MAXT_CANNOT_LOWER_LEGACY_THRESHOLD")
    summaries = []
    for s in specs:
        cid = s["candidate_id"]; complete = cid in estimates
        mean, se = estimates.get(cid, (None, None)); nz = bool(complete and se > shared.SE_TOL)
        lower = mean - critical*se if nz else None
        yearly = {str(y): (float(new_edges[cid].loc[new_edges[cid].index.year == y].mean())
            if complete and (new_edges[cid].index.year == y).any() else None) for y in (2023, 2024, 2025)}
        progressive = s["domain"] == "PROGRESSIVE_482"
        conditions = dict(complete_required_oof=complete, pooled_positive=bool(complete and mean > 0),
            year2025_positive=bool(yearly["2025"] is not None and yearly["2025"] > 0),
            nonzero_bootstrap_se=nz, simultaneous_lower_positive=bool(lower is not None and lower > 0))
        conditions["both_learning_years_positive" if progressive else "two_of_three_years_positive"] = (
            bool(yearly["2024"] is not None and yearly["2024"] > 0 and yearly["2025"] is not None and yearly["2025"] > 0)
            if progressive else sum(v is not None and v > 0 for v in yearly.values()) >= 2)
        supported = all(conditions.values())
        summaries.append(dict(**s, status="COMPLETE" if complete else "FAILED_UNTESTABLE",
            failure_reason=failed.get(cid), pooled_edge=mean, year_edges=yearly,
            bootstrap_se=se, simultaneous_lower_95=lower, required_dates=482 if progressive else 732,
            research_support_conditions=conditions, supported=supported,
            support_status=("PROGRESSIVE_MECHANISM_SUPPORTED" if progressive else "FULL_RISK_MECHANISM_SUPPORTED")
                if supported else "NO_SUPPORT", strict_PIT_promotion_eligible=False, economic_promotion_allowed=False,
            year2023_is_exact_raw_fallback=progressive, year2023_counted_as_learning_success=False))
    risk_rows = []
    for spec in RISK_SPECS:
        cid=spec["candidate_id"]; complete=cid in risk_estimates; mean,se=risk_estimates.get(cid,(None,None))
        lower=mean-critical*se if complete and se>shared.SE_TOL else None
        risk_rows.append(dict(**spec,status="COMPLETE" if complete else "FAILED_UNTESTABLE",
            failure_reason=risk_failed.get(cid),pooled_risk_improvement=mean,bootstrap_se=se,
            simultaneous_lower_95=lower,positive_lower=bool(lower is not None and lower>0),
            statistic_kind="NONADDITIVE_RISK_FUNCTIONAL_RAW_MINUS_SELECTED",
            unit="return units; reported bp multiply10000",strict_PIT_promotion_eligible=False))
    alpha_lookup={row["candidate_id"]:row for row in summaries};risk_lookup={row["candidate_id"]:row for row in risk_rows}
    efficiency={}
    for role in RISK_CLASSICAL:
        a=alpha_lookup.get(role,{}); lb=a.get("simultaneous_lower_95")
        down=risk_lookup[f"C14_RISK_DOWN_{role[-3:]}"];tail=risk_lookup[f"C14_RISK_CVAR_{role[-3:]}"]
        conditions=dict(complete_full732_alpha=a.get("status")=="COMPLETE",
            alpha_noninferiority_lower_ge_zero=bool(lb is not None and lb>=0),
            downside_simultaneous_lower_positive=down["positive_lower"],
            cvar_simultaneous_lower_positive=tail["positive_lower"],
            predicted_risk_decreased=risk_inputs.get(role,{}).get("qualification",{}).get("predicted_risk_decreased") is True)
        efficiency[role]=dict(supported=all(conditions.values()),conditions=conditions,
            status="RISK_EFFICIENCY_SUPPORTED_ONLY" if all(conditions.values()) else "NO_RISK_EFFICIENCY_SUPPORT")
    receipt = dict(previous, critical_max_t=critical, legacy_critical_max_t=previous["critical_max_t"],
        shared_draw_sha256=draw_sha, legacy_shared_draw_sha256=previous["shared_draw_sha256"],
        minimum_draw_wise_max_increment=float((maxima-old_max).min()),
        numeric_complete_series=147+len(estimates)+len(risk_estimates), legacy_numeric_complete_series=147,
        exposure_namespace=226+len(specs)+20, legacy_exposure_namespace=226, new_exposure_tests=len(specs)+20,
        family_candidates=147+len(estimates)+len(risk_estimates),
        active_nonzero_se_columns=previous["active_nonzero_se_columns"]+sum(se>shared.SE_TOL for _,se in estimates.values())
            +sum(se>shared.SE_TOL for _,se in risk_estimates.values()), failed_or_untestable={**failed,**risk_failed},
        risk_tests=risk_rows,risk_efficiency=efficiency,hybrid_gate_risk_efficiency_inferential=False,
        new_supports={s["candidate_id"]:s["domain"] for s in specs},
        support_denominator="same original732 shared draws; each fixed support uses its own resampled mass",
        failed_series="exposure metadata only; never numeric zero placeholders",
        legacy_reselected=False, independent_holdout=False, strict_PIT_promotion_eligible=False,
        limitation="Approximate exposed-history mechanism evidence; masked-domain extension is not finite-sample coverage")
    return summaries, receipt, maxima


def pair_diagnostics(candidate_id, pairs, prediction, y_edges, matched_pairs, oracle_utility, *,
        kind="edge", decision="U0", native_probability=None, final_gate, expected_design_sha256):
    """Post-gate diagnostics; the caller supplies one charged, cached daily oracle."""
    _gate(final_gate, expected_design_sha256)
    _require(candidate_id in ROLES and kind in ("edge", "probability", "quantile", "gaussian")
        and decision in ("U0", "U1", "U2", "U3"), "FROZEN_PAIR_DIAGNOSTIC_SEMANTICS_REQUIRED")
    keysha = pairs_owner.pair_key_sha256(pairs); p = pairs.reset_index(drop=True)
    values, truth = np.asarray(prediction, float), np.asarray(y_edges, float)
    columns = 3 if kind == "quantile" else 2 if kind == "gaussian" else None
    _require(values.shape == ((len(p), columns) if columns else (len(p),))
        and np.isfinite(values).all() and truth.shape == (len(p),), "COMPLETE_PAIR_PREDICTION_LABEL_SHAPE_REQUIRED")
    point = values[:, 1] if kind == "quantile" else values[:, 0] if kind == "gaussian" else values
    probability = values if kind == "probability" else None
    probability_coordinate = "NATIVE_SIGN_PROBABILITY" if kind == "probability" else None
    _require(native_probability is None or kind == "gaussian", "NATIVE_MIXTURE_PROBABILITY_ONLY_FOR_GAUSSIAN")
    if kind == "probability":
        _require(((values >= 0) & (values <= 1)).all() and decision == "U1", "PROBABILITY_U1_REQUIRED")
    if kind == "gaussian":
        _require((values[:, 1] > 0).all(), "POSITIVE_GAUSSIAN_SIGMA_REQUIRED")
        from scipy.special import ndtr
        if native_probability is None:
            probability = ndtr(point / values[:, 1])
            probability_coordinate = "GAUSSIAN_MOMENT_APPROXIMATION"
        else:
            probability = np.asarray(native_probability,float)
            _require(probability.shape == (len(p),) and np.isfinite(probability).all()
                and ((probability>=0)&(probability<=1)).all(), "FINITE_NATIVE_MIXTURE_PROBABILITY_REQUIRED")
            probability_coordinate = "NATIVE_THREE_NORMAL_MIXTURE_CDF"
    _require(decision != "U1" or probability is not None, "U1_REQUIRES_DECLARED_PROBABILITY")
    _require(decision != "U2" or kind == "quantile", "U2_REQUIRES_Q10")
    _require(decision != "U3" or kind == "gaussian", "U3_REQUIRES_MU_SIGMA")
    eligible = probability > .5 if decision == "U1" else (
        (values[:, 0] > 0) & (point > 0) if decision == "U2" else (
        point-values[:, 1] > 0 if decision == "U3" else point > 0))
    match = pd.DataFrame(matched_pairs)
    if len(match):
        _require(set(pairs_owner.PAIR_KEYS) <= set(match) and not match.duplicated(list(pairs_owner.PAIR_KEYS)).any()
            and match.merge(p[list(pairs_owner.PAIR_KEYS)], on=list(pairs_owner.PAIR_KEYS), how="left",
                indicator=True, validate="one_to_one")._merge.eq("both").all(), "MATCHED_PAIRS_MUST_BE_FROZEN_GEOMETRY")
    _require(isinstance(oracle_utility, pd.Series) and oracle_utility.index.is_unique,
        "CHARGED_SHARED_DAILY_ORACLE_SERIES_REQUIRED")
    rows, bins, ranks = [], [], []
    for date, ix in p.groupby("signal_date", sort=True).indices.items():
        date = pd.Timestamp(date); g = p.iloc[ix]; y = truth[ix]; s = point[ix]
        _require(date < pd.Timestamp("2026-01-01") and date.year in (2024, 2025),
            "PROGRESSIVE_DIAGNOSTICS_PRE2026_ONLY")
        m = match.loc[pd.to_datetime(match.signal_date).eq(date)] if len(match) else match
        _require(len(m) <= 10 and (not len(m) or m.challenger_uid.is_unique and m.incumbent_uid.is_unique),
            "ONE_TO_ONE_MATCH_REQUIRED")
        chosen = set(zip(m.challenger_uid, m.incumbent_uid)) if len(m) else set()
        selected = np.array([(e,i) in chosen for e,i in zip(g.challenger_uid,g.incumbent_uid)])
        _require((~selected | eligible[ix]).all(), "MATCH_REQUIRES_FROZEN_ELIGIBILITY")
        finite = bool(np.isfinite(y).all()); utility = float(y[selected].sum()/20) if finite else None
        oracle = oracle_utility.get(date)
        regret = float(oracle-utility) if finite and oracle is not None and np.isfinite(oracle) else None
        _require(regret is None or regret >= -1e-12, "ORACLE_UTILITY_BELOW_LEARNED_MATCH")
        rows.append(dict(candidate_id=candidate_id,signal_date=date,year=int(date.year),descriptive_only=True,
            pair_key_sha256=keysha,probability_coordinate=probability_coordinate,pair_count=len(g),unavailable_label_pairs=int((~np.isfinite(y)).sum()),
            pair_regret=float((np.maximum(y,0)-y*eligible[ix]).mean()) if finite else None,
            pair_regret_definition=prior.PAIR_REGRET_DEFINITION,
            matching_utility=utility,oracle_matching_utility=float(oracle) if oracle is not None and np.isfinite(oracle) else None,
            matching_regret=regret,matching_regret_denominator=20,replacement_count=int(selected.sum()),
            wrong_replacement_count=int((selected & (y <= 0)).sum()) if finite else None,
            correct_replacement_count=int((selected & (y > 0)).sum()) if finite else None,
            sign_accuracy=float(((probability[ix]>.5 if probability is not None else s>0)==(y>0)).mean()) if finite else None,
            brier=float(((probability[ix]-(y>0))**2).mean()) if finite and probability is not None else None,
            mean_absolute_edge_error=float(np.abs(s-y).mean()) if finite and kind!="probability" else None,
            q10_coverage=float((y<=values[ix,0]).mean()) if finite and kind=="quantile" else None,
            q50_coverage=float((y<=values[ix,1]).mean()) if finite and kind=="quantile" else None,
            q90_coverage=float((y<=values[ix,2]).mean()) if finite and kind=="quantile" else None,
            quantile_crossing_fraction=float(((values[ix,0]>values[ix,1])|(values[ix,1]>values[ix,2])).mean()) if kind=="quantile" else None))
        for side, col in (("challenger","challenger_raw_rank"),("incumbent","incumbent_raw_rank")):
            ranks.extend(dict(candidate_id=candidate_id,signal_date=date,side=side,raw_rank=int(rank))
                for rank in g.loc[selected,col])
        if finite:
            score = probability[ix] if probability is not None else s
            bounds = prior.PROBABILITY_BINS if probability is not None else prior.EDGE_BINS
            assigned=np.clip(np.searchsorted(bounds,score,side="right")-1,0,len(bounds)-2)
            for binid in np.unique(assigned):
                take=assigned==binid
                bins.append(dict(candidate_id=candidate_id,signal_date=date,bin_id=int(binid),
                    pair_count=int(take.sum()),date_pair_mass=float(take.sum()/len(g)),
                    prediction_mean=float(score[take].mean()),realized_positive_rate=float((y[take]>0).mean()),
                    realized_pair_edge_mean=float(y[take].mean()),probability_coordinate=probability_coordinate,descriptive_only=True))
    return pd.DataFrame(rows), pd.DataFrame(bins), pd.DataFrame(ranks)


def membership_diagnostics(candidate_id, reference, panel, clock, *, final_gate, expected_design_sha256):
    _gate(final_gate, expected_design_sha256); _require(candidate_id in ROLES, "FROZEN_ROLE_REQUIRED")
    calendar, _, index = _clock(clock); keys = shared.KEY
    r = reference.sort_values(keys, kind="stable").reset_index(drop=True)
    p = panel.sort_values(keys, kind="stable").reset_index(drop=True)
    _require(not r.duplicated(keys).any() and not p.duplicated(keys).any() and r[keys].equals(p[keys])
        and {"raw_rank","target","label_end_date"} <= set(r) and "rank" in p,
        "FULL_U_PRESERVED_REFERENCE_AND_PANEL_REQUIRED")
    _require(pd.DatetimeIndex(sorted(r.signal_date.unique())).equals(calendar)
        and r.security_uid.map(lambda v:isinstance(v,str) and bool(v.strip())).all(),
        "FULL752_UID_POLICY_REQUIRED")
    for col in ("ticker","U_t_fingerprint"):
        if col in r and col in p:
            _require(r[col].equals(p[col]), "UID_TICKER_UNIVERSE_IDENTITY_CHANGED")
    rows=[];previous=None
    for date, ix in r.groupby("signal_date",sort=True).indices.items():
        date=pd.Timestamp(date);g=r.iloc[ix];rr=g.raw_rank.to_numpy();rk=p.iloc[ix]["rank"].to_numpy()
        _require(date<pd.Timestamp("2026-01-01") and len(g)>=40
            and np.array_equal(np.sort(rr),np.arange(1,len(g)+1))
            and np.array_equal(np.sort(rk),np.arange(1,len(g)+1)), "PRE2026_FULL_U_ORDINAL_RANKS_REQUIRED")
        raw=rr<=20;chosen=rk<=20
        _require(chosen.sum()==20 and chosen[rr<=10].all() and (rr[chosen]<=40).all(),
            "RAW_CORE10_BOUNDARY_TOP40_FINAL20_REQUIRED")
        if candidate_id not in CLASSICAL and date.year==2023:
            _require(np.array_equal(chosen,raw),"YEAR2023_EXACT_RAW_FALLBACK_REQUIRED")
        mature,_=shared.maturity(g.reset_index(drop=True),raw|chosen)
        legal=date in index and bool(mature[raw|chosen].all())
        selected=set(g.loc[chosen,"security_uid"]);count=int((chosen & ~raw).sum())
        rows.append(dict(candidate_id=candidate_id,signal_date=date,year=int(date.year),
            common_mature_date=legal,descriptive_only=True,raw_overlap=int((raw & chosen).sum()),
            replacement_count=count,replacement_edge=shared.replacement_edge(g.target.to_numpy(float),raw,chosen) if legal else None,
            membership_turnover=None if previous is None else len(previous^selected)/40,
            challenger_raw_rank_mean=float(rr[chosen & ~raw].mean()) if count else None,
            incumbent_raw_rank_mean=float(rr[raw & ~chosen].mean()) if count else None))
        previous=selected
    return pd.DataFrame(rows)


def training_coverage_audit(plan, slots, role_statuses):
    """Plan values bind dimensions; actual coverage comes from explicit slot tags."""
    _require(set(plan)==set(COVERAGE_DIMENSIONS),"TWELVE_FROZEN_COVERAGE_DIMENSIONS_REQUIRED")
    slots=list(slots.values()) if isinstance(slots,dict) else list(slots); rows=[]
    for dimension in COVERAGE_DIMENSIONS:
        spec=plan[dimension]; values=list(spec["planned"]);field=spec.get("slot_field")
        _require(len(values)==len(set(values)),"UNIQUE_FROZEN_COVERAGE_VALUES_REQUIRED")
        entered={s.get(field) for s in slots if field and s.get("backend_entered") is True}
        actual={s.get(field) for s in slots if field and s.get("backend_entered") is True
            and s.get("status") in ("COMPLETE","SUCCEEDED","TRAINED")}
        blocked={}
        for value, members in spec.get("role_members",{}).items():
            states=[role_statuses.get(cid,"UNKNOWN") for cid in members]
            if states and all(state.startswith("BLOCKED") or state in ("FAILED","UNTESTABLE","PARTIAL_INPUT_BLOCKED") for state in states):
                blocked[value]=sorted(set(states))
            if states and all(state=="COMPLETE" for state in states) and not field:
                actual.add(value)
        rows.append(dict(dimension=dimension,planned=len(values),actual=len(set(values)&actual),
            attempted=len(set(values)&entered),blocked=blocked,uncovered=[v for v in values if v not in actual],
            coverage=float(len(set(values)&actual)/len(values)) if values else None,
            measurement="explicit backend-entry/terminal-success tags or complete fixed-transform role receipts; no fit quota"))
    return rows


def _table(rows, columns):
    head="| "+" | ".join(label for _,label in columns)+" |\n"
    body="| "+" | ".join("---" for _ in columns)+" |\n"
    for row in rows:
        cells=[]
        for key,_ in columns:
            value=row.get(key)
            text="—" if value is None else str(value)
            cells.append(text.replace("|","\\|").replace("\n"," "))
        body+="| "+" | ".join(cells)+" |\n"
    return head+body


def render_report(payload):
    """Return detailed Chinese Markdown; verified runner supplies all bindings."""
    tests=payload.get("tests",[]);budget=payload.get("budget",{})
    formatted=[]
    for row in tests:
        yearly=row.get("year_edges",{}); out=dict(row)
        for key in ("pooled_edge","bootstrap_se","simultaneous_lower_95"):
            out[key+"_bp"]=None if row.get(key) is None else round(row[key]*10000,6)
        for year in (2023,2024,2025):
            out[str(year)]=None if yearly.get(str(year)) is None else round(yearly[str(year)]*10000,6)
        formatted.append(out)
    coverage=payload.get("training_coverage_audit",[])
    return "\n\n".join([
        "# C14 Selector Maximal Breadth — 最终报告",
        "状态：**"+payload.get("status","UNVERIFIED")+"**。本轮属于已暴露pre-2026机制研究，strict_PIT_promotion_eligible=false；2026锁定、2027不读取。",
        "目标：以Raw A2为alpha anchor，固定Raw1–10，只在Raw11–40内研究边界替换、集合/排序、分布、不确定性、真正OOF融合以及风险交互。最终Top20等权；不涉及账户、Gross、Cash或RL。",
        "训练与评价：2023为exact Raw fallback；2024只用合法2023历史；2025只用合法2023–24历史。训练、scaler、校准、元学习和容量选择都早于各自cutoff及标签成熟边界。学习支持域为2024/25共482个原共同成熟日期，2023零edge不算第三个学习成功年份；完整risk支持另需732日。",
        "累计检验：旧147条numeric与226项exposure保留；75个新alpha/contrast曝光及20个固定risk hypotheses使累计namespace为321。"+str(payload.get("bootstrap",{}))+"。使用原732日期上的同一20-session block draws，新列固定mask并各自计算有效抽样分母，不零补；failed仅保留曝光。2023–25均已暴露，当前结果不能称独立holdout或生产升级。",
        "所有edge及lower bound单位为bp；它们是MEAN_ER_3D_5D_10D_20D selection edge，不能冒充净账户收益。\n\n"+
            _table(formatted,[("candidate_id","角色"),("status","状态"),("2023","2023"),("2024","2024"),("2025","2025"),
                ("pooled_edge_bp","pooled"),("simultaneous_lower_95_bp","同时lower95"),("supported","支持"),("failure_reason","未完成原因")]),
        "## 预注册风险效率检验\n\n"+_table(payload.get("risk_tests",[]),[("candidate_id","风险假设"),("status","状态"),
            ("metric","函数"),("pooled_risk_improvement","改善(原return单位)"),("simultaneous_lower_95","同时lower95(原return单位)"),
            ("failure_reason","缺口")])+"\n\n仅D01、D03–D11允许正式风险效率支持：完整732日，alpha同时lower>=0，DOWN和CVaR两个改善同时lower>0且预测风险下降。Hybrid/gate风险效率仅描述。CVaR每个shared draw重新计算原fractional-tail函数，alpha=.95，未伪造daily CVaR proxy。",
        "## TRAINING_COVERAGE_AUDIT\n\n"+_table(coverage,[("dimension","维度"),("planned","计划"),("actual","已完成"),
            ("attempted","已尝试"),("blocked","Blocked"),("coverage","Coverage"),("uncovered","未覆盖")])+
            "\n\n计数来自实际backend入口及成功receipt，不将库存在、实现存在、预留slot或单次大模型fit解释成完整科学覆盖。",
        "## 预算与执行事实\n\n"+str(budget)+"\n\n失败reservation不退款；静态融合/整组risk veto和exact reuse必须有对应receipt。ML estimator/scaler/fusion上限1800，C14 attributable risk learned units上限3000，ordinary solver上限30000。D12固定500次、block20、seed20260928独立substudy，没有预算即BLOCKED_BUDGET，不降低draws。",
        "## 机制诊断\n\n"+str(payload.get("diagnostic_summary","未提供已验证诊断摘要。"))+
            "\n\npair regret与matching regret分开；matching oracle由一次共享、已计预算的decoder生成。sign/Brier/quantile coverage只描述、不再校准或选模型。Raw overlap、替换数量与来源rank说明激进/保守行为。风险和veto归因仅在合法source、完整required domain及固定matched contrast通过时成立。",
        "## 故障、缺口与未完成项\n\n"+str(payload.get("faults",[]))+"\n\n"+str(payload.get("remaining",[]))+
            "\n\nDELTA8整臂因预算未执行，不声称训练充分覆盖该维度。B R5 numeric bank未发布时risk/hybrid/gate仅为readiness，不伪造covariance/Raw fallback。输入、依赖和预算BLOCK须与科学负结果分开。",
        "## 存储与审计\n\n"+str(payload.get("storage",{}))+"\n\n"+str(payload.get("preservation",{}))+
            "\n\n源码保存在D项目；模型、预测、ledger在唯一backtest run；报告在results；测试缓存在cache。旧C12/C13及所有冻结失败记录保留。",
        "下一步：仅推进本轮已冻结、仍具合法输入和剩余预算的队列；缺B bank保持明确等待/阻塞，不无意义轮询、不自动开C15、不把曝光窗口重新称独立验证。"])
