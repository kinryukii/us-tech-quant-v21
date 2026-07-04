import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_196_r3_moomoo_daily_bar_fetcher_and_approved_csv_builder.py"
RUNNER = ROOT / "scripts/v21/run_v21_196_r3_moomoo_daily_bar_fetcher_and_approved_csv_builder.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_196_r3", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_symbol_to_moomoo_us_symbol_mapping():
    module = load_module()
    assert module.moomoo_code_candidates("AAPL")[0] == "US.AAPL"
    assert module.moomoo_code_candidates("QQQ")[0] == "US.QQQ"


def test_class_share_fallback_mapping():
    module = load_module()
    assert module.moomoo_code_candidates("BRK.B") == ["US.BRK.B", "US.BRK-B"]
    assert module.moomoo_code_candidates("BF.B") == ["US.BF.B", "US.BF-B"]
    lookup = module.canonical_symbol_lookup(["BRK.B", "BF.B"])
    assert module.normalize_symbol("US.BRK-B", lookup) == "BRK.B"
    assert module.normalize_symbol("US.BF-B", lookup) == "BF.B"


def test_moomoo_raw_export_column_normalization(tmp_path):
    module = load_module()
    lookup = module.canonical_symbol_lookup(["AAPL"])
    path = tmp_path / "raw_moomoo_ohlcv_20260629.csv"
    raw = pd.DataFrame([{"Code": "US.AAPL", "Trading Date": "2026/06/29", "Open": 10, "High": 11, "Low": 9, "Last Price": 10.5, "Vol.": 1000}])
    normalized, errors = module.normalize_raw_export(raw, path, lookup)
    assert not errors
    assert normalized.loc[0, "symbol"] == "AAPL"
    assert normalized.loc[0, "date"] == "2026-06-29"
    assert normalized.loc[0, "source_provider"] == "MOOMOO_RAW_EXPORT"


def test_japanese_chinese_column_aliases(tmp_path):
    module = load_module()
    lookup = module.canonical_symbol_lookup(["AAPL"])
    path = tmp_path / "raw_moomoo_ohlcv_20260630.csv"
    raw = pd.DataFrame([{"銘柄コード": "AAPL.US", "日付": "2026/06/30", "始値": 10, "高値": 11, "安値": 9, "終値": 10.5, "出来高": 1000}])
    normalized, errors = module.normalize_raw_export(raw, path, lookup)
    assert not errors
    assert normalized.loc[0, "symbol"] == "AAPL"
    assert normalized.loc[0, "date"] == "2026-06-30"


def test_bad_ohlcv_rows_rejected():
    module = load_module()
    frame = pd.DataFrame([{"symbol": "AAPL", "date": "2026-06-29", "open": 10, "high": 8, "low": 9, "close": -1, "volume": -2, "source_provider": "MOOMOO_RAW_EXPORT", "source_file": "", "moomoo_code": "US.AAPL", "autype": "EXPORT", "cross_validation_status": ""}])
    valid, errors, rejected = module.validate_rows(frame, {"AAPL"})
    assert valid.empty
    assert len(rejected) == 1
    joined = "|".join(row["error"] for row in errors)
    assert "CLOSE_NON_POSITIVE" in joined
    assert "VOLUME_NEGATIVE" in joined


def test_api_normalization_allows_overlap_calibration_date():
    module = load_module()
    raw = pd.DataFrame([{"time_key": module.OVERLAP_DATE, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000}])
    normalized = module.normalize_api_rows(raw, "QQQ", "US.QQQ", "NONE", [module.OVERLAP_DATE])
    assert not normalized.empty
    assert normalized.loc[0, "date"] == module.OVERLAP_DATE


def test_duplicate_symbol_date_rows_rejected():
    module = load_module()
    row = {"symbol": "AAPL", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "MOOMOO_RAW_EXPORT", "source_file": "", "moomoo_code": "US.AAPL", "autype": "EXPORT", "cross_validation_status": ""}
    frame = pd.DataFrame([row, row])
    valid, errors, rejected = module.validate_rows(frame, {"AAPL"})
    assert valid.empty
    assert len(rejected) == 2
    assert any("DUPLICATE_SYMBOL_DATE" in row["error"] for row in errors)


def test_coverage_below_080_fails():
    module = load_module()
    frame = pd.DataFrame([{"symbol": f"T{i:03d}", "date": "2026-06-29"} for i in range(100)])
    coverage = module.coverage_rows(frame, 316)
    row = next(item for item in coverage if item["date"] == "2026-06-29")
    assert row["coverage_ratio"] < 0.80
    assert row["broad_eligible"] is False


def test_candidate_valid_when_coverage_and_ohlcv_valid():
    module = load_module()
    rows = []
    for date in module.TARGET_DATES:
        for i in range(316):
            rows.append({"symbol": f"T{i:03d}", "date": date, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "MOOMOO_RAW_EXPORT", "source_file": "", "moomoo_code": f"US.T{i:03d}", "autype": "EXPORT", "cross_validation_status": ""})
    frame = pd.DataFrame(rows)
    valid, errors, rejected = module.validate_rows(frame, {f"T{i:03d}" for i in range(316)})
    coverage = module.coverage_rows(valid, 316)
    assert not errors
    assert rejected.empty
    assert all(row["coverage_ratio"] >= 0.80 for row in coverage)


def test_approved_csv_written_only_with_env_flag(tmp_path, monkeypatch):
    module = load_module()
    candidate = tmp_path / "candidate.csv"
    approved = tmp_path / "approved.csv"
    pd.DataFrame([{"symbol": "AAPL", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000}]).to_csv(candidate, index=False)
    monkeypatch.setattr(module, "APPROVED_PATH", approved)
    monkeypatch.delenv(module.APPROVE_ENV, raising=False)
    dry = module.approve_candidate(candidate, True)
    assert dry["approved_write_requested"] is False
    assert not approved.exists()
    monkeypatch.setenv(module.APPROVE_ENV, "TRUE")
    applied = module.approve_candidate(candidate, True)
    assert applied["approved_write_succeeded"] is True
    assert approved.is_file()


def test_loads_r4c_readiness_summary(tmp_path):
    module = load_module()
    path = tmp_path / "v21_196_r4a_summary.json"
    path.write_text('{"r3_ready_to_rerun": true, "dedicated_python_executable": "py312"}', encoding="utf-8")
    loaded = module.load_r4_readiness(path)
    assert loaded["r4_readiness_loaded"] is True
    assert loaded["r4_ready_to_rerun"] is True
    assert loaded["dedicated_python_executable"] == "py312"


def test_dedicated_env_override_works(monkeypatch):
    module = load_module()
    monkeypatch.setenv(module.DEDICATED_PYTHON_ENV, "D:/custom/python.exe")
    assert module.dedicated_python_from_readiness({"dedicated_python_executable": "ignored"}) == "D:/custom/python.exe"


def test_missing_r4_readiness_wait_decision(tmp_path):
    module = load_module()
    loaded = module.load_r4_readiness(tmp_path / "missing.json")
    assert loaded["r4_readiness_loaded"] is False
    assert loaded["r4_ready_to_rerun"] is False


def test_dedicated_import_failure_classification_inputs(tmp_path):
    module = load_module()
    missing = tmp_path / "missing_python.exe"
    audit = module.verify_dedicated_moomoo_import(str(missing))
    assert audit["dedicated_python_import_succeeded"] is False
    assert "DEDICATED_PYTHON_NOT_FOUND" in audit["stderr_tail"]


def test_subprocess_timeout_classified_safely(tmp_path, monkeypatch):
    module = load_module()

    def fake_run_command(*_args, **_kwargs):
        import subprocess
        raise subprocess.TimeoutExpired(["python"], 30)

    monkeypatch.setattr(module, "run_command", fake_run_command)
    panel = pd.DataFrame({"symbol": ["QQQ"], "date": [module.OVERLAP_DATE], "close": [100.0]})
    result = module.run_dedicated_api_fetch(str(tmp_path / "python.exe"), ["QQQ"], panel, "127.0.0.1", 11111, timeout=30)
    audit = result[-1]
    assert audit["moomoo_api_fetch_subprocess_attempted"] is True
    assert audit["moomoo_api_fetch_subprocess_timeout"] is True
    assert audit["moomoo_api_fetch_subprocess_succeeded"] is False


def test_candidate_valid_path_does_not_require_main_python_moomoo_import(tmp_path, monkeypatch):
    module = load_module()
    canonical = tmp_path / "canonical.csv"
    rows = []
    for i in range(10):
        rows.append({"symbol": f"T{i:03d}", "date": module.OVERLAP_DATE, "open": 10, "high": 11, "low": 9, "close": 10.0, "volume": 1000})
    pd.DataFrame(rows).to_csv(canonical, index=False)
    monkeypatch.setattr(module, "CANONICAL", canonical)
    monkeypatch.setattr(module, "OUT", tmp_path / "out")
    monkeypatch.setattr(module, "MANUAL_DIR", tmp_path / "manual")
    monkeypatch.setattr(module, "APPROVED_PATH", tmp_path / "manual/approved.csv")
    monkeypatch.setattr(module, "MIN_COVERAGE_RATIO", 0.80)
    monkeypatch.setattr(module, "git_status", lambda: [])
    monkeypatch.setattr(module, "protected_modified", lambda *_args: False)
    monkeypatch.setattr(module, "load_r4_readiness", lambda: {"r4_readiness_loaded": True, "r4_ready_to_rerun": True, "dedicated_python_executable": "py312"})
    monkeypatch.setattr(module, "import_moomoo_package", lambda: (None, {"moomoo_package_available": False, "import_error": "missing", "install_guidance": ""}))
    monkeypatch.setattr(module, "verify_dedicated_moomoo_import", lambda _py: {"dedicated_python_executable": "py312", "dedicated_python_import_succeeded": True})

    def fake_fetch(_py, symbols, _panel, _host, _port):
        api = []
        for sym in symbols:
            for date in module.TARGET_DATES:
                api.append({"symbol": sym, "date": date, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "MOOMOO_OPEND_API", "source_file": "", "moomoo_code": f"US.{sym}", "autype": "NONE", "cross_validation_status": ""})
        return (
            pd.DataFrame(api),
            [{"symbol": sym, "moomoo_code": f"US.{sym}", "status": "SUCCESS", "error": ""} for sym in symbols],
            [],
            [{"symbol": "QQQ", "status": "SUCCESS", "detail": ""}],
            [{"autype": "NONE", "symbol": "__MEDIAN__", "median_abs_pct_diff": 0.0}],
            {"host": "127.0.0.1", "port": 11111, "connection_success": True, "error": "", "selected_autype": "NONE", "autype_calibration_passed": True},
            {"moomoo_api_fetch_subprocess_attempted": True, "moomoo_api_fetch_subprocess_succeeded": True, "moomoo_api_fetch_subprocess_timeout": False, "moomoo_api_fetch_subprocess_returncode": 0, "moomoo_api_fetch_stdout_tail": "", "moomoo_api_fetch_stderr_tail": ""},
        )

    monkeypatch.setattr(module, "run_dedicated_api_fetch", fake_fetch)
    summary = module.run()
    assert summary["main_python_moomoo_importable"] is False
    assert summary["dedicated_moomoo_python_used"] is True
    assert summary["candidate_valid"] is True
    assert summary["final_status"] == "PARTIAL_PASS_V21_196_R3_MOOMOO_CANDIDATE_READY_NOT_APPROVED"


def test_candidate_valid_takes_precedence_over_late_subprocess_timeout(tmp_path, monkeypatch):
    module = load_module()
    canonical = tmp_path / "canonical.csv"
    pd.DataFrame([{"symbol": "AAPL", "date": module.OVERLAP_DATE, "open": 10, "high": 11, "low": 9, "close": 10.0, "volume": 1000}]).to_csv(canonical, index=False)
    monkeypatch.setattr(module, "CANONICAL", canonical)
    monkeypatch.setattr(module, "OUT", tmp_path / "out")
    monkeypatch.setattr(module, "MANUAL_DIR", tmp_path / "manual")
    monkeypatch.setattr(module, "APPROVED_PATH", tmp_path / "manual/approved.csv")
    monkeypatch.setattr(module, "MIN_COVERAGE_RATIO", 0.80)
    monkeypatch.setattr(module, "git_status", lambda: [])
    monkeypatch.setattr(module, "protected_modified", lambda *_args: False)
    monkeypatch.setattr(module, "load_r4_readiness", lambda: {"r4_readiness_loaded": True, "r4_ready_to_rerun": True, "dedicated_python_executable": "py312"})
    monkeypatch.setattr(module, "import_moomoo_package", lambda: (None, {"moomoo_package_available": False, "import_error": "missing", "install_guidance": ""}))
    monkeypatch.setattr(module, "verify_dedicated_moomoo_import", lambda _py: {"dedicated_python_executable": "py312", "dedicated_python_import_succeeded": True})
    api = pd.DataFrame([
        {"symbol": "AAPL", "date": date, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "MOOMOO_OPEND_API", "source_file": "", "moomoo_code": "US.AAPL", "autype": "NONE", "cross_validation_status": ""}
        for date in module.TARGET_DATES
    ])
    monkeypatch.setattr(module, "run_dedicated_api_fetch", lambda *_args: (
        api,
        [],
        [],
        [],
        [],
        {"host": "127.0.0.1", "port": 11111, "connection_success": True, "error": "", "selected_autype": "NONE", "autype_calibration_passed": True},
        {"moomoo_api_fetch_subprocess_attempted": True, "moomoo_api_fetch_subprocess_succeeded": False, "moomoo_api_fetch_subprocess_timeout": True, "moomoo_api_fetch_subprocess_returncode": None, "moomoo_api_fetch_stdout_tail": "", "moomoo_api_fetch_stderr_tail": ""},
    ))
    summary = module.run()
    assert summary["candidate_valid"] is True
    assert summary["moomoo_api_fetch_subprocess_timeout"] is True
    assert summary["final_status"] == "PARTIAL_PASS_V21_196_R3_MOOMOO_CANDIDATE_READY_NOT_APPROVED"


def test_dry_mode_does_not_mutate_canonical(tmp_path, monkeypatch):
    module = load_module()
    canonical = tmp_path / "canonical.csv"
    pd.DataFrame({"symbol": ["AAPL"], "date": ["2026-06-26"], "close": [10.0]}).to_csv(canonical, index=False)
    monkeypatch.setattr(module, "CANONICAL", canonical)
    monkeypatch.setattr(module, "OUT", tmp_path / "out")
    monkeypatch.setattr(module, "MANUAL_DIR", tmp_path / "inputs")
    monkeypatch.setattr(module, "APPROVED_PATH", tmp_path / "inputs/approved.csv")
    monkeypatch.setattr(module, "git_status", lambda: [])
    monkeypatch.setattr(module, "protected_modified", lambda *_args: False)
    monkeypatch.setattr(module, "load_r4_readiness", lambda: {"r4_readiness_loaded": False, "r4_ready_to_rerun": False})
    before = canonical.read_text(encoding="utf-8")
    module.run()
    assert canonical.read_text(encoding="utf-8") == before


def test_no_trade_context_imported_or_used():
    text = SCRIPT.read_text(encoding="utf-8")
    banned = ["OpenSecTradeContext", "OpenFutureTradeContext", "unlock_trade", "place_order", "modify_order", "cancel_order"]
    for item in banned:
        assert item not in text


def test_safety_flags_contract():
    assert SCRIPT.is_file()
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"official_adoption_allowed": False' in text
    assert '"broker_action_allowed": False' in text
    assert "protected_outputs_modified" in text
