"""Consume next pre-event issuer cash evidence without changing candidates."""

from build_first_four_account_fields import main


EVENTS = {
    "PFE": {
        "cusip": "717081103", "first": "2026-01-23", "next": "2026-05-08",
        "public": "2025-12-12", "cash": 0.43,
        "issuer_url": "https://www.pfizer.com/news/press-release/press-release-detail/pfizer-declares-first-quarter-2026-dividend",
    },
    "CRS": {
        "cusip": "144285103", "first": "2026-01-27", "next": "2026-04-28",
        "public": "2026-01-16", "cash": 0.20,
        "issuer_url": "https://ir.carpentertechnology.com/news-events/news/news-details/2026/Carpenter-Technology-Declares-Quarterly-Cash-Dividend/default.aspx",
    },
}


if __name__ == "__main__":
    main(EVENTS, "PFE_CRS")
