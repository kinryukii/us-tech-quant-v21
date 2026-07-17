import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));import r9_postmortem_annual_stratified_random_backtest as r
class T(unittest.TestCase):
 def test_01_seed(self):self.assertEqual(r.SEED,2026071603)
 def test_02_h20(self):self.assertIn(20,r.H)
 def test_03_h40(self):self.assertIn(40,r.H)
 def test_04_h60(self):self.assertIn(60,r.H)
 def test_05_h120(self):self.assertIn(120,r.H)
 def test_06_years(self):self.assertEqual(min(r.YEARS),2019)
 def test_07_ytd(self):self.assertIn(2026,r.YEARS)
 def test_08_configs(self):self.assertEqual(len(r.configs()),5)
 def test_09_no252(self):self.assertNotIn(252,r.H)
 def test_10_external(self):self.assertIn('results',str(r.OUT))
 def test_11_core_clean(self):self.assertNotIn('postmortem',Path(r.ROOT/'scripts/v22/abcde_current_rule_random_backtest_r9.py').read_text().lower())
 def test_12_no_confirmation_returns(self):self.assertNotIn('confirmation_return',Path(r.__file__).read_text().replace("'confirmation_return_rows_loaded'",''))
 def test_13_manifest_name(self):self.assertIn('annual_manifest',Path(r.__file__).read_text())
 def test_14_soxx(self):self.assertIn('SOXX',Path(r.__file__).read_text())
 def test_15_qqq(self):self.assertIn('QQQ',Path(r.__file__).read_text())
 def test_16_forced_exit(self):self.assertIn('forced_horizon_exit_share',Path(r.__file__).read_text())
if __name__=='__main__':unittest.main()
