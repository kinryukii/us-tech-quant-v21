"""Read-only R8/R9 frozen-account valuation comparison, written after R9 replay.

This is diagnostic code, not a pre-score frozen report or a policy selector. It
does not fit, predict, trade, or replay an account.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
VALUATION = HERE.parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(VALUATION), str(VALUATION / "r8_mu_t")]
from price_overlay import gate_prices_with_r7_exact  # noqa: E402
from price_overlay_r8_mu_t import gate_prices_with_r8_mu_t_exact  # noqa: E402
from price_overlay_r9_aapl import gate_prices_with_r9_aapl_exact  # noqa: E402
from summarize_replay_valuation import classify_gaps  # noqa: E402
from summarize_r8_valuation import ROSTER, load_json, sha, summary  # noqa: E402


OLD = VALUATION / "r8_mu_t/R8_CAUSAL_VALUATION_COMPARISON_20260927_01"
REPLAY = VALUATION / "R9_2026_AAPL"
OUT = HERE / "R9_CAUSAL_VALUATION_COMPARISON_20260927_01"
NAMES = {"original": ("original_r8", "original_r9"),
         "v2": ("v2_r8", "v2_r9")}


def _read_old() -> tuple[pd.DataFrame, pd.DataFrame, dict, Path]:
    receipt_path = OLD / "RECEIPT.json"
    if sha(receipt_path) != "e30bfb503b316fafaa0920aa09e37d0db35b7a47b105683a014e633afb234c82":
        raise ValueError("R8 post-replay receipt identity changed")
    receipt = load_json(receipt_path)
    if receipt["status"] != "R8_POST_REPLAY_READ_ONLY_VALUATION_DIAGNOSTIC_COMPLETE":
        raise ValueError("R8 post-replay diagnostic incomplete")
    expected = {"R8_GAP_DETAIL.parquet", "R8_ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv"}
    if not expected.issubset(receipt["output_sha256"]):
        raise ValueError("R8 diagnostic source files absent")
    for name, digest in receipt["output_sha256"].items():
        if sha(OLD / name) != digest:
            raise ValueError(f"R8 diagnostic output changed: {name}")
    account_rows = [x for x in receipt["r8_account_lineage"] if "policy" in x]
    if len(account_rows) != 28:
        raise ValueError("R8 diagnostic must bind 28 accounts")
    for row in account_rows:
        version = row["scenario"].split("_")[0]
        folder = VALUATION / "R8_2026_MU_T" / version / f'{row["policy"]}_10bps'
        if (sha(folder / "positions.parquet") != row["positions_sha256"] or
                sha(folder / "daily.parquet") != row["daily_sha256"]):
            raise ValueError(f"R8 account source changed: {version}/{row['policy']}")
    gaps = pd.read_parquet(OLD / "R8_GAP_DETAIL.parquet")
    accounts = pd.read_csv(OLD / "R8_ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv", parse_dates=["date"])
    if set(gaps.scenario.unique()) != {"original_r8", "v2_r8"} or \
       set(accounts.scenario.unique()) != {"original_r8", "v2_r8"}:
        raise ValueError("R8 diagnostic scenario identity changed")
    return gaps, accounts, receipt, receipt_path


def _key_table(gaps: pd.DataFrame, scenario: str) -> pd.DataFrame:
    subset = gaps.loc[gaps.scenario.eq(scenario)]
    return subset.groupby(["ticker", "date"], observed=True).agg(
        reason=("reason", lambda x: "|".join(sorted(set(x)))),
        policy_positions=("policy", "size"),
        max_indicative_market_value=("market_value", "max"),
    ).reset_index()


def _stats(gaps: pd.DataFrame, accounts: pd.DataFrame, scenario: str) -> dict:
    item = summary(gaps, accounts, scenario)
    rows = accounts.loc[accounts.scenario.eq(scenario)]
    item["max_account_date_unverified_indicative_usd"] = (
        float(rows.unverified_indicative_market_value.max()) if len(rows) else 0.0)
    return item


def main() -> None:
    if OUT.exists():
        raise ValueError("Preserve existing R9 valuation diagnostic; output already exists")
    freeze_path = REPLAY / "PRE_R9_REPLAY_FREEZE.json"
    freeze = load_json(freeze_path)
    if (freeze["status"] != "R9_AAPL_POLICY_INDEPENDENT_EVALUATION_REPLAY_FROZEN" or
            freeze["roster"] != ROSTER or float(freeze["cost_bps_each_side"]) != 10):
        raise ValueError("R9 frozen cohort/cost differs")
    for relative in (
        "data/test_prices.parquet", "engine.py",
        "followup_review/valuation/R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
        "followup_review/valuation/R7_OVERLAY_RECEIPT.json",
        "followup_review/valuation/price_overlay.py",
        "followup_review/valuation/r8_mu_t/R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
        "followup_review/valuation/r8_mu_t/R8_MU_T_OVERLAY_RECEIPT.json",
        "followup_review/valuation/price_overlay_r8_mu_t.py",
        "followup_review/valuation/r9_aapl/R9_AAPL_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
        "followup_review/valuation/r9_aapl/R9_AAPL_OVERLAY_RECEIPT.json",
        "followup_review/valuation/price_overlay_r9_aapl.py",
        "followup_review/valuation/summarize_replay_valuation.py",
    ):
        if sha(ROOT / relative) != freeze["input_files_sha256"][relative]:
            raise ValueError(f"Frozen R9 input changed: {relative}")
    old_gaps, old_accounts, old_receipt, old_receipt_path = _read_old()

    price_path = ROOT / "data/test_prices.parquet"
    raw_sha = sha(price_path)
    if raw_sha != "d056d46fc7d45b8eaaad770b2767ddb14b5d055dd7b17d6e9a0aedc463f68c91":
        raise ValueError("Joint 2026 price source changed")
    r7_overlay = VALUATION / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r7_receipt = VALUATION / "R7_OVERLAY_RECEIPT.json"
    r8_overlay = VALUATION / "r8_mu_t/R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r8_receipt = VALUATION / "r8_mu_t/R8_MU_T_OVERLAY_RECEIPT.json"
    r9_overlay = HERE / "R9_AAPL_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r9_receipt = HERE / "R9_AAPL_OVERLAY_RECEIPT.json"
    raw = pd.read_parquet(price_path)
    r7, g7 = gate_prices_with_r7_exact(
        raw, raw_price_sha256=raw_sha, overlay_path=r7_overlay,
        expected_overlay_sha256=sha(r7_overlay), receipt_path=r7_receipt,
        expected_receipt_sha256=sha(r7_receipt))
    r8, g8 = gate_prices_with_r8_mu_t_exact(
        r7, raw_prices=raw, raw_price_sha256=raw_sha, overlay_path=r8_overlay,
        expected_overlay_sha256=sha(r8_overlay), receipt_path=r8_receipt,
        expected_receipt_sha256=sha(r8_receipt))
    r9, g9 = gate_prices_with_r9_aapl_exact(
        r8, raw_prices=raw, raw_price_sha256=raw_sha, overlay_path=r9_overlay,
        expected_overlay_sha256=sha(r9_overlay), receipt_path=r9_receipt,
        expected_receipt_sha256=sha(r9_receipt))
    if (g7["r7_exact_keys_restored"] != 811 or
            g8["r8_mu_t_exact_keys_restored"] != 301 or
            g9["r9_aapl_exact_keys_restored"] != 158 or
            g9["remaining_warning_rows"] != 31757):
        raise ValueError("R9 price gate key count changed")
    del raw, r7, r8

    gap_parts, account_parts, lineage = [], [], []
    for version, (_, scenario) in NAMES.items():
        base = REPLAY / version
        complete_path = base / "COMPLETE.json"
        identity_path = base / "SCENARIO_IDENTITY.json"
        gate_path = base / "PRICE_GATE.json"
        complete, identity, gate = map(load_json, (complete_path, identity_path, gate_path))
        if (complete["status"] != "R9_AAPL_FROZEN_POLICY_REPLAY_COMPLETE" or
                complete["version"] != version or complete["policies_run"] != ROSTER or
                complete["fit_guard_attempts"] != 0 or complete["days"] != 183 or
                float(complete["cost_bps_each_side"]) != 10):
            raise ValueError(f"R9 {version} account replay incomplete/altered")
        if (identity["r9_freeze_sha256"] != sha(freeze_path) or
                identity["version"] != version or identity["policies"] != ROSTER or
                identity["fitted_2026_rows"] != 0 or
                identity["policy_selected_using_2026"] is not False):
            raise ValueError(f"R9 {version} identity differs from frozen cohort")
        if gate != {"r7": g7, "r8": g8, "r9": g9}:
            raise ValueError(f"R9 {version} price gate differs")
        lineage.append({"scenario": scenario, "complete_sha256": sha(complete_path),
                        "identity_sha256": sha(identity_path),
                        "price_gate_sha256": sha(gate_path)})
        for policy in ROSTER:
            folder = base / f"{policy}_10bps"
            positions_path, daily_path = folder / "positions.parquet", folder / "daily.parquet"
            positions, daily = pd.read_parquet(positions_path), pd.read_parquet(daily_path)
            gap, account = classify_gaps(positions, daily, r9, scenario, policy, folder, False)
            gap_parts.append(gap)
            account_parts.append(account)
            lineage.append({"scenario": scenario, "policy": policy,
                            "positions_sha256": sha(positions_path), "daily_sha256": sha(daily_path),
                            "position_rows": len(positions), "daily_rows": len(daily)})
    new_gaps = pd.concat(gap_parts, ignore_index=True)
    new_accounts = pd.concat(account_parts, ignore_index=True)
    all_gaps = pd.concat([old_gaps, new_gaps], ignore_index=True)
    all_accounts = pd.concat([old_accounts, new_accounts], ignore_index=True)
    stats = [_stats(all_gaps, all_accounts, name) for pair in NAMES.values() for name in pair]

    key_parts, transitions = [], []
    for version, (prior, revised) in NAMES.items():
        before = _key_table(all_gaps, prior)
        after = _key_table(all_gaps, revised)
        merged = before.merge(after, on=["ticker", "date"], how="outer", indicator=True,
                              suffixes=("_r8", "_r9"))
        merged.insert(0, "version", version)
        merged["key_transition"] = merged.pop("_merge").map({
            "left_only": "R8_ONLY_RESOLVED", "right_only": "R9_ONLY_CAUSAL_NEW",
            "both": "BOTH_UNVERIFIED"}).astype(str)
        key_parts.append(merged)
        b = next(x for x in stats if x["scenario"] == prior)
        a = next(x for x in stats if x["scenario"] == revised)
        transitions.append({
            "version": version,
            "r8_unique_security_dates": b["unique_security_dates"],
            "r9_unique_security_dates": a["unique_security_dates"],
            "r8_keys_no_longer_gaps": int(merged.key_transition.eq("R8_ONLY_RESOLVED").sum()),
            "causal_new_gap_keys": int(merged.key_transition.eq("R9_ONLY_CAUSAL_NEW").sum()),
            "common_gap_keys": int(merged.key_transition.eq("BOTH_UNVERIFIED").sum()),
            "r8_policy_position_days": b["policy_position_days"],
            "r9_policy_position_days": a["policy_position_days"],
            "r8_uncertified_account_dates": b["uncertified_account_dates"],
            "r9_uncertified_account_dates": a["uncertified_account_dates"],
            "r8_max_account_unverified_fraction": b["max_account_date_unverified_fraction"],
            "r9_max_account_unverified_fraction": a["max_account_date_unverified_fraction"],
            "r8_max_account_unverified_indicative_usd": b["max_account_date_unverified_indicative_usd"],
            "r9_max_account_unverified_indicative_usd": a["max_account_date_unverified_indicative_usd"],
        })
    key_changes = pd.concat(key_parts, ignore_index=True)
    causes = all_gaps.groupby(["scenario", "reason"], observed=True).agg(
        policy_position_days=("policy", "size"),
        unique_security_dates=("date", lambda x: 0),
        max_indicative_market_value=("market_value", "max"),
    ).reset_index()
    cause_keys = all_gaps[["scenario", "reason", "ticker", "date"]].drop_duplicates()
    key_counts = cause_keys.groupby(["scenario", "reason"], observed=True).size().rename("unique_security_dates").reset_index()
    causes = causes.drop(columns="unique_security_dates").merge(key_counts,
        on=["scenario", "reason"], validate="one_to_one")
    ticker_keys = all_gaps[["scenario", "ticker", "reason", "date"]].drop_duplicates()
    remaining = ticker_keys.groupby(["scenario", "ticker", "reason"], observed=True).size().rename(
        "unique_security_dates").reset_index()
    position_counts = all_gaps.groupby(["scenario", "ticker", "reason"], observed=True).size().rename(
        "policy_position_days").reset_index()
    remaining = remaining.merge(position_counts, on=["scenario", "ticker", "reason"], validate="one_to_one")
    remaining = remaining.sort_values(["scenario", "policy_position_days", "ticker"],
                                       ascending=[True, False, True])

    OUT.mkdir(parents=True)
    files = {
        "R9_GAP_DETAIL.parquet": new_gaps,
        "R9_ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv": new_accounts,
        "R8_R9_CAUSE_COMPARISON.csv": causes,
        "R8_R9_SCENARIO_COMPARISON.csv": pd.DataFrame(stats),
        "R8_TO_R9_CAUSAL_KEY_TRANSITIONS.parquet": key_changes,
        "R8_R9_TICKER_REASON_GAPS.csv": remaining,
    }
    for name, frame in files.items():
        if name.endswith(".parquet"):
            frame.to_parquet(OUT / name, index=False)
        else:
            frame.to_csv(OUT / name, index=False)
    receipt = {
        "status": "R9_POST_REPLAY_READ_ONLY_VALUATION_DIAGNOSTIC_COMPLETE",
        "pre_score_frozen_report_code": False,
        "scope": "2026 evaluation, 10 bp; original/v2 frozen-policy R8 versus R9 AAPL price gate",
        "r9_freeze_sha256": sha(freeze_path),
        "prior_r8_summary_receipt_sha256": sha(old_receipt_path),
        "prior_r8_replay_freeze_sha256": old_receipt["r8_freeze_sha256"],
        "price_gates": {"r7": g7, "r8": g8, "r9": g9},
        "scenario_stats": stats,
        "causal_key_transitions": transitions,
        "r8_account_lineage": [x for x in old_receipt["r8_account_lineage"] if "policy" in x],
        "r9_account_lineage": lineage,
        "source_sha256": {
            "price": raw_sha,
            "r7_overlay": sha(r7_overlay), "r7_receipt": sha(r7_receipt),
            "r8_overlay": sha(r8_overlay), "r8_receipt": sha(r8_receipt),
            "r9_overlay": sha(r9_overlay), "r9_receipt": sha(r9_receipt),
            "prior_r8_gap_detail": sha(OLD / "R8_GAP_DETAIL.parquet"),
            "prior_r8_account_dates": sha(OLD / "R8_ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv"),
            "classifier_code": sha(VALUATION / "summarize_replay_valuation.py"),
            "script": sha(Path(__file__)),
        },
        "output_sha256": {name: sha(OUT / name) for name in files},
        "new_fit_calls": 0, "new_model_inference_calls": 0, "new_account_replay_calls": 0,
        "historical_vendor_receipt_certified": False,
        "shareholder_total_return_certified": False,
        "limitations": "R9 restores 158 AAPL price-coordinate keys from an after-test issuer-source review. Issuer HTTP bodies and historical vendor receipts were not saved. R8/R9 account results are separate frozen-policy causal replays; this diagnostic code was written after replay, is not a blind test, and does not certify shareholder total return.",
    }
    (OUT / "RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "scenario_stats": stats,
                      "causal_key_transitions": transitions}, ensure_ascii=False))


if __name__ == "__main__":
    main()
