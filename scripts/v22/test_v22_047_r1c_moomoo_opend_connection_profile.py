from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
PROFILE_MODULE_PATH = HERE / "v22_047_r1c_moomoo_opend_connection_profile.py"
PATCH_MODULE_PATH = HERE / "patch_v22_047_r1c_repo_opend_port_defaults.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


profile_mod = load_module(PROFILE_MODULE_PATH, "v22_047_r1c_profile_test")
patch_mod = load_module(PATCH_MODULE_PATH, "v22_047_r1c_patch_test")


def write_profile(path: Path, **overrides):
    payload = {
        "schema_version": 1,
        "profile_name": "TEST",
        "host": "127.0.0.1",
        "port": 18441,
        "allow_remote_host": False,
        "tcp_timeout_seconds": 1.0,
        "quote_probe_symbols": ["US.QQQ", "US.IQQ", "US.TQQQ", "US.SQQQ"],
        "trade_unlock_required_for_data": False,
        "notes": "",
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_default_profile_loads(tmp_path: Path):
    path = tmp_path / "profile.json"
    write_profile(path)
    profile = profile_mod.load_profile(path, environ={})
    assert profile.host == "127.0.0.1"
    assert profile.port == 18441


def test_environment_override(tmp_path: Path):
    path = tmp_path / "profile.json"
    write_profile(path)
    profile = profile_mod.load_profile(
        path,
        environ={"MOOMOO_OPEND_HOST": "localhost", "MOOMOO_OPEND_PORT": "19000"},
    )
    assert profile.host == "localhost"
    assert profile.port == 19000


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
def test_remote_hosts_rejected(tmp_path: Path, host: str):
    path = tmp_path / "profile.json"
    write_profile(path, host=host)
    with pytest.raises(profile_mod.ProfileError, match="REMOTE_OPEND_HOST_BLOCKED"):
        profile_mod.load_profile(path, environ={})


def test_loopback_variants_accepted(tmp_path: Path):
    for host in ("127.0.0.1", "localhost", "::1"):
        path = tmp_path / f"{host.replace(':', '_')}.json"
        write_profile(path, host=host)
        assert profile_mod.load_profile(path, environ={}).host == host


def test_environment_map_contains_compatibility_keys(tmp_path: Path):
    path = tmp_path / "profile.json"
    write_profile(path)
    profile = profile_mod.load_profile(path, environ={})
    env = profile_mod.environment_map(profile)
    assert env["MOOMOO_OPEND_PORT"] == "18441"
    assert env["FUTU_PORT"] == "18441"
    assert env["OPEND_HOST"] == "127.0.0.1"


def test_patcher_only_scans_relevant_source(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "config").mkdir(parents=True)
    (repo / "scripts" / "moomoo_fetch.py").write_text(
        'from moomoo import OpenQuoteContext\nctx=OpenQuoteContext(host="127.0.0.1", port=11111)\n',
        encoding="utf-8",
    )
    (repo / "scripts" / "unrelated.py").write_text("value=11111\n", encoding="utf-8")
    rows = patch_mod.scan(repo, 11111, 18441)
    assert [row["path"] for row in rows] == ["scripts/moomoo_fetch.py"]


def test_patcher_applies_and_backs_up(tmp_path: Path):
    repo = tmp_path / "repo"
    source = repo / "scripts" / "v22" / "fetch.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'import moomoo\ndef run(host: str="127.0.0.1", port: int=11111): return port\n',
        encoding="utf-8",
    )
    rows = patch_mod.scan(repo, 11111, 18441)
    backup = repo / "backups" / "test"
    applied = patch_mod.apply_patch(repo, rows, 11111, 18441, backup)
    assert len(applied) == 1
    assert "18441" in source.read_text(encoding="utf-8")
    assert "11111" in (backup / "scripts" / "v22" / "fetch.py").read_text(encoding="utf-8")


def test_profile_never_requires_trade_unlock(tmp_path: Path):
    path = tmp_path / "profile.json"
    write_profile(path, trade_unlock_required_for_data=True)
    with pytest.raises(profile_mod.ProfileError, match="MUST_NOT_REQUIRE_TRADE_UNLOCK"):
        profile_mod.load_profile(path, environ={})


def test_patcher_excludes_tests_and_migration_tools(tmp_path: Path):
    repo = tmp_path / "repo"
    base = repo / "scripts" / "v22"
    base.mkdir(parents=True)
    (base / "test_fake_moomoo.py").write_text(
        'from moomoo import OpenQuoteContext\nport=11111\n', encoding="utf-8"
    )
    (base / "patch_v22_047_r1c_repo_opend_port_defaults.py").write_text(
        'moomoo old_port=11111\n', encoding="utf-8"
    )
    (base / "runtime_fetch.py").write_text(
        'from moomoo import OpenQuoteContext\nport=11111\n', encoding="utf-8"
    )
    rows = patch_mod.scan(repo, 11111, 18441)
    assert [row["path"] for row in rows] == ["scripts/v22/runtime_fetch.py"]
