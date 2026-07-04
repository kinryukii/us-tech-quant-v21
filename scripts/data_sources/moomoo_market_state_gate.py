"""Market-state gate for daily Moomoo canonical imports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from scripts.data_sources.moomoo_client import MoomooQuoteClient


CLOSED_STATES = {"CLOSED", "REST", "AFTER_HOURS_END", "MORNING", "NONE", "CLOSE"}


def market_state_gate(client: MoomooQuoteClient, priority_codes: Iterable[str] = ("US.DRAM", "US.QQQ", "US.AAPL")) -> pd.DataFrame:
    codes = list(priority_codes)
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        payload = client.checked_call("get_market_state", codes)
        frame = payload if isinstance(payload, pd.DataFrame) else pd.DataFrame(payload)
        if frame.empty:
            return pd.DataFrame([{"moomoo_code": "|".join(codes), "market_state": "", "decision": "BLOCK", "timestamp": timestamp, "reason": "EMPTY_MARKET_STATE"}])
        frame = frame.rename(columns={c: str(c).lower() for c in frame.columns})
        code_col = "code" if "code" in frame else frame.columns[0]
        state_col = "market_state" if "market_state" in frame else frame.columns[-1]
        rows = []
        for _, row in frame.iterrows():
            state = str(row.get(state_col, "")).upper()
            closed = any(token in state for token in CLOSED_STATES) and "OPEN" not in state
            rows.append({
                "moomoo_code": str(row.get(code_col, "")),
                "market_state": state,
                "decision": "ALLOW_DAILY_IMPORT" if closed else "BLOCK_REGULAR_SESSION_OPEN",
                "timestamp": timestamp,
                "reason": "US regular session appears closed" if closed else "US regular session may be open; do not infer completed daily bar from system clock",
            })
        return pd.DataFrame(rows)
    except Exception as exc:
        return pd.DataFrame([{"moomoo_code": "|".join(codes), "market_state": "", "decision": "BLOCK", "timestamp": timestamp, "reason": str(exc)}])


def import_allowed(audit: pd.DataFrame) -> bool:
    return bool(not audit.empty and audit["decision"].astype(str).eq("ALLOW_DAILY_IMPORT").any())
