from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fast5 import options_data_r2 as r2

def test_r2_frozen_inputs_and_feature_contract_are_unchanged() -> None:
    verified = r2.verify_data_r1()
    assert verified["status"] == "PASS"
    assert verified["feature_contract_sha256"] == r2.EXPECTED_FEATURE_SHA

def test_r2_procurement_is_minimum_volume_only() -> None:
    requirement = r2.procurement(__import__("pandas").DataFrame({"candidate_id": ["x"]}))
    assert requirement["procurement_required"]
    assert "open_interest" in requirement["not_required"]
    assert "call_volume" in requirement["minimum_tier_1"]["fields"]
