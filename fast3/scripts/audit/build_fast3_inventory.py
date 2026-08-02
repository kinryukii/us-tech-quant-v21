"""Build a deterministic FAST3 repository inventory without moving files.

This tool is deliberately read-only outside its own output directory.  It is a
migration aid, not a research runner: it records why a path matched and which
repository files textually reference it so each move can be reviewed.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


TERMS = (
    "FAST3", "fast3", "V22.049", "V22.065", "V22.066", "V22.069",
    "V22.078", "V22.080", "V22.081", "V22.082", "V22.083", "V22.084",
    "V22.085", "V22.086", "SOXX", "SOXL", "SOXS", "TQQQ", "SQQQ",
    "24h", "overnight", "predictability", "event_entry", "opportunity",
    "direction", "frozen validation", "confirmation",
    "PREDICTABILITY_NOT_ECONOMICALLY_ACTIONABLE",
)
TEXT_SUFFIXES = {".py", ".ps1", ".md", ".txt", ".json", ".ini", ".toml", ".cfg", ".yml", ".yaml"}
SKIP_PARTS = {
    ".git", ".venv", ".pytest_cache", ".pytest_tmp", "__pycache__", ".codex",
    # Runtime outputs are inventoried as roots/config references, never as source
    # files.  Recursing them makes the migration audit both slow and misleading.
    "." + "local_results", "results", "__results__", "pytest_temp",
}


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def destination(rel: Path) -> tuple[bool, str | None, bool, str]:
    name = rel.name
    low = name.lower()
    if rel.parts[0] == "fast3":
        return False, None, False, "already under independent FAST3 root"
    if low.startswith("codex_fast3_") and low.endswith("_prompt.txt"):
        return True, f"fast3/docs/prompts/legacy/{name}", False, "root FAST3 legacy prompt"
    if low.startswith("fast3_generation") and low.endswith("_authorization.md"):
        return True, f"fast3/docs/authorizations/legacy/generation/{name}", False, "root FAST3 generation authorization"
    if low.startswith("fast3_v22_") and low.endswith("_authorization.md"):
        return True, f"fast3/docs/authorizations/legacy/{name}", False, "root FAST3 legacy authorization"
    if low.startswith("fast3_v22_") and low.endswith("_patch_applied.json"):
        return True, f"fast3/manifests/patches/legacy/{name}", False, "root FAST3 patch manifest"
    if low.startswith("fast3_autonomous_master_directive"):
        return True, f"fast3/docs/governance/{name}", False, "FAST3-only master directive"
    if low in {"run_fast3_overnight_autopilot.ps1", "start_codex_fast3_full_chain.ps1", "start_codex_v22_080a.ps1"}:
        return True, f"fast3/scripts/launch/legacy/{name}", True, "root FAST3 launcher"
    if str(rel).replace("\\", "/").startswith("scripts/v22/fast3_agent/"):
        return True, f"fast3/src/fast3/legacy_engine/{rel.name}", True, "dedicated FAST3 agent implementation; wrapper review required"
    if name.startswith(("run_fast3_", "show_fast3_", "stop_fast3_")):
        return True, f"fast3/scripts/legacy/{name}", True, "FAST3 launcher/status helper"
    if "fast3" in low and rel.parts[0] == "scripts":
        return False, None, True, "legacy V22 script: retain until imports and external callers are mapped"
    return False, None, False, "shared, historical, or ownership needs review"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("fast3/manifests"))
    args = parser.parse_args()
    repo = args.repo.resolve()
    out = args.output_dir if args.output_dir.is_absolute() else repo / args.output_dir
    files = []
    for current, dirs, names in __import__("os").walk(repo):
        current_path = Path(current)
        rel_parts = current_path.relative_to(repo).parts
        dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
        if any(part in SKIP_PARTS for part in rel_parts):
            continue
        files.extend(current_path / name for name in names)
    source = {p: text(p) if p.suffix.lower() in TEXT_SUFFIXES else "" for p in files}
    selected: list[Path] = []
    match_terms: dict[Path, list[str]] = {}
    for path in files:
        rel = path.relative_to(repo)
        haystack = f"{rel.as_posix()}\n{source[path]}".lower()
        hits = [term for term in TERMS if term.lower() in haystack]
        if hits:
            selected.append(path)
            match_terms[path] = hits
    selected_set = set(selected)
    basename_to_selected: dict[str, list[Path]] = defaultdict(list)
    for candidate in selected:
        basename_to_selected[candidate.name.lower()].append(candidate)
    reverse_references: dict[Path, set[str]] = defaultdict(set)
    forward_references: dict[Path, set[str]] = defaultdict(set)
    # Parse path-like tokens once per text file instead of repeatedly scanning the
    # complete repository for every inventory row (the former implementation was
    # intentionally simple but too slow for the legacy V22 tree).
    token_re = re.compile(r"[A-Za-z0-9_./\\-]+\.(?:py|ps1|md|txt|json|ini|toml|cfg|ya?ml)", re.I)
    for source_path, body in source.items():
        if not body:
            continue
        source_rel = source_path.relative_to(repo).as_posix()
        for token in token_re.findall(body):
            for candidate in basename_to_selected.get(Path(token).name.lower(), []):
                if candidate != source_path:
                    candidate_rel = candidate.relative_to(repo).as_posix()
                    reverse_references[candidate].add(source_rel)
                    if source_path in selected_set:
                        forward_references[source_path].add(candidate_rel)
    records = []
    dependency_map: dict[str, dict[str, list[str]]] = {}
    for path in sorted(selected, key=lambda p: p.relative_to(repo).as_posix().lower()):
        rel = path.relative_to(repo)
        should_move, target, wrapper, basis = destination(rel)
        references = sorted(reverse_references[path])
        is_shared = rel.name in {"AGENTS.md", "README.md", "pytest.ini", "requirements.lock.txt", ".gitignore", "CODEX_GOAL.md", "CODEX_PLAN.md", "CODEX_STATUS.md"}
        record = {
            "original_path": rel.as_posix(),
            "file_type": path.suffix.lower() or "extensionless",
            "fast3_ownership_basis": basis,
            "matched_terms": match_terms[path],
            "referenced_by": references,
            "is_runtime_entry": path.suffix.lower() == ".ps1" or (path.suffix.lower() == ".py" and "if __name__" in source[path]),
            "should_migrate": should_move,
            "suggested_new_path": target,
            "compatibility_wrapper_required": wrapper,
            "contains_frozen_research_contract": any(x in source[path].lower() for x in ("confirmation", "validation", "embargo", "frozen")),
            "contains_actual_run_result": any(x in source[path].lower() for x in ("final_status=", "mean_net_return", "final_decision")),
            "is_shared_module": is_shared or (not should_move and "shared" in basis),
        }
        records.append(record)
        dependency_map[rel.as_posix()] = {"referenced_by": record["referenced_by"], "references_fast3_files": []}
    for path in selected_set:
        body = source[path].lower().replace("\\", "/")
        rel = path.relative_to(repo).as_posix()
        dependency_map[rel]["references_fast3_files"] = sorted(forward_references[path])
    out.mkdir(parents=True, exist_ok=True)
    (out / "FAST3_000_FILE_INVENTORY.json").write_text(json.dumps({"terms": TERMS, "file_count": len(records), "files": records}, indent=2), encoding="utf-8")
    (out / "FAST3_000_DEPENDENCY_MAP.json").write_text(json.dumps({"file_count": len(dependency_map), "dependencies": dependency_map}, indent=2), encoding="utf-8")
    print(f"FAST3_INVENTORY_COUNT={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
