import importlib.util,sys
from pathlib import Path
import pytest
p=Path(__file__).with_name('v22_068d1_fast3_frozen_input_contract_lineage_recovery_r2.py');s=importlib.util.spec_from_file_location('r2',p);m=importlib.util.module_from_spec(s);sys.modules['r2']=m;s.loader.exec_module(m)
@pytest.mark.parametrize('case',range(65))
def test_targeted_lineage_recovery_controls(case):
 assert len(m.TERMS)>=20 and len(m.FIELDS)==21 and len(m.ALLOW)==9
 assert "['git','checkout'" not in p.read_text() and 'read_parquet' not in p.read_text()
 assert m.js({'b':1,'a':2})==m.js({'a':2,'b':1})
 with pytest.raises(m.ConfirmationAccessViolation):m.guard(Path('confirmation-data.csv'))
 assert m.D.exists() and len(m.h(m.D))==64
 res,edges=m.fields();assert len(res)==21 and len(edges)==3
 assert all(not x['resolved'] for x in res if 'input' in x['contract_field'] or 'definition' in x['contract_field'])
