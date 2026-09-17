#!/usr/bin/env python
"""CLI for A2 Research Trial Judge R1; performs evaluation only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_governance.io import TrialLedgerAdapter, read_json
from research_governance.judge import JudgeThresholds, evaluate_trial, render_scorecard, result_json
from research_governance.registry import load_registries
from research_governance.schemas import TrialInput


DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[2] / "config/research_governance/trial_judge_r1.json"
DEFAULT_REGISTRIES = Path(__file__).resolve().parents[2] / "config/research_governance"
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")


def _thresholds(path: Path) -> JudgeThresholds:
    payload = read_json(path)
    return JudgeThresholds.from_dict(payload["thresholds"])


def _expected_benchmark(registry_dir: Path, family: str) -> str:
    registry = load_registries(registry_dir)[family]
    champion = next(item for item in registry["models"] if item["role"] == f"{family}_CHAMPION")
    return str(champion["benchmark_id"])


def _write_or_print(results: list[dict], output: Path | None) -> None:
    if output is None:
        for result in results:
            print(render_scorecard(result), end="")
        return
    _validate_output(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _validate_output(output: Path) -> None:
    resolved = output.resolve()
    if not resolved.is_relative_to(RESULTS_ROOT.resolve()):
        raise ValueError(f"judge output must be under approved results root: {RESULTS_ROOT}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    single = sub.add_parser("evaluate-json")
    single.add_argument("--input", type=Path, required=True)
    single.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    single.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRIES)
    single.add_argument("--output", type=Path)
    ledger = sub.add_parser("evaluate-immutable-ledger")
    ledger.add_argument("--ledger", type=Path, required=True)
    ledger.add_argument("--immutable-manifest", type=Path, required=True)
    ledger.add_argument("--metadata", type=Path, required=True)
    ledger.add_argument("--benchmark", type=Path, required=True)
    ledger.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    ledger.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRIES)
    ledger.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    thresholds = _thresholds(args.thresholds)
    if args.command == "evaluate-json":
        trial = TrialInput.from_dict(read_json(args.input))
        expected = _expected_benchmark(args.registry_dir, trial.model_family)
        result = evaluate_trial(trial, thresholds, expected_benchmark_id=expected)
        if args.output:
            _validate_output(args.output)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result_json(result), encoding="utf-8")
        else:
            print(render_scorecard(result), end="")
        return 0 if result["classification"] != "E_INVALID" else 2

    immutable = read_json(args.immutable_manifest)
    metadata = read_json(args.metadata)
    if metadata.get("research_run_id") != (immutable.get("research_run_id") or immutable.get("run_id")):
        raise ValueError("metadata run id does not match immutable manifest")
    benchmark = read_json(args.benchmark)
    trials = TrialLedgerAdapter.from_parquet(
        args.ledger, metadata, benchmark, immutable_manifest=args.immutable_manifest,
    )
    results = []
    for trial in trials:
        expected = _expected_benchmark(args.registry_dir, trial.model_family)
        results.append(evaluate_trial(trial, thresholds, expected_benchmark_id=expected))
    _write_or_print(results, args.output)
    return 0 if results and all(item["classification"] != "E_INVALID" for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
