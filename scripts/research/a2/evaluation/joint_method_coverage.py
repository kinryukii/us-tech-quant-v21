"""V24 method coverage orchestration over existing inputs and common account.

The frozen R1 runner binds another target, seed and task root. This thin subclass
reuses its I/O and hashing, with V24 identity/budget accounting; it does not
implement prices, features, account execution or a second research registry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from scripts.common.storage_paths import resolve
from scripts.research.a2.data.joint_input_binding import (
    FEATURES, load_training_inputs, load_held_features,
)
from scripts.research.a2.evaluation.joint_execution_resume import JointExecution, digest

SEED = 20260928


def mature_training_mask(frame, cutoff):
    cutoff = pd.Timestamp(cutoff)
    if cutoff > pd.Timestamp("2026-01-01"):
        raise ValueError("Fit cutoff crosses project boundary")
    return (frame.fit_eligible.astype(bool) & frame.signal_date.lt(cutoff)
            & frame.label_mature_date.lt(cutoff) & frame.label_end_date.lt(cutoff)
            & frame.execution_date.gt(frame.signal_date)
            & np.isfinite(frame.y_open5))


def date_weights(frame):
    counts = frame.signal_date.map(frame.signal_date.value_counts()).to_numpy(float)
    weights = 1 / counts
    return weights / weights.mean()


def prior_oof_rows(history, cutoff, prediction):
    cutoff = pd.Timestamp(cutoff)
    valid = (history.fit_eligible.astype(bool)
             & history.signal_date.lt(cutoff)
             & history.label_mature_date.lt(cutoff)
             & history.label_end_date.lt(cutoff)
             & np.isfinite(history[prediction]) & np.isfinite(history.y_open5)
             & history.source_fit_cutoff.le(history.signal_date))
    return history.loc[valid].copy()


class JointMethodCoverage(JointExecution):
    def __init__(self, root):
        self.root = Path(root).resolve()
        roots = resolve(Path(__file__).resolve().parents[4])
        expected = roots.results_root / "JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1" / "V24"
        if self.root != expected.resolve():
            raise ValueError("Unexpected V24 task destination")
        self.parameters = self.read("RUN_CONFIG.json")
        self.features = list(FEATURES)
        self.status = (self.read("work/FIT_STATUS.json")
                       if self.out("work/FIT_STATUS.json").exists() else
                       {"status": "READY", "fit_attempts": 0, "records": [],
                        "failures": [], "account_paths": 0, "rl_optimizer_updates": 0,
                        "test2026_rows_read": 0})
        self.input_sha = digest(self.out("INPUT_BINDING.json"))

    def checkpoint(self):
        self.write("work/FIT_STATUS.json", self.status)
        manifest = self.read("RUN_MANIFEST.json")
        manifest.update(status=self.status["status"], actual_fit_units=self.status["fit_attempts"],
                        account_paths=self.status["account_paths"],
                        rl_optimizer_updates=self.status["rl_optimizer_updates"],
                        test2026_data_pages_read=0)
        self.write("RUN_MANIFEST.json", manifest)

    def fit_state(self, kind, year, key, frame, creator, state_count=1):
        artifact = self.out(f"models/{kind}_{year}.joblib")
        fields = [c for c in ["signal_date", "ticker", "label_end_date",
                             "label_mature_date", "y_open5", *self.features]
                  if c in frame]
        identity = {
            "kind": kind, "cutoff_exclusive": f"{year}-01-01",
            "target": self.parameters["target"], "features": self.features,
            "input_binding_sha256": self.input_sha, "key": key,
            "train_values_sha256": hashlib.sha256(pd.util.hash_pandas_object(
                frame[fields], index=False).values.tobytes()).hexdigest(),
            "parameters_sha256": digest(self.out("RUN_CONFIG.json")), "seed": SEED,
        }
        previous = next((r for r in self.status["records"] if r["identity"] == identity), None)
        if previous:
            if previous["status"] != "FIT_COMPLETE":
                raise RuntimeError("Failed or interrupted attempt retained; explicit engineering repair required")
            if not artifact.exists() or digest(artifact) != previous["sha256"]:
                raise RuntimeError("Fitted artifact changed")
            print(json.dumps({"status": "DIRECT_REUSE", "kind": kind, "year": year}), flush=True)
            return joblib.load(artifact)
        if artifact.exists():
            raise RuntimeError("Unregistered artifact preserved")
        if self.status["fit_attempts"] + state_count > self.parameters["budget"]["max_total_fit_units"]:
            raise RuntimeError("Finite fit budget exhausted")
        self.status["fit_attempts"] += state_count
        record = {"identity": identity, "status": "FIT_STARTED", "learned_states": state_count,
                  "rows": len(frame), "artifact": str(artifact),
                  "signal_min": str(frame.signal_date.min()),
                  "signal_max": str(frame.signal_date.max()),
                  "max_label_maturity": str(frame.label_mature_date.max()) if "label_mature_date" in frame else None,
                  "started_utc": datetime.now(timezone.utc).isoformat()}
        self.status["records"].append(record)
        self.status["status"] = "REAL_PRE2026_FITS_RUNNING"
        self.checkpoint()
        start = time.monotonic()
        print(json.dumps({"status": "REAL_FIT_STARTED", "kind": kind, "year": year, "rows": len(frame)}), flush=True)
        try:
            with threadpool_limits(limits=2):
                obj = creator()
            joblib.dump(obj, artifact, compress=3)
            record.update(status="FIT_COMPLETE", sha256=digest(artifact), seconds=time.monotonic()-start)
        except Exception as exc:
            record.update(status="FIT_FAILURE", error=repr(exc), seconds=time.monotonic()-start)
            self.status["failures"].append({"kind": kind, "year": year, "error": repr(exc)})
            self.checkpoint()
            raise
        self.checkpoint()
        print(json.dumps({"status": "REAL_FIT_COMPLETE", "kind": kind, "year": year,
                          "seconds": round(record["seconds"], 2)}), flush=True)
        return obj

    def fit_initial(self):
        binding = self.read("INPUT_BINDING.json")
        if not binding.get("full848_label_extension"):
            raise RuntimeError("Wait for source-backed full848 five-session binding")
        frame = load_training_inputs(binding)
        held = load_held_features(binding)
        held.signal_date = pd.to_datetime(held.signal_date)
        meta = frame[["signal_date", "ticker", "execution_date", "label_end_date",
                      "label_mature_date", "y_open5", "trade_eligible", "fit_eligible"]]
        prediction_frame = held.merge(meta, on=["signal_date", "ticker"], how="left",
                                     validate="one_to_one", sort=False)
        prediction_frame["trade_eligible"] = prediction_frame.trade_eligible.eq(True)
        prediction_frame["fit_eligible"] = prediction_frame.fit_eligible.eq(True)
        if prediction_frame.signal_date.ge("2026-01-01").any():
            raise ValueError("Forbidden mixed-year prediction input")
        freeze = {
            "status": "SOURCE_AND_INPUT_FROZEN_BEFORE_FIRST_FIT",
            "source": str(Path(__file__).resolve()), "source_sha256": digest(__file__),
            "input_binding_sha256": self.input_sha,
            "run_config_sha256": digest(self.out("RUN_CONFIG.json")),
            "target": self.parameters["target"],
            "years": [2021, 2022, 2023, 2024, 2025], "seed": SEED,
            "base_sample_weight": "date-equal within strictly matured legal training rows",
            "calibration": "all earlier matured chronological OOF; affine Ridge alpha100; weighted residual RMS",
            "prediction_domain": "accepted signal-day PIT32 including held extensions; new buys independently constrained",
            "training_legal_rows": int(frame.fit_eligible.sum()),
            "trade_eligible_rows": int(frame.trade_eligible.sum()),
            "sampling": False, "test2026_reads": 0,
        }
        freeze_path = self.out("receipts/INITIAL_FIT_FREEZE.json")
        if freeze_path.exists():
            old = self.read("receipts/INITIAL_FIT_FREEZE.json")
            if old != freeze:
                raise RuntimeError("Freeze changed after attempt")
        else:
            self.write("receipts/INITIAL_FIT_FREEZE.json", freeze)
        histories = {"Ridge": [], "HGB": []}
        for year in [2021, 2022, 2023, 2024, 2025]:
            cutoff = pd.Timestamp(year, 1, 1)
            train = frame.loc[mature_training_mask(frame, cutoff)].copy()
            if train.empty:
                raise RuntimeError(f"No matured training rows for {year}")
            valid = prediction_frame.signal_date.ge(cutoff) & prediction_frame.signal_date.lt(pd.Timestamp(year+1, 1, 1))
            block = prediction_frame.loc[valid, meta.columns].copy()
            block["source_fit_cutoff"] = cutoff
            block["fold_year"] = year
            xx = train[self.features].to_numpy(float)
            yy = train.y_open5.to_numpy(float)
            weights = date_weights(train)
            vx = prediction_frame.loc[valid, self.features].to_numpy(float)
            if not np.isfinite(vx).all():
                raise RuntimeError("Accepted feature projection contains nonfinite inputs")
            for name in ["Ridge", "HGB"]:
                cfg = dict(self.parameters["initial_primary_models"][name])
                def creator(name=name, cfg=cfg):
                    if name == "Ridge":
                        scaler = StandardScaler().fit(xx, sample_weight=weights)
                        model = Ridge(alpha=cfg["alpha"]).fit(scaler.transform(xx), yy, sample_weight=weights)
                        return {"model": model, "scaler": scaler}
                    return {"model": HistGradientBoostingRegressor(**cfg).fit(xx, yy, sample_weight=weights),
                            "scaler": None}
                bundle = self.fit_state("five_day_"+name, year, cfg, train, creator, 2 if name == "Ridge" else 1)
                with threadpool_limits(limits=2):
                    values = bundle["scaler"].transform(vx) if bundle["scaler"] is not None else vx
                    block[name+"_raw"] = bundle["model"].predict(values)
                block[name+"_mu"] = np.nan
                block[name+"_uncertainty"] = np.nan
                if histories[name]:
                    history = prior_oof_rows(pd.concat(histories[name], ignore_index=True), cutoff, name+"_raw")
                    if history.empty:
                        raise RuntimeError("No matured prior OOF for calibration")
                    hx = history[[name+"_raw"]].to_numpy(float)
                    hy = history.y_open5.to_numpy(float)
                    hw = date_weights(history)
                    def make_calibrator():
                        scaler = StandardScaler().fit(hx, sample_weight=hw)
                        model = Ridge(alpha=100).fit(scaler.transform(hx), hy, sample_weight=hw)
                        residual = hy - model.predict(scaler.transform(hx))
                        return {"model": model, "scaler": scaler,
                                "residual_rms": float(max(np.sqrt(np.average(residual**2, weights=hw)), 1e-6))}
                    calibrated = self.fit_state("five_day_calibration_"+name, year,
                                                {"alpha": 100, "source": "prior_matured_trueOOF"},
                                                history, make_calibrator, 3)
                    with threadpool_limits(limits=2):
                        block[name+"_mu"] = calibrated["model"].predict(
                            calibrated["scaler"].transform(block[[name+"_raw"]].to_numpy(float)))
                    block[name+"_uncertainty"] = calibrated["residual_rms"]
                histories[name].append(block[["signal_date", "ticker", "execution_date", "label_end_date",
                                             "label_mature_date", "y_open5", "fit_eligible",
                                             "source_fit_cutoff", name+"_raw"]].copy())
            block.to_parquet(self.out(f"OOF/INITIAL_{year}.parquet"), index=False)
            self.write(f"receipts/INITIAL_{year}.json", {
                "status": "REAL_TRUE_OOF", "year": year,
                "source_fit_cutoff": str(cutoff.date()),
                "source_label_maturity_max": str(train.label_mature_date.max()),
                "training_rows": len(train), "prediction_rows": len(block),
                "new_buy_candidate_rows": int(block.trade_eligible.sum()),
                "oof_path": str(self.out(f"OOF/INITIAL_{year}.parquet")),
                "sha256": digest(self.out(f"OOF/INITIAL_{year}.parquet")),
                "calibrated": year >= 2022, "test2026_reads": 0})
        coverage = pd.read_csv(self.out("METHOD_COVERAGE.csv"))
        for number in [1, 5]:
            mask = coverage.method_id.eq(f"M{number:03d}")
            coverage.loc[mask, "status"] = "REAL_5DAY_FIT_AND_CHRONOLOGICAL_OOF_COMPLETE"
            coverage.loc[mask, "evidence"] = "receipts/INITIAL_FIT_FREEZE.json;OOF/INITIAL_2021..2025.parquet"
        coverage.to_csv(self.out("METHOD_COVERAGE.csv"), index=False)
        self.status["status"] = "INITIAL_FULL848_FITS_AND_TRUE_OOF_COMPLETE"
        self.checkpoint()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", required=True)
    parser.add_argument("command", choices=["fit-initial"])
    args = parser.parse_args()
    JointMethodCoverage(args.task_root).fit_initial()


if __name__ == "__main__":
    main()
