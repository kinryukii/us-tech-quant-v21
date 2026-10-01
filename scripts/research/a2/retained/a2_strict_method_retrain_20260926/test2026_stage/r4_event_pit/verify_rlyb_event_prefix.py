"""Test the original adjusted-price and 32-feature functions around RLYB split."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
R3 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3")
IDENTITY = HERE.parent / "r4_identity"
REBUILD = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
R1 = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
FACTORS = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet")

def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

rebuild = load_module("a2_rebuild_readonly_rlyb", REBUILD)
r1 = load_module("a2_r1_readonly_rlyb", R1)
rebuild.END_EXCLUSIVE = pd.Timestamp("2026-09-25")
source = json.loads((R3 / "CONSUMED_RAW_SOURCE_AUDIT.json").read_text(encoding="utf-8"))
paths = [Path(x) for item in source if item["original_code"] == "US.RLYB" for x in item["paths"]]
raw = rebuild.load_raw_code("US.RLYB", paths)
rehab = pd.read_parquet(FACTORS).loc[lambda x: x.code.eq("US.RLYB")].copy()
full_price, full_audit = rebuild.adjusted_price_frame("US.RLYB", "RLYB", raw, rehab, {})
full_feature = r1.build_stock_state_features(full_price)
boundaries = ["2026-02-05", "2026-02-06", "2026-02-09", "2026-09-22"]
checks = []
for end in boundaries:
    date = pd.Timestamp(end)
    prefix_raw = raw.loc[raw.trade_date.le(date)].copy()
    # A then-current event set contains only events effective through cutoff.
    prefix_rehab = rehab.loc[pd.to_datetime(rehab.ex_div_date).le(date)].copy()
    prefix_price, prefix_audit = rebuild.adjusted_price_frame("US.RLYB", "RLYB", prefix_raw, prefix_rehab, {})
    prefix_feature = r1.build_stock_state_features(prefix_price)
    full_row = full_feature.loc[full_feature.trade_date.eq(date), ["ticker", "trade_date", *r1.FEATURE_COLUMNS]]
    prefix_row = prefix_feature.loc[prefix_feature.trade_date.eq(date), ["ticker", "trade_date", *r1.FEATURE_COLUMNS]]
    assert len(full_row) == len(prefix_row) == 1
    same = np.array_equal(full_row[list(r1.FEATURE_COLUMNS)].to_numpy(), prefix_row[list(r1.FEATURE_COLUMNS)].to_numpy(), equal_nan=True)
    assert same, end
    checks.append({"signal_date": end, "original_feature_columns": len(r1.FEATURE_COLUMNS), "full_vs_prefix_exact": same,
                   "prefix_applied_2026_event_count": sum(pd.Timestamp(e["event_date"]).year == 2026 for e in prefix_audit if e["audit_kind"] == "APPLIED_CORPORATE_ACTION"),
                   "adjusted_close": float(prefix_price.loc[prefix_price.trade_date.eq(date), "close"].iloc[0]),
                   "adjusted_volume": float(prefix_price.loc[prefix_price.trade_date.eq(date), "volume"].iloc[0])})

assert len([e for e in full_audit if e["audit_kind"] == "APPLIED_CORPORATE_ACTION" and pd.Timestamp(e["event_date"]).year == 2026]) == 1
split = [e for e in full_audit if e["audit_kind"] == "APPLIED_CORPORATE_ACTION" and pd.Timestamp(e["event_date"]) == pd.Timestamp("2026-02-06")]
assert len(split) == 1 and split[0]["factor_a"] == 8.0 and split[0]["factor_b"] == 0.0 and split[0]["share_event"]
identity = pd.read_parquet(IDENTITY / "RLYB_181_EXACT_KEY_INTERVAL_OVERLAY.parquet")
r3 = pd.read_parquet(R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet")
subset = r3.loc[r3.moomoo_transport_code.eq("US.RLYB")].copy()
keys = ["cusip", "title_of_class", "quarter", "signal_date", "ticker", "moomoo_transport_code"]
combined = subset.merge(identity[keys + ["r4_identity_result", "r4_recomputed_primary_pending_event_review"]], on=keys, how="left", validate="one_to_one")
assert len(combined) == 181 and combined.r4_identity_result.notna().all()
combined["r4_event_public_ratio_proven"] = combined.signal_date.ge(pd.Timestamp("2026-02-06"))
combined["r4_event_source_sha256"] = hashlib.sha256((IDENTITY / "RLYB_NASDAQ_ECA2026_71.html").read_bytes()).hexdigest()
combined["r4_event_result"] = np.where(combined.r4_event_public_ratio_proven, "PUBLIC_SPLIT_RATIO_AND_VALUE_REPRODUCED_BY_ORIGINAL_BUILDER", "NO_2026_SPLIT_CONSUMED_YET")
combined["r4_input_result_subject_to_parent_gate"] = "INPUT_VERIFIED_THIS_GATE"
combined[keys + ["r4_identity_result", "r4_event_public_ratio_proven", "r4_event_source_sha256", "r4_event_result", "r4_input_result_subject_to_parent_gate"]].to_parquet(HERE / "RLYB_181_IDENTITY_EVENT_COMBINED_OVERLAY.parquet", index=False)
report = {
    "notice_url": "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-71",
    "notice_date": "2026-02-04",
    "notice_original_body_sha256": combined.r4_event_source_sha256.iloc[0],
    "original_rehab_snapshot_sha256": hashlib.sha256(FACTORS.read_bytes()).hexdigest(),
    "event_source_date": "2026-02-06", "event_applied_date": "2026-02-06",
    "event_factor_a": 8.0, "event_factor_b": 0.0,
    "event_share_volume_scale_factor": 8.0,
    "r3_post_event_candidate_days": int(combined.r4_event_public_ratio_proven.sum()),
    "r3_pre_event_candidate_days": int((~combined.r4_event_public_ratio_proven).sum()),
    "event_affected_signal_first": str(combined.loc[combined.r4_event_public_ratio_proven, "signal_date"].min().date()),
    "event_affected_signal_last": str(combined.loc[combined.r4_event_public_ratio_proven, "signal_date"].max().date()),
    "all_181_other_r3_input_checks_true": bool(combined[["rehab_pass", "coordinate_match", "has_32_finite", "version_checked", "raw_on_signal"]].all().all()),
    "original_feature_prefix_checks": checks,
    "contract_interpretation": "Original run_rebuild applies the saved forward factor on ex-date and after; no per-event historical vendor receipt condition appears in test2026_contract or original run_rebuild. The Nasdaq 2026-02-04 notice establishes a one-for-eight reverse split and new CUSIP effective 2026-02-06 before first affected signal, exactly reproducing factor_a=8, factor_b=0 and share-volume scale in the original builder. This supports closing this event dependency under the original PIT-forward rule. Historical vendor-version timestamp remains unobserved and is recorded separately; do not impose it as a new eligibility rule or claim actual receipt.",
    "model_fit_calls": 0, "preprocessor_fit_calls": 0,
}
(HERE / "RLYB_EVENT_VERDICT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report, indent=2, ensure_ascii=False))
