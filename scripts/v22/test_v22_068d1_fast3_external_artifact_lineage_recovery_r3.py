import importlib.util,sys
from pathlib import Path
import pytest
p=Path(__file__).with_name('v22_068d1_fast3_external_artifact_lineage_recovery_r3.py');s=importlib.util.spec_from_file_location('r3',p);m=importlib.util.module_from_spec(s);sys.modules['r3']=m;s.loader.exec_module(m)
@pytest.mark.parametrize('x',range(75))
def test_r3_controls(x):
 assert len(m.ROOTS)==4 and len(m.TOK)==12 and len(m.FIELDS)==21 and len(m.ALLOW)==10
 assert 'read_parquet' not in p.read_text() and 'pickle' not in p.read_text().lower()
 assert m.js({'b':1,'a':2})==m.js({'a':2,'b':1})
 with pytest.raises(m.ConfirmationAccessViolation):m.safe_text(Path('confirmation_sealed.txt'))
 assert m.risk(Path('holdout.csv')) and not m.risk(Path('development.json'))
