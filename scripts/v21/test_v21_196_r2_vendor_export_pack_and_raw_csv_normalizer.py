import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.py"
RUNNER = ROOT / "scripts/v21/run_v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.ps1"
OUT = ROOT / "outputs/v21/V21.196_R2_VENDOR_EXPORT_PACK_AND_RAW_CSV_NORMALIZER"
SUMMARY = OUT / "v21_196_r2_summary.json"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_196_r2", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_df(count=316):
    return pd.DataFrame({"symbol": [f"T{i:03d}" for i in range(count)] + ["BRK.B", "BF.B"]})


def patch_paths(monkeypatch, module, tmp_path, count=316):
    manual = tmp_path / "inputs/manual_price_sources"
    out = tmp_path / "out"
    canonical = tmp_path / "canonical.csv"
    canonical_df(count).to_csv(canonical, index=False)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "MANUAL_DIR", manual)
    monkeypatch.setattr(module, "CANONICAL", canonical)
    monkeypatch.setattr(module, "APPROVED_PATH", manual / "approved_daily_ohlcv_20260629_20260630.csv")
    monkeypatch.setattr(module, "git_status", lambda: [])
    monkeypatch.setattr(module, "protected_modified", lambda *_args: False)
    return manual, out, canonical


def raw_rows(symbols, date="2026-06-29"):
    return pd.DataFrame([{
        "Symbol": sym,
        "Date": date,
        "Open": 10.0,
        "High": 11.0,
        "Low": 9.0,
        "Close": 10.5,
        "Volume": 1000,
    } for sym in symbols])


def test_export_pack_created_from_canonical_universe(tmp_path, monkeypatch):
    module = load_module()
    manual, out, _canonical = patch_paths(monkeypatch, module, tmp_path)
    symbols = module.canonical_symbols()
    symbol_path, template_path = module.create_export_pack(symbols)
    assert symbol_path.is_file()
    assert template_path.is_file()
    assert (out / "vendor_export_instructions.txt").is_file()
    exported = pd.read_csv(symbol_path)
    assert "canonical_symbol" in exported.columns
    assert len(exported) == len(symbols)


def test_moomoo_style_columns_normalize_correctly(tmp_path, monkeypatch):
    module = load_module()
    manual, _out, _canonical = patch_paths(monkeypatch, module, tmp_path)
    lookup = module.canonical_symbol_lookup(["T000"])
    path = manual / "raw_moomoo_ohlcv_20260629.csv"
    raw = pd.DataFrame([{"Code": "US.T000", "Trading Date": "2026/06/29", "Open": 10, "High": 11, "Low": 9, "Last Price": 10.5, "Turnover Volume": 1000}])
    normalized, errors = module.normalize_vendor_frame(raw, path, lookup)
    assert not errors
    assert normalized.loc[0, "symbol"] == "T000"
    assert normalized.loc[0, "date"] == "2026-06-29"
    assert normalized.loc[0, "source_provider"] == "LOCAL_VENDOR_MOOMOO"


def test_tradingview_style_columns_normalize_correctly(tmp_path, monkeypatch):
    module = load_module()
    manual, _out, _canonical = patch_paths(monkeypatch, module, tmp_path)
    lookup = module.canonical_symbol_lookup(["T000"])
    path = manual / "raw_tradingview_ohlcv_20260630.csv"
    raw = pd.DataFrame([{"Ticker": "NASDAQ:T000", "time": "2026-06-30", "open": 10, "high": 11, "low": 9, "close": 10.5, "VOL": 1000}])
    normalized, errors = module.normalize_vendor_frame(raw, path, lookup)
    assert not errors
    assert normalized.loc[0, "symbol"] == "T000"
    assert normalized.loc[0, "date"] == "2026-06-30"
    assert normalized.loc[0, "source_provider"] == "LOCAL_VENDOR_TRADINGVIEW"


def test_japanese_chinese_aliases_normalize_correctly(tmp_path, monkeypatch):
    module = load_module()
    manual, _out, _canonical = patch_paths(monkeypatch, module, tmp_path)
    lookup = module.canonical_symbol_lookup(["T000"])
    path = manual / "raw_vendor_ohlcv_20260629.csv"
    raw = pd.DataFrame([{"銘柄コード": "T000.US", "日付": "2026/06/29", "始値": 10, "高値": 11, "安値": 9, "終値": 10.5, "出来高": 1000}])
    normalized, errors = module.normalize_vendor_frame(raw, path, lookup)
    assert not errors
    assert normalized.loc[0, "symbol"] == "T000"
    assert normalized.loc[0, "date"] == "2026-06-29"


def test_exchange_prefix_suffix_and_class_share_mapping():
    module = load_module()
    lookup = module.canonical_symbol_lookup(["AAPL", "BRK.B", "BF.B"])
    assert module.normalize_symbol("NASDAQ:AAPL", lookup) == "AAPL"
    assert module.normalize_symbol("US.AAPL", lookup) == "AAPL"
    assert module.normalize_symbol("AAPL.US", lookup) == "AAPL"
    assert module.normalize_symbol("BRK-B", lookup) == "BRK.B"
    assert module.normalize_symbol("BF-B", lookup) == "BF.B"


def test_duplicate_symbol_date_rows_are_rejected():
    module = load_module()
    frame = pd.DataFrame([
        {"symbol": "T000", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "X", "source_file": "a"},
        {"symbol": "T000", "date": "2026-06-29", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "source_provider": "X", "source_file": "a"},
    ])
    valid, errors, rejected = module.validate_rows(frame, {"T000"})
    assert valid.empty
    assert len(rejected) == 2
    assert any("DUPLICATE_SYMBOL_DATE" in row["error"] for row in errors)


def test_bad_ohlcv_rows_are_rejected():
    module = load_module()
    frame = pd.DataFrame([{"symbol": "T000", "date": "2026-06-29", "open": 10, "high": 8, "low": 9, "close": -1, "volume": -2, "source_provider": "X", "source_file": "a"}])
    valid, errors, rejected = module.validate_rows(frame, {"T000"})
    assert valid.empty
    assert len(rejected) == 1
    joined = "|".join(row["error"] for row in errors)
    assert "CLOSE_NON_POSITIVE" in joined
    assert "VOLUME_NEGATIVE" in joined


def test_coverage_below_080_fails_candidate_validation():
    module = load_module()
    frame = raw_rows([f"T{i:03d}" for i in range(100)])
    coverage = module.coverage_rows(frame.rename(columns={"Symbol": "symbol", "Date": "date"}), 316)
    row = next(item for item in coverage if item["date"] == "2026-06-29")
    assert row["coverage_ratio"] < 0.80
    assert row["broad_eligible"] is False


def test_approved_csv_written_only_when_env_flag_set(tmp_path, monkeypatch):
    module = load_module()
    manual, out, _canonical = patch_paths(monkeypatch, module, tmp_path)
    candidate = out / "candidate_daily_ohlcv_20260629_20260630_from_vendor.csv"
    candidate.parent.mkdir(parents=True)
    raw_rows(["T000"]).rename(columns={"Symbol": "symbol", "Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}).to_csv(candidate, index=False)
    monkeypatch.delenv(module.APPROVE_ENV, raising=False)
    dry = module.approve_candidate(candidate, True)
    assert dry["approved_write_requested"] is False
    assert not (manual / "approved_daily_ohlcv_20260629_20260630.csv").exists()
    monkeypatch.setenv(module.APPROVE_ENV, "TRUE")
    approved = module.approve_candidate(candidate, True)
    assert approved["approved_write_succeeded"] is True
    assert (manual / "approved_daily_ohlcv_20260629_20260630.csv").is_file()


def test_dry_mode_does_not_mutate_canonical(tmp_path, monkeypatch):
    module = load_module()
    manual, _out, canonical = patch_paths(monkeypatch, module, tmp_path)
    before = canonical.read_text(encoding="utf-8")
    module.run()
    after = canonical.read_text(encoding="utf-8")
    assert before == after


def test_safety_flags_contract():
    assert SCRIPT.is_file()
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"official_adoption_allowed": False' in text
    assert '"broker_action_allowed": False' in text
    assert "protected_outputs_modified" in text
