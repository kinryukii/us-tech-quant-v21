from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_241_daily_chain_retention_guard_integration.py")
SPEC = importlib.util.spec_from_file_location("v21_241_stage", MODULE_PATH)
v241 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v241)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def args(tmp_path: Path, **overrides):
    repo = overrides.pop("repo_root", tmp_path / "repo")
    ns = Namespace(
        repo_root=repo,
        archive_root=tmp_path / "archive",
        cache_root=tmp_path / "cache",
        quarantine_root=tmp_path / "quarantine",
        output_dir=None,
        execute=overrides.pop("execute", False),
        dry_run=overrides.pop("dry_run", False),
        audit_only=overrides.pop("audit_only", False),
        discover_only=overrides.pop("discover_only", False),
        skip_daily_chain=overrides.pop("skip_daily_chain", True),
        daily_chain_command=overrides.pop("daily_chain_command", ""),
        daily_chain_wrapper=overrides.pop("daily_chain_wrapper", ""),
        retention_guard_mode=overrides.pop("retention_guard_mode", "discover_only"),
        retention_guard_ps1=overrides.pop("retention_guard_ps1", ""),
        retention_guard_python=overrides.pop("retention_guard_python", ""),
        retention_guard_allow_maintenance=overrides.pop("retention_guard_allow_maintenance", False),
        fail_on_retention_fail=overrides.pop("fail_on_retention_fail", False),
        warn_on_retention_warn=overrides.pop("warn_on_retention_warn", False),
        top_size=overrides.pop("top_size", 10),
    )
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def seed_v240(repo: Path, status: str = "PASS_V21_240_RETENTION_GUARD_OK") -> None:
    write(repo / "scripts" / "v21" / "v21_240_retention_policy_and_maintenance_guard.py", "# v240")
    write(repo / "scripts" / "v21" / "run_v21_240_retention_policy_and_maintenance_guard.ps1", "# v240")
    write(repo / "outputs" / "v21" / v241.V240_STAGE / "v21_240_summary.json", json.dumps({
        "final_status": status,
        "final_decision": "decision",
        "repo_budget_status": "OK",
        "archive_budget_status": "OK",
        "cache_budget_status": "OK",
        "quarantine_budget_status": "OK",
        "total_budget_status": "OK",
        "guard_violation_count": 0,
        "repo_large_file_warning_count": 1,
        "repo_large_file_hard_count": 0,
        "repo_unclassified_large_file_count": 0,
        "total_size_after_bytes": 1024,
    }))


class Runner:
    def __init__(self, code: int = 0):
        self.code = code
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        self.commands.append(command)
        return self.code


def test_discovers_v21_240_script_and_wrapper(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    summary = v241.run(args(tmp_path, repo_root=repo, discover_only=True))
    assert summary["final_status"] == v241.PASS_DISCOVERY
    readiness = (repo / v241.OUT_REL / "v21_241_integration_readiness_report.csv").read_text(encoding="utf-8")
    assert "v21_240_found,True" in readiness


def test_discovery_classifies_multiple_candidates_without_patching(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    write(repo / "scripts" / "v21" / "run_daily_moomoo_research_chain.ps1", "V21.199_R4 V21.197 daily research chain")
    write(repo / "scripts" / "v21" / "run_v21_180_some_chain.ps1", "stage chain")
    v241.run(args(tmp_path, repo_root=repo, discover_only=True))
    rows = (repo / v241.OUT_REL / "v21_241_discovered_daily_chain_candidates.csv").read_text(encoding="utf-8")
    assert "CURRENT_DAILY_CHAIN_CONFIRMED" in rows
    assert "False" in rows


def test_creates_hook_contract_json(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    v241.run(args(tmp_path, repo_root=repo, discover_only=True))
    payload = json.loads((repo / v241.OUT_REL / "v21_241_daily_chain_hook_contract.json").read_text(encoding="utf-8"))
    assert payload["when_to_run"] == "after_daily_research_chain"


def test_standalone_ps1_wrapper_exists():
    assert Path("scripts/v21/run_v21_241_daily_chain_with_retention_guard.ps1").exists()


def test_post_run_audit_builds_audit_only_child_command_without_maintenance_flags(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    runner = Runner()
    v241.run(args(tmp_path, repo_root=repo, execute=True, retention_guard_mode="post_run_audit"), runner=runner)
    cmd = " ".join(runner.commands[0])
    assert "-AuditOnly" in cmd
    assert "-AllowArchiveCompress" not in cmd


def test_post_run_maintenance_requires_explicit_allow_and_execute(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    summary = v241.run(args(tmp_path, repo_root=repo, execute=False, retention_guard_mode="post_run_maintenance"))
    assert summary["retention_guard_child_attempted"] is False
    assert summary["skipped_count"] == 1


def test_v240_pass_maps_to_v241_pass(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo, "PASS_V21_240_RETENTION_GUARD_OK")
    summary = v241.run(args(tmp_path, repo_root=repo, execute=True, retention_guard_mode="post_run_audit"), runner=Runner())
    assert summary["guard_result"] == "PASS"
    assert summary["final_status"] == v241.PASS_READY


def test_v240_warn_maps_to_warn_and_blocks_adoption(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo, "WARN_V21_240_RETENTION_GUARD_WARN_BUDGET")
    summary = v241.run(args(tmp_path, repo_root=repo, execute=True, retention_guard_mode="post_run_audit", warn_on_retention_warn=True), runner=Runner())
    assert summary["guard_result"] == "WARN"
    assert summary["final_status"] == v241.WARN_GUARD_REVIEW
    assert summary["retention_guard_blocks_official_adoption"] is True


def test_v240_fail_maps_to_fail_when_fail_on_retention_fail(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo, "FAIL_V21_240_RETENTION_GUARD_ERROR")
    summary = v241.run(args(tmp_path, repo_root=repo, execute=True, retention_guard_mode="post_run_audit", fail_on_retention_fail=True), runner=Runner())
    assert summary["guard_result"] == "FAIL"
    assert summary["final_status"] == v241.FAIL_GUARD


def test_daily_chain_nonzero_maps_fail_unless_skip(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    summary = v241.run(args(tmp_path, repo_root=repo, skip_daily_chain=False, daily_chain_command="exit 1", retention_guard_mode="disabled"), runner=Runner(1))
    assert summary["final_status"] == v241.FAIL_CHILD
    skipped = v241.run(args(tmp_path, repo_root=repo, skip_daily_chain=True, retention_guard_mode="disabled"), runner=Runner(1))
    assert skipped["final_status"] == v241.PASS_READY


def test_missing_v240_fails_in_post_run_audit(tmp_path):
    repo = tmp_path / "repo"
    summary = v241.run(args(tmp_path, repo_root=repo, execute=True, retention_guard_mode="post_run_audit"))
    assert summary["final_status"] == v241.FAIL_MISSING


def test_discover_only_succeeds_without_children(tmp_path):
    repo = tmp_path / "repo"
    summary = v241.run(args(tmp_path, repo_root=repo, discover_only=True), runner=Runner(1))
    assert summary["final_status"] == v241.PASS_DISCOVERY
    assert summary["retention_guard_child_attempted"] is False


def test_summary_always_blocks_broker_and_official_adoption(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    summary = v241.run(args(tmp_path, repo_root=repo, discover_only=True))
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False


def test_output_manifests_written(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    v241.run(args(tmp_path, repo_root=repo, discover_only=True))
    out = repo / v241.OUT_REL
    for name in [
        "v21_241_summary.json",
        "v21_241_discovered_daily_chain_candidates.csv",
        "v21_241_child_invocation_manifest.csv",
        "v21_241_retention_guard_status_mapping.csv",
        "v21_241_daily_chain_hook_contract.json",
        "v21_241_integration_readiness_report.csv",
        "v21_241_skipped_blockers.csv",
        "V21.241_daily_chain_retention_guard_integration_report.txt",
    ]:
        assert (out / name).exists()


def test_dry_run_does_not_mutate_external_roots(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    archive = tmp_path / "archive"
    marker = write(archive / "marker.txt", "keep")
    v241.run(args(tmp_path, repo_root=repo, dry_run=True, execute=False, retention_guard_mode="discover_only"))
    assert marker.exists()


def test_ambiguous_discovery_does_not_patch_active_wrapper(tmp_path):
    repo = tmp_path / "repo"
    seed_v240(repo)
    wrapper = write(repo / "scripts" / "v21" / "run_daily_chain_candidate.ps1", "possible")
    before = wrapper.read_text(encoding="utf-8")
    v241.run(args(tmp_path, repo_root=repo, discover_only=True))
    assert wrapper.read_text(encoding="utf-8") == before
