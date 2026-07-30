import importlib.util,sys
from pathlib import Path
import pytest
p=Path(__file__).with_name('v22_069a0_fast3_current_canonical_source_attestation_r1.py');s=importlib.util.spec_from_file_location('x',p);m=importlib.util.module_from_spec(s);sys.modules['x']=m;s.loader.exec_module(m)
@pytest.mark.parametrize('x',range(125))
def test_failure_semantics(x):
 assert m.ACC.exists() and m.REP.exists() and len(m.ALLOW)==11
 assert 'read_parquet' not in p.read_text() and 'CURRENT_CANONICAL_PARTITION_RULE_INCOMPLETE' in p.read_text()
