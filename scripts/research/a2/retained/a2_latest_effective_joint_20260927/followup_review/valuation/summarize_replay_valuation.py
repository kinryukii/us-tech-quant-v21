"""Predeclared valuation-gap comparison for four frozen joint-batch scenarios.

No fitting, prediction, policy callback or account replay occurs here. Each
scenario reads its saved 10 bp account files, including explicit hash-checked
links to unchanged policies. The old 339-key fixed-units snapshot is not an
input to this comparison or to the policy-independent 811-key price domain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from price_overlay import gate_prices_with_r7_exact

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PRICE = ROOT / "data/test_prices.parquet"
OVERLAY = HERE / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
RECEIPT = HERE / "R7_OVERLAY_RECEIPT.json"
EXPECTED_PRICE_SHA256 = "d056d46fc7d45b8eaaad770b2767ddb14b5d055dd7b17d6e9a0aedc463f68c91"
EXPECTED_OVERLAY_SHA256 = "4e6420236e57999911ae0bd6745f4d4b396418e5c5e72058c36667ec66eadd65"
EXPECTED_RECEIPT_SHA256 = "b6922b5f05a6f438a2d712db30f5988d5ad26005e828891fb79f7528bfca80f8"
OLD_VALUATION_AUDIT = HERE / "VALUATION_AUDIT.json"
EXPECTED_OLD_VALUATION_AUDIT_SHA256 = "61f50c8df45aebe1d933cc9dac699a244c6982785bc8ecb0902d212ec14a9777"
SCENARIOS = {
    "original_r6": ROOT / "evaluation_2026/cost_10",
    "original_r7_conditional": ROOT / "evaluation_2026_sampling_v2/r7_original/cost_10",
    "v2_r6": ROOT / "evaluation_2026_sampling_v2/r6_v2/cost_10",
    "v2_r7_conditional": ROOT / "evaluation_2026_sampling_v2/r7_v2/cost_10",
}
SCENARIO_IDENTITIES = {
    "original_r7_conditional": ("r7_original_10", "r7", "original"),
    "v2_r6": ("r6_v2_10", "r6", "v2"),
    "v2_r7_conditional": ("r7_v2_10", "r7", "v2"),
}


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def resolve_policy_dir(scenario_dir: Path, policy: str, links: dict[str, dict]) -> tuple[Path, bool]:
    target = scenario_dir / f"{policy}_10bps"
    if target.exists():
        if policy in links:
            raise ValueError(f"{policy}: both replay directory and linked result exist")
        return target, False
    item = links.get(policy)
    if item is None:
        raise ValueError(f"{policy}: missing policy result and approved link")
    if float(item["cost_bps"]) != 10:
        raise ValueError(f"{policy}: linked cost differs from 10 bp")
    source = (ROOT / item["source_directory"]).resolve()
    if not source.is_relative_to(ROOT.resolve()) or not source.is_dir():
        raise ValueError(f"{policy}: linked result outside joint batch or absent")
    expected = item["source_sha256"]
    if set(expected) != {"positions.parquet", "daily.parquet"}:
        raise ValueError(f"{policy}: linked source hash schema changed")
    for name, value in expected.items():
        if sha(source / name) != value:
            raise ValueError(f"{policy}: linked {name} hash mismatch")
    return source, True


def load_links(scenario_dir: Path) -> dict[str, dict]:
    path = scenario_dir / "LINKED_ORIGINAL_RESULTS.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"links"} or not isinstance(data["links"], list):
        raise ValueError("linked results schema changed")
    out = {}
    for item in data["links"]:
        policy = item["policy"]
        if policy in out:
            raise ValueError("duplicate linked policy")
        out[policy] = item
    return out


def check_scenario_identity(scenario: str, path: Path) -> None:
    if scenario == "original_r6":
        if not (path / "COMPLETE.json").is_file():
            raise ValueError("original R6 result incomplete")
        return
    code_name, gate, version = SCENARIO_IDENTITIES[scenario]
    batch = ROOT / "evaluation_2026_sampling_v2/PRE_SCORE_BATCH_FREEZE.json"
    if not batch.is_file():
        raise ValueError("revised full-batch freeze absent")
    batch_sha = sha(batch)
    identity = json.loads((path / "SCENARIO_IDENTITY.json").read_text(encoding="utf-8"))
    if not (identity["batch_manifest_sha256"] == batch_sha and identity["scenario"] == code_name and
            identity["price_gate"] == gate and identity["policy_version"] == version and
            float(identity["cost_bps_each_side"]) == 10 and identity["no_new_fit"] is True):
        raise ValueError(f"{scenario}: scenario identity differs from frozen definition")
    complete = json.loads((path / "COMPLETE.json").read_text(encoding="utf-8"))
    if complete["status"] != "FROZEN_SCENARIO_REPLAY_COMPLETE" or complete["scenario"] != code_name:
        raise ValueError(f"{scenario}: replay incomplete")
    pg = json.loads((path / "PRICE_GATE.json").read_text(encoding="utf-8"))
    if gate == "r6":
        if not (pg["status"] == "ORIGINAL_R6_PRICE_WARNING_GATE" and pg["mode"] == "R6" and
                pg["price_source_sha256"] == EXPECTED_PRICE_SHA256 and pg["restored_keys"] == 0):
            raise ValueError(f"{scenario}: R6 price gate mismatch")
    else:
        if not (pg["status"] == "R7_POLICY_INDEPENDENT_PRICE_GATE_READY_FOR_FROZEN_REPLAY" and pg["mode"] == "R7" and
                pg["price_source_sha256"] == EXPECTED_PRICE_SHA256 and pg["restored_keys"] == 811 and
                pg["original_price_sha256"] == EXPECTED_PRICE_SHA256 and
                pg["overlay_sha256"] == EXPECTED_OVERLAY_SHA256 and
                pg["receipt_sha256"] == EXPECTED_RECEIPT_SHA256 and
                pg["r7_exact_keys_restored"] == 811):
            raise ValueError(f"{scenario}: R7 price gate mismatch")


def classify_gaps(positions: pd.DataFrame, daily: pd.DataFrame, effective_prices: pd.DataFrame,
                  scenario: str, policy: str, source_dir: Path, linked: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    for name, frame, key in (("positions", positions, ["date", "ticker"]), ("daily", daily, ["date"])):
        if frame.duplicated(key).any():
            raise ValueError(f"{scenario}/{policy}: duplicate {name} keys")
    bad = positions.loc[positions.stale.astype(bool) | positions.unknown.astype(bool)].copy()
    expected_bad = daily[["date", "stale_count", "unknown_count"]].copy()
    expected_bad["expected_bad"] = expected_bad.stale_count + expected_bad.unknown_count
    if bad.empty:
        if expected_bad.expected_bad.ne(0).any():
            raise ValueError(f"{scenario}/{policy}: daily gap count without positions")
        empty = pd.DataFrame(columns=["scenario", "policy", "date", "ticker", "reason",
                                       "market_value", "index_units", "nav", "cash", "linked_source"])
        return empty, pd.DataFrame(columns=["scenario", "policy", "date", "unverified_names",
                                               "unverified_indicative_market_value", "unknown_value_names",
                                               "indicative_nav", "cash", "unverified_fraction_indicative_nav"])
    actual_bad = bad.groupby("date").size().rename("actual_bad").reset_index()
    compare = expected_bad.merge(actual_bad, on="date", how="left").fillna({"actual_bad": 0})
    if not compare.expected_bad.eq(compare.actual_bad).all():
        raise ValueError(f"{scenario}/{policy}: position and daily gap counts differ")
    price_columns = ["ticker", "trade_date", "open", "close", "price_quality_warning",
                     "original_price_quality_warning", "r7_overlay_applied",
                     "unresolved_event_on_or_before", "lifecycle_ended", "extreme_adjusted_jump",
                     "original_transport", "transport_used", "price_coordinate"]
    p = effective_prices[[c for c in price_columns if c in effective_prices]].rename(columns={"trade_date": "date"})
    bad = bad.merge(p, on=["ticker", "date"], how="left", indicator="price_join", validate="many_to_one")
    nav = daily[["date", "nav", "cash", "valuation_status"]]
    bad = bad.merge(nav, on="date", validate="many_to_one")
    absent = bad.price_join.eq("left_only")
    warning = bad.price_quality_warning.fillna(False).astype(bool)
    unresolved = bad.unresolved_event_on_or_before.fillna(False).astype(bool)
    life = bad.lifecycle_ended.fillna(False).astype(bool)
    jump = bad.extreme_adjusted_jump.fillna(False).astype(bool)
    missing_close = ~np.isfinite(pd.to_numeric(bad.close, errors="coerce")) | pd.to_numeric(bad.close, errors="coerce").le(0)
    bad["reason"] = np.select([
        absent, warning & unresolved, warning & life, warning & jump, warning,
        missing_close,
    ], ["NO_APPROVED_PRICE_ROW", "UNRESOLVED_EVENT_GATE", "LIFECYCLE_GATE",
        "EXTREME_ADJUSTED_JUMP_GATE", "OTHER_QUALITY_WARNING", "NO_POSITIVE_EFFECTIVE_CLOSE"],
        default="UNCLASSIFIED_STALE_WITH_EFFECTIVE_PRICE")
    if bad.reason.eq("UNCLASSIFIED_STALE_WITH_EFFECTIVE_PRICE").any():
        raise ValueError(f"{scenario}/{policy}: stale position with a positive effective price")
    bad["scenario"] = scenario
    bad["policy"] = policy
    bad["linked_source"] = linked
    bad["source_directory"] = str(source_dir)
    account = bad.groupby("date", as_index=False).agg(
        unverified_names=("ticker", "nunique"),
        unverified_indicative_market_value=("market_value", "sum"),
        unknown_value_names=("unknown", "sum"),
        indicative_nav=("nav", "first"), cash=("cash", "first"))
    account["unverified_fraction_indicative_nav"] = (
        account.unverified_indicative_market_value / account.indicative_nav)
    account["scenario"] = scenario
    account["policy"] = policy
    return bad, account


def summarize_scenario(scenario: str, scenario_dir: Path, roster: list[str],
                       prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    if not scenario_dir.is_dir():
        raise ValueError(f"{scenario}: evaluation directory absent")
    check_scenario_identity(scenario, scenario_dir)
    links = load_links(scenario_dir)
    if not set(links).issubset(roster):
        raise ValueError(f"{scenario}: link outside fixed roster")
    gaps, account_dates, lineage = [], [], []
    for policy in roster:
        folder, linked = resolve_policy_dir(scenario_dir, policy, links)
        pp, dp = folder / "positions.parquet", folder / "daily.parquet"
        pos, day = pd.read_parquet(pp), pd.read_parquet(dp)
        gap, account = classify_gaps(pos, day, prices, scenario, policy, folder, linked)
        gaps.append(gap)
        account_dates.append(account)
        lineage.append({"scenario": scenario, "policy": policy, "linked": linked,
                        "source_directory": str(folder),
                        "positions_sha256": sha(pp), "daily_sha256": sha(dp),
                        "position_rows": len(pos), "daily_rows": len(day)})
    return pd.concat(gaps, ignore_index=True), pd.concat(account_dates, ignore_index=True), lineage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT.resolve()):
        raise ValueError("output must remain in this joint batch")
    if out.exists():
        raise ValueError("valuation comparison output already exists; preserve prior evidence")
    batch_path = ROOT / "evaluation_2026_sampling_v2/PRE_SCORE_BATCH_FREEZE.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    this_relative = str(Path(__file__).resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    if batch["status"] != "JOINT_SAMPLING_V2_FULL_BATCH_FROZEN_BEFORE_REVISED_SCORING" or \
       batch["runtime_files_sha256"].get(this_relative) != sha(Path(__file__)):
        raise ValueError("valuation summary implementation differs from pre-score freeze")
    source_hash = sha(PRICE)
    if source_hash != EXPECTED_PRICE_SHA256 or sha(OVERLAY) != EXPECTED_OVERLAY_SHA256 or sha(RECEIPT) != EXPECTED_RECEIPT_SHA256:
        raise ValueError("frozen price/overlay identity mismatch")
    if sha(OLD_VALUATION_AUDIT) != EXPECTED_OLD_VALUATION_AUDIT_SHA256:
        raise ValueError("original R6 valuation audit identity changed")
    old_audit = json.loads(OLD_VALUATION_AUDIT.read_text(encoding="utf-8"))
    old_freeze = json.loads((SCENARIOS["original_r6"] / "FROZEN_BEFORE_SCORING.json").read_text(encoding="utf-8"))
    roster = old_freeze["roster"]
    if len(roster) != 14 or len(set(roster)) != 14:
        raise ValueError("fixed roster changed")
    raw_prices = pd.read_parquet(PRICE)
    r6_prices = raw_prices.copy()
    r6_prices["original_price_quality_warning"] = r6_prices.price_quality_warning.astype(bool)
    r6_prices["r7_overlay_applied"] = False
    r6_prices.loc[r6_prices.price_quality_warning.astype(bool), ["open", "close"]] = np.nan
    r7_prices, gate_receipt = gate_prices_with_r7_exact(
        raw_prices, raw_price_sha256=source_hash, overlay_path=OVERLAY,
        expected_overlay_sha256=EXPECTED_OVERLAY_SHA256, receipt_path=RECEIPT,
        expected_receipt_sha256=EXPECTED_RECEIPT_SHA256)
    rows, dates, lineage = [], [], []
    for scenario, path in SCENARIOS.items():
        effective = r7_prices if scenario.endswith("r7_conditional") else r6_prices
        gaps, accounts, sources = summarize_scenario(scenario, path, roster, effective)
        rows.append(gaps)
        dates.append(accounts)
        lineage.extend(sources)
    for item in lineage:
        if item["scenario"] == "original_r6":
            folder = Path(item["source_directory"])
            for kind in ("positions", "daily"):
                relative = str((folder / f"{kind}.parquet").relative_to(ROOT)).replace("\\", "/")
                matched_hashes = [value for source_path, value in old_audit["source_sha256"].items()
                                  if source_path.replace("\\", "/").endswith("/" + relative)]
                if matched_hashes != [item[f"{kind}_sha256"]]:
                    raise ValueError(f"original R6 {kind} changed since valuation baseline")
    all_gaps = pd.concat(rows, ignore_index=True)
    all_account_dates = pd.concat(dates, ignore_index=True)
    unique = all_gaps[["scenario", "reason", "ticker", "date"]].drop_duplicates()
    causes = all_gaps.groupby(["scenario", "reason"]).size().rename("policy_position_days").reset_index()
    causes = causes.merge(unique.groupby(["scenario", "reason"]).size().rename("unique_security_dates").reset_index(),
                          on=["scenario", "reason"], validate="one_to_one")
    if all_gaps[["scenario", "policy", "date", "ticker"]].duplicated().any():
        raise ValueError("duplicate policy position-day gap")
    stats = []
    for scenario in SCENARIOS:
        g = all_gaps.loc[all_gaps.scenario.eq(scenario)]
        a = all_account_dates.loc[all_account_dates.scenario.eq(scenario)]
        stats.append({"scenario": scenario, "unique_security_dates": len(g[["ticker", "date"]].drop_duplicates()),
                      "policy_position_days": len(g), "uncertified_account_dates": len(a),
                      "max_account_date_unverified_fraction": float(a.unverified_fraction_indicative_nav.max()) if len(a) else 0.0,
                      "unknown_value_rows": int(g.market_value.isna().sum()),
                      "terminal_2026_09_24_unverified_policies": int(a.date.eq(pd.Timestamp("2026-09-24")).sum())})
    out.mkdir(parents=True)
    gap_path = out / "VALUATION_GAP_DETAIL.parquet"
    date_path = out / "ACCOUNT_DATE_UNVERIFIED_EXPOSURE.csv"
    cause_path = out / "CAUSE_COMPARISON.csv"
    stats_path = out / "SCENARIO_COMPARISON.csv"
    all_gaps.to_parquet(gap_path, index=False)
    all_account_dates.to_csv(date_path, index=False)
    causes.to_csv(cause_path, index=False)
    pd.DataFrame(stats).to_csv(stats_path, index=False)
    result = {
        "status": "FOUR_FROZEN_SCENARIO_VALUATION_GAP_COMPARISON_COMPLETE",
        "scope": "2026 evaluation only; 10 bp; original R6, original R7 conditional, v2 R6, v2 R7 conditional",
        "price_source_sha256": source_hash,
        "r7_gate_receipt": gate_receipt,
        "roster": roster,
        "scenario_lineage": lineage,
        "scenario_stats": stats,
        "original_339_fixed_holdings_snapshot_used_for_replay_or_key_selection": False,
        "historical_vendor_receipt_certified": False,
        "shareholder_total_return_certified": False,
        "fit_calls": 0, "model_inference_calls": 0, "ledger_replay_calls": 0,
        "script_sha256": sha(Path(__file__)),
        "output_sha256": {p.name: sha(p) for p in (gap_path, date_path, cause_path, stats_path)},
    }
    (out / "RECEIPT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": result["status"], "scenario_stats": stats}, ensure_ascii=False))


if __name__ == "__main__":
    main()
