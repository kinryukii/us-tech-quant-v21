import unittest
from pathlib import Path
class T(unittest.TestCase):
 def test_compact_explicit(self):self.assertIn("compact_proxy_used",Path('scripts/v22/v22_050_compact_abcde_production_versioning.py').read_text())
 def test_no_score_formula_reimplementation(self):self.assertNotIn('def build_rankings',Path('scripts/v22/v22_050_compact_abcde_production_versioning.py').read_text())
 def test_reuses_r10b4_labels(self):self.assertIn('build_labels',Path('scripts/v22/r10c1_abcde_compact_v1_forward_stability_ledger.py').read_text())
if __name__=='__main__':unittest.main()
