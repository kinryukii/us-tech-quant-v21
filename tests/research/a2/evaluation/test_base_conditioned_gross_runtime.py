"""Synthetic source modules only; no account, financial data or model fitting."""
import hashlib
import json
from pathlib import Path
import sys
import types

import pytest

from scripts.research.a2.evaluation import base_conditioned_gross_runtime as runtime


def ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def binding(tmp_path, monkeypatch):
    namespace = "gross_runtime_synthetic"
    parent = types.ModuleType(namespace)
    package = tmp_path / namespace
    package.mkdir()
    parent.__path__ = [str(package)]
    monkeypatch.setattr(runtime, "REPO", tmp_path)
    monkeypatch.setitem(sys.modules, namespace, parent)
    owners = []
    for key, leaf in (("ca_owner_ref", "ca"), ("account_owner_ref", "account")):
        path = package / (leaf + ".py")
        path.write_text("def value():\n    return 7\n\nclass Event:\n    def clock(self):\n        return 3\n", encoding="utf-8")
        owners.append((key, namespace + "." + leaf, path, ref(path)["sha256"]))
    monkeypatch.setattr(runtime, "OWNERS", tuple(owners))
    monkeypatch.setattr(runtime, "RESULTS", tmp_path)
    path = tmp_path / "RUNTIME_SOURCE_BINDING_R1.json"
    monkeypatch.setattr(runtime, "BINDING_PATH", path)
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"task_id": runtime.TASK}), encoding="utf-8")
    doc = dict(schema=runtime.SCHEMA, task_id=runtime.TASK, status=runtime.STATUS,
               runtime_helper_ref=ref(Path(runtime.__file__)), scope_ref=ref(scope),
               allowed_phases=list(runtime.PHASES))
    doc.update({key: ref(source) for key, _, source, _ in owners})
    def save():
        path.write_text(json.dumps(doc), encoding="utf-8")
        return ref(path)
    yield doc, save, parent, owners
    for _, name, _, _ in owners:
        sys.modules.pop(name, None)


def test_bootstrap_exact_sources_is_idempotent_and_source_only(binding):
    _, save, parent, owners = binding
    pin = save()
    module = runtime.bootstrap(pin, phase="HISTORY2024")
    assert module is parent.account
    assert module.value() == 7
    assert runtime.bootstrap(pin, phase="HISTORY2024") is module
    result = runtime.assert_runtime(pin, phase="FROZEN2026")
    assert result["canonical_source_identity_verified"]
    assert not result["numerical_permission_granted"]
    assert not result["old_task_authority_reused"]
    assert sys.modules[owners[0][1]] is parent.ca


@pytest.mark.parametrize("field,value,reason", [
    ("task_id", "OLD_TASK", "NEW_TASK_ROOT_SEAL_REQUIRED"),
    ("status", "DRAFT", "NEW_TASK_ROOT_SEAL_REQUIRED"),
    ("allowed_phases", ["FROZEN2026"], "EXACT_PHASES_REQUIRED"),
])
def test_wrong_task_unsealed_or_changed_phases_rejected_before_import(binding, field, value, reason):
    doc, save, _, owners = binding
    doc[field] = value
    with pytest.raises(ValueError, match=reason):
        runtime.bootstrap(save(), phase="HISTORY2024")
    assert all(name not in sys.modules for _, name, _, _ in owners)


def test_unknown_phase_rejected(binding):
    _, save, _, _ = binding
    with pytest.raises(ValueError, match="EXACT_PHASE_REQUIRED"):
        runtime.bootstrap(save(), phase="FIT")


def test_future_or_old_task_scope_cannot_be_substituted(binding):
    doc, save, _, _ = binding
    scope = Path(doc["scope_ref"]["path"])
    scope.write_text(json.dumps({"task_id": "OLD_TASK"}), encoding="utf-8")
    doc["scope_ref"] = ref(scope)
    with pytest.raises(ValueError, match="NEW_TASK_SCOPE_REQUIRED"):
        runtime.bootstrap(save(), phase="HISTORY2024")


def test_changed_selected_source_rejected_before_import(binding):
    _, save, _, owners = binding
    pin = save()
    owners[0][2].write_text("raise RuntimeError('must never execute')", encoding="utf-8")
    with pytest.raises(ValueError, match="REFERENCE_CHANGED"):
        runtime.bootstrap(pin, phase="HISTORY2024")
    assert all(name not in sys.modules for _, name, _, _ in owners)


def test_existing_other_task_account_prevents_partial_ca_import(binding, monkeypatch):
    _, save, _, owners = binding
    old = types.ModuleType(owners[1][1])
    old.__file__ = str(owners[1][2])
    monkeypatch.setitem(sys.modules, owners[1][1], old)
    with pytest.raises(ValueError, match="NEW_TASK_INSTANCE_REQUIRED"):
        runtime.bootstrap(save(), phase="HISTORY2024")
    assert owners[0][1] not in sys.modules
    assert sys.modules[owners[1][1]] is old


@pytest.mark.parametrize("mutation", ["function", "class_method", "parent_alias"])
def test_loaded_source_mutations_rejected(binding, mutation):
    _, save, parent, _ = binding
    pin = save()
    module = runtime.bootstrap(pin, phase="HISTORY2024")
    if mutation == "function":
        module.value.__code__ = (lambda: 99).__code__
    elif mutation == "class_method":
        module.Event.clock = lambda self: 99
    else:
        parent.account = object()
    with pytest.raises(ValueError, match="EXECUTED_CODE_CHANGED|CANONICAL_PARENT_CHANGED"):
        runtime.assert_runtime(pin, phase="HISTORY2024")


def test_failed_module_import_removes_only_its_instance(binding, monkeypatch):
    doc, save, parent, owners = binding
    path = owners[1][2]
    path.write_text("raise RuntimeError('synthetic import failure')", encoding="utf-8")
    patched = (*owners[:1], (owners[1][0], owners[1][1], path, ref(path)["sha256"]))
    monkeypatch.setattr(runtime, "OWNERS", patched)
    doc["account_owner_ref"] = ref(path)
    with pytest.raises(RuntimeError, match="synthetic import failure"):
        runtime.bootstrap(save(), phase="HISTORY2024")
    assert owners[1][1] not in sys.modules
    assert not hasattr(parent, "account")
    assert sys.modules[owners[0][1]] is parent.ca

def test_other_namespace_root_is_rejected(binding):
    _, save, parent, owners = binding
    parent.__path__ = [str(Path(parent.__path__[0]).parent)]
    with pytest.raises(ValueError, match="CANONICAL_NAMESPACE_REQUIRED"):
        runtime.bootstrap(save(), phase="HISTORY2024")
    assert all(name not in sys.modules for _, name, _, _ in owners)