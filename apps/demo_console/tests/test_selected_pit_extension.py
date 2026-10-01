from copy import deepcopy
import ast
import importlib.util
from pathlib import Path
import sys
import pytest
sys.path.insert(0, "D:/us-tech-quant")
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
reader = load("pit_reader", Path(__file__).parents[3] / "apps/demo_console/adapters/selected_strategies_reader.py")
fixture_tree = ast.parse(Path("D:/us-tech-quant/apps/demo_console/tests/test_selected_strategies.py").read_text(encoding="utf-8"))
fixture_body = next(node for node in fixture_tree.body if isinstance(node, ast.FunctionDef) and node.name == "package")
exec(compile(ast.Module(body=[fixture_body], type_ignores=[]), "synthetic_fixture", "exec"))
def pit_package():
    p = package()
    p["performance_period"]["price_basis"] = "PIT_FORWARD_REHAB_INDEX"
    manifest = {"path": "C:/synthetic/manifest.json", "sha256": "cd" * 32}
    p["source_refs"]["pit_manifest"] = manifest
    p["source_hashes"]["pit_manifest"] = manifest["sha256"]
    p["performance_extension"] = {"source_id": "NEW_PIT_COMPARISON", "manifest": deepcopy(manifest),
        "model_fit_calls": 0, "broker_action_allowed": False,
        "performance_period": deepcopy(p["performance_period"]),
        "requested_end_date": "2026-01-06", "status": "READY", "blocked_next": None}
    raw = deepcopy(p["strategies"][reader.STRATEGY_IDS[0]])
    raw.update(strategy_id="RAW_A2", label="Raw A2", performance_period=deepcopy(p["performance_period"]))
    p["raw_reference"] = raw
    return p

def test_legacy_and_bound_pit_valid():
    reader.validate_package(package())
    p = pit_package()
    reader.validate_package(p)
    assert reader.raw_reference_view(package=p)["source_id"] == "NEW_PIT_COMPARISON"

@pytest.mark.parametrize("mutation", [
    lambda p: p.pop("performance_extension"),
    lambda p: p.pop("raw_reference"),
    lambda p: p["performance_extension"]["manifest"].update(sha256="ef" * 32),
    lambda p: p["performance_extension"].update(model_fit_calls=1),
    lambda p: p["performance_extension"].update(model_fit_calls=False),
    lambda p: p["performance_extension"].update(broker_action_allowed=True),
    lambda p: p["performance_extension"].update(requested_end_date="2026-01-07"),
    lambda p: p["raw_reference"]["daily"][-1].update(date="2026-01-07"),
    lambda p: p["performance_extension"]["performance_period"].update(end="2026-01-07"),
])
def test_invalid_pit_provenance_and_calendar_rejected(mutation):
    p = pit_package(); mutation(p)
    with pytest.raises(ValueError): reader.validate_package(p)

def test_partial_keeps_verified_date_without_fabricating_requested_date():
    p = pit_package(); e = p["performance_extension"]
    e.update(status="PARTIAL", requested_end_date="2026-01-08", blocked_next={
        "signal_date": "2026-01-06", "execution_date": "2026-01-07", "reason": "MISSING_HELD_PRICE"})
    reader.validate_package(p)
    assert reader.raw_reference_view("2026-01-08", package=p)["history"]["end"] == "2026-01-06"
    e["blocked_next"]["execution_date"] = "2026-01-06"
    with pytest.raises(ValueError): reader.validate_package(p)


def test_ui_captions_explain_basis_and_partial_boundary():
    tree = ast.parse((Path(__file__).parents[3] / "apps/demo_console/pages/selected_strategies.py").read_text(encoding="utf-8"))
    names = {"replay_basis_caption", "replay_update_caption"}
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), "captions", "exec"), namespace)
    p = pit_package()
    assert "PIT" in namespace["replay_basis_caption"](p)
    assert "不是模拟账户绩效" in namespace["replay_basis_caption"](p)
    assert "2026-01-06" in namespace["replay_update_caption"](p)
    p["performance_extension"].update(status="PARTIAL", requested_end_date="2026-01-08",
        blocked_next={"execution_date": "2026-01-07", "reason": "MISSING_HELD_PRICE"})
    caption = namespace["replay_update_caption"](p)
    for expected in ("2026-01-06", "2026-01-08", "2026-01-07", "MISSING_HELD_PRICE"):
        assert expected in caption
