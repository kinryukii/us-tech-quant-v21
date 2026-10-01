"""Post-fit identity check only; reads no market data and never updates models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
SEAL = HERE / "TRAIN_OUTPUT_SEAL.json"


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    if SEAL.exists():
        raise RuntimeError("PRESERVE_EXISTING_RL_TRAIN_SEAL")
    runtime = json.loads((HERE / "RUNTIME_COMMAND_train.json").read_text(encoding="utf-8-sig"))
    receipt = json.loads((OUT / "TRAIN_RECEIPT.json").read_text(encoding="utf-8"))
    container = json.loads((HERE / "CONTAINER_RECEIPT_train.json").read_text(encoding="utf-8-sig"))
    inspect = json.loads((HERE / "CONTAINER_INSPECT_train.json").read_text(encoding="utf-8-sig"))[0]
    if container["container_exit_code"] != 0 or container["train_receipt_sha256"] != sha(OUT / "TRAIN_RECEIPT.json"):
        raise RuntimeError("TRAIN_RUNTIME_RECEIPT_MISMATCH")
    if receipt["status"] != "PRE2026_CAPACITY_AWARE_RL_TRAINED" or receipt["actual_parameter_updates"] != 320:
        raise RuntimeError("RL_ACTUAL_UPDATE_COUNT_MISMATCH")
    if receipt["fit_2026_rows"] != 0 or receipt["reward_end_max"] >= "2026-01-01":
        raise RuntimeError("TRAIN_CUTOFF_VIOLATION")
    expected = {(stage, seed, epoch) for stage in ("validation", "final")
                for seed in (20260927, 20260928) for epoch in (1, 2, 3, 4)}
    actual = {(v["stage"], v["seed"], v["epoch"]) for v in receipt["logs"] if v["stage"] != "2025_validation"}
    if expected != actual:
        raise RuntimeError("RL_EPISODE_SET_MISMATCH")
    if any(v["days"] != (500 if v["stage"] == "validation" else 750)
           for v in receipt["logs"] if v["stage"] != "2025_validation"):
        raise RuntimeError("RL_TRAINING_DATE_COUNT_MISMATCH")
    output_names = {p.name for p in OUT.iterdir() if p.is_file()}
    if len(output_names) != 15:
        raise RuntimeError(f"UNEXPECTED_RL_OUTPUT_FILE_SET:{sorted(output_names)}")
    deltas = {}
    for stage in ("validation", "final"):
        for seed in (20260927, 20260928):
            initial = torch.load(OUT / f"{stage}_rl_{seed}_zero.pt", weights_only=True, map_location="cpu")
            trained = torch.load(OUT / f"{stage}_rl_{seed}.pt", weights_only=True, map_location="cpu")
            if initial.keys() != trained.keys():
                raise RuntimeError("MODEL_ARCHITECTURE_CHANGED")
            count = sum(v.numel() for v in trained.values())
            if count != 1729:
                raise RuntimeError(f"PARAMETER_COUNT_MISMATCH:{count}")
            diff = sum(float((trained[k] - initial[k]).abs().sum()) for k in trained)
            if not np.isfinite(diff) or diff <= 0:
                raise RuntimeError("NO_REAL_PARAMETER_UPDATE")
            if not all(bool(torch.isfinite(v).all()) for v in trained.values()):
                raise RuntimeError("NONFINITE_MODEL_WEIGHT")
            deltas[f"{stage}_{seed}"] = diff
    for mount in inspect["Mounts"]:
        source = str(mount.get("Source", "")).lower()
        destination = str(mount.get("Destination", "")).lower()
        if any(fragment in source for fragment in ("evaluation_2026", "test_prices", "test_features")):
            raise RuntimeError("TEST_SOURCE_MOUNTED")
        if mount.get("RW") and destination != "/joint/followup_review/capacity_aware_rl/out":
            raise RuntimeError(f"UNEXPECTED_WRITABLE_MOUNT:{destination}")
    if inspect["HostConfig"]["NetworkMode"] != "none" or not inspect["HostConfig"]["ReadonlyRootfs"]:
        raise RuntimeError("RUNTIME_ISOLATION_CONFIG_CHANGED")
    inputs = {}
    for item in runtime["inputs"]:
        inputs[item["target"]] = dict(host_path=item["source"], sha256=item["sha256"])
        if sha(item["source"]) != item["sha256"]:
            raise RuntimeError(f"INPUT_MODIFIED_AFTER_FIT:{item['target']}")
    if any(fragment in target for target in inputs
           for fragment in ("evaluation_2026", "test_prices", "test_features")):
        raise RuntimeError("TEST_SOURCE_INPUT")
    output = dict(
        status="PRE2026_CAPACITY_AWARE_RL_OUTPUT_SEALED",
        batch="a2_latest_effective_joint_20260927",
        container_id=container["container_id"], image_id=container["image_id"],
        container_exit_code=container["container_exit_code"],
        network_mode=inspect["HostConfig"]["NetworkMode"],
        read_only_root=inspect["HostConfig"]["ReadonlyRootfs"],
        memory_limit_bytes=inspect["HostConfig"]["Memory"],
        cpu_limit_nano=inspect["HostConfig"].get("NanoCpus"),
        writable_mounts=[m["Destination"] for m in inspect["Mounts"] if m["RW"]],
        runtime_command_sha256=sha(HERE / "RUNTIME_COMMAND_train.json"),
        input_files=inputs,
        output_files={p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()},
        actual_rl_updates=receipt["actual_parameter_updates"],
        model_parameter_deltas_l1=deltas,
        max_reward_end=receipt["reward_end_max"],
        test_2026_reads=0, new_supervised_fits=0,
    )
    SEAL.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(dict(status=output["status"], seal_sha256=sha(SEAL),
                          model_deltas=deltas, updates=320,
                          output_files=len(output["output_files"]))), flush=True)


if __name__ == "__main__":
    main()
