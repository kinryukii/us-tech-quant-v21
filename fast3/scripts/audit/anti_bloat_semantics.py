"""Strict semantic helpers for the FAST3 Anti-Bloat guard."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Iterable

ALLOWED_LEGACY_RULES = {"python_lines", "sys_path"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WILDCARD_CHARS = set("*?[]")
INTERNAL_RESULT_MARKERS = ("/.local_results", "/fast3/outputs", "/fast3/stages")
RECEIVER_WRITES = {
    "write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir",
}
TARGET_ARG_WRITES = {
    "to_csv", "to_parquet", "to_pickle", "to_json", "to_excel", "to_feather",
    "to_hdf", "to_stata", "save", "savez", "savez_compressed", "savetxt",
}
DESTINATION_ARG_WRITES = {
    "copy": 1, "copy2": 1, "copyfile": 1, "copytree": 1, "move": 1,
    "replace": 1, "rename": 1, "dump": 1,
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_relative(value: str) -> str:
    if "\\" in value or any(char in value for char in WILDCARD_CHARS):
        raise ValueError(f"legacy path must be canonical and exact: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise ValueError(f"legacy path must be repository-relative: {value}")
    return path.as_posix()


def baseline_membership_sha256(entries: Iterable[dict]) -> str:
    identities = sorted(
        f"{entry['path']}\0{entry['rule_id']}\0{entry['sha256']}" for entry in entries
    )
    return hashlib.sha256("\n".join(identities).encode("utf-8")).hexdigest()


def load_legacy_baseline(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "ANTI_BLOAT_FROZEN_LEGACY_BASELINE_V1":
        raise ValueError("unsupported legacy baseline schema")
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise ValueError("legacy baseline entries must be a list")
    seen: set[tuple[str, str]] = set()
    normalized = []
    for entry in entries:
        relative = _canonical_relative(str(entry.get("path", "")))
        rule = str(entry.get("rule_id", ""))
        digest = str(entry.get("sha256", "")).lower()
        if rule not in ALLOWED_LEGACY_RULES:
            raise ValueError(f"unsupported legacy rule: {rule}")
        if not SHA256_RE.fullmatch(digest):
            raise ValueError(f"legacy entry lacks exact SHA-256: {relative}")
        key = (relative, rule)
        if key in seen:
            raise ValueError(f"duplicate legacy path/rule: {relative}:{rule}")
        seen.add(key)
        normalized.append({**entry, "path": relative, "rule_id": rule, "sha256": digest})
    expected_membership = str(raw.get("membership_set_sha256", "")).lower()
    actual_membership = baseline_membership_sha256(normalized)
    if not SHA256_RE.fullmatch(expected_membership) or expected_membership != actual_membership:
        raise ValueError("legacy baseline membership identity mismatch")
    return {**raw, "entries": normalized}


def apply_legacy_exceptions(
    findings: Iterable[dict], *, repo_root: Path, baseline_path: Path,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return current violations, exact-SHA exceptions, and invalidated matches."""
    baseline = load_legacy_baseline(baseline_path)
    index = {(entry["path"], entry["rule_id"]): entry for entry in baseline["entries"]}
    current, excepted, invalidated = [], [], []
    for finding in findings:
        relative = Path(finding["path"]).relative_to(repo_root).as_posix()
        rule = finding["rule_id"]
        public_finding = {**finding, "path": relative, "repository_relative_path": relative}
        entry = index.get((relative, rule))
        if entry is None:
            current.append({
                **public_finding,
                "classification": "NEW_PATH_NOT_IN_BASELINE",
                "grandfathered": False,
            })
            continue
        observed = sha256_file(Path(finding["path"]))
        if observed == entry["sha256"]:
            excepted.append({
                **public_finding,
                "registered_sha256": entry["sha256"],
                "classification": "PASS_AS_FROZEN_LEGACY_EXCEPTION",
                "grandfathered": True,
            })
        else:
            invalidated.append({
                **public_finding,
                "registered_sha256": entry["sha256"], "observed_sha256": observed,
                "legacy_exception_invalidated": True,
                "classification": "BASELINE_IDENTITY_CHANGED",
            })
            current.append(public_finding)
    return current, excepted, invalidated


def legacy_baseline_status(*, repo_root: Path, baseline_path: Path) -> dict:
    baseline = load_legacy_baseline(baseline_path)
    valid, invalid = [], []
    for entry in baseline["entries"]:
        source = repo_root / PurePosixPath(entry["path"])
        observed = sha256_file(source) if source.is_file() else None
        row = {**entry, "observed_sha256": observed}
        (valid if observed == entry["sha256"] else invalid).append(row)
    return {
        "registered_count": len(baseline["entries"]),
        "valid_exact_sha_count": len(valid),
        "invalidated_count": len(invalid),
        "invalidated": invalid,
        "path_only_whitelist_count": 0,
        "directory_whitelist_count": 0,
        "wildcard_exception_count": 0,
        "legacy_exception_sha_locked": True,
        "baseline_membership_sha256": baseline["membership_set_sha256"],
        "baseline_membership_locked": True,
    }


def _symbolic(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return "{" + node.id + "}"
    if isinstance(node, ast.Attribute):
        return f"{_symbolic(node.value)}.{node.attr}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
        separator = "/" if isinstance(node.op, ast.Div) else ""
        return f"{_symbolic(node.left)}{separator}{_symbolic(node.right)}"
    if isinstance(node, ast.JoinedStr):
        return "".join(_symbolic(value) for value in node.values)
    if isinstance(node, ast.FormattedValue):
        return _symbolic(node.value)
    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        if name in {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"} and node.args:
            return _symbolic(node.args[0])
        if name.endswith(".joinpath"):
            return "/".join([_symbolic(node.func.value), *(_symbolic(arg) for arg in node.args)])
    return ""


def _contains_internal_marker(value: str) -> bool:
    normalized = "/" + value.replace("\\", "/").lower().lstrip("/")
    return any(marker in normalized for marker in INTERNAL_RESULT_MARKERS)


def _target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in node.elts)) if node.elts else set()
    return set()


def _expr_tainted(node: ast.AST | None, tainted: set[str]) -> bool:
    if node is None:
        return False
    if any(_contains_internal_marker(_symbolic(item)) for item in ast.walk(node)):
        return True
    return any(isinstance(item, ast.Name) and item.id in tainted for item in ast.walk(node))


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _mode(call: ast.Call, position: int) -> str:
    if len(call.args) > position and isinstance(call.args[position], ast.Constant):
        return str(call.args[position].value)
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    return "r"


def _keyword_or_arg(call: ast.Call, position: int, names: set[str]) -> ast.AST | None:
    if len(call.args) > position:
        return call.args[position]
    return next((item.value for item in call.keywords if item.arg in names), None)


def internal_result_write_findings(path: Path) -> list[dict]:
    """Detect actual writes to forbidden repository result paths using Python AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tainted: set[str] = set()
    assignments = [item for item in ast.walk(tree) if isinstance(item, (ast.Assign, ast.AnnAssign))]
    changed = True
    while changed:
        changed = False
        for item in assignments:
            value = item.value
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            if _expr_tainted(value, tainted):
                names = set().union(*(_target_names(target) for target in targets))
                if not names.issubset(tainted):
                    tainted.update(names); changed = True
    findings = []
    for call in (item for item in ast.walk(tree) if isinstance(item, ast.Call)):
        name = _call_name(call.func)
        short = name.rsplit(".", 1)[-1]
        target = None
        if name == "os.mkdir":
            target = _keyword_or_arg(call, 0, {"path"})
        elif short in RECEIVER_WRITES and isinstance(call.func, ast.Attribute):
            target = call.func.value
        elif short == "open":
            target = call.func.value if isinstance(call.func, ast.Attribute) else _keyword_or_arg(call, 0, {"file"})
            if not any(flag in _mode(call, 0 if isinstance(call.func, ast.Attribute) else 1) for flag in "wax+"):
                target = None
        elif short in TARGET_ARG_WRITES:
            target = _keyword_or_arg(call, 0, {"path", "path_or_buf", "fname", "file"})
        elif short in DESTINATION_ARG_WRITES:
            target = _keyword_or_arg(call, DESTINATION_ARG_WRITES[short], {"dst", "destination", "file"})
        elif name.endswith("os.makedirs"):
            target = _keyword_or_arg(call, 0, {"name"})
        if target is not None and _expr_tainted(target, tainted):
            findings.append({"path": path, "line": call.lineno, "api": name or short})
    return findings


def scan_internal_result_writes(paths: Iterable[Path]) -> list[dict]:
    findings = []
    for path in paths:
        try:
            findings.extend(internal_result_write_findings(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            findings.append({"path": path, "line": None, "api": f"AST_PARSE_FAILURE:{type(exc).__name__}"})
    return findings
