"""Fail-closed runtime probe; never opens or reads excluded market roots."""
from __future__ import annotations

import os
import platform
import shutil
import socket
from pathlib import Path


def main() -> None:
    if platform.system() != "Linux":
        raise RuntimeError("LINUX_CONTAINER_REQUIRED")
    bundle = Path("/bundle")
    output = Path("/out")
    if not bundle.is_dir() or not output.is_dir():
        raise RuntimeError("EXPECTED_MOUNTS_ABSENT")
    if not (os.statvfs(bundle).f_flag & os.ST_RDONLY):
        raise RuntimeError("BUNDLE_MUST_BE_READ_ONLY")
    mountinfo = Path("/proc/self/mountinfo").read_text()
    mount_points = {line.split()[4] for line in mountinfo.splitlines()}
    if "/bundle" not in mount_points or "/out" not in mount_points:
        raise RuntimeError("BUNDLE_OUTPUT_NOT_DISTINCT_MOUNTS")
    exact_allowed = {"/", "/bundle", "/out", "/tmp", "/etc/hosts", "/etc/hostname",
                     "/etc/resolv.conf"}
    prefix_allowed = ("/proc", "/sys", "/dev")
    for point in mount_points:
        if point not in exact_allowed and not any(point == prefix or point.startswith(prefix + "/")
                                                   for prefix in prefix_allowed):
            raise RuntimeError(f"UNEXPECTED_RUNTIME_MOUNT:{point}")
    forbidden = ("/mnt/c", "/mnt/d", "/host", "/host_mnt", "/run/desktop/mnt/host/c",
                 "/run/desktop/mnt/host/d", "/proc/1/root/mnt/c", "/proc/1/root/mnt/d")
    for candidate in forbidden:
        if Path(candidate).exists() or Path(candidate).is_symlink():
            raise RuntimeError(f"HOST_ALIAS_VISIBLE:{candidate}")
    for candidate in (bundle, output):
        resolved = candidate.resolve(strict=True)
        if resolved not in (bundle, output):
            raise RuntimeError(f"UNEXPECTED_MOUNT_ALIAS:{candidate}")
    for executable in ("docker", "podman", "wsl", "powershell", "pwsh", "cmd.exe"):
        if shutil.which(executable):
            raise RuntimeError(f"HOST_ESCAPE_TOOL_VISIBLE:{executable}")
    # No data request is sent. A successful connect means an outbound channel exists.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect(("1.1.1.1", 80))
    except OSError:
        pass
    else:
        raise RuntimeError("OUTBOUND_NETWORK_AVAILABLE")
    finally:
        sock.close()
    print("R1_ISOLATION_PROBE_PASS", flush=True)


if __name__ == "__main__":
    main()
