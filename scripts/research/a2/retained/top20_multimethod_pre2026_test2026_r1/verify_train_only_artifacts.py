"""Check saved preprocessing/risk/diagnostic provenance without refitting."""
from __future__ import annotations

import json

import joblib
import pandas as pd

from fit_supervised import HERE, FOLDS, load_fold


def main() -> None:
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    prices = pd.read_parquet(HERE / "PRE2026_PRICE_COORDINATE.parquet")
    assert panel.signal_date.max() < pd.Timestamp("2026-01-01")
    assert prices.trade_date.max() < pd.Timestamp("2026-01-01")
    source = json.loads((HERE / "RISK_DIAGNOSTIC_MANIFEST.json").read_text(encoding="utf-8"))
    checks = {}
    for fold, (cutoff, _, _) in FOLDS.items():
        train, _ = load_fold(panel, fold)
        scaler = joblib.load(HERE / "models" / f"SCALER_{fold}.joblib")
        assert scaler["train_rows"] == len(train)
        assert pd.Timestamp(scaler["train_last_label_available_at"]) < pd.Timestamp(cutoff, tz="UTC") + pd.Timedelta(days=1)
        for kind in ("LW", "PCA"):
            artifact = joblib.load(HERE / "models" / f"{kind}_{fold}.joblib")
            assert pd.Timestamp(max(artifact["training_dates"])) <= pd.Timestamp(cutoff)
            assert len(artifact["security_keys"]) == artifact["correlation"].shape[0]
        for kind in ("KMEANS", "ISOLATION"):
            assert source[fold]["diagnostics"][kind]["train_rows"] == len(train)
        checks[fold] = {"training_rows": len(train), "last_mature_label": scaler["train_last_label_available_at"],
                        "risk_last_realized_date": max(joblib.load(HERE / "models" / f"LW_{fold}.joblib")["training_dates"]),
                        "auxiliary_train_rows": source[fold]["diagnostics"]["KMEANS"]["train_rows"]}
    report = {"status": "PASS", "no_2026_rows_in_training_or_price_snapshots": True,
              "no_fit_performed": True, "folds": checks}
    (HERE / "TRAIN_ONLY_ARTIFACT_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "folds": list(checks)}))


if __name__ == "__main__":
    main()
