from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("harness_preflight.py")
SPEC = importlib.util.spec_from_file_location("harness_preflight", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


@pytest.fixture
def isolated_repository():
    # Reuse test_harness_task's external ordinary-mkdir fixture pattern; retain
    # inherited permissions without pytest's Windows mode=0700 directory setup.
    parent = Path(tempfile.gettempdir()).resolve()
    root = (parent / f"preflight-{uuid.uuid4().hex}").resolve()
    root.mkdir()
    assert root.parent == parent
    # Retained task-cache fixture: this governance validation performs no cleanup.
    yield root


def test_training_boundary_is_strictly_pre2026() -> None:
    module.assert_training_before_cutoff(["2025-12-31", "2025-12-31T23:59:59"])
    with pytest.raises(module.ResearchBoundaryError, match="TRAINING_TIMESTAMP_NOT_PRE2026"):
        module.assert_training_before_cutoff(["2026-01-01"])


def test_pit_order_rejects_future_information() -> None:
    module.assert_pit_order([("2025-01-01T15:00:00", "2025-01-01T16:00:00")])
    with pytest.raises(module.ResearchBoundaryError, match="PIT_INFORMATION_AFTER_DECISION"):
        module.assert_pit_order([("2025-01-02", "2025-01-01")])


def test_changed_literal_scanner_blocks_train_end_but_allows_exclusive_cutoff() -> None:
    safe = module._boundary_literal_violations("safe.py", 'TRAINING_CUTOFF = "2026-01-01"\n')
    bad = module._boundary_literal_violations("bad.py", 'TRAIN_END_DATE = "2026-01-02"\n')
    assert not safe
    assert bad == ["bad.py:1:2026-01-02"]


def test_exposed_holdout_is_scoped_hard_blocker() -> None:
    row = module._holdout_status_finding(
        "FAIL_CLOSED_PRIOR_2026_OUTCOME_EXPOSURE_PRECEDES_CONTRACT"
    )
    assert row["level"] == "HARD_BLOCKER"
    assert row["blocks"] == ["2026-optimization"]


def test_registry_2026_training_flag_fails_closed() -> None:
    registry = {
        "governance": {"auto_promotion_forbidden": True, "requires_explicit_user_authorization": True},
        "models": [{
            "model_id": "BAD", "training_cutoff": "PRE2026", "uses_2026_training": True,
            "uses_2026_parameter_search": False, "uses_2026_model_selection": False,
        }],
    }
    rows = module._registry_semantic_findings(Path("alpha_registry.json"), registry)
    assert any(row["code"] == "RESEARCH_REGISTRY_2026_REUSE" for row in rows)



def test_default_scope_does_not_apply_2026_optimization_blocker(monkeypatch) -> None:
    monkeypatch.setattr(module, "_git_paths", lambda repo: ([], []))
    monkeypatch.setattr(module, "_anti_bloat_findings", lambda repo: [])
    default = module.run_preflight(Path.cwd(), "independent-code")
    optimization = module.run_preflight(Path.cwd(), "2026-optimization")
    assert default["preflight_status"] == "PASS_WITH_SCOPED_HARD_BLOCKERS"
    assert default["applicable_hard_blocker_count"] == 0
    assert optimization["preflight_status"] == "HARD_BLOCKER"
    assert optimization["applicable_hard_blocker_count"] == 1


@pytest.mark.parametrize("scope", ["independent-code", "historical-fetch", "2026-optimization"])
def test_unrelated_scope_never_opens_research_content(isolated_repository, monkeypatch, scope) -> None:
    # Exclusively synthetic sentinels. Intercept the actual Path.open used by
    # registry JSON, model hashing, and changed-file scanning.
    protected = [
        isolated_repository / "config/research_governance/alpha_registry.json",
        isolated_repository / "results/mixed_years.json",
        isolated_repository / "models/model.bin",
        isolated_repository / "results/A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT/status.json",
    ]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"synthetic_2025": 0, "synthetic_2026": 1}', encoding="utf-8")
    opened = []
    original_open = Path.open

    def checked_open(path, *args, **kwargs):
        opened.append(path)
        if path in protected:
            raise AssertionError(f"FORBIDDEN_CONTENT_READ:{path.name}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked_open)
    monkeypatch.setattr(module, "_git_paths", lambda repo: (["synthetic dirty file"], protected))
    # Anti-bloat has separate tests. Exercise real research/scanner dispatch.
    monkeypatch.setattr(module, "_anti_bloat_findings", lambda repo: [])
    result = module.run_preflight(isolated_repository, scope)
    assert not set(opened).intersection(protected)
    assert any(row["code"] == "RESEARCH_CONTENT_CHECKS_NOT_CHECKED" for row in result["findings"])
    assert result["applicable_hard_blocker_count"] == int(scope == "2026-optimization")


def test_pre2026_synthetic_request_and_2026_date_test_are_not_keyword_blocked(isolated_repository, monkeypatch) -> None:
    source = isolated_repository / "model_training_pre2026.py"
    source.write_text(
        'TRAINING_CUTOFF = "2026-01-01"\n# model/train/2026 are not a denial rule\n',
        encoding="utf-8",
    )
    synthetic_test = isolated_repository / "test_2026_dates.py"
    synthetic_test.write_text('TRAIN_END_DATE = "2026-01-02"\n', encoding="utf-8")
    monkeypatch.setattr(module, "_git_paths", lambda repo: ([], [source, synthetic_test]))
    monkeypatch.setattr(module, "_anti_bloat_findings", lambda repo: [])
    result = module.run_preflight(isolated_repository, "pre2026-research")
    assert result["applicable_hard_blocker_count"] == 0
    module.assert_training_before_cutoff(["2025-12-31T23:59:59"])
    module.assert_pit_order([("2026-01-01", "2026-01-02")])


@pytest.mark.parametrize("flag", ["uses_2026_parameter_search", "uses_2026_model_selection"])
def test_registry_rejects_2026_selection_even_when_final_fit_is_pre2026(flag) -> None:
    model = {
        "model_id": "synthetic", "training_cutoff": "PRE2026",
        "uses_2026_training": False, "uses_2026_parameter_search": False,
        "uses_2026_model_selection": False,
    }
    model[flag] = True
    rows = module._registry_semantic_findings(Path("synthetic.json"), {
        "governance": {"auto_promotion_forbidden": True, "requires_explicit_user_authorization": True},
        "models": [model],
    })
    assert any(row["code"] == "RESEARCH_REGISTRY_2026_REUSE" for row in rows)


def test_label_maturity_and_information_availability_boundaries() -> None:
    with pytest.raises(module.ResearchBoundaryError, match="TRAINING_TIMESTAMP_NOT_PRE2026"):
        module.assert_training_before_cutoff(["2025-12-30", "2026-01-02"])
    # Explicit timestamps represent maturity/disclosure/mapping availability.
    # These helper checks do not establish full pipeline lineage or row filters.
    with pytest.raises(module.ResearchBoundaryError, match="PIT_INFORMATION_AFTER_DECISION"):
        module.assert_pit_order([("2025-07-01", "2025-06-30")])
    with pytest.raises(module.ResearchBoundaryError, match="PIT_INFORMATION_AFTER_DECISION"):
        module.assert_pit_order([("2026-01-01", "2025-01-01")])
    with pytest.raises(ValueError):
        module.assert_pit_order([(None, "2025-01-01")])


def test_frozen_asset_raw_bytes_are_checked_without_rewriting(isolated_repository) -> None:
    import hashlib
    import json

    asset = isolated_repository / "synthetic_model.bin"
    original = b"synthetic frozen bytes\r\n"
    expected = hashlib.sha256(original).hexdigest()
    asset.write_bytes(original)
    registry = isolated_repository / "config/research_governance/alpha_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({
        "governance": {"auto_promotion_forbidden": True, "requires_explicit_user_authorization": True},
        "models": [{
            "model_id": "synthetic", "training_cutoff": "PRE2026",
            "uses_2026_training": False, "uses_2026_parameter_search": False,
            "uses_2026_model_selection": False, "model_artifact": str(asset),
            "model_sha256": expected,
        }],
    }), encoding="utf-8")
    assert not any(row["level"] == "HARD_BLOCKER" for row in module._contract_findings(isolated_repository))
    assert asset.read_bytes() == original
    changed = original.replace(b"\r\n", b"\n")
    asset.write_bytes(changed)
    rows = module._contract_findings(isolated_repository)
    assert any(row["code"] == "FROZEN_ASSET_HASH_MISMATCH" for row in rows)
    assert asset.read_bytes() == changed
    assert json.loads(registry.read_text(encoding="utf-8"))["models"][0]["model_sha256"] == expected


def test_scope_name_must_be_known() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_TASK_SCOPE"):
        module.run_preflight(Path.cwd(), "typo")


# A subprocess audit hook observes real entrypoint I/O, including reads made by
# importlib and Path; no production reader, Git helper, or guard is mocked.
ENTRY_PROBE = r"""
import hashlib, importlib.util, json, os, runpy, shlex, sys
from pathlib import Path
root, state, entry, scope, protected_json = sys.argv[1:]
root, state = Path(root).resolve(), Path(state).resolve()
protected = {Path(value).resolve() for value in json.loads(protected_json)}
allowed = (root.parent, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())
opened, denied = [], []
harness_guard = None
source = root / 'scripts/maintenance/harness_preflight.py'
source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
harness_sha = hashlib.sha256((root / 'scripts/maintenance/harness_task.py').read_bytes()).hexdigest()
guard_sha = hashlib.sha256((root / 'fast3/scripts/audit/run_fast3_guard.py').read_bytes()).hexdigest()
def audit(event, args):
    if event == 'open' and not isinstance(args[0], int):
        path = Path(args[0]).resolve()
        assert not args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND), 'WRITE_FORBIDDEN'
        if path in protected or not any(path == base or base in path.parents for base in allowed):
            denied.append(str(path))
            raise PermissionError('BEFORE_READ_DENIED:' + str(path))
        if root.parent in path.parents:
            opened.append(path.relative_to(root.parent).as_posix())
    elif event == 'subprocess.Popen':
        command = shlex.split(args[1], posix=False) if isinstance(args[1], str) else args[1]
        assert Path(command[0]).name.lower() in {'git', 'git.exe'}, command
        assert command[1] in {'status', 'diff', 'ls-files', 'check-ignore'}, command
        assert Path(args[2]).resolve() == root, args[2]
    elif event.startswith('socket.'):
        raise AssertionError('NETWORK_FORBIDDEN')
sys.addaudithook(audit)
code = 0
try:
    if entry == 'main':
        sys.argv = [str(source), '--task-scope', scope, '--json']
        runpy.run_path(str(source), run_name='__main__')
    else:
        os.environ['USTQ_HARNESS_STATE_ROOT'] = str(state)
        path = root / 'scripts/maintenance/harness_task.py'
        spec = importlib.util.spec_from_file_location('isolated_harness', path)
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        if entry == 'harness-contract':
            saved = json.loads((state / 'tasks/synthetic-task/state.json').read_text(encoding='utf-8'))
            contract = harness._task_contract(saved['GOAL'], saved['TASK_KIND'], scope)
            assert contract['TASK_SCOPE'] == saved['TASK_SCOPE']
        result = harness._run_preflight_for('synthetic-task', root)
        harness_guard = result['overfit']
        print(json.dumps(result['result']))
        code = 2 if result['task_blocker_count'] else 0
except SystemExit as exc:
    code = int(exc.code or 0)
except Exception as exc:
    print(type(exc).__name__ + ':' + str(exc))
    code = 97
finally:
    print('ENTRY_AUDIT=' + json.dumps({'opened': opened, 'denied': denied, 'source_sha256': source_sha, 'harness_sha256': harness_sha, 'guard_sha256': guard_sha, 'harness_guard': harness_guard}))
sys.exit(code)
"""


def _entry_fixture(root: Path, scope: str, *, source_bytes: bytes | None = None, goal: str = "Synthetic scope probe"):
    # This source-only override makes the proposed cached test runnable before
    # integration. An integrated test uses its normal repository-relative source.
    source_root = Path(os.environ.get("USTQ_PREFLIGHT_TEST_SOURCE_ROOT", MODULE_PATH.parents[2]))
    repo, state = root / "repo", root / "state"
    target = repo / "scripts/maintenance/harness_preflight.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(source_bytes if source_bytes is not None else MODULE_PATH.read_bytes())
    for relative in (
        "scripts/maintenance/harness_task.py",
        "fast3/scripts/audit/run_fast3_guard.py",
        "fast3/scripts/audit/anti_bloat_semantics.py",
    ):
        dest = repo / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        origin = source_root / relative
        if relative == "scripts/maintenance/harness_task.py":
            origin = Path(os.environ.get("USTQ_PREFLIGHT_TEST_HARNESS_SOURCE", origin))
        dest.write_bytes(origin.read_bytes())
    baseline = json.dumps({
        "schema_version": "ANTI_BLOAT_FROZEN_LEGACY_BASELINE_V1", "entries": [],
        "membership_set_sha256": hashlib.sha256(b"").hexdigest(),
    }).encode("utf-8")
    manifest = repo / "fast3/docs/governance/anti_bloat_frozen_legacy_baseline.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(baseline)
    policy = (source_root / "configs/anti_bloat_policy.toml").read_text(encoding="utf-8")
    import re
    policy, count = re.subn(r'manifest_sha256 = "[a-f0-9]+"',
                           f'manifest_sha256 = "{hashlib.sha256(baseline).hexdigest()}"', policy)
    assert count == 1
    (repo / "configs").mkdir()
    (repo / "configs/anti_bloat_policy.toml").write_text(policy, encoding="utf-8")
    model = root / "models/synthetic.bin"
    model.parent.mkdir()
    model.write_bytes(b"SYNTHETIC_MODEL_ONLY")
    registry = repo / "config/research_governance/alpha_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({
        "governance": {"auto_promotion_forbidden": True, "requires_explicit_user_authorization": True},
        "models": [{"model_id": "synthetic", "training_cutoff": "PRE2026",
                    "uses_2026_training": False, "uses_2026_parameter_search": False,
                    "uses_2026_model_selection": False, "model_artifact": str(model),
                    "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest()}],
    }), encoding="utf-8")
    mixed = repo / "results/mixed_years.json"
    mixed.parent.mkdir()
    mixed.write_text('{"synthetic_2025": 0, "synthetic_2026": 1}', encoding="utf-8")
    status = root / "results/A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT/status.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT_STATUS":
                                 "FAIL_CLOSED_PRIOR_2026_OUTCOME_EXPOSURE_PRECEDES_CONTRACT"}), encoding="utf-8")
    (repo / "config/storage_paths.json").write_text(json.dumps({"results_root": str(root / "results")}), encoding="utf-8")
    task = state / "tasks/synthetic-task/state.json"
    task.parent.mkdir(parents=True)
    task.write_text(json.dumps({"TASK_ID": "synthetic-task", "HARNESS_STATE": "RUNNING", "TASK_SCOPE": scope,
                                "TASK_KIND": "maintenance", "GOAL": goal}), encoding="utf-8")
    environment = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0")
    subprocess.run(["git", "init", "--quiet", "--template=", str(repo)], env=environment, check=True, capture_output=True)
    subprocess.run([
        "git", "-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid",
        "commit", "--quiet", "--allow-empty", "--no-gpg-sign", "-m", "Synthetic preflight fixture",
    ], cwd=repo, env=environment, check=True, capture_output=True)
    return repo, state, [registry, model, mixed, status], environment


def _run_entry(fixture, entry: str, scope: str, *, protect: bool = True, protected_paths=None):
    repo, state, protected, environment = fixture
    selected = protected_paths if protected_paths is not None else protected if protect else []
    result = subprocess.run([
        sys.executable, "-B", "-c", ENTRY_PROBE, str(repo), str(state), entry, scope,
        json.dumps([str(path) for path in selected]),
    ], cwd=repo, env=environment, text=True, capture_output=True, timeout=30)
    assert "ENTRY_AUDIT=" in result.stdout, result.stderr
    body, audit_text = result.stdout.rsplit("ENTRY_AUDIT=", 1)
    audit = json.loads(audit_text)
    expected = hashlib.sha256((repo / "scripts/maintenance/harness_preflight.py").read_bytes()).hexdigest()
    assert audit["source_sha256"] == expected
    return result, body, audit


@pytest.mark.parametrize("entry", ["main", "harness"])
def test_actual_git_metadata_failure_cannot_report_clean_or_pass(isolated_repository, entry) -> None:
    fixture = _entry_fixture(isolated_repository, "independent-code")
    fixture[3]["GIT_DIR"] = str(fixture[0] / "missing-synthetic-git-metadata")
    result, body, audit = _run_entry(fixture, entry, "independent-code")
    assert result.returncode != 0
    assert "CalledProcessError" in body
    assert audit["denied"] == []
    assert '"preflight_status"' not in body
    assert audit["harness_guard"] is None


@pytest.mark.parametrize("entry", ["main", "harness"])
@pytest.mark.parametrize("scope", ["independent-code", "historical-fetch", "2026-optimization", "typo"])
def test_actual_entrypoints_scope_before_content_read(isolated_repository, entry, scope) -> None:
    fixture = _entry_fixture(isolated_repository, scope)
    result, body, audit = _run_entry(fixture, entry, scope)
    assert audit["denied"] == [], (body, audit)
    if scope == "typo":
        assert result.returncode != 0
        assert "invalid choice" in result.stderr or "UNKNOWN_TASK_SCOPE" in body
        return
    assert result.returncode == (2 if scope == "2026-optimization" else 0), (body, result.stderr)
    parsed = json.loads(body)
    assert parsed["applicable_hard_blocker_count"] == int(scope == "2026-optimization")
    assert any(row["code"] == "RESEARCH_CONTENT_CHECKS_NOT_CHECKED" for row in parsed["findings"])
    assert any(row["code"] == "ANTI_BLOAT_BUDGET" and row["level"] == "PASS" for row in parsed["findings"])
    assert "repo/fast3/docs/governance/anti_bloat_frozen_legacy_baseline.json" in audit["opened"]
    if entry == "harness":
        assert audit["harness_guard"] == ("HARD_BLOCKER" if scope == "2026-optimization" else "NOT_CHECKED_FOR_SCOPE")


@pytest.mark.parametrize("goal", [
    "Update documentation for current command entrypoints.",
    "Maintain launch scripts; no real research or model training.",
    "Maintain launch scripts; do not perform research or train a model.",
])
def test_maintenance_contract_preserves_no_result_entry_boundary(isolated_repository, goal) -> None:
    fixture = _entry_fixture(isolated_repository, "independent-code", goal=goal)
    result, body, audit = _run_entry(fixture, "harness-contract", "independent-code")
    assert result.returncode == 0, (body, result.stderr)
    assert audit["denied"] == []
    assert audit["harness_guard"] == "NOT_CHECKED_FOR_SCOPE"


@pytest.mark.parametrize("goal,expected_scope", [
    ("No real research or model training, but train a model on pre-2026 data.", "pre2026-research"),
    ("Do not perform research or train a model, but evaluate the frozen model on 2026 holdout.", "2026-evaluation"),
])
def test_positive_research_clause_keeps_research_gate(isolated_repository, goal, expected_scope) -> None:
    fixture = _entry_fixture(isolated_repository, expected_scope, goal=goal)
    # Start classification from independent-code: the actual positive request
    # must raise scope, and a denied registry must then stop the real preflight.
    result, body, audit = _run_entry(fixture, "harness-contract", "independent-code")
    assert result.returncode != 0
    assert "BEFORE_READ_DENIED:" in body
    assert audit["denied"] == [str(fixture[2][0].resolve())]


@pytest.mark.parametrize("entry", ["main", "harness"])
@pytest.mark.parametrize("scope", ["pre2026-research", "frozen-dependent", "2026-evaluation", "all"])
def test_research_read_denial_never_becomes_a_pass(isolated_repository, entry, scope) -> None:
    fixture = _entry_fixture(isolated_repository, scope)
    result, body, audit = _run_entry(fixture, entry, scope)
    assert result.returncode != 0
    assert "BEFORE_READ_DENIED:" in body
    assert audit["denied"] == [str(fixture[2][0].resolve())]
    assert "RESEARCH_CONTRACTS" not in body


@pytest.mark.parametrize("entry", ["main", "harness"])
@pytest.mark.parametrize("scope", ["frozen-dependent", "2026-evaluation"])
@pytest.mark.parametrize("evidence", ["missing_registry", "empty_models", "unknown_artifacts", "missing_hash", "invalid_hash"])
def test_missing_frozen_contract_evidence_is_a_hard_blocker(isolated_repository, entry, scope, evidence) -> None:
    fixture = _entry_fixture(isolated_repository, scope)
    registry = fixture[2][0]
    payload = json.loads(registry.read_text(encoding="utf-8"))
    if evidence == "missing_registry":
        registry.unlink()  # Only this test's synthetic registry.
    else:
        if evidence == "empty_models":
            payload["models"] = []
        elif evidence == "unknown_artifacts":
            payload["models"][0].update(model_artifact="UNKNOWN", model_sha256="UNKNOWN")
        elif evidence == "missing_hash":
            payload["models"][0].pop("model_sha256")
        else:
            payload["models"][0]["model_sha256"] = "invalid-sha256"
        registry.write_text(json.dumps(payload), encoding="utf-8")
    # Read only the available contract metadata. Model/mixed-year/holdout bodies
    # remain poison pills even though the requested scope is frozen research.
    result, body, audit = _run_entry(fixture, entry, scope, protected_paths=fixture[2][1:])
    assert result.returncode == 2, (body, result.stderr)
    assert audit["denied"] == []
    assert any(row["code"] == "FROZEN_CONTRACT_EVIDENCE_MISSING" and row["level"] == "HARD_BLOCKER"
               for row in json.loads(body)["findings"])
    assert "models/synthetic.bin" not in audit["opened"]
    assert "repo/results/mixed_years.json" not in audit["opened"]
    assert not any("FROZEN_HOLDOUT" in path for path in audit["opened"])


@pytest.mark.parametrize("entry", ["main", "harness"])
@pytest.mark.parametrize("invalid_field,invalid_value,blocker", [
    ("model_sha256", "invalid-sha256", "FROZEN_ASSET_HASH_MISMATCH"),
    ("model_sha256", "", "FROZEN_ASSET_HASH_MISMATCH"),
    ("model_sha256", None, "FROZEN_ASSET_HASH_MISMATCH"),
    ("model_artifact", "", "FROZEN_ASSET_MISSING"),
    ("model_artifact", None, "FROZEN_ASSET_MISSING"),
])
def test_verified_config_cannot_mask_an_invalid_model_binding(
    isolated_repository, entry, invalid_field, invalid_value, blocker,
) -> None:
    fixture = _entry_fixture(isolated_repository, "frozen-dependent")
    registry = fixture[2][0]
    payload = json.loads(registry.read_text(encoding="utf-8"))
    config = fixture[0] / "config/synthetic_model_config.json"
    config.write_text('{"synthetic": true}', encoding="utf-8")
    payload["models"][0].update(
        config_artifact=str(config), config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
    )
    payload["models"][0][invalid_field] = invalid_value
    registry.write_text(json.dumps(payload), encoding="utf-8")
    result, body, audit = _run_entry(fixture, entry, "frozen-dependent", protected_paths=fixture[2][1:])
    assert result.returncode == 2, (body, result.stderr)
    assert audit["denied"] == []
    parsed = json.loads(body)
    assert parsed["preflight_status"] == "HARD_BLOCKER"
    assert any(row["code"] == blocker and row["level"] == "HARD_BLOCKER" for row in parsed["findings"])
    assert "repo/config/synthetic_model_config.json" in audit["opened"]
    assert "models/synthetic.bin" not in audit["opened"]
    assert "repo/results/mixed_years.json" not in audit["opened"]


@pytest.mark.parametrize("entry", ["main", "harness"])
def test_actual_research_entry_keeps_contract_and_frozen_checks(isolated_repository, entry) -> None:
    fixture = _entry_fixture(isolated_repository, "pre2026-research")
    result, body, audit = _run_entry(fixture, entry, "pre2026-research", protect=False)
    assert result.returncode == 0, (body, result.stderr)
    assert "repo/config/research_governance/alpha_registry.json" in audit["opened"]
    assert "models/synthetic.bin" in audit["opened"]
    # Synthetic exact-hash corruption must remain a scoped hard gate.
    fixture[2][1].write_bytes(b"SYNTHETIC_CHANGED_MODEL")
    state_path = fixture[1] / "tasks/synthetic-task/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["TASK_SCOPE"] = "frozen-dependent"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result, body, audit = _run_entry(fixture, entry, "frozen-dependent", protect=False)
    assert result.returncode == 2, (body, result.stderr)
    assert any(row["code"] == "FROZEN_ASSET_HASH_MISMATCH" for row in json.loads(body)["findings"])


@pytest.mark.parametrize("entry", ["main", "harness"])
def test_disabled_scope_guard_is_caught_before_content_read(isolated_repository, entry) -> None:
    source = MODULE_PATH.read_bytes()
    guard = b'if task_scope in {*RESEARCH_SCOPES, "all"} - {"2026-optimization"}:'
    assert source.count(guard) == 1
    mutant = source.replace(guard, b'if True:  # synthetic negative control only')
    fixture = _entry_fixture(isolated_repository, "independent-code", source_bytes=mutant)
    result, body, audit = _run_entry(fixture, entry, "independent-code")
    assert result.returncode == 97
    assert "BEFORE_READ_DENIED:" in body
    assert audit["denied"] == [str(fixture[2][0].resolve())]
