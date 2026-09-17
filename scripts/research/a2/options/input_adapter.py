"""One pinned historical daily projection. Never rebuild/read mixed raw caches.

Read authority is established in the R1 design via the original producer's
physical output scope, then accepted artifact identities are checked here.
Caller-supplied paths/flags cannot create another source binding.
"""
from __future__ import annotations

import hashlib
import io
import json
import platform
import subprocess
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.common.storage_paths import resolve
from .contracts import TEMPLATE, calendar, require
from .expression import date_interval, path_metrics

BASELINE = "A_VS_A2_QUARTERLY_13F_R1"
CONFIG_SHA = "b33ec562f4c8d9d29fc74cfe3e21316516edcee7446b4ade3df1c41c177acffc"
BASELINE_SHA = "398cff8076f8c761d87c12ce195ba98e9201209499caaaf7a14ae05ac1605125"
HASH_LIST_SHA = "84770018a4a4f095b476d2af433eedad0457a9e5904dfc6b7b13b905bc1dd10b"
CHECKPOINT = "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1/raw_a2_top40_membership_checkpoint.parquet"
CHECKPOINT_SHA = "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17"
SOURCES = {
    "a2_top20": ("A2/top20_selections.parquet", ["signal_date", "ticker", "split", "a2_prediction", "a2_rank"]),
    "daily_u_membership": ("universe/daily_eligible_universe_membership.parquet",
                           ["signal_date", "ticker", "cusip", "active_13f_quarter", "required_observations", "U_t_fingerprint"]),
    "daily_active_quarter": ("universe/daily_active_quarter_ledger.parquet",
                             ["signal_date", "quarter_effective_date", "active_quarter_count", "quarter_latest_filing_timestamp"]),
    "a2_positions": ("A2/position_ledger.parquet", ["date", "ticker", "current_price", "mark_source_date", "stale_mark"]),
}


def _bytes(path: Path, expected: str, reads: list) -> bytes:
    # ONLY invoked for the finite producer-proven pure-period objects above.
    require(path.is_file(), "BOUND_SOURCE_MISSING:" + str(path))
    value = path.read_bytes()
    actual = hashlib.sha256(value).hexdigest()
    reads.append({"path": str(path), "bytes": len(value), "sha256": actual})
    require(actual == expected, "BOUND_SOURCE_HASH_MISMATCH:" + str(path))
    return value


def load_bound_inputs() -> tuple:
    paths = resolve()
    base = paths.results_root / BASELINE
    reads = []
    manifest = json.loads(_bytes(base / "audit/freeze_r1/frozen_baseline_manifest.json", BASELINE_SHA, reads))
    hashes = pd.read_csv(io.BytesIO(_bytes(base / "audit/freeze_r1/frozen_artifact_hashes.csv", HASH_LIST_SHA, reads)))
    require(manifest["artifact_hash_manifest"]["sha256"] == HASH_LIST_SHA, "HASH_LIST_BINDING")
    require(not hashes.artifact_id.duplicated().any(), "DUPLICATE_SOURCE_ID")
    hashes = hashes.set_index("artifact_id")
    frames = {}
    for key, (relative, columns) in SOURCES.items():
        p = (base / relative).resolve()
        require(Path(hashes.loc[key, "absolute_path"]).resolve() == p, "SOURCE_PATH_BINDING")
        frames[key] = pd.read_parquet(io.BytesIO(_bytes(p, hashes.loc[key, "sha256"], reads)), columns=columns)
    frames["checkpoint"] = pd.read_parquet(io.BytesIO(_bytes(paths.results_root / CHECKPOINT, CHECKPOINT_SHA, reads)))
    return frames, manifest["contracts"]["A2"]["effective_model_vintages"], reads


def validate_vintages(vintages: list) -> dict:
    result = {}
    for v in vintages:
        year = v["year"]
        require(year not in result, "DUPLICATE_VINTAGE")
        boundary = pd.Timestamp(v["prediction_min_date"])
        require(pd.Timestamp(v["train_max_date"]) <= pd.Timestamp(v["train_target_end_max"]) < boundary,
                "TRAIN_LABEL_AFTER_PREDICTION_BOUNDARY")
        require(boundary.year == year and pd.Timestamp(v["prediction_max_date"]) < pd.Timestamp("2026-01-01"),
                "VINTAGE_PERIOD")
        require(v["future_usage_contract"] == "CONSUME_FROZEN_PREDICTIONS;DO_NOT_RETRAIN_SILENTLY",
                "VINTAGE_USAGE")
        result[year] = v
    require(set(result) == {2023, 2024, 2025}, "VINTAGE_SET")
    return result


def _dates(frame: pd.DataFrame, column: str) -> None:
    frame[column] = pd.to_datetime(frame[column])
    require(frame[column].notna().all() and (frame[column] < pd.Timestamp("2026-01-01")).all(),
            "NON_PRE2026_OR_MISSING_DATE:" + column)
    require((frame[column] == frame[column].dt.normalize()).all(), "DAILY_DATE_NOT_MIDNIGHT")


def opportunity_panel(frames: dict, vintages: list) -> pd.DataFrame:
    """Decision-side columns only: no price path or evaluation labels accepted."""
    vm = validate_vintages(vintages)
    cp = frames["checkpoint"].copy()
    top = frames["a2_top20"].copy()
    eligible = frames["daily_u_membership"].copy()
    active = frames["daily_active_quarter"].copy()
    for f, name in [(cp, "decision_date"), (top, "signal_date"), (eligible, "signal_date"), (active, "signal_date")]:
        _dates(f, name)
    require(not cp.duplicated(["decision_date", "raw_rank"]).any(), "DUPLICATE_CHECKPOINT_RANK")
    require(not cp.duplicated(["decision_date", "security_id"]).any(), "DUPLICATE_CHECKPOINT_UID")
    cp = cp[cp.decision_date.between("2023-01-03", "2025-12-29") & (cp.raw_rank <= 20)].copy()
    require(len(cp) > 0 and cp.groupby("decision_date").raw_rank.apply(lambda x: set(x) == set(range(1,21))).all(),
            "ORIGINAL_TOP20_INCOMPLETE")
    require(cp.is_raw_top20.all() and (cp.prediction_asof_date == cp.decision_date).all(), "CHECKPOINT_ASOF")
    require(cp.oof_or_authoritative_replay_status.eq("FROZEN_AUTHORITATIVE_OOF").all(), "NOT_FROZEN_OOF")
    require(cp.source_research_id.eq(BASELINE).all(), "SIGNAL_SOURCE")
    require(not top.duplicated(["signal_date", "ticker"]).any(), "DUPLICATE_TOP20")
    paired = cp.merge(top, left_on=["decision_date", "ticker_if_available"], right_on=["signal_date", "ticker"],
                      how="outer", validate="one_to_one", indicator=True)
    require(paired._merge.eq("both").all() and paired.raw_rank.eq(paired.a2_rank).all() and
            np.allclose(paired.raw_score, paired.a2_prediction, rtol=0, atol=1e-12), "ORIGINAL_TOP20_IDENTITY_MISMATCH")
    require(not eligible.duplicated(["signal_date", "ticker"]).any(), "AMBIGUOUS_HISTORICAL_ELIGIBILITY")
    require(not active.signal_date.duplicated().any(), "AMBIGUOUS_ACTIVE_QUARTER")
    panel = paired.drop(columns="_merge").merge(eligible, on=["signal_date", "ticker"], how="left", validate="many_to_one")
    panel = panel.merge(active, on="signal_date", how="left", validate="many_to_one")
    panel["input_reason"] = "OK"
    valid_identity = (panel.cusip.notna() & panel.security_id.eq(panel.cusip) & panel.required_observations.ge(121)
                      & panel.active_quarter_count.eq(1) & (panel.quarter_effective_date <= panel.signal_date))
    panel.loc[~valid_identity, "input_reason"] = "HISTORICAL_UID_OR_ELIGIBILITY_UNVERIFIED"
    for year, v in vm.items():
        mask = panel.signal_date.dt.year.eq(year)
        require(panel.loc[mask, "model_hash"].eq(v["effective_model_vintage_fingerprint"]).all(), "MODEL_VINTAGE_BINDING")
        require(panel.loc[mask, "fold_id"].eq(v["vintage"]).all(), "FOLD_BINDING")
        require((panel.loc[mask, "training_cutoff"] == pd.Timestamp(v["train_target_end_max"])).all(), "TRAIN_CUTOFF_BINDING")
        require(panel.loc[mask, "signal_date"].between(v["prediction_min_date"], v["prediction_max_date"]).all(), "PREDICTION_VINTAGE_RANGE")
        panel.loc[mask, "train_label_end_max"] = v["train_target_end_max"]
    cal = calendar()
    loc = cal.sessions.get_indexer(panel.signal_date)
    require((loc >= 0).all(), "NON_SESSION_SIGNAL")
    panel["signal_information_asof"] = [x.isoformat() for x in cal.schedule.iloc[loc]["close"]]
    panel["planned_entry"] = [x.isoformat() for x in cal.schedule.iloc[loc+1]["open"]]
    panel["signal_available_at"] = None  # No invented contemporaneous publication timestamp.
    panel["availability_semantics"] = "FROZEN_HISTORICAL_CLOSE_SIGNAL_NEXT_OPEN_CONTRACT"
    panel["feature_information_asof"] = panel.signal_information_asof
    panel["underlying_uid"] = panel.security_id
    panel["decision_id"] = panel.signal_date.dt.strftime("%Y-%m-%d") + ":" + panel.security_id
    panel["option_action"] = "CASH"
    panel["option_reason"] = "NO_QUALIFIED_HISTORY_ONLY_BBO_BINDING"
    panel["option_quantity"] = 0
    panel["option_initial_cash_scenario"] = 10000.
    panel["option_cash_after"] = 10000.
    panel["stock_action"] = "PATH_LABEL_ONLY_NOT_EXECUTION"
    panel["oof_profile"] = None
    panel["evidence_domain"] = "REAL_STOCK_DAILY_PATH"
    # All entries below are original ex-ante fields or mechanical clock/binding facts.
    columns = ["decision_id", "signal_date", "underlying_uid", "ticker", "raw_rank", "raw_score", "fold_id",
               "training_cutoff", "train_label_end_max", "model_hash", "feature_contract_hash", "training_contract_hash",
               "source_research_id", "source_artifact_hash", "cusip", "active_13f_quarter", "U_t_fingerprint",
               "signal_information_asof", "feature_information_asof", "signal_available_at", "availability_semantics",
               "planned_entry", "input_reason", "option_action", "option_reason", "option_quantity",
               "option_initial_cash_scenario", "option_cash_after", "stock_action", "oof_profile", "evidence_domain"]
    return panel[columns].sort_values(["signal_date", "underlying_uid"]).reset_index(drop=True)


def daily_labels(panel: pd.DataFrame, positions: pd.DataFrame, membership: pd.DataFrame) -> tuple:
    """Outcome-only as-of projection; no replacement opportunities after gaps."""
    marks = positions.copy()
    members = membership.copy()
    _dates(marks, "date")
    _dates(members, "signal_date")
    require(not marks.duplicated(["date", "ticker"]).any(), "DUPLICATE_PRICE_MARK")
    require(not members.duplicated(["signal_date", "ticker"]).any(), "AMBIGUOUS_PATH_IDENTITY")
    # Pivot once, index all required sessions in one vectorized join per horizon.
    marks["valid"] = (marks.stale_mark.eq(False) & marks.mark_source_date.eq(marks.date)
                      & np.isfinite(marks.current_price) & marks.current_price.gt(0))
    prices = marks.set_index(["date", "ticker"])
    identities = members.set_index(["signal_date", "ticker"]).cusip
    cal = calendar()
    starts = cal.sessions.get_indexer(panel.signal_date) + 1
    rows, trace = [], []
    for horizon in (5, 20):
        indices = starts[:, None] + np.arange(horizon+1)
        dates = cal.sessions.to_numpy()[indices]
        ticker = np.repeat(panel.ticker.to_numpy(), horizon+1)
        key = pd.MultiIndex.from_arrays([dates.ravel(), ticker])
        joined = prices.reindex(key)
        values = joined.current_price.to_numpy().reshape(-1, horizon+1)
        mark_valid = joined.valid.fillna(False).to_numpy(dtype=bool).reshape(-1, horizon+1)
        ids = identities.reindex(key).to_numpy().reshape(-1, horizon+1)
        identity_ok = (ids == panel.underlying_uid.to_numpy()[:, None]).all(axis=1)
        cutoff = dates[:, -1] >= np.datetime64("2026-01-01")
        for i, p in enumerate(panel.itertuples(index=False)):
            row = {"decision_id": p.decision_id, "signal_date": p.signal_date, "underlying_uid": p.underlying_uid,
                   "horizon": horizon, "status": "MISSING", "reason": "MISSING_PATH_MARKS",
                   "clock": "STOCK_DAILY_PATH_NEXT_SESSION_OPEN", "evidence_domain": "REAL_STOCK_DAILY_PATH",
                   "role": "POSTHOC_LABEL_NOT_POLICY_INPUT", "observed_marks": int(mark_valid[i].sum()),
                   "required_marks": horizon+1, "identity_path_verified": bool(identity_ok[i]),
                   "planned_entry": p.planned_entry, "label_end": cal.schedule.iloc[indices[i,-1]]["open"].isoformat(),
                   "label_available_at": None, "price_source": BASELINE + "/A2/position_ledger.parquet",
                   "price_kind": "PIT_FORWARD_REHAB_OPEN_INDEX_NOT_BBO_FILL"}
            if p.input_reason != "OK":
                row["reason"] = p.input_reason
            elif cutoff[i]:
                row["reason"] = "CUTOFF_CENSORED"
            elif not identity_ok[i]:
                row["reason"] = "PATH_HISTORICAL_IDENTITY_MISSING_OR_CHANGED"
            elif not mark_valid[i].all():
                row["reason"] = "MISSING_PATH_MARKS" if joined.iloc[i*(horizon+1):(i+1)*(horizon+1)].current_price.isna().any() else "STALE_OR_INVALID_PATH_MARK"
            else:
                row.update(status="COMPLETE", reason="OK", **path_metrics(values[i]),
                           entry_mark=float(values[i,0]), exit_mark=float(values[i,-1]),
                           label_available_at=cal.schedule.iloc[indices[i,-1]]["close"].isoformat())
            rows.append(row)
            if i < 3:  # predeclared chronological date/UID order, independent of returns.
                trace.extend({"decision_id": p.decision_id, "horizon": horizon, "offset": j,
                              "date": pd.Timestamp(dates[i,j]), "ticker": p.ticker,
                              "mark": float(values[i,j]) if np.isfinite(values[i,j]) else None,
                              "valid_mark": bool(mark_valid[i,j]), "historical_cusip": ids[i,j],
                              "reason": row["reason"]} for j in range(horizon+1))
    return pd.DataFrame(rows), pd.DataFrame(trace)


def summarize(labels: pd.DataFrame) -> list:
    summaries = []
    for horizon, group in labels.groupby("horizon", sort=True):
        good = group[group.status.eq("COMPLETE")]
        daily = {str(d.date()): float(x) for d,x in good.groupby("signal_date").absolute_return.mean().items()} if len(good) else {}
        row = {"horizon": int(horizon), "opportunities": len(group), "complete": len(good), "missing": len(group)-len(good),
               "decision_dates": int(group.signal_date.nunique()), "complete_dates": int(good.signal_date.nunique()),
               "uids": int(group.underlying_uid.nunique()), "complete_uids": int(good.underlying_uid.nunique()),
               "reasons": group.reason.value_counts().to_dict(), "mean_date_absolute_return": float(np.mean(list(daily.values()))) if daily else None,
               "exploratory_95_interval": date_interval(daily), "population": "COMPLETE_LEDGER_MARK_PATHS_CONDITIONAL_ON_OBSERVABILITY",
               "full_population_mean": "NOT_IDENTIFIABLE_MISSING_NONRANDOM_PATHS", "evidence_domain": "REAL_STOCK_DAILY_PATH"}
        if len(good):
            row.update(q10=float(good.absolute_return.quantile(.1)), median=float(good.absolute_return.median()),
                       q90=float(good.absolute_return.quantile(.9)), positive_fraction=float(good.absolute_return.gt(0).mean()),
                       mean_mfe=float(good.mfe.mean()), mean_mae=float(good.mae.mean()),
                       mean_realized_volatility=float(good.realized_volatility.mean()),
                       first_positive_session_median=(float(good.first_positive_session.dropna().median())
                                                      if good.first_positive_session.notna().any() else None),
                       never_positive=int(good.first_positive_session.isna().sum()))
        summaries.append(row)
    return summaries


def run_real_stock(output: Path | None, config: Path | None, *, smoke: bool = False, input_path: Path | None = None) -> dict:
    require(input_path is None, "UNBOUND_INPUT_REJECTED_BEFORE_OPEN")
    paths = resolve()
    canonical = paths.results_root / TEMPLATE / "continuation/run"
    require(config is not None and config.resolve() == (canonical / "run_config.json").resolve(), "UNBOUND_CONFIG_REJECTED_BEFORE_OPEN")
    config_bytes = _bytes(config, CONFIG_SHA, [])
    configuration = json.loads(config_bytes.decode("utf-8-sig"))
    output = (output or canonical / ("smoke" if smoke else "full")).resolve()
    require(canonical.resolve() in output.parents, "CONTINUATION_OUTPUT_REQUIRED")
    started = time.perf_counter()
    tracemalloc.start()
    source_names = ["input_adapter.py", "cli.py", "expression.py", "contracts.py"]
    code = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in source_names}
    key = hashlib.sha256(json.dumps([CONFIG_SHA, code, smoke], sort_keys=True).encode()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    old_path = output / "run_manifest.json"
    if old_path.exists():
        old = json.loads(old_path.read_text())
        require(old["run_identity"] == key, "OUTPUT_IDENTITY_CHANGED_PRESERVE_EXISTING_RUN")
    frames, vintages, reads = load_bound_inputs()
    loaded = time.perf_counter()
    # Explicit decision projection prevents outcome columns crossing this interface.
    panel = opportunity_panel({k: v for k,v in frames.items() if k != "a2_positions"}, vintages)
    full_rows = len(panel)
    if smoke:
        panel = panel[panel.signal_date.eq(panel.signal_date.min())].reset_index(drop=True)
    planned = time.perf_counter()
    labels, trace = daily_labels(panel, frames["a2_positions"], frames["daily_u_membership"])
    labelled = time.perf_counter()
    summary = summarize(labels)
    require(len(panel) > 0, "ZERO_REAL_COHORT")
    any_complete = all(x["complete"] > 0 for x in summary)
    files = {}
    for name, frame in [("opportunities", panel), ("stock_path_labels", labels), ("trace", trace),
                        ("coverage", labels[["decision_id", "horizon", "status", "reason", "observed_marks", "required_marks", "identity_path_verified"]])]:
        filename = "real_" + name + ".csv"
        frame.to_csv(output / filename, index=False)
        files[filename] = hashlib.sha256((output / filename).read_bytes()).hexdigest()
    (output / "stock_path_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    files["stock_path_summary.json"] = hashlib.sha256((output / "stock_path_summary.json").read_bytes()).hexdigest()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    manifest = {"task_id": TEMPLATE, "continuation_of": configuration["continuation_of"], "run_identity": key,
                "config_sha256": CONFIG_SHA, "code_sha256": code, "mode": "real-stock", "scope": "SMOKE_FIRST_DATE" if smoke else "FULL_FROZEN_RANGE",
                "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=paths.repo_root, text=True).strip(),
                "python": platform.python_version(), "executable": __import__('sys').executable,
                "input_binding_status": "VERIFIED_FROZEN_SIGNALS_LIMITED_PRICE_OBSERVATIONS",
                "stock_path_research_status": ("SMOKE_ONLY" if smoke else "COMPLETED_WITH_PARTIAL_LABEL_COVERAGE") if any_complete else "NOT_RUN_ZERO_COMPLETE_COHORT",
                "required_stage_success": any_complete and not smoke and len(panel) == full_rows,
                "opportunity_rows": len(panel), "full_scope_rows": full_rows, "dates": int(panel.signal_date.nunique()),
                "uids": int(panel.underlying_uid.nunique()), "signal_start": str(panel.signal_date.min().date()), "signal_end": str(panel.signal_date.max().date()),
                "summary": summary, "artifact_sha256": files, "bound_source_reads": reads,
                "option_data_qualification_status": "NO_QUALIFIED_HISTORY_ONLY_BBO_BINDING",
                "option_quote_replay_status": "NOT_RUN", "real_option_pairs": 0,
                "economic_verdict": "NOT_IDENTIFIABLE", "account_executability_status": "NOT_RUN_MISSING_ACCOUNT_POLICY",
                "provider_probe": {"requests": 0, "budget": 0, "entitlement": "UNKNOWN", "history_probe": "NOT_RUN_NO_ELIGIBLE_EXPIRED_HISTORY_ENDPOINT",
                                   "reuse": "ORIGINAL_R1_DOCUMENTED_MOOMOO_CHAIN_NO_EXPIRED_SUPPORT"},
                "holdout_exposure": configuration["exposure"], "registration": configuration["registration"],
                "independent_review_status": "PENDING", "global_anti_bloat": "UNKNOWN_INCOMPLETE_PRIOR_ACCOUNTING",
                "performance": {"wall_seconds": time.perf_counter()-started, "load_seconds": loaded-started,
                                "binding_seconds": planned-loaded, "labels_seconds": labelled-planned,
                                "python_traced_peak_bytes": peak, "workers": 1,
                                "optimization": "one indexed mark/identity projection per horizon; cached XNYS schedule"}}
    old_path.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    (output / "run.log").write_text(json.dumps({"entry": "scripts.research.a2.options.cli --mode real-stock",
                                               "adapter": "load_bound_inputs -> opportunity_panel -> daily_labels -> summarize",
                                               "performance": manifest["performance"], "rows": len(panel)}, indent=2), encoding="utf-8")
    return manifest
