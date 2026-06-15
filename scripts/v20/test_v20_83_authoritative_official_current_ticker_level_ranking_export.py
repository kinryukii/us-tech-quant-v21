from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "v20"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

STAGE_SCRIPT = SCRIPT_DIR / "v20_83_authoritative_official_current_ticker_level_ranking_export.py"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_83_authoritative_official_current_ticker_level_ranking_export.py"
WRAPPER = SCRIPT_DIR / "run_v20_83_authoritative_official_current_ticker_level_ranking_export.ps1"

PASS_STATUSES = {
    "PASS_V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT",
    "PASS_V20_83_AUTHORITATIVE_EXPORT_WITH_PRICE_GAPS",
}
ALLOWED_STATUSES = PASS_STATUSES | {
    "BLOCKED_V20_83_NO_AUTHORITATIVE_OFFICIAL_CURRENT_SOURCE",
    "BLOCKED_V20_83_AMBIGUOUS_CURRENT_SOURCE",
    "BLOCKED_V20_83_ACCEPTANCE_PROOF_MISSING",
}

OUTPUTS = {
    "ranking": CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    "audit": CONSOLIDATION / "V20_83_OFFICIAL_CURRENT_INPUT_BINDING_AUDIT.csv",
    "report": READ_CENTER / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT_REPORT.md",
    "manifest": OPS / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT_MANIFEST.json",
}

RANKING_FIELDS = [
    "ticker",
    "official_current_rank",
    "official_current_score",
    "score_name",
    "latest_price",
    "latest_price_date",
    "source_stage",
    "source_run_id",
    "source_file",
    "source_role",
    "ranking_timestamp_utc",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
    "certification_status",
    "certification_reason",
    "acceptance_proof_status",
    "acceptance_proof_file",
    "acceptance_proof_stage",
    "acceptance_proof_reason",
    "acceptance_summary_file",
    "acceptance_summary_status",
    "acceptance_package_manifest_file",
    "acceptance_package_manifest_status",
    "accepted_artifact_path",
    "accepted_artifact_validation_status",
    "exact_artifact_proof_status",
    "exact_artifact_proof_reason",
    "source_row_count",
    "unique_ticker_count",
    "duplicate_ticker_count",
    "deduplication_rule",
]

AUDIT_FIELDS = [
    "candidate_file",
    "candidate_role",
    "detected_stage",
    "detected_run_id",
    "has_ticker",
    "has_rank",
    "has_score",
    "has_price",
    "row_count",
    "accepted_as_official_current",
    "reject_reason",
    "unique_ticker_count",
    "duplicate_ticker_count",
    "deduplication_rule",
    "certification_reason",
]


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def fields(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def alias_path(path: Path) -> Path:
    return path.with_name(path.name.replace("V20_83_", "V20_CURRENT_", 1))


def status_tokens(stdout: str) -> list[str]:
    return re.findall(r"\b(?:PASS|BLOCKED)_V20_83_[A-Z0-9_]+\b", stdout)


def tracked_v20_47_to_82_files() -> list[Path]:
    result = run_command(["git", "ls-files"])
    assert_true(result.returncode == 0, f"git ls-files failed: {result.stdout}\n{result.stderr}")
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        normalized = line.strip().replace("\\", "/")
        if not normalized:
            continue
        upper = normalized.upper()
        if "V20_83" in upper:
            continue
        if any(f"V20_{number}" in upper for number in range(47, 83)):
            paths.append(ROOT / normalized)
    return sorted(paths)


def digest(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(paths: list[Path]) -> dict[str, tuple[str, int, int]]:
    snap: dict[str, tuple[str, int, int]] = {}
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if path.exists():
            stat = path.stat()
            snap[rel] = (digest(path), stat.st_size, stat.st_mtime_ns)
        else:
            snap[rel] = ("MISSING", -1, -1)
    return snap


def test_compile_and_parser() -> None:
    for path in [STAGE_SCRIPT, TEST_SCRIPT]:
        result = run_command([sys.executable, "-m", "py_compile", str(path)])
        assert_true(result.returncode == 0, f"py_compile failed for {path}: {result.stdout}\n{result.stderr}")
    parse = run_command([
        "powershell",
        "-NoProfile",
        "-Command",
        "$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v20/run_v20_83_authoritative_official_current_ticker_level_ranking_export.ps1'), [ref]$null); 'PARSE_OK'",
    ])
    assert_true(parse.returncode == 0 and "PARSE_OK" in parse.stdout, f"PowerShell parser check failed: {parse.stdout}\n{parse.stderr}")


def test_wrapper_run_and_no_mutation() -> None:
    protected = tracked_v20_47_to_82_files()
    before = snapshot(protected)
    result = run_command(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    tokens = status_tokens(result.stdout)
    assert_true(tokens, f"wrapper produced no V20.83 status: {result.stdout}\n{result.stderr}")
    final_status = tokens[-1]
    assert_true(final_status in ALLOWED_STATUSES, f"unexpected wrapper status {final_status}: {result.stdout}")
    after = snapshot(protected)
    changed = [path for path, value in before.items() if after.get(path) != value]
    assert_true(not changed, "V20.83 execution mutated tracked V20.47-V20.82 files: " + "; ".join(changed[:20]))


def test_outputs_aliases_schemas_and_manifest() -> None:
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    assert_true(manifest["status"] in ALLOWED_STATUSES, f"bad manifest status: {manifest['status']}")
    for path in OUTPUTS.values():
        assert_true(path.exists() and path.stat().st_size > 0, f"missing or empty output: {path}")
        alias = alias_path(path)
        assert_true(alias.exists() and alias.stat().st_size > 0, f"missing or empty alias: {alias}")
        assert_true(path.read_bytes() == alias.read_bytes(), f"alias differs: {alias}")
    assert_true(fields(OUTPUTS["ranking"]) == RANKING_FIELDS, "ranking schema mismatch")
    assert_true(fields(OUTPUTS["audit"]) == AUDIT_FIELDS, "audit schema mismatch")
    assert_true(manifest["research_only"] is True, "research_only invariant failed")
    assert_true(manifest["official_recommendation_created"] is False, "official recommendation invariant failed")
    assert_true(manifest["official_weight_mutated"] is False, "official weight invariant failed")
    assert_true(manifest["trade_action_created"] is False, "trade action invariant failed")
    for field in [
        "acceptance_proof_status",
        "acceptance_proof_file",
        "acceptance_proof_stage",
        "acceptance_summary_file",
        "acceptance_summary_status",
        "acceptance_package_manifest_file",
        "acceptance_package_manifest_status",
        "accepted_artifact_path",
        "accepted_artifact_validation_status",
        "exact_artifact_proof_status",
        "exact_artifact_proof_reason",
        "source_row_count",
        "unique_ticker_count",
        "duplicate_ticker_count",
        "deduplication_rule",
        "rank_column_used",
        "score_column_used",
        "price_column_used",
    ]:
        assert_true(field in manifest, f"manifest missing {field}")


def test_pass_or_block_contract() -> None:
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    ranking = read_csv(OUTPUTS["ranking"])
    report = OUTPUTS["report"].read_text(encoding="utf-8")
    if manifest["status"] in PASS_STATUSES:
        assert_true(ranking, "PASS status requires ranking rows")
        for row in ranking:
            assert_true(row["ticker"], f"missing ticker: {row}")
            assert_true(row["official_current_rank"], f"missing rank: {row}")
            assert_true(row["official_current_score"], f"missing score: {row}")
            assert_true(row["research_only"] == "TRUE", f"research_only row invariant failed: {row}")
            assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation row invariant failed: {row}")
            assert_true(row["official_weight_mutated"] == "FALSE", f"weight row invariant failed: {row}")
            assert_true(row["trade_action_created"] == "FALSE", f"trade row invariant failed: {row}")
            if row["source_role"] == "OPERATOR_ACCEPTED_CURRENT_RESEARCH":
                assert_true(row["acceptance_proof_status"] == "FOUND", f"operator-accepted source missing proof status: {row}")
                assert_true(row["acceptance_proof_file"], f"operator-accepted source missing proof file: {row}")
                assert_true(row["acceptance_proof_stage"] in {"V20.49_OPERATOR_REVIEW_ACCEPTANCE_GATE", "V20.69_DAILY_OPERATION_REVIEW_ACCEPTANCE_AND_EXPORT_GATE"}, f"bad proof stage: {row}")
                assert_true(row["acceptance_summary_file"] == "outputs/v20/consolidation/V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv", f"acceptance summary file missing: {row}")
                assert_true(row["acceptance_summary_status"] == "ACCEPTED_FOR_OPERATOR_REVIEW_RESEARCH_ONLY", f"acceptance summary status invalid: {row}")
                assert_true(row["acceptance_package_manifest_file"] == "outputs/v20/consolidation/V20_49_OPERATOR_REVIEW_PACKAGE_MANIFEST.csv", f"package manifest file missing: {row}")
                assert_true(row["acceptance_package_manifest_status"] == "PASS", f"package manifest status invalid: {row}")
                assert_true(row["accepted_artifact_path"] == row["source_file"], f"accepted artifact path does not match source: {row}")
                assert_true(row["accepted_artifact_validation_status"] == "PASS", f"accepted artifact validation invalid: {row}")
                assert_true(row["exact_artifact_proof_status"] == "FOUND", f"exact artifact proof missing: {row}")
            source_count = int(row["source_row_count"])
            unique_count = int(row["unique_ticker_count"])
            duplicate_count = int(row["duplicate_ticker_count"])
            if source_count > unique_count:
                assert_true(duplicate_count == source_count - unique_count, f"duplicate count mismatch: {row}")
                assert_true(row["deduplication_rule"] == "first_ranked_row_kept", f"dedupe rule missing: {row}")
                assert_true("duplicate tickers collapsed using first_ranked_row_kept" in row["certification_reason"], f"dedupe reason missing: {row}")
    else:
        assert_true("No authoritative official-current ticker-level source with ticker, rank, and score was discovered." in report or manifest["status"] == "BLOCKED_V20_83_AMBIGUOUS_CURRENT_SOURCE", "blocked report missing clear reason")


def test_source_acceptance_and_rejections() -> None:
    audit = read_csv(OUTPUTS["audit"])
    accepted = [row for row in audit if row["accepted_as_official_current"] == "TRUE"]
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    if manifest["status"] in PASS_STATUSES:
        assert_true(len(accepted) == 1, f"expected exactly one accepted source: {accepted}")
        source = accepted[0]["candidate_file"]
        assert_true("V20_75_DAILY_RANK_CHANGE_ATTRIBUTION_TABLE.csv" not in source, "V20.75 attribution accepted")
        assert_true("V20_76_SHADOW_OPERATIONAL_RANK_TABLE.csv" not in source, "V20.76 shadow accepted")
        assert_true("REQUIRED_OUTPUT_CHECKS" not in source and "MANIFEST" not in source.upper(), "checks/manifest accepted")
        accepted_row = accepted[0]
        if "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv" in accepted_row["candidate_file"]:
            ranking = read_csv(OUTPUTS["ranking"])
            assert_true(all(row["source_role"] == "OPERATOR_ACCEPTED_CURRENT_RESEARCH" for row in ranking), "V20.48 accepted without operator role")
            assert_true(all(row["acceptance_proof_status"] == "FOUND" for row in ranking), "V20.48 operator role missing downstream proof")
            assert_true(accepted_row["unique_ticker_count"] == "40", f"accepted audit unique count missing: {accepted_row}")
            assert_true(accepted_row["duplicate_ticker_count"] == "10", f"accepted audit duplicate count missing: {accepted_row}")
            assert_true(accepted_row["deduplication_rule"] == "first_ranked_row_kept", f"accepted audit dedupe rule missing: {accepted_row}")
    for row in audit:
        path = row["candidate_file"]
        upper = path.upper()
        if "V20_75_DAILY_RANK_CHANGE_ATTRIBUTION_TABLE.CSV" in upper:
            assert_true(row["accepted_as_official_current"] == "FALSE" and row["candidate_role"] == "RANK_CHANGE_ATTRIBUTION_ONLY", "V20.75 not rejected as attribution")
        if "V20_76_SHADOW_OPERATIONAL_RANK_TABLE.CSV" in upper:
            assert_true(row["accepted_as_official_current"] == "FALSE" and row["candidate_role"] == "SHADOW_OPERATIONAL", "V20.76 not rejected as shadow")
        if "V20_80_REQUIRED_OUTPUT_CHECKS.CSV" in upper or "V20_81_REQUIRED_OUTPUT_CHECKS.CSV" in upper:
            assert_true(row["accepted_as_official_current"] == "FALSE" and row["candidate_role"] == "REQUIRED_OUTPUT_CHECKS", "required checks not rejected")
        if "V20_73" in upper or "V20_74" in upper or "OVERLAY" in upper:
            assert_true(row["accepted_as_official_current"] == "FALSE", f"overlay accepted: {row}")


def test_v20_48_mapping_and_acceptance_proof() -> None:
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    if manifest["bound_source_file"] != "outputs/v20/consolidation/V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv":
        return
    assert_true(manifest["bound_source_role"] == "OPERATOR_ACCEPTED_CURRENT_RESEARCH", "V20.48 bound with unexpected role")
    assert_true(manifest["acceptance_proof_status"] == "FOUND", "V20.48 bound without downstream acceptance proof")
    assert_true(manifest["acceptance_summary_file"] == "outputs/v20/consolidation/V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv", f"unexpected acceptance summary file: {manifest['acceptance_summary_file']}")
    assert_true(manifest["acceptance_summary_status"] == "ACCEPTED_FOR_OPERATOR_REVIEW_RESEARCH_ONLY", f"unexpected acceptance summary status: {manifest['acceptance_summary_status']}")
    assert_true(manifest["acceptance_package_manifest_file"] == "outputs/v20/consolidation/V20_49_OPERATOR_REVIEW_PACKAGE_MANIFEST.csv", f"unexpected package manifest file: {manifest['acceptance_package_manifest_file']}")
    assert_true(manifest["acceptance_package_manifest_status"] == "PASS", f"unexpected package manifest status: {manifest['acceptance_package_manifest_status']}")
    assert_true(manifest["accepted_artifact_path"] == manifest["bound_source_file"], f"accepted artifact path mismatch: {manifest}")
    assert_true(manifest["accepted_artifact_validation_status"] == "PASS", f"accepted artifact validation mismatch: {manifest}")
    assert_true(manifest["exact_artifact_proof_status"] == "FOUND", f"exact artifact proof missing: {manifest}")
    summary = read_csv(ROOT / manifest["acceptance_summary_file"])
    assert_true(any(row.get("acceptance_status") == "ACCEPTED_FOR_OPERATOR_REVIEW_RESEARCH_ONLY" and row.get("v20_47_run_id") == read_csv(ROOT / manifest["bound_source_file"])[0]["v20_47_run_id"] for row in summary), "acceptance summary does not match bound source run id")
    package = read_csv(ROOT / manifest["acceptance_package_manifest_file"])
    package_row = next((row for row in package if row.get("artifact_path") == manifest["bound_source_file"]), None)
    assert_true(package_row is not None, "package manifest does not include exact bound artifact")
    assert_true(package_row["exists_flag"] == "TRUE", f"package exists_flag invalid: {package_row}")
    assert_true(package_row["non_empty_flag"] == "TRUE", f"package non_empty_flag invalid: {package_row}")
    assert_true(package_row["research_only_flag"] == "TRUE", f"package research_only_flag invalid: {package_row}")
    assert_true(package_row["official_recommendation_allowed"] == "FALSE", f"package recommendation flag invalid: {package_row}")
    assert_true(package_row["trading_allowed"] == "FALSE", f"package trading flag invalid: {package_row}")
    assert_true(package_row["validation_status"] == "PASS", f"package validation_status invalid: {package_row}")
    assert_true(manifest["rank_column_used"] == "report_rank", f"wrong rank column: {manifest['rank_column_used']}")
    assert_true(manifest["score_column_used"] == "source_rank_or_score", f"wrong score column: {manifest['score_column_used']}")
    assert_true(manifest["price_column_used"] == "refreshed_latest_close", f"wrong price column: {manifest['price_column_used']}")
    source_rows = read_csv(ROOT / manifest["bound_source_file"])
    exported = {row["ticker"]: row for row in read_csv(OUTPUTS["ranking"])}
    first = source_rows[0]
    ticker = first["normalized_ticker"].strip().upper()
    assert_true(ticker in exported, f"sample ticker missing from export: {ticker}")
    output = exported[ticker]
    assert_true(first["report_rank"] == output["official_current_rank"], f"rank mapping mismatch: {first} -> {output}")
    assert_true(first["source_rank_or_score"] == output["official_current_score"], f"score mapping mismatch: {first} -> {output}")
    assert_true(first["refreshed_latest_close"] == output["latest_price"], f"price mapping mismatch: {first} -> {output}")
    source_unique = len({row["normalized_ticker"].strip().upper() for row in source_rows if row["normalized_ticker"].strip()})
    assert_true(manifest["source_row_count"] == len(source_rows), "manifest source row count mismatch")
    assert_true(manifest["unique_ticker_count"] == source_unique, "manifest unique ticker count mismatch")
    assert_true(manifest["duplicate_ticker_count"] == len(source_rows) - source_unique, "manifest duplicate ticker count mismatch")
    assert_true(manifest["deduplication_rule"] == "first_ranked_row_kept", "manifest dedupe rule mismatch")


def test_no_recommendation_weight_trade_paths() -> None:
    created_names = [path.name.upper() for path in OUTPUTS.values()] + [alias_path(path).name.upper() for path in OUTPUTS.values()]
    forbidden_names = ["BUY_ORDER", "SELL_ORDER", "TRADE_ORDER", "BROKER_ACTION", "OFFICIAL_WEIGHT_UPDATE", "OFFICIAL_RECOMMENDATION"]
    assert_true(not any(token in name for token in forbidden_names for name in created_names), "forbidden official/trade output name created")
    tree = ast.parse(STAGE_SCRIPT.read_text(encoding="utf-8"))
    forbidden_imports = {"requests", "urllib", "httpx", "yfinance", "alpaca_trade_api", "ibapi", "ccxt"}
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0].lower() for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0].lower())
    assert_true(not (set(imports) & forbidden_imports), "network/broker import introduced")
    script_text = STAGE_SCRIPT.read_text(encoding="utf-8")
    assert_true("official_recommendation_created" in script_text, "manifest flag missing")
    assert_true("trade_action_created" in script_text, "trade action flag missing")


def test_no_hardcoded_run_id() -> None:
    text = STAGE_SCRIPT.read_text(encoding="utf-8")
    concrete_run_ids = re.findall(r"V20_\d{2,}[A-Z]?_20\d{6}T\d{6}Z", text)
    assert_true(not concrete_run_ids, f"hardcoded run_id found: {concrete_run_ids}")


def main() -> int:
    test_compile_and_parser()
    test_wrapper_run_and_no_mutation()
    test_outputs_aliases_schemas_and_manifest()
    test_pass_or_block_contract()
    test_source_acceptance_and_rejections()
    test_v20_48_mapping_and_acceptance_proof()
    test_no_recommendation_weight_trade_paths()
    test_no_hardcoded_run_id()
    print("PASS_V20_83_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
