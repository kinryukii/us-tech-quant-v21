"""Refresh a derived research inventory and search existing work without outcomes.

The accepted research_registry.py remains the only identity authority. This
adapter preserves legacy CSV fields and never registers, reopens or deletes work.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import html
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Mapping, Sequence


DERIVED_FIELDS = (
    "registry_entity_id", "registry_status", "registry_head_sha256",
    "registry_row_hash", "registry_aliases", "registry_lifecycle_decision",
    "registry_final_status", "registry_source_refs", "registry_reopen_condition_ref",
    "inventory_status_comparison", "inventory_relocated_source_refs", "inventory_role",
)
SOURCE_ROOTS = (
    "scripts", "archive/research", "fast3", "fast4", "fast5", "fast6",
)


def load_registry(repo_root: Path):
    """Load the repository's existing implementation and compact configuration."""
    repo_root = repo_root.resolve()
    spec = importlib.util.spec_from_file_location(
        "ustq_inventory_registry", repo_root / "research_registry.py",
    )
    if spec is None or spec.loader is None:
        raise ValueError("REGISTRY_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config_path = repo_root / "config" / "research_registry.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if config.get("schema_version") != module.SCHEMA_VERSION:
        raise ValueError("CONFIG_SCHEMA_VERSION_INVALID")
    root = Path(config["registry_root"])
    return module, root if root.is_absolute() else (config_path.parent / root).resolve()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def accepted_context(registry: Any, root: Path, head: str) -> dict[str, Any]:
    """Use public reads and the accepted, hash-pinned metadata-only alias table.

    Some historical structural aliases are rejected by export_context's broader
    text firewall. Do not weaken it: the registry validator already checks this
    table's alias contract, and its accepted manifest pins the exact bytes.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    state = registry.current_state(root)
    if state["head_sha256"] != head:
        raise ValueError("REGISTRY_HEAD_CHANGED_RETRY_REFRESH")
    result = registry.query_registry(root, snapshot=head)
    alias_path = root / registry.SNAPSHOTS_DIR / head / registry.ALIASES_FILE
    content = alias_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != state["snapshot"]["files"][registry.ALIASES_FILE]:
        raise ValueError("ACCEPTED_ALIAS_FILE_HASH_MISMATCH")
    aliases = pq.read_table(pa.BufferReader(content), columns=["alias_normalized", "alias", "entity_id"]).to_pylist()
    return {"registry_head_sha256": head, "entities": result["entities"], "aliases": aliases}


def _references(entity: Mapping[str, Any]) -> list[str]:
    metadata = entity.get("metadata", {})
    values = []
    for field in ("code_reference", "source_contract_ref", "authoritative_artifact_refs"):
        value = metadata.get(field)
        values.extend(value if isinstance(value, list) else [value] if value else [])
    return list(dict.fromkeys(str(value) for value in values))


def _comparison(legacy: str, current: str) -> str:
    if not legacy:
        return "NO_LEGACY_STATUS"
    if legacy == current:
        return "SAME_STATUS"
    terminal = {"CLOSED", "TOMBSTONED", "SUPERSEDED"}
    if legacy.startswith("CLOSED") and current not in terminal:
        return "CONFLICT_LEGACY_CLOSED_CURRENT_NONTERMINAL_REVIEW_REQUIRED"
    if legacy.startswith(("OPEN", "FORWARD", "FROZEN", "INFRASTRUCTURE")) and current in terminal:
        return "DIFFERENT_LEGACY_NONTERMINAL_CURRENT_TERMINAL_REVIEW_REQUIRED"
    return "DIFFERENT_STATUS_VOCABULARY_REVIEW_REQUIRED"


def _relocated(refs: Sequence[str], path_map: Mapping[str, str], repo_root: Path) -> str:
    prefix = repo_root.as_posix().rstrip("/") + "/"
    normalized_map = {key.replace("\\", "/"): value for key, value in path_map.items()}
    matches = []
    for reference in refs:
        normalized = reference.replace("\\", "/")
        relative = normalized[len(prefix):] if normalized.casefold().startswith(prefix.casefold()) else normalized
        replacement = normalized_map.get(normalized, normalized_map.get(relative))
        if replacement:
            matches.append(f"{reference} => {replacement}")
    return "; ".join(matches)


def build_inventory(
    fields: Sequence[str], legacy_rows: Sequence[Mapping[str, str]],
    context: Mapping[str, Any], normalize_alias: Callable[[str], str],
    *, repo_root: Path, path_map: Mapping[str, str] | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    """Keep every legacy cell; append derived metadata and missing accepted IDs."""
    if not fields or "canonical_branch_id" not in fields or len(set(fields)) != len(fields):
        raise ValueError("LEGACY_CANONICAL_ID_AND_UNIQUE_FIELDS_REQUIRED")
    entities = {row["entity_id"]: row for row in context["entities"]}
    aliases: dict[str, list[str]] = {identity: [] for identity in entities}
    alias_ids: dict[str, str] = {}
    for row in context["aliases"]:
        identity = row["entity_id"]
        aliases[identity].append(row["alias"])
        alias_ids[row["alias_normalized"]] = identity
    for identity, entity in entities.items():
        alias_ids[normalize_alias(identity)] = identity
        alias_ids[normalize_alias(entity["canonical_name"])] = identity
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for original in legacy_rows:
        row = dict(original)
        candidate = row.get("canonical_branch_id", "")
        identity = candidate if candidate in entities else alias_ids.get(normalize_alias(candidate)) if candidate else None
        if identity in seen:
            raise ValueError(f"DUPLICATE_LEGACY_IDENTITY:{identity}")
        if identity:
            seen.add(identity)
        row["registry_entity_id"] = identity or ""
        rows.append(row)
    for identity in sorted(set(entities) - seen):
        entity = entities[identity]
        metadata = entity.get("metadata", {})
        source_refs = _references(entity)
        seed = {
            "canonical_branch_id": identity,
            "known_aliases": "; ".join(sorted(aliases[identity])),
            "branch_cluster": metadata.get("research_branch_cluster", metadata.get("research_family")),
            "primary_hypothesis": metadata.get("economic_thesis", metadata.get("economic_mechanism")),
            "information_source": metadata.get("information_source"),
            "target_or_outcome": metadata.get("target_definition", metadata.get("target")),
            "outcome_horizon": metadata.get("outcome_horizon"),
            "model_or_scoring_family": metadata.get("model_family"),
            "action_locus": entity.get("decision_layer"),
            "economic_translation": metadata.get("portfolio_action", metadata.get("portfolio_role")),
            "temporal_contract": metadata.get("temporal_contract"),
            "primary_source_path": "; ".join(source_refs),
            "primary_result_path": metadata.get("research_knowledge_ref"),
            "parent_or_predecessor": metadata.get("parent_entity_ids", entity.get("parent_entity_id")),
            "equivalence_class": metadata.get("equivalence_class"),
            "reason": metadata.get("lifecycle_reason"),
        }
        row = {field: _text(seed.get(field)) for field in fields}
        row["registry_entity_id"] = identity
        rows.append(row)
    for row in rows:
        identity = row["registry_entity_id"]
        row["inventory_role"] = "DERIVED_VIEW_NOT_IDENTITY_AUTHORITY"
        row["registry_head_sha256"] = context["registry_head_sha256"]
        if not identity:
            for field in DERIVED_FIELDS:
                if field not in {"inventory_role", "registry_head_sha256"}:
                    row[field] = ""
            row["registry_status"] = "UNREGISTERED_REVIEW_REQUIRED"
            row["inventory_status_comparison"] = "LEGACY_ID_NOT_IN_ACCEPTED_REGISTRY"
            continue
        entity = entities[identity]
        metadata = entity.get("metadata", {})
        row.update({
            "registry_status": entity["status"], "registry_row_hash": entity["row_hash"],
            "registry_aliases": "; ".join(sorted(aliases[identity])),
            "registry_lifecycle_decision": _text(metadata.get("lifecycle_decision")),
            "registry_final_status": _text(metadata.get("final_status")),
            "registry_source_refs": "; ".join(_references(entity)),
            "registry_reopen_condition_ref": _text(metadata.get("reopen_condition_ref")),
            "inventory_status_comparison": _comparison(row.get("branch_status", ""), entity["status"]),
            "inventory_relocated_source_refs": _relocated(_references(entity), path_map or {}, repo_root),
        })
    return list(fields) + [field for field in DERIVED_FIELDS if field not in fields], rows


def markdown_inventory(rows: Sequence[Mapping[str, str]], head: str) -> str:
    def cell(value: Any) -> str:
        return _text(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    def anchor(identity: str) -> str:
        return "research-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    ordered = sorted(rows, key=lambda r: r.get("registry_entity_id") or r.get("canonical_branch_id", ""))
    lines = [
        "# 研究复用索引", "",
        "这是既有注册表的派生导航视图，不是新的身份、研究结论或授权依据。旧表字段原样保留；空白表示元数据未登记。",
        f"本次读取的 accepted registry head：`{head}`。", "",
        "开始新工作前：先按机制关键词及旧别名 query，并核对未登记的本地源码；再运行既有 research_registry.py preflight-proposal。",
        "查询覆盖全部注册状态，包括关闭和 tombstone。NOT_FOUND_REQUIRES_REVIEW 不代表允许新建；直接脚本可能未登记，后续研究仍须原有契约。",
        "归档位置只作导航，不改写原冻结引用。状态口径或历史结论不一致会显式提示，不能据此重开研究。", "",
        "```powershell",
        "python -B scripts/maintenance/research_inventory.py query --repo-root . --text \"机制关键词\"",
        "python -B scripts/maintenance/research_inventory.py query --repo-root . --alias \"旧别名\"",
        "python -B research_registry.py preflight-proposal --proposal <proposal.json>",
        "```", "",
        "| Canonical ID | 当前登记状态 | 旧状态 | 核对 |",
        "| --- | --- | --- | --- |",
    ]
    for row in ordered:
        identity = row.get("registry_entity_id") or row.get("canonical_branch_id", "")
        comparison = row.get("inventory_status_comparison", "")
        review = {"SAME_STATUS": "一致", "NO_LEGACY_STATUS": "无旧状态"}.get(comparison, "需核对")
        values = [f"[{cell(identity)}](#{anchor(identity)})", row.get("registry_status"), row.get("branch_status") or "—", review]
        lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    lines.extend(["", "点击 ID 跳到对应条目，再展开查看机制、结论、原始引用和别名。", ""])
    for row in ordered:
        identity = row.get("registry_entity_id") or row.get("canonical_branch_id", "")
        lines.extend([f'<a id="{anchor(identity)}"></a>', f"<details><summary>{html.escape(identity)}</summary>", ""])
        details = [
            ("机制 / 假设", row.get("primary_hypothesis") or row.get("branch_cluster")),
            ("旧结论", row.get("reason")),
            ("旧状态", row.get("branch_status")),
            ("登记完成状态", row.get("registry_final_status")),
            ("登记生命周期决策", row.get("registry_lifecycle_decision")),
            ("状态核对", row.get("inventory_status_comparison")),
            ("原始引用", row.get("primary_source_path")),
            ("登记引用", row.get("registry_source_refs")),
            ("迁移位置", row.get("inventory_relocated_source_refs")),
            ("旧别名", row.get("known_aliases")),
            ("登记别名", row.get("registry_aliases")),
            ("重开条件引用", row.get("registry_reopen_condition_ref")),
        ]
        for label, value in details:
            if value:
                lines.append(f"<p><strong>{html.escape(label)}：</strong>{html.escape(_text(value))}</p>")
        lines.extend(["", "</details>", ""])
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".inventory-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def refresh(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo_root.resolve()
    output = args.output.resolve()
    markdown_output = args.markdown_output.resolve()
    manifest_output = args.manifest_output.resolve() if args.manifest_output else output.with_name("hash_manifest.json")
    if len({output, markdown_output, manifest_output}) != 3:
        raise ValueError("OUTPUT_PATHS_MUST_BE_DISTINCT")
    if output == repo or repo in output.parents:
        raise ValueError("CSV_OUTPUT_MUST_BE_EXTERNAL_TO_REPOSITORY")
    registry, root = load_registry(repo)
    validation = registry.validate_registry(root, validate_all=False)
    if validation["status"] != "PASS":
        raise ValueError(f"REGISTRY_VALIDATION_FAILED:{validation['errors']}")
    head = validation["head_sha256"]
    legacy_bytes = args.legacy_table.read_bytes()
    legacy_manifest_path = args.legacy_table.with_name("hash_manifest.json")
    legacy_manifest = json.loads(legacy_manifest_path.read_text(encoding="utf-8-sig")) if legacy_manifest_path.exists() else {}
    if not isinstance(legacy_manifest, dict):
        raise ValueError("LEGACY_MANIFEST_MUST_BE_OBJECT")
    reader = csv.DictReader(io.StringIO(legacy_bytes.decode("utf-8-sig"), newline=""))
    fields, legacy_rows = reader.fieldnames or [], list(reader)
    path_map = json.loads(args.path_map.read_text(encoding="utf-8-sig")) if args.path_map else {}
    if not isinstance(path_map, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in path_map.items()):
        raise ValueError("PATH_MAP_MUST_MAP_EXACT_OLD_PATHS_TO_NEW_PATHS")
    output.parent.mkdir(parents=True, exist_ok=True)
    context = accepted_context(registry, root, head)
    columns, rows = build_inventory(fields, legacy_rows, context, registry.normalize_alias, repo_root=repo, path_map=path_map)
    if registry.current_state(root)["head_sha256"] != head:
        raise ValueError("REGISTRY_HEAD_CHANGED_RETRY_REFRESH")
    if output == args.legacy_table.resolve():
        if not args.backup_output:
            raise ValueError("IN_PLACE_REFRESH_REQUIRES_EXPLICIT_BACKUP_OUTPUT")
        backup = args.backup_output.resolve()
        if backup in {output, markdown_output, manifest_output} or backup.exists():
            raise ValueError("BACKUP_MUST_BE_NEW_DISTINCT_PATH")
        backup.parent.mkdir(parents=True, exist_ok=True)
        with backup.open("xb") as stream:
            stream.write(legacy_bytes)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    csv_content = buffer.getvalue()
    manifest = dict(legacy_manifest)
    manifest.setdefault("legacy_view_metadata", {
        "branch_count": legacy_manifest.get("branch_count"),
        "branch_status_counts": legacy_manifest.get("branch_status_counts"),
        "source_csv_sha256": hashlib.sha256(legacy_bytes).hexdigest(),
    })
    manifest.update({
        "current_registry_path": str(output), "branch_count": len(rows),
        "branch_status_counts": dict(sorted(Counter(row.get("branch_status") or "NOT_RECORDED_IN_LEGACY_VIEW" for row in rows).items())),
        "current_status_counts": dict(sorted(Counter(row["registry_status"] for row in rows).items())),
        "registry_head_sha256": head, "accepted_entity_count": len(context["entities"]),
        "derived_view": True, "identity_authority": str(root),
        "legacy_fields_note": "Original CSV fields and remaining historical manifest fields are preserved legacy context, not current registry decisions or authorization.",
    })
    artifacts = dict(manifest.get("artifacts", {}))
    artifacts[output.name] = {"bytes": len(csv_content.encode("utf-8")), "sha256": hashlib.sha256(csv_content.encode("utf-8")).hexdigest()}
    manifest["artifacts"] = artifacts
    _atomic_write(output, csv_content)
    _atomic_write(markdown_output, markdown_inventory(rows, head))
    _atomic_write(manifest_output, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {
        "status": "PASS", "registry_head_sha256": head, "registry_mutated": False,
        "legacy_row_count": len(legacy_rows), "accepted_entity_count": len(context["entities"]),
        "output_row_count": len(rows), "legacy_sha256": hashlib.sha256(legacy_bytes).hexdigest(),
        "unregistered_rows": [row["canonical_branch_id"] for row in rows if not row["registry_entity_id"]],
        "status_conflicts": [row["canonical_branch_id"] for row in rows if "CONFLICT" in row["inventory_status_comparison"]],
        "output": str(output), "markdown_output": str(markdown_output), "manifest_output": str(manifest_output),
    }


def _matches(text: str, needle: str) -> bool:
    tokens = re.findall(r"\w+", needle.casefold().replace("_", " "))
    haystack = text.casefold().replace("_", " ").replace("-", " ")
    return bool(tokens) and all(token in haystack for token in tokens)


def source_matches(repo: Path, needle: str) -> list[str]:
    """Inspect names only; no source, data, manifest or result contents are read."""
    matches = [path.name for path in repo.iterdir() if path.is_file() and path.suffix.casefold() in {".py", ".ps1"} and _matches(path.name, needle)]
    def fail(error: OSError) -> None:
        raise error
    for relative in SOURCE_ROOTS:
        root = repo / relative
        if not root.is_dir():
            continue
        for directory, folders, files in os.walk(root, followlinks=False, onerror=fail):
            folders[:] = [name for name in folders if name not in {".git", ".venv", "__pycache__"} and not (Path(directory) / name).is_symlink() and not getattr(Path(directory) / name, "is_junction", lambda: False)()]
            for name in files:
                path = Path(directory) / name
                if path.suffix.casefold() in {".py", ".ps1"} and _matches(name, needle):
                    matches.append(path.relative_to(repo).as_posix())
    return sorted(matches)


def query(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo_root.resolve()
    registry, root = load_registry(repo)
    needle = args.text or args.alias or args.entity_id
    if not needle:
        raise ValueError("QUERY_TEXT_ALIAS_OR_ENTITY_ID_REQUIRED")
    try:
        result = registry.query_registry(root, entity_id=args.entity_id, alias=args.alias)
    except registry.RegistryError as error:
        if not args.alias or not str(error).startswith("ALIAS_NOT_FOUND:"):
            raise
        result = registry.query_registry(root, entity_id="__unmatched_inventory_alias__")
    entities = result["entities"]
    if args.text:
        entities = [entity for entity in entities if _matches(json.dumps(entity, ensure_ascii=False), args.text)]
    sources = source_matches(repo, needle)
    return {
        "status": "FOUND_REVIEW_REQUIRED" if entities or sources else "NOT_FOUND_REQUIRES_REVIEW",
        "registry_head_sha256": result["head_sha256"], "entities": entities,
        "source_name_matches": sources, "source_search_roots": list(SOURCE_ROOTS),
        "repo_root_file_names_searched": True,
        "new_research_authorized": False,
        "next_step": "Review prior aliases, closed branches and unregistered source; run research_registry.py preflight-proposal with the applicable contract.",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("refresh")
    export.add_argument("--repo-root", type=Path, required=True)
    export.add_argument("--legacy-table", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--markdown-output", type=Path, required=True)
    export.add_argument("--backup-output", type=Path)
    export.add_argument("--manifest-output", type=Path, help="Defaults to hash_manifest.json beside the external CSV")
    export.add_argument("--path-map", type=Path, help="JSON object mapping exact old source paths to relocated paths")
    search = commands.add_parser("query")
    search.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    search.add_argument("--text")
    search.add_argument("--entity-id")
    search.add_argument("--alias")
    args = parser.parse_args(argv)
    try:
        result = refresh(args) if args.command == "refresh" else query(args)
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
