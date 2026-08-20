import importlib.util
from pathlib import Path


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r35a_frozen_t1_t5_t6_outcome_blind_combination_preregistration.py"
spec = importlib.util.spec_from_file_location("r35a", RUNNER)
m = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(m)


def test_r35a_reads_only_projection_columns_by_contract():
    assert m.T1.name.endswith("OOF_PREDICTIONS.parquet")
    assert m.T5C.name.endswith("CONTRACT_R1.json")
    assert m.T6C.name.endswith("CONTRACT_R1.json")
    assert m.T1_TARGET_SHA.startswith("381ce")
