"""One fixed IsolationForest fit on pre-2026 daily states; no test read."""
from __future__ import annotations
from datetime import datetime, timezone
import platform
import time
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest
from register_models import HERE, STATE, read, write, sha

PARAMETERS = dict(n_estimators=200, max_samples=256, contamination=.05, random_state=20260927, n_jobs=1)


def main():
    artifact = HERE / "anomaly.joblib"
    if artifact.exists():
        raise RuntimeError("ANOMALY_ALREADY_FIT: preserve completed fit; use its receipt")
    registry = read(HERE / "model_registry.json")
    source = STATE / "pre2026_daily_state_inputs.parquet"
    frame = pd.read_parquet(source)
    assert frame.signal_date.notna().all() and frame.signal_date.is_unique
    assert frame.signal_date.lt("2026-01-01").all()
    columns = registry["daily_state_columns"]
    assert len(columns) == 65 and list(frame.columns) == ["signal_date", *columns]
    values = frame[columns].to_numpy(float)
    assert np.isfinite(values).all()
    contract = {"method": "IsolationForest", "parameters": PARAMETERS, "feature_order": columns,
                "cutoff_exclusive": "2026-01-01", "purpose": "diagnostic_only_no_trading_veto",
                "source_path": str(source), "source_sha256": sha(source), "train_days": len(frame),
                "train_signal_min": str(frame.signal_date.min().date()), "train_signal_max": str(frame.signal_date.max().date()),
                "created_utc": datetime.now(timezone.utc).isoformat()}
    write(HERE / "ANOMALY_PRE_FIT_CONTRACT.json", contract)
    start = time.monotonic()
    model = IsolationForest(**PARAMETERS).fit(values)
    joblib.dump(model, artifact, compress=3)
    scores = model.decision_function(values)
    assert np.isfinite(scores).all()
    receipt = {**contract, "status": "PASS", "fit_calls": 1, "fit_seconds": time.monotonic() - start,
               "artifact": str(artifact), "artifact_sha256": sha(artifact), "test_rows_read": 0,
               "training_anomaly_count": int((model.predict(values) == -1).sum()),
               "python": platform.python_version(), "sklearn": sklearn.__version__}
    write(HERE / "ANOMALY_TRAIN_RECEIPT.json", receipt)
    registry["models"]["anomaly"] = {"path": str(artifact), "source_path": str(source), "sha256": sha(artifact),
        "role": "daily_state_diagnostic_only", "fit_reused": False, "training_cutoff_exclusive": "2026-01-01",
        "feature_order": columns, "train_receipt": str(HERE / "ANOMALY_TRAIN_RECEIPT.json")}
    write(HERE / "model_registry.json", registry)
    print({"status": "PASS", "train_days": len(frame), "fit_calls": 1, "training_anomalies": receipt["training_anomaly_count"]})


if __name__ == "__main__":
    main()
