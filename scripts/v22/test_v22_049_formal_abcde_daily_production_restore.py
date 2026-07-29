import unittest
from pathlib import Path
class TestV22049(unittest.TestCase):
 def setUp(self): self.x=Path('scripts/v21/v21_233_moomoo_only_abcde_rerun.py').read_text(encoding='utf8')
 def test_compact_marker_is_explicit(self): self.assertIn('compact_proxy_used":"True"',self.x)
 def test_three_missing_components_are_explicit(self): self.assertIn('fundamentals/event/factor legacy components',self.x)
 def test_only_compact_engine_exists(self): self.assertIn('def build_rankings',self.x)
 def test_no_formal_feature_loader(self): self.assertNotIn('load_formal_fundamental',self.x)
 def test_five_compact_strategies(self): self.assertIn('E_R1_DEFENSIVE_REFERENCE',self.x)
if __name__=='__main__':unittest.main()
