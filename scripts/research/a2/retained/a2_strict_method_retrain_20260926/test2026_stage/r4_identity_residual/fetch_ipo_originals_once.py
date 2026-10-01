"""Fetch only 16 cited issuer/exchange first-trade originals; no market data calls."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent / "first_trade_originals"
OUT.mkdir(exist_ok=True)
SOURCES = {
    "AERO": "https://ir.aeromexico.com/ir-resources/investor-faqs",
    "ARX": "https://accelerant.ai/resources/accelerant-holdings-announces-closing-of-upsized-initial-public-offering-and-full-exercise-of-over-allotment-option/",
    "BLSH": "https://investors.bullish.com/shareholder-services/investor-faqs",
    "BRCB": "https://ir.br.coffee/node/6996/pdf",
    "EQPT": "https://equipmentshare.gcs-web.com/news-releases/news-release-details/equipmentshare-debuts-nasdaq-eqpt-advancing-digital",
    "FIG": "https://investor.figma.com/news-events/news/news-details/2025/Figma-Announces-Pricing-of-Initial-Public-Offering/default.aspx",
    "FIGR": "https://investors.figure.com/news-releases/news-release-details/figure-technology-solutions-inc-announces-pricing-initial-public",
    "GEMI": "https://investors.gemini.com/news-releases/news-release-details/gemini-announces-closing-initial-public-offering-and-full",
    "KLAR": "https://investors.klarna.com/News--Events/news/news-details/2025/Klarna-Completes-Initial-Public-Offering-64c932a0c/default.aspx",
    "NAVN": "https://navan.gcs-web.com/news-releases/news-release-details/navan-announces-closing-initial-public-offering",
    "NIQ": "https://nielseniq.com/global/en/news-center/2025/niq-announces-pricing-of-initial-public-offering/",
    "NP": "https://investors.neptuneflood.com/news/news-details/2025/Neptune-Insurance-Holdings-Inc--Announces-Full-Exercise-of-Underwriters-Option-to-Purchase-Additional-Shares-and-Closing-of-Initial-Public-Offering/default.aspx",
    "NTSK": "https://investors.netskope.com/shareholder-services/investor-faqs",
    "PTRN": "https://investors.pattern.com/ir-resources/investor-faqs",
    "STUB": "https://s204.q4cdn.com/138970181/files/doc_news/StubHub-Announces-Pricing-of-Initial-Public-Offering-2025.pdf",
    "VIA": "https://investors.ridewithvia.com/news/news-details/2025/Via-Announces-Pricing-of-Initial-Public-Offering/default.aspx",
}


def get(item: tuple[str, str]) -> dict:
    ticker, url = item
    record = {"ticker": ticker, "url": url, "retrieved_utc": datetime.now(timezone.utc).isoformat()}
    try:
        response = requests.get(url, timeout=10, allow_redirects=True,
                                headers={"User-Agent": "Mozilla/5.0"})
        record.update({"http_status": response.status_code, "final_url": response.url,
                       "content_type": response.headers.get("Content-Type", ""),
                       "bytes": len(response.content)})
        if response.status_code == 200 and len(response.content) > 500:
            suffix = ".pdf" if response.content.startswith(b"%PDF") else ".html"
            path = OUT / f"{ticker}_FIRST_TRADE_ORIGINAL{suffix}"
            path.write_bytes(response.content)
            record.update({"saved_path": str(path),
                           "sha256": hashlib.sha256(response.content).hexdigest(),
                           "status": "SAVED_ORIGINAL_NEEDS_TEXT_VALIDATION"})
        else:
            record["status"] = "HTTP_OR_EMPTY"
    except Exception as exc:
        record.update({"status": "ACCESS_ERROR", "error": type(exc).__name__ + ": " + str(exc)[:200]})
    return record


def main() -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        rows = list(executor.map(get, SOURCES.items()))
    path = OUT.parent / "FIRST_TRADE_ORIGINAL_FETCH_RECEIPTS.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"total": len(rows), "saved": sum(r["status"].startswith("SAVED") for r in rows),
                      "errors": [r["ticker"] for r in rows if not r["status"].startswith("SAVED")]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
