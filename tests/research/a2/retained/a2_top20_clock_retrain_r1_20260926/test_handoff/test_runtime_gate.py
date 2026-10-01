"""Synthetic Docker-inspect checks; no daemon or market data access."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from runtime_gate import verify_runtime_gate


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe"
TEST_SOURCE = r"D:\approved\r1_2026_test"
OUT_SOURCE = str(ROOT / "private_test_output")
IPC_NAME = "r1_top20_private_ipc_20260927"
IPC_SOURCE = f"/var/lib/docker/volumes/{IPC_NAME}/_data"
IDENTITY = "a" * 64
DECISION_PREDICT_CMD = ["/usr/local/bin/python", "-B", "/worker/decision_service.py",
                        "--mode", "predict", "--identity-sha", IDENTITY]
EXECUTION_PREDICT_CMD = ["/usr/local/bin/python", "-B", "/worker/test_worker.py",
                         "predict", "--manifest", "/worker/FROZEN_TEST_BATCH.json"]
DECISION_TARGET_CMD = DECISION_PREDICT_CMD[:4] + ["target", "--identity-sha", IDENTITY,
                                           "--candidate", "Raw"]
EXECUTION_ACCOUNT_CMD = EXECUTION_PREDICT_CMD[:3] + ["account", "--candidate", "Raw"]


def _bind(destination: str, source: str, writable: bool) -> dict:
    return {"Type": "bind", "Source": source, "Destination": destination,
            "Mode": "rw" if writable else "ro", "RW": writable}


def _ipc() -> dict:
    return {"Type": "volume", "Source": IPC_SOURCE, "Destination": "/ipc",
            "Name": IPC_NAME, "Mode": "rw", "RW": True}


def _container(role: str) -> dict:
    mounts = [
        _bind("/bundle", str(ROOT / "test_handoff" / "decision_bundle") if role == "decision"
              else str(ROOT / "restricted_run_20260926_01" / "run"), False),
        _bind("/worker", str(ROOT / "test_handoff"), False),
        _ipc(),
    ]
    if role == "execution":
        mounts.extend((_bind("/test", TEST_SOURCE, False),
                       _bind("/out", OUT_SOURCE, True)))
    return {
        "Id": ("d" if role == "decision" else "e") * 64,
        "Image": IMAGE,
        "Config": {"User": "10001:10001", "Volumes": {}, "Entrypoint": None,
                   "Cmd": DECISION_PREDICT_CMD if role == "decision" else EXECUTION_PREDICT_CMD,
                   "Env": ["PATH=/usr/local/bin:/usr/bin", "LANG=C.UTF-8",
                           "PYTHONDONTWRITEBYTECODE=1",
                           "R1_VERIFIED_ISOLATION=1" if role == "decision"
                           else "R1_TRAINED_ROOT=/bundle"]},
        "HostConfig": {
            "NetworkMode": "none", "Privileged": False, "ReadonlyRootfs": True,
            "CapDrop": ["ALL"], "CapAdd": [],
            "SecurityOpt": ["no-new-privileges:true"],
            "PidMode": "", "IpcMode": "private",
            "Memory": 2 * 1024**3, "PidsLimit": 256, "Tmpfs": {"/tmp": "size=64m"},
        },
        "NetworkSettings": {"Networks": {"none": {}}},
        "Mounts": mounts,
    }


def _check(decision: dict, execution: dict, should_pass: bool,
           approved_out_source: str = OUT_SOURCE,
           expected_decision_cmd: list[str] = DECISION_PREDICT_CMD,
           expected_execution_cmd: list[str] = EXECUTION_PREDICT_CMD) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "decision.json"
        e = Path(tmp) / "execution.json"
        d.write_text(json.dumps([decision]), encoding="utf-8")
        e.write_text(json.dumps([execution]), encoding="utf-8")
        try:
            receipt = verify_runtime_gate(
                d, e, r1_root=ROOT, expected_image_id=IMAGE,
                expected_decision_cmd=expected_decision_cmd,
                expected_execution_cmd=expected_execution_cmd,
                approved_test_source=TEST_SOURCE,
                approved_out_source=approved_out_source,
                approved_ipc_name=IPC_NAME,
            )
        except RuntimeError:
            if should_pass:
                raise
        else:
            if not should_pass:
                raise AssertionError("unsafe synthetic Docker inspect was accepted")
            assert receipt["decision_container_id"] != receipt["execution_container_id"]
            assert receipt["image_id"] == IMAGE
            assert len(receipt["decision_inspect_sha256"]) == 64


def main() -> None:
    decision, execution = _container("decision"), _container("execution")
    _check(decision, execution, True)

    target, account = copy.deepcopy(decision), copy.deepcopy(execution)
    target["Config"]["Cmd"] = DECISION_TARGET_CMD
    account["Config"]["Cmd"] = EXECUTION_ACCOUNT_CMD
    _check(target, account, True, expected_decision_cmd=DECISION_TARGET_CMD,
           expected_execution_cmd=EXECUTION_ACCOUNT_CMD)

    bad = copy.deepcopy(decision)
    bad["Config"]["Cmd"] = ["/bin/sh", "-c", "python /worker/decision_service.py"]
    _check(bad, execution, False)

    bad = copy.deepcopy(decision)
    bad["Config"]["Entrypoint"] = ["/bin/sh", "-c"]
    _check(bad, execution, False)

    bad = copy.deepcopy(decision)
    bad["Config"]["Env"].append("PYTHONPATH=/test")
    _check(bad, execution, False)

    bad = copy.deepcopy(execution)
    bad["Config"]["Env"][-1] = "R1_TRAINED_ROOT=/test"
    _check(decision, bad, False)

    bad = copy.deepcopy(target)
    bad["Config"]["Cmd"][-1] = "HGB_DIAG_5"
    _check(bad, account, False, expected_decision_cmd=DECISION_TARGET_CMD,
           expected_execution_cmd=EXECUTION_ACCOUNT_CMD)

    tmpfs = copy.deepcopy(decision)
    tmpfs["Mounts"].append({"Type": "tmpfs", "Source": "", "Destination": "/tmp",
                            "Mode": "rw", "RW": True})
    _check(tmpfs, execution, True)

    source = str(ROOT / "test_handoff" / "decision_bundle").replace("\\", "/")
    if len(source) > 2 and source[1:3] == ":/":
        mapped = copy.deepcopy(decision)
        mapped["Mounts"][0]["Source"] = "/run/desktop/mnt/host/" + source[0].lower() + source[2:]
        _check(mapped, execution, True)

    bad = copy.deepcopy(decision)
    bad["Mounts"].append(_bind("/test", TEST_SOURCE, False))
    _check(bad, execution, False)

    bad = copy.deepcopy(decision)
    bad["Mounts"][0]["Source"] = str(ROOT / "restricted_run_20260926_01" / "run")
    _check(bad, execution, False)

    bad = copy.deepcopy(decision)
    bad["Mounts"][2]["Name"] = "another-ipc"
    _check(bad, execution, False)

    bad = copy.deepcopy(decision)
    bad["HostConfig"]["NetworkMode"] = "bridge"
    _check(bad, execution, False)

    bad = copy.deepcopy(decision)
    bad["HostConfig"]["Privileged"] = True
    _check(bad, execution, False)

    bad = copy.deepcopy(decision)
    bad["Config"]["User"] = "root"
    _check(bad, execution, False)

    bad = copy.deepcopy(execution)
    bad["Mounts"][3]["RW"] = True
    _check(decision, bad, False)

    bad = copy.deepcopy(execution)
    bad["Mounts"][4]["Source"] = str(ROOT)
    _check(decision, bad, False)

    bad = copy.deepcopy(execution)
    bad["HostConfig"]["Memory"] = 0
    _check(decision, bad, False)

    bad = copy.deepcopy(execution)
    leaked_out = str(ROOT / "test_handoff" / "private_test_output")
    bad["Mounts"][4]["Source"] = leaked_out
    _check(decision, bad, False, approved_out_source=leaked_out)

    print("SYNTHETIC_R1_RUNTIME_GATE_PASS")


if __name__ == "__main__":
    main()
