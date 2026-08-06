"""Static safety coverage for the R2.4 research-shadow entrypoint."""
from pathlib import Path


def test_shadow_entrypoint_has_no_order_or_broker_interface():
    script = Path(__file__).resolve().parents[2] / "scripts" / "run" / "fast3_r4_prospective_shadow_hard_r24.py"
    source = script.read_text(encoding="utf-8")
    assert "PROSPECTIVE_INPUT_CONTAINS_OUTCOME" in source
    assert "broker_action_performed" in source
    assert "paper_order_performed" in source
    assert "live_order_performed" in source
