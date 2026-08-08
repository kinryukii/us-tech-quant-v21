#!/usr/bin/env python
"""Freeze the R2 execution-contract tie completion before economic data access."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ORIGINAL_SHA256 = "70d0624bb61dd77cf2d8a8aea5c53b87488a094a222eca5d42167ba343cbee8f"
FROZEN = Path(r"D:\us-tech-quant-results\frozen")
ORIGINAL = FROZEN / "fast3" / "cleanroom_r2_20260808" / "cleanroom_r2_economic_contract.json"
DESTINATION = FROZEN / "fast3" / "cleanroom_r2_execution_contract_completion_20260808"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if sha256(ORIGINAL) != ORIGINAL_SHA256:
        raise RuntimeError("STOP_ORIGINAL_ECONOMIC_CONTRACT_IDENTITY_MISMATCH")
    if DESTINATION.exists():
        raise RuntimeError("STOP_EXECUTION_CONTRACT_COMPLETION_ALREADY_EXISTS")

    original_contract = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    completed = {
        "contract_version": "CLEANROOM_R2_EXECUTION_CONTRACT_COMPLETION_R1",
        "run_id": "20260808",
        "original_economic_contract_sha256": ORIGINAL_SHA256,
        "original_economic_contract": original_contract,
        "same_direction_cross_underlying_tie": "ABSTAIN",
        "economic_outcome_opened_before_contract_completion": False,
        "execution_scope": "HGB primary signals; one global position; no model, threshold, feature, or parameter changes.",
    }
    DESTINATION.mkdir(parents=True)
    artifact = DESTINATION / "execution_contract_completion.json"
    artifact.write_bytes(json.dumps(completed, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    print(f"ORIGINAL_ECONOMIC_CONTRACT_SHA256={ORIGINAL_SHA256}")
    print("SAME_DIRECTION_CROSS_UNDERLYING_TIE=ABSTAIN")
    print("ECONOMIC_OUTCOME_OPENED_BEFORE_CONTRACT_COMPLETION=false")
    print(f"COMPLETED_ECONOMIC_CONTRACT_SHA256={sha256(artifact)}")


if __name__ == "__main__":
    main()
