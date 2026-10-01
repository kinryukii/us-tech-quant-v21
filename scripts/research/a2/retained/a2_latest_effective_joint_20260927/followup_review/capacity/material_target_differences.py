"""Read-only, pre-2026 material target-difference check on saved account traces."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path("/joint")
CAPACITY = ROOT / "followup_review" / "capacity"
OUT = CAPACITY / "out_03"
FIRST = json.loads((CAPACITY / "out" / "PRE_RUN_FREEZE.json").read_text(encoding="utf-8"))
RECOVER = json.loads((CAPACITY / "out_02" / "PRE_RECOVERY_FREEZE.json").read_text(encoding="utf-8"))
SUMMARY = json.loads((CAPACITY / "out_02" / "COMPLETE.json").read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main() -> None:
    if OUT.exists():
        if any(OUT.iterdir()):
            raise RuntimeError("MATERIAL_OUTPUT_NOT_EMPTY")
    else:
        OUT.mkdir(parents=True)
    if FIRST["status"] != "FROZEN_PRE2026_CAPACITY_DIAGNOSTIC" or \
            RECOVER["status"] != "FROZEN_SAVED_2025_REPLAY_RECOVERY" or \
            SUMMARY["status"] != "PRE2026_CAPACITY_SAVED_REPLAY_SUMMARY_COMPLETE":
        raise RuntimeError("WRONG_SAVED_CAPACITY_STUDY")
    records = []
    bound = {"first_attempt_freeze": sha(CAPACITY / "out" / "PRE_RUN_FREEZE.json"),
             "recovery_freeze": sha(CAPACITY / "out_02" / "PRE_RECOVERY_FREEZE.json"),
             "recovery_complete": sha(CAPACITY / "out_02" / "COMPLETE.json"),
             "this_script": sha(Path(__file__))}
    for policy in ("joint_hgb", "joint_rl_ensemble"):
        cap = (ROOT / ("evaluation_2025_sampling_v2" if policy == "joint_hgb" else "evaluation_2025") /
               f"{policy}_10bps" / "target_decisions.parquet")
        free = CAPACITY / "out" / f"{policy}_no_capacity" / "target_decisions.parquet"
        for path, expected in ((cap, FIRST["source_sha256"][str(cap)]),
                               (free, RECOVER["preserved_replay_sha256"][policy][str(free)])):
            actual = sha(path)
            if actual != expected:
                raise RuntimeError(f"TARGET_TRACE_HASH_CHANGED:{path}")
            bound[str(path)] = actual
        a = pd.read_parquet(cap, columns=["signal_date", "ticker", "target_weight"])
        b = pd.read_parquet(free, columns=["signal_date", "ticker", "target_weight"])
        if (a.signal_date.max() >= pd.Timestamp("2026-01-01") or
                b.signal_date.max() >= pd.Timestamp("2026-01-01")):
            raise RuntimeError("TEST_YEAR_IN_TARGET_TRACE")
        joint = a.merge(b, on=["signal_date", "ticker"], how="outer",
                        suffixes=("_cap", "_free"), validate="one_to_one")
        delta = joint.target_weight_cap.fillna(0).sub(joint.target_weight_free.fillna(0)).abs()
        first_bind = pd.Timestamp(next(p for p in SUMMARY["policies"] if p["policy"] == policy)[
            "first_binding_execution_date"])
        before = joint.signal_date.lt(first_bind)
        if joint.loc[before, ["target_weight_cap", "target_weight_free"]].isna().any().any():
            raise RuntimeError("PRE_BIND_TARGET_IDENTITY_DIFFERED")
        max_before = float(delta[before].max()) if before.any() else 0.
        if max_before > 1e-6:
            raise RuntimeError(f"PRE_BIND_TARGET_NUMERIC_DIFFERENCE:{max_before}")
        threshold_counts = {}
        for threshold in (1e-4, .01):
            changed = delta.gt(threshold)
            threshold_counts[str(threshold)] = dict(
                security_signal_keys=int(changed.sum()),
                signal_dates=int(joint.loc[changed, "signal_date"].nunique()),
                before_first_bind_keys=int((changed & before).sum()),
            )
        records.append(dict(policy=policy, compared_security_signal_keys=len(joint),
                            first_binding_execution_date=str(first_bind.date()),
                            max_pre_first_bind_weight_difference=max_before,
                            median_positive_abs_weight_difference=float(delta[delta.gt(1e-9)].median())
                            if delta.gt(1e-9).any() else 0.,
                            threshold_counts=threshold_counts))
    result = dict(status="PRE2026_MATERIAL_TARGET_DIFF_COMPLETE", year=2025,
                  scope="read-only source-hash-bound saved target comparison",
                  new_fit=0, new_replay=0, test_2026_reads=0,
                  thresholds_are_descriptive_not_selection=[1e-4, .01],
                  source_sha256=bound, policies=records)
    (OUT / "MATERIAL_TARGET_DIFFERENCES.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("PRE2026_MATERIAL_TARGET_DIFF_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
