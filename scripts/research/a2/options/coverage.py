"""R1 fixed market keys and exploratory missing-label accounting.

The original strict ledger estimator remains in input_adapter. This module
joins one qualified independent price adapter and reuses the R1 arithmetic and
date inference. Neither future holdings nor future ranks enter expected keys.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.common.storage_paths import resolve
from .contracts import TEMPLATE, calendar, require
from .expression import date_interval, path_metrics
from . import input_adapter as original

RUN_ID = "20260913T032957JST"
CONFIG_SHA = "df282995330116ccb41c8de173a39f8fc8c7f7501a64673208ec9559a1f1fe74"
PRICE_KEYS = ["underlying_uid", "ticker", "session", "field"]
VERIFIED = {
    "identity_status": {"VERIFIED", "VERIFIED_INHERITED_STATIC_TRANSPORT", "VERIFIED_DATED_HISTORICAL_MAPPING"},
    "action_status": {"VERIFIED", "UNCHANGED", "VERIFIED_NO_EVENT", "VERIFIED_INHERITED_FROZEN_FORWARD_REHAB"},
    "lifecycle_status": {"VERIFIED", "RESOLVED", "VERIFIED_NO_EVENT", "RESOLVED_CONTINUOUS_BOUND_TRANSPORT_MARK"},
}
OLD_LABEL_SHA = "aa89b22a060b13dde441da69537e91a66aeeaeff34fb47e117b8977b59479df0"
OPTION_ARTIFACTS = ("fixed_probe_plan.json", "option_qualification.csv", "actual_pairs.csv", "qualification_summary.json")


def expected_price_keys(panel: pd.DataFrame) -> pd.DataFrame:
    """Union of exact entry..entry+20 sessions; never issue post-cutoff keys."""
    require(not panel.decision_id.duplicated().any(), "DUPLICATE_OPPORTUNITY")
    cal = calendar()
    signals = pd.to_datetime(panel.signal_date)
    require(signals.lt("2026-01-01").all(), "NON_PRE2026_SIGNAL")
    positions = cal.sessions.get_indexer(signals)
    require((positions >= 0).all(), "NON_SESSION_SIGNAL")
    dates = cal.sessions.to_numpy()[positions[:, None] + 1 + np.arange(21)]
    keys = pd.DataFrame({"underlying_uid": np.repeat(panel.underlying_uid.to_numpy(), 21),
                         "ticker": np.repeat(panel.ticker.to_numpy(), 21),
                         "session": dates.ravel(), "field": "open"})
    return keys[keys.session.lt("2026-01-01")].drop_duplicates(PRICE_KEYS).sort_values(PRICE_KEYS).reset_index(drop=True)


def fixed_weights(labels: pd.DataFrame) -> pd.Series:
    """Full mature opportunity population, including entirely unobserved dates."""
    mature = ~labels.cutoff_censored.astype(bool)
    out = pd.Series(0., index=labels.index)
    if mature.any():
        group = labels.loc[mature]
        n_dates = group.signal_date.nunique()
        out.loc[mature] = 1. / (n_dates * group.groupby("signal_date").decision_id.transform("size"))
    return out


def market_labels(panel: pd.DataFrame, marks: pd.DataFrame, *, source_role: str = "PRIMARY") -> pd.DataFrame:
    """Separate endpoint, full path, and lifecycle validity on frozen sessions."""
    require(set(PRICE_KEYS + ["price", "valid", "identity_status", "action_status", "lifecycle_status", "source", "price_kind"]) <= set(marks), "MARK_SCHEMA")
    marks = marks.copy()
    marks["session"] = pd.to_datetime(marks.session)
    require(marks.session.notna().all() and marks.session.lt("2026-01-01").all(), "NON_PRE2026_PRICE")
    require(marks.field.eq("open").all(), "WRONG_PRICE_FIELD")
    require(not marks.duplicated(PRICE_KEYS).any(), "DUPLICATE_INDEPENDENT_PRICE")
    sources = marks.loc[marks.valid.eq(True), "source"].dropna().unique()
    require(len(sources) <= 1, "SOURCE_SPLICE_REJECTED")
    prices = marks.set_index(PRICE_KEYS)
    cal = calendar()
    starts = cal.sessions.get_indexer(pd.to_datetime(panel.signal_date)) + 1
    require((starts > 0).all(), "NON_SESSION_SIGNAL")
    rows = []
    for horizon in (5, 20):
        indices = starts[:, None] + np.arange(horizon + 1)
        dates = cal.sessions.to_numpy()[indices]
        key = pd.MultiIndex.from_arrays([np.repeat(panel.underlying_uid.to_numpy(), horizon+1),
                                         np.repeat(panel.ticker.to_numpy(), horizon+1), dates.ravel(),
                                         np.repeat("open", dates.size)], names=PRICE_KEYS)
        joined = prices.reindex(key)
        shape = (len(panel), horizon + 1)
        values = joined.price.to_numpy(dtype=float).reshape(shape)
        valid = joined.valid.eq(True).to_numpy().reshape(shape) & np.isfinite(values) & (values > 0)
        identity = joined.identity_status.isin(VERIFIED["identity_status"]).to_numpy().reshape(shape)
        actions = joined.action_status.isin(VERIFIED["action_status"]).to_numpy().reshape(shape)
        lifecycle = joined.lifecycle_status.isin(VERIFIED["lifecycle_status"]).to_numpy().reshape(shape)
        for i, p in enumerate(panel.itertuples(index=False)):
            censored = bool(dates[i, -1] >= np.datetime64("2026-01-01"))
            id_ok = bool(identity[i].all() and p.input_reason == "OK")
            action_ok = bool(actions[i].all())
            life_ok = bool(lifecycle[i].all()) and not censored
            endpoints = bool(valid[i, 0] and valid[i, -1])
            endpoint_ok = bool(not censored and id_ok and action_ok and life_ok and endpoints)
            path_ok = bool(endpoint_ok and valid[i].all())
            reason = ("CUTOFF_CENSORED" if censored else p.input_reason if p.input_reason != "OK" else
                      "HISTORICAL_IDENTITY_UNRESOLVED" if not id_ok else "CORPORATE_ACTION_UNRESOLVED" if not action_ok else
                      "LIFECYCLE_UNRESOLVED" if not life_ok else "MISSING_ENTRY" if not valid[i, 0] else
                      "MISSING_ENDPOINT" if not valid[i, -1] else "MISSING_INTERMEDIATE_FIELD" if not path_ok else "OK")
            row = {"decision_id": p.decision_id, "signal_date": pd.Timestamp(p.signal_date),
                   "underlying_uid": p.underlying_uid, "ticker": p.ticker, "horizon": horizon,
                   "cutoff_censored": censored, "endpoint_valid": endpoint_ok, "path_valid": path_ok,
                   "lifecycle_resolved": life_ok, "identity_resolved": id_ok, "action_resolved": action_ok,
                   "missing_entry": bool(not valid[i, 0] and not censored),
                   "missing_endpoint": bool(not valid[i, -1] and not censored),
                   "missing_intermediate_fields": bool(not valid[i, 1:-1].all() and not censored),
                   "observed_marks": int(valid[i].sum()), "required_marks": horizon+1,
                   "status": "COMPLETE" if path_ok else "MISSING", "reason": reason,
                   "planned_entry": p.planned_entry,
                   "label_end": cal.schedule.iloc[indices[i, -1]]["open"].isoformat(),
                   "clock": "STOCK_DAILY_PATH_NEXT_SESSION_OPEN", "source_role": source_role,
                   "price_source": str(sources[0]) if len(sources) else "NO_VALID_SOURCE",
                   "price_kind": ";".join(sorted(set(joined.iloc[i*(horizon+1):(i+1)*(horizon+1)].price_kind.dropna()))),
                   "evidence_domain": "REAL_STOCK_DAILY_PATH", "endpoint_role": "ENDPOINT_ONLY_DIAGNOSTIC",
                   "endpoint_return": float(values[i, -1]/values[i, 0]-1) if endpoint_ok else np.nan,
                   "absolute_return": np.nan, "mfe": np.nan, "mae": np.nan, "realized_volatility": np.nan,
                   "first_positive_session": np.nan,
                   "entry_mark": float(values[i, 0]) if valid[i, 0] else np.nan,
                   "exit_mark": float(values[i, -1]) if valid[i, -1] else np.nan}
            if path_ok:
                row.update(path_metrics(values[i]))
            rows.append(row)
    labels = pd.DataFrame(rows)
    for _, group in labels.groupby("horizon"):
        labels.loc[group.index, "fixed_weight"] = fixed_weights(group)
    return labels.sort_values(["horizon", "signal_date", "underlying_uid"]).reset_index(drop=True)


def sensitivity(group: pd.DataFrame, observed: str, returns: str) -> dict:
    """Partial identification, not a missing-value prediction or causal estimate."""
    mature = group[~group.cutoff_censored].copy()
    if mature.empty:
        return {"status": "NO_MATURE_POPULATION", "A": None, "q": None, "x_star": None}
    w = fixed_weights(mature)
    seen = mature[observed].astype(bool)
    require(np.isfinite(mature.loc[seen, returns]).all(), "OBSERVED_RETURN_NOT_FINITE")
    a = float((w[seen] * mature.loc[seen, returns]).sum())
    q = float(w[~seen].sum())
    if not (~seen).any():
        q = 0.
    return {"status": "FULLY_OBSERVED" if q == 0 else "NO_OBSERVED_LABELS" if not seen.any() else "PARTIALLY_IDENTIFIED",
            "mature_opportunities": len(mature), "mature_dates": int(mature.signal_date.nunique()),
            "observed": int(seen.sum()), "missing": int((~seen).sum()), "A": a, "q": q,
            "x_star": -a/q if q else None, "observed_weight_renormalized_mean": a/(1-q) if seen.any() else None,
            "minus_100pct_missing_scenario": a-q,
            "lower_bound_scope": "CONDITIONAL_ON_SIMPLE_UNLEVERED_SAME_EQUITY_RETURN_AND_VERIFIED_LIFECYCLE; NOT_TOTAL_RETURN_CLAIM",
            "finite_upper_bound": "NOT_IDENTIFIED", "formula": "full_population_mean = A + q * missing_weighted_mean"}


def _date_mean(frame: pd.DataFrame, column: str) -> float | None:
    return float(frame.groupby("signal_date")[column].mean().mean()) if len(frame) else None


def _description(frame: pd.DataFrame, column: str) -> dict:
    good = frame[np.isfinite(frame[column])]
    if good.empty:
        return {"rows": 0, "dates": 0, "mean_equal_date": None}
    daily = {str(pd.Timestamp(d).date()): float(v) for d, v in good.groupby("signal_date")[column].mean().items()}
    result = {"rows": len(good), "dates": len(daily), "mean_equal_date": _date_mean(good, column),
              "exploratory_95_interval": date_interval(daily), "q10": float(good[column].quantile(.1)),
              "median": float(good[column].median()), "q90": float(good[column].quantile(.9)),
              "positive_fraction": float(good[column].gt(0).mean())}
    for name in ("mfe", "mae", "realized_volatility", "first_positive_session"):
        if name in good:
            result["mean_" + name] = float(good[name].mean()) if good[name].notna().any() else None
    if "first_positive_session" in good:
        result["first_positive_session_median"] = float(good.first_positive_session.median()) if good.first_positive_session.notna().any() else None
        result["never_positive"] = int(good.first_positive_session.isna().sum())
    return result


def analyze(labels: pd.DataFrame, old: pd.DataFrame) -> tuple[pd.DataFrame, list, pd.DataFrame]:
    """Retain S/R masks; decompose numeric, added-sample and date-support effects."""
    keep = old[["decision_id", "horizon", "status", "reason", "absolute_return", "observed_marks"]].rename(
        columns={"status": "old_status", "reason": "old_reason", "absolute_return": "old_return", "observed_marks": "old_observed_marks"})
    result = labels.merge(keep, on=["decision_id", "horizon"], how="left", validate="one_to_one")
    require(result.old_status.notna().all(), "ORIGINAL_MASK_MISSING")
    result["old_path_valid"] = result.old_status.eq("COMPLETE")
    result["recovered_path"] = result.path_valid & ~result.old_path_valid
    result["recovered_endpoint"] = result.endpoint_valid & ~result.old_path_valid
    result["recovered_with_absent_ledger_marks"] = result.recovered_path & result.old_observed_marks.lt(result.required_marks)
    result["recovered_identity_only"] = result.recovered_path & result.old_observed_marks.eq(result.required_marks)
    summaries, coverage = [], []
    for horizon, group in result.groupby("horizon", sort=True):
        s = group[group.old_path_valid]
        retained = group[group.old_path_valid & group.path_valid]
        recovered = group[group.recovered_path]
        good = group[group.path_valid]
        end = group[group.endpoint_valid]
        common_dates = set(retained.signal_date) & set(recovered.signal_date)
        old_mean = _date_mean(s, "old_return")
        retained_old = _date_mean(retained, "old_return")
        retained_new = _date_mean(retained, "absolute_return")
        union_old_dates = good[good.signal_date.isin(retained.signal_date)]
        union_fixed_dates = _date_mean(union_old_dates, "absolute_return")
        new_mean = _date_mean(good, "absolute_return")
        minus = lambda a, b: a-b if a is not None and b is not None else None
        decomp = {"old_equal_observed_date_mean": old_mean, "new_equal_observed_date_mean": new_mean,
                  "old_sample_lost": len(s)-len(retained), "lost_sample_support_effect": minus(retained_old, old_mean),
                  "original_sample_numeric_repair": minus(retained_new, retained_old),
                  "recovered_samples_on_retained_S_dates": minus(union_fixed_dates, retained_new),
                  "date_support_weighting_change": minus(new_mean, union_fixed_dates),
                  "total_change": minus(new_mean, old_mean), "interpretation": "DESCRIPTIVE_DECOMPOSITION_NOT_CAUSAL_SELECTION_BIAS"}
        summaries.append({"horizon": int(horizon), "opportunities": len(group), "mature_population": int((~group.cutoff_censored).sum()),
                          "cutoff_censored": int(group.cutoff_censored.sum()), "endpoint_valid": len(end), "path_valid": len(good),
                          "remaining_endpoint_missing": int((~group.cutoff_censored & ~group.endpoint_valid).sum()),
                          "remaining_path_missing": int((~group.cutoff_censored & ~group.path_valid).sum()),
                          "missing_entry": int(group.missing_entry.sum()), "missing_endpoint": int(group.missing_endpoint.sum()),
                          "missing_intermediate_fields": int(group.missing_intermediate_fields.sum()),
                          "identity_unresolved": int((~group.cutoff_censored & ~group.identity_resolved).sum()),
                          "action_unresolved": int((~group.cutoff_censored & ~group.action_resolved).sum()),
                          "lifecycle_unresolved": int((~group.cutoff_censored & ~group.lifecycle_resolved).sum()),
                          "reason_counts_exclusive": group.reason.value_counts().to_dict(),
                          "recovered_with_absent_ledger_marks": int(group.recovered_with_absent_ledger_marks.sum()),
                          "recovered_identity_only": int(group.recovered_identity_only.sum()),
                          "canonical_strict_path": _description(good, "absolute_return"),
                          "endpoint_only_diagnostic": _description(end.drop(columns=[c for c in ["mfe", "mae", "realized_volatility", "first_positive_session"] if c in end]), "endpoint_return"),
                          "old_S_original": _description(s, "old_return"), "old_S_new_values": _description(retained, "absolute_return"),
                          "recovered_R": _description(recovered, "absolute_return"),
                          "S_R_common_date_count": len(common_dates),
                          "S_common_dates": _description(retained[retained.signal_date.isin(common_dates)], "absolute_return"),
                          "R_common_dates": _description(recovered[recovered.signal_date.isin(common_dates)], "absolute_return"),
                          "S_fixed_weight_contribution": float((retained.fixed_weight * retained.absolute_return).sum()),
                          "R_fixed_weight_contribution": float((recovered.fixed_weight * recovered.absolute_return).sum()),
                          "decomposition": decomp, "strict_sensitivity": sensitivity(group, "path_valid", "absolute_return"),
                          "endpoint_sensitivity": sensitivity(group, "endpoint_valid", "endpoint_return"),
                          "old_strict_sensitivity": sensitivity(group, "old_path_valid", "old_return")})
        for frequency in ("daily", "monthly"):
            keys = group.signal_date.dt.strftime("%Y-%m-%d" if frequency == "daily" else "%Y-%m")
            for period, part in group.groupby(keys):
                coverage.append({"horizon": int(horizon), "frequency": frequency, "period": period,
                                 "opportunities": len(part), "mature": int((~part.cutoff_censored).sum()),
                                 "censored": int(part.cutoff_censored.sum()), "endpoint_valid": int(part.endpoint_valid.sum()),
                                 "path_valid": int(part.path_valid.sum()), "old_path_valid": int(part.old_path_valid.sum()),
                                 "recovered_path": int(part.recovered_path.sum()),
                                 "endpoint_without_path": int((part.endpoint_valid & ~part.path_valid).sum()),
                                 "missing_entry": int(part.missing_entry.sum()), "missing_endpoint": int(part.missing_endpoint.sum()),
                                 "missing_intermediate_fields": int(part.missing_intermediate_fields.sum()),
                                 "fixed_missing_endpoint_weight": float(part.loc[~part.endpoint_valid, "fixed_weight"].sum())})
    return result, summaries, pd.DataFrame(coverage)


def run_coverage(output: Path | None, config: Path | None, *, input_path: Path | None = None, smoke: bool = False) -> dict:
    """Actual user CLI integration; original inputs/output never rewritten."""
    require(input_path is None, "UNBOUND_INPUT_REJECTED_BEFORE_OPEN")
    require(not smoke, "OVERNIGHT_REQUIRES_FULL_SCOPE")
    paths = resolve()
    root = paths.results_root / TEMPLATE / "overnight" / RUN_ID
    require(config is not None and config.resolve() == (root / "run_config.json").resolve(), "UNBOUND_CONFIG_REJECTED_BEFORE_OPEN")
    configuration = json.loads(original._bytes(config, CONFIG_SHA, []))
    output = (output or root / "run").resolve()
    require(root.resolve() in output.parents, "OVERNIGHT_OUTPUT_REQUIRED")
    output.mkdir(parents=True, exist_ok=True)
    from .independent_prices import load_independent_prices
    code = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in
            ("coverage.py", "independent_prices.py", "historical_quotes.py", "input_adapter.py", "expression.py", "contracts.py", "cli.py")}
    identity = hashlib.sha256(json.dumps([CONFIG_SHA, code], sort_keys=True).encode()).hexdigest()
    manifest_path = output / "run_manifest.json"
    checkpoint = {"run_identity": identity, "completed_stages": [], "artifact_sha256": {}, "code_sha256": code}
    if manifest_path.is_file():
        checkpoint = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(checkpoint["run_identity"] == identity, "OUTPUT_IDENTITY_CHANGED_PRESERVE_EXISTING_RUN")
        for name, digest in checkpoint["artifact_sha256"].items():
            require(hashlib.sha256((output / name).read_bytes()).hexdigest() == digest, "CHECKPOINT_ARTIFACT_CHANGED:" + name)
        if "finished" in checkpoint["completed_stages"]:
            require(set(checkpoint.get("option_artifact_sha256", {})) == set(OPTION_ARTIFACTS), "OPTION_EVIDENCE_BINDING_MISSING")
            for name, digest in checkpoint["option_artifact_sha256"].items():
                require(hashlib.sha256((output / "option_evidence" / name).read_bytes()).hexdigest() == digest,
                        "OPTION_EVIDENCE_CHANGED:" + name)
            return checkpoint
    def save_stage(stage, names):
        checkpoint["completed_stages"].append(stage)
        checkpoint["artifact_sha256"].update({name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in names})
        manifest_path.write_text(json.dumps(checkpoint, indent=2, allow_nan=False), encoding="utf-8")
    started = time.perf_counter()
    frames, vintages, reads = original.load_bound_inputs()
    panel = original.opportunity_panel({k: v for k, v in frames.items() if k != "a2_positions"}, vintages)
    expected = expected_price_keys(panel)
    expected.to_csv(output / "expected_price_keys.csv", index=False)
    panel.to_csv(output / "real_opportunities.csv", index=False)
    old_path = paths.results_root / TEMPLATE / "continuation/run/full_final/real_stock_path_labels.csv"
    prior = pd.read_csv(__import__('io').BytesIO(original._bytes(old_path, OLD_LABEL_SHA, reads)), dtype={"underlying_uid": str})
    if "original_reproduced" in checkpoint["completed_stages"]:
        old = pd.read_csv(output / "original_strict_labels.csv", dtype={"underlying_uid": str}, parse_dates=["signal_date"])
        trace = None
    else:
        old, trace = original.daily_labels(panel, frames["a2_positions"], frames["daily_u_membership"])
    columns = ["decision_id", "horizon", "status", "reason", "absolute_return"]
    compare = old[columns].merge(prior[columns], on=["decision_id", "horizon"], suffixes=("_now", "_prior"), validate="one_to_one")
    require(len(compare) == len(old) == len(prior) and compare.status_now.eq(compare.status_prior).all()
            and compare.reason_now.eq(compare.reason_prior).all()
            and np.allclose(compare.absolute_return_now, compare.absolute_return_prior, atol=1e-12, rtol=0, equal_nan=True), "ORIGINAL_REPRODUCTION_MISMATCH")
    if trace is not None:
        old.to_csv(output / "original_strict_labels.csv", index=False)
        trace.to_csv(output / "original_trace.csv", index=False)
        save_stage("original_reproduced", ["original_strict_labels.csv", "original_trace.csv", "expected_price_keys.csv", "real_opportunities.csv"])
    marks, evidence = load_independent_prices(expected, panel, output / "price_evidence")
    marks.to_parquet(output / "price_evidence/independent_price_keys.parquet", index=False)
    from .historical_quotes import write_qualification
    options = write_qualification(panel, output / "option_evidence")
    labels = market_labels(panel, marks)
    result, summaries, periods = analyze(labels, old)
    result.to_csv(output / "fixed_horizon_labels.csv", index=False)
    fields = ["cutoff_censored", "endpoint_valid", "path_valid", "lifecycle_resolved", "identity_resolved", "action_resolved",
              "missing_entry", "missing_endpoint", "missing_intermediate_fields", "old_path_valid", "old_reason",
              "recovered_path", "recovered_endpoint", "recovered_with_absent_ledger_marks", "recovered_identity_only",
              "old_observed_marks", "fixed_weight", "price_source", "price_kind", "reason"]
    wide = result.set_index(["decision_id", "horizon"])[fields].unstack("horizon")
    wide.columns = [f"{name}_{h}" for name, h in wide.columns]
    panel[["decision_id", "signal_date", "underlying_uid", "ticker"]].merge(wide.reset_index(), on="decision_id", validate="one_to_one").to_csv(output / "coverage_and_missingness.csv", index=False)
    periods.to_csv(output / "coverage_by_period.csv", index=False)
    (output / "fixed_horizon_summary.json").write_text(json.dumps(summaries, indent=2, allow_nan=False), encoding="utf-8")
    manifest = {"task_id": TEMPLATE, "overnight_task": configuration["overnight_task"], "run_id": RUN_ID,
                "config_sha256": CONFIG_SHA, "mode": "real-stock", "scope": "FULL_FROZEN_RANGE", "opportunity_rows": len(panel),
                "dates": int(panel.signal_date.nunique()), "uids": int(panel.underlying_uid.nunique()),
                "expected_price_keys": len(expected), "original_reproduction": "MATCHED_STATUS_REASON_RETURN_1E_12",
                "original_summary": original.summarize(old), "summary": summaries, "price_evidence": evidence,
                "option_qualification": options,
                "bound_source_reads": reads, "required_stage_success": len(panel) == 15000 and len(result) == 30000,
                "stock_path_research_status": "COMPLETED_EXPLORATORY_COVERAGE_AND_MISSINGNESS",
                "economic_verdict": "NOT_IDENTIFIABLE", "account_executability": "NOT_RUN_NO_ACCOUNT_AUTHORITY",
                "global_economic_read_count": "UNKNOWN", "new_exposure": "PRE2026_EXPLORATORY_LABELS",
                "wall_seconds": time.perf_counter()-started, "workers": 1}
    manifest["code_sha256"] = code
    manifest["run_identity"] = identity
    manifest["completed_stages"] = ["original_reproduced", "independent_prices", "full_labels", "missingness", "finished"]
    manifest["artifact_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.glob("*.csv"))}
    manifest["artifact_sha256"]["fixed_horizon_summary.json"] = hashlib.sha256((output / "fixed_horizon_summary.json").read_bytes()).hexdigest()
    manifest["option_artifact_sha256"] = {name: hashlib.sha256((output / "option_evidence" / name).read_bytes()).hexdigest()
                                        for name in OPTION_ARTIFACTS}
    manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return manifest
