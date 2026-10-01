"""R9 AAPL price-evidence replay through the existing joint policy and ledger.

This is an evaluation-only, exact-key price-coordinate gate. The frozen chain
is R7 -> R8 MU/T -> R9 AAPL. It never trains or selects a policy.
"""
from __future__ import annotations

import argparse
import gc
from pathlib import Path

import pandas as pd
from threadpoolctl import threadpool_limits

import replay_r8_mu_t as r8
from price_overlay_r9_aapl import gate_prices_with_r9_aapl_exact

ROOT = r8.ROOT
HERE = r8.HERE
prior = r8.prior
OUT = HERE / "R9_2026_AAPL"
FREEZE = OUT / "PRE_R9_REPLAY_FREEZE.json"
R9_OVERLAY = HERE / "r9_aapl" / "R9_AAPL_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
R9_RECEIPT = HERE / "r9_aapl" / "R9_AAPL_OVERLAY_RECEIPT.json"
R9_EVIDENCE = (
    "R9_AAPL_SCOPE_BEFORE_REPLAY.md",
    "aapl_triage/EVENT_PUBLIC_SOURCES.json",
    "aapl_triage/TRIAGE_REPORT.md",
    "r9_aapl/build_r9_aapl_gate.py",
    "r9_aapl/R9_AAPL_THREE_EVENT_VERDICTS.csv",
    "r9_aapl/R9_AAPL_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
    "r9_aapl/R9_AAPL_OVERLAY_RECEIPT.json",
    "r9_aapl/verify_r9_aapl_adapter.py",
    "r9_aapl/R9_ADAPTER_TECHNICAL_CHECK.json",
    "price_overlay_r9_aapl.py",
    "replay_r9_aapl.py",
    "run_r9_aapl_container.ps1",
)
SCENARIOS = r8.SCENARIOS
STATUS = "R9_AAPL_POLICY_INDEPENDENT_EVALUATION_REPLAY_FROZEN"


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def input_files() -> dict[str, str]:
    """Bind only original inputs, pre-score identities and exact-key evidence."""
    r8_frozen = r8.read_json(r8.FREEZE)
    if (r8_frozen.get("status") != "R8_MU_T_POLICY_INDEPENDENT_EVALUATION_REPLAY_FROZEN"
            or r8_frozen.get("image_id") != prior.FIXED_IMAGE
            or r8_frozen.get("roster") != prior.ROSTER
            or r8_frozen.get("scenarios") != SCENARIOS):
        raise RuntimeError("R8 pre-score freeze identity changed")
    if r8.input_files() != r8_frozen["input_files_sha256"]:
        raise RuntimeError("R8 source identity differs from its saved freeze")
    selected = dict(r8_frozen["input_files_sha256"])
    selected[relative(r8.FREEZE)] = r8.sha(r8.FREEZE)
    for name in R9_EVIDENCE:
        path = HERE / name
        if not path.is_file():
            raise RuntimeError(f"Missing R9 evidence or runner: {path}")
        selected[relative(path)] = r8.sha(path)
    if any(key.startswith("evaluation_2026/") for key in selected):
        raise RuntimeError("Prior 2026 economic results entered R9 input set")
    for key, expected in selected.items():
        if r8.sha(ROOT / key) != expected:
            raise RuntimeError(f"R9 input identity changed: {key}")
    return selected


def freeze() -> None:
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("Preserve existing R9 output")
    files = input_files()
    receipt = r8.read_json(R9_RECEIPT)
    if receipt.get("status") != "R9_AAPL_PRICE_GATE_PREPARED_NO_ACCOUNT_REPLAY":
        raise RuntimeError("R9 source evidence is not in prepared state")
    if receipt["input_sha256"]["prices"] != files["data/test_prices.parquet"]:
        raise RuntimeError("R9 evidence refers to a different original price source")
    if receipt["output_sha256"][R9_OVERLAY.name] != files[relative(R9_OVERLAY)]:
        raise RuntimeError("R9 overlay differs from its receipt")
    evidence_bindings = {
        "features": "data/test_features_context.parquet",
        "source_receipts": "data/PRICE_SOURCE_RECEIPTS.json",
        "r7_overlay": "followup_review/valuation/R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
        "r8_overlay": relative(r8.R8_OVERLAY),
        "issuer_web_facts": "followup_review/valuation/aapl_triage/EVENT_PUBLIC_SOURCES.json",
    }
    for receipt_key, source_key in evidence_bindings.items():
        if receipt["input_sha256"][receipt_key] != files[source_key]:
            raise RuntimeError(f"R9 {receipt_key} differs from bound source")
    verdicts = HERE / "r9_aapl" / "R9_AAPL_THREE_EVENT_VERDICTS.csv"
    if receipt["output_sha256"][verdicts.name] != files[relative(verdicts)]:
        raise RuntimeError("R9 event verdicts differ from their receipt")
    if (receipt["policy_independent_exact_price_keys"] != 158
            or receipt["prior_r7_keys_preserved_disjoint"] != 811
            or receipt["prior_r8_keys_preserved_disjoint"] != 301):
        raise RuntimeError("R9 exact-key domain differs from the fixed scope")
    r8_frozen = r8.read_json(r8.FREEZE)
    OUT.mkdir(parents=True, exist_ok=True)
    r8.write_json(FREEZE, dict(
        status=STATUS,
        batch=ROOT.name,
        prior_pre_score_freeze_sha256=r8.sha(prior.MANIFEST),
        prior_r8_replay_freeze_sha256=r8.sha(r8.FREEZE),
        image_id=prior.FIXED_IMAGE,
        input_files_sha256=files,
        roster=prior.ROSTER,
        scenarios=SCENARIOS,
        cost_bps_each_side=10,
        original_test_window=r8_frozen["original_test_window"],
        price_rule="R7 811 exact keys -> R8 MU/T 301 -> R9 AAPL 158; all other warnings gated",
        no_previous_2026_economic_results_mounted=True,
        no_model_fit_or_policy_selection=True,
        historical_2026_exposure_acknowledged=True,
        shareholder_total_return_certified=False,
    ))
    print("R9_AAPL_REPLAY_FROZEN", r8.sha(FREEZE), flush=True)


def run(version: str) -> None:
    if version not in SCENARIOS or not FREEZE.is_file():
        raise RuntimeError("Unknown scenario or missing R9 freeze")
    frozen = r8.read_json(FREEZE)
    if (frozen.get("status") != STATUS
            or frozen.get("scenarios") != SCENARIOS
            or frozen.get("roster") != prior.ROSTER
            or frozen.get("image_id") != prior.FIXED_IMAGE
            or frozen.get("prior_r8_replay_freeze_sha256") != r8.sha(r8.FREEZE)):
        raise RuntimeError("R9 freeze identity changed")
    for key, expected in frozen["input_files_sha256"].items():
        if r8.sha(ROOT / key) != expected:
            raise RuntimeError(f"R9 frozen input changed: {key}")
    destination = OUT / version
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError("Preserve existing R9 scenario")

    fit_guard = prior.forbid_fitting()
    # Market tables are read only after the full source/code identity gate.
    panel = pd.read_parquet(prior.TEST_PANEL)
    raw_prices = pd.read_parquet(prior.TEST_PRICES)
    calendar_frame = pd.read_parquet(prior.TEST_CALENDAR)
    calendar = pd.DatetimeIndex(calendar_frame.loc[calendar_frame.is_test, "trade_date"])
    base = r8.read_json(prior.MANIFEST)
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
    r8_prices, r8_gate = r8.gate_prices_with_r8_mu_t_exact(
        r7_prices, raw_prices=raw_prices,
        raw_price_sha256=base["runtime_files_sha256"]["data/test_prices.parquet"],
        overlay_path=r8.R8_OVERLAY,
        expected_overlay_sha256=frozen["input_files_sha256"][relative(r8.R8_OVERLAY)],
        receipt_path=r8.R8_RECEIPT,
        expected_receipt_sha256=frozen["input_files_sha256"][relative(r8.R8_RECEIPT)],
    )
    prices, r9_gate = gate_prices_with_r9_aapl_exact(
        r8_prices, raw_prices=raw_prices,
        raw_price_sha256=base["runtime_files_sha256"]["data/test_prices.parquet"],
        overlay_path=R9_OVERLAY,
        expected_overlay_sha256=frozen["input_files_sha256"][relative(R9_OVERLAY)],
        receipt_path=R9_RECEIPT,
        expected_receipt_sha256=frozen["input_files_sha256"][relative(R9_RECEIPT)],
    )
    if calendar.empty or calendar.max() != pd.Timestamp("2026-09-24"):
        raise RuntimeError("Unexpected joint-batch calendar")
    if (r7_gate["r7_exact_keys_restored"] != 811
            or r8_gate["r8_mu_t_exact_keys_restored"] != 301
            or r9_gate["r9_aapl_exact_keys_restored"] != 158):
        raise RuntimeError("Price-gate exact-key counts changed")
    panel = panel.loc[panel.signal_date.le("2026-09-22")].copy()
    baseline = prior.baseline_hgb_scores(panel)
    panel = panel.merge(baseline, on=["signal_date", "ticker"],
                        how="left", validate="one_to_one")
    keep = ["signal_date", "ticker", "new_buy_eligible", "baseline_hgb"] + list(prior.FEATURES)
    panel = panel[keep]

    destination.mkdir(parents=True, exist_ok=True)
    r8.write_json(destination / "PRICE_GATE.json", dict(r7=r7_gate, r8=r8_gate, r9=r9_gate))
    r8.write_json(destination / "SCENARIO_IDENTITY.json", dict(
        r9_freeze_sha256=r8.sha(FREEZE), version=version, policies=prior.ROSTER,
        cost_bps_each_side=10, original_test_price_sha256=r8.sha(prior.TEST_PRICES),
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
        r8.write_json(folder / "metadata.json", result.metadata)
        if actor.records:
            r8.write_json(folder / "risk_solver.json", actor.records)
        row = prior.safe_metrics(result, policy, 10)
        row["reused_result"] = False
        row["source_directory"] = relative(folder)
        rows.append(row)
        for key, field in (("cash", "max_abs_cash_error"),
                           ("cost", "max_abs_cost_error"),
                           ("nav", "max_abs_nav_error")):
            max_errors[key] = max(max_errors[key], float(row[field]))
        pd.DataFrame(rows).to_csv(destination / "comparison.partial.csv", index=False)
        print("R9_AAPL_POLICY", version, policy, row["days"], flush=True)
        del actor, result
        gc.collect()
    if fit_guard["attempts"] != 0 or max(max_errors.values()) >= 1e-6:
        raise RuntimeError("R9 fit or account invariant failed")
    (destination / "comparison.partial.csv").replace(destination / "comparison_all14.csv")
    r8.write_json(destination / "COMPLETE.json", dict(
        status="R9_AAPL_FROZEN_POLICY_REPLAY_COMPLETE", version=version,
        policies_run=prior.ROSTER, cost_bps_each_side=10,
        days=int(rows[0]["days"]), fit_guard_attempts=fit_guard["attempts"],
        account_max_errors=max_errors,
        original_test_window=frozen["original_test_window"],
        no_formal_shareholder_return=True,
    ))
    print("R9_AAPL_SCENARIO_COMPLETE", version, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--freeze", action="store_true")
    choice.add_argument("--run", choices=sorted(SCENARIOS))
    args = parser.parse_args()
    freeze() if args.freeze else run(args.run)


if __name__ == "__main__":
    main()
