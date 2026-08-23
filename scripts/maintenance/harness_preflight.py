"""Read-only, task-scoped engineering preflight for the repository Harness."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


REPO = Path(__file__).resolve().parents[2]
TRAINING_CUTOFF = datetime(2026, 1, 1)
TASK_SCOPES = (
    "independent-code",
    "pre2026-research",
    "2026-evaluation",
    "2026-optimization",
    "historical-fetch",
    "frozen-dependent",
    "all",
)
RESEARCH_SCOPES = (
    "pre2026-research",
    "2026-evaluation",
    "2026-optimization",
    "frozen-dependent",
)
DATE_PATTERN = r"20\d{2}-\d{2}-\d{2}"
STRICT_END_KEY = (
    r"(?:(?:max[_-]?)?(?:train|training)(?:[_-]?(?:label|target))?[_-]?"
    r"(?:end|max|through|last)(?:[_-]?date)?|max[_-]?label[_-]?maturity(?:[_-]?date)?|"
    r"train[_-]?target[_-]?end[_-]?max)"
)
CUTOFF_KEY = r"(?:train|training)[_-]?cutoff"
BOUNDARY_ASSIGNMENT = re.compile(
    rf"['\"]?(?P<key>{STRICT_END_KEY}|{CUTOFF_KEY})['\"]?\s*(?:=|:)\s*"
    rf"(?:pd\.Timestamp\()?\s*['\"](?P<date>{DATE_PATTERN})['\"]",
    re.I,
)
FIT_PATTERN = re.compile(
    r"\.fit\s*\(|GridSearchCV\s*\(|RandomizedSearchCV\s*\(|optuna\.(?:create_study|study)",
    re.I,
)


class ResearchBoundaryError(ValueError):
    """Raised when an explicit temporal research invariant is violated."""


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def assert_training_before_cutoff(timestamps: Iterable[Any]) -> None:
    """Mechanically enforce the exclusive default training/label boundary."""
    violations = [str(value) for value in timestamps if _timestamp(value) >= TRAINING_CUTOFF]
    if violations:
        raise ResearchBoundaryError(f"TRAINING_TIMESTAMP_NOT_PRE2026:{violations[:3]}")


def assert_pit_order(information_and_decision_times: Iterable[tuple[Any, Any]]) -> None:
    """Require information availability to be no later than its decision time."""
    violations = [
        (str(available), str(decision))
        for available, decision in information_and_decision_times
        if _timestamp(available) > _timestamp(decision)
    ]
    if violations:
        raise ResearchBoundaryError(f"PIT_INFORMATION_AFTER_DECISION:{violations[:3]}")


def finding(level: str, code: str, detail: str, blocks: Sequence[str] = ()) -> dict[str, Any]:
    return {"level": level, "code": code, "detail": detail, "blocks": list(blocks)}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _registry_semantic_findings(path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    policy = payload.get("governance", {})
    if policy.get("auto_promotion_forbidden") is not True or policy.get("requires_explicit_user_authorization") is not True:
        rows.append(finding("HARD_BLOCKER", "REGISTRY_PROMOTION_GATE_WEAKENED", str(path), RESEARCH_SCOPES))
    for model in payload.get("models", []):
        unsafe = [
            key for key in (
                "uses_2026_training", "uses_2026_parameter_search", "uses_2026_model_selection"
            ) if model.get(key) is not False
        ]
        cutoff = str(model.get("training_cutoff", "UNKNOWN"))
        if unsafe or cutoff.upper() not in {"PRE2026", "<2026-01-01"}:
            try:
                cutoff_invalid = _timestamp(cutoff) > TRAINING_CUTOFF
            except (TypeError, ValueError):
                cutoff_invalid = cutoff.upper() not in {"PRE2026", "<2026-01-01"}
            if unsafe or cutoff_invalid:
                rows.append(finding(
                    "HARD_BLOCKER", "RESEARCH_REGISTRY_2026_REUSE", f"{path.name}:{model.get('model_id')}:{unsafe or cutoff}", RESEARCH_SCOPES
                ))
    return rows


def _contract_findings(repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    governance = repo / "config/research_governance"
    checked_models = 0
    missing: list[str] = []
    for role in ("alpha", "risk", "execution"):
        path = governance / f"{role}_registry.json"
        if not path.is_file():
            missing.append(path.relative_to(repo).as_posix())
            continue
        payload = _json(path)
        rows += _registry_semantic_findings(path, payload)
        for model in payload.get("models", []):
            checked_models += 1
            for artifact_key, hash_key in (("model_artifact", "model_sha256"), ("config_artifact", "config_sha256")):
                artifact, expected = str(model.get(artifact_key, "UNKNOWN")), str(model.get(hash_key, "UNKNOWN")).lower()
                if artifact.upper() == "UNKNOWN" or expected.upper() == "UNKNOWN":
                    continue
                asset = Path(artifact)
                blocks = ("frozen-dependent", "2026-evaluation")
                if not asset.is_file():
                    rows.append(finding("HARD_BLOCKER", "FROZEN_ASSET_MISSING", artifact, blocks))
                elif _sha256(asset) != expected:
                    rows.append(finding("HARD_BLOCKER", "FROZEN_ASSET_HASH_MISMATCH", artifact, blocks))

    judge = governance / "trial_judge_r1.json"
    if judge.is_file():
        payload = _json(judge)
        if payload.get("2026_training_forbidden") is not True or payload.get("auto_promotion_forbidden") is not True:
            rows.append(finding("HARD_BLOCKER", "TRIAL_JUDGE_GATE_WEAKENED", str(judge), RESEARCH_SCOPES))
    else:
        missing.append(judge.relative_to(repo).as_posix())

    shadow = governance / "a2_forward_shadow_unified_r1.json"
    if shadow.is_file():
        payload = _json(shadow)
        unsafe = [key for key in ("training_allowed", "parameter_search_allowed", "model_selection_allowed", "broker_action_allowed") if payload.get(key) is not False]
        if unsafe:
            rows.append(finding("HARD_BLOCKER", "FORWARD_SHADOW_UNSAFE_CAPABILITY", ",".join(unsafe), ("2026-evaluation", "frozen-dependent")))
    else:
        missing.append(shadow.relative_to(repo).as_posix())

    successor = repo / "config/a2_successor_s1/control_contract.json"
    if successor.is_file():
        payload = _json(successor)
        try:
            assert_training_before_cutoff([payload["max_train_label_end_date"]])
        except (KeyError, ResearchBoundaryError) as exc:
            rows.append(finding("HARD_BLOCKER", "SUCCESSOR_TRAINING_BOUNDARY", str(exc), RESEARCH_SCOPES))
        if payload.get("canonical_data_read_only") is not True or payload.get("broker_action_allowed") is not False or payload.get("promotion_status") != "NOT_AUTHORIZED":
            rows.append(finding("HARD_BLOCKER", "SUCCESSOR_SAFETY_GATE_WEAKENED", str(successor), RESEARCH_SCOPES))
    else:
        missing.append(successor.relative_to(repo).as_posix())

    open_config = repo / "config/v22/a2_open_research_r1.json"
    if open_config.is_file():
        payload = _json(open_config)
        if not str(payload.get("cutoff", "")).startswith("2026-01-01") or "LOCKED_2026_HOLDOUT" not in str(payload.get("holdout_label", "")):
            rows.append(finding("HARD_BLOCKER", "OPEN_RESEARCH_BOUNDARY_WEAKENED", str(open_config), RESEARCH_SCOPES))
    else:
        missing.append(open_config.relative_to(repo).as_posix())

    if checked_models:
        rows.append(finding("PASS", "RESEARCH_CONTRACTS", f"validated_models={checked_models}"))
    if missing:
        rows.append(finding("INFORMATIONAL", "OPTIONAL_ACTIVE_CONTRACTS_ABSENT", ",".join(missing)))
    return rows


def _holdout_status_finding(value: str) -> dict[str, Any]:
    if "PRIOR_2026_OUTCOME_EXPOSURE" in value:
        return finding(
            "HARD_BLOCKER",
            "A2_2026_HOLDOUT_ALREADY_EXPOSED",
            "Do not tune/select/refit against this holdout or claim pristine holdout semantics; frozen forward monitoring is a separate contract.",
            ("2026-optimization",),
        )
    return finding("PASS", "A2_HOLDOUT_EXPOSURE", value)


def _holdout_findings(repo: Path) -> list[dict[str, Any]]:
    storage = _json(repo / "config/storage_paths.json")
    results = Path(storage["results_root"])
    status_path = results / "A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT/status.json"
    if not status_path.is_file():
        return [finding("SOFT_WARNING", "A2_HOLDOUT_EXPOSURE_STATUS_MISSING", str(status_path), ("2026-optimization",))]
    status = _json(status_path)
    value = str(status.get("A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT_STATUS", "UNKNOWN"))
    return [_holdout_status_finding(value)]


def _load_anti_bloat_guard(repo: Path):
    path = repo / "fast3/scripts/audit/run_fast3_guard.py"
    spec = importlib.util.spec_from_file_location("harness_anti_bloat_guard", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _anti_bloat_findings(repo: Path) -> list[dict[str, Any]]:
    try:
        guard = _load_anti_bloat_guard(repo)
        budget = guard.repository_budget(repo)
        baseline = guard.frozen_legacy_baseline()
    except Exception as exc:  # fail closed: this is the authoritative guard bridge
        return [finding("HARD_BLOCKER", "ANTI_BLOAT_GUARD_UNAVAILABLE", f"{type(exc).__name__}:{exc}", ("all",))]

    rows: list[dict[str, Any]] = []
    non_accounting = [v for v in budget["violations"] if not str(v).startswith("repository_accounting_incomplete:")]
    for violation in non_accounting:
        rows.append(finding("HARD_BLOCKER", "ANTI_BLOAT_VIOLATION", str(violation), ("all",)))
    for violation in baseline["violations"]:
        rows.append(finding("HARD_BLOCKER", "FROZEN_LEGACY_BASELINE_VIOLATION", str(violation), ("all",)))

    material_errors = [row for row in budget["access_errors"] if row["material_to_repo_accounting"]]
    if material_errors:
        paths = [row["repository_relative_path"] for row in material_errors]
        temporary = all(
            Path(path).name.startswith((".pytest", ".tmp_")) and "pytest" in Path(path).name.lower()
            for path in paths
        )
        level = "SOFT_WARNING" if temporary else "HARD_BLOCKER"
        blocks = () if temporary else ("all",)
        rows.append(finding(level, "ANTI_BLOAT_ACCOUNTING_INCOMPLETE", ",".join(paths), blocks))

    rows.append(finding(
        "PASS",
        "ANTI_BLOAT_BUDGET",
        f"worktree_bytes={budget['repository_worktree_bytes']};preferred={budget['preferred_150m_status']};local_venv={budget['repository_local_venv_exists']}",
    ))
    if not baseline["violations"]:
        rows.append(finding("PASS", "FROZEN_LEGACY_BASELINE", f"registered={baseline['registered_count']};invalidated={baseline['invalidated_count']}"))
    return rows


def _git_paths(repo: Path) -> tuple[list[str], list[Path]]:
    status = subprocess.run(
        ["git", "status", "--porcelain", "-z"], cwd=repo, capture_output=True, check=False
    ).stdout.decode("utf-8", errors="replace")
    entries = [entry for entry in status.split("\0") if entry]
    changed_names = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"], cwd=repo,
        text=True, capture_output=True, check=False,
    ).stdout.splitlines()
    changed_names += subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=repo,
        text=True, capture_output=True, check=False,
    ).stdout.splitlines()
    paths = [repo / name for name in sorted(set(changed_names)) if (repo / name).is_file()]
    return entries, paths


def _boundary_literal_violations(relative_path: str, text: str) -> list[str]:
    violations: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        match = BOUNDARY_ASSIGNMENT.search(line)
        if not match:
            continue
        stamp = _timestamp(match.group("date"))
        key = match.group("key")
        if re.fullmatch(STRICT_END_KEY, key, re.I) and stamp >= TRAINING_CUTOFF:
            violations.append(f"{relative_path}:{number}:{match.group('date')}")
        elif re.fullmatch(CUTOFF_KEY, key, re.I) and stamp > TRAINING_CUTOFF:
            violations.append(f"{relative_path}:{number}:{match.group('date')}")
    return violations


def _changed_training_findings(repo: Path, paths: Sequence[Path]) -> list[dict[str, Any]]:
    violations: list[str] = []
    fit_surfaces: list[str] = []
    allowed_suffixes = {".py", ".json", ".toml", ".yaml", ".yml"}
    for path in paths:
        rel = path.relative_to(repo).as_posix()
        if path.suffix.lower() not in allowed_suffixes or path.name.startswith("test_") or rel == "scripts/maintenance/harness_preflight.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix.lower() == ".py" and FIT_PATTERN.search(text):
            fit_surfaces.append(rel)
        violations += _boundary_literal_violations(rel, text)
    rows: list[dict[str, Any]] = []
    if violations:
        rows.append(finding("HARD_BLOCKER", "OBVIOUS_CHANGED_TRAINING_BOUNDARY", f"count={len(violations)};sample={violations[:5]}", RESEARCH_SCOPES))
    else:
        rows.append(finding("PASS", "OBVIOUS_CHANGED_TRAINING_BOUNDARY", f"scanned_files={len(paths)}"))
    if fit_surfaces:
        rows.append(finding("SOFT_WARNING", "CHANGED_TRAINING_SURFACE_REQUIRES_TARGETED_TEMPORAL_TEST", f"count={len(fit_surfaces)};sample={fit_surfaces[:5]}"))
    return rows


def run_preflight(repo: Path = REPO, task_scope: str = "independent-code") -> dict[str, Any]:
    entries, paths = _git_paths(repo)
    findings = [
        finding("SOFT_WARNING", "DIRTY_WORKTREE", f"entries={len(entries)};preserve unrelated changes")
        if entries else finding("PASS", "WORKTREE", "clean"),
        finding("INFORMATIONAL", "MOOMOO_HISTORICAL_QUOTA", "not probed; historical-fetch requires its dedicated quota preflight"),
    ]
    findings += _contract_findings(repo)
    findings += _holdout_findings(repo)
    findings += _anti_bloat_findings(repo)
    findings += _changed_training_findings(repo, paths)
    hard = [row for row in findings if row["level"] == "HARD_BLOCKER"]
    applicable = [row for row in hard if task_scope == "all" or "all" in row["blocks"] or task_scope in row["blocks"]]
    soft = [row for row in findings if row["level"] == "SOFT_WARNING"]
    status = "HARD_BLOCKER" if applicable else "PASS_WITH_SCOPED_HARD_BLOCKERS" if hard else "PASS_WITH_SOFT_WARNINGS" if soft else "PASS"
    return {
        "preflight_status": status,
        "task_scope": task_scope,
        "training_cutoff_exclusive": TRAINING_CUTOFF.date().isoformat(),
        "applicable_hard_blocker_count": len(applicable),
        "scoped_hard_blocker_count": len(hard) - len(applicable),
        "soft_warning_count": len(soft),
        "findings": findings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-scope", choices=TASK_SCOPES, default="independent-code")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run_preflight(task_scope=args.task_scope)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key in ("preflight_status", "task_scope", "training_cutoff_exclusive", "applicable_hard_blocker_count", "scoped_hard_blocker_count", "soft_warning_count"):
            print(f"{key.upper()}={result[key]}")
        for row in result["findings"]:
            scope = ",".join(row["blocks"]) or "NONE"
            print(f"{row['level']}|{row['code']}|BLOCKS={scope}|{row['detail']}")
    return 2 if result["applicable_hard_blocker_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
