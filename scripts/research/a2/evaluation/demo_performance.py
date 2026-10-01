"""Descriptive updated A2 display, reusing the frozen open-ended ledger engine.

No training, parameter selection, benchmark selection or broker operation.
Historical/frozen outputs are read-only; a new run publishes its own manifest.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import uuid

import numpy as np
import pandas as pd

SOURCE_ID = "A2_UPDATED_RESEARCH"
EVENT_REVIEW_POLICY = "TIER1_3_CONFIRMED_NON_CORPORATE_ACTION_ONLY"
ENGINE_SHA = "094bee1c429f059113521388a7483578bcdf4ad55f3af66b13469d75009741c6"
CONTRACT_SHA = "3d6f6411b2f3e22a8af9e1e34f32c31c4cefec38ec3fcf7ead39c34721664b26"
MODEL_2026_SHA = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
EVALUATION = {"signal_execution": "close signal -> next US equity session open",
    "cost_bps_round_trip": 10, "cost_formula": "0.5 * traded_notional * 10 / 10000",
    "turnover": "0.5 * traded_notional / pretrade_nav", "terminal_liquidation": False,
    "initial_nav": 1, "top_n": 20, "weighting": "EQUAL_WEIGHT_LONG_ONLY",
    "price_basis": "PIT_FORWARD_REHAB_INDEX", "training_rows_2026_plus": 0}
LIMITATIONS = [
    "Descriptive replay of already exposed periods; no untouched holdout or live-account claim.",
    "Rankings are signals. Holdings change at the next verified session open; the latest signal can remain pending.",
    "The first signal date is a cash/NAV-1 baseline. Later values are post-trade open marks, not closing NAV.",
    "No terminal liquidation. Costs are 0.5 times actual traded notional times 10/10000; cash earns zero.",
    "Performance stops before a missing execution price or unresolved held corporate-action event; no future fill.",
    "Partial stock-pool coverage is retained. Vendor rehab vintages were acquired later and replayed by event date.",
    "Frozen historical comparison artifacts remain separate; this replay does not replace their authority.",
]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reference(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def verified(ref):
    path = Path(ref["path"])
    if digest(path) != ref["sha256"]:
        raise ValueError("DEMO_PERFORMANCE_SOURCE_HASH_CHANGED:" + path.name)
    return path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def canonical_manifest(path):
    """Resolve a latest pointer only when it exactly copies its immutable run."""
    pointer = reference(path)
    value = read(path)
    canonical = Path(value["report_path"]).resolve()
    if digest(canonical) != pointer["sha256"]:
        raise ValueError("HISTORICAL_POINTER_CANONICAL_HASH_MISMATCH")
    return canonical, pointer


def _timestamp(value, label):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(label + "_TIMESTAMP_UNBOUND")
    return stamp


def _authority(paths):
    contract_path = paths.backtest_root / "research/a2/demo_2026_calendar_replay/contract.json"
    engine_path = paths.repo_root / "scripts/v22/a_a2_2026_pre_risk_holdout_r1.py"
    refs = [{"path": str(contract_path), "sha256": CONTRACT_SHA},
            {"path": str(engine_path), "sha256": ENGINE_SHA}]
    for item in refs:
        verified(item)
    contract = read(contract_path)
    if (contract["execution"] != "CLOSE_SIGNAL_NEXT_SESSION_OPEN_EQUAL_WEIGHT_TOP20_OPEN_TO_OPEN_NO_TERMINAL_LIQUIDATION"
            or contract["cost_formula"] != EVALUATION["cost_formula"] or contract["top_n"] != 20):
        raise ValueError("OPEN_ENDED_EXECUTION_CONTRACT_CHANGED")
    name = "a2_demo_frozen_open_ledger_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, engine_path)
    engine = importlib.util.module_from_spec(spec)
    sys.modules[name] = engine
    spec.loader.exec_module(engine)
    return engine, refs


def _validate_rankings(frame, models):
    required = ["target_date", "ticker", "security_id", "rank", "score", "model_sha256", "model_year"]
    if frame.empty or not set(required) <= set(frame) or frame[required].isna().any().any():
        raise ValueError("UPDATED_RANKING_SCHEMA_OR_IDENTITY_MISSING")
    frame = frame.copy()
    frame["target_date"] = pd.to_datetime(frame.target_date).dt.strftime("%Y-%m-%d")
    if not np.isfinite(frame[["rank", "score", "model_year"]].to_numpy(float)).all():
        raise ValueError("UPDATED_RANKING_NONFINITE")
    for day, part in frame.groupby("target_date", sort=True):
        if (len(part) != 40 or set(part["rank"]) != set(range(1, 41))
                or part.ticker.nunique() != 40 or part.security_id.nunique() != 40):
            raise ValueError("UPDATED_TOP40_CARDINALITY_OR_IDENTITY:" + day)
        year = int(day[:4])
        if (not part.model_year.eq(year).all() or str(year) not in models
                or not part.model_sha256.eq(models[str(year)]["sha256"]).all()):
            raise ValueError("UPDATED_RANKING_MODEL_IDENTITY:" + day)
    return frame.sort_values(["target_date", "rank"]).reset_index(drop=True)


def _daily_rows(report):
    day, universe = report["data_date"], report["universe"]
    if report.get("status") != "READY" or report.get("model_id") != "A2_HGB" or report.get("model_sha256") != MODEL_2026_SHA:
        raise ValueError("CURRENT_RECOMMENDATION_NOT_FROZEN_READY_A2")
    if not day.startswith("2026-"):
        raise ValueError("CURRENT_RECOMMENDATION_MODEL_YEAR_NOT_BOUND")
    rows = [{"target_date": day, "ticker": row["ticker"], "security_id": row["security_id"],
        "rank": row["rank"], "score": row["score"], "model_year": 2026,
        "model_sha256": report["model_sha256"], "universe_id": universe["universe_id"],
        "universe_quarter": universe.get("quarter"), "universe_effective_date": universe.get("effective_date"),
        "institution_count": universe.get("institution_count"), "source": "DAILY_READY_RECOMMENDATION"}
        for row in report.get("ranked_rows", []) if row["rank"] <= 40]
    coverage = {"target_date": day, "status": "PARTIAL" if report["coverage"]["excluded_count"] else "READY",
        "eligible_count": report["coverage"]["eligible_count"], "mapped_count": report["coverage"]["mapped_count"],
        "excluded_count": report["coverage"]["excluded_count"], "universe_member_count": universe.get("universe_member_count"),
        "quarter": universe.get("quarter"), "effective_date": universe.get("effective_date"),
        "institution_count": universe.get("institution_count"), "model_year": 2026}
    return pd.DataFrame(rows), coverage


def load_rankings(paths, historical_manifest_path, current_report_path):
    historical = read(historical_manifest_path)
    if historical.get("status") not in {"READY", "PARTIAL"}:
        raise ValueError("HISTORICAL_RANKINGS_NOT_COMPLETED")
    refs = [reference(historical_manifest_path)]
    base = pd.read_parquet(verified(historical["outputs"]["top40"]))
    coverage = pd.read_parquet(verified(historical["outputs"]["coverage"]))
    refs.extend(historical["outputs"][key] for key in ("top40", "coverage"))
    historical_stamp = _timestamp(historical["generated_at"], "HISTORICAL")
    base["target_date"] = pd.to_datetime(base.target_date).dt.strftime("%Y-%m-%d")
    coverage["target_date"] = pd.to_datetime(coverage.target_date).dt.strftime("%Y-%m-%d")
    last = str(base.target_date.max())[:10]
    explicit = read(current_report_path)
    # Even an older same-day report is bound as an input, but cannot replace the
    # newer historical replay's signal. Only that last day can overlap.
    if explicit.get("status") != "READY" or explicit.get("data_date", "") < last:
        raise ValueError("CURRENT_REPORT_NOT_READY_OR_BEHIND_HISTORY")
    _daily_rows(explicit)
    upper = explicit["data_date"]
    refs.append(reference(current_report_path))
    reports = {}
    sources = list((paths.daily_root / "A2_today_recommendation/history").glob("*.json"))
    sources.append(Path(current_report_path))
    for path in sources:
        value = read(path)
        if value.get("status") != "READY" or not last <= value.get("data_date", "") <= upper:
            continue
        stamp = _timestamp(value["generated_at"], "READY_RECOMMENDATION")
        if value["data_date"] == last and stamp <= historical_stamp:
            continue
        key = (stamp, str(path.resolve()))
        old = reports.get(value["data_date"])
        if old is None or key >= old[0] or path == Path(current_report_path):
            reports[value["data_date"]] = (key, path, value)
    current_dates = set(reports)
    frames = [base.loc[~base.target_date.isin(current_dates)]]
    cover = coverage.loc[~coverage.target_date.isin(current_dates)].to_dict("records")
    selected_reports = []
    for _, path, report in sorted(reports.values(), key=lambda item: item[2]["data_date"]):
        extra, counts = _daily_rows(report)
        frames.append(extra); cover.append(counts)
        canonical, _ = canonical_manifest(path)
        ref = reference(canonical); refs.append(ref); selected_reports.append(ref)
    merged = _validate_rankings(pd.concat(frames, ignore_index=True), historical["models"]["artifacts"])
    return merged, pd.DataFrame(cover).sort_values("target_date").reset_index(drop=True), refs, selected_reports


def _prior_verified_performance(paths, path, historical_path, models, authority, calendar_lineage, end):
    """Bind one explicitly requested completed replay, never choose a pointer."""
    path = Path(path).resolve()
    runs = (paths.daily_root / "A2_updated_research/runs").resolve()
    if path.name != "manifest.json" or path.parent.parent != runs:
        raise ValueError("PRIOR_PERFORMANCE_REQUIRES_IMMUTABLE_RUN_MANIFEST")
    manifest_ref = reference(path)
    prior = read(verified(manifest_ref))
    historical_ref = reference(historical_path)
    cutoff = prior.get("performance_end_date", "")
    if (prior.get("schema_version") != 1 or prior.get("source_id") != SOURCE_ID
            or prior.get("status") not in {"READY", "PARTIAL"}
            or Path(prior.get("report_path", "")).resolve() != path
            or prior.get("ranking_manifest") != historical_ref
            or prior.get("evaluation") != EVALUATION
            or prior.get("model_fit_count") != 0 or prior.get("parameter_search_count") != 0
            or not cutoff or not prior.get("ranking_start_date", "") <= cutoff <= prior.get("ranking_end_date", "") <= end
            or prior.get("performance_points", 0) < 2
            or prior.get("calendar_lineage") != calendar_lineage):
        raise ValueError("PRIOR_PERFORMANCE_IDENTITY_OR_CLOCK_MISMATCH")
    contract_ref = prior["evaluation_contract"]
    contract = read(verified(contract_ref))
    gate = {"gate": "FIVE_EXACT_OHLC_AND_ALL_OVERLAP_EXACT_OPEN_CLOSE_V1",
            "consumer_fields": ["open", "close"], "model_feature_eligibility_granted": False,
            "qualification_is_fixed_before_performance": True}
    rank_ref = {key: prior["outputs"]["rankings"][key] for key in ("path", "sha256")}
    if (contract.get("schema") != "A2_UPDATED_DESCRIPTIVE_EVALUATION_CONTRACT_V1"
            or contract.get("source_id") != SOURCE_ID or contract.get("evaluation") != EVALUATION
            or contract.get("ranking_manifest") != historical_ref or contract.get("authorities") != authority
            or contract.get("calendar_lineage") != calendar_lineage
            or contract.get("safe_execution_end_date") != cutoff
            or contract.get("ranking_start_date") != prior["ranking_start_date"]
            or contract.get("ranking_end_date") != prior["ranking_end_date"]
            or contract.get("model_fit_count") != 0 or contract.get("parameter_search_count") != 0
            or contract.get("execution_price_extension") != gate
            or contract.get("rankings") != rank_ref or contract.get("price_inputs") != prior["price_inputs"]):
        raise ValueError("PRIOR_PERFORMANCE_SEMANTIC_CONTRACT_MISMATCH")
    old_source = read(verified(contract["current_report"]))
    _daily_rows(old_source)
    if old_source["data_date"] != prior["ranking_end_date"]:
        raise ValueError("PRIOR_PERFORMANCE_SOURCE_DATE_MISMATCH")
    price_inputs = read(verified(prior["price_inputs"]))
    if (price_inputs.get("price_basis") != EVALUATION["price_basis"]
            or price_inputs.get("vintage_semantics") != "LATER_VENDOR_REHAB_SNAPSHOT_NOT_HISTORICAL_PUBLICATION_VINTAGE"
            or price_inputs.get("start_date") != prior["ranking_start_date"]
            or price_inputs.get("end_date") != prior["ranking_end_date"]
            or not contract.get("price_refs")
            or price_inputs.get("refs") != contract.get("price_refs")):
        raise ValueError("PRIOR_PERFORMANCE_PRICE_PROOF_MISMATCH")
    refs = [manifest_ref, contract_ref, prior["price_inputs"], contract["current_report"],
            *prior["outputs"].values(), *contract["authorities"], *contract["input_refs"], *contract["price_refs"]]
    checked = {}
    for ref in refs:
        key = str(Path(ref["path"]).resolve())
        if key in checked and checked[key] != ref["sha256"]:
            raise ValueError("PRIOR_PERFORMANCE_CONFLICTING_SOURCE_HASH")
        if key not in checked:
            verified(ref)
            checked[key] = ref["sha256"]
    frames = {name: pd.read_parquet(verified(prior["outputs"][name])) for name in
              ("rankings", "coverage", "portfolio_daily", "positions", "trades", "price_paths")}
    frames["rankings"] = _validate_rankings(frames["rankings"], models)
    counts = frames["coverage"]
    counts["target_date"] = pd.to_datetime(counts.target_date).dt.strftime("%Y-%m-%d")
    if counts.target_date.duplicated().any() or set(counts.target_date) != set(frames["rankings"].target_date):
        raise ValueError("PRIOR_PERFORMANCE_COVERAGE_MISMATCH")
    marks = frames["price_paths"]
    marks["date"] = pd.to_datetime(marks.date)
    if (not {"date", "ticker", "open", "close", "adjustment", "source"} <= set(marks)
            or marks.duplicated(["date", "ticker"]).any()
            or not marks.adjustment.eq(EVALUATION["price_basis"]).all()
            or not marks.source.eq("VERIFIED_RAW_PLUS_PIT_REHAB").all()
            or not np.isfinite(marks[["open", "close"]].to_numpy(float)).all()
            or not marks[["open", "close"]].gt(0).all().all()):
        raise ValueError("PRIOR_PERFORMANCE_EXECUTION_MARKS_INVALID")
    return {"manifest": prior, "ref": manifest_ref, "contract": contract, "frames": frames,
            "cutoff": cutoff, "refs": [{"path": path, "sha256": sha} for path, sha in sorted(checked.items())]}


def _assert_prior_prefix(name, frame, prior, date_column, keys):
    """Require every recorded field and key, including costs and identities."""
    old = prior["frames"][name].copy()
    new = frame.copy()
    old[date_column] = pd.to_datetime(old[date_column])
    new[date_column] = pd.to_datetime(new[date_column])
    cutoff = pd.Timestamp(prior["cutoff"])
    old = old.loc[old[date_column].le(cutoff)].sort_values(keys).reset_index(drop=True)
    new = new.loc[new[date_column].le(cutoff)].sort_values(keys).reset_index(drop=True)
    try:
        if set(old.columns) != set(new.columns):
            raise AssertionError("column set changed")
        pd.testing.assert_frame_equal(old, new[list(old.columns)], check_exact=True, check_dtype=False)
    except AssertionError as exc:
        raise ValueError("PRIOR_PERFORMANCE_PREFIX_CHANGED:" + name) from exc


def _reviewed_close_revisions(overlap, prior, reconciliation):
    """Accept an explicitly evidenced close vintage; never change ledger marks."""
    audit = read(verified(reconciliation))
    if (audit.get("schema") != "A2_RETAINED_CLOSE_VINTAGE_REVIEW_V1"
            or audit.get("policy") != "RETAIN_OLD_EXACT_MARKS_APPEND_NEW_DATES"
            or audit.get("allowed_fields") != ["close"]):
        raise ValueError("PRIOR_CLOSE_REVIEW_CONTRACT_INVALID")
    origin = read(verified(audit["prior_manifest"]))
    from scripts.research.a2.evaluation.demo_performance_prices import _current_entries
    historical = origin["ranking_manifest"]
    source_entries = []
    for ref in (read(verified(origin["evaluation_contract"]))["current_report"], audit["current_report"]):
        source_path = verified(ref)
        entries, _ = _current_entries(source_path, Path(historical["path"]).resolve(), historical["sha256"],
            lambda path, expected: verified({"path": str(path), "sha256": expected}))
        source_entries.append({row["ticker"]: row for row in entries})
    original = pd.read_parquet(verified(origin["outputs"]["price_paths"]))
    original["date"] = pd.to_datetime(original["date"])
    captured = pd.read_parquet(verified(audit["captured_current_prices"]))
    captured["trade_date"] = pd.to_datetime(captured["trade_date"])
    for ref in audit["source_refs"]:
        verified(ref)
    changes = overlap.loc[overlap.close_prior.ne(overlap.close_current)]
    reviews = audit.get("reviews", [])
    if not reviews or len({(item["date"], item["ticker"]) for item in reviews}) != len(reviews):
        raise ValueError("PRIOR_CLOSE_REVIEW_KEYS_INVALID")
    allowed = {}
    for item in reviews:
        day, ticker = pd.Timestamp(item["date"]), item["ticker"]
        old_entry, new_entry = (entries[ticker] for entries in source_entries)
        for entry, raw_ref in ((old_entry, item["old_raw"]), (new_entry, item["new_raw"])):
            recorded = [{"path": row["path"], "sha256": row["sha256"]} for row in entry["raw_sources"]]
            if (raw_ref not in recorded or item["shared_anchor"] not in recorded
                    or entry["rehab"]["sha256"] != item["shared_rehab"]["sha256"]):
                raise ValueError("PRIOR_CLOSE_REVIEW_SOURCE_BINDING_INVALID")
        old = original.loc[original.date.eq(day) & original.ticker.eq(ticker)]
        new = captured.loc[captured.trade_date.eq(day) & captured.ticker.eq(ticker)]
        bars = []
        for ref in (item["old_raw"], item["new_raw"]):
            frame = pd.read_csv(verified(ref)).rename(columns={
                "moomoo_symbol": "code", "fetched_at_utc": "observed_at"})
            date_column = "trade_date" if "trade_date" in frame else "date"
            row = frame.loc[pd.to_datetime(frame[date_column]).eq(day) & frame.ticker.eq(ticker)]
            if len(row) != 1 or not row.source.eq("MOOMOO_OPEND").all() or not row.adjustment.eq("raw").all():
                raise ValueError("PRIOR_CLOSE_REVIEW_RAW_QUOTE_INVALID")
            bars.append(row.iloc[0])
        before, after = bars
        if (len(old) != 1 or len(new) != 1 or day != pd.Timestamp(origin["performance_end_date"])
                or day > pd.Timestamp(prior["cutoff"])
                or any(before[field] != after[field] for field in ("code", "open", "high", "low"))
                or before.close == after.close
                or pd.Timestamp(before.observed_at) >= pd.Timestamp(after.observed_at)
                or old.iloc[0].open != new.iloc[0].open):
            raise ValueError("PRIOR_CLOSE_REVIEW_NOT_CLOSE_ONLY")
        # Shared, hash-bound anchor and rehab prove the same price coordinate.
        verified(item["shared_anchor"])
        verified(item["shared_rehab"])
        allowed[(day, ticker)] = (old.iloc[0].open, old.iloc[0].close, new.iloc[0].close)
    for item in changes.itertuples(index=False):
        expected = allowed.get((item.trade_date, item.ticker))
        if expected != (item.open_prior, item.close_prior, item.close_current):
            raise ValueError("PRIOR_PERFORMANCE_PREFIX_CHANGED:price_paths")


def _retain_prior_execution_marks(prices, prior, reconciliation=None):
    """Reuse qualified adjusted open/close only; unknown OHLCV stays unknown."""
    marks = prior["frames"]["price_paths"]
    marks = marks.loc[marks.date.le(pd.Timestamp(prior["cutoff"]))]
    marks = marks[["date", "ticker", "open", "close"]].rename(columns={"date": "trade_date"})
    overlap = marks.merge(prices, on=["trade_date", "ticker"], suffixes=("_prior", "_current"))
    if not overlap.open_prior.eq(overlap.open_current).all():
        raise ValueError("PRIOR_PERFORMANCE_PREFIX_CHANGED:price_paths")
    if not overlap.close_prior.eq(overlap.close_current).all():
        if reconciliation is None:
            raise ValueError("PRIOR_PERFORMANCE_PREFIX_CHANGED:price_paths")
        _reviewed_close_revisions(overlap, prior, reconciliation)
    keys = ["trade_date", "ticker"]
    prefix = prices.set_index(keys).reindex(pd.MultiIndex.from_frame(marks[keys]))
    prefix["open"] = marks.open.to_numpy()
    prefix["close"] = marks.close.to_numpy()
    prefix = prefix.reset_index()
    tail = prices.loc[prices.trade_date.gt(pd.Timestamp(prior["cutoff"]))]
    return pd.concat([prefix, tail], ignore_index=True).sort_values(keys).reset_index(drop=True)


def fill_missing_signals(paths, historical_path, current_path, rankings, coverage, sessions, output_dir, progress):
    """Infer only unsaved post-history 2026 sessions; never create forward history."""
    from scripts.common.daily_support import save
    first, end = rankings.target_date.min(), rankings.target_date.max()
    required = {day for day in sessions if first <= day <= end}
    missing = sorted(required - set(rankings.target_date))
    if not missing:
        return rankings, coverage, None
    historical, acquired = read(historical_path), read(current_path)
    historical_end = pd.read_parquet(verified(historical["outputs"]["top40"]), columns=["target_date"]).target_date.max()
    if any(day <= str(historical_end)[:10] or not day.startswith("2026-") for day in missing):
        raise ValueError("UPDATED_RANKINGS_SESSION_COVERAGE_FAILURE:ONLY_POST_HISTORY_2026_CAN_BE_REPLAYED")
    if acquired.get("data_date") != end or acquired.get("status") != "READY":
        raise ValueError("MISSING_SIGNAL_CURRENT_SOURCE_NOT_READY")
    work = Path(output_dir) / "missing_signals"
    work.mkdir(parents=True, exist_ok=False)
    universe_path = Path(acquired["universe"]["report_path"])
    rehab_path = Path(current_path).parent / "rehab_receipt.json"
    contract = {"schema": "A2_MISSED_SESSION_INFERENCE_CONTRACT_V1", "missing_dates": missing,
        "historical_manifest": reference(historical_path), "current_report": reference(current_path),
        "universe_report": reference(universe_path), "rehab_receipt": reference(rehab_path),
        "start_date": missing[0], "end_date": end, "model_sha256": MODEL_2026_SHA,
        "source": "MISSED_SESSION_DESCRIPTIVE_REPLAY", "model_fit_count": 0,
        "historical_latest_changed": False, "forward_history_created": False}
    save(work / "contract.json", contract)
    progress(f"补算 {len(missing)} 个尚未保存的交易日推荐，使用对应日期股票池和已冻结 A2 模型。")
    from scripts.research.a2.inference.historical_top40_universe import build_universe_schedule
    from scripts.research.a2.inference.historical_top40_models import build_models
    from scripts.research.a2.inference.historical_top40_prices import build_price_features
    from scripts.research.a2.inference.historical_top40 import ranked_predictions, write_frame
    pool = build_universe_schedule(paths, missing[0], end, sessions, str(universe_path), mode="registry25")
    ledger = pool["ledger"].copy()
    ledger["target_date"] = pd.to_datetime(ledger.target_date).dt.strftime("%Y-%m-%d")
    ledger = ledger.loc[ledger.target_date.isin(missing)]
    if sorted(ledger.target_date) != missing:
        raise ValueError("MISSING_SIGNAL_PIT_POOL_DATES_INCOMPLETE")
    snapshots = set(ledger.snapshot_id.dropna())
    schedule = pool["schedule"].loc[pool["schedule"].snapshot_id.isin(snapshots)]
    members = pool["members"].loc[pool["members"].snapshot_id.isin(snapshots)]
    universe_refs = {key: write_frame(work / "universe" / (key + ".parquet"), frame)
        for key, frame in (("schedule", schedule), ("members", members), ("ledger", ledger))}
    save(work / "universe" / "lineage.json", {"sources": pool["lineage"], "gaps": pool["gaps"]})
    # execute=False is intentional: even a later helper change must not cause a
    # missing-day display refresh to train a model or build an annual vintage.
    models = build_models(paths, work, years=(2026,), execute=False)
    artifact = models.get("artifacts", {}).get("2026", {})
    if (models.get("status") != "READY" or models.get("model_fit_count") != 0
            or set(models.get("artifacts", {})) != {"2026"}
            or artifact.get("status") != "FROZEN_REFERENCE" or artifact.get("sha256") != MODEL_2026_SHA
            or artifact.get("model_role") != "FROZEN_FULL_PRE2026_FOR_2026_INFERENCE_ONLY"
            or models["feature_columns"] != historical["models"]["feature_columns"]):
        raise ValueError("MISSING_SIGNAL_REQUIRES_FROZEN_2026_REFERENCE_ONLY")
    verified(artifact)
    save(work / "models.json", models)
    all_members = members.dropna(subset=["ticker", "moomoo_symbol"]).drop_duplicates(
        ["security_id", "ticker", "moomoo_symbol"]).to_dict("records")
    features, lineage, gaps = build_price_features(paths, all_members, missing[0], end, sessions,
        acquired["acquisitions"], read(rehab_path), work)
    save(work / "price_inputs.json", {"lineage": lineage, "gaps": gaps})
    ranked, counts = ranked_predictions(features, schedule, members, ledger, models, models["feature_columns"])
    ranked["source"] = "MISSED_SESSION_DESCRIPTIVE_REPLAY"
    top = ranked.loc[ranked["rank"].le(40)].copy()
    outputs = {name: write_frame(work / (name + ".parquet"), frame)
        for name, frame in (("ranked", ranked), ("top40", top), ("coverage", counts))}
    manifest = {"status": "READY", "generated_at": datetime.now(timezone.utc).isoformat(), **contract,
        "schema": "A2_MISSED_SESSION_INFERENCE_V1", "outputs": outputs,
        "universe_outputs": universe_refs, "models": reference(work / "models.json"),
        "price_manifest": reference(work / "price_inputs.json"),
        "feature_manifest": reference(work / "prices" / "manifest.json"),
        "report_path": str(work / "manifest.json")}
    complete = set(top.target_date) == set(missing) and top.groupby("target_date").size().eq(40).all()
    if not complete:
        manifest.update(status="BLOCKED", error="MISSING_SIGNAL_TOP40_INPUTS_INCOMPLETE")
        save(work / "manifest.json", manifest)
        raise ValueError("MISSING_SIGNAL_TOP40_INPUTS_INCOMPLETE:" + str(work / "manifest.json"))
    top = _validate_rankings(top, models["artifacts"])
    for key in ("historical_manifest", "current_report", "universe_report", "rehab_receipt"):
        verified(contract[key])
    verified(artifact)
    save(work / "manifest.json", manifest)
    return (pd.concat([rankings, top], ignore_index=True).sort_values(["target_date", "rank"]).reset_index(drop=True),
            pd.concat([coverage, counts], ignore_index=True).sort_values("target_date").reset_index(drop=True),
            reference(work / "manifest.json"))


def reviewed_events(events, review_ref, input_refs):
    """Resolve exact factual false positives while retaining every audit row.

    The price reader verifies source facts, raw identity and rehab evidence.
    This second boundary binds its review to the exact detected event; neither
    the jump threshold nor prices, quantities, targets or returns are changed.
    """
    audit = events.copy()
    audit["resolution_status"] = "UNREVIEWED"
    resolved = set()
    if review_ref is None:
        return resolved, audit
    if not any(ref.get("path") == review_ref["path"] and ref.get("sha256") == review_ref["sha256"] for ref in input_refs):
        raise ValueError("EVENT_REVIEW_NOT_BOUND_TO_PRICE_INPUTS")
    review = read(verified(review_ref))
    if review.get("schema") != "A2_EXECUTION_EVENT_REVIEW_V1" or review.get("policy") != EVENT_REVIEW_POLICY:
        raise ValueError("EVENT_REVIEW_POLICY_MISMATCH")
    seen = set()
    for row in review["records"]:
        day = pd.Timestamp(row["event_date"])
        key = (row["ticker"], day)
        if key in seen:
            raise ValueError("DUPLICATE_EVENT_REVIEW")
        seen.add(key)
        if row.get("status") != "RESOLVED_NON_CORPORATE_ACTION":
            continue
        if row.get("audit_kind") != "LARGE_RAW_MOVE_NO_VENDOR_EVENT" or not row.get("code"):
            raise ValueError("EVENT_REVIEW_IDENTITY_INVALID")
        selected = (audit.ticker.eq(row["ticker"]) & pd.to_datetime(audit.event_date).eq(day)
            & audit.audit_kind.eq(row["audit_kind"]) & audit.code.eq(row["code"]))
        matched = audit.loc[selected]
        if (len(matched) != 1 or not np.isfinite(float(row["raw_jump"]))
                or not matched.raw_jump.eq(row["raw_jump"]).all()):
            raise ValueError("EVENT_REVIEW_DETECTED_FACT_MISMATCH")
        resolved.add(key)
        audit.loc[selected, "resolution_status"] = row["status"]
    return resolved, audit


def safe_execution_end(signals, prices, calendar, events, resolved_events=None):
    """Strict old calendar stopping policy; retain only the verified prefix."""
    target = {pd.Timestamp(day): set(part.ticker) for day, part in signals.loc[signals["rank"].le(20)].groupby("target_date")}
    first, end = min(target), max(target)
    known = prices.loc[np.isfinite(prices.open.to_numpy(float)) & prices.open.gt(0)]
    opens = set(zip(pd.to_datetime(known.trade_date), known.ticker))
    exceptions = set()
    if not events.empty:
        exceptions = set(zip(pd.to_datetime(events.loc[events.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT"), "event_date"]),
                             events.loc[events.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT"), "ticker"]))
        exceptions -= {(day, ticker) for ticker, day in (resolved_events or set())}
    held, cutoff = set(), first
    for day in calendar[(calendar > first) & (calendar <= end)]:
        signal = calendar[calendar.get_loc(day) - 1]
        if signal not in target:
            return cutoff, {"date": str(day.date()), "reason": "MISSING_STRATEGY_OBSERVATION"}
        missing = sorted(ticker for ticker in held | target[signal] if (day, ticker) not in opens)
        exceptional = sorted(ticker for ticker in held if (day, ticker) in exceptions)
        if missing or exceptional:
            return cutoff, {"date": str(day.date()), "reason": "MISSING_PRICE_EVENT" if missing else "HELD_CORPORATE_ACTION_EXCEPTION",
                            "missing_open_tickers": missing, "corporate_action_tickers": exceptional}
        held, cutoff = target[signal], day
    return cutoff, None


def normalize_ledger(result, rankings, calendar):
    """Expose the existing engine's realized book in the original DEMO schema."""
    if result.missing_price_events:
        raise ValueError("UNEXPECTED_MISSING_PRICE_EVENT_AFTER_PREFLIGHT")
    daily, positions, trades = result.daily.copy(), result.positions.copy(), result.trades.copy()
    target_rows = rankings.loc[rankings["rank"].le(20)]
    targets = {pd.Timestamp(day): dict(zip(part.ticker, part.security_id)) for day, part in target_rows.groupby("target_date")}
    cash, prior_nav, prior_ids, rows, books = 1.0, 1.0, {}, [], []
    for index, entry in daily.sort_values("date").iterrows():
        day = pd.Timestamp(entry["date"])
        signal = calendar[calendar.get_loc(day) - 1] if index else None
        identities = targets.get(signal, {})
        book = positions.loc[positions.date.eq(day)].copy() if not positions.empty else pd.DataFrame()
        orders = trades.loc[trades.date.eq(day)] if not trades.empty else pd.DataFrame()
        cost = float(entry.transaction_cost)
        pretrade = float(entry.nav) + cost
        before = cash
        buys = float(orders.loc[orders.side.eq("BUY"), "notional"].sum()) if not orders.empty else 0.0
        sells = float(orders.loc[orders.side.eq("SELL"), "notional"].sum()) if not orders.empty else 0.0
        cash += sells - buys - cost
        if cash >= -1e-12:
            cash = max(0.0, cash)
        value = float((book.shares_after * book.current_price).sum()) if not book.empty else 0.0
        prevalues = dict(zip(book.ticker, book.shares_before * book.current_price)) if not book.empty else {}
        wanted = {ticker: pretrade / 20 for ticker in identities}
        requested = sum(max(0.0, amount - prevalues.get(ticker, 0.0)) for ticker, amount in wanted.items())
        scale = min(1.0, buys / requested) if requested > 1e-14 else 1.0
        turnover = float(entry.turnover)
        residuals = {"NAV_ACCOUNTING_IDENTITY_ERROR": float(entry.nav) - cash - value,
            "CASH_IDENTITY_ERROR": cash - before - sells + buys + cost,
            "POSITION_VALUE_IDENTITY_ERROR": 0.0,
            "TURNOVER_IDENTITY_ERROR": turnover - 0.5 * (buys + sells) / pretrade,
            "TRANSACTION_COST_IDENTITY_ERROR": cost - 0.0005 * (buys + sells)}
        if cash < -1e-10 or any(abs(value0) > 1e-9 for value0 in residuals.values()):
            raise ValueError("UPDATED_ACCOUNTING_IDENTITY_FAILURE")
        gross = pretrade / prior_nav - 1.0
        if abs(float(entry.daily_return) - (float(entry.nav) / prior_nav - 1)) > 1e-12:
            raise ValueError("UPDATED_RETURN_NAV_IDENTITY_FAILURE")
        rows.append({"execution_date": day, "signal_date_used": signal, "model": "A2_HGB",
            "reconstruction_mode": "POSITION_LEDGER", "cash_before": before, "cash_after": max(0.0, cash),
            "pretrade_nav": pretrade, "reconstructed_nav": float(entry.nav), "reconstructed_gross_return": gross,
            "reconstructed_daily_return": float(entry.daily_return), "target_turnover":
                0.5 * sum(abs((0.05 if ticker in identities else 0) - prevalues.get(ticker, 0) / pretrade)
                          for ticker in set(identities) | set(prevalues)),
            "reconstructed_turnover": turnover, "reconstructed_transaction_cost": cost, "position_value": value,
            "actual_risky_name_count": int(entry.holding_count), "stale_mark_count": int(entry.stale_mark_count),
            "skipped_buy_count": int(entry.skipped_buy_count), "blocked_sell_or_rebalance_count": int(entry.blocked_sell_count),
            "buy_cash_scale": scale, **residuals})
        if not book.empty:
            for pos in book.itertuples():
                if pos.shares_before > 1e-14 and pos.ticker in identities and prior_ids.get(pos.ticker) != identities[pos.ticker]:
                    raise ValueError("HELD_SECURITY_IDENTITY_CHANGED:" + pos.ticker)
            book["security_id"] = [identities.get(ticker, prior_ids.get(ticker)) for ticker in book.ticker]
            if book.security_id.isna().any():
                raise ValueError("EXECUTED_HOLDING_IDENTITY_MISSING")
            book["previous_date"] = daily.iloc[index - 1]["date"]
            book["model"] = "A2_HGB"; book["portfolio"] = "TOP20_EQUAL_WEIGHT_LONG_ONLY"
            book["position_weight"] = (book.shares_before * book.previous_price / prior_nav).fillna(0.0)
            book["posttrade_weight"] = book.shares_after * book.current_price / float(entry.nav)
            book["target_weight"] = book.ticker.map(lambda ticker: 0.05 if ticker in identities else 0.0)
            books.append(book)
            prior_ids = dict(zip(book.loc[book.shares_after.gt(1e-14), "ticker"], book.loc[book.shares_after.gt(1e-14), "security_id"]))
        prior_nav = float(entry.nav)
    if not books:
        empty = ["date", "previous_date", "ticker", "security_id", "shares_before", "shares_after", "model", "portfolio",
                 "previous_price", "current_price", "mark_source_date", "stale_mark", "market_pnl", "transaction_cost",
                 "position_weight", "posttrade_weight", "target_weight"]
        positions = pd.DataFrame(columns=empty)
    else:
        positions = pd.concat(books, ignore_index=True)
    return pd.DataFrame(rows), positions, trades


def decision_calendar(rankings, coverage, calendar, cutoff, blocked):
    counts = coverage.set_index("target_date")
    rows = []
    for day in sorted(rankings.target_date.unique()):
        signal = pd.Timestamp(day); offset = calendar.get_loc(signal) + 1
        scheduled = calendar[offset] if offset < len(calendar) else None
        executed = scheduled is not None and scheduled <= cutoff
        status = "EXECUTED" if executed else "BLOCKED_PRICE_INPUT" if blocked and scheduled is not None and scheduled <= pd.Timestamp(rankings.target_date.max()) else "PENDING_NEXT_OPEN"
        row = {"signal_date": day, "scheduled_execution_date": None if scheduled is None else str(scheduled.date()),
            "execution_date": str(scheduled.date()) if executed else None, "execution_status": status,
            "performance_cutoff_date": str((scheduled if executed else min(cutoff, signal)).date()),
            "portfolio_snapshot_date": str(scheduled.date()) if executed else None}
        record = counts.loc[day]
        for key in ("quarter", "effective_date", "institution_count", "universe_member_count", "mapped_count", "eligible_count", "excluded_count"):
            row[key] = record.get(key)
        row["coverage_status"] = record.get("status")
        rows.append(row)
    return pd.DataFrame(rows)


def refresh_demo_performance(paths, historical_manifest_path, current_report_path, output_dir=None, progress=None,
                             *, current_execution_manifest_path=None, prior_verified_performance_manifest_path=None,
                             close_vintage_review_path=None):
    from scripts.common.daily_support import save, single_update
    from scripts.research.a2.inference.historical_top40 import load_sessions
    from scripts.research.a2.evaluation.demo_performance_prices import load_execution_prices
    progress = progress or (lambda message: None)
    root = paths.daily_root / "A2_updated_research"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    work = Path(output_dir).resolve() if output_dir is not None else root / "runs" / run_id
    if work.parent.resolve() != (root / "runs").resolve():
        raise ValueError("UPDATED_RESEARCH_REQUIRES_CANONICAL_RUN_DIRECTORY")
    with single_update(root):
        work.mkdir(parents=True, exist_ok=False)
        report = {"schema_version": 1, "source_id": SOURCE_ID, "run_id": work.name, "status": "RUNNING",
            "generated_at": datetime.now(timezone.utc).isoformat(), "report_path": str(work / "manifest.json"),
            "ranking_manifest": reference(historical_manifest_path), "evaluation": EVALUATION, "limitations": LIMITATIONS}
        try:
            historical_manifest_path, pointer_ref = canonical_manifest(historical_manifest_path)
            current_report_path, current_pointer_ref = canonical_manifest(current_report_path)
            report["ranking_manifest"] = reference(historical_manifest_path)
            engine, authority = _authority(paths)
            rankings, coverage, refs, ready_reports = load_rankings(paths, historical_manifest_path, current_report_path)
            sessions, calendar_ref = load_sessions(paths)
            calendar = pd.DatetimeIndex(pd.to_datetime(sessions))
            first, end = pd.Timestamp(rankings.target_date.min()), pd.Timestamp(rankings.target_date.max())
            expected = calendar[(calendar >= first) & (calendar <= end)]
            if end > pd.Timestamp(calendar_ref["current"]["target_date"]):
                raise ValueError("UPDATED_RANKINGS_SESSION_COVERAGE_FAILURE")
            prior, prior_binding = None, None
            if prior_verified_performance_manifest_path is not None:
                prior = _prior_verified_performance(paths, prior_verified_performance_manifest_path,
                    historical_manifest_path, read(historical_manifest_path)["models"]["artifacts"],
                    authority, calendar_ref["lineage"], str(end.date()))
                absent = set(expected.strftime("%Y-%m-%d")) - set(rankings.target_date)
                retained = prior["frames"]["rankings"]
                reused = sorted(absent & set(retained.loc[retained.target_date.le(prior["cutoff"]), "target_date"]))
                rankings = _validate_rankings(pd.concat([rankings, retained.loc[retained.target_date.isin(reused)]], ignore_index=True),
                    read(historical_manifest_path)["models"]["artifacts"])
                coverage = pd.concat([coverage, prior["frames"]["coverage"].loc[
                    prior["frames"]["coverage"].target_date.isin(reused)]], ignore_index=True).sort_values("target_date").reset_index(drop=True)
                _assert_prior_prefix("rankings", rankings, prior, "target_date", ["target_date", "rank"])
                _assert_prior_prefix("coverage", coverage, prior, "target_date", ["target_date"])
                refs.extend(prior["refs"])
                prior_binding = {"manifest": prior["ref"], "evaluation_contract": prior["manifest"]["evaluation_contract"],
                    "price_inputs": prior["manifest"]["price_inputs"], "price_paths": prior["manifest"]["outputs"]["price_paths"],
                    "performance_end_date": prior["cutoff"], "reused_signal_dates": reused,
                    "consumer_fields": ["open", "close"], "model_feature_eligibility_granted": False,
                    "prefix_check": "ALL_RECORDED_FIELDS_REQUIRED_BEFORE_PUBLICATION"}
            rankings, coverage, inference_ref = fill_missing_signals(paths, historical_manifest_path,
                current_report_path, rankings, coverage, list(calendar.strftime("%Y-%m-%d")), work, progress)
            if inference_ref:
                refs.append(inference_ref)
            if list(expected.strftime("%Y-%m-%d")) != sorted(rankings.target_date.unique()):
                raise ValueError("UPDATED_RANKINGS_SESSION_COVERAGE_FAILURE")
            progress("按原 Top20 等权、次日开盘和成本规则更新展示绩效。")
            selected = sorted(set(rankings.loc[rankings["rank"].le(20), "ticker"]))
            price_input = load_execution_prices(paths, historical_manifest_path, tickers=selected,
                current_report_path=current_report_path, start=str(first.date()), end=str(end.date()),
                **({"inference_manifest_path": inference_ref["path"]} if inference_ref else {}),
                **({"current_execution_manifest_path": current_execution_manifest_path}
                   if current_execution_manifest_path is not None else {}))
            prices = price_input["prices"].copy(); prices["trade_date"] = pd.to_datetime(prices.trade_date)
            if prices.duplicated(["trade_date", "ticker"]).any():
                raise ValueError("DUPLICATE_EXECUTION_PRICE")
            if prior is not None:
                review = (reference(close_vintage_review_path) if close_vintage_review_path is not None
                          else prior["contract"].get("retained_close_vintage_review"))
                prices = _retain_prior_execution_marks(prices, prior, review)
                if review is not None:
                    price_input["retained_close_vintage_review"] = review
                    price_input.setdefault("refs", []).append(review)
                price_input["prior_verified_prefix"] = prior_binding
                price_input["refs"] = [*price_input.get("refs", []), *prior["contract"]["price_refs"],
                    prior["ref"], prior["manifest"]["evaluation_contract"], prior["manifest"]["price_inputs"],
                    prior["manifest"]["outputs"]["price_paths"]]
            resolved, event_audit = reviewed_events(price_input["events"], price_input.get("event_review"), price_input.get("refs", []))
            cutoff, blocked = safe_execution_end(rankings, prices, calendar, price_input["events"], resolved)
            if prior is not None and cutoff < pd.Timestamp(prior["cutoff"]):
                raise ValueError("PRIOR_PERFORMANCE_VERIFIED_CUTOFF_REGRESSED")
            # Persist all rules and acquired evidence before computing returns.
            # This is a descriptive extension of an existing engine, not a new
            # model/execution selection based on the resulting performance.
            rankings.to_parquet(work / "rankings.parquet", index=False)
            save(work / "price_inputs.json", {key: value for key, value in price_input.items() if key not in {"prices", "events"}})
            input_refs = authority + refs + price_input.get("refs", [])
            if prior is not None:
                by_path = {}
                for item in input_refs:
                    key = str(Path(item["path"]).resolve())
                    if key in by_path and by_path[key]["sha256"] != item["sha256"]:
                        raise ValueError("PRIOR_PERFORMANCE_CONFLICTING_SOURCE_HASH")
                    by_path[key] = item
                input_refs = list(by_path.values())
            for item in input_refs:
                verified(item)
            contract = {"schema": "A2_UPDATED_DESCRIPTIVE_EVALUATION_CONTRACT_V1",
                "source_id": SOURCE_ID, "created_at": datetime.now(timezone.utc).isoformat(),
                "authorization": "USER_REQUESTED_EXISTING_RULE_DESCRIPTIVE_EXPOSED_PERIOD_REPLAY",
                "evaluation": EVALUATION, "limitations": LIMITATIONS,
                "authorities": authority, "ranking_manifest": report["ranking_manifest"],
                "rankings": reference(work / "rankings.parquet"), "current_report": reference(current_report_path),
                "input_refs": refs, "price_inputs": reference(work / "price_inputs.json"),
                "missing_signal_inference": inference_ref,
                "price_refs": price_input.get("refs", []), "calendar_lineage": calendar_ref["lineage"],
                "event_review": price_input.get("event_review"), "event_review_policy": EVENT_REVIEW_POLICY,
                "resolved_non_corporate_action_events": [{"ticker": ticker, "event_date": str(day.date())}
                    for ticker, day in sorted(resolved)],
                "execution_price_extension": {"gate": "FIVE_EXACT_OHLC_AND_ALL_OVERLAP_EXACT_OPEN_CLOSE_V1",
                    "consumer_fields": ["open", "close"], "model_feature_eligibility_granted": False,
                    "qualification_is_fixed_before_performance": True},
                "ranking_start_date": str(first.date()), "ranking_end_date": str(end.date()),
                "safe_execution_end_date": str(cutoff.date()), "blocking_input": blocked,
                "model_fit_count": 0, "parameter_search_count": 0}
            if prior_binding is not None:
                contract["prior_verified_performance"] = prior_binding
                if price_input.get("retained_close_vintage_review"):
                    contract["retained_close_vintage_review"] = price_input["retained_close_vintage_review"]
            save(work / "evaluation_contract.json", contract)
            report["evaluation_contract"] = reference(work / "evaluation_contract.json")
            engine.EFFECTIVE_START = first
            if engine.TOP_N != 20 or engine.COST_BPS != 10:
                raise ValueError("FROZEN_ENGINE_PORTFOLIO_PARAMETERS_CHANGED")
            targets = engine.build_target_map(rankings.rename(columns={"target_date": "signal_date"}), "rank")
            result = engine.reconstruct_open_ended("A2_HGB", targets, prices, calendar, cutoff)
            daily, positions, trades = normalize_ledger(result, rankings, calendar)
            decisions = decision_calendar(rankings, coverage, calendar, cutoff, blocked)
            price_paths = prices[['trade_date', 'ticker', 'open', 'close']].rename(columns={'trade_date': 'date'}).copy()
            price_paths['adjustment'] = 'PIT_FORWARD_REHAB_INDEX'
            price_paths['source'] = 'VERIFIED_RAW_PLUS_PIT_REHAB'
            if prior is not None:
                for name, frame, column, keys in (
                    ("rankings", rankings, "target_date", ["target_date", "rank"]),
                    ("coverage", coverage, "target_date", ["target_date"]),
                    ("portfolio_daily", daily, "execution_date", ["execution_date"]),
                    ("positions", positions, "date", ["date", "ticker"]),
                    ("trades", trades, "date", ["date", "ticker", "side"]),
                    ("price_paths", price_paths, "date", ["date", "ticker"])):
                    _assert_prior_prefix(name, frame, prior, column, keys)
            outputs = {}
            for name, frame in {"rankings": rankings, "coverage": coverage, "portfolio_daily": daily,
                                "positions": positions, "trades": trades, "decision_calendar": decisions,
                                "corporate_action_events": event_audit, "price_paths": price_paths}.items():
                path = work / (name + ".parquet")
                if name != "rankings":
                    frame.to_parquet(path, index=False)
                outputs[name] = {**reference(path), "rows": len(frame)}
            for item in input_refs + [pointer_ref, current_pointer_ref, report["evaluation_contract"], contract["rankings"], contract["price_inputs"]]:
                verified(item)
            report.update(status="PARTIAL" if blocked or coverage.status.ne("READY").any() else "READY",
                ranking_end_date=str(end.date()), performance_end_date=str(cutoff.date()), ranking_start_date=str(first.date()),
                performance_start_date=str(first.date()), ranking_days=len(expected), performance_points=len(daily),
                return_observations=max(0, len(daily) - 1), outputs=outputs, blocking_input=blocked,
                authority_refs=authority, input_refs=refs, recommendation_reports=ready_reports,
                price_inputs=reference(work / "price_inputs.json"), calendar_lineage=calendar_ref["lineage"],
                missing_signal_inference=inference_ref,
                producer_sha256=digest(__file__), model_fit_count=0, parameter_search_count=0,
                ranking_status="PARTIAL" if coverage.status.ne("READY").any() else "READY",
                performance_status="BLOCKED_PRICE_INPUT" if blocked else "CURRENT_OPEN_MARKS",
                event_review=price_input.get("event_review"), resolved_non_corporate_action_count=len(resolved),
                accounting_max_absolute_residual=float(daily[[key for key in daily if key.endswith("IDENTITY_ERROR")]].abs().to_numpy().max()))
            if prior_binding is not None:
                report["prior_verified_performance"] = {**prior_binding, "prefix_verification": "PASSED"}
            save(work / "manifest.json", report)
            if len(daily) > 1:
                save(root / "latest.json", report)
            return report
        except Exception as exc:
            report.update(status="BLOCKED", error=str(exc))
            save(work / "manifest.json", report)
            return report


def main():
    from scripts.common.storage_paths import resolve
    from scripts.common.daily_support import single_update
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-manifest", type=Path, required=True)
    parser.add_argument("--current-report", type=Path, required=True)
    args = parser.parse_args()
    paths = resolve()
    # CLI owns the daily lock. In-process callers already hold it and call the
    # function directly, which only locks its separate updated-display root.
    with single_update(paths.daily_root / "A2_today_recommendation"):
        result = refresh_demo_performance(paths, args.historical_manifest, args.current_report, progress=print)
    print(json.dumps({key: result.get(key) for key in ("status", "run_id", "report_path", "ranking_end_date", "performance_end_date", "error")}, ensure_ascii=False))
    return int(result["status"] == "BLOCKED")


if __name__ == "__main__":
    raise SystemExit(main())
