"""Targeted read-only checks of original forward adjustment and 32 features."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
R3 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3")
OUT = STAGE / "r4_validation"
ORIGINAL = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
R1 = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
R0F1 = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py")
OLD = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"
RUN_CACHE = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def close_frame(left: pd.DataFrame, right: pd.DataFrame, cols: list[str]) -> bool:
    x = left.set_index("trade_date").loc[:, cols].sort_index()
    y = right.set_index("trade_date").loc[:, cols].sort_index()
    return x.index.equals(y.index) and np.allclose(x.to_numpy(float), y.to_numpy(float), equal_nan=True, rtol=0, atol=1e-10)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    source_audit = json.loads((R3 / "CONSUMED_RAW_SOURCE_AUDIT.json").read_text(encoding="utf-8"))
    source_by_code = {x["original_code"]: x for x in source_audit}
    event_audit = pd.read_parquet(R3 / "CONSUMED_REHAB_EVENT_AUDIT.parquet")
    consumed = event_audit.loc[event_audit.audit_kind.eq("APPLIED_CORPORATE_ACTION")
        & event_audit.event_date.ge("2026-01-02") & event_audit.event_date.le("2026-09-22")]
    rebuild = load("r4_prefix_original_rebuild", ORIGINAL)
    r1 = load("r4_prefix_original_r1", R1)
    r0f1 = load("r4_prefix_original_r0f1", R0F1)
    rebuild.END_EXCLUSIVE = pd.Timestamp("2026-09-25")
    wolf = next(x for x in r0f1.frozen_evidence_records() if x["ticker"] == "WOLF")
    folders = [RUN_CACHE] + [OLD / x for x in ("REHAB_NEW_OCCUPIED_ONLY", "REHAB_SUBSCRIPTION_ONLY",
        "REHAB_AUTHORITY_ALIASES_ONLY", "REHAB_OFFICIAL_COMMON_ALIASES_ONLY")]
    factors = pd.concat([pd.read_parquet(x / "rehab_factors.parquet") for x in folders], ignore_index=True)
    cases = []
    for original_code in ("US.NVDA", "US.MSFT", "US.DTP", "US.GE.WI"):
        source = source_by_code[original_code]
        transport, ticker = source["transport"], consumed.loc[consumed.original_code.eq(original_code), "ticker"].iloc[0]
        paths = [Path(x) for x in source["paths"]]
        raw = rebuild.load_raw_code(transport, paths)
        raw = raw.loc[raw.trade_date.lt(rebuild.END_EXCLUSIVE)]
        rehab = factors.loc[factors.code.eq(transport)]
        full_adjusted, _ = rebuild.adjusted_price_frame(transport, ticker, raw, rehab, wolf)
        event_day = consumed.loc[consumed.original_code.eq(original_code), "event_date"].min()
        prefix_raw = raw.loc[raw.trade_date.lt(event_day)]
        prefix_adjusted, _ = rebuild.adjusted_price_frame(transport, ticker, prefix_raw, rehab, wolf)
        full_prefix = full_adjusted.loc[full_adjusted.trade_date.lt(event_day)]
        assert close_frame(prefix_adjusted, full_prefix, ["open", "close", "high", "low", "volume"])
        start = pd.Timestamp("2025-06-01")
        prefix_features = r1.build_stock_state_features(prefix_adjusted.loc[
            prefix_adjusted.trade_date.ge(start), ["ticker", "trade_date", "close", "volume"]])
        full_features = r1.build_stock_state_features(full_adjusted.loc[
            full_adjusted.trade_date.ge(start) & full_adjusted.trade_date.lt(event_day),
            ["ticker", "trade_date", "close", "volume"]])
        assert close_frame(prefix_features, full_features, list(r1.FEATURE_COLUMNS))
        shuffled = full_adjusted.loc[full_adjusted.trade_date.ge(start),
                                     ["ticker", "trade_date", "close", "volume"]].sample(frac=1, random_state=42)
        ordered = shuffled.sort_values("trade_date", kind="mergesort")
        shuffled_features = r1.build_stock_state_features(shuffled)
        ordered_features = r1.build_stock_state_features(ordered)
        assert close_frame(shuffled_features, ordered_features, list(r1.FEATURE_COLUMNS))
        cases.append({"original_code": original_code, "actual_transport": transport, "first_2026_event": str(event_day.date()),
                      "prefix_rows_compared": len(prefix_adjusted), "feature_rows_compared": len(prefix_features),
                      "future_event_and_raw_do_not_change_prior_adjusted_rows": True,
                      "future_event_and_raw_do_not_change_prior_32_features": True,
                      "row_order_does_not_change_keyed_32_features": True,
                      "scope": "targeted invariance; event value historical availability remains separate"})
    report = {"status": "TARGETED_ORIGINAL_PREFIX_INVARIANCE_PASS", "cases": cases,
              "original_builder_sha256": sha(ORIGINAL), "original_32_feature_source_sha256": sha(R1),
              "model_objects_loaded": 0, "fit_calls": 0}
    (OUT / "PREFIX_AND_ORDER_VALIDATION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases), "status": report["status"]}))


if __name__ == "__main__":
    main()
