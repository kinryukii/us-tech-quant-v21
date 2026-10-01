"""Replay the fixed independent decision controls with fresh common accounts."""
from __future__ import annotations

import argparse
import time
import traceback
from datetime import datetime, timezone

from common import ROOT, read, write, sha, clean
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from data_contract import FEATURES, INPUT, load_eval_inputs
from engine_cached import run_replay, PreparedInputs
from engine_v2 import HoldingAwareDecision, OperationalExit
from rl_controls import FrozenRL, ARTIFACTS
import run_replays as shared

CONTROLS = ("reinforce", "reinforce_zero", "ppo", "ppo_zero", "cash")


class CashControl:
    def __call__(self, day, context):
        return HoldingAwareDecision(
            model_decisions={str(t): 0. for t in day.ticker if context.current_units.get(str(t), 0.) > 0},
            raw_model_outputs={"control": "cash", "cash_weight": context.cash_weight})


def initialize_inputs(year):
    if year == 2026:
        from freeze_batch import validate_global_freeze
        validate_global_freeze()
    panel, prices, calendar, operations, metadata = load_eval_inputs(year)
    panel = panel[["signal_date", "ticker", "new_buy_eligible", *FEATURES]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    asofs = shared.clocks(calendar)
    schedule = {d: {str(r.ticker): OperationalExit(str(r.reason), r.known_at, str(r.source_id))
                   for r in operations.loc[(operations.known_at <= asofs[d]) & (operations.effective_date <= d)].itertuples()}
                for d in calendar}
    stage = "validation" if year == 2025 else "final"
    paths = [ROOT / "contract.json", ROOT / "data_contract.py", ROOT / "engine_v2.py", ROOT / "engine_cached.py",
             ROOT / "rl_controls.py", ROOT / "run_control_replays.py", ROOT / "run_replays.py", ROOT / "INPUT_AUDIT.json",
             INPUT / f"eval_{year}" / "features.parquet", INPUT / f"eval_{year}" / "prices.parquet",
             INPUT / f"eval_{year}" / "calendar.parquet", INPUT / f"eval_{year}" / "operational_exits.csv",
             INPUT / f"eval_{year}" / "METADATA.json", ARTIFACTS / "VERIFICATION.json"]
    for method in ["reinforce", "ppo"]:
        directory = ARTIFACTS / f"{stage}_{method}"
        paths += [directory / "learned.pt", directory / "zero.pt", directory / "PRE_FIT.json", directory / "TRAIN_RECEIPT.json"]
    if year == 2026:
        paths.append(ROOT / "GLOBAL_FREEZE.json")
    sources = {str(p): sha(p) for p in paths}
    guard = shared.forbid_fitting()
    # summarize reads only this metadata; no risk/model initialization is needed for controls.
    shared.ENV = dict(year=year, metadata=metadata, guard=guard)
    return dict(panel=panel, prices=prices, calendar=calendar, schedule=schedule, asofs=asofs,
                stage=stage, metadata=metadata, guard=guard, source_sha256=sources,
                prepared=PreparedInputs(prices, calendar, panel))


def run_control(name, env, *, resume=False):
    year = int(env["metadata"]["year"])
    folder = ROOT / f"evaluation_controls_{year}" / name
    if (folder / "DONE.json").exists():
        if not resume:
            raise RuntimeError(f"completed control replay already exists: {name}")
        record = read(folder / "DONE.json")
        for relative, expected in record["ledger_sha256"].items():
            if sha(folder / relative) != expected:
                raise ValueError(f"completed control ledger changed: {relative}")
        return record
    if folder.exists():
        raise RuntimeError("partial control replay preserved; do not silently overwrite")
    folder.mkdir(parents=True)
    spec = dict(strategy_id=name, forecast_id=None, coalition="decision_controls", fusion="none",
                risk="none", optimizer="actor_projection" if name != "cash" else "cash",
                route="decision_control", target_fusion="none")
    if name == "cash":
        actor = CashControl()
        training_receipt = None
    else:
        method = name.removesuffix("_zero")
        actor = FrozenRL(env["stage"], method, zero=name.endswith("_zero"))
        training_receipt = read(ARTIFACTS / f"{env['stage']}_{method}" / "TRAIN_RECEIPT.json")
    write(folder / "FROZEN_BEFORE_REPLAY.json", dict(year=year, control=name,
        initial_cash=1_000_000, cost_bps=10, buy_capacity_fraction=.01, capacity_on_sells=False,
        max_names=20, max_target_weight=.10, max_gross=.95, no_terminal_liquidation=True,
        source_sha256=env["source_sha256"], fit_forbidden=True,
        formal_full_pool_test_allowed=env["metadata"].get("formal_full_pool_test_allowed", False),
        created_utc=datetime.now(timezone.utc).isoformat()))
    start = time.monotonic()
    try:
        with threadpool_limits(limits=1):
            result = run_replay(env["prices"], env["calendar"], env["panel"], actor,
                candidate=name, initial_cash=1_000_000, cost_bps=10,
                max_positions=20, max_weight=.10, max_invested=.95,
                capacity_fraction=.01, capacity_on_sells=False,
                signal_start=env["metadata"]["signal_start"], signal_end=env["metadata"]["signal_end"],
                signal_asof=env["asofs"], operational_exits_by_signal=env["schedule"],
                prepared_inputs=env["prepared"])
        for ledger in shared.LEDGERS:
            getattr(result, ledger).to_parquet(folder / f"{ledger}.parquet", index=False, compression="zstd")
        write(folder / "metadata.json", result.metadata)
        summary = shared.summarize(result, spec, time.monotonic()-start)
        daily = result.daily
        summary.update(
            certified_terminal_nav=float(daily.certified_nav.iloc[-1]) if np.isfinite(daily.certified_nav.iloc[-1]) else None,
            uncertified_valuation_days=int(daily.certified_nav.isna().sum()),
            headline_return_and_drawdown_basis="indicative price-index NAV; certification gaps separately shown",
            entire_valuation_path_certified=bool(daily.certified_nav.notna().all()),
            maximum_actual_gross=float(daily.gross_exposure.max()),
            maximum_target_committed_weight=float(result.target_decisions.total_signal_committed_weight.max()) if len(result.target_decisions) else 0.,
            known_glw_input_conflict_rows=env["metadata"].get("known_glw_conflict_rows", 0),
            training_receipt_sha256=sha(ARTIFACTS / f"{env['stage']}_{name.removesuffix('_zero')}" / "TRAIN_RECEIPT.json") if training_receipt else None,
            training_parameter_update_steps=0 if name.endswith("_zero") or name == "cash" else training_receipt["parameter_update_steps"],
            matched_initial_state_sha256=training_receipt["initial_state_sha256"] if training_receipt else None,
            fit_attempts_during_replay=env["guard"]["attempts"],
            ledger_sha256={f"{ledger}.parquet": sha(folder / f"{ledger}.parquet") for ledger in shared.LEDGERS})
        if env["guard"]["attempts"]:
            raise AssertionError("control replay attempted learning")
        write(folder / "DONE.json", summary)
        return clean(summary)
    except Exception as exc:
        failure = dict(spec, year=year, status="FAILED", failure_type=type(exc).__name__, reason=str(exc),
                       traceback=traceback.format_exc(), seconds=time.monotonic()-start)
        write(folder / "FAILURE.json", failure)
        return failure


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=[2025, 2026], required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    env = initialize_inputs(args.year)
    rows = []
    output = ROOT / f"evaluation_controls_{args.year}"
    output.mkdir(exist_ok=True)
    for name in CONTROLS:
        row = run_control(name, env, resume=args.resume)
        rows.append(row)
        print(f"controls {args.year} {name}: {row['status']}", flush=True)
    table = pd.DataFrame(rows)
    table.drop(columns=["ledger_sha256"], errors="ignore").to_csv(output / "COMPARISON.csv", index=False)
    zeros = table.loc[table.strategy_id.isin(["reinforce_zero", "ppo_zero"])].set_index("strategy_id")
    compare_fields = ["net_return", "max_drawdown", "mean_gross_exposure", "total_fees", "trades", "terminal_nav"]
    equal_zeros = False
    if len(zeros) == 2 and zeros.status.eq("REPLAY_COMPLETE").all():
        equal_zeros = all(np.isclose(float(zeros.loc["reinforce_zero", key]), float(zeros.loc["ppo_zero", key]), rtol=0., atol=1e-10) for key in compare_fields)
        if not equal_zeros:
            raise AssertionError("same-stage matched initial controls diverged")
    for source, expected in env["source_sha256"].items():
        if sha(source) != expected:
            raise AssertionError(f"source modified during replay: {source}")
    write(output / "COMPLETE.json", dict(status="COMPLETE_FIXED_DECISION_CONTROLS" if table.status.eq("REPLAY_COMPLETE").all() else "COMPLETE_WITH_FAILURES",
        year=args.year, controls=list(CONTROLS), completed=int(table.status.eq("REPLAY_COMPLETE").sum()),
        failures=int(table.status.eq("FAILED").sum()), guard_fit_attempts=env["guard"]["attempts"],
        source_sha256=env["source_sha256"], same_stage_zero_controls_identical=equal_zeros,
        zero_controls_are_not_independent_seed_evidence=True,
        formal_full_pool_test_allowed=env["metadata"].get("formal_full_pool_test_allowed", False),
        qualified_subset_diagnostic_only=args.year == 2026,
        training_state_limitations_evidence="rl_artifacts/VERIFICATION.json",
        notes="All outcomes retained. Cash/zero exposure differences are not proof of improved learning.",
        created_utc=datetime.now(timezone.utc).isoformat()))


if __name__ == "__main__":
    main()
