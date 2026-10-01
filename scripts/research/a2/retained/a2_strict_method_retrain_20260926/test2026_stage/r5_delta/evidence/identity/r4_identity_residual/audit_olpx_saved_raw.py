"""Bounded OLPX saved Raw/rehab/feature diagnostic; never changes the parent gate."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
DATA = Path(r"D:\us-tech-quant-data\moomoo\source")
R4 = Path(r"C:\Users\Lenovo\Documents\CODING开发\a2_strict_method_retrain_20260926\test2026_stage\r4_continuation\R4_FINAL_CANDIDATE_INPUT_GATE.parquet")
REBUILD = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
R1 = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ledger = pd.read_parquet(R4)
    target = ledger.loc[(ledger.ticker.eq("OLPX")) &
                        ledger.final_input_gate.eq("UNKNOWN_RAW_REHAB_OR_ALIAS_IDENTITY")].copy()
    assert len(target) == 65 and not target.duplicated(KEY).any()
    assert set(target.cusip) == {"679369108"}
    assert target.signal_date.max() < pd.Timestamp("2026-07-07")
    raw_parts, qfq_parts, qqq_parts, manifest = [], [], [], []
    for year in range(2021, 2027):
        raw_path = DATA / f"prices_raw/year={year}/prices.parquet"
        qfq_path = DATA / f"prices_qfq/year={year}/prices.parquet"
        raw = pd.read_parquet(raw_path)
        qfq = pd.read_parquet(qfq_path)
        raw_parts.append(raw.loc[raw.ticker.eq("OLPX")].copy())
        qfq_parts.append(qfq.loc[qfq.ticker.eq("OLPX")].copy())
        qqq_parts.append(qfq.loc[qfq.ticker.eq("QQQ"), "trade_date"])
        manifest.extend([{"year": year, "kind": "RAW", "path": str(raw_path), "sha256": sha(raw_path)},
                         {"year": year, "kind": "QFQ", "path": str(qfq_path), "sha256": sha(qfq_path)}])
    raw = pd.concat(raw_parts, ignore_index=True).sort_values("trade_date", kind="mergesort")
    qfq = pd.concat(qfq_parts, ignore_index=True).sort_values("trade_date", kind="mergesort")
    assert len(raw) == len(qfq) and len(raw) > 1100
    assert not raw.duplicated("trade_date").any() and not qfq.duplicated("trade_date").any()
    assert set(raw.source) == {"MOOMOO_OPEND"} and set(raw.autype) == {"raw"}
    assert set(qfq.source) == {"MOOMOO_OPEND"} and set(qfq.autype) == {"qfq"}
    fields = ["open", "high", "low", "close", "volume"]
    compare = raw[["trade_date", *fields]].merge(qfq[["trade_date", *fields]], on="trade_date",
                                                  suffixes=("_raw", "_qfq"), validate="one_to_one")
    assert len(compare) == len(raw)
    exact = {field: bool(compare[f"{field}_raw"].equals(compare[f"{field}_qfq"])) for field in fields}
    assert all(exact.values())
    raw.trade_date = pd.to_datetime(raw.trade_date)
    raw["code"] = "US.OLPX"
    raw = raw.rename(columns={"ticker": "name"})
    raw = raw.sort_values("trade_date", kind="mergesort")
    raw["last_close"] = raw.last_close.astype(float)
    rebuild = module("olpx_original_rebuild", REBUILD)
    r1 = module("olpx_original_r1", R1)
    rebuild.END_EXCLUSIVE = pd.Timestamp("2026-09-25")
    empty_rehab = pd.DataFrame(columns=["code", "ex_div_date"])
    adjusted, event_audit = rebuild.adjusted_price_frame("US.OLPX", "OLPX", raw, empty_rehab, {})
    assert not event_audit, "UNEXPLAINED_RAW_JUMP_OR_UNEXPECTED_EVENT"
    assert all(np.array_equal(adjusted[field].to_numpy(float), raw[field].to_numpy(float)) for field in fields)
    features = r1.build_stock_state_features(adjusted[["ticker", "trade_date", "close", "volume"]])
    assert len(r1.FEATURE_COLUMNS) == 32
    cal = pd.DatetimeIndex(pd.concat(qqq_parts)).unique().sort_values()
    position = pd.Series(np.arange(len(cal)), index=cal)
    features["calendar_position"] = features.trade_date.map(position)
    features["position_120_prior"] = features.calendar_position.shift(120)
    features["required_observations"] = np.arange(1, len(features) + 1)
    features["lookback_121_eligible"] = (features.required_observations.ge(121)
        & features.calendar_position.notna() & features.position_120_prior.notna()
        & features.calendar_position.sub(features.position_120_prior).eq(120))
    features["has_32_finite"] = np.isfinite(features[list(r1.FEATURE_COLUMNS)].to_numpy(float)).all(axis=1)
    overlay = target[KEY + ["ticker", "moomoo_transport_code", "final_input_gate"]].merge(
        features[["trade_date", "required_observations", "lookback_121_eligible", "has_32_finite"]],
        left_on="signal_date", right_on="trade_date", how="left", validate="one_to_one")
    assert len(overlay) == 65 and overlay.lookback_121_eligible.all() and overlay.has_32_finite.all()
    overlay["saved_raw_path_set"] = "D:/us-tech-quant-data/moomoo/source/prices_raw/year=2021..2026/prices.parquet"
    overlay["raw_qfq_full_history_exact"] = True
    overlay["original_adjusted_zero_event_numeric_match"] = True
    overlay["r4_residual_disposition"] = "RAW_AND_32_NUMERIC_RECOVERED_REHAB_PASS_ABSENT_HOLD"
    overlay.drop(columns="trade_date").to_parquet(OUT / "OLPX_65_EXACT_KEY_RAW_FEATURE_OVERLAY.parquet", index=False)
    pd.DataFrame(manifest).to_csv(OUT / "OLPX_SAVED_ANNUAL_SOURCE_HASHES.csv", index=False)
    report = {"candidate_days": len(overlay), "raw_rows": len(raw), "raw_first": str(raw.trade_date.min().date()),
              "raw_last": str(raw.trade_date.max().date()), "raw_qfq_exact_fields": exact,
              "original_32_feature_rows_for_candidate": int(overlay.has_32_finite.sum()),
              "121_eligible_candidate_days": int(overlay.lookback_121_eligible.sum()),
              "original_builder_event_audit_rows_with_empty_rehab": len(event_audit),
              "rehab_pass_saved": False, "formal_gate_status": "UNKNOWN_REHAB_VENDOR_ZERO_EVENT_PROOF_OR_PASS_MISSING",
              "raw_fetch_timestamp_unique": sorted(map(str, raw.fetch_timestamp.dropna().unique())),
              "original_builder_sha256": sha(REBUILD), "original_feature_source_sha256": sha(R1),
              "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0}
    (OUT / "OLPX_SAVED_RAW_FEATURE_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
