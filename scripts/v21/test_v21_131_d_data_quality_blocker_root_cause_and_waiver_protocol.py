#!/usr/bin/env python
"""Validate V21.131 data-quality root cause and waiver protocol outputs."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL"
OUT = ROOT / "outputs/v21/V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL"

SUMMARY = OUT / "V21.131_summary.json"
READABLE = OUT / "V21.131_readable_report.txt"
COMPACT = OUT / "V21.131_compact_report.txt"
DETAIL = OUT / "V21.131_data_quality_warning_detail.csv"
IMPACT = OUT / "V21.131_affected_ticker_impact_analysis.csv"
OVERLAP = OUT / "V21.131_d_top20_top50_warning_overlap.csv"
WAIVER = OUT / "V21.131_waiver_eligibility_assessment.csv"
PROJECTION = OUT / "V21.131_post_waiver_gate_projection.csv"
MAIN_SCRIPT = ROOT / "scripts/v21/v21_131_d_data_quality_blocker_root_cause_and_waiver_protocol.py"

EXPECTED_PROTECTED_SHA256 = {
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_summary.json": "9769d42521e1aace56930c2e4d553de4472c77d176d64143cf1751211233a71c",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_readable_report.txt": "bd6e99582cf23f201aaf9d4b340a2cb7139c9d8bd6dd2d6dbac0cc929dba2af3",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/V21.128_compact_report.txt": "8763446cf2d70e3712ec6a247819e334db0a9b63740151b40b91169be841835a",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv": "014bc942860b969185090998730178177a740b52b1985d8c2134e8299b3c3f01",
    "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv": "60197c9c964b2666258a2d5154ff2b97d9ca667aed964a1585653afe570d59a9",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_summary.json": "ebe5b19cdd98e6865e5d501f9307119628fb81ce28c0cfcc831849dea7fd74ff",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_strict_gate_results.csv": "14c96de363f7c9999a228e7b612724490461822ea4ce255bda03037e53eb74c1",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_tracking_top20.csv": "b0c4e1b1b3176927d696f599fcf9f24581682836919b3b4844579c40be585c44",
    "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_tracking_top50.csv": "6e4d692fdd50db3722282258c4405378aad21ac7656a104793a41f05bdc8ad1a",
    "outputs/v21/V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION/V21.130_summary.json": "7b540024f2ea643f41bdf41ef64d7017955e7e1272b7fab080af78118bb08c72",
    "outputs/v21/V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION/V21.130_d_gate_evidence_ledger.csv": "cf3045490bdbdf154beed832f21b20243986a9c690f2564a9dafecd661935225",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def validate_files() -> None:
    for path in [MAIN_SCRIPT, OUT, SUMMARY, READABLE, COMPACT, DETAIL, IMPACT, OVERLAP, WAIVER, PROJECTION]:
        require(path.exists(), f"missing required path: {path}")


def validate_outputs(summary: dict[str, Any]) -> None:
    require(summary.get("stage") == STAGE, "summary stage mismatch")
    require(str(summary.get("stale_or_missing_tickers", "")).strip(), "warning tickers must be identified or UNKNOWN")
    require(summary.get("stale_or_missing_tickers") != "", "empty warning ticker string")
    detail = read_csv(DETAIL)
    impact = read_csv(IMPACT)
    overlap = read_csv(OVERLAP)
    waiver = read_csv(WAIVER)
    projection = read_csv(PROJECTION)
    require(detail, "warning detail is empty")
    require(impact, "impact analysis is empty")
    require(overlap, "Top20/Top50 overlap output is empty")
    require(waiver, "waiver assessment is empty")
    require(projection, "post-waiver projection is empty")
    for row in detail:
        require(row.get("ticker"), "detail row missing ticker")
        require(row.get("warning_type") in {"stale", "missing", "partial", "metadata-only", "UNKNOWN"}, f"invalid warning type: {row}")
        require(row.get("latest_available_price_date"), "latest available price date not recorded")
    for row in impact:
        for field in [
            "in_D_raw_ranking",
            "in_D_top20",
            "in_D_top50",
            "in_D_forward_tracking",
            "in_D_repeated_loser_list",
            "in_D_concentration_chain_list",
            "affects_benchmark_QQQ_SOXX",
            "data_quality_impact_classification",
        ]:
            require(field in row, f"impact row missing {field}")
    for row in overlap:
        require("in_D_top20" in row and "in_D_top50" in row and "in_D_forward_tracking" in row, "overlap checks missing")
    require("DATA_QUALITY_WAIVER_ELIGIBLE" in waiver[0], "waiver eligibility not computed")
    require("projected_primary_D_blocker_after_data_waiver" in projection[0], "projected primary blocker missing")
    require("projected_D_strict_gate_pass" in projection[0], "projected strict gate missing")
    require(as_bool(projection[0]["projected_D_strict_gate_pass"]) is False, "projected strict gate must remain false")
    require(summary.get("projected_primary_D_blocker_after_data_waiver"), "summary projected primary blocker missing")


def validate_controls(summary: dict[str, Any]) -> None:
    require(as_bool(summary.get("D_adoption_allowed")) is False, "D_adoption_allowed must be false")
    require(as_bool(summary.get("D_continued_tracking")) is True, "D_continued_tracking must be true")
    require(as_bool(summary.get("official_adoption_allowed")) is False, "official_adoption_allowed must be false")
    require(as_bool(summary.get("broker_action_allowed")) is False, "broker_action_allowed must be false")
    require(as_bool(summary.get("protected_outputs_modified")) is False, "protected_outputs_modified must be false")
    require(as_bool(summary.get("research_only")) is True, "research_only must be true")
    require(as_bool(summary.get("no_future_leakage")) is True, "no future leakage must be true")
    require(as_bool(summary.get("v21_128_v21_129_v21_130_baseline_preserved")) is True, "baseline preservation failed")


def validate_protected_hashes() -> None:
    for rel_path, expected in EXPECTED_PROTECTED_SHA256.items():
        path = ROOT / rel_path
        require(path.is_file(), f"missing protected file: {rel_path}")
        require(sha256(path) == expected, f"protected baseline changed: {rel_path}")


def main() -> None:
    validate_files()
    summary = load_json(SUMMARY)
    validate_outputs(summary)
    validate_controls(summary)
    validate_protected_hashes()
    print("V21.131 validation PASS")
    print(f"summary_path={SUMMARY.relative_to(ROOT).as_posix()}")
    print(f"stale_or_missing_tickers={summary.get('stale_or_missing_tickers')}")
    print(f"DATA_QUALITY_WAIVER_ELIGIBLE={str(summary.get('DATA_QUALITY_WAIVER_ELIGIBLE')).lower()}")
    print(f"projected_primary_D_blocker_after_data_waiver={summary.get('projected_primary_D_blocker_after_data_waiver')}")


if __name__ == "__main__":
    main()
