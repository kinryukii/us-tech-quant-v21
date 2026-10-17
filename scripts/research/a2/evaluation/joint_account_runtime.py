"""Source-bound date indexing for the frozen persistent account callback.

Only the unsupported-event lookup is projected. Account, execution, eligibility,
qualification, event order, metadata and prefix checks remain the frozen code.
Frozen event receipts are immutable inputs throughout a replay, as in the
caller binding; no event date/ticker may be changed by the policy or callback.
"""
from __future__ import annotations

import ast
import copy
from functools import lru_cache
import hashlib
from pathlib import Path

from scripts.research.a2.evaluation import continuous_research_account as common

SOURCE_SHA256 = "99038f036431c91b1070fe52d5bdbbd057c617356a8b839c295c6c4bf0742d00"
NEW_SOURCE_SHA256 = "57ace7d28e6366fe08fb325aa63aeb7db000eae007172920c82f346122bbd38a"
SUPPORTED_SOURCE_SHA256 = frozenset((SOURCE_SHA256, NEW_SOURCE_SHA256))
ENGINE_SHA256 = "200462d48816918a5b9fe72f2239a81d01f69a32d57922e8e47cf1ee4c06ee1b"
_SOURCE = Path(common.__file__).resolve()
_ENGINE = Path(__file__).resolve().parents[1] / "retained/a2_pto_full_compat_20260928_r2/fast_account.py"


def _dump(node):
    return ast.dump(node, include_attributes=False)


def _validated_source(source_sha256):
    if source_sha256 not in SUPPORTED_SOURCE_SHA256:
        raise RuntimeError("Unsupported continuous-account source identity")
    source = _SOURCE.read_bytes()
    if hashlib.sha256(source).hexdigest() != source_sha256:
        raise RuntimeError("Frozen continuous-account source identity changed")
    if hashlib.sha256(_ENGINE.read_bytes()).hexdigest() != ENGINE_SHA256:
        raise RuntimeError("Frozen common account engine identity changed")
    return source


def _projection(source_sha256=None):
    selected = SOURCE_SHA256 if source_sha256 is None else source_sha256
    source = _validated_source(selected)
    original = next(n for n in ast.parse(source.decode("utf-8-sig")).body
                    if isinstance(n, ast.FunctionDef) and n.name == "run_continuous_account")
    fn = copy.deepcopy(original)
    anchor = [i for i, node in enumerate(fn.body) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "common_market" for t in node.targets)]
    if len(anchor) != 1:
        raise RuntimeError("Frozen exception initialization anchor changed")
    index_nodes = ast.parse(
        "_exception_by_day = {}\n"
        "for c, events in exception_by_ticker.items():\n"
        "    for event in events:\n"
        "        _exception_by_day.setdefault(pd.Timestamp(event['effective_date']), []).append((c,event))\n"
    ).body
    fn.body[anchor[0]:anchor[0]] = index_nodes
    callbacks = [n for n in fn.body if isinstance(n, ast.FunctionDef) and n.name == "callback"]
    if len(callbacks) != 1:
        raise RuntimeError("Frozen callback structure changed")
    callback = callbacks[0]
    expected_iter = ast.parse("exception_by_ticker.items()", mode="eval").body
    scan = [n for n in ast.walk(callback) if isinstance(n, ast.For) and _dump(n.iter) == _dump(expected_iter)]
    if len(scan) != 1:
        raise RuntimeError("Frozen daily exception scan changed")
    scan = scan[0]
    if _dump(scan.target) != _dump(ast.parse("for c,events in (): pass").body[0].target) or len(scan.body) != 1:
        raise RuntimeError("Frozen ticker/event order changed")
    inner = scan.body[0]
    if not isinstance(inner, ast.For) or _dump(inner.target) != _dump(ast.Name(id="event", ctx=ast.Store())) or not isinstance(inner.iter, ast.Name) or inner.iter.id != "events":
        raise RuntimeError("Frozen event traversal changed")
    if len(inner.body) != 2 or not isinstance(inner.body[1], ast.If):
        raise RuntimeError("Frozen exception predicate changed")
    condition = inner.body[1].test
    expected_condition = ast.parse(
        "pd.Timestamp(event['effective_date']) == row.date and current_units[r,c] > TOL and key not in reported_exceptions",
        mode="eval").body
    if _dump(condition) != _dump(expected_condition):
        raise RuntimeError("Frozen exception qualification condition changed")
    replacement = copy.deepcopy(scan)
    # Parse in an actual for-statement to preserve Store contexts.
    replacement.target = ast.parse("for c,event in (): pass").body[0].target
    replacement.iter = ast.parse("_exception_by_day.get(row.date, ())", mode="eval").body
    replacement.body = copy.deepcopy(inner.body)
    replacement.body[1].test.values = replacement.body[1].test.values[1:]
    class ReplaceScan(ast.NodeTransformer):
        def visit_For(self, node):
            return replacement if node is scan else self.generic_visit(node)
    ReplaceScan().visit(callback)
    tree = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = common.__dict__.copy()
    exec(compile(tree, str(_SOURCE) + "#effective-date-index", "exec"), namespace)
    lineage = {
        "source_path": str(_SOURCE), "source_sha256": selected,
        "engine_path": str(_ENGINE), "engine_sha256": ENGINE_SHA256,
        "original_function_ast_sha256": hashlib.sha256(_dump(original).encode()).hexdigest(),
        "projected_function_ast_sha256": hashlib.sha256(_dump(fn).encode()).hexdigest(),
        "ast_edits": [
            "insert date->[(c,event)] index before common_market construction, traversing original ticker and event order",
            "replace only daily nested event scan with same-day ordered entries; leave held-unit and duplicate-report predicates untouched",
        ],
        "frozen_source_bytes_modified": False, "frozen_engine_bytes_modified": False,
        "immutable_event_receipts_required": True,
        "all_account_gates_and_metadata_unchanged": True,
    }
    if selected == NEW_SOURCE_SHA256:
        lineage["source_binding_mode"] = "EXPLICIT_OPT_IN_ENTITLEMENT_SLIPPAGE_WRAPPER"
        lineage["legacy_default_source_sha256"] = SOURCE_SHA256
    return namespace["run_continuous_account"], lineage


@lru_cache(maxsize=2)
def _compiled(source_sha256):
    return _projection(source_sha256)


def source_lineage(*, source_sha256=SOURCE_SHA256):
    _validated_source(source_sha256)
    return copy.deepcopy(_compiled(source_sha256)[1])


def run_continuous_account_indexed(*args, source_sha256=SOURCE_SHA256, **kwargs):
    """Same wrapper/result. New economics require its explicit frozen SHA.

    The omitted source binding retains the legacy SHA and fails closed if its
    bytes no longer occupy the current path. Cache reuse never bypasses either
    wrapper or immutable-engine source identity validation.
    """
    _validated_source(source_sha256)
    return _compiled(source_sha256)[0](*args, **kwargs)

