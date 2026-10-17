"""Dependency-free metadata access to the existing bounded lexical JSON owner.

Only the reviewed parser definitions are compiled; research/model imports and
source I/O are never executed. The original owner remains the implementation.
"""
from __future__ import annotations
import ast
from functools import lru_cache
import json
from pathlib import Path

@lru_cache(maxsize=1)
def _parser_type():
    owner = Path(__file__).resolve().parents[1] / "research/a2/data/consensus_account_inputs.py"
    parsed = ast.parse(owner.read_text(encoding="utf-8"), filename=str(owner))
    names = {"require", "_JsonProjection"}
    nodes = [node for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    if len(nodes) != 2 or {node.name for node in nodes} != names:
        raise ValueError("SOURCE_JSON_PARSER_OWNER_CHANGED")
    scope = {"json": json, "__name__": __name__}
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(owner), "exec"), scope)
    return scope["_JsonProjection"]

def metadata_fields(handle, names):
    """Project allowlisted top-level metadata with the original size limits."""
    return _parser_type()(handle).metadata_fields(set(names))


def array_metadata_fields(handle, path, names):
    """Stream small allowlisted metadata per item; retain original value limits."""
    parser = _parser_type()(handle)
    parser.descend(tuple(path)); parser.expect(b"["); parser.white()
    if parser.peek() == b"]":
        parser.take(); return
    while True:
        yield parser.metadata_fields(set(names))
        parser.white(); separator = parser.take()
        if separator == b"]":
            return
        if separator != b",":
            raise ValueError("SOURCE_JSON_METADATA_ARRAY_CHANGED")
