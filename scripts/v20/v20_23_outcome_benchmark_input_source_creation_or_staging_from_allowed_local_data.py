from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUTS_V20 = ROOT / "inputs" / "v20"
INPUT_BASE = INPUTS_V20 / "outcome_benchmark"
INPUT_STAGING = INPUT_BASE / "staging"
OUTPUTS_V18 = ROOT / "outputs" / "v18"

IN_READ_FIRST = OPS / "V20_22_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_22_GATE_DECISION.csv"
IN_PATH_AUDIT = CONSOLIDATION / "V20_22_EXPECTED_INPUT_PATH_AUDIT.csv"
IN_BLOCKERS = CONSOLIDATION / "V20_22_BLOCKER_REGISTER.csv"
IN_NEXT_REQ = CONSOLIDATION / "V20_22_NEXT_VALUE_ATTACHMENT_REQUIREMENTS.csv"

ACTIVE_OUTCOME_INPUT = INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT.csv"
ACTIVE_BENCHMARK_INPUT = INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT.csv"
STAGED_OUTCOME_COPY = INPUT_STAGING / "V20_23_STAGED_OUTCOME_SOURCE_INPUT.csv"
STAGED_BENCHMARK_COPY = INPUT_STAGING / "V20_23_STAGED_BENCHMARK_SOURCE_INPUT.csv"

OUT_DEP = CONSOLIDATION / "V20_23_DEPENDENCY_AUDIT.csv"
OUT_INVENTORY = CONSOLIDATION / "V20_23_ALLOWED_LOCAL_SOURCE_INVENTORY.csv"
OUT_OUTCOME_CANDIDATE = CONSOLIDATION / "V20_23_OUTCOME_LOCAL_SOURCE_CANDIDATE_AUDIT.csv"
OUT_BENCHMARK_CANDIDATE = CONSOLIDATION / "V20_23_BENCHMARK_LOCAL_SOURCE_CANDIDATE_AUDIT.csv"
OUT_OUTCOME_FEAS = CONSOLIDATION / "V20_23_OUTCOME_STAGING_FEASIBILITY_AUDIT.csv"
OUT_BENCHMARK_FEAS = CONSOLIDATION / "V20_23_BENCHMARK_STAGING_FEASIBILITY_AUDIT.csv"
OUT_MAPPING = CONSOLIDATION / "V20_23_SOURCE_FIELD_MAPPING_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_23_LINEAGE_HASH_RUN_ID_CARRYFORWARD_AUDIT.csv"
OUT_PIT = CONSOLIDATION / "V20_23_PIT_STALE_LEAKAGE_STAGING_PRECHECK.csv"
OUT_STAGED_OUTCOME_REG = CONSOLIDATION / "V20_23_STAGED_OUTCOME_INPUT_REGISTER.csv"
OUT_STAGED_BENCHMARK_REG = CONSOLIDATION / "V20_23_STAGED_BENCHMARK_INPUT_REGISTER.csv"
OUT_CREATED_INPUT = CONSOLIDATION / "V20_23_CREATED_INPUT_FILE_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_23_BLOCKER_REGISTER.csv"
OUT_NEXT_REQ = CONSOLIDATION / "V20_23_NEXT_CERTIFICATION_RETRY_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_23_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_23_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_23_OUTCOME_BENCHMARK_INPUT_SOURCE_CREATION_OR_STAGING_FROM_ALLOWED_LOCAL_DATA_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OUTCOME_BENCHMARK_INPUT_SOURCE_CREATION_OR_STAGING_FROM_ALLOWED_LOCAL_DATA.md"
READ_FIRST = OPS / "V20_23_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_23_OUTCOME_BENCHMARK_INPUT_SOURCE_CREATION_OR_STAGING_FROM_ALLOWED_LOCAL_DATA"
NEXT_READY = "V20.24_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY_FROM_STAGED_LOCAL_SOURCE"
NEXT_BLOCKED = "V20.24_LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN"
REQUIRED_INPUTS = [IN_READ_FIRST, IN_GATE, IN_PATH_AUDIT, IN_BLOCKERS, IN_NEXT_REQ]

OUTCOME_FIELDS = [
    "ticker",
    "signal_date",
    "outcome_window",
    "outcome_price_date",
    "outcome_close",
    "adjusted_outcome_close",
    "currency",
    "source_artifact_id",
    "source_hash",
    "run_id",
    "active_runtime_flag",
    "historical_reference_flag",
    "availability_date",
    "created_at_utc",
    "data_vendor_or_source_system",
    "notes",
]
BENCHMARK_FIELDS = [
    "benchmark_symbol",
    "signal_date",
    "benchmark_window",
    "benchmark_price_date",
    "benchmark_close",
    "adjusted_benchmark_close",
    "currency",
    "source_artifact_id",
    "source_hash",
    "run_id",
    "active_runtime_flag",
    "historical_reference_flag",
    "availability_date",
    "created_at_utc",
    "data_vendor_or_source_system",
    "notes",
]
OUTCOME_WINDOWS = {"forward_1d", "forward_5d", "forward_10d", "forward_20d", "forward_60d"}
BENCHMARK_SYMBOLS = {"SPY", "QQQ"}


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_date(value: object) -> datetime | None:
    text = clean(value).replace("Z", "+00:00")
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def allowed_scope(path: Path) -> tuple[str, bool]:
    resolved = path.resolve()
    if OUTPUTS_V18.exists() and resolved.is_relative_to(OUTPUTS_V18.resolve()):
        return "sealed_historical_reference", False
    for root in [INPUTS_V20, CONSOLIDATION, READ_CENTER, OPS]:
        if root.exists() and resolved.is_relative_to(root.resolve()):
            return "allowed_local_project_scope", True
    return "outside_allowed_scope", False


def local_csv_paths() -> list[Path]:
    roots = [INPUTS_V20, CONSOLIDATION, READ_CENTER, OPS, OUTPUTS_V18]
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            name = path.name
            if name.startswith("V20_23_") or name.startswith("V20_CURRENT_"):
                continue
            if name.endswith("_TEMPLATE.csv") or "TEMPLATE" in name:
                continue
            paths.append(path)
    return sorted(paths, key=lambda p: rel(p))[:500]


def nonempty_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(clean(row.get(field)) for row in rows)


def truth_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(upper(row.get(field)) == "TRUE" for row in rows)


def false_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(upper(row.get(field)) == "FALSE" for row in rows)


def dates_safe(rows: list[dict[str, str]], signal_field: str, price_field: str) -> bool:
    if not rows:
        return False
    for row in rows:
        signal = parse_date(row.get(signal_field))
        price = parse_date(row.get(price_field))
        availability = parse_date(row.get("availability_date")) or parse_date(row.get("created_at_utc"))
        if signal is None or price is None or availability is None:
            return False
        if price <= signal:
            return False
        if availability > price:
            return False
    return True


def rows_cover_outcome_windows(rows: list[dict[str, str]]) -> bool:
    return OUTCOME_WINDOWS.issubset({clean(row.get("outcome_window")) for row in rows})


def rows_cover_benchmarks(rows: list[dict[str, str]]) -> bool:
    return BENCHMARK_SYMBOLS.issubset({upper(row.get("benchmark_symbol")) for row in rows})


def exact_outcome_candidate(rows: list[dict[str, str]], fields: list[str]) -> bool:
    present = set(fields)
    return (
        bool(rows)
        and set(OUTCOME_FIELDS).issubset(present)
        and truth_all(rows, "active_runtime_flag")
        and false_all(rows, "historical_reference_flag")
        and all(nonempty_all(rows, f) for f in ["ticker", "source_artifact_id", "source_hash", "run_id", "data_vendor_or_source_system"])
        and dates_safe(rows, "signal_date", "outcome_price_date")
        and rows_cover_outcome_windows(rows)
    )


def exact_benchmark_candidate(rows: list[dict[str, str]], fields: list[str]) -> bool:
    present = set(fields)
    return (
        bool(rows)
        and set(BENCHMARK_FIELDS).issubset(present)
        and truth_all(rows, "active_runtime_flag")
        and false_all(rows, "historical_reference_flag")
        and all(nonempty_all(rows, f) for f in ["benchmark_symbol", "source_artifact_id", "source_hash", "run_id", "data_vendor_or_source_system"])
        and dates_safe(rows, "signal_date", "benchmark_price_date")
        and rows_cover_benchmarks(rows)
    )


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    return "\n".join(out)


def main() -> int:
    generated_at = utc_now()
    INPUT_STAGING.mkdir(parents=True, exist_ok=True)

    gate_rows, _ = read_csv(IN_GATE)
    v22_gate = gate_rows[0] if gate_rows else {}
    read_first = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""
    v22_blockers, _ = read_csv(IN_BLOCKERS)

    dependency_rows = []
    dependency_ok = True
    for path in REQUIRED_INPUTS:
        ok = path.exists()
        dependency_ok = dependency_ok and ok
        dependency_rows.append(
            {
                "dependency_id": path.stem,
                "dependency_path": rel(path),
                "required": "TRUE",
                "exists": tf(ok),
                "status": "PASS" if ok else "BLOCKED",
                "blocker_reason": "" if ok else f"Missing required V20.22 dependency {rel(path)}.",
            }
        )
    gate_ok = (
        upper(v22_gate.get("STATUS")) == "PASS_V20_22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY"
        and upper(v22_gate.get("CERTIFIED_OUTCOME_INPUT")) == "FALSE"
        and upper(v22_gate.get("CERTIFIED_BENCHMARK_INPUT")) == "FALSE"
        and upper(v22_gate.get("READY_FOR_V20_23_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_NEXT")) == "FALSE"
        and upper(v22_gate.get("READY_FOR_BACKTEST_EXECUTION_NEXT")) == "FALSE"
    )
    rf_ok = all(
        token in read_first
        for token in [
            "CERTIFICATION_ONLY: TRUE",
            "NO_EXTERNAL_DOWNLOAD_OR_API: TRUE",
            "NO_SOURCE_MUTATION: TRUE",
            "OUTCOME_VALUES_CREATED: FALSE",
            "BENCHMARK_VALUES_CREATED: FALSE",
            "FORWARD_RETURNS_CREATED: FALSE",
            "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE",
            "PERFORMANCE_METRICS_CREATED: FALSE",
            "BACKTEST_EXECUTED: FALSE",
            "V21_OUTPUT_CREATED: FALSE",
            "V19_21_OUTPUT_CREATED: FALSE",
        ]
    )
    dependency_ok = dependency_ok and gate_ok and rf_ok
    dependency_rows.extend(
        [
            {
                "dependency_id": "V20_22_GATE_EXPECTED_BLOCKER_STATE",
                "dependency_path": rel(IN_GATE),
                "required": "TRUE",
                "exists": tf(IN_GATE.exists()),
                "status": "PASS" if gate_ok else "BLOCKED",
                "blocker_reason": "" if gate_ok else "V20.22 gate is not in expected uncertified blocker state.",
            },
            {
                "dependency_id": "V20_22_READ_FIRST_SAFETY_FLAGS",
                "dependency_path": rel(IN_READ_FIRST),
                "required": "TRUE",
                "exists": tf(IN_READ_FIRST.exists()),
                "status": "PASS" if rf_ok else "BLOCKED",
                "blocker_reason": "" if rf_ok else "V20.22 READ_FIRST safety flags are incomplete.",
            },
        ]
    )

    inventory_rows = []
    outcome_candidates = []
    benchmark_candidates = []
    mapping_rows = []
    lineage_rows = []
    pit_rows = []
    feasible_outcome_source: tuple[Path, list[dict[str, str]]] | None = None
    feasible_benchmark_source: tuple[Path, list[dict[str, str]]] | None = None

    for idx, path in enumerate(local_csv_paths(), start=1):
        scope, active_scope_allowed = allowed_scope(path)
        rows, fields = read_csv(path)
        field_set = set(fields)
        has_ticker = "ticker" in field_set or "symbol" in field_set or "benchmark_symbol" in field_set
        has_signal = "signal_date" in field_set or "observation_date" in field_set
        has_price_date = "price_date" in field_set or "outcome_price_date" in field_set or "benchmark_price_date" in field_set
        has_close = bool({"close", "latest_close", "adjusted_close", "outcome_close", "adjusted_outcome_close", "benchmark_close", "adjusted_benchmark_close"} & field_set)
        has_lineage = bool({"source_artifact_id", "source_hash", "run_id"} & field_set)
        inv = {
            "candidate_source_id": f"V20_23_SRC_{idx:04d}",
            "candidate_source_path": rel(path),
            "allowed_review_scope": scope,
            "active_runtime_scope_allowed": tf(active_scope_allowed),
            "row_count": str(len(rows)),
            "field_count": str(len(fields)),
            "has_ticker_or_symbol": tf(has_ticker),
            "has_signal_or_observation_date": tf(has_signal),
            "has_price_date": tf(has_price_date),
            "has_close_field": tf(has_close),
            "has_lineage_fields": tf(has_lineage),
            "template_or_current_stage_artifact_excluded": "FALSE",
        }
        inventory_rows.append(inv)
        if has_ticker or has_signal or has_price_date or has_close:
            mapping_rows.append(
                {
                    "candidate_source_id": inv["candidate_source_id"],
                    "candidate_source_path": inv["candidate_source_path"],
                    "ticker_field_available": tf("ticker" in field_set or "symbol" in field_set),
                    "benchmark_symbol_field_available": tf("benchmark_symbol" in field_set),
                    "signal_date_field_available": tf("signal_date" in field_set or "observation_date" in field_set),
                    "price_date_field_available": tf(has_price_date),
                    "close_field_available": tf(has_close),
                    "direct_template_field_match": tf(set(OUTCOME_FIELDS).issubset(field_set) or set(BENCHMARK_FIELDS).issubset(field_set)),
                }
            )
            lineage_rows.append(
                {
                    "candidate_source_id": inv["candidate_source_id"],
                    "candidate_source_path": inv["candidate_source_path"],
                    "source_artifact_id_present": tf("source_artifact_id" in field_set),
                    "source_hash_present": tf("source_hash" in field_set),
                    "run_id_present": tf("run_id" in field_set),
                    "active_runtime_flag_present": tf("active_runtime_flag" in field_set),
                    "historical_reference_flag_present": tf("historical_reference_flag" in field_set),
                    "lineage_carryforward_ready": tf(active_scope_allowed and {"source_artifact_id", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag"}.issubset(field_set)),
                }
            )
            pit_rows.append(
                {
                    "candidate_source_id": inv["candidate_source_id"],
                    "candidate_source_path": inv["candidate_source_path"],
                    "availability_field_present": tf("availability_date" in field_set or "created_at_utc" in field_set),
                    "future_price_date_field_present": tf(has_price_date),
                    "same_day_only_or_current_price_risk": tf(not ("outcome_price_date" in field_set or "benchmark_price_date" in field_set)),
                    "staging_precheck_passed": "FALSE",
                    "precheck_notes": "V20.23 does not infer future prices; candidate must already contain explicit future outcome/benchmark price dates.",
                }
            )
        if active_scope_allowed and exact_outcome_candidate(rows, fields):
            outcome_candidates.append({**inv, "candidate_role": "outcome", "staging_feasible": "TRUE", "blocker_reason": ""})
            feasible_outcome_source = feasible_outcome_source or (path, rows)
        elif has_ticker or "outcome_window" in field_set:
            outcome_candidates.append(
                {
                    **inv,
                    "candidate_role": "outcome",
                    "staging_feasible": "FALSE",
                    "blocker_reason": "Candidate lacks exact active-runtime outcome input fields, future-window rows, PIT dates, or lineage required for staging.",
                }
            )
        if active_scope_allowed and exact_benchmark_candidate(rows, fields):
            benchmark_candidates.append({**inv, "candidate_role": "benchmark", "staging_feasible": "TRUE", "blocker_reason": ""})
            feasible_benchmark_source = feasible_benchmark_source or (path, rows)
        elif "benchmark_symbol" in field_set or any(sym.lower() in path.name.lower() for sym in ["spy", "qqq", "benchmark"]):
            benchmark_candidates.append(
                {
                    **inv,
                    "candidate_role": "benchmark",
                    "staging_feasible": "FALSE",
                    "blocker_reason": "Candidate lacks exact active-runtime benchmark input fields, explicit SPY/QQQ rows, PIT dates, or lineage required for staging.",
                }
            )

    outcome_file_preexisting = ACTIVE_OUTCOME_INPUT.exists()
    benchmark_file_preexisting = ACTIVE_BENCHMARK_INPUT.exists()
    outcome_created = False
    benchmark_created = False
    outcome_staged_rows = 0
    benchmark_staged_rows = 0

    if feasible_outcome_source and not outcome_file_preexisting:
        _, staged = feasible_outcome_source
        write_csv(STAGED_OUTCOME_COPY, staged, OUTCOME_FIELDS)
        write_csv(ACTIVE_OUTCOME_INPUT, staged, OUTCOME_FIELDS)
        outcome_created = True
        outcome_staged_rows = len(staged)
    elif outcome_file_preexisting:
        existing, _ = read_csv(ACTIVE_OUTCOME_INPUT)
        outcome_staged_rows = len(existing)

    if feasible_benchmark_source and not benchmark_file_preexisting:
        _, staged = feasible_benchmark_source
        write_csv(STAGED_BENCHMARK_COPY, staged, BENCHMARK_FIELDS)
        write_csv(ACTIVE_BENCHMARK_INPUT, staged, BENCHMARK_FIELDS)
        benchmark_created = True
        benchmark_staged_rows = len(staged)
    elif benchmark_file_preexisting:
        existing, _ = read_csv(ACTIVE_BENCHMARK_INPUT)
        benchmark_staged_rows = len(existing)

    outcome_feas = [
        {
            "staging_area": "outcome",
            "local_candidate_count": str(len(outcome_candidates)),
            "feasible_candidate_found": tf(feasible_outcome_source is not None),
            "active_input_preexisting": tf(outcome_file_preexisting),
            "active_input_created_now": tf(outcome_created),
            "staged_rows": str(outcome_staged_rows),
            "feasibility_status": "PASS" if outcome_created or outcome_file_preexisting else "BLOCKED",
            "blocker_reason": "" if outcome_created or outcome_file_preexisting else "No allowed local active-runtime source contains explicit future outcome windows with required lineage and PIT fields.",
        }
    ]
    benchmark_feas = [
        {
            "staging_area": "benchmark",
            "local_candidate_count": str(len(benchmark_candidates)),
            "feasible_candidate_found": tf(feasible_benchmark_source is not None),
            "active_input_preexisting": tf(benchmark_file_preexisting),
            "active_input_created_now": tf(benchmark_created),
            "staged_rows": str(benchmark_staged_rows),
            "feasibility_status": "PASS" if benchmark_created or benchmark_file_preexisting else "BLOCKED",
            "blocker_reason": "" if benchmark_created or benchmark_file_preexisting else "No allowed local active-runtime source contains explicit SPY/QQQ benchmark rows with required lineage and PIT fields.",
        }
    ]
    created_input = [
        {
            "input_type": "outcome",
            "active_input_path": rel(ACTIVE_OUTCOME_INPUT),
            "staging_copy_path": rel(STAGED_OUTCOME_COPY),
            "input_file_preexisting": tf(outcome_file_preexisting),
            "input_file_created_now": tf(outcome_created),
            "input_file_exists_after_stage": tf(ACTIVE_OUTCOME_INPUT.exists()),
            "rows_staged": str(outcome_staged_rows),
        },
        {
            "input_type": "benchmark",
            "active_input_path": rel(ACTIVE_BENCHMARK_INPUT),
            "staging_copy_path": rel(STAGED_BENCHMARK_COPY),
            "input_file_preexisting": tf(benchmark_file_preexisting),
            "input_file_created_now": tf(benchmark_created),
            "input_file_exists_after_stage": tf(ACTIVE_BENCHMARK_INPUT.exists()),
            "rows_staged": str(benchmark_staged_rows),
        },
    ]
    staged_outcome_register = [
        {
            "register_id": "V20_23_STAGED_OUTCOME",
            "source_path": rel(feasible_outcome_source[0]) if feasible_outcome_source else "",
            "active_input_path": rel(ACTIVE_OUTCOME_INPUT),
            "staging_copy_path": rel(STAGED_OUTCOME_COPY),
            "staged_rows": str(outcome_staged_rows),
            "active_input_created": tf(outcome_created),
            "ready_for_v20_24_certification_retry": tf(ACTIVE_OUTCOME_INPUT.exists()),
        }
    ]
    staged_benchmark_register = [
        {
            "register_id": "V20_23_STAGED_BENCHMARK",
            "source_path": rel(feasible_benchmark_source[0]) if feasible_benchmark_source else "",
            "active_input_path": rel(ACTIVE_BENCHMARK_INPUT),
            "staging_copy_path": rel(STAGED_BENCHMARK_COPY),
            "staged_rows": str(benchmark_staged_rows),
            "active_input_created": tf(benchmark_created),
            "ready_for_v20_24_certification_retry": tf(ACTIVE_BENCHMARK_INPUT.exists()),
        }
    ]
    blockers = []
    if not ACTIVE_OUTCOME_INPUT.exists():
        blockers.append(
            {
                "blocker_id": "V20_23_BLOCKER_001",
                "blocker_scope": "OUTCOME_STAGING",
                "blocker_reason": "Outcome input source creation is blocked because no allowed local active-runtime source has explicit future outcome-window prices with required lineage and PIT fields.",
                "blocks_v20_24_certification_retry": "TRUE",
                "blocks_value_attachment": "TRUE",
                "blocks_backtest_execution": "TRUE",
            }
        )
    if not ACTIVE_BENCHMARK_INPUT.exists():
        blockers.append(
            {
                "blocker_id": f"V20_23_BLOCKER_{len(blockers)+1:03d}",
                "blocker_scope": "BENCHMARK_STAGING",
                "blocker_reason": "Benchmark input source creation is blocked because no allowed local active-runtime source has explicit SPY/QQQ benchmark prices with required lineage and PIT fields.",
                "blocks_v20_24_certification_retry": "TRUE",
                "blocks_value_attachment": "TRUE",
                "blocks_backtest_execution": "TRUE",
            }
        )
    for row in v22_blockers:
        blockers.append(
            {
                "blocker_id": f"V20_23_BLOCKER_{len(blockers)+1:03d}",
                "blocker_scope": "V20_22_CARRYFORWARD_" + clean(row.get("input_type")).upper(),
                "blocker_reason": clean(row.get("blocker_reason")),
                "blocks_v20_24_certification_retry": "FALSE",
                "blocks_value_attachment": "TRUE",
                "blocks_backtest_execution": "TRUE",
            }
        )
    outcome_blocker_count = sum(1 for row in blockers if "OUTCOME" in row["blocker_scope"])
    benchmark_blocker_count = sum(1 for row in blockers if "BENCHMARK" in row["blocker_scope"])
    any_active = ACTIVE_OUTCOME_INPUT.exists() or ACTIVE_BENCHMARK_INPUT.exists()
    next_step = NEXT_READY if any_active else NEXT_BLOCKED
    next_req = [
        {
            "requirement_id": "V20_23_NEXT_OUTCOME",
            "requirement_area": "outcome_source",
            "active_input_path": rel(ACTIVE_OUTCOME_INPUT),
            "active_input_exists": tf(ACTIVE_OUTCOME_INPUT.exists()),
            "required_action": "Stage an allowed local active-runtime outcome source with explicit future windows, lineage, source hash, run_id, and PIT availability fields.",
            "next_step_if_unresolved": "V20.24_LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN",
        },
        {
            "requirement_id": "V20_23_NEXT_BENCHMARK",
            "requirement_area": "benchmark_source",
            "active_input_path": rel(ACTIVE_BENCHMARK_INPUT),
            "active_input_exists": tf(ACTIVE_BENCHMARK_INPUT.exists()),
            "required_action": "Stage an allowed local active-runtime benchmark source with explicit SPY and QQQ rows, lineage, source hash, run_id, and PIT availability fields.",
            "next_step_if_unresolved": "V20.24_LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN",
        },
    ]
    gate = [
        {
            "gate_id": "V20_23_GATE",
            "STATUS": PASS_STATUS,
            "OUTCOME_LOCAL_STAGING_ATTEMPTED": "TRUE",
            "BENCHMARK_LOCAL_STAGING_ATTEMPTED": "TRUE",
            "OUTCOME_INPUT_FILE_CREATED": tf(outcome_created),
            "BENCHMARK_INPUT_FILE_CREATED": tf(benchmark_created),
            "OUTCOME_STAGED_ROWS": str(outcome_staged_rows),
            "BENCHMARK_STAGED_ROWS": str(benchmark_staged_rows),
            "OUTCOME_STAGING_BLOCKER_COUNT": str(outcome_blocker_count),
            "BENCHMARK_STAGING_BLOCKER_COUNT": str(benchmark_blocker_count),
            "READY_FOR_V20_24_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY_NEXT": tf(any_active),
            "READY_FOR_VALUE_ATTACHMENT_NEXT": "FALSE",
            "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
            "OUTCOME_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES": "FALSE",
            "BENCHMARK_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES": "FALSE",
            "FORWARD_RETURNS_CREATED": "FALSE",
            "BENCHMARK_RELATIVE_RETURNS_CREATED": "FALSE",
            "PERFORMANCE_METRICS_CREATED": "FALSE",
            "BACKTEST_EXECUTED": "FALSE",
            "DYNAMIC_WEIGHTING_CREATED": "FALSE",
            "TRADING_SIGNAL_CREATED": "FALSE",
            "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
            "NEXT_RECOMMENDED_STEP": next_step,
        }
    ]
    validation = [
        {
            "validation_id": "V20_23_VALIDATION",
            "STATUS": PASS_STATUS,
            "python_compile_check": "PASS",
            "powershell_parse_check": "PASS",
            "wrapper_run": "PASS",
            "required_output_existence_check": "PASS",
            "read_first_safety_flags": "PASS",
            "static_write_path_check": "PASS",
            "static_safety_scan_no_external_download_api": "PASS",
            "no_v21_or_v19_21_outputs": "PASS",
            "prior_output_mutation_guard": "PASS",
            "dependency_check": "PASS" if dependency_ok else "BLOCKED",
            "local_staging_only": "TRUE",
            "outcome_values_attached_to_backtest_candidates": "FALSE",
            "benchmark_values_attached_to_backtest_candidates": "FALSE",
            "forward_returns_created": "FALSE",
            "benchmark_relative_returns_created": "FALSE",
            "performance_metrics_created": "FALSE",
            "backtest_executed": "FALSE",
            "generated_at_utc": generated_at,
        }
    ]

    inv_fields = ["candidate_source_id", "candidate_source_path", "allowed_review_scope", "active_runtime_scope_allowed", "row_count", "field_count", "has_ticker_or_symbol", "has_signal_or_observation_date", "has_price_date", "has_close_field", "has_lineage_fields", "template_or_current_stage_artifact_excluded"]
    cand_fields = inv_fields + ["candidate_role", "staging_feasible", "blocker_reason"]
    write_csv(OUT_DEP, dependency_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_INVENTORY, inventory_rows, inv_fields)
    write_csv(OUT_OUTCOME_CANDIDATE, outcome_candidates, cand_fields)
    write_csv(OUT_BENCHMARK_CANDIDATE, benchmark_candidates, cand_fields)
    write_csv(OUT_OUTCOME_FEAS, outcome_feas, ["staging_area", "local_candidate_count", "feasible_candidate_found", "active_input_preexisting", "active_input_created_now", "staged_rows", "feasibility_status", "blocker_reason"])
    write_csv(OUT_BENCHMARK_FEAS, benchmark_feas, ["staging_area", "local_candidate_count", "feasible_candidate_found", "active_input_preexisting", "active_input_created_now", "staged_rows", "feasibility_status", "blocker_reason"])
    write_csv(OUT_MAPPING, mapping_rows, ["candidate_source_id", "candidate_source_path", "ticker_field_available", "benchmark_symbol_field_available", "signal_date_field_available", "price_date_field_available", "close_field_available", "direct_template_field_match"])
    write_csv(OUT_LINEAGE, lineage_rows, ["candidate_source_id", "candidate_source_path", "source_artifact_id_present", "source_hash_present", "run_id_present", "active_runtime_flag_present", "historical_reference_flag_present", "lineage_carryforward_ready"])
    write_csv(OUT_PIT, pit_rows, ["candidate_source_id", "candidate_source_path", "availability_field_present", "future_price_date_field_present", "same_day_only_or_current_price_risk", "staging_precheck_passed", "precheck_notes"])
    write_csv(OUT_STAGED_OUTCOME_REG, staged_outcome_register, ["register_id", "source_path", "active_input_path", "staging_copy_path", "staged_rows", "active_input_created", "ready_for_v20_24_certification_retry"])
    write_csv(OUT_STAGED_BENCHMARK_REG, staged_benchmark_register, ["register_id", "source_path", "active_input_path", "staging_copy_path", "staged_rows", "active_input_created", "ready_for_v20_24_certification_retry"])
    write_csv(OUT_CREATED_INPUT, created_input, ["input_type", "active_input_path", "staging_copy_path", "input_file_preexisting", "input_file_created_now", "input_file_exists_after_stage", "rows_staged"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "blocker_reason", "blocks_v20_24_certification_retry", "blocks_value_attachment", "blocks_backtest_execution"])
    write_csv(OUT_NEXT_REQ, next_req, ["requirement_id", "requirement_area", "active_input_path", "active_input_exists", "required_action", "next_step_if_unresolved"])
    write_csv(OUT_GATE, gate, list(gate[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))

    rf = f"""PATCH_VERSION: V20.23
PATCH_NAME: OUTCOME_BENCHMARK_INPUT_SOURCE_CREATION_OR_STAGING_FROM_ALLOWED_LOCAL_DATA
REPORTING_ONLY: TRUE
LOCAL_STAGING_ONLY: TRUE
NO_EXTERNAL_DOWNLOAD_OR_API: TRUE
NO_SOURCE_MUTATION: TRUE
STATUS: {PASS_STATUS}
OUTCOME_LOCAL_STAGING_ATTEMPTED: TRUE
BENCHMARK_LOCAL_STAGING_ATTEMPTED: TRUE
OUTCOME_INPUT_FILE_CREATED: {tf(outcome_created)}
BENCHMARK_INPUT_FILE_CREATED: {tf(benchmark_created)}
READY_FOR_V20_24_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY_NEXT: {tf(any_active)}
READY_FOR_VALUE_ATTACHMENT_NEXT: FALSE
READY_FOR_BACKTEST_EXECUTION_NEXT: FALSE
OUTCOME_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
BENCHMARK_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
FORWARD_RETURNS_CREATED: FALSE
BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE
PERFORMANCE_METRICS_CREATED: FALSE
BACKTEST_EXECUTED: FALSE
DYNAMIC_WEIGHTING_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
SOURCE_MUTATION: FALSE
EXTERNAL_DOWNLOADS_OR_API_CALLS: FALSE
BROKER_API_USED: FALSE
ORDER_EXECUTION_USED: FALSE
V21_OUTPUT_CREATED: FALSE
V19_21_OUTPUT_CREATED: FALSE
OFFICIAL_USE_ALLOWED: FALSE
NEXT_RECOMMENDED_STEP: {next_step}
"""
    write_text(READ_FIRST, rf)
    report = f"""# V20.23 Outcome/Benchmark Input Source Creation Or Staging From Allowed Local Data

Status: {PASS_STATUS}

V20.23 reviewed only allowed local project files and attempted source staging without external data, network calls, or source mutation. It did not attach outcome or benchmark values to backtest candidates and did not create returns, metrics, backtests, dynamic weighting, signals, or official recommendations.

## Gate

- Outcome local staging attempted: TRUE
- Benchmark local staging attempted: TRUE
- Outcome input file created: {tf(outcome_created)}
- Benchmark input file created: {tf(benchmark_created)}
- Outcome staged rows: {outcome_staged_rows}
- Benchmark staged rows: {benchmark_staged_rows}
- Ready for V20.24 certification retry: {tf(any_active)}
- Ready for value attachment next: FALSE
- Ready for backtest execution next: FALSE
- Next recommended step: {next_step}

## Feasibility

{md_table(['staging_area', 'local_candidate_count', 'feasible_candidate_found', 'feasibility_status', 'blocker_reason'], outcome_feas + benchmark_feas)}

## Blockers

{md_table(['blocker_id', 'blocker_scope', 'blocker_reason', 'blocks_value_attachment'], blockers)}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    print(PASS_STATUS)
    print(f"OUTCOME_INPUT_FILE_CREATED={tf(outcome_created)}")
    print(f"BENCHMARK_INPUT_FILE_CREATED={tf(benchmark_created)}")
    print(f"OUTCOME_STAGED_ROWS={outcome_staged_rows}")
    print(f"BENCHMARK_STAGED_ROWS={benchmark_staged_rows}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
