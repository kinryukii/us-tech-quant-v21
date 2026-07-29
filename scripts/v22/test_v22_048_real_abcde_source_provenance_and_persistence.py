import unittest, pandas as pd
from scripts.v22.v22_048_real_abcde_source_provenance_and_persistence import classify_current, EXPECTED
class TestV22048(unittest.TestCase):
 def test_proxy_is_never_real(self): self.assertEqual(classify_current(pd.DataFrame({'compact_proxy_used':[True]})),'COMPACT_PRICE_ONLY_PROXY')
 def test_expected_five(self): self.assertEqual(len(EXPECTED),5)
 def test_false_flag_is_unknown_without_provenance(self): self.assertEqual(classify_current(pd.DataFrame({'compact_proxy_used':[False]})),'UNKNOWN')
if __name__=='__main__': unittest.main()
