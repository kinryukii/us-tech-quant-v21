"""Propose bounded first-cash-event A2 keys without modifying the r6 ledger."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd


OUT = Path(__file__).resolve().parent
STAGE = OUT.parent
R6 = STAGE / "r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet"
GRAPH = STAGE / "r5_dependency_analysis/R5_UNKNOWN_CUMULATIVE_2026_EVENT_EXPOSURES.parquet"
AUDIT = STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv"
FINRA = STAGE / "finra_rule_11140_2026_snapshot.html"
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]
EXPECTED_R6_SHA = "46b4af4c87c760817bd9244ec82886b258a844b1b14dac96f3acfd5e0764e830"
EXPECTED_KEY_SHA = "0f4167d679f1e38b94ffff6488088ad27a6fa6ea1dfd84aa63f8308ae17f96d1"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def key_sha(frame: pd.DataFrame) -> str:
    ordered = frame[KEY].sort_values(KEY, kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(ordered, index=False).to_numpy().tobytes()).hexdigest()


def normalized_class(value: str) -> str:
    return " ".join(value.split())


def main() -> None:
    sources = json.loads((OUT / "EVENT_SOURCES.json").read_text("utf-8"))
    assert len(sources["events"]) == 12
    assert len({event["code"] for event in sources["events"]}) == 12
    assert sha(FINRA) == sources["finra_rule_local_sha256"]
    assert sha(R6) == EXPECTED_R6_SHA

    ledger = pd.read_parquet(R6)
    assert len(ledger) == 111868 and key_sha(ledger) == EXPECTED_KEY_SHA
    assert not ledger.duplicated(KEY).any()
    exposures = pd.read_parquet(GRAPH, columns=KEY + ["moomoo_transport_code", "event_date"])
    counts = exposures.groupby(KEY, sort=False).agg(
        consumed_2026_event_count=("event_date", "size"),
        only_event_date=("event_date", "first"),
    ).reset_index()
    audit = pd.read_csv(AUDIT, keep_default_na=False)

    all_proofs = []
    verdicts = []
    for event in sources["events"]:
        code = event["code"]
        record = event["record_date"]
        public = event["public_date"]
        source_rows = audit.loc[audit.code.eq(code) & audit.source_event_date.eq(record)]
        assert len(source_rows) == 1, (code, "original action not unique")
        action = source_rows.iloc[0]
        assert str(action.share_event).lower() == "false", code
        assert str(action.manual_wolf).lower() == "false", code
        assert float(action.factor_b) == 0.0, code
        assert float(action.total_cash_div) == float(event["cash_usd_per_original_share"]), code
        assert str(action.simple_cash_floor_matches_vendor).lower() == "true", code
        prior = float(action.prior_raw_close)
        cash = float(action.total_cash_div)
        assert prior > 0 and 0 < cash / prior < 0.25, code
        reconstructed = math.floor((1 - cash / prior) * 100000) / 100000
        assert reconstructed == float(action.factor_a), code
        assert public < record and pd.Timestamp(record).dayofweek < 5, code

        next_actions = audit.loc[audit.code.eq(code) & audit.source_event_date.gt(record), "source_event_date"]
        assert len(next_actions), (code, "missing next event boundary")
        next_event = next_actions.min()
        selected = ledger.loc[
            ledger.moomoo_transport_code.eq(code)
            & ledger.final_input_gate.eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME")
        ].merge(counts, on=KEY, how="left", validate="one_to_one")
        selected = selected.loc[selected.consumed_2026_event_count.eq(1)].copy()
        assert len(selected) == event["expected_exact_keys"], (code, len(selected))
        assert selected.cusip.eq(event["cusip"]).all(), code
        assert selected.title_of_class.map(normalized_class).eq(event["normalized_class"]).all(), code
        assert selected.only_event_date.eq(pd.Timestamp(record)).all(), code
        assert pd.to_datetime(selected.first_consumed_2026_event).eq(pd.Timestamp(record)).all(), code
        assert pd.to_datetime(selected.signal_date).ge(pd.Timestamp(record)).all(), code
        assert pd.to_datetime(selected.signal_date).lt(pd.Timestamp(next_event)).all(), code
        assert pd.to_datetime(selected.signal_date).gt(pd.Timestamp(public)).all(), code
        assert selected.feature_error.fillna("").eq("").all(), code
        assert selected[[
            "raw_on_signal", "raw_121_calendar_ready", "rehab_pass", "coordinate_match",
            "lookback_121_eligible", "all_features_available", "has_32_finite", "version_checked",
            "2026_event_publication_time_unverified",
        ]].all().all(), code
        assert not selected[[
            "proven_lifecycle_ineligible", "proven_121_ineligible", "no_frozen_coordinate_overlap",
            "unexplained_raw_jump_dependency", "multi_cusip_transport_interval_pending",
        ]].any().any(), code
        assert selected.coordinate_overlap_rows.gt(0).all(), code
        assert selected.candidate_status.eq("FEATURE_READY_VERSION_OVERLAP_CHECKED").all(), code

        proof = selected[KEY + ["ticker", "moomoo_transport_code"]].copy()
        proof["event_code"] = code
        proof["source_public_date"] = public
        proof["record_and_original_vendor_exdate"] = record
        proof["next_unproved_event_exclusive"] = next_event
        proof["public_cash_usd_per_original_share"] = cash
        proof["original_raw_prior_close"] = prior
        proof["original_factor_a"] = float(action.factor_a)
        proof["reconstructed_floor5_factor_a"] = reconstructed
        proof["source_url"] = event["source_url"]
        proof["exdate_basis"] = (
            "CONTEMPORANEOUS_ISSUER_EXDATE" if code == "US.MSFT" else
            "FINRA_11140_B1_RECORD_EQUALS_EXDATE_CORROBORATED_BY_ORIGINAL_VENDOR_EXDATE"
        )
        proof["historical_vendor_actual_receipt_observed"] = False
        proof["proposed_input_gate"] = "INPUT_VERIFIED_THIS_GATE"
        all_proofs.append(proof)
        verdicts.append({
            "event_code": code, "cusip": event["cusip"], "normalized_class": event["normalized_class"],
            "source_public_date": public, "record_and_original_vendor_exdate": record,
            "next_unproved_event_exclusive": next_event, "cash_usd_per_original_share": cash,
            "original_raw_prior_close": prior, "original_factor_a": float(action.factor_a),
            "reconstructed_floor5_factor_a": reconstructed, "cash_to_prior_raw_close_pct": 100 * cash / prior,
            "exact_candidate_keys": len(proof), "first_signal": selected.signal_date.min().date().isoformat(),
            "last_signal": selected.signal_date.max().date().isoformat(),
            "source_publication_tier": sources["source_tier"], "source_url": event["source_url"],
            "corroborating_exdate_url": event.get("corroborating_exdate_url", ""),
            "corroborating_exdate_source_tier": event.get("corroborating_exdate_source_tier", ""),
            "exdate_basis": proof.exdate_basis.iloc[0],
            "all_other_original_gates_pass": True,
            "historical_vendor_actual_receipt_observed": False,
            "proposed_input_gate": "INPUT_VERIFIED_THIS_GATE",
        })

    proposal = pd.concat(all_proofs, ignore_index=True).sort_values(KEY, kind="mergesort")
    assert len(proposal) == 811 and not proposal.duplicated(KEY).any()
    matches = ledger[KEY].merge(proposal[KEY], on=KEY, how="inner", validate="one_to_one")
    assert len(matches) == 811
    proposal.to_parquet(OUT / "R7_811_EXACT_KEY_PASS_PROPOSAL.parquet", index=False)
    pd.DataFrame(verdicts).to_csv(OUT / "R7_TWELVE_CASH_EVENT_VERDICTS.csv", index=False)
    report = {
        "status": "EXACT_KEY_PASS_PROPOSAL_ONLY_NOT_APPLIED_TO_R6",
        "r6_full_ledger_sha256": sha(R6), "original_candidate_count": len(ledger),
        "original_candidate_key_fingerprint_sha256": key_sha(ledger),
        "proposed_exact_keys": len(proposal), "proposed_exact_key_fingerprint_sha256": key_sha(proposal),
        "proposed_by_event": {code: int(count) for code, count in proposal.event_code.value_counts().sort_index().items()},
        "r6_unknown_event_publication_time": int(ledger.final_input_gate.eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").sum()),
        "r6_ledger_modified": False, "formal_four_model_predictions": 0,
        "model_fit_calls": 0, "preprocessor_fit_calls": 0,
        "historical_vendor_actual_receipt_observed": False,
        "original_http_bodies_saved": False,
    }
    (OUT / "R7_PROPOSAL_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps({"proposed_exact_keys": len(proposal), "by_event": report["proposed_by_event"]}))


if __name__ == "__main__":
    main()
