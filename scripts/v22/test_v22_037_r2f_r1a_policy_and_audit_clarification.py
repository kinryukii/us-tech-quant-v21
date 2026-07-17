from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parent
    / "v22_037_r2f_direction_aware_liquid_option_contract_ranking_and_no_trade_gate_research_only.py"
)


def load_module():
    module_name = "v22_037_r2f_under_test"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    # Python 3.14 dataclasses resolves postponed annotations through
    # sys.modules during module execution, so register before exec_module.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_unique_preserve_order_deduplicates_without_reordering():
    module = load_module()
    values = [
        "NO_TRADE_PANEL_STALE",
        "NO_UNEXPIRED_MATCHING_CONTRACT",
        "NO_UNEXPIRED_MATCHING_CONTRACT",
        "",
        "NO_TRADE_DIRECTION_INPUT_STALE",
        "NO_TRADE_PANEL_STALE",
    ]
    assert module.unique_preserve_order(values) == [
        "NO_TRADE_PANEL_STALE",
        "NO_UNEXPIRED_MATCHING_CONTRACT",
        "NO_TRADE_DIRECTION_INPUT_STALE",
    ]


def test_gate_block_reason_writer_uses_dedupe_helper():
    source = MODULE_PATH.read_text(encoding="utf-8")
    start = source.index('"gate_block_reasons": ";".join(')
    assert "unique_preserve_order(" in source[start:start + 500]


def test_generated_policy_declares_role_and_count_semantics():
    source = MODULE_PATH.read_text(encoding="utf-8")
    expected = [
        '"policy_role": "GENERATED_AUDIT_SNAPSHOT"',
        '"policy_is_input": False',
        '"runtime_configuration_source": "PYTHON_CONSTANTS_AND_DIRECTION_MODE_INPUT"',
        '"inverse_underlyings": sorted(INVERSE_UNDERLYINGS)',
        '"candidate_ranking_count_definition": "DIRECTION_COMPATIBLE_ROWS_INCLUDING_EXPIRED_FOR_AUDIT"',
        '"gate_block_reasons_deduplicated": True',
    ]
    for fragment in expected:
        assert fragment in source


def test_r1a_does_not_change_scope_or_authorization_flags():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert 'SEMICONDUCTOR_UNDERLYINGS = {"SOXX", "SMH", "SOXL", "SOXS"}' in source
    assert '"official_adoption_allowed": False' in source
    assert '"broker_action_allowed": False' in source
