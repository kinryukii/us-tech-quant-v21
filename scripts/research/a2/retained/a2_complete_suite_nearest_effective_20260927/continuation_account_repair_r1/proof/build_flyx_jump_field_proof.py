"""Validate saved FLYX 2026-01-08 jump for frozen account open/close use.

Reads only existing source files. Keeps this one-day proof separate from R7.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
JOINT = HERE.parents[1]
WORKSPACE = JOINT.parent
STRICT = WORKSPACE / "a2_strict_method_retrain_20260926"
STAGE = STRICT / "test2026_stage"
R4 = STAGE / "r4_identity"
DAY = pd.Timestamp("2026-01-08")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_html() -> dict:
    manifest = pd.read_csv(R4 / "LOCAL_PRIMARY_SOURCE_MANIFEST.csv")
    result = {}
    for name in ["FLYX_ISSUER_20260108.html", "FLYX_ISSUER_PROSPECTUS_20260109.html"]:
        path = R4 / name
        row = manifest.loc[manifest.path.astype(str).str.endswith(name)]
        assert len(row) == 1 and sha(path) == row.sha256.iloc[0], name
        result[name] = {"path": str(path), "sha256": sha(path), "url": row.url.iloc[0]}
    prospectus = (R4 / "FLYX_ISSUER_PROSPECTUS_20260109.html").read_text("utf-8")
    source_text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", prospectus)).split())
    assert "2,255,639 Shares of Class A Common Stock" in source_text
    assert re.search(r"NYSE American.{0,120}FLYX", source_text)
    assert re.search(r"January 8, 2026.{0,180}\$7\.23", source_text)
    assert re.search(r"\$7\.23.{0,180}January 8, 2026", source_text)
    return result


def main() -> None:
    source_html = check_html()
    old_raw = Path(r"D:\us-tech-quant-cache\13f_pit_v1\moomoo_daily_raw\US_FLYX.parquet")
    new_raw = STAGE / "fixed_window_raw/RAW_US_FLYX_K_DAY_NONE_RTH.parquet"
    overlap_saved = pd.read_csv(R4 / "JUMP_TWO_CODE_RAW_OVERLAP_CHECK.csv")
    overlap_row = overlap_saved.loc[overlap_saved.ticker.eq("FLYX")].iloc[0]
    assert sha(old_raw) == overlap_row.old_raw_sha256
    assert sha(new_raw) == overlap_row.new_raw_sha256
    old = pd.read_parquet(old_raw)
    new = pd.read_parquet(new_raw)
    old["time_key"] = pd.to_datetime(old.time_key)
    new["time_key"] = pd.to_datetime(new.time_key)
    fields = ["open", "high", "low", "close", "volume"]
    overlap = old[["time_key", *fields]].merge(new[["time_key", *fields]], on="time_key", validate="one_to_one", suffixes=("_old", "_new"))
    assert len(overlap) == 971 == overlap_row.old_new_raw_overlap_rows
    for field in fields:
        assert overlap[f"{field}_old"].equals(overlap[f"{field}_new"]), field
    raw = new.loc[new.time_key.eq(DAY)]
    assert len(raw) == 1 and raw.code.iloc[0] == "US.FLYX"
    raw = raw.iloc[0]
    assert raw.open == overlap_row.event_open == 6.08
    assert raw.close == overlap_row.event_close == 7.23
    assert raw.volume == overlap_row.event_volume == 115470732
    assert raw.low <= raw.open <= raw.high and raw.low <= raw.close <= raw.high

    initial = pd.read_csv(STAGE / "identity_feature_application_r1/CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv")
    init = initial.loc[initial.moomoo_transport_code.eq("US.FLYX")]
    assert len(init) == 1
    init = init.iloc[0]
    assert init.initial_alpha_2026_01_02 == 1.0
    assert init.initial_beta_2026_01_02 == 0.0
    assert init.consumed_prior_events == 0
    old_events = pd.read_parquet(WORKSPACE / "a2_complete_suite_20260927/data/consumed_price_events.parquet")
    flyx_events = old_events.loc[old_events.code.eq("US.FLYX")]
    assert len(flyx_events) == 1 and flyx_events.audit_kind.iloc[0] == "LARGE_RAW_MOVE_NO_VENDOR_EVENT"
    assert flyx_events.event_date.iloc[0] == DAY

    prices = pd.read_parquet(JOINT / "data/test_prices.parquet")
    price = prices.loc[prices.ticker.eq("FLYX") & prices.trade_date.eq(DAY)]
    assert len(price) == 1
    price = price.iloc[0]
    assert price.original_transport == price.transport_used == "US.FLYX"
    assert price.price_coordinate == "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
    assert bool(price.extreme_adjusted_jump) and bool(price.price_quality_warning)
    assert not bool(price.unresolved_event_on_or_before) and not bool(price.lifecycle_ended)
    assert price.open == price.raw_open == raw.open
    assert price.close == price.raw_close == raw.close
    assert np.isfinite(price.open) and np.isfinite(price.close)

    r6 = pd.read_parquet(STAGE / "r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet")
    key = r6.loc[r6.ticker.eq("FLYX") & r6.signal_date.eq(DAY)]
    assert len(key) == 1 and key.final_input_gate.iloc[0] == "INPUT_VERIFIED_THIS_GATE"
    assert key.cusip.iloc[0] == "343928107"
    assert " ".join(key.title_of_class.iloc[0].split()) == "COM CL A"
    assert bool(key.lookback_121_eligible.iloc[0]) and bool(key.has_32_finite.iloc[0])
    assert bool(key.coordinate_match.iloc[0])

    one = pd.DataFrame([{
        "ticker": "FLYX", "trade_date": DAY,
        "open_authorized": True, "close_authorized": True,
        "evidence_id": "R4_FLYX_GENUINE_UNADJUSTED_JUMP_2026-01-08",
        "open": float(price.open), "close": float(price.close),
        "candidate_pool_version": "R6_UNCHANGED", "r7_candidate_evidence": False,
        "old_affected_holding": False,
        "open_evidence_basis": "ORIGINAL_APPROVED_RAW_OPEN_REPEATED_971_OHLCV_ZERO_ERROR_NO_REHAB_EVENT",
        "close_evidence_basis": "ISSUER_2026_01_09_PROSPECTUS_CONFIRMS_2026_01_08_NYSE_AMERICAN_CLOSE",
    }])
    one.to_csv(HERE / "FLYX_JUMP_20260108_FIELD_PROOF.csv", index=False)
    one.to_parquet(HERE / "FLYX_JUMP_20260108_FIELD_PROOF.parquet", index=False)

    r7 = pd.read_parquet(HERE / "R7_EVENT_PRICE_FIELD_ALLOWLIST.parquet")
    assert not r7.ticker.eq("FLYX").any()
    common_cols = ["ticker", "trade_date", "open_authorized", "close_authorized", "evidence_id", "open", "close", "candidate_pool_version", "r7_candidate_evidence", "old_affected_holding"]
    merged = pd.concat([r7[common_cols], one[common_cols]], ignore_index=True).sort_values(["ticker", "trade_date"])
    assert len(merged) == 812 and not merged.duplicated(["ticker", "trade_date"]).any()
    unchanged = merged.merge(r7[common_cols], on=["ticker", "trade_date"], validate="one_to_one", suffixes=("_v2", "_r7"))
    assert len(unchanged) == 811
    for col in common_cols[2:]:
        assert unchanged[f"{col}_v2"].equals(unchanged[f"{col}_r7"]), col
    extra = merged.merge(r7[["ticker", "trade_date"]], on=["ticker", "trade_date"], how="left", indicator=True)
    assert len(extra.loc[extra._merge.eq("left_only")]) == 1
    assert extra.loc[extra._merge.eq("left_only"), ["ticker", "trade_date"]].iloc[0].tolist() == ["FLYX", DAY]
    merged.to_csv(HERE / "APPROVED_PRICE_FIELDS_V2.csv", index=False)
    merged.to_parquet(HERE / "APPROVED_PRICE_FIELDS_V2.parquet", index=False)

    inputs = {
        "old_raw": old_raw, "new_raw": new_raw,
        "overlap_check": R4 / "JUMP_TWO_CODE_RAW_OVERLAP_CHECK.csv",
        "initial_adjustment_state": STAGE / "identity_feature_application_r1/CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv",
        "old_consumed_price_events": WORKSPACE / "a2_complete_suite_20260927/data/consumed_price_events.parquet",
        "joint_test_prices": JOINT / "data/test_prices.parquet",
        "r6_candidate_gate": STAGE / "r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet",
        "r7_first_cash_allowlist": HERE / "R7_EVENT_PRICE_FIELD_ALLOWLIST.parquet",
    }
    report = {
        "status": "FLYX_ONE_DAY_OPEN_CLOSE_PROVEN_FROM_EXISTING_EVIDENCE",
        "field_proof": one.assign(trade_date=one.trade_date.dt.date.astype(str)).to_dict("records")[0],
        "source_html": source_html,
        "source_sha256": {name: {"path": str(path), "sha256": sha(path)} for name, path in inputs.items()},
        "merged_allowlist_version": "APPROVED_PRICE_FIELDS_V2",
        "merged_allowlist_ticker_dates": len(merged),
        "merged_allowlist_csv_sha256": sha(HERE / "APPROVED_PRICE_FIELDS_V2.csv"),
        "merged_allowlist_parquet_sha256": sha(HERE / "APPROVED_PRICE_FIELDS_V2.parquet"),
        "r7_811_rows_unchanged": True,
        "v2_only_addition": {"ticker": "FLYX", "trade_date": DAY.date().isoformat()},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    (HERE / "FLYX_JUMP_20260108_PROOF.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"flyx_open": bool(one.open_authorized.iloc[0]), "flyx_close": bool(one.close_authorized.iloc[0]), "merged_ticker_dates": len(merged)}))


if __name__ == "__main__":
    main()
