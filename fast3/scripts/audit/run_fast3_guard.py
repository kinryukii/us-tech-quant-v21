"""FAST3 architecture, bloat, single-source, and forbidden-pattern guard."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import tomllib
from pathlib import Path

_SEMANTICS_PATH = Path(__file__).with_name("anti_bloat_semantics.py")
_SEMANTICS_SPEC = importlib.util.spec_from_file_location("fast3_anti_bloat_semantics", _SEMANTICS_PATH)
if _SEMANTICS_SPEC is None or _SEMANTICS_SPEC.loader is None:
    raise ImportError(f"cannot load Anti-Bloat semantics: {_SEMANTICS_PATH}")
_SEMANTICS = importlib.util.module_from_spec(_SEMANTICS_SPEC)
_SEMANTICS_SPEC.loader.exec_module(_SEMANTICS)
apply_legacy_exceptions = _SEMANTICS.apply_legacy_exceptions
legacy_baseline_status = _SEMANTICS.legacy_baseline_status
scan_internal_result_writes = _SEMANTICS.scan_internal_result_writes

REPO = Path(__file__).resolve().parents[3]
FAST = REPO / "fast3"
POLICY_PATH = REPO / "configs" / "anti_bloat_policy.toml"
ALLOWED_TOP = {"compatibility", "configs", "docs", "manifests", "scripts", "src", "state", "tests"}
EXTERNAL_RESULTS_ROOT = Path(r"D:\us-tech-quant-results\fast3")
EXTERNAL_DATA_ROOT = Path(r"D:\us-tech-quant-data\fast3")
APPROVED_RESULTS_VOLUME_ROOT = Path(r"D:\us-tech-quant-results")
APPROVED_DATA_VOLUME_ROOT = Path(r"D:\us-tech-quant-data")
LEGACY_LOCAL_RESULTS_TARGET = APPROVED_RESULTS_VOLUME_ROOT / "runtime" / "local_results"
LEGACY_LOGICAL_RESULTS_NAME = "." + "local_results"
RESULT_FILE_BUDGET = 8
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def _json(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def _toml(path: Path):
    with path.open("rb") as handle:
        return tomllib.load(handle)
def _hash(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_policy(policy_path: Path = POLICY_PATH) -> dict:
    """Load the single machine-readable repository governance source."""
    policy = _toml(policy_path)
    repository = dict(policy["repository"])
    repository["forbid_repo_local_venv"] = policy["forbid_repo_local_venv"]
    return repository


def legacy_policy(policy_path: Path = POLICY_PATH) -> dict:
    return dict(_toml(policy_path)["legacy_baseline"])


def legacy_baseline_path(policy_path: Path = POLICY_PATH, repo_root: Path = REPO) -> Path:
    return Path(repo_root) / legacy_policy(policy_path)["manifest"]


def _absolute_key(path: Path) -> str:
    """Return a case-normalized logical Windows path without resolving links."""
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


def _resolved_key(path: Path) -> str:
    """Resolve every link first, then compare a normalized case-insensitive path."""
    return _absolute_key(path.resolve(strict=True))


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((_resolved_key(path), _resolved_key(root))) == _resolved_key(root)
    except (OSError, ValueError):
        return False


def _lstat_reparse(path: Path):
    """Inspect an entry without following it; return (stat_result, is_reparse)."""
    item = os.lstat(path)
    attributes = getattr(item, "st_file_attributes", 0)
    return item, bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _iter_physical_files(root: Path, *, skip_directory=lambda _: False):
    """Yield regular files while never descending into a ReparsePoint directory."""
    if not os.path.lexists(root):
        return
    try:
        _, root_reparse = _lstat_reparse(root)
    except OSError:
        return
    if root_reparse:
        return
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        item, is_reparse = _lstat_reparse(path)
                    except OSError:
                        continue
                    if stat.S_ISDIR(item.st_mode):
                        # This check deliberately precedes adding the directory to pending.
                        if not is_reparse and entry.name != "__pycache__" and not skip_directory(path):
                            pending.append(path)
                    elif stat.S_ISREG(item.st_mode):
                        yield path
        except (OSError, PermissionError):
            continue


def _files(root=FAST):
    return list(_iter_physical_files(root))


def architecture():
    top = {p.name for p in FAST.iterdir() if p.is_dir()}
    bad = sorted(top - ALLOWED_TOP)
    allowed_root = {"FAST3.md", "run_fast3_overnight_autopilot.ps1", "start_codex_fast3_full_chain.ps1", "start_codex_v22_080a.ps1"}
    root_named_fast3 = [p.name for p in REPO.iterdir() if p.is_file() and "fast3" in p.name.lower() and not p.name.endswith(".bak") and p.name != "fast3_migration_worklog.md"]
    active_root = [name for name in allowed_root if (REPO / name).is_file()]
    allowed_codex = {"CODEX_GOAL.md", "CODEX_PLAN.md", "CODEX_STATUS.md"}
    root_codex = [p.name for p in REPO.iterdir() if p.is_file() and p.name.upper().startswith("CODEX_") and not p.name.endswith(".bak")]
    root_legacy = {"CODEX_AUTOPILOT_PROMPT.txt", "CODEX_RESUME_FULL_CHAIN_PROMPT.txt", "fast3_migration_worklog.md", "-tech-quant"}
    violations = [f"top:{x}" for x in bad] + [f"root:{x}" for x in root_named_fast3 if x not in allowed_root]
    violations += [f"root_codex:{x}" for x in root_codex if x not in allowed_codex]
    violations += [f"root_legacy:{x}" for x in root_legacy if (REPO / x).exists()]
    return {"name": "architecture", "violations": violations, "root_fast3_file_count": len(active_root)}


def bloat(root=FAST, *, repo_root=None, baseline_path=None):
    root = Path(root)
    repo_root = Path(repo_root) if repo_root is not None else (REPO if root == FAST else root)
    baseline_path = Path(baseline_path) if baseline_path is not None else legacy_baseline_path()
    limits = _json(root / "configs" / "runtime" / "FAST3_ANTI_BLOAT_LIMITS.json")
    forbidden_binary_suffixes = set(limits["forbidden_binary_suffixes"]) | {".bin"}
    big = [p.relative_to(root).as_posix() for p in _files(root) if p.suffix.lower() in forbidden_binary_suffixes and "legacy/" not in p.relative_to(root).as_posix()]
    big += [p.relative_to(root).as_posix() for p in _files(root) if p.suffix.lower() in {".csv", ".json"} and p.stat().st_size > limits["max_csv_json_bytes_outside_legacy"] and "legacy/" not in p.relative_to(root).as_posix()]
    oversized_findings = [
        {"path": p, "rule_id": "python_lines"} for p in _files(root)
        if p.suffix == ".py" and len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) > limits["single_python_file_line_budget"]
    ]
    oversized_current, frozen, invalidated = apply_legacy_exceptions(
        oversized_findings, repo_root=repo_root, baseline_path=baseline_path,
    )
    suffix = re.compile(r"FAST3[-_]\d{3}.*(?:_R\d+|_FINAL(?:\d+|_V\d+)|_PATCH(?:ED)?\d*|_V\d+)", re.I)
    forbidden = [p.relative_to(root).as_posix() for p in _files(root) if suffix.search(p.name) and "legacy/" not in p.relative_to(root).as_posix()]
    return {
        "name": "bloat",
        "violations": [f"large:{x}" for x in big]
        + [f"python_lines:{row['repository_relative_path'].removeprefix('fast3/')}" for row in oversized_current]
        + [f"suffix:{x}" for x in forbidden],
        "raw_python_line_violation_count": len(oversized_findings),
        "current_python_line_violation_count": len(oversized_current),
        "frozen_legacy_exception_count": len(frozen),
        "frozen_legacy_exceptions": frozen,
        "legacy_exception_invalidated_count": len(invalidated),
        "legacy_exception_invalidated": invalidated,
    }


def repository_budget(repo_root=REPO):
    """Enforce the physical main-worktree budget without hiding local content."""
    limits = repository_policy()
    allowlist = {Path(item).as_posix() for item in limits["large_file_allowlist"]}
    tracked = set(subprocess.run(
        ["git", "ls-files"], cwd=repo_root, text=True, capture_output=True, check=False
    ).stdout.splitlines())
    introduced = set(subprocess.run(
        ["git", "ls-files", "--others"],
        cwd=repo_root, text=True, capture_output=True, check=False,
    ).stdout.splitlines())
    introduced.update(subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", "HEAD"],
        cwd=repo_root, text=True, capture_output=True, check=False,
    ).stdout.splitlines())
    files = []
    access_errors = []
    def unreadable_row(path: Path, exc: OSError) -> dict:
        try:
            relative = path.relative_to(repo_root).as_posix()
        except ValueError:
            relative = str(path)
        tracked_status = relative in tracked
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", relative], cwd=repo_root,
            text=True, capture_output=True, check=False,
        ).returncode == 0
        parts = {part.lower() for part in Path(relative).parts}
        ephemeral = any(part == ".pytest_cache" or part.startswith(".pytest_") for part in parts)
        linked_worktree = relative.lower().startswith("_worktrees/")
        material = tracked_status or not (ignored and ephemeral)
        return {
            "path": str(path), "repository_relative_path": relative,
            "error": type(exc).__name__,
            "path_scope": "LINKED_WORKTREE_EPHEMERAL" if linked_worktree else "MAIN_WORKTREE",
            "tracked_status": tracked_status, "ignored_status": ignored,
            "material_to_repo_accounting": material,
        }
    pending = [Path(repo_root)]
    git_root = Path(repo_root) / ".git"
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if path == git_root:
                        continue
                    try:
                        item, is_reparse = _lstat_reparse(path)
                    except OSError as exc:
                        access_errors.append(unreadable_row(path, exc))
                        continue
                    if stat.S_ISDIR(item.st_mode):
                        if not is_reparse:
                            pending.append(path)
                    elif stat.S_ISREG(item.st_mode):
                        files.append((path, item.st_size))
        except (OSError, PermissionError) as exc:
            access_errors.append(unreadable_row(directory, exc))

    worktree_bytes = sum(size for _, size in files)
    git_database_bytes = sum(path.stat().st_size for path in _iter_physical_files(git_root))
    file_rows = [(path.relative_to(repo_root).as_posix(), size) for path, size in files]
    oversized = [
        {"path": rel, "bytes": size}
        for rel, size in file_rows
        if size > limits["individual_file_allowlist_threshold_bytes"] and rel not in allowlist
    ]
    newly_introduced_large = [
        {"path": rel, "bytes": size, "tracked": rel in tracked}
        for rel, size in file_rows
        if size > limits["new_file_surface_threshold_bytes"] and rel in introduced
    ]
    forbidden_roots = set(limits["large_artifact_roots"])
    forbidden_suffixes = set(limits["large_artifact_suffixes"])
    forbidden_artifacts = [
        {"path": rel, "bytes": size}
        for rel, size in file_rows
        if rel not in allowlist and (
            Path(rel).suffix.lower() in forbidden_suffixes
            and size > limits["new_file_surface_threshold_bytes"]
        )
    ]
    forbidden_root_bytes = {
        name: sum(size for rel, size in file_rows if rel.split("/", 1)[0].lower() == name)
        for name in forbidden_roots
    }
    forbidden_large_roots = [
        {"path": name, "bytes": size}
        for name, size in sorted(forbidden_root_bytes.items())
        if size > limits["new_file_surface_threshold_bytes"] and name not in allowlist
    ]
    violations = []
    if worktree_bytes >= limits["required_maximum_bytes"]:
        violations.append(f"repository_worktree_budget:{worktree_bytes}")
    if limits["forbid_repo_local_venv"] and os.path.lexists(Path(repo_root) / ".venv"):
        violations.append("repository_local_venv")
    violations.extend(f"oversized_file:{row['path']}:{row['bytes']}" for row in oversized)
    violations.extend(f"forbidden_artifact:{row['path']}:{row['bytes']}" for row in forbidden_artifacts)
    violations.extend(f"forbidden_large_root:{row['path']}:{row['bytes']}" for row in forbidden_large_roots)
    material_access_errors = [row for row in access_errors if row["material_to_repo_accounting"]]
    if material_access_errors:
        violations.append(f"repository_accounting_incomplete:{len(material_access_errors)}")
    return {
        "name": "repository_budget",
        "violations": violations,
        "repository_worktree_bytes": worktree_bytes,
        "git_database_bytes": git_database_bytes,
        "repository_local_venv_exists": os.path.lexists(Path(repo_root) / ".venv"),
        "target_300m_status": "PASS" if worktree_bytes < limits["required_maximum_bytes"] else "FAIL",
        "preferred_150m_status": "PASS" if worktree_bytes < limits["preferred_bytes"] else "NOT_MET",
        "warning_400m_status": "WARNING" if worktree_bytes >= limits["warning_bytes"] else "PASS",
        "hard_limit_500m_status": "HARD_FAIL" if worktree_bytes >= limits["hard_fail_bytes"] else "PASS",
        "oversized_files": oversized,
        "new_files_over_10m": newly_introduced_large,
        "forbidden_artifacts": forbidden_artifacts,
        "forbidden_large_roots": forbidden_large_roots,
        "access_errors": access_errors,
        "accounting_complete": not access_errors,
        "accounting_complete_for_repository_scope": not material_access_errors,
        "material_access_error_count": len(material_access_errors),
        "accounting_note": "all unreadable paths are classified; bytes are a lower bound and material repository paths fail closed",
    }


def registry_hygiene():
    configs = _json(FAST / "manifests" / "registries" / "FAST3_CONFIG_REGISTRY.json")["configs"]
    stages = _json(FAST / "manifests" / "registries" / "FAST3_STAGE_REGISTRY.json")["stages"]
    formal = {}
    for item in configs: formal[item["stage_id"]] = formal.get(item["stage_id"], 0) + int(item["canonical"])
    active_auth = [p for p in _files() if "AUTHORIZATION" in p.name and "docs/legacy/" not in p.relative_to(FAST).as_posix()]
    active_patch = [p for p in _files() if "PATCH_APPLIED" in p.name and "manifests/legacy/" not in p.relative_to(FAST).as_posix()]
    active_prompt = [p for p in _files() if "PROMPT" in p.name and "docs/legacy/" not in p.relative_to(FAST).as_posix()]
    stage_manifests = list((FAST / "manifests" / "stages").glob("FAST3_003*MANIFEST.json"))
    state_files = list((FAST / "state").glob("*STATE*.json"))
    bad = [f"duplicate_config:{k}" for k,v in formal.items() if v > 1]
    if len(state_files) != 1: bad.append("duplicate_state")
    if len(stage_manifests) != 1: bad.append("duplicate_stage_manifest")
    if active_auth: bad.append("active_authorization")
    if active_patch: bad.append("active_patch")
    if active_prompt: bad.append("active_prompt")
    if (FAST / "outputs").exists() or (FAST / "stages").exists(): bad.append("deprecated_result_directory")
    if len({x["stage_id"] for x in stages}) != len(stages): bad.append("duplicate_stage_id")
    return {"name": "registry_hygiene", "violations": bad, "active_authorization_file_count": len(active_auth), "active_patch_file_count": len(active_patch), "active_prompt_file_count": len(active_prompt), "duplicate_config_count": len([k for k,v in formal.items() if v > 1]), "duplicate_state_count": max(0, len(state_files)-1)}


def compatibility():
    targets = {"run_fast3_overnight_autopilot.ps1": "fast3\\compatibility\\run_fast3_overnight_autopilot.ps1", "start_codex_fast3_full_chain.ps1": "fast3\\compatibility\\start_codex_fast3_full_chain.ps1", "start_codex_v22_080a.ps1": "fast3\\compatibility\\start_codex_v22_080a.ps1"}
    bad = []
    for old, relative in targets.items():
        if not (REPO / relative).is_file(): bad.append(f"compatibility_missing:{old}")
    return {"name": "compatibility", "violations": bad, "compatibility_wrapper_count": len(targets)}


def single_source():
    state = _json(FAST / "state" / "FAST3_STATE.json")
    registry = _json(FAST / "manifests" / "registries" / "FAST3_STAGE_REGISTRY.json")
    status = (FAST / "FAST3_STATUS.md").read_text(encoding="utf-8")
    current = next((x for x in registry["stages"] if x["stage_id"] == state["current_stage"]), None)
    bad = []
    if current is None or current["status"] != state["current_status"]: bad.append("stage_state_registry_mismatch")
    if state["current_stage"] not in status or state["current_status"] not in status: bad.append("stage_state_status_mismatch")
    if state["live_trading_allowed"] or state["confirmation_read_count"] != 0: bad.append("unsafe_state")
    if Path(state.get("result_root", "")) != EXTERNAL_RESULTS_ROOT: bad.append("result_root_mismatch")
    if Path(state.get("data_root", "")) != EXTERNAL_DATA_ROOT: bad.append("data_root_mismatch")
    contract = FAST / "configs" / "contracts" / "FAST3_002_EXECUTABLE_CONTRACT.json"
    raw = _json(contract); claimed = raw.pop("config_sha256")
    actual = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    if claimed != actual or state["contract_hashes"].get("FAST3-002") != claimed: bad.append("frozen_contract_hash_mismatch")
    return {"name": "single_source", "violations": bad}


def classify_legacy_external_junction(
    logical_path: Path,
    *,
    repo_root: Path = REPO,
    approved_results_root: Path = APPROVED_RESULTS_VOLUME_ROOT,
    canonical_data_root: Path = APPROVED_DATA_VOLUME_ROOT,
    approved_target: Path = LEGACY_LOCAL_RESULTS_TARGET,
):
    """Report final removal, and fail closed if the retired path is reintroduced.

    The logical path is intentionally compared before resolving it.  The target and
    every policy root are then resolved before comparison, so `..`, case variants,
    symlinks, and nested Junctions cannot escape the approved results volume.
    """
    expected_logical = Path(repo_root) / LEGACY_LOGICAL_RESULTS_NAME
    result = {
        "logical_path": str(Path(logical_path).absolute()),
        "resolved_target": None,
        "link_type": None,
        "classification": "REJECTED",
        "legacy_compatibility_status": "REINTRODUCED_REJECTED",
        "legacy_logical_path_exists": os.path.lexists(logical_path),
        "physical_link_exists": False,
        "approval_reason": None,
        "recursively_scanned": False,
        "violations": [],
    }
    if _absolute_key(logical_path) != _absolute_key(expected_logical):
        result["violations"].append("legacy_junction_logical_path")
        return result
    if not os.path.lexists(logical_path):
        result.update({
            "classification": "REMOVED_FINALIZED",
            "legacy_compatibility_status": "REMOVED_FINALIZED",
            "approval_reason": "retired legacy logical path is absent; Junction removal finalized",
        })
        return result
    result.update({
        "classification": "REJECTED_LEGACY_JUNCTION_REINTRODUCED",
        "approval_reason": "retired legacy path was reintroduced; compatibility links are no longer permitted",
    })
    result["violations"].append("LEGACY_JUNCTION_REINTRODUCED")
    try:
        item, is_reparse = _lstat_reparse(logical_path)
    except OSError:
        result["violations"].append("legacy_junction_lstat_failed")
        return result
    if not stat.S_ISDIR(item.st_mode) or not is_reparse:
        result["violations"].append("legacy_junction_not_reparse_point")
        return result
    tag = getattr(item, "st_reparse_tag", None)
    result["physical_link_exists"] = True
    result["link_type"] = "JUNCTION" if tag == IO_REPARSE_TAG_MOUNT_POINT else "REPARSE_POINT"
    try:
        resolved_target = logical_path.resolve(strict=True)
        result["resolved_target"] = str(resolved_target)
    except (OSError, RuntimeError):
        result["violations"].append("legacy_junction_target_unresolvable")
        return result
    if _is_within(resolved_target, repo_root):
        result["violations"].append("legacy_junction_target_inside_repository")
    elif _is_within(resolved_target, canonical_data_root):
        result["violations"].append("legacy_junction_target_inside_canonical_data_root")
    elif not _is_within(resolved_target, approved_results_root):
        result["violations"].append("legacy_junction_target_outside_approved_results_root")
    else:
        try:
            target_matches = _resolved_key(resolved_target) == _resolved_key(approved_target)
        except (OSError, RuntimeError):
            target_matches = False
        if not target_matches:
            result["violations"].append("legacy_junction_target_not_approved_compatibility_target")
    return result


def _is_repository_result_file(path: Path, repo_root: Path) -> bool:
    if path.suffix.lower() in {".parquet", ".bin", ".pickle", ".pkl", ".joblib"}:
        return True
    relative_parts = tuple(part.lower() for part in path.relative_to(repo_root).parts[:-1])
    is_result_directory = (
        bool(relative_parts) and relative_parts[0] in {LEGACY_LOGICAL_RESULTS_NAME, "outputs"}
    ) or relative_parts[:2] in {("fast3", "outputs"), ("fast3", "stages")}
    return is_result_directory and bool(
        re.search(r"FAST3|V22[._-]?0(49|65|66|69|70|71|72|73|74|75|76|77|78|79|80|81|82|83|84|85|86)", path.name, re.I)
    )


def _repository_result_scan(repo_root: Path = REPO):
    """Scan all physical repository files; ReparsePoint directories are never entered."""
    ignored = {".git", ".venv", ".pytest_cache", "node_modules"}
    return [
        path for path in _iter_physical_files(
            Path(repo_root), skip_directory=lambda directory: directory.name in ignored or directory.name.startswith(".pytest")
        ) if _is_repository_result_file(path, Path(repo_root))
    ]


def result_routing():
    state = _json(FAST / "state" / "FAST3_STATE.json")
    registry_path = EXTERNAL_RESULTS_ROOT / "FAST3_RESULTS_REGISTRY.json"
    latest_path = EXTERNAL_RESULTS_ROOT / "FAST3_LATEST.json"
    bad = []
    if Path(state["result_root"]) != EXTERNAL_RESULTS_ROOT: bad.append("state_result_root")
    if not registry_path.is_file() or not latest_path.is_file(): bad.append("external_result_registry_missing")
    production = list((FAST / "scripts" / "run").glob("*.py"))
    write_findings = scan_internal_result_writes(production)
    internal_writes = sorted({row["path"].relative_to(FAST).as_posix() for row in write_findings})
    if internal_writes: bad.extend(f"internal_result_write:{x}" for x in internal_writes)
    legacy_path = REPO / LEGACY_LOGICAL_RESULTS_NAME
    legacy = classify_legacy_external_junction(legacy_path)
    if legacy["violations"]:
        bad.extend(legacy["violations"])
    repository_result_files = _repository_result_scan()
    if repository_result_files:
        bad.append(f"repository_result_files:{len(repository_result_files)}")
    canonical_count = {}
    if registry_path.is_file():
        for item in _json(registry_path).get("results", []):
            if item.get("canonical"):
                stage = item.get("stage_id"); canonical_count[stage] = canonical_count.get(stage, 0) + 1
                result_path = Path(item.get("result_path", ""))
                if result_path.parent != EXTERNAL_RESULTS_ROOT or not result_path.is_dir(): bad.append(f"canonical_result_path:{stage}")
                elif sum(1 for p in result_path.rglob("*") if p.is_file()) > RESULT_FILE_BUDGET: bad.append(f"result_file_budget:{stage}")
                elif any(p.suffix.lower() in {".pickle", ".pkl", ".joblib"} for p in result_path.rglob("*")): bad.append(f"forbidden_result_binary:{stage}")
    bad.extend(f"duplicate_canonical_result:{stage}" for stage, count in canonical_count.items() if count > 1)
    return {
        "name": "result_routing",
        "violations": bad,
        "repository_internal_result_write_count": len(internal_writes),
        "repository_internal_result_write_findings": [
            {**row, "path": row["path"].relative_to(FAST).as_posix()} for row in write_findings
        ],
        "internal_result_write_false_positive_count": 0,
        "local_result_reference_count": sum(1 for p in production if LEGACY_LOGICAL_RESULTS_NAME in p.read_text(encoding="utf-8", errors="ignore")),
        "repository_result_file_count": len(repository_result_files),
        "legacy_junction": legacy,
        "legacy_compatibility_status": legacy["legacy_compatibility_status"],
        "legacy_logical_path_exists": legacy["legacy_logical_path_exists"],
        "recursively_scanned": legacy["recursively_scanned"],
    }


def forbidden_patterns(*, targets=None, repo_root=REPO, baseline_path=None):
    targets = list(targets) if targets is not None else list((FAST / "src").rglob("*.py")) + list((FAST / "scripts" / "run").glob("*.py"))
    baseline_path = Path(baseline_path) if baseline_path is not None else legacy_baseline_path()
    direct = []; raw_hacks = []
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"(?:from|import)\s+scripts\.v22|Path\([^\n]*scripts[/\\]v22", text): direct.append(path.relative_to(FAST).as_posix())
        if any(isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
               and node.value.id == "sys" and node.attr == "path" for node in ast.walk(ast.parse(text))):
            raw_hacks.append({"path": path, "rule_id": "sys_path"})
    current, frozen, invalidated = apply_legacy_exceptions(
        raw_hacks, repo_root=Path(repo_root), baseline_path=baseline_path,
    )
    return {
        "name": "forbidden_patterns",
        "violations": [f"legacy_import:{x}" for x in direct]
        + [f"sys_path:{row['repository_relative_path'].removeprefix('fast3/')}" for row in current],
        "direct_legacy_v22_import_count": len(direct),
        "raw_sys_path_hack_count": len(raw_hacks),
        "sys_path_hack_count": len(current),
        "frozen_legacy_exception_count": len(frozen),
        "frozen_legacy_exceptions": frozen,
        "legacy_exception_invalidated_count": len(invalidated),
        "legacy_exception_invalidated": invalidated,
    }


def frozen_legacy_baseline():
    policy = legacy_policy()
    required_true = (
        "exact_repository_relative_path_required", "exact_sha256_required",
        "exact_violation_rule_required", "path_only_exceptions_forbidden",
        "directory_exceptions_forbidden", "wildcard_exceptions_forbidden",
        "modified_files_reenter_current_enforcement",
        "exact_baseline_membership_required",
    )
    violations = [f"legacy_policy_not_strict:{name}" for name in required_true if policy.get(name) is not True]
    expected_manifest_sha = str(policy.get("manifest_sha256", "")).lower()
    actual_manifest_sha = _hash(legacy_baseline_path())
    if expected_manifest_sha != actual_manifest_sha:
        violations.append("legacy_baseline_manifest_identity_mismatch")
    status = legacy_baseline_status(repo_root=REPO, baseline_path=legacy_baseline_path())
    return {"name": "frozen_legacy_baseline", "violations": violations,
            "expected_manifest_sha256": expected_manifest_sha,
            "actual_manifest_sha256": actual_manifest_sha, **status}


def write_file_registry():
    tracked = set(subprocess.run(["git", "ls-files"], cwd=REPO, text=True, capture_output=True, check=False).stdout.splitlines())
    rows = []
    for path in _files():
        if path == FAST / "manifests" / "registries" / "FAST3_FILE_REGISTRY.json":
            continue
        rel = path.relative_to(REPO).as_posix()
        legacy = "legacy/" in path.relative_to(FAST).as_posix()
        rows.append({"path": rel, "owner_stage": "legacy" if legacy else "FAST3-003", "category": path.suffix.lstrip(".") or "file", "canonical": not legacy,
                     "generated": path.name.endswith(("SUMMARY.json", "TEST_EVIDENCE.json")), "tracked": rel in tracked, "external": False,
                     "deprecated": legacy, "replacement": None, "reason": "FAST3 legacy archive" if legacy else "FAST3 canonical project file", "sha256": _hash(path)})
    for name in ("CODEX_GOAL.md", "CODEX_PLAN.md", "CODEX_STATUS.md"):
        path = REPO / name
        if path.is_file():
            rows.append({"path": name, "owner_stage": "repository", "category": "md", "canonical": True,
                         "generated": False, "tracked": name in tracked, "external": False, "deprecated": False,
                         "replacement": None, "reason": "repository-level active instruction required by AGENTS.md", "sha256": _hash(path)})
    out = FAST / "manifests" / "registries" / "FAST3_FILE_REGISTRY.json"
    out.write_text(json.dumps({"schema_version": "1.0.0", "files": rows}, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--write-file-registry", action="store_true"); args = parser.parse_args(argv)
    if args.write_file_registry: write_file_registry()
    checks = [architecture(), frozen_legacy_baseline(), bloat(), repository_budget(), single_source(), registry_hygiene(), forbidden_patterns(), compatibility(), result_routing()]
    violations = [v for check in checks for v in check["violations"]]
    frozen_count = sum(check.get("frozen_legacy_exception_count", 0) for check in checks)
    effective = "PASS_STRICT_WITH_IMMUTABLE_LEGACY_BASELINE" if not violations else "FAIL"
    result = {
        "status": effective,
        "anti_bloat_effective_status": effective,
        "current_new_violation_count": len(violations),
        "frozen_legacy_exception_count": frozen_count,
        "checks": checks,
        "violations": violations,
    }
    print(json.dumps(result, indent=2))
    return 0 if not violations else 1

if __name__ == "__main__": raise SystemExit(main())
