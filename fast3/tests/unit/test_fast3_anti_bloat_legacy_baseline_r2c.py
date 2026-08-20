from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUARD_PATH = ROOT / "fast3/scripts/audit/run_fast3_guard.py"
SPEC = importlib.util.spec_from_file_location("fast3_guard_r2c", GUARD_PATH)
guard = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(guard)
semantics = guard.scan_internal_result_writes.__globals__
apply_legacy_exceptions = semantics["apply_legacy_exceptions"]
load_legacy_baseline = semantics["load_legacy_baseline"]
baseline_membership_sha256 = semantics["baseline_membership_sha256"]
internal_result_write_findings = semantics["internal_result_write_findings"]


@pytest.fixture
def workdir(request):
    parent = Path(os.environ["ANTI_BLOAT_TEST_TMP"]).resolve()
    suffix = hashlib.sha256(request.node.nodeid.encode("utf-8")).hexdigest()[:12]
    directory = parent / f"case_{suffix}"
    assert parent in directory.parents
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline(path: Path, entries: list[dict]) -> Path:
    path.write_text(json.dumps({
        "schema_version": "ANTI_BLOAT_FROZEN_LEGACY_BASELINE_V1",
        "migration_id": "TEST",
        "registered_date": "2026-08-20",
        "membership_set_sha256": baseline_membership_sha256(entries),
        "entries": entries,
    }), encoding="utf-8")
    return path


def entry(relative: str, source: Path, rule: str) -> dict:
    return {
        "path": relative,
        "sha256": digest(source),
        "rule_id": rule,
        "violation_type": rule,
        "reason": "fixture",
        "dependency_evidence": "fixture",
        "downstream_exact_sha_dependency": False,
    }


def test_exact_path_sha_and_rule_pass_as_frozen_legacy_exception(workdir):
    repo = workdir / "repo"; source = repo / "fast3/legacy.py"
    source.parent.mkdir(parents=True); source.write_text("x = 1\n", encoding="utf-8")
    manifest = baseline(workdir / "baseline.json", [entry("fast3/legacy.py", source, "python_lines")])
    current, frozen, invalidated = apply_legacy_exceptions(
        [{"path": source, "rule_id": "python_lines"}], repo_root=repo, baseline_path=manifest,
    )
    assert not current and not invalidated
    assert frozen[0]["classification"] == "PASS_AS_FROZEN_LEGACY_EXCEPTION"


def test_same_path_changed_sha_fails_and_invalidates_exception(workdir):
    repo = workdir / "repo"; source = repo / "fast3/legacy.py"
    source.parent.mkdir(parents=True); source.write_text("x = 1\n", encoding="utf-8")
    manifest = baseline(workdir / "baseline.json", [entry("fast3/legacy.py", source, "python_lines")])
    source.write_text("x = 2\n", encoding="utf-8")
    current, frozen, invalidated = apply_legacy_exceptions(
        [{"path": source, "rule_id": "python_lines"}], repo_root=repo, baseline_path=manifest,
    )
    assert current and not frozen and invalidated[0]["legacy_exception_invalidated"] is True


def test_same_violation_copied_to_new_file_fails(workdir):
    repo = workdir / "repo"; original = repo / "fast3/legacy.py"
    original.parent.mkdir(parents=True); original.write_text("x = 1\n", encoding="utf-8")
    copied = repo / "fast3/copied.py"; shutil.copyfile(original, copied)
    manifest = baseline(workdir / "baseline.json", [entry("fast3/legacy.py", original, "python_lines")])
    current, frozen, _ = apply_legacy_exceptions(
        [{"path": copied, "rule_id": "python_lines"}], repo_root=repo, baseline_path=manifest,
    )
    assert current and not frozen
    assert current[0]["classification"] == "NEW_PATH_NOT_IN_BASELINE"


def test_new_file_in_same_grandfathered_directory_is_not_grandfathered(workdir):
    repo = workdir / "repo"; old = repo / "fast3/legacy.py"
    old.parent.mkdir(parents=True); old.write_text("x = 1\n", encoding="utf-8")
    new = repo / "fast3/new.py"; new.write_text("x = 1\n", encoding="utf-8")
    manifest = baseline(workdir / "baseline.json", [entry("fast3/legacy.py", old, "python_lines")])
    current, frozen, _ = apply_legacy_exceptions(
        [{"path": new, "rule_id": "python_lines"}], repo_root=repo, baseline_path=manifest,
    )
    assert not frozen and current[0]["classification"] == "NEW_PATH_NOT_IN_BASELINE"


def test_similarly_named_new_file_is_not_grandfathered(workdir):
    repo = workdir / "repo"; old = repo / "fast3/legacy_r1.py"
    old.parent.mkdir(parents=True); old.write_text("x = 1\n", encoding="utf-8")
    new = repo / "fast3/legacy_r2.py"; new.write_text("x = 1\n", encoding="utf-8")
    manifest = baseline(workdir / "baseline.json", [entry("fast3/legacy_r1.py", old, "python_lines")])
    current, frozen, _ = apply_legacy_exceptions(
        [{"path": new, "rule_id": "python_lines"}], repo_root=repo, baseline_path=manifest,
    )
    assert not frozen and current[0]["classification"] == "NEW_PATH_NOT_IN_BASELINE"


def test_new_forbidden_sys_path_fails(workdir):
    repo = workdir / "repo"; source = repo / "fast3/scripts/run/new.py"
    source.parent.mkdir(parents=True); source.write_text("import sys\nsys.path.insert(0, 'x')\n", encoding="utf-8")
    manifest = baseline(workdir / "baseline.json", [])
    result = guard.forbidden_patterns(targets=[source], repo_root=repo, baseline_path=manifest)
    assert result["sys_path_hack_count"] == 1
    assert result["violations"] == ["sys_path:scripts/run/new.py"]


def test_new_line_budget_violation_fails(workdir):
    repo = workdir / "repo"; fast = repo / "fast3"
    config = fast / "configs/runtime"; config.mkdir(parents=True)
    shutil.copy(ROOT / "fast3/configs/runtime/FAST3_ANTI_BLOAT_LIMITS.json", config / "FAST3_ANTI_BLOAT_LIMITS.json")
    source = fast / "new_large.py"; source.write_text("\n".join(f"x{i} = {i}" for i in range(601)), encoding="utf-8")
    manifest = baseline(workdir / "baseline.json", [])
    result = guard.bloat(fast, repo_root=repo, baseline_path=manifest)
    assert result["current_python_line_violation_count"] == 1
    assert "python_lines:new_large.py" in result["violations"]


@pytest.mark.parametrize("statement", [
    "target.write_text('x')",
    "target.write_bytes(b'x')",
    "target.mkdir(parents=True)",
    "os.mkdir(target)",
    "target.touch()",
    "open(target, 'w').write('x')",
    "frame.to_csv(target)",
    "np.save(target, values)",
    "shutil.copy(source, target)",
])
def test_actual_internal_result_writes_fail(workdir, statement):
    source = workdir / "write_case.py"
    source.write_text(
        "from pathlib import Path\nimport numpy as np\nimport os\nimport shutil\n"
        "REPO = Path('repo')\ntarget = REPO / '.local_results' / 'out'\n" + statement + "\n",
        encoding="utf-8",
    )
    findings = internal_result_write_findings(source)
    assert findings, statement


def test_read_only_local_results_access_passes(workdir):
    source = workdir / "read_case.py"
    source.write_text(
        "from pathlib import Path\nREPO = Path('repo')\n"
        "exists = (REPO / '.local_results').exists()\n"
        "matches = list(REPO.rglob('.local_results'))\n"
        "text = (REPO / '.local_results' / 'status.txt').read_text()\n",
        encoding="utf-8",
    )
    assert internal_result_write_findings(source) == []


@pytest.mark.parametrize("bad_path", ["fast3/*.py", "fast3/scripts/../run/a.py", "/fast3/a.py", "fast3\\a.py"])
def test_path_only_wildcard_or_noncanonical_legacy_entry_is_rejected(workdir, bad_path):
    manifest = baseline(workdir / "baseline.json", [{
        "path": bad_path, "sha256": "0" * 64, "rule_id": "python_lines",
    }])
    with pytest.raises(ValueError):
        load_legacy_baseline(manifest)


def test_repository_legacy_baseline_is_exact_sha_locked():
    result = guard.frozen_legacy_baseline()
    assert not result["violations"]
    assert result["registered_count"] == result["valid_exact_sha_count"] == 30
    assert result["invalidated_count"] == 0
    assert result["path_only_whitelist_count"] == 0
    assert result["directory_whitelist_count"] == 0
    assert result["wildcard_exception_count"] == 0
    assert result["legacy_exception_sha_locked"] is True
    assert result["baseline_membership_locked"] is True
    assert result["expected_manifest_sha256"] == result["actual_manifest_sha256"]
