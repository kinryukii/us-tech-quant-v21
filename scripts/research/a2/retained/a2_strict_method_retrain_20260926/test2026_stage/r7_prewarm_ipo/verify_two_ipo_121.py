"""Prove 53 exact NIQ/STUB days cannot satisfy original 121 sessions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
R6 = STAGE / "r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet"
RAW = STAGE / "fixed_window_raw"
ORIGINALS = STAGE / "r4_identity_residual/first_trade_originals"
YEAR = Path(r"D:\us-tech-quant-data\moomoo\source\prices_raw")
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]
ORIGINAL_FILE = {"NIQ": ORIGINALS / "NIQ_FIRST_TRADE_ORIGINAL.html",
                 "STUB": ORIGINALS / "STUB_FIRST_TRADE_ORIGINAL.pdf"}


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
    meta = json.loads((HERE / "IPO_FIRST_TRADE_SOURCES.json").read_text("utf-8"))
    source = {x["ticker"]: x for x in meta["sources"]}
    assert set(source) == {"NIQ", "STUB"}
    assert sha(R6) == "46b4af4c87c760817bd9244ec82886b258a844b1b14dac96f3acfd5e0764e830"
    ledger = pd.read_parquet(R6)
    assert len(ledger) == 111868
    assert key_sha(ledger) == "0f4167d679f1e38b94ffff6488088ad27a6fa6ea1dfd84aa63f8308ae17f96d1"
    assert not ledger.duplicated(KEY).any()
    qqq_files = [YEAR / f"year={y}" / "prices.parquet" for y in (2025, 2026)]
    qqq = pd.concat([pd.read_parquet(path, columns=["ticker", "trade_date"]) for path in qqq_files], ignore_index=True)
    calendar = pd.DatetimeIndex(pd.to_datetime(qqq.loc[qqq.ticker.eq("QQQ"), "trade_date"]).drop_duplicates().sort_values())
    assert calendar.is_unique and calendar.is_monotonic_increasing
    selected = ledger.loc[ledger.ticker.isin(source) & ledger.final_input_gate.eq("UNKNOWN_121_HISTORY")].copy()
    assert len(selected) == sum(x["candidate_days"] for x in source.values()) == 53
    assert selected.final_input_gate.eq("UNKNOWN_121_HISTORY").all()
    assert not selected.lookback_121_eligible.fillna(False).any()
    assert not selected[["proven_lifecycle_ineligible", "proven_121_ineligible"]].any().any()
    rows = []
    reports = []
    for ticker, item in source.items():
        original = ORIGINAL_FILE[ticker]
        assert sha(original) == item["issuer_saved_original_sha256"]
        raw_file = RAW / f"RAW_US_{ticker}_K_DAY_NONE_RTH.parquet"
        raw = pd.read_parquet(raw_file, columns=["code", "name", "trade_date"])
        assert raw.code.eq(f"US.{ticker}").all()
        assert str(raw.trade_date.min().date()) == item["same_source_raw_first_date"] == item["first_public_trading_date"]
        part = selected.loc[selected.ticker.eq(ticker)]
        assert len(part) == item["candidate_days"]
        assert part.cusip.eq(item["cusip"]).all()
        assert part.title_of_class.eq(item["title_of_class"]).all()
        assert str(part.signal_date.max().date()) == item["candidate_last_signal"]
        assert part.signal_date.isin(calendar).all()
        session_counts = [int(calendar[(calendar >= pd.Timestamp(item["first_public_trading_date"])) &
                                       (calendar <= pd.Timestamp(date))].size) for date in part.signal_date]
        assert max(session_counts) == item["calendar_sessions_through_last_signal_inclusive"] == 120
        assert all(n < 121 for n in session_counts)
        for record, n in zip(part[KEY].to_dict("records"), session_counts):
            rows.append({**record, "ticker": ticker, "first_public_trading_date": item["first_public_trading_date"],
                         "available_public_sessions_inclusive": n,
                         "prior_gate": "UNKNOWN_121_HISTORY", "proposed_gate": "PROVEN_ORIGINAL_121_INELIGIBLE",
                         "issuer_primary_url": item["issuer_pre_ipo_url"], "exchange_primary_url": item["exchange_ipo_url"]})
        reports.append({"ticker": ticker, "candidate_days": len(part), "max_public_sessions": max(session_counts),
                        "issuer_original_sha256": sha(original), "raw_sha256": sha(raw_file)})
    proof = pd.DataFrame(rows)
    assert len(proof) == 53 and not proof.duplicated(KEY).any()
    proof.to_parquet(HERE / "R7_53_IPO_ORIGINAL_121_INELIGIBLE_EXACT_KEYS.parquet", index=False)
    report = {"status": "TWO_IPO_53_ORIGINAL_121_INELIGIBLE_EXACT_KEY_PROPOSAL",
              "decision": "IPO primary sources plus original same-source first Raw row; no first-row-only inference",
              "parent_r6_sha256": sha(R6), "candidate_key_fingerprint_sha256": key_sha(ledger),
              "original_qqq_calendar_sources": {str(p): sha(p) for p in qqq_files},
              "exact_keys": len(proof), "proposed_key_sha256": key_sha(proof), "securities": reports,
              "model_fit_calls": 0, "preprocessor_fit_calls": 0}
    (HERE / "R7_IPO_121_PROPOSAL_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps({"exact_keys": len(proof), "max_sessions": {x["ticker"]: x["max_public_sessions"] for x in reports}}))


if __name__ == "__main__":
    main()
