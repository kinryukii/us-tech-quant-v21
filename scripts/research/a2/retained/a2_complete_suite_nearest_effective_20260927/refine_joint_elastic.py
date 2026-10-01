"""One bounded numerical continuation of an unconverged fixed convex fit."""
import json
import time
import warnings
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error
from threadpoolctl import threadpool_limits
import joint_linear_tree as joint


def main():
    receipt_path = joint.OUT / "FIT_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if "numerical_repairs" in receipt:
        raise RuntimeError("NUMERICAL_REPAIR_ALREADY_ATTEMPTED")
    pending = [record for record in receipt["fits"] if record["name"] == "elastic_net" and not record["converged"]]
    joint.write(joint.OUT / "ELASTIC_NUMERICAL_REPAIR_CONTRACT.json", {
        "reason": "ConvergenceWarning only; no objective or dataset change, no performance-based parameter choice",
        "stages": [record["stage"] for record in pending], "extra_max_iterations": 25000,
        "precompute_gram": True, "warm_start": True, "alpha": joint.SPECS["elastic_net"]["alpha"],
        "l1_ratio": joint.SPECS["elastic_net"]["l1_ratio"], "maximum_attempts_per_stage": 1})
    frame = pd.read_parquet(joint.HERE / "data/pre2026_joint.parquet")
    frame = frame.loc[frame.label_available & frame.new_buy_eligible].copy()
    frame = frame.rename(columns={"y_next_open": "joint_return"}).sort_values(["signal_date", "ticker"], kind="mergesort")
    repairs = []
    for record in pending:
        stage = record["stage"]
        dates = pd.to_datetime(receipt["sampling"][stage]["dates"])
        train = frame.loc[frame.signal_date.isin(dates)]
        assert len(train) == receipt["sampling"][stage]["base_rows"]
        assert train.label_end_date.max() < pd.Timestamp("2025-01-01" if stage == "validation" else "2026-01-01")
        x, y, _ = joint.counterfactual(train, robust_training=True)
        path = Path(record["artifact"])
        assert joint.sha(path) == record["artifact_sha256"]
        pipeline = joblib.load(path)
        model = pipeline[-1]
        model.set_params(precompute=True, max_iter=25000, warm_start=True)
        start = time.monotonic()
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
            warnings.simplefilter("always")
            model.fit(pipeline[0].transform(x), y)
        converged = not any(w.category.__name__ == "ConvergenceWarning" for w in caught)
        artifact = joint.OUT / f"{stage}_elastic_net_gram_refined.joblib"
        joblib.dump(pipeline, artifact, compress=3)
        repair = {"stage": stage, "name": "elastic_net", "original_artifact": str(path), "original_sha256": record["artifact_sha256"],
                  "artifact": str(artifact), "artifact_sha256": joint.sha(artifact), "fit_seconds": time.monotonic()-start,
                  "iterations": int(model.n_iter_), "dual_gap": float(model.dual_gap_), "converged": converged,
                  "fit_warnings": [{"category": w.category.__name__, "message": str(w.message)} for w in caught],
                  "objective_and_data_unchanged": True, "used_for_policy": converged, "additional_fit_calls": 1}
        repairs.append(repair)
        if stage == "validation" and converged:
            validation = frame.loc[frame.signal_date.isin(pd.to_datetime(receipt["validation_dates"]))]
            vx, vy, _ = joint.counterfactual(validation)
            prediction = joint.predict_values(pipeline, "elastic_net", vx)
            receipt["validation_metrics_before_numerical_repair"] = {"elastic_net": receipt["validation_metrics"]["elastic_net"]}
            receipt["validation_metrics"]["elastic_net"] = {"mse": float(mean_squared_error(vy, prediction))}
        print(json.dumps(repair), flush=True)
    receipt["numerical_repairs"] = repairs
    receipt["total_fit_calls_including_numerical_repairs"] = receipt["fit_calls"] + len(repairs)
    joint.write(receipt_path, receipt)
    joint.write(joint.OUT / "ELASTIC_NUMERICAL_REPAIR_RECEIPT.json", repairs)


if __name__ == "__main__":
    main()
