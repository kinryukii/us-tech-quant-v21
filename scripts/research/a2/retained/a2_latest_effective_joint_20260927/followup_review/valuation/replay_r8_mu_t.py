"""Versioned MU/T price-evidence replay through the existing joint ledger.

Only evaluation prices change. Models, policies, actions, costs and accounting
come from the already frozen joint batch. No old 2026 results are mounted.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "followup_review" / "cost"))

import replay_2026_sampling_v2 as prior  # noqa: E402
from price_overlay_r8_mu_t import gate_prices_with_r8_mu_t_exact  # noqa: E402

OUT = HERE / "R8_2026_MU_T"
FREEZE = OUT / "PRE_R8_REPLAY_FREEZE.json"
R8_OVERLAY = HERE / "r8_mu_t" / "R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
R8_RECEIPT = HERE / "r8_mu_t" / "R8_MU_T_OVERLAY_RECEIPT.json"
R8_ADAPTER = HERE / "price_overlay_r8_mu_t.py"
R8_WRAPPER = HERE / "run_r8_mu_t_container.ps1"
R8_EVIDENCE = [
    "build_r8_mu_t_gate.py", "EVENT_PUBLIC_SOURCES.json",
    "R8_ADAPTER_TECHNICAL_CHECK.json", "R8_MU_T_FIVE_EVENT_VERDICTS.csv",
    "R8_MU_T_OVERLAY_RECEIPT.json", "R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
    "REPORT.md", "SOURCE_DOWNLOAD_ATTEMPTS.json", "verify_r8_mu_t_adapter.py",
]
SCENARIOS = {"original": "original", "v2": "v2"}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               default=str, allow_nan=False), encoding="utf-8")


def input_files() -> dict[str, str]:
    """Bind pre-score sources while excluding all previous economic results."""
    original = read_json(prior.MANIFEST)
    if original.get("status") != "JOINT_SAMPLING_V2_FULL_BATCH_FROZEN_BEFORE_REVISED_SCORING":
        raise RuntimeError("Original v2 batch freeze missing")
    if original.get("image_id") != prior.FIXED_IMAGE or original.get("roster") != prior.ROSTER:
        raise RuntimeError("Frozen image or policy roster changed")
    selected = {
        rel.replace("\\", "/"): expected
        for rel, expected in original["runtime_files_sha256"].items()
        if not rel.replace("\\", "/").startswith("evaluation_2026/")
    }
    extra = [prior.MANIFEST, R8_ADAPTER, R8_WRAPPER, Path(__file__).resolve()]
    extra += [HERE / "r8_mu_t" / name for name in R8_EVIDENCE]
    for path in extra:
        if not path.is_file():
            raise RuntimeError(f"Missing R8 evidence or runner: {path}")
        selected[str(path.relative_to(ROOT)).replace("\\", "/")] = sha(path)
    for relative, expected in selected.items():
        if sha(ROOT / relative) != expected:
            raise RuntimeError(f"Frozen source mismatch: {relative}")
    return selected


def freeze() -> None:
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("Preserve existing R8 output")
    files = input_files()
    original = read_json(prior.MANIFEST)
    receipt = read_json(R8_RECEIPT)
    if receipt["input_sha256"]["prices"] != files["data/test_prices.parquet"]:
        raise RuntimeError("R8 evidence refers to a different original price source")
    if receipt["output_sha256"][R8_OVERLAY.name] != files[
        str(R8_OVERLAY.relative_to(ROOT)).replace("\\", "/")
    ]:
        raise RuntimeError("R8 overlay not bound by its evidence receipt")
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(FREEZE, dict(
        status="R8_MU_T_POLICY_INDEPENDENT_EVALUATION_REPLAY_FROZEN",
        batch=ROOT.name,
        prior_pre_score_freeze_sha256=sha(prior.MANIFEST),
        image_id=prior.FIXED_IMAGE,
        input_files_sha256=files,
        roster=prior.ROSTER,
        scenarios=SCENARIOS,
        cost_bps_each_side=10,
        original_test_window=original["test_window"],
        price_rule="R7 811 exact keys plus R8 MU/T exact keys; FLYX remains gated",
        no_previous_2026_economic_results_mounted=True,
        no_model_fit_or_policy_selection=True,
        historical_2026_exposure_acknowledged=True,
        shareholder_total_return_certified=False,
    ))
    print("R8_MU_T_REPLAY_FROZEN", sha(FREEZE), flush=True)


def run(version: str) -> None:
    if version not in SCENARIOS or not FREEZE.is_file():
        raise RuntimeError("Unknown scenario or missing R8 freeze")
    frozen = read_json(FREEZE)
    if (frozen.get("status") != "R8_MU_T_POLICY_INDEPENDENT_EVALUATION_REPLAY_FROZEN"
            or frozen.get("scenarios") != SCENARIOS
            or frozen.get("roster") != prior.ROSTER
            or frozen.get("image_id") != prior.FIXED_IMAGE):
        raise RuntimeError("R8 freeze identity changed")
    for relative, expected in frozen["input_files_sha256"].items():
        if sha(ROOT / relative) != expected:
            raise RuntimeError(f"R8 frozen input changed: {relative}")
    destination = OUT / version
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError("Preserve existing R8 scenario")

    fit_guard = prior.forbid_fitting()
    # No 2026 table or economic result is deserialized before the identity gate.
    panel = pd.read_parquet(prior.TEST_PANEL)
    raw_prices = pd.read_parquet(prior.TEST_PRICES)
    calendar_frame = pd.read_parquet(prior.TEST_CALENDAR)
    calendar = pd.DatetimeIndex(calendar_frame.loc[calendar_frame.is_test, "trade_date"])
    base = read_json(prior.MANIFEST)
    r7_prices, r7_gate = prior.gate_prices_with_r7_exact(
        raw_prices,
        raw_price_sha256=base["runtime_files_sha256"]["data/test_prices.parquet"],
        overlay_path=prior.OVERLAY,
        expected_overlay_sha256=base["runtime_files_sha256"][
            "followup_review/valuation/R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"],
        receipt_path=prior.OVERLAY_RECEIPT,
        expected_receipt_sha256=base["runtime_files_sha256"][
            "followup_review/valuation/R7_OVERLAY_RECEIPT.json"],
    )
    prices, r8_gate = gate_prices_with_r8_mu_t_exact(
        r7_prices,
        raw_prices=raw_prices,
        raw_price_sha256=base["runtime_files_sha256"]["data/test_prices.parquet"],
        overlay_path=R8_OVERLAY,
        expected_overlay_sha256=frozen["input_files_sha256"][
            str(R8_OVERLAY.relative_to(ROOT)).replace("\\", "/")],
        receipt_path=R8_RECEIPT,
        expected_receipt_sha256=frozen["input_files_sha256"][
            str(R8_RECEIPT.relative_to(ROOT)).replace("\\", "/")],
    )
    if calendar.empty or calendar.max() != pd.Timestamp("2026-09-24"):
        raise RuntimeError("Unexpected joint-batch calendar")
    panel = panel.loc[panel.signal_date.le("2026-09-22")].copy()
    baseline = prior.baseline_hgb_scores(panel)
    panel = panel.merge(baseline, on=["signal_date", "ticker"],
                        how="left", validate="one_to_one")
    keep = ["signal_date", "ticker", "new_buy_eligible", "baseline_hgb"] + list(prior.FEATURES)
    panel = panel[keep]

    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "PRICE_GATE.json", dict(r7=r7_gate, r8=r8_gate))
    write_json(destination / "SCENARIO_IDENTITY.json", dict(
        r8_freeze_sha256=sha(FREEZE), version=version, policies=prior.ROSTER,
        cost_bps_each_side=10, original_test_price_sha256=sha(prior.TEST_PRICES),
        fitted_2026_rows=0, policy_selected_using_2026=False,
    ))
    rows = []
    max_errors = {"cash": 0.0, "cost": 0.0, "nav": 0.0}
    for policy in prior.ROSTER:
        actor = prior.VersionedStateful(policy, version)
        with threadpool_limits(limits=2):
            result = prior.run_replay(
                prices, calendar, panel, actor, candidate=policy,
                initial_cash=1_000_000.0, cost_bps=10.0,
                max_weight=.10, max_positions=20, max_invested=.95,
                capacity_fraction=.01, missing_signal_policy="cash",
                signal_start="2026-01-01", signal_end="2026-09-22",
            )
        folder = destination / f"{policy}_10bps"
        folder.mkdir(exist_ok=False)
        for key in ("daily", "trades", "positions", "target_decisions",
                    "diagnostics", "valuation_intervals"):
            getattr(result, key).to_parquet(folder / f"{key}.parquet", index=False)
        write_json(folder / "metadata.json", result.metadata)
        if actor.records:
            write_json(folder / "risk_solver.json", actor.records)
        row = prior.safe_metrics(result, policy, 10)
        row["reused_result"] = False
        row["source_directory"] = str(folder.relative_to(ROOT)).replace("\\", "/")
        rows.append(row)
        for key, field in (("cash", "max_abs_cash_error"),
                           ("cost", "max_abs_cost_error"), ("nav", "max_abs_nav_error")):
            max_errors[key] = max(max_errors[key], float(row[field]))
        pd.DataFrame(rows).to_csv(destination / "comparison.partial.csv", index=False)
        print("R8_MU_T_POLICY", version, policy, row["days"], flush=True)
        del actor, result
        gc.collect()
    if fit_guard["attempts"] != 0 or max(max_errors.values()) >= 1e-6:
        raise RuntimeError("R8 fit or account invariant failed")
    (destination / "comparison.partial.csv").replace(destination / "comparison_all14.csv")
    write_json(destination / "COMPLETE.json", dict(
        status="R8_MU_T_FROZEN_POLICY_REPLAY_COMPLETE", version=version,
        policies_run=prior.ROSTER, cost_bps_each_side=10,
        days=int(rows[0]["days"]), fit_guard_attempts=fit_guard["attempts"],
        account_max_errors=max_errors,
        original_test_window=frozen["original_test_window"],
        no_formal_shareholder_return=True,
    ))
    print("R8_MU_T_SCENARIO_COMPLETE", version, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--freeze", action="store_true")
    choice.add_argument("--run", choices=sorted(SCENARIOS))
    args = parser.parse_args()
    freeze() if args.freeze else run(args.run)


if __name__ == "__main__":
    main()
