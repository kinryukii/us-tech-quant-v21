#!/usr/bin/env python
"""A2 Attribution Framework R1: realized contribution diagnostics only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from attribution.engine import AttributionEngine
from attribution.incremental import IncrementalAttributionEngine
from attribution.io import read_table, verify_immutable_manifest, verify_loaded_identity, write_outputs
from attribution.schemas import AttributionConfig


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config/research_governance/a2_attribution_r1.json"
DEFAULT_FIXTURE = REPO_ROOT / "scripts/v22/fixtures/attribution/tiny_portfolio_fixture.json"
LIVE_RESEARCH_RUN_ID = "A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_config(path: Path) -> AttributionConfig:
    payload = read_json(path)
    return AttributionConfig.from_dict(payload["engine"])


def render_summary(summary: dict[str, Any]) -> str:
    def shown(value: Any) -> str:
        return "NA" if value is None else str(value)

    return "\n".join([
        "=" * 60, "A2 ATTRIBUTION FRAMEWORK R1", "=" * 60, "",
        f"STRATEGY_ID={shown(summary['strategy_id'])}", f"MODEL_ID={shown(summary['model_id'])}",
        f"DATE_START={summary['date_start']}", f"DATE_END={summary['date_end']}", "",
        f"INPUT_ROWS={summary['input_rows']}", f"SECURITY_COUNT={summary['security_count']}",
        f"TRADING_DAYS={summary['trading_days']}", "",
        f"ATTRIBUTION_IDENTITY_STATUS={summary['attribution_identity_status']}",
        f"MAX_DAILY_IDENTITY_ERROR={summary['max_daily_identity_error']}",
        f"TOTAL_IDENTITY_ERROR={summary['total_identity_error']}", "",
        f"TOTAL_GROSS_CONTRIBUTION={summary['total_gross_contribution']}",
        f"TOTAL_COST={summary['total_cost']}", f"TOTAL_NET_CONTRIBUTION={summary['total_net_contribution']}", "",
        f"TOP_SECURITY_CONTRIBUTORS={shown(summary['top_security_contributors'])}",
        f"BOTTOM_SECURITY_CONTRIBUTORS={shown(summary['bottom_security_contributors'])}", "",
        f"TOP_5_SECURITY_POSITIVE_SHARE={shown(summary['top_5_security_positive_share'])}",
        f"TOP_10_SECURITY_POSITIVE_SHARE={shown(summary['top_10_security_positive_share'])}",
        f"EFFECTIVE_POSITIVE_CONTRIBUTOR_COUNT={shown(summary['effective_positive_contributor_count'])}", "",
        f"BEST_YEAR={shown(summary['best_year'])}", f"WORST_YEAR={shown(summary['worst_year'])}",
        f"BEST_YEAR_POSITIVE_SHARE={shown(summary['best_year_positive_share'])}", "",
        f"RANK_1_5_CONTRIBUTION={shown(summary['rank_1_5_contribution'])}",
        f"RANK_6_10_CONTRIBUTION={shown(summary['rank_6_10_contribution'])}",
        f"RANK_11_20_CONTRIBUTION={shown(summary['rank_11_20_contribution'])}", "",
        f"SECTOR_CONCENTRATION_STATUS={summary['sector_concentration_status']}",
        f"DRAWDOWN_EPISODE_COUNT={summary['drawdown_episode_count']}",
        f"WORST_DRAWDOWN_WINDOW={shown(summary['worst_drawdown_window'])}",
        f"A_VS_A2_INCREMENTAL_STATUS={summary['a_vs_a2_incremental_status']}", "",
        f"FULL_HISTORY_EXECUTED={str(summary['full_history_executed']).upper()}",
        f"MODEL_TRAINING_EXECUTED={str(summary['model_training_executed']).upper()}",
        f"LIVE_RESEARCH_TOUCHED={str(summary['live_research_touched']).upper()}", "=" * 60,
    ]) + "\n"


def validate_fixture(config_path: Path, fixture_path: Path) -> int:
    if LIVE_RESEARCH_RUN_ID.lower() in str(fixture_path).lower():
        raise ValueError("fixture path must never point to live Overnight Research")
    payload, config = read_json(fixture_path), load_config(config_path)
    a2 = AttributionEngine(config).run(payload["a2_rows"], payload["a2_daily"])
    incremental = IncrementalAttributionEngine(config).run(
        payload["a_rows"], payload["a2_rows"], payload["a_daily"], payload["a2_daily"],
    )
    a2["summary"]["a_vs_a2_incremental_status"] = incremental["status"]
    print(render_summary(a2["summary"]), end="")
    return 0 if a2["reconciliation"]["status"] == "PASS" and incremental["status"] == "PASS" else 2


def run_immutable(args: argparse.Namespace) -> int:
    supplied = {"a_rows": args.a_rows, "a2_rows": args.a2_rows, "a_daily": args.a_daily, "a2_daily": args.a2_daily}
    manifest = verify_immutable_manifest(args.manifest, supplied)
    contract = read_json(args.config)
    if manifest["freeze_id"] != contract["required_freeze_id"]:
        raise ValueError("freeze identity does not match attribution contract")
    frames = {name: read_table(path) for name, path in supplied.items()}
    for name, frame in frames.items():
        verify_loaded_identity(name, frame, manifest["artifacts"][name])
    config = load_config(args.config)
    a = AttributionEngine(config).run(frames["a_rows"], frames["a_daily"])
    a2 = AttributionEngine(config).run(frames["a2_rows"], frames["a2_daily"])
    a2["summary"].update({
        "freeze_id": manifest["freeze_id"], "training_cutoff": manifest["training_cutoff"],
        "universe_id": manifest["universe_id"], "data_manifest_sha256": manifest["data_manifest_sha256"],
        "model_sha256": manifest["model_sha256"],
    })
    if a["reconciliation"]["status"] != "PASS" or a2["reconciliation"]["status"] != "PASS":
        raise ValueError("individual strategy attribution identity failed")
    incremental = IncrementalAttributionEngine(config).run(
        frames["a_rows"], frames["a2_rows"], frames["a_daily"], frames["a2_daily"],
    )
    if incremental["status"] != "PASS":
        raise ValueError("incremental attribution identity failed")
    write_outputs(a2, incremental, args.output_dir)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fixture = sub.add_parser("validate-fixture")
    fixture.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    fixture.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    full = sub.add_parser("run-immutable-attribution")
    full.add_argument("--manifest", type=Path, required=True)
    full.add_argument("--a-rows", type=Path, required=True)
    full.add_argument("--a2-rows", type=Path, required=True)
    full.add_argument("--a-daily", type=Path, required=True)
    full.add_argument("--a2-daily", type=Path, required=True)
    full.add_argument("--output-dir", type=Path, required=True)
    full.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    return validate_fixture(args.config, args.fixture) if args.command == "validate-fixture" else run_immutable(args)


if __name__ == "__main__":
    raise SystemExit(main())
