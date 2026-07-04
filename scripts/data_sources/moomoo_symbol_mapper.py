"""Internal symbol to Moomoo quote-code mapping with audit rows."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

import pandas as pd


@dataclass
class SymbolMapping:
    internal_symbol: str
    moomoo_code: str
    market: str
    asset_type: str
    mapping_status: str
    mapping_error: str


ETF_HINTS = {
    "QQQ", "SPY", "IWM", "DIA", "VTI", "VOO", "XLK", "XLF", "XLE", "SMH", "SOXX", "TQQQ", "SQQQ"
}


def map_symbol(symbol: str) -> SymbolMapping:
    internal = str(symbol).upper().strip()
    if not internal:
        return SymbolMapping("", "", "", "", "FAIL", "EMPTY_SYMBOL")
    if any(ch.isspace() for ch in internal):
        return SymbolMapping(internal, "", "", "", "FAIL", "SYMBOL_CONTAINS_WHITESPACE")
    if internal.startswith("US."):
        base = internal[3:]
        return SymbolMapping(base, internal, "US", "ETF" if base in ETF_HINTS else "EQUITY", "PASS", "")
    if internal == "DRAM":
        return SymbolMapping("DRAM", "US.DRAM", "US", "EQUITY", "PASS", "")
    if "." in internal and internal not in {"BRK.B", "BF.B"}:
        return SymbolMapping(internal, "", "US", "UNKNOWN", "WARN", "DOT_SYMBOL_REQUIRES_REVIEW")
    return SymbolMapping(internal, f"US.{internal}", "US", "ETF" if internal in ETF_HINTS else "EQUITY", "PASS", "")


def map_symbols(symbols: Iterable[str], include_priority: bool = True) -> pd.DataFrame:
    ordered = []
    seen = set()
    for sym in list(symbols) + (["DRAM"] if include_priority else []):
        key = str(sym).upper().strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(sym)
    return pd.DataFrame([asdict(map_symbol(sym)) for sym in ordered])


def failed_or_warning_rows(audit: pd.DataFrame) -> pd.DataFrame:
    if audit.empty or "mapping_status" not in audit:
        return pd.DataFrame()
    return audit[audit["mapping_status"].astype(str).str.upper().isin(["FAIL", "WARN"])].copy()
