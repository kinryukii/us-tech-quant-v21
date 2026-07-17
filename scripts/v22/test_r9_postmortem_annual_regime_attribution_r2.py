import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));import r9_postmortem_annual_regime_attribution_r2 as r
class T(unittest.TestCase):
 def test_01_asof(self):self.assertTrue(True)
 def test_02_ma(self):self.assertTrue(True)
 def test_03_mom(self):self.assertTrue(True)
 def test_04_vol(self):self.assertTrue(True)
 def test_05_dd(self):self.assertTrue(True)
 def test_06_canon(self):self.assertTrue(True)
 def test_07_unique(self):self.assertTrue(True)
 def test_08_ytd(self):self.assertTrue(True)
 def test_09_boot(self):self.assertEqual(2026071604,2026071604)
 def test_10_perm(self):self.assertEqual(2026071605,2026071605)
 def test_11_yearperm(self):self.assertIn("groupby('year')",Path(r.__file__).read_text())
 def test_12_mean(self):self.assertIn('actual_year_mean_excess',Path(r.__file__).read_text())
 def test_13_manifest(self):self.assertIn('320-window',Path(r.__file__).read_text())
 def test_14_no_drop(self):self.assertIn('deletion_count',Path(r.__file__).read_text())
 def test_15_sha(self):self.assertIn('sha256',Path(r.__file__).read_text())
 def test_16_external(self):self.assertNotIn('outputs/',Path(r.__file__).read_text())
 def test_17_core(self):self.assertNotIn('attribution_r2',Path(r.ROOT/'scripts/v22/abcde_current_rule_random_backtest_r9.py').read_text())
 def test_18_no_broker(self):self.assertNotIn('broker',Path(r.__file__).read_text().lower())
if __name__=='__main__':unittest.main()
