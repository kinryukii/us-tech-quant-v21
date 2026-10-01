"""Post-replay, read-only R7/R8 valuation-gap comparison for the joint batch.

This diagnostic script was written after the R8 policy replay and is not a
pre-score frozen report program. It imports the existing classification logic,
reads saved account files, and never predicts, fits or advances an account.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
VALUATION = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(VALUATION))
from price_overlay import gate_prices_with_r7_exact  # noqa: E402
from price_overlay_r8_mu_t import gate_prices_with_r8_mu_t_exact  # noqa: E402
from summarize_replay_valuation import classify_gaps  # noqa: E402


OUT = HERE / "R8_CAUSAL_VALUATION_COMPARISON_20260927_01"
OLD = VALUATION / "FOUR_SCENARIO_CAUSAL_VALUATION_20260927_01"
REPLAY = VALUATION / "R8_2026_MU_T"
ROSTER = ["joint_ridge", "joint_elastic_net", "joint_logistic", "joint_hgb",
          "joint_q10", "joint_q50", "joint_q90", "joint_quantile_risk",
          "joint_mlp", "joint_rl_ensemble", "joint_rl_zero_control",
          "hgb_return_baseline", "joint_hgb_lw", "joint_hgb_pca"]
SCENARIO_MAP = {"original": ("original_r7_conditional", "original_r8"),
                "v2": ("v2_r7_conditional", "v2_r8")}


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def summary(gaps: pd.DataFrame, accounts: pd.DataFrame, scenario: str) -> dict:
    g = gaps.loc[gaps.scenario.eq(scenario)]
    a = accounts.loc[accounts.scenario.eq(scenario)]
    terminal = a.loc[a.date.eq(pd.Timestamp("2026-09-24"))]
    if len(g) and g[["policy", "ticker", "date"]].duplicated().any():
        raise ValueError(f"Duplicate gap position-days in {scenario}")
    return {
        "scenario": scenario,
        "unique_security_dates": len(g[["ticker", "date"]].drop_duplicates()),
        "policy_position_days": len(g),
        "uncertified_account_dates": len(a),
        "max_account_date_unverified_fraction": float(a.unverified_fraction_indicative_nav.max()) if len(a) else 0.0,
        "terminal_uncertified_accounts": len(terminal),
        "terminal_max_account_unverified_fraction": float(terminal.unverified_fraction_indicative_nav.max()) if len(terminal) else 0.0,
        "unknown_value_rows": int(g.market_value.isna().sum()) if len(g) else 0,
    }


def main() -> None:
    if OUT.exists():
        raise ValueError("Preserve existing R8 valuation comparison; output already exists")
    price_path = ROOT / "data/test_prices.parquet"
    r7_overlay = VALUATION / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r7_receipt = VALUATION / "R7_OVERLAY_RECEIPT.json"
    r8_overlay = HERE / "R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r8_receipt = HERE / "R8_MU_T_OVERLAY_RECEIPT.json"
    freeze_path = REPLAY / "PRE_R8_REPLAY_FREEZE.json"
    freeze = load_json(freeze_path)
    if freeze["status"] != "R8_MU_T_POLICY_INDEPENDENT_EVALUATION_REPLAY_FROZEN" or freeze["roster"] != ROSTER:
        raise ValueError("R8 frozen cohort differs from original joint roster")
    for relative in ("data/test_prices.parquet", "followup_review/valuation/R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
                     "followup_review/valuation/R7_OVERLAY_RECEIPT.json",
                     "followup_review/valuation/r8_mu_t/R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
                     "followup_review/valuation/r8_mu_t/R8_MU_T_OVERLAY_RECEIPT.json",
                     "followup_review/valuation/price_overlay_r8_mu_t.py", "engine.py"):
        if sha(ROOT / relative) != freeze["input_files_sha256"][relative]:
            raise ValueError(f"Frozen R8 input changed: {relative}")
    if sha(price_path) != "d056d46fc7d45b8eaaad770b2767ddb14b5d055dd7b17d6e9a0aedc463f68c91":
        raise ValueError("Joint 2026 price source changed")
    old_receipt_path = OLD / "RECEIPT.json"
    old_receipt = load_json(old_receipt_path)
    if old_receipt["status"] != "FOUR_FROZEN_SCENARIO_VALUATION_GAP_COMPARISON_COMPLETE" or old_receipt["roster"] != ROSTER:
        raise ValueError("Prior R7 gap comparison identity changed")
    old_files = {"VALUATION_GAP_DETAIL.parquet": OLD / "VALUATION_GAP_DETAIL.parquet",
                 "ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv": OLD / "ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv"}
    for name, path in old_files.items():
        if sha(path) != old_receipt["output_sha256"][name]:
            raise ValueError(f"Saved R7 diagnostic changed: {name}")
    old_lineage = [x for x in old_receipt["scenario_lineage"]
                   if x["scenario"] in {"original_r7_conditional", "v2_r7_conditional"}]
    if len(old_lineage) != 28:
        raise ValueError("R7 comparison does not bind 28 policy accounts")
    for row in old_lineage:
        folder = Path(row["source_directory"])
        if not folder.is_relative_to(ROOT) or sha(folder / "positions.parquet") != row["positions_sha256"] or \
           sha(folder / "daily.parquet") != row["daily_sha256"]:
            raise ValueError("R7 account source changed since saved diagnostic")

    original_prices = pd.read_parquet(price_path)
    r7_prices, r7_gate = gate_prices_with_r7_exact(
        original_prices, raw_price_sha256=sha(price_path), overlay_path=r7_overlay,
        expected_overlay_sha256=sha(r7_overlay), receipt_path=r7_receipt,
        expected_receipt_sha256=sha(r7_receipt))
    r8_prices, r8_gate = gate_prices_with_r8_mu_t_exact(
        r7_prices, raw_prices=original_prices, raw_price_sha256=sha(price_path),
        overlay_path=r8_overlay, expected_overlay_sha256=sha(r8_overlay),
        receipt_path=r8_receipt, expected_receipt_sha256=sha(r8_receipt))
    if r7_gate["r7_exact_keys_restored"] != 811 or r8_gate["r8_mu_t_exact_keys_restored"] != 301:
        raise ValueError("Effective price gate changed")

    gap_parts, account_parts, r8_lineage = [], [], []
    for version, (_, scenario) in SCENARIO_MAP.items():
        path = REPLAY / version
        complete_path, identity_path, gate_path = [path / name for name in ("COMPLETE.json", "SCENARIO_IDENTITY.json", "PRICE_GATE.json")]
        complete, identity, gate = map(load_json, (complete_path, identity_path, gate_path))
        if complete["status"] != "R8_MU_T_FROZEN_POLICY_REPLAY_COMPLETE" or complete["version"] != version or \
           complete["policies_run"] != ROSTER or complete["fit_guard_attempts"] != 0 or \
           complete["days"] != 183 or float(complete["cost_bps_each_side"]) != 10:
            raise ValueError(f"R8 {version} account replay incomplete or altered")
        if identity["r8_freeze_sha256"] != sha(freeze_path) or identity["version"] != version or \
           identity["policies"] != ROSTER or identity["fitted_2026_rows"] != 0 or \
           identity["policy_selected_using_2026"] is not False:
            raise ValueError(f"R8 {version} identity differs from pre-replay freeze")
        if gate["r7"]["overlay_sha256"] != sha(r7_overlay) or gate["r8"]["r8_overlay_sha256"] != sha(r8_overlay) or \
           gate["r8"]["r8_mu_t_exact_keys_restored"] != 301 or gate["r8"]["remaining_warning_rows"] != 31915:
            raise ValueError(f"R8 {version} price gate receipt differs")
        r8_lineage.append({"scenario": scenario, "identity_sha256": sha(identity_path),
                           "complete_sha256": sha(complete_path), "price_gate_sha256": sha(gate_path)})
        for policy in ROSTER:
            folder = path / f"{policy}_10bps"
            positions_path, daily_path = folder / "positions.parquet", folder / "daily.parquet"
            positions, daily = pd.read_parquet(positions_path), pd.read_parquet(daily_path)
            gap, account = classify_gaps(positions, daily, r8_prices, scenario, policy, folder, False)
            gap_parts.append(gap)
            account_parts.append(account)
            r8_lineage.append({"scenario": scenario, "policy": policy,
                               "positions_sha256": sha(positions_path), "daily_sha256": sha(daily_path),
                               "position_rows": len(positions), "daily_rows": len(daily)})
    r8_gaps = pd.concat(gap_parts, ignore_index=True)
    r8_accounts = pd.concat(account_parts, ignore_index=True)
    old_gaps = pd.read_parquet(old_files["VALUATION_GAP_DETAIL.parquet"])
    old_accounts = pd.read_csv(old_files["ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv"], parse_dates=["date"])
    old_names = {"original_r7_conditional", "v2_r7_conditional"}
    old_gaps = old_gaps.loc[old_gaps.scenario.isin(old_names)].copy()
    old_accounts = old_accounts.loc[old_accounts.scenario.isin(old_names)].copy()
    if len(old_gaps) == 0 or len(old_accounts) == 0:
        raise ValueError("Prior R7 gap/account evidence absent")
    comparison_gaps = pd.concat([old_gaps, r8_gaps], ignore_index=True)
    comparison_accounts = pd.concat([old_accounts, r8_accounts], ignore_index=True)
    scenarios = ["original_r7_conditional", "original_r8", "v2_r7_conditional", "v2_r8"]
    stats = [summary(comparison_gaps, comparison_accounts, name) for name in scenarios]
    all_keys = comparison_gaps[["scenario", "reason", "ticker", "date"]].drop_duplicates()
    counts = comparison_gaps.groupby(["scenario", "reason"]).size().rename("policy_position_days").reset_index()
    counts = counts.merge(all_keys.groupby(["scenario", "reason"]).size().rename("unique_security_dates").reset_index(),
                          on=["scenario", "reason"], validate="one_to_one")
    deltas = []
    for version, (prior, revised) in SCENARIO_MAP.items():
        before = comparison_gaps.loc[comparison_gaps.scenario.eq(prior), ["ticker", "date"]].drop_duplicates()
        after = comparison_gaps.loc[comparison_gaps.scenario.eq(revised), ["ticker", "date"]].drop_duplicates()
        diff = before.merge(after, on=["ticker", "date"], how="outer", indicator=True)
        before_account = next(x for x in stats if x["scenario"] == prior)
        after_account = next(x for x in stats if x["scenario"] == revised)
        deltas.append({
            "version": version, "r7_unique_security_dates": len(before),
            "r8_unique_security_dates": len(after),
            "old_keys_no_longer_gaps": int(diff._merge.eq("left_only").sum()),
            "new_gap_keys_after_causal_replay": int(diff._merge.eq("right_only").sum()),
            "common_gap_keys": int(diff._merge.eq("both").sum()),
            "r7_policy_position_days": before_account["policy_position_days"],
            "r8_policy_position_days": after_account["policy_position_days"],
            "r7_uncertified_account_dates": before_account["uncertified_account_dates"],
            "r8_uncertified_account_dates": after_account["uncertified_account_dates"],
            "r7_max_account_unverified_fraction": before_account["max_account_date_unverified_fraction"],
            "r8_max_account_unverified_fraction": after_account["max_account_date_unverified_fraction"],
        })
    focus = comparison_gaps.loc[comparison_gaps.ticker.isin(["MU", "T", "SLMT", "EXAS", "EA", "DTP", "MSTLW", "FLYX"])]
    focus_counts = focus.groupby(["scenario", "ticker", "reason"]).size().rename("policy_position_days").reset_index()
    focus_counts = focus_counts.merge(
        focus[["scenario", "ticker", "reason", "date"]].drop_duplicates()
        .groupby(["scenario", "ticker", "reason"]).size().rename("unique_security_dates").reset_index(),
        on=["scenario", "ticker", "reason"], validate="one_to_one")

    OUT.mkdir(parents=True)
    files = {
        "R8_GAP_DETAIL.parquet": r8_gaps,
        "R8_ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv": r8_accounts,
        "R7_R8_CAUSE_COMPARISON.csv": counts,
        "R7_R8_SCENARIO_COMPARISON.csv": pd.DataFrame(stats),
        "R7_TO_R8_CAUSAL_KEY_TRANSITIONS.csv": pd.DataFrame(deltas),
        "R7_R8_PRIORITY_TICKER_GAPS.csv": focus_counts,
    }
    for name, frame in files.items():
        if name.endswith(".parquet"):
            frame.to_parquet(OUT / name, index=False)
        else:
            frame.to_csv(OUT / name, index=False)
    result = {
        "status": "R8_POST_REPLAY_READ_ONLY_VALUATION_DIAGNOSTIC_COMPLETE",
        "pre_score_frozen_report_code": False,
        "scope": "2026 evaluation, 10 bp; original/v2 frozen-policy R7 versus R8 MU/T price gate",
        "r8_freeze_sha256": sha(freeze_path),
        "prior_r7_summary_receipt_sha256": sha(old_receipt_path),
        "r7_gate": r7_gate, "r8_gate": r8_gate,
        "scenario_stats": stats, "causal_key_transitions": deltas,
        "r7_account_lineage": old_lineage,
        "r8_account_lineage": r8_lineage,
        "source_sha256": {"price": sha(price_path), "r7_overlay": sha(r7_overlay),
                          "r7_receipt": sha(r7_receipt), "r8_overlay": sha(r8_overlay),
                          "r8_receipt": sha(r8_receipt),
                          "prior_r7_gap_detail": sha(old_files["VALUATION_GAP_DETAIL.parquet"]),
                          "prior_r7_account_dates": sha(old_files["ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv"]),
                          "classifier_code": sha(VALUATION / "summarize_replay_valuation.py"),
                          "script": sha(Path(__file__))},
        "output_sha256": {name: sha(OUT / name) for name in files},
        "new_fit_calls": 0, "new_model_inference_calls": 0, "new_account_replay_calls": 0,
        "historical_vendor_receipt_certified": False,
        "shareholder_total_return_certified": False,
        "limitations": "R8 derives policy-independent quote eligibility from post-test official page reads and original price-coordinate data. Old R7 and new R8 account paths are causal replays but this report code was written after replay; no blind-test or total-return certification.",
    }
    (OUT / "RECEIPT.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "scenario_stats": stats,
                      "causal_key_transitions": deltas}, ensure_ascii=False))


if __name__ == "__main__":
    main()
