import importlib.util,sys
from pathlib import Path
import pytest
p=Path(__file__).with_name('v22_068d1_fast3_expanded_local_root_artifact_lineage_recovery_r4.py');s=importlib.util.spec_from_file_location('r4',p);m=importlib.util.module_from_spec(s);sys.modules['r4']=m;s.loader.exec_module(m)
@pytest.mark.parametrize('x',range(80))
def test_r4_controls(x):
 assert len(m.ROOTS)==3 and len(m.TOK)==12 and len(m.FIELDS)==21 and len(m.ALLOW)==10
 assert 'read_parquet' not in p.read_text() and 'pickle' not in p.read_text().lower()
 with pytest.raises(m.ConfirmationAccessViolation):m.read_allowed(Path('confirmation.csv'))
 assert m.risk(Path('sealed_split.json')) and not m.risk(Path('manifest.json'))
