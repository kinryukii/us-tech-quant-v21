"""Check the two R1 test containers from saved ``docker inspect`` output.

The caller obtains the inspect JSON from the local daemon and supplies source
paths and the image ID from the *frozen* batch manifest. This module does not
open a market file or call Docker. It only checks the actual container config;
the caller must still verify the inspect files came from its two fresh runs.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath


_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_WIN_DRIVE = re.compile(r"^[a-zA-Z]:/")
_DESKTOP_DRIVE = re.compile(
    r"^/(?:run/desktop/mnt/host|host_mnt|mnt)/([a-zA-Z])(/.*)?$", re.I
)
_BASE_ENV = frozenset({
    "PATH", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256",
    "PYTHONUNBUFFERED", "PIP_DISABLE_PIP_VERSION_CHECK", "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
})
_PYTHON = "/usr/local/bin/python"


def _host_key(value: str) -> str:
    """Compare Windows binds with Docker Desktop's equivalent Linux source."""
    if not isinstance(value, str) or not value:
        raise RuntimeError("MOUNT_SOURCE_MISSING")
    source = value.replace("\\", "/")
    match = _DESKTOP_DRIVE.fullmatch(source)
    if match:
        source = f"{match[1]}:{match[2] or '/'}"
    if _WIN_DRIVE.match(source):
        return PureWindowsPath(source).as_posix().rstrip("/").casefold()
    if source.startswith("/"):
        return str(PurePosixPath(source)).rstrip("/")
    raise RuntimeError(f"MOUNT_SOURCE_NOT_ABSOLUTE:{value}")


def _host_child(root: str | Path, *parts: str) -> str:
    """Join a manifest's Windows host path even when checking inside Linux."""
    source = str(root).replace("\\", "/")
    match = _DESKTOP_DRIVE.fullmatch(source)
    if match:
        source = f"{match[1]}:{match[2] or '/'}"
    if _WIN_DRIVE.match(source):
        return PureWindowsPath(source, *parts).as_posix()
    if source.startswith("/"):
        return str(PurePosixPath(source, *parts))
    raise RuntimeError("R1_HOST_ROOT_NOT_ABSOLUTE")


def _sources_overlap(left: str, right: str) -> bool:
    a, b = _host_key(left), _host_key(right)
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _mount_name(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise RuntimeError(f"MOUNT_DESTINATION_INVALID:{value}")
    cleaned = str(PurePosixPath(value))
    if cleaned != value or value == "/":
        raise RuntimeError(f"MOUNT_DESTINATION_INVALID:{value}")
    return cleaned


def _inspect(path: Path) -> tuple[dict, str]:
    if path.stat().st_size > 2_000_000:
        raise RuntimeError("INSPECT_TOO_LARGE")
    raw = path.read_bytes()
    value = json.loads(raw)
    if isinstance(value, list):
        if len(value) != 1:
            raise RuntimeError("INSPECT_CONTAINER_COUNT")
        value = value[0]
    if not isinstance(value, dict) or not isinstance(value.get("Id"), str) or not _CONTAINER_ID.fullmatch(value["Id"]):
        raise RuntimeError("INSPECT_CONTAINER_ID_MISSING")
    return value, hashlib.sha256(raw).hexdigest()


def _security(obj: dict, expected_image_id: str, role: str) -> None:
    host = obj.get("HostConfig") or {}
    config = obj.get("Config") or {}
    if obj.get("Image") != expected_image_id:
        raise RuntimeError(f"{role}:IMAGE_ID_MISMATCH")
    if host.get("NetworkMode") != "none":
        raise RuntimeError(f"{role}:NETWORK_NOT_NONE")
    networks = (obj.get("NetworkSettings") or {}).get("Networks") or {}
    if not isinstance(networks, dict) or set(networks) - {"none"}:
        raise RuntimeError(f"{role}:NETWORK_ATTACHMENT")
    if host.get("Privileged") is not False or host.get("ReadonlyRootfs") is not True:
        raise RuntimeError(f"{role}:PRIVILEGED_OR_WRITABLE_ROOT")
    if "all" not in {str(v).casefold() for v in (host.get("CapDrop") or [])}:
        raise RuntimeError(f"{role}:CAPABILITIES_NOT_DROPPED")
    if host.get("CapAdd"):
        raise RuntimeError(f"{role}:CAPABILITIES_ADDED")
    security = {str(v).casefold() for v in (host.get("SecurityOpt") or [])}
    if not any(v == "no-new-privileges" or v.startswith("no-new-privileges:") for v in security):
        raise RuntimeError(f"{role}:NEW_PRIVILEGES_ALLOWED")
    user = str(config.get("User") or "").split(":", 1)[0].casefold()
    if user in {"", "root", "0"}:
        raise RuntimeError(f"{role}:ROOT_USER")
    if str(host.get("PidMode") or "") not in {"", "private"}:
        raise RuntimeError(f"{role}:PID_NAMESPACE_SHARED")
    if str(host.get("IpcMode") or "") not in {"", "private"}:
        raise RuntimeError(f"{role}:IPC_NAMESPACE_SHARED")
    for key in ("UTSMode", "UsernsMode", "CgroupnsMode"):
        if str(host.get(key) or "") == "host":
            raise RuntimeError(f"{role}:{key}_HOST")
    for key in ("Devices", "DeviceRequests", "DeviceCgroupRules", "VolumesFrom",
                "Links", "PortBindings"):
        if host.get(key):
            raise RuntimeError(f"{role}:FORBIDDEN_HOST_CONFIG:{key}")
    if host.get("PublishAllPorts"):
        raise RuntimeError(f"{role}:PUBLISHED_PORTS")
    if not isinstance(host.get("Memory"), int) or host["Memory"] <= 0:
        raise RuntimeError(f"{role}:MEMORY_LIMIT_MISSING")
    if not isinstance(host.get("PidsLimit"), int) or host["PidsLimit"] <= 0:
        raise RuntimeError(f"{role}:PIDS_LIMIT_MISSING")
    tmpfs = host.get("Tmpfs") or {}
    if not isinstance(tmpfs, dict) or set(tmpfs) - {"/tmp"}:
        raise RuntimeError(f"{role}:UNAPPROVED_TMPFS")


def _expected_commands(decision: list[str], execution: list[str]) -> None:
    dec_prefix = [_PYTHON, "-B", "/worker/decision_service.py", "--mode"]
    exec_prefix = [_PYTHON, "-B", "/worker/test_worker.py"]
    if not isinstance(decision, list) or decision[:4] != dec_prefix or \
            not isinstance(execution, list) or execution[:3] != exec_prefix:
        raise RuntimeError("FIXED_PYTHON_ENTRY_REQUIRED")
    if not all(isinstance(v, str) for v in decision + execution):
        raise RuntimeError("COMMAND_ARGUMENT_INVALID")
    if len(decision) < 7 or decision[5] != "--identity-sha" or \
            _SHA256.fullmatch(decision[6]) is None:
        raise RuntimeError("DECISION_BUNDLE_IDENTITY_REQUIRED")
    mode = decision[4]
    if mode == "predict":
        if len(decision) != 7 or len(execution) < 4 or execution[3] != "predict" or \
                "--candidate" in execution:
            raise RuntimeError("PREDICTION_PROCESS_MISMATCH")
    elif mode == "target":
        if len(decision) != 9 or decision[7] != "--candidate" or \
                not decision[8] or decision[8].startswith("-"):
            raise RuntimeError("TARGET_CANDIDATE_REQUIRED")
        if len(execution) < 4 or execution[3] != "account" or \
                execution.count("--candidate") != 1:
            raise RuntimeError("ACCOUNT_PROCESS_MISMATCH")
        pos = execution.index("--candidate")
        if pos + 1 >= len(execution) or execution[pos + 1] != decision[8]:
            raise RuntimeError("ACCOUNT_CANDIDATE_MISMATCH")
    else:
        raise RuntimeError("DECISION_MODE_INVALID")


def _process(obj: dict, expected_cmd: list[str], role: str) -> None:
    config = obj.get("Config") or {}
    if config.get("Entrypoint") not in (None, []):
        raise RuntimeError(f"{role}:UNEXPECTED_ENTRYPOINT")
    if config.get("Cmd") != expected_cmd:
        raise RuntimeError(f"{role}:COMMAND_MISMATCH")
    env = config.get("Env")
    if not isinstance(env, list):
        raise RuntimeError(f"{role}:ENV_MISSING")
    parsed = {}
    for item in env:
        if not isinstance(item, str) or "=" not in item or "\x00" in item:
            raise RuntimeError(f"{role}:ENV_INVALID")
        key, value = item.split("=", 1)
        if not key or key in parsed:
            raise RuntimeError(f"{role}:ENV_DUPLICATE_OR_INVALID")
        parsed[key] = value
    required = {"PYTHONDONTWRITEBYTECODE": "1"}
    if role == "decision":
        required["R1_VERIFIED_ISOLATION"] = "1"
    else:
        required["R1_TRAINED_ROOT"] = "/bundle"
    if set(parsed) - (_BASE_ENV | set(required)) or any(
        parsed.get(key) != value for key, value in required.items()
    ):
        raise RuntimeError(f"{role}:ENV_NOT_ALLOWLISTED")


def _mounts(obj: dict, expected_destinations: set[str], role: str) -> dict[str, dict]:
    mounted = obj.get("Mounts")
    if not isinstance(mounted, list):
        raise RuntimeError(f"{role}:MOUNTS_MISSING")
    tmpfs_declared = "/tmp" in ((obj.get("HostConfig") or {}).get("Tmpfs") or {})
    by_destination = {}
    for mount in mounted:
        if not isinstance(mount, dict):
            raise RuntimeError(f"{role}:MOUNT_INVALID")
        destination = _mount_name(mount.get("Destination"))
        if destination in by_destination:
            raise RuntimeError(f"{role}:DUPLICATE_MOUNT:{destination}")
        if destination not in expected_destinations and not (destination == "/tmp" and tmpfs_declared):
            raise RuntimeError(f"{role}:UNAPPROVED_MOUNT:{destination}")
        if "docker.sock" in str(mount.get("Source", "")).casefold():
            raise RuntimeError(f"{role}:DOCKER_SOCKET_MOUNT")
        by_destination[destination] = mount
    if not expected_destinations.issubset(by_destination):
        raise RuntimeError(f"{role}:MOUNT_SET_MISMATCH:{sorted(expected_destinations - set(by_destination))}")
    if "/tmp" in by_destination:
        tmpfs = by_destination["/tmp"]
        if tmpfs.get("Type") != "tmpfs" or tmpfs.get("RW") is not True:
            raise RuntimeError(f"{role}:TMPFS_MOUNT_INVALID")
    declared = (obj.get("Config") or {}).get("Volumes") or {}
    if not isinstance(declared, dict) or set(declared) - expected_destinations:
        raise RuntimeError(f"{role}:IMAGE_DECLARES_EXTRA_VOLUMES")
    return by_destination


def _bind(mount: dict, source: str, writable: bool, role: str, dest: str) -> None:
    if mount.get("Type") != "bind" or mount.get("RW") is not writable:
        raise RuntimeError(f"{role}:BIND_MODE_MISMATCH:{dest}")
    if _host_key(mount.get("Source")) != _host_key(source):
        raise RuntimeError(f"{role}:BIND_SOURCE_MISMATCH:{dest}")


def _ipc_identity(mount: dict, approved_ipc_source: str | None,
                  approved_ipc_name: str | None, role: str,
                  ipc_mount: str) -> tuple[str, str]:
    if mount.get("RW") is not True:
        raise RuntimeError(f"{role}:IPC_NOT_WRITABLE")
    kind = mount.get("Type")
    if kind == "bind":
        if approved_ipc_source is None or approved_ipc_name is not None:
            raise RuntimeError(f"{role}:IPC_BIND_NOT_APPROVED")
        _bind(mount, approved_ipc_source, True, role, ipc_mount)
        return "bind", _host_key(mount["Source"])
    if kind == "volume":
        name = mount.get("Name")
        if approved_ipc_name is None or approved_ipc_source is not None or name != approved_ipc_name:
            raise RuntimeError(f"{role}:IPC_VOLUME_NOT_APPROVED")
        if not isinstance(name, str) or not name:
            raise RuntimeError(f"{role}:IPC_VOLUME_ANONYMOUS")
        return "volume", f"{name}|{_host_key(mount.get('Source'))}"
    raise RuntimeError(f"{role}:IPC_MOUNT_TYPE")


def verify_runtime_gate(
    decision_inspect_path: str | Path,
    execution_inspect_path: str | Path,
    *,
    r1_root: str | Path,
    expected_image_id: str,
    expected_decision_cmd: list[str],
    expected_execution_cmd: list[str],
    approved_test_source: str,
    approved_out_source: str,
    approved_ipc_source: str | None = None,
    approved_ipc_name: str | None = None,
    test_mount: str = "/test",
    ipc_mount: str = "/ipc",
    out_mount: str = "/out",
) -> dict:
    """Raise on an unexpected actual mount or runtime setting; return proof IDs.

    Exactly one of ``approved_ipc_source`` (private bind) and
    ``approved_ipc_name`` (named Docker volume) must be supplied. All approved
    sources and the pinned image ID must come from the frozen launch manifest.
    This checks mount identity, not the file hashes or dataset contents.
    """
    if not _IMAGE_ID.fullmatch(expected_image_id):
        raise RuntimeError("EXPECTED_IMAGE_ID_INVALID")
    _expected_commands(expected_decision_cmd, expected_execution_cmd)
    if (approved_ipc_source is None) == (approved_ipc_name is None):
        raise RuntimeError("IPC_APPROVAL_REQUIRED")
    destinations = [_mount_name(v) for v in (test_mount, ipc_mount, out_mount)]
    if len(set(destinations + ["/bundle", "/worker"])) != 5:
        raise RuntimeError("MOUNT_DESTINATION_COLLISION")
    test_mount, ipc_mount, out_mount = destinations
    decision_bundle_source = _host_child(r1_root, "test_handoff", "decision_bundle")
    execution_bundle_source = _host_child(r1_root, "restricted_run_20260926_01", "run")
    worker_source = _host_child(r1_root, "test_handoff")
    if any(_sources_overlap(approved_out_source, other) for other in
           (approved_test_source, decision_bundle_source, execution_bundle_source,
            worker_source)):
        raise RuntimeError("OUTPUT_SOURCE_OVERLAPS_READABLE_INPUT")
    if any(_sources_overlap(approved_test_source, other) for other in
           (decision_bundle_source, execution_bundle_source, worker_source)):
        raise RuntimeError("TEST_SOURCE_OVERLAPS_CODE_MOUNT")
    if approved_ipc_source is not None and any(
        _sources_overlap(approved_ipc_source, other) for other in
        (approved_test_source, approved_out_source, decision_bundle_source,
         execution_bundle_source, worker_source)
    ):
        raise RuntimeError("IPC_SOURCE_OVERLAPS_OTHER_MOUNT")
    decision, decision_sha = _inspect(Path(decision_inspect_path))
    execution, execution_sha = _inspect(Path(execution_inspect_path))
    if decision["Id"] == execution["Id"]:
        raise RuntimeError("DECISION_AND_EXECUTION_SAME_CONTAINER")
    for role, obj in (("decision", decision), ("execution", execution)):
        _security(obj, expected_image_id, role)
        _process(obj, expected_decision_cmd if role == "decision" else expected_execution_cmd, role)
        allowed = {"/bundle", "/worker", ipc_mount}
        if role == "execution":
            allowed |= {test_mount, out_mount}
        mounts = _mounts(obj, allowed, role)
        bundle_source = decision_bundle_source if role == "decision" else execution_bundle_source
        _bind(mounts["/bundle"], bundle_source, False, role, "/bundle")
        _bind(mounts["/worker"], worker_source, False, role, "/worker")
        if role == "execution":
            _bind(mounts[test_mount], approved_test_source, False, role, test_mount)
            _bind(mounts[out_mount], approved_out_source, True, role, out_mount)
        identity = _ipc_identity(mounts[ipc_mount], approved_ipc_source,
                                 approved_ipc_name, role, ipc_mount)
        if role == "decision":
            decision_ipc = identity
        elif identity != decision_ipc:
            raise RuntimeError("IPC_SOURCE_NOT_SHARED")
    return {
        "decision_container_id": decision["Id"],
        "execution_container_id": execution["Id"],
        "decision_inspect_sha256": decision_sha,
        "execution_inspect_sha256": execution_sha,
        "image_id": expected_image_id,
        "ipc_identity": list(decision_ipc),
        "test_mount": test_mount,
        "out_mount": out_mount,
    }
