"""One fixed 2025 capacity-account comparison for the bounded joint revision.

The two new policies are frozen together before this module reads 2025 prices
or runs the account.  It reuses the original account engine via the verified
NAV-context adapter; it never fits a model or reads 2026 data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PRICE = ROOT.parent / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"
PANEL = ROOT / "data/pre2026_joint_context.parquet"
OOF = ROOT.parent / "a2_strict_method_retrain_20260926/results/hgb/pre2026_oof.parquet"
HGB = ROOT / "followup_review/capacity_aware_supervised"
RL = ROOT / "followup_review/capacity_aware_rl"
EXPECTED_ENGINE_SHA = "c3bf057173960920de8faa15d6aa6e2522b1c8e9eae6bb3b4e96c665a37b33ff"
EXPECTED_PANEL_SHA = "5895dbca36064a7ea7a9ab66fbe47c5b1dfc2ab5e6cef61d53cd23e447b09b0e"
EXPECTED_PRICE_SHA = "a8fd449887076633a816fd1ebf4ad17f27dbf5ae0948bb805e9cc6b978cb8cda"
EXPECTED_OOF_SHA = "60cd7198818f33e8a6a496666a7c775f0e4d37c1d6a7464df50b379e0fac024f"
SEEDS = (20260927, 20260928)
OUTPUT_KEYS = ("daily", "trades", "positions", "target_decisions", "diagnostics", "valuation_intervals")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               default=str, allow_nan=False), encoding="utf-8")


def bound_files() -> list[Path]:
    fixed = [
        ROOT / "engine.py", ROOT / "joint_neural.py", ROOT / "joint_linear_tree.py",
        ROOT / "models/model_registry.json", PANEL, PRICE, OOF,
        HERE / "nav_context_adapter.py", Path(__file__).resolve(),
        HERE / "run_2025_capacity_container.ps1",
        HERE / "CONTRACT_BEFORE_FIT.md",
        HGB / "SCIENCE_CONTRACT.md", HGB / "one_step_label.py",
        HGB / "prepare_fit.py", HGB / "policy.py", HGB / "seal_output.py",
        HGB / "out/OUTPUT_SEAL.json", HGB / "out/PRE_FIT_FREEZE.json",
        HGB / "out/FIT_RECEIPT.json",
        HGB / "out/validation_hgb.joblib", HGB / "out/final_hgb.joblib",
        RL / "PRE_FIT_CONTRACT.md", RL / "train_capacity_rl.py",
        RL / "TRAIN_OUTPUT_SEAL.json",
        RL / "out/TRAIN_RECEIPT.json", RL / "out/validation_normalization.npz",
        RL / "out/final_normalization.npz",
        ROOT / "evaluation_2025_sampling_v2/PRE_REPLAY_FREEZE.json",
        ROOT / "joint_linear_tree_coverage_v2/out/FIT_RECEIPT.json",
        ROOT / "joint_neural_artifacts/TRAIN_RECEIPT.json",
        ROOT / "evaluation_2025_sampling_v2/COMPLETE.json",
        ROOT / "evaluation_2025_sampling_v2/comparison.csv",
        ROOT / "evaluation_2025_sampling_v2/joint_hgb_10bps/metadata.json",
        ROOT / "evaluation_2025/COMPLETE.json",
        ROOT / "evaluation_2025/comparison.csv",
        ROOT / "evaluation_2025/joint_rl_ensemble_10bps/metadata.json",
    ]
    fixed.extend(RL / "out" / f"{stage}_rl_{seed}.pt"
                 for stage in ("validation", "final") for seed in SEEDS)
    absent = [str(path) for path in fixed if not path.is_file()]
    if absent:
        raise RuntimeError(f"INCOMPLETE_FROZEN_BATCH:{absent}")
    return fixed


def freeze(out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        raise RuntimeError("PRESERVE_EXISTING_2025_COMPARISON_OUTPUT")
    files = bound_files()
    hashes = {str(path.relative_to(ROOT)): sha(path) if path.is_relative_to(ROOT) else None
              for path in files if path.is_relative_to(ROOT)}
    hashes["../a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"] = sha(PRICE)
    hashes["../a2_strict_method_retrain_20260926/results/hgb/pre2026_oof.parquet"] = sha(OOF)
    for key, want in (("engine.py", EXPECTED_ENGINE_SHA),
                      ("data/pre2026_joint_context.parquet", EXPECTED_PANEL_SHA),
                      ("../a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet", EXPECTED_PRICE_SHA),
                      ("../a2_strict_method_retrain_20260926/results/hgb/pre2026_oof.parquet", EXPECTED_OOF_SHA)):
        if hashes[key] != want:
            raise RuntimeError(f"BOUND_SOURCE_IDENTITY_MISMATCH:{key}:{hashes[key]}")
    hgb_receipt = json.loads((HGB / "out/FIT_RECEIPT.json").read_text(encoding="utf-8"))
    rl_receipt = json.loads((RL / "out/TRAIN_RECEIPT.json").read_text(encoding="utf-8"))
    if hgb_receipt.get("fit_calls") != 2 or hgb_receipt.get("status") != "PASS":
        raise RuntimeError("HGB_FIXED_TWO_FITS_NOT_COMPLETE")
    if rl_receipt.get("status") != "PRE2026_CAPACITY_AWARE_RL_TRAINED":
        raise RuntimeError("RL_FIXED_TRAINING_NOT_COMPLETE")
    if rl_receipt.get("actual_parameter_updates") != 320:
        raise RuntimeError("RL_FIXED_UPDATE_BUDGET_CHANGED")
    if len([row for row in rl_receipt["logs"] if row["stage"] in ("validation", "final")]) != 16:
        raise RuntimeError("RL_FIXED_EPISODE_BUDGET_CHANGED")
    if rl_receipt.get("fit_2026_rows") != 0 or hgb_receipt.get("test_2026_reads") != 0:
        raise RuntimeError("TEST_ROWS_REACHED_TRAINING")
    if {(r["stage"], r["seed"]) for r in rl_receipt["artifacts"]} != {
        (stage, seed) for stage in ("validation", "final") for seed in SEEDS}:
        raise RuntimeError("RL_SEED_STAGE_SET_CHANGED")
    for path in (ROOT / "evaluation_2025_sampling_v2/joint_hgb_10bps/metadata.json",
                 ROOT / "evaluation_2025/joint_rl_ensemble_10bps/metadata.json"):
        old_contract = json.loads(path.read_text(encoding="utf-8"))
        if (old_contract.get("capacity_fraction") != .01 or
                old_contract.get("cost_bps_one_way") != 10. or
                old_contract.get("initial_cash") != 1_000_000. or
                old_contract.get("signal_end") != "2025-12-29"):
            raise RuntimeError(f"OLD_COMPARATOR_NOT_SAME_CAPACITY_ACCOUNT:{path}")
    out.mkdir(parents=True, exist_ok=True)
    manifest = dict(status="FROZEN_BEFORE_2025_CAPACITY_COMPARISON",
                    batch="a2_latest_effective_joint_20260927",
                    policy_roster=["capacity_hgb", "capacity_rl_two_seed_ensemble"],
                    policy_training_capacity=[True, True],
                    reference_training_capacity=[False, False],
                    account_2025_capacity_fraction=.01, initial_cash=1_000_000.,
                    cost_bps_each_side=10., max_weight=.1, max_positions=20,
                    max_invested=.95, missing_signal_policy="cash",
                    signal_window=["2025-01-01", "2025-12-29"],
                    labels="price-index coordinate proxy; no shareholder total return certification",
                    selection="none after this freeze; 2025 diagnostics cannot change models or settings",
                    file_sha256=hashes)
    write_json(out / "PRE_REPLAY_FREEZE.json", manifest)
    (out / "PRE_REPLAY_FREEZE.sha256").write_text(
        sha(out / "PRE_REPLAY_FREEZE.json") + "\n", encoding="ascii")
    print(json.dumps(dict(status=manifest["status"], files=len(hashes),
                          manifest_sha256=sha(out / "PRE_REPLAY_FREEZE.json"))), flush=True)


def verify_freeze(out: Path) -> dict:
    manifest_path = out / "PRE_REPLAY_FREEZE.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = (out / "PRE_REPLAY_FREEZE.sha256").read_text(encoding="ascii").strip()
    if sha(manifest_path) != expected or manifest["status"] != "FROZEN_BEFORE_2025_CAPACITY_COMPARISON":
        raise RuntimeError("2025_FREEZE_MANIFEST_CHANGED")
    if manifest["policy_roster"] != ["capacity_hgb", "capacity_rl_two_seed_ensemble"]:
        raise RuntimeError("2025_POLICY_ROSTER_CHANGED")
    for name, expected_hash in manifest["file_sha256"].items():
        path = (ROOT / name).resolve()
        if not path.is_file() or sha(path) != expected_hash:
            raise RuntimeError(f"FROZEN_COMPONENT_CHANGED:{name}")
    if (out / "COMPLETE.json").exists():
        raise RuntimeError("PRESERVE_COMPLETED_2025_COMPARISON")
    return manifest


class Stateful:
    def __init__(self, policy, with_held_age: bool):
        self.policy = policy
        self.with_held_age = with_held_age
        self.age: dict[str, int] = {}

    def __call__(self, day: pd.DataFrame, weights: dict[str, float], cash: float):
        self.age = {ticker: self.age.get(ticker, 0) + 1
                    for ticker, weight in weights.items() if weight > 0}
        if self.with_held_age:
            return self.policy(day, weights, cash, held_age=self.age)
        return self.policy(day, weights, cash)


def result_metrics(result, name: str) -> dict:
    daily = result.daily
    nav = np.r_[1_000_000., daily.nav.to_numpy(float)]
    certified = bool(np.isfinite(nav).all() and daily.valuation_status.eq("certified").all())
    diagnostic = result.diagnostics
    cap_count = int((diagnostic.code == "capacity_limited").sum()) if len(diagnostic) else 0
    return dict(policy=name, days=len(daily),
                net_price_coordinate_return=float(nav[-1] / nav[0] - 1) if certified else None,
                max_drawdown=float((nav / np.maximum.accumulate(nav) - 1).min()) if certified else None,
                terminal_indicative_nav=float(nav[-1]) if np.isfinite(nav[-1]) else None,
                fee_dollars=float(daily.transaction_cost_amount.sum()),
                average_cash_weight=float(daily.cash_weight.mean()),
                average_actual_exposure=float(1. - daily.cash_weight.mean()),
                min_cash_dollars=float(daily.cash.min()),
                max_actual_names=int(daily.actual_name_count.max()),
                capacity_limited_orders=cap_count,
                trades=len(result.trades),
                uncertified_days=int((daily.valuation_status != "certified").sum()),
                max_abs_cash_error=float(daily.cash_flow_identity_error.abs().max()),
                max_abs_cost_error=float(daily.cost_identity_error.abs().max()),
                max_abs_nav_error=float(daily.nav_identity_error.abs().max()))


def run(out: Path) -> None:
    manifest = verify_freeze(out)
    import joint_neural
    from followup_review.capacity_aware_revision.nav_context_adapter import get_engine
    from followup_review.capacity_aware_supervised.policy import load_policy_capacity_hgb
    from followup_review.capacity_aware_rl.train_capacity_rl import CapacityRLAdapter
    features = list(joint_neural.FEATURES)
    keep = ["signal_date", "ticker", "new_buy_eligible"] + features
    panel = pd.read_parquet(PANEL, columns=keep,
                            filters=[("signal_date", ">=", pd.Timestamp("2025-01-01")),
                                     ("signal_date", "<=", pd.Timestamp("2025-12-29"))])
    prices = pd.read_parquet(PRICE, columns=["ticker", "trade_date", "open", "close"],
                             filters=[("trade_date", ">=", pd.Timestamp("2025-01-01"))])
    if panel.empty or prices.empty or panel.signal_date.max() >= pd.Timestamp("2026-01-01") or prices.trade_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("2025_INPUT_TIME_BOUNDARY")
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    if len(calendar) != 250 or panel.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("2025_INPUT_KEY_OR_CALENDAR_MISMATCH")
    policies = (("capacity_hgb", load_policy_capacity_hgb(
                    stage="validation", artifacts_root=HGB / "out"), True),
                ("capacity_rl_two_seed_ensemble", CapacityRLAdapter(stage="validation"), False))
    rows = []
    for name, policy, with_age in policies:
        output = out / name
        if output.exists():
            raise RuntimeError(f"PRESERVE_EXISTING_POLICY_OUTPUT:{name}")
        with threadpool_limits(limits=2):
            result = get_engine().run_replay(
                prices, calendar, panel, Stateful(policy, with_age), candidate=name,
                initial_cash=1_000_000., cost_bps=10., max_weight=.1,
                max_positions=20, max_invested=.95, capacity_fraction=.01,
                missing_signal_policy="cash", signal_start="2025-01-01",
                signal_end="2025-12-29")
        output.mkdir()
        for key in OUTPUT_KEYS:
            getattr(result, key).to_parquet(output / f"{key}.parquet", index=False)
        write_json(output / "metadata.json", result.metadata)
        rows.append(result_metrics(result, name))
        pd.DataFrame(rows).to_csv(out / "comparison.csv", index=False)
        print(json.dumps(rows[-1], sort_keys=True), flush=True)
    for name, expected_hash in manifest["file_sha256"].items():
        if sha((ROOT / name).resolve()) != expected_hash:
            raise RuntimeError(f"FROZEN_COMPONENT_CHANGED_AFTER_REPLAY:{name}")
    write_json(out / "COMPLETE.json", dict(status="TWO_POLICY_2025_CAPACITY_COMPARISON_COMPLETE",
                                          freeze_sha256=sha(out / "PRE_REPLAY_FREEZE.json"),
                                          new_market_fits=0, new_rl_updates=0,
                                          inference_2026=0, policies=rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run"))
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    freeze(arguments.out) if arguments.phase == "freeze" else run(arguments.out)
