import importlib.util
import os
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_196_r1_public_source_manual_csv_builder_and_validator.py"
RUNNER = ROOT / "scripts/v21/run_v21_196_r1_public_source_manual_csv_builder_and_validator.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_196_r1", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_symbol_mapping_for_normal_and_class_share_symbols():
    module = load_module()
    assert module.stooq_symbol("AAPL") == "aapl.us"
    assert module.stooq_symbol("QQQ") == "qqq.us"
    assert module.stooq_symbol("BRK.B") == "brk-b.us"
    assert module.stooq_symbol("BF.B") == "bf-b.us"


def test_valid_stooq_style_rows_normalize_into_required_schema():
    module = load_module()
    raw = pd.DataFrame([{
        "Date": "2026-06-29",
        "Open": "10.0",
        "High": "11.0",
        "Low": "9.0",
        "Close": "10.5",
        "Volume": "1000",
        "symbol": "AAPL",
    }])
    norm = module.normalize_provider_rows(raw, "STOOQ_DIRECT_DAILY_CSV", source_url="https://example.test")
    assert list(norm.columns) == module.AUDIT_COLS[:-1]
    assert norm.loc[0, "symbol"] == "AAPL"
    assert float(norm.loc[0, "close"]) == 10.5
    assert norm.loc[0, "source_provider"] == "STOOQ_DIRECT_DAILY_CSV"


def test_duplicate_same_provider_symbol_date_rows_are_rejected():
    module = load_module()
    rows = pd.DataFrame([
        {"symbol": "AAPL", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "STOOQ", "source_url": "", "source_file": "", "source_confidence": "PUBLIC"},
        {"symbol": "AAPL", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "STOOQ", "source_url": "", "source_file": "", "source_confidence": "PUBLIC"},
    ])
    valid, errors, _bad = module.validate_ohlcv_rows(rows, {"AAPL"})
    assert not errors
    candidate, audit, rejected = module.cross_validate(valid)
    assert candidate.empty
    assert rejected == 2
    assert audit[0]["status"] == "DUPLICATE_PROVIDER_SYMBOL_DATE_REJECTED"


def test_bad_ohlcv_rows_are_rejected():
    module = load_module()
    rows = pd.DataFrame([{"symbol": "AAPL", "date": "2026-06-29", "open": 10, "high": 8, "low": 9, "close": -1, "volume": -3}])
    valid, errors, rejected = module.validate_ohlcv_rows(rows, {"AAPL"})
    assert valid.empty
    assert len(rejected) == 1
    joined = "|".join(err["error"] for err in errors)
    assert "CLOSE_NON_POSITIVE" in joined
    assert "VOLUME_NEGATIVE" in joined


def test_coverage_below_080_does_not_validate():
    module = load_module()
    rows = pd.DataFrame([{"symbol": f"T{i:03d}", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000} for i in range(100)])
    coverage = module.coverage_rows(rows, 316)
    row = next(item for item in coverage if item["date"] == "2026-06-29")
    assert row["coverage_ratio"] < 0.80
    assert row["broad_eligible"] is False


def patch_paths(monkeypatch, module, tmp_path, candidate):
    out = tmp_path / "out"
    manual = tmp_path / "inputs/manual_price_sources"
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "MANUAL_DIR", manual)
    monkeypatch.setattr(module, "CANDIDATE_PATH", manual / "candidate_daily_ohlcv_20260629_20260630.csv")
    monkeypatch.setattr(module, "APPROVED_PATH", manual / "approved_daily_ohlcv_20260629_20260630.csv")
    module.write_candidate_files(candidate)
    return manual


def test_candidate_written_in_dry_mode_but_approved_path_not_written(tmp_path, monkeypatch):
    module = load_module()
    candidate = pd.DataFrame([{"symbol": "AAPL", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "TEST", "source_url": "", "source_file": "", "source_confidence": "TEST", "cross_validation_status": "SINGLE_SOURCE_ACCEPTED"}])
    manual = patch_paths(monkeypatch, module, tmp_path, candidate)
    monkeypatch.delenv(module.APPROVE_ENV, raising=False)
    audit = module.maybe_approve(candidate_valid=True)
    assert (manual / "candidate_daily_ohlcv_20260629_20260630.csv").is_file()
    assert not (manual / "approved_daily_ohlcv_20260629_20260630.csv").exists()
    assert audit["approved_write_requested"] is False


def test_approved_path_written_only_with_env_flag(tmp_path, monkeypatch):
    module = load_module()
    candidate = pd.DataFrame([{"symbol": "AAPL", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "TEST", "source_url": "", "source_file": "", "source_confidence": "TEST", "cross_validation_status": "SINGLE_SOURCE_ACCEPTED"}])
    manual = patch_paths(monkeypatch, module, tmp_path, candidate)
    monkeypatch.setenv(module.APPROVE_ENV, "TRUE")
    audit = module.maybe_approve(candidate_valid=True)
    assert audit["approved_write_requested"] is True
    assert audit["approved_write_succeeded"] is True
    assert (manual / "approved_daily_ohlcv_20260629_20260630.csv").is_file()


def test_cross_provider_conflict_is_rejected():
    module = load_module()
    rows = pd.DataFrame([
        {"symbol": "AAPL", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.0, "volume": 1000, "source_provider": "STOOQ", "source_url": "", "source_file": "", "source_confidence": "PUBLIC"},
        {"symbol": "AAPL", "date": "2026-06-29", "open": 12, "high": 13, "low": 11, "close": 12.0, "volume": 1000, "source_provider": "YAHOO", "source_url": "", "source_file": "", "source_confidence": "PUBLIC"},
    ])
    valid, errors, _bad = module.validate_ohlcv_rows(rows, {"AAPL"})
    assert not errors
    candidate, audit, rejected = module.cross_validate(valid)
    assert candidate.empty
    assert rejected == 2
    assert audit[0]["status"] == "CONFLICT_REJECTED"


def test_safety_flags_contract():
    assert SCRIPT.is_file()
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"official_adoption_allowed": False' in text
    assert '"broker_action_allowed": False' in text
    assert "protected_outputs_modified" in text
