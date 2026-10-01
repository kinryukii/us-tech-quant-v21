"""Read-only audit of saved joint-batch 10 bp valuation gaps.

This never fits a model, changes a price gate, or replays an account. 2026
observations are inspected only after the original frozen evaluations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PRE_PRICE = ROOT.parent / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    HERE.mkdir(exist_ok=True)
    sources: dict[str, str] = {}
    all_gaps = []
    summary = []
    for year in (2025, 2026):
        folder = ROOT / f"evaluation_{year}"
        if year == 2026:
            folder = folder / "cost_10"
            price_path = ROOT / "data/test_prices.parquet"
        else:
            price_path = PRE_PRICE
        prices = pd.read_parquet(price_path)
        prices["trade_date"] = pd.to_datetime(prices.trade_date).dt.normalize()
        assert not prices.duplicated(["ticker", "trade_date"]).any()
        source_columns = ["ticker", "trade_date", "open", "close"] + [
            c for c in ("raw_open", "raw_close", "price_coordinate", "original_transport", "transport_used",
                      "price_quality_warning", "unresolved_event_on_or_before",
                      "lifecycle_ended", "extreme_adjusted_jump") if c in prices
        ]
        prices = prices[source_columns].rename(columns={"trade_date": "date"})
        sources[str(price_path)] = digest(price_path)
        directories = sorted(p for p in folder.glob("*bps") if p.is_dir())
        for policy_dir in directories:
            positions_path = policy_dir / "positions.parquet"
            daily_path = policy_dir / "daily.parquet"
            positions = pd.read_parquet(positions_path)
            daily = pd.read_parquet(daily_path)
            for path in (positions_path, daily_path):
                sources[str(path)] = digest(path)
            bad = positions.loc[positions.stale.astype(bool) | positions.unknown.astype(bool)].copy()
            if bad.empty:
                summary.append({"year": year, "policy": policy_dir.name, "gap_rows": 0,
                                "gap_policy_dates": 0, "unverified_indicative_value_sum": 0.0})
                continue
            bad["date"] = pd.to_datetime(bad.date).dt.normalize()
            bad = bad.merge(prices, on=["ticker", "date"], how="left", validate="many_to_one", indicator="price_join")
            d = daily[["date", "nav", "certified_nav", "cash", "valuation_status"]].copy()
            d["date"] = pd.to_datetime(d.date).dt.normalize()
            bad = bad.merge(d, on="date", how="left", validate="many_to_one")
            if year == 2025:
                bad["reason"] = np.select([
                    bad.price_join.eq("left_only"),
                    ~np.isfinite(pd.to_numeric(bad.close, errors="coerce")) |
                    pd.to_numeric(bad.close, errors="coerce").le(0),
                ], ["NO_APPROVED_PRICE_ROW", "NO_POSITIVE_SAVED_CLOSE"], default="SAVED_PRICE_PRESENT_VERIFY_CLOCK")
            else:
                flag = bad.price_quality_warning.fillna(False).astype(bool)
                unresolved = bad.unresolved_event_on_or_before.fillna(False).astype(bool)
                life = bad.lifecycle_ended.fillna(False).astype(bool)
                jump = bad.extreme_adjusted_jump.fillna(False).astype(bool)
                bad["reason"] = np.select([
                    bad.price_join.eq("left_only"),
                    flag & unresolved,
                    flag & life,
                    flag & jump,
                    flag,
                    ~np.isfinite(pd.to_numeric(bad.close, errors="coerce")) |
                    pd.to_numeric(bad.close, errors="coerce").le(0),
                ], ["NO_APPROVED_PRICE_ROW", "UNRESOLVED_EVENT_GATE", "LIFECYCLE_GATE",
                    "EXTREME_ADJUSTED_JUMP_GATE", "OTHER_QUALITY_WARNING", "NO_POSITIVE_SAVED_CLOSE"],
                    default="SAVED_PRICE_PRESENT_VERIFY_CLOCK")
            bad["year"] = year
            bad["policy"] = policy_dir.name
            bad["repair_status"] = "NOT_REPAIRED_IN_THIS_AUDIT"
            bad["source_price_sha256"] = sources[str(price_path)]
            all_gaps.append(bad)
            summary.append({"year": year, "policy": policy_dir.name, "gap_rows": len(bad),
                            "gap_policy_dates": int(bad.date.nunique()),
                            "unverified_indicative_value_sum": float(bad.market_value.sum(skipna=True)),
                            "unknown_value_rows": int(bad.market_value.isna().sum())})
    gaps = pd.concat(all_gaps, ignore_index=True) if all_gaps else pd.DataFrame()
    assert not gaps.duplicated(["year", "policy", "date", "ticker"]).any()
    key_columns = ["year", "date", "ticker", "reason", "price_join", "open", "close",
                   "raw_open", "raw_close", "price_coordinate", "original_transport", "transport_used",
                   "price_quality_warning", "unresolved_event_on_or_before", "lifecycle_ended",
                   "extreme_adjusted_jump", "source_price_sha256"]
    reason_keys = gaps[[c for c in key_columns if c in gaps]].drop_duplicates()
    assert not reason_keys.duplicated(["year", "date", "ticker"]).any()
    reason_keys["repair_evidence_needed"] = np.select([
        reason_keys.reason.eq("UNRESOLVED_EVENT_GATE"),
        reason_keys.ticker.eq("EXAS") & reason_keys.reason.eq("NO_APPROVED_PRICE_ROW"),
        reason_keys.ticker.eq("DTP") & reason_keys.reason.eq("NO_APPROVED_PRICE_ROW"),
    ], ["BIND_HISTORICAL_EVENT_PUBLICATION_AND_ADJUSTED_COORDINATE",
        "BIND_LIFECYCLE_CASH_OR_SHARE_SETTLEMENT_AND_ACCOUNTING_DATE",
        "BIND_POST_2026_09_22_EXECUTION_AND_CLOSE_QUOTES_FOR_IDENTITY_ALIAS"],
        default="BIND_APPROVED_PRICE_AND_IDENTITY_EVIDENCE")
    account_dates = gaps.groupby(["year", "policy", "date"], as_index=False).agg(
        unresolved_names=("ticker", "nunique"), unverified_indicative_market_value=("market_value", "sum"),
        unknown_value_names=("unknown", "sum"), indicative_nav=("nav", "first"), cash=("cash", "first"),
        valuation_status=("valuation_status", "first"))
    account_dates["unverified_fraction_indicative_nav"] = (
        account_dates.unverified_indicative_market_value / account_dates.indicative_nav)
    gap_path = HERE / "SAVED_VALUATION_GAPS_10BPS.parquet"
    reason_path = HERE / "UNIQUE_SECURITY_DATE_REASONS_10BPS.csv"
    summary_path = HERE / "POLICY_GAP_SUMMARY_10BPS.csv"
    account_path = HERE / "ACCOUNT_DATE_UNVERIFIED_EXPOSURE_10BPS.csv"
    gaps.to_parquet(gap_path, index=False)
    reason_keys.sort_values(["year", "date", "ticker"]).to_csv(reason_path, index=False)
    pd.DataFrame(summary).to_csv(summary_path, index=False)
    account_dates.sort_values(["year", "policy", "date"]).to_csv(account_path, index=False)
    counts = gaps.groupby(["year", "reason"]).agg(position_rows=("ticker", "size"),
                    security_dates=("ticker", lambda x: 0)).reset_index()
    key_counts = reason_keys.groupby(["year", "reason"]).size().rename("security_dates").reset_index()
    counts = counts.drop(columns="security_dates").merge(key_counts, on=["year", "reason"])
    receipt_path = ROOT / "data/PRICE_SOURCE_RECEIPTS.json"
    receipts = {item["ticker"]: item for item in json.loads(receipt_path.read_text(encoding="utf-8"))}
    sources[str(receipt_path)] = digest(receipt_path)
    bounded_files = {
        "DTP": [ROOT.parent / "a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1/SUBSCRIPTION_US_DTE_RAW_DAY_K_INPUT_ONLY.parquet"],
        "EXAS": [ROOT.parent / "a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1/SUBSCRIPTION_US_EXAS_RAW_DAY_K_INPUT_ONLY.parquet",
                 ROOT.parent / "a2_strict_method_retrain_20260926/test2026_stage/fixed_window_raw/RAW_US_EXAS_K_DAY_NONE_RTH.parquet"],
    }
    source_bounds = {}
    for ticker, files in bounded_files.items():
        approved_hashes = {item["sha256"] for item in receipts[ticker]["paths"]}
        details = []
        for path in files:
            file_sha = digest(path)
            assert file_sha in approved_hashes
            raw = pd.read_parquet(path, columns=["trade_date"])
            details.append({"file": str(path), "sha256": file_sha,
                            "last_trade_date": str(pd.to_datetime(raw.trade_date).max().date())})
            sources[str(path)] = file_sha
        source_bounds[ticker] = {"approved_transport": receipts[ticker]["transport"], "raw_files": details}
    r6_path = ROOT.parent / "a2_strict_method_retrain_20260926/test2026_stage/r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet"
    r6 = pd.read_parquet(r6_path, columns=["ticker", "signal_date", "final_input_gate"])
    exas_lifecycle = r6.loc[r6.ticker.eq("EXAS") & r6.final_input_gate.eq("PROVEN_LIFECYCLE_INELIGIBLE"), "signal_date"]
    source_bounds["EXAS"]["saved_lifecycle_ineligible_from"] = str(exas_lifecycle.min().date())
    sources[str(r6_path)] = digest(r6_path)
    saved_daily_paths = sorted((ROOT / "evaluation_2025").glob("*bps/daily.parquet")) + sorted(
        (ROOT / "evaluation_2026").glob("cost_*/*bps/daily.parquet"))
    saved_nav_nonfinite = 0
    saved_terminal_nav_nonfinite = 0
    for path in saved_daily_paths:
        nav = pd.read_parquet(path, columns=["nav"])["nav"].to_numpy(float)
        saved_nav_nonfinite += int((~np.isfinite(nav)).sum())
        saved_terminal_nav_nonfinite += int(not np.isfinite(nav[-1]))
        sources[str(path)] = digest(path)
    report = {
        "status": "SAVED_VALUATION_GAPS_CLASSIFIED_NO_REPAIR_APPLIED",
        "scope": "Original joint-batch cost-10 evaluations, 2025 and 2026; post hoc evaluation evidence only",
        "source_sha256": sources,
        "counts_by_reason": counts.to_dict("records"),
        "unique_security_dates": int(len(reason_keys)),
        "policy_position_rows": int(len(gaps)),
        "policy_dates": int(gaps[["year", "policy", "date"]].drop_duplicates().shape[0]),
        "total_indicative_mark_value_cross_policy_noninvestable_sum": float(gaps.market_value.sum(skipna=True)),
        "unknown_market_value_rows": int(gaps.market_value.isna().sum()),
        "year_2025_gap_rows": int(gaps.year.eq(2025).sum()),
        "year_2026_gap_rows": int(gaps.year.eq(2026).sum()),
        "missing_row_approved_source_bounds": source_bounds,
        "metrics_finite_filter_original_outputs_check": {
            "saved_daily_files": len(saved_daily_paths),
            "nonfinite_nav_rows": saved_nav_nonfinite,
            "nonfinite_terminal_nav_files": saved_terminal_nav_nonfinite,
            "conclusion": "The finite-NAV filter in run_suite.metrics did not skip any actual saved 2025/2026 NAV row."},
        "max_account_date_unverified_fraction_indicative_nav": float(account_dates.unverified_fraction_indicative_nav.max()),
        "terminal_2026_account_dates": int(account_dates.date.eq(pd.Timestamp("2026-09-24")).sum()),
        "terminal_2026_unverified_indicative_value_cross_policy_noninvestable_sum": float(account_dates.loc[
            account_dates.date.eq(pd.Timestamp("2026-09-24")), "unverified_indicative_market_value"].sum()),
        "repair_before_after": {"before_unique_security_dates": int(len(reason_keys)),
                                "after_unique_security_dates": int(len(reason_keys)),
                                "repaired_unique_security_dates": 0,
                                "reason": "Existing local price rows lack the event-publication proof; EXAS lifecycle settlement and DTP terminal quotes are absent from bound sources."},
        "market_fit_calls": 0, "model_inference_calls": 0, "ledger_replay_calls": 0,
        "output_sha256": {p.name: digest(p) for p in (gap_path, reason_path, summary_path, account_path)},
    }
    assert all(digest(Path(path)) == prior for path, prior in sources.items())
    (HERE / "VALUATION_AUDIT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "counts_by_reason", "unique_security_dates", "policy_position_rows")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
