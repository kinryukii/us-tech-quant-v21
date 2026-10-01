"""Join the two existing 54-row audit extracts; never run models or a ledger."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def read(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    sampling = read("sampling/VERIFICATION.json")
    holdings = read("holdings/HOLDINGS_TRACE_RECEIPT.json")
    lineage = read("input_lineage/INPUT_LINEAGE_SUMMARY.json")
    frozen = read("FROZEN_PRESERVATION.json")
    assert sampling["status"] == "PASS_EXACT_FROZEN_SAMPLING_REPRODUCTION"
    assert holdings["status"] == frozen["status"] == "PASS"
    assert lineage["strategy_rows"] == holdings["affected_policy_ticker_rows"] == 54
    assert lineage["source_files_modified"] == holdings["fit_calls"] == holdings["ledger_replays"] == 0
    inputs = ["holdings/MISSING_METADATA_HOLDINGS_DETAIL.csv",
              "input_lineage/MISSING54_INPUT_LINEAGE.csv"]
    left, right = [pd.read_csv(ROOT / p, dtype={"ticker": str, "cusip": str,
                     "current_saved_cusip": str}) for p in inputs]
    keys = ["policy", "ticker", "signal_date", "execution_date"]
    assert not left.duplicated(keys).any() and not right.duplicated(keys).any()
    assert set(map(tuple, left[keys].to_numpy())) == set(map(tuple, right[keys].to_numpy()))
    compare = left.merge(right[keys + ["target_weight", "current_weight"]],
                         on=keys, validate="one_to_one")
    assert np.allclose(compare.target_weight_recorded, compare.target_weight, atol=1e-12)
    assert np.allclose(compare.current_weight_recorded, compare.current_weight, atol=1e-12)
    extra = ["quarter", "cusip", "new_buy_eligible", "input_absence_reason", "reason_zh",
             "in_current_saved_candidate_snapshot", "current_gate",
             "current_gate_32_finite", "current_gate_121_eligible", "current_gate_version_checked",
             "current_materialized_feature_row", "current_materialized_32_finite",
             "last_materialized_feature_date", "last_saved_transport_used", "cannot_infer"]
    joined = left.merge(right[keys + extra], on=keys, validate="one_to_one")
    assert len(joined) == 54 and joined.ticker.nunique() == 45
    assert not joined.model_input_row_present.any()
    assert joined.missing_open_sell_recorded.all() and joined.execution_fill_count.eq(0).all()
    assert joined.units_unchanged_0922_0923_0924.all()
    assert joined[["quarter", "cusip", "new_buy_eligible"]].isna().all().all()
    for suffix in ["20260922", "20260923", "20260924"]:
        assert np.allclose(joined[f"indicative_market_value_{suffix}"] /
                           joined[f"account_indicative_nav_{suffix}"],
                           joined[f"indicative_nav_weight_{suffix}"], atol=1e-12)
    output = ROOT / "HOLDINGS_54_TRACE.csv"
    joined.to_csv(output, index=False, encoding="utf-8-sig")
    receipt = {
        "status": "PASS", "universe_rule_issue": "CLOSED_PER_CURRENT_REPORT",
        "sampling_implementation": "EXACT_ORIGINAL_FIXED_SAMPLER",
        "sampling_coverage": "NEXT_VERSION_DESIGN_CHANGE_ONLY_NOT_APPLIED",
        "holding_rows": len(joined), "unique_tickers": joined.ticker.nunique(),
        "input_classification_rows": joined.input_absence_reason.value_counts().to_dict(),
        "price_classification_rows": joined.execution_price_evidence.value_counts().to_dict(),
        "source_inputs": {p: sha(ROOT / p) for p in inputs},
        "output_sha256": sha(output), "source_rows_joined_one_to_one": True,
        "missing_original_metadata_preserved": True,
        "existing_frozen_files_verified": frozen["frozen_files_checked"],
        "fit_calls": 0, "model_inference_calls": 0, "ledger_replays": 0,
        "limits": ["Raw model outputs were not persisted; absent keys are a source/input inference.",
                   "Unverified inputs and prices remain unresolved; this audit does not certify them.",
                   "Stale book values are not certified liquidation proceeds."]}
    (ROOT / "VERIFICATION.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in receipt.items() if k not in ["source_inputs", "limits"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
