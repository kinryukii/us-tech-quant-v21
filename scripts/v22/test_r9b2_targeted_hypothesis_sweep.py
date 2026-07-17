import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import r9b2_targeted_hypothesis_sweep as r

class R9B2Tests(unittest.TestCase):
    def test_preregistered_catalog_is_unique(self):
        c=r.catalog()
        self.assertEqual(len(c), 11)
        self.assertFalse(c.parameter_hash.duplicated().any())
        self.assertTrue(c.pre_registered_before_development_2.all())
    def test_primary_gate_is_immutable_copy(self):
        self.assertEqual(r.sha(r.R9B/'r9b_gate_config.json'), r.sha(r.OUT/'r9b2_primary_gate_config.json'))

if __name__ == '__main__': unittest.main()
