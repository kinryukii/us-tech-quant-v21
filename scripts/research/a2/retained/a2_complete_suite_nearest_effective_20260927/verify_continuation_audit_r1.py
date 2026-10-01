"""Check that the saved 2026 freezes and continuation receipts still bind."""

import hashlib
import json
from pathlib import Path


root = Path(__file__).resolve().parent
seals = sorted((root / "evaluation_2026").glob("cost_*/FROZEN_BEFORE_SCORING.json"))
assert len(seals) == 3
checked = 0
for seal in seals:
    frozen = json.loads(seal.read_text(encoding="utf-8"))
    for relative, expected in frozen["source_hashes"].items():
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        assert actual == expected, f"Frozen source changed: {relative} ({seal})"
        checked += 1

version = json.loads((root / "continuation_version_r1/INPUT_VERSION_RECEIPT.json").read_text(encoding="utf-8"))
assert version["joint_input"]["verified_rows"] == 61963
assert version["joint_input"]["unknown_rows"] == 47701
assert version["separate_original_four_model_r7"]["verified_rows"] == 62774
assert version["separate_original_four_model_r7"]["unknown_rows"] == 46837
print(f"CONTINUATION_AUDIT_R1_PASS: 3 seals, {checked} frozen source checks, R6/R7 distinct")
