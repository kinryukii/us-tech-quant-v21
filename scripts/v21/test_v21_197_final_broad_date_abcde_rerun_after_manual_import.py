import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_197_final_broad_date_abcde_rerun_after_manual_import.py"
RUNNER = ROOT / "scripts/v21/run_v21_197_final_broad_date_abcde_rerun_after_manual_import.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_197", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_date_coverage_broad_eligible():
    module = load_module()
    rows = [{"symbol": f"T{i:03d}", "date": "2026-06-30", "close": 10.0} for i in range(315)]
    frame = pd.DataFrame(rows)
    cov = module.date_coverage(frame)
    assert cov[0]["broad_price_date_eligible"] is True
    assert cov[0]["coverage_ratio"] == 1.0


def test_topn_uses_eligible_and_rank_order():
    module = load_module()
    frame = pd.DataFrame([
        {"ticker": "B", "rank": 2, "eligible_flag": True},
        {"ticker": "A", "rank": 1, "eligible_flag": True},
        {"ticker": "C", "rank": 3, "eligible_flag": False},
    ])
    assert list(module.topn(frame, 2)["ticker"]) == ["A", "B"]


def test_required_contract_flags_and_files():
    assert SCRIPT.is_file()
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"official_adoption_allowed": False' in text
    assert '"broker_action_allowed": False' in text
    assert "protected_outputs_modified" in text
    assert "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT" in text


def test_protected_modified_allows_only_v21_197_outputs():
    module = load_module()
    baseline = []
    allowed = ["?? outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/a.csv"]
    assert module.protected_modified(allowed, baseline) is False
    blocked = [" M outputs/v21/official_ranking.csv"]
    assert module.protected_modified(blocked, baseline) is True
