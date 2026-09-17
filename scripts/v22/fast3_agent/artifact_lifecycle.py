"""Conservative, evidence-first cleanup for future experiment runtime artifacts."""
from __future__ import annotations

import os
import shutil
import stat
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


LIFECYCLE_CLASSES = {
    "PROTECTED_FULL",
    "SELECTED_FULL",
    "COMPACTABLE",
    "EPHEMERAL",
    "FAILED",
    "UNKNOWN",
}
_PROTECTED_WORDS = {
    "authoritative",
    "baseline",
    "canonical",
    "control",
    "forward",
    "frozen",
    "ledger",
    "prereg",
    "preregister",
    "preregistered",
    "promoted",
    "prospective",
    "selected",
    "shadow",
}
_PROTECTED_FLAGS = (
    "append_only_evidence",
    "authoritative",
    "baseline",
    "control",
    "explicitly_protected",
    "forward",
    "frozen",
    "preregistered",
    "prospective",
    "shadow",
)
_SELECTED_FLAGS = (
    "champion",
    "current_challenger",
    "explicitly_retained",
    "promoted",
    "selected",
)
_EVIDENCE_GATES = (
    "final_metrics_persisted",
    "config_identity_persisted",
    "final_status_persisted",
    "required_ledger_persisted",
    "manifest_finalized",
)
_FORBIDDEN_ROOTS = tuple(
    Path(value).resolve(strict=False)
    for value in (
        r"D:\us-tech-quant",
        r"D:\us-tech-quant-data",
    )
)


def classify_run(metadata: dict[str, Any]) -> str:
    """Classify only from explicit run metadata; incomplete metadata stays UNKNOWN."""
    if metadata.get("metadata_complete") is not True:
        return "UNKNOWN"
    status = str(metadata.get("status", "")).strip().upper()
    role = str(metadata.get("run_role", "")).strip().upper()
    promotion = str(metadata.get("promotion_status", "")).strip().upper()
    if not status or not role or not promotion:
        return "UNKNOWN"
    if any(metadata.get(key) is True for key in _PROTECTED_FLAGS):
        return "PROTECTED_FULL"
    if any(word in role for word in ("BASELINE", "CONTROL", "FORWARD", "PROSPECTIVE", "SHADOW")):
        return "PROTECTED_FULL"
    if any(metadata.get(key) is True for key in _SELECTED_FLAGS):
        return "SELECTED_FULL"
    if promotion in {
        "SELECTED",
        "PROMOTED",
        "PROMOTED_CHAMPION",
        "CURRENT_CHALLENGER",
        "CHAMPION",
    }:
        return "SELECTED_FULL"
    if any(word in status for word in ("FAIL", "ABORT", "INCOMPLETE")):
        return "FAILED"
    if role in {"SCRATCH", "TEMPORARY", "EPHEMERAL"}:
        return "EPHEMERAL"
    if any(word in status for word in ("PASS", "COMPLETE", "REJECT", "SUPERSEDED")) and role in {
        "EXPLORATORY",
        "RESEARCH_CANDIDATE",
        "SYNTHESIZED_EXPLORATORY",
        "SUPERSEDED_EXPERIMENT",
    }:
        return "COMPACTABLE"
    return "UNKNOWN"


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def _is_reparse(path: Path) -> bool:
    info = os.lstat(path)
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _has_protected_name(path: Path) -> bool:
    return any(any(word in part.casefold() for word in _PROTECTED_WORDS) for part in path.parts)


def _protected_descendant(path: Path) -> bool:
    if not path.is_dir():
        return False
    def raise_error(error: OSError) -> None:
        raise error

    for root, directories, files in os.walk(path, topdown=True, onerror=raise_error, followlinks=False):
        current = Path(root)
        if current != path and (_is_reparse(current) or _has_protected_name(Path(current.name))):
            return True
        if any(_has_protected_name(Path(name)) for name in (*directories, *files)):
            return True
    return False


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    def raise_error(error: OSError) -> None:
        raise error

    for root, directories, files in os.walk(path, topdown=True, onerror=raise_error, followlinks=False):
        directories[:] = [name for name in directories if not _is_reparse(Path(root) / name)]
        for name in files:
            child = Path(root) / name
            if not _is_reparse(child):
                total += child.stat().st_size
    return total


def _validate_target(
    raw_target: str | Path,
    *,
    run_root: Path,
    approved_roots: tuple[Path, ...],
) -> tuple[Path | None, str | None]:
    raw = str(raw_target).strip()
    if not raw or raw in {".", ".."} or any(character in raw for character in "*?[]"):
        return None, "INVALID_TARGET"
    target = Path(raw_target)
    if not target.is_absolute() or ".." in target.parts:
        return None, "NON_ABSOLUTE_OR_PARENT_TRAVERSAL"
    if not target.exists():
        return None, "TARGET_MISSING"
    lexical = Path(os.path.abspath(target))
    matching_roots = [root for root in approved_roots if _is_within(lexical, root)]
    if not matching_roots:
        return None, "OUTSIDE_APPROVED_ROOT"
    matched = max(matching_roots, key=lambda value: len(value.parts))
    try:
        relative = lexical.relative_to(matched)
        cursor = matched
        for part in relative.parts:
            cursor /= part
            if _is_reparse(cursor):
                return None, "REPARSE_OR_SYMLINK_REJECTED"
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None, "PATH_RESOLUTION_FAILED"
    if not _is_within(resolved, matched.resolve(strict=True)):
        return None, "RESOLVED_PATH_ESCAPES_ROOT"
    if not _is_within(resolved, run_root):
        return None, "OUTSIDE_RUN_ROOT"
    if resolved == run_root or resolved in approved_roots:
        return None, "ROOT_DELETE_REJECTED"
    if any(resolved == root or _is_within(resolved, root) for root in _FORBIDDEN_ROOTS):
        return None, "FORBIDDEN_ROOT_REJECTED"
    try:
        if _has_protected_name(resolved) or _protected_descendant(resolved):
            return None, "PROTECTED_PATH_REJECTED"
    except OSError:
        return None, "PATH_INSPECTION_FAILED"
    return resolved, None


def _delete_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _base_summary(lifecycle_class: str, dry_run: bool) -> dict[str, Any]:
    return {
        "lifecycle_class": lifecycle_class,
        "cleanup_status": "CLEANUP_NOT_RUN",
        "deleted_target_count": 0,
        "bytes_reclaimed": 0,
        "skipped_target_count": 0,
        "skip_reasons": {},
        "would_delete_count": 0,
        "would_reclaim_bytes": 0,
        "protected_count": int(lifecycle_class in {"PROTECTED_FULL", "SELECTED_FULL"}),
        "unknown_count": int(lifecycle_class == "UNKNOWN"),
        "dry_run": bool(dry_run),
    }


def closeout_artifacts(
    *,
    run_root: str | Path,
    candidates: Iterable[str | Path],
    metadata: dict[str, Any],
    evidence: dict[str, bool],
    approved_roots: Iterable[str | Path],
    dry_run: bool = False,
    active_writer: bool = False,
    downstream_reference: bool = False,
) -> dict[str, Any]:
    """Run evidence-gated cleanup and return one compact manifest-ready summary."""
    lifecycle_class = classify_run(metadata)
    summary = _base_summary(lifecycle_class, dry_run)
    candidates = list(candidates)
    if lifecycle_class in {"PROTECTED_FULL", "SELECTED_FULL", "UNKNOWN"}:
        summary["cleanup_status"] = "KEEP_FULL" if lifecycle_class != "UNKNOWN" else "KEEP_UNKNOWN"
        summary["skipped_target_count"] = len(candidates)
        summary["skip_reasons"] = {lifecycle_class: len(candidates)}
        return summary
    missing_gates = [gate for gate in _EVIDENCE_GATES if evidence.get(gate) is not True]
    if missing_gates or active_writer or downstream_reference:
        reasons = [*(f"MISSING_{gate.upper()}" for gate in missing_gates)]
        if active_writer:
            reasons.append("ACTIVE_WRITER")
        if downstream_reference:
            reasons.append("DOWNSTREAM_REFERENCE")
        summary["cleanup_status"] = "CLEANUP_NOT_RUN_EVIDENCE_INCOMPLETE"
        summary["skipped_target_count"] = len(candidates)
        summary["skip_reasons"] = dict(sorted(Counter(reasons).items()))
        return summary
    try:
        run = Path(run_root).resolve(strict=True)
        roots = tuple(Path(root).resolve(strict=True) for root in approved_roots)
    except (OSError, RuntimeError, ValueError):
        summary["cleanup_status"] = "CLEANUP_NOT_RUN_PATH_SAFETY"
        summary["skipped_target_count"] = len(candidates)
        summary["skip_reasons"] = {"ROOT_RESOLUTION_FAILED": len(candidates)}
        return summary
    invalid_root = (
        not roots
        or any(root == Path(root.anchor) for root in roots)
        or any(root == forbidden or _is_within(root, forbidden) for root in roots for forbidden in _FORBIDDEN_ROOTS)
        or not any(_is_within(run, root) for root in roots)
    )
    if invalid_root:
        summary["cleanup_status"] = "CLEANUP_NOT_RUN_PATH_SAFETY"
        summary["skipped_target_count"] = len(candidates)
        summary["skip_reasons"] = {"INVALID_APPROVED_ROOT": len(candidates)}
        return summary
    accepted: list[Path] = []
    skip_reasons: Counter[str] = Counter()
    for candidate in candidates:
        target, reason = _validate_target(candidate, run_root=run, approved_roots=roots)
        if reason:
            skip_reasons[reason] += 1
        elif target not in accepted:
            accepted.append(target)
    accepted.sort(key=lambda path: (len(path.parts), str(path).casefold()))
    physical: list[Path] = []
    for target in accepted:
        if any(parent.is_dir() and _is_within(target, parent) for parent in physical):
            skip_reasons["COVERED_BY_PARENT_TARGET"] += 1
        else:
            physical.append(target)
    sizes: dict[Path, int] = {}
    for target in physical:
        try:
            sizes[target] = _path_size(target)
        except OSError:
            skip_reasons["PATH_SIZE_FAILED"] += 1
    physical = [target for target in physical if target in sizes]
    if dry_run:
        summary.update(
            cleanup_status="DRY_RUN",
            would_delete_count=len(physical),
            would_reclaim_bytes=sum(sizes.values()),
            skipped_target_count=sum(skip_reasons.values()),
            skip_reasons=dict(sorted(skip_reasons.items())),
        )
        return summary
    for target in sorted(physical, key=lambda path: (-sizes[path], str(path).casefold())):
        try:
            _delete_path(target)
            summary["deleted_target_count"] += 1
            summary["bytes_reclaimed"] += sizes[target]
        except PermissionError:
            skip_reasons["PERMISSION_DENIED"] += 1
        except OSError:
            skip_reasons["IO_ERROR"] += 1
        except Exception:
            skip_reasons["UNKNOWN_DELETE_ERROR"] += 1
    summary["skipped_target_count"] = sum(skip_reasons.values())
    summary["skip_reasons"] = dict(sorted(skip_reasons.items()))
    summary["cleanup_status"] = "CLEANUP_COMPLETE" if not skip_reasons else "CLEANUP_PARTIAL_PERMISSION_OR_IO"
    return summary
