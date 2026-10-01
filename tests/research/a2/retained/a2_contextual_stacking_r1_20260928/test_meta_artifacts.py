"""Real frozen-artifact restoration and adversarial identity checks; no fitting."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

import meta as m


class FrozenMetaArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt=m.read(m.OUT/'FIT_RECEIPT.json')

    def temporary_receipt(self,directory,receipt):
        (Path(directory)/'FIT_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False),encoding='utf-8')

    def test_common_scaler_identity_and_strict_stage_clocks(self):
        for stage,cutoff in m.STAGE_CUTOFFS.items():
            static=m.ContextualMeta('M0',stage)
            conditional=m.ContextualMeta('M1',stage)
            np.testing.assert_array_equal(static.model.main_scaler.mean_,conditional.model.main_scaler.mean_)
            np.testing.assert_array_equal(static.model.main_scaler.scale_,conditional.model.main_scaler.scale_)
            self.assertEqual(static.loaded_receipt['embedded_main_scaler_array_sha256'],
                conditional.loaded_receipt['embedded_main_scaler_array_sha256'])
            self.assertLess(pd.Timestamp(static.loaded_receipt['train_label_end_max']),pd.Timestamp(cutoff))
            self.assertEqual(conditional.model.interaction_multiplier,16.)

    def test_saved_2025_predictions_restore_from_validation_not_final(self):
        saved=pd.read_parquet(m.OUT/'validation_2025_panel_predictions.parquet').iloc[:1024]
        with np.load(m.ROOT/'panel_artifacts/panel_2025.npz',allow_pickle=False) as panel:
            features=[panel[name][:1024].copy() for name in ('p','z','basis')]
        for kind in ('M0','M1'):
            loaded=m.ContextualMeta(kind,'validation')
            np.testing.assert_allclose(loaded.predict(*features),saved[f'prediction_{kind}'].to_numpy(),
                rtol=1e-12,atol=1e-14)
            self.assertEqual(loaded.loaded_receipt['oof_years'],[2024])

    def test_future_label_clock_receipt_is_rejected(self):
        receipt=copy.deepcopy(self.receipt)
        next(row for row in receipt['fits'] if row['stage']=='validation' and row['kind']=='M0')['train_label_end_max']='2025-01-01'
        with tempfile.TemporaryDirectory() as directory,patch.object(m,'OUT',Path(directory)):
            self.temporary_receipt(directory,receipt)
            with self.assertRaisesRegex(RuntimeError,'LOAD_TIME_LEAKAGE'):
                m.ContextualMeta('M0','validation')

    def test_deserialized_final_identity_cannot_masquerade_as_validation(self):
        receipt=copy.deepcopy(self.receipt)
        record=next(row for row in receipt['fits'] if row['stage']=='validation' and row['kind']=='M0')
        fake=joblib.load(record['artifact'])
        fake.stage='final'
        with tempfile.TemporaryDirectory() as directory,patch.object(m,'OUT',Path(directory)):
            artifact=Path(directory)/'fake.joblib'
            joblib.dump(fake,artifact)
            record['artifact'],record['artifact_sha256']=str(artifact),m.sha(artifact)
            self.temporary_receipt(directory,receipt)
            with self.assertRaisesRegex(RuntimeError,'DESERIALIZED_IDENTITY'):
                m.ContextualMeta('M0','validation')

    def test_external_scaler_must_match_embedded_scaler(self):
        receipt=copy.deepcopy(self.receipt)
        record=next(row for row in receipt['fits'] if row['stage']=='validation' and row['kind']=='M0')
        fake=joblib.load(record['main_scaler_artifact'])
        fake.mean_=fake.mean_.copy()
        fake.mean_[0]+=.01
        with tempfile.TemporaryDirectory() as directory,patch.object(m,'OUT',Path(directory)):
            artifact=Path(directory)/'fake_scaler.joblib'
            joblib.dump(fake,artifact)
            record['main_scaler_artifact'],record['main_scaler_sha256']=str(artifact),m.sha(artifact)
            self.temporary_receipt(directory,receipt)
            with self.assertRaisesRegex(RuntimeError,'SCALER_DESERIALIZATION'):
                m.ContextualMeta('M0','validation')

    def test_hash_alteration_is_rejected_before_loading(self):
        receipt=copy.deepcopy(self.receipt)
        record=next(row for row in receipt['fits'] if row['stage']=='validation' and row['kind']=='M0')
        record['artifact_sha256']='0'*64
        with tempfile.TemporaryDirectory() as directory,patch.object(m,'OUT',Path(directory)):
            self.temporary_receipt(directory,receipt)
            with self.assertRaisesRegex(RuntimeError,'HASH_MISMATCH'):
                m.ContextualMeta('M0','validation')


if __name__=='__main__':
    unittest.main()
