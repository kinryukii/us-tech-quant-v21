"""Project the original common engine's signal target repair, without rewriting it.

This current-plan seam does not run an account or read prices/results. Frozen
source/config bytes and the unchanged AST remain the mathematical authority.
"""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "retained/a2_pto_full_compat_20260928_r2/fast_account.py"
ENGINE_SHA = "200462d48816918a5b9fe72f2239a81d01f69a32d57922e8e47cf1ee4c06ee1b"
CONFIG = Path("D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/R1_ACCOUNT_CONFIG.json")
CONFIG_SHA = "84d27ff5a16e7c26501cfb0ea61bbe38d76159c44695856503970273c7174635"


def _pinned(path, wanted):
    path = Path(path).resolve()
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != wanted:
        raise ValueError("CONSENSUS_FROZEN_TARGET_OWNER_CHANGED:" + str(path))
    return raw, {"path": str(path), "sha256": wanted}


def frozen_limits():
    from io import BytesIO
    from scripts.common.json_projection import metadata_fields
    raw, ref = _pinned(CONFIG, CONFIG_SHA)
    config = metadata_fields(BytesIO(raw), {"max_positions", "max_weight", "gross_bounds", "long_only"})
    if config != {"max_positions": 20, "max_weight": 1., "gross_bounds": [0, 1], "long_only": True}:
        raise ValueError("CONSENSUS_ORIGINAL_ACCOUNT_LIMITS_CHANGED")
    # The frozen ACCOUNT_REPLAY_R1.config_adapter uses gross_bounds[1].
    return dict(max_positions=config["max_positions"], max_weight=config["max_weight"],
                max_invested=config["gross_bounds"][1], config_ref=ref)


def _assigned(statement):
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        return statement.targets[0].id
    if isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id
    return None


def _projection():
    raw, ref = _pinned(ENGINE, ENGINE_SHA)
    tree = ast.parse(raw.decode("utf-8-sig"))
    owner = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_many")
    coordinates = [n for n in owner.body if _assigned(n) in ("ticker_rank", "ticker_keys")]
    blocks = []
    validations = []
    for node in ast.walk(owner):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for first, statement in enumerate(body):
            if isinstance(statement, ast.Assign) and _assigned(statement) == "final_reserved":
                last = next((j for j in range(first, len(body)) if _assigned(body[j]) == "keep"), None)
                if last is not None:
                    blocks.append(body[first:last + 1])
            if isinstance(statement, ast.Assign) and _assigned(statement) == "raw":
                last = next((j for j in range(first + 1, len(body)) if _assigned(body[j]) == "raw"), None)
                if last is not None:
                    validations.append(body[first:last + 1])
    names = ("final_reserved", "final_reserved", "final_reserved_weight", "final_budget", "final_slots", "adapted",
             "ineligible_adaptation", "adapted", "ordering", "rank", "slot_adaptation", "adapted", "total", "scale",
             "adapted", "adapted", "order_mask", "keep")
    if (len(coordinates) != 2 or len(blocks) != 1 or len(validations) != 1
            or tuple(_assigned(n) for n in blocks[0]) != names):
        raise ValueError("CONSENSUS_FROZEN_TARGET_AST_ANCHORS_CHANGED")
    body = coordinates + validations[0] + blocks[0]
    projected = ast.Module(body=body, type_ignores=[])
    proof = dict(engine_ref=ref, original_function="run_many", ast_edits=[],
                 block_ast_sha256=hashlib.sha256(ast.dump(projected).encode()).hexdigest(),
                 algorithm="UNCHANGED_ORIGINAL_SIGNAL_TARGET_VALIDATION_AND_FINAL_RESERVED_REPAIR")
    return compile(ast.fix_missing_locations(projected), str(ENGINE), "exec"), proof


def adapt_targets(context, result):
    """Apply the original repair to one independently valued signal-close book."""
    import numpy as np
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account as owner
    limits = frozen_limits()
    weights = np.asarray(context.current_weights, dtype=float)
    units = np.asarray(context.current_units, dtype=float)
    if (weights.ndim != 2 or weights.shape[0] != 1 or units.shape != weights.shape
            or not np.isfinite(weights).all() or (weights < 0).any()
            or not np.isfinite(units).all() or (units < 0).any()):
        raise ValueError("CONSENSUS_OWN_SIGNAL_STATE_INVALID")
    s, n = weights.shape
    tickers = np.asarray(context.tickers, dtype=str)
    if len(tickers) != n or len(set(tickers)) != n:
        raise ValueError("CONSENSUS_OWN_SIGNAL_COORDINATES_INVALID")
    for key in ("max_positions", "max_weight", "max_invested"):
        if getattr(context, key) != limits[key]:
            raise ValueError("CONSENSUS_ORIGINAL_ACCOUNT_LIMITS_REQUIRED")
    code, proof = _projection()
    namespace = dict(np=np, _positive=owner._positive, result=result, s=s, n=n,
        market=type("TickerCoordinates", (), {"tickers": tickers})(), weights=weights,
        held=units > owner.TOL, reserved=np.asarray(context.reserved_mask, bool).copy(),
        op_mask=np.asarray(context.operational_mask, bool),
        signal_sell=np.asarray(context.sell_restricted, bool)[0],
        decision_mask=np.asarray(context.decision_mask, bool),
        buy_allowed=np.asarray(context.buy_allowed, bool), nav=np.asarray(context.nav, float),
        max_positions=limits["max_positions"], max_weight=limits["max_weight"], max_invested=limits["max_invested"])
    if any(namespace[k].shape != weights.shape for k in ("reserved", "op_mask", "decision_mask", "buy_allowed")):
        raise ValueError("CONSENSUS_OWN_SIGNAL_MASK_INVALID")
    exec(code, namespace)
    if int(namespace["keep"].sum()) > limits["max_positions"]:
        raise ValueError("CONSENSUS_EXACT_HOLD_COUNT_EXCEEDS_ORIGINAL_LIMIT")
    receipt = dict(schema="CONSENSUS_FROZEN_COMMON_TARGET_ADAPTATION_R1", **proof,
        account_config_ref=limits["config_ref"],
        account_limits={k: limits[k] for k in ("max_positions", "max_weight", "max_invested")},
        reserved_positions=int(namespace["keep"].sum()), available_target_slots=int(namespace["final_slots"][0]),
        reserved_weight=float(namespace["final_reserved_weight"][0]),
        raw_requested_target_weight=float(namespace["raw"].sum()),
        active_target_weight=float(namespace["adapted"].sum()),
        slot_repair_count=int(namespace["slot_adaptation"].sum()),
        capital_scale=float(namespace["scale"][0]))
    return dict(weights=namespace["adapted"], exact_hold_mask=namespace["keep"],
                raw_weights=namespace["raw"], slot_adaptation=namespace["slot_adaptation"],
                ineligible_adaptation=namespace["ineligible_adaptation"], receipt=receipt)
