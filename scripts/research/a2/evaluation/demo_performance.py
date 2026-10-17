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
PERFORMANCE_OUTPUTS = ("portfolio_daily", "positions", "trades", "price_paths", "corporate_action_events")
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


def _prior_verified_performance(paths, path, historical_path, models, authority, calendar_lineage, end, *, _origin_seen=(), _allow_retained_partial=True,
                                _retained_seen=(), _qualified_origin=False, _native_phase_anchor=False):
    """Bind one explicitly requested completed replay, never choose a pointer."""
    path = Path(path).resolve()
    runs = (paths.daily_root / "A2_updated_research/runs").resolve()
    if path.name != "manifest.json" or path.parent.parent != runs:
        raise ValueError("PRIOR_PERFORMANCE_REQUIRES_IMMUTABLE_RUN_MANIFEST")
    if str(path) in _origin_seen or len(_origin_seen) >= 2:
        raise ValueError("PRIOR_PERFORMANCE_ORIGIN_CYCLE")
    if str(path) in _retained_seen or len(_retained_seen) >= 8:
        raise ValueError("PRIOR_RETAINED_OPEN_ORIGIN_CYCLE_OR_DEPTH")
    manifest_ref = reference(path)
    prior = read(verified(manifest_ref))
    if _native_phase_anchor and not isinstance(prior.get("execution_open"), dict):
        raise ValueError("PRIOR_RETAINED_OPEN_NATIVE_ANCHOR_REQUIRED")
    historical_ref = reference(historical_path)
    origin, origin_prior = prior.get("performance_origin"), None
    if origin is not None:
        if (set(origin) != {"schema", "mode", "manifest"}
                or origin.get("schema") != "A2_IMMUTABLE_PERFORMANCE_ORIGIN_V1"
                or origin.get("mode") != "REUSE_VERIFIED_EXECUTED_LEDGER_SAME_END"):
            raise ValueError("PRIOR_PERFORMANCE_ORIGIN_CONTRACT_INVALID")
        origin_path = Path(origin["manifest"]["path"]).resolve()
        if origin_path.name != "manifest.json" or origin_path.parent.parent != runs:
            raise ValueError("PRIOR_PERFORMANCE_ORIGIN_OUTSIDE_OWNER")
        verified(origin["manifest"])
        origin_prior = _prior_verified_performance(paths, origin_path, historical_path, models,
            authority, calendar_lineage, end, _origin_seen=(*_origin_seen, str(path)), _allow_retained_partial=_allow_retained_partial,
            _retained_seen=_retained_seen, _native_phase_anchor=_native_phase_anchor)
        original = origin_prior["manifest"]
        if (original.get("performance_origin") is not None
                or original["performance_end_date"] != prior.get("performance_end_date")
                or original["ranking_end_date"] > prior.get("ranking_end_date", "")
                or prior.get("execution_open") != original.get("execution_open")
                or prior.get("price_inputs") != original["price_inputs"]
                or any(prior["outputs"].get(name) != original["outputs"].get(name) for name in PERFORMANCE_OUTPUTS)):
            raise ValueError("PRIOR_PERFORMANCE_ORIGIN_OUTPUTS_CHANGED")
    cutoff = prior.get("performance_end_date", "")
    prior_open = prior.get("execution_open")
    clock_valid = bool(cutoff and prior.get("ranking_start_date", "") <= cutoff
        and prior.get("ranking_end_date", "") <= end
        and (cutoff <= prior.get("ranking_end_date", "") or
             prior_open and cutoff == prior_open.get("execution_end_date")
             and prior.get("ranking_end_date") == prior_open.get("signal_end_date")))
    if (prior.get("schema_version") != 1 or prior.get("source_id") != SOURCE_ID
            or prior.get("status") not in {"READY", "PARTIAL"}
            or Path(prior.get("report_path", "")).resolve() != path
            or prior.get("ranking_manifest") != historical_ref
            or prior.get("evaluation") != EVALUATION
            or prior.get("model_fit_count") != 0 or prior.get("parameter_search_count") != 0
            or not clock_valid
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
    if contract.get("performance_origin") != origin:
        raise ValueError("PRIOR_PERFORMANCE_ORIGIN_BINDING_MISMATCH")
    if contract.get("execution_open") != prior_open:
        raise ValueError("PRIOR_PERFORMANCE_OPEN_PHASE_CONTRACT_MISMATCH")
    if prior_open:
        from scripts.research.a2.evaluation.demo_performance_prices import execution_open_clock
        from scripts.research.a2.inference.historical_top40 import load_sessions
        sessions, _ = load_sessions(paths)
        execution_open_clock(prior_open["signal_end_date"], prior_open["execution_end_date"],
            sessions, prior_open["as_of_utc"])
        phase_source = read(verified(prior_open["manifest"]))
        if (phase_source.get("schema") != "A2_EXECUTION_OPEN_INPUTS_V1"
                or phase_source.get("signal_end_date") != prior_open["signal_end_date"]
                or phase_source.get("execution_end_date") != prior_open["execution_end_date"]
                or phase_source.get("as_of_utc") != prior_open["as_of_utc"]
                or phase_source.get("current_report") != (origin_prior["contract"]["current_report"] if origin_prior else contract["current_report"])):
            raise ValueError("PRIOR_PERFORMANCE_OPEN_SOURCE_BINDING_MISMATCH")
        if (prior_open.get("consumer_fields") != ["open"]
                or prior_open.get("terminal_close_available") is not False
                or prior_open.get("model_feature_eligibility_granted") is not False):
            raise ValueError("PRIOR_PERFORMANCE_OPEN_PHASE_CONTRACT_MISMATCH")
    old_source = read(verified(contract["current_report"]))
    _daily_rows(old_source)
    if old_source["data_date"] != prior["ranking_end_date"]:
        raise ValueError("PRIOR_PERFORMANCE_SOURCE_DATE_MISMATCH")
    price_inputs = read(verified(prior["price_inputs"]))
    if (price_inputs.get("price_basis") != EVALUATION["price_basis"]
            or price_inputs.get("vintage_semantics") != "LATER_VENDOR_REHAB_SNAPSHOT_NOT_HISTORICAL_PUBLICATION_VINTAGE"
            or price_inputs.get("start_date") != prior["ranking_start_date"]
            or price_inputs.get("end_date") != (origin_prior["manifest"]["ranking_end_date"] if origin_prior else prior["ranking_end_date"])
            or price_inputs.get("execution_open") != prior_open
            or not contract.get("price_refs")
            or price_inputs.get("refs") != contract.get("price_refs")):
        raise ValueError("PRIOR_PERFORMANCE_PRICE_PROOF_MISMATCH")
    refs = [*(origin_prior["refs"] if origin_prior else []), manifest_ref, contract_ref, prior["price_inputs"], contract["current_report"],
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
    terminal = marks.date.eq(pd.Timestamp(prior_open["execution_end_date"])) if prior_open else pd.Series(False, index=marks.index)
    closed = marks.loc[~terminal]
    retained_phase = None
    if (not {"date", "ticker", "open", "close", "adjustment", "source"} <= set(marks)
            or marks.duplicated(["date", "ticker"]).any()
            or not marks.adjustment.eq(EVALUATION["price_basis"]).all()
            or not marks.source.eq("VERIFIED_RAW_PLUS_PIT_REHAB").all()
            or not np.isfinite(marks.open.to_numpy(float)).all() or not marks.open.gt(0).all()
            or prior_open and (not marks.loc[terminal, "close"].isna().all()
                or set(marks.loc[terminal, "ticker"]) != set(prior_open["qualified_tickers"]))):
        raise ValueError("PRIOR_PERFORMANCE_EXECUTION_MARKS_INVALID")
    if not np.isfinite(closed[["open", "close"]].to_numpy(float)).all() or not closed[["open", "close"]].gt(0).all().all():
        if (prior_open is not None or not _allow_retained_partial
                or not closed.close.isna().any()
                or not np.isfinite(closed.loc[closed.close.notna(), "close"]).all()
                or not closed.loc[closed.close.notna(), "close"].gt(0).all()):
            raise ValueError("PRIOR_PERFORMANCE_EXECUTION_MARKS_INVALID")
        retained_phase = _verified_partial_open_phase(paths, prior, contract, price_inputs, frames,
            historical_path, models, authority, calendar_lineage, end,
            _retained_seen=(*_retained_seen, str(path)))
    audit = contract.get("retained_qualified_execution_opens")
    if audit is not None and retained_phase is None and not _native_phase_anchor:
        if origin_prior is not None:
            if audit != origin_prior["contract"].get("retained_qualified_execution_opens"):
                raise ValueError("PRIOR_RETAINED_OPEN_SAME_END_AUDIT_CHANGED")
            retained_phase = origin_prior.get("retained_execution_open")
        else:
            retained_phase = _verified_partial_open_phase(paths, prior, contract, price_inputs, frames,
                historical_path, models, authority, calendar_lineage, end,
                _retained_seen=(*_retained_seen, str(path)))
    declared = contract.get("retained_qualified_execution_open_origins")
    if (declared != price_inputs.get("retained_qualified_execution_open_origins")
            or declared is not None and (not isinstance(declared, list) or not declared or len(declared) > 366)):
        raise ValueError("PRIOR_RETAINED_OPEN_ORIGINS_NOT_BOUND")
    origins, origin_keys = [], set()
    for item in declared or []:
        key = str(Path(item["path"]).resolve())
        if key in origin_keys or item not in contract["price_refs"]:
            raise ValueError("PRIOR_RETAINED_OPEN_ORIGINS_NOT_BOUND")
        origin_keys.add(key)
        verified(item)
        if not _qualified_origin and not _native_phase_anchor:
            origin_prior_item = _prior_verified_performance(paths, verified(item), historical_path, models,
                authority, calendar_lineage, end, _allow_retained_partial=False,
                _retained_seen=(*_retained_seen, str(path)), _qualified_origin=True)
            origins.append(_compact_qualified_open_origin(origin_prior_item))
    if not _qualified_origin and not _native_phase_anchor and origin is None:
        inherited = _required_inherited_open_origins(prior)
        if any(item not in (declared or []) for item in inherited):
            raise ValueError("PRIOR_RETAINED_OPEN_ORIGIN_OMITTED")
    if _qualified_origin:
        phase_rows = (marks.loc[marks.date.eq(pd.Timestamp(retained_phase["execution_end_date"]))]
                      if retained_phase else marks.iloc[:0])
        if (not isinstance(audit, dict) or not audit.get("records") or phase_rows.empty
                or not np.isfinite(phase_rows.close).all() or not phase_rows.close.gt(0).all()):
            raise ValueError("PRIOR_RETAINED_OPEN_ORIGIN_NOT_FULLY_MATURE")
    return {"manifest": prior, "ref": manifest_ref, "contract": contract, "frames": frames,
            "cutoff": cutoff, "refs": [{"path": path, "sha256": sha} for path, sha in sorted(checked.items())],
            "verified_execution_price_lineage": "ALL_IMMUTABLE_INPUT_REFS_VERIFIED",
            "retained_execution_open": retained_phase, "qualified_open_origins": origins,
            "retained_open_origin": (_compact_qualified_open_origin(origin_prior)
                if origin_prior is not None and retained_phase is not None else None)}


def _verified_partial_open_phase(paths, manifest, contract, price_input, frames,
                                  historical_path, models, authority, calendar_lineage, end, *, _retained_seen=()):
    """Verify one accepted open transition; maturity preserves its qualification."""
    audit = contract.get("retained_qualified_execution_opens")
    binding = manifest.get("prior_verified_performance")
    if (not isinstance(audit, dict) or not isinstance(binding, dict)
            or audit != price_input.get("retained_qualified_execution_opens")
            or audit.get("schema") != "A2_RETAINED_QUALIFIED_EXECUTION_OPEN_V1"
            or audit.get("policy") != "ORIGINAL_ASOF_OPEN_EXACT_MATURE_UNKNOWN_CLOSE_ONLY"
            or audit.get("prior_ledger_changed") is not False
            or audit.get("model_feature_eligibility_granted") is not False
            or audit.get("prior_manifest") != binding.get("manifest")
            or audit.get("current_source") != contract["current_report"]
            or binding.get("prefix_verification") != "PASSED"):
        raise ValueError("PRIOR_PARTIAL_OPEN_LINEAGE_NOT_BOUND")
    # A native anchor grants only its own terminal open, not inherited closed
    # phases. Legacy partial ancestry retains the strict bounded audit path.
    ancestor_path = verified(binding["manifest"])
    native_anchor = isinstance(read(ancestor_path).get("execution_open"), dict)
    ancestor = _prior_verified_performance(paths, ancestor_path, historical_path,
        models, authority, calendar_lineage, end, _allow_retained_partial=not native_anchor,
        _retained_seen=_retained_seen, _native_phase_anchor=native_anchor)
    phase = ancestor["manifest"].get("execution_open") or ancestor.get("retained_execution_open")
    if (phase is None or manifest["performance_end_date"] < ancestor["cutoff"]
            or manifest["ranking_end_date"] < ancestor["manifest"]["ranking_end_date"]
            or audit.get("prior_price_paths") != ancestor["manifest"]["outputs"]["price_paths"]
            or audit.get("original_phase") != phase["manifest"]
            or any(binding.get(name) != ancestor["manifest"].get(name) for name in
                   ("evaluation_contract", "price_inputs"))
            or binding.get("price_paths") != ancestor["manifest"]["outputs"]["price_paths"]
            or binding.get("performance_end_date") != ancestor["cutoff"]):
        raise ValueError("PRIOR_PARTIAL_OPEN_ANCESTOR_MISMATCH")
    old_phase = read(verified(phase["manifest"]))
    if (audit.get("original_acquisition") != old_phase.get("acquisition_manifest")
            or audit.get("original_rehab") != old_phase.get("rehab_receipt")
            or not isinstance(audit.get("current_price_input_refs"), list)
            or not audit["current_price_input_refs"]
            or any(ref not in contract["price_refs"] for ref in audit["current_price_input_refs"])):
        raise ValueError("PRIOR_PARTIAL_OPEN_PRICE_PROOF_MISMATCH")
    for name, column, keys in (
        ("rankings", "target_date", ["target_date", "rank"]),
        ("coverage", "target_date", ["target_date"]),
        ("portfolio_daily", "execution_date", ["execution_date"]),
        ("positions", "date", ["date", "ticker"]),
        ("trades", "date", ["date", "ticker", "side"]),
        ("price_paths", "date", ["date", "ticker"])):
        _assert_prior_prefix(name, frames[name], ancestor, column, keys)
    marks = frames["price_paths"]
    unknown_mask = marks.close.isna()
    if manifest.get("execution_open"):
        unknown_mask &= ~marks.date.eq(pd.Timestamp(manifest["execution_open"]["execution_end_date"]))
    unknown = marks.loc[unknown_mask, ["date", "ticker"]]
    original = ancestor["frames"]["price_paths"]
    permitted = original.loc[original.date.eq(pd.Timestamp(phase["execution_end_date"]))
                             & original.close.isna(), ["date", "ticker"]]
    if (not unknown.empty and (manifest["performance_end_date"] != ancestor["cutoff"]
            or not set(unknown.itertuples(index=False, name=None))
            <= set(permitted.itertuples(index=False, name=None)))):
        raise ValueError("PRIOR_PARTIAL_OPEN_UNKNOWN_CLOSE_SCOPE_INVALID")
    # Reuse the original qualification owner rather than trust audit assertions.
    # Only temporary verification inputs regain the recorded later vendor opens.
    probe = marks[["date", "ticker", "open", "close"]].rename(columns={"date": "trade_date"}).copy()
    seen = set()
    for row in audit.get("records", []):
        key = (pd.Timestamp(row["date"]), row["ticker"])
        selected = probe.trade_date.eq(key[0]) & probe.ticker.eq(key[1])
        if (key in seen or selected.sum() != 1
                or not probe.loc[selected, "open"].eq(row["recorded_open"]).all()):
            raise ValueError("PRIOR_PARTIAL_OPEN_AUDIT_RECORD_INVALID")
        seen.add(key)
        probe.loc[selected, "open"] = row["completed_vendor_open"]
    checked, regenerated = _retain_qualified_execution_opens(probe, ancestor,
        {"end_date": manifest["ranking_end_date"], "refs": audit["current_price_input_refs"]},
        verified(contract["current_report"]))
    if regenerated != audit:
        raise ValueError("PRIOR_PARTIAL_OPEN_AUDIT_NOT_REPRODUCIBLE")
    pd.testing.assert_frame_equal(checked.reset_index(drop=True),
        marks[["date", "ticker", "open", "close"]].rename(columns={"date": "trade_date"}).reset_index(drop=True),
        check_exact=True, check_dtype=False)
    return phase


def _pending_signal_revision(prior, current_report_path, repair_path, calendar):
    """Bind a same-day input repair to one recorded, unexecuted next-open signal."""
    from scripts.research.a2.portfolio.selected_hgb import _validate_input_repair
    old_ref = prior["contract"]["current_report"]
    old_report, new_report = read(verified(old_ref)), read(current_report_path)
    day = prior["cutoff"]
    if (new_report.get("data_date") != day or old_report.get("data_date") != day
            or new_report.get("status") != "READY"
            or str(prior["frames"]["rankings"].target_date.max()) != day):
        raise ValueError("PENDING_SIGNAL_REPAIR_LATEST_SIGNAL_REQUIRED")
    new_ref = reference(current_report_path)
    repair_ref = reference(repair_path)
    def snapshot(report, report_ref):
        return {"signal_date": day, "source_refs": {
            "current/report.json": report_ref,
            "current/selected_hgb_features.parquet": report["selected_hgb_features"]}}
    _validate_input_repair(snapshot(new_report, new_ref), snapshot(old_report, old_ref), repair_ref)
    decisions = pd.read_parquet(verified(prior["manifest"]["outputs"]["decision_calendar"]))
    same = decisions.loc[decisions.signal_date.eq(day)]
    offset = calendar.get_loc(pd.Timestamp(day)) + 1
    if (len(same) != 1 or offset >= len(calendar)
            or same.iloc[0].execution_status != "PENDING_NEXT_OPEN"
            or pd.notna(same.iloc[0].execution_date)
            or pd.notna(same.iloc[0].portfolio_snapshot_date)
            or same.iloc[0].scheduled_execution_date != str(calendar[offset].date())
            or calendar[offset] <= pd.Timestamp(day)):
        raise ValueError("PENDING_SIGNAL_REPAIR_ALREADY_EXECUTED_OR_UNBOUND")
    return {"signal_date": day, "scheduled_execution_date": str(calendar[offset].date()),
            "repair_lineage": repair_ref, "prior_current_report": old_ref,
            "current_report": new_ref,
            "allowed_changed_outputs": ["rankings", "coverage"],
            "executed_ledger_prefix": "ALL_RECORDED_FIELDS_REQUIRED"}


def _assert_prior_prefix(name, frame, prior, date_column, keys, pending_revision=None):
    """Require every recorded field and key, including costs and identities."""
    old = prior["frames"][name].copy()
    new = frame.copy()
    old[date_column] = pd.to_datetime(old[date_column])
    new[date_column] = pd.to_datetime(new[date_column])
    cutoff = pd.Timestamp(prior["cutoff"])
    if name in {"rankings", "coverage"} and prior.get("manifest", {}).get("execution_open"):
        cutoff = min(cutoff, pd.Timestamp(prior["manifest"]["ranking_end_date"]))
    old = old.loc[old[date_column].le(cutoff)].sort_values(keys).reset_index(drop=True)
    new = new.loc[new[date_column].le(cutoff)].sort_values(keys).reset_index(drop=True)
    if pending_revision is not None and name in {"rankings", "coverage"}:
        day = pd.Timestamp(pending_revision["signal_date"])
        if day != cutoff:
            raise ValueError("PENDING_SIGNAL_REPAIR_PREFIX_SCOPE_INVALID")
        old = old.loc[old[date_column].ne(day)].reset_index(drop=True)
        new = new.loc[new[date_column].ne(day)].reset_index(drop=True)
    if name == "price_paths" and (prior.get("retained_execution_open") or prior.get("manifest", {}).get("execution_open")):
        # The sole mutable mark is an explicitly unknown terminal close becoming
        # its real completed-day close. Opens, books, fills, costs and NAV remain exact.
        phase = prior["manifest"].get("execution_open") or prior.get("retained_execution_open")
        if list(old[keys].itertuples(index=False, name=None)) == list(new[keys].itertuples(index=False, name=None)):
            complete = old[date_column].eq(pd.Timestamp(phase["execution_end_date"])) & old.close.isna()
            if not (new.loc[complete, "close"].isna() | (np.isfinite(new.loc[complete, "close"]) & new.loc[complete, "close"].gt(0))).all():
                raise ValueError("PRIOR_PERFORMANCE_INVALID_TERMINAL_CLOSE_COMPLETION")
            old.loc[complete, "close"] = new.loc[complete, "close"].to_numpy()
    try:
        if set(old.columns) != set(new.columns):
            raise AssertionError("column set changed")
        pd.testing.assert_frame_equal(old, new[list(old.columns)], check_exact=True, check_dtype=False)
    except AssertionError as exc:
        raise ValueError("PRIOR_PERFORMANCE_PREFIX_CHANGED:" + name) from exc


def _reviewed_close_revisions(overlap, prior, reconciliation):
    """Revalidate accepted close-vintage proofs; keep all original ledger marks."""
    allowed, seen = {}, set()

    def collect(review_ref, depth):
        if depth >= 8:
            raise ValueError("PRIOR_CLOSE_REVIEW_CHAIN_TOO_DEEP")
        identity = (str(Path(review_ref["path"]).resolve()), review_ref["sha256"])
        if identity in seen:
            raise ValueError("PRIOR_CLOSE_REVIEW_CHAIN_CYCLE")
        seen.add(identity)
        audit = read(verified(review_ref))
        if (audit.get("schema") != "A2_RETAINED_CLOSE_VINTAGE_REVIEW_V1"
                or audit.get("policy") != "RETAIN_OLD_EXACT_MARKS_APPEND_NEW_DATES"
                or audit.get("allowed_fields") != ["close"]):
            raise ValueError("PRIOR_CLOSE_REVIEW_CONTRACT_INVALID")
        accepted = prior["contract"].get("retained_close_vintage_review")
        if depth == 0 and review_ref != accepted and audit["prior_manifest"] != prior["ref"]:
            raise ValueError("PRIOR_CLOSE_REVIEW_ORIGIN_NOT_CURRENT_PRIOR")
        origin = read(verified(audit["prior_manifest"]))
        origin_contract = read(verified(origin["evaluation_contract"]))
        from scripts.research.a2.evaluation.demo_performance_prices import _current_entries
        historical = origin["ranking_manifest"]
        source_entries = []
        for ref in (origin_contract["current_report"], audit["current_report"]):
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
        reviews = audit.get("reviews", [])
        if not reviews or len({(item["date"], item["ticker"]) for item in reviews}) != len(reviews):
            raise ValueError("PRIOR_CLOSE_REVIEW_KEYS_INVALID")
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
            observed_before = _timestamp(before.observed_at, "PRIOR_CLOSE_REVIEW_OLD_RAW")
            observed_after = _timestamp(after.observed_at, "PRIOR_CLOSE_REVIEW_NEW_RAW")
            if (len(old) != 1 or len(new) != 1 or day != pd.Timestamp(origin["performance_end_date"])
                    or day > pd.Timestamp(prior["cutoff"])
                    or any(before[field] != after[field] for field in ("code", "open", "high", "low"))
                    or before.close == after.close
                    or observed_before >= observed_after
                    or old.iloc[0].open != new.iloc[0].open):
                raise ValueError("PRIOR_CLOSE_REVIEW_NOT_CLOSE_ONLY")
            # Shared, hash-bound anchor and rehab prove the same price coordinate.
            verified(item["shared_anchor"])
            verified(item["shared_rehab"])
            if (day, ticker) in allowed:
                raise ValueError("PRIOR_CLOSE_REVIEW_DUPLICATE_INHERITED_KEY")
            allowed[(day, ticker)] = (old.iloc[0].open, old.iloc[0].close, new.iloc[0].close)
        inherited = audit.get("inherited_review")
        if inherited is not None:
            authority = prior["contract"] if depth == 0 and review_ref != accepted else origin_contract
            if (not isinstance(inherited, dict)
                    or inherited != authority.get("retained_close_vintage_review")
                    or inherited not in audit["source_refs"]):
                raise ValueError("PRIOR_CLOSE_REVIEW_INHERITED_BINDING_INVALID")
            collect(inherited, depth + 1)

    collect(reconciliation, 0)
    changes = overlap.loc[overlap.close_prior.ne(overlap.close_current)]
    if set(allowed) != set(zip(changes.trade_date, changes.ticker)):
        raise ValueError("PRIOR_CLOSE_REVIEW_CHANGE_KEYS_NOT_EXACT")
    for item in changes.itertuples(index=False):
        expected = allowed.get((item.trade_date, item.ticker))
        if expected != (item.open_prior, item.close_prior, item.close_current):
            raise ValueError("PRIOR_PERFORMANCE_PREFIX_CHANGED:price_paths")



def _required_inherited_open_origins(manifest):
    """Inspect the already bound previous metadata, never scan or choose history."""
    binding = manifest.get("prior_verified_performance")
    if not isinstance(binding, dict):
        return []
    previous_ref = binding["manifest"]
    previous = read(verified(previous_ref))
    contract = read(verified(previous["evaluation_contract"]))
    price_input = read(verified(previous["price_inputs"]))
    declared = contract.get("retained_qualified_execution_open_origins")
    if declared != price_input.get("retained_qualified_execution_open_origins"):
        raise ValueError("PRIOR_RETAINED_OPEN_ORIGINS_NOT_BOUND")
    required = list(declared or [])
    audit = contract.get("retained_qualified_execution_opens")
    if isinstance(audit, dict) and audit.get("records"):
        phase = read(verified(audit["original_phase"]))
        rows = pd.read_parquet(verified(previous["outputs"]["price_paths"]),
            columns=["date", "close"], filters=[("date", "==", pd.Timestamp(phase["execution_end_date"]))])
        if not rows.empty and np.isfinite(rows.close).all() and rows.close.gt(0).all():
            origin = previous.get("performance_origin")
            canonical_ref = origin["manifest"] if origin is not None else previous_ref
            if origin is not None:
                canonical = read(verified(canonical_ref))
                canonical_contract = read(verified(canonical["evaluation_contract"]))
                if (contract.get("performance_origin") != origin
                        or canonical.get("performance_origin") is not None
                        or canonical["performance_end_date"] != previous["performance_end_date"]
                        or canonical["price_inputs"] != previous["price_inputs"]
                        or any(canonical["outputs"][name] != previous["outputs"][name] for name in PERFORMANCE_OUTPUTS)
                        or canonical_contract.get("retained_qualified_execution_opens") != audit
                        or canonical_contract.get("retained_qualified_execution_open_origins") != declared):
                    raise ValueError("PRIOR_RETAINED_OPEN_SAME_END_ORIGIN_CHANGED")
            required.append(canonical_ref)
    return required


def _compact_qualified_open_origin(prior):
    """Only a validated phase's small mark projection remains in memory."""
    if prior.get("retained_open_origin") is not None:
        return prior["retained_open_origin"]
    phase = prior.get("retained_execution_open")
    if phase is None:
        raise ValueError("PRIOR_RETAINED_OPEN_ORIGIN_PHASE_MISSING")
    rows = prior["frames"]["price_paths"]
    return {**prior, "frames": {"price_paths": rows.loc[
        rows.date.eq(pd.Timestamp(phase["execution_end_date"]))].copy()},
        "qualified_open_origins": [], "retained_open_origin": None}


def _qualified_open_origin_set(prior):
    origins = list(prior.get("qualified_open_origins", []))
    phase, audit = prior.get("retained_execution_open"), prior["contract"].get("retained_qualified_execution_opens")
    if phase is not None and isinstance(audit, dict) and audit.get("records"):
        rows = prior["frames"]["price_paths"]
        rows = rows.loc[rows.date.eq(pd.Timestamp(phase["execution_end_date"]))]
        if not rows.empty and np.isfinite(rows.close).all() and rows.close.gt(0).all():
            candidate = _compact_qualified_open_origin(prior)
            if not any(item["retained_execution_open"]["manifest"] == phase["manifest"] for item in origins):
                origins.append(candidate)
    found = {}
    for item in origins:
        key = str(Path(item["ref"]["path"]).resolve())
        if key in found and found[key]["ref"] != item["ref"]:
            raise ValueError("PRIOR_RETAINED_OPEN_ORIGIN_HASH_CONFLICT")
        found[key] = item
    return list(found.values())


def _carry_qualified_open_origins(price_input, prior):
    origins = _qualified_open_origin_set(prior)
    if origins:
        price_input["retained_qualified_execution_open_origins"] = [item["ref"] for item in origins]
        price_input.setdefault("refs", []).extend(ref for item in origins for ref in item["refs"])
    return origins


def _retain_qualified_execution_opens(prices, prior, price_input, current_report_path):
    """Reuse fixed accepted origins; qualify only a still-unknown current phase."""
    for origin in _carry_qualified_open_origins(price_input, prior):
        phase = origin["retained_execution_open"]
        day = pd.Timestamp(phase["execution_end_date"])
        marks = origin["frames"]["price_paths"]
        accepted = prior["frames"]["price_paths"]
        accepted = accepted.loc[accepted.date.eq(day)]
        _assert_prior_prefix("price_paths", accepted, {**origin, "cutoff": str(day.date())},
            "date", ["date", "ticker"])
        allowed = {}
        for row in origin["contract"]["retained_qualified_execution_opens"]["records"]:
            key = (pd.Timestamp(row["date"]), row["ticker"])
            if key in allowed or key[0] != day or row["ticker"] not in phase["qualified_tickers"]:
                raise ValueError("PRIOR_RETAINED_OPEN_ORIGIN_RECORD_INVALID")
            accepted_row = marks.loc[marks.date.eq(day) & marks.ticker.eq(key[1])]
            if (len(accepted_row) != 1 or accepted_row.iloc[0].open != row["recorded_open"]
                    or accepted_row.iloc[0].close != row["mature_close"]):
                raise ValueError("PRIOR_RETAINED_OPEN_ORIGIN_RECORD_INVALID")
            allowed[key] = row
        overlap = prices.merge(marks[["date", "ticker", "open"]].rename(columns={
            "date": "trade_date", "open": "recorded_open"}), on=["trade_date", "ticker"])
        for row in overlap.loc[overlap.open.ne(overlap.recorded_open)].itertuples(index=False):
            record = allowed.get((pd.Timestamp(row.trade_date), row.ticker))
            if (record is None or row.open != record["completed_vendor_open"]
                    or not np.isfinite([row.open, row.close]).all() or row.open <= 0 or row.close <= 0):
                raise ValueError("PRIOR_RETAINED_OPEN_UNRECORDED_VENDOR_REVISION")
        # Original owner rechecks current SID/code, raw SDK/rehab refs, source
        # maturity and known closes. No unseen vendor revision is admitted.
        prices, _ = _retain_native_qualified_execution_opens(prices, origin, price_input, current_report_path)
    phase = prior["manifest"].get("execution_open") or prior.get("retained_execution_open")
    if phase is None:
        return prices, None
    marks = prior["frames"]["price_paths"]
    if not marks.loc[marks.date.eq(pd.Timestamp(phase["execution_end_date"])), "close"].isna().any():
        return prices, None
    native = {**prior, "retained_execution_open": None if prior["manifest"].get("execution_open") else phase}
    return _retain_native_qualified_execution_opens(prices, native, price_input, current_report_path)


def _retain_native_qualified_execution_opens(prices, prior, price_input, current_report_path):
    """Prefer original qualified as-of opens; complete only unknown terminal closes."""
    phase = prior.get("retained_execution_open") or prior["manifest"].get("execution_open")
    if phase is None:
        return prices, None
    marks = prior["frames"]["price_paths"]
    terminal = marks.loc[marks.date.eq(pd.Timestamp(phase["execution_end_date"]))
        & (marks.close.isna() | bool(prior.get("retained_execution_open")))]
    current = prices.merge(terminal[["date", "ticker", "open", "close"]].rename(columns={
        "date": "trade_date", "open": "recorded_open", "close": "recorded_close"}),
        on=["trade_date", "ticker"], how="inner")
    known_close = current.recorded_close.notna()
    if not current.loc[known_close, "close"].eq(current.loc[known_close, "recorded_close"]).all():
        raise ValueError("PRIOR_PERFORMANCE_PREFIX_CHANGED:price_paths")
    changed = current.loc[current.open.ne(current.recorded_open)]
    qualifying = current.loc[current.open.ne(current.recorded_open) | (current.recorded_close.isna() & current.close.notna())]
    if qualifying.empty:
        return prices, None
    if (prior.get("verified_execution_price_lineage") != "ALL_IMMUTABLE_INPUT_REFS_VERIFIED"
            or not set(qualifying.ticker) <= set(phase["qualified_tickers"])
            or not np.isfinite(qualifying.close).all() or not qualifying.close.gt(0).all()):
        raise ValueError("QUALIFIED_PRIOR_OPEN_REQUIRES_VERIFIED_TERMINAL_CLOSE")
    source_ref = reference(current_report_path)
    source = read(verified(source_ref))
    _daily_rows(source)
    closing = pd.Timestamp(phase["execution_end_date"]).tz_localize("America/New_York") + pd.Timedelta(hours=16)
    if (source["data_date"] < phase["execution_end_date"]
            or price_input.get("end_date") != source["data_date"]
            or _timestamp(source["generated_at"], "QUALIFIED_PRIOR_OPEN_CURRENT_SOURCE") < closing
            or _timestamp(source["generated_at"], "QUALIFIED_PRIOR_OPEN_CURRENT_SOURCE") > pd.Timestamp(datetime.now(timezone.utc))
            or source_ref not in price_input.get("refs", [])):
        raise ValueError("QUALIFIED_PRIOR_OPEN_CLOSE_SOURCE_NOT_MATURE_OR_BOUND")
    for ref in [*prior["refs"], *price_input["refs"]]:
        verified(ref)
    original = read(verified(phase["manifest"]))
    acquisition = read(verified(original["acquisition_manifest"]))
    rehab = read(verified(original["rehab_receipt"]))
    if (acquisition.get("acquisition_mode") != "current-kline" or acquisition.get("trade_context_opened") is not False
            or rehab.get("source") != "MOOMOO_OPEND_GET_REHAB"
            or rehab.get("target_date") != phase["execution_end_date"]):
        raise ValueError("QUALIFIED_PRIOR_OPEN_ORIGINAL_CAPTURE_INVALID")
    universe = source["universe"]
    members_ref = {"path": str(Path(universe["report_path"]).resolve().parent / "mapped_members.parquet"),
                   "sha256": universe["universe_members_sha256"]}
    members = pd.read_parquet(verified(members_ref), columns=["ticker", "security_id", "moomoo_symbol"])
    records, capture_refs = [], []
    for row in qualifying.itertuples(index=False):
        identities = [item for item in original["records"] if item["ticker"] == row.ticker]
        mapped = members.loc[members.ticker.eq(row.ticker)]
        if (len(identities) != 1 or len(mapped) != 1 or not identities[0].get("security_id")
                or mapped.iloc[0].security_id != identities[0]["security_id"]
                or mapped.iloc[0].moomoo_symbol != identities[0]["code"]):
            raise ValueError("QUALIFIED_PRIOR_OPEN_CURRENT_SECURITY_IDENTITY_CHANGED:" + row.ticker)
        identity = identities[0]
        captures = [item for item in acquisition["results"] if item.get("item", {}).get("ticker") == row.ticker]
        factors = [item for item in rehab["results"] if item.get("code") == identity["code"] and item.get("status") == "PASS"]
        if len(captures) != 1 or len(factors) != 1:
            raise ValueError("QUALIFIED_PRIOR_OPEN_ORIGINAL_CAPTURE_MISSING:" + row.ticker)
        provenance = captures[0]["current_kline_provenance"]
        sdk_ref = provenance["sdk_response"]
        factor_ref = {"path": factors[0]["path"], "sha256": factors[0]["sha256"]}
        if (provenance.get("code") != identity["code"] or provenance.get("api") != "get_cur_kline"
                or provenance.get("autype") != "NONE" or provenance.get("session") != "RTH"
                or _timestamp(provenance["observed_at_utc"], "QUALIFIED_PRIOR_OPEN_CAPTURE") > _timestamp(phase["as_of_utc"], "QUALIFIED_PRIOR_OPEN_PHASE")
                or any(ref not in prior["refs"] for ref in (sdk_ref, factor_ref))):
            raise ValueError("QUALIFIED_PRIOR_OPEN_ORIGINAL_CAPTURE_BINDING_INVALID:" + row.ticker)
        if row.open != row.recorded_open:
            capture_refs.extend([sdk_ref, factor_ref])
            records.append({"date": str(row.trade_date.date()), "ticker": row.ticker, "security_id": identity["security_id"],
                "code": identity["code"], "recorded_open": row.recorded_open, "completed_vendor_open": row.open,
                "mature_close": row.close})
    if changed.empty:
        return prices, None
    retained = prices.copy()
    old = {row.ticker: row.recorded_open for row in changed.itertuples(index=False)}
    replacement = retained.ticker.map(old)
    selected = retained.trade_date.eq(pd.Timestamp(phase["execution_end_date"])) & replacement.notna()
    retained.loc[selected, "open"] = replacement.loc[selected].to_numpy()
    audit = {"schema": "A2_RETAINED_QUALIFIED_EXECUTION_OPEN_V1", "policy": "ORIGINAL_ASOF_OPEN_EXACT_MATURE_UNKNOWN_CLOSE_ONLY",
        "prior_manifest": prior["ref"], "prior_price_paths": prior["manifest"]["outputs"]["price_paths"],
        "original_phase": phase["manifest"], "original_acquisition": original["acquisition_manifest"],
        "original_rehab": original["rehab_receipt"], "original_capture_refs": capture_refs,
        "current_source": source_ref, "current_members": members_ref, "current_price_input_refs": price_input["refs"],
        "records": records, "prior_ledger_changed": False, "model_feature_eligibility_granted": False}
    return retained, audit

def _retain_prior_execution_marks(prices, prior, reconciliation=None):
    """Reuse qualified adjusted open/close only; unknown OHLCV stays unknown."""
    marks = prior["frames"]["price_paths"]
    marks = marks.loc[marks.date.le(pd.Timestamp(prior["cutoff"]))]
    marks = marks[["date", "ticker", "open", "close"]].rename(columns={"date": "trade_date"})
    overlap = marks.merge(prices, on=["trade_date", "ticker"], suffixes=("_prior", "_current"))
    if not overlap.open_prior.eq(overlap.open_current).all():
        raise ValueError("PRIOR_PERFORMANCE_PREFIX_CHANGED:price_paths")
    equal_close = overlap.close_prior.eq(overlap.close_current) | (overlap.close_prior.isna() & overlap.close_current.isna())
    phase = prior.get("manifest", {}).get("execution_open") or prior.get("retained_execution_open")
    completion = (overlap.trade_date.eq(pd.Timestamp(phase["execution_end_date"])) & overlap.close_prior.isna()
                  if phase else pd.Series(False, index=overlap.index))
    if not (equal_close | completion).all():
        if reconciliation is None:
            raise ValueError("PRIOR_PERFORMANCE_PREFIX_CHANGED:price_paths")
        _reviewed_close_revisions(overlap.loc[~completion], prior, reconciliation)
    keys = ["trade_date", "ticker"]
    prefix = prices.set_index(keys).reindex(pd.MultiIndex.from_frame(marks[keys]))
    prefix["open"] = marks.open.to_numpy()
    retained_close = marks.close.to_numpy().copy()
    if phase:
        complete = marks.trade_date.eq(pd.Timestamp(phase["execution_end_date"])) & marks.close.isna()
        retained_close[complete.to_numpy()] = prefix.loc[complete.to_numpy(), "close"].to_numpy()
    prefix["close"] = retained_close
    prefix = prefix.reset_index()
    tail = prices.loc[prices.trade_date.gt(pd.Timestamp(prior["cutoff"]))]
    return pd.concat([prefix, tail], ignore_index=True).sort_values(keys).reset_index(drop=True)



def _reuse_same_end_performance(paths, work, report, prior, rankings, coverage, calendar,
                                current_report_path, refs, ready_reports, expected, inference_ref, prior_binding):
    """Append a pending signal; reuse every accepted execution byte and source."""
    from scripts.common.daily_support import save
    end = str(rankings.target_date.max())
    if end != prior["cutoff"]:
        raise ValueError("SAME_END_PERFORMANCE_REUSE_DATE_MISMATCH")
    old_end = prior["manifest"]["ranking_end_date"]
    appended = rankings.loc[rankings.target_date.gt(old_end), "target_date"].unique()
    if any(calendar[calendar.get_loc(pd.Timestamp(day)) + 1] <= pd.Timestamp(prior["cutoff"])
           for day in appended):
        raise ValueError("SAME_END_REUSE_SIGNAL_ALREADY_REQUIRES_EXECUTION")
    original = prior["manifest"]
    origin = original.get("performance_origin") or {"schema": "A2_IMMUTABLE_PERFORMANCE_ORIGIN_V1",
        "mode": "REUSE_VERIFIED_EXECUTED_LEDGER_SAME_END", "manifest": prior["ref"]}
    cutoff = pd.Timestamp(prior["cutoff"])
    decisions = decision_calendar(rankings, coverage, calendar, cutoff, original.get("blocking_input"))
    old_decisions = pd.read_parquet(verified(original["outputs"]["decision_calendar"]))
    prefix = decisions.loc[decisions.signal_date.isin(old_decisions.signal_date)].sort_values("signal_date").reset_index(drop=True)
    pd.testing.assert_frame_equal(old_decisions.sort_values("signal_date").reset_index(drop=True),
                                  prefix[list(old_decisions.columns)], check_exact=True, check_dtype=False)
    outputs = dict(original["outputs"])
    for name, frame in (("rankings", rankings), ("coverage", coverage), ("decision_calendar", decisions)):
        output = work / (name + ".parquet")
        frame.to_parquet(output, index=False)
        outputs[name] = {**reference(output), "rows": len(frame)}
    contract = {**prior["contract"], "created_at": report["generated_at"],
        "current_report": reference(current_report_path), "rankings": reference(work / "rankings.parquet"),
        "ranking_end_date": end, "input_refs": refs, "missing_signal_inference": inference_ref,
        "performance_origin": origin, "prior_verified_performance": prior_binding}
    save(work / "evaluation_contract.json", contract)
    result = {**original, **report, "status": "PARTIAL" if original["status"] == "PARTIAL" or coverage.status.ne("READY").any() else "READY",
        "ranking_end_date": end, "ranking_days": len(expected), "outputs": outputs,
        "evaluation_contract": reference(work / "evaluation_contract.json"), "input_refs": refs,
        "recommendation_reports": ready_reports, "missing_signal_inference": inference_ref,
        "producer_sha256": digest(__file__), "model_fit_count": 0, "parameter_search_count": 0,
        "ranking_status": "PARTIAL" if coverage.status.ne("READY").any() else "READY",
        "performance_origin": origin, "action": "REUSE_VERIFIED_EXECUTED_LEDGER_SAME_END",
        "prior_verified_performance": {**prior_binding, "prefix_verification": "PASSED"}}
    for item in [*prior["refs"], *refs, *outputs.values(), result["evaluation_contract"]]:
        verified(item)
    save(work / "manifest.json", result)
    _prior_verified_performance(paths, work / "manifest.json", Path(report["ranking_manifest"]["path"]),
        read(verified(report["ranking_manifest"]))["models"]["artifacts"], result["authority_refs"],
        result["calendar_lineage"], end, _allow_retained_partial=False)
    save(paths.daily_root / "A2_updated_research/latest.json", result)
    return result


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


def safe_execution_end(signals, prices, calendar, events, resolved_events=None, *, execution_end=None):
    """Strict old calendar stopping policy; retain only the verified prefix."""
    target = {pd.Timestamp(day): set(part.ticker) for day, part in signals.loc[signals["rank"].le(20)].groupby("target_date")}
    first, end = min(target), max(target)
    if execution_end is not None:
        execution = pd.Timestamp(execution_end)
        if (end not in calendar or execution not in calendar
                or calendar.get_loc(execution) != calendar.get_loc(end) + 1):
            raise ValueError("EXECUTION_OPEN_NEXT_OFFICIAL_SESSION_REQUIRED")
        end = execution
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
                             close_vintage_review_path=None, additional_price_manifest_path=None,
                             pending_signal_revision_path=None, execution_open_manifest=None, execution_end=None,
                             reuse_same_end_performance=False, retain_qualified_prior_open=False):
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
            prior, prior_binding, pending_revision = None, None, None
            if pending_signal_revision_path is not None and prior_verified_performance_manifest_path is None:
                raise ValueError("PENDING_SIGNAL_REPAIR_PRIOR_REQUIRED")
            if prior_verified_performance_manifest_path is not None:
                prior = _prior_verified_performance(paths, prior_verified_performance_manifest_path,
                    historical_manifest_path, read(historical_manifest_path)["models"]["artifacts"],
                    authority, calendar_ref["lineage"], str(end.date()))
                if pending_signal_revision_path is not None:
                    pending_revision = _pending_signal_revision(
                        prior, current_report_path, pending_signal_revision_path, calendar)
                    if str(end.date()) != pending_revision["signal_date"]:
                        raise ValueError("PENDING_SIGNAL_REPAIR_CURRENT_END_MISMATCH")
                absent = set(expected.strftime("%Y-%m-%d")) - set(rankings.target_date)
                retained = prior["frames"]["rankings"]
                reused = sorted(absent & set(retained.loc[retained.target_date.le(prior["cutoff"]), "target_date"]))
                rankings = _validate_rankings(pd.concat([rankings, retained.loc[retained.target_date.isin(reused)]], ignore_index=True),
                    read(historical_manifest_path)["models"]["artifacts"])
                coverage = pd.concat([coverage, prior["frames"]["coverage"].loc[
                    prior["frames"]["coverage"].target_date.isin(reused)]], ignore_index=True).sort_values("target_date").reset_index(drop=True)
                _assert_prior_prefix("rankings", rankings, prior, "target_date", ["target_date", "rank"], pending_revision)
                _assert_prior_prefix("coverage", coverage, prior, "target_date", ["target_date"], pending_revision)
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
            if (reuse_same_end_performance and prior is not None and str(end.date()) == prior["cutoff"]
                    and execution_open_manifest is None and execution_end is None
                    and pending_revision is None):
                progress("保留已验证的执行曲线原值，单独更新最新排名与待执行信号。")
                return _reuse_same_end_performance(paths, work, report, prior, rankings, coverage, calendar,
                    current_report_path, refs, ready_reports, expected, inference_ref, prior_binding)
            progress("按原 Top20 等权、次日开盘和成本规则更新展示绩效。")
            selected = sorted(set(rankings.loc[rankings["rank"].le(20), "ticker"]))
            price_input = load_execution_prices(paths, historical_manifest_path, tickers=selected,
                current_report_path=current_report_path, start=str(first.date()), end=str(end.date()),
                **({"inference_manifest_path": inference_ref["path"]} if inference_ref else {}),
                **({"current_execution_manifest_path": current_execution_manifest_path}
                   if current_execution_manifest_path is not None else {}),
                **({"execution_open_manifest": execution_open_manifest, "execution_end": execution_end}
                   if execution_open_manifest is not None or execution_end is not None else {}),
                **({"additional_price_manifest_path": additional_price_manifest_path}
                   if additional_price_manifest_path is not None else {}))
            if additional_price_manifest_path is not None:
                price_input["additional_price_manifest"] = reference(additional_price_manifest_path)
            prices = price_input["prices"].copy(); prices["trade_date"] = pd.to_datetime(prices.trade_date)
            if prices.duplicated(["trade_date", "ticker"]).any():
                raise ValueError("DUPLICATE_EXECUTION_PRICE")
            if prior is not None:
                review = (reference(close_vintage_review_path) if close_vintage_review_path is not None
                          else prior["contract"].get("retained_close_vintage_review"))
                _carry_qualified_open_origins(price_input, prior)
                if retain_qualified_prior_open:
                    prices, retained_open = _retain_qualified_execution_opens(prices, prior, price_input, current_report_path)
                    if retained_open is not None:
                        price_input["retained_qualified_execution_opens"] = retained_open
                        price_input.setdefault("refs", []).extend([retained_open["current_members"], prior["ref"]])
                prices = _retain_prior_execution_marks(prices, prior, review)
                if review is not None:
                    price_input["retained_close_vintage_review"] = review
                    price_input.setdefault("refs", []).append(review)
                price_input["prior_verified_prefix"] = prior_binding
                price_input["refs"] = [*price_input.get("refs", []), *prior["contract"]["price_refs"],
                    prior["ref"], prior["manifest"]["evaluation_contract"], prior["manifest"]["price_inputs"],
                    prior["manifest"]["outputs"]["price_paths"]]
            resolved, event_audit = reviewed_events(price_input["events"], price_input.get("event_review"), price_input.get("refs", []))
            if execution_end is not None and (not price_input.get("execution_open")
                    or price_input["execution_open"].get("execution_end_date") != execution_end
                    or price_input["execution_open"].get("signal_end_date") != str(end.date())):
                raise ValueError("EXECUTION_OPEN_QUALIFIED_INPUT_REQUIRED")
            cutoff, blocked = safe_execution_end(rankings, prices, calendar, price_input["events"], resolved,
                **({"execution_end": execution_end} if execution_end is not None else {}))
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
            if price_input.get("execution_open") is not None:
                contract["execution_open"] = price_input["execution_open"]
            if price_input.get("retained_qualified_execution_opens") is not None:
                contract["retained_qualified_execution_opens"] = price_input["retained_qualified_execution_opens"]
            if price_input.get("retained_qualified_execution_open_origins") is not None:
                contract["retained_qualified_execution_open_origins"] = price_input["retained_qualified_execution_open_origins"]
            if price_input.get("additional_price_manifest") is not None:
                contract["additional_price_manifest"] = price_input["additional_price_manifest"]
            if pending_revision is not None:
                contract["pending_signal_revision"] = pending_revision
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
                    _assert_prior_prefix(name, frame, prior, column, keys, pending_revision)
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
            if price_input.get("execution_open") is not None:
                report["execution_open"] = price_input["execution_open"]
            if prior_binding is not None:
                report["prior_verified_performance"] = {**prior_binding, "prefix_verification": "PASSED"}
            save(work / "manifest.json", report)
            if len(daily) > 1:
                _prior_verified_performance(paths, work / "manifest.json", historical_manifest_path,
                    read(historical_manifest_path)["models"]["artifacts"], authority, calendar_ref["lineage"],
                    str(end.date()), _allow_retained_partial=False)
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
