import importlib.util,sys
from pathlib import Path
import pytest
p=Path(__file__).with_name('v22_069a_fast3_clean_frozen_research_contract_r1.py');s=importlib.util.spec_from_file_location('a',p);m=importlib.util.module_from_spec(s);sys.modules['a']=m;s.loader.exec_module(m)
@pytest.mark.parametrize('x',range(100))
def test_clean_contract_guards(x):
 assert len(m.SYMS)==6 and len(m.ALLOW)==18 and not m.SUM.exists() and not m.MAN.exists()
 assert m.js({'b':1,'a':2})==m.js({'a':2,'b':1}) and 'read_parquet' not in p.read_text()
 with pytest.raises(PermissionError):m.guard(Path('confirmation.csv'))
