"""Apply four early-published, single-event cash actions to exact A2 keys."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent / "test2026_stage"
OUT = ROOT / "r6_contract_correction"
EVENT = ROOT / "r4_event_pit"
GRAPH = ROOT / "r5_dependency_analysis/R5_UNKNOWN_CUMULATIVE_2026_EVENT_EXPOSURES.parquet"
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def key_sha(frame: pd.DataFrame) -> str:
    keys = frame[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(keys, index=False).to_numpy().tobytes()).hexdigest()


def main() -> None:
    source = OUT / "FOUR_SINGLE_EVENT_PRIMARY_VERDICTS.json"
    meta = json.loads(source.read_text("utf-8"))
    rule = ROOT / "finra_rule_11140_2026_snapshot.html"
    assert sha(rule) == meta["finra_rule_local_sha256"]
    assert len(meta["events"]) == 4
    codes = {x["code"] for x in meta["events"]}
    assert codes == {"US.WHR", "US.NWSA", "US.RERE", "US.JD"}
    audit = pd.read_csv(EVENT / "ALL_1094_EVENT_PRIORITY.csv", keep_default_na=False)
    ledger = pd.read_parquet(OUT / "R6_FINAL_CANDIDATE_INPUT_GATE.parquet")
    assert len(ledger) == 111868 and key_sha(ledger) == "0f4167d679f1e38b94ffff6488088ad27a6fa6ea1dfd84aa63f8308ae17f96d1"
    exposures = pd.read_parquet(GRAPH, columns=KEY + ["moomoo_transport_code", "event_date"])
    selected_edges = exposures.loc[exposures.moomoo_transport_code.isin(codes)]
    counts = selected_edges.groupby(KEY).size().rename("consumed_2026_event_count").reset_index()
    selected = ledger.loc[ledger.moomoo_transport_code.isin(codes) &
                          ledger.final_input_gate.eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME")].copy()
    selected = selected.merge(counts, on=KEY, how="left", validate="one_to_one")
    assert selected.consumed_2026_event_count.eq(1).all()
    assert len(selected) == sum(x["exact_candidate_days_if_other_gates_pass"] for x in meta["events"]) == 511
    assert selected.feature_error.fillna("").eq("").all()
    assert selected[["lookback_121_eligible", "has_32_finite", "version_checked"]].all().all()
    assert not selected[["proven_lifecycle_ineligible", "proven_121_ineligible",
                         "no_frozen_coordinate_overlap", "unexplained_raw_jump_dependency",
                         "multi_cusip_transport_interval_pending"]].any().any()
    assert selected["2026_event_publication_time_unverified"].all()

    proof_rows = []
    for item in meta["events"]:
        code = item["code"]
        a = audit.loc[audit.code.eq(code) & audit.source_event_date.eq(item["record_and_original_ex_date"])]
        assert len(a) == 1, code
        a = a.iloc[0]
        assert float(a.factor_b) == 0
        assert float(a.total_cash_div) == float(item["cash_per_original_traded_share_usd"])
        prior = float(a.prior_raw_close)
        cash = float(a.total_cash_div)
        assert 0 < cash / prior < 0.25
        assert math.floor((1 - cash / prior) * 1e5) / 1e5 == float(a.factor_a)
        assert str(a.simple_cash_floor_matches_vendor).lower() == "true"
        assert item["issuer_public_date"] < item["record_and_original_ex_date"]
        part = selected.loc[selected.moomoo_transport_code.eq(code)]
        assert len(part) == item["exact_candidate_days_if_other_gates_pass"]
        assert part.cusip.eq(item["cusip"]).all() and part.title_of_class.eq(item["title_of_class"]).all()
        assert pd.to_datetime(part.signal_date).ge(pd.Timestamp(item["record_and_original_ex_date"])).all()
        assert pd.to_datetime(part.signal_date).gt(pd.Timestamp(item["issuer_public_date"])).all()
        assert pd.to_datetime(part.first_consumed_2026_event).eq(pd.Timestamp(item["record_and_original_ex_date"])).all()
        for row in part[KEY].to_dict("records"):
            proof_rows.append({**row, "event_code": code, "issuer_public_date": item["issuer_public_date"],
                               "record_and_original_ex_date": item["record_and_original_ex_date"],
                               "original_factor_a": float(a.factor_a), "source_url": item["source_url"],
                               "source_body_local": False,
                               "exdate_basis": "FINRA_11140_B1_WITH_ORIGINAL_VENDOR_EXDATE"})
    proof = pd.DataFrame(proof_rows)
    assert len(proof) == 511 and not proof.duplicated(KEY).any()
    proof.to_parquet(OUT / "FOUR_SINGLE_EVENTS_511_EXACT_KEY_PROOF.parquet", index=False)
    proof = proof.rename(columns={c: "single_event_" + c for c in proof if c not in KEY})
    after = ledger.merge(proof, on=KEY, how="left", validate="one_to_one", indicator="_single_match")
    mask = after._single_match.eq("both")
    assert int(mask.sum()) == 511
    assert after.loc[mask, "final_input_gate"].eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").all()
    after["pre_single_event_gate"] = after.final_input_gate
    after.loc[mask, "2026_event_publication_time_unverified"] = False
    after.loc[mask, "final_input_gate"] = "INPUT_VERIFIED_THIS_GATE"
    after = after.drop(columns="_single_match")
    original = ledger.columns.tolist()
    pd.testing.assert_frame_equal(after.loc[~mask, original].reset_index(drop=True),
                                  ledger.loc[~mask, original].reset_index(drop=True), check_dtype=True)
    stable = [c for c in original if c not in ("2026_event_publication_time_unverified", "final_input_gate")]
    pd.testing.assert_frame_equal(after.loc[mask, stable].reset_index(drop=True),
                                  ledger.loc[mask, stable].reset_index(drop=True), check_dtype=True)
    assert len(after) == 111868 and not after.duplicated(KEY).any()
    assert key_sha(after) == "0f4167d679f1e38b94ffff6488088ad27a6fa6ea1dfd84aa63f8308ae17f96d1"
    after.to_parquet(OUT / "R6_FULL_CANDIDATE_INPUT_GATE.parquet", index=False)
    after.loc[mask, KEY + ["ticker", "moomoo_transport_code", "pre_single_event_gate", "final_input_gate",
                           "single_event_event_code", "single_event_source_url", "single_event_exdate_basis"]].to_parquet(
        OUT / "R6_FOUR_SINGLE_EVENTS_511_STATUS_TRANSITIONS.parquet", index=False)
    verified = int(after.final_input_gate.str.startswith("INPUT_VERIFIED").sum())
    ineligible = int(after.final_input_gate.str.startswith("PROVEN_").sum())
    unknown = int(after.final_input_gate.str.startswith("UNKNOWN_").sum())
    assert (verified, ineligible, unknown) == (61963, 2204, 47701)
    report = {"status": "FOUR_SINGLE_CASH_EVENTS_APPLIED_EXACT_KEY",
              "new_verified_candidate_days": 511, "verified": verified,
              "proven_ineligible": ineligible, "remaining_unknown": unknown,
              "candidate_key_fingerprint_sha256": key_sha(after),
              "final_ledger_sha256": sha(OUT / "R6_FULL_CANDIDATE_INPUT_GATE.parquet"),
              "model_objects_loaded": 0, "model_fit_calls": 0, "preprocessor_fit_calls": 0}
    (OUT / "R6_SINGLE_EVENT_APPLICATION_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps({"new_verified": 511, "unknown": unknown}))


if __name__ == "__main__":
    main()
