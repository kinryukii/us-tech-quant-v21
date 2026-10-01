"""Thin, versioned 2025 replay for seven estimators and their quantile policy.

Reuse the joint batch's frozen policy, 2025 feature projection and account
engine. Do not run the original run_suite.main, whose output root is fixed.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
V2_BUNDLE = ROOT / "joint_linear_tree_coverage_v2" / "bundle"
sys.path.insert(0, str(V2_BUNDLE))

import joint_linear_tree  # noqa: E402
from engine import run_replay  # noqa: E402
from run_suite import Stateful, forbid_fitting, metrics  # noqa: E402
from v2_policy import load_policy_v2  # noqa: E402


ESTIMATOR_NAMES = [
    "joint_ridge", "joint_elastic_net", "joint_logistic", "joint_hgb",
    "joint_q10", "joint_q50", "joint_q90",
]
NAMES = ESTIMATOR_NAMES + ["joint_quantile_risk"]
SOURCE = ROOT / "data" / "pre2026_joint_context.parquet"
PRICE = ROOT.parent / "a2_strict_method_retrain_20260926" / "results" / "pre2026_original_price_coordinate.parquet"
BASELINE = ROOT.parent / "a2_strict_method_retrain_20260926" / "results" / "hgb" / "pre2026_oof.parquet"
ORIGINAL_EVAL = ROOT / "evaluation_2025"


class V2Stateful(Stateful):
    def __init__(self, name: str, artifact_root: Path):
        self.name, self.age, self.lastdate, self.records = name, {}, None, []
        self.policy = load_policy_v2(name.removeprefix("joint_"),
                                     stage="validation", artifacts_root=artifact_root)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False,
                               default=str, allow_nan=False), encoding="utf-8")


def selected_models(artifact_root: Path) -> dict[str, dict]:
    receipt_path = artifact_root / "FIT_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    selected = {}
    for policy in ESTIMATOR_NAMES:
        name = policy.removeprefix("joint_")
        fits = [r for r in receipt["fits"] if r["stage"] == "validation" and r["name"] == name]
        if len(fits) != 1:
            raise RuntimeError(f"Expected one validation fit for {name}, got {len(fits)}")
        repairs = [r for r in receipt.get("numerical_repairs", [])
                   if r["stage"] == "validation" and r["name"] == name and r["used_for_policy"]]
        record = repairs[-1] if repairs else fits[0]
        model_path = artifact_root / Path(record["artifact"]).name
        if sha(model_path) != record["artifact_sha256"]:
            raise RuntimeError(f"v2 model hash mismatch: {name}")
        selected[name] = dict(path=str(model_path), sha256=record["artifact_sha256"])
    return selected


def source_boundary(path: Path, date_column: str) -> dict:
    parquet = pq.ParquetFile(path)
    index = parquet.schema.names.index(date_column)
    groups = []
    for i in range(parquet.metadata.num_row_groups):
        group = parquet.metadata.row_group(i)
        stats = group.column(index).statistics
        if stats is None or not stats.has_min_max:
            raise RuntimeError(f"Missing source date statistics: {path} row group {i}")
        low, high = pd.Timestamp(stats.min), pd.Timestamp(stats.max)
        if high >= pd.Timestamp("2026-01-01"):
            raise RuntimeError(f"Source row group reaches test year: {path} row group {i}")
        groups.append(dict(index=i, rows=group.num_rows, minimum=str(low), maximum=str(high)))
    return dict(date_column=date_column, row_groups=groups)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2-artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact_root = args.v2_artifacts.resolve()
    out = args.output.resolve()
    if not artifact_root.is_relative_to(ROOT) or artifact_root == (ROOT / "joint_linear_tree_artifacts"):
        raise RuntimeError("v2 model root must be separate and inside this joint batch")
    if not out.is_relative_to(ROOT) or out == ORIGINAL_EVAL or not out.name.startswith("evaluation_2025_"):
        raise RuntimeError("v2 output must be a separate evaluation_2025_* directory in this batch")
    if out.exists() and any(out.iterdir()):
        raise RuntimeError("v2 output is not empty; preserve all attempts and use a fresh versioned output")
    if not (artifact_root / "FIT_RECEIPT.json").is_file():
        raise RuntimeError("Missing v2 FIT_RECEIPT.json")
    receipt = json.loads((artifact_root / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS" or receipt.get("revision") != "DATE_COMPLETE_WITHIN_DAY_HASH_V2":
        raise RuntimeError("v2 fit receipt is not complete or has the wrong sampling revision")
    models = selected_models(artifact_root)
    source_boundaries = {
        str(SOURCE): source_boundary(SOURCE, "signal_date"),
        str(PRICE): source_boundary(PRICE, "trade_date"),
        str(BASELINE): source_boundary(BASELINE, "signal_date"),
    }
    original_hashes = {name: sha(ORIGINAL_EVAL / name) for name in
                       ("COMPLETE.json", "comparison.csv")}
    frozen = dict(
        status="PRE2026_SAMPLING_V2_2025_REPLAY_FROZEN",
        batch="a2_latest_effective_joint_20260927",
        scope="seven new validation estimators and their quantile-risk derived policy; no 2026 inference or selection",
        policies=NAMES,
        derived_policy_dependencies={"joint_quantile_risk": ["q10", "q50", "q90"]},
        initial_cash=1_000_000.0,
        cost_bps_each_side=10.0,
        capacity_fraction_signal_day_adv=.01,
        max_weight=.10,
        max_positions=20,
        max_invested=.95,
        missing_signal_policy="cash",
        signal_end="2025-12-29",
        policy_loader="joint_linear_tree_coverage_v2/bundle/v2_policy.py:load_policy_v2",
        v2_fit_receipt_sha256=sha(artifact_root / "FIT_RECEIPT.json"),
        validation_models=models,
        source_sha256={str(p): sha(p) for p in (SOURCE, PRICE, BASELINE)},
        source_row_group_pre2026_boundaries=source_boundaries,
        code_sha256={str(p.relative_to(ROOT)): sha(p) for p in
                     (ROOT / "engine.py", ROOT / "run_suite.py", ROOT / "joint_linear_tree.py",
                      V2_BUNDLE / "v2_policy.py",
                      Path(__file__).resolve())},
        original_2025_result_sha256=original_hashes,
    )
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "PRE_REPLAY_FREEZE.json", frozen)
    print("V2_PRE2026_REPLAY_FROZEN", out, flush=True)

    features = list(joint_linear_tree.FEATURES)
    keep = ["signal_date", "ticker", "new_buy_eligible"] + features
    panel = pd.read_parquet(SOURCE, columns=keep,
                            filters=[("signal_date", ">=", pd.Timestamp("2025-01-01")),
                                     ("signal_date", "<=", pd.Timestamp("2025-12-29"))])
    prices = pd.read_parquet(PRICE, columns=["ticker", "trade_date", "open", "close"],
                             filters=[("trade_date", ">=", pd.Timestamp("2025-01-01"))])
    score = pd.read_parquet(BASELINE, columns=["signal_date", "ticker", "prediction"],
                            filters=[("signal_date", ">=", pd.Timestamp("2025-01-01")),
                                     ("signal_date", "<=", pd.Timestamp("2025-12-29"))])
    for frame, date_col in ((panel, "signal_date"), (prices, "trade_date"), (score, "signal_date")):
        if frame.empty or frame[date_col].max() >= pd.Timestamp("2026-01-01"):
            raise RuntimeError("Input is empty or reaches the test year")
    score = score.rename(columns={"prediction": "baseline_hgb"})
    panel = panel.merge(score, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    if panel.baseline_hgb.isna().any():
        raise RuntimeError("Missing time-legal 2025 baseline score")
    panel = panel[["signal_date", "ticker", "new_buy_eligible", "baseline_hgb"] + features]
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    if len(calendar) != 250:
        raise RuntimeError(f"Unexpected 2025 calendar length: {len(calendar)}")
    fit_guard = forbid_fitting()
    rows = []
    for name in NAMES:
        # Reuse the original wrapper's age/state progression and call path.
        actor = V2Stateful(name, artifact_root)
        with threadpool_limits(limits=2):
            result = run_replay(
                prices, calendar, panel, actor, candidate=name,
                initial_cash=1_000_000.0, cost_bps=10.0, max_weight=.10,
                max_positions=20, max_invested=.95, capacity_fraction=.01,
                missing_signal_policy="cash", signal_start="2025-01-01",
                signal_end="2025-12-29",
            )
        destination = out / f"{name}_10bps"
        destination.mkdir(exist_ok=False)
        for key in ("daily", "trades", "positions", "target_decisions",
                    "diagnostics", "valuation_intervals"):
            getattr(result, key).to_parquet(destination / f"{key}.parquet", index=False)
        write_json(destination / "metadata.json", result.metadata)
        row = metrics(result, name, 10.0, 2025)
        rows.append(row)
        pd.DataFrame(rows).to_csv(out / "comparison.partial.csv", index=False)
        print("V2_2025_REPLAY_POLICY", name, "days", row["days"], "trades", row["trades"], flush=True)
        del result, actor
        gc.collect()
    if fit_guard["attempts"] != 0:
        raise RuntimeError("Unexpected fit attempted during 2025 replay")
    if {name: sha(ORIGINAL_EVAL / name) for name in original_hashes} != original_hashes:
        raise RuntimeError("Original 2025 result changed")
    (out / "comparison.partial.csv").replace(out / "comparison.csv")
    write_json(out / "COMPLETE.json", dict(
        status="PRE2026_V2_VALIDATION_COMPLETE", policies=NAMES,
        evaluations=len(rows), fit_guard_attempts=fit_guard["attempts"],
        training_2026_rows=0, test_2026_predictions=0,
        original_2025_result_unchanged=True,
        price_interpretation="index-coordinate research return, not shareholder total return",
    ))
    print("V2_2025_REPLAY_COMPLETE", len(rows), flush=True)


if __name__ == "__main__":
    main()
