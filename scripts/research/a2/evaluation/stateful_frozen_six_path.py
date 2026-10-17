"""Narrow six-policy descriptive evaluation using the existing account owners.

No data/model reader, source certifier or account implementation lives here.
The caller supplies admitted source projections and frozen inference packets.
Calendar scheduling never consumes prices, predictions or economic outcomes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd

from scripts.research.a2.evaluation import frozen_test_authority as authority
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
from scripts.research.a2.inference import stateful_frozen_test as frozen_inference
from scripts.research.a2.training import stateful_replay as replay
from scripts.research.a2.training import stateful_decision as decision
from scripts.research.a2.training import stateful_execution as execution_owner
from scripts.research.a2.training.stateful_final_action import FinalActionOverlay, _full_metrics
from scripts.research.a2.training.stateful_final_action_packets import decode_resource_proposals, decode_r6_row
from scripts.storage.storage_r2a import assert_write_path, sha256, write_json_atomic

PATH_IDS = authority.PATH_IDS
BENCHMARKS = (PATH_IDS[0], *PATH_IDS[4:])
MAX_PATHS = 606
SEED = 20261008
POLICY_REFS = {
    "raw": dict(path="D:/us-tech-quant-results/_maintenance/V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1/FROZEN_RESEARCH57_CANDIDATES.json",
                sha256="dc009c7596b80439eb2cdea8a410c1169213f2242b8a76e2ab55298db023daed"),
    "breadth": dict(path="D:/us-tech-quant-results/_maintenance/V24_A_OVERNIGHT_BASELINE_READY_PACKAGE_R1/A_BREADTH_FROZEN_DESIGN_R1.json",
                    sha256="d9ca279bcbe22c1f2ea5a9d17d2c76ecf8f98d1b5b4dac1c4c212dad64669488"),
    "action": dict(path="D:/us-tech-quant-results/_maintenance/V24_A_FINAL_ACTION_COVERAGE_AND_STATEFUL_DECISION_R1/A_FINAL_ACTION_COVERAGE_MANIFEST.json",
                   sha256="eee22010f3239882025b426e87a54f7fb7b7c4506637df218a8cf05942a0df7a"),
}


def _require(ok, code):
    if not ok:
        raise ValueError(code)


def _commit(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_policy_rows(rows):
    _require(isinstance(rows, (list, tuple)) and len(rows) == 6
             and tuple(r.get("candidate_id") for r in rows) == PATH_IDS, "SIX_PATH_EXACT_ORDER")
    common = dict(control="none", gross="fixed", risk="diag20_reference",
                  forecast="none", target_role="shareholder5d")
    for row in rows[:4]:
        cid = row["candidate_id"]
        expected = dict(common, action="stateful" if cid == PATH_IDS[3] else "raw",
            action_cost_mode="aware" if cid == PATH_IDS[3] else "blind",
            value_model="ngboost" if cid == PATH_IDS[3] else "ridge")
        _require(all(row.get(k) == v for k, v in expected.items())
                 and row.get("scientific_tuple_sha256") == authority.POLICY_TUPLE_SHA256[cid],
                 "SIX_PATH_FROZEN_POLICY_SCALARS_CHANGED")
        f = row.get("execution_friction", {})
        _require(f == rows[0].get("execution_friction") and f.get("one_way_bps") == 10
                 and f.get("fee_bps") == 0, "SIX_PATH_FROZEN_FRICTION_CHANGED")
        if cid in PATH_IDS[1:3]:
            _require(row.get("original_scientific_family") ==
                     ("R6_buy_tree" if cid == PATH_IDS[1] else "R6_replace_tree")
                     and row.get("model_output_state") == "ORIGINAL_FROZEN_PROXY_NOT_ACTUAL_ACCOUNT_STATE",
                     "SIX_PATH_ORIGINAL_R6_DECODER_CONTRACT_REQUIRED")
    for row in rows[4:]:
        contract = row.get("benchmark_contract", {})
        _require(contract.get("ticker") == row["candidate_id"].split("_", 1)[0]
                 and contract.get("policy") == "BUY_AND_HOLD"
                 and contract.get("fractional") is True
                 and contract.get("execution") == "ORIGINAL_NEXT_LEGAL_RAW_OPEN"
                 and contract.get("friction_bps") == 10
                 and contract.get("corporate_actions") == "SOURCE_BACKED_DIVIDENDS_SPLITS_CASH"
                 and contract.get("terminal_liquidation") is False
                 and row.get("scientific_tuple_sha256") == _commit(contract),
                 "SIX_PATH_FROZEN_ETF_CONTRACT_CHANGED")
    return rows


def load_frozen_policies(plan_ref):
    """Read only the three exact pre-outcome manifests and frozen plan metadata."""
    plan = authority.six_path_plan(plan_ref)
    docs = {k: json.loads(authority._physical(ref).read_text(encoding="utf-8-sig"))
            for k, ref in POLICY_REFS.items()}
    sources = [docs["raw"], docs["action"]["candidates"],
               docs["action"]["candidates"], docs["breadth"]["specification"]["candidates_in_exact_order"]]
    rows = []
    for cid, source in zip(PATH_IDS[:4], sources):
        matches = [r for r in source if r.get("candidate_id") == cid]
        _require(len(matches) == 1, "SIX_PATH_ORIGINAL_MANIFEST_ROW_REQUIRED")
        rows.append(deepcopy(matches[0]))
    for cid in PATH_IDS[4:]:
        contract = authority.benchmark_contract(plan, cid)
        rows.append(dict(candidate_id=cid, benchmark_contract=contract,
            scientific_tuple_sha256=_commit(contract), execution_friction=deepcopy(rows[0]["execution_friction"])))
    if plan.get("task_id") in authority.universe_variant_tasks():
        for row in rows:
            row["original_policy_tuple_sha256"] = row["scientific_tuple_sha256"]
            row["variant_evaluation_tuple_sha256"] = authority.aggregate_evaluation_tuple(
                plan_ref, row["scientific_tuple_sha256"])
    return _validate_policy_rows(rows)


def completed_calendar(common_covered_sessions, *, as_of):
    """Pure original session filter, shared by exact frozen task schedulers."""
    dates = pd.DatetimeIndex(common_covered_sessions)
    _require(len(dates) >= 2 and dates.tz is None and not dates.hasnans
             and dates.is_monotonic_increasing and dates.is_unique
             and dates.equals(dates.normalize())
             and dates.min() >= pd.Timestamp("2026-01-01")
             and dates.max() < pd.Timestamp("2027-01-01"), "SIX_PATH_2026_CALENDAR_REQUIRED")
    now = pd.Timestamp(as_of)
    _require(not pd.isna(now) and now.tzinfo is not None, "SIX_PATH_AS_OF_REQUIRED")
    closes = (dates + pd.Timedelta(hours=16)).tz_localize("America/New_York")
    dates = dates[closes <= now]
    _require(len(dates) >= 2, "SIX_PATH_COMPLETED_SIGNAL_AND_EXECUTION_REQUIRED")
    return dates, now


def random_window_records(dates):
    """Original PCG64/100/min20 selection; takes only a validated calendar."""
    eligible = np.arange(2, max(2, len(dates) - 19))
    picks = np.sort(np.random.Generator(np.random.PCG64(SEED)).choice(
        eligible, size=min(100, len(eligible)), replace=False))
    windows = []
    for ordinal, i in enumerate([1, *picks]):
        windows.append(dict(window_id="MAIN" if ordinal == 0 else f"RANDOM_{ordinal:03d}",
            kind="MAIN" if ordinal == 0 else "RANDOM", start=str(dates[i-1].date()),
            account_initialization=str(dates[i-1].date()), signal_context_start=str(dates[i-1].date()),
            first_execution_date=str(dates[i].date()), end=str(dates[-1].date()),
            execution_sessions=int(len(dates)-i)))
    return windows, len(eligible), len(picks)


def build_schedule(common_covered_sessions, *, as_of, task_id=authority.TASK, inherited_schedule_ref=None):
    """Input is already intersected calendar/source-coverage metadata, no values.

    Original pending=None is preserved. Each window initializes in cash on its
    signal-context session; its declared first execution is the following Open.
    """
    _require(task_id in authority.six_path_tasks(), "SIX_PATH_EXACT_TASK_REQUIRED")
    dates, now = completed_calendar(common_covered_sessions, as_of=as_of)
    descendant = task_id in authority.pool_descendant_tasks()
    if descendant:
        root_schedule = authority.pool_descendant_schedule(inherited_schedule_ref)
        _require(list(dates.strftime("%Y-%m-%d")) == root_schedule["common_sessions"]
                 and now.isoformat() == root_schedule["as_of"], "POOL_DESCENDANT_CALENDAR_CHANGED")
    if task_id == authority.CONSENSUS_TASK:
        _require(isinstance(inherited_schedule_ref, dict)
                 and inherited_schedule_ref.get("sha256") == authority.CONSENSUS_PARENT_SCHEDULE_SHA256,
                 "CONSENSUS_EXACT_PARENT_SCHEDULE_REQUIRED")
        parent = authority._document(inherited_schedule_ref)
        _require(parent.get("task_id") == authority.AGGREGATE_TASK,
                 "CONSENSUS_EXACT_PARENT_SCHEDULE_REQUIRED")
        _schedule_keys(parent)
        main = parent["windows"][0]
        context = dates[(dates >= pd.Timestamp(main["start"])) & (dates <= pd.Timestamp(main["end"]))]
        _require(len(context) == main["execution_sessions"] + 1
                 and str(context[0].date()) == main["start"] and str(context[-1].date()) == main["end"]
                 and all(pd.Timestamp(w[k]) in context for w in parent["windows"]
                         for k in ("start", "first_execution_date", "end")),
                 "CONSENSUS_PARENT_WINDOW_COVERAGE_REQUIRED")
        inherited = deepcopy(parent)
        inherited.update(task_id=task_id, as_of=now.isoformat(), parent_schedule_ref=deepcopy(inherited_schedule_ref))
        _schedule_keys(inherited)
        return inherited
    _require(descendant or inherited_schedule_ref is None, "SIX_PATH_UNEXPECTED_INHERITED_SCHEDULE")
    windows, eligible_count, random_count = random_window_records(dates)
    result = dict(task_id=task_id, windows=windows, path_ids=list(PATH_IDS),
        common_end=str(dates[-1].date()), as_of=now.isoformat(),
        random_generator="numpy.random.Generator(PCG64)", seed=SEED,
        eligible_random_start_count=eligible_count, random_start_count=random_count,
        account_paths=len(windows)*6, account_paths_max=MAX_PATHS,
        first_day_semantics="CASH_ONLY_SIGNAL_CONTEXT_THEN_NEXT_OPEN;NO_INHERITED_STATE",
        overlapping_starts_not_independent_trials=True)
    if descendant:
        _require(windows == root_schedule["windows"], "POOL_DESCENDANT_WINDOW_GENERATION_CHANGED")
        result["parent_schedule_ref"] = deepcopy(inherited_schedule_ref)
    return result


def _dual_nav_frames(result, frames=None):
    """Column projection of the sole owner's cash, raw marks and receivables."""
    out = {} if frames is None else dict(frames)
    d = result.daily.copy()
    _require("receivable_value_usd" in d, "SIX_PATH_OWNER_RECEIVABLE_STATE_REQUIRED")
    p = result.positions
    assets = p.groupby(["path_id", "date"]).market_value.sum(min_count=1)
    keys = pd.MultiIndex.from_frame(d[["path_id", "date"]])
    d["market_securities_value_usd"] = assets.reindex(keys, fill_value=0.).to_numpy(float)
    d["LIQUID_NAV"] = d.cash + d.market_securities_value_usd
    d["TOTAL_ECONOMIC_NAV"] = d.LIQUID_NAV + d.receivable_value_usd
    d["research_cash_weight"] = d.cash / d.TOTAL_ECONOMIC_NAV
    d["research_gross"] = d.market_securities_value_usd / d.TOTAL_ECONOMIC_NAV
    out.update(daily=d, positions=out.get("positions", p), fills=result.fills, orders=result.orders,
               execution_results=result.execution_results)
    out.setdefault("actions", pd.DataFrame(columns=["path_id", "policy_action"]))
    if hasattr(result, "entitlements"):
        out["entitlements"] = result.entitlements
    return out


def _qualification(frames):
    d, p = frames["daily"], frames["positions"]
    flags = dict(accounting=bool(d.accounting_qualified.eq(True).all()),
        certified_nav=bool(np.isfinite(d.certified_nav).all() and d.certified_nav.gt(0).all()),
        quote=bool(not p[["stale", "unknown"]].to_numpy(bool).any()),
        cash_identity=bool(np.isfinite(d.actual_cash_flow_identity_error).all()
            and np.abs(d.actual_cash_flow_identity_error).max() <= 1e-8),
        nav_identity=bool(np.isfinite(d.nav).all() and
            np.allclose(d.nav, d.TOTAL_ECONOMIC_NAV, rtol=1e-12, atol=1e-8)))
    return dict(groups=flags, all_passed=all(flags.values()),
                strict_PIT_promotion_eligible=False, production_qualified=False)


def _inference_coverage(candidate, inputs, admitted):
    """A missing frozen head is not a successful RAW fallback.

    The provider binds the actual validated model handle, original producer
    samples, adapter output and per-session support status. Zero support may
    legally produce no proposal; it must remain an explicit auditable state.
    This verifies supplied evidence without predicting or changing support.
    """
    cid = candidate["candidate_id"]
    if cid not in authority.MODEL_IDS:
        return None
    evidence = inputs.get("inference_evidence", {}).get(cid)
    _require(isinstance(evidence, dict), "SIX_PATH_FROZEN_HEAD_EVIDENCE_REQUIRED")
    bundle = evidence.get("bundle")
    _require(type(bundle) is frozen_inference.Frozen2025Model
             and bundle._seal is frozen_inference._SEAL and bundle.path_id == cid
             and bundle.model_ref.get("sha256") == authority.MODEL_SHA256[cid]
             and bundle.receipt_ref.get("sha256") == frozen_inference.RECEIPT_SHA256[cid],
             "SIX_PATH_ACTUAL_FROZEN_BUNDLE_REQUIRED")
    frozen_inference._check_sources(bundle)
    dates = inputs["market"].dates
    support, predictions = evidence.get("support"), evidence.get("predictions")
    _require(isinstance(support, pd.DataFrame) and isinstance(predictions, pd.DataFrame)
             and {"signal_date", "status", "eligible_count", "reason"} <= set(support)
             and pd.DatetimeIndex(support.signal_date).equals(dates),
             "SIX_PATH_EXPLICIT_SESSION_SUPPORT_REQUIRED")
    _require({"signal_date", "ticker"} <= set(predictions)
             and pd.to_datetime(predictions.signal_date).isin(dates).all(),
             "SIX_PATH_INFERENCE_OUTPUT_KEYS_REQUIRED")
    authority.validate_descriptive_input_dates(admitted, dates)
    if cid in authority.MODEL_IDS[:2]:
        samples = evidence.get("samples")
        _require(isinstance(samples, pd.DataFrame), "SIX_PATH_ORIGINAL_R6_SAMPLES_REQUIRED")
        if not samples.empty:
            _require({"signal_date", "sample_id", "ticker", "security_id", *bundle.features} <= set(samples)
                     and not samples.duplicated(["signal_date", "sample_id"]).any()
                     and pd.to_datetime(samples.signal_date).isin(dates).all(),
                     "SIX_PATH_ORIGINAL_R6_SAMPLE_KEYS_REQUIRED")
            legal = samples.security_id.map(decision._valid_sid)
            for row in samples.itertuples():
                _require(not decision._valid_sid(row.security_id)
                         or inputs["sid_by_key"].get((pd.Timestamp(row.signal_date), str(row.ticker))) == row.security_id,
                         "SIX_PATH_R6_SAMPLE_SID_CHANGED")
            ages = ("cohort_age_sessions",) if bundle.objective == "buy" else ("e_cohort_age_sessions", "i_cohort_age_sessions")
            for name in ages:
                legal &= samples[name].between(0, 20)
            if bundle.objective == "replace":
                legal &= samples.incumbent_sid.map(decision._valid_sid)
                for row in samples.itertuples():
                    _require(not decision._valid_sid(row.incumbent_sid)
                             or inputs["sid_by_key"].get((pd.Timestamp(row.signal_date), str(row.incumbent))) == row.incumbent_sid,
                             "SIX_PATH_R6_SAMPLE_SID_CHANGED")
            eligible = samples.loc[legal]
        else:
            eligible = samples
        _require({"sample_id", "p_superior", "model_year"} <= set(predictions)
                 and not predictions.duplicated(["signal_date", "sample_id"]).any()
                 and predictions.model_year.eq(2025).all(), "SIX_PATH_FROZEN_R6_OUTPUT_REQUIRED")
        expected_keys = set(zip(eligible.get("signal_date", []), eligible.get("sample_id", [])))
        _require(set(zip(predictions.signal_date, predictions.sample_id)) == expected_keys
                 and np.isfinite(predictions.p_superior.to_numpy(float)).all()
                 and predictions.p_superior.between(0, 1).all(), "SIX_PATH_SUPPORTED_R6_OUTPUT_MISSING")
        if not eligible.empty:
            identities = [c for c in ("ticker", "security_id", "incumbent", "incumbent_sid", "cohort_age_sessions") if c in eligible]
            _require(set(identities) <= set(predictions), "SIX_PATH_R6_PREDICTION_IDENTITY_CHANGED")
            check = eligible[["signal_date", "sample_id", *identities]].merge(
                predictions, on=["signal_date", "sample_id"], validate="one_to_one", suffixes=("_input", "_output"))
            _require(all(check[c+"_input"].fillna("__UNKNOWN__").eq(check[c+"_output"].fillna("__UNKNOWN__")).all()
                         for c in identities), "SIX_PATH_R6_PREDICTION_IDENTITY_CHANGED")
        perdate = inputs.get("action_packets", {}).get(cid)
        _require(isinstance(perdate, dict) and set(perdate) <= set(dates), "SIX_PATH_EXPLICIT_ACTION_HEAD_REQUIRED")
        for date in dates:
            rows = predictions.loc[predictions.signal_date.eq(date)]
            actual = perdate.get(date, [])
            _require(len(actual) == len(rows), "SIX_PATH_SUPPORTED_ACTION_PACKET_MISSING")
            orders = [r.get("source_order") for r in actual]
            _require(orders == sorted(set(orders)), "SIX_PATH_ORIGINAL_PROPOSAL_ORDER_CHANGED")
            for row, proposal in zip(rows.to_dict("records"), actual):
                expected = decode_r6_row(row, bundle.objective, proposal["source_order"])
                _require(json.dumps(expected, sort_keys=True, default=str) ==
                         json.dumps(proposal, sort_keys=True, default=str), "SIX_PATH_ORIGINAL_DECODER_OUTPUT_CHANGED")
    else:
        _require({"prediction_qualified", "prediction", "value_sigma", "year", "model_sha256"} <= set(predictions)
                 and not predictions.duplicated(["signal_date", "ticker"]).any()
                 and predictions.prediction_qualified.isin([True, False]).all()
                 and predictions.year.eq(2025).all()
                 and predictions.model_sha256.eq(authority.MODEL_SHA256[cid]).all(),
                 "SIX_PATH_FROZEN_VALUE_OUTPUT_REQUIRED")
        eligible = predictions.loc[predictions.prediction_qualified]
        stock = np.asarray(inputs["stock_present"], bool)
        expected_keys = {(date, str(inputs["market"].tickers[j])) for i, date in enumerate(dates)
                         for j in np.flatnonzero(stock[i])}
        _require(set(zip(eligible.signal_date, eligible.ticker)) == expected_keys,
                 "SIX_PATH_SUPPORTED_VALUE_OUTPUT_MISSING")
        packet = inputs["packets"]["ngboost"]
        lookup = {str(t): j for j, t in enumerate(inputs["market"].tickers)}
        for i, date in enumerate(dates):
            day = eligible.loc[eligible.signal_date.eq(date)]
            _require(np.isfinite(day.prediction.to_numpy(float)).all() and np.isfinite(day.value_sigma.to_numpy(float)).all()
                     and day.value_sigma.gt(0).all()
                     and all(packet["mu"][i, lookup[r.ticker]] == r.prediction for r in day.itertuples())
                     and (day.empty or day.value_sigma.eq(packet["sigma"][i]).all())
                     and np.isnan(np.asarray(packet["mu"])[i, ~stock[i]]).all(),
                     "SIX_PATH_FROZEN_VALUE_PACKET_CHANGED")
    counts = eligible.groupby("signal_date").size() if not eligible.empty else pd.Series(dtype=int)
    for row in support.itertuples():
        count = int(counts.get(pd.Timestamp(row.signal_date), 0))
        _require(row.eligible_count == count
                 and row.status == ("INFERRED" if count else "NO_SUPPORT")
                 and (count > 0 or isinstance(row.reason, str) and bool(row.reason.strip())),
                 "SIX_PATH_NO_SUPPORT_MUST_BE_EXPLICIT")
    return dict(model_ref=deepcopy(bundle.model_ref), receipt_ref=deepcopy(bundle.receipt_ref),
                inferred_sessions=int(support.status.eq("INFERRED").sum()),
                no_support_sessions=int(support.status.eq("NO_SUPPORT").sum()),
                inferred_rows=len(eligible))


def _execute_path(candidate, inputs, admitted):
    cid = candidate["candidate_id"]
    coverage = _inference_coverage(candidate, inputs, admitted)
    market = inputs["market"]
    account = deepcopy(inputs["account"])
    # Exact scalars returned by the frozen R1 config_adapter. RAW equal q is
    # owned by the policy, not by an invented engine single-name limit.
    _require(account.get("max_weight") == 1. and account.get("max_positions") == 20
             and account.get("max_invested") == 1. and account.get("capacity_fraction") is None,
             "SIX_PATH_FROZEN_ACCOUNT_SCALARS_CHANGED")
    kwargs = deepcopy(inputs["account_source_kwargs"])
    _require(kwargs.get("entitlement_enabled") is True, "SIX_PATH_EXPLICIT_CA_ACCOUNT_BINDING_REQUIRED")
    allowed = {"events", "known_at", "unsupported", "entitlement_enabled", "entitlement_events",
               "entitlement_security_tickers", "entitlement_source_binding"}
    _require(set(kwargs) <= allowed, "SIX_PATH_UNREGISTERED_ACCOUNT_OVERRIDE")
    kwargs.update(descriptive_evaluation_authority=admitted,
                  execution_friction=candidate["execution_friction"])
    if cid in PATH_IDS[:4]:
        holder = {}
        def factory(*args, **kw):
            holder["overlay"] = FinalActionOverlay(*args, **kw,
                action_packets=inputs["action_packets"], resource_decoder=decode_resource_proposals,
                sid_by_key=inputs["sid_by_key"])
            return holder["overlay"]
        result, frames = replay.execute_market(market, [candidate], inputs["packets"],
            inputs["top"], inputs["qualified"], inputs["vol"], account,
            stock_present=inputs["stock_present"], raw_selector_present=inputs["raw_selector_present"],
            policy_factory=factory, **kwargs)
        frames["learned_action_decisions"] = pd.DataFrame(holder["overlay"].action_audit)
    else:
        ticker = candidate["benchmark_contract"]["ticker"]
        _require(tuple(market.tickers) == (ticker,), "SIX_PATH_EXACT_ETF_MARKET_REQUIRED")
        account.update(max_weight=1., max_positions=1, max_invested=1.)
        def buy_hold(j, ctx):
            authority.require_descriptive_decision(admitted, ctx.signal_date, cid)
            return TargetDecision(np.ones((1, 1)) if j == 0 else np.zeros((1, 1)),
                                  explicit_mask=np.full((1, 1), j == 0, bool))
        kwargs["corporate_actions"] = kwargs.pop("events", ())
        kwargs["corporate_action_known_at"] = kwargs.pop("known_at", None)
        kwargs["unsupported_events"] = kwargs.pop("unsupported", ())
        result = run_continuous_account(market, [cid], buy_hold, account, **kwargs)
        frames = None
    frames = _dual_nav_frames(result, frames)
    if coverage is not None:
        frames["inference_coverage"] = inputs["inference_evidence"][cid]["support"].assign(path_id=cid)
    return frames


def _schedule_keys(schedule):
    windows = schedule.get("windows", [])
    _require(schedule.get("task_id") in authority.six_path_tasks() and schedule.get("path_ids") == list(PATH_IDS)
             and 1 <= len(windows) <= 101 and len({w["window_id"] for w in windows}) == len(windows)
             and schedule.get("account_paths") == len(windows)*6 <= MAX_PATHS
             and schedule.get("seed") == SEED, "SIX_PATH_SCHEDULE_OR_BUDGET_CHANGED")
    _require(windows[0].get("kind") == "MAIN" and windows[0]["window_id"] == "MAIN"
             and all(w.get("kind") == "RANDOM" and w["window_id"] == f"RANDOM_{i:03d}"
                     for i, w in enumerate(windows[1:], 1))
             and [w["first_execution_date"] for w in windows] ==
                 sorted(set(w["first_execution_date"] for w in windows)),
             "SIX_PATH_MAIN_SIX_BEFORE_RANDOM_REQUIRED")
    if schedule.get("task_id") == authority.CONSENSUS_TASK:
        ref = schedule.get("parent_schedule_ref")
        _require(isinstance(ref, dict) and ref.get("sha256") == authority.CONSENSUS_PARENT_SCHEDULE_SHA256,
                 "CONSENSUS_EXACT_PARENT_SCHEDULE_REQUIRED")
        parent = authority._document(ref)
        _require(parent.get("task_id") == authority.AGGREGATE_TASK
                 and all(schedule.get(k) == v for k,v in parent.items() if k not in ("task_id", "as_of")),
                 "CONSENSUS_FROZEN_SCHEDULE_CHANGED")
    if schedule.get("task_id") in authority.pool_descendant_tasks():
        root = authority.pool_descendant_schedule(schedule.get("parent_schedule_ref"))
        _require(windows == root["windows"] and schedule.get("as_of") == root["as_of"],
                 "POOL_DESCENDANT_FROZEN_SCHEDULE_CHANGED")
    return [(w["window_id"], cid) for w in windows for cid in PATH_IDS]


def execute_schedule(schedule, candidates, *, authority_for_window, inputs_for_window,
                     record_event, consume_result, prior_events=()):
    """One pass only; admission precedes inputs and every attempt spends a slot."""
    _validate_policy_rows(candidates)
    keys = _schedule_keys(schedule)
    windows = schedule["windows"]
    started = [(e["window_id"], e["candidate_id"]) for e in prior_events if e["event"] == "STARTED"]
    ended = [(e["window_id"], e["candidate_id"]) for e in prior_events if e["event"] in ("COMPLETE", "FAILED")]
    _require(started == keys[:len(started)] and len(set(started)) == len(started)
             and len(set(ended)) == len(ended) and set(started) == set(ended),
             "SIX_PATH_DUPLICATE_OR_OUTSTANDING_ATTEMPT_NO_RETRY")
    reports = []
    for w in windows:
        if all((w["window_id"], cid) in started for cid in PATH_IDS):
            continue
        admitted = authority.load_descriptive_authority(authority_for_window(w))
        _require(admitted.task_id == schedule["task_id"] and admitted.window_id == w["window_id"]
                 and str(admitted.start.date()) == w["start"]
                 and str(admitted.end.date()) == w["end"], "SIX_PATH_WINDOW_ADMISSION_MISMATCH")
        bound_inputs = inputs_for_window(w, admitted)
        for c in candidates:
            cid = c["candidate_id"]
            if (w["window_id"], cid) in started:
                continue
            record_event(dict(event="STARTED", window_id=w["window_id"], candidate_id=cid, path_units=1))
            stage = "INPUT_PROJECTION"
            try:
                data = bound_inputs[cid] if cid in PATH_IDS[4:] else bound_inputs["stocks"]
                dates = data["market"].dates
                _require(len(dates) >= 2 and dates[0] == admitted.start and dates[-1] == admitted.end
                         and str(dates[1].date()) == w["first_execution_date"]
                         and data["market"].signal_mask[0], "SIX_PATH_SIGNAL_EXECUTION_CALENDAR_CHANGED")
                stage = "ACCOUNT_EXECUTION"
                frames = _execute_path(c, data, admitted)
                stage = "QUALIFICATION"
                gate = _qualification(frames)
                stage = "DESCRIPTIVE_METRICS"
                metrics = descriptive_metrics(c, frames) if gate["all_passed"] else None
                report = dict(window_id=w["window_id"], candidate_id=cid,
                    status="QUALIFIED_DESCRIPTIVE" if gate["all_passed"] else "NOT_TESTABLE",
                    qualification=gate, metrics=metrics, real_fit=0)
                stage = "RESULT_STORAGE"
                consume_result(w, c, frames, report)
                terminal = "COMPLETE"
            except Exception as exc:
                report = dict(window_id=w["window_id"], candidate_id=cid,
                    status="FAILED_ENGINEERING", error_stage=stage, error_type=type(exc).__name__,
                    error=str(exc), scientific_retry=0, real_fit=0, metrics=None)
                terminal = "FAILED"
            # Terminal journal I/O errors stop the writer; never append a
            # contradictory second terminal after a partly persisted COMPLETE.
            record_event(dict(event=terminal, **report))
            reports.append(report)
    return reports


_DURABLE_EVENTS = {"STARTED": "ACCOUNT_PATH_ATTEMPT_STARTED",
                   "COMPLETE": "ACCOUNT_PATH_COMPLETE", "FAILED": "ACCOUNT_PATH_FAILED"}


def _sync(path):
    with path.open("ab") as stream:
        stream.flush()
        os.fsync(stream.fileno())


def execute_durable(run, schedule, candidates, *, authority_for_window, inputs_for_window,
                    expected_run_config_sha256):
    """Store/resume this task in an existing managed run under the owner lock.

    Creates no run, authority, model or account engine. A partly written attempt
    is never executed again. A complete audited result may be recovered without
    replay; otherwise interruption is a terminal engineering failure.
    """
    _validate_policy_rows(candidates)
    keys = _schedule_keys(schedule)
    run = Path(run).resolve()
    assert_write_path(run / "ACCOUNT_PATH_LOG.jsonl", "backtest")
    task = schedule["task_id"]
    _require(task in authority.six_path_tasks(), "SIX_PATH_DURABLE_EXACT_A_TASK_REQUIRED")
    _require(run.is_dir() and run.parent.name == task, "SIX_PATH_EXISTING_MANAGED_TASK_RUN_REQUIRED")
    config_path = run / "run_config.json"
    _require(config_path.is_file() and sha256(config_path) == expected_run_config_sha256,
             "SIX_PATH_RUN_CONFIG_PIN_CHANGED")
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    _require(cfg.get("strategy_id") == task and cfg.get("research_only") is True
             and cfg.get("broker_action_allowed") is False
             and cfg.get("official_adoption_allowed") is False, "SIX_PATH_MANAGED_RUN_SAFETY_REQUIRED")
    source_sha = sha256(Path(__file__))
    binding = dict(task_id=task, run_config_sha256=expected_run_config_sha256,
        plan_sha256=authority.six_path_plan_sha256(task), controller_sha256=source_sha,
        schedule_sha256=_commit(schedule), candidates_sha256=_commit(candidates),
        account_paths=len(keys), account_paths_max=MAX_PATHS, real_fit=0, scientific_retry=0,
        main_six_terminal_before_random=True, strict_PIT_promotion_eligible=False,
        research_only=True, broker_action_allowed=False, official_adoption_allowed=False)
    binding_path = run / "SIX_PATH_EXECUTION_BINDING.json"
    journal = run / "ACCOUNT_PATH_LOG.jsonl"

    def write(path, payload):
        execution_owner.own_path(run, path)
        write_json_atomic(path, payload)
        _sync(path)

    with execution_owner.continuation_lock(run, source_sha, namespace=task):
        if binding_path.exists():
            _require(json.loads(binding_path.read_text(encoding="utf-8")) == binding,
                     "SIX_PATH_DURABLE_BINDING_CHANGED")
        else:
            _require(not journal.exists(), "SIX_PATH_JOURNAL_WITHOUT_BINDING")
            write(binding_path, binding)
        binding_sha = sha256(binding_path)
        slots = {key: i for i, key in enumerate(keys, 1)}
        window_rows = {w["window_id"]: w for w in schedule["windows"]}
        policy_rows = {c["candidate_id"]: c for c in candidates}

        def folder(key):
            return execution_owner.own_path(run, run / "ledgers/stateful" / f"attempt_{slots[key]:04d}")

        def identity(key):
            return dict(window_id=key[0], candidate_id=key[1], attempt_ordinal=slots[key],
                        binding_sha256=binding_sha)

        def result_from_ref(key, ref):
            path = execution_owner.own_path(run, ref["path"])
            _require(path.parent == folder(key) and path.name in ("audit.json", "failure.json")
                     and sha256(path) == ref["sha256"], "SIX_PATH_RESULT_AUDIT_CUSTODY_CHANGED")
            audit = json.loads(path.read_text(encoding="utf-8"))
            _require(all(audit.get(k) == v for k, v in identity(key).items()),
                     "SIX_PATH_RESULT_IDENTITY_CHANGED")
            for name, artifact in audit.get("artifacts", {}).items():
                target = execution_owner.own_path(run, artifact["path"])
                _require(target == folder(key) / (name + ".parquet")
                         and sha256(target) == artifact["sha256"], "SIX_PATH_RESULT_ARTIFACT_CHANGED")
            report = audit["report"]
            _require((report.get("window_id"), report.get("candidate_id")) == key,
                     "SIX_PATH_RESULT_REPORT_IDENTITY_CHANGED")
            if path.name == "audit.json":
                _require(report.get("status") in ("QUALIFIED_DESCRIPTIVE", "NOT_TESTABLE")
                         and "daily" in audit.get("artifacts", {})
                         and audit.get("window") == window_rows[key[0]]
                         and audit.get("candidate") == policy_rows[key[1]],
                         "SIX_PATH_COMPLETE_RESULT_CONTRACT_CHANGED")
            else:
                _require(report.get("status") == "FAILED_ENGINEERING"
                         and report.get("metrics") is None, "SIX_PATH_FAILURE_RESULT_CONTRACT_CHANGED")
            return report

        history = execution_owner.events(run, "ACCOUNT_PATH_LOG.jsonl")
        prior = []
        pending = None
        for event in history:
            key = (event.get("window_id"), event.get("candidate_id"))
            _require(key in slots and all(event.get(k) == v for k, v in identity(key).items()),
                     "SIX_PATH_JOURNAL_CUSTODY_CHANGED")
            kind = next((k for k, v in _DURABLE_EVENTS.items() if event.get("event") == v), None)
            _require(kind is not None, "SIX_PATH_UNKNOWN_JOURNAL_EVENT")
            if kind == "STARTED":
                _require(pending is None and len(prior)//2 < len(keys)
                         and key == keys[len(prior)//2], "SIX_PATH_JOURNAL_ORDER_OR_DUPLICATE")
                pending = key
            else:
                _require(pending == key, "SIX_PATH_JOURNAL_TERMINAL_WITHOUT_START")
                report = result_from_ref(key, event["result_ref"])
                _require((kind == "FAILED") == (report.get("status") == "FAILED_ENGINEERING"),
                         "SIX_PATH_JOURNAL_RESULT_STATUS_CHANGED")
                pending = None
            prior.append(dict(event=kind, window_id=key[0], candidate_id=key[1]))

        def record(event):
            key = (event["window_id"], event["candidate_id"])
            kind = event["event"]
            durable = dict(event=_DURABLE_EVENTS[kind], **identity(key), scientific_retry=0, real_fit=0)
            if kind == "STARTED":
                durable["path_units"] = 1
            else:
                target = folder(key) / ("audit.json" if kind == "COMPLETE" else "failure.json")
                if kind == "FAILED":
                    _require(not target.exists(), "SIX_PATH_FAILURE_EVIDENCE_ALREADY_EXISTS")
                    write(target, dict(**identity(key), report={k: v for k, v in event.items() if k != "event"}, artifacts={}))
                durable["result_ref"] = dict(path=str(target), sha256=sha256(target))
                result_from_ref(key, durable["result_ref"])
            replay._append(journal, durable)
            _sync(journal)

        if pending is not None:
            key = pending
            complete, failure = folder(key) / "audit.json", folder(key) / "failure.json"
            if failure.exists():
                report = result_from_ref(key, dict(path=str(failure), sha256=sha256(failure)))
                replay._append(journal, dict(event=_DURABLE_EVENTS["FAILED"], **identity(key),
                    result_ref=dict(path=str(failure), sha256=sha256(failure)), scientific_retry=0, real_fit=0))
                _sync(journal)
                terminal = "FAILED"
            else:
                try:
                    report = result_from_ref(key, dict(path=str(complete), sha256=sha256(complete)))
                    terminal = "COMPLETE"
                except Exception as exc:
                    terminal = "FAILED"
                    report = dict(window_id=key[0], candidate_id=key[1], status="FAILED_ENGINEERING",
                        error_stage="INTERRUPTED_ATTEMPT_NO_RETRY", error_type=type(exc).__name__,
                        error=str(exc), scientific_retry=0, real_fit=0, metrics=None)
                record(dict(event=terminal, **report))
            prior.append(dict(event=terminal, window_id=key[0], candidate_id=key[1]))

        def consume(w, candidate, frames, report):
            key = (w["window_id"], candidate["candidate_id"])
            target = folder(key)
            target.mkdir(parents=True, exist_ok=True)
            artifacts = {}
            for name, frame in frames.items():
                _require(isinstance(name, str) and name.replace("_", "").isalnum()
                         and isinstance(frame, pd.DataFrame), "SIX_PATH_RESULT_FRAME_REQUIRED")
                path = execution_owner.own_path(run, target / (name + ".parquet"))
                _require(not path.exists(), "SIX_PATH_RESULT_OVERWRITE_FORBIDDEN")
                clocks = {}
                for col in ("date", "signal_date", "execution_date", "session"):
                    if col in frame and not frame.empty:
                        dates = pd.to_datetime(frame[col]).dropna()
                        if not dates.empty:
                            _require(dates.between(pd.Timestamp(w["start"]), pd.Timestamp(w["end"])).all(),
                                     "SIX_PATH_OUTPUT_CLOCK_OUTSIDE_ADMITTED_WINDOW")
                            clocks[col] = dict(min=str(dates.min()), max=str(dates.max()))
                assert_write_path(path, "backtest")
                frame.to_parquet(path, index=False)
                _sync(path)
                artifacts[name] = dict(path=str(path), sha256=sha256(path), rows=len(frame),
                    schema={str(k): str(v) for k, v in frame.dtypes.items()}, clock_bounds=clocks)
            write(target / "audit.json", dict(**identity(key), window=w, candidate=candidate,
                report=report, artifacts=artifacts, real_fit=0, scientific_retry=0))

        execute_schedule(schedule, candidates, authority_for_window=authority_for_window,
            inputs_for_window=inputs_for_window, record_event=record, consume_result=consume, prior_events=prior)
        all_events = execution_owner.events(run, "ACCOUNT_PATH_LOG.jsonl")
        terminals = [e for e in all_events if e["event"] in (_DURABLE_EVENTS["COMPLETE"], _DURABLE_EVENTS["FAILED"])]
        reports = [result_from_ref((e["window_id"], e["candidate_id"]), e["result_ref"]) for e in terminals]
        _require(len(reports) == len(keys), "SIX_PATH_COMPLETION_NOT_ALL_SLOTS_TERMINAL")
        write(run / "SIX_PATH_COMPLETION.json", dict(status="ALL_FROZEN_ATTEMPTS_TERMINAL",
            binding_sha256=binding_sha, scheduled_attempts=len(keys), terminal_attempts=len(reports),
            qualified_descriptive=sum(r["status"] == "QUALIFIED_DESCRIPTIVE" for r in reports),
            not_testable=sum(r["status"] == "NOT_TESTABLE" for r in reports),
            failed_engineering=sum(r["status"] == "FAILED_ENGINEERING" for r in reports),
            scientific_retry=0, real_fit=0, strict_PIT_promotion_eligible=False, reports=reports))
        return reports


def nav_descriptive_metrics(dates, nav, initial_cash=3000.):
    """Original descriptive NAV arithmetic, shared across native account units."""
    dates = pd.DatetimeIndex(pd.to_datetime(dates))
    nav = np.asarray(nav, dtype=float)
    _require(nav.ndim == 1 and len(nav) == len(dates) and len(nav) > 0
             and dates.is_monotonic_increasing and not dates.has_duplicates
             and np.isfinite(nav).all() and (nav > 0).all()
             and np.isfinite(initial_cash) and initial_cash > 0,
             "DESCRIPTIVE_NAV_INPUT_INVALID")
    r = nav / np.r_[initial_cash, nav[:-1]] - 1.
    n = len(r)
    std = float(np.std(r, ddof=1)) if n > 1 else 0.
    downside = float(np.sqrt(np.mean(np.minimum(r, 0.)**2)))
    annual = float((nav[-1]/initial_cash)**(252./n)-1.)
    dd = nav / np.maximum.accumulate(np.r_[initial_cash, nav])[1:] - 1.
    run = longest = 0
    for v in dd:
        run = run+1 if v < 0 else 0
        longest = max(longest, run)
    monthly = {}; previous = initial_cash
    d = pd.DataFrame({"date": dates, "nav": nav})
    for month, group in d.groupby(d.date.dt.to_period("M"), sort=True):
        end = float(group.nav.iloc[-1]); monthly[str(month)] = end/previous-1.; previous = end
    return dict(cumulative_return=float(nav[-1]/initial_cash-1.), MaxDD=float(dd.min()),
        annualized_geometric_return=annual,
        annualized_volatility=std*np.sqrt(252.) if n > 1 else None,
        Sharpe_rf0=float(np.sqrt(252.)*np.mean(r)/std) if std > 0 else None,
        Sortino_MAR0=float(np.sqrt(252.)*np.mean(r)/downside) if downside > 0 else None,
        Calmar=annual/abs(float(dd.min())) if dd.min() < 0 else None,
        drawdown_duration_max_sessions=longest, daily_positive_fraction=float(np.mean(r > 0)),
        calendar_month_return=monthly)


def descriptive_metrics(candidate, frames):
    """Reuse account/action summaries; add only the plan's descriptive measures."""
    metrics = _full_metrics(candidate, frames)
    d = frames["daily"].loc[frames["daily"].path_id.eq(candidate["candidate_id"])].sort_values("date")
    metrics.update(nav_descriptive_metrics(d.date, d.TOTAL_ECONOMIC_NAV, initial_cash=3000.))
    results = frames["execution_results"]
    metrics.update(rejected_execution_count=int(results.status.eq("REJECTED").sum()),
        execution_status_counts={str(k): int(v) for k, v in results.status.value_counts().items()},
        initial_cash_usd=3000., initial_cash_session_included=True,
        inference="DESCRIPTIVE_ONLY_NO_WINNER_SELECTION")
    learned = frames.get("learned_action_decisions", pd.DataFrame())
    metrics["action_consumer_status_counts"] = ({str(k): int(v) for k, v in
        learned.loc[learned.path_id.eq(candidate["candidate_id"]), "consumer_status"].value_counts().items()}
        if not learned.empty else {})
    return metrics


def matched_daily_comparison(daily, candidate_id, benchmark_id):
    """Exact same date keys; no dropping unmatched observations or fees."""
    def values(cid):
        x = daily.loc[daily.path_id.eq(cid)].sort_values("date")
        _require(len(x) > 0 and not x.date.duplicated().any(), "SIX_PATH_COMPARISON_KEYS_INVALID")
        return x.date.to_numpy(), x.TOTAL_ECONOMIC_NAV.to_numpy(float)
    date, nav = values(candidate_id); bd, bn = values(benchmark_id)
    _require(np.array_equal(date, bd) and np.isfinite(nav).all() and np.isfinite(bn).all()
             and (nav > 0).all() and (bn > 0).all(), "SIX_PATH_MATCHED_INTERVAL_REQUIRED")
    r = nav / np.r_[3000., nav[:-1]]-1.; b = bn / np.r_[3000., bn[:-1]]-1.; excess = r-b
    std = float(np.std(excess, ddof=1)) if len(r) > 1 else 0.
    variance = float(np.var(b, ddof=1)) if len(b) > 1 else 0.
    beta = float(np.cov(r, b, ddof=1)[0, 1]/variance) if variance > 0 else None
    return dict(candidate_id=candidate_id, benchmark_id=benchmark_id,
        net_return_difference=float((nav[-1]-bn[-1])/3000.),
        daily_excess_positive_fraction=float(np.mean(excess > 0)),
        tracking_error_annualized=std*np.sqrt(252.) if len(r) > 1 else None,
        information_ratio=float(np.sqrt(252.)*np.mean(excess)/std) if std > 0 else None,
        descriptive_OLS_beta=beta,
        descriptive_OLS_daily_alpha=float(np.mean(r)-beta*np.mean(b)) if beta is not None else None,
        overlapping_starts_not_independent_trials=True)


def random_start_summary(reports, schedule, candidate_id, benchmark_id):
    by_key = {(r["window_id"], r["candidate_id"]): r for r in reports}
    differences = []; unavailable = []
    for w in schedule["windows"]:
        if w["kind"] != "RANDOM":
            continue
        a, b = (by_key.get((w["window_id"], cid)) for cid in (candidate_id, benchmark_id))
        if not a or not b or any(r.get("status") != "QUALIFIED_DESCRIPTIVE" for r in (a, b)):
            unavailable.append(w["window_id"]); continue
        differences.append(a["metrics"]["cumulative_return"]-b["metrics"]["cumulative_return"])
    x = np.asarray(differences, float)
    _require(np.isfinite(x).all(), "SIX_PATH_RANDOM_RETURN_INVALID")
    return dict(candidate_id=candidate_id, benchmark_id=benchmark_id, matched_qualified_starts=len(x),
        unqualified_or_missing_starts=unavailable, wins=int(np.sum(x > 0)), ties=int(np.sum(x == 0)),
        losses=int(np.sum(x < 0)), win_rate=float(np.mean(x > 0)) if len(x) else None,
        excess_median=float(np.median(x)) if len(x) else None,
        excess_p10=float(np.quantile(x, .1)) if len(x) else None,
        excess_p90=float(np.quantile(x, .9)) if len(x) else None,
        excess_min=float(x.min()) if len(x) else None, excess_max=float(x.max()) if len(x) else None,
        inference="DESCRIPTIVE_OVERLAPPING_STARTS_NO_INDEPENDENT_TRIAL_OR_WINNER_CLAIM")
