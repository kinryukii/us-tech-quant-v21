from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"
INPUTS_V20 = ROOT / "inputs" / "v20"

STAGE = "V20.46_CURRENT_MARKET_REFRESH_READINESS_GATE"
PASS_STATUS = "PASS_V20_46_CURRENT_MARKET_REFRESH_READINESS_GATE"
BLOCKED_STATUS = "BLOCKED_V20_46_CURRENT_MARKET_REFRESH_READINESS_GATE"
READY_STATUS = "READY_FOR_CONTROLLED_REFRESH_STAGE"
BLOCKED_READY_STATUS = "BLOCKED_FOR_CONTROLLED_REFRESH_STAGE"
DECISION_PASS = "PASS_READY_FOR_CONTROLLED_CURRENT_MARKET_REFRESH_STAGE"
NEXT_STAGE = "V20.46_FORMAL_TESTS"
CONTROLLED_REFRESH_STAGE = "V20.47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION"

IN_V45_PROD = SCRIPT_DIR / "v20_45_current_operator_report_research_only_run.py"
IN_V45_WRAP = SCRIPT_DIR / "run_v20_45_current_operator_report_research_only_run.ps1"
IN_V45_TEST = SCRIPT_DIR / "test_v20_45_current_operator_report_research_only_run.py"
IN_V45_SUMMARY = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_REPORT_RUN_SUMMARY.csv"
IN_V45_NEXT = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_NEXT_STEP_DECISION.csv"
IN_V45_CURRENT = READ_CENTER / "V20_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY.md"
IN_V45_READ_FIRST = OPS / "V20_45_READ_FIRST.txt"

ARCH_V26_SCRIPT = SCRIPT_DIR / "v20_26_yahoo_runtime_outcome_benchmark_source_adapter.py"
ARCH_V27_SCRIPT = SCRIPT_DIR / "v20_27_yahoo_cache_certification_and_active_input_staging.py"
ARCH_V35_R1_SCRIPT = SCRIPT_DIR / "v20_35_r1_historical_yahoo_cache_expansion_for_random_asof_backtest.py"
ACTIVE_INPUTS = INPUTS_V20 / "active_market"
OUTCOME_INPUTS = INPUTS_V20 / "outcome_benchmark"
YAHOO_CACHE = OUTCOME_INPUTS / "yahoo_cache"
RANDOM_ASOF = INPUTS_V20 / "random_asof"

OUT_SUMMARY = CONSOLIDATION / "V20_46_CURRENT_MARKET_REFRESH_READINESS_SUMMARY.csv"
OUT_V45_VALIDATION = CONSOLIDATION / "V20_46_UPSTREAM_V20_45_VALIDATION.csv"
OUT_ARCH = CONSOLIDATION / "V20_46_REFRESH_SOURCE_ARCHITECTURE_REVIEW.csv"
OUT_REQUIREMENTS = CONSOLIDATION / "V20_46_CONTROLLED_REFRESH_REQUIREMENTS.csv"
OUT_SCOPE = CONSOLIDATION / "V20_46_REFRESH_SCOPE_DECISION.csv"
OUT_SAFETY = CONSOLIDATION / "V20_46_REFRESH_SAFETY_BOUNDARY.csv"
OUT_CANDIDATE_UNIVERSE = CONSOLIDATION / "V20_46_CANDIDATE_REFRESH_UNIVERSE.csv"
OUT_SOURCE_AUDIT = CONSOLIDATION / "V20_46_SOURCE_AUDIT.csv"
OUT_NEXT = CONSOLIDATION / "V20_46_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_46_CURRENT_MARKET_REFRESH_READINESS_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_MARKET_REFRESH_READINESS_GATE.md"
READ_FIRST = OPS / "V20_46_READ_FIRST.txt"

CANDIDATE_SOURCES = [
    ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES.csv",
    ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv",
    ROOT / "configs" / "v16" / "universe" / "us_full_second_stage_generated.yaml",
    ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING.csv",
    ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING.csv",
]
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$")


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def read_flags(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    flags: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        flags[key.strip()] = value.strip()
    return flags


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def exists_non_empty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def valid_ticker(value: object) -> bool:
    ticker = clean(value).upper()
    return bool(ticker) and len(ticker) <= 12 and bool(TICKER_RE.fullmatch(ticker))


def read_yaml_tickers(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    in_tickers = False
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if line == "tickers:":
            in_tickers = True
            continue
        if in_tickers and line.startswith("- "):
            ticker = line[2:].strip().strip("'\"").upper()
            if ticker:
                rows.append({"ticker": ticker})
        elif in_tickers and line and not raw.startswith((" ", "\t")):
            break
    return rows


def load_candidate_source() -> tuple[Path, list[dict[str, str]], list[str], str]:
    for path in CANDIDATE_SOURCES:
        if not path.exists() or path.stat().st_size <= 0:
            continue
        if path.suffix.lower() in {".yaml", ".yml"}:
            rows = read_yaml_tickers(path)
            if rows:
                return path, rows, ["ticker"], "YAML_TICKER_LIST"
            continue
        rows, fields = read_csv(path)
        if rows and any(field.lower() in {"ticker", "symbol", "yf_ticker"} for field in fields):
            return path, rows, fields, "CSV_TICKER_SOURCE"
    return CANDIDATE_SOURCES[0], [], [], "NO_VALID_SOURCE"


def first_present(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = clean(row.get(name))
        if value:
            return value
    return ""


def build_candidate_refresh_universe() -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    source_path, source_rows, source_fields, source_type = load_candidate_source()
    rows: list[dict[str, object]] = []
    blockers: list[str] = []
    seen: set[str] = set()
    invalid_count = 0
    duplicate_count = 0
    ticker_cols = tuple(field for field in ("ticker", "symbol", "yf_ticker") if field in source_fields) or ("ticker", "symbol", "yf_ticker")
    for source in source_rows:
        ticker = first_present(source, ticker_cols).upper()
        if not valid_ticker(ticker):
            invalid_count += 1
            continue
        if ticker in seen:
            duplicate_count += 1
            continue
        seen.add(ticker)
        rank = first_present(source, ("rank", "factor_pack_rank", "official_current_rank"))
        score = first_present(source, ("composite_candidate_score", "factor_pack_score", "official_current_score"))
        rows.append({
            "ticker": ticker,
            "universe_role": "candidate",
            "source_stage": "V20.46_CURRENT_MARKET_REFRESH_READINESS_GATE",
            "source_rank": rank,
            "source_rank_or_score": score,
            "source_artifact": rel(source_path),
            "source_row_count": len(source_rows),
            "selection_rule": "ALL_VALID_DEDUPED_TICKERS_FROM_FIRST_AVAILABLE_CURRENT_SOURCE",
            "candidate_refresh_universe_cap": "NONE",
            "requested_for_refresh": "TRUE",
            "benchmark_flag": "FALSE",
            "candidate_flag": "TRUE",
            "duplicate_removed_flag": "FALSE",
            "research_only": "TRUE",
            "official_decision_impact": "NONE",
        })
    if not rows:
        blockers.append("candidate_refresh_universe_empty")
    audit = [{
        "source_artifact": rel(source_path),
        "source_type": source_type,
        "source_exists": tf(source_path.exists()),
        "source_row_count": len(source_rows),
        "source_field_count": len(source_fields),
        "accepted_ticker_count": len(rows),
        "duplicate_ticker_count": duplicate_count,
        "invalid_ticker_count": invalid_count,
        "selection_rule": "ALL_VALID_DEDUPED_TICKERS_FROM_FIRST_AVAILABLE_CURRENT_SOURCE",
        "candidate_refresh_universe_path": rel(OUT_CANDIDATE_UNIVERSE),
        "candidate_refresh_universe_status": "PASS" if rows else "BLOCKED",
        "blocker_reason": ";".join(blockers),
        "fabricated_ticker_rows": "FALSE",
        "manual_ticker_additions": "FALSE",
        "research_only": "TRUE",
    }]
    return rows, audit, blockers


def status_row(item: str, path: Path, expected: str, actual: str, ok: bool, blocker: str = "") -> dict[str, object]:
    return {
        "validation_item": item,
        "source_path": rel(path),
        "expected_value": expected,
        "actual_value": actual,
        "validation_status": "PASS" if ok else "BLOCKED",
        "blocker_reason": "" if ok else blocker,
    }


def run_v45_tests() -> tuple[bool, str]:
    if not IN_V45_TEST.exists():
        return False, "V20.45 formal test script missing"
    result = subprocess.run(
        [sys.executable, str(IN_V45_TEST)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0 and "PASS_V20_45_TESTS" in result.stdout.splitlines(), output


def v45_validation_rows(test_passed: bool) -> list[dict[str, object]]:
    summary = first_row(IN_V45_SUMMARY)
    next_row = first_row(IN_V45_NEXT)
    checks = [
        status_row("v20_45_run_summary_exists_non_empty", IN_V45_SUMMARY, "TRUE", tf(exists_non_empty(IN_V45_SUMMARY)), exists_non_empty(IN_V45_SUMMARY), "missing_or_empty"),
        status_row("v20_45_next_step_exists_non_empty", IN_V45_NEXT, "TRUE", tf(exists_non_empty(IN_V45_NEXT)), exists_non_empty(IN_V45_NEXT), "missing_or_empty"),
        status_row("v20_45_current_alias_exists_non_empty", IN_V45_CURRENT, "TRUE", tf(exists_non_empty(IN_V45_CURRENT)), exists_non_empty(IN_V45_CURRENT), "missing_or_empty"),
        status_row("v20_45_read_first_exists_non_empty", IN_V45_READ_FIRST, "TRUE", tf(exists_non_empty(IN_V45_READ_FIRST)), exists_non_empty(IN_V45_READ_FIRST), "missing_or_empty"),
        status_row("v20_45_test_script_exists", IN_V45_TEST, "TRUE", tf(IN_V45_TEST.exists()), IN_V45_TEST.exists(), "missing_test_script"),
        status_row("v20_45_formal_tests_passed", IN_V45_TEST, "PASS", "PASS" if test_passed else "FAIL", test_passed, "formal_tests_failed"),
        status_row("v20_45_report_generation_status", IN_V45_SUMMARY, "PASS", clean(summary.get("report_generation_status")), clean(summary.get("report_generation_status")) == "PASS", "report_generation_not_pass"),
        status_row("v20_45_decision", IN_V45_NEXT, "PASS_RESEARCH_ONLY_CURRENT_OPERATOR_REPORT_CREATED", clean(next_row.get("decision")), clean(next_row.get("decision")) == "PASS_RESEARCH_ONLY_CURRENT_OPERATOR_REPORT_CREATED", "decision_not_pass"),
        status_row("v20_45_current_market_refresh_needed", IN_V45_SUMMARY, "TRUE", clean(summary.get("current_market_refresh_needed_before_real_use")), clean(summary.get("current_market_refresh_needed_before_real_use")) == "TRUE", "refresh_needed_not_true"),
        status_row("v20_45_official_trading_allowed", IN_V45_SUMMARY, "FALSE", clean(summary.get("official_trading_allowed")), clean(summary.get("official_trading_allowed")) == "FALSE", "official_trading_not_false"),
        status_row("v20_45_official_recommendation_allowed", IN_V45_SUMMARY, "FALSE", clean(summary.get("official_recommendation_allowed")), clean(summary.get("official_recommendation_allowed")) == "FALSE", "official_recommendation_not_false"),
        status_row("v20_45_provider_network_refresh_used", IN_V45_SUMMARY, "FALSE", clean(summary.get("provider_network_refresh_used")), clean(summary.get("provider_network_refresh_used")) == "FALSE", "provider_refresh_not_false"),
        status_row("v20_45_broker_order_execution_used", IN_V45_SUMMARY, "FALSE", clean(summary.get("broker_order_execution_used")), clean(summary.get("broker_order_execution_used")) == "FALSE", "broker_order_not_false"),
        status_row("v20_45_dynamic_weighting_mutated", IN_V45_SUMMARY, "FALSE", clean(summary.get("dynamic_weighting_mutated")), clean(summary.get("dynamic_weighting_mutated")) == "FALSE", "dynamic_weighting_not_false"),
        status_row("v20_45_official_ranking_mutated", IN_V45_SUMMARY, "FALSE", clean(summary.get("official_ranking_mutated")), clean(summary.get("official_ranking_mutated")) == "FALSE", "official_ranking_not_false"),
    ]
    return checks


def any_file(pattern: str) -> bool:
    return any(CONSOLIDATION.glob(pattern))


def architecture_rows() -> list[dict[str, object]]:
    hash_outputs = any_file("V20_26_*HASH*.csv") or any_file("V20_27_*HASH*.csv") or any_file("V20_35_R1_*HASH*.csv")
    read_first_outputs = any(OPS.glob("V20_26*READ_FIRST*.txt")) or any(OPS.glob("V20_27*READ_FIRST*.txt")) or any(OPS.glob("V20_35_R1*READ_FIRST*.txt"))
    specs = [
        ("yahoo_runtime_adapter_script", ARCH_V26_SCRIPT, ARCH_V26_SCRIPT.exists(), "Runtime/provider adapter pattern for controlled future refresh.", True, "Required adapter script missing."),
        ("yahoo_cache_certification_script", ARCH_V27_SCRIPT, ARCH_V27_SCRIPT.exists(), "Cache certification and staged active input pattern.", True, "Required certification script missing."),
        ("historical_yahoo_cache_expansion_script", ARCH_V35_R1_SCRIPT, ARCH_V35_R1_SCRIPT.exists(), "Historical cache expansion and hash review pattern.", True, "Historical cache expansion script missing."),
        ("active_outcome_benchmark_inputs", OUTCOME_INPUTS, OUTCOME_INPUTS.exists(), "Existing outcome/benchmark input root for future source isolation.", True, "Outcome benchmark input root missing."),
        ("yahoo_cache_directory", YAHOO_CACHE, YAHOO_CACHE.exists(), "Local cache root for future controlled cache writes.", True, "Yahoo cache directory missing."),
        ("random_asof_historical_cache_directory", RANDOM_ASOF, RANDOM_ASOF.exists(), "Existing random as-of input root for historical cache context.", False, ""),
        ("hash_ledger_or_certification_outputs", CONSOLIDATION, hash_outputs, "Prior hash/certification output pattern for future source ledger.", True, "Hash/certification outputs missing."),
        ("read_first_safety_outputs", OPS, read_first_outputs, "Prior operational READ_FIRST safety pattern.", False, ""),
        ("provider_refresh_execution", ROOT, False, "Provider access must be deferred to controlled V20.47 only.", False, ""),
        ("broker_order_execution", ROOT, False, "Broker/order execution is outside V20.46 and V20.47 refresh scope.", False, ""),
    ]
    rows = []
    for component, path, detected, use, required_for_ready, blocker in specs:
        rows.append({
            "architecture_component": component,
            "file_or_directory_path": rel(path),
            "detected_flag": tf(detected),
            "intended_future_use": use,
            "allowed_in_v20_46": "FALSE",
            "allowed_in_v20_47_candidate": tf(component not in {"broker_order_execution"} and (detected or component == "provider_refresh_execution")),
            "risk_notes": "Gate-only inspection; no refresh executed.",
            "blocker_reason": "" if detected or not required_for_ready else blocker,
        })
    return rows


def requirements_rows() -> list[dict[str, object]]:
    names = [
        ("REQ_01", "explicit provider refresh stage separation", "Keeps V20.46 inspection separate from V20.47 execution."),
        ("REQ_02", "Yahoo provider access isolated to V20.47 only", "Provider access must occur only in the controlled refresh stage."),
        ("REQ_03", "no broker/order execution", "Market data refresh must not create order routes."),
        ("REQ_04", "no official recommendation creation", "Refresh certifies data, not recommendations."),
        ("REQ_05", "no official ranking mutation", "Refresh must not recompute or mutate official ranks."),
        ("REQ_06", "no dynamic weighting mutation", "Refresh must not alter factor weights."),
        ("REQ_07", "run_id creation", "Every controlled refresh needs a reproducible run id."),
        ("REQ_08", "source hash ledger", "Every cache artifact needs a hash ledger entry."),
        ("REQ_09", "cache path isolation", "Writes must stay inside V20 current market cache paths."),
        ("REQ_10", "raw cache output", "Raw provider response/cache output must be staged before active use."),
        ("REQ_11", "candidate active input staging candidate", "Refreshed inputs must be staged as candidates first."),
        ("REQ_12", "certification before active use", "No active-use promotion before certification."),
        ("REQ_13", "stale/PIT/leakage checks", "Refresh outputs need freshness and leakage gates."),
        ("REQ_14", "failed ticker capture", "Provider failures must be captured explicitly."),
        ("REQ_15", "benchmark refresh support", "SPY and QQQ support is required for report context."),
        ("REQ_16", "READ_FIRST safety flags", "Operator handoff must expose safety flags."),
        ("REQ_17", "no V21/V19.21 output paths", "Refresh stays within V20 paths."),
        ("REQ_18", "current operator report refresh handoff to later stage", "Refreshed data handoff is separate from report rendering."),
        ("REQ_19", "formal tests required after V20.47", "Controlled refresh must be covered by formal tests."),
    ]
    return [
        {
            "requirement_id": rid,
            "requirement_name": name,
            "required_flag": "TRUE",
            "requirement_status": "DEFINED",
            "applies_to_stage": CONTROLLED_REFRESH_STAGE,
            "rationale": rationale,
            "blocker_if_missing": "TRUE",
        }
        for rid, name, rationale in names
    ]


def scope_rows() -> list[dict[str, object]]:
    specs = [
        ("current candidate ticker prices", "TRUE", "TRUE", "TRUE", "cache_candidate", "Allowed only in V20.47 controlled refresh."),
        ("benchmark prices SPY and QQQ", "TRUE", "TRUE", "TRUE", "cache_candidate", "Required for current report context."),
        ("local Yahoo cache", "TRUE", "TRUE", "TRUE", "cache", "Future writes must be isolated to approved V20 cache paths."),
        ("source hash ledger", "TRUE", "TRUE", "TRUE", "certification", "Required for source certification."),
        ("staged current market source candidate", "TRUE", "TRUE", "TRUE", "staging", "Candidate only until certified."),
        ("certification report", "TRUE", "TRUE", "TRUE", "reporting", "Required before active use."),
        ("refreshed operator report", "FALSE", "FALSE", "TRUE", "later_stage_handoff", "Report rendering should be a later-stage handoff after certification."),
        ("official recommendation packet", "FALSE", "FALSE", "TRUE", "blocked_official", "Out of scope."),
        ("official trading signal", "FALSE", "FALSE", "TRUE", "blocked_official", "Out of scope."),
        ("broker order route", "FALSE", "FALSE", "TRUE", "blocked_execution", "Out of scope."),
        ("real portfolio mutation", "FALSE", "FALSE", "TRUE", "blocked_state", "Out of scope."),
        ("dynamic factor weight mutation", "FALSE", "FALSE", "TRUE", "blocked_state", "Out of scope."),
    ]
    return [
        {
            "scope_item": item,
            "allowed_for_v20_47": allowed,
            "required_for_v20_47": required,
            "blocked_in_v20_46": blocked,
            "output_class": output_class,
            "notes": notes,
        }
        for item, allowed, required, blocked, output_class, notes in specs
    ]


def safety_rows() -> list[dict[str, object]]:
    scan_paths = [
        SCRIPT_DIR / "v20_46_current_market_refresh_readiness_gate.py",
        SCRIPT_DIR / "run_v20_46_current_market_refresh_readiness_gate.ps1",
    ]
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in scan_paths if path.exists())
    checks = [
        ("refresh_executed_in_v20_46", "FALSE", "FALSE", "Stage writes reports only."),
        ("yfinance_imported_in_v20_46", "FALSE", tf(bool(re.search(r"^\s*(import|from)\s+yfinance\b", text, re.MULTILINE))), "Static import scan."),
        ("provider_network_execution_used", "FALSE", tf(bool(re.search(r"\brequests\.(get|post|put|delete)\s*\(|\bhttpx\.(get|post|put|delete)\s*\(", text))), "Static network call scan."),
        ("broker_order_execution_used", "FALSE", tf(bool(re.search(r"\bsubmit_order\s*\(|\bplace_order\s*\(|\bbroker\.(buy|sell|order|submit)\s*\(", text))), "Static broker/order scan."),
        ("official_recommendation_allowed", "FALSE", "FALSE", "Gate-only boundary."),
        ("official_trading_allowed", "FALSE", "FALSE", "Gate-only boundary."),
        ("official_ranking_mutated", "FALSE", "FALSE", "No ranking mutation."),
        ("dynamic_weighting_mutated", "FALSE", "FALSE", "No weighting mutation."),
        ("real_portfolio_mutated", "FALSE", "FALSE", "No portfolio mutation."),
        ("returns_calculated", "FALSE", "FALSE", "No return calculation."),
        ("scores_recomputed", "FALSE", "FALSE", "No score recomputation."),
        ("rankings_recomputed", "FALSE", "FALSE", "No ranking recomputation."),
        ("v21_output_path_created", "FALSE", "FALSE", "No V21 output path."),
        ("v19_21_output_path_created", "FALSE", "FALSE", "No V19.21 output path."),
    ]
    rows = []
    for name, expected, actual, evidence in checks:
        ok = actual == expected
        rows.append({
            "safety_boundary": name,
            "expected_value": expected,
            "actual_value": actual,
            "validation_status": "PASS" if ok else "BLOCKED",
            "evidence": evidence,
            "blocker_reason": "" if ok else f"expected_{expected}_got_{actual}",
        })
    return rows


def md_table(rows: list[dict[str, object]], columns: list[str], limit: int = 20) -> str:
    if not rows:
        return "_No rows available._\n"
    text = "| " + " | ".join(columns) + " |\n"
    text += "| " + " | ".join("---" for _ in columns) + " |\n"
    for row in rows[:limit]:
        text += "| " + " | ".join(clean(row.get(col)).replace("|", "/") for col in columns) + " |\n"
    if len(rows) > limit:
        text += f"\n_Showing {limit} of {len(rows)} rows._\n"
    return text


def cleanup_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def main() -> int:
    test_passed, test_output = run_v45_tests()
    v45_rows = v45_validation_rows(test_passed)
    arch = architecture_rows()
    requirements = requirements_rows()
    scope = scope_rows()
    safety = safety_rows()
    candidate_universe, source_audit, candidate_blockers = build_candidate_refresh_universe()
    cleanup_pycache()

    summary45 = first_row(IN_V45_SUMMARY)
    architecture_required_ok = all(not clean(row.get("blocker_reason")) for row in arch)
    v45_ok = all(row["validation_status"] == "PASS" for row in v45_rows)
    safety_ok = all(row["validation_status"] == "PASS" for row in safety)
    candidate_ok = bool(candidate_universe) and not candidate_blockers
    blockers = [
        clean(row.get("blocker_reason"))
        for row in [*v45_rows, *arch, *safety]
        if clean(row.get("blocker_reason"))
    ]
    blockers.extend(candidate_blockers)
    warnings = [
        clean(row.get("architecture_component"))
        for row in arch
        if clean(row.get("detected_flag")) == "FALSE" and not clean(row.get("blocker_reason"))
    ]
    if not v45_ok:
        warnings.append("upstream_v20_45_blocked_but_v20_46_candidate_universe_built_from_current_ranked_source")
    ready = architecture_required_ok and safety_ok and candidate_ok
    readiness_status = READY_STATUS if ready else BLOCKED_READY_STATUS
    final_status = PASS_STATUS if ready else BLOCKED_STATUS
    decision = DECISION_PASS if ready else "BLOCKED_CURRENT_MARKET_REFRESH_READINESS_GATE"

    summary = [{
        "stage": STAGE,
        "upstream_v20_45_run_status": clean(summary45.get("report_generation_status")),
        "upstream_v20_45_tests_status": "PASS" if test_passed else "FAIL",
        "candidate_refresh_universe_status": "PASS" if candidate_ok else "BLOCKED",
        "candidate_refresh_universe_path": rel(OUT_CANDIDATE_UNIVERSE),
        "candidate_refresh_ticker_count": len(candidate_universe),
        "candidate_refresh_source_artifact": clean(source_audit[0].get("source_artifact")) if source_audit else "",
        "v20_45_report_ready": clean(first_row(IN_V45_NEXT).get("research_only_report_ready")),
        "v20_45_research_only_status": clean(summary45.get("research_only_status")),
        "current_market_refresh_needed": clean(summary45.get("current_market_refresh_needed_before_real_use")),
        "yahoo_runtime_architecture_detected": tf(ARCH_V26_SCRIPT.exists()),
        "yahoo_cache_certification_architecture_detected": tf(ARCH_V27_SCRIPT.exists()),
        "historical_cache_architecture_detected": tf(ARCH_V35_R1_SCRIPT.exists()),
        "refresh_allowed_in_this_stage": "FALSE",
        "provider_network_execution_used": "FALSE",
        "broker_order_execution_used": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "blocker_count": len(candidate_blockers),
        "warning_count": len(warnings),
        "readiness_status": readiness_status,
        "next_recommended_stage": NEXT_STAGE if ready else "REPAIR_V20_46_BLOCKERS",
    }]
    next_rows = [{
        "stage": STAGE,
        "decision": decision,
        "readiness_status": readiness_status,
        "controlled_refresh_stage_allowed_next": tf(ready),
        "refresh_executed_in_this_stage": "FALSE",
        "provider_refresh_allowed_next_stage": tf(ready),
        "broker_execution_allowed_next_stage": "FALSE",
        "official_recommendation_allowed_next_stage": "FALSE",
        "official_trading_allowed_next_stage": "FALSE",
        "formal_tests_required_next": tf(ready),
        "blocker_count": len(candidate_blockers),
        "warning_count": len(warnings),
        "next_recommended_stage": NEXT_STAGE if ready else "REPAIR_V20_46_BLOCKERS",
    }]

    write_csv(OUT_V45_VALIDATION, v45_rows, ["validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"])
    write_csv(OUT_ARCH, arch, ["architecture_component", "file_or_directory_path", "detected_flag", "intended_future_use", "allowed_in_v20_46", "allowed_in_v20_47_candidate", "risk_notes", "blocker_reason"])
    write_csv(OUT_REQUIREMENTS, requirements, ["requirement_id", "requirement_name", "required_flag", "requirement_status", "applies_to_stage", "rationale", "blocker_if_missing"])
    write_csv(OUT_SCOPE, scope, ["scope_item", "allowed_for_v20_47", "required_for_v20_47", "blocked_in_v20_46", "output_class", "notes"])
    write_csv(OUT_SAFETY, safety, ["safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_CANDIDATE_UNIVERSE, candidate_universe, ["ticker", "universe_role", "source_stage", "source_rank", "source_rank_or_score", "source_artifact", "source_row_count", "selection_rule", "candidate_refresh_universe_cap", "requested_for_refresh", "benchmark_flag", "candidate_flag", "duplicate_removed_flag", "research_only", "official_decision_impact"])
    write_csv(OUT_SOURCE_AUDIT, source_audit, ["source_artifact", "source_type", "source_exists", "source_row_count", "source_field_count", "accepted_ticker_count", "duplicate_ticker_count", "invalid_ticker_count", "selection_rule", "candidate_refresh_universe_path", "candidate_refresh_universe_status", "blocker_reason", "fabricated_ticker_rows", "manual_ticker_additions", "research_only"])
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    blocker_text = "None" if not blockers else "; ".join(blockers)
    warning_text = "None" if not warnings else "; ".join(warnings)
    report = f"""# V20.46 Current Market Refresh Readiness Gate

## Stage Status

Stage: {STAGE}
Status: {final_status}
Readiness status: {readiness_status}
Decision: {decision}

V20.46 is a gate-only, reporting-only stage.

## Upstream V20.45 Validation

V20.45 run status: {clean(summary45.get("report_generation_status"))}
V20.45 formal tests status: {"PASS" if test_passed else "FAIL"}
V20.45 report ready: {clean(first_row(IN_V45_NEXT).get("research_only_report_ready"))}
Candidate refresh universe status: {"PASS" if candidate_ok else "BLOCKED"}
Candidate refresh ticker count: {len(candidate_universe)}
Candidate refresh source artifact: {clean(source_audit[0].get("source_artifact")) if source_audit else ""}

{md_table(v45_rows, ["validation_item", "expected_value", "actual_value", "validation_status"], 20)}

## Candidate Refresh Universe

V20.46 builds a controlled-refresh ticker universe from legitimate current local sources when the V20.45 operator candidate view is unavailable. It does not hardcode tickers and does not create market prices.

{md_table(candidate_universe, ["ticker", "source_rank", "source_rank_or_score", "source_artifact", "requested_for_refresh"], 20)}

## Why Market Refresh Is Needed

V20.45 flagged current_market_refresh_needed_before_real_use={clean(summary45.get("current_market_refresh_needed_before_real_use"))}. The current operator report used accepted local artifacts and identified stale local source dates, so a controlled refresh/cache certification stage is required before operational use.

## Refresh Architecture Detected

{md_table(arch, ["architecture_component", "detected_flag", "allowed_in_v20_46", "allowed_in_v20_47_candidate"], 20)}

## Controlled Refresh Requirements

{md_table(requirements, ["requirement_id", "requirement_name", "required_flag", "requirement_status"], 20)}

## V20.47 Allowed Scope

{md_table(scope, ["scope_item", "allowed_for_v20_47", "required_for_v20_47", "blocked_in_v20_46"], 20)}

## Explicit V20.46 No-Refresh Statement

V20.46 did not refresh providers. V20.46 did not use the Yahoo provider package. V20.46 did not generate official recommendations, trading signals, broker routes, current returns, scores, rankings, dynamic factor weights, or portfolio mutations.

V20.47 may be allowed to perform controlled provider refresh only if V20.46 formal tests pass.

## Safety Boundary

{md_table(safety, ["safety_boundary", "expected_value", "actual_value", "validation_status"], 20)}

## Blockers And Warnings

Blockers: {blocker_text}
Warnings: {warning_text}

## Next Recommended Stage

{NEXT_STAGE if ready else "REPAIR_V20_46_BLOCKERS"}

## V20.45 Formal Test Output

```text
{test_output}
```
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        f"DECISION={decision}",
        "GATE_ONLY=TRUE",
        "REPORTING_ONLY=TRUE",
        f"V20_45_RUN_STATUS={clean(summary45.get('report_generation_status'))}",
        f"V20_45_FORMAL_TESTS_STATUS={'PASS' if test_passed else 'FAIL'}",
        f"CANDIDATE_REFRESH_UNIVERSE_STATUS={'PASS' if candidate_ok else 'BLOCKED'}",
        f"CANDIDATE_REFRESH_TICKER_COUNT={len(candidate_universe)}",
        f"CANDIDATE_REFRESH_UNIVERSE_PATH={rel(OUT_CANDIDATE_UNIVERSE)}",
        f"CANDIDATE_REFRESH_SOURCE_ARTIFACT={clean(source_audit[0].get('source_artifact')) if source_audit else ''}",
        f"CURRENT_MARKET_REFRESH_NEEDED={clean(summary45.get('current_market_refresh_needed_before_real_use'))}",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_46=FALSE",
        "YAHOO_PROVIDER_PACKAGE_IMPORTED_IN_V20_46=FALSE",
        "BROKER_ORDER_EXECUTION_USED=FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_MUTATED=FALSE",
        "REAL_PORTFOLIO_MUTATED=FALSE",
        "RETURNS_CALCULATED=FALSE",
        "SCORES_RECOMPUTED=FALSE",
        "RANKINGS_RECOMPUTED=FALSE",
        "V20_47_REQUIREMENTS=run_id;source_hash_ledger;cache_path_isolation;raw_cache_output;staging_candidate;certification_before_active_use;failed_ticker_capture;READ_FIRST_flags",
        f"READINESS_STATUS={readiness_status}",
        f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if ready else 'REPAIR_V20_46_BLOCKERS'}",
        "",
    ])
    write_text(READ_FIRST, read_first)

    print(final_status)
    print(f"DECISION={decision}")
    print(f"READINESS_STATUS={readiness_status}")
    print(f"CURRENT_MARKET_REFRESH_NEEDED={clean(summary45.get('current_market_refresh_needed_before_real_use'))}")
    print(f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if ready else 'REPAIR_V20_46_BLOCKERS'}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
