"""Static, side-effect-free method contract extraction for ABCDE freeze R1."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


FREEZE_CONTRACT_VERSION = 1
FUNCTION_NAMES = ("pct_rank", "features_by_ticker", "build_rankings")


class FreezeContractError(RuntimeError):
    pass


class _StringNeutralizer(ast.NodeTransformer):
    """Avoid freezing output labels or daily values while retaining code shape."""

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value="<STRING>"), node)
        return node


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def contract_sha256(contract: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json(contract)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assignment_value(module: ast.Module, name: str) -> ast.AST:
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in statement.targets):
            return statement.value
    raise FreezeContractError(f"missing assignment: {name}")


def _functions(module: ast.Module) -> dict[str, ast.FunctionDef]:
    found = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
    missing = set(FUNCTION_NAMES) - set(found)
    if missing:
        raise FreezeContractError(f"missing production functions: {sorted(missing)}")
    return found


def _normalized_ast(node: ast.AST) -> str:
    normalized = _StringNeutralizer().visit(ast.fix_missing_locations(ast.parse(ast.unparse(node))))
    return ast.dump(normalized, annotate_fields=True, include_attributes=False)


def _factor_names(build_rankings: ast.FunctionDef) -> list[str]:
    values: list[str] = []
    stack = [build_rankings]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "weights":
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value not in values:
                values.append(key.value)
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    if len(values) != 6:
        raise FreezeContractError(f"expected six score factors, found {values}")
    return values


def _call_keyword_bool(call: ast.Call, keyword: str) -> bool | None:
    for item in call.keywords:
        if item.arg == keyword and isinstance(item.value, ast.Constant) and isinstance(item.value.value, bool):
            return item.value.value
    return None


def _semantic_invariants(build_rankings: ast.FunctionDef) -> dict[str, object]:
    volatility_reverse: bool | None = None
    final_sort: str | None = None
    for node in ast.walk(build_rankings):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "vol" for target in node.targets):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "pct_rank":
                volatility_reverse = _call_keyword_bool(node.value, "reverse")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sorted":
            if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "scored":
                final_sort = "descending" if _call_keyword_bool(node, "reverse") is True else "ascending_or_unrecognized"
    if volatility_reverse is None or final_sort is None:
        raise FreezeContractError("could not statically establish volatility or final sort invariant")
    return {"volatility_reverse": volatility_reverse, "final_score_sort": final_sort}


def extract_contract_from_text(source_text: str) -> dict[str, object]:
    module = ast.parse(source_text)
    functions = _functions(module)
    strategies = ast.literal_eval(_assignment_value(module, "STRATEGIES"))
    if not isinstance(strategies, dict) or len(strategies) != 5:
        raise FreezeContractError("STRATEGIES is not an exact five-strategy mapping")
    factors = _factor_names(functions["build_rankings"])
    return {
        "freeze_contract_version": FREEZE_CONTRACT_VERSION,
        "strategy_weights": strategies,
        "factor_names": factors,
        "function_contracts": {
            "pct_rank_ast": _normalized_ast(functions["pct_rank"]),
            "feature_builder_ast": _normalized_ast(functions["features_by_ticker"]),
            "build_rankings_ast": _normalized_ast(functions["build_rankings"]),
        },
        "semantic_invariants": _semantic_invariants(functions["build_rankings"]),
    }


def extract_contract(source_path: Path) -> dict[str, object]:
    return extract_contract_from_text(source_path.read_text(encoding="utf-8"))
