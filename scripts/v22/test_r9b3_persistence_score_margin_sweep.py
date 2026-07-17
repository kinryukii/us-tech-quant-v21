import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import r9b3_persistence_score_margin_sweep as r
class Tests(unittest.TestCase):
 def test_catalog_exactly_ten(self): self.assertEqual(len(r.catalog()),10)
 def test_families_have_pairs(self): self.assertTrue((r.catalog().family.value_counts().loc[lambda x:x==2].size)>=4)
 def test_seed_fixed(self): self.assertEqual(r.SEED,2026071601)
 def test_core_is_separate(self): self.assertNotIn('r9b3',Path(r.ROOT/'scripts/v22/abcde_current_rule_random_backtest_r9.py').read_text().lower())
 def test_margin_values(self): self.assertEqual(set(r.catalog().margin_iqr).intersection({.2,.3}),{.2,.3})
 def test_confirmation_guard_is_metric_free(self): self.assertIn("'confirmation_return_rows_loaded':0",Path(r.__file__).read_text().lower())
 def test_result_outside_repo(self): self.assertNotEqual(r.OUT.parent.parent.parent, r.ROOT)
 def test_horizons(self): self.assertEqual(r.H,(20,60,120,252,504))
if __name__=='__main__':unittest.main()
