"""Single R1 path with bounded historical qualification; no broker or fitting."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import time
import tracemalloc
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

import exchange_calendars
import numpy as np
import pandas as pd

from scripts.common.storage_paths import resolve
from .contracts import Contract, Fees, Invalid, LifecycleEvent, Mark, Opportunity, Quote, TEMPLATE, clock, require
from .expression import evaluate, paired_summary, payoff_at_expiry


def synthetic_inputs() -> dict:
    """Small explicitly artificial fixture, never actual A2 signals or prices."""
    decision = clock("2025-03-03")
    exit_at = clock("2025-03-03", 5)
    opportunities, contracts, quotes, marks, events = [], [], [], [], []
    for name in ("good", "missing_exit", "budget", "future_signal", "indicative", "adjustment"):
        uid = "SYNTHETIC:" + name
        iso = decision.isoformat()
        o = Opportunity(name, uid, iso, iso, iso, "SYNTHETIC_RAW_A2_SHAPE_NOT_ACTUAL_SIGNAL", 1, 1.,
                        "2024-12-31T20:00:00Z", "SYNTHETIC_FOLD", 100., iso,
                        capital=600. if name == "budget" else 10000.)
        if name == "future_signal":
            o = replace(o, signal_available_at=(decision + timedelta(seconds=1)).isoformat())
        opportunities.append(o)
        c = Contract(uid + "-CALL", uid, 100., "2025-04-17", "2025-04-17T20:00:00Z", iso)
        contracts.append(c)
        for at, is_exit in ((decision, False), (decision + timedelta(seconds=1), False),
                            (exit_at + timedelta(seconds=1), True)):
            stamp = at.isoformat()
            for option in (False, True):
                if option and name == "missing_exit" and is_exit:
                    continue
                q = Quote(c.contract_id if option else uid, uid, stamp, stamp, "2026-09-13T00:00:00Z",
                          (8. if is_exit else 5.8) if option else (103. if is_exit else 99.9),
                          (8.2 if is_exit else 6.) if option else (103.1 if is_exit else 100.),
                          1000., 1000., 103. if is_exit else 100., stamp,
                          size_unit="CONTRACTS" if option else "SHARES")
                if option:
                    q = replace(q, delta=.5, delta_at=stamp, delta_source="SYNTHETIC", delta_kind="PROVIDER_HISTORICAL",
                                delta_unit="PER_UNDERLYING_SHARE", delta_style="AMERICAN", iv=.3)
                    if name == "indicative":
                        q = replace(q, quote_kind="LAST", evidence_grade="INDICATIVE_OR_AGGREGATE")
                quotes.append(q)
        for i in range(21):
            stamp = clock("2025-03-03", i).isoformat()
            marks.append(Mark(uid, stamp, stamp, 100 + .6*i))
        if name == "adjustment":
            events.append(LifecycleEvent(c.contract_id, clock("2025-03-03", 2).isoformat(), "DELIVERABLE_ADJUSTED"))
    return {"opportunities": tuple(opportunities), "contracts": tuple(contracts), "quotes": tuple(quotes),
            "marks": tuple(marks), "events": tuple(events)}


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def model_scenario() -> list[dict]:
    """Existing European formula, hypothetical zero rate/dividend; never R1 prices/Delta."""
    from scripts.v22.v22_037_r1_option_synthetic_iv_solver_research_only import black_scholes_price
    p0 = black_scholes_price("CALL", 100, 100, 45/365, 0, 0, .4)
    ps = black_scholes_price("CALL", 103, 100, 45/365, 0, 0, .4)
    pt = black_scholes_price("CALL", 103, 100, 38/365, 0, 0, .4)
    p1 = black_scholes_price("CALL", 103, 100, 38/365, 0, 0, .1)
    return [{"evidence_grade": "MODEL_SCENARIO", "model": "EUROPEAN_ZERO_RATE_ZERO_DIVIDEND",
             "spot_before": 100, "spot_after": 103, "strike": 100, "iv_before": .4, "iv_after": .1,
             "dte_before": 45, "dte_after": 38, "premium_before": p0, "premium_after": p1,
             "call_pnl_per_share": p1-p0, "stock_pnl_per_share": 3,
             "ordered_spot_effect": ps-p0, "ordered_time_effect": pt-ps, "ordered_iv_effect": p1-pt,
             "limitation": "ORDER_DEPENDENT_MECHANISM_DEMO_NOT_AMERICAN_CALIBRATION_OR_ALPHA"}]


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(dict.fromkeys(k for row in rows for k in row)) or ["status"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _boundary_discovery() -> dict:
    """Bounded filename/stat-only inventory. Does not open even a parquet footer."""
    paths = resolve()
    names = {
        "RAW_TOP20": paths.results_root / "A_VS_A2_QUARTERLY_13F_R1/A2/top20_selections.parquet",
        "OOF": paths.results_root / "A_VS_A2_QUARTERLY_13F_R1/A2/oof_predictions.parquet",
        "TOP40_CHECKPOINT": paths.results_root / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1/raw_a2_top40_membership_checkpoint.parquet",
    }
    return {"status": "NOT_RUN", "reason": "NO_VERIFIED_ISOLATED_PRE2026_INPUT_BINDING",
            "candidates": {k: {"path": str(p), "exists_metadata_only": p.is_file(), "authority": "UNKNOWN"} for k, p in names.items()},
            "missing": ["accepted frozen Top20 identity and safe physical partition", "signal/feature availability and OOF train provenance",
                        "PIT UID/action/price binding and lawful same-clock path", "historical expired contract identities and BBO timestamps"],
            "provider": {"economic_request_budget": 0, "economic_requests_observed_in_this_cli": 0,
                         "account_permissions": "UNKNOWN", "reason": "NO_HISTORY_ONLY_ELIGIBLE_REQUEST",
                         "official_doc": "https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-option-chain.html"}}


def _path_summary(result: dict) -> list[dict]:
    eligible = {r["decision_id"] for r in result["opportunities"] if r["eligible"]}
    rows = []
    for horizon in (5, 20):
        for population in ("ALL_OPPORTUNITIES", "DECISION_OPTION_ELIGIBLE"):
            members = [r for r in result["labels"] if r["horizon"] == horizon and
                       (population == "ALL_OPPORTUNITIES" or r["decision_id"] in eligible)]
            values = [r["absolute_return"] for r in members if r["status"] == "COMPLETE"]
            rows.append({"horizon": horizon, "population": population, "label_rows": len(members),
                         "complete": len(values), "missing": len(members)-len(values),
                         "mean_absolute_return": float(np.mean(values)) if values else None,
                         "positive_fraction": float(np.mean(np.array(values) > 0)) if values else None,
                         "q10": float(np.quantile(values, .1)) if values else None,
                         "median": float(np.median(values)) if values else None,
                         "q90": float(np.quantile(values, .9)) if values else None,
                         "evidence_grade": "SYNTHETIC"})
    return rows


def run(mode: str = "all", output: Path | None = None, input_path: Path | None = None) -> dict:
    started = time.perf_counter()
    tracemalloc.start()
    paths = resolve()
    output = (output or paths.results_root / TEMPLATE).resolve()
    require(paths.results_root in output.parents or paths.cache_root in output.parents, "OUTPUT_ROOT_NOT_AUTHORIZED")
    require(mode in {"all", "synthetic", "local"}, "INVALID_MODE")
    source_paths = [Path(__file__).with_name(n) for n in ("contracts.py", "expression.py", "cli.py")]
    source_paths += [paths.repo_root / p for p in ("scripts/common/storage_paths.py", "scripts/v22/r9a_trade_ledger.py",
                      "fast3/src/fast3/options/moomoo_option_shadow_r1.py", "docs/research_governance/options_expression_pilot_r1.md")]
    source_paths.append(paths.repo_root / "scripts/v22/v22_037_r1_option_synthetic_iv_solver_research_only.py")
    source_paths.append(paths.repo_root / "tests/research/a2/options/test_expression_pilot.py")
    identity = {str(p.relative_to(paths.repo_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    dependencies = {"python": platform.python_version(), "exchange_calendars": exchange_calendars.__version__,
                    "numpy": np.__version__, "pandas": pd.__version__}
    inputs = synthetic_inputs() if mode in {"all", "synthetic"} else None
    input_identity = hashlib.sha256(_canonical({k: [asdict(x) for x in v] for k, v in inputs.items()})).hexdigest() if inputs else None
    key = hashlib.sha256(_canonical({"code_and_contract": identity, "input": input_identity, "mode": mode,
                                     "input_request": str(input_path) if input_path else None,
                                     "dependencies": dependencies})).hexdigest()
    manifest_path = output / "run_manifest.json"
    prior_runs = []
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Only task-owned synthetic engineering output can be regenerated after a
        # repair; real payloads are never admitted here. Preserve attempt identities.
        require(old.get("task_id") == TEMPLATE and old.get("mode") == mode and
                old.get("input_sha256") == input_identity and
                old.get("research_registration") == "TASK_DRAFT_NO_RECEIPT" and
                old.get("economic_verdict") == "NOT_IDENTIFIABLE", "OUTPUT_IDENTITY_CHANGED_PRESERVE_EXISTING_RUN")
        prior_runs = old.get("prior_engineering_runs", [])
        if old["run_identity"] != key:
            prior_runs = prior_runs + [{"run_identity": old["run_identity"], "code_and_contract_sha256": old["code_and_contract_sha256"],
                                       "artifact_sha256": old["artifact_sha256"], "reason": "ENGINEERING_REPAIR_SAME_SYNTHETIC_INPUT"}]
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"task_id": TEMPLATE, "run_identity": key, "code_and_contract_sha256": identity,
                "input_sha256": input_identity, "mode": mode, "python": platform.python_version(),
                "executable": __import__('sys').executable, "exchange_calendars": exchange_calendars.__version__,
                "dependencies": dependencies,
                "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=paths.repo_root, capture_output=True, text=True, check=True).stdout.strip(),
                "git_branch": subprocess.run(["git", "branch", "--show-current"], cwd=paths.repo_root, capture_output=True, text=True, check=True).stdout.strip(),
                "research_registration": "TASK_DRAFT_NO_RECEIPT", "economic_verdict": "NOT_IDENTIFIABLE",
                "account_executability": "NOT_RUN", "account_missing": ["capital", "risk budget", "permissions", "confirmed fees", "exercise policy"],
                "holdout_exposure": {"historical_A2": "ALREADY_EXPOSED", "new_global_read_count": "UNKNOWN",
                                     "this_cli_real_economic_payload_opens": 0},
                "model_effort_runtime_verification": "UNAVAILABLE_NO_SWITCH_CLAIM", "files": []}
    manifest["prior_engineering_runs"] = prior_runs
    logs = []
    if inputs:
        start = time.perf_counter()
        result = evaluate(**inputs)
        summary = paired_summary(result)
        stressed = evaluate(**inputs, fees=Fees(option_slippage=.1, stock_slippage=.01))
        costs = []
        for base, stress in zip(result["outcomes"], stressed["outcomes"]):
            costs.append({"decision_id": base["decision_id"], "arm": base["arm"], "base_wealth": base["net_wealth"],
                          "adverse_wealth": stress["net_wealth"], "evidence_grade": "SYNTHETIC"})
        for name, rows in {**result, "pairs": summary["pairs"], "comparison": summary["comparisons"],
                           "stock_path_summary": _path_summary(result), "cost_sensitivity": costs,
                           "terminal_arithmetic": [{"evidence_grade": "SYNTHETIC", "spot": 103, "strike": 100,
                                                    "premium": 6, "multiplier": 100, "pnl": payoff_at_expiry(103,100,6),
                                                    "usage": "TERMINAL_ARITHMETIC_NOT_R1_EXIT"}]}.items():
            filename = f"synthetic_{name}.csv"
            _write_csv(output / filename, rows)
            manifest["files"].append(filename)
        _write_csv(output / "model_scenario.csv", model_scenario())
        manifest["files"].append("model_scenario.csv")
        manifest["synthetic"] = {k: v for k, v in summary.items() if k != "pairs"}
        manifest["synthetic"]["status"] = "COMPLETED_ENGINEERING_ONLY"
        logs.append(f"synthetic evaluate/compare/write seconds={time.perf_counter()-start:.6f}; adapter=evaluate; opportunities={len(result['opportunities'])}")
    if mode in {"all", "local"}:
        manifest["local"] = _boundary_discovery()
        logs.append("local: bounded candidate filename stat only; dependent stock and option payload reads NOT_RUN")
    if input_path is not None:
        # Do not resolve, stat, hash, inspect schema, or open an unbound input.
        manifest["input_rejection"] = "UNBOUND_INPUT_REJECTED_BEFORE_OPEN"
        logs.append("intentional boundary case: explicit unbound input rejected before open")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    manifest["performance"] = {"wall_seconds": time.perf_counter()-started, "python_traced_peak_bytes": peak,
                               "rss_peak": "UNKNOWN", "workers": 1,
                               "optimization": "cached XNYS schedule and per-session open/close bounds; one worker"}
    manifest["artifact_sha256"] = {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in manifest["files"]}
    manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "run.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
    return manifest


HISTORY_BINDINGS = {
    "reviewed/run_manifest.json": "a90d1d4837d8d18774dde05a66133310abba61e4c2169d6ba2365ea5bacef99c",
    "reviewed/option_evidence/fixed_probe_plan.json": "c71e8ee8701d0c3e8cd339e53eb4ccb4d734c6b519da635328f7e48922b784c5",
    "run_config.json": "df282995330116ccb41c8de173a39f8fc8c7f7501a64673208ec9559a1f1fe74",
}


def _hidden_massive_key() -> str:
    """Local console only; never permit getpass's plaintext fallback."""
    import getpass
    import sys
    import warnings

    require(sys.stdin is not None and sys.stderr is not None and
            sys.stdin.isatty() and sys.stderr.isatty(), "LOCAL_INTERACTIVE_TERMINAL_REQUIRED")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Massive API key (hidden input): ").strip()
    except (getpass.GetPassWarning, OSError):
        raise Invalid("HIDDEN_INPUT_UNAVAILABLE_NO_PLAINTEXT_FALLBACK") from None
    except (EOFError, KeyboardInterrupt):
        raise Invalid("HIDDEN_INPUT_CANCELLED") from None
    require(bool(key), "EMPTY_API_KEY")
    return key


def run_historical_quotes(output: Path | None, config: Path | None = None,
                          input_path: Path | None = None, *, api_key: str | None = None,
                          prompt_api_key: bool = False) -> dict:
    """Run the original nine qualification objects, never an invented pilot.

    A credential enters through local hidden input, a named environment slot or
    an in-memory function argument. It never enters the command line.
    Unqualified provider responses cannot be silently passed to evaluate.
    """
    from datetime import datetime, timezone
    from . import historical_quotes as history
    from . import expression

    require(input_path is None, "UNBOUND_INPUT_REJECTED_BEFORE_OPEN")
    paths = resolve()
    require(output is not None, "EXPLICIT_NEW_RUN_OUTPUT_REQUIRED")
    output = output.resolve()
    require(output.parent == paths.results_root / TEMPLATE / "runs", "NEW_RUN_OUTPUT_BOUNDARY")
    require(output.name and output.name.replace("_", "").replace("-", "").isalnum(), "RUN_NAME_REQUIRED")
    parent = paths.results_root / TEMPLATE / "overnight/20260913T032957JST"
    bindings = HISTORY_BINDINGS
    bound = {}
    for name, digest in bindings.items():
        data = (parent / name).read_bytes()  # Previously bound pre-2026 task metadata only.
        require(hashlib.sha256(data).hexdigest() == digest, "PARENT_BINDING_CHANGED")
        bound[name] = json.loads(data)
    plan = bound["reviewed/option_evidence/fixed_probe_plan.json"]
    original = bound["run_config.json"]
    require(plan["research_identity"] == TEMPLATE and len(plan["selected"]) == 9,
            "ORIGINAL_QUALIFICATION_PLAN_REQUIRED")
    require(original["no_training"] is True, "NO_TRAINING_CONTRACT_REQUIRED")
    source_files = {"cli": Path(__file__), "historical_quotes": Path(history.__file__),
                    "expression": Path(expression.__file__), "contracts": Path(__file__).with_name("contracts.py")}
    sources = {name: {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
               for name, path in source_files.items()}
    cache = paths.cache_root / "options_expression_pilot_r1" / output.name
    specification = {"research_identity": TEMPLATE, "parent_bindings": bindings,
                     "selected": plan["selected"], "provider_probe_request_limit": 12,
                     "total_incremental_request_limit": 1200, "pilot_opportunity_limit": 240,
                     "pilot_plan_count": 0, "pilot_plan_status": plan["pilot_plan_status"],
                     "economic_plan_generation": "AFTER_PROVEN_PROVIDER_COVERAGE_BEFORE_ECONOMIC_OBSERVATIONS",
                     "economic_plan_rule": "MAX_240;MONTH_BALANCED;REMAINDER_MONTH_ASC;WITHIN_MONTH_SHA256_R1_ID_PLUS_DECISION_ID;NO_OUTCOME_OR_EXIT_AVAILABILITY_SELECTION",
                     "signal_availability_semantics": "INHERITED_CLOSE_SIGNAL_NEXT_SESSION_OPEN_HISTORICAL_CONTRACT_NOT_LIVE_PUBLICATION",
                     "cache_root": str(cache), "cache_limit_bytes": 10737418240,
                     "qualification_pages_per_endpoint": 1,
                     "wall_time_limit_seconds": 14400, "source_modules": sources,
                     "authentication_transport": "MASSIVE_QUERY_PARAMETER",
                     "economic_cutoff_exclusive": "2026-01-01", "new_model_fits": 0,
                     "new_template_candidates": 0, "new_parameter_trials": 0,
                     "role": "ENDPOINT_QUALIFICATION_ONLY_NOT_ECONOMIC_REPLAY"}
    config_path = output / "run_config.json"
    require(config is None or config.resolve() == config_path, "UNBOUND_RUN_CONFIG")
    require(not (prompt_api_key and api_key is not None), "MULTIPLE_CREDENTIAL_INPUTS")
    # Prompt before every output write. A local user owns the terminal; the
    # agent must never launch an inaccessible password prompt through its tools.
    if prompt_api_key:
        key, credential_source = _hidden_massive_key(), "LOCAL_HIDDEN_PROMPT"
    elif api_key is not None:
        key, credential_source = api_key.strip(), "EXPLICIT_IN_MEMORY_ARGUMENT"
        require(bool(key), "EMPTY_API_KEY")
    else:
        key = os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
        credential_source = "NAMED_ENVIRONMENT" if key else "UNAVAILABLE"
    credential_available = bool(key)
    output.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        frozen = json.loads(config_path.read_text(encoding="utf-8"))
        require(all(frozen.get(k) == v for k, v in specification.items()), "RUN_CONFIG_CHANGED_PRESERVE_HISTORY")
    else:
        frozen = {**specification, "frozen_at_utc": datetime.now(timezone.utc).isoformat()}
        config_path.write_text(json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
    identity = hashlib.sha256(config_path.read_bytes()).hexdigest()
    manifest_path = output / "run_manifest.json"
    prior = []
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(old["run_identity"] == identity, "RUN_IDENTITY_CHANGED")
        prior = old.get("prior_invocations", [])
        archive_index = len(prior) + 1
        archived = output / "invocations" / f"{archive_index:03d}"
        while archived.exists():  # Preserve any interrupted archive, never delete it.
            archive_index += 1
            archived = output / "invocations" / f"{archive_index:03d}"
        archived.mkdir(parents=True, exist_ok=False)
        previous_files = {}
        for name in ("run_manifest.json", "option_qualification.csv", "qualification_summary.json",
                     "actual_pairs.csv", "qualification_transport_state.json"):
            if (output / name).exists():
                data = (output / name).read_bytes()
                (archived / name).write_bytes(data)
                previous_files[name] = hashlib.sha256(data).hexdigest()
        prior = prior + [{"path": str(archived.relative_to(output)), "artifact_sha256": previous_files}]
    manifest = {"task_id": TEMPLATE, "run_identity": identity, "mode": "real-options",
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "status": "STARTED",
                "executable": __import__("sys").executable, "source_modules": sources,
                "prior_invocations": prior, "original_opportunity_rows": 15000,
                "qualification_objects": 9, "economic_planned": 0,
                "economic_http_requests": 0, "evaluate_calls": 0,
                "economic_replay_status": "NOT_RUN_AWAITING_ENDPOINT_AND_INPUT_QUALIFICATION",
                "economic_verdict": "NOT_IDENTIFIABLE", "required_stage_success": False,
                "account_executability": "NOT_RUN", "production_adoption": "NOT_AUTHORIZED"}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    records = []
    state_path = output / "qualification_transport_state.json"
    for probe in plan["selected"]:
        requests = history.qualification_requests(probe)
        metadata = None
        for request in requests:
            result = history.request_massive_history(api_key=key, probe=probe,
                url=request["url"], params=request["params"], state_path=state_path, cache_root=cache, page_limit=1)
            records.append({"decision_id": probe["decision_id"], "provider": "MASSIVE",
                            "kind": request["kind"], **result})
            if request["kind"] == "contracts":
                metadata = result
        # The contract ticker below is for endpoint qualification only, ordered
        # from metadata without price/exit information. It is never a trade pick.
        candidates = sorted(row["ticker"] for row in (metadata or {}).get("rows", [])
                            if isinstance(row.get("ticker"), str))
        request = None
        for ticker in candidates:
            try:
                request = history.qualification_requests(probe, option_ticker=ticker)[-1]
            except Invalid as exc:
                if str(exc) not in {"OPTION_PROBE_IDENTITY", "OPTION_PROBE_EXPIRY"}:
                    raise
            else:
                break
        if request is not None:
            result = history.request_massive_history(api_key=key, probe=probe,
                url=request["url"], params=request["params"], state_path=state_path, cache_root=cache, page_limit=1)
        else:
            result = {"status": "NOT_TESTABLE_CONTRACT_ID_NOT_ESTABLISHED", "http_requests": 0,
                      "rows": [], "authentication": "UNKNOWN", "entitlement": "UNKNOWN",
                      "page_complete": False}
        records.append({"decision_id": probe["decision_id"], "provider": "MASSIVE",
                        "kind": "option_quotes", **result})
    key = None
    # Reuse qualification/economic result responsibilities. No fake zero-return
    # arms and no empty evaluate call to manufacture an execution receipt.
    public = [{k: v for k, v in row.items() if k != "rows"} | {"row_count": len(row.get("rows", [])),
               "field_names": sorted({field for item in row.get("rows", []) for field in item}),
               "unit_qualification": "UNVERIFIED_PRODUCT_ENDPOINT_DATA_VERSION",
               "identity_qualification": "NOT_ESTABLISHED", "evidence_grade": "UNQUALIFIED"}
              for row in records]
    _write_csv(output / "option_qualification.csv", public)
    (output / "qualification_summary.json").write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    # actual_pairs is an economic table; a status row would be a false pair.
    (output / "actual_pairs.csv").write_text("decision_id,date,arm,increment,evidence_grade\n", encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    manifest.update(status="EXECUTED_QUALIFICATION_BRANCH_ECONOMIC_BLOCKED",
                    http_requests_this_invocation=sum(row.get("http_requests", 0) for row in records),
                    economic_http_requests=len(state.get("attempts", [])),
                    transport_state=state, credential_available=credential_available,
                    credential_source=credential_source, authentication_transport="MASSIVE_QUERY_PARAMETER",
                    qualified_economic_inputs=0, opened_calls=0, closed_calls=0, active_no_trade_calls=0,
                    unresolved_call_positions=0, paired_rows=0, paired_new_york_decision_dates=0,
                    original_opportunities_not_evaluated=15000,
                    blockers=["NO_PROVEN_PROVIDER_BBO_COVERAGE_FOR_ECONOMIC_PLAN",
                              "NO_SYNCHRONOUS_STOCK_OPTION_BBO_QUALIFICATION",
                              "NO_PRODUCT_ENDPOINT_VERSION_UNIT_QUALIFICATION"])
    manifest["other_original_sources"] = {
        "ALPACA": {"historical_quotes_endpoint": "NOT_VERIFIED_NO_GUESSED_REQUEST",
                   "authentication": "UNKNOWN", "economic_http_requests": 0},
        "MOOMOO": {"history_endpoint": "INHERITED_NO_EXPIRED_CHAIN_SUPPORT",
                   "economic_http_requests": 0, "current_snapshot_requested": False}}
    if not manifest["credential_available"]:
        manifest["blockers"].insert(0, "NO_CREDENTIAL_IN_AVAILABLE_NAMED_INJECTION_SLOTS")
    manifest["artifact_sha256"] = {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in ("run_config.json", "option_qualification.csv", "qualification_summary.json", "actual_pairs.csv")}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "synthetic", "local", "real-stock", "real-options", "public-history", "expression-frontier", "spy2024-observed-frontier"), default="all")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input", type=Path, help="Unbound real files are rejected without opening")
    parser.add_argument("--config", type=Path, help="Pinned R1 continuation configuration; real-stock requires full real stage")
    parser.add_argument("--smoke", action="store_true", help="First decision-date wiring check; never full research success")
    parser.add_argument("--coverage", action="store_true", help="Pinned overnight independent-price and missingness continuation")
    parser.add_argument("--prompt-api-key", action="store_true",
                        help="Read Massive key once in a local interactive terminal with echo disabled; never from an argument")
    parser.add_argument("--offline", action="store_true", help="Read public-history cache without network")
    parser.add_argument("--stage", choices=("contract-continuity",))
    parser.add_argument("--source-run", type=Path)
    parser.add_argument("--reference-override", type=Path, help="Explicit SPY trade-basis reference binding")
    parser.add_argument("--recover-failed", action="store_true")
    parser.add_argument("--scenario-file", type=Path, help="Explicit synthetic expression-frontier scenarios")
    args = parser.parse_args(argv)
    try:
        require(args.scenario_file is None or args.mode == "expression-frontier", "SCENARIO_FILE_REQUIRES_FRONTIER")
        require(args.reference_override is None or args.mode == "spy2024-observed-frontier",
                "REFERENCE_OVERRIDE_REQUIRES_OBSERVED")
        if args.mode == "spy2024-observed-frontier":
            require(not (args.stage or args.recover_failed or args.prompt_api_key or args.smoke
                         or args.coverage or args.config or args.input), "OBSERVED_FLAGS_NOT_SUPPORTED")
            require(args.output is not None, "OBSERVED_OUTPUT_REQUIRED")
            from .spy_observed_frontier import run_observed
            print(json.dumps(run_observed(args.output, source_run=args.source_run, offline=args.offline,
                                          reference_override=args.reference_override)))
            return 0
        if args.mode == "expression-frontier":
            require(not (args.stage or args.source_run or args.recover_failed or args.prompt_api_key
                         or args.smoke or args.coverage or args.config or args.input), "FRONTIER_FLAGS_NOT_SUPPORTED")
            from .frontier import run_frontier
            manifest = run_frontier(args.scenario_file, args.output, offline=args.offline)
            print(json.dumps({k: manifest[k] for k in ("run_identity", "status", "source_kind", "scenario_eval_calls",
                "scenario_replay_calls", "real_historical_eval_calls", "execution_network_requests")}))
            return 0
        require(not (args.stage or args.source_run or args.recover_failed) or args.mode == "public-history", "CONTINUITY_REQUIRES_PUBLIC_HISTORY")
        require(not (args.source_run or args.recover_failed) or args.stage == "contract-continuity", "CONTINUITY_STAGE_REQUIRED")
        require(not args.offline or args.mode == "public-history", "OFFLINE_REQUIRES_PUBLIC_HISTORY")
        require(not args.prompt_api_key or args.mode == "real-options", "HIDDEN_KEY_REQUIRES_REAL_OPTIONS")
        if args.mode == "public-history":
            require(not args.smoke and not args.coverage and args.config is None and args.input is None,
                    "PUBLIC_HISTORY_FLAGS_NOT_SUPPORTED")
            if args.stage == "contract-continuity":
                from .contract_continuity import run_contract_continuity
                summary = run_contract_continuity(args.source_run, args.output, offline=args.offline, recover=args.recover_failed)
            else:
                from .public_history import run_public_history
                summary = run_public_history(args.output, offline=args.offline)
            print(json.dumps(summary))
            return 0 if summary["required_stage_success"] else 3
        if args.mode == "real-options":
            require(not args.smoke and not args.coverage, "STOCK_FLAGS_NOT_OPTION_QUALIFICATION")
            manifest = run_historical_quotes(args.output, args.config, args.input, prompt_api_key=args.prompt_api_key)
            print(json.dumps({k: manifest[k] for k in ("run_identity", "status", "economic_http_requests",
                "evaluate_calls", "economic_replay_status", "required_stage_success", "blockers")}))
            return 0 if manifest["required_stage_success"] else 3
        if args.mode == "real-stock":
            if args.coverage:
                from .coverage import run_coverage as run_real_stock
            else:
                from .input_adapter import run_real_stock
            manifest = run_real_stock(args.output, args.config, smoke=args.smoke, input_path=args.input)
            print(json.dumps({k: manifest[k] for k in ("run_identity", "scope", "stock_path_research_status", "required_stage_success", "opportunity_rows")}))
            return 0 if manifest["required_stage_success"] or (args.smoke and manifest["stock_path_research_status"] == "SMOKE_ONLY") else 3
        require(not args.smoke and not args.coverage and args.config is None, "CONTINUATION_FLAGS_REQUIRE_REAL_STOCK_MODE")
        manifest = run(args.mode, args.output, args.input)
    except Invalid as exc:
        print(json.dumps({"status": "REJECTED", "reason": str(exc)}))
        return 2
    print(json.dumps({"run_identity": manifest["run_identity"], "synthetic": manifest.get("synthetic", {}).get("status"),
                      "local": manifest.get("local", {}).get("status"), "input_rejection": manifest.get("input_rejection")}))
    return 2 if args.input else 0


if __name__ == "__main__":
    raise SystemExit(main())
