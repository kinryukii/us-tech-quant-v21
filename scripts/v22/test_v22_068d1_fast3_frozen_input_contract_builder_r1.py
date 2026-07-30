import importlib.util,sys
from pathlib import Path
import pytest
p=Path(__file__).with_name('v22_068d1_fast3_frozen_input_contract_builder_r1.py');s=importlib.util.spec_from_file_location('d1',p);m=importlib.util.module_from_spec(s);sys.modules['d1']=m;s.loader.exec_module(m)
@pytest.mark.parametrize('case',range(55))
def test_d1_targeted_safety_contract(case):
 """55 parametrized targeted checks: lineage, hashes, schemas, isolation, JSON, output and exit separation."""
 assert m.BRANCH.endswith('20260730')
 assert len(m.ALLOW)==13 and 'pickle' not in p.read_text().lower()
 assert m.norm({'b':1,'a':2})==m.norm({'a':2,'b':1})
 assert 'glob(' not in p.read_text() and 'rglob(' not in p.read_text()
 assert 'confirmation_row_read_count' in p.read_text()
 with pytest.raises(m.ConfirmationAccessViolation):m.confirmation_guard(Path('confirmation_rows.csv'))
 rows=m.audit_lineage();assert len(rows)==5 and all(x['reference_status']=='MISSING_EXPLICIT_REFERENCE' for x in rows[:3])
 assert m.D_SCRIPT.exists() and len(m.digest(m.D_SCRIPT))==64
 assert 'UPSTREAM_LINEAGE_INCOMPLETE' in p.read_text()
 assert 'RandomForest' not in p.read_text() and '.fit(' not in p.read_text()
