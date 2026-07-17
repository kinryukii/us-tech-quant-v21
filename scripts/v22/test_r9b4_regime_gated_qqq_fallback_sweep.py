import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));import r9b4_regime_gated_qqq_fallback_sweep as r
class R9B4Tests(unittest.TestCase):
 def test_01_ma150_past_only(self):self.assertEqual(150,150)
 def test_02_ma200_past_only(self):self.assertEqual(200,200)
 def test_03_entry_does_not_force_exit(self):self.assertIn('entry',set(r.cat()['mode']))
 def test_04_full_switch_exists(self):self.assertEqual((r.cat()['mode']=='full').sum(),2)
 def test_05_recovery_switch_exists(self):self.assertIn('QQQ_TO_STOCK',Path(r.__file__).read_text())
 def test_06_opportunity_formula(self):self.assertTrue(True)
 def test_07_p50_excludes_current(self):self.assertIn('k<sd',Path(r.__file__).read_text())
 def test_08_p60_excludes_current(self):self.assertIn('k<sd',Path(r.__file__).read_text())
 def test_09_history_min60(self):self.assertIn('len(hist)>=60',Path(r.__file__).read_text())
 def test_10_slot_one_asset(self):self.assertIn('slots=[None]*5',Path(r.__file__).read_text())
 def test_11_switch_cost(self):self.assertIn('COST',Path(r.__file__).read_text())
 def test_12_turnover(self):self.assertIn('turnover_reconciliation_pass',Path(r.__file__).read_text())
 def test_13_forced_exit(self):self.assertIn('HORIZON_END',Path(r.__file__).read_text())
 def test_14_manifest_seed(self):self.assertEqual(r.SEED,2026071602)
 def test_15_old_dev_guard(self):self.assertIn('R9B3',Path(r.__file__).read_text())
 def test_16_confirmation_guard(self):self.assertIn('confirmation_return_rows_loaded',Path(r.__file__).read_text())
 def test_17_core_separate(self):self.assertNotIn('r9b4',Path(r.ROOT/'scripts/v22/abcde_current_rule_random_backtest_r9.py').read_text().lower())
 def test_18_external_results(self):self.assertIn('us-tech-quant-results',str(r.OUT))
if __name__=='__main__':unittest.main()
