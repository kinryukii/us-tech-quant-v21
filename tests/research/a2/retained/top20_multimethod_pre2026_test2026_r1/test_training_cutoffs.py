"""Boundary checks for all supervised and diagnostic fold consumers."""
import unittest

import pandas as pd

from fit_supervised import HERE, load_fold


class TrainingBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")

    def test_fold_labels_are_mature_by_training_cutoff(self):
        cutoffs = {"D1": "2023-12-31", "D2": "2024-06-30",
                   "V25": "2024-12-31", "FINAL": "2025-12-31"}
        for fold, cutoff in cutoffs.items():
            train, val = load_fold(self.panel, fold)
            self.assertLessEqual(train.signal_date.max(), pd.Timestamp(cutoff))
            self.assertLessEqual(train.label_end_date.max(), pd.Timestamp(cutoff))
            self.assertLess(train.label_available_at_utc.max(),
                            pd.Timestamp(cutoff, tz="UTC") + pd.Timedelta(days=1))
            self.assertFalse(train.signal_date.isin(val.signal_date).any())

    def test_any_2026_signal_or_label_in_training_buffer_rejected(self):
        future_signal = self.panel.iloc[[0]].copy()
        future_signal["signal_date"] = pd.Timestamp("2026-01-02")
        with self.assertRaisesRegex(RuntimeError, "2026_SIGNAL"):
            load_fold(pd.concat([self.panel, future_signal]), "D1")
        future_label = self.panel.iloc[[0]].copy()
        future_label["label_available_at_utc"] = pd.Timestamp("2026-01-02", tz="UTC")
        with self.assertRaisesRegex(RuntimeError, "2026_LABEL"):
            load_fold(pd.concat([self.panel, future_label]), "D1")


if __name__ == "__main__":
    unittest.main()
