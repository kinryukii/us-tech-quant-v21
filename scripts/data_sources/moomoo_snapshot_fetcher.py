"""Batched Moomoo market snapshot fetcher for current-state audit only."""

from __future__ import annotations

import time
from typing import Iterable

import pandas as pd

from scripts.data_sources.moomoo_client import MoomooQuoteClient


def batches(symbols: Iterable[str], batch_size: int = 400) -> list[list[str]]:
    if batch_size > 400:
        raise ValueError("Moomoo snapshot batch_size must be <=400")
    vals = list(symbols)
    return [vals[i:i + batch_size] for i in range(0, len(vals), batch_size)]


def fetch_snapshots(client: MoomooQuoteClient, moomoo_codes: Iterable[str], batch_size: int = 400, backoff_seconds: float = 0.2) -> pd.DataFrame:
    frames = []
    for index, batch in enumerate(batches(moomoo_codes, batch_size=batch_size)):
        payload = client.checked_call("get_market_snapshot", batch)
        frames.append(payload if isinstance(payload, pd.DataFrame) else pd.DataFrame(payload))
        if index < len(batches(moomoo_codes, batch_size=batch_size)) - 1 and backoff_seconds > 0:
            time.sleep(backoff_seconds)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
