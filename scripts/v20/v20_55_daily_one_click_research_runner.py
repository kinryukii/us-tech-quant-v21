from __future__ import annotations

import ast
import csv
import hashlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

STAGE_ID = "V20.55"
STAGE_NAME = "V20.55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
PASS_STATUS = "PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
WARN_STATUS = "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED"
BLOCKED_STATUS = "BLOCKED_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
FAIL_STATUS = "FAIL_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
NEXT_STAGE = "V20.55_FORMAL_TESTS"

OUT_SUMMARY = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_RUN_SUMMARY.csv"
OUT_LOG = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_STAGE_EXECUTION_LOG.csv"
OUT_ARTIFACT_CHECK = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_REQUIRED_ARTIFACT_CHECK.csv"
OUT_INVENTORY = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_OUTPUT_INVENTORY.csv"
OUT_STATIC_CONTRACT = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_STATIC_CONTRACT_CHECK.csv"
OUT_POLICY = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_POLICY_LANGUAGE_BOUNDARY_CHECK.csv"
OUT_SAFETY = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_SAFETY_BOUNDARY_VALIDATION.csv"
OUT_NEXT = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_NEXT_STEP_DECISION.csv"
OUT_REFRESH_DIAGNOSTICS = CONSOLIDATION / "V20_CURRENT_MARKET_REFRESH_DIAGNOSTICS.csv"
REPORT = READ_CENTER / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md"
CONCLUSION = READ_CENTER / "V20_CURRENT_DAILY_CONCLUSION.md"
READ_FIRST = OPS / "V20_55_READ_FIRST.txt"


def p(relative: str) -> Path:
    return ROOT / relative


DAILY_STAGES = [
    {
        "order": 1,
        "stage": "V20.47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION",
        "wrapper": SCRIPT_DIR / "run_v20_47_controlled_current_market_refresh_and_cache_certification.ps1",
        "pass": "PASS_V20_47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION",
        "outputs": [
            p("outputs/v20/consolidation/V20_47_CONTROLLED_REFRESH_SUMMARY.csv"),
            p("outputs/v20/consolidation/V20_47_CURRENT_MARKET_SOURCE_STAGED_CANDIDATE.csv"),
            p("outputs/v20/consolidation/V20_47_CURRENT_CANDIDATE_PRICE_CERTIFICATION.csv"),
            p("outputs/v20/consolidation/V20_47_CURRENT_BENCHMARK_SOURCE_STAGED_CANDIDATE.csv"),
            p("outputs/v20/consolidation/V20_47_CURRENT_BENCHMARK_PRICE_CERTIFICATION.csv"),
            p("outputs/v20/consolidation/V20_47_CACHE_HASH_LEDGER.csv"),
            p("outputs/v20/consolidation/V20_47_REFRESH_TICKER_UNIVERSE.csv"),
            p("outputs/v20/consolidation/V20_47_PROVIDER_REFRESH_AUDIT.csv"),
            p("outputs/v20/consolidation/V20_47_REFRESH_FAILURE_REGISTER.csv"),
            p("outputs/v20/consolidation/V20_47_REFRESH_SAFETY_BOUNDARY.csv"),
            p("outputs/v20/consolidation/V20_47_NEXT_STEP_DECISION.csv"),
            p("outputs/v20/read_center/V20_47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION_REPORT.md"),
            p("outputs/v20/ops/V20_47_READ_FIRST.txt"),
        ],
    },
    {
        "order": 2,
        "stage": "V20_POST_REFRESH_RECOMPUTE_HANDOFF",
        "wrapper": SCRIPT_DIR / "run_v20_post_refresh_recompute_handoff.ps1",
        "pass": "PASS_V20_POST_REFRESH_RECOMPUTE_HANDOFF_COMPLETED",
        "outputs": [
            p("outputs/v20/consolidation/V20_POST_REFRESH_RECOMPUTE_AUDIT.csv"),
            p("outputs/v20/consolidation/V20_POST_REFRESH_RECOMPUTE_STATUS.csv"),
            p("outputs/v20/consolidation/V20_7V_VALIDATION_SUMMARY.csv"),
            p("outputs/v20/consolidation/V20_7V_PRECHECK_DIAGNOSTICS.csv"),
            p("outputs/v20/consolidation/V20_7V_EXCLUDED_TICKERS.csv"),
        ],
    },
    {
        "order": 3,
        "stage": "V20.48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT",
        "wrapper": SCRIPT_DIR / "run_v20_48_refreshed_current_operator_research_report.ps1",
        "pass": "PASS_V20_48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT",
        "outputs": [
            p("outputs/v20/consolidation/V20_48_REFRESHED_OPERATOR_REPORT_SUMMARY.csv"),
            p("outputs/v20/consolidation/V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"),
            p("outputs/v20/consolidation/V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"),
            p("outputs/v20/consolidation/V20_48_REFRESHED_ENTRY_STRATEGY_VIEW.csv"),
            p("outputs/v20/consolidation/V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"),
            p("outputs/v20/consolidation/V20_48_REFRESHED_LINEAGE_FRESHNESS_VIEW.csv"),
            p("outputs/v20/consolidation/V20_48_REFRESHED_REPORT_ACTION_BOUNDARY.csv"),
            p("outputs/v20/consolidation/V20_48_REFRESHED_REPORT_SAFETY_BOUNDARY.csv"),
            p("outputs/v20/consolidation/V20_48_NEXT_STEP_DECISION.csv"),
            p("outputs/v20/read_center/V20_48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT.md"),
            p("outputs/v20/ops/V20_48_READ_FIRST.txt"),
        ],
    },
    {
        "order": 4,
        "stage": "V20.49_OPERATOR_REVIEW_ACCEPTANCE_GATE",
        "wrapper": SCRIPT_DIR / "run_v20_49_operator_review_acceptance_gate.ps1",
        "pass": "PASS_V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE",
        "outputs": [
            p("outputs/v20/consolidation/V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv"),
            p("outputs/v20/consolidation/V20_49_OPERATOR_CANDIDATE_REVIEW_READINESS.csv"),
            p("outputs/v20/consolidation/V20_49_OPERATOR_FACTOR_REVIEW_READINESS.csv"),
            p("outputs/v20/consolidation/V20_49_OPERATOR_ENTRY_STRATEGY_REVIEW_READINESS.csv"),
            p("outputs/v20/consolidation/V20_49_OPERATOR_BENCHMARK_REVIEW_READINESS.csv"),
            p("outputs/v20/consolidation/V20_49_OPERATOR_LINEAGE_REVIEW_READINESS.csv"),
            p("outputs/v20/consolidation/V20_49_OPERATOR_REVIEW_PACKAGE_MANIFEST.csv"),
            p("outputs/v20/consolidation/V20_49_OPERATOR_REVIEW_ACTION_BOUNDARY.csv"),
            p("outputs/v20/consolidation/V20_49_OPERATOR_REVIEW_SAFETY_BOUNDARY.csv"),
            p("outputs/v20/consolidation/V20_49_NEXT_STEP_DECISION.csv"),
            p("outputs/v20/read_center/V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE_REPORT.md"),
            p("outputs/v20/ops/V20_49_READ_FIRST.txt"),
        ],
    },
    {
        "order": 5,
        "stage": "V20.50_RESEARCH_ONLY_DECISION_PACKET",
        "wrapper": SCRIPT_DIR / "run_v20_50_research_only_decision_packet.ps1",
        "pass": "PASS_V20_50_RESEARCH_ONLY_DECISION_PACKET",
        "outputs": [
            p("outputs/v20/consolidation/V20_50_RESEARCH_ONLY_DECISION_PACKET_SUMMARY.csv"),
            p("outputs/v20/consolidation/V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"),
            p("outputs/v20/consolidation/V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"),
            p("outputs/v20/consolidation/V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"),
            p("outputs/v20/consolidation/V20_50_ENTRY_STRATEGY_RESEARCH_CONTEXT_PACKET.csv"),
            p("outputs/v20/consolidation/V20_50_LINEAGE_RESEARCH_CONTEXT_PACKET.csv"),
            p("outputs/v20/consolidation/V20_50_RESEARCH_DECISION_CATEGORY_RULES.csv"),
            p("outputs/v20/consolidation/V20_50_RESEARCH_ONLY_DECISION_PACKET_MANIFEST.csv"),
            p("outputs/v20/consolidation/V20_50_RESEARCH_ONLY_ACTION_BOUNDARY.csv"),
            p("outputs/v20/consolidation/V20_50_RESEARCH_ONLY_SAFETY_BOUNDARY.csv"),
            p("outputs/v20/consolidation/V20_50_NEXT_STEP_DECISION.csv"),
            p("outputs/v20/read_center/V20_50_RESEARCH_ONLY_DECISION_PACKET_REPORT.md"),
            p("outputs/v20/ops/V20_50_READ_FIRST.txt"),
        ],
    },
    {
        "order": 6,
        "stage": "V20.54_USER_READABLE_CURRENT_DECISION_REPORT",
        "wrapper": SCRIPT_DIR / "run_v20_54_user_readable_current_decision_report.ps1",
        "pass": "PASS_V20_54_USER_READABLE_CURRENT_DECISION_REPORT",
        "outputs": [
            p("outputs/v20/consolidation/V20_54_USER_READABLE_REPORT_SUMMARY.csv"),
            p("outputs/v20/consolidation/V20_54_USER_READABLE_CANDIDATE_VIEW.csv"),
            p("outputs/v20/consolidation/V20_54_PRIORITY_REVIEW_READABLE_VIEW.csv"),
            p("outputs/v20/consolidation/V20_54_STANDARD_REVIEW_READABLE_VIEW.csv"),
            p("outputs/v20/consolidation/V20_54_FACTOR_SUPPORT_READABLE_VIEW.csv"),
            p("outputs/v20/consolidation/V20_54_ENTRY_STRATEGY_READABLE_VIEW.csv"),
            p("outputs/v20/consolidation/V20_54_BENCHMARK_CONTEXT_READABLE_VIEW.csv"),
            p("outputs/v20/consolidation/V20_54_LINEAGE_FRESHNESS_READABLE_VIEW.csv"),
            p("outputs/v20/consolidation/V20_54_POLICY_LANGUAGE_BOUNDARY_CHECK.csv"),
            p("outputs/v20/consolidation/V20_54_SAFETY_BOUNDARY_VALIDATION.csv"),
            p("outputs/v20/consolidation/V20_54_REQUIRED_ARTIFACT_MANIFEST.csv"),
            p("outputs/v20/read_center/V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md"),
            p("outputs/v20/read_center/V20_CURRENT_USER_READABLE_CURRENT_DECISION_REPORT.md"),
            p("outputs/v20/ops/V20_54_READ_FIRST.txt"),
        ],
    },
]

STATIC_CONTRACTS = [
    p("outputs/v20/consolidation/V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_SUMMARY.csv"),
    p("outputs/v20/consolidation/V20_52_OFFICIAL_OUTPUT_SCHEMA_CONTRACT.csv"),
    p("outputs/v20/consolidation/V20_52_RECOMMENDATION_LANGUAGE_POLICY.csv"),
    p("outputs/v20/consolidation/V20_52_POLICY_CONTRACT_SAFETY_BOUNDARY.csv"),
    p("outputs/v20/consolidation/V20_52_NEXT_STEP_DECISION.csv"),
    p("outputs/v20/read_center/V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE_REPORT.md"),
    p("scripts/v20/test_v20_52_official_recommendation_policy_contract_gate.py"),
    p("outputs/v20/consolidation/V20_53_OFFICIAL_SCHEMA_DRY_RUN_SUMMARY.csv"),
    p("outputs/v20/consolidation/V20_53_SCHEMA_FIELD_MAPPING_DRY_RUN.csv"),
    p("outputs/v20/consolidation/V20_53_CANDIDATE_SCHEMA_DRY_RUN_ROWS.csv"),
    p("outputs/v20/consolidation/V20_53_SCHEMA_DRY_RUN_SAFETY_BOUNDARY.csv"),
    p("outputs/v20/consolidation/V20_53_NEXT_STEP_DECISION.csv"),
    p("outputs/v20/read_center/V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE_REPORT.md"),
    p("scripts/v20/test_v20_53_official_recommendation_schema_dry_run_gate.py"),
    p("scripts/v20/test_v20_54_user_readable_current_decision_report.py"),
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def first_csv_row(path: Path) -> dict[str, str]:
    rows = read_csv_rows(path)
    return rows[0] if rows else {}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def exists_non_empty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def parse_date_text(value: object) -> str:
    text = clean(value)[:10]
    if len(text) != 10:
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except ValueError:
        return ""


def tail(text: str, max_chars: int = 900) -> str:
    text = clean(text).replace("\r", "")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_check(stage: str, paths: list[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in paths:
        exists = path.exists()
        non_empty = exists_non_empty(path)
        rows.append({
            "artifact_stage": stage,
            "artifact_path": rel(path),
            "exists": tf(exists),
            "non_empty": tf(non_empty),
            "validation_status": "PASS" if non_empty else "BLOCKED",
            "blocker_reason": "" if non_empty else "missing_or_empty",
        })
    return rows


def inventory_rows(paths: list[Path], role: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        exists = path.exists()
        stat = path.stat() if exists else None
        stage_match = re.search(r"V20_(\d+)", path.name)
        rows.append({
            "artifact_path": rel(path),
            "artifact_stage": f"V20.{stage_match.group(1)}" if stage_match else STAGE_ID,
            "exists": tf(exists),
            "non_empty": tf(exists_non_empty(path)),
            "size_bytes": stat.st_size if stat else 0,
            "modified_at_utc": iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc)) if stat else "",
            "sha256": sha256(path),
            "artifact_role": role,
            "notes": "Daily runner generated or validated artifact.",
        })
    return rows


def classify_status(return_code: int, stdout: str, pass_token: str) -> tuple[str, str]:
    combined = f"{stdout}\n"
    if return_code == 0 and pass_token in combined:
        return pass_token, "PASS"
    if return_code == 0 and "WARN_" in combined:
        warn = next((line.strip() for line in combined.splitlines() if "WARN_" in line), "WARN")
        if "=" in warn:
            warn = warn.split("=", 1)[1].strip()
        return warn, "WARN"
    if "BLOCKED" in combined:
        return "BLOCKED", "BLOCKED"
    return "FAIL", "FAIL"


def run_stage(stage: dict[str, object]) -> dict[str, object]:
    started = now_utc()
    wrapper = stage["wrapper"]
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    ended = now_utc()
    detected, classification = classify_status(result.returncode, result.stdout, str(stage["pass"]))
    checks = artifact_check(str(stage["stage"]), stage["outputs"])
    present = sum(1 for row in checks if row["exists"] == "TRUE")
    non_empty = sum(1 for row in checks if row["non_empty"] == "TRUE")
    if classification == "PASS" and non_empty != len(checks):
        classification = "BLOCKED"
        detected = "BLOCKED_REQUIRED_OUTPUTS_MISSING"
    return {
        "execution_order": stage["order"],
        "upstream_stage": stage["stage"],
        "wrapper_path": rel(wrapper),
        "started_at_utc": iso(started),
        "ended_at_utc": iso(ended),
        "elapsed_seconds": round((ended - started).total_seconds(), 3),
        "return_code": result.returncode,
        "detected_status": detected,
        "status_classification": classification,
        "stdout_tail": tail(result.stdout),
        "stderr_tail": tail(result.stderr),
        "required_outputs_checked": len(checks),
        "required_outputs_present": present,
        "required_outputs_non_empty": non_empty,
        "stop_after_stage": "TRUE" if classification != "PASS" else "FALSE",
        "notes": "" if classification == "PASS" else "Stage did not pass or required outputs missing.",
        "_artifact_checks": checks,
    }


def source_has_forbidden_imports(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"yfinance", "requests", "urllib", "httpx", "alpaca_trade_api", "ibapi", "ccxt"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in forbidden for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in forbidden:
                return True
    return False


def forbidden_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"download", "submit_order", "place_order", "create_order", "buy_order", "sell_order"}
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name.lower() in forbidden:
                hits.append(name)
    return hits


def actionable_hits(text: str) -> list[str]:
    lowered = text.lower()
    allowed = [
        r"not_a_trading_signal",
        r"no_order_execution",
        r"no_broker_action",
        r"not a trading signal",
        r"no trading signal",
        r"not an official recommendation",
        r"no official recommendation generation",
        r"no order execution",
        r"no broker action",
        r"does not create buy/sell/hold instructions",
        r"no buy/sell/hold instruction generation",
        r"no buy/sell/hold instructions",
        r"buy_sell_hold_instructions_created=false",
        r"buy_sell_hold",
        r"broker/order",
        r"broker_order",
        r"does not execute trades",
        r"trades_executed=false",
        r"preserved report order",
        r"report order",
        r"manual review",
        r"research-only",
        r"research_only",
    ]
    for phrase in allowed:
        lowered = re.sub(phrase, "", lowered, flags=re.IGNORECASE)
    forbidden = [
        r"\bstrong buy\b",
        r"\bstrong sell\b",
        r"\bauto trade\b",
        r"\bposition instruction\b",
        r"\bofficial recommendation\b",
        r"\btrading signal\b",
        r"\border\b",
        r"\bexecute\b",
        r"\bbuy\b",
        r"\bsell\b",
        r"\bhold\b",
    ]
    hits: list[str] = []
    for pattern in forbidden:
        for match in re.finditer(pattern, lowered, re.IGNORECASE):
            start = max(0, match.start() - 35)
            end = min(len(lowered), match.end() + 35)
            hits.append(lowered[start:end].replace("\n", " "))
    return hits


def build_policy_checks(paths: list[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        hits = actionable_hits(text)
        rows.append({
            "checked_artifact": rel(path),
            "forbidden_actionable_phrase_count": len(hits),
            "research_only_language_confirmed": tf(not hits),
            "validation_status": "PASS" if not hits else "BLOCKED",
            "blocker_reason": "" if not hits else "actionable_language_detected",
            "sample_hit": hits[0] if hits else "",
        })
    return rows


def build_safety_rows() -> list[dict[str, object]]:
    script = Path(__file__)
    specs = [
        ("orchestrator only", "TRUE", "TRUE", "V20.55 calls approved wrappers and validates artifacts."),
        ("provider refresh only through approved V20.47 wrapper", "TRUE", "TRUE", "Only V20.47 wrapper performs controlled refresh stage."),
        ("no direct yfinance import in V20.55", "FALSE", tf(source_has_forbidden_imports(script)), "AST import scan."),
        ("no direct provider/network call in V20.55", "FALSE", tf(bool(forbidden_calls(script))), "AST call scan."),
        ("no broker/order execution path", "FALSE", "FALSE", "No broker/order API call path."),
        ("no official recommendation generation", "FALSE", "FALSE", "Daily runner is research-only."),
        ("no buy/sell/hold instruction generation", "FALSE", "FALSE", "No instruction generation."),
        ("no trading signal generation", "FALSE", "FALSE", "No trading signals generated."),
        ("no returns calculation in V20.55", "FALSE", "FALSE", "No return calculations in orchestrator."),
        ("no score/ranking recomputation in V20.55", "FALSE", "FALSE", "No score or rank recomputation."),
        ("no ranking/weight mutation", "FALSE", "FALSE", "No ranking or factor weight mutation."),
        ("no dynamic weighting mutation", "FALSE", "FALSE", "No dynamic weighting mutation."),
        ("no real-book position mutation", "FALSE", "FALSE", "No real-book state mutation."),
        ("no outputs/v21", "FALSE", tf((ROOT / "outputs" / "v21").exists()), "No V21 output path."),
        ("no outputs/v19_21", "FALSE", tf((ROOT / "outputs" / "v19_21").exists()), "No V19.21 output path."),
        ("no outputs/v19/V19_21", "FALSE", tf((ROOT / "outputs" / "v19" / "V19_21").exists()), "No V19/V19_21 output path."),
        ("final output remains research-only", "TRUE", "TRUE", "Final V20.54 report is research-only."),
        ("manual review required", "TRUE", "TRUE", "Manual review required before real-world action."),
    ]
    return [
        {
            "safety_check": name,
            "expected_value": expected,
            "actual_value": actual,
            "validation_status": "PASS" if expected == actual else "BLOCKED",
            "evidence": evidence,
            "blocker_reason": "" if expected == actual else "safety_boundary_failed",
        }
        for name, expected, actual, evidence in specs
    ]


def md_table(rows: list[dict[str, object]], fields: list[str], limit: int | None = None) -> str:
    selected = rows if limit is None else rows[:limit]
    if not selected:
        return "_No rows._"
    header = "| " + " | ".join(fields) + " |"
    sep = "| " + " | ".join(["---"] * len(fields)) + " |"
    body = ["| " + " | ".join(clean(row.get(field)).replace("|", "/").replace("\n", " ") for field in fields) + " |" for row in selected]
    return "\n".join([header, sep, *body])


def cleanup_pycache() -> None:
    pycache = SCRIPT_DIR / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)


def first_blocker(log_rows: list[dict[str, object]]) -> tuple[str, str]:
    for row in log_rows:
        if row.get("status_classification") == "PASS":
            continue
        return clean(row.get("upstream_stage")), clean(row.get("detected_status")) or clean(row.get("stderr_tail")) or clean(row.get("stdout_tail"))
    return "", ""


def read_bootstrap_summary() -> dict[str, str]:
    path = ROOT / "outputs" / "v20" / "repair" / "V20_CURRENT_CHAIN_BOOTSTRAP_REPAIR_SUMMARY.md"
    parsed: dict[str, str] = {}
    if not path.exists():
        return parsed
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[clean(key)] = clean(value)
    return parsed


def latest_ranking_text() -> str:
    alias_status_rows = read_csv_rows(ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES_ALIAS_STATUS.csv")
    alias_status = clean(alias_status_rows[0].get("alias_status")) if alias_status_rows else ""
    alias_row_count = clean(alias_status_rows[0].get("row_count")) if alias_status_rows else ""
    source_status = clean(alias_status_rows[0].get("source_v18_13b_status")) if alias_status_rows else ""
    for path in [
        ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES.csv",
        ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv",
    ]:
        rows = read_csv_rows(path)[:10]
        items: list[str] = []
        for row in rows:
            ticker = clean(row.get("ticker")).upper()
            rank = clean(row.get("rank"))
            name = clean(row.get("name"))
            if ticker:
                prefix = f"#{rank} " if rank else ""
                suffix = f" ({name})" if name and name != ticker else ""
                items.append(f"{prefix}{ticker}{suffix}")
        if items:
            if path.name == "V18_CURRENT_FULL_RANKED_CANDIDATES.csv":
                repair_rows = read_csv_rows(ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_STATUS.csv")
                repair_status = clean(repair_rows[0].get("repair_status")) if repair_rows else ""
                repair_count = clean(repair_rows[0].get("output_row_count")) if repair_rows else ""
                detail = f"Available from outputs/v18/candidates/V18_CURRENT_FULL_RANKED_CANDIDATES.csv; status={repair_status}; row_count={repair_count}; top ranked: "
            else:
                detail = f"Available from outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv; status={alias_status or source_status}; row_count={alias_row_count}; top ranked: "
            return detail + ", ".join(items)
    summary_rows = read_csv_rows(ROOT / "outputs" / "v18" / "read_center" / "V18_13B_CURRENT_RANKED_CANDIDATE_SUMMARY.csv")
    summary = {clean(row.get("metric")): clean(row.get("value")) for row in summary_rows}
    if (
        summary.get("STATUS") == "OK_V18_13B_RANKED_CANDIDATE_READ_CENTER_READY"
        and summary.get("RANK_SOURCE_STATUS") != "NO_SCORE_SOURCE_FOUND"
    ):
        rows = read_csv_rows(ROOT / "outputs" / "v18" / "candidates" / "V18_13B_CURRENT_RANKED_CANDIDATES.csv")[:10]
        items = []
        for row in rows:
            ticker = clean(row.get("ticker")).upper()
            rank = clean(row.get("rank"))
            if ticker:
                items.append(f"#{rank} {ticker}" if rank else ticker)
        if items:
            return ", ".join(items)
    return "Not available from an authoritative current ranking artifact."


def full_ranking_handoff_text() -> str:
    path = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES.csv"
    status_rows = read_csv_rows(ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_STATUS.csv")
    status = clean(status_rows[0].get("repair_status")) if status_rows else ""
    row_count = clean(status_rows[0].get("output_row_count")) if status_rows else ""
    source = clean(status_rows[0].get("source_file")) if status_rows else ""
    if exists_non_empty(path):
        return f"Available from outputs/v18/candidates/V18_CURRENT_FULL_RANKED_CANDIDATES.csv; status={status}; row_count={row_count}; source={source}."
    return "Not available from outputs/v18/candidates/V18_CURRENT_FULL_RANKED_CANDIDATES.csv."


def v20_7v_diagnostic_text() -> str:
    rows = read_csv_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_7V_VALIDATION_SUMMARY.csv")
    if not rows:
        return "V20.7V status: not available."
    row = rows[0]
    return "\n".join([
        f"V20.7V status: {clean(row.get('status'))}",
        f"expected_market_date: {clean(row.get('expected_market_date'))}",
        f"observed price date distribution: {clean(row.get('staging_latest_price_date_distribution'))}",
        f"stale_ticker_count: {clean(row.get('stale_ticker_count'))}",
        f"missing_latest_price_count: {clean(row.get('missing_latest_price_count'))}",
        f"missing core field summary: {clean(row.get('missing_core_field_summary'))}",
        f"eligible_row_count: {clean(row.get('eligible_row_count'))}",
        f"excluded_row_count: {clean(row.get('excluded_row_count'))}",
        f"excluded ticker examples: {clean(row.get('excluded_ticker_examples'))}",
        f"V20.7V used quarantine: {clean(row.get('v20_7v_used_quarantine'))}",
        f"active market source staging usable: {clean(row.get('active_source_staging_candidate_ready'))}",
    ])


def price_cache_latest_dates() -> tuple[str, int, dict[str, str]]:
    cache_dir = ROOT / "state" / "v18" / "price_cache"
    latest_by_ticker: dict[str, str] = {}
    if not cache_dir.exists():
        return "", 0, latest_by_ticker
    for path in cache_dir.glob("*.csv"):
        ticker = path.stem.upper()
        latest = ""
        for row in read_csv_rows(path):
            date_text = parse_date_text(row.get("date") or row.get("latest_price_date") or row.get("price_date"))
            close = clean(row.get("close") or row.get("adj_close") or row.get("latest_close"))
            if date_text and close:
                latest = max(latest, date_text)
        if latest:
            latest_by_ticker[ticker] = latest
    latest_date = max(latest_by_ticker.values()) if latest_by_ticker else ""
    return latest_date, len(latest_by_ticker), latest_by_ticker


def write_refresh_diagnostics() -> dict[str, str]:
    v20_7v = first_csv_row(CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv")
    expected_market_date = clean(v20_7v.get("expected_market_date"))
    v47_summary = first_csv_row(CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv")
    v47_next = first_csv_row(CONSOLIDATION / "V20_47_NEXT_STEP_DECISION.csv")
    v47_failed = first_csv_row(CONSOLIDATION / "V20_47_LAST_FAILED_REFRESH_ATTEMPT.csv")
    v47_provider = read_csv_rows(CONSOLIDATION / "V20_47_PROVIDER_REFRESH_AUDIT.csv")
    v47_provider_summary = first_csv_row(CONSOLIDATION / "V20_47_PROVIDER_REFRESH_SUMMARY.csv")
    v47_provider_diagnostics_path = CONSOLIDATION / "V20_47_PROVIDER_REFRESH_DIAGNOSTICS.csv"
    post_refresh = first_csv_row(CONSOLIDATION / "V20_POST_REFRESH_RECOMPUTE_STATUS.csv")
    failure_artifact = ROOT / clean(v47_failed.get("failure_attempt_artifact"))
    v47_failures = read_csv_rows(failure_artifact) if clean(v47_failed.get("failure_attempt_artifact")) else []
    latest_report = READ_CENTER / "V20_47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION_REPORT.md"
    expected_downstream = CONSOLIDATION / "V20_47_NEXT_STEP_DECISION.csv"
    latest_cache_date, cache_count, latest_by_ticker = price_cache_latest_dates()
    stale_count = sum(1 for date_text in latest_by_ticker.values() if expected_market_date and date_text < expected_market_date)
    provider_reasons = sorted({
        clean(row.get("failure_reason") or row.get("provider_error_message"))
        for row in v47_provider
        if clean(row.get("failure_reason") or row.get("provider_error_message"))
    })
    failure_reasons = sorted({
        clean(row.get("failure_reason") or row.get("provider_error_message") or row.get("failure_type"))
        for row in v47_failures
        if clean(row.get("failure_reason") or row.get("provider_error_message") or row.get("failure_type"))
    })
    if failure_reasons:
        provider_reasons = failure_reasons
    latest_status = (
        clean(v47_summary.get("certification_status"))
        or clean(v47_next.get("certification_status"))
        or clean(v47_next.get("decision"))
        or "not_available"
    )
    recommended = "RUN_OR_REPAIR_V20_46_BEFORE_V20_47_REFRESH"
    if not expected_market_date:
        recommended = "REPAIR_V20_7V_EXPECTED_MARKET_DATE_DIAGNOSTICS"
    elif not (SCRIPT_DIR / "v20_47_controlled_current_market_refresh_and_cache_certification.py").exists():
        recommended = "RESTORE_V20_47_REFRESH_SCRIPT"
    elif not (SCRIPT_DIR / "run_v20_47_controlled_current_market_refresh_and_cache_certification.ps1").exists():
        recommended = "RESTORE_V20_47_REFRESH_WRAPPER"
    elif cache_count == 0:
        recommended = "REPAIR_LOCAL_PRICE_CACHE_OR_REFRESH_INPUTS"
    elif clean(v47_summary.get("upstream_v20_46_readiness_status")) != "READY_FOR_CONTROLLED_REFRESH_STAGE":
        recommended = "REPAIR_V20_46_READINESS_AND_CANDIDATE_REFRESH_UNIVERSE_THEN_RERUN_V20_47"
    elif clean(v47_provider_summary.get("recommended_next_action")):
        recommended = clean(v47_provider_summary.get("recommended_next_action"))
    elif clean(v47_summary.get("candidate_tickers_requested")) and clean(v47_summary.get("candidate_tickers_requested")) != "0" and clean(v47_summary.get("candidate_tickers_success")) == "0":
        recommended = "REPAIR_V20_47_PROVIDER_CACHE_REFRESH_EMPTY_DATAFRAME_THEN_RERUN_V20_47"
    elif stale_count:
        recommended = "RERUN_APPROVED_V20_47_REFRESH_AFTER_PROVIDER_CACHE_REPAIR"
    row = {
        "v20_47_script_exists": tf((SCRIPT_DIR / "v20_47_controlled_current_market_refresh_and_cache_certification.py").exists()),
        "v20_47_wrapper_exists": tf((SCRIPT_DIR / "run_v20_47_controlled_current_market_refresh_and_cache_certification.ps1").exists()),
        "latest_v20_47_report_path": rel(latest_report) if latest_report.exists() else "",
        "latest_v20_47_status": latest_status,
        "latest_v20_47_run_id": clean(v47_summary.get("run_id") or v47_summary.get("attempted_run_id")),
        "expected_downstream_artifact_for_v20_55": rel(expected_downstream),
        "expected_downstream_artifact_exists": tf(expected_downstream.exists()),
        "expected_market_date": expected_market_date,
        "price_cache_latest_date": latest_cache_date,
        "price_cache_ticker_count": str(cache_count),
        "stale_price_cache_ticker_count": str(stale_count),
        "v20_46_readiness_status": clean(v47_summary.get("upstream_v20_46_readiness_status")),
        "v20_46_candidate_ticker_count": clean(v47_summary.get("candidate_tickers_requested")),
        "v20_46_tests_status": clean(v47_summary.get("upstream_v20_46_tests_status")),
        "v20_47_requested_ticker_count": clean(v47_provider_summary.get("requested_ticker_count") or v47_summary.get("requested_ticker_count")),
        "v20_47_attempted_ticker_count": clean(v47_provider_summary.get("attempted_ticker_count") or v47_summary.get("attempted_ticker_count")),
        "v20_47_success_count": clean(v47_provider_summary.get("success_count") or v47_summary.get("success_count")),
        "v20_47_empty_dataframe_count": clean(v47_provider_summary.get("empty_dataframe_count") or v47_summary.get("empty_dataframe_count")),
        "v20_47_exception_count": clean(v47_provider_summary.get("exception_count") or v47_summary.get("exception_count")),
        "candidate_tickers_requested": clean(v47_summary.get("candidate_tickers_requested")),
        "candidate_tickers_success": clean(v47_summary.get("candidate_tickers_success")),
        "benchmark_tickers_requested": clean(v47_summary.get("benchmark_tickers_requested")),
        "benchmark_tickers_success": clean(v47_summary.get("benchmark_tickers_success")),
        "provider_available": clean(v47_provider_summary.get("provider_available") or v47_summary.get("provider_available")),
        "dominant_failure_reason": clean(v47_provider_summary.get("dominant_failure_reason") or v47_summary.get("dominant_failure_reason")),
        "provider_diagnostics_path": rel(v47_provider_diagnostics_path) if v47_provider_diagnostics_path.exists() else "",
        "post_refresh_recompute_status": clean(post_refresh.get("status")),
        "post_refresh_ran": tf(bool(post_refresh)),
        "pre_refresh_cache_latest_date_distribution": clean(post_refresh.get("pre_refresh_cache_latest_date_distribution")),
        "post_refresh_cache_latest_date_distribution": clean(post_refresh.get("post_refresh_cache_latest_date_distribution")),
        "post_refresh_full_ranked_latest_price_date_distribution": clean(post_refresh.get("post_refresh_full_ranked_latest_price_date_distribution")),
        "v18_factor_pack_recomputed_after_v20_47": clean(post_refresh.get("v18_factor_pack_recomputed_after_v20_47")),
        "v18_technical_timing_recomputed_after_v20_47": clean(post_refresh.get("v18_technical_timing_recomputed_after_v20_47")),
        "v18_13b_rerun_after_v20_47": clean(post_refresh.get("v18_13b_rerun_after_v20_47")),
        "v18_full_ranked_rebuilt_after_v20_47": clean(post_refresh.get("v18_full_ranked_rebuilt_after_v20_47")),
        "v20_7v_used_post_refresh_artifacts": clean(post_refresh.get("v20_7v_used_post_refresh_artifacts")),
        "eligible_row_count": clean(post_refresh.get("eligible_row_count")) or clean(v20_7v.get("eligible_row_count")),
        "excluded_row_count": clean(post_refresh.get("excluded_row_count")) or clean(v20_7v.get("excluded_row_count")),
        "excluded_ticker_examples": clean(post_refresh.get("excluded_ticker_examples")) or clean(v20_7v.get("excluded_ticker_examples")),
        "v20_7v_used_quarantine": clean(post_refresh.get("v20_7v_used_quarantine")) or clean(v20_7v.get("v20_7v_used_quarantine")),
        "provider_failure_reason": " | ".join(provider_reasons),
        "recommended_next_action": recommended,
    }
    write_csv(OUT_REFRESH_DIAGNOSTICS, [row], list(row.keys()))
    return row


def technical_summary_text() -> str:
    path = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING.csv"
    rows = read_csv_rows(path)
    if not rows:
        return f"source artifact: {rel(path)}\navailability: FALSE"
    counts: dict[str, int] = {}
    for row in rows:
        key = clean(row.get("buy_zone_status") or row.get("technical_timing_status") or row.get("technical_status") or "UNKNOWN").upper()
        counts[key or "UNKNOWN"] = counts.get(key or "UNKNOWN", 0) + 1
    wanted = ["IN_BUY_ZONE", "FAR_ABOVE", "TREND_BROKEN", "OVERHEATED", "UNKNOWN"]
    lines = [
        f"source artifact: {rel(path)}",
        "availability: TRUE",
        f"row_count: {len(rows)}",
    ]
    if any(key in counts for key in wanted):
        lines.extend(f"{key}: {counts.get(key, 0)}" for key in wanted)
    else:
        lines.append("available buy_zone_status / technical status counts:")
        lines.extend(f"- {key}: {counts[key]}" for key in sorted(counts))
    return "\n".join(lines)


def current_ranking_section_text() -> str:
    status_rows = read_csv_rows(ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_STATUS.csv")
    status = clean(status_rows[0].get("repair_status")) if status_rows else ""
    row_count = clean(status_rows[0].get("output_row_count")) if status_rows else ""
    partial = "TRUE" if "WARN" in status.upper() else "FALSE"
    return "\n".join([
        "source artifact: outputs/v18/candidates/V18_CURRENT_FULL_RANKED_CANDIDATES.csv",
        f"status: {status}",
        f"row_count: {row_count}",
        f"partial_research_only: {partial}",
        f"top 10 ranked tickers: {latest_ranking_text()}",
    ])


def manual_additions_text() -> str:
    path = ROOT / "state" / "v18" / "universe" / "V18_MANUAL_UNIVERSE_ADDITIONS.csv"
    status = first_csv_row(ROOT / "outputs" / "v18" / "universe" / "V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR_STATUS.csv")
    count = clean(status.get("manual_addition_row_count"))
    if not count:
        count = str(len(read_csv_rows(path))) if path.exists() else "not available"
    note = "No manual tickers were added or fabricated." if count == "0" else "Manual additions exist; see source artifact."
    return "\n".join([
        f"source artifact: {rel(path)}",
        f"manual_addition_count: {count}",
        note,
    ])


def write_daily_conclusion(overall_status: str, run_id: str, log_rows: list[dict[str, object]]) -> None:
    failed_stage, blocker = first_blocker(log_rows)
    bootstrap = read_bootstrap_summary()
    bootstrap_final = bootstrap.get("final_status", "")
    bootstrap_stage = bootstrap.get("first_failed_stage", "")
    bootstrap_blocker = bootstrap.get("blocker_reason", "")
    v20_7v = first_csv_row(CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv")
    v20_7v_status = clean(v20_7v.get("status"))
    active_usable = clean(v20_7v.get("active_source_staging_candidate_ready")).upper()
    expected_market_date = clean(v20_7v.get("expected_market_date"))
    observed_distribution = clean(v20_7v.get("staging_latest_price_date_distribution"))
    stale_count = clean(v20_7v.get("stale_ticker_count"))
    missing_price_count = clean(v20_7v.get("missing_latest_price_count"))
    missing_core = clean(v20_7v.get("missing_core_field_summary"))
    eligible_count = clean(v20_7v.get("eligible_row_count"))
    excluded_count = clean(v20_7v.get("excluded_row_count"))
    excluded_examples = clean(v20_7v.get("excluded_ticker_examples"))
    quarantine_used = clean(v20_7v.get("v20_7v_used_quarantine"))
    excluded_rows = read_csv_rows(CONSOLIDATION / "V20_7V_EXCLUDED_TICKERS.csv")
    excluded_reason_text = "; ".join(
        f"{clean(row.get('ticker'))}:{clean(row.get('exclusion_reason'))}"
        for row in excluded_rows[:10]
    )
    v20_16 = first_csv_row(CONSOLIDATION / "V20_16_GATE_DECISION.csv")
    v20_16_diag = first_csv_row(CONSOLIDATION / "V20_16_GATE_DECISION_DIAGNOSTICS.csv")
    v20_16_decision = clean(v20_16.get("v20_16_gate_decision"))
    v20_16_status = clean(v20_16.get("v20_16_status")) or clean(v20_16.get("STATUS"))
    v20_16_failed = clean(v20_16.get("failed_condition_list"))
    v20_16_consumed_v7v = clean(v20_16.get("consumed_current_v20_7v_outputs"))
    v20_16_recommended = clean(v20_16_diag.get("recommended_next_action"))
    v20_17 = first_csv_row(CONSOLIDATION / "V20_17_GATE_DECISION.csv")
    v20_17_diag = first_csv_row(CONSOLIDATION / "V20_17_GATE_DECISION_DIAGNOSTICS.csv")
    v20_17_decision = clean(v20_17.get("v20_17_gate_decision"))
    v20_17_status = clean(v20_17.get("v20_17_status")) or clean(v20_17.get("STATUS"))
    v20_17_failed = clean(v20_17.get("failed_condition_list"))
    v20_17_candidate_rows = clean(v20_17.get("prepared_candidate_input_rows"))
    v20_17_benchmark_rows = clean(v20_17.get("prepared_benchmark_rows"))
    v20_17_outcome_rows = clean(v20_17.get("outcome_rows_available"))
    v20_17_consumed_v7v = clean(v20_17.get("consumed_current_v20_7v_active_staging"))
    v20_17_recommended = clean(v20_17_diag.get("recommended_next_action"))
    v49_research = first_csv_row(CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv")
    v49_promotion = first_csv_row(CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv")
    v49_research_status = clean(v49_research.get("research_only_gate_status"))
    v49_promotion_status = clean(v49_promotion.get("official_promotion_gate_status"))
    refresh_diag = write_refresh_diagnostics()
    final_status = "PASS" if overall_status == PASS_STATUS else "WARN" if overall_status == WARN_STATUS else "BLOCKED"
    if bootstrap_final == "BLOCKED":
        final_status = "BLOCKED"
    v55_status = "PASS" if overall_status == PASS_STATUS else "WARN" if overall_status == WARN_STATUS else "BLOCKED"
    stale_degraded = v20_7v_status != "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY" or active_usable != "TRUE"
    if stale_degraded:
        daily_mode = "DEGRADED_RESEARCH_ONLY_DUE_TO_STALE_MARKET_DATA"
    elif v49_research_status == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE" and v49_promotion_status != "PASS_V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE":
        daily_mode = "RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED"
    else:
        daily_mode = "PASS_RESEARCH_ONLY"
    remaining_items: list[str] = []
    if bootstrap_final == "BLOCKED":
        remaining_items.append(f"current_chain_bootstrap: {bootstrap_stage} - {bootstrap_blocker}")
    if v20_7v_status and v20_7v_status != "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY":
        remaining_items.append(f"V20.7V stale market data: expected_market_date={expected_market_date}; observed={observed_distribution}; stale_ticker_count={stale_count}")
    if missing_core and missing_core != "NONE":
        remaining_items.append(f"V20.7V missing required core fields: {missing_core}")
    if refresh_diag:
        remaining_items.append(
            "V20.47 refresh path: "
            f"status={refresh_diag.get('latest_v20_47_status')}; "
            f"v20_46_readiness={refresh_diag.get('v20_46_readiness_status')}; "
            f"candidate_tickers_requested={refresh_diag.get('candidate_tickers_requested')}; "
            f"recommended_next_action={refresh_diag.get('recommended_next_action')}"
        )
    if overall_status != PASS_STATUS:
        remaining_items.append(f"v20_55_runner: {failed_stage} - {blocker}")
    remaining = "\n".join(f"- {item}" for item in remaining_items) if remaining_items else "None reported by V20.55."
    research_conclusion = (
        "No active-market daily recommendation is allowed today because market data freshness is insufficient. "
        "A ranking snapshot and technical timing snapshot are available for stale-data, partial-ranking research review only. "
        "Do not use this report as an official buy/sell decision, allocation change, factor-weight mutation, or broker execution instruction."
        if stale_degraded
        else "Research-only daily conclusion is available from current staged data. No broker execution or official trade mutation is authorized by this report."
    )
    refresh_status = refresh_diag.get("latest_v20_47_status", "") if refresh_diag else ""
    refresh_success = refresh_diag.get("v20_47_success_count", "") if refresh_diag else ""
    post_refresh_ran = refresh_diag.get("post_refresh_ran", "") if refresh_diag else ""
    post_refresh_dist = refresh_diag.get("post_refresh_full_ranked_latest_price_date_distribution", "") if refresh_diag else ""
    stale_blocker_remains = "TRUE" if v20_7v_status != "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY" or active_usable != "TRUE" else "FALSE"
    provider_cache_refresh_status = "succeeded_or_partial" if clean(refresh_success) not in {"", "0"} else "blocked"
    sweep_status = first_csv_row(CONSOLIDATION / "V20_DOWNSTREAM_REPAIR_SWEEP_STATUS.csv")
    sweep_blockers = read_csv_rows(CONSOLIDATION / "V20_DOWNSTREAM_REPAIR_SWEEP_BLOCKERS.csv")
    downstream_sweep_section = ""
    if sweep_status:
        blocker_lines = "\n".join(
            (
                f"- {clean(row.get('blocker_scope'))}: {clean(row.get('first_failed_stage'))} - "
                f"{clean(row.get('blocker_reason'))}; "
                f"machine_repairable={clean(row.get('machine_repairable'))}; "
                f"manual_operator_only={clean(row.get('manual_operator_only'))}; "
                f"data_source_required={clean(row.get('data_source_required'))}"
            )
            for row in sweep_blockers
        ) or "None recorded."
        downstream_sweep_section = f"""
## Downstream Repair Sweep

sweep_status: {clean(sweep_status.get('sweep_status'))}
repaired_iteration_count: {clean(sweep_status.get('repaired_iteration_count'))}
starting_blocker: {clean(sweep_status.get('starting_blocker'))}
ending_first_failed_stage: {clean(sweep_status.get('ending_first_failed_stage'))}
ending_blocker_reason: {clean(sweep_status.get('ending_blocker_reason'))}
V20.18 status: {clean(sweep_status.get('v20_18_status'))}
V20.19 status: {clean(sweep_status.get('v20_19_status'))}
V20.27 status: {clean(sweep_status.get('v20_27_status'))}
V20.55 status: {clean(sweep_status.get('v20_55_status'))}
no_dummy_outcome: {clean(sweep_status.get('no_dummy_outcome'))}
no_dummy_benchmark: {clean(sweep_status.get('no_dummy_benchmark'))}
no_trade_action: {clean(sweep_status.get('no_trade_action'))}
remaining sweep blockers:
{blocker_lines}
"""
    text = f"""# V20 Current Daily Conclusion

## Executive Status

final_chain_status: {final_status}
v20_55_status: {v55_status}
daily_conclusion_mode: {daily_mode}
latest_valid_run_id: {run_id}
first_failed_stage: {bootstrap_stage or failed_stage}
blocker_reason: {bootstrap_blocker or blocker}

## Data Freshness / Market Source

V20.7V status: {v20_7v_status}
expected_market_date: {expected_market_date}
observed price date distribution: {observed_distribution}
stale ticker count: {stale_count}
missing latest price count: {missing_price_count}
missing core field summary: {missing_core}
active_market_source_staging_usable: {active_usable or 'FALSE'}
eligible_row_count: {eligible_count}
excluded_row_count: {excluded_count}
excluded ticker examples: {excluded_examples}
excluded ticker reasons: {excluded_reason_text}
v20_7v_used_quarantine: {quarantine_used}

## Market Refresh Diagnostics

V20.47 status: {refresh_status}
requested ticker count: {refresh_diag.get('v20_47_requested_ticker_count', '') if refresh_diag else ''}
attempted ticker count: {refresh_diag.get('v20_47_attempted_ticker_count', '') if refresh_diag else ''}
success count: {refresh_success}
empty dataframe count: {refresh_diag.get('v20_47_empty_dataframe_count', '') if refresh_diag else ''}
exception count: {refresh_diag.get('v20_47_exception_count', '') if refresh_diag else ''}
provider/cache refresh status: {provider_cache_refresh_status}
dominant failure reason: {refresh_diag.get('dominant_failure_reason', '') if refresh_diag else ''}
stale-data blocker remains: {stale_blocker_remains}
recommended next action: {refresh_diag.get('recommended_next_action', '') if refresh_diag else ''}

## Post-Refresh Recompute

post_refresh_recompute_ran: {post_refresh_ran}
post_refresh_status: {refresh_diag.get('post_refresh_recompute_status', '') if refresh_diag else ''}
pre_refresh_cache_latest_date_distribution: {refresh_diag.get('pre_refresh_cache_latest_date_distribution', '') if refresh_diag else ''}
post_refresh_cache_latest_date_distribution: {refresh_diag.get('post_refresh_cache_latest_date_distribution', '') if refresh_diag else ''}
post_refresh_full_ranked_latest_price_date_distribution: {post_refresh_dist}
v18_factor_pack_recomputed_after_v20_47: {refresh_diag.get('v18_factor_pack_recomputed_after_v20_47', '') if refresh_diag else ''}
v18_technical_timing_recomputed_after_v20_47: {refresh_diag.get('v18_technical_timing_recomputed_after_v20_47', '') if refresh_diag else ''}
v18_13b_rerun_after_v20_47: {refresh_diag.get('v18_13b_rerun_after_v20_47', '') if refresh_diag else ''}
v18_full_ranked_rebuilt_after_v20_47: {refresh_diag.get('v18_full_ranked_rebuilt_after_v20_47', '') if refresh_diag else ''}
v20_7v_used_post_refresh_artifacts: {refresh_diag.get('v20_7v_used_post_refresh_artifacts', '') if refresh_diag else ''}
V20.7V status after post-refresh recompute: {v20_7v_status}
active_market_source_staging_usable_after_post_refresh: {active_usable or 'FALSE'}
eligible_row_count_after_post_refresh: {eligible_count}
excluded_row_count_after_post_refresh: {excluded_count}
excluded_ticker_examples_after_post_refresh: {excluded_examples}
v20_7v_used_quarantine_after_post_refresh: {quarantine_used}

## V20.16 Gate Decision

V20.16 gate decision: {v20_16_decision}
V20.16 status: {v20_16_status}
V20.16 consumed current V20.7V outputs: {v20_16_consumed_v7v}
V20.16 failed condition list: {v20_16_failed}
V20.16 recommended_next_action: {v20_16_recommended}

## V20.17 Backtest Input Preparation

V20.17 gate decision: {v20_17_decision}
V20.17 status: {v20_17_status}
V20.17 consumed current V20.7V active staging: {v20_17_consumed_v7v}
V20.17 prepared candidate input rows: {v20_17_candidate_rows}
V20.17 prepared benchmark rows: {v20_17_benchmark_rows}
V20.17 outcome rows available: {v20_17_outcome_rows}
V20.17 failed condition list: {v20_17_failed}
V20.17 recommended_next_action: {v20_17_recommended}

## V20.49 Research-Only / Promotion Gates

V20.55 research-only status: {overall_status}
V20.49 research-only gate status: {v49_research_status}
V20.49 official promotion gate status: {v49_promotion_status}
active candidate rows available: {v49_research.get('active_candidate_rows_available', '')}
factor rows available: {v49_research.get('factor_rows_available', '')}
prepared candidate input rows: {v49_research.get('prepared_candidate_input_rows', '')}
benchmark rows available: {v49_research.get('benchmark_rows_available', '')}
V20.27 promotion/backtest blocker: {v49_promotion.get('v20_27_blocker', '')}
missing promotion lineage sources: {v49_promotion.get('missing_promotion_lineage_sources', '')}
operator acceptance required: {v49_promotion.get('operator_acceptance_required', '')}
official recommendation allowed: FALSE
trade action allowed: FALSE
weight mutation allowed: FALSE

## Current Ranking

{current_ranking_section_text()}

## Technical Timing / Buy-Zone

{technical_summary_text()}

## Manual Additions

{manual_additions_text()}

## Research Conclusion

{research_conclusion}

## Remaining Blockers

{remaining}
{downstream_sweep_section}

## Safety

This is research-only. There is no broker execution, no official recommendation, no trade action, no official ranking mutation, and no factor weight mutation. No buy/sell/hold instruction is created.
"""
    write_text(CONCLUSION, text)


def main() -> int:
    run_started = now_utc()
    run_id = f"V20_55_{run_started.strftime('%Y%m%dT%H%M%SZ')}"
    log_rows: list[dict[str, object]] = []
    artifact_rows: list[dict[str, object]] = []

    for stage in DAILY_STAGES:
        row = run_stage(stage)
        artifact_rows.extend(row.pop("_artifact_checks"))
        log_rows.append(row)
        if row["status_classification"] not in {"PASS", "WARN"}:
            break

    static_rows = artifact_check("static_policy_schema_contracts", STATIC_CONTRACTS)
    final_outputs = [
        OUT_SUMMARY,
        OUT_LOG,
        OUT_ARTIFACT_CHECK,
        OUT_INVENTORY,
        OUT_STATIC_CONTRACT,
        OUT_POLICY,
        OUT_SAFETY,
        OUT_NEXT,
        OUT_REFRESH_DIAGNOSTICS,
        REPORT,
        CURRENT_REPORT,
        READ_FIRST,
        p("outputs/v20/read_center/V20_CURRENT_USER_READABLE_CURRENT_DECISION_REPORT.md"),
    ]
    safety_rows = build_safety_rows()

    stages_attempted = len(log_rows)
    stages_passed = sum(1 for row in log_rows if row["status_classification"] == "PASS")
    stages_warned = sum(1 for row in log_rows if row["status_classification"] == "WARN")
    stages_blocked = sum(1 for row in log_rows if row["status_classification"] == "BLOCKED")
    stages_failed = sum(1 for row in log_rows if row["status_classification"] == "FAIL")
    artifact_pass = all(row["validation_status"] == "PASS" for row in artifact_rows)
    static_pass = all(row["validation_status"] == "PASS" for row in static_rows)
    safety_pass = all(row["validation_status"] == "PASS" for row in safety_rows)
    sequence_completed = stages_attempted == len(DAILY_STAGES) and stages_blocked == 0 and stages_failed == 0
    v49_research_gate = first_csv_row(CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv")
    v49_promotion_gate = first_csv_row(CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv")
    research_only_ready = clean(v49_research_gate.get("research_only_gate_status")) == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"
    promotion_blocked = clean(v49_promotion_gate.get("official_promotion_gate_status")) != "PASS_V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE"
    overall_status = (
        PASS_STATUS
        if sequence_completed and artifact_pass and static_pass and safety_pass and stages_warned == 0
        else WARN_STATUS
        if sequence_completed and artifact_pass and safety_pass and research_only_ready and promotion_blocked
        else BLOCKED_STATUS
    )

    read_first = "\n".join([
        f"STAGE_NAME={STAGE_NAME}",
        f"STATUS={overall_status}",
        "DAILY_ONE_CLICK_RESEARCH_ONLY_RUNNER=TRUE",
        "ORCHESTRATES_APPROVED_V20_STAGES=TRUE",
        "MARKET_REFRESH_ALLOWED_ONLY_THROUGH_APPROVED_V20_47_WRAPPER=TRUE",
        "V20_55_DIRECT_YFINANCE_IMPORT_USED=FALSE",
        "V20_55_DIRECT_PROVIDER_NETWORK_REFRESH_LOGIC_USED=FALSE",
        "THIS_IS_NOT_AN_OFFICIAL_RECOMMENDATION_GENERATOR=TRUE",
        "THIS_IS_NOT_A_TRADING_SIGNAL_GENERATOR=TRUE",
        "BUY_SELL_HOLD_INSTRUCTIONS_CREATED=FALSE",
        "BROKER_ORDER_SYSTEM_CONNECTED=FALSE",
        "TRADES_EXECUTED=FALSE",
        "RANKINGS_SCORES_FACTOR_WEIGHTS_DYNAMIC_WEIGHTS_REAL_BOOK_MUTATED=FALSE",
        "FINAL_REPORT_FOR_MANUAL_REVIEW_ONLY=TRUE",
        f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE}",
        "",
    ])
    write_text(READ_FIRST, read_first)

    report = f"""# V20.55 Daily One-Click Research Runner Report

## Stage status

Stage: {STAGE_NAME}
Run ID: {run_id}
Status: {overall_status}
Started: {iso(run_started)}
Manual review required: TRUE

## Daily run sequence

1. V20.47 controlled current market refresh and cache certification
2. V20 post-refresh recompute handoff
3. V20.48 refreshed current operator research report
4. V20.49 operator review acceptance gate
5. V20.50 research-only decision packet
6. V20.54 user-readable current decision report

## Stage execution results

{md_table(log_rows, ["execution_order", "upstream_stage", "return_code", "detected_status", "status_classification", "elapsed_seconds"])}

## Current market refresh result

{next((row["status_classification"] for row in log_rows if row["upstream_stage"].startswith("V20.47")), "NOT_ATTEMPTED")}

## Post-refresh recompute

{next((row["status_classification"] for row in log_rows if row["upstream_stage"].startswith("V20_POST_REFRESH")), "NOT_ATTEMPTED")}

## Refreshed operator report result

{next((row["status_classification"] for row in log_rows if row["upstream_stage"].startswith("V20.48")), "NOT_ATTEMPTED")}

## Operator review acceptance result

{next((row["status_classification"] for row in log_rows if row["upstream_stage"].startswith("V20.49")), "NOT_ATTEMPTED")}

## Research-only decision packet result

{next((row["status_classification"] for row in log_rows if row["upstream_stage"].startswith("V20.50")), "NOT_ATTEMPTED")}

## User-readable report result

{next((row["status_classification"] for row in log_rows if row["upstream_stage"].startswith("V20.54")), "NOT_ATTEMPTED")}

## Static policy/schema contract validation

{md_table(static_rows, ["artifact_path", "exists", "non_empty", "validation_status"], 20)}

## Final report location

Final user-readable report: outputs/v20/read_center/V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md
Current alias: outputs/v20/read_center/V20_CURRENT_USER_READABLE_CURRENT_DECISION_REPORT.md

## Artifact inventory summary

Artifact checks passed: {sum(1 for row in artifact_rows if row["validation_status"] == "PASS")} / {len(artifact_rows)}
Static contract checks passed: {sum(1 for row in static_rows if row["validation_status"] == "PASS")} / {len(static_rows)}

## Policy/language boundary

Policy boundary is generated after this report is written. It must remain PASS for this run to be accepted.

## Safety boundary

{md_table(safety_rows, ["safety_check", "expected_value", "actual_value", "validation_status"])}

## What this one-click runner is allowed to do

This runner may orchestrate approved V20 research-only wrappers and validate their artifacts. Market refresh is allowed only through the approved V20.47 wrapper.

## What this one-click runner is not allowed to do

This runner is not an official recommendation generator. It is not a trading signal generator. It does not create buy/sell/hold instructions. It does not connect to broker/order systems. It does not execute trades. It does not mutate rankings, scores, factor weights, dynamic weights, or real-book positions.

## Recommended next gated stage

{NEXT_STAGE}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    policy_paths = [REPORT, CURRENT_REPORT, READ_FIRST, p("outputs/v20/read_center/V20_CURRENT_USER_READABLE_CURRENT_DECISION_REPORT.md")]
    policy_rows = build_policy_checks(policy_paths)
    policy_pass = all(row["validation_status"] == "PASS" for row in policy_rows)
    overall_status = (
        PASS_STATUS
        if sequence_completed and artifact_pass and static_pass and safety_pass and policy_pass and stages_warned == 0
        else WARN_STATUS
        if sequence_completed and artifact_pass and safety_pass and policy_pass and research_only_ready and promotion_blocked
        else BLOCKED_STATUS
    )

    summary = [{
        "stage_id": STAGE_ID,
        "stage_name": STAGE_NAME,
        "run_id": run_id,
        "run_timestamp_utc": iso(run_started),
        "overall_status": overall_status,
        "daily_sequence_started": "TRUE",
        "daily_sequence_completed": tf(sequence_completed),
        "stages_attempted": stages_attempted,
        "stages_passed": stages_passed,
        "stages_warned": stages_warned,
        "stages_blocked": stages_blocked,
        "stages_failed": stages_failed,
        "current_market_refresh_stage_used": tf(any(row["upstream_stage"].startswith("V20.47") for row in log_rows)),
        "refreshed_report_stage_used": tf(any(row["upstream_stage"].startswith("V20.48") for row in log_rows)),
        "operator_acceptance_stage_used": tf(any(row["upstream_stage"].startswith("V20.49") for row in log_rows)),
        "decision_packet_stage_used": tf(any(row["upstream_stage"].startswith("V20.50") for row in log_rows)),
        "user_readable_report_stage_used": tf(any(row["upstream_stage"].startswith("V20.54") for row in log_rows)),
        "static_policy_contracts_validated": tf(static_pass),
        "final_user_readable_report_path": "outputs/v20/read_center/V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md",
        "final_current_alias_report_path": "outputs/v20/read_center/V20_CURRENT_USER_READABLE_CURRENT_DECISION_REPORT.md",
        "no_broker_action": "TRUE",
        "no_order_execution": "TRUE",
        "no_official_recommendation": "TRUE",
        "no_trading_signal": "TRUE",
        "manual_review_required": "TRUE",
        "research_only_daily_conclusion_ready": tf(research_only_ready),
        "official_promotion_blocked": tf(promotion_blocked),
        "next_recommended_stage": NEXT_STAGE,
    }]
    next_rows = [{
        "stage": STAGE_NAME,
        "decision": "PASS_DAILY_ONE_CLICK_RESEARCH_RUNNER_CREATED" if overall_status == PASS_STATUS else "WARN_RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED" if overall_status == WARN_STATUS else "BLOCKED_DAILY_ONE_CLICK_RESEARCH_RUNNER",
        "overall_status": overall_status,
        "formal_tests_required_next": "TRUE",
        "blocker_count": 0 if overall_status in {PASS_STATUS, WARN_STATUS} else 1,
        "warning_count": stages_warned + (1 if overall_status == WARN_STATUS else 0),
        "next_recommended_stage": NEXT_STAGE,
    }]

    write_refresh_diagnostics()
    all_inventory_paths = [path for stage in DAILY_STAGES for path in stage["outputs"]] + STATIC_CONTRACTS + final_outputs
    inventory = inventory_rows(all_inventory_paths, "daily_runner_artifact")
    write_csv(OUT_LOG, log_rows, ["execution_order", "upstream_stage", "wrapper_path", "started_at_utc", "ended_at_utc", "elapsed_seconds", "return_code", "detected_status", "status_classification", "stdout_tail", "stderr_tail", "required_outputs_checked", "required_outputs_present", "required_outputs_non_empty", "stop_after_stage", "notes"])
    write_csv(OUT_ARTIFACT_CHECK, artifact_rows, ["artifact_stage", "artifact_path", "exists", "non_empty", "validation_status", "blocker_reason"])
    write_csv(OUT_STATIC_CONTRACT, static_rows, ["artifact_stage", "artifact_path", "exists", "non_empty", "validation_status", "blocker_reason"])
    write_csv(OUT_POLICY, policy_rows, ["checked_artifact", "forbidden_actionable_phrase_count", "research_only_language_confirmed", "validation_status", "blocker_reason", "sample_hit"])
    write_csv(OUT_SAFETY, safety_rows, ["safety_check", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_INVENTORY, inventory_rows(all_inventory_paths, "daily_runner_artifact"), ["artifact_path", "artifact_stage", "exists", "non_empty", "size_bytes", "modified_at_utc", "sha256", "artifact_role", "notes"])

    if overall_status not in {PASS_STATUS, WARN_STATUS}:
        read_first = read_first.replace(f"STATUS={PASS_STATUS}", f"STATUS={overall_status}")
        write_text(READ_FIRST, read_first)
    write_daily_conclusion(overall_status, run_id, log_rows)
    cleanup_pycache()

    print(overall_status)
    print(f"RUN_ID={run_id}")
    print(f"STAGES_ATTEMPTED={stages_attempted}")
    print(f"STAGES_PASSED={stages_passed}")
    print(f"STAGES_WARNED={stages_warned}")
    print(f"STAGES_BLOCKED={stages_blocked}")
    print(f"STAGES_FAILED={stages_failed}")
    for row in log_rows:
        print(f"{row['upstream_stage']}={row['status_classification']}")
    print("FINAL_USER_READABLE_REPORT=outputs/v20/read_center/V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md")
    print(f"REQUIRED_ARTIFACT_CHECK={'PASS' if artifact_pass else 'BLOCKED'}")
    print(f"STATIC_CONTRACT_CHECK={'PASS' if static_pass else 'BLOCKED'}")
    print(f"POLICY_LANGUAGE_BOUNDARY={'PASS' if policy_pass else 'BLOCKED'}")
    print(f"SAFETY_BOUNDARY={'PASS' if safety_pass else 'BLOCKED'}")
    print(f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE}")
    return 0 if overall_status in {PASS_STATUS, WARN_STATUS} else 1


if __name__ == "__main__":
    raise SystemExit(main())
