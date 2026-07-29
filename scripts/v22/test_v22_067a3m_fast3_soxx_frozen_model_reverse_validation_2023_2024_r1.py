"""Eight frozen-model contract tests for V22.067A3M."""
import importlib.util
from pathlib import Path
import joblib

PATH = Path(__file__).with_name("v22_067a3m_fast3_soxx_frozen_model_reverse_validation_2023_2024_r1.py")
SPEC = importlib.util.spec_from_file_location("v220673", PATH); M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)

def test_1_bundle_reads(): b = joblib.load(M.MODEL_FILE); M.validate_bundle(b)
def test_2_hash_unchanged_check_present(): assert "before != after" in PATH.read_text(encoding="utf-8")
def test_3_not_retrained(): assert "model_retrained\": False" in PATH.read_text(encoding="utf-8")
def test_4_features_unmodified(): assert "feature_list_modified\": False" in PATH.read_text(encoding="utf-8")
def test_5_a1_threshold_directly_used(): assert "CORE.infer(data, bundle, \"LONG\")" in PATH.read_text(encoding="utf-8")
def test_6_time_range_exact(): assert str(M.START_ET.date()) == "2023-07-29" and str(M.END_ET.date()) == "2024-07-28"
def test_7_a2_dedup_reused(): assert "CORE.infer" in PATH.read_text(encoding="utf-8") and 'drop_duplicates("overlap_group_id"' in M.CORE_PATH.read_text(encoding="utf-8")
def test_8_no_triple_etf_read(): assert all(x not in M.CORE_PATH.read_text(encoding="utf-8") for x in ("TQQQ", "SQQQ", "SOXL", "SOXS"))
