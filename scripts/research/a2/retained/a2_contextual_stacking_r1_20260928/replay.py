"""Paired, fit-forbidden replay through the unchanged A2 execution engine.

The only new production component is the frozen contextual meta policy.  Both
M0 and M1 use the original allocator, risk-in-label definition and ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
OLD = WS / "a2_multimodel_joint_20260928"
sys.path.insert(0, str(OLD))
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from threadpoolctl import threadpool_limits

import engine_v2
import values as v
from evaluate import clocks, operations, summarize, forbid_fitting
from engine_v2 import HoldingAwareDecision

DATA = WS / "a2_latest_effective_joint_20260927/data"
QUALIFIED = WS / "a2_qualification_holdings_v1_20260927/data"
PRICE = WS / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"
LEDGERS = ("daily", "trades", "positions", "target_decisions", "diagnostics",
           "valuation_intervals", "raw_model_outputs", "signal_contexts",
           "operational_actions", "execution_results")
METHODS = ("M0", "M1")


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(vv) for k, vv in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(vv) for vv in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    return value


def write(path, value):
    Path(path).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                    allow_nan=False), encoding="utf-8")


class FrameWriter:
    """Stream audit data as signals complete; do not retain whole-year matrices."""
    def __init__(self, path):
        self.path = Path(path)
        self.writer = None
        self.rows = 0

    def append(self, frame):
        if frame.empty:
            return
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self.writer is None:
            self.writer = pq.ParquetWriter(self.path, table.schema, compression="zstd")
        self.writer.write_table(table)
        self.rows += len(frame)

    def close(self):
        if self.writer is not None:
            self.writer.close()


def original_grid_coverage(current, cash, age):
    """Describe expert extrapolation, without clipping live account inputs."""
    current, cash, age = np.broadcast_arrays(np.asarray(current, float),
                                             np.asarray(cash, float), np.asarray(age, float))
    exact = np.zeros(current.shape, dtype=bool)
    for cw, ca, ag in v.STATE_GRID:
        exact |= ((np.abs(current-cw) <= 1e-8) & (np.abs(cash-ca) <= 1e-8)
                  & (np.abs(age-ag) <= 1e-8))
    gap = np.abs(cash-(.95-9*current))
    outside = ((current < -1e-8) | (current > .1+1e-8) | (cash < .05-1e-8)
               | (cash > .95+1e-8) | (age < -1e-8) | (age > 40+1e-8))
    return dict(expert_original_grid_exact=exact,
                expert_original_cash_current_line_gap=gap,
                expert_original_cash_current_line_supported=gap <= 1e-8,
                expert_original_state_box_outside=outside)


def allocate(day, ctx, current, scores):
    """Exactly the frozen stack branch's production allocation rules."""
    eligible = (day.new_buy_eligible.to_numpy(bool)
                & ~day.ticker.isin(ctx.buy_restricted_tickers).to_numpy())
    allowed = eligible[:, None] | (v.ACTIONS[None, :] <= current[:, None]+1e-10)
    _, selected = v.allocate_joint_scores(scores, day.ticker.tolist(),
        max_names=ctx.available_slots,
        max_units=min(38, int(np.floor((ctx.available_weight+1e-12)/.025))),
        allowed=allowed)
    return v.ACTIONS[selected], selected, allowed


class SharedDecisionAdapter:
    def __init__(self, policy, folder, comparator=None):
        self.policy = policy
        self.age = {}
        self.diagnostics = FrameWriter(folder / "action_diagnostics.parquet")
        self.pairs = FrameWriter(folder / "same_account_pair.parquet") if comparator is not None else None
        self.comparator = comparator
        self.daily_audit = []

    def __call__(self, day, ctx):
        self.age = {t: self.age.get(t, 0)+1 for t, ww in ctx.current_weights.items() if ww > 0}
        day = day.loc[day.new_buy_eligible.astype(bool)
                      | day.ticker.map(ctx.current_weights).fillna(0).gt(0)]
        day = day.sort_values("ticker", kind="stable").reset_index(drop=True)
        names = day.ticker.tolist()
        if not names:
            return HoldingAwareDecision(model_decisions={}, raw_model_outputs={})
        current = np.array([ctx.current_weights.get(t, 0.) for t in names])
        age = np.array([self.age.get(t, 0.) for t in names])
        scores, diag = self.policy.score_actions_with_diagnostics(
            day, current, ctx.cash_weight, age, ctx.available_slots)
        scores = np.asarray(scores, float)
        if scores.shape != (len(names), len(v.ACTIONS)) or not np.isfinite(scores).all():
            raise ValueError("INVALID_META_ACTION_SCORES")
        weights, selected, allowed = allocate(day, ctx, current, scores)
        diag = diag.copy()
        if len(diag) != len(names)*len(v.ACTIONS):
            raise ValueError("INVALID_ACTION_DIAGNOSTIC_LENGTH")
        diag.insert(0, "candidate", self.policy.kind)
        diag.insert(1, "signal_date", ctx.signal_date)
        diag.insert(2, "decision_id", day.attrs.get("decision_id", f"{self.policy.kind}|{ctx.signal_date.date()}"))
        diag["ticker"] = np.repeat(names, len(v.ACTIONS))
        diag["action_weight"] = np.tile(v.ACTIONS, len(names))
        diag["prediction_utility"] = scores.reshape(-1)
        diag["current_weight"] = np.repeat(current, len(v.ACTIONS))
        diag["cash_weight"] = ctx.cash_weight
        diag["available_slots"] = ctx.available_slots
        diag["age_fraction"] = np.repeat(np.minimum(age, 252)/252, len(v.ACTIONS))
        diag["realized_vol_20d"] = np.repeat(day.realized_vol_20d.to_numpy(float), len(v.ACTIONS))
        diag["action_allowed"] = allowed.reshape(-1)
        diag["chosen_action"] = np.tile(np.arange(len(v.ACTIONS)), len(names)) == np.repeat(selected, len(v.ACTIONS))
        diag["chosen_weight"] = np.repeat(weights, len(v.ACTIONS))
        coverage = original_grid_coverage(np.repeat(current, len(v.ACTIONS)),
                                         ctx.cash_weight, np.repeat(age, len(v.ACTIONS)))
        for key, value in coverage.items():
            diag[key] = value
        self.diagnostics.append(diag)
        audit = dict(signal_date=ctx.signal_date, candidate=self.policy.kind,
                     candidate_count=len(names), actual_cash_weight=ctx.cash_weight,
                     actual_available_slots=ctx.available_slots,
                     active_target_names=int((weights > 0).sum()),
                     active_target_weight=float(weights.sum()), reserved_weight=ctx.reserved_weight,
                     total_target_cash_weight=1-ctx.reserved_weight-float(weights.sum()))
        for key in [x for x in diag if (x.startswith("effective_") or x.startswith("contribution_")
                                          or "out_of_range" in x or x.startswith("expert_original_"))]:
            if pd.api.types.is_numeric_dtype(diag[key]) or pd.api.types.is_bool_dtype(diag[key]):
                vals = diag[key].astype(float)
                for stat, val in [("mean", vals.mean()), ("min", vals.min()), ("max", vals.max())]:
                    audit[f"{key}_{stat}"] = float(val)
        self.daily_audit.append(audit)
        if self.comparator is not None:
            # Explanation only: both frozen meta models see M0's actual account.
            # These hypothetical target weights never enter the actual ledger.
            p, z, basis = self.policy.last_features
            other_scores = self.comparator.predict(p, z, basis).reshape(len(names), len(v.ACTIONS))
            other_weights, other_selected, _ = allocate(day, ctx, current, other_scores)
            pair = pd.DataFrame(dict(signal_date=ctx.signal_date,
                account_source=self.policy.kind, ticker=names, current_weight=current,
                cash_weight=ctx.cash_weight, available_slots=ctx.available_slots,
                reserved_weight=float(ctx.reserved_weight), available_weight=float(ctx.available_weight),
                M0_target=weights, M1_target=other_weights,
                M0_action_index=selected, M1_action_index=other_selected))
            for j, action in enumerate(v.ACTIONS):
                pair[f"M0_utility_a{j}"] = scores[:, j]
                pair[f"M1_utility_a{j}"] = other_scores[:, j]
            pair["diagnostic_status"] = "POST_HOC_SAME_ACCOUNT_TARGET_DIAGNOSTIC_NOT_A_PORTFOLIO_REPLAY"
            self.pairs.append(pair)
        decisions = {str(t): float(ww) for t, ww in zip(names, weights)}
        raw = {str(t): dict(meta_method=self.policy.kind, meta_stage=self.policy.stage,
                action_values=scores[i].tolist(), chosen_weight=float(weights[i]))
               for i, t in enumerate(names)}
        return HoldingAwareDecision(model_decisions=decisions, raw_model_outputs=raw)

    def close(self, folder):
        self.diagnostics.close()
        if self.pairs is not None:
            self.pairs.close()
        pd.DataFrame(self.daily_audit).to_parquet(folder / "daily_meta_audit.parquet", index=False)


def source_data(year):
    if year == 2026:
        sources = [OLD / "data/test_features_context.parquet", OLD / "data/test_prices.parquet",
                   DATA / "calendar.parquet", QUALIFIED / "operational_exit_evidence.csv",
                   OLD / "data/ADMISSIBILITY_RECEIPT.json", OLD / "data/GLW_EVIDENCE_BINDING.json"]
        panel = pd.read_parquet(sources[0])
        prices = pd.read_parquet(sources[1])
        calendar = pd.DatetimeIndex(pd.read_parquet(sources[2]).query("is_test").trade_date)
        last, stage = "2026-09-22", "final"
        receipt = json.loads(sources[4].read_text(encoding="utf-8"))
        for name in ["test_features_context.parquet", "test_prices.parquet"]:
            assert sha(OLD / "data" / name) == receipt["output_sha256"][name]
        assert not ((panel.ticker == "GLW") & (panel.signal_date == pd.Timestamp("2026-02-26"))).any()
        glw = prices.loc[(prices.ticker == "GLW") & (prices.trade_date == pd.Timestamp("2026-02-26"))]
        assert len(glw) == 1 and bool(glw.price_quality_warning.iloc[0])
    else:
        sources = [DATA / "pre2026_joint_context.parquet", PRICE]
        panel = pd.read_parquet(sources[0])
        panel = panel.loc[panel.signal_date.ge("2025-01-01")].copy()
        prices = pd.read_parquet(PRICE)
        calendar = pd.DatetimeIndex(sorted(prices.loc[
            prices.ticker.eq("QQQ") & prices.trade_date.ge("2025-01-01"), "trade_date"].unique()))
        last, stage = "2025-12-29", "validation"
    panel = panel.loc[panel.signal_date.le(last), ["signal_date", "ticker", "new_buy_eligible", *v.FEATURES]].copy()
    assert panel.signal_date.dt.year.eq(year).all()
    assert not panel.duplicated(["signal_date", "ticker"]).any()
    assert np.isfinite(panel[v.FEATURES].to_numpy(float)).all()
    return panel, prices, calendar, last, stage, sources


def loaded_source_hashes(policy):
    """Bind actual selected-stage dependencies and actually imported source files."""
    result = dict(policy.base.hashes)
    for module in list(sys.modules.values()):
        path_value = getattr(module, "__file__", None)
        if isinstance(path_value, (str, Path)):
            path = Path(path_value).resolve()
            if path.suffix == ".py" and path.is_file() and (path.parent == ROOT or path.parent == OLD):
                result[str(path)] = sha(path)
    for name in ["EXPERIMENT_CONTRACT.md", "PRE_FIT_CONTRACT.json", "FIT_RECEIPT.json"]:
        for path in [ROOT/name, ROOT/"meta_artifacts"/name, ROOT/"artifacts"/name]:
            if path.exists():
                result[str(path)] = sha(path)
    # Actual meta/scaler paths are also explicit in the loader's own receipt.
    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(key, str) and isinstance(value, str) and len(value) == 64:
                    path = Path(key)
                    if path.is_file():
                        assert sha(path) == value, f"LOADED_HASH_MISMATCH:{path}"
                        result[str(path)] = value
                walk(value)
            for path_key, hash_key in [("artifact", "artifact_sha256"), ("path", "sha256"),
                                       ("model_path", "model_sha256"), ("scaler_path", "scaler_sha256")]:
                if path_key in obj and hash_key in obj:
                    path = Path(obj[path_key]); expected = obj[hash_key]
                    assert sha(path) == expected, f"LOADED_HASH_MISMATCH:{path}"
                    result[str(path)] = expected
        elif isinstance(obj, (list, tuple)):
            for value in obj:
                walk(value)
    walk(policy.loaded_receipt)
    return result


def verify_ledger(result, cost):
    daily, trades = result.daily, result.trades
    tolerances = dict(nav_identity_error=1e-7, cash_flow_identity_error=1e-7,
                      cost_identity_error=1e-7, open_self_finance_error=1e-7)
    maxima = {}
    for key, tol in tolerances.items():
        val = float(daily[key].dropna().abs().max()) if daily[key].notna().any() else 0.
        assert val <= tol, (key, val)
        maxima[key] = val
    assert daily.cash.ge(-1e-7).all()
    assert daily.actual_name_count.le(20).all()
    if len(trades):
        fee_error = float((trades.transaction_cost-trades.notional*cost/10000).abs().max())
        assert fee_error < 1e-7
        buys = trades.loc[trades.side.eq("BUY")]
        assert buys.capacity_enforced.astype(bool).all()
        assert (buys.notional <= .01*buys.capacity_adv+1e-7).all()
        assert trades.execution_date.gt(trades.signal_date).all()
    else:
        fee_error = 0.
    target = result.target_decisions
    raw = target.loc[target.explicit_model_decision.astype(bool), "raw_model_weight"]
    assert raw.between(0., .1+1e-7).all()
    assert result.signal_contexts.active_target_count.le(result.signal_contexts.final_available_slots).all()
    assert (result.signal_contexts.active_target_weight <= result.signal_contexts.final_available_weight+1e-7).all()
    # Missing-input holdings retain explicit HOLD_UNITS orders, unless an
    # independently evidenced operational exit supersedes the reservation.
    absent = target.loc[~target.model_input_row_present.astype(bool) & target.current_units.gt(0)
                        & ~target.decision_semantic.eq("OPERATIONAL_EXIT_REQUIRED")]
    assert absent.order_type.eq("HOLD_UNITS").all()
    assert np.allclose(absent.hold_units, absent.current_units, atol=1e-10, rtol=0)
    return dict(status="PASS", identity_error_max=maxima, fee_error_max=fee_error,
                max_actual_names=int(daily.actual_name_count.max()),
                capacity_fraction=.01, fit_during_replay=False,
                missing_input_hold_rows=len(absent))


def forbid_custom_fitting(module, guard):
    """Also block the custom weighted scaler and regularized linear solver."""
    blocked = []
    def denied(*args, **kwargs):
        guard["attempts"] += 1
        raise RuntimeError("CUSTOM_FIT_FORBIDDEN_DURING_EVALUATION")
    for name in ["fit_meta", "fit_scalers", "fit_model", "fit_regularized", "fit_weighted_ridge"]:
        if hasattr(module, name):
            setattr(module, name, denied)
            blocked.append(f"meta.{name}")
    scaler = getattr(module, "WeightedScaler", None)
    if scaler is not None:
        for name in ["fit", "fit_chunks", "partial_fit", "fit_transform"]:
            if hasattr(scaler, name):
                setattr(scaler, name, denied)
                blocked.append(f"WeightedScaler.{name}")
    return blocked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    parser.add_argument("--cost", type=float, default=10, choices=[5, 10, 25])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    # The root-controlled pre-fit seal fixes the authorized experiment.
    seal = ROOT / "PRE_FIT_LOCK.json"
    if not seal.exists():
        raise RuntimeError("ROOT_REPLAY_SEAL_REQUIRED")
    readiness = json.loads(seal.read_text(encoding="utf-8"))
    assert readiness["status"] == "PRE_FIT_LOCKED"
    locked_hashes = dict(readiness["input_sha256"])
    locked_hashes[str(ROOT/"EXPERIMENT_CONTRACT.md")] = readiness["contract_sha256"]
    locked_hashes[str(seal)] = sha(seal)
    for path, expected in locked_hashes.items():
        assert sha(path) == expected, f"REPLAY_SEAL_CHANGED:{path}"
    out = ROOT / f"evaluation_{args.year}" / f"cost_{args.cost:g}"
    out.mkdir(parents=True, exist_ok=True)
    if (out / "COMPLETE.json").exists():
        raise RuntimeError("COMPLETED_EVALUATION_ALREADY_EXISTS")
    guard = forbid_fitting()
    import meta
    custom_blocked = forbid_custom_fitting(meta, guard)
    ContextualPolicy, ContextualMeta = meta.ContextualPolicy, meta.ContextualMeta
    panel, prices, calendar, last, stage, sources = source_data(args.year)
    asofs = clocks(calendar)
    ops = operations(calendar, asofs) if args.year == 2026 else {}
    data_hashes = {str(path): sha(path) for path in sources}
    binding = dict(created_utc=pd.Timestamp.now(tz="UTC"), year=args.year,
                   cost_bps=args.cost, stage=stage, methods=list(METHODS),
                   source_sha256={**data_hashes, **locked_hashes},
                   risk_policy="original utility-label volatility penalty; no new covariance penalty",
                   fit_2026_rows=0, blind_test=False, full_pool_complete=False,
                   engine_path=engine_v2.__file__, allocator_path=v.__file__)
    frozen = out / "FROZEN_BEFORE_REPLAY.json"
    if frozen.exists():
        assert args.resume
        previous = json.loads(frozen.read_text(encoding="utf-8"))
        assert previous["source_sha256"] == binding["source_sha256"]
    else:
        write(frozen, binding)
    metrics = []
    for method in METHODS:
        folder = out / method
        if (folder / "DONE.json").exists() and args.resume:
            metrics.append(json.loads((folder / "DONE.json").read_text(encoding="utf-8")))
            continue
        if folder.exists():
            raise RuntimeError(f"INCOMPLETE_OUTPUT_PRESERVED:{folder}")
        folder.mkdir()
        start = time.monotonic()
        with threadpool_limits(limits=2), torch.no_grad():
            policy = ContextualPolicy(kind=method, stage=stage)
            assert policy.stage == stage and policy.base.stage == stage
            loaded_hashes = loaded_source_hashes(policy)
            comparator = ContextualMeta("M1", stage) if method == "M0" and args.year == 2025 and args.cost == 10 else None
            if comparator is not None:
                for path, expected in comparator.loaded_receipt["actual_loaded_hashes"].items():
                    assert sha(path) == expected
                    loaded_hashes[path] = expected
            runtime = dict(created_utc=pd.Timestamp.now(tz="UTC"), method=method, stage=stage,
                year=args.year, evaluation_cost_bps=args.cost,
                actual_loader_receipt=policy.loaded_receipt,
                actual_loaded_source_sha256=loaded_hashes, data_source_sha256=data_hashes,
                comparator_loaded_receipt=comparator.loaded_receipt if comparator is not None else None,
                python=platform.python_version(),
                package_versions={name: importlib.metadata.version(name) for name in
                                  ["numpy", "pandas", "scikit-learn", "torch", "scipy"]},
                fit_guard_installed=True, custom_fit_entrypoints_blocked=custom_blocked,
                label_interface_absent=True,
                original_engine=True, original_allocator=True,
                coefficient_semantics="utility-unit regression coefficients; not capital shares or correctness probabilities")
            write(folder / "RUNTIME_LOAD_RECEIPT.json", runtime)
            actor = SharedDecisionAdapter(policy, folder, comparator)
            try:
                result = engine_v2.run_replay(prices, calendar, panel, actor, candidate=method,
                    cost_bps=args.cost, capacity_fraction=.01,
                    signal_start=f"{args.year}-01-01", signal_end=last,
                    signal_asof=asofs, operational_exits_by_signal=ops)
            finally:
                actor.close(folder)
        acceptance = verify_ledger(result, args.cost)
        for key in LEDGERS:
            getattr(result, key).to_parquet(folder / f"{key}.parquet", index=False)
        write(folder / "metadata.json", result.metadata)
        assert guard["attempts"] == 0
        protected = {**loaded_hashes, **data_hashes, **locked_hashes}
        assert all(sha(path) == expected for path, expected in protected.items()), "FROZEN_SOURCES_CHANGED_DURING_REPLAY"
        write(folder / "LEDGER_ACCEPTANCE.json", acceptance)
        row = summarize(result, method, args.year, args.cost)
        row.update(stage=stage, seconds=round(time.monotonic()-start, 2),
                   research_batch="A2_CONTEXTUAL_STACKING_R1", blind_test=False,
                   fit_attempts=guard["attempts"], runtime_load_receipt_sha256=sha(folder / "RUNTIME_LOAD_RECEIPT.json"))
        write(folder / "DONE.json", row)
        metrics.append(row)
        pd.DataFrame(metrics).to_csv(out / "comparison.csv", index=False)
        print(json.dumps(clean(row), ensure_ascii=False), flush=True)
    assert guard["attempts"] == 0
    assert all(sha(path) == expected for path, expected in binding["source_sha256"].items())
    write(out / "COMPLETE.json", dict(status="FROZEN_PAIRED_REPLAY_COMPLETE", year=args.year,
        cost_bps=args.cost, stage=stage, policies=len(METHODS), fit_attempts=guard["attempts"],
        sources_unchanged=True, blind_test=False, full_pool_complete=False,
        formal_2026_performance=False))


if __name__ == "__main__":
    main()
