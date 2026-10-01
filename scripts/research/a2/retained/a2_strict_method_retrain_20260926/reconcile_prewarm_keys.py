"""Apply prior 121-session rulings to exact original-security candidate days."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
OLD = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"
OUT = STAGE / "identity_feature_application_r1"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    current_path = STAGE / "fixed_window_binding/full_window_candidate_raw_status.parquet"
    prior_path = OLD / "REMAINING75_INPUT_AUDIT.json"
    current = pd.read_parquet(current_path)
    assert len(current) == 111868
    prewarm = current.loc[current.input_status.eq("UNKNOWN_RAW_121_OR_PREWARM_INCOMPLETE")].copy()
    assert len(prewarm) == 983
    key = ["cusip", "title_of_class", "quarter", "signal_date"]
    assert not prewarm.duplicated(key).any()
    old = json.loads(prior_path.read_text(encoding="utf-8"))
    prior_unknown = []
    identity = current[["quarter", "ticker", "moomoo_transport_code", "cusip", "title_of_class"]].drop_duplicates()
    assert not identity.duplicated(["quarter", "ticker", "moomoo_transport_code"]).any()
    for item in old["outside_remaining75_unknown_keys"]:
        match = identity.loc[identity.quarter.eq(item["quarter"]) & identity.ticker.eq(item["ticker"])
            & identity.moomoo_transport_code.eq(item["code"])]
        assert len(match) == 1, item
        original = match.iloc[0]
        assert len(item["signal_dates"]) == item["days"]
        for day in item["signal_dates"]:
            prior_unknown.append({"cusip": original.cusip, "title_of_class": original.title_of_class,
                                  "quarter": item["quarter"], "signal_date": pd.Timestamp(day),
                                  "prior_verdict": "UNKNOWN_LOCAL_HISTORY_OR_FEATURE",
                                  "evidence": "REMAINING75_INPUT_AUDIT.outside_remaining75_unknown_keys"})
    prior_unknown = pd.DataFrame(prior_unknown)
    assert len(prior_unknown) == 768 and not prior_unknown.duplicated(key).any()
    official = []
    for item in old["official_121_ineligibility_sources"]:
        if item["ticker"] == "LLYVB":
            continue  # alias identity is applied in the separate 75-case pass
        match = identity.loc[identity.ticker.eq(item["ticker"]) & identity.cusip.eq(item["original_cusip"])
            & identity.title_of_class.eq(item["original_share_class"])]
        assert not match.empty and len(match) == match.quarter.nunique(), item
        for row in match.itertuples(index=False):
            dates = prewarm.loc[prewarm.cusip.eq(item["original_cusip"])
                & prewarm.title_of_class.eq(item["original_share_class"])
                & prewarm.quarter.eq(row.quarter), "signal_date"]
            for day in dates:
                assert day < pd.Timestamp(item["first_eligible_session"])
                official.append({"cusip": row.cusip, "title_of_class": row.title_of_class,
                                 "quarter": row.quarter, "signal_date": day,
                                 "prior_verdict": "PROVEN_ORIGINAL_121_INELIGIBLE",
                                 "evidence": item["official_source"],
                                 "first_trade": item["first_trade"],
                                 "first_eligible_session": item["first_eligible_session"]})
    official = pd.DataFrame(official)
    assert len(official) == 215 and not official.duplicated(key).any()
    verdicts = pd.concat([prior_unknown, official], ignore_index=True)
    assert len(verdicts) == 983 and not verdicts.duplicated(key).any()
    matched = prewarm.merge(verdicts, on=key, how="left", validate="one_to_one", indicator=True)
    assert matched._merge.eq("both").all()
    matched = matched.drop(columns=["_merge"])
    matched.to_parquet(OUT / "PREWARM_983_EXACT_KEY_RECONCILIATION.parquet", index=False)
    report = {"status": "EXACT_KEY_983_RECONCILED",
              "current_raw_status_sha256": sha(current_path), "prior_audit_sha256": sha(prior_path),
              "match_key": key, "total": len(matched),
              "proven_original_121_ineligible": int(matched.prior_verdict.eq("PROVEN_ORIGINAL_121_INELIGIBLE").sum()),
              "still_unknown": int(matched.prior_verdict.eq("UNKNOWN_LOCAL_HISTORY_OR_FEATURE").sum()),
              "unmatched": 0,
              "raw_first_date_used_as_first_trade_proof": False,
              "llyvb_alias_separate": "LLYVB original CUSIP 530909308 requires correct alias before 121 verdict; excluded from this 983 subset",
              "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0}
    (OUT / "PREWARM_983_RECONCILIATION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"total": len(matched), "proven_121": report["proven_original_121_ineligible"],
                      "unknown": report["still_unknown"]}))


if __name__ == "__main__":
    main()
