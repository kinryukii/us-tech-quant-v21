"""Frozen, fit-free 2025 capacity attribution for two joint policies."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "joint_linear_tree_coverage_v2" / "bundle"))

from engine import run_replay  # noqa: E402
from run_suite import Stateful, forbid_fitting, metrics  # noqa: E402
from v2_policy import load_policy_v2  # noqa: E402
import joint_linear_tree  # noqa: E402

HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "pre2026_joint_context.parquet"
PRICE = ROOT.parent / "a2_strict_method_retrain_20260926" / "results" / "pre2026_original_price_coordinate.parquet"
BASELINE = ROOT.parent / "a2_strict_method_retrain_20260926" / "results" / "hgb" / "pre2026_oof.parquet"
V2 = ROOT / "joint_linear_tree_coverage_v2" / "out"
CAP_OUTPUTS = {
    "joint_hgb": ROOT / "evaluation_2025_sampling_v2" / "joint_hgb_10bps",
    "joint_rl_ensemble": ROOT / "evaluation_2025" / "joint_rl_ensemble_10bps",
}
SAMPLE_KEYS = {
    "validation": V2 / "sample_keys_validation.parquet",
    "final": V2 / "sample_keys_final.parquet",
}
STAGES = {"validation": pd.Timestamp("2025-01-01"), "final": pd.Timestamp("2026-01-01")}


def sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False,
                               default=str, allow_nan=False), encoding="utf-8")


def boundary(path: Path, column: str) -> dict:
    pf = pq.ParquetFile(path)
    col = pf.schema.names.index(column)
    maxima = []
    for i in range(pf.metadata.num_row_groups):
        stats = pf.metadata.row_group(i).column(col).statistics
        if stats is None or not stats.has_min_max:
            raise RuntimeError(f"NO_DATE_STATS:{path.name}:{i}")
        maximum = pd.Timestamp(stats.max)
        if maximum >= pd.Timestamp("2026-01-01"):
            raise RuntimeError(f"TEST_YEAR_IN_SOURCE:{path.name}:{i}")
        maxima.append(str(maximum))
    return {"row_groups": len(maxima), "maximum": max(maxima)}


def static_training_capacity(panel: pd.DataFrame) -> dict:
    universe = panel[["signal_date", "ticker", "label_end_date", "new_buy_eligible",
                      "avg_dollar_volume_20d"]].copy()
    if universe.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_PRE2026_SAMPLE_KEY")
    output = {}
    for stage, path in SAMPLE_KEYS.items():
        keys = pd.read_parquet(path)
        if keys.duplicated(["signal_date", "ticker"]).any():
            raise RuntimeError(f"DUPLICATE_{stage.upper()}_KEY")
        fit = keys.merge(universe, on=["signal_date", "ticker"], how="left",
                         validate="one_to_one", indicator=True, suffixes=("_sample", "_source"))
        if not fit._merge.eq("both").all():
            raise RuntimeError(f"MISSING_{stage.upper()}_SOURCE_KEY")
        if not fit.label_end_date_sample.eq(fit.label_end_date_source).all():
            raise RuntimeError(f"CHANGED_{stage.upper()}_LABEL_END")
        if not fit.signal_date.lt(STAGES[stage]).all() or not fit.label_end_date_sample.lt(STAGES[stage]).all():
            raise RuntimeError(f"IMMATURE_{stage.upper()}_LABEL")
        if not fit.new_buy_eligible.all():
            raise RuntimeError(f"INELIGIBLE_{stage.upper()}_KEY")
        adv = fit.avg_dollar_volume_20d.to_numpy(float)
        valid = np.isfinite(adv) & (adv > 0)
        cap = np.where(valid, .01 * adv, 0.)
        action = {}
        for current in (0., .05):
            for target in joint_linear_tree.ACTIONS:
                if target <= current:
                    continue
                requested = 1_000_000. * (target-current)
                shortfall = np.maximum(requested-cap, 0.)
                action[f"current_{current:g}_target_{target:g}"] = dict(
                    state_weight=current, target_weight=float(target),
                    nominal_increment_dollars=float(requested),
                    unable_to_fill_once=int(np.count_nonzero(shortfall > 1e-9)),
                    unable_to_fill_once_fraction=float(np.mean(shortfall > 1e-9)),
                    total_nominal_shortfall_dollars=float(shortfall.sum()),
                )
        output[stage] = dict(rows=len(fit), dates=fit.signal_date.nunique(),
                             first_signal=str(fit.signal_date.min().date()),
                             last_signal=str(fit.signal_date.max().date()),
                             mature_before=str(STAGES[stage].date()),
                             missing_or_nonpositive_adv=int((~valid).sum()),
                             capacity_actions=action)
    return output


class V2HgbStateful(Stateful):
    def __init__(self):
        self.name, self.age, self.lastdate, self.records = "joint_hgb", {}, None, []
        self.policy = load_policy_v2("hgb", stage="validation", artifacts_root=V2)


def load_2025_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    features = list(joint_linear_tree.FEATURES)
    panel = pd.read_parquet(SOURCE,
                            columns=["signal_date", "ticker", "new_buy_eligible", *features],
                            filters=[("signal_date", ">=", pd.Timestamp("2025-01-01")),
                                     ("signal_date", "<=", pd.Timestamp("2025-12-29"))])
    prices = pd.read_parquet(PRICE, columns=["ticker", "trade_date", "open", "close"],
                             filters=[("trade_date", ">=", pd.Timestamp("2025-01-01"))])
    score = pd.read_parquet(BASELINE, columns=["signal_date", "ticker", "prediction"],
                            filters=[("signal_date", ">=", pd.Timestamp("2025-01-01")),
                                     ("signal_date", "<=", pd.Timestamp("2025-12-29"))])
    if panel.empty or prices.empty or score.empty:
        raise RuntimeError("EMPTY_2025_INPUT")
    for frame, date_col in ((panel, "signal_date"), (prices, "trade_date"), (score, "signal_date")):
        if frame[date_col].max() >= pd.Timestamp("2026-01-01"):
            raise RuntimeError(f"TEST_YEAR_IN_LOADED_{date_col}")
    panel = panel.merge(score.rename(columns={"prediction": "baseline_hgb"}),
                        on=["signal_date", "ticker"], how="left", validate="one_to_one")
    if panel.baseline_hgb.isna().any():
        raise RuntimeError("MISSING_TIME_LEGAL_BASELINE")
    panel = panel[["signal_date", "ticker", "new_buy_eligible", "baseline_hgb", *features]]
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    if len(calendar) != 250:
        raise RuntimeError(f"UNEXPECTED_2025_CALENDAR:{len(calendar)}")
    return panel, prices, calendar


def account_guard(daily: pd.DataFrame, trades: pd.DataFrame) -> dict:
    cols = ["cash_flow_identity_error", "cost_identity_error", "open_self_finance_error", "nav_identity_error"]
    maxima = {c: float(daily[c].abs().max()) for c in cols}
    if not all(np.isfinite(v) and v < 1e-6 for v in maxima.values()):
        raise RuntimeError(f"ACCOUNT_IDENTITY_FAILURE:{maxima}")
    if not trades.empty:
        fee_error = (trades.transaction_cost - trades.notional * .001).abs().max()
        maxima["max_trade_fee_error"] = float(fee_error)
        if fee_error >= 1e-6:
            raise RuntimeError("TRADE_FEE_IDENTITY_FAILURE")
    return maxima


def compare(name: str, free, cap_folder: Path) -> dict:
    capped = {k: pd.read_parquet(cap_folder / f"{k}.parquet") for k in
              ("daily", "trades", "positions", "target_decisions", "diagnostics")}
    cap_guard = account_guard(capped["daily"], capped["trades"])
    free_guard = account_guard(free.daily, free.trades)
    binding = capped["diagnostics"].loc[capped["diagnostics"].code.eq("capacity_limited")].copy()
    if binding.empty:
        raise RuntimeError(f"NO_CAPACITY_EVENT:{name}")
    binding["shortfall"] = binding.requested_notional-binding.allowed_notional
    if (binding.shortfall <= 0).any():
        raise RuntimeError("CAPACITY_DIAGNOSTIC_INVALID")
    first_bind = pd.Timestamp(binding.date.min())
    pair = capped["daily"].merge(free.daily, on="date", suffixes=("_cap", "_free"), validate="one_to_one")
    if len(pair) != 250:
        raise RuntimeError(f"MISMATCHED_2025_DAILY:{name}:{len(pair)}")
    before = pair[pair.date.lt(first_bind)]
    early_nav_diff = float((before.nav_cap-before.nav_free).abs().max()) if len(before) else 0.
    # Original 2025 files and this Linux replay may differ below one cent
    # before the capacity switch because neural inference uses float32.
    if early_nav_diff > .01:
        raise RuntimeError(f"DIVERGENCE_PRECEDES_FIRST_CAP:{name}:{early_nav_diff}")
    cap_targets = capped["target_decisions"][["signal_date", "ticker", "target_weight"]]
    free_targets = free.target_decisions[["signal_date", "ticker", "target_weight"]]
    targets = cap_targets.merge(free_targets, on=["signal_date", "ticker"], how="outer",
                                suffixes=("_cap", "_free"), validate="one_to_one")
    changed = targets.target_weight_cap.fillna(0).sub(targets.target_weight_free.fillna(0)).abs().gt(1e-9)
    early_targets = targets.loc[targets.signal_date.lt(first_bind)]
    early_target_diff = float(early_targets.target_weight_cap.fillna(0).sub(
        early_targets.target_weight_free.fillna(0)).abs().max()) if len(early_targets) else 0.
    if early_targets[["target_weight_cap", "target_weight_free"]].isna().any().any() or early_target_diff > 1e-6:
        raise RuntimeError(f"TARGETS_DIVERGE_BEFORE_FIRST_CAP:{name}:{early_target_diff}")
    order_cols = ["execution_date", "ticker", "side", "action"]
    cap_early_orders = capped["trades"].loc[capped["trades"].execution_date.lt(first_bind), order_cols]
    free_early_orders = free.trades.loc[free.trades.execution_date.lt(first_bind), order_cols]
    order_join = cap_early_orders.merge(free_early_orders, on=order_cols, how="outer", indicator=True,
                                        validate="one_to_one")
    if not order_join._merge.eq("both").all():
        raise RuntimeError(f"ORDER_IDENTITY_DIVERGES_BEFORE_FIRST_CAP:{name}")
    cap_pos = capped["positions"][["date", "ticker", "index_units"]]
    free_pos = free.positions[["date", "ticker", "index_units"]]
    positions = cap_pos.merge(free_pos, on=["date", "ticker"], how="outer",
                              suffixes=("_cap", "_free"), validate="one_to_one")
    position_changed = positions.index_units_cap.fillna(0).sub(positions.index_units_free.fillna(0)).abs().gt(1e-8)
    return dict(
        policy=name, first_binding_execution_date=str(first_bind.date()),
        cap_events=len(binding), affected_security_dates=int(binding[["date", "ticker"]].drop_duplicates().shape[0]),
        cap_requested_dollars=float(binding.requested_notional.sum()),
        cap_allowed_dollars=float(binding.allowed_notional.sum()),
        cap_unfilled_dollars=float(binding.shortfall.sum()),
        max_single_order_shortfall_dollars=float(binding.shortfall.max()),
        pre_first_bind_nav_difference_dollars=early_nav_diff,
        pre_first_bind_max_target_weight_difference=early_target_diff,
        pre_first_bind_identical_order_count=len(order_join),
        capped=dict(days=len(capped["daily"]), trades=len(capped["trades"]),
                    fees_dollars=float(capped["daily"].transaction_cost_amount.sum()),
                    terminal_indicative_nav_dollars=float(capped["daily"].nav.iloc[-1]),
                    uncertified_days=int(capped["daily"].valuation_status.ne("certified").sum()),
                    mean_cash_weight=float(capped["daily"].cash_weight.mean()), account_identity=cap_guard),
        no_capacity=dict(days=len(free.daily), trades=len(free.trades),
                         fees_dollars=float(free.daily.transaction_cost_amount.sum()),
                         terminal_indicative_nav_dollars=float(free.daily.nav.iloc[-1]),
                         uncertified_days=int(free.daily.valuation_status.ne("certified").sum()),
                         mean_cash_weight=float(free.daily.cash_weight.mean()), account_identity=free_guard),
        account_days_nav_changed=int(np.count_nonzero((pair.nav_cap-pair.nav_free).abs() > 1e-6)),
        account_days_cash_changed=int(np.count_nonzero((pair.cash_cap-pair.cash_free).abs() > 1e-6)),
        security_signal_targets_changed=int(changed.sum()),
        signal_dates_targets_changed=int(targets.loc[changed, "signal_date"].nunique()),
        security_date_holdings_changed=int(position_changed.sum()),
        holding_dates_changed=int(positions.loc[position_changed, "date"].nunique()),
        no_capacity_is_executable=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out not in (HERE / "out", HERE / "out_02") or (out.exists() and any(out.iterdir())):
        raise RuntimeError("OUTPUT_MUST_BE_NEW_PRIVATE_CAPACITY_OUT")
    receipt = json.loads((V2 / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS" or receipt.get("revision") != "DATE_COMPLETE_WITHIN_DAY_HASH_V2":
        raise RuntimeError("V2_FIT_IDENTITY_FAILURE")
    paths = [SOURCE, PRICE, BASELINE, V2 / "FIT_RECEIPT.json", V2 / "validation_hgb.joblib",
             *SAMPLE_KEYS.values(), ROOT / "joint_neural_artifacts" / "TRAIN_RECEIPT.json",
             ROOT / "joint_neural_artifacts" / "validation_normalization.npz",
             ROOT / "joint_neural_artifacts" / "validation_rl_20260927.pt",
             ROOT / "joint_neural_artifacts" / "validation_rl_20260928.pt",
             ROOT / "engine.py", ROOT / "run_suite.py", ROOT / "joint_linear_tree.py",
             ROOT / "joint_neural.py", ROOT / "models" / "model_registry.json",
             ROOT / "joint_linear_tree_coverage_v2" / "bundle" / "v2_policy.py",
             HERE / "PRE2026_STUDY_CONTRACT.md", Path(__file__).resolve()]
    for folder in CAP_OUTPUTS.values():
        paths += [folder / f"{name}.parquet" for name in
                  ("daily", "trades", "positions", "target_decisions", "diagnostics")]
    if any(not p.is_file() for p in paths):
        raise RuntimeError("MISSING_FROZEN_2025_SOURCE")
    boundaries = {str(p): boundary(p, "signal_date" if p == SOURCE or p == BASELINE else "trade_date")
                  for p in (SOURCE, PRICE, BASELINE)}
    frozen = dict(status="FROZEN_PRE2026_CAPACITY_DIAGNOSTIC", batch=ROOT.name,
                  contract="PRE2026_STUDY_CONTRACT.md", policies=list(CAP_OUTPUTS),
                  year=2025, initial_cash=1_000_000., cost_bps_each_side=10.,
                  existing_capacity_fraction=.01, counterfactual_capacity_fraction=None,
                  counterfactual_executable=False, fit_budget=0, replay_budget=2,
                  source_sha256={str(p): sha(p) for p in paths}, source_boundaries=boundaries)
    if out.exists():
        if any(out.iterdir()):
            raise RuntimeError("OUTPUT_NOT_EMPTY")
    else:
        out.mkdir(parents=True)
    write_json(out / "PRE_RUN_FREEZE.json", frozen)
    print("PRE2026_CAPACITY_FROZEN", flush=True)

    fit_guard = forbid_fitting()
    sample = pd.read_parquet(SOURCE,
                             columns=["signal_date", "ticker", "label_end_date", "new_buy_eligible",
                                      "avg_dollar_volume_20d"],
                             filters=[("signal_date", ">=", pd.Timestamp("2023-01-01")),
                                      ("signal_date", "<", pd.Timestamp("2026-01-01"))])
    if sample.signal_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("TEST_YEAR_IN_TRAIN_SAMPLE")
    structural = static_training_capacity(sample)
    del sample
    panel, prices, calendar = load_2025_panel()
    studies = []
    for name in CAP_OUTPUTS:
        actor = V2HgbStateful() if name == "joint_hgb" else Stateful(name, "validation")
        with threadpool_limits(limits=2):
            free = run_replay(prices, calendar, panel, actor,
                              candidate=f"{name}_no_capacity_diagnostic",
                              initial_cash=1_000_000., cost_bps=10., max_weight=.10,
                              max_positions=20, max_invested=.95, capacity_fraction=None,
                              missing_signal_policy="cash", signal_start="2025-01-01",
                              signal_end="2025-12-29")
        folder = out / f"{name}_no_capacity"
        folder.mkdir()
        for key in ("daily", "trades", "positions", "target_decisions", "diagnostics", "valuation_intervals"):
            getattr(free, key).to_parquet(folder / f"{key}.parquet", index=False)
        write_json(folder / "metadata.json", free.metadata)
        comparison = compare(name, free, CAP_OUTPUTS[name])
        studies.append(comparison)
        write_json(out / f"{name}_COMPARISON.json", comparison)
        print("PRE2026_CAPACITY_POLICY", name, "cap_events", comparison["cap_events"],
              "changed_target_dates", comparison["signal_dates_targets_changed"], flush=True)
    if fit_guard["attempts"] != 0:
        raise RuntimeError("FIT_ATTEMPTED_DURING_CAPACITY_STUDY")
    if any(sha(p) != expected for p, expected in
           ((Path(p), h) for p, h in frozen["source_sha256"].items())):
        raise RuntimeError("FROZEN_SOURCE_CHANGED_DURING_STUDY")
    peak_path = Path("/sys/fs/cgroup/memory.peak")
    peak = int(peak_path.read_text().strip()) if peak_path.is_file() else None
    write_json(out / "COMPLETE.json", dict(status="PRE2026_CAPACITY_STUDY_COMPLETE",
             input_identity_preserved=True, fit_guard_attempts=0, new_supervised_fits=0,
             new_rl_updates=0, new_2025_replays=len(studies), test_2026_reads=0,
             calendar_days_2025=len(calendar), structural_training_capacity=structural,
             memory_peak_bytes=peak,
             policies=studies, price_interpretation="index-coordinate proxy, not shareholder total return"))
    print("PRE2026_CAPACITY_STUDY_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
