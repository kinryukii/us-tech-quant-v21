"""Exact source bootstrap for this task; no input reads, fitting or accounts.

Call bootstrap before importing the history runner, FinalActionOverlay or any
financial owner. The returned module is the retained account owner, not a new
engine. A source binding never grants numerical or evaluation permission;
callers still need the phase's independently validated task authority.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import importlib.machinery
import json
from pathlib import Path
import re
import sys
import types

TASK = "A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1"
SCHEMA = "BASE_CONDITIONED_GROSS_RUNTIME_BINDING_R1"
STATUS = "ROOT_SEALED_SOURCE_ONLY_RUNTIME"
REPO = Path("D:/us-tech-quant")
RESULTS = Path("D:/us-tech-quant-results/_maintenance") / TASK
BINDING_PATH = RESULTS / "RUNTIME_SOURCE_BINDING_R1.json"
PHASES = ("HISTORY2024", "FROZEN2026")
MARKER = "_base_conditioned_gross_source_custody"
WORKTREE = Path("D:/us-tech-quant-worktrees/a-repair-ca-source-20261011-r1")
OWNERS = (
    ("ca_owner_ref", "scripts.v22.corporate_action_transition_r1",
     WORKTREE / "scripts/v22/corporate_action_transition_r1.py",
     "a04c6d2eddc713fda0d30eb7aefdb08e349798ed7ed5c41923b2be7fe69c2042"),
    ("account_owner_ref", "scripts.research.a2.evaluation.continuous_research_account",
     WORKTREE / "scripts/research/a2/evaluation/continuous_research_account.py",
     "4dd3b001485afab6bff4bb618391814f34063f7e262fb9a51a9864103fef9253"),
)


def _need(condition, code):
    if not condition:
        raise ValueError("BASE_GROSS_RUNTIME_" + code)


def _physical(ref, *, limit=200_000):
    _need(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
          and isinstance(ref["path"], str)
          and re.fullmatch(r"[0-9a-f]{64}", str(ref["sha256"])) is not None,
          "EXACT_REFERENCE_REQUIRED")
    path = Path(ref["path"])
    _need(path.is_file() and path.stat().st_size <= limit, "BOUNDED_SOURCE_OR_METADATA_REQUIRED")
    raw = path.read_bytes()
    _need(hashlib.sha256(raw).hexdigest() == ref["sha256"], "REFERENCE_CHANGED")
    return path, raw


def _same_path(left, right):
    return Path(left).resolve() == Path(right).resolve()


def source_execution_context(binding_ref, *, phase):
    """Check only the bounded new-task binding and selected source bytes."""
    _need(phase in PHASES, "EXACT_PHASE_REQUIRED")
    _need(isinstance(binding_ref, dict)
          and _same_path(binding_ref.get("path", ""), BINDING_PATH), "NEW_TASK_BINDING_PATH_REQUIRED")
    _, raw = _physical(binding_ref, limit=64_000)
    binding = json.loads(raw)
    _need(isinstance(binding, dict) and binding.get("schema") == SCHEMA
          and binding.get("task_id") == TASK and binding.get("status") == STATUS,
          "NEW_TASK_ROOT_SEAL_REQUIRED")
    _need(binding.get("allowed_phases") == list(PHASES), "EXACT_PHASES_REQUIRED")
    helper = binding.get("runtime_helper_ref")
    _physical(helper)
    _need(_same_path(helper["path"], __file__), "HELPER_OWNER_CHANGED")
    scope = binding.get("scope_ref")
    _need(isinstance(scope, dict) and Path(scope.get("path", "")).resolve().parent == RESULTS.resolve(),
          "NEW_TASK_SCOPE_PATH_REQUIRED")
    _, scope_raw = _physical(scope, limit=200_000)
    _need(json.loads(scope_raw).get("task_id") == TASK, "NEW_TASK_SCOPE_REQUIRED")
    for key, _, path, digest in OWNERS:
        ref = binding.get(key)
        _need(isinstance(ref, dict) and _same_path(ref.get("path", ""), path)
              and ref.get("sha256") == digest, "FROZEN_OWNER_CHANGED")
        _physical(ref)
    return {"task_id": TASK, "binding_ref": dict(binding_ref), "phase": phase,
            "binding": binding, "numerical_permission_granted": False}


def _functions(value):
    if isinstance(value, (staticmethod, classmethod)):
        return (value.__func__,)
    if isinstance(value, property):
        return tuple(x for x in (value.fget, value.fset, value.fdel) if x is not None)
    return (value,) if isinstance(value, types.FunctionType) else ()


def _snapshot(module):
    """Keep identities of executed local functions/classes and their code."""
    def signature(value):
        return tuple((fn, fn.__code__, id(fn.__globals__), id(fn.__defaults__), id(fn.__kwdefaults__))
                     for fn in _functions(value))
    functions, classes = {}, {}
    for name, value in vars(module).items():
        if getattr(value, "__module__", None) != module.__name__:
            continue
        if isinstance(value, types.FunctionType):
            functions[name] = signature(value)
        elif isinstance(value, type):
            classes[name] = (value, {name: signature(member) for name, member in vars(value).items()
                                    if _functions(member)})
    return functions, classes


def _seal(context, key, name):
    return {"task_id": TASK, "binding_ref": context["binding_ref"],
            "canonical_name": name, "source_ref": context["binding"][key]}


def _assert_owner(context, key, name):
    module = sys.modules.get(name)
    ref = context["binding"][key]
    path, _ = _physical(ref)
    _need(isinstance(module, types.ModuleType)
          and _same_path(getattr(module, "__file__", ""), path), "CANONICAL_SOURCE_COLLISION")
    _need(getattr(module, MARKER, None) == _seal(context, key, name), "NEW_TASK_INSTANCE_REQUIRED")
    spec = getattr(module, "__spec__", None)
    _need(spec is not None and spec.name == name and _same_path(spec.origin or "", path)
          and module.__name__ == name and module.__package__ == name.rsplit(".", 1)[0]
          and spec.loader is module.__loader__
          and type(spec.loader) is importlib.machinery.SourceFileLoader
          and spec.loader.name == name and _same_path(spec.loader.path, path), "CANONICAL_SPEC_CHANGED")
    parent = sys.modules.get(name.rsplit(".", 1)[0])
    _need(parent is not None and getattr(parent, name.rsplit(".", 1)[1], None) is module,
          "CANONICAL_PARENT_CHANGED")
    _need(getattr(module, MARKER + "_code", None) == _snapshot(module), "EXECUTED_CODE_CHANGED")
    return module


def _install(context, key, name):
    if name in sys.modules:
        return _assert_owner(context, key, name)
    ref = context["binding"][key]
    path, raw = _physical(ref)
    parent_name, leaf = name.rsplit(".", 1)
    parent = importlib.import_module(parent_name)
    _need(getattr(parent, "__file__", None) is None
          and {Path(p).resolve() for p in getattr(parent, "__path__", ())}
          == {REPO.joinpath(*parent_name.split(".")).resolve()}, "CANONICAL_NAMESPACE_REQUIRED")
    _need(not hasattr(parent, leaf), "PREEXISTING_PARENT_ALIAS")
    spec = importlib.util.spec_from_file_location(name, path)
    _need(spec is not None and spec.loader is not None, "SOURCE_LOADER_REQUIRED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        # Execute the verified selected source, never a possibly stale pyc.
        exec(compile(raw, str(path), "exec"), module.__dict__)
        _physical(ref)
        setattr(module, MARKER, _seal(context, key, name))
        setattr(module, MARKER + "_code", _snapshot(module))
        setattr(parent, leaf, module)
        return _assert_owner(context, key, name)
    except BaseException:
        if sys.modules.get(name) is module:
            del sys.modules[name]
        if getattr(parent, leaf, None) is module:
            delattr(parent, leaf)
        raise


def bootstrap(binding_ref, *, phase):
    """Install CA first, then the original CBC; return that CBC module.

    A preloaded other-task module is never overwritten. Use a fresh Python
    process and call this function before importing any financial consumer.
    """
    context = source_execution_context(binding_ref, phase=phase)
    # Check all collisions before creating even the first selected owner.
    for key, name, _, _ in OWNERS:
        if name in sys.modules:
            _assert_owner(context, key, name)
    for key, name, _, _ in OWNERS:
        _install(context, key, name)
    return _assert_owner(context, OWNERS[-1][0], OWNERS[-1][1])


def assert_runtime(binding_ref, *, phase):
    """Source-only receipt; does not validate datasets, models or authority."""
    context = source_execution_context(binding_ref, phase=phase)
    for key, name, _, _ in OWNERS:
        _assert_owner(context, key, name)
    return {"task_id": TASK, "binding_ref": dict(binding_ref), "phase": phase,
            "source_refs": {key: context["binding"][key] for key, *_ in OWNERS},
            "canonical_source_identity_verified": True, "numerical_permission_granted": False,
            "new_account_engine": False, "old_task_authority_reused": False}