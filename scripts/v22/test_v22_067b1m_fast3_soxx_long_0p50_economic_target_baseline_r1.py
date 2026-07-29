from pathlib import Path
p=Path(__file__).with_name("v22_067b1m_fast3_soxx_long_0p50_economic_target_baseline_r1.py")
def test_1_label():assert "long_0p50_0p25_90m" in p.read_text()
def test_2_only_a0():assert "A4M3" not in p.read_text()
def test_3_no_short_model():assert "short_pipeline" not in p.read_text()
def test_4_no_random():assert "train_test_split" not in p.read_text()
def test_5_threshold():assert "np.quantile(p['VALIDATION'],.95)" in p.read_text()
def test_6_dedup():assert "drop_duplicates('overlap_group_id')" in p.read_text()
def test_7_hash():assert "before!=after" in p.read_text()
