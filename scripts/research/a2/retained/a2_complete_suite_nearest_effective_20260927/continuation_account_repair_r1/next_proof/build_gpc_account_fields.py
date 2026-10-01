"""Consume GPC first cash event for frozen account fields."""

from build_first_four_account_fields import main


EVENTS = {
    "GPC": {
        "cusip": "372460105", "first": "2026-03-06", "next": "2026-06-05",
        "public": "2026-02-17", "cash": 1.0625,
        "issuer_url": "https://www.genpt.com/2026-02-17-Genuine-Parts-Company-Reports-Fourth-Quarter-and-Full-Year-2025-Results",
    },
}


if __name__ == "__main__":
    main(EVENTS, "GPC")
