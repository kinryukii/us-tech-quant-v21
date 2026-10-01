"""Consume bounded pre-event issuer cash evidence for two next account blocks."""

from build_first_four_account_fields import main


EVENTS = {
    "WDC": {
        "cusip": "958102105", "first": "2026-03-05", "next": "2026-06-05",
        "public": "2026-01-30", "cash": 0.125,
        "issuer_url": "https://investor.wdc.com/static-files/9156ba67-47c8-4be7-8513-acfdbc8b149b",
    },
    "CRBG": {
        "cusip": "21871X109", "first": "2026-03-17", "next": "2026-06-16",
        "public": "2026-02-09", "cash": 0.25,
        "issuer_url": "https://investors.corebridgefinancial.com/news/news-details/2026/Corebridge-Financial-Announces-Fourth-Quarter-and-Full-Year-2025-Results/default.aspx",
    },
}


if __name__ == "__main__":
    main(EVENTS, "WDC_CRBG")
