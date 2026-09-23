"""Synthetic tests for the derived view; never read real research outcomes."""
import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("research_inventory_under_test", Path(__file__).with_name("research_inventory.py"))
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory(prefix="inventory-test-", dir=os.environ.get("US_TECH_QUANT_TEST_TMP_ROOT")) as directory:
        yield Path(directory)


def normalize(value):
    return value.casefold().replace("_", "-")


def context():
    return {
        "registry_head_sha256": "a" * 64,
        "entities": [
            {"entity_id": "EXISTING", "canonical_name": "Existing", "status": "OPEN", "row_hash": "b" * 64, "metadata": {"authoritative_artifact_refs": ["scripts/v22/old.py"]}},
            {"entity_id": "NEW_CLOSED", "canonical_name": "New Closed", "status": "CLOSED", "row_hash": "c" * 64, "metadata": {"final_status": "PARKED", "research_family": "synthetic-mechanism"}},
        ],
        "aliases": [{"entity_id": "EXISTING", "alias": "Old Alias", "alias_normalized": "old alias"}],
    }


def test_preserves_every_legacy_cell_and_exposes_conflicts_and_missing_ids(workspace):
    fields = ["canonical_branch_id", "branch_status", "reason", "known_aliases", "custom_old_field"]
    legacy = [
        dict(zip(fields, ["Old Alias", "CLOSED_NEGATIVE", "Prior conclusion retained", "old labels", "must survive"])),
        dict(zip(fields, ["UNREGISTERED", "CLOSED_NEGATIVE", "do not lose failed work", "", ""])),
    ]
    columns, rows = inventory.build_inventory(fields, legacy, context(), normalize, repo_root=workspace,
        path_map={"scripts/v22/old.py": "archive/research/old.py"})
    assert columns[:len(fields)] == fields
    assert len(rows) == 3
    for original, output in zip(legacy, rows):
        assert {field: output[field] for field in fields} == original
    assert rows[0]["registry_entity_id"] == "EXISTING"
    assert rows[0]["inventory_status_comparison"].startswith("CONFLICT_")
    assert "archive/research/old.py" in rows[0]["inventory_relocated_source_refs"]
    assert rows[1]["registry_status"] == "UNREGISTERED_REVIEW_REQUIRED"
    assert rows[2]["registry_status"] == "CLOSED"
    assert rows[2]["branch_status"] == ""
    assert rows[2]["registry_final_status"] == "PARKED"
    assert "NOT_FOUND_REQUIRES_REVIEW" in inventory.markdown_inventory(rows, "a" * 64)


def test_duplicate_legacy_aliases_cannot_silently_drop_history(workspace):
    with pytest.raises(ValueError, match="DUPLICATE_LEGACY_IDENTITY"):
        inventory.build_inventory(["canonical_branch_id"], [{"canonical_branch_id": "EXISTING"}, {"canonical_branch_id": "Old Alias"}], context(), normalize, repo_root=workspace)


class FakeRegistry:
    class RegistryError(ValueError):
        pass
    normalize_alias = staticmethod(normalize)

    def validate_registry(self, root, validate_all=False):
        return {"status": "PASS", "head_sha256": "a" * 64}

    def export_context(self, root, output, snapshot):
        output.write_text(json.dumps(context()), encoding="utf-8")

    def current_state(self, root):
        return {"head_sha256": "a" * 64}

    def query_registry(self, root, entity_id=None, alias=None):
        if alias:
            raise self.RegistryError("ALIAS_NOT_FOUND:" + alias)
        return {"head_sha256": "a" * 64, "entities": []}


def test_refresh_updates_existing_manifest_counts_and_hash_without_registry_mutation(workspace, monkeypatch):
    repo, old, output = workspace / "repo", workspace / "old", workspace / "output"
    repo.mkdir()
    old.mkdir()
    table = old / "research_branch_registry_current.csv"
    table.write_text("canonical_branch_id,branch_status,reason\nEXISTING,CLOSED_NEGATIVE,keep this\n", encoding="utf-8")
    (old / "hash_manifest.json").write_text(json.dumps({"branch_count": 1, "branch_status_counts": {"CLOSED_NEGATIVE": 1}, "frozen_audit_registry_sha256": "d" * 64}), encoding="utf-8")
    monkeypatch.setattr(inventory, "load_registry", lambda path: (FakeRegistry(), workspace / "registry"))
    monkeypatch.setattr(inventory, "accepted_context", lambda registry, root, head: context())
    args = argparse.Namespace(repo_root=repo, legacy_table=table, output=output / table.name,
        markdown_output=repo / "docs/research/README.md", manifest_output=None, path_map=None, backup_output=None)
    result = inventory.refresh(args)
    manifest = json.loads((output / "hash_manifest.json").read_text(encoding="utf-8"))
    assert result["registry_mutated"] is False
    assert manifest["branch_count"] == 2
    assert sum(manifest["branch_status_counts"].values()) == 2
    assert manifest["current_status_counts"] == {"CLOSED": 1, "OPEN": 1}
    assert manifest["frozen_audit_registry_sha256"] == "d" * 64
    content = args.output.read_bytes()
    assert manifest["artifacts"][table.name] == {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    assert list(csv.DictReader(io.StringIO(content.decode())))[0]["reason"] == "keep this"
    assert not list(output.glob(".inventory-*"))


def test_missing_registry_alias_still_finds_unregistered_source_names(workspace, monkeypatch):
    source = workspace / "archive/research/legacy_mechanism.py"
    source.parent.mkdir(parents=True)
    source.write_text("raise RuntimeError('must never import or read source')", encoding="utf-8")
    monkeypatch.setattr(inventory, "load_registry", lambda path: (FakeRegistry(), workspace / "registry"))
    args = argparse.Namespace(repo_root=workspace, text=None, entity_id=None, alias="legacy mechanism")
    result = inventory.query(args)
    assert result["status"] == "FOUND_REVIEW_REQUIRED"
    assert result["source_name_matches"] == ["archive/research/legacy_mechanism.py"]
    assert result["new_research_authorized"] is False
    args.alias = "completely absent concept"
    assert inventory.query(args)["status"] == "NOT_FOUND_REQUIRES_REVIEW"


def test_keyword_search_covers_archive_root_and_legacy_scripts_only(workspace):
    paths = ["archive/research/legacy_mechanism.py", "legacy_mechanism.ps1", "scripts/v20/legacy_mechanism.py"]
    for relative in paths + ["unrelated_cache/legacy_mechanism.py"]:
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("contents must not be read", encoding="utf-8")
    assert inventory.source_matches(workspace, "legacy mechanism") == sorted(paths)


def test_markdown_uses_compact_table_and_escaped_complete_details(workspace):
    fields = ["canonical_branch_id", "branch_status", "reason", "primary_hypothesis", "known_aliases"]
    legacy = [{"canonical_branch_id": "EXISTING", "branch_status": "CLOSED_NEGATIVE", "reason": '<unsafe>&"quote"', "primary_hypothesis": "complete mechanism", "known_aliases": "original alias"}]
    _, rows = inventory.build_inventory(fields, legacy, context(), normalize, repo_root=workspace)
    document = inventory.markdown_inventory(rows, "a" * 64)
    assert "| Canonical ID | 当前登记状态 | 旧状态 | 核对 |" in document
    assert document.count("<details><summary>") == 2
    assert "&lt;unsafe&gt;&amp;&quot;quote&quot;" in document
    assert "<unsafe>" not in document
    assert all(value in document for value in ["complete mechanism", "original alias", "scripts/v22/old.py", "Old Alias"])


def test_alias_metadata_read_requires_exact_accepted_manifest_hash(workspace):
    import pyarrow as pa
    import pyarrow.parquet as pq

    head = "a" * 64
    alias_path = workspace / "snapshots" / head / "registry_aliases.parquet"
    alias_path.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(context()["aliases"]), alias_path)
    accepted_hash = hashlib.sha256(alias_path.read_bytes()).hexdigest()
    registry = SimpleNamespace(
        SNAPSHOTS_DIR="snapshots", ALIASES_FILE="registry_aliases.parquet",
        current_state=lambda root: {"head_sha256": head, "snapshot": {"files": {"registry_aliases.parquet": accepted_hash}}},
        query_registry=lambda root, snapshot: {"entities": context()["entities"]},
    )
    assert inventory.accepted_context(registry, workspace, head)["aliases"] == context()["aliases"]
    alias_path.write_bytes(b"different bytes must not be decoded")
    with pytest.raises(ValueError, match="ACCEPTED_ALIAS_FILE_HASH_MISMATCH"):
        inventory.accepted_context(registry, workspace, head)
