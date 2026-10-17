"""Original engineering registration owner, synthetic metadata only; no research imports."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.common.storage_paths import StoragePaths, assert_safe_output_path

_OWNER = Path(__file__).parents[4] / "scripts/research/a2/evaluation/hgb_policy_alignment.py"
_EXTENSION = _OWNER.with_name("three_strategy_extension.py")


def _load_owner():
    # Compile only the maintained owner functions. Its research/module imports,
    # main(), model/data consumers and real task record are never executed.
    tree = ast.parse(_OWNER.read_text(encoding="utf-8"))
    scope = {"__name__": "synthetic_registration_owner", "Path": Path, "json": json,
             "hashlib": hashlib, "assert_safe_output_path": assert_safe_output_path}
    constants = [n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id in ("SOURCE_FILES", "TASK_ID") for t in n.targets)]
    names = {"read", "record_path", "frozen_contract", "append_engineering_repair_refs"}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and (n.name in names or n.name.startswith("_engineering_") or n.name == "_checked_frozen_contract")]
    exec(compile(ast.fix_missing_locations(ast.Module(body=constants + functions, type_ignores=[])), str(_OWNER), "exec"), scope)
    extension = ast.parse(_EXTENSION.read_text(encoding="utf-8"))
    verify = [n for n in extension.body if isinstance(n, ast.FunctionDef) and n.name in ("reference", "verify_refs")]
    verify_scope = {"Path": Path, "hashlib": hashlib}
    exec(compile(ast.fix_missing_locations(ast.Module(body=verify, type_ignores=[])), str(_EXTENSION), "exec"), verify_scope)
    scope["extension"] = SimpleNamespace(**verify_scope)
    return scope


def _reference(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return _reference(path)


@pytest.fixture
def factory(tmp_path):
    number = 0
    def build(count=2, opaque_size=300):
        nonlocal number
        number += 1
        base = tmp_path / str(number)
        paths = StoragePaths(**{name: base / name for name in
            ("repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")})
        scope = _load_owner()
        old = {}
        for name in scope["SOURCE_FILES"]:
            file = paths.repo_root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("synthetic original source " + name, encoding="utf-8")
            old[name] = _reference(file)
        opaque = "NEVER_DECODE_SYNTHETIC_OUTCOME_VALUE_中文😀多字节" + "x" * opaque_size
        contract = _write(paths.backtest_root / "frozen_contract.json", {"source_refs": old, "opaque": "NEVER_DECODE_SYNTHETIC_OUTCOME_VALUE_CONTRACT"})
        receipts = []
        def receipt(name, before, after, tag):
            return _write(paths.results_root / (tag + ".json"), {
                "source_name": name, "frozen_contract_sha256": contract["sha256"],
                "old_ref": before, "new_ref": after, "opaque": "NEVER_DECODE_SYNTHETIC_OUTCOME_VALUE_RECEIPT"})
        for i in range(count):
            name = scope["SOURCE_FILES"][i % 7]
            receipts.append(receipt(name, old[name], old[name], "old" + str(i)))
        record = scope["record_path"](paths)
        _write(record, {"opaque_prefix": opaque, "frozen_contract": contract,
                        "engineering_repair_receipts": receipts, "opaque_suffix": {"deep": [opaque]}})
        owner = SimpleNamespace(**scope)
        def change(name, text, tag):
            file = paths.repo_root / name
            before = _reference(file)
            file.write_text(text, encoding="utf-8")
            return receipt(name, before, _reference(file), tag)
        def arguments(refs):
            return dict(receipt_refs=refs, expected_before_sha256=_reference(record)["sha256"],
                        expected_frozen_contract_sha256=contract["sha256"], expected_existing_refs=list(receipts))
        return SimpleNamespace(paths=paths, scope=scope, owner=owner, old=old, contract=contract,
            receipts=receipts, record=record, change=change, arguments=arguments, opaque=opaque)
    return build


def test_default_guard_keeps_original_full_read_and_metadata_mode_skips_opaque(factory, monkeypatch):
    s = factory()
    full, contract = s.owner.frozen_contract(s.paths)
    assert full["opaque_prefix"] == s.opaque and "NEVER_DECODE" in contract["opaque"]
    original = json.loads
    def loads(value, *args, **kwargs):
        assert "NEVER_DECODE_SYNTHETIC_OUTCOME_VALUE_" not in str(value)
        return original(value, *args, **kwargs)
    monkeypatch.setattr(json, "loads", loads)
    monkeypatch.setitem(s.scope, "read", lambda *a: pytest.fail("metadata mode called full reader"))
    narrow, narrow_contract = s.owner.frozen_contract(s.paths, metadata_only=True)
    assert set(narrow) == {"frozen_contract", "engineering_repair_receipts"}
    assert set(narrow_contract) == {"source_refs"}


def test_atomic_two_receipt_append_keeps_80_prefix_and_large_opaque_bytes(factory, monkeypatch):
    s = factory(80, 1_100_000)
    refs = [s.change(s.owner.SOURCE_FILES[-1], "synthetic source v2", "new_applied"),
            s.change(s.owner.SOURCE_FILES[2], "synthetic owner v2", "new_owner")]
    before = s.record.read_bytes()
    with s.record.open("rb") as f: old, (a,b) = s.owner._engineering_record_span(f)
    original = json.loads
    def loads(value, *args, **kwargs):
        assert "NEVER_DECODE_SYNTHETIC_OUTCOME_VALUE_" not in str(value)
        return original(value, *args, **kwargs)
    monkeypatch.setattr(json, "loads", loads)
    result = s.owner.append_engineering_repair_refs(s.paths, **s.arguments(refs))
    after = s.record.read_bytes()
    with s.record.open("rb") as f: new, (c,d) = s.owner._engineering_record_span(f)
    assert result["repair_count"] == 82 and result["non_chain_bytes_preserved"] is True
    assert new["engineering_repair_receipts"][:80] == old["engineering_repair_receipts"]
    assert new["engineering_repair_receipts"][80:] == refs
    assert new["frozen_contract"] == old["frozen_contract"]
    assert before[:a] == after[:c] and before[b:] == after[d:]
    assert "中文😀多字节".encode("utf-8") in before[:a]
    assert "中文😀多字节".encode("utf-8") in before[b:]
    assert not list(s.record.parent.glob("*.tmp"))


def test_same_source_two_receipts_must_keep_original_lineage_order(factory):
    for reverse in (False, True):
        s = factory()
        name = s.owner.SOURCE_FILES[-1]
        first = s.change(name, "synthetic intermediate", "first")
        second = s.change(name, "synthetic final", "second")
        before = s.record.read_bytes()
        if reverse:
            with pytest.raises(ValueError, match="LINEAGE"):
                s.owner.append_engineering_repair_refs(s.paths, **s.arguments([second, first]))
            assert s.record.read_bytes() == before
        else:
            assert s.owner.append_engineering_repair_refs(s.paths, **s.arguments([first, second]))["repair_count"] == 4


@pytest.mark.parametrize("kind", ["before_sha", "prefix", "contract_sha", "old_ref", "receipt_sha",
    "terminal_sha", "source_path", "duplicate", "unknown_source", "source_set"])
def test_fail_closed_keeps_entire_original_record(factory, kind):
    s = factory()
    name = s.owner.SOURCE_FILES[-1]
    new = s.change(name, "synthetic new source", "new")
    args = s.arguments([new])
    if kind == "before_sha": args["expected_before_sha256"] = "0" * 64
    elif kind == "prefix": args["expected_existing_refs"] = []
    elif kind == "contract_sha": args["expected_frozen_contract_sha256"] = "0" * 64
    elif kind in ("old_ref", "source_path", "unknown_source"):
        body = json.loads(Path(new["path"]).read_text(encoding="utf-8"))
        if kind == "old_ref": body["old_ref"]["sha256"] = "0" * 64
        elif kind == "unknown_source": body["source_name"] = "unknown source"
        else: body["new_ref"]["path"] = str(s.paths.repo_root / "wrong.py")
        new = _write(Path(new["path"]), body); args["receipt_refs"] = [new]
    elif kind == "receipt_sha": args["receipt_refs"][0] = {**new, "sha256": "0" * 64}
    elif kind == "terminal_sha": (s.paths.repo_root / name).write_text("unexpected later bytes")
    elif kind == "duplicate": args["receipt_refs"] = [new, new]
    elif kind == "source_set":
        body = json.loads(Path(s.contract["path"]).read_text(encoding="utf-8"))
        body["source_refs"]["extra.py"] = s.old[s.owner.SOURCE_FILES[0]]
        s.contract.update(_write(Path(s.contract["path"]), body))
        args["expected_frozen_contract_sha256"] = s.contract["sha256"]
        # Keep this branch metadata-only and coherent up to the exact-seven gate.
        for item in [*s.receipts, new]:
            content = json.loads(Path(item["path"]).read_text(encoding="utf-8"))
            content["frozen_contract_sha256"] = s.contract["sha256"]
            item.update(_write(Path(item["path"]), content))
        _write(s.record, {"frozen_contract": s.contract, "engineering_repair_receipts": s.receipts, "opaque": s.opaque})
        args["expected_before_sha256"] = _reference(s.record)["sha256"]
    before = s.record.read_bytes()
    with pytest.raises((ValueError, KeyError)):
        s.owner.append_engineering_repair_refs(s.paths, **args)
    assert s.record.read_bytes() == before
    assert not list(s.record.parent.glob("*.tmp"))


@pytest.mark.parametrize("kind", ["duplicate_key", "trailing_garbage", "trailing_comma", "missing_refs", "non_list_refs"])
def test_noncompatible_record_format_rejected(factory, kind):
    s = factory()
    if kind == "duplicate_key":
        s.record.write_bytes(b'{"opaque":1,"opaque":2,' + s.record.read_bytes()[1:])
    elif kind == "trailing_garbage": s.record.write_bytes(s.record.read_bytes() + b"not-json")
    elif kind == "trailing_comma": s.record.write_bytes(s.record.read_bytes().rstrip()[:-1] + b",}\n")
    elif kind == "missing_refs": _write(s.record, {"frozen_contract":s.contract, "opaque":s.opaque})
    else: _write(s.record, {"frozen_contract":s.contract, "engineering_repair_receipts":{}, "opaque":s.opaque})
    new = s.change(s.owner.SOURCE_FILES[-1], "new", "new")
    before = s.record.read_bytes()
    with pytest.raises(ValueError):
        s.owner.append_engineering_repair_refs(s.paths, **s.arguments([new]))
    assert s.record.read_bytes() == before


def test_original_single_update_excludes_parallel_registration(factory):
    from scripts.common.daily_support import single_update
    s = factory()
    new = s.change(s.owner.SOURCE_FILES[-1], "new", "new")
    before = s.record.read_bytes()
    with single_update(s.paths.daily_root / "A2_today_recommendation"):
        with pytest.raises(RuntimeError, match="更新任务"):
            s.owner.append_engineering_repair_refs(s.paths, **s.arguments([new]))
    assert s.record.read_bytes() == before


def test_changed_record_during_staging_not_overwritten(factory, monkeypatch):
    s = factory()
    new = s.change(s.owner.SOURCE_FILES[-1], "new", "new")
    before = s.record.read_bytes()
    original = s.owner._engineering_copy
    calls = []
    def copy(*args):
        original(*args); calls.append(True)
        if len(calls) == 2: s.record.write_bytes(before + b"\n")
    monkeypatch.setitem(s.scope, "_engineering_copy", copy)
    with pytest.raises(ValueError):
        s.owner.append_engineering_repair_refs(s.paths, **s.arguments([new]))
    assert s.record.read_bytes() == before + b"\n"


def test_postcommit_failure_has_explicit_committed_identity_not_blind_retry(factory, monkeypatch):
    s = factory()
    new = s.change(s.owner.SOURCE_FILES[-1], "new", "new")
    before = s.record.read_bytes()
    monkeypatch.setitem(s.scope, "frozen_contract", lambda *a, **kw: (_ for _ in ()).throw(ValueError("synthetic postcheck")))
    with pytest.raises(RuntimeError, match="COMMITTED_POSTCHECK_FAILED:" + "[0-9a-f]{64}"):
        s.owner.append_engineering_repair_refs(s.paths, **s.arguments([new]))
    assert s.record.read_bytes() != before
    assert not list(s.record.parent.glob("*.tmp"))


def test_staged_filename_collision_preserves_other_existing_file(factory, monkeypatch):
    import uuid
    s = factory()
    new = s.change(s.owner.SOURCE_FILES[-1], "new", "new")
    staged = s.record.with_name("." + s.record.name + ".engineering-repair-collision.tmp")
    staged.write_bytes(b"another owner's pre-existing content")
    before = s.record.read_bytes()
    monkeypatch.setattr(uuid, "uuid4", lambda: SimpleNamespace(hex="collision"))
    with pytest.raises(FileExistsError):
        s.owner.append_engineering_repair_refs(s.paths, **s.arguments([new]))
    assert s.record.read_bytes() == before
    assert staged.read_bytes() == b"another owner's pre-existing content"
