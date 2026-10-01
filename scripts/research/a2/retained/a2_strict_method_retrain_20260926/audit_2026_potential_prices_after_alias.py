"""Update candidate-level possible price needs after exact alias binding.

These are possible inputs only. Actual order/holding requirements cannot be
known until a complete candidate pool permits all four frozen TOP20 lists.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
OUT = STAGE / "identity_feature_application_r1"
OLD = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"


def main() -> None:
    candidate = pd.read_parquet(OUT / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet")
    existing = pd.read_parquet(STAGE / "fixed_window_binding/full_window_execution_valuation_input_status.parquet")
    assert len(existing) == len(candidate) == 111868
    keys = ["signal_date", "quarter", "ticker", "cusip", "moomoo_transport_code"]
    candidate = candidate[keys + ["transport_used", "final_input_gate"]]
    joined = existing.merge(candidate, on=keys, validate="one_to_one")
    alias_codes = (joined.loc[joined.transport_used.notna() & joined.transport_used.ne(joined.moomoo_transport_code),
                              ["moomoo_transport_code", "transport_used"]].drop_duplicates())
    alias_receipts = []
    for row in alias_codes.itertuples(index=False):
        path = OLD / f"SUBSCRIPTION_{row.transport_used.replace('.', '_')}_RAW_DAY_K_INPUT_ONLY.parquet"
        if not path.exists():
            continue
        raw = pd.read_parquet(path)
        raw = raw.loc[raw.code.astype(str).eq(row.transport_used)].copy()
        raw["trade_date"] = pd.to_datetime(raw.time_key).dt.normalize()
        raw["open"] = pd.to_numeric(raw.open, errors="coerce")
        dates = set(raw.loc[np.isfinite(raw.open) & raw.open.gt(0), "trade_date"])
        alias_receipts.append({"original_code": row.moomoo_transport_code, "transport": row.transport_used,
                               "raw_path": str(path), "valid_open_dates": len(dates),
                               "last_valid_open": str(max(dates).date()) if dates else None})
        mask = joined.moomoo_transport_code.eq(row.moomoo_transport_code)
        joined.loc[mask, "execution_open_input_present"] = joined.loc[mask, "execution_date"].isin(dates).to_numpy()
        joined.loc[mask, "valuation_open_input_present"] = joined.loc[mask, "subsequent_valuation_date"].isin(dates).to_numpy()
    joined["potential_execution_raw_status"] = np.where(joined.execution_open_input_present,
        "VALID_RAW_OPEN_PRESENT_ADJUSTMENT_PENDING", "NO_VALID_RAW_OPEN_OR_LIFECYCLE_PENDING")
    joined["potential_valuation_raw_status"] = np.where(joined.valuation_open_input_present,
        "VALID_RAW_OPEN_PRESENT_HOLDING_PENDING", "NO_VALID_RAW_OPEN_OR_EXIT_PENDING")
    joined["actual_order_or_position_required"] = pd.NA
    joined.to_parquet(OUT / "CANDIDATE_POTENTIAL_EXECUTION_VALUATION_AFTER_ALIAS.parquet", index=False)
    missing = joined.loc[~joined.execution_open_input_present | ~joined.valuation_open_input_present]
    missing.groupby(["quarter", "ticker", "cusip", "moomoo_transport_code"], as_index=False).agg(
        possible_execution_gap_days=("execution_open_input_present", lambda x: int((~x).sum())),
        possible_valuation_gap_days=("valuation_open_input_present", lambda x: int((~x).sum())),
        first_signal=("signal_date", "min"), last_signal=("signal_date", "max")
    ).to_csv(OUT / "CANDIDATE_POTENTIAL_PRICE_GAPS_AFTER_ALIAS.csv", index=False)
    final_day = joined.loc[joined.signal_date.eq(pd.Timestamp("2026-09-22"))]
    summary = {"status": "CANDIDATE_POTENTIAL_ONLY_NO_PORTFOLIO_REQUIREMENT_YET",
               "candidate_days": len(joined), "alias_raw_receipts": alias_receipts,
               "possible_execution_open_missing_days": int((~joined.execution_open_input_present).sum()),
               "possible_valuation_open_missing_days": int((~joined.valuation_open_input_present).sum()),
               "last_signal_candidate_count": len(final_day),
               "last_signal_sep23_possible_execution_open_present": int(final_day.execution_open_input_present.sum()),
               "last_signal_sep24_possible_valuation_open_present": int(final_day.valuation_open_input_present.sum()),
               "actual_order_holding_valuation_needs_assessed": False,
               "reason": "No complete common candidate feature and version qualification; no four frozen TOP20 orders exist."}
    (OUT / "POTENTIAL_VS_ACTUAL_PRICE_NEED_STATUS.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("last_signal_candidate_count",
        "last_signal_sep23_possible_execution_open_present", "last_signal_sep24_possible_valuation_open_present")}))


if __name__ == "__main__":
    main()
