from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import abcde_a2_r4x_hive_20230712_execution_price_recovery as r4x


def _metadata() -> dict[str, object]:
    return {
        "ktype": "KLType.K_DAY", "autype": "AuType.QFQ", "host": "127.0.0.1",
        "port": 18441, "request_count": 1, "requested_at_utc": "2026-08-16T00:00:00+00:00",
        "completed_at_utc": "2026-08-16T00:00:01+00:00", "raw_columns": [],
    }


def _frame(include_target: bool = True, valid: bool = True) -> pd.DataFrame:
    dates = ["2023-07-10", "2023-07-11", "2023-07-13", "2023-07-14"]
    if include_target:
        dates.insert(2, r4x.TARGET_DATE)
    rows = []
    for index, date in enumerate(dates):
        opening = 5.0 + index / 10
        rows.append({
            "date": date, "open": opening, "high": opening + 0.3,
            "low": opening - 0.2, "close": opening + 0.1,
            "volume": 1000.0, "turnover": np.nan, "last_close": opening - 0.1,
            "change_rate": np.nan,
        })
    result = pd.DataFrame(rows)
    if include_target and not valid:
        result.loc[result.date == r4x.TARGET_DATE, "high"] = 1.0
    return result


def test_evidence_parse_is_deterministic_and_strict_json() -> None:
    first = r4x.parse_evidence(_frame(), _metadata())
    second = r4x.parse_evidence(_frame(), _metadata())
    assert first["target_row_count"] == 1
    assert first["target_bar_valid"] is True
    assert first["evidence_fingerprint"] == second["evidence_fingerprint"]
    payload = r4x.canonical_payload(first)
    assert b"NaN" not in payload
    json.loads(payload)


def test_no_bar_and_invalid_bar_are_not_recoverable() -> None:
    absent = r4x.parse_evidence(_frame(include_target=False), _metadata())
    invalid = r4x.parse_evidence(_frame(valid=False), _metadata())
    assert absent["target_row_count"] == 0
    assert absent["target_bar_valid"] is False
    assert invalid["target_row_count"] == 1
    assert invalid["target_bar_valid"] is False


def test_candidate_adds_only_target_row(monkeypatch, tmp_path: Path) -> None:
    canonical = pd.DataFrame([
        {
            "ticker": "HIVE", "trade_date": "2023-07-11", "open": 5.0, "high": 5.2,
            "low": 4.8, "close": 5.1, "volume": 1000.0, "turnover": 5000.0,
            "change_rate": 1.0, "last_close": 4.9, "autype": "qfq",
            "source": "MOOMOO_OPEND", "fetch_timestamp": "2026-01-01T00:00:00+00:00",
            "request_start": "2023-01-01", "request_end": "2023-12-31", "opend_version": None,
        },
        {
            "ticker": "QQQ", "trade_date": "2023-07-12", "open": 370.0, "high": 372.0,
            "low": 369.0, "close": 371.0, "volume": 2000.0, "turnover": 740000.0,
            "change_rate": 0.2, "last_close": 369.5, "autype": "qfq",
            "source": "MOOMOO_OPEND", "fetch_timestamp": "2026-01-01T00:00:00+00:00",
            "request_start": "2023-01-01", "request_end": "2023-12-31", "opend_version": None,
        },
    ])
    schema = pa.schema([
        pa.field("ticker", pa.large_string()), pa.field("trade_date", pa.large_string()),
        *[pa.field(name, pa.float64()) for name in ("open", "high", "low", "close", "volume", "turnover", "change_rate", "last_close")],
        *[pa.field(name, pa.large_string()) for name in ("autype", "source", "fetch_timestamp", "request_start", "request_end")],
        pa.field("opend_version", pa.null()),
    ])
    path = tmp_path / "prices.parquet"
    pq.write_table(pa.Table.from_pandas(canonical, schema=schema, preserve_index=False), path)
    monkeypatch.setattr(r4x, "CANONICAL_PATH", path)
    evidence = r4x.parse_evidence(_frame(), _metadata())
    before = r4x.canonical_before_audit()
    candidate, audit = r4x.build_repair_candidate(evidence, before)
    assert len(candidate) == len(canonical) + 1
    target = candidate.loc[(candidate.ticker == "HIVE") & (candidate.trade_date == r4x.TARGET_DATE)]
    assert len(target) == 1
    assert float(target.iloc[0].open) == float(evidence["rows"][2]["open"])
    assert audit["non_target_rows_semantic_identity_status"] == "PASS"


def test_scope_has_no_model_target_outcome_or_broker_paths() -> None:
    source = Path(r4x.__file__).read_text(encoding="utf-8")
    forbidden = (".fit(", ".predict(", "TradeContext", "unlock_trade", "place_order")
    assert not any(token in source for token in forbidden)
    assert r4x.START_DATE == "2023-07-10"
    assert r4x.END_DATE == "2023-07-14"
    assert r4x.TARGET_DATE == "2023-07-12"


def test_authoritative_gap_and_r4_contract_are_unchanged() -> None:
    before = r4x.canonical_before_audit()
    assert before["hive_20230712_row_count_before"] in {0, 1}
    assert r4x.sha256_file(r4x.R4_CONTRACT_PATH) == r4x.EXPECTED_R4_CONTRACT_SHA256


def test_written_artifacts_preserve_fail_closed_scope_if_present() -> None:
    if not r4x.SUMMARY_PATH.is_file():
        return
    summary = json.loads(r4x.SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["SOURCE_POLICY"] == "MOOMOO_ONLY"
    assert summary["MODEL_FIT_COUNT"] == 0
    assert summary["MODEL_PREDICT_CALL_COUNT"] == 0
    assert summary["TARGET_VALUE_READ_COUNT"] == 0
    assert summary["OUTCOME_READ_COUNT"] == 0
    assert summary["BROKER_ACTION_COUNT"] == 0
    assert summary["RUN1_FINGERPRINT"] == summary["RUN2_FINGERPRINT"]
    assert summary["NEXT_AUTHORIZED_STEP"] in {
        "EXACT_RERUN_ABCDE_A2_R4_UNDER_EXISTING_FROZEN_CONTRACT",
        "FREEZE_SECURITY_UNAVAILABLE_EXECUTION_POLICY",
        "STOP_UNRESOLVED_EXECUTION_PRICE_EVIDENCE",
    }
