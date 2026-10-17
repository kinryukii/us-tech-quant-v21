"""JSON serialization compatibility for the frozen B R4 opportunity worker.

No scientific code, source, target, budget or original frozen bytes change.
The wrapper is authorized and pinned separately from the original whole matrix.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from scripts.research.a2.training import joint_opportunity_execution_r4 as execution
from scripts.research.a2.evaluation import joint_r4_runtime as runtime

ORIGINAL_MATRIX_SHA = "33ab57abde641e69de132da062650490272ac88fdaac3f6430b6f2e7fe8ad036"
ORIGINAL_EXECUTION_SHA = "a2ac822a3ffb12704695284f5b6437873bbf92632e32678ed182be46411b9209"
BINDING_NAME = "OPPORTUNITY_ACTIVATION_ENGINEERING_BINDING_R1.json"
TRANSFORM = "JSON_SERIALIZATION_LIST_TUPLE_ONLY"


def canonical_specification(stored, actual):
    """Preserve values, sequence order, number types and every source field."""
    canonical = json.loads(json.dumps(actual, allow_nan=False))
    options = dict(sort_keys=True, separators=(",", ":"), allow_nan=False)
    if json.dumps(stored, **options) != json.dumps(canonical, **options):
        raise execution.OpportunityBlocked("ACTIVATION_CANONICAL_SPEC_VALUES_CHANGED")
    return canonical


def validate_binding(run, expected_matrix_sha, expected_binding_sha):
    run = Path(run)
    if expected_matrix_sha != ORIGINAL_MATRIX_SHA or not expected_binding_sha:
        raise execution.OpportunityBlocked("EXACT_ORIGINAL_MATRIX_AND_ENGINEERING_BINDING_REQUIRED")
    binding_path = run / BINDING_NAME
    runtime._pin(binding_path, expected_binding_sha, "opportunity_engineering_binding")
    binding = runtime.read_json(binding_path)
    if (binding.get("original_matrix_sha256") != ORIGINAL_MATRIX_SHA
        or binding.get("transform") != TRANSFORM
        or binding.get("no_scientific_change") is not True
        or binding.get("stage") != "opportunity"):
        raise execution.OpportunityBlocked("UNSUPPORTED_ACTIVATION_ENGINEERING_BINDING")
    for ref in binding["pinned_artifacts"]:
        runtime._pin(ref["path"], ref["sha256"], "activation_engineering_artifact")
    wrapper = next((p for p in binding["pinned_artifacts"]
                    if Path(p["path"]).resolve() == Path(__file__).resolve()), None)
    if wrapper is None:
        raise execution.OpportunityBlocked("WRAPPER_NOT_PINNED_IN_ENGINEERING_BINDING")
    runtime._pin(execution.__file__, ORIGINAL_EXECUTION_SHA, "original_opportunity_execution")
    runtime.guard(run, expected_matrix_sha)
    stored = runtime.read_json(run / execution.SPEC_NAME)
    canonical_specification(stored, execution.specification(run))
    return stored


def run_training_compatible(run, *, phase="all", expected_matrix_sha, expected_binding_sha):
    stored = validate_binding(run, expected_matrix_sha, expected_binding_sha)
    original = execution.specification

    def canonical_view(current_run):
        return canonical_specification(stored, original(current_run))

    # A process-local metadata view; original activated, run_training and all
    # source/ledger guards run unchanged. Restore even on an engineering failure.
    execution.specification = canonical_view
    try:
        return execution.run_training(run, phase=phase, expected_matrix_sha=expected_matrix_sha)
    finally:
        execution.specification = original


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--phase", choices=("inner", "annual", "all"), default="all")
    parser.add_argument("--expected-matrix-sha", required=True)
    parser.add_argument("--expected-binding-sha", required=True)
    args = parser.parse_args()
    status = run_training_compatible(args.run, phase=args.phase,
        expected_matrix_sha=args.expected_matrix_sha,
        expected_binding_sha=args.expected_binding_sha)
    print(json.dumps(dict(status=status["status"],
                          stage_new_units=status["new_fit_units"], test2026_reads=0)), flush=True)


if __name__ == "__main__":
    main()
