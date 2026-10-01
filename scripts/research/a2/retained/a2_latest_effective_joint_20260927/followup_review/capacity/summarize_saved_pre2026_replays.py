"""Read-only recovery of two completed 2025 replays after a summary guard failed.

This program never calls run_replay, model inference, or a fit method. It only
summarizes existing first-attempt account files and mature pre-2026 sample keys.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from study_pre2026_capacity import (
    HERE, ROOT, SOURCE, CAP_OUTPUTS, SAMPLE_KEYS, compare,
    sha, static_training_capacity, write_json,
)

OLD = HERE / "out"
OUT = HERE / "out_02"
FAILED_RECEIPT = HERE / "CONTAINER_RECEIPT.json"
FAILED_LOG = HERE / "CONTAINER.log"


def main() -> None:
    if OUT.exists():
        if any(OUT.iterdir()):
            raise RuntimeError("RECOVERY_OUTPUT_NOT_EMPTY")
    else:
        OUT.mkdir(parents=True)
    for path in (OLD / "PRE_RUN_FREEZE.json", FAILED_RECEIPT, FAILED_LOG):
        if not path.is_file():
            raise RuntimeError(f"MISSING_FIRST_ATTEMPT_EVIDENCE:{path.name}")
    old_freeze = json.loads((OLD / "PRE_RUN_FREEZE.json").read_text(encoding="utf-8"))
    failed = json.loads(FAILED_RECEIPT.read_text(encoding="utf-8"))
    if old_freeze.get("status") != "FROZEN_PRE2026_CAPACITY_DIAGNOSTIC" or failed.get("container_exit_code") != 1:
        raise RuntimeError("WRONG_FIRST_ATTEMPT_IDENTITY")
    log_text = FAILED_LOG.read_text(encoding="utf-8")
    if "DIVERGENCE_PRECEDES_FIRST_CAP:joint_rl_ensemble" not in log_text:
        raise RuntimeError("WRONG_FIRST_ATTEMPT_FAILURE")
    old_sources = old_freeze["source_sha256"]
    changed = {}
    for source, expected in old_sources.items():
        actual = sha(Path(source))
        if actual != expected:
            changed[source] = dict(first_attempt=expected, recovery=actual)
    expected_changed = str(HERE / "study_pre2026_capacity.py")
    if set(changed) != {expected_changed}:
        raise RuntimeError(f"UNEXPECTED_FROZEN_SOURCE_CHANGE:{changed}")

    replay_files = {}
    for name in CAP_OUTPUTS:
        folder = OLD / f"{name}_no_capacity"
        files = [folder / f"{key}.parquet" for key in
                 ("daily", "trades", "positions", "target_decisions", "diagnostics", "valuation_intervals")]
        files.append(folder / "metadata.json")
        if any(not path.is_file() for path in files):
            raise RuntimeError(f"INCOMPLETE_SAVED_REPLAY:{name}")
        replay_files[name] = {str(path): sha(path) for path in files}
    frozen = dict(status="FROZEN_SAVED_2025_REPLAY_RECOVERY", batch=ROOT.name,
                  first_attempt_freeze_sha256=sha(OLD / "PRE_RUN_FREEZE.json"),
                  failed_receipt_sha256=sha(FAILED_RECEIPT), failed_log_sha256=sha(FAILED_LOG),
                  old_study_script_sha256=changed[expected_changed]["first_attempt"],
                  revised_study_script_sha256=changed[expected_changed]["recovery"],
                  recovery_script_sha256=sha(Path(__file__)),
                  preserved_replay_sha256=replay_files,
                  fit_budget=0, additional_replay_budget=0, year=2025,
                  tolerance_pre_first_bind_dollars=.01,
                  tolerance_relative_initial_account=1e-8,
                  other_first_attempt_sources_unchanged=True)
    write_json(OUT / "PRE_RECOVERY_FREEZE.json", frozen)
    print("CAPACITY_SAVED_REPLAY_RECOVERY_FROZEN", flush=True)

    sample = pd.read_parquet(SOURCE,
                             columns=["signal_date", "ticker", "label_end_date", "new_buy_eligible",
                                      "avg_dollar_volume_20d"],
                             filters=[("signal_date", ">=", pd.Timestamp("2023-01-01")),
                                      ("signal_date", "<", pd.Timestamp("2026-01-01"))])
    if sample.empty or sample.signal_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("RECOVERY_SAMPLE_DATE_BOUNDARY")
    structural = static_training_capacity(sample)

    comparisons = []
    for name, cap_folder in CAP_OUTPUTS.items():
        folder = OLD / f"{name}_no_capacity"
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        if (metadata["cost_bps_one_way"] != 10 or metadata["initial_cash"] != 1_000_000 or
                metadata["capacity_fraction"] is not None or metadata["signal_end"] != "2025-12-29"):
            raise RuntimeError(f"SAVED_REPLAY_SPEC_MISMATCH:{name}")
        saved = SimpleNamespace(**{key: pd.read_parquet(folder / f"{key}.parquet") for key in
                                   ("daily", "trades", "positions", "target_decisions", "diagnostics")})
        if saved.daily.date.max() >= pd.Timestamp("2026-01-01") or saved.daily.date.nunique() != 250:
            raise RuntimeError(f"SAVED_REPLAY_DATE_BOUNDARY:{name}")
        result = compare(name, saved, cap_folder)
        comparisons.append(result)
        write_json(OUT / f"{name}_COMPARISON.json", result)
        print("CAPACITY_SAVED_POLICY_SUMMARIZED", name, flush=True)
    for name, paths in replay_files.items():
        for path, expected in paths.items():
            if sha(Path(path)) != expected:
                raise RuntimeError(f"SAVED_REPLAY_CHANGED:{name}:{path}")
    for source, expected in old_sources.items():
        if source != expected_changed and sha(Path(source)) != expected:
            raise RuntimeError(f"ORIGINAL_SOURCE_CHANGED:{source}")
    peak_path = Path("/sys/fs/cgroup/memory.peak")
    peak = int(peak_path.read_text().strip()) if peak_path.is_file() else None
    write_json(OUT / "COMPLETE.json", dict(status="PRE2026_CAPACITY_SAVED_REPLAY_SUMMARY_COMPLETE",
               first_attempt_exit_code=1, first_attempt_replays_completed=2,
               additional_replays=0, new_supervised_fits=0, new_rl_updates=0,
               test_2026_reads=0, saved_replay_hashes_unchanged=True,
               first_attempt_noncode_sources_unchanged=True,
               first_attempt_technical_guard_failure="pre-first-cap NAV numerical difference below $0.01",
               memory_peak_bytes=peak, structural_training_capacity=structural,
               policies=comparisons,
               price_interpretation="index-coordinate proxy; no-cap is non-executable attribution"))
    print("PRE2026_CAPACITY_SAVED_REPLAY_SUMMARY_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
