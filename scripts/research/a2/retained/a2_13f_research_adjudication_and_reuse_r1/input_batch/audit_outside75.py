"""Bounded read-only audit of original-pool securities' 121-session gate."""

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
OLD = HERE.parent.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"
UNIVERSE = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\universe\quarterly_universe_members.parquet")
FIRST = {
    "BRCB": ("2025-09-12", "092244102", "CL A", "https://ir.br.coffee/ir-resources/investor-faqs"),
    "NIQ": ("2025-07-23", "G63755105", "ORDINARY SHARES", "https://www.sec.gov/Archives/edgar/data/2054696/000114036125042334/xslSCHEDULE_13G_X01/primary_doc.xml|https://nielseniq.com/global/en/news-center/2025/niq-announces-pricing-of-initial-public-offering/"),
    "PTRN": ("2025-09-19", "70339W104", "COM SER A", "https://investors.pattern.com/static-files/ac6d1ea7-eb40-439d-866f-deb50badd296|https://investors.pattern.com/news-releases/news-release-details/pattern-announces-closing-initial-public-offering"),
    "MDLN": ("2025-12-17", "58507V107", "COM CL A", "https://ir.medline.com/static-files/852d053a-3436-41bf-b4c4-6e1d8fcc4c96|https://ir.medline.com/investor-resources/investor-faqs"),
    "WLTH": ("2025-12-12", "947002101", "COM", "https://ir.wealthfront.com/static-files/583afc6f-67ad-46e2-b80f-9216e3ce249b|https://ir.wealthfront.com/news-releases/news-release-details/wealthfront-announces-pricing-initial-public-offering"),
    "AERO": ("2025-11-06", "40054J109", "SPONSORED ADS", "https://ir.aeromexico.com/static-files/1948be39-1654-4a31-8576-bc785432307b|https://ir.aeromexico.com/node/8281/html"),
    "FIG": ("2025-07-31", "316841105", "CLASS A COM STK", "https://investor.figma.com/news-events/news/news-details/2025/Figma-Announces-Pricing-of-Initial-Public-Offering/default.aspx"),
    "FIGR": ("2025-09-11", "349381103", "COM CL A", "https://investors.figure.com/news-releases/news-release-details/figure-technology-solutions-inc-announces-pricing-initial-public|https://investors.figure.com/static-files/d2dc442c-fba4-4351-9dbf-772b455c477c"),
    "GEMI": ("2025-09-12", "36866J105", "CL A COM", "https://investors.gemini.com/news-releases/news-release-details/gemini-announces-pricing-initial-public-offering|https://investors.gemini.com/static-files/ebde336e-7f8b-4966-a353-0a9eb4792dfc"),
    "KLAR": ("2025-09-10", "G5279N105", "SHS", "https://investors.klarna.com/News--Events/news/news-details/2025/Klarna-Completes-Initial-Public-Offering-64c932a0c/default.aspx|https://www.sec.gov/Archives/edgar/data/1607841/000119312526224178/xslForm13F_X02/53320.xml"),
    "NTSK": ("2025-09-18", "64119N608", "CL A", "https://investors.netskope.com/shareholder-services/investor-faqs|https://www.sec.gov/Archives/edgar/data/1471497/000091957426003089/xslSCHEDULE_13G_X02/primary_doc.xml"),
    "STUB": ("2025-09-17", "86384P109", "CL A", "https://investors.stubhub.com/news/news-details/2025/StubHub-Announces-Pricing-of-Initial-Public-Offering/default.aspx|https://www.sec.gov/Archives/edgar/data/1337634/000090266426001925/xslSCHEDULE_13G_X02/primary_doc.xml"),
    "VIA": ("2025-09-12", "92556W104", "COM CL A", "https://investors.ridewithvia.com/news/news-details/2025/Via-Announces-Pricing-of-Initial-Public-Offering/default.aspx|https://www.sec.gov/Archives/edgar/data/1603015/000208375325000009/xslSCHEDULE_13G_X01/primary_doc.xml"),
    "NAVN": ("2025-10-30", "639193101", "CL A", "https://investors.navan.com/ir-resources/investor-faqs"),
    "ARX": ("2025-07-24", "G00894108", "CL A", "https://investor.accelerant.ai/news/news-details/2025/Accelerant-Holdings-Announces-Closing-of-Upsized-Initial-Public-Offering-and-Full-Exercise-of-Over-Allotment-Option/default.aspx"),
    "BLSH": ("2025-08-13", "G16910120", "Common Stock", "https://investors.bullish.com/shareholder-services/investor-faqs"),
    "NP": ("2025-10-01", "64073B103", "CL A", "https://investors.neptuneflood.com/news/news-details/2025/Neptune-Insurance-Holdings-Inc--Announces-Pricing-of-Initial-Public-Offering/default.aspx"),
    "EQPT": ("2026-01-23", "29445S100", "COM CL A", "https://www.equipmentshare.com/press-releases/equipmentshare-debuts-on-nasdaq-as-eqpt-advancing-the-digital-transformation-of-construction"),
    "PURR": ("2025-12-03", "44916Y106", "COM", "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2025-647"),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    audit = json.loads((OLD / "REMAINING75_INPUT_AUDIT.json").read_text(encoding="utf-8"))
    keys = audit["outside_remaining75_unknown_keys"]
    original = pd.read_parquet(UNIVERSE)
    sessions = pd.read_csv(OLD / "SUBSCRIPTION_US_TRADING_DAYS.csv")["time"].tolist()
    sessions = [x for x in sessions if x <= "2026-09-22"]
    rows = []
    for key in keys:
        ticker = key["ticker"]
        q = key["quarter"]
        orig = original[(original.quarter == q) & (original.ticker == ticker)]
        assert len(orig) == 1, (q, ticker, len(orig))
        row = orig.iloc[0]
        dates = key["signal_dates"]
        assert len(dates) == key["days"]
        raw = next((p for p in [OLD / f"SUBSCRIPTION_US_{ticker}_RAW_DAY_K_INPUT_ONLY.parquet", OLD / f"REUSED_US_{ticker}_RAW_DAY_K.parquet"] if p.exists()), None)
        raw_first = raw_last = raw_rows = ""
        if raw:
            d = pd.read_parquet(raw, columns=["trade_date"])
            raw_first, raw_last, raw_rows = d.trade_date.min(), d.trade_date.max(), len(d)
        first_trade = first_eligible = refs = ""
        proven = 0
        pending = dates
        status = "UNCHANGED_UNKNOWN_121_OR_PRICE"
        if ticker in FIRST:
            first_trade, cusip, share_class, refs = FIRST[ticker]
            assert row.cusip == cusip, (ticker, row.cusip, cusip)
            assert row.title_of_class == share_class or (ticker == "FIG" and row.title_of_class == "Common Stock"), (ticker, row.title_of_class, share_class)
            ix = sessions.index(first_trade)
            first_eligible = sessions[ix + 120]
            proven_dates = [x for x in dates if x < first_eligible]
            pending = [x for x in dates if x >= first_eligible]
            proven = len(proven_dates)
            status = "PROVEN_PRE_121_ONLY" if pending else "PROVEN_121_INELIGIBLE_ALL_KEY_DATES"
        rows.append({
            "quarter": q, "ticker": ticker, "original_cusip": row.cusip,
            "original_share_class": row.title_of_class, "unknown_days_before": len(dates),
            "authoritative_first_trade": first_trade, "first_possible_121_signal": first_eligible,
            "proven_121_ineligible_days": proven, "still_unknown_days": len(pending),
            "still_unknown_signal_dates": "|".join(pending),
            "raw_path": str(raw) if raw else "", "raw_sha256": sha(raw) if raw else "",
            "raw_rows": raw_rows, "raw_first": raw_first, "raw_last": raw_last,
            "status": status, "official_sources": refs,
        })
    out = HERE / "OUTSIDE75_121_BATCH.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    summary = {
        "purpose": "One bounded input evidence batch; read-only old inputs; no pricing request or policy test",
        "batch_started_utc": "2026-09-26T03:37:55Z",
        "batch_completed_utc": datetime.now(timezone.utc).isoformat(),
        "time_budget_minutes": 90,
        "fixed_test_asof": "2026-09-23T18:40:43Z",
        "keys_checked": len(rows), "original_unknown_outside75": sum(x["unknown_days_before"] for x in rows),
        "keys_resolved_as_original_rule_ineligible": sum(x["still_unknown_days"] == 0 for x in rows),
        "authority_resolved_tickers": sorted(FIRST),
        "proven_121_ineligible_candidate_days": sum(x["proven_121_ineligible_days"] for x in rows),
        "remaining_outside75_unknown_candidate_days": sum(x["still_unknown_days"] for x in rows),
        "remaining_outside75_keys": [{"quarter": x["quarter"], "ticker": x["ticker"], "unknown_days": x["still_unknown_days"], "signal_dates": x["still_unknown_signal_dates"]} for x in rows if x["still_unknown_days"]],
        "remaining75_unknown_candidate_days_unchanged": audit["remaining75_unknown_candidate_days"],
        "full_pool_unknown_candidate_days_after_batch": audit["remaining75_unknown_candidate_days"] + sum(x["still_unknown_days"] for x in rows),
        "raw_new_requests": 0, "raw_new_success": 0, "fits": 0, "formal_2026_reveals": 0,
        "gate": "BLOCKED: 2025Q4 Q when-issued history, 75-table candidate dates, and as-of company-action versions; no formal policy run",
        "method_note": "Only dates earlier than the 121st session counting each verified first regular-trade day are ruled out; this does not qualify later prices or settlement.",
        "old_audit_sha256": sha(OLD / "REMAINING75_INPUT_AUDIT.json"),
        "old_quarterly_universe_sha256": sha(UNIVERSE),
        "old_calendar_sha256": sha(OLD / "SUBSCRIPTION_US_TRADING_DAYS.csv"),
    }
    (HERE / "BATCH_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for x in rows:
        if x["ticker"] in FIRST:
            print(x["quarter"], x["ticker"], x["proven_121_ineligible_days"], x["still_unknown_days"], x["first_possible_121_signal"])


if __name__ == "__main__":
    main()
