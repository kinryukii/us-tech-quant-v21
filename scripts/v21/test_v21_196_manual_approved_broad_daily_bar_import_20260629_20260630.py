import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_196_manual_approved_broad_daily_bar_import_20260629_20260630.py"
RUNNER = ROOT / "scripts/v21/run_v21_196_manual_approved_broad_daily_bar_import_20260629_20260630.ps1"
OUT = ROOT / "outputs/v21/V21.196_MANUAL_APPROVED_BROAD_DAILY_BAR_IMPORT_20260629_20260630"
SUMMARY = OUT / "v21_196_summary.json"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_196", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_frame(symbol_count=316):
    symbols = [f"T{i:03d}" for i in range(symbol_count)]
    rows = []
    for sym in symbols:
        rows.append({
            "symbol": sym,
            "date": "2026-06-26",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "adjusted_close": 10.5,
            "volume": 1000,
            "source_provider": "TEST",
            "source_artifact": "TEST",
            "refresh_timestamp": "",
            "row_hash": "",
            "price_row_status": "TEST",
        })
    rows.append({**rows[0], "date": "2026-06-29", "symbol": symbols[0]})
    return pd.DataFrame(rows)


def manual_rows(symbol_count=316, date="2026-06-29"):
    return pd.DataFrame([{
        "symbol": f"T{i:03d}",
        "date": date,
        "open": 20.0,
        "high": 21.0,
        "low": 19.0,
        "close": 20.5,
        "volume": 2000,
    } for i in range(symbol_count)])


def patch_paths(monkeypatch, module, tmp_path, canonical):
    out = tmp_path / "out"
    manual = tmp_path / "inputs/manual_price_sources"
    manual.mkdir(parents=True)
    canonical_path = tmp_path / "canonical.csv"
    canonical.to_csv(canonical_path, index=False)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "MANUAL_DIR", manual)
    monkeypatch.setattr(module, "CANONICAL", canonical_path)
    monkeypatch.setattr(module, "COMBINED_INPUT", manual / "approved_daily_ohlcv_20260629_20260630.csv")
    monkeypatch.setattr(module, "INPUT_20260629", manual / "approved_daily_ohlcv_20260629.csv")
    monkeypatch.setattr(module, "INPUT_20260630", manual / "approved_daily_ohlcv_20260630.csv")
    monkeypatch.setattr(module, "git_status", lambda: [])
    monkeypatch.setattr(module, "protected_modified", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "load_latest_broad_date_gate", lambda: {
        "broad_price_latest_date": "2026-06-26",
        "abcd_honest_latest_date": "2026-06-26",
    })
    return out, manual, canonical_path


def test_missing_manual_files_creates_schema_template_and_exits_safely(tmp_path, monkeypatch):
    module = load_module()
    out, _manual, _canonical = patch_paths(monkeypatch, module, tmp_path, canonical_frame())
    summary = module.run()
    assert summary["final_status"] == "PARTIAL_PASS_V21_196_WAIT_MANUAL_APPROVED_PRICE_SOURCE"
    assert summary["manual_import_attempted"] is False
    assert (out / "manual_import_schema_template_20260629_20260630.csv").is_file()
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False


def test_valid_manual_csv_creates_candidate(tmp_path, monkeypatch):
    module = load_module()
    out, manual, _canonical = patch_paths(monkeypatch, module, tmp_path, canonical_frame())
    manual_rows().to_csv(manual / "approved_daily_ohlcv_20260629.csv", index=False)
    summary = module.run()
    assert summary["manual_import_attempted"] is True
    assert summary["manual_import_valid_row_count"] == 316
    assert summary["candidate_created"] is True
    assert summary["candidate_valid"] is True
    assert summary["candidate_broad_price_latest_date"] == "2026-06-29"
    assert (out / "candidate_latest_broad_date_gate.json").is_file()


def test_duplicate_symbol_date_rows_are_rejected():
    module = load_module()
    canon = canonical_frame()
    rows = pd.concat([manual_rows(1), manual_rows(1)], ignore_index=True)
    valid, errors, rejected = module.validate_manual_rows(module.normalize_manual_rows(rows), set(canon["symbol"]))
    assert valid.empty
    assert len(rejected) == 2
    assert any("DUPLICATE_SYMBOL_DATE" in err["error"] for err in errors)


def test_bad_ohlcv_rows_are_rejected():
    module = load_module()
    canon = canonical_frame()
    rows = manual_rows(1)
    rows.loc[0, "close"] = -1
    rows.loc[0, "high"] = 5
    rows.loc[0, "volume"] = -2
    valid, errors, rejected = module.validate_manual_rows(module.normalize_manual_rows(rows), set(canon["symbol"]))
    assert valid.empty
    assert len(rejected) == 1
    joined = "|".join(err["error"] for err in errors)
    assert "CLOSE_NON_POSITIVE" in joined
    assert "VOLUME_NEGATIVE" in joined


def test_coverage_below_080_is_not_broad_eligible():
    module = load_module()
    base = module.normalize_price_panel(canonical_frame())
    append = module.make_append_rows(module.normalize_manual_rows(manual_rows(100)))
    coverage = module.coverage_for_import(append, int(base["symbol"].nunique()))
    row = next(item for item in coverage if item["date"] == "2026-06-29")
    assert row["coverage_ratio"] < 0.80
    assert row["broad_eligible"] is False
    candidate = module.make_candidate(base, append)
    gate, _rows = module.broad_gate_for_panel(candidate)
    assert gate["broad_price_latest_date"] == "2026-06-26"


def test_dry_mode_never_mutates_canonical_and_apply_requires_env(tmp_path, monkeypatch):
    module = load_module()
    _out, manual, canonical_path = patch_paths(monkeypatch, module, tmp_path, canonical_frame())
    before = canonical_path.read_text(encoding="utf-8")
    manual_rows().to_csv(manual / "approved_daily_ohlcv_20260629.csv", index=False)
    monkeypatch.delenv(module.APPLY_ENV, raising=False)
    summary = module.run()
    after = canonical_path.read_text(encoding="utf-8")
    assert before == after
    assert summary["apply_requested"] is False
    assert summary["apply_succeeded"] is False


def test_static_contract_and_summary_if_run():
    assert SCRIPT.is_file()
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "V21_196_APPLY_MANUAL_BROAD_BARS" in text
    assert "manual_import_schema_template_20260629_20260630.csv" in text
    if SUMMARY.is_file():
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        assert summary["research_only"] is True
        assert summary["official_adoption_allowed"] is False
        assert summary["broker_action_allowed"] is False
