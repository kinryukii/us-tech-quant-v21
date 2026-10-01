"""No-fit, pre-2026-only integrity and policy interface verification."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import joint_linear_tree as original
import retrain_coverage_v2 as v2
from v2_policy import load_policy_v2


def main():
    contract = json.loads((v2.OUT / "PRE_FIT_CONTRACT.json").read_text(encoding="utf-8"))
    v2.verify_contract(contract)
    receipt = json.loads((v2.OUT / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS" and receipt["fit_calls"] == 14
    assert receipt["total_fit_calls_including_numerical_repairs"] == 16
    assert receipt["test2026_rows_read"] == 0
    assert len(receipt["fits"]) == 14 and len(receipt["numerical_repairs"]) == 2
    assert all(r["converged"] for r in receipt["numerical_repairs"])
    for record in [*receipt["fits"], *receipt["numerical_repairs"]]:
        artifact = v2.OUT / Path(record["artifact"]).name
        assert v2.sha(artifact) == record["artifact_sha256"]
    for stage, cutoff in v2.STAGES.items():
        keys = pd.read_parquet(v2.OUT / f"sample_keys_{stage}.parquet")
        assert keys.signal_date.nunique() == contract["stages"][stage]["eligible_dates"]
        assert len(keys) == v2.BASE_BUDGET
        assert not keys.duplicated(["signal_date", "ticker"]).any()
        assert keys.label_end_date.lt(cutoff).all()
        assert keys.label_end_date.gt(keys.signal_date).all()
    panel = pd.read_parquet(v2.DATA, columns=["signal_date", "ticker", "new_buy_eligible", *original.FEATURES])
    day = panel.loc[panel.signal_date.eq(pd.Timestamp("2025-12-29"))].copy()
    assert len(day) >= 20
    results = []
    for stage in ("validation", "final"):
        for name in (*original.NAMES, "quantile_risk"):
            policy = load_policy_v2(name, stage, v2.OUT)
            target = policy(day, {}, 1.)
            assert len(target) <= 20 and sum(target.values()) <= .95 + 1e-12
            assert all(any(abs(weight - action) < 1e-12 for action in original.ACTIONS)
                       for weight in target.values())
            forbidden = day.copy()
            forbidden["new_buy_eligible"] = False
            assert policy(forbidden, {}, 1.) == {}
            results.append({"stage": stage, "name": name, "target_count": len(target),
                            "gross_target": float(sum(target.values()))})
    report = {"status": "PASS", "fit_calls": 0, "rl_updates": 0,
              "test2026_data_mounted": False, "sample_key_and_maturity_checks": True,
              "all_model_sha256_checks": True, "policy_loads": results,
              "validation_scope": "2025-12-29 pre-2026 interface smoke only, no economic scoring"}
    v2.write(v2.OUT / "TECHNICAL_VERIFICATION.json", report)
    print(json.dumps({"status": "PASS", "loaded_policies": len(results)}), flush=True)


if __name__ == "__main__":
    main()
