from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

import a2_free_pit_foundation_r1 as runner


def test_contracts_are_single_fixed_and_temporally_strict() -> None:
    contracts = runner.contracts()
    assert contracts["sic"]["conservative_dissemination_lag_minutes"] == 5
    assert "FILING_DATE_AS_AVAILABILITY" in contracts["sic"]["forbidden"]
    assert contracts["estimator"]["maximum_trailing_sessions"] == 252
    assert contracts["estimator"]["minimum_valid_observations"] == 180
    assert contracts["estimator"]["window_search_count"] == 0
    assert contracts["factor"]["factor_subset_search_count"] == 0


def test_next_legal_session_never_uses_same_date_or_future_backfill() -> None:
    dates = pd.to_datetime(["2023-01-03", "2023-01-04", "2023-01-06"])
    accepted = pd.Series(pd.to_datetime(["2023-01-03 10:00:00Z", "2023-01-04 23:59:00Z", "2023-01-06 12:00:00Z"], utc=True))
    actual = runner._next_legal_session(accepted, dates)
    assert actual.iloc[0] == pd.Timestamp("2023-01-04")
    assert actual.iloc[1] == pd.Timestamp("2023-01-06")
    assert pd.isna(actual.iloc[2])


def test_next_legal_session_uses_new_york_calendar_not_utc_date() -> None:
    dates = pd.to_datetime(["2025-05-15", "2025-05-16"])
    # 01:00 UTC is still the prior calendar date in New York.  The next legal
    # session is therefore May 15, not May 16.
    accepted = pd.Series(pd.to_datetime(["2025-05-15 01:00:00Z"], utc=True))
    actual = runner._next_legal_session(accepted, dates)
    assert actual.iloc[0] == pd.Timestamp("2025-05-15")


def test_canonical_identity_key_is_not_cik_or_ticker() -> None:
    assert runner.identity_name_key("MICROSOFT CORP.") == runner.identity_name_key("Microsoft Corporation")
    assert runner.identity_name_key("ALPHA HOLDINGS") != runner.identity_name_key("ALPHA")
    assert runner.IDENTITY_INTERVALS != runner.SEC_SUB


def test_file_level_firewall_explicitly_denies_mixed_sources() -> None:
    manifest = runner.source_temporal_manifest()
    denied = [row for row in manifest["sources"] if row["classification"].startswith("DENYLISTED") or row["classification"].startswith("UNKNOWN")]
    assert denied
    assert all(row["open_policy"] == "DO_NOT_OPEN" for row in denied)
    assert all(value == 0 for value in manifest["zero_read_counters"].values())


def test_sec_header_parser_validates_as_filed_fields() -> None:
    path = runner.PROVIDER_CACHE / "sec_headers" / "0001770787-21-000009.hdr.sgml"
    if not path.is_file():
        return
    parsed = runner._parse_sec_header(path)
    assert int(parsed["header_cik"]) == 1770787
    assert int(parsed["header_sic"]) == 3826
    assert parsed["header_form"] == "10-K"
    assert runner.identity_name_key("10X Genomics Inc") in parsed["header_name_keys"]


def test_ff_official_mappings_are_deterministic_when_acquired() -> None:
    root = runner.PROVIDER_CACHE / "kenneth_french"
    ff12_path = root / "ff12_mapping.parquet"
    ff48_path = root / "ff48_mapping.parquet"
    if not ff12_path.is_file() or not ff48_path.is_file():
        return
    ff12 = pd.read_parquet(ff12_path).set_index("sic4").industry_code
    ff48 = pd.read_parquet(ff48_path).set_index("sic4").industry_code
    assert int(ff12.loc[3571]) == 6
    assert int(ff48.loc[3571]) == 35
    assert int(ff48.loc[7372]) == 34
    assert int(ff48.loc[7373]) == 35
    assert int(ff48.loc[6020]) == 44
    assert int(ff48.loc[4950]) == 48
    assert 3990 not in ff48.index


def test_row_hash_is_deterministic_and_missing_sensitive() -> None:
    frame = pd.DataFrame({"date": pd.to_datetime(["2023-01-03"]), "id": ["A"], "value": [np.nan]})
    first = runner.row_sha256(frame, ["date", "id", "value"]).iloc[0]
    second = runner.row_sha256(frame.copy(), ["date", "id", "value"]).iloc[0]
    assert first == second and len(first) == 64
    assert first != hashlib.sha256(b"").hexdigest()


def test_rv_contract_is_frozen() -> None:
    assert runner.sha256_file(runner.RV_CONTRACT) == runner.EXPECTED_HASHES[runner.RV_CONTRACT]


def test_registry_candidate_fingerprints_are_valid_and_distinct() -> None:
    triplets = []
    for _, spec, info, mechanism, _ in runner.REGISTRY_CANDIDATES:
        assert all(len(value) == 64 and int(value, 16) >= 0 for value in (spec, info, mechanism))
        triplets.append((spec, info, mechanism))
    assert len(set(triplets)) == len(triplets)


def test_trailing_market_matrices_shift_same_day_information() -> None:
    dates = pd.date_range("2023-01-02", periods=70, freq="B")
    qfq = pd.DataFrame({"ticker": "X", "trade_date": dates, "close": np.arange(1, 71, dtype=float), "turnover": 1.0})
    raw = pd.DataFrame({"ticker": "X", "trade_date": dates, "close": np.arange(1, 71, dtype=float), "turnover": np.arange(1, 71, dtype=float)})
    matrices = runner.trailing_market_matrices(qfq, raw)
    assert matrices["adv20"].loc[dates[20], "X"] == np.mean(np.arange(1, 21, dtype=float))
    assert matrices["adv60"].loc[dates[60], "X"] == np.mean(np.arange(1, 61, dtype=float))


def test_moomoo_fetch_contract_forbids_duplicate_and_post2025() -> None:
    contract = runner.contracts()["fetch"]
    assert contract["duplicate_fetch_allowed"] is False
    assert contract["request_end"] == "2025-12-31"
    assert contract["current_industry_use"] == "FORBIDDEN"
