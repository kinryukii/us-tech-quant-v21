"""Fresh fixed KMeans and IsolationForest on unchanged pre-2026 daily states."""
from __future__ import annotations
from datetime import datetime, timezone
import platform
import time
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from register_models import HERE, STATE, read, write, sha

PARAMETERS = dict(n_estimators=200, max_samples=256, contamination=.05, random_state=20260927, n_jobs=1)
CLUSTER_PARAMETERS = dict(n_clusters=4, n_init=10, random_state=20260927)


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
    contract = {"methods": ["KMeans", "IsolationForest"], "parameters": PARAMETERS,
                "cluster_parameters": CLUSTER_PARAMETERS, "feature_order": columns,
                "cutoff_exclusive": "2026-01-01", "purpose": "diagnostic_only_no_trading_veto",
                "source_path": str(source), "source_sha256": sha(source), "train_days": len(frame),
                "train_signal_min": str(frame.signal_date.min().date()), "train_signal_max": str(frame.signal_date.max().date()),
                "created_utc": datetime.now(timezone.utc).isoformat()}
    write(HERE / "AUXILIARY_PRE_FIT_CONTRACT.json", contract)
    start = time.monotonic()
    with threadpool_limits(limits=2):
        cluster = make_pipeline(StandardScaler(), KMeans(**CLUSTER_PARAMETERS)).fit(values)
        model = IsolationForest(**PARAMETERS).fit(values)
    cluster_artifact = HERE / "cluster.joblib"
    joblib.dump(cluster, cluster_artifact, compress=3)
    joblib.dump(model, artifact, compress=3)
    scores = model.decision_function(values)
    assert np.isfinite(scores).all()
    receipt = {**contract, "status": "PASS", "fit_calls": 2, "scaler_fit_calls": 1, "fit_seconds": time.monotonic() - start,
               "cluster_artifact": str(cluster_artifact), "cluster_artifact_sha256": sha(cluster_artifact),
               "artifact": str(artifact), "artifact_sha256": sha(artifact), "test_rows_read": 0,
               "training_anomaly_count": int((model.predict(values) == -1).sum()),
               "python": platform.python_version(), "sklearn": sklearn.__version__}
    write(HERE / "AUXILIARY_TRAIN_RECEIPT.json", receipt)
    registry["models"]["anomaly"] = {"path": str(artifact), "source_path": str(source), "sha256": sha(artifact),
        "role": "daily_state_diagnostic_only", "fit_reused": False, "training_cutoff_exclusive": "2026-01-01",
        "feature_order": columns, "train_receipt": str(HERE / "AUXILIARY_TRAIN_RECEIPT.json")}
    registry["models"]["cluster"] = {"path": str(cluster_artifact), "source_path": str(source),
        "sha256": sha(cluster_artifact), "role": "daily_state_diagnostic_only", "fit_reused": False,
        "training_cutoff_exclusive": "2026-01-01", "feature_order": columns,
        "train_receipt": str(HERE / "AUXILIARY_TRAIN_RECEIPT.json")}
    write(HERE / "model_registry.json", registry)
    print({"status": "PASS", "train_days": len(frame), "fit_calls": 2, "training_anomalies": receipt["training_anomaly_count"]})


if __name__ == "__main__":
    main()
