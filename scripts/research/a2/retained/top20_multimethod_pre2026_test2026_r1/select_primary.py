"""Freeze one primary policy using only D1/D2 paired net paths."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from policy_engine import HERE

POLICIES = ["B0", *[f"P{i}" for i in range(1, 11)]]


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(fold: str) -> pd.DataFrame:
    paths = [HERE / f"DEVELOPMENT_{fold}_POLICY_DAILY.parquet",
             HERE / f"DEVELOPMENT_{fold}_P10_DAILY.parquet"]
    if not all(p.exists() for p in paths):
        raise RuntimeError(f"P10_DEVELOPMENT_PATH_REQUIRED:{fold}")
    frame = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    assert set(frame.policy) == set(POLICIES)
    for policy, part in frame.groupby("policy"):
        assert len(part) == len(frame[frame.policy.eq("B0")])
        assert part.execution_date.tolist() == frame.loc[frame.policy.eq("B0"), "execution_date"].tolist()
        assert part.net_nav_at_execution.gt(0).all()
        assert part.fee.ge(0).all()
    return frame


def main() -> None:
    target = HERE / "PRIMARY_SELECTION.json"
    if target.exists():
        raise RuntimeError("PRIMARY_ALREADY_FROZEN")
    snapshots = {fold: read(fold) for fold in ("D1", "D2")}
    records = []
    for policy in POLICIES:
        paired = []
        details = {}
        for fold, frame in snapshots.items():
            actual = frame.loc[frame.policy.eq(policy)].net_nav_at_execution.to_numpy(float)
            baseline = frame.loc[frame.policy.eq("B0")].net_nav_at_execution.to_numpy(float)
            growth = np.diff(np.log(np.r_[1., actual]))
            b_growth = np.diff(np.log(np.r_[1., baseline]))
            paired.extend((growth - b_growth).tolist())
            details[fold] = {"execution_steps_including_terminal": len(growth),
                             "terminal_nav": float(actual[-1]),
                             "b0_terminal_nav": float(baseline[-1]),
                             "mean_paired_log_growth": float(np.mean(growth - b_growth))}
        records.append({"policy": policy,
                        "pooled_mean_paired_net_log_growth": float(np.mean(paired)),
                        "folds": details})
    candidates = [r for r in records if r["policy"] != "B0"]
    best = max(candidates, key=lambda r: r["pooled_mean_paired_net_log_growth"])
    primary = best["policy"] if best["pooled_mean_paired_net_log_growth"] > 0 else "NONE"
    report = {"primary": primary, "selected_using": "D1_D2_ONLY",
              "criterion": "equal execution steps pooled across folds, same-day B0-paired after-fee log NAV growth; terminal liquidation included",
              "configurations": json.loads((HERE / "DEVELOPMENT_SELECTION.json").read_text(encoding="utf-8"))["selection_only_D1_D2"],
              "test_asof": "2026-09-23T18:40:43Z", "records": records,
              "source_hashes": {f"{fold}_{kind}": sha(HERE / f"DEVELOPMENT_{fold}_{kind}_DAILY.parquet")
                                for fold in ("D1", "D2") for kind in ("POLICY", "P10")},
              "no_v25_or_2026_read": True}
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"primary": primary, "best_paired_daily_log": best["pooled_mean_paired_net_log_growth"]}))


if __name__ == "__main__":
    main()
